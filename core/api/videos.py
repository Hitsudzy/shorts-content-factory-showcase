"""CC-0012: a batch's finished videos for the user's acceptance - the list
(with the rebuilds beside it), the mp4 to watch, its preview frame, the
verdict, the publication card. Only through the factory's own functions
(`api/factory.py`), nothing of the API's own on top:

    shared/runlog/runlog.py       editor_videos - the videos the run built, from
                                  `<batch>/05-video-editor.json` (CF-0176)
    shared/runlog/acceptance.py   read_log / entries / find / state / reasons -
                                  the record `publish/acceptance-log.json`
                                  (CF-0328); record_and_commit - the verdict
                                  and its commit, or the queue under a batch
                                  (CF-0675), AcceptanceError code / text_ru
                                  (CF-0676);
                                  score_lines - the score line beside the name
                                  (CF-0434)
    agents/publisher/publish_card.py  placeable / card_status (CF-0747) / mark_of (CF-0017)
    agents/publisher/publish_note.py  sections / title_and_description / parse

(the modules as `shared/factory_state.py` loads them - one copy each).

**The list** (`videos`): the batch's 05 as `editor_videos` reads it - slug
(the stem of `output_path`), script id, QC - each with its score line, its
mp4 (inside `<batch>/videos/` only), its preview, a short card (ready, why,
title) and what the record says about it (`acceptance.state` plus the row's
reason code, the user's words, the times, the history). A source batch lists
its **rebuilds** beside it: every `pipeline/rebuilds/<ts>` whose
`run-state.json` `rebuild.of` (CF-0668), else whose 05 `rebuild_of`
(CF-0416), names this batch - each with its own videos in the same shape; a
source video names the rebuilds that made it again (`rebuilt_in`). A rebuild
names its source (`rebuild_of`, the route's path form). The reason codes the
record has counted (`acceptance.reasons`) come with it, for the screen's
«отклонить» to offer.
**A video refused after the render** (CC-0116, CF-0727): the Editor writes it
into 05 `refusals[]`, not `videos[]` (a QC score under the threshold - the
mp4 is often there). It is listed too, with `refused: {reason_code, reason,
gate, score_line, score, at}` - the 05's last refusal of its script, as the
editor merges them - and the slug the factory's rebuild finds for it
(`shared/batch_control.py` `_source_videos`: `output_path`, else the
`work/<slug>/` whose files name the script); its mp4, preview and card go by
the same routes when the file is there. It takes no verdict - `accept`
answers 409 `video_refused` (rebuild it; the rebuild's video is the one
accepted); `refused` is null for every video of `videos[]`. CC-0119: the
refusal goes out through `paths.clean` (every string of it, recursively) - the
Editor's `score.log[].where.shot` and `note` name clips by absolute path; a
path inside the root leaves relative, any other `.../<its last part>`.
**The score** (CC-0125, «оценка ролика»): each video carries a badge
`score` {tier, score, threshold, passed, stopped_at, source, url} - its log
`work/<slug>/plan.score.json` (CF-0434), else the 05's score block, else
null - and the list the model's tiers once (`score_model`, `score.load_model`
over the root's price table); `score()` is the reasoning: stages, findings
paired with the log rows that priced them, the rule's Russian name from the
factory's `score.LABELS` / `HARD_LABELS` (its short name when there is none).
**The upload** (CC-0096): each video names its upload to YouTube - the live
row of `publish/uploads.json` (CF-0586), read through the journal's one
reader `agents/publisher/upload_records.py` `uploads`, by the acceptance key
`<channel>/<batch_id>/<slug>` (every name the key goes by: the acceptance's,
the one frozen into its row, the route's - `rebuilds/<ts>/<slug>` for a
rebuild - and a former channel id resolved), never by slug: one slug goes up
from several batches. A row replaced or removed is no upload; none -> null. A
journal that does not read is said (`uploads_error`), every `upload` null -
the acceptance list must not go with it.

**The mp4** (`mp4`): `<batch>/videos/<slug>.mp4` through the one path guard
(`factory.contained`), never the 05's absolute `output_path` (it may name any
file). Served as `video/mp4` by starlette's `FileResponse`, which streams in
chunks (never read whole) and answers HTTP Range itself in the pinned
starlette (0.49): `Accept-Ranges: bytes`, a single range `206` with
`Content-Range`, open-ended and suffix ranges, a start past the end `416`
with `Content-Range: */<size>` - the tests pin each of them, so a starlette
that stopped doing it fails there and not in the user's player.

**The preview** (CF-0674): the Editor writes one frame of the hook beside the
mp4 - `<batch>/videos/<slug>.jpg`, 720 x 1280, <= 200 KB, for batches and
rebuilds alike; no frame could be taken, no jpg (an old one is removed). The
05 does not name it: it is read from disk, through the one path guard
(`factory.contained`). `preview` serves it as is (`kind: "frame"`,
`image/jpeg`). A video without it (built before CF-0674) falls back to what
the factory made of it before: the frame judge's contact sheets
(`work/<slug>/frame-judge/sheet-N.png`, `frame_judge_pack.py`, CF-0298),
frames of the FINISHED video, 3 x 2 tiles of 360 x 640 - the first tile is the
first block; the first sheet the pack's `manifest.json` lists is served
(`kind: "sheet"`, `image/png`) with its grid and tile, so the screen can show
the first tile. Neither: `available: false` and why. The API runs no ffmpeg.

**The verdict** (`accept`): the user's press - never anything else. `yes` is
`accepted`, `no` and `redo` are `rejected` (the record knows two verdicts):
`acceptance.record_and_commit(channel, batch, slug, verdict, answer=<the
user's exact words>, by="user (центр)", root, log, reason, reason_code, amend,
shown=<the batch's videos>, batch_dir=<the batch>, strict_topic=True)`
(CF-0675) - `record` and the commit in one call, what `runlog acceptance
--record --write --commit` does. The words go in as typed and must name the
video (the factory's rule, CF-0328: a verdict is tied to a name, never a
position) - the screen puts the video's name into the box first. A rejection
needs a reason and its `reason_code` (the dictionary key CF-0319 counts); a
second verdict needs `amend` (why the user changed it). Each refusal is the
factory's (CF-0676): the problem's `code` is `AcceptanceError.code` (stable,
`answer_without_name`, `rejection_without_reason`, `verdict_already_given`...),
its `message` the factory's `text_ru`, its English words in `details` - the
API keeps no table of its own. 422 for a refused verdict, 409 when the record
or its queue does not read, 500 when git did not make the commit (the record
is then put back as it was). The day and the time are the factory's
(`answered_at`, `recorded_at`).

**Does it move the root's HEAD?** With no batch or rebuild going
(`runlog.open_batches`, the fresh rows): yes, by exactly one commit
«Приёмка: <slug> принят|отклонён (user (центр))» of `publish/acceptance-log.json`
and nothing else - after the queue, if there was one, got its own commit first
(`flushed`, `commit_pending`'s answer). Under an open batch: no - `record`
checks the verdict at once (a refusal is said now, nothing written), the row
goes to `publish/acceptance-pending.jsonl` (gitignored), HEAD and the tree stay
as `batch-start` left them, and the answer says `pending: true` and why
(`batches` [{dir, why}]). The schedule's tick (`batch_schedule`) commits the
queue once the batch is done, or the next verdict with no batch going does.
The list shows a queued verdict at once (`acceptance.entries` mixes the queue
in: `pending`, `queued_at`, `queued_by`).

**Locks.** `_WRITE` is one verdict at a time in this process. Across
processes (the center, the schedule's tick, a verdict typed in the terminal)
the factory locks itself: `record_and_commit` and `commit_pending` hold an
exclusive `fcntl.flock` on `publish/acceptance-pending.lock` around reading the
record, the queue and the commit. The commit helper
(`shared/runlog/git_commit.write_and_commit`) takes no lock of its own - git's
`index.lock` refuses a second commit at the same moment, and the helper puts
the file back. (`fcntl.flock` is POSIX - macOS and Linux alike, the
Docker target too.)

**«Переделать, потому что…»** (`redo`): recorded now as a rejection with the
user's words and reason, the row's `note` saying it was «переделать». The
operator's queue of requests (CC-0018) does not exist yet: `REDO_QUEUE` is
the seam - None today, and the answer says `redo.queued: false` and why;
CC-0018 sets it to its enqueue function (`REDO_QUEUE(root, row, words,
reason) -> dict`) and the request goes there with the same press.

**The card** (`card`): `<batch>/work/publish-card/<slug>.md`
(`publish_card.CARD_DIR`) parsed by the factory's readers - ready and why
(`placeable`: ready or ruled, CF-0747), title and description (`title_and_description`), the
description's blocks, the tags, the slot and the synthetic flag
(`publish_note.parse`; its refusal as `note_error`, the tags then off the
section as written), every section in order, the machine marker
(`mark_of`) - and the raw text for «подробнее». The card placed in
`publish/<channel>/<day>/` after the acceptance is not read here.

**The repair** (CC-0171, CF-0881): each video carries `repair` - the one
repair pass after the frame judge, as `funnel.judge_repairs` gives it
(`api/repair_refill.py`; CC-0173: the blocks' defect from the funnel too):
`repaired` (its 06 row is the ready one now) or `repair_failed` (the refusal
stands), why, the blocks and their defect, the codes before and after; null
when the video had none (a batch before 2.37 too). Its strings go out through
`paths.clean`.

Every refusal is a `BatchFault` (`{message, code, details}`).
"""
import json
import re
import threading
from pathlib import Path

from . import factory, paths, repair_refill
from .batches import PIPELINE_DIR, SAFE_NAME, BatchFault, batch_dir

VIDEOS_DIR = "videos"           # <batch>/videos/<slug>.mp4 (collect.waiting_acceptance)
PACK_DIRNAME = "frame-judge"    # = scripts/frame_judge_gate.py PACK_DIRNAME
MANIFEST = "manifest.json"      # = scripts/frame_judge_gate.py MANIFEST
WORK_DIR = "work"
MP4_TYPE = "video/mp4"
PNG_TYPE = "image/png"
JPG_TYPE = "image/jpeg"
FRAME_SUFFIX = ".jpg"           # <batch>/videos/<slug>.jpg - the Editor's preview frame (CF-0674)
UPLOADS_REL = "publish/uploads.json"    # = upload_records.JOURNAL (CF-0586)
#: CC-0096: what a video's `upload` carries of its journal row.
UPLOAD_FIELDS = ("video_id", "url", "publish_day", "publish_at", "uploaded_at", "recorded_at",
                 "source", "withdrawn")

#: The screen's three buttons -> the record's two verdicts.
VERDICTS = {"yes": "accepted", "no": "rejected", "redo": "rejected"}
REDO_NOTE = ("из центра (CC-0012): «переделать» - просьба переделать ждёт очереди просьб "
             "оператору (CC-0018)")
YES_NO_NOTE = "из центра (CC-0012)"

#: The seam of CC-0018: the operator's queue of requests. None until it lands;
#: then `REDO_QUEUE(root, row, words, reason) -> dict` enqueues a «переделать».
REDO_QUEUE = None
REDO_NOT_YET = ("очереди просьб оператору ещё нет (CC-0018) - просьба переделать записана "
                "только в журнал приёмки")

_WRITE = threading.Lock()        # one verdict at a time in this process


# ---------------------------------------------------------------- the factory's modules
def _col():
    return factory.collect()


def _acc():
    return _col().acceptance()


def _card_mod():
    return _col().card()


def _note_mod():
    return _col().note()


def _log_path(root):
    return Path(root) / _acc().ACCEPTANCE_LOG_REL


def _holds_path(root):
    return Path(root) / "publish" / "publication-holds.json"


def _journal_path(root):
    return Path(root) / UPLOADS_REL


def _rel(root, p):
    """CC-0097: relative to the root, `.../<its last part>` outside it - never
    the absolute path (`api/paths.py`)."""
    return paths.rel(root, p)


# ---------------------------------------------------------------- the videos of a batch
#: CC-0116: what a video refused after the render says of it (a 05 `refusals[]` row)
REFUSAL_FIELDS = ("reason_code", "reason", "gate", "score_line", "score", "at")


def _refused(d, have):
    """CC-0116 (CF-0727): the videos refused after the render - the 05's
    `refusals[]` rows the factory's rebuild counts as source videos
    (`batch_control._source_videos`: its script in 03, not in `videos[]`, the
    slug off `output_path` or `work/<slug>/`), each as an `editor_videos` row
    with `refused` - the script's last refusal (REFUSAL_FIELDS). A slug that
    is no file name, one already in `have`, or a factory that does not answer:
    left out (the list of the accepted ones still answers)."""
    rows = (_read(Path(d) / factory.runlog().VIDEO_EDITOR_FILE).get("refusals") or [])
    last = {r["script_id"]: r for r in rows if isinstance(r, dict) and r.get("script_id")}
    if not last:
        return []
    try:
        src = factory.batch_control()._source_videos(d)
    except Exception:                                       # noqa: BLE001
        return []
    out = []
    for v in src:
        slug, sid = v.get("slug"), v.get("script_id")
        if not v.get("refused") or sid not in last or slug in have or \
                not SAFE_NAME.match(str(slug or "")):
            continue
        r = last[sid]
        out.append({"slug": slug, "script_id": sid, "qc_passed": None, "entry": {},
                    "refused": dict({k: r.get(k) for k in REFUSAL_FIELDS},
                                    score=r.get("score") if isinstance(r.get("score"), dict)
                                    else None,
                                    reason_ru=factory.reason_ru(r.get("reason_code")))})
        have.add(slug)
    return out


def _editor(d):
    """(videos, error) - `runlog.editor_videos` of the batch, the slugs that are
    file names only; error when there is no 05 or it does not read. CC-0116:
    then the videos refused after the render (`_refused`)."""
    p = Path(d) / factory.runlog().VIDEO_EDITOR_FILE
    if not p.is_file():
        return [], f"{p.name} нет - роликов батч не собрал"
    try:
        json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return [], f"{p.name} не читается ({e})"
    out = []
    for v in factory.runlog().editor_videos(d):
        if SAFE_NAME.match(str(v.get("slug") or "")):
            out.append(dict(v, refused=None))
    return out + _refused(d, {v["slug"] for v in out}), None


def _video_of(root, channel, batch_id, slug, refused=True):
    """(batch dir, editor_videos row, every slug of `videos[]`) of one video,
    or 404. CC-0116: a video refused after the render is one too (its files,
    its card); `refused=False` (a verdict) - 409 `video_refused`."""
    d = batch_dir(root, channel, batch_id)
    vids, _err = _editor(d)
    hit = [v for v in vids if v["slug"] == slug]
    if not hit:
        raise BatchFault(404, "unknown_video", f"Ролика «{slug}» в батче «{channel}/{batch_id}» "
                                               f"нет.",
                         [f"no video {slug!r} in {factory.runlog().VIDEO_EDITOR_FILE} "
                          f"(slugs: {', '.join(v['slug'] for v in vids) or 'none'})"])
    if hit[0].get("refused") and not refused:
        gate = hit[0]["refused"].get("gate") or hit[0]["refused"].get("reason_code")
        raise BatchFault(409, "video_refused", f"Ролик «{slug}» отказан после рендера ({gate}) - "
                                               f"вердикта он не принимает; пересоберите его, "
                                               f"принимают ролик пересборки.",
                         [f"{slug!r} is in {factory.runlog().VIDEO_EDITOR_FILE} refusals[], "
                          f"not videos[] (CF-0727)"])
    return d, hit[0], [v["slug"] for v in vids if not v.get("refused")]


def _mp4(root, channel, batch_id, slug):
    return factory.contained(root, PIPELINE_DIR, channel, batch_id, VIDEOS_DIR,
                             f"{slug}{_acc().VIDEO_SUFFIX}")


def _frame(root, channel, batch_id, slug):
    """The Editor's preview frame `videos/<slug>.jpg` (CF-0674), or None."""
    p = factory.contained(root, PIPELINE_DIR, channel, batch_id, VIDEOS_DIR,
                          f"{slug}{FRAME_SUFFIX}")
    return p if p is not None and p.is_file() else None


def _sheet(root, channel, batch_id, slug):
    """(path, sheet, None) of the first contact sheet of the frame judge's pack,
    or (None, None, why)."""
    pack = (WORK_DIR, slug, PACK_DIRNAME)
    man = factory.contained(root, PIPELINE_DIR, channel, batch_id, *pack, MANIFEST)
    if man is None or not man.is_file():
        return None, None, (f"кадра превью нет: монтаж не снял кадр ({VIDEOS_DIR}/{slug}"
                            f"{FRAME_SUFFIX} нет), а листов судьи кадров "
                            f"(work/{slug}/{PACK_DIRNAME}/) у ролика нет")
    try:
        doc = json.loads(man.read_text(encoding="utf-8"))
        sheets = [s for s in (doc.get("sheets") or []) if isinstance(s, dict) and s.get("file")]
    except (OSError, ValueError, AttributeError) as e:
        return None, None, f"кадра превью нет: {MANIFEST} судьи кадров не читается ({e})"
    if not sheets:
        return None, None, f"кадра превью нет: в {MANIFEST} судьи кадров нет листов"
    s = sheets[0]
    p = factory.contained(root, PIPELINE_DIR, channel, batch_id, *pack, str(s["file"]))
    if p is None or not p.is_file():
        return None, None, f"кадра превью нет: листа {s['file']} нет рядом с {MANIFEST}"
    return p, s, None


def _preview_file(root, channel, batch_id, slug):
    """(path, kind, media type, sheet or None, why) - the frame, else the first
    sheet, else none and why."""
    f = _frame(root, channel, batch_id, slug)
    if f is not None:
        return f, "frame", JPG_TYPE, None, None
    p, s, why = _sheet(root, channel, batch_id, slug)
    if p is None:
        return None, None, None, None, why
    return p, "sheet", PNG_TYPE, s, None


def _preview(root, channel, batch_id, slug, base):
    p, kind, mt, s, why = _preview_file(root, channel, batch_id, slug)
    if p is None:
        return {"available": False, "kind": None, "media_type": None, "url": None,
                "path": None, "tile": None, "grid": None, "reason": why}
    s = s or {}
    return {"available": True, "kind": kind, "media_type": mt, "url": f"{base}/preview",
            "path": _rel(root, p),
            "tile": s.get("tile") if isinstance(s.get("tile"), dict) else None,
            "grid": s.get("grid") if isinstance(s.get("grid"), dict) else None,
            "reason": None}


def _record(root):
    """(rows, error) of the record - a record that does not parse is said, never
    read as no verdicts."""
    acc = _acc()
    try:
        return acc.entries(path=_log_path(root)), None
    except acc.AcceptanceError as e:
        return [], f"журнал приёмки не читается ({e})"


def _uploads(root):
    """CC-0096: ({entry_id: row}, error) of the upload journal
    (`upload_records.uploads` - the journal's one reader), its live rows only:
    a row whose video was replaced or taken down (`removed_at`, `replaced_by`)
    is no upload of the video any more. A row taken off the feed (CC-0179,
    CF-0918 `withdrawn`) stays: the video is in Studio, with no slot and no day,
    and its `upload` says so. A journal that does not read is said,
    never read as no uploads - every video's `upload` is then null and
    `uploads_error` says why."""
    ur = _col().journal()
    try:
        rows = ur.uploads(_journal_path(root))
    except (ur.JournalError, OSError, ValueError) as e:
        return {}, paths.scrub(f"журнал загрузок {UPLOADS_REL} не читается "
                               f"({type(e).__name__}: {e})", paths.prefixes(root))
    out = {}
    for r in rows:
        if not isinstance(r, dict) or r.get("removed_at") or r.get("replaced_by"):
            continue
        eid = str(r.get("entry_id") or "")
        head, _, rest = eid.partition("/")
        if not (head and rest):
            continue
        # the key as it was frozen and as it reads today (a former channel id
        # resolved, as `acceptance.row_keys` reads the record's own rows)
        for k in dict.fromkeys((eid, f"{factory.resolve_channel(root, head)}/{rest}")):
            if str(r.get("recorded_at") or "") >= str(out.get(k, {}).get("recorded_at") or ""):
                out[k] = r
    return out, None


def _upload(ups, keys):
    """The video's upload: the live journal row of its acceptance row's key
    (`<channel>/<batch_id>/<slug>`, every name the key goes by) - never matched
    by slug alone (one slug goes up from several batches)."""
    for k in keys:
        r = ups.get(k)
        if r:
            return {f: r.get(f) for f in UPLOAD_FIELDS}
    return None


def _upload_keys(channel, batch_id, cid, slug, acc_row):
    """Every key the video's journal row may carry: the acceptance's own
    (`entry_id` with the channel as it reads today), the key frozen into the
    acceptance row, and the route's form (`rebuilds/<ts>/<slug>` for a
    rebuild, as the acceptance of a rebuild is written)."""
    acc = _acc()
    keys = [acc.entry_id(cid, batch_id, slug)] if cid else []
    if acc_row:
        keys += acc.row_keys(acc_row)
    keys.append(f"{channel}/{batch_id}/{slug}")
    return list(dict.fromkeys(keys))


ROW_FIELDS = ("reason_code", "reason", "answer", "answer_verbatim", "recorded_at", "note",
              "amended_because", "history", "topic_id", "publish_path", "queued_by",
              "queued_verdicts")


def _acceptance(root, cid, batch_id, slug, rows, err):
    if err:
        return None
    acc = _acc()
    try:
        st = acc.state(cid, batch_id, slug, rows=rows, holds_path=_holds_path(root))
    except acc.AcceptanceError as e:
        st = {"entry_id": acc.entry_id(cid, batch_id, slug), "slug": slug,
              "state_error": str(e)}
    row = acc.find(cid, batch_id, slug, rows=rows) or {}
    return dict(st, **{k: row.get(k) for k in ROW_FIELDS})


def _video(root, channel, batch_id, cid, v, rows, err, scores, prefix, ups, repairs=None):
    slug = v["slug"]
    base = f"{prefix}/batches/{channel}/{batch_id}/videos/{slug}"
    mp4 = _mp4(root, channel, batch_id, slug)
    entry = v.get("entry") or {}
    # CC-0119: the 05 `refusals[]` row as the Editor wrote it - its
    # `score.log[].where.shot` and `note` can name a clip absolutely
    # (`<root>/pipeline/<c>/<b>/work/<slug>/clips/...mp4`): cut as every answer
    refused = paths.clean(v["refused"], root) if v.get("refused") else None
    return {"slug": slug, "script_id": v.get("script_id"), "qc_passed": v.get("qc_passed"),
            "score_line": (refused or {}).get("score_line") or scores.get(slug)
            or entry.get("score_line"),
            "refused": refused,
            "duration": entry.get("duration") if isinstance(entry.get("duration"),
                                                            (int, float)) else None,
            "mp4": {"url": f"{base}/mp4", "exists": bool(mp4 and mp4.is_file()),
                    "bytes": mp4.stat().st_size if mp4 and mp4.is_file() else None,
                    "path": _rel(root, mp4) if mp4 else None},
            "preview": _preview(root, channel, batch_id, slug, base),
            "card": _card_short(root, channel, batch_id, slug, f"{base}/card"),
            "acceptance": _acceptance(root, cid, batch_id, slug, rows, err),
            "accept_url": f"{base}/acceptance",
            "upload": _upload(ups, _upload_keys(
                channel, batch_id, cid, slug,
                _acc().find(cid, batch_id, slug, rows=rows) if cid and not err else None)),
            "score": score_short(root, channel, batch_id, slug, entry, refused,
                                 f"{base}/score"),
            # CC-0171 (CF-0881): its repair pass after the frame judge
            "repair": paths.clean(factory.with_reason_ru(repairs[v.get("script_id")]), root)
            if v.get("script_id") in (repairs or {}) else None,
            "rebuilt_in": []}


def _batch_videos(root, channel, batch_id, d, rows, err, prefix, ups):
    cid = _col()._batch_channel(d, root)
    vids, verr = _editor(d)
    made = [v["slug"] for v in vids if not v.get("refused")]
    scores = _acc().score_lines(cid, batch_id, made, batch_dir=d) if made else {}
    fj = Path(d) / repair_refill.FJ
    _counts, repairs = repair_refill.repairs(_read(fj)) if fj.is_file() else (None, {})
    return cid, verr, [_video(root, channel, batch_id, cid, v, rows, err, scores, prefix, ups,
                              repairs) for v in vids]


def _read(p):
    try:
        doc = json.loads(Path(p).read_text(encoding="utf-8"))
        return doc if isinstance(doc, dict) else {}
    except (OSError, ValueError):
        return {}


def _source_of(d):
    """The batch a rebuild was made of: `run-state.json` `rebuild.of` (CF-0668),
    else its 05's `rebuild_of` (CF-0416); None for a batch that is no rebuild."""
    st = _read(Path(d) / factory.run_executor().STATE_FILE)
    of = (st.get("rebuild") or {}).get("of") if isinstance(st.get("rebuild"), dict) else None
    if not isinstance(of, dict):
        of = _read(Path(d) / factory.runlog().VIDEO_EDITOR_FILE).get("rebuild_of")
    if not isinstance(of, dict) or not of.get("batch_id"):
        return None
    return of


def _path_form(root, of):
    """«<dir>/<batch_id>» of a source as the routes take it: the dir of its
    `path` (pipeline/<dir>/<id>), else its channel."""
    parts = Path(str(of.get("path") or "")).parts
    dirname = parts[-2] if len(parts) >= 2 and parts[-1] == of.get("batch_id") else \
        of.get("channel")
    return f"{dirname}/{of['batch_id']}" if dirname else None


def _rebuilds_of(root, cid, batch_id):
    group = factory.run_plan().REBUILDS_GROUP
    base = factory.contained(root, PIPELINE_DIR, group)
    if base is None or not base.is_dir():
        return []
    out = []
    for child in sorted(base.iterdir()):
        if not SAFE_NAME.match(child.name):
            continue
        d = factory.contained(root, PIPELINE_DIR, group, child.name)
        if d is None or not d.is_dir():
            continue
        of = _source_of(d)
        if of and of.get("batch_id") == batch_id and \
                factory.resolve_channel(root, of.get("channel")) == cid:
            out.append(d)
    return out


def videos(root, channel, batch_id, prefix=""):
    """The batch's videos, its rebuilds beside it (a source) or its source (a
    rebuild), the record's reason codes - see the module's docstring."""
    d = batch_dir(root, channel, batch_id)
    rows, err = _record(root)
    ups, uerr = _uploads(root)
    cid, verr, vids = _batch_videos(root, channel, batch_id, d, rows, err, prefix, ups)
    of = _source_of(d)
    rebuild_of = None
    if of:
        rebuild_of = {"channel": factory.resolve_channel(root, of.get("channel")),
                      "batch_id": of.get("batch_id"), "batch": _path_form(root, of)}
    rebuilds = []
    group = factory.run_plan().REBUILDS_GROUP
    if channel != group and cid:
        by_slug = {v["slug"]: v for v in vids}
        for rd in _rebuilds_of(root, cid, batch_id):
            _c, rerr, rv = _batch_videos(root, group, rd.name, rd, rows, err, prefix, ups)
            path = f"{group}/{rd.name}"
            for v in rv:
                if v["slug"] in by_slug:
                    by_slug[v["slug"]]["rebuilt_in"].append(path)
            rebuilds.append({"batch": path, "batch_id": rd.name, "dir": _rel(root, rd),
                             "editor_error": rerr, "videos": rv})
    codes = []
    if not err:
        try:
            codes = [{"code": k, "count": e.get("count"), "phrases": list(e.get("phrases") or [])}
                     for k, e in _acc().reasons(rows=rows).items()]
        except Exception:                                   # noqa: BLE001
            codes = []
    return {"batch": f"{channel}/{batch_id}", "channel": cid, "batch_id": batch_id,
            "dir": _rel(root, d), "editor_error": verr, "rebuild_of": rebuild_of,
            "videos": vids, "rebuilds": rebuilds, "reason_codes": codes,
            "score_model": score_model(root),
            "acceptance_error": err, "uploads_error": uerr}


# ---------------------------------------------------------------- the files
def mp4_path(root, channel, batch_id, slug):
    """The mp4 to serve, or 404."""
    _video_of(root, channel, batch_id, slug)
    p = _mp4(root, channel, batch_id, slug)
    if p is None or not p.is_file():
        raise BatchFault(404, "no_mp4", f"Файла ролика «{slug}» нет в батче.",
                         [f"no {VIDEOS_DIR}/{slug}.mp4 in {PIPELINE_DIR}/{channel}/{batch_id}"])
    return p


def preview_path(root, channel, batch_id, slug):
    """(path, media type) of the preview - the Editor's frame, else the frame
    judge's first contact sheet - or 404 with why."""
    _video_of(root, channel, batch_id, slug)
    p, _kind, mt, _s, why = _preview_file(root, channel, batch_id, slug)
    if p is None:
        raise BatchFault(404, "no_preview", why[:1].upper() + why[1:] + ".",
                         [f"no {VIDEOS_DIR}/{slug}{FRAME_SUFFIX} and no "
                          f"{WORK_DIR}/{slug}/{PACK_DIRNAME}/{MANIFEST} with a sheet"])
    return p, mt


# ---------------------------------------------------------------- the score (CC-0125)
#: Where a video's score was read from: its log beside the plan, else the 05.
SCORE_FILE, SCORE_05 = "plan.score.json", "05"
#: The stages of a video's score (`score.STAGES` + the Researcher's 6b,
#: `runlog/scores.STAGE_6B`) in Russian. The factory keeps no Russian words
#: for its stages - these are the center's.
STAGE_RU = {"6b": "проверка сценария (6b)", "plan": "план монтажа", "render": "рендер",
            "qc": "проверка рендера (QC)", "judge": "судья кадров"}
STAGE_ORDER = ("6b", "plan", "render", "qc", "judge")
FORECAST = "forecast"           # = score.FORECAST


def _sm():
    return factory.score_model()


def _ledger(root):
    return Path(root) / "shared" / "gate-prices.json"


def score_model(root):
    """{start, threshold, tiers [{name, floor}] best first, below: "F", status,
    error} - the root's price table through `score.load_model` (the floors the
    tiers start at; under the lowest one a video is F, `tier_of`). A table
    that does not load: `tiers: []` and why."""
    try:
        m = _sm().load_model(_ledger(root))
    except Exception as e:                              # noqa: BLE001 - said, not raised
        return {"start": None, "threshold": None, "tiers": [], "below": "F", "status": None,
                "error": paths.clean(f"таблица цен не читается: {e}", root)}
    return {"start": m["start"], "threshold": m["threshold"],
            "tiers": [{"name": n, "floor": f} for n, f in m["tiers"]], "below": "F",
            "status": m.get("status"), "error": None}


def _score_file(root, channel, batch_id, slug):
    return factory.contained(root, PIPELINE_DIR, channel, batch_id, WORK_DIR, slug,
                             f"plan{_sm().LOG_SUFFIX}")


def _score_doc(root, channel, batch_id, slug):
    """The video's `work/<slug>/plan.score.json` (CF-0434) as a dict with a
    `score` block, or None."""
    p = _score_file(root, channel, batch_id, slug)
    if p is None or not p.is_file():
        return None
    d = _read(p)
    return d if isinstance(d.get("score"), dict) else None


def _block_05(entry, refused):
    """The score block the 05 carries: a refusal's, else the built video's."""
    for b in ((refused or {}).get("score"), (entry or {}).get("score")):
        if isinstance(b, dict) and b.get("score") is not None:
            return b
    return None


def score_short(root, channel, batch_id, slug, entry, refused, url):
    """{tier, score, threshold, passed, stopped_at, source, url} - the badge;
    None when neither the log nor the 05 has a score."""
    doc = _score_doc(root, channel, batch_id, slug)
    block, source = (doc["score"], SCORE_FILE) if doc else (_block_05(entry, refused), SCORE_05)
    if not block or block.get("score") is None:
        return None
    return {"tier": block.get("tier"), "score": block.get("score"),
            "threshold": block.get("threshold"), "passed": block.get("passed"),
            "stopped_at": block.get("stopped_at"), "source": source, "url": url}


def rule_label(rule):
    """The Russian name of a rule - the words the factory's score line prints
    (`score.LABELS`, `HARD_LABELS`, the judge's `судья: <verdict>`); a rule
    the factory has no words for: its own short name, as the line prints it."""
    sm = _sm()
    rule = str(rule or "")
    short = rule.split(".", 1)[1] if rule.startswith("score.") else rule
    if short.startswith("hard."):
        tail = short.rsplit(".", 1)[-1]
        return sm.HARD_LABELS.get(tail, tail)
    if short.startswith(sm.JUDGE_PREFIX):
        return f"судья: {short[len(sm.JUDGE_PREFIX):]}"
    return sm.LABELS.get(short, short)


def _is_hard(rule, model_rules):
    r = (model_rules or {}).get(rule)
    if isinstance(r, dict):
        return r.get("mode") == "hard"
    return str(rule or "").startswith("score.hard.")


_SHOT_PREFIX = re.compile(r"^a\d+_")
_SHOT_EXT = re.compile(r"\.[A-Za-z0-9]{1,5}$")


def shot_ru(shot):
    """A shot for display (CF-0751 follow-up): the clip's file name without
    the Editor's `aNN_` prefix and its extension, `_` / `-` as spaces
    (`.../a04_mine-cart.mp4` -> `mine cart`); a shot id without a path
    (`yt:26`) as is; null for no shot."""
    if not isinstance(shot, str) or not shot.strip():
        return None
    name = shot.strip().replace("\\", "/").rsplit("/", 1)[-1]
    base = name if name.startswith(".") else _SHOT_EXT.sub("", name)
    text = " ".join(re.sub(r"[_-]+", " ", _SHOT_PREFIX.sub("", base)).split())
    return text or name


def _is_judge(rule):
    short = str(rule or "")
    short = short.split(".", 1)[1] if short.startswith("score.") else short
    return short.startswith(_sm().JUDGE_PREFIX)


def _note_ru(rule, row):
    """The Russian of the row's note (CF-0751): the log's own `note_ru`, else
    the factory's `score.note_ru` over the note (a log written before
    CF-0751); null for the judge's prose and a note no template covers."""
    if _is_judge(rule):
        return None
    ru = row.get("note_ru")
    if isinstance(ru, str) and ru.strip():
        return ru
    return _sm().note_ru(row.get("note"))


def _finding(f, stage, e=None, hard=False):
    w = f.get("where") if isinstance(f.get("where"), dict) else {}
    row = e or f
    src = row.get("source")
    return {"rule": f.get("rule"), "label_ru": rule_label(f.get("rule")), "stage": stage,
            "block": w.get("block"), "t": w.get("t"), "shot": w.get("shot"),
            "shot_ru": shot_ru(w.get("shot")),
            "where": w, "price": (e or {}).get("price"),
            "units": row.get("units"), "hook": bool((e or {}).get("hook")),
            "capped": bool((e or {}).get("capped")), "source": src,
            "note": row.get("note"), "note_ru": _note_ru(f.get("rule"), row),
            "hard": hard, "forecast": src == FORECAST}


def _findings(stages, block, model_rules):
    """Every finding of the log in stage order (`stages_block`'s order), each
    paired with what it cost: a penalty with the next `log[]` row of its rule
    (`score()` writes one row per real penalty, in this order), a hard one
    `hard: true` (no price - the hard list refuses), a forecast `forecast:
    true` (left out of the score, Q17). Rows of the log no stage names (a 05
    block without its stages) follow, stage null."""
    log = [e for e in block.get("log") or [] if isinstance(e, dict)]
    hard = [h for h in block.get("hard") or [] if isinstance(h, dict)]
    out, li = [], 0
    rows = [s for s in stages or [] if isinstance(s, dict)]
    rows.sort(key=lambda s: STAGE_ORDER.index(s["stage"]) if s.get("stage") in STAGE_ORDER
              else 99)
    used_hard = 0
    for s in rows:
        for f in s.get("findings") or []:
            if not isinstance(f, dict):
                continue
            if f.get("source") == FORECAST:
                out.append(_finding(f, s.get("stage")))
            elif _is_hard(f.get("rule"), model_rules):
                out.append(_finding(f, s.get("stage"), hard=True))
                used_hard += 1
            elif li < len(log) and log[li].get("rule") == f.get("rule"):
                out.append(_finding(f, s.get("stage"), log[li]))
                li += 1
            else:
                out.append(_finding(f, s.get("stage")))
    for e in log[li:]:
        out.append(_finding(e, None, e))
    for h in hard[used_hard:]:
        out.append(_finding(h, None, hard=True))
    return out


def score(root, channel, batch_id, slug):
    """The video's score for «оценка ролика» (CC-0125): its log
    `work/<slug>/plan.score.json` (CF-0434), else the score block its 05 row
    carries (a refused video's `refusals[].score`, a built one's
    `videos[].score` - then without stages); 404 when the video or any score
    is missing. Every string through `paths.clean` (the Editor names clips by
    absolute path in `where.shot` / `note`)."""
    _d, v, _made = _video_of(root, channel, batch_id, slug)
    doc = _score_doc(root, channel, batch_id, slug)
    if doc:
        block, source = doc["score"], SCORE_FILE
        stages, stage_scores, line = doc.get("stages"), doc.get("stage_scores"), \
            doc.get("score_line")
    else:
        refused = v.get("refused") or {}
        block, source = _block_05(v.get("entry"), refused), SCORE_05
        stages = None
        stage_scores = (block or {}).get("stages")
        line = refused.get("score_line") or (v.get("entry") or {}).get("score_line")
    if not block:
        raise BatchFault(404, "no_score", f"Оценки ролика «{slug}» нет: монтаж не записал "
                                          f"её лог (work/{slug}/{SCORE_FILE}), а в 05 у "
                                          f"ролика очков нет.",
                         [f"no {WORK_DIR}/{slug}/{SCORE_FILE} in "
                          f"{PIPELINE_DIR}/{channel}/{batch_id} and no score in "
                          f"{factory.runlog().VIDEO_EDITOR_FILE}"])
    model = score_model(root)
    try:
        rules = _sm().load_model(_ledger(root))["rules"]
    except Exception:                                   # noqa: BLE001 - by the rule's name
        rules = None
    st = []
    for s in stage_scores or []:
        if isinstance(s, dict):
            st.append({"stage": s.get("stage"), "label_ru": STAGE_RU.get(s.get("stage"),
                                                                          s.get("stage")),
                       "charged": s.get("charged"), "score_after": s.get("score_after"),
                       "tier_after": s.get("tier_after"), "at": s.get("at")})
    by_rule = {k: dict(v, label_ru=rule_label(k)) for k, v in (block.get("by_rule") or {}).items()
               if isinstance(v, dict)}
    ans = {"batch": f"{channel}/{batch_id}", "slug": slug, "script_id": v.get("script_id"),
           "source": source,
           "path": _rel(root, _score_file(root, channel, batch_id, slug)) if doc else None,
           "tier": block.get("tier"), "score": block.get("score"), "start": block.get("start"),
           "threshold": block.get("threshold"), "passed": block.get("passed"),
           "stopped_at": block.get("stopped_at"),
           "stopped_at_ru": STAGE_RU.get(block.get("stopped_at"), block.get("stopped_at")),
           "prices_status": block.get("prices_status"),
           "forecast_ignored": block.get("forecast_ignored"),
           "tiers": model["tiers"], "model_error": model["error"],
           "stages": st, "findings": _findings(stages, block, rules), "by_rule": by_rule,
           "score_line": line}
    return paths.clean(ans, root)


# ---------------------------------------------------------------- the card (CF-0017)
def _card_file(root, channel, batch_id, slug):
    parts = Path(_card_mod().CARD_DIR).parts
    return factory.contained(root, PIPELINE_DIR, channel, batch_id, *parts, f"{slug}.md")


def _card_text(p):
    try:
        return p.read_text(encoding="utf-8"), None
    except (OSError, UnicodeDecodeError) as e:
        return None, f"карточка не читается ({e})"


def _card_short(root, channel, batch_id, slug, url):
    """{exists, ready, why, title, url} - what the list shows of the card."""
    p = _card_file(root, channel, batch_id, slug)
    d = batch_dir(root, channel, batch_id)
    if p is None or not p.is_file():
        return {"exists": False, "ready": False, "title": None, "url": url,
                "why": "карточки нет - publish_card.py build для ролика не запускался",
                "card": _card_block(root, d, slug, None)}
    text, err = _card_text(p)
    if text is None:
        return {"exists": True, "ready": False, "why": err, "title": None, "url": url,
                "card": None}
    ready, why = _card_mod().placeable(text)     # CF-0747: ready or ruled
    title, _d = _note_mod().title_and_description(_note_mod().sections(text))
    return {"exists": True, "ready": bool(ready), "why": why, "title": title or None,
            "url": url, "card": _card_block(root, d, slug, text)}


def _card_block(root, d, slug, text):
    """CC-0127: the card's state as the center shows it (`api/card_center.py`
    card_block: card_status of the text, the last build from the center)."""
    from . import card_center                                   # noqa: PLC0415
    return card_center.card_block(root, d, slug, text)


def card(root, channel, batch_id, slug):
    """The publication card parsed by the factory's readers - see the module's
    docstring; 404 when the video has none."""
    d, _row, _slugs = _video_of(root, channel, batch_id, slug)
    p = _card_file(root, channel, batch_id, slug)
    if p is None or not p.is_file():
        raise BatchFault(404, "no_card", f"Карточки публикации ролика «{slug}» нет - "
                                         f"publish_card.py build для него не запускался.",
                         [f"no {Path(_card_mod().CARD_DIR) / (slug + '.md')} in "
                          f"{PIPELINE_DIR}/{channel}/{batch_id}"])
    text, err = _card_text(p)
    if text is None:
        raise BatchFault(500, "card_broken", "Карточка публикации не читается.", [err])
    pc, pn = _card_mod(), _note_mod()
    ready, why = pc.placeable(text)     # CF-0747: ready or ruled
    sec = pn.sections(text)
    title, description = pn.title_and_description(sec)
    tags, publish_at, synthetic, note_error = None, None, None, None
    try:
        parsed = pn.parse(str(p))
        tags, synthetic = parsed["tags"], parsed["contains_synthetic"]
        publish_at = parsed["publish_at"].isoformat().replace("+00:00", "Z") \
            if parsed["publish_at"] else None
    except pn.NoteError as e:
        note_error = str(e)
    mark = pc.mark_of(text)
    return {"batch": f"{channel}/{batch_id}", "slug": slug, "path": _rel(root, p),
            "ready": bool(ready), "why": why, "status": (mark or {}).get("status"),
            "title": title, "description": description,
            "description_blocks": [b.strip() for b in description.split("\n\n") if b.strip()],
            "tags": tags, "tags_raw": sec.get("Теги"), "publish_at": publish_at,
            "publish_section": sec.get("Публикация"), "contains_synthetic": synthetic,
            "note_error": note_error,
            "sections": [{"name": k, "text": v} for k, v in sec.items()],
            "problems": list((mark or {}).get("problems") or []),
            "source": (mark or {}).get("source"), "fact_checks": list(
                (mark or {}).get("fact_checks") or []),
            "claims": (mark or {}).get("claims"), "mark": mark, "raw": text,
            "card": _card_block(root, d, slug, text)}


# ---------------------------------------------------------------- the verdict (CF-0328)
#: Who gave the verdict, as the commit's subject and the queue name him (CF-0675).
BY = "user (центр)"

#: The factory's refusal codes (CF-0676, `AcceptanceError.code`) that are not
#: the verdict's fault: the record or its queue does not read (409 - a human
#: puts the file right), the commit git did not make (500). Every other code is
#: a refusal of the verdict itself (422).
UNREADABLE = frozenset({"record_unreadable", "record_not_a_log", "queue_unreadable",
                        "queue_not_a_verdict"})
NOT_COMMITTED = frozenset({"not_committed", "record_outside_repo"})


def _refusal(e):
    """The factory's refusal as the problem: its stable code, its Russian line
    (`text_ru`), its English words behind «подробнее»."""
    status = 409 if e.code in UNREADABLE else 500 if e.code in NOT_COMMITTED else 422
    return BatchFault(status, e.code, e.text_ru, [str(e)])


def _flushed(root, f):
    """`commit_pending`'s answer as the screen reads it (None: there was no queue)."""
    if not f:
        return None
    out = {k: f.get(k) for k in ("committed", "commit", "subject", "applied", "conflicts",
                                 "failed", "left", "why")}
    out["left_out"] = [x for x in (_left_out(root, x) for x in f.get("left_out") or []) if x]
    return out


def accept(root, channel, batch_id, slug, verdict, words, reason=None, reason_code=None,
           amend=None):
    """The user's press: `acceptance.record_and_commit` (CF-0675) - one commit of
    the record, or the queue under an open batch - see the module's docstring.
    Answers the row, the record's file, the commit or why the verdict waits,
    the queue flushed before it, and the CC-0018 seam's answer for a
    «переделать»."""
    if verdict not in VERDICTS:
        raise BatchFault(422, "invalid", "Вердикт - «yes», «no» или «redo».",
                         [f"verdict {verdict!r}: not one of {sorted(VERDICTS)}"])
    d, _v, shown = _video_of(root, channel, batch_id, slug, refused=False)
    cid = _col()._batch_channel(d, root)
    if not cid:
        raise BatchFault(409, "refused", f"Батч «{channel}/{batch_id}» не называет канал - "
                                         f"вердикт не к чему привязать.",
                         [f"collect._batch_channel({d}) is None"])
    log = _log_path(root)
    if not log.parent.is_dir():
        raise BatchFault(409, "refused", "В фабрике нет каталога publish/ - журнал приёмки "
                                         "некуда записать.", [f"no directory {log.parent}"])
    acc = _acc()
    note = REDO_NOTE if verdict == "redo" else YES_NO_NOTE
    with _WRITE:
        try:
            res = acc.record_and_commit(cid, d.name, slug, VERDICTS[verdict], words, by=BY,
                                        root=root, log=log, reason=reason,
                                        reason_code=reason_code or None, note=note,
                                        amend=amend or None, shown=shown, batch_dir=d,
                                        strict_topic=True)
        except acc.AcceptanceError as e:
            raise _refusal(e)
        except OSError as e:
            raise BatchFault(500, "acceptance_broken", "Журнал приёмки не записался.",
                             [f"{type(e).__name__}: {e}"])
    row = res["row"]
    redo = None
    if verdict == "redo":
        if REDO_QUEUE is None:
            redo = {"queued": False, "reason": REDO_NOT_YET, "request": None}
        else:
            redo = dict({"queued": True, "reason": None},
                        request=REDO_QUEUE(root, row, words, reason))
    rows, err = _record(root)
    return {"batch": f"{channel}/{batch_id}", "slug": slug, "verdict": verdict,
            "row": row, "log": _rel(root, log),
            "pending": bool(res["pending"]), "committed": bool(res["committed"]),
            "commit": res["commit"], "subject": res["subject"],
            "queue": _rel(root, res["queue"]) if res.get("queue") else None,
            "batches": [{"dir": _rel(root, b["dir"]), "why": b.get("why")}
                        for b in res.get("batches") or []],
            "flushed": _flushed(root, res.get("flushed")), "redo": redo,
            "queued": _queued(root, res.get("queued")),
            "left_out": _left_out(root, res.get("left_out")),
            "acceptance": _acceptance(root, cid, d.name, slug, rows, err)}


def _queued(root, q):
    """CC-0122: what the factory did with an accepted video's render (CF-0738
    `queued`: into the channel's копилка `publish/<c>/_queue/`, already placed,
    or why not) - `{code, text_ru, publish_path, ok, skipped, refused,
    changed, card_build, left_out, alert_ru, namesake, notified}`; None for a
    rejection. CC-0152 (CF-0821): `left_out` - accepted, not in the копилка
    (`text_ru` then opens with «НЕ В КОПИЛКЕ: »), `alert_ru` its loud line,
    `namesake` the placed video under the same name, `notified` the bus's
    answer. The path through `paths.clean`.
    CC-0127: `card_build` - the card's build the acceptance started by itself
    (CF-0747 `card_center.short`: ok, launched, skipped, run_id, log, refusals
    [code]); null when the factory started none (not queued). CC-0174 (CF-0891):
    `why` - the refusal's own line (`card_center.short`: «code: line; ...») when
    the build did not start; null otherwise and in an older answer."""
    if not q:
        return None
    cb = q.get("card_build")
    if isinstance(cb, dict):
        cb = {"ok": bool(cb.get("ok")), "launched": bool(cb.get("launched")),
              "skipped": cb.get("skipped"), "run_id": cb.get("run_id"), "log": cb.get("log"),
              "refusals": [str(c.get("code") if isinstance(c, dict) else c)
                           for c in cb.get("refusals") or []], "error": cb.get("error"),
              "why": cb.get("why") if isinstance(cb.get("why"), str) else None}
    else:
        cb = None
    return paths.clean({"code": q.get("code"), "text_ru": q.get("text_ru"),
                        "publish_path": q.get("publish_path"), "ok": bool(q.get("ok")),
                        "skipped": bool(q.get("skipped")), "refused": bool(q.get("refused")),
                        "changed": bool(q.get("changed")), "card_build": cb,
                        "left_out": bool(q.get("left_out")), "alert_ru": q.get("alert_ru"),
                        "namesake": _namesake(q.get("namesake")),
                        "notified": _notified(q.get("notified"))}, root)


def _namesake(ns):
    """CC-0152 (CF-0821): `{entry_id, publish_path, why}` of the placed video
    that only carries this name; None."""
    if not isinstance(ns, dict):
        return None
    return {"entry_id": ns.get("entry_id"), "publish_path": ns.get("publish_path"),
            "why": ns.get("why")}


def _notified(n):
    """CC-0152 (CF-0821): the notification bus's answer for a left-out video
    (`notify.send`: {status, ...}); None when nothing was sent."""
    return dict(n) if isinstance(n, dict) else None


def _left_out(root, x):
    """CC-0152 (CF-0821): `acceptance._left_out` - an accepted video the копилка
    did not get: `{entry_id, slug, batch_id, code, text_ru, alert_ru,
    namesake, notified}`; None."""
    if not isinstance(x, dict):
        return None
    return paths.clean({"entry_id": x.get("entry_id"), "slug": x.get("slug"),
                        "batch_id": x.get("batch_id"), "code": x.get("code"),
                        "text_ru": x.get("text_ru"), "alert_ru": x.get("alert_ru"),
                        "namesake": _namesake(x.get("namesake")),
                        "notified": _notified(x.get("notified"))}, root)
