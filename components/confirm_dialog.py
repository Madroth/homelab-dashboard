from typing import Callable, Optional

from nicegui import ui

from components import theme
from components.page_dialog import page_dialog


async def confirm(title: str, message: str, *, confirm_label: str = 'Confirm',
                   danger: bool = False) -> bool:
    with page_dialog() as dialog, ui.card().style(
            f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:12px;padding:22px'):
        ui.label(title).style(f'font-size:15px;font-weight:700;color:{theme.TEXT}')
        ui.label(message).style(f'font-size:12.5px;color:{theme.TEXT_MUTED};margin-bottom:14px')
        with ui.row().classes('justify-end w-full').style('gap:10px'):
            ui.button('Cancel', on_click=lambda: dialog.submit(False)).mark('confirm-dialog-cancel').props(
                'flat').style(f'color:{theme.TEXT_MUTED}')
            ui.button(confirm_label, on_click=lambda: dialog.submit(True)).mark('confirm-dialog-confirm').style(
                f'background:{theme.RED if danger else theme.ACCENT};'
                f'color:{theme.BG};font-weight:700')
    result = await dialog
    return bool(result)
