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
                   'memory': {'plex': '1GiB'}, 'daemon_active': True}


def _errors(entries, ok=True, error=None):
    return {'ok': ok, 'entries': entries, 'read_at': _NOW, 'error': error,
            'sources': {'journal-user': {'ok': ok, 'error': error}}}


def _stub_page(monkeypatch, *, errors, units=None, status=None):
    monkeypatch.setattr(system_service, 'get_errors', lambda *a, **kw: errors)
    monkeypatch.setattr(system_service, 'get_units',
                        lambda *a, **kw: units or {'ok': True, 'units': [], 'error': None})
    monkeypatch.setattr(system_service, 'get_status', lambda *a, **kw: status or _HEALTHY_STATUS)
    monkeypatch.setattr(system_service, 'get_logs', lambda *a, **kw: [])


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
