#!/usr/bin/env python3
"""CF-0087: hold a written batch against the channel's narration budget.

The guide used to say "110-140 words" and mean the commentary alone, while
Kokoro reads hook + commentary + payoff - so every video of batch
2026-09-03T2037Z ran 62-70s against a 35-60s target. The budget now covers
the whole narrative and lives in ONE place, the channel config:

    channels/<channel>.json -> narration_budget
        counted_sections        which script keys reach the voice
        narration_words_min/max the range the writer aims at - a WARNING
        narration_words_target  the middle of it
        commentary_words_min/max guidance for the commentary, not a gate
        total_seconds_min/max   CF-0158: the finished video's editorial band
        ending_seconds          the clip the channel closes on (end_card_seconds
                                where it ships none) - what the band leaves the voice
        words_per_second        the median rate of the channel's voice - for
                                back-of-envelope reading and the pattern
                                arithmetic, NOT for deciding a length
        narration_estimator     CF-0279: the command that says how long THIS
                                script reads, and the rule it is judged by

CF-0279: WHAT DECIDES IS THE ESTIMATE, NOT THE WORD COUNT. Kokoro cuts the
text into chunks of at most 510 phonemes and pays for every boundary, so the
same word count reads at 3.24 or at 3.99 words a second depending on a
chunking nobody can see in the count - two scripts of 183 words came out 3.9 s
apart. A single rate cannot decide whether a script fits, and CF-0261 proved
it by deriving a word budget (182-200) out of which no passing script could be
written. So this check asks `narration_budget.narration_estimator.command` -
Kokoro's own g2p, chunking and duration predictor, run as a subprocess because
the engine lives only in the video editor's venv - for the seconds of every
script in the batch, and decides on the field named by `decide_on`
(`estimated_total_seconds`) against the band named by `decide_against`
(`total_seconds_min`..`total_seconds_max`) with `tolerance_seconds` of slack.
The word range is what `word_range_is` says it is - a warning printed beside
the verdict, never the gate.

There is deliberately NO fallback. When the estimator answers
`missing_engine_exit_code` (3, the engine is not installed here) this check
refuses the batch, names the reason (`narration_estimator_unavailable`) and
writes nothing: dividing the word count by `words_per_second` instead is
exactly the defect CF-0279 closes, and a silent wrong answer is worse than a
stopped batch. `missing_engine_action` in the config may only say `refuse`,
and a config that says anything else is refused as broken.

The estimator is called ONCE for the whole batch (`--batch -`, the document on
stdin): a cold start costs 8-11 s and every further script about 1.2 s, and
the estimator assembles each script's narration itself through the editor's
`meme_layer.narration_text()`, so the text judged here is the text that will
reach the TTS.

CF-0283: BOTH ENDS OF THE BAND ARE A REWRITE, AND THE LADDER IS ONE. Until
this task over the ceiling was a problem and exit 1 while under the floor was
a warning that stopped nothing - "the remedy there is more substance and no
step of this pipeline can add it" (CF-0158). Batch 2026-09-18T2232Z is what
that cost: Delver was estimated at 44.09 s against the 45-60 s band, the stage
operator left the script as it was, and the orchestrator had to send it back
by hand (158 -> 174 words, 49.29 s). A finished video under the floor breaks
the video's Definition of Done at the user's viewing exactly as one over the
ceiling does, and since CF-0279 the estimate is exact to 0.05 s: a short
script is known BEFORE the TTS, when one added sentence still fixes it for
free. So both ends climb the same ladder, the one the rest of this stage
already climbs (CF-0274, CF-0280, CF-0284, CF-0285):

  * the estimate is inside the band, tolerance included - pass, exit 0;
  * it is outside either end and the one rewrite is unspent - REWRITE, with
    the seconds to cut or to add named in the message, exit 1;
  * it is outside either end and that rewrite is spent - REFUSE. The topic
    leaves the batch as `held_back` - the funnel's code for a stage holding a
    topic back by its own judgement - moves from `scripts[]` into `skipped[]`
    with `--write`, and the run exits 4.

CF-0932: A SENTENCE KOKORO WOULD CLIP IS A REWRITE TOO. Kokoro reads at most 510
phonemes of a chunk and its chunker can hand it 511 (CF-0931, video-editor).
Where the estimator's record says `overflow_words_lost: true`, the script goes
back on the ladder above whatever its length - REWRITE with the chunk, its
phonemes, the words that would go unread and the text to split; REFUSE as
`held_back` when the one rewrite is spent. `overflow: true` with no words lost
(only punctuation cut) is a warning line and the script passes. An estimator
from before CF-0931 writes neither field: missing is false.

CF-0295: AND THE SPENT REWRITE ONLY REFUSES A VIDEO THAT IS NOT MADE. The
user's decision of 2026-09-20 (CF-0293) put a second floor under the band:
45 s is the band's floor, under which a video is SHORT - made, warned about
and counted - and 30 s is the hard floor, under which there is no video at
all. The root holds both (`judge_video_length()`'s `short` / `too_short`,
`hard_min_seconds()`, `VIDEO_LENGTH_MADE`), the Editor refuses on the hard one
before the render, and this desk kept refusing on the band's floor: batch
`2026-09-19T0116Z` lost Rennick (44.117 s, 0.883 s short) and Wren Hollow
(43.117 s, 1.883 s short) as `held_back` on the day the decision was taken -
two videos the user had just said to keep. So the last rung is now asked which
floor was missed, and it asks the ROOT rather than a number of its own:

  * the finished video the estimate predicts is under the HARD floor
    (`too_short`) - the ladder above is unchanged: rewrite, then `held_back`.
    Nothing downstream would render it anyway;
  * it is between the hard floor and the band (`short`, 30-45 s) - the one
    rewrite is still asked for first, because 45-60 s is still the target and
    one sentence is still the cheapest fix there is. But when the rewrite
    comes back still short, the script GOES ON: `action` is `accept_short`,
    the record carries `short_video_accepted: true` beside the length it was
    judged on, the loud line says so, and the run is not stopped. The topic
    stays in `scripts[]` and is not written to `skipped[]`.

A channel whose config states no hard floor, or a checkout with no root above
it, gets the old ladder: with no floor named there is no `short` to tell from
`too_short`, and inventing one here is precisely what `hard_min_seconds()`
refuses to do.

CF-0437: AND THE SHORT VIDEO IS NOT SENT BACK TO BE STRETCHED. The direction
"make it from what is given" (the user, 2026-09-28; grill 2026-09-29, Q20):
the script is as long as the pool holds (`pool_layout.py`), not under 30 s.
A 30-45 s video costs the small `score.short_length` price
(`shared/gate-prices.json`) - it is not a reason to pad the text. So a reading
between the hard floor and the band is `accept_short` at once, with no
rewrite asked first, and the counter does not move (nothing was asked of the
writer). Under the hard floor and over the ceiling the ladder is unchanged:
one rewrite, then `held_back`.

CF-0883: A WORD OVER IS A CUT, NOT A LOST TOPIC. `example-film/2026-10-24T0840Z`
lost -007 as `held_back` at 60.242 s against the 60 s ceiling, "about 1 word(s)"
over, after its one rewrite. A second miss over the ceiling worth at most
TRIM_MAX_WORDS (1) at the channel's median is `trim` (exit 1, the rewrite's
code; nothing of the rewrite spent) with a `trim_pass` snapshot of the counted
sections: cut a word, add nothing. The next reading holds the edit to a cut
(`cut_problems`: every word left a word of the snapshot, in its order) and
refuses the topic when it was not one; otherwise it is read as any other - in
the band it passes, still over it is `held_back`. Under the band, or two words
over, the ladder is unchanged.

CF-0796: BUT ONCE, IT IS SENT BACK FOR NEW QUOTED FACTS. Since the claims rule
(CF-0552) the writer writes only what it can quote, and from 2026-10-08 every
script came out 101-146 words against 159-177 - kept short at once, while its
topic's support_text (1,000-15,000 words) still held quotable facts. The
user's decision of 2026-10-18: a reading between the hard floor and the band
is `top_up` ONCE - exit 1 like a rewrite, the words to the target and the
seconds to the floor named, and the instruction to add only NEW facts, each
its own `claims[]` entry with a verbatim quote, or to leave the script
unchanged when nothing quotable is left. The counter (`top_up_attempts`) is
the record's, so the bound is the file's and not the writer's memory, and the
rewrite guard (CF-0430) does not hold `top_up`: the unchanged script is a legal
answer and the next reading closes the pass with it. That reading is
`accept_short` (or `pass`, if the pass reached the band) carrying `topped_up`
and the word / seconds delta. The top-up spends nothing of the one rewrite.
And because the added lines are new claims, the reading after the pass says
`CLAIMS AGAIN` (a problem, exit 1, nothing to rewrite) while the script's
`claims_check` is still the one stamped before the pass.

The tolerance is slack on the band and it is symmetric: `tolerance_seconds`
past the ceiling is inside, and the same under the floor is inside. What
differs between the two ends is only the sentence. Over says cut so many
seconds of speech; under says add so many seconds of SUBSTANCE - a sentence
that serves the fact or the payoff - and never filler, because padding toward
a number buys the seconds and loses the video.

A channel that knowingly ships short videos may keep the old answer for its
own floor with `narration_estimator.under_band_action: "warn"`; absent, the
key reads `rewrite`, which is CF-0283's decision and what every channel gets
without an edit to any config. The ceiling has no such key: nothing has ever
been allowed past it.

The seconds band the SCRIPT is written to is derived, never stored:
`[total_seconds_min - tail, total_seconds_max - tail]`, so it follows the
length of the channel's ending clip by itself. The subtraction, the tail and
the record all come from the root's `patterns/validate_patterns.py`
(`narration_band()`, `judge_video_length()`), imported by path - see
`validator()` - so that this script and the render plan cannot hold two
opinions on the length of one video.

Usage:

    python3 scripts/check_narration_budget.py <03-content-researcher.json>
    python3 scripts/check_narration_budget.py <03-content-researcher.json> --write

Exit 0 when every script's estimate is inside the band and every drawn order
fits its voice - and, since CF-0295, also when a script's one rewrite is spent
and the video it predicts is short (30-45 s) rather than under the hard floor:
that is `accept_short`, a loud line, a mark in the file and exit 0, because
there is nothing left for the writer to do and nothing lost; 1 when at least
one script is sent back to be rewritten - or, CF-0796, for its one top-up
pass, or for its claims to be judged again after that pass (the
file is still written with `--write` - the record of the miss is the point,
not a reward for passing); 2 on a usage error; 3 - "cannot judge", the code
the cadence and coverage gates already use - when the estimator could not be
asked at all, with the reason named and nothing written; 4 when at least one
topic is refused as `held_back` and, with `--write`, recorded in `skipped[]`.
Exit 1 means a script is the wrong length - in either direction - and its
words are what has to change; exit 3 means this machine could not answer and
nothing about the batch is known, so nothing about it should be rewritten;
exit 4 means a topic has left the batch and there is nothing to rewrite.

What `--write` puts on each script (Video Editor: this is the contract):

    "narration": {
      "words": 168,                       # over counted_sections, whitespace-split
      "counted_sections": ["hook", "commentary", "payoff"],
      "commentary_words": 130,
      "words_per_second": 3.66,           # the channel median, for reading only
      "words_per_second_source": "...",
      "estimated_words_per_second": 3.31, # words / the estimate - THIS script's rate
      "estimated_seconds": 50.8,          # the estimator's narration seconds
      "estimated_total_seconds": 55.97,   # ... plus the channel's tail
      "chunks": 3,                        # Kokoro chunk boundaries, the cliff
      "overflow": false,                  # CF-0932: a chunk over 510 phonemes
      "overflow_words_lost": false,       #   ... whose cut takes spoken words
      "overflow_chunks": [...],           #   the estimator's entries, only when over
      "overflow_decides": true,           #   only with words lost: the clip, not the
                                          #   length, put it on `rewrite`/`refuse`
      "budget_words": [159, 177],
      "word_range_is": "warning",
      "words_verdict": "fits" | "under" | "over",   # the WARNING on the words
      "verdict": "fits" | "under" | "over",         # THE DECISION, on the seconds
      "action": "pass" | "rewrite" | "refuse"    # CF-0283's rung; "warn" only
                | "accept_short" | "top_up"     # where a channel's config asks for
                | "trim",                       # CF-0883: a word over after the rewrite
                                          # it, "top_up" on the first 30-45 s
                                          # reading (CF-0796) and "accept_short"
                                          # on the one after it
      "failed_attempts": 0,               # CF-0283: the ladder's memory, kept
      "rewrites_allowed": 1,              # in the file between runs
      "under_band_action": "rewrite",     # what the config says about the floor
      "deviation_seconds": 0.0,           # signed, to the nearest bound
      "reason": "...",                    # the estimate, the band, the chunks,
                                          # and the seconds to cut or add
      "decision_band": [45.0, 60.0],      # what decide_against named
      "decision_field": "estimated_total_seconds",
      "budget_seconds": [39.833, 54.833], # derived narration band, or null
      "estimate": { ... },                # the estimator's own record, verbatim
      "video_length": { ... },            # CF-0158's record, or null with no root
      "length_verdict": "short",          # CF-0295: the ROOT's word on the
                                          # predicted finished video -
                                          # in_band/short/too_short/over, or null
      "hard_min_seconds": 30.0,           # the channel's hard floor, asked of the
                                          # root (`hard_min_seconds()`), or null
      "short_video_accepted": false,      # THE MARK: true where this stage let a
                                          # 30-45 s script through with the rewrite
                                          # spent, instead of holding the topic back
      "top_up_attempts": 0,               # CF-0796: the one top-up pass, counted
      "top_ups_allowed": 1,
      "top_up": null | {"words", "estimated_total_seconds", "seconds_to_floor",
                        "words_to_floor", "words_target", "words_to_target",
                        "spoken_hash", "claims_check_hash"},  # what was asked
      "topped_up": true,                  # after the pass only: did it add words
      "top_up_word_delta": 31,            #   words now - words at the request
      "top_up_seconds_delta": 8.4,        #   finished seconds, the same way
      "claims_recheck_needed": false,     #   the added lines not yet judged
      "budget_source": "channels/example-film.json#narration_budget"
    }
    "estimated_spoken_duration_seconds": 50.8   # the same estimate; no longer a
                                                # guess, and no longer a division

and, when the script carries a drawn `pattern`, `pattern.voice_fit` as
`patterns/validate_patterns.py` writes it (with `parameters` recomputed in
writing when the drawn ones could not cover the narration). That fit is
pattern arithmetic - how many blocks at what hold cover about a minute of
voice - and stays on the channel median by the root's own decision: a few
seconds either way do not move a block count.
"""
import argparse
import json
import math
import os
import re
import subprocess  # for TimeoutExpired; the call itself goes through runlog.run_child
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
import _batch_arg  # noqa: E402  (CF-0853)
import _no_waiting as nw  # noqa: E402
import _rewrite_guard as rg  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
import _speech_fit as sf  # noqa: E402

ROOT_MARKERS = ("channels", "patterns/validate_patterns.py")
BUDGET_KEY = "narration_budget"
ESTIMATOR_KEY = "narration_estimator"
BUDGET_REQUIRED = (
    "counted_sections",
    "words_per_second",
    "narration_words_min",
    "narration_words_max",
    ESTIMATOR_KEY,
)
# CF-0279: every one of these is read, none of them is defaulted. The block is
# required by `BUDGET_REQUIRED` above for the same reason the word range always
# was: a check that can run without knowing how it decides is a check that will
# one day decide wrongly and quietly.
ESTIMATOR_REQUIRED = (
    "command",                  # argv, paths relative to the factory root
    "decide_on",                # the field of the estimate that decides
    "decide_against",           # the two budget keys that bound it
    "tolerance_seconds",        # slack on that comparison
    "word_range_is",            # what narration_words_min/max are: "warning"
    "missing_engine_exit_code",  # the code that means "no engine here"
    "missing_engine_action",    # what to do about it: "refuse"
)
ESTIMATOR_ACTION_REFUSE = "refuse"
ESTIMATOR_WORD_RANGE = "warning"
# A whole batch through Kokoro's g2p and duration predictor: 8-11 s of cold
# start and ~1.2 s a script, so this is minutes of headroom over the worst
# batch and still an answer rather than a hang.
ESTIMATOR_TIMEOUT_SECONDS = 300

VERDICT_FITS, VERDICT_UNDER, VERDICT_OVER = "fits", "under", "over"
# CF-0283: the stage's own ladder in the stage's own words (`check_block_capacity.py`,
# `check_alternate_sides.py`, `check_two_sources.py` climb the same one). `warn` is no
# longer an action a script can carry by default - a length nobody has to answer for is
# precisely the defect this task closed - and survives only as the value a channel may
# put in `under_band_action`.
ACTION_PASS, ACTION_REWRITE, ACTION_REFUSE = "pass", "rewrite", "refuse"
ACTION_WARN = "warn"
# CF-0295: the last rung under the band when the video is still made. Terminal
# like `refuse` - the rewrite is spent and nothing more is asked of the writer -
# and harmless like `warn`: the script stays in `scripts[]` and the run goes on.
# Its own word rather than `warn`, because `warn` is what a channel asks for in
# its config for EVERY short script, and this is what the ladder does with the
# one that was rewritten and came back short anyway.
ACTION_ACCEPT_SHORT = "accept_short"
# The mark that rung leaves on the script, beside the length it was judged on.
# One name, used by the record, the printed line and whoever reads the batch
# file afterwards.
SHORT_ACCEPTED_KEY = "short_video_accepted"

# CF-0796: THE ONE TOP-UP before `accept_short`. The user's decision of
# 2026-10-18 (Telegram, "5. Da"): since the claims rule (CF-0552) every script
# came out well under the channel's word range and every one was kept short at once
# (CF-0437) - while its topic's support_text still held quotable facts. So a
# reading between the hard floor and the band is sent back ONCE, for new facts
# only (each its own `claims[]` entry with a verbatim quote), and whatever comes
# back from that pass is `accept_short` as before. The counter lives in the
# record like `failed_attempts`, so the bound is the file's and not the
# writer's memory; the rewrite guard (CF-0430) does NOT hold `top_up`, because
# "nothing quotable is left, the script is unchanged" is a legal answer and the
# re-run on it is exactly what closes the pass.
ACTION_TOP_UP = "top_up"
TOP_UPS_ALLOWED = 1
TOP_UP_ATTEMPTS_KEY = "top_up_attempts"
TOP_UP_KEY = "top_up"                 # what the request asked: words, seconds, hashes
TOPPED_UP_KEY = "topped_up"           # after the pass: did the narration grow
TOP_UP_DELTA_KEY = "top_up_word_delta"
TOP_UP_SECONDS_DELTA_KEY = "top_up_seconds_delta"
CLAIMS_RECHECK_KEY = "claims_recheck_needed"
CLAIMS_RECORD_KEY = "claims_check"    # = check_claims.py RECORD_KEY (CF-0553)

# One, like every other rung of this stage: a script already rewritten once toward
# the seconds this check named, and still outside the band, is a topic that cannot
# be told in this channel's length rather than a writing problem.
REWRITES_ALLOWED = 1
# CF-0883: ...unless it is over by about a word. `example-film/2026-10-24T0840Z`
# lost -007 as `held_back` 0.242 s over the channel's ceiling - "about 1 word(s)"
# by the line's own arithmetic - after its one rewrite. A miss that
# small is not a topic that cannot be told in this length, it is a word too many:
# ONE trim pass, after the rewrite, that only cuts words. The next reading holds
# it to that mechanically (every word left is a word of the text the pass was
# granted on, in its order - `cut_problems`), then the ladder reads it like any
# other: inside, it passes; still over, or not a cut, `held_back` as before.
ACTION_TRIM = "trim"
TRIM_KEY = "trim_pass"
TRIM_RULE = "CF-0883"
TRIM_MAX_WORDS = 1
TRIM_GRANTED, TRIM_JUDGED, TRIM_NOT_CUT = "granted", "judged", "not_cut_only"
_TRIM_WORD_RE = re.compile(r"[0-9a-z]+(?:['’][0-9a-z]+)*")
# The funnel's code for "the stage held the topic back by its own judgement"
# (`shared/runlog/funnel.py` FUNNEL_CODES, `tests/test_pipeline_contracts.py`
# SKIP_CODES). Reused and not invented: this refusal needs no new word, and a code
# the root does not know is a contract defect the funnel would report as unknown.
SKIP_REASON_CODE = "held_back"
FUNNEL_STAGE = "scripts"
# CF-0932: Kokoro synthesizes at most 510 phonemes of a chunk (`KPipeline.__call__`
# reads `ps[:510]`) and its own chunker can hand it 511 (CF-0931). The estimator
# (video-editor, since CF-0931) says so on every record: `overflow` - a chunk is
# over - and `overflow_words_lost` - the cut takes spoken words, not just
# punctuation - with `overflow_chunks` naming each one. Words lost is a sentence
# the voice would clip, so the script goes back like a length miss, on the same
# one-rewrite ladder (and `held_back` once it is spent); punctuation only is a
# warning line and the script passes. An estimator from before CF-0931 writes
# neither field, and missing reads as false.
KOKORO_PHONEME_LIMIT = 510
OVERFLOW_KEY = "overflow"
OVERFLOW_LOST_KEY = "overflow_words_lost"
OVERFLOW_CHUNKS_KEY = "overflow_chunks"
OVERFLOW_DECIDES_KEY = "overflow_decides"   # true where the clip alone sent it back
RECORD_KEY = "narration"

# The optional key and the only two answers it may give. Absent means `rewrite`:
# CF-0283's decision, applied to every channel without an edit to any config.
# `warn` restores the pre-CF-0283 floor for a channel that knowingly ships short
# videos - it is that channel's band, so it is that channel's call - and nothing
# else may be written there.
UNDER_BAND_ACTION_KEY = "under_band_action"
UNDER_BAND_ACTIONS = (ACTION_REWRITE, ACTION_WARN)
UNDER_BAND_ACTION_DEFAULT = ACTION_REWRITE

# The two named reasons a batch can be refused before a single script is
# judged. They are distinct on purpose: "the engine is not installed here" is
# an operator's problem on this machine, "the estimator failed" is a bad input
# or a broken config, and a run log that cannot tell them apart sends the wrong
# person looking.
REFUSAL_ENGINE_MISSING = "narration_estimator_unavailable"
REFUSAL_ESTIMATOR_FAILED = "narration_estimator_failed"
REFUSAL_CODES = (REFUSAL_ENGINE_MISSING, REFUSAL_ESTIMATOR_FAILED)
# "this environment could not answer", the code `check_anchor_cadence.py` and
# `check_anchor_coverage.py` already use for the same shape of event. It is
# deliberately NOT 1: exit 1 tells the writer that a script is over and has to
# be rewritten, and a batch nobody could measure has nothing to rewrite - the
# machine is what is missing. A writer who answers this by editing words is
# doing unpaid work on a question that was never asked.
# CF-0317: the two register points this check can end in. A channel with no
# config or no `narration_budget` block is a channel that is not configured -
# the number is not invented here and never was - and an estimator that cannot
# answer is a fact about this machine. Both close the stage with a code now
# instead of ending the run in a question.
POINT_CHANNEL = "researcher_missing_channel_config"
POINT_ESTIMATOR = "researcher_estimator_unavailable"

EXIT_CANNOT_JUDGE = 3
EXIT_OK, EXIT_REWRITE = 0, 1
# CF-0283: a topic refused and moved to `skipped[]`. Deliberately not 1, for the
# same reason the sibling gates of this stage give it its own code: exit 1 asks
# for a rewrite, and here there is nothing left to rewrite.
EXIT_REFUSED = 4


class EstimatorRefusal(Exception):
    """The batch cannot be judged, so it is refused rather than guessed at.

    CF-0279's whole point: there is no second way to answer "does this script
    fit". Dividing the words by `words_per_second` is the defect this task
    closed, so the absence of an estimate is a refusal with a written reason
    and never a fallback.
    """
    reason_code = REFUSAL_ESTIMATOR_FAILED

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason

    @property
    def problem(self):
        return f"{self.reason_code}: {self.reason}"


class EngineMissing(EstimatorRefusal):
    """The estimator answered `missing_engine_exit_code` - no kokoro, no
    torch, no weights on this machine."""
    reason_code = REFUSAL_ENGINE_MISSING

# CF-0158: where the seconds band this script holds a script against came
# from. `channel` - the channel names its own ends (`total_seconds_min/max`);
# `factory` - the config predates CF-0158 and names none, so the root's outer
# limits stand in, minus that channel's own tail. There is deliberately no
# third source: a band written down in this file would be exactly the kind of
# unfounded literal CF-0158 went and removed.
BAND_FROM_CHANNEL = "channel"
BAND_FROM_FACTORY = "factory"


def find_root(start=None):
    """The shorts-content-factory checkout this agent lives in.

    `SHORTS_FACTORY_ROOT` when set; otherwise the nearest ancestor of this
    file that holds both `channels/` and `patterns/validate_patterns.py`
    (works from agents/content-researcher and from a worktree under it);
    otherwise the SKILL.md convention `~/shorts-content-factory`.
    """
    env = os.environ.get("SHORTS_FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    here = (start or Path(__file__)).resolve()
    for candidate in [here, *here.parents]:
        if all((candidate / m).exists() for m in ROOT_MARKERS):
            return candidate
    return Path.home() / "shorts-content-factory"


def load_budget(channel, root=None):
    """The channel's `narration_budget` block. Raises rather than defaults -
    a missing budget is a broken config, and this file carries no range of
    its own to fall back on."""
    root = root or find_root()
    path = root / "channels" / f"{channel}.json"
    if not path.exists():
        raise FileNotFoundError(f"no channel config at {path}")
    budget = json.loads(path.read_text()).get(BUDGET_KEY)
    if not isinstance(budget, dict):
        raise KeyError(f"{path}: {BUDGET_KEY} block is missing (CF-0087 put the "
                       f"length budget there; this script carries no default)")
    missing = [k for k in BUDGET_REQUIRED if k not in budget]
    if missing:
        raise KeyError(f"{path}: {BUDGET_KEY} is missing {missing}")
    return budget


_VALIDATORS = {}


def _validate_patterns(root):
    """The root's `patterns/validate_patterns.py`. Raises if it will not
    import - `fit_orders` has nothing to do without it."""
    sys.path.insert(0, str(root / "patterns"))
    import validate_patterns  # noqa: E402
    return validate_patterns


def validator(root=None):
    """The same module, or None when the root is out of reach.

    CF-0158 opened this seam in `agents/video-editor/scripts/
    narration_length.py:validator()` and it is opened here for the same
    reason: the length arithmetic is ONE subtraction the whole factory has to
    agree on, and a copy of it in this repo is precisely how the two would
    come apart. Everything the seconds band is made of - `tail_seconds()`,
    `total_band()`, `narration_band()`, `total_seconds_from_narration()`,
    `judge_video_length()` and the outer limits `MIN_TARGET_SECONDS` /
    `MAX_TARGET_SECONDS` - is asked of that module and computed nowhere here.

    Imported by file path, and by a name of its own, rather than through
    `sys.path` like `_validate_patterns()` above: the question here is whether
    THIS root has the module, and a `validate_patterns` some earlier import
    left in `sys.modules` would answer a different question with a yes.

    None rather than a raise: the word budget is this script's own job and
    goes on working on a checkout with no factory root above it, exactly as
    the Editor's gate keeps its ceiling. Cached per root, so a batch of
    scripts imports once.
    """
    root = Path(root or find_root()).resolve()
    if root not in _VALIDATORS:
        _VALIDATORS[root] = None
        try:
            import importlib.util
            path = root / "patterns" / "validate_patterns.py"
            spec = importlib.util.spec_from_file_location("_cf0158_validate_patterns", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            _VALIDATORS[root] = module
        except Exception:  # noqa: BLE001 - no root, no seconds band, no crash
            pass
    return _VALIDATORS[root]


def band_budget(budget, root=None):
    """The budget the seconds arithmetic is asked, and where its ends come
    from: `(budget, BAND_FROM_*)`, or `(None, None)`.

    A ladder of three, first that applies - the same one
    `agents/video-editor/scripts/build_render_plan.py` climbs, so that the
    script and the plan of one video are sized against the same ends:

    1. the channel names its own band (CF-0158) - the band is the channel's
       and it wins;
    2. the config predates CF-0158 and names no band - the root's outer limits
       stand in. The subtraction still uses THIS channel's tail, so a channel
       closing on a long clip keeps a narration floor of its own rather than
       inheriting somebody else's;
    3. the root is unreachable - no band. Inventing one here would put back
       the literal the task removed.
    """
    vp = validator(root)
    keys = getattr(vp, "TOTAL_BAND_KEYS", None)
    if vp is None or not keys:
        return None, None
    named = [budget.get(k) for k in keys]
    if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in named):
        return budget, BAND_FROM_CHANNEL
    stood_in = dict(budget)
    for key, value in zip(keys, (vp.MIN_TARGET_SECONDS, vp.MAX_TARGET_SECONDS)):
        stood_in[key] = value
    return stood_in, BAND_FROM_FACTORY


def narration_band(budget, root=None):
    """What the finished video's band leaves for the voice, `[low, high]`
    seconds - or None when it cannot be derived.

    This is the band the SCRIPT is written to, and it is derived on every
    call and stored in no config (CF-0158): it follows the length of the
    channel's ending clip by itself, where the range of words above it is the
    instrument's tolerance around a target and a different quantity entirely.
    Both are kept; neither replaces the other.
    """
    vp = validator(root)
    judged, _ = band_budget(budget, root)
    if judged is None:
        return None
    try:
        return list(vp.narration_band(judged))
    except Exception:  # noqa: BLE001 - a budget naming no tail, or ends that are not a band
        return None


def video_length_record(narration_seconds, budget, root=None):
    """CF-0158's verdict on the finished video this script would make.

    `narration_seconds` is the voice alone (words over the channel's rate);
    the channel's tail is added by the root's `total_seconds_from_narration()`
    - which picks `ending_seconds` over `end_card_seconds` where the channel
    ships a clip - and the sum is judged by `judge_video_length()`. So the
    record is `verdict` in in_band/short/over and `action` in
    pass/warn/refuse, decided in one place for the whole factory rather than
    re-argued here. `band_source` names the step of `band_budget()` the ends
    came from; None is returned when there are none.
    """
    vp = validator(root)
    judged, source = band_budget(budget, root)
    if judged is None:
        return None
    try:
        total = vp.total_seconds_from_narration(narration_seconds, judged)
        record = vp.judge_video_length(total, judged)
    except Exception:  # noqa: BLE001 - as narration_band() above
        return None
    record["narration_seconds"] = round(float(narration_seconds), 3)
    record["band_source"] = source
    return record


def hard_min_seconds(budget, root=None):
    """CF-0295: the channel's hard floor for a finished video, in seconds, as
    the root reads it - or None.

    None in three cases, and all three mean the same thing here: this checkout
    cannot tell a short video from one that is not a video. The root is out of
    reach; the root predates CF-0293 and has no such notion; or the channel
    states no `total_seconds_hard_min` and the root deliberately does not
    invent one for it. The ladder below treats None as "no second floor", which
    is the pre-CF-0295 behaviour - a floor guessed at here would refuse or keep
    videos by a number nobody decided.
    """
    vp = validator(root)
    judged, _ = band_budget(budget, root)
    if vp is None or judged is None or not hasattr(vp, "hard_min_seconds"):
        return None
    try:
        return vp.hard_min_seconds(judged)
    except Exception:  # noqa: BLE001 - a key that is there and is not a number
        return None


def length_verdict(total_seconds, budget, root=None):
    """CF-0295: what the root says about a FINISHED video of that length -
    `in_band` / `short` / `too_short` / `over`, or None with no root.

    Asked of `judge_video_length()` on the number that decided
    (`estimated_total_seconds`, the estimator's own total), so that the rung
    and the verdict are about one video and not two. `video_length_record()`
    above answers the same question off the narration seconds for the file's
    CF-0158 contract; the two are held together to `tolerance_seconds` by
    `check_batch()`, and the one that decides is this one.
    """
    vp = validator(root)
    judged, _ = band_budget(budget, root)
    if vp is None or judged is None:
        return None
    try:
        return vp.judge_video_length(float(total_seconds), judged)["verdict"]
    except Exception:  # noqa: BLE001 - as narration_band() above
        return None


def video_is_still_made(verdict, hard_min, root=None):
    """CF-0295: is a video of this length still made? The root's own answer
    (`VIDEO_LENGTH_MADE`), never a comparison written here.

    False unless the channel actually named a hard floor: without one the root
    has only the three CF-0158 verdicts, `short` then means merely "under the
    band" with no line under it, and letting it through would be this stage deciding
    the floor by itself.
    """
    vp = validator(root)
    made = getattr(vp, "VIDEO_LENGTH_MADE", None)
    if not made or hard_min is None or verdict is None:
        return False
    return verdict in made



# --------------------------------------------------------------------------
# CF-0279: the estimator, which is what decides
# --------------------------------------------------------------------------

def estimator_spec(budget):
    """The `narration_estimator` block, checked for the keys this script
    reads. Raises rather than defaults, and refuses two values outright.

    `missing_engine_action` may only say `refuse` and `word_range_is` may only
    say `warning`: those two are the ban on falling back to a rate, written in
    the schema rather than in prose (`patterns/validate_patterns.py` refuses
    such a config at the root as well). A config that says anything else is
    asking for the defect CF-0279 closed, and is answered with an error.
    """
    spec = budget.get(ESTIMATOR_KEY)
    if not isinstance(spec, dict):
        raise KeyError(f"{BUDGET_KEY}.{ESTIMATOR_KEY} is missing - CF-0279 put the command "
                       f"that decides whether a script fits there, and this script has no "
                       f"rate to divide by instead")
    missing = [k for k in ESTIMATOR_REQUIRED if k not in spec]
    if missing:
        raise KeyError(f"{BUDGET_KEY}.{ESTIMATOR_KEY} is missing {missing}")
    if spec["missing_engine_action"] != ESTIMATOR_ACTION_REFUSE:
        raise ValueError(f"{BUDGET_KEY}.{ESTIMATOR_KEY}.missing_engine_action is "
                         f"{spec['missing_engine_action']!r}; the only thing this check does "
                         f"when the engine is missing is {ESTIMATOR_ACTION_REFUSE!r} "
                         f"(CF-0279: there is no fallback to dividing words by a rate)")
    if spec["word_range_is"] != ESTIMATOR_WORD_RANGE:
        raise ValueError(f"{BUDGET_KEY}.{ESTIMATOR_KEY}.word_range_is is "
                         f"{spec['word_range_is']!r}; the word range is a "
                         f"{ESTIMATOR_WORD_RANGE!r} and the seconds are the verdict")
    # CF-0283: optional, and the only key of this block that is. Its absence is an
    # answer (`rewrite`), so a config that never heard of the key gets the rule -
    # which is what keeps this fix out of every channel file in the factory.
    under = spec.get(UNDER_BAND_ACTION_KEY, UNDER_BAND_ACTION_DEFAULT)
    if under not in UNDER_BAND_ACTIONS:
        raise ValueError(f"{BUDGET_KEY}.{ESTIMATOR_KEY}.{UNDER_BAND_ACTION_KEY} is "
                         f"{under!r}; a script under the floor is either "
                         f"{ACTION_REWRITE!r} (CF-0283, and what the key's absence "
                         f"means) or {ACTION_WARN!r} (the pre-CF-0283 floor, for a "
                         f"channel that knowingly ships short videos) - nothing else")
    return spec


def under_band_action(spec):
    """What this channel does about a script under its floor. `rewrite` unless
    the config says otherwise, and the config may only say one other thing."""
    return spec.get(UNDER_BAND_ACTION_KEY, UNDER_BAND_ACTION_DEFAULT)


def estimator_command(spec, root=None):
    """`command` as an argv for this machine.

    The config writes the paths from the factory root, because that is where
    the estimator lives and the config cannot know where this checkout sits.
    An argument that is a relative path (it carries a separator and is not a
    flag) is resolved against the root; a bare word - a flag, a channel name,
    the `-` that means stdin - is passed through untouched.
    """
    argv = spec.get("command")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) for a in argv):
        raise EstimatorRefusal(f"{ESTIMATOR_KEY}.command is {argv!r}, which is not an argv")
    root = Path(root or find_root())
    out = []
    for i, arg in enumerate(argv):
        path_like = (i == 0 or (os.sep in arg and not arg.startswith("-")))
        if path_like and not Path(arg).is_absolute():
            out.append(str(root / arg))
        else:
            out.append(arg)
    return out


def _tail(text, lines=4):
    kept = [ln for ln in str(text or "").strip().splitlines() if ln.strip()][-lines:]
    return " | ".join(kept) or "(nothing on stderr)"


def run_estimator(document, spec, root=None):
    """The estimator's answer for the whole batch: ONE subprocess, the batch
    document on stdin.

    Once, not once a script: a cold start is 8-11 s (import, weights, voice
    pack) against ~1.2 s a script, so a per-script call turns a three-script
    batch into half a minute of imports.

    Every way of not getting an answer ends in `EstimatorRefusal`, and the one
    that means "this machine has no engine" ends in its subclass, so the
    caller can name which of the two happened.
    """
    root = Path(root or find_root())
    argv = estimator_command(spec, root)
    printable = " ".join(argv)
    payload = json.dumps(document, ensure_ascii=False)
    try:
        # CF-0107: through the run log, not around it. This is the one call
        # this checker makes outside its own repository, and a call that costs
        # 8-11 s of Kokoro start-up is exactly the kind the accounting exists
        # to show. `run_child` is `subprocess.run` inside a `child` event.
        proc = runlog.run_child(argv, tool=Path(argv[1]).name if len(argv) > 1 else None,
                                input=payload, capture_output=True, text=True,
                                cwd=str(root), timeout=ESTIMATOR_TIMEOUT_SECONDS)
    except FileNotFoundError:
        raise EngineMissing(f"{argv[0]} is not on this machine, so `{printable}` could not be "
                            f"run at all") from None
    except subprocess.TimeoutExpired:
        raise EstimatorRefusal(f"`{printable}` did not answer within "
                               f"{ESTIMATOR_TIMEOUT_SECONDS}s") from None
    except OSError as e:
        raise EstimatorRefusal(f"`{printable}` could not be run: {e}") from None
    if proc.returncode == spec["missing_engine_exit_code"]:
        raise EngineMissing(f"`{printable}` answered {proc.returncode} - the engine "
                            f"(kokoro, torch, the weights) is not installed here: "
                            f"{_tail(proc.stderr)}")
    if proc.returncode != 0:
        raise EstimatorRefusal(f"`{printable}` answered {proc.returncode}: "
                               f"{_tail(proc.stderr)}")
    try:
        answer = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise EstimatorRefusal(f"`{printable}` answered 0 but not JSON ({e}): "
                               f"{_tail(proc.stdout)}") from None
    if not isinstance(answer, dict):
        raise EstimatorRefusal(f"`{printable}` answered {type(answer).__name__}, not a record")
    return answer


def estimate_batch(document, scripts, spec, root=None):
    """One estimate per script, in the batch's own order.

    The alignment is checked rather than assumed: the estimator echoes the
    `script_id` it was given, and a record judged under the wrong script's
    seconds would be the worst possible outcome of this whole task.
    """
    if not scripts:
        return []
    answer = run_estimator(document, spec, root)
    results = answer.get("results")
    if not isinstance(results, list):
        raise EstimatorRefusal(f"the estimator's answer carries no `results` list "
                               f"(keys: {sorted(answer)})")
    if len(results) != len(scripts):
        raise EstimatorRefusal(f"the estimator answered {len(results)} record(s) for "
                               f"{len(scripts)} script(s) - the batch cannot be judged on "
                               f"records that do not match it")
    for script, result in zip(scripts, results):
        if not isinstance(result, dict):
            raise EstimatorRefusal(f"the estimator answered {result!r}, not a record")
        ident, answered = script.get("script_id"), result.get("id")
        if ident and answered and str(ident) != str(answered):
            raise EstimatorRefusal(f"the estimator answered for {answered!r} where the batch "
                                   f"carries {ident!r} - the records are not aligned")
    return results


def decision_band(budget, spec, root=None):
    """`([low, high], BAND_FROM_*)` - the band `decide_against` names, or
    `(None, None)`.

    The keys are read from the config and not written here, and the same
    fallback as everywhere else applies: a config predating CF-0158 that names
    no band of its own is judged against the factory's outer limits through
    `band_budget()`, still with this channel's own tail.
    """
    keys = spec.get("decide_against")
    if not isinstance(keys, list) or len(keys) != 2:
        raise EstimatorRefusal(f"{ESTIMATOR_KEY}.decide_against is {keys!r}; a band has two "
                               f"ends and they are named by the keys that hold them")

    def band_of(source):
        values = [source.get(k) for k in keys]
        if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in values):
            return [float(v) for v in values]
        return None

    named = band_of(budget)
    if named:
        return named, BAND_FROM_CHANNEL
    judged, source = band_budget(budget, root)
    if judged is not None:
        stood_in = band_of(judged)
        if stood_in:
            return stood_in, source
    return None, None


def judge_estimate(value, band, tolerance):
    """`(verdict, deviation)` - where the estimate sits against the band.

    Symmetric, which is CF-0283 correcting CF-0158: `tolerance_seconds` is
    slack on the band and it is the same slack at both ends, because it
    measures the estimator (frame rounding, 40 frames to the second) and the
    estimator does not round one way under the floor and another over the
    ceiling. WHAT TO DO about a verdict is the ladder's answer and not this
    function's - see `ladder_action()`.
    """
    low, high = band
    slack = float(tolerance or 0.0)
    value = float(value)
    if value > high + slack:
        return VERDICT_OVER, round(value - high, 3)
    if value < low - slack:
        return VERDICT_UNDER, round(value - low, 3)
    return VERDICT_FITS, 0.0


def previous_failures(script):
    """How many times this script has already been sent back for its length.

    The counter lives in the record `--write` leaves on the script, which is
    the only memory this check has between the run that asked for a rewrite
    and the run that judges what came back. A record written before CF-0283
    carries no counter: an `action` of `refuse` was the old answer over the
    ceiling and counts as the one rewrite it demanded, while the old `warn`
    counts as nothing - under the floor nobody was ever asked to change a
    word, and charging a script for a rewrite it was never told to make would
    refuse it on its first honest attempt.
    """
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 1 if record.get("action") in (ACTION_REWRITE, ACTION_REFUSE) else 0


def previous_top_ups(script):
    """CF-0796: how many top-up passes this script has already been asked for.
    The record `--write` left is the only memory; a record from before this
    task carries no counter and reads 0."""
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get(TOP_UP_ATTEMPTS_KEY)
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 1 if record.get("action") == ACTION_TOP_UP else 0


def overflow_reading(estimate):
    """CF-0932: `(overflow, words_lost, chunks)` of one estimator record. Fields
    an older estimator never wrote read as false; `chunks` keeps only the
    entries shaped like a record."""
    chunks = estimate.get(OVERFLOW_CHUNKS_KEY)
    chunks = [c for c in chunks if isinstance(c, dict)] if isinstance(chunks, list) else []
    lost = estimate.get(OVERFLOW_LOST_KEY) is True
    return (estimate.get(OVERFLOW_KEY) is True or lost or bool(chunks)), lost, chunks


def _chunk_name(entry, record):
    """`chunk 2 of 3` - the estimator's index is 0-based, the line is not."""
    n = entry.get("chunk")
    total = record.get("chunks")
    if not isinstance(n, int) or isinstance(n, bool):
        return "a chunk"
    return f"chunk {n + 1}" + (f" of {total}" if isinstance(total, int) else "")


def _chunk_phonemes(entry):
    limit = entry.get("limit") if isinstance(entry.get("limit"), int) else KOKORO_PHONEME_LIMIT
    have = entry.get("phonemes")
    return f"{have} phonemes, over Kokoro's {limit}" if isinstance(have, int) else \
        f"over Kokoro's {limit} phonemes"


def overflow_clause(record):
    """The words a clipped reading is sent back with: which chunk, how long, what
    the voice would not read, and the text to split."""
    lost = [c for c in record.get(OVERFLOW_CHUNKS_KEY) or [] if c.get("words_lost")]
    if not lost:
        return (f"a sentence is over {KOKORO_PHONEME_LIMIT} phonemes and Kokoro would clip "
                f"spoken words of it: split the longest sentence in two (CF-0932)")
    return "; ".join(
        f"sentence in {_chunk_name(c, record)} is over {KOKORO_PHONEME_LIMIT} phonemes "
        f"({_chunk_phonemes(c)}), Kokoro would clip it and never read {c.get('dropped')!r}: "
        f"split it into two sentences (CF-0932) - text: {c.get('text')}"
        for c in lost)


def overflow_warning(record):
    """CF-0932: a chunk over 510 whose cut takes only punctuation - every word is
    read, so the script passes and this is said once beside it."""
    if not record.get(OVERFLOW_KEY) or record.get(OVERFLOW_LOST_KEY):
        return ""
    over = record.get(OVERFLOW_CHUNKS_KEY) or []
    where = "; ".join(f"{_chunk_name(c, record)} ({_chunk_phonemes(c)}) loses only "
                      f"{c.get('dropped')!r}" for c in over) or \
        f"a chunk is over {KOKORO_PHONEME_LIMIT} phonemes"
    return (f"{where} - every word is still read, nothing to rewrite (CF-0932); "
            f"splitting that sentence keeps its punctuation")


def ladder_action(verdict, failed_before, under_action=UNDER_BAND_ACTION_DEFAULT,
                  still_a_video=False, top_ups_before=0):
    """CF-0283's rung for this script: `pass`, `rewrite`, `refuse` - or, since
    CF-0295, `accept_short`.

    One ladder for both ends of the band, and the rewrite is asked for at both
    ends whatever else is true: the band is still the target and one sentence is
    still the cheapest fix in the pipeline. What CF-0295 changed is only what happens
    when that rewrite comes back still short. `still_a_video` is the root's
    answer about the length this estimate predicts (`video_is_still_made()`):
    True between the hard floor and the band on a channel that named that floor, and then the
    script goes on marked instead of the topic leaving the batch. False - under
    the hard floor, over the ceiling, or no floor named anywhere - is CF-0283's
    refusal, unchanged.

    The other asymmetry is still the one a channel may ask for in its own
    config (`under_band_action: "warn"`), and it is still off unless the key is
    there: that one waves a short script through before any rewrite is asked
    for, which is a different decision from this one.
    """
    if verdict == VERDICT_FITS:
        return ACTION_PASS
    if verdict == VERDICT_UNDER and under_action == ACTION_WARN:
        return ACTION_WARN
    # CF-0437: a video that is still made (between the hard floor and the
    # band) is not stretched toward the band - CF-0796: but it is sent back
    # once for NEW quoted facts, and whatever that pass returns is kept.
    if verdict == VERDICT_UNDER and still_a_video:
        if top_ups_before < TOP_UPS_ALLOWED:
            return ACTION_TOP_UP
        return ACTION_ACCEPT_SHORT
    if failed_before < REWRITES_ALLOWED:
        return ACTION_REWRITE
    return ACTION_REFUSE


def failed_attempts(action, failed_before):
    """The counter the record carries forward: how many readings of this script
    have missed the band, this one included.

    `pass` and `warn` add nothing - neither was ever asked to change a word.
    `accept_short` is capped at the one rewrite the ladder allows plus the miss
    that spent it, because unlike a refusal it leaves the script IN the batch:
    the check is run again after every other gate's rewrite, and a counter that
    climbed on each of those runs would say "five failed attempts" about a
    script nobody asked to rewrite twice.
    """
    if action in (ACTION_PASS, ACTION_WARN, ACTION_ACCEPT_SHORT, ACTION_TOP_UP, ACTION_TRIM):
        # CF-0437: `accept_short` asks nothing of the writer any more, so it
        # spends nothing - a later edit that goes over the ceiling still has
        # its one rewrite. CF-0796: `top_up` has its own counter
        # (`top_up_attempts`) and spends nothing of this one either; nor does
        # CF-0883's `trim` (its record is `trim_pass`).
        return failed_before
    return failed_before + 1


def seconds_in_words(seconds, budget):
    """How many words a stretch of seconds is worth, as a first guess.

    The channel median, used for the only thing a median is good for here:
    turning "cut 0.84 s" into "about three words" so the writer knows the
    order of the edit. It is named as a guess in the sentence it appears in,
    because it is exactly the arithmetic that cannot decide anything.
    """
    rate = budget.get("words_per_second")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        return ""
    return (f", about {int(round(abs(float(seconds)) * float(rate)))} word(s) at the channel's "
            f"median {rate:g} w/s - a first guess, not an answer: the rewrite has to be "
            f"measured again")


def _where(record):
    return (f"estimated {record['estimated_total_seconds']:g}s of finished video "
            f"({record['estimated_seconds']:g}s of narration over {record['chunks']} Kokoro "
            f"chunk(s), {record['words']} words)")


def _position(record):
    """Where the estimate sits against the band, and nothing about what to do."""
    low, high = record["decision_band"]
    if record["verdict"] == VERDICT_FITS:
        return f"{_where(record)} is inside the {low:g}-{high:g}s band"
    side = "over" if record["verdict"] == VERDICT_OVER else "under"
    return (f"{_where(record)} is {abs(record['deviation_seconds']):g}s {side} the "
            f"{low:g}-{high:g}s band")


def decision_reason(record, budget):
    """The length's sentence (`length_reason`) - and, since CF-0932, the clipped
    sentence's: where the estimator says Kokoro would cut spoken words, that is
    named with the chunk and its text. When the clip is what sent the script
    back (`overflow_decides`), the clip leads and the length is only where the
    script stands; when the length sent it back anyway, the clip rides along."""
    if not record.get(OVERFLOW_LOST_KEY):
        return length_reason(record, budget)
    clip = overflow_clause(record)
    if not record.get(OVERFLOW_DECIDES_KEY):
        return f"{length_reason(record, budget)}; and {clip}"
    if record["action"] == ACTION_REWRITE:
        return (f"{clip} - a clipped sentence goes back like a length miss, on the same "
                f"one rewrite ({_position(record)})")
    return (f"{clip}; the one rewrite is spent ({record['failed_attempts'] - 1} "
            f"rewrite(s)) and the reading still clips spoken words, so the topic leaves "
            f"the batch as `{SKIP_REASON_CODE}` rather than the voice losing them "
            f"({_position(record)})")


def length_reason(record, budget):
    """The sentence a verdict is worth: the estimate, the band, the chunks, the
    seconds to cut or to add, and the rung of CF-0283's ladder it puts this
    script on. A refusal copies it verbatim into `skipped[]`, so it is written
    to be read alone.

    The two ends differ in one thing only, and it is the thing that matters to
    whoever rewrites: over, the fix is fewer words; under, the fix is more
    SUBSTANCE - one more sentence serving the fact or the payoff - and saying
    so is the whole point, because the cheap way to buy 0.9 s is filler and
    filler is how a video passes the band and fails the viewing.
    """
    low, high = record["decision_band"]
    where = (f"estimated {record['estimated_total_seconds']:g}s of finished video "
             f"({record['estimated_seconds']:g}s of narration over {record['chunks']} Kokoro "
             f"chunk(s), {record['words']} words)")
    off = abs(record["deviation_seconds"])
    trim = record.get(TRIM_KEY) if isinstance(record.get(TRIM_KEY), dict) else {}
    if record["action"] == ACTION_REFUSE and trim.get("state") == TRIM_NOT_CUT:
        # CF-0883: whatever the reading, an edit that was not a cut ends the topic.
        return (f"{where} - the one trim pass (CF-0883) was not a cut: "
                + "; ".join(trim.get("problems") or []) + f"; after the one rewrite the only "
                f"edit left cuts words, so the topic leaves the batch as `{SKIP_REASON_CODE}`")
    if record["verdict"] == VERDICT_FITS:
        return f"{where} is inside the {low:g}-{high:g}s band"
    side = "over" if record["verdict"] == VERDICT_OVER else "under"
    head = f"{where} is {off:g}s {side} the {low:g}-{high:g}s band"
    if record["verdict"] == VERDICT_OVER:
        fix = f"cut {off:g}s of speech{seconds_in_words(off, budget)}"
    else:
        guess = seconds_in_words(off, budget).lstrip(", ")
        fix = (f"add {off:g}s of substance - a sentence that serves the fact or the payoff, "
               f"never filler, because padding toward a number buys the seconds and loses "
               f"the video" + (f" ({guess})" if guess else ""))
    if record["action"] == ACTION_TOP_UP:
        # CF-0796. The one pass, in the words the writer acts on: new facts
        # only, each quoted, and "nothing left" is an answer, not a failure.
        req = record[TOP_UP_KEY]
        return (f"{head}; over the channel's {record['hard_min_seconds']:g}s hard floor, so "
                f"the video is made either way - but this is the ONE TOP-UP PASS "
                f"(CF-0796, the user's decision of 2026-10-18): add only NEW facts from the "
                f"parts of the topic's support_text the script does not use yet, each "
                f"sentence its own `claims[]` entry with a verbatim quote, in the commentary "
                f"or the payoff; aim at about {req['words_to_mid_band_at_own_rate']} more "
                f"word(s) - {req['seconds_to_mid_band']:g}s to the middle of the band at this "
                f"script's own {req['own_words_per_second']:g} w/s; "
                f"{req['words_to_floor_at_own_rate']} word(s) reach {low:g}s "
                f"({req['seconds_to_floor']:g}s; the channel's word target is "
                f"{req['words_target']}, {req['words_to_target']} more). No filler, no restating, no opinion stretched, never an "
                f"invented fact; keep the hook and the pattern's structure. If nothing "
                f"quotable is left, leave the script unchanged and run this check again - it "
                f"is then kept as it is. After an edit run claims.py and check_claims.py "
                f"--write again, so the new lines are judged")
    if record["action"] == ACTION_ACCEPT_SHORT:
        # CF-0295. Written to be read alone as well, because this sentence is
        # the whole account of a video that ships outside the band on purpose.
        if record.get(TOP_UP_KEY) is not None:
            delta = record.get(TOP_UP_DELTA_KEY, 0)
            did = (f"it added {delta} word(s) ({record.get(TOP_UP_SECONDS_DELTA_KEY, 0):+g}s)"
                   if record.get(TOPPED_UP_KEY) else
                   f"it added nothing ({delta:+d} word(s)) - nothing quotable was left")
            spent = (f"the one top-up pass is spent (CF-0796): {did}; no further pass "
                     f"is asked and the text is not stretched toward {low:g}s")
        else:
            spent = (f"no rewrite is asked and the text is not stretched toward "
                     f"{low:g}s")
        return (f"{head}, but {record['estimated_total_seconds']:g}s of finished video "
                f"is over the channel's {record['hard_min_seconds']:g}s hard floor, so the "
                f"video is made at this length and marked `{SHORT_ACCEPTED_KEY}` - "
                f"{spent}: a short "
                f"video costs the small score.short_length price (CF-0437, the script is as "
                f"long as the pool holds; CF-0295, the user's decision of 2026-09-20: "
                f"between {record['hard_min_seconds']:g}s and {low:g}s a short video is "
                f"kept, counted and warned about, not lost)")
    if record["action"] == ACTION_TRIM:
        # CF-0883: a word over after the one rewrite is a cut, not a lost topic.
        return (f"{head} - the one rewrite is spent, but this is about "
                f"{trim['words_to_cut']} word(s) at the channel's median, so it is ONE TRIM "
                f"PASS (CF-0883): cut a word or two of the spoken text (a filler, an adverb, a "
                f"repeated name) and add, reword or move nothing - every word left must be a "
                f"word of this text in its order, and never a word a claim's quote needs. "
                f"Then run claims.py and check_claims.py --write again (each claim's text "
                f"must still stand in its field) and this check: inside the band it passes, "
                f"still over or not a cut and the topic leaves as `{SKIP_REASON_CODE}`")
    if record["action"] == ACTION_REFUSE:
        return (f"{head} - {fix}; that was asked once already "
                f"({record['failed_attempts'] - 1} rewrite(s)"
                + (", then the one trim pass (CF-0883)" if trim else "")
                + f") and the estimate is still outside, so the topic leaves the batch as `{SKIP_REASON_CODE}` rather "
                f"than the video leaving the band")
    if record["action"] == ACTION_WARN:
        return (f"{head} - {fix}. This channel's `{UNDER_BAND_ACTION_KEY}` says "
                f"{ACTION_WARN!r}, so the run is not stopped (CF-0283)")
    return f"{head} - {fix}"


def trim_words(text):
    """The words of a section as a trim compares them: lower case, punctuation
    aside ("Doom." and "Doom," are one word, "Doom's" is one)."""
    return _TRIM_WORD_RE.findall((text or "").lower())


def words_over(record, budget):
    """CF-0883: the words an over-the-ceiling miss is worth at the channel's
    median - the same "about N word(s)" the reason prints; None without a rate."""
    rate = budget.get("words_per_second")
    if not isinstance(rate, (int, float)) or isinstance(rate, bool) or rate <= 0:
        return None
    return int(round(abs(float(record["deviation_seconds"])) * float(rate)))


def cut_problems(base, script, sections):
    """`(problems, removed)` of the edit since a trim pass was granted: each
    counted section must be the granted one with words taken out and nothing
    added or moved (its words a subsequence of the old ones); `removed` is the
    words that went, per section."""
    problems, removed = [], {}
    for name in sections:
        old, new = trim_words((base or {}).get(name)), trim_words(script.get(name))
        j, gone = 0, []
        for w in old:
            if j < len(new) and new[j] == w:
                j += 1
            else:
                gone.append(w)
        if j < len(new):
            problems.append(f"{name}: {new[j]!r} is not a word of the text the trim was granted "
                            f"on, in its place - a trim cuts words and adds or moves none")
            continue
        if gone:
            removed[name] = gone
    return problems, removed


def trim_fields(script, record, budget, sections):
    """CF-0883: the trim pass this reading grants or closes - `(action, entry)`
    with the action it leaves the script on (the ladder's unless a trim
    changes it) and the `trim_pass` entry (None when there is none)."""
    prev = script.get(RECORD_KEY) if isinstance(script.get(RECORD_KEY), dict) else {}
    entry = prev.get(TRIM_KEY) if isinstance(prev.get(TRIM_KEY), dict) else None
    action = record["action"]
    if entry is not None:
        if entry.get("state") != TRIM_GRANTED:
            return action, entry
        bad, removed = cut_problems(entry.get("base"), script, sections)
        done = dict(entry, state=TRIM_NOT_CUT if bad else TRIM_JUDGED, removed=removed,
                    words_after=record["words"])
        done.pop("base", None)
        if bad:
            done["problems"] = bad
            return ACTION_REFUSE, done
        return action, done
    n = words_over(record, budget)
    # CF-0932: a cut of a word does not split a clipped sentence - no trim then.
    if action == ACTION_REFUSE and record["verdict"] == VERDICT_OVER and n is not None \
            and n <= TRIM_MAX_WORDS and not record.get(OVERFLOW_LOST_KEY):
        return ACTION_TRIM, {"rule": TRIM_RULE, "state": TRIM_GRANTED,
                             "seconds_over": abs(record["deviation_seconds"]),
                             "words_to_cut": max(1, n), "words_before": record["words"],
                             "base": {name: script.get(name) for name in sections}}
    return action, None


def skip_entry(script, record):
    """The `skipped[]` entry a refusal writes - CF-0232's shape, with a `reason`
    written to be read alone: the funnel copies it verbatim. The code is
    `held_back`, which is what this is: the stage judged that the topic cannot
    be told in this channel's length and held it back before the TTS."""
    return {
        "topic_id": script.get("topic_id"),
        "reason_code": SKIP_REASON_CODE,
        "reason": f"{script.get('script_id')}: {record['reason']}",
        "stage": FUNNEL_STAGE,
        "verdict": record["verdict"],
        "estimated_total_seconds": record["estimated_total_seconds"],
        "decision_band": record["decision_band"],
        "deviation_seconds": record["deviation_seconds"],
        "failed_attempts": record["failed_attempts"],
    }


def word_warning(record):
    """The word range, demoted to what it is: a first guess at the desk,
    printed beside the verdict and never instead of it."""
    if record["words_verdict"] == VERDICT_FITS:
        return ""
    low, high = record["budget_words"]
    return (f"{record['words']} words is {record['words_verdict']} the {low}-{high} the writer "
            f"aims at - a {record['word_range_is']}, not the verdict")


def word_count(text):
    """Whitespace tokens - the way the forced aligner and
    validate_patterns.narration_word_count count. A prosody mark that stands
    on its own (` — `, `...`) is a token; one glued to a word is not."""
    return len(str(text or "").split())


def narration_words(script, sections):
    return sum(word_count(script.get(k)) for k in sections)


def word_verdict(words, budget):
    """The WARNING (CF-0279): where the count sits against the range the
    writer aims at. It used to be the verdict; what decides now is the
    estimate of the seconds."""
    if words < budget["narration_words_min"]:
        return VERDICT_UNDER
    if words > budget["narration_words_max"]:
        return VERDICT_OVER
    return VERDICT_FITS


def narration_record(script, budget, channel, estimate, root=None, spec=None):
    """The record the batch file carries.

    CF-0279 turned this record inside out. `verdict` used to be the word count
    against the range and `estimated_seconds` used to be that count divided by
    the channel median; now the seconds come from the estimator - Kokoro's own
    g2p, chunking and duration predictor on THIS text - and the verdict is
    those seconds against the band. The word count is still counted, still
    recorded and still compared to the range, under `words_verdict`, as the
    warning `word_range_is` says it is.

    Everything the old record carried is still here, so the Video Editor and a
    reviewer read what they read before plus the estimate.
    """
    spec = spec or estimator_spec(budget)
    sections = list(budget["counted_sections"])
    words = narration_words(script, sections)
    field = spec["decide_on"]
    value = estimate.get(field)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EstimatorRefusal(
            f"the estimate for {script.get('script_id')!r} carries no numeric {field!r} "
            f"({value!r}) - that is the field {ESTIMATOR_KEY}.decide_on names, and without "
            f"it nothing decides")
    seconds = estimate.get("estimated_seconds")
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise EstimatorRefusal(
            f"the estimate for {script.get('script_id')!r} carries no numeric "
            f"`estimated_seconds` ({seconds!r})")
    seconds = round(float(seconds), 3)
    band, band_source = decision_band(budget, spec, root)
    if band is None:
        raise EstimatorRefusal(
            f"no band to decide against: {ESTIMATOR_KEY}.decide_against names "
            f"{spec['decide_against']} and neither the channel nor the factory root gives "
            f"both of them a number")
    verdict, deviation = judge_estimate(value, band, spec["tolerance_seconds"])
    # CF-0283: where the estimate sits is one question and what to do about it is
    # another, and the second one needs the script's own history - which is why the
    # counter is written into the file rather than held in this process.
    under_action = under_band_action(spec)
    failed_before = previous_failures(script)
    # CF-0295: the rung under the band also depends on WHICH floor was missed,
    # and that is the root's call on the number that decided - not a comparison
    # written here and not a second opinion about the same video.
    hard_min = hard_min_seconds(budget, root)
    length = length_verdict(value, budget, root)
    # CF-0796: and whether the one top-up pass is still owed - the file's
    # counter, not the writer's memory.
    top_ups_before = previous_top_ups(script)
    action = ladder_action(verdict, failed_before, under_action,
                           video_is_still_made(length, hard_min, root), top_ups_before)
    # CF-0932: a sentence Kokoro would clip is a rewrite whatever the length
    # says - the same one rewrite, and `held_back` once it is spent.
    overflow, overflow_lost, overflow_chunks = overflow_reading(estimate)
    overflow_decides = overflow_lost and action not in (ACTION_REWRITE, ACTION_REFUSE)
    if overflow_decides:
        action = ACTION_REWRITE if failed_before < REWRITES_ALLOWED else ACTION_REFUSE
    rate = budget["words_per_second"]
    record = {
        "words": words,
        "counted_sections": sections,
        "commentary_words": word_count(script.get("commentary")),
        "words_per_second": rate,
        "words_per_second_source": budget.get("words_per_second_source"),
        # This script's OWN rate, which is the number the chunk cliff moves and
        # the reason a channel median cannot decide a length. Recorded so a
        # later check (check_anchor_cadence.py) can turn this script's words
        # into this script's seconds instead of the channel's average ones.
        "estimated_words_per_second": (round(words / seconds, 3) if seconds > 0 else None),
        "estimated_seconds": seconds,
        "estimated_total_seconds": round(float(value), 3),
        "chunks": estimate.get("chunks"),
        "chunk_seconds": estimate.get("chunk_seconds"),
        "chunk_phonemes": estimate.get("chunk_phonemes"),
        OVERFLOW_KEY: overflow,
        OVERFLOW_LOST_KEY: overflow_lost,
        "estimate_tolerance_seconds": spec["tolerance_seconds"],
        "budget_words": [budget["narration_words_min"], budget["narration_words_max"]],
        "word_range_is": spec["word_range_is"],
        "words_verdict": word_verdict(words, budget),
        "verdict": verdict,
        "action": action,
        "failed_attempts": failed_attempts(action, failed_before),
        "rewrites_allowed": REWRITES_ALLOWED,
        "under_band_action": under_action,
        "deviation_seconds": deviation,
        "decision_field": field,
        "decision_band": band,
        "decision_band_source": band_source,
        "budget_seconds": narration_band(budget, root),
        "estimate": estimate,
        "estimate_source": f"channels/{channel}.json#{BUDGET_KEY}.{ESTIMATOR_KEY}",
        "video_length": video_length_record(seconds, budget, root),
        # CF-0295, beside the length they are about: what the root said about
        # the video this estimate predicts, the floor it was said against, and
        # the mark that says this stage kept a short video on purpose.
        "length_verdict": length,
        "hard_min_seconds": hard_min,
        SHORT_ACCEPTED_KEY: action == ACTION_ACCEPT_SHORT,
        "budget_source": f"channels/{channel}.json#{BUDGET_KEY}",
    }
    if overflow_chunks:
        record[OVERFLOW_CHUNKS_KEY] = overflow_chunks
    if overflow_lost:
        record[OVERFLOW_DECIDES_KEY] = overflow_decides
    record.update(top_up_fields(script, record, budget, sections, top_ups_before))
    action, trim = trim_fields(script, record, budget, sections)
    if trim is not None:
        record[TRIM_KEY] = trim
        if action != record["action"]:
            record["action"] = action
            record["failed_attempts"] = failed_attempts(action, failed_before)
    record["reason"] = decision_reason(record, budget)
    return record


def words_target(budget):
    """The word count the writer aims at: the channel's `narration_words_target`,
    or the middle of the warning range on a config that names none."""
    target = budget.get("narration_words_target")
    if isinstance(target, int) and not isinstance(target, bool) and target > 0:
        return target
    return int(round((budget["narration_words_min"] + budget["narration_words_max"]) / 2))


def spoken_hash(script, sections):
    """The spoken sections alone, as words (`_rewrite_guard`'s hash over a
    script that carries nothing else): what a top-up pass changes. Anchors are
    left out on purpose - 6b moves them without adding a fact."""
    return rg.script_hash({n: script.get(n) for n in sections}, sections)


def claims_hash_of(script):
    record = script.get(CLAIMS_RECORD_KEY)
    return record.get(rg.HASH_KEY) if isinstance(record, dict) else None


def top_up_request(script, record, budget, sections):
    """CF-0796: what the one top-up pass is asked for, kept on the record so the
    reading after it can say what the pass did. The words are the WARNING's
    numbers (the seconds still decide); they are here because "add about so
    many words of new quoted facts" is a size the writer can act on."""
    words = record["words"]
    target = words_target(budget)
    low, high = record["decision_band"]
    total = record["estimated_total_seconds"]
    # The size the line names is THIS script's: its own reading rate (the
    # estimate's words over seconds) times the seconds to the floor and to the
    # middle of the band. The channel's word target is recorded beside it, but
    # a channel median configured faster than the voice reads (ExampleTech,
    # measured 2026-10-18) would send the pass toward the ceiling.
    rate = record.get("estimated_words_per_second") or 0
    mid = (low + high) / 2
    return {
        "words": words,
        "estimated_total_seconds": total,
        "seconds_to_floor": round(max(0.0, low - total), 3),
        "seconds_to_mid_band": round(max(0.0, mid - total), 3),
        "own_words_per_second": rate,
        "words_to_floor_at_own_rate": int(math.ceil(max(0.0, low - total) * rate)),
        "words_to_mid_band_at_own_rate": int(math.ceil(max(0.0, mid - total) * rate)),
        "words_to_floor": max(0, budget["narration_words_min"] - words),
        "words_target": target,
        "words_to_target": max(0, target - words),
        "spoken_hash": spoken_hash(script, sections),
        "claims_check_hash": claims_hash_of(script),
    }


def claims_recheck_needed(script, request, sections):
    """CF-0796: the claims gate has to read what the top-up added. True when
    the spoken text changed since the request AND the script's `claims_check`
    is still the one stamped before it - `check_claims.py --write` re-stamps its
    hash whenever it judges changed words, so an unmoved hash means the added
    lines were never judged. No `claims_check` at all is not stale: the claims
    gate has not run on this script yet, and it is the stage's last gate."""
    if spoken_hash(script, sections) == request.get("spoken_hash"):
        return False
    now = claims_hash_of(script)
    return now is not None and now == request.get("claims_check_hash")


def top_up_fields(script, record, budget, sections, top_ups_before):
    """The CF-0796 part of the record: the counter, the request (carried
    forward from the run that made it), and - on every reading after the pass -
    what the pass did: `topped_up`, the word and seconds delta, and whether the
    claims gate still has to read the new lines."""
    action = record["action"]
    previous = script.get(RECORD_KEY)
    carried = previous.get(TOP_UP_KEY) if isinstance(previous, dict) else None
    if action == ACTION_TOP_UP:
        request = top_up_request(script, record, budget, sections)
    else:
        request = carried if top_ups_before and isinstance(carried, dict) else None
    out = {
        TOP_UP_ATTEMPTS_KEY: top_ups_before + (1 if action == ACTION_TOP_UP else 0),
        "top_ups_allowed": TOP_UPS_ALLOWED,
        TOP_UP_KEY: request,
    }
    if action != ACTION_TOP_UP and request is not None:
        delta = record["words"] - request["words"]
        out[TOPPED_UP_KEY] = delta > 0
        out[TOP_UP_DELTA_KEY] = delta
        out[TOP_UP_SECONDS_DELTA_KEY] = round(
            record["estimated_total_seconds"] - request["estimated_total_seconds"], 3)
        out[CLAIMS_RECHECK_KEY] = claims_recheck_needed(script, request, sections)
    return out



def band_line(budget, root=None):
    """One line saying which band this batch is held to and where it came
    from - or that there is none. Printed once per batch, above the scripts,
    because the derived band is the number a reader cannot look up in any
    config: it exists only as this subtraction."""
    vp = validator(root)
    judged, source = band_budget(budget, root)
    if judged is None:
        return ("  no seconds band: the factory root is not reachable from here, so "
                "the words below are checked and the length is not (CF-0158)")
    try:
        lo, hi = vp.total_band(judged)
        n_lo, n_hi = vp.narration_band(judged)
        tail, key = vp.tail_seconds(judged), vp.tail_key(judged)
    except Exception as e:  # noqa: BLE001 - a budget the root will not size
        return f"  no seconds band: {e}"
    whose = ("the channel's own" if source == BAND_FROM_CHANNEL else
             f"the factory's ({vp.MIN_TARGET_SECONDS:g}-{vp.MAX_TARGET_SECONDS:g}s, this "
             f"config predates CF-0158 and names no band of its own)")
    return (f"  band {lo:g}-{hi:g}s finished video, {whose}; less the {tail:g}s tail "
            f"({key}) that leaves {n_lo:g}-{n_hi:g}s of narration - derived here, "
            f"stored in no config (CF-0158)")


def length_note(record):
    """The clause printed after the verdict, and the loud line under it when
    the estimate leaves the band.

    Both are built out of the decision this script made on the estimate, not
    out of `video_length` - that record is kept in the file for the contract
    and computed from the same seconds, but a printed line and a recorded
    verdict that come from two places are two opinions waiting to differ.
    """
    clause = (f", {record['estimated_seconds']:g}s of narration over "
              f"{record['chunks']} chunk(s), {record['estimated_total_seconds']:g}s video")
    if record["action"] == ACTION_PASS:
        return clause, ""
    headline = ("VIDEO OVER THE BAND" if record["verdict"] == VERDICT_OVER
                else "VIDEO UNDER THE BAND")
    if record.get(OVERFLOW_DECIDES_KEY):
        # CF-0932: the length did not send it back - a clipped sentence did.
        headline = f"SENTENCE OVER KOKORO'S {KOKORO_PHONEME_LIMIT} PHONEMES"
    # CF-0283: the rung belongs on the loud line. "VIDEO UNDER THE BAND" used to
    # mean "and nothing follows"; it now means one of four different things, and
    # a reader who remembers the old line would otherwise read the old meaning.
    # An if-chain and not a table: CF-0295's line names the hard floor, and a
    # table would format it for every rung, including the ones on a channel that
    # has no hard floor to name.
    if record["action"] == ACTION_REWRITE:
        rung = (f"REWRITE, attempt {record['failed_attempts']} of "
                f"{record['rewrites_allowed'] + 1}")
    elif record["action"] == ACTION_REFUSE:
        rung = f"REFUSED as `{SKIP_REASON_CODE}`"
    elif record["action"] == ACTION_WARN:
        rung = f"warning only ({UNDER_BAND_ACTION_KEY})"
    elif record["action"] == ACTION_TRIM:
        rung = (f"TRIM, one cut of about {record[TRIM_KEY]['words_to_cut']} word(s) - "
                f"nothing added (CF-0883)")
    elif record["action"] == ACTION_TOP_UP:
        # CF-0796: one pass, and the line says it is the only one.
        rung = (f"TOP-UP, pass {record[TOP_UP_ATTEMPTS_KEY]} of {TOP_UPS_ALLOWED} - "
                f"new quoted facts only, then kept whatever comes back")
    else:
        # CF-0295: terminal and kept. The line has to say both, because a
        # reader who knows the old one would read "UNDER THE BAND" as a loss.
        rung = (f"SHORT VIDEO KEPT, `{SHORT_ACCEPTED_KEY}` - "
                f"{record['estimated_total_seconds']:g}s is over the "
                f"{record['hard_min_seconds']:g}s hard floor, no rewrite asked "
                f"(CF-0437, CF-0295)")
    return clause, f"        {headline}, {rung} - {record['reason']}"



def commentary_note(record, budget):
    """Guidance only: the commentary share of the budget. Never a verdict."""
    lo, hi = budget.get("commentary_words_min"), budget.get("commentary_words_max")
    if lo is None or hi is None:
        return ""
    c = record["commentary_words"]
    if c < lo:
        return f"commentary {c} words, guide says ~{lo}-{hi}"
    if c > hi:
        return f"commentary {c} words, guide says ~{lo}-{hi} - hook/payoff are what is left"
    return ""


def fit_orders(scripts, root, write, budget):
    """CF-0086's check with the real word count. Returns problems found.

    With `write`, each drawn order gets its `voice_fit` record (and
    recomputed parameters, in writing) from `fit_order_to_voice`; a pair that
    cannot fit at all is left as drawn and the reason is printed for
    `rotation/rotate.py reject`.

    CF-0300: the record also carries `hold_draw` - the root's reading of
    whether a `hold` order's `key_frame_hold_seconds` was written inside the
    window that rhythm may be drawn from. A finding there is printed as
    `REDRAW` and joins `problems`, so it rides CF-0277's existing one-rewrite
    ladder. It is not a rewrite of the script: the miss is in the number, and
    the answer is to redraw it inside the window the line prints.

    CF-0446: before any of that, an order carrying the rotation's
    `speech_fit.hold_floor_seconds` has a hold drawn under that floor raised to
    it (`_speech_fit.apply_hold_floor`, printed as `FLOOR`, recorded under
    `pattern.hold_floor`). Not a problem and not a rewrite: the number was
    under what the assignment said the speech needs.

    CF-0633: `budget` is the batch channel's `narration_budget` block - the
    root's voice fit reads the rate of the channel it is given and holds none
    of its own.
    """
    vp = _validate_patterns(root)
    patterns = vp.load_patterns()
    problems = []
    for s in scripts:
        order = s.get("pattern")
        if not order or order.get("pattern_id") not in patterns:
            continue
        words = vp.narration_word_count(s)
        if words != s["narration"]["words"]:
            # The two counters are pinned equal by the tests; if they ever
            # drift, say so rather than record two numbers.
            problems.append(f"{s.get('script_id')}: this script counts {s['narration']['words']} "
                            f"words, validate_patterns counts {words}")
        # CF-0446: the rotation's floor under the drawn hold comes first - a
        # draw under it is raised to it (inside the pair's window) before the
        # voice fit reads the order, so the fit sees the hold that will be cut.
        # An order with no `speech_fit` (an older assignment) is untouched.
        order, floor = sf.apply_hold_floor(
            order, vp.hold_draw_band(patterns[order["pattern_id"]], order.get("rhythm_id")))
        if floor and floor["finding"] != sf.FLOOR_KEPT:
            print(f"  FLOOR {s.get('script_id')}: {floor['reason']}")
        try:
            fitted = vp.fit_order_to_voice(order, patterns[order["pattern_id"]], words,
                                           channel=budget)
        except vp.OrderDoesNotFitVoice as e:
            problems.append(f"{s.get('script_id')}: {e.reason}")
            print(f"  UNFIT {s.get('script_id')}: {e.reason}")
            if write and floor:
                s["pattern"] = order
            continue
        fit = fitted["voice_fit"]
        if fit["verdict"] == "recomputed":
            print(f"  fit   {s.get('script_id')}: recomputed {fit['recomputed']} - {fit['reason']}")
        else:
            print(f"  fit   {s.get('script_id')}: {fit['reason']}")
        # CF-0300: a hold written outside its draw window. The pair fits the
        # voice - this is not about the words - so it is its own line and its
        # own problem, on the same single-rewrite ladder.
        drawn = fit.get("hold_draw")
        if drawn:
            line = f"{s.get('script_id')}: {drawn['reason']}"
            problems.append(line)
            print(f"  REDRAW {line}")
        if write:
            s["pattern"] = fitted
    return problems


def check_batch(path, write=False, root=None, channel=None):
    root = root or find_root()
    data = json.loads(Path(path).read_text())
    # CF-0197: a batch written before the channel was renamed carries the
    # old id frozen in this field - the file is a dated record and is not
    # rewritten - so resolve it before anything is looked up under it.
    channel = resolve_channel(channel or data.get("channel"), root)
    if not channel:
        raise ValueError(f"{path}: no `channel` field and no --channel given")
    try:
        budget = load_budget(channel, root)
        spec = estimator_spec(budget)
    except (FileNotFoundError, KeyError, ValueError) as exc:
        # CF-0317: this file deliberately carries no default range (CF-0087),
        # and that has not changed - a batch written to a remembered number is
        # how the 62-70 s batch happened. What changed is the exit: the check
        # says which code the stage records and stops, rather than raising a
        # traceback at somebody who is not at the machine.
        raise nw.CannotAnswer(
            str(exc), point=POINT_CHANNEL, channel=channel,
            what="channel config" if isinstance(exc, FileNotFoundError) else BUDGET_KEY
        ) from None
    scripts = data.get("scripts", [])
    print(f"{path}: {len(scripts)} script(s), {'+'.join(budget['counted_sections'])} read aloud; "
          f"the writer aims at {budget['narration_words_min']}-{budget['narration_words_max']} "
          f"words ({spec['word_range_is']}), the verdict is {spec['decide_on']} from "
          f"`{' '.join(spec['command'])}` against {'..'.join(spec['decide_against'])} "
          f"+/-{spec['tolerance_seconds']:g}s (CF-0279)")
    print(band_line(budget, root))
    # CF-0279: one call for the whole batch, and no answer means no verdict.
    # There is no second way to size a script here - dividing the words by the
    # channel median is the defect this task closed - so a batch that cannot be
    # estimated is refused whole, by its named reason, with nothing written.
    try:
        estimates = estimate_batch(data, scripts, spec, root)
    except EstimatorRefusal as e:
        print(f"  REFUSED {e.reason_code}: {e.reason}")
        print(f"        nothing was judged and nothing was written. This check does not fall "
              f"back to dividing words by words_per_second: a word count cannot see the "
              f"Kokoro chunk boundary that moves a reading by seconds (CF-0279)")
        return [e.problem], []
    # CF-0430: the rewrite this gate asked for, not made - judged no again.
    # The estimator still reads the whole document (its answer is checked
    # against the batch's own order), but an unchanged script's record is
    # left as it was and nothing is counted on it.
    held = []
    _judged, unchanged, same = rg.split(scripts, RECORD_KEY, budget["counted_sections"],
                                        held.append, write)
    for line in held:
        print(line)
    unchanged_ids = {id(x) for x in unchanged}
    problems, refused = list(same), []
    for s, estimate in zip(scripts, estimates):
        if id(s) in unchanged_ids:
            continue
        rec = narration_record(s, budget, channel, estimate, root, spec)
        # CF-0446: a pair issued with no compatible pair carries the speech
        # length it needs; the reading against it is recorded and printed, and
        # stops nothing - the rotation's target is an order, not a gate.
        target = sf.target_reading(s.get("pattern"), rec["estimated_seconds"], rec["words"],
                                   spec["tolerance_seconds"])
        if target:
            rec[sf.TARGET_RECORD_KEY] = target
        s["narration"] = rg.stamp(rec, s, budget["counted_sections"])
        s["estimated_spoken_duration_seconds"] = rec["estimated_seconds"]
        note = commentary_note(rec, budget)
        clause, loud = length_note(rec)
        tag = "ok   " if rec["verdict"] == VERDICT_FITS else rec["verdict"].upper().ljust(5)
        if rec.get(OVERFLOW_DECIDES_KEY):
            tag = "CLIP "
        print(f"  {tag} {s.get('script_id')}: {rec['words']} words{clause}"
              f"{' - ' + note if note else ''}")
        if loud:
            print(loud)
        clip_warning = overflow_warning(rec)
        if clip_warning:
            print(f"        warning: {clip_warning}")
        if target and not target["met"]:
            print(f"  TARGET {s.get('script_id')}: {target['reason']}")
        warning = word_warning(rec)
        if warning:
            print(f"        words: {warning}")
        # The estimator counts the words of the text it actually reads - the
        # editor's own `meme_layer.narration_text()` join - and this script
        # counts the sections. The two are pinned equal by the tests; if they
        # ever drift, say so rather than record two numbers.
        counted = rec["estimate"].get("words")
        if isinstance(counted, int) and counted != rec["words"]:
            problems.append(f"{s.get('script_id')}: this check counts {rec['words']} words "
                            f"over {'+'.join(rec['counted_sections'])}, the estimator read "
                            f"{counted} in the text it will hand the TTS")
        # CF-0283: one ladder, both ends. A first miss in either direction is a
        # rewrite and exit 1 - the message names the seconds and which way they
        # go. A second is a refusal: a script that could not be brought into the
        # band once already is a topic that cannot be told in this channel's
        # length, and it leaves the batch here, before the TTS is paid for and
        # long before a viewing at which the video would not count. `warn` is
        # neither, and happens only where a channel's own config asks for it.
        if rec["action"] == ACTION_REWRITE:
            problems.append(f"{s.get('script_id')}: {rec['reason']}")
        elif rec["action"] == ACTION_REFUSE:
            refused.append(s)
        elif rec["action"] == ACTION_TRIM:
            # CF-0883: the one trim rides the rewrite's exit (1) - a word to cut.
            problems.append(f"{s.get('script_id')}: {rec['reason']}")
        elif rec["action"] == ACTION_TOP_UP:
            # CF-0796: the one top-up pass rides the rewrite's exit (1) - the
            # writer has something to do - but spends nothing of the rewrite,
            # and the next reading keeps whatever came back.
            problems.append(f"{s.get('script_id')}: {rec['reason']}")
        elif rec["action"] == ACTION_ACCEPT_SHORT:
            # CF-0295: named here although nothing is done, because "nothing" is
            # the decision. Not a problem - there is nothing left to rewrite and
            # the run is not stopped for it - and not a refusal: the topic stays,
            # carrying `short_video_accepted` and the loud line above.
            pass
        # CF-0796: the lines a top-up added are judged like any other - the
        # claims gate has to have read THIS text. Not a rewrite: the line says
        # which gate to run, and the next run of this check clears it.
        if rec.get(CLAIMS_RECHECK_KEY):
            line = (f"{s.get('script_id')}: CLAIMS AGAIN - the top-up pass changed the "
                    f"spoken text ({rec[TOP_UP_DELTA_KEY]:+d} word(s)) and `claims_check` is "
                    f"still the one stamped before it, so the new lines were never judged: "
                    f"run claims.py and check_claims.py --write, then this check (nothing "
                    f"to rewrite here; CF-0796, CF-0552)")
            print(f"  {line}")
            problems.append(line)
        # The estimator adds the channel's tail through the root's own
        # arithmetic and so does `video_length`; if those two ever answer
        # differently about the same script, the length of this video is
        # undecided and saying so is the only honest thing left.
        vl = rec.get("video_length")
        if vl and abs(vl["total_seconds"] - rec["estimated_total_seconds"]) > \
                float(spec["tolerance_seconds"]):
            problems.append(f"{s.get('script_id')}: the estimator says "
                            f"{rec['estimated_total_seconds']:g}s of video and this checkout's "
                            f"arithmetic says {vl['total_seconds']:g}s - the two disagree about "
                            f"the tail, and the length of this video is undecided")
    # A refused topic is leaving the batch, so its drawn order is not fitted and
    # not reported: there is no video left to fit a voice to. Identity and not
    # equality, because two scripts may read alike and only one of them is out.
    out_ids = {id(x) for x in refused}
    kept = [s for s in scripts if id(s) not in out_ids]
    problems += fit_orders(kept, root, write, budget)
    if write:
        if refused:
            data["scripts"] = [x for x in data.get("scripts", []) if id(x) not in out_ids]
            data.setdefault("skipped", [])
            for s in refused:
                data["skipped"].append(skip_entry(s, s[RECORD_KEY]))
        Path(path).write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print(f"  wrote narration records{' and voice_fit' if any(s.get('pattern') for s in kept) else ''} to {path}"
              + (f", {len(refused)} topic(s) moved to skipped[] as `{SKIP_REASON_CODE}`"
                 if refused else ""))
    elif refused:
        print(f"  note: {len(refused)} topic(s) are refused as `{SKIP_REASON_CODE}` but "
              f"nothing was recorded - re-run with --write so the funnel sees the loss")
    return problems, refused



def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", type=_batch_arg.batch_file,  # CF-0853: usage, not a crash
                    help=_batch_arg.HELP)
    ap.add_argument("--write", action="store_true",
                    help="record `narration` (and `pattern.voice_fit`) into the file - which "
                         "is also where CF-0283's one allowed rewrite is counted between "
                         "runs - and move a refused topic into skipped[] as `held_back`")
    ap.add_argument("--channel", default=None, help="override the file's `channel`")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else None
    try:
        problems, refused = check_batch(args.batch_file, write=args.write, root=root,
                                        channel=args.channel)
    except nw.CannotAnswer as exc:
        print(f"check_narration_budget.py: {exc}")
        print("  nothing was judged and nothing was written: this channel is not configured, "
              "and the band is not a number this check is allowed to invent (CF-0087)")
        print(nw.refuse(exc.point, **exc.note_fields()))
        return EXIT_CANNOT_JUDGE
    if any(p.startswith(tuple(f"{code}:" for code in REFUSAL_CODES)) for p in problems):
        print(f"\n{problems[0]}")
        print("  nothing was judged: this is the environment, not the batch - do not rewrite "
              "anything off this run")
        # CF-0317: and it is not a question either. The refusal to fall back on
        # a word count is CF-0279's and stays exactly as it is; what changed is
        # that the report is the exit. The engine is missing from this machine
        # or the command could not be run on it, and neither will be different
        # for the next batch - so it is raised once as a standing note.
        print(nw.refuse(POINT_ESTIMATOR, why=problems[0]))
        return EXIT_CANNOT_JUDGE
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
    if refused:
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}` - the length (or, "
              f"CF-0932, a sentence Kokoro would clip) was asked for once and the reading "
              f"still misses, so there is nothing left to rewrite"
              + ("" if args.write else "; nothing was recorded (--write)"))
        for s in refused:
            print(f"  - {s.get('script_id')}: {s[RECORD_KEY]['reason']}")
    if problems:
        return EXIT_REWRITE
    return EXIT_REFUSED if refused else EXIT_OK


@runlog.script("content-researcher", "check-budget", name="check_narration_budget.py")
def cli():
    """The command-line entry: main()'s return code becomes the exit code
    inside the run event, so a non-zero result (1 = at least one script has to
    be rewritten, 2 = usage, 3 = the estimator could not be asked, 4 = a topic
    was refused as `held_back`) is recorded as `failed` (CF-0107). The check - the count and the voice fit (with --write the file is rewritten - still one event) -
    is pure Python over the batch file, the channel config and the specs: no
    external binary, no model call, so no `child` events. Without a batch
    (no RUNLOG_BATCH, no batch-shaped path) the library warns once on stderr
    and records nothing; the check itself is unchanged."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
