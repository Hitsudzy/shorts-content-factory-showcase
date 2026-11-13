#!/usr/bin/env python3
"""CF-0680: the supplement's deadline watcher (`ingest_batch.Deadline.arm`)
SIGKILLs every process it SIGTERMed, even one orphaned in between.

The bug: the watcher re-listed the descendants (`ps` walked by ppid) on every
sweep and SIGKILLed only those still on the list. A grandchild that ignores
SIGTERM, whose parent died on it, is adopted by launchd/init, drops off the
list, and the SIGKILL `grace` seconds later never reached it.

Why not a group kill (as `sieve_answer_claude.kill_group`, CF-0655): the root
starts FI in its own session (shared/runlog/supplement.py), so FI leads the
group its children - started through the shared `runlog.run_child` and plain
`subprocess.run` - are in; `killpg` would take FI down with them. The watcher
instead remembers every PID it SIGTERMed with its start time and SIGKILLs by
that memory, checking the start time so a reused PID is never hit.

Pinned here:
- on real processes (no network, no live data): a grandchild that ignores
  SIGTERM and outlives its parent is SIGKILLed after the grace;
- on stand-ins: a PID whose start time changed (reused) is not SIGKILLed; a
  PID gone from `ps` is dropped.

Every process a test starts is killed in `finally` by the PID the test
recorded itself - never by name. Temp files live under `_tmproot.tmp_root`.

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

import ingest_batch as ib          # noqa: E402
from _tmproot import tmp_root      # noqa: E402

_TMP = tmp_root("cf0680-")

SWEEP = 0.05
GRACE = 0.3
READY_WAIT_SECONDS = 20     # starting two Pythons under load costs seconds
GONE_WAIT_SECONDS = 5       # well past GRACE: SIGKILL had every chance

# The child starts a grandchild that ignores SIGTERM, waits for its pid file,
# then sleeps; the child itself dies on SIGTERM (default disposition), so the
# grandchild is orphaned the moment the watcher's SIGTERM lands.
CHILD = r'''
import os, subprocess, sys, time
pid_file = sys.argv[1]
grand = (
    "import os, signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "tmp = sys.argv[1] + '.part'\n"
    "open(tmp, 'w').write(str(os.getpid()))\n"
    "os.replace(tmp, sys.argv[1])\n"
    "time.sleep(120)\n")
subprocess.Popen([sys.executable, "-c", grand, pid_file])
while not os.path.exists(pid_file):
    time.sleep(0.05)
time.sleep(120)
'''


def _alive(pid):
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return False
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)],
                        capture_output=True, text=True, timeout=10).stdout.strip()
    return bool(st) and not st.startswith("Z")


def _wait_gone(pid, seconds):
    deadline = time.monotonic() + seconds
    while _alive(pid) and time.monotonic() < deadline:
        time.sleep(0.1)
    return not _alive(pid)


def _kill(pid):
    if pid is None:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass


def test_an_orphaned_grandchild_that_ignores_sigterm_is_sigkilled():
    p = gpid = None
    d = None
    try:
        with tempfile.TemporaryDirectory(dir=_TMP) as tmp:
            pid_file = Path(tmp) / "grandchild.pid"
            p = subprocess.Popen([sys.executable, "-c", CHILD, str(pid_file)],
                                 stdin=subprocess.DEVNULL)
            ready = time.monotonic() + READY_WAIT_SECONDS
            while not pid_file.exists():
                assert time.monotonic() < ready and p.poll() is None, (
                    "the child never started its grandchild - the machine is "
                    "too loaded for this test, not a verdict on the watcher")
                time.sleep(0.05)
            gpid = int(pid_file.read_text())
            child = p.pid
            # Only what this test started: the child and whatever is below it.
            d = ib.Deadline(0, clock=lambda: 1.0)
            d.arm(descendants=lambda: ([child] if _alive(child) else [])
                  + ib.list_descendants(child),
                  sweep=SWEEP, grace=GRACE)
            p.wait(timeout=10)          # the child dies on the SIGTERM
            assert gpid in d.killed, (d.killed, gpid)
            assert _wait_gone(gpid, GONE_WAIT_SECONDS), (
                f"grandchild {gpid} ignored SIGTERM, was orphaned when its "
                f"parent died, and outlived the {GRACE}s grace by "
                f"{GONE_WAIT_SECONDS}s - SIGKILL never reached it")
    finally:
        if d is not None:
            d.disarm()
        _kill(gpid)
        if p is not None:
            _kill(p.pid)
            try:
                p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass


def _run_watcher(listings, stamps_seq, seconds=0.5):
    """Stand-ins: `descendants()` and `starts()` answer from the given
    sequences (the last answer repeats); returns the (pid, sig) sent."""
    sent = []

    def seq(items):
        it = iter(items)
        last = [None]

        def nxt(*_):
            try:
                last[0] = next(it)
            except StopIteration:
                pass
            return last[0]
        return nxt

    d = ib.Deadline(0, clock=lambda: 1.0)
    d.arm(descendants=seq(listings), starts=seq(stamps_seq),
          send=lambda pid, sig: sent.append((pid, sig)),
          sweep=0.02, grace=0.05)
    time.sleep(seconds)
    d.disarm()
    return d, sent


def test_a_reused_pid_is_not_sigkilled():
    # 4242 is SIGTERMed, leaves the list, and its PID comes back with another
    # start time: a stranger now, never SIGKILLed.
    d, sent = _run_watcher([[4242], []],
                           [{4242: "Sat Oct 10 12:00:00 2026"},
                            {4242: "Sat Oct 10 12:00:07 2026"}])
    assert (4242, signal.SIGTERM) in sent
    assert (4242, signal.SIGKILL) not in sent, sent
    assert d.killed == [4242]


def test_a_pid_gone_from_ps_is_dropped_not_signalled():
    d, sent = _run_watcher([[4242], []], [{4242: "Sat Oct 10 12:00:00 2026"}, {}])
    assert sent == [(4242, signal.SIGTERM)], sent


def test_an_orphan_with_the_same_start_time_is_sigkilled():
    # Off the list (orphaned) but still the same process: SIGKILLed.
    stamp = {4242: "Sat Oct 10 12:00:00 2026"}
    d, sent = _run_watcher([[4242], []], [stamp])
    assert (4242, signal.SIGKILL) in sent, sent


def test_process_starts_reads_this_process_and_not_a_reaped_one():
    me = os.getpid()
    done = subprocess.Popen([sys.executable, "-c", "pass"])
    done.wait(timeout=20)              # reaped: its pid is free now
    got = ib.process_starts([me, done.pid])
    assert set(got) == {me} and got[me].strip(), got
    assert ib.process_starts([]) == {}


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
