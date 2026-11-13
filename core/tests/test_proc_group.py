#!/usr/bin/env python3
"""CF-0655: `shared/proc_group.py` and the root's kills past a ceiling.

Each case runs a stand-in in its own session: it starts a grandchild that
ignores SIGTERM (and writes its pid), then sleeps and dies on SIGTERM itself.
A kill that waits only for the direct child returns with the grandchild still
running; every kill here must leave the group empty. The grace is patched small
so the file takes seconds. Grandchildren are killed by their remembered pid in
`finally`; files live under a `_tmproot` tree; nothing live is touched.
"""
import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(ROOT / "shared"))
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root  # noqa: E402
import proc_group  # noqa: E402
import supplement  # noqa: E402
from test_run_executor_ceiling_group import STAND_IN, _gone, _wait  # noqa: E402

TMP = tmp_root("proc-group-test-")
# the grandchild does not hold the step's pipes: `communicate` returns as soon
# as the direct child is dead, and only a wait for the group still sees it
OLD_SPAWN = 'subprocess.Popen([sys.executable, "-c", grandchild, pidfile])'
assert OLD_SPAWN in STAND_IN
STAND_IN_OFF_PIPES = STAND_IN.replace(OLD_SPAWN, OLD_SPAWN[:-1] + (
    ", stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)"))
FR = ROOT / "shared" / "factrule"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cj = _load("claim_judge_cf0655", FR / "claim_judge.py")
ans = _load("claim_answer_cf0655", FR / "claim_answer_claude.py")
_N = [0]


def _with_grandchild(kill, pipes=False, stand_in=STAND_IN):
    """Start the stand-in, call `kill(p)`, assert the whole group is gone."""
    _N[0] += 1
    d = TMP / f"case{_N[0]}"
    d.mkdir(parents=True)
    (d / "stand_in.py").write_text(stand_in)
    pidfile = d / "grandchild.pid"
    out = subprocess.PIPE if pipes else subprocess.DEVNULL
    p = subprocess.Popen([sys.executable, str(d / "stand_in.py"), str(pidfile)],
                         stdin=subprocess.DEVNULL, stdout=out, stderr=out, text=True,
                         start_new_session=True)
    gpid = None
    try:
        assert _wait(pidfile.exists, 15), "the grandchild never started"
        gpid = int(pidfile.read_text())
        t0 = time.time()
        res = kill(p)
        took = time.time() - t0
        assert _wait(lambda: _gone(gpid), 1.0), \
            f"grandchild {gpid} ignored SIGTERM and outlived the kill ({took:.2f} s)"
        assert proc_group.group_gone(p.pid)
        assert took < 8, took
        return res
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


def test_group_gone_and_kill_group_wait_for_the_whole_group():
    assert _with_grandchild(lambda p: proc_group.kill_group(p.pid, 0.5, reap=p.poll)) == "kill"
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"],
                         start_new_session=True)
    try:
        assert not proc_group.group_gone(p.pid)
        assert proc_group.kill_group(p.pid, 2, reap=p.poll) == "term"     # dies on SIGTERM
        assert proc_group.group_gone(p.pid)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait()


def test_claim_judge_kill_group_takes_the_grandchild():
    cj.KILL_GRACE_S = 0.5
    _with_grandchild(cj._kill_group, pipes=True)


def test_claim_answerer_kill_group_takes_the_grandchild():
    ans.KILL_GRACE_S = 0.5
    _with_grandchild(ans.kill_group, pipes=True)


def test_supplement_kill_group_takes_the_grandchild_and_returns_the_output():
    kill = lambda p: supplement._kill_group(p, grace=0.5)        # noqa: E731
    assert _with_grandchild(kill, pipes=True) == ("", "")
    assert _with_grandchild(kill, pipes=True, stand_in=STAND_IN_OFF_PIPES) == ("", "")


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
