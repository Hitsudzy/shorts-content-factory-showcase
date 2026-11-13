#!/usr/bin/env python3
"""CF-0489 (brought here by CF-0520): a full run of the trend-hunter suite leaves no temp trees behind.

test_api_key.py and test_runlog_events.py built a module-level
`tempfile.mkdtemp()` and never removed it: 122 th-runlog-* and 65 th-apikey-*
in the real TMPDIR by 2026-10-03 (CF-0497). The runner now gives every file a
fresh TMPDIR of its own (rt-*); whatever a file leaves there once its process
group is dead makes the file FAILED, by name, and is removed.

Points tests/run_tests.py (as a subprocess, `--dir`) at fixture files, with the
runner's own TMPDIR pointed at an empty directory, and checks:
  - a file that cleans up passes, and saw a TMPDIR of its own;
  - a file whose checks pass but which leaves a tree is FAILED, named, CF-0489;
  - after the run the runner's TMPDIR is empty again - no leaked tree, no rt-* dir.
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNNER = HERE / "run_tests.py"

CLEAN = '''\
import os, shutil, sys, tempfile
from pathlib import Path
d = tempfile.mkdtemp(prefix="clean-")
shutil.rmtree(d)
Path(sys.argv[0]).with_name("clean.tmpdir").write_text(tempfile.gettempdir())
print("1/1 passed")
'''

LEAKY = '''\
import tempfile
from pathlib import Path
d = Path(tempfile.mkdtemp(prefix="leaky-"))
(d / "example-film.json").write_text("{}")
print("1/1 passed")
'''


def main():
    checks = []

    def check(name, ok, detail=""):
        checks.append(ok)
        print(f"{'ok' if ok else 'FAIL'}: {name}{f' - {detail}' if detail else ''}")

    with tempfile.TemporaryDirectory() as fixtures, \
            tempfile.TemporaryDirectory() as parent_tmp:
        fixtures, parent_tmp = Path(fixtures), Path(parent_tmp)
        (fixtures / "test_a_clean.py").write_text(CLEAN)
        (fixtures / "test_b_leaky.py").write_text(LEAKY)
        env = dict(os.environ, TMPDIR=str(parent_tmp))
        proc = subprocess.run([sys.executable, str(RUNNER), "--dir", str(fixtures)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=env, timeout=60)
        out = proc.stdout
        print(out)

        check("runner exits 1", proc.returncode == 1, f"got {proc.returncode}")
        check("clean file shows PASS", "PASS test_a_clean.py: 1/1" in out)
        seen = fixtures / "clean.tmpdir"
        own = seen.read_text() if seen.exists() else ""
        check("clean file ran with a fresh TMPDIR of its own (rt-*)",
              Path(own).parent == parent_tmp and Path(own).name.startswith("rt-"),
              f"got {own!r}")
        check("leaky file is FAILED by name, for its leftover, CF-0489",
              "FAIL test_b_leaky.py: left 1 temp entry behind in its TMPDIR (leaky-" in out
              and "CF-0489" in out)
        check("TOTAL counts the leaky file as failed",
              "TOTAL 2/2 passed in 2 files - 1 FAILED" in out)
        left = sorted(os.listdir(parent_tmp))
        check("nothing left in the runner's TMPDIR - no leaked tree, no rt-* dir",
              left == [], f"left {left}")

    passed = sum(checks)
    print(f"{passed}/{len(checks)} passed")
    return 0 if passed == len(checks) else 1


if __name__ == "__main__":
    sys.exit(main())
