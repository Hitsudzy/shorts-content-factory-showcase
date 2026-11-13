#!/usr/bin/env python3
"""CF-0592: the batch plan, the switch, the tick, the printed timer
(`shared/batch_schedule.py`) and the plan's section of the console.

Every root is a synthetic tree in a temp dir; the executor the tick starts is
a stand-in script that only writes down how it was called - no batch runs, no
timer is installed, no notification leaves the machine (`log` backend, a temp
journal).

What is pinned:

* the plan: an empty feed gets a batch with the reason and the empty slot, the
  estimates are marked as estimates; one batch a day for the whole factory;
  of several channels the one whose first empty slot comes first; a paused
  channel, one with no slot or no run_plan is not planned and the plan says
  why; an open batch makes the day busy (a stale one does not); a batch that
  already started today makes the day done; the window comes from the
  channel's `batch_schedule`, the defaults are said to be defaults;
* the switch: off with no file; `enable` only `--by user` and with a note;
  every change is a history row; nothing else writes it;
* the tick: off -> nothing; outside the window, an open batch, a batch today,
  a pause -> nothing, one line why; on and inside the window -> exactly one
  start of the executor, a journal row, one `batch_started` notification; a
  second tick the same day starts nothing; `--dry-run` starts nothing;
* `install-timer --print` prints a valid plist and the commands and installs
  nothing (no file under HOME, no process); without `--print` it refuses;
* the console's `#schedule` section and each channel's.
"""
import contextlib
import io
import json
import os
import plistlib
import sys
import time as _time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import batch_schedule as bs         # noqa: E402
import factory_state as collect    # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("batch-schedule-test-")
A, B = "alpha", "beta"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
IN_WINDOW = "2026-10-07T23:30:00Z"          # 08.10 02:30 МСК - inside the default 02:00-05:00
BEFORE_WINDOW = "2026-10-07T21:30:00Z"      # 08.10 00:30 МСК
AFTER_WINDOW = "2026-10-08T03:00:00Z"       # 08.10 06:00 МСК
_n = [0]


def _w(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False),
                    encoding="utf-8")
    return path


def _root(*chans, window=None):
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    r.mkdir(parents=True)
    for ch in chans:
        doc = {"channel_id": ch, "publisher": {"slot": SLOT}, "run_plan": {"stages": []}}
        if window is not None:
            doc["batch_schedule"] = window
        _w(r / "channels" / f"{ch}.json", doc)
    return r


def _taken(root, ch, days):
    """Studio rows of the upload journal for `ch` on the Moscow days `days` (01:00)."""
    p = root / "publish" / "uploads.json"
    rows = json.loads(p.read_text())["uploads"] if p.is_file() else []
    for d in days:
        slug = f"{ch}-{d}"
        rows.append({"channel": ch, "entry_id": f"{ch}/2026-10-01T0000Z/{slug}", "slug": slug,
                     "video_id": "V" * 11, "source": "studio", "recorded_at": "2026-10-02T00:00:00Z",
                     "publish_at": f"{d}T01:00:00+03:00", "publish_tz": "Europe/Moscow",
                     "publish_day": d})
    _w(p, {"uploads": rows})


def _span(first, n):
    """`n` Moscow days from `first` (YYYY-MM-DD), as the strings `_taken` takes."""
    from datetime import date, timedelta
    d0 = date.fromisoformat(first)
    return [(d0 + timedelta(days=i)).isoformat() for i in range(n)]


def _pause(root, ch):
    _w(root / "publish" / "channel-pauses.json", {"pauses": [
        {"pause_id": f"{ch}/2026-10-06T10:00:00Z", "channel": ch, "by": "user",
         "reason": "нарушение", "set_at": "2026-10-06T10:00:00Z", "until": None}]})


def _runs(root, rows):
    _w(root / "pipeline" / "runs.jsonl", "".join(json.dumps(r) + "\n" for r in rows))


def _day(p, i=0):
    return p["days"][i]


# ------------------------------------------------------------------ the plan
def test_an_empty_feed_gets_todays_batch_with_its_reason():
    r = _root(A)
    p = bs.plan(r, IN_WINDOW, 3, open_rows=[])
    d = _day(p)
    assert p["today"] == "2026-10-08" and d["status"] == "planned" and d["channel"] == A, d
    # CF-0922: the threshold is batch_feed_days (14 by default), not the horizon (3)
    assert "лента короче 14 дн." in d["why"] and "пусто 09.10 01:00 МСК" in d["why"], d
    line = bs.day_line(d)
    assert "оценка по умолчанию" in line and "окно 08.10 02:00 МСК–05:00" in line, line
    assert p["channels"][A]["window_source"] == "по умолчанию", p["channels"][A]


def test_estimates_come_from_runs_and_say_so():
    r = _root(A)
    _runs(r, [{"channel": A, "id": "2026-10-01T0000Z", "started": "2026-10-01T00:00:00Z",
               "wall_s": 7200, "videos": 5},
              {"channel": A, "id": "2026-10-02T0000Z", "started": "2026-10-02T00:00:00Z",
               "wall_s": 3600, "videos": 4}])
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = _day(p)
    assert d["est_wall_s"] == 5400 and d["est_wall_n"] == 2 and d["est_videos"] == 4, d
    assert "оценка по 2 прогонам" in bs.day_line(d), bs.day_line(d)


def test_one_batch_a_day_for_the_whole_factory():
    r = _root(A, B)
    p = bs.plan(r, IN_WINDOW, 7, open_rows=[])
    for d in p["days"]:
        assert d["status"] in ("planned", "idle"), d
        assert d["channel"] in (None, A, B), d      # one channel at most, by construction
    planned = [d for d in p["days"] if d["status"] == "planned"]
    assert {d["channel"] for d in planned} == {A, B}, planned
    assert _day(p)["channel"] == A and _day(p, 1)["channel"] == B, p["days"][:2]
    assert len({d["day"] for d in p["days"]}) == 7


def test_the_channel_with_the_nearest_empty_slot_gets_the_day():
    r = _root(A, B)
    _taken(r, A, ["2026-10-09", "2026-10-10"])      # alpha: empty from 11.10, beta from 09.10
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = _day(p)
    assert d["channel"] == B, d
    assert "пусто 09.10" in d["why"] and f"{A}: пусто 11.10" in d["why"], d


def test_a_long_feed_needs_no_batch():
    r = _root(A)
    _taken(r, A, _span("2026-10-09", 14))          # CF-0922: the batch threshold, 14 days
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = _day(p)
    assert d["status"] == "idle" and "батч не нужен" in d["why"], d
    assert any("не нужен" in n for n in d["notes"]), d


def test_a_paused_channel_is_not_planned():
    r = _root(A, B)
    _pause(r, A)
    p = bs.plan(r, IN_WINDOW, 3, open_rows=[])
    assert all(d["channel"] != A for d in p["days"]), p["days"]
    assert _day(p)["channel"] == B
    assert any(f"{A}: на паузе" in n for n in _day(p)["notes"]), _day(p)


def test_no_slot_or_no_run_plan_is_not_planned_and_says_why():
    r = _root(A)
    _w(r / "channels" / f"{B}.json", {"channel_id": B, "run_plan": {"stages": []}})
    _w(r / "channels" / "gamma.json", {"channel_id": "gamma", "publisher": {"slot": SLOT}})
    p = bs.plan(r, IN_WINDOW, 2, open_rows=[])
    assert "publisher.slot" in p["channels"][B]["why_not"], p["channels"][B]
    assert "run_plan" in p["channels"]["gamma"]["why_not"], p["channels"]["gamma"]
    assert all(d["channel"] in (None, A) for d in p["days"])
    text = "\n".join(bs.plan_lines(p))
    assert f"{B}: не планируется" in text and "gamma: не планируется" in text, text


def test_a_placeholder_voice_is_not_planned_and_the_launch_check_refuses():
    """CF-0659: a channel with a pipeline whose voice is still a TODO
    placeholder (ExampleScience until CF-0565) is not planned - the tick never
    starts it - and the console's launch check fails its `voice` guard."""
    r = _root(A, B)
    doc = json.loads((r / "channels" / f"{B}.json").read_text(encoding="utf-8"))
    doc["voice_profile"] = {"engine": "kokoro", "voice": "bm_george", "speed": 1.0, "lang": "b"}
    doc["voice_profile_note"] = "TODO CF-0565: a placeholder, not the choice."
    _w(r / "channels" / f"{B}.json", doc)
    p = bs.plan(r, IN_WINDOW, 2, open_rows=[])
    assert "голос" in p["channels"][B]["why_not"] and "CF-0565" in p["channels"][B]["why_not"], \
        p["channels"][B]
    assert all(d["channel"] in (None, A) for d in p["days"])
    chk = bs.launch_check(B, r, IN_WINDOW, open_rows=[])
    voice = [g for g in chk["guards"] if g["name"] == "voice"]
    assert not chk["ok"] and voice and not voice[0]["ok"], chk
    assert "CF-0565" in chk["why"], chk["why"]
    ok = bs.launch_check(A, r, IN_WINDOW, open_rows=[])
    assert [g["ok"] for g in ok["guards"] if g["name"] == "voice"] == [True], ok


def test_an_open_batch_makes_the_day_busy_and_a_stale_one_does_not():
    r = _root(A, B)
    d_open = r / "pipeline" / B / "2026-10-07T2100Z"
    d_open.mkdir(parents=True)
    p = bs.plan(r, IN_WINDOW, 2, open_rows=[(d_open, None, True)])
    d = _day(p)
    assert d["status"] == "busy" and d["channel"] == B and "идёт батч" in d["why"], d
    assert p["channels"][B]["open"] == ["2026-10-07T2100Z"]
    r2 = _root(A)
    stale = r2 / "pipeline" / A / "2026-10-01T0000Z"
    stale.mkdir(parents=True)
    p2 = bs.plan(r2, IN_WINDOW, 1, open_rows=[(stale, None, False)])
    assert _day(p2)["status"] == "planned", _day(p2)
    assert p2["stale_open"] == [f"{A} 2026-10-01T0000Z"], p2["stale_open"]


def test_a_batch_already_started_today_makes_the_day_done():
    r = _root(A)
    _runs(r, [{"channel": A, "id": "2026-10-07T2200Z", "started": "2026-10-07T22:00:00Z",
               "wall_s": 3600, "videos": 1}])        # 08.10 01:00 МСК
    p = bs.plan(r, IN_WINDOW, 2, open_rows=[])
    assert _day(p)["status"] == "done" and "сегодня батч уже был" in _day(p)["why"], _day(p)
    assert _day(p, 1)["status"] in ("planned", "idle")
    r2 = _root(A)
    (r2 / "pipeline" / A / "2026-10-07T2215Z").mkdir(parents=True)     # no summary yet
    assert _day(bs.plan(r2, IN_WINDOW, 1, open_rows=[]))["status"] == "done"


ORDER = ["rights-check", "batch-start", "pool-maintenance", "trend-hunter", "video-editor",
         "batch-done", "commit-records"]
BID = "2026-10-07T2215Z"                     # 08.10 01:15 МСК - today for IN_WINDOW


def _stopped_batch(root, ch=A, status="failed", reached=False, state=True):
    """A batch of today that the executor ran: batch-start failed (or, with
    `reached`, trend-hunter started and failed); the always-run tail ran."""
    d = root / "pipeline" / ch / BID
    d.mkdir(parents=True)
    (d / "run-executor.lock").write_text("pid 4242 since 2026-10-07T22:15:30Z\n")
    if not state:
        return d
    stages = {"rights-check": {"status": "done", "started": "x"},
              "batch-start": {"status": "failed", "started": "x"},
              "pool-maintenance": {"status": "skipped"},
              "trend-hunter": {"status": "skipped", "reason": "after failed stage batch-start"},
              "video-editor": {"status": "skipped"},
              "batch-done": {"status": "failed", "started": "x"},
              "commit-records": {"status": "done", "started": "x"}}
    if reached:
        stages["batch-start"] = {"status": "done", "started": "x"}
        stages["trend-hunter"] = {"status": "failed", "started": "2026-10-07T22:20:00Z"}
    _w(d / "run-state.json", {"version": 1, "task": "CF-0203", "channel": ch, "batch_id": BID,
                              "order": ORDER, "status": status,
                              "created": "2026-10-07T22:15:30Z", "current": None,
                              "stages": stages, "executor": {"pid": 4343}})
    return d


def _all_sources(root, pid=4242, at="2026-10-07T22:15:26Z"):
    """The launch row and the runs.jsonl row of that batch beside its folder."""
    _runs(root, [{"batch": f"{A}/{BID}", "id": BID, "channel": A,
                  "started": "2026-10-07T22:15:30Z"}])
    _w(root / "schedule" / "launches.jsonl",
       json.dumps({"at": at, "day": "2026-10-08", "channel": A, "pid": pid, "by": "user",
                   "kind": "manual"}) + "\n")


def _today_guard(root):
    chk = bs.launch_check(A, root, IN_WINDOW, open_rows=[],
                          environ={bs.STATE_ENV: str(root / "schedule")})
    return next(g for g in chk["guards"] if g["name"] == "today")


def test_a_batch_that_failed_before_trend_hunter_is_no_batch_of_the_day():
    """Hotfix 2.3.1: Science 2026-10-12T1908Z failed at batch-start, spent no
    Search quota - neither its folder, nor its runs.jsonl row, nor its launch
    (matched by pid, or by time) holds the day."""
    for pid, at in ((4242, "2026-10-07T21:00:00Z"), (1, "2026-10-07T22:15:26Z")):
        r = _root(A)
        _stopped_batch(r)
        _all_sources(r, pid, at)
        assert bs.started_on(bs.msk_day(bs.now_utc(IN_WINDOW)), r,
                             {bs.STATE_ENV: str(r / "schedule")}) == []
        g = _today_guard(r)
        assert g["ok"], g
        # the quota day stays free; the same channel is not repeated blindly on the
        # same (here: unknown) code - CF-0822 - but the day is not "done"
        d = _day(bs.plan(r, IN_WINDOW, 1, open_rows=[],
                         environ={bs.STATE_ENV: str(r / "schedule")}))
        assert d["status"] == "idle" and d["breaker"]["held"], d
    r = _root(A)
    _stopped_batch(r, status="halted")
    assert _today_guard(r)["ok"]


def test_a_batch_that_reached_trend_hunter_still_holds_the_day():
    r = _root(A)
    _stopped_batch(r, reached=True)
    _all_sources(r)
    g = _today_guard(r)
    assert not g["ok"] and "сегодня батч уже был" in g["line"], g
    # each source alone still counts
    r2 = _root(A)
    _all_sources(r2)                                   # no folder: launch + runs.jsonl
    assert not _today_guard(r2)["ok"]


def test_a_running_or_unrecorded_batch_still_holds_the_day():
    import fcntl
    r = _root(A)
    d = _stopped_batch(r)
    with open(d / "run-executor.lock", "a+") as fh:    # a live executor holds the lock
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert not _today_guard(r)["ok"]
    assert _today_guard(r)["ok"]
    for status in ("running", "paused", "done"):
        r = _root(A)
        _stopped_batch(r, status=status)
        assert not _today_guard(r)["ok"], status
    r = _root(A)
    _stopped_batch(r, state=False)                     # an old manual batch: no run-state
    g = _today_guard(r)
    assert not g["ok"] and "(pipeline/)" in g["line"], g
    _all_sources(r)
    assert not _today_guard(r)["ok"]


def test_the_window_comes_from_the_channel():
    r = _root(A, window={"window": "23:00", "tz": "Europe/Moscow", "window_hours": 2,
                         "min_feed_days": 3, "batch_feed_days": 5})
    _taken(r, A, ["2026-10-09", "2026-10-10", "2026-10-11"])
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = _day(p)
    assert d["status"] == "planned" and "окно 08.10 23:00 МСК–01:00" in bs.day_line(d), d
    assert "лента короче 5 дн. (на 3 дн.)" in d["why"], d
    assert "batch_schedule" in p["channels"][A]["window_source"]
    bad = _root(A, window={"window": "25:00"})
    pb = bs.plan(bad, IN_WINDOW, 1, open_rows=[])
    assert "not HH:MM" in pb["channels"][A]["why_not"], pb["channels"][A]


def test_a_window_already_gone_today_moves_to_tomorrow():
    r = _root(A)
    p = bs.plan(r, AFTER_WINDOW, 2, open_rows=[])
    assert _day(p)["status"] == "idle" and any("окно" in n and "прошло" in n
                                               for n in _day(p)["notes"]), _day(p)
    assert _day(p, 1)["status"] == "planned" and _day(p, 1)["channel"] == A


# ------------------------------------------------------------------ the switch
def test_the_switch_is_off_by_default_and_only_the_user_turns_it_on():
    r = _root(A)
    st = bs.switch_state(r)
    assert st["on"] is False and st["history"] == [] and "ВЫКЛЮЧЕН" in st["line"], st
    for by, note in (("operator", "x"), ("claude", "x"), ("user", "")):
        try:
            bs.set_switch(True, by, note, r)
            raise AssertionError(f"enable by {by!r} note {note!r} was taken")
        except bs.ScheduleError:
            pass
    assert not (r / "schedule" / "switch.json").exists()
    st = bs.set_switch(True, "user", "«включай» в чате 07.10", r, now="2026-10-07T10:00:00Z")
    assert st["on"] and "ВКЛЮЧЁН" in st["line"] and "«включай»" in st["line"], st
    st = bs.set_switch(False, "operator", None, r, now="2026-10-07T11:00:00Z")
    assert not st["on"], st
    assert [(h["action"], h["by"], h["at"]) for h in st["history"]] == [
        ("enable", "user", "2026-10-07T10:00:00Z"), ("disable", "operator", "2026-10-07T11:00:00Z")]
    out = io.StringIO()
    assert bs.main(["status", "--root", str(r)], out=out) == 0
    assert "disable by operator" in out.getvalue() and "enable by user" in out.getvalue()


def test_plan_tick_and_timer_never_write_the_switch():
    r = _root(A)
    bs.plan(r, IN_WINDOW, 3, open_rows=[])
    bs.tick(r, IN_WINDOW, open_rows=[])
    bs.tick(r, IN_WINDOW, dry_run=True, open_rows=[])
    bs.main(["install-timer", "--print", "--root", str(r)], out=io.StringIO(), err=io.StringIO())
    bs.main(["plan", "--root", str(r), "--now", IN_WINDOW], out=io.StringIO())
    assert not (r / "schedule" / "switch.json").exists()
    src = (ROOT / "shared" / "batch_schedule.py").read_text()
    # the definition, set_switch (the switch), set_channel_settings (CF-0605: the
    # console's overlay, schedule/channel-settings.json - never the switch) and
    # set_factory_settings (CF-0926: schedule/factory-settings.json - never the switch)
    assert src.count("_write_json_atomic(") == 4, "the switch has one writer (set_switch)"
    assert src.count("_write_json_atomic(d / SETTINGS,") == 1 and "SWITCH" not in \
        src.split("def set_channel_settings")[1].split("\ndef ")[0]
    assert src.count("_write_json_atomic(d / FACTORY_SETTINGS,") == 1 and "SWITCH" not in \
        src.split("def set_factory_settings")[1].split("\ndef ")[0]


def test_the_state_is_gitignored():
    assert "/schedule/" in (ROOT / ".gitignore").read_text().splitlines()
    assert bs.state_dir(None, environ={}) == ROOT / "schedule"


# ------------------------------------------------------------------ the tick
FAKE = TMP / "fake_executor.py"
_w(FAKE, "import json, sys\n"
         "from pathlib import Path\n"
         "root = Path(sys.argv[sys.argv.index('--root') + 1])\n"
         "with open(root / 'fake-launched.jsonl', 'a') as fh:\n"
         "    fh.write(json.dumps(sys.argv[1:]) + '\\n')\n")


def _on(r):
    bs.set_switch(True, "user", "«включай» (тест)", r, now="2026-10-07T10:00:00Z")


def _launched(r, wait=10.0):
    p = r / "fake-launched.jsonl"
    end = _time.monotonic() + wait
    while _time.monotonic() < end and not p.is_file():
        _time.sleep(0.05)
    _time.sleep(0.2)
    return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


def test_tick_with_the_switch_off_starts_nothing():
    r = _root(A)
    code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[])
    assert code == 0 and row is None and line.startswith("TICK no:") and "ВЫКЛЮЧЕН" in line, line
    assert _launched(r, 0.3) == [] and not (r / "schedule" / "launches.jsonl").exists()


def test_tick_guards_each_say_why():
    r = _root(A)
    _on(r)
    code, line, row = bs.tick(r, BEFORE_WINDOW, executor=FAKE, open_rows=[])
    assert row is None and "ещё не наступило" in line, line
    d = r / "pipeline" / A / "2026-10-07T2100Z"
    d.mkdir(parents=True)
    code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[(d, None, True)])
    assert row is None and "идёт батч" in line, line
    d.rmdir()
    _runs(r, [{"channel": A, "id": "2026-10-07T2200Z", "started": "2026-10-07T22:00:00Z"}])
    code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[])
    assert row is None and "сегодня батч уже был" in line, line
    r2 = _root(A)
    _on(r2)
    _pause(r2, A)
    code, line, row = bs.tick(r2, IN_WINDOW, executor=FAKE, open_rows=[])
    assert row is None and "на паузе" in line, line
    for root in (r, r2):
        assert _launched(root, 0.3) == [] and not (root / "schedule" / "launches.jsonl").exists()


def test_tick_on_and_in_the_window_starts_exactly_one_batch():
    r = _root(A)
    _on(r)
    old = os.environ.get("NOTIFY_STATE_DIR")
    os.environ["NOTIFY_STATE_DIR"] = str(r / "notify-state")
    try:
        code, line, row = bs.tick(r, IN_WINDOW, dry_run=True, executor=FAKE, open_rows=[])
        assert row is None and "would start" in line, line
        code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[])
        assert code == 0 and row and line.startswith(f"TICK started {A}"), line
        code2, line2, row2 = bs.tick(r, "2026-10-07T23:45:00Z", executor=FAKE, open_rows=[])
        assert row2 is None and "сегодня батч уже был" in line2, line2
        calls = _launched(r)
        assert calls == [["run", A, "--root", str(r.resolve())]], calls
        rows = bs.launches(r)
        assert len(rows) == 1 and rows[0]["day"] == "2026-10-08" and rows[0]["channel"] == A, rows
        assert Path(rows[0]["log"]).is_file()
        sent = [json.loads(x) for x in (r / "notify-state" / "sent.jsonl").read_text().splitlines()]
        assert [(s["kind"], s["channel"], s["key"]) for s in sent] == [
            ("batch_started", A, "batch_started:2026-10-08")], sent
        assert sent[0]["link"].endswith(f"/batches?channel={A}"), sent
        # CF-0925: the lines in words - Telegram gets the body, the journal one line
        body = sent[0]["body"]
        assert body.startswith(f"▶️ {A}: батч запущен по расписанию."), body
        assert "Зачем: готовых роликов меньше чем на" in body and "лента короче" not in body, body
        assert "Конец ≈ " in body and "\n" in body and "\n" not in sent[0]["text"], sent
    finally:
        if old is None:
            os.environ.pop("NOTIFY_STATE_DIR", None)
        else:
            os.environ["NOTIFY_STATE_DIR"] = old


# ---------------------------------------------- CF-0899: `claude` logged in
def _claude_stub(r, logged_in):
    """A stand-in `claude` that answers `auth status --json` only (and writes
    down every call): {"loggedIn": <bool>} - never the real CLI."""
    exe = r / "bin" / "claude"
    exe.parent.mkdir(parents=True, exist_ok=True)
    exe.write_text(f"#!{sys.executable}\n"
                   "import json, sys\nfrom pathlib import Path\n"
                   "here = Path(__file__).resolve().parent\n"
                   "with open(here / 'calls.log', 'a') as fh:\n"
                   "    fh.write(' '.join(sys.argv[1:]) + '\\n')\n"
                   "mode = (here / 'login.mode').read_text().strip()\n"
                   "if mode == 'garbled':\n    print('???'); sys.exit(0)\n"
                   "print(json.dumps({'loggedIn': mode == 'yes', 'authMethod': 'claude.ai'}))\n")
    exe.chmod(0o755)
    (exe.parent / "login.mode").write_text("yes" if logged_in else "no")
    return exe


def _login_env(r, exe):
    return {**os.environ, bs.CLAUDE_ENV: str(exe), "NOTIFY_STATE_DIR": str(r / "notify-state")}


def _sent(r):
    p = r / "notify-state" / "sent.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


@contextlib.contextmanager
def _notify_dir(r):
    old = os.environ.get("NOTIFY_STATE_DIR")
    os.environ["NOTIFY_STATE_DIR"] = str(r / "notify-state")
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("NOTIFY_STATE_DIR", None)
        else:
            os.environ["NOTIFY_STATE_DIR"] = old


def test_login_state_reads_auth_status_and_never_the_real_cli_off_the_factory_root():
    r = _root(A)
    assert bs.login_state(r, environ={})["checked"] is False      # a test root, no stand-in
    exe = _claude_stub(r, True)
    env = {bs.CLAUDE_ENV: str(exe)}
    assert bs.login_state(r, env)["ok"] is True
    (exe.parent / "login.mode").write_text("no")
    x = bs.login_state(r, env)
    assert x["ok"] is False and "/login" in x["line"], x
    (exe.parent / "login.mode").write_text("garbled")
    assert bs.login_state(r, env)["ok"] is None                   # unknown never holds a batch
    calls = (exe.parent / "calls.log").read_text().splitlines()
    assert calls and set(calls) == {"auth status --json"}, calls  # no `-p`, no tokens


def test_tick_does_not_open_a_batch_while_claude_is_not_logged_in_and_says_so_once_a_day():
    r = _root(A)
    _on(r)
    exe = _claude_stub(r, False)
    env = _login_env(r, exe)
    with _notify_dir(r):
        code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[], environ=env)
        assert row is None and "не залогинен" in line and "день не занят" in line, line
        code, line, row = bs.tick(r, "2026-10-07T23:45:00Z", executor=FAKE, open_rows=[],
                                  environ=env)
        assert row is None and "не залогинен" in line, line
        assert _launched(r, 0.3) == [] and bs.launches(r, env) == []
        need = [x for x in _sent(r) if x["kind"] == "needs_human"]
        assert [x["key"] for x in need] == ["claude_login:2026-10-08"], _sent(r)
        assert "/login" in need[0]["text"] and A in need[0]["text"], need
        # the user logs in: the next tick of the window starts the day's batch
        (exe.parent / "login.mode").write_text("yes")
        code, line, row = bs.tick(r, "2026-10-08T00:00:00Z", executor=FAKE, open_rows=[],
                                  environ=env)
        assert row and line.startswith(f"TICK started {A}"), line
        assert _launched(r) == [["run", A, "--root", str(r.resolve())]]


def _halted_batch(r, reason="NOT_LOGGED_IN: `claude` is not logged in (stage trend-hunter)"):
    d = r / "pipeline" / A / "2026-10-07T2330Z"
    d.mkdir(parents=True)
    _w(d / "run-state.json", {
        "status": "halted", "halt_reason": reason, "channel": A, "root": str(r.resolve()),
        "batch": str(d), "batch_id": d.name, "current": {"stage": "trend-hunter"},
        "next": "trend-hunter", "stages": {}, "order": [], "runs": {},
        "executor": {"pid": 999999, "started": "2026-10-07T23:30:00Z"},
        "login_halts": [{"at": "2026-10-07T23:31:00Z", "stage": "trend-hunter",
                         "reason": reason, "task": "CF-0899", "resumed": None}]})
    return d


def test_a_batch_halted_on_not_logged_in_is_resumed_by_the_tick_after_the_login():
    r = _root(A)
    _on(r)
    d = _halted_batch(r)
    exe = _claude_stub(r, False)
    env = _login_env(r, exe)
    rows = [(d, None, True)]
    with _notify_dir(r):
        # still not logged in: nothing starts, one needs_human a day, the stage named
        for at in ("2026-10-08T01:00:00Z", "2026-10-08T01:15:00Z"):
            code, line, row = bs.tick(r, at, executor=FAKE, open_rows=rows, environ=env)
            assert row is None and "trend-hunter" in line and "не залогинен" in line, line
        assert _launched(r, 0.3) == []
        assert [x["key"] for x in _sent(r) if x["kind"] == "needs_human"] == [
            "claude_login:2026-10-08"], _sent(r)
        # logged in again: the tick resumes it - no person
        (exe.parent / "login.mode").write_text("yes")
        code, line, row = bs.tick(r, "2026-10-08T01:30:00Z", executor=FAKE, open_rows=rows,
                                  environ=env)
        assert line.startswith(f"TICK resumed {A}") and row, line
        assert row["kind"] == "resume" and row["by"] == bs.LOGIN_BY and row["auto"], row
        calls = _launched(r)
        assert calls and calls[0][:4] == ["run", A, "--root", str(r.resolve())], calls
        assert "--resume" in calls[0] and Path(calls[0][-1]).resolve() == d.resolve(), calls
        # the batch is still halted (the stand-in did nothing): the next tick inside the
        # back-off does not start it again
        code, line, row = bs.tick(r, "2026-10-08T01:45:00Z", executor=FAKE, open_rows=rows,
                                  environ=env)
        assert row is None and "следующая попытка" in line, line
        assert len(_launched(r, 0.3)) == 1
        code, line, row = bs.tick(r, "2026-10-08T02:31:00Z", executor=FAKE, open_rows=rows,
                                  environ=env)
        assert line.startswith("TICK resumed"), line
        starts = [x for x in _sent(r) if x["kind"] == "batch_started"]
        assert len(starts) == 1 and starts[0]["key"].endswith(":auto:2026-10-08"), starts
        # resume rows are not batches of the day
        assert all(x.get("kind") == "resume" for x in bs.launches(r, env))


def test_a_batch_halted_for_another_reason_is_not_resumed_by_the_tick():
    r = _root(A)
    _on(r)
    d = _halted_batch(r, reason="something else")
    exe = _claude_stub(r, True)
    with _notify_dir(r):
        code, line, row = bs.tick(r, "2026-10-08T01:30:00Z", executor=FAKE,
                                  open_rows=[(d, None, True)], environ=_login_env(r, exe))
    assert row is None and "идёт батч" in line, line
    assert _launched(r, 0.3) == []


def test_tick_says_a_reminder_telegram_did_not_take_and_its_ceiling():
    """CF-0617: a reminder no outside backend took is not counted as sent - the
    tick line says so, the next tick tries again, the last try says exhausted."""
    import notify
    r = _root(A)
    env = {"NOTIFY_STATE_DIR": str(r / "notify-state"), "NOTIFY_BACKENDS": "log,telegram",
           "NOTIFY_TELEGRAM_TOKEN": "123:FakeTokenForTestsOnly", "NOTIFY_TELEGRAM_CHAT": "-1"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    old_post, old_max = notify._post, notify.REMINDER_MAX_ATTEMPTS

    def down(url, data, headers):
        raise RuntimeError("network: down")
    notify._post, notify.REMINDER_MAX_ATTEMPTS = down, 2
    try:
        notify.add_reminder("2026-10-08 02:00", "проверить ленту", root=r,
                            now="2026-10-07T20:00:00Z")
        code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[])
        assert "напоминания: отправлено 0, не ушло 1" in line and "исчерпано" not in line, line
        code, line, row = bs.tick(r, "2026-10-07T23:45:00Z", executor=FAKE, open_rows=[])
        assert "не ушло 1 (исчерпано попыток: 1)" in line, line
        assert "FakeToken" not in line
        assert [x["status"] for x in notify.reminders(r)] == ["exhausted"]
        code, line, row = bs.tick(r, "2026-10-08T00:00:00Z", executor=FAKE, open_rows=[])
        assert "напоминания" not in line, "no try past the ceiling"
    finally:
        notify._post, notify.REMINDER_MAX_ATTEMPTS = old_post, old_max
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_tick_sends_due_reminders_with_the_switch_off_and_starts_nothing():
    """CF-0606: an off schedule starts no batch but does not silence a reminder."""
    import notify
    r = _root(A)
    env = {"NOTIFY_STATE_DIR": str(r / "notify-state"), "NOTIFY_BACKENDS": "log"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        notify.add_reminder("2026-10-08 02:00", "проверить ленту", root=r,
                            now="2026-10-07T20:00:00Z")
        code, line, row = bs.tick(r, IN_WINDOW, dry_run=True, executor=FAKE, open_rows=[])
        assert notify.pending_reminders(r), "a dry run sends no reminder"
        code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[])
        assert code == 0 and row is None and "ВЫКЛЮЧЕН" in line, line
        assert "напоминания: отправлено 1" in line, line
        assert len(line.splitlines()) == 1
        assert _launched(r, 0.3) == [] and not (r / "schedule" / "launches.jsonl").exists()
        sent = [json.loads(x) for x in (r / "notify-state" / "sent.jsonl").read_text().splitlines()]
        assert [(s["kind"], s["key"]) for s in sent] == [("reminder", "reminder:R1")], sent
        assert notify.pending_reminders(r) == []
        code, line, row = bs.tick(r, "2026-10-07T23:45:00Z", executor=FAKE, open_rows=[])
        assert "напоминания" not in line, "sent once"
        assert not (r / "schedule" / "switch.json").exists(), "the tick never writes the switch"
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_tick_sends_the_studio_insurance_once_a_day_whatever_the_switch():
    """CF-0735: the tick is the periodic path of the Studio safety net - one
    Russian line with the center's link, at most once in 24 h; only the
    factory's own checkout unless asked (tests)."""
    r = _root(A)
    doc = json.loads((r / "channels" / f"{A}.json").read_text())
    doc["analyst"] = {"studio_read": {"last_videos": 2, "insurance_hours": 24,
                                      "hook_min_gap_hours": 3}}
    _w(r / "channels" / f"{A}.json", doc)
    env = {"NOTIFY_STATE_DIR": str(r / "notify-state"), "NOTIFY_BACKENDS": "log"}
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    sent = lambda: [json.loads(x) for x in (r / "notify-state" / "sent.jsonl")  # noqa: E731
                    .read_text().splitlines()] if (r / "notify-state" / "sent.jsonl").exists() \
        else []
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[])
            assert sent() == [] and "Studio" not in line, "a test root is not the checkout"
            code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[],
                                      studio_insurance=True, dry_run=True)
            assert sent() == [], "a dry run calls nobody"
            code, line, row = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[],
                                      studio_insurance=True)
            assert "страховка Studio: позвали пользователя" in line and \
                len(line.splitlines()) == 1, line
            got = sent()
            assert [g["kind"] for g in got] == ["needs_human"], got
            assert got[0]["text"].startswith(f"📊 Studio ни разу не читали ({A}) — "), got  # CF-0925
            # CF-0926: what came of the planned read and what is needed from the user
            assert "Плановое чтение: ещё ни разу не запускалось" in got[0]["body"], got
            assert "Нужно от вас: центр → «Прочитать Studio»" in got[0]["body"], got
            assert got[0]["link"] == "http://127.0.0.1:8790/", got
            code, line, row = bs.tick(r, "2026-10-08T03:00:00Z", executor=FAKE, open_rows=[],
                                      studio_insurance=True)
            assert "Studio" not in line and len(sent()) == 1, "once in 24 h"
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

def test_tick_cli_prints_one_line():
    r = _root(A)
    out = io.StringIO()
    assert bs.main(["tick", "--root", str(r), "--now", IN_WINDOW, "--executor", str(FAKE)], out=out) == 0
    assert len(out.getvalue().strip().splitlines()) == 1 and "TICK no:" in out.getvalue()


# ------------------------------------------------------------------ the timer
def test_install_timer_prints_and_installs_nothing():
    r = _root(A)
    home = TMP / "home"
    home.mkdir(exist_ok=True)
    called = []
    saved = (bs.subprocess.run, bs.subprocess.Popen, bs.os.system, os.environ.get("HOME"))
    bs.subprocess.run = lambda *a, **k: called.append(("run", a))
    bs.subprocess.Popen = lambda *a, **k: called.append(("Popen", a))
    bs.os.system = lambda *a, **k: called.append(("system", a))
    os.environ["HOME"] = str(home)
    try:
        out, err = io.StringIO(), io.StringIO()
        assert bs.main(["install-timer", "--print", "--root", str(r)], out=out, err=err) == 0
        e2 = io.StringIO()
        assert bs.main(["install-timer", "--root", str(r)], out=io.StringIO(), err=e2) == 2
    finally:
        bs.subprocess.run, bs.subprocess.Popen, bs.os.system = saved[:3]
        if saved[3] is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = saved[3]
    assert called == [], called
    assert list(home.rglob("*")) == [], list(home.rglob("*"))
    d = plistlib.loads(out.getvalue().encode())
    assert d["Label"] == bs.LABEL and d["ProgramArguments"][2:] == ["tick", "--root", str(r.resolve())], d
    assert d["StartInterval"] == bs.INTERVAL_S and d["RunAtLoad"] is False, d
    assert "launchctl bootstrap" in err.getvalue() and "launchctl bootout" in err.getvalue()
    assert "only --print" in e2.getvalue()
    assert not (r / "schedule").exists()


# ------------------------------------------------------------------ the factory's state
def test_the_factory_state_has_the_plan_and_the_switch():
    r = _root(A, B)
    _pause(r, B)
    aux = {"needs_you_dir": r / "no-needs-you", "env_file": r / "no.env",
           "environ": {"PUBLISHER_TOKEN_FILE": str(r / "no" / "t.json"),
                       "PUBLISHER_CLIENT_SECRET_FILE": str(r / "no" / "c.json")}}
    d = collect.collect(r, IN_WINDOW, open_rows=[], **aux)
    s = d["schedule"]
    assert s["ok"] and s["switch"]["on"] is False and len(s["rows"]) == bs.PLAN_DAYS, s
    assert s["rows"][0].startswith("08.10") and f"{A}: окно" in s["rows"][0], s["rows"]
    ca = next(c for c in d["channels"] if c["id"] == A)["schedule"]
    cb = next(c for c in d["channels"] if c["id"] == B)["schedule"]
    assert ca["ok"] and any("окно" in x for x in ca["rows"]), ca
    assert cb["ok"] and "батча этого канала в плане нет" in cb["rows"][0], cb
    _on(r)
    d2 = collect.collect(r, IN_WINDOW, open_rows=[], **aux)
    assert d2["schedule"]["switch"]["on"], d2["schedule"]["switch"]


def _api_data_root(mark):
    """CF-0618: a root with an API row, analytics files and a publisher .env
    whose token state carries a revocation mark at `mark`."""
    sys.path.insert(0, str(ROOT / "agents" / "publisher"))
    import publisher_auth as pa                                 # noqa: PLC0415
    import publisher_config                                     # noqa: PLC0415
    r = _root("example-film")
    vid = "APIvid12345"
    _w(r / "publish" / "uploads.json", {"uploads": [{
        "channel": "example-film", "entry_id": "example-film/b/harbourlights", "slug": "harbourlights",
        "video_id": vid, "url": f"https://youtube.com/shorts/{vid}", "source": "api",
        "recorded_at": "2026-10-01T00:00:00Z", "uploaded_at": "2026-10-01T00:00:00Z",
        "api_refreshed_at": "2026-10-07T00:00:00Z", "publish_day": "2026-10-02"}]})
    a = r / "analytics" / "example-film"
    a.mkdir(parents=True)
    (a / "daily.jsonl").write_text("")
    (a / "studio.jsonl").write_text("")
    env = r / "pub.env"
    env.write_text(f"PUBLISHER_TOKEN_FILE={r}/sec/tok.oauth-token.json\n"
                   f"PUBLISHER_CLIENT_SECRET_FILE={r}/sec/cs.json\n")
    cfg = publisher_config.load(env, environ={})
    pa.write_state(cfg, {"authorized_at": "2026-09-01T00:00:00Z", "invalid_grant_at": mark})
    return r, env, a


def test_the_tick_runs_the_api_data_auto_run_only_when_due():
    r, env, a = _api_data_root("2026-09-20T00:00:00Z")           # 18 days before IN_WINDOW
    code, line, _ = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[], publisher_env=env)
    assert code == 0 and (a / "daily.jsonl").exists() and "API Data" not in line, line
    r, env, a = _api_data_root("2026-09-10T00:00:00Z")           # 28 days
    bs.tick(r, IN_WINDOW, dry_run=True, executor=FAKE, open_rows=[], publisher_env=env)
    assert (a / "daily.jsonl").exists(), "a dry run deletes nothing"
    bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[])
    assert (a / "daily.jsonl").exists(), "another root without a publisher env: not run"
    code, line, _ = bs.tick(r, IN_WINDOW, executor=FAKE, open_rows=[], publisher_env=env)
    assert code == 0 and "API Data удалены" in line, line
    assert not (a / "daily.jsonl").exists() and (a / "studio.jsonl").exists()
    assert json.loads((r / "publish" / "uploads.json").read_text())["uploads"] == []


def _st_env(r):
    return {bs.STATE_ENV: str(r / "schedule")}


def test_started_on_records_name_the_batch_the_source_and_the_line():
    """CF-0724: `started_on(records=True)` is the plain call's evidence as
    `{batch, source, line}` - the same lines in the same order; the batch as
    `<dir>/<batch_id>` (a runs.jsonl row by its `batch`, else channel + id; a
    folder by its path; a launch by the folder it made, else None)."""
    day = bs.msk_day(bs.now_utc(IN_WINDOW))
    r = _root(A, B)
    _runs(r, [{"channel": A, "id": "2026-10-07T2200Z", "started": "2026-10-07T22:00:00Z"},
              {"batch": f"{B}/2026-10-07T2205Z", "id": "2026-10-07T2205Z", "channel": B,
               "started": "2026-10-07T22:05:00Z"},
              {"channel": A, "id": "2026-10-01T2200Z", "started": "2026-10-01T22:00:00Z"}])
    (r / "pipeline" / A / BID).mkdir(parents=True)
    (r / "pipeline" / "backfill" / BID).mkdir(parents=True)
    _w(r / "schedule" / "launches.jsonl", "".join(json.dumps(x) + "\n" for x in (
        {"at": "2026-10-07T22:14:00Z", "day": "2026-10-08", "channel": A, "pid": 7, "by": "tick"},
        {"at": "2026-10-07T23:00:00Z", "day": "2026-10-08", "channel": B, "pid": 8,
         "by": "user", "kind": "manual"},
        {"at": "2026-10-07T23:10:00Z", "day": "2026-10-08", "channel": A, "pid": 9,
         "kind": "resume", "batch": str(r / "pipeline" / A / BID)})))
    lines = bs.started_on(day, r, _st_env(r))
    recs = bs.started_on(day, r, _st_env(r), records=True)
    assert [x["line"] for x in recs] == lines and len(lines) == 5, (lines, recs)
    assert all(set(x) == {"batch", "source", "line"} for x in recs), recs
    assert [(x["batch"], x["source"]) for x in recs] == [
        (f"{A}/2026-10-07T2200Z", "pipeline/runs.jsonl"),
        (f"{B}/2026-10-07T2205Z", "pipeline/runs.jsonl"),
        (f"{A}/{BID}", "pipeline/"),
        (f"{A}/{BID}", "schedule/launches.jsonl"),      # made the folder 1 min after `at`
        (None, "schedule/launches.jsonl"),              # beta's folder is not made yet
    ], recs
    assert bs.started_batches(recs) == [f"{A}/2026-10-07T2200Z", f"{B}/2026-10-07T2205Z",
                                        f"{A}/{BID}"]
    # nothing that day: no records either
    r2 = _root(A)
    assert bs.started_on(day, r2, _st_env(r2), records=True) == [] \
        and bs.started_on(day, r2, _st_env(r2)) == []


def test_a_batch_that_spent_no_quota_has_no_record_either():
    r = _root(A)
    _stopped_batch(r)
    _all_sources(r)
    day = bs.msk_day(bs.now_utc(IN_WINDOW))
    assert bs.started_on(day, r, _st_env(r), records=True) == []
    assert _today_guard(r)["batches"] == []


def test_the_open_and_today_guards_name_their_batches_and_keep_their_keys():
    """CF-0724: `open` and `today` carry `batches` - `["<dir>/<batch_id>"]` of
    the fresh open batches / of what `started_on` names for today, `[]` when
    none; name, ok, line as before; the other guards gain nothing."""
    r = _root(A)
    chk = bs.launch_check(A, r, IN_WINDOW, open_rows=[], environ=_st_env(r))
    g = {x["name"]: x for x in chk["guards"]}
    assert chk["ok"], chk
    assert g["open"] == {"name": "open", "ok": True, "line": "открытого батча нет",
                         "batches": []}, g["open"]
    assert g["today"] == {"name": "today", "ok": True, "line": "сегодня батча ещё не было",
                          "batches": []}, g["today"]
    assert all(set(x) == {"name", "ok", "line"} for n, x in g.items()
               if n not in ("open", "today")), g
    a = r / "pipeline" / A / BID
    old = r / "pipeline" / A / "2026-10-01T0900Z"
    a.mkdir(parents=True)
    old.mkdir(parents=True)
    _runs(r, [{"batch": f"{A}/{BID}", "id": BID, "channel": A, "started": "2026-10-07T22:15:30Z"}])
    rows = [(a, None, True), (old, None, False)]
    chk = bs.launch_check(A, r, IN_WINDOW, open_rows=rows, environ=_st_env(r))
    g = {x["name"]: x for x in chk["guards"]}
    assert not g["open"]["ok"] and g["open"]["line"].startswith(f"идёт батч {A} {BID}"), g
    assert g["open"]["batches"] == [f"{A}/{BID}"], g["open"]       # the stale one is not
    assert not g["today"]["ok"] and g["today"]["batches"] == [f"{A}/{BID}"], g["today"]
    assert g["today"]["line"].startswith(f"сегодня батч уже был: {A} {BID} (pipeline/runs.jsonl)")
    assert chk["why"] == g["open"]["line"], chk


# ------------------------------------------------------------------ CF-0785: the day's kind
def test_every_day_has_a_documented_kind_one_per_why_branch():
    r = _root(A, B)
    p = bs.plan(r, IN_WINDOW, 7, open_rows=[])
    for d in p["days"]:
        assert d.get("kind") in bs.DAY_KINDS, d
        assert d["why"], d                                     # the text stays
    assert {d["kind"] for d in p["days"] if d["status"] == "planned"} <= {"needs_batch"}
    assert {d["kind"] for d in p["days"] if d["status"] == "idle"} <= {
        "fed", "nobody_plannable", "nobody_available"}, p["days"]
    # running / done_today
    d_open = r / "pipeline" / B / "2026-10-07T2100Z"
    d_open.mkdir(parents=True)
    assert _day(bs.plan(r, IN_WINDOW, 1, open_rows=[(d_open, None, True)]))["kind"] == "running"
    rd = _root(A)
    _runs(rd, [{"channel": A, "id": "2026-10-07T2200Z", "started": "2026-10-07T22:00:00Z",
                "wall_s": 3600, "videos": 1}])
    assert _day(bs.plan(rd, IN_WINDOW, 1, open_rows=[]))["kind"] == "done_today"
    # fed
    rf = _root(A)
    _taken(rf, A, _span("2026-10-09", 14))
    d = _day(bs.plan(rf, IN_WINDOW, 1, open_rows=[]))
    assert d["kind"] == "fed" and d["why"].startswith("батч не нужен"), d
    assert "covers_days" not in d and "first_empty_slot" not in d, d
    # nobody_available: the window is gone today / the only channel is paused
    d = _day(bs.plan(_root(A), AFTER_WINDOW, 1, open_rows=[]))
    assert d["kind"] == "nobody_available" and d["why"].startswith("некого планировать: "), d
    rp = _root(A)
    _pause(rp, A)
    d = _day(bs.plan(rp, IN_WINDOW, 1, open_rows=[]))
    assert d["kind"] == "nobody_available" and d["notes"], d
    # nobody_plannable: no channel with a slot and a run_plan at all
    rn = _root()
    _w(rn / "channels" / f"{A}.json", {"channel_id": A, "run_plan": {"stages": []}})
    d = _day(bs.plan(rn, IN_WINDOW, 1, open_rows=[]))
    assert d["kind"] == "nobody_plannable" and d["notes"] == [], d
    assert d["why"] == "некого планировать: ни у одного канала нет слота и run_plan", d


def test_a_needed_batch_names_the_days_it_covers_and_the_first_empty_slot():
    r = _root(A)
    _runs(r, [{"channel": A, "id": "2026-10-01T0000Z", "started": "2026-10-01T00:00:00Z",
               "wall_s": 24 * 3600, "videos": 3}])      # ends 09.10 02:30 МСК, + lead 2 h
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = _day(p)
    assert d["kind"] == "needs_batch" and d["status"] == "planned", d
    assert d["first_empty_slot"] == "2026-10-08T22:00:00Z", d      # 09.10 01:00 МСК
    assert d["fills"][0] == "2026-10-09T22:00:00Z", d               # 10.10 - after est_end + lead
    assert d["first_empty_slot"] < d["fills"][0]
    assert d["covers_days"] == ["2026-10-10", "2026-10-11", "2026-10-12"], d
    # without a long batch the first empty slot is the first fill
    p2 = bs.plan(_root(A), IN_WINDOW, 1, open_rows=[])
    d2 = _day(p2)
    assert d2["first_empty_slot"] == d2["fills"][0] == "2026-10-08T22:00:00Z", d2
    assert d2["covers_days"] == sorted(d2["covers_days"]) and len(d2["covers_days"]) == 3, d2
    json.dumps(p)                                                   # JSON-safe



# ------------------------------------------------------------------ CF-0787: the quota day
SCI_BID = "2026-10-17T0817Z"                 # 17.10 11:17 МСК - after the 10:00 МСК reset (PDT)


def _science_batch(root, ch=B, bid=SCI_BID, spent=66):
    """The 17.10 incident: a manual batch of `ch` (Science) that spent `spent`
    of the quota day's 100 search.list calls, with its launch row."""
    d = root / "pipeline" / ch / bid
    _w(d / "01-trend-hunter.json", {"search_quota": {"spent_searches": spent,
                                                     "searches_before_stage": 0}})
    at = bs.qday().batch_start(bid)
    rows = (root / "schedule" / "launches.jsonl")
    old = rows.read_text() if rows.is_file() else ""
    _w(rows, old + json.dumps({"at": at.strftime("%Y-%m-%dT%H:%M:%SZ"),
                               "day": bs.msk_day(at).isoformat(), "channel": ch, "pid": 1,
                               "by": bs.MANUAL_BY, "kind": "manual"}) + "\n")
    return d


def _days(p):
    return {d["day"]: d for d in p["days"]}


def test_the_quota_day_is_pacific_and_follows_dst():
    from datetime import date as _date
    q = bs.quota_day
    assert q(bs.parse_ts("2026-10-17T08:17:00Z")).isoformat() == "2026-10-17"
    assert q(bs.parse_ts("2026-10-17T23:00:00Z")).isoformat() == "2026-10-17"   # 18.10 02:00 МСК
    assert q(bs.parse_ts("2026-10-18T23:00:00Z")).isoformat() == "2026-10-18"   # 19.10 02:00 МСК
    s, e = bs.qday().bounds(_date(2026, 10, 17))
    assert (s.hour, e.hour) == (7, 7), (s, e)                                    # PDT: 07:00Z
    s, e = bs.qday().bounds(_date(2026, 11, 1))                                  # the 25-hour day
    assert (s.hour, e.hour, (e - s).total_seconds()) == (7, 8, 25 * 3600), (s, e)
    s, e = bs.qday().bounds(_date(2026, 11, 2))
    assert (s.hour, e.hour) == (8, 8), (s, e)                                    # PST: 08:00Z


def test_a_manual_science_batch_after_the_reset_blocks_the_next_reel_window():
    """17.10: Science 2026-10-17T0817Z (manual, 11:17 МСК) took the quota day
    17.10; Reel's window 18.10 02:00 МСК (23:00Z 17.10) is in it - blocked,
    and the plan names the next window, 19.10 02:00 МСК (quota day 18.10)."""
    r = _root(A, B)                      # alpha = Reel, beta = Science
    _taken(r, B, _span("2026-10-17", 20))   # Science's feed is full
    _science_batch(r)
    env = {bs.STATE_ENV: str(r / "schedule")}
    p = bs.plan(r, "2026-10-17T12:00:00Z", 3, open_rows=[], environ=env)       # 15:00 МСК
    days = _days(p)
    d17, d18, d19 = days["2026-10-17"], days["2026-10-18"], days["2026-10-19"]
    assert p["quota_day"] == "2026-10-17", p["quota_day"]
    assert d17["kind"] == "done_today" and "сегодня батч уже был" in d17["why"], d17
    assert f"{B} {SCI_BID}" in d17["why"] and "сутки квоты YouTube 17.10" in d17["why"], d17
    assert d18["status"] == "done" and d18["kind"] == "quota_day_taken", d18
    assert d18["quota_day"] == "2026-10-17" and d18["channel"] is None, d18
    assert d18["next_windows"] == {A: "2026-10-18T23:00:00Z"}, d18
    assert "19.10 02:00 МСК" in d18["why"] and "18.10 02:00 МСК" in d18["why"], d18
    assert any(n.startswith(f"{A}: окно 18.10 02:00 МСК") and SCI_BID in n
               for n in d18["notes"]), d18["notes"]
    assert d19["status"] == "planned" and d19["channel"] == A, d19
    assert d19["window_start"] == "2026-10-18T23:00:00Z" and d19["quota_day"] == "2026-10-18"
    lines = "\n".join(bs.plan_lines(p))
    assert "18.10 вс  —  сутки квоты YouTube 17.10 (10:00 МСК 17.10 – 10:00 МСК 18.10) уже " \
           "заняты" in lines, lines
    assert "19.10 пн  alpha: окно 19.10 02:00 МСК–05:00" in lines, lines
    # the existing rule picks the 19.10 channel: the nearest empty slot - with
    # Reel's feed at the batch threshold (CF-0922: 14 days) at the 18.10 window and
    # one day short of it at the 19.10 one (17.10-01.11), Science (empty from
    # 19.10) gets it
    r2 = _root(A, B)
    _taken(r2, A, _span("2026-10-17", 16))
    _science_batch(r2)
    p2 = bs.plan(r2, "2026-10-17T12:00:00Z", 3, open_rows=[],
                 environ={bs.STATE_ENV: str(r2 / "schedule")})
    d18, d19 = _days(p2)["2026-10-18"], _days(p2)["2026-10-19"]
    assert d18["kind"] == "quota_day_taken" and set(d18["next_windows"]) == {B}, d18
    assert d19["status"] == "planned" and d19["channel"] == B, d19
    assert "ближайший пустой слот раньше, чем у alpha" in d19["why"], d19


def test_the_tick_refuses_the_reel_window_in_the_science_quota_day():
    r = _root(A, B)
    _taken(r, B, _span("2026-10-17", 20))
    _science_batch(r)
    _on(r)
    code, line, row = bs.tick(r, "2026-10-17T23:30:00Z", dry_run=True, executor=FAKE,
                              open_rows=[], environ={bs.STATE_ENV: str(r / "schedule")})
    assert code == 0 and row is None and line.startswith("TICK no: сегодня батч уже был"), line
    assert SCI_BID in line and "сутки квоты YouTube 17.10" in line, line
    code, line, row = bs.tick(r, "2026-10-18T23:30:00Z", dry_run=True, executor=FAKE,
                              open_rows=[], environ={bs.STATE_ENV: str(r / "schedule")})
    assert line.startswith("TICK would start (dry run)") and A in line, line
    assert _launched(r, 0.3) == []


def test_the_button_counts_the_quota_day_too():
    r = _root(A, B)
    _science_batch(r)
    env = {bs.STATE_ENV: str(r / "schedule")}

    def today(now):
        chk = bs.launch_check(A, r, now, open_rows=[], environ=env)
        return chk, next(g for g in chk["guards"] if g["name"] == "today")

    chk, g = today("2026-10-18T05:00:00Z")            # 18.10 08:00 МСК - still quota day 17.10
    assert not g["ok"] and SCI_BID in g["line"] and chk["quota_day"] == "2026-10-17", g
    assert "сброса квоты 18.10 10:00 МСК" in g["line"], g
    assert g["batches"] == [f"{B}/{SCI_BID}"], g
    chk, g = today("2026-10-18T07:30:00Z")            # 10:30 МСК - the quota day 18.10
    assert g["ok"] and chk["today"] == chk["quota_day"] == "2026-10-18", (chk, g)


def test_november_pst_a_1030_window_falls_in_the_previous_quota_day():
    """From 01.11.2026 (PST) the reset is 08:00Z = 11:00 МСК: a batch at 11:30
    МСК on 01.11 and the 10:30 МСК window of 02.11 share the quota day 01.11;
    in October (PDT, reset 10:00 МСК) the same pair does not."""
    win = {"window": "10:30", "tz": "Europe/Moscow", "window_hours": 3, "min_feed_days": 3}
    r = _root(A, window=win)
    _science_batch(r, ch=A, bid="2026-11-01T0830Z")            # 01.11 11:30 МСК
    p = bs.plan(r, "2026-11-01T09:00:00Z", 3, open_rows=[],
                environ={bs.STATE_ENV: str(r / "schedule")})
    days = _days(p)
    d2 = days["2026-11-02"]
    assert d2["kind"] == "quota_day_taken" and d2["quota_day"] == "2026-11-01", d2
    assert d2["next_windows"] == {A: "2026-11-03T07:30:00Z"}, d2       # 03.11 10:30 МСК
    assert days["2026-11-03"]["status"] == "planned", days["2026-11-03"]
    assert days["2026-11-03"]["quota_day"] == "2026-11-02", days["2026-11-03"]
    r2 = _root(A, window=win)
    _science_batch(r2, ch=A, bid="2026-10-20T0830Z")           # 20.10 11:30 МСК (PDT)
    p2 = bs.plan(r2, "2026-10-20T09:00:00Z", 2, open_rows=[],
                 environ={bs.STATE_ENV: str(r2 / "schedule")})
    d21 = _days(p2)["2026-10-21"]
    assert d21["status"] == "planned" and d21["quota_day"] == "2026-10-21", d21

# ------------------------------------------------------------------ CF-0922
def test_a_full_three_day_horizon_still_needs_the_daily_batch():
    """CF-0922 (06.11: no batch at all): the horizon is 3 days and the morning
    fills it from the reserve, so the feed always covers 3 days. The threshold of
    the tick is `batch_feed_days` (14 by default), not the horizon - the batch is
    needed; the one batch of a quota day still holds."""
    r = _root(A, window={"window": "02:00", "tz": "Europe/Moscow", "window_hours": 3,
                         "min_feed_days": 3})
    _taken(r, A, _span("2026-10-09", 3))           # 09-11.10: the whole horizon (08.10 + 3)
    w = bs.window_config(A, r)
    assert w["min_feed_days"] == 3 and w["batch_feed_days"] == 14, w
    p = bs.plan(r, IN_WINDOW, 1, open_rows=[])
    d = _day(p)
    assert d["status"] == "planned" and d["kind"] == "needs_batch", d
    assert "лента короче 14 дн. (на 3 дн.)" in d["why"] and "пусто 12.10" in d["why"], d
    assert p["channels"][A]["min_feed_days"] == 3 and p["channels"][A]["batch_feed_days"] == 14
    text = "\n".join(bs.plan_lines(p))
    assert "горизонт ленты 3 дн., порог батча 14 дн." in text, text
    env = {bs.STATE_ENV: str(r / "schedule")}
    _on(r)
    code, line, row = bs.tick(r, IN_WINDOW, dry_run=True, executor=FAKE, open_rows=[],
                              environ=env)
    assert line.startswith("TICK would start (dry run)") and A in line, line
    # one batch a quota day: a batch already started in it - no second one
    _runs(r, [{"channel": A, "id": "2026-10-07T2200Z", "started": "2026-10-07T22:00:00Z",
               "wall_s": 3600, "videos": 1}])
    code, line, row = bs.tick(r, IN_WINDOW, dry_run=True, executor=FAKE, open_rows=[],
                              environ=env)
    assert code == 0 and row is None and line.startswith("TICK no: сегодня батч уже был"), line
    assert _launched(r, 0.3) == []


def test_the_batch_threshold_is_its_own_setting_never_below_the_horizon():
    """CF-0922: `batch_feed_days` - DEFAULTS, the channel's block, the center's
    overlay and `settings --batch-feed-days`; set nowhere it is 14 raised to
    min_feed_days; set below min_feed_days it is refused."""
    assert bs.DEFAULTS["batch_feed_days"] == 14 and "batch_feed_days" in bs.SETTINGS_KEYS
    assert bs.validate_settings({"batch_feed_days": "7"}) == {"batch_feed_days": 7}
    for bad in (0, 2.5, 31, "x"):
        try:
            bs.validate_settings({"batch_feed_days": bad})
            raise AssertionError(f"batch_feed_days {bad!r} accepted")
        except bs.ScheduleError as e:
            assert "порог батча" in str(e), e
    hi = _root(A, window={"min_feed_days": 20})
    w = bs.window_config(A, hi)
    assert w["min_feed_days"] == 20 and w["batch_feed_days"] == 20, w
    low = _root(A, window={"min_feed_days": 5, "batch_feed_days": 4})
    pb = bs.plan(low, IN_WINDOW, 1, open_rows=[])
    assert "batch_feed_days 4 < min_feed_days 5" in pb["channels"][A]["why_not"], pb["channels"][A]
    r = _root(A, window={"min_feed_days": 3})
    env = {bs.STATE_ENV: str(r / "schedule")}
    got = bs.set_channel_settings(A, {"batch_feed_days": 7}, "user", root=r, environ=env)
    assert got["changed"] == {"batch_feed_days": [14, 7]}, got
    assert got["settings"]["batch_feed_days"] == 7 and got["settings"]["min_feed_days"] == 3
    w = bs.window_config(A, r, environ=env)
    assert (w["min_feed_days"], w["batch_feed_days"]) == (3, 7), w
    try:
        bs.set_channel_settings(A, {"min_feed_days": 8}, "user", root=r, environ=env)
        raise AssertionError("a horizon over the batch threshold accepted")
    except bs.ScheduleError as e:
        assert "batch_feed_days 7 < min_feed_days 8" in str(e), e
    assert bs.window_config(A, r, environ=env)["min_feed_days"] == 3   # nothing written
    out = io.StringIO()
    old = os.environ.get(bs.STATE_ENV)
    os.environ[bs.STATE_ENV] = env[bs.STATE_ENV]
    try:
        assert bs.main(["settings", A, "--by", "user", "--batch-feed-days", "10",
                        "--root", str(r)], out=out) == 0
    finally:
        if old is None:
            os.environ.pop(bs.STATE_ENV, None)
        else:
            os.environ[bs.STATE_ENV] = old
    text = out.getvalue()
    assert "batch_feed_days 7 -> 10" in text and "горизонт ленты 3 дн., порог батча 10 дн." \
        in text, text


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
