#!/usr/bin/env python3
"""CF-0504: the runner survives `os.killpg` answering EPERM.

On macOS `killpg` raises PermissionError (not ProcessLookupError) when the
group has no live member left - the leader is a zombie not yet reaped. The
runner used to catch only ProcessLookupError and died with a traceback: no
FAILED line, no TOTAL. Here the runner is started (as a subprocess, `--dir` on
a temp directory) through a small wrapper that replaces `os.killpg` with one
that does the real kill and then raises PermissionError every time. One file
passes, one sleeps past a 2 s ceiling. The runner must still name the hung
file as FAILED by the ceiling and reach TOTAL, with no traceback.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CEILING = 2

PASSING = '''\
print("ok")
print("1/1 passed")
'''

HANGING = '''\
import time
print("going to sleep", flush=True)
time.sleep(60)
print("1/1 passed")
'''

# Imports the runner as a module, swaps os.killpg, runs main(). The real kill
# still happens (so the hung file dies and the test stays quick); the error is
# what macOS says about a group whose leader is only a zombie.
WRAPPER = '''\
import errno, os, sys
sys.path.insert(0, sys.argv[1])
real_killpg = os.killpg
calls = []

def eperm_killpg(pgid, sig):
    calls.append(pgid)
    try:
        real_killpg(pgid, sig)
    except OSError:
        pass
    raise PermissionError(errno.EPERM, "Operation not permitted")

os.killpg = eperm_killpg
import run_tests
sys.argv = ["run_tests.py", "--dir", sys.argv[2]]
code = run_tests.main()
print(f"[wrapper] killpg calls: {len(calls)}", flush=True)
sys.exit(code)
'''


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"{'ok' if ok else 'FAIL'}: {name}{f' - {detail}' if detail else ''}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        files = tmp / "files"
        files.mkdir()
        (files / "test_a_passes.py").write_text(PASSING)
        (files / "test_b_hangs.py").write_text(HANGING)
        wrapper = tmp / "wrapper.py"
        wrapper.write_text(WRAPPER)
        env = dict(os.environ, RUN_TESTS_FILE_TIMEOUT=str(CEILING),
                   RUN_TESTS_UNDER_VENV="1")
        started = time.monotonic()
        proc = subprocess.run([sys.executable, str(wrapper), str(HERE), str(files)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=env, timeout=60)
        elapsed = time.monotonic() - started
        out = proc.stdout
        print(out)

        check("no traceback", "Traceback" not in out and "PermissionError" not in out)
        check("the fake killpg was actually called",
              "[wrapper] killpg calls: 0" not in out and "[wrapper] killpg calls:" in out)
        check("runner exits 1", proc.returncode == 1, f"got {proc.returncode}")
        check("passing file shows PASS", "PASS test_a_passes.py: 1/1" in out)
        check("hung file listed FAILED by the ceiling",
              f"FAILED test_b_hangs.py: exceeded the per-file ceiling of {CEILING} s" in out)
        check("runner reached TOTAL", "TOTAL 1/1 passed in 2 files - 1 FAILED" in out)
        check("runner came back promptly", elapsed < 20, f"took {elapsed:.1f} s")

    passed = sum(checks)
    print(f"{passed}/{len(checks)} passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
