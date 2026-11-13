#!/usr/bin/env python3
"""CF-0108: gap detector - silent intervals of a run and why they were silent.

A run has no human in it, so a stretch with no script, child, marker or
sample event for longer than 10 minutes is either the subscription limit or a
finding. detect() walks the activity events in time order and turns every
silence longer than min_gap_s that is not covered by a running script or
child (its start .. done|failed - the case with no sampler: backfilled runs,
fixtures) into

    {start, end, seconds, cause, evidence, before, after}

    cause     "limit"    a `limit-hit` event (limit_hook.py) falls inside the
                         gap (or up to 60 s before it), or a session transcript
                         has the resume marker line

                             I hit my usage limit while you were working, but it
                             has reset now. Please continue from where you left off.

                         inside the gap or within `slack_s` (600) after it - the
                         desktop app posts it when the session resumes, and a
                         hand-written RUN_LOG names the end a few minutes early;
              "idle_exit"
                         CF-0377: the last event before the silence is a sample
                         carrying `idle_exit: true` - CF-0339's sampler left a
                         run that had been idle for ten minutes, so this is the
                         run standing still (a wait for a human, a batch nobody
                         closed), not a machine that stopped;
              "<step>_timeout"
                         CF-0377: a `watchdog` block (CF-0316) sits on the event
                         that closes the silence (or opens it) - one operation
                         was taken down by its ceiling on silence (up to
                         SILENCE_CEILING_S = 1860 s, longer than MIN_GAP_S), and
                         the gap is named by the outcome code of the operation
                         that was lost;
              "unknown"  everything else - a finding, not a category to accept

    A named cause is read off the events on the gap's own **boundaries**, one
    probe per cause in NAMED_CAUSES; a fourth cause is added as one more entry
    there. None of this touches the arithmetic: the gap's time is still counted
    once and an overlapping WAITS line still says so - only the name changes.

    evidence  {limit_hits: [ts...], markers: [{ts, session_id, path}]}, plus
              `idle_exit: {ts, stage}` or `watchdog: {ts, side, code, stage,
              step, source, silent_s, ceiling_s}` for the named causes
    before    label of the last event before the silence ("trend-hunter stage-done")
    after     label of the first event after it

Transcripts: pass paths (`transcripts=`), or session ids (`sessions=`) that
are looked up as ~/.claude/projects/*/<session_id>.jsonl (RUNLOG_PROJECTS_DIR
overrides the directory), plus the session ids carried by the run's own
limit-hit events. Only a user message that *starts with* the marker text
counts: the same sentence also appears inside "This session is being
continued..." summaries, which are not resumptions.

`runlog render` prints one `GAP <start> <end> <dur> cause=...` line per gap;
`runlog gaps [--batch DIR] [--transcript F]... [--session ID]... [--json]
[--write]` prints them, and --write appends them as `kind: gap` events
(params = the record above; a gap already recorded with the same start/end is
not written twice).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["KIND_GAP", "MARKER_TEXT", "ACTIVITY_KINDS", "MIN_GAP_S", "detect", "record",
           "transcript_markers", "find_transcripts", "format_gap", "main",
           "CAUSE_UNKNOWN", "CAUSE_LIMIT", "CAUSE_IDLE_EXIT", "NAMED_CAUSES", "name_cause",
           "CAUSE_RESET", "name_resets", "reset_in"]

KIND_GAP = "gap"
KIND_LIMIT_HIT = "limit-hit"
MARKER_TEXT = ("I hit my usage limit while you were working, but it has reset now. "
               "Please continue from where you left off.")
ACTIVITY_KINDS = (runlog.KIND_SCRIPT, runlog.KIND_CHILD, runlog.KIND_MARKER, "sample")
MIN_GAP_S = 600
SLACK_BEFORE_S = 60
SLACK_AFTER_S = 600
PROJECTS_DIR_ENV = "RUNLOG_PROJECTS_DIR"
KIND_SAMPLE = "sample"
WATCHDOG_KEY = "watchdog"      # mirrors watchdog.WATCHDOG_KEY (CF-0316)
CAUSE_UNKNOWN = "unknown"
CAUSE_LIMIT = "limit"
CAUSE_IDLE_EXIT = "idle_exit"


def _ts(s):
    try:
        return runlog.parse_z(s)
    except Exception:
        return None


def _iso(t):
    return datetime.fromtimestamp(t, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


# --------------------------------------------------------------------------
# transcripts
# --------------------------------------------------------------------------

def _text(msg):
    if not isinstance(msg, dict):
        return ""
    c = msg.get("content")
    if isinstance(c, str):
        return c
    if isinstance(c, list):
        return " ".join(x.get("text", "") for x in c if isinstance(x, dict))
    return ""


def transcript_markers(paths):
    """[{ts, session_id, path}] for every resume-marker line in the given .jsonl files."""
    out = []
    for p in paths or []:
        p = Path(p).expanduser()
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    if MARKER_TEXT[:24] not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except ValueError:
                        continue
                    if d.get("type") not in (None, "user"):
                        continue
                    if not _text(d.get("message")).strip().startswith(MARKER_TEXT[:60]):
                        continue
                    t = _ts(d.get("timestamp"))
                    if t is None:
                        continue
                    out.append({"ts": d.get("timestamp"), "t": t,
                                "session_id": d.get("sessionId"), "path": str(p)})
        except OSError as e:
            runlog._warn(f"gaps: transcript unreadable {p} ({e})")
    return sorted(out, key=lambda m: m["t"])


def projects_dir():
    env = os.environ.get(PROJECTS_DIR_ENV)
    return Path(env).expanduser() if env else Path.home() / ".claude" / "projects"


def find_transcripts(session_ids, projects=None):
    """~/.claude/projects/*/<session_id>.jsonl for every id that has one."""
    base = Path(projects) if projects else projects_dir()
    hits = []
    for sid in sorted({s for s in session_ids if s}):
        try:
            hits.extend(sorted(base.glob(f"*/{sid}.jsonl")))
        except OSError:
            pass
    return hits


# --------------------------------------------------------------------------
# detection
# --------------------------------------------------------------------------

def _label(e):
    k, st = e.get("kind"), e.get("status")
    if k == runlog.KIND_MARKER:
        return f"{e.get('stage') or 'batch'} {st}"
    if k == "sample":
        return "sample"
    head = "/".join(x for x in (e.get("stage"), e.get("step") or e.get("tool")) if x)
    bits = [head or e.get("name") or k]
    if e.get("video"):
        bits.append(e["video"])
    if st:
        bits.append(st)
    return " ".join(bits)


# --------------------------------------------------------------------------
# CF-0377: causes that have a name on the gap's own boundaries
#
# A silence is not evidence by itself; the events that close it around are. Each
# probe below reads the last event before the gap and the first one after it and
# either names the cause or says nothing, and `name_cause` asks them in order.
# A new cause is one more probe in NAMED_CAUSES - the walk in detect() does not
# change, and neither does the arithmetic: only the name of the silence.
# --------------------------------------------------------------------------

def _cause_idle_exit(before, after):
    """CF-0339: a sampler that finds the run idle for ten minutes leaves, and
    says so on its last sample. The silence after it is the run standing still -
    waiting for a human, or a batch nobody closed - not a machine that stopped."""
    if before.get("kind") != KIND_SAMPLE:
        return None
    if (before.get("params") or {}).get("idle_exit") is not True:
        return None
    return CAUSE_IDLE_EXIT, {"idle_exit": {"ts": before.get("ts"),
                                           "stage": before.get("stage")}}


def _cause_watchdog(before, after):
    """CF-0316: one operation taken down by its ceiling on silence. The ceiling
    (1860 s by default) is longer than MIN_GAP_S, so the stretch the watchdog sat
    through is itself a gap; the kill rides on the event that ends it, and on the
    event that opens it when the silent operation is the next one. The gap takes
    the operation's own outcome code (`index_timeout`), never a bare "timeout":
    the triage is supposed to read which operation the run lost."""
    for e, side in ((after, "after"), (before, "before")):
        w = e.get(WATCHDOG_KEY)
        if not isinstance(w, dict) or not w:
            continue
        code = w.get("code") or e.get("rc") or "operation_timeout"
        return str(code), {"watchdog": {
            "ts": e.get("ts"), "side": side, "code": str(code),
            "stage": e.get("stage"), "step": e.get("step") or e.get("tool"),
            "source": w.get("source"), "silent_s": w.get("silent_s"),
            "ceiling_s": w.get("ceiling_s")}}
    return None


NAMED_CAUSES = (_cause_idle_exit, _cause_watchdog)

# CF-0739: a silence that holds a recorded reset of the batch's stages
# (run-state.json `manual_resets`, or a `control batch-rerun-from` event -
# runlog.manual_resets) is the batch stopped and resumed after the reset: a
# ruled stop, not the run standing still. It is named by the reset and wins
# over every other name; the arithmetic does not change.
CAUSE_RESET = "manual_reset"


def reset_in(t0, t1, resets):
    """The first recorded reset whose `at` falls inside [t0, t1], or None."""
    for r in resets or []:
        if t0 is not None and t1 is not None and t0 <= r["t"] <= t1:
            return r
    return None


def name_resets(gaps, resets):
    """Name every gap that holds a recorded reset `manual_reset`, with the
    reset in `evidence.reset`. In place; the gaps."""
    for g in gaps or []:
        t0 = g.get("_t0") if g.get("_t0") is not None else _ts(g.get("start"))
        t1 = g.get("_t1") if g.get("_t1") is not None else _ts(g.get("end"))
        r = reset_in(t0, t1, resets)
        if r is None:
            continue
        g["cause"] = CAUSE_RESET
        ev = g.get("evidence") if isinstance(g.get("evidence"), dict) else {}
        ev["reset"] = runlog.reset_brief(r)
        g["evidence"] = ev
    return gaps


def name_cause(before, after):
    """(cause, evidence) from the events on a gap's boundaries, or None when
    neither boundary says anything - the silence stays `unknown`."""
    for probe in NAMED_CAUSES:
        hit = probe(before or {}, after or {})
        if hit:
            return hit
    return None


def detect(batch_dir=None, transcripts=None, min_gap_s=MIN_GAP_S, events=None, sessions=None,
           slack_s=SLACK_AFTER_S, projects=None):
    """Gaps of the batch (see module docstring). events= skips reading the file;
    with batch_dir too, its run-state.json still names a reset's stop (CF-0739)."""
    ev = list(events) if events is not None else runlog.read_events(batch_dir)
    resets = runlog.manual_resets(batch_dir, ev)                # CF-0739
    timed = []
    for e in ev:
        t = _ts(e.get("ts"))
        if t is not None:
            timed.append((t, e))
    timed.sort(key=lambda x: x[0])
    activity = [(t, e) for t, e in timed if e.get("kind") in ACTIVITY_KINDS]
    if len(activity) < 2:
        return []
    # the run's own limit hits, and the sessions they name
    hits = [(t, e) for t, e in timed if e.get("kind") == KIND_LIMIT_HIT]
    sids = set(sessions or [])
    paths = [Path(p) for p in (transcripts or [])]
    for _, h in hits:
        p = (h.get("params") or {})
        if p.get("session_id"):
            sids.add(p["session_id"])
        if p.get("transcript_path") and Path(p["transcript_path"]).expanduser().is_file():
            paths.append(Path(p["transcript_path"]).expanduser())
    seen = {str(p.resolve()) for p in paths if p.exists()}
    for p in find_transcripts(sids, projects):
        if str(p.resolve()) not in seen:
            paths.append(p)
            seen.add(str(p.resolve()))
    markers = transcript_markers(paths)
    # bound the run: batch-start .. batch-done when present
    starts = [t for t, e in activity if e.get("kind") == runlog.KIND_MARKER
              and e.get("status") == runlog.M_BATCH_START]
    dones = [t for t, e in activity if e.get("kind") == runlog.KIND_MARKER
             and e.get("status") == runlog.M_BATCH_DONE]
    lo = starts[0] if starts else activity[0][0]
    hi = dones[-1] if dones else activity[-1][0]
    span = [(t, e) for t, e in activity if lo <= t <= hi]
    # a script/child between its start and its done|failed is busy, not silent
    # (matters when no sampler ran: backfilled runs, fixtures)
    open_at, busy = {}, []
    for t, e in span:
        if e.get("kind") in (runlog.KIND_SCRIPT, runlog.KIND_CHILD) and e.get("id"):
            if e.get("status") == runlog.ST_START:
                open_at[e["id"]] = t
            elif e["id"] in open_at:
                busy.append((open_at.pop(e["id"]), t))
    gaps = []
    for (t0, e0), (t1, e1) in zip(span, span[1:]):
        secs = t1 - t0
        if secs <= min_gap_s:
            continue
        if any(b0 <= t0 and t1 <= b1 for b0, b1 in busy):
            continue
        gaps.append({
            "start": _iso(t0), "end": _iso(t1), "seconds": round(secs, 1),
            "cause": CAUSE_UNKNOWN, "evidence": {"limit_hits": [], "markers": []},
            "before": _label(e0), "after": _label(e1), "_t0": t0, "_t1": t1,
            "_e0": e0, "_e1": e1,
        })
    # each hit / marker explains exactly one gap: a limit-hit the first gap that
    # holds it (or starts within SLACK_BEFORE_S after it), a resume marker the
    # first gap that holds it or ended at most slack_s before it
    for t, _ in hits:
        for g in gaps:
            if g["_t0"] - SLACK_BEFORE_S <= t <= g["_t1"]:
                g["evidence"]["limit_hits"].append(_iso(t))
                break
    for m in markers:
        for g in gaps:
            if g["_t0"] <= m["t"] <= g["_t1"] + slack_s:
                g["evidence"]["markers"].append(
                    {"ts": m["ts"], "session_id": m["session_id"], "path": m["path"]})
                break
    for g in gaps:
        ev = g["evidence"]
        if ev["limit_hits"] or ev["markers"]:
            g["cause"] = CAUSE_LIMIT
        else:                                    # CF-0377: ask the boundaries
            named = name_cause(g["_e0"], g["_e1"])
            if named:
                g["cause"], extra = named
                ev.update(extra)
    name_resets(gaps, resets)                                   # CF-0739
    for g in gaps:
        del g["_t0"], g["_t1"], g["_e0"], g["_e1"]
    return gaps


def format_gap(g):
    ev = g.get("evidence") or {}
    why = []
    if ev.get("limit_hits"):
        why.append(f"limit-hit={len(ev['limit_hits'])}")
    if ev.get("markers"):
        why.append("transcript-marker=" + ",".join(m["ts"] for m in ev["markers"]))
    if ev.get("idle_exit"):                      # CF-0377
        why.append("sampler left an idle run at " + str(ev["idle_exit"].get("ts")))
    if ev.get("watchdog"):                       # CF-0377
        w = ev["watchdog"]
        why.append(f"watchdog took down {w.get('stage') or '?'}/{w.get('step') or '?'}"
                   f" after {runlog._hms(w.get('silent_s') or 0)} of silence"
                   f" (ceiling {runlog._hms(w.get('ceiling_s') or 0)})")
    if ev.get("reset"):                          # CF-0739
        r = ev["reset"]
        why.append(f"recorded reset {r.get('at')} ({r.get('task') or 'no task'}, "
                   f"{r.get('by') or '?'}: {r.get('why') or 'no reason recorded'})")
    tail = f" ({'; '.join(why)})" if why else ""
    return (f"GAP {g['start']} {g['end']} {runlog._hms(g['seconds'])} cause={g['cause']}"
            f" after '{g.get('before')}' before '{g.get('after')}'{tail}")


def record(batch_dir, gaps):
    """Append `kind: gap` events for gaps not already recorded. Returns the new events."""
    have = {((e.get("params") or {}).get("start"), (e.get("params") or {}).get("end"))
            for e in runlog.read_events(batch_dir) if e.get("kind") == KIND_GAP}
    out = []
    for g in gaps:
        if (g["start"], g["end"]) in have:
            continue
        ev = runlog.emit(batch_dir, KIND_GAP, None, params=g)
        if ev:
            out.append(ev)
    return out


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog gaps")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--transcript", action="append", default=[], metavar="FILE")
    ap.add_argument("--session", action="append", default=[], metavar="ID")
    ap.add_argument("--min-gap", type=float, default=MIN_GAP_S, metavar="SECONDS")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write", action="store_true", help="append the gaps as kind=gap events")
    ns = ap.parse_args(argv)
    bdir = runlog.find_batch_dir(ns.batch)
    if bdir is None:
        sys.stderr.write("runlog gaps: error: no batch directory (use --batch DIR)\n")
        return 2
    gaps = detect(bdir, transcripts=ns.transcript, sessions=ns.session, min_gap_s=ns.min_gap)
    if ns.json:
        print(json.dumps(gaps, ensure_ascii=False, indent=2))
    else:
        for g in gaps:
            print(format_gap(g))
        if not gaps:
            print(f"no gaps longer than {runlog._hms(ns.min_gap)} in {bdir}")
    if ns.write and gaps:
        print(f"{len(record(bdir, gaps))} gap event(s) written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
