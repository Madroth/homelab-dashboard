# OmegaLab Dashboard — Product Brief for Claude Design

Single self-contained reference for a Claude Design session redesigning this dashboard's
UI. **This document intentionally contains no aesthetic or visual direction** — no
colors, fonts, or style guidance. All graphic and aesthetic decisions are Claude Design's
to make. Everything below is functional/product context only: what the app does, who
uses it, what data it holds, and what has to keep working. Design against the real data
shapes in §4, not placeholder content — the schemas here are final, pulled directly from
the current backend, not draft.

The actual source code (`pages/`, `components/`, `services/`) is included alongside this
doc — reference it directly for anything not covered here.

## 1. What this is

A single-page, tab-based control panel for a self-hosted homelab: article intake/reading,
a Minecraft mod-approval pipeline, a media curation queue (movies/TV/books/comics
auto-sorted into Plex), system health, and an AI assistant that can see whatever tab is
open and act on it. One user, desktop-first — driven from a browser tab left open, not a
phone.

## 2. Constraints

Built in **NiceGUI** (Python; renders to Vue/Quasar under the hood), not hand-written
HTML/React — whatever comes out of this design session gets translated into NiceGUI
components afterward. Implications:

- Prefer standard layout patterns (flex columns/rows, cards, sidebars, modals, tabs) over
  bespoke CSS/JS-heavy interactions — those map cleanly to NiceGUI.
- Design against mock data shaped **exactly** like the real data in §4, not Lorem Ipsum.
- Avoid designing around live-push/websocket-only interactions that aren't already
  there — current data refresh is polling (a timer), not a live stream.

## 3. Navigation & pages

| Tab key | Label | Purpose |
|---|---|---|
| `home` | Dashboard | Landing/overview — currently just a Minecraft status card, meant to grow |
| `intake` | Article Intake | Read/triage saved articles (folder list + search + reader pane) |
| `mods` | Mod Pipeline | Review/approve/reject submitted Minecraft mods, AI-written reviews |
| `media` | Media Curator | Approve/reject/reclassify auto-sorted media |
| `settings` | Settings | API keys (Claude/Gemini/Ollama) for the AI assistant |
| `system` | System Status | Docker container health, disk space, DEFCON-style alert banner, daemon log tail |

Disabled/planned-but-not-built nav items already reserved in the sidebar: **Containers**,
**Network**.

Persistent "Quick Links" (external services, open in new tab): Crafty Controller, Plane,
Freqtrade (global sidebar); on the Media tab specifically: Radarr, Sonarr, Prowlarr,
Bazarr, Tautulli, Pulsarr, Uptime-Kuma, qBittorrent, Plex.

## 4. Real data shapes per page

### Article Intake

> **Superseded** — this subsection describes the tab as of the original 2026-07-22
> reskin. A dedicated Design pass shipped 2026-07-25 (custom folders, tag filtering,
> bulk actions, cards/table view, keyboard shortcuts, Send to HomeLab) and a follow-on
> AI Discuss mode + bug-fix pass landed since. **`INTAKE_UPGRADE_BRIEF.md` is the
> current source of truth for this tab** — use it instead of the rest of this
> subsection, which is kept only as a historical record of the original brief.

Three-pane: folder list (All/Homelab/News/Errors, with live counts) + search → article
list → reader pane.

```python
article = {
  'id': str,               # filename, e.g. "2026-07-22-193726-Some-Title.md"
  'title': str, 'date': str, 'source': str,          # source = URL
  'snippet': str,           # short auto-summary, boilerplate stripped
  'is_duplicate': bool, 'auto_generated': bool,
  'category': 'Homelab' | 'News',
  'tags': list[str],
  'content_type': str, 'primary_domain': str,        # richer schema, not yet in UI
  'priority_score': float, 'why_it_matters': str,     # richer schema, not yet in UI
  'status': 'Inbox' | 'Queued' | 'Read' | 'Archived',
}
queue_item = {'id', 'url', 'status': 'pending'|'processing'|'failed'|'done',
              'auto_generated', 'added_at', 'retry_count', 'last_error', 'finished_at'}
```

Actions: click article → open in reader (full markdown), Delete / Toggle Duplicate /
Resubmit. Failed queue items are click-to-retry.

**Known gaps:** `content_type`, `primary_domain`, `priority_score`, `why_it_matters` exist
in the data but aren't surfaced in the UI at all yet — a real opportunity here. There's
also an open backlog item for a dedicated tag-filter UI (tags currently only match via
free-text search, no way to browse/filter by tag directly).

### Mod Pipeline
Two grids: pending review, then history.

```python
staging_item = {'id': str, 'meta': {'name', 'version', 'ai_review': str},
                'sub': {'submitted_by', 'sha256', 'arrived_at'}}
history_item = {'name': str, 'version', 'submitted_by', 'submitted_at',
                'history': [{'submitted_at', 'decided_by'}]}
```

Actions: Read AI Review (modal, markdown), Approve, Reject (with reason prompt).

### Media Curator
Flat queue list, click for detail modal.

```python
media_item = {
  'id': str, 'status': 'pending' | 'approved',
  'media_type': 'movie'|'tv_show'|'ebook'|'audiobook'|'comic',
  'original_filename': str, 'proposed_title': str, 'proposed_path': str,
  'needs_intervention': bool, 'created_at': str,
  'metadata': {'year', 'franchise', 'short_description', 'long_description', 'sort_logic'},
}
```

Actions today: Approve, Reject/Delete, Edit Title, Reclassify (dropdown, moves file).
**See §7 below** for a fuller feature list for this specific page.

### System Status
```python
status = {
  'defcon': list[str],                     # critical alert banner text, e.g. "VPN_DOWN: ..."
  'containers': [{'Names', 'Status', ...}],  # raw `docker ps` JSON per container
  'disk': {'total', 'used', 'free', 'free_pct'},
  'memory': {'plex': '512MiB / 4GiB'},
  'daemon_active': bool,
}
logs: list[str]   # last 100 lines of a daemon log, rendered as a code block
```

### Home
Currently just one Minecraft card: `{'online': bool, 'players', 'max_players', 'version'}`
or `{'online': False, 'error': str}`. This is the thinnest page — it's meant to become a
real "what needs my attention across everything" overview and isn't one yet.

### Settings
API key inputs for Claude, Gemini ("Agy"), and Ollama host/model.

## 5. The AI Assistant sidebar

A collapsible right-hand panel (toggled by a wand icon in the top bar), with a
Claude/Agy/Local model picker and a chat input. It's functional, not decorative:

- Automatically knows what's on the active tab (open article, pending mod count, media
  queue, container health, etc.) — no need to re-explain context to it.
- Has real tools: search the article archive, list/approve/reject mods and media, check
  Minecraft status.
- No streaming yet (spinner → full reply) — intentionally deferred, not a bug.

This is currently the least-developed surface in the app (narrow fixed-width slide-out,
plain chat bubbles) and a good redesign target — the redesign needs to keep: the model
picker, some visible indication that the AI has access to the user's current view (new
capability, currently invisible to the user), and room for tool-call activity to be
legible (tool calls currently happen silently; the user only sees the final answer).

## 6. Known pain points

The user has flagged the current UI as having problems without yet itemizing which —
worth a first review pass through each tab to pin down specifics, rather than assuming.
Functionally: Home is nearly empty, Intake doesn't surface half its own data schema, and
the chat sidebar is the least developed surface in the app.

## 7. Media Curator — fuller feature list

This page has more detailed requirements than any other tab, from a prior feature-planning
pass:

**Must support today:** Split views (Curated vs. Pending queue); media cards showing
proposed title, media type, timestamp; a details view with original filename vs. target
library path, short/long AI-generated descriptions, franchise/series groupings, the AI's
sorting reasoning, and controls for Reclassify, Edit Title, Reject/Delete, Approve.

**Feature roadmap not yet built:**
1. Cover art & thumbnails on media cards
2. Advanced search & filters (media type, year, recently added)
3. Bulk actions — select multiple items, act on all at once (approve/reject/reclassify)
4. Undo/rollback for an already-approved item
5. In-browser audio/video preview
6. Drag-and-drop upload
7. Duplicate-resolution flow — handling version collisions (e.g. two copies of the same
   movie at different quality)
8. Disk space & daemon status visibility
9. Custom tagging that syncs to Plex collections
10. Live daemon activity/audit log

**External service integrations to link to:** Plex/Jellyfin, Radarr, Sonarr, Readarr,
Lidarr, Prowlarr, qBittorrent/Deluge, SABnzbd/NZBGet — needs a better presentation than a
plain hyperlink list.

## 8. Open roadmap items worth designing room for

- Tag-filter UI on Article Intake (see §4)
- *arr-stack integration completion (Prowlarr↔Radarr/Sonarr, qBittorrent API keys, Plex
  library claim) — infra work, not a UI task, but the Media tab's design should assume
  these will be live and reflected in status somewhere
- Uptime Kuma alerting hookup (Discord/Telegram) — may surface as a notification
  affordance somewhere in the shell if that's a good fit
