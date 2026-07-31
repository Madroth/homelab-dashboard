from nicegui import run, ui

from components import ai_context, theme
from components.util import client_alive
from services import system


def _container_color(status_text: str) -> str:
    s = status_text.lower()
    if 'exited' in s or 'unhealthy' in s:
        return theme.RED
    if 'health: starting' in s or 'waiting' in s:
        return theme.AMBER
    return theme.GREEN


def build():
    state = {'status': None, 'logs': []}

    @ui.refreshable
    def render_defcon():
        defcon = (state['status'] or {}).get('defcon') or []
        if not defcon:
            return
        with ui.column().style(
                f'background:rgba(243,139,168,0.15);border:1px solid {theme.RED};border-radius:10px;'
                f'padding:16px;margin-bottom:24px;color:{theme.RED};font-weight:600;font-size:13.5px;width:100%'):
            for msg in defcon:
                with ui.row().classes('items-center no-wrap').style('gap:8px'):
                    ui.icon('fa-solid fa-triangle-exclamation')
                    ui.label(msg)

    @ui.refreshable
    def render_containers():
        containers = (state['status'] or {}).get('containers') or []
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

    async def refresh_status():
        status = await run.io_bound(system.get_status)
        if status is None:
            return
        if client_alive():
            state['status'] = status
            render_defcon.refresh()
            render_containers.refresh()
            render_metrics.refresh()

    async def refresh_logs():
        logs = await run.io_bound(system.get_logs)
        if logs is None:
            return
        if client_alive():
            state['logs'] = logs
            render_logs.refresh()

    def get_context_summary():
        status = state['status'] or {}
        containers = status.get('containers') or []
        unhealthy = [c for c in containers if _container_color(c.get('Status', '')) != theme.GREEN]
        lines = [f"Viewing System Status. {len(containers)} container(s), {len(unhealthy)} unhealthy/starting."]
        lines += [f"- {c.get('Names', '')}: {c.get('Status', '')}" for c in unhealthy]
        defcon = status.get('defcon') or []
        if defcon:
            lines.append("DEFCON alerts: " + "; ".join(defcon))
        return '\n'.join(lines)

    def get_context_card():
        status = state['status'] or {}
        containers = status.get('containers') or []
        unhealthy = [c for c in containers if _container_color(c.get('Status', '')) != theme.GREEN]
        defcon = status.get('defcon') or []
        pills = [f'{len(containers)} containers', f'{len(unhealthy)} unhealthy']
        focus = '; '.join(defcon) if defcon else 'All systems normal.'
        return {'icon': 'fa-solid fa-heart-pulse', 'tab': 'System Status', 'pills': pills, 'focus': focus}

    ai_context.register('system', get_context_summary)
    ai_context.register_card('system', get_context_card)

    with ui.column().style('flex:1;height:100%;overflow:auto;padding:24px 28px;gap:0'):
        render_defcon()

        ui.label('STACK HEALTH').style(
            f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};margin-bottom:12px')
        render_containers()

        ui.label('RESOURCES & METRICS').style(
            f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM};'
            f'margin:28px 0 12px')
        render_metrics()

        with ui.row().classes('items-center no-wrap').style('margin:28px 0 12px;gap:10px'):
            ui.label('DAEMON LOG (LAST 100 LINES)').style(
                f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM}')
            ui.button(icon='refresh', on_click=refresh_logs).props('flat dense').style(
                f'color:{theme.TEXT_MUTED}')
        render_logs()

    ui.timer(0.05, refresh_status, once=True)
    ui.timer(0.05, refresh_logs, once=True)
    ui.timer(15.0, refresh_status)
