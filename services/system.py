import json
import os
import shutil
import subprocess
import time

DAEMON_LOG_FILE = '/home/linuxbox/projects/media-curator/daemon.log'

# get_status() is called independently by both pages/home.py and pages/system.py, each on
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
