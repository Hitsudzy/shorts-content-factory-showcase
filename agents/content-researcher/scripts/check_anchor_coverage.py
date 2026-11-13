#!/usr/bin/env python3
"""CF-0140: can the pool picture this script - asked before the voice is paid for.

The hole
--------
The order used to be script -> TTS -> plan -> resolve. The resolve was last,
so "there is nothing to show here" surfaced when the voiceover was already
synthesised and the length of the video already fixed. The Content Researcher
wrote the moments blind and regularly asked for a frame the pool cannot give;
that is the reason in the degradation record of every produced plan.

CF-0123 decided the answer has to come *before* the writing is paid for, and
hard. This script is the Content Researcher's half of that: the last act of
step 6, i.e. the last thing that happens before the stage closes and the Video
Editor synthesises speech. A refusal here costs a rewritten script and nothing
else.

**Hard, not advisory.** A `visual_anchors` entry the pool cannot picture
(`absent`) fails the batch, exit 1, and the script is rewritten. The soft form
- coverage as a report the writer may weigh - is the thing that is already
happening today and does not work (CF-0140 "Что отвергнуто").

**CF-0330 (the user, 2026-09-23): warn, not refuse.** Two videos the user
had accepted for publication were refused by these very questions on the
rebuild of 2026-09-23 - `everyday-sorcery-2` on one anchor whose best candidate
scored 0.2198 against the 0.22 floor. The user's answer: `anchor_preflight` /
`pool_too_thin` is a warning. So both pool answers of this file - the
preflight's `passed: false` (weak, absent, contention) and the margin ladder
below (rewrite, refuse) - now write a `warnings[]` entry with the same code
(`pool_too_thin`) and the same numbers, the script stays in `scripts[]`,
nothing is rewritten, and the exit is 0. The ladder is still computed and
still printed (`would_have` on the record), so the gate can be switched back
in one place (`_gate_warning.WARN_GATES`). What is *not* a warning: a
malformed `visual_anchors` (exit 1, a format error, not a measurement), a
topic none of whose sources has a shot index (exit 4, there is no pool to
measure at all), and "cannot answer" (exit 3). The prose below is the history
of the refusal and still describes the *best* move for a thin pool - it is no
longer a stop.

**CF-0412 (the user, 2026-09-28): a visual claim warns.** A line of the
narrator that points at one picture ("that one-second shot of X in the
trailer", "you can see ...") whose anchor the preflight does not picture, or
pictures with something the anchor's phrase does not name, is written into
`warnings[]` as `visual_claim_uncovered` (gate `visual_claim`,
`_visual_claim.py`). A warning only - never a refusal, no rewrite owed, the
exit is unchanged; step 6b measures the same claims again on the real
resolve (`plan_check_loop.py`, gate `visual_claim_plan`).

**CF-0437 (the direction "make it from what is given", grill 2026-09-29):
the first time, it is a rewrite.** Step 6 is the last moment the text can
still change, so a script with an uncovered claim is sent back ONCE (exit 1,
`REWRITE ... visual claim`): reword the line to a shot the pool holds
(`pool_layout.py`) or make the point without pointing. The count lives on the
script (`visual_claim_check.failed_attempts`), a re-run on the same draft is
`UNCHANGED` and spends nothing (CF-0430), and a claim still uncovered after
the one rewrite is the CF-0412 warning above and the script goes on - never a
drop, never a second round.

Where the judgement comes from
------------------------------
Not from here. Every verdict is the Video Editor's
`agents/video-editor/scripts/anchor_coverage.py`, which owns no rule of its
own either: candidates from `resolve_anchors.match()`, the pre-cut gate from
`resolve_anchors.precut_refusal()`, the verdict from
`resolve_anchors.gate_verdict()` - the same functions the real resolve runs
after TTS. This file assembles the question (which phrases, which pool) and
turns the answer into a refusal; it never judges a frame.

**The knobs cannot drift.** `--min-score` and `--top` decide which candidates
the matcher even offers, so a preflight running different ones screens a
different pool and the whole exercise is worth nothing. Two things keep them
equal, and neither is a promise to be careful:

  * this script passes **neither flag** - not as a default, not from a config,
    not from the command line; there is deliberately no way to set them here,
    so both sides fall on `resolve_anchors.DEFAULT_MIN_SCORE` /
    `DEFAULT_TOP`, which is where the Video Editor's own procedure leaves them
    too (`resolve_anchors.py` is run with no `--min-score` anywhere in its
    SKILL.md);
  * after the run, the `min_score` the report says it judged at is compared
    against `DEFAULT_MIN_SCORE` read straight out of `resolve_anchors.py`. A
    mismatch is exit 3 - "cannot answer" - never a refusal of the script.

What a pass does and does not promise
-------------------------------------
`absent` is exact: the resolve will find nothing there either. `covered` is a
**necessary condition, not a sufficient one**, and this script says so in its
own output on purpose. The real `usable()` runs on the cut clip and needs
ffmpeg and the source file; the reuse cap, the swing rules and the split
opening's spent frames are facts about a video that does not exist yet; and
the pool a plan finally runs on can be *narrower* than this one (Compliance
Checker's second pass routinely allows only some of the fetched sources), and
a narrower pool can only cover less. So a passing script can still lose a
block downstream. The one video-wide rule that can be computed in advance -
CF-0121's one sample, one use - is computed, and arrives as the report's
`contention`; when it says a block must go pictureless whatever order the
resolve picks, that is a refusal of the script, not of any one anchor.

`weak` is a refusal, and `--strict` is a no-op (CF-0291). Until CF-0290 a weak
anchor had a frame: the resolver took the best under-floor candidate, the block
had a picture, and the anchor was recorded unresolved (CF-0088) - so this gate
reported it and only `--strict` turned it into a refusal. `resolve_anchors.
screen_pool()` now takes those candidates out of the pool, so a weak anchor's
block gets nothing at all, and the preflight itself answers `passed: false`
with `weak_anchors` whether or not the flag is passed. There is no tighter line
left for a flag to draw: this stage's own run and the strict run are the same
run. `--strict` is still accepted so a runbook or a habit does not break, it is
no longer passed to the preflight, and it changes nothing.

A weak anchor is a **rewrite**, not a dropped topic: the pool has frames, this
phrase is simply not aimed at one of them. `example-film/2026-09-18T2232Z`'s
delver is both mistakes at once - "a man in a red jacket at a podium… rotunda"
names a scene those two sources do not contain at all, and "a wheelchair being
rushed past camera equipment" names one they contain for 0.985 s, which is now
a perfectly good block (the Editor holds the frame) and was then a losing
candidate.

The pool: this topic's own sources, and only those (CF-0274)
------------------------------------------------------------
The batch's own `01b-footage-index.json` - the file both agents already name -
and, per script, the sources `sources_by_topic[<topic_id>]` lists for **that
topic**, each with its `<video_id>.shots.json` beside it.

That scope is the whole of CF-0274's first finding. This check used to screen
every script against every fetched source of the batch, and the answer was
worth nothing: Pine Park's "23/23 covered" of `2026-09-18T1058Z` was covered
by Delver's, Traitors' and Famine Trials' footage, while the topic's own two
sources hold sixteen shots between them and the Editor's per-topic preflight
found seven usable samples for twenty-three anchors. The video is cut from the
topic's own sources, so the topic's own sources are the only pool whose answer
means anything - and there is deliberately no flag that widens it back, because
the operator of that batch had to pass `--strict` and a hand-built index to ask
the honest question, and a default that must be turned off by hand is a default
that is used.

A canonical source with no shot index is dropped from that topic's pool and
named, not raised: the Video Editor resolves against `shots.json` and nothing
else, so a source it has no index for is a source no video can use. A topic
left with no indexed source at all is refused (below). Before CF-0274 one
un-indexed id stopped the whole stage with exit 3 - `HEaXDIrGhS4`, whose
indexer run hung in ffmpeg, cost four other topics of `2026-09-18T1058Z` their
coverage check and was worked around by hand.

A pool too thin to carry the script (CF-0233, CF-0274)
------------------------------------------------------
One answer here is **not** a rewrite of the anchors. The pool has to hold
`anchors + POOL_MARGIN_ANCHORS` distinct usable samples; the margin is what
the blocks without anchors, the real `usable()` on the cut clip and a pool
narrowed at compliance pass 2 will eat, and it is measured off the three
batches on disk rather than chosen - see `carrying_capacity()` for the table.

CF-0233's version demanded only as many samples as anchors, and every script
that passed by a hair died downstream anyway (SVU, Traitors). What replaces it
is a ladder, in the cadence gate's own cadence:

  * the pool carries this many anchors and more - pass;
  * it carries some, just fewer than the script has - **rewrite**, and the
    writer is told the number: fewer moments, a pattern with a longer hold.
    A topic with real footage and too many anchors is a video we can still
    have, and this model call is spent before TTS instead of after it;
  * it carries none, or the one rewrite is already spent - **refuse**
    (`pool_too_thin`, exit 4). No arrangement of phrases makes a pool of a
    dozen usable frames carry a video, so no further model call is spent.

The writer's own floor - too much speech between anchors - is the other half
of CF-0233 and lives in `check_anchor_cadence.py`; the two refusals must not
be confused, because rewriting a script because the pool is thin costs money
and cannot help.

Usage:

    python3 scripts/check_anchor_coverage.py <03-content-researcher.json>
    python3 scripts/check_anchor_coverage.py <03-content-researcher.json> \
        [--footage-index <01b-footage-index.json>] [--script-id <id>] \
        [--strict] [--write] [--out <report.json>] [--root <checkout>]

Exit codes:

    0  the stage may close - every script's anchors are pictured, or the
       pool's shortfall was recorded as a warning (CF-0330: weak/absent
       anchors, contention, a pool under the margin - `pool_too_thin` in
       `warnings[]` with `--write`, the script goes on)
    1  at least one script's `visual_anchors` is malformed: fix it and run
       again
    3  cannot answer: no pool, an unreadable index, a matcher that failed, the
       knobs out of step. Nothing about the scripts is claimed - fix the
       environment and run again, do not rewrite anything.
    4  none of the topic's canonical sources has a shot index - there is no
       pool at all. The topic is refused as `pool_too_thin`, with `--write`
       recorded in `skipped[]`. (Before CF-0330 a pool under the margin, or
       the one rewrite spent, ended here too; both warn now.)
"""
import argparse
import ast
import copy
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
import _no_waiting as nw  # noqa: E402
import _gate_warning as gw  # noqa: E402
import _supplement_request as sreq  # noqa: E402
import _rewrite_guard as rg  # noqa: E402
import _visual_claim as vc  # noqa: E402 - CF-0412
import _event_footage as evf  # noqa: E402 - CF-0575
import _own_graphic as ogl  # noqa: E402 - CF-0689

from check_narration_budget import find_root, load_budget  # noqa: E402

FIELD = "visual_anchors"
ANCHOR_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
REQUIRED_KEYS = ("anchor_id", "phrase", "beat_text")
# CF-0689: on a channel with the `own_graphic` origin an anchor may place one
# of the script's own graphics instead of asking the pool - `graphic_id` in
# the place of `phrase`. The pool is never asked for it.
GRAPHIC_REQUIRED_KEYS = ("anchor_id", ogl.ANCHOR_KEY, "beat_text")
REPORT_KIND = "anchor_coverage_preflight"   # = the Editor's anchor_coverage.py report kind
# CF-0689: the preflight numbers the anchors it was asked about - the pool
# anchors only. A report handed on (`--out`, `report_for`) is renumbered to the
# script's own `visual_anchors[]` and says so, and lists the graphic anchors
# the pool never saw, so a replay reads every block's driver anchor right.
INDEX_SPACE_KEY = "anchor_index_space"
INDEX_SPACE = "visual_anchors"
GRAPHIC_INDICES_KEY = "graphic_anchor_indices"
OPTIONAL_KEYS = ("side",)
SIDES = ("a", "b")
FALLBACK_SECTIONS = ("hook", "commentary", "payoff")

EDITOR_REL = Path("agents") / "video-editor"
COVERAGE_REL = Path("scripts") / "anchor_coverage.py"
RESOLVER_REL = Path("scripts") / "resolve_anchors.py"
RHYTHM_REL = Path("scripts") / "rhythm.py"
EDITOR_PY_REL = Path(".venv") / "bin" / "python3"
FOOTAGE_INDEX_NAME = "01b-footage-index.json"

# CF-0317, `researcher_stale_cache`: the pool's cached measurements are the one
# exit-3 cause that describes its own repair - the refusal names the exact
# `remeasure_*` command - so this gate runs it and asks again instead of ending
# the run in a question. Both scripts live in the Footage Indexer's checkout and
# run on its venv, and both take the same targets this gate already has: the
# indexes of the topic being judged.
INDEXER_REL = Path("agents") / "footage-indexer"
INDEXER_PY_REL = Path(".venv") / "bin" / "python3"
REMEASURE_REL = Path("scripts")
# What the two refusals say about themselves -> the script that fixes it. The
# words are the other repositories' and are matched, never parsed into a
# command: a command built out of a subprocess's stderr is a command nobody
# wrote. The targets are this gate's own index paths.
REMEASURE_BY_CAUSE = (
    ("caption-band cache is stale", "remeasure_captions.py"),
    ("remeasure_captions.py", "remeasure_captions.py"),
    ("cached usability was measured by", "remeasure_usability.py"),
    ("remeasure_usability.py", "remeasure_usability.py"),
)
# The stage the repair's events are labelled with (CF-0173): pool work is
# nobody's turn and belongs to `pool-maintenance`, whichever stage happened to
# discover it. The markers stay the operator's - README, "RUNLOG_STAGE renames
# the events, not the markers" - so this sets the label and writes no marker of
# its own inside the Researcher's open stage.
MAINTENANCE_STAGE = "pool-maintenance"
REMEASURE_STEP = {"remeasure_captions.py": "remeasure-captions",
                  "remeasure_usability.py": "remeasure-usability"}
# One repair, and it is bounded: a second refusal after a fresh measurement is
# not a stale cache, and re-measuring the pool twice inside a batch is the wait
# this task removes wearing another hat.
REMEASURE_TIMEOUT = 1800.0
SHOTS_SUFFIX = ".shots.json"

# CF-0274: the two fields of the footage index this check reads. `fetched[]`
# says where a source's file is; `sources_by_topic` says which sources are
# *this topic's*, and that mapping - not the fetched list - is the pool. See
# `topic_pool()`.
FETCHED_KEY = "fetched"
SOURCES_BY_TOPIC_KEY = "sources_by_topic"

# The matcher loads CLIP once per call; a batch's four scripts are four calls.
DEFAULT_TIMEOUT = 600

EXIT_OK, EXIT_REWRITE, EXIT_CANNOT_ANSWER, EXIT_POOL_TOO_THIN = 0, 1, 3, 4

# CF-0233: the one refusal here that is NOT a rewrite. The code, the shape of
# the record and the funnel step are CF-0232's; `pool_too_thin` is the code
# that module reserved for exactly this day ("fewer usable samples in the pool
# than the pattern's anchors").
SKIP_REASON_CODE = "pool_too_thin"
FUNNEL_STAGE = "scripts"

# CF-0274: the margin. Read `carrying_capacity()` for where 12 comes from -
# it is the whole of the rule and it is measured, not chosen. Channel-
# independent on purpose, beside the other numbers this check owns: a pool is
# a pool, and a channel that could raise this is a channel that can buy back
# the losses of 2026-09-17/18 one video at a time.
#
# CF-0284 demoted it from *the* measure to a floor, and left the number alone.
# The first bullet of `carrying_capacity()` below - "a video has more blocks
# than the script has anchors" - is now answered where it belongs, against the
# Editor's own block plan (`check_block_capacity.py`), and that is the check
# that decides: Famine Trials cleared this margin by 36 on 2026-09-18T2232Z and
# still lost 8 blocks. What stays here is the question that comes first and
# needs no plan - can this pool picture these anchors at all - which is also
# the only answer left for a script whose beats cannot be located in the
# narration, because then there are no anchor times and no block plan.
POOL_MARGIN_ANCHORS = 12

# One rewrite, then the topic - the cadence gate's ladder (CF-0233), followed
# here for the same reason it exists there: a second attempt at a script the
# pool cannot carry is a model call that already has its answer. The count
# lives on the script (`anchor_coverage_pool.failed_attempts`), because each
# run of this gate is a new process.
REWRITES_ALLOWED = 1
RECORD_KEY = "anchor_coverage_pool"
# CF-0437: the visual claim's own ladder - one rewrite, then the CF-0412
# warning. Its own record, so the pool's counter and the claim's never mix and
# the CF-0430 guard (`_rewrite_guard.split`) holds an unedited draft on it.
CLAIM_RECORD_KEY = "visual_claim_check"
CLAIM_REWRITES_ALLOWED = 1

ACTION_PASS, ACTION_REWRITE, ACTION_REFUSE = "pass", "rewrite", "refuse"

VERDICT_COVERED, VERDICT_WEAK, VERDICT_ABSENT = "covered", "weak", "absent"

# What a pass is worth, said in the output rather than only in this docstring:
# the first script that passes here and still loses a block downstream must not
# read as the mechanism lying.
PASS_CAVEAT = ("covered = the pool has a frame that survives everything checkable "
               "before the cut; it is a necessary condition, not a guarantee - the "
               "cut clip, the reuse cap and a pool narrowed by compliance pass 2 are "
               "judged at resolve time, and the margin below is what pays for them")


# CF-0317: the three register points this file can end in. Spelled once, in
# `_no_waiting`, and asserted against the root's register in the tests.
POINT_UPSTREAM = "researcher_missing_upstream"
POINT_STALE = "researcher_stale_cache"
POINT_ENV = "researcher_env_broken"


class CannotAnswer(nw.CannotAnswer):
    """The environment could not be asked. Never a verdict on a script.

    CF-0317: it also carries *which* of this stage's register points it is, so
    that the exit records a code instead of a person reading a traceback and
    deciding. Three of this file's causes are the upstream artifact
    (`researcher_missing_upstream`), one is the pool's stale measurements
    (`researcher_stale_cache`, the only one this file can repair by itself),
    and everything else is the machine (`researcher_env_broken`) - which is the
    default precisely because an unrecognised cause is a broken environment
    until somebody proves otherwise, and never a silent pass.
    """

    def __init__(self, message, point=POINT_ENV, **fields):
        super().__init__(message, point, **fields)

    def note_fields(self):
        """What `_no_waiting.note()` needs to fill this point's template in.
        `cause` falls back to the first line of the message, because a note
        that names no cause sends the reader back to the log to find one."""
        fields = super().note_fields()
        if self.point == POINT_ENV and not fields.get("cause"):
            fields["cause"] = str(self).splitlines()[0].strip()
        return fields


# --------------------------------------------------------------------------
# CF-0233: a pool too thin for the script is not the script's fault
# --------------------------------------------------------------------------

def carrying_capacity(distinct_samples):
    """How many anchors a pool of `distinct_samples` usable samples can carry.

    `distinct_samples - POOL_MARGIN_ANCHORS`, and the whole of CF-0274's third
    finding is in that constant.

    CF-0233 put the floor at *equality* - as many distinct usable samples as
    the script has anchors - and a pool that only just clears equality dies
    downstream every time, because three things happen after this check that
    this check cannot see:

      * a video has more blocks than the script has anchors, and every block
        needs a picture of its own (CF-0121: one sample, one use);
      * the real `usable()` runs on the *cut clip*, with the block's own crop
        window, and refuses what the cached pre-filter could not: the caption
        crop taking a 1080p source under 720 (CF-0062), a window that keeps
        less than 65 % of the subject. The preflight cannot run it - there is
        no clip and no block before TTS;
      * Compliance Checker's second pass can narrow the pool further.

    So the margin is measured rather than argued. Every per-topic preflight on
    disk, with what became of the script (`distinct - anchors`):

        batch        topic            anchors  distinct  margin  outcome
        2026-09-16   lf-...-005          11        48     +37  11/11 clips cut
        2026-09-17   mormon-wives          15        46     +31  rendered
        2026-09-17   colbert               15        17      +2  refused (absent)
        2026-09-17   svu                    8        10      +2  pattern_undeliverable
        2026-09-18   delver                 6        66     +60  carried the pool
        2026-09-18   famine-trials          23        59     +36  carried the pool
        2026-09-18   pine-park            23         7     -16  16 blocks pictureless
        2026-09-18   traitors               7        16      +9  3 blocks empty

    Every script the pool actually failed sits at +9 or below; every script
    whose pictures the pool carried sits at +31 or above. Any k in [10, 31]
    separates them and there is no data between. 12 is the low end of that
    band plus three: low, because the expensive mistake here is refusing a
    script that would have worked, and not at 10 because the worst *silent*
    death (Traitors, +9) is a death this gate has to clear with room, not by
    one sample. The other two numbers of this file - `MIN_CUT_SECONDS` and the
    matcher knobs - live in the Video Editor's code because they are the
    Editor's; this one is this gate's and lives here, once, for every channel.

    A caller wanting the other direction reads it the same way: with `distinct`
    fixed, `carrying_capacity()` is how many anchors the writer may keep.
    """
    return distinct_samples - POOL_MARGIN_ANCHORS


def previous_failures(script):
    """Pool failures already recorded on this script. A record written by an
    older run with no count is one failure, not zero: the record only exists
    because a run wrote it."""
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0 if record.get("action") == ACTION_PASS else 1


def pool_judgement(report, script):
    """What this topic's own pool can carry, as a record - CF-0233 with a
    margin and a ladder (CF-0274).

    Three answers, and which one it is turns on `carrying_capacity()`:

      * **pass** - the pool holds at least `anchors + POOL_MARGIN_ANCHORS`
        distinct usable samples. The margin is what the blocks without
        anchors, the real `usable()` on the cut clip and a pool narrowed at
        compliance pass 2 will eat.
      * **rewrite** - the pool can carry *some* anchors, just not this many.
        The writer is told the number (`capacity`) and rewrites the script to
        it: fewer anchors, a pattern with a longer hold. This is the rung
        CF-0274 added ahead of the refusal, because a topic with real footage
        and too many anchors is a video we can still have, and the model call
        is spent before TTS rather than after it.
      * **refuse** - `capacity` is under one anchor, or the rewrite has
        already been spent. Then there is nothing to write to: no arrangement
        of phrases makes a pool with a dozen usable frames carry a video. The
        topic leaves the batch as `pool_too_thin` (CF-0232's funnel code) and
        no further model call is spent on it.

    The count is `contention.distinct_samples` - the distinct samples behind
    the anchors that have one at all, screened by the same pre-cut gate the
    resolve runs (cached qc including `text_cut_by_crop`, the subject-coverage
    floor, the delivery-height floor, the black-frame ceiling). It is the
    Editor's own number, out of the Editor's own preflight; this file counts
    nothing.

    Unlike CF-0233's version this does *not* stand down in front of `absent`.
    It did, because a mis-aimed anchor is cheaper to fix than a dropped topic -
    but with a ladder the two answers are the same answer: when the pool has
    room, absent anchors are a rewrite through `problems` and this record says
    `pass`; when it has none, a rewrite aimed at frames that are not there was
    never the cheaper move. `failed_attempts` counts pool failures only, so an
    anchor rewritten for being absent never spends the pool's one attempt.

    Returns None when the report cannot be read as an answer about a pool -
    never a verdict.
    """
    if not isinstance(report, dict):
        return None
    anchors = report.get("anchor_count")
    distinct = (report.get("contention") or {}).get("distinct_samples")
    if not isinstance(anchors, int) or not isinstance(distinct, int):
        return None
    capacity = carrying_capacity(distinct)
    room = distinct - anchors
    failed_before = previous_failures(script)
    pool = report.get("pool") or {}
    where = (f"the pool holds {distinct} distinct usable sample(s) over "
             f"{pool.get('sources')} source(s) / {pool.get('shots')} indexed shot(s)")

    finding = None
    if room >= POOL_MARGIN_ANCHORS:
        action, failed = ACTION_PASS, failed_before
        reason = (f"{where} for {anchors} anchor(s) - {room} over the anchors, at or over the "
                  f"{POOL_MARGIN_ANCHORS} of margin the blocks without anchors, the cut-clip "
                  f"gate and compliance pass 2 spend")
        finding = reason
    elif capacity < 1:
        action, failed = ACTION_REFUSE, failed_before + 1
        reason = (f"{where}, which carries {max(capacity, 0)} anchor(s) once the "
                  f"{POOL_MARGIN_ANCHORS} of margin is taken out: there is no script this pool "
                  f"can picture, whatever the phrases are. This is the pool, not the writing - "
                  f"the topic is dropped rather than rewritten, and no model call is spent on "
                  f"it (CF-0233, CF-0274)")
        finding = (f"{where}, which carries {max(capacity, 0)} anchor(s) once the "
                   f"{POOL_MARGIN_ANCHORS} of margin is taken out, against this script's "
                   f"{anchors}")
    else:
        failed = failed_before + 1
        action = ACTION_REWRITE if failed <= REWRITES_ALLOWED else ACTION_REFUSE
        reason = (f"{where}, which carries {capacity} anchor(s) against this script's "
                  f"{anchors}: {anchors - capacity} anchor(s) more than the pool has frames "
                  f"for once the {POOL_MARGIN_ANCHORS} of margin is taken out (the blocks "
                  f"without anchors, the real usable() on the cut clip, compliance pass 2)")
        finding = reason
        if action == ACTION_REWRITE:
            reason += (f". Rewrite the script to at most {capacity} anchor(s) - fewer moments, "
                       f"a pattern with a longer hold - and run the cadence gate and this one "
                       f"again")
        else:
            reason += (f". Refused after {failed} attempt(s): the script was already rewritten "
                       f"once against this pool and still asks for more frames than it has")
    return {
        "topic_id": script.get("topic_id"),
        "anchors": anchors,
        "distinct_samples": distinct,
        "margin_required": POOL_MARGIN_ANCHORS,
        "margin": room,
        "capacity": capacity,
        "pool": pool,
        "indexes": report.get("indexes"),
        "failed_attempts": failed,
        "rewrites_allowed": REWRITES_ALLOWED,
        "action": action,
        "reason": reason,
        # CF-0330: the measurement alone, without the ladder's instruction -
        # what a warning says when there is nothing to rewrite.
        "finding": finding,
    }


def unindexed_judgement(script, pool):
    """The answer for a topic whose own sources were never indexed.

    CF-0274: a `fetched[]` entry that carries no `path`, or a canonical source
    with no `<video_id>.shots.json` beside it, used to stop the whole stage
    (exit 3) and the operator hand-copied the index to get past it - batch
    `2026-09-18T1058Z` died that way on `HEaXDIrGhS4`, whose indexer run hung
    in ffmpeg. That is the wrong shape twice over: it is one topic's problem,
    not the batch's, and the Video Editor cannot resolve against a source it
    has no index for either, so nothing is lost by saying so here.

    So a source with no index is dropped from that topic's pool and named; a
    topic left with no indexed source at all is refused as `pool_too_thin`,
    because a pool of nothing carries nothing. Both are said in words, and
    neither touches any other topic of the batch.
    """
    missing = ", ".join(u["video_id"] for u in pool["unindexed"])
    return {
        "topic_id": script.get("topic_id"),
        "anchors": len(script.get(FIELD) or []),
        "distinct_samples": 0,
        "margin_required": POOL_MARGIN_ANCHORS,
        "margin": None,
        "capacity": 0,
        "pool": {"sources": 0, "shots": 0},
        "indexes": [],
        "failed_attempts": previous_failures(script) + 1,
        "rewrites_allowed": REWRITES_ALLOWED,
        "action": ACTION_REFUSE,
        "reason": (f"none of this topic's {len(pool['video_ids'])} canonical source(s) has a "
                   f"shot index: {missing}. The Video Editor resolves against `shots.json` and "
                   f"nothing else, so this topic has no pool at all - it is dropped rather than "
                   f"written for. Index the source(s) (Footage Indexer) and the topic comes "
                   f"back in a later batch"),
    }


def skip_entry(script, record):
    """The `skipped[]` entry a refusal writes - CF-0232's shape exactly, with
    a `reason` written to be read alone, because the funnel copies it verbatim
    into its `detail` column."""
    return {
        "topic_id": script.get("topic_id"),
        "reason_code": SKIP_REASON_CODE,
        "reason": f"{script.get('script_id')}: {record['reason']}",
        "stage": FUNNEL_STAGE,
        "pool": record["pool"],
        "anchors": record["anchors"],
        "distinct_samples": record["distinct_samples"],
        "capacity": record["capacity"],
        "margin_required": record["margin_required"],
        "failed_attempts": record["failed_attempts"],
    }


def pool_numbers(record):
    """CF-0330: the numbers a pool warning carries - the ones the refusal
    carried in `skipped[]`, plus what the ladder would have done."""
    return {k: record.get(k) for k in (
        "anchors", "distinct_samples", "margin_required", "margin", "capacity", "pool",
        "failed_attempts", "rewrites_allowed", "would_have")}


def pool_warning(record):
    """CF-0330: the warning's sentence - the pool's measurement and what the
    ladder would have done, with no instruction to rewrite."""
    return (f"{record.get('finding') or record['reason']}. Before CF-0330 this was a "
            f"{record.get('would_have')}; now a warning - the script goes on as written, "
            f"and a block the pool cannot fill is the Editor's `assetless_rung` warning")


def coverage_reason(report, warn=False):
    """The preflight's `passed: false` in one sentence - the rewrite request it
    used to be, and since CF-0330 (`warn`) the detail of the warning."""
    weak = report.get("weak") or []
    absent = report.get("absent") or []
    why = ", ".join(report.get("refused_because") or [])
    if warn:
        return (f"the pool does not cover every anchor ({why})"
                + (f". Anchor(s) {weak}: everything the pool ranked for them is under the "
                   f"{report.get('min_score')} similarity floor (CF-0290)" if weak else "")
                + (f". Anchor(s) {absent} have no usable frame at all" if absent else "")
                + ". A warning, not a refusal (CF-0330): the script goes on as written; "
                  "the per-anchor best scores are in `numbers.uncovered`")
    return (f"the pool cannot carry this script ({why}) - rewrite it against the "
            f"frames the pool has"
            + (f". Anchor(s) {weak} name scenes this pool does not hold: everything it "
               f"ranked for them is under the {report.get('min_score')} similarity floor, "
               f"so the Editor fills those blocks with the best of it and prices each one "
               f"`score.low_similarity` (CF-0433; -3 a block, cap -15). Write those anchors "
               f"off the `samples` below to save the points - a shot shorter than a block "
               f"is fine, its frame is held" if weak else "")
            + (f". Anchor(s) {absent} have no usable frame at all" if absent else ""))


def coverage_numbers(report):
    """CF-0330: the preflight's numbers, the Video Editor's
    `anchor_preflight.warning.json` shape - the floor and, per anchor the pool
    did not cover, how close it came. `everyday-sorcery-2` was refused on a
    best candidate of 0.2198 against 0.22; a warning that cannot say so cannot
    show it was measurement noise."""
    contention = report.get("contention") or {}
    return {
        "min_score": report.get("min_score"),
        "anchor_count": report.get("anchor_count"),
        "covered_count": report.get("covered_count"),
        "weak": list(report.get("weak") or []),
        "absent": list(report.get("absent") or []),
        "refused_because": list(report.get("refused_because") or []),
        "distinct_samples": contention.get("distinct_samples"),
        "short_after_repeat": contention.get("short_after_repeat"),
        "pool": report.get("pool"),
        "uncovered": [
            {"anchor_index": a.get("anchor_index"), "phrase": a.get("phrase"),
             "verdict": a.get("verdict"), "cause": a.get("cause"),
             "best_score": a.get("best_score"),
             "best_offered_score": a.get("best_offered_score"),
             "candidates": a.get("candidates"), "survivors": a.get("survivors")}
            for a in (report.get("anchors") or [])
            if isinstance(a, dict) and a.get("verdict") != VERDICT_COVERED],
    }


# --------------------------------------------------------------------------
# the Video Editor's half: where it is, and the knobs it must run with
# --------------------------------------------------------------------------

def editor_paths(root=None, editor_python=None, coverage_script=None):
    """The sibling agent's preflight, its interpreter, and its resolver.

    Nothing here is imported: the Video Editor's code runs on its own venv
    (CLIP, PIL, numpy), so the only honest way to reach it from this repo is a
    subprocess with that interpreter.
    """
    root = Path(root) if root else find_root()
    editor = root / EDITOR_REL
    paths = {
        "editor": editor,
        "coverage": Path(coverage_script) if coverage_script else editor / COVERAGE_REL,
        "resolver": editor / RESOLVER_REL,
        "python": Path(editor_python) if editor_python else editor / EDITOR_PY_REL,
    }
    for key in ("coverage", "python"):
        if not paths[key].exists():
            raise CannotAnswer(
                f"{paths[key]} is missing - the coverage preflight lives in the Video "
                f"Editor's checkout (CF-0140) and runs on its venv; this repo has no "
                f"second copy of it and must not grow one")
    return paths


def _editor_module(path):
    """One of the Video Editor's modules, parsed.

    Parsed, not imported - importing any of them pulls the Video Editor's whole
    dependency set (CLIP, PIL, numpy) into this interpreter. Reading the
    Editor's own source is how every number this repository runs on arrives
    here: there is no second copy of one anywhere under `scripts/`.
    """
    try:
        return ast.parse(Path(path).read_text())
    except (OSError, SyntaxError) as exc:
        raise CannotAnswer(f"cannot read {path}: {exc}")


def module_constants(path, names):
    """`{name: value}` for the top-level literal constants `names` of an Editor
    module. A name that is not there is simply absent from the answer - the
    caller decides whether its own question can be asked without it."""
    tree = _editor_module(path)
    wanted, found = set(names), {}
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for target in node.targets:
            if isinstance(target, ast.Name) and target.id in wanted:
                try:
                    found[target.id] = ast.literal_eval(node.value)
                except ValueError:
                    alias = _sibling_constant(path, node.value)
                    if alias is not None:
                        found[target.id] = alias
    return found


def _sibling_constant(path, value, _depth=0):
    """CF-0433: `DEFAULT_MIN_SCORE = _score.SIMILARITY_FLOOR` - a constant the
    Editor keeps in one place and aliases elsewhere. Followed into the sibling
    module `<module>.py` next to `path` (one level of aliasing per hop, at most
    three hops); anything else is not a constant this reader can vouch for."""
    if _depth > 3 or not (isinstance(value, ast.Attribute)
                          and isinstance(value.value, ast.Name)):
        return None
    sibling = Path(path).parent / f"{value.value.id}.py"
    if not sibling.exists():
        return None
    try:
        tree = _editor_module(sibling)
    except Exception:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == value.attr for t in node.targets):
            try:
                return ast.literal_eval(node.value)
            except ValueError:
                return _sibling_constant(sibling, node.value, _depth + 1)
    return None


def defines(path, name):
    """Whether an Editor module defines a top-level function by this name.

    CF-0291: the one thing the replays downstream cannot take on trust. They
    read the preflight's `samples` as *the pool a block may draw on*, and that
    is only true of a checkout whose `resolve_anchors.screen_pool()` takes the
    under-floor candidates out of it (CF-0290). Against an older Editor the
    same list still holds frames the resolver would put on screen under a
    floor, and a replay of it would repeat the very mistake this task is
    about - so the probe is a precondition of answering, not a warning.
    """
    return any(isinstance(node, ast.FunctionDef) and node.name == name
               for node in _editor_module(path).body)


def resolver_file(root=None, resolver=None):
    """`resolve_anchors.py`, for the checks that only read its source.

    Separate from `editor_paths()` because these constants are readable
    without the Editor's venv: a checkout with no `.venv` still answers the
    question "what does the resolver run at", and a check that refused to
    answer it for want of an interpreter it never starts would be refusing for
    the wrong reason.
    """
    if resolver:
        path = Path(resolver)
    else:
        path = (Path(root) if root else find_root()) / EDITOR_REL / RESOLVER_REL
    if not path.exists():
        raise CannotAnswer(
            f"{path} is missing - the floors a candidate has to clear are the Video "
            f"Editor's own constants (CF-0140, CF-0290) and this repo carries no copy "
            f"of them")
    return path


def matcher_knobs(resolver_path):
    """`DEFAULT_MIN_SCORE` / `DEFAULT_TOP` read out of `resolve_anchors.py`.

    These are the constants CF-0140 made constants for exactly this reason:
    the preflight and the real resolve have to ask the matcher the same
    question.
    """
    found = module_constants(resolver_path, ("DEFAULT_MIN_SCORE", "DEFAULT_TOP"))
    missing = [k for k in ("DEFAULT_MIN_SCORE", "DEFAULT_TOP") if k not in found]
    if missing:
        raise CannotAnswer(
            f"{resolver_path}: {', '.join(missing)} not found - the preflight and the "
            f"real resolve can no longer be shown to run the same matcher knobs")
    return {"min_score": found["DEFAULT_MIN_SCORE"], "top": found["DEFAULT_TOP"]}


# --------------------------------------------------------------------------
# the pool
# --------------------------------------------------------------------------

def load_footage_index(batch_file, footage_index=None):
    """`(path, document)` for the batch's own `01b-footage-index.json`.

    Read once for the whole batch; the pool each script is judged against is
    cut out of it per topic by `topic_pool()`.
    """
    path = Path(footage_index) if footage_index else Path(batch_file).parent / FOOTAGE_INDEX_NAME
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(
            f"no readable footage index at {path}: {exc} - there is nothing to check "
            f"the anchors against (SKILL.md Notes: a missing footage index closes the "
            f"stage with a code and the run goes on)",
            point=POINT_UPSTREAM, file=FOOTAGE_INDEX_NAME)
    if not isinstance(data, dict):
        raise CannotAnswer(f"{path}: not a footage index - expected an object",
                           point=POINT_UPSTREAM, file=FOOTAGE_INDEX_NAME)
    by_topic = data.get(SOURCES_BY_TOPIC_KEY)
    if not isinstance(by_topic, dict) or not by_topic:
        raise CannotAnswer(
            f"{path}: `{SOURCES_BY_TOPIC_KEY}` is missing or empty - it is the only record of "
            f"which sources belong to which topic, and a script judged against anything wider "
            f"is judged against footage its own video will never be allowed to use (CF-0274). "
            f"Nothing is claimed about any script on this run",
            point=POINT_UPSTREAM, file=FOOTAGE_INDEX_NAME)
    return path, data


def fetched_paths(data):
    """`video_id` -> the file it was fetched to, for every `fetched[]` entry
    that carries both.

    A malformed or pathless entry is skipped here rather than raised: whether
    it matters depends on whether some topic actually names that source, and
    that question is `topic_pool()`'s. Before CF-0274 an entry with no `path`
    stopped the whole stage, which is how one hung indexer run (`HEaXDIrGhS4`,
    batch `2026-09-18T1058Z`) cost four other topics their coverage check.
    """
    out = {}
    for entry in data.get(FETCHED_KEY) or []:
        if not isinstance(entry, dict):
            continue
        video_id, path = entry.get("video_id"), entry.get("path")
        if isinstance(video_id, str) and isinstance(path, str) and path:
            out.setdefault(video_id, path)
    return out


def topic_pool(index_path, data, topic_id):
    """The pool ONE topic is judged against: its own canonical sources, and
    nothing else.

    This is CF-0274's first finding and the only scope this check has.
    `sources_by_topic[topic_id]` is the list the Video Editor's own resolve
    runs on - the two sources fetched for this topic and cleared for it - so
    it is the only pool whose answer means anything. A check run over every
    fetched source of the batch answers a question nobody asked: Pine Park's
    "23/23 covered" of `2026-09-18T1058Z` was covered by Delver's, Traitors'
    and Famine Trials' footage, and the topic's own two sources hold sixteen
    shots in total. There is deliberately no flag to widen it back - a default
    that has to be turned off by hand is a default that is used.

    Returns `{topic_id, video_ids, indexes, unindexed}`. `unindexed` names the
    canonical sources with no `<video_id>.shots.json`: they are dropped from
    the pool with a sentence each rather than stopping the stage, because the
    resolve cannot use them either.
    """
    ids = data.get(SOURCES_BY_TOPIC_KEY, {}).get(topic_id)
    if not isinstance(ids, list) or not ids:
        raise CannotAnswer(
            f"{index_path}: `{SOURCES_BY_TOPIC_KEY}` has no source list for topic "
            f"{topic_id!r} - the pool this script will actually be resolved against is not "
            f"recorded anywhere, and judging it against the batch's other footage is the "
            f"defect CF-0274 removed. Nothing is claimed about this batch",
            point=POINT_UPSTREAM, file=FOOTAGE_INDEX_NAME)
    paths = fetched_paths(data)
    indexes, unindexed = [], []
    for video_id in ids:
        src = paths.get(video_id)
        if not src:
            unindexed.append({"video_id": video_id,
                              "reason": f"no `{FETCHED_KEY}[]` entry with a usable `path`"})
            continue
        index = Path(src).with_suffix(SHOTS_SUFFIX)
        if index.exists():
            indexes.append(str(index))
        else:
            unindexed.append({"video_id": video_id, "reason": f"no shot index at {index}"})
    return {"topic_id": topic_id, "video_ids": list(ids),
            "indexes": indexes, "unindexed": unindexed}


_SHOTS_CACHE = {}


def shot_inventory(indexes):
    """`<video_id>:<n>` -> the shot's one-line description and whether it is a
    card. What the pool can actually show, in the writer's own terms."""
    out = {}
    for index in indexes:
        data = _SHOTS_CACHE.get(index)
        if data is None:
            try:
                data = json.loads(Path(index).read_text())
            except (OSError, ValueError):
                continue
            # The embeddings are the bulk of the file and nothing here reads
            # them; keep only what the report prints.
            data = {"source": data.get("source"),
                    "shots": [{k: s.get(k) for k in ("index", "description", "is_card")}
                              for s in data.get("shots", [])]}
            _SHOTS_CACHE[index] = data
        stem = Path(str(data.get("source") or index)).stem
        for shot in data["shots"]:
            out[f"{stem}:{shot['index']}"] = {
                "description": (shot.get("description") or "").strip(),
                "is_card": bool(shot.get("is_card")),
            }
    return out


# --------------------------------------------------------------------------
# the field the writer fills in
# --------------------------------------------------------------------------

def counted_sections(channel, root=None):
    """The sections TTS reads, from the channel's `narration_budget` - the same
    place step 6's budget check reads them, so an anchor can only be pinned to
    words that will actually be spoken."""
    try:
        return tuple(load_budget(channel, root)["counted_sections"])
    except (FileNotFoundError, KeyError):
        return FALLBACK_SECTIONS


def check_anchor(anchor, i, script, sections, seen_ids, graphics=False):
    """Problems with one `visual_anchors` entry; each names its field.
    `graphics` (CF-0689): the channel draws its own graphics, so an anchor
    with `graphic_id` places one and needs no `phrase`."""
    p = f"{FIELD}[{i}]"
    if not isinstance(anchor, dict):
        return [f"{p}: must be an object, got {type(anchor).__name__}"]
    problems = []
    places_graphic = graphics and ogl.is_graphic_anchor(anchor)
    required = GRAPHIC_REQUIRED_KEYS if places_graphic else REQUIRED_KEYS
    for key in required:
        if key not in anchor:
            problems.append(f"{p}.{key}: missing")
    extra = sorted(set(anchor) - set(required) - set(OPTIONAL_KEYS))
    if extra:
        problems.append(f"{p}: unknown key(s) {extra} - an anchor is a phrase, the words it "
                        f"lands on and (optionally) its side of the axis; the word "
                        f"index, the shot and the block are the Video Editor's")
    anchor_id = anchor.get("anchor_id")
    if "anchor_id" in anchor:
        if not isinstance(anchor_id, str) or not ANCHOR_ID_RE.match(anchor_id):
            problems.append(f"{p}.anchor_id: {anchor_id!r} must match {ANCHOR_ID_RE.pattern}")
        elif anchor_id in seen_ids:
            problems.append(f"{p}.anchor_id: {anchor_id!r} is not unique in this script's {FIELD}[]")
        seen_ids.add(anchor_id)
    if places_graphic:
        gid = anchor.get(ogl.ANCHOR_KEY)
        if not isinstance(gid, str) or not ANCHOR_ID_RE.match(gid):
            problems.append(f"{p}.{ogl.ANCHOR_KEY}: {gid!r} must be the `graphic_id` of one of "
                            f"the script's `graphics[]` (CF-0689)")
    phrase = anchor.get("phrase")
    if "phrase" in anchor and (not isinstance(phrase, str) or not phrase.strip()):
        problems.append(f"{p}.phrase: must be a non-empty string - the frame the moment has to "
                        f"show, described as a frame and not as a concept")
    beat = anchor.get("beat_text")
    if "beat_text" in anchor:
        if not isinstance(beat, str) or not beat.strip():
            problems.append(f"{p}.beat_text: must be a non-empty string")
        elif not any(isinstance(script.get(sec), str) and beat in script[sec] for sec in sections):
            problems.append(f"{p}.beat_text: not a verbatim substring of any counted section "
                            f"({', '.join(sections)}) - the Video Editor turns these exact words "
                            f"into the anchor's word index after alignment")
    if "side" in anchor and anchor["side"] is not None and anchor["side"] not in SIDES:
        problems.append(f"{p}.side: {anchor['side']!r} must be 'a', 'b' or null (CF-0050)")
    return problems


def check_shape(script, sections, graphics=False):
    """Problems with one script's `visual_anchors` as a field. An absent or
    empty field is itself a problem: a script no frame was written for is the
    blind writing CF-0140 exists to end."""
    anchors = script.get(FIELD)
    if anchors is None:
        return [f"{FIELD}: missing - every script declares the frames it has to show, before "
                f"TTS, so the pool can be asked (CF-0140); a script with none is written blind"]
    if not isinstance(anchors, list):
        return [f"{FIELD}: must be a list, got {type(anchors).__name__}"]
    if not anchors:
        return [f"{FIELD}: empty - at least one moment of every script has to be seen"]
    problems, seen = [], set()
    for i, anchor in enumerate(anchors):
        problems += check_anchor(anchor, i, script, sections, seen, graphics)
    return problems


def pool_view(script, graphics=False):
    """The script as the pool is asked about it: on a channel that draws its
    own graphics (CF-0689) every graphic anchor is left out - the pool never
    pictures it. The script itself when nothing is left out."""
    if not graphics:
        return script
    anchors = script.get(FIELD) or []
    pool = [a for a in anchors if not ogl.is_graphic_anchor(a)]
    if len(pool) == len(anchors):
        return script
    return dict(script, **{FIELD: pool})


def graphics_only(script):
    """Every anchor of the script places one of its own graphics (CF-0689)."""
    anchors = script.get(FIELD) if isinstance(script, dict) else None
    return (isinstance(anchors, list) and bool(anchors)
            and all(ogl.is_graphic_anchor(a) for a in anchors))


def graphics_only_record(script):
    """The record of a script whose every anchor places one of its own
    graphics (CF-0689): nothing is asked of the pool, nothing is missing from
    it - a pass, with no indexed source needed."""
    n = len(script.get(FIELD) or [])
    return {
        "topic_id": script.get("topic_id"),
        "anchors": 0,
        "graphic_anchors": n,
        "distinct_samples": 0,
        "margin_required": POOL_MARGIN_ANCHORS,
        "margin": None,
        "capacity": 0,
        "pool": {"sources": 0, "shots": 0},
        "indexes": [],
        "failed_attempts": previous_failures(script),
        "rewrites_allowed": REWRITES_ALLOWED,
        "action": ACTION_PASS,
        "reason": (f"every one of the {n} anchor(s) places one of the script's own graphics "
                   f"(`graphic_id`, CF-0689) - drawn by the Video Editor from the script's "
                   f"facts, never asked of the pool, so no indexed source is needed"),
        "warnings": [],
    }


def graphics_only_report(script, min_score=None):
    """The coverage report of an all-graphic script, in the Editor's report
    shape (its own preflight answers the same for no phrases): no anchor asks
    the pool, so the gates reading `--out` find an empty, passing report -
    screened at the resolver's own `min_score`, like any report they read."""
    n = len(script.get(FIELD) or [])
    return {"kind": REPORT_KIND, "passed": True, "refused_because": [], "anchor_count": 0,
            "covered_count": 0, "weak": [], "absent": [], "min_score": min_score,
            "score_floor": None, "anchors": [],
            "contention": {"anchors": 0, "distinct_samples": 0}, "pool": {"sources": 0, "shots": 0},
            "indexes": [], "graphic_anchors": n,
            INDEX_SPACE_KEY: INDEX_SPACE, GRAPHIC_INDICES_KEY: list(range(n)),
            "note": "no anchor asks the pool - every one places a graphic the factory "
                    "draws (CF-0689)"}


def in_script_space(report, script):
    """CF-0689: the report with its anchor indices in the script's own
    `visual_anchors[]` numbering. The preflight was asked about the pool
    anchors only, so on a script with graphic anchors its `anchors[]
    .anchor_index`, `weak` and `absent` count pool anchors; here they are
    mapped back and `graphic_anchor_indices` names the anchors the pool never
    saw. A report already renumbered, or a script without graphic anchors,
    comes back as it is (the same object)."""
    if not isinstance(report, dict) or report.get(INDEX_SPACE_KEY) == INDEX_SPACE:
        return report
    anchors = script.get(FIELD) if isinstance(script, dict) else None
    anchors = anchors if isinstance(anchors, list) else []
    graphic = [i for i, a in enumerate(anchors) if ogl.is_graphic_anchor(a)]
    if not graphic:
        return report
    pos = [i for i, a in enumerate(anchors) if not ogl.is_graphic_anchor(a)]

    def full(i):
        return pos[i] if isinstance(i, int) and not isinstance(i, bool) and 0 <= i < len(pos) else i

    out = copy.deepcopy(report)
    for rec in out.get("anchors") or []:
        if isinstance(rec, dict) and "anchor_index" in rec:
            rec["anchor_index"] = full(rec["anchor_index"])
    for key in ("weak", "absent"):
        if isinstance(out.get(key), list):
            out[key] = [full(i) for i in out[key]]
    out[INDEX_SPACE_KEY] = INDEX_SPACE
    out[GRAPHIC_INDICES_KEY] = graphic
    return out


def load_footage_index_for(batch_file, footage_index, scripts, graphics):
    """`load_footage_index`, except that a batch whose every script stands on
    its own graphics (CF-0689) asks the pool nothing - no footage index, or an
    empty one, is then no hole."""
    try:
        return load_footage_index(batch_file, footage_index)
    except CannotAnswer:
        if not (graphics and scripts and all(graphics_only(s) for s in scripts)):
            raise
        path = (Path(footage_index) if footage_index
                else Path(batch_file).parent / FOOTAGE_INDEX_NAME)
        return path, {SOURCES_BY_TOPIC_KEY: {}}


def topic_pool_for(index_path, data, script, graphics):
    """`topic_pool`, except that an all-graphic script (CF-0689) has an empty
    pool and needs no entry in `sources_by_topic`."""
    if graphics and graphics_only(script):
        return {"topic_id": script.get("topic_id"), "video_ids": [], "indexes": [],
                "unindexed": []}
    return topic_pool(index_path, data, script.get("topic_id"))


# --------------------------------------------------------------------------
# the call
# --------------------------------------------------------------------------

def preflight_command(paths, indexes, strict=False):
    """The argv, in one place so a test can pin what is NOT in it.

    No `--min-score` and no `--top`: both sides take
    `resolve_anchors.DEFAULT_MIN_SCORE` / `DEFAULT_TOP`, and a flag here is
    exactly how the two would drift apart.

    And no `--strict` either, since CF-0291. The flag used to be the only way
    to have a weak anchor refused; CF-0290 made that the preflight's own
    answer, so passing it would say this run asked for something it did not -
    the sibling refuses a weak anchor whether or not it is there. `strict` is
    still taken as an argument so that every caller keeps compiling and every
    test that pins the argv keeps pinning the same list.
    """
    cmd = [str(paths["python"]), str(paths["coverage"]), "-", "--quiet"]
    for index in indexes:
        cmd += ["--index", str(index)]
    return cmd


def remeasure_script(message):
    """The `remeasure_*` script the preflight's refusal named, or None.

    Matched against the other repositories' own wording rather than parsed out
    of it: the caption gate prints the command with the stale indexes in it and
    the usability warning prints it with a literal `<video>` placeholder, so
    there is no line in either that could be executed as written. What this
    gate takes from the message is *which* cache went stale; the targets are
    the index paths it was judging against anyway.
    """
    text = (message or "").lower()
    for phrase, script in REMEASURE_BY_CAUSE:
        if phrase.lower() in text:
            return script
    return None


def remeasure(script, indexes, root=None, timeout=REMEASURE_TIMEOUT):
    """Run one `remeasure_*` over these indexes, labelled `pool-maintenance`.

    Returns `(ok, detail)`. Never raises: a repair that fell over is one more
    reason to close the stage with the code, and never a reason to stop the run
    and ask.
    """
    root = Path(root) if root else find_root()
    tool = root / INDEXER_REL / REMEASURE_REL / script
    python = root / INDEXER_REL / INDEXER_PY_REL
    missing = [str(p) for p in (tool, python) if not p.exists()]
    if missing:
        return False, f"{', '.join(missing)} is missing - the repair cannot be run here"
    if not indexes:
        return False, "the refusal named no index to re-measure"
    cmd = [str(python), str(tool), *[str(i) for i in indexes]]
    env = dict(os.environ, RUNLOG_STAGE=MAINTENANCE_STAGE)
    try:
        cp = runlog.run_child(cmd, tool=script, stage=MAINTENANCE_STAGE,
                              step=REMEASURE_STEP.get(script), capture_output=True,
                              text=True, timeout=timeout, env=env)
    except Exception as exc:  # timeout, OS error - both are "not repaired"
        return False, f"`{script}` did not finish: {exc}"
    if cp.returncode != 0:
        tail = [ln for ln in (cp.stderr or "").splitlines() if ln.strip()][-4:]
        return False, f"`{script}` exited {cp.returncode}: " + " / ".join(tail)
    return True, f"`{script}` re-measured {len(indexes)} index(es)"


def run_preflight(phrases, indexes, paths, knobs, strict=False, timeout=DEFAULT_TIMEOUT):
    """One subprocess, one report. Raises CannotAnswer rather than guessing."""
    cmd = preflight_command(paths, indexes, strict)
    payload = json.dumps({"phrases": list(phrases)})
    try:
        cp = runlog.run_child(cmd, tool="anchor_coverage.py", input=payload,
                              capture_output=True, text=True, timeout=timeout)
    except Exception as exc:  # timeout, missing interpreter, OS error
        raise CannotAnswer(f"the coverage preflight did not run: {exc}")
    if cp.returncode not in (0, 2):
        # Its own diagnosis, not a summary of it: a stale caption cache or an
        # unindexed source is fixed by the sentence that tool prints.
        tail = [ln for ln in (cp.stderr or "").splitlines()
                if ln.strip() and not ln.startswith("[runlog]")][-12:]
        text = "\n".join(f"  | {ln}" for ln in tail)
        # CF-0317: and one of those sentences names a repair this gate can run
        # itself. Everything else here is the machine and is not repairable
        # inside a batch.
        script = remeasure_script(cp.stderr or "")
        raise CannotAnswer(
            f"anchor_coverage.py exited {cp.returncode}:\n" + text,
            point=POINT_STALE if script else POINT_ENV,
            remeasure=script, indexes=[str(i) for i in indexes])
    try:
        report = json.loads(cp.stdout)
    except ValueError as exc:
        raise CannotAnswer(f"the coverage preflight printed no readable report: {exc}")
    if report.get("min_score") != knobs["min_score"]:
        raise CannotAnswer(
            f"the preflight judged at min_score={report.get('min_score')} while "
            f"resolve_anchors.DEFAULT_MIN_SCORE is {knobs['min_score']} - the two are "
            f"screening different pools and no answer of theirs can be compared")
    return report


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

SAMPLES_SHOWN = 5


def anchor_lines(report, anchors, inventory):
    """One line per anchor, with what the pool offered under it. `samples` is
    the answer to "what should I aim at instead" and is printed for every
    anchor that has any."""
    lines = []
    for rec in report.get("anchors", []):
        i = rec.get("anchor_index", 0)
        anchor_id = (anchors[i].get("anchor_id") if i < len(anchors)
                     and isinstance(anchors[i], dict) else f"#{i}")
        verdict = rec.get("verdict")
        head = f"    [{verdict}] {anchor_id} {rec.get('phrase')!r}"
        if verdict == VERDICT_ABSENT:
            head += f" - {rec.get('cause')}"
        elif verdict == VERDICT_WEAK:
            # CF-0290 turned this line around. It used to read "a picture will
            # be shown and it will not be this moment": the resolver took the
            # best under-floor candidate and recorded the anchor unresolved.
            # It does not any more - `screen_pool()` takes those candidates out
            # of the pool - so the block this anchor drives gets NOTHING, and
            # the script does not leave this stage.
            head += (f" - the best of {rec.get('candidates')} ranked candidate(s) scores "
                     f"{rec.get('best_offered_score')}, under the {report.get('min_score')} "
                     f"floor: nothing in this pool is a picture of this phrase, so the block "
                     f"takes the best of it at a price (`score.low_similarity`, CF-0433). "
                     + ("A warning (CF-0330): the script goes on as written"
                        if gw.warns(gw.GATE_ANCHOR_COVERAGE)
                        else "Rewrite this anchor at a frame the pool has"))
        samples = rec.get("samples") or []
        if samples:
            shown = samples[:SAMPLES_SHOWN]
            head += " - " + ", ".join(shown)
            if len(samples) > len(shown):
                head += f" (+{len(samples) - len(shown)} more)"
        lines.append(head)
        if rec.get("detail") and verdict != VERDICT_COVERED:
            lines.append(f"        {rec['detail']}")
        if rec.get("discriminative") is False:
            # CF-0009's margin, carried through: reported, never refused here
            # - whether the writing is about anything is the Compliance
            # Checker's half of CF-0043, not this gate's.
            lines.append("        the phrase singles out no shot in this pool - it describes an "
                         "idea rather than a frame; whichever shot the resolve takes will be "
                         "roughly arbitrary")
        for sample in samples[:SAMPLES_SHOWN]:
            shot = inventory.get(sample)
            if shot and shot["description"]:
                lines.append(f"        {sample}: {shot['description']}"
                             + ("  [card]" if shot["is_card"] else ""))
    return lines


def inventory_lines(report, inventory, limit, rewrite=True):
    """What the pool holds, marked with which anchor took it. Printed on a
    refusal: an anchor is rewritten towards a frame that exists, and this is
    the list of frames that exist."""
    taken = {}
    for rec in report.get("anchors", []):
        for sample in rec.get("samples") or []:
            taken.setdefault(sample, rec.get("anchor_index"))
    lines = [f"    the pool holds {len(inventory)} shot(s); aim the rewritten anchors at these:"
             if rewrite else
             f"    the pool holds {len(inventory)} shot(s) (for the record - a warning, "
             f"nothing to rewrite, CF-0330):"]
    shown = 0
    for name, shot in inventory.items():
        if shown >= limit:
            lines.append(f"      ... and {len(inventory) - shown} more "
                         f"(read the contact sheets; --max-inventory to see them all)")
            break
        mark = f"  <- anchor #{taken[name]}" if name in taken else ""
        desc = shot["description"] or "(no description in the index - read the contact sheet)"
        lines.append(f"      {name}{'  [card]' if shot['is_card'] else ''}: {desc}{mark}")
        shown += 1
    return lines


def refusal_summary(report, limit=6):
    """What the Video Editor's gate threw out of this pool, counted by reason.

    CF-0274's second finding, made visible: the writer's own measure was
    semantic (does a shot description read like this phrase), the Editor's is
    that plus the usability gate, and when the two disagree it is always this
    list that explains it. Every line here is the Editor's own sentence out of
    the preflight's `refusals[]` - a per-candidate record this file has always
    received and never printed. Numbers are folded to `#` so that thirty
    refusals of the same kind arrive as one line with a count.
    """
    counts, causes = {}, {}
    for rec in report.get("anchors", []):
        for refusal in rec.get("refusals") or []:
            reason = str(refusal.get("reason") or refusal.get("cause") or "?")
            key = re.sub(r"[0-9]+(?:\.[0-9]+)?", "#", reason)[:100]
            counts[key] = counts.get(key, 0) + 1
            causes.setdefault(key, refusal.get("cause"))
    ranked = sorted(counts.items(), key=lambda kv: -kv[1])
    total = sum(counts.values())
    return total, [(reason, n, causes.get(reason)) for reason, n in ranked[:limit]]


def pool_lines(pool, record, report=None):
    """The pool's own lines: which sources it is, what it carries, and - when
    the Editor's gate emptied it - what the gate refused."""
    lines = [f"    pool: topic {pool['topic_id']}, {len(pool['indexes'])} of "
             f"{len(pool['video_ids'])} canonical source(s) indexed "
             f"({', '.join(Path(i).name for i in pool['indexes']) or 'none'})"]
    for miss in pool["unindexed"]:
        lines.append(f"      left out: {miss['video_id']} - {miss['reason']}")
    if record:
        lines.append(f"      {record['distinct_samples']} distinct usable sample(s) carry "
                     f"{max(record['capacity'], 0)} anchor(s) (margin "
                     f"{record['margin_required']}); this script has {record['anchors']}")
    if report is not None:
        total, top = refusal_summary(report)
        if total:
            lines.append(f"      the Editor's gate refused {total} candidate(s) of this pool:")
            for reason, n, cause in top:
                lines.append(f"        {n}x {reason}" + (f"  [{cause}]" if cause else ""))
    return lines


def script_report(script, report, inventory):
    """The lines for one judged script, plus its one-line verdict."""
    anchors = script.get(FIELD) or []
    passed = bool(report.get("passed"))
    sid = script.get("script_id")
    why = ", ".join(report.get("refused_because") or [])
    head = (f"  ok     {sid}: {report.get('covered_count')}/{report.get('anchor_count')} anchors "
            f"covered, {len(report.get('weak') or [])} weak"
            if passed else
            f"  {'WARN  ' if gw.warns(gw.GATE_ANCHOR_COVERAGE) else 'REFUSE'} {sid}: {why} - "
            f"{report.get('note')}")
    lines = [head] + anchor_lines(report, anchors, inventory)
    contention = report.get("contention") or {}
    if contention.get("note"):
        lines.append(f"    contention: {contention['note']}")
    return lines


# --------------------------------------------------------------------------
# the batch
# --------------------------------------------------------------------------

# CF-0412: what the visual-claim warning of this step is measured on.
VISUAL_CLAIM_MEASURE = ("step 6 preflight: anchor_coverage.py's per-anchor verdict and the "
                        "anchor's phrase; step 6b measures it again on the real resolve")


def claim_judgement(script, claims):
    """CF-0437: what the uncovered visual claims of one script cost at step 6.

    `rewrite` the first time (the text can still change here, and the pool's
    layout says what it can show); `warn` once the one rewrite is spent - the
    CF-0412 warning, the script goes on; `pass` with no uncovered claim."""
    before = script.get(CLAIM_RECORD_KEY)
    failed = before.get("failed_attempts") if isinstance(before, dict) else 0
    failed = failed if isinstance(failed, int) and not isinstance(failed, bool) else 0
    if not claims:
        return {"action": ACTION_PASS, "failed_attempts": failed, "claims": 0,
                "task": "CF-0437", "reason": "every visual claim is answered by its anchor"}
    if failed < CLAIM_REWRITES_ALLOWED:
        return {"action": ACTION_REWRITE, "failed_attempts": failed + 1, "claims": len(claims),
                "rewrites_allowed": CLAIM_REWRITES_ALLOWED, "task": "CF-0437",
                "reason": (f"visual claim: {len(claims)} line(s) point at a picture no usable "
                           f"shot answers - reword each to a shot the pool holds "
                           f"(pool_layout.py) or make the point without pointing; one "
                           f"rewrite, then it is a warning and the script goes on (CF-0437)")}
    return {"action": gw.ACTION_WARN, "failed_attempts": failed, "claims": len(claims),
            "rewrites_allowed": CLAIM_REWRITES_ALLOWED, "task": "CF-0437",
            "reason": (f"visual claim: {len(claims)} line(s) still point at a picture the pool "
                       f"does not hold after the one rewrite - a warning, the script goes on "
                       f"(CF-0412, CF-0437)")}


def check_batch(batch_file, root=None, footage_index=None, script_id=None, strict=False,
                editor_python=None, coverage_script=None, timeout=DEFAULT_TIMEOUT,
                max_inventory=40, out=print, write=False):
    """Judge every script of the batch against **its own topic's** pool.
    Returns `(problems, reports, records, refused)`.

    `problems` are the reasons a script is rewritten - a malformed field, a
    pool that cannot picture it, or a pool that can carry fewer anchors than
    it has (CF-0274's new rung). A `CannotAnswer` is raised, never returned as
    a problem: the difference between "rewrite the script" and "fix the
    environment" is the whole reason this script has a third exit code.

    The pool refusal is the fourth kind of answer and is deliberately not a
    `problem`: it comes back in `records` as an `action` of `refuse`, so no
    caller of this function can mistake it for something to rewrite. With
    `write` the record goes onto every judged script (which is where the one
    allowed rewrite is counted between runs), a refused topic is taken out of
    `scripts[]` and recorded in `skipped[]`, and the file is rewritten once -
    a loss the funnel cannot see is a topic that merely vanished (CF-0232).
    """
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {batch_file}: {exc}")
    # CF-0197: a batch written before the channel was renamed carries the
    # old id frozen in this field - the file is a dated record and is not
    # rewritten - so resolve it before anything is looked up under it.
    channel = resolve_channel(data.get("channel"), root)
    sections = counted_sections(channel, root) if channel else FALLBACK_SECTIONS
    # CF-0689: the channel's switch for its own graphics (footage-origin.json).
    graphics = ogl.channel_draws(channel, root or find_root())
    paths = editor_paths(root, editor_python, coverage_script)
    knobs = matcher_knobs(paths["resolver"])
    scripts = [s for s in data.get("scripts", [])
               if script_id is None or s.get("script_id") == script_id]
    # CF-0689: a batch whose every script stands on its own graphics asks
    # the pool nothing - no footage index (or an empty one) is no hole.
    index_path, index_data = load_footage_index_for(batch_file, footage_index, scripts,
                                                    graphics)
    # CF-0430: the rewrite this gate asked for, not made - judged no again.
    held = []
    scripts, _unchanged, same = rg.split(scripts, RECORD_KEY, sections, held.append, write)
    # CF-0437: the same guard on the visual claim's own rewrite.
    scripts, _unchanged_claims, same_claims = rg.split(scripts, CLAIM_RECORD_KEY, sections,
                                                       held.append, write)
    # CF-0576: and on the interview anchor's.
    scripts, _unchanged_iv, same_iv = rg.split(scripts, evf.INTERVIEW_RECORD_KEY, sections,
                                               held.append, write)
    same = list(same) + list(same_claims) + list(same_iv)
    out(f"{batch_file}: {len(scripts)} script(s); pool per topic from "
        f"{index_path.name} `{SOURCES_BY_TOPIC_KEY}` (never the batch's other footage, "
        f"CF-0274); matcher min_score={knobs['min_score']} top={knobs['top']} "
        f"(resolve_anchors.py's own constants, not settable here); "
        f"an anchor whose whole pool is under the floor is the preflight's own `weak` "
        f"(CF-0290/CF-0291; `--strict` is a no-op){' - passed and ignored' if strict else ''}; "
        f"margin {POOL_MARGIN_ANCHORS} distinct sample(s) over the anchor count; a shortfall "
        f"is a `{SKIP_REASON_CODE}` warning and the script goes on (CF-0330)")
    out(f"  note: {PASS_CAVEAT}")
    for line in held:
        out(line)

    problems, reports, records, refused, warnings = list(same), {}, {}, [], []
    claim_records, ev_records, iv_records = {}, {}, {}
    for real in scripts:
        sid = real.get("script_id")
        shape = check_shape(real, sections, graphics)
        if shape:
            out(f"  FAIL   {sid}: {len(shape)} problem(s) with `{FIELD}` - the pool was not asked")
            problems += [f"{sid}: {p}" for p in shape]
            continue
        # CF-0689: the pool is asked only for the anchors it has to picture.
        script = pool_view(real, graphics)
        if graphics and not script.get(FIELD):
            records[sid] = graphics_only_record(real)
            reports[sid] = graphics_only_report(real, knobs.get("min_score"))
            out(f"  ok     {sid}: {records[sid]['reason']}")
            continue
        if script is not real:
            out(f"  note   {sid}: {len(real[FIELD]) - len(script[FIELD])} of "
                f"{len(real[FIELD])} anchor(s) place the script's own graphics (CF-0689) - "
                f"the pool is asked for the other {len(script[FIELD])}")
        pool = topic_pool(index_path, index_data, script.get("topic_id"))
        if not pool["indexes"]:
            record = records[sid] = unindexed_judgement(script, pool)
            out(f"  REFUSE {sid}: {SKIP_REASON_CODE} - {record['reason']}")
            for line in pool_lines(pool, record):
                out(line)
            refused.append(real)
            continue
        inventory = shot_inventory(pool["indexes"])
        phrases = [a["phrase"] for a in script[FIELD]]
        report = run_preflight(phrases, pool["indexes"], paths, knobs, strict, timeout)
        # CF-0575: the anchors that retell the hunter's on-screen scene count
        # only the event's own footage - here, before every gate of this stage
        # reads the report (and before `--out` hands it to block capacity and
        # the two-source spread).
        ev_scope = evf.scope_for(script, path.parent, pool, report)
        report = reports[sid] = evf.narrow(report, ev_scope)
        record = pool_judgement(report, script)
        if record is None:
            raise CannotAnswer(
                f"{sid}: the preflight's report carries no anchor count or no "
                f"`contention.distinct_samples` - the pool cannot be measured against the "
                f"script and nothing is claimed about it")
        records[sid] = record
        # CF-0330: the pool's margin and the preflight's verdict warn now. The
        # ladder above still says what it would have done (`would_have`); the
        # script stays, nothing is rewritten, and the numbers go to warnings[].
        warned = []
        if record["action"] in (ACTION_REWRITE, ACTION_REFUSE) and gw.warns(gw.GATE_ANCHOR_POOL):
            record["would_have"] = record["action"]
            record["action"] = gw.ACTION_WARN
            record["failed_attempts"] = previous_failures(script)
            warned.append(gw.entry(script.get("topic_id"), sid, gw.GATE_ANCHOR_POOL,
                                   SKIP_REASON_CODE, pool_warning(record),
                                   numbers=pool_numbers(record)))
            # CF-0342: what the pool is short of, by entity - the request
            # skeleton `--write` puts under work/supplement-requests/.
            warned[-1][sreq.FIELD] = sreq.from_pool(script, record)
        if not report.get("passed") and gw.warns(gw.GATE_ANCHOR_COVERAGE):
            warned.append(gw.entry(script.get("topic_id"), sid, gw.GATE_ANCHOR_COVERAGE,
                                   SKIP_REASON_CODE, coverage_reason(report, warn=True),
                                   numbers=coverage_numbers(report)))
            warned[-1][sreq.FIELD] = sreq.from_coverage(script, report)
        # CF-0412: a line of the narrator that points at a picture ("that shot
        # of X in the trailer") whose anchor the pool does not picture, or
        # pictures with something else. A warning only - no rewrite is owed;
        # it is the one moment the writer can still reword it to the pool.
        # CF-0575: the event's own footage against the anchors that retell it.
        ev_record = ev_records[sid] = evf.judge(script, report, ev_scope)
        if ev_record["action"] == evf.ACTION_WARN:
            warned.append(gw.entry(script.get("topic_id"), sid, gw.GATE_EVENT_FOOTAGE,
                                   evf.WARNING_CODE, ev_record["reason"],
                                   numbers=evf.numbers(ev_record)))
            warned[-1][sreq.FIELD] = sreq.from_event(script, ev_record)
        # CF-0576: an anchor that asks for another production's interview
        # under words that do not name it - one rewrite, then a warning.
        iv_record = iv_records[sid] = evf.interview_judgement(script, ev_scope)
        if iv_record["action"] == gw.ACTION_WARN:
            warned.append(gw.entry(script.get("topic_id"), sid, evf.INTERVIEW_GATE,
                                   evf.INTERVIEW_WARNING_CODE, iv_record["reason"],
                                   numbers={"anchors": iv_record.get("anchors") or []}))
            warned[-1]["predicts"] = evf.INTERVIEW_PREDICTS
        claims = vc.judge(script, vc.preflight_status(report, script))
        claim_record = claim_records[sid] = claim_judgement(script, claims)
        # CF-0437: the first time it is a rewrite (below), not a warning.
        claim = (vc.entry(script, claims, vc.GATE_PREFLIGHT, stage_note=VISUAL_CLAIM_MEASURE)
                 if claim_record["action"] == gw.ACTION_WARN else None)
        if claim:
            warned.append(claim)
        record["warnings"] = warned
        warnings.extend(warned)
        if record["action"] == ACTION_REFUSE:
            out(f"  REFUSE {sid}: {SKIP_REASON_CODE} - {record['reason']}")
            # Deliberately not `inventory_lines()`: that list is headed "aim
            # the rewritten anchors at these", and there is no rewrite here.
            for line in pool_lines(pool, record, report):
                out(line)
            refused.append(real)
            continue
        for line in script_report(script, report, inventory):
            out(line)
        for line in pool_lines(pool, record, report):
            out(line)
        for line in evf.lines(ev_record):
            out(line)
        for line in evf.interview_lines(iv_record):
            out(line)
        for w in warned:
            out(gw.line(w))
        if record["action"] == ACTION_REWRITE:
            out(f"  REWRITE {sid}: {record['reason']}")
            problems.append(f"{sid}: {record['reason']}")
        if claim_record["action"] == ACTION_REWRITE:
            out(f"  REWRITE {sid}: {claim_record['reason']}")
            out(f"    {vc.detail(claims)}")
            problems.append(f"{sid}: {claim_record['reason']}")
        if iv_record["action"] == ACTION_REWRITE:
            out(f"  REWRITE {sid}: {iv_record['reason']}")
            problems.append(f"{sid}: {iv_record['reason']}")
        if not report.get("passed") and not gw.warns(gw.GATE_ANCHOR_COVERAGE):
            problems.append(f"{sid}: {coverage_reason(report)}")
        if not report.get("passed") or record["action"] in (ACTION_REWRITE, gw.ACTION_WARN):
            rewrite = (record["action"] == ACTION_REWRITE
                       or (not report.get("passed") and not gw.warns(gw.GATE_ANCHOR_COVERAGE)))
            for line in inventory_lines(report, inventory, max_inventory, rewrite=rewrite):
                out(line)

    # CF-0689: the reports handed on are numbered like the script's anchors.
    by_sid = {s.get("script_id"): s for s in scripts}
    for sid in list(reports):
        reports[sid] = in_script_space(reports[sid], by_sid.get(sid))

    if write:
        for script in scripts:
            record = records.get(script.get("script_id"))
            if record:
                script[RECORD_KEY] = rg.stamp(record, script, sections)
            claim_record = claim_records.get(script.get("script_id"))
            if claim_record:
                script[CLAIM_RECORD_KEY] = rg.stamp(claim_record, script, sections)
            ev_record = ev_records.get(script.get("script_id"))
            if ev_record and ev_record.get("action") != evf.ACTION_OFF:
                script[evf.RECORD_KEY] = ev_record
            elif script.get("script_id") in ev_records:
                script.pop(evf.RECORD_KEY, None)
            iv_record = iv_records.get(script.get("script_id"))
            if iv_record and iv_record.get("action") != evf.ACTION_OFF:
                script[evf.INTERVIEW_RECORD_KEY] = rg.stamp(iv_record, script, sections)
            elif script.get("script_id") in iv_records:
                script.pop(evf.INTERVIEW_RECORD_KEY, None)
        judged = [s.get("topic_id") for s in scripts if s.get("script_id") in records]
        for gate in (gw.GATE_ANCHOR_POOL, gw.GATE_ANCHOR_COVERAGE, vc.GATE_PREFLIGHT,
                     gw.GATE_EVENT_FOOTAGE, evf.INTERVIEW_GATE):
            gw.clear(data, judged, gate)
        gw.record(data, warnings)
        # CF-0342: one request skeleton per topic still warned, none for a
        # topic the pool covers now.
        for line in sreq.lines(*sreq.sync(path.parent, data, judged)):
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
    return problems, reports, records, refused


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("batch_file", help="pipeline/<channel>/<batch>/03-content-researcher.json")
    ap.add_argument("--footage-index", default=None,
                    help=f"the batch's {FOOTAGE_INDEX_NAME} (default: beside the batch file)")
    ap.add_argument("--script-id", default=None, help="judge one script instead of the batch")
    ap.add_argument("--strict", action="store_true",
                    help="accepted and ignored (CF-0291). An anchor whose whole ranked pool is "
                         "under the similarity floor has been a refusal since CF-0290, with or "
                         "without this flag - the resolver offers such a block nothing, so "
                         "there is no looser line for the flag to tighten")
    ap.add_argument("--out", default=None,
                    help="write the reports here as JSON. CF-0280: this is also how the "
                         "two-source gate (check_two_sources.py --reports) gets its answers - "
                         "it replays the resolve over these same reports instead of paying "
                         "for a second CLIP load per script, so step 6 always passes it")
    ap.add_argument("--root", default=None, help="shorts-content-factory checkout (default: found)")
    ap.add_argument("--editor-python", default=None,
                    help="interpreter for the Video Editor's preflight (default: its .venv)")
    ap.add_argument("--coverage-script", default=None,
                    help="path to anchor_coverage.py (default: the Video Editor's)")
    ap.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT,
                    help="seconds for one preflight call; the matcher loads CLIP")
    ap.add_argument("--max-inventory", type=int, default=40,
                    help="how many pool shots to list under a refusal")
    ap.add_argument("--write", action="store_true",
                    help="record the pool verdict on every script, the pool's warnings "
                         "into warnings[] (CF-0330), and move a topic with no indexed source "
                         "into skipped[] as `pool_too_thin`. No verdict on any anchor is "
                         "ever written back")
    ap.add_argument("--remeasure-timeout", type=float, default=REMEASURE_TIMEOUT,
                    help="seconds for the one `remeasure_*` this gate may run")
    # No --min-score and no --top, deliberately: see the module docstring.
    # No pool scope either: the pool is the topic's own sources and there is
    # no flag that widens it back (CF-0274).
    args = ap.parse_args(argv)
    root = Path(args.root).resolve() if args.root else None

    def ask():
        return check_batch(
            args.batch_file, root=root,
            footage_index=args.footage_index, script_id=args.script_id, strict=args.strict,
            editor_python=args.editor_python, coverage_script=args.coverage_script,
            timeout=args.timeout, max_inventory=args.max_inventory, write=args.write)

    try:
        problems, reports, records, refused = ask()
    except CannotAnswer as exc:
        # CF-0317: one of the four exit-3 causes describes its own repair. The
        # stale cache is re-measured here, under the `pool-maintenance` label
        # the pool's work belongs to, and the question is put again - **once**.
        # A second refusal after a fresh measurement is not a stale cache, so
        # it is recorded with the same code and the stage closes on it; the run
        # never stops to be asked which of the four causes it was.
        if exc.point == POINT_STALE:
            ok, detail = remeasure(exc.fields.get("remeasure"), exc.fields.get("indexes") or [],
                                   root=root, timeout=args.remeasure_timeout)
            print(f"check_anchor_coverage.py: the pool's measurements were stale; "
                  f"{detail} ({MAINTENANCE_STAGE}, CF-0317)", file=sys.stderr)
            if ok:
                try:
                    problems, reports, records, refused = ask()
                    exc = None
                except CannotAnswer as again:
                    # Whatever the second ask ran into is what gets recorded:
                    # a stale cache again (the code below), or another cause
                    # the fresh measurement uncovered, under its own code.
                    exc = again
        if exc is not None:
            print(f"check_anchor_coverage.py: {exc}", file=sys.stderr)
            print("nothing is claimed about the scripts; do not rewrite anything on this run",
                  file=sys.stderr)
            # And the run does not stop here to be asked about. The exit names
            # the code the stage records and the note it closes with.
            print(nw.refuse(exc.point, **exc.note_fields()), file=sys.stderr)
            return EXIT_CANNOT_ANSWER
    warned = [w for r in records.values() for w in (r.get("warnings") or [])]
    if args.out:
        Path(args.out).write_text(json.dumps(
            {"reports": reports, "pool": records, "warnings": warned},
            indent=2, ensure_ascii=False))
    if warned:
        # CF-0330: said before the exit whatever the exit is - a warning is
        # the batch's record, not a stop, and the report of step 7 copies it.
        print(f"\n{len(warned)} warning(s) - the script(s) go on, nothing to rewrite "
              f"({gw.DECISION}):")
        for w in warned:
            print(gw.line(w))
    if problems:
        print(f"\n{len(problems)} problem(s):")
        for p in problems:
            print(f"  - {p}")
        return EXIT_REWRITE
    thin = {sid: r for sid, r in records.items() if r["action"] == ACTION_REFUSE}
    if thin:
        # After the rewrites on purpose: when one script is thin and another
        # is merely mis-aimed, the writer's move is the rewrite, and the thin
        # topic has already been recorded by then.
        print(f"\n{len(thin)} topic(s) refused as `{SKIP_REASON_CODE}` - the pool, not the "
              f"script; there is nothing to rewrite"
              + ("" if args.write else " and nothing was recorded (--write)"))
        for sid, t in thin.items():
            print(f"  - {sid}: {t['reason']}")
        return EXIT_POOL_TOO_THIN
    return EXIT_OK


@runlog.script("content-researcher", "check-anchor-coverage", name="check_anchor_coverage.py")
def cli():
    """The command-line entry (CF-0107). Unlike the other four checkers this
    one *does* call an external binary - the Video Editor's preflight, on its
    own venv - so it leaves one `child` event per script beside its own
    start/done, and the matcher's CLIP load is visible in that child's
    duration. A non-zero exit (1 = a script is refused or malformed, 3 = the
    environment could not answer) is recorded as `failed`, which is correct: a
    refusal before TTS is the record this task exists to produce."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
