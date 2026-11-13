#!/usr/bin/env python3
"""CF-0591: the notification bus (`shared/notify.py`).

Every journal is a temp dir; every backend that is called is a stand-in - no
banner is shown, nothing leaves the machine.

What is pinned:

* one notification per key: a second send of the same key is a no-op (no
  backend called, no second row); `again` makes a new key;
* only the backends the setting names are called - the default is `log` alone,
  `macos` and the outside ones are off until `NOTIFY_BACKENDS` names them; an
  outside backend without its address is skipped, not called;
* a backend that raises is written in the row and the send still returns; a
  journal that cannot be written does not raise either;
* the text is one line, cut, and a secret in it is masked;
* the console's anchors that the bus links to exist on the page;
* the CLI: send / list / test (test sends nothing and writes no row).
"""
import io
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import notify                       # noqa: E402

from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("notify-test-")
_n = [0]


def fresh(backends="log", extra=None):
    """A temp root and the environ the bus reads (nothing from the real one)."""
    _n[0] += 1
    root = TMP / f"r{_n[0]}"
    root.mkdir()
    env = {"NOTIFY_STATE_DIR": str(root / "state")}
    if backends is not None:
        env["NOTIFY_BACKENDS"] = backends
    env.update(extra or {})
    return root, env


class Recorder:
    def __init__(self, fail=None):
        self.calls = []
        self.fail = fail

    def __call__(self, ev, cfg):
        self.calls.append(dict(ev))
        if self.fail:
            raise self.fail


def registry(**kw):
    return {name: kw.get(name) or Recorder() for name in notify.BACKENDS}


def test_one_notification_per_key():
    root, env = fresh("log")
    reg = registry()
    r1 = notify.send("empty_slot", "empty_slot:alpha:x", "пусто", channel="alpha", root=root,
                     environ=env, backends=reg)
    r2 = notify.send("empty_slot", "empty_slot:alpha:x", "пусто опять", channel="alpha",
                     root=root, environ=env, backends=reg)
    assert r1["status"] == "sent" and r2["status"] == "duplicate", (r1, r2)
    assert len(reg["log"].calls) == 1
    assert len(notify.rows(root, env)) == 1
    r3 = notify.send("empty_slot", "empty_slot:alpha:x", "напоминание", again="2", root=root,
                     environ=env, backends=reg)
    assert r3["status"] == "sent" and r3["key"] == "empty_slot:alpha:x#again:2"
    assert len(reg["log"].calls) == 2 and len(notify.rows(root, env)) == 2
    assert notify.was_sent("empty_slot:alpha:x", root, env)


def test_default_is_log_alone_and_a_backend_that_is_off_is_not_called():
    root, env = fresh(backends=None)
    assert notify.enabled(root, env) == ["log"]
    reg = registry()
    notify.send("token", "token:t1", "токен", root=root, environ=env, backends=reg)
    assert len(reg["log"].calls) == 1
    for name in ("macos", "ntfy", "telegram", "webhook"):
        assert reg[name].calls == [], f"{name} is off and was called"
    root, env = fresh("log,macos")
    reg = registry()
    notify.send("token", "token:t1", "токен", root=root, environ=env, backends=reg)
    assert len(reg["macos"].calls) == 1 and reg["ntfy"].calls == []


def test_the_setting_is_read_from_the_roots_env_file_and_the_environment_wins():
    root, env = fresh(backends=None)
    (root / ".env").write_text("NOTIFY_BACKENDS=log,macos\nOTHER=1\n", encoding="utf-8")
    assert notify.enabled(root, env) == ["log", "macos"]
    env["NOTIFY_BACKENDS"] = "log"
    assert notify.enabled(root, env) == ["log"]


def test_an_outside_backend_without_its_address_is_skipped():
    root, env = fresh("log,ntfy,telegram,webhook")
    res = notify.send("run_halted", "alert:a:1", "сигнал", root=root, environ=env)
    assert res["status"] == "sent"
    for name in ("ntfy", "telegram", "webhook"):
        assert res["backends"][name].startswith("skipped: no NOTIFY_"), res["backends"]
    assert res["backends"]["log"] == "ok"


def test_a_failing_backend_does_not_break_the_send():
    root, env = fresh("log,macos")
    reg = registry(macos=Recorder(fail=RuntimeError("osascript exited 1")))
    res = notify.send("accept", "accept:a:b:s", "ждёт приёмки", root=root, environ=env,
                      backends=reg)
    assert res["status"] == "sent"
    assert res["backends"]["macos"].startswith("error: RuntimeError"), res["backends"]
    assert res["backends"]["log"] == "ok"
    row = notify.rows(root, env)[0]
    assert row["backends"]["macos"].startswith("error")


def test_a_journal_that_cannot_be_written_does_not_raise():
    root, env = fresh("log")
    blocker = root / "file"
    blocker.write_text("x")
    env["NOTIFY_STATE_DIR"] = str(blocker / "state")       # under a file: mkdir fails
    res = notify.send("run_done", "run_done:a:b", "готово", root=root, environ=env,
                      backends=registry())
    assert res["status"] == "error"


def test_a_bad_event_is_refused_without_raising():
    root, env = fresh("log")
    assert notify.send("nope", "k", "t", root=root, environ=env)["status"] == "error"
    assert notify.send("token", "  ", "t", root=root, environ=env)["status"] == "error"
    assert notify.rows(root, env) == []


def test_the_text_is_one_line_and_carries_no_secret():
    root, env = fresh("log")
    reg = registry()
    secret_access = "ya29.a0AfB_byDEADBEEF"
    secret_refresh = "1//0gQwErTyUiOpAsDfGhJkL"
    secret_client = "GOCSPX-AbCdEfGh123"
    text = (f"строка\nвторая  строка access {secret_access} refresh {secret_refresh} "
            f"client {secret_client} token=plainvalue " + "x" * 300)
    notify.send("token", "token:s", text, link=f"http://127.0.0.1:8790/?key=abc#token",
                root=root, environ=env, backends=reg)
    ev = reg["log"].calls[0]
    assert "\n" not in ev["text"] and len(ev["text"]) <= notify.TEXT_MAX
    raw = (Path(env["NOTIFY_STATE_DIR"]) / notify.JOURNAL).read_text(encoding="utf-8")
    for s in (secret_access, secret_refresh, secret_client, "plainvalue", "key=abc"):
        assert s not in ev["text"] and s not in raw and s not in (ev["link"] or ""), s
    assert "my-long-lowercase-slug-of-a-video-about-ducks" in notify.scrub(
        "my-long-lowercase-slug-of-a-video-about-ducks"), "a slug is not a secret"


def test_links_are_the_centers_routes():
    """CC-0035: the console is retired, its anchors are only the names the
    sources still give a place; each one has a route of the center."""
    for sec in notify.CHANNEL_SECTIONS:
        assert sec in notify.CHANNEL_ROUTES, sec
    for a in notify.GLOBAL_ANCHORS:
        assert a in notify.GLOBAL_ROUTES, a
    # CF-0735: the anchors are the center's routes now
    assert notify.dashboard_url("token", environ={}) == "http://127.0.0.1:8790/tokens"
    assert notify.dashboard_url("x", environ={"NOTIFY_DASHBOARD_URL": "http://h:1/#old"}) \
        == "http://h:1/"
    assert notify.dashboard_url("needs-you", environ={"NOTIFY_CENTER_URL": "http://h:2"}) \
        == "http://h:2/questions"


def test_a_stored_link_goes_to_the_center_on_8790():
    """CC-0035: the center took 8790 from the retired console. A link of the
    console (the main path with an anchor) -> the anchor's route; a link of
    the center before it moved (8791) -> the same route on 8790; a center
    link with a path, the main page, an outside URL, a file -> as they are."""
    c = "http://127.0.0.1:8790/"
    cl = lambda link, env=None: notify.center_link(link, {} if env is None else env)  # noqa: E731
    assert cl(f"{c}#ch-alpha-batch") == f"{c}batches?channel=alpha"
    assert cl("http://localhost:8790/?key=abc#token") == f"{c}tokens"
    assert cl(f"{c}#nonsense") == c
    assert cl(f"{c}videos?channel=x") == f"{c}videos?channel=x", "a center link keeps its path"
    assert cl(f"{c}videos#top") == f"{c}videos#top"
    assert cl(c) == c and cl("http://127.0.0.1:8790") == "http://127.0.0.1:8790"
    assert cl("http://127.0.0.1:8791/videos?channel=x") == f"{c}videos?channel=x"
    assert cl("http://[::1]:8791/batches") == f"{c}batches"
    assert cl("http://127.0.0.1:8791/") == c
    assert cl("http://127.0.0.1:8791/#ch-alpha-feed") == f"{c}publishing?channel=alpha"
    assert cl("http://127.0.0.1:8791/questions", {"NOTIFY_CENTER_URL": "http://h:2/"}) \
        == "http://h:2/questions"
    assert cl("http://127.0.0.1:9999/#token") == "http://127.0.0.1:9999/#token"
    assert cl("http://example.com:8791/x") == "http://example.com:8791/x"
    assert cl("/home/x/v.mp4") == "/home/x/v.mp4" and cl(None) is None


def test_an_unknown_channel_anchor_falls_back_to_the_channel_page():
    """CF-0735 follow-up: `ch-<c>-<unknown>` -> the channel's page, not
    `channels/<c>-<unknown>`; a hyphenated channel id with a config keeps its
    whole id; a fully unknown anchor -> the main page; known sections stay."""
    root, _env = fresh("anchors")
    (root / "channels").mkdir()
    for c in ("alpha", "old-reel"):
        (root / "channels" / f"{c}.json").write_text(json.dumps({"channel_id": c}),
                                                    encoding="utf-8")
    r = lambda a: notify.center_route(a, root=root)            # noqa: E731
    assert r("ch-alpha-whatever") == ("channels/alpha", None)
    assert r("ch-alpha-some-new-thing") == ("channels/alpha", None)
    assert r("ch-old-reel") == ("channels/old-reel", None)
    assert r("ch-old-reel-oddity") == ("channels/old-reel", None)
    assert r("ch-nochan-oddity") == ("channels/nochan", None)
    assert r("ch-alpha") == ("channels/alpha", None)
    assert r("ch-nochan") == ("channels/nochan", None)
    assert r("ch-alpha-batch") == ("batches", "alpha")
    assert r("ch-old-reel-feed") == ("publishing", "old-reel")
    assert r("ch-alpha-acceptance") == ("videos", "alpha")
    assert r("token") == ("tokens", None)
    assert r("whatever-this-is") == ("", None)
    assert r("ch-") == ("", None) and r("ch--x") == ("", None) and r(None) == ("", None)
    assert notify.dashboard_url("ch-zz-oddity", environ={}) == "http://127.0.0.1:8790/channels/zz"
    assert notify.dashboard_url("nonsense", environ={}) == "http://127.0.0.1:8790/"


def test_the_macos_command_quotes_the_text():
    argv = notify.macos_argv({"text": 'a "quoted" \\ line', "link": "http://127.0.0.1:8790/#token"})
    assert argv[:2] == ["osascript", "-e"]
    assert 'display notification "a \\"quoted\\" \\\\ line"' in argv[2]
    assert 'subtitle "http://127.0.0.1:8790/#token"' in argv[2]


def _cli(args, env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        buf = io.StringIO()
        code = notify.main(args, out=buf)
        return code, buf.getvalue()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_cli_send_list_and_test():
    root, env = fresh("log")
    base = ["--root", str(root)]
    code, out = _cli(["send", "--kind", "empty_slot", "--key", "k1", "--text", "пустой слот",
                      "--channel", "alpha", "--anchor", "ch-alpha-feed", *base], env)
    assert code == 0 and out.startswith("sent: k1"), out
    code, out = _cli(["send", "--kind", "empty_slot", "--key", "k1", "--text", "x", *base], env)
    assert code == 0 and out.startswith("duplicate: k1"), out
    code, out = _cli(["list", *base], env)
    assert code == 0 and "пустой слот -> http://127.0.0.1:8790/publishing?channel=alpha" in out, out
    assert "1 event(s)" in out
    code, out = _cli(["send", "--kind", "bogus", "--key", "k", "--text", "t", *base], env)
    assert code == 2
    root2, env2 = fresh("log,macos,ntfy")
    code, out = _cli(["test", "--root", str(root2)], env2)
    assert code == 0 and "backends on: log, macos, ntfy" in out, out
    assert "ntfy: would get" in out and "would be skipped" in out
    assert "nothing sent" in out
    assert notify.rows(root2, env2) == [], "test writes no row"
    env2["NOTIFY_NTFY_URL"] = "https://ntfy.example/topic"
    code, out = _cli(["test", "--root", str(root2)], env2)
    assert "SENDS THE TEXT TO AN OUTSIDE SERVICE" in out


def test_the_journal_is_gitignored():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/notify/" in ignore
    assert notify.state_dir(None, environ={}) == ROOT / "notify"


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
