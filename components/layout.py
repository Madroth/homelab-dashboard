from fastapi import Request
from nicegui import ui

from components import ai_context, chat_sidebar, live_state, nav_sidebar, theme
from pages import home, intake, media, mods, settings, system

TAB_PAGES = {
    'home': home.build,
    'intake': intake.build,
    'mods': mods.build,
    'media': media.build,
    'settings': settings.build,
    'system': system.build,
}


def build(request: Request):
    theme.install()
    initial_tab = request.query_params.get('tab', 'intake')
    if initial_tab not in TAB_PAGES:
        initial_tab = 'intake'
    ai_context.set_active_tab(initial_tab)

    with ui.row().classes('no-wrap').style(
            f'width:100vw;height:100vh;margin:0;background:{theme.BG};overflow:hidden'):

        current_tab = {'key': initial_tab}

        def select(key: str):
            current_tab['key'] = key
            tab_panels.set_value(key)
            ui.run_javascript(f"history.replaceState(null, '', '?tab={key}')")
            nav_sidebar.build.refresh(key, select)
            ai_context.set_active_tab(key)

        nav_sidebar.build(initial_tab, select)
        live_state.register('nav_sidebar', lambda: nav_sidebar.build.refresh(current_tab['key'], select))

        with ui.column().style('flex:1;height:100%;min-width:0;gap:0'):
            with ui.row().classes('items-center no-wrap').style(
                    f'height:56px;flex:none;padding:0 24px;border-bottom:1px solid {theme.BORDER};gap:14px'):
                ui.space()
                with ui.element('div').classes('nq-nav-btn-hover cursor-pointer').style(
                        f'width:30px;height:30px;border-radius:8px;background:{theme.ACCENT_TINT};'
                        f'color:{theme.ACCENT};display:flex;align-items:center;justify-content:center'
                ) as ai_toggle_btn:
                    ui.icon('fa-solid fa-wand-magic-sparkles')
                with ui.element('div').style(
                        f'width:30px;height:30px;border-radius:50%;background:{theme.ACCENT};color:{theme.BG};'
                        f'display:flex;align-items:center;justify-content:center;font-weight:700;font-size:12px'):
                    ui.label('P')

            with ui.tab_panels(value=initial_tab).style('flex:1;min-height:0;width:100%') as tab_panels:
                for key, page_build in TAB_PAGES.items():
                    with ui.tab_panel(key).style('height:100%;padding:0;display:flex'):
                        if key == 'home':
                            page_build(select)
                        else:
                            page_build()

        toggle_chat = chat_sidebar.build()
        ai_toggle_btn.on('click', lambda: toggle_chat())
