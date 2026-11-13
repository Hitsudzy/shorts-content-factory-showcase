#!/usr/bin/env python3
"""CF-0853 / CF-0854: a checker of step 6 handed something that is not the
batch file refuses as usage (exit 2, or its own "cannot answer" 3), never
dies on a traceback.

ExampleTech `2026-10-23T1504Z`: the stage's operator ran the gates in a
shell loop of its own, `python3 $S/$g ${g%% *}` - which handed each checker
its own script name as the batch file (`check_production_fact.py
check_production_fact.py`). `check_production_fact.py` and
`check_hook_opener.py` read the argument with a bare `Path.read_text()` and
died on `FileNotFoundError`; the runlog recorded a `failed` event with that
error, and the triage (`shared/runlog/triage.py`: anything but `SystemExit`
is a crash) filed two аварии. Five more checkers had the same bare read.
They now take the argument through `scripts/_batch_arg.py` (`type=`), which
turns a missing file into argparse's own usage refusal naming what was
expected - `SystemExit: 2`, a refusal for the triage, not a crash - and says
outright when the argument is a script name.

Offline: every checker runs as a subprocess in a temp cwd with no batch for
the runlog to write to.
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from _tmproot import tmp_root   # noqa: E402

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
TMP = tmp_root("cr-barg-")
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import _batch_arg  # noqa: E402

# The seven that crashed before CF-0853; each must now use the helper.
WIRED = ("check_production_fact.py", "check_hook_opener.py", "check_number_density.py",
         "check_narration_budget.py", "check_sounds.py", "check_proofs.py",
         "check_reactions.py")


def _checkers():
    """Every check_*.py whose first positional is `batch_file`."""
    return sorted(p for p in SCRIPTS.glob("check_*.py")
                  if 'add_argument("batch_file"' in p.read_text())


def _run(script, *args):
    env = dict(os.environ)
    env.pop("RUNLOG_BATCH", None)
    r = subprocess.run([sys.executable, str(script), *args], cwd=TMP, env=env,
                       capture_output=True, text=True, timeout=120, stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout + r.stderr


def test_the_helper_passes_a_file_through_unchanged():
    f = TMP / "03-content-researcher.json"
    f.write_text("{}")
    assert _batch_arg.batch_file(str(f)) == str(f)


def test_the_helper_names_a_script_name_as_one():
    try:
        _batch_arg.batch_file("check_production_fact.py")
    except argparse.ArgumentTypeError as exc:
        msg = str(exc)
        assert "script name" in msg and "03-content-researcher.json" in msg, msg
    else:
        raise AssertionError("a script name was taken for the batch file")


def test_the_helper_refuses_a_directory_without_the_batch_file_and_a_missing_file():
    empty = TMP / "empty-batch"
    empty.mkdir(exist_ok=True)
    for value in (str(empty), str(TMP / "nope" / "03-content-researcher.json")):
        try:
            _batch_arg.batch_file(value)
        except argparse.ArgumentTypeError as exc:
            assert "03-content-researcher.json" in str(exc), exc
        else:
            raise AssertionError(f"{value} was taken for the batch file")


def test_the_helper_takes_the_batch_folder_for_its_file():
    """CF-0869: `pipeline/<channel>/<batch>` names the batch as well as its
    03-content-researcher.json (the two forms already_published.py takes)."""
    folder = TMP / "batch-folder"
    folder.mkdir(exist_ok=True)
    f = folder / "03-content-researcher.json"
    f.write_text("{}")
    assert _batch_arg.batch_file(str(folder)) == str(f)


def test_beside_takes_the_file_the_1514z_spelling_the_folder_and_the_batch_file():
    """CF-0869, example-film `2026-10-26T1514Z`: `--trend
    <03-content-researcher.json>/../01-trend-hunter.json` crashed
    check_proofs.py on NotADirectoryError. `beside()` resolves it by text and
    also takes the batch folder or the batch file; anything else is exit 2."""
    folder = TMP / "beside"
    folder.mkdir(exist_ok=True)
    batch = folder / "03-content-researcher.json"
    batch.write_text("{}")
    trend = folder / "01-trend-hunter.json"
    trend.write_text("{}")
    conv = _batch_arg.beside(_batch_arg.TREND_FILE)
    assert conv(str(trend)) == str(trend)
    assert conv(f"{batch}/../01-trend-hunter.json") == str(trend)
    assert conv(str(folder)) == str(trend)
    assert conv(str(batch)) == str(trend)
    assert _batch_arg.default_beside(str(batch), _batch_arg.TREND_FILE) == str(trend)
    lonely = TMP / "beside-lonely"
    lonely.mkdir(exist_ok=True)
    (lonely / "03-content-researcher.json").write_text("{}")
    assert _batch_arg.default_beside(str(lonely / "03-content-researcher.json"),
                                     _batch_arg.TREND_FILE) is None
    for bad in (str(lonely), f"{lonely}/03-content-researcher.json/../01-trend-hunter.json",
                str(TMP / "nope.json")):
        try:
            conv(bad)
        except argparse.ArgumentTypeError as exc:
            assert "01-trend-hunter.json" in str(exc), exc
        else:
            raise AssertionError(f"{bad} was taken for the trend file")


def test_the_trend_options_read_through_beside():
    for name in ("check_proofs.py", "check_demo.py", "check_graphics.py",
                 "check_proof_quotes.py"):
        src = (SCRIPTS / name).read_text()
        assert "type=_batch_arg.beside(_batch_arg.TREND_FILE)" in src, name


def test_the_crashed_checkers_use_the_helper():
    for name in WIRED:
        src = (SCRIPTS / name).read_text()
        assert "type=_batch_arg.batch_file" in src, name


def test_no_checker_dies_on_its_own_name_as_the_batch_file():
    """The 1504Z call, verbatim, against every checker that takes a batch
    file: a usage refusal (2) or "cannot answer" (3), no traceback."""
    bad = []
    checkers = _checkers()
    assert len(checkers) >= 15, checkers
    for script in checkers:
        rc, out = _run(script, script.name)
        if rc not in (2, 3) or "Traceback" in out:
            bad.append(f"{script.name}: rc={rc} {out.strip().splitlines()[-1:]}")
    assert not bad, "\n".join(bad)


def test_the_second_1504z_call_is_a_usage_refusal_too():
    """`check_production_fact.py <03> check_production_fact.py` - an extra
    positional - was already argparse's exit 2; it stays that."""
    f = TMP / "x" / "03-content-researcher.json"
    f.parent.mkdir(exist_ok=True)
    f.write_text('{"scripts": []}')
    for name in ("check_production_fact.py", "check_hook_opener.py"):
        rc, out = _run(SCRIPTS / name, str(f), name)
        assert rc == 2 and "Traceback" not in out, (name, rc, out)


def test_the_script_name_refusal_says_what_to_pass():
    rc, out = _run(SCRIPTS / "check_production_fact.py", "check_production_fact.py")
    assert rc == 2, out
    assert "script name" in out and "03-content-researcher.json" in out, out


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
