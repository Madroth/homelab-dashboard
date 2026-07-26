from typing import Callable

from nicegui import run, ui

from components import ai_context, live_state, theme
from components.util import client_alive
from services import media, mods
from services.ai import chat as chat_service

MODELS = [('claude', 'Claude', theme.ACCENT), ('agy', 'Agy', theme.AMBER), ('local', 'Local', theme.GREEN)]

WELCOME_TEXT = ("Hi — I can see whatever tab you're on and act on it directly. "
                "Ask me anything, or try a suggestion below.")

TAB_SUGGESTIONS = {
    'home': ['What needs my attention today?', "What's new since I was last here?"],
    'intake': ['Summarize the top priority article', 'Any duplicates I should clear?'],
    'mods': ['Which mods are safe to approve?', 'Summarize the AI reviews'],
    'media': ['Approve everything that looks safe', "What's flagged for review?"],
    'system': ['Is anything unhealthy right now?', "What's using the most disk?"],
    'settings': ['What models are configured?', 'How do I set up Ollama?'],
}


def _synthesize_actions() -> list[dict]:
    """Contextual action chips derived directly from the active tab's live state -- not
    LLM-emitted. Keeps this consistent across Claude/Agy/Local without needing structured
    action-suggestion output from three different model APIs."""
    tab = ai_context.active_tab()
    actions = []
    if tab == 'mods':
        for item in mods.get_staging()[:3]:
            name = (item.get('meta') or {}).get('name', item['id'])
            sid = item['id']
            actions.append({'label': f'Approve {name}', 'danger': False,
                             'run': lambda sid=sid: mods.approve_mod(sid)})
    elif tab == 'media':
        queue = media.get_queue()
        pending = [i for i in queue if i['status'] != 'approved']
        safe = [i for i in pending if not i.get('needs_intervention')]
        if len(safe) >= 2:
            ids = [str(i['id']) for i in safe]
            actions.append({'label': 'Approve the safe items', 'danger': False,
                             'run': lambda ids=ids: media.bulk_action('approve', ids)})
        flagged = [i for i in pending if i.get('needs_intervention')]
        if flagged:
            fid = str(flagged[0]['id'])
            title = flagged[0]['proposed_title']
            actions.append({'label': f'Clear {title}', 'danger': True,
                             'run': lambda fid=fid: media.reject(fid)})
    return actions


def build() -> Callable[[], None]:
    state = {'history': [], 'open': False, 'model': 'claude', 'last_action_row': None}

    container = ui.column().style(
        f'width:384px;flex:none;background:{theme.SIDEBAR_BG};border-left:1px solid {theme.BORDER};'
        f'transition:margin-right 0.3s;margin-right:-384px;height:100%;gap:0')

    with container:
        with ui.row().classes('items-center no-wrap justify-between').style(
                f'height:56px;flex:none;padding:0 16px;border-bottom:1px solid {theme.BORDER};width:100%'):
            with ui.row().classes('items-center no-wrap').style(
                    f'gap:8px;color:{theme.ACCENT};font-weight:600;font-size:13px'):
                ui.icon('fa-solid fa-wand-magic-sparkles')
                ui.label('Assistant')
            close_btn = ui.element('div').classes('nq-nav-btn-hover cursor-pointer').style(
                f'width:26px;height:26px;border-radius:7px;display:flex;align-items:center;'
                f'justify-content:center;color:{theme.TEXT_DIM}')
            with close_btn:
                ui.icon('fa-solid fa-chevron-right').style('font-size:12px')

        model_row = ui.row().style(f'gap:3px;background:{theme.CARD_BG};border-radius:9px;padding:3px;margin:0 16px 12px')
        with model_row:
            model_buttons = {}
            for key, label, color in MODELS:
                active = key == state['model']
                btn = ui.row().classes('items-center justify-center cursor-pointer').style(
                        f'flex:1;padding:6px 0;border-radius:6px;font-size:11.5px;font-weight:600;'
                        f'background:{theme.ACCENT_TINT if active else "transparent"};'
                        f'color:{color if active else theme.TEXT_MUTED}')
                with btn:
                    ui.label(label)
                model_buttons[key] = btn

        card_container = ui.column().style(
            f'margin:0 16px 12px;background:{theme.CARD_BG};border-radius:11px;padding:12px 13px;'
            f'gap:0;animation:omegaGlow 3.5s ease-in-out infinite')

        suggestion_container = ui.row().style('gap:6px;flex-wrap:wrap;padding:0 16px 10px')

        history_container = ui.column().classes('nq-custom-scroll').style(
            'flex:1;overflow-y:auto;padding:16px;gap:14px;font-size:12.5px;width:100%')

        with ui.column().style(f'padding:12px 16px 16px;border-top:1px solid {theme.BORDER};width:100%'):
            with ui.row().classes('items-center no-wrap').style(
                    f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);border-radius:11px;'
                    f'padding:8px 10px;gap:9px;width:100%'):
                chat_input = ui.input(placeholder='Ask something...').props('borderless').style(
                    f'flex:1;color:{theme.TEXT};font-size:12.5px')
                send_btn = ui.element('div').classes('cursor-pointer').style(
                    f'width:28px;height:28px;border-radius:8px;background:{theme.ACCENT};color:{theme.BG};'
                    f'display:flex;align-items:center;justify-content:center;flex:none')
                with send_btn:
                    ui.icon('fa-solid fa-arrow-up').style('font-size:12px')

    def select_model(key: str):
        state['model'] = key
        for k, btn in model_buttons.items():
            active = k == key
            color = next(c for kk, _, c in MODELS if kk == k)
            btn.style(f'background:{theme.ACCENT_TINT if active else "transparent"};'
                      f'color:{color if active else theme.TEXT_MUTED}')

    for key, _label, _color in MODELS:
        model_buttons[key].on('click', lambda _, k=key: select_model(k))

    def refresh_card():
        card_container.clear()
        card = ai_context.current_context_card()
        with card_container:
            if not card:
                return
            with ui.row().classes('items-center no-wrap').style('gap:7px;margin-bottom:8px'):
                ui.icon('fa-solid fa-eye').style(f'color:{theme.ACCENT};font-size:11px')
                ui.label('SEEING YOUR CURRENT TAB').style(
                    f'font-size:10px;font-weight:700;letter-spacing:0.4px;color:{theme.ACCENT}')
            with ui.row().classes('items-center no-wrap').style('gap:8px;margin-bottom:7px'):
                ui.icon(card['icon']).style(f'color:{theme.TEXT};font-size:12px')
                ui.label(card['tab']).style('font-size:13.5px;font-weight:600')
            if card['pills']:
                with ui.row().style('gap:5px;flex-wrap:wrap;margin-bottom:8px'):
                    for pill in card['pills']:
                        ui.label(pill).style(
                            f'font-size:10.5px;color:{theme.TEXT_MUTED};background:rgba(255,255,255,0.05);'
                            f'border-radius:6px;padding:2px 7px')
            ui.label(card['focus']).style(
                f'font-size:11px;color:{theme.TEXT_DIM};line-height:1.4;border-top:1px solid rgba(255,255,255,0.06);'
                f'padding-top:7px;width:100%')

    def refresh_suggestions():
        suggestion_container.clear()
        tab = ai_context.active_tab()
        prompts = TAB_SUGGESTIONS.get(tab, [])
        with suggestion_container:
            for text in prompts:
                with ui.row().classes('cursor-pointer').style(
                        f'font-size:11px;color:#c2c6d6;background:{theme.CARD_BG};'
                        f'border:1px solid rgba(255,255,255,0.07);border-radius:16px;padding:6px 11px'
                ).on('click', lambda _, t=text: quick_send(t)):
                    ui.label(text)

    def render_message(role: str, text: str, tool_calls: list[dict] | None = None):
        with history_container:
            row = ui.column().style('gap:7px;width:100%')
            with row:
                if tool_calls:
                    with ui.column().style('gap:5px;width:100%'):
                        for tc in tool_calls:
                            with ui.row().classes('items-center no-wrap').style(
                                    f'gap:8px;background:rgba(165,180,252,0.07);'
                                    f'border:1px solid rgba(165,180,252,0.16);border-radius:8px;padding:6px 9px'):
                                ui.icon('fa-solid fa-bolt').style(f'color:{theme.ACCENT};font-size:10px')
                                ui.label(tc['name']).style(
                                    f'font-size:11px;font-weight:600;font-family:"JetBrains Mono",monospace;'
                                    f'color:#c2c6d6')
                                ui.label(tc.get('detail', '')).style(
                                    f'font-size:10.5px;color:{theme.TEXT_DIM};flex:1;overflow:hidden;'
                                    f'text-overflow:ellipsis;white-space:nowrap')
                                ui.icon('fa-solid fa-check').style(f'color:{theme.GREEN};font-size:10px')
                if role == 'user':
                    with ui.row().style('gap:10px;flex-direction:row-reverse;width:100%'):
                        with ui.element('div').style(
                                f'width:24px;height:24px;border-radius:6px;background:rgba(255,255,255,0.1);'
                                f'color:{theme.TEXT};display:flex;align-items:center;justify-content:center;'
                                f'font-weight:700;font-size:11px;flex:none'):
                            ui.label('U')
                        ui.label(text).style(
                            f'background:{theme.ACCENT};padding:10px 12px;border-radius:12px 0 12px 12px;'
                            f'color:{theme.BG};line-height:1.5;max-width:75%')
                elif role == 'error':
                    with ui.row().style('gap:10px;width:100%'):
                        with ui.element('div').style(
                                f'width:24px;height:24px;border-radius:6px;background:rgba(243,139,168,0.15);'
                                f'color:{theme.RED};display:flex;align-items:center;justify-content:center;flex:none'):
                            ui.icon('fa-solid fa-triangle-exclamation').style('font-size:11px')
                        ui.label(text).style(
                            f'background:{theme.CARD_BG};padding:10px 12px;border-radius:0 12px 12px 12px;'
                            f'color:{theme.RED};line-height:1.5')
                else:
                    with ui.row().style('gap:10px;width:100%'):
                        with ui.element('div').style(
                                f'width:24px;height:24px;border-radius:6px;background:rgba(165,180,252,0.15);'
                                f'color:{theme.ACCENT};display:flex;align-items:center;justify-content:center;flex:none'):
                            ui.icon('fa-solid fa-robot').style('font-size:11px')
                        ui.markdown(text).classes('nq-markdown').style(
                            f'background:{theme.CARD_BG};padding:10px 12px;border-radius:0 12px 12px 12px;'
                            f'color:{theme.TEXT};max-width:88%')
        return row

    def render_actions():
        if state['last_action_row']:
            state['last_action_row'].delete()
            state['last_action_row'] = None
        actions = _synthesize_actions()
        if not actions:
            return
        with history_container:
            row = ui.row().style('gap:6px;flex-wrap:wrap;max-width:88%')
            with row:
                for act in actions:
                    color = theme.RED if act['danger'] else theme.ACCENT
                    with ui.row().classes('cursor-pointer').style(
                            f'font-size:11.5px;font-weight:600;padding:6px 11px;border-radius:8px;'
                            f'background:{color}22;color:{color};border:1px solid {color}55'
                    ).on('click', lambda _, a=act: run_action(a)):
                        ui.label(act['label'])
        state['last_action_row'] = row

    async def run_action(act: dict):
        try:
            await run.io_bound(act['run'])
            ui.notify(f"{act['label']} — done.", type='positive')
        except Exception as e:
            ui.notify(f'Action failed: {e}', type='negative')
        live_state.refresh_all()
        if state['last_action_row']:
            state['last_action_row'].delete()
            state['last_action_row'] = None

    render_message('model', WELCOME_TEXT)

    async def _send(text: str):
        text = (text or '').strip()
        if not text:
            return
        chat_input.value = ''
        if state['last_action_row']:
            state['last_action_row'].delete()
            state['last_action_row'] = None
        render_message('user', text)
        history_snapshot = list(state['history'])
        state['history'].append({'role': 'user', 'text': text})

        with history_container:
            loading = ui.row().style('gap:10px;width:100%')
            with loading:
                with ui.element('div').style(
                        f'width:24px;height:24px;border-radius:6px;background:rgba(165,180,252,0.15);'
                        f'color:{theme.ACCENT};display:flex;align-items:center;justify-content:center;flex:none'):
                    ui.icon('fa-solid fa-robot').style('font-size:11px')
                ui.spinner(size='sm')

        model = state['model']
        context_text = ai_context.current_context_text()
        try:
            result = await run.io_bound(chat_service.send_message, text, history_snapshot, model, context_text)
        except Exception:
            result = None
        loading.delete()
        if not client_alive():
            return
        if result is None:
            render_message('error', 'Sorry, I encountered an error communicating with the backend.')
        else:
            render_message('model', result.get('text', ''), result.get('tool_calls'))
            state['history'].append({'role': 'model', 'text': result.get('text', '')})
            render_actions()

    def quick_send(text: str):
        ui.timer(0.01, lambda: _send(text), once=True)

    send_btn.on('click', lambda: _send(chat_input.value))
    chat_input.on('keydown.enter', lambda: _send(chat_input.value))

    def toggle():
        state['open'] = not state['open']
        container.style(f'margin-right:{"0" if state["open"] else "-384px"}')
        if state['open']:
            refresh_card()
            refresh_suggestions()

    close_btn.on('click', lambda: toggle())

    def _poll():
        if state['open'] and client_alive():
            refresh_card()
            refresh_suggestions()

    ui.timer(2.0, _poll)

    return toggle
