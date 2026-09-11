"""Dialogs that outlive a refresh of whatever opened them.

NiceGUI deletes a `ui.dialog()` when an invisible canary element, placed wherever the
dialog was created, is garbage-collected. A dialog opened from a click handler is created
inside the clicked element's parent -- a queue row, an error-stream entry, a container
card -- and every page here rebuilds those on a poll. So the poll deleted whatever dialog
was open: Media Curator's Edit Title box vanished within five seconds mid-typing, its
Reject confirmation took the pending action with it, and the handler awaiting the answer
hung forever. Found 2026-09-11 when the media UI tests' long-standing flake was finally
captured (see test_media_fixes.py, "an open dialog survives the page's own poll").

page_dialog() anchors the canary to the page instead, and deletes the dialog once it has
closed -- otherwise every detail dialog ever opened would stay in the page, hidden, until
the tab closed.
"""
import asyncio

from nicegui import background_tasks, context, ui

CLOSE_TRANSITION_S = 0.5   # let Quasar's close animation finish before the element goes


def page_dialog() -> ui.dialog:
    """Use exactly where `ui.dialog()` was: `with page_dialog() as dialog, ui.card(): ...`"""
    with context.client.layout:
        anchor = ui.element()
        anchor.visible = False
    with anchor:
        dialog = ui.dialog()

    def _on_value_change(e):
        if not e.value:
            background_tasks.create(_discard(dialog, anchor), name='discard closed dialog')

    dialog.on_value_change(_on_value_change)
    return dialog


async def _discard(dialog: ui.dialog, anchor: ui.element) -> None:
    await asyncio.sleep(CLOSE_TRANSITION_S)
    if dialog.is_deleted or dialog.value:
        return   # already gone, or reopened in the meantime
    dialog.delete()
    if not anchor.is_deleted:
        anchor.delete()
