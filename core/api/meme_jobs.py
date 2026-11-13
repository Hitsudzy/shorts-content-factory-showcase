"""CC-0075: the meme desk's long jobs in the center - the cutout (Apple
Vision) and the trim of blank bands, each a plan and a confirm, run in the
background by the factory, polled by the center. Only through the factory's
own functions (`scripts/meme_desk.py`, CF-0760/CF-0755, `factory.meme_desk`):

    cutout_available()                  the plan: can this machine cut at all
    cutout_entries(dry_run=True)        POST /api/memes/{c}/cutout/plan
    trim_blank_entries(dry_run=True)    POST /api/memes/{c}/trim/plan
    start_job(kind, params, by="user", via="center", commit=True)
                                        POST /api/memes/{c}/cutout | trim {confirm}
                                        - in the launcher child, never here
    list_jobs(channel, limit)           GET  /api/memes/{c}/jobs
    job_status(job_id, channel)         GET  /api/memes/{c}/jobs/{job_id}

**The plan** (nothing written): the factory's dry run of the job, the bank's
`index.json` sha256, the job's `params` (only what the user asked), `ok` /
`why` and, when ok, a confirm token (`batches` store, actions `meme_cutout`
/ `meme_trim`, CONFIRM_TTL s, single use) bound to the channel and the
params. The fingerprint is of `index.json` + the dry run's result + the
params (+ `cutout_available` for the cutout). The cutout's dry run does not
ask Vision: the plan says `available` and its reason itself, a machine that
cannot cut gets no token, and Vision's own refusals (an empty mask, several
figures) are known only after the run - the plan says so in `notes`.

**The confirm**: a job running on the bank refuses first (409 `job_active`,
the token kept), then the token spent, the plan made again (`check_changed`
when its fingerprint moved; the cutout unavailable now - `cutout_unavailable`),
then `start_job` in a child of `api/child.py` (`_LAUNCHER`, bounded by
LAUNCH_TIMEOUT_S): the factory re-checks by the same dry run, takes the one
slot of the machine (`job_running` with the running job's id otherwise),
starts `meme_desk.py job-run` in a session of its own and returns at once;
the child prints one JSON line and ends. The center never waits on the job
nor signals it - there is no cancel. `run_launcher` is the seam of the tests:
no test starts a real job.

**The polling** (not SSE, as the batches): `GET …/jobs/{job_id}` is
`job_status` plus `poll_s` (POLL_S while running, null when done), the
Russian words of the state and the kind, and the routes of the entries in
the result (`urls`: the cut-out is the desk's media `kind=cut`). `GET …/jobs`
is `list_jobs` newest first plus the running one. Every answer goes through
`api/paths.clean`: the log, the state file, the originals' folder - relative
to the root, nothing absolute; `error.log_tail` stays as text.

CF-0761: every meme plan (apply, accept, the jobs') also reads the machine's
slot (`active_job()`, no lock): an alive job on ANOTHER bank makes the plan
`ok: false` with `machine_job` and «одна задача на машину»; a dead slot is
not busy; the same bank is the `job` above. The confirms do not read it -
another bank's job is the factory's `job_running` at start_job.

While a job runs on a bank, the center refuses its own writes there - the
marks, apply, the candidates' yes and a new start (`memes.refuse_while_job`,
409 `job_active` with the job's id); the terminal's desk is not held by it.

CC-0076, the adds, the contact sheet and the embed - rows of the same table:

    plan_add_image(...)                 POST /api/memes/{c}/add-image/plan
    plan_add_gif(..., local=False)      POST /api/memes/{c}/add-gif/plan
    plan_sheet(..., local=False)        POST /api/memes/{c}/sheet/plan
    (no dry plan in the factory)        POST /api/memes/{c}/embed/plan
    start_job("add_image" | "add_gif" | "sheet" | "embed", params)
                                        POST /api/memes/{c}/add-image | add-gif | sheet | embed
    <bank>/_desk/sheets/<name>          GET  /api/memes/{c}/sheets/{name}

The center hands the factory only http(s) addresses - `url` and `video` are
checked here first (`_http`: 422 `bad_url`, the factory's plan not asked) -
and `local=False` always: no local path ever comes from the client. The
plans are the factory's (nothing fetched, no child, no write) plus `notes`
in Russian (what is downloaded or already there, that the meme comes in
unchecked, the embedding recomputed; CC-0136: plain words - the channel's
display name, no file names, no tool names, decimal commas; the worst time
is `max_seconds_word` alone, not a note); their
refusals pass with the factory's code and text (the request's - bad_url,
bad_suffix, no_source_url, bad_span, too_many_frames, bad_entry - 422; the
bank's - duplicate_id, file_exists - 409). The embed has no dry plan in the
factory (`start_job` checks only that the bank is there): its plan is the
center's own words, the bank and the step's ceiling. A sheet's `out` is one
file name (the center refuses a separator or `..`, 422 `bad_params`), its
`sheet_url` the route that serves it once made. In a job's result the new
entry of an add carries its `urls` (file, cut: null, thumb), a sheet its
`sheet_url`; `scene_cuts` / `cuts_inside` as the factory says them.

CC-0160: a job's commit is the desk's (CF-0847) - every kind starts with
`commit=True` and its `channel`; the center does not commit a job's files.

`SPECS` is the table of the jobs the center plans and starts.
`FACTORY_KW["environ"]` - the launcher child's environment on top of the
API's (the tests' `MEME_DESK_JOBS_DIR`); empty in production.
"""
import json
import math
import os
import sys
from pathlib import Path, PurePath
from urllib.parse import quote, urlsplit

from . import batches, child, factory, memes, paths
from .batches import BatchFault, _channel, _digest, _issue, _spend

BY, VIA = memes.WRITE_BY, memes.VIA
POLL_S = 3
LAUNCH_TIMEOUT_S = 120
LIST_LIMIT = 20
CUTOUT, TRIM = "meme_cutout", "meme_trim"
ADD_IMAGE, ADD_GIF, SHEET, EMBED = "meme_add_image", "meme_add_gif", "meme_sheet", "meme_embed"
ACTIONS = {CUTOUT: ("план вырезки", "вырезка не запущена", "вырезки мемов канала"),
           TRIM: ("план среза пустых полей", "срез полей не запущен",
                  "среза пустых полей мемов канала"),
           ADD_IMAGE: ("план добавления картинки", "картинка не добавлена",
                       "добавления картинки в банк канала"),
           ADD_GIF: ("план нарезки GIF", "GIF не нарезан", "нарезки GIF в банк канала"),
           SHEET: ("план листа кадров", "лист кадров не сделан", "листа кадров банка канала"),
           EMBED: ("план пересчёта признаков для поиска похожих мемов",
                   "признаки для поиска похожих мемов не пересчитываются",
                   "пересчёта признаков для поиска похожих мемов банка канала")}
#: The contact sheet's names (`meme_desk._sheet_check`: .jpg/.jpeg/.png).
SHEET_SUFFIXES = (".jpg", ".jpeg", ".png")
batches.register_actions(ACTIONS)
#: The launcher child's environment on top of the API's - empty in production.
FACTORY_KW = memes.JOBS_KW
STATE_WORDS = {"running": "идёт", "done": "готово", "failed": "не удалась",
               "interrupted": "оборвалась"}
#: A start's refusal by the factory's code -> its HTTP status (else 409).
_START_STATUS = {"bad_kind": 422, "bad_params": 422, "bad_who": 500, "unknown_id": 422,
                 "not_cutout": 422, "bad_ids": 422, "spawn_failed": 500,
                 # CC-0076: the adds' and the sheet's refusals of the request
                 "bad_url": 422, "bad_suffix": 422, "no_source_url": 422, "bad_span": 422,
                 "too_many_frames": 422, "bad_entry": 422, "outside_bank": 422,
                 "video_failed": 422}
#: The plan's own refusals of what the user asked (an id not in the bank, a
#: GIF, a still without the user's tick) - 422, the request, not the bank.
_PLAN_STATUS = {"unknown_id": 422, "not_cutout": 422, "bad_ids": 422}
LAUNCH_FAILED = ("Запуск задачи не ответил - неизвестно, стартовала ли она; посмотрите список "
                 "задач банка, прежде чем повторять.")

# The launcher: the factory's start_job, one JSON line out (a refusal too).
_LAUNCHER = r"""
import importlib.util, json, sys
mod_path, kind, params, channel, lib_root, repo = sys.argv[1:7]
spec = importlib.util.spec_from_file_location("meme_desk_for_the_center", mod_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
try:
    out = mod.start_job(kind, json.loads(params), channel=channel, by="user", via="center",
                        root=lib_root, repo=repo, commit=True)
    out = dict(out, ok=True)
except mod.MemeDeskError as e:
    out = {"ok": False, "code": e.code, "text": e.text, "en": e.en,
           "job_id": getattr(e, "job_id", None)}
print(json.dumps(out, ensure_ascii=False))
"""


def _desk():
    return factory.meme_desk()


def _lib(root):
    return memes._lib(root)


def _bank_word(root, cid):
    d = _desk()
    name, folder = memes._call(d.resolve_bank, cid, None, _lib(root), Path(root))
    return name or d.lib.KIND_FOLDERS[d.KIND], Path(folder)


# ---------------------------------------------------------------- the jobs' plans
def _cutout_params(bound):
    p = {}
    if bound.get("ids") is not None:
        p["ids"] = list(bound["ids"])
    if bound.get("force"):
        p["force"] = True
    return p


def _cutout_now(root, cid, bound):
    """(plan fields, facts, blocked): cutout_available + cutout_entries(dry_run)."""
    d = _desk()
    params = _cutout_params(bound)
    available, reason = d.cutout_available()
    got = memes._call(d.cutout_entries, cid, dry_run=True, by=BY, via=VIA, root=_lib(root),
                      repo=Path(root), statuses=_PLAN_STATUS, **params)
    notes = ["Отказы распознавания (Vision)\u00a0— пустая маска, несколько фигур, вырезано всё или "
             "ничего\u00a0— станут известны только после прогона, в плане их нет; рамка фигуры и "
             "её доля в кадре тоже появятся после него."]
    if got["unchanged"] and not params.get("force"):
        notes.append(f"Не меняются (вырезка свежая): {', '.join(got['unchanged'])}\u00a0— заново "
                     f"только с force.")
    if got["missing"]:
        notes.append(f"Нет исходного файла в банке: {', '.join(got['missing'])}.")
    blocked = None
    if not available:
        why = f"Вырезка на этой машине недоступна: {reason}."
        blocked = ("cutout_unavailable", why)
    elif not got["made"]:
        why = ("Вырезать нечего: ни у одного мема с отметкой «можно вырезать» нет новой "
               "вырезки" + (" (чтобы вырезать заново, возьмите force)"
                            if got["unchanged"] and not params.get("force") else "") + ".")
    else:
        why = None
    fields = dict(got, available=bool(available), available_reason=reason, notes=notes,
                  ok=why is None, why=why)
    return fields, {"available": [bool(available), reason], "plan": got}, blocked


def _trim_params(bound):
    return {"id": bound["id"]} if bound.get("id") is not None else {}


def _trim_now(root, cid, bound):
    """(plan fields, facts, blocked): trim_blank_entries(dry_run)."""
    d = _desk()
    params = _trim_params(bound)
    got = memes._call(d.trim_blank_entries, cid, dry_run=True, by=BY, via=VIA,
                      root=_lib(root), repo=Path(root), statuses=_PLAN_STATUS, **params)
    notes = []
    if got["trim"]:
        notes.append("У срезанных мемов сбрасываются признаки для поиска похожих мемов\u00a0— "
                     "после среза банк пересчитает их сам; оригиналы остаются в папке "
                     "оригиналов банка.")
    recut = [r["id"] for r in got["trim"] if r.get("recut")]
    if recut:
        notes.append(f"У {', '.join(recut)} есть вырезка\u00a0— после среза её надо сделать "
                     f"заново (исходник изменится).")
    if got["under"]:
        notes.append(f"После среза картинка растянулась бы сильнее допустимого"
                     f"{_ceiling_words(root)}: {', '.join(r['id'] for r in got['under'])}\u00a0— "
                     f"эти файлы остаются целыми, решает пользователь (заменить или убрать).")
    if got["left"]:
        notes.append(f"Не режутся: {', '.join(r['id'] for r in got['left'])}\u00a0— причина "
                     f"указана у каждого.")
    why = None if got["trim"] else ("Резать нечего: ни у одного мема нет пустых полей шире "
                                    "допустимого (или такие мемы не режутся\u00a0— причина указана "
                                    "у каждого).")
    fields = dict(got, embed=True, notes=notes, ok=why is None, why=why)
    return fields, {"plan": got}, None


# ---------------------------------------------------------------- the adds, the sheet, the embed (CC-0076)
def _http(value, what, word):
    """The center's own check of an address it hands to the factory (CC-0076):
    http(s) with a host, nothing else - 422 `bad_url` before the factory is
    asked. A local path never goes from the center (local=False always)."""
    ok = isinstance(value, str) and bool(value) and not any(c in value for c in " \t\r\n\0")
    scheme = None
    if ok:
        try:
            u = urlsplit(value)
            scheme = u.scheme
            ok = scheme in ("http", "https") and bool(u.hostname)
        except ValueError:
            ok = False
    if not ok:
        raise BatchFault(422, "bad_url", f"{word}: нужен адрес http(s)://... - локальный путь, "
                                         f"file:// и другие схемы центр не принимает.",
                         [f"{what} must be an http(s) URL with a host (got scheme "
                          f"{scheme or 'none'!r}); the center never passes a local path"])
    return value


def human_seconds(s):
    """`max_seconds` as a person reads it: «до 45 с», «до 33 мин», «до 2 ч 1 мин»."""
    if s is None:
        return None
    s = int(math.ceil(float(s)))
    if s < 60:
        return f"до {s} с"
    m = int(math.ceil(s / 60))
    if m < 60:
        return f"до {m} мин"
    return f"до {m // 60} ч" + (f" {m % 60} мин" if m % 60 else "")


def _num(x):
    """A number as the center writes it: «26,5», «2», never «26.5» (CC-0136)."""
    return f"{x:g}".replace(".", ",")


def _ceiling_words(root):
    """« (допустимо до 1,25)» from inserts/meme.json, or nothing when it does
    not read - the note keeps its words without the figure."""
    try:
        ceiling = _desk().max_upscale(Path(root))
    except (OSError, ValueError, KeyError, TypeError):
        return ""
    return f" (допустимо до {ceiling:g})".replace(".", ",")


def _fetch_note(got, what):
    if got.get("cached"):
        return f"Видео уже скачано\u00a0— заново не скачивается, {what} из уже скачанного видео."
    return ("Будет скачано видео по ссылке\u00a0— только картинка, без звука, до 720p; один раз "
            "для листа и GIF.")


#: The adds' shared notes (CC-0134: plain words, no field names).
_PENDING = "Мем войдёт в банк непроверенным\u00a0— его надо будет отметить на столе."
_REINDEX = "После добавления банк пересчитает признаки для поиска похожих мемов."


#: The adds' and the sheet's refusals of what the user asked - 422, the
#: request, not the bank (duplicate_id and file_exists stay 409: the bank).
_ADD_STATUS = dict(_PLAN_STATUS, bad_url=422, bad_suffix=422, no_source_url=422, bad_span=422,
                   too_many_frames=422, bad_entry=422, bad_params=422, outside_bank=422,
                   video_failed=422)


def _add_image_params(bound):
    p = {"meme_id": bound["id"], "url": bound["url"], "source_url": bound["source_url"],
         "description": bound["description"], "tags": bound["tags"]}
    if bound.get("notes") is not None:
        p["notes"] = bound["notes"]
    return p


def _add_image_now(root, cid, bound):
    """(plan fields, facts, blocked): plan_add_image (no download, no write)."""
    d = _desk()
    got = memes._call(d.plan_add_image, **_add_image_params(bound), channel=cid, by=BY, via=VIA,
                      root=_lib(root), repo=Path(root), statuses=_ADD_STATUS)
    mb = d.MAX_IMAGE_BYTES // (1024 * 1024)
    notes = [f"Будет скачана картинка по ссылке (до {mb} МБ)\u00a0— она ляжет в банк мемов "
             f"канала {memes.channel_title(root, cid)}.", _PENDING,
             "Пустую полосу под подпись срежут, если она есть (об этом скажет пометка о "
             "срезе); если файл не картинка, залит одним тоном или растянулся бы сильнее "
             f"допустимого{_ceiling_words(root)}\u00a0— отказ после скачивания, банк не меняется.",
             _REINDEX]
    return (dict(got, dry_run=True, max_seconds_word=human_seconds(got["max_seconds"]),
                 notes=notes, ok=True, why=None), {"plan": got}, None)


def _add_gif_params(bound):
    p = {"meme_id": bound["id"], "video": bound["video"], "start": bound["start"],
         "end": bound["end"], "description": bound["description"], "tags": bound["tags"],
         "local": False}
    for k in ("source_url", "notes"):
        if bound.get(k) is not None:
            p[k] = bound[k]
    return p


def _add_gif_now(root, cid, bound):
    """(plan fields, facts, blocked): plan_add_gif (no fetch, no child, no write)."""
    d = _desk()
    got = memes._call(d.plan_add_gif, **_add_gif_params(bound), channel=cid, by=BY, via=VIA,
                      root=_lib(root), repo=Path(root), statuses=_ADD_STATUS)
    span = got["span"]
    notes = [_fetch_note(got, "GIF режется"),
             f"Из отрезка {_num(span['start_s'])}–{_num(span['end_s'])} с будет нарезан "
             f"беззвучный GIF в банк мемов канала {memes.channel_title(root, cid)}.",
             f"Смены сцен внутри отрезка станут известны после прогона\u00a0— на них GIF прыгнет; "
             "отрезок сужают по листу кадров.", _PENDING, _REINDEX]
    return (dict(got, dry_run=True, max_seconds_word=human_seconds(got["max_seconds"]),
                 notes=notes, ok=True, why=None), {"plan": got}, None)


def _sheet_params(bound):
    p = {"video": bound["video"], "local": False}
    for k in ("start", "end", "every", "out"):
        if bound.get(k) is not None:
            p[k] = bound[k]
    return p


def _sheet_now(root, cid, bound):
    """(plan fields, facts, blocked): plan_sheet (no fetch, no write)."""
    d = _desk()
    got = memes._call(d.plan_sheet, **_sheet_params(bound), channel=cid,
                      root=_lib(root), repo=Path(root), statuses=_ADD_STATUS)
    span = got["span"]
    _bank, folder = _bank_word(root, cid)
    exists = (Path(folder) / got["file"]).is_file()
    till = f"{_num(span['end_s'])} с" if span["end_s"] is not None else "конца видео"
    frames = (f"{span['frames']} кадров" if span["frames"] is not None else
              f"число кадров станет известно после извлечения (если больше "
              f"{d.MAX_SHEET_FRAMES}\u00a0— отказ)")
    notes = [_fetch_note(got, "кадры берутся"),
             f"Лист: кадр каждые {_num(span['every_s'])} с от {_num(span['start_s'])} с до "
             f"{till}\u00a0— {frames}; и смены сцен этого отрезка.",
             "Лист ляжет в папку листов банка; в банк ничего не добавляется."]
    if exists:
        notes.append("Лист с таким именем уже есть\u00a0— будет перезаписан.")
    return (dict(got, dry_run=True, overwrites=exists,
                 max_seconds_word=human_seconds(got["max_seconds"]), notes=notes, ok=True,
                 why=None), {"plan": got, "exists": exists}, None)


def _embed_params(_bound):
    return {}


def _embed_now(root, cid, _bound):
    """(plan fields, facts, blocked): the factory has no dry plan of the
    embed (start_job checks only that the bank is there) - the plan is the
    center's own words, the bank and the ceiling of the step."""
    d = _desk()
    bank, _folder = _bank_word(root, cid)
    seconds = d.PROBE_TIMEOUT_SECONDS + d.EMBED_TIMEOUT_SECONDS
    got = {"bank": bank, "steps": ["embedding"], "max_seconds": seconds}
    notes = [f"Признаки для поиска похожих мемов будут пересчитаны заново для всего банка мемов "
             f"канала {memes.channel_title(root, cid)}; файлы и отметки мемов не меняются.",
             "Заранее посчитать нельзя: перед запуском фабрика проверит, что банк свободен."]
    return (dict(got, dry_run=True, max_seconds_word=human_seconds(seconds), notes=notes,
                 ok=True, why=None), {"plan": got}, None)


#: action -> the job the center plans and starts: its factory kind, the
#: params of the confirm (from the bound plan input), the plan's maker.
SPECS = {CUTOUT: {"kind": "cutout", "params": _cutout_params, "now": _cutout_now,
                  "what": "вырезка не запущена"},
         TRIM: {"kind": "trim_blank", "params": _trim_params, "now": _trim_now,
                "what": "срез полей не запущен"},
         ADD_IMAGE: {"kind": "add_image", "params": _add_image_params, "now": _add_image_now,
                     "what": "картинка не добавлена"},
         ADD_GIF: {"kind": "add_gif", "params": _add_gif_params, "now": _add_gif_now,
                   "what": "GIF не нарезан"},
         SHEET: {"kind": "sheet", "params": _sheet_params, "now": _sheet_now,
                 "what": "лист кадров не сделан"},
         EMBED: {"kind": "embed", "params": _embed_params, "now": _embed_now,
                 "what": "признаки для поиска похожих мемов не пересчитываются"}}


def _check(root, cid, action, bound):
    spec = SPECS[action]
    _bank, folder = _bank_word(root, cid)
    ifp = memes._fp(folder / memes.INDEX)
    fields, facts, blocked = spec["now"](root, cid, bound)
    params = spec["params"](bound)
    facts = dict(facts, action=action, channel=cid, params=params, index=ifp)
    return dict(fields, index_fingerprint=ifp, params=params), facts, blocked


def plan(root, channel, action, bound):
    """The job's plan (nothing written) and a confirm token when ok and no
    job runs on the bank."""
    cid = _channel(root, channel)
    out, facts, _blocked = _check(root, cid, action, bound)
    fp = _digest(facts)
    out = memes.hold_plan(dict(out, action=action, channel=cid, kind=SPECS[action]["kind"],
                               fingerprint=fp, confirm=None, expires_in_s=None),
                          root, cid, "новую задачу сейчас не запустить")
    if out["ok"]:
        out.update(confirm=_issue(root, action, cid, fp, bound),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def cutout_plan(root, channel, ids=None, force=False):
    if ids is not None and (not isinstance(ids, list) or not ids):
        raise BatchFault(422, "bad_ids", "Выберите хотя бы один мем (или не указывайте ids - "
                                         "тогда все с отметкой «можно вырезать»).",
                         ["ids: an empty list; omit it for every cutout: true still"])
    return plan(root, channel, CUTOUT, {"ids": ids, "force": bool(force)})


def trim_plan(root, channel, meme_id=None):
    return plan(root, channel, TRIM, {"id": meme_id})


def add_image_plan(root, channel, meme_id, url, source_url, description, tags, notes=None):
    """plan_add_image: the center's own http(s) check of `url` first."""
    _http(url, "url", "Адрес картинки")
    return plan(root, channel, ADD_IMAGE, {"id": meme_id, "url": url, "source_url": source_url,
                                           "description": description, "tags": tags,
                                           "notes": notes})


def add_gif_plan(root, channel, meme_id, video, start, end, description, tags, source_url=None,
                 notes=None):
    """plan_add_gif with local=False: the center's own http(s) check of `video`
    first - the center never names a local file."""
    _http(video, "video", "Адрес видео")
    return plan(root, channel, ADD_GIF, {"id": meme_id, "video": video, "start": start,
                                         "end": end, "description": description, "tags": tags,
                                         "source_url": source_url, "notes": notes})


def _sheet_name(out):
    if out is None:
        return None
    if not isinstance(out, str) or not out or out in (".", "..") or any(
            c in out for c in "/\\\0"):
        raise BatchFault(422, "bad_params", "Имя листа - одно имя файла (.jpg/.png) без папок: "
                                            "лист ляжет в <банк>/_desk/sheets/.",
                         ["out: one file name under <bank>/_desk/sheets/, no separator, no .."])
    return out


def sheet_plan(root, channel, video, start=None, end=None, every=None, out=None, prefix=""):
    """plan_sheet with local=False: the center's http(s) check of `video`, a
    plain name for `out`; `sheet_url` - where the sheet is served once made."""
    _http(video, "video", "Адрес видео")
    got = plan(root, channel, SHEET, {"video": video, "start": start, "end": end,
                                      "every": every, "out": _sheet_name(out)})
    return dict(got, sheet_url=_sheet_url(prefix, got["channel"], PurePath(got["file"]).name))


def embed_plan(root, channel):
    """The embed's plan - the center's own (no dry plan in the factory)."""
    return plan(root, channel, EMBED, {})


# ---------------------------------------------------------------- the confirm
def run_launcher(cmd, cwd, env):
    """The launch child (`child.run`, bounded by LAUNCH_TIMEOUT_S): (returncode,
    stdout, stderr). A seam of the tests - none of them starts a real job."""
    return child.run(cmd, cwd=cwd, env=env, timeout=LAUNCH_TIMEOUT_S)


def _env():
    env = FACTORY_KW.get("environ")
    return None if env is None else {**os.environ, **env}


def start(root, cid, kind, params):
    """`start_job(kind, params, channel, by="user", via="center", commit=True)`
    in the launcher child: {job_id, bank, kind, pid, log, state_file}; the
    factory's refusal is its code and Russian text."""
    d = _desk()
    cmd = [sys.executable, "-c", _LAUNCHER, str(d.__file__), kind, json.dumps(params), cid,
           str(_lib(root)), str(root)]
    try:
        rc, out, err = run_launcher(cmd, str(root), _env())
    except (child.Timeout, OSError) as e:
        raise BatchFault(500, "launch_failed", LAUNCH_FAILED,
                         paths.clean([f"{type(e).__name__}: {e}"], root)) from None
    lines = [ln for ln in (out or "").splitlines() if ln.strip()]
    try:
        res = json.loads(lines[-1]) if rc == 0 and lines else None
    except ValueError:
        res = None
    if not isinstance(res, dict):
        tail = [ln for ln in (err or "").splitlines() if ln.strip()][-5:]
        raise BatchFault(500, "launch_failed", LAUNCH_FAILED,
                         paths.clean([f"exit {rc}"] + tail, root))
    if not res.get("ok"):
        code = res.get("code") or "factory_broken"
        details = [f"MemeDeskError({code}): {res.get('en') or res.get('text')}"]
        if res.get("job_id"):
            details.append(f"running job: {res['job_id']}")
        raise BatchFault(_START_STATUS.get(code, 409), code,
                         res.get("text") or "Задача не запущена.", paths.clean(details, root))
    return res


def confirm(root, channel, action, token, prefix=""):
    """The confirmed start: no job on the bank (the token kept), the token
    spent, the plan again (the same fingerprint), then start_job in the
    launcher child - {action, channel, kind, bank, job_id, log, poll_s,
    status_url}."""
    cid = _channel(root, channel)
    spec = SPECS[action]
    memes._locked()
    try:
        memes.refuse_while_job(root, cid, spec["what"])
        tok = _spend(root, action, cid, token)
        _out, facts, blocked = _check(root, cid, action, tok["bound"])
        if blocked is not None:
            code, why = blocked
            raise BatchFault(409, code, f"{why} Задача не запущена.",
                             [f"{action}: {code} at the confirm; the token is spent"])
        if _digest(facts) != tok["fingerprint"]:
            raise BatchFault(409, "check_changed", "Банк изменился с момента плана - задача не "
                                                   "запущена; посмотрите план заново.",
                             ["the fingerprint of index.json + the dry run + the params "
                              "differs from the plan's"])
        res = start(root, cid, spec["kind"], spec["params"](tok["bound"]))
        out = paths.clean({"action": action, "channel": cid, "kind": res.get("kind"),
                           "bank": res.get("bank"), "job_id": res["job_id"],
                           "log": res.get("log"), "poll_s": POLL_S}, root)
        # the route after the cut - `/api/memes/...` is no path of this machine
        return dict(out, status_url=_status_url(prefix, cid, res["job_id"]))
    finally:
        memes._WRITE.release()


def cutout(root, channel, token, prefix=""):
    return confirm(root, channel, CUTOUT, token, prefix)


def trim(root, channel, token, prefix=""):
    return confirm(root, channel, TRIM, token, prefix)


def add_image(root, channel, token, prefix=""):
    return confirm(root, channel, ADD_IMAGE, token, prefix)


def add_gif(root, channel, token, prefix=""):
    return confirm(root, channel, ADD_GIF, token, prefix)


def sheet(root, channel, token, prefix=""):
    return confirm(root, channel, SHEET, token, prefix)


def embed(root, channel, token, prefix=""):
    return confirm(root, channel, EMBED, token, prefix)


# ---------------------------------------------------------------- the polling
def _status_url(prefix, cid, job_id):
    return f"{prefix}/memes/{quote(cid, safe='')}/jobs/{quote(job_id, safe='')}"


def _sheet_url(prefix, cid, name):
    return f"{prefix}/memes/{quote(cid, safe='')}/sheets/{quote(name, safe='')}"


def sheet_path(root, channel, name):
    """`<bank>/_desk/sheets/<name>` through the path guard (`factory.contained`):
    one name with a sheet's suffix, inside that folder, a file - else 404."""
    cid = _channel(root, channel)
    bank, _folder = _bank_word(root, cid)
    ok = isinstance(name, str) and PurePath(name).suffix.lower() in SHEET_SUFFIXES
    p = factory.contained(root, *memes.INSERTS, bank, memes.DESK, _desk().SHEETS,
                          name) if ok else None
    if p is None:
        raise BatchFault(404, "outside_bank", "Лист кадров отдаётся только из <банк>/_desk/"
                                              "sheets/ и только .jpg/.jpeg/.png.",
                         [f"not a sheet name inside {'/'.join(memes.INSERTS)}/{bank}/"
                          f"{memes.DESK}/sheets (factory.contained, {'/'.join(SHEET_SUFFIXES)})"])
    if not p.is_file():
        raise BatchFault(404, "no_file", f"Листа {name} нет в банке {bank}.",
                         [f"no {'/'.join(memes.INSERTS)}/{bank}/{memes.DESK}/sheets/{name}"])
    return p


#: The result's rows of entries that get their routes: (list, has a cut-out).
_ROWS = {"made": True, "refused": False, "trim": False, "under": False, "left": False,
         "outside_bank": False}


def _view(root, cid, v, prefix):
    """The job as it leaves: paths cut, then the words, poll_s and the
    entries' routes (after the cut - a route is no path of this machine)."""
    out = dict(paths.clean(v, root),
               state_word=STATE_WORDS.get(v.get("state"), v.get("state")),
               kind_word=memes.JOB_KIND_WORDS.get(v.get("kind"), v.get("kind")),
               poll_s=None if v.get("done") else POLL_S)
    res = out.get("result")
    if isinstance(res, dict):
        res = dict(res)
        for key, cut in _ROWS.items():
            rows = res.get(key)
            if isinstance(rows, list):
                res[key] = [dict(r, urls=memes._urls(prefix, cid, {"id": r["id"],
                                                                   "cut_file": cut}))
                            if isinstance(r, dict) and isinstance(r.get("id"), str) else r
                            for r in rows]
        e = res.get("entry")
        if v.get("kind") in ("add_image", "add_gif") and isinstance(e, dict) \
                and isinstance(e.get("id"), str):
            res["entry"] = dict(e, urls=memes._urls(prefix, cid, {"id": e["id"],
                                                                  "cut_file": None}))
        if v.get("kind") == "sheet" and isinstance(res.get("sheet"), str):
            res["sheet_url"] = _sheet_url(prefix, cid, PurePath(res["sheet"]).name)
        out["result"] = res
    return out


def job(root, channel, job_id, prefix=""):
    """`job_status(job_id)` of the channel's bank + poll_s, the words, the routes."""
    cid = _channel(root, channel)
    d = _desk()
    v = memes._call(d.job_status, job_id, channel=cid, root=_lib(root), repo=Path(root))
    return _view(root, cid, v, prefix)


def jobs(root, channel, limit=LIST_LIMIT, prefix=""):
    """`list_jobs` of the channel's bank, newest first, + the running one."""
    cid = _channel(root, channel)
    d = _desk()
    bank, _folder = _bank_word(root, cid)
    got = memes._call(d.list_jobs, channel=cid, limit=limit, root=_lib(root), repo=Path(root))
    views = [_view(root, cid, v, prefix) for v in got]
    running = next((v for v in views if v.get("state") == "running"), None)
    return {"channel": cid, "bank": bank, "running": running, "jobs": views,
            "poll_s": POLL_S if running else None}
