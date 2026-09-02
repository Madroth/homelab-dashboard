# Project status — resume point

**Last updated:** 2026-08-29 · **HEAD:** `08b8ee3` plus this backlog prune · service
`homelab-dashboard.service` **active** on :8085, running that code. Not yet pushed — pushing to
`Madroth/homelab-dashboard` needs Chris's sign-off each time (ADR 7, Tier 2).

Read this first when picking the project back up. `TODO.md` is the full backlog;
`docs/LAB_HEALTH_FEATURES.md` is the prioritized plan for the monitoring page. This file is
just "where things stand and what to do next".

## Where things stand

**Tests: 100 passing** (`./venv/bin/python -m pytest -q`, ~40s). Split: `test_intake_fixes.py`
61, `test_lab_health.py` 27, `test_media_fixes.py` 12. No known flaky tests — the one that was
(`test_toggle_select_timing_with_large_queue`) was rewritten to assert work done instead of
wall-clock and now runs green repeatedly.

**Lab Health page — P0, P1 and P2 complete.** P1 gave every panel an "as of" stamp that
ages into amber on its own timer, and one filter box across errors, units and containers
that cannot make the lab look healthier than it is. P2 added a 60-sample in-process ring
buffer (dropped on restart, never persisted, never alerted on) and the correlation window
on an error detail. Both refuse to answer rather than guess when the readings are thin.

**Originally, P0:** The old System Status tab was absorbed into
`pages/lab_health.py` (tab key is still `system`, so `?tab=system` links and the `ai_context`
registration keep working). It has:

- an **error stream** merged from journald (`-p err`, both systemd managers), failed units, and
  containers exited non-zero — collapsed by repeat, click for full copyable text plus the
  command to dig further
- a **units list** with state, restarts and a per-unit log tail
- **containers** grouped by compose project, click for state, the container's own healthcheck
  verdict, live `docker stats`, ports, mounts, output and a Dozzle link
- **resources** — CPU, memory, disks, temperature, each clickable, with kernel pressure (PSI)
  and swap exhaustion surfaced
- links to Uptime Kuma `:3001`, Dozzle `:8888`, ntfy `:5001`

**Send to HomeLab is done as a correctness effort.** Idempotent via Plane's `external_id`,
create/verify reported separately, the checkmark re-checkable against Plane, and nothing can
escape the handler and strand a spinner. Only feature gaps remain (no project picker; a sent
to-do is write-once).

## The one contract to preserve

Every reader in `services/system.py` returns `{'ok': bool, ..., 'error': str | None}`, and the
UI has a third state — "Cannot tell", dashed panel — distinct from healthy and broken. This is
not stylistic. The page it replaced reported the root SSD's free space as the NAS for three days
because an unreadable source rendered as a plausible number. **Any new reader follows this, and
you design the "cannot tell" face before the healthy one.** Same reasoning behind
`plane.issue_status()` being three-valued rather than a bool.

## What to do next

1. **Lab Health P3, remainder** — SMART (F13), backups (F15), remote hosts (F16). F14 and
   host uptime are done. Also still open: rolling per-container health up to a service-level
   verdict, where a container with no healthcheck needs an answer that is not "healthy".
2. **`reclassify()` and the Rejected folder have no tests.** `test_media_fixes.py` covers undo
   and the failure-surfacing paths; those two are the remaining gaps.
3. **Give `services/media.py` a defined boundary** — it imports media-curator's internals over
   `sys.path.append` with no package boundary and no version pin, which is what made this week's
   `undo()` data-integrity bug possible. The dashboard-side fix — name the surface this app needs
   and depend on that, so a refactor over there fails loudly — is doable from this repo alone.
   Whether media-curator publishes a real package is *their* Epic 7 and is not tracked here.

## Scope — this repo tracks the dashboard only

Decided 2026-08-29. Configuring the services the dashboard *looks at* is the owning project's
work: media stack setup (Prowlarr/Radarr/Sonarr/qBittorrent/Plex) is `media-curator`'s, and
Uptime Kuma alert configuration and alert delivery are `homelab-monitoring`'s. `TODO.md` has a
"Not this project" section recording what was pruned and where it went. Rendering links to those
services, and showing their state on Lab Health, is dashboard work and stays.

## Hard constraints — do not relitigate

From `~/HomeLab/MONITORING.md`, which governs the monitoring work and records why two
predecessor projects died:

- **No Prometheus/Grafana/time-series database. No trend charts.** Displaying a live value on
  demand is fine and is not the same thing. The ring buffer in P2 is the ceiling.
- **No alerting from the dashboard.** A page you have to be looking at is not a detector.
  Alerts belong to ntfy and `homelab-monitoring`.
- **No log-scraping alerts.** Reading logs on demand is the point.
- **No auto-remediation beyond a container restart.**
- **Anything registry-driven waits** — per-subject coverage, check pass/fail, staleness, root
  fixes. There are 27 declared subjects and 0 live checks, so there is no check *output* to
  display yet, and its shape will decide those screens. Design is parked in
  `docs/MONITORING_BRIEF.md` and a canvas at
  https://claude.ai/code/artifact/162c3a93-1e9b-431f-bd0f-6d8458e04532 — do not redo it, and do
  not build against it yet.

## Environment notes

- Run: `systemctl --user restart homelab-dashboard.service` (NiceGUI runs `reload=False`, so
  code changes need a restart), `journalctl --user -u homelab-dashboard.service -f` to watch.
- `psutil` is **not** installed; `/proc` and `/sys/class/thermal` cover what the resource panel
  needs. `smartctl` and `iostat` are present, `lm-sensors` is not. There **is** a discrete GPU
  (GeForce GTX 680M) but nothing can use it: Kepler, compute capability 3.0, below Ollama's 5.0
  floor, and the last driver branch supporting it (470.xx) is EOL and will not build against
  this kernel. Ollama runs CPU-only here and logs `offloaded 0/13 layers to GPU`. Treat the box
  as GPU-less for planning, but do not record it as having no GPU — that sent one session
  looking for hardware that is physically present and simply unusable.
- `docker stats --no-stream` across 37 containers takes 1–2s — fetch per-container on drill-down,
  never synchronously in a render. The error read is cached 20s.
- This repo is **not** the one `github-plane-sync` watches (that is `Madroth/Homelab`), and
  `TODO.md` is not published anywhere. The dashboard's own Plane writes are articles, not tasks.

## Live lab state worth knowing (2026-08-30)

- **Omega's Ollama is not answering on `100.74.2.92:11434`** — found by F14 the moment it was
  built, and confirmed by hand: `tailscale ping Omega` returns instantly, so the host is up
  and the tailnet is fine, but the API does not answer inside 15s. The AI sidebar's local/agy
  model path depends on this, and `~/shared/ask-omega.py` will be failing too. Omega is
  Windows, RDP-only by policy — restarting the Ollama service is Chris's to do. This is
  exactly the failure class F14 exists for: a host that answers at the network layer while
  its service is dead.

## Live lab state from 2026-08-23 (recheck before trusting)

None of this is a dashboard bug — it is what the dashboard is now showing:

- **3 units failed**: `plane-backup.service` (has never once succeeded; blocked by RF-1 because
  the hostname `qnap2` does not resolve), `livescore.service`, `snap.tailscale.tailscaled.service`.
- **Memory** — 30 GB total with ~11 GB available and swap ~2.9 of 4 GB used (2026-09-01). The
  RAM was upgraded at some point; earlier handoffs said 15 GB total with 2 GB free and were
  read forward for a week after they stopped being true.
- **CPU package around 72–76 °C.**
- The **NAS flapped** on 2026-08-22 afternoon — repeated `CIFS: VFS: ... has not responded in 180
  seconds` while the mountpoint check kept passing. Quiet since. This is exactly the class of
  failure the error stream exists to surface.
- **ntfy now reaches a phone** — Chris confirmed the subscription to `homelab-alerts` on
  2026-08-29, closing `homelab-monitoring`'s M1. (Superseded the long-standing note here that
  `subscribed_by` was empty and every failure stayed silent.) Detection has somewhere to land
  at last, which is what lets this page stay an investigation surface rather than drifting
  into alerting.
