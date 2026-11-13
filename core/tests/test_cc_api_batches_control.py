#!/usr/bin/env python3
"""CC-0047: stop and resume with a confirmation in the command center's API
(`api/batches.py` `stop_plan` / `stop`, `resume_plan` / `resume`;
`POST /api/batches/{channel}/{batch_id}/stop/plan`, `.../stop`,
`.../resume/plan`, `.../resume`) over `shared/batch_control.py` (CF-0667).

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_batches.py` (a temp git repository with `reel`). **No real
batch is ever stopped or resumed, no process this file did not start is ever
signalled**:

* the executor is a stand-in this file starts and owns - a script named
  `run_executor.py` under the temp dir that holds `<batch>/run-executor.lock`,
  writes `run-state.json` and sleeps in a session of its own (optionally deaf
  to SIGTERM); a step is a sleeping python whose command line carries its exit
  file (`run_executor.pid_alive`'s token);
* the factory's only signal path (`batch_control._term`) is wrapped by a
  sentry that refuses (raises, sends nothing) any pid or group this file did
  not start; the resume's start (`batch_schedule.spawn_detached`) by a sentry
  that lets through only the stand-in resumer (writes one line, exits 0) of a
  temp root whose schedule state sits under the temp dir;
* `batch_control._notify` is a recorder, never sent; the open batches are
  planted (`FACTORY_KW open_rows`); `grace_s` is small (`FACTORY_KW`).

The factory's *code* is this checkout's, as in production. Nothing is timing-
sensitive: the token's expiry is the module's clock turned forward, the
serialization is a stop held inside the sentry on an `Event` while a second
comes; `LONG` / `grace_s` are only ceilings so a bug fails rather than hangs.

What is pinned:

* the contract names the four routes, version 0.12.0 (CC-0054), `BatchProblem` with
  `confirm_mismatch` / `control_broken`; all four are POSTs behind the guard;
* a plan is the factory's check as is (its Russian `reason`), a token only
  when ok; a stop plan of a batch whose executor is dead, a resume plan of a
  batch whose executor lives - the factory's refusal, no token; an unknown
  batch is a 404; a plan signals and starts nothing;
* the stop: `batch_control.stop(confirmed=True, by "user (центр)")` - SIGTERM
  to the stand-in's group only, `status: stopped` and a `stops` row, the step
  left running, a `run_halted` notice; the token single use; then the resume:
  `batch_control.resume(confirmed=True, by "user (центр)")` - the stand-in
  resumer started detached, a `launches.jsonl` row `kind: resume`, a
  `batch_started` notice; HEAD unchanged;
* `also_step`: bound to the token (a different one at the confirm is
  `confirm_mismatch`), the step gets SIGTERM too and is gone;
* a deaf executor outliving `grace_s`: 200 with `ok: false`, the `kill -9`
  line, status untouched, never SIGKILLed;
* the token: unknown, expired, of another batch, of the other action - each a
  409 and nothing signalled;
* the check again: changed (status) - `check_changed`; the executor died
  since the plan - refused with the factory's own line as is; another batch
  opened since a resume plan - the factory's code `other_batch_open` with the
  center's line before the factory's (CC-0123, 0.52.0);
* the resume's codes (CF-0739 RESUME_CODES): every one the factory has is
  known with a Russian line, the plan carries `code` / `message`, an unknown
  code or none (an older factory) is `refused`; a start that fails is a 409
  `spawn_failed`, nothing launched;
* two confirms of one batch at once: the second is `busy` at once and its
  token is not spent.
"""
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

for _k in ("BATCH_SCHEDULE_STATE_DIR", "NOTIFY_BACKENDS", "NOTIFY_STATE_DIR"):
    os.environ.pop(_k, None)

from test_cc_api_batches import (                    # noqa: E402
    BASE, H, SESSION_HEADER, TMP, _w, client, factory_tree, state)

import api                                           # noqa: E402
from api import batches, factory, paths              # noqa: E402

PY = sys.executable
LONG = 60.0
GRACE = 10.0                # a ceiling: the stand-in dies at once on SIGTERM
BC = factory.batch_control()
BS = factory.batch_schedule()
assert BC.bs is BS, "batch_control must use the factory's batch_schedule"
_N = [0]

FAKE = r'''
import fcntl, json, os, signal, sys, time
from pathlib import Path
batch, root, status = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
step = json.loads(sys.argv[4])
if "deaf" in sys.argv[5:]:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
fh = open(batch / "run-executor.lock", "a+")
fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
fh.seek(0); fh.truncate(); fh.write(f"pid {os.getpid()} since now\n"); fh.flush()
st = {"status": status, "channel": "reel", "root": root, "current": {"stage": "prep"},
      "runs": {}, "stages": {}, "order": [], "executor": {"pid": os.getpid()}}
if step:
    st["current"]["run"] = "prep-1"
    st["runs"]["prep-1"] = {"stage": "prep", "pid": step["pid"], "pgid": step["pid"],
                            "exit_file": "prep-1.exit", "exit": None, "log": "logs/prep-1.log"}
(batch / "run-state.json").write_text(json.dumps(st))
(batch / "ready").write_text("")
time.sleep(300)
'''
RESUMER = _w(TMP / "resumer" / "run_executor.py",
             "import json, sys\n"
             "from pathlib import Path\n"
             "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
             "with open(root / 'schedule' / 'fake-resumed.jsonl', 'a') as fh:\n"
             "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n")

OWNED = set()               # pids (= groups) of the processes this file started
PROCS = []
TERMS = []                  # (pid, pgid) the factory's _term was let to signal
SPAWNS = []
NOTICES = []
HOLD = {}                   # "entered"/"release" Events: hold a stop inside the sentry


# ------------------------------------------------------------------ the sentries
_REAL_TERM = BC._term
_REAL_SPAWN = BS.spawn_detached


def _inside_tmp(p):
    return Path(p).resolve().is_relative_to(TMP.resolve())


def _sentry_term(pid, pgid):
    """The factory's SIGTERM - only to a process (and its group) this file started."""
    if int(pid) not in OWNED or int(pgid or pid) not in OWNED:
        raise AssertionError(f"refused to signal pid {pid} group {pgid}: not this test's")
    TERMS.append((int(pid), int(pgid or pid)))
    if HOLD:
        HOLD["entered"].set()
        assert HOLD["release"].wait(LONG), "never released"
    return _REAL_TERM(pid, pgid)


def _sentry_spawn(argv, root, day, channel, environ=None):
    ok = (len(argv) > 1 and argv[1] == str(RESUMER) and _inside_tmp(root)
          and _inside_tmp(BS.state_dir(root, environ))
          and argv[argv.index("--root") + 1] == str(Path(root).resolve())
          and _inside_tmp(argv[argv.index("--resume") + 1]))
    if not ok:
        raise AssertionError(f"refused to spawn {argv!r} for {root}: not the stand-in")
    SPAWNS.append(list(argv))
    return _REAL_SPAWN(argv, root, day, channel, environ)


def guarded(fn):
    """The sentries, the notice recorder and the injection points around each
    check; the stand-ins it started are killed after (they are this file's)."""
    def run(*a, **k):
        saved = (BC._term, BC._notify, BS.spawn_detached, dict(batches.FACTORY_KW))
        for rec in (TERMS, SPAWNS, NOTICES):
            rec.clear()
        BC._term = _sentry_term
        BC._notify = lambda kind, key, text, channel, root, environ=None: \
            NOTICES.append((kind, key, channel))
        BS.spawn_detached = _sentry_spawn
        batches.FACTORY_KW.clear()
        batches.FACTORY_KW.update(executor=str(RESUMER), open_rows=[], grace_s=GRACE,
                                  take_s=LONG)
        try:
            return fn(*a, **k)
        finally:
            BC._term, BC._notify, BS.spawn_detached = saved[:3]
            batches.FACTORY_KW.clear()
            batches.FACTORY_KW.update(saved[3])
            HOLD.clear()
            for p in PROCS:
                _kill_own(p)
            PROCS.clear()
    run.__name__ = fn.__name__
    return run


def _own(argv):
    p = subprocess.Popen(argv, start_new_session=True, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    OWNED.add(p.pid)
    PROCS.append(p)
    return p


def _kill_own(p):
    """Only a process this file started (its own session)."""
    assert p.pid in OWNED
    if p.poll() is None:
        try:
            os.killpg(p.pid, signal.SIGKILL)
        except OSError:
            pass
    p.wait(timeout=LONG)


def _wait(cond, what):
    end = time.monotonic() + LONG
    while time.monotonic() < end:
        if cond():
            return
        time.sleep(0.05)
    raise AssertionError(what)


def _tree():
    root = factory_tree()
    assert _inside_tmp(BS.state_dir(root)), BS.state_dir(root)     # never the live state
    return root


def _batch(root, bid=None):
    _N[0] += 1
    bid = bid or f"2026-10-10T{_N[0]:04d}Z"
    d = (root / "pipeline" / "reel" / bid)
    d.mkdir(parents=True)
    return d.resolve()


def _executor(root, d, status="running", step=False, deaf=False):
    """A stand-in executor (and step) over `d`, both this file's."""
    s = None
    if step:
        s = _own([PY, "-c", "import time; time.sleep(300)", str(d / "prep-1.exit")])
        _wait(lambda: _alive_step(s.pid, d), "the stand-in step never started")
    exe = TMP / f"fake-{_N[0]}" / "run_executor.py"
    _w(exe, FAKE)
    p = _own([PY, str(exe), str(d), str(root.resolve()), status,
              json.dumps({"pid": s.pid} if s else None), *(["deaf"] if deaf else [])])
    _wait(lambda: (d / "ready").exists(), "the stand-in executor never started")
    return p, s


def _alive_step(pid, d):
    return factory.run_executor().pid_alive(pid, str(d / "prep-1.exit"))


def _halted(d, status="halted"):
    """A batch that stands: its state, no executor."""
    _w(d / "run-state.json", {"status": status, "channel": "reel", "root": str(d.parents[2]),
                              "current": {"stage": "prep"}, "runs": {}, "stages": {},
                              "order": [], "next": "prep"})


def _st(d):
    return json.loads((d / "run-state.json").read_text(encoding="utf-8"))


def _url(d, what):
    return f"/api/batches/reel/{d.name}/{what}"


def _post(c, d, what, body=None):
    return c.post(_url(d, what), headers=H, json=body)


def _plan(c, d, what, body=None):
    r = _post(c, d, f"{what}/plan", body)
    assert r.status_code == 200, r.text
    return r.json()


def _launches(root):
    p = BS.state_dir(root) / BS.LAUNCHES
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_stop_and_resume_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for what in ("stop/plan", "stop", "resume/plan", "resume"):
        path = f"/api/batches/{{channel}}/{{batch_id}}/{what}"
        assert sorted(spec["paths"][path]) == ["post"], spec["paths"][path].keys()
        resp = spec["paths"][path]["post"]["responses"]
        assert "403" in resp, path
        for code in ("404", "409", "500"):
            schema = resp[code]["content"]["application/json"]["schema"]
            got = sorted(s["$ref"].rsplit("/", 1)[1] for s in schema.get("anyOf", [schema]))
            # CC-0058: a write route's 409 may also be `not_working_factory`
            want = ["BatchProblem", "WritesProblem"] if code == "409" else ["BatchProblem"]
            assert got == want, (path, code, got)
    schemas = spec["components"]["schemas"]
    codes = schemas["BatchProblem"]["properties"]["code"]["enum"]
    assert {"confirm_unknown", "confirm_expired", "confirm_mismatch", "check_changed", "busy",
            "refused", "control_broken"} <= set(codes), codes
    assert schemas["StopIn"]["required"] == ["confirm"], schemas["StopIn"]
    assert schemas["ResumeIn"]["required"] == ["confirm"], schemas["ResumeIn"]
    assert {"confirm", "fingerprint", "also_step", "executor_pid", "step", "reason"} <= \
        set(schemas["StopPlan"]["properties"])
    assert {"stopped", "step_killed", "step_left_running", "executor_signalled"} <= \
        set(schemas["StopResult"]["properties"])
    assert {"resumed", "pid", "log", "row", "exit"} <= set(schemas["ResumeResult"]["properties"])
    # CC-0123 (0.52.0): a resume's answers carry the factory's code and the center's line
    for name in ("ResumePlan", "ResumeResult"):
        props = schemas[name]["properties"]
        assert {"code", "message"} <= set(props), name
        assert set(props["code"]["anyOf"][0]["enum"]) == set(batches.RESUME_CODES), name
    assert {"batch_finished", "spawn_failed", "other_batch_open", "no_channel"} <= set(codes)
    assert "code" not in schemas["StopPlan"]["properties"]
    assert batches.CONTROL_BY == "user (центр)"


def test_every_resume_code_has_a_russian_line_and_the_factory_s_code_is_carried():
    assert set(BC.RESUME_CODES) <= set(batches.RESUME_CODES), \
        set(BC.RESUME_CODES) - set(batches.RESUME_CODES)
    for code, line in batches.RESUME_CODES.items():
        assert re.search("[а-яё]", line, re.I), (code, line)
    for code in ("batch_finished", "spawn_failed", "exited_at_once", "no_channel"):
        assert code in BC.RESUME_CODES, code
    assert batches._resume_code({"ok": True, "code": None}) is None
    assert batches._resume_code({"ok": False, "code": "batch_finished"}) == "batch_finished"
    assert batches._resume_code({"ok": False, "code": "brand_new"}) == "refused"
    assert batches._resume_code({"ok": False, "reason": "старая фабрика"}) == "refused"
    assert batches._resume_code({"ok": False, "resumed": True,
                                 "code": "exited_at_once"}) == "exited_at_once"
    f = batches._resume_fault({"ok": False, "code": "spawn_failed", "reason": "не стартовал x"})
    assert (f.status, f.code) == (409, "spawn_failed"), f.code
    assert f.message == batches.RESUME_CODES["spawn_failed"] + " Фабрика: не стартовал x"
    f = batches._resume_fault({"ok": False, "reason": "что-то"})        # an older factory
    assert f.code == "refused" and f.message.endswith("Фабрика: что-то"), f.message
    root = _tree()
    done = _batch(root)
    _halted(done, status="done")
    chk = BC.resume_check(str(done), root, open_rows=[])
    assert chk["code"] == "batch_finished" == batches._resume_code(chk), chk
    nochan = _batch(root)
    _halted(nochan)
    st = _st(nochan)
    st.pop("channel")
    _w(nochan / "run-state.json", st)
    chk = BC.resume_check(str(nochan), root, open_rows=[])
    assert chk["code"] == "no_channel" == batches._resume_code(chk), chk


@guarded
def test_all_four_need_the_session_and_touch_nothing():
    root = _tree()
    d = _batch(root)
    p, _ = _executor(root, d)
    c = client(root)
    before = state(root)
    for what, body in (("stop/plan", {}), ("stop", {"confirm": "x"}), ("resume/plan", None),
                       ("resume", {"confirm": "x"})):
        r = c.post(_url(d, what), headers={"Origin": BASE}, json=body)
        assert r.status_code == 403 and r.json()["guard"] == "session", r.text
        r = c.post(_url(d, what), headers={SESSION_HEADER: "tok"}, json=body)
        assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    assert TERMS == [] and SPAWNS == [] and p.poll() is None
    assert all(t["root"] != str(root.resolve()) for t in batches._TOKENS.values())
    assert state(root) == before and _st(d)["status"] == "running"


# --------------------------------------------------------------------- the plans
@guarded
def test_plans_are_the_factory_s_checks_and_touch_nothing():
    root = _tree()
    c = client(root)
    live = _batch(root)
    p, s = _executor(root, live, step=True)
    stood = _batch(root)
    _halted(stood)
    n_terms, n_spawns = len(TERMS), len(SPAWNS)

    sp = _plan(c, live, "stop")                       # a live executor: ok, a token
    want = BC.stop_check(str(live), root)
    assert sp["ok"] is True and sp["confirm"] and sp["expires_in_s"] == 120, sp
    assert sp["reason"] == want["reason"] and "можно остановить" in sp["reason"], sp
    assert sp["executor_pid"] == p.pid and sp["executor_alive"] is True, sp
    assert sp["step"]["pid"] == s.pid and sp["step"]["alive"] is True, sp
    assert sp["also_step"] is False and sp["action"] == "stop" and sp["channel"] == "reel"
    assert sp["fingerprint"] == batches._control_fingerprint(want), sp
    assert _plan(c, live, "stop", {"also_step": True})["also_step"] is True

    rp = _plan(c, live, "resume")                     # the executor lives: refused, no token
    assert rp["ok"] is False and rp["confirm"] is None, rp
    assert rp["code"] == "executor_alive", rp
    assert rp["message"] == batches.RESUME_CODES["executor_alive"], rp
    assert rp["reason"] == BC.resume_check(str(live), root, open_rows=[])["reason"]
    assert "жив" in rp["reason"], rp

    sp = _plan(c, stood, "stop")                      # nothing lives: refused, no token
    assert sp["ok"] is False and sp["confirm"] is None and "не жив" in sp["reason"], sp
    rp = _plan(c, stood, "resume")                    # stands: ok, a token, the argv
    assert rp["ok"] is True and rp["confirm"], rp
    # CC-0098: the answer through the one cutter - the root named, the batch relative
    assert rp["argv"] == paths.clean([PY, str(RESUMER), "run", "reel", "--root",
                                      str(root.resolve()), "--resume", str(stood)], root), rp
    assert rp["argv"][-3:] == [f".../{root.name}", "--resume",
                               stood.resolve().relative_to(root.resolve()).as_posix()], rp
    assert str(root.resolve()) not in json.dumps(rp), rp
    assert "можно продолжить" in rp["reason"], rp
    assert rp["code"] is None and rp["message"] == rp["reason"], rp

    r = c.post("/api/batches/reel/no-such-batch/stop/plan", headers=H, json={})
    assert r.status_code == 404 and r.json()["code"] == "unknown_batch", r.text
    assert len(TERMS) == n_terms and len(SPAWNS) == n_spawns
    assert p.poll() is None and _st(live)["status"] == "running"
    assert _st(stood)["status"] == "halted" and _launches(root) == []


# --------------------------------------------------------------------- stop, then resume
@guarded
def test_the_stop_then_the_resume():
    root = _tree()
    c = client(root)
    d = _batch(root)
    p, s = _executor(root, d, step=True)
    before = state(root)
    token = _plan(c, d, "stop")["confirm"]
    r = _post(c, d, "stop", {"confirm": token})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ok"] is True and res["stopped"] is True and res["status"] == "stopped", res
    assert res["by"] == "user (центр)" and res["also_step"] is False, res
    assert res["executor_signalled"] == f"группе {p.pid}", res
    assert res["step_left_running"] is True and res["step_killed"] is False, res
    assert f"батч {d.name} остановлен" in res["reason"], res
    assert TERMS == [(p.pid, p.pid)], TERMS                     # the executor's group only
    p.wait(timeout=LONG)
    assert _alive_step(s.pid, d), "the step must live on"
    st = _st(d)
    assert st["status"] == "stopped" and st["stops"][-1]["by"] == "user (центр)", st
    assert [n[0] for n in NOTICES][-1:] == ["run_halted"], NOTICES
    r = _post(c, d, "stop", {"confirm": token})                 # single use
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text

    rp = _plan(c, d, "resume")
    assert rp["ok"] is True and rp["status"] == "stopped", rp
    r = _post(c, d, "resume", {"confirm": rp["confirm"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["resumed"] is True and res["by"] == "user (центр)", res
    assert res["code"] is None and res["message"] == res["reason"], res
    assert res["exit"] == 0 and res["ok"] is True, res          # the stand-in ended at once
    assert res["row"]["kind"] == "resume" and res["row"]["by"] == "user (центр)", res["row"]
    assert res["row"]["batch"] == d.resolve().relative_to(root.resolve()).as_posix(), res["row"]
    assert str(root.resolve()) not in json.dumps(res) and str(root) not in json.dumps(res), res
    assert len(SPAWNS) == 1 and SPAWNS[0][1:] == [str(RESUMER), "run", "reel", "--root",
                                                  str(root.resolve()), "--resume", str(d)]
    rows = _launches(root)
    assert len(rows) == 1 and rows[0]["kind"] == "resume", rows
    lines = (root / "schedule" / "fake-resumed.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])[-2:] == ["--resume", str(d)], lines
    assert [n[0] for n in NOTICES][-1:] == ["batch_started"], NOTICES
    r = _post(c, d, "resume", {"confirm": rp["confirm"]})
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
    assert len(SPAWNS) == 1 and len(TERMS) == 1
    assert state(root)["head"] == before["head"]


@guarded
def test_also_step_is_bound_to_the_token_and_stops_the_step():
    root = _tree()
    c = client(root)
    d = _batch(root)
    p, s = _executor(root, d, step=True)
    token = _plan(c, d, "stop", {"also_step": True})["confirm"]
    r = _post(c, d, "stop", {"confirm": token, "also_step": False})
    assert r.status_code == 409 and r.json()["code"] == "confirm_mismatch", r.text
    assert "вместе с шагом" in r.json()["message"], r.text
    assert TERMS == [] and p.poll() is None                     # nothing signalled, spent
    r = _post(c, d, "stop", {"confirm": token, "also_step": True})
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text

    token = _plan(c, d, "stop", {"also_step": True})["confirm"]
    r = _post(c, d, "stop", {"confirm": token})                 # none: the plan's
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ok"] is True and res["also_step"] is True and res["step_killed"] is True, res
    assert TERMS == [(p.pid, p.pid), (s.pid, s.pid)], TERMS
    s.wait(timeout=LONG)
    p.wait(timeout=LONG)
    assert _st(d)["stops"][-1]["also_step"] is True


@guarded
def test_an_executor_that_outlives_the_grace_is_said_never_killed():
    root = _tree()
    c = client(root)
    d = _batch(root)
    p, _ = _executor(root, d, deaf=True)
    batches.FACTORY_KW["grace_s"] = 0.3
    r = _post(c, d, "stop", {"confirm": _plan(c, d, "stop")["confirm"]})
    assert r.status_code == 200, r.text
    res = r.json()
    assert res["ok"] is False and res["stopped"] is False, res
    assert f"kill -9 -{p.pid}" in res["reason"] and "SIGKILL не" in res["reason"], res
    assert TERMS == [(p.pid, p.pid)] and p.poll() is None       # alive: nothing more sent
    assert _st(d)["status"] == "running" and "stops" not in _st(d)
    assert not [n for n in NOTICES if n[0] == "run_halted"], NOTICES


# --------------------------------------------------------------------- the token
@guarded
def test_a_token_unknown_expired_of_another_batch_or_action_touches_nothing():
    root = _tree()
    c = client(root)
    d = _batch(root)
    p, _ = _executor(root, d)
    other = _batch(root)
    _halted(other)
    for body in ({"confirm": "nope"}, {"confirm": ""}):
        r = _post(c, d, "stop", body)
        assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
        assert "план остановки" in r.json()["message"], r.text
    r = _post(c, d, "resume", {"confirm": "nope"})
    assert r.status_code == 409 and "план продолжения" in r.json()["message"], r.text

    token = _plan(c, d, "stop")["confirm"]                      # expired
    real = batches._clock
    batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
    try:
        r = _post(c, d, "stop", {"confirm": token})
    finally:
        batches._clock = real
    assert r.status_code == 409 and r.json()["code"] == "confirm_expired", r.text

    token = _plan(c, other, "resume")["confirm"]                # of another batch
    r = _post(c, d, "stop", {"confirm": token})
    assert r.status_code == 409 and r.json()["code"] == "confirm_mismatch", r.text
    assert f"продолжения батча reel/{other.name}" in r.json()["message"], r.text
    r = _post(c, other, "resume", {"confirm": token})           # spent by the wrong use
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text

    token = _plan(c, other, "resume")["confirm"]                # of the other action
    r = _post(c, other, "stop", {"confirm": token})
    assert r.status_code == 409 and r.json()["code"] == "confirm_mismatch", r.text

    launch = batches._issue(root, "launch", "reel", "x")        # a launch's token
    r = _post(c, d, "stop", {"confirm": launch})
    assert r.status_code == 409 and r.json()["code"] == "confirm_mismatch", r.text
    assert TERMS == [] and SPAWNS == [] and p.poll() is None
    assert _st(d)["status"] == "running" and _st(other)["status"] == "halted"


# --------------------------------------------------------------------- the check again
@guarded
def test_the_check_again_changed_or_refused_touches_nothing():
    root = _tree()
    c = client(root)
    d = _batch(root)
    p, _ = _executor(root, d)
    token = _plan(c, d, "stop")["confirm"]
    st = _st(d)
    st["status"] = "paused"                                     # still alive, the status moved
    _w(d / "run-state.json", st)
    r = _post(c, d, "stop", {"confirm": token})
    assert r.status_code == 409 and r.json()["code"] == "check_changed", r.text
    assert "батч не остановлен" in r.json()["message"], r.text

    token = _plan(c, d, "stop")["confirm"]
    _kill_own(p)                                                # it died since the plan
    r = _post(c, d, "stop", {"confirm": token})
    assert r.status_code == 409 and r.json()["code"] == "refused", r.text
    assert r.json()["message"] == BC.stop_check(str(d), root)["reason"], r.text
    assert TERMS == []

    token = _plan(c, d, "resume")["confirm"]                    # paused, dead: resumable
    assert token
    busy = (root / "pipeline" / "reel" / "other-open")
    batches.FACTORY_KW["open_rows"] = [(str(busy), None, True)]
    r = _post(c, d, "resume", {"confirm": token})
    # CC-0123 (0.52.0): the factory's code, the center's line, then the factory's
    assert r.status_code == 409 and r.json()["code"] == "other_batch_open", r.text
    assert r.json()["message"].startswith(batches.RESUME_CODES["other_batch_open"]), r.text
    assert "Фабрика: открыт другой батч reel/other-open" in r.json()["message"], r.text
    assert SPAWNS == [] and _launches(root) == []


@guarded
def test_a_resume_that_does_not_start_is_spawn_failed():
    root = _tree()
    c = client(root)
    d = _batch(root)
    _halted(d)
    token = _plan(c, d, "resume")["confirm"]
    assert token

    def no_start(*a, **k):
        raise OSError("no exec here")

    BS.spawn_detached = no_start                    # the guard puts its sentry back
    r = _post(c, d, "resume", {"confirm": token})
    body = r.json()
    assert r.status_code == 409 and body["code"] == "spawn_failed", r.text
    assert body["message"].startswith(batches.RESUME_CODES["spawn_failed"]), body
    assert "no exec here" in body["message"], body
    assert SPAWNS == [] and _launches(root) == [] and _st(d)["status"] == "halted"


# --------------------------------------------------------------------- one at a time
@guarded
def test_two_confirms_of_one_batch_at_once():
    root = _tree()
    c = client(root)
    d = _batch(root)
    p, _ = _executor(root, d)
    t1, t2 = _plan(c, d, "stop")["confirm"], _plan(c, d, "stop")["confirm"]
    HOLD.update(entered=threading.Event(), release=threading.Event())
    out = {}

    def go():
        out["a"] = _post(c, d, "stop", {"confirm": t1})

    a = threading.Thread(target=go)
    a.start()
    try:
        assert HOLD["entered"].wait(LONG), "the first stop never reached the signal"
        r = _post(c, d, "stop", {"confirm": t2})
        assert r.status_code == 409 and r.json()["code"] == "busy", r.text
        assert t2 in batches._TOKENS, "a busy refusal must not spend the token"
    finally:
        HOLD["release"].set()
        a.join(LONG)
    assert out["a"].status_code == 200 and out["a"].json()["stopped"] is True, out["a"].text
    assert len(TERMS) == 1
    HOLD.clear()
    r = _post(c, d, "stop", {"confirm": t2})                    # now: it stands already
    assert r.status_code == 409 and r.json()["code"] == "refused", r.text
    assert len(TERMS) == 1 and p.wait(timeout=LONG) is not None


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
