#!/usr/bin/env python3
"""CF-0041: the four montage rhythms, as a block plan and as a measurement.

Everything here is pure arithmetic over anchor times and word times - no
ffmpeg, no CLIP, no filesystem. That is deliberate: the rhythm is the one part
of the montage that can be reasoned about before a single frame is cut, so it
is testable without a render, and `resolve_anchors.py` is left owning only
footage resolution.

--------------------------------------------------------------------------
Why the block plan is built here and not upstream
--------------------------------------------------------------------------

Content Researcher draws a (pattern, rhythm) pair and its parameters and writes
them into `03-content-researcher.json` as an *order* (CF-0015/CF-0039: `drawn`
parameters are orders, `emergent` ones are observations). It does not send a
block plan and must not: block boundaries depend on which anchors resolved
against the footage index, and they are re-cut again by per-block degradation
(CF-0031). A plan written before either of those is known would be a plan
about a video that does not exist.

--------------------------------------------------------------------------
The four rhythms
--------------------------------------------------------------------------

`even` is the emergent one - it is the *absence* of a device. One anchor, one
block, boundaries wherever the narration put them, as many fill shots per
anchor as it takes to cover the stretch. This is the pipeline's behaviour from
before patterns existed and it must stay bit-identical: `explainer` on `even`
is the baseline pattern (patterns/explainer.json) and the whole vocabulary is
anchored to it not changing. Running with no order at all is exactly `even`.

`hold`, `staccato` and `alternate` are ordered: the cadence is the instruction,
not the outcome. That difference decides one design question that comes up in
all three - what to do when the chosen shot is shorter than the block it has to
fill:

  * `even` reshapes the plan. A shortfall is carried into the next anchor
    (CF-0028) so the next real clip arrives early, because on `even` the
    boundary was never load-bearing.
  * an ordered rhythm holds a frame instead. Reshaping would destroy the
    ordered cadence, which is the only thing the rhythm was asked for, so the
    block is delivered as a still lifted out of its own clip - `held_frame` on
    the block, so nothing downstream mistakes a deliberate hold for a
    degradation. On `hold` that is not even a fallback, it *is* the rhythm:
    "one frame ... left on screen while the voice works over it".
  * an ordered segment with *no* clip at all (every candidate capped, failed
    or absent) is still its own block, at the planner's own bounds, on the
    assetless rung - `asset_kind: "typographic"` from resolve_anchors.py,
    `procedural` in the plan, recorded under `degraded_blocks` (CF-0085).
    Stretching the previous block over it, which is what `even` still does,
    once merged 25 unresolved staccato segments into one 31.6s block: the
    cadence must survive a footage shortage, even if the picture does not.

--------------------------------------------------------------------------
alternate, and how it differs from the defect CF-0034 recorded
--------------------------------------------------------------------------

`alternate` builds A-B-A-B on purpose. CF-0034 analysed a real video where the
same structure appeared by accident and read to a viewer as "too many repeated
shots". The important thing about that analysis is *what* it actually found,
because it is what the difference has to be measured against: shots 43 and 36
of ZZ_urA56pJE alternated across four consecutive blocks (3.53s-10.88s) with a
zero-second gap between reuses - the same **pair** of shots, back to back,
twice. Neither shot was anywhere near the reuse cap of 3 in force then
(CF-0026); the cap could not see this and lowering it would not have caught it.
CF-0121 has since lowered it all the way to 1, which does catch that particular
sequence - but only by accident, and only where the pool has a spare shot to
fall through to. The pair rule is still the thing that names the defect: an
A-B-A-B built out of four *distinct* shots (A1,B1,A2,B2 reordered to A1,B1,A1',
B1') is inside any per-shot cap and still reads as stuck.

So the discriminator is not "how often is a shot used" but "does the same
adjacent pair recur":

  * a *stuck* repeat is X,Y,X,Y - `repeated_adjacent_pairs()` counts more than
    zero.
  * *intentional* alternation is X,Y,Z,W,... - the sides alternate every block
    while the adjacent pair never repeats, and each side draws on at least
    `ALTERNATE_MIN_DISTINCT_PER_SIDE` distinct shots.

`resolve_anchors.py` enforces that at selection time (a candidate that would
recreate an already-used adjacent pair is skipped, exactly as an over-reused
one is), and `verify_rhythm()` re-measures it on the delivered plan afterwards.
Enforced and then measured, rather than only intended.

CF-0050 changed where the two sides come from, and left that discriminator
exactly as it was. A side used to be a footage *source*; it is now the side the
script declared for each anchor, with the source partition kept as the fallback
for a script that declared none. That moves the boundary of a swing from "the
files differ here" to "the writing crosses its axis here" - it does not give
`alternate` any new licence to repeat a pair, and the pair rule still applies to
every swing block regardless of where its side came from.

It also made the length of a swing block a property of the writing: a run of
four consecutive anchors on one side is one block covering all four. CF-0057
is what follows from that - a run can outlive the ordered hold and come out as
a single frame nobody can watch, while the alternation itself is exactly what
was written. `rhythm_shortfalls()` records that as a shortfall of the rhythm
rather than only of the pattern's cadence band; whether the planner should
prevent it, and at what cost to what `alternate` means, is still open.

--------------------------------------------------------------------------
Acceleration to the payoff
--------------------------------------------------------------------------

A curve over block length, applicable to any of the four rhythms, not a fifth
rhythm (CF-0041 objective 2). `strength` s means the last block is ordered at
(1 - s) of the first; the total is unchanged, because the total is the
voiceover and nothing here may move that. Boundaries are snapped to word
starts, so an accelerated cut still lands between words rather than through
one.

`explainer` declares acceleration permanently off, which is what keeps the
baseline baseline - tests/test_pattern_vocabulary.py in the repo root measures
the real corpus for exactly this curve and fails if it appears.
"""
import json
import math
import statistics
from pathlib import Path

# --------------------------------------------------------------------------
# constants. LEAD_SECONDS / MIN_ANCHOR_GAP_SECONDS / MAX_SHOT_REUSE live here rather
# than in resolve_anchors.py because the block plan is built here now;
# resolve_anchors.py imports them so the names it always exported still exist.
# --------------------------------------------------------------------------

# The eye has to arrive before the ear confirms: the shot lands slightly ahead
# of the word it illustrates, or the cut reads as a beat late.
LEAD_SECONDS = 0.35

# CF-0152: named for what it measures - the gap between one anchor and the
# next - and NOT for the length of a block. It is not a floor: when two anchors
# sit closer than this, resolve_anchors.py notes "too tight to read" in
# `unresolved` and builds the block anyway, so blocks shorter than 1.6s are
# normal output (153 of 369 blocks in 24 released plans). The block floor is a
# different number in a different repository - `patterns/validate_patterns.py
# MIN_BLOCK_SECONDS = 0.6`, the shortest block the pipeline has ever produced -
# and the two were called the same thing until CF-0152. 41.5% of the material
# lies between them, so importing the wrong one changes an answer quietly and
# plausibly: the structural ceiling of CF-0141 is 40.40s on 0.6 and 29.40s on
# 1.6. No alias for the old name is kept here on purpose - an alias would leave
# the collision importable, which is the whole defect.
MIN_ANCHOR_GAP_SECONDS = 1.6

# One sample, one use. CF-0026 measured the defect (one clip carried 40% of a
# video's runtime in the first batch) and set the cap at 3 with the caveat
# "2-3 times is the limit, and only when the script asks for it"; the operator's
# decision in CF-0074 (2026-09-05) removed the caveat's licence altogether -
# **no repeats by frame, a sample is used once in a video**. CF-0121 is that
# decision written down here: 1, not 3.
#
# The number is deliberately not a knob a run can turn down. `ShotLedger` below
# is the only code that reads it, and resolve_anchors.py's --max-shot-reuse
# defaults to it - the flag exists so a measurement can re-resolve an old batch
# at the old cap (CF-0121 item 3), not so a pipeline can quietly buy itself a
# second showing of the same shot.
MAX_SHOT_REUSE = 1


class ShotLedger:
    """Every sample this video has already shown, and the only place the reuse
    cap is read.

    A "sample" is a (source, shot number) pair - one shot of one footage
    source. It is the same sample whether it reaches the screen as a clip, as a
    frame held out of that clip (`hold_frame()`), as one side of a
    `side_by_side` opening, or as a still that degradation cut from it: what
    the viewer sees is the same picture a second time, which is what CF-0074
    refused. So there is one ledger per video and every shot-choice path asks
    it, rather than each path keeping its own set - `build_split_opening()` used
    to keep a local `taken`, main()'s fill loop a local `shot_uses` dict, and a
    third path (CF-0120's multi-shot swing block) would have arrived with a
    fourth. Being the single check is the point: a new caller that forgets to
    ask cannot silently get a repeat past the rule, because there is nothing
    else for it to ask.

    `fork()` is for a choice that may not survive: the `side_by_side` opening
    is resolved before it is known to be deliverable, and a discarded half's
    shots were never on screen, so they must not count as used. Resolve against
    a fork, then `take()` on the real ledger once the pictures are delivered.
    """

    def __init__(self, max_uses=None, retired=None):
        # The only read of MAX_SHOT_REUSE in the codebase (CF-0121).
        self.max_uses = MAX_SHOT_REUSE if max_uses is None else int(max_uses)
        self._uses = {}
        # CF-0397: the channel's memory beside this video's - a sample an
        # earlier ready video showed (`retired_shots.Retired`) is blocked here
        # too, so every path that asks this ledger refuses it without a check
        # of its own. None: no channel memory (a test, a batch outside
        # pipeline/), the old behaviour.
        self.retired_shots = retired

    def retired(self, key):
        """CF-0397: the refusal line when an earlier ready video of the
        channel already showed this sample, else None."""
        if self.retired_shots is None:
            return None
        import retired_shots  # local: rhythm.py is imported by it
        return self.retired_shots.reason(retired_shots.shot_name(key))

    def count(self, key):
        """How many times this sample has been taken."""
        return self._uses.get(key, 0)

    def blocked(self, key):
        """True when showing this sample again would break the cap - or when
        the channel already showed it in another ready video (CF-0397)."""
        return self.count(key) >= self.max_uses or self.retired(key) is not None

    def take(self, key):
        """Record one showing of this sample. Returns its new count."""
        self._uses[key] = self._uses.get(key, 0) + 1
        return self._uses[key]

    def give_back(self, key):
        """CF-0537: undo one take() of a cut that was dropped before its
        block was delivered (a soft shot traded for a sharp one under the
        similarity floor). Returns the count left; a key never taken is
        left at 0."""
        n = self._uses.get(key, 0) - 1
        if n > 0:
            self._uses[key] = n
        else:
            self._uses.pop(key, None)
        return max(n, 0)

    def fork(self):
        """A copy to resolve a not-yet-delivered choice against."""
        other = ShotLedger(self.max_uses, self.retired_shots)
        other._uses = dict(self._uses)
        return other

    @property
    def distinct(self):
        return len(self._uses)

    @property
    def total(self):
        return sum(self._uses.values())

    def uses(self):
        """{key: count}, for a report. A copy - the ledger stays the writer."""
        return dict(self._uses)

    def reason(self, key=None):
        """The `rejected_candidates` line for a candidate the cap turns away."""
        if self.max_uses == 1:
            return ("already used elsewhere in this video - one sample, one use "
                    "(CF-0121)")
        return (f"already used {self.max_uses}x elsewhere in this video "
                f"(CF-0026 cap)")

    def exhausted_reason(self):
        """The `unresolved_anchors` reason when the cap took the whole pool."""
        if self.max_uses == 1:
            return ("every remaining candidate was already used elsewhere in this "
                    "video - one sample, one use (CF-0121)")
        return (f"every remaining candidate was already used {self.max_uses}x "
                f"elsewhere in this video")


# --------------------------------------------------------------------------
# CF-0137: the emergency shot repeat - the rung above the assetless one
# --------------------------------------------------------------------------

# How many emergency repeats a *video* may spend. Deliberately a different
# shape from MAX_SHOT_REUSE above, and the difference is the whole decision:
# MAX_SHOT_REUSE is a per-sample cap ("this shot may appear once"), so a cap of
# 2 there would license one extra showing of every shot in the video and
# reproduce the CF-0026 defect a shot at a time. This is a per-video counter -
# one single repetition in the whole video, not one repetition per block that
# needs one. The second block that wants one does not get one; it gets the
# refusal, because a video that needs two emergency repeats is a video with no
# footage, and the answer to that is material, not a patched-over montage
# (CF-0123: an unfinished video is not shipped).
#
# CF-0121's rule is untouched. A sample is still used once by choice; this is
# the one explicitly-recorded exception, and every one of them lands in
# `rhythm_shortfalls` as an `emergency_reuse` entry saying the video was short
# of material - it is a signal, never a silent fix.
MAX_EMERGENCY_REUSE_PER_VIDEO = 1

# Why an emergency repeat was refused, in the wording that reaches
# `rejected_candidates` and `unresolved_anchors`.
REUSE_REFUSED_SWING = (
    "inside a swing block an emergency repeat is refused outright - CF-0074's "
    "'only distinct shots inside a swing block' does not bend, so the "
    "alternative here is the planner's refusal, not a stand-in (CF-0137)")
REUSE_REFUSED_ADJACENT = (
    "would sit next to its own first use - a repeated adjacent pair is what "
    "alternation_report() counts as a failed swing, so the one emergency "
    "repeat may not be spent there (CF-0137)")


class EmergencyReuseBudget:
    """The one emergency shot repeat a video is allowed, and its record.

    A counter of *videos*, not of shots: `ShotLedger` answers "may this sample
    be shown again", this answers "may this video patch one more hole at all".
    One instance per video, made where the ShotLedger is made, so the second
    block that asks is refused by the same object that granted the first.

    `take()` records what the repeat was spent on - which shot, which block,
    which block already had it - because the record *is* the deliverable here
    (CF-0137 item 4): a repeat nobody can see in the metadata is a defect
    hidden rather than reported.
    """

    def __init__(self, max_uses=None):
        self.max_uses = (MAX_EMERGENCY_REUSE_PER_VIDEO if max_uses is None
                         else int(max_uses))
        self._spent = []

    @property
    def spent(self):
        return len(self._spent)

    @property
    def remaining(self):
        return max(0, self.max_uses - self.spent)

    def available(self):
        """True while this video still has its emergency repeat unspent."""
        return self.spent < self.max_uses

    def take(self, record):
        """Spend the repeat on `record` and return it. Raises when spent -
        the caller has to have asked `allow()` first."""
        if not self.available():
            raise RhythmError(self.exhausted_reason())
        self._spent.append(dict(record))
        return self._spent[-1]

    def records(self):
        """What the repeats were spent on. A copy."""
        return [dict(r) for r in self._spent]

    def exhausted_reason(self):
        return (f"this video has already spent its {self.max_uses} emergency "
                f"shot repeat(s) - a second hole is not patched, the plan is "
                f"refused instead (CF-0137)")

    def allow(self, role, shot_key, prev_keys=()):
        """None when the repeat may be spent here, else why it may not.

        Three rules, in the order they are decided:

        * a swing block never gets one (`REUSE_REFUSED_SWING`) - CF-0074 says
          only distinct shots go inside a swing, and CF-0137 does not reopen
          it: what changes there is the alternative, from a stand-in block to
          the planner refusing the plan;
        * never adjacent to the block that already showed this shot
          (`REUSE_REFUSED_ADJACENT`) - `alternation_report()` reads a repeated
          adjacent pair as a swing that did not happen, so a repeat placed
          there buys a picture by breaking the cadence it was meant to save;
        * one per video (`exhausted_reason()`).
        """
        if role == "swing":
            return REUSE_REFUSED_SWING
        if shot_key in set(prev_keys or ()):
            return REUSE_REFUSED_ADJACENT
        if not self.available():
            return self.exhausted_reason()
        return None


RHYTHMS = ("even", "hold", "staccato", "alternate")
OPENING_KINDS = ("hook_over_footage", "cold_frame", "count_card", "side_by_side")

# How long the frame has to sit alone before the first word for the opening to
# be the `cold_frame` that was ordered rather than an ordinary opening with a
# rounding error in front of it. Below this the beat is not perceptible and
# claiming it would put an opening in the metadata that is not in the video.
COLD_FRAME_MIN_LEAD_SECONDS = 0.4
# What synthesize_voiceover.py is asked for when a cold frame is ordered and
# the caller named no length. Long enough to read as a deliberate beat, short
# enough that it does not eat a 35-60s budget - it is spent from that budget,
# not added to it, and build_render_plan.py records what it cost.
DEFAULT_LEAD_SILENCE_SECONDS = 0.7

# Shortest block the pipeline has ever produced is 0.60s; a rhythm may not cut
# finer than this when it splits a stretch to reach an ordered block count.
MIN_ORDERED_BLOCK_SECONDS = 0.7

# A clip that falls short of its block by less than this just plays out; past
# it, an ordered rhythm holds a frame instead of freezing on the last one.
HELD_FRAME_SLACK_SECONDS = 0.4

# CF-0075: how long a side of the `side_by_side` opening may stand on one
# frame. The opening spans the script's whole first run (12.12s on
# `wren-hollow-lockhart`, batch 2026-08-31T2155Z) and no clip in that footage
# is that long, so both halves were held frames for all of it - in the seconds
# where the viewer decides whether to stay. A half now plays its distinct clips
# back to back and may hold its last frame for at most this; past it the
# opening ends and the rest of the run goes through the ordinary block chain.
# 2.5s: the shortest still a motion video has held on purpose is ~2.4s (corn
# 2.41s, wren-hollow-christmas 2.38s) and the ordered `contrast` hold is 3.0s
# - above the one, below the other, and the same number as the staccato cap.
OPENING_MAX_STATIC_SECONDS = 2.5

# Defaults for an ordered rhythm whose parameter was left null. Only reached
# when a caller orders a rhythm without the matching parameter - the patterns
# in patterns/ all draw both.
DEFAULT_HOLD_SECONDS = 5.0
DEFAULT_STACCATO_CAP_SECONDS = 2.5

# --- the signature each rhythm has to still show in the delivered plan.
# `hold` is checked structurally rather than by a ratio: the block that carries
# the hold role has to be the longest one, has to reach the ordered length, and
# the video has to have fewer blocks than it had anchors - which is the rhythm's
# own definition, not a threshold anyone tuned. Degradation is the one thing
# that can dissolve it (a degraded key frame is no longer a frame anyone is
# holding); staccato and alternate are broken by a picture disappearing, not by
# a boundary moving, because degradation never moves a boundary.
HOLD_MIN_SECONDS = 4.0
STACCATO_MAX_CV = 0.45
ALTERNATE_MIN_SWAP_RATIO = 0.8
ALTERNATE_MIN_DISTINCT_PER_SIDE = 2

# CF-0120: the shortest a picture may stay up inside a swing block. A swing
# block is one crossing of the script's axis (CF-0050), so it is as long as the
# run of anchors the writing left on that side - 18.27s in the first `contrast`
# batch after CF-0119 - and one shot rarely covers that. It is filled with
# several *distinct* shots of the same side instead of a frozen frame, and this
# is the floor a cut inside it may not go under: under the anchor gap a cut is
# a flicker rather than a picture, and that gap is the same measurement of
# "long enough to read" `_base_segments()` already holds boundaries to. A floor
# on the *shot budget*, never on the block boundary: the boundary stays the
# crossing, so `swap_ratio` - measured on blocks - is untouched by how many
# shots one block was cut from. It borrows MIN_ANCHOR_GAP_SECONDS' number
# rather than restating 1.6, but it is its own quantity: move one and decide
# about the other deliberately.
MIN_SWING_CUT_SECONDS = MIN_ANCHOR_GAP_SECONDS


def swing_shot_budget(seconds):
    """How many distinct shots one swing block may be cut from (CF-0120).

    `even` leaves the budget open (`max_shots: None`) because its boundary was
    never load-bearing; `hold` and `staccato` pin it at 1 because the boundary
    *is* the instruction. A swing block is the third case, and that is what
    CF-0120 settles: its boundary is the instruction too (it is the crossing),
    and yet one shot over an 18s run is a frame nobody can watch. So the budget
    is bounded but larger than one - as many pictures as fit at
    MIN_SWING_CUT_SECONDS each, never fewer than one.
    """
    return max(1, int((float(seconds) + 1e-9) // MIN_SWING_CUT_SECONDS))

DEFAULT_ORDER = {
    "pattern_id": "explainer",
    "rhythm_id": "even",
    "parameters": {
        "block_count": None,
        "key_frame_hold_seconds": None,
        "opening_block": "hook_over_footage",
        "acceleration_to_payoff": {"enabled": False, "strength": None},
    },
}


class RhythmError(ValueError):
    pass


def normalize_order(raw):
    """Fill an order out to the shape the rest of this module expects.

    `None` means "no order was given", which is not a neutral state to invent a
    default for - it is precisely the pre-pattern behaviour, i.e. explainer on
    even with nothing drawn. Returning DEFAULT_ORDER for it is what makes a run
    without --order and a run with an explicit `even` order the same run.
    """
    order = {k: v for k, v in (raw or {}).items()}
    base = DEFAULT_ORDER
    order.setdefault("pattern_id", base["pattern_id"])
    order.setdefault("rhythm_id", base["rhythm_id"])
    if order["rhythm_id"] not in RHYTHMS:
        raise RhythmError(f"unknown rhythm {order['rhythm_id']!r} (known: {list(RHYTHMS)})")
    params = {k: v for k, v in (order.get("parameters") or {}).items()}
    for key, default in base["parameters"].items():
        params.setdefault(key, default)
    acc = params.get("acceleration_to_payoff") or {}
    params["acceleration_to_payoff"] = {
        "enabled": bool(acc.get("enabled")),
        "strength": acc.get("strength"),
    }
    if params["opening_block"] is None:
        params["opening_block"] = "hook_over_footage"
    if params["opening_block"] not in OPENING_KINDS:
        raise RhythmError(f"unknown opening block {params['opening_block']!r}")
    order["parameters"] = params
    return order


# --------------------------------------------------------------------------
# the opening block
# --------------------------------------------------------------------------

# Every opening kind that has a builder behind it. Not a copy of
# patterns/rhythms.json's `executable_today` - the vocabulary makes the claim,
# this is the executor, and tests/test_rhythm_execution.py in the factory root
# is what joins them. Kept here rather than in resolve_anchors.py so that the
# join can be checked without importing ffmpeg, CLIP and Vision.
OPENINGS_BUILT = ("hook_over_footage", "cold_frame", "count_card", "side_by_side")


def resolve_opening(kind, *, card_text=None, lead_silence=0.0, sides_resolved=0):
    """Which opening this video can actually deliver, and why not the ordered one.

    Returns `(delivered_kind, reason_or_None)`. Three of the four openings have
    a precondition that lives outside the block plan, and each one is a fact
    about *this* video rather than about the code: a count card needs a number
    the script actually promises, a cold frame needs a voiceover that does not
    start at 0.00s, and a side-by-side needs both sides of the comparison to
    have resolved footage. When a precondition is missing the opening falls
    back to `hook_over_footage` **in writing** - `patterns/rhythms.json` says
    so for side_by_side and CF-0041 established the shape for count_card - and
    the caller records the reason in `opening_delivered`'s company rather than
    letting the order stand as if it had been carried out.

    The fallback is never the *planned* path: `validate_patterns.draw_order()`
    picks from a pattern's `choices` at random with no executability filter, so
    an opening that always fell back would be an opening the vocabulary
    believes in and the video never shows.
    """
    if kind not in OPENINGS_BUILT:
        return "hook_over_footage", (
            f"opening {kind!r} has no builder here - fell back to hook_over_footage")
    if kind == "hook_over_footage":
        return kind, None
    if kind == "count_card":
        if card_text:
            return kind, None
        return "hook_over_footage", (
            "count_card was ordered but the anchors carry no opening_card.text - "
            "the number on the card has to be the number the script actually "
            "delivers, and nothing here knows it, so the opening fell back to "
            "hook_over_footage")
    if kind == "cold_frame":
        if lead_silence >= COLD_FRAME_MIN_LEAD_SECONDS:
            return kind, None
        return "hook_over_footage", (
            f"cold_frame was ordered but the narration starts at {lead_silence:.2f}s, "
            f"under the {COLD_FRAME_MIN_LEAD_SECONDS}s a held beat needs to read as "
            f"one - synthesize the voiceover with --lead-silence to buy it. Fell "
            f"back to hook_over_footage")
    # side_by_side
    if sides_resolved >= 2:
        return kind, None
    return "hook_over_footage", (
        f"side_by_side was ordered but only {sides_resolved} side(s) of the "
        f"comparison resolved to footage - both sides have to be on screen for "
        f"the axis to be visible before it is named. Fell back to "
        f"hook_over_footage")


# --------------------------------------------------------------------------
# segment arithmetic
# --------------------------------------------------------------------------

def _dur(seg):
    return seg["end"] - seg["start"]


def _snap(t, word_starts, lo, hi):
    """Nearest word start inside [lo, hi] - a cut between words, not through
    one. Falls back to the clamped time when no word starts in the window."""
    inside = [w for w in word_starts if lo <= w <= hi]
    if not inside:
        return min(max(t, lo), hi)
    return min(inside, key=lambda w: abs(w - t))


def _base_segments(anchor_starts, total, lead):
    """One segment per anchor, each holding until the next takes over.

    The first segment opens at 0.00s, not at its own anchor. CF-0276: the
    video starts with a picture whatever the script does, and
    `resolve_anchors.py` has always made that true by pulling block 0's start
    back to zero *after* the layout was finished - after every ceiling this
    module applies. So a script whose first anchor lands late got a first block
    that no cap had ever seen: `mormon-wives-comeback` (batch
    2026-09-17T1901Z) was laid out as 15 staccato blocks of at most 3.40s
    against contrast's 3.5s, and shipped with a first block of 4.86s, because
    2.70s of lead-in were added to a 2.16s segment afterwards. The head is
    screen time; it belongs to the layout that has to fit it, not to a
    correction applied once the layout can no longer answer for it.
    """
    segs = []
    n = len(anchor_starts)
    for i, s in enumerate(anchor_starts):
        start = 0.0 if i == 0 else max(0.0, s - lead)
        end = max(0.0, anchor_starts[i + 1] - lead) if i + 1 < n else total
        segs.append({"anchors": [i], "start": start, "end": max(end, start),
                     "role": "beat", "side": None, "max_shots": None,
                     "protected": False})
    return segs


def _spoken_dur(seg, anchor_starts):
    """`_dur` minus the dead air a segment opens with.

    Only the first segment ever has any: it starts where the video starts while
    its anchor's word arrives later, and that lead is silence or a sentence the
    script wrote before it named anything to look at. Used wherever a rhythm
    picks a segment *because the writing dwells there* - a hole in the anchor
    coverage is not dwelling, and on `you-can-see-everything` (2026-09-09,
    first anchor 10.80s in) picking by screen time would move the held key
    frame off the writing and onto the hole.
    """
    own = [anchor_starts[a] for a in seg["anchors"] if a < len(anchor_starts)]
    start = max(seg["start"], min(own)) if own else seg["start"]
    return max(0.0, seg["end"] - start)


def _merge_to(segs, target):
    """Merge adjacent segments, shortest combined pair first, until `target`.

    Shortest-first is what makes the survivors even: merging the two briefest
    neighbours is the move that costs the cadence least. A protected segment
    (the key frame of a `hold`) is never a party to a merge - absorbing it, or
    being absorbed into it, would move the very boundary the order named.
    """
    while len(segs) > target and len(segs) > 1:
        best, best_len = None, None
        for j in range(len(segs) - 1):
            if segs[j]["protected"] or segs[j + 1]["protected"]:
                continue
            span = segs[j + 1]["end"] - segs[j]["start"]
            if best_len is None or span < best_len:
                best, best_len = j, span
        if best is None:
            break
        a, b = segs[best], segs[best + 1]
        a["end"] = b["end"]
        a["anchors"] = a["anchors"] + b["anchors"]
        del segs[best + 1]
    return segs


def _split_one(segs, k, word_starts, min_block=MIN_ORDERED_BLOCK_SECONDS):
    """Cut segment `k` in half at the word boundary nearest its middle.
    Returns True when it actually split."""
    s = segs[k]
    if _dur(s) < 2 * min_block:
        return False
    cut = _snap((s["start"] + s["end"]) / 2, word_starts,
                s["start"] + min_block, s["end"] - min_block)
    if not (s["start"] < cut < s["end"]):
        return False
    tail = dict(s, start=cut, anchors=list(s["anchors"]))
    segs[k] = dict(s, end=cut)
    segs.insert(k + 1, tail)
    return True


def _split_to(segs, target, word_starts, min_block=MIN_ORDERED_BLOCK_SECONDS):
    """Split the longest unprotected segment at a word boundary near its
    middle, until `target` segments exist or nothing is long enough to cut."""
    while len(segs) < target:
        candidates = [k for k, s in enumerate(segs)
                      if not s["protected"] and _dur(s) >= 2 * min_block]
        if not candidates:
            break
        k = max(candidates, key=lambda i: _dur(segs[i]))
        if not _split_one(segs, k, word_starts, min_block):
            break
    return segs


def _divide(seg, parts, word_starts, min_block=MIN_ORDERED_BLOCK_SECONDS):
    """Cut one segment into `parts` near-equal pieces on word boundaries."""
    span = _dur(seg)
    if parts < 2 or span < parts * min_block:
        return [seg]
    edges = [seg["start"]]
    for k in range(1, parts):
        want = seg["start"] + span * k / parts
        lo = edges[-1] + min_block
        hi = seg["end"] - (parts - k) * min_block
        if lo > hi:
            break
        edges.append(_snap(want, word_starts, lo, hi))
    edges.append(seg["end"])
    return [dict(seg, start=a, end=b, anchors=list(seg["anchors"]))
            for a, b in zip(edges, edges[1:]) if b > a]


def _cap_lengths(segs, cap, word_starts, min_block=MIN_ORDERED_BLOCK_SECONDS,
                 movable=None):
    """Split anything longer than `cap` - staccato's blocks are short and
    near-equal by construction, and one long block is what makes it read as
    something else.

    `movable(seg)` says whether a new boundary may be drawn inside a segment at
    all; the default is every segment the rhythm did not protect. CF-0276 gives
    it a second caller (`_ceiling_pass`) where the answer is not the same for
    every rhythm, which is why the question is now the caller's.
    """
    if movable is None:
        def movable(s):
            return not s["protected"]
    guard = 0
    while guard < 400:
        guard += 1
        over = [k for k, s in enumerate(segs)
                if movable(s) and _dur(s) > cap and _dur(s) >= 2 * min_block]
        if not over:
            break
        # Split the offending segment itself. Splitting whatever happens to be
        # longest instead lets a segment that is already under the cap absorb
        # every cut and leaves the over-long one untouched, which is how an
        # 18-block order came back as 26 blocks.
        if not _split_one(segs, max(over, key=lambda i: _dur(segs[i])),
                          word_starts, min_block):
            break
    return segs


# --------------------------------------------------------------------------
# the rhythms
# --------------------------------------------------------------------------

def _plan_even(anchor_starts, total, order, word_starts, anchor_sides=None):
    """Untouched. The block count is emergent, so nothing here decides it."""
    return _base_segments(anchor_starts, total, LEAD_SECONDS)


def _plan_hold(anchor_starts, total, order, word_starts, anchor_sides=None):
    segs = _base_segments(anchor_starts, total, LEAD_SECONDS)
    if not segs:
        return segs
    params = order["parameters"]
    want_hold = params["key_frame_hold_seconds"] or DEFAULT_HOLD_SECONDS
    target = params["block_count"] or max(2, round(len(segs) / 2))

    # The passage the script already dwells on longest is the passage worth
    # holding: it is the one place the writing itself stopped moving. Measured
    # in spoken time (CF-0276): the first segment carries the lead-in before
    # its own anchor, and silence is not a passage the writing dwells on.
    k = max(range(len(segs)), key=lambda i: _spoken_dur(segs[i], anchor_starts))
    while _dur(segs[k]) < want_hold and k + 1 < len(segs):
        segs[k]["end"] = segs[k + 1]["end"]
        segs[k]["anchors"] += segs[k + 1]["anchors"]
        del segs[k + 1]
    while _dur(segs[k]) < want_hold and k > 0:
        segs[k - 1]["end"] = segs[k]["end"]
        segs[k - 1]["anchors"] += segs[k]["anchors"]
        del segs[k]
        k -= 1
    segs[k]["role"] = "hold"
    segs[k]["protected"] = True

    if len(segs) > target:
        _merge_to(segs, target)
    elif len(segs) < target:
        _split_to(segs, target, word_starts)

    # "the remaining anchors either fall away or become short punctuation
    # around that hold" - so nothing else may end up as long as the hold. When
    # the ordered block count leaves a punctuation block longer than the held
    # frame, the block count yields: it is a parameter of the pattern, while
    # this is the rhythm itself, and a video whose longest block is not the one
    # being held is not a hold at all. The overshoot shows up in the block
    # count that gets recorded, so it is visible rather than absorbed.
    hold_len = _dur(segs[[i for i, x in enumerate(segs) if x["role"] == "hold"][0]])
    guard = 0
    while guard < 400:
        guard += 1
        over = [k for k, x in enumerate(segs)
                if x["role"] != "hold" and _dur(x) >= hold_len]
        if not over:
            break
        if not _split_one(segs, max(over, key=lambda i: _dur(segs[i])), word_starts):
            break

    for s in segs:
        if s["role"] != "hold":
            s["role"] = "punctuation"
        # One frame a block. Chaining fill shots inside a block is what makes
        # `even` produce more blocks than anchors, and it is exactly what this
        # rhythm is asked not to do.
        s["max_shots"] = 1
    return segs


def _plan_staccato(anchor_starts, total, order, word_starts, anchor_sides=None):
    # No lead: the picture changes *on* the word that names the next item, not
    # a third of a second before it. This is the one mechanical difference
    # between staccato and even that a duration histogram cannot show.
    segs = _base_segments(anchor_starts, total, 0.0)
    if not segs:
        return segs
    params = order["parameters"]
    cap = params["key_frame_hold_seconds"] or DEFAULT_STACCATO_CAP_SECONDS
    target = params["block_count"] or len(segs)
    if len(segs) > target:
        _merge_to(segs, target)

    # "Blocks are short and near-equal by construction". Each item's stretch is
    # divided into equal pieces rather than halved repeatedly: halving a 5.3s
    # stretch under a 2.5s ceiling produces four 1.3s blocks where three of
    # 1.8s were asked for, which is how an 18-block order came back as 26.
    #
    # Two things set the number of pieces and the larger wins: the share of the
    # ordered block count this stretch is worth, and the ceiling the order put
    # on the longest block. The ceiling is not negotiable - it is
    # `key_frame_hold_seconds`, i.e. the longest block the pattern allows - so a
    # block count it cannot fit is overshot and the overshoot is visible in the
    # recorded cadence rather than hidden by a relaxed ceiling.
    total_span = sum(_dur(s) for s in segs) or 1.0
    divided = []
    for s in segs:
        by_target = max(1, round(target * _dur(s) / total_span))
        by_cap = max(1, math.ceil(_dur(s) / cap - 1e-9))
        divided.extend(_divide(s, max(by_target, by_cap), word_starts))
    segs = divided

    for s in segs:
        s["role"] = "item"
        s["max_shots"] = 1
    return segs


def declared_sides_usable(anchor_sides):
    """True when the script actually declared both sides of its comparison.

    One side declared is not a comparison, and a run built from it would be a
    single block. Anything short of both sides sends the caller back to
    `resolve_anchors.footage_sides()`, which is the fallback CF-0050 demoted it
    to rather than deleted: a script that never named its sides still gets the
    best partition the footage can offer.
    """
    seen = {s for s in (anchor_sides or []) if s in ("a", "b")}
    return len(seen) == 2


def opening_length(run_seconds, motion_seconds):
    """How long the `side_by_side` opening runs, given what each side can move.

    CF-0075. `run_seconds` is the stretch the opening was laid over (the
    script's first run); `motion_seconds` is `{side: seconds of distinct clips
    that side has}`. Each side moves for what it has, then may stand on its
    last frame for at most OPENING_MAX_STATIC_SECONDS, and the opening ends
    where the first side runs out of both. A side whose motion reaches the
    answer (within HELD_FRAME_SLACK_SECONDS) holds nothing. The remainder of
    the run is never left as a sliver no block could carry: under
    MIN_ORDERED_BLOCK_SECONDS it is added to the opening instead, and the
    overshoot is what `opening_report()` then records.

    Returns `(seconds, {side: static_seconds})`.
    """
    if not motion_seconds:
        return 0.0, {}
    length = min(run_seconds,
                 min(motion_seconds.values()) + OPENING_MAX_STATIC_SECONDS)
    if run_seconds - length < MIN_ORDERED_BLOCK_SECONDS:
        length = run_seconds
    static = {}
    for side, moved in motion_seconds.items():
        gap = length - moved
        static[side] = round(gap, 3) if gap > HELD_FRAME_SLACK_SECONDS else 0.0
    return round(length, 3), static


def side_runs(anchor_sides):
    """Group anchor indexes into runs of one declared side.

    A run is a maximal stretch of anchors that stays on one side. An anchor
    with no declared side does not start a new run and does not end one: it is
    a moment the script did not put on either side of the axis, and the honest
    reading of that is that the picture has not crossed over yet, not that the
    montage has a hole in it. Anchors before the first declared side join the
    first run for the same reason - and because the opening block has to start
    at 0.00s whatever else happens.

    Returns [(side, [anchor indexes]), ...].
    """
    runs, current = [], None
    for i, side in enumerate(anchor_sides):
        if side in ("a", "b") and side != current:
            runs.append((side, [i]))
            current = side
        elif runs:
            runs[-1][1].append(i)
        else:
            # No side has been declared yet; hold these for the first run.
            runs.append((None, [i]))
    if len(runs) > 1 and runs[0][0] is None:
        head_side, head = runs[1]
        runs = [(head_side, runs[0][1] + head)] + runs[2:]
    return runs


def _plan_alternate_declared(segs, anchor_sides):
    """The alternation the *script* declared, one block per crossing of the axis.

    CF-0050. Sides used to be two footage sources, which is a property of the
    files rather than of the writing: a comparison whose two halves were shot by
    the same camera had no second source and could not be alternated at all,
    while two sources that happened to be in the pool were declared to be the
    two sides of a comparison nobody had written. Here the block boundaries are
    the points where the script crosses its own axis, so the montage swings
    exactly where the writing does.

    The ordered `block_count` is not honoured on this path and that is the
    point, not an omission. A block per crossing is the rhythm's definition
    once the sides are declared; splitting a run to reach a higher count puts
    two same-side blocks next to each other, which is a swing that did not
    happen, and merging across a crossing deletes one that did. So the count
    yields and the rhythm stands - the same precedence `hold` already settled
    (CF-0041), where the ordered block count gives way rather than the held
    frame. `resolve_anchors.py` writes the overshoot into the plan's notes and
    `verify_pattern()` still measures the delivered cadence against the
    pattern's band, so a script that crosses its axis far too few or too many
    times is visible rather than quietly reshaped.
    """
    out = []
    for side, group in side_runs(anchor_sides):
        first, last = group[0], group[-1]
        start, end = segs[first]["start"], segs[last]["end"]
        out.append({"anchors": list(group),
                    "start": start, "end": end,
                    "role": "swing", "side": side,
                    # CF-0120: several distinct shots may go inside one
                    # crossing, and no new boundary is drawn to hold them.
                    "max_shots": swing_shot_budget(end - start),
                    "protected": False})
    return out


def _plan_alternate(anchor_starts, total, order, word_starts, anchor_sides=None):
    segs = _base_segments(anchor_starts, total, LEAD_SECONDS)
    if not segs:
        return segs
    if declared_sides_usable(anchor_sides):
        return _plan_alternate_declared(segs, list(anchor_sides))
    params = order["parameters"]
    # The pairs are what is being counted, so an odd block count leaves one
    # side unanswered - patterns/contrast.json says this is rounded here.
    target = params["block_count"] or len(segs)
    target = max(2, target - (target % 2))
    if len(segs) > target:
        _merge_to(segs, target)
    elif len(segs) < target:
        _split_to(segs, target, word_starts)
    for i, seg in enumerate(segs):
        seg["role"] = "swing"
        seg["side"] = "a" if i % 2 == 0 else "b"
        seg["max_shots"] = swing_shot_budget(_dur(seg))
    return segs


_PLANNERS = {
    "even": _plan_even,
    "hold": _plan_hold,
    "staccato": _plan_staccato,
    "alternate": _plan_alternate,
}


# --------------------------------------------------------------------------
# CF-0276: the pattern's hold band as a ceiling on the layout itself
#
# Before this, the only ceiling the block boundaries knew about was the one
# the *rhythm* carries - staccato's `key_frame_hold_seconds` cap, hold's "no
# punctuation block as long as the held one". A pattern's drawn
# `key_frame_hold_seconds` band was read twice, and both times too late to
# change a boundary: `verify_pattern()` (CF-0192) judges the finished plan,
# and `trim_to_hold_band()` (CF-0245) moves one boundary of an already-cut
# montage and refuses whenever moving it would freeze a frame. So the first
# thing that ever noticed a layout the pattern could not carry was CF-0270's
# `pattern_undeliverable` refusal, standing in front of the render with the
# only remedies that are left by then - widen the pool, or reassign the
# pattern - when the honest answer on `mormon-wives-comeback` was that block 0
# should have been cut in two 2.43s pieces before a single clip was fetched.
#
# What a ceiling may and may not do to a boundary is the whole content of this
# section. It may draw a new one inside a stretch the rhythm merely happened
# to divide that way; it may not move a boundary the rhythm *named*. Those are
# the swing blocks of a declared `alternate` (the boundary is the crossing -
# splitting one invents a swing the script never wrote, which
# `_plan_alternate_declared` refuses on the same grounds for the block count)
# and the held key frame of a `hold` (the boundary is the instruction). Where
# the ceiling may not cut, it says so with numbers instead - before the cut,
# which is the point of the whole exercise.
# --------------------------------------------------------------------------

# CF-0303: the one tolerance on the top of a hold band, and the only reason
# there is one at all.
#
# The composition is 30 fps (`plan.output.fps`, Root.jsx), and Video.jsx puts
# every block on that grid with `Math.round`: a block occupies
# `Math.round((end - start + 2*CROSSFADE) * fps)` frames, and since the
# crossfade is a whole number of frames (0.35s * 30 = 10.5 each side, 21 for
# the pair) the hold the viewer sees is `round(span * fps)` frames. So a block
# is over a ceiling of `top` seconds *on screen* when
# `round(span*fps) > round(top*fps)`, that is when `span >= top + 1/(2*fps)`.
# Half a frame is therefore not a slack anyone granted - it is the resolution
# at which the ceiling can be honoured at all, and an overshoot below it has no
# frame behind it to point at. It is the same move `end_card.check_ending()`
# makes with one frame of the composition and `common.LAST_FRAME_EPSILON` makes
# with one frame at 24 fps: a declared number against a measured span is
# compared at the grid the file is on.
#
# It is exact because every drawn band top in `patterns/` sits on a whole frame
# at 30 fps (contrast 3.5 -> 105, list 2.5 -> 75, moment-breakdown 9.0 -> 270;
# `tests/test_pattern_ceiling_gate.py` holds that). A pattern whose top did not
# would need the frame counts compared instead of the seconds.
#
# What the corpus says about the size of it: the overshoots the six videos with
# a hold band on disk actually produced are 0.4, 1.04, 1.36, 3.44 and 11.02 s at
# the video level, and 0.02 / 0.1 / 0.26 / 1.04 s at the block level
# (`coach-hale-stadiums`). The smallest of them is 0.02 s - larger than this
# tolerance, and 12 frames smaller than the smallest video-level one. So this
# constant flips no decision anywhere in the corpus; it exists so that no
# refusal is ever written on a number the picture cannot show.
HOLD_BAND_TOP_TOLERANCE_FRAMES = 0.5
COMPOSITION_FPS = 30
HOLD_BAND_TOP_TOLERANCE_SECONDS = round(
    HOLD_BAND_TOP_TOLERANCE_FRAMES / COMPOSITION_FPS, 3)


def over_band_top(measured, top):
    """True when `measured` seconds is over `top` by a frame the viewer sees.

    The one place the top of a hold band is compared, so that the judge
    (`ceiling_report`, `pattern_shortfalls`), the trim (CF-0245) and the
    refusal gate (CF-0270/CF-0303) can never drift apart - CF-0192's rule about
    the pattern verdict, applied to the comparison under it.
    """
    if measured is None or top is None:
        return False
    return float(measured) > float(top) + HOLD_BAND_TOP_TOLERANCE_SECONDS


def hold_band(pattern):
    """The pattern's `key_frame_hold_seconds` band when it *orders* one.

    `drawn` only, and that is CF-0039's rule kept rather than bent: an
    `emergent` band is an observation of what past videos did, and reshaping a
    montage to fit an observation is exactly how an observation turns into an
    order. A video outside an observed envelope still declines to claim the
    pattern (CF-0192) - it just is not cut differently because of it.

    Lived in `build_render_plan.py` until CF-0276 gave the block layout the
    same question to ask; it is re-exported there so its callers and tests keep
    the name they had, and there is still one copy of the rule.
    """
    band = (((pattern or {}).get("parameters") or {})
            .get("key_frame_hold_seconds") or {})
    if band.get("mode") != "drawn" or band.get("max") is None:
        return None
    return band


def load_pattern(pattern_id, patterns_dir):
    """`patterns/<id>.json`, or None when it cannot be read from here.

    None is a real answer and not an error: a checkout without the factory root
    beside it still builds plans, and `pattern_shortfalls()` already records
    `pattern_file_unreadable` for exactly this case. `patterns_dir` is passed in
    because this module has no opinion about where the factory root is - the
    two callers resolve it through `meme_layer.factory_root()`, which honours
    $FACTORY_ROOT.
    """
    try:
        return json.loads((Path(patterns_dir) / f"{pattern_id}.json").read_text())
    except (OSError, ValueError):
        return None


# --------------------------------------------------------------------------
# CF-0370: the pattern's drawn block-count ceiling as a shot budget on `even`
#
# Under `even` a segment's shot budget is open (`max_shots: None`) and the
# resolver cuts it into as many blocks as the pool's shots take to cover it.
# Trailer shots run short - 1.86 s on average on `you-can-see-everything`
# (2026-09-23T1722Z, lf-2026-09-23-004) - so 10 anchors came out as 22
# blocks against `moment-breakdown`'s drawn band 6-12, and the plan was
# refused `pattern_ceiling` after the wav. The layout itself had 10 segments:
# the count over the band was the chaining, not the writing.
#
# So on a pattern whose `block_count` band is drawn, the chain is budgeted:
# a segment may be cut into no more shots than leave every later segment one
# picture of its own under the band's top. What a capped segment cannot
# cover with its shots it holds - the last picture stays up to the segment's
# end, as a held frame lifted out of its clip when the clip is shorter
# (`resolve_anchors.hold_frame()`, the `still` an ordered rhythm already
# holds; not a degradation, and never CF-0031's chain). The held block is the
# segment's own stretch, which the hold-band ceiling above (CF-0276) has
# already cut to the band's top, so the hold never outruns the pattern.
#
# Front first, because the budget is spent in the order the video is watched:
# the resolver only learns how many shots a segment took by cutting them, and
# a budget that tried to foresee the later segments would be guessing the
# pool. A layout that has more segments than the top already is past this
# lever - one picture per segment is the fewest it can have - and that is
# said with its numbers (`block_band_cap` in the storyboard) rather than
# chained further.
#
# Count only, and drawn only. `emergent` is an observation (CF-0039); a drawn
# *rate* would need the length divided back in, and no pattern draws one.
# --------------------------------------------------------------------------

def block_count_ceiling(pattern):
    """The top of the pattern's block-count band when it is drawn as a count.

    None for an `emergent` or `floor_drawn` band, for a band stated as a rate,
    and for a pattern that could not be read - the cases in which nothing
    refuses a plan over the band's top (`cadence_band_refuses()`), and so
    nothing here may reshape one for it.
    """
    band = (((pattern or {}).get("parameters") or {}).get("block_count") or {})
    if not isinstance(band, dict) or band.get("mode") != BAND_MODE_DRAWN \
            or band.get("max") is None:
        return None
    return int(band["max"])


def even_shot_budget(top, blocks_so_far, segments_after, seconds=None,
                     hold_top=None):
    """How many shots an unordered segment may be cut from under `top`.

    Every segment after this one needs at least one picture, so this one may
    take what is left of the top after the blocks already laid down and one
    per later segment - never fewer than one, because a segment with no
    picture is a hole, not a hold. None when there is no ceiling to budget.

    `seconds` / `hold_top` are the segment's stretch and the pattern's drawn
    hold-band top: the budget never goes under the pictures that stretch
    needs to stay inside the hold band (`ceil(seconds / hold_top)`, at the
    band's frame tolerance). A segment is only ever longer than the hold top
    when an unfilled anchor before it was carried into it (CF-0124) - the
    layout itself was cut to the top (CF-0276) - and holding one frame over
    it would trade a count break for a hold break. The hold band wins,
    because the count is then over by a number `block_band_cap` records.
    """
    if top is None:
        return None
    budget = max(1, int(top) - int(blocks_so_far) - int(segments_after))
    if seconds is not None and hold_top:
        span = max(0.0, float(seconds) - HOLD_BAND_TOP_TOLERANCE_SECONDS)
        budget = max(budget, math.ceil(span / float(hold_top)))
    return budget


# Why a block still over the ceiling was left there. Codes, not sentences, for
# the reason CF-0192's `pattern_shortfalls` carries codes: this list is read
# beside that one and beside CF-0245's `hold_band_trims`.
CEILING_BOUNDARY_IS_THE_RHYTHM = "boundary_is_the_rhythm"
CEILING_NO_ROOM_TO_CUT = "no_room_to_cut"


def _boundary_is_the_rhythm(seg):
    """True when a new boundary inside this segment would delete the
    instruction the segment *is*: a declared crossing, or a held key frame."""
    return bool(seg.get("protected")) or seg.get("role") == "swing"


def _ceiling_pass(segs, ceiling, word_starts,
                  min_block=MIN_ORDERED_BLOCK_SECONDS):
    """Cut every segment the pattern's hold band cannot carry, where allowed."""
    return _cap_lengths(segs, ceiling, word_starts, min_block,
                        movable=lambda s: not _boundary_is_the_rhythm(s))


def ceiling_report(segs, order, pattern, anchor_starts):
    """What the finished layout could not bring under the pattern's ceiling.

    Written into the storyboard by `resolve_anchors.py` *before the first clip
    is cut*, so that the numbers CF-0270's gate refuses on are on the record
    one stage earlier, next to the reason the layout could not fix them.

    `lead_before_first_anchor` is always reported, breach or none. It is the
    seconds of video in front of the first anchor's word - screen time the
    montage has to cover with a picture nothing in the script asked for - and
    it is the single number behind the `mormon-wives-comeback` failure (2.70s
    of it turned a 2.16s block into a 4.86s one). It is reported here rather
    than fixed here because fixing it is writing, not montage: the anchor
    coverage belongs to the Content Researcher (CF-0233, CF-0277), and an
    editor that quietly conjured extra pictures for the hole would hide the
    defect the way CF-0245 was careful not to.
    """
    order = normalize_order(order)
    pid = order["pattern_id"]
    band = hold_band(pattern)
    lead = 0.0
    if segs and anchor_starts:
        lead = round(max(0.0, float(anchor_starts[0]) - segs[0]["start"]), 3)
    out = {
        "pattern_id": pid,
        "band": ({"mode": band.get("mode"), "min": band.get("min"),
                  "max": band.get("max")} if band else None),
        "lead_before_first_anchor": lead,
        "breaches": [],
    }
    if band is None:
        return out
    top = float(band["max"])
    for i, seg in enumerate(segs):
        measured = round(_dur(seg), 3)
        # CF-0303: over the top by a frame the viewer sees, not by a float.
        if not over_band_top(measured, top):
            continue
        code = (CEILING_BOUNDARY_IS_THE_RHYTHM
                if _boundary_is_the_rhythm(seg) else CEILING_NO_ROOM_TO_CUT)
        why = {
            CEILING_BOUNDARY_IS_THE_RHYTHM: (
                f"its boundaries are the {seg.get('role')} the rhythm named, "
                f"and a cut inside it would be a beat the script never wrote"),
            CEILING_NO_ROOM_TO_CUT: (
                f"there is no word boundary to cut on that leaves two blocks of "
                f"at least {MIN_ORDERED_BLOCK_SECONDS}s"),
        }[code]
        entry = {
            "kind": "layout_ceiling_breach",
            "block": i,
            "pattern_id": pid,
            "mode": band.get("mode"),
            "role": seg.get("role"),
            "measured": measured,
            "band_min": band.get("min"),
            "band_max": round(top, 3),
            "outside_by": round(measured - top, 3),
            "code": code,
        }
        head = ""
        if i == 0 and lead > 0:
            entry["lead_seconds"] = lead
            entry["measured_after_first_anchor"] = round(
                _spoken_dur(seg, anchor_starts), 3)
            head = (f" {lead}s of it is the lead-in before the first anchor's "
                    f"word, so the writing leaves {entry['measured_after_first_anchor']}s "
                    f"here and the montage has to carry the rest")
        entry["note"] = (
            f"block {i} is laid out at {measured}s against {pid}'s drawn hold "
            f"band {band.get('min')}-{round(top, 3)}s - over the top by "
            f"{entry['outside_by']}s before a single clip was cut, and "
            f"{why}.{head}")
        out["breaches"].append(entry)
    return out


def _own_anchor_cap(seg, anchor_starts, lead, eps=1e-6):
    """The latest a block may start and still be on its own word.

    CF-0084. A block illustrates the first anchor that actually lies inside
    it, and it may not begin after that word: the picture landing 1.4-6s
    behind the narration is what the Ink run (2026-09-03T2037Z, 004) looked
    like once acceleration had re-cut every boundary by index. The cap is that
    anchor's start minus the lead every other rhythm cuts ahead by. A block
    made by splitting a longer one carries its head's anchors, which all sit
    behind it - those are not its own, so it has no cap. Returns None when
    there is nothing to protect.
    """
    if not anchor_starts:
        return None
    own = [anchor_starts[a] for a in seg["anchors"]
           if a < len(anchor_starts) and anchor_starts[a] >= seg["start"] - eps]
    return (min(own) - lead) if own else None


def _unprotected_runs(segs):
    """Maximal runs of adjacent unprotected segments, as (first, last) index
    pairs. A protected segment's two boundaries are fixed - the same rule
    `_merge_to` applies - so acceleration redistributes inside each run and
    never across one."""
    runs, first = [], None
    for i, s in enumerate(segs):
        if s["protected"]:
            if first is not None:
                runs.append((first, i - 1))
                first = None
        elif first is None:
            first = i
    if first is not None:
        runs.append((first, len(segs) - 1))
    return runs


def apply_acceleration(segs, strength, word_starts,
                       min_block=MIN_ORDERED_BLOCK_SECONDS,
                       anchor_starts=None, lead=LEAD_SECONDS):
    """Redistribute the boundaries so blocks shorten toward the payoff.

    The span is fixed - the first block still starts where it started and the
    last still ends on the last word, because the audio decides that and
    nothing in the montage may move it. Only the interior boundaries move, and
    each is snapped to a word start.

    CF-0084 - three things the redistribution used to ignore, and now respects
    rather than the rhythm being written off as undelivered afterwards:

    * A boundary next to a `protected` segment (the key frame of a `hold`)
      does not move - the rule `_merge_to` already keeps. The held block keeps
      the length the planner gave it; the acceleration weights are spread over
      the runs of blocks on either side of it, each run inside its own fixed
      span, with the same index-based curve so it still reads as one
      acceleration across the video.
    * A boundary never lands later than the first anchor of the block it
      opens, minus `lead` - a block does not begin after the word it
      illustrates. Where that leaves no room, the boundary stays where the
      rhythm put it.
    * With a hold in the plan, no move may leave another block as long as the
      held one. A move that would is not made.
    """
    n = len(segs)
    if n < 3 or not strength:
        return segs
    weights = [1.0 - strength * (i / (n - 1)) for i in range(n)]
    # Caps come from the geometry the rhythm built, before anything moves.
    caps = [_own_anchor_cap(s, anchor_starts, lead) for s in segs]
    held = [s for s in segs if s["protected"] and s["role"] == "hold"]
    hold_len = _dur(held[0]) if held else None

    for a, b in _unprotected_runs(segs):
        if b <= a:
            continue
        t0, t1 = segs[a]["start"], segs[b]["end"]
        span = t1 - t0
        if span <= (b - a + 1) * min_block:
            continue
        scale = span / sum(weights[a:b + 1])
        t = t0
        for i in range(a, b):
            t += weights[i] * scale
            cur = segs[i]["end"]
            lo = segs[i]["start"] + min_block
            # The next boundary may end up staying put (its own cap can pin
            # it), so the block between them has to survive that case too.
            hi = min(t1 - (b - i) * min_block, segs[i + 1]["end"] - min_block)
            if caps[i + 1] is not None:
                hi = min(hi, caps[i + 1])
            if lo > hi:
                continue
            if word_starts and not any(lo <= w <= hi for w in word_starts):
                # Nothing to cut between inside the window: the boundary the
                # rhythm built stands rather than a cut through a word.
                continue
            cut = _snap(t, word_starts, lo, hi)
            if (cut - cur) * (t - cur) < 0:
                # The curve asks for a later boundary and the cap only leaves
                # room earlier (or the reverse): a move against the curve is
                # no acceleration, so the boundary stands.
                continue
            if hold_len is not None:
                # A block that is already as long as the hold (the planner
                # gave up splitting it) may still shrink; it may not grow.
                grows_past = False
                for old, new in ((_dur(segs[i]), cut - segs[i]["start"]),
                                 (_dur(segs[i + 1]), segs[i + 1]["end"] - cut)):
                    if new >= hold_len and new > old:
                        grows_past = True
                if grows_past:
                    continue
            segs[i]["end"] = cut
            segs[i + 1]["start"] = cut
    return segs


def plan_segments(anchor_starts, total, order=None, word_starts=None,
                  anchor_sides=None, pattern=None):
    """The block plan, before a single frame has been resolved.

    `anchor_starts` are the word times of the anchors, in order; `total` is the
    voiceover duration. `anchor_sides` (CF-0050) is the side each anchor was
    written on - `"a"`, `"b"` or None - which only `alternate` reads, and only
    when the script declared both. Returns a list of segments, each naming
    which anchors it covers, the role it plays in the rhythm, which side of an
    alternation it belongs to, and how many shots may fill it.

    `pattern` (CF-0276) is the pattern file's contents when it could be read.
    Its drawn hold band is a ceiling on this layout, applied last - after the
    acceleration, because acceleration moves boundaries and a ceiling checked
    before it would be a ceiling the delivered plan need not respect. What is
    still over it after this is `ceiling_report()`'s answer, and it is the
    caller's job to write that down.
    """
    order = normalize_order(order)
    word_starts = sorted(word_starts or [])
    segs = _PLANNERS[order["rhythm_id"]](
        list(anchor_starts), float(total), order, word_starts,
        list(anchor_sides) if anchor_sides else None)
    acc = order["parameters"]["acceleration_to_payoff"]
    if acc["enabled"] and acc.get("strength"):
        apply_acceleration(segs, float(acc["strength"]), word_starts,
                           anchor_starts=list(anchor_starts))
    band = hold_band(pattern)
    if band is not None:
        _ceiling_pass(segs, float(band["max"]), word_starts)
    for s in segs:
        s["start"] = round(s["start"], 3)
        s["end"] = round(s["end"], 3)
    return segs


# --------------------------------------------------------------------------
# measurement: what the finished plan actually is
# --------------------------------------------------------------------------

def cadence(blocks):
    """The delivered cadence as numbers, not as an adjective.

    `05-video-editor.json` carries this next to `rhythm_delivered` on purpose:
    the label is a judgement made by the thresholds below, and the Analyst has
    to be able to disagree with it later without re-deriving the video.
    """
    durations = [round(b["end"] - b["start"], 3) for b in blocks]
    if not durations:
        return {"block_count": 0, "durations": [], "mean": None, "median": None,
                "stdev": None, "cv": None, "longest": None, "shortest": None,
                "acceleration_ratio": None, "blocks_per_minute": None}
    mean = statistics.mean(durations)
    stdev = statistics.pstdev(durations) if len(durations) > 1 else 0.0
    third = max(1, len(durations) // 3)
    ratio = (statistics.mean(durations[-third:]) /
             statistics.mean(durations[:third])) if len(durations) >= 3 else None
    return {
        "block_count": len(durations),
        "durations": durations,
        "mean": round(mean, 3),
        "median": round(statistics.median(durations), 3),
        "stdev": round(stdev, 3),
        "cv": round(stdev / mean, 3) if mean else None,
        "longest": max(durations),
        "shortest": min(durations),
        "acceleration_ratio": round(ratio, 3) if ratio is not None else None,
        # CF-0310: the same count, divided by the time the blocks themselves
        # span. `block_count` is a count *and* a length - a 34s video and a 55s
        # video cut at the same pace do not produce the same number - and
        # CF-0039's envelope was measured on 40-49s videos, so the count read
        # against it answers "was this video as long as those" as much as "was
        # it cut like those". This divides the length back out. The span is the
        # blocks' own (`sum(durations)`), never `duration.composition`: the end
        # card and the tail carry no blocks, and a rate measured over them
        # would drift with the tail's length rather than with the cutting.
        "blocks_per_minute": (round(len(durations) / (sum(durations) / 60.0), 2)
                              if sum(durations) else None),
    }


def repeated_adjacent_pairs(shots):
    """How many adjacent (shot, shot) pairs occur more than once.

    This is CF-0034's defect expressed as a number. Shots 43 and 36 alternating
    over four consecutive blocks produce the pair (43, 36) twice; every shot
    involved was used twice, well inside CF-0026's cap of 3, which is why the
    cap never saw it. Intentional alternation keeps this at zero.
    """
    seen, repeats = set(), 0
    for a, b in zip(shots, shots[1:]):
        if a is None or b is None:
            continue
        key = (a, b)
        if key in seen:
            repeats += 1
        else:
            seen.add(key)
    return repeats


# A block that shows both sides of the comparison at once - the `side_by_side`
# opening (CF-0050). It is neither side, and it is emphatically not a hole:
# counting it as one would mean the opening that states the axis most directly
# is also the one most likely to cost the video its `rhythm_delivered`.
BOTH_SIDES = "both"


def alternation_report(blocks):
    """Measure the A-B-A-B on the delivered blocks.

    Blocks with no side (a card, or a block degraded to typographic - its
    picture is gone, so it is not on either side of anything) break the chain
    where they sit, which is the honest reading: an alternation with a hole in
    it is not the alternation that was ordered.

    A `side_by_side` block is the exception, and by measurement rather than by
    exemption: it has a picture, and that picture is both sides. Neither of the
    two boundaries it touches is a swing the montage failed to make, so those
    two boundaries are not counted either way rather than counted as failures.
    Its own shots are left out of `distinct_shots_per_side` - the block is one
    frame containing two, not a shot on a side - so it can neither rescue a
    side that has nothing else nor pad one that does.
    """
    sides = [b.get("side") for b in blocks]
    pairs = [(a, b) for a, b in zip(sides, sides[1:])
             if BOTH_SIDES not in (a, b)]
    swaps = sum(1 for a, b in pairs if a and b and a != b)
    # CF-0120 item 4: `swap_ratio` stays a measure of *blocks* - a block is a
    # crossing of the axis and nothing about filling one from several shots
    # moves a boundary, so this number reads exactly as it did before. The pair
    # rule is the opposite case and it moves to shots: CF-0034's defect is two
    # pictures the viewer sees in the same order twice, and after CF-0120 two
    # of those pictures can sit inside one block. Counted per block, a repeat
    # hidden inside a swing block would be invisible to the very check that
    # exists to catch it.
    shown = [s for b in blocks for s in (block_shots(b) or [None])]
    distinct = {}
    for b in blocks:
        side = b.get("side")
        if side in ("a", "b"):
            for shot in block_shots(b):
                distinct.setdefault(side, set()).add(shot)
    return {
        "sides": sides,
        "swap_ratio": round(swaps / len(pairs), 3) if pairs else None,
        "distinct_shots_per_side": {k: len(v) for k, v in sorted(distinct.items())},
        "shots": shown,
        "repeated_adjacent_pairs": repeated_adjacent_pairs(shown),
        "blocks_without_side": sum(1 for s in sides if not s),
        "both_sides_blocks": sum(1 for s in sides if s == BOTH_SIDES),
    }


# --------------------------------------------------------------------------
# CF-0057: how long the picture stands still on one side
# --------------------------------------------------------------------------

# Kinds that do not move. A `still` is a frame, a `card` is drawn text, a
# `split` is two frames side by side - none of them changes while it is up. A
# `clip` does, and `procedural` is the assetless rung, which never carries a
# side anyway (build_render_plan.py strips side and shot when it degrades a
# block, so a hole in the alternation stays a hole).
FROZEN_KINDS = ("still", "card", "split")

# CF-0136: what counts as a picture at all. The four kinds a block can carry
# something watchable in; anything else - `procedural`, or a block with no
# asset key whatsoever - is the assetless rung, the block the planner still
# cut on time because the cadence had to survive a footage shortage even
# though the picture did not (CF-0085). `verify_rhythm()` has read the same
# four since CF-0041 to decide whether any picture is left at all; this names
# the set once so the shortfall record and the verdict cannot drift apart.
PICTURE_KINDS = ("clip", "still", "card", "split", "sequence", "own_graphic")
# CF-0689: `own_graphic` - a graphic the factory draws from the script's facts
# (ExampleTech's base footage) - is a picture, and it is NOT frozen: it
# animates for its whole block (GraphicLayer.jsx), and qc_render.py probes
# its render with the same longest-still-run rule as a clip, so one that
# stands still is a fault there, not a pass here.


def block_cuts(block):
    """The pictures a multi-picture block shows in order, or None (CF-0120).

    A `sequence` block is one crossing of the axis cut from several distinct
    shots of that side. It reads the same on the storyboard (`cuts` at the top
    level, as resolve_anchors.py writes it) and on the render plan (under the
    asset, as build_render_plan.py frames it), because both are handed to the
    measurement functions below by their own tests.

    A `split` block is deliberately not one of these: its halves are two
    pictures *at once* rather than one after another, and CF-0050 already
    decided it counts as neither side.
    """
    asset = block.get("asset")
    # On a storyboard block `asset` is the path to the one file the block
    # shows, not a dict - and a storyboard block is what resolve_anchors.py's
    # own tests hand these functions.
    asset = asset if isinstance(asset, dict) else {}
    if asset.get("kind") == "split" or block.get("asset_kind") == "split":
        return None
    cuts = block.get("cuts") or asset.get("cuts")
    return list(cuts) if cuts else None


def block_shots(block):
    """Every sample this block puts on screen, in order (CF-0120).

    One entry for an ordinary block, several for a swing block cut from
    several shots. Consecutive duplicates collapse: a sequence's held tail is
    a frame of the cut before it - the picture still on screen, not a second
    showing of that sample - exactly as CF-0075 reads a split half's hold.
    Returns `[]` for a block with no picture, which is what breaks a chain.
    """
    cuts = block_cuts(block)
    if cuts:
        out = []
        for c in cuts:
            shot = c.get("shot")
            if shot is not None and (not out or out[-1] != shot):
                out.append(shot)
        return out
    shot = block.get("shot")
    return [] if shot is None else [shot]


def has_picture(block):
    """Whether this block puts anything on screen."""
    return block.get("asset", {}).get("kind") in PICTURE_KINDS


def _is_frozen(block):
    """Whether this block's picture is a standing frame rather than motion."""
    cuts = block_cuts(block)
    if cuts:
        # CF-0120: a sequence stands still only if every one of its pictures
        # does - one moving cut in it is the difference between a montage and
        # the frozen frame this block plan exists to replace.
        return all(bool(c.get("held_frame")) or c.get("kind") in FROZEN_KINDS
                   for c in cuts)
    return (bool(block.get("held_frame")) or
            block.get("asset", {}).get("kind") in FROZEN_KINDS)


def _picture_id(block):
    """What identifies the picture on screen, for "did it change" purposes.

    The shot alone is not enough: two blocks can hold two different frames
    lifted out of the same shot, and to a viewer that is a cut, not a hold.
    """
    asset = block.get("asset", {})
    # CF-0689: two own graphics are two pictures; None on every other kind.
    if asset.get("graphic_id") is not None:
        return (block.get("shot"), asset.get("src"), asset.get("text"),
                asset.get("graphic_id"))
    return (block.get("shot"), asset.get("src"), asset.get("text"))


def block_pictures(block):
    """Every distinct picture this block shows, as `_picture_id()` sees them.

    CF-0120: a swing block is no longer one picture, so "how many pictures did
    this run of one side show" cannot be counted per block any more. A held
    tail carries the same shot as the cut it was lifted from but its own file,
    so it is a picture of its own here - which is right: the viewer did see
    the montage stop moving, and `frozen` above is what says it stopped.
    """
    cuts = block_cuts(block)
    if not cuts:
        return [_picture_id(block)]
    return [(c.get("shot"), c.get("src") or c.get("asset"), None) for c in cuts]


def delivered_side_runs(blocks):
    """The stretches the picture spends without crossing the axis.

    CF-0050 made a block one crossing of the axis, so the length of a block is
    set by how many consecutive anchors the script left on one side, not by the
    ordered block count. This groups the delivered blocks back into those
    stretches and measures each one, which is the unit CF-0057 is about: a run
    of four anchors is one 15-second stretch on side `b`, however many blocks it
    was cut into.

    A block with no side (a card outside the alternation, or one degraded to
    typographic - its picture is gone) ends the run it sits in and starts no new
    one: `alternation_report()` already reads that as a hole, and a hole is not
    a stretch on a side. `both` runs are measured too, because a `side_by_side`
    opening also holds the picture still, but they are labelled as themselves -
    what to do about a long opening is a different question from what to do
    about a long run on one side, and this only records it.

    `single_held_frame` is the property the exit criterion turns on: the whole
    run is one unchanging frame, so nothing moves for `seconds` on end.
    """
    runs, current = [], None
    for i, b in enumerate(blocks):
        side = b.get("side")
        if not side:
            current = None
            continue
        if current is not None and current["side"] == side:
            current["blocks"].append(i)
            current["end"] = float(b["end"])
        else:
            current = {"side": side, "blocks": [i],
                       "start": float(b["start"]), "end": float(b["end"])}
            runs.append(current)
    out = []
    for run in runs:
        members = [blocks[i] for i in run["blocks"]]
        frozen = all(_is_frozen(b) for b in members)
        # CF-0120: per picture, not per block. A swing block cut from three
        # shots shows three pictures, and a run that used to be one frozen
        # frame is now measured as the montage it is.
        pictures = {p for b in members for p in block_pictures(b)}
        out.append({
            "side": run["side"],
            "blocks": run["blocks"],
            "start": round(run["start"], 3),
            "end": round(run["end"], 3),
            "seconds": round(run["end"] - run["start"], 3),
            "shots": [s for b in members for s in block_shots(b)],
            "pictures": len(pictures),
            "frozen": frozen,
            "single_held_frame": frozen and len(pictures) == 1,
        })
    return out


def opening_report(blocks):
    """The `side_by_side` opening as delivered, per side (CF-0075).

    Reads the plan's split block: each half carries `cuts`, one per picture
    it showed in order, with `seconds` on screen and `held_frame` on the one
    that is a frame lifted out of the clip before it. A half with no `cuts`
    (a plan built before CF-0075) is one picture for the whole block. Per
    side: how long it moved, how long it stood, and the longest single stand.
    `run_seconds` is the stretch the opening was laid over and
    `truncated_seconds` how much of it the opening gave back to the ordinary
    blocks - both come from the storyboard, and an older plan reports the
    block as its own run. None when the video has no split block.
    """
    for i, b in enumerate(blocks):
        asset = b.get("asset", {})
        if b.get("side") != BOTH_SIDES or asset.get("kind") != "split":
            continue
        seconds = round(float(b["end"]) - float(b["start"]), 3)
        sides = {}
        for half in asset.get("sides", []):
            cuts = half.get("cuts") or [{**half, "seconds": seconds}]
            motion = static = longest = 0.0
            shots = []
            for c in cuts:
                span = float(c.get("seconds") if c.get("seconds") is not None
                             else seconds)
                shots.append(c.get("shot"))
                if c.get("held_frame") or c.get("kind") in FROZEN_KINDS:
                    static += span
                    longest = max(longest, span)
                else:
                    motion += span
            sides[half.get("side")] = {
                "cuts": len(cuts),
                "shots": shots,
                "motion_seconds": round(motion, 3),
                "static_seconds": round(static, 3),
                "longest_static_seconds": round(longest, 3),
            }
        run = b.get("opening_run_seconds")
        run = round(float(run), 3) if run is not None else seconds
        longest_static = max((v["longest_static_seconds"] for v in sides.values()),
                             default=0.0)
        return {
            "block": i,
            "start": round(float(b["start"]), 3),
            "end": round(float(b["end"]), 3),
            "seconds": seconds,
            "run_seconds": run,
            "truncated_seconds": round(max(0.0, run - seconds), 3),
            "ceiling_seconds": OPENING_MAX_STATIC_SECONDS,
            "longest_static_seconds": longest_static,
            "static_over_ceiling": longest_static > OPENING_MAX_STATIC_SECONDS,
            "sides": sides,
        }
    return None


def opening_shortfalls(blocks):
    """CF-0075's entry for `rhythm_shortfalls`: the opening had to stand still
    past OPENING_MAX_STATIC_SECONDS, or could not carry its run and handed the
    rest back. A held tail inside the ceiling that finishes the run is the
    ceiling working as designed and is only in `opening_report()`."""
    rep = opening_report(blocks)
    if not rep or not (rep["static_over_ceiling"] or rep["truncated_seconds"] > 0):
        return []
    sides = rep["sides"]
    what = []
    if rep["static_over_ceiling"]:
        what.append(f"stands on one frame for {rep['longest_static_seconds']:.2f}s "
                    f"against a ceiling of {rep['ceiling_seconds']:.2f}s")
    if rep["truncated_seconds"] > 0:
        what.append(f"carries {rep['seconds']:.2f}s of the {rep['run_seconds']:.2f}s "
                    f"run it was laid over - {rep['truncated_seconds']:.2f}s went to "
                    f"the ordinary blocks because neither side had more distinct "
                    f"footage")
    return [{
        "kind": "opening_static_held",
        "opening": "side_by_side",
        "side": BOTH_SIDES,
        "blocks": [rep["block"]],
        "start": rep["start"],
        "end": rep["end"],
        "seconds": rep["seconds"],
        "run_seconds": rep["run_seconds"],
        "truncated_seconds": rep["truncated_seconds"],
        "ceiling_seconds": rep["ceiling_seconds"],
        "longest_static_seconds": rep["longest_static_seconds"],
        "over_by_seconds": round(max(0.0, rep["longest_static_seconds"]
                                     - rep["ceiling_seconds"]), 3),
        "sides": sides,
        "shots": [s for v in sides.values() for s in v["shots"]],
        "note": ("the side-by-side opening (block "
                 f"{rep['block']}) " + "; ".join(what)
                 + " - the sides are " + ", ".join(
                     f"{k}: {v['motion_seconds']:.2f}s moving / "
                     f"{v['static_seconds']:.2f}s still" for k, v in sides.items())
                 + " (CF-0075)"),
    }]


def side_run_report(blocks, hold_seconds=None):
    """`delivered_side_runs()` plus the ordered hold they are read against.

    Written into the plan whole rather than as a verdict: the Analyst (CF-0023)
    has to be able to ask "how long does this pattern actually leave the picture
    on one side" without re-deriving it from block boundaries, including on the
    runs that are perfectly fine.
    """
    runs = delivered_side_runs(blocks)
    held = [r["seconds"] for r in runs if r["single_held_frame"]]
    return {
        "hold_ordered_seconds": round(hold_seconds or DEFAULT_HOLD_SECONDS, 3),
        "hold_seconds_source": "order" if hold_seconds else "default",
        "runs": runs,
        "longest_run_seconds": max((r["seconds"] for r in runs), default=None),
        "longest_held_run_seconds": max(held, default=None),
        # CF-0075: the `both` run's own record - what each side of the opening
        # moved and held, against its ceiling and the run it was laid over.
        "opening": opening_report(blocks),
        # CF-0120 item 5: which crossings were assembled from several shots,
        # and out of what. The Analyst asks "where did a side stop being one
        # frozen frame" and gets an answer without reading the block list.
        "swing_block_shots": swing_block_shots(blocks),
    }


def swing_block_shots(blocks):
    """Where one crossing of the axis was cut from more than one shot (CF-0120).

    One entry per multi-picture block, in block order: which shots, in what
    order, how long the block runs, and how much of it its last picture had to
    stand still for because the side ran out of distinct footage. An empty list
    on every plan built before CF-0120 and on every plan where each crossing
    happened to have one shot long enough - which is the fact the Analyst is
    comparing against when one does not.
    """
    out = []
    for i, b in enumerate(blocks):
        cuts = block_cuts(b)
        if not cuts or len(cuts) < 2:
            continue
        held = sum(float(c.get("seconds") or 0.0) for c in cuts
                   if c.get("held_frame") or c.get("kind") in FROZEN_KINDS)
        out.append({
            "index": i,
            "side": b.get("side"),
            "shots": block_shots(b),
            "pictures": len(cuts),
            "seconds": round(float(b["end"]) - float(b["start"]), 3),
            "held_tail_seconds": round(held, 3),
        })
    return out


# --------------------------------------------------------------------------
# CF-0136: how much of the video has no picture at all
# --------------------------------------------------------------------------


def assetless_runs(blocks):
    """The stretches the video spends with nothing on screen.

    The counterpart of `delivered_side_runs()` for the other failure: not the
    picture standing still, the picture never arriving. A block on the
    assetless rung is still a block - the planner cut it on time because the
    cadence must survive a footage shortage (CF-0085) - so the timeline is
    intact and every rhythm verifier still confirms itself over it. What is
    gone is the thing the montage was for.

    Consecutive assetless blocks are one run, because that is how a viewer
    meets them: two `procedural` blocks back to back are one uninterrupted
    stretch of no picture, whatever the cut between them says.
    """
    runs, current = [], None
    for i, b in enumerate(blocks):
        if has_picture(b):
            current = None
            continue
        if current is None:
            current = {"blocks": [i], "start": float(b["start"]),
                       "end": float(b["end"])}
            runs.append(current)
        else:
            current["blocks"].append(i)
            current["end"] = float(b["end"])
    return [{"blocks": r["blocks"],
             "start": round(r["start"], 3),
             "end": round(r["end"], 3),
             "seconds": round(r["end"] - r["start"], 3)} for r in runs]


def picture_report(blocks, hold_seconds=None):
    """`assetless_runs()` plus the counts, written into the plan whole.

    Same shape and same reason as `side_run_report()`: the Analyst (CF-0023)
    has to be able to ask "how much of this video actually had a picture"
    without re-deriving it from the block list, including on the plans where
    the answer is "all of it".
    """
    runs = assetless_runs(blocks)
    absent = sum(len(r["blocks"]) for r in runs)
    return {
        "hold_ordered_seconds": round(hold_seconds or DEFAULT_HOLD_SECONDS, 3),
        "hold_seconds_source": "order" if hold_seconds else "default",
        "blocks": len(blocks),
        "picture_blocks": len(blocks) - absent,
        "assetless_blocks": absent,
        "assetless_seconds": round(sum(r["seconds"] for r in runs), 3),
        "longest_assetless_run_seconds": max((r["seconds"] for r in runs),
                                             default=None),
        "runs": runs,
    }


def picture_absent_shortfalls(order, blocks):
    """CF-0136's two entries for `rhythm_shortfalls`.

    The hole CF-0123 found: `rhythm_shortfalls()` knew two kinds, both of them
    about a picture that is present and not moving, and neither of them fires
    on a picture that is not there. So a plan with 25 of its 30 blocks on the
    assetless rung came back `rhythm_delivered_fully: True` - the cadence was
    exactly as ordered, nothing *about the timeline* fell short - against that
    field's own contract, "the rhythm is in the video *and* nothing about it
    fell short". CF-0123 decided variant A: `rhythm_delivered` is left alone,
    because it is the honest record of what happened to the timeline, and the
    missing picture goes into the second field, on CF-0057's precedent.

    Two kinds, and the split between them is not decorative:

    * `picture_absent_run` - consecutive assetless blocks running longer than
      the ordered `key_frame_hold_seconds`. The threshold is not invented: it
      is the same ordered hold `long_side_run_held` is read against, and it
      means the same thing there and here - past the hold the picture was
      supposed to change, and it did not, because there was nothing to change
      to.
    * `picture_absent_blocks` - every assetless block, with no threshold at
      all. This is what the run cannot see: 25 degraded blocks laid out as
      "two stubs, one clip, two stubs" produce no run longer than a 2.5s
      hold, and reporting nothing there would reproduce the exact bug this
      task exists to close. CF-0123: no threshold is needed and so none is
      invented - by the contract of `rhythm_delivered_fully` a degraded block
      is literally "not finished", one or twenty-five of them.

    The second kind is one aggregate entry, not one per block, on purpose.
    Every entry in this list is copied into `deviations` as a sentence and
    printed as its own `RHYTHM SHORT` line by write_batch_metadata.py; 25
    identical lines would be noise where a record is wanted. Nothing is lost
    by aggregating - `blocks` carries every index and `block_seconds` the
    seconds of each, in the same order.

    Applies to every rhythm, not only `alternate`. The picture is missing in
    the same way whatever cadence it is missing under, and the real case
    CF-0123 was written from is a `staccato`.
    """
    order = normalize_order(order)
    rep = picture_report(blocks, order["parameters"]["key_frame_hold_seconds"])
    if not rep["assetless_blocks"]:
        return []
    rid = order["rhythm_id"]
    want = rep["hold_ordered_seconds"]
    out = []
    for run in rep["runs"]:
        if run["seconds"] <= want:
            continue
        out.append({
            "kind": "picture_absent_run",
            "rhythm_id": rid,
            "blocks": list(run["blocks"]),
            "start": run["start"],
            "end": run["end"],
            "seconds": run["seconds"],
            "hold_ordered_seconds": want,
            "hold_seconds_source": rep["hold_seconds_source"],
            "over_by_seconds": round(run["seconds"] - want, 3),
            "note": (
                f"nothing is on screen for {run['seconds']:.2f}s "
                f"(block(s) {run['blocks']}) - {len(run['blocks'])} block(s) on "
                f"the assetless rung in a row, against an ordered hold of "
                f"{want:.2f}s. The {rid} cadence is intact; what is short is "
                f"the picture it was cut for (CF-0136)"),
        })
    indices = [i for r in rep["runs"] for i in r["blocks"]]
    out.append({
        "kind": "picture_absent_blocks",
        "rhythm_id": rid,
        "blocks": indices,
        "block_seconds": [round(float(blocks[i]["end"]) - float(blocks[i]["start"]), 3)
                          for i in indices],
        "seconds": rep["assetless_seconds"],
        "picture_blocks": rep["picture_blocks"],
        "assetless_blocks": rep["assetless_blocks"],
        "total_blocks": rep["blocks"],
        "longest_assetless_run_seconds": rep["longest_assetless_run_seconds"],
        "note": (
            f"{rep['assetless_blocks']} of {rep['blocks']} block(s) carry no "
            f"picture at all ({rep['assetless_seconds']:.2f}s of the video, "
            f"block(s) {indices}) - the {rid} cadence was delivered over the "
            f"assetless rung. No threshold: a degraded block is undelivered "
            f"picture whether there is one or twenty-five (CF-0136)"),
    })
    return out


# --------------------------------------------------------------------------
# CF-0137: the emergency repeat, as it reads off the finished plan
# --------------------------------------------------------------------------


def emergency_reuse_report(blocks):
    """Which blocks were filled by the one emergency repeat, and with what.

    Written into `plan["rhythm"]["emergency_reuse"]` whole, on every plan -
    the same reason `picture` is (CF-0136): "no repeat was needed" is as much
    a fact about a video as "one was", and the Analyst must not have to
    re-derive either from the block list.

    Where the shot's other showing is, is read back off the plan rather than
    trusted from the resolver's own note: the plan is the artefact that
    shipped, and a repeat whose first use cannot be pointed at in it is not a
    record of anything. `adjacent_to_first_use` is therefore a check, not a
    field the resolver fills in - it must be False on every plan (CF-0074 via
    `EmergencyReuseBudget.allow()`), and a True is a defect this report is how
    you find.
    """
    reuses = []
    for i, b in enumerate(blocks):
        rec = b.get("emergency_reuse")
        if not rec:
            continue
        shot = rec.get("shot") or b.get("shot")
        elsewhere = [j for j, o in enumerate(blocks)
                     if j != i and shot and o.get("shot") == shot]
        reuses.append({
            "block": i,
            "shot": shot,
            "rhythm_role": b.get("rhythm_role"),
            "seconds": round(float(b["end"]) - float(b["start"]), 3),
            "also_in_blocks": elsewhere,
            "adjacent_to_first_use": any(abs(j - i) == 1 for j in elsewhere),
            # Why nothing new could be cut for this block - the reason the
            # material shortage has, in the resolver's own words.
            "reason": rec.get("reason"),
        })
    return {
        "budget": MAX_EMERGENCY_REUSE_PER_VIDEO,
        "used": len(reuses),
        "reuses": reuses,
    }


def emergency_reuse_shortfalls(order, blocks):
    """CF-0137's entry for `rhythm_shortfalls`: this video was short of
    material and covered a block with a picture it had already shown.

    One entry per repeat (there is at most one - `MAX_EMERGENCY_REUSE_PER_
    VIDEO`), not an aggregate like `picture_absent_blocks`, because a single
    line naming the shot and the block is exactly what the signal has to say.

    A shortfall rather than a note on purpose. The block *has* a picture, so
    none of CF-0136's picture kinds fires on it and `rhythm_delivered` is
    untouched - which is right, the cadence was delivered. What fell short is
    the material: the montage showed the same frame twice because there was
    no second frame to show, and `rhythm_delivered_fully` says so.
    """
    order = normalize_order(order)
    rep = emergency_reuse_report(blocks)
    out = []
    for r in rep["reuses"]:
        out.append({
            "kind": "emergency_reuse",
            "rhythm_id": order["rhythm_id"],
            "blocks": [r["block"]] + list(r["also_in_blocks"]),
            "block": r["block"],
            "shot": r["shot"],
            "also_in_blocks": r["also_in_blocks"],
            "seconds": r["seconds"],
            "budget": rep["budget"],
            "used": rep["used"],
            "reason": r["reason"],
            "note": (
                f"block {r['block']} ({r['seconds']:.2f}s) shows shot "
                f"{r['shot']} a second time - the emergency repeat, spent "
                f"because nothing else could fill it ({r['reason']}). Already "
                f"on screen in block(s) {r['also_in_blocks']}. This video "
                f"needs material, not a montage fix: the repeat is the rung "
                f"above the assetless one, and there is no rung under it "
                f"except refusing the plan (CF-0137)"),
        })
    return out


def verify_rhythm(order, blocks, degraded_indices=(), anchor_count=None):
    """What the video actually is, against what it was ordered as.

    Returns (rhythm_delivered, reasons). `rhythm_delivered` is `None` when the
    ordered rhythm is not in the finished video - never the requested id with a
    caveat somewhere else, because the Analyst joins on this field and a video
    that lost its rhythm to degradation would otherwise teach it about a rhythm
    that was never on screen.
    """
    order = normalize_order(order)
    rid = order["rhythm_id"]
    params = order["parameters"]
    degraded = set(degraded_indices)
    c = cadence(blocks)
    reasons = []

    picture_blocks = [b for b in blocks if has_picture(b)]
    if not picture_blocks:
        return None, ["every block lost its picture - no rhythm survives a plan "
                      "with nothing on screen"]

    if rid == "even":
        # even is the absence of a device, so nothing can fail to execute it;
        # it is only lost when there is no montage left at all, handled above.
        return "even", reasons

    if rid == "hold":
        held = [i for i, b in enumerate(blocks) if b.get("rhythm_role") == "hold"]
        want = params["key_frame_hold_seconds"] or DEFAULT_HOLD_SECONDS
        durations = c["durations"]
        if not held:
            reasons.append("no block carries the hold role")
        else:
            i = held[0]
            if i in degraded:
                reasons.append(
                    f"the held key frame (block {i}) was degraded - a frame nobody "
                    f"is holding any more is not a hold")
            if durations[i] < min(want, HOLD_MIN_SECONDS):
                reasons.append(
                    f"the held block runs {durations[i]:.2f}s, under the "
                    f"{min(want, HOLD_MIN_SECONDS):.2f}s a hold has to dwell for")
            if durations[i] < max(durations):
                reasons.append(
                    f"the held block is not the longest one ({durations[i]:.2f}s "
                    f"against {max(durations):.2f}s) - whatever this video holds "
                    f"on, it is not the frame that was chosen")
        if anchor_count and c["block_count"] >= anchor_count:
            reasons.append(
                f"{c['block_count']} blocks against {anchor_count} anchors - this "
                f"rhythm is defined as deliberately fewer blocks than anchors")
        return (None if reasons else "hold"), reasons

    if rid == "staccato":
        cap = params["key_frame_hold_seconds"] or DEFAULT_STACCATO_CAP_SECONDS
        if c["cv"] is not None and c["cv"] > STACCATO_MAX_CV:
            reasons.append(
                f"block lengths scatter (cv {c['cv']:.2f} > {STACCATO_MAX_CV}) - "
                f"staccato's blocks are near-equal by construction")
        if c["longest"] and c["longest"] > cap * 1.25:
            reasons.append(
                f"longest block is {c['longest']:.2f}s against an ordered cap of "
                f"{cap:.2f}s - something is being held")
        return (None if reasons else "staccato"), reasons

    if rid == "alternate":
        rep = alternation_report(blocks)
        if rep["swap_ratio"] is None or rep["swap_ratio"] < ALTERNATE_MIN_SWAP_RATIO:
            reasons.append(
                f"the picture swaps sides on {rep['swap_ratio']} of block "
                f"boundaries, under {ALTERNATE_MIN_SWAP_RATIO} - "
                f"{rep['blocks_without_side']} block(s) have no side at all")
        thin = {k: v for k, v in rep["distinct_shots_per_side"].items()
                if v < ALTERNATE_MIN_DISTINCT_PER_SIDE}
        if len(rep["distinct_shots_per_side"]) < 2:
            reasons.append("only one side has any footage - nothing is alternating")
        elif thin:
            reasons.append(
                f"side(s) {sorted(thin)} draw on fewer than "
                f"{ALTERNATE_MIN_DISTINCT_PER_SIDE} distinct shots - that is the "
                f"same two clips recycled, which is CF-0034's defect, not this "
                f"rhythm")
        if rep["repeated_adjacent_pairs"]:
            reasons.append(
                f"{rep['repeated_adjacent_pairs']} adjacent shot pair(s) recur - "
                f"the A-B-A-B is over the same shots, exactly the stuck repeat "
                f"CF-0034 recorded")
        return (None if reasons else "alternate"), reasons

    return None, [f"no verifier for rhythm {rid!r}"]


# CF-0192: the codes `pattern_shortfalls` entries carry, and with them the one
# code that lands in the plan's `pattern_not_delivered` and in the assignment
# registry. Codes, not sentences: CF-0040's rotation and CF-0049's production
# columns join on this field, and a registry that guards a fiction is worse
# than one that guards nothing (the whole reason `null` was not good enough).
PATTERN_RHYTHM_NOT_AS_ORDERED = "rhythm_not_as_ordered"
PATTERN_FILE_UNREADABLE = "pattern_file_unreadable"
PATTERN_FILE_MISMATCHED = "pattern_file_mismatched"
PATTERN_BLOCK_COUNT_OUTSIDE_BAND = "block_count_outside_band"
PATTERN_HOLD_OUTSIDE_BAND = "hold_outside_band"
# CF-0310: the same envelope, expressed as a pace rather than as a count. A
# separate code because it is a different measurement with a different unit,
# and CF-0040/CF-0049 join on this field - a reader who sees
# `block_rate_outside_band` has to know the number beside it is blocks/min and
# not a count.
PATTERN_BLOCK_RATE_OUTSIDE_BAND = "block_rate_outside_band"
# CF-0314: the pattern file declared a band in a word this module does not
# know. Until this code existed the answer to an unknown `mode` was `continue`
# - the band was not checked, no shortfall was written, and the plan came back
# `pattern_delivered: <id>` on a parameter nobody had measured, which is
# CF-0192's defect arriving from the other side. It is a shortfall and not a
# `raise` because the honest answer is "I do not know this word, so I assert
# nothing", and a judge that dies takes the batch with it.
PATTERN_BAND_MODE_UNREADABLE = "band_mode_unreadable"

# CF-0314: the band modes this module knows, mirroring the root's
# `patterns/validate_patterns.py` (`MODES`, `FLOOR_DRAWN_MODE`). Mirrored and
# not imported for the reason every constant here is - this repo runs from a
# checkout that may not have the factory root beside it - and pinned equal to
# the root's list by tests/test_block_count_envelope.py wherever the root is
# reachable, because two lists that drift is how a new mode goes unread.
#
#   `drawn`       the band is an order, both ends (CF-0039)
#   `emergent`    the band is an observation, both ends - it refuses nothing
#   `floor_drawn` the floor is an order, the ceiling stays an observation
#                 (the user's decision of 2026-09-22, CF-0314)
BAND_MODE_DRAWN = "drawn"
BAND_MODE_EMERGENT = "emergent"
BAND_MODE_FLOOR_DRAWN = "floor_drawn"
KNOWN_BAND_MODES = (BAND_MODE_DRAWN, BAND_MODE_EMERGENT, BAND_MODE_FLOOR_DRAWN)

# The grid a pace is compared on, mirroring the root's
# `validate_patterns.BLOCK_RATE_DECIMALS`. `cadence()` already rounds
# `blocks_per_minute` to it and the bands in `patterns/` are written on it, so
# nothing measured here needs it; it is the defence for a shortfall handed in
# from elsewhere. The case that makes it necessary is real:
# `amc-leawood-films` (12 blocks over 46.79s of them) measures 15.389548 and
# *is* the floor of the frozen corpus - compared at full precision the band
# would refuse the very video it was measured from.
BLOCK_RATE_DECIMALS = 2

# CF-0310: the two shapes the block-count envelope can arrive in, newest first.
# `(parameter key, shortfall code, the cadence() field it is measured on, the
# unit printed after the measured number, the unit printed after the band)`.
# The count's band prints bare ("10 blocks, outside explainer's observed
# envelope 12-33") because that sentence is pinned on a real plan by
# tests/test_openings_and_sides.py; a rate is ambiguous without its unit on
# both halves, so it carries one on both.
#
# The measurement in CF-0310 is why there are two. `explainer`'s envelope
# 12-33 blocks was observed on videos running 40.0-46.8s of blocks; the same
# eight videos ran 15.39-47.88 blocks/min. `outrider-doune-castle`
# (2026-09-21T1541Z) is 28.7s of blocks at 20.91 blocks/min - inside that pace
# and nowhere near the count's floor of 12, because it is a short video, which
# the user's CF-0293 decision of 2026-09-20 explicitly allows. The count band
# fails it for its length. Expressed as a pace the envelope stops carrying the
# corpus's length inside it.
#
# The root's `patterns/*.json` is what decides which shape is in force, and
# this module reads whichever key is there - the rate first, because a file
# carrying both is a root mid-migration and the rate is then the newer claim.
# Until the root file changes, `block_count` is found and nothing here behaves
# differently from before (CF-0310 item 3).
BLOCK_COUNT_PARAMETER_FORMS = (
    ("block_rate_per_minute", PATTERN_BLOCK_RATE_OUTSIDE_BAND,
     "blocks_per_minute", " blocks/min", " blocks/min"),
    ("block_count", PATTERN_BLOCK_COUNT_OUTSIDE_BAND, "block_count",
     " blocks", ""),
)


def block_count_parameter(params):
    """Which shape of the block-count envelope this pattern file carries.

    The entry of `BLOCK_COUNT_PARAMETER_FORMS` whose key is present, or `None`
    when the file declares neither. One function so that the judge, the gate
    and the Researcher's pre-TTS pass (CF-0277 `plan_blocks.py`) cannot end up
    reading different halves of a half-migrated `patterns/` directory.
    """
    params = params or {}
    for form in BLOCK_COUNT_PARAMETER_FORMS:
        if isinstance(params.get(form[0]), dict):
            return form
    return None


def pattern_shortfalls(order, blocks, rhythm_delivered, pattern=None):
    """Every way this video failed to be the pattern it was assigned.

    CF-0192 built this out of verify_pattern()'s body so that there is one copy
    of the rule and two shapes of the answer: a list of machine-readable
    entries here, and the id-or-None verdict in verify_pattern(), which now
    calls this. One entry per offending band, each carrying `code` (one of the
    PATTERN_* constants above), the measured number, the band and its `mode` -
    the numbers the decision is made on, not a sentence to re-parse. Symmetric
    with CF-0057's `rhythm_shortfalls`, deliberately: the two halves of the
    record answer two different questions and each now has its own list.

    What CF-0192 changed about the judgement itself
    -----------------------------------------------
    Before, only `drawn` parameters were checked, on CF-0039's reasoning that
    an `emergent` range is an observation and failing a video against an
    observation would turn it into an order. That reasoning is intact and so
    is the consequence it was protecting: nothing here refuses a plan, sets an
    exit code or changes what is built.

    What it did not foresee is the other way to be wrong. `explainer`'s two
    bands are both `emergent`, so on `explainer` this function used to check
    *nothing*, and the plan came back `pattern_delivered: "explainer"` with an
    empty deviation list - an assertion that the pattern shipped, made without
    a single measurement behind it. On the 2026-09-09 `coach-hale` plan that
    assertion stood over 3 blocks against an observed 12-33 and a 20.50s hold
    against an observed 2.5-8.0: outside the envelope by 4x, signed as
    delivered. Measured over every plan on disk, `pattern_delivered` was
    non-null on 4 and wrong on all 4.

    So an emergent band still orders nothing, and it now disqualifies the
    *claim*: declining to assert what was never verified is not the same as
    failing a video against an observation. The entry records `mode:
    "emergent"` so a reader can always tell the two apart, and
    `patterns/explainer.json` is untouched - the envelope stays a note about
    what was observed, which is what CF-0039 made it.

    What CF-0314 changed
    --------------------
    Two things, and the second is the reason the first is safe. A band may now
    be `floor_drawn` - floor ordered, ceiling observed (the user's decision of
    2026-09-22) - and the note names the end that was broken, because on that
    mode the two ends are different kinds of statement. And an unknown `mode`
    is no longer a `continue`: it writes PATTERN_BAND_MODE_UNREADABLE. Without
    that, the day the root invented the third word this function stopped
    measuring `explainer`'s pace altogether and the plan came back
    `pattern_delivered: "explainer"` with nothing behind it - CF-0192's defect,
    reached by adding a word rather than by leaving a band emergent.

    `pattern` is the pattern file's contents when it could be read; without it
    the envelope cannot be checked and that is said, not assumed away.
    """
    order = normalize_order(order)
    pid = order["pattern_id"]
    out = []
    if rhythm_delivered != order["rhythm_id"]:
        out.append({
            "kind": "pattern_shortfall",
            "code": PATTERN_RHYTHM_NOT_AS_ORDERED,
            "pattern_id": pid,
            "rhythm_requested": order["rhythm_id"],
            "rhythm_delivered": rhythm_delivered,
            "note": (f"rhythm delivered as {rhythm_delivered!r}, not the "
                     f"ordered {order['rhythm_id']!r}"),
        })
    c = cadence(blocks)
    if pattern is None:
        out.append({
            "kind": "pattern_shortfall",
            "code": PATTERN_FILE_UNREADABLE,
            "pattern_id": pid,
            "note": (f"patterns/{pid}.json was not readable from here - the "
                     f"cadence envelope could not be checked"),
        })
        return out
    if pattern.get("pattern_id") != pid:
        out.append({
            "kind": "pattern_shortfall",
            "code": PATTERN_FILE_MISMATCHED,
            "pattern_id": pid,
            "pattern_file_id": pattern.get("pattern_id"),
            "note": f"pattern file is {pattern.get('pattern_id')!r}, not {pid!r}",
        })
        return out
    params = pattern.get("parameters", {})
    # `noun` and `suffix` keep each sentence naming which of the two bands it
    # is about ("drawn band" vs "drawn hold band") - that wording is pinned by
    # tests/test_openings_and_sides.py on a real plan, and collapsing the two
    # into one phrase would make the deviation list ambiguous for a reader.
    # CF-0310: the block-count check reads whichever shape the pattern file
    # carries (see BLOCK_COUNT_PARAMETER_FORMS); the hold band has one shape
    # and always has. A file that declares neither block-count key is checked
    # on its hold band alone - the same silence as a band with no `mode`.
    form = block_count_parameter(params)
    checks = [] if form is None else [
        (form[1], form[0], c.get(form[2]), "", form[4], f"{{}}{form[3]}")]
    checks.append((PATTERN_HOLD_OUTSIDE_BAND, "key_frame_hold_seconds",
                   c["longest"], "hold ", "s", "longest block {}s"))
    for code, key, measured, noun, suffix, head_form in checks:
        declared = params.get(key)
        band = declared if isinstance(declared, dict) else {}
        mode = band.get("mode")
        # CF-0314: a parameter that is *there* and unreadable is loud; a
        # parameter that is not there at all is silent, which is the same
        # silence a file carrying neither block-count key gets above. The word
        # is quoted back so the reader can see which repository has to move -
        # this module, or the pattern file.
        if isinstance(declared, dict) and mode not in KNOWN_BAND_MODES:
            out.append({
                "kind": "pattern_shortfall",
                "code": PATTERN_BAND_MODE_UNREADABLE,
                "pattern_id": pid,
                "parameter": key,
                "mode": mode,
                "known_modes": list(KNOWN_BAND_MODES),
                "note": (f"{pid}'s {key} band declares mode {mode!r}, which "
                         f"this editor does not know "
                         f"({', '.join(KNOWN_BAND_MODES)}) - the band was not "
                         f"checked and the pattern is not claimed"),
            })
            continue
        if mode is None or measured is None:
            continue
        # CF-0303: seconds are compared at the composition's frame grid,
        # `block_count` is a count of blocks and has no grid - the tolerance is
        # the hold band's alone.
        over = (over_band_top(measured, band["max"])
                if key == "key_frame_hold_seconds" else measured > band["max"])
        under = measured < band["min"]
        if not under and not over:
            continue
        # "band" when it was ordered, "envelope" when it was only observed -
        # the note has to read as what it is, because the whole defect this
        # closes was a record that read as more than it had measured. CF-0314
        # adds the third case, where the two ends are not the same thing: the
        # sentence names the end that was broken and what that end is, because
        # its reader is deciding whether this is a refusal or a note, and
        # "outside the band 15.39-47.88" does not tell him.
        head = head_form.format(measured)
        if mode == BAND_MODE_FLOOR_DRAWN:
            note = (f"{head}, under {pid}'s ordered {noun}floor "
                    f"{band['min']}{suffix} (ceiling {band['max']} observed)"
                    if under else
                    f"{head}, over {pid}'s observed {noun}ceiling "
                    f"{band['max']}{suffix} (floor {band['min']} ordered)")
        else:
            word = (f"drawn {noun}band" if mode == BAND_MODE_DRAWN
                    else f"observed {noun}envelope")
            note = (f"{head}, outside {pid}'s {word} "
                    f"{band['min']}-{band['max']}{suffix}")
        out.append({
            "kind": "pattern_shortfall",
            "code": code,
            "pattern_id": pid,
            "parameter": key,
            "mode": mode,
            "measured": measured,
            "band_min": band["min"],
            "band_max": band["max"],
            "outside_by": round(
                (band["min"] - measured) if under
                else (measured - band["max"]), 3),
            "note": note,
        })
    return out


def verify_pattern(order, blocks, rhythm_delivered, pattern=None):
    """Whether the pattern, not just its rhythm, is what shipped.

    A pattern is its cadence band as much as its rhythm (CF-0039's
    test_cadence_bands_are_distinguishable): a `moment-breakdown` ordered at 6
    blocks with a 6s hold that comes back as 21 short blocks is not a
    moment-breakdown, whatever the rhythm field says.

    The judgement lives in pattern_shortfalls() (CF-0192) and this is its
    id-or-None face, kept because every caller and the Analyst's join want that
    one value: the pattern id when nothing fell short, `None` when something
    did - and then the plan carries the *code* beside it rather than a bare
    `null`. `deviations` is the human half, the sentences that go into
    `rhythm.deviations`.

    CF-0314 splits one hair here: a shortfall that *unsays* the claim from one
    that stands beside it as an observation - see shortfall_denies_delivery().
    `deviations` still carries every note, including the observation's: the
    sentence is true either way and the reader of `rhythm.deviations` wants it.
    """
    short = pattern_shortfalls(order, blocks, rhythm_delivered, pattern)
    pid = normalize_order(order)["pattern_id"]
    return (None if delivery_denying_shortfalls(short) else pid), \
        [s["note"] for s in short]


def shortfall_denies_delivery(shortfall):
    """Whether this shortfall takes the pattern's name off the plan.

    True for every shortfall there has ever been - CF-0192's rule, unchanged:
    a video outside a band, ordered or observed, does not get to be signed as
    that pattern, because the claim would be made without the measurement
    backing it.

    CF-0314 carves out exactly one case, and the carve-out is as narrow as it
    can be written: `mode == "floor_drawn"`, the *rate* parameter, and the
    measurement *over the ceiling*. On that mode the ceiling is not an order -
    the user's decision of 2026-09-22 says a video cut faster than the seven
    measured ones is not a defect - so nulling `pattern_delivered` there would
    report "pattern not delivered" about a video nobody has a complaint about.
    The measurement exists and is recorded as a shortfall (`pattern_delivered_
    fully: false` beside `pattern_delivered: <id>`, the same split CF-0057
    made for the rhythm); what is not made is a verdict the decision does not
    support. Everything else - the floor of the same band, the hold band, any
    `emergent` or `drawn` band - keeps CF-0192's behaviour exactly.

    Measured before it was written: over the ceiling is a case that has never
    occurred. Across the 21 plans on disk the fastest is 47.88 blocks/min,
    `coyote-vs-acme` 2026-08-30, and it is the video the ceiling was measured
    *from*. So this changes no record that exists; it removes a false signal
    from the ones that will.
    """
    s = shortfall or {}
    if (s.get("code") == PATTERN_BLOCK_RATE_OUTSIDE_BAND
            and s.get("mode") == BAND_MODE_FLOOR_DRAWN):
        measured, top = s.get("measured"), s.get("band_max")
        if (measured is not None and top is not None
                and round(float(measured), BLOCK_RATE_DECIMALS)
                > round(float(top), BLOCK_RATE_DECIMALS)):
            return False
    return True


def delivery_denying_shortfalls(shortfalls):
    """The sub-list of `pattern_shortfalls()` that unsays the pattern.

    One place, because three readers ask the question - verify_pattern(),
    pattern_not_delivered_code() and build_render_plan.py's `pattern_delivered`
    - and a fourth answer would be the CF-0003 failure.
    """
    return [s for s in shortfalls or [] if shortfall_denies_delivery(s)]


def cadence_band_refuses(shortfall):
    """Whether a block-count shortfall is over the top of a drawn band.

    CF-0447 (the user, 2026-09-30): no stage refuses on this any more. The
    name is kept because the Content Researcher's pre-TTS pass reads it by
    name (`plan_blocks.py` -> `block_band.refuses`, which its cadence gate
    turns into the same price) - what a True means now is "priced
    `score.block_band_exceeded`" (block_band_findings() below), 2 a block
    over the top, cap 10. The rest of this docstring is why the answer is
    True exactly where it is; that reasoning is what the price is charged on.

    CF-0310's rule, in the one place both stages that need it can read: the
    Editor's `build_render_plan.cadence_band_break()` and the Content
    Researcher's pre-TTS pass (`plan_blocks.py`, CF-0277), which has to reach
    the same answer one wav earlier or the refusal moves stages instead of
    disappearing. Two copies of this predicate would be the CF-0003 failure.

    Three conditions, and each one is a decision with a measurement behind it:

      * the shortfall is about the block-count parameter, in either of its
        shapes (`BLOCK_COUNT_PARAMETER_FORMS`);
      * the band is `drawn`. An `emergent` envelope records what past videos
        did and never fails one - CF-0039, kept by CF-0192, CF-0270 and
        CF-0303;
      * and either the band is a *rate*, or the measurement is over the band's
        top. A count floor is a length requirement written in blocks - a short
        video is under it however it is cut - and refusing on one repeats the
        defect CF-0310 was filed about. A rate has the length divided out, so
        both of its ends are statements about the cutting.

    CF-0314's third mode, `floor_drawn` - floor ordered, ceiling observed:

      * CF-0433 (grill 2026-09-29): a rate under the floor - `drawn` or
        `floor_drawn` - no longer refuses at all. It is the price
        `score.pace_below_floor` (pace_findings() below), and the plan is
        refused only when the video's score falls under N. The bullet that
        follows is the history of that floor, kept for why it exists;
      * rate, under the floor -> refuse (before CF-0433). The length is divided out, so the
        floor is a statement about the cutting, and the user's decision of
        2026-09-22 made exactly that end the order: below 15.39 blocks/min an
        `explainer` is a slide show (`lf-2026-09-09-006`, 3 blocks over
        40.4s, 4.46 blocks/min, which shipped);
      * rate, over the ceiling -> False. The ceiling is not an order and fast
        cutting is not a defect - the same decision, its other half;
      * count, either end -> False. A count floor is the length requirement
        CF-0310 was filed about, and reading "a floor is a floor" into the new
        mode would bring length-dependence back through it. No pattern is
        declared that way today; the schema permits it, so the answer is
        written down rather than left to be discovered.

    Rounding: the comparison is made at BLOCK_RATE_DECIMALS, the grid
    `cadence()` already rounds to and the grid `patterns/` is written on. It
    matters on exactly one number and that number is the floor itself -
    `amc-leawood-films` is 15.389548 blocks/min and *is* where 15.39 came
    from, so a full-precision `<` would refuse the video the band was measured
    from.
    """
    s = shortfall or {}
    code, mode = s.get("code"), s.get("mode")
    if code not in (PATTERN_BLOCK_COUNT_OUTSIDE_BAND,
                    PATTERN_BLOCK_RATE_OUTSIDE_BAND):
        return False
    if pace_floor_deficit(s) is not None:
        # CF-0433: a pace under the floor is a price, not a refusal - see
        # pace_findings() below. The pattern is a target, not a floor.
        return False
    measured = s.get("measured")
    if mode == BAND_MODE_DRAWN:
        if code == PATTERN_BLOCK_RATE_OUTSIDE_BAND:
            return True
        top = s.get("band_max")
        return measured is not None and top is not None and measured > top
    return False


# --------------------------------------------------------------------------
# CF-0433: the pace floor and the hold band as prices (the score model of
# CF-0432, shared/score/score.py; prices in shared/gate-prices.json).
#
# The grill of 2026-09-29 ("делать из того, что дают"): the pattern is a
# target, not a floor. Before it a rate under `explainer`'s 15.39 blocks/min
# and a block held one frame past the hold band's top both refused the plan
# (`pattern_ceiling`), and the repeat of `example-film/2026-09-28T1126Z` lost
# four topics that way - vanguards-endgame-encore at 9.64 and backrooms at 7.18
# blocks/min, primetime's block 13 at 0.25 s over the band, a 12.3 s block
# under a 3.5 s band. Each is now a finding that costs points:
#
#   score.pace_below_floor    -2 per started block/min under the floor, cap -12
#   score.hold_band_exceeded  -2 per block over the band's top, cap -10
#
# A long plan still has to move: a picture that stops while the voice goes on
# is `score.frozen_block` (-20, x2 in the hook), measured on the render by
# qc_render, not here. What stayed a refusal in cadence_band_refuses() was
# a drawn band's *top* broken (more blocks, or a faster rate, than the
# pattern allows) - until CF-0447 (the user, 2026-09-30), which priced it too:
#
#   score.block_band_exceeded -2 per block over the band's top, cap -10
#
# (primetime of 1126Z, 25 blocks against list's 12-24, pays -2; Famine Trials,
# 42, pays the cap). A score under the threshold N is the one refusal left of
# the band, and build_render_plan.py decides it on the sum.
# --------------------------------------------------------------------------

SCORE_PACE_BELOW_FLOOR = "score.pace_below_floor"
SCORE_HOLD_BAND_EXCEEDED = "score.hold_band_exceeded"
SCORE_BLOCK_BAND_EXCEEDED = "score.block_band_exceeded"  # CF-0447
SCORE_TAIL_OVER_BAND_TOP = "score.tail_over_band_top"  # CF-0472 / CF-0490


def pace_floor_deficit(shortfall):
    """Blocks/min under the floor of a rate band (drawn or floor_drawn), or
    None when the shortfall is not that. Compared on the BLOCK_RATE_DECIMALS
    grid, like the refusal it replaces (15.389548 is not under 15.39)."""
    s = shortfall or {}
    if (s.get("code") != PATTERN_BLOCK_RATE_OUTSIDE_BAND
            or s.get("mode") not in (BAND_MODE_DRAWN, BAND_MODE_FLOOR_DRAWN)):
        return None
    measured, floor = s.get("measured"), s.get("band_min")
    if measured is None or floor is None:
        return None
    gap = round(round(float(floor), BLOCK_RATE_DECIMALS)
                - round(float(measured), BLOCK_RATE_DECIMALS), BLOCK_RATE_DECIMALS)
    return gap if gap > 0 else None


def _score_finding(rule, where, units, hook, note):
    # score.finding()'s shape (shared/score/score.py), built here so that this
    # module - which the Content Researcher loads by path - needs no root.
    return {"rule": rule, "where": dict(where), "units": units, "hook": bool(hook),
            "source": "metric", "note": note}


def pace_findings(pattern_short):
    """`score.pace_below_floor` for a rate under its floor: one finding whose
    `units` is every started block/min missing (5.75 short -> 6 units)."""
    out = []
    for s in pattern_short or []:
        gap = pace_floor_deficit(s)
        if gap is None:
            continue
        units = int(math.ceil(gap - 1e-9))
        out.append(_score_finding(
            SCORE_PACE_BELOW_FLOOR, {}, units, False,
            f"{s.get('measured')} blocks/min under {s.get('pattern_id')}'s floor "
            f"{s.get('band_min')}: {gap} short, {units} started block(s)/min"))
    return out


def block_band_blocks_over(shortfall, block_count=None):
    """CF-0447: the blocks over a drawn band's top - the units of
    `score.block_band_exceeded` - or None when cadence_band_refuses() does not
    say the shortfall is over that top. A count band: the measurement less the
    top. A rate band: the blocks less as many as the top allows over the span
    the rate was measured on (`block_count / measured` minutes), rounded up -
    the Researcher's `check_anchor_cadence.blocks_over()` counts the same way.
    At least 1: the reading is over."""
    s = shortfall or {}
    if not cadence_band_refuses(s):
        return None
    measured, top = s.get("measured"), s.get("band_max")
    if measured is None or top is None:
        return 1
    if s.get("code") == PATTERN_BLOCK_COUNT_OUTSIDE_BAND:
        return max(1, int(math.ceil(float(measured) - float(top) - 1e-9)))
    if not block_count or not float(measured):
        return 1
    allowed = float(top) * float(block_count) / float(measured)
    return max(1, int(math.ceil(float(block_count) - allowed - 1e-9)))


def block_band_findings(pattern_short, block_count=None):
    """`score.block_band_exceeded` for a drawn block band's top broken (the
    user's decision of 2026-09-30, CF-0447): ONE finding per video - the band
    is the video's, not a block's - whose `units` are the blocks over the top
    (block_band_blocks_over()). The price table caps it at 10. `block_count`
    is the plan's blocks, needed only for a band stated as a rate."""
    for s in pattern_short or []:
        over = block_band_blocks_over(s, block_count)
        if over is None:
            continue
        unit = (" blocks/min" if s.get("code") == PATTERN_BLOCK_RATE_OUTSIDE_BAND
                else " blocks")
        return [_score_finding(
            SCORE_BLOCK_BAND_EXCEEDED, {"pattern": s.get("pattern_id")}, over, False,
            f"{s.get('measured')}{unit} against {s.get('pattern_id')}'s drawn band "
            f"{s.get('band_min')}-{s.get('band_max')}{unit}, {over} block(s) over "
            f"the top")]
    return []


# CF-0453: a block shorter than MIN_ANCHOR_GAP_SECONDS - the resolver's "anchor
# sits N s before the next one - too tight to read" - is a price, not a
# refusal. It used to fall into plan_check's `absent` (a picture that is not
# there) by default and killed Primetime and AHS (2026-09-30T1248Z) on blocks
# that had their picture. The span measured is a rhythm segment's, which the
# pattern's hold cuts (list/hold 1.1s, staccato under 1.92s), so no anchor edit
# moves it - the three rounds of 6b chased it from pair to pair.
#
# The rule is NOT in the root's price table yet (CF-0320: the user signs
# prices). Until it is, block_too_short_findings() is left out of the score
# (the caller asks _score.has_rule) and the plan says what it would cost - the
# PROPOSED numbers below, what the report offers for signing.
SCORE_BLOCK_TOO_SHORT = "score.block_too_short"
BLOCK_TOO_SHORT_PRICE = 1       # proposed: per block
BLOCK_TOO_SHORT_CAP = 5         # proposed: cap per video

_TOO_TIGHT_WORDS = "too tight to read"


def too_tight_record(u):
    """`{"t", "seconds", "min_gap", "segment"}` when an `unresolved_anchors`
    record is the too-tight note (CF-0453), else None. A storyboard from
    before CF-0453 carries only the words - the seconds are read back off
    them, `t` is then None. Pure."""
    if not isinstance(u, dict):
        return None
    rec = u.get("too_tight")
    if isinstance(rec, dict):
        return {"t": rec.get("t"), "seconds": rec.get("seconds"),
                "min_gap": rec.get("min_gap", MIN_ANCHOR_GAP_SECONDS),
                "segment": rec.get("segment")}
    reason = u.get("reason") or ""
    if _TOO_TIGHT_WORDS not in reason:
        return None
    import re
    m = re.search(r"sits (\d+(?:\.\d+)?)s before", reason)
    return {"t": None, "seconds": float(m.group(1)) if m else None,
            "min_gap": MIN_ANCHOR_GAP_SECONDS, "segment": None}


def block_too_short_findings(story):
    """`score.block_too_short`, one per too-tight note on the storyboard (one
    note is one block the resolver built short). `units` 1 each; the table's
    cap, once it carries the rule, bounds the video. Pure."""
    out = []
    for u in (story or {}).get("unresolved_anchors") or []:
        rec = too_tight_record(u)
        if rec is None:
            continue
        t0, sec = rec["t"], rec["seconds"]
        where = {"phrase": (u.get("phrase") or "")[:80]}
        if rec.get("segment") is not None:
            where["segment"] = rec["segment"]
        if t0 is not None:
            where["t"] = round(float(t0), 2)
        out.append(_score_finding(
            SCORE_BLOCK_TOO_SHORT, where, 1, t0 is not None and float(t0) < 5.0,
            f"block of {sec}s, under the {rec['min_gap']}s a picture needs to "
            f"read - built and shown (CF-0453)"))
    return out


def hold_band_findings(blocks, pattern):
    """`score.hold_band_exceeded`, one per block held over the top of a
    *drawn* hold band (hold_band(); an emergent envelope orders nothing -
    CF-0039), compared by over_band_top() like every other reader of the top.
    `blocks` carry `start`/`end` (a plan) or `_start`/`_end` (a storyboard)."""
    band = hold_band(pattern)
    if not band:
        return []
    top = float(band["max"])
    out = []
    for i, b in enumerate(blocks or []):
        t0 = b.get("start", b.get("_start"))
        t1 = b.get("end", b.get("_end"))
        if t0 is None or t1 is None:
            continue
        dur = round(float(t1) - float(t0), 3)
        if not over_band_top(dur, top):
            continue
        out.append(_score_finding(
            SCORE_HOLD_BAND_EXCEEDED, {"block": i, "t": round(float(t0), 2)}, 1,
            float(t0) < 5.0,
            f"block {i} held {dur}s, {round(dur - top, 3)}s over "
            f"{(pattern or {}).get('pattern_id')}'s hold band top {top}s"))
    return out



def held_frame_seconds(block):
    """The longest HELD picture of one block, in seconds, or None when the
    block holds none - the root's `held_frame_durations()` (CF-0488) per
    block: a cut of a sequence that is a `still` or carries `held_frame`
    stands for its own `seconds`; a whole block that is a `still` or a
    `held_frame` stands for its length (`start`/`end`, or a storyboard's
    `_start`/`_end`). A moving clip is not a hold."""
    a = (block or {}).get("asset") or {}
    cuts = a.get("cuts")
    if cuts:
        held = [float(c.get("seconds") or 0.0) for c in cuts
                if c.get("kind") == "still" or c.get("held_frame")]
        return max(held) if held else None
    if a.get("kind") == "still" or a.get("held_frame"):
        t0 = block.get("start", block.get("_start"))
        t1 = block.get("end", block.get("_end"))
        if t0 is None or t1 is None:
            return None
        return round(float(t1) - float(t0), 3)
    return None


def held_frame_over_band_findings(blocks, pattern):
    """CF-0859: `score.hold_band_exceeded` for a HELD picture past the top of
    an *observed* (not drawn) hold band - one finding per block, units 1.

    hold_band_findings() charges a drawn band only (CF-0039), and explainer is
    the one pattern whose band is emergent, so a sharp held frame past its
    8.0 s top was a way out of the baseline envelope with no price that always
    fires: vanguards-doomsday of example-film/2026-10-24T0840Z held a sharp
    still 10.10 s in block 2, under half the video stretched (46.72 %), sharp
    (0.70 over the 0.53 floor) and short of the 12 s held-moving-face
    tolerance - the three conditional prices of CF-0488 all stayed silent and
    the video scored exactly N. The cut is not reshaped (an observation still
    orders nothing); the hold past the observed top is charged.

    On a drawn band nothing: hold_band_findings() already charges the whole
    block there, and a second price would pay the same way out twice. Compared
    by over_band_top(), like every other reader of the top."""
    band = (((pattern or {}).get("parameters") or {})
            .get("key_frame_hold_seconds") or {})
    if band.get("mode") == "drawn" or band.get("max") is None:
        return []
    top = float(band["max"])
    out = []
    for i, b in enumerate(blocks or []):
        held = held_frame_seconds(b)
        if held is None or not over_band_top(held, top):
            continue
        t0 = float(b.get("start", b.get("_start")) or 0.0)
        out.append(_score_finding(
            SCORE_HOLD_BAND_EXCEEDED, {"block": i, "t": round(t0, 2)}, 1,
            t0 < 5.0,
            f"block {i} holds one picture {round(held, 3)}s, "
            f"{round(held - top, 3)}s over {(pattern or {}).get('pattern_id')}'s "
            f"observed hold top {top}s (CF-0859)"))
    return out

def tail_over_band_top_findings(blocks, pattern, words):
    """`score.tail_over_band_top` (CF-0472, signed by the user 2026-10-02,
    CF-0490): the last block that still carries speech - the last one that
    starts before the last word ends - held over the top of a *drawn* hold
    band (hold_band(); no band, e.g. `explainer`, is not measured). One
    finding, units = seconds over the top (the table prices per second, cap
    66): everyday-sorcery-2 1034Z, rejected for a 13.52 s last block against
    list's 2.5 s top, is 11.02 s over.

    It adds to `score.hold_band_exceeded` on the same block rather than
    replacing it: that rule is the flat price of *a* block over the band
    (-2, any block, any length over), this one is the length of the spoken
    tail the viewer waits through - the defect the user rejects for, which
    the flat -2 never weighed. The signed calibration (a clean video 34 at
    11.02 s over) is this rule alone; the -2 rides on top.

    `blocks` carry `start`/`end` (a plan) or `_start`/`_end` (a storyboard);
    `words` carry `end` (the alignment)."""
    band = hold_band(pattern)
    if not band:
        return []
    ends = [float(w["end"]) for w in words or []
            if isinstance(w, dict) and w.get("end") is not None]
    if not ends:
        return []
    last_word = max(ends)
    top = float(band["max"])
    tail = None
    for i, b in enumerate(blocks or []):
        t0 = b.get("start", b.get("_start"))
        t1 = b.get("end", b.get("_end"))
        if t0 is None or t1 is None:
            continue
        if float(t0) < last_word:
            tail = (i, float(t0), float(t1))
    if tail is None:
        return []
    i, t0, t1 = tail
    dur = round(t1 - t0, 3)
    if not over_band_top(dur, top):
        return []
    over = round(dur - top, 2)
    return [_score_finding(
        SCORE_TAIL_OVER_BAND_TOP, {"block": i, "t": round(t0, 2)}, over, t0 < 5.0,
        f"last speech block {i} held {dur}s, {over}s over "
        f"{(pattern or {}).get('pattern_id')}'s hold band top {top}s "
        f"(the last word ends at {round(last_word, 2)}s) (CF-0472)")]

def pattern_not_delivered_code(shortfalls):
    """The one code that goes in the plan and in the assignment registry.

    CF-0192 item 4: when the pattern cannot be delivered, the record says why
    in a word a machine can join on, and `null` stops meaning both "delivered
    nothing to say" and "not delivered, reason unrecorded". `None` here means
    the pattern *was* delivered - the only case where the field is empty, and
    now the only one.

    First entry wins when there are several, and the order of
    pattern_shortfalls() is deliberate: the rhythm and the two unreadable-file
    cases come before the bands, because a cadence measured against a file that
    is missing or is some other pattern is not a cadence verdict at all. The
    whole list is in `pattern_shortfalls` for anyone who needs more than one.

    CF-0314: the first *delivery-denying* entry, because one shortfall no
    longer unsays the claim (shortfall_denies_delivery()). A plan whose only
    shortfall is a pace over a `floor_drawn` ceiling is delivered, and this
    field is empty for the one reason it is ever empty.
    """
    denying = delivery_denying_shortfalls(shortfalls)
    return denying[0]["code"] if denying else None


def rhythm_shortfalls(order, blocks):
    """CF-0057: what the delivered rhythm is short of while still being itself.

    `verify_rhythm()` answers one question - is the ordered rhythm in this
    video, yes or no - and it answers it with the whole verdict, because the
    Analyst joins on `rhythm_delivered` and a rhythm carried there with a
    caveat somewhere else is a rhythm nobody can trust. That is the right shape
    for "the alternation has a hole in it". It is the wrong shape for what
    CF-0050 produced on `wren-hollow-lockhart`: the picture crossed the axis
    at every boundary the script crossed it (swap_ratio 1.0, the alternation is
    exactly what was written) and then stood still for 15.17s inside one of
    those crossings, on an ordered hold of 3.0s. Saying `rhythm_delivered:
    null` there would teach the Analyst that `alternate` failed, which is
    false; saying `alternate` and nothing else says the rhythm was fully
    executed, which is also false.

    So this is the second field, on the model of CF-0041's
    `pattern_requested` / `pattern_delivered`: the rhythm is what it says it
    is, *and* here is the machine-readable list of what it did not manage. One
    entry per offending run, with the numbers the decision will be made on -
    not a sentence for a human to re-parse.

    Five shortfall kinds. `opening_static_held` (CF-0075) is the `side_by_side`
    opening standing past OPENING_MAX_STATIC_SECONDS or handing part of its run
    back - see opening_shortfalls(). `long_side_run_held` is a run of one
    declared side, longer than the ordered `key_frame_hold_seconds`, delivered
    as a single frame that never changes. A run that stays that long on one
    side while the picture keeps moving is not this defect (it is a long shot,
    and the exit criterion says so); a run that freezes for less than the
    ordered hold is the hold working as ordered.

    `picture_absent_run` and `picture_absent_blocks` (CF-0136) are the other
    half of the same idea and were missing until CF-0123 found the hole: both
    kinds above are about a picture that is present and standing still, so a
    plan whose blocks have no picture at all produced no entry, and
    `rhythm_delivered_fully` therefore came back True on a video that was 25
    stubs out of 30. See picture_absent_shortfalls() for what each of the two
    counts and why the second one has no threshold. Those two fire under every
    rhythm; the two above are about `alternate` and its opening.

    `emergency_reuse` (CF-0137) is the fifth and the odd one out: its block
    *has* a picture, so none of the four above sees anything wrong with it.
    What fell short is the material - the block was filled with a shot the
    video had already shown, because the alternative was the assetless rung
    CF-0123 refused. See emergency_reuse_shortfalls().

    Deliberately *not* decided here: whether a long run should be prevented in
    the first place, and if so whether by measuring swaps over runs instead of
    boundaries or by letting a run carry more than one shot. Both of those
    change what `alternate` means and neither is this function's to choose -
    CF-0057 leaves them open and this only makes the case countable.
    """
    order = normalize_order(order)
    # CF-0075: the opening's shortfall is about the opening, not the rhythm
    # it sits in, so it is recorded whatever rhythm was ordered.
    out = opening_shortfalls(blocks)
    if order["rhythm_id"] == "alternate":
        out.extend(_long_side_run_shortfalls(order, blocks))
    # CF-0136: the picture that never arrived. Recorded last, after the kinds
    # that were here first, so the entries a reader has pinned against a real
    # plan keep their positions - and under every rhythm, because a block with
    # no picture is a block with no picture whatever cadence it was cut to.
    out.extend(picture_absent_shortfalls(order, blocks))
    # CF-0137: and the picture that arrived only because it was shown twice.
    # Last for the same reason as the pair above, and under every rhythm: a
    # video short of material is short of material whatever it was cut to.
    out.extend(emergency_reuse_shortfalls(order, blocks))
    return out


def _long_side_run_shortfalls(order, blocks):
    """CF-0057's `long_side_run_held` entries - see rhythm_shortfalls()."""
    out = []
    report = side_run_report(blocks, order["parameters"]["key_frame_hold_seconds"])
    want = report["hold_ordered_seconds"]
    for run in report["runs"]:
        if run["side"] not in ("a", "b") or not run["single_held_frame"]:
            continue
        if run["seconds"] <= want:
            continue
        out.append({
            "kind": "long_side_run_held",
            "rhythm_id": "alternate",
            "side": run["side"],
            "blocks": list(run["blocks"]),
            "start": run["start"],
            "end": run["end"],
            "seconds": run["seconds"],
            "hold_ordered_seconds": want,
            "hold_seconds_source": report["hold_seconds_source"],
            "over_by_seconds": round(run["seconds"] - want, 3),
            "shots": list(run["shots"]),
            "note": (
                f"the picture stays on side {run['side']} for {run['seconds']:.2f}s "
                f"(block(s) {run['blocks']}) and never changes - one held frame "
                f"against an ordered hold of {want:.2f}s. The alternation itself is "
                f"intact; what is short is the rhythm inside the run (CF-0057)"),
        })
    return out
