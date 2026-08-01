from typing import Callable

from nicegui import ui

from components import theme
from services import intake, intake_state, mods

# Each item: (key, icon, label, external_url). key=None + external_url=None -> disabled
# placeholder (Containers/Network). key=None + external_url set -> opens in a new tab.
# key set -> a real tab, clickable via on_select(key).
NAV_GROUPS = [
    ('WORKSPACE', [
        ('home', 'fa-solid fa-gauge-high', 'Dashboard', None),
        ('intake', 'fa-solid fa-inbox', 'Article Intake', None),
        ('mods', 'fa-solid fa-cubes', 'Mod Pipeline', None),
        ('media', 'fa-solid fa-photo-film', 'Media Curator', None),
    ]),
    ('INFRASTRUCTURE', [
        ('system', 'fa-solid fa-heart-pulse', 'System Status', None),
        (None, 'fa-solid fa-boxes-stacked', 'Containers', None),
        (None, 'fa-solid fa-network-wired', 'Network', None),
        ('settings', 'fa-solid fa-gear', 'Settings', None),
    ]),
    ('SERVICES', [
        (None, 'fa-solid fa-gamepad', 'Crafty Controller', 'https://100.87.245.107:8443'),
        (None, 'fa-solid fa-diagram-project', 'Plane', 'http://100.87.245.107'),
        (None, 'fa-solid fa-chart-line', 'Freqtrade', 'http://100.87.245.107:8082'),
    ]),
]

NAV_FLAT = [item for _, items in NAV_GROUPS for item in items]


def _unread_intake_count() -> int:
    """Mirrors the pending-mods badge's synchronous-call style (no run.io_bound --
    list_articles() is directory-signature-cached and all_article_states() is a plain
    JSON read, both cheap enough to call directly from a render function)."""
    workflow = intake_state.all_article_states()
    count = 0
    for a in intake.list_articles():
        if a['is_duplicate']:
            continue
        wf = workflow.get(a['id'], {})
        if wf.get('archived'):
            continue
        if not wf.get('read'):
            count += 1
    return count


@ui.refreshable
def build(active: str, on_select: Callable[[str], None], nav_open: bool = True,
          on_toggle_nav: Callable[[], None] = lambda: None):
    pending_mods = len(mods.get_staging())
    unread_intake = _unread_intake_count()
    badges = {'mods': pending_mods, 'intake': unread_intake}

    if not nav_open:
        with ui.column().classes('h-full items-center no-wrap').style(
                f'width:48px;background:{theme.SIDEBAR_BG};border-right:1px solid {theme.BORDER};'
                f'padding:14px 0;gap:14px'):
            ui.icon('fa-solid fa-angles-right').classes('cursor-pointer').style(
                f'font-size:12px;color:{theme.TEXT_DIM}').on('click', lambda: on_toggle_nav())
            for key, icon, label, url in NAV_FLAT:
                is_active = key == active
                with ui.element('div').classes('cursor-pointer').style(
                        'position:relative'
                ).on('click', (lambda _, u=url: ui.navigate.to(u, new_tab=True)) if url else
                     (lambda _, k=key: on_select(k)) if key else (lambda _: None)):
                    ui.icon(icon).style(
                        f'font-size:13px;color:{theme.ACCENT if is_active else theme.TEXT_MUTED}'
                    ).tooltip(label)
                    if badges.get(key):
                        ui.label(str(badges[key])).style(
                            f'position:absolute;top:-4px;right:-6px;font-size:8.5px;font-weight:800;'
                            f'color:{theme.BG};background:{theme.AMBER};border-radius:8px;padding:0 4px')
        return

    with ui.column().classes('h-full justify-between no-wrap').style(
            f'width:176px;background:{theme.SIDEBAR_BG};'
            f'border-right:1px solid {theme.BORDER};padding:0;gap:0'):

        with ui.column().classes('w-full').style('gap:0'):
            with ui.row().classes('items-center no-wrap').style('padding:16px 14px 14px;gap:9px'):
                with ui.element('div').style(
                        f'width:26px;height:26px;border-radius:7px;background:rgba(165,180,252,0.14);'
                        f'display:flex;align-items:center;justify-content:center;color:{theme.ACCENT};flex:none'):
                    ui.icon('fa-solid fa-server').style('font-size:12px')
                ui.label('OmegaLab').style('font-weight:700;font-size:13px;flex:1')
                ui.icon('fa-solid fa-angles-left').classes('cursor-pointer').style(
                    f'font-size:10px;color:{theme.TEXT_DIM}').on('click', lambda: on_toggle_nav())

            with ui.column().classes('nq-custom-scroll').style('gap:0;padding:4px 8px;width:100%;overflow:auto'):
                for group_label, items in NAV_GROUPS:
                    with ui.column().style('gap:1px;margin-bottom:8px;width:100%'):
                        ui.label(group_label).style(
                            f'font-size:9px;font-weight:700;letter-spacing:0.6px;color:{theme.TEXT_DIM};'
                            f'padding:6px 9px 4px')
                        for key, icon, label, url in items:
                            disabled = key is None and url is None
                            is_active = key == active
                            handler = ((lambda _, u=url: ui.navigate.to(u, new_tab=True)) if url else
                                       (lambda _, k=key: on_select(k)) if key else None)
                            classes = 'nq-nav-item items-center no-wrap' + (
                                ' nq-disabled' if disabled else ' cursor-pointer nq-active' if is_active
                                else ' cursor-pointer')
                            row = ui.row().classes(classes).style(
                                f'padding:7px 9px;border-radius:7px;font-size:12px;font-weight:500;gap:9px;'
                                f'width:100%;cursor:{"not-allowed" if disabled else "pointer"};'
                                f'color:{theme.TEXT_DISABLED if disabled else theme.TEXT if is_active else theme.TEXT_MUTED}')
                            with row:
                                ui.icon(icon).style('width:13px;font-size:11px')
                                ui.label(label).style('flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                                if badges.get(key):
                                    ui.label(str(badges[key])).style(
                                        f'font-size:9.5px;font-weight:700;color:{theme.BG};background:{theme.AMBER};'
                                        f'border-radius:9px;padding:1px 6px')
                                if url:
                                    ui.icon('fa-solid fa-arrow-up-right-from-square').style(
                                        f'font-size:8px;color:{theme.TEXT_DIM}')
                            if handler:
                                row.on('click', handler)

        with ui.row().classes('items-center no-wrap').style(
                f'padding:12px 14px 16px;gap:8px;border-top:1px solid {theme.BORDER};width:100%'):
            ui.element('div').style(
                f'width:7px;height:7px;border-radius:50%;background:{theme.GREEN};'
                f'animation:omegaPulse 2s infinite')
            ui.label('System Operational').style(f'font-size:11px;color:{theme.TEXT_MUTED};font-weight:500')
