"""CC-0109: a test message to every delivery channel that is on - what
`python3 shared/notify.py test --send` does - plan -> confirm. Only through
the factory's own functions (`api/factory.py` `notify`, `shared/notify.py`):

    test_preview        CF-0700: the backends that are on, per backend `{name,
                        known, external, ready, skip_reason}` - the channels
                        of the plan (by name only)
    send_test           CF-0720: the probe of `test --send` - kind `test`, a
                        new key each run, the factory's text, the console
                        link, one journal row carrying `by` / `via`; with
                        `dry_run=True` (the plan) nothing sent, nothing
                        written, each backend `would send` or its `skipped:
                        ...`
    rows                the journal `notify/sent.jsonl` (the row's time)
    settings, mask_doc  the secrets of the settings, only to mask them
                        (`mask_secrets` over every string - the token, the
                        chat id, the webhook and ntfy URLs)

`api/notifications.py` (the journal, the reminders, the dry check) never
sends - `tests/test_cc_api_notify.py` walks its names; the one real send of
the API is here, in `test_send` only (`tests/test_cc_api_notify_send.py`
walks this file's names: `send_test` without `dry_run=True` only there).

**The plan** (`test_send_plan`): the channels that are on, by name (no
token, no chat id, no address - a `skip_reason` names the missing setting,
never a value), which of them send off this machine and are ready
(`outside`), the factory's dry run (`send_test(by, via, dry_run=True)`):
the text the probe will carry, per channel what it would do (`would`) and
whether that would reach the user; a confirm token (action
`notify_test_send`, 120 s, single use) bound to the channels as they are.
Nothing is sent, nothing written.

**The confirm** (`test_send`): the token spent, the channels read again - a
backend switched on or off, or an address added or gone since the plan, is
`check_changed`, nothing sent. Then `send_test(by="user", via="center")`
once - the factory's `send(by, via)`: who and from where on the journal
row; the answer per channel `{via, ok, detail}` (`detail` the bus's own
word - `ok`, `skipped: ...`, `error: ...`), `delivered` /
`delivery_reason`, the key and the journal row's time. Every string goes
out through the factory's `mask_doc` (`mask_secrets`) with the settings.

Every refusal is a `BatchFault` (`{message, code, details}`).
"""
from . import batches, factory
from .batches import BatchFault, _digest, _issue, _spend

ACTION = "notify_test_send"
KEY = "test"
ACTIONS = {ACTION: ("план пробного сообщения", "пробное сообщение не отправлено",
                    "пробного сообщения")}
batches.register_actions(ACTIONS)
WRITE_BY = "user"
WRITE_VIA = "center"
KEYS = ("name", "known", "external", "ready", "skip_reason")


def _nf():
    return factory.notify()


def _masker(nf, root):
    """The factory's own masking (`mask_doc` - `mask_secrets` over every
    string) with the settings of the root."""
    cfg = nf.settings(root)
    return lambda doc: nf.mask_doc(doc, cfg)


def _broken(e, what):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой: {what} - посмотрите "
                                             f"notify/ и .env, прежде чем повторять.",
                      [f"{type(e).__name__}: {e}"])


def _channels(nf, root):
    try:
        got = nf.test_preview(root)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "каналы доставки не прочитались") from e
    return [{k: b.get(k) for k in KEYS} for b in got]


def _facts(channels):
    return {"action": ACTION, "channels": channels, "by": WRITE_BY, "via": WRITE_VIA}


def _results(answers):
    return [{"via": name, "ok": str(v) == "ok", "detail": str(v)} for name, v in answers.items()]


def test_send_plan(root):
    """What a test send would reach (the channels by name, the factory's dry
    run), a confirm token - nothing sent."""
    nf = _nf()
    mask = _masker(nf, root)
    chans = mask(_channels(nf, root))
    try:
        dry = nf.send_test(root, by=WRITE_BY, via=WRITE_VIA, dry_run=True)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "сухой прогон пробного сообщения не составлен") from e
    fp = _digest(_facts(chans))
    outside = [c["name"] for c in chans if c["external"] and c["ready"]]
    note = None if outside else ("Ни один внешний канал не готов - сообщение увидят только "
                                 "локальные (журнал, лог).")
    would = [{"via": name, "ok": str(v) == nf.DRY_WOULD, "detail": str(v)}
             for name, v in (dry.get("backends") or {}).items()]
    out = mask({"action": ACTION, "ok": True, "why": None, "channels": chans,
                "names": [c["name"] for c in chans], "outside": outside, "note": note,
                "text": dry.get("text"), "would": would,
                "would_deliver": bool(dry.get("delivered")),
                "delivery_reason": dry.get("delivery_reason"), "by": WRITE_BY,
                "via": WRITE_VIA})
    # the token and the fingerprint are the API's own - not the bus's to scrub
    return dict(out, fingerprint=fp, confirm=_issue(root, ACTION, KEY, fp, {}),
                expires_in_s=int(batches.CONFIRM_TTL))


def test_send(root, token):
    """The confirmed test send: the token spent, the same channels as the
    plan's (else `check_changed`), then the factory's `send_test(by, via)`
    once - the answer per channel."""
    nf = _nf()
    got = _spend(root, ACTION, KEY, token)
    mask = _masker(nf, root)
    chans = mask(_channels(nf, root))
    if _digest(_facts(chans)) != got["fingerprint"]:
        raise BatchFault(409, "check_changed", "Каналы доставки изменились с момента плана - "
                                               "пробное сообщение не отправлено; посмотрите "
                                               "план заново.",
                         [f"channels now: {', '.join(c['name'] for c in chans) or '-'}"])
    try:
        res = nf.send_test(root, by=WRITE_BY, via=WRITE_VIA)
    except Exception as e:                                       # noqa: BLE001
        raise _broken(e, "пробное сообщение не отправлено") from e
    if res.get("status") == "error":
        raise BatchFault(500, "factory_broken", "Шина уведомлений не отправила пробное "
                                                "сообщение - посмотрите notify/.",
                         mask([f"notify.send: {res.get('error')}"]))
    if res.get("status") != "sent":
        raise BatchFault(409, "refused", "Шина уведомлений не отправила пробное сообщение: "
                                         "такой ключ уже в журнале.",
                         mask([f"notify.send: {res.get('status')} {res.get('key')}"]))
    row = next((r for r in reversed(nf.rows(root)) if r.get("key") == res.get("key")), {})
    return mask({"action": ACTION, "sent": True, "key": res.get("key"), "at": row.get("at"),
                 "text": row.get("text"), "results": _results(res.get("backends") or {}),
                 "delivered": bool(res.get("delivered")),
                 "delivery_reason": res.get("delivery_reason"),
                 "recorded_by": row.get("by") == WRITE_BY and row.get("via") == WRITE_VIA,
                 "by": WRITE_BY, "via": WRITE_VIA})
