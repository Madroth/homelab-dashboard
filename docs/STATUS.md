# Project status — resume point

**Last updated:** 2026-09-11 · service `homelab-dashboard.service` on :8085 · pushes to
`Madroth/homelab-dashboard` need Chris's sign-off each time (ADR 7, Tier 2).

Read this first when picking the project back up. `TODO.md` is the full backlog;
`docs/LAB_HEALTH_FEATURES.md` is the prioritized plan for the monitoring page. This file is
just "where things stand and what to do next". The session handoffs
(`sessionctl resume --slug homelab-dashboard`) carry the per-session detail.

## Where things stand

**Tests: see the last commit message for the count** (`./venv/bin/python -m pytest -q`,
~90 s). This file stopped carrying a number because it went stale for two weeks: it said 100
while the suite was at 186. Every failing test now leaves a report in `.test-failures/`
(gitignored) with the traceback, the logs, what the simulated user saw and the host's load.
That is how the media flake was finally caught — see below.

**The media UI flake is explained and fixed (2026-09-11).** It was never the harness's retry
budget. The page's 5 s poll rebuilt the whole queue whether or not anything had changed, and
a rebuild deleted whatever dialog was open (NiceGUI ties a dialog's lifetime to a canary
placed where the click happened) and whatever button was about to be clicked. On the live
page that meant the Edit Title box vanished mid-typing. Fixes: `components/page_dialog.py`
for every dialog in the app, a poll that skips unchanged data, `capture_client()` in the
media handlers, and no double reload on page open (NiceGUI repeating timers fire at once by
default, so Media, Home and Lab Health all ran their readers twice). Details are in
`TODO.md`.

**Lab Health page — P0 through P3 complete.** P4 (registry-driven) is still parked:
homelab-monitoring has live Prometheus/Alertmanager rules, but its registry lists 0 live
checks and nothing links the two yet (rechecked 2026-09-11).

**Send to HomeLab** is done as a correctness effort (idempotent, create/verify reported
separately, three-valued re-check) and has a project picker (2026-09-09). A sent to-do stays
write-once by choice: an update path was built and removed on 2026-09-11 as not needed
(see `TODO.md`).

## What to do next

1. **Game Server control panel** — gamelab's 4b is closed, so this is now blocked only on
   gamelab exposing machine-readable status (`--json` or equivalent). Ask gamelab for it;
   don't parse its tables, and don't import it over `sys.path`.
2. **P4** — waits on homelab-monitoring's Block 3.1. An Alertmanager-backed *active
   alerts* panel is buildable today if Chris wants one sooner.
3. **Local model host** — Omega's Ollama is down and the AI sidebar runs on the local
   CPU-only instance as a stopgap. See `TODO.md` "Local model host". Restarting Omega is
   Chris's.

## The one contract to preserve

Every reader in `services/system.py` returns `{'ok': bool, ..., 'error': str | None}`, and the
UI has a third state — "Cannot tell", dashed panel — distinct from healthy and broken. This is
not stylistic. The page it replaced reported the root SSD's free space as the NAS for three days
because an unreadable source rendered as a plausible number. **Any new reader follows this, and
you design the "cannot tell" face before the healthy one.** Same reasoning behind
`plane.issue_status()` being three-valued rather than a bool.

## Who builds here

Decided 2026-09-01: **building work on this repo happens in a session working in this repo.**
Other projects' sessions may add `TODO.md` items — bugs, findings, requests — and nothing else:
no source or test edits, no service restarts. The full reasoning is in `CLAUDE.md`, which every
session working here loads. Three sessions edited this tree in one evening and a routine restart
deployed two of them unreviewed; the code was fine, the coordination was not.

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

## Live lab state worth knowing (2026-09-11)

- **The WoW realm is running** (`gamelab list`: `wotlk` running, playable), so the
  "deliberately stopped" note in `TODO.md`'s game-server item describes 2026-09-01, not now.
  Load averages above 20 are ordinary again when it is up.
- **homelab-monitoring's `GamelabTenantVanished` fired a false critical overnight**
  (from 02:04Z, cleared by about 15:06Z on 2026-09-11). Its collector read the tenant name
  from column 2 of `gamelab list`, which became the new READY column on 2026-09-09, so it
  looked for a tenant called `playable`. They fixed it in `d924686` by importing gamelab's
  Python directly instead. Both halves are what the game-server panel has to avoid: the
  parsing trap, then the coupling. The ask for machine-readable output is gamelab
  `docs/OPEN-WORK.md` item 11.

## Live lab state from 2026-08-30 (Omega still down 2026-09-11)

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
