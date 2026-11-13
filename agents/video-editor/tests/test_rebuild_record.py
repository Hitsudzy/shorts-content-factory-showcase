#!/usr/bin/env python3
"""CF-0416: a rebuild writes its own 05-video-editor.json by the same call as a
batch, and a cosmetic QC refusal is an explicit admission to the frame judge.

Batch `2026-09-27T0929Z`, mechanism L. The rebuild `2026-09-27T1757Z` had no
05 of its own, so the frame-judge stage hand-assembled one - with `channel:
"rebuilds"` - and kaijura (QC refused attempt 3/3 only on
`meme_caption_blank_blocks`) could only be judged by writing `qc.passed: true`
into it. What is pinned here:

- `write_batch_metadata.py pipeline/rebuilds/<ts> --video ...` writes the
  rebuild's own record, with the source batch's channel (read off the copied
  03) and `rebuild_of`, and `videos[].score` / `score_line` from the log;
- an ordinary batch keeps its channel and says `rebuild_of: null`;
- QC failed only on a cosmetic rule -> `judge_admitted_despite: [<rule>]`,
  `qc.passed` stays false, `qc.failed_rules` names the rule;
- QC failed on anything else as well -> no field at all; passed -> no field;
- the channel's list (`video_editor.qc_cosmetic_rules`) is read, and a rule of
  the hard list is never cosmetic whatever it says;
- the cosmetic finding is priced only once the price table carries the rule.

Plain asserts, run directly; qc_report is stubbed as in test_metadata_merge.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0416-runlog-")))
sys.path.insert(0, str(SCRIPTS))
import _score  # noqa: E402
import qc_cosmetic  # noqa: E402
import score_log  # noqa: E402
import write_batch_metadata as wbm  # noqa: E402

DEST = "05-video-editor.json"
MEME_FAIL = ("blocks showing an insert with none of our captions under it: block 6 "
             "at 35.28s - the block carries a meme insert that leaves our captions on")
CAPTION_FAIL = "caption contrast 1.2 under 3.0 at 12.0s"
BURNED_FAIL = "block 3 shows a shot with burned-in text (foreign subtitles)"
QC_PASS = {"passed": True, "failures": [], "notes": [], "measured": {}}


def _plan():
    return {"style": "motion", "blocks": [], "duration": {"total": 40.0, "blocks": 0},
            "audio": {"duration": 40.0}, "output": {"width": 1080, "height": 1920}}


def _rebuild(tmp, source_channel="example-film", source_batch="2026-09-27T0929Z",
             ts="2026-09-27T1757Z", with_source=True):
    root = Path(tmp) / "pipeline"
    b = root / "rebuilds" / ts
    (b / "work").mkdir(parents=True)
    (b / "03-content-researcher.json").write_text(json.dumps(
        {"batch_id": source_batch, "channel": source_channel, "scripts": []}))
    if with_source:
        (root / source_channel / source_batch).mkdir(parents=True)
    return b


def _video(batch_dir, sid):
    work = batch_dir / "work" / sid
    work.mkdir(parents=True, exist_ok=True)
    p = work / "plan.json"
    p.write_text(json.dumps(_plan()))
    return [sid, str(p), str(batch_dir / "videos" / f"{sid}.mp4")]


def _write(batch_dir, *videos, qc=None, extra=()):
    argv = ["write_batch_metadata.py", str(batch_dir), *extra]
    for v in videos:
        argv += ["--video"] + list(v)
    real_qc, real_argv = wbm.qc_report, sys.argv
    wbm.qc_report = lambda video, plan: json.loads(json.dumps(qc or QC_PASS))
    sys.argv = argv
    err = io.StringIO()
    try:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            wbm.main()
    finally:
        wbm.qc_report, sys.argv = real_qc, real_argv
    return json.loads((batch_dir / DEST).read_text()), err.getvalue()


def test_a_rebuild_writes_its_own_record_with_the_source_channel():
    with tempfile.TemporaryDirectory() as tmp:
        b = _rebuild(tmp)
        v = _video(b, "kaijura-minus-zero")
        # a score log beside the plan, as QC leaves it (CF-0434)
        score_log.record(v[1], score_log.STAGE_PLAN, [], script_id=v[0])
        doc, err = _write(b, v)
        assert doc["channel"] == "example-film", doc["channel"]
        assert doc["batch_id"] == "2026-09-27T1757Z"
        assert doc[wbm.REBUILD_FIELD] == {
            "channel": "example-film", "batch_id": "2026-09-27T0929Z",
            "path": "pipeline/example-film/2026-09-27T0929Z",
            "read_from": "03-content-researcher.json"}, doc[wbm.REBUILD_FIELD]
        rec = doc["videos"][0]
        assert rec["script_id"] == "kaijura-minus-zero"
        assert score_log.FIELD in rec and score_log.LINE_FIELD in rec
        assert rec[score_log.FIELD] is not None and rec[score_log.LINE_FIELD], rec[score_log.LINE_FIELD]
        assert rec["qc"]["passed"] is True and qc_cosmetic.FIELD not in rec
        # the videos retire into the source channel's registry, not a
        # `rebuilds` one (this plan names no shot, so the entry is empty)
        reg = Path(tmp) / "pipeline" / "example-film" / "retired-shots.json"
        assert reg.exists(), err
        assert json.loads(reg.read_text())["channel"] == "example-film"
        assert not (Path(tmp) / "pipeline" / "rebuilds" / "retired-shots.json").exists()


def test_a_rebuild_with_no_channel_in_its_copies_says_so():
    with tempfile.TemporaryDirectory() as tmp:
        b = _rebuild(tmp)
        (b / "03-content-researcher.json").write_text("{}")
        doc, err = _write(b, _video(b, "x"))
        assert doc["channel"] == "rebuilds"
        assert doc[wbm.REBUILD_FIELD]["channel"] is None
        assert "is a rebuild, but neither" in err, err
        # --channel wins
        doc, _ = _write(b, _video(b, "x"), extra=("--channel", "example-film"))
        assert doc["channel"] == "example-film"


def test_an_ordinary_batch_is_no_rebuild():
    with tempfile.TemporaryDirectory() as tmp:
        b = Path(tmp) / "pipeline" / "example-film" / "b1"
        (b / "work").mkdir(parents=True)
        doc, _ = _write(b, _video(b, "s1"))
        assert doc["channel"] == "example-film"
        assert doc[wbm.REBUILD_FIELD] is None


def test_a_cosmetic_refusal_is_admitted_and_qc_stays_honest():
    with tempfile.TemporaryDirectory() as tmp:
        b = _rebuild(tmp)
        qc = {"passed": False, "failures": [MEME_FAIL], "notes": [],
              "measured": {"meme_caption_blank_blocks": [{"index": 6, "at": 35.28, "fault": True}]}}
        doc, err = _write(b, _video(b, "kaijura-minus-zero"), qc=qc)
        rec = doc["videos"][0]
        assert rec["qc"]["passed"] is False
        assert rec["qc"][qc_cosmetic.RULES_FIELD] == ["meme_caption_blank_blocks"]
        assert rec["qc"]["cosmetic_rules"] == ["meme_caption_blank_blocks"]
        assert rec[qc_cosmetic.FIELD] == ["meme_caption_blank_blocks"]
        assert "admitted to the frame judge" in err, err


def test_a_refusal_that_is_not_only_cosmetic_has_no_field():
    with tempfile.TemporaryDirectory() as tmp:
        b = _rebuild(tmp)
        for fails in ([MEME_FAIL, CAPTION_FAIL], [CAPTION_FAIL], [BURNED_FAIL],
                      ["qc did not run"]):
            qc = {"passed": False, "failures": fails, "notes": [], "measured": {}}
            doc, err = _write(b, _video(b, "s1"), qc=qc)
            rec = doc["videos"][0]
            assert qc_cosmetic.FIELD not in rec, (fails, rec.get(qc_cosmetic.FIELD))
            assert rec["qc"]["passed"] is False
            assert "QC FAILED: s1" in err, err


def test_the_channel_list_is_read_and_the_hard_list_is_never_cosmetic():
    with tempfile.TemporaryDirectory() as tmp:
        ch = Path(tmp) / "chan.json"
        ch.write_text(json.dumps({"video_editor": {
            "qc_cosmetic_rules": ["caption", "burned_text", "meme_caption_blank_blocks"]}}))
        c = qc_cosmetic.load(str(ch))
        assert c["rules"] == ["caption", "meme_caption_blank_blocks"], c
        assert c["dropped"] == ["burned_text"]
        assert c["source"].endswith("#video_editor.qc_cosmetic_rules")
        fail = {"passed": False, "failures": [MEME_FAIL, CAPTION_FAIL]}
        assert qc_cosmetic.admitted_despite(fail, c) == ["caption", "meme_caption_blank_blocks"]
        assert qc_cosmetic.admitted_despite(
            {"passed": False, "failures": [BURNED_FAIL]}, c) is None
        # no file / no key -> the default list
        d = qc_cosmetic.load(str(Path(tmp) / "missing.json"))
        assert d["rules"] == list(qc_cosmetic.DEFAULT_RULES) and d["source"] == "default"
        assert qc_cosmetic.admitted_despite(fail, d) is None
        assert qc_cosmetic.admitted_despite(QC_PASS, d) is None


def test_the_cosmetic_finding_is_priced_only_when_the_table_has_it():
    qc = {"passed": False, "failures": [MEME_FAIL],
          "measured": {"meme_caption_blank_blocks": [{"index": 6, "at": 35.28, "fault": True}]}}
    plan = {"blocks": [{"start": 0.0}] * 8}
    real = _score._RULES
    try:
        _score._RULES = frozenset()
        assert not [f for f in score_log.qc_findings(qc, plan)
                    if f["rule"] == score_log.RULE_MEME_CAPTION_BLANK]
        _score._RULES = frozenset({score_log.RULE_MEME_CAPTION_BLANK})
        got = [f for f in score_log.qc_findings(qc, plan)
               if f["rule"] == score_log.RULE_MEME_CAPTION_BLANK]
        assert len(got) == 1, got
    finally:
        _score._RULES = real


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
