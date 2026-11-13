#!/usr/bin/env python3
"""CF-0802: `write_batch_metadata.py --new-only` - the reserve round after the
frame judge adds entries to 05 and never rewrites one.

Pinned here:

- a new script_id is merged in by script_id; every entry the first pass
  wrote (videos[] and refusals[]) stays byte-identical and in place, and
  `merge_log[-1].mode` is `new-only`;
- a `--video` for a script_id 05 holds in videos[] or refusals[] is refused,
  exit 2, and the file is not touched (byte-identical);
- a `--refusal` for such an id is refused the same way;
- a first-pass script's refusal sidecar is not re-read in this mode (its
  entry in 05 stays as written), while a new script's sidecar is merged;
- no 05 (no first pass), `--replace-all` beside `--new-only`, and a call with
  nothing new to add, are exit 2;
- the default mode still replaces an existing record (CF-0030 unchanged).

In-process against synthetic plans in temp directories (qc_report stubbed),
as test_metadata_merge.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482
from _tmproot import tmp_root  # noqa: E402 - CF-0489
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0802-runlog-")))
sys.path.insert(0, str(AGENT_ROOT / "scripts"))
import plan_refusal  # noqa: E402
import write_batch_metadata as wbm  # noqa: E402
wbm.retired_shots.default_acceptance_log = lambda: None

DEST = "05-video-editor.json"


def _plan():
    return {"style": "motion", "blocks": [],
            "duration": {"total": 12.0, "blocks": 0},
            "audio": {"duration": 12.0}, "output": {"width": 1080, "height": 1920}}


def _batch(tmp):
    b = Path(tmp) / "pipeline" / "example-film" / "b1"
    (b / "work").mkdir(parents=True)
    return b


def _video(b, sid):
    work = b / "work" / sid
    work.mkdir(parents=True, exist_ok=True)
    p = work / "plan.json"
    p.write_text(json.dumps(_plan()))
    return [sid, str(p), str(b / "videos" / f"{sid}.mp4")]


def _sidecar(b, sid, gate="pattern_ceiling", reason="refused before the render"):
    work = b / "work" / sid
    work.mkdir(parents=True, exist_ok=True)
    return plan_refusal.write(str(work / "plan.json"), sid, gate, reason)


def _call(b, *videos, new_only=False, replace_all=False, refusals=()):
    """(exit code, stderr). 0 when main() returned."""
    argv = ["write_batch_metadata.py", str(b)]
    for v in videos:
        argv += ["--video"] + list(v)
    for r in refusals:
        argv += ["--refusal", str(r)]
    if new_only:
        argv.append("--new-only")
    if replace_all:
        argv.append("--replace-all")
    out, err = io.StringIO(), io.StringIO()
    real_qc, real_argv = wbm.qc_report, sys.argv
    wbm.qc_report = lambda video, plan: {"passed": True, "failures": [], "notes": [],
                                         "measured": {}}
    sys.argv = argv
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            wbm.main()
    except SystemExit as e:
        code = e.code
    finally:
        wbm.qc_report, sys.argv = real_qc, real_argv
    return code, err.getvalue()


def _doc(b):
    return json.loads((b / DEST).read_text())


def _first_pass(b):
    """05 as the first pass leaves it: two videos and one refusal."""
    assert _call(b, _video(b, "a-script1"))[0] == 0
    assert _call(b, _video(b, "b-script1"))[0] == 0
    _sidecar(b, "c-script1")
    assert _call(b)[0] == 0
    d = _doc(b)
    assert [v["script_id"] for v in d["videos"]] == ["a-script1", "b-script1"]
    assert [r["script_id"] for r in d["refusals"]] == ["c-script1"]
    return d


def test_new_id_is_merged_and_the_first_pass_untouched():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        before = _first_pass(b)
        code, err = _call(b, _video(b, "r-script1"), new_only=True)
        assert code == 0, err
        after = _doc(b)
        assert [v["script_id"] for v in after["videos"]] == \
            ["a-script1", "b-script1", "r-script1"]
        for i in range(2):
            assert json.dumps(after["videos"][i], sort_keys=True) == \
                json.dumps(before["videos"][i], sort_keys=True)
        assert after["refusals"] == before["refusals"]
        assert after["merge_log"][-1]["mode"] == "new-only"
        assert after["merge_log"][-1]["videos"] == ["r-script1"]


def test_video_for_an_id_in_05_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _first_pass(b)
        raw = (b / DEST).read_bytes()
        for sid in ("a-script1", "c-script1"):          # a video, a refusal
            code, err = _call(b, _video(b, "r-script1"), _video(b, sid), new_only=True)
            assert code == 2, err
            assert f"--video {sid}" in err and "first pass is final" in err, err
            assert "nothing written" in err, err
            assert (b / DEST).read_bytes() == raw, "a refused call touched 05"


def test_refusal_for_an_id_in_05_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _first_pass(b)
        raw = (b / DEST).read_bytes()
        side = _sidecar(b, "a-script1")
        code, err = _call(b, new_only=True, refusals=[side])
        assert code == 2 and "--refusal" in err and "a-script1" in err, err
        assert (b / DEST).read_bytes() == raw


def test_first_pass_sidecars_are_not_reread():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        before = _first_pass(b)
        # the first pass's sidecar changed on disk since 05 was written
        _sidecar(b, "c-script1", gate="end_card", reason="a different story")
        _sidecar(b, "r-script1")                         # the round's own refusal
        code, err = _call(b, new_only=True)
        assert code == 0, err
        after = _doc(b)
        assert after["refusals"][0] == before["refusals"][0]
        assert [r["script_id"] for r in after["refusals"]] == ["c-script1", "r-script1"]
        assert after["videos"] == before["videos"]


def test_nothing_new_is_refused_and_05_untouched():
    """Only first-pass sidecars on disk: nothing to add, exit 2, 05 as it was."""
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _first_pass(b)
        raw = (b / DEST).read_bytes()
        code, err = _call(b, new_only=True)
        assert code == 2 and "nothing to add (CF-0802)" in err, err
        assert (b / DEST).read_bytes() == raw


def test_no_05_and_replace_all_are_refused():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        code, err = _call(b, _video(b, "r-script1"), new_only=True)
        assert code == 2 and "no first pass" not in err and "there is none" in err, err
        assert not (b / DEST).exists()
        _first_pass(b)
        raw = (b / DEST).read_bytes()
        code, err = _call(b, _video(b, "r-script1"), new_only=True, replace_all=True)
        assert code == 2 and "--replace-all and --new-only" in err, err
        assert (b / DEST).read_bytes() == raw


def test_default_mode_still_replaces():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _first_pass(b)
        code, err = _call(b, _video(b, "a-script1"))
        assert code == 0, err
        d = _doc(b)
        assert [v["script_id"] for v in d["videos"]] == ["a-script1", "b-script1"]
        assert d["merge_log"][-1]["mode"] == "merge"
        assert "1 replaced" in err, err


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
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
