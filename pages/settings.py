from nicegui import run, ui

from components import ai_context, theme
from services import settings


def build():
    ai_context.register('settings', lambda: "Viewing Settings (AI/API configuration).")
    ai_context.register_card('settings', lambda: {
        'icon': 'fa-solid fa-gear', 'tab': 'Settings', 'pills': [],
        'focus': 'Configure API keys and the local model here.'})

    with ui.column().style('flex:1;height:100%;overflow:auto;padding:24px 28px;gap:24px'):
        ui.label('Dashboard Settings').style(f'font-size:18px;font-weight:700;color:{theme.TEXT}')

        with ui.column().style(
                f'max-width:600px;background:{theme.CARD_BG};border:1px solid {theme.BORDER};'
                f'border-radius:10px;padding:20px;gap:16px'):
            with ui.row().classes('items-center no-wrap').style(
                    f'font-size:14px;font-weight:600;color:{theme.ACCENT};gap:8px'):
                ui.icon('fa-solid fa-wand-magic-sparkles')
                ui.label('AI Assistant Configuration')

            ui.label('Gemini API Key (for Agy)').style(f'font-size:12px;color:{theme.TEXT_MUTED}')
            gemini_input = ui.input(placeholder='AIzaSy...', password=True, password_toggle_button=True).style(
                f'width:100%').props('outlined dense')

            ui.label('Anthropic API Key (for Claude)').style(f'font-size:12px;color:{theme.TEXT_MUTED}')
            anthropic_input = ui.input(placeholder='sk-ant-...', password=True,
                                        password_toggle_button=True).style('width:100%').props('outlined dense')

            ui.label('Ollama Host (for Local Models)').style(f'font-size:12px;color:{theme.TEXT_MUTED}')
            ollama_input = ui.input(placeholder='http://100.74.2.92:11434').style('width:100%').props(
                'outlined dense')

            ui.label('Ollama Model (for Local Models)').style(f'font-size:12px;color:{theme.TEXT_MUTED}')
            ollama_model_input = ui.input(placeholder='qwen2.5:32b-instruct-q4_K_M').style('width:100%').props(
                'outlined dense')

            with ui.row().classes('justify-end w-full'):
                save_button = ui.button('Save Settings', on_click=lambda: do_save()).style(
                    f'background:{theme.ACCENT};color:{theme.BG};font-weight:600')

    async def load():
        data = await run.io_bound(settings.get_settings)
        if data.get('geminiApiKey'):
            gemini_input.value = data['geminiApiKey']
        if data.get('anthropicApiKey'):
            anthropic_input.value = data['anthropicApiKey']
        if data.get('ollamaHost'):
            ollama_input.value = data['ollamaHost']
        if data.get('ollamaModel'):
            ollama_model_input.value = data['ollamaModel']

    async def do_save():
        save_button.props('loading')
        try:
            await run.io_bound(settings.save_settings, {
                'geminiApiKey': gemini_input.value,
                'anthropicApiKey': anthropic_input.value,
                'ollamaHost': ollama_input.value,
                'ollamaModel': ollama_model_input.value,
            })
            ui.notify('Settings saved', type='positive')
        except Exception as e:
            ui.notify(f'Failed to save: {e}', type='negative')
        finally:
            save_button.props(remove='loading')

    ui.timer(0.05, load, once=True)
