#!/usr/bin/env python3
"""CC-0026: the notifications and the user's reminders in the command center's
API (`api/notifications.py`; `GET /api/notify/journal`, `/notify/reminders`,
`/notify/check`, `POST /api/notify/reminders/plan {at, text}`,
`/notify/reminders {confirm}`; CC-0081 `POST /api/notify/reminders/{rid}/cancel/plan`,
`/notify/reminders/{rid}/cancel {confirm}`) over the factory's `shared/notify.py`
- rows, reminders, the CLI's dry `test` and test_preview, parse_when, one_line,
add_reminder(by, via), cancel_reminder(by, via).

In-process (starlette's TestClient) against a stand-in factory root in a temp
dir (`tests/test_cc_api_batches.py` `factory_tree`, a git repo on main - the
working factory). **Nothing outside the temp dir is read or written**: the
journal and the queue are the temp root's `notify/` (the
runner's NOTIFY_STATE_DIR moved into each test's root, NOTIFY_BACKENDS set only
for the check's block), the settings its `.env`; the clock is fixed
(`notifications.FACTORY_KW`); no network - the bus's `_post` and
`subprocess.run` are replaced by ones that fail the test if reached.

What is pinned:

* the contract: the three GETs and the four POSTs, version 0.48.0,
  `NotifyProblem` on the problems, the plans' and the results' shapes; the
  module never names the bus's senders (`send`, `send_due`, `--send`), calls
  `parse_when` only in its plan, `add_reminder` only in the add's confirm,
  `cancel_reminder` only in the cancel's confirm, `test_preview` only in the
  check;
* the journal as stored, newest last, by kind / channel / limit; a bad kind
  422; the Telegram bot token masked wherever it would show;
* the reminders: the ones still to go (every one with `all`), with Moscow
  time, `via` / `cancelled_by` / `cancelled_via` (None on the old rows); a
  token in a stored text masked;
* the check: the backends on, `test_preview` per backend (known, external,
  ready, skip_reason, would_get), the CLI's lines (Telegram would get the line,
  an outside service is said, ntfy would be skipped for want of its address),
  no token in them (a planted one masked), nothing sent, nothing written;
* the plan writes nothing (due in UTC and Moscow, the text as queued); the
  confirm queues by `user` via `center`; the same reminder again is
  `created: false`;
* the cancel: the plan writes nothing (the reminder, its state, what a cancel
  means); the confirm cancels by `user` via `center`; refusals - no such
  reminder (404), one already sent or cancelled, one that changed since the
  plan (a failed try), a token of another reminder or of the add (409) -
  nothing written;
* refusals: a bad / past time, an empty text (422), a time that rolled since
  the plan (`check_changed`), a spent, expired or foreign token - nothing
  written.
"""
import ast
import json
import os
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT, ROOT / "tests"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from test_cc_api_batches import BASE, _w, client, factory_tree      # noqa: E402

import api                                                          # noqa: E402
from api import batches, factory, notifications                     # noqa: E402
from api.app import SESSION_HEADER                                  # noqa: E402

H = {"Origin": BASE, SESSION_HEADER: "tok"}
NOW = "2026-10-11T12:00:00Z"                  # 15:00 МСК
TOKEN = "tg-plain-secret-77"                  # nothing but mask_token would catch this one
ENV = f"NOTIFY_TELEGRAM_TOKEN={TOKEN}\nNOTIFY_TELEGRAM_CHAT=42\n"
GETS = {"/api/notify/journal", "/api/notify/reminders", "/api/notify/check"}
PLAN, CONFIRM = "/api/notify/reminders/plan", "/api/notify/reminders"


def cplan(rid):
    return f"/api/notify/reminders/{rid}/cancel/plan"


def cconfirm(rid):
    return f"/api/notify/reminders/{rid}/cancel"


#: What `api/notifications.py` never names: the senders, files of its own.
FORBIDDEN = {"send", "send_due", "_append_op", "_post", "BACKENDS",
             "write_text", "write_bytes", "open", "unlink", "rename", "rmtree", "mkdir",
             "subprocess"}


#: The runner's isolation of the bus (tests/run_tests.py, conftest.py, _tmproot:
#: a temp NOTIFY_STATE_DIR, NOTIFY_BACKENDS=log) - each test moves the state into
#: its own temp root and puts the runner's values back after.
_BUS_ENV = ("NOTIFY_STATE_DIR", "NOTIFY_BACKENDS")
_SAVED = {k: os.environ.get(k) for k in _BUS_ENV}


def _restore():
    for k, v in _SAVED.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


try:
    import pytest

    @pytest.fixture(autouse=True)
    def _bus_env():
        yield
        _restore()
except ImportError:                                     # run by hand without pytest
    pass


class backends:
    """NOTIFY_BACKENDS for a block (the runner's `log` back after)."""

    def __init__(self, names):
        self.names = names

    def __enter__(self):
        self.saved = os.environ.get("NOTIFY_BACKENDS")
        os.environ["NOTIFY_BACKENDS"] = self.names

    def __exit__(self, *exc):
        if self.saved is None:
            os.environ.pop("NOTIFY_BACKENDS", None)
        else:
            os.environ["NOTIFY_BACKENDS"] = self.saved


def nf():
    return factory.notify()


class NoNetwork:
    """The bus's `_post` and its `subprocess` fail the test when reached."""

    def __enter__(self):
        m = nf()
        self.saved = (m._post, m.subprocess)

        def boom(*a, **k):
            raise AssertionError("the bus reached the network / a process")
        m._post, m.subprocess = boom, types.SimpleNamespace(run=boom, Popen=boom)
        return self

    def __exit__(self, *exc):
        m = nf()
        m._post, m.subprocess = self.saved


def start(env=ENV):
    notifications.FACTORY_KW.clear()
    notifications.FACTORY_KW["now"] = NOW
    root = factory_tree()
    os.environ["NOTIFY_STATE_DIR"] = str(root / "notify")
    if env is not None:
        _w(root / ".env", env)
    return root, client(root)


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(Path(root).rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


def get(c, path, **params):
    r = c.get(path, params=params)
    return r.status_code, r.json()


def post(c, path, body):
    r = c.post(path, headers=H, json=body)
    return r.status_code, r.json()


def jsonl(path):
    return [json.loads(x) for x in Path(path).read_text(encoding="utf-8").splitlines() if x]


def journal_rows(root):
    rows = [
        {"at": "2026-10-10T08:00:00Z", "kind": "accept", "channel": "reel", "key": "a:1",
         "text": "ролик ждёт «да»", "link": "http://127.0.0.1:8790/#ch-reel-acceptance",
         "task": "CF-0591", "backends": {"log": "ok"}},
        {"at": "2026-10-10T09:00:00Z", "kind": "token", "channel": None, "key": "t:1",
         "text": "токен истекает", "link": None, "task": "CF-0591",
         "backends": {"log": "ok", "telegram":
                      f"error: URLError: https://api.telegram.org/bot{TOKEN}/sendMessage"}},
        {"at": "2026-10-10T10:00:00Z", "kind": "accept", "channel": "demo", "key": "a:2",
         "text": f"старая строка с {TOKEN}", "link": None, "task": "CF-0591",
         "backends": {"log": "ok"}},
    ]
    _w(root / "notify" / "sent.jsonl", "".join(json.dumps(r, ensure_ascii=False) + "\n"
                                              for r in rows))
    return rows


# --------------------------------------------------------------------- the contract
def test_the_contract_names_the_routes():
    root, c = start()
    spec = c.get("/api/openapi.json").json()
    assert spec["info"]["version"] == api.API_VERSION == "0.79.0"
    for p in GETS:
        assert set(spec["paths"][p]) <= {"get", "post"}, spec["paths"][p]
        assert "get" in spec["paths"][p]
    assert set(spec["paths"]["/api/notify/journal"]) == {"get"}
    assert set(spec["paths"]["/api/notify/check"]) == {"get"}
    assert set(spec["paths"][PLAN]) == {"post"}
    assert set(spec["paths"][CONFIRM]) == {"get", "post"}
    ref = spec["paths"]["/api/notify/journal"]["get"]["responses"]["422"]["content"]
    assert ref["application/json"]["schema"]["$ref"].endswith("/NotifyProblem"), ref
    ref = spec["paths"][PLAN]["post"]["responses"]["422"]["content"]["application/json"]
    assert ref["schema"]["$ref"].endswith("/NotifyProblem"), ref
    plan = spec["components"]["schemas"]["NotifyReminderPlan"]["properties"]
    assert {"action", "ok", "fingerprint", "confirm", "expires_in_s", "due", "due_msk", "text",
            "by", "at"} <= set(plan)
    res = spec["components"]["schemas"]["NotifyReminderResult"]["properties"]
    assert {"written", "created", "by", "via", "reminder"} <= set(res)
    for p in ("/api/notify/reminders/{rid}/cancel/plan", "/api/notify/reminders/{rid}/cancel"):
        assert set(spec["paths"][p]) == {"post"}, spec["paths"][p]
        ref = spec["paths"][p]["post"]["responses"]["404"]["content"]["application/json"]
        assert ref["schema"]["$ref"].endswith("/NotifyProblem"), ref
    schemas = spec["components"]["schemas"]
    assert {"id", "status", "means", "reminder", "by", "via", "fingerprint", "confirm",
            "expires_in_s"} <= set(schemas["NotifyCancelPlan"]["properties"])
    assert {"written", "cancelled_at", "cancelled_by", "cancelled_via", "reminder"} <= \
        set(schemas["NotifyCancelResult"]["properties"])
    assert {"via", "cancelled_by", "cancelled_via"} <= set(schemas["NotifyReminder"]["properties"])
    assert set(schemas["NotifyBackendPreview"]["properties"]) == \
        {"name", "known", "external", "ready", "skip_reason", "would_get"}
    assert {"preview", "lines", "backends"} <= set(schemas["NotifyCheck"]["properties"])


def test_the_module_never_sends_and_cancels_only_in_the_confirm():
    tree = ast.parse((ROOT / "api" / "notifications.py").read_text(encoding="utf-8"))
    names = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)} | \
        {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert not names & FORBIDDEN, names & FORBIDDEN
    strings = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant)
               and isinstance(n.value, str)}
    assert "--send" not in strings
    where = {}
    for node in tree.body:
        for n in ast.walk(node):
            if isinstance(n, ast.Attribute) and n.attr in ("parse_when", "add_reminder", "main",
                                                           "cancel_reminder", "test_preview"):
                where.setdefault(n.attr, set()).add(getattr(node, "name", None))
    assert where == {"parse_when": {"_plan"}, "add_reminder": {"reminder_add"},
                     "main": {"check"}, "cancel_reminder": {"reminder_cancel"},
                     "test_preview": {"check"}}, where


# --------------------------------------------------------------------- the journal
def test_the_journal_as_stored_newest_last_token_masked():
    root, c = start()
    journal_rows(root)
    before = files(root)
    s, d = get(c, "/api/notify/journal")
    assert s == 200, d
    assert d["path"] == "notify/sent.jsonl" and d["total"] == 3, d
    assert [e["key"] for e in d["events"]] == ["a:1", "t:1", "a:2"], d
    assert "reminder" in d["kinds"] and "accept" in d["kinds"]
    assert TOKEN not in json.dumps(d, ensure_ascii=False), d
    assert d["events"][1]["backends"]["telegram"] == \
        "error: URLError: https://api.telegram.org/bot***/sendMessage", d["events"][1]
    assert d["events"][2]["text"] == "старая строка с ***", d["events"][2]
    s, d = get(c, "/api/notify/journal", kind="accept")
    assert [e["key"] for e in d["events"]] == ["a:1", "a:2"] and d["total"] == 2, d
    s, d = get(c, "/api/notify/journal", channel="reel")
    assert [e["key"] for e in d["events"]] == ["a:1"], d
    s, d = get(c, "/api/notify/journal", limit=1)
    assert [e["key"] for e in d["events"]] == ["a:2"] and d["total"] == 3, d
    s, d = get(c, "/api/notify/journal", limit=0)
    assert len(d["events"]) == 3, d
    s, d = get(c, "/api/notify/journal", kind="nope")
    assert s == 422 and d["code"] == "bad_kind" and set(d) == {"message", "code", "details"}, d
    assert files(root) == before


def test_an_old_console_link_is_the_centers_route():
    """CC-0120 (CF-0735): a journal row's link to the 2.2 console (8790/#anchor)
    goes out as the center's route (CC-0035: the center is on 8790 too) (`notify.center_link`); none stays none."""
    saved = {k: os.environ.pop(k, None) for k in ("NOTIFY_CENTER_URL", "NOTIFY_DASHBOARD_URL")}
    try:
        root, c = start()
        rows = journal_rows(root)
        assert rows[0]["link"] == "http://127.0.0.1:8790/#ch-reel-acceptance"
        s, d = get(c, "/api/notify/journal")
    finally:
        os.environ.update({k: v for k, v in saved.items() if v is not None})
    assert s == 200, d
    assert d["events"][0]["link"] == "http://127.0.0.1:8790/videos?channel=reel", d["events"][0]
    assert d["events"][1]["link"] is None, d["events"][1]


def test_no_journal_is_an_empty_one():
    root, c = start(env=None)
    s, d = get(c, "/api/notify/journal")
    assert s == 200 and d["events"] == [] and d["total"] == 0, d
    assert not (root / "notify").exists()


# --------------------------------------------------------------------- the reminders
def test_the_reminders_still_to_go_and_every_one():
    root, c = start()
    m = nf()
    r1, _ = m.add_reminder("2026-10-12 10:00", "позвонить", root=root, now=NOW, by="user")
    r2, _ = m.add_reminder("18:30", "проверить батч", root=root, now=NOW, by="user")
    m.cancel_reminder(r1["id"], root=root, now=NOW)
    with open(root / "notify" / "reminders.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"op": "add", "id": "R9", "due": "2026-10-13T07:00:00Z",
                             "text": f"старый {TOKEN}", "by": "user", "at": NOW}) + "\n")
    before = files(root)
    s, d = get(c, "/api/notify/reminders")
    assert s == 200, d
    assert d["path"] == "notify/reminders.jsonl" and d["all"] is False, d
    assert d["max_attempts"] == m.REMINDER_MAX_ATTEMPTS
    assert [r["id"] for r in d["reminders"]] == [r2["id"], "R9"], d
    one = d["reminders"][0]
    assert (one["due"], one["due_msk"], one["status"], one["by"]) == \
        ("2026-10-11T15:30:00Z", "2026-10-11 18:30 МСК", "pending", "user"), one
    assert d["reminders"][1]["text"] == "старый ***", d["reminders"][1]
    assert all((r["via"], r["cancelled_by"], r["cancelled_via"]) == (None, None, None)
               for r in d["reminders"]), d                      # CLI adds, an old row
    s, d = get(c, "/api/notify/reminders", all="true")
    assert [r["id"] for r in d["reminders"]] == [r1["id"], r2["id"], "R9"], d
    assert d["reminders"][0]["status"] == "cancelled" and d["reminders"][0]["due_msk"] == \
        "2026-10-12 10:00 МСК", d["reminders"][0]
    assert (d["reminders"][0]["cancelled_by"], d["reminders"][0]["cancelled_via"]) == \
        (None, None), d["reminders"][0]                          # a CLI cancel: no one
    assert files(root) == before


# --------------------------------------------------------------------- the check
def test_the_check_is_the_dry_test_nothing_sent():
    root, c = start()
    before = files(root)
    with NoNetwork(), backends("log,telegram,ntfy"):
        s, d = get(c, "/api/notify/check")
    assert s == 200, d
    assert d["backends"] == ["log", "telegram", "ntfy"] and d["default"] == ["log"], d
    assert d["external"] == ["telegram", "ntfy"] and d["sent"] is False, d
    text = "\n".join(d["lines"])
    assert TOKEN not in text, text
    assert d["lines"][0].startswith("journal: ") and d["lines"][1].startswith(
        "backends on: log, telegram, ntfy"), d["lines"]
    tg = next(ln for ln in d["lines"] if ln.strip().startswith("telegram:"))
    assert "would get" in tg and "SENDS THE TEXT TO AN OUTSIDE SERVICE" in tg, tg
    nt = next(ln for ln in d["lines"] if ln.strip().startswith("ntfy:"))
    assert "would be skipped (no NOTIFY_NTFY_URL in .env)" in nt, nt
    assert d["lines"][-1].startswith("nothing sent"), d["lines"]
    pv = {b["name"]: b for b in d["preview"]}
    assert [b["name"] for b in d["preview"]] == ["log", "telegram", "ntfy"], d["preview"]
    assert all(set(b) == {"name", "known", "external", "ready", "skip_reason", "would_get"}
               for b in d["preview"]), d["preview"]
    assert (pv["log"]["known"], pv["log"]["external"], pv["log"]["ready"],
            pv["log"]["skip_reason"]) == (True, False, True, None), pv["log"]
    assert "проверка уведомлений фабрики" in pv["log"]["would_get"], pv["log"]
    assert (pv["telegram"]["external"], pv["telegram"]["ready"],
            pv["telegram"]["skip_reason"]) == (True, True, None), pv["telegram"]
    assert pv["telegram"]["would_get"], pv["telegram"]
    assert (pv["ntfy"]["external"], pv["ntfy"]["ready"]) == (True, False), pv["ntfy"]
    assert "NOTIFY_NTFY_URL" in pv["ntfy"]["skip_reason"], pv["ntfy"]
    assert files(root) == before


def test_the_check_preview_an_unknown_backend_and_a_planted_token():
    root, c = start()
    with NoNetwork(), backends("log,pigeon"):
        s, d = get(c, "/api/notify/check")
    assert s == 200, d
    pv = {b["name"]: b for b in d["preview"]}
    assert (pv["pigeon"]["known"], pv["pigeon"]["ready"], pv["pigeon"]["would_get"]) == \
        (False, False, None) and pv["pigeon"]["skip_reason"], pv["pigeon"]
    m = nf()
    real = m.test_preview
    m.test_preview = lambda *a, **k: [{"name": "telegram", "known": True, "external": True,
                                       "ready": True, "skip_reason": None,
                                       "would_get": f"bot{TOKEN} сказал", "extra": 1}]
    try:
        with NoNetwork():
            s, d = get(c, "/api/notify/check")
    finally:
        m.test_preview = real
    assert s == 200, d
    assert TOKEN not in json.dumps(d, ensure_ascii=False), d
    assert d["preview"] == [{"name": "telegram", "known": True, "external": True,
                             "ready": True, "skip_reason": None,
                             "would_get": "bot*** сказал"}], d["preview"]


def test_the_check_with_the_default_backend():
    root, c = start(env=None)
    with NoNetwork():
        s, d = get(c, "/api/notify/check")
    assert s == 200 and d["backends"] == ["log"] and d["external"] == [], d
    assert [(b["name"], b["ready"]) for b in d["preview"]] == [("log", True)], d["preview"]
    assert any(ln.strip().startswith("log: would get") for ln in d["lines"]), d["lines"]


# --------------------------------------------------------------------- the plan
def test_the_plan_writes_nothing():
    root, c = start()
    before = files(root)
    s, plan = post(c, PLAN, {"at": "2026-10-12 10:00 МСК", "text": "  позвонить \n  в банк "})
    assert s == 200, plan
    assert files(root) == before
    assert plan["action"] == "notify_reminder_add" and plan["ok"] is True, plan
    assert plan["confirm"] and plan["expires_in_s"] == 120 and len(plan["fingerprint"]) == 64
    assert (plan["due"], plan["due_msk"], plan["text"], plan["by"], plan["via"], plan["now"]) == \
        ("2026-10-12T07:00:00Z", "2026-10-12 10:00 МСК", "позвонить в банк", "user", "center",
         NOW), plan
    s, plan = post(c, PLAN, {"at": "14:00", "text": "x"})       # passed today: tomorrow
    assert plan["due"] == "2026-10-12T11:00:00Z", plan
    s, plan = post(c, PLAN, {"at": "10:00", "text": f"токен {TOKEN}"})
    assert TOKEN not in plan["text"], plan
    assert files(root) == before


def test_a_time_or_text_the_factory_refuses_is_422():
    root, c = start()
    before = files(root)
    s, d = post(c, PLAN, {"at": "25:00", "text": "x"})
    assert s == 422 and d["code"] == "bad_time" and "no such time" in d["details"][0], d
    assert d["message"].startswith("Время «25:00» не подходит"), d
    s, d = post(c, PLAN, {"at": "2026-10-10 10:00", "text": "x"})
    assert s == 422 and d["code"] == "bad_time" and "has passed" in d["details"][0], d
    s, d = post(c, PLAN, {"at": "завтра", "text": "x"})
    assert s == 422 and d["code"] == "bad_time", d
    s, d = post(c, PLAN, {"at": "10:00", "text": "  \n "})
    assert s == 422 and d["code"] == "no_text", d
    assert files(root) == before


# --------------------------------------------------------------------- the confirm
def test_the_confirm_queues_by_user_nothing_sent():
    root, c = start()
    with NoNetwork():
        s, plan = post(c, PLAN, {"at": "2026-10-12 10:00", "text": "позвонить"})
        s, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 200, got
    assert got["written"] is True and got["created"] is True and got["by"] == "user", got
    assert got["via"] == "center", got
    r = got["reminder"]
    assert (r["id"], r["due"], r["due_msk"], r["text"], r["status"], r["by"], r["via"],
            r["created"]) == ("R1", "2026-10-12T07:00:00Z", "2026-10-12 10:00 МСК", "позвонить",
                              "pending", "user", "center", NOW), r
    (op,) = jsonl(root / "notify" / "reminders.jsonl")
    assert (op["op"], op["id"], op["by"], op["via"], op["at"], op["task"]) == \
        ("add", "R1", "user", "center", NOW, "CF-0606"), op
    assert not (root / "notify" / "sent.jsonl").exists()          # nothing sent
    # the token is spent
    s, again = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 409 and again["code"] == "confirm_unknown", again
    # the same reminder again: that one, not a second
    s, plan = post(c, PLAN, {"at": "2026-10-12 10:00", "text": "позвонить"})
    s, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 200 and got["created"] is False and got["reminder"]["id"] == "R1", got
    assert len(jsonl(root / "notify" / "reminders.jsonl")) == 1
    s, d = get(c, "/api/notify/reminders")
    assert [x["id"] for x in d["reminders"]] == ["R1"], d


def test_a_time_that_rolled_since_the_plan_is_check_changed():
    root, c = start()
    s, plan = post(c, PLAN, {"at": "16:00", "text": "x"})       # 13:00Z today
    assert plan["due"] == "2026-10-11T13:00:00Z", plan
    before = files(root)
    notifications.FACTORY_KW["now"] = "2026-10-11T13:30:00Z"     # 16:00 has passed: tomorrow
    s, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 409 and got["code"] == "check_changed", got
    assert files(root) == before
    notifications.FACTORY_KW["now"] = NOW
    s, plan = post(c, PLAN, {"at": "2026-10-11 16:00", "text": "x"})
    notifications.FACTORY_KW["now"] = "2026-10-11T13:30:00Z"     # a dated one: passed
    s, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    assert s == 422 and got["code"] == "bad_time", got
    assert files(root) == before


def test_a_token_spent_expired_or_foreign_is_refused():
    root, c = start()
    s, plan = post(c, PLAN, {"at": "10:00", "text": "x"})
    clock = batches._clock
    try:
        batches._clock = lambda: clock() + batches.CONFIRM_TTL + 1
        s, got = post(c, CONFIRM, {"confirm": plan["confirm"]})
    finally:
        batches._clock = clock
    assert s == 409 and got["code"] == "confirm_expired", got
    s, got = post(c, CONFIRM, {"confirm": "nope"})
    assert s == 409 and got["code"] == "confirm_unknown", got
    foreign = batches._issue(root, "launch", "reel", "0" * 64)
    s, got = post(c, CONFIRM, {"confirm": foreign})
    assert s == 409 and got["code"] == "confirm_mismatch", got
    assert "напоминание не поставлено" in got["message"], got
    s, got = post(c, CONFIRM, {})
    assert s == 422, got
    assert not (root / "notify").exists()


# --------------------------------------------------------------------- the cancel (CC-0081)
def queued(root, *texts):
    m = nf()
    return [m.add_reminder("2026-10-12 10:00", t, root=root, now=NOW, by="user")[0]["id"]
            for t in texts]


def test_the_cancel_plan_writes_nothing_the_confirm_cancels_by_user_via_center():
    root, c = start()
    rid, other = queued(root, f"позвонить {TOKEN}", "второе")
    before = files(root)
    with NoNetwork():
        s, plan = post(c, cplan(rid.lower()), {})
    assert s == 200, plan
    assert files(root) == before
    assert (plan["action"], plan["ok"], plan["id"], plan["status"], plan["by"], plan["via"]) == \
        ("notify_reminder_cancel", True, rid, "pending", "user", "center"), plan
    assert plan["confirm"] and plan["expires_in_s"] == 120 and len(plan["fingerprint"]) == 64
    assert plan["means"].startswith("Напоминание не уйдёт"), plan
    assert plan["reminder"]["text"] == "позвонить ***" and \
        plan["reminder"]["due_msk"] == "2026-10-12 10:00 МСК", plan["reminder"]
    assert TOKEN not in json.dumps(plan, ensure_ascii=False)
    notifications.FACTORY_KW["now"] = "2026-10-11T12:05:00Z"
    with NoNetwork():
        s, got = post(c, cconfirm(rid), {"confirm": plan["confirm"]})
    assert s == 200, got
    assert (got["action"], got["written"], got["by"], got["via"], got["cancelled_at"],
            got["cancelled_by"], got["cancelled_via"]) == \
        ("notify_reminder_cancel", True, "user", "center", "2026-10-11T12:05:00Z", "user",
         "center"), got
    r = got["reminder"]
    assert (r["id"], r["status"], r["cancelled_by"], r["cancelled_via"], r["text"]) == \
        (rid, "cancelled", "user", "center", "позвонить ***"), r
    op = jsonl(root / "notify" / "reminders.jsonl")[-1]
    assert (op["op"], op["id"], op["by"], op["via"], op["at"]) == \
        ("cancel", rid, "user", "center", "2026-10-11T12:05:00Z"), op
    assert not (root / "notify" / "sent.jsonl").exists()          # nothing sent
    s, d = get(c, "/api/notify/reminders")
    assert [x["id"] for x in d["reminders"]] == [other], d
    s, d = get(c, "/api/notify/reminders", all="true")
    mine = next(x for x in d["reminders"] if x["id"] == rid)
    assert (mine["cancelled_by"], mine["cancelled_via"], mine["cancelled_at"]) == \
        ("user", "center", "2026-10-11T12:05:00Z"), mine
    # the token is spent; the reminder is cancelled now
    s, again = post(c, cconfirm(rid), {"confirm": plan["confirm"]})
    assert s == 409 and again["code"] == "confirm_unknown", again
    s, again = post(c, cplan(rid), {})
    assert s == 409 and again["code"] == "not_cancellable", again
    assert "уже отменено" in again["message"], again


def test_the_cancel_of_no_such_or_a_sent_reminder_is_refused():
    root, c = start()
    (rid,) = queued(root, "x")
    with open(root / "notify" / "reminders.jsonl", "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"op": "sent", "id": rid, "at": NOW, "backends": {"log": "ok"},
                             "attempt": 1}) + "\n")
    before = files(root)
    s, d = post(c, cplan("R77"), {})
    assert s == 404 and d["code"] == "no_reminder" and set(d) == {"message", "code", "details"}, d
    s, d = post(c, cconfirm("R77"), {"confirm": "nope"})
    assert s == 409 and d["code"] == "confirm_unknown", d
    s, d = post(c, cplan(rid), {})
    assert s == 409 and d["code"] == "not_cancellable" and "уже отправлено" in d["message"], d
    assert files(root) == before


def test_a_failed_reminder_is_cancellable_but_a_try_since_the_plan_is_check_changed():
    root, c = start()
    (rid,) = queued(root, "x")
    path = root / "notify" / "reminders.jsonl"

    def failed(attempt):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"op": "failed", "id": rid, "at": NOW, "attempt": attempt,
                                 "reason": "no outside backend", "backends": {}}) + "\n")
    failed(1)
    s, plan = post(c, cplan(rid), {})
    assert s == 200 and plan["status"] == "failed", plan
    failed(2)                                                     # the tick tried again
    before = files(root)
    s, got = post(c, cconfirm(rid), {"confirm": plan["confirm"]})
    assert s == 409 and got["code"] == "check_changed", got
    assert files(root) == before
    # cancelled from the command line meanwhile: not cancellable, nothing written
    s, plan = post(c, cplan(rid), {})
    nf().cancel_reminder(rid, root=root, now=NOW)
    before = files(root)
    s, got = post(c, cconfirm(rid), {"confirm": plan["confirm"]})
    assert s == 409 and got["code"] == "not_cancellable", got
    assert files(root) == before


def test_a_cancel_token_of_another_reminder_or_of_the_add_is_refused():
    root, c = start()
    a, b = queued(root, "a", "b")
    before = files(root)
    s, plan = post(c, cplan(a), {})
    s, got = post(c, cconfirm(b), {"confirm": plan["confirm"]})
    assert s == 409 and got["code"] == "confirm_mismatch", got
    assert "напоминание не отменено" in got["message"], got
    s, add = post(c, PLAN, {"at": "10:00", "text": "x"})
    s, got = post(c, cconfirm(a), {"confirm": add["confirm"]})
    assert s == 409 and got["code"] == "confirm_mismatch", got
    s, plan = post(c, cplan(a), {})
    s, got = post(c, CONFIRM, {"confirm": plan["confirm"]})      # a cancel's token on the add
    assert s == 409 and got["code"] == "confirm_mismatch", got
    s, plan = post(c, cplan(a), {})
    clock = batches._clock
    try:
        batches._clock = lambda: clock() + batches.CONFIRM_TTL + 1
        s, got = post(c, cconfirm(a), {"confirm": plan["confirm"]})
    finally:
        batches._clock = clock
    assert s == 409 and got["code"] == "confirm_expired", got
    s, got = post(c, cconfirm(a), {})
    assert s == 422, got
    assert files(root) == before


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
        finally:
            _restore()
    notifications.FACTORY_KW.clear()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
