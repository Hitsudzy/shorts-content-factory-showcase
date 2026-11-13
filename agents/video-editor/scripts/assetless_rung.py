#!/usr/bin/env python3
"""CF-0137: may a block with no picture reach a shipped video, and what
happens when it may not.

The decision (CF-0123, grill 2026-09-07)
----------------------------------------
Per-block degradation to the assetless rung - an abstract animated
background sitting in the middle of the footage - was declared brak. Not
because it looks cheap in isolation but because of how it actually arrives:
in the four videos of batch `2026-09-03T2037Z` it came in runs of 2.1 to
14.3 consecutive blocks and took 14-38 % of the running time of three of
them. A video with that hole in it is not a finished video, and CF-0085,
which introduced the rung to keep an ordered cadence intact under a footage
shortage, bought the cadence at a price nobody had agreed to pay.

The ban is narrow, and the narrowness is the decision. It covers the
*per-block* rung only. The flat `typographic` style - one of the three in
CF-0015's rotation, chosen for a whole video before a frame is cut - is
untouched and never consults this module: what was called brak is the
tearing, not the look. `style_typographic()` below is the one test that
tells them apart, and it is why this gate is asked *after* the plan's style
is known.

The ladder
----------
A block whose anchor resolved to nothing climbs, in this order:

  1. an insert from the library - `meme_layer.plan_memes(fill_holes=True)`,
     CF-0138. A block with no picture is offered the library with no request
     behind it, the query being the block's own `intent`, and it gets a
     picture only if one clears the M4 floors CF-0143 measured (similarity
     0.26 and a lead of 0.02 over the third place). Below them the block
     keeps climbing, which is the usual outcome and the point: an insert
     that does not stand clear of the field is a random picture on a wall.
     `filled_by_insert()` below is how this gate sees the result.
  2. the emergency shot repeat - `rhythm.EmergencyReuseBudget`, spent in
     resolve_anchors.py where the pool and the ledger are. Exactly one per
     *video*: one single repetition, not one per block that wants one.
  3. this rung, the assetless block - and only on a channel that switched
     it on. Off everywhere by default, including on channels that do not
     exist yet, because the flag's absence means `false`.
  4. the planner's warning (CF-0330) - `judge()` returning `passed: False`
     below with `warned: True`: the block stays on the assetless rung (its
     `asset` is `procedural`, which Video.jsx paints as ProceduralBg for the
     block's span - the same deterministic render the rung has had since
     CF-0031/CF-0085), the plan is written, and the gate's code and numbers
     go into `plan["warnings"]` and the `plan.assetless-rung.json` deficit.
     Until 2026-09-23 this rung was a refusal (`sys.exit(2)`, no plan). The
     user returned it to a warning after the rebuild of `widows-bay` - a
     video he had accepted for publication - was refused for 3 of 24 blocks
     with no picture.

Why the refusal has no threshold (and why it is a warning now)
--------------------------------------------------------------
CF-0330: everything below still describes *what is measured* - one block is
one block, no share-of-runtime threshold. What changed is the consequence:
the user decided on 2026-09-23 that this gate warns (`plan_refusal.WARN_GATES`),
so "refuses the plan" below reads "warns, and the plan is written".

It was proposed that a video be refused only past some share of assetless
running time ("more than 25 %", "a run longer than 6 s"). CF-0137 rejects
that outright: with the rung switched off the rule is boolean - the hole is
there or it is not - and a percentage would be a constant nobody measured
guarding a defect everybody already agreed is a defect. One assetless block
refuses the plan.

Before the render, not after
----------------------------
`qc_render.py` does not know the word `degraded` at all: it probes the
rendered file, so by the time it could notice a procedural background the
render has already been paid for. This gate sits in build_render_plan.py
next to the two-source gate (CF-0118), on the finished block list and ahead
of the expensive layers, so a refused video costs a plan-building run and
no frames.
"""
import json
from pathlib import Path

# The channel switch. `channels/<channel>.json` -> this key, beside
# `insert_layers`: the same shape the insert switches use, because it is the
# same kind of statement - a mechanism the factory owns, and a channel saying
# whether it wants it. Deliberately *not* under `video_editor` with the render
# knobs (max_attempts_per_video, two_source_gate): those are how a video is
# made, this is what a channel is willing to publish.
CHANNEL_KEY = "assetless_block_rung"

# What a channel that says nothing gets. False, and it is the whole point of
# the task: a rung nobody switched on cannot appear in a shipped video, and a
# channel added next month inherits the ban without anyone remembering to
# write it down. There is no way to configure a default of true.
DEFAULT_ENABLED = False

# The `rhythm_shortfalls()` / deficit kind (CF-0057's shape), so a refused
# plan comes back with a record rather than a paragraph of stderr.
DEFICIT_KIND = "assetless_blocks_refused"


def enabled(channel_cfg):
    """Whether this channel allows per-block assetless degradation.

    Accepts the `{"enabled": bool, "reason": ...}` switch shape used by
    `insert_layers`, and a bare boolean for a config that writes the short
    form. Anything else - absent, null, a string, a broken config, no
    channel at all - is `DEFAULT_ENABLED`: a switch that cannot be read has
    not been switched on.
    """
    if not isinstance(channel_cfg, dict):
        return DEFAULT_ENABLED
    node = channel_cfg.get(CHANNEL_KEY)
    if isinstance(node, dict):
        return bool(node.get("enabled", DEFAULT_ENABLED))
    if isinstance(node, bool):
        return node
    return DEFAULT_ENABLED


# CF-0442: the fields an insert's picture can live in. AssetLayer.jsx draws a
# meme from `render_src` and a proof from `capture_path`; `file` is the meme
# library's own path, which older plans carried alone. Until CF-0442 this
# gate read only `file`, and a proof card - whose picture is in
# `capture_path` and which has no `file` at all (batch 2026-09-23T1722Z,
# american-dread-story block 4) - was counted as a block with no picture.
INSERT_PICTURE_FIELDS = ("file", "capture_path", "render_src")


def insert_has_picture(ins):
    """Whether this insert marker has a picture behind it - the one line
    between an insert the viewer sees and a request answered `no_asset`.
    Shared with qc_render.insert_window() so the two gates cannot disagree."""
    return bool(isinstance(ins, dict) and ins.get("kind")
                and any(ins.get(f) for f in INSERT_PICTURE_FIELDS))


def filled_by_insert(block):
    """CF-0138: whether this block's frame was given whole to a library
    insert, and so is not a block shipping with no picture.

    Kind-agnostic on purpose - a meme and a proof are both fitted whole into
    the block's frame for the block's whole span (inserts/meme.json and
    inserts/proof.json, `composition.fit: contain`), and whichever of them is
    there, the viewer is looking at a picture. What it does *not* do is
    accept a bare `insert` marker: an overlay with no file behind it is a
    request that was answered `no_asset`, and counting that as a picture
    would be this gate lying about the one thing it exists to check.

    This is deliberately not folded into `rhythm.has_picture()`. That one is
    CF-0136's question about footage - how much of the video the montage
    covered - and `rhythm.picture` keeps reporting the block as assetless,
    because the material really is missing and widening the pool is really
    the operator's next move. The two records answer two questions and are
    read together: `videos[].assetless_rung` for what shipped,
    `videos[].rhythm.picture` plus `videos[].meme_hole_fill` for what was
    short and what stood in for it.
    """
    return insert_has_picture(block.get("insert"))


def style_typographic(style):
    """CF-0015's flat style, which this gate never applies to.

    One string comparison, named rather than inlined, because the whole
    scope of CF-0137 turns on it: `--style typographic` is a video that was
    *chosen* to have no footage anywhere, and CF-0123 explicitly left it
    alone. Every other style means the assetless blocks are holes in a
    montage that was supposed to have pictures in them.
    """
    return style == "typographic"


def anchor_records(assetless, blocks=None):
    """CF-0139: one object per block that is still a hole, with enough on it
    to be an *anchor* rather than an index.

    `blocks` and `reasons` beside this are the same three facts flattened
    into two parallel lists, and they stay: `report_lines()` reads them, the
    rotation's own test pins them, and a record that is written on every
    refusal is not the place to break a reader for tidiness. What they cannot
    carry is the rest of what is known here - the block's `intent` and its
    span, and the rung it fell from (`from`, which build_assetless_rung_gate()
    copies off the degradation record and which was being dropped on the
    floor at this line).

    Why the span matters at all: when the plan is refused there is no plan
    file, so an entry that is only a block index points into a document that
    was never written. The rotation reads these in
    `rotation/shortage.py::anchors_from_deficit()` and joins them by
    `block_index` to `hole_fill.refused[]` for the library rung's outcome
    code; it accepts `index` too, but `block_index` is the name the same fact
    already has on the insert side and in the shortage record it ends up in,
    and one name across the join is worth more than symmetry with the input.
    """
    out = []
    for a in assetless:
        i = int(a["index"])
        b = blocks[i] if blocks is not None and 0 <= i < len(blocks) else {}
        start, end = b.get("start"), b.get("end")
        rec = {
            "block_index": i,
            "intent": (b.get("intent") or "").strip(),
            "start": None if start is None else round(float(start), 3),
            "end": None if end is None else round(float(end), 3),
            "from": a.get("from") or "",
            "reason": a.get("reason") or "",
        }
        # CF-0150: the third fact, beside `from`. `from` is the rung this hole
        # fell from; this is whether the pool ever offered a picture for the
        # anchor - `null` when it did (and the hole is a gate's doing), one of
        # resolve_anchors.CANDIDATE_SUPPLY_CODES when it did not. Written only
        # when it is known: an absent key is a record from before CF-0150, and
        # `rotation/shortage.py` reads historic records, so "the pool
        # delivered" and "nobody asked" may not collapse into one value.
        if "candidate_supply" in a:
            rec["candidate_supply"] = a["candidate_supply"]
        out.append(rec)
    return out


def judge(assetless, channel_cfg, style=None, blocks=None):
    """The verdict for a plan whose per-block degradations are known.

    `assetless` is the list of records build_render_plan.py collected while
    it built the blocks - `{index, from, reason}`, one per block that landed
    on the assetless rung by shortage rather than by whole-video style.
    """
    allowed = enabled(channel_cfg)
    flat = style_typographic(style)
    indices = [int(a["index"]) for a in assetless]
    seconds = None
    if blocks is not None:
        seconds = round(sum(float(blocks[i]["end"]) - float(blocks[i]["start"])
                            for i in indices if 0 <= i < len(blocks)), 3)
    if flat:
        note = (f"whole-video {style!r} style - the flat style of CF-0015, not "
                f"the per-block rung CF-0123 refused; this gate does not apply")
    elif not indices:
        note = "no block landed on the assetless rung"
    elif allowed:
        note = (f"{len(indices)} block(s) on the assetless rung, and this "
                f"channel switched the rung on ({CHANNEL_KEY}.enabled) - "
                f"allowed, and recorded")
    else:
        note = (f"{len(indices)} block(s) would ship with no picture "
                f"(block(s) {indices}) and this channel does not allow the "
                f"per-block assetless rung ({CHANNEL_KEY} is off by default, "
                f"CF-0123). Every rung above it is already spent: the library "
                f"insert of CF-0138 was offered and did not close these blocks "
                f"(the layer is off here, the block is under the 3s floor, or "
                f"nothing in the library stood clear of the M4 floors - the "
                f"plan's `meme.hole_fill` says which), the topic-footage rung "
                f"found no unused usable shot in any source of the topic "
                f"(CF-0337), and no emergency repeat is left (CF-0137). "
                f"WARNING, not a refusal (CF-0330, the user 2026-09-23): the "
                f"plan is written, but a procedural background on this "
                f"channel fails qc_render (CF-0337) - the topic needs more "
                f"material (CF-0338), not a background")
    return {
        "kind": DEFICIT_KIND,
        "rung_enabled": allowed,
        "style": style,
        "style_typographic": flat,
        "applies": not flat,
        "blocks": indices,
        "block_count": len(indices),
        "seconds": seconds,
        "reasons": [a.get("reason") for a in assetless],
        # CF-0139: the same blocks again, as anchors - see anchor_records().
        # Parallel to `blocks`/`reasons` and in the same order, never instead
        # of them.
        "anchors": anchor_records(assetless, blocks),
        # Whether every block has a picture, or the channel allowed the ones
        # that do not. False no longer stops the plan (CF-0330): see `warned`.
        "passed": bool(flat or not indices or allowed),
        # CF-0330: True when `passed` is False and the gate warned instead of
        # refusing - the plan is built with the holes on the procedural rung.
        "warned": not bool(flat or not indices or allowed),
        "mode": "warn",
        "note": note,
    }


def report_lines(rec):
    """The stderr lines - written on a pass too, for the same reason the
    two-source gate writes its passing lines (CF-0118): a run that never
    says whether it shipped a picture in every block cannot be audited
    afterwards, and this is the field CF-0123 was decided on."""
    verdict = ("passed" if rec["passed"]
               else "WARNING" if rec.get("warned") else "REFUSED")
    lines = [f"assetless-block rung {verdict}: {rec['note']}"]
    for i, reason in zip(rec["blocks"], rec["reasons"]):
        lines.append(f"  block {i}: {reason}")
    return lines


def write_deficit(output, rec, hole_fill=None):
    """The refused plan's deficit, beside where the plan would have been
    (`plan.assetless-rung.json`).

    Same move as CF-0118's `plan.two-source-gate.json`, and for the same
    reason: there is no plan file to carry the CF-0057-shaped record, and
    the caller has to be able to read the shortfall rather than parse
    stderr. CF-0139 decides what the registry does with it.

    `hole_fill` is the CF-0138 library rung's own record for this same set of
    blocks - `meme.hole_fill` as it would have been written into the plan.
    It is passed here for one reason: on a refusal there *is* no plan, so on
    exactly the runs where its `refused[]` codes matter most they used to go
    to stderr and nowhere else, while the record that survives carried only
    the gate's prose. The rotation reads this node at the top level (and
    `meme.hole_fill` as a fallback) and prefers its outcome codes to any
    reading of prose, because they are a closed list and prose is not.

    Optional, and absent rather than empty when the caller has nothing: a
    node that is there always would make "the layer said nothing" and "the
    layer was never asked" the same sentence, which is what
    `meme_layer.empty_hole_fill()` exists to keep apart."""
    p = Path(output)
    path = p.with_name(f"{p.stem}.assetless-rung.json")
    payload = {"assetless_rung": rec}
    if hole_fill is not None:
        payload["hole_fill"] = hole_fill
    try:
        json.dump(payload, open(path, "w"), indent=2)
    except OSError as e:
        return f"<not written: {e}>"
    return str(path)


def stage_fields(plan):
    """`videos[].assetless_rung` for write_batch_metadata.py. Always a
    record: a plan built before this gate existed says so rather than
    claiming it was checked."""
    rec = (plan or {}).get("assetless_rung")
    if isinstance(rec, dict):
        return rec
    return {"kind": DEFICIT_KIND, "passed": None, "applies": None,
            "rung_enabled": None, "style": None, "style_typographic": None,
            "blocks": [], "block_count": 0, "seconds": None, "reasons": [],
            "anchors": [], "warned": None, "mode": None,
            "note": "plan predates the assetless-rung gate (CF-0137) - "
                    "not checked"}
