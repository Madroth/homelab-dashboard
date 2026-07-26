import inspect

from services import intake, media, minecraft, mods, repo_search


def get_minecraft_status_tool() -> str:
    """Returns the current online status and player count of the Minecraft server."""
    return minecraft.get_status_text()


def get_pending_mods_tool() -> str:
    """Returns a list of mods currently in the staging directory pending review."""
    staging = mods.get_staging()
    if not staging:
        return "No pending mods in staging."
    return "\n".join(f"ID: {item['id']}, Mod: {item['meta'].get('name', 'Unknown')}" for item in staging)


def approve_mod_tool(mod_id: str) -> str:
    """Approves a pending mod by its exact ID (e.g., '1234abcd') and deploys it."""
    result = mods.approve_mod(mod_id, decided_by="ai_assistant")
    if result.get("success"):
        return result.get("message", f"Mod '{mod_id}' approved and deployed.")
    return f"Failed to approve mod: {result.get('error', 'unknown error')}"


def get_media_queue_tool() -> str:
    """Returns a list of media items currently in the queue pending approval."""
    items = media.get_queue(status='pending')
    if not items:
        return "No pending media in queue."
    return "\n".join(
        f"ID: {item['id']} | File: {item['original_filename']} | "
        f"Title: {item['proposed_title']} | Path: {item.get('proposed_path')}"
        for item in items
    )


def approve_media_tool(item_id: str) -> str:
    """Approves a media item in the queue by its exact ID (e.g. '1234abcd')."""
    success, msg = media.approve(item_id)
    if success:
        return f"Success! Media item '{item_id}' approved and moved to library."
    return f"Failed to approve media: {msg}"


def reject_media_tool(item_id: str) -> str:
    """Rejects a media item in the queue by its exact ID."""
    success, msg = media.reject(item_id)
    if success:
        return f"Success! Media item '{item_id}' rejected."
    return f"Failed to reject media: {msg}"


def edit_media_tool(item_id: str, proposed_title: str = None) -> str:
    """Edits a media item's proposed title in the queue."""
    success, msg = media.edit(item_id, proposed_title=proposed_title)
    if success:
        return f"Success! Media item '{item_id}' updated."
    return f"Failed to edit media: {msg}"


def search_intake_articles_tool(question: str) -> str:
    """Search the user's saved article archive (homelab-intake) for articles relevant to a
    question. Call this whenever the user asks what they've read, saved, or bookmarked about
    a topic. Returns the most relevant articles with titles, tags, and excerpts -- answer
    using only what comes back, and cite the article titles.
    """
    return intake.search_articles(question)


def read_article_tool(article_id: str) -> str:
    """Reads the full content of a specific saved article by its exact ID/filename.
    Use this to answer detailed questions about the currently-open article's content."""
    data = intake.get_article(article_id)
    if not data:
        return f"Article '{article_id}' not found."
    return data['content'][:6000]


def grep_repo_tool(query: str) -> dict:
    """Searches the user's HomeLab infrastructure repo (Madroth/Homelab) for files and
    configs relevant to a query. Returns matching lines with file paths -- use this to
    check what the user's actual setup does before answering questions about their
    homelab, docker stacks, or configs."""
    matches = repo_search.grep_repo(query)
    if not matches:
        return {"text": "No matches found in the homelab repo.", "citations": []}
    text = "\n".join(f"{m['path']}:{m['line']}: {m['snippet']}" for m in matches)
    citations = [{'path': m['path'], 'line_start': m['line'], 'line_end': m['line'],
                  'kind': 'repo', 'snippet': m['snippet']}
                 for m in matches]
    return {"text": text, "citations": citations}


def search_archive_tool(question: str) -> dict:
    """Semantic search over the user's saved article archive. Use this to find related
    articles the user has already read or saved on a topic."""
    text, citations = intake.search_articles_with_citations(question)
    return {"text": text, "citations": citations}


ALL_TOOLS = [
    get_minecraft_status_tool,
    get_pending_mods_tool,
    approve_mod_tool,
    get_media_queue_tool,
    approve_media_tool,
    reject_media_tool,
    edit_media_tool,
    search_intake_articles_tool,
]

# Discuss tools whose underlying implementation returns (text, citations) instead of
# just text -- chat.py's _run_tool special-cases these by name to unpack the tuple,
# forward only the text to the model, and thread the citations up into tool_calls.
CITED_TOOLS = {'grep_repo_tool', 'search_archive_tool'}

DISCUSS_TOOLS = [read_article_tool, grep_repo_tool, search_archive_tool]


def _schema_for(fn) -> dict:
    """Derives a JSON-schema tool definition from a function's signature + docstring, so
    Claude and Ollama (which both take JSON Schema, unlike Gemini's auto-introspection)
    share one definition instead of a hand-written, easily-stale copy. Every tool above
    takes only plain string params, so this stays simple."""
    sig = inspect.signature(fn)
    properties = {name: {"type": "string"} for name in sig.parameters}
    required = [name for name, p in sig.parameters.items() if p.default is inspect.Parameter.empty]
    description = " ".join(line.strip() for line in (fn.__doc__ or '').strip().splitlines())
    return {
        "name": fn.__name__,
        "description": description,
        "parameters": {"type": "object", "properties": properties, "required": required},
    }


def build_schemas(tool_fns: list) -> tuple[list, list, dict]:
    """Derives Anthropic/Ollama tool-schema lists + a name->function dispatch map from an
    arbitrary list of tool functions. Reused for both the fixed dashboard-assistant
    ALL_TOOLS and AI Discuss's dynamic per-request subset (which tools are available
    depends on which context-source chips are active)."""
    schemas = [_schema_for(fn) for fn in tool_fns]
    anthropic_schemas = [
        {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]} for s in schemas
    ]
    ollama_schemas = [{"type": "function", "function": s} for s in schemas]
    dispatch = {fn.__name__: fn for fn in tool_fns}
    return anthropic_schemas, ollama_schemas, dispatch


ANTHROPIC_TOOL_SCHEMAS, OLLAMA_TOOL_SCHEMAS, TOOL_DISPATCH = build_schemas(ALL_TOOLS)
