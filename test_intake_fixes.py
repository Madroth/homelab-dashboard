"""Throwaway verification for the Article Intake tab -- covers both the 2026-07-31
bug-fix pass and the subsequent Design v2 rewrite (grouped nav, toolbar dropdowns,
density view, resizable/conditional reader, archiving semantics, Discuss redesign).
Not permanent test infra -- exercises the code against isolated temp data (never the
real ~/projects/homelab-intake articles or the real intake_state.json)."""
import asyncio
import json
import os
import pathlib
import textwrap
import threading

import yaml

import pytest
from fastapi import FastAPI
from nicegui import ui
from nicegui.testing import User

from pages import intake as intake_page
from services import fulltext as fulltext_service
from services.ai import discuss as discuss_service
from services import intake as intake_service
from services import intake_state
from services import plane as plane_service


# ---------- pure-logic unit tests (no NiceGUI, no isolation needed) ----------

def test_date_sort_key_parses_frontmatter_date():
    a = {'id': 'x.md', 'date': '2026-03-05 10:00:00'}
    b = {'id': 'y.md', 'date': '2026-07-30 23:59:59'}
    assert intake_page._date_sort_key(b) > intake_page._date_sort_key(a)


def test_date_sort_key_falls_back_to_filename_timestamp_for_legacy_articles():
    # Legacy-format article: 'date' is free text, not parseable -- must fall back
    # to the filename's own embedded timestamp instead of crashing or sinking silently
    # relative to a real date.
    legacy = {'id': '2026-07-15-101500-legacy-article.md', 'date': 'sometime last week'}
    frontmatter_earlier = {'id': '2026-01-01-000000-x.md', 'date': '2026-01-01 00:00:00'}
    frontmatter_later = {'id': '2026-12-01-000000-y.md', 'date': '2026-12-01 00:00:00'}
    key = intake_page._date_sort_key(legacy)
    assert intake_page._date_sort_key(frontmatter_earlier) < key < intake_page._date_sort_key(frontmatter_later)


def test_date_sort_key_never_raises_on_garbage():
    intake_page._date_sort_key({'id': 'not-a-timestamp.md', 'date': 'garbage'})
    intake_page._date_sort_key({'id': '', 'date': ''})


def test_queue_lock_prevents_lost_update(tmp_path, monkeypatch):
    """Concurrent read-modify-write cycles on queue.json must not silently drop an
    update (dashboard-side lock; the daemon-side gap is tracked separately)."""
    queue_file = tmp_path / 'queue.json'
    queue_file.write_text('[]')
    monkeypatch.setattr(intake_service, 'QUEUE_FILE', str(queue_file))
    monkeypatch.setattr(intake_service, 'QUEUE_LOCK_FILE', str(queue_file) + '.lock')

    def worker(n):
        with intake_service._queue_lock():
            q = intake_service._read_queue()
            q.append({'id': str(n)})
            intake_service._write_queue(q)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = intake_service._read_queue()
    assert {item['id'] for item in result} == {str(i) for i in range(25)}, (
        'one or more concurrent queue updates were lost -- the lock did not prevent the race')


def test_intake_state_lock_prevents_lost_update(tmp_path, monkeypatch):
    """services/intake_state.py's set_article_state() re-reads/rewrites the whole
    file, so concurrent calls (e.g. two browser tabs) must not silently drop one
    article's update."""
    state_file = tmp_path / 'intake_state.json'
    monkeypatch.setattr(intake_state, 'STATE_FILE', str(state_file))

    def worker(n):
        intake_state.set_article_state(f'article-{n}.md', read=True)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(25)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    result = intake_state.all_article_states()
    assert set(result.keys()) == {f'article-{i}.md' for i in range(25)}, (
        'one or more concurrent intake_state updates were lost -- the lock did not prevent the race')
    assert all(entry['read'] is True for entry in result.values())


def test_prefs_shape_migrates_from_view_to_density(tmp_path, monkeypatch):
    """Caught live on 2026-07-31 restart: real production intake_state.json still had
    the pre-rewrite {'view': 'cards'|'table', ...} prefs shape, which has no 'density'
    key at all -- get_prefs() must normalize old-shape data, not just supply a default
    for a missing 'prefs' key entirely (setdefault() doesn't help when the key exists
    but its inner shape is stale)."""
    state_file = tmp_path / 'intake_state.json'
    state_file.write_text(json.dumps({'articles': {}, 'folders': [], 'prefs': {'view': 'cards', 'sort': 'date'}}))
    monkeypatch.setattr(intake_state, 'STATE_FILE', str(state_file))

    prefs = intake_state.get_prefs()
    assert prefs['density'] == 'cozy'
    assert 'view' not in prefs

    state_file.write_text(json.dumps({'articles': {}, 'folders': [], 'prefs': {'view': 'table', 'sort': 'date'}}))
    assert intake_state.get_prefs()['density'] == 'compact'


def test_default_sort_is_newest_first_never_priority(tmp_path, monkeypatch):
    """Chris's call, 2026-09-11: the list lands newest first. The model's priority_score is a
    sort he picks, never the one he lands on. Covers both ways a missing preference arises --
    no state file at all, and a prefs dict without a 'sort' key."""
    state_file = tmp_path / 'intake_state.json'
    monkeypatch.setattr(intake_state, 'STATE_FILE', str(state_file))
    assert intake_state.get_prefs()['sort'] == 'date'

    state_file.write_text(json.dumps({'articles': {}, 'folders': [], 'prefs': {'density': 'cozy'}}))
    assert intake_state.get_prefs()['sort'] == 'date'


def test_conversation_shape_migrates_from_bare_list(tmp_path, monkeypatch):
    """intake_conversations.json used to be {article_id: [messages]}; it's now
    {article_id: {"messages": [...], "sources": {...}}}. Old-shape entries must be
    read transparently and rewritten in the new shape, not lost."""
    convos_file = tmp_path / 'intake_conversations.json'
    convos_file.write_text(json.dumps({'old.md': [{'role': 'user', 'text': 'hi'}]}))
    monkeypatch.setattr(intake_state, 'CONVERSATIONS_FILE', str(convos_file))

    assert intake_state.get_thread('old.md') == [{'role': 'user', 'text': 'hi'}]
    assert intake_state.get_sources('old.md') == {'archive': True, 'repos': []}
    assert intake_state.thread_counts() == {'old.md': 1}

    intake_state.append_message('old.md', {'role': 'assistant', 'text': 'hello'})
    on_disk = json.loads(convos_file.read_text())
    assert on_disk['old.md']['messages'] == [
        {'role': 'user', 'text': 'hi'}, {'role': 'assistant', 'text': 'hello'}]
    assert on_disk['old.md']['sources'] == {'archive': True, 'repos': []}


# ---------- NiceGUI page smoke tests (isolated seed data) ----------

def _seed_article(dir_path, filename, *, title, date_processed, priority_score=5.0,
                   is_duplicate=False, tags=None, educational=False):
    content = textwrap.dedent(f"""\
        ---
        title: {title}
        date_processed: '{date_processed}'
        source_url: https://example.com/{filename}
        priority_score: {priority_score}
        tags: {tags or []}
        educational: {educational}
        dup_of: {"'x'" if is_duplicate else 'null'}
        ---

        ## Summary

        Test summary for {title}.
        """)
    (dir_path / filename).write_text(content, encoding='utf-8')


@pytest.fixture
def isolated_intake(tmp_path, monkeypatch):
    """Redirects every path the intake page touches at an isolated tmp_path, and stubs
    the Plane network call -- so this test can never read/write Chris's real article
    archive, real workflow state, or hit the real Plane API."""
    articles_dir = tmp_path / 'articles'
    articles_dir.mkdir()
    _seed_article(articles_dir, '2026-01-01-120000-old-article.md',
                   title='Old Article', date_processed='2026-01-01 12:00:00', priority_score=3,
                   tags=['docker'])
    _seed_article(articles_dir, '2026-07-30-235959-new-article.md',
                   title='New Article', date_processed='2026-07-30 23:59:59', priority_score=8,
                   tags=['gpu', 'ollama'])
    _seed_article(articles_dir, '2026-07-29-100000-dup-article.md',
                   title='Dup Article', date_processed='2026-07-29 10:00:00', priority_score=1,
                   is_duplicate=True)
    # Two educational articles in DIFFERENT sub-topics, so the Education view's grouping
    # has something to actually group; 'Old/New Article' stay non-educational as the
    # negative case.
    # 'gpu' is the more common tag across this fixture (it is also on New Article), so
    # these two land under different sub-topic headings -- which is what makes the
    # Education grouping test meaningful.
    _seed_article(articles_dir, '2026-07-28-090000-rag-guide.md',
                   title='RAG Guide', date_processed='2026-07-28 09:00:00', priority_score=7,
                   educational=True, tags=['gpu', 'rag'])
    _seed_article(articles_dir, '2026-07-27-090000-proxmox-course.md',
                   title='Proxmox Course', date_processed='2026-07-27 09:00:00', priority_score=6,
                   educational=True, tags=['proxmox'])
    # A second 'gpu' educational article, so GPU clears the 2-article minimum and becomes a
    # real heading while Proxmox Course (alone under 'proxmox') folds into Other.
    _seed_article(articles_dir, '2026-07-26-090000-cuda-primer.md',
                   title='CUDA Primer', date_processed='2026-07-26 09:00:00', priority_score=6,
                   educational=True, tags=['gpu'])

    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(articles_dir))
    monkeypatch.setattr(intake_service, 'QUEUE_FILE', str(tmp_path / 'queue.json'))
    monkeypatch.setattr(intake_service, 'QUEUE_LOCK_FILE', str(tmp_path / 'queue.json.lock'))
    monkeypatch.setattr(intake_service, '_articles_cache', {'signature': None, 'articles': None})
    # Critical: promote_tag() WRITES to this path. Without redirecting it, accepting a tag in
    # a test would permanently edit the real homelab-intake vocabulary.
    vocab_file = tmp_path / 'tags_vocabulary.json'
    vocab_file.write_text(json.dumps(['Docker', 'OpenSource', 'gpu', 'proxmox', 'rag']))
    monkeypatch.setattr(intake_service, 'TAGS_VOCAB_FILE', str(vocab_file))

    state_file = tmp_path / 'intake_state.json'
    monkeypatch.setattr(intake_state, 'STATE_FILE', str(state_file))
    monkeypatch.setattr(intake_state, 'CONVERSATIONS_FILE', str(tmp_path / 'intake_conversations.json'))

    call_log = tmp_path / 'send_calls.log'

    def _delayed_send(article, summary, project_id=None):
        # A tiny artificial delay so the "sending" transient state is actually
        # observable in the test instead of resolving faster than we can poll.
        import time
        with open(call_log, 'a') as f:
            f.write(f'called with {article.get("id")}\n')
        time.sleep(0.3)
        return {'created': True, 'verified': True, 'already_existed': False,
                'issue_id': 'stub-issue-id', 'project_id': project_id, 'error': None}

    monkeypatch.setattr(plane_service, 'send_article_to_plane', _delayed_send)

    # Full-text fetch must never hit the network in tests -- the seeded articles carry
    # example.com source URLs precisely so a missing stub here fails loudly (slow test +
    # 'failed' section) rather than silently fetching something real.
    monkeypatch.setattr(fulltext_service, 'CACHE_DIR', str(tmp_path / 'fulltext_cache'))
    monkeypatch.setattr(fulltext_service, 'fetch_and_cache',
                         lambda aid, url: f'Stub full text for {aid}')

    monkeypatch.setattr(discuss_service, 'send_discuss_message',
                         lambda *a, **kw: {'text': 'Stubbed discuss reply.', 'tool_calls': []})

    return {'tmp_path': tmp_path, 'state_file': state_file}


@ui.page('/intake-test')
def _intake_test_page():
    intake_page.build()


# This test module doubles as its own nicegui "main file" (see the nicegui_main_file
# marker on each test below). ui.run_with() needs a host FastAPI app distinct from
# nicegui's own singleton -- it's only used to flip on `has_run_config` for the
# ASGI-transport-based simulation below; no real server is started.
ui.run_with(FastAPI())


async def _wait_until(predicate, timeout=3.0, interval=0.1):
    elapsed = 0.0
    while elapsed < timeout:
        if predicate():
            return True
        await asyncio.sleep(interval)
        elapsed += interval
    return False


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_page_renders_and_excludes_duplicates_from_all(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    await user.should_see('Old Article')
    await user.should_not_see('Dup Article')  # 'all' excludes duplicates (pipeline noise)


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_duplicates_folder_shows_duplicate(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker='folder-duplicates').click()
    await asyncio.sleep(0.2)
    await user.should_see('Dup Article')
    await user.should_not_see('New Article')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_density_toggle(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker='density-toggle-compact').click()
    await asyncio.sleep(0.2)
    await user.should_see('New Article')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_open_and_close_reader(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'article-row-{aid}').click()
    await asyncio.sleep(0.3)
    await user.should_see(marker='reader-mode-read')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_row_action_icon_does_not_also_open_reader(user: User, isolated_intake):
    """The action icons (read/favorite/archive/etc.) were moved to sit inside the same
    clickable column as the title (2026-08-01, to stop them eating ~half the row's
    width in the old side-by-side layout) -- their 'click.stop' modifier must keep a
    click on an icon from also bubbling up to the column's own select_article handler
    and opening the reader, which would be a real regression from this move."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'

    user.find(marker=f'row-f-{aid}').click()  # favorite icon, nested inside the row now
    await asyncio.sleep(0.3)
    await user.should_not_see(marker='reader-mode-read')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_switching_between_articles_updates_reader_content(user: User, isolated_intake):
    """select_article()/move_focus() were changed (2026-08-01) to refresh just the
    previously- and newly-focused rows instead of render_articles.refresh()'s
    full-list rebuild -- opening an article was taking 1s+ from that rebuild cost
    alone. Confirm switching between two articles still correctly updates the reader
    to the second article's content, not stale content left over from the first."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    new_aid = '2026-07-30-235959-new-article.md'
    old_aid = '2026-01-01-120000-old-article.md'

    user.find(marker=f'article-row-{new_aid}').click()
    await user.should_see('Test summary for New Article', retries=20)

    user.find(marker=f'article-row-{old_aid}').click()
    await user.should_see('Test summary for Old Article', retries=20)


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_article_content_actually_loads(user: User, isolated_intake):
    """Caught live: the reader header/tabs render immediately regardless of whether
    the article body ever loads, so a passing 'reader-mode-read is visible' check
    (above) does NOT prove content loaded -- this specifically waits for the seeded
    body text itself. Was silently stuck forever in production (no exception) because
    select_article() fired the fetch via a detached background_tasks.create() task,
    inside which client_alive()'s context lookup was unreliable -- fixed by awaiting
    load_article_content() directly in the same coroutine NiceGUI already schedules
    for the click, instead of spinning off a separate task."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'article-row-{aid}').click()
    await user.should_see('Test summary for New Article', retries=20)


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_archive_row_action_persists(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'row-a-{aid}').click()

    state_file = isolated_intake['state_file']

    def _archived():
        if not state_file.exists():
            return False
        data = json.loads(state_file.read_text())
        return data.get('articles', {}).get(aid, {}).get('archived') is True

    assert await _wait_until(_archived), 'archived flag was not persisted after clicking the archive icon'


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_inline_delete_confirm(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-01-01-120000-old-article.md'
    user.find(marker=f'delete-icon-{aid}').click()
    await asyncio.sleep(0.2)
    await user.should_see('Delete?')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_archived_favorite_still_shows_in_favorites(user: User, isolated_intake):
    """The agreed archiving model: archived hides from 'all', NOT from Favorites --
    a favorited article that gets auto-archived (e.g. via Send to HomeLab) must not
    silently disappear from the Favorites view."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'

    user.find(marker=f'row-f-{aid}').click()  # favorite
    await asyncio.sleep(0.2)
    user.find(marker=f'row-a-{aid}').click()  # archive
    await asyncio.sleep(0.2)

    await user.should_not_see('New Article')  # gone from 'all' now that it's archived

    user.find(marker='folder-favorites').click()
    await asyncio.sleep(0.2)
    await user.should_see('New Article')  # still visible under Favorites despite being archived


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_archived_duplicate_still_shows_in_duplicates(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    dup_id = '2026-07-29-100000-dup-article.md'

    user.find(marker='folder-duplicates').click()
    await asyncio.sleep(0.2)
    await user.should_see('Dup Article')

    user.find(marker=f'row-a-{dup_id}').click()  # archive it
    await asyncio.sleep(0.2)
    await user.should_see('Dup Article')  # still visible under Duplicates despite being archived


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_send_to_homelab_shows_immediate_feedback(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')

    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'send-icon-{aid}').click()

    # the sending spinner should appear (even briefly) rather than nothing happening
    await user.should_see(marker=f'sending-{aid}', retries=10)

    state_file = isolated_intake['state_file']

    def _archived_and_read():
        if not state_file.exists():
            return False
        entry = json.loads(state_file.read_text()).get('articles', {}).get(aid, {})
        # plane_issue_id is what makes the control render as a checkmark and what stops a
        # second send filing a duplicate, so it has to be persisted alongside read/archived.
        return (entry.get('archived') is True and entry.get('read') is True
                and entry.get('plane_issue_id') == 'stub-issue-id')

    ok = await _wait_until(_archived_and_read)
    if not ok:
        call_log = isolated_intake['tmp_path'] / 'send_calls.log'
        diag = call_log.read_text() if call_log.exists() else '(send_article_to_plane was never called)'
        state_content = state_file.read_text() if state_file.exists() else '(no state file)'
        pytest.fail(f'Send to HomeLab did not mark read+archived.\ncall log: {diag!r}\nstate: {state_content!r}')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_discuss_mode_opens_and_repo_scope_popover(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'

    user.find(marker=f'article-row-{aid}').click()
    await asyncio.sleep(0.2)
    user.find(marker='reader-mode-discuss').click()
    await asyncio.sleep(0.3)

    await user.should_see('This article')
    await user.should_see('homelab-infra')
    await user.should_not_see('Repo access')  # popover starts closed (repo defaults off)

    user.find(marker='discuss-chip-repo').click()
    await asyncio.sleep(0.2)
    await user.should_see('Repo access')  # turning the repo chip on opens the scope popover


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_reader_action_row_stays_visible_in_discuss_mode(user: User, isolated_intake):
    """The reader's action icon row (Discuss/favorite/archive/send/delete/...) used to be
    hidden in Discuss mode (_reader_content_block's show_actions=False branch); Chris asked
    2026-08-04 for it to stay visible alongside the chat."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'

    user.find(marker=f'article-row-{aid}').click()
    await asyncio.sleep(0.2)
    user.find(marker='reader-mode-discuss').click()
    await asyncio.sleep(0.3)

    await user.should_see('This article')  # discuss panel is open
    for mark in (f'row-reader-f-{aid}', f'row-reader-a-{aid}',
                 f'reader-send-icon-{aid}', f'reader-delete-icon-{aid}'):
        user.find(marker=mark)  # raises if the action icon is missing


def test_model_pick_persists_per_article_and_survives_clear(tmp_path, monkeypatch):
    """Each article's Discuss model choice is saved with its conversation entry
    (Chris, 2026-08-04): unpicked articles fall back to DEFAULT_MODEL, picks stick
    per article, and 'Clear' empties messages WITHOUT resetting model or sources."""
    convos_file = tmp_path / 'convos.json'
    monkeypatch.setattr(intake_state, 'CONVERSATIONS_FILE', str(convos_file))

    assert intake_state.get_model('a.md') == intake_state.DEFAULT_MODEL
    intake_state.set_model('a.md', 'local')
    assert intake_state.get_model('a.md') == 'local'
    assert intake_state.get_model('b.md') == intake_state.DEFAULT_MODEL  # untouched article

    intake_state.append_message('a.md', {'role': 'user', 'text': 'hi'})
    intake_state.set_sources('a.md', repos=['homelab-infra'])
    intake_state.clear_thread('a.md')
    assert intake_state.get_thread('a.md') == []
    assert intake_state.get_model('a.md') == 'local'
    assert intake_state.get_sources('a.md')['repos'] == ['homelab-infra']


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_discuss_model_pick_is_per_article(user: User, isolated_intake):
    """Switching articles must restore each article's own saved model pick instead of
    carrying over whatever was selected last (the picker used to be global state)."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    new_aid = '2026-07-30-235959-new-article.md'
    old_aid = '2026-01-01-120000-old-article.md'

    user.find(marker=f'article-row-{new_aid}').click()
    await user.should_see('Test summary for New Article', retries=20)
    await asyncio.sleep(0.3)  # let load_article_content's render_reader.refresh() land
    user.find(marker='reader-mode-discuss').click()
    await asyncio.sleep(0.3)
    await user.should_see('Claude · grounded')  # default before any pick

    user.find(marker='discuss-model-local').click()
    await asyncio.sleep(0.3)
    await user.should_see('Local · grounded')

    user.find(marker='reader-show-list').click()  # discuss forces full width; unhide the list
    await asyncio.sleep(0.2)
    user.find(marker=f'article-row-{old_aid}').click()
    await user.should_see('Test summary for Old Article', retries=20)
    await asyncio.sleep(0.3)  # let load_article_content's render_reader.refresh() land
    user.find(marker='reader-mode-discuss').click()
    await asyncio.sleep(0.3)
    await user.should_see('Claude · grounded')  # old article never picked -> default
    await user.should_not_see('Local · grounded')

    user.find(marker='reader-show-list').click()
    await asyncio.sleep(0.2)
    user.find(marker=f'article-row-{new_aid}').click()
    await user.should_see('Test summary for New Article', retries=20)
    await asyncio.sleep(0.3)  # let load_article_content's render_reader.refresh() land
    user.find(marker='reader-mode-discuss').click()
    await asyncio.sleep(0.3)
    await user.should_see('Local · grounded')  # first article's pick was remembered


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_typing_in_the_tag_search_keeps_the_menu_open(user: User, isolated_intake):
    """Reported by Chris 2026-09-11: every letter typed into the tag menu's filter box closed
    the menu, so it had to be reopened to type the next one. on_tag_search refreshed the
    whole render_tag_dropdown -- and a recreated ui.menu() starts closed, the same trap
    select_tag() already sidesteps. Typing must rebuild only the list, never the menu or the
    input being typed into."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    menu = next(iter(user.find(marker='tag-menu').elements))
    search = next(iter(user.find(marker='tag-search').elements))
    menu.open()

    user.find(marker='tag-search').type('g')
    await asyncio.sleep(0.2)
    user.find(marker='tag-search').type('p')
    await asyncio.sleep(0.2)

    assert next(iter(user.find(marker='tag-menu').elements)) is menu, \
        'typing rebuilt the tag menu, which closes it'
    assert menu.value, 'the tag menu closed while typing'
    assert next(iter(user.find(marker='tag-search').elements)) is search, \
        'typing rebuilt the search box, which drops focus mid-word'
    await user.should_see(marker='tag-row-gpu')
    await user.should_not_see(marker='tag-row-docker')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_read_toggle_still_reorders_under_unread_sort(user: User, isolated_intake):
    """The single-row-refresh optimization for toggle_read/toggle_favorite/toggle_archived
    (added 2026-08-01 after a reported 1s+ delay on every toggle -- render_articles.refresh()
    was rebuilding all visible rows for a change affecting exactly one, see
    _refresh_after_workflow_change()) must still fall back to a full render_articles.refresh()
    when the toggle changes visible order, not just when it changes membership. Under
    'Unread first', marking an article read must not leave the list in a broken state. That
    sort is set explicitly: it stopped being the default on 2026-09-11."""
    isolated_intake['state_file'].write_text(json.dumps(
        {'articles': {}, 'folders': [], 'prefs': {'density': 'cozy', 'sort': 'unread'}}))
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'

    user.find(marker=f'row-r-{aid}').click()
    await asyncio.sleep(0.2)

    state_file = isolated_intake['state_file']

    def _read():
        if not state_file.exists():
            return False
        return json.loads(state_file.read_text()).get('articles', {}).get(aid, {}).get('read') is True

    assert await _wait_until(_read), 'read flag was not persisted after clicking the read/unread icon'
    await user.should_see('New Article')
    await user.should_see('Old Article')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_favorite_toggle_removes_row_from_favorites_folder(user: User, isolated_intake):
    """Same optimization as the test above -- unfavoriting while viewing the Favorites
    folder must remove the row from view (a membership change), not leave a stale row
    behind from the single-row fast path."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'

    user.find(marker=f'row-f-{aid}').click()  # favorite it
    await asyncio.sleep(0.2)
    user.find(marker='folder-favorites').click()
    await asyncio.sleep(0.2)
    await user.should_see('New Article')

    user.find(marker=f'row-f-{aid}').click()  # unfavorite while inside Favorites
    await asyncio.sleep(0.2)
    await user.should_not_see('New Article')


# ---------- 2026-08-02: three-section reader (summary / analysis / full text) ----------

def test_get_article_splits_summary_and_analysis(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(tmp_path))
    (tmp_path / 'a.md').write_text(textwrap.dedent("""\
        ---
        title: X
        ---

        ## Summary

        The summary text.

        ## Application Analysis

        The analysis text.
        """), encoding='utf-8')
    data = intake_service.get_article('a.md')
    assert data['summary'] == 'The summary text.'
    assert data['analysis'] == 'The analysis text.'
    # summary-only articles must yield an empty analysis, not leak the summary into it
    (tmp_path / 'b.md').write_text('---\ntitle: Y\n---\n\n## Summary\n\nOnly summary.\n',
                                    encoding='utf-8')
    data = intake_service.get_article('b.md')
    assert data['summary'] == 'Only summary.'
    assert data['analysis'] == ''


def test_fulltext_fetch_caches_and_get_cached_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(fulltext_service, 'CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setattr(fulltext_service.trafilatura, 'fetch_url', lambda url: '<html>page</html>')
    monkeypatch.setattr(fulltext_service.trafilatura, 'extract',
                         lambda downloaded, **kw: 'Extracted body text.')
    aid = '2026-01-01-000000-x.md'
    assert fulltext_service.get_cached(aid) is None
    assert fulltext_service.fetch_and_cache(aid, 'https://example.com/x') == 'Extracted body text.'
    assert fulltext_service.get_cached(aid) == 'Extracted body text.'
    # a failed fetch must return None and must NOT poison the cache
    monkeypatch.setattr(fulltext_service.trafilatura, 'fetch_url', lambda url: None)
    assert fulltext_service.fetch_and_cache('other.md', 'https://example.com/y') is None
    assert fulltext_service.get_cached('other.md') is None


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_reader_shows_summary_and_full_text_sections(user: User, isolated_intake):
    """The reader now stacks SUMMARY and FULL ARTICLE (plus APPLICATION ANALYSIS when
    present) instead of the old Content/AI Summary tabs -- opening an article must show
    the seeded summary AND the (stubbed) fetched full text with no tab clicking."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'article-row-{aid}').click()
    await user.should_see('Test summary for New Article', retries=20)
    await user.should_see(f'Stub full text for {aid}', retries=20)


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_discuss_reply_renders_after_send(user: User, isolated_intake):
    """Caught live 2026-08-02: discuss_send checked client_alive() WITHOUT a captured
    client after its own render_reader.refresh() had torn down the Discuss input's
    slot, so every reply was silently dropped and the busy spinner stuck on
    '... is reading ...' forever. This drives the real click path: open Discuss, click
    a suggested prompt, and require the (stubbed) assistant reply to actually render
    -- it fails if the stale-slot guard regresses."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'article-row-{aid}').click()
    # 'Test summary...' also matches the list row's snippet, so it can't prove the
    # reader opened; the stubbed full text renders ONLY inside the reader -- waiting
    # on it gives the async select_article() time to finish before find() (no retry)
    # goes looking for the reader's Discuss toggle.
    await user.should_see(f'Stub full text for {aid}', retries=20)
    user.find(marker='reader-mode-discuss').click()
    await user.should_see('Summarize the key takeaway', retries=20)
    # click the pill row by marker -- its label has no listener and clicks don't bubble
    user.find(marker='discuss-prompt-0').click()
    await user.should_see('Stubbed discuss reply.', retries=30)


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_education_folder_shows_only_educational(user: User, isolated_intake):
    """The Education view is the whole point of the educational field: it must show the
    items flagged educational and nothing else, so it stays a clean reading list rather
    than another copy of the inbox."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker='folder-education').click()
    await asyncio.sleep(0.2)
    await user.should_see('RAG Guide')
    await user.should_see('Proxmox Course')
    await user.should_not_see('New Article')
    await user.should_not_see('Old Article')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_education_folder_groups_by_subtopic(user: User, isolated_intake):
    """Education is browse-by-subject, so it renders sub-topic headers. With primary_domain
    gone the heading is each article's most corpus-frequent tag, and headings holding a
    single article fold into Other -- otherwise the real archive's tag distribution produces
    one heading per article."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker='folder-education').click()
    await asyncio.sleep(0.2)
    await user.should_see('GPU')      # 2 articles -> a real heading
    await user.should_see('OTHER')    # Proxmox Course is alone, so it folds in
    await user.should_not_see('PROXMOX')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_other_folders_are_not_grouped(user: User, isolated_intake):
    """Grouping is scoped to Education only -- the 'all' triage queue must stay flat.
    'OTHER' is asserted because it is a heading the grouped view always emits here and
    nothing else on the page renders it."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    await user.should_not_see('OTHER')


# ---------- tag editing (service layer: pure file round-trips) ----------

def _write_article(dir_path, name, *, tags, suggested=None):
    meta = {'title': 'T', 'source_url': f'https://example.com/{name}', 'tags': tags}
    if suggested is not None:
        meta['suggested_tags'] = suggested
    (dir_path / name).write_text(
        '---\n' + yaml.safe_dump(meta, sort_keys=False) + '---\n\n## Summary\n\nbody\n',
        encoding='utf-8')


def test_add_and_remove_tag_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(tmp_path))
    _write_article(tmp_path, 'a.md', tags=['Docker'])

    assert intake_service.add_tag('a.md', 'Tailscale') is True
    meta, _ = intake_service._parse_frontmatter((tmp_path / 'a.md').read_text())
    assert meta['tags'] == ['Docker', 'Tailscale']

    assert intake_service.remove_tag('a.md', 'Docker') is True
    meta, _ = intake_service._parse_frontmatter((tmp_path / 'a.md').read_text())
    assert meta['tags'] == ['Tailscale']


def test_add_tag_is_normalisation_aware(tmp_path, monkeypatch):
    """Adding 'open source' to an article already carrying 'OpenSource' must be a no-op --
    otherwise the manual editor reintroduces exactly the variant sprawl the vocabulary work
    just cleaned up."""
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(tmp_path))
    _write_article(tmp_path, 'a.md', tags=['OpenSource'])

    intake_service.add_tag('a.md', 'open source')
    intake_service.add_tag('a.md', 'Open-Source')
    meta, _ = intake_service._parse_frontmatter((tmp_path / 'a.md').read_text())
    assert meta['tags'] == ['OpenSource']


def test_accepting_a_tag_clears_it_from_suggestions(tmp_path, monkeypatch):
    """A suggestion that has been applied must stop being offered, or the article keeps
    prompting for a tag it already carries."""
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(tmp_path))
    _write_article(tmp_path, 'a.md', tags=['Docker'], suggested=['Kubernetes', 'Helm'])

    intake_service.add_tag('a.md', 'Kubernetes')
    meta, _ = intake_service._parse_frontmatter((tmp_path / 'a.md').read_text())
    assert meta['tags'] == ['Docker', 'Kubernetes']
    assert meta['suggested_tags'] == ['Helm']


def test_dismiss_suggested_tag_drops_it_without_applying(tmp_path, monkeypatch):
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(tmp_path))
    _write_article(tmp_path, 'a.md', tags=['Docker'], suggested=['Kubernetes'])

    assert intake_service.dismiss_suggested_tag('a.md', 'Kubernetes') is True
    meta, _ = intake_service._parse_frontmatter((tmp_path / 'a.md').read_text())
    assert meta['tags'] == ['Docker']
    assert meta['suggested_tags'] == []


def test_promote_tag_reuses_existing_canonical_spelling(tmp_path, monkeypatch):
    """Promoting 'open-source' when 'OpenSource' is already in the vocabulary must return the
    existing spelling and NOT add a second entry."""
    vocab = tmp_path / 'v.json'
    vocab.write_text(json.dumps(['OpenSource', 'Docker']))
    monkeypatch.setattr(intake_service, 'TAGS_VOCAB_FILE', str(vocab))

    assert intake_service.promote_tag('open-source') == 'OpenSource'
    assert sorted(json.loads(vocab.read_text())) == ['Docker', 'OpenSource']

    assert intake_service.promote_tag('Kubernetes') == 'Kubernetes'
    assert 'Kubernetes' in json.loads(vocab.read_text())


# ---------- tag editor UI ----------

@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_reader_shows_tag_chips_and_removes_one(user: User, isolated_intake):
    """The tag editor renders above the summary and its per-tag delete actually writes
    through to frontmatter."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'article-row-{aid}').click()
    await user.should_see(f'Stub full text for {aid}', retries=20)
    await user.should_see('gpu')
    await user.should_see('ollama')

    user.find(marker='tag-remove-gpu').click()
    await asyncio.sleep(0.4)
    meta, _ = intake_service._parse_frontmatter(
        (pathlib.Path(intake_service.ARTICLES_DIR) / aid).read_text())
    assert 'gpu' not in meta['tags']
    assert 'ollama' in meta['tags']


def test_group_by_subtopic_folds_single_article_headings():
    """The fold is what keeps the Education view navigable: measured on the real archive,
    grouping 23 educational articles by top tag alone produced 16 headings, 13 of them
    holding one article."""
    freqs = {'AI': 40, 'Docker': 8, 'Obscure': 1, 'AlsoRare': 1}
    arts = [
        {'id': '1', 'tags': ['AI']}, {'id': '2', 'tags': ['AI']}, {'id': '3', 'tags': ['AI']},
        {'id': '4', 'tags': ['Docker']}, {'id': '5', 'tags': ['Docker']},
        {'id': '6', 'tags': ['Obscure']},
        {'id': '7', 'tags': ['AlsoRare']},
        {'id': '8', 'tags': []},
    ]
    groups = intake_page._group_by_subtopic(arts, freqs)
    assert [h for h, _ in groups] == ['AI', 'Docker', 'Other'], groups
    assert len(groups[0][1]) == 3
    # the two singletons plus the untagged article
    assert {a['id'] for a in groups[-1][1]} == {'6', '7', '8'}


def test_subtopic_prefers_the_more_common_tag():
    """An article tagged both a rare and a common term files under the common one, so
    related articles actually land together."""
    freqs = {'AI': 40, 'ADK2.0': 1}
    assert intake_page._subtopic_of({'tags': ['ADK2.0', 'AI']}, freqs) == 'AI'
    # deterministic on ties rather than dependent on tag order
    assert intake_page._subtopic_of({'tags': ['Zebra', 'Apple']}, {'Zebra': 2, 'Apple': 2}) == 'Apple'


def test_promote_tag_preserves_frequency_ordering(tmp_path, monkeypatch):
    """The vocabulary file's ORDER is its frequency ranking, and the tagging prompt injects
    the top N by taking the first N. promote_tag() must append, not re-sort -- sorting would
    silently destroy that ranking the first time a tag is accepted in the UI."""
    vocab = tmp_path / 'v.json'
    ranked = ['AI', 'OpenSource', 'Automation', 'Docker']   # descending frequency, NOT alphabetical
    vocab.write_text(json.dumps(ranked))
    monkeypatch.setattr(intake_service, 'TAGS_VOCAB_FILE', str(vocab))

    intake_service.promote_tag('Zebra')
    after = json.loads(vocab.read_text())
    assert after == ranked + ['Zebra'], (
        'promote_tag re-ordered the vocabulary; the frequency ranking the tagging prompt '
        f'depends on has been lost: {after}')

    # a no-op promotion must not reorder either
    intake_service.promote_tag('open-source')
    assert json.loads(vocab.read_text()) == ranked + ['Zebra']


def test_load_tag_vocabulary_keeps_file_order(tmp_path, monkeypatch):
    vocab = tmp_path / 'v.json'
    vocab.write_text(json.dumps(['AI', 'OpenSource', 'Automation']))
    monkeypatch.setattr(intake_service, 'TAGS_VOCAB_FILE', str(vocab))
    assert intake_service.load_tag_vocabulary() == ['AI', 'OpenSource', 'Automation']


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_already_sent_article_shows_a_checkmark_not_a_send_button(user: User, isolated_intake):
    """A recorded plane_issue_id is what marks an article as already filed. The control
    has to render as a checkmark rather than a live send button -- a second send creates a
    second to-do rather than updating the first. (The checkmark is clickable, but it
    re-checks Plane; it never sends. See the verify tests below.)"""
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']
    state_file.write_text(json.dumps({
        'articles': {aid: {'read': False, 'favorite': False, 'archived': False,
                           'plane_issue_id': 'already-filed-id'}},
        'folders': [], 'prefs': {'density': 'cozy', 'sort': 'unread'},
    }))

    await user.open('/intake-test')
    await user.should_see('New Article')
    await user.should_see(marker=f'sent-icon-{aid}')

    with pytest.raises(AssertionError):
        user.find(marker=f'send-icon-{aid}')


# ---------- Plane send: create vs. confirm are reported separately ----------

class _FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.RequestException(f'{self.status_code} Client Error')

    def json(self):
        return self._payload


def _stub_plane(monkeypatch, *, post, get, patch=None):
    """Points services.plane at fake HTTP, with config filled in so the real .env values
    (and the real Plane instance) are never involved."""
    for name in ('PLANE_API_KEY', 'PLANE_API_URL', 'PLANE_WORKSPACE_SLUG', 'PLANE_PROJECT_ID'):
        monkeypatch.setattr(plane_service, name, 'stub')
    monkeypatch.setattr(plane_service, '_get_or_create_label', lambda *a, **kw: None)

    def _no_patch(*a, **kw):
        raise AssertionError('PATCH was not expected here')

    monkeypatch.setattr(plane_service, 'requests',
                        type('R', (), {'post': staticmethod(post), 'get': staticmethod(get),
                                       'patch': staticmethod(patch or _no_patch),
                                       'RequestException': Exception})())


def test_send_marks_verified_when_the_issue_reads_back(monkeypatch):
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(201, {'id': 'new-issue'}),
                get=lambda *a, **kw: _FakeResponse(200, {'id': 'new-issue'}))
    result = plane_service.send_article_to_plane({'title': 'T', 'source': 'https://x/'}, 'summary')
    # project_id is part of the result on purpose: the caller records it so a later
    # issue_status() asks the project the to-do actually went to. Asking the default one
    # would read a 404 as "deleted" and orphan a live to-do.
    fingerprint = result.pop('fingerprint')
    assert result == {'created': True, 'verified': True, 'already_existed': False,
                      'issue_id': 'new-issue', 'project_id': 'stub', 'error': None}
    assert set(fingerprint) == {'sent', 'held'}


def test_send_keeps_the_issue_id_when_the_read_back_fails(monkeypatch):
    """created=True with verified=False must still carry the id: the to-do may well exist,
    so the caller has to record it and NOT offer a retry that would file a duplicate."""
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(201, {'id': 'new-issue'}),
                get=lambda *a, **kw: _FakeResponse(404, {}))
    result = plane_service.send_article_to_plane({'title': 'T', 'source': 'https://x/'}, 'summary')
    assert result['created'] is True
    assert result['verified'] is False
    assert result['issue_id'] == 'new-issue'


def test_send_reports_failure_when_plane_rejects_the_create(monkeypatch):
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(403, {}),
                get=lambda *a, **kw: _FakeResponse(200, {}))
    result = plane_service.send_article_to_plane({'title': 'T', 'source': 'https://x/'}, 'summary')
    assert result['created'] is False
    assert result['issue_id'] is None
    assert '403' in result['error']


def test_resend_recovers_the_existing_issue_instead_of_duplicating(monkeypatch):
    """Plane answers a repeat external_id with 409 and the id it already holds. That is the
    only defence against a create whose response was lost: local state cannot tell a failed
    create from a successful one whose reply never arrived."""
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(409, {'id': 'existing-issue'}),
                get=lambda *a, **kw: _FakeResponse(200, {'id': 'existing-issue'}))
    result = plane_service.send_article_to_plane(
        {'id': 'a.md', 'title': 'T', 'source': 'https://x/'}, 'summary')
    assert result['created'] is True
    assert result['already_existed'] is True
    assert result['issue_id'] == 'existing-issue'


def test_send_reports_unexpected_errors_instead_of_raising(monkeypatch):
    """A malformed article used to raise straight out of the service, skipping the caller's
    refresh and toast and leaving its spinner turning with the reason only in the log."""
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(201, {'id': 'x'}),
                get=lambda *a, **kw: _FakeResponse(200, {'id': 'x'}))
    result = plane_service.send_article_to_plane({'id': 'a.md'}, 'summary')  # no 'title'
    assert result['created'] is False
    assert 'KeyError' in result['error']


# ---------- reconciling a recorded to-do against Plane ----------

def test_issue_status_calls_only_a_404_gone(monkeypatch):
    """404 is Plane positively stating it has no such issue -- the one answer that may
    clear an article's only link to its to-do."""
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(201, {}),
                get=lambda *a, **kw: _FakeResponse(404, {}))
    assert plane_service.issue_status('some-id') == 'gone'


def test_issue_status_confirms_a_live_issue(monkeypatch):
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(201, {}),
                get=lambda *a, **kw: _FakeResponse(200, {'id': 'some-id'}))
    assert plane_service.issue_status('some-id') == 'present'


def test_issue_status_never_reports_gone_when_plane_cannot_answer(monkeypatch):
    """The whole point of the three-valued return: an outage must not read as "deleted",
    or every restart of Plane would wipe the checkmarks off live to-dos."""
    for code in (401, 403, 429, 500, 502, 503):
        _stub_plane(monkeypatch,
                    post=lambda *a, **kw: _FakeResponse(201, {}),
                    get=lambda *a, c=code, **kw: _FakeResponse(c, {}))
        assert plane_service.issue_status('some-id') == 'unknown', code

    def _boom(*a, **kw):
        raise Exception('connection refused')

    _stub_plane(monkeypatch, post=lambda *a, **kw: _FakeResponse(201, {}), get=_boom)
    assert plane_service.issue_status('some-id') == 'unknown'

    # A 200 about some other issue is not an answer about this one either.
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(201, {}),
                get=lambda *a, **kw: _FakeResponse(200, {'id': 'a-different-issue'}))
    assert plane_service.issue_status('some-id') == 'unknown'


def _already_filed_state(state_file, aid, issue_id='already-filed-id'):
    state_file.write_text(json.dumps({
        'articles': {aid: {'read': False, 'favorite': False, 'archived': False,
                           'plane_issue_id': issue_id}},
        'folders': [], 'prefs': {'density': 'cozy', 'sort': 'unread'},
    }))


def _recorded_issue_id(state_file, aid):
    return json.loads(state_file.read_text()).get('articles', {}).get(aid, {}).get('plane_issue_id')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_clicking_the_checkmark_clears_a_todo_deleted_in_plane(
        user: User, isolated_intake, monkeypatch):
    """The checkmark was a one-way door: plane_issue_id was written on a successful send
    and cleared nowhere, while the control it drives refuses to resend. Deleting the to-do
    in Plane left the article permanently unsendable short of editing intake_state.json."""
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']
    _already_filed_state(state_file, aid)
    monkeypatch.setattr(plane_service, 'issue_status', lambda _id, _pid=None: 'gone')

    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker=f'sent-icon-{aid}').click()

    cleared = await _wait_until(lambda: _recorded_issue_id(state_file, aid) is None)
    assert cleared, f'plane_issue_id was not cleared: {state_file.read_text()!r}'
    # ...and the send control comes back, which is the part that actually unsticks it.
    await user.should_see(marker=f'send-icon-{aid}', retries=10)


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_checkmark_survives_a_verify_against_a_live_todo(
        user: User, isolated_intake, monkeypatch):
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']
    _already_filed_state(state_file, aid)
    monkeypatch.setattr(plane_service, 'issue_status', lambda _id, _pid=None: 'present')

    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker=f'sent-icon-{aid}').click()
    await asyncio.sleep(0.3)

    assert _recorded_issue_id(state_file, aid) == 'already-filed-id'
    await user.should_see(marker=f'sent-icon-{aid}')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_an_unreachable_plane_leaves_the_checkmark_alone(
        user: User, isolated_intake, monkeypatch):
    """Fail closed: an unreachable Plane must not be read as "the to-do was deleted" and
    strip the article's link to a to-do that is still sitting there."""
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']
    _already_filed_state(state_file, aid)
    monkeypatch.setattr(plane_service, 'issue_status', lambda _id, _pid=None: 'unknown')

    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker=f'sent-icon-{aid}').click()
    await asyncio.sleep(0.3)

    assert _recorded_issue_id(state_file, aid) == 'already-filed-id'
    await user.should_see(marker=f'sent-icon-{aid}')
    with pytest.raises(AssertionError):
        user.find(marker=f'send-icon-{aid}')


def test_send_always_carries_an_idempotency_key_even_without_an_article_id(monkeypatch):
    """external_id is the only thing between a lost response and a duplicate to-do, so
    it is never optional. An article with no id used to POST without one, silently
    dropping back to the un-idempotent behaviour the key exists to prevent."""
    captured = {}

    def _post(url, **kw):
        captured.update(kw.get('json') or {})
        return _FakeResponse(201, {'id': 'new-issue'})

    _stub_plane(monkeypatch, post=_post, get=lambda *a, **kw: _FakeResponse(200, {'id': 'new-issue'}))
    result = plane_service.send_article_to_plane(
        {'title': 'No Id Here', 'source': 'https://x/'}, 'summary')

    assert result['created'] is True
    assert captured.get('external_id', '').startswith('sha1:')
    assert captured.get('external_source') == plane_service.EXTERNAL_SOURCE


def test_the_derived_idempotency_key_is_stable_across_retries(monkeypatch):
    """Derived from the content, so the second attempt collides with the first at the
    server instead of filing a second to-do."""
    keys = []

    def _post(url, **kw):
        keys.append((kw.get('json') or {}).get('external_id'))
        return _FakeResponse(201, {'id': 'new-issue'})

    _stub_plane(monkeypatch, post=_post, get=lambda *a, **kw: _FakeResponse(200, {'id': 'new-issue'}))
    article = {'title': 'Same Article', 'source': 'https://x/'}
    plane_service.send_article_to_plane(article, 'summary')
    plane_service.send_article_to_plane(article, 'summary')

    assert keys[0] == keys[1]
    # ...and a different article does not collide with it
    plane_service.send_article_to_plane({'title': 'Other', 'source': 'https://x/'}, 'summary')
    assert keys[2] != keys[0]


def test_a_409_without_an_issue_id_is_reported_rather_than_silently_linked(monkeypatch):
    """Plane saying 'that external_id is taken' without naming the issue leaves nothing
    to record. Claiming success would tick nothing and retry into the same 409 forever."""
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(409, {'error': 'Conflict'}),
                get=lambda *a, **kw: _FakeResponse(200, {}))
    result = plane_service.send_article_to_plane(
        {'id': 'a.md', 'title': 'T', 'source': 'https://x/'}, 'summary')

    assert result['already_existed'] is True
    assert result['issue_id'] is None
    assert result['verified'] is False
    assert result['error'] and 'could not be linked' in result['error']


def _star_icon_of(user, marker):
    """The reader's Favorite control is an icon, not text, so the assertion has to read
    the rendered icon name. fa-solid = filled = favorited; fa-regular = hollow."""
    element = next(iter(user.find(marker=marker).elements))
    for child in element.descendants():
        name = getattr(child, '_props', {}).get('name', '')
        if 'star' in name:
            return name
    return ''


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_reader_star_repaints_when_the_open_article_is_toggled(user: User, isolated_intake):
    """Chris, 2026-08-04: toggling Favorite from the list row filled the row's star
    immediately while the reader's own star stayed hollow until something else rebuilt
    the reader. State on disk was always right -- purely a repaint gap."""
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'

    user.find(marker=f'article-row-{aid}').click()
    await asyncio.sleep(0.3)
    await user.should_see(marker='reader-mode-read')
    assert 'regular' in _star_icon_of(user, f'row-reader-f-{aid}'), 'should start unfavorited'

    user.find(marker=f'row-f-{aid}').click()      # toggle from the LIST row
    await asyncio.sleep(0.3)

    assert 'solid' in _star_icon_of(user, f'row-reader-f-{aid}'), \
        'the reader star did not repaint after the list row toggled it'


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_reader_star_repaints_when_toggled_from_the_reader_itself(user: User, isolated_intake):
    await user.open('/intake-test')
    await user.should_see('New Article')
    aid = '2026-07-30-235959-new-article.md'
    user.find(marker=f'article-row-{aid}').click()
    await asyncio.sleep(0.3)
    await user.should_see(marker='reader-mode-read')

    user.find(marker=f'row-reader-f-{aid}').click()   # toggle from the READER
    await asyncio.sleep(0.3)
    assert 'solid' in _star_icon_of(user, f'row-reader-f-{aid}')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_a_failed_queue_item_shows_its_full_error(user: User, isolated_intake, monkeypatch):
    """The error used to live only in a hover tooltip and clicking the entry retried it,
    so the one thing you could not do with a failure was read it (Chris, 2026-08-04)."""
    long_error = ('HTTPConnectionPool(host=\'100.74.2.92\', port=11434): Max retries exceeded '
                  'with url: /api/chat (Caused by NewConnectionError: Connection refused)')
    monkeypatch.setattr(intake_service, 'get_queue', lambda *a, **kw: [
        {'id': 'q1', 'url': 'https://example.com/an-article', 'status': 'failed',
         'retry_count': 3, 'last_error': long_error, 'added_at': '2026-08-22 10:00'},
    ])

    await user.open('/intake-test')
    await user.should_see('New Article')
    await user.should_see(marker='queue-failed-q1')

    user.find(marker='queue-failed-q1').click()
    await asyncio.sleep(0.3)

    await user.should_see('Queue item failed')
    await user.should_see('Connection refused')      # the full text, not a truncated row
    await user.should_see(marker='queue-copy-error')
    await user.should_see(marker='queue-retry')      # retry is still reachable, one click further


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_a_failed_item_with_no_recorded_error_still_opens(user: User, isolated_intake, monkeypatch):
    monkeypatch.setattr(intake_service, 'get_queue', lambda *a, **kw: [
        {'id': 'q2', 'url': 'https://example.com/x', 'status': 'failed', 'retry_count': 3},
    ])
    await user.open('/intake-test')
    await user.should_see(marker='queue-failed-q2')
    user.find(marker='queue-failed-q2').click()
    await asyncio.sleep(0.3)
    await user.should_see('no error recorded')


# ---------- the index fast path and the file fallback must agree ----------
#
# services/intake.py:list_articles() serves an article from the SQLite index when the index
# covers it and by parsing the file when it does not, and the page cannot tell which produced
# a given item. _article_from_row's own docstring says "the two must stay in step" -- which
# nothing enforced until this test. A divergence would not crash: it would render some
# articles subtly differently from others depending on index coverage, which is the failure
# class this repo keeps paying for.

def _build_index(db_path, articles_dir, filename, *, title, date_processed,
                 priority_score=5.0, tags=None, educational=False, body=None):
    import sqlite3
    conn = sqlite3.connect(str(db_path))
    conn.execute("""CREATE TABLE articles (
        file_path TEXT, title TEXT, date_processed TEXT, source_url TEXT, dup_of TEXT,
        auto_generated INTEGER, tags TEXT, suggested_tags TEXT, content_type TEXT,
        educational INTEGER, priority_score REAL, why_it_matters TEXT,
        user_folders TEXT, body TEXT, raw_content TEXT)""")
    path = os.path.join(str(articles_dir), filename)
    # The real indexer stores the article's whole body, headings and all -- the snippet
    # regex looks for '## Summary'. A stripped-down body here would fabricate a mismatch.
    if body is None:
        body = f'## Summary\n\nTest summary for {title}.\n'
    conn.execute('INSERT INTO articles VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (
        path, title, date_processed, f'https://example.com/{filename}', None, 0,
        json.dumps(tags or []), json.dumps([]), None, 1 if educational else 0,
        priority_score, None, json.dumps([]), body,
        (articles_dir / filename).read_text(encoding='utf-8')))
    conn.commit()
    conn.close()


def test_index_path_and_file_path_describe_an_article_identically(tmp_path, monkeypatch):
    articles_dir = tmp_path / 'articles'
    articles_dir.mkdir()
    _seed_article(articles_dir, '2026-05-05-101010-parity.md', title='Parity Article',
                  date_processed='2026-05-05 10:10:10', priority_score=7, tags=['docker'])
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(articles_dir))

    # First: no index at all, so the file fallback produces the article.
    monkeypatch.setattr(intake_service, 'INDEX_DB', str(tmp_path / 'absent.db'))
    monkeypatch.setattr(intake_service, '_articles_cache',
                        {'signature': None, 'articles': None})
    from_file = intake_service.list_articles()
    assert len(from_file) == 1, 'fallback did not produce the article'

    # Then: an index covering the same file, so the fast path produces it instead.
    db = tmp_path / 'articles.db'
    _build_index(db, articles_dir, '2026-05-05-101010-parity.md', title='Parity Article',
                 date_processed='2026-05-05 10:10:10', priority_score=7, tags=['docker'])
    monkeypatch.setattr(intake_service, 'INDEX_DB', str(db))
    monkeypatch.setattr(intake_service, '_articles_cache',
                        {'signature': None, 'articles': None})
    from_index = intake_service.list_articles()
    assert len(from_index) == 1, 'index path did not produce the article'

    assert from_index[0] == from_file[0], (
        'the index fast path and the file fallback disagree about the same article; '
        'the page cannot tell which served it, so this renders as an inconsistency '
        'nobody can trace'
    )


def test_an_unreadable_index_falls_back_instead_of_emptying_the_page(tmp_path, monkeypatch):
    """A blank page is a far worse failure than a slow one. A corrupt index must send
    list_articles() back to parsing files, not report an empty archive."""
    articles_dir = tmp_path / 'articles'
    articles_dir.mkdir()
    _seed_article(articles_dir, '2026-05-05-101010-parity.md', title='Parity Article',
                  date_processed='2026-05-05 10:10:10')
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(articles_dir))

    corrupt = tmp_path / 'articles.db'
    corrupt.write_bytes(b'this is not a sqlite database at all')
    monkeypatch.setattr(intake_service, 'INDEX_DB', str(corrupt))
    monkeypatch.setattr(intake_service, '_articles_cache',
                        {'signature': None, 'articles': None})

    articles = intake_service.list_articles()
    assert len(articles) == 1
    assert articles[0]['title'] == 'Parity Article'


def test_the_index_does_not_serve_rows_from_a_different_articles_dir(tmp_path, monkeypatch):
    """The index describes one directory. Pointed at another corpus it must contribute
    nothing rather than mixing two unrelated archives into one list."""
    articles_dir = tmp_path / 'articles'
    articles_dir.mkdir()
    other_dir = tmp_path / 'elsewhere'
    other_dir.mkdir()
    _seed_article(articles_dir, '2026-05-05-101010-here.md', title='Here',
                  date_processed='2026-05-05 10:10:10')
    _seed_article(other_dir, '2026-05-06-101010-there.md', title='There',
                  date_processed='2026-05-06 10:10:10')

    db = tmp_path / 'articles.db'
    _build_index(db, other_dir, '2026-05-06-101010-there.md', title='There',
                 date_processed='2026-05-06 10:10:10')

    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(articles_dir))
    monkeypatch.setattr(intake_service, 'INDEX_DB', str(db))
    monkeypatch.setattr(intake_service, '_articles_cache',
                        {'signature': None, 'articles': None})

    titles = [a['title'] for a in intake_service.list_articles()]
    assert titles == ['Here'], f'foreign corpus leaked into the list: {titles}'


def test_raw_content_is_lowercased_on_both_paths_because_search_depends_on_it(tmp_path,
                                                                              monkeypatch):
    """Parity alone would not catch both paths regressing together. pages/intake.py:307
    does `term in a['raw_content']` with an already-lowered term, so this field carries a
    contract of its own: it is a search index, not the article."""
    articles_dir = tmp_path / 'articles'
    articles_dir.mkdir()
    _seed_article(articles_dir, '2026-05-05-101010-caps.md', title='Kubernetes At Home',
                  date_processed='2026-05-05 10:10:10')
    monkeypatch.setattr(intake_service, 'ARTICLES_DIR', str(articles_dir))

    db = tmp_path / 'articles.db'
    _build_index(db, articles_dir, '2026-05-05-101010-caps.md', title='Kubernetes At Home',
                 date_processed='2026-05-05 10:10:10')
    monkeypatch.setattr(intake_service, 'INDEX_DB', str(db))
    monkeypatch.setattr(intake_service, '_articles_cache',
                        {'signature': None, 'articles': None})

    article = intake_service.list_articles()[0]
    assert article['raw_content'] == article['raw_content'].lower()
    # The capitalised word in the body must be findable by the lowered search term.
    assert 'kubernetes at home' in article['raw_content']


# ---------- Send to HomeLab: choosing the project ----------

def test_list_projects_fails_closed_rather_than_reporting_none(monkeypatch):
    """An empty list because Plane did not answer must not look like a workspace with no
    projects -- the picker would silently offer nothing and the user would conclude there
    is nowhere to send."""
    for name in ('PLANE_API_KEY', 'PLANE_API_URL', 'PLANE_WORKSPACE_SLUG', 'PLANE_PROJECT_ID'):
        monkeypatch.setattr(plane_service, name, 'stub')

    def _boom(*a, **kw):
        raise plane_service.requests.RequestException('connection refused')
    monkeypatch.setattr(plane_service.requests, 'get', _boom)

    out = plane_service.list_projects()
    assert out['ok'] is False
    assert out['projects'] == []
    assert 'connection refused' in out['error']


def test_list_projects_puts_the_configured_default_first(monkeypatch):
    for name, value in (('PLANE_API_KEY', 'k'), ('PLANE_API_URL', 'http://p'),
                        ('PLANE_WORKSPACE_SLUG', 'w'), ('PLANE_PROJECT_ID', 'default-id')):
        monkeypatch.setattr(plane_service, name, value)
    monkeypatch.setattr(plane_service, 'requests', type('R', (), {
        'get': staticmethod(lambda *a, **kw: _FakeResponse(200, {'results': [
            {'id': 'zeta', 'name': 'Zeta'},
            {'id': 'default-id', 'name': 'Homelab'},
            {'id': 'alpha', 'name': 'Alpha'}]})),
        'RequestException': Exception})())

    out = plane_service.list_projects()
    assert out['ok'] is True
    assert out['projects'][0]['id'] == 'default-id'
    assert [p['name'] for p in out['projects'][1:]] == ['Alpha', 'Zeta']


def test_a_send_names_the_project_it_landed_in(monkeypatch):
    """Without this the caller cannot record where the to-do went, and the re-check below
    has no way to ask the right project."""
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(201, {'id': 'new-issue'}),
                get=lambda *a, **kw: _FakeResponse(200, {'id': 'new-issue'}))
    result = plane_service.send_article_to_plane(
        {'title': 'T', 'source': 'https://x/'}, 'summary', project_id='other-project')
    assert result['project_id'] == 'other-project'


def test_issue_status_asks_the_project_it_is_given(monkeypatch):
    """The trap this guards. issue_status() is allowed to CLEAR the article's only link to
    its to-do when it reads 'gone'. An issue filed in another project answers 404 from the
    default one -- indistinguishable from deleted -- so asking the wrong project would
    orphan a live to-do and mark the article unsent."""
    for name, value in (('PLANE_API_KEY', 'k'), ('PLANE_API_URL', 'http://p'),
                        ('PLANE_WORKSPACE_SLUG', 'w'), ('PLANE_PROJECT_ID', 'default-id')):
        monkeypatch.setattr(plane_service, name, value)
    asked = []

    def _get(url, **kw):
        asked.append(url)
        return _FakeResponse(200, {'id': 'issue-1'})
    monkeypatch.setattr(plane_service, 'requests',
                        type('R', (), {'get': staticmethod(_get),
                                       'RequestException': Exception})())

    assert plane_service.issue_status('issue-1', 'other-project') == 'present'
    assert '/projects/other-project/' in asked[-1]
    assert '/projects/default-id/' not in asked[-1]

    plane_service.issue_status('issue-1')
    assert '/projects/default-id/' in asked[-1]      # None still means the default


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_sending_records_which_project_the_todo_went_to(user: User, isolated_intake,
                                                              monkeypatch):
    """End to end: what the send returns has to reach intake_state, or the re-check will
    ask the default project about an issue that is not in it."""
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']

    monkeypatch.setattr(plane_service, 'send_article_to_plane',
                        lambda article, summary, project_id=None: {
                            'created': True, 'verified': True, 'already_existed': False,
                            'issue_id': 'issue-9', 'project_id': 'chosen-project',
                            'error': None})

    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker=f'send-icon-{aid}').click()

    def _recorded_project():
        # The file does not exist until the first write, so tolerate its absence rather
        # than racing it.
        if not state_file.exists():
            return None
        return json.loads(state_file.read_text()).get('articles', {}).get(aid, {}).get(
            'plane_project_id')

    recorded = await _wait_until(lambda: _recorded_project() == 'chosen-project')
    assert recorded, (
        f'project not recorded: '
        f'{state_file.read_text() if state_file.exists() else "(no state file)"!r}')


# ---------- updating a sent to-do: refresh, never clobber (Chris's call, 2026-09-11) ----------
#
# A sent to-do used to be write-once. update_article_todo() may replace its name and
# description only while Plane still holds exactly what the dashboard last wrote; any hand
# edit there turns the update into a comment. The fingerprint is taken from what Plane
# STORES, because Plane rewrites description_html on save -- `<p>` comes back as
# `<div><p>` -- so a fingerprint of what we sent would read every to-do as edited.

_ARTICLE = {'id': 'a.md', 'title': 'T', 'source': 'https://x/'}


class _PlaneDouble:
    """Just enough of Plane: one issue whose stored HTML is rewritten on every write, the
    way the real one does it, plus a record of every write made."""

    def __init__(self, name='T', description_html='<div><p>summary</p></div>'):
        self.issue = {'id': 'issue-1', 'name': name, 'description_html': description_html}
        self.writes = []
        self.get_status = 200

    def get(self, url, **kw):
        return _FakeResponse(self.get_status, dict(self.issue) if self.get_status == 200 else {})

    def post(self, url, json=None, **kw):
        self.writes.append(('POST', url, json))
        if url.endswith('/comments/'):
            return _FakeResponse(201, {'id': 'comment-1'})
        self.issue.update(name=json['name'], description_html=f"<div>{json['description_html']}</div>")
        return _FakeResponse(201, {'id': 'issue-1'})

    def patch(self, url, json=None, **kw):
        self.writes.append(('PATCH', url, json))
        self.issue.update(name=json['name'], description_html=f"<div>{json['description_html']}</div>")
        return _FakeResponse(200, dict(self.issue))

    def install(self, monkeypatch):
        _stub_plane(monkeypatch, post=self.post, get=self.get, patch=self.patch)
        return self


def _sent(monkeypatch, plane):
    result = plane_service.send_article_to_plane(_ARTICLE, 'summary')
    assert result['verified'] and result['fingerprint'], result
    plane.writes.clear()
    return result['fingerprint']


def test_a_send_fingerprints_what_plane_stored_not_what_was_sent(monkeypatch):
    plane = _PlaneDouble().install(monkeypatch)
    fingerprint = _sent(monkeypatch, plane)
    assert fingerprint['held'] == plane_service._held(plane.issue)
    assert fingerprint['held'] != plane_service._sha('T', '<p>summary</p>')


def test_a_resend_that_hits_409_vouches_for_nothing(monkeypatch):
    """A 409 links an issue this call did not write. Someone may have edited it since, so
    there is nothing to fingerprint -- and a later update must comment, not overwrite."""
    _stub_plane(monkeypatch,
                post=lambda *a, **kw: _FakeResponse(409, {'id': 'existing-issue'}),
                get=lambda *a, **kw: _FakeResponse(200, {'id': 'existing-issue'}))
    result = plane_service.send_article_to_plane(_ARTICLE, 'summary')
    assert result['issue_id'] == 'existing-issue' and result['fingerprint'] is None


def test_an_untouched_todo_is_refreshed_in_place(monkeypatch):
    plane = _PlaneDouble().install(monkeypatch)
    fingerprint = _sent(monkeypatch, plane)

    result = plane_service.update_article_todo(_ARTICLE, 'a better summary', 'issue-1',
                                               fingerprint=fingerprint)

    assert result['outcome'] == 'refreshed', result
    assert [w[0] for w in plane.writes] == ['PATCH']
    assert 'a better summary' in plane.writes[0][2]['description_html']
    # The new fingerprint is again what Plane stored, so a SECOND update still refreshes.
    assert result['fingerprint']['held'] == plane_service._held(plane.issue)
    again = plane_service.update_article_todo(_ARTICLE, 'better still', 'issue-1',
                                              fingerprint=result['fingerprint'])
    assert again['outcome'] == 'refreshed'


def test_a_todo_edited_in_plane_gets_a_comment_and_keeps_the_edit(monkeypatch):
    """The whole point. Chris's notes on the to-do must survive an update from the article."""
    plane = _PlaneDouble().install(monkeypatch)
    fingerprint = _sent(monkeypatch, plane)
    plane.issue['description_html'] = '<div><p>summary</p><p>MY OWN NOTES</p></div>'

    result = plane_service.update_article_todo(_ARTICLE, 'a better summary', 'issue-1',
                                               fingerprint=fingerprint)

    assert result['outcome'] == 'commented' and result['reason'] == 'edited', result
    assert [(w[0], w[1].endswith('/comments/')) for w in plane.writes] == [('POST', True)]
    assert 'a better summary' in plane.writes[0][2]['comment_html']
    assert 'MY OWN NOTES' in plane.issue['description_html']
    # `held` must NOT become the edited version, or the next update would overwrite it.
    assert result['fingerprint']['held'] == fingerprint['held']
    plane.writes.clear()
    later = plane_service.update_article_todo(_ARTICLE, 'newer again', 'issue-1',
                                              fingerprint=result['fingerprint'])
    assert later['outcome'] == 'commented' and 'MY OWN NOTES' in plane.issue['description_html']


def test_a_retitled_todo_counts_as_edited_too(monkeypatch):
    plane = _PlaneDouble().install(monkeypatch)
    fingerprint = _sent(monkeypatch, plane)
    plane.issue['name'] = 'T -- renamed in Plane'
    result = plane_service.update_article_todo(_ARTICLE, 'new', 'issue-1', fingerprint=fingerprint)
    assert result['outcome'] == 'commented' and plane.issue['name'] == 'T -- renamed in Plane'


def test_a_todo_with_no_fingerprint_is_never_overwritten(monkeypatch):
    """Everything sent before this existed. Nobody can say whether it was edited."""
    plane = _PlaneDouble().install(monkeypatch)
    result = plane_service.update_article_todo(_ARTICLE, 'new', 'issue-1', fingerprint=None)
    assert result['outcome'] == 'commented' and result['reason'] == 'untracked'
    assert [w[0] for w in plane.writes] == ['POST']
    assert 'cannot tell whether' in plane.writes[0][2]['comment_html']


def test_an_unchanged_article_writes_nothing(monkeypatch):
    """Clicking twice must not stack identical comments on the to-do."""
    plane = _PlaneDouble().install(monkeypatch)
    fingerprint = _sent(monkeypatch, plane)
    result = plane_service.update_article_todo(_ARTICLE, 'summary', 'issue-1',
                                               fingerprint=fingerprint)
    assert result['outcome'] == 'unchanged' and plane.writes == []

    commented = plane_service.update_article_todo(_ARTICLE, 'new', 'issue-1', fingerprint=None)
    plane.writes.clear()
    repeat = plane_service.update_article_todo(_ARTICLE, 'new', 'issue-1',
                                               fingerprint=commented['fingerprint'])
    assert repeat['outcome'] == 'unchanged' and plane.writes == []


def test_update_reads_gone_and_unknown_the_way_issue_status_does(monkeypatch):
    plane = _PlaneDouble().install(monkeypatch)
    fingerprint = _sent(monkeypatch, plane)
    plane.get_status = 404
    assert plane_service.update_article_todo(_ARTICLE, 'new', 'issue-1',
                                             fingerprint=fingerprint)['outcome'] == 'gone'
    for code in (401, 500, 502):
        plane.get_status = code
        result = plane_service.update_article_todo(_ARTICLE, 'new', 'issue-1',
                                                   fingerprint=fingerprint)
        assert result['outcome'] == 'unknown' and result['fingerprint'] == fingerprint, code
    assert plane.writes == []


def test_a_failed_write_keeps_the_old_fingerprint(monkeypatch):
    plane = _PlaneDouble().install(monkeypatch)
    fingerprint = _sent(monkeypatch, plane)
    monkeypatch.setattr(plane_service.requests, 'patch',
                        lambda *a, **kw: _FakeResponse(500, {}))
    result = plane_service.update_article_todo(_ARTICLE, 'new', 'issue-1', fingerprint=fingerprint)
    assert result['outcome'] == 'failed' and result['fingerprint'] == fingerprint
    assert '500' in result['error']


def _recorded(state_file, aid):
    return json.loads(state_file.read_text()).get('articles', {}).get(aid, {})


async def _open_reader(user, aid):
    await user.open('/intake-test')
    await user.should_see('New Article')
    user.find(marker=f'article-row-{aid}').click()
    await user.should_see(marker=f'reader-update-todo-{aid}')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_updating_a_todo_records_the_new_fingerprint(user: User, isolated_intake,
                                                           monkeypatch):
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']
    _already_filed_state(state_file, aid)
    calls = []

    def _update(article, summary, issue_id, project_id=None, fingerprint=None):
        calls.append((issue_id, fingerprint))
        return {'outcome': 'refreshed', 'fingerprint': {'sent': 's2', 'held': 'h2'},
                'error': None}

    monkeypatch.setattr(plane_service, 'update_article_todo', _update)
    await _open_reader(user, aid)
    user.find(marker=f'reader-update-todo-{aid}').click()

    assert await _wait_until(lambda: _recorded(state_file, aid).get('plane_fingerprint')
                             == {'sent': 's2', 'held': 'h2'}), state_file.read_text()
    assert calls == [('already-filed-id', None)]
    await user.should_see('To-do updated in HomeLab.')
    assert _recorded(state_file, aid)['plane_issue_id'] == 'already-filed-id'


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_updating_a_todo_deleted_in_plane_unlinks_it(user: User, isolated_intake,
                                                           monkeypatch):
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']
    _already_filed_state(state_file, aid)
    monkeypatch.setattr(plane_service, 'update_article_todo',
                        lambda *a, **kw: {'outcome': 'gone', 'fingerprint': None, 'error': None})
    await _open_reader(user, aid)
    user.find(marker=f'reader-update-todo-{aid}').click()

    assert await _wait_until(lambda: _recorded(state_file, aid).get('plane_issue_id') is None)
    await user.should_see(marker=f'reader-send-icon-{aid}')


@pytest.mark.nicegui_main_file('test_intake_fixes.py')
async def test_an_update_that_could_not_reach_plane_changes_nothing(user: User, isolated_intake,
                                                                    monkeypatch):
    aid = '2026-07-30-235959-new-article.md'
    state_file = isolated_intake['state_file']
    _already_filed_state(state_file, aid)
    before = state_file.read_text()
    monkeypatch.setattr(plane_service, 'update_article_todo',
                        lambda *a, **kw: {'outcome': 'unknown', 'fingerprint': None,
                                          'error': 'HomeLab did not answer.'})
    await _open_reader(user, aid)
    user.find(marker=f'reader-update-todo-{aid}').click()

    await user.should_see('Could not reach HomeLab — nothing was changed.')
    assert json.loads(state_file.read_text())['articles'][aid] == json.loads(before)['articles'][aid]
    await user.should_see(marker=f'reader-update-todo-{aid}')
