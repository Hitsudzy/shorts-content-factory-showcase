#!/usr/bin/env python3
"""CC-0114: the stranded batches in the command center's API -
`GET /api/batches/stranded?channel&limit` over the factory's
`batch_schedule.stranded_batches` (CF-0723).

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_batches.py` (a temp git repository with `reel` and
`demo`; the schedule's state directory under the temp root), with batch
folders, `run-state.json`, `RUN_EVENTS.jsonl`, `pipeline/runs.jsonl` and a
launch row planted by the test. Nothing of the live factory is read; the
factory's *code* is this checkout's, as in production.

What is pinned:

* the contract: the route, GET only, version 0.48.0, `channel` and `limit`,
  `BatchProblem` on 404/422/500, the row's fields;
* the rows are the factory's selection as is (the same as
  `stranded_batches(root, now)` at the answer's `as_of`), plus `log_url`,
  `batch` («<dir>/<batch_id>») and `log_name` (CC-0114, for CC-0089's screen):
  a failed batch with no runs.jsonl row; one with a row, a fresh open one
  and a running one are not listed; a stale open one (> 24 h) is; a rebuild
  is and never holds the day;
* `log_url` / `log_name` - the log route / its {name} when the log is
  `<dir>/logs/<name>` that route
  serves (and that route answers its tail), null for a launch's log in
  `schedule/logs/` and for a step log that is not on disk;
* `channel` filters (an old id resolves; an unknown one is 404), `limit`
  cuts (default 20; 0 and 201 are 422);
* a failed factory read is `error` with no rows, not a refusal;
* no absolute path of the machine in the answer; the module selects nothing
  itself (no run-state, runs.jsonl or open-batch read in `stranded`).
"""
import ast
import inspect
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import _w, client, factory_tree, marker, write_batch   # noqa: E402

import api                                           # noqa: E402
from api import batches, factory                     # noqa: E402

URL = "/api/batches/stranded"
ORDER = ["batch-start", "trend-hunter", "video-editor"]


def bid(hours_ago=0.0):
    t = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
    return t.strftime("%Y-%m-%dT%H%MZ")


def ts(hours_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).strftime(
        "%Y-%m-%dT%H:%M:%SZ")


def state(d, status="failed", stage="batch-start", log="logs/batch-start.s0.a0.log",
          channel="reel"):
    stages = {"batch-start": {"status": "failed" if status == "failed" else "done",
                              "reason": "step 0 (runlog batch-start) exited 2"}}
    runs = {"batch-start.s0": {"stage": stage, "log": log}} if log else {}
    _w(d / "run-state.json", {
        "version": 1, "channel": channel, "batch": str(d), "batch_id": d.name, "order": ORDER,
        "status": status, "created": ts(1), "updated": ts(0.5), "current": {}, "next": None,
        "stages": stages, "runs": runs, "halt_reason": "halted by hand" if status == "halted"
        else None, "stops": []})
    return d


def batch(root, chan, b, *, events=None, log_on_disk=True, **kw):
    d = root / "pipeline" / chan / b
    d.mkdir(parents=True, exist_ok=True)
    if events is not None:
        write_batch(root, chan, b, events)
    state(d, **kw)
    if log_on_disk and kw.get("log", "logs/batch-start.s0.a0.log"):
        _w(d / (kw.get("log") or "logs/batch-start.s0.a0.log"), "line 1\nboom\n")
    return d


def tree():
    """reel: a failed batch (its step log on disk), one with a runs.jsonl
    row, a fresh open failed one, a running one, a stale open halted one;
    a failed rebuild of today; demo: nothing."""
    root = factory_tree()
    b1, b2, b3, b4, b5 = bid(30), bid(29), bid(1), bid(2), bid(40)
    batch(root, "reel", b1)
    batch(root, "reel", b2)
    batch(root, "reel", b3, events=[marker("batch-start", hours_ago=1)])
    batch(root, "reel", b4, status="running")
    batch(root, "reel", b5, status="halted", events=[marker("batch-start", hours_ago=40)])
    rb = batch(root, "rebuilds", bid(0.5))
    _w(root / "pipeline" / "runs.jsonl", json.dumps({"id": b2, "channel": "reel"}) + "\n")
    return root, {"failed": b1, "recorded": b2, "fresh": b3, "running": b4, "stale": b5,
                  "rebuild": rb.name}


def get(root, **params):
    r = client(root).get(URL, params=params)
    return r.status_code, r.json()


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_route():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    assert sorted(spec["paths"].get(URL, {})) == ["get"], spec["paths"].get(URL)
    op = spec["paths"][URL]["get"]
    params = {p["name"]: p for p in op["parameters"]}
    assert set(params) == {"channel", "limit"}, params
    lim = params["limit"]["schema"]
    assert (lim["minimum"], lim["maximum"], lim["default"]) == (1, 200, 20), lim
    for code in ("404", "422", "500"):
        assert op["responses"][code]["content"]["application/json"]["schema"]["$ref"] \
            .endswith("/BatchProblem"), code
    schemas = spec["components"]["schemas"]
    assert set(schemas["StrandedBatches"]["properties"]) == {"batches", "as_of", "error"}
    assert {"dir", "channel", "batch_id", "status", "created", "updated", "stage", "reason",
            "log", "log_url", "halt_reason", "stages", "holds_day",
            "batch", "log_name"} \
        == set(schemas["StrandedBatch"]["properties"])
    assert set(schemas["StrandedStage"]["properties"]) == {"id", "status", "reason"}


def test_the_command_has_its_row():
    rows = json.loads((ROOT / "api" / "commands.json").read_text(encoding="utf-8"))["commands"]
    got = [r for r in rows if r["command"] == "python3 shared/batch_schedule.py stranded --json"]
    assert len(got) == 1 and got[0]["api"] == "GET /api/batches/stranded" \
        and got[0]["screen"] == "/batches" and got[0]["task"] == "CC-0089", got


def test_the_api_selects_nothing_itself():
    src = inspect.getsource(batches.stranded)
    names = {n.attr if isinstance(n, ast.Attribute) else n.id
             for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Attribute, ast.Name))}
    assert "stranded_batches" in names, names
    for name in ("open_batches", "read_rows", "read_state", "_run_state", "launches",
                 "started_on", "STRANDED", "glob"):
        assert name not in names, name


# --------------------------------------------------------------------- the rows
def test_the_rows_are_the_factory_s_with_log_url():
    root, b = tree()
    code, got = get(root)
    assert code == 200 and got["error"] is None, got
    now = datetime.fromisoformat(got["as_of"].replace("Z", "+00:00"))
    want = factory.batch_schedule().stranded_batches(root, now=now)
    ours = ("log_url", "batch", "log_name")              # the API's, the rest the factory's
    assert [dict((k, v) for k, v in r.items() if k not in ours) for r in got["batches"]] \
        == want, (got, want)
    ids = [r["batch_id"] for r in got["batches"]]
    assert set(ids) == {b["failed"], b["stale"], b["rebuild"]}, ids
    row = {r["batch_id"]: r for r in got["batches"]}
    f = row[b["failed"]]
    assert f["dir"] == f"pipeline/reel/{b['failed']}" and f["status"] == "failed" \
        and f["stage"] == "batch-start" and f["holds_day"] is False, f
    assert f["log"] == f"pipeline/reel/{b['failed']}/logs/batch-start.s0.a0.log", f
    assert f["log_url"] == f"/api/batches/reel/{b['failed']}/logs/batch-start.s0.a0.log", f
    # CC-0114 (CC-0089's screen): the batch routes' path and the log route's {name}
    assert f["batch"] == f"reel/{b['failed']}" and f["log_name"] == "batch-start.s0.a0.log", f
    assert f["log_url"] == f"/api/batches/{f['batch']}/logs/{f['log_name']}", f
    assert [s["id"] for s in f["stages"]] == ORDER and f["stages"][1]["status"] == "pending", f
    assert row[b["stale"]]["status"] == "halted", row[b["stale"]]
    rb = row[b["rebuild"]]
    assert rb["dir"] == f"pipeline/rebuilds/{b['rebuild']}" and rb["holds_day"] is False, rb
    assert rb["log_url"] == f"/api/batches/rebuilds/{b['rebuild']}/logs/batch-start.s0.a0.log"
    assert rb["batch"] == f"rebuilds/{b['rebuild']}" and rb["log_name"] == "batch-start.s0.a0.log"
    tail = client(root).get(f["log_url"]).json()
    assert tail["text"] == "line 1\nboom\n", tail
    assert str(root) not in json.dumps(got) and str(root.resolve()) not in json.dumps(got)


def test_a_log_without_its_route_has_no_url():
    root = factory_tree()
    b1, b2 = bid(30), bid(31)
    batch(root, "reel", b1, log_on_disk=False)                  # the step log is not there
    d = batch(root, "reel", b2, log=None)                       # no step log: the launch's
    logs = factory.batch_schedule().state_dir(root) / "logs" / "run-x.log"
    _w(logs, "x\n")
    _w(factory.batch_schedule().state_dir(root) / "launches.jsonl",
       json.dumps({"kind": "resume", "batch": str(d), "log": str(logs)}) + "\n")
    code, got = get(root)
    row = {r["batch_id"]: r for r in got["batches"]}
    assert code == 200 and set(row) == {b1, b2}, got
    assert row[b1]["log"] and row[b1]["log_url"] is None and row[b1]["log_name"] is None, row
    assert row[b2]["log"] == "schedule/logs/run-x.log" and row[b2]["log_url"] is None, row[b2]
    assert row[b2]["log_name"] is None and row[b2]["batch"] == f"reel/{b2}", row[b2]
    assert str(root.resolve()) not in json.dumps(got), got


def test_none_stranded_is_an_empty_list():
    code, got = get(factory_tree())
    assert code == 200 and got["batches"] == [] and got["error"] is None and got["as_of"], got


# --------------------------------------------------------------------- filter, limit
def test_the_channel_filters_and_an_unknown_is_404():
    root, b = tree()
    _code, got = get(root, channel="reel")
    assert {r["batch_id"] for r in got["batches"]} == {b["failed"], b["stale"], b["rebuild"]}
    _code, old = get(root, channel="old-reel")
    assert old["batches"] == got["batches"], old
    code, demo = get(root, channel="demo")
    assert code == 200 and demo["batches"] == [], demo
    code, bad = get(root, channel="nope")
    assert code == 404 and bad["code"] == "unknown_channel", bad


def test_the_limit_cuts_in_the_factory_s_order():
    root, _b = tree()
    _code, every = get(root)
    _code, one = get(root, limit=1)
    assert one["batches"] == every["batches"][:1], one
    for bad in (0, 201):
        code, _got = get(root, limit=bad)
        assert code == 422, (bad, _got)


def test_a_failed_read_is_error_not_a_refusal():
    root, _b = tree()
    bs = factory.batch_schedule()
    orig = bs.stranded_batches

    def broken(*a, **kw):
        raise OSError(f"cannot read {root}/pipeline")
    bs.stranded_batches = broken
    try:
        code, got = get(root)
    finally:
        bs.stranded_batches = orig
    assert code == 200 and got["batches"] == [] and got["error"].startswith("OSError"), got
    assert str(root) not in got["error"], got


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
