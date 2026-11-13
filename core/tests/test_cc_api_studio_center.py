#!/usr/bin/env python3
"""CC-0120: the Studio read on the user's actions in the center
(`api/studio_center.py` over the factory's `agents/analyst/studio_center.py`,
CF-0735): `GET /api/studio/due`, `POST /api/studio/read/plan`, `POST
/api/studio/read {confirm}`, `GET /api/studio/read/{run_id}`.

In-process (starlette's TestClient) against the stand-in factory root of
`tests/test_cc_api_analytics.py` `world` in a temp dir (a git repo on main -
the working factory), the factory's state dir in the temp tree
(`STUDIO_READ_STATE_DIR` through `FACTORY_KW["environ"]`). **No test starts a
real `claude`**: `FACTORY_KW["claude"]` is a stand-in script in the temp dir
(it takes precedence over the environment and PATH in the factory's
`claude_binary`), and the confirm's launcher child (`run_launcher`) is either
a stand-in or runs the factory's launch against that stand-in only. No
network; the clock is fixed.

What is pinned:

* the contract: the four routes, `StudioCenterProblem`, the shapes, version
  0.49.0; the switch `STUDIO_READ_LAUNCH` ships OFF;
* due: the factory's answer (due, why, last read, channels, skipped,
  running) + `launch {available: false, why}`; a bad hook or channel is 422
  in Russian; center-first-open-of-day records the open (the first of the day,
  then not);
* the plan: nothing started, no token while the switch is off, `why` the
  switch's line; a factory refusal (no_claude) in Russian with its code;
* the confirm: the switch off refuses `launch_off` before the token; on, the
  token spent and the launcher child started with the plan's channels; a
  refusal from the launch is its Russian message; a token spent twice is
  refused;
* the result: read / no_extension / running with the Russian words and the
  poll hint; an unknown run 404, a bad id 422.
"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

os.environ.pop("ACCEPTANCE_LOG", None)
os.environ.pop("BATCH_SCHEDULE_STATE_DIR", None)

from test_cc_api_batches import BASE, client                         # noqa: E402
from test_cc_api_analytics import setup, world                     # noqa: E402

import api                                                           # noqa: E402
from api import studio_center                                        # noqa: E402
from api.app import SESSION_HEADER                                   # noqa: E402

H = {"Origin": BASE, SESSION_HEADER: "tok"}
NOW = "2026-10-11T12:00:00Z"
PY = sys.executable
ROUTES = {"/api/studio/due": {"get"}, "/api/studio/read/plan": {"post"},
          "/api/studio/read": {"post"}, "/api/studio/read/{run_id}": {"get"}}

#: The stand-in `claude`: writes its argv and stdin, prints the result line.
STUB = r'''
import json, os, sys
root = os.getcwd()
prompt = sys.stdin.read()
with open(os.path.join(root, "stub-calls.jsonl"), "a") as fh:
    fh.write(json.dumps({"argv": sys.argv[1:], "prompt": prompt}) + "\n")
print("Error: Claude in Chrome extension is not connected")
sys.exit(1)
'''


def start(stub=True):
    setup()
    studio_center.FACTORY_KW.clear()
    studio_center.STUDIO_READ_LAUNCH = False
    root = world()
    env = {"STUDIO_READ_STATE_DIR": str(root / "schedule" / "studio-read")}
    studio_center.FACTORY_KW.update({"now": NOW, "environ": env})
    if stub:
        exe = root / "bin" / "claude"
        exe.parent.mkdir(parents=True, exist_ok=True)
        exe.write_text(f"#!{PY}\n{STUB}", encoding="utf-8")
        exe.chmod(0o755)
        studio_center.FACTORY_KW["claude"] = str(exe)
    else:
        studio_center.FACTORY_KW["claude"] = str(root / "bin" / "no-claude-here")
    return root, client(root)


def runs_dir(root):
    return root / "schedule" / "studio-read" / "runs"


def get(c, path, **params):
    r = c.get(path, params=params, headers=H)
    return r.status_code, r.json()


def post(c, path, body=None):
    r = c.post(path, headers=H, json=body or {})
    return r.status_code, r.json()


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_four_routes():
    root, c = start()
    spec = c.get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    got = {p: set(v) for p, v in spec["paths"].items() if p.startswith("/api/studio")}
    assert got == ROUTES, got
    for p, ms in ROUTES.items():
        for m in ms:
            ref = spec["paths"][p][m]["responses"]["422"]["content"]["application/json"]
            assert ref["schema"]["$ref"].endswith("/StudioCenterProblem"), (p, ref)
    sch = spec["components"]["schemas"]
    assert {"due", "why", "last_read_at", "age_hours", "first_open_today", "running",
            "channels", "skipped", "launch"} <= set(sch["StudioReadDue"]["properties"])
    assert {"ok", "why", "refusals", "launch", "confirm", "expires_in_s", "channels",
            "argv"} <= set(sch["StudioReadPlan"]["properties"])
    assert {"run_id", "pid", "log", "poll_s"} <= set(sch["StudioReadStarted"]["properties"])
    assert {"code", "word", "done", "line", "detail", "recorded", "poll_s"} <= \
        set(sch["StudioReadResult"]["properties"])
    assert {"quiet"} <= set(sch["BatchDetail"]["properties"])


def test_the_switch_is_on_since_the_users_word():
    # Shipped off (CF-0735); on since 2026-10-17 on the user's «да» (hotfix v2.8.1).
    # The tests below still set it per test; this one pins what production runs.
    src = (ROOT / "api" / "studio_center.py").read_text(encoding="utf-8")
    assert "\nSTUDIO_READ_LAUNCH = True\n" in src
    saved = studio_center.STUDIO_READ_LAUNCH
    try:
        studio_center.STUDIO_READ_LAUNCH = False
        assert studio_center.launch_block()["available"] is False
    finally:
        studio_center.STUDIO_READ_LAUNCH = saved
    assert studio_center.LAUNCH_OFF_WHY == ("запуск чтения Studio из центра ещё не включён — первый "
                                  "запуск делается вместе с пользователем")


# --------------------------------------------------------------------- due
def test_due_is_the_factorys_answer_with_the_switch():
    root, c = start()
    code, d = get(c, "/api/studio/due")
    assert code == 200, d
    assert d["due"] is True and d["hook"] is None and d["channel"] is None, d
    assert [r["channel"] for r in d["channels"]] == ["reel"], d
    assert d["channels"][0]["last_read_at"] == "2026-10-09T10:00:00Z", d
    assert d["age_hours"] == 50.0 and "пора читать Studio" in d["why"], d
    assert d["launch"] == {"available": False, "why": studio_center.LAUNCH_OFF_WHY,
                           "switch": "STUDIO_READ_LAUNCH"}, d
    assert d["running"] is None and d["hook_words"]["none"] == "страховка раз в сутки", d
    code, d = get(c, "/api/studio/due", channel="reel", hook="batch-start")
    assert code == 200 and d["channel"] == "reel" and d["due"], d
    assert str(root) not in json.dumps(d, ensure_ascii=False)


def test_a_bad_hook_or_channel_is_422_in_russian():
    root, c = start()
    code, d = get(c, "/api/studio/due", hook="daily")
    assert code == 422 and d["code"] == "bad_hook" and "Неизвестный повод" in d["message"], d
    assert d["details"] and "hook" in d["details"][0], d
    code, d = get(c, "/api/studio/due", channel="nope")
    assert code == 422 and d["code"] == "bad_channel" and "«nope»" in d["message"], d
    assert str(root) not in json.dumps(d, ensure_ascii=False)


def test_the_center_first_open_records_the_open_once_a_day():
    root, c = start()
    opens = root / "schedule" / "studio-read" / "center-opens.json"
    code, d = get(c, "/api/studio/due", hook="center-first-open-of-day")
    assert code == 200 and d["first_open_today"] is True, d
    assert json.loads(opens.read_text(encoding="utf-8"))["opens"] == 1
    code, d = get(c, "/api/studio/due", hook="center-first-open-of-day")
    assert code == 200 and d["first_open_today"] is False, d
    assert "уже было сегодня" in d["why"], d
    assert json.loads(opens.read_text(encoding="utf-8"))["opens"] == 2


# --------------------------------------------------------------------- the plan
def test_the_plan_starts_nothing_and_gives_no_token_while_off():
    root, c = start()
    code, p = post(c, "/api/studio/read/plan")
    assert code == 200, p
    assert p["action"] == "studio_read_launch" and p["ok"] is True and p["launched"] is False, p
    assert p["by"] == "user" and p["via"] == "center" and p["channels"] == ["reel"], p
    assert p["argv"][1:3] == ["-p", "--chrome"], p
    assert p["confirm"] is None and p["expires_in_s"] is None, p
    assert p["why"] == studio_center.LAUNCH_OFF_WHY and p["launch"]["available"] is False, p
    assert not runs_dir(root).exists()
    assert not (root / "stub-calls.jsonl").exists()


def test_a_factory_refusal_is_its_russian_line_and_code():
    root, c = start(stub=False)
    code, p = post(c, "/api/studio/read/plan")
    assert code == 200 and p["ok"] is False, p
    assert [r["code"] for r in p["refusals"]] == ["no_claude"], p
    assert p["refusals"][0]["message"] == studio_center.REFUSALS["no_claude"][1], p
    assert p["why"] == studio_center.REFUSALS["no_claude"][1] and p["confirm"] is None, p
    for code_, (status, line) in studio_center.REFUSALS.items():
        assert any("а" <= ch <= "я" for ch in line.lower()), code_


# --------------------------------------------------------------------- the confirm
def test_the_confirm_refuses_launch_off_before_the_token():
    root, c = start()
    called = []
    seam = studio_center.run_launcher
    studio_center.run_launcher = lambda *a: called.append(a) or (0, "{}", "")
    try:
        code, d = post(c, "/api/studio/read", {"confirm": "whatever"})
    finally:
        studio_center.run_launcher = seam
    assert code == 409 and d["code"] == "launch_off", d
    assert d["message"] == studio_center.LAUNCH_OFF_WHY, d
    assert not called and not runs_dir(root).exists()


def test_switched_on_the_confirm_spends_the_token_and_runs_the_launcher():
    root, c = start()
    studio_center.STUDIO_READ_LAUNCH = True
    calls = []

    def stand_in(cmd, cwd, env):
        calls.append((cmd, cwd, env))
        return 0, json.dumps({"ok": True, "launched": True, "run_id": "20261011T120000Z",
                              "pid": 4242, "log": str(runs_dir(root) / "20261011T120000Z.log"),
                              "channels": json.loads(cmd[-1]), "argv": ["claude", "-p"],
                              "by": "user", "via": "center", "refusals": [],
                              "lines": ["запущено"]}) + "\n", ""
    seam = studio_center.run_launcher
    studio_center.run_launcher = stand_in
    try:
        code, p = post(c, "/api/studio/read/plan")
        assert code == 200 and p["confirm"] and p["why"] is None, p
        assert p["expires_in_s"] == 120 and p["launch"]["available"] is True, p
        code, d = post(c, "/api/studio/read", {"confirm": p["confirm"]})
        assert code == 200, d
        assert d["run_id"] == "20261011T120000Z" and d["pid"] == 4242 and d["poll_s"] == 5, d
        assert d["log"] == "schedule/studio-read/runs/20261011T120000Z.log", d
        (cmd, cwd, env), = calls
        assert json.loads(cmd[-1]) == ["reel"] and cmd[-2] == studio_center.FACTORY_KW["claude"]
        assert env["STUDIO_READ_STATE_DIR"].startswith(str(root)) and cwd == str(root)
        code, d = post(c, "/api/studio/read", {"confirm": p["confirm"]})
        assert code == 409 and d["code"] == "confirm_unknown", d
        # a refusal from the launch itself (another session started meanwhile)
        code, p = post(c, "/api/studio/read/plan")
        studio_center.run_launcher = lambda cmd, cwd, env: (0, json.dumps(
            {"ok": False, "refusals": [{"code": "running", "line": "чтение уже идёт (x)"}]}), "")
        code, d = post(c, "/api/studio/read", {"confirm": p["confirm"]})
        assert code == 409 and d["code"] == "running", d
        assert d["message"] == studio_center.REFUSALS["running"][1], d
        # the launcher did not answer
        code, p = post(c, "/api/studio/read/plan")
        studio_center.run_launcher = lambda cmd, cwd, env: (1, "", "Traceback ...")
        code, d = post(c, "/api/studio/read", {"confirm": p["confirm"]})
        assert code == 500 and d["code"] == "launch_failed", d
    finally:
        studio_center.run_launcher = seam
        studio_center.STUDIO_READ_LAUNCH = False


def test_the_launcher_child_starts_only_the_stand_in():
    """The real child (`child.run`) of the factory's launch - against the
    stand-in `claude` named explicitly (it outranks the environment and PATH)."""
    root, c = start()
    studio_center.STUDIO_READ_LAUNCH = True
    try:
        code, p = post(c, "/api/studio/read/plan")
        assert p["argv"][0] == "bin/claude", p          # the stand-in, from the root
        code, d = post(c, "/api/studio/read", {"confirm": p["confirm"]})
    finally:
        studio_center.STUDIO_READ_LAUNCH = False
    assert code == 200 and d["launched"] and d["run_id"], d
    end = time.time() + 20
    while time.time() < end:
        code, r = get(c, f"/api/studio/read/{d['run_id']}")
        if r.get("done"):
            break
        assert r["code"] == "running" and r["poll_s"] == 5, r
        time.sleep(0.1)
    assert code == 200 and r["code"] == "no_extension", r
    assert r["word"] == "расширение не подключено" and r["poll_s"] is None, r
    call = json.loads((root / "stub-calls.jsonl").read_text(encoding="utf-8"))
    assert call["argv"][:2] == ["-p", "--chrome"] and "reel" in call["prompt"], call


# --------------------------------------------------------------------- the result
def _run(root, run_id, log_text, pid=None):
    d = runs_dir(root)
    d.mkdir(parents=True, exist_ok=True)
    log = d / f"{run_id}.log"
    log.write_text(log_text, encoding="utf-8")
    (d / f"{run_id}.json").write_text(json.dumps(
        {"run_id": run_id, "task": "CF-0735", "started_at": NOW, "by": "user",
         "via": "center", "channels": ["reel"], "pid": pid, "argv": [], "log": str(log),
         "prompt": ""}), encoding="utf-8")


def test_the_result_words_and_the_poll_hint():
    root, c = start()
    _run(root, "20261011T110000Z", "STUDIO_READ_RESULT: login_needed - accounts.google.com\n")
    code, r = get(c, "/api/studio/read/20261011T110000Z")
    assert code == 200 and r["code"] == "login_needed" and r["word"] == "нужен вход", r
    assert r["done"] is True and r["poll_s"] is None, r
    assert r["log"] == "schedule/studio-read/runs/20261011T110000Z.log", r
    _run(root, "20261011T110500Z", "читаю...\n", pid=os.getpid())     # alive, no result line
    code, r = get(c, "/api/studio/read/20261011T110500Z")
    assert code == 200 and r["code"] == "running" and r["word"] == "читается", r
    assert r["done"] is False and r["poll_s"] == 5, r
    _run(root, "20261011T111000Z", "STUDIO_READ_RESULT: read - reel\n")
    code, r = get(c, "/api/studio/read/20261011T111000Z")
    assert code == 200 and r["code"] == "error" and "записи чтения" in r["detail"], r
    code, r = get(c, "/api/studio/read/20261011T235959Z")
    assert code == 404 and r["code"] == "unknown_run", r
    code, r = get(c, "/api/studio/read/not-a-run")
    assert code == 422 and r["code"] == "bad_run", r


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    studio_center.FACTORY_KW.clear()
    studio_center.STUDIO_READ_LAUNCH = False
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
