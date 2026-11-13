#!/usr/bin/env python3
"""CF-0109: tokens per stage x video x model x role, from the Claude Code
transcripts, by the run's time window - the third accounting layer.

No Anthropic API is called by the factory: every stage is a Claude Code
session (or a subagent of one) on the subscription, and the only record of
what it cost is the session transcript under ~/.claude/projects/<slug>/:

    <session-id>.jsonl                       the operator's own thread
    <session-id>/subagents/agent-<id>.jsonl  one file per subagent (Agent tool)
    <session-id>/subagents/agent-<id>.meta.json   {agentType, description, ...}

Every assistant record there carries `timestamp` (UTC Z), `sessionId`,
`message.id`, `message.model`, `message.usage` (`input_tokens`,
`cache_creation_input_tokens`, `cache_read_input_tokens`, `output_tokens`,
`output_tokens_details.thinking_tokens`) and, in a subagent file, `agentId`.
The run's sessions start from "/", so their slug is "-", but nothing here
depends on that: every slug is scanned, by the window.

Rules, as found in the real transcripts of the 2026-09-03 run:

  dedupe      one API call = one `message.id`, but the transcript writes one
              record per content block of the reply (thinking, text, each
              tool_use - `apiBlockIndex`), so an id appears 1..5 times. In the
              operator thread every copy carries the same final usage; in a
              subagent file the first copy (stop_reason null) is the streaming
              snapshot with output_tokens 5..7 and the later ones the final
              count - never a non-monotonic sequence. Rule: per id keep the
              record with the largest output_tokens (ties: the later one).
              `<synthetic>` model records (no API call behind them) are dropped.
  window      batch-start .. batch-done from the batch's own markers; a
              `slack` after batch-done (30 min by default) catches the
              operator's wrap-up and the last subagent finishing after the
              marker - those messages get stage "after". Messages inside the
              batch but outside every stage window get stage "between".
  stage       every message by its own timestamp against the stage-start ..
              stage-done windows - the operator's and a subagent's alike
              (CF-0168). A subagent is not a unit here: one that woke seconds
              before its stage-start, or kept working past stage-done, is split
              across the buckets its calls actually fall in, and `aggregate`
              then makes one row per bucket. So "between" means exactly "the
              call is outside every stage window", never "the group it belongs
              to began outside one" - and a between share that stays large is a
              statement about the markers (a stage marked late, a long stretch
              before the first stage-start), not about the arithmetic.
  video       from the script and child events that carry `video`, by the same
              rule one level down (CF-0174): the event is placed in the bucket
              its own timestamp falls in, and inside a bucket the slugs cut it
              into segments - a slug holds the floor from its first event until
              the first event of the next slug, the last one until the end of
              the stage. A message belongs to the segment that contains it - the
              operator's and a subagent's alike, by its own timestamp - and a
              subagent whose description names a slug belongs to it regardless
              of time. Not an envelope per slug: `min(ts) .. max(ts)` let one
              slug's late tail (a `qc` run two days after the batch, appended to
              the same events file) swallow a whole stage, and gave the earliest
              slug every call of a stage that had processed four videos.
  role        "operator" for the session's own thread, "subagent" for an
              agent-*.jsonl; `agent` is the Agent tool's description
              ("Video Editor: ink-teaser-cards") from the meta.json, or from
              the `toolUseResult.description` of the spawning record.
  sessions    every session with a message inside the window is a candidate;
              the run's own sessions are the ones named by the batch's
              `limit-hit` / `limits` events (session_id), or `--session`;
              with neither, all candidates count and the report lists them
              so the exclusion is a visible decision, not a silent one.

`usage` events (kind "usage", one per stage x video x model x role x agent):

    stage, video      as above ("between" / "after" are stages here)
    model             "claude-fable-5-1", ...
    role              "operator" | "subagent"
    agent             subagent description (subagent rows only; absent on operator rows)
    agent_ids         ["a093e657418e311ec", ...] (subagent rows only)
    session           session id (operator rows and subagent rows alike)
    usage             {input, cache_write, cache_read, output, thinking}
    calls             API calls (deduped message ids)
    minutes           span first .. last message of the row, minutes
    first, last       timestamps of the row's messages
    computed          when the rows were computed; all rows of one run of
                      usage_from_transcripts share the value
    window            {start, end, slack_s} the rows were computed for

Idempotence: RUN_EVENTS.jsonl stays append-only, so a re-run appends a new
generation of rows with a newer `computed`, and every reader (`read_usage`,
`usage_report.py`, `runlog render`) uses only the newest generation. Old
generations stay in the file as history and cost a few dozen lines.
A re-run that counts exactly the rows the newest generation already holds
appends nothing (CF-0334): one call's usage is in the file once, not once for
`batch-done` and once more for `runlog usage --write`. Files written before
that fix hold the same generation twice (runs of 2026-09-18 .. 09-22); every
reader here took the newest one, a naive sum over the file doubled.

Precision: this is the transcript's own count, so it is exact for what the
transcript recorded; what it cannot know is a call whose record never made it
to disk (killed session), a subagent whose file was written under another
session (never seen), or a stage boundary the operator marked late. Compare
against Anthropic's usage page, not against a scale.

CLI: scripts/usage_from_transcripts.py <batch-dir> [--transcripts DIR]
[--session ID]... [--slack MIN] [--write] [--json] and
scripts/usage_report.py <batch-dir> [--json] (events only, never transcripts).
"""
import glob
import json
import os
import re
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["KIND_USAGE", "KIND_USAGE_SCAN", "TRANSCRIPTS_ENV", "COUNTERS", "SLACK_S",
           "find_transcripts", "iter_messages", "load_messages", "dedupe", "windows",
           "attribute", "aggregate", "write_usage_events", "read_usage", "read_scan_error",
           "refresh", "stage_totals", "totals", "report", "run_sessions", "main", "report_main"]

KIND_USAGE = "usage"
KIND_USAGE_SCAN = "usage-scan"                  # CF-0172: only written when the scan failed
TRANSCRIPTS_ENV = "RUNLOG_TRANSCRIPTS"
PROJECTS_DIR_ENV = "RUNLOG_PROJECTS_DIR"        # shared with gaps.py
COUNTERS = ("input", "cache_write", "cache_read", "output", "thinking")
FRESH = ("input", "cache_write", "output")
SLACK_S = 30 * 60
ROLE_OPERATOR = "operator"
ROLE_SUBAGENT = "subagent"
ST_BETWEEN = "between"
ST_AFTER = "after"
SYNTHETIC = "<synthetic>"

_AGENT_FILE = re.compile(r"agent-([0-9a-f]+)\.jsonl$")


def _ts(s):
    try:
        return runlog.parse_z(s)
    except Exception:
        return None


def _iso(t):
    return runlog.now_z(t)


# --------------------------------------------------------------------------
# transcripts
# --------------------------------------------------------------------------

def transcripts_dir(override=None):
    """The directory to scan: the argument, $RUNLOG_TRANSCRIPTS, $RUNLOG_PROJECTS_DIR,
    ~/.claude/projects."""
    for cand in (override, os.environ.get(TRANSCRIPTS_ENV), os.environ.get(PROJECTS_DIR_ENV)):
        if cand:
            return Path(cand).expanduser()
    return Path.home() / ".claude" / "projects"


def find_transcripts(since=None, transcripts=None):
    """Every session and subagent transcript whose mtime is >= `since` (POSIX
    seconds; None = all). Both layouts are accepted: the real one
    (<dir>/<slug>/<session>.jsonl, <dir>/<slug>/<session>/subagents/agent-*.jsonl)
    and a flat one without the slug level (fixtures)."""
    base = transcripts_dir(transcripts)
    pats = ("*.jsonl", "*/*.jsonl", "*/subagents/*.jsonl", "*/*/subagents/*.jsonl")
    seen, out = set(), []
    for pat in pats:
        try:
            hits = base.glob(pat)
            for p in hits:
                if p in seen or not p.is_file():
                    continue
                seen.add(p)
                try:
                    if since is not None and p.stat().st_mtime < since:
                        continue
                except OSError:
                    continue
                out.append(p)
        except OSError:
            pass
    return sorted(out)


def _agent_meta(path):
    """(agent_id, agent_name, agent_type) for a subagent file, (None, None, None) otherwise."""
    m = _AGENT_FILE.search(str(path))
    if not m:
        return None, None, None
    aid, name, atype = m.group(1), None, None
    meta = Path(str(path)[: -len(".jsonl")] + ".meta.json")
    try:
        j = json.loads(meta.read_text(encoding="utf-8"))
        name = j.get("description") or None
        atype = j.get("agentType") or None
    except (OSError, ValueError):
        pass
    return aid, name, atype


def _int(v):
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def iter_messages(paths, names=None, since=None, until=None):
    """Yield one dict per usage-bearing record (not yet deduped):

        {ts, t, session_id, agent_id, agent_name, agent_type, model, message_id,
         role, usage: {input, cache_write, cache_read, output, thinking}, path}

    Malformed lines and records without message.usage are skipped. `names`
    (dict) collects agentId -> description from the spawning records'
    toolUseResult, for subagent files with no meta.json. since/until (POSIX)
    drop records outside the range early."""
    for path in paths:
        aid_file, aname, atype = _agent_meta(path)
        try:
            fh = open(path, encoding="utf-8", errors="replace")
        except OSError:
            continue
        with fh:
            for line in fh:
                if '"usage"' not in line and '"agentId"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(r, dict):
                    continue
                tur = r.get("toolUseResult")
                if names is not None and isinstance(tur, dict) and tur.get("agentId"):
                    names.setdefault(tur["agentId"], tur.get("description") or None)
                m = r.get("message")
                if not isinstance(m, dict) or not isinstance(m.get("usage"), dict):
                    continue
                t = _ts(r.get("timestamp") or "")
                if t is None:
                    continue
                if since is not None and t < since:
                    continue
                if until is not None and t > until:
                    continue
                u = m["usage"]
                model = m.get("model") or None
                if model == SYNTHETIC:
                    continue
                det = u.get("output_tokens_details")
                thinking = _int(det.get("thinking_tokens")) if isinstance(det, dict) else _int(u.get("thinking_tokens"))
                aid = r.get("agentId") or aid_file
                yield {
                    "ts": r.get("timestamp"),
                    "t": t,
                    "session_id": r.get("sessionId"),
                    "agent_id": aid,
                    "agent_name": aname if aid else None,
                    "agent_type": atype if aid else None,
                    "model": model,
                    "message_id": m.get("id") or r.get("uuid"),
                    "role": ROLE_SUBAGENT if aid else ROLE_OPERATOR,
                    "usage": {
                        "input": _int(u.get("input_tokens")),
                        "cache_write": _int(u.get("cache_creation_input_tokens")),
                        "cache_read": _int(u.get("cache_read_input_tokens")),
                        "output": _int(u.get("output_tokens")),
                        "thinking": thinking,
                    },
                    "path": str(path),
                }


def load_messages(paths, since=None, until=None):
    """iter_messages + names resolved from the spawning records, as a list."""
    names = {}
    msgs = list(iter_messages(paths, names=names, since=since, until=until))
    for m in msgs:
        if m["agent_id"] and not m["agent_name"]:
            m["agent_name"] = names.get(m["agent_id"])
    return msgs


def dedupe(messages):
    """One record per message id: the one with the largest output_tokens, the
    later one on ties (see the module docstring). Order of first appearance."""
    best, order = {}, []
    for m in messages:
        k = m.get("message_id")
        if k is None:
            order.append(m)
            continue
        cur = best.get(k)
        if cur is None:
            best[k] = m
            order.append(k)
        elif m["usage"]["output"] >= cur["usage"]["output"]:
            best[k] = m
    return [best[x] if isinstance(x, str) else x for x in order]


# --------------------------------------------------------------------------
# windows and attribution
# --------------------------------------------------------------------------

def windows(events):
    """Time windows of the batch from its events:

        {"batch": (start, end) | None,
         "stages": [{"stage", "start", "end"}],           in order, end None when open
         "videos": [{"stage", "video", "start", "end"}]}   segments, see below

    Times are POSIX floats. A stage-start without its stage-done ends at
    batch-done (or never).

    CF-0174: the video windows are *segments cut inside the stage buckets*, not
    one envelope per slug. Every script/child event that carries a video is put
    into the bucket its own timestamp falls in - the same bucket `attribute`
    will compute for a message at that moment ("after" past batch-done, the
    stage window that contains it, else "between") - and inside a bucket the
    events in slug order cut it into segments: a segment runs from its slug's
    first event to the next slug's first event, and the last one to the end of
    the bucket. So there is one entry per *stretch* of a slug, several per slug
    when the stage came back to it, and the entries never overlap.

    The envelope this replaces was `min(ts) .. max(ts)` per (stage, slug) over
    the whole file, and it collapsed the 2026-09-09 run: a `qc` run two days
    after the batch appended `bunker-venice-ovation` events to the same
    RUN_EVENTS.jsonl, the slug's envelope grew to 3511 minutes over a 37-minute
    stage, and since `_video_at` answers with the first window that contains the
    moment, that one slug took the whole `video-editor` stage (102 of 131 calls,
    20.27M of 23.9M tokens) while the three other videos of the stage got
    nothing."""
    batch_start = batch_end = None
    stages, open_ = [], {}
    marks = []
    for e in events:
        t = _ts(e.get("ts") or "")
        if t is None:
            continue
        k, st = e.get("kind"), e.get("status")
        if k == runlog.KIND_MARKER:
            if st == runlog.M_BATCH_START and batch_start is None:
                batch_start = t
            elif st == runlog.M_BATCH_DONE:
                batch_end = t
            elif st == runlog.M_STAGE_START and e.get("stage"):
                w = {"stage": e["stage"], "start": t, "end": None}
                stages.append(w)
                open_[e["stage"]] = w
            elif st == runlog.M_STAGE_DONE and e.get("stage") in open_:
                open_.pop(e["stage"])["end"] = t
        elif k in (runlog.KIND_SCRIPT, runlog.KIND_CHILD) and e.get("video"):
            marks.append((t, e["video"]))
    for w in stages:
        if w["end"] is None:
            w["end"] = batch_end
    batch = (batch_start, batch_end) if batch_start is not None else None
    return {"batch": batch, "stages": stages,
            "videos": _video_segments(marks, stages, batch_start, batch_end)}


def _bucket(t, stages, batch_end):
    """(bucket key, bucket stage name, bucket end) of a moment - the same bucket
    `attribute` gives a message at `t`. The key separates two windows of the same
    stage (footage-indexer twice in a run), the name is what goes on the row."""
    if batch_end is not None and t > batch_end:
        return (ST_AFTER, None), ST_AFTER, None
    for i, w in enumerate(stages):
        if w["start"] <= t and (w["end"] is None or t <= w["end"]):
            return (w["stage"], i), w["stage"], w["end"]
    return (ST_BETWEEN, None), ST_BETWEEN, None


def _video_segments(marks, stages, batch_start, batch_end):
    """Video-carrying events -> non-overlapping {stage, video, start, end}
    segments, see `windows`. Events before batch-start are dropped: no message
    is attributed there either."""
    by_bucket = {}
    for t, video in sorted(marks, key=lambda m: m[0]):
        if batch_start is not None and t < batch_start:
            continue
        key, stage, end = _bucket(t, stages, batch_end)
        b = by_bucket.setdefault(key, {"stage": stage, "end": end, "marks": []})
        b["marks"].append((t, video))
    out = []
    for b in by_bucket.values():
        segs = []
        for t, video in b["marks"]:
            if segs and segs[-1]["video"] == video:
                segs[-1]["end"] = t
            else:
                segs.append({"stage": b["stage"], "video": video, "start": t, "end": t})
        for i, s in enumerate(segs):
            if i + 1 < len(segs):
                s["end"] = segs[i + 1]["start"]          # the slug holds the floor until the next one
            elif b["end"] is not None:
                s["end"] = max(s["end"], b["end"])       # the last slug holds it to the end of the stage
        out += segs
    return sorted(out, key=lambda w: w["start"])


def _stage_at(t, stages):
    for w in stages:
        if w["start"] <= t and (w["end"] is None or t <= w["end"]):
            return w["stage"]
    return None


def _video_at(t, stage, videos):
    for w in videos:
        if w["stage"] == stage and w["start"] <= t <= w["end"]:
            return w["video"]
    return None


def attribute(messages, wins, slack_s=SLACK_S):
    """Set `stage` and `video` on every message and return the ones inside
    batch-start .. batch-done + slack. Without a batch window every message is
    kept and attributed against the stage windows only.

    Every message is placed by its own timestamp (CF-0168). A subagent used to
    inherit, for all of its calls, the bucket of its first one, so a group that
    woke a few seconds before its stage-start fell out of the stage whole - on
    the 2026-09-09 run that was 445 of 476 calls in "between". A group that
    straddles a boundary is now split across both buckets."""
    batch = wins.get("batch")
    stages, videos = wins.get("stages", []), wins.get("videos", [])
    t0 = batch[0] if batch else None
    t1 = (batch[1] + slack_s) if batch and batch[1] is not None else None
    slugs = {w["video"] for w in videos}
    out = []
    for m in messages:
        t = m["t"]
        if t0 is not None and t < t0:
            continue
        if t1 is not None and t > t1:
            continue
        if batch and batch[1] is not None and t > batch[1]:
            stage, video = ST_AFTER, None
        else:
            stage = _stage_at(t, stages) or ST_BETWEEN
            video = _video_at(t, stage, videos)
        if m.get("agent_id") and m.get("agent_name"):
            for s in slugs:
                if s and s in m["agent_name"]:
                    video = s
                    break
        m["stage"], m["video"] = stage, video
        out.append(m)
    return out


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def aggregate(messages):
    """Rows stage x video x model x role x agent (agent = subagent description,
    None for the operator), with the five counters, calls, minutes, first/last,
    session and agent_ids. Sorted by first message."""
    rows = {}
    for m in messages:
        key = (m.get("stage"), m.get("video"), m.get("model"), m.get("role"),
               m.get("agent_name") if m.get("role") == ROLE_SUBAGENT else None,
               m.get("session_id"))
        r = rows.get(key)
        if r is None:
            r = rows[key] = {
                "stage": key[0], "video": key[1], "model": key[2], "role": key[3],
                "agent": key[4], "session": key[5],
                "usage": {c: 0 for c in COUNTERS}, "calls": 0,
                "first": m["t"], "last": m["t"], "agent_ids": [],
            }
        for c in COUNTERS:
            r["usage"][c] += m["usage"].get(c, 0)
        r["calls"] += 1
        r["first"] = min(r["first"], m["t"])
        r["last"] = max(r["last"], m["t"])
        aid = m.get("agent_id")
        if aid and aid not in r["agent_ids"]:
            r["agent_ids"].append(aid)
    out = sorted(rows.values(), key=lambda r: (r["first"], r["role"], r["agent"] or ""))
    for r in out:
        r["minutes"] = round((r["last"] - r["first"]) / 60.0, 1)
        r["first"], r["last"] = _iso(r["first"]), _iso(r["last"])
    return out


def totals(rows):
    """{input, cache_write, cache_read, output, thinking, total, fresh, calls,
    cache_read_pct, fresh_pct} over the rows (total = in + cw + cr + out)."""
    t = {c: 0 for c in COUNTERS}
    calls = 0
    for r in rows:
        for c in COUNTERS:
            t[c] += r["usage"].get(c, 0)
        calls += r.get("calls", 0)
    total = t["input"] + t["cache_write"] + t["cache_read"] + t["output"]
    fresh = sum(t[c] for c in FRESH)
    t.update(total=total, fresh=fresh, calls=calls,
             cache_read_pct=round(100.0 * t["cache_read"] / total, 1) if total else 0.0,
             fresh_pct=round(100.0 * fresh / total, 1) if total else 0.0)
    return t


# --------------------------------------------------------------------------
# events
# --------------------------------------------------------------------------

_ROW_KEY = ("stage", "video", "model", "role", "agent", "session", "calls", "first", "last")


def _row_sig(r):
    """What makes two usage rows the same count of the same calls. `minutes` is
    derived from first/last, `agent_ids` from the transcripts the row came from;
    `computed`/`window.slack_s` are how it was counted, not what (CF-0334: the
    batch-done scan writes slack_s 1800, the CLI 1800.0 - same count)."""
    u = r.get("usage") or {}
    return (tuple(r.get(k) for k in _ROW_KEY)
            + tuple(_int(u.get(c)) for c in COUNTERS)
            + (tuple(sorted(r.get("agent_ids") or ())),))


def _generation_sig(rows):
    """The rows as a multiset - order-free, and None-safe (video/agent are None
    on some rows, so the tuples cannot be sorted)."""
    return Counter(_row_sig(r) for r in rows)


def write_usage_events(batch_dir, rows, window=None, computed=None, events=None):
    """Append one `usage` event per row; all share `computed` (a generation
    marker, see the docstring). Returns the written events.

    CF-0334: when the newest generation already in the file holds exactly these
    rows, nothing is appended and the existing generation is returned instead.
    Since 2026-09-18 every run counted its tokens twice - `batch-done` (CF-0172)
    and then the orchestrator's `runlog usage --session ID --write` a few seconds
    later - and the identical second generation doubled any count over the file
    that did not pick the newest generation. A re-count that comes out different
    (other sessions, other slack, transcripts grown) is still a new generation."""
    if events is None:
        events = runlog.read_events(batch_dir)
    newest = read_usage(events=events)
    if newest and rows and _generation_sig(newest) == _generation_sig(rows):
        return newest
    computed = computed or runlog.now_z()
    win = None
    if window and window.get("batch"):
        b = window["batch"]
        win = {"start": _iso(b[0]) if b[0] is not None else None,
               "end": _iso(b[1]) if b[1] is not None else None,
               "slack_s": window.get("slack_s", SLACK_S)}
    out = []
    for r in rows:
        ev = runlog.emit(batch_dir, KIND_USAGE, r["stage"], video=r.get("video"),
                         model=r.get("model"), role=r.get("role"), agent=r.get("agent"),
                         agent_ids=r.get("agent_ids") or None, session=r.get("session"),
                         usage=dict(r["usage"]), calls=r.get("calls", 0),
                         minutes=r.get("minutes", 0.0), first=r.get("first"), last=r.get("last"),
                         computed=computed, window=win)
        if ev is not None:
            out.append(ev)
    return out


def refresh(batch_dir, transcripts=None, sessions=None, slack_s=SLACK_S, events=None):
    """CF-0172: what `runlog usage <batch> --write` does, for `batch-done` to call
    before the summary is rendered - scan the transcripts of the batch's window and
    append one generation of `usage` events. Returns the written events.

    When the scan raises, one `usage-scan` event with status "error" is appended and
    the exception is re-raised - the caller decides whether it is fatal; for
    batch-done it is not. When it returns nothing to count (no transcripts, or none
    of them touched this batch's window) the event carries status "empty". Either
    way section 4 of RUN_SUMMARY.md quotes the reason instead of telling the reader
    to go and run the scan by hand.
    """
    where = str(transcripts_dir(transcripts))
    try:
        rows, info = collect(batch_dir, transcripts=transcripts, sessions=sessions,
                             slack_s=slack_s, events=events)
    except Exception as e:                              # noqa: BLE001 - recorded, then re-raised
        _scan_event(batch_dir, "error", f"failed ({e.__class__.__name__}: {e})"[:300], where)
        raise
    evs = write_usage_events(batch_dir, rows, window=info["window"]) if rows else []
    if not evs:                                         # nothing to show is also an answer
        _scan_event(batch_dir, "empty",
                    f"found no transcripts under {where}" if not info["paths"] else
                    f"found no calls of this batch's window in {len(info['paths'])} "
                    f"transcript(s) under {where}", where)
    return evs


def _scan_event(batch_dir, status, why, where):
    runlog.emit(batch_dir, KIND_USAGE_SCAN, None, status=status, error=why, transcripts=where)


def read_scan_error(batch_dir=None, events=None):
    """The newest `usage-scan` event of the batch (status "error" - the scan raised -
    or "empty" - it found nothing to count), or None - and None as soon
    as a usage generation newer than that failure exists (a later manual
    `runlog usage --write` answers the question the failure left open)."""
    if events is None:
        events = runlog.read_events(batch_dir)
    errs = [e for e in events if e.get("kind") == KIND_USAGE_SCAN and e.get("ts")]
    if not errs:
        return None
    err = max(errs, key=lambda e: e["ts"])
    newest_gen = max((e.get("computed") or "" for e in events if e.get("kind") == KIND_USAGE),
                     default="")
    return None if newest_gen > err["ts"] else err


def read_usage(batch_dir=None, events=None):
    """The newest generation of `usage` events of the batch (rows as written)."""
    if events is None:
        events = runlog.read_events(batch_dir)
    us = [e for e in events if e.get("kind") == KIND_USAGE]
    if not us:
        return []
    latest = max(e.get("computed") or "" for e in us)
    return [e for e in us if (e.get("computed") or "") == latest]


def stage_totals(events):
    """{stage: {input, cache_write, cache_read, output, thinking, calls}} from the
    newest usage generation - what `runlog render` prints on STAGE_DONE."""
    out = {}
    for e in read_usage(events=events):
        s = out.setdefault(e.get("stage"), dict({c: 0 for c in COUNTERS}, calls=0))
        for c in COUNTERS:
            s[c] += _int((e.get("usage") or {}).get(c))
        s["calls"] += _int(e.get("calls"))
    return out


def tokens_suffix(st):
    """' tokens=in/cw/cr/out calls=N' for a stage_totals entry, '' for None."""
    if not st:
        return ""
    return (f" tokens={st['input']}/{st['cache_write']}/{st['cache_read']}/{st['output']}"
            f" calls={st['calls']}")


# --------------------------------------------------------------------------
# sessions
# --------------------------------------------------------------------------

def run_sessions(events):
    """Session ids the batch's own events name (limit-hit / limits params)."""
    ids = set()
    for e in events:
        if e.get("kind") in ("limit-hit", "limits"):
            p = e.get("params") or {}
            sid = p.get("session_id") if isinstance(p, dict) else None
            if sid:
                ids.add(sid)
    return ids


# --------------------------------------------------------------------------
# report
# --------------------------------------------------------------------------

def _k(n):
    n = int(n or 0)
    if abs(n) >= 10_000_000:
        return f"{n / 1e6:.1f}M"
    if abs(n) >= 1_000_000:
        return f"{n / 1e6:.2f}M"
    if abs(n) >= 10_000:
        return f"{n / 1e3:.0f}k"
    return str(n)


def report(rows, window=None, sessions=None, excluded=None, title=None):
    """One-screen table: stage x model x role x agent (videos folded), a total
    line per stage and the grand total with fresh vs cache-read."""
    lines = []
    head = title or "USAGE"
    if window and window.get("batch"):
        b = window["batch"]
        head += (f"  window {_iso(b[0]) if b[0] is not None else '?'} .. "
                 f"{_iso(b[1]) if b[1] is not None else 'open'}")
        if window.get("slack_s"):
            head += f" (+{int(window['slack_s'] // 60)} min slack)"
    lines.append(head)
    if sessions:
        lines.append("sessions: " + ", ".join(sorted(sessions)))
    if excluded:
        lines.append("excluded: " + ", ".join(f"{k} ({_k(v)})" for k, v in sorted(excluded.items())))
    fmt = "{:<22} {:<18} {:<9} {:<34} {:>5} {:>7} {:>7} {:>7} {:>7} {:>6} {:>6}"
    lines.append(fmt.format("stage", "model", "role", "agent", "calls", "input", "cache_w",
                            "cache_r", "output", "think", "min"))
    # fold videos: key without video
    folded = {}
    for r in rows:
        key = (r["stage"], r["model"], r["role"], r.get("agent"))
        f = folded.get(key)
        if f is None:
            f = folded[key] = {"stage": key[0], "model": key[1], "role": key[2], "agent": key[3],
                               "usage": {c: 0 for c in COUNTERS}, "calls": 0,
                               "first": r["first"], "last": r["last"], "_order": len(folded)}
        for c in COUNTERS:
            f["usage"][c] += r["usage"].get(c, 0)
        f["calls"] += r.get("calls", 0)
        f["first"], f["last"] = min(f["first"], r["first"]), max(f["last"], r["last"])
    by_stage = {}
    for f in sorted(folded.values(), key=lambda f: f["_order"]):
        by_stage.setdefault(f["stage"], []).append(f)
    for stage, fs in by_stage.items():
        for i, f in enumerate(fs):
            mins = (_ts(f["last"]) - _ts(f["first"])) / 60.0
            u = f["usage"]
            lines.append(fmt.format(stage if i == 0 else "", (f["model"] or "?")[:18], f["role"],
                                    (f["agent"] or "-")[:34], f["calls"], _k(u["input"]),
                                    _k(u["cache_write"]), _k(u["cache_read"]), _k(u["output"]),
                                    _k(u["thinking"]), f"{mins:.0f}"))
        st = totals(fs)
        lines.append(fmt.format("", "", "", f"= {stage}", st["calls"], _k(st["input"]),
                                _k(st["cache_write"]), _k(st["cache_read"]), _k(st["output"]),
                                _k(st["thinking"]), ""))
    t = totals(rows)
    lines.append(f"TOTAL {_k(t['total'])} tokens, {t['calls']} calls: fresh {_k(t['fresh'])} "
                 f"({t['fresh_pct']}%) = input {_k(t['input'])} + cache_write {_k(t['cache_write'])} "
                 f"+ output {_k(t['output'])} (thinking {_k(t['thinking'])}); "
                 f"cache_read {_k(t['cache_read'])} ({t['cache_read_pct']}%)")
    for role in (ROLE_OPERATOR, ROLE_SUBAGENT):
        rt = totals([r for r in rows if r["role"] == role])
        if rt["total"]:
            lines.append(f"  {role}: {_k(rt['total'])} ({round(100.0 * rt['total'] / t['total'], 1)}%), "
                         f"fresh {_k(rt['fresh'])}, {rt['calls']} calls")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# the pipeline: batch dir -> rows
# --------------------------------------------------------------------------

def collect(batch_dir, transcripts=None, sessions=None, slack_s=SLACK_S, events=None):
    """Everything from the batch's window: returns (rows, info) where info has
    window, sessions (used), excluded {session: total}, paths (scanned)."""
    events = runlog.read_events(batch_dir) if events is None else events
    wins = windows(events)
    wins["slack_s"] = slack_s
    batch = wins["batch"]
    t0 = batch[0] if batch else None
    t1 = (batch[1] + slack_s) if batch and batch[1] is not None else None
    paths = find_transcripts(since=t0, transcripts=transcripts)
    msgs = dedupe(load_messages(paths, since=t0, until=t1))
    wanted = set(sessions or ()) or run_sessions(events)
    by_sess = {}
    for m in msgs:
        by_sess.setdefault(m.get("session_id"), []).append(m)
    if not wanted:
        wanted = set(by_sess)
    excluded = {}
    kept = []
    for sid, ms in by_sess.items():
        if sid in wanted:
            kept.extend(ms)
        else:
            excluded[sid] = totals(aggregate(attribute(ms, wins, slack_s)))["total"]
    excluded = {k: v for k, v in excluded.items() if v}
    rows = aggregate(attribute(kept, wins, slack_s))
    info = {"window": wins, "sessions": sorted(s for s in wanted if s in by_sess),
            "excluded": excluded, "paths": [str(p) for p in paths], "messages": len(kept)}
    return rows, info


def main(argv=None):
    """scripts/usage_from_transcripts.py"""
    import argparse
    ap = argparse.ArgumentParser(prog="usage_from_transcripts.py",
                                 description="tokens per stage x video x model x role from the "
                                             "Claude Code transcripts, by the batch's window (CF-0109)")
    ap.add_argument("batch", help="batch directory with RUN_EVENTS.jsonl")
    ap.add_argument("--transcripts", default=None, help=f"transcripts dir (default ${TRANSCRIPTS_ENV} or ~/.claude/projects)")
    ap.add_argument("--session", action="append", default=[], help="count only this session id (repeatable)")
    ap.add_argument("--slack", type=float, default=SLACK_S / 60, help="minutes after batch-done still counted as 'after' (30)")
    ap.add_argument("--write", action="store_true", help="append kind=usage events to RUN_EVENTS.jsonl and re-render RUN_LOG.txt")
    ap.add_argument("--json", action="store_true", help="print the rows as JSON instead of the table")
    ns = ap.parse_args(argv)
    bdir = Path(ns.batch)
    if not runlog.events_path(bdir).exists():
        sys.stderr.write(f"usage: no {runlog.EVENTS_FILE} in {bdir}\n")
        return 2
    t_start = time.time()
    rows, info = collect(bdir, transcripts=ns.transcripts, sessions=ns.session, slack_s=ns.slack * 60)
    if ns.json:
        print(json.dumps({"rows": rows, "sessions": info["sessions"], "excluded": info["excluded"],
                          "totals": totals(rows), "scanned": len(info["paths"])}, ensure_ascii=False, indent=1))
    else:
        sys.stdout.write(report(rows, info["window"], info["sessions"], info["excluded"],
                                title=f"USAGE {bdir.parent.name}/{bdir.name}"))
        sys.stdout.write(f"({len(info['paths'])} transcripts scanned, {info['messages']} calls kept, "
                         f"{time.time() - t_start:.1f}s)\n")
    if ns.write:
        t_write = runlog.now_z()
        evs = write_usage_events(bdir, rows, window=info["window"])
        if evs and all((e.get("computed") or "") < t_write for e in evs):
            print(f"unchanged: the newest usage generation ({evs[0].get('computed')}) already "
                  f"holds these {len(evs)} rows - nothing appended (CF-0334)")
        else:
            print(f"{len(evs)} usage events -> {runlog.events_path(bdir)}")
        try:
            print(f"rendered {runlog.write_runlog(bdir)}")
        except OSError as e:
            sys.stderr.write(f"usage: RUN_LOG.txt not rendered ({e})\n")
    return 0


def report_main(argv=None):
    """scripts/usage_report.py - events only (CF-0101 item 3)."""
    import argparse
    ap = argparse.ArgumentParser(prog="usage_report.py",
                                 description="stage x model x role x minutes from the batch's usage events")
    ap.add_argument("batch", help="batch directory with RUN_EVENTS.jsonl")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    bdir = Path(ns.batch)
    events = runlog.read_events(bdir)
    rows = read_usage(events=events)
    if not rows:
        sys.stderr.write(f"usage_report: no usage events in {runlog.events_path(bdir)} "
                         f"(run scripts/usage_from_transcripts.py {bdir} --write)\n")
        return 1
    if ns.json:
        print(json.dumps({"rows": rows, "totals": totals(rows)}, ensure_ascii=False, indent=1))
        return 0
    win = rows[0].get("window") or {}
    wins = {"batch": (_ts(win.get("start") or "") , _ts(win.get("end") or "")) if win.get("start") else None,
            "slack_s": win.get("slack_s")}
    sessions = {r.get("session") for r in rows if r.get("session")}
    sys.stdout.write(report(rows, wins, sessions, title=f"USAGE {bdir.parent.name}/{bdir.name} "
                                                       f"(events computed {rows[0].get('computed')})"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
