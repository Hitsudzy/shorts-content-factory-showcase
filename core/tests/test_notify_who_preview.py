#!/usr/bin/env python3
"""CF-0700: what the center (CC-0026, `api/notifications.py`) needs from the
bus - `by` / `via` on a reminder's add and cancel, and the dry check of the
backends as data (`notify.test_preview`).

No network, no live data: a tmp root, a made-up environment (`environ=`), the
real `_post` replaced by a stand-in that fails the test if it is ever called.

What is pinned:

* `add_reminder(via=)` puts `via` into the op `add` only when given;
  `reminders()` returns it (None for an add without it);
* `cancel_reminder(by=, via=)` puts them into the op `cancel` only when given;
  `reminders()` returns `cancelled_by` / `cancelled_via`;
* without by / via a row is byte for byte what it was before CF-0700, and a
  journal written before it reads as it did (the new keys None);
* a bad `by` / `via` (empty, not a string, a newline, over WHO_MAX) is a
  ValueError and nothing is written;
* `test_preview(root, environ)`: one dict per backend that is on - unknown,
  outside without its address (`skip_reason`), ready; nothing sent, nothing
  written; `notify.py test` prints exactly what the pre-CF-0700 code printed.
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

TMP = tmp_root("notify-who-test-")
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijklmnop"
CHAT = "-1001234"
NOW = "2026-10-07T15:00:00Z"
_n = [0]


def fresh(backends="log", extra=None):
    _n[0] += 1
    root = TMP / f"r{_n[0]}"
    root.mkdir()
    env = {"NOTIFY_STATE_DIR": str(root / "state"), "NOTIFY_BACKENDS": backends}
    env.update(extra or {})
    return root, env


@contextlib.contextmanager
def no_post():
    def boom(*a, **k):
        raise AssertionError("the preview must not send")
    old = notify._post
    notify._post = boom
    try:
        yield
    finally:
        notify._post = old


def ops(root, env):
    return [json.loads(ln) for ln in
            notify.reminders_path(root, env).read_text(encoding="utf-8").splitlines()]


def raw_lines(root, env):
    return notify.reminders_path(root, env).read_bytes().splitlines()


# ------------------------------------------------------------------ by / via
def test_add_writes_via_only_when_given_and_reminders_return_it():
    root, env = fresh()
    r1, new = notify.add_reminder("21:00", "из центра", root=root, now=NOW, environ=env,
                                  by="user", via="center")
    assert new and r1["by"] == "user" and r1["via"] == "center", r1
    r2, _ = notify.add_reminder("22:00", "из CLI", root=root, now=NOW, environ=env)
    assert r2["by"] == "user" and r2["via"] is None, r2
    o = ops(root, env)
    assert o[0]["via"] == "center" and list(o[0]) == ["op", "id", "due", "text", "by", "at",
                                                      "via", "task"], o[0]
    assert "via" not in o[1], o[1]
    got = {r["id"]: r for r in notify.reminders(root, env)}
    assert got["R1"]["via"] == "center" and got["R2"]["via"] is None


def test_cancel_writes_by_via_only_when_given_and_reminders_return_them():
    root, env = fresh()
    for t in ("09:00", "10:00", "11:00"):
        notify.add_reminder(t, f"в {t}", root=root, now=NOW, environ=env)
    c1 = notify.cancel_reminder("R1", root=root, now=NOW, environ=env, by="user", via="center")
    assert (c1["status"], c1["cancelled_by"], c1["cancelled_via"], c1["cancelled_at"]) == \
        ("cancelled", "user", "center", NOW), c1
    notify.cancel_reminder("R2", root=root, now=NOW, environ=env, by="user")
    notify.cancel_reminder("R3", root=root, now=NOW, environ=env)
    o = [x for x in ops(root, env) if x["op"] == "cancel"]
    assert (o[0]["by"], o[0]["via"]) == ("user", "center"), o[0]
    assert o[1]["by"] == "user" and "via" not in o[1], o[1]
    assert "by" not in o[2] and "via" not in o[2], o[2]
    got = {r["id"]: r for r in notify.reminders(root, env)}
    assert (got["R1"]["cancelled_by"], got["R1"]["cancelled_via"]) == ("user", "center")
    assert (got["R2"]["cancelled_by"], got["R2"]["cancelled_via"]) == ("user", None)
    assert (got["R3"]["cancelled_by"], got["R3"]["cancelled_via"]) == (None, None)
    assert all(r["status"] == "cancelled" for r in got.values())


def test_without_by_via_the_rows_are_byte_for_byte_as_before():
    root, env = fresh()
    notify.add_reminder("21:00", "проверить", root=root, now=NOW, environ=env)
    notify.cancel_reminder("R1", root=root, now=NOW, environ=env)
    old_add = {"op": "add", "id": "R1", "due": "2026-10-07T18:00:00Z", "text": "проверить",
               "by": "user", "at": NOW, "task": "CF-0606"}
    old_cancel = {"op": "cancel", "id": "R1", "at": NOW, "task": "CF-0606"}
    assert raw_lines(root, env) == [json.dumps(old_add, ensure_ascii=False).encode("utf-8"),
                                    json.dumps(old_cancel, ensure_ascii=False).encode("utf-8")]


def test_an_old_journal_reads_as_it_did():
    root, env = fresh()
    path = notify.reminders_path(root, env)
    path.parent.mkdir(parents=True)
    rows = [{"op": "add", "id": "R1", "due": "2026-10-08T07:00:00Z", "text": "старое",
             "by": "user", "at": NOW, "task": "CF-0606"},
            {"op": "add", "id": "R2", "due": "2026-10-08T08:00:00Z", "text": "снятое",
             "by": "user", "at": NOW, "task": "CF-0606"},
            {"op": "cancel", "id": "R2", "at": NOW, "task": "CF-0606"}]
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    got = notify.reminders(root, env)
    assert [(r["id"], r["status"], r["by"], r["via"], r["cancelled_by"], r["cancelled_via"])
            for r in got] == [("R1", "pending", "user", None, None, None),
                              ("R2", "cancelled", "user", None, None, None)], got
    assert got[1]["cancelled_at"] == NOW


def test_a_bad_by_or_via_is_refused_and_nothing_is_written():
    root, env = fresh()
    bad = ["", "   ", 7, "a\nb", "tab\there", "x" * (notify.WHO_MAX + 1)]
    for v in bad:
        for kw in ({"via": v}, {"by": v}):
            try:
                notify.add_reminder("21:00", "т", root=root, now=NOW, environ=env, **kw)
                raise AssertionError(f"add {kw!r} must be refused")
            except ValueError as e:
                assert list(kw)[0] in str(e), e
    assert not notify.reminders_path(root, env).exists(), "a refused add writes nothing"
    notify.add_reminder("21:00", "т", root=root, now=NOW, environ=env)
    before = notify.reminders_path(root, env).read_bytes()
    for v in bad:
        for kw in ({"via": v}, {"by": v}):
            try:
                notify.cancel_reminder("R1", root=root, now=NOW, environ=env, **kw)
                raise AssertionError(f"cancel {kw!r} must be refused")
            except ValueError as e:
                assert list(kw)[0] in str(e), e
    assert notify.reminders_path(root, env).read_bytes() == before
    assert notify.reminders(root, env)[0]["status"] == "pending"
    r = notify.cancel_reminder("R1", root=root, now=NOW, environ=env, by="  user ",
                               via="x" * notify.WHO_MAX)
    assert r["cancelled_by"] == "user" and r["cancelled_via"] == "x" * notify.WHO_MAX, r


# ------------------------------------------------------------------ test_preview
def test_preview_unknown_outside_without_address_and_ready():
    root, env = fresh("log,pigeon,ntfy,telegram",
                      extra={"NOTIFY_TELEGRAM_TOKEN": TOKEN, "NOTIFY_TELEGRAM_CHAT": CHAT})
    with no_post():
        got = notify.test_preview(root, env)
    assert [b["name"] for b in got] == ["log", "pigeon", "ntfy", "telegram"], got
    for b in got:
        assert set(b) == {"name", "known", "external", "ready", "skip_reason", "would_get"}, b
    log, pigeon, ntfy, tg = got
    assert (log["known"], log["external"], log["ready"], log["skip_reason"]) == \
        (True, False, True, None), log
    # CF-0925: the probe shows a message of the new look; the journal's line is one line
    assert log["would_get"].startswith("проверка уведомлений фабрики — так выглядит сообщение: "
                                       "· ✅ Reel: батч готов"), log
    assert " -> http" in log["would_get"] and "\n" not in log["would_get"], log
    assert (pigeon["known"], pigeon["ready"], pigeon["would_get"], pigeon["skip_reason"]) == \
        (False, False, None, notify.PREVIEW_UNKNOWN), pigeon
    assert (ntfy["known"], ntfy["external"], ntfy["ready"]) == (True, True, False), ntfy
    assert ntfy["skip_reason"] == "no NOTIFY_NTFY_URL in .env", ntfy
    assert (tg["known"], tg["external"], tg["ready"], tg["skip_reason"]) == \
        (True, True, True, None), tg
    assert "проверка уведомлений фабрики" in tg["would_get"] and "центр" in tg["would_get"], tg
    assert "\n✅ Reel: батч готов" in tg["would_get"] and "Фабрика ·" not in tg["would_get"], tg
    assert TOKEN not in json.dumps(got, ensure_ascii=False)
    assert not (root / "state").exists(), "the preview writes nothing"


def test_preview_telegram_missing_its_chat_and_the_default():
    root, env = fresh("telegram", extra={"NOTIFY_TELEGRAM_TOKEN": TOKEN})
    (tg,) = notify.test_preview(root, env)
    assert tg["ready"] is False and tg["skip_reason"] == "no NOTIFY_TELEGRAM_CHAT in .env", tg
    root, env = fresh("")
    assert [b["name"] for b in notify.test_preview(root, env)] == list(notify.DEFAULT_BACKENDS)


def test_preview_reads_the_roots_env_file_under_environ():
    root, env = fresh("log,webhook")
    (root / ".env").write_text("NOTIFY_WEBHOOK_URL=http://127.0.0.1:9/hook\n", encoding="utf-8")
    wh = notify.test_preview(root, env)[1]
    assert wh["name"] == "webhook" and wh["ready"] is True and wh["skip_reason"] is None, wh


def _old_cli_test(root, out):
    """The pre-CF-0700 body of `main()`'s `test` (without --send), frozen."""
    names = notify.enabled(root)
    cfg = notify.settings(root)
    print(f"journal: {notify.journal_path(root)}", file=out)
    print(f"backends on: {', '.join(names)} ({notify.BACKENDS_ENV}; default "
          f"{','.join(notify.DEFAULT_BACKENDS)})", file=out)
    # CF-0925: the probe's event is the new look (notify.PREVIEW_TEXT, its lines kept)
    ev = notify.make_event("run_done", "test", notify.PREVIEW_TEXT, multiline=True,
                           link=notify.link_of(None, None))
    for name in names:
        if name not in notify.BACKENDS:
            print(f"  {name}: unknown backend - ignored", file=out)
            continue
        note = ""
        if name in notify.EXTERNAL:
            try:
                notify._need(cfg, *{"ntfy": ("NOTIFY_NTFY_URL",),
                                    "telegram": ("NOTIFY_TELEGRAM_TOKEN", "NOTIFY_TELEGRAM_CHAT"),
                                    "webhook": ("NOTIFY_WEBHOOK_URL",)}[name])
                note = " - SENDS THE TEXT TO AN OUTSIDE SERVICE"
            except notify.Skip as e:
                note = f" - would be skipped ({e})"
        shown = (notify.telegram_text(ev, cfg) if name == "telegram"
                 else f"{ev['text']} -> {ev['link']}")
        print(f"  {name}: would get {shown!r}{note}", file=out)
    print("nothing sent (a stand-in backend; the journal is untouched)", file=out)


@contextlib.contextmanager
def environment(env):
    old = {k: os.environ.get(k) for k in env}
    os.environ.update(env)
    try:
        yield
    finally:
        for k, v in old.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_cli_test_prints_what_it_printed_before():
    cases = [("log,pigeon,ntfy,telegram,webhook,macos",
              {"NOTIFY_TELEGRAM_TOKEN": TOKEN, "NOTIFY_TELEGRAM_CHAT": CHAT, "NOTIFY_NTFY_URL": ""}),
             ("telegram", {"NOTIFY_TELEGRAM_TOKEN": TOKEN, "NOTIFY_TELEGRAM_CHAT": ""}),
             ("", {})]
    for backends, extra in cases:
        root, env = fresh(backends, extra)
        with environment(env), no_post():
            new, old = io.StringIO(), io.StringIO()
            code = notify.main(["test", "--root", str(root)], out=new)
            _old_cli_test(root, old)
        assert code == 0
        assert new.getvalue() == old.getvalue(), (new.getvalue(), old.getvalue())
        assert "nothing sent" in new.getvalue() and TOKEN not in new.getvalue()
        assert not (root / "state").exists()


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
