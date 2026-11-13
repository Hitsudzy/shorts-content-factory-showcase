#!/usr/bin/env python3
"""CC-0044: the batch schedule and the batches of the command center's API
(`api/batches.py`).

Everything runs in-process (starlette's TestClient) against a stand-in
factory: a temp git repository with two channels of its own - `reel` (a slot,
a run plan) and `demo` (a stub, «конвейера нет») - a `pipeline/runs.jsonl`, a
launch journal and batch directories written by the test. The schedule's
state directory is the temp tree's `schedule/` (BATCH_SCHEDULE_STATE_DIR is
taken out of the environment at import; every root is checked to sit under
the temp dir), the tick's timer is looked up under a temp HOME. No batch is
started, no timer installed, nothing of the live factory read or written;
the factory's *code* (`shared/batch_schedule.py`, runs_table, runlog) is this
checkout's, as in production.

What is pinned:

* the contract names the routes, a write needs the session, the problems are
  `BatchProblem`; version 0.12.0 (CC-0045 added the batches going, CC-0046
  the launch, CC-0047 stop and resume, CC-0048 the rebuild);
* the plan: N days, every channel (a stub not plannable, with why), the
  switch, a stale open batch in `stale_open`, the timer's line - on another OS
  the line says it is not checked;
* CC-0147: every plan day carries `kind` (PlanDay's Literal == DAY_KINDS), a
  needs_batch day `covers_days` / `first_empty_slot`, any other [] / null;
* the switch: on needs a note (refused before the factory, nothing written);
  on/off are history rows `by user`, the note «центр: ...»; the writes are the
  gitignored state - HEAD does not move, the tree stays clean, an open batch
  does not refuse them;
* CC-0184 (CF-0922): `batch_feed_days` - the batch threshold apart from the
  horizon `min_feed_days` - in the settings, the PUT and the plan's channel;
  unset it is the factory's effective value, below the horizon the factory's
  refusal (409, its Russian reason in the message);
* a channel's settings: the values and their source, a change through
  `set_channel_settings` (a row by user, «центр: ...»), the factory's Russian
  refusal of a wrong value with nothing written, a stub refused, an unknown
  channel 404;
* the runs: runs.jsonl newest first, by channel, with the launch of its
  channel and Moscow day (or none), the journal's rows, the limit;
* a batch: its markers, the stages they span, an open stage, closed or not,
  its logs/*.log; a log's tail bounded and from a whole line; a name outside
  the listing, a traversal, a symlink out of logs/ and a batch path outside
  pipeline/ are refused;
* nothing here calls `tick` or spawns; `manual_launch` is named only in
  `launch` (CC-0046, tested in `tests/test_cc_api_batches_launch.py`).
"""
import ast
import json
import os
import subprocess
import sys
import types
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)     # the state goes under each temp root
# CC-0127 (CF-0747): an acceptance in a test starts no card build - no model by accident,
# also when a file is run on its own (not through tests/run_tests.py); the state of the
# builds goes under each temp root.
os.environ["PUBLISH_CARD_AUTOBUILD"] = "0"
os.environ.pop("PUBLISH_CARD_STATE_DIR", None)

from fastapi.testclient import TestClient            # noqa: E402

import api                                           # noqa: E402
from _tmproot import tmp_root                        # noqa: E402
from api import batches, factory                     # noqa: E402
from api.app import SESSION_HEADER, create_app       # noqa: E402
from api.settings import Settings                    # noqa: E402

TMP = tmp_root("cc-api-batches-test-")
LOCAL = ("127.0.0.1", 50000)
BASE = "http://127.0.0.1:8790"
H = {"Origin": BASE, SESSION_HEADER: "tok"}
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
_N = [0]


def git(root, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    cp = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, env=env)
    assert cp.returncode == 0, f"git {args}: {cp.stderr}"
    return cp.stdout.strip()


def _w(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False),
                    encoding="utf-8")
    return path


def factory_tree():
    """A stand-in factory root, one commit of everything; `schedule/` ignored
    as in the factory's .gitignore."""
    _N[0] += 1
    root = TMP / f"factory-{_N[0]}"
    _w(root / "channels" / "reel.json", {"channel_id": "reel", "former_channel_ids": ["old-reel"],
                                         "display_name": "Reel", "publisher": {"slot": SLOT},
                                         "run_plan": {"stages": []}})
    _w(root / "channels" / "demo.json", {"channel_id": "demo", "display_name": "Demo",
                                         "status": "no_pipeline",
                                         "status_note": "a stub - milestone 9.9.9",
                                         "batch_schedule": {"enabled": False}})
    _w(root / ".gitignore", "/schedule/\n")
    hooks = TMP / f"no-hooks-{_N[0]}"
    hooks.mkdir()
    git(TMP, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.name", "Test"), ("user.email", "t@example.invalid"),
                 ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))):
        git(root, "config", k, v)
    git(root, "add", "-A")
    git(root, "commit", "-q", "-m", "the start")
    st = factory.batch_schedule().state_dir(root)
    assert st.resolve().is_relative_to(TMP.resolve()), st          # never the live state
    return root


def as_working_factory(root):
    """CC-0058: make a stand-in tree the working factory - a repo whose main checkout
    is on `main` with one commit (`agents_lock.is_working_factory`): the API writes
    only there. Hooks off, nothing global read."""
    root = Path(root)
    hooks = TMP / f"no-hooks-wf-{root.name}-{len(list(TMP.iterdir()))}"
    hooks.mkdir()
    git(TMP, "init", "-q", "-b", "main", str(root))
    for k, v in (("user.name", "Test"), ("user.email", "t@example.invalid"),
                 ("commit.gpgsign", "false"), ("core.hooksPath", str(hooks))):
        git(root, "config", k, v)
    git(root, "add", "-A")
    git(root, "commit", "-q", "--allow-empty", "-m", "the start")
    return root


def client(root):
    return TestClient(create_app(Settings(factory_root=root), token="tok"), client=LOCAL,
                      base_url=BASE)


def _ts(hours_ago=0.0):
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)) \
        .strftime("%Y-%m-%dT%H:%M:%S.000Z")


def write_batch(root, chan, batch, events):
    d = root / "pipeline" / chan / batch
    _w(d / "RUN_EVENTS.jsonl", "".join(json.dumps(e) + "\n" for e in events))
    return d


def marker(status, stage=None, hours_ago=0.0, note=None):
    e = {"ts": _ts(hours_ago), "kind": "marker", "stage": stage, "status": status}
    if note:
        e["note"] = note
    return e


@contextmanager
def temp_home():
    """The tick's timer is looked up under a temp HOME, never the user's."""
    bs = factory.batch_schedule()
    orig = bs.timer_state
    home = TMP / f"home-{_N[0]}"
    bs.timer_state = lambda home_=None: orig(home)
    try:
        yield home
    finally:
        bs.timer_state = orig


def state(root):
    return {"head": git(root, "rev-parse", "HEAD"), "status": git(root, "status", "--porcelain")}


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_schedule_and_batch_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    want = {"/api/schedule": ["get"], "/api/schedule/switch": ["post"],
            "/api/schedule/channels/{channel}": ["get", "put"],
            "/api/batches/history": ["get"],
            "/api/batches/{channel}/{batch_id}/stages": ["get"],
            "/api/batches/{channel}/{batch_id}/logs/{name}": ["get"]}
    for path, methods in want.items():
        assert path in spec["paths"], path
        assert sorted(spec["paths"][path]) == sorted(methods), (path, spec["paths"][path].keys())
        for m in methods:
            resp = spec["paths"][path][m]["responses"]
            assert "403" in resp, (path, m)
            ref = resp["404"]["content"]["application/json"]["schema"]["$ref"]
            assert ref.endswith("/BatchProblem"), ref
    codes = spec["components"]["schemas"]["BatchProblem"]["properties"]["code"]["enum"]
    assert {"note_required", "invalid", "refused", "unknown_batch", "unknown_log"} <= set(codes)


def test_the_writes_need_the_session():
    root = factory_tree()
    c = client(root)
    before = state(root)
    for call in (lambda h: c.post("/api/schedule/switch", headers=h, json={"on": False}),
                 lambda h: c.put("/api/schedule/channels/reel", headers=h,
                                 json={"window": "03:00"})):
        r = call({"Origin": BASE})
        assert r.status_code == 403 and r.json()["guard"] == "session", r.text
        r = call({SESSION_HEADER: "tok"})
        assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    assert not (root / "schedule").exists() and state(root) == before


def _names(node):
    return {n.attr for n in ast.walk(node) if isinstance(n, ast.Attribute)} | \
        {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def test_nothing_here_starts_a_batch_but_the_one_launch():
    """CC-0046 changed this deliberately: `manual_launch` is named in exactly
    one function, `launch` (the user's confirmed «запускай»), `launch_check`
    only in `_check`; the tick and any spawn of a process are never named."""
    tree = ast.parse((ROOT / "api" / "batches.py").read_text(encoding="utf-8"))
    names = _names(tree)
    for bad in ("tick", "_tick", "_spawn", "spawn_detached", "Popen", "run_executor_cmd"):
        assert bad not in names, bad
    assert not [n for n in names if "spawn" in n.lower()], names
    funcs = [f for f in ast.walk(tree) if isinstance(f, ast.FunctionDef)]
    for fname, allowed in (("manual_launch", {"launch"}), ("launch_check", {"_check"})):
        using = {f.name for f in funcs if fname in _names(f)}
        assert using == allowed, (fname, using)


# --------------------------------------------------------------------- the plan
def test_the_plan_is_the_factory_s():
    root = factory_tree()
    write_batch(root, "reel", "2026-10-01T0000Z", [marker("batch-start", hours_ago=30)])
    with temp_home():
        r = client(root).get("/api/schedule", params={"days": 3})
    assert r.status_code == 200, r.text
    p = r.json()
    assert len(p["days"]) == 3 and p["per_day"] == 1, p
    assert all(d["status"] in ("planned", "idle", "busy", "done") for d in p["days"])
    assert set(p["channels"]) == {"reel", "demo"}, p["channels"]
    assert p["channels"]["reel"]["plannable"] is True, p["channels"]["reel"]
    assert p["channels"]["reel"]["settings"]["window"] == "02:00"
    demo = p["channels"]["demo"]
    assert demo["plannable"] is False and "конвейера нет" in demo["why_not"], demo
    assert p["switch"]["on"] is False and "ВЫКЛЮЧЕН" in p["switch"]["line"], p["switch"]
    assert p["stale_open"] == ["reel 2026-10-01T0000Z"], p["stale_open"]
    assert "НЕ установлен" in p["timer"] or "не проверяется" in p["timer"], p["timer"]
    assert "path" not in p["switch"] and "root" not in p
    with temp_home():
        assert client(root).get("/api/schedule").json()["days"].__len__() == 7
    for bad in (0, 32):
        assert client(root).get("/api/schedule", params={"days": bad}).status_code == 422


def test_the_plan_s_days_carry_kind_and_needs_batch_its_covers_and_first_empty_slot():
    """CC-0147 (CF-0785): every day of /api/schedule carries `kind`; a
    needs_batch day carries `covers_days` (the slot days of its fills) and
    `first_empty_slot`; any other kind answers [] and null."""
    root = factory_tree()
    with temp_home():
        r = client(root).get("/api/schedule", params={"days": 3})
    assert r.status_code == 200, r.text
    days = r.json()["days"]
    kinds = set(factory.batch_schedule().DAY_KINDS)
    assert all(d["kind"] in kinds for d in days), days
    need = [d for d in days if d["kind"] == "needs_batch"]
    assert need, days                                   # an empty feed needs a batch
    for d in days:
        if d["kind"] == "needs_batch":
            assert d["status"] == "planned" and d["fills"], d
            assert d["first_empty_slot"] and d["first_empty_slot"].endswith("Z"), d
            assert d["first_empty_slot"] <= d["fills"][0], d
            assert d["covers_days"] == sorted(set(d["covers_days"])) and d["covers_days"], d
            assert all(len(x) == 10 and x[4] == x[7] == "-" for x in d["covers_days"]), d
        else:
            assert d["covers_days"] == [] and d["first_empty_slot"] is None, d


def test_the_plan_day_passes_the_planner_s_fields_through():
    """The route keeps what the planner writes (PlanDay is not extra=allow):
    kind on each day, needs_batch's covers_days / first_empty_slot as given."""
    root = factory_tree()
    fake = [
        {"day": "2026-10-17", "status": "done", "kind": "done_today", "why": "x", "notes": []},
        {"day": "2026-10-18", "status": "planned", "kind": "needs_batch", "channel": "reel",
         "fills": ["2026-10-19T22:00:00Z", "2026-10-20T22:00:00Z"],
         "covers_days": ["2026-10-20", "2026-10-21"],
         "first_empty_slot": "2026-10-18T22:00:00Z", "why": "y", "notes": []},
        {"day": "2026-10-19", "status": "idle", "kind": "fed", "why": "батч не нужен",
         "notes": []}]
    bs = factory.batch_schedule()
    real = bs.plan
    bs.plan = lambda *a, **k: {**real(*a, **k), "days": json.loads(json.dumps(fake))}
    try:
        with temp_home():
            r = client(root).get("/api/schedule", params={"days": 3})
    finally:
        bs.plan = real
    assert r.status_code == 200, r.text
    got = r.json()["days"]
    assert [d["kind"] for d in got] == ["done_today", "needs_batch", "fed"], got
    assert got[1]["covers_days"] == ["2026-10-20", "2026-10-21"], got[1]
    assert got[1]["first_empty_slot"] == "2026-10-18T22:00:00Z", got[1]
    for d in (got[0], got[2]):
        assert d["covers_days"] == [] and d["first_empty_slot"] is None, d


def test_the_plan_carries_the_quota_day_and_a_taken_quota_day_passes_through():
    """CC-0147 (CF-0787, factory 2.12): the plan's quota_day / quota_tz as the
    factory computes them; a quota_day_taken day keeps its status (done or
    idle), its quota_day and next_windows (a null window too); needs_batch
    keeps its quota_day; a kind without one answers null and {}."""
    root = factory_tree()
    bs = factory.batch_schedule()
    with temp_home():
        r = client(root).get("/api/schedule", params={"days": 2})
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["quota_tz"] == "America/Los_Angeles", p["quota_tz"]
    assert p["quota_day"] == bs.quota_day(bs.parse_ts(p["now"])).isoformat(), p
    for d in p["days"]:
        if d["kind"] == "needs_batch":
            assert d["quota_day"] == bs.quota_day(bs.parse_ts(d["window_start"])).isoformat(), d
    fake = [
        {"day": "2026-10-17", "status": "done", "kind": "quota_day_taken", "why": "x",
         "quota_day": "2026-10-16", "next_windows": {"reel": "2026-10-18T06:00:00Z",
                                                      "tech": None}, "notes": ["n"]},
        {"day": "2026-10-18", "status": "idle", "kind": "quota_day_taken", "why": "y",
         "quota_day": "2026-10-17", "next_windows": {"reel": None}, "notes": []},
        {"day": "2026-10-19", "status": "planned", "kind": "needs_batch", "channel": "reel",
         "quota_day": "2026-10-18", "fills": ["2026-10-19T22:00:00Z"],
         "covers_days": ["2026-10-20"], "first_empty_slot": "2026-10-19T22:00:00Z",
         "why": "z", "notes": []},
        {"day": "2026-10-20", "status": "idle", "kind": "fed", "why": "батч не нужен",
         "notes": []}]
    real = bs.plan
    bs.plan = lambda *a, **k: {**real(*a, **k), "quota_day": "2026-10-16",
                               "days": json.loads(json.dumps(fake))}
    try:
        with temp_home():
            r = client(root).get("/api/schedule", params={"days": 4})
    finally:
        bs.plan = real
    assert r.status_code == 200, r.text
    p = r.json()
    assert p["quota_day"] == "2026-10-16" and p["quota_tz"] == "America/Los_Angeles", p
    got = p["days"]
    assert [(d["kind"], d["status"]) for d in got] == [
        ("quota_day_taken", "done"), ("quota_day_taken", "idle"), ("needs_batch", "planned"),
        ("fed", "idle")], got
    assert got[0]["quota_day"] == "2026-10-16" and got[0]["notes"] == ["n"], got[0]
    assert got[0]["next_windows"] == {"reel": "2026-10-18T06:00:00Z", "tech": None}, got[0]
    assert got[1]["next_windows"] == {"reel": None} and got[1]["quota_day"] == "2026-10-17"
    assert got[2]["quota_day"] == "2026-10-18" and got[2]["next_windows"] == {}, got[2]
    assert got[3]["quota_day"] is None and got[3]["next_windows"] == {}, got[3]


def test_the_plan_day_kind_is_the_factory_s_day_kinds():
    """PlanDay.kind's Literal and batch_schedule.DAY_KINDS name the same kinds -
    a kind the factory adds fails here before /api/schedule answers 500."""
    from typing import get_args
    from api.app import PlanDay
    lit = set(get_args(PlanDay.model_fields["kind"].annotation))
    assert lit == set(factory.batch_schedule().DAY_KINDS), lit
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]["PlanDay"]
    assert set(sch["properties"]["kind"]["enum"]) == lit and "kind" in sch["required"], sch


def test_the_timer_on_another_os_is_not_checked():
    real = batches.sys
    batches.sys = types.SimpleNamespace(platform="linux")
    try:
        line = batches.timer_line()
    finally:
        batches.sys = real
    assert "не проверяется" in line and "linux" in line, line


# --------------------------------------------------------------------- the switch
def test_the_switch_on_needs_a_note_and_is_the_user_s():
    root = factory_tree()
    c = client(root)
    before = state(root)
    for body in ({"on": True}, {"on": True, "note": "  "}):
        r = c.post("/api/schedule/switch", headers=H, json=body)
        assert r.status_code == 422 and r.json()["code"] == "note_required", r.text
        assert "включай" in r.json()["message"]
    assert not (root / "schedule" / "switch.json").exists()
    r = c.post("/api/schedule/switch", headers=H, json={"on": True, "note": "«включай» в чате 10.10"})
    assert r.status_code == 200 and r.json()["on"] is True, r.text
    r = c.post("/api/schedule/switch", headers=H, json={"on": False})
    assert r.status_code == 200 and r.json()["on"] is False, r.text
    hist = r.json()["history"]
    assert [(h["action"], h["by"], h["note"]) for h in hist] == [
        ("enable", "user", "центр: «включай» в чате 10.10"), ("disable", "user", "центр")], hist
    assert state(root) == before                     # the state is not git: HEAD stays, tree clean
    with temp_home():
        assert client(root).get("/api/schedule").json()["switch"]["on"] is False


def test_a_broken_switch_file_is_refused_with_the_reason():
    root = factory_tree()
    _w(root / "schedule" / "switch.json", "{not json")
    r = client(root).post("/api/schedule/switch", headers=H, json={"on": False})
    assert r.status_code == 409 and r.json()["code"] == "refused", r.text
    assert any("does not parse" in d for d in r.json()["details"]), r.json()
    assert (root / "schedule" / "switch.json").read_text() == "{not json"


def test_an_open_batch_does_not_refuse_the_state_writes():
    root = factory_tree()
    write_batch(root, "reel", "2026-10-10T0100Z", [marker("batch-start", hours_ago=0.1)])
    c = client(root)
    r = c.post("/api/schedule/switch", headers=H, json={"on": True, "note": "в чате"})
    assert r.status_code == 200 and r.json()["on"], r.text
    r = c.put("/api/schedule/channels/reel", headers=H, json={"min_feed_days": 4})
    assert r.status_code == 200 and r.json()["changed"] == {"min_feed_days": [3, 4]}, r.text
    assert git(root, "rev-list", "--count", "HEAD") == "1"


# --------------------------------------------------------------------- a channel's settings
def test_a_channel_s_settings_and_a_change():
    root = factory_tree()
    c = client(root)
    r = c.get("/api/schedule/channels/reel")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["settings"]["window"] == "02:00" and s["settings"]["enabled"] is True, s
    assert "по умолчанию" in s["settings"]["source"] and s["history"] == [], s
    assert c.get("/api/schedule/channels/old-reel").json()["channel"] == "reel"
    before = state(root)
    r = c.put("/api/schedule/channels/reel", headers=H,
              json={"window": "03:30", "window_hours": 2.5, "enabled": False, "note": "ночью"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["changed"] == {"window": ["02:00", "03:30"], "window_hours": [3, 2.5],
                              "enabled": [True, False]}, got["changed"]
    assert got["settings"]["window"] == "03:30" and got["settings"]["enabled"] is False
    row = got["history"][0]
    assert row["by"] == "user" and row["note"] == "центр: ночью" and row["channel"] == "reel", row
    r = c.put("/api/schedule/channels/reel", headers=H, json={"window": "03:30"})
    assert r.status_code == 200 and r.json()["changed"] == {} and len(r.json()["history"]) == 1
    assert state(root) == before
    assert c.get("/api/schedule/channels/reel").json()["settings"]["overlay"]["window"] == "03:30"


def test_a_wrong_setting_is_the_factory_s_refusal_and_writes_nothing():
    root = factory_tree()
    c = client(root)
    for body, word in (({"window": "25:00"}, "начало окна"), ({"window_hours": 0.3}, "длительность"),
                       ({"min_feed_days": 2.5}, "горизонт ленты"), ({"min_feed_days": 0}, "горизонт")):
        r = c.put("/api/schedule/channels/reel", headers=H, json=body)
        assert r.status_code == 422 and r.json()["code"] == "invalid", (body, r.text)
        assert word in r.json()["message"], (body, r.json())
    assert not (root / "schedule" / "channel-settings.json").exists()
    r = c.put("/api/schedule/channels/demo", headers=H, json={"enabled": True})
    assert r.status_code == 409 and r.json()["code"] == "refused", r.text
    assert any("конвейера нет" in d for d in r.json()["details"]), r.json()
    for call in (lambda: c.get("/api/schedule/channels/nope"),
                 lambda: c.put("/api/schedule/channels/nope", headers=H, json={"enabled": True})):
        r = call()
        assert r.status_code == 404 and r.json()["code"] == "unknown_channel", r.text
        assert "nope" in r.json()["message"]
    assert not (root / "schedule" / "channel-settings.json").exists()


# --------------------------------------------------------------------- CC-0184 (CF-0922)
def _reel_block(root, block):
    """The stand-in's reel gets a `batch_schedule` block of its own, committed."""
    doc = json.loads((root / "channels" / "reel.json").read_text(encoding="utf-8"))
    doc["batch_schedule"] = block
    _w(root / "channels" / "reel.json", doc)
    git(root, "commit", "-q", "-am", "reel: batch_schedule")
    return root


def test_the_contract_carries_batch_feed_days_apart_from_the_horizon():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    for model in ("ScheduleSettings", "ScheduleSettingsEdit", "PlanChannel"):
        assert "batch_feed_days" in sch[model]["properties"], model
        assert "min_feed_days" in sch[model]["properties"], model
    assert "horizon" in sch["ScheduleSettings"]["properties"]["min_feed_days"]["description"]
    assert "batch_feed_days" in sch["PlanDay"]["properties"]["kind"]["description"]


def test_batch_feed_days_unset_is_what_the_factory_says():
    """No key anywhere: the factory's effective value (its default 14, raised to
    the horizon) - the API invents nothing; the overlay does not name it."""
    root = factory_tree()
    c = client(root)
    s = c.get("/api/schedule/channels/reel").json()["settings"]
    assert (s["min_feed_days"], s["batch_feed_days"]) == (3, 14), s
    assert "batch_feed_days" not in s["overlay"], s
    with temp_home():
        p = c.get("/api/schedule", params={"days": 2}).json()
    reel = p["channels"]["reel"]
    assert (reel["min_feed_days"], reel["batch_feed_days"]) == (3, 14), reel
    assert reel["settings"]["batch_feed_days"] == 14, reel["settings"]
    r = c.put("/api/schedule/channels/reel", headers=H, json={"min_feed_days": 20})
    assert r.status_code == 200 and r.json()["changed"] == {"min_feed_days": [3, 20]}, r.text
    assert r.json()["settings"]["batch_feed_days"] == 20, r.json()["settings"]
    r = c.put("/api/schedule/channels/reel", headers=H, json={"batch_feed_days": None})
    assert r.status_code == 200 and r.json()["changed"] == {}, r.text


def test_batch_feed_days_set_reads_writes_and_plans():
    root = _reel_block(factory_tree(), {"batch_feed_days": 7})
    c = client(root)
    s = c.get("/api/schedule/channels/reel").json()["settings"]
    assert (s["min_feed_days"], s["batch_feed_days"]) == (3, 7), s
    r = c.put("/api/schedule/channels/reel", headers=H,
              json={"batch_feed_days": 10, "note": "порог"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["changed"] == {"batch_feed_days": [7, 10]}, got["changed"]
    assert got["settings"]["batch_feed_days"] == 10 and got["settings"]["min_feed_days"] == 3
    assert got["settings"]["overlay"] == {"batch_feed_days": 10}, got["settings"]
    assert got["history"][0]["note"] == "центр: порог" and got["history"][0]["by"] == "user"
    with temp_home():
        reel = c.get("/api/schedule", params={"days": 2}).json()["channels"]["reel"]
    assert (reel["min_feed_days"], reel["batch_feed_days"]) == (3, 10), reel
    assert reel["settings"]["batch_feed_days"] == 10


def test_batch_feed_days_wrong_or_below_the_horizon_is_refused_and_writes_nothing():
    root = factory_tree()
    c = client(root)
    for bad in (2.5, 0, 31):
        r = c.put("/api/schedule/channels/reel", headers=H, json={"batch_feed_days": bad})
        assert r.status_code == 422 and r.json()["code"] == "invalid", (bad, r.text)
        assert "порог батча" in r.json()["message"], (bad, r.json())
    assert not (root / "schedule" / "channel-settings.json").exists()
    r = c.put("/api/schedule/channels/reel", headers=H, json={"batch_feed_days": 2})
    assert r.status_code == 409 and r.json()["code"] == "refused", r.text
    b = r.json()
    assert "порог батча не меньше горизонта ленты" in b["message"], b
    assert "2 дн." in b["message"] and "3 дн." in b["message"], b
    assert any("batch_feed_days 2 < min_feed_days 3" in d for d in b["details"]), b
    assert not (root / "schedule" / "channel-settings.json").exists()
    r = c.put("/api/schedule/channels/reel", headers=H, json={"batch_feed_days": 5})
    assert r.status_code == 200, r.text
    r = c.put("/api/schedule/channels/reel", headers=H, json={"min_feed_days": 6})
    assert r.status_code == 409 and "горизонта ленты" in r.json()["message"], r.text
    assert c.get("/api/schedule/channels/reel").json()["settings"]["min_feed_days"] == 3
    r = c.put("/api/schedule/channels/demo", headers=H, json={"enabled": True})
    assert r.json()["message"] == "Фабрика не приняла настройки расписания канала demo.", r.text


# --------------------------------------------------------------------- the runs
def test_the_runs_say_who_launched_them():
    root = factory_tree()
    rows = [{"batch": "old-reel/2026-10-07T2300Z", "id": "2026-10-07T2300Z", "channel": "old-reel",
             "started": "2026-10-07T23:00:00.000Z", "videos": 3, "wall_s": 7200.0,
             "tokens_total": 5},
            {"batch": "reel/2026-10-09T0900Z", "id": "2026-10-09T0900Z", "channel": "reel",
             "started": "2026-10-09T09:00:00.000Z", "videos": 2, "wall_s": 3600.0},
            {"batch": "demo/2026-10-05T0900Z", "id": "2026-10-05T0900Z", "channel": "demo",
             "started": "2026-10-05T09:00:00.000Z"}]
    _w(root / "pipeline" / "runs.jsonl", "".join(json.dumps(r) + "\n" for r in rows))
    _w(root / "schedule" / "launches.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [
        {"at": "2026-10-07T23:00:00Z", "day": "2026-10-08", "channel": "reel", "by": "tick",
         "why": "лента короче 3 дн.", "pid": 1, "argv": ["x"], "log": "/tmp/x"},
        {"at": "2026-10-01T10:00:00Z", "day": "2026-10-01", "channel": "reel",
         "by": "user (пульт)", "kind": "manual"}]))
    c = client(root)
    r = c.get("/api/batches/history")
    assert r.status_code == 200, r.text
    h = r.json()
    assert [x["id"] for x in h["runs"]] == ["2026-10-09T0900Z", "2026-10-07T2300Z",
                                            "2026-10-05T0900Z"], h["runs"]
    first, second = h["runs"][0], h["runs"][1]
    assert first["launch"] is None, first                       # started by hand in chat
    assert second["channel"] == "reel" and second["tokens_total"] == 5, second
    assert second["launch"]["by"] == "tick" and second["launch"]["day"] == "2026-10-08", second
    assert [x["by"] for x in h["launches"]] == ["tick", "user (пульт)"], h["launches"]
    r = c.get("/api/batches/history", params={"channel": "reel", "limit": 1})
    assert r.status_code == 200 and [x["id"] for x in r.json()["runs"]] == ["2026-10-09T0900Z"]
    assert len(r.json()["launches"]) == 1 and r.json()["channel"] == "reel"
    r = c.get("/api/batches/history", params={"channel": "nope"})
    assert r.status_code == 404 and r.json()["code"] == "unknown_channel"
    assert c.get("/api/batches/history", params={"limit": 0}).status_code == 422
    empty = factory_tree()
    assert client(empty).get("/api/batches/history").json() == {"channel": None, "runs": [],
                                                                "launches": []}


# --------------------------------------------------------------------- a batch
def _a_batch(root):
    d = write_batch(root, "reel", "2026-10-09T0900Z", [
        marker("batch-start", hours_ago=3),
        {"ts": _ts(2.9), "kind": "script", "status": "start", "stage": "trend-hunter", "id": "a"},
        marker("stage-start", "trend-hunter", hours_ago=2.9),
        marker("stage-done", "trend-hunter", hours_ago=2.5),
        marker("stage-start", "video-editor", hours_ago=2.0, note="three videos"),
    ])
    _w(d / "logs" / "slug-attempt-1.log", "".join(f"line {i}\n" for i in range(1000)))
    _w(d / "logs" / "batch-start.s0.a0.log", "started\n")
    _w(d / "logs" / "batch-start.s0.a0.exit", "0\n")
    _w(d / "RUN_LOG.txt", "secret-ish\n")
    return d


def test_a_batch_s_stages_and_logs():
    root = factory_tree()
    d = _a_batch(root)
    c = client(root)
    r = c.get("/api/batches/reel/2026-10-09T0900Z/stages")
    assert r.status_code == 200, r.text
    s = r.json()
    assert s["batch"] == "reel/2026-10-09T0900Z" and s["closed"] is False, s
    assert [m["marker"] for m in s["markers"]] == ["batch-start", "stage-start", "stage-done",
                                                   "stage-start"], s["markers"]
    assert s["markers"][-1]["note"] == "three videos"
    th, ve = s["stages"]
    assert th["stage"] == "trend-hunter" and th["open"] is False and th["done"], th
    assert abs(th["duration_s"] - 0.4 * 3600) < 2, th
    assert ve["stage"] == "video-editor" and ve["open"] and ve["done"] is None, ve
    assert s["open_stages"] == ["video-editor"], s["open_stages"]
    assert [x["name"] for x in s["logs"]] == ["batch-start.s0.a0.log", "slug-attempt-1.log"], s
    with open(d / "RUN_EVENTS.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps(marker("stage-done", "video-editor")) + "\n")
        fh.write(json.dumps(marker("batch-done")) + "\n")
    s = c.get("/api/batches/reel/2026-10-09T0900Z/stages").json()   # the file changed: read again
    assert s["closed"] is True and s["open_stages"] == [] and not s["stages"][-1]["open"], s


def test_a_log_tail_is_bounded_and_starts_at_a_whole_line():
    root = factory_tree()
    _a_batch(root)
    c = client(root)
    url = "/api/batches/reel/2026-10-09T0900Z/logs/slug-attempt-1.log"
    r = c.get(url, params={"bytes": 100})
    assert r.status_code == 200, r.text
    t = r.json()
    assert t["truncated"] and t["text"].startswith("line ") and t["text"].endswith("line 999\n"), t
    assert len(t["text"].encode()) <= 100 and t["offset"] + len(t["text"].encode()) == t["size"]
    whole = c.get(url).json()
    assert not whole["truncated"] and whole["offset"] == 0 and whole["text"].startswith("line 0\n")
    for bad in (0, batches.TAIL_MAX + 1):
        assert c.get(url, params={"bytes": bad}).status_code == 422


def test_a_batch_path_or_log_outside_is_refused():
    root = factory_tree()
    d = _a_batch(root)
    outside = TMP / f"outside-{_N[0]}.log"
    outside.write_text("not the batch's\n", encoding="utf-8")
    (d / "logs" / "escape.log").symlink_to(outside)
    c = client(root)
    names = [x["name"] for x in c.get("/api/batches/reel/2026-10-09T0900Z/stages").json()["logs"]]
    assert "escape.log" not in names, names
    for name in ("escape.log", "batch-start.s0.a0.exit", "..%2FRUN_LOG.txt", "nope.log",
                 "..%2F..%2F..%2Fchannels%2Freel.json"):
        r = c.get(f"/api/batches/reel/2026-10-09T0900Z/logs/{name}")
        assert r.status_code == 404, (name, r.status_code, r.text)
        if r.headers.get("content-type", "").startswith("application/json") and "code" in r.json():
            assert r.json()["code"] == "unknown_log", (name, r.json())
    for ch_, b in (("reel", "nope"), ("nope", "2026-10-09T0900Z"), ("reel", "..%2F..")):
        r = c.get(f"/api/batches/{ch_}/{b}/stages")
        assert r.status_code == 404, (ch_, b, r.text)
    for ch_, b, name in ((".."), "x", None), ("reel", "..", None), ("reel", "a/b", None), \
            ("reel", "2026-10-09T0900Z", "../RUN_LOG.txt"):
        try:
            if name:
                batches.log_tail(root, ch_, b, name)
            else:
                batches.stages(root, ch_, b)
            raise AssertionError(f"taken: {ch_}/{b}/{name}")
        except batches.BatchFault as e:
            assert e.status == 404 and e.code in ("unknown_batch", "unknown_log"), e.code


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
