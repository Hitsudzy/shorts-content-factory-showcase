#!/usr/bin/env python3
"""CF-0140: the anchors come from the script, and the pool is asked before TTS.

What changed
------------
Anchors used to be *written here*, at step 4, after the voiceover was already
synthesised. That is the hole CF-0140 closes: the pool cannot be asked about a
frame nobody has named yet, so "there is nothing to show here" surfaced when
the speech and the length of the video were already paid for. Since CF-0140 the
Content Researcher writes the frames it needs into `03-content-researcher.json`
as `visual_anchors[]` - `anchor_id`, `phrase` (the frame, in words), `beat_text`
(a verbatim substring of one of the counted sections) and an optional `side` -
and its own step 6 holds them against the batch's footage pool before the script
is ever handed over.

This module is the Video Editor's side of that contract. It does two things and
neither of them is an editorial judgement:

  * `preflight` - ask `anchor_coverage.py` whether the pool *this stage will
    resolve against* can picture every phrase, before `synthesize_voiceover.py`
    is run;
  * `spec`     - turn `visual_anchors[]` plus the forced alignment into the
    anchors file `resolve_anchors.py` takes, by locating each `beat_text` in
    `words.json`.

Why the phrase is copied and never rewritten
--------------------------------------------
A rephrased anchor is a different question to the matcher: "a wooden cottage
house by a lake" scored 0.188 and "two people sitting on a deck overlooking a
lake with trees" scored 0.264 - on the same shot. The preflight answered for the
phrase the writer wrote; an editor who improves the wording afterwards has
thrown that answer away and is back to placing anchors blind, which is the whole
of what CF-0140 removes. So this file copies `phrase` verbatim, adds no anchor
of its own, and the only thing it may do to the list is *drop* an entry whose
words are not in the voiceover (below). A script that needs different moments
goes back to the Content Researcher: a rewrite of the words is cheaper than the
synthesis, the plan and the montage it saves.

Three decisions this file makes, and why
----------------------------------------
**A script with no `visual_anchors` is handed back (exit 2), never filled in
here.** The field is mandatory upstream, but scripts written before CF-0140 sit
on disk without it. The tempting fallback - "no anchors declared, so write them
the old way" - is precisely today's behaviour restored in silence: nothing would
ever have asked the pool, and the preflight would be guarding phrases nobody
uses. Worse, it is invisible: the run looks identical to a compliant one. An old
script is not a compliant script that happens to be missing a field; its
narration was written without the pool ever being consulted, so re-running the
Content Researcher on it is the only thing that produces what CF-0140 promises.
The refusal costs one stage of writing and no TTS.

**A `beat_text` that cannot be located drops that one anchor, loudly, and never
guesses a word index.** The Editor restructures the narration for prosody
(step 2) before TTS, and Kokoro then drops or slurs the occasional word, so the
alignment is not the script's text. `meme_layer.locate_beat()` - the one beat
locator in this repository, already used by the meme, sound and proof layers -
absorbs that with a fuzzy window (`BEAT_MATCH_MIN_RATIO`). When even that fails,
the words the picture was supposed to arrive on are not in the voiceover: any
index chosen here would put the frame on a moment the writer did not ask for,
which is the same lie as a rewritten phrase, only harder to see. So the anchor is
dropped, named in `dropped[]` and on stderr, and belongs in the report.

**And the report is told which of the two drops it is (CF-0235).** `the script
does not say these words` and `the script says them and our aligner lost them`
are different news - the first sends the script back to the writer, the second
is ours to fix and costs the writer nothing - and until CF-0235 both arrived as
`ANCHOR DROPPED [beat_not_found]`, which is why the report could not tell the
Editor what to do about it. The reason is now `meme_layer.beat_failure()`'s own
code, the same three the proof, meme and sound layers answer with, and the drop
carries that function's `evidence`: the fragment searched for, how much of it is
in the script and in the alignment, and the stretch of the voiceover that came
closest as it was actually heard. If every
anchor drops, the script is handed back (exit 2) - a video with no anchors has no
montage to derive.

Two anchors that locate to the *same first word* are the same case seen from the
other end: the resolver derives block boundaries from anchor starts, so two
anchors on one word ask for two pictures in a stretch of zero seconds. The later
one is dropped as `beat_collision` and recorded.

**A preflight that refuses here hands the script back too - it does not repair
anything.** The pool this stage resolves against is regularly *narrower* than
the one the Content Researcher asked about: compliance pass 2
(`04-compliance-checker.json`) clears only some of the fetched sources, and that
file exists by the time this stage starts. So a script that passed there can
have a hole here, and that is a new fact rather than a repeat of the same
question. The answer to it is a rewrite by the writer, with the report's
`samples` and the pool inventory in hand - never a phrase edited here, never the
CF-0137 degradation ladder. That ladder answers "this block could not be
filled" *after* a plan exists; this is "the pool cannot picture what the script
asks for", before a second of speech has been synthesised, and running the video
anyway spends exactly what CF-0140 exists to save.

**And a refusal here leaves a record, not only an exit code (CF-0282).** The
preflight used to end in exit 2, a headline on stderr and a report nobody
downstream read, so the batch's own artifact said nothing about the script and
the root's funnel reported the loss as `not_built` - "the Editor neither
rendered nor refused it" - about a script the Editor had refused before
spending a second of TTS. The refusal now goes through `plan_refusal` (CF-0254),
the same mechanism the plan builder's gates use: a `<report stem>.refusal.json`
sidecar beside `--out`, gate `anchor_preflight`, funnel code `pool_too_thin`,
with the counts it refused on. `write_batch_metadata.py` finds it under
`<batch>/work/<slug>/` without a flag, so the operator's next step after a
refusal is that one command and the loss lands under the Editor's own code.
Running the preflight without `--out` leaves nowhere to write it, and the run
says so on stderr.

Usage
-----
    script_anchors.py preflight <03-content-researcher.json> --script-id <id>
        --index <shots.json> [--index ...] [--strict] [--out report.json] [--quiet]

    script_anchors.py spec <03-content-researcher.json> --script-id <id>
        --words <words.json> --out <anchors.json> [--style motion]
        [--opening-card TEXT]

**CF-0330 (the user, 2026-09-23): the pool verdict is a warning now.** Two
videos the user accepted for publication were refused here on the rebuild of
2026-09-23 - one of them by a best candidate of 0.2198 against a floor of 0.22.
"The anchor is not covered" is an observation about the measurer; it is not
"the video is bad". `preflight` still measures and still writes the report, but
an uncovered pool now writes `anchor_preflight.warning.json` (the same gate,
code and numbers, `severity: warn`) and exits 0. Everything above about a
rewrite being the right answer to a thin pool still describes the *best* move -
it is no longer a stop.

Exit codes, the same three words the rest of the stage uses:
  0  fine - including a pool that does not cover every anchor (CF-0330: a
     warning is recorded, the script goes on)
  2  the script goes back to the Content Researcher (a verdict, not a failure) -
     no `visual_anchors`, every anchor lost in the alignment, or (CF-0356) a
     text gate of the Researcher's the script never passed: `preflight` asks
     them first (`text_gates.py`) and records the refusal as
     `work/<slug>/text_gates.refusal.json`, gate `text_gates`, code `thin_scene`
  1  the question could not be asked: unreadable file, unknown `--script-id`,
     broken `words.json`, a text gate that could not judge
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import anchor_coverage  # noqa: E402
import meme_layer  # noqa: E402
import plan_refusal  # noqa: E402 - CF-0282: a refusal here is a record, not just an exit code
import text_gates  # noqa: E402 - CF-0356: the Researcher's text gates, asked before the pool
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

FIELD = "visual_anchors"
# What this stage reads. `anchor_id` is carried through for the report and is
# not required to be well-formed here: the shape of the field (its regex, its
# uniqueness, its forbidden keys) is the Content Researcher's own gate, and a
# second copy of one contract is how two copies drift.
READ_KEYS = ("phrase", "beat_text")
# CF-0689: an entry that places one of the script's own graphics carries
# `graphic_id` (shared/own_graphic.py ANCHOR_KEY) instead of a pool `phrase` -
# nothing is asked of the pool for it, the Video Editor draws it in Remotion.
GRAPHIC_KEY = "graphic_id"
GRAPHICS_FIELD = "graphics"
SIDES = ("a", "b")

# The sections TTS reads, in the order it reads them - the same three the
# Content Researcher's `narration_budget.counted_sections` names by default and
# the order `meme_layer.locate_beat()` already assumes. The scene direction is
# never spoken, so no anchor can be pinned to it.
SPOKEN_SECTIONS = ("hook", "commentary", "payoff")

EXIT_OK, EXIT_CANNOT_ANSWER, EXIT_HAND_BACK = 0, 1, 2

# Why an anchor is not in the spec. Closed, and every reason is about the
# alignment rather than about the pool - the pool's vocabulary is CF-0139's and
# lives in anchor_coverage.py.
#
# CF-0235: the beat half of this list is `meme_layer.beat_failure()`'s three
# codes and not a fourth vocabulary of our own. The predicate that drops an
# anchor is the predicate that refuses a proof, a meme and a sound - one
# locator, one set of words for why it came back empty - and the Editor's
# report needs the distinction most of all, because `beat_missing_in_script`
# hands the script back to the writer while `beat_unmatched_in_alignment` is
# ours to fix with the script untouched.
DROP_BEAT_COLLISION = "beat_collision"
DROP_REASONS = meme_layer.BEAT_FAILURE_CODES + (DROP_BEAT_COLLISION,)

# What the report is told to do about each of them, in one line.
DROP_DETAIL = {
    meme_layer.BEAT_MISSING_IN_SCRIPT:
        "these words are not in the narration either - the picture is pinned to a "
        "sentence the video never says, so no alignment could have given it back; "
        "the script goes back to the writer and no word index is guessed here",
    meme_layer.BEAT_UNMATCHED_IN_ALIGNMENT:
        "the script says these words and the forced alignment did not give them "
        "back - ours to fix, not the writer's; no word index is guessed for them",
    meme_layer.BEAT_NO_ALIGNMENT:
        "there is no alignment to look these words up in at all; no word index is "
        "guessed for them",
}


class HandBack(Exception):
    """The script goes back to the Content Researcher. A verdict about a
    script, never about the environment."""


class CannotAnswer(Exception):
    """The question could not be asked at all. Never a verdict on a script."""


# --------------------------------------------------------------------------
# the field the writer filled in
# --------------------------------------------------------------------------

def load_script(path, script_id):
    """One script out of `03-content-researcher.json`.

    `--script-id` is required rather than defaulted to the first script: a
    batch carries four of them, and silently anchoring the wrong one produces a
    video that is wrong in a way no gate downstream can see.
    """
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {path}: {exc}")
    scripts = data.get("scripts")
    if not isinstance(scripts, list) or not scripts:
        raise CannotAnswer(f"{path}: no `scripts` to read")
    for script in scripts:
        if isinstance(script, dict) and script.get("script_id") == script_id:
            return script
    known = ", ".join(str((s or {}).get("script_id")) for s in scripts if isinstance(s, dict))
    raise CannotAnswer(f"{path}: no script with script_id {script_id!r} (has: {known})")


def visual_anchors(script):
    """`visual_anchors[]`, validated only as far as this stage reads it.

    The shape is the Content Researcher's own check
    (`check_anchor_coverage.py`); repeating it here would be a second copy of
    one contract. What this refuses is what it cannot use: a missing field, an
    empty one, and an entry with no `phrase` or no `beat_text`. All of them are
    hand-backs, because the alternative in every case is this stage inventing
    the frame - the thing CF-0140 took away from it.
    """
    anchors = script.get(FIELD)
    script_id = script.get("script_id")
    if anchors is None:
        raise HandBack(
            f"script {script_id}: no `{FIELD}` - the frames a script has to show are "
            f"written before TTS so the pool can be asked (CF-0140), and a script "
            f"without them was written blind. The Video Editor does not write them "
            f"instead: that is exactly the pre-CF-0140 behaviour, and it would make "
            f"the preflight guard phrases nobody uses. Send the script back to the "
            f"Content Researcher to declare its anchors")
    if not isinstance(anchors, list) or not anchors:
        raise HandBack(f"script {script_id}: `{FIELD}` is empty or not a list - "
                       f"at least one moment of every script has to be seen")
    for i, anchor in enumerate(anchors):
        if not isinstance(anchor, dict):
            raise HandBack(f"script {script_id}: {FIELD}[{i}] is not an object")
        for key in read_keys(anchor):
            value = anchor.get(key)
            if not isinstance(value, str) or not value.strip():
                raise HandBack(f"script {script_id}: {FIELD}[{i}].{key} is missing or "
                               f"empty - nothing here may be filled in for the writer")
    return anchors


def is_graphic_anchor(anchor):
    """CF-0689: does this entry place one of the script's own graphics?"""
    gid = (anchor or {}).get(GRAPHIC_KEY)
    return isinstance(gid, str) and bool(gid.strip())


def read_keys(anchor):
    """What this stage reads of one entry: a graphic anchor has no `phrase`."""
    return ("beat_text",) if is_graphic_anchor(anchor) else READ_KEYS


def pool_anchors(anchors):
    """The anchors the pool is asked about - every one but a graphic's."""
    return [a for a in anchors if not is_graphic_anchor(a)]


def phrases(anchors):
    """The frames, verbatim. This is what the preflight asks about and what
    `resolve_anchors.py` will later ask the matcher - the same string in both,
    which is the only reason the preflight's answer means anything.
    CF-0689: a graphic anchor asks the pool nothing and is not among them."""
    return [a["phrase"].strip() for a in pool_anchors(anchors)]


# --------------------------------------------------------------------------
# beat_text -> word_index
# --------------------------------------------------------------------------

def beat_expected_index(script, beat_text):
    """Where in the *spoken* narration these words sit, in words - or None.

    The counted sections are read in this order, so the expected index of a
    beat is the words of the sections before it plus the words of its own
    section before the substring. `meme_layer.locate_beat()` computes this for
    the commentary alone, which is all its own callers need; an anchor may be
    pinned to the hook or the payoff, and a payoff is required to echo the
    hook's wording (Content Researcher SKILL.md), so two identical windows are
    a real case here and the tie has to be broken by the section the writer
    took the words from.
    """
    before = 0
    for section in SPOKEN_SECTIONS:
        text = script.get(section)
        if not isinstance(text, str):
            continue
        at = text.find(beat_text)
        if at >= 0:
            return before + len(meme_layer.norm_tokens(text[:at]))
        before += len(meme_layer.norm_tokens(text))
    return None


def spec_anchors(anchors, script, words):
    """`(kept, dropped)` - the anchors as `resolve_anchors.py` takes them.

    The word index is `meme_layer.locate_beat()`'s first word and nothing else.
    That function is the repository's single beat locator (the meme, the sound
    and the proof layers all call it), so an anchor and an insert pinned to the
    same words land on the same word, and there is one place where "these words
    in this alignment" is defined.
    """
    kept, dropped, taken = [], [], {}
    for anchor in anchors:
        anchor_id = anchor.get("anchor_id")
        span = meme_layer.locate_beat(anchor["beat_text"], script, words,
                                      expected=beat_expected_index(script, anchor["beat_text"]))
        if span is None:
            # CF-0235: which of the two faults, and the evidence to check it by.
            why = meme_layer.beat_failure(anchor["beat_text"], script, words)
            near = why.get("nearest") or {}
            dropped.append({"anchor_id": anchor_id, "phrase": anchor.get("phrase"),
                            "beat_text": anchor["beat_text"],
                            "reason": why["code"],
                            "detail": f"{DROP_DETAIL[why['code']]} "
                                      f"({why['in_script_coverage']} of its words are in "
                                      f"the script, {why['alignment_coverage']} in the "
                                      f"alignment; nearest heard at word "
                                      f"{near.get('word_index')}: {near.get('text')!r})",
                            "evidence": why})
            continue
        first = span[0]
        if first in taken:
            dropped.append({"anchor_id": anchor_id, "phrase": anchor.get("phrase"),
                            "beat_text": anchor["beat_text"],
                            "reason": DROP_BEAT_COLLISION,
                            "detail": f"lands on word {first}, already held by "
                                      f"{taken[first]!r} - two anchors on one word ask "
                                      f"for two pictures in a stretch of zero seconds"})
            continue
        taken[first] = anchor_id
        side = anchor.get("side")
        entry = {"anchor_id": anchor_id, "phrase": anchor.get("phrase"),
                 "word_index": first,
                 "side": side if side in SIDES else None}
        if is_graphic_anchor(anchor):
            # CF-0689: no phrase - the block is the graphic this id names.
            entry["phrase"] = None
            entry[GRAPHIC_KEY] = anchor[GRAPHIC_KEY].strip()
        kept.append(entry)
    kept.sort(key=lambda a: a["word_index"])
    return kept, dropped


def build_spec(script, kept, style="motion", opening_card=None):
    """The anchors file `resolve_anchors.py` reads. `script_id` and `style` are
    carried so the storyboard names the script it came from."""
    spec = {"script_id": script.get("script_id"), "style": style,
            "anchors": kept}
    # CF-0689: the order of every graphic a kept anchor places, copied from
    # the script's `graphics[]` unread - resolve_anchors.py writes it on the
    # block and build_render_plan.py checks it (shared/own_graphic.py). An id
    # the script does not order is left out here and refused at the plan.
    placed = {a[GRAPHIC_KEY] for a in kept if a.get(GRAPHIC_KEY)}
    if placed:
        ordered = script.get(GRAPHICS_FIELD) if isinstance(script.get(GRAPHICS_FIELD), list) else []
        graphics = {}
        for g in ordered:
            gid = g.get("graphic_id") if isinstance(g, dict) else None
            if gid in placed and gid not in graphics:
                graphics[gid] = g
        spec[GRAPHICS_FIELD] = graphics
    if opening_card:
        spec["opening_card"] = {"text": opening_card}
    return spec


def load_words(path):
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError) as exc:
        raise CannotAnswer(f"cannot read {path}: {exc}")
    words = data.get("words") if isinstance(data, dict) else data
    if not isinstance(words, list) or not words:
        raise CannotAnswer(f"{path}: no words in the alignment")
    return words


# --------------------------------------------------------------------------
# the two commands
# --------------------------------------------------------------------------

def refusal_numbers(rec):
    """CF-0282: what the preflight refused on, as numbers.

    Read off the report rather than recomputed, so the record and the report
    can never disagree: `contention` is `anchor_coverage.assess()`'s own
    arithmetic and `pool` is the inventory it judged against.
    """
    contention = rec.get("contention") or {}
    pool = rec.get("pool") or {}
    return {
        "anchors": rec.get("anchor_count"),
        "covered": rec.get("covered_count"),
        "absent": len(rec.get("absent") or []),
        "weak": len(rec.get("weak") or []),
        "distinct_samples": contention.get("distinct_samples"),
        "without_a_picture": contention.get("short_by"),
        "unanswered_after_repeat": contention.get("short_after_repeat"),
        "sources": pool.get("sources"),
        "shots": pool.get("shots"),
        "indexes": [str(i) for i in (rec.get("indexes") or [])],
        "refused_because": list(rec.get("refused_because") or []),
        # CF-0330: the floor and, per anchor the pool did not cover, how close
        # it came - `everyday-sorcery-2` was refused on a best candidate of
        # 0.2198 against 0.22, and a record that cannot say so cannot show
        # that the refusal was measurement noise.
        "min_score": rec.get("min_score"),
        "uncovered": [
            {"anchor_index": a.get("anchor_index"), "phrase": a.get("phrase"),
             "verdict": a.get("verdict"), "cause": a.get("cause"),
             "best_score": a.get("best_score"),
             "best_offered_score": a.get("best_offered_score"),
             "candidates": a.get("candidates"), "survivors": a.get("survivors")}
            for a in (rec.get("anchors") or [])
            if isinstance(a, dict) and not a.get("covered", True)],
    }


def refusal_reason(rec, numbers):
    """The gate's sentence for `refusals[]`, self-contained.

    It has to read in a table of losses with nothing beside it but the code,
    so it carries the counts in words - a reader of the funnel should not have
    to open the batch to learn how thin the pool was.
    """
    def n(key):
        v = numbers.get(key)
        return "?" if v is None else v
    lines = [
        f"{n('anchors')} anchor(s), {n('distinct_samples')} distinct usable "
        f"sample(s), {n('without_a_picture')} without a picture",
        f"{n('absent')} absent and {n('weak')} weak of {n('anchors')}",
        f"judged against {n('sources')} source(s) / {n('shots')} shot(s): "
        + (", ".join(Path(i).name for i in numbers.get("indexes") or []) or "none"),
        "refused because " + (", ".join(numbers.get("refused_because") or []) or "?"),
        rec.get("note") or "",
    ]
    return plan_refusal.reason_text("ANCHORS NOT COVERED", lines)


def record_refusal(rec, out):
    """The refusal sidecar beside the preflight's report (CF-0282).

    Before this, a preflight refusal was exit 2, a headline on stderr and
    nothing on disk that the batch's own artifact could be built from: the
    funnel read `05-video-editor.json`, found neither a video nor a refusal
    for the script, and printed `not_built` - the observer's inference about a
    stage that had in fact refused out loud (batch example-film/2026-09-18T1058Z,
    lf-2026-09-18-003-script1). The sidecar is the same mechanism CF-0254
    gave the plan builder's gates, so `write_batch_metadata.py` collects it
    from `<batch>/work/<slug>/` with no flag and the loss lands under the
    Editor's own code.

    `out` is the report's path; without one there is no work directory to write
    into and the caller is told so rather than the refusal going unrecorded.
    """
    numbers = refusal_numbers(rec)
    reason = refusal_reason(rec, numbers)
    if not out:
        print("REFUSAL NOT RECORDED: run the preflight with "
              "--out <batch>/work/<slug>/anchor_preflight.json so the refusal "
              "reaches 05-video-editor.json -> refusals[] (CF-0282); without it "
              "the funnel can only report this script as `not_built`",
              file=sys.stderr)
        return None
    path = plan_refusal.write(out, rec.get("script_id"),
                              plan_refusal.GATE_ANCHOR_PREFLIGHT, reason,
                              deficit=out, numbers=numbers)
    print(f"REFUSAL RECORDED [{plan_refusal.code_for(plan_refusal.GATE_ANCHOR_PREFLIGHT)}"
          f"/{plan_refusal.GATE_ANCHOR_PREFLIGHT}] {path} - run "
          f"write_batch_metadata.py <batch> so it reaches "
          f"05-video-editor.json -> refusals[]", file=sys.stderr)
    return path


def record_warning(rec, out):
    """CF-0330: the preflight's finding as a warning, not a refusal.

    The user, 2026-09-23: `anchor_preflight` / `pool_too_thin` goes back to a
    warning. The record is the one `record_refusal()` would write - gate,
    code, sentence, numbers - with `severity: warn`, beside the report as
    `anchor_preflight.warning.json`; `build_render_plan.py` reads it from the
    same work directory into `plan["warnings"]`. A refusal sidecar a
    previous run left beside the same report is removed: it is this script's
    own earlier verdict, and leaving it would list a video that goes on in
    `refusals[]`.
    """
    numbers = refusal_numbers(rec)
    reason = refusal_reason(rec, numbers)
    gate = plan_refusal.GATE_ANCHOR_PREFLIGHT
    print(f"ANCHORS NOT COVERED - WARNING, the script goes on "
          f"[{plan_refusal.code_for(gate)}/{gate}] ({plan_refusal.WARN_DECISION}): "
          f"{reason}", file=sys.stderr)
    if not out:
        print("WARNING NOT RECORDED: run the preflight with "
              "--out <batch>/work/<slug>/anchor_preflight.json so the warning "
              "reaches the plan and 05-video-editor.json -> videos[].warnings",
              file=sys.stderr)
        return None
    stale = plan_refusal.sidecar_path(out)
    try:
        stale.unlink()
    except OSError:
        pass
    path = plan_refusal.write_warning(out, rec.get("script_id"), gate, reason,
                                      numbers=numbers, deficit=out)
    print(f"WARNING RECORDED [{plan_refusal.code_for(gate)}/{gate}] {path}",
          file=sys.stderr)
    return path


TEXT_GATES_HEADLINE = "SCRIPT DID NOT PASS THE TEXT GATES"
TEXT_GATES_REPORT = "text_gates.json"


def check_text_gates(args, script):
    """CF-0356: the Researcher's text gates, before the pool and the TTS.

    A script that carries a passing record goes on untouched; one that does
    not is judged by the Researcher's own gate, run here read-only
    (`text_gates.judge()`). Returns None when every gate passed, else the exit
    code of a refusal - recorded beside the report as
    `work/<slug>/text_gates.refusal.json` (gate `text_gates`, code
    `thin_scene`). A gate that cannot judge is `CannotAnswer`."""
    work = Path(args.out).parent if args.out else None
    try:
        verdict = text_gates.judge(args.script, script, work_dir=work)
    except text_gates.CannotJudge as exc:
        raise CannotAnswer(f"the Researcher's text gates could not be asked: {exc}")
    report = work / TEXT_GATES_REPORT if work else None
    if report is not None:
        report.write_text(json.dumps(verdict, indent=2, ensure_ascii=False) + "\n")
    if not getattr(args, "quiet", False) or not verdict["passed"]:
        print(f"text gates ({text_gates.RESEARCHER.name}):", file=sys.stderr)
        for line in text_gates.report_lines(verdict):
            print(line, file=sys.stderr)
    if verdict["passed"]:
        return None
    record_text_gates_refusal(verdict, report)
    print(f"{TEXT_GATES_HEADLINE}: do not synthesize. The script goes back to the "
          f"Content Researcher with the gate's own sentence above - the Editor "
          f"cannot rewrite it, and the defect would otherwise surface in "
          f"build_render_plan.py after the TTS (CF-0356).", file=sys.stderr)
    return EXIT_HAND_BACK


def record_text_gates_refusal(verdict, report):
    """The refusal sidecar beside `work/<slug>/text_gates.json` (CF-0356), the
    same mechanism as `record_refusal()`."""
    gate = plan_refusal.GATE_TEXT_GATES
    lines = []
    for g in text_gates.failed(verdict):
        how = (f"not in 03 ({g.get('recorded')}), run by the Editor: "
               if g["source"] == text_gates.SOURCE_RUN else "")
        lines.append(f"{g['script']} [{g.get('record', g['reading'])}] {how}"
                     f"{g.get('action')}: {g.get('reason') or ''}")
    reason = plan_refusal.reason_text(TEXT_GATES_HEADLINE, lines)
    numbers = {"gates_failed": len(text_gates.failed(verdict)),
               "gates_asked": len(verdict["gates"])}
    if report is None:
        print("REFUSAL NOT RECORDED: run the preflight with "
              "--out <batch>/work/<slug>/anchor_preflight.json so the refusal "
              "reaches 05-video-editor.json -> refusals[] (CF-0356)", file=sys.stderr)
        return None
    path = plan_refusal.write(report, verdict.get("script_id"), gate, reason,
                              deficit=report, numbers=numbers)
    print(f"REFUSAL RECORDED [{plan_refusal.code_for(gate)}/{gate}] {path} - run "
          f"write_batch_metadata.py <batch> so it reaches "
          f"05-video-editor.json -> refusals[]", file=sys.stderr)
    return path


def run_preflight(args):
    script = load_script(args.script, args.script_id)
    anchors = visual_anchors(script)
    if not args.index and pool_anchors(anchors):
        # CF-0814: an empty pool is only legitimate for an all-graphic script
        raise CannotAnswer("--index is required: an anchor asks the pool (no "
                           "`graphic_id`) - which pool is it?")
    # CF-0356: the writing before the pool - a script the Researcher's text
    # gates never passed does not reach the matcher, let alone the TTS.
    refused = check_text_gates(args, script)
    if refused is not None:
        return refused
    # No --min-score and no --top, here or on the command line: both this and
    # the real resolve take resolve_anchors.DEFAULT_MIN_SCORE / DEFAULT_TOP,
    # and a knob at this seam is exactly how the two answers drift apart.
    rec = anchor_coverage.preflight(phrases(anchors), args.index,
                                    matcher_python=args.matcher_python,
                                    strict=args.strict)
    rec["script_id"] = script.get("script_id")
    # CF-0689: `anchor_index` in the records counts the pool anchors only.
    rec["anchor_ids"] = [a.get("anchor_id") for a in pool_anchors(anchors)]
    rec["graphic_anchors"] = [a.get("anchor_id") for a in anchors if is_graphic_anchor(a)]
    text = json.dumps(rec, indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(text)
    else:
        print(text)
    if not args.quiet:
        for line in anchor_coverage.report_lines(rec):
            print(line, file=sys.stderr)
        if not rec["passed"] and not plan_refusal.warns(plan_refusal.GATE_ANCHOR_PREFLIGHT):
            print(HAND_BACK_LINE, file=sys.stderr)
    if rec["passed"]:
        return EXIT_OK
    if plan_refusal.warns(plan_refusal.GATE_ANCHOR_PREFLIGHT):
        # CF-0330: an uncovered anchor is a fact about the measurer, not a
        # verdict on the video. The script goes on to the TTS; an anchor that
        # still finds nothing at resolve time becomes a block on the
        # assetless rung, which warns in its turn (assetless_rung.py).
        record_warning(rec, args.out)
        return EXIT_OK
    # CF-0282: the record, always - `--quiet` silences the human lines, never
    # the batch's own account of a loss.
    record_refusal(rec, args.out)
    return EXIT_HAND_BACK


HAND_BACK_LINE = (
    "ANCHORS NOT COVERED: do not synthesize. The pool this stage resolves against "
    "cannot picture this script - hand it back to the Content Researcher with the "
    "absent anchors, the contention line and each anchor's `samples` (what the pool "
    "can show instead). Do not reword a phrase here and do not resolve anyway: the "
    "preflight answered for the writer's wording, and a hole found now costs a "
    "rewrite instead of the synthesis, the plan and the montage.")


def run_spec(args):
    script = load_script(args.script, args.script_id)
    anchors = visual_anchors(script)
    words = load_words(args.words)
    kept, dropped = spec_anchors(anchors, script, words)
    for rec in dropped:
        print(f"ANCHOR DROPPED [{rec['reason']}] {rec['anchor_id']}: "
              f"{rec['beat_text']!r} - {rec['detail']}", file=sys.stderr)
    if not kept:
        # CF-0235: the count per reason, because "the writer named sentences the
        # video never says" and "our aligner lost sentences the script has" are
        # two different things to do next, and this line is where the Editor
        # reads which one happened.
        tally = ", ".join(f"{sum(1 for d in dropped if d['reason'] == r)} {r}"
                          for r in DROP_REASONS
                          if any(d["reason"] == r for d in dropped))
        raise HandBack(
            f"script {script.get('script_id')}: none of its {len(anchors)} anchor(s) "
            f"could be located in the alignment ({tally}) - the voiceover does not "
            f"contain the words any picture was pinned to. Nothing is invented here; "
            f"the script goes back to the Content Researcher (or the narration was "
            f"restructured past recognition in step 2, or - on "
            f"{meme_layer.BEAT_UNMATCHED_IN_ALIGNMENT} - the alignment is ours to fix "
            f"and the script is not at fault)")
    spec = build_spec(script, kept, args.style, args.opening_card)
    Path(args.out).write_text(json.dumps(spec, indent=2, ensure_ascii=False))
    print(f"anchors: {len(kept)} written to {args.out}"
          + (f", {len(dropped)} dropped" if dropped else "")
          + " (phrases copied from visual_anchors, never rewritten)", file=sys.stderr)
    return EXIT_OK


@video_script("video-editor", "anchors", name="script_anchors.py")
def main(argv=None):
    p = argparse.ArgumentParser(
        description="CF-0140: the anchors are the script's, not the Editor's - "
                    "asked of the pool before TTS, turned into word indices after "
                    "alignment.")
    sub = p.add_subparsers(dest="command", required=True)

    pre = sub.add_parser("preflight", help="can the pool picture this script's "
                                           "anchors? Run before synthesize_voiceover.py")
    pre.add_argument("script", help="the batch's 03-content-researcher.json")
    pre.add_argument("--script-id", required=True)
    pre.add_argument("--index", action="append", default=[],
                     help="a footage index (shots.json) - repeatable, and it has to be "
                          "the same list resolve_anchors.py will be given; may be "
                          "absent only when every anchor is one of the script's own "
                          "graphics (CF-0814)")
    pre.add_argument("--strict", action="store_true", help=anchor_coverage.STRICT_HELP)
    pre.add_argument("--matcher-python", default=None)
    pre.add_argument("--out", default=None, help="write the report here instead of stdout")
    pre.add_argument("--quiet", action="store_true")

    spec = sub.add_parser("spec", help="write the anchors file resolve_anchors.py takes")
    spec.add_argument("script", help="the batch's 03-content-researcher.json")
    spec.add_argument("--script-id", required=True)
    spec.add_argument("--words", required=True, help="words.json from align_words.py")
    spec.add_argument("--out", required=True, help="the anchors file to write")
    spec.add_argument("--style", default="motion")
    spec.add_argument("--opening-card", default=None,
                      help="text of the opening card, when the rotation ordered one")

    args = p.parse_args(argv)
    if getattr(args, "matcher_python", None) is None and args.command == "preflight":
        args.matcher_python = anchor_coverage.resolve_anchors.DEFAULT_INDEXER_PY
    if args.out:
        runlog.annotate(**video_attempt(args.out))  # CF-0107: slug off work/<slug>/

    try:
        return run_preflight(args) if args.command == "preflight" else run_spec(args)
    except HandBack as exc:
        print(f"SCRIPT BACK TO CONTENT RESEARCHER: {exc}", file=sys.stderr)
        return EXIT_HAND_BACK
    except CannotAnswer as exc:
        print(f"script_anchors.py: {exc}", file=sys.stderr)
        return EXIT_CANNOT_ANSWER


if __name__ == "__main__":
    sys.exit(main())
