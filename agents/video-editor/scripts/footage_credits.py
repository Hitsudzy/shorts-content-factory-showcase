#!/usr/bin/env python3
"""CF-0664 (VE-1 of the root's docs/science-footage.md): whose footage is in
the video, under what licence, and the credit some origins want on the
picture itself.

Where the rights come from (FI-2, CF-0663 - nothing is judged here):

  * `<batch>/01b-footage-index.json` -> `fetched[].rights`, matched by
    `video_id` - the batch's own fetch;
  * else `<pool>/<id>.shots.json` -> `source_rights` (top level) - a pool
    source the batch did not fetch itself;
  * else nothing: a source indexed before FI-2 has no record, and none is
    made up in its place.

What this module makes of them, both carried on the plan
(`build_render_plan.py`) so the plan stays the one source of what the render
shows:

  * `plan["footage_credits"]` - one row per *judged* source whose shots are
    really on screen (the blocks of the finished plan, not the pool offered),
    in order of first use. The 05-video-editor.json record copies it
    (`videos[].footage_credits`, `stage_fields()`); the Publisher (PUB-1)
    reads it for the card's credit lines.
  * `plan["credit_overlays"]` - the small on-screen credit
    (`© ESA/Hubble · CC BY 4.0`) for the span of every block showing a source
    whose origin's own terms want the credit on the picture (`on_screen:
    true` - ESA, ESA/Hubble, ESO). Drawn by render/src/components/
    FootageCredit.jsx; listed by frame_judge_pack.py as text of ours.

What is never invented (the root doc, «What CF-0664 (PUB-1, VE-1) reads»):

  * a source with `judged: false` (ExampleFilm, a supplement with no licence
    block) or with no record at all gets no row and no overlay - on a channel
    that judges licences the plan's notes name it, on one that does not
    (ExampleFilm) the plan says nothing new;
  * `credit` is printed as is only with `credit_from: "candidate"` (the
    file's own credit line). With `credit_from: "footage_origins"` it is the
    origin's *rule* ("the item's credit, unaltered, e.g. «ESA/Hubble»"), not a
    line: the row says `credit: null`, keeps the rule in `credit_rule` and
    names the origin (`origin_name`, the channel's `footage_origins[].who` up
    to its first bracket); the overlay then names the origin and the licence.
  * the licence is printed only when it is a Creative Commons one, and its
    version only when the licence's own name carries one (an archive's
    `CC BY 4.0`); YouTube's standard licence prints no licence at all.

Our own recording (CF-0567, the root's `docs/tech-footage.md`): a source
`own_capture-<id>` (or one whose rights record says `licence` /
`footage_origin` `own_capture`) is the factory's own footage - no licence is
needed and none granted, the tool and its maker are named by the voice and
the fact's source line. It gets **no** `footage_credits` row and **no**
on-screen credit, and no "nothing judged" note either. What the plan keeps
of it instead is `plan["own_captures"]` (`plan_own_captures()`): the page
URL, the host and the capture host entry, the Space's licence, when it was
recorded and which blocks show it - read from the recorder's sidecar
(`<pool>/<id>.own_capture.json`, capture_tool.py), else from the rights
record's `source_url`; never invented.

A vendor's proof quote (CF-0686, ExampleTech: a rights record with `role:
proof_quote` or `footage_origin: vendor_official`, FI's `quote_channel`) is
credited to the vendor's own channel: when the record carries
`channel_title` (the `official_channels[].channels[].title` its `channel_id`
matched), the row's `credit` is that title and `credit_from` is
`"channel_title"` - the Publisher's `{credit}` prints «Clip: OpenAI · <link>»,
not the origin's `who`. The source URL is kept as is. A quote record without
`channel_title` keeps the old reading (the origin's rule, `credit: null`) and
the plan's notes say so.
"""
import json
import re
from pathlib import Path

import _clip_names  # CF-0567: own capture

FIELD = "footage_credits"
OVERLAYS_FIELD = "credit_overlays"
OWN_CAPTURES_FIELD = "own_captures"
OWN_CAPTURE = "own_capture"

# The licence ids of footage-origin.json `licences.accepted` that name a
# Creative Commons licence, and how one is printed.
CC_LABELS = {"cc_by": "CC BY", "cc_by_sa": "CC BY-SA", "cc0": "CC0"}
VERSION_RE = re.compile(r"(\d+\.\d+)(\s*igo)?", re.I)
SEPARATOR = " · "
COPYRIGHT = "©"
PROOF_QUOTE = "proof_quote"            # rights `role` (FI quote_channel, CF-0567)
VENDOR_OFFICIAL = "vendor_official"    # rights `footage_origin` (CF-0567)
CHANNEL_TITLE = "channel_title"        # credit_from of a quote's credit (CF-0686)


def _str(v):
    return v.strip() if isinstance(v, str) and v.strip() else None


def _read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None


def rights_reader(footage_index=None, shot_dirs=()):
    """`video_id -> (rights record or None, where it was read)`.

    `footage_index` is the batch's 01b-footage-index.json (a path, a loaded
    dict or None); `shot_dirs` the directories whose `<id>.shots.json` may
    carry `source_rights`. `where` is `"01b"`, `"shots.json"` or None."""
    doc = footage_index if isinstance(footage_index, dict) else (
        _read_json(footage_index) if footage_index else None)
    from_01b = {}
    for row in (doc or {}).get("fetched") or []:
        if isinstance(row, dict) and row.get("video_id") and isinstance(row.get("rights"), dict):
            from_01b.setdefault(str(row["video_id"]), row["rights"])
    dirs = [Path(d) for d in shot_dirs or ()]
    cache = {}

    def read(vid):
        vid = str(vid)
        if vid in from_01b:
            return from_01b[vid], "01b"
        if vid not in cache:
            cache[vid] = (None, None)
            for d in dirs:
                data = _read_json(d / f"{vid}.shots.json")
                if isinstance(data, dict):
                    rights = data.get("source_rights")
                    cache[vid] = ((rights, "shots.json") if isinstance(rights, dict)
                                  else (None, None))
                    break
        return cache[vid]
    return read


def origin_name(origins_doc, origin_id):
    """The printable name of a footage origin: its `who` up to the first
    bracket (`ESA/Hubble (and ESA/Webb) science communication` ->
    `ESA/Hubble`; `European Space Agency` as is). None when the channel's
    document does not list the origin."""
    for o in (origins_doc or {}).get("footage_origins") or []:
        if isinstance(o, dict) and o.get("id") == origin_id:
            who = _str(o.get("who"))
            if not who:
                return None
            return who.split(" (")[0].strip() or None
    return None


def licence_label(rights):
    """`CC BY 4.0` / `CC BY-SA 3.0 IGO` / `CC BY` / `CC0`, or None for a
    licence that is not a Creative Commons one (public domain, YouTube's
    standard licence, stock)."""
    base = CC_LABELS.get((rights or {}).get("licence"))
    if not base:
        return None
    m = VERSION_RE.search(str((rights or {}).get("short_name") or ""))
    if not m:
        return base
    return f"{base} {m.group(1)}" + (" IGO" if m.group(2) else "")


def is_proof_quote(rights):
    """CF-0686: a vendor's official upload taken as a short quote."""
    r = rights if isinstance(rights, dict) else {}
    return r.get("role") == PROOF_QUOTE or r.get("footage_origin") == VENDOR_OFFICIAL


def quote_credit(rights):
    """CF-0686: the credit of a proof quote - its channel's title - or None
    (not a quote, or a quote whose record names no channel title)."""
    return _str((rights or {}).get("channel_title")) if is_proof_quote(rights) else None


def overlay_text(rights, origins_doc=None):
    """The on-screen credit of one source, or None when its origin does not
    want one on the picture (or nothing was judged)."""
    if not isinstance(rights, dict) or not rights.get("judged"):
        return None
    if rights.get("accepted") is False or rights.get("on_screen") is not True:
        return None
    name = (quote_credit(rights)
            or (_str(rights.get("credit")) if rights.get("credit_from") == "candidate"
                else origin_name(origins_doc, rights.get("footage_origin"))))
    if not name:
        return None
    label = licence_label(rights)
    return f"{COPYRIGHT} {name}" + (f"{SEPARATOR}{label}" if label else "")


def credit_row(vid, rights, where, origins_doc=None):
    """One `footage_credits[]` row for a judged source."""
    quote = quote_credit(rights)       # CF-0686: the vendor's channel, when named
    concrete = quote or (rights.get("credit_from") == "candidate" and _str(rights.get("credit")))
    origin = rights.get("footage_origin")
    row = {
        "video_id": vid,
        "rights_from": where,
        "footage_origin": origin,
        "origin_name": origin_name(origins_doc, origin),
        "licence": rights.get("licence"),
        "licence_name": rights.get("short_name"),
        "licence_label": licence_label(rights),
        "accepted": rights.get("accepted"),
        "credit": concrete or None,
        "credit_from": CHANNEL_TITLE if quote else rights.get("credit_from"),
        # The origin's rule, when that is all there is - a description of how
        # to credit, never a line to print.
        "credit_rule": (_str(rights.get("credit"))
                        if not quote and rights.get("credit_from") == "footage_origins"
                        else None),
        "credit_missing": (None if concrete else
                           "no concrete credit line for this file: "
                           + ("only the origin's rule (footage_origins) is known"
                              if rights.get("credit_from") == "footage_origins"
                              else "the rights record names no credit")),
        "attribution": rights.get("attribution"),
        "share_alike": rights.get("share_alike"),
        "on_screen": rights.get("on_screen"),
        "where": rights.get("where"),
        "role": rights.get("role"),
        "channel_id": rights.get("channel_id"),
        "channel_title": _str(rights.get("channel_title")),
        "license_url": rights.get("license_url"),
        "source_url": rights.get("source_url"),
        "overlay": overlay_text(rights, origins_doc),
        "blocks": [],
        "first_at_s": None,
    }
    return row


def is_own_capture(vid, rights=None):
    """CF-0567: the factory's own recording - by its id, or by a rights
    record that names the licence or the origin `own_capture`."""
    if _clip_names.is_own_capture(vid):
        return True
    r = rights if isinstance(rights, dict) else {}
    return OWN_CAPTURE in (r.get("licence"), r.get("footage_origin"))


def _block_sources(plan):
    """[(block index, block, [video id, ...])] for the footage the finished
    blocks show - source_gate's reading, so a block degraded to type shows
    no source and a split block shows both halves."""
    import source_gate
    rec = source_gate.independent_sources(plan)
    blocks = plan.get("blocks") or []
    return [(b["index"], blocks[b["index"]], b["sources"]) for b in rec["per_block"]
            if b["sources"]]


def plan_credits(plan, read_rights, origins_doc=None):
    """-> (footage_credits rows, credit_overlays, notes) for a finished plan.

    Overlays: one window per run of consecutive blocks showing the same
    credit lines, the run's `[start, end]`, clipped to the narration
    (`duration.actual`, where the end card starts)."""
    rows, by_vid, notes, skipped = [], {}, [], {}
    own = set()
    spans = []
    for index, block, vids in _block_sources(plan):
        lines = []
        for vid in vids:
            if vid in skipped or vid in own:
                continue
            if vid not in by_vid:
                rights, where = read_rights(vid)
                if is_own_capture(vid, rights):
                    own.add(vid)       # CF-0567: ours - no row, no overlay, no note
                    continue
                if not isinstance(rights, dict) or not rights.get("judged"):
                    skipped[vid] = ("no rights record (01b fetched[].rights, shots.json "
                                    "source_rights)" if not isinstance(rights, dict)
                                    else "rights not judged (judged: false)")
                    continue
                by_vid[vid] = credit_row(vid, rights, where, origins_doc)
                by_vid[vid]["first_at_s"] = round(float(block.get("start", 0.0)), 3)
                rows.append(by_vid[vid])
            row = by_vid[vid]
            if index not in row["blocks"]:
                row["blocks"].append(index)
            if row["overlay"] and row["overlay"] not in lines:
                lines.append(row["overlay"])
        if lines:
            spans.append((index, float(block["start"]), float(block["end"]), lines,
                          [v for v in vids if v in by_vid and by_vid[v]["overlay"]]))
    end_at = (plan.get("duration") or {}).get("actual")
    overlays = []
    for index, start, end, lines, vids in spans:
        last = overlays[-1] if overlays else None
        if last and last["lines"] == lines and last["block_indices"][-1] == index - 1:
            last["end_s"] = round(end, 3)
            last["block_indices"].append(index)
            continue
        overlays.append({"lines": lines, "start_s": round(start, 3), "end_s": round(end, 3),
                         "block_indices": [index], "video_ids": vids})
    if isinstance(end_at, (int, float)):
        for o in overlays:
            o["end_s"] = round(min(o["end_s"], float(end_at)), 3)
        overlays = [o for o in overlays if o["end_s"] > o["start_s"]]
    # A channel that judges no licences (ExampleFilm: its footage-origin.json
    # has no `licences`) has nothing to credit, and its plan says nothing new.
    judges = bool((origins_doc or {}).get("licences"))
    for vid, why in (skipped.items() if judges else ()):
        notes.append(f"footage credit: {vid} is on screen with {why} - no credit line and "
                     f"no on-screen credit for it, nothing invented (CF-0664)")
    for row in rows:
        if row["on_screen"] is True and not row["overlay"]:
            notes.append(f"footage credit: {row['video_id']} ({row['footage_origin']}) wants "
                         f"its credit on screen, but neither a credit line nor the origin's "
                         f"name is known - no overlay (CF-0664)")
        if row["role"] == PROOF_QUOTE or row["footage_origin"] == VENDOR_OFFICIAL:
            if row["credit_from"] != CHANNEL_TITLE:
                notes.append(f"footage credit: {row['video_id']} is a vendor's proof quote "
                             f"({row['footage_origin']}) whose rights record names no "
                             f"channel_title - credited by the old reading (the origin's "
                             f"rule, credit: null), not by its channel (CF-0686)")
    return rows, overlays, notes


def read_own_capture(vid, shot_dirs=()):
    """The recorder's sidecar of `vid` (`<dir>/<vid>.own_capture.json`) from
    the first of `shot_dirs` that has it, or None."""
    for d in shot_dirs or ():
        data = _read_json(Path(d) / f"{vid}{_clip_names.OWN_CAPTURE_SIDECAR_SUFFIX}")
        if isinstance(data, dict) and data.get("origin") == OWN_CAPTURE:
            return data
    return None


def plan_own_captures(plan, read_rights=None, shot_dirs=()):
    """CF-0567: `plan["own_captures"]` - one row per own recording the
    finished blocks show, in order of first use: the page, the host, the
    capture host entry, the Space's licence, when recorded, the blocks and
    the seconds on screen. `record_from` says where it was read (`sidecar` |
    `rights` | None - an id with no record is listed with nulls, not
    filled in)."""
    import source_gate
    rows, by_vid = [], {}
    for index, block, vids in _block_sources(plan):
        secs = source_gate.block_source_seconds(block)
        for vid in vids:
            rights = None
            if vid not in by_vid:
                rights = read_rights(vid)[0] if read_rights else None
                if not is_own_capture(vid, rights):
                    continue
                side = read_own_capture(vid, shot_dirs)
                space = (side or {}).get("space") or {}
                r = rights if isinstance(rights, dict) else {}
                by_vid[vid] = {
                    "video_id": vid,
                    "origin": OWN_CAPTURE,
                    "record_from": "sidecar" if side else ("rights" if r else None),
                    "url": (side or {}).get("url") or _str(r.get("source_url")),
                    "final_url": (side or {}).get("final_url"),
                    "host": (side or {}).get("host"),
                    "capture_host": (side or {}).get("capture_host"),
                    "host_entry": (side or {}).get("host_entry"),
                    "space": space.get("id"),
                    "space_licence": space.get("licence"),
                    "captured_at": (side or {}).get("captured_at"),
                    "duration_s": (side or {}).get("duration_s"),
                    "credit": None,
                    "credit_note": "our own recording - no credit row and no on-screen "
                                   "credit; the tool and its maker are named by the voice "
                                   "and the fact's source line (CF-0567)",
                    "blocks": [],
                    "seconds_on_screen": 0.0,
                    "first_at_s": round(float(block.get("start", 0.0)), 3),
                }
                rows.append(by_vid[vid])
            row = by_vid[vid]
            if index not in row["blocks"]:
                row["blocks"].append(index)
                row["seconds_on_screen"] = round(row["seconds_on_screen"]
                                                 + secs.get(vid, 0.0), 3)
    return rows


def own_capture_stage_fields(plan):
    """`videos[].own_captures` of 05-video-editor.json: the plan's rows, `[]`
    when no own recording is on screen, `null` on a plan built before CF-0567."""
    rows = (plan or {}).get(OWN_CAPTURES_FIELD)
    if not isinstance(rows, list):
        return None
    return [dict(r) for r in rows if isinstance(r, dict)]


def apply_to_plan(plan, rows, overlays):
    plan[FIELD] = rows
    plan[OVERLAYS_FIELD] = overlays


def stage_fields(plan):
    """`videos[].footage_credits` of 05-video-editor.json: the plan's rows,
    `[]` when no source on screen was judged (ExampleFilm), `null` on a plan
    built before CF-0664 - not measured, never read as "nothing to credit"."""
    rows = (plan or {}).get(FIELD)
    if not isinstance(rows, list):
        return None
    return [{k: v for k, v in r.items()} for r in rows if isinstance(r, dict)]


def judge_overlays(plan):
    """The on-screen credits as frame_judge_pack lists them under
    `ours_on_screen`: [{text, start, end, blocks}]."""
    return [{"text": " / ".join(o.get("lines") or []), "start": o.get("start_s"),
             "end": o.get("end_s"), "blocks": o.get("block_indices")}
            for o in (plan or {}).get(OVERLAYS_FIELD) or [] if isinstance(o, dict)]
