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
