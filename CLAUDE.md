# Homelab Dashboard — working rules

NiceGUI app on `:8085`, run by `homelab-dashboard.service`. It is the place Chris looks at
the lab and investigates further.

## Who may build here

**Building work on this repo happens in a session working in this repo.** That is the rule,
decided by Chris 2026-09-01 after three Claude sessions edited this working tree in one
evening.

If you are a session whose project is something else — homelab-monitoring, homelab-intake,
media-curator, gamelab, anything — you are welcome here, but your contribution is:

- **Add a `TODO.md` item.** A bug you found, a deviation from your project's architecture, a
  feature the dashboard should have. Say what you observed, with measurements where you have
  them, and what you think it means. That is genuinely valuable and Chris wants it.
- **That is all.** No source edits, no test edits, no doc restructuring, no commits touching
  anything but `TODO.md`, and no `systemctl --user restart homelab-dashboard.service`.

Why the restriction, since the code you would write is often perfectly good: on 2026-09-01
the monitoring session and the intake session both landed real, correct improvements here
while a third session was mid-feature. Nothing was lost, but the dashboard session's test
count moved under it unannounced, a file showed as modified that was only stat-dirty, and a
routine service restart **deployed two other sessions' unreviewed code to the live service**.
The code was fine. The coordination was not, and only luck separates that evening from a
lost afternoon.

This repo already carries the scar of one boundary crossed for convenience: `services/media.py`
imports media-curator's internals over `sys.path` with no package boundary, and that is
precisely what made the `undo()` data-integrity bug reachable. Same lesson, different layer.

## What belongs in this repo at all

The dashboard, not the services it looks at. Configuring the media stack is media-curator's;
Uptime Kuma alert configuration and alert delivery are homelab-monitoring's. *Rendering* links
to those services, and showing their state on Lab Health, is dashboard work and stays here.
`TODO.md` has a "Not this project" section recording what was pruned on 2026-08-29 and where
it went.

## The one contract to preserve

Every reader in `services/system.py` returns `{'ok': bool, ..., 'error': str | None}`, and the
UI has a third state — "Cannot tell", dashed panel — visually distinct from healthy and broken.
This is not stylistic. The page this replaced reported the root SSD's free space as the NAS for
three days because an unreadable source rendered as a plausible number.

**Any new reader follows this, and you design the "cannot tell" face before the healthy one.**
An empty list and "the command did not run" are different answers. Same reasoning behind
`plane.issue_status()` being three-valued rather than a bool, and behind the F11 trend refusing
to report a direction from too few samples.

## Anti-goals — do not relitigate

From `~/HomeLab/MONITORING.md`, which records why two predecessor projects died:

- **No time-series database, no Grafana, no trend charts.** The bounded in-process ring buffer
  in `services/system.py` (60 samples, dropped on restart) is the ceiling.
- **No alerting from the dashboard.** A page you have to be looking at is not a detector.
  Detection is ntfy's and homelab-monitoring's.
- **No log-scraping alerts.** Reading logs on demand is the point.
- **No auto-remediation beyond a container restart.**

## Operating

- Restart: `systemctl --user restart homelab-dashboard.service` — NiceGUI runs `reload=False`,
  so code changes need it, and it drops open browser sessions.
- Watch: `journalctl --user -u homelab-dashboard.service -f`
- Tests: `./venv/bin/python -m pytest -q` (~60 s).
- Pushes to `github.com:Madroth/homelab-dashboard` are **Tier 2** — ADR 7 requires Chris's
  sign-off *each time*. Local commits are fine unattended.
- `docker stats --no-stream` across ~40 containers takes 1–2 s. Never call it synchronously in
  a render; fetch per-container on drill-down.
- Read `docs/STATUS.md` first — it is the resume point. `TODO.md` is the full backlog;
  `docs/LAB_HEALTH_FEATURES.md` is the prioritised monitoring-page plan.
