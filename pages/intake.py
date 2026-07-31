from urllib.parse import urlparse

from nicegui import run, ui

from components import ai_context, discuss_panel, theme
from components.confirm_dialog import confirm
from components.util import client_alive
from services import intake, intake_state, plane
from services.ai import discuss

FOLDERS = [
    ('all', 'fa-solid fa-inbox', 'All Articles'),
    ('homelab', 'fa-solid fa-server', 'Homelab'),
    ('news', 'fa-solid fa-newspaper', 'News'),
    ('errors', 'fa-solid fa-triangle-exclamation', 'Errors & Rejections'),
]

SORT_OPTIONS = [
    ('date', 'Newest first'), ('priority', 'Priority'), ('title', 'Title A-Z'),
    ('unread', 'Unread first'), ('favorite', 'Favorites first'),
]

SHORTCUTS = [
    ('j / ↓', 'Next article'), ('k / ↑', 'Previous article'), ('Enter', 'Open focused article'),
    ('x', 'Toggle selection'), ('r', 'Toggle read/unread'), ('f', 'Toggle favorite'),
    ('s', 'Send to HomeLab'), ('Del', 'Delete'), ('?', 'This cheat sheet'), ('Esc', 'Close'),
]


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
        'articles': [], 'queue': [], 'workflow': {}, 'folders': [], 'prefs': {'view': 'cards', 'sort': 'date'},
        'folder': 'all', 'tag_filters': set(), 'tag_search': '', 'search': '', 'include_archived': False,
        'select_mode': False, 'selected_ids': set(), 'rail_open': True,
        'selected': None, 'article_content': None, 'reader_tab': 'content', 'reader_mode': 'read',
        'discuss': {'model': 'claude', 'active_sources': {'article', 'repo', 'archive'}, 'thread': [], 'busy': False},
        'focused_id': None, 'articles_loaded': False,
    }

    def _wf(aid):
        return state['workflow'].get(aid, {'read': False, 'favorite': False, 'archived': False})

    def folder_counts():
        arts = state['articles']
        failed = [q for q in state['queue'] if q.get('status') == 'failed']
        return {
            'all': len(arts),
            'homelab': len([a for a in arts if a['category'] == 'Homelab' and not a['is_duplicate']]),
            'news': len([a for a in arts if a['category'] == 'News' and not a['is_duplicate']]),
            'errors': len([a for a in arts if a['is_duplicate']]) + len(failed),
        }

    def my_folder_counts():
        return {name: len([a for a in state['articles'] if name in a.get('user_folders', [])])
                for name in state['folders']}

    def archived_count():
        return len([a for a in state['articles'] if _wf(a['id'])['archived']])

    def _folder_scoped_articles():
        arts = state['articles']
        folder = state['folder']
        if folder == 'homelab':
            arts = [a for a in arts if a['category'] == 'Homelab' and not a['is_duplicate']]
        elif folder == 'news':
            arts = [a for a in arts if a['category'] == 'News' and not a['is_duplicate']]
        elif folder == 'errors':
            arts = [a for a in arts if a['is_duplicate']]
        elif folder == 'archived':
            return [a for a in arts if _wf(a['id'])['archived']]
        elif folder.startswith('custom:'):
            name = folder[len('custom:'):]
            arts = [a for a in arts if name in a.get('user_folders', [])]
        if not state['include_archived']:
            arts = [a for a in arts if not _wf(a['id'])['archived']]
        return arts

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
        sort = state['prefs'].get('sort', 'date')
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

    # ---------- folder / tag / search / view actions ----------

    def select_folder(key):
        state['folder'] = key
        state['tag_filters'] = set()
        render_folders.refresh()
        render_my_folders.refresh()
        render_tags.refresh()
        render_articles.refresh()

    def toggle_rail():
        state['rail_open'] = not state['rail_open']
        render_rail.refresh()

    def select_tag(tag):
        if tag in state['tag_filters']:
            state['tag_filters'].discard(tag)
        else:
            state['tag_filters'].add(tag)
        render_tags.refresh()
        render_articles.refresh()
        render_toolbar_row2.refresh()

    def clear_tags():
        state['tag_filters'] = set()
        render_tags.refresh()
        render_articles.refresh()
        render_toolbar_row2.refresh()

    def on_tag_search(e):
        state['tag_search'] = e.value or ''
        render_tags.refresh()

    def on_search(e):
        state['search'] = e.value or ''
        render_articles.refresh()

    async def set_sort(value):
        state['prefs']['sort'] = value
        await run.io_bound(intake_state.set_prefs, sort=value)
        render_articles.refresh()

    async def set_view(value):
        state['prefs']['view'] = value
        await run.io_bound(intake_state.set_prefs, view=value)
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

    def toggle_include_archived(e):
        state['include_archived'] = e.value
        render_articles.refresh()

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
            render_my_folders.refresh()

    # ---------- workflow state (read/favorite/archived) ----------

    async def reload_workflow():
        wf = await run.io_bound(intake_state.all_article_states)
        if wf is not None and client_alive():
            state['workflow'] = wf
            render_articles.refresh()
            render_folders.refresh()
            render_my_folders.refresh()
            render_reader.refresh()

    async def toggle_read(aid):
        new_val = not _wf(aid)['read']
        await run.io_bound(intake_state.set_article_state, aid, read=new_val)
        await reload_workflow()

    async def toggle_favorite(aid):
        new_val = not _wf(aid)['favorite']
        await run.io_bound(intake_state.set_article_state, aid, favorite=new_val)
        await reload_workflow()

    async def send_to_homelab(aid):
        art = next((a for a in state['articles'] if a['id'] == aid), None)
        if not art:
            return
        data = await run.io_bound(intake.get_article, aid)
        summary = (data.get('summary') if data else '') or art.get('why_it_matters') or art.get('snippet') or ''
        result = await run.io_bound(plane.send_article_to_plane, art, summary)
        if result is None:
            return
        success, error = result
        if success:
            await run.io_bound(intake_state.set_article_state, aid, read=True, archived=True)
            await reload_workflow()
            ui.notify('Sent to HomeLab · to-do created, article archived.', type='positive')
        else:
            ui.notify(f'Failed to send to HomeLab: {error}', type='negative')

    # ---------- bulk actions ----------

    async def bulk_mark(read=None, favorite=None):
        ids = list(state['selected_ids'])
        fields = {}
        if read is not None:
            fields['read'] = read
        if favorite is not None:
            fields['favorite'] = favorite
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
            await run.io_bound(intake.delete_article, aid)
        state['selected_ids'] = set()
        await reload_articles()

    # ---------- reader ----------

    def select_article(aid):
        state['selected'] = aid
        state['article_content'] = None
        state['reader_tab'] = 'content'
        state['reader_mode'] = 'read'
        state['focused_id'] = aid
        render_reader.refresh()
        ui.timer(0.01, lambda: load_article_content(aid), once=True)

    def set_reader_tab(tab):
        state['reader_tab'] = tab
        render_reader.refresh()

    async def set_reader_mode(mode):
        state['reader_mode'] = mode
        if mode == 'discuss' and state['selected']:
            thread = await run.io_bound(intake_state.get_thread, state['selected'])
            state['discuss']['thread'] = thread if thread is not None else []
        render_reader.refresh()

    async def load_article_content(aid):
        data = await run.io_bound(intake.get_article, aid)
        if client_alive() and state.get('selected') == aid:
            state['article_content'] = data or {'content': '*Error loading article.*'}
            render_reader.refresh()

    async def delete_current():
        aid = state.get('selected')
        if not aid:
            return
        if not await confirm('Delete article?', 'Permanently delete this article?',
                              confirm_label='Delete', danger=True):
            return
        await run.io_bound(intake.delete_article, aid)
        state['selected'] = None
        if client_alive():
            render_reader.refresh()
        await reload_articles()

    async def mark_dup_current():
        aid = state.get('selected')
        if not aid:
            return
        await run.io_bound(intake.mark_duplicate, aid)
        await reload_articles()
        await load_article_content(aid)

    async def resubmit_current():
        aid = state.get('selected')
        if not aid:
            return
        result = await run.io_bound(intake.resubmit_article, aid)
        if result is None:
            return
        if result.get('success'):
            ui.notify('Queued for resubmission', type='positive')
            await reload_queue()
        else:
            ui.notify(f"Resubmit failed: {result.get('error')}", type='negative')

    # ---------- Discuss ----------

    def discuss_toggle_source(source):
        active = state['discuss']['active_sources']
        if source in active:
            active.discard(source)
        else:
            active.add(source)
        render_reader.refresh()

    def discuss_select_model(model):
        state['discuss']['model'] = model
        render_reader.refresh()

    async def discuss_clear_thread():
        aid = state['selected']
        if not aid:
            return
        await run.io_bound(intake_state.clear_thread, aid)
        state['discuss']['thread'] = []
        render_reader.refresh()

    def discuss_open_citation(aid):
        state['reader_mode'] = 'read'
        select_article(aid)

    async def discuss_send(text):
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
        state['discuss']['busy'] = True
        render_reader.refresh()

        history = [{'role': 'model' if m['role'] == 'assistant' else 'user', 'text': m['text']}
                   for m in state['discuss']['thread'][:-1]]
        active_sources = set(state['discuss']['active_sources'])
        model = state['discuss']['model']
        try:
            result = await run.io_bound(discuss.send_discuss_message, art, active_sources, text, history, model)
        except Exception as e:
            result = {'text': f'Error: {e}', 'tool_calls': []}
        if result is None:
            result = {'text': 'Cancelled.', 'tool_calls': []}
        state['discuss']['busy'] = False
        if not client_alive() or state['selected'] != aid:
            return
        cites = [c for tc in result.get('tool_calls', []) for c in tc.get('cites', [])]
        assistant_msg = {'role': 'assistant', 'text': result.get('text', ''),
                          'tools': result.get('tool_calls', []), 'cites': cites}
        state['discuss']['thread'].append(assistant_msg)
        await run.io_bound(intake_state.append_message, aid, assistant_msg)
        render_reader.refresh()

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
            render_articles.refresh()
            return

        ids = [a['id'] for a in filtered_articles()]
        if not ids:
            return
        cur = state.get('focused_id')
        idx = ids.index(cur) if cur in ids else -1

        if key == 'j' or key.is_cursorkey and key.code == 'ArrowDown':
            state['focused_id'] = ids[min(idx + 1, len(ids) - 1)]
            render_articles.refresh()
        elif key == 'k' or key.is_cursorkey and key.code == 'ArrowUp':
            state['focused_id'] = ids[max(idx - 1, 0)]
            render_articles.refresh()
        elif key.enter:
            if cur:
                select_article(cur)
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
        elif key == 's':
            if cur:
                await send_to_homelab(cur)
        elif key.backspace or key == 'Delete':
            if cur:
                state['selected'] = cur
                await delete_current()

    ui.keyboard(on_key=on_key, ignore=['input', 'select', 'button', 'textarea'])

    # ---------- reload / initial load ----------

    async def reload_articles():
        arts = await run.io_bound(intake.list_articles)
        if arts is None:
            return
        state['articles'] = arts
        state['articles_loaded'] = True
        if client_alive():
            render_folders.refresh()
            render_my_folders.refresh()
            render_tags.refresh()
            render_articles.refresh()

    async def reload_queue():
        q = await run.io_bound(intake.get_queue)
        if q is None:
            return
        state['queue'] = q
        if client_alive():
            render_queue.refresh()
            render_folders.refresh()

    async def _initial_load():
        workflow = await run.io_bound(intake_state.all_article_states)
        folders = await run.io_bound(intake_state.list_folders)
        prefs = await run.io_bound(intake_state.get_prefs)
        if workflow is not None:
            state['workflow'] = workflow
        if folders is not None:
            state['folders'] = folders
        if prefs is not None:
            state['prefs'] = prefs
        await reload_articles()
        await reload_queue()

    # ---------- rendering: rail ----------

    @ui.refreshable
    def render_folders():
        counts = folder_counts()
        for key, icon, label in FOLDERS:
            active = key == state['folder']
            classes = 'nq-nav-item items-center no-wrap cursor-pointer' + (' nq-active' if active else '')
            with ui.row().classes(classes).style(
                    f'padding:7px 9px;border-radius:7px;font-size:12px;font-weight:500;gap:10px;width:100%;'
                    f'color:{theme.TEXT if active else theme.TEXT_MUTED}'
            ).on('click', lambda _, k=key: select_folder(k)):
                ui.icon(icon).style('width:13px;font-size:11.5px')
                ui.label(label).style('flex:1')
                ui.label(str(counts[key])).style(f'font-size:10.5px;color:{theme.TEXT_DIM};font-weight:600')

    @ui.refreshable
    def render_my_folders():
        counts = my_folder_counts()
        for name in state['folders']:
            key = f'custom:{name}'
            active = key == state['folder']
            classes = 'nq-nav-item items-center no-wrap cursor-pointer' + (' nq-active' if active else '')
            with ui.row().classes(classes).style(
                    f'padding:7px 9px;border-radius:7px;font-size:12px;font-weight:500;gap:10px;width:100%;'
                    f'color:{theme.TEXT if active else theme.TEXT_MUTED}'
            ).on('click', lambda _, k=key: select_folder(k)):
                ui.icon('fa-solid fa-folder').style(f'width:13px;font-size:10.5px;color:{theme.PURPLE}')
                ui.label(name).style('flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                ui.label(str(counts.get(name, 0))).style(f'font-size:10.5px;color:{theme.TEXT_DIM};font-weight:600')

        active = state['folder'] == 'archived'
        classes = 'nq-nav-item items-center no-wrap cursor-pointer' + (' nq-active' if active else '')
        with ui.row().classes(classes).style(
                f'padding:7px 9px;border-radius:7px;font-size:12px;font-weight:500;gap:10px;width:100%;'
                f'color:{theme.TEXT if active else theme.TEXT_MUTED}'
        ).on('click', lambda _, k='archived': select_folder(k)):
            ui.icon('fa-solid fa-box-archive').style(f'width:13px;font-size:10.5px;color:{theme.PURPLE}')
            ui.label('Archived').style('flex:1')
            ui.label(str(archived_count())).style(f'font-size:10.5px;color:{theme.TEXT_DIM};font-weight:600')

    @ui.refreshable
    def render_tags():
        tags = available_tags()
        n_selected = len(state['tag_filters'])
        with ui.row().classes('items-center no-wrap').style('width:100%;padding:0 2px'):
            ui.label('TAGS').style(f'font-size:10px;font-weight:700;letter-spacing:0.4px;color:{theme.TEXT_DIM};flex:1')
            if n_selected:
                ui.label(f'clear {n_selected}').classes('cursor-pointer').style(
                    f'font-size:9.5px;font-weight:600;color:{theme.ACCENT}').on('click', lambda: clear_tags())
        with ui.row().style('align-items:center;gap:6px;background:#242435;border:1px solid rgba(255,255,255,0.07);'
                             'border-radius:6px;padding:5px 8px;margin:6px 0;width:100%'):
            ui.icon('fa-solid fa-magnifying-glass').style(f'font-size:9px;color:{theme.TEXT_DIM}')
            ui.input(placeholder='Filter tags…', on_change=on_tag_search).props('borderless dense').style(
                f'flex:1;color:{theme.TEXT};font-size:11px')
        if not tags:
            ui.label('No tags match.').style(f'font-size:11px;color:{theme.TEXT_DIM};padding:6px 2px')
            return
        with ui.column().classes('nq-custom-scroll').style('gap:1px;max-height:220px;overflow:auto;width:100%'):
            for tag, count in tags:
                active = tag in state['tag_filters']
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:8px;padding:5px 8px;border-radius:6px;'
                        f'background:{theme.ACCENT_TINT if active else "transparent"}'
                ).on('click', lambda _, t=tag: select_tag(t)):
                    with ui.element('div').style(
                            f'width:13px;height:13px;border-radius:3.5px;flex:none;'
                            f'border:1.5px solid {theme.ACCENT if active else "rgba(255,255,255,0.2)"};'
                            f'background:{theme.ACCENT if active else "transparent"};display:flex;'
                            f'align-items:center;justify-content:center'):
                        if active:
                            ui.icon('fa-solid fa-check').style(f'font-size:7.5px;color:{theme.BG}')
                    ui.label(tag).style(
                        f'flex:1;font-size:11px;color:{theme.ACCENT if active else theme.TEXT_MUTED};'
                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                    ui.label(str(count)).style(f'font-size:10px;color:{theme.TEXT_DIM}')

    @ui.refreshable
    def render_rail():
        if not state['rail_open']:
            with ui.column().style(
                    f'width:42px;flex:none;border-right:1px solid {theme.BORDER};background:{theme.SIDEBAR_BG};'
                    f'align-items:center;padding:14px 0;gap:14px'):
                ui.icon('fa-solid fa-angles-right').classes('cursor-pointer').style(
                    f'font-size:11px;color:{theme.TEXT_DIM}').on('click', lambda: toggle_rail())
                for key, icon, _ in FOLDERS:
                    ui.icon(icon).classes('cursor-pointer').style(
                        f'font-size:12px;color:{theme.TEXT_MUTED}').on('click', lambda _, k=key: select_folder(k))
            return

        with ui.column().style(
                f'width:230px;flex:none;border-right:1px solid {theme.BORDER};background:{theme.SIDEBAR_BG};'
                f'height:100%;gap:0'):
            with ui.column().classes('nq-custom-scroll').style('flex:1;overflow:auto;padding:12px 10px;gap:0;width:100%'):
                with ui.row().classes('items-center no-wrap').style('width:100%;padding:0 2px 6px'):
                    ui.label('CATEGORIES').style(
                        f'font-size:10px;font-weight:700;letter-spacing:0.4px;color:{theme.TEXT_DIM};flex:1')
                    ui.icon('fa-solid fa-angles-left').classes('cursor-pointer').style(
                        f'font-size:10px;color:{theme.TEXT_DIM}').on('click', lambda: toggle_rail())
                render_folders()

                ui.element('div').style('height:1px;background:rgba(255,255,255,0.06);margin:12px 2px')
                with ui.row().classes('items-center no-wrap').style('width:100%;padding:0 2px 6px'):
                    ui.label('MY FOLDERS').style(
                        f'font-size:10px;font-weight:700;letter-spacing:0.4px;color:{theme.TEXT_DIM};flex:1')
                    ui.icon('fa-solid fa-plus').classes('cursor-pointer').style(
                        f'font-size:10px;color:{theme.ACCENT}').on('click', lambda: create_new_folder())
                render_my_folders()

                ui.element('div').style('height:1px;background:rgba(255,255,255,0.06);margin:12px 2px')
                render_tags()

    # ---------- rendering: toolbar ----------

    @ui.refreshable
    def render_bulk_bar():
        if not state['select_mode'] or not state['selected_ids']:
            return
        n = len(state['selected_ids'])
        with ui.row().classes('items-center no-wrap').style(
                f'gap:10px;background:{theme.ACCENT_TINT};border:1px solid rgba(165,180,252,0.3);'
                f'border-radius:9px;padding:8px 12px;width:100%'):
            ui.label(f'{n} selected').style(f'font-size:12px;font-weight:600;color:{theme.ACCENT}')
            ui.space()
            ui.button('Mark read', on_click=lambda: bulk_mark(read=True)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.TEXT}')
            ui.button('Mark unread', on_click=lambda: bulk_mark(read=False)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.TEXT}')
            ui.button('Favorite', on_click=lambda: bulk_mark(favorite=True)).props('flat dense').style(
                f'font-size:11.5px;color:{theme.AMBER}')
            ui.button('Move to folder', on_click=lambda: bulk_move_to_folder()).props('flat dense').style(
                f'font-size:11.5px;color:{theme.PURPLE}')
            ui.button('Delete', on_click=lambda: bulk_delete()).props('flat dense').style(
                f'font-size:11.5px;color:{theme.RED}')
            ui.button('Clear', on_click=clear_selection).props('flat dense').style(
                f'font-size:11.5px;color:{theme.TEXT_MUTED}')

    @ui.refreshable
    def render_toolbar_row2():
        arts = filtered_articles()
        n_unread = len([a for a in arts if not _wf(a['id'])['read']])
        summary = f"{len(arts)} article{'s' if len(arts) != 1 else ''}"
        if state['tag_filters']:
            summary += f" · {len(state['tag_filters'])} tag filter{'s' if len(state['tag_filters']) != 1 else ''}"
        summary += f" · {n_unread} unread"
        with ui.row().classes('items-center no-wrap').style('width:100%'):
            ui.label(summary).style(f'font-size:11px;color:{theme.TEXT_DIM};flex:1')
            with ui.row().classes('items-center no-wrap').style('gap:6px'):
                ui.checkbox(value=state['include_archived'], on_change=toggle_include_archived).props('dense')
                ui.label('Include archived').style(f'font-size:11px;color:{theme.TEXT_MUTED}')

    def render_toolbar():
        with ui.column().style(f'gap:8px;padding:10px 14px;border-bottom:1px solid {theme.BORDER};width:100%'):
            with ui.row().classes('items-center no-wrap').style('gap:9px;width:100%'):
                with ui.row().classes('items-center no-wrap').style(
                        f'flex:1;min-width:0;gap:8px;background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.07);'
                        f'border-radius:7px;padding:6px 10px'):
                    ui.icon('fa-solid fa-magnifying-glass').style(f'font-size:11px;color:{theme.TEXT_DIM}')
                    ui.input(placeholder='Search title, snippet, tags, full text…', on_change=on_search).props(
                        'borderless dense').style(f'flex:1;color:{theme.TEXT};font-size:12px')
                ui.select(options=dict(SORT_OPTIONS), value=state['prefs']['sort'],
                          on_change=lambda e: set_sort(e.value)).props('dense outlined').style('font-size:11.5px')
                with ui.row().style(f'gap:2px;background:{theme.CARD_BG};border-radius:7px;padding:2px'):
                    for key, icon in [('cards', 'fa-solid fa-grip'), ('table', 'fa-solid fa-table-list')]:
                        active = state['prefs']['view'] == key
                        with ui.element('div').classes('cursor-pointer').style(
                                f'width:28px;height:28px;border-radius:5px;display:flex;align-items:center;'
                                f'justify-content:center;background:{theme.ACCENT_TINT if active else "transparent"};'
                                f'color:{theme.ACCENT if active else theme.TEXT_MUTED}'
                        ).on('click', lambda _, k=key: set_view(k)):
                            ui.icon(icon).style('font-size:12px')
                select_btn_active = state['select_mode']
                ui.button('Select', on_click=toggle_select_mode).props('dense outline' if not select_btn_active else 'dense').style(
                    f'font-size:11.5px;'
                    + (f'background:{theme.ACCENT};color:{theme.BG}' if select_btn_active else f'color:{theme.TEXT_MUTED}'))
                ui.button(icon='question_mark', on_click=lambda: _show_cheatsheet()).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')
            render_toolbar_row2()
            render_bulk_bar()

    # ---------- rendering: article list (cards + table) ----------

    @ui.refreshable
    def render_articles():
        if not state['articles_loaded']:
            with ui.column().classes('items-center justify-center').style(
                    f'padding:32px 12px;gap:10px;color:{theme.TEXT_DIM};width:100%'):
                ui.spinner(size='lg')
                ui.label('Loading articles…').style('font-size:12.5px')
            return

        arts = filtered_articles()
        if not arts:
            if state['tag_filters']:
                msg = f"No articles match all {len(state['tag_filters'])} selected tags."
            elif state['search']:
                msg = f'No articles match "{state["search"]}"'
            else:
                msg = 'No articles found.'
            ui.label(msg).style(
                f'padding:24px 12px;text-align:center;color:{theme.TEXT_DIM};font-size:12.5px;width:100%')
            return

        if state['prefs']['view'] == 'table':
            _render_table(arts)
        else:
            _render_cards(arts)

    def _render_cards(arts):
        for a in arts:
            aid = a['id']
            wf = _wf(aid)
            badge_text, badge_color = _badge(a)
            is_focused = state.get('focused_id') == aid
            is_selected = aid in state['selected_ids']
            title_color = theme.TEXT if not wf['read'] else theme.TEXT_MUTED
            title_weight = 700 if not wf['read'] else 500
            with ui.row().classes('no-wrap').style(
                    f'padding:10px;border-radius:9px;gap:8px;width:100%;'
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
                        'gap:5px;flex:1;min-width:0'
                ).on('click', lambda _, i=aid: select_article(i)).mark(f'article-row-{aid}'):
                    with ui.row().classes('items-center no-wrap').style('gap:8px;width:100%'):
                        ui.label(badge_text).style(
                            f'font-size:9.5px;font-weight:700;padding:2px 7px;border-radius:10px;color:{badge_color};'
                            f'background:rgba(255,255,255,0.05)')
                        if (a.get('priority_score') or 0) >= 7.5:
                            with ui.row().classes('items-center no-wrap').style(f'gap:3px;color:{theme.AMBER}'):
                                ui.icon('fa-solid fa-bolt').style('font-size:8px')
                                ui.label(f"P{a['priority_score']}").style('font-size:9.5px;font-weight:700')
                        if wf['favorite']:
                            ui.icon('fa-solid fa-star').style(f'font-size:9px;color:{theme.AMBER}')
                        ui.space()
                        ui.label(f"{a.get('reading_minutes', 1)} min").style(f'font-size:10px;color:{theme.TEXT_DIM}')
                        ui.label(a['date']).style(f'font-size:10.5px;color:{theme.TEXT_DIM}')
                    ui.label(a['title']).style(
                        f'font-size:13.5px;font-weight:{title_weight};color:{title_color};overflow:hidden;'
                        f'text-overflow:ellipsis;white-space:nowrap;max-width:320px')
                    with ui.row().classes('items-center no-wrap').style('gap:6px'):
                        ui.icon('fa-solid fa-link').style(f'font-size:9px;color:{theme.TEXT_MUTED}')
                        ui.label(_short_url(a['source']) if a['source'] else 'Unknown source').style(
                            f'font-size:10.5px;color:{theme.TEXT_MUTED}')
                    if a['snippet']:
                        ui.label(a['snippet']).style(
                            f'font-size:11.5px;color:{theme.ACCENT};opacity:0.85;max-width:320px;overflow:hidden;'
                            f'text-overflow:ellipsis;white-space:nowrap')
                    with ui.row().style('gap:4px;flex-wrap:wrap'):
                        for tag in a['tags'][:3]:
                            ui.label(tag).style(
                                f'font-size:9.5px;color:{theme.TEXT_MUTED};background:rgba(255,255,255,0.05);'
                                f'border-radius:8px;padding:1px 7px')
                        for folder in a.get('user_folders', [])[:2]:
                            ui.label(folder).style(
                                f'font-size:9.5px;color:{theme.PURPLE};background:rgba(203,166,247,0.1);'
                                f'border-radius:8px;padding:1px 7px')

                with ui.column().style('gap:5px;align-items:center;flex:none;padding-top:2px'):
                    for icon, key_hint, is_on, color, handler in [
                        ('fa-solid fa-circle-check' if wf['read'] else 'fa-regular fa-circle', 'R',
                         wf['read'], theme.GREEN, lambda _, i=aid: toggle_read(i)),
                        ('fa-solid fa-star' if wf['favorite'] else 'fa-regular fa-star', 'F',
                         wf['favorite'], theme.AMBER, lambda _, i=aid: toggle_favorite(i)),
                        ('fa-solid fa-arrow-up-from-bracket', 'S', False, theme.PURPLE,
                         lambda _, i=aid: send_to_homelab(i)),
                        ('fa-solid fa-trash', 'D', False, theme.RED, lambda _, i=aid: _delete_row(i)),
                    ]:
                        with ui.row().classes('items-center no-wrap cursor-pointer').style('gap:4px').on(
                                'click', handler):
                            ui.icon(icon).style(f'font-size:12px;color:{color if is_on else theme.TEXT_DIM}')
                            ui.label(key_hint).style(
                                f'font-family:"JetBrains Mono",monospace;font-size:8px;color:{theme.TEXT_DIM}')

    def _render_table(arts):
        with ui.row().classes('items-center no-wrap').style(
                f'padding:6px 10px;border-bottom:1px solid {theme.BORDER};width:100%;gap:8px'):
            if state['select_mode']:
                ui.element('div').style('width:16px;flex:none')
            for label, sort_key, width in [('TITLE', 'title', 'flex:1'), ('DATE', 'date', 'width:70px'),
                                            ('PRIORITY', 'priority', 'width:60px'), ('TIME', None, 'width:50px'),
                                            ('TAGS', None, 'width:120px'), ('', None, 'width:100px')]:
                active = state['prefs']['sort'] == sort_key
                style = f'font-size:9.5px;font-weight:700;letter-spacing:0.3px;color:{theme.ACCENT if active else theme.TEXT_DIM};{width}'
                if sort_key:
                    ui.label(label).classes('cursor-pointer').style(style).on('click', lambda _, k=sort_key: set_sort(k))
                else:
                    ui.label(label).style(style)

        for a in arts:
            aid = a['id']
            wf = _wf(aid)
            is_focused = state.get('focused_id') == aid
            is_selected = aid in state['selected_ids']
            with ui.row().classes('items-center no-wrap').style(
                    f'padding:7px 10px;border-radius:6px;width:100%;gap:8px;'
                    f'background:{theme.ACCENT_TINT if is_focused else "transparent"}'):
                if state['select_mode']:
                    with ui.element('div').classes('cursor-pointer').style(
                            f'width:14px;height:14px;border-radius:4px;flex:none;'
                            f'border:1.5px solid {theme.ACCENT if is_selected else "rgba(255,255,255,0.2)"};'
                            f'background:{theme.ACCENT if is_selected else "transparent"}'
                    ).on('click', lambda _, i=aid: toggle_row_selected(i)):
                        pass
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        'flex:1;min-width:0;gap:6px'
                ).on('click', lambda _, i=aid: select_article(i)).mark(f'article-row-{aid}'):
                    if not wf['read']:
                        ui.element('div').style(f'width:6px;height:6px;border-radius:50%;background:{theme.ACCENT};flex:none')
                    ui.label(a['title']).style(
                        f'font-size:12.5px;font-weight:{600 if not wf["read"] else 400};'
                        f'color:{theme.TEXT if not wf["read"] else theme.TEXT_MUTED};overflow:hidden;'
                        f'text-overflow:ellipsis;white-space:nowrap')
                    if wf['favorite']:
                        ui.icon('fa-solid fa-star').style(f'font-size:9px;color:{theme.AMBER};flex:none')
                ui.label(a['date']).style(f'font-size:10.5px;color:{theme.TEXT_DIM};width:70px')
                ui.label(str(a.get('priority_score') or '-')).style(f'font-size:10.5px;color:{theme.TEXT_DIM};width:60px')
                ui.label(f"{a.get('reading_minutes', 1)}m").style(f'font-size:10.5px;color:{theme.TEXT_DIM};width:50px')
                with ui.row().style('width:120px;gap:3px;overflow:hidden'):
                    for tag in a['tags'][:2]:
                        ui.label(tag).style(
                            f'font-size:9px;color:{theme.TEXT_MUTED};background:rgba(255,255,255,0.05);'
                            f'border-radius:6px;padding:1px 5px')
                with ui.row().style('width:100px;gap:6px'):
                    ui.icon('fa-solid fa-arrow-up-from-bracket').classes('cursor-pointer').style(
                        f'font-size:11px;color:{theme.PURPLE}').on('click', lambda _, i=aid: send_to_homelab(i))
                    ui.icon('fa-solid fa-trash').classes('cursor-pointer').style(
                        f'font-size:11px;color:{theme.RED}').on('click', lambda _, i=aid: _delete_row(i))

    async def _delete_row(aid):
        if not await confirm('Delete article?', 'Permanently delete this article?',
                              confirm_label='Delete', danger=True):
            return
        await run.io_bound(intake.delete_article, aid)
        if state['selected'] == aid:
            state['selected'] = None
            render_reader.refresh()
        await reload_articles()

    # ---------- rendering: queue ----------

    @ui.refreshable
    def render_queue():
        failed = [q for q in state['queue'] if q.get('status') == 'failed']
        active = [q for q in state['queue'] if q.get('status') in ('pending', 'processing')]
        if failed:
            ui.label('FAILED · CLICK TO RETRY').style(
                f'font-size:10.5px;font-weight:700;color:{theme.RED};margin:2px 4px 6px')
            for item in failed:
                with ui.column().classes('cursor-pointer').style(
                        'padding:10px;border-radius:9px;margin-bottom:6px;background:rgba(243,139,168,0.07);'
                        'border:1px solid rgba(243,139,168,0.25);gap:4px;width:100%'
                ).on('click', lambda _, i=item: retry_item(i['id'])):
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

    async def retry_item(item_id):
        await run.io_bound(intake.retry_queue_item, item_id)
        await reload_queue()

    # ---------- rendering: reader ----------

    @ui.refreshable
    def render_reader():
        aid = state.get('selected')
        if not aid:
            with ui.column().classes('items-center justify-center').style(
                    f'height:100%;width:100%;gap:12px;color:{theme.TEXT_DISABLED}'):
                ui.icon('fa-solid fa-book-open').style('font-size:28px')
                ui.label('Select an article to read').style('font-size:13.5px;font-weight:500')
            return
        art = next((a for a in state['articles'] if a['id'] == aid), None)
        if not art:
            return
        data = state.get('article_content')

        with ui.column().style('height:100%;width:100%;gap:0'):
            with ui.row().classes('items-center no-wrap').style(
                    f'padding:12px 20px;border-bottom:1px solid {theme.BORDER};gap:14px;width:100%'):
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
                if art.get('source'):
                    with ui.row().classes('items-center no-wrap cursor-pointer').style(
                            'gap:6px;flex:none;white-space:nowrap'
                    ).on('click', lambda: ui.navigate.to(art['source'], new_tab=True)):
                        ui.icon('fa-solid fa-arrow-up-right-from-square').style(f'font-size:10px;color:{theme.ACCENT}')
                        ui.label('Open original').style(f'font-size:11.5px;font-weight:600;color:{theme.ACCENT}')
                        ui.label(_short_url(art['source'])).style(
                            f'font-family:"JetBrains Mono",monospace;font-size:10px;color:{theme.TEXT_DIM}')

            if state['reader_mode'] == 'discuss':
                discuss_panel.build(
                    art, state['discuss'], on_send=lambda t: discuss_send(t),
                    on_toggle_source=discuss_toggle_source, on_select_model=discuss_select_model,
                    on_clear_thread=lambda: discuss_clear_thread(), on_open_citation=discuss_open_citation,
                )
                return

            with ui.column().classes('nq-custom-scroll').style('flex:1;overflow:auto;padding:20px 28px;min-width:0'):
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
                    domain_line = ' · '.join(p for p in [art.get('primary_domain'), art['date']] if p)
                    if domain_line:
                        ui.label(domain_line).style(f'font-size:12px;color:{theme.TEXT_DIM}')
                    ui.label(f"{art.get('reading_minutes', 1)} min read").style(f'font-size:12px;color:{theme.TEXT_DIM}')
                ui.label(art['title']).style(f'font-size:21px;font-weight:700;margin-bottom:12px;color:{theme.TEXT}')

                if art.get('why_it_matters'):
                    with ui.column().style(
                            'background:rgba(249,201,124,0.08);border:1px solid rgba(249,201,124,0.22);'
                            'border-radius:10px;padding:12px 14px;margin-bottom:16px;gap:6px;max-width:500px'):
                        with ui.row().classes('items-center no-wrap').style(f'gap:7px;color:{theme.AMBER}'):
                            ui.icon('fa-solid fa-bolt').style('font-size:11px')
                            ui.label(f"WHY IT MATTERS · PRIORITY {art.get('priority_score')}").style(
                                'font-size:10.5px;font-weight:700;letter-spacing:0.3px')
                        ui.label(art['why_it_matters']).style('font-size:12.5px;line-height:1.5;color:#cdd1e0')

                with ui.row().style(f'gap:4px;background:{theme.CARD_BG};border-radius:8px;padding:3px;'
                                     f'width:fit-content;margin-bottom:16px'):
                    for key, label in [('content', 'Content'), ('summary', 'AI Summary')]:
                        active = state['reader_tab'] == key
                        with ui.row().classes('cursor-pointer').style(
                                f'padding:6px 14px;border-radius:6px;font-size:12px;font-weight:600;'
                                f'background:{theme.ACCENT if active else "transparent"};'
                                f'color:{theme.BG if active else theme.TEXT_MUTED}'
                        ).on('click', lambda _, k=key: set_reader_tab(k)):
                            ui.label(label)

                if state['reader_tab'] == 'content':
                    ui.markdown(data['content']).classes('nq-markdown').style('margin-bottom:20px')
                else:
                    ui.markdown(data.get('summary') or 'No AI summary available.').classes('nq-markdown').style(
                        f'background:{theme.CARD_BG};border-radius:10px;padding:14px 16px;margin-bottom:20px')

                with ui.row().style('gap:10px;flex-wrap:wrap'):
                    ui.button('Delete', icon='delete', on_click=delete_current).props('outline').style(
                        f'color:{theme.RED}')
                    ui.button('Toggle Duplicate', icon='content_copy', on_click=mark_dup_current).props(
                        'outline').style(f'color:{theme.TEXT_MUTED}')
                    ui.button('Resubmit', icon='refresh', on_click=resubmit_current).props('outline').style(
                        f'color:{theme.ACCENT}')
                    ui.button('Send to HomeLab', icon='send', on_click=lambda: send_to_homelab(aid)).props(
                        'outline').style(f'color:{theme.PURPLE}')

    # ---------- layout ----------

    with ui.row().style('flex:1;height:100%;min-height:0;gap:0;width:100%'):
        render_rail()

        with ui.column().style(
                f'width:380px;flex:none;border-right:1px solid {theme.BORDER};height:100%;gap:0'):
            render_toolbar()
            with ui.column().classes('nq-custom-scroll').style('flex:1;overflow:auto;padding:8px 10px;gap:2px;width:100%'):
                render_queue()
                render_articles()

        with ui.column().style('flex:1;height:100%;min-width:0'):
            render_reader()

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

    ui.timer(0.05, _initial_load, once=True)
