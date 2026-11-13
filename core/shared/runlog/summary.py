#!/usr/bin/env python3
"""CF-0110: RUN_SUMMARY.md - the run summary the user reads, from RUN_EVENTS.jsonl only.

Reads the events of one batch (never the transcripts, never the logs) and
answers the six questions of DoD 1.3.6 without any hand work:

    1. time by stage and by video, with the attempts per sub-step
       (resolve / plan / render / qc - and every other step that appears);
    2. time of the external binaries (ffmpeg, kokoro, whisper.cpp, yt-dlp,
       vision, ...) apart from the Python wrapper around them;
    3. gaps with their cause (limit / unknown) and their total - the FIRST
       LINE of the summary, before the heading - and beside them the waits for a
       human (CF-0252): the stretches between a `stage-done` and the next
       `stage-start` where nothing ran for longer than WAIT_MIN_S. The gap
       detector cannot see those (the sampler ticks through them), and without
       them a batch that stood still for four hours reads `GAPS: none`;
    4. tokens by stage x model x role (from the `usage` events of CF-0109);
    5. the share of the 5-hour and the 7-day window the run and each stage
       spent (from the `limits` events of CF-0108);
    6. CPU / memory / GPU by stage (from the `sample` events) with a verdict:
       hardware-bound / waiting / mixed;
    7. CF-0232, DoD 1.4.4 item 1: the topic funnel - selected -> after
       compliance -> with two sources -> scripts -> ready, a reason code on
       every loss, and no silent losses. The only section read from the batch's
       stage artifacts rather than from the events (shared/runlog/funnel.py);
       its one-line form sits at the top of the summary beside the GAPS line,
       because a batch that started from eight topics and ended on two has to
       say so where a reader looks first.

Plus live time vs wall time, and the unattributed time. CF-0257 cuts the wall
into six parts that never overlap - gaps, busy, waiting for a human, operator,
operator idle, unattributed - and `## Where the wall went` prints them adding
up to the wall. `unattributed` is the last of them: live time outside every
stage window and outside every named wait, which is the orchestrator session
between stages and is instrumented by nothing. When that is more than
INCOMPLETE_PCT (5 %) of the live time the run is flagged
`accounting: incomplete` and the intervals longer than UNATTRIBUTED_MIN_S
(60 s) are listed. The flag blocks nothing; it is there to be seen.

Definitions (all from the events):

    wall          batch-start .. batch-done (the last event when batch-done is missing)
    gaps          `gap` events (gaps.py); when the batch has none, gaps.detect()
                  runs on the events in memory (nothing is written)
    live          wall minus the gaps
    busy          union of the script and child intervals (start .. done|failed),
                  per stage clipped to the stage's own window, so busy <= wall
                  always (CF-0252). An interval whose done|failed never came is
                  of unknown length: it is counted only to the last event of its
                  own subtree (its binaries, their children) and named in
                  section 1, never stretched to the end of the batch - that
                  stretch is what put 9h15m56s of busy into a 2h54m41s stage and
                  9h15m56s of it onto one source clip on 2026-09-15
    wrapper       busy time of the scripts minus the union of the child intervals
                  - the Python around the binaries
    attempts      per (stage, video, step): the distinct `attempt` numbers of the
                  script events, or the number of `start` events when no script
                  carried an attempt number
    waits         silences of WAIT_MIN_S or more between a stage-done and the next
                  stage-start with no script and no binary inside - the batch
                  waiting for a human; a column of the stage table, not a stage's
                  busy time
    operator      CF-0257: what is left of a stage's own window after busy, gaps
                  and waits - the stage's LLM operator reading, thinking and
                  writing JSON between its script calls. A column of the stage
                  table beside `busy`, not part of it
    operator idle CF-0257: the part of that which is a silence of IDLE_MIN_S or
                  more with no script and no binary event in it - the operator
                  standing still, not working. Found by gaps.detect() over the
                  work events (every kind but `sample`), so a silence the usage
                  limit caused says so
    unattributed  CF-0257: live time outside every stage window and outside every
                  wait - the orchestrator session between stages, which writes no
                  event of its own. Markers are instants and cover nothing

Thresholds (constants below): a stage is `hardware-bound` when its mean
cpu_pipeline_pct (0..100 of all cores) is >= HW_BOUND_CPU_PCT (70) or its
mean GPU utilisation >= HW_BOUND_GPU_PCT (80); `waiting` when the pipeline
CPU is <= WAITING_PCT (20) and the GPU too (or unknown); `mixed` in between;
`no samples` when the sampler left nothing for the stage.

    summary.waits(batch_dir)       the waits for a human, as data (CF-0252)
    summary.operator(batch_dir)    the stage operators' own time and their idle
                                   stretches, as data (CF-0257)
    summary.consistency(batch_dir) the invariants of section 1: stage busy <= stage
                                   wall, per-video busy <= stage busy, batch busy
                                   <= wall (CF-0252)
    summary.compute(batch_dir)     every section as data (the runs table reads this)
    summary.render(batch_dir)      the Markdown text
    summary.write(batch_dir)       RUN_SUMMARY.md in the batch dir; runlog.marker("batch-done")
                                   calls it after stopping the sampler
    runlog summary [--batch DIR] [--stdout] [--json]

Stdlib only, like everything under shared/runlog/.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

_funnel = runlog.sibling("funnel")                   # CF-0232: section 7
_stopcock = runlog.sibling("stopcock")               # CF-0322: the line and the block of 7
_no_waiting = runlog.sibling("no_waiting")           # CF-0317: what each wait should have been instead
_watchdog = runlog.sibling("watchdog")                # CF-0316: operations taken down for silence
_scores = runlog.sibling("scores")                    # CF-0434: the score line of every video
_monitors = runlog.sibling("monitors")                # CF-0511: the live monitors of the close
_event_log = runlog.sibling("event_log")              # CF-0718: RUN_EVENTS read by the tail, cached
_memes = runlog.sibling("memes")                      # CF-0811: memes requested / placed

__all__ = ["SUMMARY_FILE", "SUB_STEPS", "HW_BOUND_CPU_PCT", "HW_BOUND_GPU_PCT", "WAITING_PCT",
           "UNATTRIBUTED_MIN_S", "INCOMPLETE_PCT", "WAIT_MIN_S", "IDLE_MIN_S", "ESTIMATE_CHAIN",
           "load", "stage_times", "binary_times", "gaps_summary", "gaps_line", "waits",
           "waits_line", "operator", "operator_line", "tokens",
           "window_share", "is_estimate", "resources", "unattributed", "consistency",
           "funnel_of", "stopcock_of", "no_waiting_of", "scores_of", "quota_line",
           "sieve_answers_line", "after_judge_line", "after_judge_decision",
           "compute", "render", "write", "main"]

SUMMARY_FILE = "RUN_SUMMARY.md"
SUB_STEPS = ("resolve", "plan", "render", "qc")      # the DoD's four; other steps are listed after them
HW_BOUND_CPU_PCT = 70.0     # mean cpu_pipeline_pct (0..100 of all cores) at or above -> hardware-bound
HW_BOUND_GPU_PCT = 80.0     # mean GPU util_pct at or above -> hardware-bound
WAITING_PCT = 20.0          # mean pipeline CPU (and GPU, when known) at or below -> waiting
UNATTRIBUTED_MIN_S = 60.0   # unattributed intervals shorter than this are summed, not listed
INCOMPLETE_PCT = 5.0        # unattributed > this % of live -> accounting: incomplete.
                            # CF-0257 kept the 5 % and changed what is measured. Under the old
                            # definition (live minus busy, gaps and waits) all seven batches of
                            # 2026-09-15..20 failed it at 13.9-94.9 %, and a flag no run can ever
                            # clear is read as noise. Under the new one - live *outside every stage
                            # window* and outside every named wait, i.e. the orchestrator's own
                            # moves between stages, which nothing instruments - the same seven come
                            # out 1.3 / 2.6 / 4.5 / 6.2 / 6.4 / 7.6 / 17.8 %: three clear the bar
                            # without anyone having tried, four do not, so 5 % discriminates
                            # instead of always firing. It is a share of live, so it is harder on a
                            # short batch (the residue is ~2-4 min per stage boundary however long
                            # the batch is): the two batches that ran the whole pipeline, 09-18T1058
                            # and 09-19T0116, are the two that pass with room to spare.
WAIT_MIN_S = 600.0          # CF-0252: silence between a stage-done and the next stage-start at or
                            # above this is the batch waiting for a human, not a stage running slowly
IDLE_MIN_S = 600.0          # CF-0257: silence *inside* a stage window with no script and no binary
                            # at or above this is the stage's operator standing still, not working.
                            # The 99.2nd percentile of the 861 in-stage pauses of the seven batches
                            # of 2026-09-15..20 (p90 52.6 s, p95 119.9 s, p99 578.1 s, max 3755.8 s)
                            # and the same number WAIT_MIN_S and gaps.MIN_GAP_S already use, so the
                            # rule reads as one rule: ten minutes of silence is never work.
ESTIMATE_CHAIN = 2          # CF-0175: a stage share from this many readings or fewer is an estimate

V_HW, V_WAIT, V_MIXED, V_NONE = "hardware-bound", "waiting", "mixed", "no samples"
ACC_OK, ACC_INCOMPLETE = "complete", "incomplete"


# --------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------

def _ts(s):
    try:
        return runlog.parse_z(s) if s else None
    except (ValueError, TypeError):
        return None


def _iso(t):
    return runlog.now_z(t) if t is not None else None


def _union(intervals):
    """Merged, sorted [(a, b)] of the given (a, b) pairs (a <= b)."""
    xs = sorted((a, b) for a, b in intervals if a is not None and b is not None and b >= a)
    out = []
    for a, b in xs:
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def _total(merged):
    return float(sum(b - a for a, b in merged))


def _clip(merged, lo, hi):
    return [(max(a, lo), min(b, hi)) for a, b in merged if b > lo and a < hi]


def _complement(merged, lo, hi):
    """Parts of [lo, hi] not covered by the merged intervals."""
    out, cur = [], lo
    for a, b in _clip(merged, lo, hi):
        if a > cur:
            out.append((cur, a))
        cur = max(cur, b)
    if hi > cur:
        out.append((cur, hi))
    return out


def _intersect(xs, ys):
    """Merged intersection of two interval lists (CF-0257)."""
    xs, ys, out, i, j = _union(xs), _union(ys), [], 0, 0
    while i < len(xs) and j < len(ys):
        lo, hi = max(xs[i][0], ys[j][0]), min(xs[i][1], ys[j][1])
        if hi > lo:
            out.append((lo, hi))
        if xs[i][1] < ys[j][1]:
            i += 1
        else:
            j += 1
    return out


def _subtract(xs, ys, lo, hi):
    """xs minus ys, inside [lo, hi] (CF-0257)."""
    if lo is None or hi is None or hi <= lo:
        return []
    return _intersect(_clip(_union(xs), lo, hi), _complement(_union(ys), lo, hi))


def _mean(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 1) if xs else None


def _max(xs):
    xs = [x for x in xs if x is not None]
    return round(max(xs), 1) if xs else None


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if whole else 0.0


def _hms(s):
    return runlog._hms(s) if s is not None else "?"


def _hm(t):
    """HH:MM (UTC) of a moment - what the wait marker of CF-0252 says."""
    iso = _iso(t)
    return iso[11:16] if iso else "??:??"


def _label(e):
    return runlog.sibling("gaps")._label(e)


# --------------------------------------------------------------------------
# load: events -> records
# --------------------------------------------------------------------------

def load(batch_dir=None, events=None):
    """Everything the sections need, from the events only:

        {"batch_dir", "events" (sorted by ts), "header", "markers", "intervals"
         (script + child records with start/end), "samples", "limits",
         "quota", "limit_hits", "gaps", "usage", "wall": (t0, t1), "stages": [...]}

    Gaps come from the `gap` events; when there are none, gaps.detect() runs on
    the events in memory (nothing is written)."""
    ev = list(events) if events is not None else _event_log.load_events(batch_dir)
    timed = [(t, e) for t, e in ((_ts(e.get("ts")), e) for e in ev) if t is not None]
    timed.sort(key=lambda x: x[0])
    ev = [e for _, e in timed]
    usage = runlog.sibling("usage")
    wins = usage.windows(ev)
    t_last = timed[-1][0] if timed else None
    batch = wins["batch"]
    t0 = batch[0] if batch else (timed[0][0] if timed else None)
    t1 = (batch[1] if batch and batch[1] is not None else None) or t_last
    header = None
    for e in ev:
        if e.get("kind") == runlog.KIND_MARKER and e.get("status") == runlog.M_BATCH_START:
            header = e.get("header")
            break
    # script / child intervals: start paired with done|failed by id
    open_, ivs = {}, []
    for t, e in timed:
        if e.get("kind") not in (runlog.KIND_SCRIPT, runlog.KIND_CHILD):
            continue
        st = e.get("status")
        rec = {"kind": e.get("kind"), "stage": e.get("stage"), "video": e.get("video"),
               "step": e.get("step"), "attempt": e.get("attempt"), "tool": e.get("tool"),
               "name": e.get("name"), "id": e.get("id"), "parent": e.get("parent"),
               "pid": e.get("pid"), "depth": e.get("depth"),
               "start": None, "end": None, "status": st, "duration_s": e.get("duration_s"),
               "open": False}
        if st == runlog.ST_START:
            rec["start"] = t
            if e.get("id"):
                open_[e["id"]] = rec
            ivs.append(rec)
        else:
            prev = open_.pop(e.get("id"), None)
            if prev is not None:
                prev["end"], prev["status"] = t, st
                prev["duration_s"] = e.get("duration_s") if e.get("duration_s") is not None else prev["duration_s"]
                # CF-0178: the slug and the attempt number of an interval are
                # whatever the *pair* knows, not what the `start` happened to
                # know. A script that resolves its own slug inside main() -
                # `runlog.annotate(**video_attempt(path))` - annotates after the
                # decorator has already written `start`, so the markup reaches
                # the terminal event only. Reading it off `start` alone lost all
                # 263 video-editor scripts of 2026-09-09 (CF-0177), and lost
                # them as a plausible zero in `att/video` rather than as a hole.
                # Only fields the terminal event *adds* are taken: a start that
                # already carries a slug keeps it, so a script that legitimately
                # changes hands mid-run is not rewritten by its last event.
                for f in ("video", "attempt"):
                    if prev[f] is None and e.get(f) is not None:
                        prev[f] = e.get(f)
            else:                                    # a done without its start
                d = float(e.get("duration_s") or 0.0)
                rec["start"], rec["end"] = t - d, t
                ivs.append(rec)
    # CF-0252: an interval whose terminal event never came is of *unknown*
    # length, and stretching it to the end of the batch is the double count the
    # 2026-09-15 run showed: `ingest_batch.py` for the first source of
    # footage-indexer lost its `done`, so section 1 read "9h15m56s busy" for a
    # source that took 136 s, the stage's busy (9h15m56s) came out larger than
    # the stage's own wall (2h54m41s), and the four hours the batch spent
    # waiting for a human were "covered by a script" in the accounting.
    # An open interval is now bounded by evidence only: it ends at the last
    # event of its own subtree (its children, their children) and never later
    # than the stage window it started in. The tail nobody recorded is not
    # counted - it is named instead (stage_times()["open"], section 1).
    last_of, kids = {}, {}
    for t, e in timed:
        i, par = e.get("id"), e.get("parent")
        if i:
            if last_of.get(i) is None or t > last_of[i]:
                last_of[i] = t
        elif par:                                    # an event parented to an interval, no id of its own
            if last_of.get(par) is None or t > last_of[par]:
                last_of[par] = t
        if i and par and i != par:
            kids.setdefault(par, set()).add(i)
    memo = {}
    raw_stages = [w for w in wins["stages"] if w.get("start") is not None]
    for rec in ivs:
        if rec["end"] is None:
            end = rec["start"]
            eend = _last_evidence(rec["id"], last_of, kids, memo) if rec["id"] else None
            if eend is not None and eend > end:
                end = eend
            cap = None
            for w in raw_stages:
                b = w["end"] if w["end"] is not None else t1
                if w["stage"] == rec["stage"] and w["start"] <= rec["start"] and (b is None or rec["start"] <= b):
                    cap = b
                    break
            if cap is None:
                cap = t1
            if cap is not None and rec["start"] <= cap < end:
                end = cap
            rec["end"] = end
            rec["open"] = True
            rec["status"] = "open" if rec["status"] == runlog.ST_START else rec["status"]
            rec["duration_s"] = round(end - rec["start"], 3)
        if rec["duration_s"] is None:
            rec["duration_s"] = round(rec["end"] - rec["start"], 3)
    # CF-0174: only what overlaps the batch's own wall. RUN_EVENTS.jsonl is
    # append-only and belongs to the batch dir, so a script run by hand over the
    # finished batch later (a `qc --summary` two days after 2026-09-09) writes
    # its events into the same file. Left in, such a tail is a script of the run
    # everywhere the sections read intervals: it put one video's wall at 58h31m
    # in section 1 and 92 ffmpeg calls that were never part of the batch in
    # section 2. Tokens drop the same tail by the same window (usage.attribute).
    if t0 is not None and t1 is not None:
        ivs = [r for r in ivs if r["start"] <= t1 and r["end"] >= t0]
    gaps_mod = runlog.sibling("gaps")
    # CF-0718: a copy - the gap is annotated below, and the event it came from
    # may be the shared, read-only one of event_log's cache.
    gap_events = [dict(e.get("params")) for e in ev if e.get("kind") == gaps_mod.KIND_GAP
                  and isinstance(e.get("params"), dict)]
    gaps = gap_events if gap_events else gaps_mod.detect(events=ev, transcripts=[], projects=Path("/nonexistent"))
    for g in gaps:
        g["_t0"], g["_t1"] = _ts(g.get("start")), _ts(g.get("end"))
    # CF-0739: the silence that holds a recorded reset of the batch's stages is
    # the reset's stop, named by it - also on a gap recorded before the reset
    # was read (a `gap` event of `runlog gaps --write`).
    resets = runlog.manual_resets(batch_dir, ev)
    gaps_mod.name_resets(gaps, resets)
    stages = [dict(w) for w in wins["stages"]]
    for w in stages:
        if w["end"] is None:
            w["end"] = t1
    return {
        "batch_dir": Path(batch_dir) if batch_dir else None,
        "events": ev,
        "header": header if isinstance(header, dict) else None,
        "markers": [e for e in ev if e.get("kind") == runlog.KIND_MARKER],
        "intervals": ivs,
        "samples": [e for e in ev if e.get("kind") == "sample"],
        "limits": [e for e in ev if e.get("kind") == "limits"],
        "quota": [e for e in ev if e.get("kind") == "quota"],   # CF-0368
        # CF-0374: the sieve's own sentence about this batch's flag answers.
        "sieve_answers": [e for e in ev if e.get("kind") == "sieve_answers"],
        "limit_hits": [e for e in ev if e.get("kind") == gaps_mod.KIND_LIMIT_HIT],
        "gaps": [g for g in gaps if g["_t0"] is not None and g["_t1"] is not None],
        "usage": usage.read_usage(events=ev),
        "usage_error": usage.read_scan_error(events=ev),   # CF-0172
        "wall": (t0, t1),
        "stages": stages,
        "resets": resets,                                       # CF-0739
        # CF-0899: the run's halts on `claude` not logged in (run-state.json)
        "login_halts": runlog.login_halts(batch_dir) if batch_dir else [],
        "videos": wins["videos"],
    }


def _last_evidence(i, last_of, kids, memo):
    """CF-0252: the last timestamp anywhere in the subtree of interval id `i` -
    its own events, its children's, theirs. None when `i` left no event at all."""
    if i in memo:
        return memo[i]
    memo[i] = last_of.get(i)                         # cycle guard
    best = last_of.get(i)
    for c in kids.get(i, ()):
        v = _last_evidence(c, last_of, kids, memo)
        if v is not None and (best is None or v > best):
            best = v
    memo[i] = best
    return best


def _loaded(x):
    return x if isinstance(x, dict) and "intervals" in x else load(events=x)


def _stage_at(t, stages):
    for w in stages:
        if w["start"] is not None and w["start"] <= t and (w["end"] is None or t <= w["end"]):
            return w["stage"]
    return None


def _gap_merged(d):
    return _union((g["_t0"], g["_t1"]) for g in d["gaps"])


# --------------------------------------------------------------------------
# 1. time by stage and by video, attempts per sub-step
# --------------------------------------------------------------------------

def _attempts(recs):
    """{step: {attempts, failed}} over script records: attempts are counted per
    (video, step) - distinct attempt numbers, or the starts when none is
    numbered - and summed over the videos the records span."""
    by = {}
    for r in recs:
        if r["kind"] != runlog.KIND_SCRIPT or not r["step"]:
            continue
        v = by.setdefault((r["video"], r["step"]), {"numbers": set(), "starts": 0, "failed": 0})
        if r["attempt"] is not None:
            v["numbers"].add(r["attempt"])
        v["starts"] += 1
        if r["status"] == runlog.ST_FAILED:
            v["failed"] += 1
    out = {}
    for (_, step), v in by.items():
        o = out.setdefault(step, {"attempts": 0, "failed": 0})
        o["attempts"] += len(v["numbers"]) if v["numbers"] else v["starts"]
        o["failed"] += v["failed"]
    return out


def _open_report(recs):
    """CF-0252: the intervals in `recs` that never got a done|failed event."""
    op = [r for r in recs if r.get("open")]
    op.sort(key=lambda r: -(r["end"] - r["start"]))
    return {
        "count": len(op),
        "scripts": sum(1 for r in op if r["kind"] == runlog.KIND_SCRIPT),
        "children": sum(1 for r in op if r["kind"] == runlog.KIND_CHILD),
        "evidence_s": round(_total(_union((r["start"], r["end"]) for r in op)), 1),
        "items": [{"stage": r["stage"], "video": r["video"], "step": r["step"],
                   "name": r["name"] or r["tool"], "kind": r["kind"],
                   "start": _iso(r["start"]), "last_evidence": _iso(r["end"]),
                   "seconds": round(r["end"] - r["start"], 1)} for r in op],
    }


def stage_times(x):
    """{"wall": {start, end, seconds}, "gaps_s", "live_s", "busy_s", "waits_s",
        "operator_s", "idle_s",
        "stages": [{stage, start, end, wall_s, busy_s, gaps_s, waits_s, operator_s,
                    idle_s, scripts,
                    children, videos, open, attempts {step: {attempts, failed}}}],
        "videos": [{stage, video, start, end, wall_s, busy_s, attempts {...},
                    attempts_total, failed}],
        "open": {count, scripts, children, evidence_s, items [...]}}

    CF-0252: a stage's busy is the union of its intervals *clipped to its own
    window*, and a video's busy the union of its intervals clipped to the
    windows of its stage - so `busy <= wall` holds by construction and
    `consistency()` has something to check. Before that clip an interval left
    open (no done|failed) ran to the end of the batch and one source of
    footage-indexer 2026-09-15 held 9h15m56s of a 2h54m41s stage.

    A video's `wall_s` stays the envelope of its own intervals (first start ..
    last end) and may therefore include a wait between two windows of the same
    stage; `busy_s` is the one the invariants are about."""
    d = _loaded(x)
    t0, t1 = d["wall"]
    gm = _gap_merged(d)
    wall_s = (t1 - t0) if t0 is not None and t1 is not None else 0.0
    gaps_s = _total(_clip(gm, t0, t1)) if wall_s else 0.0
    busy = _union((r["start"], r["end"]) for r in d["intervals"])
    wt = waits(d)
    op = operator(d)                                 # CF-0257
    stages, wins_by_stage = [], {}
    for w in d["stages"]:
        a, b = w["start"], w["end"] if w["end"] is not None else t1
        wins_by_stage.setdefault(w["stage"], []).append((a, b))
        recs = [r for r in d["intervals"] if r["stage"] == w["stage"] and a <= r["start"] <= b]
        sbusy = _clip(_union((r["start"], r["end"]) for r in recs), a, b)
        stages.append({
            "stage": w["stage"], "start": _iso(a), "end": _iso(b),
            "wall_s": round(b - a, 1), "busy_s": round(_total(sbusy), 1),
            "gaps_s": round(_total(_clip(gm, a, b)), 1),
            "operator_s": round(_total(_intersect(op["_work_iv"], [(a, b)])), 1),
            "idle_s": round(_total(_intersect(op["_idle_iv"], [(a, b)])), 1),
            "waits_s": round(sum(q["seconds"] for q in wt["waits"]
                                 if q["after_stage"] == w["stage"] and q["_a"] >= a), 1),
            "scripts": sum(1 for r in recs if r["kind"] == runlog.KIND_SCRIPT),
            "children": sum(1 for r in recs if r["kind"] == runlog.KIND_CHILD),
            "videos": sorted({r["video"] for r in recs if r["video"]}),
            "open": _open_report(recs),
            "attempts": _attempts(recs),
        })
    videos = []
    seen = set()
    for r in d["intervals"]:
        if not r["video"] or (r["stage"], r["video"]) in seen:
            continue
        wins = wins_by_stage.get(r["stage"]) or ([(t0, t1)] if t0 is not None and t1 is not None else [])
        recs = [q for q in d["intervals"] if q["stage"] == r["stage"] and q["video"] == r["video"]
                and any(a <= q["start"] <= b for a, b in wins)]
        if not recs:                                 # outside every window of its stage
            continue
        seen.add((r["stage"], r["video"]))
        raw = _union((q["start"], q["end"]) for q in recs)
        vbusy = _union([iv for a, b in wins for iv in _clip(raw, a, b)]) or raw
        att = _attempts(recs)
        videos.append({
            "stage": r["stage"], "video": r["video"],
            "start": _iso(raw[0][0]), "end": _iso(raw[-1][1]),
            "wall_s": round(raw[-1][1] - raw[0][0], 1), "busy_s": round(_total(vbusy), 1),
            "attempts": att,
            "attempts_total": sum(v["attempts"] for v in att.values()),
            "failed": sum(v["failed"] for v in att.values()),
        })
    return {"wall": {"start": _iso(t0), "end": _iso(t1), "seconds": round(wall_s, 1)},
            "gaps_s": round(gaps_s, 1), "live_s": round(wall_s - gaps_s, 1),
            "busy_s": round(_total(busy), 1), "waits_s": wt["seconds"],
            "operator_s": op["seconds"], "idle_s": op["idle_s"],
            "stages": stages, "videos": videos, "open": _open_report(d["intervals"])}


# --------------------------------------------------------------------------
# 2. binaries vs the Python wrapper
# --------------------------------------------------------------------------

_NEST_EPS = 1e-3


def _wrapper_ids(intervals):
    """CF-0160: the ids of `child` intervals that enclose another call, so that
    per-tool seconds and calls are summed over the leaves only (a wrapper like
    `ffmpeg full-frames` around `ffmpeg cropdetect` around the real ffmpeg is
    one call of 0.55 s, not three calls of 1.7 s).

    Returns (explicit, inferred). `explicit`: some child names it as `parent` -
    what runlog.child() writes since CF-0160 (its events carry `depth`).
    `inferred`: for calls written before that (no `depth` key) nesting was not
    recorded - every call pointed at the script - so it is read off the spans,
    as footage-indexer's indexer_cost._calls did by hand: a call of the same
    process and the same parent that lies wholly inside another, strictly
    shorter. Calls that carry `depth` never take part in the inference, so two
    threads of one new-format script are never mistaken for nesting."""
    kids = [r for r in intervals if r["kind"] == runlog.KIND_CHILD]
    ids = {r["id"] for r in kids if r.get("id")}
    explicit = {r["parent"] for r in kids if r.get("parent") in ids and r["parent"] != r.get("id")}
    groups = {}
    for r in kids:
        if r.get("depth") is not None or r.get("pid") is None or r.get("id") is None \
                or r["start"] is None or r["end"] is None:
            continue
        groups.setdefault((r["pid"], r.get("parent")), []).append(r)
    inferred = set()
    for g in groups.values():
        g.sort(key=lambda r: (r["start"], -r["end"]))
        for i, r in enumerate(g):
            a, b = r["start"], r["end"]
            for q in g[i + 1:]:
                if q["start"] > b + _NEST_EPS:
                    break
                if q["end"] <= b + _NEST_EPS and (q["end"] - q["start"]) < (b - a) - _NEST_EPS:
                    inferred.add(r["id"])
                    break
    return explicit, inferred - explicit


def binary_times(x):
    """{"tools": {tool: {seconds, calls, failed}}, "total": {scripts_s, children_s, wrapper_s},
        "by_stage": {stage: {tools: {...}, scripts_s, children_s, wrapper_s}},
        "nesting": {"explicit": n, "inferred": n}}

    Per-tool seconds and calls count leaf calls only (CF-0160); `nesting` says
    how many wrapper calls were left out, and how many of them were recognised
    by their span in a journal that predates recorded nesting."""
    d = _loaded(x)
    explicit, inferred = _wrapper_ids(d["intervals"])
    wrappers = explicit | inferred

    def block(recs):
        tools = {}
        for r in recs:
            if r["kind"] != runlog.KIND_CHILD:
                continue
            if r.get("id") and r["id"] in wrappers:
                continue
            t = tools.setdefault(r["tool"] or "?", {"seconds": 0.0, "calls": 0, "failed": 0})
            t["seconds"] += float(r["duration_s"] or 0.0)
            t["calls"] += 1
            t["failed"] += 1 if r["status"] == runlog.ST_FAILED else 0
        for t in tools.values():
            t["seconds"] = round(t["seconds"], 1)
        s_u = _union((r["start"], r["end"]) for r in recs if r["kind"] == runlog.KIND_SCRIPT)
        c_u = _union((r["start"], r["end"]) for r in recs if r["kind"] == runlog.KIND_CHILD)
        scripts_s, children_s = _total(s_u), _total(c_u)
        inside = _total(_union([iv for a, b in s_u for iv in _clip(c_u, a, b)]))
        return {"tools": dict(sorted(tools.items(), key=lambda kv: -kv[1]["seconds"])),
                "scripts_s": round(scripts_s, 1), "children_s": round(children_s, 1),
                "wrapper_s": round(max(0.0, scripts_s - inside), 1)}

    total = block(d["intervals"])
    by_stage = {}
    for w in d["stages"]:
        by_stage[w["stage"]] = block([r for r in d["intervals"] if r["stage"] == w["stage"]])
    return {"tools": total["tools"], "total": {k: total[k] for k in ("scripts_s", "children_s", "wrapper_s")},
            "by_stage": by_stage,
            "nesting": {"explicit": len(explicit), "inferred": len(inferred)}}


# --------------------------------------------------------------------------
# 3. gaps - the first line
# --------------------------------------------------------------------------

def _sampler_idle_s():
    """CF-0377/CF-0339: how long a run may be idle before the sampler leaves."""
    try:
        return float(runlog.sibling("sampler").IDLE_MINUTES) * 60.0
    except Exception:
        return 600.0


def gaps_summary(x):
    d = _loaded(x)
    # CF-0377: `limit` and `unknown` are always named, so a run with neither still
    # says so. A gap that read its cause off its own boundaries (`idle_exit`,
    # `<step>_timeout`) brings its own bucket - a new cause needs no line here.
    by = {"limit": {"count": 0, "seconds": 0.0}, "unknown": {"count": 0, "seconds": 0.0}}
    out = []
    for g in d["gaps"]:
        cause = str(g.get("cause") or "unknown") or "unknown"
        secs = float(g.get("seconds") or (g["_t1"] - g["_t0"]))
        by.setdefault(cause, {"count": 0, "seconds": 0.0})
        by[cause]["count"] += 1
        by[cause]["seconds"] += secs
        out.append({"start": g.get("start"), "end": g.get("end"), "seconds": round(secs, 1),
                    "cause": cause, "before": g.get("before"), "after": g.get("after"),
                    "evidence": g.get("evidence")})
    for v in by.values():
        v["seconds"] = round(v["seconds"], 1)
    return {"count": len(out), "seconds": round(sum(g["seconds"] for g in out), 1),
            "by_cause": by, "gaps": out}


def gaps_line(x):
    """The first line of the summary."""
    d = _loaded(x)
    g = gaps_summary(d)
    t0, t1 = d["wall"]
    wall = (t1 - t0) if t0 is not None and t1 is not None else None
    if not g["count"]:
        return f"GAPS: none (wall {_hms(wall)})"
    parts = [f"{c} {v['count']} = {_hms(v['seconds'])}" for c, v in g["by_cause"].items() if v["count"]]
    return (f"GAPS: {g['count']} ({'; '.join(parts)}) - total {_hms(g['seconds'])}"
            f" of {_hms(wall)} wall ({_pct(g['seconds'], wall or 0)} %)")


# --------------------------------------------------------------------------
# 3b. waiting for a human (CF-0252)
# --------------------------------------------------------------------------

def waits(x):
    """CF-0252: the stretches where the batch waited for a human, not for a CPU.

        {"count", "seconds", "outside_gaps_s", "by_stage": {stage: seconds},
         "waits": [{start, end, since ("14:17"), seconds, minutes, after_stage,
                    next_stage, in_gap_s, seconds_outside_gaps, _a, _b}]}

    A wait is a silence of at least WAIT_MIN_S (10 min) that starts at a
    `stage-done` and runs until the next `stage-start` (or `batch-done`, or the
    end of the wall) with no script and no binary inside it. The orchestrator is
    between stages there: the batch is waiting for the operator to look at it,
    or for a fix to the code - 2026-09-15 stood 3h11m32s after
    `content-researcher` (`CF-0242` was being fixed) and 1h05m05s inside
    `video-editor` (`CF-0243`), and the summary called it `GAPS: none`.

    Why not gaps.py: a gap is a silence in *all* activity events, and the
    sampler ticks every few seconds through a wait, so a run with a sampler
    never has one. Waits look at the work events only (scripts, binaries,
    markers), which is why they see what the gap detector cannot. Where a wait
    does overlap a recorded gap, `in_gap_s` says how much - section 3 counts
    that part once, as a gap.

    The time is *named*, not hidden: it is a column of the stage table
    (`waiting`), a line of section 3, and part of the covered time in
    unattributed(), so it can no longer arrive as "unattributed 2.7 %"."""
    d = _loaded(x)
    t0, t1 = d["wall"]
    empty = {"count": 0, "seconds": 0.0, "outside_gaps_s": 0.0, "by_stage": {}, "waits": []}
    if t0 is None or t1 is None or t1 <= t0:
        return empty
    busy = _union((r["start"], r["end"]) for r in d["intervals"])
    gm = _gap_merged(d)
    marks = sorted((t, e.get("status"), e.get("stage"))
                   for t, e in ((_ts(e.get("ts")), e) for e in d["markers"]) if t is not None)
    out = []
    for i, (t, st, stage) in enumerate(marks):
        if st != runlog.M_STAGE_DONE or not (t0 <= t <= t1):
            continue
        nxt = next(((tt, s2, sg) for tt, s2, sg in marks[i + 1:]
                    if s2 in (runlog.M_STAGE_START, runlog.M_BATCH_DONE) and tt > t), None)
        b = min(nxt[0] if nxt else t1, t1)
        for a2, b2 in _complement(busy, t, b):
            if b2 - a2 < WAIT_MIN_S:
                continue
            in_gap = _total(_clip(gm, a2, b2))
            out.append({
                "start": _iso(a2), "end": _iso(b2), "since": _hm(a2),
                "seconds": round(b2 - a2, 1), "minutes": round((b2 - a2) / 60.0, 1),
                "after_stage": stage, "next_stage": nxt[2] if nxt and nxt[1] == runlog.M_STAGE_START else None,
                "in_gap_s": round(in_gap, 1), "seconds_outside_gaps": round(b2 - a2 - in_gap, 1),
                "_a": a2, "_b": b2})
    by = {}
    for w in out:
        by[w["after_stage"]] = round(by.get(w["after_stage"], 0.0) + w["seconds"], 1)
    return {"count": len(out), "seconds": round(sum(w["seconds"] for w in out), 1),
            "outside_gaps_s": round(sum(w["seconds_outside_gaps"] for w in out), 1),
            "by_stage": by, "waits": out}


def waits_line(x):
    """The WAITS line of the summary - beside the GAPS line, not inside it."""
    d = _loaded(x)
    w = waits(d)
    t0, t1 = d["wall"]
    wall = (t1 - t0) if t0 is not None and t1 is not None else None
    if not w["count"]:
        return f"WAITS: none (no stage waited for a human longer than {WAIT_MIN_S / 60:g} min)"
    bits = "; ".join(f"{q['after_stage'] or '?'} since {q['since']} {_hms(q['seconds'])}"
                     for q in w["waits"])
    line = (f"WAITS: {w['count']} = {_hms(w['seconds'])} of {_hms(wall)} wall "
            f"({_pct(w['seconds'], wall or 0)} %) waiting for a human - {bits}")
    if w["seconds"] - w["outside_gaps_s"] > 1.0:
        line += f" (of which {_hms(w['seconds'] - w['outside_gaps_s'])} already counted as a gap)"
    return line


# --------------------------------------------------------------------------
# 3b. the stage operator: its own time, and the time it stood still (CF-0257)
# --------------------------------------------------------------------------

def operator(x):
    """CF-0257: the time of the stage's *operator* - and the time it stood still.

        {"seconds"            operator time of the batch (all stages together)
         "idle_s"             of which stood still - see below
         "count"              idle stretches
         "by_stage"           {stage: {"operator_s", "idle_s"}}
         "idle"               [{start, end, since, seconds, minutes, stage, cause,
                                before, after, _a, _b}]
         "stage_wall_s"       wall covered by stage windows
         "outside"            [{start, end, seconds, _a, _b}] - live time *outside*
                              every stage window and outside every wait: what
                              unattributed() is left with}

    A batch is run by an orchestrator session; every stage is a background LLM
    operator that calls scripts. Between two script calls it reads the previous
    stage's JSON, thinks, and writes the next one - no process is running, and
    until this function that time was `unattributed`, 13.9 % to 94.9 % of the
    live time of the seven batches of 2026-09-15..20. It is not unattributed: it
    belongs to the stage whose window it falls in, exactly as `busy` does, and
    it is named `operator` - it is simply not time a *script* spent.

        operator = (a stage window) minus (busy, gaps, waits) minus idle

    Idle is the other half of the finding. A silence of IDLE_MIN_S (10 min) or
    more *inside* a stage window with no script and no binary event in it is not
    the operator working: on 2026-09-19T0116Z the footage-indexer operator
    finished an `ingest` at 2026-09-20T14:05:46Z and then wrote nothing at all
    until 15:08:22Z, and its `stage-done` came only after somebody looked at the
    batch. Counting that as operator time would put 1h02m36s of "work" on a
    stage that was standing still - the same mistake, one level down, that
    CF-0252 fixed for the four hours the batch spent waiting for a human. So it
    gets its own name, `operator idle`.

    The silences come from `gaps.detect` (CF-0108) over the batch's *work*
    events - every kind but `sample`. The gap detector already knows how to walk
    a run's events, how not to call a silence inside a running script a silence,
    and how to tell a silence caused by the usage limit (a `limit-hit` event or a
    resume marker in the transcript) from one nobody can explain; each idle
    stretch carries that `cause`. The sampler has to be dropped or there is
    never a silence to find: it ticks every five seconds straight through one.

    Why IDLE_MIN_S is 600 s: the 861 in-stage pauses of those seven batches are
    a smooth heavy tail with no natural break - median 0.8 s, p90 52.6 s,
    p95 119.9 s, p98 290.2 s, p99 578.1 s, max 3755.8 s. 600 s is the 99.2nd
    percentile: 7 pauses (0.81 %) reach it, and they hold 2h38m40s (35.9 %) of
    all in-stage pause time. It is also the number this repo already uses twice
    for "a silence this long is not work" - `gaps.MIN_GAP_S` and `WAIT_MIN_S` -
    so the rule is one rule, not three: a silence of ten minutes or more is
    idle time wherever it falls. Outside a stage it is a wait for a human
    (CF-0252); inside one it is the operator standing still."""
    d = _loaded(x)
    cached = d.get("_operator")
    if cached is not None:
        return cached
    t0, t1 = d["wall"]
    empty = {"seconds": 0.0, "idle_s": 0.0, "count": 0, "by_stage": {}, "idle": [],
             "stage_wall_s": 0.0, "outside": []}
    if t0 is None or t1 is None or t1 <= t0:
        d["_operator"] = empty
        return empty
    gm = _clip(_gap_merged(d), t0, t1)
    wt = waits(d)
    busy = _union((r["start"], r["end"]) for r in d["intervals"])
    named = _union(list(busy) + list(gm) + [(w["_a"], w["_b"]) for w in wt["waits"]])
    holes = _complement(named, t0, t1)
    wins = _clip(_union((w["start"], w["end"] if w["end"] is not None else t1)
                        for w in d["stages"] if w["start"] is not None), t0, t1)
    inside = _intersect(holes, wins)
    outside = _subtract(holes, wins, t0, t1)
    # the silences, from the gap detector over the work events (CF-0108)
    gmod = runlog.sibling("gaps")
    work = [e for e in d["events"] if e.get("kind") != "sample"]
    sil = gmod.detect(events=work, min_gap_s=IDLE_MIN_S, transcripts=[],
                      projects=Path("/nonexistent"))
    for g in sil:
        g["_a"], g["_b"] = _ts(g["start"]), _ts(g["end"])
    sil = [g for g in sil if g["_a"] is not None and g["_b"] is not None]
    idle_iv = [(a, b) for a, b in _intersect(inside, [(g["_a"], g["_b"]) for g in sil])
               if b - a >= IDLE_MIN_S]
    work_iv = _subtract(inside, idle_iv, t0, t1)
    idle = []
    for a, b in idle_iv:
        src = next((g for g in sil if g["_a"] <= a and b <= g["_b"]), None)
        idle.append({"start": _iso(a), "end": _iso(b), "since": _hm(a),
                     "seconds": round(b - a, 1), "minutes": round((b - a) / 60.0, 1),
                     "stage": _stage_at(a, d["stages"]),
                     "cause": (src or {}).get("cause") or "unknown",
                     "before": (src or {}).get("before"), "after": (src or {}).get("after"),
                     "_a": a, "_b": b})
    by = {}
    for w in d["stages"]:
        if w["start"] is None:
            continue
        a, b = w["start"], w["end"] if w["end"] is not None else t1
        cell = by.setdefault(w["stage"], {"operator_s": 0.0, "idle_s": 0.0})
        cell["operator_s"] = round(cell["operator_s"] + _total(_intersect(work_iv, [(a, b)])), 1)
        cell["idle_s"] = round(cell["idle_s"] + _total(_intersect(idle_iv, [(a, b)])), 1)
    out = {"seconds": round(_total(work_iv), 1), "idle_s": round(_total(idle_iv), 1),
           "count": len(idle), "by_stage": by, "idle": idle,
           "stage_wall_s": round(_total(wins), 1),
           "outside": [{"start": _iso(a), "end": _iso(b), "seconds": round(b - a, 1),
                        "_a": a, "_b": b} for a, b in outside],
           "_work_iv": work_iv, "_idle_iv": idle_iv}
    d["_operator"] = out
    return out


def operator_line(x):
    """The OPERATOR line of the summary - beside the GAPS and WAITS lines."""
    d = _loaded(x)
    o = operator(d)
    t0, t1 = d["wall"]
    wall = (t1 - t0) if t0 is not None and t1 is not None else None
    line = (f"OPERATOR: {_hms(o['seconds'])} of {_hms(wall)} wall "
            f"({_pct(o['seconds'], wall or 0)} %) the stage operators spent between their scripts")
    if not o["count"]:
        return line + f"; no stage stood still longer than {IDLE_MIN_S / 60:g} min"
    bits = "; ".join(f"{q['stage'] or '?'} since {q['since']} {_hms(q['seconds'])}"
                     f"{'' if q['cause'] == 'unknown' else ' (' + q['cause'] + ')'}"
                     for q in o["idle"])
    return (line + f" - and {_hms(o['idle_s'])} standing still in "
            f"{o['count']} stretch(es): {bits}")


# --------------------------------------------------------------------------
# 4. tokens by stage x model x role
# --------------------------------------------------------------------------

def tokens(x):
    """{"rows": [{stage, model, role, usage, calls}] (videos and agents folded),
        "by_stage": {stage: totals}, "videos": [{stage, video, calls, total}],
        "total": totals, "error": str|None}; from the newest `usage` generation,
        empty when the batch has none. `error` is why the batch-done scan
        produced none (CF-0172), when it left a reason.

    `videos` (CF-0174) is the same numbers cut one level down - per (stage,
    slug), models, roles and agents folded, in stage order - plus one
    `video: None` row per stage that has any slug, for the calls of that stage
    carrying none (the stage before its first slug event, a step that names no
    video). Empty when no usage row carries a slug."""
    d = _loaded(x)
    usage = runlog.sibling("usage")
    folded = {}
    for e in d["usage"]:
        key = (e.get("stage"), e.get("model"), e.get("role"))
        f = folded.setdefault(key, {"stage": key[0], "model": key[1], "role": key[2],
                                    "usage": {c: 0 for c in usage.COUNTERS}, "calls": 0})
        for c in usage.COUNTERS:
            f["usage"][c] += int((e.get("usage") or {}).get(c) or 0)
        f["calls"] += int(e.get("calls") or 0)
    rows = list(folded.values())
    by_stage = {}
    for r in rows:
        by_stage.setdefault(r["stage"], []).append(r)
    # CF-0173: a stage the markers declared and that spent nothing is a zero, not
    # a silence. Without this a `pool-maintenance` over a pool that was already
    # fresh - the 1.3 s check and no more - reads exactly like a stage that never
    # ran, and the one number the section exists to show (this stage costs no
    # tokens) can only be got by knowing it is missing.
    if rows:
        for w in d["stages"]:
            by_stage.setdefault(w["stage"], [])
    return {"rows": rows,
            "by_stage": {s: usage.totals(rs) for s, rs in by_stage.items()},
            "videos": _tokens_by_video(d["usage"], list(by_stage)),
            "total": usage.totals(rows) if rows else None,
            "computed": (d["usage"][0].get("computed") if d["usage"] else None),
            "error": _scan_error(d)}


def _tokens_by_video(rows, stage_order):
    """CF-0174: [{stage, video, calls, usage, total, fresh}] per (stage, slug),
    models, roles and agents folded, in stage order, with the slug-less
    remainder of every stage that has slugs as its `video: None` row. [] when
    nothing carries one."""
    usage = runlog.sibling("usage")
    if not any(e.get("video") for e in rows):
        return []
    folded, order = {}, {}
    for e in rows:
        key = (e.get("stage"), e.get("video"))
        f = folded.setdefault(key, {"stage": key[0], "video": key[1],
                                    "usage": {c: 0 for c in usage.COUNTERS}, "calls": 0})
        order.setdefault(key, len(order))
        for c in usage.COUNTERS:
            f["usage"][c] += int((e.get("usage") or {}).get(c) or 0)
        f["calls"] += int(e.get("calls") or 0)
    with_slug = {f["stage"] for f in folded.values() if f["video"]}
    out = [f for f in folded.values() if f["stage"] in with_slug]
    out.sort(key=lambda f: (stage_order.index(f["stage"]) if f["stage"] in stage_order else len(stage_order),
                            f["video"] is None, order[(f["stage"], f["video"])]))
    for f in out:
        t = usage.totals([f])
        f["total"], f["fresh"] = t["total"], t["fresh"]
    return out


def _scan_error(d):
    """CF-0172: 'the transcript scan of batch-done failed at <ts>: <reason>', or None."""
    e = d.get("usage_error")
    if not e:
        return None
    return (f"the `batch-done` transcript scan at {e.get('ts')} "
            f"{e.get('error') or 'left no reason'}")


# --------------------------------------------------------------------------
# 5. share of the subscription windows
# --------------------------------------------------------------------------

def _stale(p):
    """CF-0171: how long before its own event the reading was actually taken.

    `stale_s` (limits.py) is the age of the measurement at the moment it was
    written: 0 for the live statusline hook, the age of `~/.claude/rate_limits.json`
    for the fallback source `limits.record_from_file()`. Only a live reading
    measures the moment its event carries; a fallback one measures `ts - stale_s`,
    and that is the moment a stage window has to be matched against. Negative or
    unparseable values are treated as 0 - a reading is never from the future."""
    try:
        s = float(p.get("stale_s") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    return s if s > 0.0 else 0.0


def _readings(d):
    """(readings, missing) - CF-0175 item 1, CF-0171.

    `t` is when the value was *measured* (`ts - stale_s`, see _stale), not when
    the event was written, and the list is sorted by it: once readings are
    shifted back, the append order of the log is no longer time order, and both
    _consumed() and _bracket() read their input in list order. All 280 readings
    of run 2026-09-09 are live (`stale_s = 0.0`), so for them the shift is a
    no-op; it decides where a fallback reading lands, and with stage windows as
    short as 32 s (`compliance-checker` in that run) a fallback reading written
    at a stage marker would otherwise be credited to a stage that had not yet
    started when the value was taken.

    A `limits` event is written whenever *either* window is readable, so a
    reading can measure the 7-day window and say nothing about the 5-hour one
    (3 of the 280 readings of run 2026-09-09 are exactly that). Those used to
    fall out of the 5-hour chain without a word, leaving the column standing on
    277 readings while the summary said 280. `missing` counts them the way
    `probe_errors` counts a failed probe (CF-0167): per window, plus `unusable`
    for an event with no timestamp or no params at all."""
    out = []
    missing = {"five_hour": 0, "seven_day": 0, "unusable": 0}
    for e in d["limits"]:
        p = e.get("params") or {}
        t = _ts(e.get("ts"))
        if t is None or not isinstance(p, dict):
            missing["unusable"] += 1
            continue
        r = {"t": t - _stale(p)}
        for w in ("five_hour", "seven_day"):
            win = p.get(w) or {}
            up = win.get("used_percentage") if isinstance(win, dict) else None
            try:
                # round(): the percentage is computed upstream and arrives with the
                # tail of that division (`7.000000000000001`) - CF-0175 item 3.
                r[w] = (round(float(up), 3), win.get("resets_at")) if up is not None else None
            except (TypeError, ValueError):
                r[w] = None
            if r[w] is None:
                missing[w] += 1
        out.append(r)
    out.sort(key=lambda r: r["t"])          # CF-0171: by measurement time, stable
    return out, missing


def _consumed(readings, w):
    """% of window w spent between the first and the last reading: the sum of
    the increases, and the whole new value after a reset (resets_at changed
    or the percentage fell)."""
    rs = [r[w] for r in readings if r.get(w) is not None]
    if len(rs) < 2:
        return None
    used = 0.0
    for (pa, ra), (pb, rb) in zip(rs, rs[1:]):
        if (ra and rb and ra != rb) or pb < pa:
            used += pb
        else:
            used += pb - pa
    return round(used, 1)


def _bracket(rs, w, a, b, limit=None):
    """CF-0169: the readings of window `w` that measure the stage window [a, b].

    A reading carries the percentage as of the moment it was measured (`t`, i.e.
    `ts - stale_s` - see _stale), and the statusline that produces them only
    fires while the driver session redraws -
    that is, in the pauses *between* stages and almost never inside a long one
    (of the 280 readings of run 2026-09-09, six of the seven stage windows
    contain none at all). So the chain is the bracket of the window, not just
    what falls inside it:

        baseline  the last reading at or before `a` - what the stage started from;
        middle    every reading inside (a, b], so a reset inside a stage is still
                  seen by _consumed();
        closing   the last reading inside the window when there is one, otherwise
                  the first reading after `b` - the earliest one that can show what
                  the stage spent - and only while it comes before `limit` (the
                  next stage's start), so the next stage's work is never counted here.

    Empty (or a single reading) when nothing measures the stage: only then is the
    stage's share unknown. A stage whose percentage simply did not move gives a
    chain of equal values, i.e. 0 %, not `?`."""
    rs = [r for r in rs if r.get(w) is not None]
    before = [r for r in rs if r["t"] <= a]
    inside = [r for r in rs if a < r["t"] <= b]
    chain = ([before[-1]] if before else []) + inside
    if not inside:
        after = next((r for r in rs if r["t"] > b and (limit is None or r["t"] <= limit)), None)
        if after is not None:
            chain.append(after)
    return chain


def _source_at_start(d):
    """CF-0230: the `limits_source` snapshot the batch-start marker took (None for
    a run opened before CF-0230 or by hand)."""
    key = runlog.sibling("limits").SOURCE_KEY
    for e in d["events"]:
        if e.get("kind") == runlog.KIND_MARKER and e.get("status") == runlog.M_BATCH_START:
            v = e.get(key)
            return v if isinstance(v, dict) else None
    return None


def _no_share_cause(n, state):
    """CF-0230: why the readings are missing, in one clause - so section 5 never
    just goes blank. Built from what the run recorded, never from the file as it
    is when the summary is rendered."""
    if n >= 2:
        return None
    lim = runlog.sibling("limits")
    head = ("no reading was written during the run" if n == 0
            else "a single reading gives no difference")
    head += " (the statusline hook writes them only while a terminal session redraws; desktop runs leave none)"
    if state is None:
        return head + "; the fallback source was not probed at batch-start (the run predates CF-0230)"
    prob = lim.source_problem(state)
    if prob:
        return head + f"; at batch-start the fallback source was no help either: {prob}"
    return (head + f"; yet at batch-start the source was fresh ({round((state.get('age_s') or 0) / 60)} min, "
            "with five_hour) - the hook did not find this run as the active one")


def window_share(x):
    """{"readings": n, "missing": {...}, "run": {five_hour, seven_day},
        "stages": {stage: {...}}, "note"}.

    Per stage: the delta over the stage window from the readings that bracket it
    (see _bracket); a stage that ran more than once sums its windows, and its
    `readings` counts every reading the deltas were taken from. `?` (None) stays
    only where no reading measures the stage at all.
    Null percentages everywhere, with the note, when fewer than two readings exist.

    Two honesty fields, both CF-0175:

    `missing`   readings that carry no block for a window (see _readings) - the
                column stands on `readings - missing[w]` of them, not on all.
    `chain`     per stage, the *shortest* chain a part of the number came from
                (a stage that ran twice sums two chains, and the sum is only as
                solid as its weakest part; `readings` stays the total). At
                ESTIMATE_CHAIN or below some part of the share is *one difference
                of two readings*, and the readings sit on a whole-percent grid, so
                it carries about +-1 pp on values that are themselves 0..4 pp:
                an estimate, not a number to rank stages by. The reliable
                post-stage signal is tokens (section 4), not window percent."""
    d = _loaded(x)
    rs, missing = _readings(d)
    out = {"readings": len(rs), "missing": missing,
           "run": {"five_hour": None, "seven_day": None}, "stages": {}, "note": None,
           "source": None, "cause": None}
    out["source"] = _source_at_start(d)
    out["cause"] = _no_share_cause(len(rs), out["source"])
    if len(rs) < 2:
        out["note"] = (f"window share unknown: {len(rs)} `limits` reading(s) in this run, "
                       f"at least 2 needed - {out['cause']}")
        for w in d["stages"]:
            out["stages"][w["stage"]] = {"five_hour": None, "seven_day": None,
                                         "readings": 0, "chain": None}
        return out
    for w in ("five_hour", "seven_day"):
        out["run"][w] = _consumed(rs, w)
    starts = sorted(st["start"] for st in d["stages"])
    for st in d["stages"]:
        a, b = st["start"], st["end"]
        limit = next((s for s in starts if s > b), None)
        cell = out["stages"].setdefault(st["stage"],
                                        {"five_hour": None, "seven_day": None,
                                         "readings": 0, "chain": None})
        n = 0
        for w in ("five_hour", "seven_day"):
            chain = _bracket(rs, w, a, b, limit)
            n = max(n, len(chain))
            v = _consumed(chain, w)
            if v is not None:
                cell[w] = round((cell[w] or 0.0) + v, 1)
                cell["chain"] = min(cell["chain"] or len(chain), len(chain))
        cell["readings"] += n
    return out


def is_estimate(cell):
    """CF-0175: True when some part of the stage's share rests on a chain of
    ESTIMATE_CHAIN readings or fewer - one difference of two whole-percent readings."""
    c = cell.get("chain")
    return c is not None and c <= ESTIMATE_CHAIN


# --------------------------------------------------------------------------
# 6. CPU / memory / GPU by stage
# --------------------------------------------------------------------------

def verdict(cpu_pipeline_mean, gpu_mean):
    if cpu_pipeline_mean is None and gpu_mean is None:
        return V_NONE
    if (cpu_pipeline_mean or 0.0) >= HW_BOUND_CPU_PCT or (gpu_mean or 0.0) >= HW_BOUND_GPU_PCT:
        return V_HW
    # CF-0167: a missing CPU reading is not 0 % - "waiting" needs a measurement to stand on
    if (cpu_pipeline_mean is not None and cpu_pipeline_mean <= WAITING_PCT
            and (gpu_mean is None or gpu_mean <= WAITING_PCT)):
        return V_WAIT
    return V_MIXED


def _stats(samples):
    ps = [s.get("params") or {} for s in samples]
    rss = []
    for p in ps:
        procs = p.get("procs") or []
        rss.append(sum(float(q.get("rss_mb") or 0.0) for q in procs) if procs else None)
    gpu = [(p.get("gpu") or {}).get("util_pct") if isinstance(p.get("gpu"), dict) else None for p in ps]
    cpu_p = _mean([p.get("cpu_pipeline_pct") for p in ps])
    gpu_m = _mean(gpu)
    return {"samples": len(ps),
            "cores": next((p.get("cpu_cores") for p in ps if p.get("cpu_cores")), None),
            "cpu_total_mean": _mean([p.get("cpu_total_pct") for p in ps]),
            "cpu_total_max": _max([p.get("cpu_total_pct") for p in ps]),
            "cpu_pipeline_mean": cpu_p,
            "cpu_pipeline_max": _max([p.get("cpu_pipeline_pct") for p in ps]),
            "rss_max_mb": _max(rss),
            "mem_used_max_mb": _max([p.get("mem_used_mb") for p in ps]),
            "swap_max_mb": _max([p.get("swap_mb") for p in ps]),
            "gpu_mean": gpu_m, "gpu_max": _max(gpu),
            "verdict": verdict(cpu_p, gpu_m) if ps else V_NONE}


def resources(x):
    """{"run": stats, "stages": {stage: stats}, "thresholds": {...}}; a sample
    belongs to the stage it names, else to the stage open at its time."""
    d = _loaded(x)
    by = {w["stage"]: [] for w in d["stages"]}
    for s in d["samples"]:
        st = s.get("stage") or _stage_at(_ts(s.get("ts")) or -1, d["stages"])
        if st in by:
            by[st].append(s)
        elif st:
            by.setdefault(st, []).append(s)
    return {"run": _stats(d["samples"]),
            "stages": {st: _stats(ss) for st, ss in by.items()},
            "thresholds": {"hardware_bound_cpu_pct": HW_BOUND_CPU_PCT,
                           "hardware_bound_gpu_pct": HW_BOUND_GPU_PCT, "waiting_pct": WAITING_PCT}}


# --------------------------------------------------------------------------
# unattributed time and the flag
# --------------------------------------------------------------------------

def unattributed(x):
    """{"seconds", "pct" (of live), "live_s", "wall_s", "waits_s", "operator_s",
        "idle_s", "intervals": [{start, end, seconds, after, before}]
        (> UNATTRIBUTED_MIN_S), "incomplete": bool,
        "accounting": "complete" | "incomplete"}

    CF-0252: a wait for a human counts as covered time - it is attributed, to a
    human. Before this, four hours of 2026-09-15 were covered by an interval
    left open instead, which is how a batch that stood still for 4h15m reported
    `unattributed 2.7 %, accounting: complete`.

    CF-0257: so does the time of a stage's own operator, and the time it stood
    still - see operator(). What is left is what the word was always supposed to
    mean: live time that falls *outside every stage window* and outside every
    named wait, which nobody can account for at all. The orchestrator session
    that runs the batch is in there - it reads a stage's output and starts the
    next stage - but nothing records what it did or when, so the honest answer
    is that this time is unattributed rather than to invent a name for it. It is
    ~2-4 minutes per stage boundary on the seven batches of 2026-09-15..20, and
    the thing to do about it is to instrument the orchestrator, not to widen the
    threshold."""
    d = _loaded(x)
    t0, t1 = d["wall"]
    if t0 is None or t1 is None or t1 <= t0:
        return {"seconds": 0.0, "pct": 0.0, "live_s": 0.0, "wall_s": 0.0, "waits_s": 0.0,
                "operator_s": 0.0, "idle_s": 0.0,
                "intervals": [], "incomplete": False, "accounting": ACC_OK}
    gm = _gap_merged(d)
    wt = waits(d)
    op = operator(d)
    holes = [(q["_a"], q["_b"]) for q in op["outside"]]
    wall_s = t1 - t0
    live_s = wall_s - _total(_clip(gm, t0, t1))
    secs = _total(holes)
    pct = _pct(secs, live_s)
    ivs = []
    for a, b in holes:
        if b - a <= UNATTRIBUTED_MIN_S:
            continue
        before = [e for e in d["events"] if (_ts(e.get("ts")) or 0) <= a
                  and e.get("kind") in ("script", "child", "marker", "gap")]
        after = [e for e in d["events"] if (_ts(e.get("ts")) or 0) >= b
                 and e.get("kind") in ("script", "child", "marker", "gap")]
        ivs.append({"start": _iso(a), "end": _iso(b), "seconds": round(b - a, 1),
                    "after": _label(before[-1]) if before else None,
                    "before": _label(after[0]) if after else None})
    inc = pct > INCOMPLETE_PCT
    return {"seconds": round(secs, 1), "pct": pct, "live_s": round(live_s, 1),
            "wall_s": round(wall_s, 1), "waits_s": wt["seconds"],
            "operator_s": op["seconds"], "idle_s": op["idle_s"], "intervals": ivs,
            "incomplete": inc, "accounting": ACC_INCOMPLETE if inc else ACC_OK}


# --------------------------------------------------------------------------
# the invariants of section 1 (CF-0252)
# --------------------------------------------------------------------------

def consistency(x, times=None):
    """CF-0252: the checks that would have caught "busy 9h15m56s in a 2h54m41s
    stage" before a human argued with the number for a round.

        {"ok": bool, "checks": [...], "violations": ["..."], "notes": ["..."]}

    stage busy <= stage wall            no stage can compute longer than it ran
    video busy <= video wall            nor can a video, inside its own span
    video busy <= its stage's busy      a video's time is a part of its stage's
    per-video busy <= stage busy        and so is all of them together
    batch busy <= wall                  and of the batch's
    the six parts add up to the wall    CF-0257: gaps + busy + waiting for a human +
                                        operator + operator idle + unattributed is the
                                        whole wall and nothing twice. The parts are taken
                                        in that order and each one only gets what the
                                        earlier ones left, so a second of the run belongs
                                        to exactly one of them. This is the check that
                                        makes "unattributed" a residue with a meaning
                                        rather than a number nobody can reproduce.

    The per-video check is on the *union* of the per-video intervals, not on
    their sum: a stage that renders three videos at once spends less wall time
    than the sum of their busy times, which is not a double count. Such a stage
    gets a `note` naming the overlap instead - "video-editor worked on its
    videos in parallel: per-video busy sums to 48m20s over a stage busy of
    43m46s" - so the reader is not left to wonder at a column that does not add
    up.

    A violation is a defect of the accounting, not of the run: it means a time
    has been counted twice (an interval without its `done` stretched over the
    whole batch, a video window read over the whole file). `render` prints the
    result as one line under section 1 either way, so a future regression says
    so in the artifact instead of looking like a slow stage."""
    d = _loaded(x)
    T = times or stage_times(d)
    t0, t1 = d["wall"]
    tol = 1.5
    v, notes = [], []
    wall = T["wall"]["seconds"]
    if T["busy_s"] > wall + tol:
        v.append(f"batch busy {_hms(T['busy_s'])} > wall {_hms(wall)}")
    for w in T["stages"]:
        if w["busy_s"] > w["wall_s"] + tol:
            v.append(f"stage {w['stage']} ({w['start']}) busy {_hms(w['busy_s'])} "
                     f"> its wall {_hms(w['wall_s'])}")
    by_stage_busy, by_stage_video = {}, {}
    for w in T["stages"]:
        by_stage_busy[w["stage"]] = round(by_stage_busy.get(w["stage"], 0.0) + w["busy_s"], 1)
    for q in T["videos"]:
        by_stage_video[q["stage"]] = round(by_stage_video.get(q["stage"], 0.0) + q["busy_s"], 1)
        if q["busy_s"] > q["wall_s"] + tol:
            v.append(f"video {q['stage']}/{q['video']} busy {_hms(q['busy_s'])} "
                     f"> its wall {_hms(q['wall_s'])}")
    wins = {}
    for w in d["stages"]:
        wins.setdefault(w["stage"], []).append((w["start"], w["end"] if w["end"] is not None else t1))
    for st, secs in by_stage_video.items():
        have = by_stage_busy.get(st)
        if have is None:
            continue
        for q in T["videos"]:
            if q["stage"] == st and q["busy_s"] > have + tol:
                v.append(f"video {st}/{q['video']} busy {_hms(q['busy_s'])} > the busy of its "
                         f"stage {_hms(have)}")
        if secs <= have + tol:
            continue
        ws = [(a, b) for a, b in wins.get(st, []) if a is not None and b is not None]
        recs = [r for r in d["intervals"] if r["stage"] == st and r["video"]
                and any(a <= r["start"] <= b for a, b in ws)]
        raw = _union((r["start"], r["end"]) for r in recs)
        union_s = _total(_union([iv for a, b in ws for iv in _clip(raw, a, b)]))
        if union_s > have + tol:
            v.append(f"the per-video intervals of {st} cover {_hms(union_s)} > the stage's "
                     f"busy {_hms(have)}")
        else:
            notes.append(f"{st} worked on its videos in parallel: per-video busy sums to "
                         f"{_hms(secs)} over a stage busy of {_hms(have)} "
                         f"({_hms(secs - union_s)} of overlap)")
    # CF-0257: the six parts of the wall, taken in order, add up to it exactly
    parts = _parts(d)
    if parts["wall_s"] > 0:
        total = sum(parts[k] for k in ("gaps_s", "busy_s", "waits_s", "operator_s",
                                       "idle_s", "unattributed_s"))
        if abs(total - parts["wall_s"]) > tol:
            v.append(f"the parts of the wall sum to {_hms(total)}, not to the wall "
                     f"{_hms(parts['wall_s'])} (gaps {_hms(parts['gaps_s'])} + busy "
                     f"{_hms(parts['busy_s'])} + waiting {_hms(parts['waits_s'])} + operator "
                     f"{_hms(parts['operator_s'])} + idle {_hms(parts['idle_s'])} + unattributed "
                     f"{_hms(parts['unattributed_s'])})")
    return {"ok": not v, "checks": ["stage busy <= stage wall", "video busy <= video wall",
                                    "video busy <= its stage's busy", "per-video busy <= stage busy",
                                    "batch busy <= wall",
                                    "gaps + busy + waiting + operator + idle + unattributed = wall"],
            "violations": v, "notes": notes, "parts": parts}


def _parts(x):
    """CF-0257: the wall cut into six parts that never overlap, in this order -
    gaps, busy, waiting for a human, operator, operator idle, unattributed. Each
    part is only what the earlier ones left, so the six add up to the wall."""
    d = _loaded(x)
    t0, t1 = d["wall"]
    keys = ("gaps_s", "busy_s", "waits_s", "operator_s", "idle_s", "unattributed_s")
    if t0 is None or t1 is None or t1 <= t0:
        return dict({k: 0.0 for k in keys}, wall_s=0.0)
    op = operator(d)
    gm = _clip(_gap_merged(d), t0, t1)
    busy = _union((r["start"], r["end"]) for r in d["intervals"])
    waits_iv = [(q["_a"], q["_b"]) for q in waits(d)["waits"]]
    taken, out = [], {}
    for key, iv in (("gaps_s", gm), ("busy_s", busy), ("waits_s", waits_iv),
                    ("operator_s", op["_work_iv"]), ("idle_s", op["_idle_iv"]),
                    ("unattributed_s", [(q["_a"], q["_b"]) for q in op["outside"]])):
        mine = _subtract(iv, taken, t0, t1)
        out[key] = round(_total(mine), 1)
        taken = _union(list(taken) + list(mine))
    out["wall_s"] = round(t1 - t0, 1)
    return out


# --------------------------------------------------------------------------
# 7. the topic funnel (CF-0232)
# --------------------------------------------------------------------------

def funnel_of(batch_dir):
    """Section 7 as data, from the batch's stage artifacts (shared/runlog/funnel.py).

    The one section that does not come from the events: the events say when a
    stage ran, the artifacts say what it decided, and "compliance took three
    topics off the batch" is a decision. Without a batch directory - compute()
    called on an event list alone, as the tests and the runs table do - there
    are no artifacts to read and the funnel is simply unavailable."""
    return runlog.sibling("funnel").funnel(batch_dir)


def scores_of(batch_dir):
    """CF-0434: the score line of every video of the batch (shared/runlog/
    scores.py) - after the judge where it ran, else after QC; the line of a
    video the score stopped at 6b or at the Editor. Read from the artifacts
    like the funnel; `[]` without a batch directory. Never raises."""
    if not batch_dir:
        return []
    try:
        return _scores.collect(batch_dir)
    except Exception:                                       # noqa: BLE001
        return []


def no_waiting_of(batch_dir, data=None):
    """CF-0317: this run read against the rule that no stage waits for a human -
    which wait point each measured wait belongs to, and the code the automatic
    outcome should have written. Reads `waits()` above and measures nothing of
    its own. Never raises: a summary must not fail because a module beside it
    did."""
    try:
        return _no_waiting.audit(batch_dir, data=data)
    except Exception as e:                                  # noqa: BLE001
        return {"verdict": None, "error": f"{e.__class__.__name__}: {e}",
                "waits_count": 0, "codes": [], "unclassified": 0, "reads": []}


def stopcock_of(batch_dir, events=None):
    """CF-0322: the stop-cock verdict of the batch, from the same artifacts
    section 7 is read from. It is computed for every batch, not only a stopped
    one, so that the runs row can tell "the cock was up" from "nobody looked" -
    and it is silent in the rendered summary unless it actually came down."""
    return runlog.sibling("stopcock").verdict(batch_dir, events=events)


# --------------------------------------------------------------------------
# the reserve round after the frame judge (CF-0801, part of CF-0798)
# --------------------------------------------------------------------------

AFTER_JUDGE_CHECK = "reserve_after_judge"      # run_checks / run_plan.CONDITIONS
RUN_STATE_FILE = "run-state.json"               # run_executor.STATE_FILE


def _slots_ru(n):
    n = int(n)
    if n % 10 == 1 and n % 100 != 11:
        return f"{n} слот"
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return f"{n} слота"
    return f"{n} слотов"


def after_judge_decision(batch_dir):
    """`(holds, why)` of the plan's `reserve_after_judge` as the executor
    evaluated it for this batch (`run-state.json` -> `stages[].when.why`
    starting with the condition's name), or None when no stage asked it."""
    if not batch_dir:
        return None
    try:
        st = json.loads((Path(batch_dir) / RUN_STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    head = AFTER_JUDGE_CHECK + ": "
    for ss in ((st or {}).get("stages") or {}).values() if isinstance(st, dict) else []:
        w = ss.get("when") if isinstance(ss, dict) else None
        why = (w or {}).get("why") if isinstance(w, dict) else None
        if isinstance(why, str) and head in why:
            text = why[why.index(head) + len(head):].split("; {", 1)[0]
            return bool(w.get("holds")), text
    return None


def after_judge_line(batch_dir, f=None):
    """CF-0801: «добор после судьи: N слот(ов)» - the refills of the reserve
    round after the frame judge, from the funnel (01b records `at:
    frame_judge_refusal`) - or, with none, the reason the round did not run,
    as the executor recorded it. None (silent) on a batch whose plan never
    asked: every batch before CF-0802."""
    rows = _funnel.after_judge_rows(f) if f else []
    decision = after_judge_decision(batch_dir)
    if rows:
        swaps = ", ".join(f"{r['item']} вместо {(r.get('detail') or {}).get('replaced') or '?'}"
                          for r in rows)
        return f"добор после судьи: {_slots_ru(len(rows))} ({swaps})"
    if decision is None:
        return None
    holds, why = decision
    if holds:
        return (f"добор после судьи: 0 слотов - условие выполнено, но 01b не записал замену "
                f"({why})")
    return f"добор после судьи: не было - {why}"


# --------------------------------------------------------------------------
# 8. the YouTube quota of the run, by article (CF-0368)
# --------------------------------------------------------------------------

def quota_line(x):
    """CF-0368: what this run spent of the daily YouTube quota, split by
    article - scoring / footage feeds / footage search / supplement.

    The line is not built here. The hunter writes it into its `quota` event
    already finished, and the root only shows it: the contract of CF-0368 is
    "events only" - the root never opens `01-trend-hunter.json`, so the four
    articles are never re-derived on this side and cannot drift from the
    hunter's own arithmetic.

    None when the run left no `quota` event - a batch that spent nothing on
    YouTube, or one whose hunter stage predates CF-0368. Silence, not an empty
    heading and not a refusal: the same contract as `stopcock.headline`."""
    d = _loaded(x)
    for e in reversed(d.get("quota") or []):
        line = e.get("line")
        if isinstance(line, str) and line.strip():
            return line
    return None


# --------------------------------------------------------------------------
# 9. who answered the sieve flags of this batch (CF-0374)
# --------------------------------------------------------------------------

def sieve_answers_line(x):
    """CF-0374: how many sources of this batch the Footage Indexer could mark
    on the spot on `burned_text`/`on_topic`, how many it took out of the batch
    with a record instead, and where the answerer came from.

    The same contract as `quota_line` above, and deliberately the same
    mechanism rather than a second one: the line is built by the stage that
    knows what a sieve flag is, shipped finished inside its `sieve_answers`
    event, and printed here verbatim. The root never opens
    `01b-footage-index.json`, so the counts cannot drift from the sieve's own
    arithmetic.

    None when the batch left no `sieve_answers` event - a run whose indexer
    predates CF-0374, or one that never reached the sieve. Silence, not an
    empty heading and not a refusal: no answerer configured is a legal state
    (DoD 1, the run goes on), and the event itself is what says so."""
    d = _loaded(x)
    for e in reversed(d.get("sieve_answers") or []):
        line = e.get("line")
        if isinstance(line, str) and line.strip():
            return line
    return None


# --------------------------------------------------------------------------
# everything, and the Markdown
# --------------------------------------------------------------------------

def compute(batch_dir=None, events=None):
    d = load(batch_dir, events)
    _t = stage_times(d)
    _f = funnel_of(batch_dir)
    try:
        _aj = after_judge_line(batch_dir, _f)                   # CF-0801
    except Exception:                                       # noqa: BLE001
        _aj = None
    _mm = _memes.collect(batch_dir)                             # CF-0811: never raises
    return {"batch": (d["header"] or {}).get("batch") or _batch_name(batch_dir),
            "header": d["header"],
            "markup": runlog.markup_of(d["header"]),          # CF-0173
            "declared_stages": sorted({w["stage"] for w in d["stages"] if w["stage"]}),
            "machine_id": next((e.get("machine") for e in d["events"] if e.get("machine")), None),
            "times": _t, "binaries": binary_times(d),
            "gaps": gaps_summary(d), "gaps_line": gaps_line(d),
            "waits": waits(d), "waits_line": waits_line(d),          # CF-0252
            "operator": operator(d), "operator_line": operator_line(d),   # CF-0257
            "consistency": consistency(d, times=_t), "tokens": tokens(d),
            "windows": window_share(d), "resources": resources(d), "unattributed": unattributed(d),
            "funnel": _f,
            "after_judge_line": _aj,                                     # CF-0801
            "memes": _mm, "memes_line": _memes.line(_mm),                # CF-0811
            "scores": scores_of(batch_dir),                             # CF-0434
            "stopcock": stopcock_of(batch_dir, events=d["events"]),      # CF-0322
            "no_waiting": no_waiting_of(batch_dir, data=d),              # CF-0317
            "watchdog": _watchdog.detect(events=d["events"]),             # CF-0316
            "code_drift": runlog.drift_rows(                             # CF-0398
                d["events"], d.get("resets"), runlog.batch_channel(batch_dir) if batch_dir else None),
            "manual_resets": [runlog.reset_brief(r) for r in d.get("resets") or []],  # CF-0739
            "code_override": runlog.code_override_of(d["events"]),       # CF-0398
            "monitors": _monitors.of(d["events"]),                       # CF-0511
            "rerun": runlog.rerun_mode(d["events"]),                     # CF-0494
            "quota_line": quota_line(d),                                # CF-0368
            "sieve_answers_line": sieve_answers_line(d),                 # CF-0374
            "counts": {"events": len(d["events"]), "samples": len(d["samples"]),
                       "limits": len(d["limits"]), "usage_rows": len(d["usage"])}}


def _batch_name(batch_dir):
    if not batch_dir:
        return "?"
    bd = Path(batch_dir)
    return f"{bd.parent.name}/{bd.name}"


def _k(n):
    return runlog.sibling("usage")._k(n)


def _steps_present(times):
    steps = list(SUB_STEPS)
    for w in times["stages"]:
        for s in w["attempts"]:
            if s not in steps:
                steps.append(s)
    for v in times["videos"]:
        for s in v["attempts"]:
            if s not in steps:
                steps.append(s)
    return steps


def _att(att, step):
    a = att.get(step)
    if not a:
        return "-"
    return f"{a['attempts']}" + (f" ({a['failed']} failed)" if a["failed"] else "")


def _pct_or(v, estimate=False):
    if v is None:
        return "?"
    return f"{'~' if estimate else ''}{v:g} %"


def _missing_line(W):
    """CF-0175 item 1: name the readings that measured nothing, instead of letting
    the column quietly stand on fewer readings than the header claims."""
    m = W.get("missing") or {}
    bits = []
    for w in ("five_hour", "seven_day"):
        n = m.get(w) or 0
        if n:
            bits.append(f"{n} carry no `{w}` block (that column stands on "
                        f"{W['readings'] - n} of them)")
    if m.get("unusable"):
        bits.append(f"{m['unusable']} have no usable timestamp or params at all")
    if not bits:
        return None
    return (f"Of the {W['readings'] + (m.get('unusable') or 0)} `limits` readings, "
            + "; ".join(bits) + ". Claude Code omits a window block when it has "
            "nothing to report for that window; the rest of the reading is still used.")


def _hdr_bits(h):
    if not h or "error" in h:
        return "header: missing"
    git = (h.get("git") or {}).get("root") or {}
    commit = (git.get("commit") or "?")[:7] + ("+dirty" if git.get("dirty") else "")
    m = h.get("machine") or {}
    models = h.get("models") or {}
    subs = models.get("subagents") or {}
    mods = f"operator {models.get('operator') or '?'}"
    if models.get("subagent_default"):
        mods += f", subagents {models['subagent_default']}"
    if subs:
        mods += " (" + ", ".join(f"{k}: {v}" for k, v in sorted(subs.items())) + ")"
    return (f"commit {commit} · version {h.get('version') or '?'} · "
            f"machine {m.get('cpu') or m.get('platform') or '?'}, {m.get('ram_gb') or '?'} GB, "
            f"{m.get('gpu') or 'no gpu'} · models: {mods}")


def _markup_line(c):
    """CF-0173: which generation of stage markup recorded this run. Sections 1, 4
    and 5 split the run by the stage markers, so two runs marked up differently
    cannot be compared stage by stage - and the line has to be in the summary
    itself, because that is what a reader has in front of them."""
    m = c.get("markup") or runlog.MARKUP_LEGACY
    if m >= runlog.MARKUP:
        return (f"stage markup: generation {m} (current). Sections 1, 4 and 5 are comparable with "
                f"other generation-{m} runs; a generation-{runlog.MARKUP_LEGACY} run kept the "
                f"pre-stage pool work in `between` and cannot be compared to this one stage by stage.")
    return (f"stage markup: generation {m} - recorded before CF-0173, so the pool work that runs "
            f"before the first stage carries no marker and falls into `between` in sections 1, 4 and 5. "
            f"Those sections are **not** comparable with a generation-{runlog.MARKUP} run. "
            f"The attempts columns of section 1 are an upper bound, not a count: a generation-"
            f"{runlog.MARKUP_LEGACY} run also predates CF-0177, so its `video-editor` scripts carry "
            f"no attempt numbers and every call of a sub-step counts as one attempt (CF-0178).")


def render(batch_dir=None, events=None, data=None):
    """The Markdown text of RUN_SUMMARY.md. First line: the gaps."""
    c = data or compute(batch_dir, events)
    T, B, G, K, W, R, U = (c["times"], c["binaries"], c["gaps"], c["tokens"], c["windows"],
                           c["resources"], c["unattributed"])
    F = c.get("funnel")
    WT = c.get("waits") or {"count": 0, "seconds": 0.0, "waits": []}
    OPR = c.get("operator") or {"count": 0, "seconds": 0.0, "idle_s": 0.0, "idle": []}
    CN = c.get("consistency") or {"ok": True, "violations": [], "checks": []}
    SC = c.get("stopcock")
    L = [c["gaps_line"], "",
         _funnel.headline(F), ""]
    _mm_line = c.get("memes_line")
    if _mm_line:                          # CF-0811: silent without 03 and 05 in the batch
        L += [_mm_line, ""]
    _score_lines = _scores.lines(c.get("scores") or [])
    if _score_lines:                          # CF-0434: silent on a batch nothing scored
        L += _score_lines + [""]
    _sc_line = _stopcock.headline(SC)
    if _sc_line:                                          # CF-0322: silent on a healthy run
        L += [_sc_line, ""]
    _aj_line = c.get("after_judge_line")
    if _aj_line:                          # CF-0801: silent unless the plan asked the round
        L += [_aj_line, ""]
    _q_line = c.get("quota_line")
    if _q_line:                                           # CF-0368: silent without a `quota` event
        L += [_q_line, ""]
    _sa_line = c.get("sieve_answers_line")
    if _sa_line:                            # CF-0374: silent without a `sieve_answers` event
        L += [_sa_line, ""]
    NW = c.get("no_waiting")
    L += [c.get("waits_line") or ""]
    _nw_line = _no_waiting.headline(NW)
    if _nw_line:                                          # CF-0317: silent on a run that never stood
        L += [_nw_line]
    _cd_line = runlog.drift_headline(c.get("code_drift") or [], c.get("code_override"))
    if _cd_line:                                # CF-0398: silent while the code stood still
        L += [_cd_line]
    WD = c.get("watchdog") or []
    _wd_line = _watchdog.headline(WD)
    if _wd_line:                                # CF-0316: silent unless an operation was killed
        L += [_wd_line]
    L += [_monitors.headline(c.get("monitors"))]  # CF-0511: never silent - not run / green / red
    L += [
         "",
         c.get("operator_line") or "", "",
         f"# RUN_SUMMARY {c['batch']}", "",
         f"accounting: {U['accounting']} (unattributed {_hms(U['seconds'])} = {U['pct']} % of live; "
         f"flag above {INCOMPLETE_PCT:g} %)", "",
         f"wall {_hms(T['wall']['seconds'])} ({T['wall']['start']} .. {T['wall']['end']}) · "
         f"live {_hms(T['live_s'])} (wall minus gaps {_hms(T['gaps_s'])}) · "
         f"busy {_hms(T['busy_s'])} (scripts + binaries) · "
         f"operator {_hms(T.get('operator_s') or 0.0)} (+ {_hms(T.get('idle_s') or 0.0)} standing "
         f"still) · "
         f"waiting for a human {_hms(T.get('waits_s') or 0.0)}"
         f" ({_pct(T.get('waits_s') or 0.0, T['wall']['seconds'])} % of the wall)  ",
         _hdr_bits(c["header"]), "",
         _markup_line(c), "",
         "Generated by `runlog summary` from RUN_EVENTS.jsonl "
         f"({c['counts']['events']} events, {c['counts']['samples']} samples, "
         f"{c['counts']['limits']} limits readings, {c['counts']['usage_rows']} usage rows). "
         "Do not edit.", ""]
    # 1
    steps = _steps_present(T)
    L += ["## 1. Time by stage and by video, attempts per sub-step", "",
          "| stage | wall | busy | operator | idle | gaps | waiting | videos | scripts | "
          + " | ".join(steps) + " |",
          "|---|---|---|---|---|---|---|---|---|" + "---|" * len(steps)]
    for w in T["stages"]:
        L.append(f"| {w['stage']} | {_hms(w['wall_s'])} | {_hms(w['busy_s'])} | "
                 f"{_hms(w.get('operator_s') or 0.0)} | {_hms(w.get('idle_s') or 0.0)} | "
                 f"{_hms(w['gaps_s'])} | "
                 f"{_hms(w.get('waits_s') or 0.0)} | "
                 f"{len(w['videos'])} | {w['scripts']} | " + " | ".join(_att(w["attempts"], s) for s in steps) + " |")
    if not T["stages"]:
        L.append("| (no stage markers) | | | | | | | | | " + " | ".join("-" for _ in steps) + " |")
    L += ["", "`waiting` (CF-0252) is the time the batch stood still *after* that stage window with "
          "no script and no binary running - it waited for a human, and it is not part of any "
          "stage's busy. `busy` is the union of the stage's own intervals clipped to its window, so "
          "`busy <= wall` always; a stage busier than its own wall used to be how an interval "
          "without its `done` event looked.",
          "", f"`operator` (CF-0257) is the rest of the stage's own window: the stage is run by an "
          f"LLM operator that reads, thinks and writes JSON between its script calls, and that time "
          f"belongs to the stage as much as `busy` does. `idle` is the part of it the operator spent "
          f"standing still - a silence of {IDLE_MIN_S / 60:g} min or more inside the window with no "
          f"script and no binary event in it, found by the gap detector (CF-0108) over the work "
          f"events. The two are disjoint, and `busy + operator + idle + gaps <= wall` by "
          f"construction."]
    L.append("")
    if T["videos"]:
        L += ["| stage | video | wall | busy | " + " | ".join(steps) + " | attempts | failed |",
              "|---|---|---|---|" + "---|" * len(steps) + "---|---|"]
        for v in T["videos"]:
            L.append(f"| {v['stage']} | {v['video']} | {_hms(v['wall_s'])} | {_hms(v['busy_s'])} | "
                     + " | ".join(_att(v["attempts"], s) for s in steps)
                     + f" | {v['attempts_total']} | {v['failed']} |")
        n = len(T["videos"])
        L.append("")
        L.append(f"{n} video(s): mean wall {_hms(sum(v['wall_s'] for v in T['videos']) / n)}, "
                 f"mean attempts {round(sum(v['attempts_total'] for v in T['videos']) / n, 1)} per video.")
    else:
        L.append("No script event carries a video slug: per-video times are not available.")
    L.append("")
    # CF-0252: the intervals with no terminal event, named rather than stretched
    OP = T.get("open") or {"count": 0, "items": []}
    if OP["count"]:
        L.append(f"{OP['count']} interval(s) ({OP['scripts']} script(s), {OP['children']} binary call(s)) "
                 f"never got a `done` or `failed` event. Their length is unknown, so each one is "
                 f"counted only up to the last event of its own subtree ({_hms(OP['evidence_s'])} "
                 f"together) and the tail after that is counted nowhere:")
        L.append("")
        for it in OP["items"][:10]:
            who = "/".join(q for q in (it["stage"], it["video"], it["step"]) if q)
            L.append(f"- {it['name'] or it['kind']} ({who}) started {it['start']}, last evidence "
                     f"{it['last_evidence']} -> {_hms(it['seconds'])} counted")
        if OP["count"] > 10:
            L.append(f"- ... {OP['count'] - 10} more")
        L.append("")
    L.append("Invariants (CF-0252): " + "; ".join(CN["checks"]) + " - "
             + ("**hold**." if CN["ok"] else "**BROKEN**: " + "; ".join(CN["violations"])
                + ". A broken invariant is a defect of this generator, not a slow stage."))
    for note in CN.get("notes") or []:
        L.append("")
        L.append(note + ".")
    L.append("")
    # 2
    L += ["## 2. External binaries vs the Python wrapper", ""]
    tot = B["total"]
    L.append(f"Scripts busy {_hms(tot['scripts_s'])} = binaries {_hms(tot['children_s'])} "
             f"+ Python wrapper {_hms(tot['wrapper_s'])}"
             + (f" ({_pct(tot['wrapper_s'], tot['scripts_s'])} % wrapper)." if tot['scripts_s'] else "."))
    L.append("")
    if B["tools"]:
        L += ["| tool | calls | time | failed |", "|---|---|---|---|"]
        for t, v in B["tools"].items():
            L.append(f"| {t} | {v['calls']} | {_hms(v['seconds'])} | {v['failed']} |")
        nest = B.get("nesting") or {}
        if nest.get("explicit") or nest.get("inferred"):
            n = nest.get("explicit", 0) + nest.get("inferred", 0)
            L += ["", f"Calls and time count leaf calls only: {n} wrapper call(s) around another "
                      f"call left out (CF-0160)"
                      + (f"; {nest['inferred']} of them recognised by span (same process, same parent, "
                         f"wholly containing a shorter call) - this journal predates recorded nesting."
                         if nest.get("inferred") else ".")]
        L += ["", "| stage | scripts | binaries | wrapper | tools |", "|---|---|---|---|---|"]
        for st, v in B["by_stage"].items():
            tl = ", ".join(f"{t} {_hms(q['seconds'])}" for t, q in v["tools"].items()) or "-"
            L.append(f"| {st} | {_hms(v['scripts_s'])} | {_hms(v['children_s'])} | {_hms(v['wrapper_s'])} | {tl} |")
    else:
        L.append("No `child` events: no external binary was recorded (or the scripts do not use runlog.child yet).")
    L.append("")
    # 3
    L += ["## 3. Gaps and waiting for a human", ""]
    if G["gaps"]:
        for g in G["gaps"]:
            ev = g.get("evidence") or {}
            why = []
            if ev.get("limit_hits"):
                why.append(f"limit-hit x{len(ev['limit_hits'])}")
            if ev.get("markers"):
                why.append("transcript marker " + ", ".join(m.get("ts", "?") for m in ev["markers"]))
            if ev.get("idle_exit"):               # CF-0377: the run stood, the machine did not stop
                why.append("the run stood still: the sampler found it idle for "
                           f"{_hms(_sampler_idle_s())} and left "
                           f"({ev['idle_exit'].get('ts')}, CF-0339), so nothing was left to tick. "
                           "This is a parked run - a wait for a human, or a batch nobody closed - "
                           "not a machine that went quiet")
            if ev.get("watchdog"):                # CF-0377
                w = ev["watchdog"]
                why.append(f"the watchdog took down {w.get('stage') or '?'}/{w.get('step') or '?'}"
                           f"{(' on ' + str(w.get('source'))) if w.get('source') else ''} as "
                           f"`{w.get('code')}` after {_hms(w.get('silent_s') or 0)} of silence "
                           f"(ceiling {_hms(w.get('ceiling_s') or 0)}, CF-0316): the run lost one "
                           "operation here, it was not hung")
            L.append(f"- {g['start']} .. {g['end']} {_hms(g['seconds'])} **{g['cause']}** "
                     f"after '{g.get('before')}' before '{g.get('after')}'"
                     + (f" ({'; '.join(why)})" if why else ""))
        L += ["", "A gap named `idle_exit` or `<step>_timeout` read its cause off the events on "
              "its own boundaries (CF-0377): those silences are known debt, not a hang. `unknown` "
              "is the one that is a finding."]
    else:
        L.append("No gap longer than 10 min.")
    L.append("")
    if WT["waits"]:
        for q in WT["waits"]:
            nxt = f", next stage {q['next_stage']}" if q.get("next_stage") else ""
            dup = f", {_hms(q['in_gap_s'])} of it already counted as a gap" if q.get("in_gap_s") else ""
            L.append(f"- stage **{q['after_stage']}** waits for a human since {q['since']}, "
                     f"{q['minutes']:g} min ({q['start']} .. {q['end']}{nxt}{dup})")
        L += ["", f"A wait is a silence of at least {WAIT_MIN_S / 60:g} min between a `stage-done` "
              "and the next `stage-start` with no script and no binary inside it (CF-0252). The gap "
              "detector cannot see these: the sampler ticks every few seconds through a wait, so "
              "nothing about the events is silent. This is the batch waiting for the operator - a "
              "review, an answer, a fix to the code - and it belongs to no stage's busy time."]
    else:
        L.append(f"No stage waited for a human longer than {WAIT_MIN_S / 60:g} min.")
    L.append("")
    # 4
    L += ["## 4. Tokens by stage x model x role", ""]
    if K["rows"]:
        L += ["| stage | model | role | calls | input | cache_write | cache_read | output | thinking | total |",
              "|---|---|---|---|---|---|---|---|---|---|"]
        for r in K["rows"]:
            u = r["usage"]
            L.append(f"| {r['stage']} | {r['model'] or '?'} | {r['role']} | {r['calls']} | {_k(u['input'])} | "
                     f"{_k(u['cache_write'])} | {_k(u['cache_read'])} | {_k(u['output'])} | {_k(u['thinking'])} | "
                     f"{_k(u['input'] + u['cache_write'] + u['cache_read'] + u['output'])} |")
        for st, tt in K["by_stage"].items():
            L.append(f"| **= {st}** | | | {tt['calls']} | {_k(tt['input'])} | {_k(tt['cache_write'])} | "
                     f"{_k(tt['cache_read'])} | {_k(tt['output'])} | {_k(tt['thinking'])} | **{_k(tt['total'])}** |")
        t = K["total"]
        L += ["", f"TOTAL {_k(t['total'])} tokens, {t['calls']} calls: fresh {_k(t['fresh'])} ({t['fresh_pct']} %) "
              f"= input + cache_write + output; cache_read {_k(t['cache_read'])} ({t['cache_read_pct']} %). "
              f"Usage generation {K['computed']}."]
        silent = [s for s, tt in K["by_stage"].items() if not tt["calls"]]
        if silent:
            L += ["", f"`= {'`, `'.join(silent)}` at zero: the markers declare the stage and it spent "
                  "no tokens (CF-0173) - not the same thing as a stage that never ran, which has no "
                  "row here at all."]
        if K["videos"]:
            L += ["", "Per video, inside the stage that worked on it:", "",
                  "| stage | video | calls | total | of the stage |", "|---|---|---|---|---|"]
            for v in K["videos"]:
                st = K["by_stage"].get(v["stage"]) or {}
                share = _pct(v["total"], st.get("total") or 0)
                L.append(f"| {v['stage']} | {v['video'] or '- no slug -'} | {v['calls']} | "
                         f"{_k(v['total'])} | {share} % |")
            L += ["", "A call belongs to the slug whose stretch of the stage contains it (CF-0174): "
                  "a slug holds the floor from its first script or child event until the first event "
                  "of the next slug, and the last one to the end of the stage. `- no slug -` is the "
                  "part of the stage outside every stretch - shared setup before the first slug, "
                  "a step that names no video. The slug is whatever the stage's events carry: a "
                  "finished video under `video-editor`, a source clip under `footage-indexer`."]
    else:
        manual = "run `runlog usage <batch> --write` (CF-0109) and re-run `runlog summary`."
        L.append(f"No `usage` events: {K['error']}. {manual[0].upper()}{manual[1:]}" if K.get("error")
                 else f"No `usage` events: {manual}")
    L.append("")
    # 5
    L += ["## 5. Share of the subscription windows", ""]
    if W["note"]:
        L.append(f"5-hour: ? · 7-day: ? - {W['note']}.")
    else:
        L.append(f"Run: 5-hour {_pct_or(W['run']['five_hour'])} · 7-day {_pct_or(W['run']['seven_day'])} "
                 f"({W['readings']} readings).")
        L += ["", "| stage | 5-hour | 7-day | readings | chain |", "|---|---|---|---|---|"]
        for st, v in W["stages"].items():
            est = is_estimate(v)
            L.append(f"| {st} | {_pct_or(v['five_hour'], est)} | {_pct_or(v['seven_day'], est)} | "
                     f"{v['readings']} | {v['chain'] or '-'} |")
        if any(is_estimate(v) for v in W["stages"].values()):
            L += ["", f"`~` marks an estimate (CF-0175): some part of the share rests on a chain "
                  f"of {ESTIMATE_CHAIN} readings or fewer - one difference of two readings - and "
                  "the readings sit on a whole-percent grid, so it carries about +-1 pp on values "
                  "that are themselves a few pp. Do not rank stages by these numbers; the reliable "
                  "post-stage signal is tokens (section 4). `chain` is the shortest chain a part of "
                  "the number came from (a stage that ran twice sums two chains), `readings` the "
                  "total behind it; a long chain means the statusline kept refreshing inside the "
                  "stage, i.e. the number was measured rather than bracketed."]
    if not W["note"] and W["readings"] and (W.get("missing") or {}).get("five_hour") == W["readings"]:
        L += ["", f"No `five_hour` at all (CF-0230): none of the {W['readings']} readings carries a "
              "5-hour block, so the 5-hour column is `?` by absence of data, not a zero."]
    miss = _missing_line(W)
    if miss:
        L += ["", miss]
    L.append("")
    # 6
    L += ["## 6. CPU / memory / GPU by stage", "",
          f"Verdict: hardware-bound when mean pipeline CPU >= {HW_BOUND_CPU_PCT:g} % of all cores or "
          f"mean GPU >= {HW_BOUND_GPU_PCT:g} %; waiting when both <= {WAITING_PCT:g} %; mixed in between.", "",
          "| stage | samples | cpu total mean/max | cpu pipeline mean/max | rss max | mem used max | gpu mean/max | verdict |",
          "|---|---|---|---|---|---|---|---|"]

    def rrow(name, s):
        f = lambda v: "?" if v is None else f"{v:g}"  # noqa: E731
        return (f"| {name} | {s['samples']} | {f(s['cpu_total_mean'])}/{f(s['cpu_total_max'])} % | "
                f"{f(s['cpu_pipeline_mean'])}/{f(s['cpu_pipeline_max'])} % | {f(s['rss_max_mb'])} MB | "
                f"{f(s['mem_used_max_mb'])} MB | {f(s['gpu_mean'])}/{f(s['gpu_max'])} % | **{s['verdict']}** |")
    for st, s in R["stages"].items():
        L.append(rrow(st, s))
    L.append(rrow("= run", R["run"]))
    if not R["run"]["samples"]:
        L += ["", "No `sample` events: the sampler (CF-0108) did not run for this batch."]
    L.append("")
    # the wall, part by part, and what is left over (CF-0252, CF-0257)
    PT = (CN.get("parts") or {})
    L += ["## Where the wall went", "",
          f"{_hms(U['seconds'])} of live {_hms(U['live_s'])} ({U['pct']} %) falls outside every "
          f"stage window and outside every named wait: nobody records what the batch was doing "
          f"there -> accounting: **{U['accounting']}** (the flag fires above "
          f"{INCOMPLETE_PCT:g} % of live).", ""]
    if PT:
        L += ["| part | time | what it is |", "|---|---|---|",
              f"| gaps | {_hms(PT.get('gaps_s'))} | no event of any kind for "
              f"{runlog.sibling('gaps').MIN_GAP_S / 60:g} min or more - the usage limit, or a "
              f"finding (CF-0108) |",
              f"| busy | {_hms(PT.get('busy_s'))} | a script or a binary was running (CF-0110) |",
              f"| waiting for a human | {_hms(PT.get('waits_s'))} | between two stages, nothing "
              f"running for {WAIT_MIN_S / 60:g} min or more (CF-0252) |",
              f"| operator | {_hms(PT.get('operator_s'))} | inside a stage, its LLM operator "
              f"between script calls (CF-0257) |",
              f"| operator idle | {_hms(PT.get('idle_s'))} | inside a stage, standing still for "
              f"{IDLE_MIN_S / 60:g} min or more (CF-0257) |",
              f"| unattributed | {_hms(PT.get('unattributed_s'))} | outside every stage window - "
              f"the orchestrator between stages, uninstrumented |",
              f"| = wall | {_hms(PT.get('wall_s'))} | |", "",
              "The parts are taken in that order and each gets only what the earlier ones left, so "
              "no second of the run is counted twice and the six add up to the wall exactly - the "
              "last invariant of section 1 checks it."]
    if OPR["count"]:
        L += ["", f"The operator stood still {OPR['count']} time(s) for {_hms(OPR['idle_s'])} "
              f"together. A stretch like this is *not* work the summary can claim for the stage: "
              f"on 2026-09-19T0116Z the footage-indexer operator finished an `ingest` at 14:05Z and "
              f"then wrote nothing at all for 1h02m36s, and its `stage-done` came only after "
              f"somebody looked at the batch.", ""]
        for q in OPR["idle"]:
            L.append(f"- {q['start']} .. {q['end']} {_hms(q['seconds'])} in `{q['stage'] or '?'}`, "
                     f"cause={q['cause']}, after '{q['before']}' before '{q['after']}'")
    if U["intervals"]:
        L += ["", f"Unattributed intervals longer than {UNATTRIBUTED_MIN_S:g} s:", ""]
        for iv in U["intervals"]:
            L.append(f"- {iv['start']} .. {iv['end']} {_hms(iv['seconds'])} after '{iv['after']}' before '{iv['before']}'")
    if U["incomplete"]:
        L += ["", f"More than {INCOMPLETE_PCT:g} % unattributed: the time between stages is not "
              "instrumented (the orchestrator writes no event of its own), or a stage ran scripts "
              "outside its own `stage-start` .. `stage-done` window - see CF-0107 / CF-0257."]
    L.append("")
    # 7
    L += _funnel.render(F, number=7)
    L += _stopcock.render(SC)                             # CF-0322: [] unless the cock came down
    L += _no_waiting.render(NW)                           # CF-0317: [] unless the run stood still
    L += _watchdog.render(WD)                             # CF-0316: [] unless an operation was killed
    return "\n".join(L)


def write(batch_dir, events=None):
    """Write <batch_dir>/RUN_SUMMARY.md; returns its path. Never raises into a run."""
    bd = Path(batch_dir)
    text = render(bd, events)
    path = bd / SUMMARY_FILE
    tmp = path.with_suffix(".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    return path


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="runlog summary",
                                 description="RUN_SUMMARY.md from RUN_EVENTS.jsonl (CF-0110)")
    ap.add_argument("--batch", default=None)
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    ap.add_argument("--json", action="store_true", help="print the sections as JSON")
    ns = ap.parse_args(sys.argv[1:] if argv is None else argv)
    bdir = runlog.find_batch_dir(ns.batch)
    if bdir is None or not runlog.events_path(bdir).is_file():
        sys.stderr.write(f"runlog summary: error: no batch directory with {runlog.EVENTS_FILE}"
                         f"{f' at {bdir}' if bdir else ''} (use --batch DIR)\n")
        return 2
    if ns.json:
        print(json.dumps(compute(bdir), ensure_ascii=False, indent=2, default=str))
        return 0
    if ns.stdout:
        sys.stdout.write(render(bdir))
        return 0
    print(write(bdir))
    return 0


if __name__ == "__main__":
    sys.exit(main())
