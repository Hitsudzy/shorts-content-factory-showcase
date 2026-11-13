#!/usr/bin/env python3
"""CF-0723: `batch_schedule.stranded_batches()` - the batches (and rebuilds)
that stopped badly (`failed`/`halted`/`stopped`), have no `runs.jsonl` row and
are not open: what the center's screen lists (CC-0089).

Every root is a synthetic tree in a temp dir; `open_rows`/`runs` stand in for
`runlog.open_batches` and `pipeline/runs.jsonl` where a test needs them.

What is pinned:

* failed without a runs row -> listed, with the row's keys; with a runs row
  (by `batch` or by channel + id) -> not; open (a fresh open row) -> not, a
  stale open row -> listed; stopped and halted -> listed; done / running /
  paused, no run-state, `backfill/` -> not; a failed rebuild -> listed;
* `holds_day` is exactly what `started_on` counts for today: a batch that
  spent no quota (hotfix 2.3.1) does not hold it, one that reached
  trend-hunter does, one of another day does not, a rebuild never does;
* the log: the stopping stage's step log, else the executor's log of its launch;
* the CLI `stranded` (text and `--json`).
"""
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import batch_schedule as bs         # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("stranded-batches-test-")
A = "alpha"
NOW = "2026-10-07T23:30:00Z"                 # 08.10 02:30 МСК
NEXT_DAY = "2026-10-08T23:30:00Z"            # 09.10 02:30 МСК
BID = "2026-10-07T2215Z"                     # 08.10 01:15 МСК - today for NOW
ORDER = ["rights-check", "batch-start", "pool-maintenance", "trend-hunter", "video-editor",
         "batch-done", "commit-records"]
KEYS = {"dir", "channel", "batch_id", "status", "created", "updated", "stage", "reason", "log",
        "halt_reason", "stages", "holds_day"}
_n = [0]


def _w(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _root():
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    _w(r / "channels" / f"{A}.json", {"channel_id": A, "run_plan": {"stages": []}})
    return r


def _env(r):
    return {bs.STATE_ENV: str(r / "schedule")}


def _batch(root, status="failed", reached=False, parent=A, bid=BID, extra=None):
    """A batch the executor ran: batch-start failed (or, with `reached`,
    trend-hunter started and failed); the always-run tail ran."""
    d = root / "pipeline" / parent / bid
    d.mkdir(parents=True)
    (d / "run-executor.lock").write_text("pid 4242 since 2026-10-07T22:15:30Z\n")
    stages = {"rights-check": {"status": "done", "started": "x"},
              "batch-start": {"status": "failed", "started": "x",
                              "reason": "step 0 (runlog batch-start) exited 2; log "
                                        "logs/batch-start.s0.a0.log"},
              "pool-maintenance": {"status": "skipped", "reason": "after failed stage batch-start"},
              "trend-hunter": {"status": "skipped", "reason": "after failed stage batch-start"},
              "video-editor": {"status": "skipped"},
              "batch-done": {"status": "failed", "started": "x"},
              "commit-records": {"status": "done", "started": "x"}}
    if reached:
        stages["batch-start"] = {"status": "done", "started": "x"}
        stages["trend-hunter"] = {"status": "failed", "started": "2026-10-07T22:20:00Z",
                                  "reason": "step 0 exited 1"}
    st = {"version": 1, "task": "CF-0203", "channel": A, "batch_id": bid, "order": ORDER,
          "status": status, "created": "2026-10-07T22:15:30Z",
          "updated": "2026-10-07T22:30:00Z", "current": None, "stages": stages,
          "executor": {"pid": 4343},
          "runs": {"batch-start.s0.a0": {"stage": "batch-start",
                                         "log": "logs/batch-start.s0.a0.log"}}}
    st.update(extra or {})
    _w(d / "run-state.json", st)
    return d


def _stranded(r, now=NOW, **kw):
    kw.setdefault("open_rows", [])
    return bs.stranded_batches(r, now, environ=_env(r), **kw)


def _today_holds(r, now=NOW):
    return bs.started_on(bs.msk_day(bs.now_utc(now)), r, _env(r))


def test_a_failed_batch_without_a_runs_row_is_listed_with_its_row():
    """The real case: Science 2026-10-12T1908Z failed at batch-start, no runs row."""
    r = _root()
    _batch(r)
    got = _stranded(r)
    assert len(got) == 1, got
    b = got[0]
    assert set(b) == KEYS, sorted(b)
    assert b["dir"] == f"pipeline/{A}/{BID}" and b["channel"] == A and b["batch_id"] == BID
    assert b["status"] == "failed" and b["stage"] == "batch-start", b
    assert b["created"] == "2026-10-07T22:15:30Z" and b["updated"] == "2026-10-07T22:30:00Z"
    assert b["reason"].startswith("step 0 (runlog batch-start) exited 2"), b
    assert b["log"] == f"pipeline/{A}/{BID}/logs/batch-start.s0.a0.log", b
    assert b["halt_reason"] is None
    assert [s["id"] for s in b["stages"]] == ORDER
    assert b["stages"][1] == {"id": "batch-start", "status": "failed",
                              "reason": b["reason"]}, b["stages"][1]
    assert b["holds_day"] is False and _today_holds(r) == []
    json.dumps(got)                                    # the screen reads it as JSON


def test_a_runs_row_takes_it_off_the_list():
    for row in ({"batch": f"{A}/{BID}"}, {"id": BID, "channel": A}):
        r = _root()
        _batch(r)
        assert _stranded(r, runs=[row]) == [], row
        _w(r / "pipeline" / "runs.jsonl", json.dumps(row) + "\n")
        assert _stranded(r) == [], row


def test_an_open_batch_is_not_listed_and_a_stale_open_one_is():
    r = _root()
    d = _batch(r, status="halted")
    assert _stranded(r, open_rows=[(d, None, True)]) == []
    assert [b["batch_id"] for b in _stranded(r, open_rows=[(d, None, False)])] == [BID]


def test_stopped_and_halted_are_listed_with_their_stage_and_reason():
    r = _root()
    _batch(r, status="halted", reached=True,
           extra={"current": {"stage": "trend-hunter"}, "halt_reason": "нужен человек: квота"})
    b = _stranded(r)[0]
    assert b["status"] == "halted" and b["stage"] == "trend-hunter", b
    assert b["halt_reason"] == "нужен человек: квота" and b["reason"] == "step 0 exited 1", b
    r = _root()
    _batch(r, status="stopped", reached=True,
           extra={"stops": [{"at": "2026-10-07T22:40:00Z", "by": "user", "stage": "video-editor"}]})
    b = _stranded(r)[0]
    assert b["status"] == "stopped" and b["stage"] == "video-editor", b
    assert b["reason"] == "остановлен user 2026-10-07T22:40:00Z", b


def test_ended_well_running_unrecorded_and_backfill_are_not_listed():
    for status in ("done", "running", "paused", "new"):
        r = _root()
        _batch(r, status=status)
        assert _stranded(r) == [], status
    r = _root()
    d = r / "pipeline" / A / BID
    d.mkdir(parents=True)                              # an old manual batch: no run-state
    _batch(r, parent="backfill")
    assert _stranded(r) == []


def test_holds_day_is_what_started_on_counts_for_today():
    r = _root()
    _batch(r, reached=True)                            # spent quota, today
    assert _stranded(r)[0]["holds_day"] is True
    assert _today_holds(r) == [f"{A} {BID} (pipeline/)"]
    assert _stranded(r, now=NEXT_DAY)[0]["holds_day"] is False
    assert _today_holds(r, NEXT_DAY) == []
    r = _root()
    _batch(r, status="halted")                         # stopped before trend-hunter
    assert _stranded(r)[0]["holds_day"] is False and _today_holds(r) == []
    r = _root()
    _batch(r, parent="rebuilds", reached=True)         # a rebuild never holds the day
    b = _stranded(r)
    assert [x["dir"] for x in b] == [f"pipeline/rebuilds/{BID}"] and b[0]["channel"] == A, b
    assert b[0]["holds_day"] is False and _today_holds(r) == []


def test_the_log_falls_back_to_the_launch_log():
    r = _root()
    d = _batch(r, extra={"runs": {}})
    log = r / "schedule" / "logs" / "2026-10-08-alpha.log"
    _w(r / "schedule" / "launches.jsonl", "".join(json.dumps(x) + "\n" for x in (
        {"at": "2026-10-07T22:15:26Z", "day": "2026-10-08", "channel": A, "pid": 4343,
         "by": "tick", "log": str(r / "schedule" / "logs" / "first.log")},
        {"at": "2026-10-07T22:50:00Z", "day": "2026-10-08", "channel": A, "pid": 1,
         "kind": "resume", "batch": str(d), "log": str(log)},
        {"at": "2026-10-07T23:00:00Z", "day": "2026-10-08", "channel": A, "pid": 2,
         "kind": "resume", "batch": str(d.parent / "other"), "log": "/elsewhere.log"})))
    assert _stranded(r)[0]["log"] == "schedule/logs/2026-10-08-alpha.log"
    r = _root()
    _batch(r, extra={"runs": {}})
    assert _stranded(r)[0]["log"] is None


def test_the_cli_prints_the_stranded_batches():
    r = _root()
    _batch(r)
    out, err = io.StringIO(), io.StringIO()
    assert bs.main(["stranded", "--root", str(r), "--now", NOW, "--json"], out, err) == 0, \
        err.getvalue()
    assert [b["batch_id"] for b in json.loads(out.getvalue())] == [BID]
    out = io.StringIO()
    assert bs.main(["stranded", "--root", str(r), "--now", NOW], out, err) == 0
    assert out.getvalue().startswith(f"pipeline/{A}/{BID}: failed на batch-start"), out.getvalue()
    assert "день не держит" in out.getvalue()
    out = io.StringIO()
    assert bs.main(["stranded", "--root", str(_root()), "--now", NOW], out, err) == 0
    assert out.getvalue().strip() == "застрявших батчей нет"


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:400]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
