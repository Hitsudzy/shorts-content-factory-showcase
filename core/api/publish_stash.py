"""CC-0122: the channel's копилка in the center - the accepted videos waiting
in `publish/<channel>/_queue/` and `_reserve/` (CF-0919) with no slot, and placing
N of them onto the coming slots at once (the user's way of working, 13.10:
accept over several batches, let them pile up, then put N on the next week).
Only through the factory's own functions (CF-0738), nothing of the API's own on top:

    agents/publisher/publish_stash.py   stash (the pile with its details),
                                        place_plan / place_confirm (K videos
                                        in order onto the K nearest free
                                        slots, each through publish_card.place)
    shared/runlog/acceptance.py         repair_queue - the accepted rows with no
                                        place in publish/ put into `_queue/`
                                        (it commits the record itself)
    shared/runlog/git_commit.py         git, rel, is_repo, head - the commit of
                                        what the placement touched

**The pile** (`stash`): the factory's `stash` - per video its slug, batch or
rebuild, when accepted, the mp4 in publish/ and the batch's render and
thumbnail, the card (there, ready, why not; CC-0127 its state none / building /
ready / ruled / not_ready, placeable, reasons, the ruling, the last build -
CF-0747), a hold, its age (days since the
acceptance and since the topic's news) with the factory's aging rule
(CF-0741: `age.basis` news when the topic has a dated news source, else
accepted; `age.days`; `age.stale` strictly past 14 days, only marked) and the
pile's `stale` count; the video's `title` / `title_source` (CF-0750: the
card's `## Название` as the card says it - `card`, else the topic's
`title_ref` - `topic`, else null) and `card.title`, each with a `title_clean`
beside it - the same title with its trailing hashtags (the channel's
« #shorts») cut, for display; `not_queued` beside (accepted rows with no place, what
the repair would put there); CC-0186 (CF-0921) `other_version` - accepted rows
left out as another version of a placed video only because the rule could not
tell a new video from a version, with the placed one (`other_entry`,
`other_path`, `other_why`) and the factory's `--other-version-ok` command as
`repair` (data only, no route runs it; empty on an older factory); `staleness`
the factory's rule as it states it.
The plan's / confirm's items carry `stale`, `age_days`, `age_basis` and a
stale one's line « (устарел: N дн.)» - never a refusal. Every path through
`paths.clean`; `mp4_url` / `preview_url` / `videos_url` are the batch video
routes of `api/videos.py` (`/batches/{dir}/{batch}/videos/{slug}/mp4|preview`,
rebuilds as `rebuilds/<ts>`) - only when that route would serve it, else null.

**Placing** (`place_plan` / `place`): the plan is the factory's
`place_plan` (nothing written) plus the center's own two checks - the root is
a git repository (`not_repo`) and nothing is uncommitted in what a placement
writes (`dirty`: `SCOPE` - publish/<c>/, publish/README.md,
publish/acceptance-log.json, rotation/ledger/<c>.csv; the center commits what
the placement changed there and must not sweep a hand edit in with it). A
confirm token (120 s, single use, action `stash_place`) only when every video
places. The confirm: one publication write at a time (`publish._WRITE`, and
the verdict lock of `api/videos.py` - a verdict commits the acceptance record,
which a placement repoints), the token spent, the plan made again - its
fingerprint (the factory's `base_sha256`, every item's slot) must be the
plan's, else `check_changed`; then `place_confirm(by="user", via="center")`
with the plan's base (the factory checks it again under its lock, and refuses
under an open batch of the channel - `batch_open`: a batch commits its records
at the same time). `place_confirm` does not commit (`commit: null`); the
center commits exactly the files it touched, in one commit: the answer's
`touched` when the factory gives it (CF-0738 follow-up), else what
`git status --porcelain -z --no-renames` over `SCOPE` shows after the
placement and did not show before (before is empty - `dirty` refused it).
A card moved out of `_queue/` by `git mv` is a deletion and an addition - both
go into the commit (`git add` / `git rm --cached`, then `git commit --only`);
gitignored files (the mp4s) are never staged. A commit git refuses is
`commit_refused`: the paths are unstaged again, the placement stays in the
tree (it cannot be undone safely - mp4s were moved), the problem says so.

**The feed's horizon and the reserve** (CC-0179, CF-0918, the user's policy of
04.11: the feed 3 days ahead, the rest a reserve of evergreen videos). The pile's
videos carry the factory's `bucket` (`_queue` / `_reserve`, CF-0919), `feed_kind`
(news / evergreen, by the video's own fact), `kind_mark`, `news_why`, `stale_at`,
`reserve` and `video_id` (withdrawn from Studio, comes back with no new upload);
the pile its `news` and `reserve` counts and the channel's `horizon` {days,
last_day, source}. A placement's items carry the same and `beyond_horizon` (the
`no_slot` of a free slot past the horizon). An older answer without them reads
as evergreen, not in the reserve, no horizon. `auto` (the factory's `plan|confirm
--auto`) names no videos: the order is the factory's own `choose` - fresh news
first, then the reserve, as many as the free slots inside the horizon take - and
`skipped` says what waits and why (`SKIP_RU`); `force` lets a stale news video
in. The token is bound to `auto`, `force`, the order and what was skipped, and
the confirm asks the factory for the same choice again. A reserve video's return
writes the journal, so with one in the plan `publish/uploads.json` is in `scope`.

**Two videos of one name** (CC-0182, CF-0920: the second lies as `<slug>~<batch>`): the pile's
`slug` stays plain, `batch_id` and `bucket` tell them apart, an order names one as
`<batch>/<slug>`, and the name alone with two waiting is the factory's `not_in_queue` with a
Russian message naming the batches; `skipped` gives `batch_id` too.

**Repair** (`repair_plan` / `repair`): `acceptance.repair_queue` for the
channel's `not_queued` rows (or the given entry ids among them) - the dry run,
a token (action `stash_repair`) when something would be put in, then the real
run with the record's sha256 of the plan (`check_changed`), by user via
center; the factory commits the record itself.

`FACTORY_KW` holds the factory's injection points (`now`, `open_rows`) -
empty in production; the tests put a fixed clock and open batches there.
"""
import re
import threading
from pathlib import Path

from . import batches, channels, factory, paths, publish, videos
from .batches import PIPELINE_DIR, BatchFault, _channel, _digest, _issue, _spend

BY, VIA = "user", "center"
#: The factory's own injection points - empty in production.
FACTORY_KW = {}
#: How many videos one placement names at most.
ORDER_MAX = 60
WRITE_WAIT = 30.0
PLACE, REPAIR = "stash_place", "stash_repair"
batches.register_actions({
    PLACE: ("план раскладки копилки", "ролики не разложены", "раскладки копилки канала"),
    REPAIR: ("план починки копилки", "копилка не починена", "починки копилки канала"),
})

#: The refusal codes of a placement -> (HTTP status when it stops the confirm,
#: the center's Russian message). The factory's (CF-0738 TOP_REFUSALS and
#: ITEM_REFUSALS) and the center's own (dirty, not_repo, commit_refused).
PLACE_RU = {
    # the whole placement
    "bad_who": (500, "Центр подписал раскладку неверно (by/via) - это ошибка центра, ничего "
                     "не разложено."),
    "unknown_channel": (404, "Канала нет в фабрике - раскладывать некуда."),
    "no_queue": (409, "У канала нет очереди публикаций (publisher.slot) - слотов, куда "
                      "раскладывать, нет."),
    "paused": (409, "Публикации канала на паузе - раскладка подождёт снятия паузы."),
    "batch_open": (409, "Идёт батч канала - раскладка подождёт его: батч в это же время "
                        "коммитит свои записи."),
    "empty_order": (422, "Не выбран ни один ролик - отметьте, какие ролики раскладывать."),
    "check_changed": (409, "Копилка или журналы публикаций изменились с момента плана - "
                           "посмотрите план заново."),
    "dirty": (409, "В publish/ канала или журналах есть изменения, которых нет в git (правка "
                   "руками или выкладка без коммита). Центр не смешает их со своей раскладкой: "
                   "сохраните их коммитом или отмените, потом повторите."),
    "not_repo": (409, "Корень фабрики - не git-репозиторий: раскладку не закоммитить, ничего "
                      "не разложено."),
    "commit_refused": (409, "Ролики разложены в дереве фабрики, но git не принял коммит - "
                            "файлы остались изменёнными (см. подробности); посмотрите "
                            "git status, прежде чем повторять."),
    # one video
    "duplicate": (409, "Ролик назван в списке дважды - второй раз не раскладывается."),
    "not_in_queue": (409, "Этого ролика нет в копилке канала (publish/<канал>/_queue/ и _reserve/)."),
    "not_accepted": (409, "Ролик не принят в журнале приёмки - слота ему нет."),
    "held": (409, "На ролике неподписанный холд публикации - сначала подпись холда."),
    "render_missing": (409, "Файла ролика нет в копилке - раскладывать нечего."),
    "batch_missing": (409, "Батча ролика нет на диске - карточку не из чего выложить."),
    "no_card": (409, "У ролика нет карточки - сначала соберите её."),
    "card_building": (409, "Карточка ролика сейчас собирается - дождитесь итога сборки, "
                           "потом раскладывайте."),
    "card_not_ready": (409, "Карточка ролика не готова - в слот она не идёт."),
    "note_differs": (409, "Заметка в копилке - от другого батча, чем принятый ролик; нужен "
                          "человек."),
    "no_slot": (409, "Свободных слотов в горизонте очереди не осталось - этот ролик ждёт в "
                     "копилке."),
    "place_failed": (409, "Фабрика не смогла выложить ролик - он остался в копилке; строка "
                          "фабрики в подробностях."),
}
#: CC-0179: why the auto placement left a video waiting (the factory's `skipped[].reason`).
SKIP_RU = {
    "stale_news": "Новость устарела - сама в слот не идёт; поставить можно руками или "
                  "авто-раскладкой с force.",
    "beyond_horizon": "В горизонте ленты не осталось свободных слотов - ролик ждёт в копилке.",
    # CF-0919: a card that cannot be placed gives up its slot to the next one, whatever `force`
    "no_card": "У ролика нет карточки - слот отдан следующему; сначала соберите её.",
    "card_building": "Карточка ролика сейчас собирается - слот отдан следующему, ролик ждёт итога "
                     "сборки.",
    "card_not_ready": "Карточка ролика не готова - слот отдан следующему, ролик ждёт в копилке.",
    "note_differs": "Заметка в копилке - от другого батча, чем принятый ролик; слот отдан "
                    "следующему, нужен человек.",
}
#: The auto placement chose nothing: `empty_order` here is not "nothing was named".
AUTO_EMPTY_RU = ("Авто-раскладке ставить нечего: в копилке нет подходящих роликов или в горизонте "
                 "ленты нет свободных слотов (см. skipped).")
#: Which refusal speaks first when the confirm stops.
PLACE_ORDER = ("unknown_channel", "bad_who", "empty_order", "not_repo", "dirty", "no_queue",
               "paused", "batch_open", "check_changed")

#: The repair's refusals (acceptance.repair_queue) -> (status, Russian message);
#: a video's own codes carry the factory's `text_ru`.
REPAIR_RU = {
    "bad_who": (500, "Центр подписал починку неверно (by/via) - это ошибка центра."),
    "batch_open": (409, "Идёт батч - починка копилки коммитит журнал приёмки и ждёт его."),
    "check_changed": (409, "Журнал приёмки изменился с момента плана - посмотрите план "
                           "заново."),
    "commit_refused": (409, "Git не принял коммит журнала приёмки - копии в _queue/ могли "
                            "остаться; посмотрите git status."),
    "not_found": (422, "Этой строки нет среди принятых роликов канала без места в publish/."),
}


def _ps():
    return factory.publish_stash()


def _kw():
    return {"now": FACTORY_KW.get("now"), "open_rows": FACTORY_KW.get("open_rows")}


def _broken(e, what):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой ({what}) - посмотрите "
                                             f"копилку, прежде чем повторять.",
                      [f"{type(e).__name__}: {e}"])


# ---------------------------------------------------------------- the pile
def _routes(root, v, prefix):
    """The batch video routes of the video's batch - only those that would
    serve (api/videos.py: mp4_path / preview_path), else None."""
    out = {"mp4_url": None, "preview_url": None, "videos_url": None}
    parts = Path(v.get("batch_dir") or "").parts
    if len(parts) != 3 or parts[0] != PIPELINE_DIR or not v.get("slug"):
        return out
    group, name, slug = parts[1], parts[2], v["slug"]
    base = f"{prefix}/batches/{group}/{name}"
    try:
        videos._video_of(root, group, name, slug)
    except BatchFault:
        return out
    out["videos_url"] = f"{base}/videos"
    for key, fn, tail in (("mp4_url", videos.mp4_path, "mp4"),
                          ("preview_url", videos.preview_path, "preview")):
        try:
            fn(root, group, name, slug)
        except BatchFault:
            continue
        out[key] = f"{base}/videos/{slug}/{tail}"
    return out


#: Trailing hashtags of a title (the channel's « #shorts» suffix and the like):
#: each after a space, with at least one letter (so a closing «#1» stays).
_TAGS = re.compile(r"(?:\s+#\w*[^\W\d_]\w*)+\s*$")


def title_clean(title):
    """CC-0122 / CF-0750: the title without its trailing hashtags - what the
    center shows; None for no title or a title that is nothing but tags."""
    if not isinstance(title, str):
        return None
    out = _TAGS.sub("", " " + title.strip()).strip()
    return out or None


def _titled(v):
    return dict(v, title_clean=title_clean(v.get("title")))


def stash(root, channel, prefix=""):
    """The factory's pile of the channel with the routes of each video."""
    cid = _channel(root, channel)
    ps = _ps()
    try:
        res = ps.stash(cid, Path(root), FACTORY_KW.get("now"))
    except ps.publish_queue.QueueError as e:
        raise BatchFault(404, "unknown_channel", f"Канала «{channel}» нет в фабрике.",
                         [str(e)]) from e
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "копилка") from e
    out = paths.clean(res, root)          # the routes after: clean cuts any absolute path
    out["videos"] = [dict(_titled(v), card=_card(v.get("card")), **_routes(root, v, prefix))
                     for v in out["videos"]]
    for key in ("not_queued", "other_version"):     # CC-0186: other_version, CF-0921
        if key in out:
            out[key] = [dict(_titled(v), card=_card(v.get("card")), **_routes(root, v, prefix))
                        for v in out[key]]
    return out


def _card(card):
    """CC-0127: the card's state in Russian and its build's word (CF-0747
    `state`, `build.code`)."""
    from . import card_center                                   # noqa: PLC0415
    if not isinstance(card, dict):
        return card
    out = dict(card, state_ru=card_center.STATE_RU.get(card.get("state"), card.get("state")),
               title_clean=title_clean(card.get("title")))
    if isinstance(card.get("build"), dict):
        out["build"] = card_center._run_short(card["build"])
    if isinstance(card.get("ruling"), dict):
        out["ruling"] = card_center._ruling_short(card["ruling"])
    return out


# ---------------------------------------------------------------- placing
def scope(cid, reserve=False):
    """What a placement of `cid` writes in git's eyes (publish_card.place:
    the card into its day - `publish_layout.assign`, its README row and the
    record's `publish_path`; `publish_window.record_published` - the ledger's
    publication columns). CC-0179: a video of the reserve coming back writes
    its journal row too (`publish_move.return_reserve`)."""
    return [f"publish/{cid}", "publish/README.md", "publish/acceptance-log.json",
            f"rotation/ledger/{cid}.csv"] + (["publish/uploads.json"] if reserve else [])


def _status(root, rels):
    """{path: XY} of `git status --porcelain -z --no-renames` over `rels`
    (untracked files listed one by one; ignored ones never)."""
    gc = factory.git_commit()
    cp = gc.git(root, "status", "--porcelain", "-z", "--no-renames", "--untracked-files=all",
                "--", *rels)
    out = {}
    for rec in cp.stdout.split("\0"):
        if len(rec) > 3:
            out[rec[3:]] = rec[:2]
    return out


def _order(order):
    if not isinstance(order, list) or len(order) > ORDER_MAX or \
            any(not isinstance(s, str) or not s.strip() or len(s) > 400 for s in order):
        raise BatchFault(422, "invalid", f"Список роликов - от 0 до {ORDER_MAX} имён "
                                         f"(slug или <батч>/<slug>).",
                         [f"order: {order!r:.200}"])
    return [s.strip() for s in order]


def _ref(r, said=None):
    text = said if said and r["code"] == "not_in_queue" else \
        PLACE_RU.get(r["code"], (500, r.get("line") or r["code"]))[1]
    return dict(r, message=text)


def _which(root, cid, items):
    """CC-0182 (CF-0920): {slug: the Russian line naming the batches} of the names refused
    `not_in_queue` because two videos wait under them - the factory's own refusal, whose
    Russian word "нет в копилке" would be wrong here. Its other `not_in_queue` lines name a
    batch or a video that is not there."""
    out = {}
    for slug in {it["slug"] for it in items if it.get("batch_id") is None
                 and any(r["code"] == "not_in_queue" for r in it["refusals"])}:
        places = publish.waiting_namesakes(root, cid, slug)
        if len(places) > 1:
            out[slug] = publish.namesakes_message(slug, places)
    return out


def _auto_kw(auto, force):
    """The factory's `--auto` / `--force`; a named order passes neither."""
    return {"auto": True, "force": bool(force)} if auto else {}


def _named(raw):
    """`(slug, batch or None)` of `<slug>` / `<batch>/<slug>` / `rebuilds/<batch>/<slug>`."""
    s = str(raw or "")
    head, _, slug = s.rpartition("/")
    return slug, head.rpartition("/")[2] or None


def _skipped(rows, root=None, cid=None, order=()):
    """The factory's `skipped` with the Russian reason. CC-0182 (CF-0920): `slug` always the
    plain name, `batch_id` which video. A `beyond_horizon` row names it as `<batch>/<slug>`;
    the rows of `choose` give the name alone, so the batch comes from the pile, in the pile's
    order (the order `choose` walks), past the videos the order or another row took - the
    factory's own `batch_id` first, when it gives one."""
    rows = [dict(x) for x in rows or []]
    for x in rows:
        slug, batch = _named(x.get("slug"))
        x.update(slug=slug, batch_id=x.get("batch_id") or batch)
    if root is not None and any(not x["batch_id"] for x in rows):
        ps = _ps()
        try:
            pile = ps.stash(cid, Path(root), FACTORY_KW.get("now"))["videos"]
        except Exception:                                       # noqa: BLE001
            pile = []                   # the plan speaks for itself: a row with no batch only
        left = {}
        for v in pile:
            left.setdefault(v["slug"], []).append(v["batch_id"])
        taken = [_named(s) for s in order] + [(x["slug"], x["batch_id"]) for x in rows]
        for slug, batch in taken:
            if batch and batch in left.get(slug, ()):
                left[slug].remove(batch)
        for x in rows:
            if not x["batch_id"] and left.get(x["slug"]):
                x["batch_id"] = left[x["slug"]].pop(0)
    return [dict(x, message=SKIP_RU.get(x.get("reason"), x.get("line") or x.get("reason")))
            for x in rows]


def _check(root, cid, order, auto=False, force=False):
    """(the plan's answer, its fingerprint facts): the factory's place_plan by
    user via center, plus not_repo / dirty. With `auto` the order is the
    factory's choice."""
    ps, gc = _ps(), factory.git_commit()
    try:
        res = ps.place_plan(cid, order, Path(root), by=BY, via=VIA, **_auto_kw(auto, force),
                            **_kw())
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "план раскладки") from e
    if auto:
        order = list(res.get("order") or [])
    skipped = _skipped(res.get("skipped"), root, cid, order)
    top = []
    dirty = {}
    if not gc.is_repo(root):
        top.append({"code": "not_repo", "line": f"{Path(root).name}: not a git work tree"})
    else:
        reserve = any(it.get("reserve") for it in res["items"])
        dirty = _status(root, scope(cid, reserve))
        if dirty:
            top.append({"code": "dirty", "line": "uncommitted: " + ", ".join(
                f"{xy.strip() or '?'} {p}" for p, xy in sorted(dirty.items()))})
    which = _which(root, cid, res["items"])
    items = [dict(it, refusals=[_ref(r, which.get(it["slug"])) for r in it["refusals"]])
             for it in res["items"]]
    refusals = [_ref(r, which.get(r.get("slug"))) for r in top + list(res["refusals"])]
    if auto:
        refusals = [dict(r, message=AUTO_EMPTY_RU) if r["code"] == "empty_order" else r
                    for r in refusals]
    ok = bool(res["ok"]) and not top
    why = None
    if not ok:
        first = min(refusals, key=lambda r: PLACE_ORDER.index(r["code"])
                    if r["code"] in PLACE_ORDER else len(PLACE_ORDER))
        why = first["message"]
    out = {"channel": cid, "ok": ok, "dry_run": True, "auto": bool(auto),
           "force": bool(auto and force), "order": order, "skipped": skipped, "items": items,
           "refusals": refusals, "lines": list(res["lines"]) + [r["line"] for r in top],
           "base_sha256": res["base_sha256"], "why": why,
           "placed": sum(1 for it in items if it["ok"])}
    facts = {"order": order, "auto": bool(auto), "force": bool(auto and force),
             "skipped": [[x.get("slug"), x.get("batch_id"), x.get("reason")] for x in skipped],
             "base": res["base_sha256"], "ok": ok,
             "items": [[it["slug"], it["batch_id"], it["slot"], it["day"], it["ok"]]
                       for it in items],
             "refusals": sorted(r["code"] for r in refusals), "dirty": sorted(dirty)}
    return out, facts


def place_plan(root, channel, order, auto=False, force=False):
    """What placing `order` - or, with `auto`, the factory's own choice - would
    do: nothing written; a token only when every video places."""
    cid = _channel(root, channel)
    order = _order(order)
    if auto and order:
        raise BatchFault(422, "invalid", "Авто-раскладка сама выбирает ролики - список не нужен.",
                         [f"auto with order: {order!r:.200}"])
    if force and not auto:
        raise BatchFault(422, "invalid", "force - только для авто-раскладки: названный ролик и "
                                         "так ставится, устаревший - с пометкой.",
                         ["force without auto"])
    out, facts = _check(root, cid, order, auto, force)
    fp = _digest(facts)
    out = dict(out, action=PLACE, fingerprint=fp, confirm=None, expires_in_s=None)
    if out["ok"]:
        out.update(confirm=_issue(root, PLACE, cid, fp, {"order": out["order"], "auto": bool(auto),
                                                         "force": bool(auto and force),
                                                         "base": out["base_sha256"]}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def _fault(refusals, lines, root):
    first = min(refusals, key=lambda r: PLACE_ORDER.index(r["code"])
                if r["code"] in PLACE_ORDER else len(PLACE_ORDER))
    status, message = PLACE_RU.get(first["code"], (500, first.get("line") or first["code"]))
    return BatchFault(status, first["code"], first.get("message") or message,
                      paths.clean([f"{r['code']}: {r.get('line')}" for r in refusals]
                                  + list(lines or []), root))


def _touched(root, cid, ans, before):
    """The files the placement changed: the factory's `touched` when it says
    (paths from the root), else the status over `scope` after minus before."""
    gc = factory.git_commit()
    if isinstance(ans.get("touched"), list):
        return sorted({gc.rel(root, p) for p in ans["touched"]}), "factory"
    after = _status(root, scope(cid))
    return sorted(p for p, xy in after.items() if before.get(p) != xy), "git_status"


def commit_paths(root, rels, message):
    """Commit exactly `rels` (from the root) in one commit through the factory's
    git helper: present files `git add`, gone ones `git rm --cached`,
    gitignored ones left out, then `git commit --only`. The sha, or None when
    nothing is left to commit. On a refusal the paths are unstaged again and
    the helper's CommitError goes up."""
    gc = factory.git_commit()
    rels = sorted(set(rels))
    if not rels:
        return None, []
    ignored = set(gc.git(root, "check-ignore", "--", *rels, check=False).stdout.splitlines())
    rels = [r for r in rels if r not in ignored]
    present = [r for r in rels if (Path(root) / r).exists()]
    gone = [r for r in rels if r not in present]
    if gone:
        known = set(gc.git(root, "ls-tree", "-r", "--name-only", "HEAD", "--", *gone,
                           check=False).stdout.splitlines())
        known |= set(gc.git(root, "ls-files", "--", *gone, check=False).stdout.splitlines())
        gone = [r for r in gone if r in known]
    rels = sorted(present + gone)
    if not rels:
        return None, []
    try:
        if present:
            gc.git(root, "add", "--", *present)
        if gone:
            gc.git(root, "rm", "--cached", "-q", "--ignore-unmatch", "--", *gone)
        gc.git(root, "commit", "-q", "-F", "-", "--only", "--", *rels, input=message)
    except gc.CommitError:
        gc.git(root, "reset", "-q", "--", *rels, check=False)
        raise
    return gc.head(root), rels


def _message(cid, items):
    placed = [it for it in items if it.get("placed")]
    lines = [f"- {it['slug']} -> {it.get('day')}" + (f" ({it['label']})" if it.get("label")
                                                     else "")
             + (" (из запаса, без новой загрузки)" if it.get("reserve") else "") for it in placed]
    return (f"Копилка: {len(placed)} в слоты {cid} ({BY}, {VIA})\n\n"
            "CC-0122: раскладка копилки из центра (publish_stash.place_confirm, CF-0738).\n"
            + "\n".join(lines) + "\n\n" + channels._trailers(cid, PLACE) + "\n")


def place(root, channel, token):
    """The confirmed placement - see the module's docstring."""
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
            return _place(root, cid, token)
        finally:
            videos._WRITE.release()
    finally:
        publish._WRITE.release()


def _place(root, cid, token):
    got = _spend(root, PLACE, cid, token)
    order, base = got["bound"]["order"], got["bound"]["base"]
    auto, force = bool(got["bound"].get("auto")), bool(got["bound"].get("force"))
    out, facts = _check(root, cid, [] if auto else order, auto, force)
    if _digest(facts) != got["fingerprint"]:
        if not out["ok"]:
            raise _fault(out["refusals"], out["lines"], root)
        raise BatchFault(409, "check_changed", PLACE_RU["check_changed"][1],
                         ["the fingerprint of the stash placement differs from the plan's"])
    if not out["ok"]:                                   # the same plan: cannot be, but fail closed
        raise _fault(out["refusals"], out["lines"], root)
    before = _status(root, scope(cid, any(it.get("reserve") for it in out["items"])))
    ps = _ps()
    try:
        ans = ps.place_confirm(cid, [] if auto else order, base, BY, VIA, Path(root),
                               **_auto_kw(auto, force), **_kw())
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "раскладка") from e
    items = [dict(it, refusals=[_ref(r) for r in it["refusals"]]) for it in ans["items"]]
    if not ans["written"] and not ans["ok"]:
        top = [r for r in ans["refusals"] if "slug" not in r]
        raise _fault([_ref(r) for r in (top or ans["refusals"])], ans["lines"], root)
    touched, source = _touched(root, cid, ans, before)
    gc = factory.git_commit()
    commit, committed = None, []
    if touched:
        try:
            commit, committed = commit_paths(root, touched, _message(cid, items))
        except gc.CommitError as e:
            placed = [f"{it['slug']} -> {it.get('day')}" for it in items if it.get("placed")]
            raise BatchFault(409, "commit_refused", PLACE_RU["commit_refused"][1],
                             paths.clean([str(e), *e.details, "placed: " + ", ".join(placed),
                                          "touched: " + ", ".join(touched)], root)) from e
    out = {"action": PLACE, "channel": cid, "ok": bool(ans["ok"]), "dry_run": False,
           "written": bool(ans["written"]), "auto": auto, "force": force,
           "order": list(ans.get("order") or order) if auto else order,
           "skipped": _skipped(ans.get("skipped"), root, cid, ans.get("order") or order),
           "items": items,
           "refusals": [_ref(r) for r in ans["refusals"]], "lines": list(ans["lines"]),
           "base_sha256": ans["base_sha256"], "new_sha256": ans.get("new_sha256"),
           "placed": sum(1 for it in items if it.get("placed")),
           "touched": touched, "touched_from": source, "committed": committed,
           "commit": commit, "by": BY, "via": VIA}
    return paths.clean(out, root)


# ---------------------------------------------------------------- the repair
def _acc():
    return factory.collect().acceptance()


def _repair_check(root, cid, entries):
    """(answer, facts) of the dry repair of the channel's not_queued rows."""
    ps = _ps()
    try:
        lost = [v["entry_id"] for v in ps.stash(cid, Path(root), FACTORY_KW.get("now"))
                ["not_queued"] if v.get("entry_id")]
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "копилка") from e
    if entries is not None:
        if not isinstance(entries, list) or any(not isinstance(e, str) for e in entries):
            raise BatchFault(422, "invalid", "entries - список entry_id строк приёмки.",
                             [f"entries: {entries!r:.200}"])
        foreign = [e for e in entries if e not in lost]
        if foreign:
            raise BatchFault(422, "not_found", REPAIR_RU["not_found"][1],
                             [f"{e}: not among {cid}'s accepted rows without a place"
                              for e in foreign])
        only = list(entries)
    else:
        only = lost
    if not only:
        res = {"ok": False, "items": [], "refusals": [], "lines": [], "sha256": None,
               "log": "publish/acceptance-log.json"}
    else:
        try:
            res = _acc().repair_queue(root=Path(root), apply=False, only=only,
                                      open_rows=FACTORY_KW.get("open_rows"))
        except Exception as e:                                  # noqa: BLE001
            raise _broken(e, "починка копилки") from e
    refusals = [dict(r, message=(r.get("line") if "entry_id" in r and r["code"] not in REPAIR_RU
                                 else REPAIR_RU.get(r["code"], (500, r.get("line")))[1]))
                for r in res["refusals"]]
    changes = [i for i in res["items"] if i.get("ok") and not i.get("skipped")
               and i.get("code") != "already_placed"]
    ok = bool(only) and bool(changes)
    why = (None if ok else "Нечего чинить - у всех принятых роликов канала есть место в publish/."
           if not only else refusals[0]["message"] if refusals
           else "Нечего класть в копилку - фабрика ничего не скопирует.")
    items = [{k: i.get(k) for k in ("entry_id", "slug", "batch_id", "code", "text_ru", "ok",
                                    "skipped", "refused", "changed", "publish_path")}
             for i in res["items"]]
    out = {"channel": cid, "ok": ok, "entries": only, "items": items, "refusals": refusals,
           "lines": list(res["lines"]), "sha256": res.get("sha256"), "why": why,
           "log": res.get("log")}
    facts = {"entries": only, "sha": res.get("sha256"),
             "items": [[i["entry_id"], i["code"]] for i in items]}
    return out, facts


def repair_plan(root, channel, entries=None):
    cid = _channel(root, channel)
    out, facts = _repair_check(root, cid, entries)
    fp = _digest(facts)
    out = dict(out, action=REPAIR, dry_run=True, fingerprint=fp, confirm=None,
               expires_in_s=None)
    if out["ok"]:
        out.update(confirm=_issue(root, REPAIR, cid, fp, {"entries": out["entries"],
                                                          "sha": out["sha256"]}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def repair(root, channel, token):
    cid = _channel(root, channel)
    if not videos._WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт запись вердикта приёмки - подождите и запросите "
                                      "план заново.",
                         [f"the verdict lock was not free in {WRITE_WAIT} s; the token is "
                          f"not spent"])
    try:
        got = _spend(root, REPAIR, cid, token)
        b = got["bound"]
        out, facts = _repair_check(root, cid, b["entries"])
        if _digest(facts) != got["fingerprint"]:
            raise BatchFault(409, "check_changed", REPAIR_RU["check_changed"][1],
                             ["the dry repair differs from the plan's"])
        try:
            res = _acc().repair_queue(root=Path(root), apply=True, by=BY, via=VIA,
                                      base_sha256=b["sha"], only=b["entries"],
                                      open_rows=FACTORY_KW.get("open_rows"))
        except Exception as e:                                  # noqa: BLE001
            raise _broken(e, "починка копилки") from e
    finally:
        videos._WRITE.release()
    top = [r for r in res["refusals"] if "entry_id" not in r]
    if top and not res["written"]:
        first = top[0]
        status, message = REPAIR_RU.get(first["code"], (500, first.get("line")))
        raise BatchFault(status, first["code"], message,
                         paths.clean([f"{r['code']}: {r.get('line')}" for r in res["refusals"]]
                                     + list(res["lines"]), root))
    items = [{k: i.get(k) for k in ("entry_id", "slug", "batch_id", "code", "text_ru", "ok",
                                    "skipped", "refused", "changed", "publish_path")}
             for i in res["items"]]
    refusals = [dict(r, message=(r.get("line") if "entry_id" in r and r["code"] not in REPAIR_RU
                                 else REPAIR_RU.get(r["code"], (500, r.get("line")))[1]))
                for r in res["refusals"]]
    return paths.clean({"action": REPAIR, "channel": cid, "ok": bool(res["ok"]),
                        "dry_run": False, "written": bool(res["written"]),
                        "entries": b["entries"], "items": items, "refusals": refusals,
                        "lines": list(res["lines"]), "sha256": res.get("sha256"),
                        "new_sha256": res.get("new_sha256"), "commit": res.get("commit"),
                        "log": res.get("log"), "by": BY, "via": VIA}, root)
