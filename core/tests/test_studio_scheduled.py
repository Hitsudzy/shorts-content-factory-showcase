#!/usr/bin/env python3
"""CF-0926: the planned Studio read - the tick of shared/batch_schedule.py
starts agents/analyst/studio_center.py `scheduled_read` once a Moscow day.

Nothing here goes to Studio, starts a real `claude` or touches the network:
a temp factory root (the fixtures of tests/test_analyst_studio_read.py), the
reading session is a stand-in script (`STUDIO_READ_CLAUDE`), the bus has only
its `log` backend with its journal in the temp tree, the time is fake.

What is pinned:

* the tick launches the read once a day at 08:15 MSK (`by: schedule, via:
  tick`), not before, not again after it read;
* not while a batch is open, not in the hour before a batch window;
* a closed channel (Science, `enabled: false`) is not read - by the tick and
  by the center's button alike;
* at most 3 attempts a day;
* the outcome `read` -> one «📊 Studio прочитана: ...» message; `login_needed`
  -> one «⚠️ Studio не прочитана ...» needs_human; one per run id;
* the safety net is quiet after a planned read that read and speaks after one
  that failed;
* the settings: `--studio-read-at HH:MM`, `--studio-read off|on`, validated,
  shown by `settings` and `plan`.
"""
import contextlib
import io
import json
import os
import signal
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "agents" / "analyst"))
sys.path.insert(0, str(ROOT / "shared"))

import test_analyst_studio_read as t    # noqa: E402  (make_root, read_doc, RU_VIDEO)
import studio_center as sc              # noqa: E402
import batch_schedule as bs             # noqa: E402

PY = sys.executable
REEL, TECH, SCI = "example-film", "example-tech", "example-science"
DAY = "2026-10-20"                       # in the past of the real clock: `recorded_at` is real


def msk(hhmm, day=DAY):
    h, m = hhmm.split(":")
    return f"{day}T{int(h) - 3:02d}:{m}:00Z" if int(h) >= 3 else \
        f"{day}T{int(h) + 21:02d}:{m}:00Z"


STUB = r'''
import json, os, re, subprocess, sys
root = os.getcwd()
prompt = sys.stdin.read()
with open(os.path.join(root, "stub-calls.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt}) + "\n")
mode = open(os.path.join(root, "claude.mode")).read().strip()
who = re.search(r"--by (\S+) --via (\S+)", prompt)
by, via = who.group(1), who.group(2)
read_at = open(os.path.join(root, "claude.read_at")).read().strip()
if mode == "read":
    for ch in CHANNELS:
        if ch not in prompt:
            continue
        doc = {"channel": ch, "read_at": read_at, "hook": "daily",
               "videos": [VIDEOS[ch]], "rights": {"read": True, "items": []}}
        p = os.path.join(root, f"stub-read-{ch}.json")
        open(p, "w").write(json.dumps(doc))
        subprocess.run([sys.executable, SR, "record", p, "--root", root, "--channel", ch,
                        "--by", by, "--via", via], check=True, stdout=subprocess.DEVNULL)
    print("STUDIO_READ_RESULT: read - записано")
elif mode == "sleep":
    import time; time.sleep(60)
elif mode == "login":
    print("STUDIO_READ_RESULT: login_needed - Studio открыл accounts.google.com")
else:
    sys.exit(1)
'''


def world(mode="read"):
    root = t.make_root(channels=(REEL, TECH, SCI), uploads=[
        t.up("AAAAAAAAAAA", "2026-10-18T01:00:00+03:00"),
        t.up("TTTTTTTTTTT", "2026-10-18T01:00:00+03:00", channel=TECH)])
    wins = {REEL: {"windows": ["11:30"]}, TECH: {"windows": ["18:00"]}, SCI: {"enabled": False}}
    for ch, block in wins.items():
        cfg = root / "channels" / f"{ch}.json"
        doc = json.loads(cfg.read_text())
        doc["batch_schedule"] = block
        doc["display_name"] = {REEL: "ExampleFilm", TECH: "ExampleTech", SCI: "ExampleScience"}[ch]
        cfg.write_text(json.dumps(doc))
    videos = {REEL: t.RU_VIDEO, TECH: dict(t.RU_VIDEO, video_id="TTTTTTTTTTT"),
              SCI: dict(t.RU_VIDEO, video_id="SSSSSSSSSSS")}
    stub = root / "bin" / "claude"
    stub.parent.mkdir()
    stub.write_text(f"#!{PY}\nSR = {str(ROOT / 'agents' / 'analyst' / 'studio_read.py')!r}\n"
                    f"CHANNELS = {[REEL, TECH, SCI]!r}\nVIDEOS = {videos!r}\n{STUB}")
    stub.chmod(0o755)
    (root / "claude.mode").write_text(mode)
    (root / "claude.read_at").write_text(f"{DAY}T08:16:00+03:00")
    env = {"NOTIFY_STATE_DIR": str(root / "notify"), "NOTIFY_BACKENDS": "log",
           sc.CLAUDE_ENV: str(stub)}
    return root, env


@contextlib.contextmanager
def environ(env):
    old = dict(os.environ)
    os.environ.update(env)
    os.environ.pop(sc.STATE_ENV, None)
    os.environ.pop(bs.STATE_ENV, None)
    try:
        with contextlib.redirect_stderr(io.StringIO()):
            yield
    finally:
        os.environ.clear()
        os.environ.update(old)


def tick(root, now, open_rows=()):
    return bs.tick(root, now, open_rows=list(open_rows), studio_read=True,
                   studio_insurance=True)


def wait_run(root, run_id, s=30.0):
    rec = json.loads((root / "schedule" / "studio-read" / "runs" / f"{run_id}.json").read_text())
    end = time.time() + s
    while time.time() < end:
        if not sc._alive(rec["pid"]):
            return rec
        time.sleep(0.05)
    raise AssertionError(f"the stub of {run_id} did not end")


def state(root):
    return sc.scheduled_state(root)


def journal(root, kind=None):
    p = root / "notify" / "sent.jsonl"
    rows = [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
    return [r for r in rows if kind is None or r["kind"] == kind]


def launches(root):
    """The launches of a read (the run records - written before the stub starts)."""
    d = root / "schedule" / "studio-read" / "runs"
    return len(list(d.glob("*.json"))) if d.is_dir() else 0


def calls(root):
    p = root / "stub-calls.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


# ---------------------------------------------------------------- once a day at 08:15

def test_the_tick_reads_once_a_day_at_0815_and_tells_once():
    root, env = world("read")
    with environ(env):
        _c, line, _r = tick(root, msk("08:00"))
        assert launches(root) == 0 and not state(root).get("attempts"), line
        _c, line, _r = tick(root, msk("08:15"))
        st = state(root)
        assert st["run_id"] and len(st["attempts"]) == 1, st
        assert "запущено плановое чтение" in line and "попытка 1 из 3" in line, line
        rec = wait_run(root, st["run_id"])
        assert rec["by"] == "schedule" and rec["via"] == "tick", rec
        assert "плановое чтение по расписанию" in calls(root)[0]["prompt"]
        assert '`hook` = "daily"' in calls(root)[0]["prompt"]
        assert "--by schedule --via tick" in calls(root)[0]["prompt"]
        _c, line, _r = tick(root, msk("08:30"))
        st = state(root)
        assert st["outcome"] == "read" and st["run_id"] is None, st
        got = journal(root, sc.SCHED_KIND)
        assert len(got) == 1, got
        assert got[0]["body"] == ("📊 Studio прочитана: Reel — 1 ролик, Tech — 1"), got
        assert got[0]["key"] == f"studio_read:{rec['run_id']}", got
        for later in ("08:45", "12:00", "23:45"):
            tick(root, msk(later))
        assert launches(root) == 1 and len(journal(root, sc.SCHED_KIND)) == 1
        assert journal(root, "needs_human") == [], "the safety net is quiet after a read"
        p = bs.plan(root, msk("12:00"), 1, open_rows=[])
        assert p["studio_read"]["enabled"] and p["studio_read"]["at"] == "08:15", p["studio_read"]
        assert "сегодня: прочитано" in p["studio_read"]["line"], p["studio_read"]
        assert p["studio_read"]["line"] in bs.plan_lines(p)
        # the next Moscow day: again at 08:15
        (root / "claude.read_at").write_text("2026-10-21T08:16:00+03:00")
        tick(root, msk("08:00", "2026-10-21"))
        assert launches(root) == 1 and state(root)["previous"]["outcome"] == "read"
        tick(root, msk("08:15", "2026-10-21"))
        assert launches(root) == 2, "the next day reads again"


# ---------------------------------------------------------------- the guards

def test_not_while_a_batch_is_open_nor_in_the_hour_before_a_window():
    root, env = world("read")
    open_dir = root / "pipeline" / REEL / f"{DAY}T0500Z"
    open_dir.mkdir(parents=True)
    with environ(env):
        _c, line, _r = tick(root, msk("08:15"), open_rows=[(str(open_dir), None, True)])
        assert launches(root) == 0, line
        assert "открыт батч Reel" in state(root)["waiting"], state(root)
        bs.set_factory_settings({"studio_read_at": "10:40"}, "user", root=root)
        _c, line, _r = tick(root, msk("10:45"))
        assert launches(root) == 0, line
        assert "до окна батча Reel" in state(root)["waiting"] and "меньше часа" in \
            state(root)["waiting"], state(root)
        assert bs.studio_read_gate(root, bs.parse_ts(msk("11:30")), open_rows=[]) is None
        _c, line, _r = tick(root, msk("11:45"))
        assert launches(root) == 1 and state(root)["run_id"], line
        wait_run(root, state(root)["run_id"])
        # the hour before the evening window (Tech 18:00)
        g = bs.studio_read_gate(root, bs.parse_ts(msk("17:15")), open_rows=[])
        assert g and "Tech" in g, g


def test_another_read_going_is_waited_for_not_counted():
    root, env = world("sleep")
    with environ(env):
        button = sc.studio_read_launch("user", "center", True, root, msk("08:00"), environ=env)
        assert button["launched"], button
        try:
            res = sc.scheduled_read(root, msk("08:15"), environ=env)
            assert not res["launched"] and "другое чтение" in res["line"], res
            st = state(root)
            assert st["attempts"] == [] and st["outcome"] is None, st
        finally:
            try:
                os.killpg(button["pid"], signal.SIGTERM)       # our own stub's own group
            except OSError:
                pass
            wait_run(root, button["run_id"])


# ---------------------------------------------------------------- closed channels

def test_a_closed_channel_is_not_read_by_the_tick_nor_by_the_button():
    root, env = world("read")
    with environ(env):
        tick(root, msk("08:15"))
        rec = wait_run(root, state(root)["run_id"])
        assert rec["channels"] == [REEL, TECH], rec
        assert SCI not in calls(root)[0]["prompt"]
        plan = sc.studio_read_launch("user", "center", False, root, msk("09:00"), environ=env)
        assert plan["ok"] and plan["channels"] == [REEL, TECH], plan
        assert any(SCI in ln and "закрыт" in ln for ln in plan["lines"]), plan["lines"]
        refused = sc.studio_read_launch("user", "center", False, root, msk("09:00"),
                                        channels=[SCI], environ=env)
        assert refused["refusals"][0]["code"] == "no_channels", refused
        due = sc.studio_read_due(None, None, root, msk("09:00"), env)
        assert [r["channel"] for r in due["channels"]] == [REEL, TECH], due


# ---------------------------------------------------------------- three attempts

def test_at_most_three_attempts_a_day():
    root, env = world("error")
    with environ(env):
        times = ["08:15", "08:30", "08:45", "09:00", "09:15", "09:30", "09:45", "10:00",
                 "10:15", "10:30", "12:00", "13:00", "16:00"]
        for hhmm in times:
            tick(root, msk(hhmm))
            st = state(root)
            if st.get("run_id"):
                wait_run(root, st["run_id"])
        st = state(root)
        assert launches(root) == 3 and len(st["attempts"]) == 3, (launches(root), st)
        assert st["outcome"] == "failed", st
        assert [a["code"] for a in st["attempts"]] == ["error"] * 3, st
        assert journal(root, sc.SCHED_KIND) == [], "an error tells nobody by itself"
        # the safety net now speaks: the planned read failed
        nh = journal(root, "needs_human")
        assert len(nh) == 1 and "Плановое чтение: сегодня не вышло — чтение закончилось " \
            "ошибкой" in nh[0]["body"] and "(3 попытки)" in nh[0]["body"], nh
        assert "Нужно от вас:" in nh[0]["body"], nh


# ---------------------------------------------------------------- login_needed

def test_login_needed_calls_the_user_once_per_run():
    root, env = world("login")
    with environ(env):
        tick(root, msk("08:15"))
        rec = wait_run(root, state(root)["run_id"])
        tick(root, msk("08:30"))
        tick(root, msk("08:45"))
        got = [r for r in journal(root, "needs_human") if r["key"].startswith("studio_read:")]
        assert len(got) == 1 and got[0]["key"] == f"studio_read:{rec['run_id']}", got
        assert got[0]["body"].startswith("⚠️ Studio не прочитана (Reel, Tech): нужен вход "
                                         "в аккаунт Google"), got
        assert "Нужно от вас: войти в аккаунт Google в Chrome" in got[0]["body"], got
        assert "попробую сам ~09:30" in got[0]["body"], got
        st = state(root)
        assert st["outcome"] is None and len(st["attempts"]) == 1, st
        assert not [r for r in journal(root, "needs_human")
                    if r["key"].startswith("studio_insurance")], \
            "attempts are left: the safety net waits"
        tick(root, msk("09:15"))
        assert launches(root) == 1, "a failure only the user fixes waits an hour"
        tick(root, msk("09:30"))
        assert launches(root) == 2


# ---------------------------------------------------------------- the safety net

def test_the_safety_net_is_quiet_after_a_planned_read_and_speaks_after_a_failure():
    root, env = world("read")
    with environ(env):
        gate = sc.scheduled_insurance_gate(root, msk("08:00"), env)
        assert not gate["quiet"] and "ни разу" in gate["why"], "no tick has run it yet"
        tick(root, msk("08:00"))
        gate = sc.scheduled_insurance_gate(root, msk("08:00"), env)
        assert gate["quiet"] and "первое плановое чтение" in gate["why"], gate
        assert journal(root, "needs_human") == [], "the tick waits for its hour"
        tick(root, msk("08:15"))
        wait_run(root, state(root)["run_id"])
        assert sc.scheduled_insurance_gate(root, msk("08:20"), env)["quiet"], "going"
        tick(root, msk("08:30"))
        g = sc.scheduled_insurance_gate(root, msk("20:00"), env)
        assert g["quiet"] and "прошло" in g["why"], g
        # the next morning before 08:15: yesterday read - quiet
        g = sc.scheduled_insurance_gate(root, msk("07:00", "2026-10-21"), env)
        assert g["quiet"], g
        # a day the read did not read: speaks the morning after with what is needed
        st = state(root)
        st.update(outcome="failed", attempts=[{"at": msk("08:15"), "run_id": None,
                                                "code": "no_extension", "line": "x"}] * 3)
        sc._save_state(st, root, env)
        g = sc.scheduled_insurance_gate(root, msk("21:00"), env)
        assert not g["quiet"] and "расширение Chrome не подключено" in g["why"], g
        assert g["need"].startswith("открыть Chrome и включить расширение"), g
        tick(root, msk("08:00", "2026-10-21"))
        g = sc.scheduled_insurance_gate(root, msk("08:00", "2026-10-21"), env)
        assert not g["quiet"] and g["why"].startswith("вчера не вышло"), g
        # off: the safety net speaks as before, saying the planned read is off
        bs.set_factory_settings({"studio_read": "off"}, "user", root=root)
        g = sc.scheduled_insurance_gate(root, msk("12:00", "2026-10-21"), env)
        assert not g["quiet"] and g["why"] == "выключено" and "--studio-read on" in g["need"], g


# ---------------------------------------------------------------- the settings

def test_the_settings_are_validated_shown_and_turn_the_read_off():
    root, env = world("read")
    with environ(env):
        out, err = io.StringIO(), io.StringIO()
        assert bs.main(["settings", "--root", str(root), "--studio-read-at", "25:00",
                        "--by", "user"], out=out, err=err) == bs.EXIT_REFUSED
        assert "время чтения Studio" in err.getvalue(), err.getvalue()
        assert bs.main(["settings", "--root", str(root), "--studio-read", "maybe",
                        "--by", "user"], out=io.StringIO(), err=err) == bs.EXIT_REFUSED
        assert bs.main(["settings", "--root", str(root), "--studio-read-at", "9:05"],
                       out=io.StringIO(), err=err) == bs.EXIT_REFUSED, "a change needs --by"
        out = io.StringIO()
        assert bs.main(["settings", "--root", str(root), "--studio-read-at", "9:05",
                        "--by", "user", "--note", "тест"], out=out, err=err) == bs.EXIT_OK
        assert "studio_read_at 08:15 -> 09:05" in out.getvalue(), out.getvalue()
        assert "раз в сутки в 09:05 МСК" in out.getvalue(), out.getvalue()
        assert bs.factory_settings(root)["studio_read_at"] == "09:05"
        out = io.StringIO()
        bs.main(["settings", "--root", str(root)], out=out, err=err)
        assert out.getvalue().startswith("Чтение Studio: по расписанию, раз в сутки в 09:05"), \
            out.getvalue()
        assert bs.main(["settings", "--root", str(root), "--studio-read", "off", "--by", "user"],
                       out=io.StringIO(), err=err) == bs.EXIT_OK
        assert "плановое выключено" in bs.plan(root, msk("10:00"), 1, open_rows=[])[
            "studio_read"]["line"]
        tick(root, msk("10:00"))
        assert launches(root) == 0, "off: the tick does not read"
        assert bs.main(["settings", "--root", str(root), "--studio-read", "on", "--by", "user"],
                       out=io.StringIO(), err=err) == bs.EXIT_OK
        tick(root, msk("10:15"))
        assert launches(root) == 1
        wait_run(root, state(root)["run_id"])
        doc = json.loads((root / "schedule" / bs.FACTORY_SETTINGS).read_text())
        assert doc["settings"] == {"studio_read_at": "09:05"}, doc
        assert [h["by"] for h in doc["history"]] == ["user"] * 3, doc


def test_a_test_root_is_not_read_without_the_flag():
    root, env = world("read")
    with environ(env):
        _c, line, _r = bs.tick(root, msk("08:15"), open_rows=[])
        assert launches(root) == 0 and "Studio" not in line, line


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                                   # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
