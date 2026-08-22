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

  **Sequencing decided 2026-08-22 (Chris). Most of this waits for the monitors.** The
  design work is done and parked: `docs/MONITORING_BRIEF.md` (24 features in four tiers,
  grounded in `~/HomeLab/MONITORING.md` and the coverage registry) plus a four-artboard
  canvas at https://claude.ai/code/artifact/162c3a93-1e9b-431f-bd0f-6d8458e04532. Do not
  redo either; do not build against them yet.

  Why it waits: 0 of 8 declared checks are live, so there is no check *output* to design
  against — what a live check returns (status, last-run, error text, grace countdown) is
  settled by M1/M2 and determines the subject table more than any layout choice does. The
  build backlog says the same thing under "Suggested cut lines": **"Defer freely: M7"**,
  and M7 is this. Anything registry-driven — subject table, coverage/staleness, check
  states, root-fix list — waits for real checks.

  **Chris's framing for what the page is for (2026-08-22):** the dashboard is where he
  looks at *everything* and investigates further — so its job is surfacing errors and
  drilling into them, not reassurance. It is deliberately NOT a detector: under
  MONITORING.md's one principle a dashboard cannot be one, and Uptime Kuma ran for months
  with a fine UI and zero monitors while seven failures went unseen. Detection is the
  phone's job (ntfy, M1); investigation is this page's.

  What does NOT wait — build these two:
  - [ ] Phase 0.8, explicitly ungated ("not a monitor, so M1 does not gate it"): monitoring
        gets a home with Uptime Kuma `:3001` and Dozzle `:8888`, and the Media Curator
        quick-link decision gets recorded either way.
  - [ ] The floor, all computable today with no monitoring system: failed units
        (`systemctl list-units --state=failed`, both managers), mount truth
        (`os.path.ismount`), container health (`docker ps -a`), capacity
        (`shutil.disk_usage`). `services/system.py` already does three of the four. Not
        hypothetical — `plane-backup.service`, `livescore.service` and
        `snap.tailscale.tailscaled.service` are failed right now and nothing says so.

- [ ] **Send to HomeLab — hardening (2026-08-18)** — full plan and findings live in
  `homelab-intake/TODO.md` ("Send to HomeLab + its support systems"); this is the
  dashboard-side slice of it. Four fixes are committed (`f489f8f` label failure no longer
  sinks the send, `181752e` toasts survive a handler refreshing its own row, `6fffbc5`
  issue id recorded + read back + checkmark, `ca6334c` idempotent resend via Plane's
  `external_id` — a repeat POST returns 409 with the id Plane already holds, proven against
  live Plane — plus a catch-all so nothing unexpected escapes the send and leaves the row's
  spinner turning forever). Suite green at 48; pushed and live on the running service as of
  2026-08-22. Still open here:
  - [x] Reconcile recorded `plane_issue_id`s against Plane so a to-do deleted there clears
    the article's checkmark. Clicking the checkmark re-checks that one to-do
    (`plane.issue_status()`, three-valued so an unreachable Plane can never be read as
    "deleted"); gone clears the flag and restores the send control. This also closed a
    dead end the hardening pass had created: nothing cleared `plane_issue_id`, and the
    control it drives refuses to resend, so a to-do deleted in Plane left the article
    permanently unsendable short of hand-editing `intake_state.json`.
  - [ ] No project picker: every article goes to the one project in `.env`.
  - [ ] A sent article's to-do is write-once; nothing updates it afterwards.
