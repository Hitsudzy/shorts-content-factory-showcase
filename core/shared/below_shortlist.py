#!/usr/bin/env python3
"""CF-0882: when the reserve is used up, the next viable topics from below the
shortlist take the free slots - judged by compliance on the fly, paid for out
of the day's Search quota - instead of the slot staying empty.

    python3 shared/below_shortlist.py queue   <batch>
    python3 shared/below_shortlist.py budget  <batch> [--root R]
    python3 shared/below_shortlist.py check   <batch> --round first|late|judge [--root R]
    python3 shared/below_shortlist.py promote <batch> --round R --cc-dir D --cc-python P
                                              --th-dir D --th-python P [--root R]
    python3 shared/below_shortlist.py replay  <batch>... [--root R] [--json]

Why (the funnel of 20-27.10). The reserve a batch may substitute from is
`02-compliance-checker.json -> reserve[]`: the shortlist (8) less the cut (5),
three topics. It burns on the same refusals the shortlist does; in 7 batches
`reserve_after_judge` held M=0 every time, 14 refused topics had no
replacement, 6 slots stayed empty (`reserve_exhausted`) - while viable topics
below the shortlist (`01-trend-hunter.json -> skipped_topics[]` with
`reason_code: below_shortlist`, CF-0264: fact-probed, ranked, no slot) sat
untouched: Reel 21, Tech 15.

**The round** (`promote`), run by the plan right before each reserve round of
the Footage Indexer (`footage-indexer-reserve`, `-late`, `-judge`) when the
round needs more topics than the reserve holds (`check`, the named condition
`below_shortlist_refill`):

1. `need` = the slots the round will try to fill less the reserve left
   (`run_checks.refill_counts` / `run_checks.reserve_after_judge(reserve=False)`
   - the same N and M the reserve round itself is decided by).
2. `queue` = the batch's `below_shortlist` topics nothing has spent yet, in
   rank order (`queue`).
3. Compliance judges `need + EXTRA_JUDGED` of them on the fly (the seam
   `judge`); a refused one is passed over, never retried.
4. The budget (`budget`): a substitute from below the shortlist has no footage
   candidates (step 5b never walked it), so it costs one facet run -
   `search_quota.substitution_price_searches` of the batch's `01`, else
   FACET_RUN_SEARCHES. The round takes only what the day still pays for: the
   quota day's spend (`quota_day.day_spend`, every batch of the day, this one
   included) + the price of each substitute + the margin (CF-0830) stays within
   the 100 `search.list` calls of the day, and when the day's second batch would
   still be admitted (CF-0830 `admission`: a channel with `windows`, a window
   ahead in the same quota day, the day under `max_batches`), its expected
   spend is held back too - the refill never takes the day's second batch away.
5. Trend Hunter walks the affordable eligible topics through step 5b (the seam
   `footage`: the facet run, the topic back into `01 -> topics[]` with its
   candidates), and compliance admits the ones that got a pool (the seam
   `admit`: their rows into `02 -> reserve[]` marked `refill`). From there the
   Footage Indexer's reserve round takes them like any other reserve topic -
   `stopcock._remaining_reserve` reads the marked rows nobody has answered yet.

The root puts the round on what the agents wrote for it (CF-0888): compliance
is told `--round` and writes it on its `02 -> refill_refused[]` rows; Trend
Hunter's seam takes no round, so the root stamps `round` on the
`01 -> below_shortlist_refill[]` rows of the topics it just walked
(`stamp_round`). The funnel reads the three records as one
(`funnel.below_shortlist_refill`).

Everything the round decided is `work/below-shortlist-refill.json ->
rounds[]` (one record per round; a round already recorded is not run twice).
An agent with no seam script, a crash or a timeout is recorded and the batch
goes on as it did before CF-0882 - never a broken batch.

**replay** - the retro measurement over finished batches (read-only): how many
substitutions the refill would have made and what searches they would have
cost, by the batches' own artifacts and the day's recorded spend.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0882"
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent

TREND_FILE = "01-trend-hunter.json"
INDEX_FILE = "01b-footage-index.json"
COMPLIANCE_FILE = "02-compliance-checker.json"
RECORD_FILE = "work/below-shortlist-refill.json"
RECORD_SCHEMA = "below-shortlist-refill/1"
JUDGED_FILE = "work/below-shortlist-judged.json"
FOOTAGE_FILE = "work/below-shortlist-footage.json"
ADMITTED_FILE = "work/below-shortlist-admitted.json"

BELOW_CODE = "below_shortlist"            # fact_probe_topics.OVERFLOW_CODE (CF-0264)
REFILL_MARK = "refill"                    # the key on a 02 reserve[] row the refill admitted
ROUNDS = ("first", "late", "judge")
ROUND_AT = {"first": "researcher_refusal", "late": "researcher_refusal",
            "judge": "frame_judge_refusal"}
# trend-hunter search_quota.FACET_RUN_SEARCHES - the price of one walk through
# step 5b when the batch's 01 does not say `substitution_price_searches`.
FACET_RUN_SEARCHES = 6
# How many more topics than needed compliance judges at once: a refused one is
# passed over, and judging is free (no search).
EXTRA_JUDGED = 2

# The seams (the agents' halves; the task file's specs).
CC_ENTRY = "scripts/judge_below_shortlist.py"       # compliance-checker: judge / admit
TH_ENTRY = "scripts/promote_below_shortlist.py"     # trend-hunter: the facet run
TH_LOG_KEY = "below_shortlist_refill"   # 01 -> below_shortlist_refill[] (trend-hunter LOG_KEY)
SEAM_TIMEOUT_S = {"judge": 20 * 60, "footage": 45 * 60, "admit": 5 * 60}

ELIGIBLE = "eligible"
WITH_POOL = "candidates"


# ---------------------------------------------------------------------------
# reading

def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write_json(path, doc):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _now_z(now=None):
    return (now or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _id(t):
    if isinstance(t, dict):
        return t.get("topic_id") or t.get("id")
    return t if isinstance(t, str) else None


def _load(name):
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


def _checks():
    return _load("run_checks")


def factory_root(batch, root=None):
    """The factory root of `batch` (`<root>/pipeline/<channel>/<id>`), else `root`,
    else the code root."""
    if root is not None:
        return Path(root)
    b = Path(batch).resolve()
    if b.parent.parent.name == "pipeline":
        return b.parent.parent.parent
    return ROOT


def record(batch):
    doc = _read(Path(batch) / RECORD_FILE)
    if not isinstance(doc, dict) or not isinstance(doc.get("rounds"), list):
        doc = {"task": TASK, "schema": RECORD_SCHEMA, "rounds": []}
    return doc


def round_record(batch, rnd):
    for r in record(batch)["rounds"]:
        if isinstance(r, dict) and r.get("round") == rnd:
            return r
    return None


def refill_rows(c02):
    """The `02 -> reserve[]` rows the refill admitted (marked REFILL_MARK)."""
    return [r for r in (c02 or {}).get("reserve") or []
            if isinstance(r, dict) and r.get(REFILL_MARK) and _id(r)]


def spent_topics(batch):
    """Every topic id the batch has already used or judged - none of them is
    offered from below the shortlist again."""
    batch = Path(batch)
    t = _read(batch / TREND_FILE) or {}
    c = _read(batch / COMPLIANCE_FILE) or {}
    ix = _read(batch / INDEX_FILE) or {}
    out = {_id(x) for x in t.get("topics") or []}
    fs = t.get("footage_substitution") or {}
    out |= {_id(x) for x in fs.get("substitutions") or []}
    for key in ("results", "reserve", "refill_refused"):
        out |= {_id(x) for x in c.get(key) or []}
    out |= set(ix.get("sources_by_topic") or {})
    for r in record(batch)["rounds"]:
        for key in ("judged", "footage", "admitted"):
            out |= {_id(x) for x in r.get(key) or []}
    out.discard(None)
    return out


def queue(batch):
    """`[{topic_id, rank, title}]` - the batch's `below_shortlist` topics nothing
    has spent yet, by rank (a row without `rank` keeps its place: step 5a
    appends the overflow in rank order)."""
    t = _read(Path(batch) / TREND_FILE) or {}
    spent = spent_topics(batch)
    rows = []
    for i, r in enumerate(t.get("skipped_topics") or []):
        if not isinstance(r, dict) or r.get("reason_code") != BELOW_CODE:
            continue
        tid = _id(r)
        if not tid or tid in spent or any(x["topic_id"] == tid for _i, x in rows):
            continue
        rank = r.get("rank")
        rows.append(((rank if isinstance(rank, (int, float)) else math.inf, i),
                     {"topic_id": tid, "rank": rank, "title": r.get("title")}))
    return [x for _k, x in sorted(rows, key=lambda p: p[0])]


def price(batch):
    """`(searches one substitute costs, where the number came from)`."""
    q = (_read(Path(batch) / TREND_FILE) or {}).get("search_quota") or {}
    p = q.get("substitution_price_searches")
    if isinstance(p, int) and not isinstance(p, bool) and p > 0:
        return p, f"{TREND_FILE} -> search_quota.substitution_price_searches"
    return FACET_RUN_SEARCHES, "FACET_RUN_SEARCHES (search_quota.py)"


# ---------------------------------------------------------------------------
# the budget (CF-0830)

def second_batch_hold(root, now, base, expected_of=None, windows_of=None, switch_on=None,
                      channels=None):
    """`(searches held back, why)`: the expected spend of the day's next batch
    when CF-0830 would still admit it - a channel with `windows` whose window
    starts after `now` in the same quota day, the day under `max_batches`,
    spent + expected within limit - margin. 0 when no such batch can come."""
    bs = _load("batch_schedule")
    qd = bs.quota_day(now)
    if base["batches"] >= base["max_batches"]:
        return 0, (f"the quota day already has {base['batches']} of {base['max_batches']} "
                   f"batches - no second batch to hold for")
    on = switch_on(root) if switch_on else bs.switch_state(root).get("on")
    if not on:
        return 0, "the schedule switch is off - no batch starts on its own"
    expected_of = expected_of or (lambda ch: bs.expected_searches(ch, root, now))
    if windows_of is None:
        def windows_of(ch):
            w = bs.window_config(ch, root)
            if not w.get("multi") or not w.get("enabled"):
                return []
            return [s for s, _e in bs.windows_on(qd, w) + bs.windows_on(date_after(qd), w)]
    best = None
    if channels is not None:
        chans = list(channels)
    else:
        try:
            chans = bs.collect().channels(root)
        except Exception:                                   # noqa: BLE001
            chans = []
    for ch in chans:
        try:
            starts = [s for s in windows_of(ch) if s > now and bs.quota_day(s) == qd]
        except Exception:                                   # noqa: BLE001
            continue
        if not starts:
            continue
        exp = expected_of(ch)
        exp = exp["searches"] if isinstance(exp, dict) else int(exp)
        if base["spent"] + exp > base["limit"] - base["margin"]:
            continue                        # CF-0830 would not admit it anyway
        if best is None or exp > best[1]:
            best = (ch, exp, min(starts))
    if best is None:
        return 0, "no second batch of this quota day is still admissible"
    ch, exp, start = best
    return exp, (f"held for the day's next batch: {ch} at {start.strftime('%Y-%m-%dT%H:%MZ')}, "
                 f"expected {exp} searches (CF-0830)")


def date_after(day):
    from datetime import timedelta  # noqa: PLC0415
    return day + timedelta(days=1)


def budget(batch, root=None, now=None, base=None, hold=None):
    """`{price, price_from, limit, margin, spent, hold, hold_why, room,
    affordable, line}` - how many substitutes from below the shortlist the
    quota day still pays for. `base` (CF-0830 `quota_budget`) and `hold` (a
    `(searches, why)`) stand in for the ledger and the schedule in the tests.
    The spend of an earlier refill round of this batch counts even when the
    ledger has not caught up with it yet."""
    now = now or datetime.now(timezone.utc)
    root = factory_root(batch, root)
    if base is None:
        bs = _load("batch_schedule")
        base = bs.quota_budget(bs.quota_day(now), root)
    p, p_from = price(batch)
    floor = max([r.get("spent_after") or 0 for r in record(batch)["rounds"]
                 if isinstance(r, dict)] or [0])
    spent = max(int(base["spent"]), int(floor))
    if hold is None:
        try:
            hold = second_batch_hold(root, now, dict(base, spent=spent))
        except Exception as e:                              # noqa: BLE001
            hold = (0, f"the schedule is not readable ({type(e).__name__}: {e}) - nothing held")
    held, held_why = hold
    limit, margin = int(base["limit"]), int(base["margin"])
    room = limit - margin - spent - held
    affordable = max(0, room // p) if room > 0 else 0
    line = (f"квота суток: потрачено {spent} из {limit}, запас {margin}"
            + (f", придержано {held} под второй батч" if held else "")
            + f" - остаток на подстановки {max(room, 0)}, цена одной {p} ({p_from}) -> "
            f"можно {affordable}")
    return {"price": p, "price_from": p_from, "limit": limit, "margin": margin,
            "spent": spent, "hold": held, "hold_why": held_why, "room": room,
            "affordable": affordable, "line": line}


# ---------------------------------------------------------------------------
# the need of a round

def need(batch, rnd, root=None, now=None, next_batch=None):
    """`(slots the reserve cannot fill, why)` for round `rnd`. 0 when the round
    would not run for a reason other than an empty reserve (nothing refused, the
    judge's round already ran or has no time)."""
    rc = _checks()
    A = {INDEX_FILE: _read(Path(batch) / INDEX_FILE)}
    if A[INDEX_FILE] is not None and not rc._stopcock()._own_index(A, Path(batch)):
        return 0, (f"{INDEX_FILE} is another batch's (a re-run or a rebuild indexes nothing) - "
                   f"no topic can be given sources here")
    if rnd in ("first", "late"):
        counts = rc.refill_counts(batch)
        if counts is None:
            return 0, f"no {rc.RESEARCHER_FILE}: nothing refused"
        open_, left, why, _done = counts
        n, m = len(open_), len(left)
        return max(0, n - m), f"N={n} refused unanswered, M={m} in reserve ({why})"
    if rnd == "judge":
        st = {}
        holds, why = rc.reserve_after_judge(batch, root=root, now=now, next_batch=next_batch,
                                            reserve=False, state=st)
        if not holds:
            return 0, f"the judge's reserve round would not run: {why}"
        n = min(len(st.get("open") or []), max(0, (st.get("want") or 0) - (st.get("ready") or 0)))
        m = len(st.get("left") or [])
        return max(0, n - m), why
    raise ValueError(f"unknown round {rnd!r} ({', '.join(ROUNDS)})")


def check(batch, rnd, root=None, now=None, next_batch=None):
    """(holds, why) of the named condition `below_shortlist_refill`: the round
    needs more topics than the reserve holds, the queue below the shortlist is
    not empty, and this round has not run yet. The budget is decided by the
    round itself and recorded (a skip for the quota is a fact the funnel reads)."""
    if round_record(batch, rnd) is not None:
        return False, f"one pass per round: {RECORD_FILE} already holds round {rnd}"
    k, why = need(batch, rnd, root=root, now=now, next_batch=next_batch)
    if k <= 0:
        return False, f"nothing to refill from below the shortlist: {why}"
    q = queue(batch)
    if not q:
        return False, (f"{k} slot(s) the reserve cannot fill, but no unspent "
                       f"{BELOW_CODE} topic is left ({why})")
    return True, f"{k} slot(s) the reserve cannot fill, {len(q)} below the shortlist ({why})"


# ---------------------------------------------------------------------------
# the seams

def _run(argv, timeout):
    import subprocess  # noqa: PLC0415
    return subprocess.run(argv, timeout=timeout).returncode


def call_seam(kind, agent_dir, python, entry, args, result, runner=None):
    """Run one agent seam; `(rows or None, error or None)`. A missing script,
    a crash, a timeout or an unreadable result is an error, never an
    exception."""
    script = Path(agent_dir) / entry
    if not script.is_file():
        return None, f"{agent_dir} has no {entry} ({TASK}'s agent half is not in)"
    result = Path(result)
    result.parent.mkdir(parents=True, exist_ok=True)
    if result.exists():
        result.unlink()
    argv = [python or sys.executable, str(script)] + list(args) + ["--result", str(result)]
    try:
        code = (runner or _run)(argv, SEAM_TIMEOUT_S[kind])
    except Exception as e:                                  # noqa: BLE001
        return None, f"{entry} {kind}: {type(e).__name__}: {e}"
    doc = _read(result)
    rows = doc.get("topics") if isinstance(doc, dict) else None
    if not isinstance(rows, list):
        return None, (f"{entry} {kind} left no readable result"
                      + (f" (exit {code})" if code else ""))
    rows = [r for r in rows if isinstance(r, dict) and _id(r)]
    return rows, (f"exit {code}" if code else None)


def stamp_round(batch, rnd, topics):
    """CF-0888: put `round` on the `01 -> below_shortlist_refill[]` rows Trend
    Hunter just wrote for `topics` - its seam takes no `--round` and its rows
    carry none, while the root knows which round walked them. Only a row
    without a `round` is stamped (the agent's own value wins, once it writes
    one). Returns the stamped topic ids; never raises (the round goes on)."""
    path = Path(batch) / TREND_FILE
    t = _read(path)
    rows = t.get(TH_LOG_KEY) if isinstance(t, dict) else None
    if not isinstance(rows, list):
        return []
    want, done = set(topics), []
    for r in rows:
        if isinstance(r, dict) and _id(r) in want and not r.get("round"):
            r["round"] = rnd
            done.append(_id(r))
    if done:
        try:
            _write_json(path, t)
        except OSError:
            return []
    return done


def promote(batch, rnd, cc_dir, cc_python=None, th_dir=None, th_python=None, root=None,
            now=None, next_batch=None, base=None, hold=None, runner=None, out=print):
    """One refill round (module doc). Returns the round's record."""
    batch = Path(batch)
    now = now or datetime.now(timezone.utc)
    have = round_record(batch, rnd)
    if have is not None:
        out(f"round {rnd} already ran ({RECORD_FILE})")
        return have
    k, need_why = need(batch, rnd, root=root, now=now, next_batch=next_batch)
    q = queue(batch)
    rec = {"round": rnd, "at": _now_z(now), "at_code": ROUND_AT[rnd], "need": k,
           "need_why": need_why, "queue": [x["topic_id"] for x in q],
           "judged": [], "footage": [], "admitted": [], "searches": 0, "outcome": None,
           "why": None}
    doc = record(batch)

    def done(outcome, why):
        rec["outcome"], rec["why"] = outcome, why
        doc["rounds"].append(rec)
        _write_json(batch / RECORD_FILE, doc)
        out(f"below-shortlist refill, round {rnd}: {outcome} - {why}")
        return rec

    if k <= 0:
        return done("not_needed", need_why)
    if not q:
        return done("queue_empty", f"no unspent {BELOW_CODE} topic ({need_why})")
    b = budget(batch, root=root, now=now, base=base, hold=hold)
    rec["budget"] = b
    rec["spent_after"] = b["spent"]
    if b["affordable"] <= 0:
        return done("search_quota", b["line"] + (f"; {b['hold_why']}" if b["hold"] else ""))

    ids = [x["topic_id"] for x in q[:k + EXTRA_JUDGED]]
    judged, err = call_seam("judge", cc_dir, cc_python, CC_ENTRY,
                            ["judge", str(batch), "--topics", ",".join(ids), "--round", rnd],
                            batch / JUDGED_FILE, runner)
    if judged is None:
        rec["judged"] = [{"topic_id": t, "outcome": "not_judged"} for t in ids]
        return done("seam_failed", f"compliance: {err}")
    by = {_id(r): r for r in judged}
    rec["judged"] = [{"topic_id": t, "verdict": (by.get(t) or {}).get("verdict"),
                      "outcome": (by.get(t) or {}).get("outcome") or "not_judged",
                      "reason": (by.get(t) or {}).get("reason")} for t in ids]
    eligible = [r["topic_id"] for r in rec["judged"] if r["outcome"] == ELIGIBLE]
    take = eligible[:min(k, b["affordable"])]
    if not take:
        return done("none_eligible", f"compliance passed none of {', '.join(ids)}")
    walked, err = call_seam("footage", th_dir, th_python, TH_ENTRY,
                            [str(batch), "--topics", ",".join(take),
                             "--max-searches", str(len(take) * b["price"])],
                            batch / FOOTAGE_FILE, runner)
    stamp_round(batch, rnd, take)           # CF-0888: the walk's rows in 01 get their round
    if walked is None:
        rec["footage"] = [{"topic_id": t, "outcome": "not_walked"} for t in take]
        return done("seam_failed", f"trend-hunter: {err}")
    by = {_id(r): r for r in walked}
    for t in take:
        r = by.get(t) or {}
        n = r.get("searches")
        n = n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else b["price"]
        rec["searches"] += n if r else 0
        rec["footage"].append({"topic_id": t, "outcome": r.get("outcome") or "not_walked",
                               "searches": n if r else 0, "reason": r.get("reason")})
    rec["spent_after"] = b["spent"] + rec["searches"]
    pooled = [r["topic_id"] for r in rec["footage"] if r["outcome"] == WITH_POOL]
    if not pooled:
        return done("no_pool", "step 5b gave none of " + ", ".join(take) + " a pool")
    admitted, err = call_seam("admit", cc_dir, cc_python, CC_ENTRY,
                              ["admit", str(batch), "--topics", ",".join(pooled),
                               "--round", rnd], batch / ADMITTED_FILE, runner)
    rows = {_id(r) for r in refill_rows(_read(batch / COMPLIANCE_FILE))}
    rec["admitted"] = [t for t in pooled if t in rows]
    missing = [t for t in pooled if t not in rows]
    if not rec["admitted"]:
        return done("seam_failed", f"compliance admit: {err or 'no row in 02 -> reserve[]'}")
    return done("admitted", f"{len(rec['admitted'])} of {k} slot(s) from below the shortlist "
                f"({', '.join(rec['admitted'])}), {rec['searches']} search(es)"
                + (f"; not admitted: {', '.join(missing)}" if missing else ""))


# ---------------------------------------------------------------------------
# the retro measurement (read-only)

def replay_batch(batch, day_spent, limit=100, margin=5, judge_ran=True, root=None):
    """What the refill would have done in a finished batch: `{batch, losses,
    queue, price, room, substitutions, searches, by_round}`. `day_spent` is the
    quota day's recorded spend (every batch of the day): the measurement is
    conservative - it does not know which part of it came after this batch's
    reserve rounds."""
    batch = Path(batch)
    ix = _read(batch / INDEX_FILE) or {}
    sub = ix.get("reserve_substitution") or {}
    losses, uncovered = [], []
    for u in sub.get("unmatched") or []:
        if isinstance(u, dict) and u.get("reason_code") == "reserve_exhausted":
            row = {"topic_id": u.get("replaced"), "round": "first", "at": u.get("at")}
            # the indexer's own first pass answers its losses before any refill stage
            (uncovered if u.get("at") in ("sieve", "index_pass") else losses).append(row)
    if judge_ran:
        rc = _checks()
        refused, passed, ran = rc.judge_outcome(batch)
        answered = {r.get("replaced") for key in ("substitutions", "unmatched")
                    for r in sub.get(key) or [] if isinstance(r, dict)
                    and r.get("at") == "frame_judge_refusal"}
        open_ = [r for r in refused if r["topic_id"] not in answered]
        A = {n: _read(batch / n) for n in (rc.RESEARCHER_FILE, INDEX_FILE, COMPLIANCE_FILE)}
        A = {k: v for k, v in A.items() if v is not None}
        try:
            tgt = rc._funnel().target_of(batch, A, root=root) or {}
        except Exception:                                   # noqa: BLE001
            tgt = {}
        want = tgt.get(rc.TARGET_FIELD) or tgt.get(rc.TARGET_FALLBACK)
        short = len(open_) if want is None else max(0, want - len(passed))
        for r in open_[:short]:
            losses.append({"topic_id": r["topic_id"], "round": "judge",
                           "at": r.get("reason_code")})
    q = queue(batch)
    p, _ = price(batch)
    room = limit - margin - int(day_spent)
    affordable = max(0, room // p) if room > 0 else 0
    n = min(len(losses), len(q), affordable)
    by_round = {}
    for x in losses[:n]:
        by_round[x["round"]] = by_round.get(x["round"], 0) + 1
    return {"batch": f"{batch.parent.name}/{batch.name}", "losses": len(losses),
            "loss_rows": losses, "uncovered": len(uncovered), "queue": len(q), "price": p, "day_spent": int(day_spent),
            "room": room, "affordable": affordable, "substitutions": n,
            "searches": n * p, "by_round": by_round,
            "limited_by": ("nothing lost" if not losses else
                           "queue" if n == len(q) and len(q) < len(losses) else
                           "quota" if n == affordable and affordable < len(losses) else
                           "losses")}


def replay(batches, root=None):
    """The replay of `batches` in start order; the substitutes of an earlier
    batch of the same quota day are charged to the later ones (the day's
    recorded spend already holds every batch of it)."""
    qd_mod = _load("quota_day")
    rows, used = [], {}
    keyed = sorted((qd_mod.batch_start(Path(b).name) or datetime.min.replace(tzinfo=timezone.utc),
                    str(b)) for b in batches)
    for t, b in keyed:
        b = Path(b)
        r = factory_root(b, root)
        qd = qd_mod.quota_day(t) if t.year > 1 else None
        spent = qd_mod.day_spend(r, qd)["searches"] if qd else 0
        x = replay_batch(b, spent + used.get(qd, 0), root=r)
        x["quota_day"] = qd.isoformat() if qd else None
        used[qd] = used.get(qd, 0) + x["searches"]
        rows.append(x)
    return rows


# ---------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("queue", "budget", "check", "promote"):
        s = sub.add_parser(name)
        s.add_argument("batch")
        s.add_argument("--root")
        if name in ("check", "promote"):
            s.add_argument("--round", required=True, choices=ROUNDS)
        if name == "promote":
            s.add_argument("--cc-dir", required=True)
            s.add_argument("--cc-python")
            s.add_argument("--th-dir", required=True)
            s.add_argument("--th-python")
    rp = sub.add_parser("replay")
    rp.add_argument("batches", nargs="+")
    rp.add_argument("--root")
    rp.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    if ns.cmd == "replay":
        rows = replay(ns.batches, ns.root)
        if ns.json:
            print(json.dumps(rows, ensure_ascii=False, indent=2))
        else:
            for x in rows:
                print(f"{x['batch']}: потеряно {x['losses']}"
                      + (f" (+{x['uncovered']} в проходе индексатора)" if x['uncovered'] else "")
                      + f", ниже шортлиста {x['queue']}, "
                      f"квота дня {x['day_spent']} (можно {x['affordable']} по {x['price']}) -> "
                      f"подстановок {x['substitutions']} {x['by_round']}, поисков {x['searches']} "
                      f"[{x['limited_by']}]")
            print(f"итого: подстановок {sum(x['substitutions'] for x in rows)}, "
                  f"поисков {sum(x['searches'] for x in rows)}, потерь {sum(x['losses'] for x in rows)}"
                  f" (+{sum(x['uncovered'] for x in rows)} в проходе индексатора, не покрыты)")
        return 0
    if not Path(ns.batch).is_dir():
        print(f"no batch dir {ns.batch}", file=sys.stderr)
        return 2
    if ns.cmd == "queue":
        for x in queue(ns.batch):
            print(f"{x['topic_id']}\trank {x['rank']}\t{x['title'] or ''}")
        return 0
    if ns.cmd == "budget":
        print(budget(ns.batch, root=ns.root)["line"])
        return 0
    if ns.cmd == "check":
        holds, why = check(ns.batch, ns.round, root=ns.root)
        print(f"below_shortlist_refill ({ns.round}): {'yes' if holds else 'no'} - {why}")
        return 0 if holds else 1
    promote(ns.batch, ns.round, ns.cc_dir, ns.cc_python, ns.th_dir, ns.th_python, root=ns.root)
    return 0


if __name__ == "__main__":
    sys.exit(main())
