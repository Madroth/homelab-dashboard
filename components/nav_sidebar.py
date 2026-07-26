from typing import Callable

from nicegui import ui

from components import theme
from services import mods

NAV_ITEMS = [
    ('home', 'fa-solid fa-gauge-high', 'Dashboard'),
    ('intake', 'fa-solid fa-newspaper', 'Article Intake'),
    ('mods', 'fa-solid fa-cubes', 'Mod Pipeline'),
    ('media', 'fa-solid fa-film', 'Media Curator'),
    ('settings', 'fa-solid fa-gear', 'Settings'),
    ('system', 'fa-solid fa-heart-pulse', 'System Status'),
]

DISABLED_ITEMS = [
    ('fa-solid fa-boxes-stacked', 'Containers'),
    ('fa-solid fa-network-wired', 'Network'),
]

QUICK_LINKS = [
    ('fa-solid fa-cube', 'Crafty Controller', 'https://100.87.245.107:8443'),
    ('fa-solid fa-paper-plane', 'Plane', 'http://100.87.245.107'),
    ('fa-solid fa-chart-line', 'Freqtrade', 'http://100.87.245.107:8082'),
]


@ui.refreshable
def build(active: str, on_select: Callable[[str], None]):
    with ui.column().classes('h-full justify-between no-wrap').style(
            f'width:212px;background:{theme.SIDEBAR_BG};'
            f'border-right:1px solid {theme.BORDER};padding:0;gap:0'):

        with ui.column().classes('w-full').style('gap:0'):
            with ui.row().classes('items-center no-wrap').style('padding:20px 18px 16px;gap:9px'):
                with ui.element('div').style(
                        f'width:30px;height:30px;border-radius:8px;background:rgba(165,180,252,0.14);'
                        f'display:flex;align-items:center;justify-content:center;color:{theme.ACCENT}'):
                    ui.icon('fa-solid fa-server').style('font-size:14px')
                ui.label('OmegaLab').style('font-weight:700;font-size:14px')

            pending_mods = len(mods.get_staging())

            with ui.column().style('gap:1px;padding:6px 10px;width:100%'):
                for key, icon, label in NAV_ITEMS:
                    is_active = key == active
                    classes = 'nq-nav-item items-center no-wrap cursor-pointer' + (' nq-active' if is_active else '')
                    with ui.row().classes(classes).style(
                            f'padding:8px 10px;border-radius:7px;font-size:12.5px;font-weight:500;'
                            f'color:{theme.TEXT if is_active else theme.TEXT_MUTED};gap:10px;width:100%'
                    ).on('click', lambda _, k=key: on_select(k)):
                        ui.icon(icon).style('width:14px;font-size:12px')
                        ui.label(label).style('flex:1')
                        if key == 'mods' and pending_mods:
                            ui.label(str(pending_mods)).style(
                                f'background:{theme.AMBER};color:{theme.BG};font-size:10px;font-weight:800;'
                                f'border-radius:9px;padding:1px 6px')

                for icon, label in DISABLED_ITEMS:
                    with ui.row().classes('nq-nav-item nq-disabled items-center no-wrap').style(
                            f'padding:8px 10px;border-radius:7px;font-size:12.5px;font-weight:500;'
                            f'cursor:not-allowed;color:{theme.TEXT_DISABLED};gap:10px;width:100%'):
                        ui.icon(icon).style('width:14px;font-size:12px')
                        ui.label(label)

            with ui.column().style('padding:12px 18px;width:100%;gap:10px'):
                for icon, label, url in QUICK_LINKS:
                    with ui.row().classes('nq-nav-btn-hover items-center no-wrap cursor-pointer').style(
                            f'border:1px solid rgba(165,180,252,0.3);border-radius:8px;padding:9px 10px;'
                            f'color:{theme.ACCENT};font-size:12px;font-weight:600;width:100%'
                    ).on('click', lambda _, u=url: ui.navigate.to(u, new_tab=True)):
                        ui.icon(icon)
                        ui.label(label).style('flex:1')
                        ui.icon('fa-solid fa-arrow-up-right-from-square').style('font-size:9px')

        with ui.row().classes('items-center no-wrap').style(
                f'padding:14px 18px 18px;gap:8px;border-top:1px solid {theme.BORDER};width:100%'):
            ui.element('div').style(
                f'width:7px;height:7px;border-radius:50%;background:{theme.GREEN};'
                f'animation:omegaPulse 2s infinite')
            ui.label('System Operational').style(f'font-size:11.5px;color:{theme.TEXT_MUTED};font-weight:500')
