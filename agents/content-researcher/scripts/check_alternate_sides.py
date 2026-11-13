#!/usr/bin/env python3
"""CF-0285: does this `alternate` script have two sides, and can each of them
carry the blocks it is asked for - both answered before the voice is paid for.

The hole
--------
`alternate` is the one rhythm whose block plan is a *comparison*: the montage
crosses an axis, side a, side b, side a. Since CF-0050 the axis belongs to the
writing - `visual_anchors[].side` says which side each moment is on - and the
footage partition is only what happens when the script declared nothing:
`resolve_anchors.footage_sides()` calls the two commonest source files the two
sides, and `rhythm._plan_alternate()` then hands side `a` to the even blocks
and side `b` to the odd ones. Where the script's content actually comes from
is not consulted, because the script never said.

`example-film/2026-09-18T2232Z`, `lf-2026-09-18-009-script1` (The Traitors:
New Blood, `explainer`/`alternate`) is the case, and the second time this exact
topic died of it (`2026-09-18T1058Z` was the first). Eleven anchors, every one
of them `side: null`. The two sources answer the anchors 8 : 3, the parity
alternation demands side `b` in five blocks of ten: four blocks swung back to
the side they could be filled from, two (5 and 9) ended with nothing at all,
and the plan was refused as `pattern_undeliverable` - after TTS, after
alignment, after the resolve. The emergency repeat that exists for exactly this
(CF-0137) was unavailable, because every block of an `alternate` plan is a
`swing` and CF-0074 admits no repeat inside one.

What the writer was never told is that the rhythm asks a question of the
*writing*: two things the viewer can tell apart on screen. The ledger shows how
close the mechanism came to saying it - the Traitors writer rejected this
topic's first assignment, `contrast`/`alternate`, in writing, with the reason
"no second visually-distinguishable set to alternate to" - and the rotation
handed back `explainer`/`alternate`, the same rhythm. The rejection named the
pattern because the pattern is what the writer had been told to look at.

What this gate asks, in order
-----------------------------
**1. Are the sides declared at all?** The Editor's own test, asked by call and
not restated here: `rhythm.declared_sides_usable()`, which `plan_blocks.py`
answers beside the block plan. It requires both `"a"` and `"b"` to appear among
the anchors - one side is not a comparison - and reads anything else (`null`,
a third letter) as "not declared". No balance and no count: two moments, one on
each side, are a comparison.

A sideless `alternate` script is sent back once, with what the footage fallback
would do to it spelled out per side. If it comes back sideless a second time,
the fact has no second side and the *pattern does not fit*: the writer rejects
the assignment in writing and the rotation hands back the next pair, which is
the mechanism that already exists (`rotation/rotate.py reject`, R1-R5, one
ruling per script) and the one `check_narration_budget.py` already points at
when a drawn pair cannot cover the narration. This gate writes the reason for
it; it does not reject anything itself, and it invents no second route.

**2. Can each side carry its slots?** With the sides declared the Editor plans
one block per *crossing* (`rhythm._plan_alternate_declared()`), so the number of
slots a side is asked for is a property of the writing, not of parity - and it
is asked of the planner rather than derived here. The hand-out is then replayed
per block (CF-0284's `hand_out()`, one sample one use) and read per side:
slots demanded, distinct usable candidates the side's anchors offer, blocks
that would swing back to the other side, blocks that would end empty.

The asymmetry this catches is the one the whole-plan capacity gate cannot name.
Two empty blocks out of ten is, to CF-0284, a script that should be shorter; it
is really a script whose thin side was asked to hold half the video. The
remedy is not fewer anchors, it is fewer crossings onto the thin side - or
moments on it the pool can actually answer.

Sides and sources are not the same thing
----------------------------------------
Worth saying once, because the fallback makes it easy to believe otherwise: a
side is two things the viewer can tell apart **on screen**, not two files. A
comparison shot entirely by one camera has two sides and one source; two
uploads of the same set have one side and two sources. That is why the
declared path filters no candidate by source at all - the anchor's phrase is
already the side - and why this gate reports the footage partition only as the
diagnosis of a script that declared nothing.

The ladder
----------
The stage's, for the fifth time (CF-0233, CF-0274, CF-0280, CF-0284), with one
rung that belongs to this gate alone:

  * sides declared and every side fills its slots - pass;
  * no sides - **rewrite**, once, with the per-side arithmetic of what the
    footage fallback would do;
  * no sides after that rewrite - **reject the assignment**: the reason is
    written out ready for `rotation/rotate.py reject`, and nothing is recorded
    in `skipped[]` because the topic is not what failed, the pair is;
  * a side cannot carry its slots - **rewrite**, once (this rung counts its
    own rewrite: the sufficiency of an axis cannot be charged to the rewrite
    that asked for the axis in the first place), towards the crossings the
    thin side can hold;
  * and after that rewrite - **refuse**. The topic leaves the batch as
    `pool_too_thin` (CF-0274's code, already in the funnel) before TTS.

**CF-0330 (the user, 2026-09-23): a thin side warns.** The capacity rung -
a declared side that cannot carry its slots, rewrite then refuse - predicts the
Video Editor's `assetless_rung` / `pattern_undeliverable`, which is a warning
now. So it writes a `warnings[]` entry with the same code (`pool_too_thin`)
and the per-side numbers, the script stays, and the exit is 0. The axis rung
is untouched: a script that declares no sides is still sent back (exit 1) and
still rejected as an assignment after its rewrite (exit 5) - that is a
question about the writing, not a measurement of the pool.

Usage:

    python3 scripts/check_anchor_coverage.py <03-content-researcher.json> \
        --out <reports.json>
    python3 scripts/check_alternate_sides.py <03-content-researcher.json> \
        --reports <reports.json> [--write] [--root <checkout>]

Exit codes:

    0  no `alternate` script, or every one of them has two sides that carry
    1  at least one script is sent back to be rewritten
    3  cannot answer: no reports, no footage index, no block plan from the
       Editor. Nothing about the scripts is claimed.
    4  at least one topic is refused as `pool_too_thin` and (with `--write`)
       recorded in `skipped[]` (only with the gate switched back out of
       `_gate_warning.WARN_GATES` - since CF-0330 a thin side is a warning,
       exit 0)
    5  at least one assignment has to be rejected before anything is written -
       the rhythm does not fit this fact, and the rotation owns the replacement
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
import _gate_warning as gw  # noqa: E402
import _supplement_request as sreq  # noqa: E402
import _rewrite_guard as rg  # noqa: E402

from check_anchor_coverage import (  # noqa: E402
    FALLBACK_SECTIONS, FIELD, FUNNEL_STAGE, GRAPHIC_INDICES_KEY, SIDES, CannotAnswer,
    counted_sections, load_footage_index, load_footage_index_for, topic_pool, topic_pool_for)
import _own_graphic as ogl  # noqa: E402 - CF-0689
from check_narration_budget import find_root  # noqa: E402
from check_two_sources import (  # noqa: E402
    CannotJudge, editor_floors, load_reports, report_for, shot_spans)
# CF-0284's replay, reused whole rather than written a second time: the block
# plan comes from the Editor's planner and the hand-out obeys the Editor's
# constants. This file adds the reading *per side*, and nothing else.
from check_block_capacity import (  # noqa: E402
    DEFAULT_TIMEOUT, POOL_MARGIN_FRAGILE_BLOCKS, anchor_times, footage_sides,
    graphic_scope, hand_out, planner_paths, run_planner)

RHYTHM = "alternate"
RECORD_KEY = "alternate_sides"

# The same loss as CF-0274's and CF-0284's, and the same code: a pool that
# cannot picture the video before TTS. Only the *reason* differs, and the
# reason is written into the entry.
SKIP_REASON_CODE = "pool_too_thin"

# One, like every other rung of this stage.
REWRITES_ALLOWED = 1

ACTION_PASS, ACTION_REWRITE = "pass", "rewrite"
ACTION_REJECT_PAIR, ACTION_REFUSE = "reject_assignment", "refuse"
EXIT_OK, EXIT_REWRITE, EXIT_CANNOT_ANSWER, EXIT_REFUSED, EXIT_REJECT = 0, 1, 3, 4, 5

# Why a side could not be delivered, in the wording that reaches the writer.
TROUBLE_EMPTY = "block(s) with no picture"
TROUBLE_SWUNG = "block(s) that swing back to the other side"
TROUBLE_FRAGILE = "block(s) on their last candidate"

# CF-0286: `--rhythm` - what is refused here is the rhythm (no second showable side),
# so the replacement draw must not hand `alternate` back under another pattern.
REJECT_CMD = "python3 ~/shorts-content-factory/rotation/rotate.py reject {channel} {sid} --batch-id {batch_id} --rhythm \\\n        --reason \"{reason}\""


# --------------------------------------------------------------------------
# the reading per side
# --------------------------------------------------------------------------

def source_of(sample):
    """`80rOmETggNk:14` -> `80rOmETggNk`. The sample key's own shape, as
    `check_two_sources.py` and the coverage preflight both write it."""
    return sample.rsplit(":", 1)[0]


def declared_sides(script):
    """The side each anchor was written on - `resolve_anchors.
    declared_anchor_sides()`'s reading, which takes anything that is not
    exactly "a" or "b" as "not declared" rather than as an error."""
    return [a.get("side") if a.get("side") in SIDES else None
            for a in (script.get(FIELD) or [])]


def per_side(handed, report, sides, declared, written_sides=()):
    """What each side was asked for and what it can answer.

    `slots` is the number of blocks the Editor's plan puts on that side - the
    plan's own count, never parity recomputed here. `distinct_candidates` is
    how many different usable frames those blocks may draw on: under a declared
    axis that is everything their driver anchors found (the resolve filters
    nothing, because the phrase is the side), and under the footage fallback it
    is only what came from that side's source file.

    `anchors_answered` is the other half of the same picture and the number the
    Traitors case turns on: how many of the script's anchors have any usable
    frame on this side at all. Eight against three, under an alternation that
    demanded five and five.
    """
    by_anchor = {r.get("anchor_index"): r for r in report.get("anchors") or []}
    # CF-0689: an anchor that places one of the script's own graphics answers
    # the side it was written on - the graphic is always there to draw.
    graphic = [i for i in report.get(GRAPHIC_INDICES_KEY) or []
               if isinstance(i, int) and 0 <= i < len(written_sides)]
    out = {}
    for side in SIDES:
        mine = [h for h in handed if h["side"] == side]
        cands = set()
        for h in mine:
            for sample in (by_anchor.get(h["anchor"]) or {}).get("samples") or []:
                if declared or not sides or sides.get(source_of(sample)) == side:
                    cands.add(sample)
        answered = 0
        for rec in report.get("anchors") or []:
            samples = rec.get("samples") or []
            if declared:
                # The axis is the writing's: an anchor is on this side because
                # it was written on it, and it answers the side when the pool
                # found it anything at all.
                answered += 1 if (written_sides[rec.get("anchor_index")] == side
                                  and samples) else 0
            elif sides and any(sides.get(source_of(s)) == side for s in samples):
                answered += 1
        if declared:
            answered += sum(1 for i in graphic if written_sides[i] == side)
        out[side] = {
            "slots": len(mine),
            "seconds": round(sum(h["seconds"] for h in mine), 3),
            "distinct_candidates": len(cands),
            "anchors_answered": answered,
            "filled": len([h for h in mine if not h["empty"] and not h["swung"]]),
            "swung": len([h for h in mine if h["swung"]]),
            "empty": len([h for h in mine if h["empty"]]),
            "fragile": len([h for h in mine
                            if not h["empty"] and not h.get("own_graphic")
                            and (h["spare"] <= 0 or h["emergency"])]),
            "blocks": [h["block"] for h in mine],
        }
    return out


def thin_side(reading):
    """The side in the most trouble, and what kind. `None` when both carry.

    Order matters and it is the order of severity: a block with no picture is a
    hole in the video, a block that swung back is an alternation that stopped
    crossing (the montage the pattern was drawn for is not being delivered,
    even though every block has something on it), and a block on its last
    candidate is one framing failure from the first.
    """
    for key, trouble in (("empty", TROUBLE_EMPTY), ("swung", TROUBLE_SWUNG)):
        worst = max(SIDES, key=lambda s: reading[s][key])
        if reading[worst][key] > 0:
            return worst, trouble, reading[worst][key]
    total = sum(reading[s]["fragile"] for s in SIDES)
    if total > POOL_MARGIN_FRAGILE_BLOCKS:
        worst = max(SIDES, key=lambda s: reading[s]["fragile"])
        return worst, TROUBLE_FRAGILE, total
    return None


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------

RUNG_DECLARATION, RUNG_CAPACITY = "declaration", "capacity"


def previous_failures(script, rung):
    """Failures of one RUNG of this gate already recorded on the script.

    The two rungs count separately, and that is the point rather than a
    leniency: they are different questions asked in an order the writer cannot
    skip. A script sent back for having no axis at all comes back with one, and
    the sufficiency of that axis is then being asked of it for the first time -
    charging the answer to a rewrite it has not had yet would refuse the topic
    on the first honest attempt. Two rungs, one rewrite each, and the gate
    still cannot cost more than two model calls.

    A record with no counts at all is one failure of whichever rung it stopped
    on, not zero: it only exists because a run wrote it.
    """
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    counts = record.get("failures")
    if isinstance(counts, dict):
        n = counts.get(rung)
        return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0
    if record.get("action") == ACTION_PASS:
        return 0
    was = (RUNG_DECLARATION if record.get("action") in (ACTION_REJECT_PAIR,)
           or record.get("sides_from") != "script" else RUNG_CAPACITY)
    return 1 if was == rung else 0


def rejection_reason(script, record):
    """The written reason for `rotation/rotate.py reject`, ready to be pasted.

    It is about *this* script, which is what R2 requires and what the guard
    reads: the rhythm, what it demands, and the arithmetic of why this fact
    cannot answer it. The writer may say it better - it is their rejection -
    but a reason nobody had to compose is a reason that gets written.
    """
    reading, sides = record["per_side"], record["sides"]
    # Whichever side the fallback is actually failing to deliver, and only
    # then the one with less to picture: the point of the reason is the
    # damage, not the arithmetic that predicted it.
    trouble = thin_side(reading)
    thin = trouble[0] if trouble else (
        "b" if reading["b"]["anchors_answered"] <= reading["a"]["anchors_answered"] else "a")
    other = "a" if thin == "b" else "b"
    where = (f" - the two source files ({', '.join(sorted(sides))}) stood in for the "
             f"sides that were not written" if sides else "")
    return (
        f"The assigned rhythm `{RHYTHM}` crosses an axis between two sides, and this "
        f"script has none to cross: all {record['anchors']} visual anchors carry "
        f"`side: null`, and a rewrite asking for them came back the same{where}. "
        f"The alternation demands side '{thin}' in {reading[thin]['slots']} of "
        f"{record['predicted_blocks']} blocks while only {reading[thin]['anchors_answered']} "
        f"anchor(s) can be pictured there at all (against "
        f"{reading[other]['anchors_answered']} on '{other}'): "
        f"{reading[thin]['swung']} block(s) would swing back to the other side and "
        f"{reading[thin]['empty']} would end with no picture. This fact has no second side "
        f"a viewer can tell apart on screen, so `{RHYTHM}` has nothing to alternate "
        f"between.")


def judge(script, report, plan, spans, constants, floors):
    """One script's record - the ladder of the module docstring."""
    blocks = plan.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise CannotJudge(
            f"{script.get('script_id')}: the Editor's planner returned no blocks"
            + (f" ({plan.get('error')})" if plan.get("error") else "")
            + f" - without a block plan there are no slots per side to judge")
    declared = bool(plan.get("declared_sides_usable"))
    sides = None if declared else footage_sides(report)
    handed = hand_out(blocks, report, spans, constants, sides, floors,
                      plan.get("shot_budget"))
    reading = per_side(handed, report, sides, declared, declared_sides(script))
    failures = {RUNG_DECLARATION: previous_failures(script, RUNG_DECLARATION),
                RUNG_CAPACITY: previous_failures(script, RUNG_CAPACITY)}
    failed_before = failures[RUNG_DECLARATION if not declared else RUNG_CAPACITY]
    written = [s for s in declared_sides(script) if s]

    record = {
        "topic_id": script.get("topic_id"),
        "anchors": len(script.get(FIELD) or []),
        "rhythm": (script.get("pattern") or {}).get("rhythm_id"),
        "pattern_id": (script.get("pattern") or {}).get("pattern_id"),
        "sides_declared": sorted(set(written)),
        "anchors_with_a_side": len(written),
        "sides_from": "script" if declared else ("footage" if sides else None),
        "sides": sides,
        "predicted_blocks": len(blocks),
        "per_side": reading,
        "margin_required": POOL_MARGIN_FRAGILE_BLOCKS,
        "blocks": handed,
        "failures": dict(failures),
        "failed_attempts": sum(failures.values()),
        "rewrites_allowed": REWRITES_ALLOWED,
    }

    def spend(rung):
        """One more failure on this rung, and the totals that follow it."""
        record["failures"][rung] = failures[rung] + 1
        record["failed_attempts"] = sum(record["failures"].values())

    if not declared:
        # Nothing about the pool can make this a pass: the sides the montage
        # will swing between were chosen by which file a frame came out of,
        # which is not a comparison anybody wrote (CF-0050).
        have = (f"only side {written[0]!r} is declared, on "
                f"{len(written)} anchor(s) - one side is not a comparison"
                if written else f"all {record['anchors']} anchor(s) carry `side: null`")
        fallback = (
            f"so the Editor takes the sides from the footage instead ("
            + ", ".join(f"{src} = {side!r}" for src, side in sorted(sides.items(),
                                                                    key=lambda kv: kv[1]))
            + f") and alternates by block parity: side 'a' in {reading['a']['slots']} "
              f"block(s), side 'b' in {reading['b']['slots']}, against "
              f"{reading['a']['anchors_answered']} and {reading['b']['anchors_answered']} "
              f"anchor(s) that can be pictured on them"
            if sides else
            "and the pool has no second source to fall back to either, so the plan would "
            "be rebuilt as `even` and the alternation simply would not happen")
        if failed_before >= REWRITES_ALLOWED and sides:
            spend(RUNG_DECLARATION)
            record.update(action=ACTION_REJECT_PAIR)
            record["reason"] = (
                f"{have} after {failed_before} rewrite(s) asking for them, {fallback}. "
                f"A fact with no second side does not fit `{RHYTHM}`: reject the assignment "
                f"in writing and write with the pair the rotation hands back")
            record["rejection_reason"] = rejection_reason(script, record)
            return record
        spend(RUNG_DECLARATION)
        record.update(action=ACTION_REWRITE, reason=(
            f"`{RHYTHM}` swings between two sides and this script declares none: {have}, "
            f"{fallback}. Mark each anchor `side: \"a\"` or `\"b\"` by what it shows - a "
            f"side is two things the viewer can tell apart on screen, not two files - and "
            f"leave a moment that is on neither unmarked. If this fact has no second side, "
            f"say so and reject the assignment instead: the rhythm, not the writing, is "
            f"what does not fit"))
        return record

    trouble = thin_side(reading)
    if trouble is None:
        record.update(action=ACTION_PASS, reason=(
            f"both sides carry what the writing asks of them: side 'a' fills "
            f"{reading['a']['filled']} of {reading['a']['slots']} block(s), side 'b' "
            f"{reading['b']['filled']} of {reading['b']['slots']}, "
            f"{sum(reading[s]['fragile'] for s in SIDES)} on their last candidate "
            f"(margin {POOL_MARGIN_FRAGILE_BLOCKS})"))
        return record

    side, what, count = trouble
    other = "a" if side == "b" else "b"
    mine, theirs = reading[side], reading[other]
    said = (f"side {side!r} is asked for {mine['slots']} of the {len(blocks)} crossing(s) "
            f"this script makes and its anchors offer {mine['distinct_candidates']} distinct "
            f"usable frame(s) under one-sample-one-use (CF-0121): {count} {what}")
    # CF-0330: which rung answered, and the measurement alone - a capacity
    # answer is the one that warns (`check_batch`); a missing axis does not.
    record["rung"] = RUNG_CAPACITY
    record["finding"] = said
    if failed_before >= REWRITES_ALLOWED:
        spend(RUNG_CAPACITY)
        record.update(action=ACTION_REFUSE, reason=(
            f"{said} - and this script has already been rewritten {failed_before} time(s) "
            f"for it. The footage of this topic does not hold two sides of a comparison "
            f"this long"))
        return record
    # The ceiling is what the side actually filled, not what it holds: a side
    # with frames to spare and an empty block has not run out of footage, it
    # has one moment the pool cannot picture, and telling the writer to cross
    # fewer times than it holds would be a number with nothing behind it.
    ceiling = max(1, mine["filled"])
    spend(RUNG_CAPACITY)
    record.update(action=ACTION_REWRITE, reason=(
        f"{said}. The lever is the crossings, not the anchor count: every crossing onto "
        f"{side!r} owes that side another distinct frame, and side {other!r} has "
        f"{theirs['distinct_candidates']} to spend against {theirs['slots']} slot(s). "
        f"Side {side!r} fills {mine['filled']} of its {mine['slots']} slot(s) as written, "
        f"so cross onto it at most {ceiling} time(s) - consecutive moments on one side are "
        f"one crossing, so keep them together instead of going back and forth"
        + (f" - or replace the {side!r} moments the pool cannot picture (below)"
           if mine["distinct_candidates"] >= mine["slots"] else "")))
    return record


def skip_entry(script, record):
    """The `skipped[]` entry a refusal writes - CF-0232's shape, with a
    `reason` written to be read alone: the funnel copies it verbatim."""
    return {
        "topic_id": script.get("topic_id"),
        "reason_code": SKIP_REASON_CODE,
        "reason": f"{script.get('script_id')}: {record['reason']}",
        "stage": FUNNEL_STAGE,
        "anchors": record["anchors"],
        "predicted_blocks": record["predicted_blocks"],
        "per_side": record["per_side"],
        "failed_attempts": record["failed_attempts"],
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

HEADS = {ACTION_PASS: "  ok    ", ACTION_REWRITE: "  REWRITE",
         ACTION_REJECT_PAIR: "  UNFIT ", ACTION_REFUSE: "  REFUSE", gw.ACTION_WARN: "  WARN   "}


def script_lines(script, record, channel, batch_id=None):
    """The lines for one judged script."""
    sid = script.get("script_id")
    lines = [f"{HEADS[record['action']]} {sid}: {record['anchors']} anchor(s) -> "
             f"{record['predicted_blocks']} block(s) ({record['pattern_id']}/{RHYTHM}), "
             f"sides from {record['sides_from'] or 'nowhere'}"
             + (f" ({', '.join(record['sides_declared'])} declared on "
                f"{record['anchors_with_a_side']} anchor(s))"
                if record["sides_declared"] else " (none declared)")]
    for side in SIDES:
        r = record["per_side"][side]
        lines.append(f"      side {side!r}: {r['slots']} slot(s), {r['seconds']} s, "
                     f"{r['distinct_candidates']} distinct usable frame(s), "
                     f"{r['anchors_answered']} anchor(s) picturable there; "
                     f"{r['filled']} filled, {r['swung']} swung back, {r['empty']} empty, "
                     f"{r['fragile']} on their last candidate")
    for h in record["blocks"]:
        if h["empty"] or h["swung"]:
            lines.append(
                f"      block {h['block']} ({h['seconds']} s, side {h['side']!r}, "
                f"anchor #{h['anchor']}): "
                + (h["reason"] if h["empty"] else
                   "nothing on this side survived the cut - the Editor fills it from the "
                   "other side and the block carries no side, so the alternation is not "
                   "delivered here"))
    if record["action"] == gw.ACTION_WARN:
        for w in record.get("warnings") or []:
            lines.append(gw.line(w))
    elif record["action"] != ACTION_PASS:
        lines.append(f"    {record['reason']}")
    if record["action"] == ACTION_REJECT_PAIR:
        lines.append("    the reason, ready for the rotation:")
        lines.append("      " + REJECT_CMD.format(
            channel=channel or "<channel>", sid=sid, batch_id=batch_id or "<batch-id>",
            reason=record["rejection_reason"].replace('"', "'")))
        lines.append("    the guard rules on it (R1-R5); say the verdict in your report, "
                     "denial included")
    return lines


# --------------------------------------------------------------------------
# the batch
# --------------------------------------------------------------------------

def check_batch(batch_file, reports_file, root=None, footage_index=None, script_id=None,
                out=print, write=False, editor_python=None, planner=None,
                editor_scripts=None, timeout=DEFAULT_TIMEOUT, resolver=None):
    """Judge every `alternate` script of the batch.

    Returns `(problems, records, refused, rejects)`. One child process for the
    whole batch (the Editor's planner) and no other cost: the candidate lists
    come out of the coverage reports `check_anchor_coverage.py --out` wrote.
    """
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotJudge(f"cannot read {batch_file}: {exc}")
    channel = resolve_channel(data.get("channel"), root)
    # CF-0383: the ledger keys an assignment on (batch, script_id) - a repeat batch
    # carries its parent's script ids - so the rejection names this batch: the
    # directory, the same <batch-id> step 3 passed to `rotate.py assign`.
    batch_id = Path(batch_file).resolve().parent.name
    sections = counted_sections(channel, root) if channel else FALLBACK_SECTIONS
    reports = load_reports(reports_file)

    scripts = [s for s in data.get("scripts", [])
               if script_id is None or s.get("script_id") == script_id]
    # CF-0689: the channel's switch for its own graphics; an all-graphic
    # batch needs no footage index, an all-graphic script no pool.
    draws = ogl.channel_draws(channel, root)
    index_path, index_data = load_footage_index_for(batch_file, footage_index, scripts, draws)
    mine = [s for s in scripts
            if ((s.get("pattern") or {}).get("rhythm_id")) == RHYTHM]
    mine_ids = {id(s) for s in mine}
    # CF-0430: the rewrite this gate asked for, not made - judged no again.
    held = []
    mine, _unchanged, same = rg.split(mine, RECORD_KEY, sections, held.append, write)

    out(f"{batch_file}: {len(mine)} of {len(scripts)} script(s) drew `{RHYTHM}`; the axis is "
        f"the script's (CF-0050) and whether it was declared is the Editor's own "
        f"`rhythm.declared_sides_usable()`, asked through plan_blocks.py on its venv; slots "
        f"per side come from the Editor's block plan, never from parity recomputed here; "
        f"candidate lists from {Path(reports_file).name}; one sample one use (CF-0121); "
        f"no sides: one rewrite, then the assignment is rejected; a thin side is a "
        f"`{SKIP_REASON_CODE}` warning and the script goes on (CF-0330)")
    for script in scripts:
        if id(script) not in mine_ids:
            out(f"  --      {script.get('script_id')}: rhythm "
                f"{(script.get('pattern') or {}).get('rhythm_id')!r}, not `{RHYTHM}` - "
                f"sides are this rhythm's question and nothing is claimed about it")
    for line in held:
        out(line)
    if not mine:
        if write and same:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        return list(same), {}, [], []

    entries = []
    for script in mine:
        starts, total, word_starts, sides, _rate, _src = anchor_times(
            script, sections, channel, root)
        entries.append({"script_id": script.get("script_id"), "anchor_starts": starts,
                        "total": total, "word_starts": word_starts,
                        "order": script.get("pattern"), "anchor_sides": sides})

    paths = planner_paths(root, editor_python, planner, editor_scripts)
    plans, constants = run_planner(entries, paths, timeout)

    problems, records, refused, rejects, warnings = list(same), {}, [], [], []
    for script in mine:
        sid = script.get("script_id")
        report = graphic_scope(report_for(script, reports), draws)
        plan = plans.get(sid)
        if not isinstance(plan, dict):
            raise CannotJudge(f"{sid}: the Editor's planner returned no plan for this script")
        pool = topic_pool_for(index_path, index_data, script, draws)
        # CF-0291: the same floors the other two replays run at, off the
        # report and the Editor's own source. A side's slots are counted over
        # the candidates a block may actually be offered.
        record = records[sid] = judge(script, report, plan, shot_spans(pool["indexes"]),
                                      constants, editor_floors(report, root, resolver))
        record["warnings"] = []
        if (record.get("rung") == RUNG_CAPACITY
                and record["action"] in (ACTION_REWRITE, ACTION_REFUSE)
                and gw.warns(gw.GATE_ALTERNATE_SIDES)):
            # CF-0330: a side too thin for its slots is the Editor's
            # `assetless_rung` seen early, and that gate warns now. The axis
            # rung (no sides declared) is a question about the writing and is
            # not touched.
            record["would_have"] = record["action"]
            record["action"] = gw.ACTION_WARN
            record["failures"][RUNG_CAPACITY] = previous_failures(script, RUNG_CAPACITY)
            record["failed_attempts"] = sum(record["failures"].values())
            record["warnings"] = [gw.entry(
                script.get("topic_id"), sid, gw.GATE_ALTERNATE_SIDES, SKIP_REASON_CODE,
                f"{record['finding']}. Before CF-0330 this was a {record['would_have']}; now "
                f"a warning - the script goes on as written, and a block its side cannot "
                f"fill is the Editor's `assetless_rung` warning",
                numbers={k: record.get(k) for k in (
                    "anchors", "pattern_id", "sides", "sides_from", "predicted_blocks",
                    "per_side", "margin_required", "failures", "would_have")})]
            # CF-0342: what the pool is short of, by entity - the request
            # skeleton `--write` puts under work/supplement-requests/.
            record["warnings"][0][sreq.FIELD] = sreq.from_sides(script, record)
            warnings.extend(record["warnings"])
        for line in script_lines(script, record, channel, batch_id):
            out(line)
        if record["action"] == ACTION_REWRITE:
            problems.append(f"{sid}: {record['reason']}")
        elif record["action"] == ACTION_REJECT_PAIR:
            rejects.append(script)
        elif record["action"] == ACTION_REFUSE:
            refused.append(script)

    if write:
        for script in mine:
            record = records.get(script.get("script_id"))
            if record:
                script[RECORD_KEY] = rg.stamp(record, script, sections)
        gw.clear(data, [s.get("topic_id") for s in mine if s.get("script_id") in records],
                 gw.GATE_ALTERNATE_SIDES)
        gw.record(data, warnings)
        for line in sreq.lines(*sreq.sync(
                path.parent, data,
                [s.get("topic_id") for s in mine if s.get("script_id") in records])):
            out(line)
        if refused:
            ids = {id(x) for x in refused}
            data["scripts"] = [x for x in data.get("scripts", []) if id(x) not in ids]
            data.setdefault("skipped", [])
            for script in refused:
                data["skipped"].append(skip_entry(script, records[script.get("script_id")]))
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        out(f"  wrote {batch_file}: `{RECORD_KEY}` on {len(records)} script(s)"
            + (f", {len(warnings)} warning(s) in `{gw.WARNINGS_FIELD}[]`" if warnings else "")
            + (f", {len(refused)} topic(s) moved to skipped[] as `{SKIP_REASON_CODE}`"
               if refused else "")
            + (f"; {len(rejects)} assignment(s) are the rotation's to replace and nothing "
               f"was moved for them - the topic did not fail, the pair did" if rejects else ""))
    else:
        if warnings:
            out(gw.NOT_RECORDED.format(n=len(warnings)))
        if refused:
            out(f"  note: {len(refused)} topic(s) are refused as `{SKIP_REASON_CODE}` but "
                f"nothing was recorded - re-run with --write so the funnel sees the loss")
    return problems, records, refused, rejects


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--reports", required=True,
                    help="the JSON `check_anchor_coverage.py --out` wrote for this batch")
    ap.add_argument("--footage-index", default=None,
                    help="the batch's 01b-footage-index.json (default: beside the batch file)")
    ap.add_argument("--script-id", default=None, help="judge one script instead of the batch")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    ap.add_argument("--resolver", default=None,
                    help="the Video Editor's resolve_anchors.py (default: under --root). Read, "
                         "never imported and never run: the similarity floor and the shortest "
                         "cut of the replay are its own constants (CF-0291)")
    ap.add_argument("--out", default=None, help="write the records here as JSON")
    ap.add_argument("--editor-python", default=None,
                    help="interpreter for the Video Editor's planner (default: its .venv)")
    ap.add_argument("--planner", default=None,
                    help="path to plan_blocks.py (default: this repository's)")
    ap.add_argument("--editor-scripts", default=None,
                    help="the Video Editor's scripts/ (default: the checkout's)")
    ap.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    ap.add_argument("--write", action="store_true",
                    help="record the reading on every `alternate` script - which is where "
                         "the one allowed rewrite is counted between runs - and write a thin "
                         "side into warnings[] as `pool_too_thin` (CF-0330)")
    args = ap.parse_args(argv)
    try:
        problems, records, refused, rejects = check_batch(
            args.batch_file, args.reports,
            root=Path(args.root).resolve() if args.root else None,
            footage_index=args.footage_index, script_id=args.script_id, write=args.write,
            editor_python=args.editor_python, planner=args.planner,
            editor_scripts=args.editor_scripts, timeout=args.timeout,
            resolver=args.resolver)
    except CannotAnswer as exc:
        print(f"check_alternate_sides.py: {exc}", file=sys.stderr)
        print("nothing is claimed about the scripts; do not rewrite anything on this run",
              file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if args.out:
        Path(args.out).write_text(json.dumps(records, indent=2, ensure_ascii=False))
    warned = [w for r in records.values() for w in (r.get("warnings") or [])]
    if warned:
        print(f"\n{len(warned)} warning(s) - the script(s) go on, nothing to rewrite "
              f"({gw.DECISION}):")
        for w in warned:
            print(gw.line(w))
    if problems:
        print(f"\n{len(problems)} script(s) to rewrite:")
        for p in problems:
            print(f"  - {p}")
    if refused:
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}` - one side of the "
              f"comparison has less footage than the writing asks of it"
              + ("" if args.write else "; nothing was recorded (--write)"))
        for script in refused:
            print(f"  - {script.get('script_id')}: "
                  f"{records[script.get('script_id')]['reason']}")
    if rejects:
        print(f"\n{len(rejects)} assignment(s) to reject - `{RHYTHM}` has no axis in this "
              f"fact, and the replacement is the rotation's to choose, never yours")
        for script in rejects:
            print(f"  - {script.get('script_id')}: "
                  f"{records[script.get('script_id')]['rejection_reason']}")
    if rejects:
        return EXIT_REJECT
    if problems:
        return EXIT_REWRITE
    return EXIT_REFUSED if refused else EXIT_OK


@runlog.script("content-researcher", "check-alternate-sides", name="check_alternate_sides.py")
def cli():
    """The command-line entry (CF-0107). One `child` event: the Editor's block
    planner, once for the whole batch. No model, no CLIP, no ffmpeg."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
