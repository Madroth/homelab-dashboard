"""AI Discuss orchestration -- a per-article chat grounded only in explicitly-toggled
context sources (the open article, the HomeLab repo, the article archive), on top of
the generalized services/ai/chat.py send_message()."""
from services import intake
from services.ai import chat, tools

DISCUSS_SYSTEM_PROMPT = (
    "You are helping the user think through a saved article inside the OmegaLab "
    "Dashboard's Article Intake tab. Be concise and direct. Only use information from "
    "the context sources the user has explicitly turned on -- if a source is off, say "
    "so plainly rather than answering as if you had it (e.g. 'Working only from the "
    "article itself -- repo and archive context are switched off, so I can't tell you "
    "how this lines up with your actual setup.'). Never claim knowledge of the user's "
    "repo or archive unless you actually called a tool to check."
)

SOURCE_LABELS = {'article': 'This article', 'repo': 'homelab repo', 'archive': 'Article archive'}
SOURCE_ORDER = ['article', 'repo', 'archive']

SOURCE_TOOLS = {
    'article': [tools.read_article_tool],
    'repo': [tools.grep_repo_tool],
    'archive': [tools.search_archive_tool],
}


def _context_text(article: dict, active_sources: set[str]) -> str:
    lines = []
    if 'article' in active_sources:
        data = intake.get_article(article['id'])
        content = data['content'] if data else ''
        lines.append(f"Full text of the open article \"{article['title']}\":\n{content[:6000]}")
    off = [SOURCE_LABELS[s] for s in SOURCE_ORDER if s not in active_sources]
    if off:
        lines.append(f"\nContext sources currently OFF: {', '.join(off)}. Do not assume access to these.")
    return '\n\n'.join(lines)


def send_discuss_message(article: dict, active_sources: set[str], user_message: str,
                          history: list[dict], model: str = 'claude') -> dict:
    """One Discuss turn. Returns the same shape as chat.send_message()."""
    tool_fns = []
    for source in SOURCE_ORDER:
        if source in active_sources:
            tool_fns.extend(SOURCE_TOOLS[source])

    context_text = _context_text(article, active_sources)
    return chat.send_message(user_message, history, model, context_text,
                              system_prompt=DISCUSS_SYSTEM_PROMPT, tool_fns=tool_fns)


def grounding_footer(active_sources: set[str], model_label: str) -> str:
    if not active_sources:
        return 'Ungrounded — no sources selected'
    n = len(active_sources)
    return f"{model_label} · grounded in {n} source{'s' if n != 1 else ''}"


def placeholder_text(active_sources: set[str]) -> str:
    if not active_sources:
        return 'Ask anything (no context selected)…'
    names = ' + '.join(SOURCE_LABELS[s] for s in SOURCE_ORDER if s in active_sources)
    return f'Ask about {names}…'
