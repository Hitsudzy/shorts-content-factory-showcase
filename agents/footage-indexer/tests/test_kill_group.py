#!/usr/bin/env python3
"""CF-0655: `sieve_answer_claude.kill_group` takes the whole process group
down, not just the direct child.

The bug: after SIGTERM the old code waited only for the direct child. A child
that died on SIGTERM ended the wait, SIGKILL was never sent, and a grandchild
that ignores SIGTERM outlived the ceiling. test_sieve_answer_claude.py's
`test_the_ceiling_kills_the_whole_process_group` did not see it - its
grandchild dies on SIGTERM.

Pinned here, on real processes (no network, no live data):
- a grandchild that ignores SIGTERM is SIGKILLed once the grace is out;
- a group that dies on SIGTERM is left at once - the empty group is seen
  through the reaped leader and the grandchild that launchd/init reaps, the
  wait does not run to the grace on a zombie;
- a leader already gone (group empty before the call) is not an error.

Every grandchild a test starts is killed in `finally` by the PID the test
recorded itself - never by name. Temp files live under `_tmproot.tmp_root`
(CF-0489).

No pytest dependency - plain asserts, run directly.
"""
import os
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import sieve_answer_claude as sac  # noqa: E402
from _tmproot import tmp_root      # noqa: E402

_TMP = tmp_root("cf0655-")

GRACE = 1.0                 # the test's grace instead of KILL_GRACE_SECONDS
READY_WAIT_SECONDS = 20     # starting two Pythons under load costs seconds
GONE_WAIT_SECONDS = 10      # a SIGKILLed grandchild may take a moment to exit

# The child: starts a grandchild in its own process group (inherited - the
# child leads the session), waits for its pid file, then sleeps. It dies on
# SIGTERM (default disposition). The grandchild ignores SIGTERM or not, per
# argv[2], writes its pid only after the disposition is set, and sleeps.
CHILD = r'''
import os, subprocess, sys, time
pid_file, ignore = sys.argv[1], sys.argv[2]
grand = (
    "import os, signal, sys, time\n"
    "if sys.argv[2] == '1':\n"
    "    signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "tmp = sys.argv[1] + '.part'\n"
    "open(tmp, 'w').write(str(os.getpid()))\n"
    "os.replace(tmp, sys.argv[1])\n"
    "time.sleep(120)\n")
subprocess.Popen([sys.executable, "-c", grand, pid_file, ignore])
while not os.path.exists(pid_file):
    time.sleep(0.05)
time.sleep(120)
'''


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return False   # the pid is someone else's now - ours is gone
    # a zombie reparented to launchd/init is gone for our purposes
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                        capture_output=True, text=True, timeout=10).stdout.strip()
    return bool(st) and not st.startswith("Z")


def _start(tmp, ignore):
    pid_file = Path(tmp) / "grandchild.pid"
    p = subprocess.Popen([sys.executable, "-c", CHILD, str(pid_file),
                          "1" if ignore else "0"],
                         stdin=subprocess.DEVNULL, start_new_session=True)
    deadline = time.monotonic() + READY_WAIT_SECONDS
    while not pid_file.exists():
        if time.monotonic() > deadline or p.poll() is not None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                pass
            p.wait(timeout=10)
            raise AssertionError(
                f"the child never started its grandchild within "
                f"{READY_WAIT_SECONDS}s - the machine is too loaded for this "
                f"test, not a verdict on kill_group")
        time.sleep(0.05)
    return p, int(pid_file.read_text())


def _cleanup(p, gpid):
    """Kill what this test started, by the pids it recorded."""
    for pid in (gpid, p.pid if p is not None else None):
        if pid is None:
            continue
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    if p is not None:
        try:
            p.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pass


def _wait_gone(pid, seconds):
    deadline = time.monotonic() + seconds
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not _alive(pid)


def test_a_grandchild_that_ignores_sigterm_is_killed():
    p = gpid = None
    old = sac.KILL_GRACE_SECONDS
    sac.KILL_GRACE_SECONDS = GRACE
    try:
        with tempfile.TemporaryDirectory(dir=_TMP) as tmp:
            p, gpid = _start(tmp, ignore=True)
            t0 = time.monotonic()
            sac.kill_group(p)
            elapsed = time.monotonic() - t0
            assert p.poll() is not None, "the direct child is not reaped"
            assert _wait_gone(gpid, GONE_WAIT_SECONDS), (
                f"grandchild {gpid} ignored SIGTERM and outlived kill_group "
                f"({elapsed:.1f}s) - SIGKILL never reached the group")
            assert elapsed < 4 * GRACE + 5, elapsed
    finally:
        sac.KILL_GRACE_SECONDS = old
        _cleanup(p, gpid)


def test_a_group_that_dies_on_sigterm_is_left_without_waiting_the_grace():
    """The zombie case: the leader is reaped by us, the orphaned grandchild by
    launchd/init. The wait must see the group empty, not run to the grace."""
    p = gpid = None
    old = sac.KILL_GRACE_SECONDS
    sac.KILL_GRACE_SECONDS = 8
    try:
        with tempfile.TemporaryDirectory(dir=_TMP) as tmp:
            p, gpid = _start(tmp, ignore=False)
            t0 = time.monotonic()
            sac.kill_group(p)
            elapsed = time.monotonic() - t0
            assert p.poll() is not None, "the direct child is not reaped"
            assert _wait_gone(gpid, GONE_WAIT_SECONDS), f"grandchild {gpid} alive"
            assert elapsed < 4, (
                f"kill_group waited {elapsed:.1f}s on a group that died on "
                f"SIGTERM - it ran towards the 8 s grace instead of seeing "
                f"the group empty")
    finally:
        sac.KILL_GRACE_SECONDS = old
        _cleanup(p, gpid)


def test_a_group_already_gone_is_not_an_error():
    p = subprocess.Popen([sys.executable, "-c", "pass"],
                         stdin=subprocess.DEVNULL, start_new_session=True)
    try:
        p.wait(timeout=20)
        t0 = time.monotonic()
        sac.kill_group(p)
        assert time.monotonic() - t0 < 2
    finally:
        _cleanup(p, None)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
