#!/usr/bin/env python3
"""CF-0077: the runner's per-file ceiling.

Points tests/run_tests.py (as a subprocess, `--dir`) at a temp directory with
one file that passes and one that sleeps past a tiny ceiling
(RUN_TESTS_FILE_TIMEOUT=2) while holding a grandchild that sleeps even longer.
The runner must exit 1, name the sleeping file and the ceiling, show the
passing file as PASS, count the hung file as failed in the TOTAL line - and
the grandchild must be dead, because the whole process group is killed.
Runs in a few seconds; the sleeps are only there to be cut short.
"""
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_tests.py"
CEILING = 2

PASSING = '''\
print("ok")
print("1/1 passed")
'''

# Sleeps far past the ceiling, and spawns a grandchild that sleeps even
# longer, so the test can tell "killed the child" from "killed the group".
HANGING = '''\
import subprocess, sys, time
from pathlib import Path
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path(sys.argv[0]).with_name("grandchild.pid").write_text(str(child.pid))
print("going to sleep", flush=True)
time.sleep(60)
print("1/1 passed")
'''


def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"{'ok' if ok else 'FAIL'}: {name}{f' - {detail}' if detail else ''}")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        (tmp / "test_a_passes.py").write_text(PASSING)
        (tmp / "test_b_hangs.py").write_text(HANGING)
        env = dict(os.environ, RUN_TESTS_FILE_TIMEOUT=str(CEILING))
        started = time.monotonic()
        proc = subprocess.run([sys.executable, str(RUNNER), "--dir", str(tmp)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=env, timeout=60)
        elapsed = time.monotonic() - started
        out = proc.stdout
        print(out)

        check("runner exits 1", proc.returncode == 1, f"got {proc.returncode}")
        check("passing file shows PASS", "PASS test_a_passes.py: 1/1" in out)
        expected = (f"FAIL test_b_hangs.py: exceeded the per-file ceiling of "
                    f"{CEILING} s")
        check("hung file named with the ceiling", expected in out,
              f"expected {expected!r}")
        check("hint says hung, not slow",
              "hung, not slow" in out and "RUN_TESTS_FILE_TIMEOUT" in out)
        check("hung file listed in the FAILED summary",
              "FAILED test_b_hangs.py: exceeded the per-file ceiling" in out)
        check("TOTAL counts the hung file as failed",
              "TOTAL 1/1 passed in 2 files - 1 FAILED" in out)
        check("the hung file's own output was still echoed",
              "going to sleep" in out)
        check("runner came back promptly", elapsed < 10, f"took {elapsed:.1f} s")

        pid_file = tmp / "grandchild.pid"
        check("hung file spawned its grandchild", pid_file.exists())
        if pid_file.exists():
            pid = int(pid_file.read_text())
            deadline = time.monotonic() + 3
            while alive(pid) and time.monotonic() < deadline:
                time.sleep(0.1)
            dead = not alive(pid)
            if not dead:
                os.kill(pid, 9)
            check("grandchild died with the process group", dead)

    passed = sum(checks)
    print(f"{passed}/{len(checks)} passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
