#!/usr/bin/env python3
"""CF-0280: will this script put TWO sources on screen - asked before the voice
is paid for.

The hole
-------
`video_editor.two_source_gate` (CF-0118, `enforce` since CF-0129) refuses a
plan whose every footage block comes from one canonical source: YouTube calls
a video built from one upload a "compilation with no original content added"
and does not admit it to the Creator Pool. CF-0129 guarantees two sources are
**fetched** for every topic. Nothing asked the script to **use** the second
one, and the gate runs after TTS, after alignment and after the resolve - so
the whole voiceover is paid for before anyone finds out.

`example-film/2026-09-18T1058Z`, `lf-2026-09-18-008-script1` (Delver) is the
case: trailer `wIM1PDRvKSE` and GQ interview `fkuxNGbx1qk`, 60 indexed shots
each, and all seven blocks resolved from the interview. `no_second_source`,
after the voice.

What actually decided it, and why the phrases were not the culprit
------------------------------------------------------------------
The obvious reading of that batch - "all six anchors describe the interview's
set" - is wrong, and it matters, because a check built on it would refuse the
wrong scripts. Read against the Editor's own per-topic preflight
(`work/delver/anchor_preflight.json`), the trailer was the **best-scoring
usable candidate of four of the six anchors** and carried 23 distinct usable
samples. By score the script was as two-source as a script gets.

What took every block to the interview is `resolve_anchors.py`, at the point
where a block may hold only one shot::

    budget = seg["max_shots"] or len(pool)
    if budget == 1:
        pool = sorted(pool, key=lambda c: available_seconds(c) < need)

`need` is the block's own length in seconds. The sort is stable, so the
candidates long enough to fill the block keep their score order and move in
front of every candidate that is not. A trailer is cut in one-second shots
(`wIM1PDRvKSE`: median 1.58 s, 8 shots of 60 at four seconds or more); an
interview sits on long takes (`fkuxNGbx1qk`: median 4.07 s, 31 of 60 over four
seconds). On a `moment-breakdown`/`hold` script whose blocks run five to ten
seconds, *every* trailer shot sorts to the back of *every* block, and the
interview wins all seven no matter what the anchors say.

That is reconstructible exactly. Replaying the preflight's candidate lists
through "first still-unused sample that is long enough, else the first
still-unused sample" predicts all seven of Delver's blocks - shot for shot,
including the two the reuse cap (CF-0121) pushed onto a second choice. So this
gate does not model the resolve, it replays it:

  * the candidate order is the preflight's `anchors[].samples`, which is the
    resolver's own `order_candidates()` order, already screened by the
    resolver's own pre-cut gate **and, since CF-0290, by its similarity
    floor**: a candidate under `DEFAULT_MIN_SCORE` is not at the back of the queue,
    it is not in the queue. This gate reads the floor off the report and
    refuses to answer at all against an Editor checkout that does not screen
    (`editor_floors()`);
  * one sample, one use (CF-0121) - a sample taken by an earlier anchor is not
    offered to a later one;
  * long enough first **among what survived the floor**, at the block length
    this script implies (below); a shot shorter than the block still takes it
    and has its frame held (`hold_frame()`, `held_frame: true`), down to the
    resolver's own `MIN_CUT_SECONDS` of clip.

What CF-0291 changed, and why it was wrong before
-------------------------------------------------
This gate knew the block length and nothing about the score; the coverage gate
knew the score and nothing about the block. Neither knew both, so
`2026-09-18T2232Z`/delver passed both with 10/10 covered and two blocks that
played Tom Carver in an interview chair under a phrase about a rotunda podium
and one about a wheelchair on a film set - this very replay predicted those
two picks (`fkuxNGbx1qk:18` at 0.200, `:54` at 0.2046, both `long_enough`) and
called them a second source. Both are under the similarity floor and neither is in
the pool any more. The same anchors now resolve to the trailer's own frames -
`wIM1PDRvKSE:25`, 0.3431, 0.985 s, held - which is also a different answer to
this gate's own question.

The block length, from the script's own numbers
-----------------------------------------------
`need` is not knowable exactly before TTS - there is no alignment - but the
mean block is, and out of numbers the script already carries:

    speech seconds / block_count

with the speech seconds the cadence gate's own (`check_anchor_cadence.py`:
the counted sections' words divided by this script's own words-per-second,
CF-0279) and `block_count` the value the rotation drew into
`pattern.parameters.block_count`. Delver: 193 words / 3.88 wps = 49.7 s over 7
blocks = 7.1 s a block, against real blocks of 4.81 - 10.44 s. At 7.1 s the
replay gives one source, which is what happened.

A pattern that orders no count carries no such number: `explainer`'s block
envelope is observed rather than drawn, and since CF-0310 it is not even
stated as a count (`block_rate_per_minute`, a pace - and a pace is not a
number of blocks until a length is chosen). The order's `block_count` is
`null` there, which is the only thing read here, so nothing about that move
changes this reading. Then the bar is the **bottom** of that pattern's
`key_frame_hold_seconds` band - the shortest block the pattern will draw -
because the generous reading is the right one to refuse on: a source whose
shots cannot fill even the shortest block of its pattern is a source the
resolve will never reach for.

What counts as a source
-----------------------
The Video Editor's unit, not `video_id`: the canonical source after CF-0080's
alias table is collapsed (`01b-footage-index.json` -> `aliases[]`), which is
what `agents/video-editor/scripts/source_gate.py` counts and therefore the
only count worth checking against. Three uploads of one trailer are one
trailer. The floor is the gate's own `REQUIRED_SOURCES` = 2.

A `weak` anchor is not a second source, and since CF-0290 it is not a picture
either: the preflight calls an anchor `weak` when everything ranked for it is
under the floor, the resolver screens exactly those candidates out, and the
block the anchor drives ends with nothing. The replay therefore gives it no
pick at all, it is counted towards no source, and the empty block it leaves is
`check_block_capacity.py`'s to refuse. The rule this paragraph used to state -
"the resolve cuts it anyway, so follow the sample but do not count it" - was
true of CF-0088's resolver and is the behaviour DoD ролика item 3 forbids.

The ladder
----------
The cadence gate's, for the third time (CF-0233, CF-0274):

  * two canonical sources or more carry the covered anchors - pass;
  * one source carries them all, and the unused source did put at least one
    usable sample in front of some anchor - **rewrite**, once. The writer is
    told which source is unused and what its best on-topic shots show, and the
    rule to write against is in SKILL.md: at least one beat only that source
    can picture. On a pattern with long blocks that is the only move that
    works - a phrase the long-take source can also answer will lose the sort
    again;
  * the unused source put nothing usable in front of any anchor, or the pool
    holds fewer than two canonical sources at all, or the one rewrite is
    already spent - **refuse**. The topic leaves the batch as
    `no_second_source` (the funnel's own code for this loss, CF-0232) and no
    further model call is spent on it.

Our own recording (CF-0567)
---------------------------
`own_capture-<id>` (`own_capture:<id>` in the Trend Hunter's candidates) is the
factory's own screen recording of a public page - ExampleTech's «demo»
footage (the root's `docs/tech-footage.md`). The Video Editor's
`source_gate.py` reads the two-source rule as a rule about *borrowed* footage
and this replay reads it the same way:

  * a recording is never one of the two sources - it is not somebody's
    upload; the borrowed sources are counted without it;
  * a script whose recordings carry at least as many anchors as all its
    borrowed sources together passes (every block of the replay is the same
    `need` seconds long, so anchors stand for the Editor's
    `own_capture_seconds >= borrowed_seconds`), and so does a pool of nothing
    but one recording - a video that is entirely ours;
  * below that the borrowed sources are counted as always, the early
    "fewer than two sources in the pool" refusal does not fire (the recording
    can always be aimed at), and the one rewrite is aimed at the recording.

A pool with no `own_capture` id - every ExampleFilm and ExampleScience topic -
is judged exactly as before.

Our own graphics (CF-0689)
--------------------------
A `visual_anchors[]` entry with `graphic_id` places a graphic the factory
draws from the script's facts (`shared/own_graphic.py`) - on a channel whose
footage-origin has the `own_graphic` origin (ExampleTech). It is ours in the
same sense as a recording, and the Editor's `source_gate.py` counts its
seconds beside `own_capture_seconds`: so here a graphic anchor is never a
source and counts with the recording's anchors against the borrowed ones. A
script of nothing but graphics is entirely ours and passes without a pool or a
coverage report (the coverage gate asks the pool nothing for it); the
coverage report of a mixed script is about its pool anchors only, and is
checked against them.

Where the answers come from
---------------------------
Nowhere new. This gate runs **no** preflight of its own: it reads the reports
`check_anchor_coverage.py --out` already wrote for this batch, which are the
Video Editor's own `anchor_coverage.py` output, on the Video Editor's venv,
over the topic's own pool (CF-0274). A second CLIP load per script to ask a
question the first one already answered is the thing this file exists not to
do. The reports are checked against the batch phrase by phrase before anything
is judged: a report written for other anchors is stale and answers nothing.

Usage:

    python3 scripts/check_anchor_coverage.py <03-content-researcher.json> \
        --out <reports.json>
    python3 scripts/check_two_sources.py <03-content-researcher.json> \
        --reports <reports.json> [--write] [--root <checkout>]

**CF-0330 (the user, 2026-09-23): the channel's mode decides.** The Video
Editor's `two_source_gate` has two modes, and the channel picks one
(`channels/<channel>.json` -> `video_editor.two_source_gate`). This preflight
now reads the same switch: in `enforce` it keeps the ladder above (rewrite,
then `no_second_source` into `skipped[]`); in `measure` - the Editor's own
default, and the user's decision of 2026-09-23 - every such answer is a
`warnings[]` entry with the same code and the numbers (anchors per source,
indexed and unused sources, `would_have`), the script stays and the exit is 0.
`--gate-mode` overrides the channel for one run.

Exit codes:

    0  every script's anchors carry at least two canonical sources, or the
       gate is in `measure` and the shortfall is a warning (CF-0330)
    1  at least one script is rewritten towards its unused source
    3  cannot answer: no reports, reports for other anchors, no footage index,
       no block length, or an Editor checkout whose resolver does not screen
       its own pool (CF-0290). Nothing about the scripts is claimed.
    4  at least one topic is refused as `no_second_source` and (with `--write`)
       recorded in `skipped[]`; there is nothing to rewrite.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402
from _channel_ids import resolve_channel  # noqa: E402
import _gate_warning as gw  # noqa: E402
import _own_graphic as ogl  # noqa: E402 - CF-0689

from check_narration_budget import find_root, validator  # noqa: E402
from check_anchor_coverage import (  # noqa: E402
    FALLBACK_SECTIONS, FIELD, FOOTAGE_INDEX_NAME, FUNNEL_STAGE, RHYTHM_REL, CannotAnswer,
    counted_sections, defines, in_script_space, load_footage_index, matcher_knobs,
    module_constants, resolver_file, topic_pool)
from check_anchor_cadence import narration_words, speech_rate  # noqa: E402

# The Video Editor's floor, named where it is checked. Not a knob: it is
# `source_gate.REQUIRED_SOURCES`, and the reason it is two is YouTube's rule
# and not a preference of this pipeline (CF-0118).
REQUIRED_SOURCES = 2

# CF-0232's vocabulary. `no_second_source` is the code the funnel already
# carries for exactly this loss - the Editor's gate writes it after the
# render, the Footage Indexer writes it when a topic never got two sources,
# and this gate writes it before the TTS, which is the only one of the three
# that costs nothing.
SKIP_REASON_CODE = "no_second_source"
RECORD_KEY = "two_source_spread"

# One rewrite, then the topic - the ladder of `check_anchor_cadence.py` and
# `check_anchor_coverage.py`. The count lives on the script, because each run
# of this gate is a new process.
REWRITES_ALLOWED = 1

ACTION_PASS, ACTION_REWRITE, ACTION_REFUSE = "pass", "rewrite", "refuse"

# CF-0330: the gate's mode is the channel's, the Video Editor's own switch
# (`channels/<channel>.json` -> `video_editor.two_source_gate`, read the way
# `source_gate.mode_from_channel()` reads it). `measure` - the Editor's default
# - records and never rejects, so this preflight warns; `enforce` rejects, so
# this preflight keeps its ladder. The user returned the gate to a warning on
# 2026-09-23 through that switch; this file never overrides a channel.
MODE_MEASURE, MODE_ENFORCE = "measure", "enforce"
MODES = (MODE_MEASURE, MODE_ENFORCE)
DEFAULT_MODE = MODE_MEASURE

# Why a block ends with no picture, in the three words the remedies differ by.
# `check_block_capacity.py` says the same three things about the same blocks
# (its `WHY_*`), and this is the anchor-level half of them.
UNDER_FLOOR = "nothing_over_the_similarity_floor"
NO_FRAME = "no_usable_frame"
ALL_SPENT = "every_frame_already_used"
TOO_SHORT = "every_frame_too_short_to_cut"
VERDICT_COVERED, VERDICT_WEAK, VERDICT_ABSENT = "covered", "weak", "absent"

EXIT_OK, EXIT_REWRITE, EXIT_CANNOT_ANSWER, EXIT_REFUSED = 0, 1, 3, 4

ALIASES_KEY = "aliases"
HOLD_KEY = "key_frame_hold_seconds"
REPORT_KIND = "anchor_coverage_preflight"

# How many of an unused source's shots a refusal or a rewrite prints. A
# rewrite the writer cannot aim is the blind cycle CF-0140 removed.
EVIDENCE_SHOWN = 8

# CF-0291: the Editor's side of the replay, by name. `screen_pool` is the
# function whose existence makes the preflight's `samples` mean "the pool a
# block may draw on" (CF-0290); `MIN_CUT_SECONDS` is the shortest cut the
# resolver will make and `HELD_FRAME_SLACK_SECONDS` the slack under which a
# clip is held as a frame instead of played. All three are read out of the
# Editor's own source - there is no copy of any of them here.
SCREEN_FUNCTION = "screen_pool"
MIN_CUT_NAME = "MIN_CUT_SECONDS"
HELD_SLACK_NAME = "HELD_FRAME_SLACK_SECONDS"


class CannotJudge(CannotAnswer):
    """The environment could not be asked. Never a verdict on a script."""


# --------------------------------------------------------------------------
# what counts as one source (CF-0080, the Editor's own collapse)
# --------------------------------------------------------------------------

def alias_map(index_data):
    """`{alias id: canonical id}` out of the batch's `01b-footage-index.json`.

    The flat `aliases: [{video_id, alias_of, ...}]` list CF-0080's
    `ingest_batch.py` writes, which is the first of the three shapes
    `source_gate.load_aliases()` reads - the one a batch of this pipeline
    always has, since it is the file this gate is already reading for the
    pool. Chains are followed (`c -> b -> a` collapses to `a`) and a cycle is
    left alone rather than looped on.
    """
    direct = {}
    for rec in index_data.get(ALIASES_KEY) or []:
        if not isinstance(rec, dict):
            continue
        vid, canon = rec.get("video_id"), rec.get("alias_of")
        if isinstance(vid, str) and isinstance(canon, str) and vid and canon and vid != canon:
            direct[vid] = canon
    out = {}
    for vid in direct:
        seen, canon = {vid}, direct[vid]
        while canon in direct and canon not in seen:
            seen.add(canon)
            canon = direct[canon]
        out[vid] = canon
    return out


OWN_CAPTURE_HEADS = ("own_capture-", "own_capture:")


def is_own_capture(video_id):
    """CF-0567: a source id of the factory's own screen recording -
    `own_capture-<id>` (Footage Indexer's file id, shot keys) or
    `own_capture:<id>` (the Trend Hunter's candidate name). The Video
    Editor's `_clip_names.is_own_capture`, by the id alone."""
    return isinstance(video_id, str) and video_id.startswith(OWN_CAPTURE_HEADS)


def canonical(video_id, aliases):
    """The canonical id `video_id` collapses to (itself when it is one)."""
    return aliases.get(video_id, video_id)


def sample_source(sample, aliases):
    """The canonical source of a `<video_id>:<shot>` sample name."""
    return canonical(str(sample).split(":")[0], aliases)


# --------------------------------------------------------------------------
# what the pool's shots are, in seconds
# --------------------------------------------------------------------------

_SPANS_CACHE = {}


def shot_spans(indexes):
    """`<video_id>:<n>` -> `{seconds, description, is_card}` for every shot of
    every index of this topic's pool.

    `seconds` is `end - start`, the shot's whole length. The resolve compares
    the block's need against `available_seconds()` - what is left of the shot
    *after* the cut point - which is this number or less, so reading the whole
    shot is the generous direction, and the generous direction is the right
    one for a gate that refuses.
    """
    out = {}
    for index in indexes:
        data = _SPANS_CACHE.get(index)
        if data is None:
            try:
                raw = json.loads(Path(index).read_text())
            except (OSError, ValueError):
                continue
            data = {"source": raw.get("source"),
                    "shots": [{k: s.get(k) for k in
                               ("index", "start", "end", "description", "is_card")}
                              for s in raw.get("shots", [])]}
            _SPANS_CACHE[index] = data
        stem = Path(str(data.get("source") or index)).stem
        for shot in data["shots"]:
            start, end = shot.get("start"), shot.get("end")
            seconds = (float(end) - float(start)
                       if isinstance(start, (int, float)) and isinstance(end, (int, float))
                       else 0.0)
            out[f"{stem}:{shot['index']}"] = {
                "seconds": round(max(seconds, 0.0), 3),
                "description": (shot.get("description") or "").strip(),
                "is_card": bool(shot.get("is_card")),
            }
    return out


# --------------------------------------------------------------------------
# how long a block is, before there is a block
# --------------------------------------------------------------------------

def hold_floor(pattern_id, root=None):
    """`(seconds, source)` - the BOTTOM of a pattern's `key_frame_hold_seconds`.

    The cadence gate reads the top of the same band for the opposite question
    (the longest a frame may be left alone); this reads the bottom, and both
    read it out of `patterns/<pattern_id>.json` through the root's own
    `validate_patterns.load_patterns()`, so neither carries a copy of a number
    the pattern set owns.
    """
    vp = validator(root)
    if vp is None or not hasattr(vp, "load_patterns"):
        raise CannotJudge(
            f"no reachable patterns/validate_patterns.py under {Path(root or find_root())} - "
            f"the hold band of a pattern is only written down there, and this gate carries "
            f"no copy of it")
    try:
        patterns = vp.load_patterns()
    except Exception as exc:  # noqa: BLE001 - an unreadable pattern set is not a verdict
        raise CannotJudge(f"patterns/ would not load: {exc}")
    pattern = patterns.get(pattern_id)
    if pattern is None:
        raise CannotJudge(
            f"no pattern {pattern_id!r} in {sorted(patterns)} - a script drawn on a pattern "
            f"this checkout does not have cannot be held to its hold band")
    band = ((pattern.get("parameters") or {}).get(HOLD_KEY)) or {}
    floor = band.get("min")
    if not isinstance(floor, (int, float)) or isinstance(floor, bool) or floor <= 0:
        raise CannotJudge(
            f"patterns/{pattern_id}.json#parameters.{HOLD_KEY}.min is {floor!r} - without the "
            f"bottom of the hold band an emergent block count gives no block length")
    return float(floor), f"patterns/{pattern_id}.json#parameters.{HOLD_KEY}.min"


def block_seconds(script, channel, sections, root=None):
    """`(seconds, source)` - how long one block of this script holds.

    The mean block, `speech seconds / block_count`, both out of the script:
    the words of the counted sections over this script's own words-per-second
    (CF-0279, `check_anchor_cadence.speech_rate()`), and the `block_count` the
    rotation drew. That is the number the resolve's long-enough-first sort is
    run against, give or take the alignment - on Delver 7.11 s against real
    blocks of 4.81 to 10.44 s.

    A pattern that orders no block count leaves `null` here - `explainer`'s
    block envelope is observed, and since CF-0310 it is stated as a pace
    (`block_rate_per_minute`) rather than as a count. Either way this reads the
    ORDER's number, which is the rotation's draw and not the pattern's band, so
    the shape of the band does not reach this file. With no number, the bottom
    of the pattern's `key_frame_hold_seconds` band answers: the shortest block
    the pattern will draw, which is the reading most generous to the source
    being judged.
    """
    pattern = script.get("pattern") or {}
    params = pattern.get("parameters") or {}
    blocks = params.get("block_count")
    if isinstance(blocks, int) and not isinstance(blocks, bool) and blocks > 0:
        rate, rate_source = speech_rate(script, channel, root)
        _texts, _offsets, words = narration_words(script, sections)
        if words <= 0:
            raise CannotJudge(
                f"{script.get('script_id')}: the counted sections hold no words - there is no "
                f"speech to divide into blocks and no block length to judge a shot against")
        seconds = (words / rate) / blocks
        return round(seconds, 3), (f"{words} word(s) / {rate} wps / block_count {blocks} "
                                   f"({rate_source})")
    pattern_id = pattern.get("pattern_id")
    if not isinstance(pattern_id, str) or not pattern_id:
        raise CannotJudge(
            f"{script.get('script_id')}: no `pattern.parameters.block_count` and no "
            f"`pattern.pattern_id` - nothing says how long a block of this script holds, and "
            f"without that the resolve's choice between a long take and a one-second cut "
            f"cannot be replayed")
    return hold_floor(pattern_id, root)


# --------------------------------------------------------------------------
# CF-0291: the floors, and the proof that the report in hand was screened by them
# --------------------------------------------------------------------------

def editor_floors(report, root=None, resolver=None):
    """The numbers this replay has to run at, every one of them the Editor's.

    Until CF-0290 this repository had two checks with half an answer each. The
    coverage gate knew the similarity score and nothing about block length; the
    replays here knew the block length and nothing about the score, so the
    long-enough-first sort handed a block the longest shot in the pool whatever
    it depicted. `example-film/2026-09-18T2232Z`/delver is what that passed:
    10/10 covered at best scores of 0.3135 and 0.3431, and the two blocks went
    to `fkuxNGbx1qk:18` (0.200) and `:54` (0.2046) because they were eight and
    twenty seconds long.

    So the replay now runs on both halves, and takes both from the Editor:

      * `min_score` is the report's own field, cross-read against
        `resolve_anchors.DEFAULT_MIN_SCORE` - the same comparison
        `check_anchor_coverage.run_preflight()` makes when the report is
        written, made again here because the report may have been written by
        an earlier run of the stage;
      * `score_floor` is the report's own field too - the run's stricter
        floor, unset in production and set per run when a run wants one;
      * `MIN_CUT_SECONDS` and `HELD_FRAME_SLACK_SECONDS` are read out of
        `resolve_anchors.py` and `rhythm.py` - the shortest cut the resolver
        makes, and the slack under which it holds a frame rather than playing
        one.

    And it refuses to run at all against an Editor that does not screen its
    own pool. `samples` is only "the pool a block may draw on" because
    `screen_pool()` takes the under-floor candidates out of it before anything
    is ordered; replaying an older report's `samples` would put an under-floor
    frame on a block again, which is the whole of this task.

    Raises `CannotJudge`, never a verdict on a script.
    """
    path = resolver_file(root, resolver)
    if not defines(path, SCREEN_FUNCTION):
        raise CannotJudge(
            f"{path} has no {SCREEN_FUNCTION}() - this Editor checkout still offers a block "
            f"candidates under its own similarity floor (before CF-0290), so the preflight's "
            f"`samples` are not the pool a block may draw on and replaying them would predict "
            f"the picture this gate exists to refuse")
    knobs = matcher_knobs(path)
    min_score = report.get("min_score")
    if not isinstance(min_score, (int, float)) or isinstance(min_score, bool):
        raise CannotJudge(
            f"the preflight report carries no `min_score` ({min_score!r}) - without the floor "
            f"it was screened at, its `samples` cannot be told from a list of whatever the "
            f"matcher ranked")
    if min_score != knobs["min_score"]:
        raise CannotJudge(
            f"the report was screened at min_score={min_score} while "
            f"resolve_anchors.DEFAULT_MIN_SCORE is {knobs['min_score']} - the report and the "
            f"resolve are screening different pools and no replay of one predicts the other")
    score_floor = report.get("score_floor")
    if score_floor is not None and (not isinstance(score_floor, (int, float))
                                    or isinstance(score_floor, bool)):
        raise CannotJudge(f"the report's `score_floor` is {score_floor!r}, neither a number "
                          f"nor unset")
    cuts = module_constants(path, (MIN_CUT_NAME,))
    if MIN_CUT_NAME not in cuts:
        raise CannotJudge(f"{path}: {MIN_CUT_NAME} not found - without the shortest cut the "
                          f"resolver makes, a short relevant shot cannot be told from one it "
                          f"would refuse outright")
    rhythm = Path(path).parent.parent / RHYTHM_REL
    slack = module_constants(rhythm, (HELD_SLACK_NAME,)) if rhythm.exists() else {}
    if HELD_SLACK_NAME not in slack:
        raise CannotJudge(f"{rhythm}: {HELD_SLACK_NAME} not found - without it a block filled "
                          f"by holding a short shot's frame cannot be told from one the shot "
                          f"plays out")
    return {
        "min_score": float(min_score),
        "score_floor": None if score_floor is None else float(score_floor),
        "min_cut_seconds": float(cuts[MIN_CUT_NAME]),
        "held_frame_slack_seconds": float(slack[HELD_SLACK_NAME]),
        "resolver": str(path),
    }


def screened_samples(rec, floors):
    """The candidates of one anchor a block may draw on, under both floors.

    Against a CF-0290 preflight this is `samples` unchanged: the Editor
    screened them there, with `screen_pool()`, and the under-floor ones are in
    `refusals[]` by name and score instead. The screen is repeated here for
    the two cases where that is not enough - a report whose `refusals[]` and
    `samples` disagree, and a report that states its samples' scores
    (`sample_scores`, which the Editor does not write today) - so that a
    sample this gate offers a block is one it can say cleared the floor rather
    than one it assumed did.
    """
    floor, hard = floors["min_score"], floors["score_floor"]
    scores = rec.get("sample_scores")
    scores = scores if isinstance(scores, dict) else {}
    refused = {r.get("shot") for r in (rec.get("refusals") or []) if isinstance(r, dict)}
    out = []
    for sample in rec.get("samples") or []:
        if sample in refused:
            continue
        score = scores.get(sample)
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            if score < floor or (hard is not None and score < hard):
                continue
        out.append(sample)
    return out


def under_floor(rec, floors):
    """How many of this anchor's candidates the floor refused.

    Not `samples` minus the screened list - against a CF-0290 preflight those
    are the same list, because the Editor screened the pool where it belongs,
    before the report was written. The under-floor candidates are in
    `refusals[]` instead, each with the score it was refused at, and a score
    under the floor is the floor's refusal by construction: `screen_pool()`
    runs before the pre-cut gate, so nothing under the floor ever reaches
    another refusal to be recorded under.
    """
    floor = floors["min_score"]
    return sum(1 for r in (rec.get("refusals") or [])
               if isinstance(r, dict) and isinstance(r.get("score"), (int, float))
               and not isinstance(r.get("score"), bool) and r["score"] < floor)


def sample_score(rec, sample, samples, spans):
    """`(score, where it came from)` for the shot a block gets.

    The preflight states one score per anchor - `best_score`, the best of the
    survivors - and not one per sample, so this says what it can say and never
    guesses. The best is attributable when the sample in hand is the first of
    the anchor's pool and that pool leads with a photographic shot: the
    Editor's `order_candidates()` puts the promoted title/end cards in front
    and everything else in score order, so a pool whose first sample is not a
    card is in score order outright and its head is the best.

    A later sample - one an earlier anchor's claim on the head pushed the
    block onto (CF-0121) - has a score the report does not carry. It is then
    `None`, beside the floor it is known to clear, rather than a number this
    file made up. `sample_scores` is read first for the day the Editor writes
    it, after which every block here carries an exact one.
    """
    scores = rec.get("sample_scores")
    if isinstance(scores, dict) and isinstance(scores.get(sample), (int, float)):
        return scores[sample], "preflight sample score"
    best = rec.get("best_score")
    if (samples and sample == samples[0] and isinstance(best, (int, float))
            and not (spans.get(samples[0]) or {}).get("is_card")):
        return best, "preflight best_score"
    return None, "unstated"


# --------------------------------------------------------------------------
# the replay
# --------------------------------------------------------------------------

def resolve_picks(report, spans, need, floors):
    """Which sample the resolve would take for each anchor, in order.

    `resolve_anchors.py`, at the one place a block may hold a single shot, as
    CF-0290 left it:

      1. the anchor's pool is what cleared both floors - `screen_pool()` first,
         everything else after. A candidate under the similarity floor is not
         at the back of the queue, it is **not in the queue**;
      2. inside that pool the still-unused candidates long enough for the block
         keep their order and go in front of the ones that are not
         (`available_seconds(c) < need` as a stable sort key);
      3. a candidate the block would have to cut to less than `MIN_CUT_SECONDS`
         is skipped ("too short to read"), not stopped on;
      4. the first survivor fills the block. When it is shorter than the block
         by more than `HELD_FRAME_SLACK_SECONDS` the Editor holds its frame
         (`hold_frame()` -> a `still` block, `held_frame: true`) - the block is
         filled, by a frame of the shot the phrase asked for;
      5. one sample, one use (CF-0121), so a sample an earlier anchor took is
         gone.

    An anchor whose screened pool is empty gets **no pick**. That is the
    change this task is: before it, such an anchor took the longest thing the
    matcher had ranked and the block played a frame of something else. The
    block that anchor drives is empty, and it is `check_block_capacity.py`
    that counts it and sends the script back - the same answer the Editor's
    own `unresolved_anchor` gate now gives after the render, two stages
    earlier and for free.

    Returns one record per anchor: `{anchor_index, phrase, verdict, pick,
    seconds, long_enough, held_frame, score, score_source, offered,
    under_floor}`, `pick` None for an anchor the pool cannot picture.
    """
    min_cut = floors["min_cut_seconds"]
    slack = floors["held_frame_slack_seconds"]
    taken, out = set(), []

    def seconds_of(sample):
        return (spans.get(sample) or {}).get("seconds") or 0.0

    for rec in report.get("anchors") or []:
        screened = screened_samples(rec, floors)
        free = [s for s in screened if s not in taken]
        long = [s for s in free if seconds_of(s) >= need]
        short = [s for s in free if seconds_of(s) < need]
        pick = None
        for sample in long + short:
            if min(need, seconds_of(sample)) < min_cut:
                continue  # "would cut to Ns - too short to read"
            pick = sample
            break
        if pick:
            taken.add(pick)
        # Why there is no picture, told apart because the remedies are three
        # different things: rewrite the anchor, write fewer anchors onto the
        # same frames, or buy footage that is not a fraction of a second long.
        best_offered = rec.get("best_offered_score")
        why = (None if pick else
               # Which of the two "the pool has nothing" answers it is comes
               # from the preflight's own word: `weak` is the anchor whose
               # whole ranked pool is under the floor (CF-0290), `absent` the
               # one whose frames exist and cannot be cut. Different remedies,
               # so never folded together.
               (UNDER_FLOOR if (rec.get("verdict") == VERDICT_WEAK
                                or (isinstance(best_offered, (int, float))
                                    and not isinstance(best_offered, bool)
                                    and best_offered < floors["min_score"]))
                else NO_FRAME) if not screened else
               ALL_SPENT if not free else
               TOO_SHORT)
        score, score_source = ((None, "no pick") if not pick
                               else sample_score(rec, pick, screened, spans))
        out.append({
            "anchor_index": rec.get("anchor_index"),
            "phrase": rec.get("phrase"),
            "verdict": rec.get("verdict"),
            "pick": pick,
            "seconds": seconds_of(pick) if pick else None,
            "long_enough": bool(pick) and seconds_of(pick) >= need,
            # The block is filled either way; this says by a shot that plays
            # or by a frame of one that does not last the block.
            "held_frame": bool(pick) and seconds_of(pick) + slack < need,
            "score": score,
            "score_source": score_source,
            "offered": len(screened),
            "free": len(free),
            "under_floor": under_floor(rec, floors),
            "why": why,
        })
    return out


def spread(picks, aliases):
    """`(counted, all_picks)` - canonical source -> the anchors it would carry.

    `counted` holds only the anchors whose verdict is `covered`: a `weak`
    anchor's picture is cut and is on screen, so the replay spends its sample
    in `all_picks`, but a frame the Editor's own gate says is not about this
    moment is not a second source (CF-0088, and the module docstring).
    """
    counted, every = {}, {}
    for rec in picks:
        if not rec["pick"]:
            continue
        source = sample_source(rec["pick"], aliases)
        every.setdefault(source, []).append(rec["anchor_index"])
        if rec["verdict"] == VERDICT_COVERED:
            counted.setdefault(source, []).append(rec["anchor_index"])
    return counted, every


def evidence(report, spans, source, aliases, need, limit=EVIDENCE_SHOWN):
    """The unused source's best on-topic shots, in the writer's own terms.

    Every distinct sample of that source the Editor's gate passed for some
    anchor of this script, best-offered first, with the shot's description and
    its length beside it - the length because on a long-block pattern it is
    exactly what lost, and a writer aiming a rewrite has to see that a
    one-second cut only ever wins an anchor nothing else answers.
    """
    out, seen = [], set()
    for rec in report.get("anchors") or []:
        for sample in rec.get("samples") or []:
            if sample in seen or sample_source(sample, aliases) != source:
                continue
            seen.add(sample)
            shot = spans.get(sample) or {}
            out.append({"sample": sample,
                        "seconds": shot.get("seconds"),
                        "long_enough": (shot.get("seconds") or 0.0) >= need,
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
    """Two-source failures already recorded on this script. A record with no
    count is one failure, not zero: it only exists because a run wrote it."""
    record = script.get(RECORD_KEY)
    if not isinstance(record, dict):
        return 0
    n = record.get("failed_attempts")
    if isinstance(n, int) and not isinstance(n, bool) and n >= 0:
        return n
    return 0 if record.get("action") == ACTION_PASS else 1


def judge(script, report, pool, aliases, spans, need, need_source, floors, graphic_anchors=0):
    """One script's record - the ladder of the module docstring.
    `graphic_anchors` (CF-0689): how many of the script's anchors place one of
    its own graphics - ours, counted with the recording, never a source."""
    pool_sources = []
    for video_id in pool["video_ids"]:
        canon = canonical(video_id, aliases)
        if canon not in pool_sources:
            pool_sources.append(canon)
    missing = {u["video_id"] for u in pool["unindexed"]}
    indexed = []
    for video_id in pool["video_ids"]:
        canon = canonical(video_id, aliases)
        if video_id not in missing and canon not in indexed:
            indexed.append(canon)

    picks = resolve_picks(report, spans, need, floors)
    counted, every = spread(picks, aliases)
    carried = sorted(counted)
    unused = [s for s in indexed if s not in counted]
    # CF-0567: our own recordings are not borrowed sources (module docstring).
    own = [s for s in indexed if is_own_capture(s)]
    borrowed_carried = [s for s in carried if not is_own_capture(s)]
    record = {
        "topic_id": script.get("topic_id"),
        "anchors": report.get("anchor_count"),
        "block_seconds": need,
        "block_seconds_source": need_source,
        "required_sources": REQUIRED_SOURCES,
        "canonical_sources": pool_sources,
        "indexed_sources": indexed,
        # Scope item 1's report, and what `--write` leaves on the script:
        # anchors per source, counted and as the replay ran.
        "anchors_by_source": {s: sorted(v) for s, v in counted.items()},
        "picks_by_source": {s: sorted(v) for s, v in every.items()},
        "picks": picks,
        # CF-0291: the numbers the replay ran at, so a record can be read
        # years later without the reader having to guess which floors were in
        # force. Every one of them is the Editor's (`editor_floors()`).
        "floors": {k: floors[k] for k in ("min_score", "score_floor", "min_cut_seconds",
                                          "held_frame_slack_seconds")},
        # The anchors the screened pool cannot picture at all. They carry no
        # source here; `check_block_capacity.py` is what refuses the script
        # over the empty blocks they leave.
        "unpicturable": [r["anchor_index"] for r in picks if not r["pick"]],
        "unused_sources": unused,
        "rewrites_allowed": REWRITES_ALLOWED,
    }
    failed_before = previous_failures(script)
    if graphic_anchors:
        record["own_graphic_anchors"] = graphic_anchors
    if own or graphic_anchors:
        own_on = sum(len(v) for s, v in every.items() if is_own_capture(s))
        borrowed_on = sum(len(v) for s, v in every.items() if not is_own_capture(s))
        record.update(own_capture_sources=own, own_capture_anchors=own_on,
                      borrowed_anchors=borrowed_on)
        if own_on + graphic_anchors >= borrowed_on:
            ours = []
            if own:
                ours.append(f"our own recording ({', '.join(own)}) under {own_on} anchor(s)")
            if graphic_anchors:
                ours.append(f"our own graphics under {graphic_anchors} anchor(s) (CF-0689)")
            record.update(action=ACTION_PASS, failed_attempts=failed_before, evidence=[])
            record["reason"] = (
                f"{' and '.join(ours)} on screen against {borrowed_on} of borrowed footage - "
                f"a video that is mostly ours is not a compilation of anybody's upload, and "
                f"the Video Editor's two_source_gate passes it (source_gate.py, CF-0567"
                + (" / CF-0689" if graphic_anchors else "")
                + f"); ours is never counted as one of the {REQUIRED_SOURCES} sources")
            return record

    if not own and not graphic_anchors and len(indexed) < REQUIRED_SOURCES:
        collapsed = len(pool["video_ids"]) - len(pool_sources)
        record.update(action=ACTION_REFUSE, failed_attempts=failed_before + 1, evidence=[])
        record["reason"] = (
            f"this topic's pool holds {len(indexed)} canonical source(s) "
            f"({', '.join(indexed) or 'none'}) against the Video Editor's floor of "
            f"{REQUIRED_SOURCES}"
            + (f" - {len(pool['video_ids'])} video id(s) collapse to {len(pool_sources)} "
               f"canonical source(s) through the `{ALIASES_KEY}` table, and a re-upload of a "
               f"cut already in the video is not a second source (CF-0080)"
               if collapsed else "")
            + f": no arrangement of anchors puts a second source on screen, so the topic is "
              f"dropped rather than rewritten. The second source is the Footage Indexer's to "
              f"deliver (CF-0129), not the writer's to phrase around")
        return record

    if len(borrowed_carried) >= REQUIRED_SOURCES:
        record.update(action=ACTION_PASS, failed_attempts=failed_before, evidence=[])
        record["reason"] = (
            f"{len(carried)} canonical source(s) carry the covered anchors at "
            f"{need} s a block ("
            + "; ".join(f"{s}: {len(counted[s])} anchor(s)" for s in carried)
            + f") - at or over the Video Editor's floor of {REQUIRED_SOURCES} "
              f"(video_editor.two_source_gate, CF-0118)")
        return record

    failed = failed_before + 1
    record["failed_attempts"] = failed
    where = (f"every covered anchor of this script resolves from "
             f"{carried[0] if carried else 'no source at all'} at {need} s a block "
             f"({need_source})")

    # CF-0567: with a recording in the pool the rewrite is aimed at it - more
    # of the video in our own footage is the move both gates accept.
    best = own[0] if own else (unused[0] if unused else None)
    record["aimed_at"] = best
    found = evidence(report, spans, best, aliases, need) if best else []
    if not found and graphic_anchors and failed <= REWRITES_ALLOWED:
        # CF-0689: with graphics the move both gates accept is always there -
        # more of the video on our own graphics, drawn from the script's facts.
        record.update(action=ACTION_REWRITE, evidence=[], aimed_at=ogl.KIND)
        record["reason"] = (
            f"{where}; our own graphics carry {graphic_anchors} anchor(s) against "
            f"{record.get('borrowed_anchors')} of borrowed footage. Rewrite the anchors once "
            f"towards the graphics: put more of the facts' numbers, names and dates on "
            f"graphics (each value on its claim and quote, step 5), or aim a beat at a second "
            f"borrowed source")
        return record
    if not found:
        record.update(action=ACTION_REFUSE, evidence=[])
        record["reason"] = (
            f"{where}, and {best} put not one usable frame in front of any of its anchors - "
            f"every candidate it offered was refused by the Editor's own pre-cut gate, or it "
            f"offered none. There is nothing evidenced for a rewrite to aim at, so no model "
            f"call is spent on one and the topic is dropped")
        return record

    record["evidence"] = found
    if failed > REWRITES_ALLOWED:
        record.update(action=ACTION_REFUSE)
        one = carried[0] if carried else "one source"
        record["reason"] = (
            f"{where}. Refused after {failed} attempt(s): the anchors were already rewritten "
            f"once towards {best} and the resolve still takes {one} for every block")
        return record

    record["action"] = ACTION_REWRITE
    long_enough = [e for e in found if e["long_enough"]]
    record["reason"] = (
        f"{where}, so the video is built from one upload and the Video Editor's "
        f"`two_source_gate` refuses it after the TTS (CF-0118, `enforce` since CF-0129). "
        + (f"{best} is our own recording and carries fewer anchors than the borrowed footage "
           f"({record.get('own_capture_anchors')} against {record.get('borrowed_anchors')}). "
           f"Rewrite the anchors once towards it: the beats of what the tool does on screen, "
           f"framed as the recording shows them"
           if own else
           f"{best} is unused. Rewrite the anchors once towards it: at least one beat whose "
           f"frame only {best} can show")
        + (f" - {len(long_enough)} of its usable shots are long enough to fill a {need} s "
           f"block on their own"
           if long_enough else
           # CF-0290 turned this sentence around. A shot too short for the
           # block used to sort behind every long one whatever it depicted, so
           # a short source only ever won an anchor nothing else answered;
           # now the pool is screened by the floor first and a short shot that
           # is the anchor's best surviving candidate takes the block, held as
           # a frame. The aim is still one beat only this source can picture -
           # what changed is that a one-second cut is no longer a losing bet.
           f" - none of its usable shots fills a {need} s block on its own, and since CF-0290 "
           f"that no longer loses: the block goes to the best candidate over the "
           f"{floors['min_score']} floor whatever its length, and a shot shorter than the "
           f"block is held as a frame (`hold_frame()`, down to {floors['min_cut_seconds']} s "
           f"of clip)")
        + f". Aim the beat at a shot this list names, not at a scene you would like it to have")
    return record


def graphics_only_record(script):
    """CF-0689: the record of a script whose every anchor places one of its
    own graphics - entirely ours, the single-source rule does not apply (the
    Editor's source_gate: no borrowed footage at all)."""
    n = len(script.get(FIELD) or [])
    return {
        "topic_id": script.get("topic_id"), "anchors": 0, "own_graphic_anchors": n,
        "block_seconds": None, "block_seconds_source": None,
        "required_sources": REQUIRED_SOURCES, "canonical_sources": [], "indexed_sources": [],
        "anchors_by_source": {}, "picks_by_source": {}, "picks": [], "floors": {},
        "unpicturable": [], "unused_sources": [], "rewrites_allowed": REWRITES_ALLOWED,
        "own_capture_sources": [], "own_capture_anchors": 0, "borrowed_anchors": 0,
        "action": ACTION_PASS, "failed_attempts": previous_failures(script), "evidence": [],
        "gate_mode": None, "warnings": [],
        "reason": (f"every one of the {n} anchor(s) places one of the script's own graphics "
                   f"(CF-0689) - no borrowed footage at all, so the video is entirely ours and "
                   f"the single-source rule does not apply (source_gate.py)"),
    }


def skip_entry(script, record):
    """The `skipped[]` entry a refusal writes - CF-0232's shape, with a
    `reason` written to be read alone: the funnel copies it verbatim."""
    return {
        "topic_id": script.get("topic_id"),
        "reason_code": SKIP_REASON_CODE,
        "reason": f"{script.get('script_id')}: {record['reason']}",
        "stage": FUNNEL_STAGE,
        "canonical_sources": record["canonical_sources"],
        "anchors_by_source": record["anchors_by_source"],
        "block_seconds": record["block_seconds"],
        "required_sources": record["required_sources"],
        "failed_attempts": record["failed_attempts"],
    }


# --------------------------------------------------------------------------
# the reports this gate reads instead of running a preflight of its own
# --------------------------------------------------------------------------

def load_reports(path):
    """`{script_id: report}` out of `check_anchor_coverage.py --out`."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CannotJudge(
            f"no readable coverage reports at {path}: {exc} - this gate runs no preflight of "
            f"its own (a second CLIP load per script to ask what the first one answered); run "
            f"`check_anchor_coverage.py <batch> --out {path}` first")
    reports = data.get("reports") if isinstance(data, dict) else None
    if not isinstance(reports, dict) or not reports:
        raise CannotJudge(
            f"{path}: no `reports` object - that file is written by "
            f"`check_anchor_coverage.py --out` and nothing else is an answer about this pool")
    return reports


def report_for(script, reports):
    """This script's preflight report, checked against the anchors as written.

    Phrase by phrase, in order. A report written before the anchors were
    rewritten answers about frames the script no longer asks for, and a gate
    that judged on it would refuse (or pass) a script nobody wrote.
    """
    sid = script.get("script_id")
    report = reports.get(sid)
    if not isinstance(report, dict):
        raise CannotJudge(
            f"{sid}: no coverage report - run `check_anchor_coverage.py` over this batch with "
            f"`--out` first; every script it judges is in there")
    if report.get("kind") != REPORT_KIND:
        raise CannotJudge(f"{sid}: the report is {report.get('kind')!r}, not {REPORT_KIND!r}")
    anchors = script.get(FIELD)
    if not isinstance(anchors, list) or not anchors:
        raise CannotJudge(
            f"{sid}: no `{FIELD}` - the coverage gate refuses a script written blind before "
            f"this one is reached, so a batch that gets here has the field on every script")
    # CF-0689: the report is about the anchors the pool was asked for - a
    # graphic anchor is never one of them.
    written = [a.get("phrase") if isinstance(a, dict) else None for a in anchors
               if not ogl.is_graphic_anchor(a)]
    judged = [r.get("phrase") for r in report.get("anchors") or []]
    if written != judged:
        raise CannotJudge(
            f"{sid}: the coverage report was written for other anchors "
            f"({len(judged)} phrase(s) against this script's {len(written)}"
            + ("" if len(judged) != len(written) else ", and they differ")
            + f") - it is stale. Run `check_anchor_coverage.py` again with `--out` and nothing "
              f"about this script is claimed on this run")
    # CF-0689: numbered like the script's own anchors, graphic ones named.
    return in_script_space(report, script)


# --------------------------------------------------------------------------
# reporting
# --------------------------------------------------------------------------

def script_lines(script, record):
    """The lines for one judged script."""
    sid = script.get("script_id")
    counted = record["anchors_by_source"]
    spread_line = ", ".join(f"{s}: {len(v)}" for s, v in sorted(counted.items())) or "none"
    head = {ACTION_PASS: "  ok    ", ACTION_REWRITE: "  REWRITE",
            ACTION_REFUSE: "  REFUSE", gw.ACTION_WARN: "  WARN   "}[record["action"]]
    lines = [f"{head} {sid}: anchors per source {{{spread_line}}} over "
             f"{len(record['indexed_sources'])} indexed canonical source(s), "
             f"floor {REQUIRED_SOURCES}"]
    if record["action"] == gw.ACTION_WARN:
        for w in record.get("warnings") or []:
            lines.append(gw.line(w))
    elif record["action"] != ACTION_PASS or record.get("own_capture_sources"):
        # CF-0567: an own-capture pass says why - the floor of 2 printed
        # above does not apply to our own recording.
        lines.append(f"    {record['reason']}")
    lines.append(f"    block {record['block_seconds']} s ({record['block_seconds_source']}); "
                 f"the resolve screens the anchor's pool at min_score "
                 f"{record['floors']['min_score']} first (CF-0290) and only then takes the "
                 f"first still-unused sample that fills the block, holding its frame when it "
                 f"is shorter (CF-0121, resolve_anchors.py)")
    for rec in record["picks"]:
        floored = (f", {rec['under_floor']} more under the floor and never offered"
                   if rec.get("under_floor") else "")
        if not rec["pick"]:
            why = {UNDER_FLOOR: (f"not one of its candidates is over the similarity floor"
                                 f"{floored} - the pool has no picture of this phrase "
                                 f"(CF-0290: the block is not filled below the floor)"),
                   NO_FRAME: (f"the pool holds no usable frame for this anchor at all - its "
                              f"candidates were refused by the Editor's own pre-cut gate, or "
                              f"it had none"),
                   ALL_SPENT: (f"all {rec['offered']} of its frames over the floor are already "
                               f"on screen elsewhere in this video (one sample, one use, "
                               f"CF-0121)"),
                   TOO_SHORT: (f"every one of its {rec['free']} free frame(s) would cut to "
                               f"under {record['floors']['min_cut_seconds']} s - too short to "
                               f"read")}.get(rec["why"], "no picture")
            lines.append(f"      [{rec['verdict']}] anchor #{rec['anchor_index']} - {why}; the "
                         f"block this anchor drives ends EMPTY")
            continue
        mark = ("  <- too short for the block; its frame is held (CF-0290)"
                if rec["held_frame"] else "")
        score = (f"score {rec['score']}" if rec["score"] is not None
                 else f"score >= {record['floors']['min_score']} ({rec['score_source']})")
        note = "" if rec["verdict"] == VERDICT_COVERED else f"  ({rec['verdict']}, not counted)"
        lines.append(f"      [{rec['verdict']}] anchor #{rec['anchor_index']} -> {rec['pick']} "
                     f"({rec['seconds']} s, {score}, of {rec['offered']} sample(s) over the "
                     f"floor{floored}){note}{mark}")
    for source in record["unused_sources"]:
        lines.append(f"    unused: {source}")
    if record.get("evidence"):
        lines.append(f"    what {record.get('aimed_at') or record['unused_sources'][0]} can show "
                     f"(the Editor's gate "
                     f"passed these for this script's own anchors):")
        for e in record["evidence"]:
            lines.append(f"      {e['sample']} ({e['seconds']} s"
                         + (", fills a block" if e["long_enough"]
                            else ", shorter than a block - held as a frame")
                         + (", card" if e["is_card"] else "") + "): "
                         + (e["description"] or "(no description in the index - read the "
                                                "contact sheet)"))
    return lines


# --------------------------------------------------------------------------
# the batch
# --------------------------------------------------------------------------

def mode_from_config(channel_cfg, default=DEFAULT_MODE):
    """`video_editor.two_source_gate` of a loaded channel config: the string,
    or `mode` of a block. An unknown value is the default, as in the Editor's
    `source_gate.mode_from_channel()` - a typo must neither switch the gate
    off nor turn every topic into a refusal."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    node = ve.get("two_source_gate")
    if isinstance(node, dict):
        node = node.get("mode")
    if isinstance(node, str) and node.strip().lower() in MODES:
        return node.strip().lower()
    return default


def gate_mode(channel, root=None):
    """The channel's mode for this gate. No readable channel config is the
    Editor's default (`measure`) - the same answer the Editor would act on."""
    if not channel:
        return DEFAULT_MODE
    try:
        cfg = json.loads(((root or find_root()) / "channels" / f"{channel}.json").read_text())
    except (OSError, ValueError):
        return DEFAULT_MODE
    return mode_from_config(cfg)


def finding(record):
    """CF-0330: the measurement alone, for a warning - no rewrite in it."""
    counted = record["anchors_by_source"]
    spread_line = "; ".join(f"{s}: {len(v)} anchor(s)" for s, v in sorted(counted.items()))
    return (f"{len(counted)} canonical source(s) carry the covered anchors at "
            f"{record['block_seconds']} s a block ({spread_line or 'none'}) against the Video "
            f"Editor's floor of {record['required_sources']}; "
            f"{len(record['indexed_sources'])} indexed canonical source(s)"
            + (f", unused: {', '.join(record['unused_sources'])}"
               if record["unused_sources"] else ""))


def check_batch(batch_file, reports_file, root=None, footage_index=None, script_id=None,
                out=print, write=False, resolver=None, mode=None):
    """Judge every script of the batch. Returns `(problems, records, refused)`.

    `problems` are the scripts to rewrite. A refusal is not a problem and
    comes back in `records` with an `action` of `refuse`, so no caller can
    mistake it for something to rewrite. With `write` the record goes on every
    judged script (which is where the one allowed rewrite is counted between
    runs), a refused topic leaves `scripts[]` for `skipped[]`, and the file is
    rewritten once - a loss the funnel cannot see is a topic that vanished.
    """
    path = Path(batch_file)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError) as exc:
        raise CannotJudge(f"cannot read {batch_file}: {exc}")
    # CF-0197: a batch written before the channel was renamed carries the old
    # id, frozen - the file is a dated record - so resolve it before anything
    # is looked up under it.
    channel = resolve_channel(data.get("channel"), root)
    sections = counted_sections(channel, root) if channel else FALLBACK_SECTIONS
    mode = mode or gate_mode(channel, root)

    scripts = [s for s in data.get("scripts", [])
               if script_id is None or s.get("script_id") == script_id]
    # CF-0689: on a channel that draws its own graphics, a script of nothing
    # but graphics is entirely ours - no report, no pool is asked about it.
    draws = ogl.channel_draws(channel, root or find_root())
    ours_only = {s.get("script_id") for s in scripts
                 if draws and s.get(FIELD) and not ogl.pool_anchors(s)}
    if all(s.get("script_id") in ours_only for s in scripts) and scripts:
        reports, index_data = {}, {}
        index_path = Path(footage_index) if footage_index else path.parent / FOOTAGE_INDEX_NAME
    else:
        reports = load_reports(reports_file)
        index_path, index_data = load_footage_index(batch_file, footage_index)
    aliases = alias_map(index_data)
    out(f"{batch_file}: {len(scripts)} script(s); the Video Editor's own preflight reports "
        f"from {Path(reports_file).name} (no second CLIP load, CF-0280); pool per topic from "
        f"{index_path.name}, sources collapsed through `{ALIASES_KEY}` (CF-0080) the way "
        f"source_gate.py collapses them; floor {REQUIRED_SOURCES} canonical source(s) "
        f"(video_editor.two_source_gate, CF-0118); candidates screened by the Editor's own "
        f"similarity floor before any length is compared (CF-0290/CF-0291); gate mode "
        f"`{mode}` (the channel's video_editor.two_source_gate) - "
        + (f"one rewrite, then the topic is refused as `{SKIP_REASON_CODE}`"
           if mode == MODE_ENFORCE else
           f"a one-source script is a `{SKIP_REASON_CODE}` warning and goes on (CF-0330)"))

    problems, records, refused, warnings = [], {}, [], []
    for script in scripts:
        sid = script.get("script_id")
        if sid in ours_only:
            record = records[sid] = graphics_only_record(script)
            record["gate_mode"] = mode
            out(f"  ok     {sid}: {record['reason']}")
            continue
        report = report_for(script, reports)
        pool = topic_pool(index_path, index_data, script.get("topic_id"))
        spans = shot_spans(pool["indexes"])
        need, need_source = block_seconds(script, channel, sections, root)
        floors = editor_floors(report, root, resolver)
        n_graphic = len(ogl.graphic_anchors(script)) if draws else 0
        record = records[sid] = judge(script, report, pool, aliases, spans, need, need_source,
                                      floors, n_graphic)
        record["gate_mode"] = mode
        record["warnings"] = []
        if record["action"] in (ACTION_REWRITE, ACTION_REFUSE) and mode == MODE_MEASURE:
            # CF-0330: the Editor records a one-source plan in `measure` and
            # renders it, so nothing here is rewritten or dropped either.
            record["would_have"] = record["action"]
            record["action"] = gw.ACTION_WARN
            record["failed_attempts"] = previous_failures(script)
            record["warnings"] = [gw.entry(
                script.get("topic_id"), sid, gw.GATE_TWO_SOURCES, SKIP_REASON_CODE,
                f"{finding(record)}. The channel's two_source_gate is `measure`, so this is a "
                f"warning, not a {record['would_have']} - the script goes on as written",
                numbers={k: record.get(k) for k in (
                    "anchors", "block_seconds", "required_sources", "canonical_sources",
                    "indexed_sources", "anchors_by_source", "unused_sources", "unpicturable",
                    "floors", "gate_mode", "would_have")})]
            warnings.extend(record["warnings"])
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
                script[RECORD_KEY] = record
        gw.clear(data, [s.get("topic_id") for s in scripts if s.get("script_id") in records],
                 gw.GATE_TWO_SOURCES)
        gw.record(data, warnings)
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
                         "never imported and never run: the floors and the shortest cut of the "
                         "replay are its own constants (CF-0291)")
    ap.add_argument("--out", default=None, help="write the records here as JSON")
    ap.add_argument("--write", action="store_true",
                    help="record the verdict on every script (this is where the one allowed "
                         "rewrite is counted between runs) and move a refused topic into "
                         "skipped[] as `no_second_source` - or, in `measure`, write the "
                         "warning into warnings[] (CF-0330)")
    ap.add_argument("--gate-mode", choices=MODES, default=None,
                    help="override the channel's video_editor.two_source_gate for this run "
                         "(default: read from channels/<channel>.json; an unreadable config "
                         "is `measure`, the Editor's default)")
    args = ap.parse_args(argv)
    try:
        problems, records, refused = check_batch(
            args.batch_file, args.reports,
            root=Path(args.root).resolve() if args.root else None,
            footage_index=args.footage_index, script_id=args.script_id, write=args.write,
            resolver=args.resolver, mode=args.gate_mode)
    except CannotAnswer as exc:
        print(f"check_two_sources.py: {exc}", file=sys.stderr)
        print("nothing is claimed about the scripts; do not rewrite anything on this run",
              file=sys.stderr)
        return EXIT_CANNOT_ANSWER
    if args.out:
        Path(args.out).write_text(json.dumps(records, indent=2, ensure_ascii=False))
    warned = [w for r in records.values() for w in (r.get("warnings") or [])]
    if warned:
        print(f"\n{len(warned)} warning(s) - the script(s) go on, nothing to rewrite "
              f"({gw.DECISION}; the channel's two_source_gate is `measure`):")
        for w in warned:
            print(gw.line(w))
    if problems:
        print(f"\n{len(problems)} script(s) to rewrite towards their unused source:")
        for p in problems:
            print(f"  - {p}")
    if refused:
        # Printed whatever the exit code turns out to be: a topic that left the
        # batch must be readable in the same run that took it out.
        print(f"\n{len(refused)} topic(s) refused as `{SKIP_REASON_CODE}` - the second source "
              f"cannot reach the screen, and there is nothing to rewrite"
              + ("" if args.write else "; nothing was recorded (--write)"))
        for script in refused:
            print(f"  - {script.get('script_id')}: "
                  f"{records[script.get('script_id')]['reason']}")
    # The rewrite comes first when both are on the table: the writer's move is
    # the rewrite, and the refused topic has already been recorded by then.
    if problems:
        return EXIT_REWRITE
    return EXIT_REFUSED if refused else EXIT_OK


@runlog.script("content-researcher", "check-two-sources", name="check_two_sources.py")
def cli():
    """The command-line entry (CF-0107). It calls no external binary and no
    model - the expensive answer was already bought by `check_anchor_coverage.py`
    and is read out of its `--out` file - so it leaves only its own start/done
    and no `child` events."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
