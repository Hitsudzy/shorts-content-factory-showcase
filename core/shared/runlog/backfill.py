#!/usr/bin/env python3
"""CF-0111: backfill - a hand-written RUN_LOG.txt of a run made before the
accounting existed (2026-08-31T2155Z, 2026-09-03T2037Z) becomes a synthetic
RUN_EVENTS.jsonl, so that `runlog summary` and the runs table can hold the
run as a "before" baseline. Every event carries `source: "manual-runlog"` and
`precision: "minute"`; the row is marked `accounting: manual-runlog` with the
note "ручной лог, низкая точность".

    runlog backfill <batch-dir> [--out DIR] [--root DIR] [--transcripts DIR]
                    [--session ID]... [--tz utc|msk] [--tz-first utc|msk]
                    [--no-usage] [--no-table] [--stdout]

    backfill.parse(text)                 -> the log lines as records (local times)
    backfill.events(batch_dir, ...)      -> the synthetic events (nothing written)
    backfill.run(batch_dir, out=..., ...) -> writes RUN_EVENTS.jsonl + gaps + usage
                                            + RUN_SUMMARY.md into `out`, appends the row

Nothing is written into the batch directory itself: `--out` (default
<root>/pipeline/backfill/<batch-id>/) receives the synthetic events, the gap
and usage events and RUN_SUMMARY.md. The real batch is read only
(RUN_LOG.txt, 05-video-editor.json, 01-trend-hunter.json).

The two hand-written formats (both are accepted, line by line):

    [YYYY-MM-DD HH:MM:SS] BATCH_START <batch-id> channel=<ch> — <text>   (09-03 only)
    [YYYY-MM-DD HH:MM:SS] STAGE_START <name> [<text>]
    [YYYY-MM-DD HH:MM:SS] STAGE_DONE  <name> [<text>]
    [YYYY-MM-DD HH:MM:SS] BATCH_DONE  <batch-id> <text>                  (09-03 only)
    anything else (blank lines, the "=== FINAL SUMMARY ===" prose of 08-31)  ignored

`<name>` is a top-level stage (trend-hunter, compliance-1/-2 -> compliance-
checker, footage-indexer, footage-indexer-descriptions, content-researcher,
video-editor, metadata-assembly ...) or a per-video line:

    video<N>-<slug>-<step>[-attempt<K>]          08-31: video2-rapid-reckless-render-attempt2
    video-<slug>-<step>[-attempt<K>]             09-03: video-clooney-venice-lion-qc-attempt3
    video-<slug>                                 09-03: the video-level START/DONE line

The step is the longest known suffix (tts+align, tts, align, resolve-anchors
-> resolve, render-plan[+soundtrack] -> plan, degrade-to-stills -> plan,
render[-stills] -> render, qc[-stills] -> qc, metadata); a `-stills` variant
is the next attempt of its step; text starting with FAILED / KILLED makes
the event `failed`.

Time zones: the batch id (<YYYY-MM-DD>T<HHMM>Z) is the run's creation time in
UTC. The first line and the rest of the file are tested separately against
it: a line is read as MSK (UTC+3) or UTC, whichever puts it after the batch
id by the smaller margin. That is what the logs do - 09-03 wrote its
BATCH_START in MSK and everything else in UTC, 08-31 is MSK throughout - and
--tz / --tz-first override the detection.

What the events can and cannot say (the row's precision is a minute, and the
log saw only what the operator wrote down):

  * STAGE_START/STAGE_DONE pairs become stage markers; a top-level DONE
    without its START gets a start at the previous line (`synthesized`).
    A missing BATCH_START / BATCH_DONE is synthesized at the first / last line.
  * a per-video START..DONE pair becomes one script start + done with the
    same id - and, like a real script, hides a silence inside it from the
    gap detector (08-31 says itself that a 1h05m limit outage sits inside
    video2's resolve-anchors attempt 2; the events cannot show it).
  * a per-video DONE without a START becomes a single done event whose
    duration is inferred from the previous line of the same video (the
    video-level START counts), capped at INFER_CAP_S: a longer silence
    before it is left as a silence (a gap), the event is an instant.
  * the video-level START/DONE lines are `marker` events with status
    `note` - activity for the gap detector, nothing for the stage windows.
  * machine time inside a stage (the indexer's ~34 min of 3h19m on 09-03)
    is invisible: the log has no script events, only the two markers.
  * 05-video-editor.json supplies the video count, each video's duration,
    degradations and QC verdict (as `note` events); a video that has no
    line in the log at all gets one script event at batch-done so that it
    is counted.
"""
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["SOURCE", "PRECISION", "ROW_NOTE", "INFER_CAP_S", "parse", "detect_offset", "canonical_slug",
           "events", "session_transcripts", "manual_gaps", "run", "main"]

SOURCE = "manual-runlog"
PRECISION = "minute"
ROW_NOTE = "ручной лог, низкая точность"
INFER_CAP_S = 3600.0          # an inferred step start further back than this is not believed
MSK = 3                       # hours east of UTC
TZ = {"utc": 0, "msk": MSK}
OUT_DIR = "pipeline/backfill"

LINE_RE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\]\s+(BATCH_START|BATCH_DONE|STAGE_START|STAGE_DONE)\s+(\S+)\s*(.*)$")
BATCH_ID_RE = re.compile(r"(\d{4}-\d\d-\d\d)T(\d\d)(\d\d)Z")
ATTEMPT_RE = re.compile(r"-attempt(\d+)$")
VIDEO_RE = re.compile(r"^video\d*-(.+)$")
FAILED_RE = re.compile(r"^\s*(FAILED|KILLED)\b")
VERSION_RE = re.compile(r"\((\d+\.\d+)\b")

STAGE_MAP = {"compliance-1": "compliance-checker", "compliance-2": "compliance-checker"}
# suffix -> (step, stills-variant)
STEPS = (("tts+align", "tts+align", False), ("tts", "tts", False), ("align", "align", False),
         ("resolve-anchors", "resolve", False),
         ("render-plan+soundtrack", "plan", False), ("render-plan", "plan", False),
         ("degrade-to-stills", "plan", True),
         ("render-stills", "render", True), ("render", "render", False),
         ("qc-stills", "qc", True), ("qc", "qc", False),
         ("metadata", "metadata", False))
VIDEO_EDITOR = "video-editor"


# --------------------------------------------------------------------------
# parsing
# --------------------------------------------------------------------------

def parse(text):
    """The log lines as records: {lineno, local (naive datetime), kind, name, text}.
    Lines that are not `[ts] TOKEN name ...` are skipped."""
    out = []
    for n, line in enumerate(text.splitlines(), 1):
        m = LINE_RE.match(line)
        if not m:
            continue
        local = datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S")
        out.append({"lineno": n, "local": local, "kind": m.group(2), "name": m.group(3),
                    "text": m.group(4).strip()})
    return out


def batch_time(batch_id):
    """The UTC creation time encoded in a batch id, or None."""
    m = BATCH_ID_RE.search(batch_id or "")
    if not m:
        return None
    return datetime.strptime(f"{m.group(1)} {m.group(2)}:{m.group(3)}", "%Y-%m-%d %H:%M")


def detect_offset(local, batch_dt, tolerance_s=600):
    """Hours (0 or MSK) to subtract from `local` so that it lands after `batch_dt`
    by the smallest margin (a tolerance before it is allowed). None when neither
    interpretation lands after the batch id."""
    best = None
    for h in (0, MSK):
        delta = ((local - timedelta(hours=h)) - batch_dt).total_seconds()
        if delta < -tolerance_s:
            continue
        if best is None or delta < best[1]:
            best = (h, delta)
    return best[0] if best else None


def _tzname(h):
    return "MSK" if h == MSK else "UTC"


def _split_video(name):
    """video<N>-<slug>-<step>[-attempt<K>] -> (slug, step, attempt, stills) ;
    video-<slug> -> (slug, None, None, False); a top-level name -> None."""
    if name == VIDEO_EDITOR:
        return None
    m = VIDEO_RE.match(name)
    if not m:
        return None
    rest = m.group(1)
    attempt = None
    am = ATTEMPT_RE.search(rest)
    if am:
        attempt = int(am.group(1))
        rest = rest[:am.start()]
    for suffix, step, stills in STEPS:
        if rest.endswith("-" + suffix):
            return rest[:-len(suffix) - 1], step, attempt, stills
    return rest, None, attempt, False


def _id(batch_id, lineno, tag=""):
    return hashlib.sha1(f"{batch_id}:{lineno}:{tag}".encode()).hexdigest()[:12]


def _z(dt):
    return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _video_meta(batch_dir):
    """[{slug, script_id, duration_s, style, degradations, qc_passed}] from 05-video-editor.json."""
    out = []
    for m in runlog.editor_videos(batch_dir):      # CF-0176: one reader of 05-video-editor.json
        e = m["entry"]
        d = e.get("duration") or {}
        out.append({"slug": m["slug"], "script_id": m["script_id"],
                    "duration_s": d.get("actual") if isinstance(d, dict) else d,
                    "style": e.get("style_delivered"),
                    "degradations": len(e.get("degradation") or []),
                    "qc_passed": m["qc_passed"]})
    return out


def canonical_slug(slug, meta):
    """The output slug of 05-video-editor.json for a slug written in the log:
    the same, or the one meta slug it is a prefix of (08-31 wrote `wren-hollow`
    for wren-hollow-lockhart, `rapid-reckless` for rapid-reckless-neon-drift).
    Unknown slugs stay as written."""
    names = [v["slug"] for v in meta if v.get("slug")]
    if slug in names:
        return slug
    hits = [n for n in names if n.startswith(slug + "-") or slug.startswith(n + "-")]
    return hits[0] if len(hits) == 1 else slug


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------

def events(batch_dir, text=None, tz=None, tz_first=None, machine=None, sessions=None):
    """The synthetic events of the batch (a list of dicts, nothing written).
    tz / tz_first: "utc" | "msk" to override the detection for the rest of the
    file / its first line; sessions: transcript session ids, recorded in the header."""
    bd = Path(batch_dir)
    batch_id, channel = bd.name, bd.parent.name
    if text is None:
        text = (bd / runlog.RUNLOG_FILE).read_text(encoding="utf-8", errors="replace")
    recs = parse(text)
    if not recs:
        raise runlog.RunlogError(f"{bd / runlog.RUNLOG_FILE}: no `[ts] STAGE_START|STAGE_DONE|BATCH_START|BATCH_DONE` line")
    bt = batch_time(batch_id)
    first, rest = recs[0], recs[1:] if recs[0]["kind"] == "BATCH_START" else recs

    def offset(which, sample):
        if which is not None:
            return TZ[which]
        if bt is None:
            raise runlog.RunlogError(f"{batch_id}: not a <date>T<hhmm>Z batch id - pass --tz / --tz-first")
        h = detect_offset(sample["local"], bt)
        if h is None:
            raise runlog.RunlogError(f"line {sample['lineno']}: {sample['local']} is before the batch id {bt} "
                                     f"as UTC and as MSK - pass --tz / --tz-first")
        return h

    h_rest = offset(tz, rest[0] if rest else first)
    h_first = offset(tz_first, first) if first["kind"] == "BATCH_START" else h_rest
    for r in recs:
        h = h_first if r is first and first["kind"] == "BATCH_START" else h_rest
        r["t"] = r["local"] - timedelta(hours=h)
        r["tz"] = _tzname(h)
    machine = machine or runlog.machine_id()

    def ev(r, kind, stage, status=None, video=None, step=None, attempt=None, duration_s=None,
           eid=None, note=None, **extra):
        e = {"ts": _z(r["t"]), "machine": machine, "kind": kind, "stage": stage, "video": video,
             "step": step, "attempt": attempt, "status": status, "params": None,
             "duration_s": duration_s, "pid": 0, "id": eid or _id(batch_id, r["lineno"], kind + str(status)),
             "parent": None, "source": SOURCE, "precision": PRECISION, "line": r["lineno"]}
        if note:
            e["note"] = note[:runlog.PARAM_STR_MAX * 2]
        for k, v in extra.items():
            if v is not None:
                e[k] = v
        return e

    meta = _video_meta(bd)
    counts = runlog._counts(bd)
    if meta:
        counts["videos"] = len(meta)
    version = None
    if first["kind"] == "BATCH_START":
        m = VERSION_RE.search(first["text"])
        version = m.group(1) if m else None
    header = {
        "batch": f"{channel}/{batch_id}", "git": None, "version": version,
        "markup": runlog.MARKUP_LEGACY,          # CF-0173: a hand-written log predates the markers

        "models": {"operator": None, "subagent_default": None, "subagents": None},
        "counts": counts, "machine": None,
        "source": SOURCE, "precision": PRECISION, "log": str(bd / runlog.RUNLOG_FILE),
        "timezones": {"first_line": first["tz"], "rest": rest[0]["tz"] if rest else first["tz"]},
        "sessions": sorted(s for s in (sessions or []) if s),
        "row_note": ROW_NOTE,
        "note": f"{ROW_NOTE}: события восстановлены из RUN_LOG.txt (CF-0111)",
    }
    out = []
    if first["kind"] == "BATCH_START":
        out.append(ev(first, runlog.KIND_MARKER, None, runlog.M_BATCH_START, header=header, note=first["text"]))
    else:
        out.append(ev(first, runlog.KIND_MARKER, None, runlog.M_BATCH_START, header=header,
                      eid=_id(batch_id, 0, "batch-start"), synthesized="no BATCH_START line: the first line's time"))
    open_stages = {}           # stage -> record of its START
    pending = {}               # video -> (record, step) of a per-video START not yet closed
    last_seen = {}             # video -> record of the last line of that video
    attempts = {}              # (video, step) -> max attempt so far
    videos_in_log = set()
    stage_of_video = VIDEO_EDITOR
    batch_done = None
    last = first
    for r in rest:
        last = r
        kind, name = r["kind"], r["name"]
        if kind == "BATCH_START":
            out.append(ev(r, runlog.KIND_MARKER, None, "note", note=f"second BATCH_START line: {r['text']}"))
            continue
        if kind == "BATCH_DONE":
            batch_done = r
            continue
        pv = _split_video(name)
        if pv is None:                                        # top-level stage
            stage = STAGE_MAP.get(name, name)
            if kind == "STAGE_START":
                open_stages[stage] = r
                out.append(ev(r, runlog.KIND_MARKER, stage, runlog.M_STAGE_START, note=r["text"] or None,
                              log_name=name if name != stage else None))
            else:
                if stage not in open_stages:
                    prev = out[-1]
                    out.append(dict(ev(r, runlog.KIND_MARKER, stage, runlog.M_STAGE_START,
                                       eid=_id(batch_id, r["lineno"], "syn-start"),
                                       synthesized="STAGE_DONE without STAGE_START: started at the previous line"),
                                    ts=prev["ts"]))
                open_stages.pop(stage, None)
                out.append(ev(r, runlog.KIND_MARKER, stage, runlog.M_STAGE_DONE, note=r["text"] or None,
                              log_name=name if name != stage else None))
            continue
        slug, step, attempt, stills = pv
        slug = canonical_slug(slug, meta)
        videos_in_log.add(slug)
        if step is None:                                      # the video-level line
            out.append(ev(r, runlog.KIND_MARKER, stage_of_video, "note", video=slug,
                          note=f"{kind} {name} {r['text']}".strip(), log_name=name))
            last_seen[slug] = r
            continue
        if kind == "STAGE_START":
            pending[slug] = (r, step, attempt)
            last_seen[slug] = r
            continue
        # STAGE_DONE of a step
        key = (slug, step)
        if stills:
            attempt = attempts.get(key, 0) + 1
        elif attempt is None:
            attempt = 1
        attempts[key] = max(attempts.get(key, 0), attempt)
        status = runlog.ST_FAILED if FAILED_RE.match(r["text"]) else runlog.ST_DONE
        note = r["text"] or None
        eid = _id(batch_id, r["lineno"], "script")
        if slug in pending:
            start_rec, start_step, _ = pending.pop(slug)
            dur = (r["t"] - start_rec["t"]).total_seconds()
            out.append(ev(start_rec, runlog.KIND_SCRIPT, stage_of_video, runlog.ST_START, video=slug,
                          step=step, attempt=attempt, eid=eid, log_name=start_rec["name"],
                          start_from=None if start_step == step else f"START line of {start_step}"))
            out.append(ev(r, runlog.KIND_SCRIPT, stage_of_video, status, video=slug, step=step,
                          attempt=attempt, duration_s=round(dur, 1), eid=eid, note=note, log_name=name))
        else:
            prev = last_seen.get(slug)
            dur, how = None, "no previous line of this video: an instant"
            if prev is not None:
                d = (r["t"] - prev["t"]).total_seconds()
                if d <= INFER_CAP_S:
                    dur, how = round(d, 1), f"inferred from the previous line of the video (line {prev['lineno']})"
                else:
                    how = (f"previous line of the video is {runlog._hms(d)} back (line {prev['lineno']}), "
                           f"more than {runlog._hms(INFER_CAP_S)}: an instant")
            if dur:
                # a start at the previous line, so that the interval is busy for the gap detector
                out.append(dict(ev(prev, runlog.KIND_SCRIPT, stage_of_video, runlog.ST_START, video=slug,
                                   step=step, attempt=attempt, eid=eid, log_name=name, start_inferred=how),
                                ts=_z(prev["t"])))
            out.append(ev(r, runlog.KIND_SCRIPT, stage_of_video, status, video=slug, step=step,
                          attempt=attempt, duration_s=dur, eid=eid, note=note, log_name=name, start_inferred=how))
        last_seen[slug] = r
    # per-video STARTs never closed
    for slug, (start_rec, step, attempt) in pending.items():
        out.append(ev(start_rec, runlog.KIND_SCRIPT, stage_of_video, runlog.ST_START, video=slug, step=step,
                      attempt=attempt or 1, eid=_id(batch_id, start_rec["lineno"], "open"),
                      log_name=start_rec["name"], open="STAGE_START without STAGE_DONE"))
    end_rec = batch_done or last
    for stage, start_rec in open_stages.items():
        out.append(ev(end_rec, runlog.KIND_MARKER, stage, runlog.M_STAGE_DONE,
                      eid=_id(batch_id, start_rec["lineno"], "syn-done"),
                      synthesized="STAGE_START without STAGE_DONE: closed at the last line"))
    # videos the log never named: one event each so that they are counted
    for v in meta:
        if v["slug"] not in videos_in_log:
            out.append(ev(end_rec, runlog.KIND_SCRIPT, stage_of_video, runlog.ST_DONE, video=v["slug"],
                          step="render", attempt=1, eid=_id(batch_id, 0, "meta-" + v["slug"]),
                          note="from 05-video-editor.json only: no line in RUN_LOG.txt", start_inferred="none"))
    for v in meta:
        out.append(ev(end_rec, "note", stage_of_video, "video-meta", video=v["slug"],
                      eid=_id(batch_id, 0, "video-meta-" + v["slug"]),
                      params=v, note="05-video-editor.json"))
    if batch_done is not None:
        out.append(ev(batch_done, runlog.KIND_MARKER, None, runlog.M_BATCH_DONE, note=batch_done["text"] or None))
    else:
        out.append(ev(last, runlog.KIND_MARKER, None, runlog.M_BATCH_DONE, eid=_id(batch_id, 0, "batch-done"),
                      synthesized="no BATCH_DONE line: the last line's time"))
    order = {"batch-start": 0, "stage-start": 1, "start": 2, "done": 3, "failed": 3, "note": 3,
             "video-meta": 3, "stage-done": 4, "batch-done": 5}
    out.sort(key=lambda e: (e["ts"], order.get(e.get("status"), 3), e.get("line") or 0))
    return out


# --------------------------------------------------------------------------
# the whole backfill: events -> out dir -> gaps -> usage -> summary -> row
# --------------------------------------------------------------------------

def session_transcripts(sessions, transcripts=None):
    """The main transcript of every session id: <dir>/*/<id>.jsonl (the layout of
    ~/.claude/projects) or <dir>/<id>.jsonl (--transcripts pointing at one project
    dir, or a fixture). `transcripts` defaults to the usage module's directory
    ($RUNLOG_TRANSCRIPTS, $RUNLOG_PROJECTS_DIR, ~/.claude/projects)."""
    base = runlog.sibling("usage").transcripts_dir(transcripts)
    out = []
    for sid in sorted({s for s in sessions if s}):
        hits = sorted(base.glob(f"*/{sid}.jsonl")) + sorted(base.glob(f"{sid}.jsonl"))
        if not hits:
            runlog._warn(f"backfill: no transcript {sid}.jsonl under {base}")
        out.extend(hits)
    return out


def _pairs(evs):
    """(start_t, end_t, label) of every synthetic script START..DONE pair."""
    ts = {}
    out = []
    for e in evs:
        if e.get("kind") != runlog.KIND_SCRIPT or not e.get("id"):
            continue
        t = runlog.parse_z(e["ts"])
        if e.get("status") == runlog.ST_START:
            ts[e["id"]] = (t, e)
        elif e["id"] in ts:
            t0, e0 = ts.pop(e["id"])
            out.append((t0, t, f"{e.get('video')}/{e.get('step')} attempt {e.get('attempt')} "
                               f"START..DONE pair ({e0.get('log_name') or e0.get('id')})"))
    return out


def _stage_windows(evs):
    open_, out = {}, []
    for e in evs:
        if e.get("kind") != runlog.KIND_MARKER or not e.get("stage"):
            continue
        t = runlog.parse_z(e["ts"])
        if e.get("status") == runlog.M_STAGE_START:
            open_[e["stage"]] = t
        elif e.get("status") == runlog.M_STAGE_DONE and e["stage"] in open_:
            out.append((open_.pop(e["stage"]), t, e["stage"]))
    return out


def manual_gaps(evs, found, markers, min_gap_s=None):
    """The two rules a hand-written log needs on top of gaps.detect:

    1. a transcript resume-marker that no gap explains but that falls inside a
       per-video START..DONE pair longer than the gap threshold: the pair hid a
       limit outage (08-31: 1h05m inside video2's resolve-anchors attempt 2).
       The whole pair becomes a `limit` gap - the log does not say when the
       silence began, so the pair's own compute is counted into the gap too.
    2. a gap without evidence that lies inside one top-level stage window is
       tagged `inside_stage`: between STAGE_START and STAGE_DONE the log has
       no finer lines, so work and waiting look the same (08-31's indexer
       47m51s is fetch+index work by the log's own summary; 09-03's indexer
       3h19m holds a limit outage AND ~34 min of machine time, and only the
       transcript marker tells the two apart).

    Returns the gaps (found + rule 1), sorted."""
    gaps_mod = runlog.sibling("gaps")
    min_gap_s = gaps_mod.MIN_GAP_S if min_gap_s is None else min_gap_s
    found = [dict(g) for g in found]
    explained = {m["ts"] for g in found for m in (g.get("evidence") or {}).get("markers", [])}
    pairs = _pairs(evs)
    for m in markers:
        if m["ts"] in explained:
            continue
        for t0, t1, label in pairs:
            if t0 is not None and t1 is not None and t0 <= m["t"] <= t1 and t1 - t0 > min_gap_s:
                if any(g["start"] == gaps_mod._iso(t0) and g["end"] == gaps_mod._iso(t1) for g in found):
                    break
                found.append({
                    "start": gaps_mod._iso(t0), "end": gaps_mod._iso(t1), "seconds": round(t1 - t0, 1),
                    "cause": "limit",
                    "evidence": {"limit_hits": [], "markers": [
                        {"ts": m["ts"], "session_id": m["session_id"], "path": m["path"]}]},
                    "before": label, "after": label,
                    "inside_pair": label,
                    "note": "manual log: the resume marker falls inside a START..DONE pair; the pair's "
                            "own compute is inside this gap because the log has no line where the silence began",
                })
                explained.add(m["ts"])
                break
    windows = _stage_windows(evs)
    for g in found:
        ev = g.get("evidence") or {}
        if ev.get("markers") or ev.get("limit_hits") or g.get("inside_stage"):
            continue
        t0, t1 = gaps_mod._ts(g["start"]), gaps_mod._ts(g["end"])
        for w0, w1, stage in windows:
            if w0 <= t0 and t1 <= w1:
                g["inside_stage"] = stage
                g["note"] = ("manual log: silence between STAGE_START and STAGE_DONE of one stage - "
                             "no finer lines there, work and waiting look the same")
                break
    found.sort(key=lambda g: g["start"])
    return found


def run(batch_dir, out=None, root=None, transcripts=None, sessions=None, tz=None, tz_first=None,
        usage=True, table=True, machine=None):
    """Backfill one batch. Returns {out, events, gaps, markers, usage_rows, usage_info,
    summary, row, table_paths}."""
    bd = Path(batch_dir)
    r = Path(root) if root else runlog.factory_root()
    od = Path(out) if out else r / OUT_DIR / bd.name
    if od.resolve() == bd.resolve():
        raise runlog.RunlogError(f"--out must not be the batch directory itself ({bd})")
    sessions = [s for s in (sessions or []) if s]
    evs = events(bd, tz=tz, tz_first=tz_first, machine=machine, sessions=sessions)
    od.mkdir(parents=True, exist_ok=True)
    p = od / runlog.EVENTS_FILE
    p.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in evs), encoding="utf-8")
    gaps_mod = runlog.sibling("gaps")
    paths = session_transcripts(sessions, transcripts)
    markers = gaps_mod.transcript_markers(paths)
    found = gaps_mod.detect(events=evs, transcripts=paths, sessions=[], projects=Path("/nonexistent"))
    found = manual_gaps(evs, found, markers)
    gaps_mod.record(od, found)
    rows, info = [], None
    if usage and sessions:
        usage_mod = runlog.sibling("usage")
        rows, info = usage_mod.collect(od, transcripts=transcripts, sessions=sessions)
        if rows:
            usage_mod.write_usage_events(od, rows, window=info["window"])
    summary = runlog.sibling("summary")
    spath = summary.write(od)
    rt = runlog.sibling("runs_table")
    row = rt.row(od)
    paths_out = rt.append(row, r) if table else []
    return {"out": od, "events": evs, "gaps": found, "markers": markers, "usage_rows": rows,
            "usage_info": info, "summary": spath, "row": row, "table_paths": paths_out}


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog backfill",
                                 description="synthetic RUN_EVENTS.jsonl + summary + runs-table row from a "
                                             "hand-written RUN_LOG.txt (CF-0111)")
    ap.add_argument("batch", help="the batch directory with the hand-written RUN_LOG.txt (read only)")
    ap.add_argument("--out", default=None, help=f"where the synthetic events go (default <root>/{OUT_DIR}/<batch-id>/)")
    ap.add_argument("--root", default=None, help="factory root for the runs table (default FACTORY_ROOT or the repo)")
    ap.add_argument("--transcripts", default=None, help="transcripts dir for gaps and tokens (default ~/.claude/projects)")
    ap.add_argument("--session", action="append", default=[], help="session id whose transcript classifies the gaps and gives the tokens (repeatable)")
    ap.add_argument("--tz", choices=sorted(TZ), default=None, help="time zone of the log lines (default: detected from the batch id)")
    ap.add_argument("--tz-first", choices=sorted(TZ), default=None, help="time zone of the BATCH_START line (default: detected)")
    ap.add_argument("--no-usage", action="store_true", help="skip the tokens even when --session is given")
    ap.add_argument("--no-table", action="store_true", help="do not append the row to the runs table")
    ap.add_argument("--stdout", action="store_true", help="print the RUN_SUMMARY.md afterwards")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    bd = Path(ns.batch)
    if not (bd / runlog.RUNLOG_FILE).is_file():
        sys.stderr.write(f"runlog backfill: error: no {runlog.RUNLOG_FILE} in {bd}\n")
        return 2
    try:
        res = run(bd, out=ns.out, root=ns.root, transcripts=ns.transcripts, sessions=ns.session,
                  tz=ns.tz, tz_first=ns.tz_first, usage=not ns.no_usage, table=not ns.no_table)
    except runlog.RunlogError as e:
        sys.stderr.write(f"runlog backfill: error: {e}\n")
        return 2
    print(f"{len(res['events'])} events -> {res['out'] / runlog.EVENTS_FILE}")
    for g in res["gaps"]:
        print(runlog.sibling("gaps").format_gap(g))
    if res["usage_info"] is not None:
        print(f"{len(res['usage_rows'])} usage rows from {len(res['usage_info']['paths'])} transcripts "
              f"(sessions {', '.join(res['usage_info']['sessions']) or '-'})")
    elif ns.session:
        print("tokens skipped (--no-usage)")
    else:
        print("no --session: no transcript, tokens unknown")
    print(f"summary -> {res['summary']}")
    for p in res["table_paths"]:
        print(f"table -> {p}")
    if ns.stdout:
        sys.stdout.write(res["summary"].read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
