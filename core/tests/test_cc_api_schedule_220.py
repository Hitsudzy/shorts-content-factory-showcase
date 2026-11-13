"""CC-0152: factory 2.20 in the center's API - the repeat breaker (CF-0822),
the Search budget and a next batch of the day (CF-0830) on `GET /api/schedule`,
`POST /api/batches/launch/plan`, `GET /api/batches/history` and the `windows`
setting of `PUT /api/schedule/channels/{channel}`.

In-process against the stand-in factory of `tests/test_cc_api_batches.py` (a
temp git repository with `reel` and the stub `demo`); the factory's code is
this checkout's. The clock is the factory's own injection point (`now=`), set
on the real `plan` / `launch_check`, never the machine's. Nothing is started,
nothing leaves the machine, no live data is read.

What is pinned:

* a failed batch that spent no quota: the plan's day 0 is the breaker's -
  kind `nobody_available` (no new kind), `breaker` (held, the batch, the
  stage), `window_start` / `window_end`, `next_windows`; the plan's `breakers`
  and the channel's `breaker` carry the same record; `quota_budget` is typed
  (`today`, `windows_channels`), the channel's `expected_searches` too;
* a planned day with `budget`, `budget_admission` and `more` (records made by
  the factory's own `admission`) passes through; `more` has no `more`;
* the output of an older factory (no breaker, no budget keys) still validates;
* `windows`: a valid list is the factory's (sorted), the plan names the channel
  in `windows_channels`; five, a bad time, a non-string - 422 invalid, nothing
  written; an explicit null removes it, [] then changes nothing;
* the launch plan carries `breaker` (held: a line in `skipped`, the plan
  still ok) and, for a channel with `windows` in a taken quota day, `budget`;
* launches.jsonl: a `repeat_held` row and a row's `code` / `budget` pass
  through; a repeat_held row is no run's launch; two runs of one day take
  their own launches.
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

for _k in ("BATCH_SCHEDULE_STATE_DIR", "NOTIFY_BACKENDS", "NOTIFY_STATE_DIR"):
    os.environ.pop(_k, None)

from test_cc_api_batches import (                    # noqa: E402
    H, _w, client, factory_tree, temp_home)

from api import batches, factory                     # noqa: E402

BS = factory.batch_schedule()
# 02:30 МСК 21.10 = 16:30 PDT 20.10: inside reel's default window (02:00 МСК + 3 h),
# quota day 2026-10-20
NOW = "2026-10-20T23:30:00Z"
FAILED = "2026-10-20T2000Z"          # 13:00 PDT 20.10 - the same quota day
ORDER = ["rights-check", "batch-start", "pool-maintenance", "trend-hunter", "video-editor",
         "batch-done"]
REASON = "handler pool-remeasure-captions failed: step 0 exited 5"


def failed_batch(root, bid=FAILED):
    """A batch that failed in pool-maintenance before trend-hunter (no quota)."""
    d = root / "pipeline" / "reel" / bid
    _w(d / "run-state.json", {
        "status": "failed", "channel": "reel", "order": ORDER,
        "stages": {"rights-check": {"status": "done", "started": "x"},
                   "batch-start": {"status": "done", "started": "x"},
                   "pool-maintenance": {"status": "failed", "started": "x", "reason": REASON},
                   "trend-hunter": {"status": "skipped",
                                    "reason": "after failed stage pool-maintenance"},
                   "video-editor": {"status": "skipped"},
                   "batch-done": {"status": "pending"}},
        "current": {"stage": "pool-maintenance"}})
    return d


class at_now:
    """The real `plan` / `launch_check` on the fixed clock, restored after."""

    def __enter__(self):
        self.plan = BS.plan
        real = self.plan
        BS.plan = lambda root=None, now=None, days=BS.PLAN_DAYS, open_rows=None, environ=None: \
            real(root, NOW, days, [], environ)
        self.kw = dict(batches.FACTORY_KW)
        batches.FACTORY_KW.update(now=NOW, open_rows=[])
        return self

    def __exit__(self, *exc):
        BS.plan = self.plan
        batches.FACTORY_KW.clear()
        batches.FACTORY_KW.update(self.kw)


def _schedule(c, days=2):
    with temp_home():
        r = c.get("/api/schedule", params={"days": days})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------- CF-0822
def test_the_breaker_day_is_the_factory_s():
    root = factory_tree()
    failed_batch(root)
    with at_now():
        p = _schedule(client(root))
    d = p["days"][0]
    assert d["kind"] == "nobody_available" and d["status"] == "idle", d
    b = d["breaker"]
    assert b["held"] is True and b["channel"] == "reel", b
    assert b["batch"] == f"reel/{FAILED}" and b["stage"] == "pool-maintenance", b
    assert b["reason"] == REASON and b["failure"] == f"pool-maintenance: {REASON}", b
    assert b["quota_day"] == "2026-10-20" and b["status"] == "failed", b
    assert b["until"] == "2026-10-21T07:00:00Z", b                # the Pacific midnight
    assert b["code_changed"] == [] and b["code_source"] is None, b  # the code unknown
    assert isinstance(b["code_now"], dict) and "повтор" in b["line"], b
    assert d["window_start"] == "2026-10-20T23:00:00Z", d
    assert d["window_end"] == "2026-10-21T02:00:00Z", d
    assert set(d["next_windows"]) == {"reel"}, d
    assert d["budget"] == [] and d["budget_admission"] is None and d["more"] == [], d
    assert p["breakers"] == {"reel": b}, p["breakers"]
    assert p["channels"]["reel"]["breaker"] == b
    assert p["channels"]["demo"]["breaker"] is None
    # the other days carry none
    assert all(x["breaker"] is None for x in p["days"][1:]), p["days"]
    # CF-0830 on the same plan: typed, no channel with windows
    qb = p["quota_budget"]
    assert qb["limit"] == 100 and qb["max_batches"] == 2 and qb["margin"] == 5, qb
    assert qb["_note"].startswith("CF-0830") and qb["windows_channels"] == [], qb
    assert qb["today"]["quota_day"] == "2026-10-20" and qb["today"]["batches"] == 0, qb
    assert qb["today"]["left"] == 100 and qb["today"]["unrecorded"] == [], qb
    es = p["channels"]["reel"]["expected_searches"]
    assert es["source"] == "default" and es["searches"] == 85 and es["n"] == 0, es
    assert p["channels"]["reel"]["windows"] is None
    assert p["channels"]["reel"]["settings"]["windows"] is None


def test_the_launch_plan_carries_the_breaker_and_does_not_refuse():
    root = factory_tree()
    failed_batch(root)
    with at_now():
        r = client(root).post("/api/batches/launch/plan", headers=H, json={"channel": "reel"})
    assert r.status_code == 200, r.text
    lp = r.json()
    assert lp["ok"] is True and lp["confirm"], lp                  # a manual start is not held
    assert lp["breaker"]["held"] is True and lp["breaker"]["batch"] == f"reel/{FAILED}", lp
    assert any("размыкатель повторов" in s for s in lp["skipped"]), lp["skipped"]
    assert lp["budget"] is None, lp


def test_the_launch_plan_of_a_windows_channel_in_a_taken_quota_day_carries_its_budget():
    root = factory_tree()
    c = client(root)
    r = c.put("/api/schedule/channels/reel", headers=H, json={"windows": ["02:00", "17:00"]})
    assert r.status_code == 200, r.text
    _w(root / "schedule" / "launches.jsonl", json.dumps(
        {"at": "2026-10-20T20:00:00Z", "day": "2026-10-20", "channel": "reel", "pid": 7,
         "by": "tick", "task": "CF-0592"}) + "\n")
    with at_now():
        r = c.post("/api/batches/launch/plan", headers=H, json={"channel": "reel"})
    assert r.status_code == 200, r.text
    lp = r.json()
    bud = lp["budget"]
    assert bud and bud["channel"] == "reel" and bud["quota_day"] == "2026-10-20", bud
    # one batch with no record yet (85 expected) + 85 expected > 95: not admitted
    assert bud["reason"] == "budget" and bud["admitted"] is False and bud["nth"] == 2, bud
    assert bud["spent"] == 85 and bud["after"] == 170 and bud["left"] == 15, bud
    today = next(g for g in lp["guards"] if g["name"] == "today")
    assert today["ok"] is False and bud["why"] in today["line"], today
    assert lp["ok"] is False and lp["confirm"] is None and lp["breaker"] is None, lp


# --------------------------------------------------------------------- CF-0830
def _admission(nth_spent=30, expected=58):
    base = {"quota_day": "2026-10-20", "limit": 100, "margin": 5, "max_batches": 2,
            "batches": 1, "spent": nth_spent, "spent_recorded": nth_spent}
    exp = {"searches": expected, "n": 3, "line": f"{expected} (медиана 3 последн. батчей)"}
    return BS.admission("reel", base, exp, (), BS.parse_ts("2026-10-21T14:00:00Z"),
                        BS.parse_ts("2026-10-21T14:00:00Z"), BS.parse_ts("2026-10-21T17:00:00Z"))


def _patched(root, mutate):
    real = BS.plan

    def fake(*a, **k):
        p = json.loads(json.dumps(real(*a, **dict(k, now=NOW, open_rows=[]))))
        mutate(p)
        return p
    BS.plan = fake
    try:
        return _schedule(client(root), 3)
    finally:
        BS.plan = real


def test_a_planned_day_with_its_budget_and_next_batches_passes_through():
    root = factory_tree()
    ok, refused = _admission(), _admission(nth_spent=60)
    assert ok["reason"] == "ok" and refused["reason"] == "budget", (ok, refused)
    more = {"channel": "reel", "window_start": "2026-10-21T14:00:00Z",
            "window_end": "2026-10-21T17:00:00Z", "quota_day": "2026-10-21",
            "est_end": "2026-10-21T18:00:00Z", "est_wall_s": 14400, "est_wall_n": 0,
            "est_videos": 3, "est_videos_n": 0, "fills": ["2026-10-24T22:00:00Z"],
            "covers_days": ["2026-10-25"], "first_empty_slot": "2026-10-22T22:00:00Z",
            "budget_admission": ok, "status": "planned", "kind": "needs_batch",
            "why": "лента короче 3 дн."}

    def mutate(p):
        d = next(x for x in p["days"] if x["kind"] == "needs_batch")
        d.update(budget=[ok, refused], budget_admission=ok, more=[more])

    p = _patched(root, mutate)
    d = next(x for x in p["days"] if x["kind"] == "needs_batch")
    assert d["budget_admission"] == ok and d["budget"] == [ok, refused], d
    m = d["more"][0]
    assert m["budget_admission"]["reason"] == "ok" and m["kind"] == "needs_batch", m
    assert m["status"] == "planned" and m["covers_days"] == ["2026-10-25"], m
    assert "more" not in m and "day" not in m, m
    for k in ("task", "nth", "spent_planned", "expected_line", "why", "start", "after"):
        assert k in d["budget"][1], (k, d["budget"][1])


def test_the_schema_of_more_does_not_recurse():
    spec = json.loads((ROOT / "api" / "openapi.json").read_text(encoding="utf-8"))
    sch = spec["components"]["schemas"]
    more = sch["PlanDay"]["properties"]["more"]
    assert more["items"]["$ref"].endswith("/PlanMoreBatch"), more
    assert "more" not in sch["PlanMoreBatch"]["properties"]
    assert set(sch["BudgetAdmission"]["properties"]["reason"]["enum"]) == {
        "ok", "budget", "max_batches", "busy"}
    assert set(sch["PlanBreaker"]["required"]) == {"channel", "batch", "held"}
    assert "_note" in sch["QuotaBudget"]["properties"]
    assert set(sch["PlanDay"]["properties"]["kind"]["enum"]) == set(BS.DAY_KINDS)  # no new kind
    assert "windows" in sch["ScheduleSettingsEdit"]["properties"]


def test_an_older_factory_s_plan_still_validates():
    root = factory_tree()

    def mutate(p):
        for k in ("breakers", "quota_budget"):
            p.pop(k, None)
        for ch in p["channels"].values():
            for k in ("breaker", "windows", "expected_searches"):
                ch.pop(k, None)
            ch["settings"].pop("windows", None)
        for d in p["days"]:
            for k in ("breaker", "budget", "budget_admission", "more"):
                d.pop(k, None)

    p = _patched(root, mutate)
    assert p["breakers"] == {} and p["quota_budget"] is None, p
    ch = p["channels"]["reel"]
    assert ch["breaker"] is None and ch["windows"] is None and ch["expected_searches"] is None
    for d in p["days"]:
        assert d["breaker"] is None and d["budget"] == [] and d["more"] == [], d
        assert d["budget_admission"] is None, d


# --------------------------------------------------------------------- windows
def test_the_windows_setting_is_written_by_the_factory():
    root = factory_tree()
    c = client(root)
    r = c.put("/api/schedule/channels/reel", headers=H,
              json={"windows": ["17:00", "11:30"], "note": "два окна"})
    assert r.status_code == 200, r.text
    got = r.json()
    assert got["changed"] == {"windows": [None, ["11:30", "17:00"]]}, got["changed"]
    assert got["settings"]["windows"] == ["11:30", "17:00"], got["settings"]
    assert got["settings"]["window"] == "11:30", got["settings"]       # windows override it
    assert got["settings"]["overlay"] == {"windows": ["11:30", "17:00"]}, got["settings"]
    row = got["history"][0]
    assert row["by"] == "user" and row["note"] == "центр: два окна", row
    ov = json.loads((root / "schedule" / "channel-settings.json").read_text(encoding="utf-8"))
    assert ov["channels"]["reel"] == {"windows": ["11:30", "17:00"]}, ov
    with at_now():
        p = _schedule(c)
    assert p["channels"]["reel"]["windows"] == ["11:30", "17:00"], p["channels"]["reel"]
    assert p["quota_budget"]["windows_channels"] == ["reel"], p["quota_budget"]
    # an explicit null removes it; [] then changes nothing
    r = c.put("/api/schedule/channels/reel", headers=H, json={"windows": None})
    assert r.status_code == 200, r.text
    assert r.json()["changed"] == {"windows": [["11:30", "17:00"], None]}, r.json()
    assert r.json()["settings"]["windows"] is None and r.json()["settings"]["window"] == "02:00"
    r = c.put("/api/schedule/channels/reel", headers=H, json={"windows": []})
    assert r.status_code == 200 and r.json()["changed"] == {}, r.text
    # left out: no change
    r = c.put("/api/schedule/channels/reel", headers=H, json={"window": "03:00"})
    assert r.status_code == 200 and set(r.json()["changed"]) == {"window"}, r.text


def test_a_wrong_windows_value_is_refused_and_writes_nothing():
    root = factory_tree()
    c = client(root)
    for value, word in ((["01:00", "02:00", "03:00", "04:00", "05:00"], "не больше 4"),
                        (["9:00"], "ЧЧ:ММ"), (["24:00"], "ЧЧ:ММ"), (["11:30", "ab"], "ЧЧ:ММ"),
                        (["11:60"], "ЧЧ:ММ")):
        r = c.put("/api/schedule/channels/reel", headers=H, json={"windows": value})
        assert r.status_code == 422 and r.json()["code"] == "invalid", (value, r.text)
        assert word in r.json()["message"], (value, r.json())
    r = c.put("/api/schedule/channels/reel", headers=H, json={"windows": "11:30,17:00"})
    assert r.status_code == 422, r.text                            # a list, not a string
    r = c.put("/api/schedule/channels/reel", headers=H, json={"windows": [930]})
    assert r.status_code == 422, r.text
    assert not (root / "schedule" / "channel-settings.json").exists()


# --------------------------------------------------------------------- launches.jsonl
def test_repeat_held_rows_pass_through_and_are_no_run_s_launch():
    root = factory_tree()
    code = {"root": "a" * 40, "agents/trend-hunter": "b" * 40}
    bud = _admission()
    rows = [
        {"at": "2026-10-20T08:31:00Z", "day": "2026-10-20", "channel": "reel", "pid": 11,
         "argv": ["x"], "log": "/tmp/l", "why": "лента короче", "by": "tick",
         "task": "CF-0592", "code": code},
        {"at": "2026-10-20T11:01:00Z", "day": "2026-10-20", "quota_day": "2026-10-20",
         "channel": "reel", "pid": None, "by": "tick", "kind": "repeat_held",
         "failed_batch": "reel/2026-10-20T0831Z", "failure": f"pool-maintenance: {REASON}",
         "until": "2026-10-21T07:00:00Z", "why": "reel: повтор того же отказа не запущен",
         "task": "CF-0822"},
        {"at": "2026-10-20T14:00:00Z", "day": "2026-10-20", "channel": "reel", "pid": 12,
         "argv": ["x"], "log": "/tmp/l2", "why": "второй батч", "by": "tick",
         "task": "CF-0592", "code": code, "budget": bud}]
    _w(root / "schedule" / "launches.jsonl",
       "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows))
    runs = [{"batch": "reel/2026-10-20T0831Z", "id": "2026-10-20T0831Z", "channel": "reel",
             "started": "2026-10-20T08:31:05.000Z"},
            {"batch": "reel/2026-10-20T1400Z", "id": "2026-10-20T1400Z", "channel": "reel",
             "started": "2026-10-20T14:00:04.000Z"}]
    _w(root / "pipeline" / "runs.jsonl", "".join(json.dumps(r) + "\n" for r in runs))
    r = client(root).get("/api/batches/history", params={"channel": "reel"})
    assert r.status_code == 200, r.text
    h = r.json()
    held = [x for x in h["launches"] if x["kind"] == "repeat_held"]
    assert len(held) == 1 and len(h["launches"]) == 3, h["launches"]
    x = held[0]
    assert x["pid"] is None and x["failed_batch"] == "reel/2026-10-20T0831Z", x
    assert x["until"] == "2026-10-21T07:00:00Z" and x["quota_day"] == "2026-10-20", x
    assert x["failure"].startswith("pool-maintenance") and x["code"] is None, x
    by_id = {r["id"]: r for r in h["runs"]}
    first, second = by_id["2026-10-20T0831Z"], by_id["2026-10-20T1400Z"]
    assert first["launch"]["pid"] == 11 and first["launch"]["code"] == code, first
    assert second["launch"]["pid"] == 12 and second["launch"]["budget"] == bud, second
    assert all(r["launch"]["kind"] != "repeat_held" for r in h["runs"]), h["runs"]


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
