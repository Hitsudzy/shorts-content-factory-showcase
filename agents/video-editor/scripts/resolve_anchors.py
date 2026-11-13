#!/usr/bin/env python3
"""Turn visual anchors into cut footage, so the picture arrives with the word.

An anchor is a moment in the narration that has to be *seen*: the word
"cottage" at 8.2s wants a shot of a cottage on screen when it is spoken. Blocks
are derived from the anchors rather than written by hand - each anchor holds the
frame until the next one takes over.

Matching is CLIP retrieval against the footage index, so the choice is evidence,
not my eye. A shot is usually shorter than the stretch it has to cover, so the
next-best matches are appended until the block is filled; that also keeps a long
passage from sitting on one image.

Title/end cards are the one class the matcher keeps out of an ordinary anchor's
pool, and hands over first to an anchor that names on-screen graphics (CF-0035);
this only has to keep that order through the cross-index merge below.

Anchors are soft, as agreed: a weak best match is still used, but it is recorded
as unresolved so the gap is visible upstream instead of silently papered over.

CF-0041: which blocks the anchors turn into is now the rhythm's business, not
this file's. `rhythm.py` builds the block plan out of the anchor times and the
ordered (pattern, rhythm) pair; everything below only resolves footage into the
segments it hands back. With no `--order` the plan is `even`, which is the
behaviour that existed before patterns and has to stay identical to it - the
baseline pattern is pinned against real batches in the repo root's
tests/test_pattern_vocabulary.py.

Usage:
    resolve_anchors.py <anchors.json> <words.json> <voice.wav> <out-storyboard.json>
      --index <shots.json> [--index ...] --clips-dir <dir> [--min-score 0.22]
      [--order <order.json|inline json>] [--rhythm even|hold|staccato|alternate]
      [--block-count N] [--hold-seconds S] [--acceleration S]
      [--opening hook_over_footage|cold_frame|count_card|side_by_side]

CF-0050: an anchor may carry `side: "a"|"b"`, which is the side of the script's
comparison that moment belongs to. That declaration is what `alternate` swings
on and what the `side_by_side` opening splits the frame between; the footage
partition in `footage_sides()` is the fallback for a script that declared none.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

import cache_fingerprint
import meme_layer  # CF-0276: factory_root() - where patterns/ is, $FACTORY_ROOT honoured
import prepare_clip
import rhythm
import assetless_rung  # CF-0337: whether the topic-footage rung stands in for it
import repeat_guard   # CF-0337: no repeat / look-alike within 5 s
import _clip_names  # CF-0567: own capture, exempt by kind
import entity_guard   # CF-0348: no supplement shot without its entity
import event_footage  # CF-0545: a block that retells the event takes its own footage
import retired_shots  # CF-0397: a shot of an earlier ready video is spent
import _score         # CF-0433: the similarity floor's one home, the score model
import person_shot    # CF-0879: no close face of Y under the words naming X
import shot_score     # CF-0435: a weak shot is ranked and priced, not refused
import still_share    # CF-0480: what counts as a stretched held frame
import held_sharpness # CF-0480: a split block holds its sharpest frame (CF-0465)
import held_motion    # CF-0536: a split does not hold a face frozen mid-motion (CF-0481)
import wide_place     # CF-0352: a wide shot of a place is not low framing
from repo_paths import INDEXER, INDEXER_PY  # CF-0125: the sibling agent
from common import (VENV_PY, SCRIPTS, audio_duration, leading_silence,
                    load_words, grab_frame, grab_frames, PROBE_OFFSET, MIN_COVERAGE,
                    MIN_SHORT_SIDE, MAX_CONTAIN_UPSCALE, delivery_fit,
                    predict_resolution_floor_fail,
                    # CF-0132: this stage runs on every video of a batch, and
                    # every child it started waited forever. run_tool() takes
                    # the argv qc_command()/cut_command() build - those stay
                    # the one place the argv is written - and puts a ceiling
                    # under it; grab_frame() carries CF-0077's own.
                    run_tool, ASSET_TOOL_TIMEOUT_SECONDS)
from qc_asset import evaluate as qc_evaluate, MIN_MEAN_LUMA
from _runlog import runlog  # noqa: E402 - CF-0107 run accounting
# CF-0177: `video_script` is this repo's entry-point decorator (the pairing
# per-video events need). It is the same cross-repo import as `video_attempt`
# below, so a shim without it - the indexer's - falls back instead of failing;
# the decorated CLI never runs outside this repo.
try:
    from _runlog import video_script  # noqa: E402
except ImportError:  # pragma: no cover - only the other repo's shim
    video_script = runlog.script
# CF-0159: `video_attempt` is video-editor's own addition to the shim, and this
# module is imported across repositories (agents/footage-indexer). Requiring the
# addition at module level made that import fail with the indexer's own _runlog
# already in sys.modules, so the indexer would not start at all. It is needed on
# the CLI path only, which never runs outside this repo, so it is imported there.

# CF-0125: beside the main checkout. `SCRIPTS.parent.parent` used to be the
# answer and still is in the main checkout, but from a git worktree it names
# .claude/worktrees/footage-indexer, which nothing ever creates.
DEFAULT_INDEXER_PY = INDEXER_PY
MATCHER = str(INDEXER / "scripts" / "match_anchors.py")

# These moved into rhythm.py with the block plan itself (CF-0041) and are
# re-exported here, because they were this module's names for two versions and
# other code reads them off it. One definition, two places to find it.
#
# LEAD_SECONDS   - the eye has to arrive before the ear confirms.
# MIN_ANCHOR_GAP_SECONDS - the gap below which an anchor sits too tight to
#   read. CF-0152 renamed it: it was MIN_BLOCK_SECONDS, which is also the name
#   of a *different* number in `patterns/validate_patterns.py` (0.6, the block
#   floor). This one never floors a block - see the note in rhythm.py.
# MAX_SHOT_REUSE - one sample, one use (CF-0074's decision, written down in
#   CF-0121; it was 3 under CF-0026, whose caveat "2-3 times, and only when the
#   script asks for it" this replaces). Re-exported here for callers that read
#   it off this module; nothing in this file reads it directly - every path
#   asks `rhythm.ShotLedger`, which is the only code that reads the number.
#
#   A repeat used to be this stage's *sink*: when the pool ran dry, the shortage
#   drained into showing a shot a second and third time, and only a fourth
#   would surface as an unresolved anchor. There is no such sink any more. A
#   block that cannot find an unused sample falls through to the next candidate
#   and, failing that, into `unresolved_anchors` and a typographic block
#   (CF-0085) - the shortage is now visible as a missing picture instead of
#   being hidden as a familiar one. That is why CF-0121 expects the degradation
#   count to rise, and why the answer to it is a wider pool (CF-0105), not a
#   higher cap. `alternate` gets no exemption (CF-0041), nor does the
#   `side_by_side` opening (CF-0075), nor does clip -> still degradation.
from rhythm import (LEAD_SECONDS, MIN_ANCHOR_GAP_SECONDS, MAX_SHOT_REUSE,  # noqa: E402,F401
                    MAX_EMERGENCY_REUSE_PER_VIDEO,  # noqa: F401 - CF-0137
                    EmergencyReuseBudget, ShotLedger)


# The near-black ceiling this stage gates a *clip* at, looser than the 0.35
# qc_asset.py applies to a still: a shot that fades through black is normal
# footage, a still frame that is 35% black is a letterbox or a screenshot.
# Named (CF-0048) rather than left inline as an argparse default, because
# remeasure_usability.py has to report verdict changes at the same threshold
# a real run uses and a second copy of the number is how CF-0003 happened.
MAX_BLACK_CLIPS = 0.90

# CF-0276: where the drawn hold band comes from. The same answer
# build_render_plan.py uses - meme_layer.factory_root(), which honours
# $FACTORY_ROOT - because the layout and the trim that repairs it afterwards
# must not be able to read two different bands.
PATTERNS_DIR = meme_layer.factory_root() / "patterns"

# The matcher knobs this stage runs with, as constants rather than argparse
# literals (CF-0140): anchor_coverage.py has to ask the matcher the *same*
# question this stage will ask it later, and a preflight that defaulted to a
# different `--top` would be screening a different pool.
# CF-0433: the number itself lives in _score.py (one place, shared with
# build_render_plan.py's DEFAULT_SIMILARITY_FLOOR).
DEFAULT_MIN_SCORE = _score.SIMILARITY_FLOOR
DEFAULT_TOP = 10


def below_score_floor(cand, score_floor):
    """CF-0088's outright refusal: a candidate under `--score-floor` is never
    offered to a block, however many top-N slots are free. One line, named
    (CF-0140) because the coverage preflight has to narrow a pool by exactly
    the same rule before it screens what is left."""
    return score_floor is not None and cand["score"] < score_floor


def below_similarity_floor(cand, min_score):
    """CF-0290: a candidate under the similarity floor is never offered either.

    `--min-score` was a *label* until now. `match()` hands it to the matcher,
    `gate_verdict()` reports a block filled under it as unresolved ("using it
    anyway"), `candidate_supply()` calls such a pool off-topic - and the frame
    went on screen regardless. `example-film/2026-09-18T2232Z` (delver.mp4) is
    what that looks like from the sofa: two blocks of Tom Carver in an
    interview chair under phrases about a rotunda podium and a wheelchair
    being rushed across a film set, both recorded as unresolved, both shipped.
    DoD ролика item 3 says the opposite in one sentence - an unresolved anchor
    means the phrase is dropped or the video goes to needs-you, never a random
    frame - so the floor is a gate now, in exactly the shape CF-0088 gave
    `--score-floor`: under it, never offered, in every rhythm.

    The two floors stand together rather than one replacing the other.
    `--min-score` is the constant this stage and the coverage preflight
    (CF-0140) both run on - the answer to "is this a picture of the phrase";
    `--score-floor` is a run's stricter one, settable per run and unset in
    production. A candidate has to clear both to be offered.
    """
    return min_score is not None and cand["score"] < min_score


def screen_pool(candidates, min_score, score_floor):
    """The candidates a block may draw on, and the ones refused before it.

    One screen for both floors, applied once per anchor before anything is
    ordered, budgeted or cut - which is what makes "best available under the
    floor, using it anyway" unreachable from every rhythm at once instead of
    from the `budget == 1` path the delver run happened to take.

    Returns `(pool, refusals)`; a refusal is the `rejected_candidates` fields
    this module's callers merge their own `phrase` into, so a screened-out
    candidate is in the record by name and score, never merely absent. Pure.
    """
    pool, refused = [], []
    for c in candidates:
        if below_score_floor(c, score_floor):
            refused.append({
                "shot": c["shot"], "score": c["score"],
                "reason": f"scores {c['score']:.3f}, under --score-floor "
                          f"{score_floor} - never offered (CF-0088)"})
        elif below_similarity_floor(c, min_score):
            refused.append({
                "shot": c["shot"], "score": c["score"],
                "reason": f"scores {c['score']:.3f}, under the {min_score} "
                          f"similarity floor - held back (CF-0290): offered "
                          f"only when nothing at or above the floor fills the "
                          f"block, and then at a price (score.low_similarity, "
                          f"CF-0433)"})
        else:
            pool.append(c)
    return pool, refused


def below_floor_pool(candidates, min_score, score_floor):
    """CF-0433: what a block may draw on when nothing at or above the
    similarity floor filled it - the candidates `screen_pool()` held back
    under `min_score`, in rank order (score first, never length: trading the
    phrase for a longer clip is the delver defect CF-0290 was filed on).

    `--score-floor` still refuses outright: it is the run's own lower bound
    (CF-0088, unset in production) and nothing here reaches under it. No
    second, invented floor is added - the grill priced the picture instead
    (`score.low_similarity`, -3 a block, cap -15). Pure."""
    return sorted((c for c in candidates
                   if below_similarity_floor(c, min_score)
                   and not below_score_floor(c, score_floor)),
                  key=lambda c: -c["score"])


def order_candidates(candidates, max_promoted):
    """Merge one phrase's candidates from every index into one order.

    Score order, as it always was, except that title/end cards the matcher
    promoted for a card-shaped phrase (CF-0035) go in front. A plain score sort
    would undo the promotion, because a card is promoted precisely when it may
    not win on score against the photographic field: shot 3 of ZZ_urA56pJE does
    (0.390 against 0.240), but iJz9yl4ljys's German-headline card scores 0.265
    against a 0.296 portrait that is not the shot the phrase asks for.

    The matcher caps promotion per index, so N indexes can hand back N caps'
    worth; capping again here is what keeps that at `max_promoted` for the
    phrase as a whole. Demoted cards stay in the list, just not in front -
    nothing is ever dropped, so the reuse cap (CF-0121) and the usability gate
    keep every fallback they have today - and with the cap at one use, the
    length of this list is exactly how many distinct samples an anchor still
    has to fall through to.
    """
    ordered = sorted(candidates, key=lambda c: (not c.get("promoted"), -c["score"]))
    for c in [c for c in ordered if c.get("promoted")][max_promoted:]:
        c["promoted"] = False
    return sorted(ordered, key=lambda c: (not c.get("promoted"), -c["score"]))


def match(indexes, phrases, min_score, top, python):
    """Ask the indexer for the best shots per phrase, across every index.

    One matcher call for every index, not one call per index (CF-0009): each
    call loads CLIP from scratch, so two sources used to mean paying for the
    model load twice.
    """
    index_args = []
    for idx in indexes:
        index_args += ["--index", idx]
    out = run_tool(
        [python, MATCHER, *index_args, *phrases, "--top", str(top),
         "--min-score", str(min_score), "--json"], tool="match_anchors.py",
        target=", ".join(str(i) for i in indexes))
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit(f"matcher failed on {indexes}:\n{out.stderr}")
    matched = json.loads(out.stdout)
    per_index = matched["results_by_index"]
    # CF-0035: the matcher puts the best few title/end cards in front of the
    # ordinary candidates for a phrase that names on-screen graphics, and it
    # does that per index. Its own cap is therefore per index; the merge below
    # has to apply the same cap again across all of them. Read rather than
    # duplicated, so the number lives in the matcher alone.
    max_promoted = matched.get("max_promoted_cards", 0)

    # Loaded once per index and reused below, instead of once per (index,
    # phrase) pair as before (CF-0029) - also what the cached-usability
    # pre-filter looks shots up in, so main() gets it back too.
    index_data = {idx: json.load(open(idx)) for idx in per_index}

    merged = []
    for i, phrase in enumerate(phrases):
        candidates = []
        for idx, results in per_index.items():
            source = index_data[idx]["source"]
            for m in results[i]["matches"]:
                candidates.append({**m, "index": idx, "source": source})
        candidates = order_candidates(candidates, max_promoted)
        # Keep the strongest verdict across indexes: a phrase that is flat in
        # one source may be sharp in another.
        merged.append({
            "phrase": phrase,
            # The best *score* available, not whichever candidate promotion
            # put first (CF-0035) - "found" answers "does anything here
            # depict this", which promotion does not change.
            "found": bool(candidates) and max(c["score"] for c in candidates) >= min_score,
            "discriminative": any(r[i].get("discriminative", True)
                                  for r in per_index.values()),
            # CF-0227: an index that offered no candidate for this phrase
            # reports `margin: null`, not a number - the matcher's own CF-0083
            # empty-pool record, which every all-card source in the pool emits
            # for every ordinary phrase (three of the 47 today). `null` is not
            # a margin of zero: zero is a real, flat margin a source can
            # honestly have, and folding the two together would make "nothing
            # here to compare" read as "everything here looks alike". So the
            # nulls are dropped rather than defaulted, and the merged margin
            # stays `null` when *no* index had anything to measure - the same
            # answer the matcher gave, carried through instead of invented.
            # `.get("margin", 0)` defaulted only on a missing key and handed
            # `max` a None/float mix on the pool's all-card sources, which is
            # the TypeError CF-0151 hit; it never reproduced on one index
            # because `max` of a single None never compares anything.
            "margin": max((m for m in (r[i].get("margin")
                                       for r in per_index.values())
                           if m is not None), default=None),
            "candidates": candidates,
        })
    return merged, index_data


def top_exhausts_pool(index_data, top):
    """CF-0088: which indexes `--top N` filtered nothing in.

    The matcher ranks a phrase against the index's plain (non-card) shots and
    hands back the first `top` of them. On a pool no bigger than `top` that
    is the whole index, for every phrase - the ranking still orders the
    shots, but nothing is ever withheld, so an anchor can end up with a shot
    that has nothing to do with its phrase simply because it is the one the
    gates let through. Run 2026-09-03T2037Z (Raygun, 4-shot pool, default
    --top 10) shipped exactly that with no record of it; the operator had to
    guess `--top 1` by hand to see what the matcher actually preferred.

    Returns one warning string per index where `top >= plain shot count`,
    in index order; empty when top-N really was a filter everywhere. Pure -
    the caller prints and records them.
    """
    warnings = []
    for idx, data in index_data.items():
        shots = data.get("shots", [])
        plain = sum(1 for s in shots if not s.get("is_card"))
        if top >= plain:
            warnings.append(
                f"--top {top} >= {plain} candidate shot(s) in "
                f"{Path(data.get('source', idx)).name}: top-N filtered nothing - every "
                f"shot of this index was offered under every phrase, so an anchor may "
                f"take a shot unrelated to it just by surviving the gates (CF-0088). "
                f"Narrow --top, or set --score-floor to refuse weak matches")
    return warnings


def gate_verdict(phrase, used, rejected, capped, pool_size, min_score,
                 ledger=None):
    """CF-0088: the anchor's `found` verdict, taken *after* the gates.

    `match()` still reports `found` off the best score the matcher saw, and
    that number answers "does anything here depict this". It says nothing
    about whether that shot survived the gates (cached usability, the real
    usable() on the cut clip, the caption crop's floor, the reuse cap, the
    swing rules) - and in run 2026-09-03T2037Z (Wren Hollow, attempt 1) it
    did not: the matcher's first picks lost to their cached caption crop and
    cached usability, and the block was filled with whatever was left, with
    no `unresolved_anchors` entry because `found` had been settled before the
    gates ran. The operator rebuilt the record by hand from the stderr lines.

    So the verdict is taken here, on what `fill()` actually used:

      * nothing used - unresolved, and the reason carries every gate's own
        line for every candidate it turned away (`rejected` is this block's
        slice of `rejected_candidates`), rather than "failed to cut";
      * something used but its best score is under --min-score - unresolved,
        "using it anyway" as before, but now also naming the higher-scoring
        candidates the gates refused in front of it, since that is the whole
        difference between "nothing depicts this" and "the shot that did was
        rejected". **CF-0290: main() can no longer reach this branch** -
        `screen_pool()` takes such a candidate out of the pool before `fill()`
        sees it, so nothing under the floor is ever in `used`. The branch stays
        because it is the sentence that describes the defect, and because
        `build_render_plan.py`'s `unresolved_anchor` gate reads exactly this
        record (`best_used_score` against `min_score`) to refuse a storyboard
        that carries an under-floor picture anyway - one built by an older
        resolver, or by a caller that skipped the screen;
      * something used at or over --min-score - found, None.

    Returns an `unresolved_anchors` record or None. Pure.
    """
    def line(r):
        return f"shot {r['shot']}: {r['reason']}"

    if not used:
        if capped and capped == pool_size:
            # The cap took the whole pool - its own wording, from the ledger,
            # so this reason and the per-candidate ones cannot drift apart.
            reason = (ledger or ShotLedger()).exhausted_reason()
        elif rejected:
            reason = ("every candidate failed a gate - "
                      + "; ".join(line(r) for r in rejected))
        else:
            reason = "every candidate failed to cut"
        return {"phrase": phrase, "reason": reason, "found_after_gate": False,
                "gate_rejections": list(rejected)}

    best_used = max(u["score"] for u in used)
    if best_used >= min_score:
        return None
    ahead = [r for r in rejected if r.get("score", 0) >= min_score]
    reason = (f"best candidate that passed the gates scores {best_used:.3f}, below "
              f"{min_score} - using it anyway, but nothing usable in the available "
              f"footage actually depicts this")
    if ahead:
        reason += (f"; {len(ahead)} candidate(s) over the threshold were refused by "
                   f"the gates in front of it: " + "; ".join(line(r) for r in ahead))
    return {"phrase": phrase, "reason": reason, "found_after_gate": False,
            "best_used_score": round(best_used, 4), "min_score": min_score,
            "gate_rejections": ahead}


# --------------------------------------------------------------------------
# CF-0150: what the *pool* did for this anchor - a supply fact, not a verdict
# on the block. Three codes, because "no picture here" answered three
# unrelated questions with one word, and the rotation buys different things
# for each of them (rotation/shortage.py's no_footage vs footage_unusable).
# --------------------------------------------------------------------------

POOL_OFFERED_NOTHING = "pool_offered_nothing"
POOL_OFFERED_OFF_TOPIC = "pool_offered_off_topic"
POOL_OFFERED_REFUSED = "pool_offered_refused"
CANDIDATE_SUPPLY_CODES = (POOL_OFFERED_NOTHING, POOL_OFFERED_OFF_TOPIC,
                          POOL_OFFERED_REFUSED)

# How much of a phrase the evidence carries. Long enough to recognise the
# anchor, short enough that a deficit record stays readable.
SUPPLY_EVIDENCE_CHARS = 160


def candidate_supply(phrase, candidates, used, rejected, min_score):
    """Whether the pool had anything for this anchor, and if not, why not.

    `degraded_from` says which rung the block fell from; it cannot say
    whether there was ever a picture to fall with. On the Clooney run of
    2026-09-03T2037Z a block whose only offer scored 0.116 and a block whose
    two good offers were refused by `usable()` both came out `from: "clip"`,
    and the shortage record called both of them "a frame exists and cannot be
    taken". One of them needed footage bought; the other did not.

    Taken here, on the same three inputs `gate_verdict()` takes its verdict
    on, and deliberately *beside* it rather than inside it: the verdict is
    about this block ("did it get a picture"), this is about the material
    ("was there one to get"), and a block can be filled - by a 0.116 frame,
    or by CF-0137's emergency repeat - while the pool offered nothing.

      pool_offered_nothing    the matcher merged zero candidates for this
                              phrase across every index. Nothing in the pool
                              was even ranked against it.
      pool_offered_off_topic  candidates existed and the best of them scores
                              under `--min-score`. Frames were ranked; none
                              of them is about this anchor. This is the
                              Clooney water taxi, and it is still "this does
                              not exist in the pool" - buying material is the
                              remedy, not a looser gate.
      pool_offered_refused    at least one candidate stood at or over
                              `--min-score` and nothing on topic was used:
                              the gates (cached usability, `usable()` on the
                              cut, the caption-crop floor, the reuse cap,
                              `--score-floor`) or a failed cut took them all.
                              The frame exists and could not be taken.

    Returns None when the pool delivered - something at or over `--min-score`
    was used - so a caller can ask "and if not, why not" once. Pure.

    `used` is what fill() actually kept, `rejected` this anchor's own slice of
    `rejected_candidates`, `candidates` the merged pre-gate offers
    (`match_phrases()`'s `candidates`, before `--score-floor` filters it -
    the score floor is a gate like any other and must not read as "the pool
    never offered anything").
    """
    offers = list(candidates or [])
    kept = list(used or [])
    refused = list(rejected or [])
    best_offered = max((c["score"] for c in offers), default=None)
    best_used = max((u["score"] for u in kept), default=None)

    if not offers:
        code = POOL_OFFERED_NOTHING
    elif best_offered < min_score:
        # Nothing ranked here depicts the anchor. True whether or not a
        # sub-threshold frame was used anyway - that frame is not the picture
        # the script asked for, and the pool is short of material either way.
        code = POOL_OFFERED_OFF_TOPIC
    elif best_used is not None and best_used >= min_score:
        return None
    else:
        code = POOL_OFFERED_REFUSED
    return {
        "code": code,
        "searched": (phrase or "")[:SUPPLY_EVIDENCE_CHARS],
        "min_score": min_score,
        "offered": len(offers),
        "best_offered_score": None if best_offered is None else round(best_offered, 4),
        "on_topic_offered": sum(1 for c in offers if c["score"] >= min_score),
        "used": len(kept),
        "best_used_score": None if best_used is None else round(best_used, 4),
        "refused": len(refused),
        # The evidence the diagnosis can be checked against: the best offer
        # the pool actually had, named the way a shot is named everywhere
        # else. Without it the record says only that a number was below
        # another number.
        "nearest": _nearest_offer(offers),
    }


# ---------------------------------------------------------------------------
# CF-0278: the length of what a one-shot block was offered, on the record.
#
# A one-shot block sorts its pool long-enough-first (`available_seconds(c) <
# need`) and holds a frame only when the clip it got is shorter than the
# block. CF-0270's `pattern_ceiling` refusal of a degraded block stood on that
# sort: "the pool offered no longer candidate" was a sentence about the code,
# not about the pool. This is the fact instead - per block, which candidates
# were long enough, how long each was (`available_seconds`, from the cut
# point), and what became of it: `cut` (fill() accepted it), `refused` (with
# the gate's own reason, copied from `rejected_candidates`) or `not_reached`
# (the walk stopped before it - the rank put it behind the cut one). Pure
# record: nothing here reorders or refuses a candidate.
#
# CF-0517: since the user's decision of 2026-10-04 the walk is length first,
# usability second (`rank_by_usability(need=)`), so a long-enough candidate
# is `not_reached` only behind another long-enough one or behind a cut that
# already covered the block; `rung_order` says which order each run walked.
#
# Written only on blocks of a one-shot segment, the ones the sort applies to.
# Absent means "not recorded" - a storyboard from before CF-0278, a multi-shot
# block, or a segment no fill() ran for (`candidate_supply` says why).
LENGTH_SUPPLY_LIST_CAP = 8
LENGTH_CUT = "cut"
LENGTH_REFUSED = "refused"
LENGTH_NOT_REACHED = "not_reached"
LENGTH_ORDER_FIRST = "length_first"
LENGTH_ORDER_RANK = "rank"


def _shot_name(cand):
    source = cand.get("source") or cand.get("index") or ""
    return f"{Path(source).stem}:{cand.get('shot')}" if source else str(cand.get("shot"))


def fill_run(ranked, reached, rejected, length_first=False, held_whole=False):
    """One fill() run as `length_supply()` reads it: the pool in walk order
    and, per reached candidate, the refusal reason (None = cut). `reached`
    is `(cand, len(rejected) when it was reached)`; a candidate's refusal is
    the record at that index when the next one starts later. CF-0517:
    `length_first` - the run walked the long-enough shots first."""
    tried = []
    for i, (cand, at) in enumerate(reached):
        end = reached[i + 1][1] if i + 1 < len(reached) else len(rejected)
        tried.append((cand, rejected[at].get("reason") if end > at else None))
    return {"ranked": list(ranked), "tried": tried,
            "length_first": bool(length_first),
            # CF-0648: the run ranked for a block that cannot be split
            "held_whole": bool(held_whole)}


def length_supply(need, runs):
    """The block's length record from its fill() runs - see the note above.

    `long_enough` lists every candidate at or over `need` (the sort's own
    test), `too_short_tried` the shorter ones fill() actually reached; both
    capped at LENGTH_SUPPLY_LIST_CAP, the counts beside them uncapped. A
    candidate met in several runs keeps its last outcome. Pure."""
    seen = {}
    for run_no, run in enumerate(runs or []):
        outcome = {}
        for cand, reason in run.get("tried") or []:
            outcome[(cand.get("source"), cand.get("shot"))] = reason
        for rank, cand in enumerate(run.get("ranked") or []):
            key = (cand.get("source"), cand.get("shot"))
            entry = {"shot": _shot_name(cand),
                     "available_seconds": round(available_seconds(cand), 3),
                     "score": (round(cand["score"], 4)
                               if isinstance(cand.get("score"), (int, float)) else None),
                     "rung": run_no, "rank": rank}
            if key in outcome:
                reason = outcome[key]
                entry["outcome"] = LENGTH_CUT if reason is None else LENGTH_REFUSED
                if reason is not None:
                    entry["reason"] = str(reason)[:SUPPLY_EVIDENCE_CHARS]
            elif key in seen and seen[key]["outcome"] != LENGTH_NOT_REACHED:
                continue
            else:
                entry["outcome"] = LENGTH_NOT_REACHED
            seen[key] = entry
    entries = list(seen.values())
    long_enough = [e for e in entries if e["available_seconds"] >= need]
    short_tried = [e for e in entries if e["available_seconds"] < need
                   and e["outcome"] != LENGTH_NOT_REACHED]
    short_tried.sort(key=lambda e: -e["available_seconds"])
    return {
        "need_seconds": round(need, 3),
        "rungs": len(runs or []),
        # CF-0517: per rung, the order fill() walked - `length_first` (every
        # long-enough shot before any shorter one, usability within each)
        # or `rank` (usability alone: the under-floor rung).
        "rung_order": [LENGTH_ORDER_FIRST if run.get("length_first") else LENGTH_ORDER_RANK
                       for run in runs or []],
        # CF-0648: per rung, whether the walk ranked for a block a short
        # shot holds whole (a mildly blurry long shot leads, the anchor's
        # own short shot ahead of it).
        "held_whole": [bool(run.get("held_whole")) for run in runs or []],
        "offered": len(entries),
        # CF-0648: candidates no run reached - the alternatives a held-screen
        # re-cut (build_render_plan.py, held_recut) may still find.
        "not_reached": sum(1 for e in entries if e["outcome"] == LENGTH_NOT_REACHED),
        "long_enough_offered": len(long_enough),
        "longest_available_seconds": max((e["available_seconds"] for e in entries),
                                         default=None),
        "long_enough": long_enough[:LENGTH_SUPPLY_LIST_CAP],
        "too_short_tried": short_tried[:LENGTH_SUPPLY_LIST_CAP],
    }


def _nearest_offer(offers):
    """The best-scoring candidate the matcher merged, as a shot you can open."""
    if not offers:
        return None
    c = max(offers, key=lambda x: x["score"])
    source = c.get("source") or c.get("index") or ""
    return {"shot": f"{Path(source).stem}:{c['shot']}" if source else str(c["shot"]),
            "score": round(c["score"], 4),
            "source": str(source)}


def shot_lookup(index_data):
    """(index path, shot number) -> shot dict, so the pre-filter below can
    reach the usability/caption-band fields index_footage.py cached at index
    time (CF-0029) for whichever candidate it is currently looking at."""
    lut = {}
    for idx, data in index_data.items():
        for s in data.get("shots", []):
            lut[(idx, s["index"])] = s
    return lut


_STALE_CACHE_SEEN = set()


def _stale_cache(cached):
    """True when this cached measurement was not made by the code running now
    (CF-0048), including when this checkout cannot tell what made it.

    Says so once per distinct stamp per run, on stderr: the effect otherwise
    is invisible - the pipeline just quietly gets slower and starts cutting
    candidates it used to skip - and the operator needs to know a remeasure
    is owed, not discover it a batch later.
    """
    current = cache_fingerprint.usability_fingerprint()
    stamp = cached.get("measured_by")
    # CF-0406: a legacy whole-file stamp of the same reached code is current.
    if cache_fingerprint.stamp_is_current(stamp, current):
        return False
    if stamp not in _STALE_CACHE_SEEN:
        _STALE_CACHE_SEEN.add(stamp)
        print(f"  cached usability was measured by {stamp or 'unrecorded code'}, "
              f"this checkout measures {current or 'unknown'} - not trusting it, "
              f"checking those candidates for real (CF-0048). Re-stamp with: "
              f"footage-indexer/scripts/remeasure_usability.py <video>",
              file=sys.stderr)
    return True


# --------------------------------------------------------------------------
# CF-0275: somebody else's text, cut in half by our 9:16 window.
#
# The defect the operator found by eye in `mormon-wives-comeback`
# (`example-film/2026-09-17T1901Z`, 26-31s): two split-screen shots of a
# commentary video - a Vulture article on the left of shot 9, a phone thread
# on the left of shot 54 - where `cover` on the host's face keeps half of the
# left-hand panel. Words end mid-glyph ("...UING"), a stray "Share" button
# hangs in the frame, and our own captions land on top of the remains.
#
# No gate could see it: `usable()` measures the subject, the short side,
# black and luma; `card_frame` asks whether text *dominates* the frame (0.0
# here - half a frame is not domination); `detect_text_band` looks at the
# bottom strip only. CF-0275's indexer half measures the missing fact per
# shot, against the very window `build_render_plan.framing()` will use, and
# leaves it in `usable_cached`:
#
#   text_regions       how many text regions Vision found on the frame
#   text_area          their boxes as a share of the frame (boxes overlap)
#   text_outside_crop  share of the text *area* the window does not show
#   text_cut_by_crop   share of the *regions* the window's edge passes through
#   text_cut_area      those same cut regions as a share of the frame
#
# The thresholds below are chosen off the 25-shot measurement in
# `tasks/CF-0275-...md` ("Замер"), and the reasoning is worth keeping next to
# them because three of the five numbers are traps:
#
#   * `text_cut_by_crop` alone is useless on small counts. Ordinary talking-
#     head shots 40 and 42 of the same video hold exactly one region - the
#     host's own SUBSCRIBE plate - the window clips it, and they score 1.000:
#     higher than either shot of the actual defect. The share of the *frame*
#     (`text_cut_area`) is the comparable number, so that is the one thresholded.
#   * `text_outside_crop` alone is useless too: a perfectly ordinary
#     `m9R6j1KLRbQ:3` sits at 0.932 simply because its one caption is off to
#     the side, and text the window shows *none* of breaks nothing.
#   * no single number catches both shots of the defect. Shot 9 is a panel the
#     window cuts (`text_cut_area` 0.0968). On shot 54 the window's left edge
#     landed 7px past the end of the text line, so it cuts no region at all
#     (0.0) and the panel is simply beside the frame: 23 regions, 97% of their
#     area outside. Hence two clauses, each with its own evidence, rather than
#     one number stretched to cover a case it cannot see.
#
# Where each threshold stands in the measurement (non-cards):
#
#   TEXT_CUT_AREA_MAX     positives 0.0516 / 0.0751 / 0.0968; worst negative in
#                         the same video 0.0174; worst negative anywhere 0.0422
#                         (an NBC lower-third that genuinely is cut, just
#                         small). 0.05 is inside that gap and a round share of
#                         the frame - one twentieth of it in broken words. The
#                         two shots the task requires clear it by 1.5x and 1.9x.
#                         The gap 0.0422 -> 0.0516 is narrow, and deliberately
#                         resolved towards catching: a false positive costs one
#                         candidate out of a pool that offers a dozen per
#                         anchor, a false negative ships the defect.
#   TEXT_PANEL_*          shot 54 is 0.9705 outside / 23 regions, and it is the
#                         only shot in the whole measurement that meets both.
#                         The nearest negatives miss on the region count, which
#                         is what makes the clause safe: `-3NpUXI5juI:31`
#                         (0.983, 16 regions - a split screen whose left half
#                         is a photograph), `m9R6j1KLRbQ:3` (0.932, 5),
#                         `QE0W5UW2qxE:27` (1.000, 3). Twenty regions is a
#                         *panel* of text - a document, an article, a thread -
#                         not a logo or a lower-third.
#
# Two rules from the indexer's contract that the code below obeys and a reader
# has to know about:
#
#   * cards are excluded before any threshold. A card is delivered `contain`
#     (`common.delivery_fit`), so its window is the whole frame and there is
#     nothing to cut; the numbers were measured at `cover` regardless and are
#     simply wrong for it. Left in, `m9R6j1KLRbQ:0` and `-3NpUXI5juI:47` would
#     be thrown away for nothing.
#   * a missing key is not `null`. An index measured before CF-0275 never
#     asked the question, and "unknown" is not "doomed" - the same rule
#     CF-0047 states for `card_ink_fraction`. `text_regions: 0` with four
#     nulls is the other thing: measured, no text on the frame.
# --------------------------------------------------------------------------

# Share of the frame that may be text the delivered window's edge passes
# through. Above it the render shows cut words.
TEXT_CUT_AREA_MAX = 0.05
# The other clause: a panel of text the window all but excludes. Both halves
# are needed - see above, each alone names ordinary footage.
TEXT_PANEL_OUTSIDE_MIN = 0.95
TEXT_PANEL_REGIONS_MIN = 20

# The refusal's name, in the vocabulary `rejected_candidates` /
# `anchor_coverage.py`'s `refusals[]` report. Deliberately the same word as
# the `text_cut_by_crop` counter it is named after (the field cannot be
# renamed cheaply - a pool remeasure costs four hours), and the sentence it
# heads always names which of the two clauses fired.
REASON_TEXT_CUT_BY_CROP = "text_cut_by_crop"


def text_cut_refusal(shot, cached):
    """CF-0275: None, or the sentence saying this shot's text does not survive
    the 9:16 window.

    Reads only what the indexer measured about *this* frame against *this*
    delivery window; it never re-measures anything, and it is deliberately
    separate from `cached_verdict()`'s qc_asset.py call, which knows about
    darkness, subject and pixels and nothing about text.
    """
    if not cached:
        return None
    # CF-0567: our own recording is delivered as recorded - 1080x1920, the
    # 9:16 window is the whole frame - and its text is the tool's interface,
    # the footage itself. Exempt by its kind, never by its numbers.
    if _clip_names.is_own_capture_shot(shot, (shot or {}).get("source")):
        return None
    # `contain` shows the whole frame - there is no window to be cut by, and
    # the cached numbers were measured at `cover` anyway.
    if delivery_fit(bool((shot or {}).get("is_card"))) != "cover":
        return None
    cut_area = cached.get("text_cut_area")
    if cut_area is not None and cut_area > TEXT_CUT_AREA_MAX:
        return (f"{REASON_TEXT_CUT_BY_CROP}: the delivered 9:16 window cuts through "
                f"text covering {cut_area:.1%} of the frame, over the "
                f"{TEXT_CUT_AREA_MAX:.0%} ceiling")
    outside, regions = cached.get("text_outside_crop"), cached.get("text_regions")
    if (outside is not None and regions is not None
            and outside >= TEXT_PANEL_OUTSIDE_MIN
            and regions >= TEXT_PANEL_REGIONS_MIN):
        return (f"{REASON_TEXT_CUT_BY_CROP}: {regions} text regions with "
                f"{outside:.1%} of their area outside the delivered 9:16 window - "
                f"a panel of somebody else's text the window stands in the middle of")
    return None


# --------------------------------------------------------------------------
# CF-0791: the root's shot rule before the cut.
#
# ExampleScience's voyager-1 (`2026-10-17T0817Z`) lost 36 points to the frame
# judge's `judge_foreign` on seven blocks of one NASA lecture: charts and
# slides that sit *inside* the 9:16 window, which CF-0275's clause above (a
# panel 95 % outside the window) lets through by design, plus shots under
# 600 px the soft resolution price only charges -2 each for. The pool knew it
# all before the cut (`usable_cached.text_regions`, `short_side`). The rule is
# the root's - `shared/score/shot_guard.py`, beside the score model, so the
# root's offline `shot_guard.py measure` and this filter read one copy - and
# per channel: `channels/<id>.json -> video_editor.shot_guard.mode`
#
#   fail  a refusing finding takes the shot out of the pool before the cut,
#         with its own sentence in `rejected_candidates`
#         (`text_panel_in_window: ...` / `under_resolution_floor: ...`);
#   warn  (every channel until the user signs `fail`) nothing is refused, the
#         findings of the shots the storyboard shows are written to its
#         `shot_guard` record;
#   off   the rule is not asked.
#
# A root without the module (older than CF-0791, or this repo copied out on
# its own) refuses nothing and says so once: a plan is never lost to it.
# --------------------------------------------------------------------------
SHOT_GUARD_TASK = "CF-0791"
_GUARD_STATE = {"loaded": False, "cfg": None, "channel": None, "error": None}
# shot id -> the guard's findings, for the storyboard's `shot_guard` record
_GUARD_SEEN = {}


def configure_shot_guard(channel=None, cfg=None, root=None):
    """Load the guard's settings for this process, once: `cfg` as given (a
    test's block, overlaid on the module's defaults), else the channel's
    `video_editor.shot_guard` (`shot_guard.channel_config`, under `root` -
    by default the root the module came from). Returns the
    settings in force, or None when the module cannot be reached."""
    _GUARD_SEEN.clear()
    _GUARD_STATE.update(loaded=True, cfg=None, channel=channel, error=None)
    mod = _score.shot_guard()
    if mod is None:
        _GUARD_STATE["error"] = _score.shot_guard_error()
        print(f"  WARNING: {_GUARD_STATE['error']} - the pre-cut shot guard "
              f"({SHOT_GUARD_TASK}) is not asked this run", file=sys.stderr)
        return None
    try:
        cfg = (mod.config(cfg) if cfg is not None
               else mod.channel_config(channel, root=root))
    except mod.ShotGuardError as e:
        _GUARD_STATE["error"] = f"{channel}: {e}"
        print(f"  WARNING: shot guard settings of {channel!r} unusable ({e}) - "
              f"using the module's defaults ({SHOT_GUARD_TASK})", file=sys.stderr)
        cfg = mod.config()
    _GUARD_STATE["cfg"] = cfg
    return cfg


def shot_guard_refusal(shot, shot_id=None, cached=None):
    """CF-0791: None, or the root's sentence for why this shot leaves the pool
    before the cut (mode `fail` only). `shot_id` is `<video id>:<index>` as
    the plan writes it; `cached` stands in for the shot's own `usable_cached`
    (`cached_verdict()`'s caller may hand a fresh measurement). Every finding,
    refusing or not, is remembered for the storyboard's record."""
    if not _GUARD_STATE["loaded"]:
        configure_shot_guard(None)
    cfg, mod = _GUARD_STATE["cfg"], _score.shot_guard()
    if cfg is None or mod is None or not isinstance(shot, dict):
        return None
    if cached is not None:
        shot = {**shot, "usable_cached": cached}
    sid = shot_id
    # our own recording is exempt by kind; the root reads the kind off the
    # id, the pool may say it only in `source_kind` (CF-0567)
    if _clip_names.is_own_capture_shot(shot, sid) and not mod.is_own_capture(sid):
        sid = f"{mod.OWN_CAPTURE_PREFIX}{sid or ''}"
    findings = mod.shot_findings(shot, cfg, sid)
    if findings and shot_id:
        _GUARD_SEEN[str(shot_id)] = findings
    return mod.shot_refusal(shot, cfg, sid)


SHOT_GUARD_REASONS = ("text_panel_in_window", "under_resolution_floor")


def shot_guard_record(blocks, rejected):
    """The storyboard's `shot_guard`: the mode in force, the guard's findings
    on every shot the blocks show (what `warn` keeps on screen and says), and
    how many candidates it took out (`fail`)."""
    shown = []
    for b in blocks or []:
        shown.extend(block_shots(b))
    findings = [{"shot": sid, **f}
                for sid in dict.fromkeys(shown) for f in _GUARD_SEEN.get(str(sid), ())]
    cfg = _GUARD_STATE["cfg"]
    return {"mode": cfg["mode"] if cfg else None,
            "channel": _GUARD_STATE["channel"],
            "error": _GUARD_STATE["error"],
            "findings": findings,
            "refused": sum(1 for r in rejected or []
                           if str(r.get("reason", "")).startswith(SHOT_GUARD_REASONS))}


def precut_cache_refusal(shot, min_short_side, min_coverage, max_black, shot_id=None):
    """What the cached measurement refuses this shot for, in words, or None.

    `probably_unusable()`'s answer with a reason attached, and the only place
    the two cached refusals are ordered. Split out (CF-0275) because the new
    one has to be *named* where it lands - `rejected_candidates`, the coverage
    preflight's `refusals[]` - instead of arriving as the same
    "pre-filtered by cached shot usability" sentence every other cached
    refusal has carried since CF-0029: the whole point of the rule is that an
    operator who sees a block change picture can tell which gate moved it.
    """
    cached = shot.get("usable_cached") if shot else None
    if not cached:
        return None
    if _stale_cache(cached):
        return None
    text = text_cut_refusal(shot, cached)
    if text:
        return text
    # CF-0791: the root's shot rule - a panel of somebody else's text inside
    # the window, a source under the channel's resolution floor. Refuses only
    # in a channel set to `fail`; `warn` records.
    guard = shot_guard_refusal(shot, shot_id)
    if guard:
        return guard
    # CF-0435: only a hard fact of the cache refuses - a black or an empty
    # frame. Framing, brightness and resolution under their floors no longer
    # do: such a shot is ranked behind the clean ones (`shot_score.rank()`)
    # and, when it is the best there is, shown and priced by the plan.
    hard = cached_hard_refusal(shot)
    if hard:
        return f"pre-filtered by cached shot usability, not cut - {hard}"
    return None


# CF-0435: the hard rules of the pool's usability record the pre-filter acts
# on. `burned_text` is the third one, and it is `entity_guard.refusal()`'s -
# asked before this filter on every rung, with its own sentence.
CACHED_HARD_RULES = ("black_frame", "empty_frame")


def cached_hard_refusal(shot):
    """CF-0435: None, or the words for the hard rule the shot's (fresh) cache
    breaks - `black_frame` (over MAX_BLACK_CLIPS, a lit card excused) or
    `empty_frame` (Vision found no subject). The Footage Indexer's
    `shot_usability` decides it (`shot_score.cached_hard`), the same record
    that ranks the shot, so the pool's depth count and this filter agree."""
    for v in shot_score.cached_hard(shot, fresh=True):
        if v.get("rule") not in CACHED_HARD_RULES:
            continue
        limit = v.get("ceiling")
        return (f"{v['rule']} ({v.get('value')}"
                + (f" > {limit}" if limit is not None else "") + ")")
    return None


def probably_unusable(shot, min_short_side, min_coverage, max_black, shot_id=None):
    """Pre-filter a candidate using the usability index_footage.py measured
    once at index time, before paying for cut() at all (CF-0029, safe
    variant agreed in CF-0011).

    This only ever *skips* a candidate before it is cut - it never decides
    which candidate is chosen. Whichever candidate actually gets cut still
    goes through the real usable() check below on its own cut clip, exactly
    as before; this just stops the obviously-doomed ones from paying for a
    cut() first. A candidate with no cache (an index built before CF-0029,
    or whose per-shot probe failed) is never skipped here - it costs exactly
    what it always cost.

    CF-0048: nor is a candidate skipped on a measurement some *other* version
    of the measuring code made. The cache holds raw measurements rather than
    a verdict so that moving a threshold needs no re-index - that still holds -
    but a raw measurement is the output of code, and when that code changes the
    cached numbers describe a measurement this pipeline no longer takes. Every
    index in the pool was measured before CF-0004 taught smart_crop.py to
    re-centre animated frames; re-probing all 257 cached shots in the pool
    flipped 21 of them from doomed to fine and none the other way, 7 of the 21
    title cards. An unrecognised stamp is treated exactly like no cache at
    all: check for real. The pre-filter is documented as never deciding who
    is chosen, and it can only keep that promise while the numbers it reads
    are ones this code would produce today.

    CF-0275 adds a second cached refusal beside the qc_asset.py one (text the
    delivery window cuts in half); both live in `precut_cache_refusal()`,
    which is this function with the reason kept rather than thrown away.
    """
    return precut_cache_refusal(shot, min_short_side, min_coverage,
                                max_black, shot_id) is not None


def cached_verdict(shot, cached, min_short_side, min_coverage, max_black,
                   shot_id=None):
    """What these cached numbers alone say about the shot: True for "skip it,
    it is doomed". Split out of probably_unusable() (CF-0048) so that
    remeasure_usability.py can report what a remeasure changes about the
    pre-filter's opinion using this exact rule instead of a second copy of it -
    the answer to "how much does re-measuring move the montage" has to come
    from the code that actually does the filtering.

    Age is not this function's question - probably_unusable() decides whether
    these numbers may be believed at all before it gets here.

    CF-0435: this is the old bundle's opinion (every floor a refusal), and the
    pre-filter no longer acts on it: `precut_cache_refusal()` refuses on
    `cached_hard_refusal()` (black, empty) and on `text_cut_refusal()` only,
    and the soft floors rank the candidate instead. Kept for
    remeasure_usability.py's report of what a remeasure moves in the bundle.
    """
    # CF-0275: text the delivered window cuts in half, decided ahead of
    # everything else for the same reason as the resolution floor below - it
    # is a fact about what the render will put on screen, independent of
    # darkness, ink and subject, and none of the fallbacks further down can
    # excuse it. Here rather than only in precut_cache_refusal() so that
    # remeasure_usability.py, which asks this function directly for "what does
    # a remeasure change about the pre-filter's opinion", gets the same answer
    # the resolver acts on.
    if text_cut_refusal(shot, cached):
        return True
    # CF-0791: nor does anything below excuse a shot the root's shot rule
    # takes out before the cut (a channel in `fail`).
    if shot_guard_refusal(shot, shot_id, cached=cached):
        return True
    # CF-0104: `cached["short_side"]` is min(real_width, real_height) with
    # the orientation thrown away, which is exactly the number the old floor
    # needed and not enough for the new one - cover's floor now needs the
    # tightened crop window's *height* (smart_crop's focus/zoom, never
    # cached), and contain's needs the frame's real height on its own axis
    # (a 608-wide portrait source and a 608-tall landscape one collapse to
    # the same cached number and only one of them would actually fail). This
    # square placeholder keeps the *other* checks below - subject, black,
    # luma, coverage - reading the same cache correctly; the resolution axis
    # is deliberately neutralised a few lines down rather than judged on a
    # number that cannot tell those two shots apart.
    vision = {"source_size": {"width": cached["short_side"], "height": cached["short_side"]},
              "roi_source": cached["roi_source"], "roi_coverage": cached["roi_coverage"]}
    # CF-0047: for a card, whether its darkness is legitimate is decided by
    # how much of its own text is lit, and that measurement is cached only by
    # an index built since CF-0047. `None` here spans two different states and
    # they are not interchangeable: the key present but null means "measured,
    # Vision found no text" (a genuine reason to reject), while the key being
    # absent means "this index never asked" - handled below.
    card = bool(shot.get("is_card"))
    measured_ink = card and "card_ink_fraction" in cached
    # CF-0104 left the resolution axis unconditionally neutralised here -
    # min_short_side=0 / max_contain_upscale=inf make evaluate()'s floor
    # pass unconditionally, in both delivery modes - because usable_cached
    # did not yet carry the geometry the new floor actually needs. CF-0078
    # gives it that geometry (`width`/`height`, alongside the old squared
    # `short_side` placeholder) and judges the resolution axis separately,
    # below, instead of asking evaluate() to judge it from the placeholder.
    # The other checks - subject, black, luma, coverage - still go through
    # evaluate() exactly as before; only what used to be a permanently-passing
    # placeholder changes.
    verdict = qc_evaluate(vision, cached["black_fraction"], cached["mean_luma"],
                          0, min_coverage, max_black, MIN_MEAN_LUMA,
                          card_ink=(cached["card_ink_fraction"] or 0.0) if measured_ink else None,
                          fit=delivery_fit(card), max_contain_upscale=float("inf"))
    # CF-0078: is this shot *guaranteed* to fail the geometry-aware
    # resolution floor once prepare_clip.py's own caption crop is applied -
    # predict_resolution_floor_fail()'s docstring has the exact reasoning for
    # what can and cannot be told from cached geometry alone. This is a hard
    # fact about the source's own pixels, independent of the darkness/ink
    # question the fallback below exists for, so it is checked first and
    # short-circuits regardless of how that other question resolves - a shot
    # this proves doomed is doomed no matter what its ink measurement would
    # have said.
    width, height = cached.get("width"), cached.get("height")
    if width is not None and height is not None:
        # CF-0092: the crop prepare_clip.py will *actually* apply - a live
        # shot's band above the live ceiling is refused there (and, CF-0103,
        # a card's band above CARD_OWN_BAND is kept as the card's own), so a
        # prediction made from the raw cached band would doom a shot that
        # is about to be cut at full height.
        crop_bottom, _, _ = prepare_clip.caption_crop(
            shot.get("crop_bottom_cached") if shot else None, card)
        if predict_resolution_floor_fail(width, height, crop_bottom, delivery_fit(card),
                                          min_short_side, MAX_CONTAIN_UPSCALE):
            return True
    # width/height absent (CF-0048: an index measured before CF-0078 added
    # them cannot answer this question at all) falls through exactly as
    # before - "unknown" is not "doomed".
    if not verdict["usable"] and card and not measured_ink \
            and set(verdict["failed"]) <= {"black", "luma"}:
        # An older index cannot answer the only question that would condemn
        # this candidate, and "unknown" is not "doomed". Fall through to the
        # real gate on the cut clip, which measures the ink itself, rather
        # than skipping a card on a question this cache never asked. Costs a
        # cut() for such candidates - exactly what they cost before CF-0029 -
        # and is the same rule the docstring already states for a shot with
        # no cache at all, and the same rule CF-0048 now applies to a cache
        # measured by code this checkout does not recognise.
        return False
    return not verdict["usable"]


def qc_command(probe, min_short_side, min_coverage, max_black, card=False,
               crop=None, window=None, window_zoom=1.0):
    """The qc_asset.py call usable() makes for one probe frame. Its own
    function so a test can check what the gate is told without cutting a
    clip: CF-0062's whole point is that the gate is told about the crop.
    `crop` is what cut() returned - the caption crop applied and the frame
    it was applied to.

    `window` (CF-0155) is the framing this clip will be shown with - `"self"`
    for the frame the planner takes that framing from, or the `(x, y)` focus
    it produced, for every other frame of the same clip. Without it
    qc_asset.py measures coverage against the frame's own best crop, which
    is what every caller outside this gate still asks for.
    """
    cmd = [VENV_PY, str(SCRIPTS / "qc_asset.py"),
           str(probe), "--json", "--min-short-side", str(min_short_side),
           "--min-coverage", str(min_coverage), "--max-black", str(max_black)]
    if card:
        cmd.append("--card")
    if crop and crop.get("crop_bottom"):
        cmd += ["--caption-crop", str(crop["crop_bottom"])]
        if crop.get("frame_before_crop"):
            cmd += ["--frame-before-crop", crop["frame_before_crop"]]
    if window == "self":
        cmd += ["--window", "self"]
    elif window:
        cmd += ["--window", f"{window[0]},{window[1]}",
                "--window-zoom", str(window_zoom)]
    return cmd


# --------------------------------------------------------------------------
# CF-0904: past the strip allowance, a cover-ready shot of the same pool.
#
# After CF-0903 the strip a plan keeps past the signed allowance
# (shot_score.STRIP_ALLOW_SECONDS, `score.narrow_strip_on_blur`) is the one
# its own probe asks for: a wide trailer frame (2.2-2.39:1) whose subject is
# wider than the 9:16 crop. The 12 refusals of 18.10-30.10 kept 88 s of it
# (wildwood 0840Z 27 %, the-long-voyage 1624Z 34 %, sandfall-part-three 0841Z 36 %),
# while 40-77 % of the same works' pool shots fit the crop. The resolver is
# where a shot is chosen and the only place that cuts the clip and probes the
# very frame the plan frames it from (usable()'s first probe, CF-0155), so
# the choice is made here: fill() keeps a running count of the seconds of
# such pictures (strip-wide clip, first probe `low_framing`), and once the
# next one would take the video past the allowance that cut is held back -
# not refused - while up to STRIP_SPARE_CUTS more candidates of the same rung
# are cut, in rank order, for one whose first probe keeps the subject. Found:
# it is the picture and the held cut goes back to the pool. Not found: the
# held cut is taken after all, exactly as before. No price, no refusal, no
# rank changes; the record is the storyboard's `strip_picks`.
# --------------------------------------------------------------------------
STRIP_PICK_TASK = "CF-0904"
STRIP_SPARE_CUTS = 3        # extra cuts one fill() may spend looking (~3 s each)
STRIP_SCREEN_WIDTH = 1080   # a blur_fill picture spans the screen's width
STRIP_SCREEN_HEIGHT = 1920


def clip_size(applied, shot=None):
    """`(width, height)` of the cut clip: cut()'s `frame_before_crop` less
    its caption crop, else the pool's cached size, else None."""
    applied = applied or {}
    m = re.match(r"^(\d+)x(\d+)$", str(applied.get("frame_before_crop") or ""))
    if m:
        w, h = float(m.group(1)), float(m.group(2))
        try:
            h *= 1.0 - float(applied.get("crop_bottom") or 0.0)
        except (TypeError, ValueError):
            pass
        return w, h
    cached = (shot or {}).get("usable_cached") or {}
    try:
        return float(cached["width"]), float(cached["height"])
    except (KeyError, TypeError, ValueError):
        return None


def strip_wide(size, share_below=None):
    """True when a picture of `size` shown whole across the screen's width
    (blur_fill, shot_score.blur_fill_rect) is under the strip share - every
    16:9 or wider frame. False for an unknown size."""
    share_below = shot_score.STRIP_SHARE if share_below is None else share_below
    try:
        w, h = float(size[0]), float(size[1])
    except (TypeError, ValueError, IndexError):
        return False
    if w <= 0 or h <= 0:
        return False
    return STRIP_SCREEN_WIDTH * h / w / STRIP_SCREEN_HEIGHT < share_below


def strip_seconds_of(span, first, applied, shot=None, card=False):
    """CF-0904: the strip seconds this cut asks the plan for on its own probe -
    `span` when its first probe found the framing low and its picture is
    strip-wide, else 0.0. A card is fitted whole anyway (not a blur_fill)."""
    if card or not first or not first[0].get("low_framing"):
        return 0.0
    return float(span) if strip_wide(clip_size(applied, shot)) else 0.0


def strip_hold_reason(so_far, span):
    """The `rejected_candidates` line of a cut held back (CF-0904)."""
    return (f"held back: its own probe frame cuts the subject in the 9:16 crop "
            f"and the picture would be a strip on blur ({span:.2f} s) with the "
            f"video's strip already at {so_far:.2f} s of the "
            f"{shot_score.STRIP_ALLOW_SECONDS:g} s allowance - a cover-ready "
            f"shot of this pool was cut instead ({STRIP_PICK_TASK})")


# CF-0155: how many frames of the window the block will actually show this
# gate judges. Four, sampled in one ffmpeg pass, measured at ~3s per candidate
# on the CF-0122 sample - cheaper than the two separate seeks the gate used to
# make, and the ceiling stays there until a remeasurement argues otherwise.
PROBE_FRAMES = 4
# A block shorter than this much past the planner's own frame is sampled at a
# fixed step instead of a degenerate one: four frames of a 0.6s window are the
# same frame four times, and ffmpeg cannot be asked for `fps=1/0`.
MIN_PROBE_STEP = 0.05


def probe_offsets(seconds, count=PROBE_FRAMES, first=PROBE_OFFSET):
    """Which moments of a `seconds`-long cut clip the gate judges.

    `first` is PROBE_OFFSET - the frame build_render_plan.py takes this clip's
    framing from - and it has to be one of the probes, because the whole point
    of CF-0155 is that the other frames are judged against *its* window. The
    rest divide the shown window [first, seconds] into `count` equal cells and
    stand at the head of each, so the offsets are a function of the clip alone:
    a longer block adds frames, it never moves the ones a shorter block had
    scaled to a different place in the picture (CF-0122's defect).

    The window is [first, seconds] rather than [0, seconds] on the same
    budget: the planner's frame must be probed and a fifth frame costs a fifth
    Vision call, so the half second before it - which no framing decision is
    ever made from - is what the budget gives up.
    """
    # Rounded before the offsets are built, not after: ffmpeg is asked for one
    # `fps=1/step` pass, so the moments it really samples are multiples of the
    # step it was given, and the offsets this returns are the ones a failure
    # line names.
    step = round(max((seconds - first) / count, MIN_PROBE_STEP), 3)
    return [round(first + k * step, 3) for k in range(count)]


def usable(clip, seconds, min_short_side, min_coverage, max_black, card=False,
           crop=None, soft_out=None, wide_out=None, first_out=None):
    """Gate a freshly cut candidate before it is accepted. Returns
    (ok, failures): an empty list when the clip passed, otherwise
    qc_asset.py's own failure lines, so the storyboard can record *why* a
    candidate was rejected rather than just that it was.

    CLIP ranks by resemblance and knows nothing about whether a shot is
    *usable* - it happily returned a frame that was 98% black. Checking here
    means a failed candidate simply yields to the next best one, instead of
    surfacing later as a rejected plan with nothing to substitute.

    `card` (CF-0047) tells qc_asset.py that this clip was cut from a shot the
    index flagged as a title/end card, so a frame that is dark because the
    card is gold-on-black can be told from one that is dark because nothing
    is on it. It never loosens anything on its own: qc_asset.py still has to
    measure that the card's own text is lit.

    `crop` (CF-0062) is cut()'s record of the caption crop prepare_clip.py
    actually applied to this clip. The resolution floor is checked on the cut clip,
    after that crop, so a 720px source fails it on any caption band at all;
    telling qc_asset.py what was cropped lets it name that failure for what
    it is - our own crop, not a low-res source - instead of the two reading
    identically. It changes no verdict.

    CF-0155: what this gate asks about framing is whether the subject is
    inside the rectangle the viewer will see. build_render_plan.py frames the
    whole clip from the frame at PROBE_OFFSET and never recomputes it, so that
    is the rectangle - taken from that frame here, exactly as the planner
    takes it, and then held over every other probe. Before, each probe was
    measured against its *own* best crop: a number no render ever uses, which
    answered "this frame could have been cropped well" and flipped whenever
    Vision switched detector between neighbouring frames (CF-0122's measured
    profile). The probes themselves are PROBE_FRAMES frames of the window the
    block actually shows, in one ffmpeg pass, so the verdict is a property of
    the clip and not of the length the rhythm happened to ask for.

    The aggregation rule is deliberately untouched: every probed frame must
    pass, as both probes had to before. Whether one bad frame should sink a
    block is CF-0156's question, to be answered on numbers measured with only
    this one factor moved.

    CF-0435: "pass" means no *hard* failure. A probe that fails only framing,
    brightness or resolution (`shot_score.split_verdict()`) does not sink the
    clip: its soft rules are appended to `soft_out` (when the caller passes a
    list) and the clip goes on screen, priced by the plan. Subject, black,
    crop framing and a hung tool still refuse, with every line, as before.

    CF-0352: `wide_out` (a list, passed only for a picture of a place anchor)
    takes a probe's `coverage` failure off its verdict when the probe's
    subject box is not a face (`wide_place.waive_qc`) - a general view of a
    building is not a badly framed shot - and gets `(coverage, roi_source)`
    for the record's warning. A face keeps the floor.

    CF-0904: `first_out` (a list) gets the verdict of the first probe - the
    frame build_render_plan.py frames the clip from - as `{"offset",
    "roi_coverage", "low_framing"}`: `low_framing` True when that frame's
    9:16 window cuts the subject (after the place waiver). That is the frame
    whose low framing asks the plan for a blur_fill CF-0903 never takes back
    (`framed_by: probe`), so the resolver can count the strip it will cost.
    """
    offsets = probe_offsets(seconds)
    step = round(offsets[1] - offsets[0], 3)
    pattern = str(Path(clip).with_suffix(".probe_%02d.png"))
    probes = grab_frames(clip, offsets[0], step, len(offsets), pattern)
    if not probes:
        return False, [f"could not extract a probe frame at {offsets[0]:.1f}s"]
    # CF-0155: the framing this clip will be rendered with, taken from the same
    # frame build_render_plan.py takes it from and then held for every other
    # probe - which is what the renderer does with it. `"self"` asks qc_asset.py
    # to point that first frame at itself and hand the framing back.
    window, window_zoom = "self", 1.0
    try:
        for probe, offset in zip(probes, offsets):
            out = run_tool(
                qc_command(probe, min_short_side, min_coverage, max_black, card,
                           crop, window=window, window_zoom=window_zoom),
                tool="qc_asset.py", target=str(probe),
                # The same class build_render_plan.py caps this gate at (CF-0077):
                # one asset through qc_asset.py, Vision fallback chain included.
                timeout=ASSET_TOOL_TIMEOUT_SECONDS)
            if not out.stdout.strip():
                return False, [f"qc_asset.py gave no verdict at {offset:.1f}s: "
                               f"{out.stderr.strip()[-200:]}"]
            verdict = json.loads(out.stdout)
            if window == "self":
                measured = verdict.get("coverage_window")
                if measured:
                    window = (measured["focus"]["x"], measured["focus"]["y"])
                    window_zoom = measured["zoom"]
            if wide_out is not None:
                verdict, waived = wide_place.waive_qc(verdict)
                if waived is not None:
                    wide_out.append((waived, verdict.get("roi_source")))
                    print(f"  QC WIDE PLACE {Path(clip).name} @{offset:.1f}s: "
                          f"window keeps {waived:.0%} of a {verdict.get('roi_source')} "
                          f"box - a general view of the place, not low framing "
                          f"(CF-0352)", file=sys.stderr)
            hard, soft = shot_score.split_verdict(verdict)
            if first_out is not None and offset == offsets[0]:
                first_out.append({"offset": offset,
                                  "roi_coverage": verdict.get("roi_coverage"),
                                  "low_framing": (not hard
                                                  and shot_score.LOW_FRAMING in soft)})
            if soft and not hard:
                # CF-0435: weak, not unusable - said out loud like a
                # relaxation, since the clip is kept for a price.
                print(f"  QC SOFT {Path(clip).name} @{offset:.1f}s: "
                      + "; ".join(verdict.get("failures") or soft)
                      + " - shown and priced (CF-0435)", file=sys.stderr)
                if soft_out is not None:
                    soft_out.extend(r for r in soft if r not in soft_out)
                continue
            failed = probe_failure(clip, offset, verdict, crop, min_short_side)
            if failed is not None:
                return False, failed
        return True, []
    finally:
        for probe in probes:
            Path(probe).unlink(missing_ok=True)


def probe_failure(clip, offset, verdict, crop, min_short_side):
    """qc_asset.py's verdict on one probe frame, as usable()'s answer: the
    failure lines when this frame sinks the candidate, None when it does not.

    Split out of usable()'s loop (CF-0155) only because that loop now runs over
    a variable number of frames and the reporting - which failures are named
    out loud on stderr, and which relaxations - is a page of its own. The rule
    is unchanged, deliberately: every probed frame must pass, exactly as both
    probes had to before. Whether that stays the rule is CF-0156's question,
    and it is asked against numbers measured with this one factor changed.
    """
    if not verdict["usable"]:
        if verdict.get("resolution_lost_to_crop"):
            # CF-0062/CF-0104: the same rule as a relaxation, from the
            # other side - a shot the pipeline itself made unusable may
            # not go quietly. Names which floor it fell under - cover's
            # window height or contain's upscale norm - since the two
            # read very differently on the same crop.
            mode = verdict.get("fit", "cover")
            if mode == "contain":
                print(f"  QC CROP LOSS {Path(clip).name} @{offset:.1f}s [contain]: "
                      f"caption crop {crop['crop_bottom']:.0%} took a "
                      f"{verdict['short_side_before_crop']}px frame over the "
                      f"x{verdict.get('max_contain_upscale')} upscale norm "
                      f"(x{verdict.get('contain_upscale_factor')} now)", file=sys.stderr)
            else:
                print(f"  QC CROP LOSS {Path(clip).name} @{offset:.1f}s [cover]: "
                      f"caption crop {crop['crop_bottom']:.0%} took a "
                      f"{verdict['short_side_before_crop']}px source under the "
                      f"{min_short_side}px delivery-height floor "
                      f"({verdict.get('delivery_height')}px left)", file=sys.stderr)
        if verdict.get("framing_lost_to_crop"):
            # CF-0092: the crop cut into the people, not just the
            # pixel count - the defect the Clooney run's operator had
            # to find by eye. Named out loud for the same reason.
            print(f"  QC CROP FRAMING {Path(clip).name} @{offset:.1f}s: "
                  f"caption crop {crop['crop_bottom']:.0%} left the faces at "
                  f"{verdict.get('subject_centre'):.0%} of the frame's height, "
                  f"{verdict.get('subject_foot_margin'):.0%} from the bottom edge",
                  file=sys.stderr)
        return list(verdict["failures"])
    # A gate that was relaxed has to say so out loud (CF-0047): a card is
    # the one thing here allowed past the darkness checks, and it may not
    # be allowed past them quietly.
    for note in verdict.get("relaxations", []):
        print(f"  QC RELAXED {Path(clip).name} @{offset:.1f}s: {note}", file=sys.stderr)
    return None


def load_order(spec, args):
    """The order Content Researcher drew, or None for the pre-pattern default.

    Accepts a path to a JSON file or an inline JSON object - the order is the
    `pattern` object of `03-content-researcher.json` (CF-0039's `draw_order`),
    so a caller can point straight at a file it extracted rather than
    reassembling it. The individual flags below it exist for running one
    scenario through several rhythms, which is how CF-0041's exit criterion is
    checked; they override whatever the order said.
    """
    order = None
    if spec:
        text = spec
        if not spec.lstrip().startswith("{"):
            text = Path(spec).read_text()
        order = json.loads(text)
        # A whole 03-*.json, or one script out of it, both carry the order
        # under "pattern" - unwrap rather than making the caller do it.
        if "pattern" in order and "rhythm_id" not in order:
            order = order["pattern"]
    if args.rhythm or args.block_count or args.hold_seconds or \
            args.acceleration is not None or args.opening:
        order = order or {}
        params = dict(order.get("parameters") or {})
        if args.rhythm:
            order["rhythm_id"] = args.rhythm
        if args.pattern:
            order["pattern_id"] = args.pattern
        if args.block_count:
            params["block_count"] = args.block_count
        if args.hold_seconds:
            params["key_frame_hold_seconds"] = args.hold_seconds
        if args.opening:
            params["opening_block"] = args.opening
        if args.acceleration is not None:
            params["acceleration_to_payoff"] = {
                "enabled": args.acceleration > 0,
                "strength": args.acceleration or None}
        order["parameters"] = params
    elif order is not None and args.pattern:
        order["pattern_id"] = args.pattern
    return order


def footage_sides(matches, shots_lut, min_short_side, min_coverage, max_black):
    """The two sets `alternate` swings between, taken from the footage itself.

    **The fallback, since CF-0050, not the main path.** A side is a property of
    the script - the anchors say which side of the comparison each moment is on
    (`declared_anchor_sides()` below) - and this is what happens when the script
    declared none. It partitions by *source*: two different source videos are
    the one partition available without a declaration that a viewer can tell
    apart on sight.

    Its limit is exactly why it is now the fallback: a comparison whose two
    halves were shot by the same camera has one source and no second side here,
    while two sources that merely happen to be in the pool are declared to be
    the two sides of a comparison nobody wrote.

    A candidate the cached usability pre-filter already condemns (CF-0029) is
    not counted. A source that turns up in the match results and then supplies
    nothing usable is not a second set of footage, and treating it as one is
    worse than having no second set at all: every block ordered onto that side
    falls back to the first, which is how an alternation degenerates into the
    same shot twice in a row - CF-0034's defect arrived at from the other end.
    This is the check that fires on the real wren-hollow batch, whose second
    source is 608px against a 720px floor.

    Returns {source: "a"|"b"} or None when fewer than two sources can supply a
    picture, in which case there is nothing to alternate and the caller falls
    back to `even` in writing.
    """
    counts = Counter()
    for m in matches:
        for c in m["candidates"]:
            shot = shots_lut.get((c["index"], c["shot"]))
            if probably_unusable(shot, min_short_side, min_coverage, max_black,
                                 _shot_name(c)):
                continue
            counts[c["source"]] += 1
    top = [src for src, _ in counts.most_common(2)]
    if len(top) < 2:
        return None
    return {top[0]: "a", top[1]: "b"}


def declared_anchor_sides(anchors):
    """The side each anchor was written on, or None (CF-0050).

    `side` is optional on an anchor and only means anything to `alternate` and
    to the `side_by_side` opening. Anything that is not exactly "a" or "b" is
    read as "not declared" rather than rejected: an anchor that names no side is
    a legitimate moment in a comparison - it is simply not on either side of the
    axis, and `rhythm.side_runs()` keeps the picture where it already was.
    """
    return [a.get("side") if a.get("side") in ("a", "b") else None for a in anchors]


def side_pools(anchors, matches, anchor_sides, sides):
    """Candidate pools for the two halves of a `side_by_side` opening.

    Returns `{"a": (anchor_index, candidates), "b": ...}` for whichever sides
    can supply one. Two ways in, matching the two ways sides are known at all:

      * declared - the first anchor written on each side supplies that half.
        The phrase is the side, so its own match results already describe the
        right thing and nothing has to be filtered.
      * footage - the opening anchor's own candidates split by source. There is
        no per-anchor declaration to read, so the only thing that distinguishes
        the halves is where the footage came from, which is the same partition
        `footage_sides()` hands `alternate`.
    """
    pools = {}
    for want in ("a", "b"):
        if anchor_sides and want in anchor_sides:
            i = anchor_sides.index(want)
            cands = matches[i]["candidates"]
        elif sides:
            i = 0
            cands = [c for c in matches[0]["candidates"]
                     if sides.get(c["source"]) == want]
        else:
            continue
        if cands:
            pools[want] = (i, cands)
    return pools


# CF-0689: a `visual_anchors[]` entry that places one of the script's own
# graphics (shared/own_graphic.py ANCHOR_KEY) asks the pool nothing; its
# segment is the graphic, drawn in Remotion, `asset_kind: "own_graphic"`.
GRAPHIC_KEY = "graphic_id"
OWN_GRAPHIC_KIND = "own_graphic"


def is_graphic_anchor(anchor):
    gid = (anchor or {}).get(GRAPHIC_KEY)
    return isinstance(gid, str) and bool(gid.strip())


def graphic_match():
    """The matcher's place for a graphic anchor: nothing asked, nothing
    offered - never read as a hole, its segment is the graphic's."""
    return {"phrase": None, "found": False, "discriminative": True, "margin": None,
            "candidates": [], "graphic": True}


def match_pool_anchors(anchors, indexes, min_score, top, python):
    """`match()` over the anchors that ask the pool, a `graphic_match()` in
    the place of every graphic anchor; no matcher call when none asks."""
    asks = [i for i, a in enumerate(anchors) if not is_graphic_anchor(a)]
    if not asks:
        return [graphic_match() for _ in anchors], {}
    found, index_data = match(indexes, [anchors[i]["phrase"] for i in asks],
                              min_score, top, python)
    out = [graphic_match() for _ in anchors]
    for i, m in zip(asks, found):
        out[i] = m
    return out, index_data


def graphic_block(a, graphics, start, end, seg, prev):
    """CF-0689: the block of a segment a graphic anchor drives. The order is
    copied from the spec's `graphics` unread (None when the script ordered no
    such graphic - build_render_plan.py refuses it). A segment that continues
    the same graphic's previous block carries `graphic_offset`, the seconds
    its animation has already run, so a run the rhythm cut in two is one
    animation on screen rather than the graphic starting over."""
    gid = a[GRAPHIC_KEY].strip()
    offset = 0.0
    if (prev and prev.get("asset_kind") == OWN_GRAPHIC_KIND and prev.get("graphic_id") == gid
            and abs(float(prev["_end"]) - float(start)) < 0.01):
        offset = round(float(prev.get("graphic_offset") or 0.0)
                       + float(prev["_end"]) - float(prev["_start"]), 3)
    graphic = (graphics or {}).get(gid)
    template = graphic.get("template") if isinstance(graphic, dict) else None
    return {
        "word_range": [a["word_index"], a["word_index"]],
        "intent": f"own graphic {gid} ({template or 'not ordered'}) - drawn by the "
                  f"factory from the script's facts (CF-0689)",
        "asset_kind": OWN_GRAPHIC_KIND,
        "graphic_id": gid,
        "graphic": graphic,
        "graphic_offset": offset,
        "emphasis_words": a.get("emphasis_words", []),
        "rhythm_role": seg["role"],
        "side": seg.get("side"),
        "shot": None,
        "held_frame": False,
        "_start": round(start, 3),
        "_end": round(end, 3),
    }


def graphic_shots(seg, driver, anchors, anchor_starts, start, end, opening=False):
    """CF-0923: the graphics one segment shows, as (anchor index, start, end).

    A declared `alternate` makes one swing block per crossing of the axis
    (`rhythm._plan_alternate_declared`), so a run of same-side anchors is one
    segment - and until now one graphic: the driver's, for the whole run,
    while every later graphic the script placed in that run was never drawn.
    Tech 08.11 github: v11 (g11 «distributed version control») and v12 (g12,
    the summing-up card) are both side b, so g11 held the last 10.2 s while
    the narrator moved on to «a bootstrapped start-up became a Microsoft
    subsidiary»; v1/v2 (side a) lost g2 the same way.

    CF-0120 already lets a swing block be cut from several distinct pictures
    without moving its boundary; a graphic is one more picture. So inside a
    swing segment each graphic anchor takes over at its own word (less
    LEAD_SECONDS, as every boundary does), and a piece shorter than
    rhythm.MIN_SWING_CUT_SECONDS is folded into its longer neighbour - the
    graphic of the longer span stays, the picture follows the most of the
    speech. Any other role (`hold`'s held frame, `staccato`'s and `even`'s
    one picture per segment) keeps its single driver graphic, as before.

    `opening` (the segment the video starts with): its first graphic is the
    hook's and is never folded away. Shorter than the floor, it holds the
    floor at the next piece's expense; a short neighbour folds into it, not
    the other way round (github 08.11: g1 «launched April 2008» 0-1.6 s, then
    g2). Pure.
    """
    if seg.get("role") != "swing" or len(seg.get("anchors") or []) < 2:
        return [(driver, start, end)]
    group = [i for i in seg["anchors"] if i >= driver and is_graphic_anchor(anchors[i])]
    pieces = []
    for i in group:
        t = start if i == driver else min(end, max(start, anchor_starts[i] - LEAD_SECONDS))
        gid = anchors[i][GRAPHIC_KEY].strip()
        if pieces and pieces[-1][3] == gid:
            continue
        if pieces:
            pieces[-1][2] = t
        pieces.append([i, t, end, gid])
    pieces = [p for p in pieces if p[2] - p[1] > 1e-6]
    floor = rhythm.MIN_SWING_CUT_SECONDS
    hook = opening and bool(pieces) and pieces[0][0] == driver
    if hook and len(pieces) > 1 and pieces[0][2] - pieces[0][1] < floor - 1e-9:
        cut = min(end, pieces[0][1] + floor)
        pieces[0][2] = cut
        while len(pieces) > 1 and pieces[1][2] <= cut + 1e-6:
            pieces[0][2] = max(cut, pieces[1][2])
            del pieces[1]
        if len(pieces) > 1:
            pieces[1][1] = pieces[0][2]
    while len(pieces) > 1:
        k = min(range(len(pieces)), key=lambda j: pieces[j][2] - pieces[j][1])
        if pieces[k][2] - pieces[k][1] >= floor - 1e-9:
            break
        nb = [j for j in (k - 1, k + 1) if 0 <= j < len(pieces)]
        j = max(nb, key=lambda q: pieces[q][2] - pieces[q][1])
        lo, hi = min(j, k), max(j, k)
        keep = 0 if (hook and lo == 0) else j  # the hook's graphic is never folded away
        merged = [pieces[keep][0], pieces[lo][1], pieces[hi][2], pieces[keep][3]]
        pieces[lo:hi + 1] = [merged]
        # two neighbours that now show the same graphic are one piece
        for q in range(len(pieces) - 1, 0, -1):
            if pieces[q][3] == pieces[q - 1][3]:
                pieces[q - 1][2] = pieces[q][2]
                del pieces[q]
    if not pieces:
        return [(driver, start, end)]
    return [(p[0], round(p[1], 3), round(p[2], 3)) for p in pieces]


def driver_anchor(seg, matches):
    """Which anchor of a merged segment supplies the picture.

    For every rhythm but `hold` it is the first: the segment starts at that
    anchor's word, and the whole point of anchoring is that the picture arrives
    with the word. `hold` is the exception because its segment is a passage
    rather than a moment - "the held frame must be worth holding: it is chosen
    for what it shows, not for where it happens to fall in the timeline" - so
    there it is whichever anchor in the group actually found something.
    """
    if seg["role"] != "hold" or len(seg["anchors"]) == 1:
        return seg["anchors"][0]
    def best(i):
        cands = matches[i]["candidates"]
        return max((c["score"] for c in cands), default=-1.0)
    return max(seg["anchors"], key=best)


def _shot_of(data, n):
    for sh in (data or {}).get("shots", []) or []:
        if sh.get("index") == n:
            return sh
    return None


def topic_pool(candidates, index_data, min_score, score_floor, sups=None):
    """CF-0337: what the topic-footage rung may offer a block, in order.

    First the matcher's candidates for this phrase that a floor refused, by
    score - the nearest thing to a picture of the phrase the pool has.
    Then every shot of every index that the matcher did not offer for it,
    source by source (the source whose best candidate scored highest first,
    so the topic's most relevant footage is spent first) and in shot order;
    those carry `score: 0.0` and `unscored: True`, since the matcher never
    measured them against this phrase. `topic_rung` on each says which pool
    it came from. Already-used shots are left in: fill()'s ledger refuses
    them in writing, like everywhere else. Pure.

    CF-0348: `sups` (entity_guard.supplements()) - a supplement source's shot
    that shows neither the topic nor the entity is never offered, however
    empty the block. CF-0351: nor is any shot marked `burned_text: true`. """
    below = sorted((c for c in candidates
                    if below_similarity_floor(c, min_score)
                    or below_score_floor(c, score_floor)),
                   key=lambda c: -c["score"])
    out = [{**c, "topic_rung": "below_floor"} for c in below
           if not entity_guard.refusal(
               c.get("source"), c.get("shot"),
               _shot_of(index_data.get(c.get("index")), c.get("shot")), sups)]
    offered = {(c["index"], c["shot"]) for c in candidates}
    best = {}
    for c in candidates:
        best[c["index"]] = max(best.get(c["index"], -1.0), c["score"])
    for idx in sorted(index_data, key=lambda i: (-best.get(i, -1.0), str(i))):
        data = index_data[idx]
        for sh in data.get("shots", []):
            n = sh.get("index")
            if n is None or (idx, n) in offered:
                continue
            if entity_guard.refusal(data.get("source"), n, sh, sups):
                continue
            try:
                s0, s1 = float(sh["start"]), float(sh["end"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append({"shot": n, "start": s0, "end": s1, "score": 0.0,
                        "card": bool(sh.get("is_card")),
                        "moment_at": sh.get("moment_at"),
                        "index": idx, "source": data.get("source"),
                        "unscored": True, "topic_rung": "topic_pool"})
    return out


# CF-0428: how many of the pool's unused shots the storyboard lists by name.
# The list is what the writer rewrites an anchor onto, so it has to be there;
# capped so a 250-shot pool does not bloat every storyboard.
POOL_CAPACITY_LIST_MAX = 60


def pool_capacity(index_data, sups, blocks, cut_refused, retired_reason,
                  min_short_side, min_coverage, max_black,
                  emergency_repeats=MAX_EMERGENCY_REUSE_PER_VIDEO,
                  reuse_cap=None):
    """CF-0428: the most blocks this pool can put on screen in this video,
    whatever the anchors say. Pure.

    The block count of a storyboard is the number of pictures the resolver
    handed out, and at one sample, one use (CF-0121) a picture is a distinct
    shot. An anchor whose phrase no free shot answers adds *no* block: its
    seconds are carried into a neighbour (CF-0124). So the pace a script can
    reach by editing `visual_anchors` is bounded by the pool, not by the
    anchor count - which is what `example-film/2026-09-28T1126Z` vanguards
    showed: 11 -> 18 anchors, the same 7 blocks, 9.64 blocks/min both times,
    because 16 of the 18 phrases found every free shot refused.

    A shot counts when it passes every gate that does not depend on the
    phrase: the burned-text / supplement screen (CF-0351, CF-0348), the
    cached usability pre-filter (CF-0029/CF-0275), the channel's retired
    shots (CF-0397), and - measured this round - the cut-clip gate: a shot
    whose cut clip `usable()` refused is cut the same way next round
    (`cut_refused`, shot keys). The similarity floor is the phrase's, so it
    is exactly what an anchor edit can move and it is not applied here.

    `emergency_repeats` is CF-0137's one repeat per video; `reuse_cap` is a
    measurement run's `--max-shot-reuse` - with one set, a shot is not one
    block and there is no bound to report (`blocks_max: None`).
    """
    eligible, refused = [], {"burned_text_or_off_entity": 0,
                             "usability_cache": 0, "retired": 0,
                             "cut_clip": 0}
    total = 0
    for idx, data in (index_data or {}).items():
        source = data.get("source")
        stem = Path(str(source)).stem
        for sh in data.get("shots", []) or []:
            n = sh.get("index")
            if n is None:
                continue
            total += 1
            key = (source, n)
            if entity_guard.refusal(source, n, sh, sups):
                refused["burned_text_or_off_entity"] += 1
            elif precut_cache_refusal(sh, min_short_side, min_coverage, max_black,
                                      f"{stem}:{n}"):
                refused["usability_cache"] += 1
            elif retired_reason(key):
                refused["retired"] += 1
            elif key in (cut_refused or ()):
                refused["cut_clip"] += 1
            else:
                try:
                    secs = round(float(sh["end"]) - float(sh["start"]), 2)
                except (KeyError, TypeError, ValueError):
                    secs = None
                eligible.append({"shot": f"{stem}:{n}", "seconds": secs,
                                 "is_card": bool(sh.get("is_card")),
                                 "description": " ".join(
                                     str(sh.get("description") or "").split())[:200]})
    on_screen = {b.get("shot") for b in blocks or [] if b.get("shot")}
    used = [e for e in eligible if e["shot"] in on_screen]
    unused = [e for e in eligible if e["shot"] not in on_screen]
    bounded = reuse_cap is None
    return {
        "shots": total,
        "eligible": len(eligible),
        "refused": refused,
        "used": len(used),
        "emergency_repeats": emergency_repeats if bounded else None,
        # Every eligible shot once, plus the one emergency repeat. An upper
        # bound: the phrases still have to reach each shot over the floor.
        "blocks_max": (len(eligible) + emergency_repeats) if bounded else None,
        "unused": unused[:POOL_CAPACITY_LIST_MAX],
        "unused_listed": min(len(unused), POOL_CAPACITY_LIST_MAX),
        "unused_total": len(unused),
    }


def is_ordered_segment(seg):
    """Whether this segment belongs to an ordered rhythm's cadence.

    `hold`, `staccato` and `alternate` all plan a bounded number of shots per
    block because the boundary is the instruction; `even` leaves the budget
    open (`max_shots: None`) because its boundary was never load-bearing. That
    flag, not the rhythm id, is what the resolver reads everywhere it decides
    whether a boundary may move - so it is the same test here.

    CF-0120 is why the test is "a budget was set" rather than the older
    "`max_shots == 1`": a swing block may now be cut from several distinct
    shots of its side (rhythm.swing_shot_budget()), and its boundary is no
    less the instruction for that - it is still exactly one crossing of the
    script's axis. What separates an ordered segment from an `even` one is
    that somebody decided how many pictures fit, not that the answer was one.
    """
    return seg.get("max_shots") is not None


def unfilled_block(anchor, seg, start, end, reason):
    """The block an ordered rhythm delivers for a segment nothing could fill.

    CF-0085: the block spans exactly what the plan said - the same rule the
    held-frame branch applies to a clip that came out too short. Its length is
    the planner's own (staccato's cap, hold's dwell, alternate's crossing),
    never a new constant, so an unfillable stretch degrades into as many
    bounded blocks as the plan had segments, each one landing on the
    assetless rung `build_render_plan.py` already renders (`procedural`) and
    records in `degraded_blocks`. No side and no shot: to `alternate` that is
    a hole in the alternation, not a swing.
    """
    return {
        "word_range": [anchor["word_index"], anchor["word_index"]],
        "intent": f"{anchor['phrase']} (no usable footage - typographic block, CF-0085)",
        "asset_kind": "typographic",
        "unfilled_reason": reason,
        "emphasis_words": anchor.get("emphasis_words", []),
        "rhythm_role": seg["role"],
        "side": None,
        "shot": None,
        "held_frame": False,
        "_start": round(start, 3),
        "_end": round(end, 3),
    }


# What settle_unresolved() did with a segment nothing could fill. Three
# outcomes rather than a boolean, because each one leaves the caller a
# different job: reset the shot chain, carry the span forward, or nothing.
SETTLED_BLOCK = "block"        # the segment became its own bounded block
SETTLED_CARRY = "carry"        # its span was left for the next anchor to cover
SETTLED_STRETCH = "stretch"    # the previous block was extended over it


def settle_unresolved(blocks, anchor, seg, start, end, reason, has_next):
    """What the block plan keeps for a segment with no picture.

    On an ordered rhythm stretching the previous block is the one thing the
    resolver may not do - the Raygun run (CF-0085) merged 25 consecutive
    unresolved staccato segments into one 31.6s block that way, the opposite of
    the cadence ordered. The segment becomes its own bounded block instead
    (SETTLED_BLOCK), and the caller resets the shot chain, because a block with
    no picture is not the previous shot of anything.

    On `even` the segment has no bounds of its own worth keeping - its
    boundary was never an instruction - so there is nothing to make a block
    out of. What is wrong with the old answer there is not the boundary but
    the picture: stretching the previous block means holding a clip past its
    own footage, which freezes on its last frame with no record of why, and a
    run short of footage merges segment after segment into one such freeze.
    That is the same defect CF-0028 already refused for the smaller case
    (candidates that cover only part of an anchor), and its remedy applies
    unchanged here: hand the span to the next anchor (SETTLED_CARRY), whose
    block then starts early with a real picture in it. The caller sets
    `carry_start`; `prev_shot` stays as it is, because the picture on screen
    across this gap is still the next block's, not a new one.

    Only the last segment has no next anchor to carry into, and coverage may
    not be dropped on the floor - the plan has to reach the end of the voice.
    There the old stretch-and-freeze stands (SETTLED_STRETCH), exactly as
    CF-0028 leaves it for its own shortfall; CF-0011's design session is the
    place to do better than a frozen tail.

    Returns one of SETTLED_BLOCK / SETTLED_CARRY / SETTLED_STRETCH.
    """
    if is_ordered_segment(seg):
        blocks.append(unfilled_block(anchor, seg, start, end, reason))
        return SETTLED_BLOCK
    if has_next:
        return SETTLED_CARRY
    if blocks:
        blocks[-1]["_end"] = round(end, 3)
    return SETTLED_STRETCH


# CF-0480 (DoD 1.5.1 item 1): a one-frame block is not built out of one shot
# stretched past twice its length. vanguards-doomsday 1313Z, refused by the
# user for "stop-frames": 7 of 7 blocks were frames held off one source, shots
# of 1.4-3.3 s standing for 5-9 s (x2.4-x3.9), while 12 eligible shots of the
# same pool stayed unused. When the longest shot the block could take is
# shorter than its stretch by more than `still_share.STRETCH_MIN_RATIO` (and
# the block is longer than `STRETCH_MIN_SECONDS` - the two numbers that make a
# held frame "stretched" in the plan's price, CF-0418), the block takes 2-3
# shots of its own phrase instead: one block, its boundary untouched, a
# `sequence` of cuts whose last picture holds what is left (the swing chain's
# shape, CF-0120). Only the phrase's own screened candidates: a split never
# reaches for a shot of something else. When they do not give a second cut the
# block is held as before and says so (`stretch_split.short`) - the plan
# turns that into "the pool does not hold this video" (build_render_plan.py).
STRETCH_SPLIT_TASK = "CF-0480"
STRETCH_SPLIT_MAX_SHOTS = 3


def stretch_split_wanted(seconds, need, seg=None):
    """CF-0480: the record of a one-frame block whose one cut (`seconds` of
    picture for a `need`-second block) would stand still for more than
    `still_share.STRETCH_MIN_RATIO` times its length - the 2-3 shots the
    block is to take instead (`wanted`) - or None when the block keeps its
    one shot: not a one-frame segment of an ordered rhythm (`max_shots` 1,
    not a swing), a block no longer than `STRETCH_MIN_SECONDS`, or a shot
    long enough."""
    if seg is not None and (not is_ordered_segment(seg) or seg.get("max_shots") != 1
                            or seg.get("role") == "swing"):
        return None
    if seconds <= 0 or need <= still_share.STRETCH_MIN_SECONDS \
            or need <= still_share.STRETCH_MIN_RATIO * seconds:
        return None
    # Past twice the shot, ceil(need / shot) is 3 or more: the most a split
    # takes. fill() stops earlier once the tail is no longer than its cut.
    want = STRETCH_SPLIT_MAX_SHOTS
    return {"task": STRETCH_SPLIT_TASK, "why": "stretched", "need": round(need, 3),
            "first_shot_seconds": round(seconds, 3),
            "ratio": round(need / seconds, 2), "wanted": want}


def soft_hold_wanted(u, need, seg, clips_dir, si):
    """CF-0480 item 2 (CF-0465's proposal "hold only a sharp frame"): the
    record of a one-frame block that is not stretched but would still hold
    its one cut (`u`) as a frame, and that frame reads under
    `held_sharpness.FLOOR` - such a block is cut into 2-3 shots too, so it
    plays them and holds only a tail, on the sharpest of them. None when the
    block is not a one-frame segment, holds nothing, or the frame is sharp
    (or cannot be measured). The probe frame is lifted the way hold_frame()
    lifts it and removed."""
    if seg is not None and (not is_ordered_segment(seg) or seg.get("max_shots") != 1
                            or seg.get("role") == "swing"):
        return None
    seconds = u.get("seconds") or 0.0
    if seconds <= 0 or seconds + rhythm.HELD_FRAME_SLACK_SECONDS >= need:
        return None
    probe = clips_dir / f"s{si:02d}_probe_{Path(u['clip']).stem}.png"
    try:
        value = (held_sharpness.frame_value(str(probe))
                 if hold_frame(u["clip"], seconds, probe, used=dict(u)) else None)
    finally:
        probe.unlink(missing_ok=True)
    if value is None or value >= held_sharpness.FLOOR:
        return None
    return {"task": STRETCH_SPLIT_TASK, "why": "soft_frame", "need": round(need, 3),
            "first_shot_seconds": round(seconds, 3),
            "ratio": round(need / seconds, 2), "wanted": STRETCH_SPLIT_MAX_SHOTS,
            "soft_frame": round(value, 4), "floor": held_sharpness.FLOOR}


def later_first_picks(segments, matches, si, min_score, score_floor):
    """CF-0480: the shots the one-frame segments after `si` would most likely
    take as their one picture - each one's first pick in the order a
    one-shot block sorts its pool (long enough first, then by score) and its
    longest shot. A stretch split does not spend them on its extra cuts:
    on vanguards-doomsday 1313Z (one source, 19 eligible shots for 7 blocks)
    the early blocks' splits otherwise took the 3.0-3.25 s shots the last
    two blocks held, and the pattern's key hold fell to a 1.2 s shot held
    x7.4."""
    out = set()
    for seg in segments[si + 1:]:
        if seg.get("max_shots") != 1 or seg.get("role") == "swing":
            continue
        cands = matches[driver_anchor(seg, matches)]["candidates"]
        pool, _ = screen_pool(cands, min_score, score_floor)
        if not pool:
            continue
        need = seg["end"] - seg["start"]
        first = sorted(pool, key=lambda c: available_seconds(c) < need)[0]
        longest = max(pool, key=available_seconds)
        out.update({(first["source"], first["shot"]),
                    (longest["source"], longest["shot"])})
    return out


# CF-0537 (the user's decision of 2026-10-05, delver 0701Z block 2): a block
# whose every cut at or above the similarity floor is a soft shot
# (`low_sharpness`, warned - the price stays unsigned) takes a sharp shot of
# the same phrase from just under the floor instead, priced
# `score.low_similarity` (-3 a block, signed, CF-0433). "Just under" is the
# lower bound the CF-0536 split already goes on into - `below_floor_pool()`,
# the matcher's own candidates of the phrase, `--score-floor` the only floor
# under them; no new threshold.
SHARP_UNDER_TASK = "CF-0537"


def soft_cut(u):
    """True when the resolver's cut `u` carries `low_sharpness` in its
    storyboard usability record (warned while the price is unsigned, in
    `soft` once signed)."""
    rec = (u or {}).get("usability") or {}
    return shot_score.LOW_SHARPNESS in (list(rec.get("warn") or [])
                                        + list(rec.get("soft") or []))


def measured_sharp(cand, shots_lut):
    """True when the candidate's shot has a fresh sharpness record (stored,
    or measured on the fly by this run's rank) and it is not `low_sharpness`.
    A shot nobody measured is not called sharp - the trade below takes a
    price, and it is paid only for a picture known to be sharper."""
    shot = shots_lut.get((cand.get("index"), cand.get("shot")))
    if not isinstance(shot, dict) or cand.get("card"):
        return False
    video = cand.get("source")
    if shot_score.sharpness_record(shot, video) is None:
        return False
    return shot_score.sharpness_verdict(shot, video) is None


def sharp_under_pool(candidates, min_score, score_floor, shots_lut, skip=()):
    """CF-0537: the phrase's candidates under the similarity floor
    (`below_floor_pool()`, score order) that are measured sharp, minus the
    sample keys in `skip` (this block's cuts, the later one-shot blocks'
    first picks). The best-scoring ones the old pool stored no sharpness for
    are measured on the fly first (`shot_score.probe_unmeasured`: the rank's
    probe count and per-run ceiling, but in score order - the closest
    pictures of the phrase are asked, not only the cleanest ones)."""
    under = [c for c in below_floor_pool(candidates, min_score, score_floor)
             if (c["source"], c["shot"]) not in skip]
    if not under:
        return []
    shot_score.probe_unmeasured(
        under, lambda c: shots_lut.get((c.get("index"), c.get("shot"))),
        lambda c: c.get("source"))
    return [c for c in under if measured_sharp(c, shots_lut)]


def sharpest_last(used, clips_dir, si, need=None, frozen_of=None):
    """CF-0480 item 2 (CF-0465's proposal "hold only a sharp frame"): the cuts
    of a split block, reordered so the one whose held frame reads sharpest is
    the last - the picture the block's tail stands still on. Each cut's frame
    is lifted the way hold_frame() lifts it (the shot's sharpest moment when
    the pool knows it) and measured at once with the plan's own measure
    (`held_sharpness.frame_value`); a frame that cannot be measured counts as
    the softest. Order otherwise kept: the cuts are all pictures of the same
    phrase, ranked by fill(). Only a cut at least as long as the tail it would
    hold is a candidate (with `need`, the block's length) - held, it stands at
    most twice its length; when none is, the longest cut alone (the held
    picture's stretch is (cut + tail) / cut, least for the longest).

    CF-0536: `frozen_of(u)` - True when the frame `u` would hold is a face
    frozen mid-motion (`frozen_frame`) - is asked only for a tail longer than
    `FROZEN_HOLD_MAX_SECONDS`, and a frame that is not frozen goes before the
    sharpness: a sharp face stopped mid-word is the defect the user named.
    Returns `(used, {clip: (png, value)})`."""
    frames = {}
    if len(used) < 2:
        return used, frames
    tail = (need - sum(u["seconds"] for u in used)) if need is not None else 0.0
    if tail <= rhythm.HELD_FRAME_SLACK_SECONDS:
        return used, frames      # nothing will be held
    fit = [u for u in used if u["seconds"] >= tail] or \
        [max(used, key=lambda u: u["seconds"])]
    for u in fit:
        png = clips_dir / f"s{si:02d}_held_{Path(u['clip']).stem}.png"
        if hold_frame(u["clip"], u["seconds"], png, used=u):
            frames[u["clip"]] = (str(png), held_sharpness.frame_value(str(png)))
    def value(u):
        v = (frames.get(u["clip"]) or (None, None))[1]
        return -1.0 if v is None else v
    calm = (lambda u: True) if (frozen_of is None or tail <= FROZEN_HOLD_MAX_SECONDS) \
        else (lambda u: not frozen_of(u))
    fit_ids = {id(u) for u in fit}
    best = max((i for i in range(len(used)) if id(used[i]) in fit_ids),
               key=lambda i: (calm(used[i]), value(used[i]), i))
    if best != len(used) - 1:
        used = used[:best] + used[best + 1:] + [used[best]]
    return used, frames


# CF-0536 (delver 0701Z, rejected 2026-10-05: "неудачный стоп кадр на 15с,
# 21с"): block 3 played its three shots of the phrase (4.99 s of an 11.2 s
# block) and held the last one, a face in the middle of a movement
# (`held_motion` motion 7.43, face 0.087 - CF-0481's frozen frame), for 6.21 s.
# CF-0480 stopped at three shots; `score.held_moving_face` lets 12 s of such
# frames go free per video. Now a split does not stop at three while what is
# left would still be held stretched (still_share's line) or would hold a
# frozen face longer than FROZEN_HOLD_MAX_SECONDS: it takes the phrase's next
# shot, one at a time, up to STRETCH_SPLIT_MAX_SHOTS_LONG; and a one-frame block
# whose one shot would hold a frozen face that long is split like a stretched
# one (`frozen_hold_wanted`). A ranking of this stage, not a price: the pool's
# shots of the same phrase, every gate of fill() as usual; when the pool has
# no more, the block is held as before and the plan prices it.
FROZEN_TASK = "CF-0536"
# The line past which a held frame is "stretched" (still_share, the user's
# line of CF-0418) - a frozen face is not held longer than a frame may stand.
FROZEN_HOLD_MAX_SECONDS = still_share.STRETCH_MIN_SECONDS
STRETCH_SPLIT_MAX_SHOTS_LONG = 6
_FINDERS = {}


def held_motion_probe(u, png):
    """CF-0481's reading of the frame `png` lifted from cut `u`
    (`held_motion.measure_frame` against the cut's own source dir), with
    `frozen` - motion around the moment >= MOTION_MIN and a face >= FACE_MIN."""
    src = Path(str(u["key"][0]))
    d = str(src.parent)
    if d not in _FINDERS:
        _FINDERS[d] = held_motion.source_finder([d])
    rec = held_motion.measure_frame(f"{src.stem}:{u['shot']}", png, _FINDERS[d])
    rec["frozen"] = held_motion.frozen(rec.get("motion"), rec.get("face_area"))
    return rec


def frozen_frame(u, clips_dir, si, cache):
    """The held_motion reading (with `frozen`) of the frame hold_frame() would
    lift from cut `u` - lifted into a probe file, measured and removed; kept
    in `cache` by clip. None when the frame cannot be lifted or measured."""
    if u["clip"] in cache:
        return cache[u["clip"]]
    probe = clips_dir / f"s{si:02d}_mprobe_{Path(u['clip']).stem}.png"
    rec = None
    try:
        if hold_frame(u["clip"], u["seconds"], probe, used=dict(u)):
            rec = held_motion_probe(u, str(probe))
    except Exception:  # noqa: BLE001 - an unmeasured frame is not found frozen
        rec = None
    finally:
        probe.unlink(missing_ok=True)
    cache[u["clip"]] = rec
    return rec


def frozen_hold_wanted(u, need, seg, clips_dir, si, cache):
    """CF-0536: the split record of a one-frame block that is neither
    stretched nor soft but would hold its one cut (`u`) for more than
    FROZEN_HOLD_MAX_SECONDS on a frame that is a face frozen mid-motion -
    such a block is cut into shots of its phrase too. None otherwise."""
    if seg is not None and (not is_ordered_segment(seg) or seg.get("max_shots") != 1
                            or seg.get("role") == "swing"):
        return None
    seconds = u.get("seconds") or 0.0
    if seconds <= 0 or need - seconds <= FROZEN_HOLD_MAX_SECONDS:
        return None
    rec = frozen_frame(u, clips_dir, si, cache)
    if not (rec or {}).get("frozen"):
        return None
    return {"task": STRETCH_SPLIT_TASK, "why": "frozen_frame", "need": round(need, 3),
            "first_shot_seconds": round(seconds, 3),
            "ratio": round(need / seconds, 2), "wanted": STRETCH_SPLIT_MAX_SHOTS,
            "frozen_by": FROZEN_TASK,
            "held_motion": {"motion": rec.get("motion"), "face_area": rec.get("face_area")}}


def split_wants_more(used, need, frozen_of=None):
    """CF-0536: why a split with the cuts `used` (seconds each) still wants
    the phrase's next shot - `"stretched"`: no cut is as long as what is left,
    so the held one would stand past twice its length and FROZEN_HOLD_MAX
    seconds (still_share's line); `"frozen"`: what is left is longer than
    FROZEN_HOLD_MAX_SECONDS and every cut long enough to hold it holds a face
    frozen mid-motion (`frozen_of(u)`); None when the tail may be held (or
    nothing is held)."""
    tail = need - sum(u["seconds"] for u in used)
    if not used or tail <= rhythm.HELD_FRAME_SLACK_SECONDS:
        return None
    longest = max(u["seconds"] for u in used)
    if tail > longest:
        return "stretched" if still_share.stretched(longest + tail, longest) else None
    if tail <= FROZEN_HOLD_MAX_SECONDS or frozen_of is None:
        return None
    fit = [u for u in used if u["seconds"] >= tail]
    return "frozen" if all(frozen_of(u) for u in fit) else None


def hold_frame(clip, seconds, dest, used=None):
    """Lift one frame out of a clip so an ordered rhythm can hold it.

    Not a degradation: the block asked for a frame that stays, and CF-0031's
    chain is about assets that failed a gate. The block records `held_frame`
    so `05-video-editor.json` can tell the two apart - without it a `hold`
    video would read downstream as a motion video that lost most of its
    footage.

    CF-0452: `used` is the cut the frame is lifted from. When its shot has a
    fresh sharpness record (`used["sharpness"]`, pool or on-the-fly) with a
    `best_at`, the frame is the shot's sharpest moment, not the middle of the
    clip (day-drinker's bhKKR5He_Fo:21 was held at 0.524, its best moment
    0.728): from the clip when the moment is inside it, else from a short
    snippet of the source cut at that moment with the clip's own caption crop.
    `used["held_from"]` records where; any failure falls back to the old frame.
    """
    best = shot_score.held_moment(used)
    if best is not None:
        at, value = best
        origin = held_at_best(clip, seconds, dest, used, at)
        if origin:
            used["held_from"] = {"task": shot_score.SHARPNESS_TASK,
                                 "at": round(at, 3), "sharpness": value,
                                 "from": origin}
            print(f"  HELD AT SHARPEST {Path(dest).name}: shot {used.get('shot')} "
                  f"held at {at:.2f}s (sharpness {value}) from the {origin} "
                  f"(CF-0452)", file=sys.stderr)
            return True
    # CF-0536: no record of the shot's sharpest moment - its calmest frame,
    # not the middle of the clip (delver 0701Z held a face mid-motion).
    calm = calm_moment(clip)
    if calm is not None and grab_frame(clip, calm, dest):
        if isinstance(used, dict):
            used["held_calm"] = {"task": FROZEN_TASK, "at": calm}
        print(f"  HELD AT CALMEST {Path(dest).name}: shot {(used or {}).get('shot')} "
              f"held at {calm:.2f}s into its clip (CF-0536)", file=sys.stderr)
        return True
    return grab_frame(clip, max(0.2, seconds / 2), dest)


def calm_moment(clip):
    """CF-0536: `held_motion.calmest_moment(clip)` (a hook the tests stub)."""
    return held_motion.calmest_moment(clip)


# CF-0452: a best moment this close to the clip's end is lifted from the
# source instead - a seek to the last frame of a clip can come back empty.
HELD_CLIP_END_MARGIN = 0.05
HELD_SNIPPET_SECONDS = 0.5


def held_at_best(clip, seconds, dest, used, at):
    """Lift the frame at source second `at` for hold_frame(): `"clip"` or
    `"source"` for where it came from, None when neither worked."""
    cut_at = used.get("cut_at")
    if (isinstance(cut_at, (int, float)) and cut_at <= at
            and at - cut_at < seconds - HELD_CLIP_END_MARGIN):
        return "clip" if grab_frame(clip, round(at - cut_at, 3), dest) else None
    source = used.get("source") or (used.get("key") or (None,))[0]
    if not source:
        return None
    snippet = Path(dest).with_name(Path(dest).stem + "_best.mp4")
    try:
        applied = cut(source, at, HELD_SNIPPET_SECONDS, str(snippet),
                      used.get("crop_bottom", 0.0), card=bool(used.get("card")))
        return "source" if (applied is not None and grab_frame(str(snippet), 0, dest)) else None
    finally:
        snippet.unlink(missing_ok=True)


def held_usability(u, held):
    """CF-0452: the usability record of a block that holds `u` as a frame.
    A frame lifted at the shot's sharpest moment is judged again as a held
    frame (`sharpness.verdict(held=True)`) - its low_sharpness can go (or
    come) with it. Otherwise the cut's own record."""
    if not held or not u.get("held_from"):
        return u.get("usability")
    verdict = shot_score.sharpness_verdict(None, held=True, rec=u.get("sharpness"))
    return shot_score.with_sharpness(u.get("usability"), verdict)


def band_cap_entry(si, budget, shots, start, end, held_start, u, held, kind):
    """One segment the drawn block-count ceiling budgeted (CF-0370).

    `start`/`end` are the segment's stretch as it was filled; `held_start` is
    where its last block begins - the block the budget made stand to the end.
    `held_seconds` is how long a held frame stands there (the whole of that
    block: the frame is lifted out of the clip and replaces it), 0 when the
    clip was long enough to play the block out. `hold_failed` is the one case
    the hold could not be made - the frame grab failed, the block stays a clip
    shorter than itself, and CF-0031's QC is what will see it.
    """
    last_len = float(end) - float(held_start)
    return {
        "segment": si,
        "budget": budget,
        "shots": shots,
        "start": round(start, 3),
        "end": round(end, 3),
        "last_shot": f"{Path(u['key'][0]).stem}:{u['shot']}",
        "last_clip_seconds": round(float(u["seconds"]), 3),
        "last_block_seconds": round(last_len, 3),
        "held_frame": bool(held),
        "held_seconds": round(last_len, 3) if held else 0.0,
        "hold_failed": (kind == "clip" and float(u["seconds"])
                        + rhythm.HELD_FRAME_SLACK_SECONDS < last_len),
    }


def band_cap_note(c):
    """The RUN_LOG line for one budgeted segment (CF-0370)."""
    how = (f"its last picture ({c['last_shot']}, a {c['last_clip_seconds']}s clip) "
           f"holds a frame for {c['held_seconds']}s" if c["held_frame"] else
           f"its last picture ({c['last_shot']}) plays the {c['last_block_seconds']}s "
           f"block out" + (" - the frame grab FAILED, the clip is shorter than "
                           "its block and will freeze" if c["hold_failed"] else ""))
    return (f"segment {c['segment']}: budgeted to {c['budget']} shot(s) under the "
            f"pattern's drawn block-count top - {c['shots']} cut, and {how} "
            f"instead of chaining another shot (CF-0370)")


def block_band_report(top, pattern, segments, blocks, caps):
    """The storyboard's `rhythm.block_band_cap` record (CF-0370), or None
    when no drawn block-count ceiling applied.

    Written whole on every plan the ceiling applied to, capped segments or
    not: "the chain fitted under the top without a hold" is the ordinary
    answer and the one `build_render_plan.py`'s refusal text has to be able to
    tell from "this storyboard predates the budget". `layout_over_top_by` is
    the case the budget cannot answer - more segments than the top, one
    picture each already - and it is a number, not a sentence.
    """
    if top is None:
        return None
    band = ((pattern or {}).get("parameters") or {}).get("block_count") or {}
    return {
        "pattern_id": (pattern or {}).get("pattern_id"),
        "band_min": band.get("min"),
        "band_max": top,
        "segments": len(segments),
        "blocks": len(blocks),
        "over_top_by": max(0, len(blocks) - top),
        "layout_over_top_by": max(0, len(segments) - top),
        "capped_segments": caps,
        "held_frames": sum(1 for c in caps if c["held_frame"]),
        "hold_failed": [c["segment"] for c in caps if c["hold_failed"]],
    }


# CF-0106: how far ahead of a shot's `moment_at` the clip starts. The mark is
# the frame the describer meant ("the card, once it appears"); a cut that
# lands exactly on it opens dead, so the moment sits near the head of the
# window but not on its first frame. The lead is the same 0.35s the anchor
# timing already uses - the eye arriving before the thing it is there to see -
# rather than a second, unrelated number.
MOMENT_LEAD_SECONDS = LEAD_SECONDS


class MomentOutOfBounds(ValueError):
    """A shot's `moment_at` lies outside the shot itself.

    match_anchors.py refuses such an index before CLIP runs, so a candidate
    carrying one never reaches this script through the matcher; this is the
    belt for a future caller that skips it. Rejected, never clamped - a mark
    outside its shot is an index inconsistency, and quietly cutting from the
    head would hide it behind a clip that shows the wrong thing.
    """


def moment_of(cand):
    """The candidate's `moment_at` (absolute source seconds), validated, or
    None when the shot carries no mark - absent and null both mean "cut from
    the head", exactly as before CF-0106."""
    mark = cand.get("moment_at")
    if mark is None:
        return None
    where = f"shot {cand.get('shot')} of {Path(str(cand.get('source', '?'))).name}"
    try:
        mark = float(mark)
    except (TypeError, ValueError):
        raise MomentOutOfBounds(
            f"{where}: moment_at={mark!r} is not a timecode in seconds (CF-0106)")
    if not (cand["start"] <= mark <= cand["end"]):
        raise MomentOutOfBounds(
            f"{where}: moment_at={mark:.2f}s lies outside the shot "
            f"[{cand['start']:.2f}, {cand['end']:.2f}] - the index is "
            f"inconsistent, match_anchors.py should have refused it (CF-0106)")
    return mark


def cut_start(cand):
    """Where in the source this candidate's clip starts, and why.

    Returns `(seconds, origin)` with origin `"head"` (no mark: the shot's own
    `start`, as it always was) or `"moment"` (MOMENT_LEAD_SECONDS ahead of
    the mark, clamped to the shot's head when the mark sits closer to it than
    the lead). The window never leaves the shot: its end is the shot's `end`
    at most, which is what `available_seconds()` hands the span rules.
    Raises MomentOutOfBounds for a mark outside the shot.
    """
    mark = moment_of(cand)
    if mark is None:
        return cand["start"], "head"
    return max(cand["start"], mark - MOMENT_LEAD_SECONDS), "moment"


def available_seconds(cand):
    """How much of the shot lies after the cut point - the "is it long
    enough" number every span rule and every long-enough-first sort used to
    read off `end - start`. A candidate with an invalid mark counts as 0 here
    so a sort key never raises; the cut itself then rejects it with the real
    error."""
    try:
        at, _ = cut_start(cand)
    except MomentOutOfBounds:
        return 0.0
    return cand["end"] - at


# The shortest clip this stage will cut. A block filled with anything under it
# is a flash, not a picture. Named (CF-0140) rather than left inline in the two
# places that used to compare against it, because the coverage preflight asks
# the same question and a second copy of the number is how CF-0003 happened.
MIN_CUT_SECONDS = 0.7

# CF-0140: the two causes of the CF-0139 shortage vocabulary
# (`rotation/shortage.py::CAUSES`) that this stage can be the reason for. Named
# here, on the gate that produces them, so anchor_coverage.py reports the same
# words the rotation already reads instead of inventing a third list.
#
#   no_footage       nothing in the pool answers this anchor at all - the
#                    matcher offered no candidate.
#   footage_unusable a frame exists and cannot be taken. Everything
#                    precut_refusal() below can say is of this kind: a mark
#                    outside its shot, a shot too short to cut, a shot the
#                    cached usability condemns.
CAUSE_NO_FOOTAGE = "no_footage"
CAUSE_FOOTAGE_UNUSABLE = "footage_unusable"


def precut_refusal(cand, shot, min_short_side, min_coverage, max_black,
                   need=None, covered=0.0, budget=None):
    """Every refusal a candidate can earn *before* anything is cut.

    Extracted (CF-0140) from main()'s `fill()`, which is the only place these
    three checks ever lived, and it is now the only place they live at all -
    `cut_usable()` asks it, and so does the coverage preflight
    (`anchor_coverage.py`). That is the whole point of the extraction: the
    preflight's answer to "can the pool show this anchor" has to be the *same
    judgement* the resolver will make an hour later, and two copies of a rule
    are two rules. A preflight that judged more leniently would pass a script
    straight into the hole it exists to prevent.

    What it does *not* cover, deliberately, is everything that is a fact about
    this video rather than about this candidate: the reuse ledger, the
    side-by-side opening's spent frames, the swing rules, and the real
    `usable()` on the cut clip - which needs the clip, and therefore ffmpeg and
    the source file. So this is the largest question that can be answered from
    an index alone, and no more. `anchor_coverage.py` says so in its own
    docstring rather than implying its verdict is the whole verdict.

    `need` / `covered` / `budget` are the block's, and the span formula is
    here rather than at the two call sites for the same reason the checks are.
    `need=None` asks the block-free question - the longest cut this candidate
    could give anywhere - which is what the preflight has to ask, since before
    TTS there are no blocks yet.

    Returns `(at, origin, span, refusal)`. `refusal` is None when the candidate
    is still standing; otherwise a dict of:

      cause   one of CAUSE_* above, for the CF-0139 record;
      record  the fields the caller merges into its `rejected_candidates`
              entry, beside its own `phrase` and `shot`;
      log     the stderr line this refusal owes the run log, or None.

    On a refused mark `at`/`origin`/`span` are all None: there is no cut point.
    """
    try:
        at, origin = cut_start(cand)
    except MomentOutOfBounds as e:
        # CF-0106: a mark outside its shot is refused in writing, never
        # clamped - see MomentOutOfBounds.
        return None, None, None, {
            "cause": CAUSE_FOOTAGE_UNUSABLE,
            "record": {"reason": f"moment_at rejected: {e}",
                       "moment_at": cand.get("moment_at")},
            "log": f"MOMENT REJECTED: {e}"}
    avail = cand["end"] - at
    if need is None:
        span = avail
    else:
        span = (min(need, avail) if budget == 1
                else min(avail, need - covered + 0.5))
    if span < MIN_CUT_SECONDS:
        return at, origin, span, {
            "cause": CAUSE_FOOTAGE_UNUSABLE,
            "record": {"score": cand["score"],
                       "reason": f"would cut to {span:.2f}s - too short to read"},
            "log": None}
    cached_reason = precut_cache_refusal(shot, min_short_side, min_coverage, max_black,
                                         _shot_name(cand))
    if cached_reason:
        # Cached usability (CF-0029) says this shot is doomed - skip it before
        # paying for cut() at all. Never the deciding check: the candidate that
        # actually gets cut still goes through the real usable() gate on its
        # own clip.
        #
        # CF-0275: `cached_reason` is the sentence, not a bare bool, because
        # there are now two cached refusals and they send an operator to two
        # different places - a dark or low-res shot is the pool's problem, a
        # `text_cut_by_crop` one is this video's framing showing somebody
        # else's half-cut words. No stderr line for either: the pre-filter
        # runs over every candidate of every anchor, so the same shot would be
        # announced a dozen times per video. Both land in
        # `rejected_candidates` and in the coverage preflight's `refusals[]`,
        # which is where a per-block question is asked from.
        return at, origin, span, {
            "cause": CAUSE_FOOTAGE_UNUSABLE,
            "record": {"score": cand["score"], "reason": cached_reason},
            "log": None}
    return at, origin, span, None


# CF-0517, the user's decision of 2026-10-04 (22:25): length leads a one-shot
# block's walk only among shots at least this usable (the viewer's usability
# score, 0..1). A long shot under it is ranked the ordinary way, with the
# short ones - so a long shot priced near zero (the corpus's case:
# vanguards-endgame-encore 2210Z, block 17, a 0.0 shot over a 0.98 one) no
# longer beats a clean short one. A threshold of this stage's own order, not a
# channel price: the soft prices themselves live in shared/gate-prices.json.
LENGTH_LEAD_MIN_USABILITY = 0.5


# CF-0648 (delver 1824Z, block 7 - the user's "мыльный растянутый кадр" at
# 18 s): a one-shot block that cannot be split (a swing, an `even` block, a
# block too short to split, CF-0480's own conditions) shows a short shot as a
# frame held still for the whole block. Two thresholds of this stage's order
# (not prices) let the walk prefer motion there -
#
# MILD_BLUR_LEAD_FROM - a long-enough shot found `low_sharpness` at or above
#   this keeps its length lead over the short ones. Calibrated on the moving
#   clips the factory has shown under the 0.57 floor: the user's "экранка"
#   (CF-0537, delver 0701Z block 1) read 0.5099 and the soft clip of delver
#   1824Z (24 s) is the same scope trailer; accepted videos carry moving
#   clips at 0.5582 (vanguards-endgame 0701Z) and 0.55-0.5688 (spire-runner
#   1313Z / 1748Z / 2210Z, coach-hale 1748Z, weekend-night-live 1825Z).
# ANCHOR_MATCH - the share of the phrase's words (stop words out) found in a
#   shot's description at or over which the shot IS the anchor's picture: the
#   writer composes `visual_anchors` from the pool's descriptions, and on the
#   batches 1824Z / 1208Z the anchor's own shot reads 1.0 (or 0.92 for a
#   lightly reworded one) while the next best reads 0.2-0.8. Such a short
#   shot keeps its place ahead of a mildly blurry long one - "заметно лучше
#   по смыслу": delver block 7's anchor wIM1PDRvKSE:21 ("a man in a decorated
#   military uniform speaks") over ZLXL1L0TfsI's talk-show host.
MILD_BLUR_LEAD_FROM = 0.55
ANCHOR_MATCH = 0.9
_ANCHOR_STOP = frozenset(
    "a an the of in on at to with and or his her their its is are by from for "
    "into as near over under while".split())


def _anchor_words(text):
    return {t for t in re.findall(r"[a-z0-9']+", str(text or "").lower())
            if t not in _ANCHOR_STOP}


def anchor_match(phrase, description):
    """CF-0648: the share of `phrase`'s words found in `description` (0..1),
    stop words out. 1.0 when the phrase was written from that description."""
    p = _anchor_words(phrase)
    return len(p & _anchor_words(description)) / len(p) if p else 0.0


def split_reachable(seg, need, args=None):
    """CF-0648: whether a one-shot block's short shot would be cut into a
    stretch split (CF-0480) rather than held still for the whole block -
    stretch_split_wanted()'s conditions on the segment and the block."""
    if args is not None and getattr(args, "no_stretch_split", False):
        return False
    if seg is not None and (not is_ordered_segment(seg) or seg.get("max_shots") != 1
                            or seg.get("role") == "swing"):
        return False
    return need > still_share.STRETCH_MIN_SECONDS


def rank_by_usability(pool, shots_lut, place=False, need=None, phrase=None,
                      held_whole=False):
    """CF-0435: `pool` with the clean shots first and the weak ones behind
    them by their usability score (`shot_score.rank()`), stable - so among
    equally usable shots the order the caller gave (similarity, length) holds.
    A weak shot is not dropped: when nothing cleaner survives the gates it is
    the one cut, and the plan prices it. A cache the running code did not
    measure is ranked on the describer's flags alone (CF-0048).

    CF-0352: `place` - the anchor is a view of a place - ranks its own
    candidates' faceless shots without `low_framing` (`wide_candidate`).

    CF-0517: `need` - the block's seconds, given by a one-shot block - puts
    length before usability: every shot long enough for the block
    (`available_seconds() >= need`) goes ahead of every shorter one, and
    usability orders each group. A short clean shot no longer wins over a
    long, slightly weaker one and leaves the block holding a frame; with no
    long-enough shot in the pool the order is the usability one. Hard shots
    stay last (`shot_score.rank(lead=)`), and a long shot under
    LENGTH_LEAD_MIN_USABILITY does not lead - it ranks with the short ones.

    CF-0648: `held_whole` - the one-shot block cannot be split, so a short
    shot would be a frame held for the whole block - lets a mildly blurry
    long shot keep its lead (MILD_BLUR_LEAD_FROM) and puts the anchor's own
    short shot (`phrase` vs the shot's description, ANCHOR_MATCH) ahead of
    it (`shot_score.rank(mild_from=, pinned=)`)."""
    def fresh(shot):
        cached = shot.get("usable_cached")
        return bool(cached) and not _stale_cache(cached)
    # CF-0452: `video_of` lets the rank measure the sharpness of its top
    # candidates on the fly when the old pool stored none (SHARPNESS_PROBES_
    # PER_RANK of them, SHARPNESS_PROBES_PER_RUN per run), and a blurry shot
    # drops behind a sharp one of its score.
    return shot_score.rank(
        pool, lambda c: shots_lut.get((c.get("index"), c.get("shot"))),
        fresh_of=fresh, video_of=lambda c: c.get("source"),
        wide_of=(lambda c: wide_candidate(c, place)),
        lead=(None if need is None else (lambda c: available_seconds(c) < need)),
        lead_floor=None if need is None else LENGTH_LEAD_MIN_USABILITY,
        mild_from=MILD_BLUR_LEAD_FROM if (need is not None and held_whole) else None,
        pinned=(_anchor_of(phrase, shots_lut)
                if (need is not None and held_whole and phrase) else None))


def _anchor_of(phrase, shots_lut):
    """CF-0648: `cand -> bool`, the candidate's shot is the anchor's own
    picture (`anchor_match(phrase, description) >= ANCHOR_MATCH`)."""
    def pinned(c):
        shot = shots_lut.get((c.get("index"), c.get("shot"))) or {}
        return anchor_match(phrase, shot.get("description")) >= ANCHOR_MATCH
    return pinned


def wide_candidate(cand, place):
    """CF-0352: True when `cand` is a picture of a place anchor - the
    anchor's own match, not a topic-rung stand-in (`below_floor`,
    `topic_pool`: not a picture of the phrase, so not of the place)."""
    return bool(place) and not cand.get("topic_rung")


def wide_record(weak, wide_seen):
    """CF-0352: the storyboard record of a cut whose `coverage` failure was
    waived as a wide view of a place - `wide_place.mark()`'s warning on top
    of `weak` (record()'s, or None). `weak` unchanged when nothing was."""
    if not wide_seen:
        return weak
    cov = min(c for c, _ in wide_seen)
    return wide_place.mark(weak, cov, wide_seen[0][1])


def report_moment_cut(dest, cand, at, span):
    """The stderr line for a clip cut from a mark - the same shape as the
    `QC CROP LOSS` / `RHYTHM:` lines, so RUN_LOG shows from which point the
    clip was taken and why, next to everything else it says about it."""
    mark = cand["moment_at"]
    clamped = " - clamped to the shot's head" if at <= cand["start"] else ""
    print(f"  CUT FROM MOMENT {Path(dest).name}: moment_at={mark:.2f}s in shot "
          f"[{cand['start']:.2f}, {cand['end']:.2f}] -> clip [{at:.2f}, "
          f"{at + span:.2f}] (lead {MOMENT_LEAD_SECONDS}s{clamped})",
          file=sys.stderr)


def cut_provenance(cand, at, origin):
    """The storyboard's record of where the clip was cut from (CF-0106):
    `cut_at` is the absolute source timecode the clip starts at, `cut_origin`
    says whether that is the shot's head or its mark, `moment_at` is the mark
    itself (null without one). Carried onto the block so the frame a
    `comparison.checks[]` entry stands on can be traced to the frame that was
    actually cut, not to the head of the shot it was matched in."""
    return {"cut_at": round(at, 3), "cut_origin": origin,
            "moment_at": cand.get("moment_at") if origin == "moment" else None}


def cut_usable(cand, need, dest, shots_lut, args, place=False):
    """Cut one candidate and gate it. Returns a `used` record, or None.

    The single-candidate core of main()'s `fill()`, factored out (CF-0050) so
    the `side_by_side` opening can resolve its two halves before the block loop
    starts - it has to know whether *both* sides survived the gate before it can
    say which opening this video is delivering, and contrast.json is explicit
    that one unresolved side means the opening is not built at all.

    Deliberately without the adjacent-pair rules: those are about a sequence of
    blocks, and this is one frame containing two pictures. The reuse cap is not
    in that exemption - it never was for the two sides of one comparison
    (comparing a thing with itself states no axis) and since CF-0075 cut each
    side to several distinct shots it is not for a side's own sequence either.
    The caller asks `rhythm.ShotLedger` before it gets here; this function only
    cuts and gates what it is handed.
    """
    shot = shots_lut.get((cand["index"], cand["shot"]))
    # CF-0140: one gate, three callers - see precut_refusal(). `budget=1` is
    # this path's span rule (`min(need, avail)`), unchanged.
    at, origin, span, refusal = precut_refusal(
        cand, shot, args.min_short_side, args.min_coverage, args.max_black,
        need=need, budget=1)
    if refusal:
        if refusal["log"]:
            print(f"  {refusal['log']}", file=sys.stderr)
        return None
    crop_bottom = shot.get("crop_bottom_cached") if shot else None
    if origin == "moment":
        report_moment_cut(dest, cand, at, span)
    applied = cut(cand["source"], at, span, str(dest), crop_bottom,
                  card=bool(cand.get("card")))
    if applied is None:
        return None
    soft = []
    wide = [] if wide_candidate(cand, place) else None   # CF-0352
    ok, _ = usable(str(dest), span, args.min_short_side, args.min_coverage,
                   args.max_black, card=bool(cand.get("card")), crop=applied,
                   soft_out=soft, wide_out=wide)
    if not ok:
        Path(dest).unlink(missing_ok=True)
        return None
    weak = shot_score.record(shot, soft, video=cand["source"])  # CF-0435/0452
    weak = wide_record(weak, wide)
    # CF-0452: the shot's fresh sharpness record, as the rank found it - a
    # held frame of this cut is taken at its `best_at` (hold_frame()).
    sharp = shot_score.sharpness_record(shot, cand["source"])
    return {"clip": str(dest), "shot": cand["shot"], "source": cand["source"],
            "key": (cand["source"], cand["shot"]), "score": cand["score"],
            "seconds": round(span, 2), "card": bool(cand.get("card")),
            **cut_provenance(cand, at, origin), **applied,
            **({"usability": weak} if weak else {}),
            **({"sharpness": sharp} if sharp else {})}


def split_cut_record(c):
    """One picture of a `side_by_side` half as the storyboard carries it
    (CF-0075): the same fields a single-asset block records for its clip,
    plus `at` - where in the block it starts - and `seconds` on screen."""
    return {"asset": c["asset"], "kind": c["kind"], "held_frame": c["held_frame"],
            "shot": f"{Path(c['source']).stem}:{c['shot']}", "score": c["score"],
            "at": c["at"], "seconds": c["seconds"], "is_card": c["card"],
            "crop_bottom": c.get("crop_bottom", 0.0),
            "frame_before_crop": c.get("frame_before_crop"),
            "cut_at": c.get("cut_at"), "cut_origin": c.get("cut_origin", "head"),
            "moment_at": c.get("moment_at"),
            # CF-0435: a weak picture's soft rules, priced by the plan.
            **({"usability": c["usability"]} if c.get("usability") else {}),
            # CF-0452: a held frame lifted at the shot's sharpest moment.
            **({"held_from": c["held_from"]}
               if c.get("held_frame") and c.get("held_from") else {})}


def discard_halves(halves):
    """Delete every file cut for an opening that is not being built."""
    for h in halves:
        for c in h["cuts"]:
            Path(c["clip"]).unlink(missing_ok=True)
            if c["asset"] != c["clip"]:
                Path(c["asset"]).unlink(missing_ok=True)


def build_split_opening(anchors, matches, shots_lut, pools, clips_dir, seg, args,
                        ledger=None):
    """Resolve both halves of a `side_by_side` opening, or neither.

    Returns a list of two half records, or an empty list - there is no such
    thing as a half-built side-by-side. patterns/contrast.json states the rule
    ("Needs both sets to have resolved footage; if either side is unresolved
    this opening cannot be built and the block falls back to hook_over_footage")
    and this is where it is carried out; the clips cut for a lone surviving side
    are deleted rather than left behind for a montage that will not use them.

    No shot appears twice in the opening - not on the other side, not later on
    the same side, and not later in the body either. A comparison of a thing
    with itself states no axis, and the same sample twice is not a cut
    (CF-0074's rule). `ledger` is `rhythm.ShotLedger`, the one place that
    answers "has this sample been shown". This function never writes to the one
    it is handed: it resolves against a `fork()`, because an opening that turns
    out not to be deliverable - or a cut trimmed away below because the other
    side ran out first - was never on screen and must not count as a use.
    main() takes the *delivered* cuts on the real ledger afterwards, and that
    is what keeps the body off the opening's samples.

    CF-0075: a half is no longer one picture for the whole block. The block is
    laid over the script's first run, which on `wren-hollow-lockhart` was
    12.12s against clips of 1.09s and 3.8s, and holding a frame for the
    difference put a motionless split on screen for the whole opening. Each
    side now plays its distinct clips back to back (`cuts`), holds its last
    frame for at most rhythm.OPENING_MAX_STATIC_SECONDS, and the opening ends
    where the first side runs out of both - rhythm.opening_length() decides
    that. `seconds` on every half is the opening's length; what is left of the
    run goes back to the ordinary block chain in main().
    """
    run = seg["end"] - seg["start"]
    # No ledger given: a caller resolving an opening on its own still gets the
    # rule inside the opening (what the local `taken` set used to do), because
    # a fresh ledger reads the same cap.
    ledger = (ledger if ledger is not None
              else ShotLedger(getattr(args, "max_shot_reuse", None))).fork()
    halves = []
    for side in ("a", "b"):
        if side not in pools:
            continue
        ai, cands = pools[side]
        # CF-0290: the similarity floor is a gate here too. A side of a
        # comparison filled with a frame that depicts neither thing states no
        # axis, and this path reaches cut_usable() without passing main()'s
        # screen. A side left with nothing above the floor simply does not
        # resolve, and `len(halves) < 2` below is contrast.json's own answer to
        # that: the opening is not built at all and the block falls back to
        # hook_over_footage.
        cands, _ = screen_pool(cands, getattr(args, "min_score", DEFAULT_MIN_SCORE),
                               getattr(args, "score_floor", None))
        # Long enough to finish the run first, then by the order the matcher
        # gave them - one clip that carries the run beats two that have to be
        # joined, and a run nothing carries is still started by the best match.
        cands = sorted(cands, key=lambda c: available_seconds(c) < run)
        # CF-0435: clean before weak, the order above kept among equals.
        place = wide_place.is_place_anchor(matches[ai].get("phrase"))  # CF-0352
        cands = rank_by_usability(cands, shots_lut, place)
        cuts, covered = [], 0.0
        for cand in cands:
            if covered >= run:
                break
            key = (cand["source"], cand["shot"])
            if ledger.blocked(key):
                continue
            dest = (clips_dir /
                    f"open_{side}_{Path(cand['source']).stem}_s{cand['shot']:03d}.mp4")
            # CF-0352: `place` only when it is one, so a stand-in for this
            # function with the old signature still answers every other side.
            u = cut_usable(cand, run - covered, dest, shots_lut, args,
                           **({"place": True} if place else {}))
            if not u:
                continue
            ledger.take(key)
            cuts.append({**u, "kind": "clip", "asset": u["clip"], "held_frame": False,
                         "at": round(covered, 3)})
            covered += u["seconds"]
        if cuts:
            halves.append({"side": side, "anchor": ai, "cuts": cuts,
                           "motion_seconds": round(covered, 3),
                           "phrase": matches[ai]["phrase"]})
    if len(halves) < 2:
        discard_halves(halves)
        return []
    length, static = rhythm.opening_length(
        run, {h["side"]: h["motion_seconds"] for h in halves})
    for h in halves:
        kept = []
        for c in h["cuts"]:
            if c["at"] >= length - 0.01:
                # Starts after the opening now ends (the other side ran out
                # first) - never on screen, so not a use of the shot either.
                Path(c["clip"]).unlink(missing_ok=True)
                continue
            if c["at"] + c["seconds"] > length:
                c["seconds"] = round(length - c["at"], 2)
            kept.append(c)
        gap = static[h["side"]]
        last = kept[-1]
        if gap > 0:
            # Nothing else distinct on this side: hold the last frame for the
            # gap, which opening_length() has already capped at the ceiling.
            frame = clips_dir / f"open_{h['side']}_held_{Path(last['clip']).stem}.png"
            if hold_frame(last["clip"], last["seconds"], frame, used=last):
                kept.append({**last, "kind": "still", "asset": str(frame),
                             "held_frame": True, "at": round(length - gap, 3),
                             "seconds": round(gap, 2)})
            else:
                # The frame could not be lifted, so the clip will sit on its
                # last frame for the gap - recorded as exactly that.
                last["seconds"] = round(last["seconds"] + gap, 2)
                last["held_frame"] = True
        h["cuts"] = kept
        h["motion_seconds"] = round(sum(c["seconds"] for c in kept
                                        if not c["held_frame"]), 3)
        h["static_seconds"] = round(gap, 3)
        h["seconds"] = round(length, 3)
        h["held_frame"] = gap > 0
        # The first picture's fields on the half itself: the shape every reader
        # of a split half knew before CF-0075, still true of what is on screen
        # when the opening starts.
        first = kept[0]
        for key in ("clip", "shot", "source", "key", "score", "card", "kind",
                    "asset", "crop_bottom", "frame_before_crop", "cut_at",
                    "cut_origin", "moment_at"):
            if key in first:
                h[key] = first[key]
    return halves


# CF-0367: the re-cut lever. SKILL.md has always said "re-cut the same anchor
# against a different candidate first" before a block drops a rung, and there
# was no tool that did it: the operator on 2026-09-23T1722Z/american-horror-
# story had a block qc_render refused and no way to ask for any other picture
# for that one anchor. `--exclude-candidate BLOCK` names a block of the
# storyboard this run replaces; its shot is refused *for that anchor only*,
# inside fill(), ahead of every other gate - so whatever replaces it went
# through the same repeat (CF-0337), text (CF-0351/0354), entity (CF-0348)
# and even-budget (CF-0370) checks as any first choice. Exclusions carry over
# from the storyboard being replaced, so a second re-cut cannot bring the
# first rejected shot back.
def channel_id_of(spec):
    """CF-0397: `--channel`'s id - `example-film` for `channels/example-film.json`,
    a bare id as is, None for none."""
    return Path(spec).stem if spec else None


def parse_exclusion(spec):
    """`BLOCK` or `BLOCK=SOURCE:SHOT` -> `(block, shot or None)`."""
    head, _, shot = str(spec).partition("=")
    try:
        return int(head), (shot or None)
    except ValueError:
        raise SystemExit(f"--exclude-candidate {spec!r}: expected BLOCK or "
                         f"BLOCK=SOURCE:SHOT (e.g. 6 or 6=EmOTDswBfgE:28)")


def block_shots(block):
    """Every shot a storyboard block shows - rhythm.block_shots(), plus the
    lead `shot` of a block that names its chain only in `swing_block_shots`."""
    shots = [block.get("shot")] + list(rhythm.block_shots(block)) + \
        list(block.get("swing_block_shots") or [])
    return [x for x in dict.fromkeys(shots) if x]


def load_exclusions(storyboard_path, requested, by=None):
    """`(exclusions, previous_blocks)` for `--exclude-candidate`.

    `exclusions` is a list of `{block, word_index, phrase, shot, reason}` -
    the ones the replaced storyboard already carried, then one per requested
    block index, naming the shot that block shows now. `previous_blocks` is
    that storyboard's block list, kept to say afterwards what else moved.
    Refuses (SystemExit) when there is no storyboard to re-cut, or when a
    requested block has no picture of its own to exclude.

    CF-0648: `by` names who asked (`held_screen` - build_render_plan.py's
    automatic re-cut of a held frame CF-0646 flags); it rides on the new
    entries, so the per-anchor ceiling of that re-cut counts its own.
    """
    path = Path(storyboard_path)
    if not path.exists():
        raise SystemExit(f"--exclude-candidate re-cuts an existing storyboard, "
                         f"and there is none at {path} - resolve it once first")
    prev = json.loads(path.read_text())
    blocks = prev.get("blocks") or []
    out = [dict(e) for e in (prev.get("excluded_candidates") or [])]
    supply = {e.get("block_index"): e.get("phrase")
              for e in (prev.get("anchor_supply") or [])}
    for spec in requested:
        idx, named = parse_exclusion(spec)
        if not 0 <= idx < len(blocks):
            raise SystemExit(f"--exclude-candidate {idx}: the storyboard at {path} "
                             f"has blocks 0-{len(blocks) - 1}")
        b = blocks[idx]
        shot = named or b.get("shot") or (block_shots(b) or [None])[0]
        wr = b.get("word_range") or [None]
        if named and named not in block_shots(b):
            raise SystemExit(f"--exclude-candidate {spec}: block {idx} shows "
                             f"{', '.join(block_shots(b)) or 'no shot'}, not "
                             f"{named}")
        if not shot or wr[0] is None:
            raise SystemExit(f"--exclude-candidate {idx}: block {idx} shows no "
                             f"shot of its own (a card, a split or an unfilled "
                             f"block) - there is no candidate to exclude")
        entry = {"block": idx, "word_index": wr[0],
                 "phrase": supply.get(idx) or b.get("intent"), "shot": shot,
                 "reason": f"block {idx}'s picture on the storyboard this "
                           f"re-cut replaced - excluded for that anchor by "
                           f"--exclude-candidate (CF-0367)",
                 **({"by": by} if by else {})}
        if not any(e["word_index"] == entry["word_index"] and e["shot"] == shot
                   for e in out):
            out.append(entry)
    return out, blocks


def resolve_call(argv):
    """CF-0648: `{"script", "python", "cwd", "argv"}` - this run's command
    line with `--exclude-candidate` / `--exclude-by` taken out (the
    exclusions live on the storyboard and carry over from it)."""
    out, skip = [], False
    for a in argv:
        if skip:
            skip = False
            continue
        if a in ("--exclude-candidate", "--exclude-by"):
            skip = True
            continue
        if a.startswith(("--exclude-candidate=", "--exclude-by=")):
            continue
        out.append(str(a))
    return {"task": "CF-0648", "script": str(Path(__file__).resolve()),
            "python": sys.executable, "cwd": os.getcwd(), "argv": out}


def exclusion_misses(exclusions, blocks):
    """The exclusions a finished block list still shows: an excluded shot on
    a block of the very anchor it was excluded from. Empty when every one
    landed - which is the only state a re-cut may be written in."""
    missed = []
    for e in exclusions:
        for i, b in enumerate(blocks):
            if (b.get("word_range") or [None])[0] == e["word_index"] and \
                    e["shot"] in block_shots(b):
                missed.append({**e, "still_on_block": i})
    return missed


def recut_report(previous, blocks, exclusions):
    """What the re-cut changed, block by block: `{"blocks": [...],
    "changed_elsewhere": [...], "block_count": [before, after]}`. A block
    that was not asked about and still changed is said out loud - a shot
    handed to the re-cut block can no longer be the later block's (the
    CF-0121 one-use ledger), and that is a consequence, not a secret."""
    asked = {e["block"] for e in exclusions if "block" in e}
    changed = []
    for i in range(max(len(previous), len(blocks))):
        before = block_shots(previous[i]) if i < len(previous) else []
        after = block_shots(blocks[i]) if i < len(blocks) else []
        if before != after:
            changed.append({"block": i, "before": before, "after": after})
    return {"blocks": [c for c in changed if c["block"] in asked],
            "changed_elsewhere": [c for c in changed if c["block"] not in asked],
            "block_count": [len(previous), len(blocks)]}


def cut_command(source, start, duration, dest, crop_bottom=None, card=False):
    """The prepare_clip.py call cut() makes. Its own function so a test can
    check what the cutter is told without cutting: CF-0092's point is that
    a live shot and a card are told apart *before* the band is applied."""
    args = [VENV_PY, str(SCRIPTS / "prepare_clip.py"), source, str(start), str(duration), dest]
    args += ["--crop-bottom", str(crop_bottom)] if crop_bottom is not None else ["--auto-crop"]
    if card:
        args.append("--card")
    return args


def cut(source, start, duration, dest, crop_bottom=None, card=False):
    """Cut a candidate; returns what was cropped - {"crop_bottom": fraction
    (0.0 for none), "frame_before_crop": "WxH" or None, "crop_refused":
    fraction or None} - or None if the cut failed. `crop_bottom`, when known,
    comes from index_footage.py's per-shot cache (CF-0029) and is passed
    straight through to prepare_clip.py, which already treats an explicit
    --crop-bottom as "skip detection, use this" - so this reuses that
    existing mechanism rather than adding a new one. Falls back to
    --auto-crop (today's fresh detect_text_band.py call) when no cached
    value is available, e.g. an index built before CF-0029.

    `card` (CF-0092) tells prepare_clip.py whether this is a title/end card
    or a live shot: a live shot's band above prepare_clip.MAX_LIVE_CAPTION_
    CROP is scene text (a studio backdrop, name plates) and is refused
    rather than cut - `crop_refused` carries the band that was, so the
    storyboard records it instead of it reading as "no captions". A card's
    band above prepare_clip.CARD_OWN_BAND (CF-0103) is the card's own
    lettering and is kept - `card_band_kept` carries that one."""
    # SIBLING_SCRIPT_TIMEOUT_SECONDS, not media_timeout(duration): on the
    # --auto-crop path prepare_clip.py runs detect_text_band.py (Vision) before
    # it cuts anything, so this wait is not an ffmpeg pass over `duration`
    # seconds of material and must not be sized as one.
    out = run_tool(cut_command(source, start, duration, dest, crop_bottom, card),
                   tool="prepare_clip.py", target=str(dest))
    if out.returncode != 0:
        print(out.stderr, file=sys.stderr)
        return None
    # CF-0062: what prepare_clip.py actually took off the bottom, and the
    # frame it took it from - read back from it rather than assumed, because
    # on the --auto-crop path only it knows the crop, and only it saw the
    # frame before the crop. The gate is told both so a clip it rejects on
    # resolution can say whether the source or this crop is to blame.
    applied = re.search(r"crop_bottom=([\d.]+)", out.stdout)
    frame = re.search(r"frame_before_captions=(\d+x\d+)", out.stdout)
    refused = re.search(r"caption_crop_refused=([\d.]+)", out.stdout)
    if refused:
        print(f"  CROP REFUSED {Path(dest).name}: live shot, cached caption band "
              f"{float(refused.group(1)):.0%} of the frame reads as scene text "
              f"(> {prepare_clip.MAX_LIVE_CAPTION_CROP:.0%}, CF-0092) - cut uncropped",
              file=sys.stderr)
    # CF-0103: a card's thick band is its own lettering, kept rather than
    # cropped; the storyboard records the band so a card cut at full height
    # does not read as "no captions".
    kept = re.search(r"card_band_kept=([\d.]+)", out.stdout)
    if kept:
        print(f"  CARD BAND KEPT {Path(dest).name}: cached band "
              f"{float(kept.group(1)):.0%} of the frame is the card's own lettering "
              f"(> {prepare_clip.CARD_OWN_BAND:.0%}, CF-0103) - cut uncropped",
              file=sys.stderr)
    return {"crop_bottom": float(applied.group(1)) if applied else float(crop_bottom or 0.0),
            "frame_before_crop": frame.group(1) if frame else None,
            "crop_refused": float(refused.group(1)) if refused else None,
            "card_band_kept": float(kept.group(1)) if kept else None}


def script_of_order(spec_arg, script_id=None):
    """CF-0545: the script the order came from (`topic_id`, `scene_id`,
    `title_ref`) - `--order` names one script of `03-content-researcher.json`
    (`work/<slug>/order.json`) or the whole file; {} when there is none."""
    if not spec_arg:
        return {}
    try:
        text = spec_arg if spec_arg.lstrip().startswith("{") else Path(spec_arg).read_text()
        data = json.loads(text)
    except (OSError, ValueError, TypeError):
        return {}
    if isinstance(data, dict) and isinstance(data.get("scripts"), list):
        data = next((x for x in data["scripts"] if isinstance(x, dict)
                     and x.get("script_id") == script_id), {})
    return data if isinstance(data, dict) else {}


def event_guard_for(script, index_data, report_path):
    """CF-0545: the event-footage guard for this script and pool - the
    batch beside `01b` (the hunter's record, the supplement requests), the
    footage registry beside the shots.json files."""
    sources, footage_dir = [], None
    for data in (index_data or {}).values():
        src = data.get("source")
        vid = entity_guard.source_id(src)
        if vid and vid not in sources:
            sources.append(vid)
        if src and footage_dir is None:
            footage_dir = Path(src).parent
    batch_dir = Path(report_path).parent if report_path else None
    hunter, registry, reqs = event_footage.batch_inputs(batch_dir, footage_dir)
    return event_footage.build(script, sources, hunter, registry, reqs)


def event_decisions(guard, anchors, words):
    """CF-0545: block_rule()'s answer per anchor, over the words spoken from
    its word_index to the next anchor's."""
    wi = [a["word_index"] for a in anchors]
    return [event_footage.block_rule(
        guard, event_footage.words_text(
            words, wi[i], wi[i + 1] if i + 1 < len(wi) else len(words)))
        for i in range(len(wi))]


def event_footage_record(guard, anchors, decisions, refused, found_before,
                         matches):
    """CF-0545: the storyboard's `event_footage` - whether the rule was on
    and why, each anchor's answer, how many candidates it took, and `short[]`:
    the anchors that had a picture over the floor before the guard and none
    after - the event's own footage does not carry the phrase, and the
    answer is a supplement of the event's footage (CF-0345), never the
    interview back."""
    by_phrase = Counter(r.get("phrase") for r in refused)
    short = []
    for i, a in enumerate(anchors):
        n = by_phrase.get(a.get("phrase"), 0)
        if n and i < len(matches) and found_before[i] and not matches[i].get("found"):
            short.append({
                "anchor_id": a.get("anchor_id"), "word_index": a["word_index"],
                "phrase": a.get("phrase"), "refused": n,
                "reason": ("nothing of the event's own footage is over the floor "
                           "for this phrase once the interview is out - the "
                           "block goes down the ladder, and the pool wants a "
                           "supplement of the event's footage (CF-0345)")})
    return {
        "task": "CF-0545",
        "applied": bool(guard.get("applied")),
        "why": guard.get("why"),
        "scene_id": guard.get("scene_id"),
        "scene_kind": guard.get("scene_kind"),
        "sources": {v: r.get("role") for v, r in (guard.get("sources") or {}).items()},
        "interview": list(guard.get("interview") or []),
        "blocks": [{"anchor_id": a.get("anchor_id"), "word_index": a["word_index"],
                    "retells_event": bool(d[0]), "why": d[1]}
                   for a, d in zip(anchors, decisions)] if guard.get("applied") else [],
        "refused": len(refused),
        "short": short,
        "needs_supplement": bool(short) or bool(guard.get("needs_supplement")),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("anchors")
    p.add_argument("words")
    p.add_argument("voice")
    p.add_argument("output")
    # CF-0814: repeatable; may be absent only when every anchor is one of the
    # script's own graphics (CF-0689) - checked once the spec is read.
    p.add_argument("--index", action="append", default=[])
    p.add_argument("--footage-index", default=None,
                   help="<batch>/01b-footage-index.json - which sources are a "
                        "thin-pool supplement and which of their shots lack the "
                        "entity (CF-0348). Default: found above --clips-dir.")
    p.add_argument("--clips-dir", required=True)
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    p.add_argument("--top", type=int, default=DEFAULT_TOP,
                   help="candidates the matcher offers per phrase and index. On a "
                        "pool no bigger than this it filters nothing - the run "
                        "warns when that happens (CF-0088)")
    p.add_argument("--score-floor", type=float, default=None,
                   help="CF-0088: a candidate scoring under this is never offered to "
                        "a block, however many top-N slots are free (--min-score "
                        "only *reports* a weak best match; this one refuses it). "
                        "Off by default - no threshold has been measured for it, "
                        "and a refused anchor becomes a typographic block")
    # CF-0104: renamed from --min-short-side, which named what the old check
    # compared against (the source's raw short side) rather than what the
    # relaxation actually reaches - the floor is now checked against the
    # delivered geometry (a cover window's height, or a contain card's
    # upscale factor), never against the source's short side directly.
    p.add_argument("--min-delivery-height", type=int, default=MIN_SHORT_SIDE,
                   help="floor on the pixel height the render actually delivers "
                        "(CF-0104): a cover block's 9:16 window height after any "
                        "caption crop. Defaults to common.MIN_SHORT_SIDE (720, "
                        "CF-0062 variant A - not meant to be loosened to paper over "
                        "the pipeline's own caption crop, RUN_LOG.txt:52).")
    p.add_argument("--min-short-side", type=int, default=None,
                   help="deprecated alias for --min-delivery-height (CF-0104) - kept "
                        "so an old batch command still runs, with a warning")
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE)
    p.add_argument("--max-black", type=float, default=MAX_BLACK_CLIPS)
    p.add_argument("--matcher-python", default=DEFAULT_INDEXER_PY,
                   help="interpreter that runs the indexer's matcher; the indexer owns "
                        "its own environment, this only exists to point elsewhere")
    p.add_argument("--order", default=None,
                   help="the (pattern, rhythm) order drawn upstream: a path to a JSON "
                        "file or an inline JSON object. Omit for the pre-pattern "
                        "default, which is explainer on even (CF-0041).")
    p.add_argument("--pattern", default=None)
    p.add_argument("--rhythm", default=None, choices=list(rhythm.RHYTHMS))
    p.add_argument("--block-count", type=int, default=None)
    p.add_argument("--hold-seconds", type=float, default=None)
    p.add_argument("--opening", default=None, choices=list(rhythm.OPENING_KINDS))
    # Default None, not the constant itself: `ShotLedger` is the only code that
    # reads MAX_SHOT_REUSE (CF-0121), and an argparse default would be a second
    # reader - which is how CF-0003's two copies of one number happened.
    p.add_argument("--channel", default=None,
                   help="CF-0337: channels/<id>.json (or a path). Read for one "
                        "switch only - assetless_block_rung. Where it is off "
                        "(the default, and the answer for no channel at all) a "
                        "block nothing matched is filled from the topic's own "
                        "footage before any repeat, never left for the "
                        "procedural background.")
    p.add_argument("--max-shot-reuse", type=int, default=None,
                   help="how many times one sample (source + shot) may appear in "
                        "the video. Defaults to rhythm.MAX_SHOT_REUSE, which is 1: "
                        "one sample, one use (CF-0074's decision, CF-0121). This "
                        "flag exists so a measurement can re-resolve an old batch "
                        "at the cap that batch was cut under (CF-0026's 3) and "
                        "compare the degradation - not so a pipeline can buy a "
                        "second showing of the same shot; a run that passes it "
                        "anything but the default is not a deliverable run.")
    p.add_argument("--no-stretch-split", action="store_true",
                   help="CF-0480: measurement only - resolve the way it was before "
                        "the stretch split (a one-frame block holds its one shot "
                        "however short), to price the split on an old batch. A run "
                        "that passes it is not a deliverable run.")
    p.add_argument("--retired-shots", default=None, metavar="PATH",
                   help="CF-0397: the channel's retired-shots registry - shots an "
                        "earlier ready video already showed, refused here. Default "
                        "pipeline/<channel>/retired-shots.json for a storyboard "
                        "under pipeline/<group>/<batch>/work/<slug>/; none "
                        "elsewhere. Entries of this video's own slug never refuse.")
    p.add_argument("--exclude-candidate", action="append", default=[],
                   dest="exclude_candidate", metavar="BLOCK[=SOURCE:SHOT]",
                   help="CF-0367: re-cut storyboard block BLOCK (as qc_render "
                        "numbers it) under its next candidate - its shot (or the "
                        "named one of a multi-shot block's) is refused for that "
                        "anchor only, every other gate "
                        "applies as usual. Reads the storyboard at OUTPUT before "
                        "replacing it; repeatable; earlier exclusions carry over. "
                        "A re-render after it is an attempt like any other.")
    p.add_argument("--exclude-by", default=None, metavar="WHO",
                   help="CF-0648: who asked for this run's --exclude-candidate "
                        "(build_render_plan.py passes `held_screen`); recorded "
                        "on the new exclusions")
    p.add_argument("--acceleration", type=float, default=None,
                   help="acceleration-to-payoff strength in (0,1]; 0 turns it off. "
                        "A curve over block length, not a rhythm of its own.")
    args = p.parse_args()
    from _runlog import video_attempt  # CF-0159: CLI-only, see the import above
    runlog.annotate(**video_attempt(args.output))  # CF-0107: slug + ledger attempt

    # CF-0104: --min-short-side is a deprecated alias for --min-delivery-
    # height (see its help above) - resolve the two into the one attribute
    # the rest of this file reads. --min-delivery-height already defaults to
    # MIN_SHORT_SIDE on its own, so the alias only has anything to do when a
    # caller actually passed the old flag.
    if args.min_short_side is not None:
        print("WARNING: --min-short-side is deprecated, use --min-delivery-height "
              "(CF-0104: the floor now checks delivered geometry, not the source's "
              "raw short side) - using it as --min-delivery-height for this run",
              file=sys.stderr)
        args.min_delivery_height = args.min_short_side
    args.min_short_side = args.min_delivery_height
    # CF-0791: the root's shot rule, in the channel's mode, once per run
    configure_shot_guard(channel_id_of(args.channel))

    exclusions, previous_blocks = ([], None)
    if args.exclude_candidate:
        exclusions, previous_blocks = load_exclusions(args.output,
                                                      args.exclude_candidate,
                                                      by=args.exclude_by)
    excluded_by_anchor = {}
    for e in exclusions:
        excluded_by_anchor.setdefault(e["word_index"], set()).add(e["shot"])

    spec = json.load(open(args.anchors))
    words = load_words(args.words)
    total = audio_duration(args.voice)
    clips_dir = Path(args.clips_dir)
    clips_dir.mkdir(parents=True, exist_ok=True)

    anchors = sorted(spec["anchors"], key=lambda a: a["word_index"])
    if not args.index and any(not is_graphic_anchor(a) for a in anchors):
        # CF-0814: an empty pool is only legitimate for an all-graphic script
        p.error("--index is required: an anchor asks the pool (no `graphic_id`) "
                "- which pool is it?")
    # CF-0689: a graphic anchor asks the pool nothing (graphic_match()).
    graphics = spec.get("graphics") if isinstance(spec.get("graphics"), dict) else {}
    matches, index_data = match_pool_anchors(anchors, args.index, args.min_score,
                                             args.top, args.matcher_python)
    shots_lut = shot_lookup(index_data)
    # CF-0348: a supplement source's shot without its entity leaves the pool
    # here, before any rung - the regular match, the split opening, the
    # emergency repeat - can see it; the topic rung and fill() ask again.
    # CF-0351: the same screen refuses a `burned_text: true` shot of any
    # source (somebody else's caption or title card), supplement or not.
    report_path = args.footage_index or entity_guard.find_report(args.clips_dir)
    sups = entity_guard.supplements(
        entity_guard.load_report(report_path) if report_path else None)
    # CF-0567: own-capture shots kept despite their text flag, by their kind.
    own_capture_exempt = []
    entity_refused = entity_guard.screen_matches(matches, index_data, sups,
                                                 args.min_score,
                                                 exempted=own_capture_exempt)
    # CF-0545: a block whose words retell the hunter's on-screen scene takes
    # no shot of an interview of another production (WNL 0701Z: Late Night
    # with Sam Meadows under the monologue) - out of the pool here, before
    # any rung; fill() asks again, whichever rung built its pool. A block
    # whose words say "in an interview" keeps it.
    event_guard = event_guard_for(script_of_order(args.order, spec.get("script_id")),
                                  index_data, report_path)
    event_dec = event_decisions(event_guard, anchors, words)
    found_before = [bool(m.get("found")) for m in matches]
    event_refused = event_footage.screen_matches(matches, event_dec, event_guard,
                                                 args.min_score)
    # CF-0879: an anchor whose words name person X loses the single-person
    # shots that are somebody else's (Y's source by its title, or the other
    # sex by the description) - only when a non-foreign candidate over the
    # floor stays; with none the foreign shot is kept and measured below.
    script_spec = script_of_order(args.order, spec.get("script_id"))
    people = person_shot.script_people(script_spec)
    source_titles = {vid: (rec or {}).get("title")
                     for vid, rec in (event_guard.get("sources") or {}).items()}
    shots_by_key = {}
    for data in (index_data or {}).values():
        vid = entity_guard.source_id(data.get("source"))
        for _sh in data.get("shots", []) or []:
            shots_by_key[(vid, _sh.get("index"))] = _sh
    person_refused, person_kept = person_shot.screen_matches(
        matches, person_shot.anchor_names(anchors, words, people),
        lambda c: shots_lut.get((c.get("index"), c.get("shot"))),
        lambda c: source_titles.get(entity_guard.source_id(c.get("source"))),
        people, args.min_score)
    # CF-0088: say so when top-N was no filter at all on this pool. Printed
    # here, once per index, and recorded on the storyboard under `warnings`
    # so the fact survives past the terminal.
    warnings = top_exhausts_pool(index_data, args.top)
    for w in warnings:
        print(f"WARNING: {w}", file=sys.stderr)

    order = rhythm.normalize_order(load_order(args.order, args))
    ordered_rhythm = order["rhythm_id"]
    params = order["parameters"]
    opening_requested = params["opening_block"]
    rhythm_notes = []

    # --- which two sides the comparison has, and where that answer came from.
    #
    # CF-0050: the script's own declaration comes first. A side is a property
    # of the writing - "then versus now", "what was promised versus what
    # shipped" - and the anchors carry it per moment. The footage partition is
    # what happens when the script declared nothing, and it is a weaker answer
    # for a reason stated in footage_sides(): it can neither see a comparison
    # shot by one camera nor refuse two sources that compare nothing.
    anchor_sides = declared_anchor_sides(anchors)
    declared = rhythm.declared_sides_usable(anchor_sides)
    needs_sides = (order["rhythm_id"] == "alternate"
                   or opening_requested == "side_by_side")
    sides, sides_from = None, None
    if declared:
        sides_from = "script"
    elif needs_sides:
        sides = footage_sides(matches, shots_lut, args.min_short_side,
                              args.min_coverage, args.max_black)
        if sides:
            sides_from = "footage"
            rhythm_notes.append(
                "the script declared no sides, so they were taken from the "
                f"footage sources instead (CF-0050 fallback): {sides}")

    # `alternate` needs two sets to swing between. With neither a declaration
    # nor two usable sources there is nothing to alternate, so the plan falls
    # back to `even` here rather than building an A-B-A-B out of one pool -
    # which is precisely the accidental repetition CF-0034 recorded.
    if order["rhythm_id"] == "alternate" and not declared and not sides:
        rhythm_notes.append(
            "alternate was ordered but the script declared no sides and only "
            "one footage source produced candidates - there is no second set "
            "to swing to, so the plan was built as even instead")
        order = rhythm.normalize_order({**order, "rhythm_id": "even"})
        params = order["parameters"]

    # The block plan. Boundaries are the rhythm's business (CF-0041); this
    # file only fills them.
    #
    # CF-0276: with the pattern file in hand the layout is also held to the
    # pattern's drawn hold band - the ceiling that used to be read for the
    # first time by CF-0270's refusal, standing in front of the render with
    # nothing left to offer but "widen the pool or reassign the pattern".
    # `ceiling_report()` is what the layout could *not* bring under it, and it
    # is written into the storyboard below, before a single clip is cut.
    anchor_starts = [words[a["word_index"]]["start"] for a in anchors]
    pattern_file = rhythm.load_pattern(order["pattern_id"], PATTERNS_DIR)
    segments = rhythm.plan_segments(
        anchor_starts, total, order, [w["start"] for w in words],
        anchor_sides=anchor_sides if declared else None,
        pattern=pattern_file)
    hold_ceiling = rhythm.ceiling_report(segments, order, pattern_file,
                                         anchor_starts)
    for breach in hold_ceiling["breaches"]:
        rhythm_notes.append(breach["note"])
    if order["rhythm_id"] == "alternate" and declared and params["block_count"] \
            and len(segments) != params["block_count"]:
        rhythm_notes.append(
            f"alternate followed the sides the script declared: it crosses its "
            f"axis {len(segments)} time(s), against an ordered block count of "
            f"{params['block_count']}. The declared structure sets the cadence "
            f"and the count yields - splitting a run would put two same-side "
            f"blocks together, which is a swing that never happened")

    # --- the opening block.
    #
    # Three of the four openings need something this file has to go and check
    # before it can promise them, and each check is a fact about this video:
    # a number the script promised, a voiceover that starts late, both sides
    # resolved. rhythm.resolve_opening() holds the rules; everything here does
    # is supply the measurements and record the answer.
    card_text = (spec.get("opening_card") or {}).get("text")
    # The lead is measured off the audio, not taken from a flag: what makes a
    # cold frame a cold frame is that the narration really does start late in the
    # file that is about to be mixed. Off the audio rather than off the word
    # alignment, because whisper hands its first token the segment's start time
    # and would report a beat that is really there as zero.
    lead_silence = leading_silence(args.voice)

    # CF-0121: one sample, one use - and one ledger per video to say so. It is
    # created before the opening because the opening chooses shots too, and
    # everything the block loop below picks has to be off the same list.
    # CF-0397: and the channel's memory of every earlier ready video, read
    # before the first shot is chosen. Unreadable -> stop: resolving without
    # it would quietly hand out shots the channel already showed.
    try:
        retired = retired_shots.Retired.for_output(
            args.output, registry=args.retired_shots,
            channel=channel_id_of(args.channel))
    except retired_shots.RegistryError as e:
        print(f"ERROR: retired-shots registry unreadable (CF-0397): {e}",
              file=sys.stderr)
        sys.exit(2)
    ledger = ShotLedger(args.max_shot_reuse, retired=retired)

    # CF-0689: an opening that would take the first segment from a graphic
    # anchor (a count card, a side-by-side) gives way - the graphic is the
    # script's own frame for those words, the opening only a layout.
    graphic_first = bool(segments) and is_graphic_anchor(
        anchors[driver_anchor(segments[0], matches)])
    if graphic_first and opening_requested in ("count_card", "side_by_side"):
        rhythm_notes.append(
            f"the {opening_requested} opening gave way: the first anchor places "
            f"the script's own graphic, which opens the video instead (CF-0689)")
    opening_asked = ("hook_over_footage" if graphic_first and opening_requested
                     in ("count_card", "side_by_side") else opening_requested)
    split_halves = []
    if opening_asked == "side_by_side" and segments:
        split_halves = build_split_opening(
            anchors, matches, shots_lut, side_pools(anchors, matches,
                                                    anchor_sides if declared else None,
                                                    sides),
            clips_dir, segments[0], args, ledger)
    opening_delivered, opening_reason = rhythm.resolve_opening(
        opening_asked, card_text=card_text, lead_silence=lead_silence,
        sides_resolved=len(split_halves))
    if opening_reason:
        rhythm_notes.append(opening_reason)
    if opening_delivered != "side_by_side":
        discard_halves(split_halves)
        split_halves = []

    blocks, unresolved, rejected_candidates = [], [], []
    rejected_candidates.extend(entity_refused)
    rejected_candidates.extend(event_refused)
    rejected_candidates.extend(person_refused)
    # CF-0150: the pool's answer for each segment, and where that segment's
    # blocks start, so the fact can be stamped on the blocks after the loop.
    # Collected rather than written inline because a segment leaves this loop
    # from a dozen different `continue`s and the fact is only known at one of
    # them - a stamp at each exit is a stamp that will be forgotten at the
    # thirteenth.
    supply_by_segment = {}
    # CF-0278: one-shot segments -> (need, their fill() runs), written onto
    # their blocks as `length_supply` below.
    length_by_segment = {}
    segment_first_block = []
    used_pairs = set()
    # CF-0428: every sample whose cut clip usable() refused this round - the
    # next round cuts it the same way, so pool_capacity() counts it out.
    cut_refused_keys = set()
    prev_shot = None
    # CF-0137: every sample on screen in the block that was just laid down -
    # `prev_shot` is the single-shot answer and is None after a multi-shot
    # block, and the emergency repeat has to know about all of them, because
    # "next to its own first use" is about the picture the viewer just saw.
    prev_keys = set()
    # CF-0137: the one emergency shot repeat this video may spend, and the
    # only thing that says so. One per video, made here beside the ledger for
    # the same reason the ledger is one per video (CF-0121): a second caller
    # with a counter of its own is how a rule that says "once" becomes twice.
    reuse_budget = EmergencyReuseBudget()
    # CF-0337: every picture already laid down, with its span on the voice
    # clock and its signature, so no pick - regular, topic rung or emergency
    # repeat - lands within repeat_guard.MIN_REPEAT_GAP_SECONDS of itself or
    # of a look-alike of the same source - nor, anywhere in the video, as the
    # same footage from another upload of the same trailer (CF-0461).
    placed = []
    # CF-0904: the seconds of strip on blur the cuts laid down so far ask the
    # plan for on its own probe, and every cut held back for a cover-ready
    # shot (`strip_picks` in the storyboard).
    strip_state = {"seconds": 0.0}
    strip_picks = []
    # CF-0337: the topic-footage rung, on wherever the procedural one is off.
    channel_cfg = (meme_layer.load_channel(args.channel, meme_layer.factory_root())
                   if args.channel else None)
    topic_rung = not assetless_rung.enabled(channel_cfg)
    # CF-0337: the one exception to repeat_guard - a measurement run at an
    # old reuse cap (--max-shot-reuse) exists to reproduce the repeats of the
    # batch it re-resolves, and is not a deliverable run (the flag says so).
    guard_repeats = args.max_shot_reuse is None
    carry_start = None
    # CF-0075: the shots on screen in the side-by-side opening, kept off the
    # block that fills the rest of its run - the frame that just left the
    # screen is not a new picture.
    opening_keys = set()
    after_opening = False
    # CF-0370: the pattern's drawn block-count ceiling, as a shot budget on
    # every unordered (`even`) segment - see rhythm.block_count_ceiling(). The
    # segments it capped are written into the storyboard with their numbers.
    band_top = rhythm.block_count_ceiling(pattern_file)
    hold_top = (float(rhythm.hold_band(pattern_file)["max"])
                if rhythm.hold_band(pattern_file) else None)
    band_caps = []
    if band_top is not None and len(segments) > band_top:
        rhythm_notes.append(
            f"the layout has {len(segments)} segments against the pattern's "
            f"drawn block-count top of {band_top} - one picture per segment is "
            f"already over it by {len(segments) - band_top}, so no shot budget "
            f"brings this plan under the band (CF-0370)")
    for si, seg in enumerate(segments):
        after_opening = False
        ai = driver_anchor(seg, matches)
        a, m = anchors[ai], matches[ai]
        end = seg["end"]
        start = carry_start if carry_start is not None else seg["start"]
        carry_start = None
        need = end - start
        # Whether there is a later anchor to hand an uncovered span to - the
        # test both shortfall paths key on (CF-0028's partial cover, CF-0124's
        # segment that resolved to nothing at all).
        has_next = si + 1 < len(segments)
        segment_first_block.append(len(blocks))

        if si == 0 and opening_delivered == "side_by_side":
            # Both sides of the comparison in one frame, so the axis is visible
            # before it is named. Two clips, one block: the halves were cut and
            # gated above, because whether this opening exists at all decides
            # what `opening_delivered` says. CF-0075: the block is as long as
            # the halves can carry (rhythm.opening_length()), not as long as
            # the run - what is left of the run is filled below as an
            # ordinary block of this run's side.
            length = split_halves[0]["seconds"]
            open_end = end if length >= need - 0.01 else round(start + length, 3)
            blocks.append({
                "word_range": [a["word_index"], a["word_index"]],
                "intent": ("side by side: "
                           + " | ".join(f"{h['phrase']} (shot {h['shot']}, "
                                        f"score {h['score']:.3f})" for h in split_halves)
                           + " (opening_block side_by_side)"),
                "asset_kind": "split",
                "split": [{"asset": h["asset"], "kind": h["kind"],
                           "side": h["side"], "held_frame": h["held_frame"],
                           "shot": f"{Path(h['source']).stem}:{h['shot']}",
                           "seconds": h["seconds"], "is_card": h["card"],
                           "crop_bottom": h.get("crop_bottom", 0.0),
                           "frame_before_crop": h.get("frame_before_crop"),
                           "cut_at": h.get("cut_at"),
                           "cut_origin": h.get("cut_origin", "head"),
                           "moment_at": h.get("moment_at"),
                           "phrase": h["phrase"],
                           # CF-0075: every picture this half shows, in order.
                           "cuts": [split_cut_record(c) for c in h["cuts"]],
                           "motion_seconds": h["motion_seconds"],
                           "static_seconds": h["static_seconds"]}
                          for h in split_halves],
                # CF-0075: the run the opening was laid over, so the plan can
                # say how much of it the opening handed back.
                "opening_run_seconds": round(need, 3),
                "emphasis_words": a.get("emphasis_words", []),
                "rhythm_role": seg["role"],
                # Both sides at once is not a hole in the alternation and not a
                # swing either - rhythm.alternation_report() leaves the two
                # boundaries it touches out of the count rather than scoring
                # them as swings the montage failed to make.
                "side": rhythm.BOTH_SIDES,
                "shot": None,
                "held_frame": False,
                "_start": round(start, 3),
                "_end": open_end,
            })
            # The opening is delivered, so its pictures are now spent. One
            # take per *distinct* sample: a half's held frame (CF-0075) is the
            # last cut's own frame - the same picture still on screen, not a
            # second showing of it - and both halves resolved against one
            # forked ledger, so the two sides never overlap in the first place.
            for key in dict.fromkeys(c["key"] for h in split_halves
                                     for c in h["cuts"]):
                ledger.take(key)
                opening_keys.add(key)
            # One block, two shots: there is no single "previous shot" for the
            # adjacent-pair rule to be about, so the chain restarts here.
            prev_shot = None
            # CF-0137: both of them are still on screen, though, so an
            # emergency repeat of either would sit next to its own first use.
            prev_keys = set(opening_keys)
            if open_end >= end:
                continue
            # CF-0075: the opening ran out of distinct footage before the run
            # did. The rest of the run is this side's own block, filled by the
            # chain below exactly as any other - a clip, or a held frame that
            # rhythm_shortfalls() records - rather than a split that stands
            # still until the script crosses its axis.
            rhythm_notes.append(
                f"block {si}: the side-by-side opening carries {length:.2f}s of "
                f"the {need:.2f}s run it opens - past that neither side had "
                f"another distinct shot, and a held frame stops at "
                f"{rhythm.OPENING_MAX_STATIC_SECONDS}s. The remaining "
                f"{end - open_end:.2f}s is filled as an ordinary side "
                f"{seg.get('side')!r} block (CF-0075)")
            start = open_end
            need = end - start
            after_opening = True

        if si == 0 and opening_delivered == "count_card":
            # A card is drawn here, not sourced: no file, no rights, no asset
            # gate, no crop (CF-0012's reading of this class). It takes the
            # opening block's own bounds so the ordered cadence is untouched.
            blocks.append({
                "word_range": [a["word_index"], a["word_index"]],
                "intent": f"count card: {card_text!r} (opening_block count_card)",
                "asset_kind": "card",
                "card": {"kind": "count_card", "text": card_text},
                "emphasis_words": a.get("emphasis_words", []),
                "rhythm_role": "opening_card",
                "side": None,
                "shot": None,
                "held_frame": False,
                "_start": round(start, 3),
                "_end": round(end, 3),
            })
            prev_shot = None
            prev_keys = set()
            continue

        if is_graphic_anchor(a):
            # CF-0689: the factory draws this one - no candidate, no cut, no
            # gate, no ledger take; the plan checks the order (own_graphic.py).
            # CF-0923: every graphic the script placed in this run, each from
            # its own word (graphic_shots); one block per graphic.
            for gi, g_start, g_end in graphic_shots(seg, ai, anchors, anchor_starts,
                                                    start, end, opening=si == 0):
                blocks.append(graphic_block(anchors[gi], graphics, g_start, g_end, seg,
                                            blocks[-1] if blocks else None))
            prev_shot = None
            prev_keys = set()
            continue

        if need < MIN_ANCHOR_GAP_SECONDS and has_next and not after_opening:
            # CF-0453: a note on the block's length, not a missing picture -
            # the block is built below like any other. What is measured is
            # this segment's span (the rhythm cuts one anchor's run into
            # several segments by the pattern's hold, CF-0041), which is why
            # no anchor edit moves it: the short span is the cadence's. The
            # structured `too_tight` is what plan_check (a note, not a
            # refusal) and build_render_plan (`score.block_too_short`) read;
            # the words stay for the readers that grep them.
            unresolved.append({"phrase": a["phrase"], "reason":
                               f"anchor sits {need:.1f}s before the next one - too tight to read",
                               "too_tight": {"segment": si, "t": round(start, 3),
                                             "seconds": round(need, 3),
                                             "min_gap": MIN_ANCHOR_GAP_SECONDS}})
        if not m["candidates"] and not (topic_rung and is_ordered_segment(seg)):
            # CF-0337: an ordered block with a topic rung to climb falls
            # through instead - an empty pool for the phrase is not an empty
            # pool for the topic.
            reason = "no shot in any index"
            supply_by_segment[si] = candidate_supply(
                a["phrase"], [], [], [], args.min_score)
            unresolved.append({"phrase": a["phrase"], "reason": reason})
            settled = settle_unresolved(blocks, a, seg, start, end, reason, has_next)
            if settled == SETTLED_BLOCK:
                prev_shot = None
                prev_keys = set()
            elif settled == SETTLED_CARRY:
                unresolved.append({"phrase": a["phrase"], "reason":
                    f"nothing filled this anchor - its {end - start:.2f}s were "
                    f"carried into the next anchor's block (CF-0124) instead of "
                    f"freezing the previous block over them"})
                carry_start = start
            continue
        if not m.get("discriminative", True):
            unresolved.append({
                "phrase": a["phrase"],
                "reason": f"phrase does not single out any shot (margin "
                          f"{m.get('margin')}) - it likely describes an idea rather "
                          f"than a frame, or nothing available depicts it"})
        # CF-0088: no `found` verdict here. `m["found"]` is the matcher's
        # pre-gate answer; the one the report carries is gate_verdict()'s,
        # taken below on what the gates actually let through.

        # --- which candidates this block may draw on.
        pool = m["candidates"]
        rejected_before = len(rejected_candidates)
        # CF-0088 + CF-0290: both floors, refused outright and in writing, and
        # before anything below has a chance to order or budget them - a free
        # top-N slot is not a reason to offer a shot that matches nothing, and
        # neither is a block nothing else is long enough to fill.
        pool, floored = screen_pool(pool, args.min_score, args.score_floor)
        for r in floored:
            rejected_candidates.append({"phrase": a["phrase"], **r})
        side = seg["side"]
        if side and sides:
            # Sides taken from the footage (CF-0050's fallback): the side is a
            # source, so it is the pool that has to be filtered down to it.
            # When the *script* declared the sides there is nothing to filter -
            # the anchor's phrase already is the side, and its own match results
            # already describe that side's content. That is the whole point of
            # the change: the same camera can now supply both sides.
            on_side = [c for c in pool if sides.get(c["source"]) == side]
            if on_side:
                pool = on_side
            else:
                # Nothing on the side this block was supposed to swing to. The
                # block still gets a picture, but it is recorded as having no
                # side, so alternation_report() sees the hole instead of the
                # plan claiming an alternation it did not perform.
                side = None
                rhythm_notes.append(
                    f"block {si}: no usable candidate on side {seg['side']!r} - "
                    f"the swing is missing here")
        budget = seg["max_shots"] or len(pool)
        # CF-0370: on `even` the chain is budgeted under a drawn block-count
        # top, and what the budget leaves uncovered is held, not chained.
        capped_by_band = False
        if band_top is not None and not is_ordered_segment(seg):
            cap = rhythm.even_shot_budget(band_top, len(blocks),
                                          len(segments) - si - 1,
                                          seconds=need, hold_top=hold_top)
            if cap < budget:
                budget, capped_by_band = cap, True
        if budget == 1:
            # One shot for the whole block, so prefer one long enough to fill
            # it; only when none is does the block hold a frame instead.
            #
            # CF-0290: this sort is *within* the screened pool, and that is the
            # whole of "similarity before length". Every candidate here is
            # already a picture of the phrase, so trading one of them for
            # another by length trades nothing away; before the screen the same
            # line was trading the phrase itself, because a candidate under the
            # floor that happened to be long sorted in front of the one shot
            # that depicted the anchor (delver, block 4: wIM1PDRvKSE:25 at
            # 0.3431 and 0.985s lost the block to fkuxNGbx1qk:54 at 0.2046).
            # A too-short candidate that wins here fills the block the way this
            # branch has always filled a short clip - hold_frame() below, the
            # `still` rung - not by reaching for a shot of something else.
            #
            # CF-0517: fill() keeps this order over its usability rank
            # (`length_first`) - the rank orders the long-enough shots among
            # themselves and the short ones among themselves, never a short
            # one ahead of a long one.
            pool = sorted(pool, key=lambda c: available_seconds(c) < need)
        split = None   # CF-0480, decided after the first fill below
        frozen_probes = {}   # CF-0536: clip -> held_motion reading of its held frame
        # CF-0352: a view of a place - its faceless wide shots are no
        # `low_framing` (wide_place.py); a person's anchor keeps the floor.
        place = wide_place.is_place_anchor(a["phrase"])
        fill_cont = {}
        # CF-0278: every fill() run of this block - the pool in the order it
        # was walked and what became of each candidate it reached - so the
        # length of what was offered is on the record (`length_supply`).
        fill_trace = []
        if budget == 1:
            length_by_segment[si] = (need, fill_trace)

        def fill(pool, reuse_key=None, length_first=False):
            """Cut candidates from `pool` until the block is covered.

            `length_first` (CF-0517) - the caller is a one-shot block's
            match, its side retry or its topic rung: a shot long enough for
            the whole block is walked before any shorter one, usability
            ordering each group (`rank_by_usability(need=)`). The under-floor
            rung and a stretch split's extra cuts walk by rank alone.

            `reuse_key` is CF-0137's emergency repeat and the *only* way past
            the CF-0121 cap: exactly one sample, named by the caller after
            `EmergencyReuseBudget.allow()` said so, may be cut a second time.
            Every other blocked candidate is refused here exactly as before,
            so a caller that passes nothing gets the old behaviour and there
            is no path that quietly buys a repeat.
            """
            # CF-0480: a stretch split's second call goes on from the first
            # cut (`fill_cont`): `covered` of the block already shown, `last`
            # its shot, `cap` the cuts it may still add.
            cap = fill_cont.get("cap", budget)
            covered, used, capped = fill_cont.get("covered", 0.0), [], 0
            # CF-0435: every rung's pool (the match, its retry, under the
            # floor, topic footage, the emergency repeat) goes through here,
            # so this is where a weak shot is put behind the clean ones -
            # and kept: it is the one cut when nothing cleaner survives.
            # CF-0517: behind the long-enough ones on a one-shot block - the
            # usability rank used to override the length sort the caller
            # made, and a short clean shot won the block and held a frame.
            # CF-0648: and where the block cannot be split, a short shot is
            # a frame held for all of it - a mildly blurry long shot keeps
            # its lead, the anchor's own short shot goes ahead of that.
            held_whole = length_first and not split_reachable(seg, need, args)
            pool = rank_by_usability(pool, shots_lut, place,
                                     need=need if length_first else None,
                                     phrase=a["phrase"], held_whole=held_whole)
            # CF-0278: which candidate was reached, and the index its refusal
            # (if any) lands on - every refusal below appends exactly one
            # record to `rejected_candidates`, an accepted cut appends none.
            reached = []
            # CF-0120: the swing rules below are about the picture *just before*
            # this one, and inside a multi-shot swing block that is the previous
            # cut of this same block, not the previous block. Measuring them by
            # block would let a swing block open with the shot its predecessor
            # closed on, or rebuild an adjacent pair CF-0034 already refused,
            # simply because the repeat happened to sit inside one block. So the
            # chain is carried per cut here; `used_pairs` itself is only written
            # once the block is delivered, further down.
            last_key, seen_pairs = fill_cont.get("last", prev_shot), set(used_pairs)
            # CF-0337: this call's own accepted cuts, checked against each
            # other too, and handed to `placed` only when the call returns.
            block_placed = []
            # CF-0904: a cut held back for a cover-ready shot (its stash),
            # the extra cuts spent looking, and whether this call may still
            # hold one back (once its spare cuts are spent it may not).
            held, spare, may_hold = None, 0, True

            def take(c):
                """Lay the cut `c` down - the old accept step, now shared by
                a held cut taken after all (CF-0904). True when a split is
                covered and the walk stops (CF-0480)."""
                nonlocal covered, last_key
                block_placed.append(c["here"])
                # CF-0435: what makes this picture weak - the clip's own soft
                # failures and the shot's `on_topic: false` - for the plan.
                # CF-0452: and `low_sharpness` (warn until signed); the shot's
                # fresh sharpness record goes along for a held frame's best_at.
                weak = shot_score.record(c["shot"], c["soft"], video=c["cand"]["source"])
                weak = wide_record(weak, c["wide"])   # CF-0352
                sharp = shot_score.sharpness_record(c["shot"], c["cand"]["source"])
                used.append({"clip": c["dest"], "shot": c["cand"]["shot"],
                             "key": c["key"], "score": c["cand"]["score"],
                             "seconds": round(c["span"], 2),
                             "card": bool(c["cand"].get("card")),
                             **cut_provenance(c["cand"], c["at"], c["origin"]),
                             **c["applied"],
                             **({"usability": weak} if weak else {}),
                             **({"sharpness": sharp} if sharp else {}),
                             **({"topic_rung": c["cand"]["topic_rung"]}
                                if c["cand"].get("topic_rung") else {})})
                ledger.take(c["key"])
                strip_state["seconds"] += c["strip"]   # CF-0904
                covered += c["span"]
                if last_key is not None:
                    seen_pairs.add((last_key, c["key"]))
                last_key = c["key"]
                stop = fill_cont.get("stop")
                span = c["span"]
                if split and (stop(used) if stop else need - covered <= span):
                    # CF-0480: what is left is no longer than this cut - held,
                    # it stands at most twice its length (not stretched,
                    # still_share's line). The pool's next shots are left to
                    # the blocks after this one. CF-0536: a split's extension
                    # (`fill_cont["stop"]`) stops once split_wants_more() is
                    # answered.
                    return True
                return False

            def take_held(why):
                """CF-0904: no cover-ready shot came within the spare cuts -
                the held cut is the picture after all; its hold line leaves
                `rejected_candidates` (the indices `reached` points at after
                it move back by one), and `strip_picks` says so."""
                nonlocal held, may_hold
                c, held, may_hold = held, None, False
                at_rec = rejected_candidates.index(c["record"])
                del rejected_candidates[at_rec]
                reached[:] = [(rc, i - 1 if i > at_rec else i) for rc, i in reached]
                strip_picks.append({"segment": si, "phrase": a["phrase"],
                                    "held": _shot_name(c["cand"]),
                                    "seconds": round(c["span"], 3),
                                    "picked": None, "spare_cuts": spare,
                                    "outcome": why})
                return take(c)

            for cand in pool:
                if covered >= need or len(used) >= cap:
                    break
                reached.append((cand, len(rejected_candidates)))
                shot_key = (cand["source"], cand["shot"])
                if (f"{Path(cand['source']).stem}:{cand['shot']}"
                        in excluded_by_anchor.get(a["word_index"], ())):
                    # CF-0367: the operator's re-cut - this anchor may not
                    # have this picture again. First, so no gate below spends
                    # a cut or a probe on it.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"],
                        "score": cand["score"],
                        "reason": "excluded for this anchor by "
                                  "--exclude-candidate (CF-0367) - it was the "
                                  "picture qc_render refused here"})
                    continue
                spent = ledger.retired(shot_key)
                if spent and shot_key != reuse_key:
                    # CF-0397: an earlier ready video of the channel showed
                    # it. Its own line, and not counted as `capped` - the
                    # cap's wording is about this video's own repeats.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"],
                        "score": cand["score"], "reason": spent})
                    continue
                if ledger.blocked(shot_key) and shot_key != reuse_key:
                    capped += 1
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"], "score": cand["score"],
                        "reason": ledger.reason(shot_key)})
                    continue
                if after_opening and shot_key in opening_keys:
                    # Unreachable at the CF-0121 cap of one use - the ledger
                    # above already refused it, and with its own wording. Kept
                    # because it is the *reason* this block in particular may
                    # not have that picture (the frame that just left the
                    # screen), and because it stays true if a measurement run
                    # raises --max-shot-reuse.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"], "score": cand["score"],
                        "reason": "already on screen in the side-by-side opening "
                                  "this block follows - not a new picture (CF-0075)"})
                    continue
                if seg["role"] == "swing" and shot_key == last_key:
                    # Two identical shots either side of a cut is not a swing,
                    # it is one picture with a crossfade in the middle of it.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"], "score": cand["score"],
                        "reason": "same shot as the picture before it - not a swing"})
                    continue
                if seg["role"] == "swing" and last_key is not None and \
                        (last_key, shot_key) in seen_pairs:
                    # The alternation may not be built out of the same adjacent
                    # pair twice. That repeated pair - not the per-shot count,
                    # which never came near CF-0026's cap - is what CF-0034
                    # measured as the one genuinely stuck repeat in a real
                    # video, and it is the whole difference between this rhythm
                    # and that defect.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"], "score": cand["score"],
                        "reason": "would repeat the adjacent shot pair already "
                                  "used (CF-0034)"})
                    continue
                shot = shots_lut.get((cand["index"], cand["shot"]))
                off_entity = entity_guard.refusal(cand["source"], cand["shot"],
                                                  shot, sups)
                if off_entity:
                    # CF-0348: the last word, whichever rung built the pool.
                    # CF-0351: also refuses a `burned_text: true` shot.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"],
                        "score": cand["score"], "reason": off_entity})
                    continue
                off_event = event_footage.refusal(
                    event_guard, event_dec[ai][0] if ai < len(event_dec) else False,
                    cand["source"])
                if off_event:
                    # CF-0545: the topic rung, the repeat - never back to the
                    # interview under the event's words.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"],
                        "score": cand["score"], "reason": off_event})
                    continue
                # CF-0140: the mark, the span and the cached-usability
                # pre-filter are one gate now (precut_refusal()), because
                # anchor_coverage.py has to ask exactly this question about a
                # pool before any of this runs. The three refusals below read
                # the same as they always did; only the place they are written
                # moved.
                at, origin, span, refusal = precut_refusal(
                    cand, shot, args.min_short_side, args.min_coverage,
                    args.max_black, need=need, covered=covered, budget=budget)
                if refusal:
                    if refusal["log"]:
                        print(f"  {refusal['log']}", file=sys.stderr)
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"],
                        **refusal["record"]})
                    continue
                short_after_long = (held is not None and length_first
                                    and available_seconds(held["cand"]) >= need
                                    > available_seconds(cand))
                if held is not None and (spare >= STRIP_SPARE_CUTS or short_after_long):
                    # CF-0904: the spare cuts are spent, or the walk reached
                    # the shots too short for the block while the held one
                    # is long enough (CF-0517: length first) - the held cut
                    # is laid down, and this candidate is walked as before.
                    if take_held("spare_cuts_spent" if spare >= STRIP_SPARE_CUTS
                                 else "no_long_enough_shot") \
                            or covered >= need or len(used) >= cap:
                        break
                if held is not None:
                    spare += 1
                # Shot numbers are per-index, so two sources both have a shot
                # 20. Without the source in the name they collide: the second
                # candidate overwrites the first one's file, fails the gate, and
                # the unlink below deletes a clip an accepted block points at.
                dest = (clips_dir /
                        f"a{si:02d}_{Path(cand['source']).stem}_s{cand['shot']:03d}.mp4")
                crop_bottom = shot.get("crop_bottom_cached") if shot else None
                if origin == "moment":
                    report_moment_cut(dest, cand, at, span)
                applied = cut(cand["source"], at, span, str(dest),
                              crop_bottom, card=bool(cand.get("card")))
                if applied is None:
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"], "score": cand["score"],
                        "reason": "prepare_clip.py failed to cut it"})
                    continue
                soft = []
                wide = [] if wide_candidate(cand, place) else None  # CF-0352
                first = []   # CF-0904: the plan's own probe frame
                ok, failures = usable(str(dest), span, args.min_short_side,
                                      args.min_coverage, args.max_black,
                                      card=bool(cand.get("card")), crop=applied,
                                      soft_out=soft, wide_out=wide,
                                      first_out=first)
                if not ok:
                    Path(dest).unlink(missing_ok=True)
                    cut_refused_keys.add(shot_key)
                    # CF-0062: the failure lines themselves, not just the fact.
                    # "failed usable()" covered a low-res source and a clip our
                    # own caption crop had pushed under the floor with the same
                    # words; `lost_to_crop` is the machine-readable split.
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"], "score": cand["score"],
                        "reason": "failed usable() on the cut clip: "
                                  + "; ".join(failures),
                        "failures": failures,
                        "lost_to_crop": any("(CF-0062)" in f for f in failures),
                        **applied})
                    continue
                # CF-0337: not within MIN_REPEAT_GAP_SECONDS of itself or of a
                # look-alike of its source - asked of the cut clip, because the
                # look is what the rule is about.
                t0 = start + covered
                # The last picture a budgeted block may take stays up to the
                # block's end (held, CF-0370), so that is the span it occupies.
                last_slot = budget == 1 or (capped_by_band and len(used) + 1 >= cap) \
                    or (split and len(used) + 1 >= cap)
                here = {"key": shot_key, "start": t0,
                        "end": max(t0 + span, end) if last_slot else t0 + span,
                        "sig": (repeat_guard.signature(str(dest), span)
                                if guard_repeats else None)}
                clash = (repeat_guard.conflict(placed + block_placed, here)
                         if guard_repeats else None)
                if clash:
                    Path(dest).unlink(missing_ok=True)
                    other = clash["other"]["key"]
                    rejected_candidates.append({
                        "phrase": a["phrase"], "shot": cand["shot"], "score": cand["score"],
                        "reason": repeat_guard.describe(
                            clash, f"{Path(str(other[0])).stem}:{other[1]}"),
                        "repeat_guard": {"kind": clash["kind"],
                                         "gap": clash["gap"],
                                         "similarity": clash["similarity"],
                                         **({"copy": True} if clash.get("copy")
                                            else {})}})
                    continue
                c = {"cand": cand, "shot": shot, "key": shot_key,
                     "dest": str(dest), "span": span, "at": at, "origin": origin,
                     "applied": applied, "soft": soft, "wide": wide, "here": here,
                     "strip": strip_seconds_of(span, first, applied, shot,
                                               card=bool(cand.get("card")))}
                if c["strip"] and held is None and may_hold and \
                        strip_state["seconds"] + c["strip"] > shot_score.STRIP_ALLOW_SECONDS:
                    # CF-0904: past the allowance - held back, not refused;
                    # the next candidates are cut for a cover-ready one.
                    c["record"] = {"phrase": a["phrase"], "shot": cand["shot"],
                                   "score": cand["score"],
                                   "reason": strip_hold_reason(strip_state["seconds"],
                                                               span),
                                   "strip_hold": STRIP_PICK_TASK}
                    rejected_candidates.append(c["record"])
                    held = c
                    continue
                if held is not None:
                    if c["strip"]:
                        # CF-0904: no better than the held one - back to the
                        # pool (later blocks may still cut it).
                        Path(dest).unlink(missing_ok=True)
                        rejected_candidates.append({
                            "phrase": a["phrase"], "shot": cand["shot"],
                            "score": cand["score"],
                            "reason": "its own probe frame cuts the subject too - "
                                      "not the cover-ready shot looked for in "
                                      f"place of the one held back ({STRIP_PICK_TASK})"})
                        continue
                    # CF-0904: a cover-ready shot - the picture; the held cut
                    # goes back to the pool and its clip is thrown away.
                    if held["dest"] != str(dest):
                        Path(held["dest"]).unlink(missing_ok=True)
                    strip_picks.append({"segment": si, "phrase": a["phrase"],
                                        "held": _shot_name(held["cand"]),
                                        "seconds": round(held["span"], 3),
                                        "picked": _shot_name(cand),
                                        "spare_cuts": spare,
                                        "outcome": "cover_ready_picked"})
                    held = None
                if take(c):
                    break
            if held is not None and covered < need and len(used) < cap:
                take_held("pool_spent")
            elif held is not None:
                Path(held["dest"]).unlink(missing_ok=True)
                held = None
            placed.extend(block_placed)
            fill_trace.append(fill_run(pool, reached, rejected_candidates,
                                       length_first=length_first,
                                       held_whole=held_whole))
            return used, capped

        used, capped = fill(pool, length_first=budget == 1)
        if side and sides and not used:
            # Nothing on the ordered side survived the cut. The block keeps its
            # place in the cadence - dropping it would collapse an ordered
            # rhythm into a shorter, different one - but it is recorded with no
            # side, so alternation_report() sees the hole and the video does not
            # get to claim a swing it only half performed.
            rhythm_notes.append(
                f"block {si}: nothing on side {side!r} survived the cut - the block "
                f"was filled from the other side and carries no side")
            side = None
            # CF-0290: screened again rather than taken raw. This line used to
            # restore `m["candidates"]`, which handed the retry the candidates
            # `--score-floor` had just refused as well; the refusals are already
            # in the record from the screen above, so they are not written twice.
            pool, _ = screen_pool(m["candidates"], args.min_score, args.score_floor)
            if budget == 1:
                pool = sorted(pool, key=lambda c: available_seconds(c) < need)
            used, capped = fill(pool, length_first=budget == 1)
        def stretch_split(used, capped, pool, rung):
            """CF-0480: the one shot this one-frame block got would stand
            for more than twice its length - cut the block into 2-3 shots of
            its phrase (`pool`, the rung's own candidates) instead, the first
            one kept where it is. Returns `(used, capped)`; sets `split`
            and `budget`."""
            nonlocal split, budget
            if budget != 1 or len(used) != 1 or args.no_stretch_split:
                return used, capped
            split = (stretch_split_wanted(used[0]["seconds"], need, seg)
                     or soft_hold_wanted(used[0], need, seg, clips_dir, si)
                     or frozen_hold_wanted(used[0], need, seg, clips_dir, si,
                                           frozen_probes))
            if not split:
                return used, capped
            split["rung"] = rung
            first = used[0]
            for pl in placed:
                # It no longer stands to the block's end (fill() placed the
                # one shot of a one-shot block over the whole of it).
                if pl["key"] == first["key"] and pl["end"] > pl["start"] + first["seconds"]:
                    pl["end"] = pl["start"] + first["seconds"]
            budget = split["wanted"]
            keep_for_later = later_first_picks(segments, matches, si,
                                               args.min_score, args.score_floor)
            rest = [c for c in pool if (c["source"], c["shot"]) != first["key"]
                    and (c["source"], c["shot"]) not in keep_for_later]
            split["kept_for_later"] = len([c for c in pool if (c["source"], c["shot"])
                                           in keep_for_later])
            fill_cont.update(covered=first["seconds"], last=first["key"],
                             cap=budget - 1)
            try:
                more, more_capped = fill(rest)
            finally:
                fill_cont.clear()
            used, capped = used + more, capped + more_capped
            if len(used) >= 2:
                used, capped = extend_split(used, capped, rest)
            split["got"] = len(used)
            if len(used) < 2:
                split["short"] = True
                split["reason"] = (
                    f"the pool gave {a['phrase']!r} one shot of "
                    f"{first['seconds']:.2f}s for a {need:.2f}s block and no "
                    f"second shot of the phrase survived the gates - the frame "
                    f"is held x{split['ratio']}"
                    + (f", soft ({split['soft_frame']} under {split['floor']})"
                       if split["why"] == "soft_frame" else "")
                    + ": the pool does not hold this block with motion (CF-0480)")
                rhythm_notes.append(f"block {si}: STRETCH SPLIT SHORT - "
                                    + split["reason"])
            else:
                rhythm_notes.append(
                    f"block {si}: STRETCH SPLIT - {Path(first['key'][0]).stem}:"
                    f"{first['shot']} runs {first['seconds']:.2f}s against a "
                    f"{need:.2f}s block (x{split['ratio']}"
                    + (f", its frame soft {split['soft_frame']}"
                       if split["why"] == "soft_frame" else "")
                    + f"); cut into {len(used)} shots of the phrase rather than one frame "
                    f"held (CF-0480)")
            return used, capped

        def frozen_of(u):
            """CF-0536: the frame cut `u` would hold is a face frozen mid-motion."""
            return bool((frozen_frame(u, clips_dir, si, frozen_probes) or {}).get("frozen"))

        def extend_split(used, capped, rest):
            """CF-0536: a split whose cuts still leave a stretched tail, or a
            tail longer than FROZEN_HOLD_MAX_SECONDS held only on frozen faces
            (`split_wants_more`), takes the phrase's next shots, one fill()
            run going on from the last cut, up to STRETCH_SPLIT_MAX_SHOTS_LONG
            cuts, stopping as soon as the tail may be held: first `rest` (the
            pool the split was filled from), then - when that is spent - the
            phrase's own candidates under the similarity floor (CF-0433's
            pool: the matcher's pictures of this phrase, not of something
            else; the block is then priced `score.low_similarity` like any
            block filled under the floor). Records `more` (why, the cuts it
            added, which of them were under the floor) or `more_short` (the
            pool had none) on the split."""
            why = split_wants_more(used, need, frozen_of)
            if not why or len(used) >= STRETCH_SPLIT_MAX_SHOTS_LONG:
                return used, capped
            added, under = [], []
            taken = {u["key"] for u in used}
            keep = later_first_picks(segments, matches, si, args.min_score,
                                     args.score_floor)
            unders = [c for c in below_floor_pool(m["candidates"], args.min_score,
                                                  args.score_floor)
                      if (c["source"], c["shot"]) not in keep]
            for pool_n, src in enumerate((rest, unders)):
                cur = used + added
                if len(cur) >= STRETCH_SPLIT_MAX_SHOTS_LONG \
                        or not split_wants_more(cur, need, frozen_of):
                    break
                taken = {u["key"] for u in cur}
                left = [c for c in src if (c["source"], c["shot"]) not in taken]
                if not left:
                    continue
                last = cur[-1]
                for pl in placed:
                    # the last cut no longer stands to the block's end
                    if pl["key"] == last["key"] and pl["end"] > pl["start"] + last["seconds"]:
                        pl["end"] = pl["start"] + last["seconds"]
                fill_cont.update(covered=sum(u["seconds"] for u in cur), last=last["key"],
                                 cap=STRETCH_SPLIT_MAX_SHOTS_LONG - len(cur),
                                 stop=lambda new, cur=cur: not split_wants_more(
                                     cur + new, need, frozen_of))
                try:
                    more, more_capped = fill(left)
                finally:
                    fill_cont.clear()
                added += more
                capped += more_capped
                if pool_n == 1:
                    under += more
            if added:
                split["more"] = {"task": FROZEN_TASK, "why": why,
                                 "shots": [f"{Path(u['key'][0]).stem}:{u['shot']}"
                                           for u in added]}
                if under:
                    split["more"]["below_floor"] = {
                        "shots": [f"{Path(u['key'][0]).stem}:{u['shot']}" for u in under],
                        "score": round(min(u["score"] for u in under), 4),
                        "min_score": args.min_score}
                rhythm_notes.append(
                    f"block {si}: STRETCH SPLIT GOES ON - {len(used)} shots left "
                    f"{need - sum(u['seconds'] for u in used):.2f}s to hold "
                    f"({why}); {len(added)} more shot(s) of the phrase"
                    + (f", {len(under)} under the similarity floor, priced "
                       f"score.low_similarity" if under else "") + " (CF-0536)")
            else:
                split["more_short"] = {"task": FROZEN_TASK, "why": why}
            return used + added, capped

        # --- CF-0537: a soft shot over the floor yields to a sharp one under it.
        #
        # The user's decision of 2026-10-05 (delver 0701Z block 2: the phrase's
        # sharp shots at or above 0.22 were spent, and the soft 1920x786
        # trailer shot `ZLXL1L0TfsI:15`, sharpness 0.51, stood 5.6 s while the
        # phrase's sharp shots sat at 0.2194 / 0.2158 / 0.2155). When every cut
        # this block got from its match is `low_sharpness`, the phrase's
        # measured-sharp candidates under the floor (`sharp_under_pool()`) are
        # walked through fill() - every gate applies - and when one survives
        # the soft cuts are dropped and the block is priced
        # `score.low_similarity` like any block filled under the floor. When
        # none survives the soft cuts stay, exactly as before.
        sharp_swap = None
        if used and all(soft_cut(u) for u in used):
            soft = list(used)
            soft_keys = {u["key"] for u in soft}
            keep = later_first_picks(segments, matches, si, args.min_score,
                                     args.score_floor)
            spool = sharp_under_pool(m["candidates"], args.min_score,
                                     args.score_floor, shots_lut,
                                     skip=soft_keys | keep)
            if spool:
                held_back = [pl for pl in placed if pl["key"] in soft_keys
                             and pl["start"] >= start - 1e-6]
                placed[:] = [pl for pl in placed if not any(pl is h for h in held_back)]
                for u in soft:
                    ledger.give_back(u["key"])
                # By rank, never by length - the under-floor rung's own rule
                # (CF-0433/CF-0290: trading the phrase for a longer clip is
                # the delver defect the floor was filed on).
                sharp, sharp_capped = fill(spool)
                if sharp:
                    for u in soft:
                        Path(u["clip"]).unlink(missing_ok=True)
                    used, capped = sharp, capped + sharp_capped
                    sharp_swap = {
                        "task": SHARP_UNDER_TASK,
                        "instead_of": [
                            {"shot": f"{Path(u['key'][0]).stem}:{u['shot']}",
                             "score": u["score"],
                             "sharpness": ((u.get("usability") or {}).get("sharpness")
                                           or {}).get("value")} for u in soft],
                        "shots": [f"{Path(u['key'][0]).stem}:{u['shot']}"
                                  for u in sharp]}
                    rhythm_notes.append(
                        f"block {si}: SHARP UNDER THE FLOOR - every cut over the "
                        f"floor was soft ({', '.join(x['shot'] for x in sharp_swap['instead_of'])}"
                        f"); {len(sharp)} sharp shot(s) of {a['phrase']!r} under "
                        f"{args.min_score} instead ({', '.join(sharp_swap['shots'])}, "
                        f"best {max(u['score'] for u in sharp):.3f}), priced "
                        f"score.low_similarity (CF-0537)")
                else:
                    for u in soft:
                        ledger.take(u["key"])
                    placed.extend(held_back)
                    rhythm_notes.append(
                        f"block {si}: SOFT SHOT KEPT - no sharp shot of "
                        f"{a['phrase']!r} under the floor survived the gates "
                        f"({len(spool)} offered); the soft cut stays (CF-0537)")

        if sharp_swap:
            used, capped = stretch_split(used, capped, spool, "sharp_below_floor")
        else:
            used, capped = stretch_split(used, capped, pool, "match")

        # --- CF-0433: under the floor, when nothing better filled the block.
        #
        # The grill of 2026-09-29 ("делать из того, что дают"): `0929Z` had
        # dozens of candidates at 0.144-0.218 against the 0.22 floor on two
        # topics, and each such block was a hole, a carry or a lost video.
        # Now the best of them - by rank, never by length - fills the block
        # and the plan prices it (`score.low_similarity`, -3 a block, cap
        # -15; build_render_plan.similarity_findings() reads the mark below).
        # Every gate of fill() still applies: the ledger, usable(), the swing
        # rules, repeat_guard. `gate_verdict()` then writes its "using it
        # anyway" record with `best_used_score`, exactly the record it was
        # written for.
        below = None
        if split and (split.get("more") or {}).get("below_floor"):
            # CF-0536: the split went on into the phrase's candidates under
            # the floor - the block is priced like one filled there (CF-0433).
            bf = split["more"]["below_floor"]
            below = {"phrase": a["phrase"], "score": bf["score"],
                     "min_score": bf["min_score"]}
        if sharp_swap and used:
            # CF-0537: the block's pictures are the phrase's sharp shots under
            # the floor - priced like any block filled there (CF-0433).
            below = {"phrase": a["phrase"],
                     "score": round(max(u["score"] for u in used), 4),
                     "min_score": args.min_score, "sharp_swap": sharp_swap}
        if not used:
            bpool = below_floor_pool(m["candidates"], args.min_score,
                                     args.score_floor)
            if side and sides:
                on_side = [c for c in bpool if sides.get(c["source"]) == side]
                bpool = on_side or bpool
            if bpool:
                if not seg["max_shots"]:
                    budget = len(bpool)
                    if band_top is not None and not is_ordered_segment(seg):
                        cap = rhythm.even_shot_budget(band_top, len(blocks),
                                                      len(segments) - si - 1,
                                                      seconds=need, hold_top=hold_top)
                        if cap < budget:
                            budget, capped_by_band = cap, True
                used, capped = fill(bpool)
                # CF-0480: under the floor too - the phrase's own candidates.
                used, capped = stretch_split(used, capped, bpool, "below_floor")
                if used:
                    best = max(u["score"] for u in used)
                    below = {"phrase": a["phrase"], "score": round(best, 4),
                             "min_score": args.min_score}
                    rhythm_notes.append(
                        f"block {si}: UNDER THE FLOOR - the best picture the pool "
                        f"had for {a['phrase']!r} scores {best:.3f} against "
                        f"{args.min_score}; used, and priced score.low_similarity "
                        f"(CF-0433)")

        # CF-0088: the verdict is taken here, after the gates, on what they
        # let through - not on the matcher's best score. Every candidate the
        # gates turned away for this block is in rejected_candidates from
        # `rejected_before` on, and the record names them.
        verdict = gate_verdict(a["phrase"], used, rejected_candidates[rejected_before:],
                               capped, len(pool), args.min_score, ledger)
        if verdict:
            unresolved.append(verdict)

        # CF-0150: and the supply fact beside it, on the same three inputs and
        # deliberately *before* the emergency repeat below. A block saved by
        # repeating a picture this video has already shown was not supplied by
        # the pool, and a record taken after the rescue would say it was. The
        # pre-gate `m["candidates"]` is passed, not the `--score-floor`-filtered
        # `pool`: the floor is a gate, and a gate refusing every offer is not
        # the same event as the matcher having none to offer.
        supply_by_segment[si] = candidate_supply(
            a["phrase"], m["candidates"], used,
            rejected_candidates[rejected_before:], args.min_score)

        # --- CF-0137 rung 2: the emergency shot repeat.
        #
        # The ladder for a block nothing could fill runs: an insert from the
        # library (CF-0138, at the layer stage - this resolver has no library
        # to draw on), then this one repetition, then the assetless rung only
        # where the channel switched it on, then the planner refusing the plan
        # (build_render_plan.py, assetless_rung.py). Here is where the second
        # rung is climbed, because this is where the pool, the ledger and the
        # cut live.
        #
        # Only on an ordered segment. That is not a policy choice, it is where
        # the rung exists: `settle_unresolved()` turns an *unordered* (`even`)
        # gap into a carry into the next anchor's real picture (CF-0124), so
        # there is no assetless block there to save from and nothing to spend
        # the video's one repeat on.
        # --- CF-0337: the topic-footage rung, before any repeat.
        #
        # The user on widows-bay (2026-09-23): on this channel a block with
        # no picture of its phrase gets *any* frame of the topic, never an
        # abstract background and never, first, a picture already shown.
        # Two pools, in order: the matcher's own candidates for this phrase
        # that the floors refused (closest to the phrase first - 0.216 / 0.212
        # / 0.209 on widows-bay against 0.22), then every other shot of every
        # source of the topic. fill() applies every gate a regular pick has -
        # the one-use ledger, the swing rules, the cached and real usable(),
        # repeat_guard - so the rung can only give a new, usable picture.
        # Only when both pools are spent does the block go on to the repeat
        # and past it to the planner's warning; the answer to that is more
        # material (CF-0338), not a background.
        topic = None
        if not used and topic_rung and is_ordered_segment(seg):
            tpool = topic_pool(m["candidates"], index_data, args.min_score,
                               args.score_floor, sups)
            if budget == 1:
                tpool = sorted(tpool, key=lambda c: available_seconds(c) < need)
            before = len(rejected_candidates)
            used, _ = fill(tpool, length_first=budget == 1)
            if used and budget == 1 and not args.no_stretch_split:
                # CF-0480: a frame of the topic, not of the phrase - never
                # split into more of them, only said: the pool did not hold it.
                split = stretch_split_wanted(used[0]["seconds"], need, seg)
                if split:
                    split.update(rung="topic", got=1, short=True, reason=(
                        f"nothing of {a['phrase']!r} survived the gates; the "
                        f"topic's shot {used[0]['seconds']:.2f}s stands for "
                        f"{need:.2f}s (x{split['ratio']}): the pool does not hold "
                        f"this block with motion (CF-0480)"))
            if used:
                u = used[0]
                topic = {
                    "rung": u.get("topic_rung") or "below_floor",
                    "shot": f"{Path(u['key'][0]).stem}:{u['shot']}",
                    "score": u["score"],
                    # The headline only: the full per-candidate list is the
                    # verdict's, already in `unresolved_anchors`.
                    "reason": (verdict["reason"] if verdict else
                               "no candidate survived the gates for this "
                               "block").split(" - ")[0],
                }
                rhythm_notes.append(
                    f"block {si}: TOPIC FOOTAGE - shot {topic['shot']} "
                    f"({topic['rung']}, score {u['score']:.3f}) stands in for "
                    f"{a['phrase']!r}: a frame of the topic, not a picture of "
                    f"the phrase (CF-0337)")
                unresolved.append({"phrase": a["phrase"], "reason":
                    f"filled from the topic's footage - shot {topic['shot']} "
                    f"({topic['rung']}, score {u['score']:.3f}), not a picture "
                    f"of the phrase (CF-0337)"})
            else:
                unresolved.append({"phrase": a["phrase"], "reason":
                    f"the topic-footage rung found no new usable shot in any "
                    f"source of the topic ({len(tpool)} offered, "
                    f"{len(rejected_candidates) - before} refused) - the topic "
                    f"needs more material (CF-0337, CF-0338)"})

        emergency = None
        if not used and is_ordered_segment(seg):
            shortage = verdict["reason"] if verdict else \
                "no candidate survived the gates for this block"
            repeats = [c for c in pool if ledger.count((c["source"], c["shot"]))]
            refused = None
            if seg["role"] == "swing":
                refused = rhythm.REUSE_REFUSED_SWING
            elif not reuse_budget.available():
                refused = reuse_budget.exhausted_reason()
            elif not repeats:
                refused = ("nothing this block matches is already on screen "
                           "anywhere in this video, so there is no shot to "
                           "repeat (CF-0137)")
            if refused:
                unresolved.append({"phrase": a["phrase"], "reason":
                                   f"no emergency repeat for this block: {refused}"})
            else:
                for cand in repeats:
                    key = (cand["source"], cand["shot"])
                    refusal = reuse_budget.allow(seg["role"], key, prev_keys)
                    if refusal:
                        rejected_candidates.append({
                            "phrase": a["phrase"], "shot": cand["shot"],
                            "score": cand["score"],
                            "reason": f"emergency repeat refused: {refusal}"})
                        continue
                    reused, _ = fill([cand], reuse_key=key)
                    if not reused:
                        continue
                    used = reused
                    emergency = reuse_budget.take({
                        "shot": f"{Path(key[0]).stem}:{key[1]}",
                        "source": key[0],
                        "shot_number": key[1],
                        "block": si,
                        "reason": shortage,
                    })
                    rhythm_notes.append(
                        f"block {si}: EMERGENCY REPEAT - shot "
                        f"{emergency['shot']} is shown a second time because "
                        f"{shortage}. This is the video's one repeat "
                        f"(MAX_EMERGENCY_REUSE_PER_VIDEO="
                        f"{reuse_budget.max_uses}); the next block that cannot "
                        f"be filled has no rung left but the planner's refusal "
                        f"(CF-0137). This video needs material.")
                    unresolved.append({"phrase": a["phrase"], "reason":
                        f"filled by the emergency repeat of shot "
                        f"{emergency['shot']} - a picture this video has "
                        f"already shown, not a new one (CF-0137)"})
                    break
                else:
                    unresolved.append({"phrase": a["phrase"], "reason":
                        "the emergency repeat could not be spent here - every "
                        "already-shown candidate was refused or failed to cut "
                        "(CF-0137)"})

        if not used:
            reason = verdict["reason"]
            settled = settle_unresolved(blocks, a, seg, start, end, reason, has_next)
            if settled == SETTLED_BLOCK:
                prev_shot = None
                prev_keys = set()
            elif settled == SETTLED_CARRY:
                unresolved.append({"phrase": a["phrase"], "reason":
                    f"nothing filled this anchor - its {end - start:.2f}s were "
                    f"carried into the next anchor's block (CF-0124) instead of "
                    f"freezing the previous block over them"})
                carry_start = start
            continue

        def block_for(u, b_start, b_end, kind, asset, held):
            return {
                "word_range": [a["word_index"], a["word_index"]],
                "intent": (f"{a['phrase']} (shot {u['shot']}, score {u['score']:.3f}"
                           f"{', title/end card' if u['card'] else ''}"
                           f"{', held frame' if held else ''}"
                           f"{', from moment ' + format(u['moment_at'], '.1f') + 's' if u.get('cut_origin') == 'moment' else ''})"),
                "asset_kind": kind,
                "asset": asset,
                "emphasis_words": a.get("emphasis_words", []),
                "rhythm_role": seg["role"],
                "side": side,
                "shot": f"{Path(u['key'][0]).stem}:{u['shot']}",
                # CF-0047: this block's footage came from a shot the index
                # flagged `is_card` - a frame of somebody else's trailer that
                # happens to be a title/end card. Emphatically NOT CF-0041's
                # `asset_kind: "card"`, which is a card this factory draws
                # itself and which has no file, no rights and no asset gate at
                # all. The two must stay distinguishable: `style_delivered`
                # reads the second to tell intent from shortage, and this one
                # only tells build_render_plan.py how to frame a picture that
                # is text.
                "is_card": bool(u["card"]),
                # CF-0062: the caption crop this clip was cut with, so that
                # build_render_plan.py's gate can tell the same story
                # usable() told above if it rejects the clip on resolution.
                "crop_bottom": u.get("crop_bottom", 0.0),
                "frame_before_crop": u.get("frame_before_crop"),
                # CF-0106: the source timecode this clip actually starts at
                # and why - the shot's head, or MOMENT_LEAD_SECONDS ahead of
                # its `moment_at`. What a comparison check's frame has to be
                # traced to, since the head of a marked shot is not the frame
                # the description was written about.
                "cut_at": u.get("cut_at"),
                "cut_origin": u.get("cut_origin", "head"),
                "moment_at": u.get("moment_at"),
                "held_frame": held,
                **({"topic_fill": topic} if topic else {}),
                # CF-0433: admitted under the similarity floor, priced by the plan.
                **({"below_floor": below} if below else {}),
                # CF-0435: a weak picture (soft rules), priced by the plan.
                # CF-0452: a frame held at the shot's sharpest moment is
                # judged again as held (held_usability).
                **({"usability": held_u} if (held_u := held_usability(u, held)) else {}),
                **({"held_from": u["held_from"]}
                   if held and u.get("held_from") else {}),
                "_start": round(b_start, 3),
                "_end": round(b_end, 3),
            }

        if budget == 1 or (seg["role"] == "swing" and len(used) == 1) \
                or (split and len(used) == 1):
            # An ordered rhythm keeps its cadence: the block spans exactly what
            # the plan said, and a clip too short to fill it is held as a frame
            # rather than reshaping the boundary or freezing on its last frame.
            #
            # CF-0120: a swing block with a budget for several shots and only
            # one shot to spend it on lands here too, and that is the whole
            # answer to "what if there is not enough distinct footage". It
            # degrades down the chain that already exists - the clip is held as
            # a still, and `build_render_plan.py` drops that to typographic if
            # even the still fails a gate - rather than showing the one shot it
            # does have twice. CF-0121 is not bent to fill a hole.
            u = used[0]
            held = u["seconds"] + rhythm.HELD_FRAME_SLACK_SECONDS < need
            kind, asset = "clip", u["clip"]
            if held:
                frame = clips_dir / f"s{si:02d}_held_{Path(u['clip']).stem}.png"
                if hold_frame(u["clip"], u["seconds"], frame, used=u):
                    kind, asset = "still", str(frame)
                else:
                    held = False
            blocks.append(block_for(u, start, end, kind, asset, held))
            if split:
                # CF-0480: the split was wanted and the pool had one shot.
                blocks[-1]["stretch_split"] = split
            if capped_by_band:
                band_caps.append(band_cap_entry(si, budget, 1, start, end, start,
                                                u, held, kind))
                rhythm_notes.append(band_cap_note(band_caps[-1]))
            if emergency is not None:
                # CF-0137: the block carries how it was filled, so the plan
                # (and the batch metadata behind it) says the picture is a
                # second showing rather than a shot of its own.
                blocks[-1]["emergency_reuse"] = emergency
            if prev_shot is not None:
                used_pairs.add((prev_shot, u["key"]))
            prev_shot = u["key"]
            prev_keys = {u["key"]}
            continue

        if seg["role"] == "swing" or split:
            # CF-0480: a stretch split is built exactly like a swing chain -
            # one block, its boundary untouched, distinct shots back to back
            # and the last one held for what is left - with the shot whose
            # held frame reads sharpest put last (CF-0465's proposal).
            split_frames = {}
            if split:
                used, split_frames = sharpest_last(used, clips_dir, si, need,
                                                   frozen_of=frozen_of)
            # CF-0120: one crossing of the axis, several distinct shots inside
            # it. The block boundary is *not* touched - it is still exactly the
            # stretch the script spent on this side, so "a block is a crossing"
            # holds and `swap_ratio`, which is measured over block sides, reads
            # the same as it did when the same stretch was one frozen frame.
            # What changes is what is inside: distinct shots of this side, back
            # to back, filled by the same `fill()` chain `even` uses (CF-0028)
            # and under the same one-sample-one-use ledger (CF-0121), so no
            # shot is recut and none is shown twice.
            cuts, at = [], 0.0
            for u in used:
                seconds = min(u["seconds"], max(0.0, need - at))
                if seconds < MIN_CUT_SECONDS:
                    # What is left of the block is shorter than a picture: the
                    # remainder belongs to the held tail below, not to a cut
                    # nobody can see. The clip stays on disk for nothing, which
                    # is cheaper than a flicker in the montage.
                    break
                cuts.append(split_cut_record({
                    **u, "asset": u["clip"], "kind": "clip", "held_frame": False,
                    "source": u["key"][0], "at": round(at, 3),
                    "seconds": round(seconds, 3)}))
                at += seconds
            # The tail. The shots of this side ran out before the crossing did,
            # so the last picture stands still for what is left - the same
            # `still` rung the single-shot block above uses, and the same
            # sample it was already showing (CF-0075's reading: a half's held
            # frame is the picture still on screen, not a second showing of
            # it). Never another block's shot, and never this one again.
            tail = round(need - at, 3)
            held = bool(cuts) and tail > rhythm.HELD_FRAME_SLACK_SECONDS
            if held:
                last = used[len(cuts) - 1]
                frame = clips_dir / f"s{si:02d}_held_{Path(last['clip']).stem}.png"
                if hold_frame(last["clip"], cuts[-1]["seconds"], frame, used=last):
                    cuts.append({**cuts[-1], "asset": str(frame), "kind": "still",
                                 "held_frame": True, "at": round(at, 3),
                                 "seconds": tail,
                                 **({"held_from": last["held_from"]}
                                    if last.get("held_from") else {})})
                else:
                    held = False
            keep_png = cuts[-1]["asset"] if held else None
            for png, _v in split_frames.values():
                if png != keep_png:
                    Path(png).unlink(missing_ok=True)
            if not cuts:
                # Nothing survived the trim - fall through to the single-shot
                # branch's own accounting by treating it as an unfilled block.
                reason = "no cut of this side was long enough to read"
                unresolved.append({"phrase": a["phrase"], "reason": reason})
                settle_unresolved(blocks, a, seg, start, end, reason, has_next)
                prev_shot = None
                prev_keys = set()
                continue
            shots = [c["shot"] for c in cuts[:len(cuts) - 1 if held else len(cuts)]]
            first = used[0]
            if split:
                split["held_seconds"] = tail if held else 0.0
                if held:
                    v = (split_frames.get(used[len(cuts) - 2]["clip"])
                         or (None, None))[1]
                    split["held_sharpness"] = None if v is None else round(v, 4)
                    hm = frozen_probes.get(used[len(cuts) - 2]["clip"])
                    if hm:
                        # CF-0536: what the held frame was found to be
                        split["held_motion"] = {k: hm.get(k) for k in
                                                ("motion", "face_area", "frozen")}
            blocks.append({
                "word_range": [a["word_index"], a["word_index"]],
                "intent": (f"{a['phrase']} ({len(shots)} shots of "
                           + (f"the phrase (stretch split, CF-0480)"
                              if split and seg["role"] != "swing"
                              else f"side {side!r}")
                           + ": " + ", ".join(shots)
                           + (f", held {tail:.2f}s" if held else "") + ")"),
                "asset_kind": "sequence",
                # One picture per entry, in order, exactly the shape a
                # `side_by_side` half carries (CF-0075) - so build_render_plan.py
                # frames them the same way and nothing downstream has to learn a
                # second way of reading a sequence of pictures.
                "cuts": cuts,
                # CF-0120 item 5: the provenance the Analyst reads - which shots
                # this one crossing was assembled from, in order.
                "swing_block_shots": shots,
                "emphasis_words": a.get("emphasis_words", []),
                "rhythm_role": seg["role"],
                "side": side,
                # The first picture's fields on the block itself, so every
                # reader that knew one shot per block still gets an answer.
                "shot": cuts[0]["shot"],
                "is_card": bool(first["card"]),
                "crop_bottom": first.get("crop_bottom", 0.0),
                "frame_before_crop": first.get("frame_before_crop"),
                "cut_at": first.get("cut_at"),
                "cut_origin": first.get("cut_origin", "head"),
                "moment_at": first.get("moment_at"),
                # The block as a whole does not stand still - only its tail
                # might, and `cuts` says which entry that is.
                "held_frame": False,
                **({"stretch_split": split} if split else {}),
                **({"topic_fill": topic} if topic else {}),
                # CF-0433: admitted under the similarity floor, priced by the plan.
                **({"below_floor": below} if below else {}),
                "_start": round(start, 3),
                "_end": round(end, 3),
            })
            # CF-0034 by shots, not by blocks: every adjacent pair the viewer
            # sees is recorded, including the ones inside this block, so the
            # next block cannot rebuild a pair that has already been shown.
            keys = [u["key"] for u in used[:len(shots)]]
            for x, y in zip([prev_shot] + keys, keys):
                if x is not None:
                    used_pairs.add((x, y))
            prev_shot = keys[-1]
            prev_keys = set(keys)
            continue

        # `even`: each cut becomes its own block, sharing the anchor's stretch.
        t = start
        for u in used:
            seg_end = min(end, t + u["seconds"])
            if seg_end - t < 0.5:
                break
            blocks.append(block_for(u, t, seg_end, "clip", u["clip"], False))
            if prev_shot is not None:
                used_pairs.add((prev_shot, u["key"]))
            prev_shot = u["key"]
            prev_keys = {u["key"]}
            t = seg_end
        over_hold = (capped_by_band and t < end and len(used) >= budget
                     and len(blocks) > segment_first_block[si]
                     and rhythm.over_band_top(end - blocks[-1]["_start"], hold_top))
        if over_hold:
            # CF-0370: the hold the budget asks for would outrun the pattern's
            # hold band, so it is not made - the shortfall goes the CF-0028
            # way below, and the numbers say why.
            rhythm_notes.append(
                f"segment {si}: budgeted to {budget} shot(s), but holding the "
                f"last picture to the segment's end would stand "
                f"{end - blocks[-1]['_start']:.2f}s against the drawn hold top "
                f"{hold_top}s - not held; the {end - t:.2f}s left go the "
                f"ordinary shortfall way (CF-0370)")
        if capped_by_band and t < end and len(used) >= budget and \
                not over_hold and len(blocks) > segment_first_block[si]:
            # CF-0370: the budget, not the pool, stopped the chain - so the
            # last picture holds the rest of the segment instead of the
            # shortfall being carried (which would only move the chain on).
            last = blocks[-1]
            u = next(x for x in used if x["clip"] == last["asset"])
            length = end - last["_start"]
            held = u["seconds"] + rhythm.HELD_FRAME_SLACK_SECONDS < length
            kind = "clip"
            if held:
                frame = clips_dir / f"s{si:02d}_held_{Path(u['clip']).stem}.png"
                if hold_frame(u["clip"], u["seconds"], frame, used=u):
                    blocks[-1] = block_for(u, last["_start"], end, "still",
                                           str(frame), True)
                    kind = "still"
                else:
                    held = False
            if kind == "clip":
                last["_end"] = round(end, 3)
            band_caps.append(band_cap_entry(
                si, budget, len(blocks) - segment_first_block[si], start, end,
                last["_start"], u, held, kind))
            rhythm_notes.append(band_cap_note(band_caps[-1]))
            t = end
        if t < end and blocks:
            # Candidates ran out before covering the anchor's full span (CF-0028).
            # Stretching this block's _end used to be the only option here, but
            # the clip is only u["seconds"] long - past that it holds on its
            # last frame, which qc_render.py then catches as a frozen block with
            # no record of why. Carry the shortfall into the next anchor's start
            # instead, so the next real clip arrives early rather than this one
            # freezing. Only the last anchor has no "next" to carry into, so it
            # keeps the old stretch-and-freeze fallback - CF-0011's design
            # session is the place to do better than that.
            shortfall = round(end - t, 3)
            if has_next:
                unresolved.append({"phrase": a["phrase"], "reason":
                    f"resolved candidates cover only {t - start:.2f}s of {need:.2f}s "
                    f"needed - {shortfall}s shortfall carried into the next anchor's "
                    f"block instead of freezing this clip's last frame"})
                carry_start = t
            else:
                unresolved.append({"phrase": a["phrase"], "reason":
                    f"resolved candidates cover only {t - start:.2f}s of {need:.2f}s "
                    f"needed - {shortfall}s shortfall with no next anchor to carry "
                    f"into, so the last clip's block was stretched to fill (may "
                    f"freeze on its last frame)"})
                blocks[-1]["_end"] = round(end, 3)

    # If the earliest anchor(s) never produced a block, the first real block
    # starts partway through the video instead of at 0 - the same hole
    # CF-0008 fixed mid-video, just at the leading edge where there is no
    # "previous block" to extend forward into, only a next one to pull back.
    #
    # CF-0276 narrowed what this line is for. The lead-in before the first
    # anchor's word is no longer its business: `_base_segments()` opens
    # segment 0 at 0.00s, so the layout - and every ceiling the layout is held
    # to - already accounts for it. What is left here is the case the comment
    # above names and only that one: a segment that resolved to no block at
    # all. Silently extending a picture past a ceiling nobody re-checked is
    # what turned a 15-block staccato plan whose longest block was 3.40s into
    # a video whose longest was 4.86s, against contrast's 3.5s.
    if blocks and blocks[0]["_start"] > 0:
        blocks[0]["_start"] = 0.0

    # CF-0150: the supply fact onto every block, by the segment that built it.
    # The key is written on *all* of them, `null` included: absent means "this
    # plan predates the fact" and null means "the pool delivered here", and a
    # reader that cannot tell those apart (rotation/shortage.py reads historic
    # records) would read every old plan as a pool that delivered.
    anchor_supply = []
    for si, first in enumerate(segment_first_block):
        last = (segment_first_block[si + 1] if si + 1 < len(segment_first_block)
                else len(blocks))
        for b in blocks[first:last]:
            b["candidate_supply"] = supply_by_segment.get(si)
        if si in length_by_segment:
            lengths = length_supply(*length_by_segment[si])
            for b in blocks[first:last]:
                b["length_supply"] = lengths
        # ...and the same answer once per anchor, whether or not it left a
        # block behind. On `even` a segment nothing could fill is carried into
        # the next anchor (CF-0124) and has no block of its own, so a record
        # that lives only on blocks is silent about exactly the anchors the
        # pool failed hardest. `block_index` is null for those - the fact is
        # still true of the anchor, it just has no picture to hang on.
        seg = segments[si]
        ai = driver_anchor(seg, matches)
        anchor_supply.append({
            "segment": si,
            "phrase": anchors[ai]["phrase"],
            "block_index": first if last > first else None,
            "block_count": last - first,
            "start": round(float(seg["start"]), 3),
            "end": round(float(seg["end"]), 3),
            "supply": supply_by_segment.get(si),
        })

    # CF-0879: every block's named people, and the blocks that still show
    # somebody else's face under them (measure, CF-0320).
    def _shot_by_key(vid, n):
        try:
            return shots_by_key.get((vid, int(n)))
        except (TypeError, ValueError):
            return None
    person_risky = person_shot.block_risks(blocks, words, people, _shot_by_key,
                                           source_titles.get)
    for r in person_risky:
        print(f"  PERSON SHOT RISK (measure, CF-0879): block {r['block']} names "
              f"{', '.join(r['names_person'])}, shows {r['shot']}: "
              f"{'; '.join(r['reasons'])}", file=sys.stderr)

    out = {
        "script_id": spec.get("script_id"),
        "style": spec.get("style", "motion"),
        # CF-0290: the similarity floor this storyboard was resolved against,
        # so the planner's `unresolved_anchor` gate judges a picture by the
        # number that screened its pool rather than by its own default. An
        # absent key means a storyboard from before the screen existed.
        "min_score": args.min_score,
        "resolved_from_anchors": True,
        # CF-0041: the order this plan was built to answer, carried forward so
        # build_render_plan.py can compare it against what degradation left.
        "rhythm": {
            "pattern_requested": order["pattern_id"],
            # What was ordered upstream, always - never overwritten by what
            # this file managed to build. `rhythm_built` is what the block plan
            # was actually laid out as, and the two differ exactly when the
            # footage could not carry the order (alternate with one source).
            "rhythm_requested": ordered_rhythm,
            "rhythm_built": order["rhythm_id"],
            "parameters": params,
            "opening_requested": opening_requested,
            "opening_delivered": opening_delivered,
            # CF-0050: the beat the frame was held alone for before the first
            # word, measured off the alignment. Non-zero without a cold_frame
            # order simply means the voiceover starts a little late.
            "lead_silence": lead_silence,
            # Where the two sides came from, and what they are. `sides` is the
            # source partition and is null whenever the script declared its own
            # sides - the two answers are not interchangeable and the Analyst
            # has to be able to tell which one a video was cut on.
            "sides_from": sides_from,
            "sides": sides,
            "anchor_sides": anchor_sides if sides_from == "script" else None,
            "anchor_count": len(anchors),
            "planned_block_count": len(segments),
            # CF-0276: the pattern's drawn hold band as this layout answered
            # it, written before a clip was cut. `breaches` is empty on a
            # layout that fits - which is the ordinary case and the fact a
            # reader needs to see, so it is written whole rather than only
            # when something went wrong. `lead_before_first_anchor` is
            # reported either way: it is the screen time the writing left
            # without an anchor, the number behind the one breach this task
            # was opened on, and the one CF-0277's side of the fix aims at.
            "hold_ceiling": hold_ceiling,
            # CF-0370: the drawn block-count ceiling as this plan answered it -
            # which unordered segments were budgeted, which of them hold a
            # frame, and what no budget could bring under the top.
            "block_band_cap": block_band_report(band_top, pattern_file, segments,
                                                blocks, band_caps),
            "notes": rhythm_notes,
        },
        "blocks": blocks,
        # CF-0150: what the pool had for each anchor, one entry per segment in
        # segment order. Parallel to the per-block `candidate_supply`, never
        # instead of it: the block copy is what build_render_plan.py carries
        # into the refusal record, this one is what a measurement over a whole
        # corpus can be taken on without a block to hang the answer on.
        "anchor_supply": anchor_supply,
        # CF-0428: the most blocks this pool can put on screen, whatever the
        # anchors say - the bound build_render_plan.py reads a pace floor
        # against to tell "rewrite the anchors" from "the pool is too thin".
        "pool_capacity": pool_capacity(
            index_data, sups, blocks, cut_refused_keys, ledger.retired,
            args.min_short_side, args.min_coverage, args.max_black,
            reuse_cap=args.max_shot_reuse),
        "unresolved_anchors": unresolved,
        "rejected_candidates": rejected_candidates,
        # CF-0791: the root's pre-cut shot rule - its mode, what it found on
        # the shots shown (`warn` keeps them and says so) and how many
        # candidates it took out (`fail`).
        "shot_guard": shot_guard_record(blocks, rejected_candidates),
        # CF-0904: the strip on blur the plan's own probe will ask for, and
        # every cut held back past the allowance for a cover-ready shot.
        "strip_picks": {"task": STRIP_PICK_TASK,
                        "allow_seconds": shot_score.STRIP_ALLOW_SECONDS,
                        "spare_cuts": STRIP_SPARE_CUTS,
                        "probe_strip_seconds": round(strip_state["seconds"], 3),
                        "picks": strip_picks},
        # CF-0545: which blocks retell the event, what the guard took away
        # and where the event's own footage did not carry the phrase.
        "event_footage": event_footage_record(
            event_guard, anchors, event_dec, event_refused, found_before,
            matches),
        # CF-0879: who the script names, what the person screen took away,
        # where it had to keep a foreign face, and which blocks still show one.
        person_shot.RECORD: person_shot.record(people, person_refused,
                                               person_kept, person_risky),
        # CF-0088: run-level facts the operator would otherwise only have
        # seen scroll past on stderr - today, that top-N filtered nothing.
        "warnings": warnings,
        # CF-0567: shots of our own recording whose text flag was exempted by
        # their kind (entity_guard.own_capture_exemption) - [] on every other pool.
        "own_capture_exempt": own_capture_exempt,
        # CF-0397: which channel memory this video was resolved against and
        # what it cost - how many candidates it turned away.
        "retired_shots": {
            "registry": retired.path, "exempt": retired.exempt,
            # CF-0532: the video a rebuild replaces - its shots stay on offer
            "also_exempt": retired.also_exempt,
            "retired": len(retired),
            "refused": sum(1 for r in rejected_candidates
                           if "(CF-0397)" in str(r.get("reason", "")))},
    }
    if exclusions:
        missed = exclusion_misses(exclusions, blocks)
        if missed:
            # The storyboard being replaced stays on disk untouched: a re-cut
            # that did not re-cut is not written over the one it was for.
            raise SystemExit(
                "RECUT NOT APPLIED: " + "; ".join(
                    f"{m['shot']} is still on block {m['still_on_block']} of "
                    f"the anchor it was excluded from (asked for block "
                    f"{m.get('block')}) - this block is not filled through "
                    f"the candidate pool (an opening split or a card)"
                    for m in missed))
        out["excluded_candidates"] = exclusions
        report = recut_report(previous_blocks or [], blocks, exclusions)
        out["recut"] = report
        for c in report["blocks"]:
            print(f"  RECUT: block {c['block']}: {', '.join(c['before'])} -> "
                  f"{', '.join(c['after']) or 'no picture'}", file=sys.stderr)
        for c in report["changed_elsewhere"]:
            print(f"  RECUT: block {c['block']} changed too: "
                  f"{', '.join(c['before']) or '-'} -> "
                  f"{', '.join(c['after']) or '-'}", file=sys.stderr)
        if report["block_count"][0] != report["block_count"][1]:
            print(f"  RECUT: block count {report['block_count'][0]} -> "
                  f"{report['block_count'][1]}", file=sys.stderr)
    ev = out["event_footage"]
    if ev["needs_supplement"]:
        # CF-0545: said where the operator reads, like CF-0088's warnings.
        w = ("event footage (CF-0545): "
             + (f"{len(ev['short'])} block(s) retelling scene {ev['scene_id']} "
                f"have none of the event's own footage over the floor once the "
                f"interview is out" if ev["short"] else ev["why"])
             + " - the pool wants a supplement of the event's footage (CF-0345)")
        out["warnings"].append(w)
        print(f"WARNING: {w}", file=sys.stderr)
    # CF-0648: how this storyboard was resolved, so build_render_plan.py can
    # re-cut a held frame held_screen flags with the same inputs. The
    # exclusions are not in it - they carry over from the storyboard itself.
    out["resolve_call"] = resolve_call(sys.argv[1:])
    json.dump(out, open(args.output, "w"), indent=2)
    print(f"{len(anchors)} anchors -> {len(segments)} {order['rhythm_id']} segment(s) "
          f"-> {len(blocks)} blocks -> {args.output}")
    for n in rhythm_notes:
        print(f"  RHYTHM: {n}", file=sys.stderr)
    for u in unresolved:
        print(f"  UNRESOLVED: {u['phrase']} - {u['reason']}", file=sys.stderr)


@video_script("video-editor", "resolve", name="resolve_anchors.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    main()


if __name__ == "__main__":
    cli()
