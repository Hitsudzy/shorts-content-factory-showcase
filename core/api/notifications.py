"""CC-0026: the notifications and the user's reminders - the journal of what
the bus sent, the reminders, a check of the backends, and queueing a
reminder. Only through the factory's own functions (`api/factory.py`
`notify`, `shared/notify.py`), nothing of the API's own on top:

    rows                the journal `notify/sent.jsonl` (CF-0591) - what
                        `notify.py list` prints; every row's `link` through
                        `center_link` (CF-0735, CC-0035: an old row's
                        `8790/#anchor` of the retired console, or its
                        `8791/<route>` of the center before it moved, as
                        the center's route)
    reminders, msk_text the reminders queue `notify/reminders.jsonl` (CF-0606,
                        CF-0617) - what `notify.py remind --list [--all]` prints
    main(["test"])      the CLI's dry `test`: which backends are on and what
                        each would get - a stand-in, nothing is sent, the
                        journal is untouched (its lines, kept for 0.27.0)
    test_preview        CF-0700: the same check as data, per backend
                        `{name, known, external, ready, skip_reason, would_get}`
    parse_when, one_line  the plan of a reminder: its time (Moscow -> UTC) and
                        its text as the queue would hold them, nothing written
    add_reminder(by, via)  the confirmed reminder, by `user` via `center`
                        (nothing is sent now: it goes at its time, `remind
                        --due` / the tick)
    cancel_reminder(by, via)  CC-0081: the confirmed cancel of one reminder
                        still to go, by `user` via `center`
    settings, mask_token  the Telegram bot token, only to mask it

**Never called**: `send`, `send_due` (sending is the bus's and the tick's) and
`test --send` (a real message to every backend that is on).
`cancel_reminder` is called only in the cancel's confirm (`reminder_cancel`).
`tests/test_cc_api_notify.py` walks this file's names.

**No secret leaves**: every string of a journal row, a reminder and the
check's lines goes through `notify.mask_token` with the Telegram bot token of
the factory's settings (the token itself is never returned); the factory
already scrubs what it writes, this is the second line.

**The plan** (`reminder_plan`): `parse_when(at, now)` and `one_line(text,
REMINDER_TEXT_MAX)` - the due time in UTC and in Moscow (`msk_text`) and the
text as the queue would hold them; a time the factory refuses is 422
`bad_time` (its line in `details`), an empty text 422 `no_text`. Whether a
reminder will be new or the same one already queued (the same text at the same
time) the factory says only by writing - the confirm's `created`. A confirm
token (`batches` store, action `notify_reminder_add`, 120 s, single use) is
bound to `at` and `text`.

**The confirm** (`reminder_add`): the token spent, the plan again at the same
clock as the write; a due time that is not the plan's (an «ЧЧ:ММ» that rolled
to tomorrow meanwhile) is `check_changed`, nothing written. Then
`add_reminder(at, text, now, by="user", via="center")`.

**The cancel** (CC-0081, `reminder_cancel_plan`, `reminder_cancel`): the plan
reads `reminders()` - a reminder not in the queue is 404 `no_reminder`, one
already sent or cancelled 409 `not_cancellable` - and gives the reminder, its
state and what a cancel means, with a confirm token (action
`notify_reminder_cancel`, key the reminder's id) bound to the row as it is.
The confirm spends it, reads the row again (a try, a delivery or a cancel in
between is `check_changed`), then `cancel_reminder(rid, now, by="user",
via="center")` and returns its `cancelled_at` / `cancelled_by` /
`cancelled_via`.

Every refusal is a `BatchFault` (`{message, code, details}`). `FACTORY_KW`
holds the factory's clock (`now`) - empty in production; the tests put a fixed
one there.
"""
import io
from pathlib import Path

from . import batches, factory, paths
from .batches import BatchFault, _digest, _issue, _spend

ACTION = "notify_reminder_add"
#: CC-0081: the cancel of one reminder - its token's key is the reminder's id.
CANCEL = "notify_reminder_cancel"
#: The token's key: the reminders queue is the factory's, not a channel's.
KEY = "reminders"
ACTIONS = {ACTION: ("план напоминания", "напоминание не поставлено", "напоминания"),
           CANCEL: ("план отмены напоминания", "напоминание не отменено",
                    "отмены напоминания")}
batches.register_actions(ACTIONS)
#: Who the center writes and from where (`publish.WRITE_BY`, CF-0700's `via`).
WRITE_BY = "user"
WRITE_VIA = "center"
#: The factory's own injection points - empty in production.
FACTORY_KW = {}


def _nf():
    return factory.notify()


def _rel(root, p):
    """CC-0097: relative to the root, `.../<its last part>` outside it - never
    the absolute path (`api/paths.py`)."""
    return paths.rel(root, p)


def _masker(nf, root):
    """`mask_token` with the factory's Telegram bot token, over a document."""
    token = nf.settings(root).get("NOTIFY_TELEGRAM_TOKEN")

    def mask(doc):
        if isinstance(doc, str):
            return nf.mask_token(doc, token)
        if isinstance(doc, dict):
            return {k: mask(v) for k, v in doc.items()}
        if isinstance(doc, list):
            return [mask(v) for v in doc]
        return doc
    return mask


def _broken(e, what):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой: {what} - посмотрите "
                                             f"notify/, прежде чем повторять.",
                      [f"{type(e).__name__}: {e}"])


# ---------------------------------------------------------------- the journal
def journal(root, kind=None, channel=None, limit=20):
    """`notify.py list [--kind] [--channel] [--limit]`: the journal's rows,
    newest last; `limit` 0 - every one."""
    nf = _nf()
    if kind and kind not in nf.KINDS:
        raise BatchFault(422, "bad_kind", f"Нет такого вида уведомлений: «{kind}».",
                         [f"kind {kind!r}: one of {', '.join(nf.KINDS)}"])
    mask = _masker(nf, root)
    got = [r for r in nf.rows(root) if (not kind or r.get("kind") == kind)
           and (not channel or r.get("channel") == channel)]
    shown = got[-limit:] if limit and limit > 0 else got
    # CF-0735, CC-0035: an old row's console anchor or 8791 link as the center's route
    shown = [dict(r, link=nf.center_link(r["link"])) if r.get("link") else r for r in shown]
    return {"path": _rel(root, nf.journal_path(root)), "kinds": list(nf.KINDS),
            "total": len(got), "events": mask(shown)}


# ---------------------------------------------------------------- the reminders
def _reminder(nf, r):
    """A row of `notify.reminders()` with its Moscow time; CF-0700's `via`,
    `cancelled_by`, `cancelled_via` always present (None on the rows written
    before it, and on a CLI add / cancel)."""
    out = {"via": None, "cancelled_by": None, "cancelled_via": None}
    out.update(r, due_msk=nf.msk_text(r.get("due")))
    return out


def reminders(root, all_rows=False):
    """`notify.py remind --list [--all]`: the ones still to go or not
    delivered (every one with `all`), oldest first."""
    nf = _nf()
    mask = _masker(nf, root)
    got = nf.reminders(root)
    shown = got if all_rows else [r for r in got if r["status"] not in ("sent", "cancelled")]
    return {"path": _rel(root, nf.reminders_path(root)), "all": bool(all_rows),
            "max_attempts": nf.REMINDER_MAX_ATTEMPTS,
            "reminders": mask([_reminder(nf, r) for r in shown])}


# ---------------------------------------------------------------- the check
def check(root):
    """`notify.py test` (without --send): the backends that are on, CF-0700's
    `test_preview` per backend (`preview`) and the CLI's lines (kept for the
    clients of 0.27.0) - what each would get, through a stand-in."""
    nf = _nf()
    mask = _masker(nf, root)
    buf = io.StringIO()
    try:
        code = nf.main(["test", "--root", str(root)], out=buf)
        preview = nf.test_preview(root)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "проверка уведомлений не прошла") from e
    lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
    if code != 0:
        raise BatchFault(500, "factory_broken", "Проверка уведомлений фабрики не прошла.",
                         mask([f"notify.py test: exit {code}", *lines]))
    on = nf.enabled(root)
    keys = ("name", "known", "external", "ready", "skip_reason", "would_get")
    return {"backends": on, "default": list(nf.DEFAULT_BACKENDS),
            "external": [b for b in on if b in nf.EXTERNAL],
            "preview": mask([{k: b.get(k) for k in keys} for b in preview]),
            "lines": mask(lines), "sent": False}


# ---------------------------------------------------------------- queue a reminder
def _now(nf):
    """The one clock of a plan or a write: the factory's `now` (tests) or now."""
    return FACTORY_KW.get("now") or nf._utc_iso(nf._utc())


def _plan(nf, at, text, now):
    """(due UTC ISO, text): `parse_when` and `one_line` - nothing written."""
    try:
        due = nf._utc_iso(nf.parse_when(at, now))
    except ValueError as e:
        raise BatchFault(422, "bad_time", f"Время «{at}» не подходит: нужно «ЧЧ:ММ» или "
                                          f"«ГГГГ-ММ-ДД ЧЧ:ММ» по Москве, не в прошлом.",
                         [str(e)]) from e
    line = nf.one_line(text, nf.REMINDER_TEXT_MAX)
    if not line:
        raise BatchFault(422, "no_text", "Напишите, о чём напомнить.",
                         ["a reminder needs a text"])
    return due, line


def _facts(due, line):
    return {"action": ACTION, "due": due, "text": line, "by": WRITE_BY, "via": WRITE_VIA}


def reminder_plan(root, at, text):
    """What «напомнить» would queue (its time, its text) and a confirm token
    bound to `at` and `text` - nothing written."""
    nf = _nf()
    now = _now(nf)
    due, line = _plan(nf, at, text, now)
    fp = _digest(_facts(due, line))
    return {"action": ACTION, "ok": True, "why": None, "at": at, "due": due,
            "due_msk": nf.msk_text(due), "text": _masker(nf, root)(line), "by": WRITE_BY,
            "via": WRITE_VIA, "now": now, "fingerprint": fp, "confirm": _issue(root, ACTION, KEY, fp,
                                                              {"at": at, "text": text}),
            "expires_in_s": int(batches.CONFIRM_TTL)}


def reminder_add(root, token):
    """The confirmed reminder: the token spent, the same due time and text as
    the plan's (else `check_changed`), then `add_reminder(by=user)`."""
    nf = _nf()
    got = _spend(root, ACTION, KEY, token)
    at, text = got["bound"]["at"], got["bound"]["text"]
    now = _now(nf)
    due, line = _plan(nf, at, text, now)
    if _digest(_facts(due, line)) != got["fingerprint"]:
        raise BatchFault(409, "check_changed", "Время напоминания изменилось с момента плана - "
                                               "напоминание не поставлено; посмотрите план "
                                               "заново.",
                         [f"due {due} differs from the plan's for --at {at!r}"])
    try:
        r, created = nf.add_reminder(at, text, root=root, now=now, by=WRITE_BY, via=WRITE_VIA)
    except ValueError as e:
        raise BatchFault(422, "refused", f"Фабрика не поставила напоминание: {e}",
                         [f"ValueError: {e}"]) from e
    except OSError as e:
        raise _broken(e, "напоминание не записано") from e
    return {"action": ACTION, "written": True, "created": bool(created), "by": WRITE_BY,
            "via": WRITE_VIA, "reminder": _masker(nf, root)(_reminder(nf, r))}


# ---------------------------------------------------------------- cancel a reminder
#: The statuses `cancel_reminder` takes (the others are `sent`, `cancelled`).
CANCELLABLE = ("pending", "failed", "exhausted")
CANCEL_MEANS = ("Напоминание не уйдёт: тик и `remind --due` его больше не отправят, "
                "повторов не будет. В очереди оно остаётся отменённым (кем и откуда - "
                "user, center); вернуть его - поставить заново.")


def _rid(rid):
    """The id as `cancel_reminder` reads it (`R<n>`, any case, spaces cut)."""
    return str(rid or "").strip().upper()


def _cancellable(nf, root, rid):
    """The reminder `rid` still to go - else 404 `no_reminder` / 409
    `not_cancellable`."""
    got = {r["id"]: r for r in nf.reminders(root)}
    if rid not in got:
        raise BatchFault(404, "no_reminder", f"Напоминания {rid or '(пусто)'} нет в очереди.",
                         [f"no reminder {rid!r} in notify/reminders.jsonl"])
    r = got[rid]
    if r["status"] not in CANCELLABLE:
        word = {"sent": "уже отправлено", "cancelled": "уже отменено"}.get(r["status"],
                                                                            r["status"])
        raise BatchFault(409, "not_cancellable", f"Напоминание {rid} {word} - отменять нечего.",
                         [f"reminder {rid} is {r['status']}; cancellable: "
                          f"{', '.join(CANCELLABLE)}"])
    return r


def _cancel_facts(r):
    return {"action": CANCEL, "reminder": r, "by": WRITE_BY, "via": WRITE_VIA}


def reminder_cancel_plan(root, rid):
    """What cancelling `rid` would do (the reminder, its state, what a cancel
    means) and a confirm token bound to the reminder as it is - nothing
    written."""
    nf = _nf()
    rid = _rid(rid)
    r = _cancellable(nf, root, rid)
    fp = _digest(_cancel_facts(r))
    return {"action": CANCEL, "ok": True, "why": None, "id": rid, "status": r["status"],
            "means": CANCEL_MEANS, "reminder": _masker(nf, root)(_reminder(nf, r)),
            "by": WRITE_BY, "via": WRITE_VIA, "fingerprint": fp,
            "confirm": _issue(root, CANCEL, rid, fp, {"id": rid}),
            "expires_in_s": int(batches.CONFIRM_TTL)}


def reminder_cancel(root, rid, token):
    """The confirmed cancel: the token of this reminder spent, the reminder the
    same as in the plan (a try, a delivery or a cancel meanwhile is
    `check_changed`), then `cancel_reminder(by=user, via=center)`."""
    nf = _nf()
    rid = _rid(rid)
    got = _spend(root, CANCEL, rid, token)
    r = _cancellable(nf, root, rid)
    if _digest(_cancel_facts(r)) != got["fingerprint"]:
        raise BatchFault(409, "check_changed", "Напоминание изменилось с момента плана - "
                                               "оно не отменено; посмотрите план заново.",
                         [f"reminder {rid} differs from the plan's (status now "
                          f"{r['status']}, attempts {r.get('attempts')})"])
    try:
        done = nf.cancel_reminder(rid, root=root, now=_now(nf), by=WRITE_BY, via=WRITE_VIA)
    except ValueError as e:
        raise BatchFault(409, "refused", f"Фабрика не отменила напоминание: {e}",
                         [f"ValueError: {e}"]) from e
    except OSError as e:
        raise _broken(e, "отмена не записана") from e
    return {"action": CANCEL, "written": True, "by": WRITE_BY, "via": WRITE_VIA,
            "cancelled_at": done.get("cancelled_at"), "cancelled_by": done.get("cancelled_by"),
            "cancelled_via": done.get("cancelled_via"),
            "reminder": _masker(nf, root)(_reminder(nf, done))}
