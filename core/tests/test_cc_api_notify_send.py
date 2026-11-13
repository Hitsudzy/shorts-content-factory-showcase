#!/usr/bin/env python3
"""CC-0109: a test message to every delivery channel that is on (`python3
shared/notify.py test --send`), plan -> confirm (`api/notify_send.py`):

    POST /api/notify/test-send/plan          the channels that are on, by name, and the
                                             factory's dry run - nothing sent
    POST /api/notify/test-send {confirm}     notify.send_test(by, via) once

In-process (the TestClient) against a stand-in factory root in a temp dir
(`tests/test_cc_api_notify.py` `start`: the journal in the root's `notify/`,
the settings its `.env`). **No message ever leaves**: the bus's `_post` and
`subprocess` and the socket's connect / name lookup are replaced by recorders
that refuse - a test that reached any of them fails on `hits`; the outside
backends that are on are stand-ins in the bus's own registry (`BACKENDS`) for
the block, except ntfy, which is left real and is skipped for want of its
address before it could post.

What is pinned:

* the contract: the two POSTs, `NotifyProblem` on the problems, the shapes;
  the module calls `send_test` with `dry_run=True` in the plan and without
  it only in `test_send`, `test_preview` only in `_channels`, never `send`,
  `send_due`, `_post`, `BACKENDS`, `main` nor a write of its own;
* the plan: the channels by name (no token, no chat id, no address anywhere),
  which send off this machine (`outside`), ntfy not ready with the setting it
  lacks; nothing sent, nothing written;
* the confirm: one event of kind `test` to every backend that is on, the
  journal row saying it came from the center (`by` / `via`); per channel `{via, ok, detail}` in the
  order sent (an outside one's error with the token, the chat id and the
  webhook's URL in it - masked), `delivered`, one row in the journal; the
  token spent;
* the channels changed since the plan is `check_changed`, nothing sent;
  every outside channel failing is `delivered: false` with its reason;
  only the default `log` on - `outside` empty and the note says so.
"""
import ast
import json
import os
import socket
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_notify import _restore, backends, files, jsonl, nf, post, start  # noqa: E402

from api import batches, notify_send                                           # noqa: E402

PLAN, CONFIRM = "/api/notify/test-send/plan", "/api/notify/test-send"
TOKEN = "tg-plain-secret-77"
CHAT = "123456789"
HOOK = "https://hooks.example/abcdef-hook-secret"
ENV = f"NOTIFY_TELEGRAM_TOKEN={TOKEN}\nNOTIFY_TELEGRAM_CHAT={CHAT}\nNOTIFY_WEBHOOK_URL={HOOK}\n"
ON = "log,telegram,webhook,ntfy"
SECRETS = (TOKEN, CHAT, HOOK, "abcdef-hook-secret")
FORBIDDEN = {"send", "send_due", "_post", "BACKENDS", "main", "write_text", "write_bytes", "open",
             "unlink", "rename", "rmtree", "mkdir", "subprocess", "add_reminder",
             "cancel_reminder"}

try:
    import pytest

    @pytest.fixture(autouse=True)
    def _bus_env():
        yield
        _restore()
except ImportError:                                     # run by hand without pytest
    pass


class Guard:
    """No message leaves: the bus's `_post` / `subprocess` and the socket
    refuse and write the attempt down (`hits` - asserted empty); `fakes`
    stand in for backends of the bus's registry for the block."""

    def __init__(self, **fakes):
        self.fakes = fakes

    def __enter__(self):
        m = nf()
        self.hits, self.saved_reg = [], {k: m.BACKENDS.get(k) for k in self.fakes}
        self.saved = (m._post, m.subprocess, socket.socket.connect, socket.socket.connect_ex,
                      socket.getaddrinfo, socket.create_connection)

        def refuse(*a, **k):
            self.hits.append(repr(a)[:200])
            raise OSError("the test send reached the network")
        m._post = refuse
        m.subprocess = types.SimpleNamespace(run=refuse, Popen=refuse)
        socket.socket.connect = socket.socket.connect_ex = refuse
        socket.getaddrinfo = socket.create_connection = refuse
        m.BACKENDS.update(self.fakes)
        return self

    def __exit__(self, *exc):
        m = nf()
        (m._post, m.subprocess, socket.socket.connect, socket.socket.connect_ex,
         socket.getaddrinfo, socket.create_connection) = self.saved
        for k, v in self.saved_reg.items():
            if v is None:
                m.BACKENDS.pop(k, None)
            else:
                m.BACKENDS[k] = v


class Took:
    """A stand-in backend: keeps every event, says ok - or raises `fail`."""

    def __init__(self, fail=None):
        self.events, self.fail = [], fail

    def __call__(self, ev, cfg):
        self.events.append(dict(ev))
        if self.fail:
            raise RuntimeError(self.fail)


def no_secret(doc):
    text = json.dumps(doc, ensure_ascii=False)
    for s in SECRETS:
        assert s not in text, (s, text)


def sent_rows(root):
    p = root / "notify" / "sent.jsonl"
    return jsonl(p) if p.is_file() else []


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_two_posts():
    root, c = start(ENV)
    spec = c.get("/api/openapi.json").json()
    for path in (PLAN, CONFIRM):
        assert set(spec["paths"][path]) == {"post"}, spec["paths"][path]
        ref = spec["paths"][path]["post"]["responses"]["422"]["content"]["application/json"]
        assert ref["schema"]["$ref"].endswith("/NotifyProblem"), ref
    sch = spec["components"]["schemas"]
    assert {"action", "ok", "channels", "names", "outside", "text", "by", "via", "fingerprint",
            "confirm", "expires_in_s"} <= set(sch["NotifyTestSendPlan"]["properties"])
    assert set(sch["NotifyTestChannel"]["properties"]) == \
        {"name", "known", "external", "ready", "skip_reason"}
    assert {"sent", "key", "results", "delivered", "delivery_reason", "by", "via"} <= \
        set(sch["NotifyTestSendResult"]["properties"])
    assert set(sch["NotifyTestSendRow"]["properties"]) == {"via", "ok", "detail"}


def test_the_module_sends_only_in_the_confirm():
    tree = ast.parse((ROOT / "api" / "notify_send.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & FORBIDDEN, names & FORBIDDEN
    where, real = {}, set()
    for node in tree.body:
        for n in ast.walk(node):
            if isinstance(n, ast.Attribute) and n.attr in ("send_test", "test_preview"):
                where.setdefault(n.attr, set()).add(getattr(node, "name", None))
            if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "send_test":
                dry = [k for k in n.keywords if k.arg == "dry_run"]
                if not (dry and isinstance(dry[0].value, ast.Constant) and dry[0].value.value is True):
                    real.add(getattr(node, "name", None))
    assert where == {"send_test": {"test_send_plan", "test_send"},
                     "test_preview": {"_channels"}}, where
    assert real == {"test_send"}, real


# --------------------------------------------------------------------- the plan
def test_the_plan_names_the_channels_nothing_sent():
    root, c = start(ENV)
    before = files(root)
    tg, wh = Took(), Took()
    with Guard(telegram=tg, webhook=wh) as g, backends(ON):
        s, d = post(c, PLAN, {})
    assert s == 200, d
    assert d["names"] == ["log", "telegram", "webhook", "ntfy"], d
    assert d["outside"] == ["telegram", "webhook"] and d["note"] is None, d
    ch = {x["name"]: x for x in d["channels"]}
    assert all(set(x) == {"name", "known", "external", "ready", "skip_reason"}
               for x in d["channels"]), d["channels"]
    assert (ch["ntfy"]["ready"], ch["ntfy"]["external"]) == (False, True), ch["ntfy"]
    assert "NOTIFY_NTFY_URL" in ch["ntfy"]["skip_reason"], ch["ntfy"]
    assert (ch["log"]["external"], ch["log"]["ready"]) == (False, True), ch["log"]
    assert d["text"].startswith("пробное сообщение фабрики (") and \
        d["text"].endswith("уведомления доходят") and (d["by"], d["via"]) == ("user", "center"), d
    would = {x["via"]: x for x in d["would"]}
    assert [x["via"] for x in d["would"]] == ["log", "telegram", "webhook", "ntfy"], d["would"]
    assert would["telegram"]["ok"] and would["telegram"]["detail"] == "would send", would
    assert not would["ntfy"]["ok"] and would["ntfy"]["detail"].startswith("skipped: "), would
    assert d["would_deliver"] is True, d
    assert d["confirm"] and d["expires_in_s"] == 120, d
    no_secret(d)
    assert g.hits == [] and tg.events == [] and wh.events == []
    assert files(root) == before


# --------------------------------------------------------------------- the confirm
def test_the_confirm_sends_once_per_channel_masked():
    root, c = start(ENV)
    tg = Took()
    wh = Took(fail=f"HTTP 500: {HOOK} said no to bot{TOKEN} for chat {CHAT}")
    with Guard(telegram=tg, webhook=wh) as g, backends(ON):
        s, plan = post(c, PLAN, {})
        assert s == 200, plan
        s, d = post(c, CONFIRM, {"confirm": plan["confirm"]})
        assert s == 200, d
        s2, again = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert g.hits == [], g.hits
    assert len(tg.events) == 1 and len(wh.events) == 1, (tg.events, wh.events)
    ev = tg.events[0]
    assert ev["kind"] == "test" and ev["key"].startswith("test:"), ev
    assert ev["text"].startswith("пробное сообщение фабрики (") and \
        ev["text"].endswith("уведомления доходят"), ev
    assert d["sent"] is True and d["key"] == ev["key"] and (d["by"], d["via"]) == \
        ("user", "center"), d
    assert [r["via"] for r in d["results"]] == ["log", "telegram", "webhook", "ntfy"], d
    got = {r["via"]: r for r in d["results"]}
    assert (got["log"]["ok"], got["log"]["detail"]) == (True, "ok"), got
    assert (got["telegram"]["ok"], got["telegram"]["detail"]) == (True, "ok"), got
    assert got["webhook"]["ok"] is False and got["webhook"]["detail"].startswith("error: "), got
    assert "***" in got["webhook"]["detail"], got["webhook"]
    assert got["ntfy"]["ok"] is False and got["ntfy"]["detail"].startswith("skipped: "), got
    assert d["delivered"] is True and d["delivery_reason"] is None, d
    no_secret(d)
    rows = sent_rows(root)
    assert [r["key"] for r in rows] == [d["key"]] and rows[0]["kind"] == "test", rows
    assert (rows[0]["by"], rows[0]["via"]) == ("user", "center") and d["recorded_by"], rows
    assert d["at"] == rows[0]["at"], d
    assert s2 == 409 and again["code"] == "confirm_unknown", again


def test_the_channels_changed_since_the_plan_is_check_changed():
    root, c = start(ENV)
    tg = Took()
    with Guard(telegram=tg) as g:
        with backends("log,telegram"):
            s, plan = post(c, PLAN, {})
            assert s == 200, plan
        with backends("log"):
            s, d = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 409 and d["code"] == "check_changed", d
    assert set(d) == {"message", "code", "details"}, d
    assert g.hits == [] and tg.events == []
    assert sent_rows(root) == []


def test_every_outside_channel_failing_is_not_delivered():
    root, c = start(ENV)
    tg = Took(fail=f"Telegram: chat {CHAT} not found (bot{TOKEN})")
    with Guard(telegram=tg) as g, backends("log,telegram"):
        s, plan = post(c, PLAN, {})
        s, d = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 200, d
    assert g.hits == [] and len(tg.events) == 1
    assert d["delivered"] is False and d["delivery_reason"].startswith("telegram: error"), d
    no_secret(d)


def test_only_the_default_log_says_no_outside_channel():
    root, c = start(env=None)
    with Guard() as g:
        os.environ.pop("NOTIFY_BACKENDS", None)
        s, plan = post(c, PLAN, {})
        assert s == 200 and plan["names"] == ["log"] and plan["outside"] == [], plan
        assert plan["note"], plan
        s, d = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 200 and d["results"] == [{"via": "log", "ok": True, "detail": "ok"}], d
    assert d["delivered"] is True, d
    assert g.hits == []


def test_the_action_is_on_the_confirm_store():
    assert notify_send.ACTION in batches._ACTIONS


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
        finally:
            _restore()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
