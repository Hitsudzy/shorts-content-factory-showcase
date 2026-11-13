"""CC-0024: the meme desk of a channel - review its bank (Reel's default
`shared/inserts/memes/`, Tech's `memes-example-tech/`, whatever the channel's
`insert_layers.meme.bank` names): the entries and their review, the media,
the user's marks (keep / drop / cut / note), `apply`. Only through the
factory's own functions (`api/factory.py` `meme_desk`, CF-0693), nothing of
the API's own on top:

    scripts/meme_desk.py   desk_state, save_marks, plan_apply, apply_marks,
                           thumb, resolve_bank, MemeDeskError(code, text);
                           candidates_state, plan_accept, check_accept_answer,
                           accept_candidates (CF-0725 - the candidates' yes)

Every call names its bank by the channel (`channel=<id>`), the inserts
library `<factory root>/shared/inserts` and the checkout `<factory root>`
(its `channels/` and `inserts/meme.json`) - never the desk's module-global
`BANK`, so Reel and Tech in one process do not mix.

**The overview** (`overview`): every channel of the root with the bank its
config names and the counts of `desk_state` (one call per bank - channels on
the same bank share it); a bank that does not open is the channel's `error`,
not the whole answer's.

**The desk** (`state`): `desk_state` as the factory returns it, plus what the
screen needs to use it: `folder` under the root (not the absolute path),
`fingerprint` (sha256 of the bytes of `<bank>/_desk/decisions.json`, null
when there is no draft - the PUT of the marks carries it back) and
`index_fingerprint` (of `<bank>/index.json`), each entry's `urls` (media,
cut, thumb). Nothing written.

**The media** (`media_path`): the entry's `file` (`kind=file`; a GIF is its
file) or its cut-out `cut_file` (`kind=cut`), as `desk_state` names them -
through the one path guard (`factory.contained`: one name per part, no `..`,
no link out but the ones `scripts/agents sync` declared), served by
starlette's `FileResponse` with HTTP Range (as the videos' mp4).
`thumb_path`: `thumb()` - the factory makes the still's JPEG in
`<bank>/_desk/thumbs/` when it is missing or older than the source and
returns the cached one otherwise (a GIF is its own file): an idempotent cache,
which is why it is a GET. The path it returns goes through the same guard
(CC-0078): taken relative to the bank lexically, then walked by
`factory.contained` - in a worktree the bank's `_desk/` and media are links
to the working copy's same bank (`links.root` `shared/inserts/*/*`), served;
a link planted to anywhere else is still `outside_bank`.

**The marks** (`save`): the whole draft `{id: {v: keep|drop, cut: bool,
note: str}}` - `save_marks(by="user", via="center")` (the changed marks get
`marked_by`, `marked_at`, `via`). A light write, a draft as the factory's
desk treats it - but still a write: `require_writes`, one meme write at a time,
and `base` must be the `fingerprint` of the last GET (or of the last save):
a draft that changed meanwhile (another tab, the terminal's desk) is
`check_changed`, nothing written.

**Apply** (`apply_plan` / `apply`): two steps, as the publication writes
(CC-0065): the plan is `plan_apply(drop)` (nothing written) and, when the
index it would write is valid, a confirm token (`batches` store, action
`meme_apply`, 120 s, single use) bound to the channel and `drop`; the confirm
makes the plan again - its fingerprint covers the bytes of `index.json` and
`decisions.json` and the plan itself, a change is `check_changed` - then
`apply_marks(drop)`.

**The candidates** (`candidates`, CC-0103): the bank's `candidates.json`
(CF-0393, `meme_desk.py candidates --channel <id>`) - the templates waiting
on the user's yes. The bank by `resolve_bank` (the channel names it), the
file by the desk's `CANDIDATES`; checked by the desk's own
`candidate_problems` with the root's `fit_box` / `max_upscale` and the
root's `inserts/meme.json` intent vocabulary (the CLI's REPO is this
checkout, not the factory root); each row as written plus `stretch_now`
(`upscale_factor` of its size into the box), its `group` (pass / fail /
unknown by `passes_ceiling`, as the CLI groups them) and `copy_from` - when
`in_reel_bank` names an entry of the default bank, that entry's media routes
under the first channel on the default bank (`GET /api/memes/{c}/{id}/thumb`
already serves them); the download / copy totals as the CLI counts them.
The templates' own `url` is Imgflip's file - the API never fetches it.
A bank without the file is `missing`, not a refusal. Each row also carries
`status` / `bank_file` of the desk's `candidates_state` (CF-0725: `ready` -
its file lies in the bank, not in the index yet; `in_bank`, `not_downloaded`,
`outside_bank`) and `accept` says whether the yes is open: `available`, the
state's `fingerprint` ("sha256:<16 hex>" - of the list and the disk), its
`counts`, the `ready` ids and `other_bank` (the reel_tail ids).

**The yes** (`accept_plan` / `accept`, CC-0114 over CF-0725): two steps. The
plan is `plan_accept(channel, ids, details, by="user", via="center")` -
nothing written: `accept`, `refused [{id, reason, text}]` (in_bank,
not_downloaded, outside_bank, other_bank, no_source_url, over_ceiling,
media_failed), the list's `fingerprint` and `answer {must_contain: «да»,
must_not_contain, prompt}`; when something would be accepted, a confirm
token (`batches` store, action `meme_candidates_accept`, 120 s, single use)
bound to the plan's ids, `details` and the fingerprint. The confirm carries
the user's own typed `answer` - the API passes it through and never fills
it in; `check_accept_answer` runs before the token is spent (not a «да»:
422 `bad_answer`, the token kept). Then `accept_candidates(channel, ids,
answer, by="user", via="center", fingerprint=<the plan's>, details,
embed=True)`: a list or disk that moved since the plan is the desk's
`list_changed` (409, nothing written - the plan is asked again; after an
accept the statuses change, so every new accept needs a new plan). Nothing
is downloaded and nothing cut out here. `details` {id: {description, tags,
notes}} is the user's text for the entries; without it the factory writes
the candidate record's text and «rewrite on the desk» in the notes.

**A job on the bank** (CC-0075, CF-0755): while a background job of the desk
runs on the channel's bank (`job_on_bank` - `list_jobs`, alive while its
process holds its lock), the center refuses its own writes there - the
marks, apply, the candidates' yes (`refuse_while_job`, 409 `job_active` with
the job's id, before a token is spent) and a new start (`api/meme_jobs.py`);
the desk (`state`), the apply plan and the accept plan carry `job` and give
no token. The terminal's desk is not held by it.

**The commit** (CC-0156): apply and the candidates' yes end in one commit of
what they changed of the bank's tracked files - `<bank>/index.json` and
`<bank>/candidates.json` (`bank_scope`; the media, `_desk/` and the jobs'
records are gitignored), `Cc-Channel: <cid>` / `Cc-Action: meme_apply |
meme_candidates_accept` (`api/root_commit.py`: git's word on them before the
desk's write and after, only what moved). git's refusal is 409 `refused`
(`commit_refused`), the write stays in the tree, nothing staged; a root that
is not a git work tree commits nothing. The background jobs commit the same
scope when they end done (`api/meme_job_commit.py`). The marks' draft
(`_desk/decisions.json`) is gitignored - nothing to commit.

Every refusal is a `BatchFault` (`{message, code, details}`); a desk refusal
carries the factory's code and its Russian `text` as the message.
"""
import hashlib
import json
import os
import threading
from pathlib import Path
from urllib.parse import quote

from . import batches, factory, paths, root_commit
from .batches import BatchFault, _channel, _digest, _issue, _spend

INSERTS = ("shared", "inserts")
DESK = "_desk"
DECISIONS = "decisions.json"
INDEX = "index.json"
#: Who the center writes in the marks' stamp (`publish.WRITE_BY`) and from where.
WRITE_BY = "user"
VIA = "center"
#: One meme write at a time; how long a write waits for the one going.
WRITE_WAIT = 30.0
_WRITE = threading.Lock()
KINDS = ("file", "cut")
ACCEPT = "meme_candidates_accept"
ACTIONS = {"meme_apply": ("план применения отметок", "отметки не применены",
                          "применения отметок мемов канала"),
           ACCEPT: ("план приёма кандидатов", "кандидаты не приняты",
                    "приёма кандидатов в банк мемов канала")}
batches.register_actions(ACTIONS)

#: The HTTP status of a desk refusal by its code; every other code is 409 (the
#: state of the bank on disk, not the request). `outside_bank` is the factory's
#: own refusal too (CF-0697: the desk opens, thumbnails and deletes only media
#: inside the bank) - the same 404 as the API's guard says it.
_STATUS = {"unknown_id": 404, "no_file": 404, "no_channel": 404, "outside_bank": 404,
           "bad_decisions": 422, "thumb_failed": 500,
           # CC-0114: the candidates' yes (CF-0725)
           "bad_answer": 422, "bad_ids": 422, "bad_details": 422, "bad_entry": 422,
           "bad_who": 500,
           # CC-0075: the background jobs (CF-0755) - start_job, job_status, list_jobs
           "not_cutout": 422, "bad_kind": 422, "bad_params": 422, "bad_limit": 422,
           "unknown_job": 404, "spawn_failed": 500}


def _desk():
    return factory.meme_desk()


def _lib(root):
    return Path(root).joinpath(*INSERTS)


def _fault(e, status=None):
    """`MemeDeskError` -> `{message: the factory's Russian text, code: its code,
    details: its English line}`."""
    return BatchFault(status or _STATUS.get(e.code, 409), e.code, e.text,
                      [f"MemeDeskError({e.code}): {e.en}"])


def _call(fn, *a, statuses=None, **k):
    d = _desk()
    try:
        return fn(*a, **k)
    except d.MemeDeskError as e:
        raise _fault(e, (statuses or {}).get(e.code)) from e


def _fp(path):
    """sha256 of the file's bytes, None when there is none."""
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except FileNotFoundError:
        return None


def _rel(root, p):
    """CC-0097: relative to the root, `.../<its last part>` outside it - never
    the absolute path (`api/paths.py`)."""
    return paths.rel(root, p)


def _state(root, cid):
    return _call(_desk().desk_state, cid, root=_lib(root), repo=Path(root))


def _fingerprints(folder):
    folder = Path(folder)
    return _fp(folder / DESK / DECISIONS), _fp(folder / INDEX)


#: CC-0156: the bank's files git keeps (`.gitignore`: shared/inserts/*/* but these).
TRACKED = (INDEX, "candidates.json")


def bank_scope(root, folder):
    """The bank's tracked files, from the root - what a write of the desk may
    change in git's eyes (outside the root: nothing)."""
    return root_commit.rels(root, [Path(folder) / f for f in TRACKED])


def _layer_enabled(root, cid):
    """`insert_layers.meme.enabled` of the channel's config, None when it does
    not say (the factory switches it, not the center)."""
    try:
        cfg = json.loads((Path(root) / factory.CHANNELS_SUBDIR / f"{cid}.json").read_text())
        v = ((cfg.get("insert_layers") or {}).get("meme") or {}).get("enabled")
    except (OSError, ValueError, AttributeError):
        return None
    return v if isinstance(v, bool) else None


# ---------------------------------------------------------------- reading
def overview(root):
    """{channels: [{channel, bank, default_bank, layer_enabled, entries,
    pending, keep, drop, cut_diff, stale, error}]} - one desk_state per bank."""
    d = _desk()
    seen, out = {}, []
    for cid in factory.channel_list(root):
        row = {"channel": cid, "bank": None, "default_bank": None,
               "layer_enabled": _layer_enabled(root, cid), "entries": 0, "pending": 0,
               "keep": 0, "drop": 0, "cut_diff": 0, "stale": 0, "error": None}
        try:
            name, _folder = d.resolve_bank(cid, None, _lib(root), Path(root))
            key = name or ""
            if key not in seen:
                seen[key] = d.desk_state(cid, root=_lib(root), repo=Path(root))
            s = seen[key]
        except d.MemeDeskError as e:
            row["error"] = {"message": e.text, "code": e.code,
                            "details": [f"MemeDeskError({e.code}): {e.en}"]}
            out.append(row)
            continue
        st = s["status"]
        row.update(bank=s["bank"], default_bank=s["default_bank"], entries=len(s["entries"]),
                   pending=len(st["pending"]), keep=len(st["keep"]), drop=len(st["drop"]),
                   cut_diff=len(st["cut_diff"]), stale=len(st["stale"]))
        out.append(row)
    return {"channels": out}


def _urls(prefix, cid, e):
    base = f"{prefix}/memes/{quote(cid, safe='')}/{quote(e['id'], safe='')}"
    return {"file": f"{base}/media?kind=file",
            "cut": f"{base}/media?kind=cut" if e.get("cut_file") else None,
            "thumb": f"{base}/thumb"}


def state(root, channel, prefix=""):
    """desk_state + folder under the root, fingerprint (decisions.json),
    index_fingerprint, each entry's urls."""
    cid = _channel(root, channel)
    s = _state(root, cid)
    fp, ifp = _fingerprints(s["folder"])
    return dict(s, folder=_rel(root, s["folder"]), fingerprint=fp, index_fingerprint=ifp,
                entries=[dict(e, urls=_urls(prefix, cid, e)) for e in s["entries"]],
                job=paths.clean(job_ref(job_on_bank(root, cid)), root))


def _entry(s, meme_id):
    e = next((x for x in s["entries"] if x["id"] == meme_id), None)
    if e is None:
        raise BatchFault(404, "unknown_id", f"мема {meme_id!r} нет в банке",
                         [f"no entry {meme_id!r} in {s['bank']}/index.json"])
    return e


def _inside(root, bank, rel):
    """`<bank>/<rel>` through the path guard, or 404 `outside_bank`."""
    parts = Path(rel).parts if isinstance(rel, str) and rel else ()
    p = factory.contained(root, *INSERTS, bank, *parts) if parts else None
    if p is None:
        raise BatchFault(404, "outside_bank", f"Файл {rel!r} лежит не в банке {bank} - не "
                                              f"отдаётся.",
                         [f"{rel!r} is not a path inside {'/'.join(INSERTS)}/{bank} "
                          f"(factory.contained)"])
    return p


def media_path(root, channel, meme_id, kind="file"):
    """The entry's file (`file`) or its cut-out (`cut`), inside its bank."""
    cid = _channel(root, channel)
    s = _state(root, cid)
    e = _entry(s, meme_id)
    if kind == "cut":
        if not e.get("cut_file"):
            why = e.get("cut_refused") or "у мема нет вырезки"
            raise BatchFault(404, "no_cut", f"Вырезки {meme_id} нет: {why}",
                             [f"{meme_id}: cutout={e.get('cutout')}, cut_file is null"])
        rel = e["cut_file"]
    else:
        rel = e["file"]
    p = _inside(root, s["bank"], rel)
    if not p.is_file():
        raise BatchFault(404, "no_file", f"файла {rel} нет в банке {s['bank']}",
                         [f"no {'/'.join(INSERTS)}/{s['bank']}/{rel}"])
    return p


def _bank_rel(root, bank, p):
    """`p` - a path the factory returned - relative to `<root>/shared/inserts/
    <bank>`, lexically (normalized, symlinks not followed), or None when it is
    not under it. The bank folder is taken both as written and with the root
    resolved (as `factory.contained` takes it)."""
    target = Path(os.path.normpath(os.path.abspath(p)))
    for base in (Path(root).joinpath(*INSERTS, bank),
                 Path(root).resolve().joinpath(*INSERTS, bank)):
        try:
            return target.relative_to(Path(os.path.normpath(os.path.abspath(base)))).as_posix()
        except ValueError:
            continue
    return None


def thumb_path(root, channel, meme_id):
    """`thumb()` - the cached JPEG of a still (made when missing or stale), a
    GIF's own file - through the same guard as the media (CC-0078): the path
    the factory returned is taken relative to the bank lexically, then
    `factory.contained` walks it (a link `scripts/agents sync` declared is in,
    any other link out is not)."""
    cid = _channel(root, channel)
    d = _desk()
    name, _folder = _call(d.resolve_bank, cid, None, _lib(root), Path(root))
    bank = name or d.lib.KIND_FOLDERS[d.KIND]
    p = _call(d.thumb, cid, meme_id, root=_lib(root), repo=Path(root))
    rel = _bank_rel(root, bank, p)
    parts = Path(rel).parts if rel else ()
    got = factory.contained(root, *INSERTS, bank, *parts) if parts else None
    if got is None:
        raise BatchFault(404, "outside_bank", f"Миниатюра {meme_id} лежит не в банке {bank} - "
                                              f"не отдаётся.",
                         [f"thumb() returned {p}, not a path inside {'/'.join(INSERTS)}/{bank} "
                          f"(factory.contained)"])
    return got


# ---------------------------------------------------------------- the candidates (CC-0103)
def _vocabulary(root):
    """`selection.intent_vocabulary` of the root's `inserts/meme.json` - what
    `candidate_problems` reads from the desk's own checkout by default."""
    spec = json.loads((Path(root) / "inserts" / "meme.json").read_text(encoding="utf-8"))
    return set(spec["selection"]["intent_vocabulary"])


def _default_bank_media(root):
    """(channel on the default bank or None, {id: entry} of that bank, error):
    the first channel whose config names no bank - the routes `copy_from`
    points at."""
    d = _desk()
    for cid in factory.channel_list(root):
        try:
            name, _folder = d.resolve_bank(cid, None, _lib(root), Path(root))
        except d.MemeDeskError:
            continue
        if name is None:
            try:
                s = d.desk_state(cid, root=_lib(root), repo=Path(root))
            except d.MemeDeskError as e:
                return cid, {}, f"MemeDeskError({e.code}): {e.en}"
            return cid, {e["id"]: e for e in s["entries"]}, None
    return None, {}, None


def candidates(root, channel, prefix=""):
    """The bank's candidates.json, checked by the desk's `candidate_problems`,
    each row with `stretch_now`, `group` and `copy_from`; nothing written."""
    cid = _channel(root, channel)
    d = _desk()
    name, folder = _call(d.resolve_bank, cid, None, _lib(root), Path(root))
    bank = name or d.lib.KIND_FOLDERS[d.KIND]
    path = Path(folder) / d.CANDIDATES
    out = {"channel": cid, "bank": bank, "default_bank": name is None,
           "path": _rel(root, path), "fingerprint": _fp(path), "missing": None,
           "listed": None, "source": None, "summary": None, "schema_note": None,
           "fit_box": None, "ceiling": None, "candidates": [], "tail": [], "problems": [],
           "counts": {"pass": 0, "fail": 0, "unknown": 0},
           "download": {"files": 0, "bytes": 0}, "copy": {"files": 0, "bytes": 0},
           "copy_channel": None, "copy_error": None,
           "accept": {"available": False, "reason": None, "fingerprint": None, "counts": None,
                      "ready": [], "other_bank": []}}
    if not path.is_file():
        out["missing"] = (f"У банка {bank} нет списка кандидатов ({_rel(root, path)}) - "
                          f"ждать «да» нечему.")
        out["accept"]["reason"] = out["missing"]
        return paths.clean(out, root)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise BatchFault(409, "bad_candidates", f"Список кандидатов банка {bank} не читается "
                                                f"как JSON - кандидатов не показать.",
                         [f"{_rel(root, path)}: {type(e).__name__}: {e}"]) from e
    try:
        box, ceiling = d.fit_box(Path(root)), d.max_upscale(Path(root))
        vocab = _vocabulary(root)
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise BatchFault(409, "bad_spec", "inserts/meme.json фабрики не читается (рамка, "
                                          "потолок растяжения или словарь намерений) - "
                                          "кандидатов не проверить.",
                         [f"inserts/meme.json: {type(e).__name__}: {e}"]) from e
    problems = d.candidate_problems(data, box=box, ceiling=ceiling, vocabulary=vocab)
    rows = data.get("candidates") if isinstance(data, dict) else None
    rows = [c for c in rows if isinstance(c, dict)] if isinstance(rows, list) else []
    copy_cid, default_entries, copy_error = (_default_bank_media(root)
                                             if any(c.get("in_reel_bank") for c in rows)
                                             else (None, {}, None))
    try:
        st = d.candidates_state(cid, root=_lib(root), repo=Path(root))
    except d.MemeDeskError as e:
        st = None
        out["accept"]["reason"] = (f"Принять кандидатов сейчас нельзя: {e.text}")
    by_state = {r["id"]: r for r in (st or {}).get("candidates", [])}
    if st is not None:
        out["accept"].update(available=True, fingerprint=st["fingerprint"],
                             counts=st["counts"],
                             ready=[r["id"] for r in st["candidates"] if r["status"] == "ready"],
                             other_bank=list(st["other_bank"]))
    groups = {True: "pass", False: "fail"}
    listed = []
    for c in rows:
        w, h = c.get("width"), c.get("height")
        sized = all(isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0
                    for v in (w, h))
        group = groups.get(c.get("passes_ceiling"), "unknown")
        src = c.get("in_reel_bank")
        hit = default_entries.get(src) if isinstance(src, str) else None
        copy_from = {"channel": copy_cid, "id": src} if hit is not None else None
        sr = by_state.get(c.get("id")) if isinstance(c.get("id"), str) else None
        listed.append(dict(c, stretch_now=(round(d.upscale_factor((w, h), box), 4)
                                           if sized else None),
                           group=group, copy_from=copy_from,
                           status=sr["status"] if sr else None,
                           bank_file=sr["file"] if sr and sr["downloaded"] else None))
        out["counts"][group] += 1
        if group == "pass":
            side = out["copy"] if src else out["download"]
            side["files"] += 1
            n = c.get("bytes")
            side["bytes"] += n if isinstance(n, int) and not isinstance(n, bool) else 0
    tail = ((data.get("reel_tail") or {}).get("candidates") or []) if isinstance(data, dict) \
        else []
    out.update(listed=data.get("listed") if isinstance(data, dict) else None,
               source=data.get("source") if isinstance(data, dict) else None,
               summary=data.get("summary") if isinstance(data, dict) else None,
               schema_note=data.get("schema_note") if isinstance(data, dict) else None,
               fit_box=list(box), ceiling=ceiling, candidates=listed,
               tail=[t for t in tail if isinstance(t, dict)], problems=problems,
               copy_channel=copy_cid, copy_error=copy_error)
    out = paths.clean(out, root)
    # the routes after the cut - `/api/memes/...` is no path of this machine
    for c in out["candidates"]:
        if c["copy_from"] is not None:
            c["copy_from"]["urls"] = _urls(prefix, copy_cid, default_entries[c["in_reel_bank"]])
    return out


# ---------------------------------------------------------------- a job on the bank (CC-0075)
#: A job's kind in Russian (`meme_desk.JOB_KINDS`, CF-0755).
JOB_KIND_WORDS = {"cutout": "вырезка", "trim_blank": "срез пустых полей",
                  "add_image": "добавление картинки", "add_gif": "нарезка GIF",
                  "sheet": "контактный лист",
                  "embed": "пересчёт признаков для поиска похожих мемов"}


def job_on_bank(root, cid):
    """The bank's running job as `job_status` says it, or None: the newest
    records of `list_jobs` (a job is running while its process holds its
    lock, CF-0755). Reads only."""
    d = _desk()
    jobs = _call(d.list_jobs, channel=cid, limit=d.JOBS_KEEP, root=_lib(root), repo=Path(root))
    return next((j for j in jobs if j.get("state") == "running"), None)


def job_ref(job):
    """The short form of a running job a refusal or a plan names."""
    if job is None:
        return None
    return {"job_id": job["job_id"], "kind": job.get("kind"),
            "kind_word": JOB_KIND_WORDS.get(job.get("kind"), job.get("kind")),
            "bank": job.get("bank"), "started_at": job.get("started_at"),
            "progress": job.get("progress")}


def channel_title(root, cid):
    """The channel's `display_name` from its config (channels/<cid>.json) for
    the center's words (CC-0136: «ExampleTech», not «example-tech»); the slug
    when the config has none or does not read."""
    if not isinstance(cid, str) or not cid or any(c in cid for c in "/\\\0") or \
            cid.startswith("."):
        return cid
    try:
        cfg = json.loads((Path(root) / factory.CHANNELS_SUBDIR / f"{cid}.json")
                         .read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return cid
    name = cfg.get("display_name") if isinstance(cfg, dict) else None
    return name.strip() if isinstance(name, str) and name.strip() else cid


def job_busy_text(job, what, cid, root):
    kind = JOB_KIND_WORDS.get(job.get("kind"), job.get("kind"))
    return (f"Над банком мемов канала {channel_title(root, cid)} идёт задача {job['job_id']} ({kind})\u00a0— {what}; "
            f"дождитесь её конца (отмены нет).")


#: The factory's environment on top of the API's for the machine's slot
#: (`MEME_DESK_JOBS_DIR` in the tests) - `meme_jobs.FACTORY_KW` is this dict.
JOBS_KW = {}


def _jobs_environ():
    env = JOBS_KW.get("environ")
    return None if env is None else {**os.environ, **env}


def machine_job(root, cid):
    """CF-0761 `active_job()`: the machine's one job when it is alive and
    runs on ANOTHER bank than the channel's, as a ref (+ its channel), else
    None - a dead slot is not busy, the same bank is `job_on_bank`'s. Reads
    only the slot's active.json, takes no lock."""
    d = _desk()
    a = _call(d.active_job, root=_lib(root), repo=Path(root), environ=_jobs_environ())
    if not a or not a.get("alive"):
        return None
    name, _folder = _call(d.resolve_bank, cid, None, _lib(root), Path(root))
    if a.get("bank") == (name or d.lib.KIND_FOLDERS[d.KIND]):
        return None
    return dict(job_ref(a), channel=a.get("channel"))


def machine_busy_text(job, root):
    bank = (f"банк мемов канала {channel_title(root, job['channel'])}" if job.get("channel")
            else f"банк {job.get('bank')}")
    return (f"На машине идёт задача {job['job_id']} ({job.get('kind_word')}, {bank})\u00a0— одна "
            f"задача на машину, дождитесь её конца.")


def hold_plan(out, root, cid, what):
    """A plan's answer with `job` (a job on the bank: ok false, its words) and
    `machine_job` (CF-0761: an alive job on another bank of the machine: ok
    false, «одна задача на машину»). The confirms keep the bank's
    `job_active` and the factory's own `job_running` for another bank."""
    job = job_on_bank(root, cid)
    other = None if job is not None else machine_job(root, cid)
    out = dict(out, job=job_ref(job), machine_job=other)
    if job is not None:
        out.update(ok=False, why=job_busy_text(job, what, cid, root))
    elif other is not None:
        out.update(ok=False, why=machine_busy_text(other, root))
    return out


def refuse_while_job(root, cid, what):
    """409 `job_active` while a job runs on the channel's bank - the center's
    own refusal of its writes on that bank (the terminal's desk is not held
    by it). Before any token is spent."""
    job = job_on_bank(root, cid)
    if job is not None:
        raise BatchFault(409, "job_active", job_busy_text(job, what, cid, root),
                         [f"job {job['job_id']} ({job.get('kind')}) is running on "
                          f"{job.get('bank')} (list_jobs: its lock is held); a token, if any, "
                          f"is not spent"])


# ---------------------------------------------------------------- the writes
def _locked():
    if not _WRITE.acquire(timeout=WRITE_WAIT):
        raise BatchFault(409, "busy", "Идёт другая запись мемов - подождите и повторите.",
                         [f"the meme write lock was not free in {WRITE_WAIT} s; the token, if "
                          f"any, is not spent"])


def save(root, channel, decisions, base):
    """The whole draft, saved when `base` is the draft's fingerprint now (None:
    there was no draft) - else `check_changed`, nothing written."""
    cid = _channel(root, channel)
    d = _desk()
    _locked()
    try:
        refuse_while_job(root, cid, "отметки не сохранены")
        _name, folder = _call(d.resolve_bank, cid, None, _lib(root), Path(root))
        now = _fp(Path(folder) / DESK / DECISIONS)
        if now != base:
            raise BatchFault(409, "check_changed", "Отметки изменились с тех пор, как вы открыли "
                                                   "стол (другая вкладка или стол в терминале) - "
                                                   "отметки не сохранены; откройте стол заново.",
                             [f"decisions.json is {now}, the request's base is {base}"])
        got = _call(d.save_marks, decisions, cid, by=WRITE_BY, via=VIA, root=_lib(root),
                    repo=Path(root), statuses={"unknown_id": 422})
        return {"channel": cid, "saved": got["saved"], "bank": got["bank"],
                "fingerprint": _fp(Path(folder) / DESK / DECISIONS)}
    finally:
        _WRITE.release()


def _apply_check(root, cid, bound):
    """(plan, facts): plan_apply(drop) and the bytes it was made of."""
    d = _desk()
    drop = bool(bound.get("drop"))
    _name, folder = _call(d.resolve_bank, cid, None, _lib(root), Path(root))
    fp, ifp = _fingerprints(folder)
    plan = _call(d.plan_apply, cid, drop, root=_lib(root), repo=Path(root))
    ok = not plan["errors"]
    why = None if ok else ("Применить нельзя\u00a0— список мемов банка вышел бы неверным: "
                           + "; ".join(plan["errors"]))
    out = dict(plan, ok=ok, why=why, decisions_fingerprint=fp, index_fingerprint=ifp)
    return out, {"action": "meme_apply", "channel": cid, "drop": drop, "decisions": fp,
                 "index": ifp, "plan": plan}


def apply_plan(root, channel, drop=False):
    """What «применить» would do (plan_apply), a confirm token when ok -
    nothing written."""
    cid = _channel(root, channel)
    bound = {"drop": bool(drop)}
    out, facts = _apply_check(root, cid, bound)
    fp = _digest(facts)
    out = hold_plan(dict(out, action="meme_apply", channel=cid, fingerprint=fp, confirm=None,
                         expires_in_s=None), root, cid, "применить отметки сейчас нельзя")
    if out["ok"]:
        out.update(confirm=_issue(root, "meme_apply", cid, fp, bound),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return out


def apply(root, channel, token):
    """The confirmed apply: the token spent, the plan made again from its
    `drop` (the same fingerprint, else `check_changed`), then apply_marks."""
    cid = _channel(root, channel)
    d = _desk()
    _locked()
    try:
        refuse_while_job(root, cid, "отметки не применены")
        got = _spend(root, "meme_apply", cid, token)
        out, facts = _apply_check(root, cid, got["bound"])
        if _digest(facts) != got["fingerprint"]:
            raise BatchFault(409, "check_changed", "Банк или отметки изменились с момента плана "
                                                   "- отметки не применены; посмотрите план "
                                                   "заново.",
                             ["the fingerprint of index.json + decisions.json + the plan "
                              "differs from the plan's"])
        drop = bool(got["bound"].get("drop"))
        _name, folder = _call(d.resolve_bank, cid, None, _lib(root), Path(root))
        scope = bank_scope(root, folder)
        before = root_commit.snap(root, scope)
        try:
            res = d.apply_marks(cid, drop, root=_lib(root), repo=Path(root))
        except d.MemeDeskError as e:
            raise _fault(e) from e
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Стол мемов ответил ошибкой посреди записи "
                                                    "- посмотрите банк, прежде чем повторять.",
                             [f"{type(e).__name__}: {e}"]) from e
        sha, committed = root_commit.commit_changed(
            root, cid, "meme_apply", scope, before,
            lambda: (f"Мемы {cid}: отметки применены ({WRITE_BY}, {VIA})",
                     f"CC-0156: применение отметок из центра (memes.apply, "
                     f"meme_desk.apply_marks).\nПриняты: {_ids(res.get('accept'))}\n"
                     f"Удалены: {_ids(res.get('remove'))}"
                     + ("\nС удалением непринятых." if drop else "")),
            "Отметки применены")
        _name, folder = d.resolve_bank(cid, None, _lib(root), Path(root))
        fp, ifp = _fingerprints(folder)
        return dict(res, action="meme_apply", channel=cid, decisions_fingerprint=fp,
                    index_fingerprint=ifp, commit=sha, committed=committed)
    finally:
        _WRITE.release()


def _ids(ids):
    return ", ".join(str(i) for i in ids or []) or "нет"


# ---------------------------------------------------------------- the candidates' yes (CC-0114)
def _accept_args(ids, details):
    if ids is not None and (not isinstance(ids, list) or not ids):
        raise BatchFault(422, "bad_ids", "Выберите хотя бы одного кандидата (или не "
                                         "указывайте ids - тогда все готовые).",
                         ["ids: an empty list; omit it for every ready candidate"])
    if details is not None:
        details = {k: {f: v for f, v in (d or {}).items() if v is not None}
                   for k, d in details.items()}
    return ids, details or None


def _accept_plan(root, cid, ids, details):
    d = _desk()
    plan = _call(d.plan_accept, cid, ids, details=details, by=WRITE_BY, via=VIA,
                 root=_lib(root), repo=Path(root))
    ok = bool(plan["accept"])
    why = None if ok else ("Принять некого: " + ("; ".join(f"{r['id']}\u00a0— {r['text']}"
                                                           for r in plan["refused"])
                                                 or "готовых кандидатов нет"))
    facts = {"action": ACCEPT, "channel": cid, "ids": plan["ids"], "details": details,
             "fingerprint": plan["fingerprint"], "accept": plan["accept"],
             "refused": plan["refused"]}
    return dict(plan, ok=ok, why=why, details=details), facts


def accept_plan(root, channel, ids=None, details=None):
    """What «да» would take in (plan_accept, by user via center) and a confirm
    token when some candidate would be accepted - nothing written."""
    cid = _channel(root, channel)
    ids, details = _accept_args(ids, details)
    out, facts = _accept_plan(root, cid, ids, details)
    out = hold_plan(dict(out, action=ACCEPT, channel=cid, plan_fingerprint=_digest(facts),
                         confirm=None, expires_in_s=None), root, cid,
                    "принять кандидатов сейчас нельзя")
    if out["ok"]:
        out.update(confirm=_issue(root, ACCEPT, cid, out["plan_fingerprint"],
                                  {"ids": out["ids"], "details": details,
                                   "fingerprint": out["fingerprint"]}),
                   expires_in_s=int(batches.CONFIRM_TTL))
    return paths.clean(out, root)


def accept(root, channel, token, answer):
    """The confirmed yes: the user's typed answer checked by the factory's own
    rule before the token is spent, the token spent, then accept_candidates
    with the plan's ids, details and fingerprint (by user via center) - the
    desk refuses a list that moved (`list_changed`)."""
    cid = _channel(root, channel)
    d = _desk()
    got = d.check_accept_answer(answer)
    if not got["ok"]:
        raise BatchFault(422, "bad_answer", f"Кандидаты не приняты: {got['why']}.",
                         [f"check_accept_answer: {got['why']}", "the token is not spent"])
    _locked()
    try:
        refuse_while_job(root, cid, "кандидаты не приняты")
        tok = _spend(root, ACCEPT, cid, token)
        b = tok["bound"]
        _name, folder = _call(d.resolve_bank, cid, None, _lib(root), Path(root))
        scope = bank_scope(root, folder)
        before = root_commit.snap(root, scope)
        try:
            res = d.accept_candidates(cid, b["ids"], answer, WRITE_BY, VIA,
                                      fingerprint=b["fingerprint"], details=b["details"],
                                      embed=True, root=_lib(root), repo=Path(root))
        except d.MemeDeskError as e:
            raise _fault(e) from e
        except Exception as e:                                  # noqa: BLE001
            raise BatchFault(500, "factory_broken", "Стол мемов ответил ошибкой посреди приёма "
                                                    "кандидатов - посмотрите банк, прежде чем "
                                                    "повторять.",
                             [f"{type(e).__name__}: {e}"]) from e
        sha, committed = root_commit.commit_changed(
            root, cid, ACCEPT, scope, before,
            lambda: (f"Мемы {cid}: кандидаты приняты в банк ({WRITE_BY}, {VIA})",
                     f"CC-0156: приём кандидатов из центра (memes.accept, "
                     f"meme_desk.accept_candidates).\nПриняты: {_ids(res.get('accepted'))}\n"
                     f"Ответ: «{answer}»"),
            "Кандидаты приняты")
        return paths.clean(dict(res, action=ACCEPT, channel=cid, answer=answer, commit=sha,
                                committed=committed), root)
    finally:
        _WRITE.release()
