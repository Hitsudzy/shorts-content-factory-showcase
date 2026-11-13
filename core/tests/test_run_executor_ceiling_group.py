#!/usr/bin/env python3
"""CF-0655: a run killed past its ceiling is killed with its whole process
group, not only with the wrapper's direct child.

The wrapper (`run_executor.py _exec`) catches SIGTERM, forwards it to its child
and writes the exit file when that child dies. The ceiling's wait used to stop
on that exit file - so a grandchild in the same group that ignores SIGTERM
outlived the ceiling: no SIGKILL was ever sent to the group.

Here the real wrapper runs a stand-in that starts such a grandchild and dies on
SIGTERM itself; `_kill_past_ceiling` is called on a minimal executor stand-in
with a 1 s grace. The grandchild is killed by pid in `finally` whatever happens.
Everything lives under a `_tmproot` tree; nothing live is touched.
"""
import os
import signal
import subprocess
import sys
import time
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "shared"))

from _tmproot import tmp_root  # noqa: E402
import run_executor as rx  # noqa: E402

TMP = tmp_root("run-executor-ceiling-group-test-")

STAND_IN = r'''
import os, signal, subprocess, sys, time
pidfile = sys.argv[1]
grandchild = (
    "import os, signal, sys, time\n"
    "signal.signal(signal.SIGTERM, signal.SIG_IGN)\n"
    "open(sys.argv[1] + '.tmp', 'w').write(str(os.getpid()))\n"
    "os.replace(sys.argv[1] + '.tmp', sys.argv[1])\n"
    "time.sleep(60)\n")
subprocess.Popen([sys.executable, "-c", grandchild, pidfile])
time.sleep(60)                      # dies on SIGTERM (the default action)
'''


def _gone(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    st = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
    return not st.stdout.strip() or st.stdout.strip().startswith("Z")


def _wait(cond, timeout):
    t0 = time.time()
    while time.time() - t0 < timeout:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


def test_a_grandchild_that_ignores_sigterm_does_not_outlive_the_ceiling():
    batch = TMP / "batch-grandchild"
    (batch / "logs").mkdir(parents=True)
    script = batch / "stand_in.py"
    script.write_text(STAND_IN)
    pidfile = batch / "grandchild.pid"
    exit_file = batch / "logs" / "run.exit"
    wrapped = [sys.executable, str(Path(rx.__file__).resolve()), "_exec",
               "--exit-file", str(exit_file), "--log", str(batch / "logs" / "run.log"),
               "--cwd", str(batch), "--", sys.executable, str(script), str(pidfile)]
    p = subprocess.Popen(wrapped, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)
    gpid = None
    try:
        assert _wait(pidfile.exists, 15), "the grandchild never started"
        gpid = int(pidfile.read_text())
        rec = {"pid": p.pid, "pgid": p.pid, "exit_file": "logs/run.exit"}
        ex = types.SimpleNamespace(batch=batch, kill_grace_s=1.0, poll=0.05, minute_s=60.0,
                                   _children={"run": p}, save=lambda: None,
                                   out=lambda *_a, **_k: None)
        t0 = time.time()
        code = rx.Executor._kill_past_ceiling(ex, "run", rec, 60)
        took = time.time() - t0
        assert _wait(lambda: _gone(gpid), 1.0), (
            f"grandchild {gpid} ignored SIGTERM and outlived the ceiling "
            f"(kill returned {code} after {took:.2f} s)")
        assert code == -int(signal.SIGTERM), code       # the wrapper's exit file still decides
        assert rec["exit"] == code and rec["timed_out"]["after_s"] == 60
        assert took < 8, took
    finally:
        if gpid is not None and not _gone(gpid):
            try:
                os.kill(gpid, signal.SIGKILL)
            except OSError:
                pass
        if p.poll() is None:
            try:
                os.killpg(p.pid, signal.SIGKILL)
            except OSError:
                pass
            p.wait()


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
