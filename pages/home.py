from typing import Callable

from nicegui import run, ui

from components import ai_context, live_state, theme
from components.util import client_alive
from services import intake, media, minecraft, mods, system


def _fmt_time(t: str) -> str:
    return (t or '')[:19].replace('T', ' ')


def _schedule(fn):
    ui.timer(0.01, fn, once=True)


@ui.refreshable
def _minecraft_card(status: dict):
    with ui.column().style(
            f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;padding:16px;gap:4px'):
        with ui.row().classes('items-center no-wrap').style(
                f'color:{theme.GREEN};font-size:11.5px;font-weight:700;margin-bottom:6px;gap:8px'):
            ui.icon('fa-solid fa-gamepad')
            ui.label('MINECRAFT SERVER')
        if status.get('online'):
            ui.label(f"{status['players']} / {status['max_players']} players").style(
                f'font-size:20px;font-weight:700;color:{theme.TEXT}')
            ui.label(status['version']).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')
        else:
            ui.label('Offline').style(f'font-size:20px;font-weight:700;color:{theme.RED}')
            ui.label(status.get('error', 'unreachable')).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')


def build(on_navigate: Callable[[str], None]):
    state = {
        'minecraft': {'online': False, 'error': 'checking...'},
        'staging': [],
        'mod_map': {},
        'media_queue': [],
        'system_status': {},
        'articles': [],
        'intake_queue': [],
    }

    def _media_review_count():
        return len([i for i in state['media_queue']
                    if i.get('needs_intervention') and i.get('status') != 'approved'])

    def _recent_activity():
        recent = []
        for mod_name, mod in state['mod_map'].items():
            for h in mod.get('history') or []:
                if h.get('decision') == 'approved' and h.get('deployed_at'):
                    recent.append({'text': f'Approved {mod_name}', 'time': h['deployed_at'],
                                    'icon': 'fa-solid fa-cube', 'color': theme.GREEN})
        for item in state['media_queue']:
            if item.get('status') == 'approved':
                recent.append({'text': f"Auto-sorted: {item['proposed_title']}", 'time': item.get('created_at', ''),
                                'icon': 'fa-solid fa-film', 'color': theme.ACCENT})
        recent.sort(key=lambda e: e['time'], reverse=True)
        return recent[:5]

    @ui.refreshable
    def render_attention():
        staging_count = len(state['staging'])
        review_count = _media_review_count()
        alerts = (state['system_status'] or {}).get('defcon') or []

        chips = []
        if staging_count:
            chips.append(('fa-solid fa-cubes', theme.AMBER, staging_count,
                           f"mod{'s' if staging_count != 1 else ''} pending review", 'mods'))
        if review_count:
            chips.append(('fa-solid fa-film', '#cba6f7', review_count,
                           f"media item{'s' if review_count != 1 else ''} need review", 'media'))
        if alerts:
            chips.append(('fa-solid fa-heart-pulse', theme.RED, len(alerts),
                           f"system alert{'s' if len(alerts) != 1 else ''}", 'system'))

        if not chips:
            with ui.row().classes('items-center no-wrap').style(
                    'background:rgba(166,227,161,0.1);border:1px solid rgba(166,227,161,0.3);'
                    'border-radius:10px;padding:10px 14px;gap:9px'):
                ui.icon('fa-solid fa-circle-check').style(f'color:{theme.GREEN};font-size:13px')
                ui.label('All clear — nothing needs review').style(
                    f'font-size:12.5px;color:#c2c6d6;font-weight:600')
            return

        for icon, color, count, label, target in chips:
            with ui.row().classes('items-center no-wrap cursor-pointer').style(
                    f'background:rgba(255,255,255,0.04);border:1px solid {color}55;border-radius:10px;'
                    f'padding:10px 14px;gap:9px'
            ).on('click', lambda _, t=target: on_navigate(t)):
                ui.icon(icon).style(f'color:{color};font-size:13px')
                ui.label(str(count)).style(f'font-size:13px;font-weight:600;color:{theme.TEXT}')
                ui.label(label).style('font-size:12.5px;color:#c2c6d6')
                ui.icon('fa-solid fa-arrow-right').style(f'font-size:10px;color:{color}')

    @ui.refreshable
    def render_cards():
        with ui.column().style(
                f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;'
                f'padding:16px;gap:4px;cursor:pointer'
        ).on('click', lambda: on_navigate('intake')):
            with ui.row().classes('items-center no-wrap').style(
                    f'color:{theme.ACCENT};font-size:11.5px;font-weight:700;margin-bottom:6px;gap:8px'):
                ui.icon('fa-solid fa-newspaper')
                ui.label('ARTICLE INTAKE')
            ui.label(f"{len(state['articles'])} articles").style(
                f'font-size:20px;font-weight:700;color:{theme.TEXT}')
            processing = len([q for q in state['intake_queue'] if q.get('status') in ('pending', 'processing')])
            if processing:
                with ui.row().classes('items-center no-wrap').style(f'gap:6px;color:{theme.AMBER};font-size:11.5px'):
                    ui.element('div').style(
                        f'width:6px;height:6px;border-radius:50%;background:{theme.AMBER};'
                        f'animation:omegaPulseAmber 2s infinite')
                    ui.label(f'{processing} processing now')
            else:
                ui.label('Up to date').style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')

        with ui.column().style(
                f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;'
                f'padding:16px;gap:4px;cursor:pointer'
        ).on('click', lambda: on_navigate('mods')):
            with ui.row().classes('items-center no-wrap').style(
                    f'color:{theme.AMBER};font-size:11.5px;font-weight:700;margin-bottom:6px;gap:8px'):
                ui.icon('fa-solid fa-cubes')
                ui.label('MOD PIPELINE')
            staging = state['staging']
            ui.label(f'{len(staging)} pending review').style(f'font-size:20px;font-weight:700;color:{theme.TEXT}')
            names = ', '.join((s.get('meta') or {}).get('name', s['id']) for s in staging[:3])
            ui.label(names or 'Nothing pending').style(
                f'font-size:11.5px;color:{theme.TEXT_MUTED};overflow:hidden;text-overflow:ellipsis;white-space:nowrap')

        with ui.column().style(
                f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;'
                f'padding:16px;gap:4px;cursor:pointer'
        ).on('click', lambda: on_navigate('media')):
            with ui.row().classes('items-center no-wrap').style(
                    'color:#cba6f7;font-size:11.5px;font-weight:700;margin-bottom:6px;gap:8px'):
                ui.icon('fa-solid fa-film')
                ui.label('MEDIA CURATOR')
            ui.label(f"{len(state['media_queue'])} in queue").style(
                f'font-size:20px;font-weight:700;color:{theme.TEXT}')
            review_count = _media_review_count()
            ui.label(f'{review_count} need review' if review_count else 'Nothing pending').style(
                f'font-size:11.5px;color:{theme.RED if review_count else theme.TEXT_MUTED}')

        with ui.column().style(
                f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;'
                f'padding:16px;gap:4px;cursor:pointer'
        ).on('click', lambda: on_navigate('system')):
            with ui.row().classes('items-center no-wrap').style(
                    f'color:{theme.GREEN};font-size:11.5px;font-weight:700;margin-bottom:6px;gap:8px'):
                ui.icon('fa-solid fa-heart-pulse')
                ui.label('SYSTEM STATUS')
            disk = (state['system_status'] or {}).get('disk') or {}
            alerts = (state['system_status'] or {}).get('defcon') or []
            if disk.get('total'):
                ui.label(f"{disk['free'] / 1073741824:.1f} GB free").style(
                    f'font-size:20px;font-weight:700;color:{theme.TEXT}')
            else:
                ui.label('Unavailable').style(f'font-size:20px;font-weight:700;color:{theme.TEXT}')
            if alerts:
                ui.label(f'{len(alerts)} alert(s)').style(f'font-size:11.5px;color:{theme.RED}')
            else:
                ui.label('All systems normal').style(f'font-size:11.5px;color:{theme.GREEN}')

        with ui.column().style(
                f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};border-radius:11px;padding:16px;gap:4px'):
            with ui.row().classes('items-center no-wrap').style(
                    f'color:{theme.TEXT_MUTED};font-size:11.5px;font-weight:700;margin-bottom:6px;gap:8px'):
                ui.icon('fa-solid fa-clock-rotate-left')
                ui.label('RECENT ACTIVITY')
            recent = _recent_activity()
            if not recent:
                ui.label('No recent activity.').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')
            for ev in recent:
                with ui.row().classes('items-center no-wrap').style(
                        f'gap:7px;padding:4px 0;border-top:1px solid rgba(255,255,255,0.05);font-size:11.5px;width:100%'):
                    ui.icon(ev['icon']).style(f'color:{ev["color"]};font-size:9px')
                    ui.label(ev['text']).style(
                        'color:#c2c6d6;flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                    ui.label(_fmt_time(ev['time'])).style(f'color:{theme.TEXT_DIM}')

        for icon, label in [('fa-solid fa-boxes-stacked', 'Containers'), ('fa-solid fa-network-wired', 'Network')]:
            with ui.column().classes('items-center justify-center').style(
                    f'border:1.5px dashed rgba(255,255,255,0.12);border-radius:11px;padding:16px;'
                    f'gap:7px;color:{theme.TEXT_DISABLED};min-height:104px'):
                ui.icon(icon).style('font-size:16px')
                ui.label(label).style('font-size:11.5px;font-weight:500')

    async def _refresh_minecraft():
        status = await run.io_bound(minecraft.get_status)
        if client_alive():
            state['minecraft'] = status
            _minecraft_card.refresh(status)

    async def reload_all():
        result = await run.io_bound(
            lambda: (
                mods.get_staging(), mods.get_mods(), media.get_queue(),
                system.get_status(), intake.list_articles(), intake.get_queue(),
            ))
        if result is None:
            return
        staging, mod_map, media_queue, sys_status, articles, intake_queue = result
        if client_alive():
            state['staging'] = staging
            state['mod_map'] = mod_map
            state['media_queue'] = media_queue
            state['system_status'] = sys_status
            state['articles'] = articles
            state['intake_queue'] = intake_queue
            render_attention.refresh()
            render_cards.refresh()

    def get_context_summary():
        staging_count = len(state['staging'])
        review_count = _media_review_count()
        alerts = (state['system_status'] or {}).get('defcon') or []
        return (f"Viewing the Dashboard home tab. {staging_count} mod(s) pending review, "
                f"{review_count} media item(s) need review, {len(alerts)} system alert(s).")

    def get_context_card():
        staging_count = len(state['staging'])
        review_count = _media_review_count()
        alerts = (state['system_status'] or {}).get('defcon') or []
        pills = [f'{staging_count} mods pending', f'{review_count} media need review']
        if alerts:
            pills.append(f'{len(alerts)} alerts')
        focus = 'Nothing needs attention right now.' if not (staging_count or review_count or alerts) \
            else 'Ask me to triage or act on anything outstanding.'
        return {'icon': 'fa-solid fa-gauge-high', 'tab': 'Dashboard', 'pills': pills, 'focus': focus}

    ai_context.register('home', get_context_summary)
    ai_context.register_card('home', get_context_card)
    live_state.register('home', lambda: _schedule(reload_all))

    with ui.column().classes('nq-custom-scroll').style('flex:1;height:100%;overflow:auto;padding:24px;gap:0'):
        ui.label('What needs your attention').style(f'font-size:19px;font-weight:700;margin-bottom:3px')
        ui.label('A cross-tab overview of your homelab').style(
            f'font-size:12.5px;color:{theme.TEXT_MUTED};margin-bottom:18px')

        with ui.row().style('flex-wrap:wrap;gap:10px;margin-bottom:22px'):
            render_attention()

        with ui.grid(columns=3).style('gap:14px;width:100%'):
            _minecraft_card(state['minecraft'])
            render_cards()

    ui.timer(10.0, _refresh_minecraft)
    ui.timer(0.1, _refresh_minecraft, once=True)
    ui.timer(15.0, reload_all)
    ui.timer(0.1, reload_all, once=True)
