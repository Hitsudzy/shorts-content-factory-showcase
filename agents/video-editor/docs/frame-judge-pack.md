# The frame judge's pack

What this stage hands the `frame-judge` stage of the root. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

## The pack the frame judge is handed (CF-0298)

DoD item 3 - "the picture is about what the voice is saying" - is answered by
a judge that looks, and this repo builds what it looks at. No number can
answer it: `check_two_sources.py` counts sources, CF-0290's similarity floor
compares embeddings, and on 2026-09-18T2232Z the floor passed a Rennick video
that put three blocks of sixteen on frames of an unrelated short film.

```
scripts/frame_judge_pack.py <video.mp4> <plan.json> --out <dir> \
        [--tile-width 360] [--keep-frames] [--json]
```

Exit 0 = the pack is written (`<dir>/manifest.json` plus `sheet-N.png`),
1 = refused - the video or the plan is not there, or no frame of the video
could be read; the sentence is on stderr and in the manifest's `refusal`.

What it writes, per block: 1-3 frames of the **finished** video (one under
2.5s, two under 6s, three above it), grabbed by `qc_render.delivered_frame()`
- the same function, not a copy of it, that CF-0294's subject gate samples
with, so the gate and the judge argue about one picture. The sample points are
that gate's own `SUBJECT_PROBE_FRACTIONS`. Each frame is a 360x640 tile with a
two-line label over it (`#7 block 3 clip 14.45-18.13s @ 15.37s / shot
fkuxNGbx1qk:15`); six tiles to a 1128x1430 sheet, which keeps both sides under
the 1568px a vision model resamples to - the judge sees the tile at the size
it was drawn, and the last sheet is never one lonely tile.

The manifest stands on its own, because the judge is handed it and the sheets
and nothing else: per entry the timecodes, the narration heard over that
picture (words that straddle the cut included - the judge needs the whole
phrase), the anchor phrase without the resolver's "(shot 26, score 0.335)"
tail and its `anchor_id` when `anchors.json` is beside the plan, the kind of
picture, the shot's video id, and which tile of which sheet shows it. The
`ours_on_screen` block names the text **this repo** puts on the picture -
captions, watermark, a comparison line panel, the footage owner's credit in
the top corner opposite the watermark (`footage_credits`, CF-0664 - ESA,
ESA/Hubble, ESO want it on the picture; the block's `overlays` list it too as
`footage_credit`) - because the same judge answers
DoD item 2, and one that cannot tell our caption band from somebody else's
burned-in subtitles either convicts every block or acquits every one.

Not judged as a picture under a phrase, and saying so in the manifest and on
the tile: typographic blocks (`asset.kind: procedural` - the assetless rung,
where the picture *is* the words) and the channel's end card. They keep one
tile each so the operator paging the sheets sees an unbroken video. An insert
(a proof card) is an entry of its own with the claim it supports, and the
block under it is sampled where its own footage is actually on screen.

Measured on `delver.mp4` (2026-09-18T2232Z): 8 blocks + the end card = 9
entries, 20 frames, 4 sheets of 1.0-1.2MB, a 16KB manifest, 27.5s wall.

### The people the words name (CF-0879)

Every judged entry carries `named_people`: the people of the script's own
list (`plan.person_shot.people`, `scripts/person_shot.py`) the words over
that picture name - the plan block's `names_person` for a block, read off the
insert's own words for an insert. `[]` when nobody is named, and on a plan
from before CF-0879. The judge's step 3 (`mismatch: person`, CF-0877) reads
it.

### Our own recording is the footage (CF-0567)

A block that shows the factory's own screen recording of a tool
(`own_capture-<id>`, `scripts/capture_tool.py`) carries an overlay
`{"kind": "own_capture_ui", "sources": [...], "note": ...}` and
`source.own_capture: true`, and `ours_on_screen.own_capture` lists the
blocks, the recordings and the page of each. The note tells the judge that
the interface text of the tool - menus, labels, the prompt typed in, the
answer it shows - is the footage itself, not foreign burned-in text, so no
`foreign_text` is written for it; a third party's content the page shows (a
studio's character, a label's song) is still judged as usual. The block is
judged for DoD item 3 like any other.

CF-0689: a block that shows a graphic the factory drew itself from the
script's facts (`asset.kind: "own_graphic"`) carries an overlay
`{"kind": "own_graphic", "graphic_id", "template", "text": <what the viewer
reads, line by line - shared/own_graphic.py viewer_text>, "note"}` and
`source.own_graphic: true`; `ours_on_screen.own_graphic` lists its blocks and
each graphic's text. Every word on it is ours (no `foreign_text`); it is still
judged against the narration.

CF-0690: an `api_chat` graphic (a model's real answer through its API, in our
own chat) keeps the overlay kind `own_graphic` and adds `template:
"api_chat"`, its `record_id` and the note `API_CHAT_NOTE`: our animation, the
label «<model> · via API», the prompt we sent and the model's verbatim answer
on our record of the call - declared, no `foreign_text`, and the answer is not
a fact the video states.

