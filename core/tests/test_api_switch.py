#!/usr/bin/env python3
"""CF-0607: the per-channel switch of the API upload (`agents/publisher/api_switch.py`).

Temp roots only; no network, no launchctl, no token of the user's. Pinned:

* off by default for every channel, and `check` refuses with the one line
  `upload.py` prints;
* `enable` takes `--by user` and a note only; `disable` takes anyone; every
  change is a history row (who, when, the note, the warnings), written
  atomically into the state directory (`schedule/`, gitignored), never into
  `channels/*.json`;
* the warnings on enable - the OAuth app in Testing, the tick's timer not
  installed, the token not usable - are said and written, and block nothing;
* an unreadable state reads as off and is not overwritten;
* `batch_schedule.timer_state` looks for the plist in ~/Library/LaunchAgents.
"""
import io
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AGENT = ROOT / "agents" / "publisher"
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(AGENT))
sys.path.append(str(ROOT / "shared"))

import api_switch                   # noqa: E402
import batch_schedule               # noqa: E402
import publisher_auth               # noqa: E402
import publisher_config             # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("api-switch-test-")
_n = [0]
CH = "example-film"
NOW = datetime(2026, 10, 7, 12, 0, tzinfo=timezone.utc)
TIMER_ON = {"installed": True, "line": "таймер тика установлен"}
TIMER_OFF = {"installed": False, "line": "таймер тика НЕ установлен (нет plist)"}
ENV = {"BATCH_SCHEDULE_STATE_DIR": ""}


def fixture(mode="testing", token=True):
    """A temp root with channels/<CH>.json and a Publisher .env whose secrets
    lie in the temp dir (outside any git tree); `token` - a usable token."""
    _n[0] += 1
    root = TMP / f"r{_n[0]}"
    (root / "channels").mkdir(parents=True)
    (root / "channels" / f"{CH}.json").write_text('{"name": "Example Reel"}', encoding="utf-8")
    sec = root / "sec"
    env = root / "publisher.env"
    env.write_text(f"PUBLISHER_CLIENT_SECRET_FILE={sec}/client_secret.json\n"
                   f"PUBLISHER_TOKEN_FILE={sec}/t.oauth-token.json\n"
                   f"PUBLISHER_CHANNEL_ID=UCtest\nPUBLISHER_OAUTH_MODE={mode}\n", encoding="utf-8")
    if token:
        cfg = publisher_config.load(env, environ={})
        sec.mkdir()
        cfg.token_file.write_text(json.dumps({"refresh_token": "r", "scopes": publisher_auth.SCOPES}))
        publisher_auth.write_state(cfg, {"authorized_at": "2026-10-07T00:00:00Z",
                                         "oauth_mode": mode, "scopes": publisher_auth.SCOPES,
                                         "expires_at": None if mode == "production"
                                         else "2026-10-14T00:00:00Z"})
    return root, env


def _set(root, env, on, by="user", note="чат 07.10: аудит пройден", timer=TIMER_ON):
    return api_switch.set_switch(CH, on, by, note, root=root, now=NOW, environ=ENV,
                                 env_file=env, timer=timer)


def test_off_by_default_and_the_gate_says_one_line():
    root, _ = fixture()
    st = api_switch.channel_state(CH, root, ENV)
    assert st["on"] is False and "ВЫКЛЮЧЕНА" in st["line"] and "не включалась" in st["line"]
    try:
        api_switch.check(CH, root, ENV)
    except api_switch.SwitchError as e:
        assert str(e) == ("API-загрузка для example-film выключена: ждёт аудита YouTube API "
                          "(CF-0470, docs/api-audit/README.md); публикация — через Studio")
    else:
        raise AssertionError("an untouched channel must be off")
    assert not (root / "schedule").exists(), "reading writes nothing"


def test_enable_needs_the_user_and_a_note_and_disable_takes_anyone():
    root, env = fixture(mode="production")
    for by, note in (("operator", "x"), ("claude", "x"), ("user", ""), ("User!", "x")):
        try:
            _set(root, env, True, by=by, note=note)
        except api_switch.SwitchError:
            pass
        else:
            raise AssertionError(f"enable by {by!r} note {note!r} must be refused")
    assert not api_switch.is_on(CH, root, ENV)
    got = _set(root, env, True)
    assert got["changed"] and got["state"]["on"] and api_switch.check(CH, root, ENV)["on"]
    got = _set(root, env, False, by="operator", note="")
    assert got["changed"] and not got["state"]["on"]
    try:
        api_switch.set_switch("nochannel", True, "user", "x", root=root, environ=ENV,
                              env_file=env, timer=TIMER_ON)
    except api_switch.SwitchError as e:
        assert "нет в channels/" in str(e)
    else:
        raise AssertionError("an unknown channel must be refused")


def test_every_change_is_a_history_row_in_the_state_dir_written_atomically():
    root, env = fixture(mode="production")
    _set(root, env, True)
    _set(root, env, False, by="operator", note="ролик ушёл не туда")
    p = root / "schedule" / api_switch.STATE_FILE
    doc = json.loads(p.read_text(encoding="utf-8"))
    assert [h["action"] for h in doc["history"]] == ["enable", "disable"]
    assert doc["history"][0]["by"] == "user" and doc["history"][0]["at"] == "2026-10-07T12:00:00Z"
    assert doc["history"][0]["note"] == "чат 07.10: аудит пройден"
    assert doc["history"][1]["note"] == "ролик ушёл не туда" and "warnings" not in doc["history"][1]
    assert doc["channels"][CH]["on"] is False
    assert not list(p.parent.glob("*.tmp")), "the write goes through a temp file and os.replace"
    assert json.loads((root / "channels" / f"{CH}.json").read_text()) == {"name": "Example Reel"}
    src = (AGENT / "api_switch.py").read_text(encoding="utf-8")
    assert "os.replace(tmp, path)" in src and src.count("write_text(") == 1
    st = api_switch.channel_state(CH, root, ENV)
    assert len(st["history"]) == 2 and "operator" in st["line"]


def test_the_warnings_are_said_written_and_block_nothing():
    root, env = fixture(mode="testing", token=False)
    got = _set(root, env, True, timer=TIMER_OFF)
    assert got["state"]["on"], "warnings never block"
    w = "\n".join(got["warnings"])
    assert len(got["warnings"]) == 3, got["warnings"]
    assert "Testing" in w and "PUBLISHER_OAUTH_MODE" in w
    assert "таймер тика" in w and "пробел 7" in w and "CF-0618" in w
    assert "токен:" in w and "OAUTH NO AUTH" in w
    doc = json.loads((root / "schedule" / api_switch.STATE_FILE).read_text(encoding="utf-8"))
    assert doc["history"][-1]["warnings"] == got["warnings"]
    assert api_switch.channel_state(CH, root, ENV)["warnings"] == got["warnings"]
    root, env = fixture(mode="production")
    assert _set(root, env, True, timer=TIMER_ON)["warnings"] == []
    root, env = fixture(mode="testing")
    w = _set(root, env, True, timer=TIMER_ON)["warnings"]
    assert len(w) == 1 and "Testing" in w[0]


def test_an_unreadable_state_reads_off_and_is_not_overwritten():
    root, env = fixture(mode="production")
    p = root / "schedule" / api_switch.STATE_FILE
    p.parent.mkdir(parents=True)
    p.write_text("{ broken", encoding="utf-8")
    st = api_switch.channel_state(CH, root, ENV)
    assert st["on"] is False and "не читается" in st["line"]
    try:
        _set(root, env, True)
    except api_switch.SwitchError as e:
        assert "does not parse" in str(e)
    else:
        raise AssertionError("a broken state must not be overwritten")
    assert p.read_text(encoding="utf-8") == "{ broken"


def test_the_cli_enable_disable_status():
    root, env = fixture(mode="testing", token=False)
    base = ["--root", str(root), "--env", str(env), "--now", "2026-10-07T12:00:00Z"]
    out = io.StringIO()
    assert api_switch.main(base + ["status"], out=out) == 0
    assert "ВЫКЛЮЧЕНА" in out.getvalue()
    out = io.StringIO()
    assert api_switch.main(base + ["enable", CH, "--by", "operator", "--note", "x"], out=out) == 1
    assert "REFUSED" in out.getvalue() and "only the user" in out.getvalue()
    out = io.StringIO()
    rc = api_switch.main(base + ["enable", CH, "--by", "user", "--note", "чат"], out=out,
                         timer=TIMER_OFF)
    assert rc == 0 and out.getvalue().count("WARNING ") == 3 and "ВКЛЮЧЕНА" in out.getvalue()
    out = io.StringIO()
    assert api_switch.main(base + ["status", "--channel", CH], out=out) == 0
    assert "ВКЛЮЧЕНА" in out.getvalue() and "при включении:" in out.getvalue()
    out = io.StringIO()
    assert api_switch.main(base + ["disable", CH, "--by", "operator"], out=out) == 0
    assert "ВЫКЛЮЧЕНА" in out.getvalue()


def test_the_state_dir_is_gitignored_and_follows_the_schedule_env():
    cp = subprocess.run(["git", "check-ignore", "-q", "schedule/api-upload.json"], cwd=ROOT,
                        timeout=30)
    assert cp.returncode == 0, "schedule/ (the console's state) is gitignored"
    other = TMP / "elsewhere"
    assert api_switch.state_path(TMP, {"BATCH_SCHEDULE_STATE_DIR": str(other)}) == \
        other / api_switch.STATE_FILE


def test_timer_state_looks_for_the_plist_in_launch_agents():
    home = TMP / "home"
    st = batch_schedule.timer_state(home)
    assert st["installed"] is False and "НЕ установлен" in st["line"]
    plist = home / "Library" / "LaunchAgents" / f"{batch_schedule.LABEL}.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("<plist/>")
    assert batch_schedule.timer_state(home)["installed"] is True




if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
