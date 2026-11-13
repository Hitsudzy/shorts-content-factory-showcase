#!/usr/bin/env python3
"""CF-0739 items 3-5: the post-run readers see a recorded reset of the batch's stages.

The incident: example-film/2026-10-13T1411Z. The footage-indexer operator was
killed (hotfix 2.3.4, CF-0734), the batch went failed, main moved under it
(cde33e2 -> 9385d97), the user reset the stages from footage-indexer on - a
`manual_resets` row in run-state.json, nothing in RUN_EVENTS.jsonl - and the
batch was resumed and finished. The triage then filed four аварии that were
all this one event: code_drift:root, built_off_run (4 videos), a red DoD-1
(GAPS 1h13m40s) and a crash (footage-indexer opened 14:18:17Z, never closed).

Pinned here, on a stand-in of that batch (its marker times, its reset row):

* with the reset recorded (run-state only, or rerun_from's event only) none of
  the four is an авария - the triage lists the reset under `resets` instead,
  with what it explained, and the no-waiting reading sets the stop aside named
  by the reset;
* the same data without the reset gives all four, as before;
* a move of the code after the reset is still code_drift (and a video built by
  it still built_off_run); a gap elsewhere in the run is still judged; a stage
  opened before the reset but not reset by it is still a crash.

Temp trees only; no live batch, no network.
"""
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "runlog"))
import gaps          # noqa: E402
import no_waiting    # noqa: E402
import runlog        # noqa: E402
import runs_table    # noqa: E402
import triage        # noqa: E402
from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("manual-reset-readers-")
_n = [0]

OLD, NEW, LATER = "cde33e2f7cd55893b86807a4eca090a94f4dab13", \
    "9385d97ced5bb9b557aff5e02279683788cfbc40", "c" * 40
VE = "e" * 40
BATCH_ID = "2026-10-13T1411Z"
RESET = {   # the row the user's reset script wrote into 1411Z's run-state.json
    "at": "2026-10-13T15:52:24Z",
    "by": "user (script prepared by the auto-dev driver)",
    "task": "CF-0734",
    "why": "footage-indexer was recorded done by the pre-2.3.4 executor while its ingest "
           "was killed (the operator ended its turn); stages from footage-indexer on reset "
           "to pending",
    "reset": ["footage-indexer", "content-researcher", "compliance-scripts", "video-editor",
              "frame-judge", "batch-done", "monitors", "triage", "commit-records"],
}
STOP_S = 4419.8     # 14:39:09.243 -> 15:52:49.086, the GAPS of 1411Z's runs row


def _t(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def _z(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def mk(ts, status, stage=None, kind="marker", **kw):
    e = {"ts": ts, "kind": kind, "status": status, "stage": stage, "step": None,
         "video": None, "id": f"id{ts}"}
    e.update(kw)
    return e


def events_1411z(move_after_reset=False, hole=None, reset_event=False):
    """The marker timeline of 1411Z, with a sampler tick every 5 minutes except
    while the batch stood stopped (and inside `hole`, an extra silence)."""
    m = [
        mk("2026-10-13T14:11:27.584Z", "batch-start", header={"git": {
            "root": {"commit": OLD, "dirty": False},
            "agents": {"video-editor": {"commit": VE, "dirty": False}}}}),
        mk("2026-10-13T14:11:52.947Z", "stage-start", "trend-hunter"),
        mk("2026-10-13T14:17:14.590Z", "stage-done", "trend-hunter"),
        mk("2026-10-13T14:17:33.453Z", "stage-start", "compliance-checker"),
        mk("2026-10-13T14:17:56.346Z", "stage-done", "compliance-checker"),
        mk("2026-10-13T14:18:17.836Z", "stage-start", "footage-indexer"),
        mk("2026-10-13T14:38:57.785Z", "stage-start", "content-researcher"),
        mk("2026-10-13T14:38:59.182Z", "stage-done", "content-researcher",
           note="01b-footage-index.json is missing, no scripts written"),
        mk("2026-10-13T14:39:09.243Z", "batch-done"),
        mk("2026-10-13T15:48:35.794Z", "batch-resume", kind="control", by="user (центр)"),
        mk("2026-10-13T15:52:35.822Z", "batch-resume", kind="control", by="user (центр)"),
        mk("2026-10-13T15:52:49.086Z", "stage-start", "footage-indexer",
           code_drift=[{"repo": "root", "was": OLD, "now": NEW}]),
        mk("2026-10-13T16:58:16.303Z", "stage-done", "footage-indexer"),
        mk("2026-10-13T16:58:54.372Z", "stage-start", "content-researcher"),
        mk("2026-10-13T18:25:50.929Z", "stage-done", "content-researcher"),
        mk("2026-10-13T18:26:14.134Z", "stage-start", "thin-pool-supplement"),
        mk("2026-10-13T18:39:00.463Z", "stage-done", "thin-pool-supplement"),
        mk("2026-10-13T18:39:15.241Z", "stage-start", "content-researcher"),
        mk("2026-10-13T18:53:41.404Z", "stage-done", "content-researcher"),
        mk("2026-10-13T18:54:04.151Z", "stage-start", "compliance-checker"),
        mk("2026-10-13T18:54:33.907Z", "stage-done", "compliance-checker"),
        mk("2026-10-13T18:55:16.802Z", "stage-start", "video-editor",
           **({"code_drift": [{"repo": "root", "was": NEW, "now": LATER}]}
              if move_after_reset else {})),
        mk("2026-10-13T19:33:34.203Z", "stage-done", "video-editor"),
        mk("2026-10-13T19:34:05.797Z", "stage-start", "frame-judge"),
        mk("2026-10-13T19:37:03.727Z", "stage-done", "frame-judge"),
        mk("2026-10-13T19:37:31.374Z", "batch-done"),
    ]
    if reset_event:
        m.append(mk("2026-10-13T15:52:25.000Z", runlog.EV_RERUN_FROM, kind="control",
                    by=RESET["by"], task=RESET["task"], note="батч: стадии сброшены",
                    params={"from": "footage-indexer", "reset": RESET["reset"],
                            "why": RESET["why"]}))
    stopped = (_t("2026-10-13T14:39:09.243Z"), _t("2026-10-13T15:52:49.086Z"))
    holes = [stopped] + ([tuple(map(_t, hole))] if hole else [])
    t, end = _t("2026-10-13T14:11:30.000Z"), _t("2026-10-13T19:37:30.000Z")
    while t < end:
        if not any(a <= t <= b for a, b in holes):
            m.append(mk(_z(t), "tick", kind="sample", params={}))
        t += timedelta(seconds=300)
    return sorted(m, key=lambda e: e["ts"])


def batch(events, resets=(RESET,), video_root=NEW, slugs=("s1", "s2", "s3", "s4")):
    """A 1411Z stand-in: the events, a run-state.json with `manual_resets`, and
    four ready videos whose code_shas name `video_root`."""
    _n[0] += 1
    b = TMP / f"pool-{_n[0]}" / "example-film" / BATCH_ID
    b.mkdir(parents=True)
    scripts = [{"script_id": s, "topic_id": f"t{i}"} for i, s in enumerate(slugs)]
    files = {
        "01-trend-hunter.json": {"batch_id": "B", "topics": [{"topic_id": x["topic_id"]}
                                                             for x in scripts]},
        "02-compliance-checker.json": {"batch_id": "B", "results": [
            {"topic_id": x["topic_id"], "verdict": "clear"} for x in scripts]},
        "01b-footage-index.json": {"batch": str(b), "fetched": [], "skipped_topics": [],
                                   "failed": [], "sources_by_topic": {
                                       x["topic_id"]: ["a", "b"] for x in scripts}},
        "03-content-researcher.json": {"batch_id": "B", "skipped": [], "scripts": scripts},
        "04-compliance-checker.json": {"batch_id": "B", "results": [
            {"script_id": x["script_id"], "verdict": "clear"} for x in scripts]},
        "05-video-editor.json": {"batch_id": "B", "refusals": [], "videos": [
            {"script_id": s, "output_path": f"/x/{s}.mp4", "qc": {"passed": True},
             "code_shas": {"root": {"commit": video_root, "dirty": False},
                           "agents/video-editor": {"commit": VE, "dirty": False}}}
            for s in slugs]},
        "06-frame-judge.json": {"batch_id": "B", "videos": []},
    }
    for name, d in files.items():
        (b / name).write_text(json.dumps(d), encoding="utf-8")
    (b / runlog.EVENTS_FILE).write_text("".join(json.dumps(e, ensure_ascii=False) + "\n"
                                                for e in events), encoding="utf-8")
    state = {"status": "done", "order": RESET["reset"], "stages": {}}
    if resets:
        state["manual_resets"] = [dict(r) for r in resets]
    (b / runlog.STATE_FILE).write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    return b


def run(b):
    return triage.triage(b, config={}, ledger={"rules": {}}, gate_results=[])


def keys(res, kind):
    return sorted(i["key"] for i in res["incidents"] if i["kind"] == kind)


# --------------------------------------------------------------------------
# the triage: code_drift, built_off_run, crash (items 3 and 5)
# --------------------------------------------------------------------------

def test_without_the_reset_1411z_gives_the_three_triage_incidents_as_before():
    res = run(batch(events_1411z(), resets=()))
    assert keys(res, triage.CODE_DRIFT) == ["code_drift:root"], res["incidents"]
    off = [i for i in res["incidents"] if i["kind"] == triage.BUILT_OFF_RUN]
    assert [(i["key"], i["count"]) for i in off] == [("built_off_run:root:commit", 4)], off
    assert keys(res, triage.CRASH) == ["crash:footage-indexer:stage_not_closed"], res["incidents"]
    assert res["resets"] == []


def test_with_the_reset_recorded_in_run_state_only_none_of_the_three_is_an_incident():
    b = batch(events_1411z())
    res = run(b)
    assert res["incidents"] == [], res["incidents"]
    [r] = res["resets"]
    assert r["task"] == "CF-0734" and r["at"] == RESET["at"] and r["from"] == "footage-indexer"
    assert r["by"] == RESET["by"] and r["why"] == RESET["why"], r
    what = sorted((x["what"], x.get("repo") or x["stage"]) for x in r["explained"])
    assert what == [("code_base", "root"), ("stage_closed", "footage-indexer")], r["explained"]
    base = next(x for x in r["explained"] if x["what"] == "code_base")
    assert (base["was"], base["now"]) == (OLD, NEW), base
    text = triage.render(res)
    assert "Ручные сбросы стадий: 1 (CF-0739)" in text and "CF-0734" in text, text
    assert "закрыта сбросом" in text and "база кода: root" in text, text


def test_the_reset_seen_only_as_rerun_froms_event_counts_too_and_once_with_the_row():
    res = run(batch(events_1411z(reset_event=True), resets=()))
    assert res["incidents"] == [], res["incidents"]
    assert [r["task"] for r in res["resets"]] == ["CF-0734"], res["resets"]
    both = run(batch(events_1411z(reset_event=True)))
    assert both["incidents"] == [] and len(both["resets"]) == 1, both["resets"]


def test_a_move_of_the_code_after_the_reset_is_still_code_drift_and_its_videos_off_run():
    res = run(batch(events_1411z(move_after_reset=True), video_root=LATER))
    drift = [i for i in res["incidents"] if i["kind"] == triage.CODE_DRIFT]
    assert [(i["key"], i["count"]) for i in drift] == [("code_drift:root", 1)], drift
    assert NEW[:12] in drift[0]["what"] and LATER[:12] in drift[0]["what"], drift
    off = [i for i in res["incidents"] if i["kind"] == triage.BUILT_OFF_RUN]
    assert [(i["key"], i["count"]) for i in off] == [("built_off_run:root:commit", 4)], off
    assert NEW[:12] in off[0]["what"], off     # judged against the reset's base, not the header
    # the reset's own base move and the closed stage are still explained, not аварии
    assert keys(res, triage.CRASH) == [], res["incidents"]


def test_videos_of_the_old_code_after_a_reset_of_the_editor_are_off_run():
    """The new base binds the reset video-editor: a video it built on the code the
    batch started on is not the output of the run after the reset."""
    res = run(batch(events_1411z(), video_root=OLD))
    assert keys(res, triage.BUILT_OFF_RUN) == ["built_off_run:root:commit"], res["incidents"]


def test_a_stage_opened_before_the_reset_but_not_reset_by_it_is_still_a_crash():
    evs = events_1411z()
    evs.append(mk("2026-10-13T14:20:00.000Z", "stage-start", "trend-hunter"))
    res = run(batch(sorted(evs, key=lambda e: e["ts"])))
    assert keys(res, triage.CRASH) == ["crash:trend-hunter:stage_not_closed"], res["incidents"]


def test_a_reset_names_its_stages_by_their_markers():
    """A plan id whose stage writes another marker (compliance-scripts writes
    compliance-checker) is matched through the `markers` rerun_from records."""
    r = runlog.manual_resets(state={"manual_resets": [dict(RESET, markers=["compliance-checker"])]})
    assert "compliance-checker" in runlog.reset_names(r[0])
    assert "compliance-checker" not in runlog.reset_names(
        runlog.manual_resets(state={"manual_resets": [RESET]})[0], channel=None)


# --------------------------------------------------------------------------
# CF-0730: the contract check - a close the reset threw away, and the
# no-waiting close that names its missing upstream file
# --------------------------------------------------------------------------

FIRST_DONE = "2026-10-13T14:39:09.243Z"


def _before_reset(evs):
    return [e for e in evs if e["ts"] <= FIRST_DONE]


def test_the_first_1411z_triage_blames_the_footage_indexer_not_the_researcher():
    """The triage at 14:39 (CF-0730 was filed by it): the indexer was killed
    without 01b, the researcher closed on its no-waiting exit naming 01b. The
    broken contract is the indexer's - not `contract:missing:03`."""
    b = batch(_before_reset(events_1411z()), resets=())
    for name in ("01b-footage-index.json", "03-content-researcher.json",
                 "04-compliance-checker.json", "05-video-editor.json", "06-frame-judge.json"):
        (b / name).unlink()
    res = run(b)
    contract = [i for i in res["incidents"] if i["kind"] == triage.CONTRACT]
    assert [(i["key"], i["stage"]) for i in contract] == [
        ("contract:missing:01b-footage-index.json", "footage-indexer")], contract
    assert "content-researcher closed on its no-waiting exit" in contract[0]["detail"]
    assert "crash:footage-indexer:stage_not_closed" in keys(res, triage.CRASH)


def test_a_close_without_a_note_naming_upstream_is_still_the_stages_own_break():
    evs = [dict(e, note=None) if e.get("status") == "stage-done" else e
           for e in _before_reset(events_1411z())]
    b = batch(evs, resets=())
    (b / "03-content-researcher.json").unlink()
    assert "contract:missing:03-content-researcher.json" in keys(run(b), triage.CONTRACT)


def test_a_close_the_reset_threw_away_is_listed_not_an_incident():
    """The batch reset after the first close and not run again yet: the old
    close owes nothing - the reset says so, under `resets`."""
    b = batch(_before_reset(events_1411z()))
    for name in ("01b-footage-index.json", "03-content-researcher.json", "04-compliance-checker.json",
                 "05-video-editor.json", "06-frame-judge.json"):
        (b / name).unlink()
    res = run(b)
    assert keys(res, triage.CONTRACT) == [], res["incidents"]
    [r] = res["resets"]
    sup = [x for x in r["explained"] if x["what"] == "artifact_superseded"]
    assert [(x["stage"], x["file"]) for x in sup] == [
        ("content-researcher", "03-content-researcher.json")], r["explained"]
    assert "этот прогон сброшен" in triage.render(res)


def test_a_run_after_the_reset_that_closes_without_its_file_is_still_a_break():
    b = batch(events_1411z())
    (b / "05-video-editor.json").unlink()
    assert "contract:missing:05-video-editor.json" in keys(run(b), triage.CONTRACT)


def test_a_shared_marker_is_told_apart_by_the_file_the_reset_stage_produces():
    """compliance-scripts (reset) and compliance-shortlist (not) both write the
    compliance-checker marker: the reset does not excuse a missing 02."""
    b = batch(events_1411z())
    (b / "02-compliance-checker.json").unlink()
    res = run(b)
    assert "contract:missing:02-compliance-checker.json" in keys(res, triage.CONTRACT), \
        res["incidents"]
    assert "contract:missing:04-compliance-checker.json" not in keys(res, triage.CONTRACT)


# --------------------------------------------------------------------------
# no waiting: the stop around the reset (item 4)
# --------------------------------------------------------------------------

def test_the_gap_that_holds_the_reset_is_named_by_it():
    b = batch(events_1411z())
    [g] = gaps.detect(b)
    assert g["cause"] == gaps.CAUSE_RESET and g["seconds"] == STOP_S, g
    assert g["evidence"]["reset"]["task"] == "CF-0734", g
    assert "recorded reset 2026-10-13T15:52:24Z (CF-0734" in gaps.format_gap(g)
    [g0] = gaps.detect(batch(events_1411z(), resets=()))
    assert g0["cause"] == gaps.CAUSE_UNKNOWN, g0


def test_without_the_reset_the_stop_is_a_gap_and_an_incident():
    a = no_waiting.audit(batch(events_1411z(), resets=()))
    assert a["verdict"] == no_waiting.INCIDENT and a["gaps_s"] == STOP_S, a
    assert a["reset_stops"] == [], a


def test_with_the_reset_the_stop_is_ruled_and_named_not_silently_passed():
    a = no_waiting.audit(batch(events_1411z()))
    assert a["verdict"] == no_waiting.CLEAN and a["gaps_s"] == 0 and a["gaps_count"] == 0, a
    [s] = a["reset_stops"]
    assert s["task"] == "CF-0734" and s["by"] == RESET["by"] and s["why"] == RESET["why"], s
    assert s["gaps_s"] == STOP_S and s["start"] == "2026-10-13T14:39:09.243Z", s
    block = "\n".join(no_waiting.render(a))
    assert "Ruled stops (CF-0739)" in block and "CF-0734" in block, block


def test_a_gap_elsewhere_in_the_run_is_still_judged():
    hole = ("2026-10-13T19:00:00.000Z", "2026-10-13T19:20:00.000Z")
    a = no_waiting.audit(batch(events_1411z(hole=hole)))
    assert a["verdict"] == no_waiting.INCIDENT and a["gaps_count"] == 1, a
    assert 900 < a["gaps_s"] < 1800 and len(a["reset_stops"]) == 1, a


def test_the_runs_row_carries_the_ruled_stop():
    row = runs_table.row(batch(events_1411z()))
    assert row["gaps_s"] == STOP_S, row["gaps_s"]          # the wall is still the wall
    assert [(s["task"], s["gaps_s"]) for s in row["reset_stops"]] == [("CF-0734", STOP_S)], row
    assert runs_table.row(batch(events_1411z(), resets=()))["reset_stops"] == []


# --------------------------------------------------------------------------
# DoD 1 over the runs table
# --------------------------------------------------------------------------

def fake_root(rows, batch_dirs=()):
    _n[0] += 1
    r = TMP / f"root{_n[0]}"
    (r / "pipeline").mkdir(parents=True)
    (r / runs_table.RUNS_JSONL).write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
    for src, name in batch_dirs:
        dst = r / "pipeline" / name
        dst.mkdir(parents=True)
        for f in src.iterdir():
            (dst / f.name).write_bytes(f.read_bytes())
    return r


def row_1411z(**kw):
    r = {"batch": f"example-film/{BATCH_ID}", "id": BATCH_ID, "channel": "example-film",
         "started": "2026-10-13T14:11:27.584Z", "gaps_s": STOP_S, "wall_s": 19563.8,
         "waits_s": 0, "waits": {"count": 0, "codes": [], "unclassified": 0,
                                 "verdict": "incident"}}
    r.update(kw)
    return r


STOP_ROW = {"at": RESET["at"], "task": "CF-0734", "by": RESET["by"], "why": RESET["why"],
            "from": "footage-indexer", "gaps_s": STOP_S, "waits_s": 0.0}


def test_dod_sets_a_run_aside_by_its_recorded_reset_and_names_it():
    x = no_waiting.dod(fake_root([row_1411z(reset_stops=[STOP_ROW])]))
    assert x["state"] == no_waiting.DOD_NO_RUN and x["offenders"] == [], x
    assert [r["batch"] for r in x["reset"]] == [f"example-film/{BATCH_ID}"], x
    assert "set aside by a recorded batch reset (CF-0739)" in x["line"], x["line"]
    assert "CF-0734" in x["line"] and "1h13m40s" in x["line"], x["line"]
    # more than the stop: the rest is judged, and the line says what was ruled
    y = no_waiting.dod(fake_root([row_1411z(gaps_s=STOP_S + 900, reset_stops=[STOP_ROW])]))
    assert y["state"] == no_waiting.DOD_FAILED, y
    assert y["offenders"][0]["why"].startswith("GAPS 15m00s"), y["offenders"]
    assert "CF-0734" in y["offenders"][0]["why"], y["offenders"]


def test_dod_reads_an_older_row_against_its_batchs_run_state():
    """1411Z's own row was written before CF-0739: no `reset_stops`. While the
    batch directory is on disk, its run-state.json names the reset."""
    with_reset = fake_root([row_1411z()], [(batch(events_1411z()), f"example-film/{BATCH_ID}")])
    x = no_waiting.dod(with_reset)
    assert x["state"] == no_waiting.DOD_NO_RUN and len(x["reset"]) == 1, x["line"]
    assert "CF-0734" in x["line"], x["line"]
    without = fake_root([row_1411z()], [(batch(events_1411z(), resets=()),
                                         f"example-film/{BATCH_ID}")])
    y = no_waiting.dod(without)
    assert y["state"] == no_waiting.DOD_FAILED and "GAPS 1h13m40s" in y["line"], y["line"]
    gone = no_waiting.dod(fake_root([row_1411z()]))
    assert gone["state"] == no_waiting.DOD_FAILED, gone["line"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
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
    sys.exit(1 if failed else 0)
