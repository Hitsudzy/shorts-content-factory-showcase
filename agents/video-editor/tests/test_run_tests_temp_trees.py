#!/usr/bin/env python3
"""CF-0489: a full run of the video-editor suite leaves no temp trees behind.

26 video-editor files built fixtures under a bare `tempfile.mkdtemp()` (or an
eagerly evaluated `setdefault("RUNLOG_BATCH", mkdtemp(...))`) and never removed
them - `cf0139-editor-*`, `ve-*`, `cfNNNN-runlog-*`, measured 2026-10-02 (the
root guard, CF-0378, here; same as content-researcher and footage-indexer).
The runner now gives every file a fresh TMPDIR of its own (rt-*);
whatever a file leaves there once its process group is dead makes the file
FAILED, by name, and is removed.

Points tests/run_tests.py (as a subprocess, `--dir`) at fixture files, with the
runner's own TMPDIR pointed at an empty directory, and checks:
  - a file that cleans up passes, and saw a TMPDIR of its own;
  - Node's compile cache (Remotion) is pointed at the suite's tempdir, so a
    rendering file neither loses it nor leaves it behind;
  - a file whose checks pass but which leaves a tree is FAILED, named, CF-0489;
  - after the run the runner's TMPDIR is empty again - no leaked tree, no rt-* dir.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
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
Path(sys.argv[0]).with_name("clean.nodecache").write_text(os.environ.get("NODE_COMPILE_CACHE", ""))
print("1/1 passed")
'''

LEAKY = '''\
import tempfile
from pathlib import Path
d = Path(tempfile.mkdtemp(prefix="leaky-"))
(d / "plan.assetless-rung.json").write_text("{}")
print("1/1 passed")
'''


_RUN = {}


def run_once():
    """Run the runner on the two fixture files once; every check reads this."""
    if _RUN:
        return _RUN
    with tempfile.TemporaryDirectory() as fixtures, \
            tempfile.TemporaryDirectory() as parent_tmp:
        fixtures, parent_tmp = Path(fixtures), Path(parent_tmp)
        (fixtures / "test_a_clean.py").write_text(CLEAN)
        (fixtures / "test_b_leaky.py").write_text(LEAKY)
        env = dict(os.environ, TMPDIR=str(parent_tmp))
        env.pop("NODE_COMPILE_CACHE", None)
        proc = subprocess.run([sys.executable, str(RUNNER), "--dir", str(fixtures)],
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                              text=True, env=env, timeout=60)
        print(proc.stdout)
        read = lambda name: (fixtures / name).read_text() if (fixtures / name).exists() else ""
        _RUN.update(rc=proc.returncode, out=proc.stdout, parent=parent_tmp,
                    own=read("clean.tmpdir"), cache=read("clean.nodecache"),
                    left=sorted(os.listdir(parent_tmp)))
    return _RUN


def test_runner_exits_1():
    assert run_once()["rc"] == 1, run_once()["rc"]


def test_clean_file_passes():
    assert "PASS test_a_clean.py: 1/1" in run_once()["out"]


def test_clean_file_ran_with_a_fresh_tmpdir_of_its_own():
    r = run_once()
    own = Path(r["own"])
    assert own.parent == r["parent"] and own.name.startswith("rt-"), r["own"]


def test_node_compile_cache_stays_in_the_suites_tempdir():
    r = run_once()
    assert r["cache"] == str(r["parent"] / "node-compile-cache"), r["cache"]


def test_leaky_file_is_failed_by_name_cf0489():
    out = run_once()["out"]
    assert ("FAIL test_b_leaky.py: left 1 temp entry behind in its TMPDIR (leaky-" in out
            and "CF-0489" in out)


def test_total_counts_the_leaky_file_as_failed():
    assert "TOTAL 2/2 passed in 2 files - 1 FAILED" in run_once()["out"]


def test_nothing_left_in_the_runners_tmpdir():
    assert run_once()["left"] == [], run_once()["left"]


def main():
    tests = [f for name, f in sorted(globals().items())
             if name.startswith("test_") and callable(f)]
    passed = 0
    for t in tests:
        try:
            t()
            passed += 1
            print(f"ok: {t.__name__}")
        except Exception as e:  # noqa: BLE001 - every check reports, none stops the rest
            print(f"FAIL: {t.__name__} - {e!r}")
    print(f"{passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    sys.exit(main())
