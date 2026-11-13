#!/usr/bin/env python3
"""CF-0140: can the pool show these anchors - asked on its own, before TTS.

The hole this closes
--------------------
Today the order is script -> TTS -> plan -> resolve. The resolve is last, so
"there is nothing to show here" surfaces when the voiceover is already
synthesised and the length of the video is already fixed; the Content
Researcher places anchors blind and regularly asks for a frame the pool cannot
give. CF-0123 decided that the answer has to come *before* the writing is
paid for, and hard: an anchor the pool cannot picture is refused and the
script is rewritten.

This module is the Editor's half of that - the *judgement*, not the order of
stages. It answers, for a list of anchor phrases and a pool of indexes,
whether each anchor has a frame behind it, and when it has not, why - in the
CF-0139 shortage vocabulary the rotation already reads. It resolves nothing,
cuts nothing, writes no clips and repairs no anchor. build_render_plan.py's
stage order is untouched and the real resolve stays exactly where it is; this
duplicates its judgement, ahead of time, and never replaces it.

Why it cannot judge differently from the real resolve
----------------------------------------------------
That is the whole risk of the idea: a preflight that is more lenient than
resolve_anchors.py passes a script straight into the hole it exists to
prevent, and one that is stricter throws away scripts that would have worked.
So this file owns no rule of its own. Every judgement in it is made by
calling the resolver's own code:

  * the candidates come from `resolve_anchors.match()` - the same subprocess
    call to the indexer's `match_anchors.py`, with the same `--top` and
    `--min-score` defaults (`resolve_anchors.DEFAULT_TOP` /
    `DEFAULT_MIN_SCORE`, which is why those are constants now);
  * a candidate under either floor is dropped by
    `resolve_anchors.screen_pool()` - CF-0088's `--score-floor` and CF-0290's
    `--min-score`, the resolver's own single screen. CF-0290 is why `weak` is
    a refusal here now and not a note: the resolver no longer offers an
    under-floor frame to a block at all, so an anchor whose whole pool is
    under the floor gets no picture there, and a preflight that passed it
    would be the lenient preflight this module exists not to be;
  * every remaining candidate is screened by
    `resolve_anchors.precut_refusal()` - the mark, the span and the cached
    usability pre-filter, extracted from `fill()` so there is exactly one
    copy of them in the repository;
  * the verdict on what survives is `resolve_anchors.gate_verdict()`, the
    post-gate verdict CF-0088 built for the storyboard's
    `unresolved_anchors`. `covered` here is literally "gate_verdict() would
    have said nothing about this anchor".

`tests/test_anchor_coverage_preflight.py` pins both halves of that: that the
gate is one function with three callers, and that this module and a real
`resolve_anchors.main()` run reach the same verdict on the same pool.

What it still cannot promise
----------------------------
`absent` is certain: the resolver will find nothing there either, because
every check this module applies is a check the resolver applies. `covered` is
a *necessary* condition and not a sufficient one, and saying so plainly is
better than implying otherwise:

  * the real `usable()` runs on the cut clip and needs ffmpeg and the source
    file - a shot with no cached measurement (an index built before CF-0029,
    or a probe that failed) is only judged there;
  * the reuse cap, the swing rules and the side-by-side opening's spent
    frames are facts about a *video*, not about a candidate, and there is no
    video yet at preflight time.

The reuse cap is the one of those that shows up as a script-wide shortage
rather than a per-anchor one - two anchors whose only surviving sample is the
same shot cannot both have it (CF-0121: one sample, one use). `contention()`
below answers exactly that much of it, as a maximum matching between anchors
and the distinct samples that survived screening: if fewer anchors can be
given a sample of their own than there are anchors, that many blocks *must*
end up without a picture, whichever order the resolver picks them in. It is a
lower bound on the shortage and never names which anchor loses, because which
one loses depends on the block plan and there is none yet.

Usage
-----
    anchor_coverage.py <anchors.json|-> --index <shots.json> [--index ...]
        [--min-score 0.22] [--top 10] [--score-floor F] [--strict]
        [--min-delivery-height 720] [--min-coverage C] [--max-black B]
        [--matcher-python PATH] [--out report.json] [--quiet]

Input is the anchors file resolve_anchors.py already takes
(`{"anchors": [{"phrase": ...}, ...]}`), a bare JSON list of phrases, or
either of those on stdin as `-`. Output is one JSON object on stdout (or to
`--out`). Exit 0 when every anchor is covered, 2 when the pool cannot carry
this script, 1 on a broken input or a matcher that failed.
"""
import argparse
import json
import sys
from pathlib import Path

import resolve_anchors
from resolve_anchors import (CAUSE_FOOTAGE_UNUSABLE, CAUSE_NO_FOOTAGE,
                             DEFAULT_MIN_SCORE, DEFAULT_TOP,
                             MAX_BLACK_CLIPS)
from common import MIN_COVERAGE, MIN_SHORT_SIDE
from rhythm import MAX_EMERGENCY_REUSE_PER_VIDEO

# The record's own name, the way `assetless_rung.DEFICIT_KIND` names the
# refusal record. A reader that is handed a JSON object should be able to tell
# what it is looking at without being told.
KIND = "anchor_coverage_preflight"

# The three answers, and there are exactly three.
#
#   covered  something in the pool survives every check that can be made
#            before a cut, and it scores at or over --min-score. The anchor
#            has a frame behind it.
#   weak     something survives, but the best of it is under --min-score.
#            The resolver would use it anyway and record the anchor as
#            unresolved (CF-0088): there will be a picture in that block, and
#            it is not a picture of this anchor. Not a hole, and not a
#            covered anchor either - which is why it is its own word and not
#            folded into either neighbour.
#   absent   nothing survives. This is a hole, and it is the one verdict that
#            is certain rather than necessary-but-not-sufficient.
VERDICTS = ("covered", "weak", "absent")

# What `--strict` adds: `weak` counts as a refusal too. Off by default,
# because CF-0140's hard constraint is about an anchor the pool cannot
# picture at all, and a weak match is a job for the Compliance Checker's
# judgement of content (CF-0043's second level), not for a threshold here.
STRICT_HELP = ("refuse a weak anchor too - one whose best surviving candidate "
               "is under --min-score, i.e. the pool can put a picture there "
               "but not a picture of this")


def load_anchors(data):
    """The phrases to screen, out of whatever shape the caller wrote.

    Three accepted forms, because the caller of this module is the Content
    Researcher's validator and it has not written an anchors file yet when it
    asks - at preflight time there is no voiceover, so there are no word
    indices either. `phrase` is the only field this module reads.

      {"anchors": [{"phrase": "..."}, ...]}   resolve_anchors.py's own file
      {"phrases": ["...", ...]}
      ["...", ...]  /  [{"phrase": "..."}, ...]

    Raises ValueError with what was wrong, which the CLI turns into exit 1.
    """
    if isinstance(data, dict):
        items = data.get("anchors", data.get("phrases"))
        if items is None:
            raise ValueError("no `anchors` and no `phrases` in the input object")
    elif isinstance(data, list):
        items = data
    else:
        raise ValueError(f"expected a JSON object or list, got {type(data).__name__}")
    if not isinstance(items, list):
        raise ValueError("`anchors`/`phrases` has to be a list")
    phrases = []
    for i, item in enumerate(items):
        if isinstance(item, str):
            phrase = item
        elif isinstance(item, dict):
            phrase = item.get("phrase")
        else:
            raise ValueError(f"anchor {i} is a {type(item).__name__}, not a phrase "
                             f"or an object with one")
        if not isinstance(phrase, str) or not phrase.strip():
            raise ValueError(f"anchor {i} has no `phrase`")
        phrases.append(phrase.strip())
    if not phrases:
        raise ValueError("no anchors to screen")
    return phrases


def sample_name(cand):
    """`<source stem>:<shot>` - the name a block's `shot` field already
    carries, so a preflight record and a storyboard name the same picture the
    same way."""
    return f"{Path(str(cand['source'])).stem}:{cand['shot']}"


def screen_anchor(m, shots_lut, min_short_side, min_coverage, max_black,
                  score_floor=None, min_score=DEFAULT_MIN_SCORE, anchor_index=0):
    """One anchor's record: what the pool offers it and what survives.

    Every judgement here is the resolver's own - see this module's docstring.
    Pure: no file is opened, nothing is cut, `shots_lut` is only read.
    """
    offered = list(m["candidates"])
    refusals, survivors = [], []
    for cand in offered:
        kept, floored = resolve_anchors.screen_pool([cand], min_score, score_floor)
        if floored:
            refusals.append({
                "shot": sample_name(cand), "score": cand["score"],
                # A candidate that matches nothing well enough to be offered
                # is the pool not depicting this anchor, not a frame that
                # could not be taken - so it is the other cause.
                "cause": CAUSE_NO_FOOTAGE,
                "reason": floored[0]["reason"]})
            continue
        _at, _origin, _span, refusal = resolve_anchors.precut_refusal(
            cand, shots_lut.get((cand["index"], cand["shot"])),
            min_short_side, min_coverage, max_black)
        if refusal:
            refusals.append({"shot": sample_name(cand), "score": cand["score"],
                             "cause": refusal["cause"],
                             "reason": refusal["record"]["reason"]})
            continue
        survivors.append(cand)

    # The resolver's own post-gate verdict, on what would have survived to be
    # cut. `gate_verdict()` wants `rejected` records shaped the way `fill()`
    # appends them (a bare shot number and a reason), and `capped` is 0 here:
    # the reuse cap is a fact about a video and there is none yet - what this
    # module can say about it is script-wide and lives in contention().
    used = [{"shot": c["shot"], "score": c["score"]} for c in survivors]
    rejected = [{"shot": r["shot"], "score": r["score"], "reason": r["reason"]}
                for r in refusals]
    verdict = resolve_anchors.gate_verdict(m["phrase"], used, rejected, 0,
                                           len(offered), min_score)

    # CF-0290: which of the two "no picture" answers this is, taken from the
    # resolver's own supply vocabulary rather than from a rule of this
    # module's. `pool_offered_off_topic` is the anchor whose pool was ranked
    # and whose best offer is under the floor - nothing here depicts the
    # phrase - and that is `weak`. Everything else that survives nothing is
    # `absent`: frames that exist and cannot be taken, or no frame at all.
    supply = resolve_anchors.candidate_supply(m["phrase"], offered, used,
                                              rejected, min_score)
    off_topic = bool(supply) and supply["code"] == resolve_anchors.POOL_OFFERED_OFF_TOPIC

    if verdict is None:
        name, cause, detail = "covered", None, ""
    elif off_topic:
        # Until CF-0290 this was "not a hole: the resolver uses it anyway",
        # `covered: true`, and a refusal only under `--strict`. The resolver
        # does not use it any more - `screen_pool()` takes it out of the pool -
        # so the honest verdict is that this anchor has no picture, under its
        # own name because the remedy differs: `weak` is answered by buying
        # footage that depicts the phrase, `absent` by footage that survives
        # the usability gates.
        name, cause = "weak", CAUSE_NO_FOOTAGE
        detail = verdict["reason"]
    else:
        # Nothing survived. Which of the two footage causes it is turns on
        # whether the pool offered anything this anchor could have used at
        # all: no candidate (or none over the score floor) is the pool not
        # depicting this - `no_footage`, the one cause CF-0023's shopping
        # list is about. Candidates that existed and were refused are frames
        # that could not be taken - `footage_unusable`. The split is the same
        # one rotation/shortage.py draws and is kept apart for the same
        # reason: they send the operator to two different places.
        name = "absent"
        cause = (CAUSE_FOOTAGE_UNUSABLE
                 if any(r["cause"] == CAUSE_FOOTAGE_UNUSABLE for r in refusals)
                 else CAUSE_NO_FOOTAGE)
        detail = verdict["reason"] if offered else "no shot in any index"

    best = max((c["score"] for c in survivors), default=None)
    offered_best = max((c["score"] for c in offered), default=None)
    return {
        # The anchor's position in the list that was handed in - the only
        # handle a caller has on it, since there is no plan and no block yet.
        "anchor_index": anchor_index,
        "phrase": m["phrase"],
        "verdict": name,
        # CF-0290: `weak` is no longer covered. An anchor the pool only has
        # under-floor frames for reaches the resolver and comes out of it with
        # no picture at all.
        "covered": name == "covered",
        "cause": cause,
        "best_score": None if best is None else round(best, 4),
        "best_offered_score": None if offered_best is None else round(offered_best, 4),
        "candidates": len(offered),
        "survivors": len(survivors),
        # Distinct, best first: what contention() matches anchors against,
        # and what a caller can read to see *which* frames an anchor rests on.
        "samples": list(dict.fromkeys(sample_name(c) for c in survivors)),
        # CF-0009's margin check, carried through rather than re-judged: a
        # phrase that singles out no shot describes an idea rather than a
        # frame. Reported, never a refusal - that judgement is the Compliance
        # Checker's (CF-0043).
        "discriminative": bool(m.get("discriminative", True)),
        "detail": detail,
        "refusals": refusals,
    }


def _max_matching(sample_lists):
    """How many of these anchors can be given a sample of their own.

    Kuhn's augmenting-path matching over a bipartite graph of anchors and
    samples. Exact, and small: the anchor count is the script's, a dozen at
    most, and each anchor's list is `--top` long times the index count.
    """
    taken = {}  # sample -> anchor position in `sample_lists`

    def assign(a, seen):
        for s in sample_lists[a]:
            if s in seen:
                continue
            seen.add(s)
            if s not in taken or assign(taken[s], seen):
                taken[s] = a
                return True
        return False

    return sum(1 for a in range(len(sample_lists)) if assign(a, set()))


def contention(records, emergency=MAX_EMERGENCY_REUSE_PER_VIDEO):
    """How many anchors must go without a picture because the pool has to
    show the same sample twice - the one video-wide rule this module can
    answer ahead of time.

    CF-0121: one sample, one use. So two anchors whose only surviving
    candidate is the same shot cannot both be given it, however good the
    match is, and the second one becomes a hole at resolve time with nothing
    per-anchor about it - which is exactly the kind of surprise this whole
    task exists to move earlier. A maximum matching between the anchors that
    *have* survivors and the distinct samples behind them says how many can
    be served at once; the rest cannot, whichever order the resolver walks
    them in. Anchors already `absent` are left out, because they are counted
    as holes once already.

    `short_after_repeat` deducts CF-0137's one emergency repeat per video -
    the rung that exists precisely to close one such hole. Deliberately
    generous: this is a hard constraint on a writer, and being wrong in the
    direction of refusing a script that would have worked is the worse
    mistake. The repeat has conditions of its own (it may not sit next to its
    own first use), so a script that leans on it is not guaranteed - which is
    why both numbers are reported and only the deducted one decides `passed`.
    """
    contested = [r for r in records if r["verdict"] != "absent"]
    lists = [r["samples"] for r in contested]
    matched = _max_matching(lists)
    short = len(contested) - matched
    distinct = len({s for ss in lists for s in ss})
    after = max(0, short - emergency)
    if short == 0:
        note = (f"{len(contested)} anchor(s) with a frame behind them, "
                f"{distinct} distinct sample(s) - each can have one of its own")
    else:
        note = (f"{len(contested)} anchor(s) have a frame behind them but only "
                f"{distinct} distinct sample(s) between them: {short} of them "
                f"must go without a picture at resolve time, because one sample "
                f"may be shown once (CF-0121). {emergency} emergency repeat(s) "
                f"per video (CF-0137) leave {after} unanswered")
    return {"anchors": len(contested), "distinct_samples": distinct,
            "matched": matched, "short_by": short,
            "emergency_repeats": emergency, "short_after_repeat": after,
            "note": note}


def assess(matches, index_data, min_short_side=MIN_SHORT_SIDE,
           min_coverage=MIN_COVERAGE, max_black=MAX_BLACK_CLIPS,
           score_floor=None, min_score=DEFAULT_MIN_SCORE, strict=False,
           indexes=None):
    """The whole report, over a matcher result that has already been fetched.

    Split from `preflight()` so the judgement can be tested without a
    subprocess, and so a caller that already ran `resolve_anchors.match()`
    (which is not cheap - it loads CLIP) does not run it twice.
    """
    shots_lut = resolve_anchors.shot_lookup(index_data)
    records = [screen_anchor(m, shots_lut, min_short_side, min_coverage,
                             max_black, score_floor, min_score, i)
               for i, m in enumerate(matches)]
    crowd = contention(records)

    absent = [r["anchor_index"] for r in records if r["verdict"] == "absent"]
    weak = [r["anchor_index"] for r in records if r["verdict"] == "weak"]
    refused_because = []
    if absent:
        refused_because.append("absent_anchors")
    if crowd["short_after_repeat"]:
        refused_because.append("sample_contention")
    if weak:
        # CF-0290: with or without `--strict`. `--strict` used to be the only
        # way this refused a weak anchor, on the reading that "the resolver
        # uses it anyway"; it does not, so the flag has nothing left to
        # tighten here and is kept only so a caller that passes it still runs.
        refused_because.append("weak_anchors")
    passed = not refused_because

    if passed:
        note = f"every one of {len(records)} anchor(s) has a frame in the pool"
    else:
        parts = []
        if absent:
            parts.append(f"{len(absent)} anchor(s) the pool cannot picture "
                         f"(anchor(s) {absent})")
        if crowd["short_after_repeat"]:
            parts.append(f"{crowd['short_after_repeat']} anchor(s) beyond what the "
                         f"distinct samples can carry ({crowd['note']})")
        if weak:
            parts.append(f"{len(weak)} anchor(s) the pool only has under-floor "
                         f"frames for - nothing ranked for them scores {min_score} "
                         f"or better, so the resolver will offer them nothing "
                         f"(CF-0290; anchor(s) {weak})")
        note = ("this pool cannot carry this script: " + "; ".join(parts)
                + ". Rewrite the anchors against what the pool has - the "
                  "`samples` of the covered anchors are what it can actually "
                  "show (CF-0140)")

    return {
        "kind": KIND,
        "passed": passed,
        "refused_because": refused_because,
        "anchor_count": len(records),
        "covered_count": sum(1 for r in records if r["verdict"] == "covered"),
        "weak": weak,
        "absent": absent,
        "min_score": min_score,
        "score_floor": score_floor,
        "strict": bool(strict),
        "indexes": list(indexes if indexes is not None else index_data),
        "pool": {"sources": len(index_data),
                 "shots": sum(len(d.get("shots", [])) for d in index_data.values())},
        "contention": crowd,
        "anchors": records,
        "note": note,
    }


def preflight(phrases, indexes, min_score=DEFAULT_MIN_SCORE, top=DEFAULT_TOP,
              matcher_python=resolve_anchors.DEFAULT_INDEXER_PY,
              min_short_side=MIN_SHORT_SIDE, min_coverage=MIN_COVERAGE,
              max_black=MAX_BLACK_CLIPS, score_floor=None, strict=False):
    """Ask the matcher, then judge. The one call that touches a subprocess.

    Importable on purpose: a caller in this repository (or a sibling agent
    running this interpreter) can have the answer without going through the
    CLI and back through JSON.
    """
    if not phrases:
        # CF-0689: every anchor of the script places one of its own graphics -
        # nothing to ask the pool, and no pool is not a hole here.
        rec = assess([], {}, min_short_side, min_coverage, max_black,
                     score_floor, min_score, strict, indexes=indexes)
        rec["note"] = ("no anchor asks the pool - every one places a graphic the "
                       "factory draws (CF-0689)")
        return rec
    matches, index_data = resolve_anchors.match(indexes, phrases, min_score,
                                                top, matcher_python)
    return assess(matches, index_data, min_short_side, min_coverage, max_black,
                  score_floor, min_score, strict, indexes=indexes)


def report_lines(rec):
    """The stderr lines. Written on a pass too, for the reason CF-0118 and
    CF-0137 both write theirs: a run that never says whether the pool could
    carry the script cannot be audited afterwards."""
    lines = [f"anchor coverage {'passed' if rec['passed'] else 'REFUSED'}: {rec['note']}"]
    for r in rec["anchors"]:
        head = (f"  [{r['verdict']}] {r['phrase']!r}"
                + (f" - {r['cause']}" if r["cause"] else ""))
        if r["verdict"] == "covered":
            head += f" ({r['survivors']} sample(s), best {r['best_score']})"
        lines.append(head)
        if r["detail"]:
            lines.append(f"      {r['detail']}")
    lines.append(f"  contention: {rec['contention']['note']}")
    return lines


def main():
    p = argparse.ArgumentParser(
        description="CF-0140: whether the footage pool can picture these "
                    "anchors, asked before the script is paid for in TTS. "
                    "Judges, never resolves.")
    p.add_argument("anchors", help="anchors JSON, or `-` for stdin")
    p.add_argument("--index", action="append", required=True,
                   help="a footage index (shots.json); repeatable, exactly as "
                        "resolve_anchors.py takes it")
    p.add_argument("--min-score", type=float, default=DEFAULT_MIN_SCORE)
    p.add_argument("--top", type=int, default=DEFAULT_TOP,
                   help="candidates the matcher offers per phrase and index - "
                        "the same knob resolve_anchors.py runs with, and it has "
                        "to be the same number for this answer to mean anything")
    p.add_argument("--score-floor", type=float, default=None,
                   help="CF-0088: a candidate under this is never offered")
    p.add_argument("--strict", action="store_true", help=STRICT_HELP)
    p.add_argument("--min-delivery-height", type=int, default=MIN_SHORT_SIDE)
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE)
    p.add_argument("--max-black", type=float, default=MAX_BLACK_CLIPS)
    p.add_argument("--matcher-python", default=resolve_anchors.DEFAULT_INDEXER_PY)
    p.add_argument("--out", default=None,
                   help="write the report here instead of stdout")
    p.add_argument("--quiet", action="store_true",
                   help="no human-readable lines on stderr")
    p.add_argument("--channel", default=None,
                   help="CF-0791: the channel id (or channels/<id>.json) whose "
                        "video_editor.shot_guard mode the pre-cut screening runs "
                        "in, as resolve_anchors.py --channel; without it the "
                        "root's default (`warn`, refuses nothing)")
    args = p.parse_args()
    resolve_anchors.configure_shot_guard(resolve_anchors.channel_id_of(args.channel))

    try:
        raw = sys.stdin.read() if args.anchors == "-" else Path(args.anchors).read_text()
        phrases = load_anchors(json.loads(raw))
    except (OSError, ValueError) as e:
        print(f"anchor_coverage.py: cannot read the anchors: {e}", file=sys.stderr)
        return 1

    rec = preflight(phrases, args.index, args.min_score, args.top,
                    args.matcher_python, args.min_delivery_height,
                    args.min_coverage, args.max_black, args.score_floor,
                    args.strict)

    text = json.dumps(rec, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    if not args.quiet:
        for line in report_lines(rec):
            print(line, file=sys.stderr)
    # 0 the pool carries this script, 2 it does not. 2 rather than 1 for the
    # same reason build_render_plan.py refuses a plan with 2: a refusal is an
    # answer this tool was asked for, not a failure to answer.
    return 0 if rec["passed"] else 2


if __name__ == "__main__":
    sys.exit(main())
