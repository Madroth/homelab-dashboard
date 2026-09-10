import collections
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import time
from services import container_catalog

DAEMON_LOG_FILE = '/home/linuxbox/projects/media-curator/daemon.log'

# get_status() is called independently by both pages/home.py and pages/lab_health.py, each on
# its own 15s poll, for every connected client -- with no caching that meant redundant
# `docker ps`/`docker stats`/`systemctl` subprocess spawns piling up whenever those polls
# landed close together, adding avoidable load on top of whatever else the host is doing
# (e.g. an actively-played Minecraft server routinely wants a full CPU core). An 8s TTL
# de-duplicates calls that land within the same window without making alerts noticeably stale.
_STATUS_CACHE_TTL = 8.0
_status_cache = {'time': 0.0, 'status': None}


def get_status() -> dict:
    now = time.time()
    if _status_cache['status'] is not None and (now - _status_cache['time']) < _STATUS_CACHE_TTL:
        return _status_cache['status']

    status = {'defcon': [], 'containers': [], 'disk': {}, 'memory': {},
              'containers_error': None, 'read_at': now}

    try:
        # Check the mount before reading it. /mnt/Multimedia exists as a plain
        # directory when the NAS is unmounted, so disk_usage() would silently
        # report the root SSD's free space as if it were the NAS -- a failed
        # mount showed up here as a healthy number for three days.
        if not os.path.ismount('/mnt/Multimedia'):
            status['disk'] = {'error': '/mnt/Multimedia is NOT MOUNTED'}
            status['defcon'].append('MOUNT_DOWN: /mnt/Multimedia is not mounted — the NAS is unreachable!')
        else:
            total, used, free = shutil.disk_usage('/mnt/Multimedia')
            free_pct = (free / total) * 100
            status['disk'] = {'total': total, 'used': used, 'free': free, 'free_pct': free_pct}
            if free_pct < 5.0:
                status['defcon'].append('STORAGE_CRITICAL: /mnt/Multimedia is below 5% free space!')
    except Exception:
        status['disk'] = {'error': 'Could not read /mnt/Multimedia'}

    try:
        docker_ps = subprocess.check_output(['docker', 'ps', '-a', '--format', '{{json .}}'], text=True)
        containers = [json.loads(line) for line in docker_ps.strip().split('\n') if line]
        status['containers'] = containers

        gluetun = next((c for c in containers if 'gluetun' in c['Names']), None)
        if gluetun and ('unhealthy' in gluetun.get('Status', '').lower()
                         or 'exited' in gluetun.get('Status', '').lower()):
            status['defcon'].append('VPN_DOWN: Gluetun tunnel has collapsed or failed authentication!')

        try:
            plex_stats = subprocess.check_output(
                ['docker', 'stats', '--no-stream', '--format', '{{json .}}', 'plex'], text=True)
            if plex_stats.strip():
                plex_data = json.loads(plex_stats.strip())
                status['memory']['plex'] = plex_data.get('MemUsage', 'Unknown')
        except Exception:
            pass

    except Exception as e:
        # Keep the reason. An empty container list and "docker did not answer" are
        # different answers, and a caller that only sees [] cannot tell an idle host
        # from a broken daemon -- so it would render one as the other, forever.
        status['containers'] = []
        status['containers_error'] = f'{type(e).__name__}: {e}'
        status['defcon'].append('DOCKER_UNREACHABLE: could not read container state — '
                                f'{type(e).__name__}: {e}')

    try:
        daemon_status = subprocess.run(
            ['systemctl', '--user', 'is-active', 'media-curator'],
            capture_output=True, text=True).stdout.strip()
        status['daemon_active'] = (daemon_status == 'active')
        if daemon_status != 'active':
            status['defcon'].append('DAEMON_CRASH: media-curator.service is not active!')
    except Exception as e:
        # This used to set daemon_active False and stop, which suppressed the banner:
        # the daemon read as dead AND the alert that says so went missing. Not knowing
        # is its own alert -- the one thing it must never do is go quiet.
        status['daemon_active'] = False
        status['defcon'].append('DAEMON_UNKNOWN: could not ask systemd about '
                                f'media-curator.service — {type(e).__name__}: {e}')

    _status_cache['time'] = now
    _status_cache['status'] = status
    return status


def get_logs(tail: int = 100) -> list[str]:
    if not os.path.exists(DAEMON_LOG_FILE):
        return []
    with open(DAEMON_LOG_FILE, 'r') as f:
        lines = f.readlines()
    return lines[-tail:]


# ---------------------------------------------------------------------------
# Lab Health: errors and units, read on demand from journald and systemd.
#
# Every reader here returns {'ok': bool, ..., 'error': str | None} rather than a
# bare list. An empty list and "the command did not run" are different answers and
# must never render the same: the whole reason this page exists is that the old
# System page reported the root SSD's free space as the NAS for three days. `ok`
# False means we could not determine, and the UI is obliged to say so.
# ---------------------------------------------------------------------------

MANAGERS = ('user', 'system')
_ERROR_CACHE = {'time': 0.0, 'data': None, 'key': None}
_ERROR_CACHE_TTL = 20.0


def _run(cmd: list[str], timeout: int = 20, merge_stderr: bool = False) -> tuple[bool, str]:
    """(ok, output). Never raises -- a failed read is data, not an exception.

    merge_stderr is for `docker logs`, which splits a container's output across both
    streams: reading only stdout silently loses half the log for most images.
    """
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if merge_stderr and out.returncode == 0:
            return True, (out.stdout or '') + (out.stderr or '')
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as e:
        return False, f'{type(e).__name__}: {e}'
    if out.returncode != 0 and not out.stdout.strip():
        return False, (out.stderr or '').strip() or f'exit {out.returncode}'
    return True, out.stdout


def _journal_message(raw) -> str:
    """journald MESSAGE is usually a string but is a byte array when the line was
    not valid UTF-8. Render both rather than dropping the entry."""
    if isinstance(raw, list):
        try:
            return bytes(raw).decode('utf-8', 'replace')
        except (ValueError, TypeError):
            return str(raw)
    return raw if isinstance(raw, str) else ''


_PRIORITY_NAMES = {'0': 'emergency', '1': 'alert', '2': 'critical', '3': 'error',
                   '4': 'warning', '5': 'notice', '6': 'info', '7': 'debug'}


def get_failed_units() -> dict:
    """Units in a failed state across both managers -- the cheapest, highest-yield
    check there is: it covers every unit that will ever exist, including the ones
    nobody remembered to declare."""
    units, errors = [], []
    for manager in MANAGERS:
        ok, out = _run(['systemctl', f'--{manager}', 'list-units', '--state=failed',
                        '--output=json', '--no-pager'])
        if not ok:
            errors.append(f'{manager}: {out}')
            continue
        try:
            rows = json.loads(out or '[]')
        except json.JSONDecodeError as e:
            errors.append(f'{manager}: unreadable systemctl output ({e})')
            continue
        for row in rows:
            units.append({'unit': row.get('unit', ''), 'manager': manager,
                          'description': row.get('description', ''),
                          'active': row.get('active', ''), 'sub': row.get('sub', '')})
    return {'ok': not errors, 'units': units,
            'error': '; '.join(errors) if errors else None}


def get_unit_detail(unit: str, manager: str = 'user', log_lines: int = 40) -> dict:
    """Everything needed to act on one unit: its properties, and its own log tail."""
    if manager not in MANAGERS:
        return {'ok': False, 'error': f'unknown manager {manager!r}', 'props': {}, 'logs': []}

    props: dict[str, str] = {}
    ok, out = _run(['systemctl', f'--{manager}', 'show', unit,
                    '-p', 'Description', '-p', 'ActiveState', '-p', 'SubState',
                    '-p', 'Result', '-p', 'NRestarts', '-p', 'ExecMainStatus',
                    '-p', 'ActiveEnterTimestamp', '-p', 'InactiveEnterTimestamp',
                    '-p', 'FragmentPath', '-p', 'TriggersUnit', '--no-pager'])
    if not ok:
        return {'ok': False, 'error': out, 'props': {}, 'logs': []}
    for line in out.splitlines():
        if '=' in line:
            k, _, v = line.partition('=')
            props[k] = v

    logs, log_error = [], None
    ok, out = _run(['journalctl', f'--{manager}', '-u', unit, '-n', str(log_lines),
                    '--no-pager', '-o', 'short-iso'])
    if ok:
        logs = out.splitlines()
    else:
        log_error = out

    return {'ok': True, 'error': None, 'unit': unit, 'manager': manager,
            'props': props, 'logs': logs, 'log_error': log_error}


def get_units(manager: str = 'user') -> dict:
    """Loaded services and timers for one manager, newest failure first. Deliberately
    not filtered to a hand-kept list -- a unit nobody declared is exactly the kind
    this lab loses track of."""
    rows, errors = [], []
    for kind in ('service', 'timer'):
        ok, out = _run(['systemctl', f'--{manager}', 'list-units', f'--type={kind}',
                        '--all', '--output=json', '--no-pager'])
        if not ok:
            errors.append(f'{kind}: {out}')
            continue
        try:
            parsed = json.loads(out or '[]')
        except json.JSONDecodeError as e:
            errors.append(f'{kind}: unreadable systemctl output ({e})')
            continue
        for row in parsed:
            active = row.get('active', '')
            rows.append({'unit': row.get('unit', ''), 'kind': kind, 'manager': manager,
                         'description': row.get('description', ''), 'active': active,
                         'sub': row.get('sub', ''),
                         'failed': active == 'failed'})
    rows.sort(key=lambda r: (not r['failed'], r['unit']))
    return {'ok': not errors, 'units': rows, 'read_at': time.time(),
            'error': '; '.join(errors) if errors else None}


# Numbers that vary between otherwise-identical errors: pids, addresses, byte counts,
# timeouts. Exact-string grouping never folds those, so fifty OOM kills stay fifty rows.
_NOISE_PATTERNS = [
    (re.compile(r'\b0x[0-9a-fA-F]+\b'), '0xN'),   # addresses
    (re.compile(r'\[\d+\]'), '[N]'),              # bracketed pids
    # No trailing \b: a unit suffix ("after 90s", "in 180 seconds") must normalise too,
    # while the leading \b still protects identifiers like GPC1 and nvme0n1.
    (re.compile(r'\b\d{2,}'), 'N'),
]


def _normalise_message(message: str) -> str:
    """A grouping key, never displayed. Single digits are left alone deliberately --
    'disk 1' and 'disk 2' are different subjects, while a pid or a byte count is the
    same error wearing a different number."""
    for pattern, replacement in _NOISE_PATTERNS:
        message = pattern.sub(replacement, message)
    return message


def _group_key(entry: dict) -> tuple:
    """journald stamps a stable 128-bit MESSAGE_ID on catalogued messages -- when one
    is there it is exact and free. Only about a fifth of this host's error entries
    carry one, so the normalised text carries the rest."""
    identity = entry.get('message_id') or _normalise_message(entry['message'])
    return (entry['source'], entry['origin'], identity)


def _collapse(entries: list[dict]) -> list[dict]:
    """Fold repeats into one row carrying a count. The NAS reconnect logs the same
    sentence every few minutes -- fourteen near-identical rows push everything else off
    the screen and say nothing the first one didn't. The row shows the newest actual
    message; only the grouping is normalised."""
    grouped: dict[tuple, dict] = {}
    for e in entries:
        key = _group_key(e)
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = dict(e, count=1, first_at=e['at'])
            continue
        existing['count'] += 1
        existing['first_at'] = min(existing['first_at'], e['at'])
        if e['at'] > existing['at']:
            existing['at'] = e['at']
            existing['message'] = e['message']   # show the newest real text, not the key
    return sorted(grouped.values(), key=lambda e: e['at'], reverse=True)


def get_errors(hours: int = 24, limit: int = 400) -> dict:
    """The error stream: journald errors from both managers, every failed unit, and
    containers that died non-zero -- merged, collapsed and newest first.

    Sources are reported individually: one unreadable source must not silently
    shrink the list into a calmer-looking one.
    """
    now = time.time()
    key = (hours, limit)
    if (_ERROR_CACHE['data'] is not None and _ERROR_CACHE['key'] == key
            and (now - _ERROR_CACHE['time']) < _ERROR_CACHE_TTL):
        return _ERROR_CACHE['data']

    entries: list[dict] = []
    sources: dict[str, dict] = {}

    for manager in MANAGERS:
        ok, out = _run(['journalctl', f'--{manager}', '-p', 'err',
                        '--since', f'{hours} hours ago', '-o', 'json', '--no-pager'],
                       timeout=30)
        sources[f'journal-{manager}'] = {'ok': ok, 'error': None if ok else out}
        if not ok:
            continue
        for line in out.splitlines():
            if not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            message = _journal_message(d.get('MESSAGE'))
            if not message:
                continue
            try:
                at = int(d.get('__REALTIME_TIMESTAMP', 0)) / 1_000_000
            except (TypeError, ValueError):
                at = 0.0
            origin = (d.get('_SYSTEMD_UNIT') or d.get('SYSLOG_IDENTIFIER')
                      or d.get('_COMM') or 'unknown')
            entries.append({
                'source': f'journal-{manager}', 'origin': origin, 'message': message,
                'at': at, 'severity': _PRIORITY_NAMES.get(str(d.get('PRIORITY')), 'error'),
                'message_id': d.get('MESSAGE_ID'),
                'detail': {'manager': manager, 'pid': d.get('_PID'),
                           'identifier': d.get('SYSLOG_IDENTIFIER'),
                           'unit': d.get('_SYSTEMD_UNIT')},
            })

    failed = get_failed_units()
    sources['failed-units'] = {'ok': failed['ok'], 'error': failed['error']}
    for u in failed['units']:
        entries.append({
            'source': 'unit', 'origin': u['unit'], 'at': now, 'severity': 'critical',
            'message': f"{u['unit']} is in a failed state ({u['sub']}) — {u['description']}",
            'detail': {'manager': u['manager'], 'unit': u['unit']},
        })

    ok, out = _run(['docker', 'ps', '-a', '--format', '{{json .}}'])
    sources['containers'] = {'ok': ok, 'error': None if ok else out}
    if ok:
        for line in out.strip().splitlines():
            if not line.strip():
                continue
            try:
                c = json.loads(line)
            except json.JSONDecodeError:
                continue
            status = c.get('Status', '')
            # "Exited (137) 3 weeks ago" -- a zero exit is a job that finished, not a
            # failure, and this lab has several of those by design.
            match = re.search(r'Exited \((\d+)\)', status)
            if match and match.group(1) != '0':
                entries.append({
                    'source': 'container', 'origin': c.get('Names', ''), 'at': 0.0,
                    'severity': 'error',
                    'message': f"container {c.get('Names', '')} exited with code {match.group(1)} — {status}",
                    'detail': {'image': c.get('Image', ''), 'status': status,
                               'container': c.get('Names', '')},
                })

    collapsed = _collapse(entries)[:limit]
    data = {'ok': all(s['ok'] for s in sources.values()), 'entries': collapsed,
            'sources': sources, 'read_at': now,
            'error': '; '.join(f"{n}: {s['error']}" for n, s in sources.items() if s['error']) or None}
    _ERROR_CACHE.update(time=now, data=data, key=key)
    return data


# ---------------------------------------------------------------------------
# Lab Health F2/F3: container detail and host resources.
#
# Same contract as the readers above -- {'ok': bool, ..., 'error': str|None} -- and
# the same reason. A resource panel that renders 0% because the file could not be
# read is worse than one that says it does not know.
# ---------------------------------------------------------------------------

def _read_proc(path: str) -> tuple[bool, str]:
    try:
        with open(path) as f:
            return True, f.read()
    except OSError as e:
        return False, f'{type(e).__name__}: {e}'


def _psi(path: str) -> dict:
    """Kernel pressure-stall info: the share of time work was stalled waiting for a
    resource. This is how you answer 'is the machine actually struggling' without
    keeping any history -- the kernel already computes the averages."""
    ok, raw = _read_proc(path)
    if not ok:
        return {'ok': False, 'error': raw}
    out = {'ok': True, 'error': None}
    for line in raw.splitlines():
        parts = line.split()
        if not parts:
            continue
        scope = parts[0]  # 'some' | 'full'
        for token in parts[1:]:
            if '=' in token:
                k, _, v = token.partition('=')
                if k.startswith('avg'):
                    try:
                        out[f'{scope}_{k}'] = float(v)
                    except ValueError:
                        pass
    return out


def get_host_resources() -> dict:
    """CPU, memory, disks and temperature, each reporting its own readability."""
    res: dict = {'ok': True, 'error': None, 'read_at': time.time()}

    ok, raw = _read_proc('/proc/loadavg')
    if ok:
        parts = raw.split()
        try:
            res['cpu'] = {'ok': True, 'error': None, 'cores': os.cpu_count() or 1,
                          'load': [float(parts[0]), float(parts[1]), float(parts[2])],
                          'psi': _psi('/proc/pressure/cpu')}
        except (IndexError, ValueError) as e:
            res['cpu'] = {'ok': False, 'error': f'unreadable /proc/loadavg ({e})'}
    else:
        res['cpu'] = {'ok': False, 'error': raw}

    ok, raw = _read_proc('/proc/meminfo')
    if ok:
        fields = {}
        for line in raw.splitlines():
            k, _, v = line.partition(':')
            fields[k.strip()] = v.strip()

        def kb(name):
            try:
                return int(fields.get(name, '0').split()[0]) * 1024
            except (ValueError, IndexError):
                return None

        total, available = kb('MemTotal'), kb('MemAvailable')
        swap_total, swap_free = kb('SwapTotal'), kb('SwapFree')
        res['memory'] = {
            'ok': total is not None and available is not None,
            'error': None if total else 'MemTotal/MemAvailable missing from /proc/meminfo',
            'total': total, 'available': available,
            'used': (total - available) if (total and available is not None) else None,
            'used_pct': round((total - available) / total * 100, 1) if (total and available is not None) else None,
            'swap_total': swap_total, 'swap_free': swap_free,
            'swap_used_pct': (round((swap_total - swap_free) / swap_total * 100, 1)
                              if swap_total else None),
            'psi': _psi('/proc/pressure/memory'),
        }
    else:
        res['memory'] = {'ok': False, 'error': raw}

    disks = []
    for label, path, must_be_mount in (('root', '/', False),
                                        ('NAS', '/mnt/Multimedia', True)):
        # Same trap as get_status()'s disk read: /mnt/Multimedia exists as a plain
        # directory when the NAS is away, and disk_usage() would happily report the
        # root SSD's numbers under the NAS's name.
        if must_be_mount and not os.path.ismount(path):
            disks.append({'label': label, 'path': path, 'ok': False,
                          'error': f'{path} is NOT MOUNTED'})
            continue
        try:
            total, used, free = shutil.disk_usage(path)
        except OSError as e:
            disks.append({'label': label, 'path': path, 'ok': False,
                          'error': f'{type(e).__name__}: {e}'})
            continue
        disks.append({'label': label, 'path': path, 'ok': True, 'error': None,
                      'total': total, 'used': used, 'free': free,
                      'used_pct': round(used / total * 100, 1) if total else None})
    res['disks'] = disks

    temps, temp_error = [], None
    try:
        import glob
        for zone in sorted(glob.glob('/sys/class/thermal/thermal_zone*')):
            ok_t, raw_t = _read_proc(os.path.join(zone, 'temp'))
            ok_n, raw_n = _read_proc(os.path.join(zone, 'type'))
            if ok_t and ok_n:
                try:
                    temps.append({'name': raw_n.strip(), 'celsius': int(raw_t.strip()) / 1000})
                except ValueError:
                    continue
    except Exception as e:
        temp_error = f'{type(e).__name__}: {e}'
    res['temps'] = {'ok': temp_error is None, 'error': temp_error, 'zones': temps}

    problems = [k for k in ('cpu', 'memory') if not res[k].get('ok')]
    if problems or any(not d['ok'] for d in disks):
        res['ok'] = False
        res['error'] = '; '.join(
            [f"{k}: {res[k].get('error')}" for k in problems]
            + [f"{d['label']}: {d['error']}" for d in disks if not d['ok']])
    _record_sample(res)
    return res


# F11. A bounded, in-process memory of recent readings: 60 samples, dropped on restart,
# never written anywhere and never queried by anything but the panel that shows it. It
# exists to answer "is this climbing?", which a bare percentage cannot. It is deliberately
# NOT a time-series store -- nothing is persisted, no history is retained across a restart,
# and no alert is ever derived from it. That line is what keeps it inside MONITORING.md's
# anti-goals rather than being the first inch of a metrics stack.
#
# Sampling is demand-driven: a sample is recorded when a page actually reads resources, so
# the window this covers depends on whether anyone had the page open, and how many tabs.
# Rather than paper over that with a fixed "over the last five minutes", every sample
# carries its own timestamp, the trend reports the span it genuinely covers, and it refuses
# to report at all when the readings are too few or too closely spaced to mean anything.
# A confident rate computed from three samples two seconds apart would be the same species
# of lie as a stale number rendered as current.
_TREND_SAMPLES = 60
_TREND_MIN_GAP = 5.0      # several open tabs polling together are one reading, not three
_TREND_MIN_SPAN = 60.0    # under a minute, "rising" is indistinguishable from noise
_TREND_MIN_POINTS = 3
_TREND_FLAT = 2.0         # percentage points; below this it is steady, not a direction

_resource_history: collections.deque = collections.deque(maxlen=_TREND_SAMPLES)

_TREND_LABELS = {'cpu': 'CPU load', 'memory': 'Memory used', 'swap': 'Swap used'}


def _sample_of(res: dict) -> dict:
    """Scalars only, and None wherever the reader failed -- a sub-reader that could not
    answer must never enter the history as a plausible zero."""
    def pct(block: dict, key: str):
        return block.get(key) if block.get('ok') else None

    cpu = res.get('cpu') or {}
    mem = res.get('memory') or {}
    load = cpu.get('load') or []
    cores = cpu.get('cores') or 1
    return {
        'at': res.get('read_at') or time.time(),
        'cpu': (load[0] / cores * 100.0) if (cpu.get('ok') and load) else None,
        'memory': pct(mem, 'used_pct'),
        'swap': pct(mem, 'swap_used_pct'),
    }


def _record_sample(res: dict) -> None:
    sample = _sample_of(res)
    if _resource_history and (sample['at'] - _resource_history[-1]['at']) < _TREND_MIN_GAP:
        return
    _resource_history.append(sample)


def resource_trend(metric: str) -> dict:
    """first -> last across however long the samples actually span, or an honest refusal.

    Never extrapolates and never smooths: it reports two real readings, the true interval
    between them, and how many samples sit in between so the caller can judge the shape.
    """
    points = [s for s in _resource_history if s.get(metric) is not None]
    label = _TREND_LABELS.get(metric, metric)
    if len(points) < _TREND_MIN_POINTS:
        return {'ok': False, 'metric': metric, 'label': label,
                'reason': f'only {len(points)} reading(s) so far — not enough to say'}

    first, last = points[0], points[-1]
    span = last['at'] - first['at']
    if span < _TREND_MIN_SPAN:
        return {'ok': False, 'metric': metric, 'label': label,
                'reason': f'readings cover only {int(span)}s — too short to call a trend'}

    delta = last[metric] - first[metric]
    direction = ('rising' if delta > _TREND_FLAT else
                 'falling' if delta < -_TREND_FLAT else 'steady')
    return {'ok': True, 'metric': metric, 'label': label, 'reason': None,
            'first': first[metric], 'last': last[metric], 'delta': delta,
            'span': span, 'samples': len(points), 'direction': direction}


def resource_window(at: float, window: float = 300.0) -> dict:
    """What the history retained around a moment -- or an honest account of why nothing.

    F10's resource half. Because the buffer is short and only fills while somebody has the
    page open, most historical errors will have no resource context at all. Saying that
    plainly beats implying the machine was calm: "no samples" and "nothing was happening"
    are different answers, and only one of them is knowable here.
    """
    lo, hi = at - window, at + window
    points = [s for s in _resource_history if lo <= s['at'] <= hi]
    if not points:
        return {'ok': False, 'samples': 0, 'metrics': {},
                'reason': 'nothing was retained for that time — readings are kept only '
                          'while this page is open, and only for the last few minutes'}
    out = {'ok': True, 'reason': None, 'samples': len(points),
           'from': points[0]['at'], 'to': points[-1]['at'], 'metrics': {}}
    for metric in ('cpu', 'memory', 'swap'):
        values = [s[metric] for s in points if s.get(metric) is not None]
        if values:
            out['metrics'][metric] = {'label': _TREND_LABELS[metric],
                                      'min': min(values), 'max': max(values)}
    return out


# F14. Reachability, and the reason it is its own reader: os.path.ismount() answers
# "is something mounted here", which is not the question. On 2026-08-22 the NAS spent an
# afternoon logging `CIFS: VFS: ... has not responded in 180 seconds` while that check
# passed the whole time, so every surface on this dashboard called it healthy. A mount
# that cannot answer is down, whatever the mount table says.
#
# Everything here is checked at the service layer rather than by ping, for the same
# reason: a host that answers ICMP while its service is dead is the failure, not the
# reassurance. QNAP2 is deliberately absent and must stay absent -- it is the off-limits
# backup vault (ADR 22) and the restic job is the only sanctioned thing that talks to it.
NAS_MOUNT = '/mnt/Multimedia'

_REACH_CACHE = {'time': 0.0, 'data': None}
_REACH_CACHE_TTL = 20.0
_PROBE_TIMEOUT = 4.0

# Named here rather than derived, so what the lab considers load-bearing is an explicit
# list somebody can argue with. Each is a real endpoint of the service, not its front door.
_ENDPOINTS = [
    ('Omega — Ollama', 'http://100.74.2.92:11434/api/tags'),
    ('ntfy', 'http://100.87.245.107:5001/v1/health'),
    ('Uptime Kuma', 'http://100.87.245.107:3001/'),
    ('Dozzle', 'http://100.87.245.107:8888/'),
]

# Tailnet peers this lab actually depends on. The tailnet also carries family laptops and
# phones; listing those here would turn a lab health page into a presence tracker, which
# is neither its job nor anybody's business.
_LAB_PEERS = {'omega', 'steamdeck', 'kitchen'}


def probe_mount(path: str = NAS_MOUNT, timeout: float = 5.0) -> dict:
    """Does the share answer, or is it merely listed in the mount table?

    The I/O runs as a subprocess with a timeout on purpose: a hung CIFS call blocks
    uninterruptibly, so doing this in-process would wedge the reader that is supposed to
    report the problem.
    """
    if not os.path.ismount(path):
        return {'ok': False, 'path': path, 'mounted': False, 'responded': False,
                'error': f'{path} is NOT MOUNTED'}

    started = time.time()
    ok, out = _run(['stat', '-f', '-c', '%b %a', path], timeout=timeout)
    elapsed = (time.time() - started) * 1000
    if not ok:
        return {'ok': False, 'path': path, 'mounted': True, 'responded': False,
                'latency_ms': elapsed,
                'error': f'mounted, but did not answer within {timeout:.0f}s — {out}'}
    return {'ok': True, 'path': path, 'mounted': True, 'responded': True,
            'latency_ms': elapsed, 'error': None,
            # A share that answers in two seconds is not healthy, it is on its way out.
            'slow': elapsed > 1000}


def _probe_endpoint(name: str, url: str, timeout: float = _PROBE_TIMEOUT) -> dict:
    import requests
    started = time.time()
    try:
        resp = requests.get(url, timeout=timeout)
        elapsed = (time.time() - started) * 1000
        # Any answer proves the service is listening and serving; 4xx/5xx is a different
        # problem from unreachable, so it is reported as reached-but-unhappy, not as down.
        return {'name': name, 'url': url, 'ok': resp.status_code < 400,
                'reached': True, 'status': resp.status_code, 'latency_ms': elapsed,
                'error': None if resp.status_code < 400 else f'HTTP {resp.status_code}'}
    except Exception as e:
        return {'name': name, 'url': url, 'ok': False, 'reached': False, 'status': None,
                'latency_ms': (time.time() - started) * 1000,
                'error': f'{type(e).__name__}: {e}'}


def get_tailscale() -> dict:
    ok, out = _run(['tailscale', 'status', '--json'], timeout=8)
    if not ok:
        return {'ok': False, 'error': out, 'peers': []}
    try:
        data = json.loads(out or '{}')
    except json.JSONDecodeError as e:
        return {'ok': False, 'error': f'unreadable tailscale output ({e})', 'peers': []}

    self_node = data.get('Self') or {}
    peers = []
    for peer in (data.get('Peer') or {}).values():
        host = peer.get('HostName') or ''
        if host.lower() not in _LAB_PEERS:
            continue
        peers.append({'host': host, 'online': bool(peer.get('Online')),
                      'os': peer.get('OS') or '', 'last_seen': peer.get('LastSeen') or ''})
    peers.sort(key=lambda p: (p['online'], p['host'].lower()))

    backend = data.get('BackendState') or 'unknown'
    return {'ok': backend == 'Running', 'error': None if backend == 'Running'
            else f'tailscaled backend is {backend}, not Running',
            'backend': backend, 'self': self_node.get('HostName') or '',
            'ips': data.get('TailscaleIPs') or [], 'peers': peers}


def get_reachability() -> dict:
    """Tailscale, the NAS mount's real responsiveness, and the endpoints this lab needs."""
    now = time.time()
    if (_REACH_CACHE['data'] is not None
            and (now - _REACH_CACHE['time']) < _REACH_CACHE_TTL):
        return _REACH_CACHE['data']

    # Probed in parallel: serially, four dead endpoints would take four timeouts and the
    # panel would be the slowest thing on the page.
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(_ENDPOINTS) + 1) as pool:
        mount_future = pool.submit(probe_mount)
        endpoint_futures = [pool.submit(_probe_endpoint, name, url)
                            for name, url in _ENDPOINTS]
        endpoints = [f.result() for f in endpoint_futures]
        mount = mount_future.result()

    tailscale = get_tailscale()
    down = ([e['name'] for e in endpoints if not e['ok']]
            + ([mount['path']] if not mount['ok'] else [])
            + ([] if tailscale['ok'] else ['tailscale']))
    data = {'ok': not down, 'read_at': now, 'error': None,
            'tailscale': tailscale, 'mount': mount, 'endpoints': endpoints,
            'down': down}
    _REACH_CACHE.update(time=now, data=data)
    return data


def get_uptime() -> dict:
    """Host uptime -- the other half of "system status beyond the media stack"."""
    ok, raw = _read_proc('/proc/uptime')
    if not ok:
        return {'ok': False, 'error': raw}
    try:
        seconds = float(raw.split()[0])
    except (IndexError, ValueError) as e:
        return {'ok': False, 'error': f'unreadable /proc/uptime ({e})'}
    return {'ok': True, 'error': None, 'seconds': seconds,
            'booted_at': time.time() - seconds}


# F13. SMART, read from smartd's own world-readable attribute log rather than by shelling
# out to smartctl. Three reasons that is the better source and not merely the accessible one:
# smartctl needs root and this app is a user service; smartd is already polling on its own
# schedule, so reading its output wakes no disk that was allowed to sleep; and it is the
# component whose alerts are going nowhere, so reading its own record is reading exactly what
# is being lost. `/etc/smartd.conf` mails root via smartd-runner and this host has no MTA at
# all -- so a disk could be reporting reallocated sectors right now and the only trace would
# be a file nobody opens.
#
# Only the newest row is read. The log is a time series and this is deliberately not one --
# a current value on demand, which MONITORING.md permits, not a trend, which it does not.
SMARTD_STATE_DIR = '/var/lib/smartmontools'

# The attributes that actually mean a disk is dying. Non-zero raw on any of these is the
# signal; everything else on a SMART report is context.
_SMART_CRITICAL = {
    5: 'Reallocated sectors',
    187: 'Reported uncorrectable errors',
    196: 'Reallocation events',
    197: 'Current pending sectors',
    198: 'Offline uncorrectable sectors',
    199: 'UDMA CRC errors',
}


def _parse_attrlog_row(row: str) -> dict:
    """`ts;\tid;val;raw;\tid;val;raw;...` -> {id: {'val': int, 'raw': int}}."""
    attrs = {}
    for group in row.split('\t'):
        parts = [p for p in group.strip().strip(';').split(';') if p != '']
        if len(parts) != 3:
            continue
        try:
            attrs[int(parts[0])] = {'val': int(parts[1]), 'raw': int(parts[2])}
        except ValueError:
            continue
    return attrs


def get_disk_health() -> dict:
    """SMART for every disk smartd is watching, from its attribute log."""
    if not os.path.isdir(SMARTD_STATE_DIR):
        return {'ok': False, 'disks': [],
                'error': f'{SMARTD_STATE_DIR} does not exist — smartmontools may not be installed'}
    try:
        logs = [f for f in os.listdir(SMARTD_STATE_DIR)
                if f.startswith('attrlog.') and f.endswith('.csv')]
    except OSError as e:
        return {'ok': False, 'disks': [], 'error': f'cannot read {SMARTD_STATE_DIR} ({e})'}

    if not logs:
        return {'ok': False, 'disks': [],
                'error': 'smartd is not writing attribute logs — nothing to read. '
                         'It may be running without -A, or watching no devices.'}

    disks, problems = [], []
    for name in sorted(logs):
        path = os.path.join(SMARTD_STATE_DIR, name)
        # attrlog.<MODEL>-<SERIAL>.<type>.csv
        label = name[len('attrlog.'):].rsplit('.', 2)[0]
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as f:
                rows = [r for r in f.read().splitlines() if r.strip()]
            mtime = os.path.getmtime(path)
        except OSError as e:
            problems.append(f'{label}: {e}')
            disks.append({'label': label, 'ok': False, 'error': str(e)})
            continue
        if not rows:
            problems.append(f'{label}: attribute log is empty')
            disks.append({'label': label, 'ok': False, 'error': 'attribute log is empty'})
            continue

        stamp, _, rest = rows[-1].partition(';')
        attrs = _parse_attrlog_row(rest)
        if not attrs:
            problems.append(f'{label}: unparseable attribute row')
            disks.append({'label': label, 'ok': False,
                          'error': 'newest attribute row could not be parsed'})
            continue

        # An attribute this device does not report is NOT a zero. A drive that never
        # publishes attribute 5 has not told us it has no reallocated sectors, and
        # rendering that as a clean tick would be inventing the reassurance.
        failing, clean, unreported = [], [], []
        for attr_id, attr_name in _SMART_CRITICAL.items():
            if attr_id not in attrs:
                unreported.append(attr_name)
            elif attrs[attr_id]['raw'] > 0:
                failing.append({'name': attr_name, 'id': attr_id,
                                'raw': attrs[attr_id]['raw']})
            else:
                clean.append(attr_name)

        temp = attrs.get(194)
        disks.append({
            'label': label, 'ok': True, 'error': None,
            'read_at': mtime, 'sampled': stamp.strip(),
            'failing': failing, 'clean': clean, 'unreported': unreported,
            'power_on_hours': attrs.get(9, {}).get('raw'),
            'power_cycles': attrs.get(12, {}).get('raw'),
            # Attribute 231's normalised value is percent of life left on most SSDs.
            'life_left_pct': attrs.get(231, {}).get('val'),
            # 194's raw packs several fields; the current temperature is the low 16 bits.
            'temp_c': (temp['raw'] & 0xFFFF) if temp else None,
        })

    return {'ok': not problems, 'disks': disks,
            'read_at': time.time(),
            'error': '; '.join(problems) if problems else None}


# F15. Backups, read from systemd rather than from a self-report each job would have to
# be taught to write. systemd already records what we need -- when a unit last ran, whether
# it succeeded, how long it took, when its timer fires next -- and a convention nobody has
# to adopt cannot fall out of date. What systemd does NOT know is what a run actually wrote
# or how big it was, so this does not claim to: the job's own last journal line is shown as
# its self-report, whatever form the job chose, and nothing is inferred beyond it.
#
# QNAP2 is never contacted here. The backup job is the only sanctioned thing that talks to
# it (ADR 22); reading systemd's record of whether that job succeeded touches nothing.
_BACKUP_UNIT_HINT = 'backup'


def _unit_props(unit: str, manager: str, props: list[str]) -> dict:
    ok, out = _run(['systemctl', f'--{manager}', 'show', unit, '--timestamp=unix']
                   + [f'--property={p}' for p in props], timeout=10)
    if not ok:
        return {}
    values = {}
    for line in (out or '').splitlines():
        key, _, value = line.partition('=')
        if key:
            values[key] = value
    return values


def _systemd_stamp(raw: str) -> float | None:
    """Parse `@<epoch seconds>`, which is what --timestamp=unix emits.

    Without that flag systemd prints "Wed 2026-09-09 20:18:56 EDT", which would need
    locale- and timezone-dependent parsing to read. An unset timestamp comes back empty
    or as "n/a", and both must read as "never", not as the epoch.
    """
    if not raw:
        return None
    raw = raw.strip()
    if not raw.startswith('@'):
        return None
    try:
        seconds = float(raw[1:])
    except ValueError:
        return None
    return seconds if seconds > 0 else None


def get_backups() -> dict:
    """Every backup unit this host runs, with its last result and next run."""
    jobs, problems = [], []
    for manager in ('user', 'system'):
        ok, out = _run(['systemctl', f'--{manager}', 'list-units', '--type=service',
                        '--all', '--output=json', '--no-pager'], timeout=20)
        if not ok:
            problems.append(f'{manager}: {out}')
            continue
        try:
            units = json.loads(out or '[]')
        except json.JSONDecodeError as e:
            problems.append(f'{manager}: unreadable systemctl output ({e})')
            continue

        for row in units:
            name = row.get('unit', '')
            if _BACKUP_UNIT_HINT not in name.lower() or not name.endswith('.service'):
                continue
            props = _unit_props(name, manager, [
                'Description', 'Result', 'ExecMainStatus', 'NRestarts',
                'ActiveEnterTimestampMonotonic', 'InactiveEnterTimestampMonotonic',
                'ExecMainStartTimestamp', 'ExecMainExitTimestamp',
                'ExecMainStartTimestampMonotonic'])
            timer_props = _unit_props(name[:-len('.service')] + '.timer', manager,
                                      ['NextElapseUSecRealtime', 'LastTriggerUSec'])

            last_run = _systemd_stamp(timer_props.get('LastTriggerUSec'))
            next_run = _systemd_stamp(timer_props.get('NextElapseUSecRealtime'))
            result = props.get('Result') or 'unknown'
            exit_status = props.get('ExecMainStatus')

            # A job that has never run at all and one that ran and failed are different
            # problems: the first is a timer that never fired, the second is a broken job.
            never_ran = last_run is None and not _systemd_stamp(
                props.get('ExecMainStartTimestamp'))
            # systemd's own Result is the verdict, not ExecMainStatus. gamelab-backup@wotlk
            # reports Result=success with ExecMainStatus=1 -- a oneshot whose last ExecStart
            # is not its main process, or a configured SuccessExitStatus. Requiring both to
            # agree invented a failure systemd does not see. The disagreement is still worth
            # showing, so it is reported as a note rather than swallowed or promoted.
            succeeded = result == 'success'
            odd_exit = (succeeded and exit_status not in ('0', '', None))

            log_ok, log_out = _run(['journalctl', f'--{manager}', '-u', name, '-n', '3',
                                    '--no-pager', '--output=cat'], timeout=10)
            jobs.append({
                'unit': name, 'manager': manager,
                'description': props.get('Description') or name,
                'ok': succeeded and not never_ran,
                'never_ran': never_ran,
                'result': result, 'exit_status': exit_status, 'odd_exit': odd_exit,
                'last_run': last_run, 'next_run': next_run,
                # The job's own words about what it did. systemd cannot know what was
                # written or how large it was; if the job does not say, nobody knows.
                'last_words': (log_out or '').strip() if log_ok else None,
                'log_error': None if log_ok else log_out,
            })

    jobs.sort(key=lambda j: (j['ok'], j['unit']))
    return {'ok': not problems, 'jobs': jobs, 'read_at': time.time(),
            'error': '; '.join(problems) if problems else None}


# F16. Remote hosts. This box cannot enumerate them -- nothing here can prove what a
# Windows workstation across the room is doing -- so everything below is a *claim* with a
# date on it, read from ~/HomeLab/HARDWARE.md, which is the canonical inventory. Copying
# that list into this repo would create a second source of truth that drifts; reading it
# means the dashboard is wrong exactly when the doc is, and says when it was last touched.
#
# Where a host is on the tailnet, F14's peer list upgrades the claim to a fact for the one
# narrow question of reachability. Everything else stays a claim.
HARDWARE_DOC = os.path.expanduser('~/HomeLab/HARDWARE.md')
HARDWARE_REVIEW_MAX_AGE_DAYS = 90     # matches MONITORING-COVERAGE.json's verify_max_age_days

def _squash(name: str) -> str:
    return re.sub(r'[^a-z0-9]', '', name.lower())


_NODE_HEADING = re.compile(r'^###\s+(Node\s+\w+|QNAP\d)\s*[—-]\s*(.+?)\s*$')


def get_remote_hosts() -> dict:
    """The declared inventory, dated, with tailnet reachability where we have it."""
    try:
        with open(HARDWARE_DOC, 'r', encoding='utf-8', errors='replace') as f:
            lines = f.read().splitlines()
        reviewed_at = os.path.getmtime(HARDWARE_DOC)
    except OSError as e:
        return {'ok': False, 'hosts': [], 'error': f'cannot read {HARDWARE_DOC} ({e})'}

    peers = {}
    ts = get_tailscale()
    if ts.get('ok'):
        for p in ts['peers']:
            peers[p['host'].lower()] = p
            peers[_squash(p['host'])] = p

    hosts = []
    for line in lines:
        m = _NODE_HEADING.match(line)
        if not m:
            continue
        label, rest = m.group(1), m.group(2)
        offlimits = 'OFF-LIMITS' in rest.upper()
        # The heading carries the nickname in quotes when it has one.
        name_match = re.search(r'"([^"]+)"', rest)
        if name_match:
            name = name_match.group(1)
        else:
            # "Surface Pro 8 (Mobile Engineering Client)" -> "Surface Pro 8"
            name = re.sub(r'\s*\(.*$', '', rest.split('—')[0]).strip()
        # Tailscale hostnames drop spacing and case, and often drop trailing model words
        # too: the peer calling itself "steamdeck" is this doc's "Steam Deck OLED". Exact
        # first, then a prefix match long enough not to collide by accident.
        squashed = _squash(name)
        peer = peers.get(name.lower()) or peers.get(squashed)
        if peer is None:
            for key, candidate in peers.items():
                if len(key) >= 5 and (squashed.startswith(key) or key.startswith(squashed)):
                    peer = candidate
                    break
        hosts.append({
            'label': label, 'name': name, 'detail': rest,
            'off_limits': offlimits,
            # None means "we have no way to ask", which is not the same as offline.
            'online': None if (offlimits or peer is None) else peer['online'],
            'on_tailnet': peer is not None and not offlimits,
        })

    age_days = (time.time() - reviewed_at) / 86400
    return {'ok': True, 'hosts': hosts, 'error': None, 'read_at': time.time(),
            'reviewed_at': reviewed_at, 'age_days': age_days,
            'stale': age_days > HARDWARE_REVIEW_MAX_AGE_DAYS,
            'source': HARDWARE_DOC}


def get_top_processes(limit: int = 8) -> dict:
    """Top CPU consumers -- the answer to 'what is eating this'."""
    ok, out = _run(['ps', '-eo', 'pid,pcpu,pmem,rss,comm', '--sort=-pcpu', '--no-headers'])
    if not ok:
        return {'ok': False, 'error': out, 'processes': []}
    rows = []
    for line in out.splitlines()[:limit]:
        parts = line.split(None, 4)
        if len(parts) < 5:
            continue
        try:
            rows.append({'pid': parts[0], 'cpu': float(parts[1]), 'mem': float(parts[2]),
                         'rss': int(parts[3]) * 1024, 'command': parts[4].strip()})
        except ValueError:
            continue
    return {'ok': True, 'error': None, 'processes': rows}


def get_container_detail(name: str, log_lines: int = 60) -> dict:
    """Everything about one container: what it is, whether its own healthcheck agrees
    that it is well, what it is currently consuming, and its recent output."""
    ok, out = _run(['docker', 'inspect', name])
    if not ok:
        return {'ok': False, 'error': out, 'name': name}
    try:
        info = json.loads(out)[0]
    except (json.JSONDecodeError, IndexError, KeyError) as e:
        return {'ok': False, 'error': f'unreadable docker inspect output ({e})', 'name': name}

    state = info.get('State') or {}
    config = info.get('Config') or {}
    labels = config.get('Labels') or {}
    health = (state.get('Health') or {}).get('Status')

    ports = []
    for container_port, bindings in ((info.get('NetworkSettings') or {}).get('Ports') or {}).items():
        for b in bindings or []:
            ports.append(f"{b.get('HostIp', '')}:{b.get('HostPort', '')} -> {container_port}")
    mounts = [f"{m.get('Source', '')} -> {m.get('Destination', '')}"
              for m in info.get('Mounts') or []]

    # What this container IS, which docker inspect cannot answer -- see
    # services/container_catalog.py. Carries its own provenance because a curated
    # sentence and a vendor's own blurb are different kinds of claim.
    description = container_catalog.describe(
        name, config.get('Image', ''),
        labels.get('org.opencontainers.image.description'),
        project=labels.get('com.docker.compose.project'),
        service=labels.get('com.docker.compose.service'),
        ports=ports, mounts=mounts)

    detail = {
        'ok': True, 'error': None, 'name': name,
        'description': description['text'],
        'description_source': description['source'],
        'description_hint': description.get('hint'),
        'state': state.get('Status', 'unknown'),
        # A container's own healthcheck is a different question from "is the process
        # running", and only some images define one. None means "not declared", which
        # is not the same as healthy.
        'health': health,
        'restarts': info.get('RestartCount', 0),
        'started_at': state.get('StartedAt'),
        'finished_at': state.get('FinishedAt'),
        'exit_code': state.get('ExitCode'),
        'oom_killed': state.get('OOMKilled', False),
        'image': config.get('Image', ''),
        'project': labels.get('com.docker.compose.project'),
        'service': labels.get('com.docker.compose.service'),
        'ports': ports, 'mounts': mounts,
        'stats': None, 'stats_error': None,
        'logs': [], 'log_error': None,
    }

    if state.get('Running'):
        ok, out = _run(['docker', 'stats', '--no-stream', '--format', '{{json .}}', name], timeout=25)
        if ok and out.strip():
            try:
                s = json.loads(out.strip().splitlines()[0])
                detail['stats'] = {'cpu': s.get('CPUPerc'), 'mem': s.get('MemUsage'),
                                   'mem_pct': s.get('MemPerc'), 'net': s.get('NetIO'),
                                   'block': s.get('BlockIO'), 'pids': s.get('PIDs')}
            except (json.JSONDecodeError, IndexError) as e:
                detail['stats_error'] = f'unreadable docker stats output ({e})'
        else:
            detail['stats_error'] = out or 'docker stats returned nothing'

    ok, out = _run(['docker', 'logs', '--tail', str(log_lines), name],
                   timeout=20, merge_stderr=True)
    if ok:
        detail['logs'] = out.splitlines()
    else:
        detail['log_error'] = out
    return detail
