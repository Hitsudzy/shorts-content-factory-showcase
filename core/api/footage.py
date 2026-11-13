"""CC-0119: how far the Footage Indexer has got with each topic of a batch,
read only - the factory's `shared/runlog/footage_progress.footage_progress`
(CF-0715) through `api/factory.py`, nothing re-derived here.

**The sources** (the factory's order): `<batch>/work/footage-progress.json`
(`source: "file"`, written by footage-indexer 2.4+ while it walks), else the
batch's RUN_EVENTS.jsonl (`"events"` - a batch of FI v2.3.2 and older, which
writes no progress file), else `01b-footage-index.json` alone (`"report"`),
else nothing (`"none"`, `topics: []`). A progress file that does not parse is
`error` (the answer falls back to the journal), not a refusal.

**The cost**: the answer is kept per state of the files it is made of - the
progress file, the 01b report, RUN_EVENTS.jsonl (and Trend Hunter's 01, whose
topics are the `queued` rows of the journal's answer): their mtime and size.
An unchanged batch answers at once, `cached: true`; any of them touched -
computed afresh. A batch going changes with every event, so a reader polls it
no faster than `poll_s`.

**The rows** go out as the factory gives them, each value checked for its
type (a hand-edited file with a string where a count goes reads null, not a
500). Every string that may carry a path - `last_video`, `reason`, `error` -
is cut by `api/paths.clean` in the route; the factory's absolute `batch_dir`
does not leave (`batch` is «<channel>/<batch_id>»).

**Nothing here writes**: `write_progress`, `Tracker`, `tracker`, `main` are
never named - `tests/test_cc_api_footage.py` walks this file's names.
"""
import threading
from pathlib import Path

from . import factory
from .batches import batch_dir

#: The recommended poll interval of a batch going, seconds.
POLL_S = 5
_KEEP = 16
_KEPT = {}                    # str(batch dir) -> (state, answer)
_LOCK = threading.Lock()

ROW_STR = ("topic_id", "state", "state_ru", "last_video", "indexed_at", "reason_code",
           "reason", "updated_at")
ROW_INT = ("collected", "needed", "attempts")
ROW_NUM = ("usable_shots", "floor")
SOURCES = ("file", "events", "report", "none")


def _files(d):
    fp, rl = factory.footage_progress(), factory.runlog()
    return [d / fp.PROGRESS_REL, d / fp.REPORT_FILE, Path(rl.events_path(d)), d / fp.TREND_FILE]


def _state(d):
    out = []
    for p in _files(d):
        try:
            st = p.stat()
        except OSError:
            out.append((p.name, None, None))
            continue
        out.append((p.name, st.st_mtime_ns, st.st_size))
    return tuple(out)


def _str(v):
    return None if v is None else (v if isinstance(v, str) else str(v))


def _int(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return int(v) if float(v).is_integer() else None


def _num(v):
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    return v


def _row(r):
    out = {k: _str(r.get(k)) for k in ROW_STR}
    out.update({k: _int(r.get(k)) for k in ROW_INT})
    out.update({k: _num(r.get(k)) for k in ROW_NUM})
    out["topic_id"] = out["topic_id"] or ""
    out["state"] = out["state"] or ""
    # CC-0113: under the name every other code of the API uses - the
    # factory's own `reason` (footage_progress words it by funnel.reason_ru)
    out["reason_ru"] = out["reason"] if out["reason_code"] else None
    return out


def _answer(doc):
    running = doc.get("running")
    counts = doc.get("counts") if isinstance(doc.get("counts"), dict) else {}
    source = doc.get("source")
    return {"source": source if source in SOURCES else "none",
            "file": _str(doc.get("file")),
            "started_at": _str(doc.get("started_at")),
            "updated_at": _str(doc.get("updated_at")),
            "finished": bool(doc.get("finished")),
            "running": running if isinstance(running, bool) else None,
            "needed": _int(doc.get("needed")),
            "topics": [_row(r) for r in doc.get("topics") or () if isinstance(r, dict)],
            "counts": {str(k): v for k, v in counts.items() if _int(v) is not None},
            "error": _str(doc.get("error"))}


def _compute(d):
    try:
        return _answer(factory.footage_progress().footage_progress(d))
    except Exception as e:                                  # noqa: BLE001
        fp = factory.footage_progress()
        return {"source": "none", "file": str(fp.PROGRESS_REL), "started_at": None,
                "updated_at": None, "finished": False, "running": None, "needed": None,
                "topics": [], "counts": {},
                "error": f"сбор футажа не прочитался: {type(e).__name__}: {e}"}


def footage(root, channel, batch_id):
    d = batch_dir(root, channel, batch_id)
    with _LOCK:
        state = _state(d)
        kept = _KEPT.get(str(d))
        if kept and kept[0] == state:
            got, cached = kept[1], True
        else:
            got, cached = _compute(d), False
            _KEPT.pop(str(d), None)
            _KEPT[str(d)] = (state, got)
            while len(_KEPT) > _KEEP:
                _KEPT.pop(next(iter(_KEPT)))
    return {"batch": f"{channel}/{batch_id}", "channel": channel, "batch_id": batch_id,
            **got, "cached": cached, "poll_s": POLL_S}
