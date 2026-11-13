#!/usr/bin/env python3
"""CC-0046: the launch with a confirmation in the command center's API
(`api/batches.py` `launch_plan` / `launch`, `POST /api/batches/launch/plan`
and `POST /api/batches/launch`).

In-process (starlette's TestClient) against the stand-in factory of
`tests/test_cc_api_batches.py` (a temp git repository with `reel` and the
stub `demo`). **No real batch is ever started**: the factory's own injection
points (`batches.FACTORY_KW`: `executor=` a stand-in script that writes one
line and exits, `open_rows=` planted) are filled around every check (`guarded`), and the factory's
`spawn_detached` is wrapped by a sentry that refuses (raises, starts nothing)
any argv that is not the stand-in's or any root / state directory outside the
temp dir. The schedule's state directory is each temp root's `schedule/`
(BATCH_SCHEDULE_STATE_DIR taken out of the environment, every one checked to
sit under the temp dir); the `batch_started` notice is recorded by a stand-in
of `batch_schedule._notify`, never sent. The factory's *code*
(`shared/batch_schedule.py` `launch_check` / `manual_launch`) is this
checkout's, as in production.

Nothing is timing-sensitive: the token's expiry is the module's clock turned
forward (`batches._clock`), the serialization is proved by a launch held
inside the factory's spawn on an `Event` while a second one comes, never by
a stopwatch (`LONG` is only a ceiling so a bug fails rather than hangs).

What is pinned:

* the contract names the two routes, version 0.12.0 (CC-0054), `BatchProblem` with the
  confirm codes; both are POSTs behind the guard (Origin + X-CC-Session);
* the plan is `launch_check` (guards, argv, skipped) plus a token only when
  ok; a stub's plan is the factory's Russian refusal and no token; a former
  channel id is resolved; an unknown channel is a 404; the plan starts nothing;
* the launch: `manual_launch(confirmed=True, by "user (центр)")` - the
  stand-in executor started detached, the answer at once with pid, log
  (`schedule/logs/`) and the `launches.jsonl` row; the root's HEAD and tree
  unchanged; the token is single use; after it the plan says «1 батч в
  сутки» as the factory says it;
* the token: unknown, spent, of another channel, expired - each a 409 and
  nothing started; a token of another channel is spent too;
* the check again: a batch opened since the plan, or the day's batch
  started - refused with the factory's own line as is; the check otherwise
  changed (argv) - `check_changed`; nothing started;
* two confirms at once: one starts, the other is refused - one spawn, one row;
* production fills no injection point (`FACTORY_KW = {}` in the source);
* CC-0176 (CF-0899): logged in or not - the factory's `login_state` on a
  stand-in `RUN_EXECUTOR_CLAUDE` (a /bin/sh script printing the json of
  `claude auth status`, never the real CLI): logged in - the launch starts and
  answers `login`; not logged in - 409 `not_logged_in` with the factory's line,
  nothing spawned, no row; unknown - the launch starts, `login.ok` null and its
  line the warning; the plan tells `login` and keeps its token.
"""
import ast
import functools
import json
import os
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
    BASE, H, SESSION_HEADER, TMP, _w, client, factory_tree, git, state)

import api                                           # noqa: E402
from api import batches, factory, paths              # noqa: E402

LONG = 120.0
BS = factory.batch_schedule()
FAKE = _w(TMP / "fake_executor.py",
          "import json, sys\n"
          "from pathlib import Path\n"
          "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
          "with open(root / 'schedule' / 'fake-launched.jsonl', 'a') as fh:\n"
          "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n")
FAKE2 = _w(TMP / "fake_executor_2.py", FAKE.read_text(encoding="utf-8"))
FAKES = {str(FAKE), str(FAKE2)}
SPAWNS = []                 # every argv the sentry let through
NOTICES = []


# ------------------------------------------------------------------ the sentries
_REAL_SPAWN = BS.spawn_detached


def _inside_tmp(p):
    return Path(p).resolve().is_relative_to(TMP.resolve())


def _sentry_spawn(argv, root, day, channel, environ=None):
    """The factory's spawn, only for the stand-in executor of a temp root."""
    ok = (len(argv) > 1 and argv[1] in FAKES and _inside_tmp(root)
          and _inside_tmp(BS.state_dir(root, environ))
          and argv[argv.index("--root") + 1] == str(root))
    if not ok:
        raise AssertionError(f"refused to spawn {argv!r} for {root}: not the stand-in")
    SPAWNS.append(list(argv))
    return _REAL_SPAWN(argv, root, day, channel, environ)


def guarded(fn):
    """Each check runs with the sentries in place and leaves nothing behind
    (pytest runs every file in one process: the console's own tests use the
    same `batch_schedule` module): the spawn sentry, the notice recorder, the
    stand-in executor and planted open rows in FACTORY_KW."""
    @functools.wraps(fn)
    def run(*a, **k):
        saved = (BS.spawn_detached, BS._notify, dict(batches.FACTORY_KW))
        BS.spawn_detached = _sentry_spawn
        BS._notify = lambda kind, key, text, channel, root: NOTICES.append((kind, key, channel))
        batches.FACTORY_KW.clear()
        batches.FACTORY_KW.update(executor=str(FAKE), open_rows=[])
        try:
            return fn(*a, **k)
        finally:
            BS.spawn_detached, BS._notify = saved[0], saved[1]
            batches.FACTORY_KW.clear()
            batches.FACTORY_KW.update(saved[2])
    return run


def _tree():
    root = factory_tree()
    assert _inside_tmp(BS.state_dir(root)), BS.state_dir(root)     # never the live state
    assert os.environ.get("BATCH_SCHEDULE_STATE_DIR") is None
    return root


def _kw(**over):
    kw = dict(executor=str(FAKE), open_rows=[])
    kw.update(over)
    return kw


class _Kw:
    """FACTORY_KW changed for a block, restored after."""

    def __init__(self, **over):
        self.over = over

    def __enter__(self):
        self.saved = dict(batches.FACTORY_KW)
        batches.FACTORY_KW.update(self.over)

    def __exit__(self, *exc):
        batches.FACTORY_KW.clear()
        batches.FACTORY_KW.update(self.saved)


def _launches(root):
    p = BS.state_dir(root) / BS.LAUNCHES
    return [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()] if p.is_file() else []


def _ran(root, n=1):
    """The stand-in's lines once `n` are there (LONG is only a ceiling)."""
    p = root / "schedule" / "fake-launched.jsonl"
    end = time.monotonic() + LONG
    while time.monotonic() < end:
        if p.is_file():
            lines = [x for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
            if len(lines) >= n:
                return [json.loads(x) for x in lines]
        time.sleep(0.05)
    raise AssertionError(f"the stand-in executor did not run under {root}")


def _plan(c, channel="reel"):
    r = c.post("/api/batches/launch/plan", headers=H, json={"channel": channel})
    assert r.status_code == 200, r.text
    return r.json()


def _launch(c, token, channel="reel"):
    return c.post("/api/batches/launch", headers=H, json={"channel": channel, "confirm": token})


def _nothing_started(root, spawns_before):
    assert len(SPAWNS) == spawns_before, SPAWNS[spawns_before:]
    assert _launches(root) == [], _launches(root)


def _today_line(root, channel="reel"):
    chk = BS.launch_check(channel, root, **_kw())
    g = {x["name"]: x for x in chk["guards"]}
    return chk, g


def _bare(guards):
    """The guards without `batches` (CC-0110: the API's; CF-0724: launch_check's
    `open` / `today` carry their own too - `test_a_guard_names_its_batches`)."""
    return [{k: v for k, v in g.items() if k != "batches"} for g in guards]


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_launch_routes():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for path in ("/api/batches/launch/plan", "/api/batches/launch"):
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
    assert {"confirm_unknown", "confirm_expired", "confirm_channel", "check_changed", "busy",
            "refused"} <= set(codes), codes
    assert {"channel", "confirm"} <= set(schemas["LaunchIn"]["required"]), schemas["LaunchIn"]
    assert {"confirm", "guards", "argv", "skipped", "fingerprint"} <= \
        set(schemas["LaunchPlan"]["properties"])


def test_production_fills_no_injection_point():
    tree = ast.parse((ROOT / "api" / "batches.py").read_text(encoding="utf-8"))
    got = [n.value for n in tree.body if isinstance(n, ast.Assign)
           and any(isinstance(t, ast.Name) and t.id == "FACTORY_KW" for t in n.targets)]
    assert len(got) == 1 and isinstance(got[0], ast.Dict) and not got[0].keys, got
    assert batches.LAUNCH_BY == "user (центр)"


@guarded
def test_both_routes_need_the_session_and_start_nothing():
    root = _tree()
    c = client(root)
    before, n = state(root), len(SPAWNS)
    for path, body in (("/api/batches/launch/plan", {"channel": "reel"}),
                       ("/api/batches/launch", {"channel": "reel", "confirm": "x"})):
        r = c.post(path, headers={"Origin": BASE}, json=body)
        assert r.status_code == 403 and r.json()["guard"] == "session", r.text
        r = c.post(path, headers={SESSION_HEADER: "tok"}, json=body)
        assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
        r = c.post(path, headers={"Origin": "http://evil.example", SESSION_HEADER: "tok"},
                   json=body)
        assert r.status_code == 403 and r.json()["guard"] == "origin", r.text
    assert not batches._TOKENS or all(t["root"] != str(root.resolve())
                                      for t in batches._TOKENS.values())
    _nothing_started(root, n)
    assert state(root) == before


# --------------------------------------------------------------------- the plan
@guarded
def test_the_plan_is_launch_check_with_a_token_and_starts_nothing():
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    p = _plan(c)
    want = BS.launch_check("reel", root, **_kw())
    assert p["ok"] is True and p["why"] == want["why"] == "все защиты пройдены", p
    assert _bare(p["guards"]) == _bare(want["guards"]) and p["skipped"] == want["skipped"], p
    assert [g["name"] for g in p["guards"]] == ["run_plan", "voice", "open", "today", "pause"], \
        p["guards"]   # CF-0659: `voice` - a TODO placeholder voice refuses
    # CC-0098: the answer through the one cutter - no absolute path of the machine
    assert p["argv"] == paths.clean(want["argv"], root), p["argv"]
    assert p["argv"][1] == ".../" + FAKE.name and str(root) not in json.dumps(p), p["argv"]
    assert p["argv"][2:4] == ["run", "reel"] and p["today"] == want["today"], p
    assert isinstance(p["confirm"], str) and len(p["confirm"]) >= 24, p
    assert p["expires_in_s"] == int(batches.CONFIRM_TTL) == 120, p
    assert p["fingerprint"] == batches._fingerprint(want), p
    p2 = _plan(c, "old-reel")                         # a former id is the channel
    assert p2["channel"] == "reel" and p2["confirm"] != p["confirm"], p2
    _nothing_started(root, n)
    assert not (root / "schedule" / "fake-launched.jsonl").exists()


@guarded
def test_a_stub_s_plan_is_the_factory_s_refusal_without_a_token():
    root = _tree()
    c = client(root)
    p = _plan(c, "demo")
    want = BS.launch_check("demo", root, **_kw())
    assert p["ok"] is False and p["confirm"] is None and p["expires_in_s"] is None, p
    assert p["why"] == want["why"] and "run_plan" in p["why"], p
    r = c.post("/api/batches/launch/plan", headers=H, json={"channel": "nope"})
    assert r.status_code == 404 and r.json()["code"] == "unknown_channel", r.text


@guarded
def test_a_todo_voice_s_plan_is_the_voice_guard_without_a_token():
    """CF-0659: a channel whose voice is still a TODO placeholder is refused by
    launch_check's `voice` guard - the plan says so, with no token."""
    root = _tree()
    doc = json.loads((root / "channels" / "reel.json").read_text(encoding="utf-8"))
    doc["voice_profile"] = {"voice_id": "TODO CF-0659: choose by ear"}
    _w(root / "channels" / "reel.json", doc)
    git(root, "commit", "-q", "-am", "a placeholder voice")
    c = client(root)
    n = len(SPAWNS)
    p = _plan(c)
    want = BS.launch_check("reel", root, **_kw())
    assert p["ok"] is False and p["confirm"] is None and p["expires_in_s"] is None, p
    g = {x["name"]: x for x in p["guards"]}
    assert g["voice"]["ok"] is False and "голос reel не выбран (CF-0659)" in g["voice"]["line"], g
    assert p["why"] == want["why"] == g["voice"]["line"], p
    assert _bare(p["guards"]) == _bare(want["guards"]), p
    r = c.get("/api/schedule")
    assert r.status_code == 200, r.text
    _nothing_started(root, n)


# --------------------------------------------------------------------- the launch
@guarded
def test_the_launch_starts_the_stand_in_detached_and_answers_at_once():
    root = _tree()
    c = client(root)
    before, n = state(root), len(SPAWNS)
    token = _plan(c)["confirm"]
    r = _launch(c, token)
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["ok"] is True and a["channel"] == "reel" and isinstance(a["pid"], int), a
    assert a["line"].startswith("запущен reel: pid "), a
    row = a["row"]
    assert row["by"] == "user (центр)" and row["kind"] == "manual" and row["pid"] == a["pid"], row
    assert row["argv"][1] == ".../" + FAKE.name and row["log"] == a["log"], row
    assert (root / a["log"]).resolve().is_relative_to((BS.state_dir(root) / "logs").resolve()), a
    assert str(root) not in json.dumps(a) and str(root.resolve()) not in json.dumps(a), a
    # CC-0152: Launch types the CF-0822 / CF-0830 keys (budget, quota_day, failed_batch,
    # failure, until) - null in the answer when the journal's row has none
    assert paths.clean(_launches(root), root) == [{k: v for k, v in row.items()
                                                   if v is not None}], _launches(root)
    assert isinstance(row["code"], dict) and row["code"], row      # CF-0822: the launch's code
    assert row["budget"] is None and row["quota_day"] is None, row
    assert len(SPAWNS) == n + 1 and paths.clean(SPAWNS[-1], root) == row["argv"], SPAWNS[n:]
    ran = _ran(root)
    assert ran == [["run", "reel", "--root", str(root.resolve())]], ran
    assert ("batch_started", f"batch_started:{row['day']}", "reel") in NOTICES, NOTICES
    assert state(root) == before                     # schedule/ is gitignored, HEAD the same
    # single use
    r = _launch(c, token)
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
    # the day's batch is there: the plan says «1 батч в сутки» as the factory does
    p = _plan(c)
    chk, g = _today_line(root)
    assert p["ok"] is False and p["confirm"] is None, p
    assert p["why"] == chk["why"] == g["today"]["line"] and "1 батч в сутки" in p["why"], p
    assert len(SPAWNS) == n + 1


@guarded
def test_a_batch_already_today_is_refused_at_the_launch_as_the_factory_says():
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    token = _plan(c)["confirm"]
    day = BS.msk_day(BS.now_utc()).isoformat()
    BS.state_dir(root).mkdir(parents=True, exist_ok=True)
    BS.journal_launch({"at": BS.iso(BS.now_utc()), "day": day, "channel": "reel",   # CF-0787
                       "by": "tick", "pid": 1, "argv": ["x"], "log": "x"}, root)
    r = _launch(c, token)
    assert r.status_code == 409, r.text
    chk, g = _today_line(root)
    body = r.json()
    assert body["code"] == "refused" and body["message"] == chk["why"] == g["today"]["line"], body
    assert "1 батч в сутки" in body["message"], body
    assert len(SPAWNS) == n and len(_launches(root)) == 1


@guarded
def test_a_guard_names_its_batches():
    """CC-0110: LaunchGuard.batches - `open`: «<dir>/<batch_id>» of every fresh
    open batch (batch_schedule.open_batches, the guard's own call, with the
    same planted rows; a stale one is not); `today`: the factory's own row
    (CF-0724: `started_on` records - `[]` when none, and a launch whose folder
    is not made yet names none); the rest: null - they carry only the line."""
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    g = {x["name"]: x for x in _plan(c)["guards"]}
    assert g["open"]["batches"] == [] and g["open"]["ok"] is True, g["open"]
    assert g["today"]["batches"] == [], g["today"]
    assert all(g[n]["batches"] is None for n in g if n not in ("open", "today")), g
    a = root / "pipeline" / "reel" / "2026-10-09T0900Z"
    b = root / "pipeline" / "old-reel" / "2026-10-09T1000Z"
    s = root / "pipeline" / "reel" / "2026-10-01T0900Z"
    for d in (a, b, s):
        d.mkdir(parents=True)
    rows = [(a, None, True), (b, None, True), (s, None, False)]
    with _Kw(open_rows=rows):
        p = _plan(c)
        want = BS.launch_check("reel", root, **_kw(open_rows=rows))
    g = {x["name"]: x for x in p["guards"]}
    assert g["open"]["ok"] is False and g["open"]["line"] == \
        {x["name"]: x for x in want["guards"]}["open"]["line"], g["open"]
    assert g["open"]["batches"] == ["reel/2026-10-09T0900Z", "old-reel/2026-10-09T1000Z"], g
    assert p["confirm"] is None and p["fingerprint"] == batches._fingerprint(want), p
    day = BS.msk_day(BS.now_utc()).isoformat()
    BS.state_dir(root).mkdir(parents=True, exist_ok=True)
    BS.journal_launch({"at": BS.iso(BS.now_utc()), "day": day, "channel": "reel",   # CF-0787
                       "by": "tick", "pid": 1, "argv": ["x"], "log": "x"}, root)
    g = {x["name"]: x for x in _plan(c)["guards"]}
    assert g["today"]["ok"] is False and g["today"]["batches"] == [], g["today"]
    # a factory row that carries them is passed as is
    saved = BS.launch_check

    def carrying(*a, **k):
        chk = saved(*a, **k)
        for x in chk["guards"]:
            if x["name"] == "today":
                x["batches"] = ["reel/2026-10-10T0000Z"]
        return chk
    BS.launch_check = carrying
    try:
        g = {x["name"]: x for x in _plan(c)["guards"]}
    finally:
        BS.launch_check = saved
    assert g["today"]["batches"] == ["reel/2026-10-10T0000Z"], g["today"]
    assert len(SPAWNS) == n and len(_launches(root)) == 1        # only the planted row


def test_the_launch_plan_carries_the_check_s_quota_day():
    """CC-0147 (CF-0787): the launch plan passes launch_check's quota_day (the
    YouTube Search quota day, Pacific) through, next to the Moscow `today`."""
    root = _tree()
    c = client(root)
    p = _plan(c)
    want = BS.launch_check("reel", root, **_kw())
    assert p["quota_day"] == want["quota_day"] == BS.quota_day(BS.now_utc()).isoformat(), p
    assert p["today"] == want["today"], p


def test_today_names_the_batch_from_the_factorys_own_field():
    """CC-0114 (over CF-0724): `today`'s batches are launch_check's own list
    (`started_on(records=True)` -> started_batches) passed through - a folder
    of today's batch in pipeline/ is named, the line text is never parsed."""
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    # CF-0787: «today» is the quota day of now - a batch started this very minute
    bid = BS.now_utc().strftime("%Y-%m-%dT%H%MZ")
    d = root / "pipeline" / "reel" / bid
    d.mkdir(parents=True)
    p = _plan(c)
    want = {x["name"]: x for x in BS.launch_check("reel", root, **_kw())["guards"]}["today"]
    g = {x["name"]: x for x in p["guards"]}["today"]
    assert want["batches"] == [f"reel/{bid}"], want
    assert g["ok"] is False and g["batches"] == want["batches"] and g["line"] == want["line"], g
    assert p["confirm"] is None and len(SPAWNS) == n, p
    # the API takes the list, not the line: a row whose line names another batch keeps its own
    saved = BS.launch_check

    def other_line(*a, **k):
        chk = saved(*a, **k)
        for x in chk["guards"]:
            if x["name"] == "today":
                x["line"] = "reel 2026-01-01T0000Z (pipeline/)"
        return chk
    BS.launch_check = other_line
    try:
        g = {x["name"]: x for x in _plan(c)["guards"]}["today"]
    finally:
        BS.launch_check = saved
    assert g["batches"] == [f"reel/{bid}"], g


# --------------------------------------------------------------------- the token
@guarded
def test_a_token_unknown_of_another_channel_or_expired_starts_nothing():
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    r = _launch(c, "not-a-token")
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
    assert "заново" in r.json()["message"], r.text
    r = c.post("/api/batches/launch", headers=H, json={"channel": "reel"})
    assert r.status_code == 422, r.text                   # no confirm at all
    # another channel's: refused and spent
    token = _plan(c)["confirm"]
    r = _launch(c, token, "demo")
    assert r.status_code == 409 and r.json()["code"] == "confirm_channel", r.text
    r = _launch(c, token)
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
    # expired: the clock turned past the TTL
    token = _plan(c)["confirm"]
    real = batches._clock
    batches._clock = lambda: real() + batches.CONFIRM_TTL + 1
    try:
        r = _launch(c, token)
    finally:
        batches._clock = real
    assert r.status_code == 409 and r.json()["code"] == "confirm_expired", r.text
    r = _launch(c, token)
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
    # a token of another root (another app over another tree) is not this one's
    other = _tree()
    token = _plan(client(other))["confirm"]
    r = _launch(c, token)
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text
    _nothing_started(root, n)
    _nothing_started(other, n)


# --------------------------------------------------------------------- the check again
@guarded
def test_a_batch_opened_since_the_plan_is_refused_with_the_factory_s_line():
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    token = _plan(c)["confirm"]
    d = root / "pipeline" / "reel" / "2026-10-09T0900Z"
    d.mkdir(parents=True)
    rows = [(d, None, True)]
    with _Kw(open_rows=rows):
        r = _launch(c, token)
        chk = BS.launch_check("reel", root, **_kw(open_rows=rows))
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "refused" and body["message"] == chk["why"], body
    assert body["message"].startswith("идёт батч"), body
    assert "the check changed since the plan" in body["details"], body
    _nothing_started(root, n)


@guarded
def test_a_check_changed_otherwise_is_check_changed():
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    token = _plan(c)["confirm"]
    with _Kw(executor=str(FAKE2)):                   # the argv differs, every guard holds
        r = _launch(c, token)
    assert r.status_code == 409 and r.json()["code"] == "check_changed", r.text
    _nothing_started(root, n)


# --------------------------------------------------------------------- one at a time
@guarded
def test_two_confirms_at_once_start_one_batch():
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    t1, t2 = _plan(c)["confirm"], _plan(c)["confirm"]
    entered, release = threading.Event(), threading.Event()
    inner = BS.spawn_detached

    def held(*a, **k):
        entered.set()
        assert release.wait(LONG), "never released"
        return inner(*a, **k)

    out = {}

    def go(key, token):
        out[key] = _launch(c, token)

    BS.spawn_detached = held
    try:
        a = threading.Thread(target=go, args=("a", t1))
        a.start()
        assert entered.wait(LONG), "the first launch never reached the spawn"
        assert batches._LAUNCH.locked()             # the second has to wait for it
        b = threading.Thread(target=go, args=("b", t2))
        b.start()
        release.set()
        a.join(LONG)
        b.join(LONG)
    finally:
        BS.spawn_detached = inner
        release.set()
    assert out["a"].status_code == 200, out["a"].text
    assert out["b"].status_code == 409, out["b"].text
    body = out["b"].json()
    assert body["code"] == "refused" and "1 батч в сутки" in body["message"], body
    assert len(SPAWNS) == n + 1 and len(_launches(root)) == 1, (SPAWNS[n:], _launches(root))
    assert len(_ran(root)) == 1


# --------------------------------------------------------------------- logged in (CC-0176)
CLAUDE_CALLS = TMP / "claude-calls.txt"


def _claude(name, doc, code=0):
    """A stand-in `claude` (RUN_EXECUTOR_CLAUDE): /bin/sh builtins only, it
    records its argv and prints `doc` as `claude auth status --json` would."""
    p = _w(TMP / f"claude-{name}.sh",
           "#!/bin/sh\n"
           f"echo \"$*\" >> '{CLAUDE_CALLS}'\n"
           f"printf '%s\\n' '{json.dumps(doc)}'\n"
           f"exit {code}\n")
    p.chmod(0o755)
    return str(p)


def _calls():
    return CLAUDE_CALLS.read_text(encoding="utf-8").splitlines() if CLAUDE_CALLS.is_file() else []


def _env(stub):
    return {"RUN_EXECUTOR_CLAUDE": stub, "PATH": os.environ.get("PATH", "/usr/bin:/bin")}


@guarded
def test_logged_in_the_launch_starts_and_answers_login():
    root = _tree()
    c = client(root)
    n, calls = len(SPAWNS), len(_calls())
    with _Kw(environ=_env(_claude("in", {"loggedIn": True, "authMethod": "claude.ai"}))):
        p = _plan(c)
        assert p["ok"] is True and p["confirm"], p
        assert p["login"] == {"ok": True, "checked": True, "line": "claude залогинен"}, p
        r = _launch(c, p["confirm"])
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["ok"] is True and a["login"] == {"ok": True, "checked": True,
                                              "line": "claude залогинен"}, a
    assert _calls()[calls:] == ["auth status --json"] * 2, _calls()   # the plan's and the launch's
    assert len(SPAWNS) == n + 1 and len(_launches(root)) == 1, SPAWNS[n:]
    assert _ran(root) == [["run", "reel", "--root", str(root.resolve())]]


@guarded
def test_not_logged_in_is_refused_and_opens_nothing():
    root = _tree()
    c = client(root)
    before, n, notices = state(root), len(SPAWNS), len(NOTICES)
    with _Kw(environ=_env(_claude("out", {"loggedIn": False}, code=1))):
        p = _plan(c)
        # the plan tells it; the token is the guards' - the launch refuses
        assert p["ok"] is True and p["confirm"], p
        assert p["login"]["ok"] is False and p["login"]["checked"] is True, p
        r = _launch(c, p["confirm"])
        want = BS.login_state(root, _env(_claude("out", {"loggedIn": False}, code=1)))
    assert r.status_code == 409, r.text
    body = r.json()
    assert body["code"] == "not_logged_in", body
    assert want["ok"] is False and body["message"] == f"{want['line']} - батч не открыт.", body
    assert "claude не залогинен" in body["message"] and body["details"][0] == want["line"], body
    _nothing_started(root, n)
    assert not (root / "schedule" / "fake-launched.jsonl").exists()
    assert NOTICES[notices:] == [], NOTICES[notices:]
    assert state(root) == before
    # the token is spent, as any presented token is
    r = _launch(c, p["confirm"])
    assert r.status_code == 409 and r.json()["code"] == "confirm_unknown", r.text


@guarded
def test_login_unknown_starts_with_a_warning():
    root = _tree()
    c = client(root)
    n = len(SPAWNS)
    with _Kw(environ=_env(_claude("what", {"status": "?"}, code=3))):
        p = _plan(c)
        r = _launch(c, p["confirm"])
        want = BS.login_state(root, _env(_claude("what", {"status": "?"}, code=3)))
    assert want["ok"] is None and want["checked"] is True, want
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["ok"] is True and a["login"] == want and "вход не проверен" in a["login"]["line"], a
    assert p["login"] == want, p
    assert len(SPAWNS) == n + 1 and len(_launches(root)) == 1, SPAWNS[n:]
    assert _ran(root) == [["run", "reel", "--root", str(root.resolve())]]


@guarded
def test_a_root_not_the_factorys_without_the_stand_in_is_unknown_and_starts():
    """No RUN_EXECUTOR_CLAUDE and a temp root: the factory never asks the real
    CLI - unknown, the launch goes on."""
    root = _tree()
    c = client(root)
    calls = len(_calls())
    with _Kw(environ={"PATH": os.environ.get("PATH", "/usr/bin:/bin")}):
        p = _plan(c)
        r = _launch(c, p["confirm"])
    assert r.status_code == 200, r.text
    login = r.json()["login"]
    assert login["ok"] is None and login["checked"] is False, login
    assert "не корень фабрики" in login["line"], login
    assert len(_calls()) == calls


def test_the_contract_names_not_logged_in_and_login():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    assert "not_logged_in" in sch["BatchProblem"]["properties"]["code"]["enum"]
    assert sorted(sch["LoginState"]["properties"]) == ["checked", "line", "ok"]
    assert sch["LoginState"]["required"] == ["line"]
    for m in ("LaunchPlan", "LaunchResult"):
        assert "login" in sch[m]["properties"] and "login" not in sch[m].get("required", []), m
    assert "auto" in sch["Launch"]["properties"]


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
