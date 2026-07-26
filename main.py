from fastapi import Request
from nicegui import ui

from components import layout


@ui.page('/')
def index(request: Request):
    layout.build(request)


if __name__ in {'__main__', '__mp_main__'}:
    ui.run(host='0.0.0.0', port=8085, reload=False, title='OmegaLab Dashboard')
