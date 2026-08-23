"""Lab Health — the dashboard's informational monitoring surface.

Absorbs the old System Status tab (Chris, 2026-08-22) rather than sitting beside it:
that page already rendered containers, disk and a log tail, and two pages showing
container health eventually disagree with each other. The tab key stays 'system' so
existing ?tab=system links and the ai_context registration keep working.

This page informs; it does not detect. Detection belongs to homelab-monitoring and
ends at a phone -- a page you have to be looking at cannot be a detector, which is
why Uptime Kuma ran here for months with a fine UI and zero monitors while seven
failures went unseen. What this page owes you instead is somewhere to look when you
already know something is wrong, and a way to get from "that is red" to the actual
error text and the command that tells you more.
"""
import re

from nicegui import run, ui

from components import ai_context, theme
from components.util import client_alive
from services import system

TOOLS = [
    ('fa-solid fa-heart-pulse', 'Uptime Kuma', 'http://100.87.245.107:3001', theme.GREEN),
    ('fa-solid fa-bars-staggered', 'Dozzle', 'http://100.87.245.107:8888', theme.ACCENT),
    ('fa-solid fa-bell', 'ntfy', 'http://100.87.245.107:5001', theme.PURPLE),
]

SEVERITY_COLORS = {'emergency': theme.RED, 'alert': theme.RED, 'critical': theme.RED,
                   'error': theme.RED, 'warning': theme.AMBER}


def _slug(text: str) -> str:
    """Marker-safe key. NiceGUI markers are matched as whole tokens, and a dot in a
    unit name (livescore.service) makes the element unfindable -- so the row markers
    the tests click are built from a sanitized slug, not the raw name."""
    return re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower() or 'unknown'


def _container_color(status_text: str) -> str:
    s = status_text.lower()
    if 'exited' in s or 'unhealthy' in s:
        return theme.RED
    if 'health: starting' in s or 'waiting' in s:
        return theme.AMBER
    return theme.GREEN


def _ago(ts: float) -> str:
    import time as _t
    if not ts:
        return 'unknown'
    delta = max(0, _t.time() - ts)
    if delta < 90:
        return f'{int(delta)}s ago'
    if delta < 5400:
        return f'{int(delta // 60)}m ago'
    if delta < 172800:
        return f'{int(delta // 3600)}h ago'
    return f'{int(delta // 86400)}d ago'


def _clock(ts: float) -> str:
    import time as _t
    return _t.strftime('%H:%M:%S', _t.localtime(ts)) if ts else '--:--:--'


def build():
    state = {'status': None, 'logs': [], 'errors': None, 'units': None,
             'status_error': None}

    # ---------- shared chrome ----------

    def _section_label(text: str, top: str = '28px'):
        ui.label(text).style(
            f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};'
            f'margin:{top} 0 12px')

    def _unknown_box(message: str):
        """The load-bearing visual: a dashed, muted panel that can never be mistaken
        for a healthy one. 'Could not determine' is a third outcome, not a quiet
        version of 'fine' -- reporting an unavailable source as an empty list is
        exactly how a downed NAS looked healthy for three days."""
        with ui.row().classes('items-center no-wrap').style(
                f'gap:10px;padding:13px 15px;border-radius:9px;width:100%;'
                f'border:1px dashed rgba(147,153,178,0.5);background:rgba(255,255,255,0.02)'):
            ui.icon('fa-solid fa-circle-question').style(f'color:{theme.TEXT_MUTED};font-size:13px')
            ui.label(message).style(f'font-size:11.5px;color:{theme.TEXT_MUTED};line-height:1.5')

    def _copy(text: str, label: str = 'Copy'):
        def do_copy():
            ui.clipboard.write(text)
            ui.notify('Copied', type='positive')
        with ui.row().classes('items-center no-wrap cursor-pointer').style(
                f'gap:6px;padding:5px 10px;border-radius:6px;background:{theme.ACCENT_TINT};'
                f'color:{theme.ACCENT};font-size:10.5px;font-weight:600').on('click', do_copy):
            ui.icon('fa-solid fa-clone').style('font-size:10px')
            ui.label(label)

    # ---------- verdict ----------

    @ui.refreshable
    def render_verdict():
        errors = state['errors']
        failed = [e for e in (errors or {}).get('entries', []) if e['source'] == 'unit']
        unreadable = errors is not None and not errors['ok']

        if errors is None:
            tone, title, detail = theme.TEXT_MUTED, 'Reading…', 'Collecting errors, units and containers.'
        elif unreadable:
            tone, title = theme.TEXT_MUTED, 'Cannot tell'
            detail = f"A source did not answer — {errors['error']}. What is shown is incomplete."
        elif failed:
            tone, title = theme.RED, 'Something is broken'
            names = ', '.join(u['origin'] for u in failed[:3])
            detail = f"{len(failed)} unit(s) in a failed state: {names}."
        elif errors['entries']:
            tone, title = theme.AMBER, 'Errors logged'
            detail = f"{len(errors['entries'])} distinct error(s) in the last 24h. Nothing is in a failed state."
        else:
            tone, title = theme.GREEN, 'Nothing is broken'
            detail = 'No failed units, and no errors logged in the last 24h.'

        dashed = tone == theme.TEXT_MUTED
        with ui.row().classes('items-center no-wrap').style(
                f'gap:16px;padding:18px 20px;border-radius:12px;width:100%;margin-bottom:4px;'
                + (f'border:1px dashed rgba(147,153,178,0.5);background:rgba(255,255,255,0.02)'
                   if dashed else
                   f'border:1px solid {tone};background:rgba(255,255,255,0.03)')):
            ui.icon('fa-solid fa-circle-question' if dashed else
                    'fa-solid fa-triangle-exclamation' if tone in (theme.RED, theme.AMBER) else
                    'fa-solid fa-circle-check').style(f'color:{tone};font-size:22px')
            with ui.column().style('gap:4px;min-width:0'):
                ui.label(title).style(f'font-size:18px;font-weight:800;color:{tone}')
                ui.label(detail).style(f'font-size:12.5px;color:{theme.TEXT_MUTED};line-height:1.5')
            ui.space()
            if state['errors']:
                with ui.column().style('gap:3px;align-items:flex-end;flex:none'):
                    ui.label('AS OF').style(
                        f'font-size:9.5px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                    ui.label(_clock(state['errors']['read_at'])).style(
                        f"font-size:12.5px;font-weight:600;color:{theme.TEXT};font-family:'JetBrains Mono',monospace")

    # ---------- errors ----------

    def show_error_detail(entry: dict):
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:12px;padding:20px;min-width:660px;max-width:840px'):
            color = SEVERITY_COLORS.get(entry['severity'], theme.TEXT_MUTED)
            with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                ui.icon('fa-solid fa-circle-exclamation').style(f'color:{color};font-size:14px')
                ui.label(entry['origin']).style(
                    f"font-size:14px;font-weight:700;color:{theme.TEXT};font-family:'JetBrains Mono',monospace")
                ui.label(entry['severity'].upper()).style(
                    f'font-size:9.5px;font-weight:700;letter-spacing:0.06em;color:{color};'
                    f'background:rgba(255,255,255,0.05);padding:3px 8px;border-radius:5px')
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')

            with ui.row().classes('items-center no-wrap').style('gap:16px;margin:4px 0 12px'):
                for label, value in [
                        ('SOURCE', entry['source']),
                        ('SEEN', f"{entry['count']}×" if entry['count'] > 1 else 'once'),
                        ('LAST', _ago(entry['at'])),
                        ('FIRST', _ago(entry.get('first_at', entry['at']))),
                ]:
                    with ui.column().style('gap:2px'):
                        ui.label(label).style(
                            f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                        ui.label(value).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')

            # Selectable, not a tooltip: the whole point is being able to read the
            # error and paste it somewhere. (Same complaint as intake's failed-queue
            # entries, 2026-08-04 -- solved once, here.)
            ui.label('MESSAGE').style(
                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
            ui.label(entry['message']).style(
                f"width:100%;background:rgba(0,0,0,0.28);border-radius:8px;padding:12px 14px;"
                f"font-family:'JetBrains Mono',monospace;font-size:11.5px;color:{theme.TEXT};"
                f"line-height:1.6;white-space:pre-wrap;word-break:break-word;user-select:text;"
                f"max-height:240px;overflow:auto")

            detail = entry.get('detail') or {}
            shown = {k: v for k, v in detail.items() if v}
            if shown:
                with ui.row().classes('items-center').style('gap:14px;flex-wrap:wrap;margin-top:4px'):
                    for k, v in shown.items():
                        ui.label(f'{k}: {v}').style(
                            f"font-size:10.5px;color:{theme.TEXT_DIM};font-family:'JetBrains Mono',monospace")

            probe = _investigate_command(entry)
            if probe:
                ui.label('INVESTIGATE').style(
                    f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM};margin-top:6px')
                with ui.row().classes('items-center no-wrap w-full').style(
                        f'gap:10px;background:rgba(0,0,0,0.28);border-radius:8px;padding:10px 12px'):
                    ui.label(probe).style(
                        f"flex:1;min-width:0;font-family:'JetBrains Mono',monospace;font-size:11px;"
                        f"color:{theme.TEXT_MUTED};user-select:text;overflow-x:auto;white-space:nowrap")
                    _copy(probe, 'Copy')

            with ui.row().classes('justify-end w-full').style('gap:10px;margin-top:14px'):
                _copy(entry['message'], 'Copy error')
        dialog.open()

    def _investigate_command(entry: dict) -> str | None:
        detail = entry.get('detail') or {}
        if entry['source'] == 'container' or detail.get('container'):
            name = detail.get('container') or entry['origin']
            return f'docker logs --tail 200 {name}'
        unit = detail.get('unit') or (entry['origin'] if entry['origin'].endswith('.service') else None)
        if unit:
            manager = detail.get('manager', 'user')
            return f'journalctl --{manager} -u {unit} -n 200 --no-pager'
        return None

    @ui.refreshable
    def render_errors():
        errors = state['errors']
        if errors is None:
            with ui.column().style('gap:8px;width:100%'):
                for _ in range(4):
                    ui.element('div').classes('nq-skel').style(
                        'height:44px;border-radius:9px;background:rgba(255,255,255,0.04);width:100%')
            return

        if errors['error']:
            _unknown_box(f"Some sources did not answer — {errors['error']}. "
                         f"The list below is incomplete; treat gaps as unknown, not as quiet.")

        if not errors['entries']:
            if errors['ok']:
                with ui.row().classes('items-center no-wrap').style(
                        f'gap:10px;padding:13px 15px;border-radius:9px;width:100%;'
                        f'background:{theme.CARD_BG};border:1px solid {theme.BORDER}'):
                    ui.icon('fa-solid fa-circle-check').style(f'color:{theme.GREEN};font-size:13px')
                    ui.label('No errors logged in the last 24 hours.').style(
                        f'font-size:11.5px;color:{theme.TEXT_MUTED}')
            return

        with ui.column().style('gap:6px;width:100%'):
            for entry in errors['entries'][:40]:
                color = SEVERITY_COLORS.get(entry['severity'], theme.TEXT_MUTED)
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:12px;padding:10px 14px;border-radius:9px;width:100%;'
                        f'background:{theme.CARD_BG};border:1px solid {theme.BORDER}'
                ).on('click', lambda _, e=entry: show_error_detail(e)).mark(
                        f"error-row-{_slug(entry['origin'])}-{int(entry['at'])}"):
                    ui.element('div').style(
                        f'width:7px;height:7px;border-radius:50%;background:{color};flex:none')
                    ui.label(entry['origin']).style(
                        f"font-size:11.5px;font-weight:600;color:{theme.TEXT};flex:none;width:210px;"
                        f"font-family:'JetBrains Mono',monospace;overflow:hidden;text-overflow:ellipsis;"
                        f"white-space:nowrap")
                    ui.label(entry['message']).style(
                        f'flex:1;min-width:0;font-size:11.5px;color:{theme.TEXT_MUTED};'
                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                    if entry['count'] > 1:
                        ui.label(f"×{entry['count']}").style(
                            f'font-size:10px;font-weight:700;color:{theme.AMBER};background:rgba(249,201,124,0.12);'
                            f'padding:2px 7px;border-radius:5px;flex:none')
                    ui.label(_ago(entry['at'])).style(
                        f'font-size:10.5px;color:{theme.TEXT_DIM};flex:none;width:70px;text-align:right')

    # ---------- units ----------

    def show_unit_detail(unit: str, manager: str):
        detail = system.get_unit_detail(unit, manager)
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:12px;padding:20px;min-width:680px;max-width:880px'):
            with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                ui.label(unit).style(
                    f"font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace;color:{theme.TEXT}")
                ui.label(manager).style(
                    f'font-size:9.5px;font-weight:700;letter-spacing:0.06em;color:{theme.TEXT_MUTED};'
                    f'background:rgba(255,255,255,0.05);padding:3px 8px;border-radius:5px')
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')

            if not detail['ok']:
                _unknown_box(f'Could not read this unit — {detail["error"]}')
            else:
                props = detail['props']
                active = props.get('ActiveState', '')
                color = theme.RED if active == 'failed' else theme.GREEN if active == 'active' else theme.AMBER
                with ui.row().classes('items-center').style('gap:18px;flex-wrap:wrap;margin:6px 0 12px'):
                    for label, value, tone in [
                            ('STATE', f"{active}/{props.get('SubState', '')}", color),
                            ('RESULT', props.get('Result', '—'), theme.TEXT_MUTED),
                            ('RESTARTS', props.get('NRestarts', '0'), theme.TEXT_MUTED),
                            ('LAST EXIT', props.get('ExecMainStatus', '—'), theme.TEXT_MUTED),
                    ]:
                        with ui.column().style('gap:2px'):
                            ui.label(label).style(
                                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                            ui.label(str(value)).style(f'font-size:12px;font-weight:600;color:{tone}')
                if props.get('Description'):
                    ui.label(props['Description']).style(
                        f'font-size:11.5px;color:{theme.TEXT_MUTED};margin-bottom:6px')

                ui.label('RECENT LOG').style(
                    f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                if detail.get('log_error'):
                    _unknown_box(f'Could not read this unit\'s log — {detail["log_error"]}')
                elif detail['logs']:
                    ui.label('\n'.join(detail['logs'])).style(
                        f"width:100%;background:rgba(0,0,0,0.28);border-radius:8px;padding:12px 14px;"
                        f"font-family:'JetBrains Mono',monospace;font-size:10.5px;color:{theme.TEXT_MUTED};"
                        f"line-height:1.55;white-space:pre-wrap;word-break:break-word;user-select:text;"
                        f"max-height:280px;overflow:auto")
                else:
                    ui.label('No log entries.').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')

                cmd = f'journalctl --{manager} -u {unit} -n 200 --no-pager'
                with ui.row().classes('items-center no-wrap w-full').style(
                        f'gap:10px;background:rgba(0,0,0,0.28);border-radius:8px;padding:10px 12px;margin-top:10px'):
                    ui.label(cmd).style(
                        f"flex:1;min-width:0;font-family:'JetBrains Mono',monospace;font-size:11px;"
                        f"color:{theme.TEXT_MUTED};user-select:text;overflow-x:auto;white-space:nowrap")
                    _copy(cmd, 'Copy')
        dialog.open()

    @ui.refreshable
    def render_units():
        units = state['units']
        if units is None:
            ui.element('div').classes('nq-skel').style(
                'height:120px;border-radius:9px;background:rgba(255,255,255,0.04);width:100%')
            return
        if not units['ok']:
            _unknown_box(f'Could not list units — {units["error"]}')
            if not units['units']:
                return

        failed = [u for u in units['units'] if u['failed']]
        shown = failed + [u for u in units['units'] if not u['failed']][:14]
        with ui.column().style('gap:6px;width:100%'):
            for u in shown:
                color = theme.RED if u['failed'] else (
                    theme.GREEN if u['active'] == 'active' else theme.TEXT_DIM)
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:12px;padding:9px 14px;border-radius:9px;width:100%;background:{theme.CARD_BG};'
                        f'border:1px solid ' + (theme.RED if u['failed'] else theme.BORDER)
                ).on('click', lambda _, n=u['unit'], m=u['manager']: show_unit_detail(n, m)).mark(
                        f"unit-row-{_slug(u['unit'])}"):
                    ui.element('div').style(
                        f'width:7px;height:7px;border-radius:50%;background:{color};flex:none')
                    ui.label(u['unit']).style(
                        f"font-size:11.5px;font-weight:600;color:{theme.TEXT};flex:none;width:290px;"
                        f"font-family:'JetBrains Mono',monospace;overflow:hidden;text-overflow:ellipsis;"
                        f"white-space:nowrap")
                    ui.label(u['description']).style(
                        f'flex:1;min-width:0;font-size:11px;color:{theme.TEXT_MUTED};'
                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                    ui.label(f"{u['active']}/{u['sub']}").style(
                        f'font-size:10.5px;color:{color};flex:none;width:120px;text-align:right')
        if len(units['units']) > len(shown):
            ui.label(f"{len(units['units']) - len(shown)} more units not shown").style(
                f'font-size:10.5px;color:{theme.TEXT_DIM};margin-top:8px')

    # ---------- containers, metrics, logs (carried over from System Status) ----------

    @ui.refreshable
    def render_containers():
        status = state['status']
        if status is None:
            ui.element('div').classes('nq-skel').style(
                'height:90px;border-radius:9px;background:rgba(255,255,255,0.04);width:100%')
            return
        containers = status.get('containers') or []
        if status.get('containers_error'):
            _unknown_box(f"Could not read container state — {status['containers_error']}")
            return
        if not containers:
            with ui.row().classes('items-center no-wrap').style(
                    f'gap:10px;padding:13px 15px;border-radius:9px;width:100%;'
                    f'background:{theme.CARD_BG};border:1px solid {theme.BORDER}'):
                ui.icon('fa-solid fa-circle-check').style(f'color:{theme.GREEN};font-size:13px')
                ui.label('Docker is reachable and reports no containers.').style(
                    f'font-size:11.5px;color:{theme.TEXT_MUTED}')
            return
        with ui.grid(columns='repeat(auto-fill, minmax(200px, 1fr))').style('gap:14px;width:100%'):
            for c in containers:
                color = _container_color(c.get('Status', ''))
                with ui.column().style(
                        f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:9px;'
                        f'padding:12px;gap:6px'):
                    with ui.row().classes('items-center no-wrap').style('gap:8px'):
                        ui.icon('fa-solid fa-box').style(f'color:{color}')
                        ui.label(c.get('Names', '')).style(
                            f'font-weight:600;font-size:12.5px;color:{theme.TEXT}')
                    ui.label(c.get('Status', '')).style(
                        f'font-size:10.5px;color:{theme.TEXT_MUTED};overflow:hidden;text-overflow:ellipsis;'
                        f'white-space:nowrap;max-width:100%')

    @ui.refreshable
    def render_metrics():
        status = state['status'] or {}
        disk = status.get('disk', {})
        memory = status.get('memory', {})
        daemon_active = status.get('daemon_active', False)

        with ui.grid(columns=3).style('gap:14px;width:100%'):
            with ui.column().style(
                    f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;padding:16px'):
                with ui.row().classes('items-center no-wrap').style(
                        f'color:{theme.ACCENT};font-size:11.5px;font-weight:700;gap:8px;margin-bottom:10px'):
                    ui.icon('fa-solid fa-hard-drive')
                    ui.label('/MNT/MULTIMEDIA STORAGE')
                if disk.get('total'):
                    free_gb = disk['free'] / 1073741824
                    total_gb = disk['total'] / 1073741824
                    color = theme.RED if disk.get('free_pct', 100) < 10 else theme.TEXT
                    ui.label(f'{free_gb:.1f} GB Free').style(f'font-size:20px;font-weight:700;color:{color}')
                    ui.label(f'Out of {total_gb:.1f} GB Total').style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')
                elif disk.get('error'):
                    ui.label('NOT MOUNTED').style(f'font-size:20px;font-weight:700;color:{theme.RED}')
                    ui.label(disk['error']).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')
                else:
                    ui.label('Unavailable').style(f'font-size:20px;font-weight:700;color:{theme.TEXT}')

            with ui.column().style(
                    f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;padding:16px'):
                with ui.row().classes('items-center no-wrap').style(
                        f'color:{theme.AMBER};font-size:11.5px;font-weight:700;gap:8px;margin-bottom:10px'):
                    ui.icon('fa-solid fa-memory')
                    ui.label('PLEX MEMORY')
                ui.label(memory.get('plex', 'Unknown')).style(
                    f'font-size:20px;font-weight:700;color:{theme.TEXT}')
                ui.label('Hard Limit: 4.00GB').style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')

            with ui.column().style(
                    f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;padding:16px'):
                with ui.row().classes('items-center no-wrap').style(
                        f'color:{theme.GREEN};font-size:11.5px;font-weight:700;gap:8px;margin-bottom:10px'):
                    ui.icon('fa-solid fa-microchip')
                    ui.label('DAEMON STATUS')
                status_text = 'Active (Running)' if daemon_active else 'Failed / Stopped'
                status_color = theme.GREEN if daemon_active else theme.RED
                ui.label(status_text).style(f'font-size:20px;font-weight:700;color:{status_color}')
                ui.label('media-curator.service').style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')

    @ui.refreshable
    def render_logs():
        logs = state['logs']
        if not logs:
            ui.label('No log entries.').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')
            return
        ui.markdown('```\n' + ''.join(logs) + '\n```').classes('nq-markdown').style(
            'max-height:280px;overflow:auto;width:100%')

    # ---------- refreshers ----------

    async def refresh_status():
        status = await run.io_bound(system.get_status)
        if status is None:
            return
        if client_alive():
            state['status'] = status
            render_containers.refresh()
            render_metrics.refresh()

    async def refresh_logs():
        logs = await run.io_bound(system.get_logs)
        if logs is None:
            return
        if client_alive():
            state['logs'] = logs
            render_logs.refresh()

    async def refresh_errors():
        errors = await run.io_bound(system.get_errors)
        units = await run.io_bound(system.get_units, 'user')
        if errors is None or units is None:
            return
        if client_alive():
            state['errors'] = errors
            state['units'] = units
            render_errors.refresh()
            render_units.refresh()
            render_verdict.refresh()

    async def refresh_all():
        await refresh_errors()
        await refresh_status()

    # ---------- AI context ----------

    def get_context_summary():
        status = state['status'] or {}
        containers = status.get('containers') or []
        unhealthy = [c for c in containers if _container_color(c.get('Status', '')) != theme.GREEN]
        errors = state['errors'] or {}
        failed = [e for e in errors.get('entries', []) if e['source'] == 'unit']
        lines = [f"Viewing Lab Health. {len(containers)} container(s), {len(unhealthy)} unhealthy/starting. "
                 f"{len(failed)} failed unit(s), {len(errors.get('entries', []))} distinct error(s) in 24h."]
        lines += [f"- FAILED {e['origin']}" for e in failed]
        lines += [f"- {e['origin']}: {e['message'][:160]}" for e in errors.get('entries', [])[:10]
                  if e['source'] != 'unit']
        if errors.get('error'):
            lines.append(f"Some sources unreadable: {errors['error']}")
        return '\n'.join(lines)

    def get_context_card():
        status = state['status'] or {}
        containers = status.get('containers') or []
        unhealthy = [c for c in containers if _container_color(c.get('Status', '')) != theme.GREEN]
        errors = state['errors'] or {}
        failed = [e for e in errors.get('entries', []) if e['source'] == 'unit']
        pills = [f'{len(containers)} containers', f'{len(unhealthy)} unhealthy',
                 f'{len(failed)} failed units']
        if failed:
            focus = 'Failed: ' + ', '.join(e['origin'] for e in failed)
        elif errors.get('entries'):
            focus = f"{len(errors['entries'])} distinct error(s) in the last 24h."
        else:
            focus = 'No failed units and no errors logged.'
        return {'icon': 'fa-solid fa-heart-pulse', 'tab': 'Lab Health', 'pills': pills, 'focus': focus}

    ai_context.register('system', get_context_summary)
    ai_context.register_card('system', get_context_card)

    # ---------- layout ----------

    with ui.column().style('flex:1;height:100%;overflow:auto;padding:24px 28px;gap:0'):
        with ui.row().classes('items-center no-wrap w-full').style('gap:12px;margin-bottom:16px'):
            with ui.column().style('gap:2px'):
                ui.label('Lab Health').style(
                    f'font-size:19px;font-weight:800;letter-spacing:-0.02em;color:{theme.TEXT}')
                ui.label('Errors, units and containers — read live from this machine').style(
                    f'font-size:11.5px;color:{theme.TEXT_DIM}')
            ui.space()
            for icon, label, url, color in TOOLS:
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:7px;padding:7px 12px;border-radius:7px;background:{theme.CARD_BG};'
                        f'border:1px solid {theme.BORDER};flex:none'
                ).on('click', lambda _, u=url: ui.navigate.to(u, new_tab=True)).mark(f'tool-{_slug(label)}'):
                    ui.icon(icon).style(f'color:{color};font-size:11.5px')
                    ui.label(label).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')
            ui.button(icon='refresh', on_click=refresh_all).props('flat dense').style(
                f'color:{theme.TEXT_MUTED}').mark('lab-health-refresh')

        render_verdict()

        _section_label('ERRORS — LAST 24 HOURS', top='24px')
        render_errors()

        _section_label('UNITS')
        render_units()

        _section_label('STACK HEALTH')
        render_containers()

        _section_label('RESOURCES & METRICS')
        render_metrics()

        with ui.row().classes('items-center no-wrap').style('margin:28px 0 12px;gap:10px'):
            ui.label('DAEMON LOG (LAST 100 LINES)').style(
                f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM}')
            ui.button(icon='refresh', on_click=refresh_logs).props('flat dense').style(
                f'color:{theme.TEXT_MUTED}')
        render_logs()

    ui.timer(0.05, refresh_errors, once=True)
    ui.timer(0.05, refresh_status, once=True)
    ui.timer(0.05, refresh_logs, once=True)
    ui.timer(15.0, refresh_status)
    ui.timer(30.0, refresh_errors)
