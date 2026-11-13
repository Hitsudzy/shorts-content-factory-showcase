#!/usr/bin/env python3
"""CF-0523: the defaults of the Editor's production scripts that point at the
live factory tree can be moved by a test without moving FACTORY_ROOT.

Before: every write_batch_metadata.py subprocess of the suite read the user's
live `publish/acceptance-log.json` (retired_shots.default_acceptance_log), and
every qc_render.py subprocess looked the tests' synthetic shot ids up in the
live `shared/footage/` (its `--footage-dir` default ignored `$FOOTAGE_DIR`,
which build_render_plan.py already followed). Pinned here: the two knobs, the
flag, and that `_isolated_runlog` points both at temp paths.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import retired_shots  # noqa: E402

def _help(script, **env):
    e = dict(os.environ, COLUMNS="400", **env)
    r = subprocess.run([sys.executable, str(SCRIPTS / script), "--help"],
                       capture_output=True, text=True, env=e, timeout=120)
    assert r.returncode == 0, r.stderr
    return r.stdout


def test_isolation_points_both_knobs_at_temp_paths():
    tmp = Path(tempfile.gettempdir()).resolve()
    for name in ("ACCEPTANCE_LOG", "FOOTAGE_DIR"):
        val = os.environ.get(name)
        assert val, f"{name} not exported by _isolated_runlog"
        assert Path(val).resolve().is_relative_to(tmp), (name, val)
    assert not Path(os.environ["ACCEPTANCE_LOG"]).exists()


def test_acceptance_log_default_follows_the_variable():
    log = tmp_root("cf0523-log-") / "verdicts.json"
    old = os.environ.get("ACCEPTANCE_LOG")
    os.environ["ACCEPTANCE_LOG"] = str(log)
    try:
        assert retired_shots.default_acceptance_log() == log
        assert retired_shots.acceptance_verdicts(
            retired_shots.default_acceptance_log()) == {}
    finally:
        if old is None:
            os.environ.pop("ACCEPTANCE_LOG", None)
        else:
            os.environ["ACCEPTANCE_LOG"] = old


def test_acceptance_log_default_without_the_variable_is_the_publish_log():
    old = os.environ.pop("ACCEPTANCE_LOG", None)
    try:
        got = retired_shots.default_acceptance_log()
        assert got is None or got.parts[-2:] == ("publish", "acceptance-log.json"), got
    finally:
        if old is not None:
            os.environ["ACCEPTANCE_LOG"] = old


def test_write_batch_metadata_takes_the_flag():
    assert "--acceptance-log" in _help("write_batch_metadata.py")


def test_qc_render_footage_dir_default_follows_the_variable():
    pool = tmp_root("cf0523-pool-")
    out = _help("qc_render.py", FOOTAGE_DIR=str(pool))
    assert f"default {pool}:" in out, out[-600:]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
