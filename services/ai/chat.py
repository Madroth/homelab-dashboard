import os

import requests

from services import settings as settings_service
from services.ai import tools as tools_module
from services.ai.tools import ALL_TOOLS, ANTHROPIC_TOOL_SCHEMAS, CITED_TOOLS, OLLAMA_TOOL_SCHEMAS, TOOL_DISPATCH

DASHBOARD_SYSTEM_PROMPT = (
    "You are an AI assistant built directly into the OmegaLab Dashboard sidebar. "
    "Be helpful, concise, and friendly. You have tools to manage the dashboard and "
    "server. When a user asks you to execute a change, first use a GET tool (like "
    "get_media_queue_tool) to find the ID of the item, then use the appropriate "
    "action tool (like edit_media_tool) with that ID."
)

DEFAULT_OLLAMA_HOST = "http://100.74.2.92:11434"  # Omega, over Tailscale -- see ~/HomeLab/HARDWARE.md
DEFAULT_OLLAMA_MODEL = "qwen2.5:32b-instruct-q4_K_M"  # verified tool-calling-capable against Omega

MAX_TOOL_ITERATIONS = 6


def _system_prompt(context_text: str, base_prompt: str | None = None) -> str:
    base = base_prompt or DASHBOARD_SYSTEM_PROMPT
    if not context_text:
        return base
    return f"{base}\n\nWhat the user is currently viewing on the dashboard:\n{context_text}"


def _detail(arguments: dict) -> str:
    return ', '.join(f'{k}={v}' for k, v in arguments.items())[:80]


def _empty(text: str) -> dict:
    return {'text': text, 'tool_calls': []}


def send_message(user_message: str, history: list[dict], model: str = 'agy', context_text: str = '',
                  system_prompt: str | None = None, tool_fns: list | None = None) -> dict:
    """Returns {'text': str, 'tool_calls': [{'name': str, 'detail': str, 'cites': [...]}]}.
    system_prompt/tool_fns default to the dashboard assistant's fixed prompt/toolset when
    omitted -- AI Discuss passes its own grounded prompt and a per-request tool subset."""
    settings = settings_service.get_settings()

    if model == 'local':
        return _send_local(user_message, history, settings, context_text, system_prompt, tool_fns)

    if model == 'claude':
        return _send_claude(user_message, history, settings, context_text, system_prompt, tool_fns)

    if model == 'agy':
        return _send_agy(user_message, history, settings, context_text, system_prompt, tool_fns)

    return _empty(f'Model {model} is not supported yet.')


def _run_tool(name: str, arguments: dict, dispatch: dict) -> tuple[str, bool, list]:
    """Returns (result_text, is_error, citations). Tools in CITED_TOOLS return a
    {'text', 'citations'} dict instead of plain text; everything else is unaffected."""
    try:
        result = dispatch[name](**arguments)
        if name in CITED_TOOLS:
            return str(result.get('text', '')), False, result.get('citations', [])
        return str(result), False, []
    except Exception as e:
        return f"Error: {e}", True, []


def _send_claude(user_message: str, history: list[dict], settings: dict, context_text: str,
                  system_prompt: str | None = None, tool_fns: list | None = None) -> dict:
    import anthropic

    api_key = settings.get('anthropicApiKey') or os.environ.get('ANTHROPIC_API_KEY')
    if not api_key:
        return _empty('Anthropic API key is not configured in Settings.')

    if tool_fns is not None:
        anthropic_schemas, _, dispatch = tools_module.build_schemas(tool_fns)
    else:
        anthropic_schemas, dispatch = ANTHROPIC_TOOL_SCHEMAS, TOOL_DISPATCH

    messages = [
        {"role": "assistant" if m.get('role') == 'model' else "user", "content": m.get('text', '')}
        for m in history
    ]
    messages.append({"role": "user", "content": user_message})
    tool_calls = []

    try:
        client = anthropic.Anthropic(api_key=api_key)
        for _ in range(MAX_TOOL_ITERATIONS):
            response = client.messages.create(
                model="claude-sonnet-5",
                max_tokens=1024,
                system=_system_prompt(context_text, system_prompt),
                tools=anthropic_schemas,
                messages=messages,
            )

            if response.stop_reason != "tool_use":
                text = next((b.text for b in response.content if b.type == "text"), "")
                return {'text': text, 'tool_calls': tool_calls}

            messages.append({"role": "assistant", "content": response.content})
            tool_results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                result, is_error, citations = _run_tool(block.name, block.input, dispatch)
                tc = {'name': block.name, 'detail': _detail(block.input)}
                if citations:
                    tc['cites'] = citations
                tool_calls.append(tc)
                tool_results.append({
                    "type": "tool_result", "tool_use_id": block.id, "content": result, "is_error": is_error,
                })
            messages.append({"role": "user", "content": tool_results})

        return {'text': "I hit the tool-call limit for this request without finishing -- try rephrasing or "
                         "narrowing it.", 'tool_calls': tool_calls}
    except Exception as e:
        return _empty(f'Error communicating with Claude: {e}')


def _send_agy(user_message: str, history: list[dict], settings: dict, context_text: str,
              system_prompt: str | None = None, tool_fns: list | None = None) -> dict:
    from google import genai
    from google.genai import types

    api_key = settings.get('geminiApiKey') or os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return _empty('GEMINI_API_KEY is not configured in Settings.')

    try:
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=_system_prompt(context_text, system_prompt),
            tools=tool_fns if tool_fns is not None else ALL_TOOLS,
            temperature=0.5,
        )
        gemini_history = [
            types.Content(
                role="model" if m.get('role') == 'model' else "user",
                parts=[types.Part(text=m.get('text', ''))],
            )
            for m in history
        ]
        chat = client.chats.create(model='gemini-2.5-flash', config=config, history=gemini_history)

        response = chat.send_message(user_message)

        # The SDK auto-executes tools transparently; the intermediate function_call parts it
        # made along the way are preserved on the response for exactly this kind of inspection.
        # Note: unlike Claude/Ollama below, we don't drive Gemini's tool loop ourselves, so
        # CITED_TOOLS' citations (buried in the paired function_response part) aren't
        # extracted here -- Gemini/Agy tool-call chips render without citation strips. A
        # disclosed v1 scope reduction rather than an oversight.
        tool_calls = []
        for content in (response.automatic_function_calling_history or []):
            for part in (content.parts or []):
                if part.function_call:
                    tool_calls.append({'name': part.function_call.name,
                                        'detail': _detail(dict(part.function_call.args or {}))})

        return {'text': response.text, 'tool_calls': tool_calls}
    except Exception as e:
        return _empty(f'Error communicating with Gemini: {e}')


def _send_local(user_message: str, history: list[dict], settings: dict, context_text: str,
                 system_prompt: str | None = None, tool_fns: list | None = None) -> dict:
    ollama_host = settings.get('ollamaHost') or DEFAULT_OLLAMA_HOST
    ollama_model = settings.get('ollamaModel') or DEFAULT_OLLAMA_MODEL

    if tool_fns is not None:
        _, ollama_schemas, dispatch = tools_module.build_schemas(tool_fns)
    else:
        ollama_schemas, dispatch = OLLAMA_TOOL_SCHEMAS, TOOL_DISPATCH

    messages = [{"role": "system", "content": _system_prompt(context_text, system_prompt)}]
    messages += [
        {"role": "assistant" if m.get('role') == 'model' else "user", "content": m.get('text', '')}
        for m in history
    ]
    messages.append({"role": "user", "content": user_message})
    tool_calls = []

    try:
        for _ in range(MAX_TOOL_ITERATIONS):
            resp = requests.post(
                f"{ollama_host}/api/chat",
                json={
                    "model": ollama_model,
                    "messages": messages,
                    "tools": ollama_schemas,
                    "stream": False,
                    # Required -- omitting this silently falls back to partial CPU inference
                    # on 32B models (measured: 4.5 tok/s vs 39 tok/s). See ~/shared/ask-omega.py.
                    "options": {"num_ctx": 4096},
                },
                timeout=180,
            )
            resp.raise_for_status()
            message = resp.json()["message"]
            calls = message.get("tool_calls") or []

            if not calls:
                return {'text': message.get("content", ""), 'tool_calls': tool_calls}

            messages.append(message)
            for call in calls:
                fn = call["function"]
                result, _, citations = _run_tool(fn["name"], fn["arguments"], dispatch)
                tc = {'name': fn['name'], 'detail': _detail(fn['arguments'])}
                if citations:
                    tc['cites'] = citations
                tool_calls.append(tc)
                messages.append({"role": "tool", "content": result})

        return {'text': "I hit the tool-call limit for this request without finishing -- try rephrasing or "
                         "narrowing it.", 'tool_calls': tool_calls}
    except requests.RequestException as e:
        return _empty(f'Error communicating with local model at {ollama_host}: {e}')
