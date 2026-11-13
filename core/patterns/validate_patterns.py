#!/usr/bin/env python3
"""CF-0039: the schema of the pattern vocabulary, as executable code.

This file *is* the schema. There is no prose copy of it anywhere else on
purpose - CF-0015 rejected the "numbers in JSON, prose in SKILL.md" split for
creating two sources of truth about one entity, and a SCHEMA.md next to a
validator would be the same mistake one level up. To find out what a pattern
file may contain, read `validate_pattern` below; to find out how to write with
a pattern, read that pattern's own `writing_instruction`.

Run it directly to check the vocabulary on disk:

    python3 patterns/validate_patterns.py

Or to check the orders already written into a batch against the narration
they will be read over (CF-0086, see `check_order_fits_voice` below):

    python3 patterns/validate_patterns.py check-orders \\
        pipeline/legacy-film/<batch>/03-content-researcher.json

Or to check that no half of a contrast script's pair is longer than one anchor
and the hold it was ordered under (CF-0119, see `check_contrast_pairs` below):

    python3 patterns/validate_patterns.py check-pairs \\
        pipeline/legacy-film/<batch>/03-content-researcher.json

Consumers: `tests/test_pattern_vocabulary.py` (this repo), the rotation and
distribution guard of CF-0040, and Video Editor's rhythm execution in CF-0041.

--------------------------------------------------------------------------
A pattern file - patterns/<pattern_id>.json, one per pattern
--------------------------------------------------------------------------

Required:

  pattern_id          str, matches the filename stem
  display_name        str, short human name (rotation ledger, chat reports)
  summary             str, one line - what the pattern is
  script_sections     ordered list of the keys the script must emit. Identical
                      across all four patterns today, and required per-pattern
                      anyway: patterns are meant to vary the *writing*, not the
                      contract with the next stage, and a future pattern that
                      breaks that has to say so here where a test can see it.
  allowed_rhythms     non-empty list of rhythm ids from patterns/rhythms.json.
                      The tag is the (pattern, rhythm) pair; a rhythm outside
                      this list is never assigned to this pattern.
  writing_instruction non-empty list of paragraphs - the whole prose of how to
                      write with this pattern. Lives here in full, per CF-0015.
  parameters          exactly the four parameters of CF-0015 (see below)
  original_contribution
                      {status, blocked_by, text}. status "pending" means the
                      content is owed by the task named in blocked_by and text
                      must be empty; status "defined" means text carries it and
                      blocked_by is gone. Declared empty by CF-0039 on purpose
                      (the field cost nothing then and retrofitting a contract
                      costs a walk over the whole vocabulary) and filled by
                      CF-0063 from the CF-0043 decision. A defined text is this
                      pattern's *own* part of the channel's contribution - the
                      shared thesis lives in the channel's stance file
                      (channels/<channel>/stance.json) - so the same text on two
                      patterns is rejected at vocabulary level, see
                      `validate_contribution_texts`: a length check alone is
                      satisfied by any stub of forty characters.

Optional:

  baseline            {is_current_form: true, rhythm_id, note} - marks the one
                      pattern that is the form the factory already produces.
                      Exactly one pattern in the vocabulary carries it.
  meme_layer          {allowed: bool, reason}
  proof_layer         {allowed: bool, reason}
  sound_layer         {allowed: bool, reason}
                      A pattern's right to refuse an insert layer at home. All
                      are optional by design: an insert is an orthogonal layer
                      over any pattern (CF-0012, CF-0013), so silence means "no
                      objection" and is a complete, valid pattern. A pattern
                      that does object has to say why - a bare false is a
                      preference, not a rule. Which patterns object is a user
                      decision and neither CF-0039 nor CF-0013 took it.

                      The two fields are one family, listed in
                      LAYER_PERMISSION_FIELDS and checked by one function. The
                      layers themselves - what an insert is, where it may go,
                      what it must record - live in `inserts/` and are the
                      schema of `inserts/validate_inserts.py`, not of this file:
                      a pattern only ever answers whether its own shape of
                      script tolerates the interruption. Whether the *channel*
                      wants the layer at all is a third answer, in the channel
                      config.
  side_length         {max_anchors_per_side, seconds_from,
                       words_per_second_from, note} - CF-0119, and today only
                      on contrast: the band one half of a matched pair may not
                      exceed, expressed as *where its numbers are read from*
                      rather than as numbers. `seconds_from` names one of the
                      four parameters (the drawn value when the script carries
                      one, that parameter's band maximum otherwise) and
                      `words_per_second_from` names the channel key the rate
                      comes from, so the rule moves when the hold band or the
                      measured voice moves. Read by `check_contrast_pairs`.
                      Absent means the pattern has no such rule and a pair
                      check on it raises rather than guessing a default.
  notes               free text

--------------------------------------------------------------------------
The four parameters (CF-0015 Q12)
--------------------------------------------------------------------------

Every parameter declares a `mode`:

  "drawn"     Content Researcher picks a value inside the declared range or
              choice set and writes it into 03-content-researcher.json as an
              order. Video Editor builds the block plan inside that order.
  "emergent"  the pattern does not steer this. Nothing is drawn, the agent
              writes null, and the declared range is a drift envelope for the
              guard and the Analyst - an observation, not an instruction.
  "floor_drawn"
              CF-0314, and only for a band parameter ({min, max}): the two ends
              of the band are not the same kind of statement. The floor is an
              order - under it the pattern is not this pattern and the plan is
              refused - and the ceiling stays an observation, a drift envelope
              like an emergent one. Nothing is drawn: the floor is a boundary,
              not a number to pick, so `draw_order` writes null exactly as it
              does for `emergent` and the order's shape does not change.

The distinction exists because of the baseline pattern. Its block count and
hold length are not decided by anyone today: they fall out of the narration and
the anchors that resolved. Declaring ranges for them as if they were orders
would change behaviour, and the baseline pattern is specifically not allowed to
do that.

The third mode exists because that argument turned out to be true of only one
end of one band. CF-0310 measured explainer's block rate at 15.39-47.88 blocks
a minute and left it emergent, so a plan of 3 blocks over 40.4s - 4.46 a
minute, a slideshow with 13-second frames (lf-2026-09-09-006) - was recorded
as outside the envelope and shipped anyway. The user's decision of 2026-09-22:
below the floor the video is not an explainer and is refused before the render;
above the ceiling it is a fast cut, which is not a defect and orders nothing.
`floor_drawn` is that decision in one word, and it is one word rather than two
sub-objects (`floor: {mode: drawn}`) because three readers have to agree on it
- this schema, the width guard, and Video Editor's rhythm.block_count_parameter
- and a reader that does not know the word has to stop rather than fall through
to a default. A nested shape would let an old reader see `mode` absent, or see
a dict it can still index, and carry on.

  block_count             {mode, min, max}   ints, 2 <= min <= max
    -- or --                                 exactly one of the two; CF-0310
  block_rate_per_minute   {mode, min, max}   blocks per minute of blocks,
                                             numbers, 1.0 <= min <= max
  key_frame_hold_seconds  {mode, min, max}   the longest block in the finished
                                             video, in seconds; 0 < min <= max
  opening_block           {mode, choices}    non-empty, from the
                                             opening_block_kinds enum
  acceleration_to_payoff  {mode, enabled_choices, strength}
                                             enabled_choices non-empty list of
                                             booleans; strength {min,max} in
                                             (0,1] when true is available, and
                                             null when it is not

Feasibility is checked too: a pattern may not order more blocks, or a longer
hold, than a 35-60 second video can physically contain at the observed floor of
0.6 seconds a block.
"""
import json
import math
import random
import re
import sys
import textwrap
from pathlib import Path, PurePosixPath

PATTERNS_DIR = Path(__file__).resolve().parent
RHYTHMS_FILE = PATTERNS_DIR / "rhythms.json"

# Shortest block the pipeline has ever produced (0.60s, 2026-08-30T2329Z /
# the-long-voyage). Used only for the feasibility check below.
MIN_BLOCK_SECONDS = 0.6
# The editorial band a finished video has to land in, as the factory agrees
# it. The numbers live in the channel config (`narration_budget.
# total_seconds_min` / `total_seconds_max`, CF-0158) because the band is the
# channel's; these two are repeated here as the outer limits no channel's band
# may leave, and MAX_TARGET_SECONDS additionally as the ceiling a pattern may
# not physically exceed.
#
# CF-0158: the floor is new. Until it, `MAX_TARGET_SECONDS` was the only
# length boundary anywhere in the repository, and a video coming out at 30
# seconds was caught by nothing at all. The two ends are not treated alike -
# see `judge_video_length()` for what happens at each and why.
MIN_TARGET_SECONDS = 45.0
MAX_TARGET_SECONDS = 60.0
# CF-0293, the user's decision of 2026-09-20 on CF-0283, verbatim: "keep videos
# up to 45 s, hard limit down to 30 s. Everything under 45 s - with a warning
# and counted for later". So there are now TWO floors and they mean different
# things:
#
#   MIN_TARGET_SECONDS       45 s  the band's floor. Under it the video is
#                                  SHORT: it still gets made, it carries a
#                                  warning and it is counted in the run
#                                  summary (that is the "counted for later").
#   HARD_MIN_TARGET_SECONDS  30 s  the hard floor. Under it there is no video
#                                  at all: the plan is refused before the
#                                  render, the same way the 60 s ceiling is.
#
# Like the band, the number that binds is the channel's
# (`narration_budget.total_seconds_hard_min`); this constant is the outer
# limit no channel's hard floor may go below - a channel may be stricter than
# the factory, never looser.
HARD_MIN_TARGET_SECONDS = 30.0

# CF-0310: how many blocks a pattern has, in the two units it can be said in.
# `block_count` is how many there are; `block_rate_per_minute` is how fast they
# come. They are the same statement divided by the length of the video, a
# pattern declares exactly one of them, and which one it declares is a decision
# about what the band is really about:
#
#   a count is a rate times a length, so a band on the count is also a band on
#   the length. That is fine for a `drawn` band - the order says "give this
#   video twelve blocks" and the length is the channel's, fixed - and it is
#   wrong for an `emergent` one, which claims to describe the *form*. CF-0310
#   measured the damage on explainer: a 34-second video cut at 20.9 blocks a
#   minute, squarely inside the form, failed a 12-block floor for being 34
#   seconds long, which CF-0293 permits on purpose; a 64-second slideshow at
#   11.3 blocks a minute, half the pace of anything in the corpus, passed it
#   for being long. The count was grading length under the name of rhythm.
#
# One name, not a renaming: the drawn bands of list/contrast/moment-breakdown
# are orders that `draw_order` pulls a number out of and the capacity gate
# reads, and turning those into rates is a separate decision with its own
# measurement. So both names are legal, exactly one per pattern.
BLOCK_COUNT_KEY = "block_count"
BLOCK_RATE_KEY = "block_rate_per_minute"
BLOCK_PARAMETER_KEYS = (BLOCK_COUNT_KEY, BLOCK_RATE_KEY)

PARAMETER_KEYS = (
    "block_count",
    "key_frame_hold_seconds",
    "opening_block",
    "acceleration_to_payoff",
)
# Every key a pattern file may legally carry under `parameters` - PARAMETER_KEYS
# with the alternative spelling of the first one. The four parameters are still
# four (CF-0015); only the unit of one of them is a choice.
ALLOWED_PARAMETER_KEYS = PARAMETER_KEYS + (BLOCK_RATE_KEY,)
# CF-0314. `floor_drawn` is a band's two ends said separately: the floor is an
# order, the ceiling an observation. Spelled as a constant because three
# repositories compare against the literal.
FLOOR_DRAWN_MODE = "floor_drawn"
# Which modes a parameter may declare depends on what its band is made of. A
# {min, max} parameter can have one end ordered and the other observed;
# `opening_block` and `acceleration_to_payoff` are choice sets with no ends at
# all, and `floor_drawn` on one of them would be a word with no meaning that
# every `mode == "drawn"` branch would then read as "not ordered".
CHOICE_MODES = ("drawn", "emergent")
BAND_MODES = CHOICE_MODES + (FLOOR_DRAWN_MODE,)
MODES = BAND_MODES
# The modes whose band is (wholly or in part) a record of what the pipeline was
# measured doing, and therefore the modes that owe `envelope_evidence` and are
# held to it by the width guard (CF-0195). `floor_drawn` is here for both of
# its ends and for different reasons - see `envelope_width_errors`.
MEASURED_MODES = ("emergent", FLOOR_DRAWN_MODE)


def draws_a_value(cfg):
    """Does this parameter hand Content Researcher a number to pick?

    Only `drawn` does. `emergent` never did, and `floor_drawn` does not either:
    a floor is the edge of what the pattern will accept, not a value inside a
    range, and the rate cannot be drawn before a video length is chosen anyway
    (CF-0310) - which is the whole reason the band is a rate. One predicate so
    that the draw, the hold window and the capacity gate cannot disagree about
    which modes produce a number.
    """
    return isinstance(cfg, dict) and cfg.get("mode") == "drawn"


def block_parameter_key(params):
    """Which of the two block parameters this pattern declares, or None.

    The single place that knows a pattern file can say the same thing in two
    units, mirroring `rhythm.block_count_parameter()` on Video Editor's side
    (CF-0310). Everything that wants the band goes through here rather than
    writing `params["block_count"]`, so that adding the rate cost one function
    instead of a `if "block_count" in ...` in every reader - which is the shape
    that guarantees one of them is missed.
    """
    if not isinstance(params, dict):
        return None
    for key in BLOCK_PARAMETER_KEYS:
        if isinstance(params.get(key), dict):
            return key
    return None


def block_parameter(pattern):
    """(key, band) for the pattern's block parameter, or (None, None)."""
    params = (pattern or {}).get("parameters") or {}
    key = block_parameter_key(params)
    return (key, params[key]) if key else (None, None)


# The cadence parameters, and the only ones an envelope is declared over: how
# many blocks a pattern has and how long its longest hold runs are what a
# viewer can tell apart in the first seconds (CF-0015), which is why they carry
# a band at all. The first parameter appears here under both of its names - a
# pattern declares one of them, and the loops below skip the one it does not.
CADENCE_PARAMETERS = (BLOCK_COUNT_KEY, BLOCK_RATE_KEY, "key_frame_hold_seconds")

# How much wider than the measurement a declared envelope may be. An envelope
# is a drift envelope: it has to leave room for a video that lands a little
# outside the seven that were measured, and it must not be so wide that
# nothing can fall out of it.
#
# These are *slack over a fixed point*, not slack over the live corpus, and
# that distinction is the whole of CF-0195. The guard that existed before
# compared the declared band against the corpus as it stands today - which
# includes whatever regression has just shipped - so a corpus containing a
# 3-block video authorised a 3-block floor, and a corpus containing a 20.5s
# hold would have authorised a 20.5s ceiling. The corpus was granting itself
# the tolerance it needed to be accepted. The fixed point is
# `parameters.<p>.envelope_evidence`: the batches the envelope was declared
# from, named in the pattern file, with the span those batches actually
# shipped. Widening the band now requires either a new batch on disk that
# really produced the wider span, or an edit that the disk contradicts.
ENVELOPE_SLACK_BLOCKS = 2
ENVELOPE_SLACK_SECONDS = 0.5
# CF-0310: the same allowance in the rate's unit - two blocks a minute. Not
# derived from ENVELOPE_SLACK_BLOCKS by arithmetic, because there is none to
# do: two blocks of slack on a count is a different width at every video
# length, which is the whole reason the parameter stopped being a count. This
# is a decision that the pace of a form is pinned to within two blocks a
# minute, and on the explainer envelope (15.39-47.88) that is about 6% of the
# band - tighter in relative terms than the 2-of-12 the count allowed.
ENVELOPE_SLACK_BLOCKS_PER_MINUTE = 2.0

# CF-0310: rates are stored on the same two-decimal grid as every other
# non-integral number in this schema (`draw_order` rounds to it, HOLD_GRID is
# it). A measured rate is a full-precision float - 33 blocks over 41.35s is
# 47.883918... - so a band declared at exactly its own measurement excludes
# the measurement by a rounding error unless the comparison is snapped to the
# grid first. Readers that compare a measured rate against a declared band
# round to this many places; `envelope_width_errors` does not, because both
# sides of that comparison are already on the grid.
BLOCK_RATE_DECIMALS = 2

# Fields of an envelope_evidence block. `declared_by` is the task that measured
# the span; `frozen_by` the task that made the fixed point machine-readable.
ENVELOPE_EVIDENCE_KEYS = ("measured_over_batches", "observed_min", "observed_max",
                          "declared_by", "frozen_by", "note")
CONTRIBUTION_STATUSES = ("pending", "defined")

# A pattern's veto over an insert layer, one optional field per layer. Kept as
# a list rather than as two hand-written branches so that the third layer costs
# a string here instead of a copied block: the layers are defined in `inserts/`
# and tests/test_insert_layers.py checks that every kind described there has
# its field named here.
LAYER_PERMISSION_FIELDS = ("meme_layer", "proof_layer", "sound_layer")

# CF-0086: an order is drawn before TTS runs, so the voice it has to fit does
# not exist yet - only the narration's word count does. The rate turns that
# count into an expected voice length. It is the median of the 7 finished wavs
# this channel has on Kokoro am_puck@1.10 (2026-09-16T2148Z, 2026-09-17T1901Z,
# 2026-09-18T1058Z). CF-0188 measured 3.02 on 2026-09-03T2037Z with the same
# voice and the same method; CF-0261 re-measured it at 3.88 because the rate
# turned out to follow the WRITING as well as the voice - those scripts reached
# the TTS as five or six paragraphs full of ellipses and read a third slower
# than the one paragraph today's do. The numbers it replaces are 3.02 and 3.88.
#
# CF-0279: A SINGLE RATE IS NOT A LENGTH, and this module's use of it is the
# only one left that is allowed to pretend otherwise. Kokoro cuts the text into
# chunks of at most 510 phonemes and every boundary costs its own phrase-final
# lengthening, so the same voice reads between 3.24 and 3.99 words a second
# depending on how many chunks a script falls into - and the 2/3-chunk boundary
# sits inside any usable word range. Against the 7 measured wavs the median
# above is off by up to 5.67 s. What the voice-fit check does with it is still
# sound (it asks whether an order has enough blocks to cover roughly a minute
# of voice, and 5 s does not change that answer); what may NOT be done with it
# is deciding whether a written script fits the channel's 45-60 s band. That
# decision is `narration_budget.narration_estimator` - Kokoro's own duration
# predictor, run per script, residual 0.000 s - and the word budget below is
# derived from the ENVELOPE (`words_per_second_min/max`), never from this
# number times a target length.
#
# CF-0087: the rate is not this module's number. It lives in the channel
# config, `channels/<channel>.json` -> `narration_budget.words_per_second`,
# next to the duration budget it is combined with, so that Content Researcher
# (word budget) and Video Editor (TTS overrun gate) - separate repos that
# cannot import this file - read the same copy. The `_source` string travels
# with every verdict so a reader of the ledger or of 03-content-researcher.json
# can see where the arithmetic came from; tests/test_narration_budget.py pins
# it to the config's own citation.
#
# CF-0633: and it is the CHANNEL's number, so nothing here holds one. Until
# then this module loaded the first channel's budget at import
# (`NARRATION_BUDGET`, `WORDS_PER_SECOND*`) and every loader below defaulted
# to it - a batch of another channel drawn, fitted and judged at example-film's
# rate and band without a word said. Every function that needs a rate, a band
# or a channel block now takes the channel (an id, its config, or its
# `narration_budget` block - see `narration_budget_of()`), and one that is
# given none raises instead of picking one.
ROOT = PATTERNS_DIR.parent
CHANNELS_DIR = ROOT / "channels"
NARRATION_BUDGET_KEY = "narration_budget"
NARRATION_BUDGET_REQUIRED = (
    "total_seconds_min",
    "total_seconds_max",
    # CF-0293: the hard floor, under which the video is not made at all.
    # Required for the same reason the band's two ends are: a channel that
    # names no hard floor is a channel whose videos have no bottom, and this
    # module carries no default to quietly put there. `hard_min_seconds()`
    # still tolerates a budget dict without it (a caller holding an older
    # config in memory degrades to the three CF-0158 verdicts) - what is
    # refused here is a channel config on disk that omits the decision.
    "total_seconds_hard_min",
    "target_total_seconds",
    "words_per_second",
    "words_per_second_source",
    # CF-0279: the ends of the measured envelope. Required and not optional,
    # because the word budget is derived from THEM and a config that carries
    # only a median is a config claiming a precision the voice does not have.
    "words_per_second_min",
    "words_per_second_max",
    "narration_words_min",
    "narration_words_max",
    # CF-0279: how the channel decides whether a written script fits. Required
    # for the same reason: a channel with no estimator has nothing to fall back
    # on but words / rate, which is the defect this key exists to remove.
    "narration_estimator",
)
# CF-0279. The estimator block: the command that turns a script into seconds,
# and the rule for reading its answer. Prose keys (`*_note`) are free.
NARRATION_ESTIMATOR_REQUIRED = (
    "command",
    "decide_on",
    "decide_against",
    "tolerance_seconds",
    "word_range_is",
    "missing_engine_exit_code",
    "missing_engine_action",
)
# CF-0141: what the video closes on comes out of `target_total_seconds`, and
# there are two kinds of channel, so there are two keys for it - but a config
# owes exactly as much as before, one of them.
#
#   `ending_seconds`   - the channel ships its own ending clip
#                        (`channels/<id>/ending.mp4`) and the narration is
#                        budgeted against the file's measured length.
#   `end_card_seconds` - the channel has no such file and closes on the drawn
#                        card, whose length is a per-channel constant.
#
# Both may be present: a channel with a clip still records the card's length
# as the floor it would fall back to, which is the case on example-film
# today. `ending_seconds` wins then, because that is the tail the video
# actually has - see tail_seconds(). Neither present is a config that does not
# say how its videos end, and the word budget below it is then unfounded.
NARRATION_TAIL_KEYS = ("ending_seconds", "end_card_seconds")
# The stored `narration_seconds` is rounded for a human reader (49.83 for
# 55 - 5.167), so it is checked to the hundredth rather than exactly. What has
# to agree to a frame is `ending_seconds` against the file itself, and that
# check belongs to whoever holds the file - agents/video-editor/scripts/
# end_card.py, at plan time.
NARRATION_SECONDS_TOLERANCE = 0.005
# CF-0158: the finished video's band - narration, footage and the tail
# together, everything a viewer sits through. `target_total_seconds` is one
# number inside it; these two are its ends.
TOTAL_BAND_KEYS = ("total_seconds_min", "total_seconds_max")
# CF-0293: the hard floor, one key and deliberately NOT a third member of
# TOTAL_BAND_KEYS - it is not an end of the band, it is the line below the
# band under which there is no video. Everything that reads the band as a pair
# (`total_band()`, `narration_band()`, every plan's `duration.target`) has to
# go on reading exactly two numbers.
TOTAL_HARD_MIN_KEY = "total_seconds_hard_min"
# The narration's band is derived from those two and never stored: it is
# `[total_seconds_min - tail, total_seconds_max - tail]`, the same subtraction
# CF-0141 made for `narration_seconds`, so that the two cannot drift apart
# when the channel's ending clip is replaced. See `narration_band()`.
#
# One word of the channel's own rate is the slack allowed when the word band
# is checked against the derived seconds: `narration_words_min/max` are whole
# numbers of words and cannot land on the second exactly.
WORD_BAND_SLACK_WORDS = 1.0


class ChannelRequired(TypeError):
    """CF-0633: a function that reads a channel's numbers was given no channel.

    Raised instead of picking one: there is no channel this module may assume
    (shared/channel_data.py's contract, CF-0561)."""


def _require_channel(channel, what):
    if channel is None or (isinstance(channel, str) and not channel.strip()):
        raise ChannelRequired(
            f"{what} needs the channel whose numbers it reads - got {channel!r}. "
            f"CF-0633: this module holds no channel of its own; pass the batch's "
            f"channel id, its config or its {NARRATION_BUDGET_KEY} block")
    return channel


def narration_budget_file(channel):
    _require_channel(channel, "narration_budget_file()")
    return CHANNELS_DIR / f"{channel}.json"


def load_narration_budget(channel):
    """The channel's `narration_budget` block, checked for the keys the
    pipeline arithmetic needs. Raises rather than defaults: a missing rate is
    a broken config, not some number this module remembers."""
    path = narration_budget_file(channel)
    if not path.exists():
        raise FileNotFoundError(f"no channel config at {path}")
    budget = json.loads(path.read_text()).get(NARRATION_BUDGET_KEY)
    if not isinstance(budget, dict):
        raise KeyError(f"{path}: {NARRATION_BUDGET_KEY} block is missing - CF-0087 put the "
                       f"length budget and the words-per-second rate there, and this code "
                       f"carries no default for either")
    missing = [k for k in NARRATION_BUDGET_REQUIRED if k not in budget]
    if missing:
        raise KeyError(f"{path}: {NARRATION_BUDGET_KEY} is missing {missing}")
    if not any(k in budget for k in NARRATION_TAIL_KEYS):
        raise KeyError(f"{path}: {NARRATION_BUDGET_KEY} records neither of "
                       f"{list(NARRATION_TAIL_KEYS)} - a channel has to say how long its "
                       f"videos' tail is (CF-0141: its own ending clip, or the drawn "
                       f"card), because the narration budget is what is left of "
                       f"target_total_seconds after it")
    rate = budget["words_per_second"]
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        raise ValueError(f"{path}: {NARRATION_BUDGET_KEY}.words_per_second must be a positive "
                         f"number, got {rate!r}")
    _check_rate_envelope(path, budget, rate)
    _check_narration_estimator(path, budget)
    _check_total_band(path, budget, rate)
    stored = budget.get("narration_seconds")
    if stored is not None:
        derived = float(budget["target_total_seconds"]) - tail_seconds(budget)
        if abs(float(stored) - derived) > NARRATION_SECONDS_TOLERANCE:
            raise ValueError(
                f"{path}: {NARRATION_BUDGET_KEY}.narration_seconds is {stored}, but "
                f"target_total_seconds - {tail_key(budget)} is {derived:.3f}. The stored "
                f"number is a convenience copy of that subtraction and may not become a "
                f"second opinion on it - the word budget under it was derived from the "
                f"subtraction, not from this field")
    return budget


def tail_key(budget):
    """Which of `NARRATION_TAIL_KEYS` this budget is measured against.

    `ending_seconds` first: a channel that ships an ending clip closes on the
    clip, and the drawn card's constant beside it is only the floor it would
    fall back to if the file went away."""
    for key in NARRATION_TAIL_KEYS:
        if budget.get(key) is not None:
            return key
    return None


def tail_seconds(budget):
    """How many of `target_total_seconds` the tail takes, so that the rest is
    the narration. Raises rather than defaulting to 0: a budget with no tail
    length is a budget nobody may quietly read as "all 55 seconds are
    narration"."""
    key = tail_key(budget)
    if key is None:
        raise KeyError(f"{NARRATION_BUDGET_KEY} records neither of "
                       f"{list(NARRATION_TAIL_KEYS)}")
    value = budget[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{NARRATION_BUDGET_KEY}.{key} must be a positive number, "
                         f"got {value!r}")
    return float(value)


def total_band(budget):
    """The finished video's editorial band as `(low, high)` seconds.

    CF-0158. This is the whole video - the narration, the footage under it and
    the tail the channel closes on - because that is what the rule the band
    comes from is about: a viewer's patience is spent on the file, not on the
    voice track inside it."""
    lo, hi = (budget.get(k) for k in TOTAL_BAND_KEYS)
    for key, value in zip(TOTAL_BAND_KEYS, (lo, hi)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{NARRATION_BUDGET_KEY}.{key} must be a positive number, "
                             f"got {value!r}")
    lo, hi = float(lo), float(hi)
    if lo >= hi:
        raise ValueError(f"{NARRATION_BUDGET_KEY}: {TOTAL_BAND_KEYS[0]} {lo} is not below "
                         f"{TOTAL_BAND_KEYS[1]} {hi} - that is not a band")
    return lo, hi


def hard_min_seconds(budget):
    """CF-0293. The length under which the channel makes no video at all, or
    `None` when this budget states none.

    `None` rather than a raise, and rather than a default: a budget dict that
    predates CF-0293 is judged by the three CF-0158 verdicts, exactly as it
    was, and nothing invents a refusing floor for a channel that never
    declared one. A channel config on disk may not be in that state -
    `load_narration_budget()` requires the key - but a caller holding an old
    dict (the Editor reads the JSON itself, a test builds one by hand) has to
    degrade rather than crash.

    A key that is present is checked, here and at config time: a hard floor
    that is not a positive number is a typo, and a typo in this field is a
    refusal that never fires."""
    value = budget.get(TOTAL_HARD_MIN_KEY)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{NARRATION_BUDGET_KEY}.{TOTAL_HARD_MIN_KEY} must be a positive "
                         f"number, got {value!r}")
    return float(value)


def narration_band(budget):
    """What the band leaves for the voice and the footage, `(low, high)`.

    `[total_seconds_min - tail, total_seconds_max - tail]` - 39.833-54.833 s
    on example-film today, against a 5.167 s ending clip.

    Derived on every call and stored nowhere, which is the point of CF-0158:
    the floor of the narration follows the length of `ending.mp4` by itself,
    where the literal `[35.0, 60.0]` it replaces followed nothing. It is the
    same subtraction as `narration_seconds = target_total_seconds - tail`
    (CF-0141), deliberately living next to it so the two cannot come apart.

    This is the number a render plan's `duration.target` is: the plan measures
    the voice track, and the voice track is the video minus the tail."""
    lo, hi = total_band(budget)
    tail = tail_seconds(budget)
    if lo - tail <= 0:
        raise ValueError(
            f"{NARRATION_BUDGET_KEY}: the tail ({tail_key(budget)} = {tail}s) is longer "
            f"than the whole video's floor ({TOTAL_BAND_KEYS[0]} = {lo}s), so there is no "
            f"narration left at the bottom of the band")
    return round(lo - tail, 3), round(hi - tail, 3)


def rate_envelope(budget):
    """The slowest and the fastest reading on record, `(min, max)` w/s.

    CF-0279. The voice does not have A rate: Kokoro synthesizes the text in
    chunks of at most 510 phonemes, every extra boundary costs its own
    phrase-final lengthening, and a script's chunk count is not knowable from
    its word count. Measured and estimated over every script this factory has
    on disk for this voice, the reading runs 3.24-3.99 words a second - a
    23 % spread that the median (`words_per_second`) hides. The word budget is
    derived from these two ends and nothing else."""
    lo, hi = (budget.get(k) for k in ("words_per_second_min", "words_per_second_max"))
    for key, value in (("words_per_second_min", lo), ("words_per_second_max", hi)):
        if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"{NARRATION_BUDGET_KEY}.{key} must be a positive number, "
                             f"got {value!r}")
    return float(lo), float(hi)


def derived_word_band(budget):
    """The word budget the channel's own numbers imply, `(min, max)`.

    CF-0279, and the whole shape of the fix. It used to be one length times
    one rate - `(target_total_seconds - tail) x words_per_second` - which is
    how CF-0261 arrived at 182-200 words, a range in which NO script could
    pass: those word counts fall into 3 or 4 Kokoro chunks, the rate had been
    measured on 2-chunk scripts, and the whole range sat beyond the cliff.

    It is now the narration band divided by the rate ENVELOPE, i.e. the
    intersection of what every chunk class allows:

        min = ceil(narration_floor   x fastest rate)   39.833 x 3.990 -> 159
        max = floor(narration_ceiling x slowest rate)  54.833 x 3.240 -> 177

    Read it as: the shortest narration that still reaches the floor when it is
    read as fast as this voice has ever read, and the longest that still
    clears the ceiling when it is read as slowly. A range derived any other
    way promises a script that fits and cannot deliver one.

    It is a WARNING for the writer, not a gate. Even inside it the envelope is
    13 points rather than a promise - two scripts of 183 words in 3 chunks
    came out 3.9 s apart - so what decides whether a written script fits is
    `narration_budget.narration_estimator`, run on the script itself."""
    n_lo, n_hi = narration_band(budget)
    fast_rate = rate_envelope(budget)[1]
    slow_rate = rate_envelope(budget)[0]
    return math.ceil(n_lo * fast_rate - 1e-9), math.floor(n_hi * slow_rate + 1e-9)


def _check_rate_envelope(path, budget, rate):
    """The envelope has to be a band, and it has to contain the median the
    rest of the module reads. A median outside the sample it was taken from is
    a typo somewhere, and everything downstream would be arithmetic on it."""
    lo, hi = rate_envelope(budget)
    if lo > hi:
        raise ValueError(f"{path}: {NARRATION_BUDGET_KEY}.words_per_second_min {lo} is above "
                         f"words_per_second_max {hi} - that is not an envelope")
    if not lo <= float(rate) <= hi:
        raise ValueError(
            f"{path}: {NARRATION_BUDGET_KEY}.words_per_second is {rate}, outside the measured "
            f"envelope {lo}-{hi} w/s it is supposed to be the median of (CF-0279)")


def _check_narration_estimator(path, budget):
    """CF-0279: the block that says how a script's length is decided.

    Checked here rather than left as prose because the one thing that must
    never happen again is a caller quietly dividing words by a constant when
    the estimator is unavailable. `missing_engine_action` is the field that
    forbids it, and a config may not say anything else there."""
    est = budget.get("narration_estimator")
    if not isinstance(est, dict):
        raise KeyError(
            f"{path}: {NARRATION_BUDGET_KEY}.narration_estimator is missing - CF-0279: a "
            f"channel has to name the command that turns a script into seconds, because the "
            f"word budget under it is a warning and not a gate")
    missing = [k for k in NARRATION_ESTIMATOR_REQUIRED if k not in est]
    if missing:
        raise KeyError(f"{path}: {NARRATION_BUDGET_KEY}.narration_estimator is missing {missing}")
    command = est["command"]
    if not isinstance(command, list) or not command or not all(
            isinstance(part, str) and part for part in command):
        raise ValueError(f"{path}: {NARRATION_BUDGET_KEY}.narration_estimator.command must be a "
                         f"non-empty list of strings (argv, run as a subprocess), got {command!r}")
    tol = est["tolerance_seconds"]
    if not isinstance(tol, (int, float)) or isinstance(tol, bool) or tol < 0:
        raise ValueError(f"{path}: {NARRATION_BUDGET_KEY}.narration_estimator.tolerance_seconds "
                         f"must be a non-negative number, got {tol!r}")
    against = est["decide_against"]
    if not isinstance(against, list) or [k for k in against if k not in budget]:
        raise ValueError(
            f"{path}: {NARRATION_BUDGET_KEY}.narration_estimator.decide_against must name keys of "
            f"this block (the band the estimate is judged against), got {against!r}")
    if est["missing_engine_action"] != "refuse":
        raise ValueError(
            f"{path}: {NARRATION_BUDGET_KEY}.narration_estimator.missing_engine_action is "
            f"{est['missing_engine_action']!r}; the only legal value is 'refuse' (CF-0279). A "
            f"caller that cannot run the estimator refuses and writes why - it may not fall back "
            f"to dividing words by words_per_second, which is the defect this block replaces")
    if est["word_range_is"] != "warning":
        raise ValueError(
            f"{path}: {NARRATION_BUDGET_KEY}.narration_estimator.word_range_is is "
            f"{est['word_range_is']!r}; the only legal value is 'warning' (CF-0279). "
            f"narration_words_min/max cannot gate a script: a word count cannot see the chunk "
            f"boundary that moves the reading by seconds")


def _check_total_band(path, budget, rate):
    """CF-0158, the half of the floor that is a refusal: a config whose own
    numbers describe a video outside the band it declares.

    Refused here, at config time, rather than warned about at measure time,
    because these are all decisions somebody typed - the band, the target and
    the word tolerance around it - and a decision that contradicts itself has
    no measurement to wait for. What a finished video actually came out at is
    a different kind of fact and is judged differently; see
    `judge_video_length()`."""
    lo, hi = total_band(budget)
    if lo < MIN_TARGET_SECONDS or hi > MAX_TARGET_SECONDS:
        raise ValueError(
            f"{path}: {NARRATION_BUDGET_KEY} declares a video band of {lo}-{hi}s, outside "
            f"the {MIN_TARGET_SECONDS:.0f}-{MAX_TARGET_SECONDS:.0f}s the factory agrees on "
            f"(CF-0158). A channel may be stricter than the factory, never looser")
    # CF-0293: the hard floor, judged the same way and for the same reason -
    # it is a decision somebody typed, so a decision that contradicts itself is
    # wrong the moment it is typed. Two ways it can:
    #   * below the factory's own hard floor - looser than the factory, which
    #     no channel may be (same rule as the band above);
    #   * not strictly under the band's floor - a hard floor at or above
    #     `total_seconds_min` leaves no room for the band between them, i.e.
    #     it erases the whole point of CF-0293's two-floor decision: the 30-45s
    #     stretch where the video is made, warned about and counted.
    hard = hard_min_seconds(budget)
    if hard is not None:
        if hard < HARD_MIN_TARGET_SECONDS:
            raise ValueError(
                f"{path}: {NARRATION_BUDGET_KEY}.{TOTAL_HARD_MIN_KEY} is {hard}s, under the "
                f"{HARD_MIN_TARGET_SECONDS:.0f}s hard floor the factory agrees on (CF-0293). "
                f"A channel may be stricter than the factory, never looser")
        if hard >= lo:
            raise ValueError(
                f"{path}: {NARRATION_BUDGET_KEY}.{TOTAL_HARD_MIN_KEY} is {hard}s, not below "
                f"{TOTAL_BAND_KEYS[0]} {lo}s. The hard floor is the line UNDER the band "
                f"(CF-0293): between the two a video is short - made, warned about and "
                f"counted - and a hard floor that reaches the band's floor leaves no such "
                f"stretch at all")
    target = float(budget["target_total_seconds"])
    if not lo <= target <= hi:
        raise ValueError(
            f"{path}: {NARRATION_BUDGET_KEY}.target_total_seconds is {target}s, outside its "
            f"own band {lo}-{hi}s. The target is one number inside the band, and the whole "
            f"word budget is derived from it")
    # CF-0279 replaced the single-rate form of this check. Until today each end
    # of the word range was read at the median rate, which passes a range the
    # voice cannot actually deliver: 200 words at the median 3.66 is 54.6 s and
    # looks safe, while the same 200 words read at the slowest rate on record
    # is 61.7 s - over the ceiling, which is what shipped. Each end is now read
    # at the rate that pushes it OUTWARD, so the range is only legal if every
    # reading of it lands in the band.
    n_lo, n_hi = narration_band(budget)
    slow_rate, fast_rate = rate_envelope(budget)
    words_lo = budget.get("narration_words_min")
    words_hi = budget.get("narration_words_max")
    for words, seconds, worst_rate, end, bound in (
            (words_lo, n_lo, fast_rate, "shortest", "floor"),
            (words_hi, n_hi, slow_rate, "longest", "ceiling")):
        if words is None:
            continue
        slack = WORD_BAND_SLACK_WORDS / worst_rate
        spoken = float(words) / worst_rate
        outside = spoken < seconds - slack if bound == "floor" else spoken > seconds + slack
        if outside:
            raise ValueError(
                f"{path}: {NARRATION_BUDGET_KEY}'s {end} allowed narration is {words} words "
                f"= {spoken:.2f}s at {worst_rate} w/s - the {'fastest' if bound == 'floor' else 'slowest'} "
                f"reading on record - which is past the {bound} of the derived narration band "
                f"{n_lo}-{n_hi}s ({TOTAL_BAND_KEYS[0]}/{TOTAL_BAND_KEYS[1]} minus "
                f"{tail_key(budget)}). Every reading of the word range has to land inside the "
                f"editorial band, not just the median one (CF-0158, CF-0279)")
    derived_lo, derived_hi = derived_word_band(budget)
    if words_lo is not None and words_hi is not None and (
            float(words_lo) < derived_lo - 1e-9 or float(words_hi) > derived_hi + 1e-9):
        raise ValueError(
            f"{path}: {NARRATION_BUDGET_KEY}'s word range {words_lo}-{words_hi} is wider than "
            f"the {derived_lo}-{derived_hi} its own numbers derive - the narration band "
            f"{n_lo}-{n_hi}s divided by the rate envelope {slow_rate}-{fast_rate} w/s "
            f"(CF-0279). A channel may be stricter than its measurements, never looser")


# CF-0158: what a finished video's measured length means. Verdicts and actions
# are kept as separate fields because they are deliberately not in step with
# each other at the ends of the band.
#
#   over      ->  refuse   past `total_seconds_max`; CF-0087's existing halt
#   in_band   ->  pass
#   short     ->  warn     under `total_seconds_min`; recorded, never silent
#   too_short ->  refuse   under `total_seconds_hard_min` (CF-0293)
#
# CF-0293 (the user, 2026-09-20) added the fourth. Read the two low verdicts
# together: `short` is 30-45 s, where the video is made and counted, and
# `too_short` is under 30 s, where it is not made at all. The four reasons
# below are why `short` warns; each of them is an argument about a video that
# is a few seconds under the band, and each stops applying at half the target:
#
#   1. "the fix is to say more, and the refusal would only spend renders on
#      the way to the same hand-back" - true of a 43 s video, whose script is
#      a few sentences short. A 25 s video is not a script a few sentences
#      short; something upstream went wrong (a truncated TTS, a script that
#      lost half its body), and rendering it spends the render to produce a
#      file nobody will publish.
#   2. "nothing in the rule says a 43 s video is unpublishable" - nothing says
#      a 25 s one is publishable either. At half the target the video has not
#      missed the band, it has missed being the thing the channel makes.
#   3. "the floor is a day old and has no retention data behind it" - CF-0158
#      wrote that on 2026-09-08 about the 45 s line, and it still holds: 45 s
#      still only warns. The 30 s line is not a retention number at all, it is
#      the user's line for "this is not a video", which is why it may refuse
#      without waiting for the Analyst.
#   4. "a warning here is still a change, because today there is nothing" -
#      that change happened; the warning exists, and CF-0293 keeps it. What
#      the warning could not do is stop a broken render, and that is the only
#      thing the new verdict adds.
#
# WHY THE FLOOR ONLY WARNS, when the ceiling refuses. Four reasons, and the
# first is the one that decides it:
#
# 1. The remedies are not symmetric. Over the ceiling the fix is mechanical
#    and belongs to the pipeline - cut words, the word budget above says
#    exactly how many. Under the floor the fix is to SAY MORE, and there is no
#    step in this factory that can invent another eight seconds of substance
#    on demand. A refusal is only worth issuing where somebody can act on it;
#    a refusal on the floor would send the video round the render loop until
#    it hit the attempt cap (CF-0098) and stopped at NEEDS-YOU anyway - the
#    same hand-back, several renders later.
# 2. The costs of being wrong are not symmetric either. A 63-second video
#    breaks the stated rule exactly where the rule bites - that is the length
#    at which the user says viewers leave. A 43-second video is merely short
#    of the band; nothing in the rule says it is unpublishable, only that it
#    is not where the channel wants to be.
# 3. The two numbers have different standing. The ceiling has been enforced
#    since CF-0087 and everything downstream is built around that halt. The
#    floor is a day old (CF-0158) and this repository has no retention data
#    behind it at all - the Analyst (1.4) has not run. A brand-new editorial
#    number should not begin its life by refusing to publish; the repo has
#    made this call before, and `video_editor.two_source_gate` is the same
#    shape - measure first, enforce when the measurements justify it.
# 4. A warning here is still a change, because today there is nothing. A
#    video can come out at 30 seconds and no gate, log line or field anywhere
#    records that it happened. The floor's job in this task is to make the
#    short video VISIBLE and named; making it fatal is a second decision, and
#    one that wants the measurements this warning will produce.
#
# What IS refused on the floor side is a config that contradicts itself -
# `_check_total_band()` above. The difference is what kind of thing is being
# judged: a config is a set of decisions, and a decision outside the band is
# wrong the moment it is typed; a rendered length is an outcome, and an
# outcome outside the band is information.
VIDEO_LENGTH_VERDICTS = ("in_band", "short", "too_short", "over")
VIDEO_LENGTH_ACTIONS = {"in_band": "pass", "short": "warn",
                        "too_short": "refuse", "over": "refuse"}
# The verdicts a video is still made under. Named so that a caller does not
# have to know which of the four they are: "is this length publishable" is
# `verdict in VIDEO_LENGTH_MADE` or, the same thing, `action != "refuse"`.
VIDEO_LENGTH_MADE = ("in_band", "short")
# CF-0293: the funnel code a `too_short` refusal carries out of the batch -
# shared/runlog/funnel.py FUNNEL_CODES. Named here, next to the verdict that
# causes it, so the gate that refuses does not have to pick a code by hand.
VIDEO_LENGTH_REFUSAL_CODE = "video_too_short"


def total_seconds_from_narration(narration_seconds, budget):
    """The finished video's length: the narration plus whatever the channel
    closes on, chosen by `tail_key()` - the ending clip when the channel ships
    one, the drawn card otherwise. Here so that a caller adding the tail by
    hand does not reach for `end_card_seconds` on a channel whose videos end
    on a clip.

    CF-0633: `budget` is the channel's `narration_budget` block (or its id or
    config, see `narration_budget_of()`) and is required."""
    budget = narration_budget_of(budget)
    return round(float(narration_seconds) + tail_seconds(budget), 3)


def judge_video_length(total_seconds, budget):
    """CF-0158. The verdict on one finished video's length.

    `total_seconds` is the whole file - narration plus tail; pass a voice
    length through `total_seconds_from_narration()` first. Returns a record
    with `verdict` in `VIDEO_LENGTH_VERDICTS` and `action` in
    `VIDEO_LENGTH_ACTIONS`; `deviation` is the signed distance to the nearest
    bound of the BAND, 0 inside the band, in the same convention as a render
    plan's `duration.deviation` - including under the hard floor, where the
    band's floor stays the ruler and the reason names the hard floor.

    The asymmetry between the two ends is the point of the task and is
    argued in the block comment above, not an oversight to be tidied away.

    CF-0293: a budget that states `total_seconds_hard_min` gets the fourth
    verdict, `too_short`/`refuse`, under it; one that states none is judged by
    the three CF-0158 verdicts exactly as before - see `hard_min_seconds()`
    for why an absent hard floor is not invented here.

    CF-0633: `budget` - the channel's `narration_budget` block, or its id or
    config - is required: the band is the channel's, never this module's."""
    budget = narration_budget_of(budget)
    lo, hi = total_band(budget)
    hard = hard_min_seconds(budget)
    total = round(float(total_seconds), 3)
    if total > hi:
        verdict, deviation = "over", round(total - hi, 3)
        reason = (f"{total:.2f}s is over the {hi:.0f}s ceiling by {deviation:.2f}s - the "
                  f"length past which the channel says viewers leave (CF-0158); the "
                  f"pipeline stops here rather than publish it (CF-0087)")
    elif hard is not None and total < hard:
        # CF-0293. Measured against the HARD floor, and `deviation` still
        # points at the band's floor: the band is what the video was aiming
        # at, and a reader comparing two short videos wants the same ruler
        # under both. How far under the hard floor it is, is in the reason.
        verdict, deviation = "too_short", round(total - lo, 3)
        reason = (f"{total:.2f}s is under the {hard:.0f}s hard floor by {hard - total:.2f}s "
                  f"(CF-0293, the user 2026-09-20). Refused, not warned: under half the "
                  f"target this is not a video a few sentences short of the band, it is a "
                  f"video that should not be rendered - the plan stops here, the same way "
                  f"the {hi:.0f}s ceiling stops it. Between {hard:.0f}s and {lo:.0f}s the "
                  f"video is still made, with a warning ('short')")
    elif total < lo:
        verdict, deviation = "short", round(total - lo, 3)
        reason = (f"{total:.2f}s is {abs(deviation):.2f}s under the {lo:.0f}s floor of the "
                  f"channel's band (CF-0158). Recorded, not refused: the fix is more "
                  f"substance, which no step of this pipeline can add on its own - see "
                  f"VIDEO_LENGTH_ACTIONS for why the two ends differ")
    else:
        verdict, deviation = "in_band", 0.0
        reason = f"{total:.2f}s is inside the channel's {lo:.0f}-{hi:.0f}s band"
    return {
        "total_seconds": total,
        "band": [lo, hi],
        # CF-0293: the hard floor this length was judged against, beside the
        # band, for the same reason the band travels - a verdict that lands in
        # a plan or a ledger has to say what it measured against. `None` says
        # the budget stated no hard floor and no `too_short` was possible.
        "hard_min": hard,
        "narration_band": list(narration_band(budget)),
        "tail_seconds": tail_seconds(budget),
        "tail_key": tail_key(budget),
        "verdict": verdict,
        "action": VIDEO_LENGTH_ACTIONS[verdict],
        "deviation": deviation,
        "reason": reason,
    }


def narration_budget_of(channel):
    """CF-0633: the `narration_budget` block a caller means by `channel`.

    `channel` is a channel id (loaded and checked by `load_narration_budget`),
    a path to a channel config, a whole channel config, or an already-loaded
    `narration_budget` block (returned as it is - a caller holding a doctored
    copy judges by its copy). None or "" raises `ChannelRequired`: there is no
    channel this module may fall back to.
    """
    _require_channel(channel, "this check")
    if isinstance(channel, (str, Path)):
        path = Path(channel)
        if path.suffix == ".json" or path.exists():
            budget = json.loads(path.read_text()).get(NARRATION_BUDGET_KEY)
            if not isinstance(budget, dict):
                raise KeyError(f"{path}: no {NARRATION_BUDGET_KEY} block")
            return budget
        return load_narration_budget(str(channel))
    if isinstance(channel, dict):
        if NARRATION_BUDGET_KEY in channel:
            return channel[NARRATION_BUDGET_KEY]
        return channel
    raise TypeError(f"cannot read a narration budget from {channel!r}")


def narration_rate(channel):
    """CF-0633: `(words_per_second, words_per_second_source)` of a channel -
    what the module once held as `WORDS_PER_SECOND` / `_SOURCE` for the first
    channel. `channel` as in `narration_budget_of()`."""
    budget = narration_budget_of(channel)
    rate = budget.get("words_per_second")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        raise ValueError(f"words_per_second must be a positive number, got {rate!r}")
    return rate, budget.get("words_per_second_source", "unstated")

# CF-0098: the Video Editor's per-video attempt cap. The stage counts every
# render attempt of a video - CF-0031 degradations included - and at the cap
# stops with `NEEDS-YOU <slug>: attempt cap <N> reached - last failure: ...`
# instead of trying once more. The number lives in the channel config under
# `video_editor.max_attempts_per_video`, read by
# agents/video-editor/scripts/attempts.py (a separate repo that reads the JSON,
# not this module); this is the root's copy of the rule so that a config the
# Editor would refuse - or silently misread - is caught at `validate_inserts.py`
# time, which is where the root walks every channel config. Absent block or
# absent key means the default; anything present has to be an integer of at
# least 1, and no key the Editor does not read is admitted, because a typo in
# here (`max_attempts` for `max_attempts_per_video`) would otherwise be a cap
# that is silently 3.
# CF-0118: the two-source gate's mode, in the same block and read the same
# way - agents/video-editor/scripts/source_gate.py and build_render_plan.py
# take it from `video_editor.two_source_gate`. `"measure"` records the verdict
# on every plan and never rejects; `"enforce"` refuses the plan with exit 2 and
# a `two_source_gate` deficit. The object form carries the same `mode` plus
# `required`, the number of independent sources a plan needs (>= 2 - a required
# of 1 is not a two-source gate, it is the gate switched off, and switching it
# off is what `"measure"` is for). Absent = `"measure"`, because the measured
# pass rate is 38 % (0 of 4 in the 2026-09-03 batch) and the task's own rule
# says a rate under 50 % widens the source pool before it turns the gate on.
VIDEO_EDITOR_KEY = "video_editor"
VIDEO_EDITOR_MAX_ATTEMPTS_KEY = "max_attempts_per_video"
VIDEO_EDITOR_DEFAULT_MAX_ATTEMPTS = 3
# CF-0415: the degradations QC itself hinted have a ceiling of their own -
# agents/video-editor/scripts/attempts.py reads `video_editor.max_qc_degrades_per_video`
# the same way as the attempt cap (an integer >= 1, else its default 3). The key
# reached the Editor without the root's copy of the rule; CF-0431 added it.
VIDEO_EDITOR_MAX_QC_DEGRADES_KEY = "max_qc_degrades_per_video"
VIDEO_EDITOR_TWO_SOURCE_GATE_KEY = "two_source_gate"
VIDEO_EDITOR_GATE_MODES = ("measure", "enforce")
VIDEO_EDITOR_DEFAULT_TWO_SOURCE_GATE = "measure"
VIDEO_EDITOR_GATE_MIN_REQUIRED = 2
VIDEO_EDITOR_GATE_KNOWN_KEYS = ("mode", "required")
# CF-0327: the inset-panel gate's mode, in the same block and read the same
# way - agents/video-editor/scripts/build_render_plan.py::panel_gate_thresholds
# takes it off `video_editor.panel_in_frame` and carries it into the plan's
# `qc_thresholds`, where inset_panel.mode_of() and qc_render.py read it. The
# gate refuses a block whose source carries an on-screen panel the framing
# delivers a sliver of (CF-0327, `mormon-wives-comeback` at 29 s). `"fail"`
# refuses the render, `"warn"` records and ships, `"off"` only measures; the
# Editor's own default is `"fail"`, which is why a channel that wants the
# warning has to say so here. `floor` is the share of the panel that has to be
# in frame for the block to pass, a number in (0, 1].
#
# Object only, never a bare string: the Editor's reader calls `.get("mode")` on
# whatever it finds, so `"warn"` written flat would not be a milder gate but an
# unread key - the silent misreading this whole schema exists to catch
# (CF-0161, CF-0191).
VIDEO_EDITOR_PANEL_IN_FRAME_KEY = "panel_in_frame"
VIDEO_EDITOR_PANEL_MODES = ("fail", "warn", "off")
VIDEO_EDITOR_PANEL_KNOWN_KEYS = ("mode", "floor")
# CF-0379: the meme-caption gate's mode, in the same block and read the same
# way. The gate refuses a block that a meme insert holds while not one of our
# word-by-word captions is drawn on it with the voice still speaking - the
# defect the user found on 2026-09-24, watching the meme's span play as a
# silent picture with the narration unwritten. `"fail"` refuses the render,
# `"warn"` records and ships, `"off"` only measures; the Editor's own default
# is `"fail"`, so a channel that wants the warning has to say so here - and
# example-film does, because ROADMAP `## Versioning` holds an unpriced rule at a
# warning and `runlog gate-price --rule video_editor.meme_captions` reads `no
# basis` (shared/gate-prices.json, docs/gate-prices.md).
#
# Object only, never a bare string, for `panel_in_frame`'s reason exactly: the
# Editor's reader calls `.get("mode")` on whatever it finds, so `"warn"`
# written flat would not be a milder gate but an unread key, leaving the gate
# at `fail` - the silent misreading this whole schema exists to catch (CF-0161,
# CF-0191).
VIDEO_EDITOR_MEME_CAPTIONS_KEY = "meme_captions"
# CF-0791: the root's shot rule before the cut, read by
# agents/video-editor/scripts/resolve_anchors.py::configure_shot_guard() off
# `video_editor.shot_guard` (`shared/score/shot_guard.channel_config`). The
# rule and its settings' contract are the module's own - `mode` fail/warn/off,
# the text-panel region count, the resolution floor, the hook's still floor -
# so the block is judged by `shot_guard.validate_config()` and nothing here
# keeps a second copy of its keys.
VIDEO_EDITOR_SHOT_GUARD_KEY = "shot_guard"
VIDEO_EDITOR_MEME_CAPTION_MODES = ("fail", "warn", "off")
VIDEO_EDITOR_MEME_CAPTION_KNOWN_KEYS = ("mode",)
# CF-0416: the QC refusals the channel counts as cosmetic. Read by
# agents/video-editor/scripts/qc_cosmetic.py load() (CONFIG_KEY
# `video_editor.qc_cosmetic_rules`): a video QC refused *only* on rules of this
# list keeps `qc.passed: false` and is admitted to the frame judge in writing
# (`05-video-editor.json#videos[].judge_admitted_despite`), paying the score
# model's price for the rule instead. A list of rule names - the `measured` key
# of a gate (`meme_caption_blank_blocks`, `panel_cut_blocks`, ...) or a gate's
# short name. The hard gates of the score model are never cosmetic: the loader
# drops them quietly, so the schema refuses them loudly - a channel that wrote
# `burned_text` here believes something about its videos that is not true.
VIDEO_EDITOR_QC_COSMETIC_RULES_KEY = "qc_cosmetic_rules"
VIDEO_EDITOR_QC_NEVER_COSMETIC = ("stream", "resolution", "duration", "black", "silence",
                                  "clipping", "burned_text", "other")
# CF-0418: the channel's line on pictures - the share of the running time the
# pictures (images, posters, cards, a whole-frame meme; a frame held off a
# video never counts, the user's variant (a) of 2026-09-30) may hold before the
# plan is refused as `score.hard.still_share_over_half`. Read by
# agents/video-editor/scripts/still_share.py max_share(): a number in (0, 1],
# anything else is read as its default 0.5 - so the schema refuses it loudly.
VIDEO_EDITOR_MAX_STILL_SHARE_KEY = "max_still_share"
# CF-0153: the three keys through which a channel says where its own asset
# files live. Each one overrides a convention path under
# `channels/<channel_id>/` - the directory that already holds `stance.json` -
# and each is read by the Editor in the same shape:
#
#   video_editor.ambient.path   -> agents/video-editor/scripts/ambient_bed.py
#                                  ambient_path(), overriding ambient.<ext>
#   video_editor.ending.path    -> scripts/end_card.py ending_path()  (CF-0141),
#                                  overriding ending.mp4
#   video_editor.end_card.logo  -> scripts/end_card.py logo_path()    (CF-0117),
#                                  overriding logo.png|svg|jpg|jpeg|webp
#
# None of the three was admitted here until CF-0153, so the strict rule at
# validate_video_editor_block() refused all of them - a gap, not a decision:
# CF-0117 and CF-0141 each documented an override the root would then reject.
# It never showed in production because example-film uses none of them and
# lives on the convention paths.
#
# What is enforced, and why exactly this much. Each block is an object, every
# key it may carry is listed, and the key it exists for is required and has to
# be a non-empty string. That is the whole of what the Editor reads, and each
# clause catches a typo that would otherwise be silent rather than loud: the
# readers all test `isinstance(str) and value.strip()` before using the
# override and fall through to the convention when it fails, so `{"path": ""}`,
# `{"path": null}`, `{"paht": "..."}` or a bare `{}` would not raise anywhere -
# they would render the convention file, or the drawn card, or the generated
# bed, and the channel's stated decision would simply not have happened. An
# unknown-key check that admits an empty object is the same silence in a
# different place.
#
# What is deliberately *not* enforced: whether the file is there. A relative
# path is resolved against the factory root and an absolute one is taken as
# given, and neither is stat()ed here. This validator reads a config and
# answers whether it is a legal set of decisions; it runs from
# inserts/validate_inserts.py over every channel, on machines and at moments
# that have nothing to do with a render, and a check that touches the disk
# would make that answer depend on which checkout it was asked in - an asset
# not yet synced, or a task branch, would fail vocabulary validation for a
# reason that is not in the config. The missing file is caught, loudly and up
# front, where the doctrine already puts it: `AmbientBedError` and
# `EndCardError` raise before ffmpeg starts, in the process that has the file
# system the render will actually use. The two checks are different kinds and
# both are wanted - shape here, existence there.
VIDEO_EDITOR_AMBIENT_KEY = "ambient"
VIDEO_EDITOR_ENDING_KEY = "ending"
VIDEO_EDITOR_END_CARD_KEY = "end_card"
# CF-0191: the kind of value each key inside an asset block carries. `path` is
# the override string CF-0153 wrote this machinery for; `number` arrived with
# CF-0165, which put the supplied bed's mix level in the same block, and is the
# reason the shape below is a per-key kind and no longer "every key is a path".
VIDEO_EDITOR_KIND_PATH = "path"
VIDEO_EDITOR_KIND_NUMBER = "number"
# CF-0271: a *list* of paths, the third kind. The user decided on 2026-09-20
# that this channel's bed is a rotation of three lofi tracks rather than one
# file, so `ambient` has to be able to name a set. `path` (one file) is not
# replaced by it - other channels and every batch rendered before 2026-09-21
# are on the single form, and the Editor keeps reading it.
VIDEO_EDITOR_KIND_PATHS = "paths"
VIDEO_EDITOR_BEDS_KEY = "beds"
# block -> {key the Editor reads inside it: its kind}.
#
# CF-0153 required every key here, on the argument that these blocks exist only
# to carry an override, so one that names none is not a decision but a line
# that does nothing. CF-0165 broke the premise, not the argument: `ambient` now
# also carries `bed_db`, a level for the file the *convention* path already
# finds, so `{"bed_db": -25}` - the real example-film config - is a complete
# decision with no `path` in it, and the root refused it for five weeks (the
# defect CF-0191 was written for). What survives of the argument is the part
# that was actually about decisions: a block has to name *at least one* of the
# keys the Editor reads. For `ending` and `end_card`, which read one key each,
# that is the old rule unchanged.
#
# CF-0271 adds `beds` beside `path`, and the pair is exclusive - see
# VIDEO_EDITOR_EXCLUSIVE_KEYS.
VIDEO_EDITOR_ASSET_KEYS = {
    VIDEO_EDITOR_AMBIENT_KEY: {"path": VIDEO_EDITOR_KIND_PATH,
                               VIDEO_EDITOR_BEDS_KEY: VIDEO_EDITOR_KIND_PATHS,
                               "bed_db": VIDEO_EDITOR_KIND_NUMBER},
    VIDEO_EDITOR_ENDING_KEY: {"path": VIDEO_EDITOR_KIND_PATH},
    VIDEO_EDITOR_END_CARD_KEY: {"logo": VIDEO_EDITOR_KIND_PATH},
}
# CF-0271: keys inside one block that may not both be named, because the
# Editor has to pick one of them and would pick silently. `ambient.path` names
# the one file the bed is, `ambient.beds` names the set it is drawn from; a
# config carrying both has stated two different beds and the render would
# answer with whichever the reader happens to check first - which is the exact
# shape of failure CF-0271 exists to stop.
VIDEO_EDITOR_EXCLUSIVE_KEYS = {
    VIDEO_EDITOR_AMBIENT_KEY: ("path", VIDEO_EDITOR_BEDS_KEY),
}
# CF-0161/CF-0191: the source badge's switch (CF-0164, CF-0166), read by
# agents/video-editor/scripts/comparison_line.py - publishers(), platforms(),
# enabled(). It is *not* an asset block and is not validated as one: its keys
# are two additive tables and an on/off switch, none of them required, because
# an empty table here is a stated decision ("nothing this channel has met needs
# an entry the built-in defaults do not already carry") rather than a missing
# one. The precedent is `_validate_two_source_gate` - a switch - not
# `_validate_asset_override` - a path the channel substitutes.
#
#   publishers  {host: the publication's own name}, merged over
#               comparison_line.DEFAULT_PUBLISHERS -> that host gets a badge
#   platforms   [host, ...], added to comparison_line.DEFAULT_PLATFORMS ->
#               that host gets no badge and the check records a skip
#   enabled     false turns the line off for the channel. Absent = on, and
#               absent has to stay absent: load_video_editor_settings() fills
#               in no default for it (CF-0153, decision 3 - the root may not
#               name a decision the channel never took).
VIDEO_EDITOR_COMPARISON_LINE_KEY = "comparison_line"
VIDEO_EDITOR_COMPARISON_LINE_KNOWN_KEYS = ("publishers", "platforms", "enabled")
# CF-0695 (the user's Q35, 2026-10-12): the loudness every finished video is
# brought to - read by agents/video-editor/scripts/loudness.py settings(),
# applied by build_soundtrack.py and checked by qc_render.py. An object
# {target_lufs, true_peak_db}; either field, or the whole block, may be left
# out and the Editor's default (-14 LUFS, -1 dBTP) applies - all three Example
# channels rely on it. The ranges are the Editor's own (loudness.py
# TARGET_LUFS_RANGE / TRUE_PEAK_RANGE); out of range the Editor refuses the mix.
VIDEO_EDITOR_LOUDNESS_KEY = "loudness"
VIDEO_EDITOR_LOUDNESS_KNOWN_KEYS = ("target_lufs", "true_peak_db")
VIDEO_EDITOR_LOUDNESS_RANGES = {"target_lufs": (-30.0, -5.0),
                                "true_peak_db": (-9.0, 0.0)}
# The keys the Editor actually reads at the top of the block. Prose is added to
# this by _video_editor_known_keys() below.
VIDEO_EDITOR_READ_KEYS = (VIDEO_EDITOR_MAX_ATTEMPTS_KEY,
                          VIDEO_EDITOR_MAX_QC_DEGRADES_KEY,
                          VIDEO_EDITOR_TWO_SOURCE_GATE_KEY,
                          VIDEO_EDITOR_PANEL_IN_FRAME_KEY,
                          VIDEO_EDITOR_MEME_CAPTIONS_KEY,
                          VIDEO_EDITOR_SHOT_GUARD_KEY,
                          VIDEO_EDITOR_QC_COSMETIC_RULES_KEY,
                          VIDEO_EDITOR_MAX_STILL_SHARE_KEY,
                          VIDEO_EDITOR_AMBIENT_KEY,
                          VIDEO_EDITOR_ENDING_KEY,
                          VIDEO_EDITOR_END_CARD_KEY,
                          VIDEO_EDITOR_COMPARISON_LINE_KEY,
                          VIDEO_EDITOR_LOUDNESS_KEY)
# CF-0191: prose. Every block in this config carries its reasoning with it -
# `note` at the top of `video_editor`, `note` inside `ambient`, and
# `enabled_note` inside `comparison_line`, which explains a switch the channel
# deliberately did *not* set. Admitting prose by a rule rather than by a list
# is what keeps the strict unknown-key check strict: `note`, and `<key>_note`
# for a key the Editor reads, are the two legal shapes, so `bed_db_note`
# annotates `bed_db` and `bed_bd_note` is still the loud typo it should be.
VIDEO_EDITOR_NOTE_KEY = "note"
VIDEO_EDITOR_NOTE_SUFFIX = "_note"


def _video_editor_prose_keys(read_keys):
    """The prose keys legal beside `read_keys`: `note` and `<key>_note`."""
    return (VIDEO_EDITOR_NOTE_KEY,) + tuple(f"{k}{VIDEO_EDITOR_NOTE_SUFFIX}"
                                            for k in read_keys)


def _video_editor_known_keys(read_keys):
    """Everything a block may carry: what the Editor reads, plus prose."""
    return tuple(read_keys) + _video_editor_prose_keys(read_keys)


def _unknown_key_errors(block, read_keys, ctx):
    """The strict unknown-key clause, shared by every block under
    `video_editor`. Named separately so the message says what the Editor reads
    and mentions prose without burying the first list in the second."""
    known = _video_editor_known_keys(read_keys)
    unknown = sorted(k for k in block if k not in known)
    if not unknown:
        return []
    return [f"{ctx}: unknown key(s) {unknown} - the Video Editor reads only "
            f"{list(read_keys)} (beside {VIDEO_EDITOR_NOTE_KEY!r} and "
            f"'<key>{VIDEO_EDITOR_NOTE_SUFFIX}' prose)"]


VIDEO_EDITOR_KNOWN_KEYS = _video_editor_known_keys(VIDEO_EDITOR_READ_KEYS)


def _validate_two_source_gate(gate, bctx):
    """Errors for one `video_editor.two_source_gate` value."""
    gctx = f"{bctx}.{VIDEO_EDITOR_TWO_SOURCE_GATE_KEY}"
    modes = list(VIDEO_EDITOR_GATE_MODES)
    if isinstance(gate, str):
        if gate not in VIDEO_EDITOR_GATE_MODES:
            return [f"{gctx}: must be one of {modes}, got {gate!r}"]
        return []
    if not isinstance(gate, dict):
        return [f"{gctx}: must be one of {modes} or an object "
                f"{{mode, required}}, got {gate!r}"]
    errs = []
    unknown = sorted(k for k in gate if k not in VIDEO_EDITOR_GATE_KNOWN_KEYS)
    if unknown:
        errs.append(f"{gctx}: unknown key(s) {unknown} - the Video Editor reads only "
                    f"{list(VIDEO_EDITOR_GATE_KNOWN_KEYS)}")
    if "mode" not in gate:
        errs.append(f"{gctx}.mode: required in the object form, one of {modes}")
    else:
        mode = gate["mode"]
        if mode not in VIDEO_EDITOR_GATE_MODES:
            errs.append(f"{gctx}.mode: must be one of {modes}, got {mode!r}")
    if "required" in gate:
        req = gate["required"]
        if (not isinstance(req, int) or isinstance(req, bool)
                or req < VIDEO_EDITOR_GATE_MIN_REQUIRED):
            errs.append(f"{gctx}.required: must be an integer >= "
                        f"{VIDEO_EDITOR_GATE_MIN_REQUIRED}, got {req!r}")
    return errs


def _validate_panel_in_frame(block, bctx):
    """Errors for one `video_editor.panel_in_frame` block (CF-0327).

    A switch like `two_source_gate`, with one difference that is not a matter
    of taste: the object form is the only form. The Editor reads the block with
    `.get("mode")`, so a bare `"warn"` here is not a milder gate, it is a key
    nobody reads and a gate left at its `fail` default - which is exactly the
    kind of silence CF-0191 was about. `mode` is required for the same reason:
    a block naming only a floor states no opinion on the thing it was written
    to state an opinion on.
    """
    kctx = f"{bctx}.{VIDEO_EDITOR_PANEL_IN_FRAME_KEY}"
    modes = list(VIDEO_EDITOR_PANEL_MODES)
    if not isinstance(block, dict):
        return [f"{kctx}: must be an object {{mode, floor}} with `mode` one of {modes}, "
                f"got {block!r} - the Editor reads this block's `mode` key, so a bare "
                f"string is an unread key and leaves the gate at its default "
                f"({VIDEO_EDITOR_PANEL_MODES[0]!r})"]
    errs = _unknown_key_errors(block, VIDEO_EDITOR_PANEL_KNOWN_KEYS, kctx)
    if "mode" not in block:
        errs.append(f"{kctx}.mode: required, one of {modes}")
    elif block["mode"] not in VIDEO_EDITOR_PANEL_MODES:
        errs.append(f"{kctx}.mode: must be one of {modes}, got {block['mode']!r}")
    if "floor" in block:
        floor = block["floor"]
        if (not isinstance(floor, (int, float)) or isinstance(floor, bool)
                or not 0.0 < floor <= 1.0):
            errs.append(f"{kctx}.floor: must be a number in (0, 1] - the share of the "
                        f"panel that has to be in frame - got {floor!r}")
    return errs


def _validate_qc_cosmetic_rules(value, bctx):
    """Errors for `video_editor.qc_cosmetic_rules` (CF-0416): a list of
    non-empty rule names, none of them a hard gate. The Editor's loader reads a
    value of any other shape as its default, so a wrong shape here is a setting
    that silently does not apply."""
    kctx = f"{bctx}.{VIDEO_EDITOR_QC_COSMETIC_RULES_KEY}"
    if not isinstance(value, list) or not all(isinstance(r, str) and r.strip()
                                              for r in value):
        return [f"{kctx}: must be a list of rule names (e.g. [\"meme_caption_blank_blocks\"]), "
                f"got {value!r} - the Editor reads any other shape as its default"]
    hard = [r for r in value if r in VIDEO_EDITOR_QC_NEVER_COSMETIC]
    if hard:
        return [f"{kctx}: {hard} are hard gates and never cosmetic "
                f"({list(VIDEO_EDITOR_QC_NEVER_COSMETIC)}) - the Editor would drop them"]
    return []


def _validate_loudness(block, bctx):
    """Errors for `video_editor.loudness` (CF-0695)."""
    kctx = f"{bctx}.{VIDEO_EDITOR_LOUDNESS_KEY}"
    if not isinstance(block, dict):
        return [f"{kctx}: must be an object {{target_lufs, true_peak_db}}, got "
                f"{block!r} - the Editor refuses the mix on anything else"]
    errs = _unknown_key_errors(block, VIDEO_EDITOR_LOUDNESS_KNOWN_KEYS, kctx)
    for field, (lo, hi) in VIDEO_EDITOR_LOUDNESS_RANGES.items():
        if field not in block:
            continue
        v = block[field]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
            errs.append(f"{kctx}.{field}: must be a number in [{lo}, {hi}], got "
                        f"{v!r} - the Editor refuses the mix on anything else")
    return errs


def _validate_max_still_share(value, bctx):
    """Errors for `video_editor.max_still_share` (CF-0418): a fraction in (0, 1]."""
    ok = isinstance(value, (int, float)) and not isinstance(value, bool) and 0 < value <= 1
    if ok:
        return []
    return [f"{bctx}.{VIDEO_EDITOR_MAX_STILL_SHARE_KEY}: must be a number in (0, 1] "
            f"(a share of the running time, e.g. 0.5), got {value!r} - the Editor reads "
            f"any other value as its default 0.5"]


def _validate_meme_captions(block, bctx):
    """Errors for one `video_editor.meme_captions` block (CF-0379).

    `panel_in_frame`'s shape, and for the same two reasons. The object form is
    the only form, because the Editor reads the block with `.get("mode")` and a
    bare `"warn"` here would be a key nobody reads and a gate left at its
    `fail` default. `mode` is required, because a block that names nothing else
    and omits it states no opinion on the only thing it exists to state an
    opinion on.
    """
    kctx = f"{bctx}.{VIDEO_EDITOR_MEME_CAPTIONS_KEY}"
    modes = list(VIDEO_EDITOR_MEME_CAPTION_MODES)
    if not isinstance(block, dict):
        return [f"{kctx}: must be an object {{mode}} with `mode` one of {modes}, "
                f"got {block!r} - the Editor reads this block's `mode` key, so a bare "
                f"string is an unread key and leaves the gate at its default "
                f"({VIDEO_EDITOR_MEME_CAPTION_MODES[0]!r})"]
    errs = _unknown_key_errors(block, VIDEO_EDITOR_MEME_CAPTION_KNOWN_KEYS, kctx)
    if "mode" not in block:
        errs.append(f"{kctx}.mode: required, one of {modes}")
    elif block["mode"] not in VIDEO_EDITOR_MEME_CAPTION_MODES:
        errs.append(f"{kctx}.mode: must be one of {modes}, got {block['mode']!r}")
    return errs


def _validate_path_list(value, ctx):
    """Errors for a VIDEO_EDITOR_KIND_PATHS value - `ambient.beds` today.

    Three clauses, each one a typo that would otherwise be silent. A
    non-list, or a list with a non-string in it, is a config the reader cannot
    use and would fall through on (to the convention path, i.e. to a bed
    nobody chose). An *empty* list is the same silence spelled correctly: it
    reads as "this channel rotates its bed" and names nothing to rotate. A
    duplicate is the copy-paste that doubles one track's share of the rotation
    without saying so - the rotation would still run, and would simply be
    biased in a way nobody wrote down.

    What is not checked here is, as everywhere in this block, whether the
    files are on disk: see VIDEO_EDITOR_ASSET_KEYS. The render answers that,
    on the file system it will actually use.
    """
    if not isinstance(value, list):
        return [f"{ctx}: must be a list of path strings (relative to the factory "
                f"root, or absolute), got {value!r}"]
    if not value:
        return [f"{ctx}: is empty - a channel that names this key says its bed is "
                f"drawn from a list, and an empty list leaves the convention path "
                f"in place while reading as a decision. Leave the key out, or name "
                f"the files"]
    errs = []
    for i, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            errs.append(f"{ctx}[{i}]: must be a non-empty path string, got {item!r}")
    seen, dupes = set(), []
    for item in value:
        if isinstance(item, str):
            norm = item.strip()
            if norm in seen and norm not in dupes:
                dupes.append(norm)
            seen.add(norm)
    if dupes:
        errs.append(f"{ctx}: names {dupes} more than once - the list is a rotation, "
                    f"so a repeated entry silently gives that file a larger share of "
                    f"the videos than the others. Name each file once")
    return errs


def _validate_asset_override(block, key, bctx):
    """Errors for one `video_editor.<ambient|ending|end_card>` block.

    Shape only - see VIDEO_EDITOR_ASSET_KEYS for what is checked, what is not,
    and why the file's existence is the render's question and not this one's.
    """
    kctx = f"{bctx}.{key}"
    kinds = VIDEO_EDITOR_ASSET_KEYS[key]
    shape = "{" + ", ".join(f"{k}: <{kind}>" for k, kind in kinds.items()) + "}"
    if not isinstance(block, dict):
        return [f"{kctx}: must be an object {shape}, got {block!r}"]
    errs = _unknown_key_errors(block, tuple(kinds), kctx)
    named = [name for name in kinds if name in block]
    if not named:
        errs.append(f"{kctx}: names none of {list(kinds)} - {kctx} exists only to "
                    f"carry one of them, and a block that names none leaves the "
                    f"convention in place while reading as a decision")
    exclusive = VIDEO_EDITOR_EXCLUSIVE_KEYS.get(key, ())
    if len([n for n in exclusive if n in block]) > 1:
        errs.append(f"{kctx}: names both {list(exclusive)} - they are two different "
                    f"answers to the same question ('which file is the bed'), and a "
                    f"reader handed both would pick one of them silently. Name the "
                    f"single file, or the list it is drawn from, not both")
    for name in named:
        value = block[name]
        if kinds[name] == VIDEO_EDITOR_KIND_PATH:
            if not isinstance(value, str) or not value.strip():
                errs.append(f"{kctx}.{name}: must be a non-empty path string (relative "
                            f"to the factory root, or absolute), got {value!r}")
        elif kinds[name] == VIDEO_EDITOR_KIND_PATHS:
            errs += _validate_path_list(value, f"{kctx}.{name}")
        # CF-0165: the bed's level. Range and calibration belong to the reader
        # (ambient_bed.bed_db() refuses anything outside BED_DB_RANGE, loudly,
        # in the process that mixes); this is the shape check, and its job is
        # the typo - `"-25"`, `true`, `null` - that would otherwise read as
        # "no level stated" and mix 7 dB louder than the channel chose.
        elif not isinstance(value, (int, float)) or isinstance(value, bool):
            errs.append(f"{kctx}.{name}: must be a number in dB, got {value!r}")
    return errs


def _validate_comparison_line(block, bctx):
    """Errors for one `video_editor.comparison_line` block.

    A switch, not an override - see VIDEO_EDITOR_COMPARISON_LINE_KNOWN_KEYS for
    why nothing inside it is required and why an empty table is a decision.
    """
    kctx = f"{bctx}.{VIDEO_EDITOR_COMPARISON_LINE_KEY}"
    if not isinstance(block, dict):
        return [f"{kctx}: must be an object "
                f"{{publishers, platforms, enabled}}, got {block!r}"]
    errs = _unknown_key_errors(block, VIDEO_EDITOR_COMPARISON_LINE_KNOWN_KEYS, kctx)
    if "publishers" in block:
        table = block["publishers"]
        if not isinstance(table, dict):
            errs.append(f"{kctx}.publishers: must be an object "
                        f"{{host: the publication's own name}}, got {table!r}")
        else:
            for host, name in sorted(table.items()):
                if not isinstance(host, str) or not host.strip():
                    errs.append(f"{kctx}.publishers: host must be a non-empty string, "
                                f"got {host!r}")
                if not isinstance(name, str) or not name.strip():
                    errs.append(f"{kctx}.publishers[{host!r}]: the name drawn on the "
                                f"badge must be a non-empty string, got {name!r}")
    if "platforms" in block:
        hosts = block["platforms"]
        if not isinstance(hosts, list):
            errs.append(f"{kctx}.platforms: must be a list of hosts, got {hosts!r}")
        else:
            for host in hosts:
                if not isinstance(host, str) or not host.strip():
                    errs.append(f"{kctx}.platforms: every entry must be a non-empty "
                                f"host string, got {host!r}")
    if "enabled" in block and not isinstance(block["enabled"], bool):
        # Not truthiness: comparison_line.enabled() turns the line off on
        # `is False` and on nothing else, so `0` or `"false"` here would read
        # as "on" while the config says otherwise.
        errs.append(f"{kctx}.enabled: must be true or false, got "
                    f"{block['enabled']!r}. Leave the key out for the default (on)")
    return errs


def _shot_guard_module():
    """CF-0791: `shared/score/shot_guard.py`, the rule whose settings
    `video_editor.shot_guard` carries."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from shared.score import shot_guard  # noqa: PLC0415 - root's module
    return shot_guard


def _validate_shot_guard(block, bctx):
    """CF-0791: `video_editor.shot_guard`, by the module that reads it."""
    return _shot_guard_module().validate_config(
        block, f"{bctx}.{VIDEO_EDITOR_SHOT_GUARD_KEY}")


def validate_video_editor_block(cfg, ctx="channel"):
    """Errors for a channel config's `video_editor` block; [] when absent."""
    block = cfg.get(VIDEO_EDITOR_KEY)
    if block is None:
        return []
    bctx = f"{ctx}.{VIDEO_EDITOR_KEY}"
    if not isinstance(block, dict):
        return [f"{bctx}: must be an object"]
    errs = _unknown_key_errors(block, VIDEO_EDITOR_READ_KEYS, bctx)
    for key in (VIDEO_EDITOR_MAX_ATTEMPTS_KEY, VIDEO_EDITOR_MAX_QC_DEGRADES_KEY):
        if key in block:
            cap = block[key]
            if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
                errs.append(f"{bctx}.{key}: must be an integer >= 1, got {cap!r}")
    if VIDEO_EDITOR_TWO_SOURCE_GATE_KEY in block:
        errs += _validate_two_source_gate(block[VIDEO_EDITOR_TWO_SOURCE_GATE_KEY], bctx)
    if VIDEO_EDITOR_PANEL_IN_FRAME_KEY in block:
        errs += _validate_panel_in_frame(block[VIDEO_EDITOR_PANEL_IN_FRAME_KEY], bctx)
    if VIDEO_EDITOR_MEME_CAPTIONS_KEY in block:
        errs += _validate_meme_captions(block[VIDEO_EDITOR_MEME_CAPTIONS_KEY], bctx)
    if VIDEO_EDITOR_SHOT_GUARD_KEY in block:
        errs += _validate_shot_guard(block[VIDEO_EDITOR_SHOT_GUARD_KEY], bctx)
    if VIDEO_EDITOR_QC_COSMETIC_RULES_KEY in block:
        errs += _validate_qc_cosmetic_rules(block[VIDEO_EDITOR_QC_COSMETIC_RULES_KEY], bctx)
    if VIDEO_EDITOR_MAX_STILL_SHARE_KEY in block:
        errs += _validate_max_still_share(block[VIDEO_EDITOR_MAX_STILL_SHARE_KEY], bctx)
    for key in VIDEO_EDITOR_ASSET_KEYS:
        if key in block:
            errs += _validate_asset_override(block[key], key, bctx)
    if VIDEO_EDITOR_COMPARISON_LINE_KEY in block:
        errs += _validate_comparison_line(block[VIDEO_EDITOR_COMPARISON_LINE_KEY], bctx)
    if VIDEO_EDITOR_LOUDNESS_KEY in block:
        errs += _validate_loudness(block[VIDEO_EDITOR_LOUDNESS_KEY], bctx)
    return errs


# --------------------------------------------------------------------------
# CF-0374: who answers the Footage Indexer's open sieve flags
# --------------------------------------------------------------------------
# The sieve (agents/footage-indexer/scripts/source_sieve.py) marks a reused
# source's `burned_text` / `on_topic` itself before it judges the batch, and
# the command that does the marking is configured rather than typed:
#
#     channels/<channel>.json -> footage_indexer.sieve_flags_answer_cmd
#
# read by `source_sieve.answer_cmd_from_config()`. A bare string is the
# command; the object form is `{"command": ..., "timeout_seconds": N}`, the
# shape `sources.youtube.max_source_duration_seconds` already uses, so the
# ceiling on one source's answerer can live beside the command. Both forms are
# read, which is why - unlike `video_editor.panel_in_frame` (CF-0327) - the
# flat one is legal here: there a bare string was an unread key, here it is
# the documented short form.
#
# What is *not* legal is a block without `command`: the reader takes the
# command off that field and nothing else, so a block naming only a timeout
# configures no answerer while reading as one - the silent misreading this
# schema exists to catch (CF-0161, CF-0191).
#
# The key absent is legal (CF-0374, 2026-09-24): with no answerer the sieve
# marks nothing, takes the unanswered sources out of the batch with an
# `index_failed` record, and the run goes on (DoD 1). An absent key is
# therefore not an error here and must never become one - that would turn a
# legal state into a broken config. Since CF-0478 (2026-10-02) example-film
# sets it to the indexer's headless answerer, scripts/sieve_answer_claude.py.
FOOTAGE_INDEXER_KEY = "footage_indexer"
FOOTAGE_INDEXER_ANSWER_CMD_KEY = "sieve_flags_answer_cmd"
# CF-0419 (the user's decision of 2026-09-28): the source floor's own switch,
# read by agents/footage-indexer/scripts/ingest_batch.py floor_mode() and by
# shared/runlog/triage.py mode_of() at this exact path. A string or {"mode"}.
FOOTAGE_INDEXER_NO_SECOND_SOURCE_KEY = "no_second_source"
NO_SECOND_SOURCE_MODES = ("warn", "measure", "off", "enforce", "fail", "refuse")
FOOTAGE_INDEXER_READ_KEYS = (FOOTAGE_INDEXER_ANSWER_CMD_KEY,
                             FOOTAGE_INDEXER_NO_SECOND_SOURCE_KEY)
ANSWER_CMD_COMMAND_FIELD = "command"
ANSWER_CMD_TIMEOUT_FIELD = "timeout_seconds"
ANSWER_CMD_KNOWN_KEYS = (ANSWER_CMD_COMMAND_FIELD, ANSWER_CMD_TIMEOUT_FIELD)


def _validate_sieve_answer_cmd(value, bctx):
    """Errors for one `footage_indexer.sieve_flags_answer_cmd` value."""
    kctx = f"{bctx}.{FOOTAGE_INDEXER_ANSWER_CMD_KEY}"
    if isinstance(value, str):
        if not value.strip():
            return [f"{kctx}: is empty - the indexer reads an empty command as no "
                    f"answerer at all, which is what leaving the key out already "
                    f"says. Name the command, or leave the key out"]
        return []
    if not isinstance(value, dict):
        return [f"{kctx}: must be a command string, or an object "
                f"{{{ANSWER_CMD_COMMAND_FIELD}, {ANSWER_CMD_TIMEOUT_FIELD}}} - got "
                f"{value!r}, which the indexer ignores "
                f"(source_sieve.answer_cmd_from_config)"]
    errs = _block_unknown_keys(value, ANSWER_CMD_KNOWN_KEYS, kctx,
                               "the sieve-flag answerer")
    cmd = value.get(ANSWER_CMD_COMMAND_FIELD)
    if ANSWER_CMD_COMMAND_FIELD not in value:
        errs.append(f"{kctx}.{ANSWER_CMD_COMMAND_FIELD}: required - the indexer takes "
                    f"the command off this field and nothing else, so a block without "
                    f"it configures no answerer while reading as one")
    elif not isinstance(cmd, str) or not cmd.strip():
        errs.append(f"{kctx}.{ANSWER_CMD_COMMAND_FIELD}: must be a non-empty command "
                    f"string, got {cmd!r}")
    if ANSWER_CMD_TIMEOUT_FIELD in value:
        t = value[ANSWER_CMD_TIMEOUT_FIELD]
        if not isinstance(t, int) or isinstance(t, bool) or t <= 0:
            errs.append(f"{kctx}.{ANSWER_CMD_TIMEOUT_FIELD}: must be a whole number of "
                        f"seconds > 0 - the ceiling on one source's answerer - got "
                        f"{t!r}")
    return errs


def validate_footage_indexer_block(cfg, ctx="channel"):
    """Errors for a channel config's `footage_indexer` block; [] when absent.

    Absent is the default and means the sieve has no answerer: legal (CF-0374).
    example-film names the indexer's headless answerer since CF-0478."""
    block = cfg.get(FOOTAGE_INDEXER_KEY)
    if block is None:
        return []
    bctx = f"{ctx}.{FOOTAGE_INDEXER_KEY}"
    if not isinstance(block, dict):
        return [f"{bctx}: must be an object"]
    errs = _block_unknown_keys(block, FOOTAGE_INDEXER_READ_KEYS, bctx,
                               "the Footage Indexer's channel setting")
    if FOOTAGE_INDEXER_ANSWER_CMD_KEY in block:
        errs += _validate_sieve_answer_cmd(block[FOOTAGE_INDEXER_ANSWER_CMD_KEY], bctx)
    if FOOTAGE_INDEXER_NO_SECOND_SOURCE_KEY in block:
        v = block[FOOTAGE_INDEXER_NO_SECOND_SOURCE_KEY]
        kctx = f"{bctx}.{FOOTAGE_INDEXER_NO_SECOND_SOURCE_KEY}"
        if isinstance(v, dict):
            errs += _block_unknown_keys(v, ("mode",), kctx, "the source floor's switch")
            v = v.get("mode")
        if v not in NO_SECOND_SOURCE_MODES:
            errs.append(f"{kctx}: mode must be one of {list(NO_SECOND_SOURCE_MODES)}, "
                        f"got {v!r} - the indexer falls through a value it cannot "
                        f"read, so a typo here would silently run another mode")
    return errs


# --------------------------------------------------------------------------
# CF-0411: the Content Researcher's channel block - the plan check's ceiling
# --------------------------------------------------------------------------
# The user's decision of 2026-09-28 (batch example-film/2026-09-27T0929Z, 0
# videos): a script does not leave the Researcher for compliance-2 until the
# Video Editor's own gates have built a plan out of it (TTS -> resolve -> plan,
# no render), with rounds of editing the `visual_anchors` only - 1-2 at first,
# 3 since the user's CF-0430 option A (2026-09-28); a rerun on a script whose
# text and anchors did not change spends no round. The ceiling
# on those rounds is this channel key, read by
# agents/content-researcher/scripts/plan_check_loop.py (`rounds_allowed`),
# which is outside this repository - so, as with CF-0374's key above, this
# schema is the only place a typo in it is caught before a run reads past it.
#
# Absent is legal and means the reader's default (3, plan_check_loop.DEFAULT_ROUNDS). The reader falls back to
# that default on a value it cannot use rather than refusing to run, which is
# exactly why a wrong value has to be caught here: a `"2"` or a `-1` would run
# the default and look like the channel's own setting. 0 is legal - one check,
# no anchor-edit round, an unassembled script is dropped at once.
CONTENT_RESEARCHER_KEY = "content_researcher"
CONTENT_RESEARCHER_PLAN_CHECK_ROUNDS_KEY = "plan_check_rounds"
CONTENT_RESEARCHER_DEFAULT_PLAN_CHECK_ROUNDS = 3
# CF-0424 (the user's idea and decision of 2026-09-28): the channel's library of
# hook openers - 15-20 formulas ('The most talked-about {x}...', 'Nobody
# noticed...') the writer picks one from and fills with the topic's specifics -
# and the rotation gap: one opener at most once in every N consecutive videos,
# so the channel does not read as a template. Both are read by
# agents/content-researcher (outside this repository), so, as with the round
# ceiling above, a typo is caught here or not at all: an opener without an id
# cannot be rotated, two openers under one id rotate as one, an empty template
# gives the writer nothing, and a gap of `"5"` would run as the reader's default.
# Absent is legal: no library means the writer opens freely, as before.
CONTENT_RESEARCHER_HOOK_OPENERS_KEY = "hook_openers"
CONTENT_RESEARCHER_HOOK_OPENER_GAP_KEY = "hook_opener_min_gap_videos"
CONTENT_RESEARCHER_DEFAULT_HOOK_OPENER_GAP = 5
CONTENT_RESEARCHER_HOOK_OPENER_KEYS = ("id", "template")
# CF-0578 (the root half of CF-0542, the user's remark of 2026-10-05 on
# vanguards-endgame 0701Z: three figures in one sentence): the ceiling on how
# many figures a narration may carry - per sentence and per 10 words - and
# what the writer's check does over it. Read by
# agents/content-researcher/scripts/check_number_density.py::settings (outside
# this repository) at `content_researcher.number_density`; absent means the
# reader's defaults (measure, 1, 0.4), and so does each sub-key left out. The
# reader keeps an unknown mode as its default `measure` and passes a number
# through unchecked, so an `"enforce "` would read as the channel's choice
# while measuring, and a `"1"` or `-1` would break or invert the threshold -
# caught here. `measure` warns, `enforce` makes the writer rewrite the named
# sentences once (never drops the topic), `off` skips the check.
CONTENT_RESEARCHER_NUMBER_DENSITY_KEY = "number_density"
CONTENT_RESEARCHER_NUMBER_DENSITY_MODES = ("measure", "enforce", "off")
CONTENT_RESEARCHER_NUMBER_DENSITY_PER_SENTENCE_KEY = "max_figures_per_sentence"
CONTENT_RESEARCHER_NUMBER_DENSITY_PER_10_WORDS_KEY = "max_figures_per_10_words"
CONTENT_RESEARCHER_NUMBER_DENSITY_READ_KEYS = (
    "mode",
    CONTENT_RESEARCHER_NUMBER_DENSITY_PER_SENTENCE_KEY,
    CONTENT_RESEARCHER_NUMBER_DENSITY_PER_10_WORDS_KEY,
)
# CF-0845 (the user's signature of 2026-10-21, Q8): the floor of a script's
# pool - a topic whose pool holds fewer clean usable shots than this
# (01b pool_depth.topics[].usable_shots) is taken out before the first plan
# check as `pool_too_thin` and its supplement request is closed `too_thin`
# without a search. Read by shared/runlog/thin_topic.py; absent means the
# reader's default 10, 0 switches the rule off. The reader falls back to the
# default on a value it cannot use, so a `"10"` or a `-1` is caught here.
CONTENT_RESEARCHER_MIN_USABLE_SHOTS_KEY = "min_usable_shots_for_script"
CONTENT_RESEARCHER_DEFAULT_MIN_USABLE_SHOTS = 10
CONTENT_RESEARCHER_READ_KEYS = (
    CONTENT_RESEARCHER_PLAN_CHECK_ROUNDS_KEY,
    CONTENT_RESEARCHER_HOOK_OPENERS_KEY,
    CONTENT_RESEARCHER_HOOK_OPENER_GAP_KEY,
    CONTENT_RESEARCHER_NUMBER_DENSITY_KEY,
    CONTENT_RESEARCHER_MIN_USABLE_SHOTS_KEY,
)


def validate_content_researcher_block(cfg, ctx="channel"):
    """Errors for a channel config's `content_researcher` block; [] when absent."""
    block = cfg.get(CONTENT_RESEARCHER_KEY)
    if block is None:
        return []
    bctx = f"{ctx}.{CONTENT_RESEARCHER_KEY}"
    if not isinstance(block, dict):
        return [f"{bctx}: must be an object"]
    errs = _block_unknown_keys(block, CONTENT_RESEARCHER_READ_KEYS, bctx,
                               "the Content Researcher's channel setting")
    if CONTENT_RESEARCHER_PLAN_CHECK_ROUNDS_KEY in block:
        n = block[CONTENT_RESEARCHER_PLAN_CHECK_ROUNDS_KEY]
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errs.append(
                f"{bctx}.{CONTENT_RESEARCHER_PLAN_CHECK_ROUNDS_KEY}: must be a whole number "
                f">= 0 - the anchor-edit rounds plan_check_loop.py allows before it drops "
                f"a script as `plan_unassembled` (CF-0411) - got {n!r}, which the reader "
                f"would silently replace with its default "
                f"{CONTENT_RESEARCHER_DEFAULT_PLAN_CHECK_ROUNDS}")
    if CONTENT_RESEARCHER_HOOK_OPENERS_KEY in block:
        errs += _hook_opener_errors(block[CONTENT_RESEARCHER_HOOK_OPENERS_KEY],
                                    f"{bctx}.{CONTENT_RESEARCHER_HOOK_OPENERS_KEY}")
    if CONTENT_RESEARCHER_HOOK_OPENER_GAP_KEY in block:
        n = block[CONTENT_RESEARCHER_HOOK_OPENER_GAP_KEY]
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errs.append(
                f"{bctx}.{CONTENT_RESEARCHER_HOOK_OPENER_GAP_KEY}: must be a whole number "
                f">= 0 - the number of consecutive videos one hook opener may appear in "
                f"at most once (CF-0424; 0 turns the rotation off) - got {n!r}, which the "
                f"reader would silently replace with its default "
                f"{CONTENT_RESEARCHER_DEFAULT_HOOK_OPENER_GAP}")
    if CONTENT_RESEARCHER_NUMBER_DENSITY_KEY in block:
        errs += _number_density_errors(block[CONTENT_RESEARCHER_NUMBER_DENSITY_KEY],
                                       f"{bctx}.{CONTENT_RESEARCHER_NUMBER_DENSITY_KEY}")
    if CONTENT_RESEARCHER_MIN_USABLE_SHOTS_KEY in block:
        n = block[CONTENT_RESEARCHER_MIN_USABLE_SHOTS_KEY]
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errs.append(
                f"{bctx}.{CONTENT_RESEARCHER_MIN_USABLE_SHOTS_KEY}: must be a whole number "
                f">= 0 - the fewest clean usable shots a topic's pool must hold to be "
                f"written and to get a supplement (CF-0845; 0 turns the rule off) - got "
                f"{n!r}, which the reader would silently replace with its default "
                f"{CONTENT_RESEARCHER_DEFAULT_MIN_USABLE_SHOTS}")
    return errs


def _number_density_errors(nd, ctx):
    """CF-0578: `{mode, max_figures_per_sentence, max_figures_per_10_words}`,
    each optional (the reader's default fills it), nothing else but prose."""
    if not isinstance(nd, dict):
        return [f"{ctx}: must be an object with "
                f"{list(CONTENT_RESEARCHER_NUMBER_DENSITY_READ_KEYS)} - got {nd!r}"]
    errs = _block_unknown_keys(nd, CONTENT_RESEARCHER_NUMBER_DENSITY_READ_KEYS, ctx,
                               "the writer's number-density check")
    if "mode" in nd and nd["mode"] not in CONTENT_RESEARCHER_NUMBER_DENSITY_MODES:
        errs.append(f"{ctx}.mode: must be one of "
                    f"{list(CONTENT_RESEARCHER_NUMBER_DENSITY_MODES)} - got {nd['mode']!r}, "
                    f"which check_number_density.py would silently run as `measure`")
    k = CONTENT_RESEARCHER_NUMBER_DENSITY_PER_SENTENCE_KEY
    if k in nd:
        n = nd[k]
        if not isinstance(n, int) or isinstance(n, bool) or n < 0:
            errs.append(f"{ctx}.{k}: must be a whole number >= 0 - the most figures one "
                        f"sentence may carry (CF-0542) - got {n!r}")
    k = CONTENT_RESEARCHER_NUMBER_DENSITY_PER_10_WORDS_KEY
    if k in nd:
        x = nd[k]
        if not isinstance(x, (int, float)) or isinstance(x, bool) or x != x or x < 0 \
                or x == float("inf"):
            errs.append(f"{ctx}.{k}: must be a finite number >= 0 - figures per 10 words "
                        f"of the whole narration (CF-0542) - got {x!r}")
    return errs


def _hook_opener_errors(openers, ctx):
    """CF-0424: the library is a non-empty list of {id, template}, ids unique
    (kebab-case, since the id is what the rotation counts and what a script
    records), every template a non-empty string."""
    if not isinstance(openers, list) or not openers:
        return [f"{ctx}: must be a non-empty list of {{'id', 'template'}} objects - an "
                f"empty library is written by leaving the key out"]
    errs, seen = [], set()
    for i, op in enumerate(openers):
        octx = f"{ctx}[{i}]"
        if not isinstance(op, dict):
            errs.append(f"{octx}: must be an object with {list(CONTENT_RESEARCHER_HOOK_OPENER_KEYS)}")
            continue
        unknown = sorted(k for k in op if k not in CONTENT_RESEARCHER_HOOK_OPENER_KEYS)
        if unknown:
            errs.append(f"{octx}: unknown key(s) {unknown} - an opener is "
                        f"{list(CONTENT_RESEARCHER_HOOK_OPENER_KEYS)}")
        oid = op.get("id")
        if not isinstance(oid, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", oid):
            errs.append(f"{octx}.id: must be a kebab-case string - it is what the rotation "
                        f"counts and what 03 -> scripts[].hook_opener_id records - got {oid!r}")
        elif oid in seen:
            errs.append(f"{octx}.id: {oid!r} is used twice - two openers under one id "
                        f"would rotate as one")
        else:
            seen.add(oid)
        tpl = op.get("template")
        if not isinstance(tpl, str) or not tpl.strip():
            errs.append(f"{octx}.template: must be a non-empty string - got {tpl!r}")
    return errs


# --------------------------------------------------------------------------
# CF-0426: the thin-pool supplement step's wall-clock ceiling
# --------------------------------------------------------------------------
# The user's decision of 2026-09-28: the supplement step (CF-0345) stays, with
# a ceiling of 30 minutes of wall clock per batch. Read by
# shared/runlog/supplement.py::wall_ceiling_seconds at
# `channels/<channel>.json -> supplement.max_wall_seconds`; absent means the
# reader's default (1800). The reader falls back to that default on a value it
# cannot use, so a `"1800"` or a `0` would run as the default while reading as
# the channel's own setting - caught here, in the one loop that walks every
# channel config.
SUPPLEMENT_KEY = "supplement"
SUPPLEMENT_MAX_WALL_SECONDS_KEY = "max_wall_seconds"
SUPPLEMENT_DEFAULT_MAX_WALL_SECONDS = 1800
# CF-0842: the channel's switch of the step (absent = on); `false` closes every
# request without a search or a fetch (shared/runlog/supplement.py).
SUPPLEMENT_ENABLED_KEY = "enabled"
SUPPLEMENT_READ_KEYS = (SUPPLEMENT_MAX_WALL_SECONDS_KEY, SUPPLEMENT_ENABLED_KEY)


def validate_supplement_block(cfg, ctx="channel"):
    """Errors for a channel config's `supplement` block; [] when absent."""
    block = cfg.get(SUPPLEMENT_KEY)
    if block is None:
        return []
    bctx = f"{ctx}.{SUPPLEMENT_KEY}"
    if not isinstance(block, dict):
        return [f"{bctx}: must be an object"]
    errs = _block_unknown_keys(block, SUPPLEMENT_READ_KEYS, bctx,
                               "the thin-pool supplement step's channel setting")
    if SUPPLEMENT_MAX_WALL_SECONDS_KEY in block:
        n = block[SUPPLEMENT_MAX_WALL_SECONDS_KEY]
        if not isinstance(n, int) or isinstance(n, bool) or n <= 0:
            errs.append(
                f"{bctx}.{SUPPLEMENT_MAX_WALL_SECONDS_KEY}: must be a whole number of "
                f"seconds > 0 - the wall-clock ceiling of the supplement step per batch "
                f"(CF-0426) - got {n!r}, which the reader would silently replace with "
                f"its default {SUPPLEMENT_DEFAULT_MAX_WALL_SECONDS}")
    if SUPPLEMENT_ENABLED_KEY in block and not isinstance(block[SUPPLEMENT_ENABLED_KEY], bool):
        errs.append(
            f"{bctx}.{SUPPLEMENT_ENABLED_KEY}: must be true or false - the channel's "
            f"switch of the supplement step (CF-0842) - got "
            f"{block[SUPPLEMENT_ENABLED_KEY]!r}, which the reader would read as on")
    return errs


def load_video_editor_settings(channel):
    """The channel's `video_editor` block with the default filled in, or a
    ValueError naming what the Editor would refuse. Absent = the default cap
    and the default gate mode, the same reading
    agents/video-editor/scripts/{attempts,source_gate}.py make."""
    path = narration_budget_file(channel)
    if not path.exists():
        raise FileNotFoundError(f"no channel config at {path}")
    cfg = json.loads(path.read_text())
    errs = validate_video_editor_block(cfg, ctx=path.name)
    if errs:
        raise ValueError("; ".join(errs))
    settings = dict(cfg.get(VIDEO_EDITOR_KEY) or {})
    settings.setdefault(VIDEO_EDITOR_MAX_ATTEMPTS_KEY, VIDEO_EDITOR_DEFAULT_MAX_ATTEMPTS)
    settings.setdefault(VIDEO_EDITOR_TWO_SOURCE_GATE_KEY,
                        VIDEO_EDITOR_DEFAULT_TWO_SOURCE_GATE)
    return settings


# --------------------------------------------------------------------------
# CF-0190: the blooper rights relaxation, and why its borders have a schema
# --------------------------------------------------------------------------
# The user decided on 2026-09-11 that this channel may show on-set bloopers -
# studio material end to end, without one frame of our own in it - with the
# rights-holder check relaxed for them, inside four borders: a fragment no
# longer than 3 s, a voice-over over it, a piece rather than a whole gag, and
# nothing else in the pipeline touched. `channels/<channel>.json` ->
# `blooper_rights_relaxation` is where a channel writes that down, and this is
# the schema that judges the block. Two agents read it and neither is in this
# repository (agents/compliance-checker, agents/video-editor), which is
# exactly why the borders are checked here: a contract two separate repos read
# and nobody validates drifts the way CF-0165 and CF-0166 drifted from the
# `video_editor` schema for three days (CF-0191).
#
# What this schema does that a key list would not:
#
#   * Every key is required, switched on or off alike. A relaxation recorded
#     without its date, its reason or its borders is the thing the project's
#     own rule ("every relaxation is recorded rather than hidden") forbids,
#     and `enabled: false` is not an excuse to leave them out - the block is
#     the record, not the switch.
#   * The two numbers are ceilings, not defaults. A channel may write a
#     stricter fragment length or a stricter silence than the decision took;
#     it may not write a looser one. Anything else and the relaxation widens
#     itself in a config edit nobody grills.
#   * `narration_over_fragment.required` must be `true` and
#     `not_the_whole_gag.machine_checkable` must be `false`. Both are pinned
#     to one value on purpose, and for opposite reasons. The first is a border
#     of the decision, not a knob: a config writing `false` there would be
#     switching off the half of the relaxation the user was most explicit
#     about. The second is a statement of fact about this repository - nothing
#     here can tell a piece of a gag from a whole one - and a config claiming
#     `true` would be claiming a check that does not exist, which is the
#     `gate honesty` failure the block's own prose is about.
#   * `does_not_touch` has to name the rights-holder list
#     (`rights-holder-blacklist.json` - the channel's, CF-0561).
#     "The blacklist is not touched" is an acceptance criterion of CF-0190 and
#     the one sentence a later reader most needs to find in the block.
BLOOPER_KEY = "blooper_rights_relaxation"
BLOOPER_READ_KEYS = ("enabled", "decided_on", "recorded_by", "reason", "marker",
                     "max_fragment_seconds", "narration_over_fragment",
                     "not_the_whole_gag", "applies_to", "does_not_touch",
                     "read_by")
BLOOPER_MARKER_KEYS = ("field", "required_keys", "carried_on", "absent_or_malformed")
BLOOPER_NARRATION_KEYS = ("required", "max_silent_seconds", "words_source")
BLOOPER_GAG_KEYS = ("machine_checkable", "attested_by", "min_chars", "held_by")
BLOOPER_READER_KEYS = ("compliance_checker", "video_editor")
# The decision's own numbers, as ceilings on what any channel may write.
BLOOPER_MAX_FRAGMENT_CEILING = 3.0
BLOOPER_MAX_SILENT_CEILING = 0.5
# The marker key that carries the one border no machine checks.
BLOOPER_ATTESTATION_KEY = "not_whole_gag"
BLOOPER_BLACKLIST_NAME = "rights-holder-blacklist.json"
# A channel that wrote no block has no relaxation, the same reading
# agents/video-editor/scripts/assetless_rung.py makes of its own switch.
BLOOPER_DEFAULT_ENABLED = False
BLOOPER_PROSE_MIN_CHARS = 40
BLOOPER_LONG_PROSE_MIN_CHARS = 160
BLOOPER_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _block_unknown_keys(block, read_keys, ctx, noun="the relaxation"):
    """The same strict rule the `video_editor` block uses - the listed keys
    plus `note` and `<key>_note` prose - with a message that names the right
    reader. Kept separate from `_unknown_key_errors` for that reason only.

    `noun` is what the block is, so that the message reads correctly for each
    of the channel-level blocks that share these helpers (CF-0190's
    relaxation, CF-0185's refusal rule)."""
    known = tuple(read_keys) + _video_editor_prose_keys(read_keys)
    unknown = sorted(k for k in block if k not in known)
    if not unknown:
        return []
    return [f"{ctx}: unknown key(s) {unknown} - {noun} is written in "
            f"{list(read_keys)} (beside {VIDEO_EDITOR_NOTE_KEY!r} and "
            f"'<key>{VIDEO_EDITOR_NOTE_SUFFIX}' prose)"]


def _block_required(block, keys, ctx, noun="a relaxation"):
    """Every key of the block is required - see the note above."""
    return [f"{ctx}.{k}: required - {noun} is recorded whole or not at "
            f"all, `enabled: false` included" for k in keys if k not in block]


def _block_prose(errs, block, key, ctx, min_chars=BLOOPER_PROSE_MIN_CHARS):
    """A required non-empty prose string, long enough not to be a stub."""
    if key not in block:
        return False
    value = block[key]
    if not isinstance(value, str) or len(value.strip()) < min_chars:
        errs.append(f"{ctx}.{key}: must be at least {min_chars} characters of "
                    f"prose, got {value!r}")
        return False
    return True


def _blooper_number(errs, block, key, ctx, ceiling, floor=0.0, strict_floor=False):
    """A number inside the band the decision set. The ceiling is the
    decision's own value: stricter is a channel's business, looser is not."""
    if key not in block:
        return
    value = block[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        errs.append(f"{ctx}.{key}: must be a number, got {value!r}")
        return
    if (value <= floor) if strict_floor else (value < floor):
        errs.append(f"{ctx}.{key}: must be "
                    f"{'>' if strict_floor else '>='} {floor}, got {value!r}")
    if value > ceiling:
        errs.append(f"{ctx}.{key}: {value!r} is looser than the decision of "
                    f"2026-09-11, whose value is {ceiling}. A channel may be "
                    f"stricter than the relaxation, never looser - widening it "
                    f"is a decision to be taken again, not a config edit")


def _block_pinned(errs, block, key, ctx, expected, why):
    """A key pinned to one value, with the reason in the message."""
    if key not in block:
        return
    if block[key] is not expected:
        errs.append(f"{ctx}.{key}: must be {str(expected).lower()} - {why} "
                    f"(got {block[key]!r})")


def _validate_blooper_marker(marker, bctx):
    """The marker contract both agents read: what makes material a blooper."""
    mctx = f"{bctx}.marker"
    if not isinstance(marker, dict):
        return [f"{mctx}: must be an object"], None
    errs = _block_unknown_keys(marker, BLOOPER_MARKER_KEYS, mctx)
    errs += _block_required(marker, BLOOPER_MARKER_KEYS, mctx)
    field = marker.get("field")
    if "field" in marker and (not isinstance(field, str) or not field.strip()
                              or field.strip() != field):
        errs.append(f"{mctx}.field: must be the non-empty, unpadded name of the "
                    f"key that marks the material, got {field!r}")
        field = None
    required = marker.get("required_keys")
    if "required_keys" in marker:
        if (not isinstance(required, list) or not required
                or any(not isinstance(k, str) or not k.strip() for k in required)):
            errs.append(f"{mctx}.required_keys: must be a non-empty list of key "
                        f"names, got {required!r}")
            required = None
        elif BLOOPER_ATTESTATION_KEY not in required:
            errs.append(f"{mctx}.required_keys: must contain "
                        f"{BLOOPER_ATTESTATION_KEY!r} - it carries the one border "
                        f"no machine checks, and a marker that may omit it turns "
                        f"that border into nothing at all")
            required = None
    for key in ("carried_on", "absent_or_malformed"):
        _block_prose(errs, marker, key, mctx, BLOOPER_LONG_PROSE_MIN_CHARS)
    return errs, (field if isinstance(field, str) else None,
                  required if isinstance(required, list) else None)


def _validate_blooper_narration(node, bctx):
    """The border that says a blooper never runs without a voice over it."""
    nctx = f"{bctx}.narration_over_fragment"
    if not isinstance(node, dict):
        return [f"{nctx}: must be an object"]
    errs = _block_unknown_keys(node, BLOOPER_NARRATION_KEYS, nctx)
    errs += _block_required(node, BLOOPER_NARRATION_KEYS, nctx)
    _block_pinned(errs, node, "required", nctx, True,
                    "a blooper with no commentary over it does not pass, and "
                    "that is a border of the decision of 2026-09-11 rather "
                    "than a knob a channel sets")
    _blooper_number(errs, node, "max_silent_seconds", nctx,
                    BLOOPER_MAX_SILENT_CEILING, floor=0.0)
    _block_prose(errs, node, "words_source", nctx, BLOOPER_LONG_PROSE_MIN_CHARS)
    return errs


def _validate_blooper_gag(node, bctx, field, required_keys):
    """The border that is not machine-checkable, and says so in the config."""
    gctx = f"{bctx}.not_the_whole_gag"
    if not isinstance(node, dict):
        return [f"{gctx}: must be an object"]
    errs = _block_unknown_keys(node, BLOOPER_GAG_KEYS, gctx)
    errs += _block_required(node, BLOOPER_GAG_KEYS, gctx)
    _block_pinned(errs, node, "machine_checkable", gctx, False,
                    "nothing in this repository can tell a piece of a gag from "
                    "a whole one, and a config claiming otherwise would be "
                    "claiming a check that does not exist")
    attested = node.get("attested_by")
    if "attested_by" in node:
        legal = ([f"{field}.{k}" for k in required_keys]
                 if field and required_keys else None)
        if not isinstance(attested, str) or (legal and attested not in legal):
            errs.append(f"{gctx}.attested_by: must name a key of the marker"
                        + (f" - one of {legal}" if legal else "")
                        + f", got {attested!r}")
    if "min_chars" in node:
        mc = node["min_chars"]
        if not isinstance(mc, int) or isinstance(mc, bool) or mc < 1:
            errs.append(f"{gctx}.min_chars: must be an integer >= 1 - it is the "
                        f"length below which the attestation is a stub, got {mc!r}")
    _block_prose(errs, node, "held_by", gctx, BLOOPER_LONG_PROSE_MIN_CHARS)
    return errs


def validate_blooper_relaxation_block(cfg, ctx="channel"):
    """Errors for a channel config's `blooper_rights_relaxation` block; [] when
    the channel wrote none, which is the default and means no relaxation."""
    block = cfg.get(BLOOPER_KEY)
    if block is None:
        return []
    bctx = f"{ctx}.{BLOOPER_KEY}"
    if not isinstance(block, dict):
        return [f"{bctx}: must be an object"]
    errs = _block_unknown_keys(block, BLOOPER_READ_KEYS, bctx)
    errs += _block_required(block, BLOOPER_READ_KEYS, bctx)
    if "enabled" in block and not isinstance(block["enabled"], bool):
        errs.append(f"{bctx}.enabled: must be true or false, got "
                    f"{block['enabled']!r}. There is no third state and no "
                    f"default: an unreadable switch is not a switched-on one")
    if "decided_on" in block:
        when = block["decided_on"]
        if not isinstance(when, str) or not BLOOPER_DATE_RE.match(when):
            errs.append(f"{bctx}.decided_on: must be an ISO date (YYYY-MM-DD) - "
                        f"'when' is an acceptance criterion of CF-0190, got {when!r}")
    _block_prose(errs, block, "recorded_by", bctx, 1)
    _block_prose(errs, block, "reason", bctx, BLOOPER_LONG_PROSE_MIN_CHARS)
    _block_prose(errs, block, "applies_to", bctx, BLOOPER_PROSE_MIN_CHARS)
    field = required_keys = None
    if "marker" in block:
        merrs, names = _validate_blooper_marker(block["marker"], bctx)
        errs += merrs
        if names:
            field, required_keys = names
    _blooper_number(errs, block, "max_fragment_seconds",
                    bctx, BLOOPER_MAX_FRAGMENT_CEILING, floor=0.0,
                    strict_floor=True)
    if "narration_over_fragment" in block:
        errs += _validate_blooper_narration(block["narration_over_fragment"], bctx)
    if "not_the_whole_gag" in block:
        errs += _validate_blooper_gag(block["not_the_whole_gag"], bctx,
                                      field, required_keys)
    if "does_not_touch" in block:
        untouched = block["does_not_touch"]
        if (not isinstance(untouched, list) or len(untouched) < 2
                or any(not isinstance(s, str)
                       or len(s.strip()) < BLOOPER_PROSE_MIN_CHARS
                       for s in untouched)):
            errs.append(f"{bctx}.does_not_touch: must be a list of at least two "
                        f"prose lines naming what the relaxation leaves alone, "
                        f"got {untouched!r}")
        elif not any(BLOOPER_BLACKLIST_NAME in s for s in untouched):
            errs.append(f"{bctx}.does_not_touch: none of these lines names "
                        f"{BLOOPER_BLACKLIST_NAME!r}. That the blacklist is left "
                        f"alone is an acceptance criterion of CF-0190 and has to "
                        f"be readable here")
    if "read_by" in block:
        readers = block["read_by"]
        rctx = f"{bctx}.read_by"
        if not isinstance(readers, dict):
            errs.append(f"{rctx}: must be an object of reader -> what it reads")
        else:
            errs += _block_unknown_keys(readers, BLOOPER_READER_KEYS, rctx)
            errs += _block_required(readers, BLOOPER_READER_KEYS, rctx)
            for key in BLOOPER_READER_KEYS:
                _block_prose(errs, readers, key, rctx,
                               BLOOPER_LONG_PROSE_MIN_CHARS)
    return errs


def blooper_relaxation(cfg):
    """The relaxation a channel config grants, or None.

    None when the block is absent, unreadable, or switched off - the same
    fail-closed reading agents/video-editor/scripts/assetless_rung.py makes of
    its own switch, and the reading both CF-0190 agents are contracted to
    make. Legality is the root's business (`validate_blooper_relaxation_block`
    through `inserts/validate_inserts.py`), not a reader's: an agent that met
    an illegal block would relax nothing, which is the safe direction.
    """
    if not isinstance(cfg, dict):
        return None
    block = cfg.get(BLOOPER_KEY)
    if not isinstance(block, dict):
        return None
    if block.get("enabled", BLOOPER_DEFAULT_ENABLED) is not True:
        return None
    if validate_blooper_relaxation_block(cfg):
        return None
    return block


def load_blooper_relaxation(channel):
    """`blooper_relaxation()` for a channel by id; None when it grants none."""
    path = narration_budget_file(channel)
    if not path.exists():
        raise FileNotFoundError(f"no channel config at {path}")
    return blooper_relaxation(json.loads(path.read_text()))

# --------------------------------------------------------------------------
# CF-0185: the refusal rule - no fact found, the topic is dropped
# (a production fact until CF-0438/CF-0439; a fact of any kind since - the
# key and the warning code keep their old names as contract names)
# --------------------------------------------------------------------------
# The schema of `production_fact_refusal`, the third channel-level block after
# CF-0137's rung and CF-0190's relaxation, and the one written *before* its
# reader exists: the behaviour is CF-0185 part 2, in
# `agents/content-researcher`, and this block is the contract it will be
# written against. That order is why the schema is stricter than a key list.
#
# What it holds that a key list would not, and why each border is here:
#
#   * `enabled: true` is refused while the source named in `fact_source` is
#     missing from the channel's `sources` or switched off there. This is the
#     trap the task was written around - a rule that drops a topic on
#     not-found, switched on before anything looks for facts, empties the
#     batch on its first pass. Prose cannot prevent that; a validator can, and
#     the condition it checks is a line in the same file rather than a date or
#     the status of a task.
#   * `not_found.statuses` is pinned to the three empty results CF-0184's
#     lookup returns, so a channel cannot widen "no fact" to include the case
#     where the source could not be reached, and `source_unreachable.
#     drops_topic` is pinned to false for the same reason from the other side.
#     A batch emptied by our own outage is the failure this rule must not have.
#   * the two code strings are pinned: `no_production_fact` is the
#     orchestrator's vocabulary (tests/test_pipeline_contracts.py SKIP_CODES),
#     not a per-channel name, and `production_fact_not_found` is the warning
#     the disabled state owes the report.
#   * `empty_batch_guard.min_scripts_after_refusal` has a floor of 1 that a
#     channel may raise but not lower - the one ceiling-shaped number here,
#     and the same "stricter yes, looser no" rule the relaxation's seconds
#     carry.
#   * `does_not_touch` has to name `min_popularity_score`. Item 3 of CF-0185
#     forbids touching the funnel numbers, each of which carries the
#     provenance of its own measurement; the sentence saying so has to be
#     findable in the block rather than only in the task file.
FACT_REFUSAL_KEY = "production_fact_refusal"
FACT_REFUSAL_READ_KEYS = ("enabled", "decided_on", "recorded_by", "rule",
                          "reason", "fact_source", "not_found",
                          "source_unreachable", "when_disabled", "when_enabled",
                          "empty_batch_guard", "applies_to", "does_not_touch",
                          "read_by")
FACT_REFUSAL_NOT_FOUND_KEYS = ("statuses", "candidates_field")
FACT_REFUSAL_UNREACHABLE_KEYS = ("drops_topic", "signal")
FACT_REFUSAL_DISABLED_KEYS = ("topic_proceeds", "warning_code", "written_to",
                              "entry_keys")
FACT_REFUSAL_ENABLED_KEYS = ("topic_dropped", "reason_code", "written_to",
                             "entry_keys")
FACT_REFUSAL_GUARD_KEYS = ("min_scripts_after_refusal",)
FACT_REFUSAL_READER_KEYS = ("content_researcher",)
# The names CF-0184's lookup returns when it worked and found nothing. Not a
# vocabulary this file invents: `agents/content-researcher/scripts/
# production_facts.py` writes exactly these into `status`, with `candidates`
# empty, and raises instead when the source could not be reached.
FACT_REFUSAL_STATUSES = ("no_article", "no_section", "no_candidates")
# The orchestrator's words for the two outcomes, pinned so that a channel
# decides whether it refuses and never what the refusal is called.
# CF-0438: `no_fact` - the rule takes any kind of fact now
# (shared/factrule/fact_rule.py REFUSAL_CODE); the old word is read, never pinned.
FACT_REFUSAL_REASON_CODE = "no_fact"
FACT_REFUSAL_WARNING_CODE = "production_fact_not_found"
# What a skip written under this rule has to carry beyond the three keys every
# skip carries, so that a refusal can be audited afterwards.
FACT_REFUSAL_AUDIT_KEY = "fact_lookup"
FACT_REFUSAL_SKIP_KEYS = ("topic_id", "reason_code", "reason",
                          FACT_REFUSAL_AUDIT_KEY)
FACT_REFUSAL_WARNING_KEYS = ("topic_id", "warning_code")
# A channel may demand more scripts than this before it will ship a batch;
# below it lies the empty batch the switch exists to prevent.
FACT_REFUSAL_MIN_SCRIPTS_FLOOR = 1
# The funnel number item 3 of CF-0185 puts out of reach.
FACT_REFUSAL_FUNNEL_NAME = "min_popularity_score"
# A channel that wrote no block refuses nothing - the reading CF-0137's rung
# and CF-0190's relaxation both make of their own switches.
FACT_REFUSAL_DEFAULT_ENABLED = False
FACT_REFUSAL_PROSE_MIN_CHARS = 40
FACT_REFUSAL_LONG_PROSE_MIN_CHARS = 160


def _block_pinned_string(errs, node, key, ctx, expected, why):
    """A key pinned to one exact string, with the reason in the message.
    `_block_pinned`'s twin for the values that are words rather than states."""
    if key not in node:
        return
    if node[key] != expected:
        errs.append(f"{ctx}.{key}: must be {expected!r} - {why} "
                    f"(got {node[key]!r})")


def _fact_refusal_entry_keys(errs, node, ctx, must_have):
    """The keys an entry written under this rule has to carry. A list, because
    the block is telling a reader in another repository what to write; more
    than these is a channel's business, fewer is a record nobody can audit."""
    if "entry_keys" not in node:
        return
    keys = node["entry_keys"]
    if (not isinstance(keys, list) or not keys
            or any(not isinstance(k, str) or not k.strip() for k in keys)):
        errs.append(f"{ctx}.entry_keys: must be a non-empty list of the key "
                    f"names such an entry carries, got {keys!r}")
        return
    missing = [k for k in must_have if k not in keys]
    if missing:
        errs.append(f"{ctx}.entry_keys: missing {missing} - an entry without "
                    f"them cannot be read back afterwards, and the root's own "
                    f"contract (tests/test_pipeline_contracts.py) requires them")


def _validate_fact_refusal_not_found(node, bctx):
    """What 'no fact' is allowed to mean - the source's own empty results."""
    nctx = f"{bctx}.not_found"
    if not isinstance(node, dict):
        return [f"{nctx}: must be an object"]
    errs = _block_unknown_keys(node, FACT_REFUSAL_NOT_FOUND_KEYS, nctx,
                               "the refusal rule")
    errs += _block_required(node, FACT_REFUSAL_NOT_FOUND_KEYS, nctx,
                            "a refusal rule")
    if "statuses" in node:
        statuses = node["statuses"]
        if (not isinstance(statuses, list)
                or sorted(str(s) for s in statuses)
                != sorted(FACT_REFUSAL_STATUSES)):
            errs.append(
                f"{nctx}.statuses: must be exactly {list(FACT_REFUSAL_STATUSES)} "
                f"- the empty results CF-0184's lookup returns when it worked "
                f"and found nothing. Fewer of them is a rule that silently "
                f"passes a topic it was meant to catch; one more is a channel "
                f"inventing an emptiness the source never reports, and the one "
                f"that must never be added is an unreachable source. Got "
                f"{statuses!r}")
    if "candidates_field" in node:
        field = node["candidates_field"]
        if not isinstance(field, str) or not field.strip() or field.strip() != field:
            errs.append(f"{nctx}.candidates_field: must be the non-empty, "
                        f"unpadded name of the lookup's list of candidates, "
                        f"got {field!r}")
    return errs


def _validate_fact_refusal_unreachable(node, bctx):
    """The third state: our side could not ask, and nothing is dropped."""
    uctx = f"{bctx}.source_unreachable"
    if not isinstance(node, dict):
        return [f"{uctx}: must be an object"]
    errs = _block_unknown_keys(node, FACT_REFUSAL_UNREACHABLE_KEYS, uctx,
                               "the refusal rule")
    errs += _block_required(node, FACT_REFUSAL_UNREACHABLE_KEYS, uctx,
                            "a refusal rule")
    _block_pinned(errs, node, "drops_topic", uctx, False,
                  "a source that could not be reached is not a title without "
                  "facts, and a batch emptied by our own outage is this rule "
                  "doing the opposite of what it is for")
    _block_prose(errs, node, "signal", uctx, FACT_REFUSAL_PROSE_MIN_CHARS)
    return errs


def _validate_fact_refusal_state(node, bctx, name, keys, flag, flag_value,
                                 code_key, code, code_why, entry_must_have):
    """One of the two halves of the switch. Both are written out in the block,
    because a switch whose off position is undescribed is a switch nobody can
    read: `when_disabled` is the state this channel is actually in."""
    sctx = f"{bctx}.{name}"
    if not isinstance(node, dict):
        return [f"{sctx}: must be an object"]
    errs = _block_unknown_keys(node, keys, sctx, "the refusal rule")
    errs += _block_required(node, keys, sctx, "a refusal rule")
    _block_pinned(errs, node, flag, sctx, flag_value,
                  "this is what the switch means in that position, not a "
                  "second switch inside it")
    _block_pinned_string(errs, node, code_key, sctx, code, code_why)
    _block_prose(errs, node, "written_to", sctx, FACT_REFUSAL_PROSE_MIN_CHARS)
    _fact_refusal_entry_keys(errs, node, sctx, entry_must_have)
    return errs


def _validate_fact_refusal_guard(node, bctx):
    """The floor under the batch: the rule may not empty one by itself."""
    gctx = f"{bctx}.empty_batch_guard"
    if not isinstance(node, dict):
        return [f"{gctx}: must be an object"]
    errs = _block_unknown_keys(node, FACT_REFUSAL_GUARD_KEYS, gctx,
                               "the refusal rule")
    errs += _block_required(node, FACT_REFUSAL_GUARD_KEYS, gctx,
                            "a refusal rule")
    if "min_scripts_after_refusal" in node:
        value = node["min_scripts_after_refusal"]
        if isinstance(value, bool) or not isinstance(value, int):
            errs.append(f"{gctx}.min_scripts_after_refusal: must be an integer "
                        f"count of scripts, got {value!r}")
        elif value < FACT_REFUSAL_MIN_SCRIPTS_FLOOR:
            errs.append(
                f"{gctx}.min_scripts_after_refusal: {value!r} is below the "
                f"floor of {FACT_REFUSAL_MIN_SCRIPTS_FLOOR}. A channel may ask "
                f"for more scripts before it ships a batch - that is the "
                f"stricter direction - but not for fewer: below the floor an "
                f"empty batch becomes an acceptable outcome of the rule, and "
                f"an empty batch being unacceptable is why the rule has a "
                f"switch at all")
    return errs


def _fact_refusal_source_enabled(cfg, name):
    """Whether the channel's `sources` carries `name` and has it switched on -
    the state `enabled: true` is not allowed to get ahead of."""
    sources = cfg.get("sources")
    if not isinstance(sources, dict) or not isinstance(name, str):
        return False
    entry = sources.get(name)
    return isinstance(entry, dict) and entry.get("enabled") is True


def validate_production_fact_refusal_block(cfg, ctx="channel"):
    """Errors for a channel config's `production_fact_refusal` block; [] when
    the channel wrote none, which is the default and means no refusal."""
    block = cfg.get(FACT_REFUSAL_KEY)
    if block is None:
        return []
    bctx = f"{ctx}.{FACT_REFUSAL_KEY}"
    if not isinstance(block, dict):
        return [f"{bctx}: must be an object"]
    errs = _block_unknown_keys(block, FACT_REFUSAL_READ_KEYS, bctx,
                               "the refusal rule")
    errs += _block_required(block, FACT_REFUSAL_READ_KEYS, bctx,
                            "a refusal rule")
    if "enabled" in block and not isinstance(block["enabled"], bool):
        errs.append(f"{bctx}.enabled: must be true or false, got "
                    f"{block['enabled']!r}. There is no third state and no "
                    f"default: an unreadable switch is not a switched-on one")
    if "decided_on" in block:
        when = block["decided_on"]
        if not isinstance(when, str) or not BLOOPER_DATE_RE.match(when):
            errs.append(f"{bctx}.decided_on: must be an ISO date (YYYY-MM-DD) - "
                        f"a rule that drops topics says when it was decided, "
                        f"got {when!r}")
    _block_prose(errs, block, "recorded_by", bctx, 1)
    _block_prose(errs, block, "rule", bctx, FACT_REFUSAL_PROSE_MIN_CHARS)
    _block_prose(errs, block, "reason", bctx, FACT_REFUSAL_LONG_PROSE_MIN_CHARS)
    _block_prose(errs, block, "enabled_note", bctx,
                 FACT_REFUSAL_LONG_PROSE_MIN_CHARS)
    _block_prose(errs, block, "applies_to", bctx, FACT_REFUSAL_PROSE_MIN_CHARS)
    source = block.get("fact_source")
    if "fact_source" in block and (not isinstance(source, str)
                                   or not source.strip()
                                   or source.strip() != source):
        errs.append(f"{bctx}.fact_source: must be the non-empty, unpadded name "
                    f"of the key in this channel's `sources` that supplies the "
                    f"facts, got {source!r}")
    if "not_found" in block:
        errs += _validate_fact_refusal_not_found(block["not_found"], bctx)
    if "source_unreachable" in block:
        errs += _validate_fact_refusal_unreachable(block["source_unreachable"],
                                                   bctx)
    if "when_disabled" in block:
        errs += _validate_fact_refusal_state(
            block["when_disabled"], bctx, "when_disabled",
            FACT_REFUSAL_DISABLED_KEYS, "topic_proceeds", True,
            "warning_code", FACT_REFUSAL_WARNING_CODE,
            "the warning the report owes a topic the rule let through is one "
            "word for the whole factory, not a per-channel one",
            FACT_REFUSAL_WARNING_KEYS)
    if "when_enabled" in block:
        errs += _validate_fact_refusal_state(
            block["when_enabled"], bctx, "when_enabled",
            FACT_REFUSAL_ENABLED_KEYS, "topic_dropped", True,
            "reason_code", FACT_REFUSAL_REASON_CODE,
            "the skip codes are the orchestrator's vocabulary "
            "(tests/test_pipeline_contracts.py SKIP_CODES); a channel decides "
            "whether it refuses, never what the refusal is called",
            FACT_REFUSAL_SKIP_KEYS)
    if "empty_batch_guard" in block:
        errs += _validate_fact_refusal_guard(block["empty_batch_guard"], bctx)
    if "does_not_touch" in block:
        untouched = block["does_not_touch"]
        if (not isinstance(untouched, list) or len(untouched) < 2
                or any(not isinstance(s, str)
                       or len(s.strip()) < FACT_REFUSAL_PROSE_MIN_CHARS
                       for s in untouched)):
            errs.append(f"{bctx}.does_not_touch: must be a list of at least two "
                        f"prose lines naming what the rule leaves alone, got "
                        f"{untouched!r}")
        elif not any(FACT_REFUSAL_FUNNEL_NAME in s for s in untouched):
            errs.append(f"{bctx}.does_not_touch: none of these lines names "
                        f"{FACT_REFUSAL_FUNNEL_NAME!r}. Item 3 of CF-0185 keeps "
                        f"the funnel numbers out of this decision - each "
                        f"carries the provenance of its own measurement and "
                        f"none has been measured against the narrower funnel - "
                        f"and that has to be readable here, not only in the "
                        f"task file")
    if "read_by" in block:
        readers = block["read_by"]
        rctx = f"{bctx}.read_by"
        if not isinstance(readers, dict):
            errs.append(f"{rctx}: must be an object of reader -> what it reads")
        else:
            errs += _block_unknown_keys(readers, FACT_REFUSAL_READER_KEYS, rctx,
                                        "the refusal rule")
            errs += _block_required(readers, FACT_REFUSAL_READER_KEYS, rctx,
                                    "a refusal rule")
            for key in FACT_REFUSAL_READER_KEYS:
                _block_prose(errs, readers, key, rctx,
                             FACT_REFUSAL_LONG_PROSE_MIN_CHARS)
    if block.get("enabled") is True and not _fact_refusal_source_enabled(
            cfg, block.get("fact_source")):
        errs.append(
            f"{bctx}.enabled: true, but this config's `sources` does not carry "
            f"{block.get('fact_source')!r} switched on. The rule drops every "
            f"topic for which no fact was found, so switching it on "
            f"before anything looks for facts empties the batch on its first "
            f"pass - the trap CF-0185 was written around. The switch is "
            f"therefore not allowed to get ahead of the source: add the source "
            f"to `sources` with `enabled: true` (CF-0184) in the same checkout, "
            f"or leave this false. This is the whole of the enabling condition "
            f"and it is a line in this file, not a date and not the status of "
            f"a task")
    return errs


def production_fact_refusal(cfg):
    """The refusal rule a channel config puts in force, or None.

    None when the block is absent, unreadable or switched off - the same
    fail-closed reading `blooper_relaxation()` and
    agents/video-editor/scripts/assetless_rung.py make of their own switches,
    and the one CF-0185 part 2 is contracted to make. Here the safe direction
    is *not refusing*: a reader that treated an illegal block as a rule in
    force would drop topics on a contract nobody could parse.
    """
    if not isinstance(cfg, dict):
        return None
    block = cfg.get(FACT_REFUSAL_KEY)
    if not isinstance(block, dict):
        return None
    if block.get("enabled", FACT_REFUSAL_DEFAULT_ENABLED) is not True:
        return None
    if validate_production_fact_refusal_block(cfg):
        return None
    return block


def load_production_fact_refusal(channel):
    """`production_fact_refusal()` for a channel by id; None when it refuses
    nothing - which is what every channel in this checkout does today."""
    path = narration_budget_file(channel)
    if not path.exists():
        raise FileNotFoundError(f"no channel config at {path}")
    return production_fact_refusal(json.loads(path.read_text()))


# --------------------------------------------------------------------------
# CF-0154: the two files a channel's owner brings, and the reminder about them
# --------------------------------------------------------------------------
# Two of the assets above are not produced by this factory and cannot be: the
# ending clip (CF-0141) and the ambient bed (CF-0153). Both are optional -
# each degrades to a floor the factory does own - and until CF-0154 there was
# nowhere to find that out. There is no channel-creation script to put the
# reminder in (CF-0016 creates the channel on YouTube, not the directory here;
# `channels/example-film/` was assembled by hand), so it is printed by the
# one command in the root that walks every channel config:
# `inserts/validate_inserts.py`. See tasks/CF-0154-*.md for the alternatives
# that were weighed.
#
# The reminder is a *report*, never a verdict. It is not part of
# `validate_vocabulary()`, it produces no errors and it cannot move an exit
# code: a channel without these files is a channel that sounds and looks worse
# than it could, not a broken one, and a reminder that read as a failure would
# be a lie about what happens next.
#
# `logo.<ext>` (CF-0117) is deliberately *not* on this list. It is brought by a
# human too, but it is the floor's own detail - which of the two drawn cards
# you get - rather than a thing whose absence costs the channel a layer.
CHANNEL_ENDING_NAME = "ending.mp4"
CHANNEL_AMBIENT_STEM = "ambient"
# The extensions tried, in this order, by
# agents/video-editor/scripts/ambient_bed.py AMBIENT_EXTS. A copy, like
# CHANNEL_ENDING_NAME is a copy of that repo's ENDING_NAME: the root may not
# import the Editor. tests/test_channel_asset_reminder.py reads both back out
# of the Editor's source and fails when they drift - and skips that check when
# `agents/` is not in the checkout, which is the normal state of a worktree.
CHANNEL_AMBIENT_EXTS = (".wav", ".flac", ".aif", ".aiff", ".m4a", ".mp3",
                        ".aac", ".ogg", ".opus")
# asset key -> what it is, what its absence costs, and how its path is found.
# `override` is the `video_editor.<block>.<key>` pair from
# VIDEO_EDITOR_ASSET_KEYS above; `names` are the convention file names under
# `channels/<channel_id>/`, in the order the reader tries them.
CHANNEL_BROUGHT_ASSETS = {
    VIDEO_EDITOR_ENDING_KEY: {
        "task": "CF-0141",
        "names": (CHANNEL_ENDING_NAME,),
        "override": (VIDEO_EDITOR_ENDING_KEY, "path"),
        "what": "the clip every video of the channel closes on",
        "absent": ("the Video Editor draws its end card instead - the logo card "
                   "if channels/<channel_id>/logo.<ext> is there, typographic if "
                   "not. Nothing breaks; the channel just ends on a drawn card "
                   "rather than on its own footage"),
        "also": ("bringing one later is an edit to narration_budget.ending_seconds "
                 "and through it to the script length of every future video - the "
                 "narration band is [total_seconds_min - tail, total_seconds_max - "
                 "tail] (CF-0158)"),
    },
    VIDEO_EDITOR_AMBIENT_KEY: {
        "task": "CF-0153",
        "names": tuple(f"{CHANNEL_AMBIENT_STEM}{e}" for e in CHANNEL_AMBIENT_EXTS),
        "override": (VIDEO_EDITOR_AMBIENT_KEY, "path"),
        "what": "the background bed under the narration",
        "absent": ("build_soundtrack.py generates a bed instead. Nothing breaks; "
                   "the generated bed reads as a cooling fan and is the accepted "
                   "floor (CF-0025, decision 2) - it is not being repaired"),
        "also": ("the file has to run at least 8 s and carry real energy above "
                 "200 Hz; one that does not is refused as the wrong file "
                 "(AmbientBedError) before ffmpeg starts. Sample rate, channels, "
                 "codec and mastering level do not matter"),
    },
}


def channel_asset_override(cfg, asset):
    """The path `video_editor.<asset>.<key>` names, or None.

    Read exactly as the Editor reads it: a non-string or a blank string is not
    an override and falls through to the convention, which is why the shape
    check at `_validate_asset_override` exists at all."""
    block = (cfg.get(VIDEO_EDITOR_KEY) or {}).get(asset)
    if not isinstance(block, dict):
        return None
    key = CHANNEL_BROUGHT_ASSETS[asset]["override"][1]
    value = block.get(key)
    if not isinstance(value, str) or not value.strip():
        return None
    return value.strip()


def channel_bed_list(cfg):
    """The paths `video_editor.ambient.beds` names, or None.

    CF-0271: the rotation form of the same override. Read in the same forgiving
    shape as `channel_asset_override` - anything that is not a non-empty list of
    non-empty strings is not a list of beds, and the loud complaint about it is
    `_validate_path_list`'s job, not this accessor's. Blank and non-string
    entries are dropped rather than raising here for the same reason: this is
    what a reader *would see*, and the reminder that uses it must not be the
    thing that fails.
    """
    block = (cfg.get(VIDEO_EDITOR_KEY) or {}).get(VIDEO_EDITOR_AMBIENT_KEY)
    if not isinstance(block, dict):
        return None
    value = block.get(VIDEO_EDITOR_BEDS_KEY)
    if not isinstance(value, list):
        return None
    paths = [v.strip() for v in value if isinstance(v, str) and v.strip()]
    return paths or None


def _shown_bed_list(paths):
    """A bed list in one readable line, in the brace shape this module already
    prints the ambient extensions in (`channels/c/ambient.{wav,flac,...}`):
    a shared directory is said once. The reminder is read in a terminal, and
    three absolute paths on one line is three paths nobody compares."""
    parents = {str(PurePosixPath(p).parent) for p in paths}
    if len(paths) > 1 and len(parents) == 1:
        parent = parents.pop()
        names = ", ".join(PurePosixPath(p).name for p in paths)
        return f"{parent}/{{{names}}}"
    return ", ".join(paths)


def channel_asset_status(cfg, channel_id, asset, root=None):
    """Where one brought asset would be read from, and whether it is there.

    Mirrors the Editor's resolution (`ending_path()`, `ambient_path()`): the
    config override first, then the convention names under
    `channels/<channel_id>/` in order. Returns a dict:

        asset      the key in CHANNEL_BROUGHT_ASSETS
        source     "config" | "convention" | None (nothing on disk either way)
        path       the resolved Path when something is there, else None
        paths      every resolved Path the config names (CF-0271: the bed
                   rotation names several); one-element for a single file
        shown      what to print as the place to put the file
        present    bool
    """
    root = ROOT if root is None else Path(root)
    spec = CHANNEL_BROUGHT_ASSETS[asset]
    # CF-0271: the rotation form comes first, because a channel that names it
    # has said its bed is this list and nothing else - the convention path is
    # not a fallback under it, exactly as it is not a fallback under `path`.
    # `present` is all-of-them: a rotation missing one file is a rotation that
    # renders a video with a bed nobody chose, which is the whole complaint.
    beds = channel_bed_list(cfg) if asset == VIDEO_EDITOR_AMBIENT_KEY else None
    if beds is not None:
        resolved = [p if p.is_absolute() else root / p
                    for p in (Path(b) for b in beds)]
        here = [p for p in resolved if p.exists()]
        missing = [b for b, p in zip(beds, resolved) if not p.exists()]
        shown = _shown_bed_list(missing or beds)
        return {"asset": asset, "source": "config" if not missing else None,
                "path": here[0] if here and not missing else None,
                "paths": here if not missing else [],
                "shown": shown, "present": not missing}
    override = channel_asset_override(cfg, asset)
    if override is not None:
        p = Path(override)
        p = p if p.is_absolute() else root / p
        return {"asset": asset, "source": "config" if p.exists() else None,
                "path": p if p.exists() else None,
                "paths": [p] if p.exists() else [], "shown": override,
                "present": p.exists()}
    base = root / "channels" / str(channel_id)
    for name in spec["names"]:
        cand = base / name
        if cand.exists():
            rel = f"channels/{channel_id}/{name}"
            return {"asset": asset, "source": "convention", "path": cand,
                    "paths": [cand], "shown": rel, "present": True}
    shown = f"channels/{channel_id}/{spec['names'][0]}"
    if len(spec["names"]) > 1:
        exts = ",".join(n.split(".", 1)[1] for n in spec["names"])
        shown = f"channels/{channel_id}/{CHANNEL_AMBIENT_STEM}.{{{exts}}}"
    return {"asset": asset, "source": None, "path": None, "paths": [],
            "shown": shown, "present": False}


def channel_asset_reminder(cfg, channel_id, root=None):
    """The printable reminder for one channel: a list of lines.

    A present asset gets one line saying so. An absent one gets the path to
    put it at and what its absence costs - CF-0154's acceptance is that the
    reminder names both, because "put a file here" with no consequence reads
    as a hard requirement, and neither of these files is one.
    """
    lines = [f"  {channel_id}"]
    for asset, spec in CHANNEL_BROUGHT_ASSETS.items():
        st = channel_asset_status(cfg, channel_id, asset, root=root)
        if st["present"]:
            where = " (video_editor override)" if st["source"] == "config" else ""
            lines.append(f"    {asset:<8} ok       {st['shown']}{where}")
            continue
        lines.append(f"    {asset:<8} ABSENT   put it at {st['shown']}")
        pad = " " * 14
        for text in (f"{spec['what']} ({spec['task']}).",
                     f"without it: {spec['absent']}.",
                     f"note: {spec['also']}."):
            lines += textwrap.wrap(text, width=CHANNEL_REMINDER_WIDTH,
                                   initial_indent=pad, subsequent_indent=pad)
    return lines


# Width the reminder wraps its prose to - the report is read in a terminal,
# and a 200-character consequence on one line is a consequence nobody reads.
CHANNEL_REMINDER_WIDTH = 88
CHANNEL_ASSET_REMINDER_HEADING = (
    "channels/: files a channel's owner brings - the factory cannot make these")


# CF-0279's rate and envelope are the channel's: `narration_rate(channel)` is
# the median an estimate is drawn at, `rate_envelope(budget)` the two ends a
# range has to survive (CF-0633 took the first channel's copies off this
# module).
# The sections that are actually read aloud. scene_direction is a stage
# direction and never reaches the voice.
NARRATION_SECTIONS = ("hook", "commentary", "payoff")
# Hold lengths are drawn to two decimals (see draw_order); a recomputed hold is
# rounded up on the same grid so the record stays in the schema's own units.
HOLD_GRID = 0.01
# CF-0300. The one rhythm that *grows* a block towards the hold it was given,
# and therefore the one where the drawn number is a floor rather than a cap.
# The share of the band it may be drawn from lives in rhythms.json under this
# rhythm's `drawn_hold` (with the evidence); these are only its spellings.
HOLD_RHYTHM_ID = "hold"
DRAWN_HOLD_KEY = "drawn_hold"


def load_rhythms():
    """The shared enums: rhythm ids and opening-block kinds."""
    return json.loads(RHYTHMS_FILE.read_text())


def pattern_files():
    """Every pattern file. rhythms.json is the shared enum, not a pattern."""
    return sorted(p for p in PATTERNS_DIR.glob("*.json") if p.name != RHYTHMS_FILE.name)


def load_patterns():
    return {p.stem: json.loads(p.read_text()) for p in pattern_files()}


def rhythm_entry(rhythm_id, rhythms=None):
    """The rhythms.json record for one rhythm id, or None."""
    r = rhythms if rhythms is not None else load_rhythms()
    for item in r.get("rhythms", []):
        if item.get("rhythm_id") == rhythm_id:
            return item
    return None


def drawn_hold_share(rhythms=None):
    """CF-0300: the share of a pattern's hold band the `hold` rhythm may draw.

    None when rhythms.json declares no constraint - then the draw is the
    pattern's own band, as it was before this rule. The number itself and the
    reasoning behind it live in rhythms.json, not here: this is one more shared
    enum the patterns read, and a constant copied into code is a rule that can
    drift away from the file that explains it.
    """
    entry = rhythm_entry(HOLD_RHYTHM_ID, rhythms) or {}
    cfg = entry.get(DRAWN_HOLD_KEY)
    return None if not isinstance(cfg, dict) else cfg.get("max_share_of_band")


def hold_draw_band(pattern, rhythm_id, rhythms=None):
    """The window `key_frame_hold_seconds` may be drawn from for this pair.

    The pattern's own band for every rhythm but `hold`, and for `hold` the
    lower part of it: on that rhythm the montage grows the held block *past*
    the drawn number by swallowing whole stretches, so a draw near the top of
    the band puts the block over the top of the band (CF-0300). The envelope is
    never touched (CF-0195) - only the point drawn inside it.

    Returns None when the parameter draws no value - `emergent`, and CF-0314's
    `floor_drawn`, where the floor is a boundary and not a number to pick.
    """
    cfg = pattern["parameters"]["key_frame_hold_seconds"]
    if not draws_a_value(cfg):
        return None
    lo, hi = float(cfg["min"]), float(cfg["max"])
    share = drawn_hold_share(rhythms) if rhythm_id == HOLD_RHYTHM_ID else None
    if share is None:
        return lo, hi
    # Down onto the grid the draw is written on: a ceiling that is not itself a
    # legal value would refuse the very number it names.
    capped = math.floor(hi * float(share) / HOLD_GRID + 1e-9) * HOLD_GRID
    return lo, round(max(lo, capped), 2)


def _num_range(errs, obj, ctx, integral):
    if not isinstance(obj, dict):
        errs.append(f"{ctx}: expected an object with min/max")
        return
    for k in ("min", "max"):
        if k not in obj:
            errs.append(f"{ctx}: missing {k}")
            return
    lo, hi = obj["min"], obj["max"]
    kind = int if integral else (int, float)
    if not isinstance(lo, kind) or not isinstance(hi, kind) or isinstance(lo, bool):
        errs.append(f"{ctx}: min/max must be {'integers' if integral else 'numbers'}")
        return
    if lo > hi:
        errs.append(f"{ctx}: min {lo} > max {hi}")


def _drawn_hold_errors(item):
    """CF-0300: the optional `drawn_hold` block on a rhythm.

    A rhythm that narrows what may be drawn for it has to say which parameter
    it narrows, by how much, and why - the share is the whole rule, and a
    share with no reasoning beside it is a number nobody can argue with later.
    Absent is legal: only `hold` grows a block past the value it was given.
    """
    rid = item.get("rhythm_id")
    cfg = item.get(DRAWN_HOLD_KEY)
    if cfg is None:
        return []
    if not isinstance(cfg, dict):
        return [f"rhythms.json: rhythm {rid!r} {DRAWN_HOLD_KEY} must be an object"]
    errs = []
    if cfg.get("applies_to") not in PARAMETER_KEYS:
        errs.append(f"rhythms.json: rhythm {rid!r} {DRAWN_HOLD_KEY}.applies_to must name "
                    f"one of {list(PARAMETER_KEYS)}, got {cfg.get('applies_to')!r}")
    share = cfg.get("max_share_of_band")
    if not isinstance(share, (int, float)) or isinstance(share, bool) or not 0 < share <= 1:
        errs.append(f"rhythms.json: rhythm {rid!r} {DRAWN_HOLD_KEY}.max_share_of_band must "
                    f"be a number in (0, 1], got {share!r}")
    note = cfg.get("note")
    if not isinstance(note, str) or len(note.strip()) < 200:
        errs.append(f"rhythms.json: rhythm {rid!r} {DRAWN_HOLD_KEY}.note must carry the "
                    f"reasoning and the measurement the share rests on")
    return errs


def validate_rhythms(rhythms=None):
    """The shared enum file itself."""
    errs = []
    r = rhythms if rhythms is not None else load_rhythms()
    for key in ("rhythms", "opening_block_kinds"):
        if not isinstance(r.get(key), list) or not r[key]:
            errs.append(f"rhythms.json: {key} must be a non-empty list")
            return errs
    for item in r["rhythms"]:
        for k in ("rhythm_id", "display_name", "summary", "cut_logic",
                  "executable_today", "blocked_by"):
            if k not in item:
                errs.append(f"rhythms.json: rhythm {item.get('rhythm_id')!r} missing {k}")
        if not isinstance(item.get("cut_logic"), list) or not item.get("cut_logic"):
            errs.append(f"rhythms.json: rhythm {item.get('rhythm_id')!r} has no cut_logic prose")
        if item.get("executable_today") is False and not item.get("blocked_by"):
            errs.append(f"rhythms.json: rhythm {item.get('rhythm_id')!r} is not executable "
                        f"but names no blocking task")
        errs += _drawn_hold_errors(item)
    ids = [i.get("rhythm_id") for i in r["rhythms"]]
    if len(set(ids)) != len(ids):
        errs.append(f"rhythms.json: duplicate rhythm ids in {ids}")
    for item in r["opening_block_kinds"]:
        for k in ("kind", "summary", "description", "executable_today", "blocked_by"):
            if k not in item:
                errs.append(f"rhythms.json: opening block {item.get('kind')!r} missing {k}")
        if item.get("executable_today") is False and not item.get("blocked_by"):
            errs.append(f"rhythms.json: opening block {item.get('kind')!r} is not executable "
                        f"but names no blocking task")
    kinds = [i.get("kind") for i in r["opening_block_kinds"]]
    if len(set(kinds)) != len(kinds):
        errs.append(f"rhythms.json: duplicate opening block kinds in {kinds}")
    return errs


def validate_pattern(pattern, rhythms=None, stem=None):
    """Return a list of human-readable errors. Empty list means valid."""
    errs = []
    r = rhythms if rhythms is not None else load_rhythms()
    known_rhythms = {i["rhythm_id"] for i in r["rhythms"]}
    known_openings = {i["kind"] for i in r["opening_block_kinds"]}
    pid = pattern.get("pattern_id", "<no pattern_id>")
    ctx = f"pattern {pid}"

    for key in ("pattern_id", "display_name", "summary", "script_sections",
                "allowed_rhythms", "writing_instruction", "parameters",
                "original_contribution"):
        if key not in pattern:
            errs.append(f"{ctx}: missing required field {key!r}")
    if errs:
        return errs

    if stem is not None and pattern["pattern_id"] != stem:
        errs.append(f"{ctx}: pattern_id does not match filename stem {stem!r}")
    for key in ("display_name", "summary"):
        if not isinstance(pattern[key], str) or not pattern[key].strip():
            errs.append(f"{ctx}: {key} must be a non-empty string")

    # --- the prose. The whole method of writing lives here, so a stub is a
    # failure, not a warning: a pattern nobody can write by is not a pattern.
    wi = pattern["writing_instruction"]
    if not isinstance(wi, list) or not wi or not all(
            isinstance(p, str) and p.strip() for p in wi):
        errs.append(f"{ctx}: writing_instruction must be a non-empty list of paragraphs")
    elif sum(len(p) for p in wi) < 400:
        errs.append(f"{ctx}: writing_instruction is a stub "
                    f"({sum(len(p) for p in wi)} chars) - the prose of how to write "
                    f"with this pattern lives here in full, not in any SKILL.md")

    ss = pattern["script_sections"]
    if not isinstance(ss, list) or not ss or not all(isinstance(s, str) and s for s in ss):
        errs.append(f"{ctx}: script_sections must be a non-empty list of key names")

    ar = pattern["allowed_rhythms"]
    if not isinstance(ar, list) or not ar:
        errs.append(f"{ctx}: allowed_rhythms must be a non-empty list")
    else:
        if len(set(ar)) != len(ar):
            errs.append(f"{ctx}: duplicate entries in allowed_rhythms {ar}")
        for rid in ar:
            if rid not in known_rhythms:
                errs.append(f"{ctx}: unknown rhythm {rid!r} (known: {sorted(known_rhythms)})")

    # --- parameters
    params = pattern["parameters"]
    if not isinstance(params, dict):
        errs.append(f"{ctx}: parameters must be an object")
    else:
        # CF-0310: the block parameter is one parameter with two legal
        # spellings, so it is taken out of the set arithmetic and judged on
        # its own - "exactly one of the two". Declaring both would leave two
        # bands that can disagree with each other and no rule for which wins.
        declared_block_keys = [k for k in BLOCK_PARAMETER_KEYS if k in params]
        rest = tuple(k for k in PARAMETER_KEYS if k != BLOCK_COUNT_KEY)
        extra = set(params) - set(ALLOWED_PARAMETER_KEYS)
        missing = set(rest) - set(params)
        if len(declared_block_keys) != 1:
            errs.append(
                f"{ctx}: parameters must declare exactly one of "
                f"{list(BLOCK_PARAMETER_KEYS)}, found {declared_block_keys or 'neither'} "
                f"- how many blocks the pattern has is one parameter said in one of two "
                f"units, a count or a rate (CF-0310); two bands for it can disagree, and "
                f"none leaves the cadence half of CF-0015 undeclared")
        if missing:
            errs.append(f"{ctx}: missing parameter(s) {sorted(missing)}")
        if extra:
            errs.append(f"{ctx}: unknown parameter(s) {sorted(extra)} - the four "
                        f"parameters are fixed by CF-0015; a fifth is a design "
                        f"decision, not a file edit")
        for key in set(ALLOWED_PARAMETER_KEYS) & set(params):
            p = params[key]
            # CF-0314: the legal modes depend on the parameter's shape - only a
            # {min, max} band has a floor and a ceiling that can be two
            # different kinds of statement.
            legal = BAND_MODES if key in CADENCE_PARAMETERS else CHOICE_MODES
            if not isinstance(p, dict) or p.get("mode") not in legal:
                extra = ("" if legal is BAND_MODES else
                         f" ({FLOOR_DRAWN_MODE!r} says the floor of a band is ordered and "
                         f"its ceiling observed, and {key} is a choice set with no ends)")
                got = p.get("mode") if isinstance(p, dict) else p
                # The offending word is named, not just the legal set: every
                # reader downstream decides by comparing against one of these
                # strings, and the ones that do not recognise a fourth fall
                # through to a default instead of stopping (CF-0314).
                errs.append(f"{ctx}.{key}: mode must be one of {legal}, got {got!r}{extra}")
        if not missing and len(declared_block_keys) == 1 and \
                not any(e.startswith(f"{ctx}.") for e in errs):
            block_key = declared_block_keys[0]
            is_rate = block_key == BLOCK_RATE_KEY
            _num_range(errs, params[block_key], f"{ctx}.{block_key}",
                       integral=not is_rate)
            _num_range(errs, params["key_frame_hold_seconds"],
                       f"{ctx}.key_frame_hold_seconds", integral=False)
            bc, hold = params[block_key], params["key_frame_hold_seconds"]
            if is_rate:
                # A rate below one block a minute is not a montage, and the
                # ceiling is the same physical fact the feasibility check
                # below is about: at MIN_BLOCK_SECONDS a block, a minute holds
                # 100 of them and no more.
                if isinstance(bc.get("min"), (int, float)) and bc["min"] < 1.0:
                    errs.append(f"{ctx}.{block_key}: min must be at least 1.0 - below one "
                                f"block a minute the video is a single held frame, which "
                                f"is a still, not a pattern")
                rate_ceiling = 60.0 / MIN_BLOCK_SECONDS
                if isinstance(bc.get("max"), (int, float)) and bc["max"] > rate_ceiling:
                    errs.append(f"{ctx}.{block_key}: infeasible - {bc['max']} blocks a "
                                f"minute needs blocks under {60.0 / bc['max']:.2f}s, and "
                                f"the shortest block the pipeline has ever produced is "
                                f"{MIN_BLOCK_SECONDS}s ({rate_ceiling:.0f} a minute)")
            elif isinstance(bc.get("min"), int) and bc["min"] < 2:
                errs.append(f"{ctx}.block_count: min must be at least 2")
            if isinstance(hold.get("min"), (int, float)) and hold["min"] <= 0:
                errs.append(f"{ctx}.key_frame_hold_seconds: min must be positive")

            # CF-0300: a pattern that allows the `hold` rhythm has to leave
            # that rhythm something to draw. The window is the lower part of
            # the band (the held block grows past the draw by whole stretches),
            # so a band whose floor is already above the share is a pair with
            # no legal draw at all - and that is a decision about the pattern's
            # envelope, not a number to be silently clamped at a draw.
            share = drawn_hold_share(r)
            if (HOLD_RHYTHM_ID in (ar if isinstance(ar, list) else [])
                    and hold.get("mode") == "drawn" and share is not None
                    and isinstance(hold.get("min"), (int, float))
                    and isinstance(hold.get("max"), (int, float))
                    and hold["min"] > hold["max"] * float(share) + 1e-9):
                errs.append(
                    f"{ctx}.key_frame_hold_seconds: allows the {HOLD_RHYTHM_ID} rhythm but "
                    f"its band {hold['min']}-{hold['max']} leaves that rhythm nothing to "
                    f"draw - on {HOLD_RHYTHM_ID} the draw may take at most "
                    f"{share} of the band ({hold['max'] * float(share):.2f}s, "
                    f"rhythms.json#{HOLD_RHYTHM_ID}.{DRAWN_HOLD_KEY}) and the band's floor "
                    f"is already above it")

            ob = params["opening_block"]
            choices = ob.get("choices")
            if not isinstance(choices, list) or not choices:
                errs.append(f"{ctx}.opening_block: choices must be a non-empty list")
            else:
                if len(set(choices)) != len(choices):
                    errs.append(f"{ctx}.opening_block: duplicate choices {choices}")
                for c in choices:
                    if c not in known_openings:
                        errs.append(f"{ctx}.opening_block: unknown kind {c!r} "
                                    f"(known: {sorted(known_openings)})")

            acc = params["acceleration_to_payoff"]
            enabled = acc.get("enabled_choices")
            if not isinstance(enabled, list) or not enabled or \
                    not all(isinstance(e, bool) for e in enabled):
                errs.append(f"{ctx}.acceleration_to_payoff: enabled_choices must be a "
                            f"non-empty list of booleans")
            elif len(set(enabled)) != len(enabled):
                errs.append(f"{ctx}.acceleration_to_payoff: duplicate enabled_choices")
            else:
                strength = acc.get("strength", "<missing>")
                if strength == "<missing>":
                    errs.append(f"{ctx}.acceleration_to_payoff: missing strength "
                                f"(use null when acceleration is never on)")
                elif True in enabled:
                    _num_range(errs, strength, f"{ctx}.acceleration_to_payoff.strength",
                               integral=False)
                    if isinstance(strength, dict) and isinstance(strength.get("min"), (int, float)):
                        if not (0 < strength["min"] <= 1 and 0 < strength.get("max", 0) <= 1):
                            errs.append(f"{ctx}.acceleration_to_payoff.strength: must lie "
                                        f"in (0, 1]")
                elif strength is not None:
                    errs.append(f"{ctx}.acceleration_to_payoff: acceleration is never on, "
                                f"so strength must be null")

            # Feasibility: an order the pipeline could not physically fill.
            # Both checks are about a *count* of blocks having to fit in a
            # video, so they are skipped for a rate, which carries no count
            # until a length is chosen - and choosing one here would be the
            # length-dependence CF-0310 removed, put back by the validator.
            # The rate's own feasibility ceiling is checked above instead.
            # (Spelled out rather than left to `isinstance(min, int)` being
            # false for 15.39: a rate written as a round 15 is an int too.)
            if not is_rate and isinstance(bc.get("min"), int) \
                    and isinstance(hold.get("max"), (int, float)):
                floor = hold["max"] + (bc["min"] - 1) * MIN_BLOCK_SECONDS
                if floor > MAX_TARGET_SECONDS:
                    errs.append(f"{ctx}: infeasible - a {bc['min']}-block video with a "
                                f"{hold['max']}s hold needs at least {floor:.1f}s, over the "
                                f"{MAX_TARGET_SECONDS:.0f}s channel ceiling")
            if isinstance(bc.get("min"), int) and \
                    bc["min"] * MIN_BLOCK_SECONDS > MAX_TARGET_SECONDS:
                errs.append(f"{ctx}: infeasible - {bc['min']} blocks do not fit in "
                            f"{MAX_TARGET_SECONDS:.0f}s at {MIN_BLOCK_SECONDS}s a block")

    # --- original_contribution. Required, and required to be honest about
    # being empty: "pending" has to name the task that owes the content, which
    # is what makes forgetting it impossible to mistake for deferring it.
    oc = pattern["original_contribution"]
    if not isinstance(oc, dict):
        errs.append(f"{ctx}.original_contribution: must be an object, not {type(oc).__name__}")
    else:
        status = oc.get("status")
        if status not in CONTRIBUTION_STATUSES:
            errs.append(f"{ctx}.original_contribution: status must be one of "
                        f"{CONTRIBUTION_STATUSES}, got {status!r}")
        elif status == "pending":
            if oc.get("text", "") != "":
                errs.append(f"{ctx}.original_contribution: status is pending but text is "
                            f"not empty - set status to 'defined' instead")
            blocker = oc.get("blocked_by")
            if not isinstance(blocker, str) or not blocker.startswith("CF-"):
                errs.append(f"{ctx}.original_contribution: status is pending, so blocked_by "
                            f"must name the task that owes the content (got {blocker!r})")
        else:
            if not isinstance(oc.get("text"), str) or len(oc.get("text", "").strip()) < 40:
                errs.append(f"{ctx}.original_contribution: status is defined but text is "
                            f"empty or a stub")
            if oc.get("blocked_by"):
                errs.append(f"{ctx}.original_contribution: status is defined, so blocked_by "
                            f"must be absent or null")

    # --- optional fields
    if "baseline" in pattern:
        b = pattern["baseline"]
        if not isinstance(b, dict) or b.get("is_current_form") is not True:
            errs.append(f"{ctx}.baseline: present but is_current_form is not true - drop the "
                        f"field rather than declaring a false baseline")
        elif b.get("rhythm_id") not in known_rhythms:
            errs.append(f"{ctx}.baseline: rhythm_id {b.get('rhythm_id')!r} is not a known rhythm")
        elif b["rhythm_id"] not in pattern.get("allowed_rhythms", []):
            errs.append(f"{ctx}.baseline: rhythm_id {b['rhythm_id']!r} is not in this "
                        f"pattern's allowed_rhythms")

    errs += validate_envelope_evidence(pattern, ctx=ctx)
    errs += envelope_width_errors(pattern, ctx=ctx)
    errs += validate_side_length(pattern, ctx=ctx)

    for field in LAYER_PERMISSION_FIELDS:
        if field not in pattern:
            continue
        m = pattern[field]
        if not isinstance(m, dict) or not isinstance(m.get("allowed"), bool):
            errs.append(f"{ctx}.{field}: must be an object with a boolean 'allowed'")
        elif m["allowed"] is False and not str(m.get("reason", "")).strip():
            errs.append(f"{ctx}.{field}: a pattern that forbids an insert layer has to say "
                        f"why - a bare false is a preference, not a rule")

    return errs


def validate_envelope_evidence(pattern, ctx=None):
    """The fixed point an emergent envelope is measured against (CF-0195).

    An emergent parameter declares a band over what the pipeline was observed
    to do. Until this block existed, *what was observed* lived only in the
    parameter's English note, so the only thing a check could compare the band
    against was the corpus on disk right now - and that corpus is the one a
    regression joins. Hence the rule: a cadence parameter in `emergent` mode
    owes a machine-readable record of the batches its band was measured over
    and the span they shipped.

    A `drawn` parameter owes nothing here: its band is a decision, not an
    observation, and there is no measurement to be faithful to.

    CF-0314: a `floor_drawn` parameter owes everything an emergent one does.
    Its ceiling is still an observation, so the reason above applies to it
    unchanged; and its floor, though it is an order, was *drawn at a
    measurement* - the pace below which the corpus shows the form stops being
    itself. An order set from a measurement that is not written down is an
    order nobody can check, and lowering it to admit a slideshow would be the
    same circularity in a different costume.
    """
    errs = []
    pid = pattern.get("pattern_id", "<no pattern_id>")
    ctx = ctx or f"pattern {pid}"
    params = pattern.get("parameters")
    if not isinstance(params, dict):
        return errs
    for key in CADENCE_PARAMETERS:
        prm = params.get(key)
        if not isinstance(prm, dict) or prm.get("mode") not in MEASURED_MODES:
            continue
        where = f"{ctx}.{key}.envelope_evidence"
        ev = prm.get("envelope_evidence")
        if not isinstance(ev, dict):
            errs.append(f"{where}: missing - a {prm['mode']} band is a claim about what "
                        f"the pipeline was measured doing, and a claim with no "
                        f"measurement attached can only be checked against the live "
                        f"corpus, which is the corpus the regression is in (CF-0195)")
            continue
        extra = set(ev) - set(ENVELOPE_EVIDENCE_KEYS)
        if extra:
            errs.append(f"{where}: unknown field(s) {sorted(extra)}")
        batches = ev.get("measured_over_batches")
        if not isinstance(batches, list) or not batches or \
                not all(isinstance(b, str) and b.strip() for b in batches):
            errs.append(f"{where}: measured_over_batches must be a non-empty list of "
                        f"batch ids - the fixed point is those batches and nothing else")
        elif len(set(batches)) != len(batches):
            errs.append(f"{where}: duplicate batch ids in {batches}")
        lo, hi = ev.get("observed_min"), ev.get("observed_max")
        nums = []
        for name, val in (("observed_min", lo), ("observed_max", hi)):
            if not isinstance(val, (int, float)) or isinstance(val, bool):
                errs.append(f"{where}: {name} must be a number, got {val!r}")
            else:
                nums.append(val)
        if len(nums) == 2 and nums[0] > nums[1]:
            errs.append(f"{where}: observed_min {lo} > observed_max {hi}")
        for name in ("declared_by", "frozen_by"):
            val = ev.get(name)
            if not isinstance(val, str) or not val.startswith("CF-"):
                errs.append(f"{where}: {name} must name the task the fixed point comes "
                            f"from (got {val!r})")
        if len(nums) == 2 and isinstance(prm.get("min"), (int, float)) and \
                isinstance(prm.get("max"), (int, float)):
            if not (prm["min"] <= nums[1] and prm["max"] >= nums[0]):
                errs.append(f"{where}: the declared band {prm['min']}-{prm['max']} does "
                            f"not overlap the measured span {lo}-{hi} at all - one of "
                            f"the two is describing a different pattern")
    return errs


def envelope_width_errors(pattern, ctx=None):
    """The width guard: a band may not be much wider than its fixed point.

    This is the check CF-0195 exists to make honest, and the sentence that
    explains it is short: *the corpus does not get to set its own tolerance.*
    The span compared against is `envelope_evidence.observed_min/max` - the
    batches named in the pattern file - not `min()`/`max()` over whatever is
    on disk when the check runs. A video that falls outside the band is caught
    by the envelope check; it must never be able to widen the band that is
    supposed to catch it.

    Both cadence parameters are guarded, in whichever unit the pattern states
    the first one (CF-0310: `block_count` or `block_rate_per_minute`, with its
    own slack - see ENVELOPE_SLACK_BLOCKS_PER_MINUTE for why it is a decision
    and not a conversion). `key_frame_hold_seconds` had no width guard of any
    kind before this: the hold could be taken from 8.0s to 20.5s and the suite
    stayed green.

    CF-0314: a `floor_drawn` band is guarded at both ends too, and the two ends
    are guarded for two different reasons that happen to produce the same rule.
    The ceiling is an observation, so it is the emergent case unchanged. The
    floor is an *order* - and an order whose only justification is the
    measurement it was drawn at. Moving it down widens what the pattern accepts
    until it accepts the video that was refused, which is precisely the edit
    this guard exists to stop; moving it up narrows the pattern, and that is a
    decision about the form with its own evidence, not a file edit either. So
    the floor may not leave its fixed point by more than the slack, exactly as
    an emergent one may not - the order is only as honest as its measurement.

    Returns a list of human-readable errors; empty means the band is honest.
    Callers that want to know whether the *measurement* is honest too have to
    re-derive it from the batches on disk - `tests/test_pattern_vocabulary.py`
    does, and that is what stops the numbers here from being edited upward.
    """
    errs = []
    pid = pattern.get("pattern_id", "<no pattern_id>")
    ctx = ctx or f"pattern {pid}"
    params = pattern.get("parameters") or {}
    slack = {BLOCK_COUNT_KEY: ENVELOPE_SLACK_BLOCKS,
             BLOCK_RATE_KEY: ENVELOPE_SLACK_BLOCKS_PER_MINUTE,
             "key_frame_hold_seconds": ENVELOPE_SLACK_SECONDS}
    unit = {BLOCK_COUNT_KEY: " blocks",
            BLOCK_RATE_KEY: " blocks/min",
            "key_frame_hold_seconds": "s"}
    for key in CADENCE_PARAMETERS:
        prm = params.get(key)
        if not isinstance(prm, dict) or prm.get("mode") not in MEASURED_MODES:
            continue
        ev = prm.get("envelope_evidence")
        if not isinstance(ev, dict):
            errs.append(f"{ctx}.{key}: no envelope_evidence, so the width of the band "
                        f"cannot be judged against anything fixed (CF-0195)")
            continue
        lo, hi = ev.get("observed_min"), ev.get("observed_max")
        dmin, dmax = prm.get("min"), prm.get("max")
        if not all(isinstance(x, (int, float)) and not isinstance(x, bool)
                   for x in (lo, hi, dmin, dmax)):
            errs.append(f"{ctx}.{key}: band or measured span is not numeric "
                        f"(band {dmin!r}-{dmax!r}, span {lo!r}-{hi!r})")
            continue
        s = slack[key]
        u = unit[key]
        batches = ", ".join(ev.get("measured_over_batches") or []) or "<none named>"
        if dmin < lo - s:
            # CF-0314: on `floor_drawn` this end is an order, and the sentence
            # says so - dropping it does not merely mis-describe the corpus,
            # it makes the pipeline accept the plan it was written to refuse.
            ordered = ("" if prm.get("mode") != FLOOR_DRAWN_MODE else
                       f" On {FLOOR_DRAWN_MODE} this floor is an order - the pace below "
                       f"which a plan is refused before the render - so dropping it is "
                       f"not a description going stale, it is the refusal being "
                       f"switched off for the video that triggered it.")
            errs.append(
                f"{ctx}.{key}: declared floor {dmin}{u} is more than {s}{u} below the "
                f"{lo}{u} measured over {batches} - a floor dropped to admit a video "
                f"that fell out of the band is the band being written by the thing it "
                f"was meant to catch (CF-0195).{ordered} Widen this only from a batch "
                f"that actually shipped it, listed in envelope_evidence.")
        if dmax > hi + s:
            errs.append(
                f"{ctx}.{key}: declared ceiling {dmax}{u} is more than {s}{u} above the "
                f"{hi}{u} measured over {batches} - same rule, same reason (CF-0195).")
    return errs


def rhythm_usage(patterns=None):
    """rhythm_id -> sorted pattern ids that allow it.

    CF-0015 requires every rhythm to be used by exactly two patterns so that
    pattern and rhythm main effects stay separately estimable for the Analyst.
    Enforced as a test rather than as a schema rule, because adding a fifth
    pattern later legitimately rebalances the map.
    """
    pats = patterns if patterns is not None else load_patterns()
    usage = {}
    for p in pats.values():
        for rid in p.get("allowed_rhythms", []):
            usage.setdefault(rid, []).append(p["pattern_id"])
    return {k: sorted(v) for k, v in usage.items()}


def contribution_text_key(text):
    """What counts as 'the same text' for the duplicate check.

    Whitespace and case are folded so that a copy with a second space or a
    capital letter does not pass as a different contribution; anything beyond
    that is a rewording, and whether a rewording is real is Compliance
    Checker's question (CF-0066), not a validator's.
    """
    return " ".join(str(text).split()).casefold()


def validate_contribution_texts(patterns):
    """CF-0063: a defined original_contribution has to be that pattern's own.

    CF-0043 chose a shared thesis for the channel plus each pattern's own part
    in this field. Per-file validation can only measure length, and forty
    characters are satisfied by any stub - one text pasted into all four files
    would pass and empty the field of meaning. So this is checked across the
    vocabulary: the same text on two patterns is an error naming both.

    Takes `patterns` as {pattern_id: pattern} rather than reading disk, so a
    test can hand it a doctored copy.
    """
    errs = []
    seen = {}
    for pid, pattern in sorted(patterns.items()):
        oc = pattern.get("original_contribution")
        if not isinstance(oc, dict) or oc.get("status") != "defined":
            continue
        if not isinstance(oc.get("text"), str):
            continue
        key = contribution_text_key(oc["text"])
        if key in seen:
            errs.append(f"pattern {pid}.original_contribution: text is the same as "
                        f"{seen[key]}'s - CF-0043 chose a shared thesis plus each "
                        f"pattern's own part; one text reused across patterns is a "
                        f"stub of the field, not a contribution")
        else:
            seen[key] = pid
    return errs


def validate_vocabulary():
    """Validate every file in patterns/. Returns a list of errors."""
    rhythms = load_rhythms()
    errs = validate_rhythms(rhythms)
    if errs:
        return errs
    baselines = []
    patterns = {}
    for path in pattern_files():
        pattern = json.loads(path.read_text())
        errs += validate_pattern(pattern, rhythms, stem=path.stem)
        patterns[path.stem] = pattern
        if pattern.get("baseline"):
            baselines.append(pattern.get("pattern_id"))
    if len(baselines) != 1:
        errs.append(f"vocabulary: exactly one pattern must carry `baseline` - the form "
                    f"already proven end to end (CF-0015); found {baselines}")
    errs += validate_contribution_texts(patterns)
    return errs


def draw_order(pattern, rhythm_id, rng=None, narration_words=None, rhythms=None, *,
               channel=None):
    """The draw Content Researcher performs once a pair has been assigned.

    Returns the `pattern` object it writes into 03-content-researcher.json.
    Drawn parameters get a value inside the declared range; emergent ones get
    null, because the pattern does not steer them and writing a number there
    would turn an observation into an order.

    With `narration_words` (CF-0086) the draw is also checked against the
    voice it will be read over - see `fit_order_to_voice`: a block count the
    drawn hold cannot fit on that many words is recomputed here, in writing,
    rather than left for the resolver to overshoot silently; a pair that
    cannot fit at any value in its bands raises OrderDoesNotFitVoice.

    On the `hold` rhythm the hold is drawn from `hold_draw_band` rather than
    from the pattern's band (CF-0300): there the montage grows the held block
    until it *reaches* this number, so a draw near the top of the band leaves
    the block no room to stop under it.

    CF-0633: the voice check reads the channel's rate, so `narration_words`
    needs `channel`; a draw without words reads no channel and needs none.
    """
    if narration_words is not None:
        _require_channel(channel, "draw_order(narration_words=...)")
    rng = rng or random.Random()
    if rhythm_id not in pattern["allowed_rhythms"]:
        raise ValueError(f"{pattern['pattern_id']} does not allow rhythm {rhythm_id!r}")
    p = pattern["parameters"]
    hold_window = hold_draw_band(pattern, rhythm_id, rhythms)

    def span(cfg, integral):
        # CF-0310: a pattern that states its blocks as a rate has no
        # `block_count` band to draw from, and nothing downstream wants one -
        # a rate is never drawn (CF-0314: not on `floor_drawn` either - a floor
        # is the edge of what is accepted, not a value inside a range), and the
        # order's shape does not change (the key stays, the value is null,
        # which is what "the pattern does not steer this" has always been
        # written as).
        if not draws_a_value(cfg):
            return None
        if integral:
            return rng.randint(cfg["min"], cfg["max"])
        return round(rng.uniform(cfg["min"], cfg["max"]), 2)

    acc_cfg = p["acceleration_to_payoff"]
    enabled = rng.choice(acc_cfg["enabled_choices"]) if acc_cfg["mode"] == "drawn" else None
    strength = None
    if enabled and acc_cfg.get("strength"):
        strength = round(rng.uniform(acc_cfg["strength"]["min"], acc_cfg["strength"]["max"]), 2)

    opening = None
    if p["opening_block"]["mode"] == "drawn":
        opening = rng.choice(p["opening_block"]["choices"])

    order = {
        "pattern_id": pattern["pattern_id"],
        "rhythm_id": rhythm_id,
        "parameters": {
            "block_count": span(p.get(BLOCK_COUNT_KEY), integral=True),
            "key_frame_hold_seconds": (
                None if hold_window is None
                else min(round(rng.uniform(*hold_window), 2), hold_window[1])),
            "opening_block": opening,
            "acceleration_to_payoff": {"enabled": enabled, "strength": strength},
        },
    }
    if narration_words is not None:
        order = fit_order_to_voice(order, pattern, narration_words, channel=channel)
    return order


# --------------------------------------------------------------------------
# CF-0086: does the order fit the voice it will be read over?
# --------------------------------------------------------------------------
#
# `key_frame_hold_seconds` is the longest block the finished video may contain
# (schema above), so `block_count` blocks can cover at most
# block_count * key_frame_hold_seconds of narration. Video Editor's rhythm.py
# applies exactly that arithmetic when it divides a stretch into pieces
# (`by_cap = ceil(duration / cap)`), and the ceiling is not negotiable there:
# a block count that does not fit under it is overshot, the overshoot lands
# outside the pattern's band, and the pattern is recorded as not delivered.
# Batch 2026-09-03T2037Z, video 001 (Raygun): list on staccato, block_count 20
# under a 1.4s hold, on a narration that took 69.7s to read - 20 x 1.4 = 28s of
# room for 69.7s of voice, so the resolver cut 54 pieces and the order was
# never executable as written. The first sign of that was a number deep inside
# the resolver's log, which is a side effect, not a diagnosis.
#
# The check lives at the draw, before any of that: given the words that will
# be read, either the order fits, or its block count (and failing that its
# hold) is recomputed to the smallest value that does, in writing; a pair that
# cannot fit at the top of both bands is refused with a reason the agent can
# put into `rotation/rotate.py reject`. The estimate is the voice length the
# narration *will* have, not the one it has - there is no voice.wav yet.


class OrderDoesNotFitVoice(ValueError):
    """The pair cannot cover the narration at any value inside its bands.

    Carries the same report `check_order_fits_voice` returns, plus the reason
    text written for the rotation's rejection valve.
    """

    def __init__(self, reason, report):
        super().__init__(reason)
        self.reason = reason
        self.report = report


def narration_word_count(script):
    """Words the voice will read: hook + commentary + payoff, whitespace-split.

    The count the narration is measured by, and the only one the estimate
    should use - `total_word_count` written by the agent is a self-report, and
    on the Raygun script it was three words under what was actually read.
    """
    return sum(len(str(script.get(k) or "").split()) for k in NARRATION_SECTIONS)


def expected_voice_seconds(narration_words, channel):
    """The voice length `narration_words` is expected to take at the channel's
    rate (CF-0633: the channel is required)."""
    return narration_words / narration_rate(channel)[0]


def _min_block_count(seconds, hold):
    # rhythm.py's `by_cap`, verbatim: the number of pieces the cap forces.
    return max(1, math.ceil(seconds / hold - 1e-9))


def block_cap_seconds(order, pattern=None):
    """The longest one block may run under this order, and where that comes from.

    On every rhythm but `hold` it is the drawn `key_frame_hold_seconds`: the
    montage divides each stretch by that number (`rhythm._plan_staccato`'s
    `by_cap`), so it is the cap the arithmetic below is about.

    On `hold` the drawn number is not a cap at all (CF-0300) - `_plan_hold`
    never divides anything by it; it *grows* one block until it reaches it and
    then keeps every other block shorter than that one. The number that caps a
    block there is the pattern's own ceiling, `key_frame_hold_seconds.max`, and
    reading the drawn value as a cap is what used to push it to the top of the
    band: a block count that would not fit was answered by raising the hold,
    and the raised hold was exactly the draw that overshoots. Without a
    `pattern` there is nothing to read that ceiling from, so the drawn value
    stands and the answer is the pre-CF-0300 one.
    """
    hold = (order.get("parameters") or {}).get("key_frame_hold_seconds")
    if order.get("rhythm_id") != HOLD_RHYTHM_ID or pattern is None:
        return hold, "the drawn key_frame_hold_seconds"
    cfg = pattern["parameters"]["key_frame_hold_seconds"]
    if not draws_a_value(cfg):
        return hold, "the drawn key_frame_hold_seconds"
    return float(cfg["max"]), (f"{pattern['pattern_id']}'s hold band top "
                               f"(the drawn hold is a floor on this rhythm)")


def check_order_fits_voice(order, narration_words, pattern=None, *, channel):
    """Report whether the drawn block count and hold can cover the narration.

    Pure arithmetic over an already written order, so it can be run over a
    03-content-researcher.json after the fact (`check-orders` below). An order
    with nothing drawn - emergent block count or hold - always fits: there is
    no number to be unreachable.

    With a `pattern` the cap is read through `block_cap_seconds`, which on the
    `hold` rhythm is the pattern's band top rather than the drawn hold
    (CF-0300). Without one the answer is unchanged.

    CF-0633: `channel` (an id, a config or a `narration_budget` block) is the
    channel whose rate the narration is read at; required.
    """
    rate, rate_source = narration_rate(channel)
    params = order.get("parameters") or {}
    bc = params.get("block_count")
    hold = params.get("key_frame_hold_seconds")
    seconds = narration_words / rate
    cap, cap_source = block_cap_seconds(order, pattern)
    report = {
        "narration_words": narration_words,
        "words_per_second": rate,
        "words_per_second_source": rate_source,
        "expected_voice_seconds": round(seconds, 1),
        "block_count": bc,
        "key_frame_hold_seconds": hold,
        "block_cap_seconds": cap,
        "block_cap_source": cap_source,
    }
    if bc is None or cap is None:
        report.update(fits=True, max_content_seconds=None, min_block_count=None,
                      reason="nothing drawn - the block count and hold are emergent")
        return report
    room = bc * cap
    need = _min_block_count(seconds, cap)
    report.update(max_content_seconds=round(room, 1), min_block_count=need, fits=bc >= need)
    if report["fits"]:
        report["reason"] = (f"{bc} blocks under a {cap:.2f}s cap ({cap_source}) hold "
                            f"{room:.1f}s, the narration is expected to take {seconds:.1f}s")
    else:
        report["reason"] = (
            f"block_count {bc} is unreachable under the {cap:.2f}s cap ({cap_source}) on a "
            f"narration expected to take {seconds:.1f}s ({narration_words} words at "
            f"{rate} w/s, {rate_source}): {bc} x {cap:.2f} = "
            f"{room:.1f}s of room, the cap forces at least {need} pieces")
    return report


def check_hold_draw(order, pattern, rhythms=None):
    """CF-0300: is this order's drawn hold inside the window it may be drawn from?

    None when it is, or when there is nothing to judge (no hold drawn, or the
    parameter is emergent). Otherwise a finding naming the drawn value, the
    window, the pattern's untouched envelope and what happens to the block.

    This is the reading that catches a hold written *by hand*. `draw_order`
    cannot produce a value outside the window, but nothing in the pipeline
    calls `draw_order`: the operator of the Content Researcher stage draws the
    four parameters themselves, which is how batch 2026-09-19T0116Z came to
    carry a `list` hold of 2.50 - the top of the band - raised there to get
    past a block-capacity gate.
    """
    if order.get("rhythm_id") != HOLD_RHYTHM_ID:
        return None
    hold = (order.get("parameters") or {}).get("key_frame_hold_seconds")
    window = hold_draw_band(pattern, HOLD_RHYTHM_ID, rhythms)
    if hold is None or window is None:
        return None
    lo, hi = window
    if lo - 1e-9 <= hold <= hi + 1e-9:
        return None
    band = pattern["parameters"]["key_frame_hold_seconds"]
    return {
        "finding": "hold_drawn_outside_the_window",
        "pattern_id": pattern.get("pattern_id"),
        "rhythm_id": HOLD_RHYTHM_ID,
        "key_frame_hold_seconds": hold,
        "draw_window": [lo, hi],
        "band": [band["min"], band["max"]],
        "reason": (
            f"{pattern.get('pattern_id')} on {HOLD_RHYTHM_ID} drew "
            f"key_frame_hold_seconds {hold:.2f}, outside the window "
            f"{lo:.2f}-{hi:.2f} this rhythm may draw from. The band "
            f"{band['min']}-{band['max']} is unchanged and is the ceiling the "
            f"montage may not break; on this rhythm the drawn number is a floor "
            f"the held block is grown to by swallowing whole stretches of "
            f"narration, so a draw this high leaves the block no length it can "
            f"stop at under the ceiling (CF-0300). Redraw inside the window, or "
            f"reject the assignment in writing (rotation/rotate.py reject)"),
    }


def fit_order_to_voice(order, pattern, narration_words, *, channel):
    """Return the order with a `voice_fit` record, recomputed if it had to be.

    The smallest change that makes the order executable, in this order:
    block_count up to what the drawn hold needs, inside the pattern's band;
    failing that, the hold up to what the band's top block count needs, inside
    its own band. Whatever moved is written under `voice_fit.recomputed` as
    (drawn, recomputed) pairs, so the ledger and 03-content-researcher.json
    show that the number was not the draw. The rotation's pair is never
    touched here: the pair is the rotation's decision, and a pair that cannot
    fit at the top of both bands is refused with a written reason
    (OrderDoesNotFitVoice) for `rotate.py reject`, not swapped quietly.

    CF-0633: `channel` (an id, a config or a `narration_budget` block) is the
    channel whose rate the narration is read at; required.
    """
    rate, rate_source = narration_rate(channel)
    order = json.loads(json.dumps(order))
    params = order["parameters"]
    report = check_order_fits_voice(order, narration_words, pattern, channel=channel)
    recomputed = {}
    if not report["fits"]:
        bands = pattern["parameters"]
        if BLOCK_COUNT_KEY not in bands:
            # CF-0310: this pattern states its blocks as a rate, so it has no
            # count band to raise the order into. It also never draws a count
            # (the rate is emergent, the order carries null) and an order with
            # no count always fits - so getting here means a count was written
            # into the order by hand against a pattern that orders none. Say
            # that, rather than dying on a missing key three lines down.
            raise OrderDoesNotFitVoice(
                f"{order['pattern_id']} states its blocks as "
                f"{BLOCK_RATE_KEY} and orders no block count, but this order "
                f"carries block_count {params['block_count']!r} - there is no "
                f"band to recompute it inside. Remove the number: on this "
                f"pattern the count is observed, not ordered (CF-0310)",
                report)
        bc_max = bands[BLOCK_COUNT_KEY]["max"]
        hold_max = bands["key_frame_hold_seconds"]["max"]
        seconds = narration_words / rate
        bc, hold = params["block_count"], params["key_frame_hold_seconds"]
        need = report["min_block_count"]
        # CF-0300: raising the hold only buys room where the hold is the cap.
        # On the `hold` rhythm the cap is already the band's top, so there is
        # nothing above it to raise into - and raising the *drawn* hold there
        # buys no room at all, it only moves the held block towards the
        # ceiling. A pair that does not fit at the top of the block count is
        # refused instead of being quietly pushed into the forbidden window.
        hold_is_the_cap = report["block_cap_source"] == "the drawn key_frame_hold_seconds"
        if need <= bc_max:
            recomputed["block_count"] = [bc, need]
            params["block_count"] = need
        elif hold_is_the_cap and seconds <= bc_max * hold_max + 1e-9:
            hold_need = math.ceil(seconds / bc_max / HOLD_GRID - 1e-9) * HOLD_GRID
            hold_need = round(min(hold_need, hold_max), 2)
            if bc != bc_max:
                recomputed["block_count"] = [bc, bc_max]
            recomputed["key_frame_hold_seconds"] = [hold, hold_need]
            params["block_count"] = bc_max
            params["key_frame_hold_seconds"] = hold_need
        else:
            # The room is always measured at the top of both bands: on a cap
            # rhythm because the hold has just been raised as far as it goes,
            # on `hold` because the band's top is the cap from the start.
            max_words = math.floor(bc_max * hold_max * rate)
            floor_note = ("" if hold_is_the_cap else
                          " (on this rhythm the drawn hold is a floor, so the band's top "
                          "is the cap and raising the draw buys no room)")
            reason = (
                f"{order['pattern_id']} on {order['rhythm_id']} cannot cover this "
                f"narration at any value in its bands: {bc_max} blocks x {hold_max:.2f}s "
                f"= {bc_max * hold_max:.1f}s of room against an expected "
                f"{seconds:.1f}s voice ({narration_words} words at {rate} w/s, "
                f"{rate_source}){floor_note}. Either cut the narration to at "
                f"most {max_words} words, or reject the assignment in writing "
                f"(rotation/rotate.py reject) with this reason")
            report["reason"] = reason
            raise OrderDoesNotFitVoice(reason, report)
        report = check_order_fits_voice(order, narration_words, pattern, channel=channel)
        assert report["fits"], report
    drawn = check_hold_draw(order, pattern)
    order["voice_fit"] = dict(report, verdict="recomputed" if recomputed else "fits",
                              recomputed=recomputed, hold_draw=drawn)
    return order


def check_orders(scripts, patterns=None, *, channel):
    """Run the check over the scripts of a 03-content-researcher.json.

    Yields (script_id, report, would_fit) where `would_fit` is the record
    `fit_order_to_voice` would have written, or the reason it would have
    refused. Pure: nothing on disk is changed.

    CF-0300: the report also carries `hold_draw` - None, or the finding that
    this order's hold was written outside the window the `hold` rhythm may
    draw from. It is a separate question from the voice fit and is reported
    even on an order that fits.

    `channel` is the batch's - the rate the narration is read at (CF-0633).
    """
    patterns = patterns or load_patterns()
    for s in scripts:
        order = s.get("pattern") or {}
        words = narration_word_count(s)
        pattern = patterns.get(order.get("pattern_id"))
        report = check_order_fits_voice(order, words, pattern, channel=channel)
        report["hold_draw"] = None if pattern is None else check_hold_draw(order, pattern)
        would = None
        if not report["fits"] and order.get("pattern_id") in patterns:
            try:
                would = fit_order_to_voice(order, patterns[order["pattern_id"]], words,
                                           channel=channel)["voice_fit"]
            except OrderDoesNotFitVoice as e:
                would = {"verdict": "does_not_fit", "reason": e.reason}
        yield s.get("script_id"), report, would


def _channel_option(args):
    """CF-0633: `[--channel <id>] <file> [...]` -> (channel or None, files)."""
    args = list(args)
    channel = None
    if "--channel" in args:
        i = args.index("--channel")
        if i + 1 >= len(args):
            return False, []
        channel = args[i + 1]
        del args[i:i + 2]
    return channel, args


def _batch_channel(data, channel, path):
    """CF-0633: the channel a batch file is read at - `--channel` when given,
    else the file's own `channel` field, a former id resolved either way
    (CF-0197). None when neither names one: the caller refuses, it does not
    pick a channel."""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    from shared.channel_ids import resolve_channel  # noqa: PLC0415 - root's door
    resolved = resolve_channel(
        channel or (data.get("channel") if isinstance(data, dict) else None), ROOT)
    if not resolved:
        print(f"{path}: names no channel and none was given with --channel - the rate and "
              f"band are a channel's, and this check picks none for you (CF-0633)")
    return resolved


def _check_orders_cli(args):
    channel, paths = _channel_option(args)
    if not paths or channel is False:
        print("usage: validate_patterns.py check-orders [--channel <id>] "
              "<03-content-researcher.json> [...]")
        return 2
    bad = 0
    for path in paths:
        data = json.loads(Path(path).read_text())
        scripts = data.get("scripts", []) if isinstance(data, dict) else data
        batch_channel = _batch_channel(data, channel, path)
        if not batch_channel:
            return 2
        print(f"{path}: {len(scripts)} script(s)")
        for sid, report, would in check_orders(scripts, channel=batch_channel):
            pat = f"{report['block_count']} x {report['key_frame_hold_seconds']}"
            drawn = report.get("hold_draw")
            if drawn:
                bad += 1
                print(f"  HOLD  {sid}: {drawn['reason']}")
            if report["fits"]:
                if not drawn:
                    print(f"  ok    {sid}: {pat}, {report['expected_voice_seconds']}s expected "
                          f"({report['narration_words']} words)")
                continue
            bad += 1
            print(f"  UNFIT {sid}: {report['reason']}")
            if would and would["verdict"] == "recomputed":
                print(f"        would recompute {would['recomputed']}")
            elif would:
                print(f"        {would['reason']}")
    return 1 if bad else 0


# --------------------------------------------------------------------------
# CF-0119: is each half of a contrast pair short enough to cut?
# --------------------------------------------------------------------------
#
# CF-0050 made the sides of `alternate` a property of the script: one block per
# crossing of the axis. It follows that the length of a block is set by the
# writing - by how many anchors in a row the commentary left on one side - and
# not by the order. CF-0057 measured what that costs when the writing does not
# cooperate: a run of one side longer than the drawn `key_frame_hold_seconds`
# is almost always delivered as a frame that stops moving (the resolver freezes
# a frame when no clip that long is in the pool), 15.17 s on the one real
# alternate plan, and at this pattern's 1.5-3.5 s band a run of two anchors
# leaves the band on 7 scripts out of 11, a run of three on 11 out of 11.
#
# CF-0074 chose to fix that in the writing (variant 3): the pairs are short,
# one anchor a side per crossing, and the check that catches a long half runs
# on the script rather than on the plan - before there is a montage to blame.
# This is that check. It is arithmetic over an already written script, the same
# shape as `check_order_fits_voice` above: the band comes from the pattern's
# own rhythm parameter (`side_length.seconds_from` -> the order's drawn hold,
# or the pattern band's maximum when nothing was drawn) and the channel's
# measured words a second, so no number in this file is a literal. A half over
# the band is a machine-readable finding naming the pair and the side, and the
# script goes back for a rewrite on the same non-zero exit `check-orders` uses.

CONTRAST_PATTERN_ID = "contrast"
SIDE_LENGTH_KEY = "side_length"
SIDE_LENGTH_KNOWN_KEYS = ("max_anchors_per_side", "seconds_from",
                          "words_per_second_from", "note")
# The two halves of a pair, named as CF-0050 names the sides.
PAIR_SIDES = ("a", "b")
PAIR_TOO_LONG = "contrast_pair_too_long"
PAIR_UNMATCHED = "contrast_pair_unmatched"


def validate_side_length(pattern, ctx=None):
    """Errors for a pattern's optional `side_length` block; [] when absent.

    The block names where the band comes from, never the band itself: a
    seconds ceiling written here would be a second copy of
    `key_frame_hold_seconds`, and the two would drift.
    """
    cfg = pattern.get(SIDE_LENGTH_KEY)
    if cfg is None:
        return []
    ctx = ctx or f"pattern {pattern.get('pattern_id', '<no pattern_id>')}"
    sctx = f"{ctx}.{SIDE_LENGTH_KEY}"
    if not isinstance(cfg, dict):
        return [f"{sctx}: must be an object"]
    errs = []
    unknown = sorted(k for k in cfg if k not in SIDE_LENGTH_KNOWN_KEYS)
    if unknown:
        errs.append(f"{sctx}: unknown key(s) {unknown} - the check reads only "
                    f"{list(SIDE_LENGTH_KNOWN_KEYS)}")
    cap = cfg.get("max_anchors_per_side")
    if not isinstance(cap, int) or isinstance(cap, bool) or cap < 1:
        errs.append(f"{sctx}.max_anchors_per_side: must be an integer >= 1, got {cap!r}")
    src = cfg.get("seconds_from")
    if src not in PARAMETER_KEYS:
        errs.append(f"{sctx}.seconds_from: must name one of the parameters "
                    f"{list(PARAMETER_KEYS)}, got {src!r}")
    else:
        band = (pattern.get("parameters") or {}).get(src)
        if not isinstance(band, dict) or not isinstance(band.get("max"), (int, float)) \
                or isinstance(band.get("max"), bool):
            errs.append(f"{sctx}.seconds_from: {src!r} carries no numeric max on this "
                        f"pattern, so there is no band to read")
    rate_from = cfg.get("words_per_second_from")
    if not isinstance(rate_from, str) or not rate_from.strip():
        errs.append(f"{sctx}.words_per_second_from: must name where the rate is read "
                    f"from (the channel config key), got {rate_from!r}")
    return errs


def side_length_band(pattern, order=None, *, channel):
    """The band one half of a pair may not exceed, and where every number in
    it came from.

    Seconds: the order's drawn value for the parameter `side_length` names
    (`key_frame_hold_seconds` on contrast) - that is the number a rhythm
    shortfall is measured against, CF-0057 - falling back to the pattern
    band's maximum when the script carries no drawn value. Words: those
    seconds at the channel's measured rate. Anchors: `max_anchors_per_side`.

    CF-0633: `channel` - an id, a config path, a config or a
    `narration_budget` block (`narration_budget_of()`) - is required; the rate
    is the channel's, never this module's.
    """
    errs = validate_side_length(pattern)
    if errs:
        raise ValueError("; ".join(errs))
    cfg = pattern.get(SIDE_LENGTH_KEY)
    if cfg is None:
        raise ValueError(
            f"pattern {pattern.get('pattern_id')!r} carries no {SIDE_LENGTH_KEY} block, "
            f"so there is no band to check a pair against - CF-0119 put the band in the "
            f"pattern file next to the hold it is read from, and this check invents no "
            f"default")
    param = cfg["seconds_from"]
    drawn = ((order or {}).get("parameters") or {}).get(param)
    if isinstance(drawn, (int, float)) and not isinstance(drawn, bool) and drawn > 0:
        seconds, seconds_source = float(drawn), "order"
    else:
        seconds, seconds_source = float(pattern["parameters"][param]["max"]), "pattern"
    rate, rate_source = narration_rate(channel)
    return {
        "max_anchors_per_side": cfg["max_anchors_per_side"],
        "max_seconds": round(seconds, 2),
        "max_words": int(math.floor(seconds * rate + 1e-9)),
        "seconds_from": param,
        "seconds_source": seconds_source,
        "words_per_second": rate,
        "words_per_second_source": rate_source,
    }


def _half_anchors(half):
    """The anchors of one half of a pair, as a list of strings.

    A string is one anchor - that is the shape the writing instruction asks
    for. A list is as many anchors as it has entries, which is how a writer
    spells out a half that runs longer than one, and how this check can count
    it. Empty and missing halves come back as no anchors at all.
    """
    if half is None:
        return []
    if isinstance(half, str):
        return [half] if half.strip() else []
    if isinstance(half, dict):
        for key in ("anchors", "text"):
            if key in half:
                return _half_anchors(half[key])
        return []
    if isinstance(half, (list, tuple)):
        out = []
        for item in half:
            out += _half_anchors(item)
        return out
    return _half_anchors(str(half))


def measure_half(half, band):
    """Anchors, words and expected seconds of one half of a pair."""
    anchors = _half_anchors(half)
    words = sum(len(a.split()) for a in anchors)
    return {
        "anchors": len(anchors),
        "words": words,
        "seconds": round(words / band["words_per_second"], 2),
    }


def check_contrast_pairs(script, pattern=None, *, channel):
    """Walk a contrast script's declared pairs and measure both halves.

    Returns a report; `findings` is the machine-readable part, one entry per
    half that may not be written as it stands:

        {"kind": "contrast_pair_too_long", "pair": 3, "side": "b",
         "anchors": 3, "words": 31, "seconds": 11.27, "band": {...}}

    `verdict` is "return_for_rewrite" when there is any finding - the same
    answer `check-orders` gives an order that does not fit the voice, and the
    CLI below exits non-zero on it. "not_applicable" for a script written on
    another pattern; "no_pairs_declared" for a contrast script that carries no
    `pattern.sides.pairs` (batches written before CF-0119 do not), which is
    reported but is not a rewrite: nothing was measured.
    """
    order = script.get("pattern") or {}
    pid = order.get("pattern_id")
    report = {
        "script_id": script.get("script_id"),
        "pattern_id": pid,
        "verdict": "not_applicable",
        "band": None,
        "pairs": [],
        "findings": [],
        "reason": f"pattern_id is {pid!r}, not {CONTRAST_PATTERN_ID!r} - the pair rule is "
                  f"this pattern's own",
    }
    if pid != CONTRAST_PATTERN_ID:
        return report
    if pattern is None:
        pattern = load_patterns()[CONTRAST_PATTERN_ID]
    band = side_length_band(pattern, order, channel=channel)
    report["band"] = band
    pairs = (order.get("sides") or {}).get("pairs")
    if not isinstance(pairs, list) or not pairs:
        report["verdict"] = "no_pairs_declared"
        report["reason"] = (
            f"contrast script with no pattern.sides.pairs - nothing to measure. The "
            f"pairs are the writer's own record of where the commentary crosses the "
            f"axis (CF-0119); a script written under the current instruction carries "
            f"them")
        return report
    findings = []
    for index, pair in enumerate(pairs, start=1):
        row = {"pair": index}
        for side in PAIR_SIDES:
            half = pair.get(side) if isinstance(pair, dict) else None
            m = measure_half(half, band)
            row[side] = m
            finding = dict(m, pair=index, side=side, band=band)
            if m["anchors"] == 0:
                finding["kind"] = PAIR_UNMATCHED
                finding["note"] = (
                    f"pair {index} has no side {side}: a claim about one side with no "
                    f"answering claim about the other is an argument, not a comparison, "
                    f"and it leaves the montage nothing to cut to")
                findings.append(finding)
            elif m["anchors"] > band["max_anchors_per_side"] or \
                    m["seconds"] > band["max_seconds"] + 1e-9:
                finding["kind"] = PAIR_TOO_LONG
                finding["note"] = (
                    f"pair {index} side {side} runs {m['anchors']} anchor(s), "
                    f"{m['words']} words, about {m['seconds']:.2f}s; the band is "
                    f"{band['max_anchors_per_side']} anchor and {band['max_seconds']:.2f}s "
                    f"({band['max_words']} words at {band['words_per_second']} w/s), the "
                    f"{band['seconds_source']}'s {band['seconds_from']}. A run this long "
                    f"is one block the montage can only fill with a frame that stops "
                    f"moving (CF-0057) - split it into that many pairs")
                findings.append(finding)
        report["pairs"].append(row)
    report["findings"] = findings
    report["verdict"] = "return_for_rewrite" if findings else "ok"
    longest = max((max(r["a"]["seconds"], r["b"]["seconds"]) for r in report["pairs"]),
                  default=0.0)
    report["reason"] = (
        f"{len(report['pairs'])} pair(s), longest half {longest:.2f}s against a "
        f"{band['max_seconds']:.2f}s / {band['max_anchors_per_side']}-anchor band from the "
        f"{band['seconds_source']}'s {band['seconds_from']} at "
        f"{band['words_per_second']} w/s ({band['words_per_second_source']})")
    return report


def check_pairs(scripts, patterns=None, *, channel):
    """Run the pair check over the scripts of a 03-content-researcher.json.

    Yields one report per script, contrast or not. Pure: nothing on disk is
    changed. `channel` is the batch's (CF-0633).
    """
    patterns = patterns or load_patterns()
    for s in scripts:
        yield check_contrast_pairs(s, patterns.get(CONTRAST_PATTERN_ID), channel=channel)


def _check_pairs_cli(args):
    channel, paths = _channel_option(args)
    if not paths or channel is False:
        print("usage: validate_patterns.py check-pairs [--channel <id>] "
              "<03-content-researcher.json> [...]")
        return 2
    bad = 0
    for path in paths:
        data = json.loads(Path(path).read_text())
        scripts = data.get("scripts", []) if isinstance(data, dict) else data
        batch_channel = _batch_channel(data, channel, path)
        if not batch_channel:
            return 2
        reports = [r for r in check_pairs(scripts, channel=batch_channel)]
        contrast = [r for r in reports if r["verdict"] != "not_applicable"]
        print(f"{path}: {len(contrast)} contrast script(s) of {len(scripts)}")
        for r in contrast:
            sid = r["script_id"]
            if r["verdict"] == "no_pairs_declared":
                print(f"  NOPAIRS {sid}: {r['reason']}")
                continue
            if r["verdict"] == "ok":
                print(f"  ok      {sid}: {r['reason']}")
                continue
            bad += 1
            print(f"  REWRITE {sid}: {len(r['findings'])} finding(s), {r['reason']}")
            for f in r["findings"]:
                print(f"          {f['kind']} pair {f['pair']} side {f['side']}: "
                      f"{f['note']}")
    return 1 if bad else 0


# --------------------------------------------------------------------------
# CF-0565: the `scale` pattern's arithmetic, recomputed
# --------------------------------------------------------------------------
#
# A scale script carries one number from the source onto a familiar stand-in
# by one factor (patterns/scale.json). A comparison sounds true whether or not
# its numbers are, so the writer's arithmetic is a record - `script.scale` -
# and this is the deterministic half of its gate: every number of the record
# is found in its own quote, the source's number is in the fact record the
# writer copied (`script.fact`, never retyped), the result is recomputed, and
# the words the voice says for it may not overstate it. The other half - that
# the comparison as said follows from its footing - is the claim judge's
# (agents/content-researcher/scripts/check_claims.py, CF-0553).

SCALE_PATTERN_ID = "scale"
SCALE_FOOTING_KEY = "scale_footing"
SCALE_PARTS = ("quantity", "reference", "familiar")
SCALE_SPOKEN_FIELDS = ("hook", "commentary", "payoff")

# Units the recompute converts between: one family each, to the family's base.
SCALE_UNITS = {
    "mm": ("length", 1e-3), "cm": ("length", 1e-2), "m": ("length", 1.0),
    "km": ("length", 1e3), "au": ("length", 1.495978707e11),
    "light-year": ("length", 9.4607304725808e15), "ly": ("length", 9.4607304725808e15),
    "s": ("time", 1.0), "min": ("time", 60.0), "h": ("time", 3600.0),
    "day": ("time", 86400.0), "year": ("time", 31557600.0),
    "g": ("mass", 1e-3), "kg": ("mass", 1.0), "t": ("mass", 1e3),
    "m/s": ("speed", 1.0), "km/s": ("speed", 1e3), "km/h": ("speed", 1 / 3.6),
}
_SCALE_MULTIPLIERS = {"thousand": 1e3, "million": 1e6, "billion": 1e9, "trillion": 1e12}
_SCALE_NUMBER = re.compile(
    r"(?<![\w.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?(?:\s+(thousand|million|billion|trillion))?",
    re.IGNORECASE)


# CF-0673: numbers said in words. The Content Researcher's «Write for the
# ear» rule has the voice say «about three thousand four hundred kilometres»,
# not «3,400», and a said_as in words was invisible to `scale_overstated`.
_WORD_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19,
}
_WORD_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fifty": 50, "sixty": 60,
              "seventy": 70, "eighty": 80, "ninety": 90}
_WORD_HUNDRED = "hundred"
_WORD_SCALES = dict(_SCALE_MULTIPLIERS)
_WORD_NUMBER_WORDS = set(_WORD_UNITS) | set(_WORD_TENS) | {_WORD_HUNDRED} | set(_WORD_SCALES)
_WORD_TOKEN = re.compile(r"[a-z]+", re.IGNORECASE)


def _word_numbers(text):
    """[(position, value)] of every number spelt out in English in `text`:
    «three thousand four hundred» 3400, «twelve» 12, «forty-two» 42, «a
    hundred» 100, «two and a half thousand» 2500, «one point three nine
    million» 1.39e6. A run starts on a number word (or «a» right before
    hundred / thousand / million / ...), so the «million» of «1.39 million» -
    read with its digits by `_SCALE_NUMBER` - is never read a second time."""
    found = list(_WORD_TOKEN.finditer(text))
    toks = [(m.start(), m.group(0).lower()) for m in found]
    # a run of number words is joined by spaces and hyphens only - a comma or
    # a full stop between two words ends it («forty-two, three» is two numbers)
    joined = [i > 0 and not text[found[i - 1].end():found[i].start()].strip(" -\t")
              for i in range(len(found))]
    out, i, n = [], 0, len(toks)
    while i < n:
        pos, w = toks[i]
        lead_a = (w == "a" and i + 1 < n and
                  (toks[i + 1][1] == _WORD_HUNDRED or toks[i + 1][1] in _WORD_SCALES))
        if not (w in _WORD_UNITS or w in _WORD_TENS or lead_a):
            i += 1
            continue
        total, current, seen, j, last = 0.0, 0.0, False, i, None
        if lead_a:
            current, seen, j, last = 1.0, True, i + 1, "a"
        while j < n:
            w = toks[j][1]
            if j > i and not joined[j]:
                break
            if w in _WORD_TENS and last in (None, "hundred", "scale", "and"):
                current += _WORD_TENS[w]
                seen, last = True, "tens"
                j += 1
            elif w in _WORD_UNITS and last in (None, "tens", "hundred", "scale", "and") and \
                    not (last == "tens" and _WORD_UNITS[w] >= 10):
                current += _WORD_UNITS[w]
                seen, last = True, "unit"
                j += 1
            elif w == _WORD_HUNDRED and seen and last in ("unit", "a"):
                current = (current or 1.0) * 100
                last = "hundred"
                j += 1
            elif w in _WORD_SCALES and seen and last != "scale":
                total += (current or 1.0) * _WORD_SCALES[w]
                current, last = 0.0, "scale"
                j += 1
            elif w == "point" and seen and j + 1 < n and toks[j + 1][1] in _WORD_UNITS \
                    and _WORD_UNITS[toks[j + 1][1]] < 10:
                digits, k = "", j + 1
                while k < n and toks[k][1] in _WORD_UNITS and _WORD_UNITS[toks[k][1]] < 10:
                    digits += str(_WORD_UNITS[toks[k][1]])
                    k += 1
                current += float("0." + digits)
                j, last = k, "point"
            elif w == "and" and seen and j + 2 < n and toks[j + 1][1] == "a" \
                    and toks[j + 2][1] == "half":
                current += 0.5
                j, last = j + 3, "half"
            elif w == "and" and last in ("hundred", "scale") and j + 1 < n and (
                    toks[j + 1][1] in _WORD_UNITS or toks[j + 1][1] in _WORD_TENS):
                j, last = j + 1, "and"       # «three hundred and forty»
            else:
                break
        out.append((pos, float(f"{total + current:.12g}")))
        i = max(j, i + 1)
    return out


def numbers_in(text):
    """Every number written in `text` as a float, in the order they stand -
    digits with thousands commas and decimals, a following «thousand /
    million / billion / trillion» multiplying them, and (CF-0673) numbers
    spelt out in English words («about three thousand four hundred
    kilometres» is 3400), so a said_as written for the ear is checked like
    one written in digits."""
    text = str(text or "")
    out = []
    for m in _SCALE_NUMBER.finditer(text):
        whole = m.group(1).replace(",", "")
        val = float(whole + ("." + m.group(2) if m.group(2) else ""))
        if m.group(3):
            val *= _SCALE_MULTIPLIERS[m.group(3).lower()]
        out.append((m.start(), val))
    out.extend(_word_numbers(text))
    return [v for _, v in sorted(out, key=lambda pv: pv[0])]


def _scale_rules(pattern):
    rules = ((pattern or {}).get(SCALE_FOOTING_KEY) or {}).get("rules") or {}
    return float(rules.get("arithmetic_tolerance", 0.15)), bool(rules.get("never_overstate", True))


def _number_in_quote(value, quote, rel=0.005):
    return any(abs(n - value) <= rel * max(abs(value), 1e-12) for n in numbers_in(quote))


def check_scale_footing(script, pattern=None):
    """Hold a `scale` script's `script.scale` record to its own arithmetic.

    Returns {"script_id", "pattern_id", "verdict", "computed", "findings",
    "reason"}; `verdict` is "not_applicable" for another pattern, "ok", or
    "return_for_rewrite" with one finding per broken rule:

      scale_record_missing     no `script.scale` on a scale script
      scale_field_missing      a part or a field of it is absent or empty
      scale_unit_unknown       a unit outside SCALE_UNITS, or two families mixed
      scale_number_not_quoted  a value is not a number of its own quote
      scale_quantity_not_from_fact  the quantity's quote is not in `script.fact`
      scale_result_off         the stated result is off the recompute by more
                               than the pattern's tolerance
      scale_overstated         the voice's said_as carries a number above the
                               recompute by more than the tolerance - in digits
                               or in words (CF-0673, `numbers_in`)
      scale_said_as_not_spoken said_as is not a verbatim part of the narration
    """
    order = script.get("pattern") or {}
    pid = order.get("pattern_id")
    report = {"script_id": script.get("script_id"), "pattern_id": pid,
              "verdict": "not_applicable", "computed": None, "findings": [],
              "reason": f"pattern_id is {pid!r}, not {SCALE_PATTERN_ID!r}"}
    if pid != SCALE_PATTERN_ID:
        return report
    if pattern is None:
        pattern = load_patterns()[SCALE_PATTERN_ID]
    tol, never_overstate = _scale_rules(pattern)
    findings = []

    def find(kind, note):
        findings.append({"kind": kind, "note": note})

    sc = script.get("scale")
    if not isinstance(sc, dict):
        find("scale_record_missing",
             "a scale script carries its arithmetic in `script.scale` "
             "(patterns/scale.json scale_footing) - none here, so nothing the voice "
             "compares is checked")
        return _scale_close(report, findings, tol)

    parts = {}
    for name in SCALE_PARTS:
        part = sc.get(name)
        need = ("value", "unit", "quote") + (("source_url",) if name != "quantity" else ())
        if not isinstance(part, dict) or any(
                part.get(k) in (None, "") for k in need):
            find("scale_field_missing", f"scale.{name} needs {list(need)}")
            continue
        if not isinstance(part["value"], (int, float)) or isinstance(part["value"], bool) \
                or part["value"] <= 0:
            find("scale_field_missing", f"scale.{name}.value must be a positive number")
            continue
        if part["unit"] not in SCALE_UNITS:
            find("scale_unit_unknown", f"scale.{name}.unit {part['unit']!r} is not one of "
                                       f"{sorted(SCALE_UNITS)}")
            continue
        if not _number_in_quote(part["value"], part["quote"]):
            find("scale_number_not_quoted",
                 f"scale.{name}.value {part['value']} is not a number of its quote "
                 f"{part['quote']!r} - every number of the comparison is a sourced one")
        parts[name] = part
    result = sc.get("result")
    if not isinstance(result, dict) or result.get("unit") not in SCALE_UNITS or \
            not isinstance(result.get("value"), (int, float)) or \
            not str(result.get("said_as") or "").strip():
        find("scale_field_missing", "scale.result needs value, a known unit and said_as")
        result = None

    if "quantity" in parts:
        fact = script.get("fact") or {}
        carriers = [str(fact.get("quote") or ""), str(fact.get("text") or "")]
        if not any(parts["quantity"]["quote"] in c for c in carriers if c):
            find("scale_quantity_not_from_fact",
                 "scale.quantity.quote is not a verbatim part of the script's fact record "
                 "(`fact.quote` / `fact.text`) - the scaled number is the video's fact, "
                 "copied, never retyped")
    if len(parts) == len(SCALE_PARTS) and result is not None:
        q, r, f = parts["quantity"], parts["reference"], parts["familiar"]
        fam_q, fam_r = SCALE_UNITS[q["unit"]][0], SCALE_UNITS[r["unit"]][0]
        fam_f, fam_out = SCALE_UNITS[f["unit"]][0], SCALE_UNITS[result["unit"]][0]
        if fam_q != fam_r or fam_f != fam_out:
            find("scale_unit_unknown",
                 f"quantity ({q['unit']}) and reference ({r['unit']}) must be one kind of "
                 f"measure, and so must the familiar size ({f['unit']}) and the result "
                 f"({result['unit']})")
        else:
            ratio = (q["value"] * SCALE_UNITS[q["unit"]][1]) / \
                    (r["value"] * SCALE_UNITS[r["unit"]][1])
            computed = ratio * f["value"] * SCALE_UNITS[f["unit"]][1] / \
                SCALE_UNITS[result["unit"]][1]
            report["computed"] = round(computed, 6)
            if abs(result["value"] - computed) > tol * computed:
                find("scale_result_off",
                     f"scale.result.value {result['value']} {result['unit']} is "
                     f"{abs(result['value'] - computed) / computed:.0%} off the recompute "
                     f"{computed:.4g} {result['unit']} (tolerance {tol:.0%})")
            said = str(result["said_as"])
            spoken = " ".join(str(script.get(k) or "") for k in SCALE_SPOKEN_FIELDS)
            if said not in spoken:
                find("scale_said_as_not_spoken",
                     "scale.result.said_as is not a verbatim part of hook / commentary / "
                     "payoff")
            if never_overstate:
                over = [n for n in numbers_in(said) if n > computed * (1 + tol)]
                if over:
                    find("scale_overstated",
                         f"said_as says {over[0]:g}, over the recompute {computed:.4g} "
                         f"{result['unit']} by more than {tol:.0%} - the rounding goes to "
                         f"the less dramatic side")
    return _scale_close(report, findings, tol)


def _scale_close(report, findings, tol):
    report["findings"] = findings
    report["verdict"] = "return_for_rewrite" if findings else "ok"
    report["reason"] = (f"{len(findings)} finding(s); recomputed "
                        f"{report['computed']!r}, tolerance {tol:.0%}")
    return report


def _check_scale_cli(args):
    if not args:
        print("usage: validate_patterns.py check-scale <03-content-researcher.json> [...]")
        return 2
    pattern = load_patterns()[SCALE_PATTERN_ID]
    bad = 0
    for path in args:
        data = json.loads(Path(path).read_text())
        scripts = data.get("scripts", []) if isinstance(data, dict) else data
        reports = [check_scale_footing(s, pattern) for s in scripts]
        scale = [r for r in reports if r["verdict"] != "not_applicable"]
        print(f"{path}: {len(scale)} scale script(s) of {len(scripts)}")
        for r in scale:
            if r["verdict"] == "ok":
                print(f"  ok      {r['script_id']}: {r['reason']}")
                continue
            bad += 1
            print(f"  REWRITE {r['script_id']}: {r['reason']}")
            for f in r["findings"]:
                print(f"          {f['kind']}: {f['note']}")
    return 1 if bad else 0


def _draw_window_cli(args):
    """CF-0300: what may be drawn for a pair, printed before anything is drawn.

    The draw happens by hand at the Content Researcher's step 3, before the
    narration exists, and until now the only place to read the legal range was
    the pattern file's own band - which on the `hold` rhythm is the ceiling
    rather than the range. One line, so the operator never has to hold two
    files against each other in their head.
    """
    if len(args) != 2:
        print("usage: validate_patterns.py draw-window <pattern_id> <rhythm_id>")
        return 2
    pid, rid = args
    patterns = load_patterns()
    if pid not in patterns:
        print(f"unknown pattern {pid!r} (known: {sorted(patterns)})")
        return 2
    pattern = patterns[pid]
    if rid not in pattern["allowed_rhythms"]:
        print(f"{pid} does not allow rhythm {rid!r} "
              f"(allowed: {pattern['allowed_rhythms']})")
        return 2
    band = pattern["parameters"]["key_frame_hold_seconds"]
    window = hold_draw_band(pattern, rid)
    print(f"{pid} on {rid}")
    block_key, block_band = block_parameter(pattern)
    print(f"  {block_key:<22} {block_band['mode']}: "
          f"{block_band.get('min')}-{block_band.get('max')}"
          + (" blocks/min" if block_key == BLOCK_RATE_KEY else ""))
    if window is None:
        print(f"  key_frame_hold_seconds {band['mode']}: write null - this pattern does "
              f"not steer it, and a number there becomes an order")
        return 0
    lo, hi = window
    print(f"  key_frame_hold_seconds draw {lo:g}-{hi:g}"
          f"   (band {band['min']:g}-{band['max']:g})")
    if hi < band["max"]:
        print(f"  the band's top is the ceiling the montage may not break; on {rid} the "
              f"drawn number is a floor the held block is grown to, so it is drawn from "
              f"the lower part only (CF-0300, rhythms.json#{rid}.{DRAWN_HOLD_KEY})")
    return 0


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv and argv[0] == "check-orders":
        return _check_orders_cli(argv[1:])
    if argv and argv[0] == "check-pairs":
        return _check_pairs_cli(argv[1:])
    if argv and argv[0] == "check-scale":
        return _check_scale_cli(argv[1:])
    if argv and argv[0] == "draw-window":
        return _draw_window_cli(argv[1:])
    errs = validate_vocabulary()
    patterns = load_patterns()
    print(f"patterns/: {len(patterns)} pattern(s), "
          f"{len(load_rhythms()['rhythms'])} rhythm(s)")
    for rid, users in sorted(rhythm_usage(patterns).items()):
        print(f"  {rid:<10} used by {', '.join(users)}")
    pending = [p["pattern_id"] for p in patterns.values()
               if p.get("original_contribution", {}).get("status") == "pending"]
    if pending:
        print(f"  original_contribution pending on: {', '.join(sorted(pending))}")
    if errs:
        print(f"\n{len(errs)} error(s):")
        for e in errs:
            print(f"  - {e}")
        return 1
    print("\nvocabulary valid")
    return 0


if __name__ == "__main__":
    sys.exit(main())
