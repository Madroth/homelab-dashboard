"""Lab Health page + the readers behind it.

The rule under test throughout: an unreadable source must never render as a calm
one. Every reader reports {'ok': False} and the page has to say "cannot tell"
rather than showing a shorter, quieter list -- the failure mode that let a downed
NAS look healthy for three days.
"""
import asyncio
import time

import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.testing import User

from pages import lab_health as lab_health_page
from services import system as system_service


# ---------- pure logic ----------

def test_collapse_folds_identical_repeats_into_one_row():
    """The NAS logs the same reconnect sentence every few minutes. Fourteen identical
    rows push everything else off the screen and say nothing the first one didn't."""
    now = time.time()
    entries = [
        {'source': 'journal-system', 'origin': 'kernel', 'message': 'CIFS: not responding',
         'at': now - 600, 'severity': 'error', 'detail': {}},
        {'source': 'journal-system', 'origin': 'kernel', 'message': 'CIFS: not responding',
         'at': now - 120, 'severity': 'error', 'detail': {}},
        {'source': 'journal-system', 'origin': 'kernel', 'message': 'something else',
         'at': now - 300, 'severity': 'error', 'detail': {}},
    ]
    out = system_service._collapse(entries)
    assert len(out) == 2
    cifs = next(e for e in out if 'CIFS' in e['message'])
    assert cifs['count'] == 2
    assert cifs['at'] == now - 120      # newest occurrence
    assert cifs['first_at'] == now - 600  # but the run started here
    assert out[0]['at'] >= out[1]['at']   # newest first


def test_collapse_keeps_same_message_from_different_origins_apart():
    now = time.time()
    entries = [
        {'source': 'journal-user', 'origin': 'a.service', 'message': 'connection refused',
         'at': now, 'severity': 'error', 'detail': {}},
        {'source': 'journal-user', 'origin': 'b.service', 'message': 'connection refused',
         'at': now, 'severity': 'error', 'detail': {}},
    ]
    assert len(system_service._collapse(entries)) == 2


def test_failed_units_fails_closed_when_systemctl_cannot_be_read(monkeypatch):
    monkeypatch.setattr(system_service, '_run', lambda *a, **kw: (False, 'systemctl: not found'))
    result = system_service.get_failed_units()
    assert result['ok'] is False
    assert result['error'] and 'not found' in result['error']
    assert result['units'] == []   # empty, but ok=False says why -- never read as "none failed"


def test_get_errors_reports_a_dead_source_instead_of_a_quieter_list(monkeypatch):
    """A source that cannot answer must show up as ok=False. Dropping it silently
    would shrink the error list and make the lab look calmer than it is."""
    def fake_run(cmd, timeout=20):
        if cmd[0] == 'journalctl':
            return False, 'journalctl: permission denied'
        if cmd[0] == 'docker':
            return True, ''
        return True, '[]'
    monkeypatch.setattr(system_service, '_run', fake_run)
    monkeypatch.setattr(system_service, '_ERROR_CACHE', {'time': 0.0, 'data': None, 'key': None})

    result = system_service.get_errors()
    assert result['ok'] is False
    assert 'permission denied' in result['error']
    assert result['sources']['journal-user']['ok'] is False
    assert result['sources']['containers']['ok'] is True


def test_get_errors_counts_a_failed_unit_and_ignores_a_clean_container_exit(monkeypatch):
    """Exited (0) is a job that finished -- this lab has several by design. Only a
    non-zero exit is an error."""
    ps = ('{"Names":"ac-db-import","Status":"Exited (0) 2 days ago","Image":"x"}\n'
          '{"Names":"freqtrade-dry1","Status":"Exited (137) 3 weeks ago","Image":"y"}\n')

    def fake_run(cmd, timeout=20):
        if cmd[0] == 'journalctl':
            return True, ''
        if cmd[0] == 'docker':
            return True, ps
        if cmd[0] == 'systemctl':
            return True, ('[{"unit":"plane-backup.service","active":"failed","sub":"failed",'
                          '"description":"Plane Backup"}]')
        return True, ''
    monkeypatch.setattr(system_service, '_run', fake_run)
    monkeypatch.setattr(system_service, '_ERROR_CACHE', {'time': 0.0, 'data': None, 'key': None})

    entries = system_service.get_errors()['entries']
    origins = [e['origin'] for e in entries]
    assert 'freqtrade-dry1' in origins
    assert 'ac-db-import' not in origins
    assert any(e['source'] == 'unit' and e['severity'] == 'critical' for e in entries)


def test_journal_message_decodes_a_byte_array():
    """journald hands back a byte array when the line was not valid UTF-8; dropping
    those entries would hide exactly the kind of crash output that isn't clean text."""
    assert system_service._journal_message([104, 105]) == 'hi'
    assert system_service._journal_message('plain') == 'plain'
    assert system_service._journal_message(None) == ''


# ---------- page ----------

@ui.page('/lab-health-test')
def _lab_health_test_page():
    lab_health_page.build()


ui.run_with(FastAPI())

_NOW = time.time()

_HEALTHY_STATUS = {'defcon': [], 'containers': [{'Names': 'plex', 'Status': 'Up 2 hours'}],
                   'disk': {'total': 100, 'used': 40, 'free': 60, 'free_pct': 60.0},
                   'memory': {'plex': '1GiB'}, 'daemon_active': True, 'read_at': _NOW}


def _errors(entries, ok=True, error=None):
    return {'ok': ok, 'entries': entries, 'read_at': _NOW, 'error': error,
            'sources': {'journal-user': {'ok': ok, 'error': error}}}


_HEALTHY_RESOURCES = {
    'ok': True, 'error': None, 'read_at': _NOW,
    'cpu': {'ok': True, 'error': None, 'cores': 8, 'load': [1.2, 1.0, 0.9],
            'psi': {'ok': True, 'error': None, 'some_avg10': 0.4}},
    'memory': {'ok': True, 'error': None, 'total': 16 * 1024**3, 'available': 8 * 1024**3,
               'used': 8 * 1024**3, 'used_pct': 50.0, 'swap_total': 4 * 1024**3,
               'swap_free': 4 * 1024**3, 'swap_used_pct': 0.0,
               'psi': {'ok': True, 'error': None, 'some_avg10': 0.0}},
    'disks': [{'label': 'root', 'path': '/', 'ok': True, 'error': None,
               'total': 200 * 1024**3, 'used': 100 * 1024**3, 'free': 100 * 1024**3,
               'used_pct': 50.0}],
    'temps': {'ok': True, 'error': None, 'zones': [{'name': 'x86_pkg_temp', 'celsius': 55.0}]},
}


_HEALTHY_REACH = {
    'ok': True, 'error': None, 'read_at': _NOW, 'down': [],
    'tailscale': {'ok': True, 'error': None, 'backend': 'Running', 'self': 'linuxbox-GT70',
                  'ips': ['100.87.245.107'],
                  'peers': [{'host': 'Omega', 'online': True, 'os': 'windows',
                             'last_seen': ''}]},
    'mount': {'ok': True, 'path': '/mnt/Multimedia', 'mounted': True, 'responded': True,
              'latency_ms': 7.0, 'error': None, 'slow': False},
    'endpoints': [{'name': 'ntfy', 'url': 'http://ntfy/v1/health', 'ok': True,
                   'reached': True, 'status': 200, 'latency_ms': 6.0, 'error': None}],
}


_HEALTHY_SMART = {
    'ok': True, 'error': None, 'read_at': _NOW,
    'disks': [{'label': 'KINGSTON_SQ500-ABC', 'ok': True, 'error': None, 'read_at': _NOW,
               'sampled': '2026-09-09 22:08:57', 'failing': [],
               'clean': ['Reported uncorrectable errors', 'UDMA CRC errors'],
               'unreported': [], 'power_on_hours': 6600, 'power_cycles': 138,
               'life_left_pct': 96, 'temp_c': 34}],
}


_HEALTHY_BACKUPS = {
    'ok': True, 'error': None, 'read_at': _NOW,
    'jobs': [{'unit': 'sessions-backup.service', 'manager': 'user',
              'description': 'Back up the session store to QNAP1', 'ok': True,
              'never_ran': False, 'result': 'success', 'exit_status': '0',
              'odd_exit': False, 'last_run': _NOW - 3600, 'next_run': _NOW + 3600,
              'last_words': 'wrote 12 files', 'log_error': None}],
}

_HEALTHY_HOSTS = {
    'ok': True, 'error': None, 'read_at': _NOW, 'reviewed_at': _NOW - 86400,
    'age_days': 1.0, 'stale': False, 'source': '/home/x/HARDWARE.md',
    'hosts': [{'label': 'Node C', 'name': 'Omega', 'detail': 'Main workstation',
               'off_limits': False, 'online': True, 'on_tailnet': True},
              {'label': 'QNAP2', 'name': 'Ellishomenas02', 'detail': 'Backup Vault',
               'off_limits': True, 'online': None, 'on_tailnet': False}],
}


_HEALTHY_ALERTS = {'ok': True, 'error': None, 'read_at': _NOW, 'alerts': [],
                   'exempt_units': {}, 'exempt_names': {}}


def _stub_page(monkeypatch, *, errors, units=None, status=None, resources=None, reach=None,
               smart=None, backups=None, hosts=None, alerts=None):
    monkeypatch.setattr(system_service, 'get_errors', lambda *a, **kw: errors)
    monkeypatch.setattr(system_service, 'get_units',
                        lambda *a, **kw: units or {'ok': True, 'units': [], 'error': None,
                                                   'read_at': _NOW})
    monkeypatch.setattr(system_service, 'get_status', lambda *a, **kw: status or _HEALTHY_STATUS)
    monkeypatch.setattr(system_service, 'get_logs', lambda *a, **kw: [])
    # Keep the page off the real machine: without this the resource panel reads this
    # host's live /proc during the test run.
    monkeypatch.setattr(system_service, 'get_host_resources',
                        lambda *a, **kw: resources or _HEALTHY_RESOURCES)
    monkeypatch.setattr(system_service, 'get_top_processes',
                        lambda *a, **kw: {'ok': True, 'error': None, 'processes': []})
    # Same rule as the resource reader above, and more important here: without this the
    # reachability panel would make real network probes during the test run.
    monkeypatch.setattr(system_service, 'get_reachability',
                        lambda *a, **kw: reach or _HEALTHY_REACH)
    monkeypatch.setattr(system_service, 'get_disk_health',
                        lambda *a, **kw: smart or _HEALTHY_SMART)
    monkeypatch.setattr(system_service, 'get_backups',
                        lambda *a, **kw: backups or _HEALTHY_BACKUPS)
    monkeypatch.setattr(system_service, 'get_remote_hosts',
                        lambda *a, **kw: hosts or _HEALTHY_HOSTS)
    # Never the real Alertmanager: what is firing on this host must not decide a test.
    monkeypatch.setattr(system_service, 'get_alerts',
                        lambda *a, **kw: alerts or _HEALTHY_ALERTS)
    monkeypatch.setattr(system_service, 'get_uptime',
                        lambda *a, **kw: {'ok': True, 'error': None, 'seconds': 486000.0,
                                          'booted_at': _NOW - 486000.0})


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_page_lists_errors_and_names_the_failed_unit(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([
        {'source': 'unit', 'origin': 'plane-backup.service', 'at': _NOW, 'count': 1,
         'first_at': _NOW, 'severity': 'critical',
         'message': 'plane-backup.service is in a failed state (failed) — Plane Backup',
         'detail': {'manager': 'user', 'unit': 'plane-backup.service'}},
    ]))
    await user.open('/lab-health-test')
    await user.should_see('Lab Health')
    await user.should_see('Something is broken')
    await user.should_see('plane-backup.service')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_page_says_cannot_tell_when_a_source_is_unreadable(user: User, monkeypatch):
    """The heart of it: a source that did not answer must not render as a quiet page.
    'Cannot tell' is a third outcome, never a softer shade of 'nothing is broken'."""
    _stub_page(monkeypatch, errors=_errors([], ok=False,
                                            error='journal-user: permission denied'))
    await user.open('/lab-health-test')
    await user.should_see('Cannot tell')
    await user.should_not_see('Nothing is broken')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_page_reports_all_clear_only_when_every_source_answered(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('Nothing is broken')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_clicking_an_error_opens_its_full_text(user: User, monkeypatch):
    """The reason the page exists: an error you can read and copy, not a truncated row
    with the detail trapped in a tooltip."""
    long_message = ('CIFS: VFS: \\\\192.168.1.213 has not responded in 180 seconds. '
                    'Reconnecting to the share and retrying the mount.')
    _stub_page(monkeypatch, errors=_errors([
        {'source': 'journal-system', 'origin': 'kernel', 'at': _NOW - 300, 'count': 4,
         'first_at': _NOW - 900, 'severity': 'error', 'message': long_message,
         'detail': {'manager': 'system'}},
    ]))
    await user.open('/lab-health-test')
    await user.should_see('kernel')
    user.find(marker=f'error-row-kernel-{int(_NOW - 300)}').click()
    await asyncio.sleep(0.3)
    await user.should_see('Reconnecting to the share')
    await user.should_see('MESSAGE')
    # A kernel line names no unit and no container, so there is nothing to suggest
    # running -- the panel offers a command only when it can build a real one.
    await user.should_not_see('INVESTIGATE')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_failed_unit_row_offers_the_command_to_investigate_it(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([
        {'source': 'unit', 'origin': 'livescore.service', 'at': _NOW, 'count': 1,
         'first_at': _NOW, 'severity': 'critical', 'message': 'livescore.service is in a failed state',
         'detail': {'manager': 'system', 'unit': 'livescore.service'}},
    ]))
    await user.open('/lab-health-test')
    await user.should_see('livescore.service')   # wait for the async first read
    user.find(marker=f'error-row-livescore-service-{int(_NOW)}').click()
    await asyncio.sleep(0.3)
    await user.should_see('journalctl --system -u livescore.service')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_units_section_reports_unreadable_rather_than_empty(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]),
               units={'ok': False, 'units': [], 'error': 'systemctl: not found'})
    await user.open('/lab-health-test')
    await user.should_see('Could not list units')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_monitoring_tools_are_linked_from_this_page(user: User, monkeypatch):
    """Phase 0.8: monitoring's own tools get a home here rather than a quick-link
    parked on the Media Curator page."""
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('Uptime Kuma')
    await user.should_see('Dozzle')


def test_media_page_no_longer_links_uptime_kuma():
    """Moved to Lab Health (Chris, 2026-08-22) -- Kuma is not a media service and that
    stack stopped owning it at Phase 0.7."""
    from pages import media
    labels = [label for _, label, _ in media.QUICK_LINKS]
    assert 'Uptime-Kuma' not in labels
    assert 'Plex' in labels   # the real media links are untouched


# ---------- get_status(): the two inherited fail-open paths ----------

def test_docker_failure_keeps_the_reason_and_raises_defcon(monkeypatch):
    """An empty container list and 'docker did not answer' are different answers. The
    old code returned [] with the reason discarded, so an unreachable daemon and an
    idle host rendered identically -- and neither raised the banner."""
    def boom(*a, **kw):
        raise OSError('docker daemon not reachable')
    monkeypatch.setattr(system_service.subprocess, 'check_output', boom)
    monkeypatch.setattr(system_service.os.path, 'ismount', lambda p: True)
    monkeypatch.setattr(system_service, '_status_cache', {'time': 0.0, 'status': None})

    status = system_service.get_status()
    assert status['containers'] == []
    assert 'not reachable' in status['containers_error']
    assert any('DOCKER_UNREACHABLE' in d for d in status['defcon'])


def test_unknown_daemon_state_still_raises_defcon(monkeypatch):
    """The subtlest one: if systemctl raised, the old code set daemon_active False and
    stopped -- the daemon read as dead AND the alert saying so went missing. Not being
    able to tell is its own alert; the one thing it must never do is go quiet."""
    def boom(*a, **kw):
        raise FileNotFoundError('systemctl missing')
    monkeypatch.setattr(system_service.subprocess, 'run', boom)
    monkeypatch.setattr(system_service.subprocess, 'check_output', lambda *a, **kw: '')
    monkeypatch.setattr(system_service.os.path, 'ismount', lambda p: True)
    monkeypatch.setattr(system_service, '_status_cache', {'time': 0.0, 'status': None})

    status = system_service.get_status()
    assert status['daemon_active'] is False
    assert any('DAEMON_UNKNOWN' in d for d in status['defcon']), \
        'a daemon whose state cannot be read must not fail silently'


# ---------- grouping key ----------

def test_repeats_group_despite_a_changing_pid_or_byte_count():
    """Exact-string grouping never folds a message carrying a pid, an address or a
    timeout, so fifty OOM kills stayed fifty rows."""
    now = time.time()
    entries = [
        {'source': 'journal-system', 'origin': 'kernel', 'at': now - 300, 'severity': 'error',
         'message': 'CIFS: VFS: has not responded in 180 seconds. Reconnecting...', 'detail': {}},
        {'source': 'journal-system', 'origin': 'kernel', 'at': now - 60, 'severity': 'error',
         'message': 'CIFS: VFS: has not responded in 240 seconds. Reconnecting...', 'detail': {}},
    ]
    out = system_service._collapse(entries)
    assert len(out) == 1
    assert out[0]['count'] == 2
    # the row shows the newest REAL text, not the normalised key
    assert '240 seconds' in out[0]['message']


def test_grouping_keeps_genuinely_different_subjects_apart():
    """Single digits are left alone on purpose: GPC1 and GPC2 are different units,
    while a pid is the same error wearing a different number."""
    now = time.time()
    entries = [
        {'source': 'journal-system', 'origin': 'kernel', 'at': now, 'severity': 'error',
         'message': 'nouveau: GPC1/PROP trap', 'detail': {}},
        {'source': 'journal-system', 'origin': 'kernel', 'at': now, 'severity': 'error',
         'message': 'nouveau: GPC2/PROP trap', 'detail': {}},
    ]
    assert len(system_service._collapse(entries)) == 2


def test_message_id_groups_entries_whose_text_differs_entirely():
    """journald's MESSAGE_ID is exact where it exists -- roughly a fifth of this host's
    error entries -- and beats any amount of text normalising."""
    now = time.time()
    entries = [
        {'source': 'journal-user', 'origin': 'a.service', 'at': now - 10, 'severity': 'error',
         'message': 'totally different wording here', 'detail': {},
         'message_id': 'be02cf6855d2428ba40df7e9d022f03d'},
        {'source': 'journal-user', 'origin': 'a.service', 'at': now, 'severity': 'error',
         'message': 'and something else again', 'detail': {},
         'message_id': 'be02cf6855d2428ba40df7e9d022f03d'},
    ]
    out = system_service._collapse(entries)
    assert len(out) == 1 and out[0]['count'] == 2


def test_normalise_leaves_the_displayed_message_untouched():
    assert system_service._normalise_message('pid [12345] failed at 0xdeadbeef after 90s') == \
        'pid [N] failed at 0xN after Ns'
    assert system_service._normalise_message('disk 1 offline') == 'disk 1 offline'


# ---------- F2 / F3 ----------

@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_containers_are_grouped_by_compose_project(user: User, monkeypatch):
    """54 containers across 13 projects: one flat grid buries everything under media."""
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'plex', 'Status': 'Up 2 hours',
         'Labels': 'com.docker.compose.project=media-curator'},
        {'Names': 'plane-app-api-1', 'Status': 'Up 16 hours',
         'Labels': 'com.docker.compose.project=plane-app'},
        {'Names': 'stray', 'Status': 'Up 1 hour', 'Labels': ''},
    ])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    await user.open('/lab-health-test')
    await user.should_see('media-curator')
    await user.should_see('plane-app')
    await user.should_see('ungrouped')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_clicking_a_container_shows_health_and_live_usage(user: User, monkeypatch):
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'gluetun', 'Status': 'Up 3 hours (unhealthy)',
         'Labels': 'com.docker.compose.project=media-curator'}])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    monkeypatch.setattr(system_service, 'get_container_detail', lambda *a, **kw: {
        'ok': True, 'error': None, 'name': 'gluetun', 'state': 'running',
        'health': 'unhealthy', 'restarts': 14, 'started_at': '', 'finished_at': '',
        'exit_code': 0, 'oom_killed': False, 'image': 'qmcgaw/gluetun:v3',
        'project': 'media-curator', 'service': 'gluetun',
        'ports': ['0.0.0.0:8090 -> 8090/tcp'], 'mounts': [],
        'stats': {'cpu': '3.20%', 'mem': '48MiB / 15GiB', 'mem_pct': '0.31%',
                  'net': '1MB / 2MB', 'block': '0B / 0B', 'pids': '12'},
        'stats_error': None, 'logs': ['tunnel down, retrying'], 'log_error': None})

    await user.open('/lab-health-test')
    await user.should_see('gluetun')
    user.find(marker='container-gluetun').click()
    await asyncio.sleep(0.3)
    await user.should_see('unhealthy')     # its own healthcheck, not just "running"
    await user.should_see('3.20%')         # live usage
    await user.should_see('tunnel down, retrying')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_running_container_with_no_healthcheck_does_not_claim_health(
        user: User, monkeypatch):
    """A container with no healthcheck declared is not the same as a healthy one."""
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'dozzle', 'Status': 'Up 1 hour', 'Labels': ''}])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    monkeypatch.setattr(system_service, 'get_container_detail', lambda *a, **kw: {
        'ok': True, 'error': None, 'name': 'dozzle', 'state': 'running', 'health': None,
        'restarts': 0, 'started_at': '', 'finished_at': '', 'exit_code': 0,
        'oom_killed': False, 'image': 'amir20/dozzle', 'project': None, 'service': None,
        'ports': [], 'mounts': [], 'stats': None, 'stats_error': None,
        'logs': [], 'log_error': None})

    await user.open('/lab-health-test')
    await user.should_see('dozzle')   # wait for the async first read
    user.find(marker='container-dozzle').click()
    await asyncio.sleep(0.3)
    await user.should_see('no healthcheck declared')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_resource_cards_render_from_the_reader(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('CPU LOAD')
    await user.should_see('MEMORY')
    await user.should_see('TEMPERATURE')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_an_unreadable_resource_says_cannot_tell_rather_than_zero(user: User, monkeypatch):
    """A panel rendering 0% because /proc could not be read is worse than one that
    admits it does not know."""
    broken = dict(_HEALTHY_RESOURCES, ok=False,
                  memory={'ok': False, 'error': 'PermissionError: /proc/meminfo'})
    _stub_page(monkeypatch, errors=_errors([]), resources=broken)
    await user.open('/lab-health-test')
    await user.should_see('Cannot tell')
    await user.should_see('/proc/meminfo')


def test_host_resources_refuses_to_read_the_nas_when_it_is_not_mounted(monkeypatch):
    """The original sin: /mnt/Multimedia exists as a plain directory when the NAS is
    away, so disk_usage() reports the root SSD's numbers under the NAS's name."""
    monkeypatch.setattr(system_service.os.path, 'ismount', lambda p: False)
    res = system_service.get_host_resources()
    nas = next(d for d in res['disks'] if d['label'] == 'NAS')
    assert nas['ok'] is False
    assert 'NOT MOUNTED' in nas['error']
    assert 'total' not in nas          # no plausible-looking number from another disk
    assert res['ok'] is False


def test_psi_reports_unreadable_rather_than_zero(monkeypatch):
    monkeypatch.setattr(system_service, '_read_proc', lambda p: (False, 'OSError: nope'))
    psi = system_service._psi('/proc/pressure/memory')
    assert psi['ok'] is False and 'nope' in psi['error']
    assert 'some_avg10' not in psi


# ---------- F6: freshness ----------

def test_every_reader_stamps_when_it_actually_read(monkeypatch):
    """A panel that cannot say when it was read cannot be trusted to be current."""
    monkeypatch.setattr(system_service, '_run', lambda *a, **kw: (True, '[]'))
    before = time.time()
    units = system_service.get_units()
    resources = system_service.get_host_resources()
    after = time.time()

    for name, data in (('units', units), ('resources', resources)):
        assert 'read_at' in data, f'{name} reports no read time'
        assert before <= data['read_at'] <= after


def test_a_cache_hit_reports_when_the_data_was_read_not_when_it_was_served(monkeypatch):
    """get_status() is cached for 8s. If a cache hit restamped itself, the page would
    claim data was read just now when it is up to eight seconds old -- the stamp would
    launder staleness instead of exposing it, which is the whole point of having one."""
    read_at = time.time() - 5
    cached = {'defcon': [], 'containers': [], 'disk': {}, 'memory': {},
              'containers_error': None, 'read_at': read_at}
    monkeypatch.setattr(system_service, '_status_cache',
                        {'time': read_at, 'status': cached})

    served = system_service.get_status()

    assert served is cached
    assert served['read_at'] == read_at


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_each_panel_shows_when_it_was_read(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('Nothing is broken')
    # One stamp per panel -- errors, units, containers, resources -- plus the verdict.
    stamp = time.strftime('%H:%M:%S', time.localtime(_NOW))
    await user.should_see(f'AS OF {stamp}')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_an_old_reading_is_shown_as_stale_rather_than_as_current(user: User, monkeypatch):
    """The failure this guards: the poll dies, the numbers freeze, and the page keeps
    presenting them as the current state of the lab. Age is reported, not hidden."""
    old = time.time() - 600
    stale_resources = dict(_HEALTHY_RESOURCES, read_at=old)
    _stub_page(monkeypatch, errors=_errors([]), resources=stale_resources)
    await user.open('/lab-health-test')
    await user.should_see('Nothing is broken')
    await user.should_see('10m ago')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_reader_with_no_read_time_says_so_instead_of_looking_fresh(user: User, monkeypatch):
    no_stamp = dict(_HEALTHY_RESOURCES)
    no_stamp.pop('read_at')
    _stub_page(monkeypatch, errors=_errors([]), resources=no_stamp)
    await user.open('/lab-health-test')
    await user.should_see('AS OF UNKNOWN')


# ---------- F7: search and filter ----------

_MANY_CONTAINERS = {
    'defcon': [], 'disk': {'total': 100, 'used': 40, 'free': 60, 'free_pct': 60.0},
    'memory': {}, 'daemon_active': True, 'read_at': _NOW, 'containers_error': None,
    'containers': [
        {'Names': 'plex', 'Status': 'Up 2 hours', 'Image': 'plexinc/pms-docker',
         'Labels': 'com.docker.compose.project=media'},
        {'Names': 'sonarr', 'Status': 'Up 3 days', 'Image': 'linuxserver/sonarr',
         'Labels': 'com.docker.compose.project=media'},
        {'Names': 'plane-api', 'Status': 'Up 1 day', 'Image': 'makeplane/plane',
         'Labels': 'com.docker.compose.project=plane-app'},
    ],
}


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_filtering_narrows_containers_to_the_match(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]), status=_MANY_CONTAINERS)
    await user.open('/lab-health-test')
    await user.should_see('sonarr')

    user.find(marker='lab-health-search').type('plane')
    await user.should_see('plane-api')
    await user.should_not_see('sonarr')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_filtered_page_says_it_is_filtered(user: User, monkeypatch):
    """A narrowed list must never read as the whole truth."""
    _stub_page(monkeypatch, errors=_errors([]), status=_MANY_CONTAINERS)
    await user.open('/lab-health-test')
    user.find(marker='lab-health-search').type('plex')
    await user.should_see('Filtered by "plex"')
    await user.should_see('showing 1 of 3')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_filter_matching_nothing_says_so_rather_than_looking_calm(user: User, monkeypatch):
    """An empty panel and a panel with nothing wrong look identical. They must not."""
    _stub_page(monkeypatch, errors=_errors([]), status=_MANY_CONTAINERS)
    await user.open('/lab-health-test')
    user.find(marker='lab-health-search').type('nosuchcontainer')
    await user.should_see('No containers match')
    await user.should_not_see('Docker is reachable and reports no containers')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_filtering_never_downgrades_the_verdict(user: User, monkeypatch):
    """The load-bearing one. Filtering hides rows; it must not make a broken lab
    report as a quiet one. The verdict is about the whole lab, not the slice on screen."""
    _stub_page(monkeypatch, status=_MANY_CONTAINERS, errors=_errors([
        {'source': 'unit', 'origin': 'plane-backup.service', 'at': _NOW, 'count': 1,
         'first_at': _NOW, 'severity': 'critical',
         'message': 'plane-backup.service is in a failed state (failed)',
         'detail': {'manager': 'user', 'unit': 'plane-backup.service'}},
    ]))
    await user.open('/lab-health-test')
    await user.should_see('Something is broken')

    # Filter to something that matches no error at all.
    user.find(marker='lab-health-search').type('plex')
    await user.should_see('No errors match')
    await user.should_see('Something is broken')      # still true, still said
    await user.should_not_see('Nothing is broken')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_searching_finds_a_healthy_unit_the_summary_view_would_cap_away(
        user: User, monkeypatch):
    """Unfiltered, units show failures first and then only 14 of the rest. Searching
    for one by name has to find it regardless of where it fell in that cap."""
    units = {'ok': True, 'error': None, 'read_at': _NOW, 'units': [
        {'unit': f'filler-{i}.service', 'kind': 'service', 'manager': 'user',
         'description': 'filler', 'active': 'active', 'sub': 'running', 'failed': False}
        for i in range(30)
    ] + [
        {'unit': 'homelab-dashboard.service', 'kind': 'service', 'manager': 'user',
         'description': 'Homelab Dashboard', 'active': 'active', 'sub': 'running',
         'failed': False},
    ]}
    _stub_page(monkeypatch, errors=_errors([]), units=units)
    await user.open('/lab-health-test')
    await user.should_not_see('homelab-dashboard.service')   # capped away at 14

    user.find(marker='lab-health-search').type('homelab-dashboard')
    await user.should_see('homelab-dashboard.service')


# ---------- F11: short-window rates, without a database ----------

@pytest.fixture
def clean_history(monkeypatch):
    import collections
    buf = collections.deque(maxlen=system_service._TREND_SAMPLES)
    monkeypatch.setattr(system_service, '_resource_history', buf)
    return buf


def _sample(at, memory=50.0, cpu=10.0, swap=0.0):
    return {'at': at, 'cpu': cpu, 'memory': memory, 'swap': swap}


def test_trend_refuses_to_call_a_direction_from_too_few_readings(clean_history):
    """Two points and a straight line is how you get a confident number that means
    nothing. It has to say it cannot tell yet."""
    now = time.time()
    clean_history.extend([_sample(now - 300, memory=40.0), _sample(now, memory=88.0)])
    t = system_service.resource_trend('memory')
    assert t['ok'] is False
    assert 'not enough' in t['reason']
    assert 'last' not in t          # no number offered alongside the refusal


def test_trend_refuses_when_the_readings_are_too_close_together(clean_history):
    """Three samples two seconds apart span nothing. A rate drawn from them would be
    noise wearing a percentage sign."""
    now = time.time()
    clean_history.extend([_sample(now - 4, memory=40.0), _sample(now - 2, memory=60.0),
                          _sample(now, memory=88.0)])
    t = system_service.resource_trend('memory')
    assert t['ok'] is False
    assert 'too short' in t['reason']


def test_trend_reports_the_span_it_actually_covers(clean_history):
    """The point of the honesty: sampling only happens while the page is open, so the
    window is whatever it turned out to be -- never a claimed five minutes."""
    now = time.time()
    clean_history.extend([_sample(now - 600, memory=40.0), _sample(now - 300, memory=64.0),
                          _sample(now, memory=88.0)])
    t = system_service.resource_trend('memory')
    assert t['ok'] is True
    assert t['first'] == 40.0 and t['last'] == 88.0
    assert t['direction'] == 'rising'
    assert 590 < t['span'] < 610        # the real interval, not a nominal one
    assert t['samples'] == 3


def test_trend_calls_a_small_wobble_steady_rather_than_a_direction(clean_history):
    now = time.time()
    clean_history.extend([_sample(now - 600, memory=50.0), _sample(now - 300, memory=51.5),
                          _sample(now, memory=51.0)])
    assert system_service.resource_trend('memory')['direction'] == 'steady'


def test_a_failed_reader_never_enters_the_history_as_a_zero(clean_history):
    """Fail-closed, applied to the buffer: an unreadable source must leave a gap, not a
    plausible number that drags a trend toward it."""
    res = {'read_at': time.time(),
           'cpu': {'ok': False, 'error': 'unreadable /proc/loadavg'},
           'memory': {'ok': True, 'used_pct': 70.0, 'swap_used_pct': 12.0}}
    system_service._record_sample(res)
    assert clean_history[-1]['cpu'] is None
    assert clean_history[-1]['memory'] == 70.0

    # And a metric that is always None never fabricates a trend.
    now = time.time()
    clean_history.clear()
    clean_history.extend([{'at': now - 600, 'cpu': None, 'memory': 40.0, 'swap': None},
                          {'at': now - 300, 'cpu': None, 'memory': 64.0, 'swap': None},
                          {'at': now, 'cpu': None, 'memory': 88.0, 'swap': None}])
    assert system_service.resource_trend('cpu')['ok'] is False


def test_simultaneous_reads_from_several_tabs_count_as_one_reading(clean_history):
    """Three open tabs polling together must not fill the buffer three times as fast --
    that would silently shrink the window the trend covers."""
    res = {'read_at': time.time(), 'cpu': {'ok': True, 'cores': 4, 'load': [2.0]},
           'memory': {'ok': True, 'used_pct': 50.0, 'swap_used_pct': 0.0}}
    for _ in range(3):
        system_service._record_sample(res)
    assert len(clean_history) == 1


def test_history_is_bounded_and_drops_the_oldest(clean_history):
    """Bounded, in-process, dropped on restart -- the thing that keeps this from being
    a time-series store."""
    now = time.time()
    for i in range(200):
        clean_history.append(_sample(now - (200 - i) * 10, memory=float(i)))
    assert len(clean_history) == system_service._TREND_SAMPLES == 60
    assert clean_history[-1]['memory'] == 199.0


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_memory_detail_shows_the_trend_it_can_support(user: User, monkeypatch,
                                                            clean_history):
    now = time.time()
    clean_history.extend([_sample(now - 600, memory=41.0), _sample(now - 300, memory=70.0),
                          _sample(now, memory=88.0)])
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('MEMORY')
    user.find(marker='resource-memory').click()
    await user.should_see('Memory used 41% → 88%')
    await user.should_see('across 10m of readings')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_memory_detail_says_it_cannot_tell_yet_rather_than_showing_a_flat_line(
        user: User, monkeypatch, clean_history):
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('MEMORY')
    user.find(marker='resource-memory').click()
    await user.should_see('not enough to say')


# ---------- F10: the correlation window ----------

def _err(origin, at, message='something failed', severity='error', source='journal-system',
         count=1, first_at=None):
    return {'source': source, 'origin': origin, 'at': at, 'count': count,
            'first_at': first_at if first_at is not None else at,
            'severity': severity, 'message': message, 'detail': {}}


def test_resource_window_says_nothing_was_retained_rather_than_nothing_happened(clean_history):
    """The distinction that matters: 'no samples' and 'the machine was calm' are
    different answers, and only one of them is knowable from a five-minute buffer."""
    w = system_service.resource_window(time.time() - 86400)
    assert w['ok'] is False
    assert w['samples'] == 0
    assert 'nothing was retained' in w['reason']
    assert w['metrics'] == {}


def test_resource_window_reports_the_range_it_saw(clean_history):
    now = time.time()
    clean_history.extend([_sample(now - 60, memory=40.0), _sample(now, memory=88.0),
                          _sample(now + 60, memory=70.0)])
    w = system_service.resource_window(now, window=300.0)
    assert w['ok'] is True and w['samples'] == 3
    assert w['metrics']['memory']['min'] == 40.0
    assert w['metrics']['memory']['max'] == 88.0


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_error_detail_shows_what_else_happened_around_it(user: User, monkeypatch,
                                                               clean_history):
    """The CIFS case: the NAS timing out and a media container stalling are one event
    seen twice. Reading either alone tells you the wrong story."""
    now = time.time()
    _stub_page(monkeypatch, errors=_errors([
        _err('kernel', now, 'CIFS: VFS: \\\\192.168.1.213 has not responded in 180 seconds'),
        _err('plex', now - 90, 'container exited with code 137', source='container'),
        _err('unrelated', now - 7200, 'hours away, not in the window'),
    ]))
    await user.open('/lab-health-test')
    await user.should_see('kernel')
    user.find(marker=f'error-row-kernel-{int(now)}').click()
    await user.should_see('AROUND THIS TIME')
    await user.should_see('container exited with code 137')
    await user.should_see('1m before')
    # The 2h-old error is still in the list behind the dialog, so this asserts on the
    # correlation row itself: nothing that far out earns a place in the window.
    await user.should_not_see('2.0h before')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_error_detail_admits_it_kept_no_resource_readings_for_an_old_error(
        user: User, monkeypatch, clean_history):
    now = time.time()
    _stub_page(monkeypatch, errors=_errors([_err('kernel', now, 'a lone error')]))
    await user.open('/lab-health-test')
    await user.should_see('kernel')
    user.find(marker=f'error-row-kernel-{int(now)}').click()
    await user.should_see('No other error was logged in this window')
    await user.should_see('nothing was retained for that time')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_error_detail_pairs_resource_readings_with_the_error_when_it_has_them(
        user: User, monkeypatch, clean_history):
    now = time.time()
    clean_history.extend([_sample(now - 120, memory=41.0), _sample(now - 60, memory=77.0),
                          _sample(now, memory=93.0)])
    _stub_page(monkeypatch, errors=_errors([_err('kernel', now, 'a lone error')]))
    await user.open('/lab-health-test')
    await user.should_see('kernel')
    user.find(marker=f'error-row-kernel-{int(now)}').click()
    await user.should_see('Memory used 41–93%')
    await user.should_see('3 samples')


# ---------- F14: network & reachability ----------

def test_a_mounted_share_that_does_not_answer_is_reported_down(monkeypatch):
    """The 22 Aug failure exactly: os.path.ismount() kept passing for an afternoon while
    the NAS logged 180-second timeouts. Being in the mount table is not being alive."""
    monkeypatch.setattr(system_service.os.path, 'ismount', lambda p: True)
    monkeypatch.setattr(system_service, '_run',
                        lambda *a, **kw: (False, 'timed out after 5s'))
    m = system_service.probe_mount('/mnt/Multimedia')
    assert m['mounted'] is True         # the mount table still says yes
    assert m['responded'] is False      # and it is still down
    assert m['ok'] is False
    assert 'did not answer' in m['error']


def test_an_unmounted_share_is_distinguished_from_an_unresponsive_one(monkeypatch):
    monkeypatch.setattr(system_service.os.path, 'ismount', lambda p: False)
    m = system_service.probe_mount('/mnt/Multimedia')
    assert m['mounted'] is False and m['responded'] is False
    assert 'NOT MOUNTED' in m['error']


def test_a_slow_share_is_flagged_before_it_becomes_a_dead_one(monkeypatch):
    monkeypatch.setattr(system_service.os.path, 'ismount', lambda p: True)
    monkeypatch.setattr(system_service, '_run',
                        lambda *a, **kw: (time.sleep(1.05), (True, '100 50'))[1])
    m = system_service.probe_mount('/mnt/Multimedia')
    assert m['ok'] is True and m['slow'] is True


def test_an_endpoint_that_answers_unhappily_is_not_the_same_as_unreachable(monkeypatch):
    """A 500 proves the service is listening. Folding it in with 'did not answer' would
    send you looking at the network when the problem is the service."""
    class _Resp:
        status_code = 503
    monkeypatch.setattr('requests.get', lambda *a, **kw: _Resp())
    e = system_service._probe_endpoint('thing', 'http://x/health')
    assert e['reached'] is True and e['ok'] is False
    assert e['status'] == 503


def test_an_unreachable_endpoint_says_so_and_keeps_the_reason(monkeypatch):
    def boom(*a, **kw):
        raise OSError('connection refused')
    monkeypatch.setattr('requests.get', boom)
    e = system_service._probe_endpoint('thing', 'http://x/health')
    assert e['reached'] is False and e['ok'] is False
    assert e['status'] is None
    assert 'connection refused' in e['error']


def test_tailscale_lists_only_lab_peers_not_the_family_laptops(monkeypatch):
    """The tailnet carries phones and family machines. A lab health page listing who is
    online is a presence tracker, which is neither its job nor anybody's business."""
    payload = {
        'BackendState': 'Running',
        'TailscaleIPs': ['100.87.245.107'],
        'Self': {'HostName': 'linuxbox-GT70'},
        'Peer': {
            'a': {'HostName': 'Omega', 'Online': True, 'OS': 'windows'},
            'b': {'HostName': 'JoanDell5300', 'Online': False, 'OS': 'windows'},
            'c': {'HostName': 'Pixel 10 Pro XL', 'Online': True, 'OS': 'android'},
            'd': {'HostName': 'steamdeck', 'Online': False, 'OS': 'linux'},
        },
    }
    monkeypatch.setattr(system_service, '_run',
                        lambda *a, **kw: (True, __import__('json').dumps(payload)))
    ts = system_service.get_tailscale()
    hosts = {p['host'] for p in ts['peers']}
    assert hosts == {'Omega', 'steamdeck'}
    assert ts['ok'] is True


def test_tailscale_down_fails_closed_rather_than_reporting_an_empty_tailnet(monkeypatch):
    monkeypatch.setattr(system_service, '_run',
                        lambda *a, **kw: (False, 'tailscale: command not found'))
    ts = system_service.get_tailscale()
    assert ts['ok'] is False
    assert 'not found' in ts['error']
    assert ts['peers'] == []      # empty, but ok=False says why


def test_qnap2_is_never_probed():
    """ADR 22: the off-limits backup vault. The restic job is the only sanctioned thing
    that talks to it, and nothing here may quietly become the second."""
    blob = ' '.join(url for _, url in system_service._ENDPOINTS)
    assert '192.168.1.171' not in blob
    assert 'qnap2' not in blob.lower()
    assert system_service.NAS_MOUNT == '/mnt/Multimedia'


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_dead_endpoint_cannot_sit_under_a_green_banner(user: User, monkeypatch):
    """The load-bearing one. The page must never say 'Nothing is broken' directly above
    a panel listing a service that did not answer."""
    reach = dict(_HEALTHY_REACH, ok=False, down=['Omega — Ollama'], endpoints=[
        {'name': 'Omega — Ollama', 'url': 'http://100.74.2.92:11434/api/tags',
         'ok': False, 'reached': False, 'status': None, 'latency_ms': 4000.0,
         'error': 'ConnectTimeout: timed out'},
    ])
    _stub_page(monkeypatch, errors=_errors([]), reach=reach)
    await user.open('/lab-health-test')
    await user.should_see('Something is broken')
    await user.should_see('not reachable: Omega — Ollama')
    await user.should_see('did not answer')
    await user.should_not_see('Nothing is broken')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_all_clear_requires_reachability_to_have_answered(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('every endpoint answered')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_the_page_shows_host_uptime(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('This host has been up')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_container_detail_says_what_the_container_actually_is(user: User, monkeypatch):
    """An image name answers 'what is it called', not 'what is it for'."""
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'gluetun', 'Status': 'Up 3 hours', 'Labels': ''}])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    monkeypatch.setattr(system_service, 'get_container_detail', lambda *a, **kw: {
        'ok': True, 'error': None, 'name': 'gluetun', 'state': 'running', 'health': None,
        'description': 'VPN gateway container. qbittorrent uses its network namespace.',
        'description_source': 'catalog', 'description_hint': None,
        'restarts': 0, 'started_at': '', 'finished_at': '', 'exit_code': 0,
        'oom_killed': False, 'image': 'qmcgaw/gluetun:v3', 'project': None, 'service': None,
        'ports': [], 'mounts': [], 'stats': None, 'stats_error': None,
        'logs': [], 'log_error': None})

    await user.open('/lab-health-test')
    await user.should_see('gluetun')
    user.find(marker='container-gluetun').click()
    await asyncio.sleep(0.3)
    await user.should_see('VPN gateway container. qbittorrent uses its network namespace.')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_an_undescribed_container_says_so_instead_of_rendering_blank(
        user: User, monkeypatch):
    """Blank space reads as 'nothing to report'. It actually means nobody wrote it
    down, and the dialog has to say which."""
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'context-server', 'Status': 'Up 1 hour', 'Labels': ''}])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    monkeypatch.setattr(system_service, 'get_container_detail', lambda *a, **kw: {
        'ok': True, 'error': None, 'name': 'context-server', 'state': 'running',
        'health': None, 'description': None, 'description_source': 'unknown',
        'description_hint': 'Locally built image -- check where it was built from.',
        'restarts': 0, 'started_at': '', 'finished_at': '', 'exit_code': 0,
        'oom_killed': False, 'image': 'context-server-context-server',
        'project': None, 'service': None, 'ports': [], 'mounts': [],
        'stats': None, 'stats_error': None, 'logs': [], 'log_error': None})

    await user.open('/lab-health-test')
    await user.should_see('context-server')
    user.find(marker='container-context-server').click()
    await asyncio.sleep(0.3)
    await user.should_see('No description recorded for this container.')
    await user.should_see('Locally built image -- check where it was built from.')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_vendor_blurb_is_labelled_as_one(user: User, monkeypatch):
    """A curated sentence and an image's own marketing label are different kinds of
    claim; presenting them identically overstates how much anyone here knows."""
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'someapp', 'Status': 'Up 1 hour', 'Labels': ''}])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    monkeypatch.setattr(system_service, 'get_container_detail', lambda *a, **kw: {
        'ok': True, 'error': None, 'name': 'someapp', 'state': 'running', 'health': None,
        'description': 'The best app for doing things.', 'description_source': 'image label',
        'description_hint': None,
        'restarts': 0, 'started_at': '', 'finished_at': '', 'exit_code': 0,
        'oom_killed': False, 'image': 'vendor/someapp:1', 'project': None, 'service': None,
        'ports': [], 'mounts': [], 'stats': None, 'stats_error': None,
        'logs': [], 'log_error': None})

    await user.open('/lab-health-test')
    await user.should_see('someapp')
    user.find(marker='container-someapp').click()
    await asyncio.sleep(0.3)
    await user.should_see("from the image's own label, not written for this host")


# ---------- F13: SMART ----------

def _attrlog(tmp_path, name, row):
    d = tmp_path / 'smartd'
    d.mkdir(exist_ok=True)
    (d / f'attrlog.{name}.ata.csv').write_text(row + '\n', encoding='utf-8')
    return d


def test_smart_reads_the_newest_row_of_smartds_own_log(tmp_path, monkeypatch):
    """Read smartd's output rather than shelling out to smartctl: smartctl needs root,
    this app is a user service, and smartd is already polling so nothing wakes a disk."""
    d = _attrlog(tmp_path, 'DISK-1',
                 '2026-09-09 22:08:57;\t5;100;0;\t9;100;6600;\t12;100;138;\t187;100;0;\t'
                 '196;100;0;\t197;100;0;\t198;100;0;\t199;100;0;\t231;96;96;\t194;66;34;')
    monkeypatch.setattr(system_service, 'SMARTD_STATE_DIR', str(d))
    out = system_service.get_disk_health()
    assert out['ok'] is True
    disk = out['disks'][0]
    assert disk['failing'] == [] and disk['unreported'] == []
    assert disk['power_on_hours'] == 6600
    assert disk['life_left_pct'] == 96
    assert disk['temp_c'] == 34


def test_a_nonzero_critical_attribute_is_reported_as_failing(tmp_path, monkeypatch):
    d = _attrlog(tmp_path, 'DISK-1',
                 '2026-09-09 22:08:57;\t5;100;7;\t9;100;6600;\t187;100;0;\t196;100;0;\t'
                 '197;100;2;\t198;100;0;\t199;100;0;')
    monkeypatch.setattr(system_service, 'SMARTD_STATE_DIR', str(d))
    disk = system_service.get_disk_health()['disks'][0]
    names = {f['name']: f['raw'] for f in disk['failing']}
    assert names == {'Reallocated sectors': 7, 'Current pending sectors': 2}


def test_an_attribute_the_drive_does_not_report_is_unknown_not_zero(tmp_path, monkeypatch):
    """The load-bearing one. This host's SSD publishes no attribute 5 at all. Treating
    absent as zero would render 'no reallocated sectors' -- a reassurance the drive never
    actually gave."""
    d = _attrlog(tmp_path, 'DISK-1', '2026-09-09 22:08:57;\t9;100;6600;\t199;100;0;')
    monkeypatch.setattr(system_service, 'SMARTD_STATE_DIR', str(d))
    disk = system_service.get_disk_health()['disks'][0]
    assert 'Reallocated sectors' in disk['unreported']
    assert 'Reallocated sectors' not in disk['clean']
    assert disk['failing'] == []          # unknown is not failing either


def test_smart_fails_closed_when_smartd_has_written_nothing(tmp_path, monkeypatch):
    empty = tmp_path / 'smartd'
    empty.mkdir()
    monkeypatch.setattr(system_service, 'SMARTD_STATE_DIR', str(empty))
    out = system_service.get_disk_health()
    assert out['ok'] is False
    assert 'not writing attribute logs' in out['error']
    assert out['disks'] == []


def test_smart_fails_closed_when_the_state_dir_is_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(system_service, 'SMARTD_STATE_DIR', str(tmp_path / 'nope'))
    out = system_service.get_disk_health()
    assert out['ok'] is False and 'does not exist' in out['error']


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_failing_disk_cannot_sit_under_a_green_banner(user: User, monkeypatch):
    smart = {'ok': True, 'error': None, 'read_at': _NOW, 'disks': [
        {'label': 'KINGSTON_SQ500-ABC', 'ok': True, 'error': None, 'read_at': _NOW,
         'sampled': '2026-09-09 22:08:57',
         'failing': [{'name': 'Reallocated sectors', 'id': 5, 'raw': 7}],
         'clean': [], 'unreported': [], 'power_on_hours': 6600, 'power_cycles': 138,
         'life_left_pct': 96, 'temp_c': 34}]}
    _stub_page(monkeypatch, errors=_errors([]), smart=smart)
    await user.open('/lab-health-test')
    await user.should_see('Something is broken')
    await user.should_see('SMART errors on KINGSTON_SQ500-ABC')
    await user.should_see('Reallocated sectors: 7')
    await user.should_not_see('Nothing is broken')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_partly_reporting_drive_is_not_shown_as_clean(user: User, monkeypatch):
    smart = {'ok': True, 'error': None, 'read_at': _NOW, 'disks': [
        {'label': 'DISK-1', 'ok': True, 'error': None, 'read_at': _NOW,
         'sampled': '2026-09-09 22:08:57', 'failing': [], 'clean': ['UDMA CRC errors'],
         'unreported': ['Reallocated sectors'], 'power_on_hours': 10,
         'power_cycles': 1, 'life_left_pct': None, 'temp_c': None}]}
    _stub_page(monkeypatch, errors=_errors([]), smart=smart)
    await user.open('/lab-health-test')
    await user.should_see('No errors in what it reports')
    await user.should_see('absent is not zero')


# ---------- service-level health roll-up ----------

def test_a_container_with_no_healthcheck_is_unchecked_not_healthy():
    """`docker ps` writes "(healthy)" only when the image declares a healthcheck. A bare
    "Up 2 hours" says the process has not exited -- nothing more. Reading that as healthy
    is the running-container-is-not-a-working-service lie in one line of code."""
    assert lab_health_page._container_health('Up 2 hours') == lab_health_page.HEALTH_UNCHECKED
    assert lab_health_page._container_health('Up 2 hours (healthy)') == lab_health_page.HEALTH_HEALTHY


def test_container_health_separates_the_five_states():
    h = lab_health_page._container_health
    assert h('Up 3 days (unhealthy)') == lab_health_page.HEALTH_UNHEALTHY
    assert h('Up 4 seconds (health: starting)') == lab_health_page.HEALTH_STARTING
    assert h('Exited (137) 2 hours ago') == lab_health_page.HEALTH_DOWN
    assert h('Restarting (1) 5 seconds ago') == lab_health_page.HEALTH_STARTING
    assert h('') == lab_health_page.HEALTH_UNCHECKED


def test_unhealthy_is_not_read_as_healthy_by_substring():
    """'unhealthy' contains 'healthy'. Order of checks is load-bearing here."""
    assert lab_health_page._container_health('Up (unhealthy)') == lab_health_page.HEALTH_UNHEALTHY


def test_an_unchecked_container_is_not_coloured_as_verified():
    from components import theme
    assert lab_health_page._container_color('Up 2 hours') != theme.GREEN
    assert lab_health_page._container_color('Up 2 hours (healthy)') == theme.GREEN


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_the_list_says_unchecked_rather_than_implying_health(user: User, monkeypatch):
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'plex', 'Status': 'Up 2 hours', 'Labels': 'com.docker.compose.project=media'},
        {'Names': 'sonarr', 'Status': 'Up 3 days (healthy)',
         'Labels': 'com.docker.compose.project=media'},
    ])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    await user.open('/lab-health-test')
    await user.should_see('no healthcheck declared')
    await user.should_see('1 healthy')
    await user.should_see('1 running, unchecked')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_unchecked_containers_do_not_rank_a_project_as_broken(user: User, monkeypatch):
    """Sorting by "not green" would bury genuinely broken containers under the many that
    simply never declared a healthcheck."""
    status = dict(_HEALTHY_STATUS, containers=[
        {'Names': 'a1', 'Status': 'Up 2 hours', 'Labels': 'com.docker.compose.project=quiet'},
        {'Names': 'a2', 'Status': 'Up 2 hours', 'Labels': 'com.docker.compose.project=quiet'},
        {'Names': 'b1', 'Status': 'Exited (1) 5 minutes ago',
         'Labels': 'com.docker.compose.project=broken'},
    ])
    _stub_page(monkeypatch, errors=_errors([]), status=status)
    await user.open('/lab-health-test')
    await user.should_see('1 down')
    await user.should_see('2 running, unchecked')


# ---------- F15 backups / F16 remote hosts ----------

def test_systemd_timestamps_parse_only_in_unix_form():
    """systemd prints "Wed 2026-09-09 20:18:56 EDT" unless asked for --timestamp=unix.
    The human form must read as 'never' rather than being coerced into a wrong number."""
    assert system_service._systemd_stamp('@1788999536') == 1788999536.0
    assert system_service._systemd_stamp('Wed 2026-09-09 20:18:56 EDT') is None
    assert system_service._systemd_stamp('') is None
    assert system_service._systemd_stamp('@0') is None       # unset, not the epoch
    assert system_service._systemd_stamp('n/a') is None


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_failed_backup_reaches_the_verdict(user: User, monkeypatch):
    backups = dict(_HEALTHY_BACKUPS, jobs=[
        {'unit': 'plane-backup.service', 'manager': 'user', 'description': 'Plane Backup',
         'ok': False, 'never_ran': False, 'result': 'exit-code', 'exit_status': '1',
         'odd_exit': False, 'last_run': _NOW - 7200, 'next_run': _NOW + 7200,
         'last_words': 'could not resolve qnap2', 'log_error': None}])
    _stub_page(monkeypatch, errors=_errors([]), backups=backups)
    await user.open('/lab-health-test')
    await user.should_see('Something is broken')
    await user.should_see('backup failed: plane-backup.service')
    await user.should_see('could not resolve qnap2')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_failed_backup_is_not_counted_twice_with_its_failed_unit(user: User,
                                                                        monkeypatch):
    """plane-backup.service appears both as a failed unit and as a failed backup. Naming
    it in both halves of one sentence reads as two separate problems."""
    backups = dict(_HEALTHY_BACKUPS, jobs=[
        {'unit': 'plane-backup.service', 'manager': 'user', 'description': 'Plane Backup',
         'ok': False, 'never_ran': False, 'result': 'exit-code', 'exit_status': '1',
         'odd_exit': False, 'last_run': _NOW, 'next_run': None, 'last_words': None,
         'log_error': None}])
    _stub_page(monkeypatch, backups=backups, errors=_errors([
        {'source': 'unit', 'origin': 'plane-backup.service', 'at': _NOW, 'count': 1,
         'first_at': _NOW, 'severity': 'critical', 'message': 'failed state',
         'detail': {'manager': 'user', 'unit': 'plane-backup.service'}}]))
    await user.open('/lab-health-test')
    await user.should_see('Something is broken')
    await user.should_not_see('backup failed: plane-backup.service')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_host_we_cannot_reach_is_not_called_offline(user: User, monkeypatch):
    """"Offline" is a measurement. For a host this box cannot ask, we did not take it."""
    hosts = dict(_HEALTHY_HOSTS, hosts=[
        {'label': 'Node G', 'name': 'Media Box', 'detail': 'Remote Windows box',
         'off_limits': False, 'online': None, 'on_tailnet': False}])
    _stub_page(monkeypatch, errors=_errors([]), hosts=hosts)
    await user.open('/lab-health-test')
    await user.should_see('no way to check from here')
    await user.should_not_see('not on the tailnet now')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_qnap2_renders_as_off_limits_never_as_unknown(user: User, monkeypatch):
    """ADR 22. It must be visibly a policy decision, not a gap in coverage somebody might
    helpfully close by adding a probe."""
    _stub_page(monkeypatch, errors=_errors([]))
    await user.open('/lab-health-test')
    await user.should_see('off-limits by policy')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_stale_inventory_says_it_is_unverified(user: User, monkeypatch):
    hosts = dict(_HEALTHY_HOSTS, age_days=140.0, stale=True)
    _stub_page(monkeypatch, errors=_errors([]), hosts=hosts)
    await user.open('/lab-health-test')
    await user.should_see('past the 90-day review window')


# ---------- alerts from homelab-monitoring (Chris, 2026-09-11) ----------
#
# Read-only display of what Alertmanager holds. Two rules decided with the panel: only an
# ACTIVE critical counts against the banner, and a unit monitoring has exempted reads as
# known -- but only while Alertmanager answers, so an unverifiable exemption never hides a
# failure.

class _AMResponse:
    def __init__(self, payload, status=200):
        self._payload, self.status_code = payload, status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f'HTTP {self.status_code}')

    def json(self):
        return self._payload


def _am_alert(alertname, severity, *, state='active', inhibited=False, **labels):
    # `alertname`, not `name`: container exemptions carry a `name` label of their own.
    return {'labels': {'alertname': alertname, 'severity': severity, **labels},
            'annotations': {'summary': f'{alertname} summary',
                            'runbook': f'look at {alertname}'},
            'status': {'state': state, 'inhibitedBy': ['x'] if inhibited else [],
                       'silencedBy': [], 'mutedBy': []},
            'startsAt': '2026-09-11T15:04:39.662Z'}


def test_alerts_reader_fails_closed_when_alertmanager_does_not_answer(monkeypatch):
    import requests

    def boom(*a, **kw):
        raise requests.ConnectionError('connection refused')

    monkeypatch.setattr(requests, 'get', boom)
    result = system_service.get_alerts()
    assert result['ok'] is False and 'ConnectionError' in result['error']
    # No exemptions either: an exemption nobody could read must not hide a failure.
    assert result['alerts'] == [] and result['exempt_units'] == {}


def test_alerts_reader_rejects_an_answer_that_is_not_a_list(monkeypatch):
    import requests
    monkeypatch.setattr(requests, 'get', lambda *a, **kw: _AMResponse({'status': 'error'}))
    assert system_service.get_alerts()['ok'] is False


def test_alerts_reader_sorts_firing_from_held_back_from_exemptions(monkeypatch):
    """The shapes are the live ones from 2026-09-11: a suppressed critical about
    plane-backup, a 'known' repo alert, and exemption reminders for a unit and a container."""
    import requests
    payload = [
        # Far-future dates: a real one would start failing this test the day it passed.
        _am_alert('MonitoringExemption', 'silent', unit='plane-backup.service',
                  id='plane-backup', review_after='2999-10-01'),
        _am_alert('MonitoringExemption', 'silent', name='freqtrade-dry1', id='freqtrade-dry1',
                  review_after='2999-11-15'),
        _am_alert('SystemdUnitFailed', 'critical', state='suppressed', inhibited=True,
                  unit='plane-backup.service', manager='user'),
        _am_alert('repo-missing', 'known', source='plane-backup'),
        _am_alert('RootFilling', 'degraded', source='node'),
        _am_alert('HostDown', 'critical', source='node'),
    ]
    monkeypatch.setattr(requests, 'get', lambda *a, **kw: _AMResponse(payload))
    result = system_service.get_alerts()
    assert result['ok'] is True
    kinds = [(a['name'], a['kind']) for a in result['alerts']]
    assert kinds[:2] == [('HostDown', 'paging'), ('RootFilling', 'paging')]
    assert ('SystemdUnitFailed', 'accepted') in kinds and ('repo-missing', 'accepted') in kinds
    held = next(a for a in result['alerts'] if a['name'] == 'SystemdUnitFailed')
    assert held['held_by'] == 'inhibited' and held['manager'] == 'user'
    assert set(result['exempt_units']) == {'plane-backup.service'}
    assert set(result['exempt_names']) == {'freqtrade-dry1'}
    assert result['exempt_units']['plane-backup.service']['review_after'] == '2999-10-01'


def _reader_alerts(*items):
    """Build what get_alerts() returns, via the real classifier."""
    return dict(_HEALTHY_ALERTS, alerts=list(items),
                exempt_units={a['unit']: {'id': a['rule_id'], 'review_after': a['review_after']}
                              for a in items if a['kind'] == 'exemption' and a['unit']},
                exempt_names={a['subject']: {'id': a['rule_id'], 'review_after': a['review_after']}
                              for a in items if a['kind'] == 'exemption' and not a['unit']})


def _alert(name, severity, kind, *, unit=None, subject=None, held_by=None, review_after=None,
           state='active'):
    return {'name': name, 'severity': severity, 'state': state, 'kind': kind,
            'held_by': held_by, 'since': _NOW - 600, 'unit': unit, 'manager': 'user',
            'subject': subject or unit, 'summary': f'{name} summary', 'description': '',
            'runbook': f'look at {name}', 'rule_id': name, 'review_after': review_after}


_PLANE_BACKUP_FAILED = [
    {'source': 'unit', 'origin': 'plane-backup.service', 'at': _NOW, 'count': 1,
     'first_at': _NOW, 'severity': 'critical',
     'message': 'plane-backup.service is in a failed state (failed)',
     'detail': {'manager': 'user', 'unit': 'plane-backup.service'}}]


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_firing_critical_alert_reaches_the_verdict(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]), alerts=_reader_alerts(
        _alert('HostDown', 'critical', 'paging', subject='nas')))
    await user.open('/lab-health-test')
    await user.should_see('Something is broken')
    await user.should_see('HostDown (nas)', kind=ui.label)


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_held_back_critical_does_not_turn_the_banner_red(user: User, monkeypatch):
    """Monitoring suppressed it on purpose. Turning the banner red would overrule that."""
    _stub_page(monkeypatch, errors=_errors([]), alerts=_reader_alerts(
        _alert('SystemdUnitFailed', 'critical', 'accepted', unit='quant-lab.service',
               held_by='inhibited')))
    await user.open('/lab-health-test')
    await user.should_see('Nothing is broken')
    await user.should_see('critical · held back (inhibited)')
    await user.should_see(marker='alerts-none-firing')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_failure_monitoring_has_exempted_reads_as_known(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors(_PLANE_BACKUP_FAILED), alerts=_reader_alerts(
        _alert('MonitoringExemption', 'silent', 'exemption', unit='plane-backup.service',
               review_after='2026-10-01')))
    await user.open('/lab-health-test')
    await user.should_see('Nothing unexpected is broken')
    await user.should_see('Known and exempted by monitoring: plane-backup.service', kind=ui.label)
    await user.should_not_see('Something is broken')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_an_unreadable_alertmanager_applies_no_exemptions(user: User, monkeypatch):
    """Fail closed: the exemption cannot be verified, so the failure counts."""
    _stub_page(monkeypatch, errors=_errors(_PLANE_BACKUP_FAILED),
               alerts={'ok': False, 'error': 'ConnectionError: refused', 'read_at': _NOW,
                       'alerts': [], 'exempt_units': {}, 'exempt_names': {}})
    await user.open('/lab-health-test')
    await user.should_see('Something is broken')
    await user.should_see("Could not read homelab-monitoring's alerts — ConnectionError: refused",
                          kind=ui.label)
    await user.should_not_see(marker='alerts-none-firing')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_exemption_reminders_collapse_into_one_line(user: User, monkeypatch):
    _stub_page(monkeypatch, errors=_errors([]), alerts=_reader_alerts(
        _alert('MonitoringExemption', 'silent', 'exemption', unit='livescore.service'),
        _alert('MonitoringExemption', 'silent', 'exemption', unit='quant-lab.service')))
    await user.open('/lab-health-test')
    await user.should_see(marker='alert-exemptions')
    with user.client:
        expansion = next(iter(user.find(marker='alert-exemptions').elements))
        assert expansion.props.get('label') == '2 exemptions in force'


# ---------- AntiGravity's review of the alerts panel, 2026-09-11 ----------

def test_an_expired_or_undated_exemption_is_shown_but_not_applied(monkeypatch):
    import requests
    payload = [
        _am_alert('MonitoringExemption', 'silent', unit='old.service', id='old',
                  review_after='2000-01-01'),
        _am_alert('MonitoringExemption', 'silent', unit='undated.service', id='undated'),
        _am_alert('MonitoringExemption', 'silent', unit='current.service', id='current',
                  review_after='2999-01-01'),
    ]
    monkeypatch.setattr(requests, 'get', lambda *a, **kw: _AMResponse(payload))
    result = system_service.get_alerts()
    assert set(result['exempt_units']) == {'current.service'}
    expired = {a['subject']: a['expired'] for a in result['alerts']}
    assert expired == {'old.service': True, 'undated.service': True, 'current.service': False}


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_an_unprocessed_critical_does_not_count_yet(user: User, monkeypatch):
    """Chris's rule is ACTIVE critical only. 'unprocessed' has not been run past the
    silences and inhibitions yet, and may turn out suppressed a moment later."""
    _stub_page(monkeypatch, errors=_errors([]), alerts=_reader_alerts(
        _alert('HostDown', 'critical', 'paging', subject='nas', state='unprocessed')))
    await user.open('/lab-health-test')
    await user.should_see('Nothing is broken')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_an_exempted_container_reads_as_known_not_as_logged_errors(user: User,
                                                                        monkeypatch):
    _stub_page(monkeypatch, errors=_errors([
        {'source': 'container', 'origin': 'freqtrade-dry1', 'at': 0.0, 'count': 1,
         'first_at': 0.0, 'severity': 'error',
         'message': 'container freqtrade-dry1 exited with code 137',
         'detail': {'container': 'freqtrade-dry1'}}]),
        alerts=_reader_alerts(_alert('MonitoringExemption', 'silent', 'exemption',
                                     subject='freqtrade-dry1', review_after='2999-01-01')))
    await user.open('/lab-health-test')
    await user.should_see('Nothing unexpected is broken')
    await user.should_not_see('Errors logged')


@pytest.mark.nicegui_main_file('test_lab_health.py')
async def test_a_failed_backup_and_its_alert_are_named_once(user: User, monkeypatch):
    backups = dict(_HEALTHY_BACKUPS, jobs=[
        {'unit': 'x-backup.service', 'manager': 'user', 'description': 'X Backup',
         'ok': False, 'never_ran': False, 'result': 'exit-code', 'exit_status': '1',
         'odd_exit': False, 'last_run': _NOW, 'next_run': None, 'last_words': None,
         'log_error': None}])
    _stub_page(monkeypatch, errors=_errors([]), backups=backups, alerts=_reader_alerts(
        _alert('SystemdUnitFailedLogged', 'critical', 'paging', unit='x-backup.service')))
    await user.open('/lab-health-test')
    await user.should_see('backup failed: x-backup.service')
    await user.should_not_see('critical alert(s) firing')
