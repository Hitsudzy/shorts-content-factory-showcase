#!/usr/bin/env python3
"""CF-0071: the screenshot proof - plan the proof inserts for one video.

The contract is `inserts/proof.json` in the factory root and nothing else;
this file executes it. In one line: the writer names the document behind the
script's one fact (of any kind since CF-0439; the field is still
`production_fact`) and the words it carries (`proofs[]` in
03-content-researcher.json, script_contract), the editor puts that document
on the block whose narration says the fact, captures it by the channel's
chain of methods, and answers every request in `proof_requested`/
`proof_delivered` with one of the closed outcomes - never with a substitute.

CF-0243: the anchor is `script.production_fact` - `beat_text` (where the
voice says the fact), `source_url` (the document the insert shows), the key
names CF-0186 fixed and CF-0223 wrote into the contract. It used to be a
`comparison.checks[]` entry looked up by the request's `check_id`; CF-0181
cancelled the comparison and CF-0223 deleted `check_id` from the request,
because a script carries exactly one fact and there is nothing to name. The
lookup is gone rather than kept for old scripts: an unreachable branch is a
path nobody walks, and `check_id` arriving `null` against it answered every
request on every script `check_not_found`, which is what stopped the batch of
2026-09-15 before the render.

CF-0193: an unplaced request is answered *twice* - once in the pair, and once
in `proof_shortfalls` / `proof_not_delivered` / `proof_delivered_fully`, the
three fields CF-0192 gave the pattern, which carry the code, the evidence and
the decision the CF-0137 ladder took (`refuse` or `ship_without_proof`).
Before it, a proof whose beat was not located ended as `beat_not_found` with
`attempted: []` and a sentence in `notes`, and the video shipped: two of the
three proofs ever ordered ended that way, and in all four of the corpus's
unlocatable beats the words were in the script character for character.

What one request goes through, in order (metadata.outcomes):

    layer_off           channel insert_layers.proof.enabled is not true, or
                        no capture_method is set
    pattern_refused     patterns/<pattern_id>.json proof_layer.allowed is not true
    fact_not_found      the script carries no fact this document
                        could be evidence of: no `production_fact` at all, or
                        one with no `source_url`, or one with no `beat_text`
                        to put the insert on. Which of the three is in the
                        answer's `evidence.missing` and in the shortfall's
                        note - one code, because the question is one ("is
                        there a fact here"), and a named cause, because a
                        refusal that does not say what to fix is the silence
                        CF-0193 was filed over.
    beat_missing_in_script      the fact's beat_text is not in the script
                        either - a fact naming a sentence the video never
                        says. CF-0193: nothing downstream can supply it, so
                        the ladder refuses the plan over this one. CF-0243:
                        it is reached only with a beat_text in hand, so an
                        absent fact is never filed as a missing beat.
    beat_unmatched_in_alignment the beat is in the script word for word and
                        the forced alignment did not give it back. Ours; the
                        record carries the fragment searched for and the
                        nearest one heard, so the claim can be checked.
    beat_no_alignment   there is no words.json to look the beat up in
    too_long            len(verbatim_text) > PROOF_MAX_VERBATIM_CHARS
    source_incomplete   the source lacks url, published_at or
                        publication-or-handle: nothing could be typeset
                        honestly and no capture could be attributed
    no_block            no block at the floor: >= PROOF_MIN_BLOCK_SECONDS AND
                        >= len(verbatim_text) / PROOF_READING_RATE_CPS; or the
                        per-video ceiling is spent
    no_line             CF-0244: a block was found and the fact's on-screen
                        line does not cover it at the floor - there is no
                        window the card could be up in. Decided after the
                        lines exist (bind_to_lines), so the capture chain has
                        already run and the answer keeps what it measured
    -- the capture chain runs from here --
    capture_failed      every method was tried and none delivered a file
    illegible           a capture exists and failed the legibility /
                        attribution gate - the chain stops (never_substitute)
    placed              the first method tried delivered and passed
    capture_failed_fell_back
                        the first method's page did not come back, the next
                        delivered and passed

Placement (placement.priority): the fact's beat's block, and nowhere else -
the block holding the beat's first word first, then any other block the beat
overlaps. CF-0012's M1 (an anchorless block takes an insert first) does not
apply: a proof is evidence for one sentence, not a filler.

CF-0244 deleted the rung under those two - "a block whose narration quotes
the verbatim text, the handle or the date exactly". It was never in
`inserts/proof.json`, whose priority ends "Nowhere else, and never on the
hook or the payoff", and on `widows-bay` it did exactly what that sentence
forbids: it put the document on block 0, the hook, 26 s before the fact it
is evidence for is spoken and nowhere near the fact's own line. A full-frame
capture with no line under it measures 98.3% of pixels under blackdetect's
threshold - the whole block read as a black screen and the gate failed the
video. A block that quotes the wording is not the fact's beat; it is a block
that happens to say some of the same words.

Window (CF-0244): a placed card is on screen for the part of its block that
the fact's line covers, and not for the whole block - `insert.start_s` /
`insert.end_s` / `insert.window_from`, written by bind_to_lines() once
comparison_line.py has decided where the line is. The card and the line are
two halves of one annotation: the document is evidence for the sentence the
strip is naming, so when the strip leaves, the block's own asset (which the
storyboard contract keeps on the block for exactly this) comes back, and the
caption band drops back to its own place under it (CF-0390: our captions stay
on for the card's window and only give way to its text).

The chain (capture_priority): the channel's `capture_method` names the top
- `headless_browser` means headless_browser then rendered_quote,
`rendered_quote` means rendered_quote alone. A post (source.handle set) or
`capture_method_hint: "rendered_quote"` enters at rendered_quote. The chain
moves on a *fetch* failure only (capture_page.py); a capture that arrived
and failed the gate is `illegible` and the block is built without it.

The gate (check_proof_gates) is not inspect_asset(): near_black,
roi_coverage, subject_present and MIN_SHORT_SIDE are skipped by name
(composition.asset_gate.skipped, composition.note). What it checks:
no_upscale (>= PROOF_MIN_CAPTURE_WIDTH natively), text_present, legibility
and attribution_visible. Legibility (legibility.floor_applies_to =
"gating_lines", refined 2026-09-06): every recognised line is measured on
the delivered `contain` framing, but the floor (half our caption) applies
to the *gating* lines only - for headless_browser the lines matching the
capture's `proof_text` sidecar ({h1, standfirst}, written beside the PNG by
capture_page.py; line_gates_proof_text() is the match), for rendered_quote
every line drawn. Furniture (navigation, subscribe prompts, breadcrumbs,
dateline, byline, masthead) is measured and recorded, never gating. Fewer
than PROOF_MIN_GATING_LINES gating lines recognised is `illegible` too, and
PROOF_MAX_LINES counts gating lines. The measurement goes onto the delivered
entry as `legibility: {gating_min_px, gating_lines, furniture_min_px,
lines_total}` whenever a capture or a card was measured.

Degradation: a proof is an insert beside the block's own asset. apply_to_
blocks() adds `insert` to the placed block and nothing else; a request that
was not placed leaves every block identical.

Test seams: `capturer`, `quote_renderer`, `text_regions` and `now` are
injectable on plan_proofs(); PROOF_TEXT_REGIONS_JSON=<json {basename:
regions}> replaces Vision for a subprocess run (build_render_plan.py).

Usage:
    proof_layer.py <plan.json> --script <03-content-researcher.json> --script-id <id>
        [--channel <id|path.json>] [--pattern <id>] [--root <factory root>] [--write]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import channel_theme  # CF-0572: the quote card is drawn in the channel's theme
import comparison_line
import meme_layer
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting
from common import (PROOF_CAPTION_SIZE_PX, PROOF_MATCH_MIN_LINE_CHARS,
                    PROOF_MATCH_MIN_TOKEN_FRACTION, PROOF_MAX_LINES, PROOF_MAX_PER_VIDEO,
                    PROOF_MAX_VERBATIM_CHARS, PROOF_MIN_BLOCK_SECONDS, PROOF_MIN_CAPTURE_WIDTH,
                    PROOF_MIN_GATING_LINES, PROOF_MIN_TEXT_HEIGHT_FRACTION_OF_CAPTION,
                    PROOF_READING_RATE_CPS, PROOF_REGION_DEFAULT, PROOF_TEXT_FIELD, image_size)

LAYER = "proof"
SPEC_REL = ("inserts", "proof.json")
# The script field the proof is anchored to (CF-0186's key, CF-0223's
# contract). Taken from comparison_line.py rather than spelled again: two
# layers reading one field under two spellings is the CF-0159 defect, and
# they read the very same object.
FACT_FIELD = comparison_line.FACT_FIELD
TEXT_REGIONS_ENV = "PROOF_TEXT_REGIONS_JSON"

METHOD_HEADLESS = "headless_browser"
METHOD_QUOTE = "rendered_quote"
CHAIN = (METHOD_HEADLESS, METHOD_QUOTE)

OUTCOME_PLACED = "placed"
OUTCOME_FELL_BACK = "capture_failed_fell_back"
OUTCOME_LAYER_OFF = "layer_off"
OUTCOME_PATTERN_REFUSED = "pattern_refused"
OUTCOME_FACT_NOT_FOUND = "fact_not_found"
# CF-0193 split `beat_not_found` in three. One word used to answer two
# unrelated questions - "the video never says this" and "the video says it and
# our aligner lost it" - and the second is ours to fix, while the first is a
# reason to refuse the video. The old code is kept for *reading* plans built
# before this; nothing writes it.
OUTCOME_BEAT_MISSING_IN_SCRIPT = meme_layer.BEAT_MISSING_IN_SCRIPT
OUTCOME_BEAT_UNMATCHED_IN_ALIGNMENT = meme_layer.BEAT_UNMATCHED_IN_ALIGNMENT
OUTCOME_BEAT_NO_ALIGNMENT = meme_layer.BEAT_NO_ALIGNMENT
OUTCOME_BEAT_NOT_FOUND = "beat_not_found"
BEAT_OUTCOMES = meme_layer.BEAT_FAILURE_CODES
LEGACY_OUTCOMES = (OUTCOME_BEAT_NOT_FOUND,)
OUTCOME_TOO_LONG = "too_long"
OUTCOME_NO_BLOCK = "no_block"
# CF-0244: the card was placed and there is no window to show it in - the
# fact's on-screen line does not cover its block for long enough to read the
# document. `no_block` is "nowhere to put it" and this is "nothing to put it
# under": two questions, two words (CF-0235).
OUTCOME_NO_LINE = "no_line"
OUTCOME_SOURCE_INCOMPLETE = "source_incomplete"
OUTCOME_CAPTURE_FAILED = "capture_failed"
OUTCOME_ILLEGIBLE = "illegible"
OUTCOMES = (OUTCOME_PLACED, OUTCOME_FELL_BACK, OUTCOME_LAYER_OFF, OUTCOME_PATTERN_REFUSED,
            OUTCOME_FACT_NOT_FOUND) + BEAT_OUTCOMES + (
            OUTCOME_TOO_LONG, OUTCOME_NO_BLOCK, OUTCOME_NO_LINE,
            OUTCOME_SOURCE_INCOMPLETE, OUTCOME_CAPTURE_FAILED, OUTCOME_ILLEGIBLE)
PLACED_OUTCOMES = (OUTCOME_PLACED, OUTCOME_FELL_BACK)

# --------------------------------------------------------------------------
# CF-0193: the ladder's last rung for a proof that was ordered and did not
# arrive. Same shape as CF-0192's `pattern_shortfalls` / `pattern_not_delivered`
# / `pattern_delivered_fully`, deliberately: two layers answering "was the
# thing I ordered delivered, and if not why" in two different shapes is the
# CF-0159 defect, and one of them had to give.
#
# The decision, not just the diagnosis (CF-0137's ladder, item 4 of the task):
#
#   refuse              the request points at something that does not exist.
#                       The script carries no usable fact, or the
#                       fact's beat is not in the script at all - no rung
#                       below can fix either, and the video is built on a
#                       script that contradicts itself. build_render_plan.py
#                       refuses the plan.
#   ship_without_proof  everything else, and it is a *recorded* decision with
#                       a code, not the silence CF-0193 found: the channel or
#                       the pattern said no, the source was incomplete, no
#                       block was free, the capture chain was walked and came
#                       back empty, or the alignment lost words the script
#                       does have (which is ours and is measured - see the
#                       `beat_unmatched_in_alignment` evidence).
DECISION_REFUSE = "refuse"
DECISION_SHIP = "ship_without_proof"
REFUSAL_OUTCOMES = (OUTCOME_FACT_NOT_FOUND, OUTCOME_BEAT_MISSING_IN_SCRIPT)

# provenance.required - the nine fields every placed record carries.
PROVENANCE_REQUIRED = ["source_url", "source_platform", "author_or_outlet", "posted_at",
                       "captured_at", "capture_method", "claim_supported", "verbatim_text",
                       "still_live"]

# The legibility floor in delivered pixels: half our caption on the 1080x1920 frame.
LEGIBILITY_FLOOR_PX = PROOF_CAPTION_SIZE_PX * PROOF_MIN_TEXT_HEIGHT_FRACTION_OF_CAPTION


# --------------------------------------------------------------------------
# gates: channel, pattern, request
# --------------------------------------------------------------------------

def layer_switch(channel_cfg):
    """(enabled, capture_method): insert_layers.proof.enabled exactly true
    AND a capture_method named - a switch that is on with no method is a
    layer that cannot run, so it reads as off."""
    layers = (channel_cfg or {}).get("insert_layers") or {}
    switch = layers.get(LAYER) if isinstance(layers, dict) else None
    if not isinstance(switch, dict) or switch.get("enabled") is not True:
        return False, None
    method = switch.get("capture_method")
    if method not in CHAIN:
        return False, None
    return True, method


def pattern_allows(pattern_cfg):
    block = (pattern_cfg or {}).get("proof_layer")
    return isinstance(block, dict) and block.get("allowed") is True


def find_fact(script):
    """The one fact (`production_fact`, any kind) the script carries, or None.

    CF-0243: there is nothing to look up. A script carries exactly one fact
    (CF-0181, CF-0223), so the request names no id and this is a field read
    rather than a search - which is why `find_check()` and the whole
    `comparison.checks[]` path are deleted and not kept beside it.
    """
    fact = (script or {}).get(FACT_FIELD)
    return fact if isinstance(fact, dict) else None


# Which part of the anchor is absent, on the answer's `evidence.missing`.
# One outcome and three causes: `fact_not_found` answers "is there a fact for
# this document to be evidence of", and that is one question however it fails
# - inventing a code per field is the CF-0235 defect read backwards. The
# cause is on the record because a refusal whose record does not say what to
# fix is the silence CF-0193 was filed over.
MISSING_FACT = FACT_FIELD
MISSING_SOURCE_URL = "source_url"
MISSING_BEAT_TEXT = "beat_text"
# The sentence each cause is worth, in one place: the answer's evidence
# carries the cause, the shortfall's note renders it from here, and neither
# has to hold a copy of the other's wording.
MISSING_NOTES = {
    MISSING_FACT: f"the script carries no `{FACT_FIELD}` - there is no fact for the "
                  f"document to be evidence of",
    MISSING_SOURCE_URL: f"`{FACT_FIELD}` names no `source_url` - the fact points at no "
                        f"document, so there is nothing to put on screen",
    MISSING_BEAT_TEXT: f"`{FACT_FIELD}` names no `beat_text` - the fact has a document "
                       f"and no moment in the narration for it to sit on",
}


def fact_failure(fact):
    """Why the fact cannot anchor a proof, or None when it can.

    Runs *before* the beat is looked for, and that order is the point
    (CF-0243 item 3): `meme_layer.beat_failure()` answers an empty beat with
    `beat_missing_in_script`, a refusal-grade code meaning "the video never
    says this sentence". On a script with no fact at all that sentence is a
    lie about the script and an unconditional refusal - the same shape of
    defect as the `check_not_found` this task removed. A missing anchor is
    `fact_not_found`; `beat_*` is only ever reached with a beat in hand.
    """
    if not fact:
        return {"code": OUTCOME_FACT_NOT_FOUND, "missing": MISSING_FACT}
    url = fact.get("source_url")
    if not (isinstance(url, str) and url.strip()):
        return {"code": OUTCOME_FACT_NOT_FOUND, "missing": MISSING_SOURCE_URL}
    beat = fact.get("beat_text")
    if not (isinstance(beat, str) and beat.strip()):
        return {"code": OUTCOME_FACT_NOT_FOUND, "missing": MISSING_BEAT_TEXT}
    return None


def fact_note(gap):
    """The sentence a `fact_not_found` answer is worth, from its cause."""
    return MISSING_NOTES.get((gap or {}).get("missing"),
                             f"the script carries no usable `{FACT_FIELD}`")


def is_post(source):
    return (source or {}).get("handle") is not None


def source_fields(source):
    """(author_or_outlet, posted_at, url, platform) - None for a missing one."""
    src = source or {}
    handle = src.get("handle")
    author = handle if handle is not None else src.get("publication")
    author = author.strip() if isinstance(author, str) and author.strip() else None
    url = src.get("url")
    url = url if isinstance(url, str) and url.startswith("http") else None
    posted = src.get("published_at")
    posted = str(posted).strip() if posted not in (None, "") else None
    return author, posted, url, ("x" if handle is not None else "publication")


def capture_chain(capture_method, hint, post):
    """The methods to try, in capture_priority order, from the channel's
    method down - except that a post, or a writer's hint, enters at
    rendered_quote (headless_browser does not apply to X)."""
    if post or hint == METHOD_QUOTE:
        return [METHOD_QUOTE]
    start = CHAIN.index(capture_method) if capture_method in CHAIN else CHAIN.index(METHOD_QUOTE)
    return list(CHAIN[start:])


def floor_seconds(verbatim_text):
    return max(PROOF_MIN_BLOCK_SECONDS, len(verbatim_text or "") / PROOF_READING_RATE_CPS)


# --------------------------------------------------------------------------
# the block
# --------------------------------------------------------------------------

def _at_floor(block, floor):
    return round(block["end"] - block["start"], 3) >= floor - 1e-9


def _free(block, i, taken):
    return i not in taken and not block.get("insert")


def candidate_blocks(blocks, beat_start, beat_end, floor, taken):
    """[(index, reason)] in placement.priority order: the fact's beat's
    block - the one holding the beat's first word, then the others the beat
    overlaps, by start. Every candidate is at the floor and carries no
    insert. No M1, and (CF-0244) no rung below the beat: see the module
    docstring for what the rung that used to be here did to `widows-bay`."""
    first, others = [], []
    for i, b in enumerate(blocks):
        if not _free(b, i, taken) or not _at_floor(b, floor):
            continue
        if not (b["start"] < beat_end and b["end"] > beat_start):
            continue
        if b["start"] <= beat_start < b["end"]:
            first.append(i)
        else:
            others.append(i)
    return ([(i, "fact's beat: block holding the beat's first word") for i in first]
            + [(i, "fact's beat: overlapping block") for i in others])


# --------------------------------------------------------------------------
# the gate
# --------------------------------------------------------------------------

def _stubbed_text_regions():
    """PROOF_TEXT_REGIONS_JSON: {basename: [regions]} in place of Vision."""
    path = os.environ.get(TEXT_REGIONS_ENV)
    if not path:
        return None
    try:
        table = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None
    return lambda image_path, level=0: list(table.get(Path(image_path).name, []))


def default_text_regions(image_path, level=0):
    stub = _stubbed_text_regions()
    if stub is not None:
        return stub(image_path, level)
    import detect_text_band
    return detect_text_band.sample_text_regions(image_path, level=level)


# Quotation marks and apostrophes are deleted ("it's" -> "its", so a curly
# and a straight apostrophe read the same); every other punctuation mark is
# a word break ("fifth-season" -> "fifth season", the way Vision reads it).
_QUOTES_RE = re.compile("[\'\"\u2018\u2019\u201a\u201b\u201c\u201d\u201e\u201f\u2032\u2033\u00ab\u00bb`\u00b4]")
_PUNCT_RE = re.compile(r"[^\w\s]|_", re.UNICODE)


def normalise_proof_text(text):
    """legibility.gating_lines.headless_browser.match.normalise: casefold,
    strip punctuation and quotation marks, collapse whitespace - applied to
    the recognised line and to the proof text alike."""
    return " ".join(_PUNCT_RE.sub(" ", _QUOTES_RE.sub("", str(text or "").casefold())).split())


def _tokens_in_order(tokens, target_tokens):
    """How many of `tokens` occur in `target_tokens` as an in-order
    subsequence. A token not found ahead of the cursor is skipped and the
    cursor stays - a Vision misread drops that token, not the rest."""
    hit, j = 0, 0
    for tok in tokens:
        try:
            k = target_tokens.index(tok, j)
        except ValueError:
            continue
        hit += 1
        j = k + 1
    return hit


def line_gates_proof_text(line_text, proof_text):
    """legibility.gating_lines.headless_browser.match.line_gates_when: a
    recognised line gates when its normalised text is a substring of the
    normalised h1 (or standfirst), or at least PROOF_MATCH_MIN_TOKEN_FRACTION
    of its tokens appear in one of them in order. A normalised line shorter
    than PROOF_MATCH_MIN_LINE_CHARS never gates (a two-letter section label
    must not match by accident). `proof_text` is the capture's sidecar
    {h1, standfirst}; None or an empty h1 gates nothing."""
    line = normalise_proof_text(line_text)
    if len(line) < PROOF_MATCH_MIN_LINE_CHARS:
        return False
    targets = [normalise_proof_text(t) for t in
               ((proof_text or {}).get("h1"), (proof_text or {}).get("standfirst")) if t]
    targets = [t for t in targets if t]
    if not targets:
        return False
    tokens = line.split()
    for target in targets:
        if line in target:
            return True
        if tokens and _tokens_in_order(tokens, target.split()) / len(tokens) >= PROOF_MATCH_MIN_TOKEN_FRACTION:
            return True
    return False


def gating_rule(method, proof_text):
    """Which recognised lines gate, per method (legibility.gating_lines): a
    predicate over the line's text. rendered_quote - every line drawn (the
    card carries nothing else). headless_browser - the lines matching the
    sidecar. Any other method has no rule and gates nothing, which fails."""
    if method == METHOD_QUOTE:
        return lambda text: True
    if method == METHOD_HEADLESS:
        return lambda text: line_gates_proof_text(text, proof_text)
    return lambda text: False


def measure_lines(regions, size, frame):
    """(lines_px, lines_total): each recognised line's height in delivered
    pixels of the `contain` framing, in the order Vision returned them."""
    width, height = size
    fw, fh = frame
    scale = min(fw / width, fh / height)
    texted = [r for r in regions if str(r.get("text", "")).strip()]
    return [(str(r["text"]).strip(), float(r["height"]) * height * scale) for r in texted], len(texted)


def check_proof_gates(capture_path, provenance, frame=(1080, 1920), text_regions=None,
                      method=METHOD_HEADLESS, proof_text=None, seen=None):
    """CF-0071: the gate a proof capture answers to instead of inspect_asset()
    - composition.asset_gate: near_black / roi_coverage / subject_present
    are skipped (a page of text has no subject and is letterboxed by
    construction), and MIN_SHORT_SIDE is not borrowed for it (composition.
    note - it is a footage-quality signal, and a 1280x400 header capture is
    not 400px footage). What is checked instead, `added`:

      no_upscale            native width >= PROOF_MIN_CAPTURE_WIDTH
      text_present          Vision recognises at least one line
      legibility            every recognised line is measured on the
                            delivered `contain` framing; the floor
                            LEGIBILITY_FLOOR_PX (half our caption) applies
                            to the gating lines (gating_rule: the sidecar's
                            h1/standfirst for headless_browser, every line
                            for rendered_quote); fewer than
                            PROOF_MIN_GATING_LINES gating lines recognised
                            fails; more than PROOF_MAX_LINES gating lines
                            fails. Furniture is measured, never gating.
      attribution_visible   provenance names an outlet/author and a platform

    `proof_text` is the capture's sidecar ({h1, standfirst}); the gate takes
    it as input and never re-fetches. Returns (ok, failures, legibility) -
    failures are human-readable strings, the shape qc_asset.py reports in,
    for the plan's notes; legibility is the record for the delivered entry,
    {gating_min_px, gating_lines, furniture_min_px, lines_total}, or None when
    nothing could be measured (no readable image).

    `seen` (CF-0390), when a dict is passed, is filled with what the gate
    read on the way - `size` (native width, height) and `regions` (the
    recognised lines) - so the caller can place the caption band clear of the
    card's text without asking Vision a second time.
    """
    failures = []
    regions_of = text_regions or default_text_regions
    legibility = None

    size = image_size(capture_path)
    if size is not None and not (size[0] > 0 and size[1] > 0):
        size = None
    if size is None:
        failures.append("no_upscale: could not read the capture's native resolution")
    else:
        width, height = size
        if width < PROOF_MIN_CAPTURE_WIDTH:
            failures.append(
                f"no_upscale: capture is {width}px wide, below proof's own "
                f"{PROOF_MIN_CAPTURE_WIDTH}px floor")

    try:
        regions = regions_of(capture_path, level=0)
    except Exception as e:  # noqa: BLE001 - Vision unavailable is a gate failure, not a crash
        regions = []
        failures.append(f"text_present: text recognition did not run ({e})")
    texted = [r for r in regions if str(r.get("text", "")).strip()]
    if seen is not None:
        seen["size"], seen["regions"] = size, texted
    if not texted and not any(f.startswith("text_present") for f in failures):
        failures.append("text_present: Vision reads no transcribable text on the capture")
    if size is not None:
        lines, total = measure_lines(regions, size, frame)
        gates = gating_rule(method, proof_text)
        gating = [px for text, px in lines if gates(text)]
        furniture = [px for text, px in lines if not gates(text)]
        legibility = {"gating_min_px": round(min(gating), 2) if gating else None,
                      "gating_lines": len(gating),
                      "furniture_min_px": round(min(furniture), 2) if furniture else None,
                      "lines_total": total}
        fw, fh = frame
        if texted and len(gating) < PROOF_MIN_GATING_LINES:
            what = ("the sidecar's h1/standfirst" if method == METHOD_HEADLESS
                    else f"{method} names no gating lines")
            failures.append(
                f"legibility: {len(gating)} of {total} recognised lines match {what} "
                f"(min {PROOF_MIN_GATING_LINES}) - the proof text was not read")
        elif gating and min(gating) < LEGIBILITY_FLOOR_PX:
            failures.append(
                f"legibility: smallest gating text line is {min(gating):.1f}px on the "
                f"delivered {fw}x{fh} frame, below {LEGIBILITY_FLOOR_PX:.0f}px "
                f"({PROOF_MIN_TEXT_HEIGHT_FRACTION_OF_CAPTION:.0%} of the "
                f"{PROOF_CAPTION_SIZE_PX}px caption)")
        if len(gating) > PROOF_MAX_LINES:
            failures.append(
                f"legibility: {len(gating)} gating lines, more than {PROOF_MAX_LINES} - "
                f"a thread or a body, not a header")

    author = str((provenance or {}).get("author_or_outlet") or "").strip()
    platform = str((provenance or {}).get("source_platform") or "").strip()
    if not author or not platform:
        failures.append(
            "attribution_visible: provenance does not name both an outlet/author "
            "and a source platform")

    return not failures, failures, legibility


# --------------------------------------------------------------------------
# the decision
# --------------------------------------------------------------------------

def _request(p):
    src = p.get("source") or {}
    return {"proof_id": p.get("proof_id"),
            "verbatim_text": p.get("verbatim_text"), "source_url": src.get("url"),
            "capture_method_hint": p.get("capture_method_hint")}


def _answer(proof_id, outcome, block_index=None, used=None, attempted=(), file=None,
            legibility=None, evidence=None):
    """legibility (legibility.record) is written whenever a capture or a card
    was measured - placed, capture_failed_fell_back, illegible - absent otherwise.

    `evidence` (CF-0193) is written whenever the outcome is a *diagnosis about
    the words* - which fragment was looked for and which one the alignment
    came closest with. Without it `beat_unmatched_in_alignment` is one word
    replacing another and nobody downstream can tell whether it is true."""
    a = {"proof_id": proof_id, "outcome": outcome, "block_index": block_index,
         "capture_method_used": used, "attempted": list(attempted), "file": file}
    if legibility is not None:
        a["legibility"] = legibility
    if evidence is not None:
        a["evidence"] = evidence
    return a


# --------------------------------------------------------------------------
# CF-0193: what was ordered and did not arrive, in CF-0192's shape
# --------------------------------------------------------------------------

def proof_shortfalls(requested, delivered):
    """One machine-readable entry per ordered proof that is not on the screen.

    CF-0192 built the same thing for the pattern and the reasoning carries
    over whole: `null` meant both "nothing to say" and "not delivered, reason
    unrecorded", and a registry that guards a fiction is worse than one that
    guards nothing. Here it was worse still - the reason was not even `null`,
    it was a note in prose beside an `attempted: []`.

    Each entry carries `code` (the outcome, already a closed word), `decision`
    (REFUSE or SHIP, so the ladder's answer is on the record and not inferred
    from the code by whoever reads next), and the `evidence` when the outcome
    is about the words. Order is the order the requests were made, so the
    first entry is the first thing that went wrong in the video.
    """
    by_id = {r.get("proof_id"): r for r in (requested or [])}
    out = []
    for d in delivered or []:
        if d.get("outcome") in PLACED_OUTCOMES:
            continue
        req = by_id.get(d.get("proof_id")) or {}
        entry = {"kind": "proof_shortfall",
                 "code": d.get("outcome"),
                 "proof_id": d.get("proof_id"),
                 "decision": (DECISION_REFUSE if d.get("outcome") in REFUSAL_OUTCOMES
                              else DECISION_SHIP),
                 "attempted": list(d.get("attempted") or []),
                 "note": _shortfall_note(d, req)}
        if d.get("evidence") is not None:
            entry["evidence"] = d["evidence"]
        out.append(entry)
    return out


def _shortfall_note(d, req):
    code = d.get("outcome")
    ev = d.get("evidence") or {}
    if code == OUTCOME_FACT_NOT_FOUND:
        # The cause travels on the answer's evidence, because the gate reads
        # the pair and nothing else: proof_beat_gate.judge(requested,
        # delivered) has no script to re-derive it from.
        return fact_note(ev)
    if code == OUTCOME_BEAT_UNMATCHED_IN_ALIGNMENT:
        near = (ev.get("nearest") or {})
        return (f"the fact's beat is in the script ({ev.get('in_script_coverage')} of its "
                f"words) and not in the alignment ({ev.get('alignment_coverage')}); "
                f"nearest heard at word {near.get('word_index')}: {near.get('text')!r}")
    if code == OUTCOME_BEAT_MISSING_IN_SCRIPT:
        return (f"the fact's beat is not in the script either "
                f"({ev.get('in_script_coverage')} of its words) - nothing downstream "
                f"can supply it")
    if code == OUTCOME_BEAT_NO_ALIGNMENT:
        return "there is no alignment to look the beat up in"
    if code == OUTCOME_NO_LINE:
        # CF-0244: the evidence is the arithmetic that pulled the card, so
        # the note can say the two numbers rather than "see the notes".
        return (f"the fact's line covers {ev.get('covered_seconds')}s of block "
                f"{ev.get('block_index')} and the card needs "
                f"{ev.get('floor_seconds')}s to be read"
                if ev.get("line") is not None else
                f"block {ev.get('block_index')} was found and the fact has no "
                f"on-screen line for the card to sit under")
    return f"{code} - see the layer's notes"


def proof_not_delivered_code(shortfalls):
    """The one code that goes in the plan and in the batch record. `None` only
    when every ordered proof is on the screen - CF-0192's rule, the same
    sentence: the empty field now means one thing."""
    return shortfalls[0]["code"] if shortfalls else None


def _blacklist_check(root, channel, author):
    """The page author against the rights-holder list of the channel the
    proof is planned for (CF-0630: `channels/<id>/rights-holder-blacklist.json`
    through `meme_layer.load_blacklist`). Recorded, never gating - as before
    the list moved: a channel without a list gets a record that says the
    check was not applied and why, never another channel's list."""
    try:
        bl = meme_layer.load_blacklist(root, channel)
    except meme_layer.ChannelDataError as e:
        return {"applied": False, "skip": False,
                "reason": f"no rights-holder list for channel {channel!r}: {e}"}
    try:
        lib = meme_layer._lib(root)
        return lib.blacklist_check(author, None, bl)
    except Exception as e:  # noqa: BLE001 - recorded, never gating
        return {"skip": False, "reason": f"blacklist not reachable from {root} ({e})"}


def _rel(path, work_dir):
    try:
        return str(Path(path).resolve().relative_to(Path(work_dir).resolve()))
    except ValueError:
        return str(path)


def source_size_of(size):
    """`{width, height}` of the capture in native pixels, or None - the same
    field meme_layer.py writes for a meme (CF-0379), read by captionBand.js
    to find where a `contain`-fitted picture lands."""
    if not size or not (size[0] > 0 and size[1] > 0):
        return None
    return {"width": int(size[0]), "height": int(size[1])}


def text_box_of(regions):
    """CF-0390: the rectangle holding every recognised line of the card, as
    fractions of the capture `{top, bottom, left, right}`, or None when no
    line was read. It is what the caption band keeps clear of: the band and
    the card may share the frame, the band does not cover the card's text
    (inserts/proof.json composition.note). A union and not the lines one by
    one - the band is one row across the safe width, and a gap between two
    lines of a title is not room for it."""
    boxes = []
    for r in regions or []:
        try:
            top, height = float(r["top"]), float(r["height"])
            left, width = float(r.get("left", 0.0)), float(r.get("width", 1.0))
        except (KeyError, TypeError, ValueError):
            continue
        bottom = float(r["bottom"]) if r.get("bottom") is not None else top + height
        boxes.append((top, bottom, left, left + width))
    if not boxes:
        return None
    clamp = lambda v: round(min(1.0, max(0.0, v)), 4)
    return {"top": clamp(min(b[0] for b in boxes)), "bottom": clamp(max(b[1] for b in boxes)),
            "left": clamp(min(b[2] for b in boxes)), "right": clamp(max(b[3] for b in boxes))}


def plan_proofs(script, words, blocks, channel_cfg, pattern_cfg, root=None, work_dir=None,
                capturer=None, quote_renderer=None, text_regions=None, now=None,
                frame=(1080, 1920), region=PROOF_REGION_DEFAULT):
    """The layer's decision for one video. Returns
    {proof_requested, proof_delivered, inserts (provenance records of the
    placed proofs), overlays {block_index: insert}, telemetry, notes}.
    Never raises past a malformed request: every request is answered."""
    root = Path(root) if root else meme_layer.factory_root()
    work_dir = Path(work_dir) if work_dir else Path.cwd()
    now = now or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
    notes = []
    proofs = script.get("proofs") or []
    proofs = [p for p in proofs if isinstance(p, dict)] if isinstance(proofs, list) else []
    if len(proofs) > PROOF_MAX_PER_VIDEO:
        notes.append(f"proof: {len(proofs)} requests, only the first {PROOF_MAX_PER_VIDEO} "
                     f"are considered (placement.max_inserts_per_video)")
        proofs = proofs[:PROOF_MAX_PER_VIDEO]
    requested = [_request(p) for p in proofs]
    delivered, records, overlays = [], [], {}
    taken = set()
    telemetry = None

    enabled, capture_method = layer_switch(channel_cfg)
    allowed = pattern_allows(pattern_cfg)

    for req, p in zip(requested, proofs):
        pid = req["proof_id"]
        if not enabled:
            delivered.append(_answer(pid, OUTCOME_LAYER_OFF))
            continue
        if not allowed:
            delivered.append(_answer(pid, OUTCOME_PATTERN_REFUSED))
            continue
        fact = find_fact(script)
        gap = fact_failure(fact)
        if gap is not None:
            # CF-0243: the anchor, before the beat. Three causes under one
            # code, each named on the record - never a beat diagnosis about
            # a beat the script never offered.
            delivered.append(_answer(pid, OUTCOME_FACT_NOT_FOUND, evidence=gap))
            notes.append(f"proof {pid}: {OUTCOME_FACT_NOT_FOUND} - {fact_note(gap)}")
            continue
        span = meme_layer.match_beat(fact.get("beat_text"), script, words)
        if span is None:
            # CF-0193: which of the two, and the fragments to check it by.
            why = meme_layer.beat_failure(fact.get("beat_text"), script, words)
            delivered.append(_answer(pid, why["code"], evidence=why))
            near = why.get("nearest") or {}
            notes.append(f"proof {pid}: {why['code']} - beat {why['searched']!r} "
                         f"({why['in_script_coverage']} of its words are in the script, "
                         f"{why['alignment_coverage']} in the alignment); nearest heard "
                         f"at word {near.get('word_index')}: {near.get('text')!r}")
            continue
        text = req["verbatim_text"] if isinstance(req["verbatim_text"], str) else ""
        if not text.strip() or len(text) > PROOF_MAX_VERBATIM_CHARS:
            delivered.append(_answer(pid, OUTCOME_TOO_LONG))
            notes.append(f"proof {pid}: {len(text)} chars > {PROOF_MAX_VERBATIM_CHARS}")
            continue
        source = p.get("source") or {}
        author, posted, url, platform = source_fields(source)
        if not (author and posted and url):
            delivered.append(_answer(pid, OUTCOME_SOURCE_INCOMPLETE))
            notes.append(f"proof {pid}: source lacks "
                         + ", ".join(n for n, v in (("publication-or-handle", author),
                                                    ("published_at", posted), ("url", url)) if not v))
            continue
        floor = floor_seconds(text)
        beat_start = words[span["first_word_index"]]["start"]
        beat_end = words[span["last_word_index"]]["end"]
        cands = ([] if len(taken) >= PROOF_MAX_PER_VIDEO else
                 candidate_blocks(blocks, beat_start, beat_end, floor, taken))
        if not cands:
            delivered.append(_answer(pid, OUTCOME_NO_BLOCK))
            notes.append(f"proof {pid}: no free block at the floor ({floor:.2f}s) over the beat "
                         f"{beat_start:.2f}-{beat_end:.2f}s")
            continue
        bi, why = cands[0]

        # -- the capture chain ---------------------------------------------
        provenance_base = {"source_url": url, "source_platform": platform,
                           "author_or_outlet": author, "posted_at": posted,
                           # The sentence this document is evidence for: the
                           # fact's own text (contract, provenance.record_
                           # shape.claim_supported), its beat when the writer
                           # wrote only that.
                           "claim_supported": (fact.get("text") or fact.get("beat_text") or ""),
                           "verbatim_text": text}
        chain = capture_chain(capture_method, req["capture_method_hint"], is_post(source))
        attempted, used, file, outcome, legibility, proof_text = [], None, None, None, None, None
        for method in chain:
            attempted.append(method)
            used = method
            dest = work_dir / f"proof-{pid}-{method}.png"
            if method == METHOD_HEADLESS:
                if capturer is None:
                    import capture_page
                    capturer = capture_page.HeadlessCapture(capture_page.pool_hosts(channel_cfg))
                res = capturer.capture(url, dest, region)
                telemetry = getattr(capturer, "telemetry", telemetry)
                if not res.ok:
                    notes.append(f"proof {pid}: headless_browser fetch failed ({res.reason}) - "
                                 f"next method")
                    continue
                file = res.file
                still_live = True
                # The sidecar the capture step wrote beside the PNG - on the
                # result when the capturer is ours, read from disk otherwise
                # (a seam's capturer); never fetched again.
                proof_text = getattr(res, PROOF_TEXT_FIELD, None)
                if proof_text is None:
                    import capture_page
                    proof_text = capture_page.read_proof_text(file)
            else:
                renderer = quote_renderer
                if renderer is None:
                    import render_quote
                    renderer = render_quote.render_quote_card
                try:
                    # CF-0572: the card is drawn in the channel's theme - the
                    # config this layer plans for; a channel without one gets
                    # no card (the renderer refuses theme=None: no_theme).
                    try:
                        quote_theme = channel_theme.config_theme(channel_cfg)
                    except channel_theme.ThemeError as e:
                        quote_theme = None
                        notes.append(f"proof {pid}: {e}")
                    info = renderer(text, author, posted, dest, theme=quote_theme)
                except Exception as e:  # noqa: BLE001 - a card that could not be drawn
                    reason = getattr(e, "reason", None)
                    notes.append(f"proof {pid}: rendered_quote could not be built ({e})")
                    if reason == OUTCOME_ILLEGIBLE:
                        outcome = OUTCOME_ILLEGIBLE
                    elif reason in (OUTCOME_TOO_LONG, OUTCOME_SOURCE_INCOMPLETE):
                        outcome = reason
                    break
                file = info["file"] if isinstance(info, dict) else str(dest)
                still_live = True
            provenance = {**provenance_base, "captured_at": now(), "capture_method": method,
                          "still_live": still_live}
            seen = {}
            ok, failures, legibility = check_proof_gates(
                file, provenance, frame=frame, text_regions=text_regions,
                method=method, proof_text=proof_text, seen=seen)
            if not ok:
                outcome = OUTCOME_ILLEGIBLE
                notes.append(f"proof {pid}: {method} capture failed the gate - "
                             + "; ".join(failures))
                file = None
                break
            outcome = OUTCOME_PLACED if len(attempted) == 1 else OUTCOME_FELL_BACK
            break

        if outcome not in PLACED_OUTCOMES:
            if outcome is None:
                outcome = OUTCOME_CAPTURE_FAILED
            if outcome in (OUTCOME_TOO_LONG, OUTCOME_SOURCE_INCOMPLETE):
                # Decided by the renderer's own reading of the request,
                # before any capture: no method is named.
                delivered.append(_answer(pid, outcome))
            else:
                delivered.append(_answer(pid, outcome, used=used, attempted=attempted,
                                         legibility=legibility))
            continue

        taken.add(bi)
        rel_file = _rel(file, work_dir)
        record = {
            "kind": LAYER, "id": pid, "layer": LAYER, "proof_id": pid,
            "block": bi, "file": rel_file,
            **provenance,
            "rights_holder": author, "licence": None,
            "blacklist_check": _blacklist_check(root, meme_layer.channel_of(channel_cfg),
                                               author), "skipped": False,
        }
        if provenance["still_live"] is False:
            record["archive_url"] = None
        records.append(record)
        overlays[bi] = {
            "kind": LAYER, "proof_id": pid,
            "capture_path": str(Path(file).resolve()), "capture_method": used,
            # CF-0390: our captions stay on under the card (inserts/proof.json
            # composition.our_captions). The card's size and where its text
            # sits travel with it; since CF-0394 the band no longer reads
            # them (it is fixed, the card is fitted above it) and they stay
            # on the plan as the record of the card.
            "fit": "contain", "background": "black", "captions": "shown",
            "source_size": source_size_of(seen.get("size")),
            "text_box": text_box_of(seen.get("regions")),
            "source_url": url, "author_or_outlet": author, "posted_at": posted,
            "placed_by": why,
        }
        delivered.append(_answer(pid, outcome, bi, used, attempted, rel_file, legibility))
        notes.append(f"proof {pid}: {outcome} by {used} on block {bi} ({why})")

    short = proof_shortfalls(requested, delivered)
    for sf in short:
        notes.append(f"proof {sf['proof_id']}: not delivered ({sf['code']}), "
                     f"decision {sf['decision']} - {sf['note']}")
    return {"proof_requested": requested, "proof_delivered": delivered, "inserts": records,
            "overlays": overlays, "telemetry": telemetry, "notes": notes,
            # CF-0193, CF-0192's three fields: the list, the one code, the
            # boolean. `proof_delivered_fully` is true with nothing ordered -
            # a video nobody asked a proof of is not short of one.
            "proof_shortfalls": short,
            "proof_not_delivered": proof_not_delivered_code(short),
            "proof_delivered_fully": not short}


# --------------------------------------------------------------------------
# the plan and the batch record
# --------------------------------------------------------------------------

def apply_to_blocks(blocks, result):
    """`insert` on each placed block, nothing else on any block. Idempotent."""
    for bi, overlay in result["overlays"].items():
        blocks[int(bi)]["insert"] = dict(overlay)
    return blocks


def apply_to_plan(plan, result, storyboard_inserts=None):
    """Merge a plan_proofs() result into a render plan in place: the
    inserts on their blocks and plan["proof"] with the pair, the provenance
    records, the capture telemetry and the notes. `storyboard_inserts` are
    the 54e524b-style entries for a storyboard that hand-declared
    `insert: {kind: "proof"}` blocks - kept beside the pair, not in it."""
    apply_to_blocks(plan["blocks"], result)
    # CF-0193: recomputed when the caller's result predates the three fields
    # (build_render_plan.py's `empty` fallback, a test seam) - the pair is the
    # source and these are a reading of it, so they may never disagree with it.
    short = result.get("proof_shortfalls")
    if short is None:
        short = proof_shortfalls(result["proof_requested"], result["proof_delivered"])
    plan["proof"] = {
        "proof_requested": result["proof_requested"],
        "proof_delivered": result["proof_delivered"],
        "proofs": result["inserts"],
        "proof_shortfalls": short,
        "proof_not_delivered": proof_not_delivered_code(short),
        "proof_delivered_fully": not short,
        "proof_capture_telemetry": result.get("telemetry"),
        "notes": result["notes"],
        "storyboard_inserts": list(storyboard_inserts or []),
    }
    return plan


# --------------------------------------------------------------------------
# CF-0244: the card's window
# --------------------------------------------------------------------------

# What `insert.window_from` says. One value today, and a field rather than a
# bare pair of seconds because the pair is the *answer* and this is the
# question it answers: a window nobody can name the origin of is the state
# CF-0244 was filed about - the card's length was the block's length by
# accident, and no plan said so either way.
CARD_WINDOW_FROM = "fact line"


def line_for(lines, source_url):
    """The fact's line a placed card belongs under, or None.

    CF-0243's join, from the other side: `comparison_line.proof_source_url()`
    reads the url off this layer's provenance record to decide what the badge
    names, so the url is what a card and a line already agree on. A line with
    no url is a fact whose source we could not name, and a card is exactly a
    document at a url - those two never pair."""
    if not source_url:
        return None
    for rec in lines or []:
        if isinstance(rec, dict) and rec.get("source_url") == source_url:
            return rec
    return None


def bind_to_lines(plan):
    """CF-0244: write the window each placed proof card is on screen for, and
    pull the card that has none. Returns the notes, in place. Idempotent.

    The defect this closes. A card used to be up for its whole block, because
    nothing ever said otherwise - `insert` was a field on a block and a block
    is a span, so the card inherited one. The fact's own line is a separate
    element with a separate window (comparison_line.py, off the beat), and on
    `everyday-sorcery-2` the block outlasted the line by 4.80 s: a contained
    document on black, our captions hidden because the document carries its
    own text, and no strip. Measured on that render, 98.1% of the frame's
    pixels sit under blackdetect's threshold against the filter's 98% - the
    QC gate called it a black screen, correctly. With the strip up the same
    frame measures 91.4%. The strip is not decoration on that frame; it is
    the difference between a proof and a black screen.

    Which way the two are tied, and why. The card is clipped to the line and
    not the line stretched to the card: the document is evidence for the
    sentence the strip is naming, and evidence that stays after the claim has
    gone is a full-frame graphic the narration has stopped explaining. When
    the line leaves, the block's own asset comes back - the storyboard
    contract has always kept it on the block (storyboard_contract.note: the
    insert sits *beside* the asset, never instead of it), and this is the
    second thing that keeps it there.

    The floor is the same one placement uses: a card must be up at least
    PROOF_MIN_BLOCK_SECONDS and at least the time its text takes to read. A
    card the line covers for less than that is not shortened to fit, it is
    pulled - `no_line`, decision ship_without_proof. Half a proof on the
    frame is the "decorative rectangle that asserts evidence without
    supplying it" the contract's legibility rule already refuses.
    """
    blocks = plan.get("blocks") or []
    lines = plan.get("comparison_lines") or []
    pr = plan.get("proof") if isinstance(plan.get("proof"), dict) else None
    verbatim = {r.get("proof_id"): (r.get("verbatim_text") or "")
                for r in ((pr or {}).get("proof_requested") or []) if isinstance(r, dict)}
    notes, pulled = [], {}

    for i, b in enumerate(blocks):
        ins = b.get("insert")
        if not isinstance(ins, dict) or ins.get("kind") != LAYER:
            continue
        pid = ins.get("proof_id")
        floor = round(floor_seconds(verbatim.get(pid, "")), 3)
        line = line_for(lines, ins.get("source_url"))
        start = max(float(b["start"]), float(line["start_s"])) if line else None
        end = min(float(b["end"]), float(line["end_s"])) if line else None
        covered = None if line is None else round(max(0.0, end - start), 3)
        if covered is None or covered < floor - 1e-9:
            b.pop("insert", None)
            pulled[pid] = {
                "block_index": i,
                "block": [round(float(b["start"]), 3), round(float(b["end"]), 3)],
                "line": None if line is None else [line.get("start_s"), line.get("end_s")],
                "covered_seconds": covered, "floor_seconds": floor,
            }
            notes.append(
                f"proof {pid}: card pulled off block {i} - "
                + (f"the fact's line {line['start_s']:.2f}-{line['end_s']:.2f}s covers "
                   f"{covered:.2f}s of it, under the {floor:.2f}s floor"
                   if line is not None else
                   "the fact has no on-screen line for the card to sit under")
                + " (CF-0244: a card with no line under it is a black screen)")
            continue
        ins["start_s"], ins["end_s"] = round(start, 3), round(end, 3)
        ins["window_from"] = CARD_WINDOW_FROM
        notes.append(f"proof {pid}: card up {start:.2f}-{end:.2f}s on block {i} "
                     f"({covered:.2f}s) - the part of the block the fact's line "
                     f"{line['start_s']:.2f}-{line['end_s']:.2f}s covers (CF-0244)")

    if pulled and pr is not None:
        delivered = []
        for d in pr.get("proof_delivered") or []:
            if d.get("proof_id") in pulled and d.get("outcome") in PLACED_OUTCOMES:
                # The capture stays on the answer - it was fetched, measured
                # and passed the legibility gate; what it has not got is a
                # window. Only the outcome and the block change.
                d = {**d, "outcome": OUTCOME_NO_LINE, "block_index": None,
                     "evidence": pulled[d.get("proof_id")]}
            delivered.append(d)
        pr["proof_delivered"] = delivered
        pr["proofs"] = [r for r in pr.get("proofs") or []
                        if not (isinstance(r, dict) and r.get("proof_id") in pulled)]
        short = proof_shortfalls(pr.get("proof_requested"), delivered)
        pr["proof_shortfalls"] = short
        pr["proof_not_delivered"] = proof_not_delivered_code(short)
        pr["proof_delivered_fully"] = not short
    if notes and pr is not None:
        pr["notes"] = list(pr.get("notes") or []) + notes
    return notes


def stage_fields(plan):
    """(proof_requested, proof_delivered, proofs, telemetry) for
    write_batch_metadata.py - the pair always both lists."""
    pr = plan.get("proof") or {}
    req = pr.get("proof_requested")
    dlv = pr.get("proof_delivered")
    # A plan built by 54e524b carried counts here; that plan never ran the
    # layer, so its pair is the empty one.
    if not isinstance(req, list) or not isinstance(dlv, list):
        req, dlv = [], []
    proofs = pr.get("proofs") if isinstance(pr.get("proofs"), list) else []
    proofs = [r for r in proofs if isinstance(r, dict) and r.get("layer") == LAYER]
    return list(req), list(dlv), list(proofs), pr.get("proof_capture_telemetry")


def merge_inserts(existing, records):
    """videos[].inserts[] with this layer's records replacing this layer's
    previous ones and every other layer's (underlay, meme, sound) kept."""
    kept = [r for r in (existing or []) if not (isinstance(r, dict) and r.get("layer") == LAYER)]
    return kept + list(records)


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="plan the proof inserts for one render plan")
    ap.add_argument("plan")
    ap.add_argument("--script", required=True, help="03-content-researcher.json")
    ap.add_argument("--script-id", required=True)
    ap.add_argument("--channel", help="channel id under <root>/channels or a path to a .json")
    ap.add_argument("--pattern", help="pattern id; default: the plan's rhythm.pattern_requested")
    ap.add_argument("--root", help="factory root (default $FACTORY_ROOT or the checkout)")
    ap.add_argument("--words", help="words.json; default: the plan's own `words`")
    ap.add_argument("--region", default=PROOF_REGION_DEFAULT)
    ap.add_argument("--write", action="store_true", help="merge the result into the plan file")
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.plan))  # CF-0107

    root = Path(a.root).resolve() if a.root else meme_layer.factory_root()
    plan = json.load(open(a.plan))
    batch = json.load(open(a.script))
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    script = next((s for s in scripts or [] if s.get("script_id") == a.script_id), None)
    if script is None:
        raise SystemExit(f"script {a.script_id!r} not in {a.script}")
    words = meme_layer.load_words(a.words) if a.words else plan.get("words") or []
    pattern_id = a.pattern or (plan.get("rhythm") or {}).get("pattern_requested")
    out = plan.get("output") or {}
    # CF-0394: the card is delivered `contain` into the box above the caption
    # band, not into the whole frame, so legibility is measured on that box
    # (render/src/lib/captionBand.js insertBox, mirrored by meme_captions).
    import meme_captions
    _x, _y, box_w, box_h = meme_captions.insert_box(
        {**plan, "output": {"width": out.get("width", 1080), "height": out.get("height", 1920)}})
    result = plan_proofs(
        script, words, plan["blocks"], meme_layer.load_channel(a.channel, root),
        meme_layer.load_pattern(pattern_id, root), root=root,
        work_dir=Path(a.plan).resolve().parent,
        frame=(box_w, box_h), region=a.region)
    if a.write:
        apply_to_plan(plan, result, (plan.get("proof") or {}).get("storyboard_inserts"))
        json.dump(plan, open(a.plan, "w"), indent=2)
    print(json.dumps({k: result[k] for k in ("proof_requested", "proof_delivered",
                                             "telemetry", "notes")},
                     ensure_ascii=False, indent=2))
    return 0


@video_script("video-editor", "proof", name="proof_layer.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
