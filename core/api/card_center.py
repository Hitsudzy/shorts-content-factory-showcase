"""CC-0127: the publication card without the operator (CF-0747) - its state
wherever the center shows a card, «Собрать заново» (a detached build with its
log), what the build came to, and the user's ruling on a card that is not
ready only because of the video's own claims. Only through the factory's own
functions, `agents/publisher/card_center.py` loaded by path
(`factory.card_center`):

    card_info(channel, slug, batch_id)       GET  /api/publish/{c}/cards/{slug}?batch_id=
    card_build_launch(channel, slug, "user", "center", batch_id, draft)
                                             POST /api/publish/{c}/cards/{slug}/build/plan
                                                  (the center's plan, nothing started)
                                             POST /api/publish/{c}/cards/{slug}/build {confirm}
    card_build_result(run_id)                GET  /api/publish/{c}/cards/build/{run_id}
    ruling_plan(channel, slug, batch_id, "user", "center", words)
                                             POST /api/publish/{c}/cards/{slug}/ruling/plan
    ruling_confirm(..., base_sha256=plan.sha256, ...)
                                             POST /api/publish/{c}/cards/{slug}/ruling {confirm}

**The state** (`card_block`): `{state: none|building|ready|ruled|not_ready,
placeable, why, reasons, ruling {by, via, words, at}, build {run_id, log,
code, word, started_at, by, via, auto}}` - `publish_card.card_status` of the
card's text and `card_center.last_run` of its video (a build going makes the
state `building`). The batch video list and card (`api/videos.py`), a placed
note (`api/publish.py`) and the копилка (`publish_stash.stash` carries the
same, CF-0747) show it.

**The build**: the plan reads `card_info` (the video, the card, a build going)
and checks the draft (`publish_card.validate_draft`) - nothing is started;
a token (action `card_build_launch`, CONFIRM_TTL s, single use, bound to the
batch, the slug and the draft) only when nothing refuses. The confirm spends
the token, makes the plan again (its fingerprint, else `check_changed`) and
calls `card_build_launch(channel, slug, "user", "center", batch_id, draft)` -
the factory starts `publish_card.py build` as a detached process of its own
with its log (`schedule/publish-card/runs/<run_id>.log`) and answers at once;
the center never waits on it. Without a draft the model drafts the title,
the description and the tags and the claim check runs (CF-0555); with one the
model only checks the claims. `launcher` is the seam of the tests: no test
starts a real build. The outcome (`result`) is `card_build_result(run_id)`
with its Russian word and line (`OUTCOME_RU`) and `poll_s` while it runs.

**The ruling** covers only the video's own claims (the narration and the
on-screen text - the video is rendered, its words are not the card's): the
plan is the factory's `ruling_plan` (the failing claims `failing [{code,
where, video, text}]`, its `sha256`) plus the center's `not_repo` and `dirty`
(the note in publish/ the ruling writes has changes git does not have); a
token (action `card_ruling`, bound to the batch, the slug, the words and the
plan's sha256) only when nothing refuses. The confirm takes the publication
write lock and the verdict lock (as the копилка's placement), spends the
token, makes the plan again (else `check_changed`), calls `ruling_confirm`
with the plan's `sha256` as `base_sha256`, and commits exactly the files the
factory names in `touched` (`publish_stash.commit_paths` - gitignored ones,
the batch's card under pipeline/, left out). A commit git refuses is
`commit_refused`: the ruling stays written, nothing stays staged.

Every refusal code has a Russian line (`BUILD_RU`, `RULING_RU`); the factory's
own line goes into `details` / `refusals[].line`. Every answer goes out
through `api/paths.clean`. `FACTORY_KW` holds the factory's injection points
(`now`, `environ`) - empty in production.
"""
import threading
from pathlib import Path

from . import batches, channels, factory, paths, publish, publish_stash, videos
from .batches import BatchFault, _channel, _digest, _issue, _spend

BY, VIA = "user", "center"
BUILD, RULING = "card_build_launch", "card_ruling"
batches.register_actions({
    BUILD: ("план сборки карточки", "сборка карточки не запущена", "сборки карточки канала"),
    RULING: ("план решения по карточке", "решение не записано", "решения по карточке канала"),
})
POLL_S = 10
WRITE_WAIT = 30.0
_LAUNCH = threading.Lock()      # one build confirm at a time
#: The factory's injection points (now, environ) - empty in production.
FACTORY_KW = {}

STATES = ("none", "building", "ready", "ruled", "not_ready")
STATE_RU = {"none": "карточки нет", "building": "карточка собирается",
            "ready": "карточка готова", "ruled": "карточка принята решением пользователя",
            "not_ready": "карточка не готова"}

#: card_center.BUILD_REFUSALS and the center's own -> (HTTP status, Russian line).
BUILD_RU = {
    "bad_who": (500, "Центр подписал сборку неверно (by/via) - это ошибка центра, ничего не "
                     "запущено."),
    "unknown_channel": (404, "Канала нет в фабрике - карточку собирать не для кого."),
    "batch_missing": (404, "Батча ролика нет на диске - карточку собирать не из чего."),
    "unknown_video": (404, "Такого ролика в батче нет - карточку собирать не для чего."),
    "bad_draft": (422, "Черновик не годится (название, описание, хэштеги, теги) - подробности "
                       "ниже; ничего не запущено."),
    "running": (409, "Карточка этого ролика уже собирается - дождитесь итога сборки."),
    "spawn_failed": (500, "Сборка не стартовала - фабрика не смогла запустить процесс; "
                          "подробности ниже."),
    "batch_required": (422, "Принятого ролика с таким именем у канала не найдено - укажите "
                            "батч (batch_id)."),
    "namesakes": (409, "Роликов с этим именем в копилке несколько - укажите, какой из них, его "
                       "батч (batch_id)."),
}

#: card_build_result codes -> the center's Russian line (the factory's word is `word`).
OUTCOME_RU = {
    "ready": "Карточка готова - её можно выкладывать.",
    "not_ready": "Карточка собрана, но не готова - причины ниже. Если не прошли только "
                 "утверждения самого ролика, её можно принять своим решением.",
    "refused": "Карточка не собрана - фабрика отказала (строка фабрики ниже).",
    "not_asked": "Модель не ответила - карточка не собрана; повторите сборку позже.",
    "error": "Сборка закончилась ошибкой - смотрите журнал сборки.",
    "running": "Карточка собирается - итог появится здесь.",
}

#: card_center.RULING_REFUSALS and the center's own -> (HTTP status, Russian line).
RULING_RU = {
    "namesakes": BUILD_RU["namesakes"],
    "bad_who": (500, "Центр подписал решение неверно (by/via) - это ошибка центра, ничего не "
                     "записано."),
    "bad_words": (422, "Напишите решение своими словами - непустой текст до 1000 знаков; он "
                       "ляжет в карточку."),
    "unknown_channel": (404, "Канала нет в фабрике."),
    "batch_missing": (404, "Батча ролика нет на диске - карточку не из чего взять."),
    "unknown_video": (404, "Такого ролика в батче нет."),
    "not_accepted": (409, "Ролик не принят в журнале приёмки - решение по карточке принимают "
                          "только для принятого ролика."),
    "building": (409, "Карточка сейчас собирается - дождитесь итога сборки и посмотрите план "
                      "заново."),
    "no_card": (409, "У ролика нет карточки - сначала соберите её."),
    "card_ready": (409, "Карточка уже готова - решать нечего, её можно выкладывать."),
    "claims_not_failed": (409, "Карточка не готова не из-за утверждений: проверка утверждений "
                               "не провалилась или не запускалась. Решением такую не принять - "
                               "исправьте причины и соберите карточку заново."),
    "failing_unknown": (409, "Из карточки не читается, что именно не прошло проверку - "
                             "соберите её заново."),
    "note_claim_failed": (409, "Не прошло утверждение в названии, описании или тегах - их "
                               "переписывают (новый черновик и сборка заново), решением это не "
                               "принимается."),
    "card_problem": (409, "У карточки есть проблема, которая не относится к утверждениям "
                          "самого ролика - её исправляют и собирают заново, решением не "
                          "принять."),
    "no_video": (409, "Ролика нет в publish/ канала - карточка идёт за принятым роликом (его "
                      "место в копилке)."),
    "check_changed": (409, "Карточка или заметка изменились с момента плана - посмотрите план "
                           "заново."),
    "place_failed": (409, "Фабрика не смогла записать решение в карточку - ничего не записано; "
                          "строка фабрики в подробностях."),
    # the center's own
    "not_repo": (409, "Корень фабрики - не git-репозиторий: решение не закоммитить, ничего не "
                      "записано."),
    "dirty": (409, "В заметке ролика в publish/ есть изменения, которых нет в git. Центр не "
                   "смешает их со своим коммитом: сохраните их коммитом или отмените, потом "
                   "повторите."),
    "commit_refused": (409, "Решение записано в карточку, но git не принял коммит - файлы "
                            "остались изменёнными (см. подробности); посмотрите git status, "
                            "прежде чем повторять."),
}
#: Which ruling refusal speaks first.
RULING_ORDER = ("unknown_channel", "batch_missing", "unknown_video", "bad_who", "bad_words",
                "not_repo", "dirty", "not_accepted", "building", "no_card", "card_ready",
                "check_changed")

RULING_SCOPE = ("Решение касается только утверждений самого ролика - озвучки и надписей на "
                "экране: ролик уже собран, его слова карточка не меняет. Название, описание и "
                "теги проверку прошли; если их потом поправить или собрать карточку заново, "
                "решение снимается и карточка снова не готова.")
BUILD_WHAT = {
    False: ("Сборка карточки моделью: модель пишет название, описание и теги, затем проверка "
            "утверждений (CF-0555). Идёт отдельным процессом со своим журналом, обычно "
            "несколько минут."),
    True: ("Сборка карточки из вашего черновика: название, описание, хэштеги и теги - ваши, "
           "модель только проверяет утверждения (CF-0555). Идёт отдельным процессом со своим "
           "журналом."),
}
REPLACES_RU = {
    "ready": "Готовая карточка будет собрана заново - если новая выйдет не готовой, выкладывать "
             "будет нечего до новой сборки или решения.",
    "ruled": "Карточка принята вашим решением - сборка заново снимает решение: новую карточку "
             "проверят с нуля.",
    "not_ready": "Не готовая карточка будет заменена новой сборкой.",
}


def _cc():
    return factory.card_center()


def _pc():
    return factory.collect().card()


def _env():
    return FACTORY_KW.get("environ")


def _broken(e, what):
    return BatchFault(500, "factory_broken", f"Фабрика ответила ошибкой ({what}) - посмотрите "
                                             f"карточку, прежде чем повторять.",
                      [f"{type(e).__name__}: {e}"])


# ---------------------------------------------------------------- the state
def _run_short(run):
    if not run:
        return None
    cc = _cc()
    return dict(run, word=cc.OUTCOME_WORDS.get(run.get("code"), run.get("code")))


def _ruling_short(ruling):
    if not isinstance(ruling, dict):
        return None
    return {k: ruling.get(k) for k in ("by", "via", "words", "at")}


def card_block(root, batch_dir, slug, text=None):
    """{state, placeable, why, reasons, ruling, build} of a card's text (None:
    no card) and the last build of the video from the center."""
    pc, cc = _pc(), _cc()
    out = {"state": "none", "placeable": False, "why": None, "reasons": [], "ruling": None,
           "build": None, "state_ru": None}
    if text is not None:
        st = pc.card_status(text)
        out.update(state=st["state"], placeable=bool(st["placeable"]), why=st["why"],
                   reasons=[str(r) for r in st["reasons"] or []],
                   ruling=_ruling_short(st["ruling"]) if st["state"] == pc.RULED else None)
    if batch_dir is not None:
        try:
            out["build"] = _run_short(cc.last_run(Path(batch_dir), slug, Path(root), _env()))
        except OSError:
            out["build"] = None
        if out["build"] and out["build"]["code"] == "running":
            out["state"] = "building"
    out["state_ru"] = STATE_RU[out["state"]]
    return paths.clean(out, root)


def _ref(r, table):
    return dict(r, message=table.get(r.get("code"), (409, r.get("line") or r.get("code")))[1])


def _accepted_batch(root, cid, slug):
    """The batch of the channel's latest accepted video of this slug, or None."""
    acc = factory.collect().acceptance()
    try:
        rows = acc.entries(path=Path(root) / acc.ACCEPTANCE_LOG_REL)
    except Exception:                                           # noqa: BLE001
        return None
    hits = [r for r in rows if r.get("slug") == slug and r.get("verdict") == acc.ACCEPTED
            and acc.resolve_channel(r.get("channel"), root=Path(root)) == cid]
    hits.sort(key=lambda r: str(r.get("answered_at") or r.get("recorded_at") or ""))
    return hits[-1].get("batch_id") if hits else None


def _batch_id(root, cid, slug, batch_id):
    """The batch a card route means: the one named, else the latest accepted of the name -
    CC-0182 (CF-0920): unless two videos of it wait in the копилка, then 409 `namesakes`."""
    if not batch_id:
        waiting = publish.waiting_namesakes(root, cid, slug)
        if len(waiting) > 1:
            raise publish.namesakes_fault(cid, slug, waiting)
    bid = batch_id or _accepted_batch(root, cid, slug)
    if not bid:
        raise BatchFault(422, "batch_required", BUILD_RU["batch_required"][1],
                         [f"{slug}: no accepted row of {cid} in the acceptance log"])
    if not batches.SAFE_NAME.match(str(bid)):
        raise BatchFault(422, "invalid", f"«{bid}» - не имя батча.", [f"batch_id {bid!r}"])
    return bid


def _info(root, cid, slug, bid):
    cc = _cc()
    try:
        return cc.card_info(cid, slug, bid, root=Path(root), environ=_env())
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "состояние карточки") from e


def info(root, channel, slug, batch_id=None):
    """`card_info` of one video - the card's state as the center shows it."""
    cid = _channel(root, channel)
    bid = _batch_id(root, cid, slug, batch_id)
    got = _info(root, cid, slug, bid)
    refusals = [_ref(r, BUILD_RU) for r in got.get("refusals") or []]
    four = [r for r in refusals if BUILD_RU.get(r["code"], (409,))[0] == 404]
    if four:
        raise BatchFault(404, four[0]["code"], four[0]["message"],
                         paths.clean([r.get("line") or "" for r in four], root))
    out = dict(got, refusals=refusals, ruling=_ruling_short(got.get("ruling")),
               build=_run_short(got.get("build")), reasons=[str(r) for r in
                                                            got.get("reasons") or []])
    out["state_ru"] = STATE_RU.get(out.get("state"), out.get("state"))
    return paths.clean(out, root)


# ---------------------------------------------------------------- the build
def _draft_problems(draft):
    if draft is None:
        return []
    if not isinstance(draft, dict):
        return ["the draft is an object {title, about, hashtags, tags}"]
    return list(_pc().validate_draft(draft))


def _build_check(root, cid, slug, bound, prefix=""):
    """(the plan's answer, its fingerprint facts) - nothing started."""
    bid, draft = bound["batch_id"], bound.get("draft")
    got = _info(root, cid, slug, bid)
    refusals = [_ref(r, BUILD_RU) for r in got.get("refusals") or []]
    four = [r for r in refusals if BUILD_RU.get(r["code"], (409,))[0] == 404]
    if four:
        raise BatchFault(404, four[0]["code"], four[0]["message"],
                         paths.clean([r.get("line") or "" for r in four], root))
    problems = _draft_problems(draft)
    if problems:
        refusals.append(_ref({"code": "bad_draft", "line": "the draft: " + "; ".join(problems)},
                             BUILD_RU))
    build = _run_short(got.get("build"))
    if build and build.get("code") == "running":
        refusals.append(_ref({"code": "running", "line": f"{slug}: the build {build['run_id']} "
                                                        f"is going"}, BUILD_RU))
    state = got.get("state") or "none"
    ok = not refusals
    out = {"action": BUILD, "channel": cid, "slug": slug, "batch_id": bid, "ok": ok,
           "dry_run": True, "draft": draft, "with_draft": draft is not None,
           "what": BUILD_WHAT[draft is not None],
           "replaces": REPLACES_RU.get(state) if got.get("path") else None,
           "card": {"state": state, "state_ru": STATE_RU.get(state, state),
                    "placeable": bool(got.get("placeable")), "why": got.get("why"),
                    "reasons": [str(r) for r in got.get("reasons") or []],
                    "ruling": _ruling_short(got.get("ruling")), "build": build,
                    "path": got.get("path")},
           "problems": problems, "refusals": refusals,
           "why": refusals[0]["message"] if refusals else None, "by": BY, "via": VIA}
    facts = {"batch_id": bid, "slug": slug, "draft": draft, "state": state,
             "path": got.get("path"), "build": (build or {}).get("run_id"),
             "build_code": (build or {}).get("code"),
             "refusals": sorted(r["code"] for r in refusals)}
    return out, facts


def build_plan(root, channel, slug, batch_id=None, draft=None, prefix=""):
    """What «Собрать заново» would start - nothing started; a token when ok."""
    cid = _channel(root, channel)
    bound = {"batch_id": _batch_id(root, cid, slug, batch_id), "slug": slug, "draft": draft}
    out, facts = _build_check(root, cid, slug, bound, prefix)
    fp = _digest(facts)
    out = dict(out, fingerprint=fp, confirm=None, expires_in_s=None)
    if out["ok"]:
        out.update(confirm=_issue(root, BUILD, cid, fp, bound),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def launcher(channel, slug, by, via, batch_id, draft, root):
    """The factory's launch - the seam of the tests: no test starts a real
    build (a model)."""
    return _cc().card_build_launch(channel, slug, by, via, batch_id=batch_id, draft=draft,
                                   root=Path(root), environ=_env())


def _fault(refusals, table, root, extra=()):
    first = refusals[0]
    status, message = table.get(first["code"], (409, first.get("line") or first["code"]))
    return BatchFault(status, first["code"], message,
                      paths.clean([f"{r['code']}: {r.get('line')}" for r in refusals]
                                  + list(extra), root))


def _same_slug(got, slug, action):
    if got["bound"].get("slug") != slug:
        raise BatchFault(409, "confirm_mismatch", f"Подтверждение выдано для ролика "
                                                  f"«{got['bound'].get('slug')}», а не для "
                                                  f"«{slug}».",
                         [f"the {action} token is bound to another video"])


def build(root, channel, slug, token, prefix=""):
    """The confirmed «Собрать заново»: the token, the same plan, then
    `card_build_launch` by user via center - {ok, launched, run_id, pid, log,
    result_url, poll_s, ...}; the build goes on detached."""
    cid = _channel(root, channel)
    if not _LAUNCH.acquire(blocking=False):
        raise BatchFault(409, "busy", "Идёт другой запуск сборки карточки - подождите и "
                                      "запросите план заново.", ["one build confirm at a time"])
    try:
        got = _spend(root, BUILD, cid, token)
        _same_slug(got, slug, BUILD)
        b = got["bound"]
        out, facts = _build_check(root, cid, slug, b, prefix)
        if _digest(facts) != got["fingerprint"]:
            if out["refusals"]:
                raise _fault(out["refusals"], BUILD_RU, root)
            raise BatchFault(409, "check_changed", "Карточка или её сборка изменились с момента "
                                                   "плана - ничего не запущено; посмотрите план "
                                                   "заново.",
                             ["the fingerprint of the build plan differs from the plan's"])
        if out["refusals"]:
            raise _fault(out["refusals"], BUILD_RU, root)
        try:
            res = launcher(cid, slug, BY, VIA, b["batch_id"], b.get("draft"), root)
        except Exception as e:                                  # noqa: BLE001
            raise _broken(e, "запуск сборки карточки") from e
    finally:
        _LAUNCH.release()
    refusals = [_ref(r, BUILD_RU) for r in res.get("refusals") or []]
    if refusals:
        raise _fault(refusals, BUILD_RU, root, res.get("lines") or [])
    run_id = res.get("run_id")
    out = paths.clean({
        "action": BUILD, "channel": cid, "slug": slug, "batch_id": b["batch_id"],
        "ok": bool(res.get("ok")), "launched": bool(res.get("launched")),
        "skipped": res.get("skipped"), "run_id": run_id, "pid": res.get("pid"),
        "log": res.get("log"), "draft": res.get("draft"), "card": res.get("card"),
        "lines": list(res.get("lines") or []), "by": BY, "via": VIA,
        "poll_s": POLL_S if run_id else None}, root)
    # the route after: clean cuts any absolute path
    out["result_url"] = f"{prefix}/publish/{cid}/cards/build/{run_id}" if run_id else None
    return out


def result(root, channel, run_id):
    """`card_build_result(run_id)` + the Russian line of its code and a poll hint."""
    cid = _channel(root, channel)
    cc = _cc()
    if not cc.RUN_ID_RE.match(run_id or ""):
        raise BatchFault(422, "bad_run", f"«{run_id}» - не номер сборки карточки "
                                         f"(<ролик>-ГГГГММДДTЧЧММССZ).",
                         [f"run id {run_id!r}: {cc.RUN_ID_RE.pattern}"])
    try:
        got = cc.card_build_result(run_id, root=Path(root), environ=_env())
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "итог сборки карточки") from e
    acc = factory.collect().acceptance()
    theirs = got.get("channel")
    if got.get("run_id") is None or (theirs and acc.resolve_channel(
            theirs, root=Path(root)) != cid):
        raise BatchFault(404, "unknown_run", f"Сборки карточки «{run_id}» у канала нет.",
                         paths.clean([got.get("detail") or f"run {run_id} of {theirs}"], root))
    code = got.get("code")
    return paths.clean(dict(got, word=cc.OUTCOME_WORDS.get(code, code),
                            text_ru=OUTCOME_RU.get(code, got.get("line")),
                            poll_s=None if got.get("done") else POLL_S), root)


# ---------------------------------------------------------------- the ruling
def _ruling_check(root, cid, slug, bound):
    """(the plan's answer, its facts): the factory's ruling_plan + not_repo /
    dirty over what the ruling writes."""
    cc, gc = _cc(), factory.git_commit()
    try:
        res = cc.ruling_plan(cid, slug, bound["batch_id"], BY, VIA, bound.get("words"),
                             root=Path(root), now=FACTORY_KW.get("now"), environ=_env())
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "план решения по карточке") from e
    res = paths.clean(res, root)
    top, dirty = [], {}
    if not gc.is_repo(root):
        top.append({"code": "not_repo", "line": f"{Path(root).name}: not a git work tree"})
    else:
        rels = [p for p in (res.get("card"), res.get("path")) if p]
        dirty = publish_stash._status(root, rels) if rels else {}
        if dirty:
            top.append({"code": "dirty", "line": "uncommitted: " + ", ".join(
                f"{xy.strip() or '?'} {p}" for p, xy in sorted(dirty.items()))})
    refusals = [_ref(r, RULING_RU) for r in top + list(res.get("refusals") or [])]
    refusals.sort(key=lambda r: RULING_ORDER.index(r["code"]) if r["code"] in RULING_ORDER
                  else len(RULING_ORDER))
    ok = bool(res.get("ok")) and not refusals
    out = dict(res, action=RULING, ok=ok, dry_run=True, refusals=refusals,
               why=refusals[0]["message"] if refusals else None, scope=RULING_SCOPE,
               state_ru=STATE_RU.get(res.get("state"), res.get("state")))
    facts = {"batch_id": bound["batch_id"], "slug": slug, "words": bound.get("words"),
             "sha256": res.get("sha256"), "failing": res.get("failing"),
             "refusals": sorted(r["code"] for r in refusals), "dirty": sorted(dirty)}
    return out, facts


def ruling_plan(root, channel, slug, batch_id=None, words=None):
    """What the user's ruling would write - nothing written; a token when ok."""
    cid = _channel(root, channel)
    bid = _batch_id(root, cid, slug, batch_id)
    bound = {"batch_id": bid, "slug": slug, "words": words}
    out, facts = _ruling_check(root, cid, slug, bound)
    four = [r for r in out["refusals"] if RULING_RU.get(r["code"], (409,))[0] == 404]
    if four:
        raise BatchFault(404, four[0]["code"], four[0]["message"],
                         paths.clean([r.get("line") or "" for r in four], root))
    fp = _digest(facts)
    out = dict(out, fingerprint=fp, confirm=None, expires_in_s=None)
    if out["ok"]:
        out.update(confirm=_issue(root, RULING, cid, fp, dict(bound, base=out["sha256"])),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def _ruling_message(cid, slug, res):
    failing = "\n".join(f"- `{f.get('code')}` [{f.get('where')}] {f.get('text') or ''}".rstrip()
                        for f in res.get("failing") or [])
    return (f"Карточка: {slug} принята решением пользователя ({BY}, {VIA})\n\n"
            f"CC-0127: решение пользователя по карточке из центра (card_center.ruling_confirm, "
            f"CF-0747) - не прошли только утверждения самого ролика:\n{failing}\n"
            f"Слово пользователя: «{(res.get('words') or '').strip()}»\n\n"
            + channels._trailers(cid, RULING) + "\n")


def ruling(root, channel, slug, token):
    """The confirmed ruling - see the module's docstring."""
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
            return _ruling(root, cid, slug, token)
        finally:
            videos._WRITE.release()
    finally:
        publish._WRITE.release()


def _ruling(root, cid, slug, token):
    got = _spend(root, RULING, cid, token)
    _same_slug(got, slug, RULING)
    b = got["bound"]
    out, facts = _ruling_check(root, cid, slug, b)
    if _digest(facts) != got["fingerprint"]:
        if out["refusals"] and out["refusals"][0]["code"] != "check_changed":
            raise _fault(out["refusals"], RULING_RU, root, out.get("lines") or [])
        raise BatchFault(409, "check_changed", RULING_RU["check_changed"][1],
                         ["the fingerprint of the ruling plan differs from the plan's"])
    if out["refusals"]:
        raise _fault(out["refusals"], RULING_RU, root, out.get("lines") or [])
    cc = _cc()
    try:
        res = cc.ruling_confirm(cid, slug, b["batch_id"], b["base"], BY, VIA, b["words"],
                                root=Path(root), now=FACTORY_KW.get("now"), environ=_env())
    except Exception as e:                                      # noqa: BLE001
        raise _broken(e, "решение по карточке") from e
    res = paths.clean(res, root)
    if not res.get("written"):
        refusals = [_ref(r, RULING_RU) for r in res.get("refusals") or []] or \
            [_ref({"code": "place_failed", "line": "nothing written"}, RULING_RU)]
        raise _fault(refusals, RULING_RU, root, res.get("lines") or [])
    touched = sorted(res.get("touched") or [])
    gc = factory.git_commit()
    commit, committed = None, []
    if touched:
        try:
            commit, committed = publish_stash.commit_paths(root, touched,
                                                           _ruling_message(cid, slug, res))
        except gc.CommitError as e:
            raise BatchFault(409, "commit_refused", RULING_RU["commit_refused"][1],
                             paths.clean([str(e), *e.details, "touched: " + ", ".join(touched)],
                                         root)) from e
    return paths.clean(dict(res, action=RULING, ok=True, dry_run=False,
                            refusals=[], scope=RULING_SCOPE, touched=touched,
                            committed=committed, commit=commit,
                            state_ru=STATE_RU.get(res.get("state"), res.get("state"))), root)
