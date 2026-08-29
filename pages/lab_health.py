"""Lab Health — the dashboard's informational monitoring surface.

Absorbs the old System Status tab (Chris, 2026-08-22) rather than sitting beside it:
that page already rendered containers, disk and a log tail, and two pages showing
container health eventually disagree with each other. The tab key stays 'system' so
existing ?tab=system links and the ai_context registration keep working.

This page informs; it does not detect. Detection belongs to homelab-monitoring and
ends at a phone -- a page you have to be looking at cannot be a detector, which is
why Uptime Kuma ran here for months with a fine UI and zero monitors while seven
failures went unseen. What this page owes you instead is somewhere to look when you
already know something is wrong, and a way to get from "that is red" to the actual
error text and the command that tells you more.
"""
import re

from nicegui import run, ui

from components import ai_context, theme
from components.util import client_alive
from services import system

TOOLS = [
    ('fa-solid fa-heart-pulse', 'Uptime Kuma', 'http://100.87.245.107:3001', theme.GREEN),
    ('fa-solid fa-bars-staggered', 'Dozzle', 'http://100.87.245.107:8888', theme.ACCENT),
    ('fa-solid fa-bell', 'ntfy', 'http://100.87.245.107:5001', theme.PURPLE),
]

SEVERITY_COLORS = {'emergency': theme.RED, 'alert': theme.RED, 'critical': theme.RED,
                   'error': theme.RED, 'warning': theme.AMBER}


def _slug(text: str) -> str:
    """Marker-safe key. NiceGUI markers are matched as whole tokens, and a dot in a
    unit name (livescore.service) makes the element unfindable -- so the row markers
    the tests click are built from a sanitized slug, not the raw name."""
    return re.sub(r'[^a-zA-Z0-9]+', '-', text).strip('-').lower() or 'unknown'


def _container_color(status_text: str) -> str:
    s = status_text.lower()
    if 'exited' in s or 'unhealthy' in s:
        return theme.RED
    if 'health: starting' in s or 'waiting' in s:
        return theme.AMBER
    return theme.GREEN


def _ago(ts: float) -> str:
    import time as _t
    if not ts:
        return 'unknown'
    delta = max(0, _t.time() - ts)
    if delta < 90:
        return f'{int(delta)}s ago'
    if delta < 5400:
        return f'{int(delta // 60)}m ago'
    if delta < 172800:
        return f'{int(delta // 3600)}h ago'
    return f'{int(delta // 86400)}d ago'


def _clock(ts: float) -> str:
    import time as _t
    return _t.strftime('%H:%M:%S', _t.localtime(ts)) if ts else '--:--:--'


def build():
    state = {'status': None, 'logs': [], 'errors': None, 'units': None,
             'status_error': None, 'resources': None, 'query': ''}

    # ---------- shared chrome ----------

    def _section_label(text: str, top: str = '28px', stamp=None):
        label_style = (f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;'
                       f'color:{theme.TEXT_DIM}')
        if stamp is None:
            ui.label(text).style(f'{label_style};margin:{top} 0 12px')
            return
        with ui.row().classes('items-center no-wrap w-full').style(
                f'margin:{top} 0 12px;gap:10px'):
            ui.label(text).style(label_style)
            ui.space()
            stamp()

    # F6. Every panel states when its data was read, because the alternative is the
    # failure this page was built to stop: a plausible-looking number that is actually
    # minutes old. The stamp turns amber on its own once the reading ages past the
    # panel's own poll interval, so a poll that has quietly died shows as stale rather
    # than as calm -- which is why the stamps tick on a timer of their own and do not
    # only repaint when fresh data arrives.
    def _stamp_for(key: str, stale_after: float, partial=None):
        is_partial = partial or (lambda d: not d.get('ok', True))

        @ui.refreshable
        def _stamp():
            import time as _t
            mono = "font-family:'JetBrains Mono',monospace"
            data = state.get(key)
            if not data:
                ui.label('READING…').style(
                    f'font-size:10.5px;letter-spacing:0.06em;color:{theme.TEXT_DIM};{mono}')
                return
            read_at = data.get('read_at') or 0
            stale = not read_at or (_t.time() - read_at) > stale_after
            text = f'AS OF {_clock(read_at)}'
            if not read_at:
                text, tone = 'AS OF UNKNOWN', theme.AMBER
            elif stale:
                text, tone = f'{text} · {_ago(read_at)}', theme.AMBER
            elif is_partial(data):
                text, tone = f'{text} · PARTIAL', theme.AMBER
            else:
                tone = theme.TEXT_MUTED
            ui.label(text).style(
                f'font-size:10.5px;font-weight:600;letter-spacing:0.04em;color:{tone};{mono}')

        return _stamp

    # Stale thresholds are 2x the panel's poll below, so one missed tick is tolerated
    # and two is reported.
    stamp_errors = _stamp_for('errors', 60.0)
    stamp_units = _stamp_for('units', 60.0)
    stamp_containers = _stamp_for(
        'status', 30.0, partial=lambda d: bool(d.get('containers_error')))
    stamp_resources = _stamp_for('resources', 30.0)

    # F7. With 54 containers and 101 units, scrolling is not navigation.
    #
    # The rule this filter obeys: it may hide rows, but it may never make the lab look
    # healthier than it is. So the verdict banner above stays global and unfiltered, every
    # filtered section says how many of how many it is showing, and a section with no
    # matches says "no matches" rather than rendering the same empty calm as "nothing is
    # wrong here". A filter that quietly emptied a panel would be the NAS bug wearing a
    # different hat.
    def _q() -> str:
        return state['query']

    def _hit(query: str, *fields) -> bool:
        return any(query in (f or '').lower() for f in fields)

    def _match_error(entry: dict, query: str) -> bool:
        return _hit(query, entry.get('message'), entry.get('origin'),
                    entry.get('source'), entry.get('severity'))

    def _match_unit(u: dict, query: str) -> bool:
        return _hit(query, u.get('unit'), u.get('description'), u.get('active'), u.get('sub'))

    def _match_container(c: dict, query: str) -> bool:
        return _hit(query, c.get('Names'), c.get('Status'), c.get('Image'), _project_of(c))

    def _filtered_note(shown: int, total: int):
        """Says what the filter is hiding. Without this a narrowed list reads as the
        whole truth."""
        if not _q():
            return
        ui.label(f'showing {shown} of {total} — filtered by "{state["query"]}"').style(
            f'font-size:10.5px;color:{theme.AMBER};margin-top:8px')

    def _no_matches(what: str):
        with ui.row().classes('items-center no-wrap').style(
                f'gap:10px;padding:13px 15px;border-radius:9px;width:100%;'
                f'background:{theme.CARD_BG};border:1px dashed rgba(147,153,178,0.5)'):
            ui.icon('fa-solid fa-magnifying-glass').style(f'color:{theme.TEXT_DIM};font-size:13px')
            ui.label(f'No {what} match "{state["query"]}". This hides rows; '
                     f'it does not mean there are none.').style(
                f'font-size:11.5px;color:{theme.TEXT_MUTED}')

    def _unknown_box(message: str):
        """The load-bearing visual: a dashed, muted panel that can never be mistaken
        for a healthy one. 'Could not determine' is a third outcome, not a quiet
        version of 'fine' -- reporting an unavailable source as an empty list is
        exactly how a downed NAS looked healthy for three days."""
        with ui.row().classes('items-center no-wrap').style(
                f'gap:10px;padding:13px 15px;border-radius:9px;width:100%;'
                f'border:1px dashed rgba(147,153,178,0.5);background:rgba(255,255,255,0.02)'):
            ui.icon('fa-solid fa-circle-question').style(f'color:{theme.TEXT_MUTED};font-size:13px')
            ui.label(message).style(f'font-size:11.5px;color:{theme.TEXT_MUTED};line-height:1.5')

    def _copy(text: str, label: str = 'Copy'):
        def do_copy():
            ui.clipboard.write(text)
            ui.notify('Copied', type='positive')
        with ui.row().classes('items-center no-wrap cursor-pointer').style(
                f'gap:6px;padding:5px 10px;border-radius:6px;background:{theme.ACCENT_TINT};'
                f'color:{theme.ACCENT};font-size:10.5px;font-weight:600').on('click', do_copy):
            ui.icon('fa-solid fa-clone').style('font-size:10px')
            ui.label(label)

    # ---------- verdict ----------

    @ui.refreshable
    def render_verdict():
        errors = state['errors']
        failed = [e for e in (errors or {}).get('entries', []) if e['source'] == 'unit']
        unreadable = errors is not None and not errors['ok']

        if errors is None:
            tone, title, detail = theme.TEXT_MUTED, 'Reading…', 'Collecting errors, units and containers.'
        elif unreadable:
            tone, title = theme.TEXT_MUTED, 'Cannot tell'
            detail = f"A source did not answer — {errors['error']}. What is shown is incomplete."
        elif failed:
            tone, title = theme.RED, 'Something is broken'
            names = ', '.join(u['origin'] for u in failed[:3])
            detail = f"{len(failed)} unit(s) in a failed state: {names}."
        elif errors['entries']:
            tone, title = theme.AMBER, 'Errors logged'
            detail = f"{len(errors['entries'])} distinct error(s) in the last 24h. Nothing is in a failed state."
        else:
            tone, title = theme.GREEN, 'Nothing is broken'
            detail = 'No failed units, and no errors logged in the last 24h.'

        dashed = tone == theme.TEXT_MUTED
        with ui.row().classes('items-center no-wrap').style(
                f'gap:16px;padding:18px 20px;border-radius:12px;width:100%;margin-bottom:4px;'
                + (f'border:1px dashed rgba(147,153,178,0.5);background:rgba(255,255,255,0.02)'
                   if dashed else
                   f'border:1px solid {tone};background:rgba(255,255,255,0.03)')):
            ui.icon('fa-solid fa-circle-question' if dashed else
                    'fa-solid fa-triangle-exclamation' if tone in (theme.RED, theme.AMBER) else
                    'fa-solid fa-circle-check').style(f'color:{tone};font-size:22px')
            with ui.column().style('gap:4px;min-width:0'):
                ui.label(title).style(f'font-size:18px;font-weight:800;color:{tone}')
                ui.label(detail).style(f'font-size:12.5px;color:{theme.TEXT_MUTED};line-height:1.5')
            ui.space()
            if state['errors']:
                with ui.column().style('gap:3px;align-items:flex-end;flex:none'):
                    ui.label('AS OF').style(
                        f'font-size:9.5px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                    ui.label(_clock(state['errors']['read_at'])).style(
                        f"font-size:12.5px;font-weight:600;color:{theme.TEXT};font-family:'JetBrains Mono',monospace")

    # ---------- errors ----------

    def show_error_detail(entry: dict):
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:12px;padding:20px;min-width:660px;max-width:840px'):
            color = SEVERITY_COLORS.get(entry['severity'], theme.TEXT_MUTED)
            with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                ui.icon('fa-solid fa-circle-exclamation').style(f'color:{color};font-size:14px')
                ui.label(entry['origin']).style(
                    f"font-size:14px;font-weight:700;color:{theme.TEXT};font-family:'JetBrains Mono',monospace")
                ui.label(entry['severity'].upper()).style(
                    f'font-size:9.5px;font-weight:700;letter-spacing:0.06em;color:{color};'
                    f'background:rgba(255,255,255,0.05);padding:3px 8px;border-radius:5px')
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')

            with ui.row().classes('items-center no-wrap').style('gap:16px;margin:4px 0 12px'):
                for label, value in [
                        ('SOURCE', entry['source']),
                        ('SEEN', f"{entry['count']}×" if entry['count'] > 1 else 'once'),
                        ('LAST', _ago(entry['at'])),
                        ('FIRST', _ago(entry.get('first_at', entry['at']))),
                ]:
                    with ui.column().style('gap:2px'):
                        ui.label(label).style(
                            f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                        ui.label(value).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')

            # Selectable, not a tooltip: the whole point is being able to read the
            # error and paste it somewhere. (Same complaint as intake's failed-queue
            # entries, 2026-08-04 -- solved once, here.)
            ui.label('MESSAGE').style(
                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
            ui.label(entry['message']).style(
                f"width:100%;background:rgba(0,0,0,0.28);border-radius:8px;padding:12px 14px;"
                f"font-family:'JetBrains Mono',monospace;font-size:11.5px;color:{theme.TEXT};"
                f"line-height:1.6;white-space:pre-wrap;word-break:break-word;user-select:text;"
                f"max-height:240px;overflow:auto")

            detail = entry.get('detail') or {}
            shown = {k: v for k, v in detail.items() if v}
            if shown:
                with ui.row().classes('items-center').style('gap:14px;flex-wrap:wrap;margin-top:4px'):
                    for k, v in shown.items():
                        ui.label(f'{k}: {v}').style(
                            f"font-size:10.5px;color:{theme.TEXT_DIM};font-family:'JetBrains Mono',monospace")

            probe = _investigate_command(entry)
            if probe:
                ui.label('INVESTIGATE').style(
                    f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM};margin-top:6px')
                with ui.row().classes('items-center no-wrap w-full').style(
                        f'gap:10px;background:rgba(0,0,0,0.28);border-radius:8px;padding:10px 12px'):
                    ui.label(probe).style(
                        f"flex:1;min-width:0;font-family:'JetBrains Mono',monospace;font-size:11px;"
                        f"color:{theme.TEXT_MUTED};user-select:text;overflow-x:auto;white-space:nowrap")
                    _copy(probe, 'Copy')

            with ui.row().classes('justify-end w-full').style('gap:10px;margin-top:14px'):
                _copy(entry['message'], 'Copy error')
        dialog.open()

    def _investigate_command(entry: dict) -> str | None:
        detail = entry.get('detail') or {}
        if entry['source'] == 'container' or detail.get('container'):
            name = detail.get('container') or entry['origin']
            return f'docker logs --tail 200 {name}'
        unit = detail.get('unit') or (entry['origin'] if entry['origin'].endswith('.service') else None)
        if unit:
            manager = detail.get('manager', 'user')
            return f'journalctl --{manager} -u {unit} -n 200 --no-pager'
        return None

    @ui.refreshable
    def render_errors():
        errors = state['errors']
        if errors is None:
            with ui.column().style('gap:8px;width:100%'):
                for _ in range(4):
                    ui.element('div').classes('nq-skel').style(
                        'height:44px;border-radius:9px;background:rgba(255,255,255,0.04);width:100%')
            return

        if errors['error']:
            _unknown_box(f"Some sources did not answer — {errors['error']}. "
                         f"The list below is incomplete; treat gaps as unknown, not as quiet.")

        if not errors['entries']:
            if errors['ok']:
                with ui.row().classes('items-center no-wrap').style(
                        f'gap:10px;padding:13px 15px;border-radius:9px;width:100%;'
                        f'background:{theme.CARD_BG};border:1px solid {theme.BORDER}'):
                    ui.icon('fa-solid fa-circle-check').style(f'color:{theme.GREEN};font-size:13px')
                    ui.label('No errors logged in the last 24 hours.').style(
                        f'font-size:11.5px;color:{theme.TEXT_MUTED}')
            return

        query = _q()
        all_entries = errors['entries']
        entries = [e for e in all_entries if _match_error(e, query)] if query else all_entries
        if query and not entries:
            _no_matches('errors')
            return

        with ui.column().style('gap:6px;width:100%'):
            for entry in entries[:40]:
                color = SEVERITY_COLORS.get(entry['severity'], theme.TEXT_MUTED)
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:12px;padding:10px 14px;border-radius:9px;width:100%;'
                        f'background:{theme.CARD_BG};border:1px solid {theme.BORDER}'
                ).on('click', lambda _, e=entry: show_error_detail(e)).mark(
                        f"error-row-{_slug(entry['origin'])}-{int(entry['at'])}"):
                    ui.element('div').style(
                        f'width:7px;height:7px;border-radius:50%;background:{color};flex:none')
                    ui.label(entry['origin']).style(
                        f"font-size:11.5px;font-weight:600;color:{theme.TEXT};flex:none;width:210px;"
                        f"font-family:'JetBrains Mono',monospace;overflow:hidden;text-overflow:ellipsis;"
                        f"white-space:nowrap")
                    ui.label(entry['message']).style(
                        f'flex:1;min-width:0;font-size:11.5px;color:{theme.TEXT_MUTED};'
                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                    if entry['count'] > 1:
                        ui.label(f"×{entry['count']}").style(
                            f'font-size:10px;font-weight:700;color:{theme.AMBER};background:rgba(249,201,124,0.12);'
                            f'padding:2px 7px;border-radius:5px;flex:none')
                    ui.label(_ago(entry['at'])).style(
                        f'font-size:10.5px;color:{theme.TEXT_DIM};flex:none;width:70px;text-align:right')
        _filtered_note(min(len(entries), 40), len(all_entries))

    # ---------- units ----------

    def show_unit_detail(unit: str, manager: str):
        detail = system.get_unit_detail(unit, manager)
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:12px;padding:20px;min-width:680px;max-width:880px'):
            with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                ui.label(unit).style(
                    f"font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace;color:{theme.TEXT}")
                ui.label(manager).style(
                    f'font-size:9.5px;font-weight:700;letter-spacing:0.06em;color:{theme.TEXT_MUTED};'
                    f'background:rgba(255,255,255,0.05);padding:3px 8px;border-radius:5px')
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')

            if not detail['ok']:
                _unknown_box(f'Could not read this unit — {detail["error"]}')
            else:
                props = detail['props']
                active = props.get('ActiveState', '')
                color = theme.RED if active == 'failed' else theme.GREEN if active == 'active' else theme.AMBER
                with ui.row().classes('items-center').style('gap:18px;flex-wrap:wrap;margin:6px 0 12px'):
                    for label, value, tone in [
                            ('STATE', f"{active}/{props.get('SubState', '')}", color),
                            ('RESULT', props.get('Result', '—'), theme.TEXT_MUTED),
                            ('RESTARTS', props.get('NRestarts', '0'), theme.TEXT_MUTED),
                            ('LAST EXIT', props.get('ExecMainStatus', '—'), theme.TEXT_MUTED),
                    ]:
                        with ui.column().style('gap:2px'):
                            ui.label(label).style(
                                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                            ui.label(str(value)).style(f'font-size:12px;font-weight:600;color:{tone}')
                if props.get('Description'):
                    ui.label(props['Description']).style(
                        f'font-size:11.5px;color:{theme.TEXT_MUTED};margin-bottom:6px')

                ui.label('RECENT LOG').style(
                    f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                if detail.get('log_error'):
                    _unknown_box(f'Could not read this unit\'s log — {detail["log_error"]}')
                elif detail['logs']:
                    ui.label('\n'.join(detail['logs'])).style(
                        f"width:100%;background:rgba(0,0,0,0.28);border-radius:8px;padding:12px 14px;"
                        f"font-family:'JetBrains Mono',monospace;font-size:10.5px;color:{theme.TEXT_MUTED};"
                        f"line-height:1.55;white-space:pre-wrap;word-break:break-word;user-select:text;"
                        f"max-height:280px;overflow:auto")
                else:
                    ui.label('No log entries.').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')

                cmd = f'journalctl --{manager} -u {unit} -n 200 --no-pager'
                with ui.row().classes('items-center no-wrap w-full').style(
                        f'gap:10px;background:rgba(0,0,0,0.28);border-radius:8px;padding:10px 12px;margin-top:10px'):
                    ui.label(cmd).style(
                        f"flex:1;min-width:0;font-family:'JetBrains Mono',monospace;font-size:11px;"
                        f"color:{theme.TEXT_MUTED};user-select:text;overflow-x:auto;white-space:nowrap")
                    _copy(cmd, 'Copy')
        dialog.open()

    @ui.refreshable
    def render_units():
        units = state['units']
        if units is None:
            ui.element('div').classes('nq-skel').style(
                'height:120px;border-radius:9px;background:rgba(255,255,255,0.04);width:100%')
            return
        if not units['ok']:
            _unknown_box(f'Could not list units — {units["error"]}')
            if not units['units']:
                return

        query = _q()
        all_units = units['units']
        if query:
            matches = [u for u in all_units if _match_unit(u, query)]
            if not matches:
                _no_matches('units')
                return
            # Searching for a unit means wanting to see it, healthy or not -- so the
            # "failed first, then 14 of the rest" summary gives way to the matches.
            shown = sorted(matches, key=lambda u: (not u['failed'], u['unit']))[:40]
        else:
            failed = [u for u in all_units if u['failed']]
            shown = failed + [u for u in all_units if not u['failed']][:14]
        with ui.column().style('gap:6px;width:100%'):
            for u in shown:
                color = theme.RED if u['failed'] else (
                    theme.GREEN if u['active'] == 'active' else theme.TEXT_DIM)
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:12px;padding:9px 14px;border-radius:9px;width:100%;background:{theme.CARD_BG};'
                        f'border:1px solid ' + (theme.RED if u['failed'] else theme.BORDER)
                ).on('click', lambda _, n=u['unit'], m=u['manager']: show_unit_detail(n, m)).mark(
                        f"unit-row-{_slug(u['unit'])}"):
                    ui.element('div').style(
                        f'width:7px;height:7px;border-radius:50%;background:{color};flex:none')
                    ui.label(u['unit']).style(
                        f"font-size:11.5px;font-weight:600;color:{theme.TEXT};flex:none;width:290px;"
                        f"font-family:'JetBrains Mono',monospace;overflow:hidden;text-overflow:ellipsis;"
                        f"white-space:nowrap")
                    ui.label(u['description']).style(
                        f'flex:1;min-width:0;font-size:11px;color:{theme.TEXT_MUTED};'
                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                    ui.label(f"{u['active']}/{u['sub']}").style(
                        f'font-size:10.5px;color:{color};flex:none;width:120px;text-align:right')
        if query:
            _filtered_note(len(shown), len(all_units))
        elif len(all_units) > len(shown):
            ui.label(f'{len(all_units) - len(shown)} more units not shown').style(
                f'font-size:10.5px;color:{theme.TEXT_DIM};margin-top:8px')

    # ---------- containers, metrics, logs (carried over from System Status) ----------

    def _project_of(container: dict) -> str:
        for pair in (container.get('Labels') or '').split(','):
            if pair.startswith('com.docker.compose.project='):
                return pair.split('=', 1)[1] or 'ungrouped'
        return 'ungrouped'

    def show_container_detail(name: str):
        detail = system.get_container_detail(name)
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:12px;padding:20px;min-width:700px;max-width:900px'):
            with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                ui.label(name).style(
                    f"font-size:14px;font-weight:700;font-family:'JetBrains Mono',monospace;color:{theme.TEXT}")
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')

            if not detail['ok']:
                _unknown_box(f"Could not inspect this container — {detail['error']}")
                dialog.open()
                return

            running = detail['state'] == 'running'
            state_color = theme.GREEN if running else theme.RED
            # A declared healthcheck disagreeing with 'running' is the interesting case;
            # no healthcheck at all is not the same as healthy, so it says so.
            health = detail['health']
            health_text = health or 'no healthcheck declared'
            health_color = (theme.GREEN if health == 'healthy' else
                            theme.RED if health == 'unhealthy' else
                            theme.AMBER if health else theme.TEXT_DIM)
            with ui.row().classes('items-center').style('gap:20px;flex-wrap:wrap;margin:6px 0 12px'):
                for label, value, tone in [
                        ('STATE', detail['state'], state_color),
                        ('HEALTH', health_text, health_color),
                        ('RESTARTS', str(detail['restarts']),
                         theme.AMBER if detail['restarts'] > 3 else theme.TEXT_MUTED),
                        ('EXIT', str(detail['exit_code']), theme.TEXT_MUTED),
                        ('OOM KILLED', 'yes' if detail['oom_killed'] else 'no',
                         theme.RED if detail['oom_killed'] else theme.TEXT_MUTED),
                ]:
                    with ui.column().style('gap:2px'):
                        ui.label(label).style(
                            f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                        ui.label(value).style(f'font-size:12px;font-weight:600;color:{tone}')

            if detail['stats']:
                s = detail['stats']
                ui.label('USING NOW').style(
                    f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                with ui.row().classes('items-center').style('gap:20px;flex-wrap:wrap;margin-bottom:10px'):
                    for label, value in [('CPU', s['cpu']), ('MEMORY', f"{s['mem']} ({s['mem_pct']})"),
                                          ('NET I/O', s['net']), ('BLOCK I/O', s['block']),
                                          ('PIDS', s['pids'])]:
                        with ui.column().style('gap:2px'):
                            ui.label(label).style(
                                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                            ui.label(str(value)).style(f'font-size:12px;color:{theme.TEXT}')
            elif detail['stats_error']:
                _unknown_box(f"Could not read live stats — {detail['stats_error']}")

            with ui.row().classes('items-center').style('gap:18px;flex-wrap:wrap;margin-bottom:8px'):
                for label, value in [('IMAGE', detail['image']),
                                      ('PROJECT', detail['project'] or '—'),
                                      ('SERVICE', detail['service'] or '—')]:
                    ui.label(f'{label}: {value}').style(
                        f"font-size:10.5px;color:{theme.TEXT_DIM};font-family:'JetBrains Mono',monospace")
            if detail['ports']:
                ui.label('PORTS: ' + ', '.join(detail['ports'])).style(
                    f"font-size:10.5px;color:{theme.TEXT_DIM};font-family:'JetBrains Mono',monospace")
            if detail['mounts']:
                ui.label(f"MOUNTS: {len(detail['mounts'])} — " + '; '.join(detail['mounts'][:2])).style(
                    f"font-size:10.5px;color:{theme.TEXT_DIM};font-family:'JetBrains Mono',monospace;"
                    f"overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:100%")

            ui.label('RECENT OUTPUT').style(
                f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM};margin-top:8px')
            if detail['log_error']:
                _unknown_box(f"Could not read logs — {detail['log_error']}")
            elif detail['logs']:
                ui.label('\n'.join(detail['logs'])).style(
                    f"width:100%;background:rgba(0,0,0,0.28);border-radius:8px;padding:12px 14px;"
                    f"font-family:'JetBrains Mono',monospace;font-size:10.5px;color:{theme.TEXT_MUTED};"
                    f"line-height:1.55;white-space:pre-wrap;word-break:break-word;user-select:text;"
                    f"max-height:260px;overflow:auto")
            else:
                ui.label('No output.').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')

            cmd = f'docker logs --tail 200 {name}'
            with ui.row().classes('items-center no-wrap w-full').style(
                    f'gap:10px;background:rgba(0,0,0,0.28);border-radius:8px;padding:10px 12px;margin-top:10px'):
                ui.label(cmd).style(
                    f"flex:1;min-width:0;font-family:'JetBrains Mono',monospace;font-size:11px;"
                    f"color:{theme.TEXT_MUTED};user-select:text")
                _copy(cmd, 'Copy')
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:6px;padding:5px 10px;border-radius:6px;border:1px solid rgba(255,255,255,0.08);'
                        f'color:{theme.TEXT_MUTED};font-size:10.5px'
                ).on('click', lambda: ui.navigate.to(
                        f'http://100.87.245.107:8888/container/{name}', new_tab=True)):
                    ui.label('Open in Dozzle')
        dialog.open()

    @ui.refreshable
    def render_containers():
        status = state['status']
        if status is None:
            ui.element('div').classes('nq-skel').style(
                'height:90px;border-radius:9px;background:rgba(255,255,255,0.04);width:100%')
            return
        containers = status.get('containers') or []
        if status.get('containers_error'):
            _unknown_box(f"Could not read container state — {status['containers_error']}")
            return
        if not containers:
            with ui.row().classes('items-center no-wrap').style(
                    f'gap:10px;padding:13px 15px;border-radius:9px;width:100%;'
                    f'background:{theme.CARD_BG};border:1px solid {theme.BORDER}'):
                ui.icon('fa-solid fa-circle-check').style(f'color:{theme.GREEN};font-size:13px')
                ui.label('Docker is reachable and reports no containers.').style(
                    f'font-size:11.5px;color:{theme.TEXT_MUTED}')
            return
        query = _q()
        all_containers = containers
        if query:
            containers = [c for c in containers if _match_container(c, query)]
            if not containers:
                _no_matches('containers')
                return

        # Grouped by compose project: the media stack is 11 of 54 containers across 13
        # projects, so one flat grid buries everything else under it. A group whose
        # members all filtered out drops away rather than rendering as an empty stack.
        groups: dict[str, list] = {}
        for c in containers:
            groups.setdefault(_project_of(c), []).append(c)

        def _group_rank(item):
            name, members = item
            unhealthy = sum(1 for m in members
                            if _container_color(m.get('Status', '')) != theme.GREEN)
            return (-unhealthy, name)

        with ui.column().style('gap:14px;width:100%'):
            for project, members in sorted(groups.items(), key=_group_rank):
                down = [m for m in members if _container_color(m.get('Status', '')) != theme.GREEN]
                with ui.column().style('gap:7px;width:100%'):
                    with ui.row().classes('items-center no-wrap').style('gap:9px'):
                        ui.label(project).style(
                            f"font-size:11.5px;font-weight:700;color:{theme.TEXT};"
                            f"font-family:'JetBrains Mono',monospace")
                        ui.label(f'{len(members) - len(down)}/{len(members)} up').style(
                            f'font-size:10.5px;color:{theme.RED if down else theme.TEXT_DIM}')
                    with ui.grid(columns='repeat(auto-fill, minmax(210px, 1fr))').style(
                            'gap:10px;width:100%'):
                        for c in members:
                            color = _container_color(c.get('Status', ''))
                            name = c.get('Names', '')
                            with ui.column().classes('cursor-pointer').style(
                                    f'background:{theme.CARD_BG};border:1px solid {theme.BORDER};'
                                    f'border-radius:9px;padding:11px;gap:5px'
                            ).on('click', lambda _, n=name: show_container_detail(n)).mark(
                                    f'container-{_slug(name)}'):
                                with ui.row().classes('items-center no-wrap').style('gap:8px'):
                                    ui.icon('fa-solid fa-box').style(f'color:{color};font-size:11px')
                                    ui.label(name).style(
                                        f'font-weight:600;font-size:12px;color:{theme.TEXT};'
                                        f'overflow:hidden;text-overflow:ellipsis;white-space:nowrap')
                                ui.label(c.get('Status', '')).style(
                                    f'font-size:10.5px;color:{theme.TEXT_MUTED};overflow:hidden;'
                                    f'text-overflow:ellipsis;white-space:nowrap;max-width:100%')
        _filtered_note(len(containers), len(all_containers))

    def _human(n):
        if n is None:
            return '—'
        for unit in ('B', 'KB', 'MB', 'GB', 'TB'):
            if abs(n) < 1024 or unit == 'TB':
                return f'{n:.1f} {unit}' if unit != 'B' else f'{int(n)} B'
            n /= 1024
        return f'{n:.1f} TB'

    def show_resource_detail(kind: str):
        res = state['resources'] or {}
        with ui.dialog() as dialog, ui.card().style(
                f'background:{theme.CARD_BG};border:1px solid rgba(255,255,255,0.08);'
                f'border-radius:12px;padding:20px;min-width:640px;max-width:820px'):
            titles = {'cpu': 'CPU', 'memory': 'Memory', 'disks': 'Disks', 'temps': 'Temperature'}
            with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                ui.label(titles.get(kind, kind)).style(
                    f'font-size:14px;font-weight:700;color:{theme.TEXT}')
                ui.space()
                ui.button(icon='close', on_click=dialog.close).props('flat dense round').style(
                    f'color:{theme.TEXT_MUTED}')

            if kind in ('cpu', 'memory'):
                block = res.get(kind) or {}
                if not block.get('ok'):
                    _unknown_box(f"Could not read {kind} — {block.get('error')}")
                else:
                    psi = block.get('psi') or {}
                    if psi.get('ok'):
                        # Pressure is the honest "is this actually hurting" number, and
                        # the kernel keeps the averages so nothing has to be stored.
                        ui.label('PRESSURE — share of time work stalled waiting for this').style(
                            f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                        with ui.row().classes('items-center').style('gap:22px;margin-bottom:10px'):
                            for window in ('avg10', 'avg60', 'avg300'):
                                value = psi.get(f'some_{window}')
                                with ui.column().style('gap:2px'):
                                    ui.label(window).style(f'font-size:10px;color:{theme.TEXT_DIM}')
                                    ui.label('—' if value is None else f'{value:.2f}%').style(
                                        f'font-size:13px;font-weight:700;color:'
                                        + (theme.RED if (value or 0) > 20 else
                                           theme.AMBER if (value or 0) > 5 else theme.TEXT))
                    else:
                        _unknown_box(f"Pressure unavailable — {psi.get('error')}")

                    if kind == 'memory':
                        with ui.row().classes('items-center').style('gap:22px;margin-bottom:10px'):
                            for label, value in [
                                    ('TOTAL', _human(block.get('total'))),
                                    ('AVAILABLE', _human(block.get('available'))),
                                    ('SWAP USED', f"{block.get('swap_used_pct')}%"
                                     if block.get('swap_used_pct') is not None else '—'),
                                    ('SWAP FREE', _human(block.get('swap_free')))]:
                                with ui.column().style('gap:2px'):
                                    ui.label(label).style(
                                        f'font-size:9px;font-weight:700;letter-spacing:0.08em;'
                                        f'color:{theme.TEXT_DIM}')
                                    ui.label(value).style(f'font-size:12px;color:{theme.TEXT}')

                top = system.get_top_processes()
                ui.label('TOP PROCESSES BY CPU').style(
                    f'font-size:9px;font-weight:700;letter-spacing:0.08em;color:{theme.TEXT_DIM}')
                if not top['ok']:
                    _unknown_box(f"Could not list processes — {top['error']}")
                else:
                    for proc in top['processes']:
                        with ui.row().classes('items-center no-wrap w-full').style(
                                f'gap:14px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.04)'):
                            ui.label(proc['command']).style(
                                f"flex:1;min-width:0;font-size:11.5px;color:{theme.TEXT};"
                                f"font-family:'JetBrains Mono',monospace;overflow:hidden;"
                                f"text-overflow:ellipsis;white-space:nowrap")
                            ui.label(f"pid {proc['pid']}").style(
                                f'font-size:10.5px;color:{theme.TEXT_DIM};width:78px')
                            ui.label(f"{proc['cpu']:.0f}% cpu").style(
                                f'font-size:10.5px;color:{theme.TEXT_MUTED};width:70px;text-align:right')
                            ui.label(_human(proc['rss'])).style(
                                f'font-size:10.5px;color:{theme.TEXT_MUTED};width:78px;text-align:right')

            elif kind == 'disks':
                for d in res.get('disks') or []:
                    if not d['ok']:
                        _unknown_box(f"{d['label']} ({d['path']}) — {d['error']}")
                        continue
                    with ui.column().style('gap:5px;width:100%;margin-bottom:12px'):
                        with ui.row().classes('items-center no-wrap w-full').style('gap:10px'):
                            ui.label(f"{d['label']} · {d['path']}").style(
                                f"font-size:12px;font-weight:600;color:{theme.TEXT};"
                                f"font-family:'JetBrains Mono',monospace")
                            ui.space()
                            ui.label(f"{_human(d['free'])} free of {_human(d['total'])}").style(
                                f'font-size:11px;color:{theme.TEXT_MUTED}')
                        pct = d['used_pct'] or 0
                        with ui.element('div').style(
                                'height:6px;border-radius:3px;width:100%;background:rgba(255,255,255,0.07)'):
                            ui.element('div').style(
                                f'height:100%;border-radius:3px;width:{min(pct, 100)}%;background:'
                                + (theme.RED if pct > 90 else theme.AMBER if pct > 80 else theme.GREEN))

            elif kind == 'temps':
                temps = res.get('temps') or {}
                if not temps.get('ok'):
                    _unknown_box(f"Could not read temperatures — {temps.get('error')}")
                elif not temps.get('zones'):
                    _unknown_box('No thermal zones exposed by this kernel.')
                else:
                    for zone in temps['zones']:
                        with ui.row().classes('items-center no-wrap w-full').style(
                                'gap:14px;padding:7px 0;border-bottom:1px solid rgba(255,255,255,0.04)'):
                            ui.label(zone['name']).style(
                                f"flex:1;font-size:11.5px;color:{theme.TEXT};"
                                f"font-family:'JetBrains Mono',monospace")
                            ui.label(f"{zone['celsius']:.1f} °C").style(
                                f'font-size:12px;font-weight:600;color:'
                                + (theme.RED if zone['celsius'] >= 85 else
                                   theme.AMBER if zone['celsius'] >= 75 else theme.TEXT))
        dialog.open()

    def _resource_card(kind, icon, label, value, sub, tone, ok=True, error=None):
        border = (f'1px dashed rgba(147,153,178,0.5)' if not ok
                  else f'1px solid {theme.BORDER}')
        with ui.column().classes('cursor-pointer' if ok else '').style(
                f'background:{theme.CARD_BG if ok else "rgba(255,255,255,0.02)"};border:{border};'
                f'border-radius:11px;padding:15px 16px;gap:7px'
        ).on('click', lambda _, k=kind: show_resource_detail(k) if ok else None).mark(f'resource-{kind}'):
            with ui.row().classes('items-center no-wrap').style(
                    f'color:{tone};font-size:10.5px;font-weight:700;gap:8px;letter-spacing:0.06em'):
                ui.icon(icon).style('font-size:12px')
                ui.label(label)
            if not ok:
                ui.label('Cannot tell').style(
                    f'font-size:17px;font-weight:800;color:{theme.TEXT_MUTED}')
                ui.label(str(error)[:70]).style(f'font-size:10.5px;color:{theme.TEXT_MUTED}')
                return
            ui.label(value).style(f'font-size:22px;font-weight:800;color:{tone};line-height:1')
            ui.label(sub).style(f'font-size:10.5px;color:{theme.TEXT_MUTED}')

    @ui.refreshable
    def render_resources():
        res = state['resources']
        if res is None:
            ui.element('div').classes('nq-skel').style(
                'height:96px;border-radius:11px;background:rgba(255,255,255,0.04);width:100%')
            return

        with ui.grid(columns=4).style('gap:14px;width:100%'):
            cpu = res.get('cpu') or {}
            if cpu.get('ok'):
                load1 = cpu['load'][0]
                per_core = load1 / max(cpu['cores'], 1)
                tone = theme.RED if per_core > 1.5 else theme.AMBER if per_core > 0.9 else theme.GREEN
                _resource_card('cpu', 'fa-solid fa-microchip', 'CPU LOAD', f'{load1:.2f}',
                               f"{cpu['cores']} cores · {per_core * 100:.0f}% per core", tone)
            else:
                _resource_card('cpu', 'fa-solid fa-microchip', 'CPU LOAD', '', '',
                               theme.TEXT_MUTED, ok=False, error=cpu.get('error'))

            mem = res.get('memory') or {}
            if mem.get('ok'):
                pct = mem['used_pct'] or 0
                swap_pct = mem.get('swap_used_pct')
                # Swap exhaustion is the interesting signal, not RAM percentage: a full
                # swap with RAM this tight is the machine with nowhere left to go.
                tone = (theme.RED if pct > 92 or (swap_pct or 0) > 95 else
                        theme.AMBER if pct > 80 else theme.GREEN)
                _resource_card('memory', 'fa-solid fa-memory', 'MEMORY', f'{pct:.0f}%',
                               f"{_human(mem['available'])} available · swap "
                               + (f'{swap_pct:.0f}% used' if swap_pct is not None else 'n/a'), tone)
            else:
                _resource_card('memory', 'fa-solid fa-memory', 'MEMORY', '', '',
                               theme.TEXT_MUTED, ok=False, error=mem.get('error'))

            disks = res.get('disks') or []
            broken = [d for d in disks if not d['ok']]
            if broken:
                _resource_card('disks', 'fa-solid fa-hard-drive', 'DISKS', '', '',
                               theme.TEXT_MUTED, ok=False,
                               error=f"{broken[0]['label']}: {broken[0]['error']}")
            elif disks:
                worst = max(disks, key=lambda d: d['used_pct'] or 0)
                tone = (theme.RED if (worst['used_pct'] or 0) > 90 else
                        theme.AMBER if (worst['used_pct'] or 0) > 80 else theme.GREEN)
                _resource_card('disks', 'fa-solid fa-hard-drive', 'DISKS',
                               f"{worst['used_pct']:.0f}%",
                               f"{worst['label']} fullest · {_human(worst['free'])} free", tone)

            temps = res.get('temps') or {}
            zones = temps.get('zones') or []
            if temps.get('ok') and zones:
                hottest = max(zones, key=lambda z: z['celsius'])
                tone = (theme.RED if hottest['celsius'] >= 85 else
                        theme.AMBER if hottest['celsius'] >= 75 else theme.GREEN)
                _resource_card('temps', 'fa-solid fa-temperature-half', 'TEMPERATURE',
                               f"{hottest['celsius']:.0f} °C",
                               f"{hottest['name']} · {len(zones)} zones", tone)
            else:
                _resource_card('temps', 'fa-solid fa-temperature-half', 'TEMPERATURE', '', '',
                               theme.TEXT_MUTED, ok=False,
                               error=temps.get('error') or 'no thermal zones')

    @ui.refreshable
    def render_logs():
        logs = state['logs']
        if not logs:
            ui.label('No log entries.').style(f'font-size:11.5px;color:{theme.TEXT_DIM}')
            return
        ui.markdown('```\n' + ''.join(logs) + '\n```').classes('nq-markdown').style(
            'max-height:280px;overflow:auto;width:100%')

    # A filter narrows three panels at once, and the verdict above them stays global.
    # Saying so out loud is the difference between "the lab is quiet" and "you are
    # looking at a slice of it".
    @ui.refreshable
    def render_filter_banner():
        if not _q():
            return
        with ui.row().classes('items-center no-wrap w-full').style(
                f'gap:10px;padding:10px 14px;border-radius:9px;margin-bottom:12px;'
                f'background:rgba(249,201,124,0.10);border:1px solid {theme.AMBER}'):
            ui.icon('fa-solid fa-filter').style(f'color:{theme.AMBER};font-size:12px')
            ui.label(f'Filtered by "{state["query"]}" — errors, units and containers below '
                     f'show only what matches. The verdict above is for the whole lab.').style(
                f'font-size:11.5px;color:{theme.TEXT_MUTED}')

    def apply_query(value):
        state['query'] = (value or '').strip().lower()
        render_filter_banner.refresh()
        render_errors.refresh()
        render_units.refresh()
        render_containers.refresh()

    # ---------- refreshers ----------

    async def refresh_status():
        status = await run.io_bound(system.get_status)
        if status is None:
            return
        if client_alive():
            state['status'] = status
            render_containers.refresh()
            stamp_containers.refresh()

    async def refresh_logs():
        logs = await run.io_bound(system.get_logs)
        if logs is None:
            return
        if client_alive():
            state['logs'] = logs
            render_logs.refresh()

    async def refresh_resources():
        res = await run.io_bound(system.get_host_resources)
        if res is None:
            return
        if client_alive():
            state['resources'] = res
            render_resources.refresh()
            stamp_resources.refresh()

    async def refresh_errors():
        errors = await run.io_bound(system.get_errors)
        units = await run.io_bound(system.get_units, 'user')
        if errors is None or units is None:
            return
        if client_alive():
            state['errors'] = errors
            state['units'] = units
            render_errors.refresh()
            render_units.refresh()
            render_verdict.refresh()
            stamp_errors.refresh()
            stamp_units.refresh()

    async def refresh_all():
        await refresh_errors()
        await refresh_resources()
        await refresh_status()

    # ---------- AI context ----------

    def get_context_summary():
        status = state['status'] or {}
        containers = status.get('containers') or []
        unhealthy = [c for c in containers if _container_color(c.get('Status', '')) != theme.GREEN]
        errors = state['errors'] or {}
        failed = [e for e in errors.get('entries', []) if e['source'] == 'unit']
        lines = [f"Viewing Lab Health. {len(containers)} container(s), {len(unhealthy)} unhealthy/starting. "
                 f"{len(failed)} failed unit(s), {len(errors.get('entries', []))} distinct error(s) in 24h."]
        lines += [f"- FAILED {e['origin']}" for e in failed]
        lines += [f"- {e['origin']}: {e['message'][:160]}" for e in errors.get('entries', [])[:10]
                  if e['source'] != 'unit']
        if errors.get('error'):
            lines.append(f"Some sources unreadable: {errors['error']}")
        return '\n'.join(lines)

    def get_context_card():
        status = state['status'] or {}
        containers = status.get('containers') or []
        unhealthy = [c for c in containers if _container_color(c.get('Status', '')) != theme.GREEN]
        errors = state['errors'] or {}
        failed = [e for e in errors.get('entries', []) if e['source'] == 'unit']
        pills = [f'{len(containers)} containers', f'{len(unhealthy)} unhealthy',
                 f'{len(failed)} failed units']
        if failed:
            focus = 'Failed: ' + ', '.join(e['origin'] for e in failed)
        elif errors.get('entries'):
            focus = f"{len(errors['entries'])} distinct error(s) in the last 24h."
        else:
            focus = 'No failed units and no errors logged.'
        return {'icon': 'fa-solid fa-heart-pulse', 'tab': 'Lab Health', 'pills': pills, 'focus': focus}

    ai_context.register('system', get_context_summary)
    ai_context.register_card('system', get_context_card)

    # ---------- layout ----------

    with ui.column().style('flex:1;height:100%;overflow:auto;padding:24px 28px;gap:0'):
        with ui.row().classes('items-center no-wrap w-full').style('gap:12px;margin-bottom:16px'):
            with ui.column().style('gap:2px'):
                ui.label('Lab Health').style(
                    f'font-size:19px;font-weight:800;letter-spacing:-0.02em;color:{theme.TEXT}')
                ui.label('Errors, units and containers — read live from this machine').style(
                    f'font-size:11.5px;color:{theme.TEXT_DIM}')
            ui.space()
            for icon, label, url, color in TOOLS:
                with ui.row().classes('items-center no-wrap cursor-pointer').style(
                        f'gap:7px;padding:7px 12px;border-radius:7px;background:{theme.CARD_BG};'
                        f'border:1px solid {theme.BORDER};flex:none'
                ).on('click', lambda _, u=url: ui.navigate.to(u, new_tab=True)).mark(f'tool-{_slug(label)}'):
                    ui.icon(icon).style(f'color:{color};font-size:11.5px')
                    ui.label(label).style(f'font-size:11.5px;color:{theme.TEXT_MUTED}')
            ui.button(icon='refresh', on_click=refresh_all).props('flat dense').style(
                f'color:{theme.TEXT_MUTED}').mark('lab-health-refresh')

        with ui.row().classes('items-center no-wrap w-full').style('gap:10px;margin-bottom:14px'):
            ui.input(placeholder='Filter containers, units and errors — name, image, port, '
                                 'error text…',
                     on_change=lambda e: apply_query(e.value)) \
                .props('dense outlined clearable') \
                .style(f'flex:1;min-width:0;font-size:12px') \
                .mark('lab-health-search')

        render_filter_banner()
        render_verdict()

        _section_label('ERRORS — LAST 24 HOURS', top='24px', stamp=stamp_errors)
        render_errors()

        _section_label('UNITS', stamp=stamp_units)
        render_units()

        _section_label('STACK HEALTH', stamp=stamp_containers)
        render_containers()

        _section_label('RESOURCES', stamp=stamp_resources)
        render_resources()

        with ui.row().classes('items-center no-wrap').style('margin:28px 0 12px;gap:10px'):
            ui.label('DAEMON LOG (LAST 100 LINES)').style(
                f'font-size:11.5px;font-weight:700;letter-spacing:0.5px;color:{theme.TEXT_DIM}')
            ui.button(icon='refresh', on_click=refresh_logs).props('flat dense').style(
                f'color:{theme.TEXT_MUTED}')
        render_logs()

    ui.timer(0.05, refresh_errors, once=True)
    ui.timer(0.05, refresh_resources, once=True)
    ui.timer(0.05, refresh_status, once=True)
    ui.timer(0.05, refresh_logs, once=True)
    ui.timer(15.0, refresh_status)
    ui.timer(15.0, refresh_resources)
    ui.timer(30.0, refresh_errors)

    def tick_stamps():
        if not client_alive():
            return
        for stamp in (stamp_errors, stamp_units, stamp_containers, stamp_resources):
            stamp.refresh()

    ui.timer(5.0, tick_stamps)
