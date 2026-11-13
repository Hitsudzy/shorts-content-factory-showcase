#!/usr/bin/env python3
"""CC-0111: what the factory's batches of 13.10 brought into the command
center's batch API (`api/batches.py`).

* **frame-judge-empty** (CF-0707): the channels' run plans got a machine stage
  `frame-judge-empty` between `video-editor` and `frame-judge` - its markers
  are the executor's under the name `frame-judge` (`marker: frame-judge`,
  `marker_by: executor`), the LLM stage `frame-judge` is then `skipped`. The
  API knows no stage list of its own: the list (`GoingBatch.stages`), one batch
  (`state.order`, `state.stages`), the stages by markers and «повторить со
  стадии» carry the stage in the plan's place, none dropped, none renumbered.
* **code_edits** (CF-0713): a batch stage changed the factory's tracked code -
  run-state.json `code_edits[]` (`run_executor.record_code_edits`: `{stage,
  run, at, mode, task, edits: [{repo, files, head_was?, head_now?}]}`) and the
  `stage_code_edit` event in RUN_EVENTS.jsonl. `BatchDetail.code_edits` (each
  row with `files` from the root, the factory's `stage_code_guard.describe`
  line, `source`), `GoingBatch.code_edits` (the console's lines,
  `shared/dashboard/collect.py`) and `code_edits_count`; an old batch without
  the key: [] and 0; a batch with only the event: read from the event.

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_batches.py` (a temp git repository); every batch, state and
event is planted by the test. No batch is started, resumed or stopped, no
process is launched or signalled, nothing is timing-sensitive.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import _w, _ts, client, factory_tree, marker, write_batch  # noqa: E402

from api import batches                              # noqa: E402

batches.VIEW_TTL = 0.0          # every read rescans and waits for it
batches.VIEW_WAIT = 600.0
BID = "2026-10-13T0900Z"
ORDER = ["trend-hunter", "video-editor", "frame-judge-empty", "frame-judge", "publisher"]


def plan(root):
    _w(root / "channels" / "reel.json",
       {"channel_id": "reel", "display_name": "Reel",
        "run_plan": {"stages": [
            {"id": "trend-hunter"}, {"id": "video-editor"},
            {"id": "frame-judge-empty", "kind": "machine", "marker": "frame-judge",
             "marker_by": "executor", "after": ["video-editor"]},
            {"id": "frame-judge", "kind": "llm", "marker": "frame-judge",
             "marker_by": "skill", "after": ["frame-judge-empty"]},
            {"id": "publisher", "timeout_min": 30}]}})


def state(d, **kw):
    doc = {"version": 1, "task": "CF-0203", "channel": "reel", "batch": str(d),
           "batch_id": d.name, "order": ORDER, "status": "running", "created": _ts(3),
           "current": {"stage": "publisher", "run": "publisher.s0"}, "next": None,
           "stages": {"trend-hunter": {"status": "done"}, "video-editor": {"status": "done"},
                      "frame-judge-empty": {"status": "done"},
                      "frame-judge": {"status": "skipped",
                                      "reason": "when: judge_candidates - nothing to judge"},
                      "publisher": {"status": "running", "started": _ts(0.5)}},
           "handlers": {}, "decisions": {}, "runs": {}, "reruns": {}, "needs_human": [],
           "executor": {}}
    doc.update(kw)
    _w(d / "run-state.json", doc)
    return doc


def batch(root, bid=BID, extra=(), **kw):
    d = write_batch(root, "reel", bid, [
        marker("batch-start", hours_ago=3),
        marker("stage-start", "trend-hunter", hours_ago=2.9),
        marker("stage-done", "trend-hunter", hours_ago=2.5),
        marker("stage-start", "video-editor", hours_ago=2.4),
        marker("stage-done", "video-editor", hours_ago=1.5),
        marker("stage-start", "frame-judge", hours_ago=1.4),     # frame-judge-empty's,
        marker("stage-done", "frame-judge", hours_ago=1.39),     # by the executor
        marker("stage-start", "publisher", hours_ago=0.5), *extra])
    if kw.get("no_state"):
        return d
    state(d, **kw)
    return d


# --------------------------------------------------------------------- frame-judge-empty
def test_frame_judge_empty_is_carried_in_its_place():
    root = factory_tree()
    plan(root)
    batch(root)
    c = client(root)
    got = c.get("/api/batches").json()
    [b] = [x for x in got["batches"] if x["batch_id"] == BID]
    assert [s["id"] for s in b["stages"]] == ORDER, b["stages"]
    assert [s["status"] for s in b["stages"]] == \
        ["done", "done", "done", "skipped", "running"], b["stages"]
    assert b["stages"][3]["reason"].startswith("when: judge_candidates"), b["stages"]
    assert b["stage"] == "publisher" and b["stage_timeout_min"] == 30, b
    one = c.get(f"/api/batches/reel/{BID}").json()
    assert one["state"]["order"] == ORDER, one["state"]
    assert one["state"]["stages"]["frame-judge-empty"] == {"status": "done"}, one["state"]
    st = c.get(f"/api/batches/reel/{BID}/stages").json()
    assert [s["stage"] for s in st["stages"]] == \
        ["trend-hunter", "video-editor", "frame-judge", "publisher"], st["stages"]
    assert [s["open"] for s in st["stages"]] == [False, False, False, True], st["stages"]
    assert st["open_stages"] == ["publisher"], st
    rr = c.get(f"/api/batches/reel/{BID}/rerun-from").json()
    assert [s["stage"] for s in rr["stages_for_rerun"]] == ORDER, rr
    assert rr["stages_for_rerun"][2]["status"] == "done", rr


# --------------------------------------------------------------------- code_edits
def _row(root, at="2026-10-13T01:12:00Z"):
    """The night of 12-13.10: footage-indexer patched source_rights.py."""
    return {"stage": "footage-indexer", "run": "footage-indexer.s0", "at": at, "mode": "warn",
            "task": "CF-0713",
            "edits": [{"repo": "agents/footage-indexer",
                       "files": ["scripts/source_rights.py"]},
                      {"repo": "root", "files": [f"{root}/scripts/odd.py"],
                       "head_was": "a" * 40, "head_now": "b" * 40}]}


def _event(row):
    return {"ts": row["at"], "kind": "stage_code_edit", "stage": row["stage"], "status": "warn",
            "note": "agents/footage-indexer: scripts/source_rights.py", "edits": row["edits"],
            "task": "CF-0713", "run": row["run"], "plan_stage": row["stage"]}


def test_code_edits_from_the_run_state():
    root = factory_tree()
    plan(root)
    row = _row(root)
    later = dict(_row(root, "2026-10-13T02:00:00Z"), stage="frame-judge",
                 edits=[{"repo": "root", "files": ["shared/x.py"]}])
    d = batch(root, extra=[_event(dict(row, at="2026-10-13T00:00:00Z"))],
              code_edits=[row, later])
    c = client(root)
    one = c.get(f"/api/batches/reel/{BID}").json()
    assert str(root) not in json.dumps(one["code_edits"]), one["code_edits"]
    first, second = one["code_edits"]
    assert first["source"] == "state" and first["at"] == "2026-10-13T01:12:00Z", first
    assert (first["stage"], first["run"], first["mode"], first["task"]) == \
        ("footage-indexer", "footage-indexer.s0", "warn", "CF-0713"), first
    assert first["edits"][0] == {"repo": "agents/footage-indexer",
                                 "files": ["scripts/source_rights.py"],
                                 "head_was": None, "head_now": None}, first
    assert first["edits"][1]["head_now"] == "b" * 40, first
    assert first["files"][0] == "agents/footage-indexer/scripts/source_rights.py", first
    assert first["files"][1] in ("scripts/odd.py", ".../odd.py"), first     # cut, never absolute
    assert first["line"].startswith("agents/footage-indexer: scripts/source_rights.py; root: "), \
        first
    assert "HEAD aaaaaaaaaa -> bbbbbbbbbb" in first["line"], first
    assert second["files"] == ["shared/x.py"] and second["line"] == "root: shared/x.py", second
    assert len(one["state"]["code_edits"]) == 2, one["state"]
    assert str(root) not in json.dumps(one["state"]["code_edits"]), one["state"]
    got = c.get("/api/batches").json()
    [b] = [x for x in got["batches"] if x["batch_id"] == BID]
    assert b["code_edits_count"] == 2, b
    assert b["code_edits"][0].startswith("footage-indexer: agents/footage-indexer: "
                                         "scripts/source_rights.py"), b["code_edits"]
    assert str(root) not in json.dumps(b["code_edits"]), b["code_edits"]
    assert d.is_dir()


def test_code_edits_from_the_event_only():
    root = factory_tree()
    plan(root)
    row = _row(root)
    batch(root, extra=[_event(row)], no_state=True)
    c = client(root)
    one = c.get(f"/api/batches/reel/{BID}").json()
    assert one["state"] is None, one
    [e] = one["code_edits"]
    assert e["source"] == "events" and e["stage"] == "footage-indexer", e
    assert (e["run"], e["at"], e["mode"], e["task"]) == \
        ("footage-indexer.s0", "2026-10-13T01:12:00Z", "warn", "CF-0713"), e
    assert e["files"][0] == "agents/footage-indexer/scripts/source_rights.py", e
    assert e["note"] == "agents/footage-indexer: scripts/source_rights.py", e
    assert str(root) not in json.dumps(e), e
    got = c.get("/api/batches").json()
    [b] = [x for x in got["batches"] if x["batch_id"] == BID]
    assert b["code_edits_count"] == 1, b
    assert b["code_edits"] == [f"footage-indexer: {e['line']}"], b
    # the event comes in with the journal's next line, the cache read anew
    with open(root / "pipeline" / "reel" / BID / "RUN_EVENTS.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(_event(dict(row, at="2026-10-13T03:00:00Z"))) + "\n")
    assert len(c.get(f"/api/batches/reel/{BID}").json()["code_edits"]) == 2


def test_an_old_batch_has_no_code_edits():
    root = factory_tree()
    plan(root)
    batch(root)                                       # run-state.json without the key
    batch(root, "2026-10-13T1000Z", no_state=True)    # markers only, no event
    c = client(root)
    for bid in (BID, "2026-10-13T1000Z"):
        one = c.get(f"/api/batches/reel/{bid}").json()
        assert one["code_edits"] == [], one
        assert (one["state"] or {}).get("code_edits") is None, one
    got = c.get("/api/batches").json()
    rows = {x["batch_id"]: x for x in got["batches"]}
    assert rows[BID]["code_edits_count"] == 0 and rows[BID]["code_edits"] == [], rows[BID]
    assert rows["2026-10-13T1000Z"]["code_edits_count"] == 0, rows["2026-10-13T1000Z"]
    assert not rows["2026-10-13T1000Z"]["code_edits"], rows["2026-10-13T1000Z"]


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:                       # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
