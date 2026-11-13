#!/usr/bin/env python3
"""CF-0652: the journal of questions to the user - what was NEEDS-YOU.md.

Until 2.3 a question was a free-text line a script appended to Notebook
`Operator-Notes/NEEDS-YOU.md`: nothing could mark it answered or resolved,
and the command center (CC-0016/0017) could not show it. Now every question
is a row of this journal, in the root of the factory, written by one function
and read by the factory's state (shared/factory_state.py), the API of the center
(`GET /api/questions`) and the CLI below.

**Where.** `<root>/needs-you/questions.jsonl` (`NEEDS_YOU_DIR` puts the
default directory elsewhere - the test runners do; a caller that names a root
or a directory gets that one). It is **state, not code**:
gitignored, like `notify/` (CF-0591). It is written while a batch runs (the
token's reminder, the Analyst's refusal), and `batch-start` wants a
clean `main` - a tracked journal would make every question a dirty tree and a
commit nobody asked for. It lives in the checkout that runs the factory (the
production `main`); a release worktree has its own (empty) one.

**Format.** An append-only log of operations, one JSON object per line - the
shape of the reminders' queue (`shared/notify.py`, CF-0606):

    {"op": "add",     "id": "Q7", "key": K, "source": S, "channel": C|null,
                      "text": T, "link": L|null, "by": B, "at": ISO}
    {"op": "text",    "id": "Q7", "text": T, "at": ISO}    # the same event, reworded
    {"op": "suggest", "id": "Q7", "suggestion": S, "why": W|null, "by": B, "at": ISO}
    {"op": "answer",  "id": "Q7", "answer": A, "by": B, "at": ISO
                      [, "via": V] [, "accepted_suggestion": true]}
    {"op": "resolve", "id": "Q7", "note": N|null, "by": B, "at": ISO}

folded into the questions' state by `questions()`:

    {id, n, key, source, channel, text, link, created, created_by, updated,
     status (open | answered | resolved), suggestion, suggestion_why,
     suggested_by, suggested_at, answer, answered_by, answered_at,
     answered_via, accepted_suggestion, resolved_by, resolved_at, note}

**The suggested answer (CF-0703).** Whoever asks the user proposes the answer
they would give (the user, 12.10: the center shows it as the placeholder of
the answer field, with a way to apply it at once). `add(..., suggestion=S,
why=W)` writes a `suggest` op right after the `add`; `suggest(qid, S)` adds
or replaces it on a question not resolved yet. The user who takes it answers
with `accepted_suggestion=True` (the text may then be left out - it is the
suggestion), and `via` says where the answer came from (`center`, `telegram`,
`chat`). The new keys of an op are written only when given, so an `add`
without a suggestion and an `answer` without `via` are byte for byte the rows
they always were, and a journal written before reads as it did (the new
fields None / False). The rule and the shape for the askers: docs/needs-you.md.

Why a log and not one JSON document: a write is one appended line under the
lock - a crash mid-write cannot cut the file in half, two processes (a batch's
stage and the archive job) never overwrite each other's state, and who
answered what when is kept, not overwritten. Every write takes an exclusive
`flock` on `questions.lock` beside it; reads take nothing (a line is appended
whole).

**One question per event.** A question carries the key of its event (the
source's own: `oauth-token:<term>`,
`archive:publish-debt`, ...). `add` with a key that already has a question
not yet resolved returns that one - a changed text is written as a `text` op,
nothing else - so a script that runs every hour asks once. A key whose last
question was resolved asks again (the debt came back next month): a new
number.

**Telegram.** A question that is new goes once through the notification bus
(`shared/notify.py`, kind `needs_human`, key `needs-you:<id>`, link to the
console's `#needs-you`). A source that already tells the bus about its event
in its own words (the token, the Analyst) passes `notify=False`, so
the user's phone gets one message, not two. A notification is never on the
critical path: a bus that fails is said on stderr and the question stays.

    python3 shared/needs_you.py add --source S --key K --text T [--channel C]
                                    [--link L] [--by B] [--no-notify]
                                    [--suggest S [--why W]]
    python3 shared/needs_you.py suggest ID S [--why W] [--by B]
    python3 shared/needs_you.py list [--status live|open|answered|resolved|all]
                                     [--source S] [--channel C] [--json]
    python3 shared/needs_you.py answer ID [TEXT] [--by B] [--via V] [--accept]
    python3 shared/needs_you.py resolve (ID | --key K | --key-prefix P) [--note N] [--by B]
        # every command takes --dir DIR (the journal's directory)
        # exit 0 done, 1 nothing to do (no such question, already resolved), 2 bad call
"""
import argparse
import fcntl
import json
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0652"
ROOT = Path(__file__).resolve().parent.parent
DIR_ENV = "NEEDS_YOU_DIR"
DIRNAME = "needs-you"
JOURNAL = "questions.jsonl"
LOCK = "questions.lock"
STATUSES = ("open", "answered", "resolved")
LIVE = ("open", "answered")
TEXT_MAX = 2000
WHO_MAX = 40                # CF-0703: `by` / `via` of a new op (notify.WHO_MAX)
PUSH_SUGGESTION_MAX = 300   # CF-0703: the suggestion in the Telegram message
SUGGESTED_BY = "claude"     # CF-0703: who suggests when `suggest()` is not told
NOTIFY_KIND = "needs_human"
CONSOLE_ANCHOR = "needs-you"


class QuestionError(ValueError):
    """No such question, or it cannot take this step."""


# ------------------------------------------------------------------ where
def journal_dir(root=None, environ=None, directory=None):
    """`directory`, else `<root>/needs-you` of a root given (a caller that
    names its factory root - a temp one in tests - gets that factory's
    journal), else `NEEDS_YOU_DIR`, else `<this checkout>/needs-you`. The test
    runners set `NEEDS_YOU_DIR`, so a test that forgets both never writes the
    live journal."""
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


def _clean(text, limit=TEXT_MAX):
    text = " ".join(str(text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def _who(value, what):
    """CF-0703 (the shape of CF-0700's `notify._who`): `by` / `via` - None
    (not given) or a short non-empty single-line string; anything else is a
    QuestionError and nothing is written."""
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise QuestionError(f"{what}={value!r}: a short non-empty string (e.g. by='user', "
                            f"via='center') or not given at all")
    value = value.strip()
    if len(value) > WHO_MAX or any(c in value for c in "\r\n\t"):
        raise QuestionError(f"{what}={value!r}: at most {WHO_MAX} characters on one line")
    return value


def _suggest_op(qid, suggestion, why, by, at):
    return {"op": "suggest", "id": qid, "suggestion": suggestion, "why": why or None,
            "by": by, "at": at}


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


def _number(qid):
    m = re.match(r"^Q(\d+)$", str(qid or ""))
    return int(m.group(1)) if m else 0


def _channel_ids():
    """shared/channel_ids.py, beside this file."""
    shared = str(Path(__file__).resolve().parent)
    if shared not in sys.path:
        sys.path.append(shared)
    import channel_ids                                          # noqa: PLC0415
    return channel_ids


def _fold(ops, root=None):
    """The questions' state. The journal is a dated record: a question asked
    before a channel was renamed carries the former id, so the channel is
    resolved here, where it is read (`channel_ids.resolve_channel`, CF-0197) -
    every question handed out names the channel by its current id."""
    ids = _channel_ids()
    by_id = {}
    for op in ops:
        qid, kind = op["id"], op.get("op")
        if kind == "add":
            if qid in by_id:
                continue
            by_id[qid] = {"id": qid, "n": _number(qid), "key": op.get("key"),
                          "source": op.get("source"),
                          "channel": ids.resolve_channel(op.get("channel"), root),
                          "text": op.get("text"), "link": op.get("link"),
                          "created": op.get("at"), "created_by": op.get("by"),
                          "updated": op.get("at"), "status": "open",
                          "suggestion": None, "suggestion_why": None, "suggested_by": None,
                          "suggested_at": None, "answer": None,
                          "answered_by": None, "answered_at": None, "answered_via": None,
                          "accepted_suggestion": False, "resolved_by": None,
                          "resolved_at": None, "note": None}
            continue
        q = by_id.get(qid)
        if q is None or q["status"] == "resolved":
            continue
        q["updated"] = op.get("at")
        if kind == "text":
            q["text"] = op.get("text")
        elif kind == "suggest":
            q.update(suggestion=op.get("suggestion"), suggestion_why=op.get("why"),
                     suggested_by=op.get("by"), suggested_at=op.get("at"))
        elif kind == "answer":
            q.update(status="answered", answer=op.get("answer"), answered_by=op.get("by"),
                     answered_at=op.get("at"), answered_via=op.get("via"),
                     accepted_suggestion=op.get("accepted_suggestion") is True)
        elif kind == "resolve":
            q.update(status="resolved", resolved_by=op.get("by"), resolved_at=op.get("at"),
                     note=op.get("note"))
    return sorted(by_id.values(), key=lambda q: q["n"])


# ------------------------------------------------------------------ read
def questions(root=None, status=None, source=None, channel=None, environ=None, directory=None):
    """Every question, oldest first. `status`: one of STATUSES, `live` (open +
    answered), a tuple of them, or None / `all`."""
    qs = _fold(_ops(journal_dir(root, environ, directory)), root)
    if status in ("live",):
        status = LIVE
    if status and status != "all":
        want = (status,) if isinstance(status, str) else tuple(status)
        qs = [q for q in qs if q["status"] in want]
    if source:
        qs = [q for q in qs if q["source"] == source]
    if channel:
        channel = _channel_ids().resolve_channel(channel, root)
        qs = [q for q in qs if q["channel"] == channel]
    return qs


def live(root=None, environ=None, directory=None, **kw):
    """The questions still waiting (open or answered but not resolved)."""
    return questions(root, "live", environ=environ, directory=directory, **kw)


def get(qid, root=None, environ=None, directory=None):
    qid = str(qid or "").strip().upper()
    return next((q for q in questions(root, environ=environ, directory=directory)
                 if q["id"] == qid), None)


# ------------------------------------------------------------------ write
def push_text(q):
    """The Telegram message of a new question; CF-0703: with the suggested
    answer, short, when there is one (one line - the bus keeps one)."""
    text = f"Вопрос {q['id']}: {q['text']}"
    if q.get("suggestion"):
        text += f" — предлагаю: {_clean(q['suggestion'], PUSH_SUGGESTION_MAX)}"
    return text


def _push(q, root=None, environ=None, backends=None):
    """The bus of CF-0591, one notification per question. Never raises."""
    try:
        shared = str(Path(__file__).resolve().parent)
        if shared not in sys.path:
            sys.path.append(shared)
        import notify as bus                                    # noqa: PLC0415
        return bus.send(NOTIFY_KIND, f"needs-you:{q['id']}", push_text(q),
                        channel=q["channel"],         # resolved by _fold
                        link=q.get("link") or bus.link_of(None, CONSOLE_ANCHOR),
                        root=root, environ=environ, backends=backends)
    except Exception as e:                                      # noqa: BLE001
        print(f"NEEDS-YOU notify: {e.__class__.__name__}: {e} - the question stays",
              file=sys.stderr)
        return {"status": "error", "error": str(e)}


def add(source, key, text, channel=None, link=None, by=None, root=None, now=None,
        notify=True, notifier=None, environ=None, directory=None, suggestion=None, why=None):
    """Ask once per event. `(question, created)`: a question of this key that
    is not resolved yet is returned as it is (`created` False; a new wording
    is written as a `text` op, a new suggestion as a `suggest` op). A new one
    goes to the bus once (`notify`; `notifier(q)` replaces the bus - tests).

    CF-0703: `suggestion` (and its `why`) - the answer the asker recommends,
    written as a `suggest` op by the asker (`by`, else `source`) right after
    the `add`; without it the journal gets exactly the rows it always got."""
    by = _who(by, "by") if by else None      # an empty by is the source, as it always was
    source = _clean(source, 80)
    key = _clean(key, 300)
    text = _clean(text)
    suggestion = _clean(suggestion) or None
    why = _clean(why) or None
    if not source or not key or not text:
        raise QuestionError("a question needs a source, a key and a text")
    if why and not suggestion:
        raise QuestionError("a why needs a suggestion")
    d = journal_dir(root, environ, directory)
    at = now_iso(now)
    with _locked(d):
        ops = _ops(d)
        have = next((q for q in _fold(ops, root) if q["key"] == key and q["status"] in LIVE), None)
        if have is not None:
            if have["text"] != text:
                _append(d, {"op": "text", "id": have["id"], "text": text, "at": at})
                have = dict(have, text=text, updated=at)
            if suggestion and (suggestion, why) != (have["suggestion"], have["suggestion_why"]):
                s_by = _who((by or source)[:WHO_MAX], "by")
                _append(d, _suggest_op(have["id"], suggestion, why, s_by, at))
                have = dict(have, suggestion=suggestion, suggestion_why=why, suggested_by=s_by,
                            suggested_at=at, updated=at)
            return have, False
        qid = f"Q{max([_number(o['id']) for o in ops] + [0]) + 1}"
        op = {"op": "add", "id": qid, "key": key, "source": source, "channel": channel or None,
              "text": text, "link": link or None, "by": by or source, "at": at}
        _append(d, op)
        if suggestion:
            _append(d, _suggest_op(qid, suggestion, why, _who((by or source)[:WHO_MAX], "by"),
                                   at))
    q = next(q for q in _fold(_ops(d), root) if q["id"] == qid)
    if notify:
        try:
            (notifier or (lambda x: _push(x, root=root, environ=environ)))(q)
        except Exception as e:                                  # noqa: BLE001
            print(f"NEEDS-YOU notify: {e.__class__.__name__}: {e} - the question stays",
                  file=sys.stderr)
    return q, True


def suggest(qid, suggestion, why=None, by=SUGGESTED_BY, root=None, now=None, environ=None,
            directory=None):
    """CF-0703: the answer recommended to the user - added to, or replacing
    the one of, a question not resolved yet (open or answered). A resolved or
    unknown question raises QuestionError."""
    by = _who(by, "by") or SUGGESTED_BY
    qid = str(qid or "").strip().upper()
    suggestion = _clean(suggestion)
    why = _clean(why) or None
    if not suggestion:
        raise QuestionError("a suggestion needs a text")
    d = journal_dir(root, environ, directory)
    with _locked(d):
        q = next((q for q in _fold(_ops(d), root) if q["id"] == qid), None)
        if q is None:
            raise QuestionError(f"no question {qid}")
        if q["status"] == "resolved":
            raise QuestionError(f"question {qid} is already resolved")
        at = now_iso(now)
        _append(d, _suggest_op(qid, suggestion, why, by, at))
    return dict(q, suggestion=suggestion, suggestion_why=why, suggested_by=by, suggested_at=at,
                updated=at)


def answer(qid, text, by="user", root=None, now=None, environ=None, directory=None, via=None,
           accepted_suggestion=False):
    """The user's answer: open/answered -> answered (a second answer replaces
    the first). A resolved question takes none.

    CF-0703: `via` (where the answer came from - `center`, `telegram`, ...)
    and `accepted_suggestion` (the user took the suggested answer; the text,
    when left out, is the suggestion) go into the op only when given / true,
    so an answer without them is byte for byte the row it always was. `by`
    and `via` are checked (`_who`) before anything is written."""
    by, via = (_who(by, "by") if by else None) or "user", _who(via, "via")
    accepted = accepted_suggestion is True
    if accepted_suggestion not in (True, False, None):
        raise QuestionError(f"accepted_suggestion={accepted_suggestion!r}: true or false")
    qid = str(qid or "").strip().upper()
    text = _clean(text)
    if not text and not accepted:
        raise QuestionError("an answer needs a text")
    d = journal_dir(root, environ, directory)
    with _locked(d):
        q = next((q for q in _fold(_ops(d), root) if q["id"] == qid), None)
        if q is None:
            raise QuestionError(f"no question {qid}")
        if q["status"] == "resolved":
            raise QuestionError(f"question {qid} is already resolved")
        if accepted and not q["suggestion"]:
            raise QuestionError(f"question {qid} has no suggestion to accept")
        text = text or q["suggestion"]
        at = now_iso(now)
        op = {"op": "answer", "id": qid, "answer": text, "by": by, "at": at}
        if via is not None:
            op["via"] = via
        if accepted:
            op["accepted_suggestion"] = True
        _append(d, op)
    return dict(q, status="answered", answer=text, answered_by=by, answered_at=at,
                answered_via=via, accepted_suggestion=accepted, updated=at)


def resolve(qid=None, key=None, key_prefix=None, by="user", note=None, root=None, now=None,
            environ=None, directory=None, keep=None):
    """Mark resolved: one question by `qid` (a resolved or unknown one raises
    QuestionError), or every live question whose key is `key` / starts with
    `key_prefix` (none is not an error; `keep` - a key spared, the source's
    current one). Returns the questions resolved."""
    if not (qid or key or key_prefix):
        raise QuestionError("resolve what: an id, --key or --key-prefix")
    d = journal_dir(root, environ, directory)
    at = now_iso(now)
    done = []
    with _locked(d):
        qs = _fold(_ops(d), root)
        if qid:
            qid = str(qid).strip().upper()
            q = next((q for q in qs if q["id"] == qid), None)
            if q is None:
                raise QuestionError(f"no question {qid}")
            if q["status"] == "resolved":
                raise QuestionError(f"question {qid} is already resolved")
            todo = [q]
        else:
            todo = [q for q in qs if q["status"] in LIVE and q["key"] != keep
                    and ((key is not None and q["key"] == key)
                         or (key_prefix is not None and str(q["key"]).startswith(key_prefix)))]
        for q in todo:
            _append(d, {"op": "resolve", "id": q["id"], "note": _clean(note) or None,
                        "by": by or "user", "at": at})
            done.append(dict(q, status="resolved", resolved_by=by or "user", resolved_at=at,
                             note=_clean(note) or None, updated=at))
    return done


# ------------------------------------------------------------------ the CLI
def line_of(q):
    ch = f" [{q['channel']}]" if q["channel"] else ""
    tail = ""
    if q["status"] == "open" and q.get("suggestion"):
        tail = f" -> предложение ({q.get('suggested_by')}): {q['suggestion']}"
    elif q["status"] == "answered":
        tail = f" -> ответ ({q.get('answered_by')}, {q.get('answered_at')}): {q.get('answer')}"
        if q.get("accepted_suggestion"):
            tail += " [принято предложение]"
    elif q["status"] == "resolved":
        tail = f" -> решено ({q.get('resolved_by')}, {q.get('resolved_at')})" + \
            (f": {q['note']}" if q.get("note") else "")
    return f"{q['id']} {q['status']:<8} {q['created']} {q['source']}{ch}: {q['text']}{tail}"


def main(argv=None, out=sys.stdout):
    ap = argparse.ArgumentParser(description="CF-0652: the journal of questions to the user",
                                 allow_abbrev=False)
    ap.add_argument("--dir", help=f"the journal's directory (default ${DIR_ENV}, "
                                  f"else <root>/{DIRNAME})")
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("add", help="ask (once per --key)")
    a.add_argument("--source", required=True)
    a.add_argument("--key", required=True)
    a.add_argument("--text", required=True)
    a.add_argument("--channel")
    a.add_argument("--link")
    a.add_argument("--by")
    a.add_argument("--no-notify", action="store_true", help="do not tell the bus")
    a.add_argument("--suggest", help="the answer you recommend (CF-0703)")
    a.add_argument("--why", help="why that answer (with --suggest)")
    sg = sub.add_parser("suggest", help="add or replace the recommended answer (CF-0703)")
    sg.add_argument("id")
    sg.add_argument("suggestion")
    sg.add_argument("--why")
    sg.add_argument("--by", default=SUGGESTED_BY)
    ls = sub.add_parser("list", help="the questions")
    ls.add_argument("--status", default="live",
                    choices=("live", "all") + STATUSES)
    ls.add_argument("--source")
    ls.add_argument("--channel")
    ls.add_argument("--json", action="store_true")
    an = sub.add_parser("answer", help="the user's answer")
    an.add_argument("id")
    an.add_argument("text", nargs="?", help="the answer (left out with --accept: the suggestion)")
    an.add_argument("--by", default="user")
    an.add_argument("--via", help="where the answer came from (center, telegram, chat)")
    an.add_argument("--accept", action="store_true", help="the user took the suggestion")
    rs = sub.add_parser("resolve", help="mark resolved")
    rs.add_argument("id", nargs="?")
    rs.add_argument("--key")
    rs.add_argument("--key-prefix")
    rs.add_argument("--note")
    rs.add_argument("--by", default="user")
    try:
        args = ap.parse_args(argv)
    except SystemExit as e:
        return 2 if e.code else 0
    d = args.dir
    try:
        if args.cmd == "add":
            q, created = add(args.source, args.key, args.text, channel=args.channel,
                             link=args.link, by=args.by, notify=not args.no_notify, directory=d,
                             suggestion=args.suggest, why=args.why)
            print(("new " if created else "already asked ") + line_of(q), file=out)
            return 0
        if args.cmd == "suggest":
            print(line_of(suggest(args.id, args.suggestion, why=args.why, by=args.by,
                                  directory=d)), file=out)
            return 0
        if args.cmd == "list":
            qs = questions(status=args.status, source=args.source, channel=args.channel,
                           directory=d)
            if args.json:
                print(json.dumps(qs, ensure_ascii=False, indent=2), file=out)
            else:
                for q in qs:
                    print(line_of(q), file=out)
                if not qs:
                    print("вопросов нет", file=out)
            return 0
        if args.cmd == "answer":
            print(line_of(answer(args.id, args.text, by=args.by, directory=d, via=args.via,
                                 accepted_suggestion=args.accept)), file=out)
            return 0
        if args.cmd == "resolve":
            if not (args.id or args.key or args.key_prefix):
                print("resolve: an id, --key or --key-prefix", file=out)
                return 2
            done = resolve(args.id, key=args.key, key_prefix=args.key_prefix, by=args.by,
                           note=args.note, directory=d)
            for q in done:
                print(line_of(q), file=out)
            return 0 if done else 1
    except QuestionError as e:
        print(f"needs-you: {e}", file=out)
        bad_call = ("a question needs", "needs a text", "needs a suggestion", "characters on one",
                    "short non-empty", "accepted_suggestion=")
        return 2 if any(b in str(e) for b in bad_call) else 1
    return 2


if __name__ == "__main__":
    sys.exit(main())
