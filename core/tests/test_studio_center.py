#!/usr/bin/env python3
"""CF-0735: the Studio read on the user's actions in the command center
(agents/analyst/studio_center.py).

Nothing here goes to Studio, starts a real `claude` or touches the network:
every check builds a temp factory root (the fixtures of
tests/test_analyst_studio_read.py), the reading session is a stand-in script
(`claude` stub) and the bus has only its `log` backend with its journal in the
temp tree.

What is pinned:

* `studio_read_due` follows `studio_read.due` - the hook gap for
  `batch-start` / `upload`, the daily insurance without a hook; the center's
  first open of the Moscow day takes the hook rule, a later open the insurance;
  the opens are a small state file, rewritten atomically;
* the launch is a plan without `confirmed` (nothing started, nothing written)
  and refuses with codes (bad_who, no_claude, running); confirmed, it starts
  the session detached with the prompt on stdin and a log, `claude -p --chrome`
  with the Chrome tools allowed;
* `studio_read_result` reads the outcome: read (only when the visit was really
  recorded through `via`), no_extension, login_needed, error, running;
* the insurance: one Russian line with the center's link (8790) at most once
  in 24 hours, nothing when the read is fresh, nothing on a dry run.
"""
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

import test_analyst_studio_read as t    # noqa: E402  (its fixtures: make_root, read_doc)
import studio_center as sc              # noqa: E402

NOW = "2026-10-06T10:00:00Z"
PY = sys.executable

STUB = r'''
import json, os, subprocess, sys
root = os.getcwd()
prompt = sys.stdin.read()
with open(os.path.join(root, "stub-calls.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt}) + "\n")
mode = open(os.path.join(root, "claude.mode")).read().strip()
if mode == "sleep":
    import time; time.sleep(60)
elif mode in ("read", "read-norecord"):
    if mode == "read":
        doc = {"channel": "example-film", "read_at": "2026-10-06T12:59:00+03:00", "hook": "manual",
               "rights": {"read": True, "items": []}}
        p = os.path.join(root, "stub-read.json")
        open(p, "w").write(json.dumps(doc))
        subprocess.run([sys.executable, SR, "record", p, "--root", root, "--channel",
                        "example-film", "--by", "user", "--via", "center"], check=True)
    print("Прочитано.")
    print("STUDIO_READ_RESULT: read - example-film: права прочитаны, записано")
elif mode == "noext":
    print("Error: Claude in Chrome extension is not connected")
    sys.exit(1)
elif mode == "login":
    print("STUDIO_READ_RESULT: login_needed - Studio открыл accounts.google.com")
elif mode == "notlogged":
    print("Not logged in · Please run /login")
    sys.exit(1)
else:
    sys.exit(1)
'''


def world(**kw):
    root = t.make_root(**kw)
    stub = root / "bin" / "claude"
    stub.parent.mkdir()
    stub.write_text(f"#!{PY}\nSR = {str(ROOT / 'agents' / 'analyst' / 'studio_read.py')!r}\n{STUB}")
    stub.chmod(0o755)
    env = {"NOTIFY_STATE_DIR": str(root / "notify"), "NOTIFY_BACKENDS": "log",
           sc.CLAUDE_ENV: str(stub)}
    return root, env


def full_read(root, read_at):
    sr = sc.sr
    sr.record(sr.parse_read(t.read_doc([t.RU_VIDEO], read_at=read_at), root=root), root, NOW)


def wait_done(pid, s=20.0):
    end = time.time() + s
    while time.time() < end:
        if not sc._alive(pid):
            return True
        time.sleep(0.05)
    return False


def quiet_stderr():
    import contextlib
    return contextlib.redirect_stderr(io.StringIO())


# ---------------------------------------------------------------- due

def test_due_follows_the_rule_of_studio_read():
    root, env = world()
    d = sc.studio_read_due("example-film", "batch-start", root, NOW, env)
    assert d["due"] and d["last_read_at"] is None and d["age_hours"] is None, d
    assert "ни разу" in d["why"] and d["hooks"] == list(sc.HOOKS), d
    full_read(root, "2026-10-06T08:00:00Z")                       # 2 h ago
    d = sc.studio_read_due("example-film", "batch-start", root, NOW, env)
    assert not d["due"] and d["age_hours"] == 2.0, d
    assert d["last_read_at"] == "2026-10-06T08:00:00Z" and "прочитан недавно" in d["why"], d
    later = "2026-10-06T13:00:00Z"                                 # 5 h: past the 3 h gap
    assert sc.studio_read_due("example-film", "upload", root, later, env)["due"]
    assert not sc.studio_read_due("example-film", None, root, later, env)["due"], "insurance 24 h"
    d = sc.studio_read_due(None, None, root, "2026-10-07T09:00:00Z", env)
    assert d["due"] and d["channel"] is None and [r["channel"] for r in d["channels"]] == \
        ["example-film"], d
    assert "пора читать Studio" in d["why"] and "страховка" in d["why"], d
    for bad in ("daily", "x"):
        try:
            sc.studio_read_due(None, bad, root, NOW, env)
        except sc.CenterError:
            pass
        else:
            raise AssertionError(f"hook {bad} accepted")


def test_the_center_first_open_of_the_day_takes_the_hook_then_the_insurance():
    root, env = world()
    full_read(root, "2026-10-06T05:00:00Z")                       # 5 h before NOW
    d = sc.studio_read_due(None, sc.HOOK_CENTER, root, NOW, env)
    assert d["first_open_today"] is True and d["due"], d
    assert "первое открытие центра за день" in d["why"], d
    d = sc.studio_read_due(None, sc.HOOK_CENTER, root, "2026-10-06T10:30:00Z", env)
    assert d["first_open_today"] is False and not d["due"], d
    assert "уже было сегодня" in d["why"], d
    state = root / "schedule" / "studio-read" / sc.OPENS_FILE
    doc = json.loads(state.read_text())
    assert doc["day"] == "2026-10-06" and doc["opens"] == 2, doc
    assert doc["first_open_at"] == "2026-10-06T10:00:00Z", doc
    assert not list(state.parent.glob("*.tmp")), "written atomically"
    # 21:30 UTC is 00:30 MSK of the 7th: a new day, a first open again
    d = sc.studio_read_due(None, sc.HOOK_CENTER, root, "2026-10-06T21:30:00Z", env)
    assert d["first_open_today"] is True, d
    assert json.loads(state.read_text())["day"] == "2026-10-07"


def test_channels_without_settings_or_pipeline_are_named_not_read():
    root, env = world(channels=("example-film", "example-tech"),
                      settings={"example-film": {"last_videos": 2, "insurance_hours": 24,
                                                "hook_min_gap_hours": 3},
                                "example-tech": None})
    d = sc.studio_read_due(None, None, root, NOW, env)
    assert [r["channel"] for r in d["channels"]] == ["example-film"], d
    assert any(s.startswith("example-tech:") for s in d["skipped"]), d


# ---------------------------------------------------------------- the launch

def test_the_launch_without_confirm_is_a_plan_and_starts_nothing():
    root, env = world()
    res = sc.studio_read_launch("user", "center", False, root, NOW, environ=env)
    assert res["ok"] and not res["launched"] and res["pid"] is None, res
    argv = res["argv"]
    assert argv[1:3] == ["-p", "--chrome"], argv
    tools = argv[argv.index("--allowedTools") + 1:argv.index("--add-dir")]
    assert "mcp__claude-in-chrome__*" in tools and \
        "Bash(python3 agents/analyst/studio_read.py record:*)" in tools, tools
    assert res["channels"] == ["example-film"] and res["refusals"] == []
    assert any("только при пользователе" in ln for ln in res["lines"]), res["lines"]
    assert not (root / "schedule").exists(), "the plan writes nothing"
    assert not (root / "stub-calls.jsonl").exists(), "and starts nothing"


def test_the_launch_refuses_with_codes():
    root, env = world()
    res = sc.studio_read_launch("", "center", True, root, NOW, environ=env)
    assert not res["ok"] and res["refusals"][0]["code"] == "bad_who", res
    res = sc.studio_read_launch("user", None, True, root, NOW, environ=env)
    assert res["refusals"][0]["code"] == "bad_who", res
    res = sc.studio_read_launch("user", "center", True, root, NOW,
                                claude=str(root / "no-such-claude"), environ=env)
    assert [r["code"] for r in res["refusals"]] == ["no_claude"] and not res["launched"], res
    res = sc.studio_read_launch("user", "center", True, root, NOW, channels=["nope"],
                                environ=env)
    assert res["refusals"][0]["code"] == "no_channels", res
    assert set(sc.LAUNCH_REFUSALS) >= {r["code"] for r in res["refusals"]}


def _launch(root, env, mode):
    (root / "claude.mode").write_text(mode)
    res = sc.studio_read_launch("user", "center", True, root, NOW, environ=env)
    assert res["ok"] and res["launched"] and res["pid"], res
    return res


def test_a_confirmed_launch_runs_the_session_detached_and_reads_read():
    root, env = world()
    res = _launch(root, env, "read")
    assert wait_done(res["pid"]), "the stub ended"
    call = json.loads((root / "stub-calls.jsonl").read_text().splitlines()[0])
    assert call["argv"][:2] == ["-p", "--chrome"], call
    assert "studio.youtube.com" in call["prompt"] and "--by user --via center" in call["prompt"]
    assert "STUDIO_READ_RESULT: read" in call["prompt"]
    rec = json.loads((root / "schedule" / "studio-read" / "runs" / f"{res['run_id']}.json")
                     .read_text())
    assert rec["pid"] == res["pid"] and rec["by"] == "user" and rec["log"] == res["log"], rec
    got = sc.studio_read_result(res["run_id"], root, env)
    assert got["code"] == "read" and got["done"] and got["recorded"] == ["example-film"], got
    assert got["line"].startswith("прочитано: example-film"), got
    assert sc.studio_read_result(res["log"], root, env)["code"] == "read", "by the log too"
    assert not sc.studio_read_due("example-film", None, root, "2026-10-06T12:00:00Z", env)["due"]


def test_the_outcomes_of_a_session_that_did_not_read():
    for mode, code, word in (("noext", "no_extension", "расширение не подключено"),
                             ("login", "login_needed", "нужен вход"),
                             ("notlogged", "error", "ошибка: claude не вошёл"),
                             ("silent", "error", "ошибка: сессия закончилась без итога"),
                             ("read-norecord", "error", "ошибка: сессия сказала «прочитано»")):
        root, env = world()
        res = _launch(root, env, mode)
        assert wait_done(res["pid"]), mode
        got = sc.studio_read_result(res["run_id"], root, env)
        assert got["code"] == code and got["line"].startswith(word), (mode, got)
        assert got["code"] in sc.OUTCOMES
    got = sc.studio_read_result("20990101T000000Z", root, env)
    assert got["code"] == "error" and "нет журнала" in got["line"], got


def test_a_session_still_going_is_running_and_a_second_click_is_refused():
    root, env = world()
    res = _launch(root, env, "sleep")
    try:
        got = sc.studio_read_result(res["run_id"], root, env)
        assert got["code"] == "running" and not got["done"], got
        again = sc.studio_read_launch("user", "center", True, root, NOW, environ=env)
        assert not again["launched"] and again["refusals"][0]["code"] == "running", again
        assert sc.studio_read_due(None, None, root, NOW, env)["running"] == res["run_id"]
    finally:
        try:
            os.killpg(res["pid"], signal.SIGTERM)          # our own stub's own group
        except OSError:
            pass
        wait_done(res["pid"])


# ---------------------------------------------------------------- the insurance

def _journal(root):
    p = root / "notify" / "sent.jsonl"
    return [json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []


def test_the_insurance_calls_once_a_day_in_russian_with_the_center_link():
    root, env = world()
    with quiet_stderr():
        res = sc.studio_insurance_notify(root, NOW, env)
        assert res["sent"] and res["status"] == "sent", res
        # CF-0925: the channel by its name, what stands still, who reads Studio
        # CF-0926: what came of the planned read, what is needed from the user
        assert res["text"] == ("📊 Studio ни разу не читали (example-film) — статистика роликов "
                               "не обновляется.\nПлановое чтение: ещё ни разу не запускалось, "
                               "хотя пора было в 08:15 МСК (тик расписания не работает?)."
                               "\nНужно от вас: центр → «Прочитать "
                               "Studio»."), res
        rows = _journal(root)
        assert len(rows) == 1 and rows[0]["kind"] == "needs_human", rows
        assert rows[0]["link"] == "http://127.0.0.1:8790/", rows
        again = sc.studio_insurance_notify(root, "2026-10-07T09:59:00Z", env)
        assert not again["sent"] and "не чаще раза в 24 ч" in again["why"], again
        assert len(_journal(root)) == 1
        full_read(root, "2026-10-05T04:00:00Z")
        later = sc.studio_insurance_notify(root, "2026-10-07T10:00:00Z", env)
        assert later["sent"] and later["text"].startswith("📊 Studio не читали 54 часа (example-film)"), \
            later
        assert len(_journal(root)) == 2
        assert {r["key"] for r in _journal(root)} == {
            "studio_insurance:2026-10-06T10:00:00Z", "studio_insurance:2026-10-07T10:00:00Z"}


def test_the_insurance_leaves_out_a_closed_channel():
    """CF-0925: a channel off the schedule (`batch_schedule.enabled: false` -
    ExampleScience since 05.11) is no reason to call; the rest are named."""
    root, env = world()
    cfg = root / "channels" / "example-film.json"
    doc = json.loads(cfg.read_text())
    doc["batch_schedule"] = dict(doc.get("batch_schedule") or {}, enabled=False)
    cfg.write_text(json.dumps(doc))
    with quiet_stderr():
        res = sc.studio_insurance_notify(root, NOW, env)
    assert not res["sent"] and res["channels"] == [], res
    assert _journal(root) == [], _journal(root)


def test_the_insurance_is_quiet_when_the_read_is_fresh_and_on_a_dry_run():
    root, env = world()
    with quiet_stderr():
        res = sc.studio_insurance_notify(root, NOW, env, dry_run=True)
        assert not res["sent"] and res["text"] and "сухой" in res["why"], res
        assert _journal(root) == [] and not (root / "schedule" / "studio-read" /
                                              sc.INSURANCE_FILE).exists()
        full_read(root, "2026-10-06T01:00:00Z")
        res = sc.studio_insurance_notify(root, NOW, env)
        assert not res["sent"] and res["channels"] == [] and _journal(root) == [], res


def test_the_cli_insurance_never_fails_a_batch():
    root, env = world()
    old = dict(os.environ)
    os.environ.update(env)
    try:
        out = io.StringIO()
        with quiet_stderr():
            assert sc.main(["insurance", "--root", str(root), "--now", NOW], out=out) == 0
        assert out.getvalue().startswith("страховка Studio: позвали"), out.getvalue()
        out = io.StringIO()
        assert sc.main(["insurance", "--root", str(root / "missing"), "--now", NOW], out=out) == 0
    finally:
        os.environ.clear()
        os.environ.update(old)


def test_hours_word():
    assert [f"{n} {sc.hours_word(n)}" for n in (1, 2, 5, 11, 21, 24, 54, 112)] == [
        "1 час", "2 часа", "5 часов", "11 часов", "21 час", "24 часа", "54 часа", "112 часов"]


# ---------------------------------------------------------------- CF-0759: what the session may run

def _rule_allows(rule, command):
    """A stand-in of claude's Bash allow rule for the forms used here: `X:*` -
    the command is X or X followed by a space; otherwise the exact command.
    A compound command (loop, `;`, `&&`, `|`) is never one line of a rule."""
    if not (rule.startswith("Bash(") and rule.endswith(")")):
        return False
    body = rule[len("Bash("):-1]
    if body.endswith(":*"):
        prefix = body[:-2]
        return command == prefix or command.startswith(prefix + " ")
    return command == body


def _bash_lines(prompt):
    """The command lines the prompt names (the indented block)."""
    return [ln.strip().split("   (")[0] for ln in prompt.splitlines() if ln.startswith("  ")]


def test_each_allowed_tool_is_its_own_argument_and_bash_is_only_the_read():
    root, env = world()
    argv = sc.studio_read_launch("user", "center", False, root, NOW, environ=env)["argv"]
    i, j = argv.index("--allowedTools"), argv.index("--add-dir")
    tools = argv[i + 1:j]
    assert tools == sc.allowed_tools(), tools
    for tool in tools:      # no list joined by commas: a rule is one argument
        assert "," not in tool and not tool.startswith("-"), tool
    assert argv[i - 2:i] == ["--permission-mode", "dontAsk"], argv
    assert [Path(d).resolve() for d in argv[j + 1:]] == [root.resolve()], \
        "the state dir is inside the root: one dir"
    bash = [t for t in tools if t.startswith("Bash")]
    assert bash == ["Bash(python3 agents/analyst/studio_read.py plan:*)",
                    "Bash(python3 agents/analyst/studio_read.py parse:*)",
                    "Bash(python3 agents/analyst/studio_read.py record:*)",
                    "Bash(date -u +%Y-%m-%dT%H:%M:%SZ)"], bash
    assert "Bash" not in tools and not any(t.startswith("Bash(python3:") for t in tools)
    assert set(tools) - set(bash) == {"mcp__claude-in-chrome__*", "Read", "Write"}, tools


def test_a_state_dir_outside_the_root_is_added_for_the_session():
    root, env = world()
    outside = root.parent / (root.name + "-state")
    env = dict(env, **{sc.STATE_ENV: str(outside)})
    argv = sc.studio_read_launch("user", "center", False, root, NOW, environ=env)["argv"]
    dirs = [Path(d).resolve() for d in argv[argv.index("--add-dir") + 1:]]
    assert dirs == [root.resolve(), (outside / sc.RUNS_DIR).resolve()], argv
    prompt = sc.read_prompt(["example-film"], "R1", outside / sc.RUNS_DIR, "user", "center", root)
    assert f"{outside / sc.RUNS_DIR}/R1-<канал>.json" in prompt, "absolute when outside the root"


def test_every_command_the_prompt_names_is_allowed_and_the_failed_forms_are_not():
    root, env = world()
    runs = root / "schedule" / "studio-read" / "runs"
    prompt = sc.read_prompt(["example-film", "example-tech"], "20261015T185106Z", runs,
                            "user", "center", root)
    lines = _bash_lines(prompt)
    rel = "schedule/studio-read/runs/20261015T185106Z-<канал>.json"
    assert lines == [
        "python3 agents/analyst/studio_read.py plan --channel <канал>",
        "date -u +%Y-%m-%dT%H:%M:%SZ",
        f"python3 agents/analyst/studio_read.py parse {rel} --channel <канал>",
        f"python3 agents/analyst/studio_read.py record {rel} --channel <канал> "
        "--by user --via center"], lines
    rules = sc.allowed_tools()
    for line in lines:
        cmd = line.replace("<канал>", "example-film")
        assert any(_rule_allows(r, cmd) for r in rules), cmd
    assert str(sc._root(root)) in prompt, "the prompt names the cwd the commands run from"
    for word in ("for/while", "`;`", "`&&`", "`cd`", ".venv/bin/python", "dontAsk"):
        assert word in prompt, word
    assert "switch_browser" in prompt and "createIfEmpty" in prompt
    assert "Прочие скрипты в этой сессии не запускай" in prompt
    # the run of 15.10 was denied on a loop; these forms stay denied
    for cmd in ["for c in example-film example-tech; do python3 agents/analyst/studio_read.py "
                "plan --channel $c; done",
                f"cd {root} && python3 agents/analyst/studio_read.py plan --channel example-film",
                f"python3 {root}/agents/analyst/studio_read.py plan --channel example-film",
                ".venv/bin/python3 agents/analyst/studio_read.py plan --channel example-film",
                "python agents/analyst/studio_read.py plan --channel example-film",
                "python3 agents/analyst/summary.py daily --channel x",
                "python3 agents/analyst/studio_read.py planx"]:
        assert not any(_rule_allows(r, cmd) for r in rules), cmd


def test_the_launched_session_gets_the_rules_and_the_exact_lines():
    root, env = world()
    res = _launch(root, env, "read-norecord")
    assert wait_done(res["pid"]), "the stub ended"
    call = json.loads((root / "stub-calls.jsonl").read_text().splitlines()[0])
    argv = call["argv"]
    assert argv[argv.index("--allowedTools") + 1:argv.index("--add-dir")] == sc.allowed_tools()
    rel = f"schedule/studio-read/runs/{res['run_id']}-<канал>.json"
    assert (f"  python3 agents/analyst/studio_read.py record {rel} --channel <канал> "
            "--by user --via center") in call["prompt"].splitlines(), call["prompt"]


if __name__ == "__main__":
    tests = [(k, v) for k, v in globals().items() if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            import traceback
            traceback.print_exc()
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
