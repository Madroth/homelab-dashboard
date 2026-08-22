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

    status = {'defcon': [], 'containers': [], 'disk': {}, 'memory': {}}

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

    except Exception:
        status['containers'] = []

    try:
        daemon_status = subprocess.run(
            ['systemctl', '--user', 'is-active', 'media-curator'],
            capture_output=True, text=True).stdout.strip()
        status['daemon_active'] = (daemon_status == 'active')
        if daemon_status != 'active':
            status['defcon'].append('DAEMON_CRASH: media-curator.service is not active!')
    except Exception:
        status['daemon_active'] = False

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


def _run(cmd: list[str], timeout: int = 20) -> tuple[bool, str]:
    """(ok, output). Never raises -- a failed read is data, not an exception."""
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
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
    return {'ok': not errors, 'units': rows,
            'error': '; '.join(errors) if errors else None}


def _collapse(entries: list[dict]) -> list[dict]:
    """Fold identical repeats into one row carrying a count. The NAS reconnect logs
    the same sentence every few minutes -- fourteen identical rows push everything
    else off the screen and say nothing the first one didn't."""
    grouped: dict[tuple, dict] = {}
    for e in entries:
        key = (e['source'], e['origin'], e['message'])
        existing = grouped.get(key)
        if existing is None:
            grouped[key] = dict(e, count=1, first_at=e['at'])
            continue
        existing['count'] += 1
        existing['first_at'] = min(existing['first_at'], e['at'])
        if e['at'] > existing['at']:
            existing['at'] = e['at']
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
