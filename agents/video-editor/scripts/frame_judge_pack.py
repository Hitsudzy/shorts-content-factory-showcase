#!/usr/bin/env python3
"""CF-0298 item 1: the machine half of the frame judge.

DoD item 3 - "the picture is about what the voice is saying" - has never had
a checker. `check_two_sources.py` counts sources, CF-0290's similarity floor
compares embeddings, and neither can tell "looks like it by CLIP" from "this
is the thing the narrator just named": on 2026-09-18T2232Z the floor passed a
Rennick video that put three of sixteen blocks on frames of an unrelated
short film. The operator caught it by eye, off contact sheets.

So the checker is a judge that looks, and this script is what it looks at.
For a finished mp4 and the plan it was rendered from it writes, into one
directory:

    manifest.json     every block: its picture's timecodes, the words the
                      voice says over it, the anchor phrase the picture was
                      chosen for, what kind of picture it is, which shot it
                      came from, and which tile of which sheet shows it
    sheet-N.png       the tiles themselves, big enough to read

Two rules decide the shape of both:

* the frames are of the FINISHED video, never of the source clip. The
  question is what the viewer is shown - after the 9:16 crop, the captions
  and the scrim - and CF-0294 settled that this is readable: Vision finds
  faces through all of it. The extraction is qc_render.delivered_frame(),
  the same function the CF-0294 subject gate samples with, so the judge and
  the gate argue about one picture rather than two similar ones.

* the manifest is self-sufficient. The judge is an LLM operator that gets
  the sheets and this file and nothing else - no plan, no batch, no
  storyboard - so anything it needs in order not to convict an innocent
  block is written down here: which text on the picture is OURS (captions,
  the watermark, a comparison line panel, a proof card) as opposed to text
  baked into the footage, and which entries are not a picture-under-a-phrase
  at all.

Typographic blocks (the assetless rung: `asset.kind == "procedural"`) and
the channel's end card are in the manifest with `judged: false` and the
reason spelled out - they carry a tile so that the operator paging through
the sheets sees an unbroken video, but there is no footage under them to be
about anything, and a judge asked to rate them would be inventing a verdict.

Usage:
    frame_judge_pack.py <video.mp4> <plan.json> --out <dir> [--json]

Exit code 0 = the pack is written, 1 = refused (see `refusal` in the JSON:
an unreadable video or plan, or a video with no judgeable block in it).
"""
import argparse
import json
import re
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import _clip_names  # CF-0567: our own screen recording
import footage_credits  # CF-0664: the footage credit over the picture is ours
import own_graphic_plan  # CF-0689: a graphic the factory drew is ours
import person_shot  # CF-0879: the people the words over a picture name
import source_gate
import qc_render
import render_quote
import video_plan_args  # CF-0815
from common import media_duration, probe_json
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

SCHEMA = "frame-judge-pack/1"

# How many frames a block is worth. One picture is enough to say what a
# 1.5-second punctuation beat shows; a seven-second hold can cut away from
# the thing it was chosen for and back, and one sample at the midpoint would
# miss both halves. Three is the ceiling because the judge reads the sheet as
# a page - past three tiles a block starts to cost more attention than the
# block after it.
TWO_FRAMES_OVER = 2.5        # seconds: shorter than this gets one frame
THREE_FRAMES_OVER = 6.0      # seconds: longer than this gets three
# The sample points are CF-0294's, in its own order (0.5 first): a pack and
# the subject gate that reads the same render should be looking at the same
# instants, so a judge's "block 7 shows knees" and the gate's "block 7 has no
# face" are about one frame.
FRACTIONS = qc_render.SUBJECT_PROBE_FRACTIONS
# A stretch of block too short to be worth a picture of its own - a proof
# insert that eats all but a third of a second of its block leaves no block
# frame behind, rather than one grabbed off the crossfade.
MIN_SPAN = 0.4

# Sheet geometry. A tile is the delivered 9:16 frame at 360x640: three across
# is 1128px of sheet, two down is ~1430px, and both stay under the 1568px
# that a vision model resamples a long side to - so the judge sees the tile at
# the size it was drawn instead of a thumbnail of it. Six tiles a sheet is
# the number that falls out of that; it is not a taste.
TILE_WIDTH = 360
SHEET_COLUMNS = 3
SHEET_ROWS = 2
GUTTER = 12
LABEL_HEIGHT = 40
HEADER_HEIGHT = 34
SHEET_BG = (14, 14, 20)
LABEL_BG = (32, 32, 42)
LABEL_FG = (255, 255, 255)
LABEL_MUTED = (185, 185, 198)

# What each kind is called in the manifest, and why a kind is not judged.
NOT_JUDGED = {
    "typography": "typographic block - the assetless rung, there is no footage "
                  "under these words, the picture IS the words, so there is "
                  "nothing here to be about the phrase",
    "end_card": "the channel's end card - a fixed clip appended to every video "
                "of this channel, not a picture chosen for anything the "
                "narrator says",
}

# CF-0567: what the judge is told about a block that shows our own screen
# recording of a tool (`own_capture-<id>`, capture_tool.py). Its interface
# text - menus, labels, the prompt typed into it, the answer it printed - is
# the tool's own screen, recorded by this factory on purpose: the footage
# itself, not burned-in subtitles or a title card of somebody else's upload.
OWN_CAPTURE_NOTE = (
    "our own screen recording of the tool this video is about (own_capture) - "
    "the text in its interface (menus, labels, the prompt typed in, the answer "
    "it shows) IS the footage, not foreign burned-in text: do not write "
    "`foreign_text` for it. Still foreign: a third party's content the page "
    "happens to show (a studio's character, a label's song, another channel's "
    "video) - judge that as usual")

SHOT_TAIL = re.compile(r"\s*\((?:shot\s|count card|opening_block|[^()]*\bscore\b)[^()]*\)\s*$")


def block_kind(block):
    """The word the manifest calls this block's picture by.

    `clip`/`still` are footage (moving, or one frame of it held); `card` is a
    count or quote card the planner drew on purpose; `typography` is
    build_render_plan.py's `procedural` asset - the assetless rung, a block
    nothing could fill. `split` and `sequence` keep their own names: their
    pictures live on the sides and cuts, and the judge is told so rather than
    shown one of them as if it were the block.
    """
    kind = (block.get("asset") or {}).get("kind")
    return {"procedural": "typography"}.get(kind, kind or "unknown")


def anchor_phrase(intent):
    """The anchor as the writer wrote it, out of the plan's `intent`.

    resolve_anchors.py appends its own bookkeeping to the phrase ("(shot 26,
    score 0.335)", "(shot 9, score 0.212, held frame)", "count card: '4'
    (opening_block count_card)"), and a judge handed that tail starts
    reasoning about scores. The phrase is what the picture was ordered by, so
    the tail comes off and the untouched `intent` stays in the entry beside
    it.
    """
    return SHOT_TAIL.sub("", intent or "").strip()


def anchors_beside(plan_path):
    """`anchors.json` from the plan's own work directory, or None.

    The pack works off the plan alone; this is enrichment, because the
    resolver's file carries the anchor's id and its phrase *before* the
    resolver rewrote it into an intent, and naming `v4` lets a verdict be
    traced back to the line of the storyboard it came from.
    """
    path = Path(plan_path).parent / "anchors.json"
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def anchor_for(block, words_range, anchors):
    """`{"id", "phrase", "source"}` for one block.

    The anchors file indexes into the same `words[]` the plan carries
    (`word_index` is the index of the block's first word), so an anchor whose
    word falls inside this block's words is this block's anchor. Nothing
    matches - an old plan, a merged block, no file - and the phrase comes off
    the intent, which is where the resolver put it.
    """
    intent_phrase = anchor_phrase(block.get("intent"))
    if anchors and words_range:
        lo, hi = words_range
        for anchor in anchors.get("anchors") or []:
            index = anchor.get("word_index")
            if index is not None and lo <= index <= hi:
                return {"id": anchor.get("anchor_id"),
                        "phrase": anchor.get("phrase") or intent_phrase,
                        "source": "anchors.json"}
    return {"id": None, "phrase": intent_phrase, "source": "intent"}


def narration(words, start, end):
    """What the voice says while this picture is up.

    `(text, [first_word_index, last_word_index])`, or `("", None)` for a
    stretch with no words in it (the end card, a held beat after the last
    word). A word counts when it *overlaps* the span rather than when it
    starts inside it: a word straddling the cut is heard over both pictures,
    and the judge deciding whether the picture backs the phrase needs the
    whole phrase, not the part that fits.
    """
    picked = [(i, w) for i, w in enumerate(words or [])
              if float(w.get("end", 0)) > start and float(w.get("start", 0)) < end]
    if not picked:
        return "", None
    text = " ".join(w.get("word", "") for _, w in picked).strip()
    return text, [picked[0][0], picked[-1][0]]


def insert_window(block):
    """`(kind, start, end)` of the insert covering part of this block, or None.

    Video.jsx: an insert is up for `insert.start_s`/`end_s` when it carries a
    window of its own (CF-0244's proof card) and for the whole block when it
    does not.
    """
    insert = block.get("insert")
    if not insert:
        return None
    start = insert.get("start_s")
    end = insert.get("end_s")
    return (insert.get("kind") or "insert",
            float(block["start"] if start is None else start),
            float(block["end"] if end is None else end))


def free_span(block):
    """The longest stretch of the block showing the block's own picture.

    An insert sits on top of the footage, so a frame grabbed under it shows
    the screenshot, not the shot the anchor was resolved to. The insert gets
    an entry of its own; the block keeps the longer of the two stretches
    beside it, and a block wholly covered keeps none.
    """
    start, end = float(block["start"]), float(block["end"])
    window = insert_window(block)
    if not window:
        return start, end
    _, i_start, i_end = window
    before, after = (start, min(i_start, end)), (max(i_end, start), end)
    return max(before, after, key=lambda s: s[1] - s[0])


def sample_times(start, end, most=3):
    """1-3 composition times inside `[start, end)`, in time order.

    The fractions are CF-0294's own, taken in its order and sorted for the
    sheet, so a two-frame block is sampled at the same instants a three-frame
    one is sampled at first.

    `most` caps the count: an entry that is not judged as a picture under a
    phrase is on the sheet so the operator sees an unbroken video, and one
    tile does that. Three tiles of the same end card would cost the judge
    attention it owes the blocks.
    """
    span = end - start
    if span <= 0:
        return []
    count = 1 if span < TWO_FRAMES_OVER else (2 if span < THREE_FRAMES_OVER else 3)
    return sorted(round(start + span * f, 3) for f in FRACTIONS[:min(count, most)])


# CF-0689: what the judge is told about a block that shows a graphic the
# factory drew itself from the script's facts (shared/own_graphic.py). Every
# word on it is ours; it is still judged against the narration.
OWN_GRAPHIC_NOTE = (
    "a graphic this factory drew itself from the script's own facts (own_graphic) - "
    "every word and number on it is ours: do not write `foreign_text` for it. It is "
    "still judged against the narration: it must show what the voice says here, and "
    "a value on it the narration does not say or back is a defect of the block")
# CF-0690: the `api_chat` template - the topic's model asked one of the
# channel's fixed prompts through its official API, its answer shown verbatim
# in our own chat. Ours and declared like any own graphic; the answer's words
# are the model's, on the record of the call, never a fact of the story.
API_CHAT_NOTE = (
    "our own chat animation (own_graphic, template api_chat) - the label "
    "«<model> · via API», the prompt this factory sent and the model's verbatim answer, "
    "on our record of the real API call: drawn by us and declared, do not write "
    "`foreign_text` for it and do not read the answer as a fact the video states. It is "
    "still judged against the narration: the voice must be about this demo here")


def own_graphic_overlays(block):
    """The overlay row of an own-graphic block ([] for any other): ours,
    with what the viewer reads. CF-0690: an `api_chat` also names its
    `record_id` and carries API_CHAT_NOTE."""
    asset = (block or {}).get("asset") or {}
    if asset.get("kind") != own_graphic_plan.KIND:
        return []
    row = {"kind": own_graphic_plan.KIND, "graphic_id": asset.get("graphic_id"),
           "template": asset.get("template"),
           "text": own_graphic_plan.viewer_text(asset), "note": OWN_GRAPHIC_NOTE}
    if asset.get("template") == own_graphic_plan.API_CHAT:
        row.update(record_id=asset.get("record_id"), note=API_CHAT_NOTE)
    return [row]


def overlays_for(plan, index, block):
    """The text this repo itself puts on the picture of this block.

    Written down because the judge also answers DoD item 2 ("no subtitles or
    titles over the picture") and our own captions, watermark and comparison
    line are not that violation - the baked-in subtitles of somebody else's
    upload are. A judge that cannot tell them apart either convicts every
    block or acquits every one.
    """
    out = []
    insert = block.get("insert")
    captions = "hidden" if (insert and insert.get("captions") != "shown") else "shown"
    # CF-0390: a proof card leaves them on now too (CF-0379 did it for a
    # meme), so a block under either is judged for DoD item 1 like any other -
    # the voice and our text together. CF-0394: the band is in one place for
    # the whole video, small type just above the player's bottom dead zone,
    # and an insert is fitted above it (render/src/lib/captionBand.js) - the
    # band is never raised over the picture any more.
    if captions == "hidden":
        note = "captions are off under this insert (Video.jsx)"
    elif insert:
        note = ("our own burned-in narration captions - they stay on under this "
                f"{insert.get('kind') or 'insert'}, in the fixed lower band below it")
    else:
        note = "our own burned-in narration captions, fixed lower band"
    out.append({"kind": "captions", "state": captions, "note": note})
    # CF-0664: the footage credit an origin wants on the picture (ESA,
    # ESA/Hubble, ESO) - drawn by this repo over the shots of that source.
    for credit in plan.get(footage_credits.OVERLAYS_FIELD) or []:
        if index in (credit.get("block_indices") or []):
            out.append({"kind": "footage_credit", "text": " / ".join(credit.get("lines") or []),
                        "start": credit.get("start_s"), "end": credit.get("end_s"),
                        "note": "our own small credit of the footage's owner, in the top "
                                "corner opposite the watermark - ours, not foreign text"})
    own = [v for v in source_gate.block_sources(block) if _clip_names.is_own_capture(v)]
    if own:
        out.append({"kind": "own_capture_ui", "sources": own, "note": OWN_CAPTURE_NOTE})
    asset = block.get("asset") or {}
    if asset.get("kind") == own_graphic_plan.KIND:
        out += own_graphic_overlays(block)
    for line in plan.get("comparison_lines") or []:
        if line.get("block_index") == index:
            out.append({"kind": "comparison_line", "text": line.get("text"),
                        "start": line.get("start_s"), "end": line.get("end_s"),
                        "publisher": line.get("publisher"),
                        "note": "our own fact panel, typeset by this repo"})
    return out


def source_of(block):
    """Where the picture came from: the shot's video id, the file on disk."""
    asset = block.get("asset") or {}
    shot = block.get("shot")
    video_id, shot_index = None, None
    if shot and ":" in str(shot):
        video_id, _, tail = str(shot).partition(":")
        shot_index = int(tail) if tail.isdigit() else None
    return {"shot": shot, "video_id": video_id, "shot_index": shot_index,
            "own_capture": any(_clip_names.is_own_capture(v)
                               for v in source_gate.block_sources(block)),
            # CF-0689: drawn by the factory, no source at all
            "own_graphic": asset.get("kind") == own_graphic_plan.KIND,
            "graphic_id": asset.get("graphic_id"),
            "src": asset.get("src"), "asset_kind": asset.get("kind"),
            "held_frame": block.get("held_frame"),
            "text": asset.get("text"), "card_kind": asset.get("card_kind")}


def proof_entry(plan, index, block, window):
    """The insert covering (part of) a block, as an entry of its own.

    The picture under an insert is a captured document or a meme card, not
    the block's shot, so it is judged as itself: the claim it is supposed to
    support is right here, and the judge can say whether the page on screen
    is that document.
    """
    kind, start, end = window
    insert = block.get("insert") or {}
    proofs = {p.get("proof_id"): p for p in (plan.get("proof") or {}).get("proofs") or []}
    proof = proofs.get(insert.get("proof_id")) or {}
    return {
        "id": f"block-{index}-{kind}", "block": index, "kind": kind,
        "judged": True, "not_judged_reason": None,
        "start": round(start, 3), "end": round(end, 3),
        "intent": block.get("intent"),
        "anchor": {"id": None,
                   "phrase": proof.get("claim_supported") or insert.get("source_url"),
                   "source": "insert"},
        "source": {"shot": None, "video_id": None, "shot_index": None,
                   "src": insert.get("capture_path"), "asset_kind": kind,
                   "capture_method": insert.get("capture_method"),
                   "source_url": insert.get("source_url"),
                   "author_or_outlet": insert.get("author_or_outlet"),
                   "verbatim_text": proof.get("verbatim_text")},
        "overlays": [{"kind": "insert", "state": "shown",
                      "note": f"a {kind} card of ours is over the footage here; "
                              f"the text on it is ours, not the footage's"}],
    }


def end_card_entry(plan, video_seconds):
    """The channel's ending, when the render actually carries it."""
    card = plan.get("end_card") or {}
    start = card.get("start_s")
    seconds = card.get("seconds")
    if start is None or not seconds:
        return None
    start, end = float(start), float(start) + float(seconds)
    if video_seconds and video_seconds < start + MIN_SPAN:
        return None          # planned, not rendered into this file
    return {
        "id": "end-card", "block": None, "kind": "end_card",
        "judged": False, "not_judged_reason": NOT_JUDGED["end_card"],
        "start": round(start, 3), "end": round(min(end, video_seconds or end), 3),
        "intent": card.get("text") or "the channel's ending clip",
        "anchor": {"id": None, "phrase": None, "source": None},
        "source": {"shot": None, "video_id": None, "shot_index": None,
                   "src": card.get("path"), "asset_kind": "end_card",
                   "variant": card.get("variant"),
                   "channel_name": card.get("channel_name")},
        "overlays": [],
    }


def named_people(plan, block, text, whole_block=False):
    """CF-0879: the people the words over this picture name - the plan
    block's own `names_person` (the editor's reading) for an entry that is
    the block's whole span, otherwise read off `text` against the script's
    people the plan carries (`person_shot.people`). `[]` on a plan from
    before CF-0879: the judge is told nobody rather than guessed at."""
    own = block.get(person_shot.FIELD) if isinstance(block, dict) else None
    if whole_block and isinstance(own, list):
        return list(own)
    rec = (plan or {}).get(person_shot.RECORD)
    people = rec.get("people") if isinstance(rec, dict) else None
    if people:
        return person_shot.names_in(text or "", people)
    if isinstance(own, list):
        return [n for n in own if person_shot.named_in(text or "", n)]
    return []


def entries_for(plan, video_seconds, anchors=None):
    """Every picture in the video, in time order, before any frame is grabbed.

    One entry per block, plus one per insert that covers part of a block,
    plus the end card. `frames` is filled in afterwards - the arithmetic is
    separated from the ffmpeg so that a test can check what the judge will be
    asked without decoding anything.
    """
    words = plan.get("words") or []
    out = []
    for index, block in enumerate(plan.get("blocks") or []):
        start, end = float(block["start"]), float(block["end"])
        kind = block_kind(block)
        text, span_words = narration(words, start, end)
        entry = {
            "id": f"block-{index}", "block": index, "kind": kind,
            "judged": kind not in NOT_JUDGED,
            "not_judged_reason": NOT_JUDGED.get(kind),
            "start": round(start, 3), "end": round(end, 3),
            "narration": text, "words": span_words,
            "intent": block.get("intent"),
            "anchor": anchor_for(block, span_words, anchors),
            "rhythm_role": block.get("rhythm_role"),
            "source": source_of(block),
            "overlays": overlays_for(plan, index, block),
        }
        if entry["judged"]:
            entry["named_people"] = named_people(plan, block, text, whole_block=True)
        window = insert_window(block)
        picture_from = free_span(block)
        if window and picture_from[1] - picture_from[0] < MIN_SPAN:
            entry["frames_from"] = None
            entry["note"] = (f"a {window[0]} insert is up for this whole block - "
                             f"the block's own footage is never on screen alone")
        else:
            entry["frames_from"] = [round(picture_from[0], 3), round(picture_from[1], 3)]
        out.append(entry)
        if window:
            insert = proof_entry(plan, index, block, window)
            insert["narration"], insert["words"] = narration(words, window[1], window[2])
            insert["frames_from"] = [insert["start"], insert["end"]]
            if insert["judged"]:
                insert["named_people"] = named_people(plan, block, insert["narration"])
            out.append(insert)
    end_card = end_card_entry(plan, video_seconds)
    if end_card:
        end_card["narration"], end_card["words"] = narration(
            words, end_card["start"], end_card["end"])
        end_card["frames_from"] = [end_card["start"], end_card["end"]]
        out.append(end_card)
    out.sort(key=lambda e: (e["start"], 0 if e["block"] is None else e["block"]))
    return out


def sheet_grid(count, columns=SHEET_COLUMNS, rows=SHEET_ROWS):
    """How many tiles on each sheet, so the last sheet is not a lonely tile.

    A pack of 7 tiles in 6-tile sheets would end on one tile in the corner of
    an otherwise empty page; the count is spread instead (4 + 3), which keeps
    every sheet a page the judge reads the same way.
    """
    per = columns * rows
    sheets = max(1, -(-count // per))
    base, extra = divmod(count, sheets)
    return [base + (1 if i < extra else 0) for i in range(sheets)]


def tile_label(tile, entry, at):
    """The two lines printed over a tile. First line identifies the picture,
    second says where it came from - or that it is not judged, which is the
    one thing a judge must not have to infer from a thumbnail."""
    block = "end card" if entry["block"] is None else f"block {entry['block']}"
    head = (f"#{tile}  {block}  {entry['kind']}  "
            f"{entry['start']:.2f}-{entry['end']:.2f}s  @ {at:.2f}s")
    if not entry["judged"]:
        return head, "NOT judged as a picture under a phrase"
    source = entry["source"]
    if source.get("shot"):
        return head, f"shot {source['shot']}"
    if source.get("source_url"):
        return head, str(source["source_url"])[:90]
    if source.get("text"):
        return head, f"card text: {source['text']}"
    return head, ""


def draw_sheets(tiles, out_dir, video_name, tile_width=TILE_WIDTH,
                columns=SHEET_COLUMNS, rows=SHEET_ROWS):
    """Write the contact sheets. `tiles` is `[(tile_number, entry, at, png)]`.

    Returns one record per sheet for the manifest. The label is drawn in a
    strip above the tile rather than over the picture: the picture is the
    evidence, and a judge should never have to wonder whether the text it is
    about to call a subtitle is ours.
    """
    from PIL import Image, ImageDraw
    font = render_quote.load_font(15)[0]
    small = render_quote.load_font(13)[0]
    sheets, at_tile = [], 0
    for number, size in enumerate(sheet_grid(len(tiles), columns, rows), start=1):
        batch = tiles[at_tile:at_tile + size]
        at_tile += size
        first = Image.open(batch[0][3])
        tile_height = round(tile_width * first.height / first.width)
        first.close()
        cell_w, cell_h = tile_width, tile_height + LABEL_HEIGHT
        used_rows = max(1, -(-len(batch) // columns))
        width = columns * cell_w + (columns + 1) * GUTTER
        height = HEADER_HEIGHT + used_rows * (cell_h + GUTTER) + GUTTER
        sheet = Image.new("RGB", (width, height), SHEET_BG)
        draw = ImageDraw.Draw(sheet)
        draw.text((GUTTER, 9),
                  f"{video_name} - frame-judge pack - sheet {number}, "
                  f"tiles {batch[0][0]}-{batch[-1][0]}", font=font, fill=LABEL_MUTED)
        for k, (tile, entry, at, png) in enumerate(batch):
            col, row = k % columns, k // columns
            x = GUTTER + col * (cell_w + GUTTER)
            y = HEADER_HEIGHT + row * (cell_h + GUTTER)
            draw.rectangle([x, y, x + cell_w, y + LABEL_HEIGHT], fill=LABEL_BG)
            head, tail = tile_label(tile, entry, at)
            draw.text((x + 6, y + 3), head, font=font, fill=LABEL_FG)
            draw.text((x + 6, y + 21), tail, font=small,
                      fill=LABEL_FG if not entry["judged"] else LABEL_MUTED)
            with Image.open(png) as frame:
                sheet.paste(frame.convert("RGB").resize((tile_width, tile_height),
                                                        Image.LANCZOS),
                            (x, y + LABEL_HEIGHT))
        name = f"sheet-{number}.png"
        sheet.save(out_dir / name)
        sheets.append({"file": name, "tiles": [batch[0][0], batch[-1][0]],
                       "grid": {"columns": columns, "rows": used_rows},
                       "tile": {"width": tile_width, "height": tile_height},
                       "bytes": (out_dir / name).stat().st_size})
    return sheets


def video_facts(video):
    """`{"seconds", "width", "height", "fps"}` of the finished file."""
    facts = {"seconds": None, "width": None, "height": None, "fps": None}
    try:
        facts["seconds"] = round(media_duration(video), 3) or None
        for stream in probe_json(video).get("streams") or []:
            if stream.get("codec_type") != "video":
                continue
            facts["width"] = stream.get("width")
            facts["height"] = stream.get("height")
            rate = stream.get("avg_frame_rate") or ""
            if "/" in rate:
                num, _, den = rate.partition("/")
                if float(den or 0):
                    facts["fps"] = round(float(num) / float(den), 3)
            break
    except Exception:                                   # noqa: BLE001 - see below
        # A probe that fails is not a reason to refuse the pack: the frames
        # are grabbed by timecode off the plan, and the only thing lost is
        # the header line. A refusal here would take the judge out of the
        # chain over a header.
        pass
    return facts


def ours_on_screen(plan):
    """The text this repo itself drew over the whole video, for the judge
    (`manifest.ours_on_screen`) - and, CF-0567, the blocks that show our own
    screen recording, whose interface text is the footage."""
    return {
        "captions": "the narration is burned into every block as captions in "
                    "one fixed lower band just above the player's bottom UI, "
                    "small type, up to two lines, a meme or a proof card "
                    "sitting above it (CF-0394) - ours, not the footage's",
        "watermark": plan.get("watermark"),
        "comparison_lines": [
            {"text": line.get("text"), "start": line.get("start_s"),
             "end": line.get("end_s"), "block": line.get("block_index"),
             "publisher": line.get("publisher")}
            for line in plan.get("comparison_lines") or []],
        # CF-0664: the footage owner's credit over its shots, where the
        # origin's terms want it on screen - typeset by this repo.
        "footage_credits": footage_credits.judge_overlays(plan),
        # CF-0567: the blocks that show our own screen recording of the
        # tool - its interface text is ours to show, not foreign text.
        "own_capture": {
            "blocks": [i for i, b in enumerate(plan.get("blocks") or [])
                       if any(_clip_names.is_own_capture(v)
                              for v in source_gate.block_sources(b))],
            "sources": sorted({v for b in plan.get("blocks") or []
                               for v in source_gate.block_sources(b)
                               if _clip_names.is_own_capture(v)}),
            # the page each recording is of (plan["own_captures"], CF-0567)
            "pages": [{"video_id": r.get("video_id"), "url": r.get("url")}
                      for r in plan.get(footage_credits.OWN_CAPTURES_FIELD) or []
                      if isinstance(r, dict)],
            "note": OWN_CAPTURE_NOTE,
        },
        # CF-0689: the blocks that show a graphic the factory drew itself,
        # and what each graphic says - all of it ours.
        "own_graphic": {
            "blocks": [i for i, b in enumerate(plan.get("blocks") or [])
                       if own_graphic_plan.is_own_graphic(b)],
            "graphics": [{"graphic_id": r.get("graphic_id"), "template": r.get("template"),
                          "blocks": r.get("blocks"), "text": r.get("viewer_text")}
                         for r in (plan.get(own_graphic_plan.FIELD)
                                   or own_graphic_plan.record(plan))],
            "note": OWN_GRAPHIC_NOTE,
        },
        "note": "text drawn by this repo. Any OTHER text over the picture - "
                "burned-in subtitles, a title card of somebody else's edit, "
                "a caption strip - came with the footage (the interface of "
                "an `own_capture` block excepted: that is our recording of "
                "the tool, see `own_capture`; an `own_graphic` block is "
                "ours entirely, see `own_graphic`).",
    }


def build(video, plan_path, out_dir, tile_width=TILE_WIDTH, keep_frames=False):
    """The pack. Returns the manifest dict; writes it and the sheets."""
    started = time.monotonic()
    video, plan_path, out_dir = Path(video), Path(plan_path), Path(out_dir)
    plan = json.loads(plan_path.read_text())
    facts = video_facts(video)
    anchors = anchors_beside(plan_path)
    entries = entries_for(plan, facts["seconds"], anchors=anchors)
    out_dir.mkdir(parents=True, exist_ok=True)
    frames_dir = out_dir / "frames"
    if keep_frames:
        frames_dir.mkdir(exist_ok=True)
    tiles, unread = [], []
    with tempfile.TemporaryDirectory() as tmp:
        for entry in entries:
            entry["frames"] = []
            window = entry.get("frames_from")
            if not window:
                continue
            for k, at in enumerate(sample_times(*window,
                                                most=3 if entry["judged"] else 1)):
                png = qc_render.delivered_frame(video, at, tmp,
                                                f"{entry['id']}_{k}".replace("-", "_"))
                if png is None:
                    unread.append({"entry": entry["id"], "at": at})
                    continue
                if keep_frames:
                    kept = frames_dir / f"{entry['id']}-{k}.png"
                    kept.write_bytes(Path(png).read_bytes())
                    png = kept
                tiles.append([len(tiles) + 1, entry, at, Path(png)])
                entry["frames"].append({"tile": len(tiles), "at": at,
                                        "sheet": None,
                                        "file": (f"frames/{kept.name}"
                                                 if keep_frames else None)})
        if not tiles:
            return {"schema": SCHEMA, "refusal":
                    "no frame of this video could be read - nothing to judge",
                    "video": {"path": str(video), **facts},
                    "plan": {"path": str(plan_path)},
                    "entries": entries, "sheets": [],
                    "counts": {"entries": len(entries), "frames": 0, "sheets": 0}}
        sheets = draw_sheets(tiles, out_dir, video.name, tile_width=tile_width)
    by_tile = {}
    for sheet in sheets:
        lo, hi = sheet["tiles"]
        for tile in range(lo, hi + 1):
            by_tile[tile] = sheet["file"]
    for entry in entries:
        for frame in entry["frames"]:
            frame["sheet"] = by_tile.get(frame["tile"])
    judged = [e for e in entries if e["judged"]]
    manifest = {
        "schema": SCHEMA,
        "built_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "refusal": None,
        "video": {"path": str(video), **facts},
        # The plan carries no script id of its own; the resolver's anchors
        # file beside it does, and the judge's verdict has to name the script
        # it is about rather than a path under /var/folders.
        "plan": {"path": str(plan_path),
                 "script_id": plan.get("script_id") or (anchors or {}).get("script_id"),
                 "slug": plan_path.parent.name, "style": plan.get("style"),
                 "blocks": len(plan.get("blocks") or []),
                 "spoken_seconds": (plan.get("duration") or {}).get("actual")},
        "ours_on_screen": ours_on_screen(plan),
        "sheets": sheets,
        "entries": entries,
        "unreadable_frames": unread,
        "counts": {"entries": len(entries), "judged": len(judged),
                   "not_judged": len(entries) - len(judged),
                   "frames": len(tiles), "sheets": len(sheets)},
        "seconds": round(time.monotonic() - started, 2),
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False,
                                                      indent=2) + "\n")
    return manifest


def summary(manifest):
    """The one line the operator reads in the terminal."""
    if manifest.get("refusal"):
        return f"frame-judge pack refused: {manifest['refusal']}"
    counts = manifest["counts"]
    return (f"frame-judge pack: {counts['frames']} frames of {counts['entries']} "
            f"pictures ({counts['judged']} judged, {counts['not_judged']} not) on "
            f"{counts['sheets']} sheet(s), {manifest['seconds']}s")


@video_script("video-editor", "frame-pack", name="frame_judge_pack.py")
def cli():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("video")
    parser.add_argument("plan")
    parser.add_argument("--out", required=True,
                        help="directory for manifest.json and the sheets")
    parser.add_argument("--tile-width", type=int, default=TILE_WIDTH)
    parser.add_argument("--keep-frames", action="store_true",
                        help="also keep the full-size frames under frames/")
    parser.add_argument("--json", action="store_true",
                        help="print the manifest instead of the summary line")
    args = parser.parse_args()
    # CF-0815: the same `video plan` pair as qc_render.py, the same swap rule.
    args.video, args.plan, swapped = video_plan_args.ordered(args.video, args.plan)
    if swapped:
        print(f"frame-judge pack: note: {video_plan_args.swap_note(args.video, args.plan)}",
              file=sys.stderr)
    runlog.annotate(**video_attempt(args.plan))
    video, plan = Path(args.video), Path(args.plan)
    for path, what in ((video, "video"), (plan, "plan")):
        if not path.is_file():
            print(f"frame-judge pack refused: {what} not found: {path}",
                  file=sys.stderr)
            return 1
    try:
        video_plan_args.load_plan(plan)
    except video_plan_args.PlanUnreadable as e:
        print(f"frame-judge pack refused: {e}", file=sys.stderr)
        return 1
    manifest = build(video, plan, args.out, tile_width=args.tile_width,
                     keep_frames=args.keep_frames)
    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    else:
        print(summary(manifest))
    return 1 if manifest.get("refusal") else 0


if __name__ == "__main__":
    sys.exit(cli())
