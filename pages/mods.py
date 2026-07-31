from nicegui import run, ui

from components import ai_context, live_state, theme
from components.util import client_alive
from services import mods


def _fmt_date(d):
    return d or ''


async def _show_review(name: str, review_text: str):
    with ui.dialog() as dialog, ui.card().style(
            f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;'
            f'padding:22px;width:600px;max-height:80vh'):
        ui.label('AI Review').style(f'font-size:15px;font-weight:700;color:{theme.TEXT}')
        ui.label(name).style(f'font-size:12.5px;color:{theme.TEXT_MUTED};margin-bottom:10px')
        with ui.column().classes('nq-custom-scroll').style('flex:1;overflow-y:auto;max-height:55vh'):
            ui.markdown(review_text or 'No AI review available.').classes('nq-markdown')
        with ui.row().classes('justify-end w-full').style('margin-top:14px'):
            ui.button('Close', on_click=dialog.close).props('flat').style(f'color:{theme.TEXT_MUTED}')
    await dialog


async def _prompt_reject_reason(name: str) -> str | None:
    with ui.dialog() as dialog, ui.card().style(
            f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:22px'):
        ui.label('Reject mod').style(f'font-size:15px;font-weight:700;color:{theme.TEXT}')
        ui.label(f'{name} — this moves the submission to the review folder.').style(
            f'font-size:12.5px;color:{theme.TEXT_MUTED};margin-bottom:14px')
        reason_input = ui.textarea(placeholder='Reason for rejection...').style('width:100%')
        with ui.row().classes('justify-end w-full').style('gap:10px;margin-top:14px'):
            ui.button('Cancel', on_click=lambda: dialog.submit(None)).props('flat').style(
                f'color:{theme.TEXT_MUTED}')
            ui.button('Confirm Reject', on_click=lambda: dialog.submit(
                reason_input.value or 'rejected via dashboard')).style(
                f'background:{theme.RED};color:{theme.BG};font-weight:700')
    return await dialog


def build():
    state = {'staging': [], 'mods': {}}

    @ui.refreshable
    def render_staging():
        staging = state['staging']
        if not staging:
            with ui.column().classes('items-center justify-center').style(
                    f'grid-column:1/-1;border:1.5px dashed rgba(255,255,255,0.12);border-radius:11px;'
                    f'padding:34px;gap:8px;color:{theme.TEXT_DISABLED}'):
                ui.icon('fa-solid fa-circle-check').style('font-size:22px')
                ui.label('No pending reviews').style('font-size:13px;font-weight:500')
            return
        for item in staging:
            sid = item['id']
            meta = item.get('meta') or {}
            sub = item.get('sub') or {}
            mod_name = meta.get('name', sid)
            submitter = sub.get('submitted_by', 'Unknown')
            sha = sub.get('sha256', '')
            short_hash = (sha[:16] + '...') if sha else 'Unknown'
            version = meta.get('version')
            submitted_at = sub.get('arrived_at')

            with ui.column().style(
                    f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.07);border-radius:11px;'
                    f'padding:16px;gap:10px;min-width:0'):
                with ui.row().classes('items-center no-wrap').style('gap:9px'):
                    with ui.element('div').style(
                            f'width:30px;height:30px;border-radius:8px;background:rgba(249,201,124,0.14);'
                            f'color:{theme.AMBER};display:flex;align-items:center;justify-content:center'):
                        ui.icon('fa-solid fa-cube')
                    with ui.column().style('gap:0;flex:1;min-width:0'):
                        with ui.row().classes('items-center no-wrap').style('gap:6px'):
                            ui.label(mod_name).style(
                                f'font-size:13.5px;font-weight:600;color:{theme.TEXT};overflow:hidden;'
                                f'text-overflow:ellipsis;white-space:nowrap')
                            if version:
                                ui.label(f'v{version}').style(
                                    f'font-size:9.5px;font-weight:700;color:{theme.TEXT_MUTED};'
                                    f'background:rgba(255,255,255,0.06);border-radius:6px;padding:1px 6px')
                        sub_line = f'by {submitter}' + (f' · {_fmt_date(submitted_at)}' if submitted_at else '')
                        ui.label(sub_line).style(f'font-size:11px;color:{theme.TEXT_MUTED}')

                with ui.row().classes('items-center no-wrap').style(
                        f'gap:6px;font-size:10.5px;color:{theme.TEXT_DIM};font-family:"JetBrains Mono",monospace;'
                        f'background:rgba(255,255,255,0.03);border-radius:6px;padding:6px 8px'):
                    ui.icon('fa-solid fa-shield-halved').style(f'color:{theme.GREEN}')
                    ui.label(short_hash)

                ui.button('Read Review', icon='description',
                          on_click=lambda _, n=mod_name, r=meta.get('ai_review'): _show_review(n, r)).props(
                    'flat').style(f'width:100%;background:rgba(165,180,252,0.15);color:{theme.ACCENT}')

                with ui.row().style('gap:8px;width:100%'):
                    ui.button('Approve', on_click=lambda _, s=sid: do_approve(s)).style(
                        f'flex:1;background:{theme.GREEN};color:{theme.BG};font-weight:700')
                    ui.button('Reject', on_click=lambda _, s=sid, n=mod_name: do_reject(s, n)).props(
                        'outline').style(f'flex:1;color:{theme.RED}')

    @ui.refreshable
    def render_history():
        mod_map = state['mods']
        if not mod_map:
            ui.label('No mods found in registry.').style(f'grid-column:1/-1;color:{theme.TEXT_DIM};font-size:12.5px')
            return
        for mod_name, mod in mod_map.items():
            history = mod.get('history') or []
            last_update = history[-1].get('submitted_at', '') if history else ''
            decided_by = (history[-1].get('decided_by') if history else None) or 'admin'
            version = mod.get('version')

            with ui.column().style(
                    f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.05);border-radius:11px;'
                    f'padding:16px;gap:8px;opacity:0.85;min-width:0'):
                with ui.row().classes('items-center no-wrap').style('gap:9px'):
                    with ui.element('div').style(
                            f'width:28px;height:28px;border-radius:7px;background:rgba(166,227,161,0.12);'
                            f'color:{theme.GREEN};display:flex;align-items:center;justify-content:center'):
                        ui.icon('fa-solid fa-check').style('font-size:12px')
                    with ui.column().style('gap:0;flex:1;min-width:0'):
                        with ui.row().classes('items-center no-wrap').style('gap:6px'):
                            ui.label(mod_name).style(
                                f'font-size:13px;font-weight:600;color:{theme.TEXT};overflow:hidden;'
                                f'text-overflow:ellipsis;white-space:nowrap')
                            if version:
                                ui.label(f'v{version}').style(
                                    f'font-size:9.5px;font-weight:700;color:{theme.TEXT_MUTED};'
                                    f'background:rgba(255,255,255,0.06);border-radius:6px;padding:1px 6px')
                        sub_line = f"by {mod.get('submitted_by', 'Unknown')}"
                        if mod.get('submitted_at'):
                            sub_line += f" · submitted {_fmt_date(mod['submitted_at'])}"
                        ui.label(sub_line).style(f'font-size:10.5px;color:{theme.TEXT_MUTED}')
                ui.label(f'Approved {_fmt_date(last_update)} · deployed by {decided_by}').style(
                    f'font-size:11px;color:{theme.TEXT_DIM}')

    async def do_approve(sid: str):
        result = await run.io_bound(mods.approve_mod, sid)
        if result is None:
            return
        if result.get('success'):
            ui.notify(result.get('message', 'Deployed.'), type='positive')
        else:
            ui.notify(f"Deploy failed: {result.get('error', 'Unknown error')}", type='negative')
        await reload()
        live_state.refresh_all(exclude='mods')

    async def do_reject(sid: str, name: str):
        reason = await _prompt_reject_reason(name)
        if reason is None:
            return
        result = await run.io_bound(mods.reject_mod, sid, reason)
        if result is None:
            return
        if result.get('success'):
            ui.notify('Rejected.', type='positive')
        else:
            ui.notify(f"Rejection failed: {result.get('error')}", type='negative')
        await reload()
        live_state.refresh_all(exclude='mods')

    async def reload():
        staging = await run.io_bound(mods.get_staging)
        mod_map = await run.io_bound(mods.get_mods)
        if staging is None or mod_map is None:
            return
        if client_alive():
            state['staging'] = staging
            state['mods'] = mod_map
            render_staging.refresh()
            render_history.refresh()

    def get_context_summary():
        staging = state['staging']
        lines = [f"Viewing Mod Pipeline. {len(staging)} pending review(s)."]
        lines += [f"- {(item.get('meta') or {}).get('name', item['id'])} ({item['id']})" for item in staging]
        return '\n'.join(lines)

    def get_context_card():
        staging = state['staging']
        names = [(item.get('meta') or {}).get('name', item['id']) for item in staging]
        focus = f"Ask me to approve or reject {names[0]}." if names else 'Nothing pending review.'
        return {'icon': 'fa-solid fa-cubes', 'tab': 'Mod Pipeline',
                'pills': [f'{len(staging)} pending'], 'focus': focus}

    ai_context.register('mods', get_context_summary)
    ai_context.register_card('mods', get_context_card)
    live_state.register('mods', lambda: ui.timer(0.01, reload, once=True))

    with ui.column().style('flex:1;height:100%;overflow:auto;padding:24px 28px;gap:0'):
        ui.label('PENDING REVIEWS').style(
            f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};margin-bottom:12px')
        with ui.grid(columns=3).style('gap:14px;margin-bottom:28px;width:100%'):
            render_staging()

        ui.label('PIPELINE HISTORY').style(
            f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};margin-bottom:12px')
        with ui.grid(columns=3).style('gap:14px;width:100%'):
            render_history()

    ui.timer(0.05, reload, once=True)
