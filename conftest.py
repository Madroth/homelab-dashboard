"""Shared pytest setup.

The retry patch below is the second time this suite has been bitten by a wall-clock
budget, so it is fixed once at the harness rather than a third time per test.

The failure recorder at the bottom exists because the media UI flake was chased for two
sessions without a single failing run ever having its output saved.
"""
import datetime
import os
import re
from pathlib import Path

import pytest
from nicegui.testing import User

pytest_plugins = ['nicegui.testing.user_plugin']


# NiceGUI's User.should_see makes 3 attempts with a 0.1s sleep between them: a 0.3s budget
# for an asynchronous render to finish. That is a wall-clock assertion wearing a different
# hat, and this host is the wrong place for one -- it runs a WoW realm and a Minecraft
# server that each hold a core, so load averages above 20 are ordinary rather than
# exceptional. Under that contention four media UI tests fail together and then pass on a
# rerun (found by the homelab-intake session 2026-09-01, confirmed over repeated runs
# against unmodified code: 12 passed, 12 passed, 3 failed).
#
# This is the same disease as test_toggle_select_timing_with_large_queue, fixed in a329de8
# on 2026-08-22 by asserting work done rather than seconds elapsed. That one was a single
# test with a threshold of its own. This one is the harness's own default, reached by every
# `should_see` in the suite, so raising it per test would be ~100 edits and every new test
# would start out fragile again.
#
# Raising the retry count is close to free. Both helpers return the moment the assertion is
# satisfied -- should_see as soon as the element appears, should_not_see as soon as it is
# absent -- so a passing test costs exactly what it did before. The extra budget is spent
# only by a test that is failing or still racing, which is precisely when waiting is the
# right thing to do. A genuinely broken assertion now takes ~3s to report instead of 0.3s;
# that is a fair price for never again rerunning a suite to find out whether it meant it.
#
# Override with NICEGUI_TEST_RETRIES for a run on a quiet machine or a deliberately
# impatient one.
DEFAULT_RETRIES = int(os.environ.get('NICEGUI_TEST_RETRIES', '30'))

_original_should_see = User.should_see
_original_should_not_see = User.should_not_see


async def _patient_should_see(self, target=None, *, kind=None, marker=None, content=None,
                              retries=None):
    return await _original_should_see(
        self, target, kind=kind, marker=marker, content=content,
        retries=DEFAULT_RETRIES if retries is None else retries)


async def _patient_should_not_see(self, target=None, *, kind=None, marker=None, content=None,
                                  retries=None):
    return await _original_should_not_see(
        self, target, kind=kind, marker=marker, content=content,
        retries=DEFAULT_RETRIES if retries is None else retries)


# An explicit retries= at a call site still wins: a test that deliberately wants to be
# impatient keeps that power.
User.should_see = _patient_should_see
User.should_not_see = _patient_should_not_see


# ---------- a failing run records what it saw ----------
#
# test_media_fixes.py fails intermittently and the mechanism is still unknown, because no
# failing run was ever kept: the batches that failed were read off a terminal and gone.
# Every failure now leaves a file behind with the traceback, the captured logs, what the
# simulated user was looking at, and how loaded the host was at that moment -- the one
# thing a rerun on a quieter box can never tell you afterwards.
#
# Written for every phase, not just the call: NiceGUI's `user` fixture fails in TEARDOWN
# when anything logged at ERROR during the test, so a failure that lives in a background
# task shows up there and nowhere else.

FAILURE_DIR = Path(os.environ.get('TEST_FAILURE_DIR', Path(__file__).parent / '.test-failures'))
FAILURE_KEEP = 200   # newest files kept; a flake hunt of a few hundred runs fits


def _read(path):
    try:
        return Path(path).read_text().strip()
    except OSError as e:
        return f'(unreadable: {e})'


def _what_the_user_saw(item):
    user = getattr(item, 'funcargs', {}).get('user')
    if user is None:
        return None
    try:
        notes = '\n'.join(f'  {m}' for m in user.notify.messages) or '  (none)'
        return f'notifications:\n{notes}\n\nlayout:\n{user.current_layout}'
    except Exception as e:  # noqa: BLE001 -- the client may already be torn down
        return f'(could not read the page: {type(e).__name__}: {e})'


def _record_failure(item, report):
    stamp = datetime.datetime.now().strftime('%Y%m%dT%H%M%S.%f')
    name = re.sub(r'[^\w.-]+', '_', item.nodeid)[-120:]
    parts = [
        f'test:     {item.nodeid}',
        f'phase:    {report.when}',
        f'at:       {datetime.datetime.now().isoformat(timespec="milliseconds")}',
        f'duration: {report.duration:.3f}s',
        f'retries:  {DEFAULT_RETRIES} (NICEGUI_TEST_RETRIES)',
        f'nice:     {os.nice(0)}',
        f'loadavg:  {_read("/proc/loadavg")}',
        f'cpu psi:\n{_read("/proc/pressure/cpu")}',
        f'io psi:\n{_read("/proc/pressure/io")}',
    ]
    saw = _what_the_user_saw(item)
    if saw:
        parts.append(f'\n===== what the user saw =====\n{saw}')
    parts.append(f'\n===== failure =====\n{report.longreprtext}')
    for title, content in report.sections:
        parts.append(f'\n===== {title} =====\n{content}')

    FAILURE_DIR.mkdir(exist_ok=True)
    (FAILURE_DIR / f'{stamp}--{name}--{report.when}.txt').write_text('\n'.join(parts) + '\n')
    for old in sorted(FAILURE_DIR.glob('*.txt'))[:-FAILURE_KEEP]:
        old.unlink(missing_ok=True)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item, call):
    report = yield
    if report.failed:
        try:
            _record_failure(item, report)
        except Exception as e:  # noqa: BLE001 -- recording must never change the verdict
            print(f'conftest: could not record failure of {item.nodeid}: {e}')
    return report
