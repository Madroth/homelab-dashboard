"""Verification for pages/media.py's per-item-refreshable optimization (2026-08-01),
mirroring the fix + test pattern already applied to pages/intake.py after a reported
1s+ delay per toggle was traced to render_articles.refresh()'s full-list rebuild.
Monkeypatches services/media.py directly (an in-memory fake queue) rather than the
real sqlite-backed media-curator DB -- never touches real media state."""
import asyncio
import time

import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.testing import User

from pages import media as media_page
from services import media as media_service


def _item(iid, *, status='pending', title=None, media_type='movie', needs_intervention=False):
    return {
        'id': iid,
        'status': status,
        'media_type': media_type,
        'proposed_title': title or f'Title {iid}',
        'original_filename': f'{iid}.mkv',
        'proposed_path': f'/media/{iid}',
        'created_at': '2026-08-01',
        'metadata': {},
        'needs_intervention': needs_intervention,
    }


@pytest.fixture
def fake_media_service(monkeypatch):
    queue = [_item(str(i)) for i in range(3)]

    def _get_queue(*a, **kw):
        # Fresh dicts every call, as sqlite rows are. Handing back the same objects let a
        # test's edit to the fake mutate the page's stored copy too, so "has anything
        # changed?" compared an object with itself and could never say yes.
        return [dict(it) for it in queue]

    def _approve(item_id):
        for it in queue:
            if it['id'] == item_id:
                it['status'] = 'approved'
        return True, None

    def _reject(item_id):
        queue[:] = [it for it in queue if it['id'] != item_id]
        return True, None

    def _edit(item_id, title):
        for it in queue:
            if it['id'] == item_id:
                it['proposed_title'] = title
        return True, None

    def _undo(item_id):
        for it in queue:
            if it['id'] == item_id:
                it['status'] = 'pending'
        return True, None

    monkeypatch.setattr(media_service, 'get_queue', _get_queue)
    monkeypatch.setattr(media_service, 'approve', _approve)
    monkeypatch.setattr(media_service, 'reject', _reject)
    monkeypatch.setattr(media_service, 'edit', _edit)
    monkeypatch.setattr(media_service, 'undo', _undo)
    # Without this every page load read the REAL media-curator queue.db and stat'ed its
    # rejected files on the NAS mount, despite the module docstring's promise -- and a slow
    # NAS then decided whether a UI test passed. Tests that care override it.
    monkeypatch.setattr(media_service, 'get_rejected', lambda *a, **kw: [])
    return queue


@ui.page('/media-test')
def _media_test_page():
    media_page.build()


ui.run_with(FastAPI())


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_toggle_select_flips_without_server_round_trip(user: User, fake_media_service):
    await user.open('/media-test')
    await user.should_see('Title 0')

    calls = []
    monkeypatch_calls = media_service.get_queue
    media_service.get_queue = lambda *a, **kw: (calls.append(1) or monkeypatch_calls(*a, **kw))
    try:
        user.find(marker='row-select-0').click()
        await asyncio.sleep(0.2)
    finally:
        media_service.get_queue = monkeypatch_calls
    assert not calls, 'toggle_select should never re-fetch the queue -- selection is local-only state'


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_approve_updates_row_and_stays_visible(user: User, fake_media_service):
    """Approving a pending item changes its status (and thus its row's rendering) but
    doesn't remove it from the queue -- proving the single-row fast path (reload()
    with a changed_id hint) renders the updated status correctly."""
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='approve-0').click()
    await user.should_see('Auto-sorted: Title 0', retries=20)  # approved-row rendering
    assert fake_media_service[0]['status'] == 'approved'


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_reject_removes_row_via_full_refresh_fallback(user: User, fake_media_service):
    """Rejecting removes the item from the queue entirely (a membership change) --
    proving reload()'s before/after id comparison correctly falls back to a full
    render_queue.refresh() instead of leaving a stale row from the fast path."""
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='reject-0').click()
    await asyncio.sleep(0.2)
    user.find(marker='confirm-dialog-confirm').click()  # confirm the danger dialog
    await user.should_not_see('Title 0', retries=20)
    assert all(it['id'] != '0' for it in fake_media_service)


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_edit_title_updates_single_row(user: User, fake_media_service):
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='edit-0').click()
    await asyncio.sleep(0.2)
    title_input = user.find(kind=ui.input)
    with user.client:
        for el in title_input.elements:
            el.value = 'Renamed Item'
    user.find(content='Save').click()
    await asyncio.sleep(0.3)  # do_edit() runs as a background task, not awaited by .click()

    await user.should_see('Renamed Item', retries=20)
    assert fake_media_service[0]['proposed_title'] == 'Renamed Item'


def _row_element_id(user, index):
    return next(iter(user.find(marker=f'row-select-{index}').elements)).id


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_toggle_select_rebuilds_one_row_not_the_whole_queue(user: User, monkeypatch):
    """Against a ~80-item queue (the real media-curator size that motivated the fix),
    toggling selection must refresh only the row that changed.

    This asserts work done rather than seconds elapsed. It used to assert a 0.5s
    wall-clock budget and failed 2 runs in 3 on a loaded machine -- this host also runs
    a game server and a media daemon, so a timing threshold here measures the host's
    mood, not the code. Element identity is the honest signal: NiceGUI's .refresh()
    tears its subtree down and rebuilds it, so a full-list rebuild gives every row new
    elements while a single-row refresh touches exactly one.
    """
    queue = [_item(str(i)) for i in range(80)]
    monkeypatch.setattr(media_service, 'get_queue', lambda *a, **kw: list(queue))

    await user.open('/media-test')
    await user.should_see('Title 0')
    # Let the initial async load finish replacing the skeleton. Measured: ids churn once
    # right after open, then hold. The page also reloads every 5s, which is two orders of
    # magnitude outside the window below -- unlike the 0.5s budget this test used to
    # assert, that margin does not shrink when the host is busy.
    await asyncio.sleep(1.0)

    untouched = [0, 39, 41, 79]
    before = {i: _row_element_id(user, i) for i in untouched}
    before_target = _row_element_id(user, 40)

    user.find(marker='row-select-40').click()
    await asyncio.sleep(0.1)

    assert _row_element_id(user, 40) != before_target, 'the toggled row should have been rebuilt'
    for i in untouched:
        assert _row_element_id(user, i) == before[i], (
            f'row {i} was rebuilt too -- this is the full-list rebuild the fix removed')


# ---------- an open dialog survives the page's own poll ----------
#
# Captured 2026-09-11 by the failure recorder in conftest.py, the first time a failing run
# of this file was ever kept: the confirm and edit dialogs had vanished between the click
# and the next step. NiceGUI ties a dialog's lifetime to an invisible canary element placed
# wherever the click happened -- here, inside a queue row -- and deletes the dialog when
# that canary is collected. reload() rebuilt the whole queue on its 5s poll, so any poll
# landing while a dialog was open destroyed it, and the handler awaiting it hung forever.
# Under load the tests straddle a poll more often, which is the flake; on the live page it
# was your Edit Title box disappearing mid-typing.
#
# Two fixes, tested separately: components/page_dialog.py anchors dialogs to the page, and
# the poll no longer rebuilds a queue that has not changed. The dialog tests below make the
# queue change on purpose, so they still prove the first fix with the second in place.

async def _outlast_a_poll(user, queue):
    """Something arrives in the queue -- the daemon's everyday business -- so the next poll
    genuinely rebuilds the list rather than skipping an unchanged one. Waits until it has."""
    queue.append(_item('arrived'))
    await user.should_see('Title arrived', retries=70)   # the poll is every 5s
    import gc
    gc.collect()   # the canary may sit in a reference cycle; don't let timing hide the bug
    await asyncio.sleep(0.2)


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_an_open_edit_dialog_survives_the_poll(user: User, fake_media_service):
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='edit-0').click()
    await user.should_see(kind=ui.input)
    await _outlast_a_poll(user, fake_media_service)

    await user.should_see(kind=ui.input, retries=1)
    title_input = user.find(kind=ui.input)
    with user.client:
        for el in title_input.elements:
            el.value = 'Typed Through A Poll'
    user.find(content='Save').click()
    # Not should_see(): the dialog's own input shows this text until it is discarded.
    await user.should_see(content='Typed Through A Poll', kind=ui.label)
    assert fake_media_service[0]['proposed_title'] == 'Typed Through A Poll'


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_an_open_reject_confirmation_survives_the_poll(user: User, fake_media_service):
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='reject-0').click()
    await user.should_see(marker='confirm-dialog-confirm')
    await _outlast_a_poll(user, fake_media_service)

    await user.should_see(marker='confirm-dialog-confirm', retries=1)
    user.find(marker='confirm-dialog-confirm').click()
    await user.should_not_see('Title 0')
    assert all(it['id'] != '0' for it in fake_media_service)


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_a_poll_that_finds_nothing_new_rebuilds_nothing(user: User, fake_media_service):
    """The poll used to tear down and rebuild every row every five seconds whether or not
    anything had changed -- deleting whichever button you were reaching for."""
    await user.open('/media-test')
    await user.should_see('Title 0')
    await asyncio.sleep(0.5)
    before = [_row_element_id(user, i) for i in range(3)]

    await asyncio.sleep(5.5)   # at least one poll

    assert [_row_element_id(user, i) for i in range(3)] == before


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_a_change_elsewhere_in_the_queue_still_renders(user: User, fake_media_service):
    """AntiGravity's review, 2026-09-11. The single-row fast path refreshes only the row you
    acted on but stores the whole refetched queue -- so a change the daemon made to ANOTHER
    item was recorded as already shown, and the poll, seeing nothing new, never drew it."""
    await user.open('/media-test')
    await user.should_see('Title 1')
    await asyncio.sleep(0.5)

    fake_media_service[1]['proposed_title'] = 'Renamed By The Daemon'   # a background change
    user.find(marker='approve-0').click()
    await user.should_see('Auto-sorted: Title 0')

    await user.should_see('Renamed By The Daemon', retries=70)   # through at least one poll


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_a_closed_dialog_is_deleted_not_just_hidden(user: User, fake_media_service):
    """Anchoring dialogs to the page means nothing else will ever clean them up, so
    page_dialog() must -- or every detail dialog opened in a long-lived Lab Health tab
    stays in it, hidden, until the tab closes."""
    await user.open('/media-test')
    await user.should_see('Title 0')
    await asyncio.sleep(0.5)   # let the initial load settle
    with user.client:
        before = len(list(user.current_layout.descendants()))

    user.find(marker='edit-0').click()
    await user.should_see(kind=ui.input)
    user.find(content='Cancel').click()
    await asyncio.sleep(1.0)   # past page_dialog's close transition

    with user.client:
        assert len(list(user.current_layout.descendants())) == before


@ui.page('/blank')
def _blank_page():
    ui.label('Nothing here')


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_a_closed_tab_leaves_nothing_in_the_per_tab_registries(user: User,
                                                                     fake_media_service):
    """AntiGravity's review, 2026-09-11: live_state and ai_context keyed their entries by
    client id and never removed them, so every page view stayed in memory for good."""
    from components import ai_context, live_state
    await user.open('/media-test')
    await user.should_see('Title 0')
    tab = user.client
    assert tab.id in live_state._REGISTRY and tab.id in ai_context._REGISTRY
    await user.open('/blank')
    tab.delete()   # what NiceGUI does to a tab that closed and did not come back
    assert tab.id not in live_state._REGISTRY
    assert tab.id not in ai_context._REGISTRY


def test_no_page_creates_a_dialog_the_poll_can_delete():
    """page_dialog() fixes this once; a bare ui.dialog() anywhere a click handler can
    reach reintroduces it. Every page here rebuilds on a timer."""
    import pathlib
    offenders = [f'{p}:{n}' for p in [*pathlib.Path('pages').glob('*.py'),
                                      *pathlib.Path('components').glob('*.py')]
                 if p.name != 'page_dialog.py'
                 for n, line in enumerate(p.read_text().splitlines(), 1)
                 if 'ui.dialog(' in line]
    assert not offenders, f'use components.page_dialog.page_dialog() instead: {offenders}'


# ---------- undo(): the filesystem and the database must move together ----------
#
# services/media.py imports media-curator's internals over sys.path with no version
# pin. That repo dropped its UNIQUE index on original_path for a PARTIAL unique index
# over (original_path, file_hash) scoped to pending rows -- so undo(), which writes
# original_path while flipping status back to 'pending', can now raise IntegrityError
# where it previously could not. These tests pin the ordering guarantee rather than
# the index: whatever the database rejects, the file must not be left moved.

import os
import sqlite3


def _undo_db(tmp_path, *, original_path, proposed_path):
    """A stand-in queue.db carrying media-curator's new partial unique index. Returns the
    path: undo() closes whatever connection it is handed, so every caller opens its own."""
    path = tmp_path / 'queue.db'
    db = sqlite3.connect(path)
    db.execute("""CREATE TABLE media_queue (id TEXT PRIMARY KEY, status TEXT,
                  original_path TEXT, proposed_path TEXT, original_filename TEXT,
                  file_hash TEXT, needs_intervention INTEGER DEFAULT 0)""")
    db.execute("""CREATE UNIQUE INDEX idx_pending ON media_queue(original_path, file_hash)
                  WHERE status = 'pending' """)
    db.execute('INSERT INTO media_queue VALUES (?,?,?,?,?,?,?)',
               ('item-1', 'approved', original_path, proposed_path, 'movie.mkv', 'hash-a', 0))
    db.commit()
    db.close()
    return path


def _open(path):
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _add_pending(path, original_path):
    """A pending row already occupying the (original_path, file_hash) an undo will claim
    -- exactly what media-curator's new partial index forbids."""
    db = _open(path)
    db.execute('INSERT INTO media_queue VALUES (?,?,?,?,?,?,?)',
               ('item-2', 'pending', original_path, '/x', 'movie.mkv', 'hash-a', 0))
    db.commit()
    db.close()


def _row(path, item_id='item-1'):
    db = _open(path)
    row = db.execute('SELECT * FROM media_queue WHERE id=?', (item_id,)).fetchone()
    db.close()
    return row


@pytest.fixture
def undo_env(tmp_path, monkeypatch):
    """Real files and a real sqlite database in tmp_path, with DROP_ZONE pointed at it.
    Nothing here can reach the real queue.db or the real drop zone."""
    drop_zone = tmp_path / 'drop'
    library = tmp_path / 'library'
    drop_zone.mkdir()
    library.mkdir()
    proposed = library / 'Movie (2026).mkv'
    proposed.write_text('the file')

    fake_daemon = type('m', (), {'DROP_ZONE': str(drop_zone)})
    monkeypatch.setitem(__import__('sys').modules, 'curator_daemon', fake_daemon)
    return {'tmp_path': tmp_path, 'drop_zone': drop_zone, 'proposed': proposed,
            'dest': drop_zone / 'movie.mkv'}


def test_undo_moves_the_file_and_requeues_the_row(undo_env, monkeypatch):
    path = _undo_db(undo_env['tmp_path'], original_path='/orig/movie.mkv',
                    proposed_path=str(undo_env['proposed']))
    monkeypatch.setattr(media_service, '_get_conn', lambda: _open(path))

    ok, err = media_service.undo('item-1')
    assert (ok, err) == (True, None)
    assert undo_env['dest'].exists()
    assert not undo_env['proposed'].exists()
    row = _row(path)
    assert row['status'] == 'pending'
    assert row['original_path'] == str(undo_env['dest'])


def test_undo_puts_the_file_back_when_the_database_rejects_the_write(undo_env, monkeypatch):
    """The bug agy found: the move happened first and the UPDATE was unguarded, so an
    IntegrityError left the file in the drop zone while the database still called it
    approved and living in the library. Permanently out of sync, from a button press."""
    path = _undo_db(undo_env['tmp_path'], original_path='/orig/movie.mkv',
                    proposed_path=str(undo_env['proposed']))
    _add_pending(path, str(undo_env['dest']))
    monkeypatch.setattr(media_service, '_get_conn', lambda: _open(path))

    ok, err = media_service.undo('item-1')

    assert ok is False
    assert 'left where it was' in err
    # The two halves agree again: file back in the library, row still approved.
    assert undo_env['proposed'].exists(), 'file was not moved back -- this is the data-loss bug'
    assert not undo_env['dest'].exists()
    row = _row(path)
    assert row['status'] == 'approved'
    assert row['proposed_path'] == str(undo_env['proposed'])


def test_undo_refuses_when_the_drop_zone_already_holds_that_name(undo_env, monkeypatch):
    path = _undo_db(undo_env['tmp_path'], original_path='/orig/movie.mkv',
                    proposed_path=str(undo_env['proposed']))
    monkeypatch.setattr(media_service, '_get_conn', lambda: _open(path))
    undo_env['dest'].write_text('a different file already here')

    ok, err = media_service.undo('item-1')
    assert ok is False and 'already exists' in err
    assert undo_env['dest'].read_text() == 'a different file already here'  # untouched
    assert undo_env['proposed'].exists()


def test_undo_reports_a_database_failure_even_with_no_file_to_move(undo_env, monkeypatch):
    """proposed_path missing from disk means nothing is moved -- the row still has to
    be reported honestly rather than raising out of the handler."""
    path = _undo_db(undo_env['tmp_path'], original_path='/orig/movie.mkv',
                    proposed_path=str(undo_env['tmp_path'] / 'gone.mkv'))
    _add_pending(path, str(undo_env['drop_zone'] / 'movie.mkv'))
    monkeypatch.setattr(media_service, '_get_conn', lambda: _open(path))

    ok, err = media_service.undo('item-1')
    assert ok is False
    assert 'Undo failed' in err
    assert _row(path)['status'] == 'approved'


# ---------- the page layer surfaces service failures instead of swallowing them ----------
#
# services/media.py talks to another repo's database over an unpinned import, so its
# calls genuinely fail -- undo() can now come back with an IntegrityError message it
# could not previously produce. A failure that reaches the user as nothing at all is
# the same class of bug as the Send-to-HomeLab spinner that turned forever.

@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_a_failed_approve_tells_the_user_why(user: User, fake_media_service, monkeypatch):
    monkeypatch.setattr(media_service, 'approve',
                        lambda item_id: (False, 'library path is not writable'))
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='approve-0').click()
    await asyncio.sleep(0.3)

    await user.should_see('library path is not writable')


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_a_failed_reject_tells_the_user_why(user: User, fake_media_service, monkeypatch):
    monkeypatch.setattr(media_service, 'reject',
                        lambda item_id: (False, 'file is gone from the drop zone'))
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='reject-0').click()
    await asyncio.sleep(0.2)
    user.find(marker='confirm-dialog-confirm').click()   # reject is confirm-gated
    await asyncio.sleep(0.3)

    await user.should_see('file is gone from the drop zone')


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_a_failed_approve_leaves_the_row_where_it_was(user: User, fake_media_service, monkeypatch):
    """A refused approve must not optimistically mark the row approved -- the file did
    not move, and a row claiming otherwise sends you looking in the wrong place."""
    monkeypatch.setattr(media_service, 'approve', lambda item_id: (False, 'nope'))
    await user.open('/media-test')
    await user.should_see('Title 0')

    user.find(marker='approve-0').click()
    await asyncio.sleep(0.3)

    assert fake_media_service[0]['status'] == 'pending'
    await user.should_see(marker='approve-0')   # still offering the action


# ---------- the media-curator seam ----------
#
# services/media.py borrows five symbols from another repo over sys.path, with no package
# boundary and no version pin. services/media_backend.py is the one place that reaching
# happens, so a refactor over there fails loudly and legibly here instead of surfacing as
# a bare ImportError inside a click handler. These tests hold that seam.

def test_the_borrowed_surface_is_declared_in_exactly_one_place():
    """The list is the point. If something new gets imported from media-curator without
    being declared, the surface has silently grown again -- which is how it reached seven
    scattered call sites in the first place."""
    import re
    from services import media_backend

    source = open('services/media.py', encoding='utf-8').read()
    # Nothing may import media-curator's internals directly any more.
    for module in media_backend.REQUIRED:
        assert not re.search(rf'^\s*from {module} import', source, re.M), (
            f'services/media.py imports from `{module}` directly again; it must go '
            f'through media_backend so the dependency stays declared')
    assert 'sys.path.append' not in source

    # And every symbol it does reach for must be one the contract declares.
    for module, symbol in re.findall(r"media_backend\.get\('(\w+)',\s*'(\w+)'\)", source):
        assert symbol in media_backend.REQUIRED.get(module, ()), (
            f'{module}.{symbol} is used but not declared in REQUIRED')


def test_a_symbol_media_curator_stopped_providing_says_so_by_name(monkeypatch):
    """The failure this exists to improve. Previously: "ImportError: cannot import name
    'approve_item'" from somewhere inside a handler. Now it names the symbol and points at
    the coupling note."""
    from services import media_backend

    class _Stub:
        pass   # library, but approve_item has been renamed away

    monkeypatch.setitem(__import__('sys').modules, 'library', _Stub())
    with pytest.raises(media_backend.MediaBackendUnavailable) as excinfo:
        media_backend.get('library', 'approve_item')
    message = str(excinfo.value)
    assert 'library' in message and 'approve_item' in message
    assert 'media-curator coupling' in message


def test_reaching_for_something_undeclared_is_refused(monkeypatch):
    """Drift in the other direction: code quietly widening the surface."""
    from services import media_backend
    with pytest.raises(media_backend.MediaBackendUnavailable) as excinfo:
        media_backend.get('library', 'some_new_helper')
    assert 'not declared in media_backend.REQUIRED' in str(excinfo.value)


def test_a_missing_media_curator_checks_out_as_unavailable_not_healthy(monkeypatch):
    """Same {'ok', ..., 'error'} contract as the system readers: "the backend is fine"
    and "we could not tell" have to be different answers."""
    from services import media_backend
    monkeypatch.setattr(media_backend, 'MEDIA_CURATOR_PATH', '/nonexistent/media-curator')
    report = media_backend.check()
    assert report['ok'] is False
    assert 'not at /nonexistent/media-curator' in report['error']


def test_reclassify_reports_a_missing_backend_instead_of_raising(monkeypatch):
    """reclassify() is the one path that already degraded on ImportError; it must keep
    degrading, and now say which symbol went missing rather than 'Backend daemon not
    found.'"""
    from services import media_backend

    class _Row(dict):
        def __getitem__(self, k):
            return dict.get(self, k)

    class _Cursor:
        def execute(self, *a, **kw):
            return self
        def fetchone(self):
            return _Row(original_path='/tmp/x.mkv', proposed_path=None, status='pending')

    class _Conn:
        def cursor(self):
            return _Cursor()
        def close(self):
            self.closed = True

    monkeypatch.setattr(media_service, '_get_conn', lambda: _Conn())

    def _boom(module, symbol):
        raise media_backend.MediaBackendUnavailable(
            f'`{module}` no longer provides `{symbol}`')
    monkeypatch.setattr(media_backend, 'get', _boom)

    ok, error = media_service.reclassify('7', 'tv')
    assert ok is False
    assert 'identify_media' in error


# ---------- the Rejected folder ----------

@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_the_rejected_folder_shows_what_is_waiting_to_be_deleted(user: User,
                                                                      monkeypatch,
                                                                      fake_media_service):
    """Rejection moves files aside rather than deleting them, so without this view the
    folder fills up silently and nobody knows."""
    monkeypatch.setattr(media_service, 'get_rejected', lambda *a, **kw: [
        {'id': '1', 'original_filename': 'junk.mkv', 'proposed_title': 'Junk Movie',
         'media_type': 'movie', 'created_at': '2026-09-01', 'status': 'rejected',
         'rejected_path': '/mnt/Multimedia/Rejected/junk.mkv', 'on_disk': True},
    ])
    await user.open('/media-test')
    await user.should_see('1 rejected item awaiting deletion')
    await user.should_see('Junk Movie')
    await user.should_see('/mnt/Multimedia/Rejected/junk.mkv')
    await user.should_see('not deleted')


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_rejected_rows_whose_files_are_gone_are_not_listed(user: User, monkeypatch,
                                                                 fake_media_service):
    """Rows from before rejection stopped deleting have nothing left to clear. Listing
    them would ask the user to go delete files that are not there."""
    monkeypatch.setattr(media_service, 'get_rejected', lambda *a, **kw: [
        {'id': '1', 'original_filename': 'old.mkv', 'proposed_title': 'Old Reject',
         'media_type': 'movie', 'created_at': '2026-01-01', 'status': 'rejected',
         'rejected_path': None, 'on_disk': False},
    ])
    await user.open('/media-test')
    await user.should_not_see('awaiting deletion')
    await user.should_not_see('Old Reject')
