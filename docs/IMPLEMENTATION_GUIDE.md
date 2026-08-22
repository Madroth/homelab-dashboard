# Implementation Guide — wiring the new visuals to existing logic

For whichever Claude Code session picks up the Claude Design output and rebuilds the
dashboard's UI around it. This is **not** a design doc (see `DESIGN_BRIEF.md` for that)
and **not** a feature checklist (see `FEATURE_INVENTORY.md` for that) — it's the
architecture and service-layer reference so the reskin calls into existing, working
logic instead of reinventing it.

## Stack & entrypoint

Python + **NiceGUI** (not Flask, not React — `app.py`/`static/` are dead legacy code,
see Feature Inventory's last section). Entry: `main.py` → `components/layout.build(request)`,
which reads the `?tab=` query param, renders the nav sidebar, a `ui.tab_panels` holding
all six pages (all six are built eagerly per client, not lazily on tab switch), and the
AI chat sidebar.

Runs as a systemd user service:
```
systemctl --user restart homelab-dashboard.service   # NiceGUI runs with reload=False —
journalctl --user -u homelab-dashboard.service -f    # code changes need a restart to load
```

## File map

```
main.py                        entrypoint
components/
  layout.py                    per-client shell: nav + tab_panels + chat sidebar; owns tab-switch logic
  nav_sidebar.py                left nav (NAV_ITEMS / DISABLED_ITEMS / QUICK_LINKS constants)
  chat_sidebar.py               AI Assistant panel UI + send() handler
  discuss_panel.py               Article Intake's per-article Discuss mode (stateless render fn)
  ai_context.py                 per-client "what's on screen" registry (see below)
  confirm_dialog.py             async confirm(title, message, ...) -> bool helper
  util.py                        client_alive() guard
  theme.py                       color/font constants + global CSS (ui.add_css)
pages/<tab>.py                  one module per tab, each exposes build()
services/<name>.py              backend logic per domain — pages call these, never touch
                                 files/subprocess/other-repos' data directly themselves
services/ai/
  chat.py                        send_message(...) — routes to Claude/Gemini/Ollama
  tools.py                       tool implementations + auto-derived schemas
  discuss.py                     Article Intake Discuss mode's grounded-chat backend
docs/
  DESIGN_BRIEF.md                 input to Claude Design (whole dashboard)
  INTAKE_UPGRADE_BRIEF.md         input to Claude Design (Article Intake tab specifically)
  INTAKE_ARCHITECTURE.md          Article Intake code-level architecture (Code-facing, not Design)
  FEATURE_INVENTORY.md            parity checklist for the reskin
  IMPLEMENTATION_GUIDE.md          this file
```

## Structural patterns that must survive the reskin (not aesthetic — load-bearing)

**Per-page local state + refreshable renders.** Every page's `build()` closes over a
plain `state = {...}` dict; `@ui.refreshable`-decorated render functions read from it;
`reload()`/action functions mutate `state` then call `.refresh()`. This is the only state
management pattern in the app — no global store, no reactive framework beyond NiceGUI's
own. Keep it; don't introduce a second pattern for new UI.

**`client_alive()` after every `await run.io_bound(...)`.** A NiceGUI client (browser
tab) can disconnect mid-await; refreshing a deleted client's UI raises. Every reload
function in every page guards its `state` write + `.refresh()` calls with
`if client_alive(): ...` after the awaited call returns. Copy this pattern for any new
async reload logic.

**`run.io_bound(...)` for anything blocking.** File reads, subprocess calls (`docker
ps`, `systemctl`), and network calls (Ollama, Anthropic, Gemini) all go through
`nicegui.run.io_bound` from inside `async def` handlers — never called directly on the
event loop. This is what keeps the UI responsive while a service call is in flight.

**`confirm()` before destructive actions.** `components/confirm_dialog.confirm(title,
message, *, confirm_label='Confirm', danger=False) -> bool` (async, awaits a dialog).
Used today for article delete and media reject. Reuse it for any new destructive action
rather than a bespoke `ui.dialog()`.

**`ui.notify(...)`** for transient success/failure feedback (resubmit, approve/reject
outcomes). Keep using it for the same class of feedback.

**The AI context registry (`components/ai_context.py`) is the mechanism that makes the
Assistant sidebar context-aware — this is new as of the most recent rework and must be
preserved, not just visually reskinned:**
```python
ai_context.register(tab_key: str, get_summary: Callable[[], str])   # once per page build()
ai_context.set_active_tab(tab_key: str)                              # on every tab switch (layout.py)
ai_context.current_context_text() -> str                              # read at chat send-time
```
Keyed off `nicegui.context.client.id` (per-browser-tab). If any page gets restructured
enough that its `state` shape changes, its `get_context_summary()` closure needs updating
to match — it's not auto-derived from anything, it's a small hand-written summary per
page (see any current page for the pattern, `pages/intake.py` has the richest example).

**Tool schemas are derived, not hand-written** (`services/ai/tools.py`): `ALL_TOOLS` is
the single source of truth (plain Python functions, one-line-first docstring becomes the
description). `ANTHROPIC_TOOL_SCHEMAS`, `OLLAMA_TOOL_SCHEMAS`, and `TOOL_DISPATCH` are all
derived from it via `_schema_for()`. **If the reskin adds a new page-level action that
the AI should also be able to take, add one function to `ALL_TOOLS` — don't hand-write a
schema anywhere.** All tool params today are plain strings; if a new tool needs a
non-string param, `_schema_for` will need extending (it currently hardcodes
`{"type": "string"}` for every parameter).

## Service layer — the real API surface pages call into

Reuse these exactly; don't re-derive file paths, subprocess calls, or backend logic in
page code. Page modules should only ever import from `services.*`.

```python
# services/intake.py -- reads homelab-intake's files directly by path (see
# INTAKE_UPGRADE_BRIEF.md §8 for the article dict shape); queue.json read-modify-write
# is fcntl-locked + atomic (2026-07-31, see _queue_lock()/_write_queue())
list_articles() -> list[dict]                                # cached by articles-dir mtime signature
get_article(filename: str) -> dict | None                    # {'content': str, 'summary': str}
delete_article(filename: str) -> bool
mark_duplicate(filename: str) -> bool
add_to_folder(filename: str, folder: str) -> bool            # writes into the article's own frontmatter
remove_from_folder(filename: str, folder: str) -> bool
resubmit_article(filename: str) -> dict                      # {'success': True} | {'error': str}
get_queue() -> list[dict]
retry_queue_item(item_id: str) -> bool
search_articles(question: str, top_k: int = 5) -> str         # semantic search (plain text), used by the AI tool
search_articles_with_citations(question, top_k=5) -> tuple[str, list[dict]]   # same, + citation records for Discuss

# services/intake_state.py -- dashboard-owned sidecar state (intake_state.json /
# intake_conversations.json), NOT part of homelab-intake; every read-modify-write is
# fcntl-locked + atomic (2026-07-31, see _file_lock()/_atomic_write())
get_article_state(article_id: str) -> dict                   # {'read', 'favorite', 'archived',
                                                             #  'plane_issue_id'}
all_article_states() -> dict                                 # {article_id: state}
set_article_state(article_id: str, **fields) -> None
bulk_set_article_state(article_ids: list[str], **fields) -> None
list_folders() -> list[str]
create_folder(name: str) -> None
get_prefs() -> dict                                            # {'view', 'sort'}
set_prefs(**fields) -> None
get_thread(article_id: str) -> list[dict]                      # Discuss conversation
append_message(article_id: str, message: dict) -> None
clear_thread(article_id: str) -> None
thread_counts() -> dict                                        # {article_id: message_count}, list-row chip

# services/plane.py -- "Send to HomeLab"
send_article_to_plane(article: dict, summary: str) -> dict
# {'created', 'verified', 'already_existed', 'issue_id', 'error'}. Was a (bool, str) tuple
# until 2026-08-18; callers want all five, and conflating them cost real duplicate to-dos:
#   created         Plane holds an issue for this article
#   verified        a follow-up GET actually found it. Separate from created on purpose --
#                   a read-back that fails after a successful create must NOT read as "not
#                   sent", or the retry files a duplicate
#   already_existed the article id is sent as Plane's external_id, so a repeat POST comes
#                   back 409 carrying the id Plane already holds. That is the only defence
#                   against a create whose response was lost: local state cannot tell that
#                   apart from a create that failed
#   error           never raises -- anything unexpected (malformed article, unreadable
#                   response) comes back here, because an exception escaping this function
#                   skips the caller's refresh and toast and strands its spinner
# Callers persist issue_id as intake_state's plane_issue_id, which is what makes the
# row/reader control a checkmark and guards the `s` shortcut against a resend.

issue_status(issue_id: str | None) -> str    # 'present' | 'gone' | 'unknown'
# Three-valued on purpose, and the only thing allowed to clear a plane_issue_id. A bool
# would have to fold "Plane is down" in with "Plane says it deleted that", and acting on
# that mistake deletes the article's only link to a live to-do -- so only a 404 counts as
# gone; 401/403/5xx/timeouts are 'unknown' and change nothing. _issue_exists() is now a
# thin `== 'present'` wrapper over it.

# services/repo_search.py + services/ai/discuss.py -- backing the Discuss panel
repo_search.repo_file_count() -> int
discuss.send_discuss_message(article, active_sources, text, history, model) -> dict | None   # {'text', 'tool_calls'}
discuss.placeholder_text(active_sources) -> str
discuss.grounding_footer(active_sources, model_label) -> str

# services/mods.py
get_mods() -> dict                                            # {mod_name: {history, version, submitted_by, submitted_at}}
get_staging() -> list[dict]                                   # [{id, meta, sub}]
approve_mod(sid: str, decided_by: str = "parent") -> dict     # {"success": True, "message"} | {"success": False, "error"}
reject_mod(sid: str, reason: str = "...", decided_by: str = "parent") -> dict

# services/media.py
get_queue(search: str = '', media_type: str = '', status: str = '') -> list[dict]
approve(item_id: str) -> tuple[bool, str]
reject(item_id: str) -> tuple[bool, str]
reclassify(item_id: str, new_type: str) -> tuple[bool, str | None]
edit(item_id: str, proposed_title: str | None = None) -> tuple[bool, str | None]
bulk_action(action: str, item_ids: list[str]) -> list[dict]   # exists, not wired to any UI yet
undo(item_id: str) -> tuple[bool, str | None]                  # exists, not wired to any UI yet
upload(filename: str, content: bytes) -> tuple[bool, str]      # exists, not wired to any UI yet
get_cover_path(item_id: str) -> str | None                     # exists, not wired to any UI yet — relevant to the "cover art" feature from DESIGN_BRIEF §8

# services/system.py
get_status() -> dict            # {defcon, containers, disk, memory, daemon_active}
get_logs(tail: int = 100) -> list[str]

# services/minecraft.py
get_status() -> dict            # {online, players, max_players, version} | {online: False, error}
get_status_text() -> str        # same info, pre-formatted for the AI tool

# services/settings.py
get_settings() -> dict          # API keys returned masked (first 8 chars + asterisks)
save_settings(data: dict) -> None   # values containing '*' are treated as "unchanged", not saved over the real value

# services/ai/chat.py
send_message(user_message: str, history: list[dict], model: str = 'agy', context_text: str = '') -> str
```

**Note on `services/media.py`, `bulk_action`/`undo`/`upload`/`get_cover_path` already
exist in the backend** but have no UI hooked up to them yet — these map directly to
unbuilt items in the Media Curator feature brief (bulk actions, undo, drag-and-drop
upload, cover art). The reskin doesn't need to write that backend logic, just wire pages
to what's already there.

## Verification after the reskin

1. Restart the service (`systemctl --user restart homelab-dashboard.service`), tail the
   log for import/startup errors.
2. Walk `FEATURE_INVENTORY.md` tab by tab — every checkbox should still work.
3. AI-context regression check (this is the part most likely to silently break in a
   reskin, since it depends on each page's exact `state` shape): open a specific article
   on Intake, ask the sidebar "summarize what I'm reading" on all three models, confirm
   it answers grounded in the actual open article and not a generic response. Repeat on
   at least one other tab with real data (e.g. Mods with a pending review).
4. Confirm destructive actions (article delete, media reject) still route through
   `confirm()` — easy to lose in a visual rewrite of the modal.
