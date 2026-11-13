#!/usr/bin/env python3
"""CF-0434: every video carries its score line - in `05`, in the run summary
and in the message it comes to the user with (DoD 1.4.7 item 2).

`shared/runlog/scores.py` reads the line the last stage that scored a video
wrote (the frame judge's `06`, else the Editor's `05`; the line of a video the
score stopped at 6b or at the Editor from `03` `skipped[]` / `05`
`refusals[]`), and the summary and `runlog acceptance --ask` print it. What is
tested is the reading and the printing: that the line after the judge wins over
the line after QC, that a video stopped under N is named with its stage, and
that a batch before CF-0434 prints nothing new.
"""
import json
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
sys.path.insert(0, str(ROOT / "tests"))

from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("scores-test-")
os.environ.pop("RUNLOG_BATCH", None)

import funnel     # noqa: E402
import scores     # noqa: E402
import summary    # noqa: E402
import acceptance  # noqa: E402
import runlog     # noqa: E402

LINE_QC = "B · 80 — −20 зависший кадр (1 блок)"
LINE_JUDGE = "C · 70 — −20 зависший кадр (1 блок), −10 судья: 1 contradicts"
_n = [0]


def batch(judge=True, scored=True):
    _n[0] += 1
    b = TMP / f"batch-{_n[0]}"
    b.mkdir()
    sc = (lambda line, pts: {"score_line": line, "score": {"score": pts, "tier": line[0],
                                                           "threshold": 60}}
          ) if scored else (lambda line, pts: {})
    ve = {"batch_id": "B", "channel": "example-film", "videos": [
        {"script_id": "a-s1", "output_path": "/x/videos/alpha.mp4", "qc": {"passed": True},
         **sc(LINE_QC, 80)},
        {"script_id": "b-s1", "output_path": "/x/videos/beta.mp4", "qc": {"passed": True},
         **sc("A · 88 — −12 судья: 1 foreign", 88)},
        {"script_id": "c-s1", "output_path": "/x/videos/gamma.mp4", "qc": {"passed": False},
         **sc("S · 97 — −3 нет подложки", 97)}],
        "refusals": [
            {"script_id": "d-s1", "reason_code": "held_back", "gate": "score_below_threshold",
             "reason": "SCORE UNDER THE THRESHOLD after qc", "numbers": {"stage": "qc"},
             **({"score_line": "F · 40 — −40 зависший кадр (1 блок, хук)"} if scored else {})},
            {"script_id": "e-s1", "reason_code": "pool_too_thin", "reason": "no picture"}]}
    (b / "05-video-editor.json").write_text(json.dumps(ve, ensure_ascii=False))
    (b / "03-content-researcher.json").write_text(json.dumps({"batch_id": "B", "scripts": [],
        "skipped": [{"topic_id": "t6", "script_id": "f-s1",
                     "reason_code": funnel.SCORE_BELOW_THRESHOLD,
                     "gate": "score_below_threshold", "tier": "F",
                     **({"score_line": "F · 52 — −41 кроп режет героя (1 случай)"}
                        if scored else {}),
                     "reason": "under N after 3 rounds"},
                    {"topic_id": "t7", "reason_code": "thin_scene", "reason": "x"}]},
        ensure_ascii=False))
    if judge:
        (b / funnel.FRAME_JUDGE_FILE).write_text(json.dumps({
            "schema": funnel.FRAME_JUDGE_SCHEMA, "videos": [
                {"script_id": "a-s1", "slug": "alpha", "gate": funnel.GATE_PASS,
                 "reason_code": None, "score_line": LINE_JUDGE,
                 "score": {"score": 70, "tier": "C", "threshold": 60}},
                {"script_id": "b-s1", "slug": "beta", "gate": funnel.GATE_REJECT,
                 "reason_code": funnel.SCORE_BELOW_THRESHOLD,
                 "score_line": "F · 58 — −30 судья: 3 contradicts, −12 ...",
                 "score": {"score": 58, "tier": "F", "threshold": 60}}]},
            ensure_ascii=False))
    return b


def by_slug(rows):
    return {r["slug"]: r for r in rows}


def test_the_line_after_the_judge_wins_and_a_video_stopped_under_n_names_its_stage():
    rows = by_slug(scores.collect(batch()))
    assert set(rows) == {"alpha", "beta", "gamma", "d-s1", "f-s1"}, rows.keys()
    assert rows["alpha"]["score_line"] == LINE_JUDGE and rows["alpha"]["state"] == scores.READY
    assert rows["alpha"]["source"] == funnel.FRAME_JUDGE_FILE and rows["alpha"]["score"] == 70
    assert rows["beta"]["state"] == scores.STOPPED and rows["beta"]["stage"] == "judge"
    assert rows["gamma"]["state"] == scores.NOT_READY          # QC failed
    assert rows["d-s1"]["state"] == scores.STOPPED and rows["d-s1"]["stage"] == "qc"
    assert rows["d-s1"]["code"] == funnel.SCORE_BELOW_THRESHOLD   # the old spelling, read as it
    assert rows["f-s1"]["state"] == scores.STOPPED and rows["f-s1"]["stage"] == "6b"
    assert rows["f-s1"]["score_line"].startswith("F · 52")


def test_without_a_judge_the_line_is_the_editors():
    rows = by_slug(scores.collect(batch(judge=False)))
    assert rows["alpha"]["score_line"] == LINE_QC and rows["alpha"]["state"] == scores.READY
    assert rows["beta"]["state"] == scores.READY
    assert scores.line_of(batch(judge=False), "alpha") == LINE_QC
    assert scores.line_of(batch(judge=False), "nobody") is None


def test_the_run_summary_prints_one_line_per_video_under_its_headlines():
    b = batch()
    data = summary.compute(events=[{"ts": "2026-09-29T10:00:00Z", "kind": "marker",
                                    "status": "batch-start", "batch": "B"}])
    data["scores"] = summary.scores_of(b)
    assert len(data["scores"]) == 5
    text = summary.render(data=data)
    head = text.split("# RUN_SUMMARY")[0]
    assert "**score (CF-0434)**: 1 ready, 3 stopped under N, 1 other" in head, head
    assert f"- `alpha`: {LINE_JUDGE}" in head, head
    assert "- `f-s1` (stopped at 6b): F · 52" in head and "- `d-s1` (stopped at qc)" in head
    assert "- `beta` (stopped at judge): F · 58" in head
    assert head.index("`alpha`") < head.index("`beta`"), "ready first"


def test_a_batch_before_cf_0434_prints_no_score_block_and_nothing_breaks():
    b = batch(judge=False, scored=False)
    assert scores.lines(scores.collect(b)) == []
    assert summary.scores_of(None) == [] and summary.scores_of(TMP / "nowhere") == []
    rows = by_slug(scores.collect(b))
    assert rows["alpha"]["score_line"] == scores.NO_LINE


def test_the_message_the_video_comes_to_the_user_with_carries_the_line():
    b = batch()
    lines = acceptance.question("example-film", "B", ["alpha", "beta", "delta"], batch_dir=b)
    assert any(l.startswith("- `alpha.mp4` — ") and LINE_JUDGE in l for l in lines), lines
    assert any("`delta.mp4`" in l and "·" not in l for l in lines), lines
    assert not acceptance.is_numbered(lines), lines
    plain = acceptance.question("example-film", "B", ["alpha"])      # no batch on disk
    assert plain[1] == "- `alpha.mp4` — принят или отклонён?", plain


def test_runlog_scores_is_a_command():
    b = batch()
    assert runlog.main(["scores", "--batch", str(b)]) == 0
    assert scores.main(["--batch", str(b), "--json"]) == 0


if __name__ == "__main__":
    import traceback
    tests = [(k, x) for k, x in sorted(globals().items())
             if k.startswith("test_") and callable(x)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                              # noqa: BLE001
            failed += 1
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
