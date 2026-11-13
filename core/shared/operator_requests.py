#!/usr/bin/env python3
"""CF-0684: the queue of the user's free requests to the operator.

Grill CF-0626, Q5. A free request of the user («переделай, потому что...»)
is not executed by the command center, and the center does not start Claude
for it: the center puts it in this queue, an operator session takes it and
answers, and the answer is seen in the center and goes to Telegram. The
shape is the journal of questions (shared/needs_you.py, CF-0652); the API of
the center (CC-0018/0019, the `cc/api` line) reads and writes it through the
functions below.

**Where.** `<root>/requests/requests.jsonl` (`REQUESTS_DIR` puts the default
directory elsewhere - the test runners do; a caller that names a root or a
directory gets that one). It is **state, not code**: gitignored, like
`needs-you/` and `notify/` - the center writes it at any moment, and
`batch-start` wants a clean `main`. Nothing here commits.

**Format.** An append-only log of operations, one JSON object per line:

    {"op": "add",    "id": "R7", "text": T, "by": B, "channel": C|null,
                     "context": X|null, "at": ISO}
    {"op": "take",   "id": "R7", "by": B, "at": ISO}
    {"op": "answer", "id": "R7", "answer": A, "by": B, "at": ISO}
    {"op": "notify", "id": "R7", "attempt": N, "key": K, "status": "sent"|"failed",
                     "reason": R|null, "backends": {name: result}, "at": ISO}
    {"op": "close",  "id": "R7", "by": B, "at": ISO}
    {"op": "cancel", "id": "R7", "by": B, "at": ISO}

folded into the requests' state by `requests()` / `list()`:

    {id, n, text, channel, context, created, created_by, updated,
     status (open | taken | answered | closed | cancelled),
     taken_by, taken_at, answer, answered_by, answered_at,
     closed_by, closed_at, cancelled_by, cancelled_at,
     notify: null | {status: sent | failed, attempt, key, reason, backends, at}}

The steps: `open` -> `taken` (`next`) -> `answered` (`answer`) -> `closed`
(`close`); `cancel` from `open` or `taken`. Any other step is refused with a
RequestError that carries a stable `code` and the Russian line `text_ru`
(REFUSALS_RU), as AcceptanceError does in shared/runlog/acceptance.py.

Every write takes an exclusive `flock` on `requests.lock` beside the journal
and appends one whole line (fsync'd); reads take nothing.

**Telegram.** An answer goes through the notification bus (shared/notify.py,
kind `request_answer`, key `request:<id>:answer`, a retry `...#again:try<n>`).
As with the reminders of CF-0617 the bus's answer is judged by
`notify.delivery`: an answer no outside backend took is the op `notify` with
`status: failed` and the reason - seen in the request's `notify`, not lost -
and `resend` tries again. The bot token never reaches this journal: the bus
masks it in every backend's answer, and this file scrubs the reason again.

    python3 shared/operator_requests.py add TEXT [--channel C] [--by B]
    python3 shared/operator_requests.py list [--status open|taken|answered|closed|cancelled|live|all] [--json]
    python3 shared/operator_requests.py next [--by B] [--json]
    python3 shared/operator_requests.py answer ID TEXT [--by B]
    python3 shared/operator_requests.py close ID [--by B]
    python3 shared/operator_requests.py cancel ID [--by B]
    python3 shared/operator_requests.py resend ID [--by B]
        # every command takes --dir DIR (the journal's directory) or --root DIR
        # exit 0 done, 1 refused / nothing to take, 2 bad call

The module is `operator_requests`, not `requests`: a file of that name in
`shared/` would shadow the HTTP library (Google's clients use it) for every
process with `shared/` on `sys.path`. The journal's directory, `REQUESTS_DIR`,
the bus kind `request_answer` and the ids `R<n>` keep the short name - none
of them is an import.
"""
import argparse
import builtins
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0684"
ROOT = Path(__file__).resolve().parent.parent
DIR_ENV = "REQUESTS_DIR"
DIRNAME = "requests"
JOURNAL = "requests.jsonl"
LOCK = "requests.lock"
STATUSES = ("open", "taken", "answered", "closed", "cancelled")
LIVE = ("open", "taken", "answered")
TEXT_MAX = 4000
CONTEXT_MAX = 4000
BY_MAX = 80
NOTIFY_KIND = "request_answer"
NOTIFY_PREVIEW = 160          # how much of the request the Telegram line quotes
DEFAULT_OPERATOR = "operator"
DEFAULT_USER = "user"

# The steps and the states each may start from.
STEPS = {"take": ("open",), "answer": ("taken",), "close": ("answered",),
         "cancel": ("open", "taken")}

_next = builtins.next         # this module defines its own `next` and `list`


# CF-0684: code -> the Russian line of a refusal (the center shows it). The
# English text - str(e) - is for journals and tests.
REFUSALS_RU = {
    "text_empty": "Просьба пустая - напишите, что сделать.",
    "text_too_long": "Просьба длиннее {limit} знаков - сократите её.",
    "answer_empty": "Ответ пустой - напишите текст ответа.",
    "answer_too_long": "Ответ длиннее {limit} знаков - сократите его.",
    "by_missing": "Не сказано, кто это делает.",
    "context_invalid": "Контекст просьбы не записать: {why}.",
    "status_unknown": "«{status}» - не состояние просьбы; бывают: {known}.",
    "not_found": "Просьбы {id} нет.",
    "not_taken": "Просьба {id} ещё не взята в работу - отвечает оператор, который её взял.",
    "already_answered": "На просьбу {id} уже ответили - второй ответ не записывается.",
    "not_answered": "На просьбу {id} ещё не ответили - закрыть её можно после ответа "
                    "(или отменить).",
    "already_closed": "Просьба {id} уже закрыта.",
    "already_cancelled": "Просьба {id} отменена.",
    "cancel_answered": "На просьбу {id} уже ответили - отменять нечего, её можно закрыть.",
    "no_answer": "У просьбы {id} нет ответа - отправлять в Telegram нечего.",
    "already_delivered": "Ответ на просьбу {id} уже дошёл - повторять не нужно.",
}


class RequestError(ValueError):
    """A request that may not be written, or a step it cannot take.

    Carries a stable `code` and `text_ru` (REFUSALS_RU, filled with the values
    the raise passes); a code with no row is a KeyError at the raise."""

    def __init__(self, text, *, code, **values):
        super().__init__(text)
        self.code = code
        self.values = values
        self.text_ru = REFUSALS_RU[code].format_map(values)

    def as_dict(self):
        """{code, text_ru, text} - the refusal as the center reads it."""
        return {"code": self.code, "text_ru": self.text_ru, "text": str(self)}


# ------------------------------------------------------------------ where
def journal_dir(root=None, environ=None, directory=None):
    """`directory`, else `<root>/requests` of a root given, else
    `REQUESTS_DIR`, else `<this checkout>/requests`. The test runners set
    `REQUESTS_DIR`, so a test that forgets both never writes the live queue."""
    if directory:
        return Path(directory).expanduser()
    if root:
        return Path(root) / DIRNAME
    env = os.environ if environ is None else environ
    if env.get(DIR_ENV):
        return Path(env[DIR_ENV]).expanduser()
    return ROOT / DIRNAME


def journal_path(root=None, environ=None, directory=None):
    return journal_dir(root, environ, directory) / JOURNAL


def now_iso(now=None):
    if now:
        if isinstance(now, datetime):
            if now.tzinfo is None:
                now = now.replace(tzinfo=timezone.utc)
            return now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        return str(now)
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _text(text):
    """The user's words as written: lines kept, ends stripped."""
    return "\n".join(ln.rstrip() for ln in str(text or "").strip().splitlines())


def _by(by):
    by = " ".join(str(by or "").split())[:BY_MAX]
    if not by:
        raise RequestError("who does it: `by` is empty", code="by_missing")
    return by


def _norm_id(rid):
    return str(rid or "").strip().upper()


def _number(rid):
    m = re.match(r"^R(\d+)$", str(rid or ""))
    return int(m.group(1)) if m else 0


@contextmanager
def _locked(directory):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    with open(directory / LOCK, "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _ops(directory):
    out = []
    try:
        lines = (Path(directory) / JOURNAL).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            doc = json.loads(ln)
        except ValueError:
            continue
        if isinstance(doc, dict) and doc.get("id") and doc.get("op"):
            out.append(doc)
    return out


def _append(directory, op):
    with open(Path(directory) / JOURNAL, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(dict(op, task=TASK), ensure_ascii=False) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _channel_ids():
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.append(shared)
    import channel_ids                                          # noqa: PLC0415
    return channel_ids


def _bus():
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.append(shared)
    import notify                                               # noqa: PLC0415
    return notify


def _fold(ops, root=None):
    """The requests' state, oldest first. A step the state does not allow
    (a journal written by hand) is skipped, as the functions would refuse it.
    The channel is resolved where it is read (`channel_ids.resolve_channel`,
    CF-0197): a request made before a rename names the channel by its current id."""
    ids = _channel_ids()
    by_id = {}
    for op in ops:
        rid, kind = op["id"], op.get("op")
        if kind == "add":
            if rid in by_id:
                continue
            by_id[rid] = {"id": rid, "n": _number(rid), "text": op.get("text"),
                          "channel": ids.resolve_channel(op.get("channel"), root),
                          "context": op.get("context"),
                          "created": op.get("at"), "created_by": op.get("by"),
                          "updated": op.get("at"), "status": "open",
                          "taken_by": None, "taken_at": None,
                          "answer": None, "answered_by": None, "answered_at": None,
                          "closed_by": None, "closed_at": None,
                          "cancelled_by": None, "cancelled_at": None, "notify": None}
            continue
        r = by_id.get(rid)
        if r is None:
            continue
        if kind == "notify":
            if r["answer"] is not None:
                r["notify"] = {k: op.get(k) for k in
                               ("status", "attempt", "key", "reason", "backends", "at")}
            continue
        if kind not in STEPS or r["status"] not in STEPS[kind]:
            continue
        at, by = op.get("at"), op.get("by")
        r["updated"] = at
        if kind == "take":
            r.update(status="taken", taken_by=by, taken_at=at)
        elif kind == "answer":
            r.update(status="answered", answer=op.get("answer"), answered_by=by, answered_at=at)
        elif kind == "close":
            r.update(status="closed", closed_by=by, closed_at=at)
        elif kind == "cancel":
            r.update(status="cancelled", cancelled_by=by, cancelled_at=at)
    return sorted(by_id.values(), key=lambda r: r["n"])


def _refuse_step(step, r):
    """The refusal of `step` on request `r` in a state it does not start from."""
    rid, st = r["id"], r["status"]
    if st == "closed":
        code = "already_closed"
    elif st == "cancelled":
        code = "already_cancelled"
    elif step == "answer":
        code = "not_taken" if st == "open" else "already_answered"
    elif step == "close":
        code = "not_answered"
    elif step == "cancel":
        code = "cancel_answered"
    else:                                                       # take: never by id
        code = "already_answered"
    raise RequestError(f"request {rid} is {st}: it cannot take the step {step!r}",
                       code=code, id=rid)


def _step(rid, step, by, root, now, environ, directory, extra=None):
    """One step on one request under the lock. Returns its new state."""
    rid = _norm_id(rid)
    d = journal_dir(root, environ, directory)
    with _locked(d):
        r = _next((x for x in _fold(_ops(d), root) if x["id"] == rid), None)
        if r is None:
            raise RequestError(f"no request {rid or '(empty id)'}", code="not_found", id=rid)
        if r["status"] not in STEPS[step]:
            _refuse_step(step, r)
        _append(d, dict({"op": step, "id": rid, "by": by, "at": now_iso(now)}, **(extra or {})))
        return _next(x for x in _fold(_ops(d), root) if x["id"] == rid)


# ------------------------------------------------------------------ read
def requests(status=None, root=None, environ=None, directory=None):
    """Every request, oldest first. `status`: one of STATUSES, `live` (open +
    taken + answered), a tuple of them, or None / `all`."""
    if status == "live":
        status = LIVE
    if status and status != "all":
        want = (status,) if isinstance(status, str) else tuple(status)
        bad = [s for s in want if s not in STATUSES]
        if bad:
            raise RequestError(f"unknown status {bad[0]!r}", code="status_unknown",
                               status=bad[0], known=", ".join(STATUSES + ("live", "all")))
    else:
        want = None
    rs = _fold(_ops(journal_dir(root, environ, directory)), root)
    return [r for r in rs if r["status"] in want] if want else rs


def list(status=None, root=None, environ=None, directory=None):     # noqa: A001
    """The requests (see `requests`): the center's list."""
    return requests(status, root=root, environ=environ, directory=directory)


def get(rid, root=None, environ=None, directory=None):
    rid = _norm_id(rid)
    return _next((r for r in requests(root=root, environ=environ, directory=directory)
                  if r["id"] == rid), None)


# ------------------------------------------------------------------ write
def add(text, by, channel=None, context=None, root=None, now=None, environ=None,
        directory=None):
    """A new request, `open`. `context` - anything JSON the center wants kept
    with it (the video, the batch, the screen it was asked from)."""
    text = _text(text)
    if not text:
        raise RequestError("a request needs a text", code="text_empty")
    if len(text) > TEXT_MAX:
        raise RequestError(f"a request is longer than {TEXT_MAX}", code="text_too_long",
                           limit=TEXT_MAX)
    by = _by(by)
    if context is not None:
        try:
            size = len(json.dumps(context, ensure_ascii=False))
        except (TypeError, ValueError) as e:
            raise RequestError(f"context is not JSON: {e}", code="context_invalid",
                               why="это не JSON") from None
        if size > CONTEXT_MAX:
            raise RequestError(f"context is longer than {CONTEXT_MAX}", code="context_invalid",
                               why=f"длиннее {CONTEXT_MAX} знаков")
    channel = " ".join(str(channel or "").split()) or None
    d = journal_dir(root, environ, directory)
    with _locked(d):
        ops = _ops(d)
        rid = f"R{max([_number(o['id']) for o in ops] + [0]) + 1}"
        _append(d, {"op": "add", "id": rid, "text": text, "by": by, "channel": channel,
                    "context": context, "at": now_iso(now)})
        return _next(r for r in _fold(_ops(d), root) if r["id"] == rid)


def next(by=DEFAULT_OPERATOR, root=None, now=None, environ=None, directory=None):  # noqa: A001
    """Take the oldest `open` request into work (`taken`, by `by`) and return
    it; None when nothing is open. Two operators never take one request: the
    pick and the step are one locked write."""
    by = _by(by)
    d = journal_dir(root, environ, directory)
    with _locked(d):
        r = _next((x for x in _fold(_ops(d), root) if x["status"] == "open"), None)
        if r is None:
            return None
        _append(d, {"op": "take", "id": r["id"], "by": by, "at": now_iso(now)})
        return _next(x for x in _fold(_ops(d), root) if x["id"] == r["id"])


def _telegram_line(r):
    asked = " ".join(str(r["text"] or "").split())
    if len(asked) > NOTIFY_PREVIEW:
        asked = asked[:NOTIFY_PREVIEW - 1].rstrip() + "…"
    return f"{r['id']} «{asked}» - {r['answer']}"


def _push(r, key, root=None, environ=None, backends=None):
    """The bus's send of the answer: its result dict. Never raises."""
    try:
        return _bus().send(NOTIFY_KIND, key, _telegram_line(r), channel=r["channel"],
                           root=root, environ=environ, backends=backends)
    except Exception as e:                                      # noqa: BLE001
        return {"status": "error", "key": key, "error": f"{type(e).__name__}: {e}",
                "backends": {}}


def _deliver(rid, root, now, environ, directory, backends, notifier):
    """Send the answer of `rid` once more through the bus and write the op
    `notify` with what came of it. Never raises; the request's new state."""
    d = journal_dir(root, environ, directory)
    r = get(rid, root=root, environ=environ, directory=directory)
    attempt = int(((r.get("notify") or {}).get("attempt")) or 0) + 1
    key = f"request:{rid}:answer" + (f"#again:try{attempt}" if attempt > 1 else "")
    bus = _bus()
    try:
        res = (notifier(r, key) if notifier else
               _push(r, key, root=root, environ=environ, backends=backends)) or {}
    except Exception as e:                                      # noqa: BLE001
        res = {"status": "error", "error": f"{type(e).__name__}: {e}", "backends": {}}
    got = res.get("backends") or {}
    if res.get("status") == "duplicate":
        row = _next((x for x in bus.rows(root, environ) if x.get("key") == key), {})
        got = row.get("backends") or {}
    if res.get("status") in ("sent", "duplicate"):
        ok, reason = bus.delivery(got)
    else:
        ok, reason = False, f"bus: {res.get('error') or res.get('status')}"
    reason = None if ok else bus.one_line(bus.scrub(reason), bus.REASON_MAX)
    got = {k: bus.scrub(v) for k, v in got.items()}
    if not ok:
        print(f"REQUESTS {rid}: the answer did not reach Telegram (try {attempt}: {reason}) - "
              f"seen in the request; `resend {rid}` tries again", file=sys.stderr, flush=True)
    with _locked(d):
        _append(d, {"op": "notify", "id": rid, "attempt": attempt, "key": key,
                    "status": "sent" if ok else "failed", "reason": reason, "backends": got,
                    "at": now_iso(now)})
    return get(rid, root=root, environ=environ, directory=directory)


def answer(rid, text, by=DEFAULT_OPERATOR, root=None, now=None, environ=None, directory=None,
           backends=None, notifier=None):
    """The operator's answer: `taken` -> `answered`, then the answer goes to
    Telegram through the bus. Whether it got there is the request's `notify`
    (`sent` / `failed` + reason); a failed send never undoes the answer.
    `backends` - the bus's registry (tests: stand-ins); `notifier(request,
    key)` replaces the bus and returns its result dict (tests)."""
    text = _text(text)
    if not text:
        raise RequestError("an answer needs a text", code="answer_empty")
    if len(text) > TEXT_MAX:
        raise RequestError(f"an answer is longer than {TEXT_MAX}", code="answer_too_long",
                           limit=TEXT_MAX)
    by = _by(by)
    r = _step(rid, "answer", by, root, now, environ, directory, extra={"answer": text})
    return _deliver(r["id"], root, now, environ, directory, backends, notifier)


def resend(rid, root=None, now=None, environ=None, directory=None, backends=None,
           notifier=None):
    """Send the answer to Telegram again - after a failed try (the request's
    `notify.status` is `failed`). A new bus key per try."""
    rid = _norm_id(rid)
    r = get(rid, root=root, environ=environ, directory=directory)
    if r is None:
        raise RequestError(f"no request {rid or '(empty id)'}", code="not_found", id=rid)
    if r["answer"] is None:
        raise RequestError(f"request {rid} has no answer", code="no_answer", id=rid)
    if (r.get("notify") or {}).get("status") == "sent":
        raise RequestError(f"the answer to {rid} was delivered", code="already_delivered", id=rid)
    return _deliver(rid, root, now, environ, directory, backends, notifier)


def close(rid, by=DEFAULT_USER, root=None, now=None, environ=None, directory=None):
    """`answered` -> `closed`: the user has read the answer."""
    return _step(rid, "close", _by(by), root, now, environ, directory)


def cancel(rid, by=DEFAULT_USER, root=None, now=None, environ=None, directory=None):
    """`open` / `taken` -> `cancelled`: the request is no longer wanted."""
    return _step(rid, "cancel", _by(by), root, now, environ, directory)


# ------------------------------------------------------------------ the CLI
def line_of(r):
    ch = f" [{r['channel']}]" if r["channel"] else ""
    text = " ".join(str(r["text"] or "").split())
    tail = ""
    if r["status"] == "taken":
        tail = f" -> взял {r['taken_by']} ({r['taken_at']})"
    elif r["answer"] is not None:
        tail = f" -> ответ ({r['answered_by']}, {r['answered_at']}): " + \
            " ".join(str(r["answer"]).split())
    elif r["status"] == "cancelled":
        tail = f" -> отменена ({r['cancelled_by']}, {r['cancelled_at']})"
    n = r.get("notify")
    if n:
        tail += " [Telegram: дошёл]" if n["status"] == "sent" else \
            f" [Telegram: НЕ ДОШЁЛ, попытка {n['attempt']}: {n['reason']}]"
    return f"{r['id']} {r['status']:<9} {r['created']} {r['created_by']}{ch}: {text}{tail}"


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(prog="operator_requests.py", allow_abbrev=False,
                                 description="CF-0684: the queue of the user's requests "
                                             "to the operator")
    where = argparse.ArgumentParser(add_help=False)
    where.add_argument("--dir", help=f"the journal's directory (default ${DIR_ENV}, "
                                     f"else <root>/{DIRNAME})")
    where.add_argument("--root", help="the factory root whose requests/ to use")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", parents=[where], help="a new request (a manual check)")
    a.add_argument("text")
    a.add_argument("--channel")
    a.add_argument("--by", default=DEFAULT_USER)
    a.add_argument("--json", action="store_true")
    ls = sub.add_parser("list", parents=[where], help="the requests")
    ls.add_argument("--status", default="all", choices=("live", "all") + STATUSES)
    ls.add_argument("--json", action="store_true")
    nx = sub.add_parser("next", parents=[where], help="take the oldest open request")
    nx.add_argument("--by", default=DEFAULT_OPERATOR)
    nx.add_argument("--json", action="store_true")
    an = sub.add_parser("answer", parents=[where], help="answer a taken request (+ Telegram)")
    an.add_argument("id")
    an.add_argument("text")
    an.add_argument("--by", default=DEFAULT_OPERATOR)
    an.add_argument("--json", action="store_true")
    for name, hlp in (("close", "close an answered request"),
                      ("cancel", "cancel an open or taken request"),
                      ("resend", "send a failed answer to Telegram again")):
        p = sub.add_parser(name, parents=[where], help=hlp)
        p.add_argument("id")
        if name != "resend":
            p.add_argument("--by", default=DEFAULT_USER)
        p.add_argument("--json", action="store_true")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    kw = {"directory": args.dir, "root": Path(args.root).absolute() if args.root else None}

    def show(r):
        print(json.dumps(r, ensure_ascii=False, indent=2) if args.json else line_of(r), file=out)

    try:
        if args.cmd == "add":
            show(add(args.text, args.by, channel=args.channel, **kw))
            return 0
        if args.cmd == "list":
            rs = requests(args.status, **kw)
            if args.json:
                print(json.dumps(rs, ensure_ascii=False, indent=2), file=out)
            else:
                for r in rs:
                    print(line_of(r), file=out)
                if not rs:
                    print("просьб нет", file=out)
            return 0
        if args.cmd == "next":
            r = next(args.by, **kw)
            if r is None:
                print("null" if args.json else "открытых просьб нет", file=out)
                return 1
            show(r)
            return 0
        if args.cmd == "answer":
            r = answer(args.id, args.text, by=args.by, **kw)
        elif args.cmd == "close":
            r = close(args.id, by=args.by, **kw)
        elif args.cmd == "cancel":
            r = cancel(args.id, by=args.by, **kw)
        else:
            r = resend(args.id, **kw)
        show(r)
        if args.cmd in ("answer", "resend"):
            return 0 if (r.get("notify") or {}).get("status") == "sent" else 1
        return 0
    except RequestError as e:
        if getattr(args, "json", False):
            print(json.dumps({"refused": e.as_dict()}, ensure_ascii=False), file=out)
        else:
            print(f"отказ [{e.code}]: {e.text_ru}", file=out)
        bad_call = ("text_empty", "text_too_long", "answer_empty", "answer_too_long",
                    "by_missing", "context_invalid", "status_unknown")
        return 2 if e.code in bad_call else 1


if __name__ == "__main__":
    sys.exit(main())
