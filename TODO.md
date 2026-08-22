# Homelab Dashboard TODOs

- [x] **AI Assistant Sidebar Integration**
  - [x] Add a collapsible tab to the right side of the screen.
  - [x] Implement a chat interface allowing interaction with an LLM.
  - [x] Provide a model selector to switch between Claude, Agy, and a local model.
  - [x] Give the LLM context of what the user is currently looking at on the dashboard.
  - [x] Grant the LLM capabilities/tools to discuss the dashboard state, make changes to the dashboard, and manage the homelab.

- [x] **Media Stack (Backend & Security)**
  - [x] Deploy 15-container stack (Plex, *arrs, VPN).
  - [x] Enforce strict Gluetun Killswitch on qBittorrent.
  - [x] SRE Hardening (Docker Socket Proxy, Autoheal labels, Resource Limits).
  - [x] Wire live monitoring into Dashboard (DEFCON banner, container states).

- [ ] **Article Intake (Tag Filtering)** — ⏸ ON HOLD (Chris, 2026-08-02; revisit later)
  - [ ] Add a dedicated tag-filter UI to the article intake tab — tags currently only match via the free-text search bar, no way to browse/filter by tag directly.
  - [ ] Decide on presentation (filter chips, tag cloud, etc.) alongside the existing Homelab/News/Errors folder sidebar.

- [ ] **Article Intake — investigate (noted 2026-08-04, from Chris's live testing)**
  - [ ] Reader's action icons go stale after workflow toggles: clicking Favorite (from
    either the list row or the reader itself) updates the list row's highlight
    immediately, but the reader pane's own star doesn't repaint until something else
    rebuilds the reader (switching articles, opening Discuss, etc.). Cause is visible in
    `pages/intake.py`: `toggle_read`/`toggle_favorite`/`toggle_archived` call
    `_refresh_after_workflow_change()` (list row) but never `render_reader.refresh()`
    when the toggled article is the one open in the reader. State on disk is always
    correct — purely a repaint gap. Applies to the reader's Read/Archive icons too, and
    now also bites in Discuss mode since the action row shows there as well (2026-08-04
    change). DON'T fix blind: Chris is mid-testing and collecting more behavior notes —
    batch them, then investigate together.
  - [ ] Failed queue entries give no way to read/copy the error: clicking the entry
    just retries it, and the error text only exists as a hover tooltip ("RETRY n/3").
    Chris wants to be able to see and copy/paste the full error. (Noted 2026-08-04
    while triaging the Omega-unreachable failures below.)

- [ ] **Media Stack (Frontend & GUI Config)**
  - [ ] Connect Prowlarr indexers to Radarr & Sonarr.
  - [ ] Link Radarr & Sonarr to qBittorrent via API keys.
  - [ ] Claim Plex server and configure library folders (`/data/media`).
  - [ ] Setup Discord/Telegram Webhook alerts inside Uptime Kuma.
    (Note: Uptime Kuma is no longer part of the media stack — see the
    monitoring item below. Its alerting is now gated on homelab-monitoring's
    M1, which standardises on self-hosted ntfy rather than Discord/Telegram.)

- [ ] **Monitoring / lab health home on the dashboard (2026-08-22)** — one place to see
  whether the lab is healthy, rather than the pieces scattered across pages. Merged from
  two notes written the same day: Chris's ask for a single health/status/usage/alerts/errors
  surface, and the fallout from the Phase 0.7 move.

  Uptime Kuma, Dozzle, socket-proxy and autoheal moved out of `media-curator`
  into the `homelab-monitoring` project on 2026-08-22 (HomeLab BUILD_BACKLOG.md
  Phase 0.7). The dashboard has no surface of its own for them: the only entry
  point is the Uptime-Kuma quick-link parked on the **Media Curator** page
  (`pages/media.py:28`, `static/index.html:209`), which now points at a service
  that page no longer owns. Dozzle (`:8888`) has no link at all.

  The other half already exists but only partly: `pages/system.py` renders
  `services.system.get_status()` — a DEFCON list (mount down, <5% free, Gluetun collapsed,
  media-curator inactive), `docker ps` container cards, `/mnt/Multimedia` disk usage, Plex's
  memory line, and `get_logs()` for a log tail. Decide whether that page becomes this home
  or sits beside it.
  - [ ] Give monitoring its own section or page (Uptime Kuma `:3001` +
        Dozzle `:8888`) rather than borrowing another project's page.
  - [ ] Once it exists, decide whether the Media Curator quick-link stays as a
        convenience or moves. Deliberately left working in the meantime —
        removing it would have cost a shortcut and returned nothing.
  - [ ] Lab health at a glance: one honest up/degraded/down verdict per service, not just
        a container's own `Status` string — a running container is not a working service.
  - [ ] System status beyond the media stack: host uptime, load, the other systemd units,
        Tailscale reachability (Omega at `100.74.2.92`, the bridge service), NAS mount.
  - [ ] Resource usage: host CPU / RAM / temps and per-container stats. `docker stats` is
        only read for Plex today, and nothing is kept over time — no trend, so a slow leak
        or a filling disk is invisible until it trips a DEFCON threshold.
  - [ ] Notifications: somewhere alerts actually land and can be acknowledged. The DEFCON
        banner only shows while you happen to be on the page, and Kuma's alerting is gated
        on homelab-monitoring's M1 (self-hosted ntfy, not Discord/Telegram).
  - [ ] Error reporting: a real surface for failures with the full text readable and
        copyable — this is the general form of the intake failed-queue complaint above,
        where the error survives only as a hover tooltip.

- [ ] **Send to HomeLab — hardening (2026-08-18)** — full plan and findings live in
  `homelab-intake/TODO.md` ("Send to HomeLab + its support systems"); this is the
  dashboard-side slice of it. Four fixes are committed (`f489f8f` label failure no longer
  sinks the send, `181752e` toasts survive a handler refreshing its own row, `6fffbc5`
  issue id recorded + read back + checkmark, `ca6334c` idempotent resend via Plane's
  `external_id` — a repeat POST returns 409 with the id Plane already holds, proven against
  live Plane — plus a catch-all so nothing unexpected escapes the send and leaves the row's
  spinner turning forever). Suite green at 48; pushed and live on the running service as of
  2026-08-22. Still open here:
  - [ ] Reconcile recorded `plane_issue_id`s against Plane so a to-do deleted there clears
    the article's checkmark — today verification runs only at send time.
  - [ ] No project picker: every article goes to the one project in `.env`.
  - [ ] A sent article's to-do is write-once; nothing updates it afterwards.
