# Feature Inventory — OmegaLab Dashboard

Every interactive behavior currently implemented, page by page. This is the parity
checklist for a reskin: after wiring new visuals from Claude Design, walk this list and
confirm each item still works — a redesign should carry all of it forward unless a
change is deliberate, not a silent drop.

Companion docs: `DESIGN_BRIEF.md` (what Claude Design needs), `IMPLEMENTATION_GUIDE.md`
(architecture patterns + service contracts for wiring the new visuals to existing logic).

## Global shell (`components/layout.py`, `nav_sidebar.py`)

- [ ] Left nav: 6 tabs (Dashboard / Article Intake / Mod Pipeline / Media Curator /
      Settings / System Status), active tab highlighted
- [ ] Tab state persists in the URL (`?tab=intake`) and survives a page reload
- [ ] Two disabled/reserved nav items shown but not clickable: Containers, Network
      (placeholders for future pages)
- [ ] Quick-links block (Crafty Controller, Plane, Freqtrade) — opens in a new tab
- [ ] "System Operational" pulse indicator at the bottom of the nav
- [ ] Top bar: AI toggle button (wand icon) opens/closes the chat sidebar; user-avatar
      placeholder circle ("P")

## AI Assistant sidebar (`components/chat_sidebar.py`, `services/ai/*`)

- [ ] Collapsible right-hand panel, slides in/out (not a separate page/route)
- [ ] Model picker: Claude / Agy / Local — switching models mid-conversation is allowed
- [ ] Chat history renders in-panel (user bubbles right-aligned/accent, model bubbles
      left-aligned with markdown rendering, error bubbles in red) — history is
      **client-side only**, lost on refresh (not currently persisted)
- [ ] Spinner shown while waiting for a reply; textarea + send button (click or Enter)
- [ ] The assistant automatically knows what's on the active tab (open article, pending
      mod count, media queue, container health, etc.) with no user action required
- [ ] The assistant can call real tools: search the article archive, list/approve/reject
      mods and media items, check Minecraft status — all three models share the same
      tool set
- [ ] No token streaming — full reply appears at once after the spinner (intentional,
      not a bug, per prior scoping conversation)

## Home / Dashboard (`pages/home.py`)

- [ ] Minecraft server status card: online → player count + version; offline → error
      message
- [ ] Auto-refreshes every 10s, plus once immediately on page load
- [ ] **Thinnest page today** — meant to become a cross-page "what needs my attention"
      overview; current version only shows one card

## Article Intake (`pages/intake.py`, `services/intake.py`)

- [ ] Folder sidebar: All / Homelab / News / Errors & Rejections, each with a live count
- [ ] Free-text search — matches against title, snippet, tags, and full raw content
- [ ] Queue panel above the article list:
  - [ ] Failed items shown first, red-tinted, click-to-retry
  - [ ] Active items (pending/processing) shown with a retry-count badge when applicable
- [ ] Article list: badge (Duplicate / Automated / Manual), date, title, source domain
      (parsed from URL), snippet, up to 3 tags
- [ ] Empty states: "No articles match '\<search\>'" vs "No articles found."
- [ ] Click an article → loads full content into the reader pane (async, shows a spinner
      while loading)
- [ ] Reader pane actions: **Delete** (behind a confirm dialog), **Toggle Duplicate**,
      **Resubmit** (re-queues by the article's original source URL, notifies
      success/failure)
- [ ] Empty reader state: "Select an article to read"
- [ ] **Data not yet surfaced anywhere in the UI**, present in the schema:
      `content_type`, `primary_domain`, `priority_score`, `why_it_matters` — worth
      exposing in the reskin, not just re-skinning what's already shown
- [ ] Known open backlog item (not yet built): dedicated tag-filter UI — tags currently
      only match via the free-text search box

## Mod Pipeline (`pages/mods.py`, `services/mods.py`)

- [ ] Pending-review grid: mod name + version badge, "by \<submitter\> · \<date\>",
      truncated sha256 hash (monospace)
- [ ] "Read Review" button → modal showing the full AI-generated review (markdown)
- [ ] Approve button → deploys the mod (moves through staging → approved → deployed,
      updates the registry)
- [ ] Reject button → prompts for a rejection reason (textarea), moves to review folder
- [ ] Pipeline-history grid: previously deployed mods, version badge, submitter/date,
      "Approved \<date\> · deployed by \<decided_by\>"
- [ ] Empty states for both grids
- [ ] Manual reload after every approve/reject

## Media Curator (`pages/media.py`, `services/media.py`)

- [ ] Quick-links row: 9 external service icons (Radarr, Sonarr, Prowlarr, Bazarr,
      Tautulli, Pulsarr, Uptime-Kuma, qBittorrent, Plex) — opens in a new tab
- [ ] Queue list, two visual states per row:
  - [ ] **Approved** items: compact row, click opens the details modal
  - [ ] **Pending** items: fuller card with year, "NEEDS REVIEW" badge when flagged,
        inline Approve / Edit Title / Reject buttons
- [ ] Details modal (approved items): category reclassify dropdown (moves the file and
      re-runs identification on change), original filename vs. target path, franchise,
      short description, long description, sort logic/reasoning, Reject/Delete, Close
- [ ] Edit Title modal (pending items): text input, Cancel/Save
- [ ] Reject/Delete requires confirm dialog
- [ ] Empty state: "Queue is empty. Waiting for media..."
- [ ] Auto-refreshes every 5s, plus once on load
- [ ] **Not yet built** (see `DESIGN_BRIEF.md` §8 for the full original feature brief on
      this page specifically): cover art/thumbnails, advanced search/filters, bulk
      actions, undo/rollback, in-browser preview player, drag-and-drop upload,
      duplicate-resolution center, disk-space widget, custom tagging, live audit log

## System Status (`pages/system.py`, `services/system.py`)

- [ ] DEFCON alert banner — red, only rendered when at least one alert string is present
      (e.g. storage critical, VPN down, daemon crashed)
- [ ] Container health grid — one card per Docker container, color-coded (green/amber/red
      by status text)
- [ ] Three metric cards: disk free/total for `/mnt/Multimedia`, Plex memory usage
      (with a hard-limit label), daemon active/inactive status
- [ ] Daemon log tail — last 100 lines, rendered as a code block, manual refresh button
- [ ] Auto-refresh: container/metric data every 15s + once on load; log tail loads once on
      load (manual refresh only, no polling)

## Settings (`pages/settings.py`, `services/settings.py`)

- [ ] Four fields: Gemini API key (masked, toggleable), Anthropic API key (masked,
      toggleable), Ollama Host, Ollama Model
- [ ] Save button persists all four; existing masked values are preserved (re-saving
      doesn't overwrite a key with a masked placeholder — see `services/settings.py`)
- [ ] Loads existing saved values on page open
- [ ] Purely a form today — no visual grouping/help text beyond the section header

## Explicitly out of scope / dead code

- [ ] `app.py` (Flask, ~1000 lines) and `static/` (`app.js`, `index.html`, `style.css`) —
      the pre-NiceGUI version of this dashboard. **Not running, not imported by anything
      in the live app.** Don't try to reconcile or migrate anything from it; the NiceGUI
      stack (`main.py` → `components/` → `pages/` → `services/`) is the only live
      implementation.
