#!/usr/bin/env python3
"""CF-0881: `write_batch_metadata.py --repair` - the repair pass after the
frame judge rewrites the row of a video it re-rendered, in place, and nothing
else.

Pinned here:

- the repaired row replaces the old one at its position, carries `repair`
  (read off `<plan dir>/repair/record.json`, or the bare stamp), every other
  row and `refusals[]` stay byte-identical, `merge_log[-1].mode` is `repair`;
- no refusal sidecar is read in this mode (a stale one on disk changes
  nothing);
- a `--video` for a script_id that is not in videos[] (a new one, or one in
  refusals[]) is refused, exit 2, 05 untouched;
- `--refusal`, no `--video`, no 05, `--replace-all` / `--new-only` beside it:
  exit 2, nothing written.

In-process against synthetic plans in temp directories (qc_report stubbed),
as test_metadata_new_only.py.
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
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0881-runlog-")))
sys.path.insert(0, str(AGENT_ROOT / "scripts"))
import plan_refusal  # noqa: E402
import write_batch_metadata as wbm  # noqa: E402
wbm.retired_shots.default_acceptance_log = lambda: None

DEST = "05-video-editor.json"


def _plan(style="motion"):
    return {"style": style, "blocks": [],
            "duration": {"total": 12.0, "blocks": 0},
            "audio": {"duration": 12.0}, "output": {"width": 1080, "height": 1920}}


def _batch(tmp):
    b = Path(tmp) / "pipeline" / "example-film" / "b1"
    (b / "work").mkdir(parents=True)
    return b


def _video(b, sid, style="motion"):
    work = b / "work" / sid
    work.mkdir(parents=True, exist_ok=True)
    p = work / "plan.json"
    p.write_text(json.dumps(_plan(style)))
    return [sid, str(p), str(b / "videos" / f"{sid}.mp4")]


def _sidecar(b, sid, gate="pattern_ceiling", reason="refused before the render"):
    work = b / "work" / sid
    work.mkdir(parents=True, exist_ok=True)
    return plan_refusal.write(str(work / "plan.json"), sid, gate, reason)


def _call(b, *videos, repair=False, new_only=False, replace_all=False, refusals=()):
    argv = ["write_batch_metadata.py", str(b)]
    for v in videos:
        argv += ["--video"] + list(v)
    for r in refusals:
        argv += ["--refusal", str(r)]
    for flag, on in (("--repair", repair), ("--new-only", new_only),
                     ("--replace-all", replace_all)):
        if on:
            argv.append(flag)
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
    for sid in ("a-script1", "b-script1", "c-script1"):
        assert _call(b, _video(b, sid))[0] == 0
    _sidecar(b, "d-script1")
    assert _call(b)[0] == 0
    d = _doc(b)
    assert [v["script_id"] for v in d["videos"]] == ["a-script1", "b-script1", "c-script1"]
    assert [r["script_id"] for r in d["refusals"]] == ["d-script1"]
    return d


def test_row_is_rewritten_in_place_with_the_repair_record():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        before = _first_pass(b)
        v = _video(b, "b-script1", style="stills")       # the re-rendered plan
        rec = {"task": "CF-0881", "at": "2026-10-28T10:00:00Z",
               "blocks": [{"block": 4, "entry": "block-4", "target": "shot",
                           "exclude_shot": "abc:3", "kind": "thin_strip"}],
               "replaced": [{"block": 4, "before": "abc:3", "after": "abc:9"}],
               "changed_blocks": [4]}
        rp = Path(v[1]).parent / "repair" / "record.json"
        rp.parent.mkdir(parents=True)
        rp.write_text(json.dumps(rec))
        code, err = _call(b, v, repair=True)
        assert code == 0, err
        after = _doc(b)
        assert [x["script_id"] for x in after["videos"]] == \
            ["a-script1", "b-script1", "c-script1"]
        for i in (0, 2):
            assert json.dumps(after["videos"][i], sort_keys=True) == \
                json.dumps(before["videos"][i], sort_keys=True)
        row = after["videos"][1]
        assert row["style_delivered"] == "stills"
        assert row["repair"] == rec
        assert after["refusals"] == before["refusals"]
        assert after["merge_log"][-1]["mode"] == "repair"
        assert after["merge_log"][-1]["videos"] == ["b-script1"]


def test_bare_stamp_without_a_record():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _first_pass(b)
        code, err = _call(b, _video(b, "a-script1"), repair=True)
        assert code == 0, err
        r = _doc(b)["videos"][0]["repair"]
        assert r["task"] == "CF-0881" and r["at"] and r["blocks"] is None


def test_no_sidecar_is_read():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        before = _first_pass(b)
        _sidecar(b, "d-script1", gate="end_card", reason="a different story")
        _sidecar(b, "e-script1")                    # nobody's round
        _sidecar(b, "a-script1")                    # even the repaired one's
        code, err = _call(b, _video(b, "a-script1"), repair=True)
        assert code == 0, err
        after = _doc(b)
        assert after["refusals"] == before["refusals"]
        assert [x["script_id"] for x in after["videos"]] == \
            ["a-script1", "b-script1", "c-script1"]


def test_a_row_05_does_not_hold_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        _first_pass(b)
        raw = (b / DEST).read_bytes()
        for sid in ("new-script1", "d-script1"):        # new, and a refusal
            code, err = _call(b, _video(b, "a-script1"), _video(b, sid), repair=True)
            assert code == 2, err
            assert f"--video {sid}" in err and "never adds one" in err, err
            assert "nothing written (CF-0881" in err, err
            assert (b / DEST).read_bytes() == raw


def test_other_shapes_are_refused():
    with tempfile.TemporaryDirectory() as tmp:
        b = _batch(tmp)
        code, err = _call(b, _video(b, "a-script1"), repair=True)
        assert code == 2 and "there is none" in err, err
        assert not (b / DEST).exists()
        _first_pass(b)
        raw = (b / DEST).read_bytes()
        cases = [
            (dict(repair=True), "--repair with no --video"),
            (dict(repair=True, refusals=[_sidecar(b, "d-script1")]), "--refusal with --repair"),
            (dict(repair=True, new_only=True), "--new-only and --repair"),
            (dict(repair=True, replace_all=True), "--replace-all and --repair"),
        ]
        for kw, says in cases:
            vids = () if "no --video" in says or "--refusal" in says else \
                (_video(b, "a-script1"),)
            code, err = _call(b, *vids, **kw)
            assert code == 2 and says in err, (kw, err)
            assert (b / DEST).read_bytes() == raw


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
