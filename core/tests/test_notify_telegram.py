#!/usr/bin/env python3
"""CF-0606: the bus's Telegram backend and the user's reminders.

No network: `notify._post` is replaced by a stand-in that records the call
(or raises the way urllib does); the bot token in these tests is made up.

What is pinned:

* `sendMessage` gets plain text (no parse_mode - nothing to escape, the text
  goes as it is), the chat id, no preview; a console link becomes the
  section's name, a file its name, an outside URL stays;
* the 4096 limit: a longer text is cut with a mark;
* the token never reaches the journal, stderr, an exception or the CLI output
  - also when the HTTP layer puts the URL into its error;
* a failing Telegram does not fail the send (the row says `error: ...`);
* the local backends (log, macos) keep the console link;
* `test --send` sends one probe event per run to the backends that are on.
"""
import contextlib
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

TMP = tmp_root("notify-tg-test-")
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijklmnop"
CHAT = "-1001234"
_n = [0]


def fresh(backends="log,telegram", extra=None):
    _n[0] += 1
    root = TMP / f"r{_n[0]}"
    root.mkdir()
    env = {"NOTIFY_STATE_DIR": str(root / "state"), "NOTIFY_BACKENDS": backends,
           "NOTIFY_TELEGRAM_TOKEN": TOKEN, "NOTIFY_TELEGRAM_CHAT": CHAT}
    env.update(extra or {})
    return root, env


class FakePost:
    def __init__(self, reply=b'{"ok": true, "result": {}}', fail=None):
        self.calls = []
        self.reply = reply
        self.fail = fail

    def __call__(self, url, data, headers):
        self.calls.append((url, data, headers))
        if self.fail:
            raise self.fail
        return self.reply

    def form(self, i=-1):
        from urllib.parse import parse_qs
        return {k: v[0] for k, v in parse_qs(self.calls[i][1].decode()).items()}


@contextlib.contextmanager
def posting(fake):
    old = notify._post
    notify._post = fake
    try:
        yield fake
    finally:
        notify._post = old


def _send(env, root, fake, **kw):
    err = io.StringIO()
    with posting(fake), contextlib.redirect_stderr(err):
        res = notify.send(kw.pop("kind", "run_done"), kw.pop("key", "k1"), kw.pop("text", "готово"),
                          root=root, environ=env, **kw)
    return res, err.getvalue()


def test_send_message_is_plain_text_with_the_section_name_instead_of_the_console_link():
    root, env = fresh()
    fake = FakePost()
    res, _ = _send(env, root, fake, channel="example-film", text="батч <b>&готов_*",
                   link=notify.link_of("example-film", "batch"))
    assert res["status"] == "sent" and res["backends"]["telegram"] == "ok", res
    url, _data, headers = fake.calls[0]
    assert url == f"https://api.telegram.org/bot{TOKEN}/sendMessage"
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    form = fake.form()
    assert form["chat_id"] == CHAT and form["disable_web_page_preview"] == "true"
    assert "parse_mode" not in form, "plain text: nothing is markup"
    assert "батч <b>&готов_*" in form["text"], form["text"]
    # CF-0735: the center's page by name, and its address (CC-0035: 8790, not the old 8791)
    # CF-0925: the channel by its name (Reel), the head in words, not the kind
    assert "центр → Батчи · канал Reel: http://127.0.0.1:8790/batches?channel=example-film" \
        in form["text"], form["text"]
    assert form["text"].startswith("Батч закончен · Reel\n"), form["text"]
    assert "run_done" not in form["text"] and "example-film\n" not in form["text"]
    assert "8791" not in form["text"]
    row = notify.rows(root, env)[-1]
    assert row["link"] == "http://127.0.0.1:8790/batches?channel=example-film", "the journal keeps the link"


def test_links_for_the_phone():
    # CF-0735: an old console link (a stored question) goes to the center's page
    c = "http://127.0.0.1:8790/"
    assert notify.phone_link("http://127.0.0.1:8790/#ch-alpha-acceptance", {}) == \
        f"центр → Ролики · канал alpha: {c}videos?channel=alpha"
    assert notify.phone_link("http://127.0.0.1:8790/#ch-my-feed-ch-feed", {}) == \
        f"центр → Публикация · канал my-feed-ch: {c}publishing?channel=my-feed-ch"
    assert notify.phone_link("http://127.0.0.1:8790/#ch-alpha", {}) == \
        f"центр → Каналы → alpha: {c}channels/alpha"
    assert notify.phone_link("http://127.0.0.1:8790/#schedule", {}) == f"центр → Батчи: {c}batches"
    assert notify.phone_link(f"{c}tokens", {}) == f"центр → Токены: {c}tokens"
    assert notify.phone_link("http://127.0.0.1:8790/", {}) == f"центр: {c}"
    # CC-0035: the center is on 8790 - its own links keep their path; a link of
    # the center before it moved (8791) goes to the same page on 8790
    assert notify.phone_link(f"{c}videos?channel=alpha", {}) == \
        f"центр → Ролики · канал alpha: {c}videos?channel=alpha"
    assert notify.phone_link("http://127.0.0.1:8791/videos?channel=alpha", {}) == \
        f"центр → Ролики · канал alpha: {c}videos?channel=alpha"
    assert notify.phone_link("http://localhost:8791/", {}) == f"центр: {c}"
    assert notify.phone_link(c, {}) == f"центр: {c}"
    assert notify.phone_link("http://localhost:9999/notifications", {}) == \
        "центр → Уведомления: http://localhost:9999/notifications"
    assert notify.phone_link("/home/x/publish/alpha/2026-10-07/v.mp4", {}) == "файл на Mac: v.mp4"
    assert notify.phone_link("https://youtu.be/abc", {}) == "https://youtu.be/abc"
    assert notify.phone_link(None, {}) == ""
    assert notify.phone_link("http://h:1/tokens", {"NOTIFY_DASHBOARD_URL": "http://h:1/"}) == \
        "центр → Токены: http://h:1/tokens"


def test_local_backends_keep_the_console_link():
    root, env = fresh("log,macos")
    seen = {}

    def rec(name):
        return lambda ev, cfg: seen.setdefault(name, dict(ev))

    reg = {n: rec(n) for n in notify.BACKENDS}
    res = notify.send("accept", "a1", "ждёт приёмки", channel="alpha",
                      link=notify.link_of("alpha", "acceptance"), root=root, environ=env, backends=reg)
    assert res["status"] == "sent"
    assert seen["log"]["link"] == "http://127.0.0.1:8790/videos?channel=alpha"
    argv = notify.macos_argv(seen["macos"])
    assert "http://127.0.0.1:8790/videos?channel=alpha" in argv[2]


def test_a_long_text_is_cut_at_the_telegram_limit_with_a_mark():
    ev = {"kind": "reminder", "text": "я" * 5000, "link": None, "channel": None}
    text = notify.telegram_text(ev, {})
    assert len(text) <= notify.TELEGRAM_MAX, len(text)
    assert text.endswith(notify.TELEGRAM_CUT)
    short = notify.telegram_text({"kind": "reminder", "text": "позвонить", "link": None}, {})
    assert short == "Напоминание\nпозвонить", short


def test_the_token_never_reaches_the_journal_the_log_or_an_exception():
    leaky = RuntimeError(f"<urlopen error for https://api.telegram.org/bot{TOKEN}/sendMessage>")
    for fail in (leaky, OSError(f"bot{TOKEN} refused"), ValueError(TOKEN)):
        root, env = fresh()
        res, err = _send(env, root, FakePost(fail=fail))
        assert res["status"] == "sent", "a failing Telegram does not fail the send"
        assert res["backends"]["telegram"].startswith("error:"), res
        assert res["backends"]["log"] == "ok"
        assert TOKEN not in json.dumps(res, ensure_ascii=False)
        assert TOKEN not in err and "NOTIFY telegram error" in err, err
        assert TOKEN not in (Path(env["NOTIFY_STATE_DIR"]) / "sent.jsonl").read_text()
    # and straight from the backend: the raised exception carries no token, no chain
    with posting(FakePost(fail=leaky)):
        try:
            notify._telegram({"kind": "run_done", "text": "x", "link": None},
                             {"NOTIFY_TELEGRAM_TOKEN": TOKEN, "NOTIFY_TELEGRAM_CHAT": CHAT})
            raise AssertionError("must raise")
        except RuntimeError as e:
            assert TOKEN not in str(e) and e.__cause__ is None and e.__suppress_context__


def test_telegram_saying_not_ok_is_an_error_with_its_description():
    root, env = fresh()
    res, err = _send(env, root, FakePost(reply=b'{"ok": false, "description": "Bad Request: chat not found"}'))
    assert "chat not found" in res["backends"]["telegram"], res
    assert TOKEN not in err


def test_the_real_post_masks_an_http_error_and_has_a_timeout():
    import urllib.error
    import urllib.request
    seen = {}

    def fake_urlopen(req, timeout=None):
        seen["timeout"] = timeout
        raise urllib.error.HTTPError(req.full_url, 401, "Unauthorized", {},
                                     io.BytesIO(b'{"ok":false,"description":"Unauthorized"}'))

    old = urllib.request.urlopen
    urllib.request.urlopen = fake_urlopen
    try:
        try:
            notify._post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", b"x", {})
            raise AssertionError("must raise")
        except RuntimeError as e:
            assert str(e).startswith("HTTP 401") and "Unauthorized" in str(e)
            assert TOKEN not in str(e) and e.__cause__ is None
    finally:
        urllib.request.urlopen = old
    assert seen["timeout"] == notify.HTTP_TIMEOUT_S


def test_telegram_without_its_address_is_skipped_not_called():
    root, env = fresh(extra={"NOTIFY_TELEGRAM_CHAT": ""})
    fake = FakePost()
    res, _ = _send(env, root, fake)
    assert res["backends"]["telegram"].startswith("skipped: no NOTIFY_TELEGRAM_CHAT"), res
    assert fake.calls == []


def _cli(args, env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        buf, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stderr(err):
            code = notify.main(args, out=buf)
        return code, buf.getvalue(), err.getvalue()
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_cli_test_previews_and_test_send_probes_every_backend_that_is_on():
    root, env = fresh()
    fake = FakePost()
    with posting(fake):
        code, out, err = _cli(["test", "--root", str(root)], env)
        assert code == 0 and "telegram: would get" in out and "центр" in out, out
        assert fake.calls == [] and notify.rows(root, env) == []
        assert TOKEN not in out + err
        code, out, err = _cli(["test", "--send", "--root", str(root)], env)
        assert code == 0, out
        assert "sent: test:" in out and "telegram: ok" in out and "log: ok" in out, out
        assert len(fake.calls) == 1 and "пробное сообщение" in fake.form()["text"]
        assert TOKEN not in out + err
    with posting(FakePost(fail=RuntimeError(f"bot{TOKEN}"))):
        code, out, err = _cli(["test", "--send", "--root", str(root)], env)
    assert code == 1 and "telegram: error" in out and TOKEN not in out + err, out
    assert len([r for r in notify.rows(root, env) if r["kind"] == "test"]) == 2


# ------------------------------------------------------------------ reminders
NOW = "2026-10-07T15:00:00Z"            # 18:00 МСК


def test_when_is_moscow_time_kept_in_utc():
    assert notify._utc_iso(notify.parse_when("21:00", NOW)) == "2026-10-07T18:00:00Z"
    assert notify._utc_iso(notify.parse_when("21:00 МСК", NOW)) == "2026-10-07T18:00:00Z"
    assert notify._utc_iso(notify.parse_when("09:30", NOW)) == "2026-10-08T06:30:00Z", "passed today: tomorrow"
    assert notify._utc_iso(notify.parse_when("2026-10-09 07:05 MSK", NOW)) == "2026-10-09T04:05:00Z"
    for bad in ("25:00", "21-00", "2026-10-01 10:00", "2026-02-30 10:00", "", "21:00 UTC"):
        try:
            notify.parse_when(bad, NOW)
            raise AssertionError(f"{bad!r} must be refused")
        except ValueError:
            pass
    assert notify.msk_text("2026-10-07T18:00:00Z") == "2026-10-07 21:00 МСК"


def test_queue_list_cancel_and_the_same_reminder_is_queued_once():
    root, env = fresh("log")
    r1, new = notify.add_reminder("21:00", "проверить  батч", root=root, now=NOW, environ=env)
    assert new and r1["id"] == "R1" and r1["due"] == "2026-10-07T18:00:00Z" and r1["text"] == "проверить батч"
    again, new = notify.add_reminder("21:00 МСК", "проверить батч", root=root, now=NOW, environ=env)
    assert not new and again["id"] == "R1", "the same text at the same time is one reminder"
    r2, _ = notify.add_reminder("2026-10-08 10:00", "загрузить ролик", root=root, now=NOW, environ=env)
    assert r2["id"] == "R2"
    assert [r["id"] for r in notify.pending_reminders(root, env)] == ["R1", "R2"]
    assert notify.rows(root, env) == [], "queuing sends nothing"
    notify.cancel_reminder("r2", root=root, now=NOW, environ=env)
    assert [r["id"] for r in notify.pending_reminders(root, env)] == ["R1"]
    try:
        notify.cancel_reminder("R2", root=root, environ=env)
        raise AssertionError("a cancelled one cannot be cancelled again")
    except ValueError as e:
        assert "cancelled" in str(e)
    r3, _ = notify.add_reminder("2026-10-08 10:00", "загрузить ролик", root=root, now=NOW, environ=env)
    assert r3["id"] == "R3", "ids are never reused"


def test_send_due_sends_what_has_come_once_and_leaves_the_rest():
    root, env = fresh()
    notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
    notify.add_reminder("2026-10-08 12:00", "второе", root=root, now=NOW, environ=env)
    fake = FakePost()
    with posting(fake):
        assert notify.send_due(root, "2026-10-07T15:29:00Z", env) == [], "not yet"
        got = notify.send_due(root, "2026-10-07T15:31:00Z", env)
        assert [(g["id"], g["status"]) for g in got] == [("R1", "sent")], got
        assert got[0]["backends"] == {"log": "ok", "telegram": "ok"}
        assert notify.send_due(root, "2026-10-07T16:00:00Z", env) == [], "sent once"
    assert len(fake.calls) == 1
    text = fake.form(0)["text"]
    assert text == "Напоминание\nпервое\nцентр → Уведомления: http://127.0.0.1:8790/notifications", text
    row = [r for r in notify.rows(root, env) if r["kind"] == "reminder"]
    assert len(row) == 1 and row[0]["key"] == "reminder:R1"
    assert row[0]["link"] == "http://127.0.0.1:8790/notifications"
    st = {r["id"]: r["status"] for r in notify.reminders(root, env)}
    assert st == {"R1": "sent", "R2": "pending"}, st


def test_a_reminder_the_bus_could_not_send_stays_pending():
    root, env = fresh("log")
    notify.add_reminder("18:30", "x", root=root, now=NOW, environ=env)
    old = notify.send
    notify.send = lambda *a, **k: {"status": "error", "key": "k", "backends": {}}
    try:
        got = notify.send_due(root, "2026-10-07T16:00:00Z", env)
    finally:
        notify.send = old
    assert got[0]["status"] == "failed" and got[0]["reason"].startswith("bus:"), got
    assert [r["id"] for r in notify.pending_reminders(root, env)] == ["R1"]
    assert notify.send_due(root, "2026-10-07T16:00:00Z", env)[0]["status"] == "sent"


# ------------------------------------------------------------------ CF-0617: not delivered is not sent

def _due(root, env, fake, now="2026-10-07T16:00:00Z"):
    err = io.StringIO()
    with posting(fake), contextlib.redirect_stderr(err):
        got = notify.send_due(root, now, env)
    assert TOKEN not in err.getvalue()
    return got, err.getvalue()


def _status(root, env):
    return {r["id"]: r for r in notify.reminders(root, env)}


def test_telegram_ok_is_sent():
    root, env = fresh()
    notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
    got, _ = _due(root, env, FakePost())
    assert [(g["id"], g["status"], g["attempt"]) for g in got] == [("R1", "sent", 1)], got
    r = _status(root, env)["R1"]
    assert r["status"] == "sent" and r["attempts"] == 1 and r["reason"] is None, r


def test_telegram_error_is_failed_with_its_reason_and_goes_again():
    root, env = fresh()
    notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
    got, err = _due(root, env, FakePost(reply=b'{"ok": false, "description": "Bad Request: chat not found"}'))
    assert [(g["id"], g["status"], g["attempt"]) for g in got] == [("R1", "failed", 1)], got
    assert "chat not found" in got[0]["reason"] and got[0]["reason"].startswith("telegram: error"), got
    r = _status(root, env)["R1"]
    assert r["status"] == "failed" and r["attempts"] == 1 and "chat not found" in r["reason"], r
    assert "not delivered (try 1 of" in err and "tried again next tick" in err, err
    assert [x["id"] for x in notify.pending_reminders(root, env)] == ["R1"], "still to go"
    raw = notify.reminders_path(root, env).read_text(encoding="utf-8")
    assert TOKEN not in raw and '"op": "failed"' in raw
    # the next tick: network down this time - still failed, the second try
    got, _ = _due(root, env, FakePost(fail=RuntimeError("network: [Errno 8] nodename nor servname")),
                  now="2026-10-07T16:15:00Z")
    assert [(g["status"], g["attempt"]) for g in got] == [("failed", 2)], got
    assert "network" in _status(root, env)["R1"]["reason"]


def test_a_retry_that_goes_through_is_sent_under_a_new_key():
    root, env = fresh()
    notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
    _due(root, env, FakePost(fail=RuntimeError("network: timed out")))
    fake = FakePost()
    got, _ = _due(root, env, fake, now="2026-10-07T16:15:00Z")
    assert [(g["status"], g["attempt"]) for g in got] == [("sent", 2)], got
    assert len(fake.calls) == 1 and fake.form(0)["text"].startswith("Напоминание\nпервое")
    r = _status(root, env)["R1"]
    assert r["status"] == "sent" and r["attempts"] == 2, r
    keys = [x["key"] for x in notify.rows(root, env) if x["kind"] == "reminder"]
    assert keys == ["reminder:R1", "reminder:R1#again:try2"], keys
    got, _ = _due(root, env, FakePost(), now="2026-10-07T16:30:00Z")
    assert got == [], "sent once"


def test_the_ceiling_makes_it_exhausted_and_no_more_tries():
    root, env = fresh()
    notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
    fake = FakePost(reply=b'{"ok": false, "description": "Bad Request: chat not found"}')
    seen = []
    for i in range(notify.REMINDER_MAX_ATTEMPTS):
        got, err = _due(root, env, fake, now=f"2026-10-07T{16 + i:02d}:00:00Z")
        seen.append(got[0]["status"])
    assert seen == ["failed"] * (notify.REMINDER_MAX_ATTEMPTS - 1) + ["exhausted"], seen
    assert "no more tries" in err
    r = _status(root, env)["R1"]
    assert r["status"] == "exhausted" and r["attempts"] == notify.REMINDER_MAX_ATTEMPTS, r
    assert notify.pending_reminders(root, env) == [] and [x["id"] for x in notify.unsent_reminders(root, env)] == ["R1"]
    got, _ = _due(root, env, fake, now="2026-10-08T12:00:00Z")
    assert got == [] and len(fake.calls) == notify.REMINDER_MAX_ATTEMPTS, "no try past the ceiling"
    code, out, _ = _cli(["remind", "--list", "--root", str(root)], env)
    assert "exhausted" in out and f"try {notify.REMINDER_MAX_ATTEMPTS} of" in out and "chat not found" in out, out
    notify.cancel_reminder("R1", root=root, environ=env)
    assert notify.unsent_reminders(root, env) == [], "cancel clears an exhausted one"


def test_no_outside_backend_is_sent():
    for backends, extra in (("log", None), ("log,telegram", {"NOTIFY_TELEGRAM_TOKEN": ""})):
        root, env = fresh(backends, extra)
        notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
        fake = FakePost()
        got, _ = _due(root, env, fake)
        assert [g["status"] for g in got] == ["sent"], (backends, got)
        assert fake.calls == [] and _status(root, env)["R1"]["status"] == "sent"


def test_delivery_rule():
    assert notify.delivery({"log": "ok"}) == (True, None)
    assert notify.delivery({"log": "ok", "telegram": "skipped: no NOTIFY_TELEGRAM_TOKEN in .env"})[0]
    assert notify.delivery({"telegram": "error: x", "ntfy": "ok"}) == (True, None), "one outside ok is enough"
    ok, why = notify.delivery({"log": "ok", "telegram": "error: RuntimeError: network: down"})
    assert not ok and why == "telegram: error: RuntimeError: network: down"


def test_a_duplicate_key_is_judged_by_its_journal_row():
    root, env = fresh()
    notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
    # a process sent try 1 (Telegram said no) and died before the queue's op
    _send(env, root, FakePost(fail=RuntimeError("network: down")), kind="reminder", key="reminder:R1")
    fake = FakePost()
    got, _ = _due(root, env, fake)
    assert [(g["status"], g["attempt"]) for g in got] == [("failed", 1)] and fake.calls == [], got
    got, _ = _due(root, env, fake, now="2026-10-07T16:15:00Z")
    assert [(g["status"], g["attempt"]) for g in got] == [("sent", 2)], got


def test_cli_due_says_failed_and_exits_1():
    root, env = fresh()
    notify.add_reminder("18:30", "первое", root=root, now=NOW, environ=env)
    with posting(FakePost(fail=RuntimeError("network: down"))):
        code, out, _ = _cli(["remind", "--due", "--root", str(root), "--now", "2026-10-07T18:00:00Z"], env)
    assert code == 1 and "failed: R1" in out and "try 1 of" in out and "reason: telegram: error" in out, out
    assert TOKEN not in out


def test_the_reminders_are_state_not_git():
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "/notify/" in ignore
    assert notify.reminders_path(None, environ={}) == ROOT / "notify" / "reminders.jsonl"


def test_cli_remind():
    root, env = fresh()
    base = ["--root", str(root), "--now", NOW]
    code, out, _ = _cli(["remind", "--at", "21:00 МСК", "позвонить", "в", "банк", *base], env)
    assert code == 0 and out.startswith("queued: R1 2026-10-07 21:00 МСК - позвонить в банк"), out
    code, out, _ = _cli(["remind", "--at", "21:00", *base], env)
    assert code == 2 and "needs the text" in out
    code, out, _ = _cli(["remind", "--at", "99:00", "x", *base], env)
    assert code == 2 and "error:" in out
    code, out, _ = _cli(["remind", "--list", *base], env)
    assert code == 0 and "R1" in out and "1 reminder(s) pending" in out, out
    fake = FakePost()
    with posting(fake):
        code, out, _ = _cli(["remind", "--due", "--root", str(root), "--now", "2026-10-07T18:00:00Z"], env)
        assert code == 0 and "sent: R1" in out and "telegram: ok" in out, out
        code, out, _ = _cli(["remind", "--due", "--root", str(root), "--now", "2026-10-07T18:05:00Z"], env)
        assert code == 0 and "nothing due" in out
    assert len(fake.calls) == 1
    code, out, _ = _cli(["remind", "--cancel", "R1", *base], env)
    assert code == 2 and "already sent" in out
    code, out, _ = _cli(["remind", "--list", "--all", *base], env)
    assert "sent" in out and "1 reminder(s) in" in out, out


def _state():
    """CC-0035: the factory's state (once the console's data, shared/factory_state.py)."""
    if str(ROOT / "shared") not in sys.path:
        sys.path.insert(0, str(ROOT / "shared"))
    import factory_state
    return factory_state


def test_the_factory_state_lists_the_pending_reminders_read_only():
    fs = _state()
    root, env = fresh("log")
    (root / "channels").mkdir()
    r0 = fs.collect(root, NOW, needs_you_dir=root / "NY", env_file=root / "none.env",
                    environ=env, open_rows=[])["reminders"]
    assert r0["ok"] and r0["pending"] == [], r0
    notify.add_reminder("18:30", "<b>забрать</b> посылку", root=root, now=NOW, environ=env)
    notify.add_reminder("2026-10-09 10:00", "второе", root=root, now=NOW, environ=env)
    notify.cancel_reminder("R2", root=root, environ=env)
    data = fs.collect(root, "2026-10-07T15:40:00Z", needs_you_dir=root / "NY",
                      env_file=root / "none.env", environ=env, open_rows=[])
    r = data["reminders"]
    assert r["ok"] and [x["id"] for x in r["pending"]] == ["R1"] and r["cancelled"] == 1, r
    assert r["pending"][0]["due_msk"] == "2026-10-07 18:30 МСК", r["pending"]
    assert r["pending"][0]["text"] == "<b>забрать</b> посылку", "the data keeps the text as it is"
    assert r["pending"][0]["overdue"] is True, "an overdue one waits for the tick"


def test_the_factory_state_shows_the_unsent_with_reason_and_tries():
    fs = _state()
    root, env = fresh()
    (root / "channels").mkdir()
    notify.add_reminder("18:30", "позвонить", root=root, now=NOW, environ=env)
    notify.add_reminder("18:40", "второе", root=root, now=NOW, environ=env)
    notify.add_reminder("2026-10-09 10:00", "потом", root=root, now=NOW, environ=env)
    fake = FakePost(reply=b'{"ok": false, "description": "Bad Request: chat not found"}')
    _due(root, env, fake, now="2026-10-07T15:35:00Z")                 # R1: try 1
    for i in range(notify.REMINDER_MAX_ATTEMPTS):                      # R2 to the ceiling, R1 too
        _due(root, env, fake, now=f"2026-10-07T{16 + i:02d}:00:00Z")
    notify.add_reminder("2026-10-08 10:00", "свежее", root=root, now=NOW, environ=env)
    data = fs.collect(root, "2026-10-08T00:00:00Z", needs_you_dir=root / "NY",
                      env_file=root / "none.env", environ=env, open_rows=[])
    r = data["reminders"]
    assert r["ok"] and r["max_attempts"] == notify.REMINDER_MAX_ATTEMPTS, r
    assert {x["id"]: x["status"] for x in r["unsent"]} == {"R1": "exhausted", "R2": "exhausted"}, r["unsent"]
    assert [x["id"] for x in r["pending"]] == ["R4", "R3"], "the unsent are not in the pending table"
    assert all(x["attempts"] == notify.REMINDER_MAX_ATTEMPTS for x in r["unsent"]), r["unsent"]
    assert all("chat not found" in (x["reason"] or "") for x in r["unsent"]), r["unsent"]
    assert TOKEN not in json.dumps(data, ensure_ascii=False, default=str)
    # one try short of the ceiling: failed, another try comes
    root, env = fresh()
    (root / "channels").mkdir()
    notify.add_reminder("18:30", "позвонить", root=root, now=NOW, environ=env)
    _due(root, env, FakePost(fail=RuntimeError("network: down")))
    data = fs.collect(root, "2026-10-07T16:05:00Z", needs_you_dir=root / "NY",
                      env_file=root / "none.env", environ=env, open_rows=[])
    r = data["reminders"]
    assert [(x["id"], x["status"], x["attempts"]) for x in r["unsent"]] == [("R1", "failed", 1)], r
    assert "network: down" in r["unsent"][0]["reason"] and r["pending"] == [], r


# ------------------------------------------------------------------ CF-0720: send_test, by/via, masking
CHAT_LONG = "-1009876543210"
NTFY = "https://ntfy.example.test/factory-secret-topic"
HOOK = "https://hooks.example.test/T000/B000/xyz"


def test_cf0720_send_test_records_by_via_and_returns_send_s_shape():
    root, env = fresh()
    fake = FakePost()
    err = io.StringIO()
    with posting(fake), contextlib.redirect_stderr(err):
        res = notify.send_test(root, by="user", via="center", environ=env)
    assert res["status"] == "sent" and res["key"].startswith("test:"), res
    assert res["backends"] == {"log": "ok", "telegram": "ok"}, res
    assert res["by"] == "user" and res["via"] == "center" and res["delivered"] is True
    assert res["delivery_reason"] is None and "пробное сообщение" in res["text"]
    (row,) = notify.rows(root, env)
    assert row["kind"] == "test" and row["by"] == "user" and row["via"] == "center", row
    assert len(fake.calls) == 1
    for bad in ({"by": ""}, {"via": "a\nb"}, {"by": "x" * 41}):
        try:
            notify.send_test(root, environ=env, **bad)
        except ValueError as e:
            assert "by=" in str(e) or "via=" in str(e)
        else:
            raise AssertionError(f"{bad} was taken")
    assert len(fake.calls) == 1 and len(notify.rows(root, env)) == 1


def test_cf0720_send_test_dry_run_sends_nothing_and_has_the_same_shape():
    root, env = fresh(backends="log,telegram,ntfy,pigeon")
    fake = FakePost()
    with posting(fake):
        dry = notify.send_test(root, by="user", via="center", environ=env, dry_run=True)
    assert fake.calls == [] and notify.rows(root, env) == []
    assert not (Path(env["NOTIFY_STATE_DIR"]) / "sent.jsonl").exists()
    assert dry["status"] == "dry_run" and dry["key"].startswith("test:"), dry
    assert dry["backends"] == {"log": notify.DRY_WOULD, "telegram": notify.DRY_WOULD,
                               "ntfy": "skipped: no NOTIFY_NTFY_URL in .env",
                               "pigeon": "skipped: unknown backend"}, dry["backends"]
    with posting(FakePost()):
        real = notify.send_test(root, by="user", via="center", environ=env)
    assert set(dry) == set(real), (sorted(dry), sorted(real))
    assert set(dry["backends"]) == set(real["backends"])
    assert real["backends"]["ntfy"] == dry["backends"]["ntfy"]
    assert real["backends"]["pigeon"] == dry["backends"]["pigeon"]


def test_cf0720_the_journal_never_holds_the_token_the_chat_id_or_the_addresses():
    root, env = fresh(backends="log,telegram,ntfy,webhook",
                      extra={"NOTIFY_TELEGRAM_CHAT": CHAT_LONG, "NOTIFY_NTFY_URL": NTFY,
                             "NOTIFY_WEBHOOK_URL": HOOK})
    secrets = (TOKEN, CHAT_LONG, NTFY, HOOK, TOKEN.split(":")[1])

    def leaky(url, data, headers):
        raise RuntimeError(f"failed {url} for chat {CHAT_LONG} via {NTFY} and {HOOK}")

    err = io.StringIO()
    with posting(leaky), contextlib.redirect_stderr(err):
        res = notify.send("run_done", f"k-{CHAT_LONG}", f"готово {CHAT_LONG} {HOOK}",
                          link=NTFY, root=root, environ=env, by="user", via="cli")
        notify.send_test(root, by="user", via="cli", environ=env)
    raw = (Path(env["NOTIFY_STATE_DIR"]) / "sent.jsonl").read_text()
    shown = raw + err.getvalue() + json.dumps(res, ensure_ascii=False)
    for v in secrets:
        assert v not in shown, (v, shown)
    assert "api.telegram.org/bot***" in raw or "api.telegram.org/bot" not in raw, raw
    rows = [json.loads(x) for x in raw.splitlines()]
    assert [r["kind"] for r in rows] == ["run_done", "test"]
    assert all(r["by"] == "user" and r["via"] == "cli" for r in rows), rows
    assert all(v.startswith("error:") for r in rows for k, v in r["backends"].items()
               if k != "log"), rows
    # a row written before the masking (raw secrets in it) reads masked
    with open(Path(env["NOTIFY_STATE_DIR"]) / "sent.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"at": "x", "kind": "run_done", "key": "old", "text": CHAT_LONG,
                             "link": f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                             "backends": {"telegram": f"error: {HOOK}"}}) + "\n")
    assert not any(v in json.dumps(notify.rows(root, env)) for v in secrets)
    # a Telegram bot URL whose token is not in the settings any more
    assert notify.mask_secrets("https://api.telegram.org/bot42:XYZ/sendMessage", {}) == \
        "https://api.telegram.org/bot***/sendMessage"


def test_cf0720_send_without_by_via_writes_the_row_as_before():
    root, env = fresh(backends="log")
    res, _ = _send(env, root, FakePost())
    (row,) = notify.rows(root, env)
    assert res["status"] == "sent" and "by" not in row and "via" not in row, row
    assert list(row) == ["at", "kind", "channel", "key", "text", "link", "task", "backends"], row
    res, _ = _send(env, root, FakePost(), key="k2", by=" ")
    assert res["status"] == "error" and "by=" in res["error"]
    assert len(notify.rows(root, env)) == 1


def test_cf0720_cli_test_send_takes_by_via():
    root, env = fresh()
    with posting(FakePost()):
        code, out, err = _cli(["test", "--send", "--by", "user", "--via", "cli", "--root",
                               str(root)], env)
        assert code == 0, out + err
        (row,) = notify.rows(root, env)
        assert row["by"] == "user" and row["via"] == "cli", row
        code, out, err = _cli(["test", "--send", "--by", "", "--root", str(root)], env)
    assert code == 2 and "by=" in out, out
    assert len(notify.rows(root, env)) == 1


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
