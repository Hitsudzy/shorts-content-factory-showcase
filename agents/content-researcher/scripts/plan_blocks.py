#!/usr/bin/env python3
"""CF-0284: the Video Editor's block plan, asked for before TTS is paid for.

This file is a **stub, not a planner**. It holds no rhythm rule of its own and
computes nothing about block boundaries: it reads a payload on stdin, hands it
to `agents/video-editor/scripts/rhythm.plan_segments()` - the code that will
cut the real video an hour later - and prints what came back. It is written
here rather than in the Editor's checkout for the same reason
`check_anchor_coverage.py` runs `anchor_coverage.py` as a child process: the
Editor owns the rule, the Content Researcher owns the *question*, and the
question is asked on the Editor's own venv (CF-0140).

Run it with the Editor's interpreter, not this repo's::

    agents/video-editor/.venv/bin/python3 scripts/plan_blocks.py \
        --editor-scripts agents/video-editor/scripts \
        --patterns patterns < payload.json

`--patterns` is the factory root's `patterns/` directory, and it is what makes
the answer the layout the Editor will actually cut. CF-0276 made a pattern's
**drawn** `key_frame_hold_seconds` band a ceiling on the layout itself: the
boundaries are cut to it where the rhythm allows a new boundary, and what is
still over it afterwards is `rhythm.ceiling_report()`. Without the directory
this stub plans the pre-CF-0276 layout - fewer blocks than the Editor will
cut, and no word about the ceiling - so every caller passes it and
`pattern_read` says per plan whether the file was there.

`rhythm.py` is pure arithmetic over anchor times and word times - `import
math, statistics` and nothing else - so this costs one interpreter start
(~0.2 s) for a whole batch and no model, no CLIP and no ffmpeg.

Payload (stdin), one entry per script::

    {"scripts": [{"script_id": "...",
                  "anchor_starts": [0.0, 2.44, ...],   # seconds
                  "total": 51.298,                      # speech seconds
                  "word_starts": [0.0, 0.305, ...],     # seconds, all words
                  "order": {...},                       # script's `pattern`
                  "anchor_sides": ["a", "b", null, ...] | null,
                  "picture_shots": [1, 3, 2, ...]}]}    # CF-0365, optional

Answer (stdout)::

    {"kind": "block_plan",
     "constants": {...},          # the Editor's own numbers, never copied
     "plans": [{"script_id": "...",
                "declared_sides_usable": false,   # CF-0285, the Editor's own test
                "pattern_read": true,             # CF-0277, patterns/<id>.json
                "ceiling": {...},                 # rhythm.ceiling_report()
                "margin": {...},                  # CF-0303, only when asked for
                "block_band": {...},              # CF-0310, see block_band_report()
                "picture_band": {...},            # CF-0365, only with picture_shots
                "shot_budget": {...},             # CF-0371, see shot_budget_report()
                "score_findings": [...],          # CF-0433, see score_findings()
                "blocks": [{"index": 0, "start": .., "end": .., "seconds": ..,
                            "anchors": [0], "role": "item", "side": null,
                            "max_shots": 1}]}]}

`margin` (CF-0303) appears only when `--hold-margin-fraction` is given, and it
is the one piece of arithmetic this file does: it subtracts a share of the
band's width from the band's top and asks the Editor's own `over_band_top()`
which blocks are over what is left. The share is the *caller's* number and is
never written down here - see `margin_report()`.

`block_band` (CF-0310) is the pattern's *other* band - how many blocks, or at
what pace, the pattern is cut - measured on the layout above and judged by the
Editor's own `rhythm.block_count_parameter()` and `rhythm.cadence_band_refuses()`.
No band, no shape of a band and no refusal rule is written down here either;
what this file adds is the reading's own limit, because the number is measured
over the rhythm's segments while the judge's is measured over the render plan's
picture blocks - see `block_band_report()`.

`picture_band` (CF-0365) is the same band read once more, over the **picture
blocks** the caller's replay of the resolve hands out (`picture_shots`: how many
shots each block of this very layout is cut from, one number per block, in
order). It is asked by `check_block_capacity.py` in a second payload, after its
replay, and answered by the same `block_band_report()` - see
`picture_band_report()`.

`constants` travels with the plan on purpose. The replay that consumes this
(`check_block_capacity.py`) needs the reuse cap, the emergency-repeat budget
and the shortest cut the resolver will make, and a second copy of any of those
numbers in this repository is how two rules with one name happen (CF-0003).

Exit codes: 0 answered, 2 the payload is not a payload, 3 the Editor's
`rhythm.py` is not importable from `--editor-scripts`.
"""
import argparse
import json
import sys
from pathlib import Path


def load_rhythm(editor_scripts):
    """The Editor's `rhythm` module, or an explanation of why not."""
    path = Path(editor_scripts).resolve()
    if not (path / "rhythm.py").exists():
        raise SystemExit(f"plan_blocks.py: no rhythm.py under {path} - the block plan "
                         f"is the Video Editor's rule and this stub carries no copy "
                         f"of it")
    sys.path.insert(0, str(path))
    try:
        import rhythm  # noqa: PLC0415 - the whole point of the stub
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"plan_blocks.py: {path}/rhythm.py would not import: {exc}")
    return rhythm


def constants(rhythm):
    """The Editor's numbers the replay downstream has to run at.

    `min_cut_seconds` lives in `resolve_anchors.py`, which imports cheaply
    (~0.2 s, no torch, no CLIP) but is not needed for the plan itself, so a
    checkout where it will not import still answers - with the field absent
    rather than with a guess.
    """
    out = {
        "lead_seconds": rhythm.LEAD_SECONDS,
        "min_anchor_gap_seconds": rhythm.MIN_ANCHOR_GAP_SECONDS,
        "min_ordered_block_seconds": rhythm.MIN_ORDERED_BLOCK_SECONDS,
        "min_swing_cut_seconds": rhythm.MIN_SWING_CUT_SECONDS,
        "max_shot_reuse": rhythm.MAX_SHOT_REUSE,
        "max_emergency_reuse_per_video": rhythm.MAX_EMERGENCY_REUSE_PER_VIDEO,
        # CF-0277: what `hold` grows the key frame to when the order drew no
        # `key_frame_hold_seconds` of its own. The cadence gate quotes it back
        # at the writer, and quoting it is the reason it travels rather than
        # being written down over there.
        "default_hold_seconds": rhythm.DEFAULT_HOLD_SECONDS,
    }
    try:
        import resolve_anchors  # noqa: PLC0415
        out["min_cut_seconds"] = resolve_anchors.MIN_CUT_SECONDS
        out["default_min_score"] = resolve_anchors.DEFAULT_MIN_SCORE
        out["default_top"] = resolve_anchors.DEFAULT_TOP
    except Exception:  # noqa: BLE001 - the plan does not depend on it
        pass
    return out


def band_top_comparison(rhythm):
    """`(over, name, tolerance)` - how the top of a hold band is compared.

    CF-0303 gave the Editor one comparison for it, `rhythm.over_band_top()`,
    with half a frame of the 30 fps composition under it: an overshoot smaller
    than that shows no extra frame on screen, so it is not an overshoot. Every
    gate that speaks about the top of a band - the Editor's judge, its trim, its
    refusal before the render, and this margin - has to use that one, or two
    rules with the same name drift apart (CF-0003).

    It is fetched by name rather than imported outright because the checkout
    beside this one may be older than CF-0303 (today it is a branch, not
    `main`). Without the name the comparison falls back to the strict `>` that
    `ceiling_report()` used before it, which is the reading this gate had
    anyway; the answer says which of the two was used, so a record never
    pretends to a tolerance the Editor did not grant.
    """
    over = getattr(rhythm, "over_band_top", None)
    if callable(over):
        return (over, "rhythm.over_band_top",
                getattr(rhythm, "HOLD_BAND_TOP_TOLERANCE_SECONDS", None))
    return ((lambda measured, top: measured is not None and top is not None
             and float(measured) > float(top)),
            "strict `>` (this Editor checkout has no rhythm.over_band_top)", 0.0)


def margin_report(rhythm, blocks, band, fraction, last_fraction=None):
    """CF-0303: which blocks sit too close to the top of the band to survive TTS.

    The Content Researcher measures its layout on an *estimate* of the speech
    (`check_anchor_cadence.anchor_times()`, word *k* at `k / rate`), and the
    estimate is right about the whole - 49.153s against a 49.15s wav on
    `coach-hale-stadiums`, 44.129 against 44.125 on `delver` - and wrong about
    the share each block gets: the longest block came out +0.839s and +1.135s
    longer once the wav existed. So a block that fits under the top by a tenth
    of a second before TTS is a block the Editor refuses after it. The remedy is
    to hold the estimate under `top - margin`, and this is where the subtraction
    happens, beside the comparison it has to be made with.

    `fraction` and `last_fraction` are the caller's - the share of the band's
    *width* the margin is (`check_anchor_cadence.HOLD_MARGIN_BAND_FRACTION`).
    **No margin of this file's own exists**: the stub holds no rule, and a
    number here would be the second copy CF-0003 is about. A band with no floor
    has no width and therefore no margin; an absent `fraction`, or a band that
    is not drawn (`band` is None, CF-0039), means no reading at all.
    """
    if fraction is None or not band:
        return None
    top, floor = band.get("max"), band.get("min")
    out = {"asked": False, "fraction": fraction, "last_fraction": last_fraction,
           "band": dict(band), "blocks": []}
    if top is None or floor is None:
        out["why"] = ("the band draws no floor, so a share of its width is not a number - "
                      "the top is held without a margin")
        return out
    over, comparison, tolerance = band_top_comparison(rhythm)
    width = float(top) - float(floor)
    last_index = len(blocks) - 1
    margin = round(float(fraction) * width, 3)
    last_margin = (margin if last_fraction is None
                   else round(float(last_fraction) * width, 3))
    out.update({
        "asked": True, "band_width_seconds": round(width, 3),
        "margin_seconds": margin, "last_block_margin_seconds": last_margin,
        "ceiling_seconds": round(float(top) - margin, 3),
        "last_block_ceiling_seconds": round(float(top) - last_margin, 3),
        "comparison": comparison, "tolerance_seconds": tolerance,
    })
    for block in blocks:
        is_last = block["index"] == last_index
        ceiling = (out["last_block_ceiling_seconds"] if is_last
                   else out["ceiling_seconds"])
        if not over(block["seconds"], ceiling):
            continue
        out["blocks"].append({
            "block": block["index"], "role": block["role"],
            "seconds": block["seconds"], "last_block": is_last,
            "margin": last_margin if is_last else margin,
            "ceiling": ceiling, "band_max": top,
            "outside_by": round(block["seconds"] - ceiling, 3),
        })
    return out


def block_band_report(rhythm, blocks, pattern):
    """CF-0310: the pattern's block-count envelope, read before the TTS.

    The other band. `key_frame_hold_seconds` says how long one frame may hold;
    this one says how many blocks the video is cut into - and until CF-0310 no
    stage read it before the render, which is how `outrider-doune-castle`
    (`2026-09-21T1541Z`) was written, voiced, cut and sent to the user carrying
    `pattern_delivered: null`.

    Three things are asked of the Editor and none is decided here:

      * `rhythm.cadence(blocks)` - the measurement, over the blocks this stage
        already built above. Same arithmetic as the judge's, one copy of it;
      * `rhythm.block_count_parameter()` - *which shape* the envelope is in.
        CF-0310 moved `explainer` from a count (12-33 blocks, which is a count
        AND a length: the same cutting over 34s and over 55s gives different
        numbers) to a pace (15.39-47.88 blocks/min). Patterns that draw a count
        still draw one. No `if "block_count" in ...` may be written here: a
        second reader of that shape is a second thing to migrate;
      * `rhythm.cadence_band_refuses()` - whether a shortfall is one a stage
        may refuse a plan on. The rule has three branches since CF-0314 and
        every one of them lives in the Editor, beside the gate that refuses
        after the render; this stage refuses one wav earlier *on the same
        predicate* - two copies of it would drift apart on the first pattern
        file that changes (CF-0003).

    All three are fetched by name, as CF-0303 fetched `over_band_top`: the
    checkout beside this one may be older than CF-0310, and then the answer
    says the reading was not taken rather than inventing one.

    The third mode, and the word this Editor cannot read (CF-0314)
    --------------------------------------------------------------
    `explainer`'s rate band is `floor_drawn` since 2026-09-22: its floor is an
    order and its ceiling is still an observation. Three things follow here and
    none of them is a rule of this file's own.

    Which words are modes is `rhythm.KNOWN_BAND_MODES` - fetched by name, so an
    Editor checkout older than CF-0314 reads `floor_drawn` exactly as it read
    any other unknown word before, and a word NEITHER repository knows is its
    own case (`rhythm.PATTERN_BAND_MODE_UNREADABLE`) rather than "there is no
    band": the band is there and was not read, and the reader is told which
    word stopped it.

    The sentence names the end that was broken, in the Editor's own two
    phrasings, because "outside 15.39-47.88" does not tell its reader whether
    he is looking at a refusal or at a note.

    And under an ORDERED floor `reading_note` does not stop at "this says
    nothing about the cutting" - it says what happens next, which is that the
    Editor checks the same floor again on the finished plan and refuses it as
    `pattern_undeliverable` with the wav already paid for. That is the whole
    difference between a floor that was observed and a floor that was ordered,
    and the operator reading this line is the one who can still act on it.

    What this stage can and cannot see
    ----------------------------------
    The number here is measured over **the rhythm's segments** - what
    `plan_segments()` returns - and the judge's is measured over the finished
    render plan's **picture blocks**, which is not the same unit: inside one
    segment `resolve_anchors.py` hands out as many shots as the pool affords,
    and each becomes a block. On `outrider-doune-castle` that is 3 segments
    against 10 blocks (6.27 vs 20.91 blocks/min); on `coach-hale` (2026-09-09),
    3 against 3. The spread is 1.0x-3.7x over the four `even` videos on disk
    and it depends on the *pool*, which this pass does not know.

    The error has one direction: the delivered count is never below the
    segment count. So a reading over the band's top is a reading the delivered
    video will also be over - safe to refuse on - and a reading under a floor
    is not evidence of anything about the cutting. `reading_supports_refusal`
    carries that, and the gate refuses only when the Editor's predicate says
    refuse *and* this reading carries it. That condition is not a second copy
    of the band rule: it is this stage's correction for measuring an estimate,
    the same job CF-0303's margin does under the hold band's top, and it can
    only soften a refusal, never add one.
    """
    out = {"asked": False, "pattern_read": pattern is not None,
           "measured_over": "rhythm.plan_segments() - the rhythm's segments, not the "
                            "render plan's picture blocks (CF-0310)"}
    if pattern is None:
        out["why"] = ("patterns/ was not read, so the block band is unknown - this is a "
                      "record of `not checked`, not of `inside` (CF-0192)")
        return out
    pid = pattern.get("pattern_id")
    out["pattern_id"] = pid
    parameter_of = getattr(rhythm, "block_count_parameter", None)
    if not callable(parameter_of):
        out["why"] = ("this Editor checkout has no rhythm.block_count_parameter - which shape "
                      "the envelope is in is its answer to give, and this file carries no "
                      "copy of it (CF-0310)")
        return out
    params = pattern.get("parameters") or {}
    form = parameter_of(params)
    if form is None:
        out["why"] = (f"patterns/{pid}.json declares neither block-count parameter, so there "
                      f"is no envelope to hold this layout to")
        return out
    key, code, field, measured_unit, band_unit = form
    cadence = rhythm.cadence(blocks)
    measured = cadence.get(field)
    declared = params.get(key)
    band = declared if isinstance(declared, dict) else {}
    mode, lo, hi = band.get("mode"), band.get("min"), band.get("max")
    # CF-0314: which words are modes is the Editor's list, fetched by name like
    # every other answer of his in this file - a checkout older than CF-0314
    # does not know `floor_drawn`, and then this reading behaves as it did
    # before, rather than inventing a rule for a word its judge cannot read.
    known = getattr(rhythm, "KNOWN_BAND_MODES", None)
    unreadable_code = getattr(rhythm, "PATTERN_BAND_MODE_UNREADABLE", None)
    floor_drawn = getattr(rhythm, "BAND_MODE_FLOOR_DRAWN", "floor_drawn")
    decimals = getattr(rhythm, "BLOCK_RATE_DECIMALS", None)
    out.update({
        "parameter": key, "code": code, "mode": mode, "unit": measured_unit.strip(),
        "measured": measured, "band_min": lo, "band_max": hi,
        "blocks": cadence.get("block_count"),
        "block_span_seconds": round(sum(cadence.get("durations") or []), 3),
        "measured_by": f"rhythm.cadence()[{field!r}]",
        "parameter_form_by": "rhythm.block_count_parameter()",
    })
    # A mode this Editor does not know is not "no band": the band is there and
    # was not read, which is the Editor's own PATTERN_BAND_MODE_UNREADABLE
    # (CF-0314) - and the word is quoted back, because one of the two
    # repositories has to move and the reader has to see which.
    if known is not None and unreadable_code is not None and mode not in known:
        out.update({
            "code": unreadable_code, "known_modes": list(known), "refuses": False,
            "why": (f"patterns/{pid}.json#parameters.{key} declares mode {mode!r}, which the "
                    f"Editor beside this stage does not know ({', '.join(known)}) - the band "
                    f"was not checked and nothing is claimed about it"),
        })
        return out
    if measured is None or lo is None or hi is None or mode not in (known or ("drawn",
                                                                              "emergent")):
        out["why"] = (f"patterns/{pid}.json#parameters.{key} is {band!r} and the layout "
                      f"measures {measured!r} - there is no band to hold it to")
        return out
    # CF-0314: both ends are compared on the grid the Editor compares them on
    # (`rhythm.cadence()` already rounds a rate to BLOCK_RATE_DECIMALS and the
    # pattern file's band lies on the same grid), so the two stages give the
    # same answer about a layout measured at the floor's own full precision.
    at_grid = (lambda v: round(v, decimals)) if decimals is not None else (lambda v: v)
    over = at_grid(measured) > at_grid(hi)
    inside = at_grid(lo) <= at_grid(measured) and not over
    out.update({
        "asked": True, "inside": inside,
        "outside_by": 0.0 if inside else round(
            (lo - measured) if not over else (measured - hi), 3),
    })
    if inside:
        out.update({"refuses": False, "shortfall": None,
                    "refusal_rule": "not asked - the layout is inside the band"})
        return out
    # The shape `rhythm.pattern_shortfalls()` writes, because the predicate
    # that judges it is the one the Editor's judge feeds - including the
    # sentence, which on a `floor_drawn` band names the END that was broken and
    # what that end is (CF-0314): its reader is deciding whether this is a
    # refusal or a note, and "outside the band" does not tell him.
    if mode == floor_drawn:
        tail = (f"over {pid}'s observed ceiling {hi}{band_unit} (floor {lo} ordered)" if over
                else f"under {pid}'s ordered floor {lo}{band_unit} (ceiling {hi} observed)")
    else:
        word = "drawn band" if mode == "drawn" else "observed envelope"
        tail = f"outside {pid}'s {word} {lo}-{hi}{band_unit}"
    shortfall = {
        "kind": "pattern_shortfall", "code": code, "pattern_id": pid,
        "parameter": key, "mode": mode, "measured": measured,
        "band_min": lo, "band_max": hi, "outside_by": out["outside_by"],
        "note": (f"{measured}{measured_unit} over {out['block_span_seconds']}s of blocks, "
                 f"{tail}"),
    }
    out["shortfall"] = shortfall
    refuses_on = getattr(rhythm, "cadence_band_refuses", None)
    if not callable(refuses_on):
        out.update({"refuses": None, "reading_supports_refusal": None,
                    "refusal_rule": "not asked - this Editor checkout has no "
                                    "rhythm.cadence_band_refuses (CF-0310)"})
        return out
    note = (
        "over the band's top: the delivered block count is never below the segment "
        "count this stage measures, so the finished video is over it too"
        if over else
        "under the band's floor: this stage counts the rhythm's segments and the "
        "Editor counts picture blocks (3 against 10 on outrider-doune-castle), so a "
        "reading under a floor says nothing about how the video is cut")
    # CF-0314: under a floor that was ORDERED the sentence above is true and
    # stops one step early. This stage still cannot refuse - it measures an
    # estimate - but the plan is not therefore fine: the same floor is checked
    # again after the wav is paid for, and there the count is the finished
    # video's.
    if mode == floor_drawn and not over:
        note += (f". That floor is an order (the user's decision of 2026-09-22, CF-0314), "
                 f"not an observation - and since CF-0433 (grill 2026-09-29) a price, not "
                 f"a refusal: if the finished plan is still cut under {lo}{band_unit} the "
                 f"Editor charges `score.pace_below_floor` (-2 per started block/min "
                 f"missing, cap -12) and refuses only a video whose whole score falls "
                 f"under N")
    out.update({
        "refuses": bool(refuses_on(shortfall)),
        "refusal_rule": "rhythm.cadence_band_refuses()",
        "reading_supports_refusal": over,
        "reading_note": note,
    })
    return out


PICTURE_MEASURED_OVER = (
    "the picture blocks of the Content Researcher's replay of resolve_anchors' hand-out "
    "(check_block_capacity.hand_out) - each shot a block, as the Editor's judge counts "
    "them (CF-0365)")


def picture_band_report(rhythm, blocks, shots, pattern):
    """CF-0365: the block band, read over the picture blocks and not the segments.

    `example-film/2026-09-23T1722Z`, `lf-2026-09-23-004` (You Can See
    Everything, `moment-breakdown`/`even`): 10 anchors, 11 segments - inside
    the drawn 6-12, so `block_band` passed it - and the Editor refused the plan
    after the TTS at **22** blocks, because under `even` a segment takes as many
    shots as the pool needs to cover it (`max_shots: None`) and each shot is a
    block the judge counts. The replay in `check_block_capacity.py` had already
    handed out 21 of them before the voice was paid for; nobody held that
    number to the band.

    `shots` is that hand-out, one count per block of THIS layout. Each block is
    divided into that many equal pieces and the pieces go through
    `block_band_report()` unchanged - the Editor's `cadence()`, its
    `block_count_parameter()` and its `cadence_band_refuses()`, no rule of this
    file's own. How the block is divided does not move either shape of the
    band: a count is the number of pieces and a rate divides it by the same span.

    What does not carry over is `block_band_report()`'s one-directional error
    note: the segment count is a floor under the delivered count, a replayed
    picture count is not - it can be over or under what the resolver cuts. So
    `reading_supports_refusal` and `reading_note` are taken out and `over_top`
    is left for the caller, who holds the replay's measured error.
    """
    pieces = []
    for block, n in zip(blocks, shots):
        n = max(1, int(n or 0))
        start, end = float(block["start"]), float(block["end"])
        step = (end - start) / n
        for k in range(n):
            pieces.append({"start": round(start + k * step, 3),
                           "end": round(end if k == n - 1 else start + (k + 1) * step, 3)})
    out = block_band_report(rhythm, pieces, pattern)
    over = out.pop("reading_supports_refusal", None)
    out.pop("reading_note", None)
    if over is None and out.get("asked"):
        over = False
    out.update({"measured_over": PICTURE_MEASURED_OVER, "over_top": over,
                "segments": len(blocks), "picture_blocks": len(pieces)})
    return out


def shot_budget_report(rhythm, segs, blocks, pattern):
    """CF-0371: how many shots the resolver lets each `even` block take.

    CF-0370 capped the chain on the Editor's side: under a pattern whose
    `block_count` band is drawn as a count, every unordered segment is cut
    from at most `rhythm.even_shot_budget(top, blocks_so_far, segments_after,
    seconds, hold_top)` shots and the last one holds the rest of the segment
    (`resolve_anchors.py`, right after `budget = seg["max_shots"] or
    len(pool)`). `example-film/2026-09-23T1722Z`/004 went from 22 picture
    blocks to 12 on it - while the replay in `check_block_capacity.py`, which
    knew nothing of the cap, still handed out 21 and rejected the pattern.

    The budget depends on one number only the replay knows - how many
    pictures are already down (`blocks_so_far`) - so what travels is the
    Editor's own function evaluated over every value that number can take
    before the answer stops moving: `by_block[i][k]` is the budget of block
    `i` with `k` pictures before it, for k = 0..top; past `top` the budget is
    the one at `top` (the function is flat there - its first term is already
    at its floor of one). `None` is a block the resolver never caps: an
    ordered one, by the resolver's own `is_ordered_segment()`. The top, the
    hold top and which segments are ordered are all the Editor's
    (`rhythm.block_count_ceiling()`, `rhythm.hold_band()`), and nothing of
    the rule is written down here.

    `asked: false` with a `why` when there is nothing to budget - no drawn
    count top, or an Editor checkout older than CF-0370 - and then the replay
    hands out what it always did.
    """
    budget = getattr(rhythm, "even_shot_budget", None)
    ceiling = getattr(rhythm, "block_count_ceiling", None)
    if not (callable(budget) and callable(ceiling)):
        return {"asked": False,
                "why": "this Editor checkout has no rhythm.even_shot_budget() - older "
                       "than CF-0370, so its resolver does not cap `even` either"}
    top = ceiling(pattern)
    if top is None:
        return {"asked": False,
                "why": "the pattern draws no block-count top as a count "
                       "(rhythm.block_count_ceiling() is None) - nothing caps the chain"}
    try:
        import resolve_anchors  # noqa: PLC0415
        ordered = resolve_anchors.is_ordered_segment
    except Exception as exc:  # noqa: BLE001
        return {"asked": False,
                "why": f"resolve_anchors.is_ordered_segment() would not import ({exc}) - "
                       f"which segments the resolver caps is its rule, not this file's"}
    band = rhythm.hold_band(pattern)
    hold_top = float(band["max"]) if band else None
    n = len(segs)
    by_block = []
    for i, (seg, block) in enumerate(zip(segs, blocks)):
        if ordered(seg):
            by_block.append(None)
            continue
        by_block.append([budget(top, k, n - i - 1, seconds=block["seconds"],
                                hold_top=hold_top)
                         for k in range(int(top) + 1)])
    return {"asked": True, "top": int(top), "hold_top": hold_top,
            "budget_by": "rhythm.even_shot_budget()",
            "ordered_by": "resolve_anchors.is_ordered_segment()",
            "by_block": by_block}


def score_findings(rhythm, blocks, pattern, band):
    """CF-0433: `score.pace_below_floor` and `score.hold_band_exceeded` on
    this layout, in the score model's finding shape (shared/score/score.py).

    Both are the Editor's functions, fetched by name like every other answer
    of his here: `rhythm.pace_findings()` over the block band's shortfall and
    `rhythm.hold_band_findings()` over the blocks. A checkout older than
    CF-0433 has neither, and then there is nothing to price - `[]`, not a
    guess. Every finding is marked `estimate: "before_tts"`: the layout is
    measured on an estimated speech rate, and the Editor prices the real
    one."""
    pace = getattr(rhythm, "pace_findings", None)
    hold = getattr(rhythm, "hold_band_findings", None)
    out = []
    if callable(pace) and isinstance(band, dict) and band.get("shortfall"):
        out += pace([band["shortfall"]])
    if callable(hold) and pattern is not None:
        out += hold(blocks, pattern)
    for f in out:
        f["estimate"] = "before_tts"
    return out


def plan_one(rhythm, entry, patterns_dir=None, margin_fraction=None,
             last_margin_fraction=None):
    """One script's layout, with the pattern's ceiling on it when it can be read.

    CF-0277. The pattern file is the Editor's own `rhythm.load_pattern()` and
    the ceiling is its own `plan_segments(pattern=...)` - this stub still
    computes nothing. What comes back beside the blocks is
    `rhythm.ceiling_report()`: the seconds of video in front of the first
    anchor's word (`lead_before_first_anchor`, reported breach or none) and
    every block the layout could **not** bring under the drawn band, with the
    code saying why it could not (`boundary_is_the_rhythm` when a new boundary
    inside it would delete the instruction the block is - a declared crossing
    or a held key frame - and `no_room_to_cut` when there is no word boundary
    left to cut on). Those are the blocks that are a writing problem and
    nothing else: the montage has already done everything it is allowed to do.
    """
    anchor_starts = [float(x) for x in entry["anchor_starts"]]
    order = entry.get("order")
    pattern = None
    if patterns_dir:
        pid = (order or {}).get("pattern_id") or rhythm.normalize_order(order)["pattern_id"]
        pattern = rhythm.load_pattern(pid, patterns_dir)
    segs = rhythm.plan_segments(
        anchor_starts,
        float(entry["total"]),
        order,
        [float(x) for x in (entry.get("word_starts") or [])],
        entry.get("anchor_sides") or None,
        pattern=pattern,
    )
    blocks = []
    for i, seg in enumerate(segs):
        blocks.append({
            "index": i,
            "start": round(seg["start"], 3),
            "end": round(seg["end"], 3),
            "seconds": round(seg["end"] - seg["start"], 3),
            "anchors": list(seg["anchors"]),
            "role": seg["role"],
            "side": seg["side"],
            "max_shots": seg["max_shots"],
        })
    # CF-0285: which of the two side rules this plan was built under, decided
    # by the Editor's own `declared_sides_usable()` rather than by a second
    # reading of the same list here. It changes what the replay downstream may
    # do with a block's side: sides the script declared are a property of the
    # writing and the resolve filters nothing by them (the anchor's phrase
    # already *is* the side), while sides taken from the footage are sources
    # and the candidate pool is filtered down to them
    # (`resolve_anchors.py`, "which candidates this block may draw on").
    report = rhythm.ceiling_report(segs, order, pattern, anchor_starts)
    out = {"script_id": entry.get("script_id"), "blocks": blocks,
           "declared_sides_usable": bool(
               rhythm.declared_sides_usable(entry.get("anchor_sides") or None)),
           "pattern_read": pattern is not None,
           "ceiling": report,
           # CF-0310: the other band, read on the blocks just built - the one
           # nobody read before the render until now.
           "block_band": block_band_report(rhythm, blocks, pattern),
           # CF-0371: the resolver's cap on `even`, for the replay to cut to.
           "shot_budget": shot_budget_report(rhythm, segs, blocks, pattern)}
    # CF-0365: the same band over the caller's replayed picture blocks.
    shots = entry.get("picture_shots")
    if isinstance(shots, list) and len(shots) == len(blocks):
        out["picture_band"] = picture_band_report(rhythm, blocks, shots, pattern)
    # CF-0433: the two rules of this layout that stopped refusing and started
    # costing points - asked of the Editor's own rhythm.pace_findings() /
    # hold_band_findings(), so the prices are read off the same blocks the
    # Editor will price after the voice. Each finding says it is an estimate
    # before the TTS (`estimate: before_tts`); the Editor prices the real wav.
    out["score_findings"] = score_findings(rhythm, blocks, pattern, out["block_band"])
    margin = margin_report(rhythm, blocks, report.get("band"), margin_fraction,
                           last_margin_fraction)
    if margin is not None:
        out["margin"] = margin
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--editor-scripts", required=True,
                    help="the Video Editor's scripts/ directory")
    ap.add_argument("--patterns", default=None,
                    help="the factory root's patterns/ directory (CF-0277). Without it the "
                         "layout is planned with no pattern ceiling on it, which is not the "
                         "layout the Editor will cut")
    ap.add_argument("--hold-margin-fraction", type=float, default=None,
                    help="CF-0303: hold every block this share of the band's WIDTH under "
                         "the band's top and report the ones that are not. The share is the "
                         "caller's rule (`check_anchor_cadence.py`); without it no margin "
                         "is read and the answer carries no `margin`")
    ap.add_argument("--hold-margin-last-fraction", type=float, default=None,
                    help="the same share for the LAST block, which the estimate "
                         "underestimates worse than any other (CF-0303). Defaults to "
                         "`--hold-margin-fraction`")
    ap.add_argument("--payload", default="-",
                    help="JSON payload ('-' for stdin, the default)")
    args = ap.parse_args(argv)

    raw = sys.stdin.read() if args.payload == "-" else Path(args.payload).read_text()
    try:
        payload = json.loads(raw)
        entries = payload["scripts"]
    except (ValueError, KeyError, TypeError) as exc:
        print(f"plan_blocks.py: unreadable payload: {exc}", file=sys.stderr)
        return 2

    rhythm = load_rhythm(args.editor_scripts)
    out = {"kind": "block_plan", "constants": constants(rhythm), "plans": []}
    for entry in entries:
        try:
            out["plans"].append(plan_one(rhythm, entry, args.patterns,
                                         args.hold_margin_fraction,
                                         args.hold_margin_last_fraction))
        except Exception as exc:  # noqa: BLE001 - one script's failure is a record
            out["plans"].append({"script_id": entry.get("script_id"),
                                 "blocks": None, "error": f"{type(exc).__name__}: {exc}"})
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    import _pipe_safe  # CF-0915: a closed pipe (`| head`) is not a crash
    _pipe_safe.guard()
    sys.exit(main())
