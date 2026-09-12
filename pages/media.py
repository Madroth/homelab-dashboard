from nicegui import run, ui

from components import ai_context, live_state, theme
from components.confirm_dialog import confirm
from components.page_dialog import page_dialog
from components.util import capture_client, client_alive, notify_on
from services import media

MEDIA_TYPE_VISUALS = {
    'movie': ('fa-solid fa-film', 'linear-gradient(150deg,#45475a,#313244)'),
    'tv_show': ('fa-solid fa-tv', 'linear-gradient(150deg,#4a4370,#2f2b45)'),
    'ebook': ('fa-solid fa-book', 'linear-gradient(150deg,#3a5245,#26332b)'),
    'audiobook': ('fa-solid fa-headphones', 'linear-gradient(150deg,#5a4a3a,#332a22)'),
    'comic': ('fa-solid fa-book-open', 'linear-gradient(150deg,#553a4a,#33222b)'),
}


def _type_visual(media_type: str) -> tuple[str, str]:
    return MEDIA_TYPE_VISUALS.get(media_type, ('fa-solid fa-file', 'linear-gradient(150deg,#45475a,#313244)'))


QUICK_LINKS = [
    ('fa-solid fa-clapperboard', 'Radarr', 'http://100.87.245.107:7878'),
    ('fa-solid fa-tv', 'Sonarr', 'http://100.87.245.107:8989'),
    ('fa-solid fa-magnifying-glass', 'Prowlarr', 'http://100.87.245.107:9696'),
    ('fa-solid fa-closed-captioning', 'Bazarr', 'http://100.87.245.107:6767'),
    ('fa-solid fa-chart-simple', 'Tautulli', 'http://100.87.245.107:8181'),
    ('fa-solid fa-list-check', 'Pulsarr', 'http://100.87.245.107:3003'),
    ('fa-solid fa-download', 'qBittorrent', 'http://100.87.245.107:8090'),
    ('fa-solid fa-play', 'Plex', 'http://100.87.245.107:32400/web'),
]

MEDIA_TYPES = [('movie', 'Movie'), ('tv_show', 'TV Show'), ('ebook', 'Ebook'),
               ('audiobook', 'Audiobook'), ('comic', 'Comic')]


async def _show_approved_details(item: dict, on_changed):
    meta = item.get('metadata') or {}
    with page_dialog() as dialog, ui.card().style(
            f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;'
            f'padding:22px;width:550px;max-height:85vh'):
        ui.label('Media Details').style(f'font-size:15px;font-weight:700;color:{theme.TEXT}')
        ui.label(item['proposed_title']).style(f'font-size:12.5px;color:{theme.TEXT_MUTED};margin-bottom:10px')

        with ui.column().classes('nq-custom-scroll').style(
                'gap:12px;font-size:12.5px;max-height:55vh;overflow-y:auto;width:100%'):
            with ui.row().classes('items-center no-wrap').style('gap:8px'):
                ui.label('Category:').style(f'color:{theme.ACCENT};font-weight:700')
                type_select = ui.select(dict(MEDIA_TYPES), value=item['media_type']).props('dense outlined')

            with ui.column().style(
                    f'background:#191925;border:1px solid {theme.BORDER};border-radius:8px;padding:12px;gap:4px'):
                ui.label('Original File:').style(f'color:{theme.ACCENT};font-weight:700')
                ui.label(item['original_filename'])
                if item['original_filename'] != item.get('proposed_path'):
                    ui.label('Target Path:').style(f'color:{theme.RED};font-weight:700;margin-top:4px')
                    ui.label(item.get('proposed_path', ''))

            for label, value in [('Series/Grouping:', meta.get('franchise', 'None')),
                                  ('Short Description:', meta.get('short_description', 'No short description available.')),
                                  ('Long Description:', meta.get('long_description', 'No long description available.')),
                                  ('Sorting Logic:', meta.get('sort_logic', 'No logic recorded.'))]:
                with ui.column().style(
                        f'background:#191925;border:1px solid {theme.BORDER};border-radius:8px;padding:12px;gap:2px'):
                    ui.label(label).style(f'color:{theme.ACCENT};font-weight:700')
                    ui.label(value)

        with ui.row().classes('justify-between w-full').style('margin-top:14px'):
            with ui.row().style('gap:8px'):
                ui.button('Reject/Delete', on_click=lambda: do_reject()).props('outline').style(
                    f'color:{theme.RED}')
                if item.get('status') == 'approved':
                    ui.button('Undo Approval', on_click=lambda: do_undo()).props('outline').style(
                        f'color:{theme.TEXT_MUTED}')
            ui.button('Close', on_click=dialog.close).props('flat').style(f'color:{theme.TEXT_MUTED}')

        async def on_reclassify(e):
            type_select.disable()
            result = await run.io_bound(media.reclassify, str(item['id']), e.value)
            if result is None:
                type_select.enable()
                return
            success, error = result
            if success:
                dialog.close()
                await on_changed(item['id'])
                live_state.refresh_all(exclude='media')
            else:
                ui.notify(f'Failed to reclassify: {error}', type='negative')
                type_select.enable()

        type_select.on_value_change(on_reclassify)

        async def do_reject():
            if not await confirm('Delete media item?',
                                  'It will be removed from your library.',
                                  confirm_label='Delete', danger=True):
                return
            result = await run.io_bound(media.reject, str(item['id']))
            if result is None:
                return
            success, error = result
            if success:
                dialog.close()
                await on_changed(item['id'])
                live_state.refresh_all(exclude='media')
            else:
                ui.notify(f'Failed to reject/delete: {error}', type='negative')

        async def do_undo():
            result = await run.io_bound(media.undo, str(item['id']))
            if result is None:
                return
            success, error = result
            if success:
                dialog.close()
                await on_changed(item['id'])
                live_state.refresh_all(exclude='media')
            else:
                ui.notify(f'Failed to undo: {error}', type='negative')

    await dialog


async def _prompt_edit_title(current_title: str) -> str | None:
    with page_dialog() as dialog, ui.card().style(
            f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:22px'):
        ui.label('Edit Title').style(f'font-size:15px;font-weight:700;color:{theme.TEXT};margin-bottom:10px')
        title_input = ui.input(value=current_title).style('width:100%').props('outlined dense')
        with ui.row().classes('justify-end w-full').style('gap:10px;margin-top:14px'):
            ui.button('Cancel', on_click=lambda: dialog.submit(None)).props('flat').style(
                f'color:{theme.TEXT_MUTED}')
            ui.button('Save', on_click=lambda: dialog.submit(title_input.value)).style(
                f'background:{theme.ACCENT};color:{theme.BG};font-weight:700')
    return await dialog


MEDIA_FILTERS = [('', 'All')] + MEDIA_TYPES


def build():
    state = {'queue': [], 'rejected': [], 'type_filter': '', 'selected_ids': set()}
    # Per-item @ui.refreshable closures (created lazily, keyed by item id) -- lets a
    # single-item change (select, approve, reject, edit) re-render just that one row
    # instead of render_queue.refresh()'s full-queue rebuild (all visible items torn
    # down and recreated), same fix applied to pages/intake.py's article rows after a
    # ~1s-per-click delay was traced to that full-rebuild cost. See _get_row_refreshable().
    row_refreshables: dict[str, object] = {}

    def filtered_queue():
        if not state['type_filter']:
            return state['queue']
        return [i for i in state['queue'] if i.get('media_type') == state['type_filter']]

    def _get_row_refreshable(iid):
        target = row_refreshables.get(iid)
        if target is None:
            @ui.refreshable
            def _row():
                item = next((x for x in state['queue'] if x['id'] == iid), None)
                if item is not None:
                    _render_item(item)
            target = _row
            row_refreshables[iid] = target
        return target

    def toggle_select(item_id):
        # Selection never changes filtered_queue()'s membership or order (it isn't a
        # filter/sort criterion), so this is always safe as a single-row refresh --
        # unlike reload() below, no before/after membership check is needed here.
        sel = state['selected_ids']
        if item_id in sel:
            sel.discard(item_id)
        else:
            sel.add(item_id)
        _get_row_refreshable(item_id).refresh()
        render_bulk_bar.refresh()

    def clear_selection():
        state['selected_ids'].clear()
        render_queue.refresh()
        render_bulk_bar.refresh()

    def set_type_filter(t):
        state['type_filter'] = t
        render_filters.refresh()
        render_queue.refresh()

    @ui.refreshable
    def render_filters():
        with ui.row().style('gap:8px;flex-wrap:wrap'):
            for value, label in MEDIA_FILTERS:
                active = value == state['type_filter']
                with ui.row().classes('cursor-pointer').style(
                        f'font-size:11.5px;font-weight:600;padding:6px 12px;border-radius:16px;'
                        f'background:{theme.ACCENT_TINT if active else "rgba(255,255,255,0.05)"};'
                        f'color:{theme.ACCENT if active else theme.TEXT_MUTED};'
                        f'border:1px solid {theme.ACCENT if active else "transparent"}'
                ).on('click', lambda _, v=value: set_type_filter(v)):
                    ui.label(label)

    @ui.refreshable
    def render_bulk_bar():
        sel = state['selected_ids']
        if not sel:
            return
        with ui.row().classes('items-center no-wrap').style(
                f'gap:12px;background:{theme.ACCENT_TINT};border:1px solid rgba(165,180,252,0.3);'
                f'border-radius:10px;padding:10px 16px;margin-bottom:16px;width:100%'):
            ui.label(f'{len(sel)} selected').style(f'font-size:12.5px;font-weight:600;color:{theme.ACCENT}')
            ui.space()
            ui.button('Approve all', on_click=lambda: bulk('approve')).style(
                f'font-size:12px;font-weight:700;background:{theme.GREEN};color:{theme.BG}')
            ui.button('Reject all', on_click=lambda: bulk('reject')).props('outline').style(
                f'font-size:12px;font-weight:700;color:{theme.RED}')
            ui.button('Clear', on_click=clear_selection).props('flat').style(
                f'font-size:12px;font-weight:600;color:{theme.TEXT_MUTED}')

    def _render_item(item):
        iid = item['id']
        selected = iid in state['selected_ids']
        icon, grad = _type_visual(item.get('media_type'))
        if item['status'] == 'approved':
            with ui.row().classes('items-center no-wrap nq-nav-btn-hover').style(
                    'background:rgba(166,227,161,0.05);border:1px solid rgba(166,227,161,0.2);'
                    'border-radius:9px;padding:12px;gap:10px;width:100%'):
                with ui.element('div').classes('cursor-pointer').style(
                        f'width:17px;height:17px;border-radius:5px;flex:none;'
                        f'border:1.5px solid {theme.ACCENT if selected else "rgba(255,255,255,0.2)"};'
                        f'background:{theme.ACCENT if selected else "transparent"};display:flex;'
                        f'align-items:center;justify-content:center'
                ).on('click', lambda _, i=iid: toggle_select(i)).mark(f'row-select-{iid}'):
                    if selected:
                        ui.icon('fa-solid fa-check').style(f'font-size:9px;color:{theme.BG}')
                with ui.element('div').style(
                        f'width:34px;height:46px;border-radius:5px;background:{grad};flex:none;'
                        f'display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,0.6)'):
                    ui.icon(icon).style('font-size:14px')
                with ui.column().classes('cursor-pointer').style(
                        'gap:2px;flex:1;min-width:0'
                ).on('click', lambda _, it=item: _show_approved_details(it, reload)):
                    ui.label(f"Auto-sorted: {item['proposed_title']}").style(
                        f'font-size:12.5px;font-weight:600;color:{theme.TEXT};overflow:hidden;'
                        f'text-overflow:ellipsis;white-space:nowrap')
                    with ui.row().classes('items-center no-wrap').style('gap:4px'):
                        ui.icon('fa-solid fa-folder-tree').style(f'font-size:9px;color:{theme.TEXT_MUTED}')
                        ui.label(item.get('proposed_path', '')).style(
                            f'font-size:10.5px;color:{theme.TEXT_MUTED};overflow:hidden;'
                            f'text-overflow:ellipsis;white-space:nowrap')
                ui.label(item.get('created_at', '')).style(f'font-size:10.5px;color:{theme.TEXT_DIM}')
        else:
            meta = item.get('metadata') or {}
            year = f"({meta['year']})" if meta.get('year') else ''
            with ui.row().style(
                    f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.07);border-radius:11px;'
                    f'padding:16px;gap:14px;width:100%'):
                with ui.element('div').classes('cursor-pointer').style(
                        f'width:17px;height:17px;border-radius:5px;flex:none;margin-top:2px;'
                        f'border:1.5px solid {theme.ACCENT if selected else "rgba(255,255,255,0.2)"};'
                        f'background:{theme.ACCENT if selected else "transparent"};display:flex;'
                        f'align-items:center;justify-content:center'
                ).on('click', lambda _, i=iid: toggle_select(i)).mark(f'row-select-{iid}'):
                    if selected:
                        ui.icon('fa-solid fa-check').style(f'font-size:9px;color:{theme.BG}')
                with ui.element('div').style(
                        f'width:62px;height:88px;border-radius:7px;background:{grad};flex:none;'
                        f'display:flex;align-items:center;justify-content:center;color:rgba(255,255,255,0.65)'):
                    ui.icon(icon).style('font-size:22px')
                with ui.column().style('flex:1;min-width:0;gap:9px'):
                    ui.label(f"Original: {item['original_filename']}").style(
                        f'font-size:11px;color:{theme.TEXT_MUTED};overflow:hidden;'
                        f'text-overflow:ellipsis;white-space:nowrap')
                    with ui.row().classes('items-center no-wrap').style('gap:8px;flex-wrap:wrap'):
                        ui.label(f"{item['proposed_title']} {year}").style(
                            f'font-size:15px;font-weight:600;color:{theme.TEXT}')
                        if item.get('needs_intervention'):
                            ui.label('NEEDS REVIEW').style(
                                f'font-size:9.5px;font-weight:700;padding:2px 7px;border-radius:10px;'
                                f'background:rgba(243,139,168,0.15);color:{theme.RED};'
                                f'border:1px solid rgba(243,139,168,0.4)')
                    with ui.row().classes('items-center no-wrap').style('gap:4px'):
                        ui.icon('fa-solid fa-folder-tree').style(f'font-size:9px;color:{theme.ACCENT}')
                        ui.label(item.get('proposed_path', '')).style(f'font-size:11px;color:{theme.ACCENT}')

                    with ui.row().style('gap:8px;width:100%;flex-wrap:wrap'):
                        ui.button('Approve', on_click=lambda _, i=iid: do_approve(i)).mark(f'approve-{iid}').style(
                            f'background:{theme.GREEN};color:{theme.BG};font-weight:700')
                        ui.button('Edit Title', on_click=lambda _, i=iid, t=item['proposed_title']:
                                   do_edit(i, t)).mark(f'edit-{iid}').props('flat').style(
                            f'background:rgba(165,180,252,0.15);color:{theme.ACCENT}')
                        ui.button('Reject', on_click=lambda _, i=iid: do_reject(i)).mark(f'reject-{iid}').props(
                            'outline').style(f'color:{theme.RED}')
                        ui.button('Details', on_click=lambda _, it=item: _show_approved_details(it, reload)).mark(
                            f'details-{iid}').props('flat').style(f'color:{theme.TEXT_MUTED}')

    @ui.refreshable
    def render_rejected():
        """What is sitting in the Rejected folder waiting to be deleted.

        Rejection moves files aside rather than deleting them, so without a view
        like this the folder fills up silently and nobody knows. Only rows whose
        file is still on disk are shown -- older rows, from when reject really
        did delete, have nothing left to clear.
        """
        items = [i for i in state.get('rejected', []) if i.get('on_disk')]
        if not items:
            return
        with ui.column().style(
                f'border:1.5px solid rgba(255,180,80,0.25);border-radius:11px;'
                f'padding:12px 14px;width:100%;gap:8px;margin-bottom:12px;'
                f'background:rgba(255,180,80,0.05)'):
            with ui.row().classes('items-center no-wrap').style('gap:8px'):
                ui.icon('delete_outline').style('color:#ffb450;font-size:18px')
                ui.label(f'{len(items)} rejected item'
                         f'{"s" if len(items) != 1 else ""} awaiting deletion').style(
                    f'font-size:13.5px;font-weight:700;color:{theme.TEXT}')
            ui.label('Moved out of the pipeline, not deleted. Remove them yourself when '
                     'you are sure.').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')
            for it in items[:20]:
                with ui.column().style('gap:2px;width:100%'):
                    ui.label(it.get('proposed_title') or it['original_filename']).style(
                        f'font-size:12.5px;color:{theme.TEXT};word-break:break-all')
                    ui.label(it.get('rejected_path') or '').style(
                        f'font-size:11px;color:{theme.TEXT_DIM};word-break:break-all')
            if len(items) > 20:
                ui.label(f'...and {len(items) - 20} more').style(
                    f'font-size:11.5px;color:{theme.TEXT_DIM}')

    @ui.refreshable
    def render_queue():
        queue = filtered_queue()
        if not queue:
            with ui.column().classes('items-center justify-center').style(
                    f'border:1.5px dashed rgba(255,255,255,0.12);border-radius:11px;padding:20px;'
                    f'color:{theme.TEXT_DIM};font-size:12.5px;width:100%'):
                ui.label('Queue is empty. Waiting for media...')
            return
        for item in queue:
            _get_row_refreshable(item['id'])()

    # Every row handler captures its client before its first await. The row it was clicked
    # from can be rebuilt while it waits -- by its own reload, the 5s poll, or another tab --
    # and after that context.client no longer resolves for the rest of the handler, so a
    # bare client_alive() reads "tab closed" and the result never renders. See
    # components/util.capture_client().

    async def do_approve(item_id):
        client = capture_client()
        result = await run.io_bound(media.approve, str(item_id))
        if result is None:
            return
        success, error = result
        if not success:
            notify_on(client, f'Approve failed: {error}', type='negative')
        else:
            notify_on(client, 'Approved.', type='positive')
        await reload(item_id, client=client)
        live_state.refresh_all(exclude='media', client=client)

    async def do_reject(item_id):
        client = capture_client()
        # Reject stopped deleting on 2026-08-22 -- it moves the file to
        # /mnt/Multimedia/Rejected and leaves it for a human. Saying "cannot be
        # undone" would now be false, and would make people hesitate over an
        # action that is actually recoverable.
        if not await confirm('Reject this media item?',
                              'The file moves to the Rejected folder. Nothing is deleted -- '
                              'clear that folder yourself when you are sure.',
                              confirm_label='Reject', danger=True):
            return
        result = await run.io_bound(media.reject, str(item_id))
        if result is None:
            return
        success, error = result
        if not success:
            notify_on(client, f'Reject failed: {error}', type='negative')
        else:
            notify_on(client, 'Rejected.', type='positive')
        await reload(item_id, client=client)
        live_state.refresh_all(exclude='media', client=client)

    async def do_edit(item_id, current_title):
        client = capture_client()
        new_title = await _prompt_edit_title(current_title)
        if not new_title or new_title == current_title:
            return
        result = await run.io_bound(media.edit, str(item_id), new_title)
        if result is None:
            return
        success, error = result
        if not success:
            notify_on(client, f'Edit failed: {error}', type='negative')
        await reload(item_id, client=client)
        live_state.refresh_all(exclude='media', client=client)

    async def bulk(action: str):
        client = capture_client()
        ids = list(state['selected_ids'])
        if action == 'reject' and not await confirm(
                'Reject all selected?', f'{len(ids)} item(s) will be rejected. This cannot be undone.',
                confirm_label='Reject all', danger=True):
            return
        results = await run.io_bound(media.bulk_action, action, ids)
        if results is None:
            return
        failed = [r for r in results if not r['success']]
        if failed:
            notify_on(client, f'{len(failed)} of {len(ids)} failed', type='negative')
        else:
            notify_on(client, f'{action.capitalize()}d {len(ids)} item(s).', type='positive')
        state['selected_ids'].clear()
        await reload(client=client)
        live_state.refresh_all(exclude='media', client=client)

    async def reload(changed_id=None, *, client=None, poll=False):
        """changed_id, when given, names the single item a caller knows it just
        mutated (approve/reject/edit/reclassify/undo). If the refetched queue's
        filtered membership and order didn't actually change -- the common case for a
        single-item status/title edit -- refresh just that one row instead of paying
        render_queue.refresh()'s full-list rebuild cost. Callers that don't know a
        specific id (bulk actions, initial load) always get the full, definitely-correct
        refresh.

        poll=True is the 5s timer, and it rebuilds nothing unless the data changed. It used
        to rebuild the whole queue every five seconds regardless, which deleted whatever
        button you were about to click and, until page_dialog(), whatever dialog you had
        open.

        The queue renders before the rejected list is read, because that read stats each
        rejected file on the NAS mount -- a CIFS path that can hang for minutes when the
        NAS stops answering -- and the row you just approved should not wait on it."""
        if client is None:
            client = capture_client()
        before_ids = [i['id'] for i in filtered_queue()]
        queue = await run.io_bound(media.get_queue)
        if queue is None or not client_alive(client):
            return
        if not (poll and queue == state['queue']):
            # The single-row fast path is only honest when the clicked item is the ONLY thing
            # that changed. Otherwise it stored the whole refetched queue while drawing one
            # row, so a change the daemon made to another item was recorded as shown -- and
            # the poll, finding nothing new, never drew it (AntiGravity's review, 2026-09-11).
            others_unchanged = ([i for i in state['queue'] if i['id'] != changed_id]
                                == [i for i in queue if i['id'] != changed_id])
            state['queue'] = queue
            after_ids = [i['id'] for i in filtered_queue()]
            if (changed_id is not None and before_ids == after_ids and others_unchanged
                    and changed_id in row_refreshables):
                _get_row_refreshable(changed_id).refresh()
            else:
                render_queue.refresh()
            render_bulk_bar.refresh()

        rejected = await run.io_bound(media.get_rejected)
        if rejected is None or not client_alive(client):
            return
        if not (poll and rejected == state['rejected']):
            state['rejected'] = rejected
            render_rejected.refresh()

    def get_context_summary():
        queue = state['queue']
        pending = [i for i in queue if i['status'] != 'approved']
        lines = [f"Viewing Media Curator. {len(queue)} item(s) in queue, {len(pending)} pending review."]
        lines += [f"- {i['proposed_title']} ({i['id']}) [{i['status']}]" for i in pending[:15]]
        return '\n'.join(lines)

    def get_context_card():
        queue = state['queue']
        pending = [i for i in queue if i['status'] != 'approved']
        needs_review = [i for i in pending if i.get('needs_intervention')]
        pills = [f'{len(queue)} in queue', f'{len(pending)} pending']
        focus = (f"Flagged: {needs_review[0]['proposed_title']}" if needs_review
                 else 'Nothing flagged for review.')
        return {'icon': 'fa-solid fa-film', 'tab': 'Media Curator', 'pills': pills, 'focus': focus}

    ai_context.register('media', get_context_summary)
    ai_context.register_card('media', get_context_card)
    live_state.register('media', lambda: ui.timer(0.01, reload, once=True))

    with ui.column().classes('nq-custom-scroll').style('flex:1;height:100%;overflow:auto;padding:24px 28px;gap:0'):
        ui.label('MEDIA STACK').style(
            f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};margin-bottom:12px')
        with ui.row().style('gap:10px;flex-wrap:wrap;margin-bottom:24px'):
            for icon, label, url in QUICK_LINKS:
                with ui.row().classes('nq-nav-btn-hover items-center no-wrap cursor-pointer').style(
                        f'border:1px solid rgba(165,180,252,0.3);border-radius:8px;padding:8px 12px;'
                        f'color:{theme.ACCENT};font-size:12px;font-weight:600;gap:7px'
                ).on('click', lambda _, u=url: ui.navigate.to(u, new_tab=True)):
                    ui.icon(icon)
                    ui.label(label)
                    ui.icon('fa-solid fa-arrow-up-right-from-square').style('font-size:9px')

        render_filters()
        with ui.column().style('margin-top:16px;width:100%'):
            render_bulk_bar()

        ui.label('MEDIA QUEUE').style(
            f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};margin-bottom:12px')
        with ui.column().style('gap:14px;width:100%'):
            render_rejected()
            render_queue()

    ui.timer(0.05, reload, once=True)
    # immediate=False: NiceGUI fires a repeating timer at once by default, which made every
    # page open run two reloads concurrently with the one above.
    ui.timer(5.0, lambda: reload(poll=True), immediate=False)
