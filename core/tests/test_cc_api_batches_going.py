#!/usr/bin/env python3
"""CC-0045: the batches going in the command center's API (`api/batches.py`) -
the list, one batch, its events by byte cursor.

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_batches.py` (a temp git repository with `reel` and
`demo`), with batch directories, `run-state.json`, `RUN_EVENTS.jsonl`,
`pipeline/runs.jsonl` and a journal of questions planted by the test. No
batch is started, resumed or stopped, nothing is signalled but the one
stand-in process this test starts itself (a `python -c sleep` whose command
line carries the exit file's path, so `pid_alive` says yes) - killed by its
own handle at the end. The factory's *code* (collect, runlog, run_executor,
needs_you) is this checkout's, as in production.

Nothing is timing-sensitive: the list's times are compared with what
`collect.batches` gives at the answer's own `as_of`; "a read did not wait"
is proved by the read coming back while the stand-in scan is held on an
`Event`, never by a stopwatch (`LONG` is only a ceiling so a bug fails).

What is pinned:

* the contract names the three routes, version 0.12.0 (CC-0054), `BatchProblem`;
* the list is `collect.batches` (stage, elapsed, `timeout_min`, the
  estimate from the mean wall) plus the path form `batch`; a stale batch is in
  it with `fresh: false`; a stopped one (CF-0667) with its status; the times
  are as of `as_of`;
* the list is a kept scan: the first read waits for it, a later one past
  VIEW_TTL answers the last result at once (`checking: true`) and one refresh
  runs; a failed scan is a 500 `scan_broken`;
* one batch: run-state.json whole (stops too), every process with `alive`
  (a live stand-in yes, an exited one and a dead pid no), its channel's live
  questions only; no run-state: `state: null`; a broken one: `state_error`;
* the events: the tail; from 0 by `limit`, `next` goes on, `more`; a line
  being written waits for the next poll; a cursor inside a line goes to the
  next whole one; a cursor past the end is the tail with `reset`; an
  unparsable line is `text`; the read is bounded (EVENTS_BYTES_MAX) and a
  line longer than it is stepped over; a batch with no events file is empty;
* nothing here stops or signals (the one launch: CC-0046's tests).
"""
import ast
import json
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import (                    # noqa: E402
    _w, _ts, client, factory_tree, marker, write_batch)

import api                                           # noqa: E402
from api import batches, factory                     # noqa: E402

LONG = 120.0
batches.VIEW_TTL = 0.0          # the tests write batches between two reads:
batches.VIEW_WAIT = 600.0       # every read rescans and waits for it
BID = "2026-10-09T0900Z"


def ny():
    return factory.needs_you()


def plan_reel(root):
    """reel with a run plan whose video-editor has a ceiling."""
    _w(root / "channels" / "reel.json",
       {"channel_id": "reel", "former_channel_ids": ["old-reel"], "display_name": "Reel",
        "run_plan": {"stages": [{"id": "trend-hunter"},
                                {"id": "video-editor", "timeout_min": 90}]}})
    _w(root / "pipeline" / "runs.jsonl",
       "".join(json.dumps(r) + "\n" for r in (
           {"id": "a", "channel": "reel", "wall_s": 3000},
           {"id": "b", "channel": "old-reel", "wall_s": 5000},
           {"id": "c", "channel": "demo", "wall_s": 99})))


def run_state(d, **kw):
    doc = {"version": 1, "task": "CF-0203", "channel": "reel", "batch": str(d),
           "batch_id": d.name, "order": ["trend-hunter", "video-editor"], "status": "running",
           "created": _ts(3), "current": {"stage": "video-editor", "run": "video-editor.s0"},
           "next": None,
           "stages": {"trend-hunter": {"status": "done"},
                      "video-editor": {"status": "running", "started": _ts(2)}},
           "handlers": {}, "decisions": {}, "runs": {}, "reruns": {"video-editor.s0": 1},
           "needs_human": [{"stage": "video-editor", "key": "k", "took": "default"}],
           "executor": {}}
    doc.update(kw)
    _w(d / "run-state.json", doc)
    return doc


def going_batch(root, bid=BID, **kw):
    d = write_batch(root, "reel", bid, [
        marker("batch-start", hours_ago=3),
        marker("stage-start", "trend-hunter", hours_ago=2.9),
        marker("stage-done", "trend-hunter", hours_ago=2.5),
        marker("stage-start", "video-editor", hours_ago=2.0)])
    run_state(d, **kw)
    return d


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for path in ("/api/batches", "/api/batches/{channel}/{batch_id}",
                 "/api/batches/{channel}/{batch_id}/events"):
        assert sorted(spec["paths"].get(path, {})) == ["get"], path
        resp = spec["paths"][path]["get"]["responses"]
        assert "403" in resp, path
        assert resp["500"]["content"]["application/json"]["schema"]["$ref"] \
            .endswith("/BatchProblem"), path
    params = {p["name"]: p for p in
              spec["paths"]["/api/batches/{channel}/{batch_id}/events"]["get"]["parameters"]}
    assert {"after", "limit"} <= set(params), params
    codes = spec["components"]["schemas"]["BatchProblem"]["properties"]["code"]["enum"]
    assert "scan_broken" in codes, codes


def test_nothing_here_stops_or_signals_but_the_one_stop_and_resume():
    """CC-0047 changed this deliberately: `batch_control.stop` is called in
    exactly one function (`stop`), `batch_control.resume` in one (`resume`),
    the checks only in `_control_check`; nothing in `api/` signals or starts a
    process itself (no os.kill / killpg / signal / Popen / spawn)."""
    for f in sorted((ROOT / "api").glob("*.py")):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)} | \
            {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
        mods = {a.name for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))
                for a in n.names} | {n.module for n in ast.walk(tree)
                                     if isinstance(n, ast.ImportFrom) and n.module}
        for bad in ("tick", "_spawn", "Popen", "kill", "killpg", "send_signal", "_term",
                    "cmd_run", "cmd_stop", "cmd_resume", "stop_batch", "resume_batch",
                    "spawn_detached", "SIGTERM", "SIGKILL"):
            assert bad not in names, (f.name, bad)
        assert not [n for n in names if "spawn" in n.lower()], (f.name, names)
        assert "signal" not in mods, (f.name, mods)
        # `subprocess.run` of git (channels), the re-run under .venv (__main__) and
        # the one runner of the read children (child: `subprocess.run(timeout=)`,
        # which ends only its own child - agents status, the archive's dry run,
        # the ending's reader; it names no Popen / kill / signal either) only
        assert "subprocess" not in mods or f.name in ("channels.py", "__main__.py",
                                                      "child.py"), f.name
    tree = ast.parse((ROOT / "api" / "batches.py").read_text(encoding="utf-8"))
    funcs = [f for f in tree.body if isinstance(f, ast.FunctionDef)]

    def calling(attr):
        return {f.name for f in funcs if any(
            isinstance(n, ast.Attribute) and n.attr == attr and isinstance(n.value, ast.Name)
            and n.value.id == "bc" for n in ast.walk(f))}
    assert calling("stop") == {"stop"}, calling("stop")
    assert calling("resume") == {"resume"}, calling("resume")
    assert calling("stop_check") == calling("resume_check") == {"_control_check"}
    # CC-0048 changed this deliberately: the rebuild is the user's confirmed
    # «пересобрать» - `bc.rebuild` only in `rebuild`, `bc.rebuild_check` only in
    # `_rebuild_check`; the run plan read only for the modes
    assert calling("rebuild") == {"rebuild"}, calling("rebuild")
    assert calling("rebuild_check") == {"_rebuild_check"}, calling("rebuild_check")
    # CC-0123 changed this deliberately: «повторить со стадии» is the user's
    # confirmed rerun - `bc.rerun_from` only in `rerun_from` (its resume after
    # is the factory's own), `bc.rerun_from_check` only in `_rerun_check`
    assert calling("rerun_from") == {"rerun_from"}, calling("rerun_from")
    assert calling("rerun_from_check") == {"_rerun_check"}, calling("rerun_from_check")
    # every other `.stop` / `.resume` attribute - none
    for attr, allowed in (("stop", {"stop"}), ("resume", {"resume"}), ("rebuild", {"rebuild"})):
        using = {f.name for f in funcs if attr in {n.attr for n in ast.walk(f)
                                                   if isinstance(n, ast.Attribute)}}
        assert using == allowed, (attr, using)
    # CC-0046: the one launch (`launch`, manual_launch) is pinned in
    # test_cc_api_batches.py::test_nothing_here_starts_a_batch_but_the_one_launch


# --------------------------------------------------------------------- the list
def test_the_list_is_the_console_s():
    root = factory_tree()
    plan_reel(root)
    going_batch(root)
    going_batch(root, "2026-10-08T0900Z", status="stopped",
                stops=[{"at": _ts(1), "by": "user", "note": "stop"}])
    write_batch(root, "reel", "2026-10-01T0000Z", [marker("batch-start", hours_ago=30)])
    write_batch(root, "reel", "2026-09-30T0000Z", [marker("batch-start", hours_ago=40),
                                                   marker("batch-done", hours_ago=39)])
    r = client(root).get("/api/batches")
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["checking"] is False and got["checked_at"] and got["poll_s"] == batches.LIST_POLL_S
    ids = [b["batch_id"] for b in got["batches"]]
    assert ids == ["2026-10-01T0000Z", "2026-10-08T0900Z", BID], ids     # the closed one: no
    stale, stopped, cur = got["batches"]
    assert stale["open_why"] == "нет batch-done", stale             # CC-0123: OpenRow.why
    assert stale["fresh"] is False and stale["batch"] == "reel/2026-10-01T0000Z", stale
    assert stopped["status"] == "stopped" and stopped["fresh"] is True, stopped
    assert cur["status"] == "running" and cur["stage"] == "video-editor", cur
    assert cur["stage_timeout_min"] == 90 and cur["batch"] == f"reel/{BID}", cur
    assert cur["needs_human"] == ["video-editor: default"], cur
    assert cur["estimate"]["mean_wall_s"] == 4000 and cur["estimate"]["runs"] == 2, cur
    assert cur["estimate"]["left_s"] == 4000 - cur["elapsed_s"], cur
    # exactly collect's numbers at the answer's own moment - no formula of the API
    col, rl = factory.collect(), factory.runlog()
    now = col.now_utc(got["as_of"])
    want = col.batches(root, now, open_rows=rl.open_batches(root, now=now))
    for w in want:
        w["batch"] = f"{Path(w['dir']).parent.name}/{w['batch_id']}"
    want = json.loads(json.dumps(want))
    assert len(got["batches"]) == len(want)
    added = {"executor_alive", "lock_held", "executor_why",           # CC-0110, pinned below
             "open_why",                                              # CC-0123: OpenRow.why
             "code_edits_count"}                                      # CC-0111 (CF-0713)
    for g, w in zip(got["batches"], want):
        g = dict(g, stages=[{k: v for k, v in s.items() if k != "reason"}
                            for s in g["stages"]] if g.get("stages") is not None else None)
        assert {k: g[k] for k in w} == w, (g, w)
        assert all(g[k] is None for k in set(g) - set(w) - added), (g, w)  # the model's empty
        assert g["executor_alive"] is False and g["lock_held"] is False, g  # no lock file
        assert g["executor_why"] is None, g
    assert 3 * 3600 - 5 <= cur["elapsed_s"] <= 3 * 3600 + 600, cur["elapsed_s"]


def test_the_list_never_waits_past_the_first_scan():
    root = factory_tree()
    calls, held, entered = [0], threading.Event(), threading.Event()

    def scan(r):
        calls[0] += 1
        if calls[0] > 1:
            entered.set()
            assert held.wait(LONG)
        return {"as_of": f"scan-{calls[0]}", "batches": [
            {"batch": "reel/x", "dir": "pipeline/reel/x", "batch_id": "x", "fresh": True}]}

    saved = batches._view_scan, batches.VIEW_TTL, batches.VIEW_WAIT
    batches._view_scan, batches.VIEW_TTL, batches.VIEW_WAIT = scan, 0.0, 0.0
    try:
        c = client(root)
        first = c.get("/api/batches").json()                 # nothing known: waits once
        assert first["as_of"] == "scan-1" and calls[0] == 1, first
        second = c.get("/api/batches").json()                # past the TTL: no wait
        assert entered.wait(LONG)
        assert second["as_of"] == "scan-1", second
        third = c.get("/api/batches").json()
        assert third["as_of"] == "scan-1" and third["checking"] is True, third
        assert calls[0] == 2, calls                          # one refresh for both reads
        held.set()
        st = batches._VIEWS[str(Path(root).resolve())]
        with batches.channels._SCAN_COND:
            batches.channels._SCAN_COND.wait_for(lambda: not st.running, timeout=LONG)
        batches.VIEW_TTL = 3600.0
        assert c.get("/api/batches").json()["as_of"] == "scan-2"
    finally:
        held.set()
        batches._view_scan, batches.VIEW_TTL, batches.VIEW_WAIT = saved


def test_a_broken_scan_is_a_batch_problem():
    root = factory_tree()

    def scan(r):
        raise OSError("pipeline unreadable")

    saved = batches._view_scan
    batches._view_scan = scan
    try:
        r = client(root).get("/api/batches")
    finally:
        batches._view_scan = saved
    assert r.status_code == 500 and r.json()["code"] == "scan_broken", r.text
    assert "pipeline unreadable" in r.json()["details"][0], r.json()


STANDIN = r'''
import fcntl, os, sys, time
from pathlib import Path
batch = Path(sys.argv[1])
fh = open(batch / "run-executor.lock", "a+")
fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
fh.seek(0); fh.truncate(); fh.write(f"pid {os.getpid()} since now\n"); fh.flush()
(batch / "ready").write_text("")
time.sleep(600)
'''


def test_the_list_and_a_batch_say_whether_the_executor_lives():
    """CC-0110: `executor_alive`, `lock_held`, `executor_why` - batch_control.
    executor_of and executor_lock.why, in the list (the kept scan) and in one
    batch: no lock file; a lock this test holds itself under its own pid (an
    unknown holder: not run_executor.py); a stand-in `run_executor.py` that
    holds it (alive) - killed by its own handle."""
    import fcntl
    import time
    root = factory_tree()
    plan_reel(root)
    free = going_batch(root, "2026-10-09T0700Z")
    held = going_batch(root, "2026-10-09T0800Z")
    live = going_batch(root)
    fh = open(held / "run-executor.lock", "a+")
    fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    fh.write(f"pid {__import__('os').getpid()} since now\n")
    fh.flush()
    script = _w(root / "standin" / "run_executor.py", STANDIN)
    proc = subprocess.Popen([sys.executable, str(script), str(live)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        end = time.monotonic() + LONG
        while not (live / "ready").exists():
            assert time.monotonic() < end and proc.poll() is None, "the stand-in did not start"
            time.sleep(0.05)
        c = client(root)
        got = {b["batch_id"]: b for b in c.get("/api/batches").json()["batches"]}
        one = {d.name: c.get(f"/api/batches/reel/{d.name}").json() for d in (free, held, live)}
        bc = factory.batch_control()
        want = {d.name: bc.executor_of(str(d)) for d in (free, held, live)}
    finally:
        proc.kill()
        proc.wait()
        fh.close()
    for name, ex in want.items():
        for src in (got[name], one[name]):
            assert src["executor_alive"] is ex["alive"] and src["lock_held"] is ex["lock_held"], \
                (name, src, ex)
    assert want[free.name] == dict(want[free.name], alive=False, lock_held=False)
    assert got[free.name]["executor_why"] is None is one[free.name]["executor_why"]
    assert want[held.name]["lock_held"] is True and want[held.name]["alive"] is False
    for src in (got[held.name], one[held.name]):
        assert "держит не исполнитель" in src["executor_why"], src
    assert want[live.name]["alive"] is True, want
    for src in (got[live.name], one[live.name]):
        assert src["executor_why"] == f"исполнитель жив (pid {proc.pid})", src


def test_the_list_s_stages_carry_their_reason():
    """CC-0110: GoingStage.reason - run-state.json `stages[id].reason`, null
    where the executor wrote none."""
    root = factory_tree()
    plan_reel(root)
    going_batch(root, status="failed", current=None,
                stages={"trend-hunter": {"status": "failed",
                                         "reason": "step 0 (x) exited 2; log logs/t.s0.a0.log"},
                        "video-editor": {"status": "skipped",
                                         "reason": "after failed stage trend-hunter"}})
    b = client(root).get("/api/batches").json()["batches"][0]
    assert b["stages"] == [
        {"id": "trend-hunter", "status": "failed",
         "reason": "step 0 (x) exited 2; log logs/t.s0.a0.log"},
        {"id": "video-editor", "status": "skipped",
         "reason": "after failed stage trend-hunter"}], b["stages"]
    root = factory_tree()
    plan_reel(root)
    going_batch(root)
    b = client(root).get("/api/batches").json()["batches"][0]
    assert [s["reason"] for s in b["stages"]] == [None, None], b["stages"]


# --------------------------------------------------------------------- one batch
def test_one_batch_whole_with_its_processes_and_questions():
    root = factory_tree()
    plan_reel(root)
    d = going_batch(root, stops=[{"at": _ts(1), "by": "user", "kind": "stop"}])
    exit_live = d / "logs" / "video-editor.s0.exit"
    exit_live.parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)",
                             str(exit_live)], stdin=subprocess.DEVNULL,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        st = json.loads((d / "run-state.json").read_text(encoding="utf-8"))
        st["runs"] = {
            "video-editor.s0": {"stage": "video-editor", "argv": ["x"], "pid": proc.pid,
                                "pgid": proc.pid, "started": _ts(2),
                                "log": "logs/video-editor.s0.log",
                                "exit_file": "logs/video-editor.s0.exit", "exit": None,
                                "ended": None, "restarts": 0},
            "trend-hunter.s0": {"stage": "trend-hunter", "pid": proc.pid,
                                "exit_file": "logs/video-editor.s0.exit", "exit": 0,
                                "ended": _ts(2.5)},
            "gone.s0": {"stage": "trend-hunter", "pid": dead.pid,
                        "exit_file": "logs/gone.s0.exit", "exit": None}}
        _w(d / "run-state.json", st)
        n = ny()
        n.add("monitor", "alert:reel:1", "нарушение на reel", channel="old-reel",
              root=root, notify=False)
        n.add("monitor", "alert:demo:1", "нарушение на demo", channel="demo",
              root=root, notify=False)
        q, _ = n.add("archive", "archive:reel", "решено", channel="reel", root=root,
                     notify=False)
        n.resolve(q["id"], root=root)
        r = client(root).get(f"/api/batches/reel/{BID}")
        assert r.status_code == 200, r.text
        got = r.json()
    finally:
        proc.kill()
        proc.wait()
    assert got["batch"] == f"reel/{BID}" and got["channel"] == "reel", got
    assert got["dir"] == f"pipeline/reel/{BID}" and got["status"] == "running", got
    s = got["state"]
    assert s["stops"] == st["stops"] and s["reruns"] == {"video-editor.s0": 1}, s
    assert s["needs_human"] == st["needs_human"] and s["handlers"] == {}, s   # whole
    assert s["runs"]["video-editor.s0"]["alive"] is True, s["runs"]
    assert s["runs"]["trend-hunter.s0"]["alive"] is False                  # exited
    assert s["runs"]["gone.s0"]["alive"] is False                          # pid gone
    assert got["alive"] == ["video-editor.s0"], got["alive"]
    assert [x["text"] for x in got["questions"]] == ["нарушение на reel"], got["questions"]
    assert got["questions"][0]["channel"] == "reel", got["questions"]


def test_a_batch_without_or_with_a_broken_run_state():
    root = factory_tree()
    write_batch(root, "reel", BID, [marker("batch-start", hours_ago=1)])
    c = client(root)
    got = c.get(f"/api/batches/reel/{BID}").json()
    assert got["state"] is None and got["state_error"] is None and got["alive"] == [], got
    assert got["channel"] == "reel", got
    _w(root / "pipeline" / "reel" / BID / "run-state.json", "{not json")
    got = c.get(f"/api/batches/reel/{BID}").json()
    assert got["state"] is None and "не читается" in got["state_error"], got
    for path in ("/api/batches/reel/nope", "/api/batches/nope/x", "/api/batches/reel/..%2F.."):
        r = c.get(path)
        assert r.status_code == 404, (path, r.text)


def test_a_batch_s_quiet_decisions_with_and_without_the_key():
    """CC-0120 (CF-0735): run-state.json `quiet[]` as the answer's own `quiet`
    (and in `state`), paths cut; [] when the key is not there or no state."""
    root = factory_tree()
    plan_reel(root)
    d = going_batch(root)
    c = client(root)
    got = c.get(f"/api/batches/reel/{BID}").json()
    assert got["quiet"] == [] and got["state"].get("quiet") is None, got
    line = (f"studio-read: Studio не читали, лог {root}/pipeline/reel/{BID}/logs/x.log - "
            f"никто не ждёт (CF-0317), взято по умолчанию «skip»")
    row = {"stage": "studio-read", "key": "studio-read", "line": line, "took": "skip",
           "at": "2026-10-13T14:11:00Z"}
    run_state(d, quiet=[row, "not a row"],
              decisions={"studio-read": {"outcome": "skip", "by": "default (human, quiet)"}})
    got = c.get(f"/api/batches/reel/{BID}").json()
    assert len(got["quiet"]) == 1 and got["state"]["quiet"] == got["quiet"], got
    q = got["quiet"][0]
    assert (q["stage"], q["key"], q["took"], q["at"]) == \
        ("studio-read", "studio-read", "skip", "2026-10-13T14:11:00Z"), q
    assert str(root) not in q["line"] and f"pipeline/reel/{BID}/logs/x.log" in q["line"], q
    write_batch(root, "reel", "2026-10-09T1000Z", [marker("batch-start", hours_ago=1)])
    got = c.get("/api/batches/reel/2026-10-09T1000Z").json()
    assert got["state"] is None and got["quiet"] == [], got


# --------------------------------------------------------------------- the events
def _events_file(root, n=10, tail=b""):
    d = root / "pipeline" / "reel" / BID
    d.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"ts": f"t{i}", "kind": "script", "i": i}) + "\n" for i in range(n)]
    data = "".join(lines).encode() + tail
    (d / "RUN_EVENTS.jsonl").write_bytes(data)
    return d / "RUN_EVENTS.jsonl", data


def test_events_by_cursor():
    root = factory_tree()
    path, data = _events_file(root, 10)
    c = client(root)
    url = f"/api/batches/reel/{BID}/events"
    t = c.get(url, params={"limit": 3}).json()                       # no cursor: the tail
    assert [e["event"]["i"] for e in t["events"]] == [7, 8, 9], t
    assert t["next"] == len(data) == t["size"] and t["more"] is False, t
    assert t["poll_s"] == batches.EVENTS_POLL_S and t["reset"] is False
    got, after = [], 0
    for _ in range(5):
        a = c.get(url, params={"after": after, "limit": 4}).json()
        got += [e["event"]["i"] for e in a["events"]]
        for e in a["events"]:
            assert data[e["offset"]:].startswith(json.dumps(e["event"]).encode()), e
        after = a["next"]
        if not a["more"]:
            break
    assert got == list(range(10)) and after == len(data), (got, after)
    assert c.get(url, params={"after": after}).json()["events"] == []      # nothing new
    with open(path, "ab") as fh:                                         # a line being written
        fh.write(b'{"ts": "t10", "kind": "scr')
    a = c.get(url, params={"after": after}).json()
    assert a["events"] == [] and a["next"] == after and a["more"] is False, a
    with open(path, "ab") as fh:
        fh.write(b'ipt", "i": 10}\nnot json at all\n')
    a = c.get(url, params={"after": after}).json()
    assert [e["event"] and e["event"]["i"] for e in a["events"]] == [10, None], a
    assert a["events"][1]["text"] == "not json at all", a
    mid = data.index(b"\n", 5) - 3                                       # inside line 0
    a = c.get(url, params={"after": mid, "limit": 1}).json()
    assert a["events"][0]["event"]["i"] == 1, a                          # the next whole line
    big = path.stat().st_size + 100
    a = c.get(url, params={"after": big, "limit": 2}).json()             # replaced file
    assert a["reset"] is True and a["events"][-1]["text"] == "not json at all", a
    for bad in ({"after": -1}, {"limit": 0}, {"limit": batches.EVENTS_LIMIT_MAX + 1}):
        assert c.get(url, params=bad).status_code == 422, bad


def test_events_read_is_bounded():
    root = factory_tree()
    path, data = _events_file(root, 400)
    saved = batches.EVENTS_BYTES_MAX
    batches.EVENTS_BYTES_MAX = 1000
    try:
        c = client(root)
        url = f"/api/batches/reel/{BID}/events"
        a = c.get(url, params={"after": 0, "limit": 1000}).json()
        assert 0 < a["next"] <= 1000 and a["more"] is True, (a["next"], a["more"])
        assert a["events"][0]["event"]["i"] == 0
        assert len(a["events"]) == a["events"][-1]["event"]["i"] + 1
        t = c.get(url, params={"limit": 1000}).json()                    # the tail: last KB only
        assert t["events"][-1]["event"]["i"] == 399 and len(t["events"]) < 40, len(t["events"])
        with open(path, "ab") as fh:                                     # one line > a read
            fh.write(json.dumps({"kind": "x", "blob": "z" * 5000}).encode() + b"\n")
            fh.write(b'{"kind": "after", "i": 400}\n')
        a = c.get(url, params={"after": len(data)}).json()
        assert len(a["events"]) == 1 and a["events"][0]["event"] is None, a
        assert len(a["events"][0]["text"]) <= batches.LINE_TEXT_MAX and a["more"] is True, a
        b = c.get(url, params={"after": a["next"]}).json()
        assert [e["event"]["i"] for e in b["events"]] == [400], b
    finally:
        batches.EVENTS_BYTES_MAX = saved


def test_events_of_a_batch_with_none_yet():
    root = factory_tree()
    (root / "pipeline" / "reel" / BID).mkdir(parents=True)
    a = client(root).get(f"/api/batches/reel/{BID}/events", params={"after": 0}).json()
    assert a["events"] == [] and a["next"] == 0 and a["size"] == 0 and not a["more"], a


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
