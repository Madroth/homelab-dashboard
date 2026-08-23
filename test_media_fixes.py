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
        return list(queue)

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


@pytest.mark.nicegui_main_file('test_media_fixes.py')
async def test_toggle_select_timing_with_large_queue(user: User, monkeypatch):
    """Sanity check against a ~80-item queue (matching the real media-curator queue
    size that motivated this fix) -- toggling selection must stay well under the ~1s
    full-rebuild cost the equivalent intake.py bug caused."""
    queue = [_item(str(i)) for i in range(80)]
    monkeypatch.setattr(media_service, 'get_queue', lambda *a, **kw: list(queue))

    await user.open('/media-test')
    await user.should_see('Title 0')

    t0 = time.time()
    user.find(marker='row-select-40').click()
    await asyncio.sleep(0.05)
    t1 = time.time()
    print(f'\n\nMEDIA TOGGLE_SELECT (80 items) TOOK {t1 - t0:.3f}s\n\n')
    assert t1 - t0 < 0.5


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
