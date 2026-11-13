"""CC-0165: moving a placed video to another day, or taking it back into the
копилка, from the center - only through the factory's own functions
(CF-0856, nothing of the API's own on top):

    agents/publisher/publish_move.py    move_plan (a dry run, nothing written)
                                        move_confirm (all or nothing under the
                                        acceptance record's lock, one commit -
                                        the factory's own: it measures the files
                                        it touched and commits exactly those)

CC-0182 (CF-0920): one of two videos of a name is `batch_id` beside the `slug` of a move
(the factory's `<batch>/<slug>`) and `<batch>/<slug>` in `unplace` / `withdraw`, whose bare
name means the placed one; a bare move the factory cannot tell is its `ambiguous`, in
Russian with the batches named.

The edits: `moves` `[{slug, day}]` - the video takes that day's slot of the
channel (a video already in Studio: its journal row's publish_at / publish_day
/ note are rewritten and the move is appended to `rescheduled`; the date in
Studio itself is the human's - a STUDIO line in the item's `warnings` says
so); `unplace` `[slug]` - a video with no live journal row goes back into
`publish/<channel>/_queue/` (one in Studio is refused `in_studio`); `withdraw`
`[slug]` (CC-0179, CF-0918: the feed 3 days ahead, the rest a reserve) - a video
in Studio with its slot ahead goes into `_reserve/` (CF-0919) as the копилка's reserve:
its journal row gets `withdrawn` and holds no slot and no day. A `move` of such
a video brings it back with no new upload (the item's `reserve`). Taking it off
its schedule in Studio is the user's, before the withdraw - this API only writes
what the factory writes after it (a STUDIO line in the item's `warnings`). The
plan is judged as a whole: "25->24, 26->25 and unplace the 24th" is no conflict,
the order named does not matter.

**The plan** (`move_plan`): the factory's `move_plan(by="user", via="center")`
plus the center's two checks of the stash placement (`api/publish_stash.py`)
- the root is a git repository (`not_repo`) and nothing is uncommitted in what
a move writes (`dirty`: `scope` - publish/<c>/, publish/README.md,
publish/acceptance-log.json, publish/uploads.json; the factory commits every
file it touched and would sweep a hand edit of one of them in). Its
`base_sha256` is the factory's `publish_stash.state_sha256`. A confirm token
(120 s, single use, action `publish_move`, bound to the moves, the unplaces,
the withdraws and the base) only when every edit is ok.

**The confirm** (`move`): one publication write at a time (`publish._WRITE`,
and the verdict lock of `api/videos.py` - a move repoints the acceptance
record's `publish_path`), the token spent; a `base_sha256` the client sends
back must be the token's (`check_changed`); the plan made again - its
fingerprint must be the plan's, else `check_changed`; then
`move_confirm(by="user", via="center", base_sha256=<the plan's>)` - the
factory checks the base again under its lock and refuses under an open batch
(`batch_open`). Nothing written: the first refusal is the problem (409 /
404 / 422 / 500 by its code). Written but not ok (`apply_failed` - stopped
half-way; `commit_refused` - git refused the factory's commit): 409 with the
touched files in the details. Else the answer with the factory's `commit`.

`FACTORY_KW` holds the factory's injection points (`now`, `open_rows`) -
empty in production; the tests put a fixed clock and open batches there.
"""
from pathlib import Path

from . import batches, factory, paths, publish, videos
from .batches import SAFE_NAME, BatchFault, _channel, _digest, _issue, _spend
from .publish_stash import _status

BY, VIA = "user", "center"
#: The factory's own injection points - empty in production.
FACTORY_KW = {}
#: How many edits (moves + unplaces + withdraws) one plan names at most.
ORDER_MAX = 60
WRITE_WAIT = 30.0
MOVE = "publish_move"
batches.register_actions({
    MOVE: ("план переноса", "ролики не перенесены", "переноса роликов канала"),
})

#: The refusal codes of a move -> (HTTP status when it stops the confirm, the
#: center's Russian message). The factory's (CF-0856 TOP_REFUSALS and
#: ITEM_REFUSALS, CF-0918 / CF-0919 WITHDRAW_REFUSALS) and the center's own (dirty, not_repo).
MOVE_RU = {
    # the whole plan
    "bad_who": (500, "Центр подписал перенос неверно (by/via) - это ошибка центра, ничего не "
                     "перенесено."),
    "unknown_channel": (404, "Канала нет в фабрике - переносить нечего."),
    "no_queue": (409, "У канала нет очереди публикаций (publisher.slot) - слотов, куда "
                      "переносить, нет."),
    "empty_order": (422, "Не выбран ни один ролик - укажите, что перенести или снять."),
    "batch_open": (409, "Идёт батч канала - перенос подождёт его: батч в это же время коммитит "
                        "свои записи."),
    "check_changed": (409, "Очередь канала или журналы публикаций изменились с момента плана - "
                           "посмотрите план заново."),
    "apply_failed": (409, "Фабрика остановилась на середине переноса - часть файлов уже "
                          "изменена (см. подробности); нужен человек, прежде чем повторять."),
    "commit_refused": (409, "Перенос записан в дереве фабрики, но git не принял коммит - файлы "
                            "остались изменёнными (см. подробности); посмотрите git status, "
                            "прежде чем повторять."),
    "dirty": (409, "В publish/ канала или журналах есть изменения, которых нет в git (правка "
                   "руками или выкладка без коммита). Фабрика закоммитит всё, что тронет "
                   "перенос, - сохраните их коммитом или отмените, потом повторите."),
    "not_repo": (409, "Корень фабрики - не git-репозиторий: перенос не закоммитить, ничего не "
                      "перенесено."),
    # one video
    "bad_order": (422, "Перенос - это ролик и день (ГГГГ-ММ-ДД), снятие - имя ролика."),
    "not_in_studio": (409, "Ролика нет в Studio (нет живой строки журнала загрузок) - снимать из "
                           "ленты нечего; такой ролик возвращается в копилку обычным снятием "
                           "со слота."),
    "in_reserve": (409, "Ролик уже снят из ленты и лежит в запасе копилки - снимать нечего; "
                        "вернуть его можно переносом на день."),
    "not_placed": (409, "У ролика есть строка журнала загрузок, но нет пары в папке дня - "
                        "забирать в копилку нечего; сначала поправьте запись."),
    "reserve_taken": (409, "В запасе заняты и имя этого ролика, и его имя с батчем (или батч "
                           "ролика неизвестен) - сначала верните тот ролик на день или оставьте "
                           "этот в ленте."),
    "duplicate": (409, "Ролик назван в плане дважды - один ролик, одна правка."),
    "not_found": (409, "Ролика нет ни в одном дне publish/ канала и нет в журнале загрузок."),
    "in_queue": (409, "Ролик и так в копилке без слота - переносить нечего (его ставит в слот "
                      "«Разложить по слотам»)."),
    "ambiguous": (409, "Ролик лежит в нескольких местах сразу - укажите, какой из них, его батч "
                       "(batch_id); если батч не поможет, нужен человек."),
    "inconsistent": (409, "Папка дня и строка журнала загрузок называют разные дни - сначала "
                          "поправьте запись."),
    "published": (409, "Слот ролика уже прошёл - опубликованный ролик не переносится и не "
                       "снимается."),
    "in_studio": (409, "Ролик уже в Studio - обычным снятием в копилку его не вернуть (журнал "
                       "хранит его строку); снимите его из ленты в запас или перенесите на "
                       "другой день."),
    "bad_day": (422, "День не читается - нужен ГГГГ-ММ-ДД."),
    "same_day": (409, "Ролик и так стоит на этот день."),
    "no_slot_day": (409, "В этот день у канала нет слота."),
    "day_taken": (409, "День занят другим роликом - перенесите или снимите его в этом же плане."),
    "too_soon": (409, "Слот этого дня ближе, чем запас канала (lead) - в Studio его уже не "
                      "поставить."),
}
#: Which refusal speaks first when the confirm stops.
MOVE_ORDER = ("unknown_channel", "bad_who", "empty_order", "not_repo", "dirty", "no_queue",
              "batch_open", "check_changed", "apply_failed", "commit_refused")


def _pm():
    return factory.publish_move()


def _kw():
    return FACTORY_KW.get("now")


def _broken(e, what):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой ({what}) - посмотрите "
                                             f"очередь канала, прежде чем повторять.",
                      [f"{type(e).__name__}: {e}"])


def scope(cid):
    """What a move of `cid` writes in git's eyes (publish_move._write: the
    notes and their day folders, the README rows and the acceptance record's
    `publish_path` - `publish_layout.move_day` / `unassign`; the journal rows -
    `upload_records.reschedule`). The rotation ledger is never touched."""
    return [f"publish/{cid}", "publish/README.md", "publish/acceptance-log.json",
            "publish/uploads.json"]


def _invalid(why, what):
    return BatchFault(422, "invalid", why, [what])


def _order(moves, unplace, withdraw=None):
    """([{slug, day, batch_id?}], [slug], [slug]) - the request's edits, checked for shape
    (the factory judges the rest: bad_order, bad_day, ...). CC-0182: an unplace and a
    withdraw name one of two namesakes as `<batch>/<slug>`, as the factory takes them."""
    moves = [] if moves is None else moves
    unplace = [] if unplace is None else unplace
    withdraw = [] if withdraw is None else withdraw
    if not isinstance(moves, list) or not isinstance(unplace, list) or \
            not isinstance(withdraw, list):
        raise _invalid("moves, unplace и withdraw - списки.",
                       f"moves: {moves!r:.200}; unplace: {unplace!r:.200}; "
                       f"withdraw: {withdraw!r:.200}")
    if len(moves) + len(unplace) + len(withdraw) > ORDER_MAX:
        raise _invalid(f"В одном плане - не больше {ORDER_MAX} правок.",
                       f"{len(moves)} moves + {len(unplace)} unplaces + "
                       f"{len(withdraw)} withdraws")
    out_m = []
    for m in moves:
        if not isinstance(m, dict) or not isinstance(m.get("slug"), str) or \
                not isinstance(m.get("day"), str) or len(m["slug"]) > 400 or len(m["day"]) > 40:
            raise _invalid("Перенос - {slug, day}: имя ролика и день ГГГГ-ММ-ДД.",
                           f"moves: {m!r:.200}")
        edit = {"slug": m["slug"].strip(), "day": m["day"].strip()}
        if m.get("batch_id") is not None:
            if not isinstance(m["batch_id"], str) or not SAFE_NAME.match(m["batch_id"]) \
                    or "/" in edit["slug"]:
                raise _invalid("batch_id - имя батча рядом с именем ролика, без <батч>/ в slug.",
                               f"moves: {m!r:.200}")
            edit["batch_id"] = m["batch_id"]
        out_m.append(edit)
    if any(not isinstance(s, str) or len(s) > 400 for s in unplace + withdraw):
        raise _invalid("Снятие - список имён роликов.",
                       f"unplace: {unplace!r:.200}; withdraw: {withdraw!r:.200}")
    return out_m, [s.strip() for s in unplace], [s.strip() for s in withdraw]


def _factory_moves(moves):
    """CC-0182: the edits as the factory takes them - one of two namesakes is `<batch>/<slug>`."""
    return [{"slug": f"{m['batch_id']}/{m['slug']}" if m.get("batch_id") else m["slug"],
             "day": m["day"]} for m in moves]


def _ref(r, said=None):
    text = said if said and r["code"] == "ambiguous" else \
        MOVE_RU.get(r["code"], (500, r.get("line") or r["code"]))[1]
    return dict(r, message=text)


def _which(root, cid, items):
    """CC-0182: {slug: the Russian line naming the batches} of the names refused `ambiguous`
    that are several videos in publish/ (the factory's line says only one batch)."""
    out = {}
    for slug in {it["slug"] for it in items
                 if any(r["code"] == "ambiguous" for r in it.get("refusals") or [])}:
        places = publish.namesakes(root, cid, slug)
        if len(places) > 1:
            out[slug] = publish.namesakes_message(slug, places)
    return out


def _first(refusals):
    return min(refusals, key=lambda r: MOVE_ORDER.index(r["code"])
               if r["code"] in MOVE_ORDER else len(MOVE_ORDER))


def _fault(refusals, lines, root, extra=()):
    first = _first(refusals)
    status, message = MOVE_RU.get(first["code"], (500, first.get("line") or first["code"]))
    return BatchFault(status, first["code"], message,
                      paths.clean([f"{r['code']}: {r.get('line')}" for r in refusals]
                                  + list(lines or []) + list(extra), root))


def _items(items, which=None):
    return [dict(it, refusals=[_ref(r, (which or {}).get(it["slug"]))
                               for r in it.get("refusals") or []],
                 warnings=list(it.get("warnings") or [])) for it in items]


def _counts(items):
    return {"moved": sum(1 for it in items if it["op"] == "move" and it["ok"]),
            "unplaced": sum(1 for it in items if it["op"] == "unplace" and it["ok"]),
            "withdrawn": sum(1 for it in items if it["op"] == "withdraw" and it["ok"])}


def _check(root, cid, moves, unplace, withdraw):
    """(the plan's answer, its fingerprint facts): the factory's move_plan by
    user via center, plus not_repo / dirty."""
    pm, gc = _pm(), factory.git_commit()
    try:
        res = pm.move_plan(cid, moves=_factory_moves(moves), unplace=unplace, root=Path(root),
                           now=_kw(), by=BY, via=VIA, withdraw=withdraw)
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "план переноса") from e
    top, dirty = [], {}
    if not gc.is_repo(root):
        top.append({"code": "not_repo", "line": f"{Path(root).name}: not a git work tree"})
    else:
        dirty = _status(root, scope(cid))
        if dirty:
            top.append({"code": "dirty", "line": "uncommitted: " + ", ".join(
                f"{xy.strip() or '?'} {p}" for p, xy in sorted(dirty.items()))})
    which = _which(root, cid, res["items"])
    items = _items(res["items"], which)
    refusals = [_ref(r, which.get(r.get("slug"))) for r in top + list(res["refusals"])]
    ok = bool(res["ok"]) and not top
    out = {"action": MOVE, "channel": cid, "ok": ok, "dry_run": True, "task": res.get("task"),
           "moves": moves, "unplace": unplace, "withdraw": withdraw, "items": items,
           "refusals": refusals, "warnings": list(res.get("warnings") or []),
           "lines": list(res["lines"]) + [r["line"] for r in top],
           "ledger": res.get("ledger"), "base_sha256": res.get("base_sha256"),
           "sha256": res.get("sha256"), "why": None if ok else _first(refusals)["message"], "by": BY, "via": VIA,
           **_counts(items)}
    facts = {"moves": moves, "unplace": unplace, "withdraw": withdraw,
             "base": res.get("base_sha256"), "ok": ok,
             "items": [[it["op"], it["slug"], it.get("from_day"), it.get("day"), it.get("slot"),
                        it["ok"]] for it in items],
             "refusals": sorted(r["code"] for r in refusals), "dirty": sorted(dirty)}
    return out, facts


def move_plan(root, channel, moves=None, unplace=None, withdraw=None):
    """What the moves / unplaces / withdraws would do - nothing written; a
    token only when every edit is ok."""
    cid = _channel(root, channel)
    moves, unplace, withdraw = _order(moves, unplace, withdraw)
    out, facts = _check(root, cid, moves, unplace, withdraw)
    fp = _digest(facts)
    out = dict(out, fingerprint=fp, confirm=None, expires_in_s=None)
    if out["ok"]:
        out.update(confirm=_issue(root, MOVE, cid, fp, {"moves": moves, "unplace": unplace,
                                                        "withdraw": withdraw,
                                                        "base": out["base_sha256"]}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def move(root, channel, token, base_sha256=None):
    """The confirmed move - see the module's docstring."""
    cid = _channel(root, channel)
    if not publish._WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая запись публикации - подождите и запросите "
                                      "план заново.",
                         [f"the publication write lock was not free in {WRITE_WAIT} s; the "
                          f"token is not spent"])
    try:
        if not videos._WRITE.acquire(timeout=WRITE_WAIT):
            raise BatchFault(409, "busy", "Идёт запись вердикта приёмки - подождите и "
                                          "запросите план заново.",
                             [f"the verdict lock was not free in {WRITE_WAIT} s; the token is "
                              f"not spent"])
        try:
            return _move(root, cid, token, base_sha256)
        finally:
            videos._WRITE.release()
    finally:
        publish._WRITE.release()


def _move(root, cid, token, base_sha256):
    got = _spend(root, MOVE, cid, token)
    b = got["bound"]
    moves, unplace, withdraw, base = b["moves"], b["unplace"], b.get("withdraw") or [], b["base"]
    if base_sha256 is not None and base_sha256 != base:
        raise BatchFault(409, "check_changed", MOVE_RU["check_changed"][1],
                         [f"base_sha256 {base_sha256} is not the plan's ({base})"])
    out, facts = _check(root, cid, moves, unplace, withdraw)
    if _digest(facts) != got["fingerprint"]:
        if not out["ok"]:
            raise _fault(out["refusals"], out["lines"], root)
        raise BatchFault(409, "check_changed", MOVE_RU["check_changed"][1],
                         ["the fingerprint of the move plan differs from the plan's"])
    if not out["ok"]:                                   # the same plan: cannot be, but fail closed
        raise _fault(out["refusals"], out["lines"], root)
    pm = _pm()
    try:
        ans = pm.move_confirm(cid, moves=_factory_moves(moves), unplace=unplace, by=BY, via=VIA,
                              root=Path(root), now=_kw(), base_sha256=base,
                              open_rows=FACTORY_KW.get("open_rows"), withdraw=withdraw)
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "перенос") from e
    refusals = [_ref(r) for r in ans["refusals"]]
    if not ans["ok"]:
        if not ans["written"]:
            top = [r for r in refusals if "slug" not in r]
            raise _fault(top or refusals, ans["lines"], root)
        late = [r for r in refusals if r["code"] in ("apply_failed", "commit_refused")]
        raise _fault(late or refusals, ans["lines"], root,
                     ["touched: " + ", ".join(ans.get("touched") or [])])
    items = _items(ans["items"])
    res = {"action": MOVE, "channel": cid, "ok": True, "dry_run": False,
           "written": bool(ans["written"]), "task": ans.get("task"), "moves": moves,
           "unplace": unplace, "withdraw": withdraw, "items": items, "refusals": refusals,
           "warnings": list(ans.get("warnings") or []), "lines": list(ans["lines"]),
           "ledger": ans.get("ledger"), "base_sha256": ans.get("base_sha256"),
           "sha256": ans.get("sha256"), "new_sha256": ans.get("new_sha256"),
           "commit": ans.get("commit"), "touched": sorted(ans.get("touched") or []),
           "by": ans.get("by") or BY, "via": ans.get("via") or VIA, **_counts(items)}
    return paths.clean(res, root)
