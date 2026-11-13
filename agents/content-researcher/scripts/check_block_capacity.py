#!/usr/bin/env python3
"""CF-0284: can the pool fill the BLOCKS this script will be cut into - asked
before the voice is paid for.

The hole
--------
`check_anchor_coverage.py` (CF-0274) measures the pool against the script's
**anchors**: 57 distinct usable samples for 21 anchors, 36 of margin over the
12 required, pass. The Video Editor does not hand shots to anchors. It hands
one distinct shot to every **block** (CF-0121: one sample, one use; CF-0137:
one emergency repeat per video; CF-0074: none at all inside a `swing` block),
and a rhythm makes as many blocks as it likes out of one anchor.

`example-film/2026-09-18T2232Z`, `lf-2026-09-18-006-script1` (Famine Trials,
`list`/`staccato`) is the case. 21 anchors, 51.3 s of speech, so 2.443 s
between anchors; the pattern drew a 1.92 s hold ceiling, and
`rhythm._plan_staccato()` divides every anchor's stretch by that ceiling::

    by_cap = max(1, math.ceil(_dur(s) / cap - 1e-9))

`ceil(2.443 / 1.92) = 2`, twenty-one times over: **41 blocks** for 21 anchors.
Eight of them ended with no picture and the plan was refused as
`pattern_undeliverable` - after TTS, after alignment, after the resolve.
`carrying_capacity()` in the coverage gate says so in its own docstring ("a
video has more blocks than the script has anchors"); this file is that gap.

The block plan, by calling the rule and not copying it
------------------------------------------------------
`scripts/plan_blocks.py` runs on the Video Editor's venv and asks
`rhythm.plan_segments()` itself - the same function that will cut the real
video - for the block boundaries, roles, sides and per-block shot budgets.
Nothing about staccato's ceiling, `alternate`'s even rounding or `hold`'s
acceleration is written down in this repository, and the Editor's reuse and
cut constants travel back with the plan rather than being restated here.

What this gate has to supply is where the anchors sit **in time**, and before
TTS that is an estimate: word *k* is placed at `k / words_per_second` with this
script's own rate (CF-0279, `check_anchor_cadence.speech_rate()` - the
estimator's reading of this very text, not the channel median). Measured
against the Editor's real `words.json` on `2026-09-18T2232Z`, an anchor lands
within 0.64 s on average (Famine Trials), 0.79 s (Delver), 1.74 s (Traitors) of
where the wav put it, and the block counts come out 42 / 8 / 10 against a real
41 / 8 / 10. The one block of difference is Famine Trials' first anchor, whose
stretch reads 1.893 s in the wav against 2.443 s predicted - just under the
1.92 s ceiling instead of just over it. The error is on the safe side: a gate
that refuses may overcount blocks, it may not undercount them.

The hand-out, replayed
----------------------
`check_two_sources.py` (CF-0280) already replays the resolve per anchor. This
is the same replay per **block**, which is the unit that actually needs a
picture:

  * the candidate order is the preflight's `anchors[].samples` - the
    resolver's own `order_candidates()` order, already screened by the
    resolver's own pre-cut gate, which is where the Indexer's cached usability
    (`usable_cached`, and CF-0275's `text_cut_by_crop`) is applied;
  * a block's candidates are its **driver anchor**'s (`resolve_anchors.
    driver_anchor()`: the first anchor of the segment, except under `hold`
    where it is the anchor that found the best-scoring frame);
  * `alternate` filters them by side only when the side came from the
    *footage*. With no side declared the Editor partitions by source
    (`footage_sides()`: the two sources with the most candidates that survive
    the cached pre-filter), and so does this; when the script declared its
    sides (CF-0050, CF-0285) nothing is filtered at all, because the anchor's
    phrase already is the side. Which rule applies is the Editor's own
    `declared_sides_usable()`, answered by `plan_blocks.py` beside the plan;
  * long enough first when the block may hold one shot, exactly as
    `resolve_anchors.py` sorts it; a swing block takes several distinct shots
    up to `rhythm.swing_shot_budget()`, which the plan carries as `max_shots`;
  * one sample, one use (CF-0121). A sample an earlier block took is gone;
  * one emergency repeat for the whole video (CF-0137), refused outright
    inside a `swing` block and next to its own first use.

Output per script: the predicted blocks, the blocks that end with no picture,
and why each one did - the anchor's pool empty (with the Editor's own refusal
sentences behind it), every usable frame already spent, or nothing on this
block's side.

The margin, and what it is for
------------------------------
The replay under-counts, on purpose and by a known amount. What it cannot see
is what only exists once a clip is cut: `usable()` on the cut clip, which on
the six predictable empty blocks of Famine Trials is about 7 % of the refusals
(the rest being the cached pre-filter at ~66 % and reuse-once at ~27 %). So
the replay predicted 4 of the 8 empty blocks there and 1 of the 2 on Traitors.

The margin is therefore not a count of spare samples but a count of blocks
with no second choice. A **fragile** block is one whose pool held nothing
beyond what it took: it is one framing failure away from being empty, and a
framing failure is exactly the thing that cannot be known here. Over the seven
scripts on disk that carry a preflight report (`2026-09-18T1058Z` and
`2026-09-18T2232Z`):

    script                       empty  fragile   what happened
    delver      2232Z            0      0         rendered
    delver      1058Z            0      0         filled all 7 blocks
    traitors    1058Z            1      3         pattern_undeliverable (3)
    traitors    2232Z            1      4         pattern_undeliverable (2)
    famine-trials 2232Z           4      6         pattern_undeliverable (8)
    famine-trials 1058Z           3      7         held back with the batch
    pine-park  1058Z           13      2         pool_too_thin (CF-0274)

Both readings separate the two that filled every block from the five that did
not, and nothing sits between: zero fragile blocks against two and up.
`POOL_MARGIN_FRAGILE_BLOCKS = 1` is the top of that gap - one block may stand
on its last candidate, two may not.

What happens to `POOL_MARGIN_ANCHORS = 12`
------------------------------------------
Kept, as a floor, and no longer the measure. It is the coverage gate's own
question - can this pool picture these anchors at all - and it is answered
before there is a block plan to speak of, including for a script whose beats
cannot be located in the narration (no positions, no plan, no replay). But it
decides nothing here: Famine Trials cleared it by 36 and still died. On the
seven scripts above it never refuses anything this gate would pass, so it
costs nothing to keep and it is the only answer left when the plan cannot be
built.

The ladder
----------
The cadence gate's, for the fourth time (CF-0233, CF-0274, CF-0280):

  * every predicted block gets a distinct picture and at most
    `POOL_MARGIN_FRAGILE_BLOCKS` of them stand on their last candidate - pass;
  * a block ends empty, or too many are fragile, and a rewrite is left -
    **rewrite**, once, with the number the pool can carry at this rhythm: how
    many anchors, and - when the rhythm makes more blocks than anchors - the
    block count the script cannot go under at the hold it drew, and the anchor
    spacing that reaches it;
  * the pool carries no anchor at all, or the one rewrite is spent -
    **refuse**. The topic leaves the batch as `pool_too_thin` (CF-0274's code
    for this loss, already in the funnel) before TTS.

**CF-0330 (the user, 2026-09-23): warn, not refuse.** The Video Editor's
`assetless_rung` / `pattern_undeliverable` - the gate this file predicts - is a
warning now, so the prediction is too. Both rungs of the ladder above (rewrite,
refuse) write a `warnings[]` entry with the same code (`pool_too_thin`) and the
numbers (predicted blocks, the empty and fragile ones, what the pool carries,
`would_have`), the script stays, nothing is rewritten, and the exit is 0. The
ladder is still computed; `_gate_warning.WARN_GATES` switches it back.

Usage:

    python3 scripts/check_anchor_coverage.py <03-content-researcher.json> \
        --out <reports.json>
    python3 scripts/check_block_capacity.py <03-content-researcher.json> \
        --reports <reports.json> [--write] [--root <checkout>]

Exit codes:

    0  every script's pool fills every block its rhythm will cut, or the
       shortfall was recorded as a `pool_too_thin` warning (CF-0330)
    1  at least one script is sent back to be rewritten shorter (only with
       the gate switched back out of `_gate_warning.WARN_GATES`)
    3  cannot answer: no reports, stale reports, no footage index, no block
       plan from the Editor. Nothing about the scripts is claimed.
    4  at least one topic is refused as `pool_too_thin` and (with `--write`)
       recorded in `skipped[]`; there is nothing to rewrite. (Only with the
       gate switched back - since CF-0330 this is a warning.) Since CF-0449
       the picture band never gets here.
    5  no longer written (CF-0449): until 2026-10-02 the picture band
       (CF-0365) rejected the assignment here; it is priced now
       (`score.block_band_exceeded`, `band: PRICED`) and the exit is 0.

The picture band (CF-0365)
--------------------------
The pattern's block band read over the **pictures** this replay hands out,
not over the rhythm's segments (which is what `check_anchor_cadence.py`'s
`block_band` reads, and which is a floor under the delivered count, never a
forecast of it). `lf-2026-09-23-004` of `example-film/2026-09-23T1722Z` is the
case: 11 segments inside `moment-breakdown`'s 6-12, 21 pictures handed out
here, 22 blocks refused by the Editor after the TTS. See `picture_verdict()`.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
import _gate_warning as gw  # noqa: E402
import _supplement_request as sreq  # noqa: E402
import _rewrite_guard as rg  # noqa: E402
import _score  # noqa: E402 - CF-0433: the score model (shared/score)

from check_anchor_coverage import (  # noqa: E402
    FALLBACK_SECTIONS, FIELD, FUNNEL_STAGE,
    VERDICT_WEAK, CannotAnswer, counted_sections, refusal_summary)
from check_anchor_cadence import (  # noqa: E402,F401 - `anchor_times` is re-exported
    anchor_times, anchor_word_index, narration_words, speech_rate)
from check_anchor_cadence import blocks_over as _blocks_over  # noqa: E402 - CF-0449
from check_two_sources import (  # noqa: E402
    CannotJudge, editor_floors, load_reports, report_for, sample_score,
    screened_samples, shot_spans, under_floor)
from check_anchor_coverage import load_footage_index, topic_pool  # noqa: E402
from check_anchor_coverage import (  # noqa: E402 - CF-0689
    GRAPHIC_INDICES_KEY, load_footage_index_for, topic_pool_for)
import _own_graphic as ogl  # noqa: E402 - CF-0689
# `find_root` is not used here since CF-0277 moved the planner paths out; it
# stays an attribute of this module because that is where its callers and
# tests have always reached for it.
from check_narration_budget import find_root  # noqa: E402,F401
from _planner import (  # noqa: E402,F401 - re-exported, see below
    DEFAULT_TIMEOUT, EDITOR_SCRIPTS_REL, PLANNER_REL, planner_paths, run_planner)

# CF-0274's code, reused rather than invented: a pool that cannot picture the
# video is the same loss whether it is counted in anchors or in blocks, and the
# funnel already carries it (`shared/runlog/funnel.py`, CF-0232).
SKIP_REASON_CODE = "pool_too_thin"
RECORD_KEY = "block_capacity"

# How many blocks may stand on their last candidate and still pass. The gap in
# the data is 0 against 2 (module docstring): everything that filled its blocks
# has none, everything that died has two or more. One is the top of that gap -
# strictly the largest number that still separates the two groups, and the
# reserve is for the one refusal a preflight cannot see (framing on the cut
# clip, ~7 % of the refusals behind the real empty blocks).
POOL_MARGIN_FRAGILE_BLOCKS = 1

# One, like every other rung of this stage: a script that has already been
# rewritten once for this and still cannot fill its blocks is a topic with too
# little footage, not a writing problem.
REWRITES_ALLOWED = 1

# The probe entry that rides along in the same payload (`probe_positions()`):
# a script id no script can have, so it can never be mistaken for one.
PROBE_SUFFIX = "::at-hold"

REPORT_KIND = "anchor_coverage_preflight"

ACTION_PASS, ACTION_REWRITE, ACTION_REFUSE = "pass", "rewrite", "refuse"
EXIT_OK, EXIT_REWRITE, EXIT_CANNOT_ANSWER, EXIT_REFUSED = 0, 1, 3, 4

# CF-0365: the picture band - see picture_verdict(). Its own record inside this
# one, its own ladder and its own exit, the sides gate's (`check_alternate_sides`
# EXIT_REJECT): the assignment is what does not fit, so the one attempt is a
# rejection of it, and a script whose next assignment is still over the band is
# a topic this pool cannot make a video of.
PICTURE_KEY = "picture_band"
ACTION_REJECT = "reject"
PICTURE_NOTE = "note"
# CF-0449: over the top by more than the replay's error - priced
# (`score.block_band_exceeded`), the script goes on. ACTION_REJECT / EXIT_REJECT
# stay as names (older records carry `reject`), the picture band writes neither.
PICTURE_PRICED = "priced"
EXIT_REJECT = 5
PICTURE_ATTEMPTS_ALLOWED = 1
REJECT_CMD = ("python3 ~/shorts-content-factory/rotation/rotate.py reject {channel} {sid} "
              "--batch-id {batch_id} "
              "--reason \"{reason}\"")

# How far the replay's picture count may run over what the resolver really
# cuts, measured on every script on disk that carries both numbers (the
# replay's `block_capacity.blocks[].shots` and the Editor's storyboard), all of
# them from 2026-09-19 on:
#
#     batch / script                     pattern/rhythm      replay  real
#     2026-09-19T0116Z  -008             list/staccato         23     23
#     2026-09-21T0358Z  -007             contrast/alternate    22     16
#     2026-09-21T1541Z  -009             explainer/even         9     10
#     2026-09-23T1722Z  -001             moment-breakdown/hold  7      8
#     2026-09-23T1722Z  -004             moment-breakdown/even 21     22
#     2026-09-23T1722Z  -005             explainer/even        17     14
#     2026-09-23T1722Z  -006             explainer/alternate   15     12
#     rebuilds/2026-09-23T1344Z  -002    list/staccato         15     22
#
# The error has both signs, so - unlike the segment count, which is a floor -
# a replayed count just over the band's top is not evidence the video will be
# over it. 22 against 16 is the worst overcount, so a reading refuses only
# when it is over the top by more than that: 12 blocks x 22/16 = 16.5 on
# `moment-breakdown`, which 004's 21 clears and nothing that shipped comes near.
PICTURE_OVERCOUNT_RATIO = 22 / 16
PICTURE_OVERCOUNT_SOURCE = ("2026-09-21T0358Z lf-2026-09-21-007: 22 shots replayed "
                            "against 16 blocks cut, the worst of 8 scripts measured (CF-0365)")

# Why a block ended with no picture, in the wording that reaches the writer.
WHY_NO_FRAME = "no_usable_frame"
WHY_ALL_SPENT = "every_frame_already_used"
WHY_WRONG_SIDE = "nothing_on_this_side"
# CF-0291: the one this task added. The pool ranked frames for this anchor and
# every one of them is under the Editor's similarity floor, so `screen_pool()`
# takes them all out and the block is offered nothing. Its own word, because
# the remedy is the opposite of the others': not more footage and not fewer
# anchors, but this anchor rewritten at a frame the pool actually holds.
WHY_UNDER_FLOOR = "nothing_over_the_similarity_floor"

# How many of the pool's own shots a rewrite prints. The blind cycle CF-0140
# removed: a writer told "rewrite this anchor" and not told what the pool has
# writes the same anchor again.
EVIDENCE_SHOWN = 8


# --------------------------------------------------------------------------
# where the anchors sit in the speech, in seconds
#
# `anchor_times()` was written here and moved to `check_anchor_cadence.py` by
# CF-0277, which needed the same estimate one gate earlier; it is imported
# above and stays an attribute of this module for its callers.
# --------------------------------------------------------------------------

# --------------------------------------------------------------------------
# the Editor's planner, as a child process
# --------------------------------------------------------------------------

# `planner_paths()` and `run_planner()` were written here and moved to
# `_planner.py` by CF-0277, when `check_anchor_cadence.py` - which runs before
# this gate and knows nothing about the pool - needed the same call. They are
# re-exported so that this module's callers (and `check_alternate_sides.py`)
# keep the import they had; there is still one copy of the call.


# --------------------------------------------------------------------------
# the replay
# --------------------------------------------------------------------------

def footage_sides(report):
    """`{source: "a"|"b"}` - the partition `alternate` swings between when the
    script declared no sides.

    `resolve_anchors.footage_sides()` counts, per source, the candidates that
    the cached usability pre-filter does **not** condemn, and calls the two
    commonest sources the two sides. The preflight's `samples` are exactly
    those survivors, so the same count is available here without a second
    pass over the index.
    """
    counts = Counter()
    for rec in report.get("anchors") or []:
        for sample in rec.get("samples") or []:
            counts[sample.rsplit(":", 1)[0]] += 1
    top = [source for source, _ in counts.most_common(2)]
    return {top[0]: "a", top[1]: "b"} if len(top) >= 2 else None


def driver_anchor(block, report):
    """Which anchor of a merged block supplies the picture - `hold` takes the
    one that found the best-scoring frame, every other rhythm the first
    (`resolve_anchors.driver_anchor()`)."""
    anchors = block.get("anchors") or []
    if block.get("role") != "hold" or len(anchors) <= 1:
        return anchors[0] if anchors else None
    best = {r.get("anchor_index"): (r.get("best_offered_score") or -1.0)
            for r in report.get("anchors") or []}
    return max(anchors, key=lambda i: best.get(i, -1.0))


def gate_threw_out(rec):
    """What the Editor's own gate refused for this anchor, in its own words.

    The sentence behind two thirds of the real empty blocks: the anchor's pool
    is short here not because the writing is vague but because the Indexer's
    cached usability condemned most of its candidates before a frame was cut
    (CF-0029, and CF-0275's `text_cut_by_crop`). Reading it out of the
    preflight's `refusals[]` costs nothing and is the difference between "find
    other words" and "this source cannot be cut into 9:16".
    """
    total, ranked = refusal_summary({"anchors": [rec]}, limit=2)
    if not total:
        return ""
    detail = "; ".join(f"{n} x {reason}" for reason, n, _ in ranked)
    return f"; the Editor's gate had already thrown out {total} candidate(s) here ({detail})"


def why_empty(rec, side, sides, taken, samples, floor):
    """Why this block found nothing, in one of four words and a sentence.

    `samples` is the anchor's **screened** pool (CF-0291) - what a block may
    actually be offered - while `rec["samples"]` is what the preflight listed.

    The first branch is the one CF-0291 added, and which of the two "no
    picture" answers it is comes from the preflight's own word rather than from
    a rule of this file: `weak` is the verdict the Editor gives an anchor whose
    whole ranked pool is under the similarity floor (CF-0290,
    `candidate_supply(pool_offered_off_topic)`), and `absent` the one it gives
    an anchor whose frames exist and cannot be cut. The remedies are opposite -
    rewrite the phrase, or buy footage that survives the usability gates - so
    they are never folded together.
    """
    best = rec.get("best_offered_score")
    under_floor = rec.get("verdict") == VERDICT_WEAK or (
        isinstance(best, (int, float)) and best < floor)
    if not samples and under_floor:
        return WHY_UNDER_FLOOR, (
            f"the pool ranked {rec.get('candidates') or len(rec.get('samples') or [])} "
            f"candidate(s) for this anchor and not one of them is a picture of it - the best "
            f"scores {best}, under the Editor's similarity floor, so `screen_pool()` offers "
            f"the block none of them (CF-0290). This anchor names a scene the pool does not "
            f"hold; rewrite it at one the pool does"
            + gate_threw_out(rec))
    if not samples:
        total, ranked = refusal_summary({"anchors": [rec]}, limit=2)
        detail = "; ".join(f"{n} x {reason}" for reason, n, _ in ranked)
        return WHY_NO_FRAME, (f"the pool has no usable frame for this anchor at all "
                              f"({total} candidate(s) refused: {detail})")
    if side and sides:
        on_side = [s for s in samples if sides.get(s.rsplit(":", 1)[0]) == side]
        if on_side and all(s in taken for s in on_side):
            return WHY_ALL_SPENT, (f"all {len(on_side)} usable frame(s) of side {side!r} are "
                                   f"already on screen elsewhere in this video (CF-0121)"
                                   + gate_threw_out(rec))
        if not on_side:
            return WHY_WRONG_SIDE, (f"none of this anchor's {len(samples)} usable frame(s) is "
                                    f"on side {side!r} - the swing has nothing to cross to")
    return WHY_ALL_SPENT, (f"all {len(samples)} usable frame(s) for this anchor are already "
                           f"on screen elsewhere in this video (one sample, one use, CF-0121)"
                           + gate_threw_out(rec))


def below_floor_pick(rec, floors, blocked, spans, min_cut, side=None, sides=None):
    """CF-0433: `(shot, score)` the resolver would take under the similarity
    floor for this anchor, or None.

    The candidates are the preflight's own `refusals[]` that scored under
    `min_score` (the floor's refusals, by construction - `screen_pool()` runs
    before any other gate) and not under `score_floor` (CF-0088, still an
    outright refusal). Rank order, never length: trading the phrase for a
    longer clip is the delver defect CF-0290 was filed on. One sample, one use
    applies; a shot known to be too short to read is skipped, one whose length
    is unknown is not. On a side the block prefers that side, falling back to
    the whole list, as `resolve_anchors.py` does."""
    floor, hard = floors["min_score"], floors["score_floor"]
    cands = []
    for r in rec.get("refusals") or []:
        if not isinstance(r, dict):
            continue
        s, shot = r.get("score"), r.get("shot")
        if (not shot or not isinstance(s, (int, float)) or isinstance(s, bool)
                or s >= floor or (hard is not None and s < hard)):
            continue
        if "similarity floor" not in str(r.get("reason") or ""):
            # refused by another gate (cached usability, text_cut_by_crop) - a
            # low score does not make it the floor's; the resolver refuses it
            # again under the floor, in fill().
            continue
        if blocked(shot):
            continue
        avail = (spans.get(shot) or {}).get("seconds")
        if avail is not None and avail < min_cut:
            continue
        cands.append((shot, float(s)))
    cands.sort(key=lambda c: -c[1])
    if side and sides:
        on_side = [c for c in cands if sides.get(c[0].rsplit(":", 1)[0]) == side]
        cands = on_side or cands
    return cands[0] if cands else None


def similarity_findings(handed):
    """CF-0433: `score.low_similarity`, one per block the replay filled under
    the floor (-3 a block, cap -15)."""
    return [_score.finding(
        _score.RULE_LOW_SIMILARITY, {"block": h["block"]}, 1, False,
        f"block {h['block']} (anchor {h['anchor']}) takes {h['below_floor']['shot']} at "
        f"{h['below_floor']['score']} under the {h['below_floor']['min_score']} floor")
        for h in handed if h.get("below_floor")]


def graphic_scope(report, draws):
    """CF-0689: the report as this channel may read it - a channel without the
    `own_graphic` origin draws no graphic, so no anchor is one there."""
    if draws or not isinstance(report, dict) or GRAPHIC_INDICES_KEY not in report:
        return report
    return {k: v for k, v in report.items() if k != GRAPHIC_INDICES_KEY}


def hand_out(blocks, report, spans, constants, sides, floors, shot_budget=None):
    """Give a distinct shot to every block the way `resolve_anchors.py` does.

    CF-0291: the pool a block draws on is the anchor's **screened** pool - the
    candidates over the Editor's own similarity floor (`screened_samples()`,
    the floor off the report and the Editor's source, never a copy here). The
    long-enough-first sort runs inside that, exactly as CF-0290 left it, and a
    shot too short for the block still takes it with its frame held
    (`held_frame`), which is a filled block. A block whose driver anchor has no
    candidate over the floor is EMPTY - it is not filled below the floor, and
    that is the whole of this task: before it, such a block took the longest
    thing the matcher had ranked and played a frame of something else under the
    phrase.

    CF-0371: `shot_budget` is the plan's `shot_budget` (`plan_blocks.py`,
    `shot_budget_report()`) - the resolver's CF-0370 cap on an `even` block
    under a drawn block-count top, as the Editor's own
    `rhythm.even_shot_budget()` evaluated for every count of pictures already
    down. The replay reads the row of the block at the pictures it has handed
    out so far and cuts the chain there, the way `resolve_anchors.py` does
    right after `budget = seg["max_shots"] or len(pool)`; the last picture of
    a capped block holds the rest of it (`held_frame`), which is what the
    resolver does instead of chaining on. Without it (an older plan, a pattern
    with no drawn count top) the hand-out is the one it always was.

    Returns one record per block: what it took, at what score, whether its
    frame is held, how much of the pool was left over for a second choice
    (`spare`), and - when it took nothing - why.

    CF-0689: a block whose driver anchor places one of the script's own
    graphics (the report's `graphic_anchor_indices`, its anchors numbered like
    the script's - `check_anchor_coverage.in_script_space`) is the graphic: the
    Video Editor draws it, nothing is taken from the pool, and it is filled -
    never empty, never on its last candidate (`own_graphic: true`). As in the
    resolver, the shot after a graphic is not a cut of the same shot.
    """
    by_anchor = {r.get("anchor_index"): r for r in report.get("anchors") or []}
    graphic = set(report.get(GRAPHIC_INDICES_KEY) or [])
    min_cut = float(floors["min_cut_seconds"])
    slack = float(floors["held_frame_slack_seconds"])
    max_reuse = int(constants.get("max_shot_reuse") or 1)
    emergency_left = int(constants.get("max_emergency_reuse_per_video") or 1)
    used_count, out, prev_keys = Counter(), [], set()
    budget_rows = ((shot_budget or {}).get("by_block")
                   if (shot_budget or {}).get("asked") else None) or []
    so_far = 0

    def blocked(sample):
        return used_count[sample] >= max_reuse

    def take(samples, need, budget_of, cap=None):
        """Cut candidates out of `samples` until the block is covered -
        `resolve_anchors.fill()`, with the same long-enough-first sort and the
        same "too short to read" skip. `cap` is the CF-0370 budget, applied
        where the resolver applies it: only when it is under the block's own.
        Returns `(pool, used, capped, covered)`."""
        pool = [s for s in samples if not blocked(s)]
        budget = budget_of or len(pool) or 1
        capped = cap is not None and cap < budget
        if capped:
            budget = cap
        if budget == 1:
            pool = sorted(pool, key=lambda s: (spans.get(s, {}).get("seconds") or 0.0) < need)
        covered, used = 0.0, []
        for sample in pool:
            if covered >= need or len(used) >= budget:
                break
            avail = spans.get(sample, {}).get("seconds") or 0.0
            span = min(need, avail) if budget == 1 else min(avail, need - covered + 0.5)
            if span < min_cut:
                continue  # "would cut to Ns - too short to read", not a stop
            used.append(sample)
            used_count[sample] += 1
            covered += span
        return pool, used, capped, covered

    for bi, block in enumerate(blocks):
        need = float(block["seconds"])
        ai = driver_anchor(block, report)
        if ai in graphic:
            out.append({"block": block["index"], "seconds": round(need, 3),
                        "anchor": ai, "role": block.get("role"), "side": block.get("side"),
                        "swung": False, "offered": 0, "shots": [], "spare": 0,
                        "emergency": None, "score": None, "score_source": ogl.KIND,
                        "held_frame": False, "under_floor": 0, "shot_cap": None,
                        "below_floor": None, "own_graphic": True,
                        "empty": False, "why": None, "reason": None})
            prev_keys = set()
            continue
        rec = by_anchor.get(ai) or {}
        samples = screened_samples(rec, floors)
        floored = under_floor(rec, floors)
        side, swung = block.get("side"), False
        on_side = samples
        if side and side in ("a", "b") and sides:
            on_side = [s for s in samples if sides.get(s.rsplit(":", 1)[0]) == side]
        row = budget_rows[bi] if bi < len(budget_rows) else None
        cap = int(row[min(so_far, len(row) - 1)]) if row else None
        pool, used, capped, covered = take(on_side, need, block.get("max_shots"), cap)
        if side and side in ("a", "b") and sides and not used:
            # CF-0285: "nothing on side X survived the cut - the block was
            # filled from the other side and carries no side". The resolve
            # keeps the block in the cadence and drops the *side*, refilling
            # from the whole pool (`resolve_anchors.py`, right after `fill`),
            # and so does this. It is recorded because a block that took the
            # other side's picture is an alternation that did not happen: the
            # montage stops crossing the axis long before a block ends empty,
            # and until now the replay called that an empty block instead.
            swung = True
            pool, used, capped, covered = take(samples, need, block.get("max_shots"), cap)
        # CF-0290: with one shot for the whole block - or one shot found for a
        # swing block's budget - a clip shorter than the block is held as a
        # frame rather than passed over for a longer shot of something else.
        one_shot = (block.get("max_shots") == 1
                    or (block.get("role") == "swing" and len(used) == 1))
        held = bool(used) and one_shot and (
            (spans.get(used[0]) or {}).get("seconds") or 0.0) + slack < need
        # CF-0370/CF-0371: the budget, not the pool, stopped the chain - the
        # last picture holds the rest of the block instead of a next shot.
        held = held or (capped and len(used) >= cap and covered + slack < need)
        score, score_source = ((None, "no pick") if not used
                               else sample_score(rec, used[0], samples, spans))
        # CF-0433: nothing at or above the similarity floor filled the block -
        # the resolver now takes the best candidate it held back under the
        # floor (`resolve_anchors.below_floor_pool()`: by rank, never by
        # length, never under `--score-floor`) and the plan prices it
        # `score.low_similarity`. Replayed the same way, off the preflight's
        # own `refusals[]`, before the emergency repeat - as the resolver does.
        below = None
        if not used:
            pick = below_floor_pick(rec, floors, blocked, spans, min_cut,
                                    side if not swung else None, sides)
            if pick is not None:
                shot, below_score = pick
                used = [shot]
                used_count[shot] += 1
                score, score_source = below_score, "refusals[] (under the similarity floor)"
                avail = (spans.get(shot) or {}).get("seconds")
                held = avail is not None and avail + slack < need
                below = {"shot": shot, "score": below_score,
                         "min_score": floors["min_score"]}
        record = {"block": block["index"], "seconds": round(need, 3),
                  "anchor": ai, "role": block.get("role"), "side": side,
                  "swung": bool(swung and used), "offered": len(pool), "shots": used,
                  "spare": max(0, len(pool) - len(used)), "emergency": None,
                  "score": score, "score_source": score_source, "held_frame": held,
                  "under_floor": floored, "shot_cap": cap if capped else None,
                  "below_floor": below,
                  "empty": False, "why": None, "reason": None}
        if not used:
            reuse = next((s for s in samples if s not in prev_keys), None)
            if block.get("role") == "swing":
                # CF-0074/CF-0137: refused outright inside a swing.
                record["empty"] = True
            elif emergency_left > 0 and reuse:
                emergency_left -= 1
                record["emergency"] = reuse
                record["shots"] = [reuse]
                # CF-0137's repeat is a picture like any other, so it carries
                # the same two facts: what it scored and whether the block sits
                # on a held frame of it.
                record["score"], record["score_source"] = sample_score(
                    rec, reuse, samples, spans)
                record["held_frame"] = (
                    ((spans.get(reuse) or {}).get("seconds") or 0.0) + slack < need)
            else:
                record["empty"] = True
            if record["empty"]:
                record["why"], record["reason"] = why_empty(
                    rec, side if not swung else None, sides,
                    {s for s in samples if blocked(s)}, samples,
                    floors["min_score"])
        prev_keys = set(record["shots"])
        so_far += len(record["shots"])
        out.append(record)
    return out


# --------------------------------------------------------------------------
# what the pool can carry instead
# --------------------------------------------------------------------------

def hold_seconds(script):
    """The hold ceiling the planner actually cut at: the one the rotation drew
    into this script's `pattern.parameters`, or the pattern band's top that
    `check_anchor_cadence.py` already wrote onto the script when nothing was
    drawn."""
    drawn = ((script.get("pattern") or {}).get("parameters") or {}).get("key_frame_hold_seconds")
    if isinstance(drawn, (int, float)) and not isinstance(drawn, bool) and drawn > 0:
        return float(drawn), "pattern.parameters.key_frame_hold_seconds (drawn)"
    ceiling = (script.get("anchor_cadence") or {}).get("hold_ceiling_seconds")
    if isinstance(ceiling, (int, float)) and not isinstance(ceiling, bool) and ceiling > 0:
        return float(ceiling), (script.get("anchor_cadence") or {}).get(
            "hold_ceiling_source", "anchor_cadence.hold_ceiling_seconds")
    return None, None


def probe_positions(total, hold):
    """Anchor times one hold apart, for the question "and if it were written
    at the pattern's own pace?".

    Not an answer, a **payload**: these positions go to the Editor's planner
    beside the real ones and it says how many blocks they cost. Nothing here
    divides a stretch by a hold - that arithmetic is `_plan_staccato()`'s and
    stays there, which is the whole reason the planner is called at all.
    """
    if not hold or hold <= 0 or not total or total <= 0:
        return []
    out, at = [], 0.0
    while at < total - 1e-9:
        out.append(round(at, 3))
        at += hold
    return out


def carrying(plan, filled, fragile, anchors, probe=None):
    """What the pool CAN carry, in the writer's own units.

    `blocks_per_anchor` is this rhythm's own price, taken from the plan it just
    produced rather than from a rule restated here: `list`/`staccato` at a
    1.92 s hold cost 2.0 blocks an anchor on Famine Trials, `explainer`/
    `alternate` 0.91, `moment-breakdown`/`hold` 0.80.

    `cheapest_blocks` only means anything when the rhythm makes more blocks
    than the script has anchors, and it is the Editor's answer too: the same
    planner, asked what anchors spaced one hold apart would cost. That is the
    floor no writing can go under, and it is reached by spacing the anchors at
    the ceiling rather than by using fewer of them - 21 anchors 2.443 s apart
    cost 42 blocks, 27 anchors 1.9 s apart cost 27.
    """
    blocks = len(plan)
    per_anchor = (blocks / anchors) if anchors else 1.0
    excess = max(0, fragile - POOL_MARGIN_FRAGILE_BLOCKS)
    safe = max(0, filled - excess)
    carried = int(safe / per_anchor) if per_anchor > 0 else 0
    out = {"blocks": blocks, "blocks_filled": filled, "fragile": fragile,
           "blocks_per_anchor": round(per_anchor, 3),
           "safe_blocks": safe, "anchors_carried": min(carried, anchors)}
    if probe and blocks > anchors:
        out["cheapest_blocks"] = probe["blocks"]
        out["cheapest_anchors"] = probe["anchors"]
    return out


def pool_shows(report, spans, floors, limit=EVIDENCE_SHOWN):
    """The best frames this topic's pool actually holds, for the rewrite.

    Every distinct sample over the Editor's floor that the preflight put in
    front of some anchor of this script, with its description, its length and
    its score where the report states one. It is the list an anchor has to be
    rewritten **at**: the defect this answers is an anchor written from
    imagination - "a man in a red jacket at a podium" against a pool that holds
    no podium at all - and a refusal that does not print what the pool has
    sends the writer back to the same blank page (CF-0140's blind cycle).

    Best first per anchor and anchors in order, deduplicated, so the head of
    the list is what the pool is strongest at.
    """
    out, seen = [], set()
    for rec in report.get("anchors") or []:
        screened = screened_samples(rec, floors)
        for sample in screened:
            if sample in seen:
                continue
            seen.add(sample)
            shot = spans.get(sample) or {}
            score, score_source = sample_score(rec, sample, screened, spans)
            out.append({"sample": sample,
                        "seconds": shot.get("seconds"),
                        "score": score,
                        "score_source": score_source,
                        "is_card": bool(shot.get("is_card")),
                        "description": shot.get("description") or "",
                        "for_anchor": rec.get("anchor_index")})
            if len(out) >= limit:
                return out
    return out


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------

def previous_failures(script):
    """Block-capacity failures already recorded on this script. A record with
    no count is one failure, not zero: it only exists because a run wrote it."""
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0 if record.get("action") == ACTION_PASS else 1


def judge(script, report, plan, spans, constants, speech_seconds, rate_source, floors,
          probe=None):
    """One script's record - the ladder of the module docstring."""
    blocks = plan.get("blocks")
    if not isinstance(blocks, list) or not blocks:
        raise CannotJudge(
            f"{script.get('script_id')}: the Editor's planner returned no blocks"
            + (f" ({plan.get('error')})" if plan.get("error") else "")
            + " - without a block plan there is no capacity to judge")
    # CF-0285: the footage partition is the *fallback*. When the script
    # declared its sides the Editor filters no candidate by source at all - the
    # anchor's phrase is the side - so filtering here would refuse pictures the
    # resolve will happily cut. Which rule this plan was built under is the
    # Editor's own answer, carried back by `plan_blocks.py`.
    sides = None if plan.get("declared_sides_usable") else footage_sides(report)
    handed = hand_out(blocks, report, spans, constants, sides, floors,
                      plan.get("shot_budget"))
    empty = [h for h in handed if h["empty"]]
    # CF-0433: a block filled under the similarity floor is priced, not fragile.
    # CF-0689: a block of our own graphic stands on no candidate at all.
    fragile = [h for h in handed if not h["empty"] and not h.get("below_floor")
               and not h.get("own_graphic") and (h["spare"] <= 0 or h["emergency"])]
    anchors = len(script.get(FIELD) or [])
    hold, hold_source = hold_seconds(script)
    room = carrying(blocks, len(handed) - len(empty), len(fragile), anchors, probe)
    failed_before = previous_failures(script)

    record = {
        "topic_id": script.get("topic_id"),
        "anchors": anchors,
        "rhythm": (script.get("pattern") or {}).get("rhythm_id"),
        "pattern_id": (script.get("pattern") or {}).get("pattern_id"),
        "speech_seconds": round(speech_seconds, 3),
        "speech_seconds_source": rate_source,
        "hold_seconds": hold,
        "hold_seconds_source": hold_source,
        "probe_at_hold": probe,
        "predicted_blocks": len(blocks),
        "blocks_empty": [h["block"] for h in empty],
        "blocks_fragile": [h["block"] for h in fragile],
        "emergency_repeat": next((h["emergency"] for h in handed if h["emergency"]), None),
        "margin_required": POOL_MARGIN_FRAGILE_BLOCKS,
        "sides": sides,
        "sides_from": ("script" if plan.get("declared_sides_usable")
                       else ("footage" if sides else None)),
        "carrying": room,
        "blocks": handed,
        # CF-0291: the numbers the replay ran at, all of them the Editor's.
        "floors": {k: floors[k] for k in ("min_score", "score_floor", "min_cut_seconds",
                                          "held_frame_slack_seconds")},
        "blocks_under_floor": [h["block"] for h in handed if h["why"] == WHY_UNDER_FLOOR],
        # CF-0433: the blocks filled under the similarity floor, and their
        # price on the score model - a finding, never a rewrite.
        "blocks_below_floor": [h["block"] for h in handed if h.get("below_floor")],
        "score": _score.score_block(similarity_findings(handed)),
        "failed_attempts": failed_before,
        "rewrites_allowed": REWRITES_ALLOWED,
    }

    if not empty and len(fragile) <= POOL_MARGIN_FRAGILE_BLOCKS:
        record["evidence"] = []
        record.update(action=ACTION_PASS, reason=(
            f"the pool fills all {len(blocks)} block(s) this {record['rhythm']} rhythm cuts "
            f"from {anchors} anchor(s), {len(fragile)} of them on their last candidate "
            f"(margin {POOL_MARGIN_FRAGILE_BLOCKS})"))
        return record

    # Everything below sends the script back or drops the topic, and both are
    # read by a writer who has to aim the next version at something.
    record["evidence"] = pool_shows(report, spans, floors)
    under_floor = [h for h in empty if h["why"] == WHY_UNDER_FLOOR]
    trouble = (f"{len(empty)} of {len(blocks)} predicted block(s) end with no picture"
               if empty else
               f"{len(fragile)} of {len(blocks)} predicted block(s) stand on their last "
               f"candidate, over the margin of {POOL_MARGIN_FRAGILE_BLOCKS}")
    carried = room["anchors_carried"]
    # CF-0330: the measurement alone - what a warning says, with no rewrite.
    record["finding"] = (f"{trouble}; the pool carries {max(carried, 0)} anchor(s) at this "
                         f"rhythm ({len(blocks)} block(s) for {anchors} anchor(s), "
                         f"{room['blocks_per_anchor']} block(s) an anchor)")
    if carried <= 0:
        record.update(action=ACTION_REFUSE, failed_attempts=failed_before + 1, reason=(
            f"{trouble}, and the pool carries no anchor at all at this rhythm "
            f"({len(blocks)} block(s) for {anchors} anchor(s), "
            f"{room['blocks_per_anchor']} block(s) an anchor) - there is nothing to "
            f"rewrite towards"))
        return record
    if failed_before >= REWRITES_ALLOWED:
        record.update(action=ACTION_REFUSE, failed_attempts=failed_before + 1, reason=(
            f"{trouble} after {failed_before} rewrite(s) - the pool carries {carried} "
            f"anchor(s) at this rhythm and the script still asks for {anchors}; this topic "
            f"has too little footage for the video it was written for"))
        return record

    if under_floor:
        anchors_named = sorted({h["anchor"] for h in under_floor})
        record.update(action=ACTION_REWRITE, failed_attempts=failed_before + 1, reason=(
            f"{trouble}, and {len(under_floor)} of them because anchor(s) {anchors_named} name "
            f"a scene this pool does not hold: every candidate the matcher ranked for them is "
            f"under the {floors['min_score']} similarity floor, so the Editor offers those "
            f"blocks nothing at all (CF-0290 - a frame that far from the phrase is not a "
            f"picture of it, and the block is refused rather than filled). Rewrite those "
            f"anchors at frames this pool has - the list below is what it showed for this "
            f"script's own phrases, with each shot's length beside it; a shot shorter than a "
            f"block is not a problem, the Editor holds its frame"))
        return record

    advice = (f"the pool fills {room['blocks_filled']} of {len(blocks)} block(s) and "
              f"{len(fragile)} stand(s) on the last candidate, so write a script this rhythm "
              f"cuts into at most {room['safe_blocks']} block(s) - at this spacing "
              f"{room['blocks_per_anchor']} block(s) an anchor, which is {carried} anchor(s)")
    if "cheapest_blocks" in room:
        fits = ("under that ceiling" if room["cheapest_blocks"] <= room["safe_blocks"]
                else "still over that ceiling, so this topic needs more footage either way")
        advice += (f". The lever is the spacing, not only the count: at the {hold} s hold this "
                   f"pattern drew, any stretch longer than {hold} s is cut in two, which is "
                   f"why {anchors} anchor(s) over {round(speech_seconds, 1)} s cost "
                   f"{len(blocks)} block(s). Anchors spaced at or under {hold} s cost one "
                   f"block each - {room['cheapest_anchors']} anchor(s) would be "
                   f"{room['cheapest_blocks']} block(s), the fewest this pattern can be cut "
                   f"into and {fits}")
    record.update(action=ACTION_REWRITE, failed_attempts=failed_before + 1,
                  reason=f"{trouble}; {advice}")
    return record


def previous_picture_failures(script):
    """CF-0365: attempts already spent on the picture band by this script."""
    record = script.get(RECORD_KEY)
    band = record.get(PICTURE_KEY) if isinstance(record, dict) else None
    n = band.get("failed_attempts") if isinstance(band, dict) else None
    return n if isinstance(n, int) and not isinstance(n, bool) and n >= 0 else 0


def picture_verdict(script, record, band, channel):
    """CF-0365: the pattern's block band, held to the pictures this replay handed out.

    `example-film/2026-09-23T1722Z`, `lf-2026-09-23-004` (You Can See
    Everything, `moment-breakdown`/`even`, 10 anchors): the cadence gate read
    the band over the rhythm's **segments** - 11, inside the drawn 6-12 - and
    the voice was paid for. The Editor refused the plan before the render at
    **22** blocks (`pattern_ceiling` / `pattern_undeliverable`), because under
    `even` a segment takes as many shots as the pool needs to cover it and each
    shot is a block. It was not an estimate against a wav: the estimate put 174
    words in 39.13 s and the wav said 174 words in 38.65 s, 11 segments against
    the Editor's 10. It was a unit. This replay had handed out **21** pictures
    for those 11 segments before the TTS, and nobody held them to the band.

    `band` is `plan_blocks.picture_band_report()`'s answer: the Editor's
    `cadence()` over the pictures and its own `cadence_band_refuses()` on the
    shortfall. This adds the replay's own error (`PICTURE_OVERCOUNT_RATIO`) and
    the ladder:

      * inside the band, or not asked - pass;
      * over the top, and the Editor's predicate refuses, but not by more than
        the replay's worst overcount - a note: printed and recorded, nothing
        refused on a number this replay cannot carry;
      * over it by more than that - a price since CF-0449 (the user's
        decision of 2026-10-02, the score model): `score.block_band_exceeded`
        (CF-0447's signed price, 2 a block over the top, cap 10) on this
        record's score, action `priced`, exit 0. Before it was a rejection of
        the assignment (exit 5) and, the second time, the topic lost as
        `pool_too_thin` - neither happens any more: the score decides at 6b.
    """
    if not isinstance(band, dict) or not band.get("asked"):
        return {"asked": False, "action": ACTION_PASS,
                "why": ((band or {}).get("why") if isinstance(band, dict) else None)
                or "the Editor's planner answered no `picture_band` - this checkout of "
                   "plan_blocks.py is older than CF-0365, and the band was not read"}
    out = {k: band.get(k) for k in (
        "pattern_id", "parameter", "code", "mode", "unit", "measured", "band_min",
        "band_max", "segments", "picture_blocks", "block_span_seconds", "inside",
        "outside_by", "refuses", "refusal_rule", "over_top", "measured_over", "shortfall")}
    out["asked"] = True
    hi = band.get("band_max")
    ceiling = (round(float(hi) * PICTURE_OVERCOUNT_RATIO, 2) if hi is not None else None)
    out.update({"overcount_ratio": round(PICTURE_OVERCOUNT_RATIO, 4),
                "overcount_source": PICTURE_OVERCOUNT_SOURCE,
                "refusal_ceiling": ceiling})
    failed_before = previous_picture_failures(script)
    out["failed_attempts"] = failed_before
    out["attempts_allowed"] = PICTURE_ATTEMPTS_ALLOWED
    over = bool(band.get("over_top"))
    measured = band.get("measured")
    beyond_error = bool(band.get("refuses") and over and ceiling is not None
                        and measured is not None and float(measured) > ceiling)
    # CF-0449: `refused_here` stays in the record, always false (a reader of
    # an older record and of this one ask the same key); `over_error` is the
    # reading that used to refuse and is priced now.
    out["refused_here"] = False
    out["over_error"] = beyond_error
    out["priced_here"] = False
    pid, rhythm_id = record.get("pattern_id"), record.get("rhythm")
    unit = f" {band.get('unit')}" if band.get("unit") else ""
    speech = record.get("speech_seconds") or 0.0
    pics = band.get("picture_blocks") or 0
    per_shot = round(speech / pics, 2) if pics else None
    head = (f"the replay hands out {pics} picture(s) for {band.get('segments')} segment(s) "
            f"({pid}/{rhythm_id}, {speech} s of speech, {per_shot} s a picture on this pool) "
            f"- {measured}{unit} against {pid}'s {band.get('mode')} band "
            f"{band.get('band_min')}-{hi}{unit}")
    if band.get("inside") or not over:
        out.update(action=ACTION_PASS, reason=f"{head}: inside" if band.get("inside")
                   else f"{head}: not over the top (a floor is not read on a replay)")
        return out
    if not beyond_error:
        out.update(action=PICTURE_NOTE, reason=(
            f"{head}: over the top, but "
            + (f"not by more than the replay's worst overcount ({ceiling}{unit}, "
               f"{PICTURE_OVERCOUNT_SOURCE})" if band.get("refuses")
               else "the Editor's `cadence_band_refuses()` does not refuse this band there")
            + f" - nothing is refused here; the Editor counts the real pictures after the "
              f"TTS and refuses over {hi}{unit} as `pattern_undeliverable`"))
        return out
    holds = round(float(hi) * per_shot, 1) if per_shot else None
    # CF-0449 (the user's decision of 2026-10-02, the score model, as CF-0447
    # for the cadence gate's reading of the same band): over the top by more
    # than the replay's error is a PRICE, never a rejection of the assignment
    # and never a topic lost as `pool_too_thin`. The price is CF-0447's signed
    # one - `score.block_band_exceeded`, 2 a block over the top, cap 10 - put
    # on this record's score (`block_capacity.score`) as the forecast it is;
    # the Editor charges the real count after the voice. `failed_attempts`
    # does not move: there is no attempt to spend any more.
    over_by = picture_blocks_over(band)
    out.update(action=PICTURE_PRICED, priced_here=True, blocks_over=over_by,
               price_rule=_score.RULE_BLOCK_BAND_EXCEEDED, reason=(
        f"{head}: over the top by more than the replay's worst overcount ({ceiling}{unit}) - "
        f"not refused (CF-0449): `{_score.RULE_BLOCK_BAND_EXCEEDED}` for {over_by} block(s) "
        f"over the top, the Editor charges the real count after the voice. Fewer anchors "
        f"do not move it: under `{rhythm_id}` a segment is cut into as many shots as its "
        f"length needs, so the count follows the speech - at {per_shot} s a picture, {hi} "
        f"pictures hold {holds} s of speech and this script speaks {speech} s; if the "
        f"score is under N at step 6b, the assignment is what does not fit (`rotate.py "
        f"reject`)"))
    return out


def picture_blocks_over(band):
    """CF-0449: the pictures over the band's top, in blocks - the units of
    `score.block_band_exceeded`, counted as the cadence gate counts them
    (`check_anchor_cadence.blocks_over()`, CF-0447): a count band, the
    pictures less the top; a rate band, the pictures less as many as the top
    allows over this span. At least 1 - the reading is over."""
    blocks = band.get("picture_blocks") or band.get("blocks")
    return _blocks_over(dict(band, blocks=blocks))


def picture_finding(band):
    """CF-0449: the picture band's price, in the score model's shape."""
    unit = f" {band.get('unit')}" if band.get("unit") else ""
    note = (f"{band.get('picture_blocks')} picture(s) replayed = {band.get('measured')}{unit} "
            f"against {band.get('pattern_id')}'s {band.get('mode')} band "
            f"{band.get('band_min')}-{band.get('band_max')}{unit}, {band.get('blocks_over')} "
            f"block(s) over the top (replay estimate, CF-0365)")
    return _score.finding(_score.RULE_BLOCK_BAND_EXCEEDED,
                          {"pattern": band.get("pattern_id"), "count": "pictures"},
                          band.get("blocks_over") or 1, False, note)


def picture_lines(band):
    """The lines for the picture band of one script (CF-0365)."""
    if not band.get("asked"):
        return []
    mark = {ACTION_PASS: "    band: ", PICTURE_NOTE: "    band: CLOSE ",
            PICTURE_PRICED: "    band: PRICED ",
            ACTION_REJECT: "    band: REJECT ", ACTION_REFUSE: "    band: REFUSE "}
    lines = [f"{mark.get(band['action'], '    band: ')}{band['reason']}"]
    if band.get("reject_command"):
        lines.append(f"      {band['reject_command']}")
    return lines


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
        "blocks_empty": record["blocks_empty"],
        "carrying": record["carrying"],
        "failed_attempts": record["failed_attempts"],
    }


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

EMPTY_SHOWN = 8


def script_lines(script, record):
    """The lines for one judged script."""
    sid = script.get("script_id")
    head = {ACTION_PASS: "  ok    ", ACTION_REWRITE: "  REWRITE",
            ACTION_REFUSE: "  REFUSE", gw.ACTION_WARN: "  WARN   ",
            ACTION_REJECT: "  REJECT "}[record["action"]]
    room = record["carrying"]
    lines = [f"{head} {sid}: {record['anchors']} anchor(s) -> "
             f"{record['predicted_blocks']} block(s) "
             f"({record['pattern_id']}/{record['rhythm']}, "
             f"{room['blocks_per_anchor']} block(s) an anchor"
             + (f", hold {record['hold_seconds']} s" if record["hold_seconds"] else "")
             + f"); {room['blocks_filled']} filled, {len(record['blocks_empty'])} empty, "
               f"{len(record['blocks_fragile'])} on their last candidate "
               f"(margin {record['margin_required']})"]
    picture = record.get(PICTURE_KEY) or {}
    by_picture = picture.get("action") in (ACTION_REJECT, ACTION_REFUSE)
    for w in record.get("warnings") or []:
        lines.append(gw.line(w))
    if record["action"] not in (ACTION_PASS, gw.ACTION_WARN) and not by_picture:
        lines.append(f"    {record['reason']}")
    lines.extend(picture_lines(picture))
    if record["emergency_repeat"]:
        lines.append(f"    the one emergency repeat (CF-0137) is spent on "
                     f"{record['emergency_repeat']}")
    held = [h for h in record["blocks"] if h.get("held_frame") and not h["empty"]]
    if held:
        lines.append(f"    {len(held)} block(s) are filled by holding the frame of a shot "
                     f"shorter than the block (CF-0290): "
                     + ", ".join(f"{h['shots'][0]} on block {h['block']}" for h in held[:4])
                     + (" ..." if len(held) > 4 else ""))
    shown = [h for h in record["blocks"] if h["empty"]][:EMPTY_SHOWN]
    for h in shown:
        lines.append(f"      block {h['block']} ({h['seconds']} s, {h['role']}"
                     + (f", side {h['side']!r}" if h["side"] else "")
                     + f", anchor #{h['anchor']}): {h['reason']}")
    hidden = len(record["blocks_empty"]) - len(shown)
    if hidden > 0:
        lines.append(f"      ... and {hidden} more empty block(s)")
    if record.get("evidence"):
        lines.append(f"    what this pool does show (the Editor's preflight passed these for "
                     f"this script's own phrases, over its "
                     f"{record['floors']['min_score']} floor):")
        for e in record["evidence"]:
            score = (f"score {e['score']}" if e["score"] is not None
                     else f"score >= {record['floors']['min_score']}")
            lines.append(f"      {e['sample']} ({e['seconds']} s, {score}"
                         + (", card" if e["is_card"] else "") + "): "
                         + (e["description"] or "(no description in the index - read the "
                                                "contact sheet)"))
    return lines


# --------------------------------------------------------------------------
# the batch
# --------------------------------------------------------------------------

def check_batch(batch_file, reports_file, root=None, footage_index=None, script_id=None,
                out=print, write=False, editor_python=None, planner=None,
                editor_scripts=None, timeout=DEFAULT_TIMEOUT, resolver=None):
    """Judge every script of the batch. Returns `(problems, records, refused)`.

    One child process for the whole batch (the Editor's planner), then no
    further cost: the candidate lists come out of the coverage reports that
    `check_anchor_coverage.py --out` already wrote.
    """
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotJudge(f"cannot read {batch_file}: {exc}")
    channel = resolve_channel(data.get("channel"), root)
    sections = counted_sections(channel, root) if channel else FALLBACK_SECTIONS
    reports = load_reports(reports_file)

    scripts = [s for s in data.get("scripts", [])
               if script_id is None or s.get("script_id") == script_id]
    # CF-0689: the channel's switch for its own graphics; an all-graphic
    # batch needs no footage index, an all-graphic script no pool.
    draws = ogl.channel_draws(channel, root)
    index_path, index_data = load_footage_index_for(batch_file, footage_index, scripts, draws)
    # CF-0430: the rewrite this gate asked for, not made - judged no again.
    held = []
    scripts, _unchanged, same = rg.split(scripts, RECORD_KEY, sections, held.append, write)

    entries, context = [], {}
    for script in scripts:
        sid = script.get("script_id")
        starts, total, word_starts, sides, _rate, rate_source = anchor_times(
            script, sections, channel, root)
        entries.append({"script_id": sid, "anchor_starts": starts, "total": total,
                        "word_starts": word_starts, "order": script.get("pattern"),
                        "anchor_sides": sides})
        context[sid] = (total, rate_source)
        # The same planner, asked the writer's other question in the same
        # breath: what would this pattern cost if the anchors were spaced at
        # its own hold? It rides along in the one payload, so it is free.
        probe = probe_positions(total, hold_seconds(script)[0])
        if probe:
            entries.append({"script_id": f"{sid}{PROBE_SUFFIX}", "anchor_starts": probe,
                            "total": total, "word_starts": word_starts,
                            "order": script.get("pattern"), "anchor_sides": None})

    paths = planner_paths(root, editor_python, planner, editor_scripts)
    plans, constants = run_planner(entries, paths, timeout) if entries else ({}, {})

    out(f"{batch_file}: {len(scripts)} script(s); block plan from the Video Editor's own "
        f"`rhythm.plan_segments()` via {paths['planner'].name} on its venv (CF-0284), anchors "
        f"placed at word_index / this script's words-per-second (CF-0279); candidate lists "
        f"from {Path(reports_file).name} (the Editor's preflight, no second CLIP load, "
        f"CF-0280), screened by the Editor's own similarity floor before any length is "
        f"compared (CF-0290/CF-0291); one sample one use (CF-0121), one emergency repeat a "
        f"video (CF-0137); "
        f"margin {POOL_MARGIN_FRAGILE_BLOCKS} block(s) on their last candidate; a shortfall "
        f"is a `{SKIP_REASON_CODE}` warning and the script goes on (CF-0330)")
    for line in held:
        out(line)

    problems, records, refused, warnings = list(same), {}, [], []
    for script in scripts:
        sid = script.get("script_id")
        report = graphic_scope(report_for(script, reports), draws)
        plan = plans.get(sid)
        if not isinstance(plan, dict):
            raise CannotJudge(f"{sid}: the Editor's planner returned no plan for this script")
        pool = topic_pool_for(index_path, index_data, script, draws)
        spans = shot_spans(pool["indexes"])
        total, rate_source = context[sid]
        at_hold = plans.get(f"{sid}{PROBE_SUFFIX}") or {}
        probe = ({"anchors": len(probe_positions(total, hold_seconds(script)[0])),
                  "blocks": len(at_hold["blocks"]),
                  "hold_seconds": hold_seconds(script)[0]}
                 if isinstance(at_hold.get("blocks"), list) else None)
        floors = editor_floors(report, root, resolver)
        records[sid] = judge(script, report, plan, spans, constants,
                             total, rate_source, floors, probe)

    # CF-0365: the pattern's block band over the pictures just handed out -
    # one more payload for the whole batch, the same layout with the shot
    # count of every block beside it, answered by the Editor's own band rule.
    picture_entries = [dict(e, picture_shots=[max(1, len(h["shots"]))
                                              for h in records[e["script_id"]]["blocks"]])
                       for e in entries if e["script_id"] in records]
    picture_plans = (run_planner(picture_entries, paths, timeout)[0]
                     if picture_entries else {})

    for script in scripts:
        sid = script.get("script_id")
        record = records[sid]
        record["warnings"] = []
        if record["action"] in (ACTION_REWRITE, ACTION_REFUSE) and gw.warns(gw.GATE_BLOCK_CAPACITY):
            # CF-0330: the Editor's `assetless_rung` warns, so its prediction
            # here does too - same code, same numbers, the script goes on.
            record["would_have"] = record["action"]
            record["action"] = gw.ACTION_WARN
            record["failed_attempts"] = previous_failures(script)
            record["warnings"] = [gw.entry(
                script.get("topic_id"), sid, gw.GATE_BLOCK_CAPACITY, SKIP_REASON_CODE,
                f"{record['finding']}. Before CF-0330 this was a {record['would_have']}; now a "
                f"warning - the script goes on as written, and the blocks the pool cannot fill "
                f"are the Editor's `assetless_rung` warning",
                numbers=warning_numbers(record))]
            # CF-0342: what the pool is short of, by entity - the request
            # skeleton `--write` puts under work/supplement-requests/.
            record["warnings"][0][sreq.FIELD] = sreq.from_blocks(script, record)
            warnings.extend(record["warnings"])
        picture = record[PICTURE_KEY] = picture_verdict(
            script, record, (picture_plans.get(sid) or {}).get(PICTURE_KEY), channel)
        if picture["action"] == PICTURE_PRICED:
            # CF-0449: a price on this record's score, not a rejection of the
            # assignment and not a topic lost - charged once here (the
            # cadence gate's own record prices the segment count apart, and
            # the Editor charges the real pictures after the voice).
            findings = list((record.get("score") or {}).get("findings") or [])
            if not any(f.get("rule") == _score.RULE_BLOCK_BAND_EXCEEDED for f in findings):
                findings.append(picture_finding(picture))
            record["score"] = _score.score_block(findings)
        for line in script_lines(script, record):
            out(line)
        if record["action"] == ACTION_REWRITE:
            problems.append(f"{sid}: {record['reason']}")
        elif record["action"] == ACTION_REFUSE:
            refused.append(script)

    if write:
        for script in scripts:
            record = records.get(script.get("script_id"))
            if record:
                script[RECORD_KEY] = rg.stamp(record, script, sections)
        gw.clear(data, [s.get("topic_id") for s in scripts if s.get("script_id") in records],
                 gw.GATE_BLOCK_CAPACITY)
        gw.record(data, warnings)
        for line in sreq.lines(*sreq.sync(
                path.parent, data,
                [s.get("topic_id") for s in scripts if s.get("script_id") in records])):
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
               if refused else ""))
    else:
        if warnings:
            out(gw.NOT_RECORDED.format(n=len(warnings)))
        if refused:
            out(f"  note: {len(refused)} topic(s) are refused as `{SKIP_REASON_CODE}` but "
                f"nothing was recorded - re-run with --write so the funnel sees the loss")
    return problems, records, refused


def warning_numbers(record):
    """CF-0330: the numbers a block-capacity warning carries."""
    return {k: record.get(k) for k in (
        "anchors", "rhythm", "pattern_id", "speech_seconds", "hold_seconds",
        "predicted_blocks", "blocks_empty", "blocks_fragile", "blocks_under_floor",
        "margin_required", "carrying", "floors", "failed_attempts", "would_have")}


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
                    help="record the prediction on every script - which is both where the one "
                         "allowed rewrite is counted between runs and what the Editor's real "
                         "block plan can later be compared against - and write a shortfall "
                         "into warnings[] as `pool_too_thin` (CF-0330)")
    args = ap.parse_args(argv)
    try:
        problems, records, refused = check_batch(
            args.batch_file, args.reports,
            root=Path(args.root).resolve() if args.root else None,
            footage_index=args.footage_index, script_id=args.script_id, write=args.write,
            editor_python=args.editor_python, planner=args.planner,
            editor_scripts=args.editor_scripts, timeout=args.timeout,
            resolver=args.resolver)
    except CannotAnswer as exc:
        print(f"check_block_capacity.py: {exc}", file=sys.stderr)
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
        print(f"\n{len(problems)} script(s) to rewrite shorter:")
        for p in problems:
            print(f"  - {p}")
    if refused:
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}` - the pool cannot "
              f"fill the blocks this rhythm cuts, and there is nothing to rewrite"
              + ("" if args.write else "; nothing was recorded (--write)"))
        for script in refused:
            print(f"  - {script.get('script_id')}: "
                  f"{records[script.get('script_id')]['reason']}")
    # CF-0449: the picture band no longer rejects (exit 5 is gone from this
    # gate) - a reading over it is priced and printed as `band: PRICED`.
    priced = [sid for sid, r in records.items()
              if (r.get(PICTURE_KEY) or {}).get("action") == PICTURE_PRICED]
    if priced:
        print(f"\n{len(priced)} script(s) over the pattern's block band in pictures - priced "
              f"`{_score.RULE_BLOCK_BAND_EXCEEDED}`, not refused (CF-0449); the score decides "
              f"at step 6b:")
        for sid in priced:
            sc = records[sid].get("score") or {}
            print(f"  - {sid}: {records[sid][PICTURE_KEY]['blocks_over']} block(s) over, "
                  f"{_score.summary(sc) if sc.get('score') is not None else 'score not computed'}")
    if problems:
        return EXIT_REWRITE
    return EXIT_REFUSED if refused else EXIT_OK


@runlog.script("content-researcher", "check-block-capacity", name="check_block_capacity.py")
def cli():
    """The command-line entry (CF-0107). One `child` event: the Editor's block
    planner, once for the whole batch. No model, no CLIP, no ffmpeg - the
    expensive answer was bought by `check_anchor_coverage.py` and is read out
    of its `--out` file."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
