#!/usr/bin/env python3
"""CF-0822: the schedule does not repeat the same failure blindly in the same
quota day (`shared/batch_schedule.py` `breakers`).

20.10 Tech 0831Z failed in pool-maintenance before trend-hunter, spent no quota,
and the tick at 11:01Z started 1101Z, which failed the same way. Pinned here,
on synthetic factories (a temp git repo, a stand-in executor, a temp
notification journal - nothing leaves the machine, no live data is read):

* the same code: the plan's day carries the breaker (failure's stage and
  handler; kind nobody_available - the center's closed list), the tick starts nothing, writes one `repeat_held` row of
  launches.jsonl and one notification per channel and quota day; a commit of
  records only (runs table, footage-wanted list) is still the same code;
* new code: the plan plans the channel again and the tick starts it once; when
  that repeat fails on the new code (known from the tick's launch row when it
  failed before its run header) the breaker holds again;
* «запускай» (`launch_check` / `manual_launch`, kind manual) is not held, and a
  `repeat_held` row is no batch of the day;
* another channel may take the day; the next quota day is free;
* `status --json` / `plan --json` carry the breaker.
"""
import io
import json
import os
import subprocess
import sys
import time as _time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import batch_schedule as bs         # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("repeat-breaker-test-")
A, B = "alpha", "beta"
SLOT = {"time": "01:00", "tz": "Europe/Moscow", "per_day": 1, "lead_hours": 2}
WINDOW = {"window": "14:00", "tz": "Europe/Moscow", "window_hours": 3, "min_feed_days": 3}
FAILED = "2026-10-20T0831Z"          # quota day 20.10 (PDT: 07:00Z 20.10 - 07:00Z 21.10)
NOW = "2026-10-20T11:01:00Z"         # 14:01 МСК - inside the 14:00 window
BEFORE = "2026-10-20T10:30:00Z"      # 13:30 МСК - before it
ORDER = ["rights-check", "batch-start", "pool-maintenance", "trend-hunter", "video-editor",
         "batch-done", "commit-records"]
REASON = ("handler pool-remeasure-captions failed: step 0 (python3 run_checks.py) exited 5; "
          "log logs/pool-remeasure-captions_pool-maintenance.s0.a0.log")
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


def git(d, *args):
    cp = subprocess.run(["git", "-C", str(d), *args], capture_output=True, text=True,
                        timeout=30)
    assert cp.returncode == 0, (args, cp.stderr)
    return cp.stdout.strip()


def commit(d, rel, text, msg):
    _w(d / rel, text)
    git(d, "add", rel)
    git(d, "commit", "-q", "-m", msg)
    return git(d, "rev-parse", "HEAD")


def factory(*chans):
    """A root that is a git repo of its own (code + channels committed), the
    state directories untracked."""
    _n[0] += 1
    r = TMP / f"r{_n[0]}"
    r.mkdir(parents=True)
    git(r, "init", "-q", "-b", "main")
    git(r, "config", "user.email", "t@example.invalid")
    git(r, "config", "user.name", "test")
    git(r, "config", "core.hooksPath", str(r / ".git" / "hooks"))   # no global hook
    _w(r / ".gitignore", "schedule/\nnotify-state/\nfake-launched.jsonl\npipeline/*/\n")
    for ch in chans or (A,):
        _w(r / "channels" / f"{ch}.json",
           {"channel_id": ch, "publisher": {"slot": SLOT}, "run_plan": {"stages": []},
            "batch_schedule": WINDOW})
    _w(r / "shared" / "code.py", "x = 1\n")
    git(r, "add", "-A")
    git(r, "commit", "-q", "-m", "init")
    return r


def env(r):
    return {bs.STATE_ENV: str(r / "schedule")}


def failed_batch(r, ch=A, bid=FAILED, head=None, header=True, created=None, status="failed"):
    """A batch that failed in pool-maintenance before trend-hunter (no quota
    spent); its run header names `head` (the root's HEAD by default)."""
    d = r / "pipeline" / ch / bid
    d.mkdir(parents=True)
    (d / "run-executor.lock").write_text("pid 4242\n")
    stages = {"rights-check": {"status": "done", "started": "x"},
              "batch-start": {"status": "done", "started": "x"},
              "pool-maintenance": {"status": "failed", "started": "x", "reason": REASON},
              "trend-hunter": {"status": "skipped",
                               "reason": "after failed stage pool-maintenance"},
              "video-editor": {"status": "skipped"},
              "batch-done": {"status": "done", "started": "x"},
              "commit-records": {"status": "done", "started": "x"}}
    start = bs._batch_start(bid)
    _w(d / "run-state.json", {
        "version": 1, "task": "CF-0203", "channel": ch, "batch_id": bid, "order": ORDER,
        "status": status, "created": created or bs.iso(start), "current": None,
        "stages": stages, "executor": {"pid": 4343}})
    if header:
        head = head or git(r, "rev-parse", "HEAD")
        _w(d / "RUN_EVENTS.jsonl", json.dumps({
            "ts": bs.iso(start), "kind": "marker", "status": "batch-start",
            "header": {"batch": f"{ch}/{bid}",
                       "git": {"root": {"commit": head, "dirty": False}, "agents": {},
                               "checkout": str(r)}}}) + "\n"
           + json.dumps({"ts": bs.iso(start), "kind": "marker", "status": "batch-done"}) + "\n")
    return d


def switch_on(r):
    bs.set_switch(True, "user", "«включай» (тест)", r, now="2026-10-19T10:00:00Z")


def launched(r, wait=10.0):
    p = r / "fake-launched.jsonl"
    end = _time.monotonic() + wait
    while _time.monotonic() < end and not p.is_file():
        _time.sleep(0.05)
    _time.sleep(0.2)
    return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


class notify_dir:
    def __init__(self, r):
        self.r = r

    def __enter__(self):
        self.old = os.environ.get("NOTIFY_STATE_DIR")
        os.environ["NOTIFY_STATE_DIR"] = str(self.r / "notify-state")
        return self

    def __exit__(self, *exc):
        if self.old is None:
            os.environ.pop("NOTIFY_STATE_DIR", None)
        else:
            os.environ["NOTIFY_STATE_DIR"] = self.old

    def sent(self):
        p = self.r / "notify-state" / "sent.jsonl"
        return [json.loads(x) for x in p.read_text().splitlines()] if p.is_file() else []


def day0(r, now=NOW):
    return bs.plan(r, now, 1, open_rows=[], environ=env(r))["days"][0]


# ------------------------------------------------------------------ the same code
def test_the_same_failure_on_the_same_code_is_not_repeated():
    r = factory()
    failed_batch(r)
    p = bs.plan(r, NOW, 2, open_rows=[], environ=env(r))
    d = p["days"][0]
    # the kind stays one the center knows (api PlanDay.kind is a closed list)
    assert d["status"] == "idle" and d["kind"] == "nobody_available", d
    b = d["breaker"]
    assert b["channel"] == A and b["batch"] == f"{A}/{FAILED}" and b["held"] is True, b
    assert b["stage"] == "pool-maintenance" and "pool-remeasure-captions" in b["failure"], b
    assert b["code_changed"] == [] and b["code_source"].startswith("RUN_EVENTS"), b
    assert b["quota_day"] == "2026-10-20" and b["until"] == "2026-10-21T07:00:00Z", b
    assert "повтор того же отказа не запущен" in d["why"] and FAILED in d["why"], d
    assert d["window_start"] == "2026-10-20T11:00:00Z" and d["next_windows"][A], d
    assert p["breakers"][A] == b and p["channels"][A]["breaker"] == b
    # the next day of the plan (another quota day) plans the channel again
    assert p["days"][1]["status"] == "planned" and p["days"][1]["channel"] == A, p["days"][1]
    assert any("повтор того же отказа" in x for x in bs.plan_lines(p))
    assert bs.factory_section(p)["breakers"] == [b["line"]]
    assert bs.channel_section(A, p)["breaker"] == b
    # a commit of records only (runs table, the footage-wanted list, task notes) is the same code
    commit(r, "pipeline/runs.jsonl", "{}\n", "batch records")
    commit(r, "analytics/alpha/footage-wanted.json", "{}\n", "footage list")
    commit(r, "tasks/CF-1.md", "x\n", "triage")
    assert day0(r)["breaker"]["held"]


def test_the_tick_holds_journals_once_and_notifies_once():
    r = factory()
    failed_batch(r)
    switch_on(r)
    with notify_dir(r) as nd:
        code, line, row = bs.tick(r, BEFORE, executor=FAKE, open_rows=[], environ=env(r))
        assert row is None and "повтор того же отказа не запущен" in line, line
        assert bs.launches(r, env(r)) == [] and nd.sent() == []     # the window has not come
        for now in (NOW, "2026-10-20T11:16:00Z", "2026-10-20T11:31:00Z"):
            code, line, row = bs.tick(r, now, executor=FAKE, open_rows=[], environ=env(r))
            assert code == 0 and row is None and line.startswith("TICK no:"), line
            assert "повтор того же отказа не запущен" in line, line
        assert launched(r, 0.3) == []
        rows = bs.launches(r, env(r))
        assert len(rows) == 1, rows
        h = rows[0]
        assert h["kind"] == "repeat_held" and h["channel"] == A and h["pid"] is None, h
        assert h["quota_day"] == "2026-10-20" and h["failed_batch"] == f"{A}/{FAILED}", h
        assert "pool-maintenance" in h["failure"] and h["task"] == "CF-0822", h
        sent = nd.sent()
        assert [(s["kind"], s["channel"], s["key"]) for s in sent] == [
            ("run_halted", A, f"repeat_held:{A}:2026-10-20")], sent
        # the held row is no batch of the day: the quota day is still free
        assert bs.started_on(bs.quota_day(bs.now_utc(NOW)), r, env(r), quota=True) == []
        # a dry run writes nothing
        r2 = factory()
        failed_batch(r2)
        switch_on(r2)
        bs.tick(r2, NOW, dry_run=True, executor=FAKE, open_rows=[], environ=env(r2))
        assert bs.launches(r2, env(r2)) == []


# ------------------------------------------------------------------ new code
def test_new_code_lets_one_repeat_through():
    r = factory()
    failed_batch(r)
    commit(r, "shared/code.py", "x = 2\n", "the fix")
    d = day0(r)
    assert d["status"] == "planned" and d["channel"] == A, d
    b = bs.breakers(r, NOW, env(r))[A]
    assert b["held"] is False and b["code_changed"] == ["root"], b
    assert "один повтор разрешён" in b["line"], b
    switch_on(r)
    with notify_dir(r):
        code, line, row = bs.tick(r, NOW, executor=FAKE, open_rows=[], environ=env(r))
    assert row and line.startswith(f"TICK started {A}"), line
    assert launched(r) == [["run", A, "--root", str(r.resolve())]]
    head = git(r, "rev-parse", "HEAD")
    assert row["code"] == {"root": head}, row
    # the repeat failed too, before its run header: its code is the launch row's
    failed_batch(r, bid="2026-10-20T1101Z", header=False, created="2026-10-20T11:01:30Z")
    b = bs.breakers(r, "2026-10-20T13:30:00Z", env(r))[A]
    assert b["batch"] == f"{A}/2026-10-20T1101Z" and b["held"] is True, b
    assert b["code_source"] == "schedule/launches.jsonl", b
    d = day0(r, "2026-10-20T13:30:00Z")
    assert d["breaker"]["held"] and d["kind"] == "nobody_available", d
    # an agent's other commit is new code too
    r2 = factory()
    (r2 / "agents" / "trend-hunter").mkdir(parents=True)
    ag = r2 / "agents" / "trend-hunter"
    git(ag, "init", "-q", "-b", "main")
    git(ag, "config", "user.email", "t@example.invalid")
    git(ag, "config", "user.name", "test")
    old = commit(ag, "x.py", "1\n", "one")
    failed_batch(r2)
    ev = r2 / "pipeline" / A / FAILED / "RUN_EVENTS.jsonl"
    lines = ev.read_text().splitlines()
    e = json.loads(lines[0])
    e["header"]["git"]["agents"] = {"trend-hunter": {"commit": old, "dirty": False}}
    ev.write_text("\n".join([json.dumps(e)] + lines[1:]) + "\n")
    assert bs.breakers(r2, NOW, env(r2))[A]["held"] is True
    commit(ag, "x.py", "2\n", "two")
    assert bs.breakers(r2, NOW, env(r2))[A]["code_changed"] == ["agents/trend-hunter"]


# ------------------------------------------------------------------ «запускай»
def test_a_manual_launch_is_not_held():
    r = factory()
    failed_batch(r)
    switch_on(r)
    with notify_dir(r):
        bs.tick(r, NOW, executor=FAKE, open_rows=[], environ=env(r))     # writes the held row
        chk = bs.launch_check(A, r, NOW, open_rows=[], environ=env(r), executor=FAKE)
        assert chk["ok"], chk
        assert chk["breaker"]["held"] is True, chk
        assert any("размыкатель повторов" in s for s in chk["skipped"]), chk["skipped"]
        ok, line, row = bs.manual_launch(A, r, NOW, confirmed=True, executor=FAKE,
                                         open_rows=[], environ=env(r))
    assert ok and row["kind"] == "manual", line
    assert launched(r) == [["run", A, "--root", str(r.resolve())]]


# ------------------------------------------------------------------ the others
def test_another_channel_takes_the_day_and_the_next_quota_day_is_free():
    r = factory(A, B)
    failed_batch(r)
    d = day0(r)
    assert d["status"] == "planned" and d["channel"] == B, d
    assert any("повтор того же отказа не запущен" in n for n in d["notes"]), d["notes"]
    r2 = factory()
    failed_batch(r2)
    assert bs.breakers(r2, "2026-10-21T11:01:00Z", env(r2)) == {}
    assert day0(r2, "2026-10-21T11:01:00Z")["status"] == "planned"
    # a batch that reached trend-hunter holds the quota day itself - no breaker
    r3 = factory()
    d3 = failed_batch(r3)
    st = json.loads((d3 / "run-state.json").read_text())
    st["stages"]["trend-hunter"] = {"status": "failed", "started": "x"}
    (d3 / "run-state.json").write_text(json.dumps(st))
    assert bs.breakers(r3, NOW, env(r3)) == {}
    assert day0(r3)["kind"] == "done_today"


def test_status_and_plan_json_carry_the_breaker():
    r = factory()
    failed_batch(r)
    old = os.environ.get(bs.STATE_ENV)
    os.environ[bs.STATE_ENV] = str(r / "schedule")
    try:
        out = io.StringIO()
        assert bs.main(["status", "--root", str(r), "--now", NOW, "--json"], out=out) == 0
        doc = json.loads(out.getvalue())
        # CF-0830: the Search budget of the quota day rides along
        assert set(doc) == {"switch", "breakers", "budget"}, doc
        assert doc["breakers"][A]["held"] is True, doc
        out = io.StringIO()
        assert bs.main(["status", "--root", str(r), "--now", NOW], out=out) == 0
        assert "Размыкатель повторов (CF-0822)" in out.getvalue(), out.getvalue()
        out = io.StringIO()
        assert bs.main(["plan", "--root", str(r), "--now", NOW, "--days", "1", "--json"],
                       out=out) == 0
        doc = json.loads(out.getvalue())
        assert doc["breakers"][A]["batch"] == f"{A}/{FAILED}", doc["breakers"]
        assert doc["days"][0]["breaker"]["held"], doc["days"][0]
    finally:
        if old is None:
            os.environ.pop(bs.STATE_ENV, None)
        else:
            os.environ[bs.STATE_ENV] = old


# ------------------------------------------------------------------ a renamed channel
def test_a_held_row_written_under_the_former_id_still_holds_the_day():
    """CF-0835 (CF-0197): launches.jsonl is a dated record - a `repeat_held` row
    written before the channel was renamed keeps the old id, and the tick must
    still read the day as held (else it journals and notifies a second time)."""
    r = factory()
    cfg = json.loads((r / "channels" / f"{A}.json").read_text())
    cfg["former_channel_ids"] = ["alpha-old"]
    _w(r / "channels" / f"{A}.json", cfg)
    qd = "2026-10-20"
    sd = bs.state_dir(r, env(r))
    _w(sd / bs.LAUNCHES, json.dumps({"kind": bs.HELD_KIND, "channel": "alpha-old",
                                     "quota_day": qd}) + "\n")
    assert bs._held_journaled(r, env(r), A, qd)
    assert not bs._held_journaled(r, env(r), A, "2026-10-21")
    assert not bs._held_journaled(r, env(r), B, qd)


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
