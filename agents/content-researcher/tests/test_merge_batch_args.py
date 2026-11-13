#!/usr/bin/env python3
"""CF-0907: `merge_batch_file.py` refuses a call whose batch path is broken,
before it reads or writes anything.

`example-film/2026-11-01T0832Z`, 13:23:35Z: the reserve call ran

    python3 agents/content-researcher/scripts/merge_batch_file.py \\
        $B/03-content-researcher.json --add /tmp/03-reserve-topics.json

in a Bash call where `B` was set only inside a Python heredoc, never in the
shell. `$B` expanded to nothing, the batch file became
`/03-content-researcher.json`, it did not exist, so "the fragment simply
becomes it" - and the atomic write tried to put its temp file into `/`
(OSError: Read-only file system). Had the path been plain
`03-content-researcher.json` the fragment would have been written, quietly,
into whatever directory the shell stood in.

The rule now: the batch file is `<...>/pipeline/<channel>/<batch-id>/
03-content-researcher.json` in a batch directory that exists. Anything else -
an empty path, the root, the cwd outside a batch, a directory, another file
name, a tree that is not under `pipeline/` - exits 2 with a line saying what
was wrong, and nothing is created. This is a refusal of the call, never of a
topic or a video.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

from _tmproot import tmp_root   # noqa: E402  (CF-0489: this file's temp trees go at exit)
_TMP = tmp_root("cr-merge-args-")

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "scripts"))
os.environ.setdefault("RUNLOG_BATCH", tempfile.mkdtemp(dir=_TMP))

import merge_batch_file as mbf  # noqa: E402

SKILL = (REPO / ".claude" / "skills" / "content-researcher" / "SKILL.md").read_text()
BATCH_ID = "2026-11-01T0832Z"


def _fragment_in(d):
    frag = Path(d) / "fragment.json"
    frag.write_text(json.dumps({
        "batch_id": BATCH_ID, "channel": "example-film", "warnings": [],
        "skipped": [], "scripts": [{"topic_id": "lf-003", "hook": "..."}]}))
    return frag


def _batch():
    root = Path(tempfile.mkdtemp(dir=_TMP))
    d = root / "pipeline" / "example-film" / BATCH_ID
    d.mkdir(parents=True)
    return root, d


def _call(batch_file, frag):
    err = io.StringIO()
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
        try:
            code = mbf.main([str(batch_file), "--add", str(frag)])
        except SystemExit as exc:      # argparse
            code = exc.code
    return code, err.getvalue()


def _refused(batch_file, frag, words):
    code, err = _call(batch_file, frag)
    assert code == 2, (code, err)
    assert "merge_batch_file.py" in err and "CF-0907" in err, err
    assert words in err, err
    return err


def test_an_empty_shell_variable_is_refused_not_written_to_root():
    """The exact call of 0832Z: `$B` empty."""
    _, d = _batch()
    _refused("/03-content-researcher.json", _fragment_in(d), "pipeline")
    assert not Path("/03-content-researcher.json").exists()


def test_an_empty_path_is_refused():
    _, d = _batch()
    _refused("", _fragment_in(d), "empty")


def test_a_bare_name_in_a_cwd_that_is_not_a_batch_is_refused():
    root, d = _batch()
    frag = _fragment_in(d)
    here = os.getcwd()
    os.chdir(root)
    try:
        _refused("03-content-researcher.json", frag, "pipeline")
    finally:
        os.chdir(here)
    assert not (root / "03-content-researcher.json").exists()


def test_a_tree_outside_pipeline_is_refused():
    root, d = _batch()
    other = root / "elsewhere" / "example-film" / BATCH_ID
    other.mkdir(parents=True)
    _refused(other / "03-content-researcher.json", _fragment_in(d), "pipeline")
    assert not (other / "03-content-researcher.json").exists()


def test_dot_dot_out_of_pipeline_is_refused():
    root, d = _batch()
    (root / "x" / "y").mkdir(parents=True)
    sneaky = d / ".." / ".." / ".." / "x" / "y" / "03-content-researcher.json"
    _refused(sneaky, _fragment_in(d), "pipeline")
    assert not (root / "x" / "y" / "03-content-researcher.json").exists()


def test_a_batch_directory_that_does_not_exist_is_refused():
    root, d = _batch()
    ghost = root / "pipeline" / "example-film" / "2026-11-01T9999Z"
    _refused(ghost / "03-content-researcher.json", _fragment_in(d), "does not exist")
    assert not ghost.exists()


def test_the_batch_directory_itself_is_refused():
    _, d = _batch()
    _refused(d, _fragment_in(d), "03-content-researcher.json")


def test_another_file_name_is_refused():
    _, d = _batch()
    _refused(d / "02-compliance-checker.json", _fragment_in(d),
             "03-content-researcher.json")
    assert not (d / "02-compliance-checker.json").exists()


def test_a_proper_batch_file_still_merges():
    _, d = _batch()
    code, err = _call(d / "03-content-researcher.json", _fragment_in(d))
    assert code == 0, err
    doc = json.loads((d / "03-content-researcher.json").read_text())
    assert doc["scripts"][0]["topic_id"] == "lf-003"


def test_a_relative_path_from_the_factory_root_still_merges():
    """`cd ~/shorts-content-factory; ... pipeline/<ch>/<id>/03-...` is a
    proper call."""
    root, d = _batch()
    frag = _fragment_in(d)
    here = os.getcwd()
    os.chdir(root)
    try:
        code, err = _call(Path("pipeline") / "example-film" / BATCH_ID
                          / "03-content-researcher.json", frag)
    finally:
        os.chdir(here)
    assert code == 0, err
    assert (d / "03-content-researcher.json").exists()


def test_write_atomically_never_writes_into_the_root():
    try:
        mbf.write_atomically("/03-content-researcher.json", "{}\n")
    except ValueError as exc:
        assert "CF-0907" in str(exc)
    else:
        raise AssertionError("write_atomically accepted a file in /")


def test_the_skill_tells_the_operator_to_set_the_path_in_the_same_call():
    assert "CF-0907" in SKILL


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
