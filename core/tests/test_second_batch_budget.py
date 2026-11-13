#!/usr/bin/env python3
"""CF-0830: a next batch in the same YouTube Search quota day, by the Search
budget (`shared/batch_schedule.py` `windows`, `expected_searches`,
`quota_budget`, `admission`).

Synthetic factories in a temp dir (no network, no live data; the executor the
tick starts is a stand-in that writes down its argv, notifications go to a
temp journal). The quota day 20.10 runs 07:00Z 20.10 - 07:00Z 21.10 (PDT);
the windows are 11:30 and 17:00 МСК (08:30Z, 14:00Z), three hours each; a
batch is estimated at the default 4 hours.

Pinned:
* one window (no `windows`): one batch a quota day, no `more`, no `budget` -
  as before;
* `windows` + the budget fits: the second window of the day takes a batch of
  the other channel (the nearest empty slot), `budget_admission` says why; the
  tick starts it after the first one, its row carries the admission and its
  notification has a key of its own; the button admits it too;
* the budget does not fit: no second batch, `budget` says why (reason budget),
  the day is done_today, the button refuses with the same reason;
* the ceiling `max_batches`; a window that passes while the day's booked batch
  runs takes nothing (never two at once);
* the repeat breaker (CF-0822) holds a later window of the day as well;
* the expected spend: the median of the last N batches, the default without one;
* the setting `windows` (validated, cleared by an empty value, the CLI);
* `status --json` / `plan --json` carry the budget.
"""
import io
import json
import os
import sys
import time as _time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import batch_schedule as bs         # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("second-batch-budget-test-")
A, B = "alpha", "beta"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
ONE = {"window": "11:30", "tz": "Europe/Moscow", "window_hours": 3, "min_feed_days": 14}
TWO = dict(ONE, windows=["11:30", "17:00"])
MORNING = "2026-10-20T07:30:00Z"     # 10:30 МСК, quota day 20.10, before both windows
EVENING = "2026-10-20T14:05:00Z"     # 17:05 МСК - inside the second window
FIRST = "2026-10-20T0830Z"           # the day's first batch (11:30 МСК)
_n = [0]

FAKE = TMP / "fake_executor.py"
FAKE.parent.mkdir(parents=True, exist_ok=True)
FAKE.write_text("import json, sys\n"
                "from pathlib import Path\n"
                "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
                "with open(root / 'fake-launched.jsonl', 'a') as fh:\n"
                "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n", encoding="utf-8")


def _w(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False),
                    encoding="utf-8")
    return path


def spent(r, ch, bid, n, before=0):
    """A batch folder whose trend-hunter spent `n` searches of its own."""
    _w(r / "pipeline" / ch / bid / "01-trend-hunter.json",
       {"search_quota": {"spent_searches": n + before, "searches_before_stage": before}})


def factory(window=TWO, chans=(A, B), history=40):
    """Each channel with three old batches of `history` searches each."""
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    r.mkdir(parents=True)
    for ch in chans:
        _w(r / "channels" / f"{ch}.json",
           {"channel_id": ch, "publisher": {"slot": SLOT}, "run_plan": {"stages": []},
            "batch_schedule": window})
        if history is not None:
            for k in (1, 2, 3):
                spent(r, ch, f"2026-10-0{k}T0830Z", history)
    return r


def env(r):
    return {bs.STATE_ENV: str(r / "schedule")}


def plan(r, now, days=1):
    return bs.plan(r, now, days, open_rows=[], environ=env(r))


def failed_batch(r, ch, bid):
    """Failed in pool-maintenance before trend-hunter: no quota spent, no run header."""
    d = r / "pipeline" / ch / bid
    d.mkdir(parents=True)
    (d / "run-executor.lock").write_text("pid 4242\n")
    order = ["batch-start", "pool-maintenance", "trend-hunter", "batch-done"]
    _w(d / "run-state.json", {
        "version": 1, "task": "CF-0203", "channel": ch, "batch_id": bid, "order": order,
        "status": "failed", "created": bs.iso(bs._batch_start(bid)), "current": None,
        "executor": {"pid": 4343},
        "stages": {"batch-start": {"status": "done", "started": "x"},
                   "pool-maintenance": {"status": "failed", "started": "x", "reason": "boom"},
                   "trend-hunter": {"status": "skipped"},
                   "batch-done": {"status": "done", "started": "x"}}})


class notify_dir:
    def __init__(self, r):
        self.r = r

    KEYS = ("NOTIFY_STATE_DIR", "NOTIFY_BACKENDS")

    def __enter__(self):
        self.old = {k: os.environ.get(k) for k in self.KEYS}
        os.environ["NOTIFY_STATE_DIR"] = str(self.r / "notify-state")
        os.environ["NOTIFY_BACKENDS"] = "log"           # nothing leaves the machine
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def sent(self):
        p = self.r / "notify-state" / "sent.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


def launched(r, wait=10.0):
    p = r / "fake-launched.jsonl"
    end = _time.monotonic() + wait
    while _time.monotonic() < end and not p.is_file():
        _time.sleep(0.05)
    _time.sleep(0.2)
    return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


# ------------------------------------------------------------------ one window
def test_one_window_keeps_one_batch_a_quota_day():
    r = factory(ONE)
    p = plan(r, MORNING, 2)
    d0, d1 = p["days"]
    assert d0["status"] == "planned" and d0["channel"] == A, d0
    for d in (d0, d1):
        assert "more" not in d and "budget" not in d and "budget_admission" not in d, d
    assert d1["channel"] == B, d1                      # B waits for the next quota day
    assert p["channels"][A]["windows"] is None and p["channels"][A]["settings"]["windows"] is None
    assert p["quota_budget"]["windows_channels"] == [], p["quota_budget"]
    spent(r, A, FIRST, 30)
    d = plan(r, EVENING)["days"][0]
    assert d["kind"] == "done_today" and "budget" not in d, d
    assert d["why"].startswith("сегодня батч уже был: ") and "бюджет" not in d["why"], d
    chk = bs.launch_check(B, r, EVENING, open_rows=[], environ=env(r), executor=FAKE)
    assert not chk["ok"] and chk["budget"] is None, chk
    # the plan's text names no budget without `windows`
    assert not any("Бюджет поиска" in x for x in bs.plan_lines(plan(r, MORNING)))


# ------------------------------------------------------------------ two windows, the budget fits
def test_two_windows_and_room_in_the_budget_give_a_second_batch():
    r = factory(TWO, history=40)
    p = plan(r, MORNING, 2)
    d0 = p["days"][0]
    assert d0["status"] == "planned" and d0["kind"] == "needs_batch" and d0["channel"] == A, d0
    assert d0["window_start"] == "2026-10-20T08:30:00Z" and "budget_admission" not in d0, d0
    assert len(d0["more"]) == 1, d0
    m = d0["more"][0]
    assert m["channel"] == B and m["kind"] == "needs_batch" and m["status"] == "planned", m
    assert m["window_start"] == "2026-10-20T14:00:00Z" and m["quota_day"] == "2026-10-20", m
    assert m["est_end"] > d0["est_end"] and m["window_start"] >= d0["est_end"], (m, d0)
    ba = m["budget_admission"]
    assert ba["admitted"] and ba["reason"] == "ok" and ba["nth"] == 2, ba
    assert (ba["spent"], ba["spent_planned"], ba["expected"], ba["after"]) == (40, 40, 40, 80), ba
    assert ba["left"] == 60 and ba["limit"] == 100 and ba["margin"] == 5, ba
    assert "2-й батч" in m["why"] and "допущен по бюджету поиска" in m["why"], m
    assert ba in d0["budget"], d0["budget"]
    # the next day: the same two
    d1 = p["days"][1]
    assert d1["status"] == "planned" and len(d1["more"]) == 1, d1
    assert {d1["channel"], d1["more"][0]["channel"]} == {A, B}, d1
    lines = bs.plan_lines(p)
    assert any(x.startswith("      + ") and B in x for x in lines), lines
    assert any("Бюджет поиска (CF-0830" in x for x in lines), lines
    assert p["channels"][A]["windows"] == ["11:30", "17:00"], p["channels"][A]
    assert p["channels"][A]["expected_searches"]["searches"] == 40
    # the first batch ran (spent 40): the evening window takes the second one
    spent(r, A, FIRST, 40)
    d = plan(r, EVENING)["days"][0]
    assert d["status"] == "planned" and d["window_start"] == "2026-10-20T14:00:00Z", d
    ba = d["budget_admission"]
    assert ba["admitted"] and ba["spent_recorded"] == 40 and ba["batches"] == 1, ba
    chk = bs.launch_check(B, r, EVENING, open_rows=[], environ=env(r), executor=FAKE)
    assert chk["ok"] and chk["budget"]["admitted"], chk
    assert "допущен по бюджету" in [g for g in chk["guards"] if g["name"] == "today"][0]["line"]
    bs.set_switch(True, "user", "«включай» (тест)", r, now="2026-10-19T10:00:00Z")
    with notify_dir(r) as nd:
        code, line, row = bs.tick(r, EVENING, executor=FAKE, open_rows=[], environ=env(r))
        assert code == 0 and row and line.startswith("TICK started"), line
        assert row["budget"]["admitted"] and row["channel"] == d["channel"], row
        assert launched(r) == [["run", d["channel"], "--root", str(r.resolve())]]
        keys = [s["key"] for s in nd.sent() if s["kind"] == "batch_started"]
        assert keys == [f"batch_started:2026-10-20:{d['channel']}:1700"], keys
        # the launched one is the second batch of the quota day: a third waits
        code, line, row = bs.tick(r, "2026-10-20T14:20:00Z", executor=FAKE, open_rows=[],
                                  environ=env(r))
        assert row is None and "не допущен" in line, line


# ------------------------------------------------------------------ the budget does not fit
def test_no_room_in_the_budget_no_second_batch_and_why():
    r = factory(TWO, history=70)
    d0 = plan(r, MORNING)["days"][0]
    assert d0["status"] == "planned" and d0["channel"] == A and "more" not in d0, d0
    refused = d0["budget"]
    assert refused and all(not e["admitted"] and e["reason"] == "budget" for e in refused), refused
    e = refused[0]
    assert (e["spent"], e["expected"], e["after"]) == (70, 70, 140), e
    assert "не допущен по бюджету поиска" in e["why"] and "> 95" in e["why"], e
    spent(r, A, FIRST, 70)
    d = plan(r, EVENING)["days"][0]
    assert d["status"] == "done" and d["kind"] == "done_today", d
    assert "не допущен по бюджету поиска" in d["why"], d
    assert d["budget"][0]["left"] == 30 and d["budget"][0]["reason"] == "budget", d
    chk = bs.launch_check(B, r, EVENING, open_rows=[], environ=env(r), executor=FAKE)
    assert not chk["ok"] and chk["budget"]["reason"] == "budget", chk
    assert "не допущен по бюджету поиска" in chk["why"], chk
    # a batch whose spend is not on record yet counts at its channel's expected spend
    r2 = factory(TWO, history=40)
    (r2 / "pipeline" / A / FIRST).mkdir(parents=True)          # no 01, no run log
    base = bs.quota_budget(bs.quota_day(bs.now_utc(EVENING)), r2, env(r2))
    assert base["batches"] == 1 and base["spent"] == 40 and base["spent_recorded"] == 0, base
    assert base["unrecorded"] == [{"batch": f"{A}/{FIRST}", "channel": A, "expected": 40}], base


# ------------------------------------------------------------------ the ceiling, never two at once
def test_the_ceiling_and_no_overlap():
    three = dict(ONE, windows=["11:30", "15:00", "19:00"])
    r = factory(three, history=20)
    spent(r, A, FIRST, 20)
    spent(r, B, "2026-10-20T1200Z", 20)
    now = "2026-10-20T16:05:00Z"                     # 19:05 МСК
    d = plan(r, now)["days"][0]
    assert d["kind"] == "done_today", d
    e = d["budget"][0]
    assert not e["admitted"] and e["reason"] == "max_batches" and e["batches"] == 2, e
    assert "потолок 2 батча" in e["why"], e
    old = bs.QUOTA_BUDGET["max_batches"]
    bs.QUOTA_BUDGET["max_batches"] = 3
    try:
        d = plan(r, now)["days"][0]
        assert d["status"] == "planned" and d["budget_admission"]["nth"] == 3, d
    finally:
        bs.QUOTA_BUDGET["max_batches"] = old
    # a window that passes while the day's booked batch runs (4 h) takes nothing
    near = dict(ONE, windows=["11:30", "13:00"], window_hours=2)
    r2 = factory(near, history=20)
    d = plan(r2, MORNING)["days"][0]
    assert d["status"] == "planned" and "more" not in d, d


# ------------------------------------------------------------------ the repeat breaker
def test_the_breaker_holds_a_later_window_too():
    three = dict(ONE, windows=["11:30", "14:00", "17:00"])
    r = factory(three, chans=(A,), history=30)
    spent(r, A, FIRST, 30)                           # the first batch spent its quota
    failed_batch(r, A, "2026-10-20T1100Z")           # the second failed before trend-hunter
    p = plan(r, EVENING)
    d = p["days"][0]
    assert d["status"] == "idle" and d["kind"] == "nobody_available", d
    assert d["breaker"]["held"] and d["breaker"]["batch"] == f"{A}/2026-10-20T1100Z", d
    assert d["window_start"] == "2026-10-20T14:00:00Z", d
    assert d["budget"][0]["admitted"], d["budget"]       # the budget alone would let it
    bs.set_switch(True, "user", "«включай» (тест)", r, now="2026-10-19T10:00:00Z")
    with notify_dir(r):
        code, line, row = bs.tick(r, EVENING, executor=FAKE, open_rows=[], environ=env(r))
    assert row is None and "повтор того же отказа не запущен" in line, line
    assert launched(r, 0.3) == []
    held = [x for x in bs.launches(r, env(r)) if x.get("kind") == "repeat_held"]
    assert len(held) == 1 and held[0]["channel"] == A, held
    # the failure alone (the day's only batch) - the evening window is held as well
    r2 = factory(TWO, chans=(A,), history=30)
    failed_batch(r2, A, FIRST)
    d = plan(r2, EVENING)["days"][0]
    assert d["kind"] == "nobody_available" and d["breaker"]["held"], d


# ------------------------------------------------------------------ the expected spend
def test_the_expected_spend_is_the_median_of_the_last_batches():
    r = factory(TWO, chans=(A,), history=None)
    e = bs.expected_searches(A, r, MORNING)
    assert e["searches"] == 85 and e["n"] == 0 and e["source"] == "default", e
    for k, n in enumerate((10, 90, 40, 51), start=1):
        spent(r, A, f"2026-10-0{k}T0830Z", n, before=7)  # the earlier batches' share is not its own
    _w(r / "pipeline" / A / "2026-10-05T0830Z" / "run-state.json", {"status": "running"})
    e = bs.expected_searches(A, r, MORNING)
    assert e["n"] == 3 and e["searches"] == 51, e   # 90, 40, 51 -> 51; no 01 - not counted
    assert [b["searches"] for b in e["batches"]] == [90, 40, 51], e
    old = bs.QUOTA_BUDGET["expected_batches"]
    bs.QUOTA_BUDGET["expected_batches"] = 2
    try:
        assert bs.expected_searches(A, r, MORNING)["searches"] == 46    # (40 + 51) / 2, up
    finally:
        bs.QUOTA_BUDGET["expected_batches"] = old


# ------------------------------------------------------------------ the setting
def test_the_windows_setting():
    r = factory(ONE, chans=(A,))
    assert bs.validate_settings({"windows": "17:00, 11:30"}) == {"windows": ["11:30", "17:00"]}
    assert bs.validate_settings({"windows": ""}) == {"windows": None}
    for bad in ("25:00", "11:30,12:00,13:00,14:00,15:00", "7:00"):
        try:
            bs.validate_settings({"windows": bad})
        except bs.ScheduleError:
            pass
        else:
            raise AssertionError(bad)
    got = bs.set_channel_settings(A, {"windows": ["11:30", "17:00"]}, "user", "тест", r,
                                  environ=env(r))
    assert got["changed"] == {"windows": [None, ["11:30", "17:00"]]}, got
    st = bs.channel_settings(A, r, env(r))
    assert st["windows"] == ["11:30", "17:00"] and st["overlay"]["windows"] == ["11:30", "17:00"]
    w = bs.window_config(A, r, environ=env(r))
    assert w["multi"] and [t.strftime("%H:%M") for t in w["windows"]] == ["11:30", "17:00"], w
    got = bs.set_channel_settings(A, {"windows": ""}, "user", None, r, environ=env(r))
    assert got["changed"] == {"windows": [["11:30", "17:00"], None]}, got
    assert "windows" not in (bs.settings_overlay(r, env(r))["channels"].get(A) or {})
    assert not bs.window_config(A, r, environ=env(r))["multi"]
    old = os.environ.get(bs.STATE_ENV)
    os.environ[bs.STATE_ENV] = str(r / "schedule")
    try:
        out = io.StringIO()
        assert bs.main(["settings", A, "--by", "user", "--windows", "11:30,18:00",
                        "--root", str(r)], out=out) == 0
        assert "окно 11:30, 18:00 Europe/Moscow" in out.getvalue(), out.getvalue()
        # a broken `windows` in the channel's file is said, not guessed
        _w(r / "channels" / "gamma.json",
           {"channel_id": "gamma", "publisher": {"slot": SLOT}, "run_plan": {"stages": []},
            "batch_schedule": dict(ONE, windows="11:30")})
        assert "windows must be a list" in bs.channel_settings("gamma", r)["error"]
    finally:
        if old is None:
            os.environ.pop(bs.STATE_ENV, None)
        else:
            os.environ[bs.STATE_ENV] = old


# ------------------------------------------------------------------ status / plan --json
def test_status_and_plan_json_carry_the_budget():
    r = factory(TWO, history=40)
    spent(r, A, FIRST, 40)
    old = os.environ.get(bs.STATE_ENV)
    os.environ[bs.STATE_ENV] = str(r / "schedule")
    try:
        out = io.StringIO()
        assert bs.main(["status", "--root", str(r), "--now", EVENING, "--json"], out=out) == 0
        b = json.loads(out.getvalue())["budget"]
        assert b["config"]["max_batches"] == 2 and b["config"]["limit"] == 100, b
        assert "_note" in b["config"], b
        assert b["today"]["spent"] == 40 and b["today"]["left"] == 60, b
        assert b["today"]["batches"] == 1, b
        assert b["expected"][A]["searches"] == 40 and b["expected"][B]["n"] == 3, b
        out = io.StringIO()
        assert bs.main(["status", "--root", str(r), "--now", EVENING], out=out) == 0
        assert "Бюджет поиска (CF-0830)" in out.getvalue() and "остаток 60" in out.getvalue()
        out = io.StringIO()
        assert bs.main(["plan", "--root", str(r), "--now", EVENING, "--days", "1", "--json"],
                       out=out) == 0
        p = json.loads(out.getvalue())
        assert p["quota_budget"]["today"]["left"] == 60, p["quota_budget"]
        assert p["quota_budget"]["windows_channels"] == [A, B], p["quota_budget"]
        assert p["days"][0]["budget_admission"]["admitted"], p["days"][0]
    finally:
        if old is None:
            os.environ.pop(bs.STATE_ENV, None)
        else:
            os.environ[bs.STATE_ENV] = old


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
