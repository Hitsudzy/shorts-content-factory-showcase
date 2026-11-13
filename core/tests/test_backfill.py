#!/usr/bin/env python3
"""CF-0111: `runlog backfill` (shared/runlog/backfill.py) - a hand-written
RUN_LOG.txt becomes synthetic events, a summary and a runs-table row marked
`manual-runlog`.

Runs in seconds on two small synthetic logs written here, one per hand-written
format (08-31: no BATCH_START, MSK throughout, `video<N>-<slug>-<step>`; 09-03:
BATCH_START in MSK, the rest UTC, `video-<slug>-<step>-attempt<K>` plus video-
level lines) and on a transcript-marker fixture built in a temp dir. FACTORY_ROOT,
RUNLOG_STATE_DIR, RUNLOG_TRANSCRIPTS and RUNLOG_PROJECTS_DIR all point into the
temp dir: nothing outside the repo is read or written, and the repo's own
pipeline/runs.jsonl / RUNS.md are never touched (run_tests.py checks that).
"""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))

from _tmproot import tmp_root   # noqa: E402  (CF-0339: stops the samplers, removes the tree)

TMP = tmp_root("backfill-test-")
FAKE_ROOT = TMP / "root"
(FAKE_ROOT / "pipeline").mkdir(parents=True)
PROJ = TMP / "projects"
PROJ.mkdir()
os.environ["FACTORY_ROOT"] = str(FAKE_ROOT)
os.environ["RUNLOG_STATE_DIR"] = str(TMP / "state")
os.environ["RUNLOG_PROJECTS_DIR"] = str(PROJ)
os.environ["RUNLOG_TRANSCRIPTS"] = str(PROJ)
os.environ.pop("RUNLOG_BATCH", None)
os.environ.pop("RUNLOG_PARENT", None)

import runlog  # noqa: E402
import backfill  # noqa: E402
import gaps  # noqa: E402
import runs_table  # noqa: E402

SID = "aaaaaaaa-0000-0000-0000-000000000001"

# format A (08-31): MSK throughout, no BATCH_START/BATCH_DONE, video<N>-<slug>-<step>,
# a FINAL SUMMARY prose block. Batch id 2026-08-31T2155Z = 00:55 MSK on 09-01.
LOG_A = """[2026-09-01 00:56:00] STAGE_START trend-hunter
[2026-09-01 01:01:00] STAGE_DONE trend-hunter 3 topics
[2026-09-01 01:01:00] STAGE_START compliance-1
[2026-09-01 01:01:30] STAGE_DONE compliance-1 3/3 clear
[2026-09-01 01:01:30] STAGE_START footage-indexer
[2026-09-01 01:31:30] STAGE_DONE footage-indexer 6/6 fetched
[2026-09-01 01:35:00] STAGE_DONE footage-indexer-descriptions 201 shots described
[2026-09-01 01:35:00] STAGE_START video-editor
[2026-09-01 01:36:00] STAGE_START video1-wren-hollow-tts
[2026-09-01 01:36:30] STAGE_DONE video1-wren-hollow-tts+align 149 words
[2026-09-01 01:37:00] STAGE_START video1-wren-hollow-render
[2026-09-01 01:42:00] STAGE_DONE video1-wren-hollow-render rendered wren-hollow-lockhart.mp4
[2026-09-01 01:42:00] STAGE_START video1-wren-hollow-qc
[2026-09-01 01:43:00] STAGE_DONE video1-wren-hollow-qc FAILED frozen clip
[2026-09-01 01:43:00] STAGE_START video1-wren-hollow-resolve-anchors-attempt2
[2026-09-01 03:00:00] STAGE_DONE video1-wren-hollow-resolve-anchors-attempt2 12 anchors
[2026-09-01 03:00:10] STAGE_START video1-wren-hollow-degrade-to-stills
[2026-09-01 03:01:00] STAGE_DONE video1-wren-hollow-degrade-to-stills stills storyboard
[2026-09-01 03:01:00] STAGE_START video1-wren-hollow-render-stills
[2026-09-01 03:05:00] STAGE_DONE video1-wren-hollow-render-stills rendered
[2026-09-01 03:05:00] STAGE_START video1-wren-hollow-qc-stills
[2026-09-01 03:05:30] STAGE_DONE video1-wren-hollow-qc-stills PASSED clean
[2026-09-01 03:08:00] STAGE_DONE metadata-assembly wrote 05-video-editor.json

=== FINAL SUMMARY: batch 2026-08-31T2155Z ===
Total wall-clock 2h12m; Gap 1, session rate-limit interruption: 1h 05m (01:50 -> 02:55).
"""

# format B (09-03): BATCH_START in MSK (23:38 MSK = 20:38 UTC), the rest UTC,
# video-<slug>-<step>-attempt<K>, video-level START/DONE lines, BATCH_DONE.
LOG_B = """[2026-09-03 23:38:00] BATCH_START 2026-09-03T2037Z channel=legacy-film — full run (1.2)
[2026-09-03 20:38:30] STAGE_START trend-hunter
[2026-09-03 20:45:00] STAGE_DONE trend-hunter 8 topics
[2026-09-03 20:50:00] STAGE_START footage-indexer
[2026-09-04 00:09:00] STAGE_DONE footage-indexer 23/24 sources
[2026-09-04 00:09:00] STAGE_START content-researcher
[2026-09-04 00:27:00] STAGE_DONE content-researcher 2 scripted
[2026-09-04 00:30:00] STAGE_START video-editor 2 scripts
[2026-09-04 00:31:00] STAGE_START video-ink-teaser-cards script lf-2026-09-03-004-script1
[2026-09-04 00:45:00] STAGE_DONE video-ink-teaser-cards-tts+align 165 words
[2026-09-04 00:45:00] STAGE_DONE video-ink-teaser-cards-resolve-anchors-attempt1 15 anchors, 3 below floor
[2026-09-04 00:47:00] STAGE_DONE video-ink-teaser-cards-resolve-anchors-attempt2 15 anchors
[2026-09-04 00:48:00] STAGE_DONE video-ink-teaser-cards-render-plan 15 blocks
[2026-09-04 00:53:00] STAGE_DONE video-ink-teaser-cards-render rendered ink-teaser-cards.mp4
[2026-09-04 00:53:00] STAGE_DONE video-ink-teaser-cards-qc PASSED clean
[2026-09-04 00:54:00] STAGE_DONE video-ink-teaser-cards-metadata wrote
[2026-09-04 00:54:00] STAGE_DONE video-ink-teaser-cards style motion
[2026-09-04 00:56:00] STAGE_START video-clooney-venice-lion script lf-2026-09-03-003-script1
[2026-09-04 04:56:00] STAGE_DONE video-clooney-venice-lion-tts+align 188 words
[2026-09-04 05:02:00] STAGE_DONE video-clooney-venice-lion-render-plan 12 blocks
[2026-09-04 05:08:00] STAGE_DONE video-clooney-venice-lion-render rendered
[2026-09-04 05:09:00] STAGE_DONE video-clooney-venice-lion-qc-attempt1 FAILED - frozen_clip_block
[2026-09-04 05:10:00] STAGE_DONE video-clooney-venice-lion-render-plan-attempt2 block 4 re-cut
[2026-09-04 05:11:00] STAGE_DONE video-clooney-venice-lion-render-attempt2 KILLED by me mid-render
[2026-09-04 05:18:00] STAGE_DONE video-clooney-venice-lion-render-attempt3 rendered
[2026-09-04 05:19:00] STAGE_DONE video-clooney-venice-lion-qc-attempt2 PASSED clean
[2026-09-04 05:20:00] STAGE_DONE video-clooney-venice-lion-metadata wrote
[2026-09-04 05:20:00] STAGE_DONE video-clooney-venice-lion style motion
[2026-09-04 05:21:00] STAGE_DONE video-editor 2/2 rendered
[2026-09-04 05:21:00] BATCH_DONE 2026-09-03T2037Z 2 videos
"""


def _batch(name, log, videos):
    bd = TMP / "batches" / "legacy-film" / name
    bd.mkdir(parents=True, exist_ok=True)
    (bd / "RUN_LOG.txt").write_text(log, encoding="utf-8")
    (bd / "05-video-editor.json").write_text(json.dumps({"batch_id": name, "videos": [
        {"script_id": f"s{i}", "output_path": f"/x/{name}/videos/{v}.mp4",
         "duration": {"actual": 40.0 + i}, "style_delivered": "motion", "degradation": [], "qc": {"passed": True}}
        for i, v in enumerate(videos)]}), encoding="utf-8")
    return bd


def _marker_file(sid, stamps):
    p = PROJ / f"{sid}.jsonl"
    p.write_text("".join(json.dumps({
        "type": "user", "sessionId": sid, "timestamp": ts,
        "message": {"role": "user", "content": gaps.MARKER_TEXT}}) + "\n" for ts in stamps), encoding="utf-8")
    return p


def _by(evs, **kw):
    return [e for e in evs if all(e.get(k) == v for k, v in kw.items())]


# --------------------------------------------------------------------------

def test_parse_keeps_marker_lines_only_and_offset_detection_picks_msk_or_utc():
    recs = backfill.parse(LOG_A)
    assert len(recs) == 23, len(recs)                      # the FINAL SUMMARY prose is skipped
    assert recs[0]["kind"] == "STAGE_START" and recs[0]["name"] == "trend-hunter"
    assert recs[-1]["name"] == "metadata-assembly" and recs[-1]["text"].startswith("wrote")
    bt = backfill.batch_time("2026-08-31T2155Z")
    assert bt.strftime("%Y-%m-%d %H:%M") == "2026-08-31 21:55"
    assert backfill.detect_offset(recs[0]["local"], bt) == 3           # 00:56 MSK = 21:56 UTC, 1 min after
    bt2 = backfill.batch_time("2026-09-03T2037Z")
    rb = backfill.parse(LOG_B)
    assert backfill.detect_offset(rb[0]["local"], bt2) == 3            # 23:38 MSK
    assert backfill.detect_offset(rb[1]["local"], bt2) == 0            # 20:38 UTC
    assert backfill.batch_time("not-a-batch") is None


def test_format_a_msk_throughout_shape_stages_pairs_stills_and_slug_canonicalisation():
    bd = _batch("2026-08-31T2155Z", LOG_A, ["wren-hollow-lockhart"])
    evs = backfill.events(bd)
    for e in evs:
        assert e["source"] == "manual-runlog" and e["precision"] == "minute", e
        assert e["ts"].endswith("Z") and e["machine"], e
    bs = _by(evs, status="batch-start")
    assert len(bs) == 1 and bs[0]["synthesized"]                         # no BATCH_START line
    assert bs[0]["ts"] == "2026-08-31T21:56:00.000Z", bs[0]["ts"]         # MSK -> UTC
    h = bs[0]["header"]
    assert h["batch"] == "legacy-film/2026-08-31T2155Z" and h["source"] == "manual-runlog"
    assert h["timezones"] == {"first_line": "MSK", "rest": "MSK"}, h["timezones"]
    assert h["counts"]["videos"] == 1 and h["row_note"] == backfill.ROW_NOTE
    assert _by(evs, status="batch-done")[0]["ts"] == "2026-09-01T00:08:00.000Z"
    stages = [(e["stage"], e["status"]) for e in evs if e["kind"] == "marker" and e["stage"]]
    assert ("compliance-checker", "stage-start") in stages               # compliance-1 mapped
    assert ("footage-indexer-descriptions", "stage-start") in stages     # synthesized start
    assert ("metadata-assembly", "stage-done") in stages
    assert ("video-editor", "stage-done") in stages                      # closed at the last line
    scripts = [e for e in evs if e["kind"] == "script"]
    assert all(e["video"] == "wren-hollow-lockhart" for e in scripts), {e["video"] for e in scripts}
    tts = _by(scripts, step="tts+align", status="done")
    assert len(tts) == 1 and tts[0]["duration_s"] == 30.0 and tts[0].get("start_from") is None
    assert _by(scripts, step="tts+align", status="start")[0]["start_from"] == "START line of tts"
    assert _by(scripts, step="qc", status="failed")[0]["attempt"] == 1
    assert _by(scripts, step="resolve", status="done")[0]["attempt"] == 2
    assert _by(scripts, step="plan", status="done")[0]["attempt"] == 1   # degrade-to-stills = plan
    assert _by(scripts, step="render", status="done")[-1]["attempt"] == 2  # render-stills = next render
    assert _by(scripts, step="qc", status="done")[0]["attempt"] == 2      # qc-stills
    ids = {e["id"] for e in scripts}
    for i in ids:
        assert len(_by(scripts, id=i)) == 2, i                           # every script is a start + end pair
    meta = _by(evs, kind="note", status="video-meta")
    assert len(meta) == 1 and meta[0]["params"]["duration_s"] == 40.0


def test_format_b_first_line_msk_rest_utc_video_level_lines_and_inferred_starts():
    bd = _batch("2026-09-03T2037Z", LOG_B, ["ink-teaser-cards", "clooney-venice-lion"])
    evs = backfill.events(bd, sessions=[SID])
    bs = _by(evs, status="batch-start")[0]
    assert bs["ts"] == "2026-09-03T20:38:00.000Z" and "synthesized" not in bs
    assert bs["header"]["timezones"] == {"first_line": "MSK", "rest": "UTC"}
    assert bs["header"]["version"] == "1.2" and bs["header"]["sessions"] == [SID]
    assert _by(evs, status="batch-done")[0]["ts"] == "2026-09-04T05:21:00.000Z"
    notes = _by(evs, kind="marker", status="note")
    assert {n["video"] for n in notes} == {"ink-teaser-cards", "clooney-venice-lion"}
    # a DONE without START: start inferred from the previous line of the same video
    ink_tts = _by(evs, video="ink-teaser-cards", step="tts+align")
    assert len(ink_tts) == 2 and ink_tts[0]["status"] == "start"
    assert ink_tts[0]["ts"] == "2026-09-04T00:31:00.000Z" and ink_tts[1]["duration_s"] == 840.0
    # attempt numbers from the line, plan without a suffix = attempt 1
    r = _by(evs, video="ink-teaser-cards", step="resolve", status="done")
    assert [e["attempt"] for e in r] == [1, 2]
    # 4 hours back from the previous line: not believed, an instant with no start event
    ct = _by(evs, video="clooney-venice-lion", step="tts+align")
    assert len(ct) == 1 and ct[0]["duration_s"] is None and "more than" in ct[0]["start_inferred"]
    assert _by(evs, video="clooney-venice-lion", step="render", status="failed")[0]["attempt"] == 2  # KILLED
    assert [e["attempt"] for e in _by(evs, video="clooney-venice-lion", step="qc")
            if e["status"] != "start"] == [1, 2]
    order = [e["status"] for e in evs]
    assert order[0] == "batch-start" and order[-1] == "batch-done"
    assert evs == sorted(evs, key=lambda e: e["ts"])


def test_gaps_from_a_marker_fixture_limit_inside_stage_and_inside_pair():
    _marker_file(SID, ["2026-09-04T00:01:00.000Z", "2026-09-04T04:50:00.000Z"])
    bd = _batch("2026-09-03T2037Z", LOG_B, ["ink-teaser-cards", "clooney-venice-lion"])
    res = backfill.run(bd, sessions=[SID], usage=False, table=False)
    g = {(x["start"], x["cause"]): x for x in res["gaps"]}
    idx = g[("2026-09-03T20:50:00.000Z", "limit")]                     # the indexer's silence: marker inside
    assert idx["evidence"]["markers"][0]["session_id"] == SID and "inside_stage" not in idx
    cr = g[("2026-09-04T00:09:00.000Z", "unknown")]                    # content-researcher: 18 min, no evidence
    assert cr["inside_stage"] == "content-researcher" and "no finer lines" in cr["note"]
    ve = g[("2026-09-04T00:56:00.000Z", "limit")]                      # 4 h before clooney's first line
    assert ve["evidence"]["markers"][0]["ts"] == "2026-09-04T04:50:00.000Z"
    assert len(res["gaps"]) == 3, [x["start"] for x in res["gaps"]]
    assert len(res["markers"]) == 2
    # format A: the marker falls inside video1's resolve attempt 2 START..DONE pair (1h17m)
    _marker_file(SID, ["2026-08-31T23:55:00.000Z"])
    bd = _batch("2026-08-31T2155Z", LOG_A, ["wren-hollow-lockhart"])
    res = backfill.run(bd, sessions=[SID], usage=False, table=False)
    pair = [x for x in res["gaps"] if x.get("inside_pair")]
    assert len(pair) == 1 and pair[0]["cause"] == "limit", res["gaps"]
    assert pair[0]["start"] == "2026-08-31T22:43:00.000Z" and pair[0]["end"] == "2026-09-01T00:00:00.000Z"
    assert "resolve attempt 2" in pair[0]["inside_pair"]
    other = [x for x in res["gaps"] if not x.get("inside_pair")]
    assert len(other) == 1 and other[0]["inside_stage"] == "footage-indexer" and other[0]["seconds"] == 1800.0
    recorded = [e for e in runlog.read_events(res["out"]) if e["kind"] == "gap"]
    assert len(recorded) == 2


def test_run_writes_out_dir_summary_and_a_marked_row_and_leaves_the_batch_alone():
    _marker_file(SID, ["2026-09-04T00:01:00.000Z"])
    bd = _batch("2026-09-03T2037Z", LOG_B, ["ink-teaser-cards", "clooney-venice-lion"])
    before = sorted(p.name for p in bd.iterdir())
    res = backfill.run(bd, sessions=[SID], usage=False, root=FAKE_ROOT)
    assert sorted(p.name for p in bd.iterdir()) == before             # the batch is read only
    assert res["out"] == FAKE_ROOT / "pipeline" / "backfill" / "2026-09-03T2037Z"
    assert (res["out"] / "RUN_EVENTS.jsonl").is_file() and (res["out"] / "RUN_SUMMARY.md").is_file()
    row = res["row"]
    assert row["batch"] == "legacy-film/2026-09-03T2037Z" and row["channel"] == "legacy-film"
    assert row["id"] == "2026-09-03T2037Z" and row["videos"] == 2 and row["version"] == "1.2"
    assert row["accounting"] == "manual-runlog"
    assert row["note"] == "ручной лог, низкая точность; токенов нет", row["note"]
    assert row["wall_s"] == 31380.0 and row["gaps"] == {"limit": 1, "unknown": 2}, row["gaps"]
    assert row["indexer_s"] == 11940.0 and row["tokens_total"] is None
    rows = runs_table.read_rows(FAKE_ROOT)
    assert [r["batch"] for r in rows] == ["legacy-film/2026-09-03T2037Z"]
    md = (FAKE_ROOT / "pipeline" / "RUNS.md").read_text(encoding="utf-8")
    assert "| note |" in md and "| manual-runlog | ручной лог, низкая точность; токенов нет |" in md
    assert "`manual-runlog`" in md                                     # the column key explains the mark
    assert not (FAKE_ROOT / "pipeline" / "RUNS.notebook.md").exists()        # CF-0499
    summ = (res["out"] / "RUN_SUMMARY.md").read_text(encoding="utf-8")
    assert summ.startswith("GAPS: 3 (limit 1 =") and "| clooney-venice-lion |" in summ
    # an instrumented row keeps note empty and its own accounting
    fake = dict(row, batch="legacy-film/2026-09-05T0000Z", accounting="complete", note=None,
                started="2026-09-05T00:00:00.000Z")
    runs_table.append(fake, FAKE_ROOT)
    md = (FAKE_ROOT / "pipeline" / "RUNS.md").read_text(encoding="utf-8")
    assert "| complete | - |" in md and "| manual-runlog | ручной лог" in md
    # --out must not be the batch itself
    try:
        backfill.run(bd, out=bd, sessions=[], usage=False, table=False)
        raise AssertionError("out == batch accepted")
    except runlog.RunlogError:
        pass


def test_cli_backfill_prints_gaps_and_summary_and_refuses_without_a_log():
    bd = _batch("2026-08-31T2155Z", LOG_A, ["wren-hollow-lockhart"])
    out = TMP / "cli-out"
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "runlog"), "backfill", str(bd), "--out", str(out),
                        "--root", str(FAKE_ROOT), "--no-table", "--stdout"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr
    assert "events -> " in r.stdout and "GAP 2026-08-31T22:01:30.000Z" in r.stdout
    assert "no --session: no transcript, tokens unknown" in r.stdout
    assert "# RUN_SUMMARY legacy-film/2026-08-31T2155Z" in r.stdout
    assert (out / "RUN_EVENTS.jsonl").is_file()
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "runlog"), "backfill", str(TMP)],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "no RUN_LOG.txt" in r.stderr
    r = subprocess.run([sys.executable, str(ROOT / "scripts" / "runlog"), "--help"],
                       capture_output=True, text=True, timeout=60)
    assert "runlog backfill" in r.stdout


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    shutil.rmtree(TMP, ignore_errors=True)
    sys.exit(1 if failed else 0)
