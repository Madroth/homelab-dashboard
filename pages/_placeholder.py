from nicegui import ui

from components import theme


def build(title: str):
    with ui.column().classes('items-center justify-center').style(
            f'flex:1;height:100%;gap:10px;color:{theme.TEXT_DISABLED}'):
        ui.icon('fa-solid fa-hammer').style('font-size:24px')
        ui.label(f'{title} — not yet ported').style('font-size:13.5px;font-weight:500')
        ui.label('Still served by the legacy app on :8085').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')
