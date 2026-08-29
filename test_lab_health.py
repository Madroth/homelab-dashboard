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


def _stub_page(monkeypatch, *, errors, units=None, status=None, resources=None):
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
