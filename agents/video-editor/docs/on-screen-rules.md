# On-screen rules

What has to be on screen, and how inserts share the frame with our captions. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

## The blooper relaxation's two borders (CF-0190)

The channel's ending clip promises `On-set bloopers`, and a blooper is studio
material end to end - the ordinary rights-holder check takes such a topic off
the batch, correctly. The user chose to show them anyway, with that check
relaxed for marked material only and against two borders a machine can check.
`agents/compliance-checker` is the half that stops forcing `review`
(`blooper_relaxation.py`); `scripts/blooper_gate.py` here is the half that
makes the borders real, and this is the only place in the factory where they
become a refusal.

The rule lives in `channels/<channel>.json` → `blooper_rights_relaxation`
(top-level beside `assetless_block_rung`, for that block's reason and one
more: two agents read it), never in this repository. A plan block claiming to
be a blooper carries the marker object the config names in `marker.field` -
`{marked_by, marked_at, not_whole_gag}`, written by whoever marked the
material, carried off the storyboard block onto the plan block verbatim. Then:

* `end - start` of the plan block must be at most `max_fragment_seconds`
  (3.0). Measured **on the timeline** - the number the editor controls and the
  viewer sees - not on the length of the upload the fragment was cut from;
* narration must run over it: no stretch of the block longer than
  `narration_over_fragment.max_silent_seconds` (0.5), **its leading and
  trailing edges included**, may fall outside every `[word.start, word.end)`
  of the plan's aligned `words[]` (`align_words.py`). A fragment parked in a
  pause has no commentary over it whatever the script says it has, and this is
  the one reading of "commentary over the fragment" the factory can take.

A breach is CF-0137's refusal, for CF-0137's reason: `BLOOPER BORDERS - plan
not written` on stderr, exit 2, no plan file, and a `plan.blooper-gate.json`
deficit beside where the plan would have been. The verdict rides on every plan
that *is* written as `plan["blooper_gate"]`, including the ordinary one where
nothing is marked (`marked_count: 0`) - a relaxation is recorded rather than
hidden.

Everything about it fails closed. A block that is absent, switched off, or
illegal (a channel may write **stricter** numbers than the decision, never
looser) grants no relaxation - and under no relaxation a well-formed marker is
a *refusal*, not an unmeasured fragment: the marker is the editor's own word
that this is somebody else's studio material, and nothing then permits it to
ship. In the other direction, a marker that is absent, `null`, `false`, not an
object, or missing one of `marker.required_keys` is not a blooper at all: such
a block is not measured against these numbers, and the kind of the material is
never guessed from an intent, a tag or a filename (it is recorded in
`malformed_markers` when the key is there but unreadable). The third border -
"not the whole gag" - is attested in prose and is not machine-checkable; the
config says so in as many words, and what the machine checks is that the claim
was made and is not a stub.

## The hero has to be in the delivered frame (CF-0294)

DoD item 7 of a video, checked where items 1, 2, 5 and 6 are checked - on the
finished mp4, by `qc_render.py`'s `subject_blocks()`. For every block whose
plan promised a person (`roi_source: faces`, `fit: cover`, with a `focus` to
reproduce), Vision is asked for a face on a frame of the render itself. The
captions, the watermark and the bottom scrim sit over that frame and turn out
not to matter: on the eight blocks of 2026-09-18T2232Z `delver.mp4`, the seven
the user accepted each yield one face (0.15-0.61 of the frame high) and the one
he rejected - a 9:16 window laid on the gap between two seated people, leaving
their knees - yields none at any of three sample points.

It reads pixels rather than re-checking the plan's geometry **because the plan
is what was wrong**: that block records `coverage: 0.895` and believes it. A
watchdog that trusts the number it is watching watches nothing.

An empty answer is not a verdict on its own - a moving clip's face can be
turned away for an instant, so two more samples are taken, and then the
*source* is asked what it was showing there. That second look is CF-0292's
`smart_crop.subject_coverage()` on a fresh detection of the source frame
against the window the block is actually framed with, judged by the plan's own
`qc_thresholds.min_coverage`. Three outcomes: the source has no face there
either (footage turned away - a note, not a failure, in the CF-0004 idiom); the
window kept less of the nearest face than the floor allows (delver block 7:
0.515 against 0.65 - the crop landed off the subject); or the window kept the
face and the picture still shows none. The last two fail, with different
sentences, and the failed gate is `subject`.

What is *not* judged: a block with none of those fields (an old plan, a card, a
procedural background), a split - its pictures live on the sides, not on
the block - and `fit: contain` (or a `blur_fill` presentation, drawn whole
over its own blurred copy), where the whole source
is on screen and no crop can have lost anybody. The last one is not caution but
measurement: 2026-09-03T2037Z ink-teaser-cards block 13 is a 1920x960 card
letterboxed into 1080x1920, its 72px face arrives 41px wide, Vision finds none,
and judging it would have failed a video that shipped.

A `sequence` is judged cut by cut (CF-0892, `subject_pictures()`): each cut
framed on a face, over the seconds it is on screen (the block is mounted
RENDER_CROSSFADE early and cut k starts the earlier cuts' `seconds` after that
mount), against its own clip at its own second; a contained cut not at all;
still one record per block. Before it the gate took the sequence asset - which
mirrors cut 0's fields - for one cover picture, probed the middle of the block,
which lay in a later contained strip, and explained the empty answer against
cut 0's clip held on its last frame. Batch example-film/2026-10-28T1505Z lost
three videos to F on that alone (ali-g-who-iz-i, the-gilded-age, crystal-lake,
-61 each), 2026-10-24T0840Z the-rings-of-power a fourth; re-run on their mp4s
the fixed gate finds the face in cut 0 of each 1505Z block, and the
rings-of-power block's two cover cuts sit under the comparison line.

Cost: one frame grab plus one detection per judged block, 0.92s each measured
on `delver.mp4` (7.35s for its eight blocks), and 1.9s more for the one block
that came up empty. Over five finished videos of three batches - 44 judged
blocks - it fails exactly one block, the one the user rejected.

## An inset panel is on screen whole, or not at all (CF-0327)

The user's verdict on `mormon-wives-comeback` (`example-film/2026-09-17T1901Z`)
was "29th second - a cut-off insert": for a second and a half a narrow strip of
pink hugged the left edge of the frame, a shoulder and a rim at the very
border, and nothing else of the picture it belonged to. It reads as our proof
card gone wrong, and it is not: that batch's own artefacts say the proof layer
delivered nothing at all (`proof p1: no_block`, on all three attempts). What
was on screen is the *source shot's own* inset. Block 11 is a split screen
whose panel spans x 0.056-0.459 of 1920, and the 9:16 cover window this factory
pointed at the face - `focus.x 0.5305`, window 696-1304 - kept 24 % of it,
flush against the left edge.

The block one second earlier, the "insert that was drawn whole", is the same
kind of shot with no panel at all: its brightest structure is a gradient whose
strongest candidate border runs down 57 % of the frame's rows, where block 11's
two borders run down 96 %. That gap is the detector. `scripts/inset_panel.py`
calls a panel a band between two vertical edges that step across
`EDGE_STEP = 25` luma in at least `MIN_EDGE_ROWS = 0.85` of the rows, at least
`MIN_PANEL_WIDTH = 0.12` of the width apart - which is what a picture-in-
picture, a split screen, an on-screen document or a phone mock-up looks like,
and what a photograph of a room never does. A scene has edges, but they stop.

The rule is one sentence: **a panel is delivered whole (`>= 0.9` of its width)
or not delivered at all (`<= 0.05`), and the state between the two is
refused.** A sliver shows the viewer that there was something to see and then
does not show it - which is the same failure whether the panel was our proof
capture or the footage's own inset, so it is stated once, about geometry,
rather than twice, about layers.

Two places act on it, and they are deliberately not the same place:

- `build_render_plan.frame_the_panel()`, on the probe frame it already has,
  moves `focus.x` to the nearest focus that answers legally, preferring the one
  that *shows* the panel - and only if the subject survives the move at the
  plan's own `min_coverage`. The framing is pointed at a face for CF-0294's
  reason and may not be spent to fix a panel. On the real block 11 the move
  costs nothing and buys twice: the panel goes from 24 % to 0 %, and
  `smart_crop.subject_coverage()` of the guest's face goes from **0.496 to
  1.000** - the old window had been sitting half off her.
- `qc_render.panel_blocks()` refuses what reached the screen anyway. Replayed
  over that shipped plan it names block 11 and nothing else: `cut, 0.24`, while
  block 12 - which also carries a panel - reads `absent, 0.00` and passes.
  Measured on the source against the delivered window, through the same
  `source_frame()` the subject gate uses, because the delivered frame alone
  cannot say how much of a panel is missing: what is missing is not in it.
  The failed gate is `panel`, so an attempt's reason reads `qc_failed:panel`.

When no move keeps both the panel and the subject, the planner leaves the
framing exactly as it was and records `verdict: unresolved`. It does **not**
fall back to `fit: contain` - letterboxing a montage block to a postage stamp
trades one visible defect for another and does it silently - and it does not
refuse: the refusal happens once, at `qc_render`, where the attempt ladder and
CF-0367's re-cut are already wired up.

The gate's mode is configuration, not code (CF-0320): a channel writes
`video_editor.panel_in_frame.mode` (`fail` / `warn` / `off`, and `floor`), the
planner copies it onto the plan as `qc_thresholds.panel_in_frame_mode`, and
`inset_panel.mode_of()` reads it there, defaulting to `fail` - which is what
DoD item 4 of 1.4.5 asks for. The measurement is written into
`qc.measured.panel_blocks` and the batch record's `qc.panel_in_frame` on every
render in every mode, including `off`: a rule whose measurement only appears
when it fires can never be priced, which is the failure CF-0320 exists to stop.
`assets[].focus` travels into the batch record for the same reason - a replay
has to be able to rebuild the window, and until now the one number that fixes
it lived only in the batch's `work/`, which the rotation deletes.

Not judged: a block with no `focus`, a card, a procedural background, a split
or a sequence, `fit: contain` (the whole source is on screen, so nothing can be
cut off it), and - CF-0363 - the stretch an opaque insert covers, sampled
through the same `open_span()` the subject gate uses.

Cost: one frame grab and one downscaled read per block, no Vision.

## A meme does not silence our captions (CF-0379)

Found by the user on 2026-09-24: while a reaction meme was on screen our
word-by-word captions were gone entirely. Not a bug in the meme layer - a rule
borrowed from the wrong place. `Video.jsx` hid the captions for the span of
**any** block carrying an insert, which is CF-0071's rule for the proof layer,
and there it is right: a screenshot of an article carries its own text and ours
on top of it double-captions the frame. A meme carries no such text. It is a
reaction to the block, not evidence for the sentence being spoken - if it has
words of its own they are about something else, and if it has none the viewer
simply loses our line for the length of the insert and watches a mute picture.
DoD item 1 asks for voice and on-screen text together; this took the text away
for seconds at a time.

So the suppression is a property of the *kind* of insert, and it is spelled in
the insert's own file: `inserts/proof.json` keeps
`composition.our_captions: "hidden"`, `inserts/meme.json` says `"shown"`, and
the renderer obeys the field (`block.insert.captions !== 'shown'`) rather than
the presence of an insert.

The frame is then shared. Until CF-0394 it was the caption band that gave way
(it rose clear of the meme for the insert's span); since 2026-09-25 the band
never moves and the **insert** makes room - see "The caption band is fixed"
below. `insert.source_size` (the meme's own pixels, written by `meme_layer.py`)
is what the render QC uses to know where the `contain`-fitted picture lands.

`qc_render.meme_caption_blocks()` is the gate that reads the pixels: a block
whose insert promises our captions, with a word actually being spoken over it
and no caption-white in the band, is a defect and is caught before a human sees
the video. Silence under an insert is not judged (no line is due), and a proof
is not judged at all - since CF-0390 it shows them too, but the rule was priced
on memes alone (below).

The mode is configuration, not code (CF-0320): a channel writes
`video_editor.meme_captions.mode` (`fail` / `warn` / `off`, and `min_ink`), the
planner copies it onto the plan as `qc_thresholds.meme_captions_mode`, and
`meme_captions.mode_of()` reads it there, defaulting to `fail`. The rows are
written into `qc.measured.meme_caption_blocks` on every render in every mode,
because `runlog gate-price --rule video_editor.meme_captions` prices the rule by
replaying them over the frozen batches. The failed gate is `meme_caption`, so
an attempt's reason reads `qc_failed:meme_caption`.

Cost: one frame grab and one band read per block carrying such an insert.

## A proof card does not silence our captions either (CF-0390)

The user's frame, 2026-09-24 (`paper-dragon`, example-film 2026-09-23T1722Z): a
proof card filling the frame - the document's title, outlet and date, with our
fact strip above it - and no captions of ours for its whole window while the
voice went on. CF-0071 had hidden them on the argument that a proof is a
photograph of the sentence being spoken; what the card actually shows is a
title, an outlet and a date, not the narrator's line, which is the argument
CF-0379 already withdrew for the meme. `inserts/proof.json` now says
`composition.our_captions: "shown"` and `proof_layer.py` writes
`captions: "shown"` on the placed card, together with the card's pixel size
(`insert.source_size`) and where its text sits (`insert.text_box`, the union of
the lines Vision read during the legibility gate, as fractions of the capture;
null when the lines carry no position, and then nothing is guessed).

CF-0390 made the band give way to the card's text; CF-0394 retired that - the
card, like a meme, is fitted above the fixed band, so `text_box` stays on the
plan as a record and nothing reads it for placement.

No new refusal: `meme_captions.captioned_insert()` leaves proofs out, so
`video_editor.meme_captions` still judges only what it was priced on. The frame judge is told the captions are
on under the card (`frame_judge_pack.overlays_for`) and checks DoD item 1 there
as on any other block.

## The caption band is fixed (CF-0394)

The user's pick of 2026-09-25 from four rendered styles on `paper-dragon` (the
complaint: the captions jump and take up too much of the screen). Variant D,
all of it in `render/src/lib/captionBand.js`:

- type at `CAPTION_SCALE` (0.64) of `theme.captionSize` - 50 px at the default
  78 - stroke scaled the same; phrases of at most 3 words / 1.8 s, closed early
  when the estimated wrap (`lib/captions.js linesFor`) would need a third line;
- the band's foot is the top of the bottom dead zone (`safeArea.bottom`,
  `scripts/safe_area.py` `OVERLAY["bottom"]` = 0.28), no extra foot; the row has
  no fixed height, so a second line grows upward;
- the band never moves - `captionLiftRanges` and the CF-0379/CF-0390 raise are
  gone;
- an insert (meme, proof card) is fitted `contain` into `insertBox()` - the
  block's zone cut `INSERT_GAP` above the band's top (`BAND_HEIGHT` = 0.07 of
  the frame reserved for two lines) - on a black ground that still covers the
  whole zone;
- no scrim: the stroke carries the contrast, `caption_design_guard` checks the
  drawn size (>= 48 px) and stroke, and `caption_contrast` records the band's
  contrast on real footage.

Colours (CF-0699, the user 12.10: ExampleTech's cyan active word on its blue
did not stand out from the base words). The row draws `captionColours(theme)`
(`render/src/lib/theme.js`): `theme.caption_text` for the base words and
`theme.caption_active` for the spoken one, falling back to `text`/`accent` -
a channel without the keys draws exactly what it drew before. With
`theme.caption_active_box` the spoken word sits on a rounded pill
(`CAPTION_BOX_PAD_Y_EM`/`_X_EM`/`RADIUS_EM` in `captionBand.js`) and loses its
stroke; every word then carries the pill's side padding (transparent on the
base words), the flex gap shrinks by the same amount, and the spoken word
keeps the row's size instead of the 1.1em bump - so the row is the same
width whichever word is spoken and never slides; `linesFor(words, em,
padEm)` counts the padding, so the two-line limit holds. The padding is
cancelled vertically by an equal negative margin: the band's height is what
it was. The keys come in `plan.theme` like the rest of the theme
(`scripts/channel_theme.py` passes the channel's block through), checked by
the root's `theme_errors` (contrast 4.5; root `docs/channel-data.md`). Only
`Captions.jsx` reads them; the graphics keep `text`/`accent`.

`scripts/meme_captions.py` mirrors the geometry (`band_box`, `insert_box`) for
the `meme_captions` gate and `caption_contrast`, and `tests/test_meme_captions.py`
checks the mirror against the real module under node. Three videos were
published this way on 2026-09-25 from a scratch fork before it landed here
(root `publish/README.md`).
