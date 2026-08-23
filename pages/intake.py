import re
from datetime import datetime
from urllib.parse import urlparse

from nicegui import run, ui

from components import ai_context, discuss_panel, live_state, theme
from components.confirm_dialog import confirm
from components.util import capture_client, client_alive, notify_on
from services import fulltext, intake, intake_state, plane
from services.ai import discuss

SORT_OPTIONS = [
    ('unread', 'Unread first'), ('date', 'Newest first'), ('priority', 'Priority'),
    ('title', 'Title A-Z'), ('favorite', 'Favorites first'),
]

SHORTCUTS = [
    ('j / ↓', 'Next article'), ('k / ↑', 'Previous article'), ('Enter', 'Open focused article'),
    ('x', 'Toggle selection'), ('r', 'Toggle read/unread'), ('f', 'Toggle favorite'),
    ('a', 'Toggle archived'), ('s', 'Send to HomeLab'), ('Del', 'Delete'),
    ('?', 'This cheat sheet'), ('Esc', 'Close'),
]

# Fixed status entries in the folder/status dropdown. Custom folders (from
# intake_state.list_folders()) are appended after these. Archiving semantics (agreed
# with Chris 2026-07-31): archived hides an article from 'all' and from plain
# tag-browsing only -- Favorites and Duplicates are deliberate "keep visible to me"
# collections, independent of triage state, so both INCLUDE archived items. Custom
# folders get the same treatment as Favorites (a folder is a deliberate collection too).
STATUS_ENTRIES = [
    ('all', 'fa-solid fa-inbox', 'All'),
    ('education', 'fa-solid fa-graduation-cap', 'Education'),
    ('favorites', 'fa-solid fa-star', 'Favorites'),
    ('duplicates', 'fa-solid fa-clone', 'Duplicates'),
    ('archived', 'fa-solid fa-box-archive', 'Archived'),
]

def _tag_frequencies(articles: list[dict]) -> dict:
    """How often each tag appears across the whole archive -- the weight used to pick an
    article's sub-topic."""
    counts: dict[str, int] = {}
    for a in articles:
        for t in a.get('tags') or []:
            counts[t] = counts.get(t, 0) + 1
    return counts


def _subtopic_of(article: dict, freqs: dict) -> str:
    """An article's sub-topic heading: whichever of its tags is most used across the archive.

    `primary_domain` used to supply this — a single-valued enum, so every article had exactly
    one home for free. Tags are multi-valued and can't give that on their own, so the single
    home is recovered by a rule instead of a field: most-common tag wins, alphabetical to
    break ties so the grouping is stable between renders rather than dependent on tag order.
    Articles with no tags fall through to a catch-all rather than vanishing from the view."""
    tags = article.get('tags') or []
    if not tags:
        return 'Other'
    return sorted(tags, key=lambda t: (-freqs.get(t, 0), t))[0]


OTHER_SUBTOPIC = 'Other'


def _group_by_subtopic(articles: list[dict], freqs: dict, min_group: int = 2) -> list[tuple]:
    """Returns [(heading, items)] largest-first, with `Other` always last.

    Groups smaller than `min_group` are folded into `Other`. Without that fold the archive's
    tag distribution produces a heading per article -- measured on the real corpus, grouping
    23 educational articles by top tag gave 16 headings, 13 holding a single item, which is
    less navigable than no grouping at all. A minimum group size targets that directly and
    self-heals: as the archive grows and the vocabulary consolidates, real groups clear the
    bar on their own and `Other` shrinks without anyone tuning a threshold."""
    buckets: dict[str, list] = {}
    for a in articles:
        buckets.setdefault(_subtopic_of(a, freqs), []).append(a)

    named, other = [], list(buckets.pop(OTHER_SUBTOPIC, []))
    for heading, items in buckets.items():
        if len(items) >= min_group:
            named.append((heading, items))
        else:
            other.extend(items)

    named.sort(key=lambda pair: (-len(pair[1]), pair[0]))
    if other:
        named.append((OTHER_SUBTOPIC, other))
    return named

_FILENAME_TS_RE = re.compile(r'^(\d{4})-(\d{2})-(\d{2})-(\d{2})(\d{2})(\d{2})')


def _date_sort_key(article: dict) -> datetime:
    """Prefers the parsed 'date' field (reliable for frontmatter articles -- it's
    date_processed[:19] in '%Y-%m-%d %H:%M:%S'); falls back to the filename's own
    embedded timestamp for legacy articles whose 'date' is unparseable free text --
    every file (frontmatter or legacy) is named YYYY-MM-DD-HHMMSS-*.md, so this
    fallback never raises and stays chronologically meaningful."""
    raw = (article.get('date') or '').strip()
    try:
        return datetime.strptime(raw[:19], '%Y-%m-%d %H:%M:%S')
    except ValueError:
        m = _FILENAME_TS_RE.match(article.get('id') or '')
        if m:
            try:
                return datetime(*(int(g) for g in m.groups()))
            except ValueError:
                pass
        return datetime.min


def _short_url(url: str) -> str:
    try:
        return urlparse(url).hostname or url
    except Exception:
        return url


def _badge(article: dict) -> tuple[str, str]:
    if article['is_duplicate']:
        return 'Duplicate', '#fab387'
    if article['auto_generated']:
        return 'Automated', theme.ACCENT
    return 'Manual', '#b8c0d9'


async def _prompt_folder_choice(folders: list[str]) -> str | None:
    with ui.dialog() as dialog, ui.card().style(
            f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;'
            f'padding:22px;width:360px'):
        ui.label('Move to folder').style(f'font-size:15px;font-weight:700;color:{theme.TEXT};margin-bottom:10px')
        folder_select = None
        if folders:
            folder_select = ui.select(options=folders, label='Existing folder').style(
                'width:100%;margin-bottom:10px').props('outlined dense clearable')
        new_input = ui.input(placeholder='Or type a new folder name').style('width:100%').props('outlined dense')
        with ui.row().classes('justify-end w-full').style('gap:10px;margin-top:14px'):
            ui.button('Cancel', on_click=lambda: dialog.submit(None)).props('flat').style(
                f'color:{theme.TEXT_MUTED}')
            ui.button('Move', on_click=lambda: dialog.submit(
                (new_input.value or '').strip() or (folder_select.value if folder_select else None)
            )).style(f'background:{theme.ACCENT};color:{theme.BG};font-weight:700')
    return await dialog


async def _show_cheatsheet():
    with ui.dialog() as dialog, ui.card().style(
            f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;'
            f'padding:22px;width:340px'):
        ui.label('Keyboard shortcuts').style(f'font-size:15px;font-weight:700;color:{theme.TEXT};margin-bottom:12px')
        with ui.column().style('gap:8px;width:100%'):
            for key, desc in SHORTCUTS:
                with ui.row().classes('items-center justify-between no-wrap').style('width:100%'):
                    ui.label(desc).style(f'font-size:12.5px;color:{theme.TEXT_MUTED}')
                    ui.label(key).style(
                        f'font-family:"JetBrains Mono",monospace;font-size:11px;color:{theme.TEXT};'
                        f'background:rgba(255,255,255,0.06);border-radius:5px;padding:2px 7px')
        ui.button('Close', on_click=dialog.close).props('flat').style(f'margin-top:14px;color:{theme.TEXT_MUTED}')
    await dialog


def build():
    state = {
        'articles': [], 'queue': [], 'workflow': {}, 'folders': [],
        # homelab-intake's controlled vocabulary, backing the tag editor's search box.
        'tag_vocabulary': [],
        'prefs': {'density': 'cozy', 'sort': 'unread'},
        'folder': 'all', 'tag_filters': set(), 'tag_search': '', 'search': '',
        'select_mode': False, 'selected_ids': set(),
        'selected': None, 'article_content': None, 'reader_mode': 'read',
        'reader_size': 'normal',
        # 'idle' -> no source URL (never fetchable); 'loading' -> fetch in flight;
        # 'ready' -> text populated; 'failed' -> fetch failed, retry offered
        'fulltext': {'status': 'idle', 'text': None},
        'discuss': {'model': intake_state.DEFAULT_MODEL, 'active_sources': {'article', 'archive'},
                     'repo_scope_open': False, 'thread': [], 'busy': False},
        'focused_id': None, 'articles_loaded': False, 'sending_ids': set(), 'confirming_ids': set(),
        'verifying_ids': set(),
        'thread_counts': {},
    }
    # Populated by render_tag_dropdown() each time it (re)builds; lets select_tag()
    # restyle a single row's checked-state in place instead of refreshing the whole
    # dropdown, which would otherwise close it (a NiceGUI @ui.refreshable tears down
    # and recreates its subtree on .refresh(), and a recreated ui.menu() defaults to
    # closed) -- needed so picking several tags in one visit doesn't reopen the menu
    # after every click.
    tag_row_elements: dict[str, tuple] = {}
    # Captured by render_toolbar() when it creates the search input; lets
    # clear_search() reset the box's displayed value directly rather than needing to
    # refresh (and thereby tear down/rebuild) the toolbar that contains it.
    ui_refs: dict[str, object] = {'search_input': None}
    # Per-article @ui.refreshable closures (created lazily, keyed by article id) --
    # lets a single-article change (favorite/read/archived) re-render just that one
    # row instead of paying render_articles.refresh()'s full-list rebuild cost (all
    # visible rows torn down and recreated) for a change that affects one row's
    # visuals. See _get_row_refreshable() below.
    row_refreshables: dict[str, object] = {}

    def _wf(aid):
        return state['workflow'].get(aid, {'read': False, 'favorite': False, 'archived': False})

    def _apply_workflow_change(aid, **fields):
        """Patch state['workflow'][aid] in memory from a value we already just wrote to
        disk -- avoids re-fetching all_article_states() (every article) for a change we
        know affects exactly one."""
        current = dict(_wf(aid))
        current.update(fields)
        state['workflow'][aid] = current
        return current

    def _refresh_after_workflow_change(aid, before_ids):
        """Single-article read/favorite/archived toggles only need to touch that one
        row's visuals in the common case. But the same toggle can also change which
        articles are visible (e.g. unfavoriting while viewing the Favorites folder) or
        their order (e.g. toggling read under the default 'Unread first' sort) --
        recomputing the full list is the only way to know that reliably (mirrors
        filtered_articles()'s own filter/sort rules exactly, no risk of the two
        drifting apart), but it's cheap in itself: comparing two lists of ~100 ids is
        microseconds, unlike render_articles.refresh()'s full row rebuild. Only pay
        that full rebuild when membership/order actually changed; otherwise refresh
        just the one row that changed."""
        after_ids = [a['id'] for a in filtered_articles()]
        if before_ids != after_ids:
            render_articles.refresh()
        else:
            _get_row_refreshable(aid).refresh()
        # The reader's own action row draws the same read/favorite/archived state, so a
        # toggle on the article that happens to be open has to repaint it too. Without
        # this the list row's star fills immediately and the reader's stays hollow until
        # something else rebuilds the reader -- switching articles, opening Discuss.
        # Fixed here rather than in each toggle so a fourth one cannot forget. (Reported
        # by Chris 2026-08-04; also bit Discuss mode, which shows the same row.)
        if state.get('selected') == aid:
            render_reader.refresh()

    # ---------- folder scoping (archiving semantics live here) ----------

    def _folder_scoped_articles():
        arts = state['articles']
        folder = state['folder']
        if folder == 'archived':
            return [a for a in arts if _wf(a['id'])['archived']]
        if folder == 'favorites':
            return [a for a in arts if _wf(a['id'])['favorite']]
        if folder == 'duplicates':
            return [a for a in arts if a['is_duplicate']]
        if folder == 'education':
            # Same archived/duplicate hiding as 'all' -- this is a reading view, so handled
            # and duplicate items are noise here for exactly the same reason.
            return [a for a in arts if a.get('educational')
                    and not _wf(a['id'])['archived'] and not a['is_duplicate']]
        if folder.startswith('custom:'):
            name = folder[len('custom:'):]
            return [a for a in arts if name in a.get('user_folders', [])]
        # 'all' -- the main triage view: hides archived (handled) and duplicates
        # (pipeline noise, reviewed separately via the Duplicates entry instead)
        return [a for a in arts if not _wf(a['id'])['archived'] and not a['is_duplicate']]

    def status_counts():
        arts = state['articles']
        live = [a for a in arts if not _wf(a['id'])['archived']]
        return {
            'all': len(live),
            'education': len([a for a in live if a.get('educational') and not a['is_duplicate']]),
            'favorites': len([a for a in arts if _wf(a['id'])['favorite']]),
            'duplicates': len([a for a in arts if a['is_duplicate']]),
            'archived': len([a for a in arts if _wf(a['id'])['archived']]),
        }

    def custom_folder_counts():
        return {name: len([a for a in state['articles'] if name in a.get('user_folders', [])])
                for name in state['folders']}

    def available_tags():
        counts = {}
        for a in _folder_scoped_articles():
            for t in a.get('tags', []):
                counts[t] = counts.get(t, 0) + 1
        tags = sorted(counts.items(), key=lambda kv: -kv[1])
        if state['tag_search']:
            term = state['tag_search'].lower()
            tags = [(t, c) for t, c in tags if term in t.lower()]
        return tags

    def _sorted_articles(arts):
        sort = state['prefs'].get('sort', 'unread')
        if sort == 'date':
            return sorted(arts, key=_date_sort_key, reverse=True)
        if sort == 'priority':
            return sorted(arts, key=lambda a: -(a.get('priority_score') or 0))
        if sort == 'title':
            return sorted(arts, key=lambda a: a['title'].lower())
        if sort == 'unread':
            return sorted(arts, key=lambda a: _wf(a['id'])['read'])
        if sort == 'favorite':
            return sorted(arts, key=lambda a: not _wf(a['id'])['favorite'])
        return arts

    def filtered_articles():
        arts = _folder_scoped_articles()
        if state['tag_filters']:
            arts = [a for a in arts if state['tag_filters'].issubset(set(a.get('tags', [])))]
        term = state['search'].lower()
        if term:
            arts = [a for a in arts if
                    term in a['title'].lower() or term in a.get('raw_content', '') or
                    term in a.get('snippet', '').lower() or
                    any(term in t.lower() for t in a.get('tags', []))]
        return _sorted_articles(arts)

    # ---------- folder / tag / search / density / select actions ----------

    def select_folder(key):
        state['folder'] = key
        state['tag_filters'] = set()
        state['selected_ids'] = set()
        state['select_mode'] = False
        render_folder_dropdown.refresh()
        render_tag_dropdown.refresh()
        render_filter_chips.refresh()
        render_articles.refresh()
        render_bulk_bar.refresh()

    def select_tag(tag):
        if tag in state['tag_filters']:
            state['tag_filters'].discard(tag)
        else:
            state['tag_filters'].add(tag)
        active = tag in state['tag_filters']
        refs = tag_row_elements.get(tag)
        if refs:
            row_el, label_el = refs
            row_el.style(f'background:{theme.ACCENT_TINT if active else "transparent"}')
            label_el.style(
                f'flex:1;font-size:12px;color:{theme.ACCENT if active else theme.TEXT_MUTED};'
                f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
        render_articles.refresh()
        render_header.refresh()
        render_filter_chips.refresh()

    def clear_tags():
        state['tag_filters'] = set()
        render_tag_dropdown.refresh()
        render_articles.refresh()
        render_header.refresh()
        render_filter_chips.refresh()

    def on_tag_search(e):
        state['tag_search'] = e.value or ''
        render_tag_dropdown.refresh()

    def on_search(e):
        state['search'] = e.value or ''
        render_articles.refresh()
        render_header.refresh()
        render_filter_chips.refresh()

    def clear_search():
        state['search'] = ''
        if ui_refs['search_input'] is not None:
            ui_refs['search_input'].value = ''
        render_articles.refresh()
        render_header.refresh()
        render_filter_chips.refresh()

    async def set_sort(value):
        state['prefs']['sort'] = value
        await run.io_bound(intake_state.set_prefs, sort=value)
        render_articles.refresh()

    async def set_density(value):
        state['prefs']['density'] = value
        await run.io_bound(intake_state.set_prefs, density=value)
        render_articles.refresh()

    def toggle_select_mode():
        state['select_mode'] = not state['select_mode']
        if not state['select_mode']:
            state['selected_ids'] = set()
        render_articles.refresh()
        render_bulk_bar.refresh()

    def toggle_row_selected(aid):
        if aid in state['selected_ids']:
            state['selected_ids'].discard(aid)
        else:
            state['selected_ids'].add(aid)
        render_articles.refresh()
        render_bulk_bar.refresh()

    def clear_selection():
        state['selected_ids'] = set()
        render_articles.refresh()
        render_bulk_bar.refresh()

    async def create_new_folder():
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;'
                f'padding:22px;width:320px'):
            ui.label('New folder').style(f'font-size:15px;font-weight:700;color:{theme.TEXT};margin-bottom:10px')
            name_input = ui.input(placeholder='Folder name').style('width:100%').props('outlined dense')
            with ui.row().classes('justify-end w-full').style('gap:10px;margin-top:14px'):
                ui.button('Cancel', on_click=lambda: dialog.submit(None)).props('flat').style(
                    f'color:{theme.TEXT_MUTED}')
                ui.button('Create', on_click=lambda: dialog.submit((name_input.value or '').strip())).style(
                    f'background:{theme.ACCENT};color:{theme.BG};font-weight:700')
        name = await dialog
        if name:
            await run.io_bound(intake_state.create_folder, name)
            folders = await run.io_bound(intake_state.list_folders)
            if folders is not None:
                state['folders'] = folders
            render_folder_dropdown.refresh()

    # ---------- workflow state (read/favorite/archived) ----------

    async def reload_workflow():
        # Captured up front: render_articles.refresh() below tears down this handler's
        # originating row/list slot, and live_state.refresh_all() below that would
        # otherwise re-resolve context.client fresh and find it gone. See
        # capture_client()'s docstring for the full mechanism.
        client = capture_client()
        wf = await run.io_bound(intake_state.all_article_states)
        if wf is not None and client_alive(client):
            state['workflow'] = wf
            render_articles.refresh()
            render_folder_dropdown.refresh()
            render_header.refresh()
            render_reader.refresh()
            live_state.refresh_all(exclude='intake', client=client)

    async def toggle_read(aid):
        client = capture_client()
        new_val = not _wf(aid)['read']
        before_ids = [a['id'] for a in filtered_articles()]
        await run.io_bound(intake_state.set_article_state, aid, read=new_val)
        if client_alive(client):
            _apply_workflow_change(aid, read=new_val)
            _refresh_after_workflow_change(aid, before_ids)
            render_header.refresh()
            live_state.refresh_all(exclude='intake', client=client)

    async def toggle_favorite(aid):
        client = capture_client()
        new_val = not _wf(aid)['favorite']
        before_ids = [a['id'] for a in filtered_articles()]
        await run.io_bound(intake_state.set_article_state, aid, favorite=new_val)
        if client_alive(client):
            _apply_workflow_change(aid, favorite=new_val)
            _refresh_after_workflow_change(aid, before_ids)
            render_folder_dropdown.refresh()

    async def toggle_archived(aid):
        client = capture_client()
        new_val = not _wf(aid)['archived']
        before_ids = [a['id'] for a in filtered_articles()]
        await run.io_bound(intake_state.set_article_state, aid, archived=new_val)
        if not client_alive(client):
            return
        _apply_workflow_change(aid, archived=new_val)
        _refresh_after_workflow_change(aid, before_ids)
        render_folder_dropdown.refresh()
        render_header.refresh()
        live_state.refresh_all(exclude='intake', client=client)

    async def send_to_homelab(aid):
        if aid in state['sending_ids']:
            return
        art = next((a for a in state['articles'] if a['id'] == aid), None)
        if not art:
            return
        # The row/reader control renders as an inert checkmark once sent, but the `s`
        # shortcut still reaches here -- and an unguarded second send files a duplicate
        # to-do, which is exactly how the lost-toast bug produced two.
        if _wf(aid).get('plane_issue_id'):
            notify_on(capture_client(), 'Already sent to HomeLab.', type='info')
            return
        # Captured before render_articles.refresh() below tears down this handler's
        # originating row slot -- see capture_client()'s docstring for the full
        # mechanism. Without this, every client_alive() check past that refresh would
        # wrongly read as "tab disconnected" and silently skip the result toast/refresh.
        client = capture_client()
        state['sending_ids'].add(aid)
        render_articles.refresh()
        if state.get('selected') == aid:
            render_reader.refresh()
        try:
            data = await run.io_bound(intake.get_article, aid)
            summary = (data.get('summary') if data else '') or art.get('why_it_matters') or art.get('snippet') or ''
            result = await run.io_bound(plane.send_article_to_plane, art, summary)
        except Exception as e:  # noqa: BLE001 -- see below
            # Anything escaping here would skip every refresh and toast past this point,
            # leaving the row's spinner turning forever with the reason only in the service
            # log. Funnel it into the normal failure result instead so the UI still resolves.
            result = {'created': False, 'verified': False, 'issue_id': None,
                      'already_existed': False, 'error': f'{type(e).__name__}: {e}'}
        finally:
            state['sending_ids'].discard(aid)
        if result is None:
            # run.io_bound yields None when its work was cancelled (tab closed mid-send).
            if client_alive(client):
                render_articles.refresh()
                if state.get('selected') == aid:
                    render_reader.refresh()
            return
        success, error = result['created'], result['error']
        if success:
            # Persist unconditionally (mirrors toggle_read/toggle_favorite/toggle_archived) --
            # the Plane to-do was really created, so local state must reflect that even if
            # the tab closes mid-request; only the in-memory patch/refresh needs a live client.
            await run.io_bound(intake_state.set_article_state, aid, read=True, archived=True,
                                plane_issue_id=result['issue_id'])
            if client_alive(client):
                _apply_workflow_change(aid, read=True, archived=True,
                                        plane_issue_id=result['issue_id'])
                render_articles.refresh()
                render_folder_dropdown.refresh()
                render_header.refresh()
                live_state.refresh_all(exclude='intake', client=client)
                if state.get('selected') == aid:
                    render_reader.refresh()
                if result['already_existed'] and not result['issue_id']:
                    # Plane confirmed the duplicate but would not say which issue it is,
                    # so nothing got linked. Saying "linked" here would be a plain lie.
                    notify_on(client, 'Already filed in HomeLab, but the to-do could not be '
                                      'identified — nothing was linked.', type='warning')
                elif result['already_existed']:
                    # Plane already had an issue under this article's external_id -- a
                    # resend recovered it rather than duplicating it.
                    notify_on(client, 'Already filed in HomeLab · linked to the existing to-do.',
                              type='info')
                elif result['verified']:
                    notify_on(client, 'Sent to HomeLab · to-do created, article archived.',
                              type='positive')
                else:
                    # Created, but the read-back could not find it. Say so rather than
                    # claiming success -- and still record the id, so no retry duplicates it.
                    notify_on(client, 'Sent to HomeLab, but could not confirm the to-do exists.',
                              type='warning')
        else:
            if client_alive(client):
                render_articles.refresh()
                if state.get('selected') == aid:
                    render_reader.refresh()
                notify_on(client, f'Failed to send to HomeLab: {error}', type='negative')

    async def verify_plane_todo(aid):
        """Re-checks a recorded to-do against Plane, clearing the checkmark if it is gone.

        Without this the checkmark is a one-way door: plane_issue_id was written on a
        successful send and nothing anywhere cleared it, while the control it drives is
        inert and the `s` shortcut refuses to resend. Delete the to-do in Plane and the
        article became permanently unsendable -- the flag said "filed" forever, and only
        hand-editing intake_state.json could undo it.
        """
        if aid in state['verifying_ids'] or aid in state['sending_ids']:
            return
        issue_id = _wf(aid).get('plane_issue_id')
        if not issue_id:
            return
        # Captured before the refresh below tears down this handler's own slot -- same
        # mechanism as send_to_homelab, see capture_client()'s docstring.
        client = capture_client()
        state['verifying_ids'].add(aid)
        _refresh_send_control(aid)
        try:
            status = await run.io_bound(plane.issue_status, issue_id)
        finally:
            state['verifying_ids'].discard(aid)
        if status == 'gone':
            # Persist unconditionally, then patch in memory only if the tab is still
            # there -- mirrors send_to_homelab's split for the same reason.
            await run.io_bound(intake_state.set_article_state, aid, plane_issue_id=None)
            if client_alive(client):
                _apply_workflow_change(aid, plane_issue_id=None)
        if not client_alive(client):
            return
        _refresh_send_control(aid)
        if status == 'gone':
            notify_on(client, 'That to-do no longer exists in HomeLab — you can send again.',
                      type='warning')
        elif status == 'present':
            notify_on(client, 'Still filed in HomeLab.', type='positive')
        else:
            # Includes run.io_bound returning None on a cancelled call. Plane did not say
            # the to-do is gone, so nothing was cleared -- say that rather than implying
            # the checkmark was checked and stands.
            notify_on(client, 'Could not reach HomeLab — checkmark left as it is.', type='info')

    def _refresh_send_control(aid):
        """Repaints just the surfaces showing this article's send control. Nothing here
        changes filter membership or sort order, so the full-list rebuild that
        _refresh_after_workflow_change() exists to decide on is never needed."""
        _get_row_refreshable(aid).refresh()
        if state.get('selected') == aid:
            render_reader.refresh()

    # ---------- bulk actions ----------

    async def bulk_mark(read=None, favorite=None, archived=None):
        ids = list(state['selected_ids'])
        fields = {}
        if read is not None:
            fields['read'] = read
        if favorite is not None:
            fields['favorite'] = favorite
        if archived is not None:
            fields['archived'] = archived
        await run.io_bound(intake_state.bulk_set_article_state, ids, **fields)
        await reload_workflow()
        ui.notify(f'{len(ids)} article(s) updated', type='positive')

    async def bulk_move_to_folder():
        folder = await _prompt_folder_choice(state['folders'])
        if not folder:
            return
        ids = list(state['selected_ids'])
        if folder not in state['folders']:
            await run.io_bound(intake_state.create_folder, folder)
            folders = await run.io_bound(intake_state.list_folders)
            if folders is not None:
                state['folders'] = folders
        for aid in ids:
            await run.io_bound(intake.add_to_folder, aid, folder)
        await reload_articles()
        ui.notify(f'Moved {len(ids)} article(s) to "{folder}"', type='positive')

    async def bulk_delete():
        ids = list(state['selected_ids'])
        if not await confirm('Delete articles?', f'Permanently delete {len(ids)} article(s)?',
                              confirm_label='Delete', danger=True):
            return
        for aid in ids:
            await _delete_article_and_cleanup(aid)
        await reload_articles()

    # ---------- reader ----------

    async def move_focus(delta):
        ids = [a['id'] for a in filtered_articles()]
        if not ids:
            return
        cur = state.get('focused_id')
        idx = ids.index(cur) if cur in ids else -1
        new_idx = min(max(idx + delta, 0), len(ids) - 1)
        new_focused = ids[new_idx]
        state['focused_id'] = new_focused
        # Same single-row-refresh optimization as select_article() below -- j/k only
        # changes which row is highlighted, not filtered_articles()'s membership/order.
        if cur and cur != new_focused and cur in row_refreshables:
            _get_row_refreshable(cur).refresh()
        if new_focused in row_refreshables:
            _get_row_refreshable(new_focused).refresh()
        else:
            render_articles.refresh()
        if state.get('selected'):
            await select_article(new_focused)

    async def select_article(aid):
        # Captured *before* any row refresh below: refreshing the clicked row's own
        # target rebuilds it, and NiceGUI runs this whole handler (every await
        # included) inside the slot the click captured at dispatch time. Once this
        # function destroys its own originating slot, context.client stops resolving
        # for the rest of the handler -- load_article_content's client_alive() check
        # would silently see a RuntimeError-turned-False and skip populating the
        # reader forever, even though the browser tab never went anywhere. See
        # components/util.py's capture_client() docstring for the full mechanism.
        client = capture_client()
        prev_focused = state.get('focused_id')
        state['selected'] = aid
        state['article_content'] = None
        state['fulltext'] = {'status': 'idle', 'text': None}
        state['reader_mode'] = 'read'
        state['focused_id'] = aid
        # update_layout() only adjusts the (persistent) list/reader columns' own
        # width/visibility -- it never tears down the list itself, so scroll position
        # survives opening/closing/resizing the reader. Only the previously-focused
        # and newly-focused rows' highlight actually changes, so refresh just those
        # two instead of render_articles.refresh()'s full-list rebuild -- opening an
        # article doesn't change filtered_articles()'s membership/order, unlike
        # toggle_read/toggle_favorite/toggle_archived, so no fallback case is needed
        # here. (Chris, 2026-08-01: opening an article was taking 1s+ from exactly
        # this full-rebuild cost, on top of the actual content fetch below.)
        update_layout()
        if prev_focused and prev_focused != aid and prev_focused in row_refreshables:
            _get_row_refreshable(prev_focused).refresh()
        if aid in row_refreshables:
            _get_row_refreshable(aid).refresh()
        else:
            render_articles.refresh()
        render_reader.refresh()
        await load_article_content(aid, client)

    def close_reader():
        state['selected'] = None
        state['reader_size'] = 'normal'
        update_layout()
        render_reader.refresh()


    async def set_reader_mode(mode):
        state['reader_mode'] = mode
        if mode == 'discuss' and state['selected']:
            aid = state['selected']
            thread = await run.io_bound(intake_state.get_thread, aid)
            sources = await run.io_bound(intake_state.get_sources, aid)
            model = await run.io_bound(intake_state.get_model, aid)
            state['discuss']['thread'] = thread if thread is not None else []
            state['discuss']['model'] = model or intake_state.DEFAULT_MODEL
            active = {'article'}
            if sources is None or sources.get('archive', True):
                active.add('archive')
            if sources and sources.get('repos'):
                active.add('repo')
            state['discuss']['active_sources'] = active
            state['discuss']['repo_scope_open'] = False
            # Always ensure full width for Discuss regardless of the size it was at
            # before -- the original condition only widened from exactly 'normal', so
            # entering Discuss while already at 'wide' left both the article pane and
            # the chat squeezed into 860px with no expansion at all.
            if state['reader_size'] != 'full':
                state['reader_size'] = 'full'
                update_layout()
                render_reader.refresh()
                return
        render_reader.refresh()

    async def open_discuss(aid):
        await select_article(aid)
        await set_reader_mode('discuss')

    def cycle_reader_wider():
        # Two states, not three: 'normal' already fills all space left of the fixed
        # list column (see update_layout()), so a former middle 'wide' step would be
        # visually identical to 'normal' -- an expand button that appears to do
        # nothing. 'full' remains meaningfully different: it also hides the list.
        state['reader_size'] = 'full' if state['reader_size'] != 'full' else 'normal'
        update_layout()
        render_reader.refresh()

    def reset_reader_size():
        state['reader_size'] = 'normal'
        update_layout()
        render_reader.refresh()

    async def load_article_content(aid, client=None):
        data = await run.io_bound(intake.get_article, aid)
        if client_alive(client) and state.get('selected') == aid:
            state['article_content'] = data or {'content': '*Error loading article.*'}
            render_reader.refresh()
            await load_full_text(aid, client)

    async def load_full_text(aid, client=None):
        """Populates the reader's 'Full article' section: instant from cache when
        available, otherwise a network fetch of the source URL (first open of an
        article, or a retry). Every await can outlive the open article -- both the
        client and the still-selected check must pass before touching state."""
        art = next((a for a in state['articles'] if a['id'] == aid), None)
        if not art or not art.get('source'):
            return  # no source URL -> section renders its 'nothing to fetch' note
        cached = await run.io_bound(fulltext.get_cached, aid)
        if not client_alive(client) or state.get('selected') != aid:
            return
        if cached:
            state['fulltext'] = {'status': 'ready', 'text': cached}
            render_reader.refresh()
            return
        state['fulltext'] = {'status': 'loading', 'text': None}
        render_reader.refresh()
        text = await run.io_bound(fulltext.fetch_and_cache, aid, art['source'])
        if not client_alive(client) or state.get('selected') != aid:
            return
        state['fulltext'] = {'status': 'ready', 'text': text} if text else {'status': 'failed', 'text': None}
        render_reader.refresh()

    async def retry_full_text():
        # Captured here, not inside load_full_text: its render_reader.refresh() tears
        # down the Retry control's own slot mid-handler (capture_client() docstring).
        aid = state.get('selected')
        if aid:
            await load_full_text(aid, capture_client())

    async def _delete_article_and_cleanup(aid):
        """No-confirm delete primitive shared by every delete path (single, table-row,
        keyboard, bulk) -- only clears state['selected']/blanks the reader if the
        deleted article is the one actually open, so deleting an unrelated
        keyboard-focused or bulk-selected row never touches an untouched open reader."""
        await run.io_bound(intake.delete_article, aid)
        if state.get('selected') == aid:
            state['selected'] = None
            if client_alive():
                render_reader.refresh()
        if state.get('focused_id') == aid:
            state['focused_id'] = None
        state['selected_ids'].discard(aid)
        state['confirming_ids'].discard(aid)

    def request_delete(aid):
        """Single-row/keyboard delete confirmation is inline (the row's action column
        swaps to 'Delete? Yes/No') rather than a modal -- bulk delete keeps its modal
        (see bulk_delete()), since an inline per-row confirm doesn't make sense for a
        multi-row action."""
        state['confirming_ids'].add(aid)
        render_articles.refresh()
        if state.get('selected') == aid:
            render_reader.refresh()

    def cancel_delete(aid):
        state['confirming_ids'].discard(aid)
        render_articles.refresh()
        if state.get('selected') == aid:
            render_reader.refresh()

    async def confirm_delete(aid):
        await _delete_article_and_cleanup(aid)
        await reload_articles()

    async def mark_duplicate_row(aid):
        # Captured before reload_articles(), whose own render_articles.refresh() would
        # otherwise tear down this handler's originating row slot -- see
        # capture_client()'s docstring and select_article() above for the full mechanism.
        client = capture_client()
        await run.io_bound(intake.mark_duplicate, aid)
        await reload_articles()
        if state.get('selected') == aid:
            await load_article_content(aid, client)

    async def resubmit_row(aid):
        result = await run.io_bound(intake.resubmit_article, aid)
        if result is None:
            return
        if result.get('success'):
            ui.notify('Queued for resubmission', type='positive')
            await reload_queue()
        else:
            ui.notify(f"Resubmit failed: {result.get('error')}", type='negative')

    async def move_article_to_folder(aid):
        # Captured before reload_articles() tears down this handler's originating row slot,
        # which would otherwise swallow the toast below (capture_client()/notify_on()).
        client = capture_client()
        folder = await _prompt_folder_choice(state['folders'])
        if not folder:
            return
        if folder not in state['folders']:
            await run.io_bound(intake_state.create_folder, folder)
            folders = await run.io_bound(intake_state.list_folders)
            if folders is not None:
                state['folders'] = folders
        await run.io_bound(intake.add_to_folder, aid, folder)
        await reload_articles()
        notify_on(client, f'Moved to "{folder}"', type='positive')

    # ---------- Discuss ----------

    async def discuss_toggle_source(source):
        if source == 'article':
            return  # locked on, not a user choice
        active = state['discuss']['active_sources']
        if source in active:
            active.discard(source)
        else:
            active.add(source)
        if source == 'repo':
            state['discuss']['repo_scope_open'] = source in active
        render_reader.refresh()
        aid = state['selected']
        if not aid:
            return
        if source == 'archive':
            await run.io_bound(intake_state.set_sources, aid, archive=source in active)
        elif source == 'repo':
            await run.io_bound(intake_state.set_sources, aid,
                                repos=['homelab-infra'] if source in active else [])

    def discuss_close_repo_scope():
        state['discuss']['repo_scope_open'] = False
        render_reader.refresh()

    async def discuss_select_model(model):
        aid = state['selected']
        state['discuss']['model'] = model
        render_reader.refresh()
        # Persisted per article (Chris, 2026-08-04): each article's Discuss keeps its
        # own model pick, so switching articles never silently changes which model
        # answers. Persist AFTER the refresh -- refresh tears down this handler's
        # originating slot, and nothing below touches UI context, so order matters
        # only for snappiness.
        if aid:
            await run.io_bound(intake_state.set_model, aid, model)

    async def discuss_clear_thread():
        aid = state['selected']
        if not aid:
            return
        await run.io_bound(intake_state.clear_thread, aid)
        state['discuss']['thread'] = []
        state['thread_counts'].pop(aid, None)
        render_reader.refresh()
        render_articles.refresh()

    async def discuss_open_citation(aid):
        state['reader_mode'] = 'read'
        await select_article(aid)

    async def discuss_send(text):
        # Captured before the busy-spinner refresh below: the Discuss input lives
        # inside render_reader's subtree, so render_reader.refresh() tears down this
        # handler's originating slot and a bare client_alive() after the model call
        # would always read "disconnected" -- dropping the reply and leaving the
        # spinner stuck on "… is reading …" forever (hit live 2026-08-02; same
        # mechanism as select_article/send_to_homelab, see capture_client()).
        client = capture_client()
        text = (text or '').strip()
        if not text:
            return
        aid = state['selected']
        art = next((a for a in state['articles'] if a['id'] == aid), None)
        if not art:
            return
        user_msg = {'role': 'user', 'text': text}
        state['discuss']['thread'].append(user_msg)
        await run.io_bound(intake_state.append_message, aid, user_msg)
        state['thread_counts'][aid] = state['thread_counts'].get(aid, 0) + 1
        state['discuss']['busy'] = True
        render_reader.refresh()
        render_articles.refresh()

        history = [{'role': 'model' if m['role'] == 'assistant' else 'user', 'text': m['text']}
                   for m in state['discuss']['thread'][:-1]]
        active_sources = set(state['discuss']['active_sources'])
        model = state['discuss']['model']
        try:
            result = await run.io_bound(discuss.send_discuss_message, art, active_sources, text, history, model)
        except Exception as e:
            result = {'text': f'Error: {e}', 'tool_calls': []}
        state['discuss']['busy'] = False
        if result is None:
            return  # io_bound cancelled (shutdown/teardown) -- no reply to keep
        cites = [c for tc in result.get('tool_calls', []) for c in tc.get('cites', [])]
        assistant_msg = {'role': 'assistant', 'text': result.get('text', ''),
                          'tools': result.get('tool_calls', []), 'cites': cites}
        # Persist unconditionally (mirrors send_to_homelab): the reply was really
        # generated, so it must land in the on-disk thread even if the tab closed
        # mid-call -- reopening Discuss then shows it instead of losing it.
        await run.io_bound(intake_state.append_message, aid, assistant_msg)
        state['thread_counts'][aid] = state['thread_counts'].get(aid, 0) + 1
        if not client_alive(client):
            return
        if state['selected'] == aid:
            # Only the in-memory thread is per-open-article; if Chris switched
            # articles mid-reply, state['discuss'] already belongs to the new one --
            # appending there would leak the reply into the wrong thread.
            state['discuss']['thread'].append(assistant_msg)
        render_reader.refresh()
        render_articles.refresh()

    # ---------- keyboard ----------

    async def on_key(e):
        if not e.action.keydown:
            return
        key = e.key
        if key == '?':
            await _show_cheatsheet()
            return
        if key.escape:
            state['focused_id'] = None
            state['confirming_ids'] = set()
            render_articles.refresh()
            return

        ids = [a['id'] for a in filtered_articles()]
        if not ids:
            return
        cur = state.get('focused_id')

        if key == 'j' or key.is_cursorkey and key.code == 'ArrowDown':
            await move_focus(1)
        elif key == 'k' or key.is_cursorkey and key.code == 'ArrowUp':
            await move_focus(-1)
        elif key.enter:
            if cur:
                await select_article(cur)
        elif key == 'x':
            if cur:
                state['select_mode'] = True
                toggle_row_selected(cur)
        elif key == 'r':
            if cur:
                await toggle_read(cur)
        elif key == 'f':
            if cur:
                await toggle_favorite(cur)
        elif key == 'a':
            if cur:
                await toggle_archived(cur)
        elif key == 's':
            if cur:
                await send_to_homelab(cur)
        elif key.backspace or key == 'Delete':
            if cur:
                request_delete(cur)

    ui.keyboard(on_key=on_key, ignore=['input', 'select', 'button', 'textarea'])

    # ---------- reload / initial load ----------

    async def reload_articles():
        arts = await run.io_bound(intake.list_articles)
        if arts is None:
            return
        state['articles'] = arts
        state['articles_loaded'] = True
        vocab = await run.io_bound(intake.load_tag_vocabulary)
        if vocab is not None:
            state['tag_vocabulary'] = vocab
        if client_alive():
            render_folder_dropdown.refresh()
            render_tag_dropdown.refresh()
            render_header.refresh()
            render_articles.refresh()

    async def reload_queue():
        q = await run.io_bound(intake.get_queue)
        if q is None:
            return
        state['queue'] = q
        if client_alive():
            render_queue.refresh()
            render_header.refresh()

    async def _initial_load():
        workflow = await run.io_bound(intake_state.all_article_states)
        folders = await run.io_bound(intake_state.list_folders)
        prefs = await run.io_bound(intake_state.get_prefs)
        tcounts = await run.io_bound(intake_state.thread_counts)
        if workflow is not None:
            state['workflow'] = workflow
        if folders is not None:
            state['folders'] = folders
        if prefs is not None:
            state['prefs'] = prefs
        if tcounts is not None:
            state['thread_counts'] = tcounts
        await reload_articles()
        await reload_queue()

    # ---------- rendering: header ----------

    @ui.refreshable
    def render_header():
        arts = state['articles']
        live_n = len([a for a in arts if not _wf(a['id'])['archived']])
        unread_n = len([a for a in arts if not _wf(a['id'])['archived'] and not _wf(a['id'])['read']])
        archived_n = len([a for a in arts if _wf(a['id'])['archived']])
        queue_n = len([q for q in state['queue'] if q.get('status') in ('pending', 'processing', 'failed')])
        # Two rows, not one -- the list column can be as narrow as 380px (when the
        # reader is open), and title + full stats string + 4 buttons never fits on a
        # single no-wrap row at that width (confirmed live: it was wrapping mid-word
        # instead of laying out cleanly). Buttons are icon-only + tooltipped, same
        # convention as the row-action icons, so they stay compact regardless of width.
        with ui.column().style('width:100%;gap:4px;padding:14px 18px 0;min-width:0'):
            with ui.row().classes('items-center no-wrap').style('width:100%;gap:8px;min-width:0'):
                ui.label('Article Intake').style(
                    f'font-size:16px;font-weight:700;color:{theme.TEXT};flex:none;white-space:nowrap')
                ui.space()
                for icon, tip, handler in [
                    ('add_link', 'Add URL — not wired to a backend yet',
                     lambda: ui.notify('Add URL — not wired to a backend yet', type='info')),
                    ('play_arrow', 'Run intake — not wired to a backend yet',
                     lambda: ui.notify('Run intake — not wired to a backend yet', type='info')),
                    ('menu_book', 'Library — coming in a later phase',
                     lambda: ui.notify('Library window — coming in a later phase', type='info')),
                    ('question_mark', 'Keyboard shortcuts', lambda: _show_cheatsheet()),
                ]:
                    ui.button(icon=icon, on_click=handler).props('flat dense round').style(
                        f'color:{theme.TEXT_MUTED};flex:none').tooltip(tip)
            ui.label(
                f"{live_n} article{'s' if live_n != 1 else ''} · {unread_n} unread · "
                f"{archived_n} archived · queue {queue_n}"
            ).style(f'font-size:11.5px;color:{theme.TEXT_DIM};width:100%')

    # ---------- rendering: toolbar dropdowns ----------

    @ui.refreshable
    def render_folder_dropdown():
        counts = status_counts()
        custom_counts = custom_folder_counts()
        active_key = state['folder']
        if active_key.startswith('custom:'):
            active_label = active_key[len('custom:'):]
        else:
            active_label = next((label for k, _, label in STATUS_ENTRIES if k == active_key), 'All')

        with ui.row().classes('items-center no-wrap cursor-pointer').style(
                f'gap:7px;height:32px;padding:0 11px;border-radius:8px;background:{theme.CARD_BG};'
                f'border:1px solid rgba(255,255,255,0.09);color:{theme.TEXT};font-size:11.5px;font-weight:600'):
            ui.icon('fa-solid fa-folder-open').style(f'font-size:10px;color:{theme.TEXT_MUTED}')
            ui.label(active_label)
            ui.icon('fa-solid fa-chevron-down').style(f'font-size:8px;color:{theme.TEXT_DIM}')
            with ui.menu() as menu:
                with ui.column().style('gap:1px;padding:6px;min-width:200px'):
                    for key, icon, label in STATUS_ENTRIES:
                        active = key == active_key
                        with ui.row().classes('items-center no-wrap cursor-pointer').style(
                                f'gap:8px;padding:7px 9px;border-radius:6px;width:100%;'
                                f'background:{theme.ACCENT_TINT if active else "transparent"}'
                        ).on('click', lambda _, k=key, m=menu: (select_folder(k), m.close())).mark(f'folder-{key}'):
                            ui.icon(icon).style(
                                f'font-size:11px;width:14px;color:{theme.ACCENT if active else theme.TEXT_MUTED}')
                            ui.label(label).style(
                                f'flex:1;font-size:12px;color:{theme.TEXT if active else theme.TEXT_MUTED}')
                            ui.label(str(counts.get(key, 0))).style(f'font-size:10.5px;color:{theme.TEXT_DIM}')
                    if state['folders']:
                        ui.element('div').style('height:1px;background:rgba(255,255,255,0.06);margin:6px 2px')
                        ui.label('MY FOLDERS').style(
                            f'font-size:9px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};'
                            f'padding:4px 9px')
                        for name in state['folders']:
                            key = f'custom:{name}'
                            active = key == active_key
                            with ui.row().classes('items-center no-wrap cursor-pointer').style(
                                    f'gap:8px;padding:7px 9px;border-radius:6px;width:100%;'
                                    f'background:{theme.ACCENT_TINT if active else "transparent"}'
                            ).on('click', lambda _, k=key, m=menu: (select_folder(k), m.close())):
                                ui.icon('fa-solid fa-folder').style(
                                    f'font-size:11px;width:14px;color:{theme.PURPLE if active else theme.TEXT_MUTED}')
                                ui.label(name).style(
                                    f'flex:1;font-size:12px;color:{theme.TEXT if active else theme.TEXT_MUTED};'
                                    f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                                ui.label(str(custom_counts.get(name, 0))).style(
                                    f'font-size:10.5px;color:{theme.TEXT_DIM}')
                    ui.element('div').style('height:1px;background:rgba(255,255,255,0.06);margin:6px 2px')
                    with ui.row().classes('items-center no-wrap cursor-pointer').style(
                            f'gap:8px;padding:7px 9px;border-radius:6px;width:100%'
                    ).on('click', lambda _, m=menu: (create_new_folder(), m.close())):
                        ui.icon('fa-solid fa-plus').style(f'font-size:10px;color:{theme.ACCENT}')
                        ui.label('New folder').style(f'font-size:12px;color:{theme.ACCENT}')

    @ui.refreshable
    def render_tag_dropdown():
        tag_row_elements.clear()
        tags = available_tags()
        n_selected = len(state['tag_filters'])
        with ui.row().classes('items-center no-wrap cursor-pointer').style(
                f'gap:7px;height:32px;padding:0 11px;border-radius:8px;'
                f'background:{theme.ACCENT_TINT if n_selected else theme.CARD_BG};'
                f'border:1px solid {"rgba(165,180,252,0.35)" if n_selected else "rgba(255,255,255,0.09)"};'
                f'color:{theme.ACCENT if n_selected else theme.TEXT};font-size:11.5px;font-weight:600'):
            ui.icon('fa-solid fa-tags').style(f'font-size:10px')
            ui.label(f'Tags{f" ({n_selected})" if n_selected else ""}')
            ui.icon('fa-solid fa-chevron-down').style('font-size:8px')
            with ui.menu().props('persistent'):
                with ui.column().style('gap:6px;padding:8px;min-width:220px'):
                    with ui.row().classes('items-center no-wrap').style(
                            'gap:6px;background:#242435;border:1px solid rgba(255,255,255,0.07);'
                            'border-radius:6px;padding:5px 8px'):
                        ui.icon('fa-solid fa-magnifying-glass').style(f'font-size:9px;color:{theme.TEXT_DIM}')
                        ui.input(placeholder='Filter tags…', value=state['tag_search'],
                                  on_change=on_tag_search).props('borderless dense').style(
                            f'flex:1;color:{theme.TEXT};font-size:11px')
                    if n_selected:
                        ui.label(f'clear {n_selected}').classes('cursor-pointer').style(
                            f'font-size:9.5px;font-weight:600;color:{theme.ACCENT}').on('click', lambda: clear_tags())
                    if not tags:
                        ui.label('No tags match.').style(f'font-size:11px;color:{theme.TEXT_DIM};padding:6px 2px')
                    with ui.column().classes('nq-custom-scroll').style('gap:1px;max-height:260px;overflow:auto'):
                        for tag, count in tags:
                            active = tag in state['tag_filters']
                            row = ui.row().classes('items-center no-wrap cursor-pointer').style(
                                    f'gap:8px;padding:5px 8px;border-radius:6px;'
                                    f'background:{theme.ACCENT_TINT if active else "transparent"}'
                            ).on('click', lambda _, t=tag: select_tag(t))
                            with row:
                                ui.icon('fa-solid fa-check').style(
                                    f'font-size:9px;color:{theme.ACCENT if active else "transparent"};width:12px')
                                label = ui.label(tag).style(
                                    f'flex:1;font-size:12px;color:{theme.ACCENT if active else theme.TEXT_MUTED};'
                                    f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                                ui.label(str(count)).style(f'font-size:10px;color:{theme.TEXT_DIM}')
                            tag_row_elements[tag] = (row, label)

    @ui.refreshable
    def render_filter_chips():
        chips = []
        if state['folder'] != 'all':
            chips.append(('folder', 'fa-solid fa-folder', None))
        for tag in sorted(state['tag_filters']):
            chips.append(('tag', tag, tag))
        if state['search']:
            chips.append(('search', f'"{state["search"]}"', None))
        if not chips:
            return
        with ui.row().classes('items-center no-wrap').style('gap:6px;flex-wrap:wrap;width:100%'):
            for kind, label, tag_value in chips:
                with ui.row().classes('items-center no-wrap').style(
                        f'gap:5px;padding:3px 4px 3px 9px;border-radius:12px;background:{theme.CARD_BG};'
                        f'border:1px solid rgba(255,255,255,0.08)'):
                    ui.label(label if kind != 'tag' else label).style(f'font-size:10.5px;color:{theme.TEXT_MUTED}')
                    if kind == 'tag':
                        ui.icon('fa-solid fa-xmark').classes('cursor-pointer').style(
                            f'font-size:9px;color:{theme.TEXT_DIM};padding:2px').on(
                            'click', lambda _, t=tag_value: select_tag(t))
                    elif kind == 'folder':
                        ui.icon('fa-solid fa-xmark').classes('cursor-pointer').style(
                            f'font-size:9px;color:{theme.TEXT_DIM};padding:2px').on(
                            'click', lambda: select_folder('all'))
                    elif kind == 'search':
                        ui.icon('fa-solid fa-xmark').classes('cursor-pointer').style(
                            f'font-size:9px;color:{theme.TEXT_DIM};padding:2px').on(
                            'click', lambda: clear_search())
            ui.label('Clear all').classes('cursor-pointer').style(
                f'font-size:10.5px;font-weight:600;color:{theme.ACCENT}').on('click', lambda: clear_all_filters())

    def clear_all_filters():
        state['folder'] = 'all'
        state['tag_filters'] = set()
        state['search'] = ''
        render_folder_dropdown.refresh()
        render_tag_dropdown.refresh()
        render_articles.refresh()
        render_header.refresh()
        render_filter_chips.refresh()

    def render_toolbar():
        # Two rows, same reasoning as render_header(): folder dropdown + tag dropdown
        # moved in from the old rail, so this toolbar now has more controls than fit
        # on one no-wrap row at 380px (confirmed live -- density icons and the Select
        # button were wrapping/overlapping unpredictably). Search gets its own full-
        # width row; everything else goes on a second row that also wraps as a safety
        # net if it's ever squeezed narrower than this.
        with ui.column().style(f'gap:8px;padding:10px 14px;border-bottom:1px solid {theme.BORDER};'
                                f'width:100%;min-width:0'):
            with ui.row().classes('items-center no-wrap').style(
                    f'width:100%;min-width:0;gap:8px;background:{theme.CARD_BG};'
                    f'border:1px solid rgba(255,255,255,0.07);border-radius:7px;padding:6px 10px'):
                ui.icon('fa-solid fa-magnifying-glass').style(f'font-size:11px;color:{theme.TEXT_DIM};flex:none')
                ui_refs['search_input'] = ui.input(
                    placeholder='Search title, snippet, tags, full text…', value=state['search'],
                    on_change=on_search).props('borderless dense').style(
                    f'flex:1;min-width:0;color:{theme.TEXT};font-size:12px')
            with ui.row().classes('items-center').style('gap:9px;width:100%;flex-wrap:wrap'):
                render_folder_dropdown()
                render_tag_dropdown()
                ui.select(options=dict(SORT_OPTIONS), value=state['prefs']['sort'],
                          on_change=lambda e: set_sort(e.value)).props('dense outlined').style('font-size:11.5px')
                with ui.row().style(f'gap:2px;background:{theme.CARD_BG};border-radius:7px;padding:2px;flex:none'):
                    for key, icon in [('cozy', 'fa-solid fa-grip-lines'), ('compact', 'fa-solid fa-bars')]:
                        active = state['prefs']['density'] == key
                        with ui.element('div').classes('cursor-pointer').style(
                                f'width:28px;height:28px;border-radius:5px;display:flex;align-items:center;'
                                f'justify-content:center;background:{theme.ACCENT_TINT if active else "transparent"};'
                                f'color:{theme.ACCENT if active else theme.TEXT_MUTED}'
                        ).on('click', lambda _, k=key: set_density(k)).mark(f'density-toggle-{key}').tooltip(
                                'Cozy — shows a snippet under each title' if key == 'cozy' else
                                'Compact — titles only, more rows on screen'):
                            ui.icon(icon).style('font-size:12px')
                select_btn_active = state['select_mode']
                ui.button('Select', on_click=toggle_select_mode).props(
                    'dense outline' if not select_btn_active else 'dense').style(
                    f'font-size:11.5px;flex:none;'
                    + (f'background:{theme.ACCENT};color:{theme.BG}' if select_btn_active else f'color:{theme.TEXT_MUTED}'))
            render_filter_chips()
            render_bulk_bar()

    # ---------- rendering: article list (density-aware rows) ----------

    def _get_row_refreshable(aid):
        """Lazily creates (and caches) a @ui.refreshable closure for one article's row.
        Each call to ui.refreshable() on a distinct function object gets its own
        independent refresh target, so calling .refresh() on this row's target later
        only tears down and rebuilds that one row -- not render_articles()'s whole
        list. Reads density/article content fresh on every call (including on
        .refresh()), so it always reflects current state rather than whatever was
        true when the closure was first created."""
        target = row_refreshables.get(aid)
        if target is None:
            @ui.refreshable
            def _row():
                art = next((x for x in state['articles'] if x['id'] == aid), None)
                if art is not None:
                    _render_row(art, state['prefs']['density'] == 'compact')
            target = _row
            row_refreshables[aid] = target
        return target

    @ui.refreshable
    def render_articles():
        if not state['articles_loaded']:
            with ui.column().classes('items-center justify-center').style('gap:10px;width:100%;padding:8px 0'):
                for _ in range(6):
                    ui.element('div').classes('nq-skel').style(
                        f'height:52px;border-radius:9px;background:rgba(255,255,255,0.04);width:100%')
            return

        arts = filtered_articles()
        if not arts:
            if state['tag_filters']:
                msg = f"No articles carry all {len(state['tag_filters'])} selected tags."
            elif state['search']:
                msg = f'No articles match "{state["search"]}"'
            elif state['folder'] == 'education':
                # Distinguishes "nothing is educational" from "nothing has been classified
                # yet" -- the latter is the expected state until the backfill has run, and a
                # bare "No articles found." would read as the former.
                msg = ('No articles are marked educational yet. Articles processed before '
                       'this view existed need scripts/backfill_educational.py to be run '
                       'over them first.')
            else:
                msg = 'No articles found.'
            with ui.column().classes('items-center justify-center').style('width:100%;padding:24px 12px;gap:8px'):
                ui.label(msg).style(f'text-align:center;color:{theme.TEXT_DIM};font-size:12.5px')
                if state['tag_filters'] or state['search'] or state['folder'] != 'all':
                    ui.label('Clear filters').classes('cursor-pointer').style(
                        f'font-size:11.5px;font-weight:600;color:{theme.ACCENT}').on(
                        'click', lambda: clear_all_filters())
            return

        if state['folder'] == 'education':
            _render_grouped_by_subtopic(arts)
            return

        for a in arts:
            _get_row_refreshable(a['id'])()

    def _render_grouped_by_subtopic(arts):
        """Education is a browse-by-subject view, not a triage queue -- flat reverse-chron
        buries the one Kubernetes guide under thirty AI ones. Groups preserve whatever sort
        the user picked *within* each sub-topic; only the grouping is imposed.

        Headers are emitted by render_articles (not by the per-row refreshables), so a
        single-row refresh never touches them. That's safe because any change that moves an
        article between groups also changes filtered_articles()' id list, which
        _refresh_after_workflow_change() already detects and answers with a full rebuild."""
        # Frequencies come from the WHOLE archive, not just the educational subset, so a
        # sub-topic heading means the same thing here as the tag does everywhere else.
        freqs = _tag_frequencies(state['articles'])
        for subtopic, items in _group_by_subtopic(arts, freqs):
            with ui.row().classes('items-center no-wrap').style(
                    'width:100%;gap:8px;padding:14px 2px 5px'):
                ui.label(subtopic.upper()).style(
                    f'font-size:9.5px;font-weight:700;letter-spacing:0.6px;color:{theme.TEXT_DIM};'
                    f'flex:none;white-space:nowrap')
                ui.element('div').style(
                    'flex:1;height:1px;background:rgba(255,255,255,0.06);min-width:0')
                ui.label(str(len(items))).style(
                    f'font-size:9.5px;font-weight:600;color:{theme.TEXT_DIM};flex:none')
            for a in items:
                _get_row_refreshable(a['id'])()

    def _render_row(a: dict, compact: bool):
        aid = a['id']
        wf = _wf(aid)
        badge_text, badge_color = _badge(a)
        is_focused = state.get('focused_id') == aid
        is_selected = aid in state['selected_ids']
        title_color = theme.TEXT if not wf['read'] else theme.TEXT_MUTED
        title_weight = 700 if not wf['read'] else 500
        with ui.row().classes('no-wrap items-center').style(
                f'padding:{"6px 10px" if compact else "10px"};border-radius:9px;gap:8px;width:100%;'
                f'background:{theme.ACCENT_TINT if is_focused else "transparent"};'
                f'border-left:2px solid {theme.ACCENT if not wf["read"] else "transparent"}'):
            if state['select_mode']:
                with ui.element('div').classes('cursor-pointer').style(
                        f'width:16px;height:16px;border-radius:4px;flex:none;margin-top:2px;'
                        f'border:1.5px solid {theme.ACCENT if is_selected else "rgba(255,255,255,0.2)"};'
                        f'background:{theme.ACCENT if is_selected else "transparent"};display:flex;'
                        f'align-items:center;justify-content:center'
                ).on('click', lambda _, i=aid: toggle_row_selected(i)):
                    if is_selected:
                        ui.icon('fa-solid fa-check').style(f'font-size:9px;color:{theme.BG}')

            with ui.column().classes('cursor-pointer').style(
                    'gap:4px;flex:1;min-width:0'
            ).on('click', lambda _, i=aid: select_article(i)).mark(f'article-row-{aid}'):
                with ui.row().classes('items-center no-wrap').style('gap:8px;width:100%'):
                    if not compact:
                        ui.label(badge_text).style(
                            f'font-size:9.5px;font-weight:700;padding:2px 7px;border-radius:10px;color:{badge_color};'
                            f'background:rgba(255,255,255,0.05)')
                    if (a.get('priority_score') or 0) >= 7.5:
                        with ui.row().classes('items-center no-wrap').style(f'gap:3px;color:{theme.AMBER}'):
                            ui.icon('fa-solid fa-bolt').style('font-size:8px')
                            ui.label(f"P{a['priority_score']}").style('font-size:9.5px;font-weight:700')
                    if wf['favorite']:
                        ui.icon('fa-solid fa-star').style(f'font-size:9px;color:{theme.AMBER}')
                    if wf['archived']:
                        ui.label('ARCHIVED').style(
                            f'font-size:8.5px;font-weight:700;color:{theme.TEXT_DIM};'
                            f'background:rgba(255,255,255,0.05);border-radius:8px;padding:1px 6px')
                    n_msgs = state['thread_counts'].get(aid, 0)
                    if n_msgs:
                        with ui.row().classes('items-center no-wrap').style(f'gap:3px;color:{theme.TEXT_DIM}'):
                            ui.icon('fa-regular fa-comment').style('font-size:9px')
                            ui.label(str(n_msgs)).style('font-size:9.5px;font-weight:600')
                    ui.space()
                    ui.label(f"{a.get('reading_minutes', 1)} min").style(f'font-size:10px;color:{theme.TEXT_DIM}')
                    ui.label(a['date']).style(f'font-size:10.5px;color:{theme.TEXT_DIM}')
                ui.label(a['title']).style(
                    f'font-size:13.5px;font-weight:{title_weight};color:{title_color};overflow:hidden;'
                    f'text-overflow:ellipsis;white-space:nowrap;width:100%;display:block')
                if not compact:
                    with ui.row().classes('items-center no-wrap').style('gap:6px'):
                        ui.icon('fa-solid fa-link').style(f'font-size:9px;color:{theme.TEXT_MUTED}')
                        ui.label(_short_url(a['source']) if a['source'] else 'Unknown source').style(
                            f'font-size:10.5px;color:{theme.TEXT_MUTED}')
                    if a['snippet']:
                        ui.label(a['snippet']).style(
                            f'font-size:11.5px;color:{theme.ACCENT};opacity:0.85;width:100%;display:block;'
                            f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                    with ui.row().style('gap:4px;flex-wrap:wrap'):
                        for tag in a['tags'][:3]:
                            ui.label(tag).style(
                                f'font-size:9.5px;color:{theme.TEXT_MUTED};background:rgba(255,255,255,0.05);'
                                f'border-radius:8px;padding:1px 7px')
                        for folder in a.get('user_folders', [])[:2]:
                            ui.label(folder).style(
                                f'font-size:9.5px;color:{theme.PURPLE};background:rgba(203,166,247,0.1);'
                                f'border-radius:8px;padding:1px 7px')

                _render_row_actions(aid, wf)

    def _render_row_actions(aid: str, wf: dict):
        # Sits inside the same clickable column as the title/snippet now (moved out of
        # the old side-by-side layout, which fixed 178px of action icons ate roughly
        # half the row width on a narrower list pane -- Chris, 2026-08-01). 'click.stop'
        # (a Quasar/Vue event modifier NiceGUI passes straight through to the frontend,
        # see element.on()'s docstring) keeps a click on any icon/button here from also
        # bubbling up to the column's own on('click', select_article) and opening the
        # reader -- it only needs to be attached once at this wrapping row's level;
        # each icon's own listener already fires on the target before bubbling starts.
        if aid in state['confirming_ids']:
            with ui.row().classes('items-center no-wrap').style(
                    'gap:6px;width:100%;margin-top:2px'
            ).on('click.stop', js_handler='() => {}'):
                ui.label('Delete?').style(f'font-size:11.5px;color:{theme.RED};font-weight:600')
                ui.button('Yes', on_click=lambda: confirm_delete(aid)).props('flat dense').style(
                    f'color:{theme.RED};font-size:11px;min-width:0;padding:2px 8px')
                ui.button('No', on_click=lambda: cancel_delete(aid)).props('flat dense').style(
                    f'color:{theme.TEXT_MUTED};font-size:11px;min-width:0;padding:2px 8px')
            return

        with ui.row().classes('items-center no-wrap').style(
                'gap:2px;width:100%;margin-top:2px'
        ).on('click.stop', js_handler='() => {}'):
            for icon, tip, is_on, color, handler, mark_name in [
                ('fa-solid fa-circle-check' if wf['read'] else 'fa-regular fa-circle', 'Read/unread',
                 wf['read'], theme.GREEN, lambda _, i=aid: toggle_read(i), 'r'),
                ('fa-solid fa-star' if wf['favorite'] else 'fa-regular fa-star', 'Favorite',
                 wf['favorite'], theme.AMBER, lambda _, i=aid: toggle_favorite(i), 'f'),
                ('fa-solid fa-box-archive', 'Archive/unarchive', wf['archived'], theme.ACCENT,
                 lambda _, i=aid: toggle_archived(i), 'a'),
            ]:
                with ui.element('div').classes('cursor-pointer').style(
                        'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;'
                        'justify-content:center'
                ).on('click', handler).mark(f'row-{mark_name}-{aid}').tooltip(tip):
                    ui.icon(icon).style(f'font-size:12.5px;color:{color if is_on else theme.TEXT_DIM}')

            if aid in state['sending_ids']:
                with ui.element('div').style(
                        'width:28px;height:28px;display:flex;align-items:center;justify-content:center'
                ).mark(f'sending-{aid}'):
                    ui.spinner(size='xs').style(f'color:{theme.PURPLE}')
            elif aid in state['verifying_ids']:
                with ui.element('div').style(
                        'width:28px;height:28px;display:flex;align-items:center;justify-content:center'
                ).mark(f'verifying-{aid}'):
                    ui.spinner(size='xs').style(f'color:{theme.GREEN}')
            elif wf.get('plane_issue_id'):
                # Still not a resend -- that would duplicate the to-do rather than update
                # it. Clicking re-checks Plane instead, which is the only way back if the
                # to-do was deleted there (see verify_plane_todo()).
                with ui.element('div').classes('cursor-pointer').style(
                        'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;'
                        'justify-content:center'
                ).on('click', lambda _, i=aid: verify_plane_todo(i)).mark(
                        f'sent-icon-{aid}').tooltip('Sent to HomeLab — click to re-check it still exists'):
                    ui.icon('fa-solid fa-check').style(f'font-size:12.5px;color:{theme.GREEN}')
            else:
                with ui.element('div').classes('cursor-pointer').style(
                        'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;justify-content:center'
                ).on('click', lambda _, i=aid: send_to_homelab(i)).mark(f'send-icon-{aid}').tooltip('Send to HomeLab'):
                    ui.icon('fa-solid fa-arrow-up-from-bracket').style(f'font-size:12.5px;color:{theme.PURPLE}')

            with ui.element('div').classes('cursor-pointer').style(
                    'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;justify-content:center'
            ).on('click', lambda _, i=aid: request_delete(i)).mark(f'delete-icon-{aid}').tooltip('Delete'):
                ui.icon('fa-solid fa-trash').style(f'font-size:12.5px;color:{theme.RED}')

            with ui.element('div').classes('cursor-pointer').style(
                    'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;justify-content:center'
            ).tooltip('More actions'):
                ui.icon('fa-solid fa-ellipsis').style(f'font-size:13px;color:{theme.TEXT_DIM}')
                with ui.menu():
                    art = next((x for x in state['articles'] if x['id'] == aid), None)
                    if art and art.get('source'):
                        ui.menu_item('Open original', on_click=lambda u=art['source']: ui.navigate.to(u, new_tab=True))
                    ui.menu_item('Discuss with AI', on_click=lambda i=aid: open_discuss(i))
                    ui.menu_item('Move to folder', on_click=lambda i=aid: move_article_to_folder(i))
                    ui.menu_item(
                        'Clear duplicate flag' if art and art.get('is_duplicate') else 'Flag as duplicate',
                        on_click=lambda i=aid: mark_duplicate_row(i))
                    ui.menu_item('Resubmit', on_click=lambda i=aid: resubmit_row(i))

    # ---------- rendering: bulk bar ----------

    @ui.refreshable
    def render_bulk_bar():
        if not state['select_mode'] or not state['selected_ids']:
            return
        n = len(state['selected_ids'])
        with ui.row().classes('items-center no-wrap').style(
                f'gap:10px;background:{theme.ACCENT_TINT};border:1px solid rgba(165,180,252,0.3);'
                f'border-radius:9px;padding:8px 12px;width:100%;flex-wrap:wrap'):
            ui.label(f'{n} selected').style(f'font-size:12px;font-weight:600;color:{theme.ACCENT}')
            ui.space()
            ui.button('Mark read', on_click=lambda: bulk_mark(read=True)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.TEXT}')
            ui.button('Mark unread', on_click=lambda: bulk_mark(read=False)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.TEXT}')
            ui.button('Favorite', on_click=lambda: bulk_mark(favorite=True)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.AMBER}')
            ui.button('Archive', on_click=lambda: bulk_mark(archived=True)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.ACCENT}')
            ui.button('Unarchive', on_click=lambda: bulk_mark(archived=False)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.ACCENT}')
            ui.button('Move to folder', on_click=lambda: bulk_move_to_folder()).props('flat dense').style(
                f'font-size:11.5px;color:{theme.PURPLE}')
            ui.button('Delete', on_click=lambda: bulk_delete()).props('flat dense').style(
                f'font-size:11.5px;color:{theme.RED}')
            ui.button('Clear', on_click=clear_selection).props('flat dense').style(
                f'font-size:11.5px;color:{theme.TEXT_MUTED}')

    # ---------- rendering: queue ----------

    @ui.refreshable
    def render_queue():
        failed = [q for q in state['queue'] if q.get('status') == 'failed']
        active = [q for q in state['queue'] if q.get('status') in ('pending', 'processing')]
        if failed:
            with ui.row().classes('items-center no-wrap').style('width:100%;padding:2px 4px 6px'):
                ui.label('FAILED · CLICK FOR DETAILS').style(
                    f'font-size:10.5px;font-weight:700;color:{theme.RED};flex:1')
                ui.label('Retry all').classes('cursor-pointer').style(
                    f'font-size:10px;font-weight:600;color:{theme.RED}').on('click', lambda: retry_all_failed())
            for item in failed:
                with ui.column().classes('cursor-pointer').style(
                        'padding:10px;border-radius:9px;margin-bottom:6px;background:rgba(243,139,168,0.07);'
                        'border:1px solid rgba(243,139,168,0.25);gap:4px;width:100%'
                ).on('click', lambda _, i=item: show_queue_error(i)).mark(f"queue-failed-{item['id']}"):
                    ui.label(_short_url(item['url'])).style(
                        f'font-size:11.5px;font-weight:600;color:{theme.RED}')
                    ui.label(item.get('last_error', 'Failed after retries')).style(
                        f'font-size:10px;color:{theme.TEXT_MUTED};overflow:hidden;text-overflow:ellipsis;'
                        f'white-space:nowrap')
        for item in active:
            is_retry = item.get('status') == 'pending' and item.get('retry_count', 0) > 0
            status_label = f"RETRY {item.get('retry_count')}/3" if is_retry else item['status'].upper()
            with ui.column().style(
                    'padding:10px;border-radius:9px;margin-bottom:4px;background:rgba(249,201,124,0.06);'
                    'gap:6px;width:100%'):
                with ui.row().classes('items-center no-wrap').style('gap:8px;width:100%'):
                    ui.element('div').style(
                        f'width:6px;height:6px;border-radius:50%;background:{theme.AMBER}')
                    ui.label(_short_url(item['url'])).style(
                        f'flex:1;font-size:11.5px;font-weight:600;color:{theme.AMBER};overflow:hidden;'
                        f'text-overflow:ellipsis;white-space:nowrap')
                    ui.label(status_label).style(f'font-size:9.5px;font-weight:700;color:{theme.AMBER}')

    def show_queue_error(item: dict):
        """The error used to exist only as a hover tooltip, and clicking the entry
        retried it -- so the one thing you could not do with a failure was read it.
        (Chris, 2026-08-04.) Retry still lives here, one click further in."""
        error_text = item.get('last_error') or 'Failed after retries (no error recorded).'
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:12px;padding:20px;min-width:620px;max-width:820px'):
            with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                ui.icon('fa-solid fa-circle-exclamation').style(f'color:{theme.RED};font-size:14px')
                ui.label('Queue item failed').style(
                    f'font-size:14px;font-weight:700;color:{theme.TEXT}')
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')

            with ui.row().classes('items-center').style('gap:18px;margin:2px 0 10px;flex-wrap:wrap'):
                for label, value in [('ATTEMPTS', f"{item.get('retry_count', 0)}/3"),
                                      ('ADDED', str(item.get('added_at') or '—'))]:
                    with ui.column().style('gap:2px'):
                        ui.label(label).style(
                            f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                        ui.label(value).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')

            ui.label('URL').style(
                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
            ui.label(item.get('url', '')).style(
                f"width:100%;font-family:'JetBrains Mono',monospace;font-size:11px;"
                f"color:{theme.TEXT_MUTED};user-select:text;word-break:break-all;margin-bottom:8px")

            ui.label('ERROR').style(
                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
            ui.label(error_text).style(
                f"width:100%;background:rgba(0,0,0,0.28);border-radius:8px;padding:12px 14px;"
                f"font-family:'JetBrains Mono',monospace;font-size:11.5px;color:{theme.TEXT};"
                f"line-height:1.6;white-space:pre-wrap;word-break:break-word;user-select:text;"
                f"max-height:260px;overflow:auto")

            async def _retry_and_close():
                dialog.close()
                await retry_item(item['id'])

            with ui.row().classes('justify-end w-full').style('gap:10px;margin-top:14px'):
                def _copy_error():
                    ui.clipboard.write(error_text)
                    ui.notify('Copied', type='positive')
                ui.button('Copy error', on_click=_copy_error).props('flat dense').mark(
                    'queue-copy-error').style(f'color:{theme.ACCENT};font-size:11.5px')
                ui.button('Retry', on_click=_retry_and_close).props('dense').mark(
                    'queue-retry').style(
                    f'background:{theme.ACCENT};color:{theme.BG};font-weight:700;font-size:11.5px')
        dialog.open()

    async def retry_item(item_id):
        await run.io_bound(intake.retry_queue_item, item_id)
        await reload_queue()

    async def retry_all_failed():
        for item in [q for q in state['queue'] if q.get('status') == 'failed']:
            await run.io_bound(intake.retry_queue_item, item['id'])
        await reload_queue()

    # ---------- rendering: tag editor ----------

    async def _after_tag_change(aid):
        """Tags feed the tag dropdown, the Education view's sub-topic grouping, and tag
        filtering, so a change has to reload the article list rather than just repaint the
        chips. reload_articles() already refreshes those surfaces and guards a dead client."""
        await reload_articles()
        if client_alive():
            render_tag_editor.refresh()

    async def add_tag_to_article(aid, tag, promote=False):
        tag = (tag or '').strip()
        if not tag:
            return
        if promote:
            # Accepting a suggestion is the approval step the vocabulary was missing: it
            # teaches the pipeline to auto-apply this tag on future articles instead of
            # re-proposing it every time.
            await run.io_bound(intake.promote_tag, tag)
        ok = await run.io_bound(intake.add_tag, aid, tag)
        if ok is None:
            return
        await _after_tag_change(aid)

    async def remove_tag_from_article(aid, tag):
        if await run.io_bound(intake.remove_tag, aid, tag) is None:
            return
        await _after_tag_change(aid)

    async def dismiss_suggestion(aid, tag):
        if await run.io_bound(intake.dismiss_suggested_tag, aid, tag) is None:
            return
        await _after_tag_change(aid)

    @ui.refreshable
    def render_tag_editor(art: dict):
        aid = art['id']
        # Read tags from state rather than the `art` dict passed in: `art` is a snapshot
        # captured when the reader rendered, so after an add/remove it is stale.
        current = next((a for a in state['articles'] if a['id'] == aid), art)
        tags = current.get('tags') or []
        suggested = current.get('suggested_tags') or []

        with ui.column().style('gap:7px;margin-bottom:16px;width:100%;max-width:640px'):
            with ui.row().classes('items-center').style('gap:6px;flex-wrap:wrap;width:100%'):
                for t in tags:
                    with ui.row().classes('items-center no-wrap').style(
                            f'gap:5px;padding:3px 6px 3px 9px;border-radius:11px;'
                            f'background:{theme.ACCENT_TINT};border:1px solid rgba(255,255,255,0.09)'):
                        ui.label(t).style(f'font-size:11px;font-weight:600;color:{theme.TEXT}')
                        with ui.element('div').classes('cursor-pointer').style(
                                'display:flex;align-items:center;justify-content:center;'
                                'width:13px;height:13px;border-radius:50%'
                        ).on('click', lambda _, i=aid, tg=t: remove_tag_from_article(i, tg)
                             ).mark(f'tag-remove-{t}').tooltip(f'Remove "{t}"'):
                            ui.icon('fa-solid fa-xmark').style(
                                f'font-size:9px;color:{theme.TEXT_DIM}')
                if not tags:
                    ui.label('No tags yet').style(f'font-size:11px;color:{theme.TEXT_DIM}')

            vocab = state.get('tag_vocabulary') or []
            # Existing tags on the article are dropped from the options so the box only ever
            # offers something that would actually change the article.
            options = [v for v in vocab if v not in tags]
            tag_input = ui.select(
                options=options, with_input=True, new_value_mode='add-unique',
                label='Search tags, or type a new one',
            ).props('dense outlined use-input hide-selected fill-input input-debounce=0').style(
                'width:100%;max-width:320px;font-size:12px').mark('tag-input')

            async def _submit(e):
                value = (e.value or '').strip() if hasattr(e, 'value') else ''
                if not value:
                    return
                tag_input.set_value(None)
                # A value that isn't already in the vocabulary is a new tag, so accepting it
                # here promotes it -- typing a tag by hand IS the approval.
                await add_tag_to_article(aid, value, promote=value not in vocab)

            tag_input.on_value_change(_submit)

            if suggested:
                with ui.row().classes('items-center').style('gap:6px;flex-wrap:wrap;width:100%'):
                    ui.label('SUGGESTED').style(
                        f'font-size:9px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM}')
                    for t in suggested:
                        with ui.row().classes('items-center no-wrap').style(
                                'gap:5px;padding:3px 6px 3px 9px;border-radius:11px;'
                                'background:rgba(255,255,255,0.04);'
                                'border:1px dashed rgba(255,255,255,0.18)'):
                            ui.label(t).style(f'font-size:11px;color:{theme.TEXT_MUTED}')
                            with ui.element('div').classes('cursor-pointer').style(
                                    'display:flex;align-items:center;width:13px;height:13px'
                            ).on('click', lambda _, i=aid, tg=t: add_tag_to_article(i, tg, promote=True)
                                 ).mark(f'tag-accept-{t}').tooltip(f'Add "{t}" and learn it'):
                                ui.icon('fa-solid fa-check').style(f'font-size:9px;color:{theme.GREEN}')
                            with ui.element('div').classes('cursor-pointer').style(
                                    'display:flex;align-items:center;width:13px;height:13px'
                            ).on('click', lambda _, i=aid, tg=t: dismiss_suggestion(i, tg)
                                 ).mark(f'tag-dismiss-{t}').tooltip('Dismiss'):
                                ui.icon('fa-solid fa-xmark').style(f'font-size:9px;color:{theme.TEXT_DIM}')

    # ---------- rendering: reader ----------

    def _reader_content_block(art: dict, data: dict | None):
        """Shared between plain Read mode and Discuss mode's left-hand article pane --
        badge/meta/title/action row/why-it-matters/body (Chris, 2026-08-04: the action
        row stays visible in Discuss mode too, not just plain Read mode)."""
        if data is None:
            ui.spinner(size='lg')
            return
        badge_text, badge_color = _badge(art)
        with ui.row().classes('items-center no-wrap').style('gap:10px;margin-bottom:8px;flex-wrap:wrap'):
            ui.label(badge_text).style(
                f'font-size:9.5px;font-weight:700;padding:2px 7px;border-radius:10px;color:{badge_color}')
            if art.get('content_type'):
                ui.label(art['content_type']).style(
                    f'font-size:11px;color:{theme.TEXT_MUTED};background:rgba(255,255,255,0.05);'
                    f'border-radius:6px;padding:2px 8px')
            if art['date']:
                ui.label(art['date']).style(f'font-size:12px;color:{theme.TEXT_DIM}')
            ui.label(f"{art.get('reading_minutes', 1)} min read").style(f'font-size:12px;color:{theme.TEXT_DIM}')
        ui.label(art['title']).style(f'font-size:20px;font-weight:700;margin-bottom:10px;color:{theme.TEXT}')

        aid = art['id']
        wf = _wf(aid)
        if aid in state['confirming_ids']:
            with ui.row().classes('items-center no-wrap').style('gap:8px;margin-bottom:14px'):
                ui.label('Delete this article?').style(f'font-size:12.5px;color:{theme.RED};font-weight:600')
                ui.button('Yes, delete', on_click=lambda: confirm_delete(aid)).props('dense').style(
                    f'background:{theme.RED};color:{theme.BG};font-size:11.5px')
                ui.button('Cancel', on_click=lambda: cancel_delete(aid)).props('flat dense').style(
                    f'color:{theme.TEXT_MUTED};font-size:11.5px')
        else:
            is_sending = aid in state['sending_ids']
            # Every action here is a small icon button now, matching the
            # article-list row's style (Chris, 2026-08-01: felt redundant as full
            # labeled buttons). 'Flag duplicate' was dropped entirely rather than
            # shrunk -- duplicate detection already runs automatically at ingest
            # (semantic/embedding dedup in homelab-intake's daemon, see
            # services/intake.py's is_duplicate), the manual toggle only existed
            # to correct that automatic call, and Chris decided that's not worth a
            # dedicated control here: the "Duplicate" badge above (_badge()) still
            # surfaces the status passively, and Delete covers the case where he
            # actually wants a wrongly-kept duplicate gone. (The list row's own
            # "..." overflow menu still has a manual flag/clear entry -- untouched,
            # out of scope for this change.) Marker names are prefixed 'reader-' --
            # the list row's own icons for this same article use unprefixed marker
            # names and are visible on screen at the same time, so both need to
            # stay uniquely findable.
            with ui.row().classes('items-center no-wrap').style('gap:6px;flex-wrap:wrap;margin-bottom:14px'):
                icon_actions = [
                    ('fa-solid fa-comment-dots', 'Discuss', True, theme.ACCENT,
                     lambda _, i=aid: open_discuss(i), 'reader-discuss'),
                ]
                if art.get('source'):
                    icon_actions.append((
                        'fa-solid fa-arrow-up-right-from-square', 'Open original', True, theme.TEXT_MUTED,
                        lambda _, u=art['source']: ui.navigate.to(u, new_tab=True), 'reader-open-original'))
                icon_actions += [
                    ('fa-solid fa-star' if wf['favorite'] else 'fa-regular fa-star', 'Favorite',
                     wf['favorite'], theme.AMBER, lambda _, i=aid: toggle_favorite(i), 'reader-f'),
                    ('fa-solid fa-box-archive', 'Archive/unarchive', wf['archived'], theme.ACCENT,
                     lambda _, i=aid: toggle_archived(i), 'reader-a'),
                ]
                for icon, tip, is_on, color, handler, mark_name in icon_actions:
                    with ui.element('div').classes('cursor-pointer').style(
                            'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;'
                            'justify-content:center'
                    ).on('click', handler).mark(f'row-{mark_name}-{aid}').tooltip(tip):
                        ui.icon(icon).style(f'font-size:12.5px;color:{color if is_on else theme.TEXT_DIM}')

                if is_sending:
                    with ui.element('div').style(
                            'width:28px;height:28px;display:flex;align-items:center;justify-content:center'
                    ).mark(f'reader-sending-{aid}'):
                        ui.spinner(size='xs').style(f'color:{theme.PURPLE}')
                elif aid in state['verifying_ids']:
                    with ui.element('div').style(
                            'width:28px;height:28px;display:flex;align-items:center;'
                            'justify-content:center'
                    ).mark(f'reader-verifying-{aid}'):
                        ui.spinner(size='xs').style(f'color:{theme.GREEN}')
                elif wf.get('plane_issue_id'):
                    with ui.element('div').classes('cursor-pointer').style(
                            'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;'
                            'justify-content:center'
                    ).on('click', lambda _, i=aid: verify_plane_todo(i)).mark(
                            f'reader-sent-icon-{aid}').tooltip(
                            'Sent to HomeLab — click to re-check it still exists'):
                        ui.icon('fa-solid fa-check').style(f'font-size:12.5px;color:{theme.GREEN}')
                else:
                    with ui.element('div').classes('cursor-pointer').style(
                            'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;'
                            'justify-content:center'
                    ).on('click', lambda _, i=aid: send_to_homelab(i)).mark(
                            f'reader-send-icon-{aid}').tooltip('Send to HomeLab'):
                        ui.icon('fa-solid fa-arrow-up-from-bracket').style(f'font-size:12.5px;color:{theme.PURPLE}')

                with ui.element('div').classes('cursor-pointer').style(
                        'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;'
                        'justify-content:center'
                ).on('click', lambda _, i=aid: resubmit_row(i)).mark(f'reader-resubmit-{aid}').tooltip('Resubmit'):
                    ui.icon('fa-solid fa-rotate-right').style(f'font-size:12.5px;color:{theme.ACCENT}')

                with ui.element('div').classes('cursor-pointer').style(
                        'width:28px;height:28px;border-radius:6px;display:flex;align-items:center;'
                        'justify-content:center'
                ).on('click', lambda _, i=aid: request_delete(i)).mark(
                        f'reader-delete-icon-{aid}').tooltip('Delete'):
                    ui.icon('fa-solid fa-trash').style(f'font-size:12.5px;color:{theme.RED}')

        render_tag_editor(art)

        if art.get('why_it_matters'):
            with ui.column().style(
                    'background:rgba(249,201,124,0.08);border:1px solid rgba(249,201,124,0.22);'
                    'border-radius:10px;padding:12px 14px;margin-bottom:16px;gap:6px;max-width:640px'):
                with ui.row().classes('items-center no-wrap').style(f'gap:7px;color:{theme.AMBER}'):
                    ui.icon('fa-solid fa-bolt').style('font-size:11px')
                    ui.label(f"WHY IT MATTERS · PRIORITY {art.get('priority_score')}").style(
                        'font-size:10.5px;font-weight:700;letter-spacing:0.3px')
                ui.label(art['why_it_matters']).style('font-size:12.5px;line-height:1.5;color:#cdd1e0')

        # Three stacked sections replace the old Content/AI Summary tab toggle
        # (Chris, 2026-08-02: wanted summary, analysis, and the real article text all
        # scrollable on one screen instead of flipping tabs).

        def _section_header(label):
            with ui.row().classes('items-center no-wrap').style('gap:8px;width:100%;margin:4px 0 8px'):
                ui.label(label).style(
                    f'font-size:10.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};'
                    f'white-space:nowrap')
                ui.element('div').style('flex:1;height:1px;background:rgba(255,255,255,0.06)')

        _section_header('SUMMARY')
        # data['summary'] is the ## Summary section; articles whose body has no
        # parseable summary heading (odd legacy files) fall back to the whole stored body
        ui.markdown(data.get('summary') or data['content']).classes('nq-markdown').style(
            f'background:{theme.CARD_BG};border-radius:10px;padding:14px 16px;margin-bottom:18px')

        if data.get('analysis'):
            _section_header('APPLICATION ANALYSIS')
            ui.markdown(data['analysis']).classes('nq-markdown').style(
                f'background:rgba(165,180,252,0.05);border:1px solid rgba(165,180,252,0.14);'
                f'border-radius:10px;padding:14px 16px;margin-bottom:18px')

        _section_header('FULL ARTICLE')
        ft = state['fulltext']
        if not art.get('source'):
            ui.label('No source URL on this article — nothing to fetch.').style(
                f'font-size:12px;color:{theme.TEXT_DIM};margin-bottom:20px')
        elif ft['status'] == 'ready' and ft['text']:
            ui.markdown(ft['text']).classes('nq-markdown').style('margin-bottom:20px')
        elif ft['status'] == 'failed':
            with ui.column().style(
                    'background:rgba(249,201,124,0.06);border:1px solid rgba(249,201,124,0.2);'
                    'border-radius:10px;padding:12px 14px;margin-bottom:20px;gap:8px;max-width:640px'):
                ui.label("Couldn't fetch the full article (paywall, dead link, or the site "
                          'blocked the request).').style(f'font-size:12px;color:{theme.TEXT_MUTED}')
                with ui.row().classes('items-center no-wrap').style('gap:12px'):
                    ui.label('Retry').classes('cursor-pointer').style(
                        f'font-size:11.5px;font-weight:600;color:{theme.ACCENT}').on(
                        'click', lambda: retry_full_text()).mark('fulltext-retry')
                    ui.label('Open original ↗').classes('cursor-pointer').style(
                        f'font-size:11.5px;font-weight:600;color:{theme.TEXT_MUTED}').on(
                        'click', lambda u=art['source']: ui.navigate.to(u, new_tab=True))
        else:  # 'idle' (kickoff pending) or 'loading' -- both mean a fetch is on its way
            with ui.row().classes('items-center no-wrap').style('gap:8px;margin-bottom:20px'):
                ui.spinner(size='sm').style(f'color:{theme.ACCENT}')
                ui.label(f'Fetching full article from {_short_url(art["source"])}…').style(
                    f'font-size:12px;color:{theme.TEXT_DIM}')

    @ui.refreshable
    def render_reader():
        aid = state.get('selected')
        if not aid:
            return
        art = next((a for a in state['articles'] if a['id'] == aid), None)
        if not art:
            return
        data = state.get('article_content')
        ids = [a['id'] for a in filtered_articles()]
        position = f"{ids.index(aid) + 1} of {len(ids)}" if aid in ids else None

        with ui.column().style('height:100%;width:100%;gap:0'):
            with ui.row().classes('items-center no-wrap').style(
                    f'padding:10px 16px;border-bottom:1px solid {theme.BORDER};gap:10px;width:100%'):
                if state['reader_size'] == 'full':
                    # Full width hides the article list entirely, which is the most
                    # disorienting of the two sizes -- give the way back a visible
                    # text label, not just a small icon, so it's easy to find (live
                    # testing showed the icon-only version was easy to miss entirely).
                    with ui.row().classes('items-center no-wrap cursor-pointer').style(
                            f'gap:5px').on('click', lambda: reset_reader_size()).mark('reader-show-list'):
                        ui.icon('fa-solid fa-compress').style(f'font-size:11px;color:{theme.ACCENT}')
                        ui.label('Show list').style(f'font-size:11.5px;font-weight:600;color:{theme.ACCENT}')
                else:
                    ui.icon('fa-solid fa-expand').classes('cursor-pointer').style(
                        f'font-size:11px;color:{theme.TEXT_DIM}').on('click', lambda: cycle_reader_wider()).tooltip(
                        'Full width')
                with ui.row().style(f'gap:3px;background:{theme.CARD_BG};border-radius:8px;padding:3px'):
                    for key, label in [('read', 'Read'), ('discuss', 'Discuss')]:
                        active = state['reader_mode'] == key
                        with ui.row().classes('items-center no-wrap cursor-pointer').style(
                                f'padding:6px 14px;border-radius:6px;font-size:12px;font-weight:600;'
                                f'background:{theme.ACCENT if active else "transparent"};'
                                f'color:{theme.BG if active else theme.TEXT_MUTED};gap:6px'
                        ).on('click', lambda _, k=key: set_reader_mode(k)).mark(f'reader-mode-{key}'):
                            ui.label(label)
                            if key == 'discuss' and state['discuss']['thread']:
                                ui.label(str(len(state['discuss']['thread']))).style(
                                    f'font-size:9px;font-weight:700;background:rgba(0,0,0,0.2);'
                                    f'border-radius:8px;padding:0 5px')
                ui.space()
                if position:
                    ui.label(position).style(f'font-size:11px;color:{theme.TEXT_DIM}')
                ui.icon('fa-solid fa-chevron-up').classes('cursor-pointer').style(
                    f'font-size:11px;color:{theme.TEXT_DIM}').on('click', lambda: move_focus(-1)).tooltip('Previous (k)')
                ui.icon('fa-solid fa-chevron-down').classes('cursor-pointer').style(
                    f'font-size:11px;color:{theme.TEXT_DIM}').on('click', lambda: move_focus(1)).tooltip('Next (j)')
                ui.icon('fa-solid fa-xmark').classes('cursor-pointer').style(
                    f'font-size:13px;color:{theme.TEXT_DIM}').on('click', lambda: close_reader()).tooltip('Close')

            if state['reader_mode'] == 'discuss':
                # height:100% on the article pane is load-bearing: NiceGUI rows default
                # to align-items:flex-start (nicegui.css), so without it the pane sizes
                # to its full content height instead of the row -- its overflow:auto
                # then never engages, the page itself grows/scrolls, and the chat column
                # stays anchored at the article's top instead of staying in view
                # (hit live 2026-08-02, with the full-text section making articles long).
                with ui.row().classes('no-wrap').style('flex:1;min-height:0;width:100%;gap:0'):
                    with ui.column().classes('nq-custom-scroll').style(
                            'flex:1;height:100%;overflow:auto;padding:18px 24px;min-width:0'):
                        _reader_content_block(art, data)
                    with ui.column().style(f'width:520px;flex:none;border-left:1px solid {theme.BORDER};height:100%'):
                        discuss_panel.build(
                            art, state['discuss'], on_send=lambda t: discuss_send(t),
                            on_toggle_source=lambda s: discuss_toggle_source(s),
                            on_select_model=discuss_select_model,
                            on_clear_thread=lambda: discuss_clear_thread(), on_open_citation=discuss_open_citation,
                            on_close_repo_scope=discuss_close_repo_scope,
                        )
                return

            with ui.column().classes('nq-custom-scroll').style('flex:1;overflow:auto;padding:20px 28px;min-width:0'):
                _reader_content_block(art, data)

    # ---------- layout ----------
    #
    # list_col/reader_col are created ONCE, outside any @ui.refreshable -- opening,
    # closing, or resizing the reader only ever calls update_layout(), which adjusts
    # these two columns' own width/visibility in place. Nothing here tears down or
    # recreates the list (or its scroll container), so scroll position survives every
    # article click; only render_articles()/render_reader() (each independently
    # refreshable) replace their own contents when the underlying data actually
    # changes. An earlier version refreshed one big wrapper around everything
    # (header/toolbar/list/reader) on every reader open/close/resize -- correct, but
    # needlessly rebuilt the whole list (and its scroll position) just to show a
    # reader pane; this version keeps the perf/UX property without changing behavior.

    _LIST_BASE_STYLE = f'border-right:1px solid {theme.BORDER};height:100%;gap:0;min-width:0'
    _READER_BASE_STYLE = 'height:100%;min-width:0'

    with ui.row().style('flex:1;height:100%;min-height:0;gap:0;width:100%'):
        list_col = ui.column().style(f'flex:1;{_LIST_BASE_STYLE}')
        with list_col:
            render_header()
            render_toolbar()
            with ui.column().classes('nq-custom-scroll').style(
                    'flex:1;overflow:auto;padding:8px 10px;gap:2px;width:100%'):
                render_queue()
                render_articles()

        reader_col = ui.column().style(f'width:560px;flex:none;{_READER_BASE_STYLE}')
        with reader_col:
            render_reader()
        reader_col.set_visibility(False)

    def update_layout():
        reader_open = bool(state.get('selected'))
        reader_full = reader_open and state['reader_size'] == 'full'

        list_col.set_visibility(not reader_full)
        # flex:1 when the reader's closed (list gets the full width); a fixed narrow
        # width once it's open, so the reader -- not the list -- gets whatever space
        # is left (Chris, 2026-08-01: wanted the article content easier to read, not
        # a wider triage list). Irrelevant when reader_full since the list is hidden.
        list_col.style(replace=f'{"flex:1" if not reader_open else "width:380px;flex:none"};{_LIST_BASE_STYLE}')

        reader_col.set_visibility(reader_open)
        if reader_open:
            # Always flex:1 once open, at both remaining sizes ('normal' fills what's
            # left next to the list; 'full' fills everything once the list is hidden
            # too) -- previously 'normal'/'wide' were fixed 560px/860px, which left a
            # dead blank region on anything wider than list+reader's combined fixed
            # widths on a wide monitor.
            reader_col.style(replace=f'flex:1;{_READER_BASE_STYLE}')

    def get_context_summary():
        folder_desc = f"folder='{state['folder']}'"
        if state['search']:
            folder_desc += f", search=\"{state['search']}\""
        arts = filtered_articles()
        lines = [f"Viewing Article Intake, {folder_desc}.", f"{len(arts)} articles visible:"]
        lines += [f"- {a['title']} ({a['id']})" for a in arts[:15]]

        aid = state.get('selected')
        content = state.get('article_content')
        if aid and content:
            art = next((a for a in state['articles'] if a['id'] == aid), None)
            if art:
                lines.append(f'\nCurrently OPEN article: "{art["title"]}"')
                lines.append(content['content'][:4000])
        return '\n'.join(lines)

    def get_context_card():
        aid = state.get('selected')
        art = next((a for a in state['articles'] if a['id'] == aid), None) if aid else None
        pills = [f"{len(filtered_articles())} visible"]
        if state['tag_filters']:
            pills.append(f"{len(state['tag_filters'])} tags")
        focus = f'Open: "{art["title"]}"' if art else 'Ask me about anything in the archive.'
        return {'icon': 'fa-solid fa-newspaper', 'tab': 'Article Intake', 'pills': pills, 'focus': focus}

    ai_context.register('intake', get_context_summary)
    ai_context.register_card('intake', get_context_card)

    live_state.register('intake', lambda: ui.timer(0.01, reload_workflow, once=True))

    ui.timer(0.05, _initial_load, once=True)
