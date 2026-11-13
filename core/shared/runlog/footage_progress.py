#!/usr/bin/env python3
"""CF-0715: how far the Footage Indexer has got with each topic of a batch -
one reader for the command center, one small file the indexer writes as it goes.

Until this task the only live trace of footage collection was RUN_EVENTS: one
nested `footage-indexer/ingest` event per candidate video, the topic in its
`params`, and the outcome in the annotations of its end event. The center had
to rebuild "topic X has 1 of 2 sources, fetching its third candidate" from
that journal by itself. Now:

The progress file
-----------------
`<batch>/work/footage-progress.json` (`PROGRESS_REL`), written by
`ingest_batch.py` through `Tracker` while it walks - small, rewritten whole on
every change through a temporary file in the same directory and `os.replace`,
so a reader sees the previous version or the next one, never half of one.
Never appended, never edited in place:

    {
      "schema":       "footage-progress/1",
      "stage":        "footage-indexer",
      "batch":        "<batch directory name>",
      "started_at":   "<UTC Z>",          the Tracker's first write
      "updated_at":   "<UTC Z>",          the last write
      "finished":     false | true,       true once the 01b report settled it
      "needed":       2,                  canonical sources a topic is walking to
      "max_attempts": 4 | null,           CF-0129's cap per topic
      "floor":        N | null,           CF-0304's depth floor (usable shots)
      "error":        null | "<text>",    the run died before it settled
      "topics": [                         in Trend Hunter's order
        {"topic_id":     "...",
         "state":        "queued" | "collecting" | "collected" | "short"
                         | "refused" | "stopped",
         "collected":    n,               canonical sources held (aliases are not)
         "needed":       2,
         "attempts":     n,               distinct candidates spent (CF-0129)
         "last_video":   "<id>" | null,   the candidate the walk took last
         "usable_shots": n | null,        CF-0304 depth, once the report has it
         "floor":        n | null,
         "indexed_at":   "<UTC Z>" | null, the 01b `pool_depth.topics[]` row's
         "reason_code":  null | "<funnel code, as recorded>",
         "updated_at":   "<UTC Z>"}
      ]
    }

States: `queued` - not walked yet; `collecting` - the walk is on (or between
its passes); `collected` - holds `needed` canonical sources (`reason_code`
`pool_too_thin` when the pool stayed under the depth floor - a warning, the
topic goes on); `short` - under `needed` and kept anyway (`no_second_source`
in the warn mode, `kept_on_own_graphics`, CF-0689); `refused` - the stage
dropped it (`skipped_topics[]`: `reserve_unused`, `not_screened`,
`no_second_source`, `no_source`, ...); `stopped` - the run ended without
settling it (a crash, a kill).

The reader: `footage_progress(batch_dir)`
-----------------------------------------
Answers, in this order of sources:

  1. the progress file (`source: "file"`). If `01b-footage-index.json` is newer
     than the file - a reserve, supplement or sieve pass amended the report
     after the walk - the report's settlement is laid over it; if the file is
     not finished and RUN_EVENTS says the last `footage-indexer/ingest` run
     ended, its unsettled topics read `stopped`.
  2. RUN_EVENTS (`source: "events"`), for a batch written before this task or
     one whose file is missing or broken: per topic, the distinct candidates
     started (`attempts`), the ones whose end event is `done` with no failure
     annotation (`collected` - an upper bound until the report settles it: a
     re-upload deduplicated into an alias ends `done` too), the last event's
     time; Trend Hunter's topics with no event yet are `queued`. The run still
     open -> `collecting`, the run over and no report -> `stopped`. The report,
     when there is one, is laid over it. The events come through
     `event_log.load_events` (CF-0718) and are only read.
  3. the report alone (`source: "report"`) - an old batch with no journal.
  4. nothing (`source: "none"`, `topics: []`).

Every row of the answer carries `state_ru` and `reason` - the Russian line of
`reason_code` by `funnel.reason_ru` (CF-0714), None for a code outside the
vocabulary (a contract defect to show, not to translate) - and `reason_code`
as the funnel counts it (`funnel.canonical_code`).
"""
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

PROGRESS_REL = Path("work") / "footage-progress.json"
REPORT_FILE = "01b-footage-index.json"
TREND_FILE = "01-trend-hunter.json"
SCHEMA = "footage-progress/1"
STAGE = "footage-indexer"
STEP = "ingest"
# ingest_batch.SOURCES_WANTED - the default when nothing on disk names it.
DEFAULT_NEEDED = 2

QUEUED, COLLECTING, COLLECTED, SHORT, REFUSED, STOPPED = (
    "queued", "collecting", "collected", "short", "refused", "stopped")
STATES = (QUEUED, COLLECTING, COLLECTED, SHORT, REFUSED, STOPPED)
UNSETTLED = (QUEUED, COLLECTING)
STATE_RU = {
    QUEUED: "ждёт очереди",
    COLLECTING: "идёт сбор футажа",
    COLLECTED: "футаж собран",
    SHORT: "источников меньше нормы, тема оставлена",
    REFUSED: "тема выбыла на сборе футажа",
    STOPPED: "сбор прервался, тема не досчитана",
}
THIN_CODE = "pool_too_thin"
SHORT_CODE = "no_second_source"
OWN_GRAPHIC_KEPT = "kept_on_own_graphics"
OWN_GRAPHIC_KEY = "own_graphic_footing"
# The annotations `ingest_batch._attempt` puts on a per-source event whose
# candidate did not become a source.
FAIL_KEYS = ("fetch_failed", "too_long", "index_failed", "index_timeout",
             "wall_ceiling", "rights_exclusion", "licence_changed")

ROW_KEYS = ("topic_id", "state", "collected", "needed", "attempts", "last_video",
            "usable_shots", "floor", "indexed_at", "reason_code", "updated_at")


def progress_path(batch_dir):
    return Path(batch_dir) / PROGRESS_REL


def _now():
    return runlog.now_z()


def _mtime_z(path):
    try:
        return runlog.now_z(os.stat(path).st_mtime)
    except OSError:
        return None


def write_progress(batch_dir, doc):
    """`doc` to `<batch>/work/footage-progress.json`, whole or not at all: a
    temporary file beside it, then `os.replace`. Raises on a failed write."""
    dest = progress_path(batch_dir)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(f".{dest.name}.{os.getpid()}.{threading.get_ident()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=1)
        os.replace(tmp, dest)
    finally:
        if tmp.exists():
            tmp.unlink()
    return dest


def read_progress(batch_dir):
    """(doc, error): the progress file as written, (None, None) when there is
    none, (None, "<why>") when it does not read as a progress document."""
    path = progress_path(batch_dir)
    if not path.is_file():
        return None, None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"{PROGRESS_REL}: {type(e).__name__}: {e}"
    if not isinstance(doc, dict) or not isinstance(doc.get("topics"), list):
        return None, f"{PROGRESS_REL}: not a {SCHEMA} document"
    return doc, None


def _row(tid, needed, at=None, state=QUEUED):
    return {"topic_id": tid, "state": state, "collected": 0, "needed": needed,
            "attempts": 0, "last_video": None, "usable_shots": None, "floor": None,
            "indexed_at": None, "reason_code": None, "updated_at": at}


def _own_graphic_kept(report):
    """The topics the indexer kept on own graphics (CF-0689), from both places
    it writes them - as funnel._own_graphic_kept reads them."""
    out = set()
    block = report.get(OWN_GRAPHIC_KEY)
    for r in (block.get("kept") if isinstance(block, dict) else None) or []:
        if isinstance(r, dict) and r.get("topic_id"):
            out.add(r["topic_id"])
    floor = report.get("two_source_floor")
    for t in (floor.get(OWN_GRAPHIC_KEPT) if isinstance(floor, dict) else None) or []:
        if isinstance(t, str) and t:
            out.add(t)
    return out


def settle(rows, report, at=None):
    """Lay the 01b report's settlement over `rows` ({topic_id: row}, kept in
    order; topics the report names and `rows` lacks are appended). Returns the
    `needed` the report names (or None). Every topic the report names is
    settled; a topic it does not name keeps its row."""
    if not isinstance(report, dict):
        return None
    floor_block = report.get("two_source_floor")
    needed = floor_block.get("wanted") if isinstance(floor_block, dict) else None
    by_topic = report.get("sources_by_topic")
    by_topic = by_topic if isinstance(by_topic, dict) else {}
    depth = report.get("pool_depth")
    depth = depth if isinstance(depth, dict) else {}
    depth_rows = {r["topic_id"]: r for r in depth.get("topics") or []
                  if isinstance(r, dict) and r.get("topic_id")}
    thin = {t for t in depth.get("thin") or [] if isinstance(t, str)}
    skipped = {s["topic_id"]: s for s in report.get("skipped_topics") or []
               if isinstance(s, dict) and s.get("topic_id")}
    kept = _own_graphic_kept(report)

    def row_of(tid):
        if tid not in rows:
            rows[tid] = _row(tid, needed or DEFAULT_NEEDED)
        return rows[tid]

    for tid in list(by_topic) + [t for t in depth_rows if t not in by_topic]:
        r = row_of(tid)
        n = needed or r.get("needed") or DEFAULT_NEEDED
        vids = by_topic.get(tid)
        if isinstance(vids, list):
            r["collected"] = len(vids)
            if vids:
                r["last_video"] = r.get("last_video") or vids[-1]
        d = depth_rows.get(tid)
        if d:
            r["usable_shots"] = d.get("usable_shots")
            r["floor"] = d.get("floor")
            r["indexed_at"] = d.get("indexed_at")
            if isinstance(d.get("attempts"), int):
                r["attempts"] = d["attempts"]
        r["needed"] = n
        if r["collected"] >= n:
            r["state"] = COLLECTED
            r["reason_code"] = THIN_CODE if tid in thin else None
        else:
            r["state"] = SHORT
            r["reason_code"] = OWN_GRAPHIC_KEPT if tid in kept else SHORT_CODE
        r["updated_at"] = at
    for tid, s in skipped.items():
        r = row_of(tid)
        r["state"] = REFUSED
        r["reason_code"] = s.get("reason_code")
        r["updated_at"] = at
    return needed


class Tracker:
    """The writer the Footage Indexer holds while it walks. Every change
    rewrites the whole file (`write_progress`); a write that fails is said once
    on stderr and never stops the walk. Thread-safe: CF-0332's walks run in
    parallel threads."""

    def __init__(self, batch_dir, needed=DEFAULT_NEEDED, max_attempts=None,
                 floor=None, now=None):
        self.batch_dir = Path(batch_dir)
        self._now = now or _now
        self._lock = threading.Lock()
        self._rows = {}
        self._warned = False
        self.doc = {"schema": SCHEMA, "stage": STAGE, "batch": self.batch_dir.name,
                    "started_at": None, "updated_at": None, "finished": False,
                    "needed": needed, "max_attempts": max_attempts, "floor": floor,
                    "error": None, "topics": []}

    def _write(self):
        at = self._now()
        if self.doc["started_at"] is None:
            self.doc["started_at"] = at
        self.doc["updated_at"] = at
        self.doc["topics"] = [dict(r) for r in self._rows.values()]
        try:
            write_progress(self.batch_dir, self.doc)
        except Exception as e:      # progress never breaks a walk
            if not self._warned:
                self._warned = True
                sys.stderr.write(f"[footage-progress] not written ({type(e).__name__}: {e})\n")

    def _get(self, tid):
        if tid not in self._rows:
            self._rows[tid] = _row(tid, self.doc["needed"])
        return self._rows[tid]

    def start(self, topic_ids):
        """Every topic of the batch, queued, in order."""
        with self._lock:
            at = self._now()
            for tid in topic_ids:
                self._get(tid)["updated_at"] = at
            self._write()

    def skip(self, tid, reason_code):
        """The stage dropped this topic (a `skipped_topics[]` record)."""
        with self._lock:
            r = self._get(tid)
            r.update(state=REFUSED, reason_code=reason_code, updated_at=self._now())
            self._write()

    def walking(self, tid, collected, attempts, video=None):
        """The topic's walk is on: what it holds and has spent right now."""
        with self._lock:
            r = self._get(tid)
            r.update(state=COLLECTING, collected=int(collected or 0),
                     attempts=int(attempts or 0), updated_at=self._now())
            if video:
                r["last_video"] = video
            self._write()

    def settle(self, report):
        """The written 01b report decides every topic it names; the file is
        finished."""
        with self._lock:
            needed = settle(self._rows, report, self._now())
            if needed:
                self.doc["needed"] = needed
            self.doc["finished"] = True
            self._write()

    def fail(self, error):
        """The run is dying before it settled: its unsettled topics stop."""
        with self._lock:
            at = self._now()
            for r in self._rows.values():
                if r["state"] in UNSETTLED:
                    r.update(state=STOPPED, updated_at=at)
            self.doc["error"] = str(error)[:300]
            self._write()


def tracker(batch_dir, **kw):
    """A `Tracker`, or None when one cannot be made (the caller then walks
    without a progress file)."""
    try:
        return Tracker(batch_dir, **kw)
    except Exception:
        return None


# ------------------------------------------------------------------ the reader

def _ingest_events(events):
    return [e for e in events or ()
            if isinstance(e, dict) and e.get("stage") == STAGE
            and e.get("step") == STEP and e.get("kind", runlog.KIND_SCRIPT) == runlog.KIND_SCRIPT]


def _topic_of(e):
    p = e.get("params")
    return p.get("topic") if isinstance(p, dict) else None


def run_open(events):
    """Is the last top-level `footage-indexer/ingest` run still open? None when
    the journal holds no such run."""
    runs = {}
    order = []
    for e in _ingest_events(events):
        if e.get("video") is not None or _topic_of(e):
            continue
        rid = e.get("id")
        if e.get("status") == runlog.ST_START:
            runs[rid] = True
            order.append(rid)
        elif rid in runs:
            runs[rid] = False
    if not order:
        return None
    return runs[order[-1]]


def from_events(events, needed=DEFAULT_NEEDED, topic_ids=()):
    """{topic_id: row} rebuilt from the per-source ingest events (and
    `topic_ids` - Trend Hunter's - as queued). The state is `collecting` /
    `queued` while the run is open, `stopped` once it is over."""
    rows = {tid: _row(tid, needed) for tid in topic_ids}
    per = {}            # tid -> {video: {"open": bool, "ok": bool}}
    starts = {}         # event id -> (tid, video)
    for e in _ingest_events(events):
        tid, vid = _topic_of(e), e.get("video")
        if not tid or vid is None:
            continue
        r = rows.setdefault(tid, _row(tid, needed))
        r["updated_at"] = e.get("ts") or r["updated_at"]
        r["last_video"] = vid
        vids = per.setdefault(tid, {})
        if e.get("status") == runlog.ST_START:
            starts[e.get("id")] = (tid, vid)
            v = vids.setdefault(vid, {"open": False, "ok": False})
            v["open"] = True
        else:
            v = vids.setdefault(vid, {"open": False, "ok": False})
            v["open"] = False
            p = e.get("params") if isinstance(e.get("params"), dict) else {}
            if e.get("status") == runlog.ST_DONE and not any(p.get(k) for k in FAIL_KEYS):
                v["ok"] = True
    is_open = run_open(events)
    for tid, r in rows.items():
        vids = per.get(tid) or {}
        r["attempts"] = len(vids)
        r["collected"] = sum(1 for v in vids.values() if v["ok"])
        if is_open is None:
            running = any(v["open"] for v in vids.values())
        else:
            running = is_open
        if not running:
            r["state"] = STOPPED
        elif vids:
            r["state"] = COLLECTING
        else:
            r["state"] = QUEUED
    return rows


def _read_json(path):
    try:
        doc = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return doc if isinstance(doc, dict) else None


def _trend_topics(batch_dir):
    doc = _read_json(Path(batch_dir) / TREND_FILE)
    return [t["topic_id"] for t in (doc or {}).get("topics") or []
            if isinstance(t, dict) and isinstance(t.get("topic_id"), str)]


def _funnel():
    return runlog.sibling("funnel")


def _answer_row(r, funnel):
    out = {k: r.get(k) for k in ROW_KEYS}
    code = funnel.canonical_code(r.get("reason_code")) if r.get("reason_code") else None
    out["reason_code"] = code
    out["reason"] = funnel.reason_ru(code) if code else None
    out["state_ru"] = STATE_RU.get(out["state"])
    return out


def footage_progress(batch_dir, events=None):
    """Footage collection per topic for the batch at `batch_dir` - see the
    module docstring for the sources and the rules. `events` may be handed in
    (the batch's RUN_EVENTS, already loaded); otherwise they are read through
    `event_log.load_events` only when the answer needs them.

    -> {"batch_dir", "source": "file" | "events" | "report" | "none",
        "file": "work/footage-progress.json", "started_at", "updated_at",
        "finished", "running" (True / False / None - the last ingest run open,
        unknown), "needed", "topics": [row + state_ru, reason], "counts":
        {state: n}, "error": the progress file's problem or None}
    """
    bd = Path(batch_dir)
    funnel = _funnel()
    report_path = bd / REPORT_FILE
    report = _read_json(report_path) if report_path.is_file() else None
    report_at = _mtime_z(report_path) if report is not None else None
    doc, error = read_progress(bd)
    loaded = []

    def evs():
        if not loaded:
            loaded.append(list(events) if events is not None
                          else runlog.sibling("event_log").load_events(bd))
        return loaded[0]

    out = {"batch_dir": str(bd), "source": "none", "file": str(PROGRESS_REL),
           "started_at": None, "updated_at": None, "finished": False,
           "running": None, "needed": DEFAULT_NEEDED, "topics": [], "counts": {},
           "error": error}
    if doc is not None:
        rows = {r["topic_id"]: dict(r) for r in doc["topics"]
                if isinstance(r, dict) and r.get("topic_id")}
        needed = doc.get("needed") or DEFAULT_NEEDED
        finished = bool(doc.get("finished"))
        file_mtime = os.stat(progress_path(bd)).st_mtime
        out.update(source="file", started_at=doc.get("started_at"),
                   updated_at=doc.get("updated_at"))
        if report is not None and (not finished
                                   or os.stat(report_path).st_mtime > file_mtime):
            needed = settle(rows, report, report_at) or needed
            finished = True
        if finished:
            out["running"] = False
        else:
            is_open = run_open(evs())
            out["running"] = is_open
            if is_open is False:
                for r in rows.values():
                    if r["state"] in UNSETTLED:
                        r["state"] = STOPPED
        if report is not None and report_at and (out["updated_at"] or "") < report_at:
            out["updated_at"] = report_at
    else:
        ev = evs()
        if _ingest_events(ev):
            rows = from_events(ev, DEFAULT_NEEDED, _trend_topics(bd))
            out["source"] = "events"
            out["running"] = run_open(ev)
            stamps = [e.get("ts") for e in _ingest_events(ev) if e.get("ts")]
            out["started_at"] = stamps[0] if stamps else None
            out["updated_at"] = stamps[-1] if stamps else None
        elif report is not None:
            rows = {}
            out["source"] = "report"
            out["running"] = False
            out["updated_at"] = report_at
        else:
            return out
        needed = DEFAULT_NEEDED
        finished = False
        if report is not None:
            needed = settle(rows, report, report_at) or needed
            finished = True
            if report_at and (out["updated_at"] or "") < report_at:
                out["updated_at"] = report_at
    for r in rows.values():
        if not r.get("needed"):
            r["needed"] = needed
    topics = [_answer_row(r, funnel) for r in rows.values()]
    counts = {}
    for t in topics:
        counts[t["state"]] = counts.get(t["state"], 0) + 1
    out.update(finished=finished, needed=needed, topics=topics, counts=counts)
    return out


def main(argv=None):
    import argparse
    p = argparse.ArgumentParser(description="CF-0715: footage collection per topic of a batch")
    p.add_argument("batch_dir")
    a = p.parse_args(argv)
    print(json.dumps(footage_progress(a.batch_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
