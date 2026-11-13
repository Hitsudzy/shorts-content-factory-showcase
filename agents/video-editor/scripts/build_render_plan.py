#!/usr/bin/env python3
"""Turn a storyboard plus a word alignment into the render plan Remotion consumes.

This is the deterministic half of the agent. The one LLM step upstream decides
*what should be on screen when*; everything from here down is mechanical, which
is what makes the output testable and lets the QC gate reason about it.

Usage:
    build_render_plan.py <storyboard.json> <words.json> <voice.wav> <out.json>
      [--style stills] [--target-duration LO HI]
      [--degrade-block "4:still:motion 0.32 below threshold" ...]
      [--script <03-content-researcher.json> --script-id <id> --channel <channel>]

CF-0067: with `--script`/`--script-id` (and `--channel`, whose config holds
the `insert_layers.meme` switch) the plan also runs the meme layer -
scripts/meme_layer.py, executing inserts/meme.json: the script's
`reactions[]` are answered in plan["meme"] (`meme_requested`/
`meme_delivered` plus provenance), and a placed meme is merged onto its
block as `insert: {kind: "meme", ...}` beside the block's own `asset`, which
is built exactly as it would be without one. Without `--script` the pair is
written empty.

CF-0127: with `--channel` alone (no script needed) the plan also runs the
second-plane underlay - scripts/underlay_layer.py over the factory's
shared/inserts/underlay.py: `plan["underlay"]` says which muted loop went
into `layout.secondary` and, when one did, `plan["secondary_source"]` is the
prop SecondaryZone.jsx draws. Decided *before* the block loop, unlike every
other insert layer, because the band takes its height out of `main` and
`main` is what the blocks are framed against; a layer that is off or a
library that is empty leaves `secondary` null and the plan otherwise
unchanged.

CF-0041: the plan also carries `rhythm` - the (pattern, rhythm) order the
storyboard was built to answer, the cadence that actually came out, and the
verdict on whether the order survived degradation. `write_batch_metadata.py`
copies it into `05-video-editor.json` as requested/delivered pairs.

CF-0031: degradation is per-block, not per-video. `qc_render.py`'s
`frozen_blocks()` already names the exact block indices that failed the
post-render motion probe; `--degrade-block` is how the caller feeds those
specific indices back in, so only they drop a rung (clip -> still, or
still -> typographic) while every other block keeps its original asset.
Only when a plan comes back with zero surviving clip/still blocks is a
whole-video rung drop (a fresh `--style` on the *original*, undegraded
storyboard) the right move - see SKILL.md's degradation-chain section.
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import rhythm
import _score  # CF-0433: the score model (shared/score) and the similarity floor
import fact_anchor  # CF-0583: score.fact_anchor_early, the fact's picture ahead of its words
import score_log  # CF-0434: the video's score log and the early stop
import shot_score  # CF-0435: a weak shot is priced, not refused
import held_sharpness  # CF-0465: a soft frame held still
import held_motion  # CF-0481: a face held still out of a moving shot
import held_screen  # CF-0646: a thin strip, a headless body, a soft stretched hold
import held_recut   # CF-0648: what held_screen flags is re-cut before the render
import face_window  # CF-0535: the face window chosen over the shown span, by the intent
import wide_place  # CF-0352: a wide shot of a place is not low framing
import still_share as share_gate  # CF-0418: pictures over half the running time; aliased *_gate like every gate whose deficit the planner writes (root test_the_editors_deficit_shape_is_the_one_we_read)
import meme_captions  # CF-0436: the insert box a blur_fill picture is fitted into
import ambient_bed
import assetless_rung
import attempts
import blooper_gate
import channel_watermark  # CF-0212: the mark is the channel's display_name, never a default
import channel_theme  # CF-0572: colours and faces are the channel's theme, never Reel's
import plan_refusal
import proof_quote_cap  # CF-0567: vendor quotes and the demo's own footage
import own_graphic_plan  # CF-0689: the graphics the factory draws from the script's facts
import person_shot  # CF-0879: the people a block names, and a foreign face under them
import safe_area
import smart_crop
import detect_text_band
import inset_panel
import narration_length
import comparison_line
import end_card
import footage_credits  # CF-0664: whose footage is on screen, and the on-screen credit
import meme_layer
import proof_beat_gate
import proof_layer
import sound_layer
import source_gate
import underlay_layer
from common import (FFMPEG, VENV_PY, SCRIPTS, AGENT_ROOT, SOUND_MAX_PER_VIDEO, audio_duration,
                    ASSET_TOOL_TIMEOUT_SECONDS, PROBE_FRAME_TIMEOUT_SECONDS, TOOL_TIMEOUT_KEY,
                    leading_silence, load_words, run_json, grab_frame,
                    PROBE_OFFSET, MIN_COVERAGE, MIN_SHORT_SIDE, image_size,
                    delivery_fit,
                    # CF-0131: qc_render.py's own freeze arithmetic, applied
                    # before the render instead of after it.
                    media_duration, clip_shortfall, held_tail, MAX_HELD_RUN,
                    LAST_FRAME_EPSILON,
                    # CF-0245: the renderer's own "where inside its clip is
                    # this block" arithmetic, so the hold-band trim asks the
                    # freeze question by the same numbers the gates answer it
                    # with instead of a second copy of them.
                    source_time, CLIP_TAIL_TOLERANCE)

# CF-0047: a title/end card lifted from footage is read, not looked at, so the
# framing question for one is "is the wordmark whole", not "did the salient
# box survive". Measured on the real frames of the 2026-08-31T2155Z batch, the
# 9:16 cover crop keeps only 76% of the Wren Hollow card's recognised text
# (ZZ_urA56pJE shot 50 - the wordmark reads "Harry Pott") and 80% of the Example Network
# Max splash's (shot 3 - "Examplemax" with its edges cut), while roi_coverage
# reports a clean 1.000 for both, because Vision's saliency box does survive
# the crop even though the lettering does not. Fitting the card whole is
# therefore the fix, not relaxing a gate - and note which direction that goes:
# the coverage floor is left exactly as strict as it was, and this adds a
# check that did not exist.
MIN_CARD_TEXT_KEPT = 0.98

# The pattern vocabulary lives in the factory root, not in this agent (CF-0039):
# the same files are read by Content Researcher, by the rotation guard and here.
# Read-only from this side - Video Editor executes the vocabulary, it does not
# own it - and absent on a checkout of this repo alone, which verify_pattern()
# reports rather than assumes away.
#
# "The factory root" is meme_layer.factory_root()'s answer, not two levels up
# from this file: a git worktree of this agent sits in
# `.claude/worktrees/<branch>`, where two-levels-up is a directory of
# worktrees and every pattern silently reads as unreadable. That is not a
# harmless miss - a plan built in a worktree loses its whole cadence check,
# so the same build comes out with fewer deviations than in the checkout,
# which is exactly the class of difference a worktree must not introduce.
# factory_root() honours $FACTORY_ROOT first and otherwise walks up to the
# real root by its marker file, so both layouts land on the same patterns/.
PATTERNS_DIR = meme_layer.factory_root() / "patterns"


# A still that is mostly black is almost always junk - a letterbox or a
# screenshot. A *clip* that is mostly black is often just a night interior, and
# this trailer is full of them. Same check, different ceiling, because the two
# cases genuinely differ.
CLIP_MAX_BLACK = 0.90

# CF-0050: the `side_by_side` opening divides the main zone into two halves
# with a seam between them. **Stacked, not left and right.** Splitting a 9:16
# frame vertically leaves each side 540x1920 - an aspect of 0.28:1 against
# source footage that is 2.35:1, so a cover crop would keep 12% of each shot's
# width and the two sides would be unreadable slivers. Stacking gives each half
# 1080x957 (1.13:1), which is *wider* than the 9:16 window every other block is
# framed in, so a subject that survived the full-frame crop survives this one
# with room to spare. The number is in one place and read by name from
# SplitLayer.jsx's own comment - the two have to agree or the halves the plan
# was framed for are not the halves that get rendered.
SPLIT_SEAM_PX = 6

# CF-0071: proof captures (screenshots of a trade announcement, a typeset
# quotation) are evidence, not footage - inspect_asset()'s asset gate does
# not apply to them. The gate that does (proof_layer.check_proof_gates) and
# the numbers behind it (common.PROOF_*) live with the layer; the names are
# kept here for the storyboard-declared `insert: {kind: "proof"}` path below
# and for the tests that read them off this module.
from common import (PROOF_CAPTION_SIZE_PX, PROOF_FRAME_HEIGHT_REF,  # noqa: E402
                    PROOF_MIN_CAPTURE_WIDTH, PROOF_MIN_TEXT_HEIGHT_FRACTION,
                    PROOF_MIN_TEXT_HEIGHT_FRACTION_OF_CAPTION)
import capture_page  # noqa: E402
from proof_layer import check_proof_gates  # noqa: E402
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

PROVENANCE_REQUIRED = [
    "source_url", "source_platform", "author_or_outlet", "posted_at",
    "captured_at", "capture_method", "claim_supported", "verbatim_text",
    "still_live",
]


def main_zone_height(height, layout):
    """Mirror of resolveZones() in render/src/lib/layout.js: a null `secondary`
    gives its height back to `main`. The split halves divide the *main* zone,
    so this has to be the renderer's answer and not the frame height."""
    secondary = (layout or {}).get("secondary")
    if not secondary:
        return height
    return height - round(height * secondary.get("height", 0.28))


def split_half_size(width, height, layout):
    """Pixel size of one half of a split block, in composition pixels."""
    return width, (main_zone_height(height, layout) - SPLIT_SEAM_PX) // 2


def framing(info):
    """Where the renderer should point this asset, from smart_crop's verdict.

    Factored out (CF-0050) because a `side_by_side` half needs exactly the same
    answer computed against a different window: `smart_crop.analyse()` already
    takes the target aspect as a parameter, so a half is framed by asking it
    about the half's own geometry rather than by adjusting numbers that were
    computed for the whole frame. Anything else would be a second, unexplained
    copy of the framing rules - and adjusting a 9:16 `zoom` for a 1.13:1 window
    by hand is precisely how CF-0033 happened.
    """
    size = info["source_size"]
    # CF-0155: the focus rule itself lives in smart_crop.focus_point() - the
    # asset gate has to reproduce this exact window to judge a probe frame
    # against what the render will show, and two copies of it would drift.
    focus_x, focus_y = smart_crop.focus_point(info)
    return {
        "focus": {"x": focus_x, "y": focus_y},
        "fit": "cover",
        "coverage": info["roi_coverage"],
        "roi_source": info["roi_source"],
        "source_size": size,
        # CF-0033: AssetLayer.jsx applies object-fit:cover on the raw source,
        # which always frames the *entire* height whenever the source is wider
        # than the target aspect - smart_crop's "crop" is a diagnostic rect
        # only, never actually cut out of the file. `zoom` (>=1.0) is the one
        # field that makes a tightened crop real: an extra scale AssetLayer.jsx
        # applies on top of cover's natural framing, anchored at the same
        # `focus` point.
        "zoom": info.get("zoom", 1.0),
    }


def frame_the_panel(asset, probe_path, info, min_coverage, aspect=(9, 16)):
    """CF-0327: never deliver a sliver of the shot's own inset panel.

    `mormon-wives-comeback` block 11: the source frame is a split screen whose
    bright panel spans x 0.056-0.459, the window this planner pointed at the
    face runs 696-1304 of 1920, and what reached the screen was 24 % of that
    panel pressed against the left edge for a second and a half. Nothing here
    had ever asked where the panel was - `smart_crop` frames on faces, and a
    face is not a panel.

    The rule (inset_panel.py): a panel is on screen whole or not at all, and
    the sliver between the two is refused. This moves `focus.x` to the nearest
    focus that gives one of the two allowed answers, preferring the one that
    shows the panel, and only if the subject survives the move at the plan's
    own coverage floor - the framing is pointed at the subject for CF-0294's
    reason and this may not spend that to fix a panel.

    Returns the record to hang on the asset, or None when the shot has no
    panel at all (the ordinary case, and block 10 of the same video one second
    earlier). `subject_kept` on that record is the delivered coverage at the
    focus this chose - the asset's own `coverage` is left alone on purpose,
    because it is a different quantity (analyse()'s ROI-against-aspect fit,
    computed for a window centred on the ROI and never on `focus`) and the
    asset gate's threshold is written against that one. When no move keeps both, the record says `unresolved` and the
    framing is left exactly as it was: the refusal then happens once, at
    `qc_render`, which is where "the delivered picture is wrong" is said in
    this factory and where the attempt ladder and CF-0367's re-cut are already
    wired up. Deliberately not `fit: contain` here - letterboxing a montage
    block to a postage stamp trades a visible defect for another visible
    defect, and does it silently.
    """
    if asset.get("fit") != "cover":
        return None             # contain shows the whole source; nothing is cut
    panel = inset_panel.find_panel(probe_path)
    if not panel:
        return None
    size_d = asset.get("source_size") or {}
    size = (size_d.get("width"), size_d.get("height"))
    if not all(size):
        return None
    focus_x, focus_y = asset["focus"]["x"], asset["focus"]["y"]
    zoom, fit = asset.get("zoom", 1.0), asset["fit"]

    def measure(fx):
        window = inset_panel.window_for(size, fx, focus_y, zoom, fit, aspect)
        fraction = inset_panel.visible_fraction(panel, window, size)
        return fraction, inset_panel.verdict(fraction)

    fraction, seen = measure(focus_x)
    record = {**panel, "visible": fraction, "verdict": seen,
              "focus_x_before": round(focus_x, 4), "moved": False}
    if seen != inset_panel.CUT:
        return record
    for candidate, outcome in inset_panel.candidates(panel, size, focus_x,
                                                     zoom, fit, aspect):
        try:
            kept = smart_crop.subject_coverage(info, (candidate, focus_y), zoom,
                                               aspect[0], aspect[1], fit)
        except (KeyError, TypeError, ZeroDivisionError):
            kept = None
        if kept is not None and kept < min_coverage:
            continue
        asset["focus"] = {"x": candidate, "y": focus_y}
        fraction, seen = measure(candidate)
        record.update({"visible": fraction, "verdict": seen, "moved": True,
                       "outcome": outcome, "subject_kept": (None if kept is None
                                                            else round(kept, 3))})
        return record
    record["verdict"] = "unresolved"
    return record


def carry_rhythm(sb):
    """Copy a storyboard block's rhythm fields onto the plan block.

    `rhythm_role`, `side` and `shot` are what `rhythm.verify_rhythm()` measures
    the delivered montage with afterwards, and they have to survive into
    plan.json because that is the only artefact `write_batch_metadata.py` and
    `qc_render.py` read. `held_frame` marks a still that the rhythm asked for
    rather than one degradation produced.
    """
    out = {}
    for key in ("rhythm_role", "side", "shot", "held_frame",
                # CF-0137: the block was filled by the video's one emergency
                # shot repeat. It has to survive into plan.json for the same
                # reason `held_frame` does - the plan is the only artefact
                # write_batch_metadata.py reads, and a repeat nobody can see
                # downstream is a material shortage hidden rather than
                # reported.
                "emergency_reuse",
                # CF-0337: the block was filled from the topic's footage, not
                # with a picture of its phrase - carried for the same reason.
                "topic_fill",
                # CF-0120: which shots one crossing of the axis was assembled
                # from. Carried for the same reason - the plan is the only
                # artefact downstream reads, and a side that stopped being a
                # frozen frame because three shots were cut into it says so
                # here rather than being re-derived from the asset's cuts.
                "swing_block_shots",
                # CF-0480: a one-frame block cut into 2-3 shots of its phrase
                # because its one shot would have stood for more than twice
                # its length - or held anyway, `short`, because the pool had
                # no second shot. The plan's "pool does not hold the video"
                # warning reads it here.
                "stretch_split",
                # CF-0106: where in the source the clip was cut from and why
                # (head / moment) - the QC report and batch metadata are what
                # a comparison check's frame is traced through.
                "cut_at", "cut_origin", "moment_at",
                # CF-0879: the people the block's words name - the frame
                # judge's pack hands them to the judge (`named_people`).
                person_shot.FIELD):
        if sb.get(key) is not None:
            out[key] = sb[key]
    return out


def load_pattern(pattern_id):
    """The pattern file, when the factory root is reachable from here.

    CF-0276 moved the body into `rhythm.load_pattern()` so that the block
    layout, which now asks the same question one stage earlier, asks it of the
    same code. This keeps the one-argument name every caller here already uses.
    """
    return rhythm.load_pattern(pattern_id, PATTERNS_DIR)


# ---------------------------------------------------------------------------
# CF-0245: a block held longer than the pattern's hold band, trimmed to the
# top of the band with the remainder handed to the next block.
#
# What this is, and what it deliberately is not. `hold_outside_band` was the
# one of the four 2026-09-15 pattern failures that belongs to the editor:
# dtf-st-louis held its longest block 9.40s against moment-breakdown's drawn
# 4.0-9.0s - over by 0.40s. The other three are a thin pool (a topic that got
# one source, the same narration spread over fewer pictures) and are fixed
# upstream in CF-0129/CF-0232/CF-0233; masking them here with a trim would
# hide a supply defect those tasks just made visible, so nothing below looks
# at `sample_contention` or `rhythm_not_as_ordered` at all.
#
# The band is not touched. CF-0195 put a guard with a negative control on
# widening an envelope to fit a broken corpus, and this is the other
# direction: the montage moves, one internal boundary, and every other number
# in the plan - the video's length, the words, the other blocks - is
# unchanged.
#
# The refusals are the substance of it. Handing the remainder to a block whose
# clip cannot carry it is how you *build* CF-0249's defect - a block that
# plays real footage and then holds one frame - and CF-0249 is the defect that
# reached a viewer and reset the "three in a row" counter. So the condition is
# stricter than either freeze gate: the next block's clip must cover the
# extended span outright (`source_time()`, the renderer's own arithmetic,
# crossfade included), not merely stay under MAX_HELD_RUN. A block that can
# absorb the remainder by this rule cannot be failed by held_tail() or
# clip_shortfall() afterwards, because it holds no frame at all - which is the
# only way a repair can be trusted not to be the thing it repairs.
# ---------------------------------------------------------------------------

# The codes a trim record carries. Codes, not sentences, for the same reason
# CF-0192's `pattern_shortfalls` carries codes: this list joins with that one.
HOLD_TRIM_APPLIED = "trimmed_to_hold_band"
HOLD_TRIM_NO_NEXT_BLOCK = "no_next_block"
HOLD_TRIM_NEXT_HAS_NO_CLIP = "next_block_has_no_clip"
HOLD_TRIM_NEXT_CLIP_TOO_SHORT = "next_clip_too_short"
HOLD_TRIM_NEXT_WOULD_LEAVE_BAND = "next_block_would_leave_band"


# The band itself now lives in rhythm.py (CF-0276): the block layout is held
# to it before the clips are cut, and the trim below repairs what is left, so
# the two stages must not be able to disagree about which band that is. Kept
# as a name here because this module's callers and tests use it.
hold_band = rhythm.hold_band


def block_span(story_blocks, i, duration):
    """Block `i`'s screen time, read the way main()'s loop reads it.

    One definition of "how long is this block", because the trim below decides
    on a span the loop then has to agree with: the last block runs to the end
    of the audio, not to its own `_end` (the picture must not die before the
    voice does).
    """
    sb = story_blocks[i]
    end = duration if i == len(story_blocks) - 1 else sb["_end"]
    return sb["_start"], end


def trim_to_hold_band(story_blocks, pattern, duration, degraded=(),
                      clip_seconds=media_duration):
    """Trim every block held past the top of the hold band, where that is safe.

    Mutates `_start`/`_end` on `story_blocks` - the boundary between the long
    block and the next one moves earlier by the overshoot, and nothing else
    moves - and returns one record per over-band block, applied or refused,
    each carrying the numbers it was decided on.

    A block is trimmed only when all of these hold:

      * the pattern *orders* a hold band (`hold_band()` above);
      * there is a next block to hand the remainder to. The last block has
        none, and freezing the overshoot into the previous picture is the
        defect, so it is left long and the pattern goes undelivered;
      * that next block shows a clip of its own. A still, a card, an
        assetless block, a `sequence` and a `split` half are all refused: a
        still has no footage to play longer, and a multi-picture block would
        have to be recut, which is a cut, not a boundary;
      * the next block's clip covers the extended span. Nothing is recut here
        on purpose - the clips were cut by resolve_anchors.py against the
        boundaries it had, and this stage asks whether the file on disk is
        long enough, which is the question the grill of 2026-09-16 asked;
      * the extended block stays inside the band itself. Otherwise the trim
        would move the failure one block to the right rather than end it.

    `clip_seconds` is injected so the rule can be tested without ffmpeg; in
    the run it is common.media_duration, and it is called at most once per
    over-band block.
    """
    records = []
    band = hold_band(pattern)
    n = len(story_blocks)
    if band is None or not n:
        return records
    if not all("_start" in sb and "_end" in sb for sb in story_blocks):
        # A storyboard without explicit times is not anchor-resolved: the
        # planner reads its bounds off the word alignment, and a boundary
        # there is a word, not a number this may move.
        return records
    top = float(band["max"])
    pid = pattern.get("pattern_id")
    i = 0
    while i < n:
        start, end = block_span(story_blocks, i, duration)
        measured = round(end - start, 3)
        # CF-0303: `rhythm.over_band_top()` is the one comparison - a block
        # over the top by less than the half frame the grid can show is not
        # over it, here or in the judge that reads this record.
        if not rhythm.over_band_top(measured, top):
            i += 1
            continue
        remainder = round(measured - top, 3)
        boundary = round(start + top, 3)
        rec = {"kind": "hold_band_trim", "block": i, "pattern_id": pid,
               "measured": measured, "band_max": round(top, 3),
               "remainder": remainder}

        def refuse(code, note, **fields):
            records.append({**rec, "code": code, "applied": False,
                            "note": note, **fields})

        if i + 1 >= n:
            refuse(HOLD_TRIM_NO_NEXT_BLOCK,
                   f"block {i} is held {measured}s against {pid}'s drawn hold "
                   f"band top {top}s, and it is the last block - there is no "
                   f"next anchor to hand the {remainder}s to, so it is left as "
                   f"it is rather than frozen shorter (CF-0249)")
            i += 1
            continue
        nxt = story_blocks[i + 1]
        next_kind = nxt.get("asset_kind", "still")
        if (i + 1) in set(degraded) or next_kind != "clip":
            refuse(HOLD_TRIM_NEXT_HAS_NO_CLIP,
                   f"block {i} is held {measured}s against {pid}'s drawn hold "
                   f"band top {top}s, and block {i + 1} shows no clip of its "
                   f"own ({next_kind}) - there is no footage there to play the "
                   f"{remainder}s, only a frame to hold it on (CF-0249)",
                   next_block=i + 1, next_asset_kind=next_kind)
            i += 1
            continue
        _, next_end = block_span(story_blocks, i + 1, duration)
        next_span = round(next_end - end, 3)
        extended = round(next_end - boundary, 3)
        # CF-0303: the same comparison as the one that put this block here - a
        # next block half a frame over the top is not over it, and refusing the
        # trim on that would leave a real breach standing for an unreal one.
        if rhythm.over_band_top(extended, top):
            refuse(HOLD_TRIM_NEXT_WOULD_LEAVE_BAND,
                   f"block {i} is held {measured}s against {pid}'s drawn hold "
                   f"band top {top}s, and handing the {remainder}s to block "
                   f"{i + 1} would take it from {next_span}s to {extended}s - "
                   f"outside the same band, which moves the failure rather "
                   f"than ending it",
                   next_block=i + 1, next_span=next_span,
                   next_span_extended=extended)
            i += 1
            continue
        seconds = clip_seconds(nxt["asset"])
        # What the renderer would ask of that clip: Video.jsx mounts the block
        # RENDER_CROSSFADE early and AssetLayer.jsx trims by `start_seconds`,
        # so an extra `remainder` of screen time is an extra `remainder` of
        # file. common.source_time() is that arithmetic, and it is imported
        # rather than restated (CF-0003).
        needed = round(source_time(
            {"start": boundary, "end": next_end,
             "asset": {"start_seconds": nxt.get("asset_start_seconds", 0)}},
            next_end), 3)
        if not seconds or needed - seconds > CLIP_TAIL_TOLERANCE:
            refuse(HOLD_TRIM_NEXT_CLIP_TOO_SHORT,
                   f"block {i} is held {measured}s against {pid}'s drawn hold "
                   f"band top {top}s, and block {i + 1}'s clip runs "
                   f"{(seconds or 0.0):.3f}s against the {needed}s the "
                   f"extended block would play of it - so the {remainder}s it "
                   f"would be handed is footage that clip does not have, and "
                   f"it would hold its last frame over them instead (CF-0249)",
                   next_block=i + 1, next_span=next_span,
                   next_span_extended=extended,
                   next_clip_seconds=round(seconds or 0.0, 3),
                   next_clip_needed=needed)
            i += 1
            continue
        story_blocks[i]["_end"] = boundary
        nxt["_start"] = boundary
        records.append({
            **rec, "code": HOLD_TRIM_APPLIED, "applied": True,
            "trimmed_to": round(top, 3), "boundary": boundary,
            "next_block": i + 1, "next_span": next_span,
            "next_span_extended": extended,
            "next_clip_seconds": round(seconds, 3),
            "next_clip_needed": needed,
            "note": (f"block {i} was held {measured}s against {pid}'s drawn "
                     f"hold band {band['min']}-{top}s, so it was trimmed to "
                     f"{top}s and its {remainder}s went to block {i + 1}, "
                     f"which grows from {next_span}s to {extended}s and has "
                     f"the footage for it ({seconds:.3f}s of clip against "
                     f"{needed}s played). The band is untouched (CF-0195) - "
                     f"this is a different montage, not a different envelope"),
        })
        # The extended block was checked against the band above, so it cannot
        # be over it; step past it either way rather than re-deciding a block
        # this pass has just written.
        i += 2
    return records


# ---------------------------------------------------------------------------
# CF-0290: an anchor the pool cannot picture, and the picture that went on
# screen for it anyway.
#
# DoD ролика item 3: "An unresolved anchor means the phrase is dropped or the
# video goes to needs-you - never a random frame."
# `example-film/2026-09-18T2232Z` (delver.mp4) is the case it was written
# against. Two of its ten anchors - "a man in a red jacket at a podium under an
# ornate rotunda ceiling" and "a wheelchair rushed past camera equipment on a
# chaotic set" - were filled with Tom Carver sitting in an interview chair, at
# 0.2000 and 0.2046 against a 0.22 similarity floor, because
# `resolve_anchors.py` sorted each block's pool long-enough-first *before* it
# looked at similarity and the shots that did depict those phrases were 1.9s
# and 0.985s long. The storyboard said so, in `unresolved_anchors`, in the
# gate's own words ("using it anyway, but nothing usable in the available
# footage actually depicts this") - and nothing read the field. The video
# rendered, passed QC, and shipped with `degradation: []` and
# `needs_you: null`.
#
# `resolve_anchors.screen_pool()` is the fix and this is the gate behind it.
# The screen makes an under-floor picture unreachable from this repo's
# resolver; what this adds is that a storyboard carrying one cannot be
# *rendered* - by an older resolver's output replayed here, by a hand-written
# storyboard, or by a future branch that forgets the screen. Same shape as
# CF-0136's rule for the assetless rung: the gate judges the record on the
# storyboard, not the branch that was supposed to have prevented it.
#
# What it reads is exactly what `gate_verdict()` writes for that case and for
# no other: `best_used_score` - the score of the picture the block actually
# got - beside `min_score`, the floor it was judged against. A record without
# `best_used_score` is one of the other unresolved kinds (no candidate at all,
# a phrase too tight, a carry, the emergency repeat) and is not this gate's
# business: none of them puts a frame of something else on screen.
# ---------------------------------------------------------------------------

# The floor to judge a storyboard by when it names none. Storyboards written
# before CF-0290 carry no `min_score` of their own. CF-0433: the number has one
# home, `_score.SIMILARITY_FLOOR`, which resolve_anchors.DEFAULT_MIN_SCORE is
# also an alias of - this file still does not pull in the resolver (it needs
# neither the matcher nor ffmpeg's cutter).
DEFAULT_SIMILARITY_FLOOR = _score.SIMILARITY_FLOOR  # CF-0433: one home, _score.py


def under_floor_anchors(story):
    """The anchors this storyboard put an off-topic picture under, if any.

    One record per `unresolved_anchors` entry whose block was filled below the
    similarity floor, carrying the phrase, the score and the floor it is under.
    `[]` means no such anchor - including for a storyboard that has no
    `unresolved_anchors` at all, which is every storyboard from before CF-0088.
    Pure.
    """
    default = story.get("min_score")
    if default is None:
        default = DEFAULT_SIMILARITY_FLOOR
    out = []
    for u in story.get("unresolved_anchors") or []:
        if not isinstance(u, dict):
            continue
        best = u.get("best_used_score")
        if best is None:
            continue
        floor = u.get("min_score")
        if floor is None:
            floor = default
        if best < floor:
            out.append({"phrase": u.get("phrase"), "score": round(float(best), 4),
                        "min_score": floor, "reason": u.get("reason")})
    return out


def under_floor_lines(records):
    """The gate's findings - the `reason` the funnel prints, one line each."""
    lines = [f"{len(records)} anchor(s) were given a picture under the "
             f"similarity floor - the phrase is not what is on screen"]
    for r in records:
        lines.append(f"{r['phrase']!r}: the block's picture scores "
                     f"{r['score']:.4f} against the {r['min_score']} floor "
                     f"({r['reason']})")
    return lines


def asset_gate(rejected, weak_seen, notes, i, asset, qc, shot_key, where=""):
    """CF-0435: the asset gate of one picture. A hard failure refuses the plan
    (appended to `rejected`, ASSETS REJECTED, as always); a verdict failing
    only framing, brightness or resolution is a weak picture - noted, its
    rules kept in `weak_seen[(i, shot_key)]` for the plan stage's price
    (`shot_score.plan_findings`), and shown (`shot_score.split_verdict`)."""
    hard, soft = shot_score.split_verdict(qc)
    if hard:
        rejected.append((i, asset, qc["failures"]))
    elif soft:
        weak_seen.setdefault((i, shot_key), set()).update(soft)
        notes.append(f"block {i}{where}: weak picture, shown and priced "
                     f"(CF-0435) - " + "; ".join(qc.get("failures") or soft))


def waive_wide_place(info, record, notes, i, where=""):
    """CF-0352: the plan's own verdict of a picture the resolver took as a
    wide view of a place (`wide_place.waived(record)`) loses its `coverage`
    failure when this probe's subject box is not a face either - so the asset
    gate does not price `low_framing` and `present_picture` does not
    blur-fill a general view of a building. Said in the notes; a face, or a
    picture the resolver did not mark, is left exactly as measured."""
    if not wide_place.waived(record) or not isinstance(info.get("qc"), dict):
        return
    qc, cov = wide_place.waive_qc(info["qc"])
    if cov is None:
        return
    info["qc"] = qc
    notes.append(f"block {i}{where}: a wide view of a place - the window keeps "
                 f"{cov:.0%} of a {qc.get('roi_source')} box, not low framing; "
                 f"unpriced warning {wide_place.WARN_RULE} (CF-0352)")


def present_picture(target, info, probe_path, record, box, presented, notes,
                    i, shot_key, where=""):
    """CF-0436: how one picture is shown - as it is, `blur_fill` or
    `luma_lift` (shot_score's presentation model), decided on this plan's own
    probe frame before it is thrown away. `target` is the plan dict the
    renderer reads (a block's asset, a sequence cut) and is updated in place:
    `presentation: {mode: detail}`, and `fit: contain` for blur_fill (the
    picture is whole on screen - every "is the subject cut?" gate stands down
    for a contained picture). `record` is the resolver's `usability` record of
    the same picture (its measured soft rules count too). The lifted
    brightness is measured on the probe (qc_asset.lifted_luma) - a lift that
    does not clear the floor is dropped and the picture is priced as it is.
    `presented[(i, shot_key)]` collects the modes for plan_findings. A hard
    verdict or a card is left alone: the first is refused anyway, the second
    is already fitted whole and its darkness is excused."""
    qc = info.get("qc") or {}
    hard, soft = shot_score.split_verdict(qc)
    if hard or target.get("fit") == "contain":
        return {}
    rules = set(soft) | set((record or {}).get("soft") or [])
    choice = shot_score.choose(rules, luma=qc.get("mean_luma"))
    if not choice:
        return {}
    shown = {}
    if shot_score.BLUR_FILL in choice:
        detail = shot_score.blur_fill_detail(target.get("source_size"), box)
        if detail is not None:
            # CF-0903: who found the framing low - this probe (the crop cuts
            # the subject), or the picture's record alone (this probe's crop
            # keeps it; the record is the resolver's, a later probe frame of
            # the cut clip - CF-0904): only the second is taken back past the
            # strip allowance (shot_score.take_back_strips).
            detail[shot_score.FRAMED_BY] = (
                shot_score.FRAMED_BY_PROBE if shot_score.LOW_FRAMING in soft
                else shot_score.FRAMED_BY_RECORD)
            shown[shot_score.BLUR_FILL] = detail
    if shot_score.LUMA_LIFT in choice:
        gain = choice[shot_score.LUMA_LIFT]["gain"]
        try:
            from qc_asset import lifted_luma
            after = lifted_luma(probe_path, gain)
        except Exception:   # no probe to measure: a lift nobody measured is not taken
            after = None
        if after is not None and after >= shot_score.LUMA_FLOOR:
            shown[shot_score.LUMA_LIFT] = {"gain": gain,
                                           "luma_before": qc.get("mean_luma"),
                                           "luma_after": round(after, 1)}
    if not shown:
        return {}
    target[shot_score.PRESENTATION_FIELD] = shown
    if shot_score.BLUR_FILL in shown:
        target["fit"] = "contain"
    presented.setdefault((i, shot_key), set()).update(shown)
    bits = []
    if shot_score.BLUR_FILL in shown:
        r = shown[shot_score.BLUR_FILL]["rect"]
        bits.append(f"blur_fill (whole picture {r['width']}x{r['height']} at "
                    f"y={r['y']} over its own blurred frame, instead of a crop "
                    f"keeping {info.get('roi_coverage', 0):.0%} of the subject)")
    if shot_score.LUMA_LIFT in shown:
        d = shown[shot_score.LUMA_LIFT]
        bits.append(f"luma_lift x{d['gain']} (mean luma {d['luma_before']} -> "
                    f"{d['luma_after']})")
    notes.append(f"block {i}{where}: shown " + " + ".join(bits) + " - priced "
                 + ", ".join(f"{shot_score.presentation_key(m)} "
                             f"{shot_score.presentation_price(m)}" for m in shown)
                 + " instead of " + ", ".join(
                     f"{shot_score.price_key(shot_score.FIXES[m])} "
                     f"{shot_score.soft_price(shot_score.FIXES[m])}" for m in shown)
                 + " (CF-0436)")
    return shown


def take_back_strips(blocks, presented, notes, screen_height=1920):
    """CF-0903: shot_score.take_back_strips() on the plan's blocks, and the
    plan stage told: each picture taken back leaves `presented` (so its
    `low_framing` is charged at its own price by plan_findings and no
    presentation is) and is said in the notes. Returns the record."""
    rec = shot_score.take_back_strips(blocks, screen_height=screen_height)
    for t in rec["taken_back"]:
        key = (t["block"], t["shot"])
        if shot_score.BLUR_FILL not in presented.get(key, ()):
            key = next((k for k, modes in presented.items()
                        if k[1] == t["shot"] and shot_score.BLUR_FILL in modes), key)
        modes = presented.get(key)
        if modes is not None:
            modes.discard(shot_score.BLUR_FILL)
            if not modes:
                presented.pop(key, None)
        where = f"block {t['block']}" + (f" (cut {t['cut']})" if t["cut"] is not None else "")
        notes.append(f"{where}: blur_fill taken back - {t['seconds']:g} s of strip "
                     f"({t['share']:.0%} of the height) asked for by the pool's record "
                     f"alone, this plan's probe keeps the subject in the crop; the "
                     f"plan's strip ran past {rec['allow_seconds']:g} s "
                     f"({shot_score.STRIP_TASK})")
    if rec["taken_back"]:
        notes.append(f"strip on blur: {rec['seconds_before']:g} s -> "
                     f"{rec['seconds_after']:g} s ({len(rec['taken_back'])} picture(s) "
                     f"back to the crop, {rec['kept_by_probe_seconds']:g} s kept where "
                     f"the probe's own crop cuts the subject) ({shot_score.STRIP_TASK})")
    return rec


def similarity_findings(story, off_topic=None):
    """CF-0433: `score.low_similarity`, one per block whose picture scores
    under the similarity floor.

    The resolver marks such a block `below_floor` (it admitted the candidate
    because nothing at or above the floor filled the block); the finding
    names that block. An `unresolved_anchors` record with `best_used_score`
    under its floor (`under_floor_anchors()`) whose phrase no marked block
    carries - a storyboard from before CF-0433 - is priced too, by phrase,
    so no under-floor picture goes on screen for free. Topic-footage blocks
    (`topic_fill`, CF-0337) are not priced: docs/score-model.md, "кадры темы
    не считаются". Pure."""
    out, seen = [], set()
    for i, b in enumerate((story or {}).get("blocks") or []):
        bf = b.get("below_floor") if isinstance(b, dict) else None
        if not isinstance(bf, dict):
            continue
        seen.add((bf.get("phrase") or "").strip())
        t0 = b.get("_start")
        out.append(_score.finding(
            _score.RULE_LOW_SIMILARITY, {"block": i, **({"t": t0} if t0 is not None else {})},
            hook=_score.in_hook(t0),
            note=f"shot {b.get('shot')} scores {bf.get('score')} against the "
                 f"{bf.get('min_score')} floor - the best the pool had for "
                 f"{(bf.get('phrase') or '')[:80]!r}"))
    if off_topic is None:
        off_topic = under_floor_anchors(story or {})
    for r in off_topic:
        phrase = (r.get("phrase") or "").strip()
        if phrase in seen:
            continue
        seen.add(phrase)
        out.append(_score.finding(
            _score.RULE_LOW_SIMILARITY, {"phrase": phrase[:80]},
            note=f"picture scores {r['score']} against the {r['min_score']} floor"))
    return out


def too_short_findings(story, notes, priced=None):
    """CF-0453: `score.block_too_short` for every block the resolver noted as
    too tight to read (rhythm.block_too_short_findings()). Returned only when
    the root's price table carries the rule (`priced`, default
    `_score.has_rule`); otherwise `[]` and one line in `notes` with the
    count and what it would cost at the proposed price - the rule waits for
    the user's signature (CF-0320), the plan is not refused on it either
    way."""
    found = rhythm.block_too_short_findings(story)
    if not found:
        return []
    if (priced or _score.has_rule)(rhythm.SCORE_BLOCK_TOO_SHORT):
        return found
    would = min(len(found) * rhythm.BLOCK_TOO_SHORT_PRICE, rhythm.BLOCK_TOO_SHORT_CAP)
    notes.append(
        f"{len(found)} block(s) shorter than {rhythm.MIN_ANCHOR_GAP_SECONDS}s "
        f"(too tight to read) - built and shown, not refused; "
        f"{rhythm.SCORE_BLOCK_TOO_SHORT} is not in the price table yet, so "
        f"unpriced (proposed {rhythm.BLOCK_TOO_SHORT_PRICE} a block, cap "
        f"{rhythm.BLOCK_TOO_SHORT_CAP}: -{would} here) (CF-0453)")
    print(f"  WARNING: {notes[-1]}", file=sys.stderr)
    return []


def still_share_gate(args, plan, plan_score, story):
    """CF-0418: measure the still share of the assembled plan, add its
    findings to the plan stage of the score log (and to `plan["score"]`), and
    refuse the plan above the channel's `video_editor.max_still_share` with
    gate `still_share_over_half`. Returns the record (also `plan["still_share"]`).

    The refusal is the hard share only (variant (a)). A frame held off a
    video and stretched past twice its shot (the user, 2026-09-30) goes into
    the soft share instead - `score.stretched_still_share`, a penalty the
    score weighs, never a refusal here. The shot's source length is stamped
    onto the block / cut (`shot_seconds`), off the indexes this plan was
    resolved against and the pool, so the plan answers after the pool is gone."""
    dirs = list(dict.fromkeys([str(Path(i).parent) for i in (getattr(args, "index", None) or [])]
                              + [str(d) for d in share_gate.footage_dirs()]))
    shots_of = share_gate.shot_reader(dirs)
    share_gate.stamp_shot_seconds(plan, shots_of)
    rec = share_gate.measure(plan, share_gate.max_share(load_channel_cfg(args)), shots_of)
    plan["still_share"] = rec
    st = rec["stretched"]
    runlog.annotate(still_share=(f"{'OVER' if rec['over'] else 'ok'} "
                                 f"{rec['share']} of {rec['running_seconds']}s "
                                 f"(max {rec['threshold']}); with stretched held frames "
                                 f"{st['share']} ({st['penalty']:g})"))
    found = share_gate.findings(rec)
    if found:
        block = _score.score_block(list(plan_score.get("findings") or []) + found)
        line = score_log.record(args.output, score_log.STAGE_PLAN,
                                block.get("findings") or [],
                                script_id=refusal_script_id(args, story)).get("line")
        if line:
            block["line"] = line
            print(f"  SCORE after plan (still share): {line}", file=sys.stderr)
        plan_score.clear()
        plan_score.update(block)
        plan["score"] = plan_score
    if rec["over"]:
        refuse_plan(args, plan_refusal.GATE_STILL_SHARE, "PICTURES OVER THE STILL SHARE",
                    share_gate.report_lines(rec),
                    deficit=share_gate.write_deficit(args.output, rec), story=story,
                    supersedes_video=bool(args.degrade_block))
    return rec


def held_soft_gate(args, plan, plan_score, story, notes=None):
    """CF-0465: the sharpness of every frame the render holds (the held_frame
    picture itself, `held_sharpness.py`), stamped onto its block / cut while
    the picture is there, the record in `plan["held_sharpness"]`. A held frame
    under the floor is `score.held_soft_frame` per second on screen - charged
    only once the root's table carries the row with the user's signature;
    until then it is a warning (the record's `mode`, a note), nothing taken."""
    base = Path(args.output).parent
    held_sharpness.stamp(plan, base=base)
    rec = held_sharpness.record(plan)
    m = held_sharpness.mode()
    rec["mode"] = m["mode"]
    plan["held_sharpness"] = rec
    line = held_sharpness.describe(rec, m)
    runlog.annotate(held_sharpness=line)
    if rec["soft_seconds"] > 0:
        print(f"  HELD SOFT FRAME: {line}", file=sys.stderr)
        if notes is not None:
            notes.append(line)
    found = held_sharpness.findings(rec, m)
    if found:
        block = _score.score_block(list(plan_score.get("findings") or []) + found)
        sline = score_log.record(args.output, score_log.STAGE_PLAN,
                                 block.get("findings") or [],
                                 script_id=refusal_script_id(args, story)).get("line")
        if sline:
            block["line"] = sline
            print(f"  SCORE after plan (held soft frames): {sline}", file=sys.stderr)
        plan_score.clear()
        plan_score.update(block)
        plan["score"] = plan_score
    return rec

def held_screen_gate(args, plan, plan_score, story, notes=None):
    """CF-0646: every held frame read as it is SHOWN (`held_screen.py`) - its
    height on screen, its sharpness at screen scale, how much native detail
    its source has, a body with the head out of frame - stamped onto its
    block / cut while the picture is there, plus the thin moving pictures
    from the plan's geometry; the record in `plan["held_screen"]`. Each rule
    (`score.thin_picture`, `score.held_cut_subject`, `score.held_soft_stretch`)
    is charged only once the root's table carries its row with the user's
    signature; until then a warning (the record's `modes`, a note)."""
    held_screen.stamp(plan, base=Path(args.output).parent)
    # CF-0650: a contained clip that barely moves is read like a held one
    held_screen.stamp_motion(plan, base=Path(args.output).parent)
    rec = held_screen.record(plan)
    modes = held_screen.mode()
    rec["modes"] = {r: m["mode"] for r, m in modes.items()}
    plan["held_screen"] = rec
    line = held_screen.describe(rec, modes)
    runlog.annotate(held_screen=line)
    if rec["findings"]:
        print(f"  HELD/LONG PICTURE ON SCREEN: {line}", file=sys.stderr)
        if notes is not None:
            notes.append(line)
    found = held_screen.findings(rec, modes)
    if found:
        block = _score.score_block(list(plan_score.get("findings") or []) + found)
        sline = score_log.record(args.output, score_log.STAGE_PLAN,
                                 block.get("findings") or [],
                                 script_id=refusal_script_id(args, story)).get("line")
        if sline:
            block["line"] = sline
            print(f"  SCORE after plan (held/long pictures on screen): {sline}",
                  file=sys.stderr)
        plan_score.clear()
        plan_score.update(block)
        plan["score"] = plan_score
    return rec


def held_motion_gate(args, plan, plan_score, story, notes=None):
    """CF-0481: every frame the render holds is read against its source shot
    (`held_motion.py`): how much the shot moves around the held moment and
    how big a face the held picture shows, stamped onto its block / cut while
    the source is in the pool, the record in `plan["held_motion"]`. Faces
    held still out of moving shots over `held_motion.ALLOW` seconds are
    `score.held_moving_face` per second over - charged only once the root's
    table carries the row with the user's signature; until then a warning
    (the record's `mode`, a note), nothing taken."""
    dirs = list(dict.fromkeys([str(Path(i).parent) for i in (getattr(args, "index", None) or [])]
                              + [str(d) for d in share_gate.footage_dirs()]))
    held_motion.stamp(plan, base=Path(args.output).parent, dirs=dirs)
    rec = held_motion.record(plan)
    m = held_motion.mode()
    rec["mode"] = m["mode"]
    plan["held_motion"] = rec
    line = held_motion.describe(rec, m)
    runlog.annotate(held_motion=line)
    if rec["over_seconds"] > 0:
        print(f"  HELD MOVING FACE: {line}", file=sys.stderr)
        if notes is not None:
            notes.append(line)
    found = held_motion.findings(rec, m)
    if found:
        block = _score.score_block(list(plan_score.get("findings") or []) + found)
        sline = score_log.record(args.output, score_log.STAGE_PLAN,
                                 block.get("findings") or [],
                                 script_id=refusal_script_id(args, story)).get("line")
        if sline:
            block["line"] = sline
            print(f"  SCORE after plan (held moving faces): {sline}", file=sys.stderr)
        plan_score.clear()
        plan_score.update(block)
        plan["score"] = plan_score
    return rec

def held_frame_band_gate(args, plan, plan_score, story, pattern):
    """CF-0859: a held picture past the top of an observed (emergent) hold
    band - `score.hold_band_exceeded`, -2 a block (rhythm.py). The plan-stage
    price of CF-0433 asks hold_band_findings(), which charges a drawn band
    only; explainer's band is emergent, so vanguards-doomsday of
    example-film/2026-10-24T0840Z held a sharp still 10.10 s against its 8.0 s
    top and paid nothing. Asked here, on the final blocks (cuts, degradation
    and held re-cuts done), before late_score_stop() - the price is already
    signed, so under N the plan is refused by the score, no new code."""
    found = rhythm.held_frame_over_band_findings(plan.get("blocks") or [], pattern)
    if not found:
        return []
    block = _score.score_block(list(plan_score.get("findings") or []) + found)
    sline = score_log.record(args.output, score_log.STAGE_PLAN,
                             block.get("findings") or [],
                             script_id=refusal_script_id(args, story)).get("line")
    if sline:
        block["line"] = sline
        print(f"  SCORE after plan (held frame over the hold top): {sline}",
              file=sys.stderr)
    plan_score.clear()
    plan_score.update(block)
    plan["score"] = plan_score
    return found


def late_score_stop(args, plan_score, story):
    """CF-0794: the early stop asked once more, after every plan-stage gate.

    CF-0433's check (`plan_score_refusal`) runs on the prices the plan has
    when its blocks are cut; the still share, the held frames read as shown
    (`score.thin_picture`), the held faces (`score.held_moving_face`) and the
    one-source line are priced later, into the same plan stage of the log. A
    video those prices put under N used to be written as a plan, refused by
    render_video.py (exit 4) with no refusal anywhere - the operator went on
    to QC a file that was never rendered and the batch lost the script
    (street-fighter, example-film 2026-10-18T0841Z, F · 36,08).

    So: the log as it stands (`score_log.current`, the very block
    render_video.py asks), and under N the score's own sidecar
    (`<plan stem>.score.refusal.json`, gate and funnel code
    `score_below_threshold`, `supersedes_video`) through `score_log.check()`,
    the plan not written, exit 2 - the CF-0254 refusal shape. At or over N a
    stale sidecar of an earlier build is removed (the log forgot its later
    stages when this plan stage was recorded). Returns None when the plan
    goes on."""
    block = score_log.current(args.output)
    if block is None:
        block = dict(plan_score)
    side = score_log.check(args.output, block, refusal_script_id(args, story),
                           score_log.STAGE_PLAN)
    if not side:
        return None
    line = block.get("line") or plan_score.get("line") or score_log.summary_line(block)
    # the record is written (score_log.check above) - the CF-0254 shape of
    # refuse_plan(), with the score's own sidecar instead of plan.refusal.json
    headline = "SCORE UNDER THE THRESHOLD after the plan's last gates"
    print(f"{headline} - plan not written:", file=sys.stderr)
    print(f"  {score_log.stop_line({**block, 'line': line}, score_log.STAGE_PLAN, side)}",
          file=sys.stderr)
    for x in _score.lines(block):
        if x:
            print(f"  {x}", file=sys.stderr)
    print(f"  refusal -> {side} ({plan_refusal.code_for(plan_refusal.GATE_SCORE)}: "
          f"{refusal_script_id(args, story)})", file=sys.stderr)
    runlog.annotate(refused=f"{plan_refusal.GATE_SCORE} "
                            f"{plan_refusal.code_for(plan_refusal.GATE_SCORE)}")
    sys.exit(2)


def supplement_request_for(output):
    """CF-0480: the topic's thin-pool supplement request in the batch this plan
    lies in (CF-0345: `<batch>/work/supplement-requests/<topic>.json` pending,
    `consumed/<topic>.json` answered) and what the supplement step did with
    it (`work/supplement-step.json`), or None outside a batch / without a
    topic id (`order.json` beside the plan)."""
    found = attempts.batch_context(output)
    if not found:
        return None
    batch, slug = found
    work = batch / "work"
    try:
        topic = json.loads((work / slug / "order.json").read_text()).get("topic_id")
    except (OSError, ValueError, AttributeError):
        topic = None
    if not topic:
        return None
    out = {"topic_id": topic, "request": None, "state": None, "step": None}
    for state, path in (("pending", work / "supplement-requests" / f"{topic}.json"),
                        ("consumed", work / "supplement-requests" / "consumed"
                         / f"{topic}.json")):
        if path.exists():
            out["request"], out["state"] = str(path), state
            break
    try:
        step = json.loads((work / "supplement-step.json").read_text())
        topics = step.get("topics") or {}
        rec = topics.get(topic) if isinstance(topics, dict) else None
        if isinstance(rec, dict):
            out["step"] = {k: rec.get(k) for k in ("phase", "outcome") if rec.get(k)}
    except (OSError, ValueError, AttributeError):
        pass
    return out


def pool_holds_gate(args, plan, plan_score, story, warnings, notes=None):
    """CF-0480 items 3-4, after the still share is measured.

    Item 4: whose frames the video holds (`still_share.held_sources`) -
    `plan["still_share"]["held_sources"]`, a note when one upload is behind
    all of them, and its own line of the score log once the root's table
    prices `score.held_one_source` (signed 2026-10-02 at 0, CF-0490: a visible
    0-point line, never a penalty).

    Item 3: the resolver cut every stretched one-frame block it could into
    2-3 shots of its phrase; the blocks it could not (`stretch_split.short`)
    are the pool's shortage. When they leave the video over the stretched
    line, the plan says "the pool does not hold this video" - gate
    `pool_holds_video` (funnel `pool_too_thin`), with the topic's supplement
    request, the existing answer to a thin pool (CF-0345) - instead of
    building it silently. A new refusal priced on the replay (CF-0320), so a
    WARNING until the user signs the price: the plan is written."""
    rec = plan.get("still_share") or {}
    src = share_gate.held_sources(plan)
    rec["held_sources"] = src
    if src.get("one_source") and src.get("held_seconds"):
        line = share_gate.describe_sources(src)
        runlog.annotate(held_sources=line)
        if notes is not None:
            notes.append(line)
    found = share_gate.one_source_findings(src)
    if found:
        block = _score.score_block(list(plan_score.get("findings") or []) + found)
        sline = score_log.record(args.output, score_log.STAGE_PLAN,
                                 block.get("findings") or [],
                                 script_id=refusal_script_id(args, story)).get("line")
        if sline:
            block["line"] = sline
        plan_score.clear()
        plan_score.update(block)
        plan["score"] = plan_score
    pool = share_gate.pool_holds(plan, rec)
    plan["pool_holds"] = pool
    if pool["verdict"] != share_gate.POOL_SHORT:
        return pool
    sup = supplement_request_for(args.output)
    pool["supplement"] = sup
    lines = [share_gate.describe_pool(pool)]
    if sup and sup.get("request"):
        lines.append(f"the topic's supplement request: {sup['request']} ({sup['state']}"
                     + (f"; supplement step {sup['step']}" if sup.get("step") else "")
                     + ") - more footage of the topic is the answer (CF-0345)")
    else:
        lines.append("no supplement request for this topic in the batch - the "
                     "answer is more footage of the topic (CF-0338/CF-0345)")
    lines.append(f"warning, not a refusal: a new refusal waits for the user's "
                 f"signature under its price (CF-0320, {share_gate.POOL_TASK})")
    reason = plan_refusal.reason_text("THE POOL DOES NOT HOLD THE VIDEO", lines)
    w = plan_refusal.warning(refusal_script_id(args, story), plan_refusal.GATE_POOL_HOLDS_VIDEO,
                             reason, numbers={"share": pool["share"],
                                              "short_blocks": len(pool["short_blocks"]),
                                              "split_blocks": pool["split_blocks"]})
    w["decision"] = (f"CF-0320: a new refusal, unsigned - a warning until the user "
                     f"signs its price ({share_gate.POOL_TASK})")
    warnings.append(w)
    print("THE POOL DOES NOT HOLD THE VIDEO - WARNING, the plan is written "
          f"[{plan_refusal.code_for(plan_refusal.GATE_POOL_HOLDS_VIDEO)}/{plan_refusal.GATE_POOL_HOLDS_VIDEO}]",
          file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)
    runlog.annotate(warned=f"{plan_refusal.GATE_POOL_HOLDS_VIDEO} "
                           f"{plan_refusal.code_for(plan_refusal.GATE_POOL_HOLDS_VIDEO)}")
    if notes is not None:
        notes.append(lines[0])
    return pool


def plan_score_refusal(args, plan_score, hold_break, story, supersedes_video=False):
    """CF-0433: the one refusal left of the three rules - the score under N.

    `pattern_ceiling` when a pace, hold-band or block-band (CF-0447) price is
    in the log (the gate
    they used to refuse under, so the funnel code and 6b's reading do not
    move; the deficit file carries the score beside the hold record), else
    `unresolved_anchor` (the similarity floor's gate). Does not return."""
    rules = {f["rule"] for f in plan_score.get("findings") or []}
    head = (f"score {plan_score.get('score')} under the threshold "
            f"{plan_score.get('threshold')} (tier {plan_score.get('tier')})"
            + (f" - {plan_score['line']}" if plan_score.get("line") else ""))
    lines = [head] + [x for x in _score.lines(plan_score) if x]
    if rules & {rhythm.SCORE_PACE_BELOW_FLOOR, rhythm.SCORE_HOLD_BAND_EXCEEDED,
                 rhythm.SCORE_BLOCK_BAND_EXCEEDED}:
        rec = dict(hold_break or {"kind": "pattern_ceiling_break"})
        rec["cause"] = rec.get("cause") or "score"
        rec["score"] = plan_score
        rec.setdefault("fixable_by_anchors", None)
        refuse_plan(args, plan_refusal.GATE_PATTERN_CEILING, "PATTERN CEILING BROKEN",
                    lines, deficit=write_pattern_ceiling_deficit(args.output, rec),
                    story=story, supersedes_video=supersedes_video)
    refuse_plan(args, plan_refusal.GATE_UNRESOLVED_ANCHOR, "UNDER-FLOOR PICTURE",
                lines, story=story, supersedes_video=supersedes_video)


# ---------------------------------------------------------------------------
# CF-0270: the ceiling a degradation broke, and the refusal that follows.
#
# `example-film/2026-09-17T1901Z`, `mormon-wives-comeback`, is the case. Block 0
# was 4.86s long against a 2.17s clip, so it was degraded clip -> still before
# the render (CF-0131/CF-0249, the loop below). `contrast` draws a
# 1.5-3.5s hold band, CF-0245's trim could not hand the 1.36s overshoot to
# block 1 (its clip is 1.867s and does not have the footage), and so the video
# shipped as 4.86s of one motionless frame under a pattern whose ceiling is
# 3.5s: `pattern_delivered: null`, `qc.passed: true`, three render attempts
# spent, and a finished video recorded ready. DoD 1.4.4 item 3 says the
# opposite in one sentence - every ready video delivers the pattern it was
# assigned, and a topic that cannot is refused with a code *before* the render.
#
# So the judgement is not re-derived here. `rhythm.pattern_shortfalls()` is the
# one pattern judge in this repo (CF-0192) and it has already run by the time
# this is asked; this reads its answer and decides what to do about it. Three
# things have to be true, **of one and the same block** - and the join is the
# whole rule, not a detail of it:
#
#   1 the pattern's hold band was *ordered* (`mode: "drawn"`) and the video is
#     over its top. `emergent` is an observation and never refuses a video -
#     CF-0039's rule, kept here exactly as CF-0192 kept it; and a video *under*
#     the band's floor is a different fault that trimming cannot answer;
#   2 the block that is over it - the one whose span *is* `cadence.longest`,
#     matched on the number both records carry - was degraded. That is what
#     makes the measurement literal rather than conservative: the cadence
#     treats every block as a hold, and a block playing real footage for 4.86s
#     is not holding a key frame for 4.86s. A degradation is what turns it into
#     one, and `key_frame_hold_seconds` is exactly how long one frame may be
#     held;
#   3 CF-0245's trim was asked about that block and the obstacle was
#     **footage** - `next_block_has_no_clip` or `next_clip_too_short`. This is
#     the ladder's own shape: the remedy order is a replacement clip first and
#     a refusal second, so the refusal belongs where a replacement would have
#     been the answer and the pool did not have one.
#
# Three things it deliberately does not refuse, each because something else
# already owns it:
#
#   * `rhythm_not_as_ordered`, which rides in the same shortfall list. It is
#     CF-0057's subject, it has been recorded and shipped for dozens of
#     batches, and widening this gate to it would refuse most of them;
#   * a block over the band that was *not* degraded. The picture is still
#     moving; CF-0245 looked at exactly this and decided to ship it long rather
#     than freeze it shorter, and `pattern_delivered: null` already says what
#     it is;
#   * the structural refusals - `no_next_block` (the last block, which runs to
#     the end of the audio and has no next anchor at all) and
#     `next_block_would_leave_band` (handing the remainder on would move the
#     failure rather than end it). No clip in any pool answers either, so
#     "replacement, then refusal" has no first rung to have failed. Those are
#     anchor-coverage faults (CF-0129/CF-0232/CF-0233) wearing a montage's
#     clothes, and a gate here would refuse a large share of the corpus for a
#     reason it cannot act on.
#
# The remedy order is replacement first, refusal second - and the replacement
# rung is already spent by the time a storyboard reaches this stage.
# `resolve_anchors.py` sorts each block's pool long-enough-first
# (`available_seconds(c) < need`, :1327/:1860/:1998) precisely so that a block
# gets a clip that covers it and only holds a frame when no candidate does. A
# storyboard whose block outruns its clip is therefore the pool's own answer,
# not an unasked question, and this stage has neither the index nor the cutter
# to ask it again. What it can do is say what a replacement would have had to
# be - `replacement_requirement()` below - so the number is in the deficit
# instead of in someone's head.
#
# CF-0278: and the sort is no longer the evidence. The resolver writes what a
# one-shot block was offered - each long-enough candidate's
# `available_seconds` and what became of it - as `length_supply` on the
# storyboard block, and the `degradation` record copies it for the blocks it
# names (`length_supply_evidence()`). The record showed why the sentence above
# had stopped being true: from CF-0435 to CF-0517 fill() walked the pool in
# usability rank, "long enough first" held only among shots of one score, and
# a short clean shot won a block a long-enough one could have filled (corpus
# of 2026-10-04: 40 of 56 held one-shot blocks, docs/empty-block-ladder.md).
# CF-0517 made it true again - a one-shot block's match, side retry and topic
# rung walk length first, usability second (`rank_by_usability(need=)`), and
# `length_supply.rung_order` says so per run. Two edges stay: the under-floor
# rung (CF-0433) walks by rank alone, and a long-enough candidate a gate
# refused (`outcome: refused`) is the pool's answer in the gate's words.
# ---------------------------------------------------------------------------

PATTERN_CEILING_DEFICIT_SUFFIX = ".pattern-ceiling.json"

# The two trim refusals a replacement clip would have answered: the next block
# has no footage of its own, or the footage it has is too short. The other two
# (`no_next_block`, `next_block_would_leave_band`) are structural - see the note
# above - and no pool answers them, so they are not this gate's business.
POOL_HOLD_TRIM_CODES = (HOLD_TRIM_NEXT_HAS_NO_CLIP, HOLD_TRIM_NEXT_CLIP_TOO_SHORT)

# ---------------------------------------------------------------------------
# CF-0303: the second way the same ceiling breaks, and why it is the same gate.
#
# `example-film/2026-09-21T0358Z`, `coach-hale-stadiums`, is the case. `contrast`
# draws a 1.5-3.5s hold band; the Content Researcher checked the layout before
# TTS was paid for (`03-content-researcher.json#scripts[].anchor_cadence.layout`,
# CF-0277) and its longest block came out 3.405s - inside the band, zero
# breaches, the script passed. Then the wav was made, the words were aligned,
# and the *same* layout rule on the real speech put blocks 6, 7, 13 and 15 at
# 3.6 / 3.76 / 3.52 / 4.54s. All four are `boundary_is_the_rhythm`: their edges
# are the swing the rhythm named, so the layout may not cut inside them
# (CF-0276), and CF-0245's trim had no footage to hand the overshoot to. The
# plan wrote `pattern_delivered: null`, `pattern_not_delivered:
# "hold_outside_band"` - and went to the render.
#
# CF-0270's gate above let it through, and the reason is exactly its third
# condition: the block over the band has to have been **degraded**. That
# condition is what made CF-0270's measurement literal - a block playing real
# footage for 4.86s is not holding a key frame for 4.86s. Here nothing was
# degraded: the pictures move. What is over the ceiling is the *writing* -
# there are too many spoken words between two anchors for any montage to cut
# the stretch shorter, and `rhythm.ceiling_report()` says so with numbers, one
# stage earlier, before a single clip was cut.
#
# So this is not a second mechanism; it is a second **cause** admitted to the
# one gate. Both causes end in the same sentence - a video that cannot deliver
# the pattern it was assigned is refused before the render, with a code, and
# never shipped with `pattern_delivered: null` (DoD 1.4.4 item 3) - and they
# ride the same refusal: `plan_refusal.GATE_PATTERN_CEILING`, the same
# `pattern_undeliverable` funnel code, the same deficit file, the same exit.
# What differs is the remedy the record points at, and that is why the record
# carries `cause`:
#
#   * `degradation` (CF-0270): the pool had no clip long enough for the block,
#     so the picture froze. The remedy is footage - `replacement` says how much;
#   * `layout` (CF-0303): the block is over the ceiling *as laid out*, before
#     any clip. The remedy is the script - fewer words between those anchors, or
#     another anchor inside the stretch - and the reader has to be told that the
#     Researcher's pass on this script was made on an estimate of the speech and
#     not on the wav, or the next reader looks for the defect in the montage.
#
# Deliberately not widened further, for CF-0270's own reasons kept intact: an
# `emergent` envelope never refuses a video (CF-0039), `rhythm_not_as_ordered`
# is CF-0057's subject and not a refusal, and a breach under
# `rhythm.HOLD_BAND_TOP_TOLERANCE_SECONDS` is not a breach at all.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# CF-0310: the third cause - the band that is not the hold band
#
# `2026-09-21T1541Z`, `outrider-doune-castle`: `explainer` / `even`, 10 blocks,
# 28.7s of them. `pattern_delivered: null`, `pattern_not_delivered:
# "block_count_outside_band"` - and it rendered, passed QC, passed the frame
# judge and went to the user, because this gate looked at one parameter of the
# two. `key_frame_hold_seconds` was guarded twice over (CF-0270, CF-0303) and
# `block_count` not at all, and nothing in either task's reasoning says the hold
# band is the only band a plan can fail on: what they say is that a video which
# cannot deliver its pattern is refused before the render.
#
# So the same gate takes a third cause, `cadence`, and it is the plainest of the
# three. There is no remedy inside this repo to try first: the block count is
# the number of resolved anchors and it was fixed one stage earlier, before a
# clip was cut - no trim moves it, no replacement clip changes it. The remedy is
# the script, which is the `layout` cause's remedy, so the record carries the
# same `estimate_record`.
#
# What it deliberately does not do, both for CF-0039's reason kept intact by
# CF-0270 and because the corpus says so: it does not fire on an `emergent`
# envelope. Re-judged on 2026-09-22, ten of the eleven plans on disk that carry
# a pattern have at least one shortfall and only `delver` has none, so "any
# `pattern_not_delivered` refuses" would refuse 10 of 11 - most of them on
# `explainer`'s two emergent envelopes and on `rhythm_not_as_ordered`, which is
# CF-0057's subject and not a refusal.
#
# Nor does it refuse under the floor of a band stated as a *count*: see
# `cadence_band_break()` for why, and for the three real layouts that rule
# spares. As written, this cause refuses nothing that is on disk today - it
# guards the ceiling, and the floor only once a band is stated as a rate - and
# that is the honest reading of the measurement rather than a weakness:
# nothing in the corpus is over a drawn ceiling, and every floor breach there
# is a length, not a cadence.
#
# `outrider-doune-castle` itself is therefore *not* closed by this cause -
# `explainer`'s envelope is emergent - and that is the honest half of CF-0310:
# the measurement found the band, not the gate, is what is wrong there. 10
# blocks in 28.7s is 20.91 blocks/min, inside the 15.39-47.88 blocks/min the
# very batches the envelope was frozen over actually ran; the count 12-33 was
# measured on 40.0-46.8s of blocks and carries those lengths inside it. See
# `rhythm.BLOCK_COUNT_PARAMETER_FORMS`: this file reads whichever shape the
# root's pattern declares, so the day `patterns/explainer.json` states the
# envelope as a rate, that plan is delivered and needs no refusal at all.
# ---------------------------------------------------------------------------

CEILING_CAUSE_DEGRADATION = "degradation"
CEILING_CAUSE_LAYOUT = "layout"
CEILING_CAUSE_CADENCE = "cadence"

# Where the pre-TTS reading of *this* band belongs. The `layout` cause points
# at `.layout` because that reading exists and was taken; this one points at a
# reading CF-0310's spec asks the Content Researcher to start taking, and
# until it does the field is absent - which is the finding, not an oversight:
# nobody measured this band before the wav was paid for, which is how a plan
# reached the render with `block_count_outside_band` on it.
BLOCK_BAND_RECORD_PATH = (
    "03-content-researcher.json#scripts[].anchor_cadence.block_band")
# CF-0365/CF-0370: where the same band is read in *pictures* rather than in
# segments - the replay of the resolver's shot hand-out, which is the count an
# `even` plan is refused on.
PICTURE_BAND_RECORD_PATH = (
    "03-content-researcher.json#scripts[].block_capacity.picture_band")

# Where the pre-TTS reading of this same layout lives, named in the refusal so
# the next reader knows which stage has to change and on what it decided.
ESTIMATE_RECORD_PATH = (
    "03-content-researcher.json#scripts[].anchor_cadence.layout")


def layout_ceiling_breaches(ceiling):
    """The blocks `rhythm.ceiling_report()` could not bring under the top.

    Reads the storyboard's record and measures nothing: `resolve_anchors.py`
    wrote it from the real alignment before the first clip was cut, and the
    tolerance is applied with the same `rhythm.over_band_top()` the report
    itself used, so a record and a gate can never disagree about what "over"
    means.
    """
    ceiling = ceiling or {}
    band = ceiling.get("band") or {}
    if band.get("mode") != "drawn":
        return []
    return [b for b in ceiling.get("breaches") or []
            if rhythm.over_band_top(b.get("measured"), b.get("band_max"))]


def replacement_requirement(trims):
    """Per refused trim, the footage that would have ended the break.

    One entry per `applied: false` record that named a next block, carrying the
    seconds that block's clip has against the seconds the extended block would
    play of it. `needed`/`has` are CF-0245's own numbers, copied rather than
    recomputed; a record that refused for a reason with no next block (the last
    block, a next block that is not a clip at all) carries `has: None` and says
    so in `code`.
    """
    out = []
    for t in trims or []:
        if t.get("applied") or t.get("next_block") is None:
            continue
        out.append({
            "block": t.get("block"),
            "next_block": t.get("next_block"),
            "code": t.get("code"),
            "has": t.get("next_clip_seconds"),
            "needed": t.get("next_clip_needed"),
            "short_by": (round(t["next_clip_needed"] - t["next_clip_seconds"], 3)
                         if t.get("next_clip_needed") is not None
                         and t.get("next_clip_seconds") is not None else None),
        })
    return out


def length_supply_evidence(trims, blocks):
    """CF-0278: the recorded fact the `degradation` cause stands on - per
    block the refusal names (the degraded one and the next one its trim
    could not hand the overshoot to), the resolver's `length_supply` copied
    off the plan block: which candidates were long enough, their
    `available_seconds`, and what became of each. `recorded: false` when the
    block carries no such record (a storyboard from before CF-0278, a
    multi-shot block) - the refusal then says so instead of citing the sort.
    Reads, measures nothing."""
    blocks = blocks or []
    out, seen = [], set()
    for t in trims or []:
        for role, i in (("degraded", t.get("block")), ("next", t.get("next_block"))):
            if not isinstance(i, int) or (role, i) in seen:
                continue
            seen.add((role, i))
            b = blocks[i] if 0 <= i < len(blocks) else {}
            rec = b.get("length_supply") if isinstance(b, dict) else None
            out.append({"block": i, "role": role,
                        "recorded": isinstance(rec, dict),
                        "record": rec if isinstance(rec, dict) else None})
    return out


def length_supply_line(ev):
    """One finding line per `length_supply_evidence()` entry."""
    i, role = ev.get("block"), ev.get("role")
    rec = ev.get("record")
    if not ev.get("recorded") or not rec:
        return (f"block {i} ({role}): which candidates were long enough is not "
                f"recorded (storyboard without `length_supply`, CF-0278) - "
                f"re-resolve to see what the pool offered")
    long_ = rec.get("long_enough") or []
    head = (f"block {i} ({role}) needed {rec.get('need_seconds')}s; the pool "
            f"offered {rec.get('offered')} candidate(s), "
            f"{rec.get('long_enough_offered')} long enough, the longest "
            f"{rec.get('longest_available_seconds')}s")
    if not long_:
        return head + " - none long enough"
    named = "; ".join(
        f"{e.get('shot')} {e.get('available_seconds')}s {e.get('outcome')}"
        + (f" ({e['reason']})" if e.get("reason") else "")
        for e in long_[:3])
    return head + ": " + named + (" ..." if len(long_) > 3 else "")


def pattern_ceiling_break(pattern_short, hold_trims, degraded_blocks,
                          ceiling_report=None, block_band=None, rhythm_built=None,
                          story=None, blocks=None):
    """The record of a broken ordered ceiling, or None. See the two notes above.

    `pattern_short` is `rhythm.pattern_shortfalls()`'s list verbatim and
    `ceiling_report` is the storyboard's `rhythm.hold_ceiling` - this function
    measures nothing of its own, which is the whole point: one judge, one set of
    numbers, and a gate that reads them.

    Three causes, one gate (CF-0270, CF-0303 and CF-0310). The hold band is
    looked at first because two of the three causes are about it and they name
    a particular block; `cadence` is the whole video's and has no block to
    name. The degradation is looked for before the layout because it is the
    narrower reading of the same break - it names a block whose picture froze
    and the footage that would have ended it - and a plan where both are true
    is about that block.
    """
    over = next((s for s in pattern_short or []
                 if s.get("code") == rhythm.PATTERN_HOLD_OUTSIDE_BAND
                 and s.get("mode") == "drawn"
                 and rhythm.over_band_top(s.get("measured"),
                                          s.get("band_max"))), None)
    if over is None:
        return cadence_band_break(pattern_short, block_band, rhythm_built,
                                  story=story, blocks=blocks)
    base = {
        "kind": "pattern_ceiling_break",
        "pattern_id": over.get("pattern_id"),
        "parameter": over.get("parameter"),
        "measured": over.get("measured"),
        "band_min": over.get("band_min"),
        "band_max": over.get("band_max"),
        "outside_by": over.get("outside_by"),
        "tolerance_seconds": rhythm.HOLD_BAND_TOP_TOLERANCE_SECONDS,
        "shortfall": over,
    }
    # The trim record and the shortfall were taken from the same span, so the
    # block that is over the band is the one whose `measured` is the shortfall's
    # - no index arithmetic, no second measurement.
    refused = [t for t in hold_trims or []
               if not t.get("applied")
               and t.get("code") in POOL_HOLD_TRIM_CODES
               and t.get("measured") == over["measured"]]
    over_blocks = {t.get("block") for t in refused}
    degraded = [d for d in degraded_blocks or [] if d.get("index") in over_blocks]
    if degraded:
        # Two blocks can measure the same to the millisecond; only the ones that
        # are degraded *and* over the band are this refusal's subject, so the
        # record never names a trim whose block still moves.
        broken = {d["index"] for d in degraded}
        pool_refused = [t for t in refused if t.get("block") in broken]
        return {**base,
                "cause": CEILING_CAUSE_DEGRADATION,
                "refused_trims": pool_refused,
                "degraded_blocks": degraded,
                "breaches": [],
                "replacement": replacement_requirement(pool_refused),
                # The trims index the storyboard's blocks (trim_to_hold_band).
                "length_supply": length_supply_evidence(
                    pool_refused, (story or {}).get("blocks") or blocks)}
    # CF-0303: nothing froze, so what is over the ceiling is the layout itself.
    # `resolve_anchors.py` wrote that verdict from the real alignment one stage
    # ago and said per block why it could not cut it shorter.
    breaches = layout_ceiling_breaches(ceiling_report)
    if not breaches:
        # Nothing froze and the layout was inside the ceiling, so this hold
        # break is the one CF-0245 decided to ship long. The block-count band
        # is a different question about the same plan and is still open
        # (CF-0310) - answering "no" here would hide it behind a band that
        # happens to be checked first.
        return cadence_band_break(pattern_short, block_band, rhythm_built,
                                  story=story, blocks=blocks)
    breached = {b.get("block") for b in breaches}
    # Every trim that was asked about one of those blocks and refused - all four
    # codes, not only the two a replacement clip answers: when the boundary is
    # the rhythm, `no_next_block` and `next_block_would_leave_band` are part of
    # the same answer and the operator needs to read them.
    layout_trims = [t for t in hold_trims or []
                    if not t.get("applied") and t.get("block") in breached]
    # Usually empty - that is what makes this the layout's fault rather than
    # CF-0270's - but not necessarily: a degraded *last* block over the band is
    # one CF-0270 leaves alone (`no_next_block` has no replacement rung), and it
    # arrives here. The record carries whatever is true of the breached blocks so
    # that the lines never claim more than they measured.
    on_breaches = [d for d in degraded_blocks or [] if d.get("index") in breached]
    return {**base,
            "cause": CEILING_CAUSE_LAYOUT,
            "refused_trims": layout_trims,
            "degraded_blocks": on_breaches,
            "breaches": breaches,
            "estimate_record": ESTIMATE_RECORD_PATH,
            "replacement": replacement_requirement(layout_trims)}


def cadence_band_break(pattern_short, block_band=None, rhythm_built=None,
                       story=None, blocks=None):
    """CF-0310's cause: the block-count band, drawn, and broken. See the note.

    CF-0447 (the user, 2026-09-30): the record no longer refuses the plan. It
    rides on it as `rhythm.block_band_break` beside its price
    (`score.block_band_exceeded`, rhythm.block_band_findings(), 2 a block
    over the top, cap 10) and is the deficit of a score under N. Where the
    text below says "refuses", read "is priced" - the condition is unchanged.

    CF-0370: `block_band` is the storyboard's `rhythm.block_band_cap` and
    `rhythm_built` its `rhythm.rhythm_built`, both copied into the record so
    that the findings can say *what* the count is. On an ordered rhythm it is
    the layout's segments; on `even` it is the shots the resolver chained over
    them, which since CF-0370 are budgeted under a drawn top - and a break on
    `even` is then either a layout with more segments than the top (the
    writing's) or a storyboard resolved before the budget existed (the
    resolver's, re-run it). The old sentence - "the number of resolved
    anchors, no trim moves it" - was said of both and was wrong of `even`:
    `you-can-see-everything` had 10 anchors and 22 blocks.

    Reads `rhythm.pattern_shortfalls()` and measures nothing, like the other
    two. `mode == "drawn"` is the whole condition - there is no second
    condition to find, because no stage after the storyboard can change the
    number of blocks, so a drawn band broken here is broken finally. Either
    shape of the parameter counts (CF-0310's `BLOCK_COUNT_PARAMETER_FORMS`):
    the band is the same claim whether the root states it as a count or as a
    rate, and this gate should not have to be re-opened on the day it moves.

    The condition itself is `rhythm.cadence_band_refuses()` and not a copy of
    it here, because the Content Researcher's pre-TTS pass has to reach the
    same answer one stage and one wav earlier (CF-0277) - a rule that lives in
    this file can only be applied in this file.

    `emergent` is not this gate's business and never was - CF-0039's rule,
    kept by CF-0270 and CF-0303: an envelope that only records what was
    observed does not refuse a video, it declines to certify one.

    The one asymmetry, and it is CF-0310's finding applied to itself: a band
    stated as a **count** refuses over its ceiling and not under its floor.
    More blocks than the pattern allows cannot be an artefact of length - a
    longer video needs *more* blocks to break the ceiling, so the break is
    about the cutting. Fewer blocks than the floor is the defect this task was
    filed about: `moment-breakdown`'s own file says its floor of 6 is "where a
    35-60 second video still has enough picture changes", so a count floor is a
    length requirement written in blocks, and refusing a short video on it
    would repeat CF-0310 one pattern over. Measured on disk: three real
    layouts are under a drawn count floor and none is over a ceiling -
    `2026-09-09T2031Z/everyday-sorcery-2` (contrast, 3), `2026-09-03T2037Z/
    raygun-sneak-peek` (list, 6) and `2026-08-31T2155Z/wren-hollow-lockhart`'s
    `storyboard_sbs.json` (contrast, 6), the last of which is the one piece of
    material in the corpus the user called better than its batch.

    A band stated as a **rate** has the length divided out of it, so both ends
    refuse. That is the shape CF-0310 asks the factory root for, and this is
    where the ask pays: the floor becomes a statement about cutting the day
    the band stops being a count.
    """
    short = next((s for s in pattern_short or []
                  if rhythm.cadence_band_refuses(s)), None)
    if short is None:
        return None
    return cadence_record(short, block_band, rhythm_built, story=story, blocks=blocks)


def pace_floor_record(pattern_short, block_band=None, rhythm_built=None,
                      story=None, blocks=None):
    """CF-0433: the cadence record of a pace under its floor, or None.

    Since CF-0433 that pace is not a refusal (`score.pace_below_floor`,
    rhythm.pace_findings()), but what CF-0310 and CF-0428 measured about it
    is still the answer to "can the writer's anchors buy the points back":
    the plan carries this record as `rhythm.pace_below_floor`, with
    `supply` and `fixable_by_anchors` exactly as the refusal had them."""
    short = next((s for s in pattern_short or []
                  if rhythm.pace_floor_deficit(s) is not None), None)
    if short is None:
        return None
    return cadence_record(short, block_band, rhythm_built, story=story, blocks=blocks)


def cadence_record(short, block_band=None, rhythm_built=None, story=None, blocks=None):
    """The `pattern_ceiling_break` record of the cadence cause for one
    block-count shortfall - cadence_band_break()'s refusal and
    pace_floor_record()'s price share it."""
    return {
        "kind": "pattern_ceiling_break",
        "cause": CEILING_CAUSE_CADENCE,
        "pattern_id": short.get("pattern_id"),
        "parameter": short.get("parameter"),
        "measured": short.get("measured"),
        "band_min": short.get("band_min"),
        "band_max": short.get("band_max"),
        "outside_by": short.get("outside_by"),
        # No grid and no tolerance: a count has no frames to round to, and a
        # rate is a count divided by a span. `None` rather than 0 so a reader
        # can tell "no tolerance applies" from "a tolerance of zero applied".
        "tolerance_seconds": None,
        "shortfall": short,
        # The three keys the other two causes fill, empty and present: every
        # reader of `plan.pattern-ceiling.json` and every line writer below
        # takes the same record apart, whichever cause wrote it.
        "refused_trims": [],
        "degraded_blocks": [],
        "breaches": [],
        "replacement": [],
        "estimate_record": BLOCK_BAND_RECORD_PATH,
        "rhythm_built": rhythm_built,
        "block_band_cap": block_band,
        # CF-0428: what, if anything, an edit of `visual_anchors` can do
        # about it - see cadence_supply().
        **cadence_supply(short, story, blocks),
    }


# CF-0428: why the pace is what it is, as a code the writer's loop can act on.
SUPPLY_POOL_TOO_THIN = "pool_too_thin"        # no anchor edit reaches the floor
SUPPLY_ANCHORS_UNFILLED = "anchors_unfilled"  # anchors that left no block
SUPPLY_SIDE_RUNS = "same_side_runs"           # alternate: a block per crossing
SUPPLY_TOO_FEW_ANCHORS = "too_few_anchors"    # every anchor filled, still short
SUPPLY_UNMEASURED = "unmeasured"              # storyboard predates CF-0428

# How many of the pool's unused shots the finding names by description.
SUPPLY_UNUSED_NAMED = 8


def cadence_supply(short, story=None, blocks=None):
    """CF-0428: whether a pace under the ordered floor is the anchors' to fix.

    `{"supply": ..., "fixable_by_anchors": True | False | None}`, or `{}` when
    the break is not a rate under its floor (a count, or a pace over a drawn
    top - neither is what the writer's loop is sent to add anchors for).

    The Content Researcher's loop (CF-0411) read "under the floor" as "ADD
    anchors" and nothing more. `example-film/2026-09-28T1126Z` showed two ways
    that is false, both readable off the storyboard the plan was built on:

      * vanguards, `even`: 11 -> 18 anchors, 7 blocks both rounds, 9.64
        blocks/min both rounds. A block is a picture the resolver handed out,
        at one sample, one use a distinct shot - and the pool had 8 shots
        passing every gate a phrase cannot move (burned text, cached
        usability, retired, the cut clip), 7 of them already on screen. 16
        of the 18 phrases found every free shot refused and added no block;
        their seconds were carried into a neighbour (CF-0124). The floor
        wanted 12 blocks over 43.6 s; the pool's most is 9. No anchor edit
        reaches it (`pool_too_thin`, `fixable_by_anchors: false`).
      * backrooms, `alternate` with declared sides: 11 anchors, 6 blocks,
        because on that path a block is one crossing of the script's axis
        (`rhythm._plan_alternate_declared`) and the sides ran a|bbb|aa|b|aaa|b.
        An anchor added on its neighbour's side adds no block; the lever is
        the anchors' `side`, not their number (`same_side_runs`).

    `pool_capacity` is `resolve_anchors.pool_capacity()`'s record; without it
    (a storyboard older than CF-0428) the bound is unknown and the answer is
    `None` - not `True`. Measures nothing the storyboard and the plan's own
    blocks do not already say.
    """
    if (short.get("parameter") != "block_rate_per_minute"
            or not isinstance(short.get("measured"), (int, float))
            or not isinstance(short.get("band_min"), (int, float))
            or short["measured"] >= short["band_min"]):
        return {}
    story = story or {}
    srh = story.get("rhythm") or {}
    c = rhythm.cadence(blocks or [])
    n = c["block_count"]
    span = round(sum(c["durations"]), 3)
    need = (int(-(-(short["band_min"] * span / 60.0 - 1e-9) // 1))
            if span else None)
    cap = story.get("pool_capacity")
    blocks_max = (cap or {}).get("blocks_max")
    unfilled = [s.get("phrase") for s in story.get("anchor_supply") or []
                if s.get("block_count") == 0]
    anchor_sides = srh.get("anchor_sides")
    runs = None
    if (srh.get("rhythm_built") == "alternate" and anchor_sides
            and rhythm.declared_sides_usable(anchor_sides)):
        runs = len(list(rhythm.side_runs(anchor_sides)))
    supply = {
        "blocks": n,
        "span_seconds": span,
        "blocks_needed": need,
        "anchor_count": srh.get("anchor_count"),
        "segments": srh.get("planned_block_count"),
        "anchors_without_block": unfilled,
        "side_runs": runs,
        "pool_capacity": ({k: cap.get(k) for k in ("shots", "eligible", "used",
                                                   "refused", "blocks_max",
                                                   "emergency_repeats",
                                                   "unused_total")}
                          if cap else None),
        "max_rate_per_minute": (round(blocks_max / span * 60.0, 2)
                                if isinstance(blocks_max, int) and span else None),
        "unused_shots": [{"shot": u.get("shot"), "seconds": u.get("seconds"),
                          "description": u.get("description")}
                         for u in ((cap or {}).get("unused") or [])[:SUPPLY_UNUSED_NAMED]],
    }
    if need is None or not isinstance(blocks_max, int):
        supply["code"] = SUPPLY_UNMEASURED
        return {"supply": supply, "fixable_by_anchors": None}
    if blocks_max < need:
        supply["code"] = SUPPLY_POOL_TOO_THIN
        return {"supply": supply, "fixable_by_anchors": False}
    supply["code"] = (SUPPLY_ANCHORS_UNFILLED if unfilled else
                      SUPPLY_SIDE_RUNS if runs is not None
                      and (srh.get("anchor_count") or 0) > runs else
                      SUPPLY_TOO_FEW_ANCHORS)
    return {"supply": supply, "fixable_by_anchors": True}


def supply_lines(rec):
    """CF-0428: the remedy half of a pace-floor refusal, in the numbers of
    `cadence_supply()`. Replaces the old closing sentence ("more or fewer
    anchors ... then a re-run from the Content Researcher"), which was said of
    every break and was false of both breaks CF-0428 was filed on."""
    sp = rec.get("supply") or {}
    code = sp.get("code")
    cap = sp.get("pool_capacity") or {}
    n, need, span = sp.get("blocks"), sp.get("blocks_needed"), sp.get("span_seconds")
    head = (f"this plan has {n} block(s) over {span}s and the floor wants at "
            f"least {need}")
    if code == SUPPLY_POOL_TOO_THIN:
        ref = cap.get("refused") or {}
        return [
            f"{head}; this pool can put at most {cap.get('blocks_max')} on screen "
            f"({cap.get('eligible')} of its {cap.get('shots')} shots pass every "
            f"gate a phrase cannot move - refused: burned text "
            f"{ref.get('burned_text_or_off_entity')}, cached usability "
            f"{ref.get('usability_cache')}, retired {ref.get('retired')}, cut "
            f"clip {ref.get('cut_clip')}; {cap.get('used')} already on screen, "
            f"plus {cap.get('emergency_repeats')} emergency repeat), i.e. "
            f"{sp.get('max_rate_per_minute')} blocks/min at best",
            "NOT FIXABLE BY ANCHORS (fixable_by_anchors: false): at one sample, "
            "one use a block is a distinct shot, and an anchor no free shot "
            "answers adds no block - its seconds are carried into a neighbour "
            "(CF-0124). Widen the pool (the supplement step, another source "
            "for this topic) or assign a pattern whose pace floor "
            f"{sp.get('max_rate_per_minute')} blocks/min can meet",
        ]
    if code == SUPPLY_UNMEASURED:
        return [f"{head}; the storyboard carries no pool_capacity (resolved "
                f"before CF-0428), so whether an anchor edit can reach it is "
                f"unknown - re-run from the resolver to measure it"]
    lines = [f"{head}; the pool can put up to {cap.get('blocks_max')} on screen "
             f"({cap.get('unused_total')} usable shot(s) not yet used), so the "
             f"anchors can reach it (fixable_by_anchors: true)"]
    unfilled = sp.get("anchors_without_block") or []
    if unfilled:
        lines.append(
            f"{len(unfilled)} anchor(s) left no block - no free shot of the "
            f"pool answered the phrase, and an anchor that resolves to nothing "
            f"adds nothing to the pace: "
            + "; ".join(f"«{p}»" for p in unfilled[:6])
            + (" ..." if len(unfilled) > 6 else "")
            + ". Rewrite those phrases onto shots the pool still has")
    runs = sp.get("side_runs")
    if runs is not None and (sp.get("anchor_count") or 0) > runs:
        lines.append(
            f"on `alternate` with declared sides a block is one crossing of "
            f"the axis: {sp.get('anchor_count')} anchors in {runs} same-side "
            f"run(s) are {runs} block(s). An anchor added on its neighbour's "
            f"side adds no block - the anchors' `side` has to change at least "
            f"{max(0, (need or 0) - 1)} time(s), or the sides be dropped")
    elif not unfilled:
        lines.append(
            f"every anchor filled; about {max(0, (need or 0) - (n or 0))} more "
            f"anchor(s), each on a shot not yet used, are what raises the pace")
    named = sp.get("unused_shots") or []
    if named:
        lines.append("unused usable shots: " + "; ".join(
            f"{u.get('shot')} ({u.get('seconds')}s) {str(u.get('description') or '')[:90]}"
            for u in named))
    return lines


def pattern_ceiling_lines(rec):
    """The gate's findings - the `reason` the funnel prints, one line each."""
    if rec.get("cause") == CEILING_CAUSE_CADENCE:
        unmeasured = (rec.get("supply") or {}).get("code") == SUPPLY_UNMEASURED
        return cadence_band_lines(rec) + (supply_lines(rec) if unmeasured else [])
    if rec.get("cause") == CEILING_CAUSE_LAYOUT:
        return layout_ceiling_lines(rec)
    blocks = sorted({t.get("block") for t in rec["refused_trims"]}, key=str)
    lines = [
        f"block {', '.join(str(b) for b in blocks)} runs {rec['measured']}s "
        f"against {rec['pattern_id']}'s drawn hold band "
        f"{rec['band_min']}-{rec['band_max']}s - over the top by "
        f"{rec['outside_by']}s, and it is a degraded block, so that is one "
        f"frame held for {rec['measured']}s",
    ]
    for d in rec["degraded_blocks"]:
        lines.append(f"block {d.get('index')} was degraded "
                     f"{d.get('from')} -> {d.get('to')}: {d.get('reason')}")
    for t in rec["refused_trims"]:
        lines.append(f"block {t.get('block')} could not be trimmed to the band "
                     f"({t.get('code')}): {t.get('note')}")
    for r in rec["replacement"]:
        if r.get("short_by") is not None:
            lines.append(
                f"a replacement clip for block {r['next_block']} would have to run "
                f"{r['needed']}s against the {r['has']}s this one has "
                f"({r['short_by']}s short)")
    # CF-0278: what the pool offered those blocks, from the record - an old
    # deficit without the key says nothing rather than citing the sort.
    for ev in rec.get("length_supply") or []:
        lines.append(length_supply_line(ev))
    return lines


def layout_ceiling_lines(rec):
    """CF-0303's half of the findings: the blocks, their seconds, the band, and
    the one sentence that sends the next reader to the right stage.

    Every number is copied from `rhythm.ceiling_report()` and CF-0245's trim
    records - this writes sentences, it does not measure.
    """
    breaches = sorted(rec["breaches"], key=lambda b: (b.get("block") is None,
                                                      b.get("block")))
    blocks = ", ".join(str(b.get("block")) for b in breaches)
    seconds = ", ".join(f"{b.get('measured')}s" for b in breaches)
    tail = ("and none of them was degraded: the pictures move, it is the block "
            "layout itself that is over the ceiling"
            if not rec["degraded_blocks"] else
            "and the block layout itself is over the ceiling, before any clip "
            "was cut")
    lines = [
        f"block {blocks} run {seconds} against {rec['pattern_id']}'s drawn hold "
        f"band {rec['band_min']}-{rec['band_max']}s - the longest is over the top "
        f"by {rec['outside_by']}s, {tail}",
        f"the layout was cut against this band before a single clip "
        f"(rhythm.ceiling_report, CF-0276) and these blocks survived it, so no "
        f"montage brings them under {rec['band_max']}s",
    ]
    for d in rec["degraded_blocks"]:
        lines.append(f"block {d.get('index')} was also degraded "
                     f"{d.get('from')} -> {d.get('to')}: {d.get('reason')}")
    for b in breaches:
        lines.append(
            f"block {b.get('block')} is laid out at {b.get('measured')}s, over by "
            f"{b.get('outside_by')}s ({b.get('code')}, role {b.get('role')!r}): "
            f"{b.get('note')}")
    for t in rec["refused_trims"]:
        lines.append(f"block {t.get('block')} could not be trimmed to the band "
                     f"({t.get('code')}): {t.get('note')}")
    lines.append(
        f"the Content Researcher passed this script on an estimate of the "
        f"speech, not on the wav: {rec.get('estimate_record')} holds that reading "
        f"(check_anchor_cadence.py / plan_blocks.py, CF-0277 - word k at k/rate, "
        f"no alignment exists before TTS is paid for). The layout above is the "
        f"same rule on the real alignment, which is why a script that fit the "
        f"band before the render does not fit it after - the fix is in the "
        f"writing (fewer spoken words between those anchors, or another anchor "
        f"inside the stretch), or in the margin that pass holds under the band's "
        f"top")
    return lines


def cadence_band_lines(rec):
    """CF-0310's half of the findings.

    Short on purpose: there is one number, one band and one stage that can
    change it. No block is named because none is at fault - the count is the
    video's, not a block's.

    CF-0314: when the band is `floor_drawn` the first line says which end is
    an order and which is not. The operator reading this refusal is being told
    his video is too slow, and "outside the drawn band 15.39-47.88" invites
    him to read the ceiling as an order too - it is not one, and cutting
    faster than the seven measured videos is explicitly allowed (the user's
    decision of 2026-09-22). Only the floor can ever bring a plan here, so the
    line names the pace, the floor, and what the floor is.
    """
    rate = rec.get("parameter") == "block_rate_per_minute"
    unit = " blocks/min" if rate else " blocks"
    under = rec["measured"] < rec["band_min"]
    floor_drawn = (rec.get("shortfall") or {}).get("mode") == \
        rhythm.BAND_MODE_FLOOR_DRAWN
    side = (f"under the floor by {rec['outside_by']}" if under
            else f"over the top by {rec['outside_by']}")
    what = ("the video is cut at" if rate else "the video is laid out in")
    lines = [
        (f"{what} {rec['measured']}{unit} against {rec['pattern_id']}'s "
         f"ordered floor of {rec['band_min']}{unit} - {side}. That floor is "
         f"an order (the user's decision of 2026-09-22, CF-0314); the ceiling "
         f"{rec['band_max']}{unit} above it is an observation of the seven "
         f"measured videos and refuses nothing - a faster cut is not a defect"
         if floor_drawn else
         f"{what} {rec['measured']}{unit} against {rec['pattern_id']}'s drawn "
         f"band {rec['band_min']}-{rec['band_max']}{unit} - {side}"),
        (f"that pace is the block count over the span the blocks themselves "
         f"cover, and both halves were fixed in the storyboard, before a clip "
         f"was cut"
         if rate else
         f"the block count is the number of segments the rhythm laid the "
         f"anchors out in, and it was fixed in the storyboard, before a clip "
         f"was cut")
        + ": no trim moves it and no replacement clip changes it, so there is "
          "no rung of the ladder left to spend here",
    ]
    even = (not rate) and rec.get("rhythm_built") == "even"
    if even:
        lines[1] = even_band_line(rec)
    if under and floor_drawn:
        lines.append(
            f"below that floor the picture stands still long enough that the "
            f"video reads as a slide show, which is what the floor was drawn "
            f"to stop: {rec['pattern_id']} is its pace as much as it is its "
            f"rhythm (CF-0039), and this plan is refused before the render "
            f"rather than shipped with pattern_delivered: null (DoD 1.4.4 "
            f"item 3, the case CF-0314 was filed on: lf-2026-09-09-006, "
            f"3 blocks over 40.4s)")
    elif under:
        lines.append(
            f"a video with too few blocks for its pattern is the pattern's "
            f"defect, not the montage's - {rec['pattern_id']} is that band as "
            f"much as it is its rhythm (CF-0039), and a plan signed "
            f"pattern_delivered: null is the record saying so")
    if (rec.get("supply") or {}).get("code") not in (None, SUPPLY_UNMEASURED):
        return lines + supply_lines(rec)
    if even and not rec.get("block_band_cap"):
        lines.append(
            "the fix is not in the writing: re-run this video from the resolver "
            "(resolve_anchors.py), which since CF-0370 budgets the chain under "
            "the band's top and holds a frame where the budget ends")
        return lines
    if even:
        lines.append(
            f"the Content Researcher reads this band in pictures before the TTS "
            f"at {PICTURE_BAND_RECORD_PATH} (check_block_capacity.py, CF-0365); "
            f"the remedy there is the same as here - fewer anchors for this "
            f"pattern, or a pattern whose band the script's shape can fill - and "
            f"then a re-run from the Content Researcher")
        return lines
    lines.append(
        f"this band belongs to the Content Researcher's pre-TTS pass and its "
        f"reading goes in {rec.get('estimate_record')} (plan_blocks.py, "
        f"CF-0277, which already builds this layout with the Editor's own "
        f"code). An absent record there is the whole story of how this plan "
        f"got here: nobody measured this band before the wav was paid for. "
        f"The fix is in the writing - more or fewer anchors for this pattern, "
        f"or a pattern whose band this script's shape can fill - and then a "
        f"re-run from the Content Researcher, not from the resolver")
    return lines


def even_band_line(rec):
    """CF-0370: the second finding of a count break on `even`, in numbers.

    Under `even` the count is not the layout's: a segment is cut into as many
    shots as the pool takes to cover it, each shot its own block. Since
    CF-0370 the resolver budgets that chain under a drawn top and holds a
    frame where the budget ends, so a break that still reaches here has one
    of three causes, and each is said with the numbers
    `rhythm.block_band_cap` recorded:

      * no record - a storyboard resolved before the budget existed: the
        chain ran unbudgeted, and re-resolving is the remedy;
      * `layout_over_top_by` > 0 - more segments than the top, one picture
        each: the count is the writing's, no budget moves it;
      * otherwise - the segments the pattern's hold band would not let hold
        one frame (a stretch carried in from an unfilled anchor, CF-0124) or a
        hold that failed to be made took the pictures past the top.
    """
    cap = rec.get("block_band_cap") or {}
    measured, top = rec.get("measured"), rec.get("band_max")
    if not cap:
        return (f"on `even` the block count is not the number of anchors: it is "
                f"the {measured} shots the resolver chained over the layout's "
                f"segments, each shot its own block - and this storyboard has no "
                f"`rhythm.block_band_cap`, so it was resolved before CF-0370 "
                f"budgeted that chain under the band's top")
    segs = cap.get("segments")
    capped = cap.get("capped_segments") or []
    held = cap.get("held_frames", 0)
    if cap.get("layout_over_top_by"):
        return (f"on `even` the resolver budgeted the chain under the top of "
                f"{top} ({len(capped)} segment(s) capped, {held} holding a "
                f"frame), but the layout itself has {segs} segments - one "
                f"picture per segment is already {cap['layout_over_top_by']} "
                f"over the top, so no budget, trim or replacement clip moves it")
    forced = [c["segment"] for c in capped
              if c.get("budget", 0) > 1 and c.get("shots", 0) > 1]
    failed = cap.get("hold_failed") or []
    return (f"on `even` the resolver budgeted the chain under the top of {top} "
            f"over {segs} segments ({len(capped)} capped, {held} holding a "
            f"frame) and still cut {measured} blocks: "
            + (f"the hold could not be made on segment(s) {failed} (frame grab "
               f"failed); " if failed else "")
            + (f"segment(s) {forced} needed more than one picture to stay "
               f"inside the pattern's hold band (a stretch carried in from an "
               f"unfilled anchor, CF-0124) - " if forced else "")
            + "see rhythm.block_band_cap and the RHYTHM notes in the storyboard")


PATTERN_CEILING_NOTES = (
    "DoD 1.4.4 item 3: a ready video delivers the pattern it was assigned, and a "
    "topic that cannot is refused with a code before the render - not rendered and "
    "recorded with pattern_delivered: null.",
    "The remedy order is replacement then refusal. The replacement rung is "
    "resolve_anchors.py's long-enough-first pool sort and it has already run: the "
    "storyboard's clip is the longest the pool offered for that anchor. Widen the "
    "pool (another source video for this topic) or assign a pattern whose hold band "
    "this montage can hold, and re-run from the resolver.",
)

# CF-0303: the same first sentence - it is the same DoD item and the same
# refusal - and a different second one, because no clip in any pool answers a
# block that is too long before the first cut.
LAYOUT_CEILING_NOTES = (
    PATTERN_CEILING_NOTES[0],
    "Two remedies, and the record says which block takes which. Where "
    "`replacement` names a next block with numbers, a longer clip for that block "
    "would let CF-0245's trim move the boundary and end the breach - the pool's "
    "rung, and resolve_anchors.py's long-enough-first sort has already spent it. "
    "Where the trim refused with no_next_block or next_block_has_no_clip, no "
    "footage in any pool answers: the stretch between those two anchors is longer "
    "than the ceiling and its edges are the rhythm, so it is the writing that has "
    "to change - fewer spoken words there, another anchor inside the stretch, or a "
    "pattern whose hold band this script can hold. Then re-run from the Content "
    "Researcher, not from the resolver.",
    "The pre-render pass that let this through measured an estimate of the "
    "speech (03-content-researcher.json#scripts[].anchor_cadence.layout, "
    "CF-0277). Its numbers and the ones above are the same rule on different "
    "inputs; the margin it holds under the band's top is what has to cover the "
    "difference.",
)


# CF-0310: the same first sentence - the same DoD item, the same refusal - and
# one remedy instead of two, because only one stage can answer.
CADENCE_BAND_NOTES = (
    PATTERN_CEILING_NOTES[0],
    "One remedy, and it is upstream of this repo. The block count is decided in "
    "the storyboard before the first cut - on an ordered rhythm it is the "
    "layout's segments, on `even` the shots the resolver chains over them, "
    "budgeted under a drawn top and held where the budget ends since CF-0370 - "
    "and nothing in the montage - no trim, no replacement clip, no re-render - "
    "changes it. Either the script gets the anchors this pattern's band asks "
    "for, or the topic is assigned a pattern whose band the script's shape can "
    "fill. Then re-run from the Content Researcher.",
    "The same band can be read before TTS is paid for: plan_blocks.py "
    "(CF-0277) already builds this layout with the Editor's own code, and "
    "rhythm.block_count_parameter() is the one place that says which shape of "
    "the band a pattern file carries. A topic refused here should have been "
    "refused there, one stage and one wav earlier.",
)


# CF-0428: a pace the pool cannot reach. The anchors are not the lever, so
# the writer's loop must not be sent round again to add them.
POOL_BOUND_NOTES = (
    PATTERN_CEILING_NOTES[0],
    "Not the anchors' to fix. The pace is the number of distinct pictures the "
    "resolver handed out over the voice, and the pool holds fewer pictures that "
    "pass the phrase-independent gates than the floor needs "
    "(storyboard.pool_capacity, resolve_anchors.pool_capacity()). An anchor no "
    "free shot answers adds no block. The remedy is more footage for the topic "
    "(the supplement step) or a pattern whose floor this pool can meet - then a "
    "re-run from the resolver; an anchor-edit round spent here changes nothing.",
)


def ceiling_notes(rec):
    """The policy paragraphs for the cause this refusal has."""
    if rec.get("fixable_by_anchors") is False:
        return POOL_BOUND_NOTES
    if rec.get("cause") == CEILING_CAUSE_CADENCE:
        return CADENCE_BAND_NOTES
    return (LAYOUT_CEILING_NOTES if rec.get("cause") == CEILING_CAUSE_LAYOUT
            else PATTERN_CEILING_NOTES)


def write_pattern_ceiling_deficit(output, rec):
    """`plan.pattern-ceiling.json`, beside where the plan would have been - the
    same move as CF-0118's two-source deficit and CF-0137's assetless rung."""
    p = Path(output)
    path = p.with_name(f"{p.stem}{PATTERN_CEILING_DEFICIT_SUFFIX}")
    try:
        json.dump({"pattern_ceiling": rec}, open(path, "w"), indent=2)
    except OSError as e:
        return f"<not written: {e}>"
    return str(path)


def tool_timeout_info(tool, path, ceiling):
    """CF-0077: what inspect_asset() hands back when a gate tool ran past its
    ceiling on `path`. The shape of a failed qc_asset.py verdict (`usable`
    False, a `failures` line naming the tool, the asset and the ceiling,
    `failed` keyed TOOL_TIMEOUT_KEY) over neutral framing, so the block is
    built like any other and refused on the ordinary ASSETS REJECTED path -
    the caller substitutes a candidate exactly as it does for a dark frame.
    Never a hang, never a traceback out of the whole plan. The framing
    numbers are placeholders: a plan with a rejected asset is never written."""
    print(f"[build_render_plan] {tool} exceeded the ceiling of {ceiling} s on "
          f"{path} - killed, treated as a gate failure", file=sys.stderr)
    return {
        "roi": {"x": 0, "y": 0, "width": 1, "height": 1},
        "source_size": {"width": 1, "height": 1},
        "crop": {"x": 0, "y": 0, "width": 1, "height": 1},
        "roi_source": "none", "roi_coverage": 0.0, "zoom": 1.0,
        TOOL_TIMEOUT_KEY: {"tool": tool, "ceiling_seconds": ceiling},
        "qc": {
            "usable": False,
            "failures": [
                f"{tool}: no verdict within the {ceiling} s ceiling on {path} - "
                f"hung, not slow (raise the ceiling in common.py only if the tool "
                f"is honestly this long)"],
            "failed": [TOOL_TIMEOUT_KEY],
            "relaxations": [],
        },
    }


# CF-0483: a probe that came back without a frame - the clip is gone,
# empty, unreadable, or shorter than the point asked for. Keyed like
# TOOL_TIMEOUT_KEY so the steps that would read the (absent) probe skip it.
NO_FRAME_KEY = "no_probe_frame"


def no_frame_info(source, at, reason):
    """CF-0483: the verdict of a clip probe_frame() could not lift a frame
    out of. Same shape and same consequence as tool_timeout_info(): the
    asset is unusable with one failure line naming the clip, the offset and
    why, and the plan refuses it on the ordinary ASSETS REJECTED path, where
    the caller substitutes another candidate. Not a traceback out of the
    whole plan - one bad clip used to take every block of the video down."""
    print(f"[build_render_plan] no probe frame out of {source} at {at:.3f} s "
          f"({reason}) - treated as a gate failure", file=sys.stderr)
    return {
        "roi": {"x": 0, "y": 0, "width": 1, "height": 1},
        "source_size": {"width": 1, "height": 1},
        "crop": {"x": 0, "y": 0, "width": 1, "height": 1},
        "roi_source": "none", "roi_coverage": 0.0, "zoom": 1.0,
        NO_FRAME_KEY: {"at": round(float(at), 3), "reason": reason},
        "qc": {
            "usable": False,
            "failures": [
                f"no probe frame: {source} gave no frame at {at:.3f} s ({reason}) - "
                f"the clip is missing, empty or shorter than the probe point"],
            "failed": [NO_FRAME_KEY],
            "relaxations": [],
        },
    }


def probe_missing(info):
    """True when `info` stands for a probe frame that is not on disk - a
    hung tool (CF-0077) or no frame at all (CF-0483)."""
    return bool(info.get(TOOL_TIMEOUT_KEY) or info.get(NO_FRAME_KEY))


def probe_at_within(at, seconds):
    """CF-0483: `at`, pulled back inside a clip of `seconds` (when known and
    positive) so the seek never lands past the last frame."""
    at = max(0.0, float(at))
    if seconds and float(seconds) > 0:
        at = min(at, max(0.0, float(seconds) - LAST_FRAME_EPSILON))
    return at


def probe_frame(source, at, dest, seconds=None):
    """One frame out of `source` at `at` seconds for the asset gate. Returns
    None when the frame is on disk, or the tool_timeout_info() the caller
    uses in place of inspect_asset() when ffmpeg hung (CF-0077) - the clip
    is then failed by the probe the same way a dark frame fails it.

    CF-0483: `seconds` (the clip's length, when the caller knows it) keeps
    the seek inside the clip. An ffmpeg error, or a pass that wrote no frame
    (a seek past the end of a clip shorter than `at`, a clip that is empty,
    a clip deleted under the plan by a concurrent resolve), returns
    no_frame_info() - the clip is refused with a record, never a
    CalledProcessError out of the plan."""
    at = probe_at_within(at, seconds)
    Path(dest).unlink(missing_ok=True)
    try:
        runlog.run_child(
            [FFMPEG, "-y", "-nostdin", "-v", "error", "-ss", str(round(at, 3)),
             "-i", source, "-frames:v", "1", dest], tool="ffmpeg",
            check=True, timeout=PROBE_FRAME_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return tool_timeout_info("ffmpeg (probe frame)", source, PROBE_FRAME_TIMEOUT_SECONDS)
    except subprocess.CalledProcessError as e:
        if not Path(source).exists():
            reason = "clip not on disk"
        elif Path(source).stat().st_size == 0:
            reason = "clip is empty"
        else:
            reason = f"ffmpeg exit {e.returncode}"
        return no_frame_info(source, at, reason)
    if not Path(dest).exists() or Path(dest).stat().st_size == 0:
        return no_frame_info(source, at, "ffmpeg wrote no frame")
    return None


# CF-0549: a `sequence` block (CF-0120 swing, CF-0480/CF-0536 stretch split)
# that QC failed `frozen` came down the CF-0031 rung by renaming its first cut
# `still` - with the cut's .mp4 still as its asset, so qc_asset.py and
# smart_crop.py were handed a video as a picture ("cannot read image", delver
# 1244Z block 3) and the rebuild died. The rung is now taken the way
# qc_render.py found the fault: per cut. QC sweeps a sequence cut by cut
# (`probe_targets`, CF-0120) and names where the picture stuck; only the cut
# that stuck stops moving - "18 motion blocks and 1 still is the correct
# outcome of a single frozen block" (CF-0031) holds inside a block too, and
# the other cuts were never at fault. The still is a real frame lifted out of
# that cut's own clip by the hold rule (`lift_held_frame`). Only when nothing
# says which cut stuck (no ledger, a hand-run flag) does the whole block hold
# its first picture, as before - lifted by the same rule.
FROZEN_DETAIL_RX = re.compile(r"\bblock (\d+) \(still for [\d.]+s from ([\d.]+)s")
FROZEN_CUT_TASK = "CF-0549"
# A cut's span as qc_render.py walks it, and the tolerance of its rounded
# `still_run_at` (two decimals) against a span's start.
FROZEN_AT_SLACK = 0.011


def _sequence_cut_at(block, at):
    """The index of the clip cut of the plan `block` (a sequence) on screen at
    composition second `at`, walked the way qc_render.probe_targets() walked
    it before CF-0893 (from `block.start`) - only a ledger without `cut` is
    read here, and the QC that wrote it (pre-CF-0549) walked the cuts so;
    None when the block is not a sequence or no clip cut covers `at`."""
    asset = (block or {}).get("asset") or {}
    if asset.get("kind") != "sequence":
        return None
    cuts = asset.get("cuts") or []
    t = float(block.get("start") or 0.0)
    for k, cut in enumerate(cuts):
        end = (float(block.get("end") or t) if k == len(cuts) - 1
               else t + float(cut.get("seconds") or 0.0))
        if cut.get("kind") == "clip" and t - FROZEN_AT_SLACK <= at < end:
            return k
        t = end
    return None


def frozen_cuts(output, indices):
    """CF-0549: {block index: sorted cut indices} for the `indices` the last
    render's QC named frozen inside a sequence block - read from the attempt
    ledger beside the plan (`qc_frozen`, qc_render.py since CF-0549; a ledger
    from before it has only the `detail` line, whose "from <t>s" is mapped
    onto the plan QC judged - the one at `output`, read before this build
    overwrites it). A block with no cut named is absent: the caller then
    degrades it whole. Never raises."""
    found = attempts.batch_context(output)
    if not found or not indices:
        return {}
    try:
        ledger = json.loads(attempts.ledger_path(*found).read_text())
        done = attempts.renders(ledger)
    except (OSError, ValueError, TypeError, KeyError):
        return {}
    if not done or done[-1].get("result") != attempts.RESULT_QC_FAILED:
        return {}
    last = done[-1]
    records = [r for r in last.get("qc_frozen") or [] if isinstance(r, dict)]
    if not records:
        records = [{"index": int(m.group(1)), "still_run_at": float(m.group(2))}
                   for m in FROZEN_DETAIL_RX.finditer(str(last.get("detail") or ""))]
    plan_before = None
    out = {}
    for r in records:
        try:
            i = int(r.get("index"))
        except (TypeError, ValueError):
            continue
        if i not in indices:
            continue
        k = r.get("cut")
        if not isinstance(k, int) and isinstance(r.get("still_run_at"), (int, float)):
            if plan_before is None:
                try:
                    plan_before = json.loads(Path(output).read_text())
                except (OSError, ValueError):
                    plan_before = {}
            blocks = plan_before.get("blocks") or []
            if 0 <= i < len(blocks):
                k = _sequence_cut_at(blocks[i], float(r["still_run_at"]))
        if isinstance(k, int) and k >= 0:
            out.setdefault(i, set()).add(k)
    return {i: sorted(ks) for i, ks in out.items()}


def lift_held_frame(cut, dest):
    """CF-0549: one frame of the sequence cut `cut`'s clip into `dest`, picked
    by the rule a held frame is picked by in resolve_anchors.hold_frame() -
    the shot's sharpest-calm moment from its sharpness record when the cut
    carries one inside its clip (CF-0452/CF-0536, shot_score.held_moment),
    else the clip's calmest moment (CF-0536, held_motion.calmest_moment),
    else its middle. Returns (failure, record): `failure` is None with the
    frame on disk, else probe_frame()'s verdict (the block is then refused
    on the ordinary ASSETS REJECTED path, never handed a video as a
    picture); `record` says where and by which rule."""
    clip = cut["asset"]
    try:
        clip_seconds = media_duration(clip)
    except Exception:  # noqa: BLE001 - an unreadable clip: the probe says so
        clip_seconds = None
    span = clip_seconds or float(cut.get("seconds") or 0.0)
    at = rule = None
    best = shot_score.held_moment(cut)
    cut_at = cut.get("cut_at")
    if best is not None and isinstance(cut_at, (int, float)):
        t = float(best[0]) - float(cut_at)
        if 0.0 <= t < span - 0.05:
            at, rule = t, "sharpest_calm"
    if at is None:
        try:
            calm = held_motion.calmest_moment(clip)
        except Exception:  # noqa: BLE001 - no calm reading: the middle
            calm = None
        if calm is not None:
            at, rule = float(calm), "calmest"
    if at is None:
        at, rule = max(0.2, span / 2), "middle"
    failure = probe_frame(clip, at, dest, seconds=clip_seconds)
    return failure, {"task": FROZEN_CUT_TASK, "at": round(at, 3), "rule": rule}


def degrade_sequence_cuts(cuts_in, frozen, block_seconds, out_dir, index):
    """CF-0549: the cuts of a sequence block QC failed `frozen`, one rung down.

    `frozen` (cut indices, from frozen_cuts()) names the cuts that stuck:
    each of those clip cuts becomes a held frame of its own clip, lifted by
    lift_held_frame(), for the seconds it had; when the cut right after it is
    already a held frame of the same shot (the stretch split's tail), the two
    are one picture - that frame, held for both spans, rather than two stills
    of one shot back to back. Every other cut keeps moving. With no cut
    named, the block keeps its first picture over its whole length, as the
    rung always read - a frame lifted the same way when that picture is a
    clip. Returns (cuts, record, failures): `failures` maps a new cut's
    position to the probe verdict of a frame that could not be lifted."""
    failures = {}
    lifted = []
    named = sorted(k for k in set(frozen or ())
                   if 0 <= k < len(cuts_in) and cuts_in[k].get("kind", "clip") == "clip")
    if not named:
        first = {**cuts_in[0], "kind": "still", "held_frame": True,
                 "seconds": round(block_seconds, 3), "at": 0.0}
        if cuts_in[0].get("kind", "clip") == "clip":
            dest = str(Path(out_dir) / f"_degraded_still_{index}.png")
            failure, rec = lift_held_frame(cuts_in[0], dest)
            first["asset"] = dest
            first["degraded_still"] = {**rec, "cut": 0, "from": "clip"}
            lifted.append(first["degraded_still"])
            if failure:
                failures[0] = failure
        return [first], {"cuts": "all", "frames": lifted}, failures
    out, k = [], 0
    while k < len(cuts_in):
        c = cuts_in[k]
        if k not in named:
            out.append(c)
            k += 1
            continue
        nxt = cuts_in[k + 1] if k + 1 < len(cuts_in) else None
        seconds = float(c.get("seconds") or 0.0)
        if (nxt and nxt.get("kind") == "still" and nxt.get("held_frame")
                and nxt.get("shot") == c.get("shot") and nxt.get("asset")
                and Path(nxt["asset"]).exists()):
            rec = {"task": FROZEN_CUT_TASK, "cut": k, "from": "held_frame",
                   "held_cut": k + 1}
            out.append({**c, "kind": "still", "held_frame": True,
                        "asset": nxt["asset"],
                        "seconds": round(seconds + float(nxt.get("seconds") or 0.0), 3),
                        "degraded_still": rec})
            lifted.append(rec)
            k += 2
            continue
        dest = str(Path(out_dir) / f"_degraded_still_{index}_c{k}.png")
        failure, rec = lift_held_frame(c, dest)
        rec = {**rec, "cut": k, "from": "clip"}
        out.append({**c, "kind": "still", "held_frame": True, "asset": dest,
                    "degraded_still": rec})
        lifted.append(rec)
        if failure:
            failures[len(out) - 1] = failure
        k += 1
    return out, {"cuts": named, "frames": lifted}, failures


def _vision_framing(path, aspect):
    """smart_crop.analyse() of one frame through the warm Vision worker
    (CF-0029), or None when it cannot be had."""
    try:
        import vision_client
        info = vision_client.find_roi(str(path), aspect)
    except Exception:  # noqa: BLE001 - an unread frame is not a candidate
        return None
    return info if isinstance(info, dict) and "roi" in info else None


def grab_frames(source, offsets, dests, seconds=None):
    """CF-0535: frames of `source` at `offsets` into `dests`, in one ffmpeg
    pass (one decoder start, PNG unpacked - compression is most of a frame
    grab's cost at 1080p and the frame lives for one Vision call). Returns
    the dests that were written; a hung or failed pass writes none."""
    cmd = [FFMPEG, "-y", "-nostdin", "-v", "error"]
    for at in offsets:
        cmd += ["-ss", str(round(probe_at_within(at, seconds), 3)), "-i", source]
    for k, dest in enumerate(dests):
        Path(dest).unlink(missing_ok=True)
        cmd += ["-map", f"{k}:v:0", "-frames:v", "1", "-compression_level", "0",
                dest]
    try:
        runlog.run_child(cmd, tool="ffmpeg", check=True,
                         timeout=PROBE_FRAME_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass
    return [d for d in dests if Path(d).exists() and Path(d).stat().st_size > 0]


def reframe_faces(asset, info, probe_path, source, asset_start, shown_seconds,
                  clip_seconds, intent, aspect_wh, block_index, notes,
                  grab=None, analyse=None, score=None):
    """CF-0535: a `faces` clip's window is chosen over the span the block
    shows, by the block's intent - face_window.py has the rule and the reason
    (WNL 0701Z block 5: the probe frame at 0.5 s had the host turned away, so
    the window went to the band behind her for seven seconds).

    `info` is the probe frame's verdict, already framed into `asset`; a few
    more frames of the shown span are lifted, framed by the same rules, and
    the chosen window replaces the probe's in `asset` (focus, zoom, coverage).
    The record goes on the asset (`face_window`) and its lines into `notes`.
    Returns the record (as written) or None when nothing was looked at."""
    if info.get("roi_source") != "faces" or "roi" not in info:
        return None
    grab = grab or grab_frames
    analyse = analyse or _vision_framing
    aw, ah = aspect_wh
    aspect = f"{aw}:{ah}"
    offsets = face_window.span_offsets(asset_start, shown_seconds, clip_seconds,
                                       PROBE_OFFSET)
    frames = [(offsets[0], str(probe_path), info)]
    extra = [str(Path(probe_path).with_name(f"{Path(probe_path).stem}_span{k}.png"))
             for k in range(1, len(offsets))]
    try:
        written = set(grab(source, offsets[1:], extra, seconds=clip_seconds)
                      if extra else [])
        for t, dest in zip(offsets[1:], extra):
            got = analyse(dest, aspect) if dest in written else None
            if got is not None:
                frames.append((t, dest, got))
        kwargs = {} if score is None else {"score": score}
        rec = face_window.reframe(frames, intent, aw, ah, **kwargs)
    finally:
        for dest in extra:
            Path(dest).unlink(missing_ok=True)
    if rec is None:
        return None
    if rec["moved"]:
        fit = asset.get("fit")
        asset.update(framing(rec["info"]))
        if fit:
            asset["fit"] = fit
    out = face_window.public(rec)
    asset[face_window.FIELD] = out
    notes.extend(face_window.describe(block_index, rec))
    return out


def inspect_asset(path, aspect, min_short_side, min_coverage, max_black, card=False,
                  caption_crop=None, frame_before_crop=None, fit=None):
    """Run the gate first: an asset that fails it never reaches the montage.
    Catching this here is the whole point - the first batch shipped a YouTube
    page screenshot because nothing looked at the pictures before cutting.

    `card` (CF-0047) is passed straight through to qc_asset.py, which is where
    the decision about a legitimately dark card is made - this only has to
    tell it what kind of frame it is looking at. `caption_crop` and
    `frame_before_crop` (CF-0062) are the storyboard's record of what
    prepare_clip.py cut off this clip's bottom and the frame it cut it
    from, passed through for the same reason: a resolution rejection then
    says whether the source or that crop is what failed. `fit` (CF-0104) is
    the delivery mode the block will actually use - `common.delivery_fit(
    card)` when the caller does not know better, which is what qc_asset.py
    itself falls back to when this is omitted, so passing it explicitly here
    is only ever a restatement of the same answer, not a second decision.

    CF-0077: both tools run under ASSET_TOOL_TIMEOUT_SECONDS. One that reaches
    it is killed and the asset comes back as tool_timeout_info() - failed by
    that gate, with the tool, the asset and the ceiling in the failure line.
    A qc_asset.py timeout skips smart_crop.py: the asset is already refused,
    a second ceiling on it would only be a second wait.

    CF-0649: qc_asset.py already computes this frame's smart_crop.analyse()
    (through the warm Vision worker, CF-0029) to judge the subject, and with
    --with-framing hands it back under `framing` - the same dict a separate
    smart_crop.py process used to compute a second time, cold, for every
    block (219 s of a 25-block plan's 277 s under load). That dict is the
    framing now; smart_crop.py runs only for a verdict without it."""
    try:
        qc = runlog.run_child(
            [VENV_PY, str(SCRIPTS / "qc_asset.py"), path, "--aspect", aspect, "--json",
             "--with-framing",
             "--min-short-side", str(min_short_side),
             "--min-coverage", str(min_coverage),
             "--max-black", str(max_black)]
            + (["--card"] if card else [])
            + (["--fit", fit] if fit else [])
            + (["--caption-crop", str(caption_crop)] if caption_crop else [])
            + (["--frame-before-crop", str(frame_before_crop)]
               if caption_crop and frame_before_crop else []),
            tool="qc_asset.py",
            capture_output=True, text=True, timeout=ASSET_TOOL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return tool_timeout_info("qc_asset.py", path, ASSET_TOOL_TIMEOUT_SECONDS)
    if not qc.stdout.strip():
        raise SystemExit(f"qc_asset produced no verdict for {path}:\n{qc.stderr}")
    verdict = json.loads(qc.stdout)
    framing = verdict.pop("framing", None)
    if isinstance(framing, dict) and "roi" in framing:
        framing["qc"] = verdict
        return framing

    try:
        crop = runlog.run_child(
            [VENV_PY, str(SCRIPTS / "smart_crop.py"), path, "--aspect", aspect, "--json"],
            tool="smart_crop.py",
            capture_output=True, text=True, timeout=ASSET_TOOL_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        info = tool_timeout_info("smart_crop.py", path, ASSET_TOOL_TIMEOUT_SECONDS)
        # What qc_asset.py did find on this frame stays on the record: the
        # framing gate failed, the picture gate's findings are not unsaid.
        info["qc"]["failures"] = verdict.get("failures", []) + info["qc"]["failures"]
        info["qc"]["failed"] = verdict.get("failed", []) + info["qc"]["failed"]
        info["qc"]["relaxations"] = verdict.get("relaxations", [])
        return info
    if crop.returncode != 0:
        raise SystemExit(f"smart_crop failed for {path}:\n{crop.stderr}")
    info = json.loads(crop.stdout)
    info["qc"] = verdict
    return info

def build_proof_insert(insert, block_index):
    """CF-0071: what build_render_plan.py does with a storyboard's
    `insert: {kind: "proof", ...}` (inserts/proof.json's
    `storyboard_contract`) - runs the proof-specific gate instead of
    inspect_asset(), and returns a provenance record for every insert
    requested (delivered or not - `proof_requested`/`proof_delivered` in
    the plan need every attempt, not just the ones that made it) plus the
    additive `insert` dict for the block itself when it clears the gate.
    Never raises and never touches `rejected`: a failed proof degrades
    its own block, it does not take the whole render down (CF-0031's
    per-block degradation, not CF-0003's whole-plan one).
    """
    provenance = insert.get("provenance") or {}
    capture_path = insert.get("capture_path")
    entry = {
        "block_index": block_index,
        "capture_path": capture_path,
        "delivered": False,
        "gate_failures": [],
    }
    for f in PROVENANCE_REQUIRED:
        entry[f] = provenance.get(f)
    if provenance.get("still_live") is False:
        entry["archive_url"] = provenance.get("archive_url")

    if not capture_path or not Path(capture_path).exists():
        entry["gate_failures"] = ["capture_path missing or file not found"]
        return entry, None

    # A storyboard capture answers to the same gate: the method from its
    # provenance and, for headless_browser, the sidecar beside the file.
    method = provenance.get("capture_method") or "headless_browser"
    proof_text = capture_page.read_proof_text(capture_path) if method == "headless_browser" else None
    ok, failures, legibility = check_proof_gates(capture_path, provenance, method=method,
                                                 proof_text=proof_text)
    entry["gate_failures"] = failures
    if legibility is not None:
        entry["legibility"] = legibility
    if not ok:
        return entry, None

    entry["delivered"] = True
    return entry, {"kind": "proof", "capture_path": str(Path(capture_path).resolve())}


def build_proof_layer(args, words, blocks, pattern_id):
    """CF-0071: plan_proofs() over the finished blocks, or the empty pair
    when the plan was built without a script. Runs ahead of the meme layer
    so that a proof - which has exactly one place, the fact's beat's
    block - is never pre-empted by a meme that could have gone elsewhere.
    Same promise as the other layers: nothing about a proof may fail a
    render, so a missing or malformed script is a note."""
    empty = {"proof_requested": [], "proof_delivered": [], "inserts": [],
             "overlays": {}, "telemetry": None, "notes": []}
    if not args.script:
        return empty
    root = meme_layer.factory_root()
    try:
        batch = json.load(open(args.script))
    except (OSError, ValueError) as e:
        return {**empty, "notes": [f"proof layer skipped: --script unreadable ({e})"]}
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    script = next((sc for sc in scripts or []
                   if sc.get("script_id") == args.script_id), None)
    if script is None:
        return {**empty, "notes": [f"proof layer skipped: script {args.script_id!r} "
                                   f"not in {args.script}"]}
    try:
        return proof_layer.plan_proofs(
            script, words, blocks,
            meme_layer.load_channel(args.channel, root),
            meme_layer.load_pattern(pattern_id, root),
            root=root, work_dir=Path(args.output).resolve().parent,
            frame=(args.width, args.height))
    except Exception as e:  # noqa: BLE001 - nothing about a proof may fail a render
        proofs = script.get("proofs") or []
        proofs = [pr for pr in proofs if isinstance(pr, dict)][:proof_layer.PROOF_MAX_PER_VIDEO]
        return {**empty,
                "proof_requested": [proof_layer._request(pr) for pr in proofs],
                "proof_delivered": [proof_layer._answer(pr.get("proof_id"),
                                                        proof_layer.OUTCOME_CAPTURE_FAILED,
                                                        used=proof_layer.METHOD_QUOTE,
                                                        attempted=[proof_layer.METHOD_QUOTE])
                                    for pr in proofs],
                "notes": [f"proof layer: could not run from {root} ({e}) - "
                          f"{len(proofs)} request(s) answered capture_failed"]}


def build_meme_layer(args, words, blocks, degraded_blocks, pattern_id):
    """CF-0067: plan_memes() over the finished blocks. Never raises past a
    missing or malformed script: that is reported as a note, the way a failed
    proof is, because nothing about a meme may fail a render.

    CF-0138: a missing script is no longer a reason to skip the layer, only a
    reason to have no requests. Rung 1 of the CF-0137 ladder - an insert in a
    block that has no picture - has nothing to do with what the writer asked
    for, and a plan built without `--script` has the same holes as one built
    with it. With the layer switched off (every channel today) that costs a
    spec read and nothing else: plan_memes() touches neither the library nor
    CLIP before `insert_layers.meme.enabled` is true."""
    empty = {"meme_requested": [], "meme_delivered": [], "inserts": [],
             "overlays": {}, "notes": [], "hole_fill": meme_layer.empty_hole_fill()}
    root = meme_layer.factory_root()
    # A note only when a script was named and could not be used - that is an
    # anomaly worth reporting. No `--script` at all is not: it is how the
    # planner is run without a batch, and CF-0138 leaves it a working ladder
    # rather than a complaint.
    script, why = {}, None
    if args.script:
        try:
            batch = json.load(open(args.script))
        except (OSError, ValueError) as e:
            batch, why = None, f"--script unreadable ({e})"
        if batch is not None:
            scripts = batch.get("scripts") if isinstance(batch, dict) else None
            script = next((sc for sc in scripts or []
                           if sc.get("script_id") == args.script_id), None)
            if script is None:
                script, why = {}, (f"script {args.script_id!r} not in {args.script}")
    notes = [f"meme layer: no requests - {why}"] if why else []
    try:
        result = meme_layer.plan_memes(
            script, words, blocks,
            meme_layer.load_channel(args.channel, root),
            meme_layer.load_pattern(pattern_id, root),
            root=root,
            embed=meme_layer.make_embedder(root, args.query_vectors),
            # CF-0392: the box the meme is drawn into (above the caption
            # band, CF-0394), not the output frame - the stretch it is judged
            # on is the stretch it gets. The plan written below carries
            # safe_area.safe_zones(), which is what meme_box() reads by default.
            frame=meme_layer.meme_box({"output": {"width": args.width,
                                                  "height": args.height}}),
            plan_degraded=degraded_blocks,
            work_dir=Path(args.output).resolve().parent)
    except Exception as e:  # noqa: BLE001 - nothing about a meme may fail a render
        return {**empty, "notes": notes + [f"meme layer: could not run from {root} ({e})"]}
    result["notes"] = notes + result["notes"]
    return result


def default_alias_files(output):
    """CF-0080's alias table for the batch this plan belongs to, found the
    way `video_attempt()` finds the ledger: off the `<batch>/work/<slug>/
    plan.json` layout of the output path. Both files are optional - a batch
    ingested before CF-0080 has neither, and no table means "no known
    duplicates", which is the only thing such a batch can honestly say."""
    try:
        batch = Path(output).resolve().parents[2]
    except IndexError:
        return []
    return [p for p in (batch / "01b-footage-index.json",
                        batch / "work" / "footage-aliases.json") if p.is_file()]


def build_two_source_gate(args, blocks):
    """CF-0118: how many independent footage sources the finished blocks
    actually use, and in which mode that verdict is applied.

    "Independent" is CF-0080's canonical source, not a video id: three
    uploads of one trailer are one source (source_gate.py holds the whole
    definition). The mode comes from the channel -
    `video_editor.two_source_gate`, default `measure` - and
    `--two-source-gate` overrides it for one run.

    Never raises: a gate that cannot read an alias table counts the ids it
    can see and says so, the same promise the insert layers make."""
    cfg = None
    try:
        cfg = meme_layer.load_channel(args.channel, meme_layer.factory_root())
    except Exception:  # noqa: BLE001 - an unreachable root is a `measure` run
        cfg = None
    mode = args.two_source_gate or source_gate.mode_from_channel(cfg)
    required = source_gate.required_from_channel(cfg)
    alias_files = [p for p in (args.footage_index, args.footage_aliases,
                               args.alias_groups) if p]
    if not alias_files:
        alias_files = default_alias_files(args.output)
    aliases = source_gate.load_aliases(*alias_files)
    return source_gate.judge(blocks, args.index, aliases,
                             required=required, mode=mode)


def api_chat_context(args, story):
    """CF-0690: (config, protocols) for the `api_chat` graphics this
    storyboard places - the channel's `api_demo` block of its
    footage-origin.json and {record_id: protocol} of the calls their orders
    name (the batch's 01-trend-hunter.json, else the Trend Hunter's cache
    `<batch>/work/api_demo/`). (None, {}) when the storyboard places no chat:
    nothing is read. A record not found is simply absent - the chat is then
    refused `api_demo_no_record`; never guessed."""
    orders = [sb.get("graphic") for sb in (story or {}).get("blocks") or []
              if isinstance(sb, dict) and sb.get("asset_kind") == own_graphic_plan.KIND
              and isinstance(sb.get("graphic"), dict)
              and sb["graphic"].get("template") == own_graphic_plan.API_CHAT]
    if not orders:
        return None, {}
    config = None
    if args.channel:
        try:
            from _channel_data import channel_data
            channel = ((load_channel_cfg(args) or {}).get("channel_id")
                       or (Path(args.channel).stem if str(args.channel).endswith(".json")
                           else args.channel))
            config = own_graphic_plan.api_demo_config(
                channel_data.footage_origin(channel, meme_layer.factory_root()))
        except Exception:  # noqa: BLE001 - no document: no config, the order's own caps
            config = None
    found = attempts.batch_context(args.output)
    return config, own_graphic_plan.chat_protocols(orders, found[0] if found else None)


def load_channel_cfg(args):
    """The channel's config, or None.

    Never raises: an unreachable factory root, a channel that does not exist
    and a config that is not JSON all answer None, and every switch this
    planner reads treats None as off (`assetless_rung.enabled()`,
    `blooper_gate.relaxation()`). A switch that cannot be read has not been
    switched on."""
    try:
        return meme_layer.load_channel(args.channel, meme_layer.factory_root())
    except Exception:  # noqa: BLE001 - no config readable means no permission
        return None


def panel_gate_thresholds(cfg):
    """CF-0327: the panel gate's mode and floor, as the plan will carry them.

    Read off `video_editor.panel_in_frame` of the channel config - `{"mode":
    "warn"}` is the whole of what a channel has to write to keep the gate as a
    warning until CF-0320's price is measured. An unreadable config, a channel
    that says nothing, or a value the gate does not recognise all leave the
    keys off the plan entirely, and `inset_panel.mode_of()` then answers with
    its own default. Only a stated opinion travels.
    """
    block = ((cfg or {}).get("video_editor") or {}).get("panel_in_frame") or {}
    out = {}
    mode = str(block.get("mode", "")).strip().lower()
    if mode in inset_panel.MODES:
        out[inset_panel.MODE_KEY] = mode
    try:
        floor = float(block.get("floor"))
    except (TypeError, ValueError):
        floor = None
    if floor is not None and 0.0 < floor <= 1.0:
        out[inset_panel.FLOOR_KEY] = floor
    # CF-0894: sequence cuts judged like plain blocks - only a real boolean.
    if isinstance(block.get("sequence_cuts"), bool):
        out[inset_panel.SEQUENCE_KEY] = block["sequence_cuts"]
    return out


def build_blooper_gate(args, blocks, words):
    """CF-0190 part 3: the two borders of the blooper relaxation, on the
    finished block list.

    Asked here rather than in qc_render.py for CF-0137's reason - a refusal
    after the render is a refusal that was already paid for - and it sees the
    *plan* block, which is where the marker carried off the storyboard and the
    span the viewer actually gets both live."""
    return blooper_gate.judge(blocks, words, load_channel_cfg(args))


def build_assetless_rung_gate(args, blocks, degraded_blocks, style):
    """CF-0137: whether any block would ship with no picture, and whether
    this channel allows that.

    The blocks are the truth, not `degraded_blocks`: a block is on the
    assetless rung when it has no picture (`rhythm.has_picture()`, CF-0136),
    whichever branch above put it there, so a rung added later cannot slip
    past this by forgetting to append a degradation record. The records are
    only what the reasons are read from.

    Never raises: an unreachable factory root means no channel config, and
    no channel config means the rung is off (`assetless_rung.enabled()`
    defaults to False) - a refusal, never an accidental permission."""
    cfg = load_channel_cfg(args)
    records = {int(d["index"]): d for d in degraded_blocks
               if d.get("to") == "typographic"}
    assetless = []
    for i, b in enumerate(blocks):
        # CF-0138: a block whose frame was given whole to a library insert is
        # not a block shipping with no picture. Two predicates rather than
        # one, and deliberately: `rhythm.has_picture()` stays CF-0136's
        # question about *footage* - how much of this video the montage
        # actually covered - and folding an insert into it would erase from
        # `rhythm.picture` the fact that the material never arrived, which is
        # the number the Analyst reads to widen the pool. What this gate asks
        # is the different question of whether anything at all is on screen.
        if rhythm.has_picture(b) or assetless_rung.filled_by_insert(b):
            continue
        rec = records.get(i, {})
        entry = {
            "index": i,
            "from": rec.get("from"),
            "reason": rec.get("reason") or "block carries no picture at all",
        }
        # CF-0150: and what the pool had for this anchor, off the plan block
        # where emit_block() copied it. `from` says which rung the block fell
        # from and cannot say whether there was ever a picture to fall with;
        # this says whether the pool offered one. Only when the block carries
        # the key at all - a plan built before CF-0150 leaves it out, and the
        # rotation has to be able to tell "the pool delivered" (null) from
        # "nobody asked" (absent).
        if "candidate_supply" in b:
            entry["candidate_supply"] = b["candidate_supply"]
        assetless.append(entry)
    return assetless_rung.judge(assetless, cfg, style=style, blocks=blocks)


def build_hole_fill_probe(args, blocks, degraded_blocks, pattern_id):
    """CF-0138: could rung 1 close every hole in this plan, in principle?

    The cheap question the assetless gate has to answer before it decides
    whether to refuse now or after the insert layer has run. Config switches
    and block lengths only - see meme_layer.hole_fill_feasible().

    Never raises, and an unreadable anything answers `False`: a probe that
    cannot tell whether the rung applies must not buy the plan a reprieve it
    then cannot use - that would turn an unreachable factory root into a full
    bill for the vision layers on a plan that is refused anyway."""
    try:
        root = meme_layer.factory_root()
        return meme_layer.hole_fill_feasible(
            blocks,
            meme_layer.load_channel(args.channel, root),
            meme_layer.load_pattern(pattern_id, root),
            root=root, plan_degraded=degraded_blocks)
    except Exception as e:  # noqa: BLE001 - an unreadable probe is a refusal
        return {"holes": [], "at_floor": [], "feasible": False,
                "reason": f"the insert rung could not be probed ({e})"}


def write_gate_deficit(output, rec):
    """The refused plan's machine-readable deficit, beside where the plan
    would have been (`plan.two-source-gate.json`).

    In `enforce` mode there is no plan file to carry the CF-0057-shaped
    record, and the caller has to be able to *read* the shortfall rather
    than parse our stderr - it is the same record that rides in
    plan["rhythm"]["rhythm_shortfalls"] on a plan that was written."""
    p = Path(output)
    path = p.with_name(f"{p.stem}.two-source-gate.json")
    try:
        json.dump({"two_source_gate": rec, "deficit": source_gate.deficit(rec)},
                  open(path, "w"), indent=2)
    except OSError as e:
        return f"<not written: {e}>"
    return str(path)


def refusal_script_id(args, story=None):
    """Which script this plan was for, for the CF-0254 refusal record.

    `--script-id` is what the orchestrator passes and what the funnel joins
    on (03-content-researcher.json `scripts[].script_id`); the storyboard's
    own field is the same id when it carries one. The slug of
    `<batch>/work/<slug>/` is the last resort - it is what the batch calls
    this video everywhere else, so a refusal recorded under it is still
    findable, which a plan file's stem ("plan") would not be.
    """
    sid = args.script_id or (story or {}).get("script_id")
    if sid:
        return sid
    found = attempts.batch_context(args.output)
    return found[1] if found else Path(args.output).stem


def person_shot_warnings(args, story, blocks, warnings):
    """CF-0879: the resolver's `person_shot` record onto the plan, and one
    `person_shot_risk` warning per block that still shows somebody else's
    face under the words naming X (mode `measure`, CF-0320 - no price, no
    refusal). A risky block counts only while the plan block still shows the
    shot the resolver measured. Returns the record (None for a storyboard
    resolved before CF-0879)."""
    rec = (story or {}).get(person_shot.RECORD)
    if not isinstance(rec, dict):
        return None
    for r in rec.get("risky_blocks") or []:
        i = r.get("block")
        if not isinstance(i, int) or not 0 <= i < len(blocks):
            continue
        shown = {key for key, _, _ in person_shot.block_shot_refs(blocks[i])}
        if r.get("shot") not in shown:
            continue
        w = person_shot.warning(refusal_script_id(args, story), r)
        warnings.append(w)
        print(f"PERSON SHOT RISK - WARNING (measure), the plan is written: "
              f"{w['reason']}", file=sys.stderr)
    return rec


def warn_plan(args, warnings, gate, headline, lines, numbers=None, deficit=None,
              story=None):
    """CF-0330: what `refuse_plan()` would have recorded, as a warning.

    The user, 2026-09-23: the gates of `plan_refusal.WARN_GATES` (and a
    measured two-source gate) warn instead of refusing. Same gate id, same
    funnel code, same sentence and numbers a refusal carries - appended to
    `warnings`, which becomes `plan["warnings"]` - and the plan goes on.
    Nothing exits here and nothing is written to `refusals[]`."""
    reason = plan_refusal.reason_text(headline, lines)
    rec = plan_refusal.warning(refusal_script_id(args, story), gate, reason,
                               numbers=numbers, deficit=deficit)
    warnings.append(rec)
    print(f"{headline} - WARNING, the plan is written "
          f"[{plan_refusal.code_for(gate)}/{gate}] ({plan_refusal.WARN_DECISION})",
          file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)
    runlog.annotate(warned=f"{gate} {plan_refusal.code_for(gate)}")
    return rec


def assetless_numbers(rec, hole_fill=None):
    """CF-0330: the assetless gate's numbers for its warning record."""
    out = {"blocks": list(rec.get("blocks") or []),
           "block_count": rec.get("block_count"),
           "total_blocks": rec.get("total_blocks"),
           "seconds": rec.get("seconds"),
           "rung_enabled": rec.get("rung_enabled")}
    if hole_fill is not None:
        out["filled_by_insert"] = len(hole_fill.get("filled") or [])
    return out


def refuse_plan(args, gate, headline, lines, notes=(), deficit=None, story=None,
                exit_code=2, supersedes_video=False):
    """CF-0254: end a whole-plan refusal - stderr, the record, the exit.

    Every gate that refuses a plan outright goes through here, so that the
    batch's own artifact carries the answer and not only the run's stderr.
    `lines` are the gate's findings and are the `reason` the funnel prints;
    `notes` are the policy paragraphs some gates add for the operator and stay
    on stderr - the reason has to fit one cell of a table. `deficit` is the
    path a gate that writes one just wrote (`plan.two-source-gate.json` and
    the rest): printed as before, and carried in the record so a reader of
    05-video-editor.json can find the machine-readable half.

    `supersedes_video` (CF-0270) says this refusal was made on a *rebuild* -
    an attempt has already been spent and its mp4 is on disk. The record then
    carries the flag that stops that mp4 winning at merge, because the render
    it names is the one this refusal is about. Only the gates that can fire on
    a rebuild pass it.

    Does not return: the caller's next line would have been `sys.exit`.
    """
    lines = [str(x) for x in lines]
    print(f"{headline} - plan not written:", file=sys.stderr)
    for line in lines:
        print(f"  {line}", file=sys.stderr)
    for line in notes:
        print(f"  {line}", file=sys.stderr)
    if deficit:
        print(f"  deficit -> {deficit}", file=sys.stderr)
    script_id = refusal_script_id(args, story)
    path = plan_refusal.write(args.output, script_id, gate,
                              plan_refusal.reason_text(headline, lines), deficit=deficit,
                              supersedes_video=supersedes_video)
    # CF-0254: the line the operator carries into `write_batch_metadata.py` -
    # which is now called for a batch with zero videos too, and finds this
    # file by itself.
    print(f"  refusal -> {path} ({plan_refusal.code_for(gate)}: {script_id})", file=sys.stderr)
    runlog.annotate(refused=f"{gate} {plan_refusal.code_for(gate)}")
    sys.exit(exit_code)


def footage_rights_inputs(args):
    """-> (read_rights, shot_dirs, origins) - what CF-0664's credits, CF-0567's
    own captures and its quote cap read: the rights reader over the batch's
    01b-footage-index.json (`--footage-index`, else found beside the plan) and
    the pool's shots.json, the pool directories, and the channel's
    footage-origin.json (None when the channel has none). Raises only on an
    unreadable batch layout; the callers decide what that costs."""
    index = args.footage_index
    if not index:
        index = next((p for p in default_alias_files(args.output)
                      if p.name == "01b-footage-index.json"), None)
    dirs = list(dict.fromkeys(
        [str(Path(i).parent) for i in (getattr(args, "index", None) or [])]
        + [str(d) for d in share_gate.footage_dirs()]))
    origins = None
    if args.channel:
        try:
            from _channel_data import channel_data
            channel = ((load_channel_cfg(args) or {}).get("channel_id")
                       or (Path(args.channel).stem if str(args.channel).endswith(".json")
                           else args.channel))
            origins = channel_data.footage_origin(channel, meme_layer.factory_root())
        except Exception:  # noqa: BLE001 - no document: no origin names, rows still written
            origins = None
    return footage_credits.rights_reader(index, dirs), dirs, origins


def build_footage_credits(args, plan):
    """CF-0664 (VE-1): plan["footage_credits"] - one row per judged source the
    finished blocks show, with its rights record (01b `fetched[].rights`, else
    the pool's shots.json `source_rights`) - and plan["credit_overlays"], the
    small credit over the shots of an origin that wants it on the picture.
    CF-0567: our own recording (`own_capture-<id>`) gets neither.
    CF-0689: nor does a graphic the factory draws (`own_graphic` names no
    source: source_gate.block_sources() is [] for it).

    Never raises: a source whose rights cannot be read gets no row and a note,
    which is what an unjudged source gets anyway (nothing is invented)."""
    try:
        read_rights, _dirs, origins = footage_rights_inputs(args)
        rows, overlays, notes = footage_credits.plan_credits(plan, read_rights, origins)
    except Exception as e:  # noqa: BLE001 - a credit never fails a render
        return [], [], [f"footage credit: could not be read ({e}) - none written (CF-0664)"]
    return rows, overlays, notes


def build_proof_quote_cap(args, blocks, pattern_id):
    """CF-0567: the proof-quote cap's record over the final blocks
    (proof_quote_cap.judge). The rights of each source and the channel's
    `proof_quotes` / `official_channels` come through footage_rights_inputs();
    a channel whose document cannot be read is not measured, and says so."""
    try:
        read_rights, _dirs, origins = footage_rights_inputs(args)
    except Exception as e:  # noqa: BLE001 - an unreadable batch layout: the rights stay unknown
        read_rights, origins = None, None
        note = f"rights could not be read ({e})"
    else:
        note = None
    rec = proof_quote_cap.judge({"blocks": blocks}, read_rights, origins, pattern_id)
    if note:
        rec["note"] = f"{rec['note']} - {note}"
    return rec


def build_own_captures(args, plan):
    """CF-0567: plan["own_captures"] - the factory's own recordings on screen,
    with the page, the host entry and the Space's licence from the
    recorder's sidecar in the pool (footage_credits.plan_own_captures). Never
    raises: a record that cannot be read is a note."""
    try:
        read_rights, dirs, _origins = footage_rights_inputs(args)
        return footage_credits.plan_own_captures(plan, read_rights, dirs), []
    except Exception as e:  # noqa: BLE001 - a record never fails a render
        return [], [f"own capture: could not be read ({e}) - none written (CF-0567)"]


def build_comparison_lines(args, words, plan):
    """CF-0116 / CF-0186: the on-screen line - the video's production fact
    and a badge naming the source it came from - planned over the *finished*
    plan, because it needs the blocks, the video's duration and whatever
    proof CF-0071 placed. It runs last of all and touches nothing but
    plan["comparison_lines"]. Same promise as the insert layers: a missing
    or malformed script is a note, never a failed render, and a script with
    no `production_fact` at all (every script until CF-0183 lands) is the
    ordinary case of that.

    One exception, CF-0164: `comparison_line.SourceBadgeError`. An unknown
    publication host, a name too wide for the panel and a tenth source are
    the three cases the user ruled must stop and be reported rather than be
    worked around - a badge naming the wrong publication, or naming a
    truncated one, is worse than no video. Those pass straight through and
    fail the plan, the way end_card.EndCardError does."""
    empty = {"lines": [], "delivered": [], "notes": []}
    if not args.script:
        return empty
    try:
        root = meme_layer.factory_root()
        batch = json.load(open(args.script))
    except (OSError, ValueError, RuntimeError) as e:
        return {**empty, "notes": [f"comparison line skipped: --script unreadable ({e})"]}
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    script = next((sc for sc in scripts or []
                   if sc.get("script_id") == args.script_id), None)
    if script is None:
        return {**empty, "notes": [f"comparison line skipped: script {args.script_id!r} "
                                   f"not in {args.script}"]}
    try:
        return comparison_line.plan_lines(script, words, plan,
                                          meme_layer.load_channel(args.channel, root))
    except comparison_line.SourceBadgeError:
        raise  # CF-0164: these three stop the stage; see the docstring
    except Exception as e:  # noqa: BLE001 - nothing else about a line may fail a render
        return {**empty, "notes": [f"comparison line: could not be planned ({e})"]}


def build_end_card(args, plan):
    """CF-0117: the channel's end card, planned over the *finished* plan -
    it starts where the narration ends, so it runs after everything that
    could still move that number.

    Unlike every other layer here, this one does not degrade to a note. The
    stance document is the channel's position and has exactly one address
    (CF-0063); the length is the CF-0087 constant. Neither can be guessed, so
    a channel that names a stance document it does not have gets no plan -
    the same answer a rejected asset gets - and the operator is told which
    file to fix.

    CF-0186: a stance document that carries no `signature_phrase` is not that
    case. The channel signs with its logo or its name and the card is planned
    without a phrase; with none of the three there is nothing to draw and the
    card is dropped with a note (`plan_end_card()` returns None).

    Two soft cases, and neither is a broken channel. No `--channel` at all:
    nothing here knows which channel the video belongs to, and that is a
    call the operator made. A config that names no `stance` document: it
    never joined CF-0063's system, so there is no phrase to have lost. Both
    are a note on the plan and a line on stderr, and the plan is written.
    """
    if not args.channel:
        return None, ["end card: no --channel, so no card was planned - the phrase "
                      "and the 3s constant are the channel's (CF-0063 / CF-0087)"]
    root = meme_layer.factory_root()
    cfg = meme_layer.load_channel(args.channel, root)
    if cfg is None:
        raise end_card.EndCardError(
            f"channel {args.channel!r} not found under {root}/channels")
    named = cfg.get("stance")
    # CF-0141: a channel that closes on its own clip needs no phrase, so the
    # stance requirement below must not stand between it and its ending. The
    # clip is asked for first, and only a channel without one falls through to
    # the drawn card and its CF-0063 obligations.
    has_clip = end_card.ending_path(cfg, root, args.channel)[0] is not None
    if not has_clip and not (isinstance(named, str) and named.strip()):
        # A config that names no stance document has not joined the CF-0063
        # system at all - it is not a channel with a position whose file went
        # missing, which is the case the refusal below exists for. No card, a
        # note, and the plan is written: refusing here would hold every
        # config that predates the stance (and every layer fixture built from
        # one) hostage to a field it never had.
        return None, [f"end card: {args.channel} names no `stance` document, so the "
                      f"channel has no signature phrase to sign with (CF-0063) - "
                      f"no card was planned"]
    stance = {} if has_clip and not (isinstance(named, str) and named.strip()) \
        else end_card.load_stance(cfg, root, args.channel)
    card = end_card.plan_end_card(plan, cfg, stance, root=root, channel=args.channel)
    if card is None:
        # CF-0186: no phrase, no logo, no name - nothing to hold the frame
        # for. The card is not planned and its seconds stay with the
        # narration; a blank slate on the end of the video would be worse
        # than no card at all.
        return None, [f"end card: {args.channel} has no signature phrase, no logo and "
                      f"no display name - there is nothing to draw on a card, so none "
                      f"was planned (CF-0186)"]
    if card["variant"] == end_card.VARIANT_CLIP:
        # CF-0315: the ceiling the clip was let through by, on the plans that
        # PASS and not only in the refusal. A pattern that gave the ceiling no
        # number - an envelope shape or a band mode this repo cannot read - is
        # named in that line, and a plan that passes is the only place such a
        # pattern would otherwise never be noticed: the ceiling silently
        # computed over half the vocabulary reads exactly like one computed
        # over all of it, which is the defect this task is about.
        return card, [f"ending: the channel's own clip, {card['seconds']:.2f}s from "
                      f"{card['start_s']:.2f}s - {card['path']} "
                      f"(found by {card['source']})",
                      "ending ceiling: " + end_card.ceiling_sentence(
                          end_card.structural_ceiling(cfg, root))]
    note = (f"end card: {card['variant']}, {card['seconds']:.2f}s from "
            f"{card['start_s']:.2f}s, "
            + (f"phrase from {card['text_source']}" if card["text"]
               # CF-0186: a phraseless card names what it *is* instead of
               # where its words came from, so the note never reads as a
               # phrase that went missing.
               else f"no signature phrase - the card is "
                    f"{'the channel logo' if card['logo_path'] else 'the channel name'}"))
    if card["variant"] == end_card.VARIANT_TYPOGRAPHIC:
        note += " (no channel logo asset - typographic is the floor, not a failure)"
    return card, [note]


def build_underlay_layer(args, story, voice_seconds):
    """CF-0127: which loop goes in the second plane of this video's frame.

    The only insert layer that is decided *before* the blocks, because it is
    the only one that changes `layout`: the band takes its height out of
    `main`, and `main` is what every block is framed and cropped against
    (`split_half_size()` frames CF-0050's halves against it too). Deciding
    it after the loop would frame a two-plane video against a one-plane
    frame. It needs no script and no pattern - the underlay answers to the
    channel switch and the library rotation alone (CF-0014) - so it runs on
    every plan, with or without `--script`.

    `voice_seconds` is the narration's length, not the composition's: the
    band stops where CF-0117's end card is mounted, so the loop is sized to
    the span it actually covers.

    Never raises: any failure is an answer with `applied: false`, an empty
    second plane and a reason in `plan["underlay"]`.
    """
    root = meme_layer.factory_root()
    video_id = (args.script_id or (story or {}).get("script_id")
                or Path(args.output).stem)
    try:
        return underlay_layer.plan_underlay(
            video_id, meme_layer.load_channel(args.channel, root),
            root=root, video_seconds=voice_seconds)
    except Exception as e:  # noqa: BLE001 - decoration may never fail a render
        record = underlay_layer.unreachable_record(video_id, root)
        record["note"] = f"underlay layer unreadable from {root} ({e})"
        return record


def build_sound_layer(args, words, blocks, pattern_id, voice_seconds):
    """CF-0068: plan_sounds() over the finished blocks, or the empty pair when
    the plan was built without a script. Same shape and same promise as
    build_meme_layer(): a missing or malformed script is a note, never a
    failed render."""
    empty = {"sound_requested": [], "sound_delivered": [], "inserts": [],
             "placed": [], "notes": []}
    if not args.script:
        return empty
    root = meme_layer.factory_root()
    try:
        batch = json.load(open(args.script))
    except (OSError, ValueError) as e:
        return {**empty, "notes": [f"sound layer skipped: --script unreadable ({e})"]}
    scripts = batch.get("scripts") if isinstance(batch, dict) else None
    script = next((sc for sc in scripts or []
                   if sc.get("script_id") == args.script_id), None)
    if script is None:
        return {**empty, "notes": [f"sound layer skipped: script {args.script_id!r} "
                                   f"not in {args.script}"]}
    try:
        return sound_layer.plan_sounds(
            script, words, blocks,
            meme_layer.load_channel(args.channel, root),
            meme_layer.load_pattern(pattern_id, root),
            root=root, voice_end=voice_seconds)
    except Exception as e:  # noqa: BLE001 - nothing about a sound may fail a render
        # The spec or the library could not be read from this root (a
        # checkout without inserts/sound.json, a broken index): no file can
        # be chosen, so every request is answered no_asset - still counted,
        # never dropped - and the reason goes into the notes.
        sounds = script.get("sounds") or []
        sounds = sounds[:SOUND_MAX_PER_VIDEO] if isinstance(sounds, list) else []
        return {**empty,
                "sound_requested": [{"beat_id": s.get("beat_id"), "intent": s.get("intent")}
                                    for s in sounds],
                "sound_delivered": [{"beat_id": s.get("beat_id"),
                                     "outcome": sound_layer.OUTCOME_NO_ASSET,
                                     "block_index": None, "asset_id": None, "at_seconds": None}
                                    for s in sounds],
                "notes": [f"sound layer: library unreadable from {root} ({e}) - "
                          f"{len(sounds)} request(s) answered no_asset"]}


def build_bed_rotation(args, story):
    """CF-0271: which of the channel's beds plays under this video.

    Decided here, in the plan, and not in `build_soundtrack.py`, for one
    reason: the mixer is handed `--plan` and a voice file and does not know
    the `script_id` - the plan does, and the plan is already where the
    Editor's decisions live (`rhythm`, `two_source_gate`, `assetless_rung`,
    `end_card`). The mixer executes what is written here.

    `None` - meaning "this channel does not rotate" - on every channel that
    brings a single file, on a plan built without `--channel`, and on a
    channel with no bed at all: those mix exactly as they did before this
    task. The key is `None` too on a plan built before it, and the mixer can
    tell the two cases apart because the *channel* says whether it rotates.

    An `AmbientBedError` from the channel's list is deliberately not caught.
    A rotation that names a missing file stops the video here rather than
    after the render, which is CF-0153's own doctrine (a channel asset is a
    written rule checked before anything runs), and one step earlier than the
    mixer would have stopped it anyway.
    """
    if not args.channel:
        return None
    cfg = load_channel_cfg(args)
    if cfg is None:
        return None
    root = meme_layer.factory_root()
    beds = ambient_bed.ambient_beds(cfg, root, args.channel)
    if not beds or beds[0][1] != ambient_bed.AMBIENT_SOURCE_ROTATION:
        return None
    # The same key the underlay layer rotates on, and for the same reason: it
    # is what the batch calls this video everywhere else, and it does not move
    # between render attempts of the same video. `chosen_by` names whichever
    # of the two was hashed, because a record that cannot be rechecked is a
    # record that has to be believed.
    script_id = args.script_id or (story or {}).get("script_id")
    key = script_id or Path(args.output).stem
    return ambient_bed.rotation_record(
        beds, key,
        chosen_by=(ambient_bed.BED_CHOSEN_BY_SCRIPT_ID if script_id else "sha256(slug)"))


# CF-0648: the command line's run (cli()) re-cuts what held_screen flags; an
# in-process caller of main() (a test) builds one plan and nothing else.
HELD_RECUT_ON = False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("storyboard")
    p.add_argument("words")
    p.add_argument("voice")
    p.add_argument("output")
    p.add_argument("--style", default=None)
    p.add_argument("--width", type=int, default=1080)
    p.add_argument("--height", type=int, default=1920)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--target-duration", type=float, nargs=2, default=None,
                   help="the NARRATION's length band. Default (CF-0158): derived "
                        "from --channel as [total_seconds_min - tail, "
                        "total_seconds_max - tail] - the channel's 45-60s "
                        "finished-video band minus the tail it ends on, 39.83-"
                        "54.83s on example-film today; without --channel the "
                        "factory's band itself, unsubtracted. The CF-0087 gate's "
                        "ceiling is this upper bound plus the tail, so the video "
                        "is still refused at the same 60s")
    p.add_argument("--channel", default=None,
                   help="CF-0087: channel whose channels/<channel>.json#"
                        "narration_budget supplies the 55s target, the tail the "
                        "video ends on and (CF-0158) the band --target-duration "
                        "defaults to; without it only the ceiling is gated")
    p.add_argument("--estimated-seconds", type=float, default=None,
                   help="CF-0087: the script's own estimate (narration."
                        "estimated_seconds in 03-content-researcher.json), "
                        "recorded against the actual length - a signal, not a gate")
    # CF-0212: no --watermark-text. The mark's text is the channel's
    # `display_name` (channel_watermark.py); a default here was the first
    # channel's name drawn on every other channel's frames.
    p.add_argument("--watermark-position", default="top-left")
    p.add_argument("--max-black", type=float, default=0.35,
                   help="near-black ceiling for stills; clips use a looser ceiling because "
                        "dark cinematography is normal")
    p.add_argument("--min-coverage", type=float, default=MIN_COVERAGE,
                   help="subject-retention floor; a relaxed floor is recorded in the "
                        "plan's notes, never silently applied")
    p.add_argument("--min-short-side", type=int, default=MIN_SHORT_SIDE,
                   help="resolution floor for source assets; a relaxed floor is "
                        "recorded in the plan's notes, never silently applied")
    p.add_argument("--script", default=None,
                   help="CF-0067: the batch's 03-content-researcher.json, whose "
                        "script (--script-id) may carry `reactions[]` for the "
                        "meme layer; without it meme_requested is []")
    p.add_argument("--script-id", default=None,
                   help="CF-0067: which script in --script this plan is for")
    p.add_argument("--query-vectors", default=None,
                   help="CF-0067 test seam: json {query: 512-d vector} in place "
                        f"of CLIP (also ${meme_layer.QUERY_VECTORS_ENV})")
    # CF-0118: the two-source gate. The mode is the channel's
    # (`video_editor.two_source_gate`, default `measure`); these say what to
    # count it over. --index is optional (a block's `shot` key already names
    # its source); the alias table is found off the batch layout of `output`
    # unless one is named here.
    p.add_argument("--index", action="append", default=[],
                   help="a shots.json this plan was resolved against. "
                        "Repeatable. CF-0118: the media behind each source id.")
    p.add_argument("--footage-index", default=None,
                   help="<batch>/01b-footage-index.json - CF-0080's `aliases`. "
                        "Default: found beside the output's batch.")
    p.add_argument("--footage-aliases", default=None,
                   help="<batch>/work/footage-aliases.json (CF-0080). "
                        "Default: found beside the output's batch.")
    p.add_argument("--alias-groups", default=None,
                   help="a plain grouping of re-uploads, [[canonical, alias, "
                        "...]] or {canonical: [alias, ...]}, for a batch that "
                        "predates CF-0080 and has no alias table of its own.")
    p.add_argument("--two-source-gate", choices=source_gate.MODES, default=None,
                   help="override the channel's "
                        f"{source_gate.CHANNEL_KEY} for this run. "
                        "`measure` records the verdict and rejects nothing; "
                        "`enforce` refuses a plan with fewer than two "
                        "independent sources (exit 2).")
    p.add_argument("--no-held-recut", action="store_true",
                   help="CF-0648: measurement only - write the plan with the "
                        "pictures held_screen flags, without re-cutting them "
                        "under the anchor's next candidate")
    p.add_argument("--degrade-block", action="append", default=[],
                   metavar="INDEX:TARGET:REASON",
                   help="drop one specific block a rung (TARGET is 'still' or "
                        "'typographic') instead of degrading the whole plan. "
                        "REASON is free text (e.g. the motion score from "
                        "qc_render.py's frozen_blocks()). Repeatable, one per "
                        "failed block. CF-0031.")
    args = p.parse_args()
    runlog.annotate(**video_attempt(args.output))  # CF-0107: slug + ledger attempt
    # CF-0212: read before any work, so a channel that cannot name its mark
    # costs one config read, not a plan.
    watermark_text, watermark_note = channel_watermark.watermark_text(
        args.channel, load_channel_cfg(args) if args.channel else None)
    # CF-0572: the same for the on-screen theme - a channel without one is a
    # refusal here, not ExampleFilm's palette in the frame.
    plan_theme, theme_note = channel_theme.plan_theme(
        args.channel, load_channel_cfg(args) if args.channel else None,
        meme_layer.factory_root())

    degrade_map = {}
    for spec in args.degrade_block:
        idx_s, _, rest = spec.partition(":")
        target, _, reason = rest.partition(":")
        if target not in ("still", "typographic"):
            raise SystemExit(
                f"--degrade-block target must be 'still' or 'typographic', "
                f"got {spec!r}")
        degrade_map[int(idx_s)] = (target, reason or "failed post-render QC")
    # CF-0549: which cut of a sequence block QC found stuck - read now, from
    # the ledger and the plan QC judged, before this build overwrites it.
    frozen_cut_map = frozen_cuts(
        args.output, {i for i, (t, _) in degrade_map.items() if t == "still"})

    story = json.load(open(args.storyboard))
    story_rhythm = story.get("rhythm") or {}

    # CF-0290: before the words are loaded and before the voice is probed -
    # this gate needs the storyboard and nothing else, so a plan that may not
    # be written costs one file read. `supersedes_video` on a rebuild for the
    # same reason the pattern ceiling passes it (CF-0270): a `--degrade-block`
    # run is the answer to an mp4 that already exists, and that mp4 is the
    # render this refusal is about.
    #
    # CF-0433: no longer a refusal. A block whose picture scores under the
    # floor is `score.low_similarity` (-3 a block, cap -15) - the resolver
    # admits such a candidate only when nothing at or above the floor fills
    # the block - and the plan is refused only when the score falls under N
    # (plan_score_gate() below, where every price of this stage is summed).
    off_topic = under_floor_anchors(story)
    similarity = similarity_findings(story, off_topic)

    words = load_words(args.words)
    duration = audio_duration(args.voice)

    # CF-0158: `duration.target` is the narration's band, and the band is
    # derived, never a literal. It used to be `[35.0, 60.0]` typed into the
    # argparse default above - a floor that followed nothing (it predates the
    # channel having an ending at all) and therefore did not move when
    # ending.mp4 did. Now it is the channel's finished-video band minus the
    # channel's tail; lengthen the ending clip and both ends come down by
    # exactly that much. An explicit --target-duration still wins: an
    # operator overriding the band is the one case where a literal is a
    # decision rather than a leftover.
    budget = narration_length.load_narration_budget(args.channel)
    target_notes = []
    if args.target_duration:
        lo_t, hi_t = args.target_duration
    else:
        derived = narration_length.narration_band(budget)
        if derived is None:
            # No factory root reachable from this checkout: this repo carries
            # the ceiling (HARD_CEILING_SECONDS, one copy of
            # MAX_TARGET_SECONDS) but no floor of its own, and inventing one
            # here is what CF-0158 exists to undo. Say so instead.
            lo_t, hi_t = 0.0, narration_length.HARD_CEILING_SECONDS
            target_notes.append(
                f"duration target: the channel's band could not be derived here "
                f"(no patterns/validate_patterns.py above this checkout, or a tail "
                f"longer than the floor of the band), so the plan is judged on the "
                f"{hi_t:.0f}s ceiling alone and carries no floor")
        else:
            lo_t, hi_t = derived
            if budget:
                tail, tail_key = narration_length.tail_seconds(budget)
                target_notes.append(
                    f"duration target {lo_t:.2f}-{hi_t:.2f}s is derived (CF-0158): the "
                    f"channel's finished-video band minus its {tail:.3f}s tail"
                    + (f" ({tail_key})" if tail_key else " (the channel names no tail)"))
            else:
                target_notes.append(
                    f"duration target {lo_t:.2f}-{hi_t:.2f}s is the factory's whole-video "
                    f"band: with no --channel there is no tail to subtract, so the floor "
                    f"is the one a video with no ending at all would have (CF-0158)")

    # CF-0158: the gate's ceiling is on the finished VIDEO - voice plus the
    # channel's tail - while the band above is on the narration. They were
    # the same number only while the target band was (wrongly) applied to the
    # voice track. Adding the tail back keeps the property CF-0087 wanted -
    # the ceiling is the upper target bound and not a second constant, so a
    # channel moving its range moves the gate with it - and on example-film
    # 54.833 + 5.167 lands back on exactly 60.
    ceiling = narration_length.total_seconds(hi_t, budget)

    # CF-0087: the narration-length gate, before any asset is probed. Batch
    # 2026-09-03T2037Z had this exact number printed as `DURATION OFF TARGET
    # (+2.1s)` at the bottom of a plan that was then rendered; a total (voice
    # + the channel's tail) over the ceiling is now a refused plan, same as a rejected
    # asset. Over the channel's 55s target but under the ceiling stays what it
    # was - a line on stderr - and the record goes into plan["duration"] for
    # 05-video-editor.json either way.
    narration = narration_length.judge(
        duration, budget, args.estimated_seconds, ceiling=ceiling)
    if narration["verdict"] == "reject":
        refuse_plan(args, plan_refusal.GATE_NARRATION_CEILING, "NARRATION OVER CEILING",
                    narration_length.report_lines(narration), story=story,
                    exit_code=narration_length.REJECT_EXIT_CODE)

    # CF-0293: the floor of the same measurement, refused in the same place and
    # by the same machinery. The band's 45s floor still only warns (CF-0158 -
    # the fix for a short video is more substance, which nothing downstream can
    # invent, so refusing there would only spend renders on the way to the same
    # hand-back); under the channel's hard floor - 30 s, the user 2026-09-20 -
    # that argument stops holding and the plan is not written at all. The
    # verdict is the root's (`judge_video_length()`); nothing is re-derived
    # here, and a channel that states no hard floor yields no `too_short` and
    # therefore no refusal.
    band = narration.get("video_length")
    if band and band.get("verdict") == narration_length.VIDEO_TOO_SHORT_VERDICT:
        refuse_plan(args, plan_refusal.GATE_NARRATION_FLOOR,
                    narration_length.VIDEO_TOO_SHORT_HEADLINE,
                    narration_length.report_lines(narration), story=story,
                    exit_code=narration_length.REJECT_EXIT_CODE)

    style = args.style or story.get("style", "stills")
    aspect = f"{args.width}:{args.height}"

    # CF-0127: the second plane, decided before the layout it changes. An
    # applied underlay takes underlay_layer.SECONDARY_HEIGHT of the frame
    # off the bottom of `main`; every other answer leaves `secondary` null,
    # which is what every plan before this layer carried.
    underlay_result = build_underlay_layer(args, story, duration)

    # Declared before the loop because the `side_by_side` halves are framed
    # against the main zone this describes, not against the whole frame.
    layout = {"main": {"fit": "cover"},
              "secondary": underlay_layer.layout_secondary(underlay_result)}

    blocks, notes, rejected, degraded_blocks = [], [], [], []
    # CF-0435: {(block, shot key): {soft rule}} this plan's own frame found -
    # priced beside the resolver's record (`shot_score.plan_findings`).
    weak_seen = {}
    # CF-0436: {(block, shot key): {presentation mode}} - the pictures this
    # plan shows blur_fill / luma_lift; the rule a mode removes is not priced.
    presented = {}
    # The box a blur_fill picture is fitted into: the insert box (the main
    # zone ending a gap above the caption band, captionBand.js insertBox()).
    present_box = meme_captions.insert_box(
        {"output": {"width": args.width, "height": args.height},
         "layout": layout})

    def present(target, info, probe_path, record, i, shot_key, where=""):
        return present_picture(target, info, probe_path, record, present_box,
                               presented, notes, i, shot_key, where)

    def gate_asset(i, asset, qc, shot_key, where=""):
        asset_gate(rejected, weak_seen, notes, i, asset, qc, shot_key, where)
    # CF-0330: the gates that warn rather than refuse, as records - the
    # preflight's (read from this video's work directory, where
    # `script_anchors.py preflight --out` left it) and this planner's own.
    warnings = plan_refusal.collect_warnings(Path(args.output).resolve().parent)
    for w in warnings:
        print(plan_refusal.warning_line(w), file=sys.stderr)
    # CF-0158: where the band in `duration.target` came from - derived,
    # overridden or underivable. The first plan whose floor moves with
    # ending.mp4 should say so in the artifact, not only on stderr.
    notes.extend(target_notes)

    # CF-0071: one place every former blocks.append() site (renamed to
    # emit_block() just above) funnels through, so a delivered proof insert
    # (this loop iteration's `block_insert`) is merged onto whichever block
    # dict that site builds without touching all seven call sites
    # individually. Late-binding closure: `block_insert` is reassigned every
    # iteration, and this reads whatever it is set to at call time, not at
    # definition time.
    proof_entries = []
    # CF-0689: what stops a graphic being drawn, per block - refused below
    # with the rejected assets, once every block is final.
    graphic_refusals = []
    graphic_lang = own_graphic_plan.lang_of(load_channel_cfg(args))
    # CF-0690: an `api_chat` graphic is held to the record of its call - the
    # channel's `api_demo` block and the protocols its orders name, read once.
    chat_config, chat_protocols = api_chat_context(args, story)
    # CF-0190: the key the blooper marker is written under, read off the
    # channel's own block rather than hardcoded (blooper_gate.marker_field()).
    # Needed here, before any block is emitted, because the marker rides on the
    # storyboard block and the gate below reads it off the *plan* block.
    blooper_field = blooper_gate.marker_field(
        blooper_gate.relaxation(load_channel_cfg(args)))
    block_marker = None
    # CF-0150: the same late-binding pair for the resolver's supply fact -
    # whether the storyboard block carries one at all, and what it is.
    has_supply = False
    block_supply = None

    def emit_block(d):
        """Append a block, with the CF-0071 proof insert (if any) for this
        storyboard block merged in additively - `insert` sits beside
        whatever `asset` the block already has, never replacing it
        (inserts/proof.json's `degradation.never_substitute`). One place so
        every one of this loop's several append sites carries a delivered
        proof the same way, including CF-0067's meme layer later.

        CF-0190's blooper marker rides along the same way and for the same
        reason - it is written on the storyboard block by whoever marked the
        material, and the borders are measured on the plan block. Copied
        verbatim, including a malformed one: this function is not the place
        that decides what a marker means (blooper_gate.marker_state() is), and
        dropping an unreadable one here would hide it from the record."""
        if block_insert:
            d = {**d, "insert": block_insert}
        if block_marker is not None:
            d = {**d, blooper_field: block_marker}
        # CF-0150: the resolver's supply fact, carried onto the plan block
        # unread, exactly like the marker above. Copied by key *presence*,
        # never by truthiness: `null` there means "the pool delivered for this
        # anchor" and is as much of an answer as a code is, while an absent
        # key means the storyboard predates the fact. Defaulting one to the
        # other is the whole failure this field exists to end.
        if has_supply:
            d = {**d, "candidate_supply": block_supply}
        # CF-0278: the length of what this one-shot block was offered, by
        # presence like the supply fact - absent means "not recorded".
        if "length_supply" in sb:
            d = {**d, "length_supply": sb["length_supply"]}
        blocks.append(d)

    # --- CF-0041: what was ordered against what is actually in the plan.
    #
    # Read here, before the first boundary is written, because CF-0245's
    # hold-band trim below needs the pattern's own band and the band lives in
    # the factory root's pattern file, not in the order (the order carries the
    # single drawn value, the file carries the band it was drawn from). It is
    # still read before the assetless and two-source gates, which is what
    # CF-0138 needed of it: the gate has to know whether this pattern
    # tolerates an insert at all before it refuses.
    order = {
        "pattern_id": story_rhythm.get("pattern_requested", rhythm.DEFAULT_ORDER["pattern_id"]),
        "rhythm_id": story_rhythm.get("rhythm_requested", rhythm.DEFAULT_ORDER["rhythm_id"]),
        "parameters": story_rhythm.get("parameters"),
    }
    order = rhythm.normalize_order(order)
    pattern = load_pattern(order["pattern_id"])

    # CF-0245: a block held past the top of the pattern's hold band is trimmed
    # to the top and the remainder goes to the next block - here, before the
    # loop, so that every boundary written below (and the CF-0249 freeze gate,
    # the layers, the punches and the cadence the pattern verdict is taken on)
    # sees one set of numbers. Refused far more often than applied, and each
    # refusal says which of the conditions failed, with the numbers.
    hold_trims = trim_to_hold_band(story["blocks"], pattern, duration,
                                   degraded=set(degrade_map))
    notes.extend(t["note"] for t in hold_trims)

    for i, sb in enumerate(story["blocks"]):
        lo, hi = sb["word_range"]
        # Anchor-resolved storyboards carry explicit times: a block there spans
        # from its anchor word to the next anchor, which is not the same thing as
        # a word range.
        if "_start" in sb and "_end" in sb:
            start, end = sb["_start"], sb["_end"]
            if i == len(story["blocks"]) - 1:
                end = duration
        else:
            start = words[lo]["start"]
            # The last block runs to the end of the audio so the picture never
            # dies before the voice does.
            end = duration if i == len(story["blocks"]) - 1 else words[hi]["end"]

        # CF-0031: a per-block degradation (fed in from qc_render.py's
        # frozen_blocks(), see --degrade-block above) is decided before the
        # plan's overall style, and only touches the one flagged index. A
        # block dropped straight to typographic needs no asset at all, same
        # as the whole-plan case below - it just applies to one block instead
        # of every block.
        degrade_target = degrade_reason = None
        if i in degrade_map:
            degrade_target, degrade_reason = degrade_map[i]

        original_kind = sb.get("asset_kind", "still")

        # CF-0071: a proof insert sits beside asset_kind, never replacing it
        # (inserts/proof.json's `storyboard_contract`/`degradation.never_
        # substitute`) - so it is resolved once here, ahead of the asset_kind
        # branches below, and merged onto whatever block those branches build
        # through emit_block(). A missing or gate-failing proof degrades only
        # the insert, never the block's own asset.
        block_insert = None
        # CF-0190: whatever this storyboard block says about being somebody
        # else's blooper, carried onto the plan block unread. `None` when the
        # key is absent, which is every block the factory writes today.
        block_marker = sb.get(blooper_field)
        # CF-0150: whether this storyboard block was built by a resolver that
        # knows the supply fact, and what it said.
        has_supply = "candidate_supply" in sb
        block_supply = sb.get("candidate_supply")

        insert = sb.get("insert")
        if insert and insert.get("kind") == "proof":
            proof_entry, block_insert = build_proof_insert(insert, i)
            proof_entries.append(proof_entry)
            if not block_insert:
                notes.append(
                    f"block {i}: proof requested but not delivered - "
                    + "; ".join(proof_entry["gate_failures"] or ["capture missing"]))

        # CF-0050: a `side_by_side` opening - two clips in one block, stacked,
        # so the axis of the comparison is visible before it is named. Handled
        # ahead of everything below because it is the one block with more than
        # one asset, and each half is framed against the half's own geometry
        # rather than against the 9:16 frame.
        if original_kind == "split":
            if style == "typographic" or degrade_target == "typographic":
                notes.append(
                    f"block {i}: the side-by-side opening was flattened to the "
                    f"assetless rung - the comparison it states is gone with it")
                emit_block({"start": round(start, 3), "end": round(end, 3),
                               "intent": sb.get("intent", ""),
                               "asset": {"kind": "procedural"}})
                if degrade_target == "typographic":
                    degraded_blocks.append({"index": i, "from": original_kind,
                                            "to": "typographic",
                                            "reason": degrade_reason})
                continue
            if degrade_target == "still":
                notes.append(
                    f"block {i}: --degrade-block asked to drop the side-by-side "
                    f"opening to a still, ignored - a frozen comparison is not "
                    f"one rung down from a moving one, it is a different opening")
            half_w, half_h = split_half_size(args.width, args.height, layout)
            half_aspect = f"{half_w}:{half_h}"
            halves = []
            for h in sb["split"]:
                # CF-0075: a half is a sequence of pictures (`cuts`) - distinct
                # clips back to back, then at most a short held frame. A
                # storyboard from before that carries one picture per half and
                # is read as one cut spanning the block.
                cuts_in = h.get("cuts") or [{**h, "at": 0.0,
                                             "seconds": round(end - start, 3)}]
                framed = []
                for k, c in enumerate(cuts_in):
                    cut_kind = c.get("kind", "clip")
                    # A held frame is its own probe; a clip is judged by a
                    # frame out of it, exactly as a single-asset clip block is.
                    probe_path = c["asset"]
                    grab_failure = None
                    if cut_kind == "clip":
                        probe_path = str(Path(args.output).parent /
                                         f"_probe_{i}_{h['side']}_{k}.png")
                        grab_failure = probe_frame(c["asset"], PROBE_OFFSET, probe_path,
                                                   seconds=c.get("seconds"))
                    # Both are judged at the clip ceiling: a held frame is a
                    # frame of a shot the resolver already accepted under it,
                    # and judging it as a photograph rejects it for being
                    # exactly as dark as the shot it came from (CF-0041).
                    info = grab_failure or inspect_asset(
                        probe_path, half_aspect, args.min_short_side,
                        args.min_coverage, CLIP_MAX_BLACK,
                        card=bool(c.get("is_card", h.get("is_card"))),
                        caption_crop=c.get("crop_bottom"),
                        frame_before_crop=c.get("frame_before_crop"))
                    if cut_kind == "clip":
                        Path(probe_path).unlink(missing_ok=True)
                    for r in info["qc"].get("relaxations", []):
                        notes.append(f"block {i} ({h['side']}): gate relaxed - {r}")
                    waive_wide_place(info, c.get(shot_score.FIELD), notes, i,
                                     f" ({h['side']})")
                    gate_asset(i, c["asset"], info["qc"], c.get("shot"),
                               f" ({h['side']})")
                    framed.append({"kind": cut_kind, "src": c["asset"],
                                   "start_seconds": 0,
                                   "from_seconds": round(float(c.get("at", 0.0)), 3),
                                   "seconds": round(float(c["seconds"]), 3),
                                   "held_frame": bool(c.get("held_frame")),
                                   "shot": c.get("shot"),
                                   **framing(info)})
                first = framed[0]
                static = sum(c["seconds"] for c in framed if c["held_frame"] or
                             c["kind"] != "clip")
                halves.append({"side": h["side"],
                               # The first picture's fields on the half itself:
                               # what SplitLayer.jsx and qc_render.py read when
                               # there is one picture, and the shape every
                               # reader of a half knew before CF-0075.
                               **{k: v for k, v in first.items() if k != "from_seconds"},
                               "held_frame": static > 0,
                               "half": {"width": half_w, "height": half_h},
                               "cuts": framed,
                               "motion_seconds": round(end - start - static, 3),
                               "static_seconds": round(static, 3)})
                notes.append(
                    f"block {i}: side {h['side']} framed for a {half_w}x{half_h} "
                    f"half (not the 9:16 frame) - {len(framed)} picture(s), keeps "
                    f"{info['roi_coverage']:.0%} of its subject at zoom "
                    f"{info.get('zoom', 1.0)}"
                    + (f" - held frame for {static:.2f}s, nothing more on this "
                       f"side was long enough to carry the opening (ceiling "
                       f"{rhythm.OPENING_MAX_STATIC_SECONDS}s, CF-0075)"
                       if static > 0 else ""))
            emit_block({
                "start": round(start, 3),
                "end": round(end, 3),
                "intent": sb.get("intent", ""),
                "asset": {"kind": "split", "seam_px": SPLIT_SEAM_PX,
                          "sides": halves},
                # CF-0075: the run the opening was laid over - what
                # rhythm.opening_report() measures the block against.
                "opening_run_seconds": sb.get("opening_run_seconds"),
                **carry_rhythm(sb),
            })
            continue

        # CF-0120: a swing block cut from several distinct shots of one side -
        # pictures one after another inside a single crossing of the axis, as
        # against `split`'s two at once. Handled here, beside `split`, because
        # it is the other block with more than one asset; each cut is framed
        # against the full 9:16 frame like any ordinary clip, since it *is* an
        # ordinary clip that happens to share a block with the next one.
        if original_kind == "sequence":
            cuts_in = sb.get("cuts") or []
            if style == "typographic" or degrade_target == "typographic" \
                    or not cuts_in:
                notes.append(
                    f"block {i}: the multi-shot swing block was flattened to "
                    f"the assetless rung - the side it was cut for has no "
                    f"picture left")
                emit_block({"start": round(start, 3), "end": round(end, 3),
                            "intent": sb.get("intent", ""),
                            "asset": {"kind": "procedural"}})
                if degrade_target == "typographic":
                    degraded_blocks.append({"index": i, "from": original_kind,
                                            "to": "typographic",
                                            "reason": degrade_reason})
                continue
            lift_failures = {}
            if degrade_target == "still":
                # One rung down the CF-0031 chain. CF-0549: the cut QC found
                # stuck stops moving - a frame lifted out of its own clip, by
                # the hold rule - and the other cuts keep playing; with no cut
                # named, the block keeps its first picture and stops moving.
                # Never a *different* shot and never one of its own a second
                # time - the rung below this is typographic, which is where a
                # block with nothing watchable in it belongs (CF-0120: no
                # repeats to patch a hole).
                cuts_in, degraded_rec, lift_failures = degrade_sequence_cuts(
                    cuts_in, frozen_cut_map.get(i), end - start,
                    Path(args.output).parent, i)
                degraded_blocks.append({"index": i, "from": original_kind,
                                        "to": "still", "reason": degrade_reason,
                                        **degraded_rec})
                notes.append(
                    f"block {i}: degraded sequence -> still "
                    + (f"on cut(s) {degraded_rec['cuts']} QC found stuck, the "
                       f"other cuts keep moving"
                       if degraded_rec["cuts"] != "all" else
                       "on the whole block (no cut named), its first picture")
                    + "; frame(s): " + ", ".join(
                        f"cut {r.get('cut')} {r.get('rule') or r.get('from')}"
                        + (f" at {r['at']}s" if "at" in r else "")
                        for r in degraded_rec["frames"])
                    + f" ({FROZEN_CUT_TASK})")
            framed = []
            for k, c in enumerate(cuts_in):
                cut_kind = c.get("kind", "clip")
                is_card_cut = bool(c.get("is_card", sb.get("is_card")))
                fit = delivery_fit(is_card_cut)
                # A clip is judged by a frame out of it; a held frame is its
                # own probe. Both at the clip ceiling, for the reason the
                # single-asset branch below spells out - the frame was lifted
                # from a shot the resolver already accepted under it.
                probe_path = c["asset"]
                grab_failure = lift_failures.get(k)
                if cut_kind == "clip":
                    probe_path = str(Path(args.output).parent /
                                     f"_probe_{i}_seq_{k}.png")
                    grab_failure = probe_frame(
                        c["asset"], PROBE_OFFSET, probe_path,
                        seconds=float(c["seconds"]))
                info = grab_failure or inspect_asset(
                    probe_path, aspect, args.min_short_side, args.min_coverage,
                    CLIP_MAX_BLACK, card=is_card_cut,
                    caption_crop=c.get("crop_bottom"),
                    frame_before_crop=c.get("frame_before_crop"), fit=fit)
                for r in info["qc"].get("relaxations", []):
                    notes.append(f"block {i} (cut {k}): gate relaxed - {r}")
                waive_wide_place(info, c.get(shot_score.FIELD), notes, i,
                                 f" (cut {k})")
                gate_asset(i, c["asset"], info["qc"], c.get("shot"), f" (cut {k})")
                framed.append({"kind": cut_kind, "src": c["asset"],
                               "start_seconds": 0,
                               "from_seconds": round(float(c.get("at", 0.0)), 3),
                               "seconds": round(float(c["seconds"]), 3),
                               "held_frame": bool(c.get("held_frame")),
                               "shot": c.get("shot"),
                               "fit": fit,
                               **({"degraded_still": c["degraded_still"]}
                                  if c.get("degraded_still") else {}),
                               **framing(info)})
                # CF-0436: the cut's presentation, on its probe, before the
                # probe is gone (a card cut is not presented - it is a card).
                if not is_card_cut and not probe_missing(info):
                    present(framed[-1], info, probe_path, c.get(shot_score.FIELD),
                            i, c.get("shot"), f" (cut {k})")
                if cut_kind == "clip":
                    Path(probe_path).unlink(missing_ok=True)
            static = sum(c["seconds"] for c in framed
                         if c["held_frame"] or c["kind"] != "clip")
            notes.append(
                f"block {i}: side {sb.get('side')!r} is cut from "
                f"{len(framed)} picture(s) inside one crossing (CF-0120)"
                + (f" - the last one is held for {static:.2f}s, the side had no "
                   f"further distinct shot" if static > 0 else ""))
            emit_block({
                "start": round(start, 3),
                "end": round(end, 3),
                "intent": sb.get("intent", ""),
                "asset": {"kind": "sequence", "cuts": framed,
                          # The first picture's fields on the asset itself, so
                          # a reader that knows a block has one src still gets
                          # one - the same shape SplitLayer's halves keep.
                          **{k: v for k, v in framed[0].items()
                             if k not in ("kind", "held_frame",
                                          "from_seconds", "seconds")}},
                **carry_rhythm(sb),
            })
            continue

        # CF-0689: a graphic the factory draws from the script's facts. Like a
        # card it has no file, no rights, no asset gate and no crop - and it is
        # neither a card nor the `typographic`/`procedural` rung: it is the
        # video's footage, checked again here against shared/own_graphic.py
        # (a bad order refuses the plan, it is never swapped for anything).
        # Under a whole-video typographic drop it stays `own_graphic`:
        # Video.jsx draws own-graphic blocks over the procedural ground.
        if original_kind == own_graphic_plan.KIND:
            gid = sb.get("graphic_id")
            graphic = sb.get("graphic")
            found = own_graphic_plan.problems(gid, graphic, chat_config, chat_protocols)
            graphic_refusals.extend(f"block {i} ({gid}): {f}" for f in found)
            if style == "typographic":
                notes.append(f"block {i}: own graphic {gid} kept through the whole-video "
                             f"typographic drop - it is drawn over the procedural ground, "
                             f"never flattened into it (CF-0689)")
            if degrade_target:
                notes.append(f"block {i}: --degrade-block asked to drop own graphic {gid} "
                             f"to {degrade_target}, ignored - a graphic is not degraded to "
                             f"a still or to type; a frozen one is a fault of its own "
                             f"(qc_render, CF-0689)")
            emit_block({
                "start": round(start, 3),
                "end": round(end, 3),
                "intent": sb.get("intent", ""),
                "asset": own_graphic_plan.asset(graphic, gid, sb.get("graphic_offset"),
                                                graphic_lang),
                **carry_rhythm(sb),
            })
            continue

        # CF-0041: a `card` is a deliberate text frame the factory draws
        # itself. There is no external file, so there are no rights to clear,
        # no asset gate to pass and no crop to compute (CF-0012 fixed this
        # class): it goes down the same assetless branch `typographic` uses,
        # but it is emphatically *not* that rung. `typographic` is where a
        # block lands when the footage failed; a card is where a block was
        # aimed on purpose, and `style_delivered` cannot tell intent from
        # shortage unless the two are different kinds.
        if original_kind == "card":
            if style == "typographic":
                # The whole video dropped to the assetless rung, which flattens
                # everything - Video.jsx renders the procedural background for
                # the composition, not per block. Recorded, because a card that
                # was drawn and then flattened is not the same as no card.
                notes.append(f"block {i}: deliberate card was flattened by the "
                             f"whole-video typographic drop")
                emit_block({"start": round(start, 3), "end": round(end, 3),
                               "intent": sb.get("intent", ""),
                               "asset": {"kind": "procedural"}})
                continue
            if degrade_target:
                notes.append(f"block {i}: --degrade-block asked to drop a card to "
                             f"{degrade_target}, ignored - a card has no asset that "
                             f"could fail a gate, so it has nothing to degrade from")
            card = sb.get("card") or {}
            emit_block({
                "start": round(start, 3),
                "end": round(end, 3),
                "intent": sb.get("intent", ""),
                "asset": {"kind": "card",
                          "card_kind": card.get("kind", "count_card"),
                          "text": card.get("text", "")},
                **carry_rhythm(sb),
            })
            continue

        if original_kind == "typographic":
            # CF-0085: the resolver already put this block on the assetless
            # rung - an ordered rhythm's segment that no candidate could fill,
            # kept at the planner's own bounds rather than merged into the
            # previous block. It is a degradation by shortage, not by choice
            # (that is `card`, above), so it is recorded in `degraded_blocks`
            # exactly like a --degrade-block drop: write_batch_metadata.py
            # reports the mix, verify_rhythm() sees the missing picture.
            if degrade_target:
                notes.append(
                    f"block {i}: --degrade-block asked to drop an unfilled block "
                    f"to {degrade_target}, ignored - it is already on the "
                    f"assetless rung")
            emit_block({
                "start": round(start, 3),
                "end": round(end, 3),
                "intent": sb.get("intent", ""),
                "asset": {"kind": "procedural"},
                "rhythm_role": sb.get("rhythm_role"),
            })
            degraded_blocks.append({
                "index": i, "from": "unfilled", "to": "typographic",
                "reason": sb.get("unfilled_reason")
                          or "no usable footage for this block (CF-0085)"})
            continue

        if degrade_target == "typographic":
            # A block dropped to the assetless rung has no picture left, so it
            # carries no side and no shot: `alternate` reads that as a hole in
            # the alternation rather than as a swing that happened.
            emit_block({
                "start": round(start, 3),
                "end": round(end, 3),
                "intent": sb.get("intent", ""),
                "asset": {"kind": "procedural"},
                "rhythm_role": sb.get("rhythm_role"),
            })
            degraded_blocks.append({"index": i, "from": original_kind,
                                    "to": "typographic", "reason": degrade_reason})
            continue

        # `typographic` is the floor of the degradation chain, so it must build
        # with no external asset at all - otherwise the chain has no bottom and
        # a job with nothing to show fails outright instead of degrading.
        if style == "typographic":
            emit_block({
                "start": round(start, 3),
                "end": round(end, 3),
                "intent": sb.get("intent", ""),
                "asset": {"kind": "procedural"},
            })
            continue

        # CF-0131: a clip block that outruns its own clip is a decided defect,
        # and it is the most expensive one the renderer can be handed. The
        # CF-0052 demo render held a 1.30s clip over a 31.6s block: ~948
        # OffthreadVideo frames past the end of the file, ~250s of a 29-minute
        # render, every one of them decoding and drawing the same held last
        # frame. qc_render.py already fails exactly this block afterwards
        # (frozen_clip_blocks, reason "playback ran out"); there is nothing
        # for the render to find out, so the block drops a rung here instead.
        #
        # The threshold is not a new one. clip_shortfall() *is* the condition
        # freeze_verdict() uses - every probe qc_render.py would take is
        # already on the held frame - moved into common.py so the planner
        # cannot drift from the gate. In particular a clip block is *allowed*
        # to outrun its clip a little (the Sequence is a crossfade longer than
        # the clip, and QC accepts that by design); only a block with no live
        # probe left anywhere in it degrades.
        #
        # Degrade rather than reject: the drop is one rung on the CF-0031
        # chain, this block only, and it is written into `degraded_blocks`
        # where write_batch_metadata.py already reports it. Rejecting would
        # send an otherwise good video to needs-you whole, over a block whose
        # picture is a still either way - the only difference being whether
        # the still costs 948 video frames to draw.
        #
        # CF-0249: and the same arithmetic answers the *partial* freeze, which
        # is the one that reached a viewer. A block does not have to be frozen
        # end to end to be a defect - dtf-st-louis block 0 ran 0.0-9.4s on a
        # 4.03s clip, so it played real footage for 4 seconds and then held one
        # frame for 5.37, and every rule that looks for "no live probe
        # anywhere" (clip_shortfall above, max() in the gate) says it is fine.
        # How far a block outruns its clip is known here, from two numbers
        # already in hand, before a single frame is rendered - so the cheapest
        # place to say it is here, and common.held_tail() says it by the same
        # number the post-render gate fails a frozen stretch by.
        clip_seconds = None
        if original_kind == "clip" and degrade_target is None:
            clip_seconds = media_duration(sb["asset"])
            probe_block = {"start": start, "end": end,
                           "asset": {"start_seconds": sb.get("asset_start_seconds", 0)}}
            shortfall = clip_shortfall(probe_block, clip_seconds)
            hold = held_tail(probe_block, clip_seconds)
            if shortfall is not None:
                degrade_target = "still"
                degrade_reason = (
                    f"the clip runs {clip_seconds:.2f}s but the block plays it "
                    f"to {shortfall + clip_seconds:.2f}s - every frame of this "
                    f"block would be the held last one (CF-0131)")
                notes.append(
                    f"block {i}: degraded clip -> still before the render - "
                    f"{shortfall:.2f}s short of the footage it asks for; "
                    f"rendering it as a clip would have decoded "
                    f"{shortfall:.2f}s of frozen video for no picture")
            elif hold is not None:
                degrade_target = "still"
                degrade_reason = (
                    f"the clip runs {clip_seconds:.2f}s but the block is "
                    f"{end - start:.2f}s long, so its last {hold:.2f}s would be "
                    f"the held last frame - over the {MAX_HELD_RUN:.2f}s the "
                    f"motion gate fails a frozen stretch by (CF-0249)")
                notes.append(
                    f"block {i}: degraded clip -> still before the render - "
                    f"the block plays {hold:.2f}s past the end of its clip, "
                    f"which the render would have shown as a frozen frame and "
                    f"qc_render.py would have failed afterwards")

        kind = "still" if degrade_target == "still" else original_kind
        asset = {"kind": kind, "src": sb["asset"]}
        if kind == "clip":
            asset["start_seconds"] = sb.get("asset_start_seconds", 0)

        # A clip is judged by a representative frame: the same gate that keeps
        # an unusable photo out has to keep an unusable shot out too. A block
        # degraded from clip to still reuses this same extracted frame as its
        # *delivered* image, rather than the whole video re-sourcing separate
        # still photography - same visual choice, one rung simpler.
        #
        # CF-0121 (one sample, one use) is satisfied here by construction, and
        # it is worth writing down why, because "clip -> still" sounds like a
        # second showing of the shot. The frame is lifted from *this block's
        # own* clip and replaces it: the sample goes from moving to motionless
        # in the one place it was already going to be, so the viewer still sees
        # it once. Degradation never goes and finds a still of some other
        # block's shot - it has no candidate pool and never picks a sample.
        # Which is also why the rule cannot be dodged this way: since the
        # resolver's ledger let that shot through exactly once, there is no
        # second block for a still of it to appear in. The rung below (still ->
        # typographic) drops the picture altogether.
        probe_path = sb["asset"]
        grab_failure = None
        if original_kind == "clip" and kind in ("clip", "still"):
            frame_name = (f"_degraded_still_{i}.png" if degrade_target == "still"
                         else f"_probe_{i}.png")
            probe_path = str(Path(args.output).parent / frame_name)
            # CF-0131: PROBE_OFFSET into the clip, except on a clip whose whole
            # problem is that it is too short to hold one - a seek past the end
            # returns no frame at all, and the block would be rejected for
            # having no picture rather than degraded to the one it has.
            probe_at = sb.get("asset_start_seconds", 0) + PROBE_OFFSET
            grab_failure = probe_frame(sb["asset"], probe_at, probe_path,
                                       seconds=clip_seconds)
            if degrade_target == "still":
                asset["src"] = probe_path

        if kind in ("still", "clip"):
            # CF-0041: a held frame is a still by construction only - it is one
            # frame of a clip the resolver already accepted, and the clip passed
            # under the looser ceiling because dark cinematography is normal in
            # footage. Judging it at the stills ceiling rejects the frame for
            # being exactly as dark as the shot it was lifted from, and takes
            # the whole plan down with it (a 46%-black frame of an accepted
            # night interior did precisely that on the first hold run).
            # CF-0131 extends the same exemption to a frame this script just
            # lifted off a clip on the way down a rung: it is a still by
            # construction only, exactly like a held frame, and judging it at
            # the stills ceiling would reject the plan for the shot being as
            # dark as the clip the resolver already accepted - turning a
            # degradation that saves the video into one that fails it.
            degraded_off_clip = original_kind == "clip" and degrade_target == "still"
            ceiling = (CLIP_MAX_BLACK
                       if kind == "clip" or sb.get("held_frame") or degraded_off_clip
                       else args.max_black)
            # CF-0047: `is_card` is the storyboard's note that this footage is
            # a title/end card out of someone else's trailer. Distinct from
            # `asset_kind == "card"` handled far above, which is a card this
            # factory draws and which never reaches this branch at all.
            is_card_shot = bool(sb.get("is_card"))
            # CF-0104: the same delivery-mode choice the QC gate below needs,
            # decided once here rather than twice - `inspect_asset()` tells
            # qc_asset.py explicitly instead of leaving it to rederive the
            # same answer from `card`.
            fit = delivery_fit(is_card_shot)
            info = grab_failure or inspect_asset(
                probe_path, aspect, args.min_short_side, args.min_coverage, ceiling,
                card=is_card_shot, caption_crop=sb.get("crop_bottom"),
                frame_before_crop=sb.get("frame_before_crop"), fit=fit)
            waive_wide_place(info, sb.get(shot_score.FIELD), notes, i)  # CF-0352
            asset.update(framing(info))
            asset["fit"] = fit
            # CF-0535: a face clip's window over the span it is shown, by the
            # intent - not off the one frame at PROBE_OFFSET.
            if (kind == "clip" and original_kind == "clip" and not is_card_shot
                    and not probe_missing(info)
                    and info.get("qc", {}).get("usable", True)):
                reframe_faces(asset, info, probe_path, sb["asset"],
                              sb.get("asset_start_seconds", 0) or 0,
                              end - start, clip_seconds, sb.get("intent", ""),
                              (args.width, args.height), i, notes)
            size = asset["source_size"]

            # CF-0077: a card whose gate tool hung is already refused below;
            # measuring its text survival would be one more Vision wait on
            # an asset that is not going anywhere.
            if is_card_shot and not probe_missing(info):
                # Fit the whole card instead of cropping into it. `cover`
                # takes the largest 9:16 window it can and centres it on the
                # ROI, which for a wide card means throwing away the ends of
                # the wordmark; `contain` letterboxes and keeps all of it.
                # zoom and focus are reset with it: both exist to push a
                # `cover` window toward a subject, and applying either to a
                # contained frame would start cutting the lettering again.
                px_size = (size["width"], size["height"])
                cover_kept, _ = smart_crop.text_survival(
                    probe_path, px_size, (asset["focus"]["x"], asset["focus"]["y"]),
                    asset["zoom"], args.width, args.height, "cover")
                asset["zoom"] = 1.0
                asset["focus"] = {"x": 0.5, "y": 0.5}
                kept, n_text = smart_crop.text_survival(
                    probe_path, px_size, (0.5, 0.5), 1.0, args.width, args.height,
                    asset["fit"])
                # What the delivered framing does to the text, and what the
                # crop it replaced would have done. The second number is the
                # evidence for the first, per block, on the real frame - not
                # a claim carried over from the task file.
                asset["card_text_kept"] = None if kept is None else round(kept, 3)
                asset["card_text_kept_if_cropped"] = (
                    None if cover_kept is None else round(cover_kept, 3))
                if kept is None:
                    notes.append(
                        f"block {i}: flagged a title/end card but Vision reads no "
                        f"text on its probe frame - fitted whole anyway, which "
                        f"cannot crop anything, but nothing here confirms it is a "
                        f"card")
                elif kept < MIN_CARD_TEXT_KEPT:
                    # Not reachable through `contain`, which shows the entire
                    # source by construction. It is a guard on the geometry
                    # rather than on the footage: if this ever fires, the
                    # framing above stopped agreeing with AssetLayer.jsx.
                    rejected.append((i, sb["asset"], [
                        f"card framing: the delivered frame keeps only {kept:.0%} "
                        f"of the card's text (< {MIN_CARD_TEXT_KEPT:.0%})"]))
                else:
                    notes.append(
                        f"block {i}: title/end card fitted whole (letterboxed) - "
                        f"keeps {kept:.0%} of its {n_text} text region(s); the 9:16 "
                        f"crop it replaces would have kept {cover_kept:.0%}")

            # CF-0327: the shot's own inset panel, before the probe frame is
            # thrown away. After the card branch above on purpose - a card is
            # already delivered `contain`, which cuts nothing - and before the
            # clip's probe is unlinked, which is the last moment this frame
            # exists to be looked at.
            # CF-0436: blur_fill / luma_lift, decided on this probe - before
            # the panel framing (a picture shown whole cuts no panel).
            if not is_card_shot and not probe_missing(info):
                present(asset, info, probe_path, sb.get(shot_score.FIELD), i,
                        sb.get("shot"))
            panel = frame_the_panel(asset, probe_path, info, args.min_coverage,
                                    (args.width, args.height))
            if panel:
                asset["panel"] = panel
                if panel.get("moved"):
                    notes.append(
                        f"block {i}: the shot carries an inset panel across "
                        f"{panel['x0']:.2f}-{panel['x1']:.2f} of its width and the "
                        f"framing kept {panel['focus_x_before']:.3f} of it cut off - "
                        f"focus moved to {asset['focus']['x']:.3f}, which delivers it "
                        f"{panel['outcome']} (subject kept {panel.get('subject_kept')})")
                elif panel["verdict"] == "unresolved":
                    notes.append(
                        f"block {i}: the shot's inset panel "
                        f"({panel['x0']:.2f}-{panel['x1']:.2f} of its width) is delivered "
                        f"{panel['visible']:.0%} cut off and no framing that fixes it "
                        f"keeps the subject at the {args.min_coverage:.0%} floor - left "
                        f"as framed, for qc_render's panel gate to judge (CF-0327)")

            if kind == "clip":
                Path(probe_path).unlink(missing_ok=True)

            if degrade_target == "still":
                degraded_blocks.append({"index": i, "from": original_kind,
                                        "to": "still", "reason": degrade_reason})

            # CF-0047: a gate that let something through on a relaxation says
            # so in the plan, next to the block it applied to. The rule is the
            # one already stated for --min-coverage and --min-short-side: a
            # relaxed floor is recorded, never silently applied.
            for r in info["qc"].get("relaxations", []):
                notes.append(f"block {i}: gate relaxed - {r}")

            if not info["qc"]["usable"]:
                gate_asset(i, sb["asset"], info["qc"], sb.get("shot"))
            elif is_card_shot:
                # roi_coverage is not this block's framing question: the card
                # is delivered whole, and card_text_kept above is what says so.
                pass
            elif info["qc"]["upscale_factor"] > 1.5:
                notes.append(
                    f"block {i}: source is {info['qc']['short_side']}px wide and "
                    f"is upscaled {info['qc']['upscale_factor']}x - accepted "
                    f"because the floor was relaxed to {args.min_short_side}px, "
                    f"expect visible softness")
            elif (info["roi_coverage"] < 0.85
                  and not wide_place.waived(sb.get(shot_score.FIELD))):
                notes.append(
                    f"block {i}: crop keeps {info['roi_coverage']:.0%} of the "
                    f"subject" + (f" - below the default {MIN_COVERAGE:.0%} floor, "
                    f"accepted only because it was relaxed to {args.min_coverage:.0%}"
                    if info["roi_coverage"] < MIN_COVERAGE else
                    " - acceptable, but not the whole frame"))

        if sb.get("cut_origin") == "moment":
            # CF-0106: the QC report says which frame this block was cut
            # from, so the frame a comparison check stands on is traced to
            # the clip's real head - not to the head of the shot it was
            # matched in, which for a marked shot is a different picture.
            notes.append(
                f"block {i}: cut from the shot's moment_at={sb['moment_at']:.2f}s "
                f"(clip starts at {sb['cut_at']:.2f}s of {sb.get('shot')}), "
                f"not from the shot's head")

        emit_block({
            "start": round(start, 3),
            "end": round(end, 3),
            "intent": sb.get("intent", ""),
            "asset": asset,
            **carry_rhythm(sb),
        })

    punches = []
    for sb in story["blocks"]:
        for idx in sb.get("emphasis_words", []):
            if 0 <= idx < len(words):
                punches.append(round(words[idx]["start"], 3))

    if rejected:
        # A hard gate, as agreed: brak the agent can detect must not reach a
        # human. The caller substitutes another candidate and tries again, and
        # after its retry budget drops a rung down the degradation chain.
        # CF-0254: one line per rejected block, its failures folded into it -
        # the record's `reason` is one cell of the funnel's table, so the
        # nesting this used to print becomes "block N: file - a; b".
        refuse_plan(args, plan_refusal.GATE_ASSETS_REJECTED, "ASSETS REJECTED",
                    [f"block {i}: {path} - " + "; ".join(str(f) for f in failures)
                     for i, path, failures in rejected], story=story)
    # CF-0690: the chat's clock, scaled to the run of blocks it spans; a run
    # that cannot hold the whole answer 1.5 s is refused with the graphics.
    graphic_refusals.extend(own_graphic_plan.stamp_chat_timing(blocks))
    if graphic_refusals:
        # CF-0689: the backstop of the graphic rule (shared/own_graphic.py) -
        # the Content Researcher's gate should have stopped every one of
        # these; a graphic that slipped through is not drawn, and nothing is
        # drawn in its place.
        refuse_plan(args, plan_refusal.GATE_OWN_GRAPHIC, "OWN GRAPHIC REFUSED",
                    graphic_refusals,
                    notes=["a graphic draws only the script's values, each backed by its "
                           "claims (shared/own_graphic.py, CF-0689) - the script goes back "
                           "to the Content Researcher"],
                    story=story)

    # --- CF-0137: the last rung of the ladder. Every block is final at this
    # line, so this is the first moment the question "does any block ship
    # with no picture" can be answered - and it is asked before the two-source
    # gate and before every layer below, because a video that is not going to
    # be published should not pay for a vision call either.
    #
    # This is where rung 4 lives: rung 1 (a library insert, CF-0138) and rung
    # 2 (the one emergency shot repeat, CF-0137 / rhythm.EmergencyReuseBudget)
    # were climbed back in resolve_anchors.py, where the pool and the ledger
    # are; rung 3 is this gate returning `passed` because the channel switched
    # the rung on. Off - which is every channel, by default and on purpose -
    # the plan is not written at all. CF-0123 made that boolean deliberately:
    # the hole is there or it is not, and no share-of-runtime threshold is
    # invented to soften it.
    #
    # `qc_render.py` cannot do this job: it has never heard of degradation
    # (the word `degraded` does not occur in it) and it probes a rendered
    # file, so a procedural background reaching it means the render was
    # already paid for. Refusing here is what "visible before the render"
    # means.
    # --- CF-0041's `order` is built above the block loop now (CF-0245 needs
    # the pattern's hold band before the first boundary is written); it was
    # read here for CF-0138's reason - the insert layer has to know whether
    # this pattern tolerates an insert before the gate below refuses - and
    # earlier still satisfies that.

    # CF-0138: and this is where rung 1 stops being a comment. The gate above
    # is asked here, early, precisely so a doomed plan pays for no vision
    # call - but rung 1 (a library insert in the hole) is executed by the
    # meme layer, 150 lines below, which means asking the gate *only* here
    # refuses the plan before the rung it names has had its turn.
    #
    # The way out is not to move the gate down - that would hand every
    # refused video the full bill for the proof, meme and sound layers. It is
    # that the two goals only collide when the layer could actually change
    # the verdict, and whether it could is answerable for free:
    # `hole_fill_feasible()` reads two channel/pattern switches and the block
    # lengths - no library, no CLIP, no Vision. Not feasible (the layer is
    # off, the pattern refuses, a hole is under the 3s floor, more holes than
    # the insert budget) and the refusal happens right here, exactly as
    # CF-0137 wrote it, with nothing paid for. Feasible, and the refusal is
    # deferred to just below the meme layer and above the sound layer, and
    # re-asked there on blocks that may now carry a picture.
    #
    # So the expensive layers are paid for on a plan that will be refused in
    # one case only: the holes were fillable in principle and the library had
    # no picture clear of the M4 floors for them. That case is a real rescue
    # attempt, not a wasted one.
    assetless_gate = build_assetless_rung_gate(args, blocks, degraded_blocks, style)
    deferred_for_inserts = None
    if not assetless_gate["passed"]:
        deferred_for_inserts = build_hole_fill_probe(args, blocks, degraded_blocks,
                                                     order["pattern_id"])
    runlog.annotate(assetless_rung=(
        f"{'pass' if assetless_gate['passed'] else 'WARN'} "
        f"{assetless_gate['block_count']} block(s)"))
    if not assetless_gate["passed"] and not deferred_for_inserts["feasible"]:
        # CF-0139: the deficit carries the insert rung's record too, and here
        # that record is "it never ran, and this is why" - the probe's own
        # verdict, in the shape `meme.hole_fill` has everywhere else. Not a
        # synthesised `refused[]`: the layer refused nothing, it was never
        # offered the holes, and filling the list with outcome codes derived
        # from the probe would tell the rotation that configuration is why
        # this video has no picture, when the reason is that it has no
        # footage. Absent codes are read as prose; invented codes are read as
        # fact, and they would beat the prose that is true.
        #
        # CF-0330 (the user, 2026-09-23): a warning, not a refusal. The holes
        # stay on the procedural rung - `asset.kind: procedural`, painted by
        # Video.jsx for the block's span - and the plan is written.
        # CF-0337: since the topic-footage rung (resolve_anchors.py) a hole
        # gets here only when no source of the topic has an unused usable shot
        # left, and on a channel with the rung off qc_render fails the render
        # (`assetless_blocks`): the answer is material (CF-0338).
        probe_fill = {**meme_layer.empty_hole_fill(),
                      "holes": deferred_for_inserts.get("holes") or [],
                      "at_floor": deferred_for_inserts.get("at_floor") or [],
                      "note": f"the insert rung did not run: "
                              f"{deferred_for_inserts['reason']}"}
        deficit = assetless_rung.write_deficit(args.output, assetless_gate, hole_fill=probe_fill)
        assetless_gate["total_blocks"] = len(blocks)
        warn_plan(args, warnings, plan_refusal.GATE_ASSETLESS_RUNG, "ASSETLESS BLOCKS",
                  list(assetless_rung.report_lines(assetless_gate))
                  + [f"library insert (CF-0138, rung 1): not possible here - "
                     f"{deferred_for_inserts['reason']}"],
                  numbers=assetless_numbers(assetless_gate), deficit=deficit, story=story)
        deferred_for_inserts = None
    if deferred_for_inserts is not None:
        notes.append(
            f"assetless-block gate deferred past the insert layer (CF-0138): "
            f"{deferred_for_inserts['reason']}")

    # --- CF-0118: the gate of two independent footage sources. Here because
    # the blocks are final at this line (every degradation and every
    # rejection has been decided) and everything below is the expensive
    # part - the proof/meme/sound layers and their vision calls - which a
    # refused plan should not pay for. `measure` (the default, and what the
    # channel says today) records the verdict and rejects nothing; that is
    # item 3 of the task, not timidity: on the batches on disk the pass rate
    # is far under 50 %, so the pool widens before the gate bites. `enforce`
    # refuses the plan the way a rejected asset does - stderr and exit 2.
    gate_record = build_two_source_gate(args, blocks)
    runlog.annotate(two_source_gate=(
        f"{'pass' if gate_record['passed'] else 'fail'} "
        f"{gate_record['count']}/{gate_record['required']} "
        f"({gate_record['mode']})"))
    if not gate_record["passed"] and gate_record["mode"] == source_gate.MODE_ENFORCE:
        refuse_plan(args, plan_refusal.GATE_TWO_SOURCE, "TWO-SOURCE GATE FAILED",
                    source_gate.report_lines(gate_record),
                    deficit=write_gate_deficit(args.output, gate_record), story=story)
    if not gate_record["passed"]:
        # CF-0330: `measure` is this gate's warning, and a measured failure
        # now writes the same record the other warned gates do, so a reader of
        # `videos[].warnings` sees every gate the video went past.
        warn_plan(args, warnings, plan_refusal.GATE_TWO_SOURCE, "TWO-SOURCE GATE FAILED",
                  source_gate.report_lines(gate_record),
                  numbers={"count": gate_record.get("count"),
                           "required": gate_record.get("required"),
                           "canonical_ids": list(gate_record.get("canonical_ids") or []),
                           "mode": gate_record.get("mode")},
                  story=story)

    # --- CF-0567: the proof-quote cap and the demo's own footage. Here, on
    # the final blocks and before the expensive layers, as the gate above.
    # A channel without `proof_quotes` (ExampleFilm, ExampleScience) and a
    # pattern other than `demo` are not measured at all.
    quote_record = build_proof_quote_cap(args, blocks, order["pattern_id"])
    if quote_record["applies"]:
        runlog.annotate(proof_quote_cap=(
            f"{'pass' if quote_record['passed'] else 'REFUSED'} "
            f"{quote_record['quote_count']} quote(s) {quote_record['quote_seconds']:.1f}s"))
        for line in proof_quote_cap.report_lines(quote_record):
            print(line, file=sys.stderr)
    if not quote_record["passed"]:
        gate = (plan_refusal.GATE_PROOF_QUOTE_CAP
                if quote_record["gate"] == plan_refusal.GATE_PROOF_QUOTE_CAP
                else plan_refusal.GATE_DEMO_OWN_CAPTURE)
        refuse_plan(args, gate,
                    "PROOF-QUOTE CAP BROKEN" if gate == plan_refusal.GATE_PROOF_QUOTE_CAP
                    else "DEMO WITHOUT ITS OWN RECORDING",
                    [f"[{r['code']}] {r['text']}" for r in quote_record["refusals"]],
                    notes=["a vendor's clip is a short quote beside our own recording, "
                           "never the base (channels/<id>/footage-origin.json "
                           "`proof_quotes`, the root's docs/tech-footage.md)"],
                    story=story)

    # --- CF-0190: the blooper relaxation's two borders. Here, beside the two
    # gates above, for the three reasons that put them here: the blocks are
    # final at this line (every degradation and every rejection is decided, so
    # a fragment's span is the span the viewer gets), the words are aligned and
    # on the same timeline, and everything below is the expensive part a
    # refused plan should not pay for.
    #
    # A block with no marker is not measured against these numbers at all - the
    # material's kind is never guessed from a description, a tag or a filename.
    # A marked block with no relaxation in force is refused: the marker is the
    # editor's own word that this fragment is third-party studio material, and
    # with the channel's block absent, off or illegal nothing in this factory
    # permits it to ship. The relaxation is what carried such material past the
    # rights-holder verdict in the Compliance Checker (part 2); these borders
    # are what it was granted for, and this is the only place they become a
    # refusal.
    blooper_record = build_blooper_gate(args, blocks, words)
    runlog.annotate(blooper_gate=(
        f"{'pass' if blooper_record['passed'] else 'REFUSED'} "
        f"{blooper_record['marked_count']} marked fragment(s)"))
    if not blooper_record["passed"]:
        refuse_plan(args, plan_refusal.GATE_BLOOPER, "BLOOPER BORDERS",
                    blooper_gate.report_lines(blooper_record),
                    deficit=blooper_gate.write_deficit(args.output, blooper_record),
                    story=story)
    if blooper_record["marked_count"]:
        for line in blooper_gate.report_lines(blooper_record):
            print(f"  {line}", file=sys.stderr)

    degraded_indices = [d["index"] for d in degraded_blocks]
    rhythm_delivered, rhythm_reasons = rhythm.verify_rhythm(
        order, blocks, degraded_indices, story_rhythm.get("anchor_count"))
    # CF-0192: one judgement, three shapes of it. `pattern_shortfalls` is the
    # machine-readable list, `pattern_delivered` the id-or-None the Analyst
    # joins on, `pattern_reasons` the sentences for `deviations`.
    pattern_short = rhythm.pattern_shortfalls(
        order, blocks, rhythm_delivered, pattern)
    # CF-0314: not `if pattern_short` - `rhythm.delivery_denying_shortfalls()`
    # is the one place that says which shortfall unsays the claim and which
    # one only stands beside it (a pace over a `floor_drawn` ceiling: measured,
    # recorded, and not a defect the user's 2026-09-22 decision recognises).
    # `pattern_delivered_fully` below still answers "was there anything at
    # all", so the two fields together never say less than the list does.
    pattern_delivered = (None
                         if rhythm.delivery_denying_shortfalls(pattern_short)
                         else order["pattern_id"])
    pattern_reasons = [s["note"] for s in pattern_short]

    # CF-0270: the gate, on the judge's own answer and nothing else - see the
    # note above pattern_ceiling_break(). Here rather than lower because this
    # is the first line where all three of its inputs exist (`hold_trims` from
    # before the loop, `degraded_blocks` and `pattern_short` from it), and the
    # proof, meme and sound layers below are the expensive half of this file:
    # a plan that will be refused should not pay for them - CF-0137's reason,
    # kept.
    #
    # `--degrade-block` is how a post-QC degradation reaches this stage
    # (see the module docstring), so a non-empty one means an attempt has
    # already been rendered and its mp4 is on disk. That mp4 is the render
    # this refusal is about, and `supersedes_video` is what stops it winning
    # over the refusal in 05-video-editor.json (plan_refusal.merge /
    # superseded_video_ids). Before the first render the flag is absent and
    # the ordinary rule holds: zero attempts, no mp4, nothing to argue with.
    #
    # CF-0303 adds the second cause on the same call: when nothing was degraded
    # and the *layout* is over the ceiling, the storyboard's own
    # `rhythm.hold_ceiling` record is what the gate reads. Before the first
    # render that record is the only evidence there is - it was written from the
    # real alignment, which is the difference from the Researcher's pre-TTS pass.
    ceiling = pattern_ceiling_break(pattern_short, hold_trims, degraded_blocks,
                                    story_rhythm.get("hold_ceiling"),
                                    story_rhythm.get("block_band_cap"),
                                    story_rhythm.get("rhythm_built"),
                                    story=story, blocks=blocks)
    # CF-0433: a block over the hold band's top - degraded or laid out that
    # way - is `score.hold_band_exceeded`, not a refusal. The record is kept
    # on the plan (`rhythm.hold_ceiling_break`) because it says *why* the block
    # is long; the block-count band is still asked on its own, since the hold
    # record used to answer first and hide it.
    #
    # CF-0447 (the user, 2026-09-30): what cadence_band_break() returns - a
    # drawn band's top broken, more blocks (or a faster rate) than the pattern
    # allows - does not refuse either. It is `score.block_band_exceeded`, 2 a
    # block over the top, cap 10, charged once, here, on the plan's own count
    # (the Researcher's 6b price is its estimate before the TTS, in 03, and is
    # not in this video's log). The record rides on the plan as
    # `rhythm.block_band_break` and is the deficit of a score under N.
    hold_break = None
    if ceiling and ceiling.get("cause") != CEILING_CAUSE_CADENCE:
        hold_break = ceiling
        ceiling = cadence_band_break(pattern_short, story_rhythm.get("block_band_cap"),
                                     story_rhythm.get("rhythm_built"),
                                     story=story, blocks=blocks)
    band_break = ceiling
    # CF-0453: blocks the resolver built shorter than the 1.6s a picture
    # needs to read - a price, never a refusal of their own. The root's table
    # does not carry the rule yet (CF-0320: the user signs it); until it does
    # the plan notes what it would cost at the proposed price and the score
    # leaves it out.
    too_short = too_short_findings(story, notes)
    # CF-0903: the strip the plan's blur_fills add up to, past the signed
    # allowance of score.narrow_strip_on_blur - the blur_fills the pool's
    # record alone asked for go back to the crop this plan's probe found
    # keeping the subject; their low_framing is priced again below.
    strip_budget = take_back_strips(blocks, presented, notes, args.height)
    # CF-0433: the prices of this stage, summed on the score model (CF-0432).
    # The plan carries the block as `plan["score"]`; under N it is the refusal
    # the three rules used to be each on their own.
    plan_score = _score.score_block(
        rhythm.pace_findings(pattern_short)
        + rhythm.hold_band_findings(blocks, pattern)
        # CF-0490: the last block that still speaks, over the band's top - per
        # second over (signed 2026-10-02); on top of hold_band_exceeded's flat
        # price for the same block. Only once the root's table carries it.
        + (rhythm.tail_over_band_top_findings(blocks, pattern, words)
           if _score.has_rule(rhythm.SCORE_TAIL_OVER_BAND_TOP) else [])
        # CF-0583: the anchor whose picture arrives ahead of the fact's first
        # word, per second of its lead over 2 s in this voice (CF-0547, signed
        # 2026-10-06). Only once the root's table carries it, and only with
        # the script (`--script`/`--script-id`), where the fact and anchors are.
        + (fact_anchor.findings(fact_anchor.script_of(args.script, args.script_id), words)
           if _score.has_rule(fact_anchor.RULE) else [])
        + rhythm.block_band_findings(pattern_short, len(blocks))
        + similarity
        + too_short
        # CF-0435: every weak shot on screen - the resolver's record on the
        # storyboard (the cut clip's probes, `on_topic: false`) and what this
        # plan's own frame found - one finding per rule per distinct shot.
        + shot_score.plan_findings(story.get("blocks"), extra=weak_seen,
                                   presented=presented)
        # CF-0436: a picture shown blur_fill / luma_lift pays the
        # presentation instead of the rule it removes.
        + shot_score.presentation_findings(blocks))
    # CF-0434: the plan stage of the video's score log (score_log.py,
    # `<plan stem>.score.json`). Recorded before the refusal below, so a plan
    # refused under N leaves its log too; a rebuild replaces this stage and
    # forgets the render and QC of the plan it replaces.
    score_line = score_log.record(args.output, score_log.STAGE_PLAN,
                                  plan_score.get("findings") or [],
                                  script_id=refusal_script_id(args, story)).get("line")
    if score_line:
        plan_score["line"] = score_line
        print(f"  SCORE after plan: {score_line}", file=sys.stderr)
    if _score.refuses(plan_score):
        plan_score_refusal(args, plan_score, hold_break or band_break or pace_floor_record(
                               pattern_short, story_rhythm.get("block_band_cap"),
                               story_rhythm.get("rhythm_built"), story=story,
                               blocks=blocks),
                           story, supersedes_video=bool(args.degrade_block))
    # CF-0057: the rhythm can be present and still not fully executed. A run of
    # one declared side that came out as a single 15s frame is such a case -
    # the alternation crossed the axis everywhere the script did, so nulling
    # `rhythm_delivered` would be a lie, and leaving only the pattern's cadence
    # deviation says the rhythm was fine, which is the other lie. These two
    # fields are the second half of the record, the way CF-0041 split
    # `pattern_requested` from `pattern_delivered`.
    shortfalls = rhythm.rhythm_shortfalls(order, blocks)
    rhythm_record = {
        "pattern_requested": order["pattern_id"],
        "pattern_delivered": pattern_delivered,
        # CF-0192 item 4: why it was not, in a code a machine can join on.
        # `null` used to carry two meanings at once - "delivered, nothing to
        # say" and "not delivered, reason unrecorded" - and the assignment
        # registry (CF-0040/CF-0049) reads this field to decide whether the
        # rotation it is guarding actually happened. `None` here now means
        # exactly one thing: the pattern was delivered.
        "pattern_not_delivered": rhythm.pattern_not_delivered_code(pattern_short),
        # CF-0192 item 3: the pattern's own shortfall list, symmetric with
        # CF-0057's `rhythm_shortfalls`. This is what stops the two fields
        # contradicting each other: `rhythm_delivered_fully` speaks about the
        # rhythm and nothing else, `pattern_delivered_fully` about the pattern
        # and nothing else, and each has the list its verdict was made from.
        # `bunker-venice-ovation` (2026-09-09) is the plan that showed why:
        # `rhythm_delivered_fully: true` beside `pattern_delivered: null` read
        # as two answers to one question, and it was two answers to two.
        "pattern_shortfalls": pattern_short,
        "pattern_delivered_fully": not pattern_short,
        # CF-0245: every block that was held past the top of the drawn hold
        # band, and what the editor did about it - trimmed to the band top
        # with the remainder handed on, or refused, with the numbers the
        # refusal was decided on. Beside `pattern_shortfalls` because the two
        # answer one question together: an entry here with `applied: false`
        # and a `hold_outside_band` shortfall above is the montage saying it
        # could not fix this one without freezing a frame (CF-0249). An empty
        # list means no block was over the band at all.
        "hold_band_trims": hold_trims,
        # CF-0276: the same band, asked one stage earlier - what the *layout*
        # could not bring under the pattern's ceiling, carried from the
        # storyboard so the three records read in the order the video was
        # built. `hold_ceiling.breaches` empty beside a `hold_outside_band`
        # shortfall means the montage left the band after the cut (a
        # degradation, a stretch) and CF-0245/CF-0270 own it; a breach here
        # means the boundaries never fitted, and the remedy is upstream of
        # this file. `null` on a plan built before the layout answered.
        "hold_ceiling": story_rhythm.get("hold_ceiling"),
        # CF-0433: a hold-band break that no longer refuses - why the block
        # is long (degradation / layout); its price is in plan["score"].
        "hold_ceiling_break": hold_break,
        # CF-0447: a drawn block band's top broken, priced and not refused
        # (`score.block_band_exceeded`) - the CF-0310 cadence record, with
        # CF-0428's `supply` / `fixable_by_anchors`. `null` when inside it.
        "block_band_break": band_break,
        # CF-0433: a pace under the pattern's floor, priced and not refused -
        # the CF-0310/CF-0428 record (`supply`, `fixable_by_anchors`) of
        # whether more anchors could lift it. `null` when the pace is on it.
        "pace_below_floor": pace_floor_record(
            pattern_short, story_rhythm.get("block_band_cap"),
            story_rhythm.get("rhythm_built"), story=story, blocks=blocks),
        "rhythm_requested": order["rhythm_id"],
        "rhythm_delivered": rhythm_delivered,
        "rhythm_built": story_rhythm.get("rhythm_built", order["rhythm_id"]),
        "anchor_count": story_rhythm.get("anchor_count"),
        "parameters": story_rhythm.get("parameters"),
        "opening_requested": story_rhythm.get("opening_requested"),
        "opening_delivered": story_rhythm.get("opening_delivered"),
        "cadence": rhythm.cadence(blocks),
        "alternation": (rhythm.alternation_report(blocks)
                        if order["rhythm_id"] == "alternate" else None),
        "side_runs": (rhythm.side_run_report(
                          blocks, order["parameters"]["key_frame_hold_seconds"])
                      if order["rhythm_id"] == "alternate" else None),
        # CF-0120: which crossings were cut from several shots of their side,
        # in block order. Beside `side_runs` rather than inside it because
        # write_batch_metadata.py carries it into `05-video-editor.json` as a
        # field of its own - the Analyst's question ("where is a side more
        # than one picture") is asked of the video, not of a run.
        "swing_block_shots": rhythm.swing_block_shots(blocks),
        # CF-0136: how much of this video had a picture at all -
        # `picture_blocks`, `assetless_blocks`, `longest_assetless_run_seconds`
        # and the runs behind them. Written on every rhythm, unlike `side_runs`
        # and `alternation`, because a footage shortage is not a property of
        # the cadence it lands in; and written whole, including on the plans
        # where nothing is missing, for the same reason `side_runs` is - the
        # Analyst (CF-0023) must not have to re-derive it from the block list.
        "picture": rhythm.picture_report(
            blocks, order["parameters"]["key_frame_hold_seconds"]),
        # CF-0137: the video's one emergency shot repeat - which block, which
        # shot, where else that shot is on screen. Written whole on every
        # rhythm, including the (usual) plans that spent none, because "this
        # video needed no repeat" is the fact the Analyst is comparing
        # against when one does.
        "emergency_reuse": rhythm.emergency_reuse_report(blocks),
        "rhythm_shortfalls": shortfalls,
        # True only when the rhythm is in the video *and* nothing about it fell
        # short. False when either half failed - the two fields above say which.
        # CF-0192: about the *rhythm*, and never about the pattern. That was
        # the ambiguity behind "two fields about one thing give opposite
        # answers": a plan can execute `even` perfectly and still not be the
        # pattern it was assigned, because the pattern is a cadence band and
        # `even` asks nothing of cadence. `pattern_delivered_fully` above is
        # this field's opposite number and the only one that speaks for the
        # pattern.
        # CF-0136: "nothing about it fell short" now includes the picture that
        # never arrived, not only the picture that arrived and stood still. The
        # accepted price, decided in CF-0123: on a batch like 2026-09-03T2037Z,
        # where all four videos had degraded blocks, this is False almost
        # always. That is the field telling the truth, not a regression.
        "rhythm_delivered_fully": bool(rhythm_delivered) and not shortfalls,
        "held_frames": [i for i, b in enumerate(blocks) if b.get("held_frame")],
        "deviations": (story_rhythm.get("notes", []) + rhythm_reasons
                       + [s["note"] for s in shortfalls]
                       + [r for r in pattern_reasons if r not in rhythm_reasons]),
    }

    # CF-0118: `rhythm_shortfalls` is deliberately left alone here, and that
    # is the whole point of the field. It is CF-0057's record of *rhythm*
    # deficits - the list the Analyst reads to tell a rhythm that is present
    # but standing still from one that is missing - and a plan that reached
    # this line is a plan the gate did not refuse. In `measure` (the default,
    # and what every channel says today) the gate reports and returns
    # nothing, so a `two_source_gate` entry here would be a deficit nobody
    # was asked to act on, silently lengthening the shortfall list of every
    # plan built off a single-source pool - which is exactly what it did to
    # the real `wren-hollow-lockhart` run CF-0057 is pinned against.
    #
    # The gate's verdict is not lost by that: it is on
    # plan["two_source_gate"] (and videos[].two_source_gate in
    # 05-video-editor.json) in every mode, pass or fail, with its own stderr
    # line. And the one path where the deficit really is the return value -
    # `enforce` - never reaches this line at all: it exits 2 above, having
    # written the same CF-0057-shaped record to plan.two-source-gate.json,
    # which is where a refused script reads what it has to fix.

    # CF-0050: what the cold open cost. Measured off the alignment rather than
    # taken from a flag - the beat exists because the narration really starts
    # late in the wav that is about to be mixed, and the words are what know
    # that. It is spent *from* the narration band, never added to it - and
    # since CF-0158 that band is derived from the channel rather than the
    # literal 35-60 this line used to name: a video
    # that opens on a held frame for 0.7s has 0.7s less narration in it, and
    # writing the cost down is what stops that showing up later as a script
    # that mysteriously came in short.
    lead_silence = leading_silence(args.voice)
    if story_rhythm.get("opening_delivered") == "cold_frame":
        notes.append(
            f"block 0 is a cold frame: the picture is up from 0.00s and the "
            f"first word lands at {lead_silence:.2f}s. That beat is spent from "
            f"the {lo_t:.1f}-{hi_t:.1f}s budget - {duration - lead_silence:.2f}s "
            f"of narration in a {duration:.2f}s video")

    # CF-0071: plan["proof"] is written by proof_layer.apply_to_plan() below -
    # the requested/delivered pair, the provenance records and the capture
    # telemetry of the script's proofs[]. `proof_entries` (a storyboard that
    # hand-declared `insert: {kind: "proof"}` blocks, the 54e524b path) ride
    # beside it as storyboard_inserts, never inside the pair: they were not
    # requested by the script.

    # CF-0067: the meme layer, after every block is built and the pattern is
    # known - a meme is an overlay on a finished block, not a rung of the
    # chain above, so it runs last and touches only the `insert` field of the
    # block it lands on (meme_layer.apply_to_plan). The channel switch, the
    # pattern gate, M1/M2 and the asset gate are all in meme_layer.py; here
    # the plan only supplies what those rules read.
    # CF-0071: the proof layer first - a proof has one place (the block
    # where the voice says the production fact) and the meme, which may go anywhere its beat overlaps,
    # must see that block as taken. apply_to_blocks() writes `insert` onto
    # the placed block now, so meme_layer.candidate_blocks skips it.
    proof_result = build_proof_layer(args, words, blocks, order["pattern_id"])
    proof_layer.apply_to_blocks(blocks, proof_result)
    notes.extend(proof_result["notes"])

    # --- CF-0193: the CF-0137 ladder for a proof that was ordered and did not
    # arrive. Before this the ladder had no last rung at all: a request whose
    # beat could not be located ended `beat_not_found` with `attempted: []`,
    # the note went into the plan and the video shipped as if nothing had been
    # asked for. Two of the three proofs ever ordered ended exactly there.
    #
    # The rungs, and where each one is:
    #   1 the equal-length window            meme_layer._window_match()
    #   2 the drift-tolerant pass, CF-0193   meme_layer._drift_match()
    #   3 ship without the proof, in writing  proof_shortfalls(), decision
    #     `ship_without_proof` - a code and the evidence on the record, which
    #     is what "the layer no longer goes silent" means for the reasons the
    #     factory can see and not fix from here (channel off, no free block,
    #     the capture chain walked and empty, the alignment losing words the
    #     script does have)
    #   4 this: the refusal. REFUSAL_OUTCOMES are the two that say the request
    #     points at something that does not exist - no production fact in the
    #     script (CF-0243), or a fact whose beat is not in the script either. No rung below can supply
    #     what is not there, and a video built on a script contradicting itself
    #     is not a video to publish.
    #
    # Here rather than lower for CF-0137's reason exactly: the meme and sound
    # layers below are the expensive part, and a plan that will be refused
    # should not pay for them.
    proof_beat = proof_beat_gate.judge(proof_result["proof_requested"],
                                       proof_result["proof_delivered"])
    runlog.annotate(proof_beat=("REFUSED" if not proof_beat["passed"] else
                                f"pass {len(proof_beat['shortfalls'])} shortfall(s)"))
    if not proof_beat["passed"]:
        refuse_plan(args, plan_refusal.GATE_PROOF_BEAT, "PROOF REQUEST POINTS AT NOTHING",
                    proof_beat_gate.report_lines(proof_beat["refusals"]),
                    deficit=proof_beat_gate.write_deficit(args.output, proof_beat["refusals"]),
                    story=story)
    meme_result = build_meme_layer(args, words, blocks, degraded_blocks, order["pattern_id"])
    # CF-0138: the overlays go onto the blocks now, not at plan-assembly time,
    # because the gate re-asked immediately below reads the blocks. (The
    # proof layer has written its own this way since CF-0071;
    # meme_layer.apply_to_plan() writes the same dicts again later and is
    # safe to call after this.)
    meme_layer.apply_to_blocks(blocks, meme_result)
    notes.extend(meme_result["notes"])

    # CF-0138: the deferred refusal, re-asked with rung 1 spent. Here and not
    # lower: the sound layer below is the last expensive thing in this file,
    # and a plan that is going to be refused should not pay for it either.
    if deferred_for_inserts is not None:
        assetless_gate = build_assetless_rung_gate(args, blocks, degraded_blocks, style)
        filled = meme_result.get("hole_fill") or {}
        runlog.annotate(assetless_rung=(
            f"{'pass' if assetless_gate['passed'] else 'WARN'} after insert rung, "
            f"{len(filled.get('filled') or [])} hole(s) filled"))
        for rec in filled.get("filled") or []:
            notes.append(f"block {rec['block_index']}: a library insert "
                         f"({rec['asset_id']}) stands in for footage that never "
                         f"arrived - nobody asked for it (CF-0138, rung 1)")
        if not assetless_gate["passed"]:
            # CF-0139: `filled` is the layer's own record of these same
            # blocks, and its `refused[]` codes are the machine-readable half
            # of why the hole is still a hole. On a plan that is written they
            # also ride `meme.hole_fill`; the deficit keeps them beside the
            # gate's record for the rotation, which reads that file.
            # CF-0330: a warning, not a refusal - see the first ask above.
            deficit = assetless_rung.write_deficit(args.output, assetless_gate, hole_fill=filled)
            assetless_gate["total_blocks"] = len(blocks)
            warn_plan(args, warnings, plan_refusal.GATE_ASSETLESS_RUNG, "ASSETLESS BLOCKS",
                      list(assetless_rung.report_lines(assetless_gate))
                      + [f"library insert (CF-0138, rung 1): "
                         f"{filled.get('note') or 'the layer placed nothing'}"]
                      + [f"block {rec['block_index']}: {rec['outcome']} - {rec['note']}"
                         for rec in filled.get("refused") or []],
                      numbers=assetless_numbers(assetless_gate, filled),
                      deficit=deficit, story=story)
    # CF-0068: the sound layer, after the meme - a sound sits on a moment of
    # the voice, not on a block, and its block index is only recorded. It
    # writes `sound` on that block and plan["sound"]; build_soundtrack.py
    # mixes from plan["sound"]["placed"], nothing on the picture side reads it.
    sound_result = build_sound_layer(args, words, blocks, order["pattern_id"], duration)
    notes.extend(sound_result["notes"])
    if watermark_note:
        notes.append(watermark_note)
    if theme_note:
        notes.append(theme_note)

    person_record = person_shot_warnings(args, story, blocks, warnings)
    plan = {
        "style": style,
        "output": {"width": args.width, "height": args.height, "fps": args.fps},
        # CF-0329: derived, not typed. safe_area.py keeps the player's cut
        # apart from the player's overlay; the four numbers here are their sum.
        "safe_zones": safe_area.safe_zones(),
        "layout": layout,
        # CF-0212: the channel's display_name in capitals (what Watermark.jsx
        # draws), or null on a plan built without --channel - no mark rather
        # than some other channel's.
        "watermark": ({"text": watermark_text, "position": args.watermark_position}
                      if watermark_text else None),
        # CF-0572: the channel's on-screen theme (channels/<id>.json -> theme,
        # without picked/note) - every colour and face Video.jsx draws, or
        # null on a plan built without --channel, which the render refuses.
        "theme": plan_theme,
        # CF-0271: `bed_rotation` is the bed this video drew from the channel's
        # list, or `null` when the channel brings one file (or none). Written
        # on every plan, `null` included, for the reason `unresolved_anchors`
        # below is: `null` is this planner saying it looked, and an *absent*
        # key is a plan built before the rotation existed - which the mixer
        # refuses rather than choosing a bed of its own.
        # `audio.bed` is not this key: the mixer overwrites that one with what
        # it actually mixed.
        # CF-0423: `channel` is the channel this plan was built for, so the
        # render can build the mix for it (render_video.ensure_mix) instead of
        # rendering the bare voice when nobody ran build_soundtrack.py.
        "audio": {"src": str(Path(args.voice).resolve()), "duration": round(duration, 3),
                  "bed_rotation": build_bed_rotation(args, story),
                  "channel": args.channel},
        "words": [{"word": w["word"], "start": w["start"], "end": w["end"]} for w in words],
        # CF-0433: the score log of this stage (pace, hold band, similarity),
        # shared/score/score.py's block plus the findings it was taken from.
        # 6b (plan_check), 05 and the run summary read it here.
        "score": plan_score,
        "blocks": blocks,
        # CF-0903: the plan's strip seconds before and after the blur_fills
        # decided on the pool's record alone went back to the crop.
        "strip_budget": strip_budget,
        # CF-0290: the resolver's own record of the anchors it could not
        # picture, carried through unchanged so that `05-video-editor.json` -
        # and anyone auditing DoD ролика item 3 after the fact - can see it on
        # a video that shipped, instead of only in a work directory that is
        # deleted with the batch. `[]` is an answer ("this resolver looked and
        # found none"); an absent key means a plan from before this change.
        "unresolved_anchors": list(story.get("unresolved_anchors") or []),
        "punches": sorted(punches),
        "duration": {
            "target": [lo_t, hi_t],
            "actual": round(duration, 3),
            # CF-0050: the deviation is still judged on `actual`, because that
            # is how long the video is and the target is about the video. These
            # two say where the seconds went, so a cold open is legible as a
            # deliberate spend rather than as narration that went missing.
            "lead_silence": lead_silence,
            "spoken": round(duration - lead_silence, 3),
            "deviation": round(
                0 if lo_t <= duration <= hi_t
                else (duration - lo_t if duration < lo_t else duration - hi_t), 3),
            # CF-0087: voice + end card against the channel's target and the
            # ceiling, and the actual against the script's estimate. A plan
            # only exists with verdict "ok" or "warn" - "reject" never got here.
            "narration": narration,
        },
        "notes": notes,
        # CF-0330: every gate this video went past with a warning instead of a
        # refusal (the user, 2026-09-23) - `plan_refusal.warning()` records,
        # gate id, funnel code, sentence and numbers. `[]` on a plan nothing
        # warned about; write_batch_metadata.py carries it to
        # `videos[].warnings`.
        plan_refusal.WARNINGS_FIELD: warnings,
        # CF-0879: who the script names and which blocks still show a foreign
        # face under them (measure); null on a storyboard from before it.
        person_shot.RECORD: person_record,
        # CF-0031: which specific blocks were dropped a rung and why - fed
        # straight from --degrade-block, one entry per flagged index. Empty
        # on a clean run or on a whole-video --style drop (that path has no
        # per-block indices, only a plan-wide style change; write_batch_
        # metadata.py falls back to its own from/to reasoning for it).
        "degraded_blocks": degraded_blocks,
        # CF-0118: how many independent footage sources are on screen, which
        # ones, and what the alias table (CF-0080) collapsed to get there.
        # Written on every plan, pass or fail, in either mode: a plan that
        # does not say how many sources it drew on cannot be audited against
        # the policy it exists to satisfy.
        "two_source_gate": gate_record,
        # CF-0567: the vendor quotes on screen against the channel's
        # `proof_quotes` caps, and a demo's own footage. `applies: false` on a
        # channel with no caps and a pattern other than demo.
        proof_quote_cap.FIELD: quote_record,
        # CF-0137: whether any block shipped with no picture, and whether the
        # channel allows that at all. Written on every plan, pass or refusal
        # (a refusal has no plan file - its copy goes to
        # `plan.assetless-rung.json`), for the same reason the gate above is:
        # a plan that does not say it had a picture in every block cannot be
        # audited against the decision that says it must.
        "assetless_rung": assetless_gate,
        # CF-0190: which fragments claimed to be somebody else's blooper and
        # whether they stood inside the relaxation's borders. Written on every
        # plan, including the overwhelmingly common one where nothing is marked
        # at all (`marked_count: 0`), for the reason the two gates above are
        # written on every plan: a relaxation is recorded rather than hidden,
        # and a plan that does not say it was measured cannot be audited
        # against the decision that says it must be. A refusal has no plan file
        # - its copy goes to `plan.blooper-gate.json`.
        "blooper_gate": blooper_record,
        # CF-0041: the order, the cadence that came out of it, and the verdict.
        # Written on every run, including a run with no order at all - a plan
        # that does not say what rhythm it is cannot be learned from, and the
        # absence of an order is itself the `even` baseline, not a blank.
        "rhythm": rhythm_record,
        "qc_thresholds": {"min_short_side": args.min_short_side,
                          "min_coverage": args.min_coverage,
                          "max_black_stills": args.max_black,
                          "max_black_clips": CLIP_MAX_BLACK,
                          # CF-0327 / CF-0320: a refusal whose mode is
                          # configuration, not code. The channel says
                          # `video_editor.panel_in_frame.mode` and the plan
                          # carries it to qc_render, so that flipping the gate
                          # between `fail` and `warn` after `runlog gate-price`
                          # has measured it is one line in a channel file
                          # rather than a code change.
                          **panel_gate_thresholds(load_channel_cfg(args))},
    }
    # CF-0367: a storyboard re-cut with `resolve_anchors.py --exclude-candidate`
    # says so on the plan - which shots were excluded from which anchor and
    # what moved - so the attempt ledger can name the rebuild `recut:` and
    # the batch record can tell a re-cut from a first choice. Absent on a
    # storyboard nobody re-cut.
    if story.get("excluded_candidates"):
        plan["recut"] = {"excluded_candidates": story["excluded_candidates"],
                         **(story.get("recut") or {})}

    # CF-0127: plan["underlay"] (always) and plan["secondary_source"] + the
    # band in plan["layout"] (only when a loop was applied). First, because
    # it is the plane under everything else - and `layout` above already
    # carries the band, so this only records the answer that produced it.
    underlay_layer.apply_to_plan(plan, underlay_result)
    # CF-0071: `insert` onto each placed block (already there - see above),
    # plan["proof"] with the pair, the provenance and the capture telemetry.
    proof_layer.apply_to_plan(plan, proof_result, storyboard_inserts=proof_entries)
    # CF-0067: `insert` onto each placed block, plan["meme"] with the pair.
    meme_layer.apply_to_plan(plan, meme_result)
    # CF-0068: `sound` onto the block holding each anchor, plan["sound"] with the pair.
    sound_layer.apply_to_plan(plan, sound_result)
    # CF-0116 / CF-0186: plan["comparison_lines"] - our wording of the
    # video's production fact, and the badge naming its source, for the
    # window of the beat that speaks it. Last, because it reads the
    # finished plan: the blocks (which block the line comes up on), the
    # duration (the window is clipped to it) and the proof records (a
    # placed proof's `source_url` rides on the line, inserts/proof.json
    # capture_methods[rendered_quote].behaviour.url_placement). It writes
    # one field and changes no block; render_video.py hands the whole plan
    # to Remotion, so the composition reads it as props.
    try:
        comparison_result = build_comparison_lines(args, words, plan)
    except comparison_line.SourceBadgeError as e:
        refuse_plan(args, plan_refusal.GATE_SOURCE_BADGE, "SOURCE BADGE NOT PLANNED", [str(e)],
                    notes=["the badge names the publication, and nothing here invents a "
                           "name, truncates one or grows the anchor (CF-0164, "
                           "docs/source-badge-spec.md §§3, 7). A host that is no "
                           "publication at all goes in video_editor.comparison_line."
                           "platforms and costs the line its badge, not the plan "
                           "(CF-0166)."],
                    story=story, exit_code=narration_length.REJECT_EXIT_CODE)
    comparison_line.apply_to_plan(plan, comparison_result)
    notes.extend(comparison_result["notes"])

    # CF-0244: and now the proof cards learn how long they are up for. It has
    # to be here and not in the proof layer above: the card's window is the
    # part of its block the fact's line covers, and the line does not exist
    # until the call above has made it. A card is evidence for the sentence
    # the line is naming - when the line leaves, the block's own asset comes
    # back, and a card the line never covers is pulled rather than left on
    # the frame as a black screen with a document in it.
    notes.extend(proof_layer.bind_to_lines(plan))

    # CF-0117: plan["end_card"] and plan["duration"]["composition"] - the
    # channel's logo and signature phrase after the last word, and the
    # length of the composition that now contains them. Last of all: the
    # card starts where the narration ends, and it is the only thing here
    # that makes the video longer than its voice-over.
    try:
        card, card_notes = build_end_card(args, plan)
    except end_card.EndCardError as e:
        refuse_plan(args, plan_refusal.GATE_END_CARD, "END CARD NOT PLANNED", [str(e)],
                    notes=["the stance document is the channel's position and has one "
                           "address (CF-0063); nothing invents one here. A channel with no "
                           "signature phrase is not this case - that card is drawn without "
                           "one (CF-0186)."],
                    story=story, exit_code=narration_length.REJECT_EXIT_CODE)
    if card is not None:
        end_card.apply_to_plan(plan, card)
    notes.extend(card_notes)

    # CF-0664: whose footage is on screen and the credit some origins want
    # over it. After the end card: the overlays are clipped to the narration,
    # and the blocks are final (degradation and held re-cuts are done).
    credit_rows, credit_overlays, credit_notes = build_footage_credits(args, plan)
    footage_credits.apply_to_plan(plan, credit_rows, credit_overlays)
    notes.extend(credit_notes)
    # CF-0567: our own recordings on screen - no credit, but the page, the
    # host and the Space's licence stay on the record.
    own_rows, own_notes = build_own_captures(args, plan)
    plan[footage_credits.OWN_CAPTURES_FIELD] = own_rows
    notes.extend(own_notes)
    # CF-0689: the graphics the factory drew - no credit either, the record
    # of what each one says. Only on a plan that has one (Reel/Science plans
    # are unchanged).
    graphic_rows = own_graphic_plan.record(plan)
    if graphic_rows:
        plan[own_graphic_plan.FIELD] = graphic_rows

    # CF-0418: the share of the running time in pictures (cards, posters,
    # proof cards, whole-frame memes - a frame held from a video does not
    # count, the user's variant (a) of 2026-09-30). Here, last, because the
    # proof card's span is only final after bind_to_lines() and the running
    # time only after the end card. Both rules of the model that price it come
    # out of one count (still_share.measure): the soft `score.still_share`
    # joins the plan stage of the score log, the hard line refuses the plan
    # under its own gate before the render, into the writer's anchor loop.
    # CF-0859: a held picture past an observed hold top (explainer's emergent
    # band) - hold_band_exceeded, which the CF-0433 price above charges on a
    # drawn band only.
    held_frame_band_gate(args, plan, plan_score, story, pattern)
    still_share_gate(args, plan, plan_score, story)
    # CF-0465: a soft frame held still - warn until the price row is signed.
    held_soft_gate(args, plan, plan_score, story, notes=plan.get("notes"))
    # CF-0646: a thin strip, a headless body, a soft source stretched and
    # held - read as shown; warn until each row is signed.
    held_screen_gate(args, plan, plan_score, story, notes=plan.get("notes"))
    # CF-0481: a face held still out of a moving shot - priced since the user
    # signed the row on 2026-10-02 (CF-0490: -16/s over 12 s, cap 64); a
    # table without the signed row still only warns.
    held_motion_gate(args, plan, plan_score, story, notes=plan.get("notes"))
    # CF-0480: whose frames it holds, and whether the pool held the video.
    pool_holds_gate(args, plan, plan_score, story,
                    plan.setdefault(plan_refusal.WARNINGS_FIELD, []),
                    notes=plan.get("notes"))
    # CF-0794: the gates above add their prices to the plan stage after
    # CF-0433's refusal was asked - street-fighter (example-film
    # 2026-10-18T0841Z) went from over N to F · 36 on a thin picture and a
    # held face here, and its plan was written anyway. Asked again on the log
    # as it now stands; under N the plan is not written and the score's own
    # refusal is.
    late_score_stop(args, plan_score, story)

    # CF-0415: what this plan was built from, --degrade-block aside - the
    # render compares it with the previous render's to tell a rebuild that
    # only applied QC's own hint (a qc_degrade, not an attempt) from one that
    # also re-resolved, re-cut or changed a flag.
    plan["build_inputs"] = attempts.build_inputs(vars(args))
    json.dump(plan, open(args.output, "w"), indent=2)
    print(f"plan -> {args.output}  {len(blocks)} blocks, {duration:.2f}s, "
          f"{len(punches)} punches")
    print("  " + underlay_layer.report_line(underlay_result), file=sys.stderr)
    # CF-0244: off the plan and not off `proof_result`, because bind_to_lines()
    # above may have pulled a card the layer placed - and the line the operator
    # reads has to be the one the render will show.
    planned_proof = plan.get("proof") or {}
    for req, ans in zip(planned_proof.get("proof_requested") or [],
                        planned_proof.get("proof_delivered") or []):
        placed = ans["outcome"] in proof_layer.PLACED_OUTCOMES
        window = ((plan["blocks"][ans["block_index"]].get("insert") or {})
                  if placed and isinstance(ans.get("block_index"), int) else {})
        print(f"  PROOF {req['proof_id']}: {ans['outcome']}"
              + (f" - {ans['capture_method_used']} on block {ans['block_index']}"
                 if placed else "")
              + (f", card up {window['start_s']:.2f}-{window['end_s']:.2f}s "
                 f"({window['window_from']})" if window.get("start_s") is not None else ""),
              file=sys.stderr)
    for req, ans in zip(meme_result["meme_requested"], meme_result["meme_delivered"]):
        span = ans.get("span") or {}  # CF-0811: a meme laid over several blocks
        print(f"  MEME {req['beat_id']} ({req['intent']}): {ans['outcome']}"
              + (f" - {ans['asset_id']} on block {ans['block_index']}"
                 if ans["outcome"] == meme_layer.OUTCOME_PLACED else "")
              + (f", span blocks {span['blocks']} {span['start_s']:.2f}-{span['end_s']:.2f}s"
                 if span else "")
              + (f" ({ans['reason']})" if ans.get("reason") else ""),
              file=sys.stderr)
    for req, ans in zip(sound_result["sound_requested"], sound_result["sound_delivered"]):
        print(f"  SOUND {req['beat_id']} ({req['intent']}): {ans['outcome']}"
              + (f" - {ans['asset_id']} at {ans['at_seconds']:.2f}s on block {ans['block_index']}"
                 if ans["outcome"] == sound_layer.OUTCOME_PLACED else ""),
              file=sys.stderr)
    for rec in plan.get("comparison_lines", []):
        print(f"  FACT LINE {rec['fact_id']}: {rec['start_s']:.2f}-"
              f"{rec['end_s']:.2f}s on block {rec['block_index']}"
              + (f" - {rec['text']!r}" if rec["text"] else " - no screen wording")
              + (f", badge [{rec['ref']}] {rec['publisher']!r} {rec['panel_w']}px"
                 if rec["ref"] else ", no badge"),
              file=sys.stderr)
    for o in plan.get(footage_credits.OWN_CAPTURES_FIELD) or []:
        print(f"  OWN CAPTURE {o['video_id']} on block(s) {o['blocks']} "
              f"({o['seconds_on_screen']:.1f}s): {o.get('url') or 'no record of the page'}"
              + (f", Space licence {o['space_licence']}" if o.get("space_licence") else ""),
              file=sys.stderr)
    for o in plan.get(footage_credits.OVERLAYS_FIELD) or []:
        print(f"  FOOTAGE CREDIT {o['start_s']:.2f}-{o['end_s']:.2f}s on block(s) "
              f"{o['block_indices']}: {' / '.join(o['lines'])!r}", file=sys.stderr)
    card_rec = plan.get("end_card")
    if card_rec and card_rec.get("variant") == end_card.VARIANT_CLIP:
        print(f"  ENDING clip: {card_rec['start_s']:.2f}-"
              f"{card_rec['start_s'] + card_rec['seconds']:.2f}s "
              f"({card_rec['seconds']:.2f}s), {card_rec['path']}", file=sys.stderr)
        print(f"  composition {plan['duration']['composition']:.2f}s "
              f"= {duration:.2f}s narration + {card_rec['seconds']:.2f}s ending",
              file=sys.stderr)
    elif card_rec:
        print(f"  END CARD {card_rec['variant']}: {card_rec['start_s']:.2f}-"
              f"{card_rec['start_s'] + card_rec['seconds']:.2f}s "
              f"({card_rec['seconds']:.2f}s), "
              + (f"{card_rec['text']!r} from {card_rec['text_source']}"
                 if card_rec.get("text")
                 else f"no phrase, {card_rec['channel_name']!r} (CF-0186)")
              + (f", logo {card_rec['logo_path']}" if card_rec["logo_path"] else ""),
              file=sys.stderr)
        print(f"  composition {plan['duration']['composition']:.2f}s "
              f"= {duration:.2f}s narration + {card_rec['seconds']:.2f}s card",
              file=sys.stderr)
    if plan["duration"]["deviation"]:
        print(f"  DURATION OFF TARGET: {duration:.1f}s vs target "
              f"{lo_t:.1f}-{hi_t:.1f}s ({plan['duration']['deviation']:+.1f}s)",
              file=sys.stderr)
    for line in narration_length.report_lines(narration):
        print(f"  {line}", file=sys.stderr)
    c = rhythm_record["cadence"]
    print(f"  rhythm {rhythm_record['rhythm_requested']} -> "
          f"{rhythm_record['rhythm_delivered']}, pattern "
          f"{rhythm_record['pattern_requested']} -> "
          f"{rhythm_record['pattern_delivered']}"
          # CF-0192: the run log says the code, not just the absence. A reader
          # of this line should never have to open the plan to learn why.
          + (f" ({rhythm_record['pattern_not_delivered']})"
             if rhythm_record["pattern_not_delivered"] else "")
          + f"; {c['block_count']} blocks, "
          f"mean {c['mean']}s, longest {c['longest']}s, cv {c['cv']}")
    for d in rhythm_record["deviations"]:
        print(f"  RHYTHM: {d}", file=sys.stderr)
    # CF-0118: one line either way. A pass is as much a fact about this
    # video as a failure, and in `measure` mode the passing lines are the
    # measurement the decision to enforce will be made from.
    for line in source_gate.report_lines(gate_record):
        print(f"  {line}", file=sys.stderr)
    # CF-0137: one line either way, same as the gate above. A plan reaching
    # here passed - either no block is assetless, or the channel allows the
    # rung - and which of the two it was is the thing worth recording.
    for line in assetless_rung.report_lines(assetless_gate):
        print(f"  {line}", file=sys.stderr)
    for r in plan["rhythm"]["emergency_reuse"]["reuses"]:
        print(f"  EMERGENCY REPEAT block {r['block']}: shot {r['shot']} shown "
              f"again ({r['seconds']:.2f}s), already in block(s) "
              f"{r['also_in_blocks']} - this video needs material (CF-0137)",
              file=sys.stderr)
    for n in notes:
        print(f"  NOTE: {n}", file=sys.stderr)
    if degraded_blocks:
        for d in degraded_blocks:
            print(f"  DEGRADED block {d['index']}: {d['from']} -> {d['to']} "
                  f"({d['reason']})", file=sys.stderr)
        # CF-0120: a `sequence` block survives as footage exactly as a clip
        # does - it is several clips of one side rather than one.
        surviving = sum(1 for b in blocks
                        if b["asset"]["kind"] in ("clip", "still", "sequence"))
        if surviving == 0:
            # CF-0031's documented escape valve: per-block degradation looked
            # at every block and none of them survive as clip or still - the
            # source material itself is bad, not just one segment, so a
            # whole-video rung drop (re-run with a plain --style on the
            # *original* storyboard) is the justified move here, not silence.
            print("  ALL BLOCKS DEGRADED: zero surviving clip/still blocks - "
                  "per-block degradation is exhausted, a whole-video rung "
                  "drop is warranted here (see SKILL.md degradation policy)",
                  file=sys.stderr)
    # CF-0648: a held / long picture held_screen flagged is re-cut under its
    # anchor's next candidate - the storyboard resolved again with the
    # picture excluded, this plan built again - and kept only when the new
    # plan scores higher; at most 2 re-cuts per anchor, 2 rounds per build.
    if HELD_RECUT_ON and not args.no_held_recut:
        held_recut.run(args.output, args.storyboard, plan, story,
                       argv=[str(Path(__file__).resolve()), *sys.argv[1:]])


@video_script("video-editor", "plan", name="build_render_plan.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    global HELD_RECUT_ON
    HELD_RECUT_ON = True
    main()


if __name__ == "__main__":
    cli()
