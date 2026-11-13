#!/usr/bin/env python3
"""CF-0203: the mechanical decisions of a batch that the operator used to make
by reading, as commands the run plan can name and the executor can run.

    python3 shared/run_checks.py reserve-refill <batch>
    python3 shared/run_checks.py judge-set <batch>
    python3 shared/run_checks.py reserve-after-judge <batch>
    <indexer python> shared/run_checks.py captions-stale     --indexer-dir DIR <shots.json>...
    <indexer python> shared/run_checks.py captions-remeasure --indexer-dir DIR <shots.json>...

**reserve-refill** - the named condition `reserve_refill` of `run_plan.py`
(docs/pipeline.md, "When a topic is lost after the cut (CF-0306)"): N = the
Researcher's refusals (`03-content-researcher.json` -> `skipped[]`) whose slot
`01b -> reserve_substitution` has not answered yet (CF-0645: the plan asks it
again after the supplement's plan check - the late round), M = what
the batch may still substitute (`01b-footage-index.json` ->
`reserve_substitution.remaining[]`; read through the stop-cock's own reader,
`stopcock._remaining_reserve`, so the two can never disagree about whether a
reserve is left - including the re-run whose `01b` is its parent's and can
refill nothing). Exit 0 when N > 0 and M > 0, 1 otherwise, 2 on a bad call;
one line saying N and M either way.

**reserve-after-judge** - the named condition `reserve_after_judge` (CF-0801,
part of CF-0798, the user's yes of 2026-10-18; docs/pipeline.md, "When the
frame judge refuses a video (CF-0798)"): the frame judge refused topics
(`06-frame-judge.json`: no video of the topic passed the gate), the slots
carried short (topics with a passing video < the channel's slots,
`scope.max_titles_per_batch` read through `funnel.target_of`), the reserve
still holds a topic (`stopcock._remaining_reserve`, the same reader as
`reserve_refill`), no round ran yet (no `01b -> reserve_substitution` record
with `at: frame_judge_refusal` - one round only), and the round fits in the
time left (the guard: the round's length, from this batch's own stage times or
2 h, against the end of the YouTube quota day and the factory's next planned
batch start). Exit 0 holds, 1 not, 2 bad call; one line with the decision and
why either way - a skipped round names its reason.

**repair_after_judge / repair_judge_pending** (CF-0881) - the named conditions
of the repair round after the frame judge, evaluated by shared/judge_repair.py
(its own CLI: `judge_repair.py candidates|pending <batch>`): a refused video
with its defect in one or two blocks and no request written yet; a re-rendered
video of that round the judge owes verdicts on.

**judge-set** - the named conditions `judge_candidates` and `nothing_to_judge`
(CF-0707): whether `05-video-editor.json` names a video the frame judge owes a
verdict on, by the gate's own predicate (`scripts/frame_judge_gate.py`
`batch_judge_set`). Exactly one of the two holds for a batch with a readable
`05`; with no `05`, `judge_candidates` holds (the judge's SKILL closes with a
note). Exit 0 when there is a video to judge, 1 when there is none, 3 when
there is no readable `05`; one line either way.

**write_candidates / nothing_to_write** (CF-0763) - the named conditions of the
LLM stage `content-researcher` and of the machine stage `content-researcher-empty`:
whether `02` and `01b` hand the Researcher any topic, by the writer's own
predicate (`scripts/researcher_nothing_to_write.py` `nothing_to_write`; its
`--check` is the CLI). Exactly one holds on any batch.

**captions-stale** - the pool's caption-crop freshness as an exit code.
`caption_cache.py <indexes>` prints the stale report but exits 0 either way
(its `on_exit 1` in the plan could never fire); this runs the same
`caption_cache.survey()` and exits 1 when anything is stale, printing the
agent's own complaint. **captions-remeasure** takes that stale list itself and
runs `remeasure_captions.py` over exactly those indexes - the line the
operator used to copy from the complaint. Both run under the Footage Indexer's
interpreter and import its code from `--indexer-dir`: the rule stays the
agent's, only the reading of the printed line moves here.

CF-0819 (Tech `2026-10-20T0831Z`: a two-hour remeasure of the whole pool timed
out, exit 5, the batch got no topics): the pool is never re-measured in bulk.
`captions-remeasure` gives `remeasure_captions.py --stale-only` a budget of
`REMEASURE_BUDGET` seconds and `--set-aside-rest`; whatever is still stale
after it - the budget ran out, the child was stopped at `REMEASURE_TIMEOUT`,
it crashed, a probe failed - is set aside here (`caption_cache.set_aside`:
the stale crop moves to `crop_bottom_set_aside`, nothing is measured, the cut
gives that shot a fresh `--auto-crop`). The pool then reads current and the
batch goes on. Exit 0: nothing was set aside; exit `SET_ASIDE_EXIT` (6): stale
crops were set aside - the plan takes 6 as ok and its `note_on_exit` puts the
warning into pool-maintenance's `stage-done` note; the loud line itself
(`caption_cache.set_aside_warning`) is on stderr, in the step's log. Exit 2: the
Footage Indexer at `--indexer-dir` predates CF-0819 (no `set_aside`) - a pin
mismatch, said in one line instead of an AttributeError mid-batch.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent

RESEARCHER_FILE = "03-content-researcher.json"
INDEX_FILE = "01b-footage-index.json"
COMPLIANCE_FILE = "02-compliance-checker.json"
# CF-0819: remeasure_captions.py takes ~8 s a shot, so a moved caption key over
# the whole pool is hours (2026-10-20: a two-hour ceiling hit, the batch lost
# every topic). The pool is never re-measured in bulk: five minutes of
# remeasure, the rest set aside (a fresh --auto-crop at cut time). The ceiling
# is the budget plus room for the shot in flight and the set-aside writes.
REMEASURE_BUDGET = 300
REMEASURE_TIMEOUT = REMEASURE_BUDGET + 300
# captions-remeasure: stale crops were set aside, not re-measured (ok for the
# plan, with a note).
SET_ASIDE_EXIT = 6
# What caption_cache must have for the CF-0819 path (an older pin has none).
SET_ASIDE_API = ("set_aside", "set_aside_warning", "SET_ASIDE_KEY", "VALUE_KEY")


def _read(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def _stopcock():
    p = str(HERE / "runlog")
    if p not in sys.path:
        sys.path.insert(0, p)
    import stopcock  # noqa: PLC0415
    return stopcock


def _answered(A, batch=None):
    """The topics whose free slot the CF-0306 loop has already answered -
    with a substitute or with `reserve_exhausted` - in `01b ->
    reserve_substitution` (`replaced` of `substitutions[]` and `unmatched[]`).
    The indexer's `--reserve-for` never answers a loss twice
    (`ingest_batch.substitute_reserve`), so these are not N. CF-0781: the
    block is read through the stop-cock's reader - the previous run's block
    a `rerun-from` left in `01b` answers nothing for the re-run."""
    sub, _ = _stopcock().substitution_block(A, batch)
    if not isinstance(sub, dict):
        return set()
    return {r.get("replaced") for key in ("substitutions", "unmatched")
            for r in sub.get(key) or [] if isinstance(r, dict) and r.get("replaced")}


def reserve_refill(batch):
    """(holds, why): N > 0 refused topics whose slot is still unanswered and
    M > 0 left in the reserve.

    CF-0645: the plan asks this twice - after the Researcher (the CF-0306
    loop) and again after the plan check that follows the thin-pool
    supplement, where a deferred script can still fall to `plan_unassembled`
    (the late round). A refusal the first round already refilled is not
    counted the second time, so the late round runs only for a slot lost
    after it (or a substitute the Researcher refused in it)."""
    counts = refill_counts(batch)
    if counts is None:
        return False, f"no {RESEARCHER_FILE}: N unknown, nothing to refill"
    open_, left, why, done = counts
    n, m = len(open_), len(left)
    return (n > 0 and m > 0), (f"N={n} refused" + (f" (+{done} already refilled)" if done else "")
                               + f", M={m} in reserve ({why})")


def refill_counts(batch):
    """`(open refusals, reserve left, why, already refilled)` of `reserve_refill`,
    or None without a readable `03`. CF-0882 reads the same numbers to decide
    how many topics from below the shortlist a round needs (N - M)."""
    batch = Path(batch)
    cr = _read(batch / RESEARCHER_FILE)
    if not isinstance(cr, dict):
        return None
    refused = [s for s in cr.get("skipped") or [] if s is not None]
    A = {name: _read(batch / name) for name in (RESEARCHER_FILE, INDEX_FILE, COMPLIANCE_FILE)}
    A = {k: v for k, v in A.items() if v is not None}
    answered = _answered(A, batch)
    open_ = [s for s in refused if not (isinstance(s, dict) and s.get("topic_id") in answered)]
    left, why = _stopcock()._remaining_reserve(A, batch)
    return open_, left, why, len(refused) - len(open_)


# --------------------------------------------------------------------------
# CF-0801: the reserve round after the frame judge (CF-0798)

JUDGE_FILE = "06-frame-judge.json"
JUDGE_AT = "frame_judge_refusal"          # ingest_batch.JUDGE_AT (CF-0799)
JUDGE_PASS = "pass"
JUDGE_INCOMPLETE_CODE = "frame_judge_failed"
# What the topic count is compared with: the slots the cut carries
# (`scope.max_titles_per_batch`, `funnel.target_of` -> `max_titles`), not the
# ready-video target (`ready`, 3 on Reel). The user's yes of 2026-10-18 was
# given on Reel 0841Z, where 3 videos were ready against a ready target of 3
# and whalefall's slot went unanswered with -009 left in reserve: a slot paid
# for and lost to the judge is refilled while the cut's slots are not full.
# The ready target is the fallback for a channel with no slot count.
TARGET_FIELD = "max_titles"
TARGET_FALLBACK = "ready"
# The guard (CF-0801, the driver's decision on the run window: the schedule
# window is the start time, not a duration cap; the user accepted +1-2 h).
ROUND_DEFAULT_S = 2 * 3600
# The stages one round repeats, as `(stage id prefixes, fallback prefixes)`:
# the duration of the latest finished stage whose id starts with a prefix
# (the `-late` round included), else with a fallback one.
ROUND_STAGES = ((("footage-indexer-reserve",), ()),
                (("content-researcher-reserve",), ("content-researcher",)),
                (("compliance-scripts",), ()),
                (("video-editor",), ()),
                (("frame-judge",), ()))
RUN_STATE = "run-state.json"
_SCRIPT_SUFFIX = re.compile(r"-script\d+$")


def judge_outcome(batch):
    """`(refused, passed, ran)` of `06-frame-judge.json` by topic - the
    footage-indexer's own reading (`ingest_batch.judge_refusals`, CF-0799):
    a topic is refused when none of its videos passed; its id is the row's
    `topic_id`, else `03`'s `script_id` -> `topic_id`, else the script id
    without its `-scriptN`. `refused` is `[{topic_id, script_id, slug,
    reason_code}]` in `06`'s order, `passed` the set of topics with a video
    through the gate."""
    batch = Path(batch)
    fj = _read(batch / JUDGE_FILE)
    if not isinstance(fj, dict):
        return [], set(), False
    cr = _read(batch / RESEARCHER_FILE)
    by_script = {s["script_id"]: s["topic_id"] for s in (cr or {}).get("scripts") or []
                 if isinstance(s, dict) and s.get("script_id") and s.get("topic_id")}
    passed, out, seen = set(), [], set()
    for v in fj.get("videos") or []:
        if not isinstance(v, dict):
            continue
        sid = v.get("script_id")
        tid = v.get("topic_id") or by_script.get(sid) or (_SCRIPT_SUFFIX.sub("", sid) if sid else None)
        if not tid:
            continue
        if v.get("gate") == JUDGE_PASS:
            passed.add(tid)
            continue
        if tid not in seen:
            seen.add(tid)
            out.append({"topic_id": tid, "script_id": sid, "slug": v.get("slug"),
                        "reason_code": v.get("reason_code") or JUDGE_INCOMPLETE_CODE})
    return [r for r in out if r["topic_id"] not in passed], passed, True


def _ts(text):
    try:
        return datetime.strptime(str(text), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def round_estimate(batch):
    """`(seconds, why)` - how long one reserve round after the judge takes:
    the sum of this batch's own finished durations of the stages it repeats
    (ROUND_STAGES, from `run-state.json`), or ROUND_DEFAULT_S when any of
    them is not recorded (a batch whose first reserve round never ran has no
    measure of the indexer's part, the longest one)."""
    st = _read(Path(batch) / RUN_STATE)
    stages = (st or {}).get("stages") if isinstance(st, dict) else None
    if not isinstance(stages, dict):
        return ROUND_DEFAULT_S, f"{ROUND_DEFAULT_S // 3600} h by default (no {RUN_STATE})"

    def took(prefixes):
        best = None
        for sid, ss in stages.items():
            if not isinstance(ss, dict) or not any(sid.startswith(p) for p in prefixes):
                continue
            a, b = _ts(ss.get("started")), _ts(ss.get("ended"))
            if ss.get("status") == "done" and a and b and b >= a:
                if best is None or b > best[2]:
                    best = (sid, (b - a).total_seconds(), b)
        return best

    parts, missing = [], []
    for prefixes, fallback in ROUND_STAGES:
        hit = took(prefixes) or (took(fallback) if fallback else None)
        if hit is None:
            missing.append(prefixes[0])
        else:
            parts.append((hit[0], hit[1]))
    if missing:
        return ROUND_DEFAULT_S, (f"{ROUND_DEFAULT_S // 3600} h by default (this batch has no "
                                 f"finished {', '.join(missing)} to measure)")
    total = sum(s for _, s in parts)
    return total, (f"{_hm(total)} = this batch's "
                   + " + ".join(f"{sid} {_hm(sec)}" for sid, sec in parts))


def _hm(seconds):
    m = int(round(seconds / 60.0))
    return f"{m // 60} h {m % 60:02d} min" if m >= 60 else f"{m} min"


def _shared(name):
    import importlib.util  # noqa: PLC0415
    path = HERE / f"{name}.py"
    mod = sys.modules.get(name)
    if mod is not None and Path(getattr(mod, "__file__", "") or "").resolve() == path:
        return mod
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def quota_day_end(now):
    """The end (UTC) of the YouTube quota day `now` is in (shared/quota_day.py,
    CF-0787: Pacific midnight)."""
    qd = _shared("quota_day")
    return qd.bounds(qd.quota_day(now))[1]


def next_planned_start(root, now):
    """`(start or None, why)`: the factory's next planned batch start after
    `now` (shared/batch_schedule.py `plan`, the days it plans), None when the
    schedule switch is off (nothing starts on its own) or no day is planned.
    A plan that cannot be read is None too, said in `why` - the quota day's
    end still bounds the round."""
    try:
        bs = _shared("batch_schedule")
        p = bs.plan(root=root, now=now)
    except Exception as e:                                  # noqa: BLE001
        return None, f"the schedule plan is not readable ({type(e).__name__}: {e})"
    if not (p.get("switch") or {}).get("on"):
        return None, "the schedule switch is off: no planned batch starts on its own"
    starts = [_ts(d.get("window_start")) for d in p.get("days") or []
              if d.get("status") == "planned"]
    starts = [s for s in starts if s and s > now]
    if not starts:
        return None, "no batch planned in the schedule"
    first = min(starts)
    return first, f"next planned batch {first.strftime('%Y-%m-%dT%H:%MZ')}"


def _judge_round_records(sub):
    if not isinstance(sub, dict):
        return []
    return [r for key in ("substitutions", "unmatched") for r in sub.get(key) or []
            if isinstance(r, dict) and r.get("at") == JUDGE_AT]


def reserve_after_judge(batch, root=None, now=None, next_batch=None, reserve=True, state=None):
    """(holds, why) of `reserve_after_judge` (CF-0801). `now` and
    `next_batch` (a `(root, now) -> (start or None, why)`) stand in for the
    clock and the schedule in the tests.

    CF-0882: `reserve=False` drops the one clause "the reserve still holds a
    topic" - the refill from below the shortlist asks whether the round would
    run if it had one; `state` (a dict) receives `open` (the refused topics
    still unanswered), `left` (the reserve) and `want`/`ready`."""
    state = {} if state is None else state
    batch = Path(batch)
    refused, passed, ran = judge_outcome(batch)
    if not ran:
        return False, f"no {JUDGE_FILE}: the frame judge has not run, nothing to refill"
    A = {name: _read(batch / name) for name in (RESEARCHER_FILE, INDEX_FILE, COMPLIANCE_FILE)}
    A = {k: v for k, v in A.items() if v is not None}
    sub, _ = _stopcock().substitution_block(A, batch)
    done = _judge_round_records(sub)
    if done:
        return False, (f"one round only: {INDEX_FILE} -> reserve_substitution already holds "
                       f"{len(done)} record(s) at {JUDGE_AT} ("
                       + ", ".join(f"{r.get('topic_id') or '-'} for {r.get('replaced')}"
                                   for r in done) + ")")
    answered = _answered(A, batch)
    open_ = [r for r in refused if r["topic_id"] not in answered]
    n = len(open_)
    if not n:
        return False, (f"N=0: the frame judge refused no topic ({len(passed)} with a video "
                       f"through the gate)" if not refused else
                       f"N=0: every topic the frame judge refused is already answered in "
                       f"{INDEX_FILE}")
    named = ", ".join(f"{r['topic_id']} ({r['reason_code']})" for r in open_)
    tgt = _funnel().target_of(batch, A, root=root) or {}
    want = tgt.get(TARGET_FIELD)
    field = TARGET_FIELD
    if want is None:
        want, field = tgt.get(TARGET_FALLBACK), TARGET_FALLBACK
    if want is None:
        return False, (f"N={n} refused ({named}), but the channel's slot count is not "
                       f"readable (channels/<channel>.json -> scope): nothing to compare with")
    key = {"max_titles": "scope.max_titles_per_batch",
           "ready": "scope.target_ready_videos_per_batch"}[field]
    ready = len(passed)
    if ready >= want:
        return False, (f"N={n} refused ({named}), but {ready} topic(s) already have a video "
                       f"through the gate - not under {want} ({key})")
    left, why_left = _stopcock()._remaining_reserve(A, batch)
    state.update(open=open_, left=left, want=want, ready=ready)
    head = f"N={n} refused ({named}), ready {ready} < {want} ({key}), M={len(left)} in reserve ({why_left})"
    if not left and reserve:
        return False, head
    now = now or datetime.now(timezone.utc)
    est, est_why = round_estimate(batch)
    q_end = quota_day_end(now)
    nb, nb_why = (next_batch or next_planned_start)(root, now)
    limits = [(q_end, f"the quota day ends {q_end.strftime('%Y-%m-%dT%H:%MZ')}")]
    if nb is not None:
        limits.append((nb, nb_why))
    deadline, what = min(limits, key=lambda x: x[0])
    room = (deadline - now).total_seconds()
    guard = f"round ~{est_why}; {_hm(max(room, 0))} left until {what}"
    if nb is None:
        guard += f" ({nb_why})"
    if room < est:
        return False, f"{head}; skipped - time: {guard}"
    return True, f"{head}; {guard}"


def _funnel():
    p = str(HERE / "runlog")
    if p not in sys.path:
        sys.path.insert(0, p)
    import funnel  # noqa: PLC0415
    return funnel


def _gate():
    p = str(HERE.parent / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    import frame_judge_gate  # noqa: PLC0415
    return frame_judge_gate


def judge_set(batch):
    """CF-0707: (state, why) of the batch's `05-video-editor.json` for the
    frame judge - read by the gate's own predicate (`batch_judge_set`, the one
    `deliverable()` the gate judges by), never a second copy of it."""
    return _gate().batch_judge_set(batch)


def judge_candidates(batch):
    """The LLM stage `frame-judge` runs: 05 names a video to judge, or 05 is
    not there to read (the judge's SKILL then closes with a note saying so -
    the Editor's broken contract is the triage's, not a reason to skip)."""
    state, why = judge_set(batch)
    return state != "none", why


def nothing_to_judge(batch):
    """The machine stage `frame-judge-empty` runs: 05 is readable and owes the
    judge nothing - the gate writes `06` with `videos: []` and the sentence."""
    state, why = judge_set(batch)
    return state == "none", why


def _researcher_empty():
    p = str(HERE.parent / "scripts")
    if p not in sys.path:
        sys.path.insert(0, p)
    import researcher_nothing_to_write  # noqa: PLC0415
    return researcher_nothing_to_write


def nothing_to_write(batch):
    """CF-0763: the machine stage `content-researcher-empty` runs - `02` and
    `01b` are readable and hand the Researcher no topic; the script writes `03`
    with `scripts: []` and the sentence, and the stop-cock then reads `stop`."""
    return _researcher_empty().nothing_to_write(batch)


def write_candidates(batch):
    """CF-0763: the LLM stage `content-researcher` runs - the complement of
    `nothing_to_write` (a missing `02`/`01b` included: the Researcher's own
    no-waiting exit names it, and the triage puts the break upstream)."""
    holds, why = nothing_to_write(batch)
    return not holds, why


# The named conditions of run_plan.CONDITIONS -> their evaluation.
def _below_shortlist():
    return _shared("below_shortlist")


CHECKS = {"reserve_refill": lambda batch, root=None: reserve_refill(batch),
          "below_shortlist_refill":
              lambda batch, root=None: _below_shortlist().check(batch, "first", root=root),
          "below_shortlist_refill_late":
              lambda batch, root=None: _below_shortlist().check(batch, "late", root=root),
          "below_shortlist_refill_judge":
              lambda batch, root=None: _below_shortlist().check(batch, "judge", root=root),
          "reserve_after_judge": lambda batch, root=None: reserve_after_judge(batch, root=root),
          "repair_after_judge": lambda batch, root=None: _shared("judge_repair").repair_after_judge(batch),
          "repair_judge_pending": lambda batch, root=None: _shared("judge_repair").repair_judge_pending(batch),
          "judge_candidates": lambda batch, root=None: judge_candidates(batch),
          "nothing_to_judge": lambda batch, root=None: nothing_to_judge(batch),
          "write_candidates": lambda batch, root=None: write_candidates(batch),
          "nothing_to_write": lambda batch, root=None: nothing_to_write(batch)}


# CF-0917: the contracts an LLM stage's output file owes the files it read,
# beyond being there (that is the executor's `stage_left_no_output`, CF-0730).
# {contract file: fn(batch, strict) -> (kept, why)}; `strict` is True for a
# stage that `produces` the file, False for one that `updates` it (a merging
# pass: rows of scripts it replaced are harmless). The executor fails a stage
# whose file breaks one (`stage_broke_contract`) instead of recording it done.
def compliance_rows(batch, strict=True):
    """CF-0917: `04-compliance-checker.json` holds a row under every script id
    of `03-content-researcher.json`, each with its `claims_gate` (and, strict,
    no row naming something that is not a script of 03). (kept, why). A batch
    with no readable 03 or 04 keeps it here - the missing file is CF-0730's."""
    fn = _funnel()
    cr, c04 = _read(Path(batch) / "03-content-researcher.json"), _read(
        Path(batch) / fn.SCRIPTS_04_FILE)
    brk = fn.compliance_rows_break(cr, c04, strict=strict)
    if brk is None:
        return True, (f"{fn.SCRIPTS_04_FILE} answers every script of 03"
                      if isinstance(cr, dict) and isinstance(c04, dict)
                      else "03 or 04 not readable - nothing to compare")
    return False, brk["line"]


OUTPUT_CONTRACTS = {"04-compliance-checker.json": compliance_rows}


def output_contract(name, batch, strict=True):
    """(kept, why) of the contract file `name`; (True, "") for a file with none."""
    fn = OUTPUT_CONTRACTS.get(name)
    if fn is None:
        return True, ""
    return fn(batch, strict=strict)


def check(name, batch, root=None):
    fn = CHECKS.get(name)
    if fn is None:
        return False, f"no evaluation for condition {name!r} in shared/run_checks.py"
    return fn(batch, root=root)


def _caption_cache(indexer_dir):
    scripts = str(Path(indexer_dir) / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    import caption_cache  # noqa: PLC0415
    return caption_cache


def captions_stale(indexer_dir, paths):
    """{index path: [(shot, stamp)]} of the stale ones."""
    return _caption_cache(indexer_dir).survey([p for p in paths if Path(p).is_file()])


def _run_remeasure(argv, timeout):
    """remeasure_captions.py in its own process group: (exit code or None when
    stopped at `timeout`). The whole group goes on a timeout - its --jobs
    children included."""
    import os  # noqa: PLC0415
    import signal  # noqa: PLC0415
    p = subprocess.Popen(argv, start_new_session=True)
    try:
        return p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        for sig, grace in ((signal.SIGTERM, 10), (signal.SIGKILL, 10)):
            try:
                os.killpg(p.pid, sig)
            except (ProcessLookupError, PermissionError):
                pass
            try:
                p.wait(timeout=grace)
                break
            except subprocess.TimeoutExpired:
                continue
        return None


def _set_aside_count(cc, stale):
    """How many of the shots `stale` named ({index: [(shot, stamp)]}) now carry
    a set-aside crop and no cached one - what this run set aside, whoever did
    it (remeasure_captions.py --set-aside-rest or this command)."""
    n, k = 0, 0
    for path, shots in stale.items():
        try:
            data = json.loads(Path(path).read_text())
        except (OSError, ValueError):
            continue
        ids = {i for i, _ in shots}
        m = sum(1 for s in data.get("shots", [])
                if s.get("index") in ids and cc.SET_ASIDE_KEY in s and cc.VALUE_KEY not in s)
        n += m
        k += bool(m)
    return n, k


def captions_remeasure(cc, indexer_dir, stale, dry_run=False, budget=None, timeout=None):
    """CF-0819: re-measure what fits in the budget, set the rest aside, never
    fail the batch over the caption cache. Returns the exit code (see the
    module docstring)."""
    budget = REMEASURE_BUDGET if budget is None else budget
    timeout = REMEASURE_TIMEOUT if timeout is None else timeout
    missing = [a for a in SET_ASIDE_API if not hasattr(cc, a)]
    if missing:
        print(f"run_checks: the Footage Indexer at {indexer_dir} predates CF-0819 - "
              f"caption_cache has no {', '.join(missing)}; it cannot set a stale crop "
              f"aside, and a bulk remeasure of the pool is not run (CF-0819). Pin "
              f"footage-indexer at or past CF-0819 in agents.lock.json.", file=sys.stderr)
        return 2
    script = Path(indexer_dir) / "scripts" / "remeasure_captions.py"
    argv = [sys.executable, str(script), *sorted(stale), "--stale-only",
            "--budget-seconds", str(budget), "--set-aside-rest"] + (["--dry-run"] if dry_run else [])
    n_stale = sum(len(v) for v in stale.values())
    print(f"remeasuring {n_stale} stale shot(s) in {len(stale)} index(es), budget {budget}s, "
          f"the rest set aside: {' '.join(Path(p).name for p in sorted(stale))}", flush=True)
    rc = _run_remeasure(argv, timeout)
    if dry_run:
        return 0 if rc is None else rc
    if rc != 0:
        why = (f"ran past {timeout}s and was stopped" if rc is None
               else f"exited {rc}")
        print(f"run_checks: remeasure_captions.py {why}; what is still stale is set "
              f"aside, not re-measured (CF-0819)", file=sys.stderr)
    # Whatever is still stale - a stopped or crashed child, a failed probe - is
    # set aside here, so the rerun of captions-stale reads the pool current.
    left = cc.survey(sorted(stale))
    for path in sorted(left):
        try:
            cc.set_aside(path)
        except Exception as e:                              # noqa: BLE001
            print(f"run_checks: could not set aside {Path(path).name}: "
                  f"{e.__class__.__name__}: {e}", file=sys.stderr)
    n, k = _set_aside_count(cc, stale)
    if not n:
        return 0
    print(f"run_checks: {cc.set_aside_warning(n, k)}", file=sys.stderr, flush=True)
    return SET_ASIDE_EXIT


def main(argv=None):
    ap = argparse.ArgumentParser(prog="run_checks.py", description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("reserve-refill")
    r.add_argument("batch")
    ra = sub.add_parser("reserve-after-judge")
    ra.add_argument("batch")
    ra.add_argument("--root", default=None, help="the factory root (default: $FACTORY_ROOT, else this checkout)")
    j = sub.add_parser("judge-set")
    j.add_argument("batch")
    for name in ("captions-stale", "captions-remeasure"):
        c = sub.add_parser(name)
        c.add_argument("--indexer-dir", required=True)
        c.add_argument("--dry-run", action="store_true", help="remeasure: report, write nothing")
        c.add_argument("indexes", nargs="*")
    ns = ap.parse_args(argv)
    if ns.cmd == "reserve-refill":
        if not Path(ns.batch).is_dir():
            print(f"run_checks: no batch directory {ns.batch}", file=sys.stderr)
            return 2
        holds, why = reserve_refill(ns.batch)
        print(f"reserve_refill: {'yes' if holds else 'no'} - {why}")
        return 0 if holds else 1
    if ns.cmd == "reserve-after-judge":
        if not Path(ns.batch).is_dir():
            print(f"run_checks: no batch directory {ns.batch}", file=sys.stderr)
            return 2
        holds, why = reserve_after_judge(ns.batch, root=ns.root)
        print(f"reserve_after_judge: {'yes' if holds else 'no'} - {why}")
        return 0 if holds else 1
    if ns.cmd == "judge-set":
        if not Path(ns.batch).is_dir():
            print(f"run_checks: no batch directory {ns.batch}", file=sys.stderr)
            return 2
        state, why = judge_set(ns.batch)
        print(f"judge_set: {state} - {why}")
        return {"some": 0, "none": 1}.get(state, 3)
    stale = captions_stale(ns.indexer_dir, ns.indexes)
    cc = _caption_cache(ns.indexer_dir)
    if not stale:
        print(f"{len(ns.indexes)} index(es): every cached caption crop is current")
        return 0
    if ns.cmd == "captions-stale":
        print(cc.complaint(stale))
        return 1
    return captions_remeasure(cc, ns.indexer_dir, stale, ns.dry_run)


if __name__ == "__main__":
    sys.exit(main())
