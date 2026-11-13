#!/usr/bin/env python3
"""CF-0684: the queue of the user's requests to the operator (shared/operator_requests.py).

Everything in a temp directory; the bus is a stand-in (a recorder, or the real
bus with its state in the temp dir and Telegram's POST replaced) - nothing
leaves the machine, nothing of the live queue is read.

Pinned:
* open -> taken -> answered -> closed, cancel from open and taken; every other
  step refused with its code and a Russian line, nothing written;
* `next` takes the oldest open one, and None when none is open;
* concurrent `add`s (separate processes) lose nothing: unique ids, whole lines;
* an answer goes to the bus as `request_answer`; a Telegram that refuses is
  the request's `notify.status == "failed"` with the reason (no token), and
  `resend` tries again under a new key;
* the CLI: add / list / next / answer / close / cancel / resend, exit codes;
* the journal is gitignored and lives in <root>/requests by default.
"""
import contextlib
import importlib.util
import io
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(ROOT / "shared"))

import notify                        # noqa: E402

from _tmproot import tmp_root        # noqa: E402

# By path, under a name of its own (the way the center's API may load it too).
_spec = importlib.util.spec_from_file_location("factory_operator_requests",
                                               ROOT / "shared" / "operator_requests.py")
rq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rq)

TMP = tmp_root("requests-test-")
TOKEN = "123456789:AAFakeTokenForTestsOnly_abcdefghijklmnop"
_n = [0]


def fresh():
    _n[0] += 1
    d = TMP / f"r{_n[0]}"
    d.mkdir()
    return d


def bus_env(d, backends="log,telegram"):
    return {"NOTIFY_STATE_DIR": str(d / "notify"), "NOTIFY_BACKENDS": backends,
            "NOTIFY_TELEGRAM_TOKEN": TOKEN, "NOTIFY_TELEGRAM_CHAT": "-1001"}


class FakePost:
    def __init__(self, fail=None, reply=b'{"ok": true, "result": {}}'):
        self.calls, self.fail, self.reply = [], fail, reply

    def __call__(self, url, data, headers):
        self.calls.append((url, data, headers))
        if self.fail:
            raise self.fail
        return self.reply


@contextlib.contextmanager
def posting(fake):
    old = notify._post
    notify._post = fake
    err = io.StringIO()
    try:
        with contextlib.redirect_stderr(err):
            yield err
    finally:
        notify._post = old


def ok_notifier(sent):
    def fn(r, key):
        sent.append((r, key))
        return {"status": "sent", "key": key, "backends": {"log": "ok", "telegram": "ok"}}
    return fn


def refused(fn, code):
    try:
        fn()
    except rq.RequestError as e:
        assert e.code == code, (e.code, code)
        assert e.text_ru and e.as_dict() == {"code": code, "text_ru": e.text_ru, "text": str(e)}
        return e
    raise AssertionError(f"not refused, wanted {code}")


def ops_of(d):
    return [json.loads(ln) for ln in (d / rq.JOURNAL).read_text(encoding="utf-8").splitlines()]


# ------------------------------------------------------------------ the steps
def test_the_whole_way_and_the_fields():
    d, sent = fresh(), []
    r = rq.add("Переделай ролик про Каиджуру:\nкадр мутный", "user", channel="example-reel",
               context={"video": "kaijura-x", "batch": "1722Z"}, directory=d,
               now="2026-10-11T10:00:00Z")
    assert r["id"] == "R1" and r["n"] == 1 and r["status"] == "open"
    assert r["text"] == "Переделай ролик про Каиджуру:\nкадр мутный", "lines are kept"
    assert r["context"] == {"video": "kaijura-x", "batch": "1722Z"}
    assert r["created_by"] == "user" and r["created"] == "2026-10-11T10:00:00Z"
    t = rq.next("op-session-1", directory=d, now="2026-10-11T10:05:00Z")
    assert t["id"] == "R1" and t["status"] == "taken" and t["taken_by"] == "op-session-1"
    a = rq.answer("r1", "Пересобрал, кадр заменён", "op-session-1", directory=d,
                  now="2026-10-11T10:30:00Z", notifier=ok_notifier(sent))
    assert a["status"] == "answered" and a["answer"] == "Пересобрал, кадр заменён"
    assert a["answered_by"] == "op-session-1" and a["answered_at"] == "2026-10-11T10:30:00Z"
    assert a["notify"]["status"] == "sent" and a["notify"]["attempt"] == 1
    assert a["notify"]["key"] == "request:R1:answer" and len(sent) == 1
    c = rq.close("R1", "user", directory=d, now="2026-10-11T11:00:00Z")
    assert c["status"] == "closed" and c["closed_by"] == "user" and c["answer"]
    assert [o["op"] for o in ops_of(d)] == ["add", "take", "answer", "notify", "close"]
    assert all(o["task"] == "CF-0684" for o in ops_of(d))
    assert rq.get("R1", directory=d)["status"] == "closed"
    assert [r["status"] for r in rq.list(directory=d)] == ["closed"]


def test_cancel_from_open_and_from_taken():
    d = fresh()
    rq.add("a", "user", directory=d)
    rq.add("b", "user", directory=d)
    assert rq.cancel("R1", "user", directory=d)["status"] == "cancelled"
    assert rq.next("op", directory=d)["id"] == "R2"
    c = rq.cancel("R2", "center", directory=d)
    assert c["status"] == "cancelled" and c["cancelled_by"] == "center"


def test_refused_steps_have_codes_and_write_nothing():
    d, sent = fresh(), []
    rq.add("a", "user", directory=d)
    before = len(ops_of(d))
    refused(lambda: rq.answer("R1", "x", "op", directory=d, notifier=ok_notifier(sent)),
            "not_taken")
    refused(lambda: rq.close("R1", "user", directory=d), "not_answered")
    refused(lambda: rq.resend("R1", directory=d), "no_answer")
    rq.next("op", directory=d)
    refused(lambda: rq.close("R1", "user", directory=d), "not_answered")
    rq.answer("R1", "готово", "op", directory=d, notifier=ok_notifier(sent))
    refused(lambda: rq.answer("R1", "ещё", "op", directory=d, notifier=ok_notifier(sent)),
            "already_answered")
    refused(lambda: rq.cancel("R1", "user", directory=d), "cancel_answered")
    refused(lambda: rq.resend("R1", directory=d), "already_delivered")
    rq.close("R1", "user", directory=d)
    for fn, code in ((lambda: rq.close("R1", "user", directory=d), "already_closed"),
                     (lambda: rq.cancel("R1", "user", directory=d), "already_closed"),
                     (lambda: rq.answer("R1", "x", "op", directory=d), "already_closed")):
        refused(fn, code)
    rq.add("b", "user", directory=d)
    rq.cancel("R2", "user", directory=d)
    for fn in (lambda: rq.cancel("R2", "user", directory=d),
               lambda: rq.close("R2", "user", directory=d),
               lambda: rq.answer("R2", "x", "op", directory=d)):
        refused(fn, "already_cancelled")
    e = refused(lambda: rq.close("R9", "user", directory=d), "not_found")
    assert "R9" in e.text_ru
    refused(lambda: rq.add("   \n ", "user", directory=d), "text_empty")
    refused(lambda: rq.add("x" * (rq.TEXT_MAX + 1), "user", directory=d), "text_too_long")
    refused(lambda: rq.add("x", "  ", directory=d), "by_missing")
    refused(lambda: rq.add("x", "user", context={"a": {1, 2}}, directory=d), "context_invalid")
    refused(lambda: rq.add("x", "user", context="y" * (rq.CONTEXT_MAX + 1), directory=d),
            "context_invalid")
    refused(lambda: rq.list("bogus", directory=d), "status_unknown")
    ops = [o["op"] for o in ops_of(d)]
    assert ops == ["add", "take", "answer", "notify", "close", "add", "cancel"], ops
    assert before == 1 and len(sent) == 1, "a refused answer sends nothing"


def test_every_code_has_a_russian_line():
    for code, line in rq.REFUSALS_RU.items():
        assert line and any("а" <= ch <= "я" for ch in line.lower()), code
    try:
        rq.RequestError("x", code="no-such-code")
    except KeyError:
        pass
    else:
        raise AssertionError("a code with no Russian line is a KeyError at the raise")


def test_a_journal_written_by_hand_cannot_skip_a_step():
    d = fresh()
    d.mkdir(exist_ok=True)
    lines = [{"op": "add", "id": "R1", "text": "a", "by": "user", "at": "t1"},
             {"op": "close", "id": "R1", "by": "user", "at": "t2"},
             {"op": "answer", "id": "R7", "answer": "?", "by": "op", "at": "t3"},
             "not json"]
    (d / rq.JOURNAL).write_text("\n".join(x if isinstance(x, str) else json.dumps(x)
                                          for x in lines) + "\n", encoding="utf-8")
    assert [(r["id"], r["status"]) for r in rq.list(directory=d)] == [("R1", "open")]


# ------------------------------------------------------------------ next
def test_next_takes_the_oldest_open_and_none_when_none():
    d = fresh()
    assert rq.next("op", directory=d) is None
    for t in ("первая", "вторая", "третья"):
        rq.add(t, "user", directory=d)
    rq.cancel("R1", "user", directory=d)
    assert rq.next("op", directory=d)["text"] == "вторая"
    assert rq.next("op2", directory=d)["text"] == "третья"
    assert rq.next("op", directory=d) is None
    assert [r["id"] for r in rq.list("taken", directory=d)] == ["R2", "R3"]
    assert [r["id"] for r in rq.list("live", directory=d)] == ["R2", "R3"]
    assert [r["id"] for r in rq.list(("cancelled", "taken"), directory=d)] == ["R1", "R2", "R3"]


def test_concurrent_adds_and_nexts_lose_nothing():
    d = fresh()
    code = ("import importlib.util, sys\n"
            f"s = importlib.util.spec_from_file_location('m', {str(ROOT / 'shared' / 'operator_requests.py')!r})\n"
            "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
            "for k in range(15):\n"
            f"    m.add(f'p{{sys.argv[1]}}-{{k}}', 'user', directory={str(d)!r})\n")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(i)]) for i in range(4)]
    assert all(p.wait(timeout=120) == 0 for p in procs)
    rs = rq.list(directory=d)
    assert len(rs) == 60 and len({r["id"] for r in rs}) == 60
    assert sorted(r["n"] for r in rs) == list(range(1, 61))
    assert {r["text"] for r in rs} == {f"p{i}-{k}" for i in range(4) for k in range(15)}
    taker = ("import importlib.util, sys, json\n"
             f"s = importlib.util.spec_from_file_location('m', {str(ROOT / 'shared' / 'operator_requests.py')!r})\n"
             "m = importlib.util.module_from_spec(s); s.loader.exec_module(m)\n"
             "got = []\n"
             "while True:\n"
             f"    r = m.next(sys.argv[1], directory={str(d)!r})\n"
             "    if r is None: break\n"
             "    got.append(r['id'])\n"
             "print(json.dumps(got))\n")
    procs = [subprocess.Popen([sys.executable, "-c", taker, f"op{i}"], stdout=subprocess.PIPE,
                              text=True) for i in range(3)]
    taken = [i for p in procs for i in json.loads(p.communicate(timeout=120)[0])]
    assert sorted(taken, key=lambda x: int(x[1:])) == [f"R{i}" for i in range(1, 61)], \
        "every request taken once, by one operator"
    for ln in (d / rq.JOURNAL).read_text(encoding="utf-8").splitlines():
        json.loads(ln)


# ------------------------------------------------------------------ Telegram
def test_the_answer_goes_to_the_bus_and_telegram():
    d = fresh()
    env = bus_env(d)
    rq.add("Почему ролик про Дельвера не вышел?", "user", channel="example-reel", directory=d)
    rq.next("op", directory=d)
    with posting(FakePost()) as _err:
        fake = notify._post
        r = rq.answer("R1", "Держит проверка, выйдет завтра", "op", directory=d,
                      environ=env)
    assert r["notify"]["status"] == "sent" and r["notify"]["reason"] is None
    assert r["notify"]["backends"] == {"log": "ok", "telegram": "ok"}
    assert len(fake.calls) == 1
    from urllib.parse import parse_qs
    form = {k: v[0] for k, v in parse_qs(fake.calls[0][1].decode()).items()}
    assert form["text"].startswith("Ответ на просьбу · example-reel\n"), form["text"]
    assert "R1 «Почему ролик про Дельвера не вышел?» - Держит проверка" in form["text"]
    row = notify.rows(environ=env)[-1]
    assert row["kind"] == "request_answer" and row["key"] == "request:R1:answer"


def test_a_long_answer_is_not_cut_at_the_gate_line_length():
    d = fresh()
    env = bus_env(d, backends="log")
    rq.add("q", "user", directory=d)
    rq.next("op", directory=d)
    long = "слово " * 120
    with posting(FakePost()):
        rq.answer("R1", long, "op", directory=d, environ=env)
    assert len(notify.rows(environ=env)[-1]["text"]) > notify.TEXT_MAX


def test_a_failed_telegram_is_seen_in_the_request_and_resend_tries_again():
    d = fresh()
    env = bus_env(d)
    rq.add("q", "user", directory=d)
    rq.next("op", directory=d)
    with posting(FakePost(fail=RuntimeError(f"<urlopen error bot{TOKEN}: timed out>"))) as err:
        r = rq.answer("R1", "ответ", "op", directory=d, environ=env)
    assert r["status"] == "answered", "a failed send never undoes the answer"
    n = r["notify"]
    assert n["status"] == "failed" and n["attempt"] == 1 and "telegram" in n["reason"]
    assert "timed out" in n["reason"]
    assert "НЕ ДОШЁЛ" in rq.line_of(r) and "resend R1" in err.getvalue()
    for text in ((d / rq.JOURNAL).read_text(encoding="utf-8"), err.getvalue(),
                 (d / "notify" / "sent.jsonl").read_text(encoding="utf-8")):
        assert TOKEN not in text and TOKEN.split(":")[1] not in text
    with posting(FakePost(reply=b'{"ok": false, "description": "Forbidden"}')):
        r = rq.resend("R1", directory=d, environ=env)
    assert r["notify"]["status"] == "failed" and r["notify"]["attempt"] == 2
    assert "Forbidden" in r["notify"]["reason"]
    assert r["notify"]["key"] == "request:R1:answer#again:try2"
    with posting(FakePost()):
        r = rq.resend("R1", directory=d, environ=env)
    assert r["notify"]["status"] == "sent" and r["notify"]["attempt"] == 3
    refused(lambda: rq.resend("R1", directory=d, environ=env), "already_delivered")
    assert [o["status"] for o in ops_of(d) if o["op"] == "notify"] == ["failed", "failed", "sent"]


def test_a_bus_that_raises_is_a_failed_notify_not_a_lost_answer():
    d = fresh()
    rq.add("q", "user", directory=d)
    rq.next("op", directory=d)

    def boom(r, key):
        raise OSError("disk full")
    with contextlib.redirect_stderr(io.StringIO()):
        r = rq.answer("R1", "ответ", "op", directory=d, notifier=boom)
    assert r["status"] == "answered" and r["notify"]["status"] == "failed"
    assert "disk full" in r["notify"]["reason"]


# ------------------------------------------------------------------ the CLI
def cli(*argv):
    out = io.StringIO()
    with contextlib.redirect_stderr(io.StringIO()):
        code = rq.main(list(argv), out=out)
    return code, out.getvalue()


def test_cli():
    d = fresh()
    dd = ["--root", str(d)]
    code, out = cli("add", "переделай, потому что мутно", "--channel", "example-reel", *dd)
    assert code == 0 and out.startswith("R1 open") and "[example-reel]" in out
    code, out = cli("list", "--json", *dd)
    assert code == 0 and [r["id"] for r in json.loads(out)] == ["R1"]
    assert cli("close", "R1", *dd) == (1, "отказ [not_answered]: " +
                                       rq.REFUSALS_RU["not_answered"].format(id="R1") + "\n")
    code, out = cli("close", "R1", "--json", *dd)
    assert code == 1 and json.loads(out)["refused"]["code"] == "not_answered"
    code, out = cli("next", "--by", "op", "--json", *dd)
    assert code == 0 and json.loads(out)["status"] == "taken"
    assert cli("next", *dd) == (1, "открытых просьб нет\n")
    assert cli("next", "--json", *dd) == (1, "null\n")
    code, out = cli("answer", "R1", "сделано", *dd)
    assert code == 0 and "R1 answered" in out and "сделано" in out
    code, out = cli("list", "--status", "answered", *dd)
    assert code == 0 and out.count("\n") == 1
    assert cli("close", "R1", *dd)[0] == 0
    code, out = cli("add", "вторая", *dd)
    assert cli("cancel", "R2", *dd)[0] == 0
    assert cli("list", "--status", "open", *dd) == (0, "просьб нет\n")
    assert cli("add", "  ", *dd)[0] == 2
    assert cli("list", "--status", "bogus", *dd)[0] == 2
    assert cli("nonsense", *dd)[0] == 2
    assert cli("resend", "R2", *dd)[0] == 1


def test_cli_as_a_script_and_the_root_option():
    d = fresh()
    env = dict(bus_env(d, backends="log"), PATH="/usr/bin:/bin")
    env.pop("NOTIFY_TELEGRAM_TOKEN")
    p = subprocess.run([sys.executable, str(ROOT / "shared" / "operator_requests.py"), "add", "проверка",
                        "--root", str(d)], capture_output=True, text=True, env=env, timeout=60)
    assert p.returncode == 0 and p.stdout.startswith("R1 open"), p.stdout + p.stderr
    assert (d / "requests" / rq.JOURNAL).is_file()


def test_no_module_shadows_the_http_library():
    assert not (ROOT / "shared" / "requests.py").exists(), \
        "shared/requests.py would shadow the HTTP library `requests`"


def test_the_journal_is_state_gitignored_in_the_root():
    assert "/requests/" in (ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert rq.journal_dir(environ={}) == ROOT / "requests"
    assert rq.journal_dir(environ={"REQUESTS_DIR": "/x/y"}) == Path("/x/y")
    assert rq.journal_dir(root="/r", environ={"REQUESTS_DIR": "/x/y"}) == Path("/r/requests")
    assert rq.journal_dir(root="/r", directory="/d") == Path("/d")
    assert rq.journal_path(root="/r") == Path("/r/requests/requests.jsonl")


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
