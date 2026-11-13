"""CC-0020: the statistics and the analyst, read only - the videos' metrics,
the analyst's summary by style, what Studio was read to say, the footage the
scripts wanted. Only through the factory's own functions (`api/factory.py`),
nothing of the API's own on top:

    agents/analyst/metrics_store.py   read_daily, read_windows, window, video_rows,
                                      read_runs, read_studio, latest_studio,
                                      last_visit, WINDOW_DAYS (CF-0020/CF-0588/CF-0624)
    agents/analyst/metrics.py         default_day - the Pacific yesterday
    agents/analyst/summary.py         build, channels_of (CF-0021) - what
                                      `summary.py daily` writes, built on the ask
    agents/analyst/footage_wanted.py  build, DEFAULT_ARCHIVE (CF-0023) - what
                                      `footage_wanted.py collect` writes
    agents/analyst/studio_read.py     studio_settings, last_videos, due,
                                      no_pipeline, STUDIO_VIDEO_URL (CF-0588) -
                                      `studio_read.py plan` / `due`
    shared/runlog/publish_profile.py  diversity, render_diversity, AXES,
                                      DEFAULT_LAST, _load (CF-0440) - what
                                      `runlog diversity --json` prints

**Nothing here writes.** Every route is a GET: the collection (`collect`,
`merge`, `merge_windows`, `append_run`), the summary's `write`, the footage
list's `write`, the Studio read's `parse_read` / `record` (`merge_studio`,
`append_visit`) and the notices are never named
- `tests/test_cc_api_analytics.py` walks this file's names. Nothing touches
the network: `analytics_client` makes its Google client only in `collect`.

**The overview** (`overview`): the channels of the upload journal
(`summary.channels_of`), each with its last collection run
(`read_runs`, the last line of `analytics/<ch>/runs.jsonl`) and the days a
summary was written for (`analytics/<ch>/summary/<day>.json`, newest first).

**A channel's metrics** (`metrics`): what `metrics.py show` prints - every
video of `daily.jsonl` and `windows.jsonl`, its YouTube window of the first N
days (`window`; none is `null`, never recombined from the daily rows), how
many daily rows it has and the last one, its last Studio read
(`latest_studio`). `collected` says whether N is a window the factory asks
(`WINDOW_DAYS`). **A video's series** (`video`): its daily rows, window rows
and Studio reads as stored.

**The summary** (`summary`): `summary.build` for the day (default
`metrics.default_day` - what `summary.py daily` takes) and N - nothing is
written, the same report the daily run writes. `saved_days` / `saved` beside
it; `saved_summary` reads the one written for a day as it is.

**The footage wanted** (`footage`): `footage_wanted.build` over the root's
batches; the packed ones (Archive, `DEFAULT_ARCHIVE`) only with `packed` - a GET
does not read a month of zips unless asked. `reasons_ru` (CC-0113): every
reason code of the report in Russian - `funnel.reason_ru` (CF-0714), else
footage_wanted's own `REASONS`; null for a code neither knows.

**Studio** (`studio`): the channel's `analyst.studio_read` settings (or the
factory's refusal of them), the last N published videos with their Studio
links (`last_videos`), whether a read is due (`due`), the last visit
(`last_visit`), the latest read of every video
read so far (`latest_studio`). Entering what was read is a write of
`studio_read.record`, not here.

**The feed's diversity** (`diversity`, CC-0108): what `runlog diversity
--last N` reports - `publish_profile.diversity` over the rows of
`publish/acceptance-log.json` read by the factory's own `_load`, as the CLI
does: the last N videos the user accepted and still stands behind, the share
of each fact kind, pattern, rhythm and hook opener (an axis's values as
`{value, count, share}`, the CLI's `[value, count, share]`), the videos whose
profile is not written yet and were read from their batch on the spot
(`read_live` - nothing is written; `runlog profile --fill` writes them), and
the CLI's lines (`render_diversity`) verbatim. The feed is the factory's
whole one - across channels and rebuilds, as the CLI counts it, unless a
channel is asked. A missing log is an empty feed, `log_exists: false`; one that does not
parse as an object is an empty feed too, `log_read: false`, and since CF-0719
(the factory's `_load` raises `PublishProfileError` for it) `log_error` names
the file and why - the text goes out through `paths.clean` as the whole
answer does. `?channel=` (CC-0119, `publish_profile.diversity(channel=...)`,
CF-0719): only that channel's feed - what `runlog diversity --channel C`
prints; an unknown channel is 404 `unknown_channel`.

Every refusal is a `BatchFault` (`{message, code, details}`). `FACTORY_KW`
holds the factory's own injection points (`now`, `archive`) - empty in
production; the tests put a clock and a stand-in archive there.
"""
import json
import re
from datetime import date
from pathlib import Path

from . import factory
from .batches import BatchFault, _channel

ANALYTICS_DIR = "analytics"          # = metrics_store.STORE, studio_read.store_root
SUMMARY_DIR = "summary"              # = summary.SUMMARY_DIR
PUBLISH_DIR, JOURNAL = "publish", "uploads.json"
ACCEPTANCE = "acceptance-log.json"   # = acceptance.ACCEPTANCE_LOG_REL
FIRST_DAYS_DEFAULT = 7               # = summary.DEFAULT_FIRST_DAYS
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: The factory's own injection points - empty in production.
FACTORY_KW = {}


# ---------------------------------------------------------------- the factory's modules
def _ms():
    return factory.metrics_store()


def _path(root, *parts, code, what):
    p = factory.contained(root, *parts)
    if p is None:
        raise BatchFault(409, code, f"{'/'.join(parts)} leads out of the factory root",
                         [f"{what}: {'/'.join(parts)} is a link out of {root} the lock does "
                          f"not declare (factory.contained)"])
    return p


def _store(root):
    return _path(root, ANALYTICS_DIR, code="store_unreadable", what="the analytics store")


def _journal(root):
    return _path(root, PUBLISH_DIR, JOURNAL, code="journal_unreadable", what="the journal")


def _fault(code, e, status=409):
    return BatchFault(status, code, str(e), [f"{type(e).__name__}: {e}"])


def _read(fn, *a, **k):
    """A store read; a line that does not parse is 409 `store_unreadable` with
    the factory's line."""
    ms = _ms()
    try:
        return fn(*a, **k)
    except (ms.StoreError, ValueError, OSError) as e:
        raise _fault("store_unreadable", e) from e


def _day(text, what="day"):
    if not DAY_RE.match(text or ""):
        raise BatchFault(422, "bad_day", f"{what} {text!r}: give YYYY-MM-DD", [])
    try:
        return date.fromisoformat(text)
    except ValueError as e:
        raise BatchFault(422, "bad_day", f"{what} {text!r}: {e}", []) from e


def _saved_days(st, cid):
    d = st / cid / SUMMARY_DIR
    if not d.is_dir():
        return []
    return sorted((p.stem for p in d.glob("*.json") if DAY_RE.match(p.stem)), reverse=True)


# ---------------------------------------------------------------- the overview
def overview(root):
    su, ms = factory.analyst_summary(), _ms()
    jr = factory.collect().journal()
    st = _store(root)
    try:
        chans = su.channels_of(_journal(root))
    except (jr.JournalError, ValueError) as e:
        raise _fault("journal_unreadable", e) from e
    out = []
    for ch in chans:
        runs = _read(ms.read_runs, ch, st)
        out.append({"channel": ch, "last_run": runs[-1] if runs else None,
                    "summary_days": _saved_days(st, ch)})
    return {"channels": out, "window_days": list(ms.WINDOW_DAYS)}


# ---------------------------------------------------------------- the metrics
def metrics(root, channel, first_days=FIRST_DAYS_DEFAULT):
    """`metrics.py show`: the videos of the store with YouTube's window."""
    cid = _channel(root, channel)
    ms, st = _ms(), _store(root)
    rows = _read(ms.read_daily, cid, st)
    wrows = _read(ms.read_windows, cid, st)
    studio = _read(ms.read_studio, cid, st)
    runs = _read(ms.read_runs, cid, st)
    vids = sorted({r["video_id"] for r in rows} | {r["video_id"] for r in wrows})
    videos = []
    for vid in vids:
        vr = ms.video_rows(rows, vid)
        videos.append({"video_id": vid, "window": _read(ms.window, wrows, vid, first_days),
                       "daily_rows": len(vr), "last_daily": vr[-1] if vr else None,
                       "studio": _read(ms.latest_studio, studio, vid)})
    return {"channel": cid, "first_days": first_days,
            "collected": first_days in ms.WINDOW_DAYS, "window_days": list(ms.WINDOW_DAYS),
            "last_run": runs[-1] if runs else None, "videos": videos}


def video(root, channel, video_id):
    """One video's rows as stored: daily, windows, Studio reads."""
    cid = _channel(root, channel)
    ms, st = _ms(), _store(root)
    daily = ms.video_rows(_read(ms.read_daily, cid, st), video_id)
    windows = [r for r in _read(ms.read_windows, cid, st) if r["video_id"] == video_id]
    studio = [r for r in _read(ms.read_studio, cid, st) if r["video_id"] == video_id]
    if not (daily or windows or studio):
        raise BatchFault(404, "unknown_video",
                         f"У ролика {video_id} канала {cid} нет ни одной строки аналитики.",
                         [f"{ANALYTICS_DIR}/{cid}/: no daily, window or Studio row of "
                          f"{video_id}"])
    return {"channel": cid, "video_id": video_id, "daily": daily, "windows": windows,
            "studio": studio}


# ---------------------------------------------------------------- the summary
def summary(root, channel, day=None, first_days=FIRST_DAYS_DEFAULT):
    """`summary.build` for the day - what `summary.py daily` writes, nothing written."""
    cid = _channel(root, channel)
    su, me, ms = factory.analyst_summary(), factory.analyst_metrics(), _ms()
    jr, acc = factory.collect().journal(), factory.collect().acceptance()
    d = _day(day) if day else me.default_day(FACTORY_KW.get("now"))
    st = _store(root)
    alog = _path(root, PUBLISH_DIR, ACCEPTANCE, code="acceptance_unreadable",
                 what="the acceptance record")
    try:
        rep = su.build(cid, d, first_days, journal=_journal(root), acceptance_log=alog,
                       store_root=st)
    except jr.JournalError as e:
        raise _fault("journal_unreadable", e) from e
    except acc.AcceptanceError as e:
        raise _fault("acceptance_unreadable", e) from e
    except (ValueError, OSError) as e:
        raise _fault("store_unreadable", e) from e
    days = _saved_days(st, cid)
    return dict(rep, saved_days=days, saved=rep["day"] in days)


def saved_summary(root, channel, day):
    """`analytics/<ch>/summary/<day>.json` as `summary.py daily` wrote it."""
    cid = _channel(root, channel)
    _day(day)
    p = _path(root, ANALYTICS_DIR, cid, SUMMARY_DIR, f"{day}.json", code="store_unreadable",
              what="the summary")
    if not p.is_file():
        raise BatchFault(404, "no_saved_summary",
                         f"Сводки канала {cid} за {day} нет - её пишет `summary.py daily`.",
                         [f"no {ANALYTICS_DIR}/{cid}/{SUMMARY_DIR}/{day}.json"])
    try:
        rep = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise _fault("store_unreadable", e) from e
    days = _saved_days(_store(root), cid)
    return dict(rep, saved_days=days, saved=True)


# ---------------------------------------------------------------- the footage wanted
def footage(root, channel, since=None, packed=False):
    """`footage_wanted.build` - the packed batches only when asked."""
    cid = _channel(root, channel)
    if since:
        _day(since, "since")
    fw = factory.footage_wanted()
    archive = FACTORY_KW.get("archive", fw.DEFAULT_ARCHIVE) if packed else None
    try:
        rep = fw.build(Path(root), cid, archive=archive, since=since)
    except (fw.WantedError, OSError, ValueError) as e:
        raise _fault("footage_unreadable", e) from e
    return dict(rep, packed_read=bool(packed), reasons_ru=_wanted_ru(fw, rep))


def _wanted_ru(fw, rep):
    """CC-0113: {code: Russian} of every reason the report names (`by_reason`,
    the rows' `reasons`) - the funnel's line (`funnel.reason_ru`, CF-0714)
    for a funnel code, else footage_wanted's own `REASONS` (its codes of the
    Editor and the frame judge: anchor_short, frame_foreign, ...); null for a
    code neither knows."""
    codes = list((rep.get("by_reason") or {}) if isinstance(rep.get("by_reason"), dict) else ())
    for r in rep.get("rows") or []:
        if isinstance(r, dict) and isinstance(r.get("reasons"), dict):
            codes += [c for c in r["reasons"] if c not in codes]
    own = getattr(fw, "REASONS", None) or {}
    return {c: factory.reason_ru(c) or own.get(c) for c in codes if isinstance(c, str) and c}


# ---------------------------------------------------------------- Studio
def studio(root, channel):
    """`studio_read.py plan` / `due` and the stored reads."""
    cid = _channel(root, channel)
    sr, ms, st = factory.studio_read(), _ms(), _store(root)
    jr = factory.collect().journal()
    now = FACTORY_KW.get("now")
    settings = err = due = None
    last, n = [], None
    try:
        settings = sr.studio_settings(cid, root)
    except sr.ReadError as e:
        err = str(e)
    if settings is not None:
        try:
            vids, n = sr.last_videos(cid, root, now)
            is_due, line = sr.due(cid, root, now)
        except ms.StoreError as e:
            raise _fault("store_unreadable", e) from e
        except (jr.JournalError, ValueError) as e:
            raise _fault("journal_unreadable", e) from e
        due = {"due": bool(is_due), "line": line}
        last = [{"video_id": r["video_id"], "slug": r.get("slug"), "entry_id": r.get("entry_id"),
                 "published": factory.utc_iso(r["_published"].timestamp()),
                 "studio_url": sr.STUDIO_VIDEO_URL.format(id=r["video_id"])} for r in vids]
    reads = _read(ms.read_studio, cid, st)
    latest = [_read(ms.latest_studio, reads, vid) for vid in sorted({r["video_id"] for r in reads})]
    return {"channel": cid, "no_pipeline": sr.no_pipeline(cid, root), "settings": settings,
            "settings_error": err, "last_videos": last, "n": n, "due": due,
            "last_visit": _read(ms.last_visit, cid, st),
            "latest_reads": latest}


# ---------------------------------------------------------------- the feed's diversity (CC-0108)
DIVERSITY_LAST = 10                  # = publish_profile.DEFAULT_LAST


def diversity(root, last=DIVERSITY_LAST, channel=None):
    """`runlog diversity --last N [--channel C] --json` - publish_profile.diversity
    over the acceptance log, as its `main` reads it; `last` 0 - the whole feed.
    CC-0119 (CF-0719): `channel` - only that channel's rows, before the last N
    are taken (the factory's `channel_rows`: a former id resolved, a rebuilds
    row the one channel on file's); a channel the factory has no config of is
    404 `unknown_channel` in Russian before anything is read; the answer's
    `channel` is today's id, null for the whole feed."""
    cid = _channel(root, channel) if channel else None
    pp = factory.publish_profile()
    log = _path(root, PUBLISH_DIR, ACCEPTANCE, code="acceptance_unreadable",
                what="the acceptance log")
    # CF-0719: a log that is there but broken is `PublishProfileError` (it used
    # to read as None); the answer stays an empty feed with `log_read` false, as
    # before, and `log_error` says which file and why - no absolute path
    log_error = None
    try:
        raw = pp._load(log)
    except pp.PublishProfileError as e:
        raw, log_error = None, f"{PUBLISH_DIR}/{ACCEPTANCE}: {e.reason}"
    doc = raw or {}
    try:
        d = pp.diversity([r for r in doc.get("acceptances") or [] if isinstance(r, dict)],
                         last=last, root=Path(root), channel=cid)
    except (OSError, ValueError) as e:
        raise _fault("acceptance_unreadable", e) from e
    labels = dict(pp.AXES)
    return {"last": last, "channel": d.get("channel"), "n": d["n"], "videos": d["videos"], "read_live": d["read_live"],
            "axes": [{"key": k, "label": labels[k],
                      "values": [{"value": v, "count": c, "share": sh}
                                 for v, c, sh in d["axes"][k]]} for k, _ in pp.AXES],
            "lines": pp.render_diversity(d),
            "log": f"{PUBLISH_DIR}/{ACCEPTANCE}", "log_exists": log.is_file(),
            "log_read": raw is not None, "log_error": log_error}
