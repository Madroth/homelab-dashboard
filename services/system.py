import json
import os
import shutil
import subprocess

DAEMON_LOG_FILE = '/home/linuxbox/projects/media-curator/daemon.log'


def get_status() -> dict:
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

    return status


def get_logs(tail: int = 100) -> list[str]:
    if not os.path.exists(DAEMON_LOG_FILE):
        return []
    with open(DAEMON_LOG_FILE, 'r') as f:
        lines = f.readlines()
    return lines[-tail:]
