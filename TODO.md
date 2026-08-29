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
  - [x] **Fixed `a329de8`.** Reader's action icons went stale after workflow toggles: clicking Favorite (from
    either the list row or the reader itself) updates the list row's highlight
    immediately, but the reader pane's own star doesn't repaint until something else
    rebuilds the reader (switching articles, opening Discuss, etc.). Cause is visible in
    `pages/intake.py`: `toggle_read`/`toggle_favorite`/`toggle_archived` call
    `_refresh_after_workflow_change()` (list row) but never `render_reader.refresh()`
    when the toggled article is the one open in the reader. State on disk is always
    correct — purely a repaint gap. Applies to the reader's Read/Archive icons too, and
    now also bites in Discuss mode since the action row shows there as well (2026-08-04
    change). Fixed inside `_refresh_after_workflow_change()` rather than in each of the
    three toggles, so a fourth cannot forget it. Two regression tests, both confirmed
    failing against the old code.
  - [x] **Fixed `a329de8`.** Failed queue entries gave no way to read/copy the error: clicking the entry
    just retries it, and the error text only exists as a hover tooltip ("RETRY n/3").
    Clicking now opens the full text — selectable, copyable, with the attempt count —
    and Retry moved one click further in. (Noted 2026-08-04 while triaging the
    Omega-unreachable failures.)

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

  **Feature backlog: `docs/LAB_HEALTH_FEATURES.md`** (2026-08-22) — P0–P4 in priority
  order, from Chris's framing that the page is for looking at everything and investigating
  further. P0–P3 are all derived-on-read from this box (docker / systemd / /proc / journald)
  and depend on `homelab-monitoring` for nothing; only P4 waits.

  What does NOT wait:
  - [x] **Phase 0.8 — done `ba101fa`.** Monitoring has its own home: the System Status tab
        became **Lab Health** (`pages/lab_health.py`, tab key still `system` so `?tab=`
        links survive), linking Uptime Kuma `:3001`, Dozzle `:8888` and ntfy `:5001`.
        The Kuma quick-link **moved off Media Curator** — Chris's call, 2026-08-22: it is
        not a media service and that stack stopped owning it at Phase 0.7. (`static/index.html`
        still has a Kuma link at :209, deliberately untouched — that file is dead legacy.)
  - [x] **F1 error stream + F4 units — done `ba101fa`.** journald errors from both managers,
        every failed unit, and containers exited non-zero, merged and collapsed by repeat;
        click for the full copyable text plus the command to dig further. Units list with
        state, restarts and a per-unit log tail. All readers fail closed (`{'ok': ...}`),
        so an unreadable source renders as "cannot tell", never as a quieter list.
        Suite 73 green.
  - [x] **F2 + F3 — done `2bf4b9c`.** P0 is complete. Containers group by compose project
        and open to state, their own healthcheck verdict, live `docker stats`, ports, mounts,
        output and a Dozzle link. Resources replaced the old three-card grid: CPU load,
        memory, disks and temperature, each clickable, with kernel pressure (PSI) on CPU and
        memory and swap exhaustion leading the memory card. Every card has a "cannot tell"
        face. Suite 100 green.
  - [ ] Next from `LAB_HEALTH_FEATURES.md`: P1 (freshness stamps, search/filter across
        everything) and P2 (correlation window, the bounded ring buffer for short-window
        rates). Nothing blocks either.

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

- [ ] **media-curator coupling — a change over there landed today that reaches in here (2026-08-22)**
  `services/media.py` does `sys.path.append('/home/linuxbox/projects/media-curator')` and imports
  that repo's internals directly: `database.get_conn`, `library.approve_item`/`reject_item`,
  `curator_daemon.identify_media`, `DROP_ZONE`, `is_contained`. No package boundary, no version
  pin, so a refactor there breaks this with no compile-time or test-time signal. That risk stopped
  being theoretical today.

  **What changed in media-curator (commits `1ebc6f4`, `8e817d3`):**
  - `queue.db` gained an `alert_state` table and `PRAGMA user_version` migrations. `get_conn()` is
    unchanged, so nothing here breaks — but this repo is now the **third writer** to that database
    (daemon, this app, and this app's AI assistant tool).
  - `check_exists(original_path)` is now `check_exists(original_path, file_hash=None)` and matches
    on status as well as path. It also **raises** on a database error instead of returning `False`.
    Nothing here calls it today — that was checked — but it is the bridge to watch.
  - The `UNIQUE` index on `original_path` was **dropped**, replaced by a partial unique index over
    `(original_path, file_hash)` that applies only to `pending` rows.
  - Two new statuses exist: `superseded` and `rejected_kept`. `static/app.js` filters explicitly on
    `'pending'`/`'approved'`, so neither renders in the active list — correct by luck, not design.

  - [x] **`undo()` fixed — `93aaaa4`.** It was worse than "would 500": the file moved
        *before* the unguarded `UPDATE`, so an `IntegrityError` against the new partial index
        left the file in the drop zone while the row still said approved at `proposed_path` —
        filesystem and database permanently out of sync, from a button press. The file is now
        moved back before the error is reported, the connection closes on every path, and a
        failure to restore says so naming both paths rather than stranding the file silently.
        (Found by agy's 2026-08-22 review of the week; confirmed against the code.)
  - [x] **Tests — `a329de8`.** The "zero tests" note was wrong: `pages/media.py` already had
        5 page-level tests. Added 3 more covering the gap that mattered — a service failure
        reaching the user rather than arriving as nothing — plus the 4 undo tests on the
        service side. `test_media_fixes.py` is at 12.
  - [ ] Still thin: nothing covers `reclassify()` or the Rejected folder.
  - [ ] **Dashboard side of the boundary:** name what this app actually needs from
        media-curator (approve, reject, reclassify, identify, the drop zone) and depend on
        that surface instead of reaching past `sys.path` into its internals — so a refactor
        over there fails loudly here. Doable from this repo alone against today's imports;
        it does not wait on media-curator publishing anything. Whether *they* expose a real
        package is theirs (their Epic 7, unowned) and is not tracked here.

- [x] **Fixed `a329de8` — `test_toggle_select_timing_with_large_queue` was flaky (2026-08-22)** — it asserts a
  wall-clock budget (`< 0.5s`) and fails intermittently on a loaded machine. Measured on clean
  `HEAD`, unrelated to any change: 2 of 3 consecutive runs failed. A timing threshold in a test
  suite that shares a host with a game server and a media daemon will keep doing this. Either
  raise the budget substantially, mark it as a benchmark that does not gate the suite, or
  measure work done rather than seconds elapsed. **Took the third option:** it is now
  `test_toggle_select_rebuilds_one_row_not_the_whole_queue`, asserting via element identity
  that the toggled row was rebuilt and the other 79 were not. Five consecutive green runs.

---

## Not this project (pruned 2026-08-29)

Chris's call: this backlog tracks the dashboard only. Work on the services the dashboard
*looks at* belongs to the project that owns them. Recorded here so it is handed over rather
than dropped — none of it is tracked in this repo any more.

**→ `media-curator`** (its stack, its configuration; nothing below touches dashboard code)
- Connect Prowlarr indexers to Radarr & Sonarr.
- Link Radarr & Sonarr to qBittorrent via API keys.
- Claim the Plex server and configure library folders (`/data/media`).
- Whether media-curator exposes a real package/API instead of importable internals — its
  Epic 7, unowned. The dashboard-side half of that boundary *is* still tracked above.

**→ `homelab-monitoring`** (it owns detection and alerting; Kuma and ntfy moved there at
HomeLab BUILD_BACKLOG Phase 0.7)
- Uptime Kuma alert configuration. The old note said Discord/Telegram webhooks; M1
  standardises on self-hosted ntfy, so that item was stale as well as misplaced.
- Somewhere alerts land and can be acknowledged. This one was not just misfiled, it was
  against the rule: **the dashboard informs and investigates, it does not detect or alert.**
  A page you have to be looking at is not a detector. Alert delivery is ntfy's, and M1
  (subscribe a phone to `homelab-alerts`) is Chris's.

What stays here: rendering Kuma/Dozzle/ntfy quick-links, showing media-curator's queue on the
Media Curator page, and everything in `docs/LAB_HEALTH_FEATURES.md` — including P4, whose
screens are this dashboard's even though they wait on homelab-monitoring for check output.
