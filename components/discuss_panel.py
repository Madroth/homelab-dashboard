"""AI Discuss panel -- rendered inside the Article Intake reader when the Read/Discuss
toggle is set to Discuss. Stateless rendering function: all persistent state (selected
model, active context sources, cached thread) lives in the CALLER's state dict, not here,
because pages/intake.py's reader is a @ui.refreshable that gets fully rebuilt on
unrelated state changes (switching articles, Content/Summary tab, etc.) -- closures
captured inside this module would be wiped out on every such rebuild. Mirrors the
external-state-plus-callbacks pattern already used by components/nav_sidebar.py.
"""
from typing import Callable

from nicegui import ui

from components import theme
from services import intake, repo_search
from services.ai import discuss

MODELS = [('claude', 'Claude', theme.ACCENT), ('agy', 'Agy', theme.AMBER), ('local', 'Local', theme.GREEN)]


def _suggested_prompts(article: dict) -> list[str]:
    content_type = (article.get('content_type') or '').lower()
    if content_type in ('guide', 'tutorial', 'reference'):
        return ["Does my setup already do what this recommends?",
                "What in my repo would I have to change?"]
    return [f'Summarize the key takeaway from this article',
            "How does this relate to what I've saved before?"]


def _render_citation(cite: dict, on_open_citation: Callable[[str], None]):
    is_repo = cite['kind'] == 'repo'
    color = theme.GREEN if is_repo else theme.PURPLE
    label = f"{cite['path']}:{cite['line_start']}" if is_repo else cite['title']
    with ui.expansion(label, icon='fa-solid fa-quote-left').classes('w-full').style(
            f'background:rgba(255,255,255,0.03);border-radius:8px;font-size:11px;color:{color}'):
        if is_repo:
            ui.label(cite.get('snippet', '')).style(
                f'font-family:"JetBrains Mono",monospace;font-size:11px;color:{theme.TEXT_MUTED};'
                f'background:rgba(0,0,0,0.25);padding:8px;border-radius:6px;white-space:pre-wrap;display:block')
        else:
            with ui.row().classes('cursor-pointer').on(
                    'click', lambda _, aid=cite['article_id']: on_open_citation(aid)):
                ui.icon('fa-solid fa-arrow-right').style(f'color:{theme.PURPLE};font-size:10px')
                ui.label(f"Open \"{cite['title']}\"").style(f'color:{theme.PURPLE};font-size:11px')


def _render_message(msg: dict, on_open_citation: Callable[[str], None]):
    with ui.column().style('gap:6px;width:100%'):
        for tool in msg.get('tools', []):
            with ui.row().classes('items-center no-wrap').style(
                    f'gap:8px;background:rgba(165,180,252,0.07);border:1px solid rgba(165,180,252,0.16);'
                    f'border-radius:8px;padding:6px 9px;width:100%'):
                ui.icon('fa-solid fa-bolt').style(f'color:{theme.ACCENT};font-size:10px')
                ui.label(tool['name']).style(
                    'font-size:11px;font-weight:600;font-family:"JetBrains Mono",monospace;color:#c2c6d6')
                ui.label(tool.get('detail', '')).style(
                    f'font-size:10.5px;color:{theme.TEXT_DIM};flex:1;overflow:hidden;'
                    f'text-overflow:ellipsis;white-space:nowrap')
                ui.icon('fa-solid fa-check').style(f'color:{theme.GREEN};font-size:10px')

        if msg['role'] == 'user':
            with ui.row().style('justify-content:flex-end;width:100%'):
                ui.label(msg['text']).style(
                    f'background:{theme.ACCENT};padding:9px 12px;border-radius:12px 0 12px 12px;'
                    f'color:{theme.BG};max-width:80%;line-height:1.5;font-size:13px')
        else:
            ui.markdown(msg['text']).classes('nq-markdown').style(
                f'background:{theme.CARD_BG};padding:9px 12px;border-radius:0 12px 12px 12px;'
                f'max-width:88%;color:{theme.TEXT}')

        for cite in msg.get('cites', []):
            _render_citation(cite, on_open_citation)


REPO_LABEL = 'homelab-infra'  # the only repo currently wired into grounding (~/HomeLab)


def _thinking_line(model_label: str, active: set[str]) -> str:
    scope_bits = ['this article']
    if 'archive' in active:
        scope_bits.append('your archive')
    if 'repo' in active:
        scope_bits.append(REPO_LABEL)
    if len(scope_bits) == 1:
        scope = scope_bits[0]
    else:
        scope = ', '.join(scope_bits[:-1]) + f' + {scope_bits[-1]}'
    return f'{model_label} is reading {scope}…'


def build(article: dict, discuss_state: dict, on_send: Callable[[str], None],
          on_toggle_source: Callable[[str], None], on_select_model: Callable[[str], None],
          on_clear_thread: Callable[[], None], on_open_citation: Callable[[str], None],
          on_close_repo_scope: Callable[[], None] = lambda: None):
    active = discuss_state['active_sources']
    thread = discuss_state['thread']

    with ui.column().style('width:100%;height:100%;background:#1b1b28;gap:0'):
        # align-self:stretch / width:100% throughout: the panel column doesn't stretch
        # its children (NiceGUI default), so any row missing this shrinks to content
        # width and clusters at the left edge (hit live 2026-08-02 on the input row).
        with ui.row().style(
                f'gap:3px;background:{theme.CARD_BG};border-radius:9px;padding:3px;margin:12px 16px 0;'
                f'align-self:stretch'):
            for key, label, color in MODELS:
                is_active = key == discuss_state['model']
                with ui.row().classes('items-center justify-center cursor-pointer').style(
                        f'flex:1;padding:6px 0;border-radius:6px;font-size:11.5px;font-weight:600;'
                        f'background:{theme.ACCENT_TINT if is_active else "transparent"};'
                        f'color:{color if is_active else theme.TEXT_MUTED}'
                ).on('click', lambda _, k=key: on_select_model(k)).mark(f'discuss-model-{key}'):
                    ui.label(label)

        archive_count = len(intake.list_articles())
        repo_count = repo_search.repo_file_count()
        # 'article' is always on -- not a user choice, so it's rendered locked (no click
        # handler, a lock glyph instead of the on/off dot) rather than as a real toggle.
        chips = [
            ('article', 'This article', f"{article.get('reading_minutes', 1)} min read", True),
            ('repo', REPO_LABEL, f"{repo_count} files", False),
            ('archive', 'Article archive', f"{archive_count} saved", False),
        ]
        with ui.row().style('gap:6px;flex-wrap:wrap;padding:10px 16px 4px;width:100%'):
            for key, label, meta, locked in chips:
                is_on = key in active
                with ui.element('div').style('position:relative'):
                    row = ui.row().classes(
                        'items-center no-wrap' + ('' if locked else ' cursor-pointer')
                    ).style(
                            f'gap:6px;padding:5px 10px;border-radius:14px;'
                            f'background:{theme.ACCENT_TINT if is_on else "rgba(255,255,255,0.04)"};'
                            f'border:1px solid {theme.ACCENT if is_on else "transparent"}')
                    row.mark(f'discuss-chip-{key}')
                    if not locked:
                        row.on('click', lambda _, k=key: on_toggle_source(k))
                    with row:
                        if locked:
                            ui.icon('fa-solid fa-lock').style(f'font-size:8px;color:{theme.ACCENT};flex:none')
                        else:
                            ui.element('div').style(
                                f'width:6px;height:6px;border-radius:50%;flex:none;'
                                f'background:{theme.ACCENT if is_on else theme.TEXT_DIM}')
                        ui.label(label).style(
                            f'font-size:11.5px;font-weight:600;color:{theme.TEXT if is_on else theme.TEXT_MUTED}')
                        ui.label(meta).style(f'font-size:10px;color:{theme.TEXT_DIM}')

                    if key == 'repo' and discuss_state.get('repo_scope_open'):
                        with ui.column().style(
                                f'position:absolute;top:34px;left:0;z-index:20;width:260px;'
                                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.1);'
                                f'border-radius:10px;padding:12px;gap:8px;'
                                f'box-shadow:0 8px 24px rgba(0,0,0,0.35)'):
                            ui.label('Repo access').style(f'font-size:12px;font-weight:700;color:{theme.TEXT}')
                            ui.label(
                                f'Reads from {REPO_LABEL} only, and only on the turns you ask — '
                                f'nothing is indexed or scanned in the background.'
                            ).style(f'font-size:11px;line-height:1.5;color:{theme.TEXT_MUTED}')
                            with ui.row().classes('items-center no-wrap').style('gap:6px'):
                                ui.icon('fa-solid fa-code-branch').style(f'font-size:10px;color:{theme.GREEN}')
                                ui.label(f'{REPO_LABEL} · {repo_count} files').style(
                                    f'font-size:11px;color:{theme.TEXT}')
                            ui.button('Got it', on_click=lambda: on_close_repo_scope()).props('flat dense').style(
                                f'align-self:flex-end;color:{theme.ACCENT};font-size:11px')

        ui.label(f"{REPO_LABEL} read on request · {archive_count} articles in archive").style(
            f'font-size:10px;color:{theme.TEXT_DIM};padding:0 16px 8px')

        with ui.column().classes('nq-custom-scroll').style(
                'flex:1;overflow-y:auto;padding:8px 16px;gap:14px;width:100%'):
            if not thread:
                ui.label("No messages yet — try one of these, or ask your own question.").style(
                    f'font-size:12px;color:{theme.TEXT_DIM};margin-bottom:6px')
                with ui.row().style('gap:6px;flex-wrap:wrap'):
                    for i, p in enumerate(_suggested_prompts(article)):
                        with ui.row().classes('cursor-pointer').style(
                                f'font-size:11px;color:#c2c6d6;background:{theme.CARD_BG};'
                                f'border:1px solid rgba(255,255,255,0.07);border-radius:16px;padding:6px 11px'
                        ).on('click', lambda _, t=p: on_send(t)).mark(f'discuss-prompt-{i}'):
                            ui.label(p)
            for msg in thread:
                _render_message(msg, on_open_citation)
            if discuss_state.get('busy'):
                model_label = next(l for k, l, _ in MODELS if k == discuss_state['model'])
                with ui.row().classes('items-center no-wrap').style(f'gap:8px;color:{theme.TEXT_MUTED}'):
                    ui.spinner(size='sm')
                    ui.label(_thinking_line(model_label, active)).style('font-size:12px')

        with ui.row().classes('items-center no-wrap').style(
                'padding:10px 16px;border-top:1px solid rgba(255,255,255,0.06);gap:8px;width:100%'):
            draft_input = ui.input(placeholder=discuss.placeholder_text(active)).props('borderless dense').style(
                f'flex:1;min-width:0;background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.07);'
                f'border-radius:7px;padding:6px 10px;color:{theme.TEXT};font-size:12.5px')
            send_btn = ui.element('div').classes('cursor-pointer').style(
                f'width:32px;height:32px;border-radius:8px;background:{theme.ACCENT};color:{theme.BG};'
                f'display:flex;align-items:center;justify-content:center;flex:none')
            with send_btn:
                ui.icon('fa-solid fa-arrow-up').style('font-size:13px')
            send_btn.on('click', lambda: on_send(draft_input.value))
            draft_input.on('keydown.enter', lambda: on_send(draft_input.value))

        model_label = next(l for k, l, _ in MODELS if k == discuss_state['model'])
        with ui.row().classes('items-center justify-between no-wrap').style('padding:0 16px 10px;width:100%'):
            ui.label(discuss.grounding_footer(active, model_label)).style(f'font-size:10px;color:{theme.TEXT_DIM}')
            if thread:
                with ui.row().classes('cursor-pointer').on('click', lambda: on_clear_thread()):
                    ui.label('Clear thread').style(f'font-size:10px;color:{theme.TEXT_MUTED}')
