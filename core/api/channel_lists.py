"""CC-0114 (the CC-0102 remainder): the user's edit of a channel's own lists
from the center - two steps each, only through the factory's checked writers
(CF-0726), nothing of the API's own on top:

    shared/channel_list_write.py      write_fact_sources, write_footage_origin
                                      (the common write_list: by/via, the
                                      list's schema, no batch of the channel
                                      open, base_sha256, the one lock
                                      channels/.lists.lock, an atomic write
                                      committed alone); list_sha256 (the base)
    shared/affiliate.py               write_table - the same write

The reads are `api/rights.py`'s GETs (each carries the file's `sha256`,
the base a plan is made from).

**The plan** (`plan`): the factory's own writer with `dry_run=True`, by
"user" via "center" - nothing written, no lock taken: `ok`, the file's
`sha256` now, the `new_sha256` that would be written, `refusals [{code, line,
message}]` (the factory's code and line, the center's Russian message) and
the writer's `lines`. A confirm token (`batches` store, 120 s, single use;
actions `fact_sources_write`, `footage_origin_write`, `affiliate_write`) is bound to the document and `base_sha256` - only
when the dry run is ok and the document is not the file already.

**The confirm** (`write`): one channel-list write of the center at a time;
the token spent; then the same writer for real with the plan's `base_sha256`
(`commit=True` - one commit of exactly this file). The factory checks the
base again under its lock: a file that moved since the plan is its
`check_changed` - «список изменился, откройте заново», nothing written. Any
refusal is a problem `{message, code, details}`: the code the factory's, the
message Russian, the details its lines (no absolute path - `paths.clean`).

`FACTORY_KW` holds the factory's injection points (`now`, `open_rows`) -
empty in production; the tests put a fixed clock and open batches there.
"""
import threading

from . import batches, factory, paths
from .batches import BatchFault, _channel, _digest, _issue, _spend

#: Who and where the center writes (CF-0726's by/via).
WRITE_BY, VIA = "user", "center"
#: How long a confirm waits for the factory's lock of the channel lists.
LOCK_WAIT = 15.0
#: One channel-list write of the center at a time; how long the next waits.
_WRITE = threading.Lock()
WRITE_WAIT = 30.0
#: The factory's own injection points - empty in production.
FACTORY_KW = {}

#: list -> (confirm action, its words for the token store, what the body carries)
LISTS = {
    "fact-sources": ("fact_sources_write", "источников фактов", "doc"),
    "footage-origin": ("footage_origin_write", "списка происхождения футажа", "doc"),
    "affiliate": ("affiliate_write", "таблицы партнёрских ссылок", "doc"),
}
ACTIONS = {a: (f"план записи {w}", "список не записан", f"записи {w} канала")
           for a, w, _ in LISTS.values()}
batches.register_actions(ACTIONS)

#: The factory's refusal code -> (HTTP status, the center's Russian message).
REFUSALS = {
    "unknown_channel": (404, "Канала нет в фабрике - список не записан."),
    "unknown_list": (500, "Фабрика не знает такого списка канала - это ошибка центра."),
    "bad_who": (500, "Центр подписал запись неверно (by/via) - это ошибка центра, список не "
                     "записан."),
    "invalid": (422, "Список не прошёл проверку фабрики - ничего не записано; исправьте "
                     "строки из подробностей."),
    "batch_open": (409, "Идёт батч канала - его списки не пишутся, пока батч работает; "
                        "повторите после него."),
    "check_changed": (409, "Список изменился, откройте заново - ничего не записано."),
    "locked": (409, "Списки каналов сейчас пишет кто-то другой (другая запись) - подождите и повторите."),
    "not_repo": (409, "Корень фабрики - не git-репозиторий: список не закоммитить, ничего не "
                      "записано."),
    "commit_refused": (409, "Git не принял коммит списка - файл возвращён как был."),
    "write_failed": (500, "Файл списка не записался - посмотрите диск, прежде чем повторять."),
}
#: Which refusal speaks first when there are several.
ORDER = ("unknown_channel", "unknown_list", "bad_who", "invalid", "batch_open",
         "check_changed", "locked", "not_repo", "commit_refused", "write_failed")


def _writer(name):
    if name == "fact-sources":
        return factory.channel_list_write().write_fact_sources
    if name == "footage-origin":
        return factory.channel_list_write().write_footage_origin
    return factory.affiliate().write_table


def _run(root, cid, name, body, base, dry_run):
    try:
        return _writer(name)(cid, body, base_sha256=base, by=WRITE_BY, via=VIA, root=root,
                             dry_run=dry_run, commit=True, lock_wait=LOCK_WAIT,
                             now=FACTORY_KW.get("now"), open_rows=FACTORY_KW.get("open_rows"))
    except Exception as e:                                      # noqa: BLE001
        raise BatchFault(500, "factory_broken", "Писатель списков фабрики ответил ошибкой - "
                                                "посмотрите список, прежде чем повторять.",
                         [f"{type(e).__name__}: {e}"]) from e


def _refusals(res):
    return [dict(r, message=REFUSALS.get(r["code"], (500, r["line"]))[1])
            for r in res["refusals"]]


def _first(refs):
    return min(refs, key=lambda r: ORDER.index(r["code"]) if r["code"] in ORDER else len(ORDER))


def _body(res, refs):
    return {"ok": bool(res["ok"]), "path": res["path"], "base_sha256": res["base_sha256"],
            "sha256": res["sha256"], "new_sha256": res["new_sha256"], "refusals": refs,
            "lines": list(res["lines"]), "by": res["by"], "via": res["via"]}


def plan(root, channel, name, body, base_sha256):
    """The factory's dry run of the write and a confirm token when it would
    write - nothing written."""
    cid = _channel(root, channel)
    action, _words, _key = LISTS[name]
    res = _run(root, cid, name, body, base_sha256, dry_run=True)
    refs = _refusals(res)
    changes = bool(res["ok"]) and res["new_sha256"] != res["sha256"]
    why = (_first(refs)["message"] if refs
           else None if changes else "Нечего записывать - список уже такой.")
    out = dict(_body(res, refs), action=action, channel=cid, list=name, dry_run=True,
               changes=changes, why=why, confirm=None, expires_in_s=None)
    if changes:
        fp = _digest({"action": action, "channel": cid, "body": body, "base": base_sha256,
                      "new": res["new_sha256"]})
        out.update(confirm=_issue(root, action, cid, fp, {"body": body, "base": base_sha256}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def write(root, channel, name, token):
    """The confirmed write: the token spent, then the factory's writer for
    real with the plan's base - a refusal is a problem, nothing written."""
    cid = _channel(root, channel)
    action, _words, _key = LISTS[name]
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая запись списков канала - подождите и "
                                      "запросите план заново.",
                         [f"the channel lists' write lock was not free in {WRITE_WAIT} s; the "
                          f"token is not spent"])
    try:
        got = _spend(root, action, cid, token)
        res = _run(root, cid, name, got["bound"]["body"], got["bound"]["base"], dry_run=False)
    finally:
        _WRITE.release()
    refs = _refusals(res)
    if not res["ok"]:
        first = _first(refs)
        status = REFUSALS.get(first["code"], (500, ""))[0]
        raise BatchFault(status, first["code"], first["message"],
                         paths.clean([f"{r['code']}: {r['line']}" for r in res["refusals"]]
                                     + list(res["lines"]), root))
    return paths.clean(dict(_body(res, refs), action=action, channel=cid, list=name,
                            dry_run=False, written=bool(res["written"]), commit=res["commit"]),
                       root)
