#!/usr/bin/env python3
"""CF-0118: the gate of two independent footage sources.

A video whose every frame of footage comes from one upload is a
"compilation with no original content added" in YouTube's own words - the
one thing the policy names as not even eligible for the Creator Pool. The
alternation of sides (CF-0050) is a *preference* built on top of the same
requirement; this is the prohibition under it.

What counts as one source
-------------------------
Not a `video_id`. After CF-0080 (footage-indexer's content dedup) the
honest unit is the *canonical* source: search returns re-uploads of the
same trailer, and three uploads of one teaser are one trailer no matter
how many ids they carry. So a block's source is

    shots.json `source` (its stem is the video id)
      -> collapsed through the batch's alias table
      -> a canonical id

and the gate counts the canonical ids the blocks actually *use*, never the
ones the pool merely offered. A pool of five uploads that the resolver
never reached buys nothing: what is on screen is what a viewer sees, and
what the policy is about.

Where the alias table comes from
--------------------------------
Three shapes, all read by `load_aliases()`:

  * `<batch>/01b-footage-index.json` - `aliases: [{video_id, alias_of,
    distance, ...}]`, the flat list CF-0080's `ingest_batch.py` writes.
  * `<batch>/work/footage-aliases.json` - `{topic_id: [alias record, ...]}`,
    the same records grouped by topic.
  * `--alias-groups <file>` - a plain grouping, `[[canonical, alias, ...],
    ...]` or `{canonical: [alias, ...]}`. This exists for batches that
    predate CF-0080 (`2026-08-31T2155Z`, `2026-09-03T2037Z`): their
    duplicates are real and documented, but no ingest ever wrote a table
    for them, so the item-3 measurement feeds CF-0080's calibrated groups
    in by hand rather than pretending the batch was deduplicated.

Our own recording (CF-0567)
---------------------------
`own_capture-<id>` - the factory's screen recording of a public page
(`capture_tool.py`, the root's `docs/tech-footage.md`) - is not somebody's
upload. The gate's own definition is about *borrowed* footage: a video
"whose every frame of footage comes from one upload". So:

  * an own capture is never counted as an independent source: two
    recordings of two pages are not "two sources" in this sense, they are
    both ours (`canonical_ids` and `count` hold borrowed sources only; the
    recordings are listed apart, `own_capture_ids`);
  * a block that shows only our recording is not borrowed footage
    (`own_capture_blocks`, not `footage_blocks`) - a video of nothing but
    recordings is entirely ours and the rule does not apply, as for a video
    of nothing but type;
  * a video whose recordings are on screen at least as long as all its
    borrowed footage together (`own_capture_seconds` >= `borrowed_seconds`)
    is not a compilation of anybody's upload whatever the borrowed count -
    the gate passes and says why. Below that the borrowed sources are
    counted as always. A vendor's quote is held to its own cap besides
    (`proof_quote_cap.py`: never the base of a video).

Channels without own capture (ExampleFilm, ExampleScience) are judged
exactly as before: their plans hold no `own_capture-` id.

Our own graphic (CF-0689)
-------------------------
`asset.kind: "own_graphic"` - a graphic the factory draws in Remotion from
the script's facts - names no source at all (the kind is not in
`FOOTAGE_KINDS`, so `block_sources()` is [] and no credit is made). It is
ours in the same sense as a recording: a video of nothing but graphics (and
recordings) is entirely ours and the rule does not apply; graphics on screen
count with the recordings (`own_graphic_seconds` beside
`own_capture_seconds`) against the borrowed footage. Plans without one are
judged exactly as before.

Cheap on purpose: json + string work, no CLIP, no ffmpeg, no network. The
fingerprinting that decides what is a re-upload already happened in
footage-indexer; this reads its answer.

Two modes (channels/<channel>.json `video_editor.two_source_gate`)
------------------------------------------------------------------
  * `"measure"` - the default. The verdict goes on the plan
    (`plan["two_source_gate"]`, `videos[].two_source_gate`) and on stderr,
    the plan is built, nothing is rejected - and nothing is written into
    `rhythm["rhythm_shortfalls"]`. That list is CF-0057's record of *rhythm*
    deficits; a measurement that returns nobody's script is not a deficit
    the Analyst has been asked to act on, and adding one there lengthens the
    shortfall list of every plan built off a single-source pool.
  * `"enforce"` - a failing gate refuses the plan: `TWO-SOURCE GATE
    FAILED` on stderr and exit 2, the same path a rejected asset takes,
    plus the machine-readable deficit (`deficit()` below - `kind:
    "two_source_gate"`, the CF-0057 shortfall shape) written to
    `plan.two-source-gate.json` beside where the plan would have been, so
    the script goes back with a deficit that can be read rather than a
    paragraph that has to be parsed. This is the only mode that produces a
    deficit record at all: a returned script has one, a measured one does
    not.

The default is `measure` because of item 3 of the task: on the batches on
disk the pass rate is far under 50 %, and a gate switched on over a pool
that cannot feed it would reject nearly the whole stream. The pool widens
first (Trend Hunter / Footage Indexer), the mode flips after.
"""
import argparse
import json
import re
from pathlib import Path

import _clip_names  # CF-0665: the source id in a clip name; CF-0567 own capture

REQUIRED_SOURCES = 2

MODE_MEASURE = "measure"
MODE_ENFORCE = "enforce"
MODES = (MODE_MEASURE, MODE_ENFORCE)

# channels/<channel>.json key that flips the mode. Read by
# build_render_plan.py through mode_from_channel(); absent = MODE_MEASURE.
CHANNEL_KEY = "video_editor.two_source_gate"

# The shortfall `kind` a failing gate contributes to the CF-0057 record.
DEFICIT_KIND = "two_source_gate"

# The asset kinds that put somebody else's footage on screen. `card` is not
# among them on purpose: `asset_kind: "card"` is a card this factory draws
# (build_render_plan.py's own comment on the distinction), and a title card
# *lifted* from a trailer arrives as a `clip`/`still` with `is_card` set, so
# it is counted where it belongs. `procedural`/`typographic`/`text` show our
# own type, which is exactly the "original content added" the policy asks
# for - and a block degraded down to one of those shows no footage even
# though it still carries the `shot` it was cut from, so its former source
# must not be counted as a source on screen.
#
# CF-0120: `sequence` is one crossing of the axis cut from several distinct
# shots (build_render_plan.py), so it shows footage like the rest - and it can
# show more than one source in the one block, which `_asset_sources()` below
# reads out of its `cuts` for exactly the reason a `split` block's halves are
# read: a source on screen is a source on screen whichever picture of the block
# it arrived in.
FOOTAGE_KINDS = ("clip", "still", "split", "sequence")
# CF-0689: the factory's own graphic - ours, never a borrowed source.
OWN_GRAPHIC_KIND = "own_graphic"

# `a00_<video_id>_s009.mp4`, `nc01_<video_id>_s008.mp4`,
# `s01_held_a01_<video_id>_s011.png` - every clip/held-frame name
# resolve_anchors.py writes carries the source id between the attempt
# prefix and the `_sNNN` shot suffix. A YouTube id is exactly 11 chars of
# [A-Za-z0-9_-], which is what makes this unambiguous even for ids that
# contain underscores themselves (`H6RXVb_J5J4`, `_LE1L4Huyys`); an archive
# file (CF-0665) is `nasa-<id>` / `commons-<pageid>` of any length. Both are
# read by _clip_names, the one reading the Editor has.


def source_id(value):
    """The canonical-*shape* source id in `value`, or None.

    Accepts what the several places that name a source actually hold: a
    shots.json `source` path (`.../shared/footage/<id>.mp4`), a block's
    `shot` key (`<id>:<n>`), a cut clip or held frame path
    (`a00_<id>_s009.mp4`). None when nothing id-shaped is in there - an
    old batch's `s0.mp4` (2026-08-30T1759Z, before ids were in the
    filenames) is genuinely unidentifiable and is reported as such, never
    guessed at.
    """
    if not value:
        return None
    s = str(value).strip()
    if not s:
        return None
    if ":" in s and "/" not in s:          # a `shot` key: "<id>:<n>"
        head = s.split(":")[0].strip()
        return head or None
    stem = Path(s).stem
    hit = _clip_names.clip_shot(stem)
    if hit:
        return hit[0]
    # A bare shots.json `source` / media path: the stem *is* the id - but
    # only when it is id-shaped. Anything looser reads `frame_4_clean.png`
    # (batch 2026-08-28T2016Z's stills, which came from no indexed source at
    # all) as four separate sources and hands that batch a PASS it has not
    # earned. An unrecognisable name is unidentified footage, and the gate
    # says so rather than inventing a source for it.
    if _clip_names.is_source_id(stem):
        return stem
    return None


def _asset_sources(asset):
    """Every source id an asset names, in order. A `side_by_side` block
    (CF-0050) has two halves and therefore two sources; both count."""
    out = []
    if not isinstance(asset, dict):
        return out
    for half in asset.get("halves") or []:
        if isinstance(half, dict):
            out += [v for v in (source_id(half.get("shot")),
                                source_id(half.get("src")),
                                source_id(half.get("clip"))) if v][:1]
    # CF-0120: a `sequence` block's pictures, in order. Same reading as a
    # half's - the first id-shaped field of each one counts once.
    for cut in asset.get("cuts") or []:
        if isinstance(cut, dict):
            out += [v for v in (source_id(cut.get("shot")),
                                source_id(cut.get("src")),
                                source_id(cut.get("asset"))) if v][:1]
    for key in ("source", "shot", "src", "clip"):
        vid = source_id(asset.get(key))
        if vid:
            out.append(vid)
            break
    return out


def block_sources(block):
    """The source ids one block's picture comes from ([] for a procedural
    or typographic block, which has no footage in it at all)."""
    if not isinstance(block, dict):
        return []
    out = []
    for key in ("source", "shot"):
        vid = source_id(block.get(key))
        if vid:
            out.append(vid)
            break
    out += [v for v in _asset_sources(block.get("asset")) if v not in out]
    if not out:
        # A storyboard block names its file in `asset` (a string), where a
        # plan block has a dict.
        vid = source_id(block.get("asset")) if isinstance(block.get("asset"), str) else None
        if vid:
            out.append(vid)
    return out


def _first_id(*values):
    for v in values:
        vid = source_id(v)
        if vid:
            return vid
    return None


def block_source_seconds(block):
    """CF-0567: {source id: seconds on screen} of one block's picture - a
    `sequence` cut or a split half's cut by its own `seconds`, anything else
    the whole block. A split's two halves are both on screen the whole time,
    so each counts in full. {} for a block that shows no footage."""
    if not isinstance(block, dict):
        return {}
    asset = block.get("asset") if isinstance(block.get("asset"), dict) else None
    kind = asset.get("kind") if asset else block.get("asset_kind")
    if not (kind in FOOTAGE_KINDS or kind is None):
        return {}
    try:
        dur = max(0.0, float(block.get("end", 0.0)) - float(block.get("start", 0.0)))
    except (TypeError, ValueError):
        dur = 0.0
    out = {}

    def add(vid, secs):
        if vid:
            out[vid] = round(out.get(vid, 0.0) + max(0.0, float(secs)), 3)

    def add_cuts(cuts, whole):
        named = [c for c in cuts if isinstance(c, dict)]
        for c in named:
            secs = c.get("seconds")
            add(_first_id(c.get("shot"), c.get("src"), c.get("asset")),
                secs if isinstance(secs, (int, float)) else whole / max(1, len(named)))

    if asset and asset.get("cuts"):
        add_cuts(asset["cuts"], dur)
    elif asset and asset.get("halves"):
        for half in asset["halves"]:
            if not isinstance(half, dict):
                continue
            if half.get("cuts"):
                add_cuts(half["cuts"], dur)
            else:
                add(_first_id(half.get("shot"), half.get("src"), half.get("clip")), dur)
    else:
        for vid in block_sources(block):
            add(vid, dur)
    return out


def own_and_borrowed_seconds(plan_or_storyboard):
    """CF-0567: (seconds our own recordings are on screen, seconds borrowed
    footage is) over the blocks - by block_source_seconds()."""
    own = borrowed = 0.0
    for b in _blocks_of(plan_or_storyboard):
        for vid, secs in block_source_seconds(b).items():
            if _clip_names.is_own_capture(vid):
                own += secs
            else:
                borrowed += secs
    return round(own, 3), round(borrowed, 3)


def own_graphic_seconds(plan_or_storyboard):
    """CF-0689: seconds the factory's own graphics are on screen."""
    total = 0.0
    for b in _blocks_of(plan_or_storyboard):
        if not isinstance(b, dict):
            continue
        asset = b.get("asset") if isinstance(b.get("asset"), dict) else None
        kind = asset.get("kind") if asset else b.get("asset_kind")
        if kind != OWN_GRAPHIC_KIND:
            continue
        try:
            total += max(0.0, float(b.get("end", b.get("_end", 0.0)))
                         - float(b.get("start", b.get("_start", 0.0))))
        except (TypeError, ValueError):
            continue
    return round(total, 3)


def load_indexes(indexes):
    """{video_id: shots.json `source` path} from `--index` shots.json files
    (paths or already-loaded dicts).

    The gate does not need these to count - a block's own `shot` key
    carries the id - so a missing or unreadable index is not an error. What
    they add is the media path behind each id (for the report) and the
    `fingerprint` header CF-0080 writes, which is how a source that is in
    the pool under two ids is legible even without an alias table.
    """
    out = {}
    for idx in indexes or ():
        data = idx
        if not isinstance(data, dict):
            try:
                data = json.loads(Path(idx).read_text())
            except (OSError, ValueError):
                continue
        src = data.get("source")
        vid = source_id(src)
        if not vid:
            continue
        out[vid] = {"source": src, "fingerprint": data.get("fingerprint")}
    return out


def alias_groups_map(obj):
    """{alias: canonical} from a plain grouping: `[[canonical, alias, ...]]`
    or `{canonical: [alias, ...]}`. The first id of a list is the canonical
    one, the way CF-0080 keeps one canonical per group of re-uploads."""
    out = {}
    if isinstance(obj, dict):
        # Either {canonical: [aliases]} or the wrapper {"groups": [...]}.
        if isinstance(obj.get("groups"), list):
            return alias_groups_map(obj["groups"])
        for canon, members in obj.items():
            for vid in (members if isinstance(members, list) else [members]):
                if vid and vid != canon:
                    out[str(vid)] = str(canon)
        return out
    for group in obj or []:
        ids = [str(v) for v in group if v]
        for vid in ids[1:]:
            out[vid] = ids[0]
    return out


def _alias_records(obj):
    """The {video_id, alias_of} records inside either CF-0080 shape."""
    if isinstance(obj, dict):
        if isinstance(obj.get("aliases"), list):        # 01b-footage-index.json
            return [r for r in obj["aliases"] if isinstance(r, dict)]
        # work/footage-aliases.json: {topic_id: [record, ...]}
        recs = []
        for v in obj.values():
            if isinstance(v, list):
                recs += [r for r in v if isinstance(r, dict)]
        return recs
    if isinstance(obj, list):
        return [r for r in obj if isinstance(r, dict)]
    return []


def load_aliases(*sources):
    """{alias id: canonical id} from any mix of CF-0080 alias tables and
    plain groupings (paths or loaded objects). Unreadable sources are
    skipped: an absent table means "no known duplicates", which is exactly
    what a batch ingested before CF-0080 can honestly say."""
    out = {}
    for src in sources:
        obj = src
        if isinstance(src, (str, Path)):
            try:
                obj = json.loads(Path(src).read_text())
            except (OSError, ValueError):
                continue
        recs = _alias_records(obj)
        if recs and any(r.get("alias_of") for r in recs):
            for r in recs:
                vid, canon = r.get("video_id"), r.get("alias_of")
                if vid and canon and vid != canon:
                    out[str(vid)] = str(canon)
        else:
            out.update(alias_groups_map(obj))
    return out


def canonical(vid, aliases=None):
    """`vid` collapsed through the alias table, following a chain (an alias
    of an alias) and never looping."""
    if not vid:
        return None
    seen = {vid}
    cur = vid
    while aliases and cur in aliases:
        nxt = aliases[cur]
        if not nxt or nxt in seen:
            break
        cur = nxt
        seen.add(cur)
    return cur


def _blocks_of(plan_or_storyboard):
    if isinstance(plan_or_storyboard, dict):
        blocks = plan_or_storyboard.get("blocks")
        return blocks if isinstance(blocks, list) else []
    if isinstance(plan_or_storyboard, list):
        return plan_or_storyboard
    return []


def independent_sources(plan_or_storyboard, indexes=(), aliases=None):
    """The canonical sources the blocks actually use.

    Returns
      canonical_ids  - sorted, deduplicated: the count the gate judges
      per_block      - one record per block: {index, kind, sources,
                       canonical, unidentified}
      aliased_away   - [{video_id, alias_of}] for every used id that
                       collapsed onto another one; this is the difference
                       CF-0080 makes, written down instead of assumed
      blocks_by_source - {canonical id: [block index, ...]}
      unidentified_blocks - footage blocks whose source could not be named
      own_capture_ids / own_capture_blocks - CF-0567: our own recordings
                       on screen and the blocks that show nothing else;
                       neither counts as borrowed footage
    """
    aliases = aliases or {}
    idx = load_indexes(indexes)
    per_block, canon_ids, aliased, by_source, unnamed = [], [], [], {}, []
    footage_blocks, own_ids, own_blocks, graphic_blocks = [], [], [], []
    for i, b in enumerate(_blocks_of(plan_or_storyboard)):
        asset = b.get("asset") if isinstance(b, dict) else None
        kind = asset.get("kind") if isinstance(asset, dict) else b.get("asset_kind")
        if kind == OWN_GRAPHIC_KIND:
            graphic_blocks.append(i)
        # A block that shows our own type shows no footage, whatever it
        # carries: a clip degraded to `typographic` (CF-0031) keeps its
        # `shot` for the rhythm's sake, and counting that as a source on
        # screen would let a video of nothing but cards claim two trailers.
        # A block whose kind we cannot read is judged by what it names.
        shows_footage = kind in FOOTAGE_KINDS or kind is None
        srcs = block_sources(b) if shows_footage else []
        # CF-0567: our own recording is not borrowed footage - listed apart,
        # never counted as a source (the module docstring).
        own = [v for v in srcs if _clip_names.is_own_capture(v)]
        borrowed = [v for v in srcs if v not in own]
        for vid in own:
            if vid not in own_ids:
                own_ids.append(vid)
        if own and not borrowed:
            own_blocks.append(i)
        elif kind in FOOTAGE_KINDS or (kind is None and srcs):
            footage_blocks.append(i)
        cans = []
        for vid in borrowed:
            can = canonical(vid, aliases)
            if can != vid and not any(a["video_id"] == vid for a in aliased):
                aliased.append({"video_id": vid, "alias_of": can})
            if can not in cans:
                cans.append(can)
            if can not in canon_ids:
                canon_ids.append(can)
            by_source.setdefault(can, [])
            if i not in by_source[can]:
                by_source[can].append(i)
        # A block with a picture but no nameable source is footage we cannot
        # attribute; it is listed, and it counts towards nothing.
        unidentified = bool(not srcs and kind in FOOTAGE_KINDS)
        if unidentified:
            unnamed.append(i)
        per_block.append({"index": i, "kind": kind, "sources": srcs,
                          "canonical": cans, "unidentified": unidentified})
    return {
        "canonical_ids": sorted(canon_ids),
        "per_block": per_block,
        "aliased_away": sorted(aliased, key=lambda a: a["video_id"]),
        "blocks_by_source": {k: by_source[k] for k in sorted(by_source)},
        "unidentified_blocks": unnamed,
        "footage_blocks": footage_blocks,
        "own_capture_ids": sorted(own_ids),
        "own_capture_blocks": own_blocks,
        # CF-0689: blocks that show the factory's own graphic.
        "own_graphic_blocks": graphic_blocks,
        "index_sources": idx,
    }


def gate(count, required=REQUIRED_SOURCES):
    """{passed, count, required, canonical_ids, note}.

    `count` is a number, or the independent_sources() result / a list of
    canonical ids to take the number from - the callers have all three at
    hand and the arithmetic is the same one."""
    ids = []
    if isinstance(count, dict):
        ids = list(count.get("canonical_ids") or [])
        n = len(ids)
    elif isinstance(count, (list, tuple, set)):
        ids = sorted(str(v) for v in count)
        n = len(ids)
    else:
        n = int(count)
    required = int(required)
    passed = n >= required
    named = ", ".join(ids) if ids else "none"
    if passed:
        note = (f"{n} independent footage source(s) on screen ({named}) against a "
                f"floor of {required} - not a single-source compilation")
    elif n == 0:
        note = ("no footage source could be identified in this plan - a video with "
                f"no attributable footage cannot show {required} independent sources")
    else:
        note = (f"every footage block comes from {n} source(s) ({named}) against a "
                f"floor of {required} - YouTube calls a video built from one "
                "upload a 'compilation with no original content added' and does "
                "not admit it to the Creator Pool (CF-0118)")
    return {"passed": passed, "count": n, "required": required,
            "canonical_ids": ids, "note": note}


def mode_from_channel(channel_cfg, default=MODE_MEASURE):
    """The mode from `video_editor.two_source_gate` of a loaded channel
    config: the string itself, or `mode` when the key holds a block. An
    unknown value falls back to the default - a typo in a config must not
    silently reject every plan, nor silently switch the gate off."""
    ve = (channel_cfg or {}).get("video_editor") or {}
    node = ve.get("two_source_gate")
    if isinstance(node, dict):
        node = node.get("mode")
    if isinstance(node, str) and node.strip().lower() in MODES:
        return node.strip().lower()
    return default


def required_from_channel(channel_cfg, default=REQUIRED_SOURCES):
    ve = (channel_cfg or {}).get("video_editor") or {}
    node = ve.get("two_source_gate")
    if isinstance(node, dict):
        try:
            n = int(node.get("required"))
        except (TypeError, ValueError):
            return default
        return n if n > 0 else default
    return default


def judge(plan_or_storyboard, indexes=(), aliases=None,
          required=REQUIRED_SOURCES, mode=MODE_MEASURE):
    """The whole record that goes on the plan, into `05-video-editor.json`
    and onto the RUN_LOG line - the gate's verdict plus what it was
    computed from."""
    found = independent_sources(plan_or_storyboard, indexes, aliases)
    verdict = gate(found, required)
    # A video with no borrowed footage in it at all - every block
    # typographic or procedural, the bottom rung of the degradation chain -
    # has nothing for this rule to bite on: it is not a compilation of
    # anybody's material, it is entirely ours. Failing it would refuse the
    # one fallback the pipeline drops to when the footage is unusable, which
    # is the opposite of what the gate is for.
    applies = bool(found["footage_blocks"])
    own_ids = found["own_capture_ids"]
    own_s, borrowed_s = own_and_borrowed_seconds(plan_or_storyboard)
    graphic_s = own_graphic_seconds(plan_or_storyboard)
    if not applies:
        ours = []
        if own_ids:
            ours.append("recording (own_capture: " + ", ".join(own_ids) + ")")
        if graphic_s > 0:
            ours.append(f"graphic (own_graphic, {graphic_s:.1f}s)")
        verdict = {**verdict, "passed": True, "note": (
            "no borrowed footage in this video at all - every block is our own "
            + (", ".join(ours) + ", type or procedural" if ours else "type or procedural")
            + ", so the single-source rule does not apply")}
    elif ((own_ids or graphic_s > 0) and not verdict["passed"]
          and own_s + graphic_s >= borrowed_s):
        # CF-0567: the base of the video is our own recording - not a
        # compilation of anybody's upload, whatever the borrowed count.
        # CF-0689: our own graphics count beside the recordings.
        what = []
        if own_ids:
            what.append(f"{own_s:.1f}s of own_capture: {', '.join(own_ids)}")
        if graphic_s > 0:
            what.append(f"{graphic_s:.1f}s of own_graphic")
        verdict = {**verdict, "passed": True, "note": (
            f"our own footage is the base of this video ({'; '.join(what)}) against "
            f"{borrowed_s:.1f}s of borrowed footage from {verdict['count']} source(s) - "
            f"not a compilation of one upload (CF-0118 / CF-0567"
            + (" / CF-0689)" if graphic_s > 0 else ")"))}
    return {
        "passed": verdict["passed"],
        "applies": applies,
        "count": verdict["count"],
        "required": verdict["required"],
        "canonical_ids": verdict["canonical_ids"],
        "aliased_away": found["aliased_away"],
        "mode": mode if mode in MODES else MODE_MEASURE,
        "blocks_by_source": found["blocks_by_source"],
        "unidentified_blocks": found["unidentified_blocks"],
        "footage_blocks": found["footage_blocks"],
        # CF-0567: our own recordings, apart from the borrowed count.
        "own_capture_ids": own_ids,
        "own_capture_blocks": found["own_capture_blocks"],
        "own_capture_seconds": own_s,
        # CF-0689: the factory's own graphics, ours like the recordings.
        "own_graphic_blocks": found["own_graphic_blocks"],
        "own_graphic_seconds": graphic_s,
        "borrowed_seconds": borrowed_s,
        "note": verdict["note"],
    }


def deficit(rec):
    """The machine-readable deficit of a *returned* gate, in the shape
    `rhythm.rhythm_shortfalls()` records use (CF-0057): the script comes
    back with this, not with a line of prose to re-read.

    Only the `enforce` path builds one, into `plan.two-source-gate.json`
    (there is no plan file to carry it). A `measure` run has a verdict, not
    a deficit, and leaves `rhythm_shortfalls` untouched - see the module
    docstring's two modes."""
    blocks = list(rec.get("footage_blocks") or sorted(
        {i for idxs in (rec.get("blocks_by_source") or {}).values() for i in idxs}
        | set(rec.get("unidentified_blocks") or [])))
    return {
        "kind": DEFICIT_KIND,
        "count": rec.get("count"),
        "required": rec.get("required"),
        "canonical_ids": list(rec.get("canonical_ids") or []),
        "aliased_away": list(rec.get("aliased_away") or []),
        "blocks": blocks,
        "blocks_by_source": dict(rec.get("blocks_by_source") or {}),
        "unidentified_blocks": list(rec.get("unidentified_blocks") or []),
        "missing_sources": max(0, int(rec.get("required") or 0) - int(rec.get("count") or 0)),
        "note": rec.get("note"),
    }


def report_lines(rec):
    """The stderr lines - one verdict line, then where the footage came
    from. Written on a pass as well as a failure: a run that never says
    how many sources it used cannot be audited later."""
    verdict = "passed" if rec["passed"] else "FAILED"
    lines = [f"two-source gate {verdict} ({rec['mode']}): {rec['note']}"]
    for src, blocks in (rec.get("blocks_by_source") or {}).items():
        lines.append(f"  {src}: block(s) {blocks}")
    for a in rec.get("aliased_away") or []:
        lines.append(f"  {a['video_id']} counted as {a['alias_of']} "
                     "(re-upload of the same material, CF-0080)")
    if rec.get("unidentified_blocks"):
        lines.append(f"  block(s) {rec['unidentified_blocks']}: footage with no "
                     "identifiable source - counted towards nothing")
    if rec.get("own_capture_ids"):
        lines.append(f"  own capture (ours, not a borrowed source): "
                     f"{', '.join(rec['own_capture_ids'])} - "
                     f"{rec.get('own_capture_seconds') or 0:.1f}s on screen")
    if rec.get("own_graphic_blocks"):
        lines.append(f"  own graphic (ours, not a borrowed source): block(s) "
                     f"{rec['own_graphic_blocks']} - "
                     f"{rec.get('own_graphic_seconds') or 0:.1f}s on screen")
    return lines


def stage_fields(plan):
    """`videos[].two_source_gate` for write_batch_metadata.py. Always a
    record, never absent: a plan built before this gate existed gets one
    with `mode: null` and `passed: null`, because a plan that never
    measured its sources cannot claim it had two."""
    rec = (plan or {}).get("two_source_gate")
    if isinstance(rec, dict):
        return rec
    return {"passed": None, "applies": None, "count": None,
            "required": REQUIRED_SOURCES, "canonical_ids": [], "aliased_away": [],
            "mode": None, "blocks_by_source": {}, "unidentified_blocks": [],
            "footage_blocks": [], "own_capture_ids": [], "own_capture_blocks": [],
            "note": "plan predates the two-source gate (CF-0118) - not measured"}


def main():
    p = argparse.ArgumentParser(
        description="CF-0118: count the independent footage sources a plan "
                    "or storyboard actually uses, and judge the gate.")
    p.add_argument("plan", help="plan.json or storyboard.json")
    p.add_argument("--index", action="append", default=[],
                   help="a shots.json the plan was resolved against. "
                        "Repeatable; optional (the media path behind each id).")
    p.add_argument("--footage-index", default=None,
                   help="<batch>/01b-footage-index.json - CF-0080's `aliases`.")
    p.add_argument("--aliases", default=None,
                   help="<batch>/work/footage-aliases.json.")
    p.add_argument("--alias-groups", default=None,
                   help="a plain grouping of re-uploads, [[canonical, alias, "
                        "...]] or {canonical: [alias, ...]} - for batches that "
                        "predate CF-0080 and have no alias table of their own.")
    p.add_argument("--required", type=int, default=REQUIRED_SOURCES)
    p.add_argument("--mode", choices=MODES, default=MODE_MEASURE)
    p.add_argument("--json", action="store_true")
    a = p.parse_args()

    aliases = load_aliases(*[s for s in (a.footage_index, a.aliases, a.alias_groups) if s])
    rec = judge(json.loads(Path(a.plan).read_text()), a.index, aliases,
                required=a.required, mode=a.mode)
    if a.json:
        print(json.dumps(rec, indent=2))
    else:
        for line in report_lines(rec):
            print(line)
    return 0 if (rec["passed"] or a.mode == MODE_MEASURE) else 2


if __name__ == "__main__":
    raise SystemExit(main())
