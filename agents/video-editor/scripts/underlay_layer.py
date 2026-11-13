#!/usr/bin/env python3
"""CF-0127: the brainrot underlay, wired into the second plane of the frame.

The decision is not made here. `shared/inserts/underlay.py` in the factory
root owns it - is the layer on for this channel, which loop goes under this
video, what is written about it (CF-0014) - and this file is the Video
Editor half: it calls that module, turns its answer into the two fields the
composition reads, and leaves the plan otherwise untouched.

Where the second plane is
-------------------------
It already existed: `layout.secondary`, the named slot `render/src/lib/
layout.js` resolves and `render/src/components/SecondaryZone.jsx` draws -
"the slot exists for an underlay loop, a reaction, or an ad" (SKILL.md,
Layout). It has been `null` on every plan the factory has ever built, which
is the empty slot CF-0014 describes. A null `secondary` gives its height
back to `main` (full-bleed), and a non-null one takes SECONDARY_HEIGHT of
the frame off the bottom of `main` - the two-plane frame the 2026-09-05
decision asked for: the main content with its own audio in the first plane,
a muted loop in the second.

No relevance judgement, so nothing for CF-0143 to threshold
-----------------------------------------------------------
The lead floor CF-0143 put on the meme layer has no counterpart here, and
not because the loops folder is empty (it is - 0 entries on 2026-09-08).
`inserts_lib.pick_loop()` chooses by `rotation_position()`: sha256 of the
video id modulo the folder size. The loop is picked to be *different from
last time*, never to be *about* the video, so there is no query, no score,
no second place, and no sense in which one loop answers a block better than
another. A floor here would only be an elaborate way of refusing at random.

So the underlay is a *band*, not a wash behind a full-frame picture. That is
deliberate: `main` is `objectFit: cover` over the whole frame, so a layer
mounted behind it would be covered by every block that has a picture and
visible only through the gaps - which is to say, never. The band is the
geometry this composition already has for a second plane, the QC gate and
the degradation chain can name it, and `build_render_plan.split_half_size()`
already frames CF-0050's side-by-side halves against `main`'s height rather
than the frame's, so the halves follow the band down without a change here.

Decided before the blocks, unlike every other insert layer
----------------------------------------------------------
The meme (CF-0067), sound (CF-0068) and proof (CF-0071) layers are overlays
on finished blocks: they run at the end of `build_render_plan.py` and change
nothing about the frame. This one changes `layout`, and `layout` is what
every block is framed and cropped against, so it is decided *first* - right
after the voice-over's length is known and before the block loop - and
merged into the finished plan at the end with the others. Running it late
would leave the halves and the crops of a two-plane video framed against a
one-plane frame.

The end card is not underlaid
-----------------------------
`video_seconds` is the narration's length (`plan["duration"]["actual"]`),
never the composition's: CF-0117's card owns the frame it is on - the
watermark and the captions are already hidden under it and a comparison line
is cut off at its first frame - and a loop still moving in a band under the
channel's signature reads as the file not having ended. `Video.jsx` mounts
the band in a Sequence that stops where the card is mounted.

Degradation
-----------
Everything here is opt-in twice over: the channel switch has to be on *and*
a file has to be found. Any other answer (`layer_disabled`, `library_empty`,
`all_skipped`, `file_missing`, and a factory root with no underlay.py in it)
leaves `layout.secondary` null, writes no `secondary_source`, and leaves the
plan byte-for-byte what it would have been without the layer apart from
`plan["underlay"]`, which says what happened and why. A video with no
underlay is never a failed video.

Factory root: `meme_layer.factory_root()` - $FACTORY_ROOT, else the checkout
above this repo - so a test points every insert layer at one temp library.

Usage:
    underlay_layer.py <plan.json> --video-id <id> [--channel <id|path.json>]
        [--root <factory root>] [--write]
"""
import argparse
import json
import sys
from pathlib import Path

import meme_layer
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

LAYER = "underlay"
STAGE_FIELD = "underlay"           # plan["underlay"] / videos[].underlay
SOURCE_FIELD = "secondary_source"  # plan["secondary_source"], the composition's prop
FACTORY_ROOT_ENV = meme_layer.FACTORY_ROOT_ENV

# The band's height as a fraction of the frame, and the default
# render/src/lib/layout.js already applies to a `secondary` zone that does
# not name one. Written into the plan explicitly all the same: a geometry
# that lives only as a default in the renderer is a geometry no plan records.
SECONDARY_HEIGHT = 0.28

# What the composition is told to do with the file. `still` and
# `loop_or_trim` are underlay.py's FIT_* values; `clip`/`still` is the
# `source.kind` SecondaryZone.jsx switches on.
KIND_CLIP = "clip"
KIND_STILL = "still"

# The reason a plan carries when the factory root has no underlay.py: the
# layer cannot run, which reads as off. Same closed vocabulary as the
# module's REASONS - a free-text reason is a reason nobody counts.
REASON_DISABLED = "layer_disabled"


def factory_root():
    return meme_layer.factory_root()


def _module(root=None):
    """`underlay` from <root>/shared/inserts, or None when the root has no
    such module - an older checkout, or a temp root built for another
    layer's tests. Never raises: a missing module is the layer being off."""
    path = str(Path(root or factory_root()) / "shared" / "inserts")
    if not (Path(path) / "underlay.py").exists():
        return None
    if path not in sys.path:
        sys.path.insert(0, path)
    try:
        import underlay
    except ImportError:
        return None
    return underlay


def unreachable_record(video_id, root):
    """The plan record for a root with no underlay.py - the same shape
    plan_underlay() returns, so nothing downstream has two shapes to read."""
    return {
        "layer": LAYER, "video_id": video_id, "enabled": False,
        "applied": False, "reason": REASON_DISABLED, "entry": None,
        "path": None, "media": None,
        "treatment": {"audio": "muted", "fit": None, "loops_needed": None},
        "inserts": [],
        "library": {"root": str(Path(root) / "shared" / "inserts"),
                    "entries": 0, "eligible": 0, "skipped": 0},
        "note": f"no shared/inserts/underlay.py under {root} - the layer cannot run",
    }


def plan_underlay(video_id, channel_cfg, root=None, video_seconds=None):
    """The factory's answer for this video, or the unreachable record.

    video_seconds is the *narration's* length, not the composition's: the
    band stops where CF-0117's end card starts (see the module docstring).
    """
    root = Path(root) if root else factory_root()
    module = _module(root)
    if module is None:
        return unreachable_record(video_id, root)
    return module.plan_underlay(video_id, channel_cfg, root=root,
                                video_seconds=video_seconds)


# --------------------------------------------------------------------------
# the two fields the composition reads
# --------------------------------------------------------------------------

def layout_secondary(record):
    """`layout.secondary` for this answer: the band when a loop was applied,
    None otherwise (which is what every plan before this layer carried, and
    what `resolveZones` turns back into a full-bleed `main`)."""
    if not (record or {}).get("applied"):
        return None
    return {"height": SECONDARY_HEIGHT, "kind": LAYER}


def secondary_source(record):
    """`plan["secondary_source"]` - the prop SecondaryZone.jsx draws.

    `kind` is what the component switches on (`clip` -> OffthreadVideo,
    anything else -> Img); `muted` and `loop` carry underlay.py's treatment
    onto the frame, and `loops_needed` is how many repeats the loop needs to
    cover the span (informational - Remotion's own `loop` does the repeating).
    """
    if not (record or {}).get("applied"):
        return None
    treatment = record.get("treatment") or {}
    fit = treatment.get("fit")
    entry = record.get("entry") or {}
    return {
        "layer": LAYER,
        "id": entry.get("id"),
        "kind": KIND_STILL if record.get("media") == "image" else KIND_CLIP,
        "src": record.get("path"),
        # Fixed by the 2026-09-05 decision, not by the channel: the main
        # content has the only audio track in the video.
        "muted": treatment.get("audio", "muted") == "muted",
        "loop": fit != "still",
        "fit": fit,
        "loops_needed": treatment.get("loops_needed"),
        "object_fit": "cover",
        # CF-0117: the band is mounted for the narration and stops where the
        # end card is mounted. Recorded so the plan says it, not only the JSX.
        "span": "narration",
    }


def apply_to_plan(plan, record):
    """Merge one answer into a render plan in place: `plan["underlay"]` (the
    whole answer, always, applied or not) and - only when a loop was applied
    - `plan["secondary_source"]` and `plan["layout"]["secondary"]`. Returns
    the plan.

    A plan that got no underlay is byte-identical to a plan built with the
    layer absent apart from `plan["underlay"]`: no source, no band, no note
    in `plan["notes"]`.
    """
    record = dict(record or {})
    # The file the renderer will actually serve. render_video.py stages it
    # into render/public/ beside the block assets and rewrites both this and
    # secondary_source.src, so the record says what was served, not what was
    # chosen (they differ once staged).
    if record.get("applied") and record.get("path"):
        record["render_src"] = record["path"]
    plan[STAGE_FIELD] = record
    source = secondary_source(record)
    if source is not None:
        plan[SOURCE_FIELD] = source
        layout = plan.setdefault("layout", {})
        layout["secondary"] = layout_secondary(record)
    return plan


def report_line(record):
    """One line for build_render_plan.py's stderr summary, in the shape the
    other layers print."""
    record = record or {}
    if record.get("applied"):
        t = record.get("treatment") or {}
        loops = t.get("loops_needed")
        return (f"UNDERLAY: {(record.get('entry') or {}).get('id')} in the second plane "
                f"({t.get('fit')}, muted"
                + (f", {loops} loop(s)" if loops else "") + ")")
    return f"UNDERLAY: none - {record.get('reason')} ({record.get('note')})"


# --------------------------------------------------------------------------
# what lands in 05-video-editor.json
# --------------------------------------------------------------------------

def stage_record(plan):
    """`videos[].underlay` for a plan, or None for a plan built before this
    layer existed (which is not the same as a plan that got no underlay -
    that one has a record saying why)."""
    record = plan.get(STAGE_FIELD)
    if not isinstance(record, dict):
        return None
    module = _module()
    if module is not None:
        return module.stage_record(record)
    return {
        "applied": record.get("applied", False),
        "reason": record.get("reason"),
        "id": (record.get("entry") or {}).get("id"),
        "file": (record.get("entry") or {}).get("file"),
        "treatment": dict(record.get("treatment") or {}),
        "library": dict(record.get("library") or {}),
        "note": record.get("note", ""),
    }


def merge_inserts(existing, records):
    """videos[].inserts[] with this layer's records replacing this layer's
    previous ones and every other layer's (meme, sound, proof) left alone -
    the same merge underlay.write_stage_record() does, so the layers can run
    in any order."""
    kept = [r for r in (existing or [])
            if not (isinstance(r, dict) and r.get("layer") == LAYER)]
    return kept + list(records)


def write_stage_record(video_record, plan):
    """Write this layer's half of one videos[] record: the provenance under
    `inserts[]` and the summary under `underlay`. Delegates to the factory's
    own `underlay.write_stage_record()` when the module is reachable (it is
    the one that owns the shape); falls back to the identical merge here
    when it is not. No-op on a plan that carries no underlay record."""
    record = plan.get(STAGE_FIELD) if isinstance(plan, dict) else None
    if not isinstance(record, dict):
        return video_record
    module = _module()
    if module is not None:
        return module.write_stage_record(video_record, record)
    video_record["inserts"] = merge_inserts(video_record.get("inserts"),
                                            record.get("inserts") or [])
    video_record[STAGE_FIELD] = stage_record(plan)
    return video_record


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(
        description="plan the second-plane underlay for one render plan")
    ap.add_argument("plan")
    ap.add_argument("--video-id", help="default: the plan file's stem")
    ap.add_argument("--channel", help="channel id under <root>/channels or a path to a .json")
    ap.add_argument("--root", help=f"factory root (default ${FACTORY_ROOT_ENV} or the checkout)")
    ap.add_argument("--write", action="store_true", help="merge the answer into the plan file")
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.plan))  # CF-0107

    root = Path(a.root).resolve() if a.root else factory_root()
    plan = json.load(open(a.plan))
    seconds = (plan.get("duration") or {}).get("actual")
    record = plan_underlay(a.video_id or Path(a.plan).stem,
                           meme_layer.load_channel(a.channel, root),
                           root=root, video_seconds=seconds)
    if a.write:
        apply_to_plan(plan, record)
        json.dump(plan, open(a.plan, "w"), indent=2)
    print(json.dumps(record, ensure_ascii=False, indent=2))
    print(report_line(record), file=sys.stderr)
    return 0


@video_script("video-editor", "underlay", name="underlay_layer.py")
def cli():
    sys.exit(main())


if __name__ == "__main__":
    cli()
