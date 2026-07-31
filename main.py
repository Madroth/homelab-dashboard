from fastapi import Request
from nicegui import ui

from components import layout


@ui.page('/')
def index(request: Request):
    layout.build(request)


if __name__ in {'__main__', '__mp_main__'}:
    # Default reconnect_timeout is 3.0s (-> ~4s ping interval, ~2s ping timeout) -- far too
    # tight for a real client left open for hours: any brief hiccup (background-tab
    # throttling, a slow event-loop tick, a moment of thread-pool contention) exceeds it
    # and the server fully deletes the client instead of letting it gracefully reconnect,
    # which is what "Connection lost" repeatedly showed. 30s gives real margin.
    ui.run(host='0.0.0.0', port=8085, reload=False, title='OmegaLab Dashboard', reconnect_timeout=30.0)
