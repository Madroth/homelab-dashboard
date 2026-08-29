import json
import os
import re
import shutil
import subprocess
import time

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
    return res


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

    detail = {
        'ok': True, 'error': None, 'name': name,
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
