#!/usr/bin/env python3
"""CC-0123: «повторить батч с выбранной стадии» in the command center's API
(`api/batches.py` `rerun_stages` / `rerun_plan` / `rerun_from`;
`GET /api/batches/{channel}/{batch_id}/rerun-from`, `POST .../rerun-from/plan`,
`POST .../rerun-from`) over `shared/batch_control.py` `rerun_from_check` /
`rerun_from` (CF-0739), and the reopened batch (CF-0739 `open_batches`) in
the list and the stages read.

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_batches.py` (a temp git repository with `reel`, here with a
small run plan of its own) and the sentries of
`tests/test_cc_api_batches_control.py`: the only start a resume may make is
the stand-in resumer of a temp root (`batch_schedule.spawn_detached` wrapped),
no signal leaves (`batch_control._term` wrapped), notices are recorded, the
open batches are planted (`FACTORY_KW open_rows`). No real batch is read,
reset or resumed; no network.

What is pinned:

* the contract: the three routes, version 0.52.0, BatchProblem with every
  rerun code (resume_failed is no refusal), RerunFromPlan / RerunFromResult / RerunFromStages fields,
  BatchStages.open_why and GoingBatch.open_why;
* the stages read: each stage of run-state.json `order` with its status, can
  and the factory's why / the refusal's code; nothing written;
* the plan: the factory's check as is (reset, kept, lines, its reason also as
  why), the code and the center's Russian line of every refusal the factory
  makes here (a handler, an unknown stage, the opener, an earlier failure, a
  stage not run, a live executor, another batch open, a changed plan), a token
  only when ok, no absolute path; nothing written;
* the confirm: the state reset by the factory (backup equal to the state
  before, stages pending, status stopped, next the stage, a manual_resets row
  by user via center with the note), the token single use; with resume the
  stand-in executor started detached (`kind: resume` launch row, pid, log);
* refusals at the confirm: changed (check_changed), the factory's refusal now
  (other_batch_open with its line), a bad note (422 before the token is
  spent), another action's token (confirm_mismatch) - nothing written;
* every rerun code has a Russian line; the factory's own `code` (CF-0739
  RERUN_CODES, every one of them known to the center) is what the center
  answers, and without it (an older factory) each line the factory says maps
  to the same code by its fragments; an unknown code is `refused`;
* a rerun whose resume after it did not go (the start failed): 200, done,
  `code` resume_failed with its Russian line, `resume_code` spawn_failed;
* a batch reopened after batch-done (a stage-start not closed) is open in
  `GET /batches` with the factory's why and not closed in `.../stages`; once
  the stage closes it is closed again.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import (                    # noqa: E402
    TMP, _w, client, git, marker, write_batch)
from test_cc_api_batches_control import (            # noqa: E402
    BC, BS, SPAWNS, _batch, _executor, _launches, _post, _tree, _url, guarded, H)

import api                                           # noqa: E402
from api import batches, factory                     # noqa: E402

RX = factory.run_executor()
RL = factory.runlog()
batches.VIEW_WAIT = 600.0       # the list read waits for its scan


def _step(name):
    return {"argv": ["python3", "{root}/scripts/step.py", name]}


def plan():
    return {"version": 1, "batch_dir": "pipeline/{channel}/{batch_id}", "stages": [
        {"id": "open", "title": "open", "kind": "machine", "owner": "root", "marker": None,
         "steps": [{"argv": ["{runlog}", "batch-start", "--batch", "{batch}"]}]},
        {"id": "prep", "title": "prep", "kind": "machine", "owner": "root", "marker": None,
         "after": ["open"], "produces": ["made-by-prep.json"],
         "steps": [dict(_step("prep"), on_exit={"1": {"run": "fix", "then": "rerun"}})]},
        {"id": "fix", "title": "fix", "kind": "machine", "owner": "root", "marker": None,
         "trigger": "on_exit", "steps": [_step("fix")]},
        {"id": "hunt", "title": "hunt", "kind": "machine", "owner": "root", "marker": None,
         "after": ["prep"], "steps": [_step("hunt")]},
        {"id": "close", "title": "close", "kind": "machine", "owner": "root", "marker": None,
         "after": ["hunt"], "always": True, "steps": [_step("close")]},
    ]}


ORDER = ["open", "prep", "hunt", "close"]


def _root():
    root = _tree()
    cfg = json.loads((root / "channels" / "reel.json").read_text(encoding="utf-8"))
    cfg["run_plan"] = plan()
    _w(root / "channels" / "reel.json", cfg)
    git(root, "commit", "-q", "-am", "the plan")
    return root


def _failed(root, prep="failed", close="done", hunt="skipped"):
    """A batch the executor ended `failed` at prep: its state, a step log, the
    file prep wrote; no executor."""
    d = _batch(root)
    st = {"status": "failed", "channel": "reel", "root": str(root.resolve()), "order": ORDER,
          "plan_fingerprint": RX.fingerprint(plan()), "current": None, "next": None,
          "stages": {"open": {"status": "done"},
                     "prep": {"status": prep, "reason": "step 0 (prep) exited 1"},
                     "hunt": {"status": hunt, "reason": "after failed stage prep"},
                     "close": {"status": close}},
          "runs": {"open.s0.a1": {"stage": "open", "pid": 1, "exit": 0,
                                  "exit_file": "logs/open.s0.a1.exit",
                                  "log": "logs/open.s0.a1.log"},
                   "prep.s0.a1": {"stage": "prep", "pid": 1, "exit": 1,
                                  "exit_file": "logs/prep.s0.a1.exit",
                                  "log": "logs/prep.s0.a1.log"},
                   "fix@prep.s0.a0": {"stage": "fix", "pid": 1, "exit": 0,
                                      "exit_file": "logs/fix.exit", "log": "logs/fix.log"}},
          "reruns": {"prep.s0": 2}}
    if close == "pending":
        st["stages"].pop("close")
    _w(d / "run-state.json", st)
    _w(d / "logs" / "prep.s0.a1.log", "prep failed\n")
    _w(d / "made-by-prep.json", {"x": 1})
    return d


def _bytes(d):
    return (d / "run-state.json").read_bytes()


def _plan(c, d, stage):
    r = _post(c, d, "rerun-from/plan", {"stage": stage})
    assert r.status_code == 200, r.text
    assert str(TMP) not in r.text and str(TMP.resolve()) not in r.text, r.text
    return r.json()


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_rerun_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    base = "/api/batches/{channel}/{batch_id}/rerun-from"
    assert sorted(spec["paths"][base]) == ["get", "post"], spec["paths"][base].keys()
    assert sorted(spec["paths"][base + "/plan"]) == ["post"]
    for path in (base, base + "/plan"):
        resp = spec["paths"][path]["post"]["responses"]
        assert "403" in resp and "409" in resp and "404" in resp, (path, resp.keys())
    schemas = spec["components"]["schemas"]
    codes = set(schemas["BatchProblem"]["properties"]["code"]["enum"])
    want = set(batches.RERUN_CODES) - {"resume_failed"}
    assert want <= codes, want - codes
    assert "resume_failed" not in codes
    assert {"reset", "reset_status", "keys", "logs", "kept", "lines", "code", "message", "why",
            "stages_for_rerun", "fingerprint", "confirm", "expires_in_s", "from_stage"} <= \
        set(schemas["RerunFromPlan"]["properties"])
    assert schemas["RerunFromPlanIn"]["required"] == ["stage"]
    assert schemas["RerunFromIn"]["required"] == ["confirm"]
    assert {"note", "resume"} <= set(schemas["RerunFromIn"]["properties"])
    assert {"done", "backup", "row", "resume", "resumed", "pid", "log", "resume_ok",
            "resume_reason", "resume_code", "by", "via"} <= \
        set(schemas["RerunFromResult"]["properties"])
    assert "resume_failed" in schemas["RerunFromResult"]["properties"]["code"]["anyOf"][0]["enum"]
    assert {"stage", "status", "can", "why", "code"} == set(schemas["RerunStage"]["properties"])
    assert "stages_for_rerun" in schemas["RerunFromStages"]["properties"]
    assert "open_why" in schemas["BatchStages"]["properties"]
    assert "open_why" in schemas["GoingBatch"]["properties"]
    assert (batches.RERUN_BY, batches.RERUN_VIA) == ("user", "center")


def test_every_code_has_a_russian_line_and_the_factory_s_lines_map_to_their_codes():
    for code, line in batches.RERUN_CODES.items():
        assert re.search("[а-яё]", line, re.I), (code, line)
    assert set(BC.RERUN_CODES) <= set(batches.RERUN_CODES), \
        set(BC.RERUN_CODES) - set(batches.RERUN_CODES)
    for code in ("no_channel", "resume_failed"):
        assert code in batches.RERUN_CODES and code in BC.RERUN_CODES, code

    def code_of(chk):
        """The center's code of the answer - off the factory's `code`, and the same
        off its line alone (an older factory: no `code`)."""
        got = batches._rerun_code(chk)
        if chk.get("ok"):
            assert chk.get("code") is None, chk
        else:
            assert chk.get("code") == got, (chk.get("code"), got, chk.get("reason"))
        old = batches._rerun_code({k: v for k, v in chk.items() if k != "code"})
        assert old == got, (old, got, chk.get("reason"))
        return got

    root = _root()
    d = _failed(root)
    ask = lambda *a, **k: code_of(BC.rerun_from_check(str(d), *a, **k))  # noqa: E731
    assert ask("prep", root, open_rows=[]) is None
    assert ask("prep", root, open_rows=[], by="") == "bad_who"
    assert ask("prep", root, open_rows=[], via="x" * 41) == "bad_who"
    assert ask("fix", root, open_rows=[]) == "stage_handler"
    assert ask("nope", root, open_rows=[]) == "stage_unknown"
    assert ask("open", root, open_rows=[]) == "stage_opens_batch"
    assert ask("hunt", root, open_rows=[]) == "earlier_failed"
    other = _batch(root)
    assert ask("prep", root, open_rows=[(str(other), None, True)]) == "other_batch_open"
    assert code_of(BC.rerun_from_check(str(_batch(root)), "prep", root,
                                       open_rows=[])) == "no_state"
    res = BC.rerun_from(str(d), "prep", "user", "center", confirmed=False, root=root,
                        open_rows=[])
    assert code_of(res) == "not_confirmed", res["reason"]
    res = BC.rerun_from(str(d), "prep", "user", "center", confirmed=True, root=root,
                        open_rows=[], note="a\nb")
    assert code_of(res) == "bad_note", res["reason"]
    pend = _failed(root, prep="done", hunt="done", close="pending")
    assert code_of(BC.rerun_from_check(str(pend), "close", root,
                                       open_rows=[])) == "stage_not_run"
    nochan = _failed(root)
    st = json.loads(_bytes(nochan))
    st.pop("channel")
    _w(nochan / "run-state.json", st)
    assert code_of(BC.rerun_from_check(str(nochan), "prep", root,
                                       open_rows=[])) == "no_channel"
    # the factory's code wins over the line; an unknown one is refused
    assert batches._rerun_code({"ok": False, "code": "stage_unknown",
                                "reason": "открыт другой батч x"}) == "stage_unknown"
    assert batches._rerun_code({"ok": False, "code": "brand_new", "reason": "x"}) == "refused"
    f = batches._rerun_fault({"ok": False, "code": "brand_new", "reason": "что-то"})
    assert f.code == "refused" and "factory code: brand_new" in f.details, f.details
    # a done rerun whose resume did not go: resume_failed with and without the code
    done = {"ok": False, "done": True, "resume": {"ok": False, "code": "spawn_failed"}}
    assert batches._rerun_code(dict(done, code="resume_failed")) == "resume_failed"
    assert batches._rerun_code(done) == "resume_failed"
    assert batches._rerun_code({"ok": False, "posix": False, "reason": "x"}) == "not_posix"
    assert batches._rerun_code({"ok": False, "reason": "что-то новое"}) == "refused"
    assert batches._rerun_code({"ok": False, "reason": "отказ: lock"}) == "locked"


# --------------------------------------------------------------------- the reads
@guarded
def test_the_stages_read_offers_each_stage_with_the_factory_s_why():
    root = _root()
    d = _failed(root)
    before = _bytes(d)
    c = client(root)
    r = c.get(_url(d, "rerun-from"))
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["status"] == "failed" and got["has_state"] is True, got
    rows = {s["stage"]: s for s in got["stages_for_rerun"]}
    assert [s["stage"] for s in got["stages_for_rerun"]] == ORDER
    assert rows["open"]["can"] is False and rows["open"]["code"] == "stage_opens_batch"
    assert rows["prep"] == {"stage": "prep", "status": "failed", "can": True,
                            "why": rows["prep"]["why"], "code": None}, rows["prep"]
    assert "повтор с prep" in rows["prep"]["why"], rows["prep"]
    assert rows["hunt"]["status"] == "skipped" and rows["hunt"]["code"] == "earlier_failed"
    assert rows["close"]["code"] == "earlier_failed"
    assert _bytes(d) == before and not SPAWNS
    empty = _batch(root)
    got = c.get(_url(empty, "rerun-from")).json()
    assert got["has_state"] is False and got["stages_for_rerun"] == [], got
    assert c.get("/api/batches/reel/nope/rerun-from").status_code == 404


@guarded
def test_the_plan_is_the_factory_s_check_with_a_code_and_a_token_only_when_ok():
    root = _root()
    d = _failed(root)
    before = _bytes(d)
    c = client(root)
    p = _plan(c, d, "prep")
    assert p["ok"] is True and p["code"] is None and p["confirm"], p
    assert p["expires_in_s"] == 120 and p["why"] == p["reason"], p
    assert p["reset"] == ["prep", "hunt", "close"], p["reset"]
    assert p["reset_status"] == {"prep": "failed", "hunt": "skipped", "close": "done"}
    assert p["keys"]["runs"] == ["fix@prep.s0.a0", "prep.s0.a1"], p["keys"]
    assert p["keys"]["reruns"] == ["prep.s0"], p["keys"]
    assert p["kept"] == [{"path": "made-by-prep.json", "stage": "prep"}], p["kept"]
    assert p["logs"] == ["logs/fix.log", "logs/prep.s0.a1.log"], p["logs"]
    assert p["lines"] and all(isinstance(x, str) for x in p["lines"])
    assert "Можно повторить со стадии prep: 3 стад." in p["message"], p["message"]
    assert [s["stage"] for s in p["stages_for_rerun"]] == ORDER
    assert p["action"] == "rerun-from" and p["from_stage"] == "prep"
    for stage, code in (("fix", "stage_handler"), ("nope", "stage_unknown"),
                        ("open", "stage_opens_batch"), ("hunt", "earlier_failed")):
        q = _plan(c, d, stage)
        assert q["ok"] is False and q["code"] == code and q["confirm"] is None, (stage, q)
        assert q["message"] == batches.RERUN_CODES[code] and q["why"], q
    batches.FACTORY_KW["open_rows"] = [(str(_batch(root)), None, True)]
    q = _plan(c, d, "prep")
    assert q["code"] == "other_batch_open" and "открыт другой батч" in q["why"], q
    assert q["confirm"] is None
    batches.FACTORY_KW["open_rows"] = []
    assert _bytes(d) == before and not SPAWNS
    r = _post(c, d, "rerun-from/plan", {"stage": ""})
    assert r.status_code == 422, r.text


@guarded
def test_a_live_executor_and_a_changed_plan_refuse():
    root = _root()
    d = _batch(root)
    _executor(root, d, status="running")
    c = client(root)
    q = _plan(c, d, "prep")
    assert q["code"] == "executor_alive" and q["executor_alive"] is True, q
    assert q["message"] == batches.RERUN_CODES["executor_alive"] and q["confirm"] is None
    d2 = _failed(root)
    cfg = json.loads((root / "channels" / "reel.json").read_text(encoding="utf-8"))
    cfg["run_plan"]["stages"][-1]["title"] = "close, renamed"
    _w(root / "channels" / "reel.json", cfg)
    q = _plan(c, d2, "prep")
    assert q["code"] == "plan_changed" and q["confirm"] is None, q


# --------------------------------------------------------------------- the confirm
@guarded
def test_the_confirm_resets_the_batch_and_the_token_is_single_use():
    root = _root()
    d = _failed(root)
    before = json.loads(_bytes(d))
    c = client(root)
    p = _plan(c, d, "prep")
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"], "note": "ингест убит 13.10"})
    assert r.status_code == 200, r.text
    assert str(TMP.resolve()) not in r.text, r.text
    res = r.json()
    assert res["ok"] is True and res["done"] is True and res["code"] is None, res
    assert (res["by"], res["via"]) == ("user", "center")
    assert res["resume_asked"] is False and res["resumed"] is False and res["pid"] is None
    assert res["resume_ok"] is None and res["resume"] is None
    assert "Чтобы прогнать их, нажмите «Продолжить»" in res["message"], res["message"]
    st = json.loads(_bytes(d))
    assert st["status"] == "stopped" and st["next"] == "prep", st
    assert all(st["stages"][s] == {"status": "pending"} for s in ("prep", "hunt", "close"))
    assert st["stages"]["open"]["status"] == "done"
    assert set(st["runs"]) == {"open.s0.a1"} and st["reruns"] == {}, st["runs"]
    row = st["manual_resets"][-1]
    assert (row["by"], row["via"], row["from"], row["why"]) == \
        ("user", "center", "prep", "ингест убит 13.10"), row
    backup = d / row["backup"]
    assert json.loads(backup.read_text(encoding="utf-8")) == before
    assert res["backup"].endswith(row["backup"]) and not res["backup"].startswith("/")
    assert (d / "made-by-prep.json").is_file()                  # kept, not deleted
    assert not SPAWNS and not _launches(root)
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"]})
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text


@guarded
def test_the_confirm_with_resume_starts_the_executor_detached():
    root = _root()
    d = _failed(root)
    c = client(root)
    p = _plan(c, d, "prep")
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"], "resume": True})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["resume_asked"] is True and res["resumed"] is True, res
    assert res["resume_ok"] is True and res["ok"] is True, res
    assert res["code"] is None and res["resume_code"] is None, res
    assert isinstance(res["pid"], int) and res["log"] and not res["log"].startswith("/"), res
    assert f"Исполнитель запущен (pid {res['pid']})" in res["message"], res["message"]
    assert len(SPAWNS) == 1 and SPAWNS[0][SPAWNS[0].index("--resume") + 1] == str(d), SPAWNS
    rows = _launches(root)
    assert rows and rows[-1]["kind"] == "resume" and rows[-1]["by"] == "user", rows
    assert json.loads(_bytes(d))["manual_resets"][-1]["via"] == "center"


@guarded
def test_a_resume_after_the_rerun_that_does_not_start_is_resume_failed():
    root = _root()
    d = _failed(root)
    c = client(root)
    p = _plan(c, d, "prep")

    def no_start(*a, **k):
        raise OSError("no exec here")

    BS.spawn_detached = no_start                    # the guard puts its sentry back
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"], "resume": True})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["done"] is True and res["ok"] is False, res
    assert res["code"] == "resume_failed" and res["resume_code"] == "spawn_failed", res
    assert res["resume"]["code"] == "spawn_failed" and res["resumed"] is False, res
    assert res["resume_ok"] is False and "no exec here" in res["resume_reason"], res
    assert batches.RERUN_CODES["resume_failed"] in res["message"], res["message"]
    assert batches.RESUME_CODES["spawn_failed"] in res["message"], res["message"]
    st = json.loads(_bytes(d))
    assert st["status"] == "stopped" and st["next"] == "prep", st
    assert not SPAWNS and not _launches(root)


@guarded
def test_refusals_at_the_confirm_touch_nothing():
    root = _root()
    d = _failed(root)
    c = client(root)
    # changed since the plan, still ok: check_changed
    p = _plan(c, d, "prep")
    st = json.loads(_bytes(d))
    st["runs"]["hunt.s0.a1"] = {"stage": "hunt", "pid": 1, "exit": 0, "exit_file": "h.exit",
                                "log": "logs/hunt.log"}
    _w(d / "run-state.json", st)
    before = _bytes(d)
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"]})
    assert r.status_code == 409 and r.json()["code"] == "check_changed", r.text
    assert _bytes(d) == before
    # the factory refuses now: its code, the center's line and the factory's
    p = _plan(c, d, "prep")
    batches.FACTORY_KW["open_rows"] = [(str(_batch(root)), None, True)]
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"]})
    body = r.json()
    assert r.status_code == 409 and body["code"] == "other_batch_open", r.text
    assert body["message"].startswith(batches.RERUN_CODES["other_batch_open"])
    assert "Фабрика: открыт другой батч" in body["message"], body
    assert _bytes(d) == before
    batches.FACTORY_KW["open_rows"] = []
    # a bad note: 422 before the token is spent - the same token then goes
    p = _plan(c, d, "prep")
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"], "note": "a\nb"})
    assert r.status_code == 422 and r.json()["code"] == "bad_note", r.text
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"], "note": "x" * 501})
    assert r.status_code == 422, r.text
    assert _bytes(d) == before
    # another action's token: confirm_mismatch, spent, nothing done
    rp = _post(c, d, "resume/plan").json()
    assert rp["ok"] is True, rp
    r = _post(c, d, "rerun-from", {"confirm": rp["confirm"]})
    assert r.status_code == 409 and r.json()["code"] == "confirm_mismatch", r.text
    assert "повтора батча со стадии" in r.json()["message"], r.text
    assert _bytes(d) == before and not SPAWNS
    r = _post(c, d, "rerun-from", {"confirm": p["confirm"]})
    assert r.status_code == 200 and r.json()["done"] is True, r.text


# --------------------------------------------------------------------- reopened (CF-0739)
def test_a_batch_reopened_after_batch_done_is_open_until_its_stage_closes():
    root = _tree()
    bid = "2026-10-13T1411Z"
    events = [marker("batch-start", hours_ago=2), marker("stage-start", "s1", 1.9),
              marker("stage-done", "s1", 1.8), marker("batch-done", hours_ago=1.7),
              marker("stage-start", "s2", 0.1)]
    d = write_batch(root, "reel", bid, events)
    _w(d / "run-state.json", {"status": "failed", "channel": "reel", "order": ["s1", "s2"],
                              "stages": {"s1": {"status": "done"}, "s2": {"status": "running"}}})
    c = client(root)
    why = RL.REOPENED_WHY.format(stage="s2")
    st = c.get(f"/api/batches/reel/{bid}/stages").json()
    assert st["closed"] is False and st["open_why"] == why, st
    rows = [b for b in c.get("/api/batches").json()["batches"] if b["batch_id"] == bid]
    assert len(rows) == 1 and rows[0]["open_why"] == why, rows
    stranded = c.get("/api/batches/stranded").json()["batches"]
    assert bid not in [b.get("batch_id") for b in stranded], stranded
    _w(d / "RUN_EVENTS.jsonl", "".join(json.dumps(e) + "\n" for e in
                                       events + [marker("stage-done", "s2", 0.05)]))
    st = c.get(f"/api/batches/reel/{bid}/stages").json()
    assert st["closed"] is True and st["open_why"] is None, st
    root2 = _tree()
    d2 = write_batch(root2, "reel", bid, events[:3])
    st = client(root2).get(f"/api/batches/reel/{bid}/stages").json()
    assert st["closed"] is False and st["open_why"] == "нет batch-done", st
    rows = client(root2).get("/api/batches").json()["batches"]
    assert [b["open_why"] for b in rows if b["batch_id"] == bid] == ["нет batch-done"], rows
    assert d2.is_dir()


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
