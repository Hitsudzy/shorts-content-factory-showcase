# The empty-block ladder

What fills a block the anchors could not. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

## The ladder under a block that could not be filled (CF-0137)

CF-0123 then went one step further: recording the hole is not enough, the hole
must not ship. Per-block degradation to the assetless rung is brak - three of
the four videos of `2026-09-03T2037Z` spent 14-38 % of their running time on
it, in runs of 2.1 to 14.3 consecutive blocks. So a block whose anchor
resolved to nothing climbs a ladder, and only the last rung writes a plan:

1. **an insert from the library** - CF-0138. After the script's `reactions[]`
   are answered, `meme_layer.plan_memes()` offers the library every block that
   has no picture, with no request behind it. The query is the block's own
   `intent` - the storyboard's description of the frame the resolver failed to
   find - and the picture is admitted by the floors CF-0143 measured and by no
   other number: similarity 0.26 *and* a lead of 0.02 over the third place.
   Below them the block keeps its hole and climbs, which is the usual outcome
   and the whole safeguard: a picture that does not stand clear of the field
   is a random picture on a wall, and that is what CF-0123 refused. A request
   keeps first claim on `max_inserts_per_video`, the 3s block floor is not
   relaxed for a hole, and the channel switch still governs both. The two
   kinds of insert are never counted as one - `origin` (`script_request` /
   `hole_fill`) on every overlay and provenance record, `plan["meme"]
   ["hole_fill"]`, `videos[].meme_hole_fill`, and an `INSERT IN A HOLE` line
   of its own in the acceptance output;
2. **the emergency shot repeat** - one showing of a shot this video has
   already used, spent in `resolve_anchors.py`. `MAX_EMERGENCY_REUSE_PER_VIDEO
   = 1` (`scripts/rhythm.py`, beside `MAX_SHOT_REUSE` and deliberately of
   another shape: a counter of *videos*, so a second hole is not patched at
   all). Never adjacent to its own first use, and inside a swing block never -
   CF-0074's "only distinct shots inside a swing block" does not bend. Every
   repeat is an `emergency_reuse` entry in `rhythm_shortfalls` plus
   `rhythm.emergency_reuse` on the plan and `videos[].emergency_reuse` in the
   batch metadata: it is a signal that the video needs *material*, never a
   silent fix;
3. **the assetless block** - only where `channels/<channel>.json`
   `assetless_block_rung.enabled` is `true`. Absent means off, so every
   channel, including one added next month, has it off until somebody writes
   it down. The flat `--style typographic` (CF-0015) is a different thing
   entirely and does not read the flag;
4. **the planner warns (CF-0330; it refused until 2026-09-23).** The block
   stays on the procedural rung, the plan is written, and a warning with the
   blocks and their seconds goes into `plan["warnings"]`. Before CF-0330:
   `ASSETLESS BLOCKS - plan not written`, exit 2, no
   plan file, and a `plan.assetless-rung.json` deficit beside where the plan
   would have been - the same shape CF-0118's `enforce` mode leaves. One
   assetless block is enough: with the rung off the rule is boolean, and no
   share-of-runtime threshold was invented. What happens to the video's entry
   in the registry after this is CF-0139's.

   That deficit is what the rotation reads (`rotation/shortage.py` in the
   factory, which turns it into a line of
   `rotation/ledger/<channel>.shortages.jsonl`), so CF-0139 made it carry
   everything the run already knew and used to throw away: `anchors[]` beside
   the old `blocks`/`reasons` - one object per hole with its `intent`, its
   span and the rung it fell from - and a top-level `hole_fill` node, the
   library rung's own record for those same blocks. The second one matters
   because a refusal writes no plan: `meme.hole_fill.refused[]`, the closed
   list of per-block outcome codes, used to go to stderr and nowhere else on
   exactly the runs that end in a refusal. When the rung was never reachable
   the node says so (`attempted: false`, empty `refused[]`) rather than
   inventing codes from the probe - a made-up code is read as fact and would
   turn "this video has no footage" into "this channel is configured that
   way".

The gate sits in `build_render_plan.py`, on the finished block list and before
the proof/meme/sound layers - `qc_render.py` probes a rendered file and has
never heard of degradation, so refusing there would arrive after the render
was paid for.

Rung 1 lives *below* that gate, though, so CF-0138 had to answer how the gate
can refuse early and still let the rung have its turn. Not by moving the gate
down - that hands every refused video the full bill for the vision layers.
The two goals only collide when the layer could actually change the verdict,
and whether it could is free to ask: `meme_layer.hole_fill_feasible()` reads
the channel switch, the pattern gate and the block lengths, and touches
neither the library nor CLIP nor Vision. Not feasible (layer off, pattern
refuses, a hole under the 3s floor, more holes than the insert budget) and
the refusal happens exactly where CF-0137 put it, with nothing paid for.
Feasible, and the refusal is deferred to just past the meme layer and above
the sound layer, and re-asked there over blocks that may now carry a picture
(`assetless_rung.filled_by_insert()`). So the expensive layers are paid for on
a doomed plan in one case only: the holes were closable in principle and the
library had nothing above the floors - a real rescue attempt, not a wasted
one. `rhythm.picture` keeps counting a filled hole as assetless on purpose:
that record is CF-0136's question about *material*, the material really was
missing, and widening the pool is really the next move.

The resolution floor (`MIN_SHORT_SIDE`) is checked on the *cut* clip, after
`prepare_clip.py` has cropped the source's caption band, so a 1280×720 source
fails it on any non-zero band at all (CF-0062). The gate is told what was
cropped and from what frame: a clip rejected for that reason says so
(`resolution_lost_to_crop` in `qc_asset.py`'s verdict, a `QC CROP LOSS` line
on stderr, `lost_to_crop` on the storyboard's `rejected_candidates`) instead
of reading like a genuinely low-res source. `scripts/measure_crop_floor.py`
is the measurement behind that, per shot of a pool.

What `usable()` asks about framing is whether the subject is inside the
rectangle the viewer will see (CF-0155). `build_render_plan.py` frames an
asset once, from the frame at `PROBE_OFFSET`, and holds that framing for the
whole clip; the gate takes the same framing from the same frame
(`qc_asset.py --window`, `smart_crop.focus_point()`/`delivered_window()` -
one copy of the rule, not a second one, for CF-0033's reason) and measures
every other probe against it. Before, each probe was measured against its
*own* best crop - a number no render ever uses, which answers "this frame
could have been cropped well" and moved with whatever detector Vision
happened to fire on that frame. The probes themselves are four frames of the
window the block will actually show, taken in one ffmpeg pass, so the verdict
is a property of the clip rather than of the length the rhythm asked for: the
same cut no longer passes at one block length and fails at another
(CF-0122). Every probed frame still has to pass; whether that stays the rule
is CF-0156's question. `scripts/measure_probe_profile.py` is the measurement
behind it - it gates every frame of a clip twice, against its own crop and
against the plan's window, and prints what each rule would have said.

**With several people in the frame, "the subject" is a person, not the box
around all of them (CF-0292).** Vision's faces used to be merged into one
union rectangle and thrown away; on a wide two-shot - Tom Carver at x=0.33 of
a 1920px frame, his interviewer at x=0.70, an empty hangar between them - that
union is mostly air, so the 607px `cover` window centred on it contained no
face at all and `roi_coverage` still reported 0.895 (the last, longest block
of `2026-09-18T2232Z`/delver.mp4, which the viewer rejected as "only the
hosts' legs"). Two things follow from keeping the faces. The window no longer
goes between them: when they do not fit it together, `smart_crop.window_face()`
picks one - the largest, near-ties to the one nearer the frame's centre - and
the ROI, the plan's `focus` and the gate's window are all built around that
face. And coverage is measured over the faces themselves
(`smart_crop.subject_coverage()`, the one rule the planner and `qc_asset.py`
share), as the share of the *best-served* face the window keeps: a window
holding one person whole is a good shot of that person, one holding nobody
scores near zero and the shot is `unusable` for `cover`, so the resolver moves
to the next candidate (CF-0290) instead of shipping an empty frame. The same
delver frame reads 0.895 → 0.515 against the window that shipped, and 1.0
against the window it gets now, with a whole face in it. One face, a saliency
box and a group that fits the window are all untouched, by construction:
`roi_parts` is written only for several faces, and everything else keeps
`window_coverage()` on the ROI box. A source `contain`ed with a backdrop, or
split between two faces, is a different answer to the same frame and is not
this change.

**Coverage is judged in the delivery the block actually gets, and the
animation excuse has to be argued (CF-0296).** The Famine Trials scenario of
`2026-09-19T0116Z` resolved into 23 blocks and was then refused whole over
three of them, on a measure the resolver had already passed. Two causes, no
faces involved in either (all three frames are saliency boxes). Blocks 1 and
19 are `is_card`, delivered `contain`: `resolve_anchors.usable()` asks
`qc_asset.py` for the *delivered* window and gets 1.0, because a contained
card is entirely on screen; `build_render_plan.inspect_asset()` asks for no
window, so the number stays `smart_crop.analyse()`'s own 9:16 **cover**
measurement - 0.344 and 0.264 - and was compared against the 65% floor. Under
`contain` there is no share of a subject to fall short, so coverage is now
reported and not judged (`coverage_judged` in the verdict); what a card has to
keep is its text, and `MIN_CARD_TEXT_KEPT` on the delivered framing (CF-0047)
already asks that. Block 10 is live-action `cover` and was a coin toss:
CF-0004's animation classifier scored the resolver's four probe frames
0.510-0.582 (excused, synthetic ROI, coverage ~1.0) and the planner's probe of
the *same moment* 0.497 (not excused, 0.45, refused) - 0.003 of softmax
between shipping and losing 20 good blocks. `ANIMATION_CONFIDENCE` is now 0.75:
the midpoint of the empty gap between the highest live-action `cover` frame
measured (0.582) and the lowest animated frame that needs the excuse (0.914,
`kMsiD1Nky5I` under the coverage floor); it flips no verdict in either sample
and removes the band where the verdict was noise. The block is now refused by
the resolver as well, which is the point: a shot the plan gate would refuse
falls out while CF-0290's ladder can still give the block another candidate,
a held frame or typography, instead of the video being lost whole.

Somebody else's text, cut in half by our window, is refused before the cut
(CF-0275). The defect is a split screen - a commentary video with an article
or a phone thread on the left of the 16:9 frame - where `cover` on the host's
face keeps half of that panel: words end mid-glyph, a stray "Share" button
hangs in the shot and our captions land on top of it. Nothing else could see
it (`usable()` measures subject, pixels, black and luma; `card_frame` asks
whether text *dominates*, and half a frame does not; `detect_text_band` looks
at the bottom strip), so the indexer measures the text of the whole frame
against the very window `build_render_plan.framing()` will use and leaves five
numbers in `usable_cached`: `text_regions`, `text_area`, `text_outside_crop`,
`text_cut_by_crop` (share of regions the window's edge passes through) and
`text_cut_area` (those regions as a share of the frame).
`resolve_anchors.text_cut_refusal()` reads them, and refuses on either of two
clauses - `text_cut_area` over `TEXT_CUT_AREA_MAX` (0.05: the window runs
through words), or a panel of text the window stands beside
(`TEXT_PANEL_REGIONS_MIN` 20 regions with `TEXT_PANEL_OUTSIDE_MIN` 95% of
their area outside it, which is the case where the edge happened to miss the
glyphs). Two clauses because no single number sees both shots of the measured
defect, and each threshold sits in a gap the 25-shot measurement left - the
numbers, and the three traps that rule out the simpler rules, are in
`tasks/CF-0275-split-screen-text-cut-by-vertical-crop.md` and pinned by
`tests/test_text_cut_by_crop.py`. Cards are exempt (delivered `contain`, so
there is no window to be cut by) and an index that never measured this is not
condemned by it - which is every index until the pool is remeasured
(`footage-indexer/scripts/remeasure_usability.py`, about four hours), so the
rule bites on the day that runs and not before.

A panel of somebody else's text *inside* the window, and a source too small
to show, are the root's rule (CF-0791). ExampleScience's voyager-1
(`2026-10-17T0817Z`) lost 36 points to the frame judge's `judge_foreign` on
seven blocks of one NASA lecture - plasma-wave charts and slides the window
shows whole, so CF-0275's "panel beside the window" clause lets them through
by design - and its worst shots were under 600 px. The pool knew both before
the cut. `precut_cache_refusal()` asks `shared/score/shot_guard.py`
`shot_refusal()` right after `text_cut_refusal()` (cached `text_regions` >= 13
in the frame, our own screen recording exempt by kind; `short_side` under the
channel's floor, 600), and `cached_verdict()` does not excuse such a shot
either. The module is the root's, beside the score model and found the same
way (`_score.shot_guard()`), so the root's offline
`shot_guard.py measure` and this filter read one copy. The mode is the
channel's (`channels/<id>.json -> video_editor.shot_guard`, read once per run
from `--channel`): `fail` takes the shot out with the root's sentence,
`warn` keeps it and writes the findings on the shots shown to the
storyboard's `shot_guard` record, `off` does not ask. Every channel is `warn`
until the user signs `fail`; the measurement behind it (0 accepted videos
touched across 50 Reel/Tech plans, all seven voyager blocks covered) is in
`tasks/CF-0791-science-judge-cuts-after-render.md` of the root and pinned by
`tests/test_shot_guard_precut.py`.

**The similarity floor is a gate (CF-0290).** `--min-score` (0.22) used to be
a label: the matcher reported against it, `gate_verdict()` wrote "using it
anyway" when a block was filled under it, `candidate_supply()` called such a
pool off-topic - and the frame went on screen. `resolve_anchors.screen_pool()`
now takes both floors - `--min-score` and CF-0088's stricter `--score-floor` -
and applies them to the pool once per anchor, before it is ordered, budgeted
or cut, so an under-floor candidate is never offered to a block in **any**
rhythm (`hold`, `staccato`, `alternate`, `even`, the side retry and the
side-by-side opening's two halves alike). That is DoD ролика item 3: an
unresolved anchor means the phrase is dropped or the video goes to needs-you,
never a random frame. `example-film/2026-09-18T2232Z` / delver.mp4 is the run
it was written against - two of its ten blocks played Tom Carver in an
interview chair, at 0.2000 and 0.2046, under phrases about a rotunda podium
and a wheelchair on a chaotic set.

Similarity comes before length as a consequence, not as a second rule. The
`budget == 1` order is unchanged - long enough for the block first, then the
matcher's own order (promoted title/end cards, then score) - but it now runs
*inside* the screened pool, so it only ever reorders candidates that already
depict the phrase. The full order a block draws on is therefore:

1. above both floors **and** long enough for the block - cards first, then
   score, descending; since CF-0435 the usability rank orders this group,
   the matcher's order breaking its ties;
2. above both floors, too short for the block - same order (CF-0517: never
   ahead of group 1, however clean - see the last section);
3. under either floor - not in the pool at all, and in
   `rejected_candidates` by name, score and which floor refused it.

A candidate from group 2 that wins its block fills it the way this branch has
always filled a clip too short for its block: `hold_frame()` lifts one frame
and the block becomes a `still` with `held_frame: true` (delver's wheelchair
block: `wIM1PDRvKSE:25`, 0.985s of real footage for a 4.08s block). That is
the ladder's existing rung and it carries its existing limits - the clip still
has to be at least `MIN_CUT_SECONDS` (0.7s) and to pass `usable()`, a block
held past a pattern's *drawn* hold band is still CF-0245's trim and CF-0270's
ceiling, and CF-0249's `MAX_HELD_RUN` is untouched because it judges a clip
block that outruns its clip, not a block that is a still by construction. No
new rung was invented for this: holding the *neighbouring* anchor's shot
across an ordered block is what CF-0085 refused (the Raygun 31.6s merge) and
what CF-0249 fails after the render, and on `even` the neighbour already
covers the gap through CF-0124's carry.

An anchor with nothing above the floor therefore falls down the ladder that
already exists - the insert, CF-0137's one emergency repeat, the carry on
`even`, a typographic block on an ordered rhythm - and the assetless-rung gate
refuses the plan where the channel has that rung off, which is everywhere.
`anchor_coverage.py` says the same thing one stage earlier and cheaper: its
`weak` verdict (a pool ranked, nothing on topic) is no longer `covered` and
refuses the script with or without `--strict`, because the resolver will now
give that anchor no picture at all.

`unresolved_anchors` is the post-gate verdict (CF-0088). The matcher's `found`
says whether anything in the pool *depicts* the phrase; the storyboard's record
says what actually happened after cached usability, the cut clip's `usable()`,
the caption crop's floor, the reuse cap and the swing rules had their say. An
anchor whose best matches were all refused is unresolved with each gate's own
line per shot (`gate_rejections`, `found_after_gate: false`); one whose
surviving shot scores under `--min-score` is recorded as "using it anyway" and
names the over-threshold candidates the gates turned away in front of it. Every
`fill()` refusal now lands on `rejected_candidates` with its `score`, including
the reuse cap, a too-short cut and a failed `prepare_clip.py`. The cached
pre-filter's refusals are two and say which they are (CF-0275): the old
`pre-filtered by cached shot usability, not cut` - dark, low-res, no subject,
a problem with the pool - and `text_cut_by_crop: ...`, which is this video's
framing showing somebody else's half-cut words and sends an operator
somewhere else entirely. A channel whose `video_editor.shot_guard` is `fail`
adds the root's two (CF-0791): `text_panel_in_window: ...` and
`under_resolution_floor: ...`. Both are `footage_unusable` in the CF-0139 cause
vocabulary, and the coverage preflight's `refusals[]` carries the same
sentences.

`--top N` (default 10) is only a filter while the pool is bigger than N. On a
pool of N or fewer plain shots the matcher hands back the whole index under
every phrase, and the run says so - a `WARNING:` line on stderr, the same text
under the storyboard's `warnings` - because on run 2026-09-03T2037Z's 4-shot
pool that silence let an unrelated shot through for want of anything else.
`--score-floor S` (off by default) refuses any candidate under S outright,
whatever top-N left free; there is no measured threshold behind a default yet,
so it is a knob the operator sets, not a policy. Since CF-0290 it can only
*tighten*: `--min-score` is a floor on what may be offered too, so a candidate
has to clear both.

`unresolved_anchors` travels out of the work directory now (CF-0290):
`build_render_plan.py` copies it onto the plan and `write_batch_metadata.py`
onto `videos[].unresolved_anchors` in `05-video-editor.json`, so DoD ролика
item 3 is auditable on a video that shipped rather than only in a batch
directory that the rotation deletes. `null` there means a plan from before the
change; `[]` means the resolver looked and found none.

The same crop can take the *people* with it, not just the pixel count
(CF-0092): a studio backdrop's lettering and name plates read as a 40%
caption band, and the cropped clip put the heads on the bottom edge under
two thirds of empty backdrop - `roi_coverage` cannot see this, because the
9:16 cover window keeps the full height and so always "contains" the faces.
Two independent guards. `prepare_clip.py` refuses a live (non-card) shot's
band above `MAX_LIVE_CAPTION_CROP` (33% - subtitles never start that high;
`--card` exempts a title/end card, whose band is CF-0103's business), and
`cut()` records the refusal as `crop_refused` on the block. Independently,
`qc_asset.py` judges the cut clip's face ROI after the crop
(`crop_framing()`: chin at the crop line, or the face centre sunk into the
lower third, where the same frame was fine before the crop) and rejects
with `framing_lost_to_crop` / a `QC CROP FRAMING` line - the safety net for
any band the ceiling lets through.

A card's band is judged by its thickness (CF-0103, the decision of CF-0061):
a title/end card's own bottom lettering is thick - the pool's clean cards
measure 0.3133 ... 0.4791 of the frame - and somebody else's subtitles burned
into a card are thin, 0.082 ... 0.2911. `prepare_clip.py --card` keeps a band
above `CARD_OWN_BAND` (30%) and cuts the card at full height, `cut()` records
it as `card_band_kept` on the block; a band at or below it is cropped like
any subtitle. Two things had to change for the number to mean anything.
`detect_text_band.py` no longer clamps the band at 0.45 - the clamp
saturated exactly on the thick bands the threshold has to see (CF-0061's
table had three cards sitting on it). And it refuses the measurement outright
when the text covers the frame instead of lying in a band: `FULLSCREEN_TEXT_
LINES` counts distinct text lines held above `LOWER_REGION` across the
sampled frames, and at 8 or more the shot is a list or a credits roll, not a
captioned card (x9wMFCMXCRE s3, a full-screen sponsor list, holds 14; every
genuine band measured holds 0-5). The band's *top* could not be the guard:
that list's cluster starts at 0.5685 and the thickest real card band at
0.5583, above it. Lifting the clamp changes the number `crop_bottom_cached`
holds, so every index measured before it is stale under CF-0055's fingerprint
(the same `caption_cache.py` mechanism, nothing new) and `match_anchors.py`
refuses the pool until `remeasure_captions.py` has been run. The threshold
was calibrated on 8 clean cards and 2 subtitled sources, a gap of one
subtitle line - `scripts/measure_card_bands.py` re-derives the table and says
where `CARD_OWN_BAND` falls in the gap; re-run it when a third subtitled
source enters the pool.

A title/end card that is dark on purpose is excused the two darkness checks
only if its own text is measurably lit (`--card`, CF-0047), and "its own
text" excludes a streaming platform's corner bug (CF-0094): a text box that
is both smaller than any card text (`WATERMARK_MAX_AREA`) and pinned in a
corner (`CORNER_MARGIN`) is left out of the ink measurement, so a
fade-to-black with nothing on it but "Example max" reads as a frame with no card
text - rejected, with `card text: none - the only text on this frame is N
watermark-shaped box(es)` in its failures - instead of as "a card with 58%
of its text lit". A card that carries the bug next to its title keeps the
title and loses the bug. The constants are bracketed by measured boxes from
the pool (comment above them in `qc_asset.py`); `card_ink()` feeds the
indexer's usability cache, so the change re-stamps `measured_by` and a
`remeasure_usability.py` pass is owed before the cache is trusted again.

A shot is cut from its head unless the index marks a moment inside it
(CF-0106). `moment_at` on a shot in `shots.json` - an absolute source
timecode, set by the describer when the described picture is not at the
shot's head, never by the indexer itself - reaches `resolve_anchors.py` on the
matcher's own match record. A marked shot's clip starts `MOMENT_LEAD_SECONDS`
(the anchor lead, 0.35s) ahead of the mark, so the moment sits near the head
of the window but not on its first frame, and the window is clamped to the
shot: never before its `start`, never past its `end`. A mark outside the shot
is refused in writing (`MOMENT REJECTED` on stderr, `moment_at rejected` on
`rejected_candidates`), never clamped - the matcher already refuses such an
index, this is the belt for a caller that skips it. Every block records where
its clip was cut from: `cut_at` (source seconds), `cut_origin` (`head` /
`moment`) and `moment_at`; a clip cut from a mark also says so on stderr
(`CUT FROM MOMENT`), in the block's `intent`, and as a note in the plan and
the QC report - the frame the on-screen line (`production_fact`, CF-0186)
stands on is traced
to that, not to the head of the shot it was matched in.

## Length before usability on a one-shot block (CF-0517)

A one-shot block (`budget == 1`: every block of `hold` and `staccato`, a
one-shot swing of `alternate`) wants one clip that covers its phrase, and holds
a frame only when the pool has none - the order above. CF-0435 then put a
usability rank (`rank_by_usability()` -> `shot_score.rank()`, key `(hard,
-usability_score, blur)`) in front of every `fill()`, and the long-enough-first
sort survived only among shots of one score: a short "clean" shot (1.0) in
front of a long one at 0.99 won the block, the block held a frame, and
CF-0270's `pattern_ceiling` refused a "degradation" the pool could have
answered. CF-0278's `length_supply` record made it visible - a long-enough
candidate with `outcome: not_reached` and a `rank` behind the cut short one.

The user's decision of 2026-10-04: **length first, then usability** - from the
shots long enough for the whole phrase the most usable one is taken; a short
clean shot no longer beats a long one; when no shot is long enough the order is
what it was.

### The measure before the change

`scripts/measure_length_first.py` (read-only; one matcher call for the whole
corpus). The corpus is the finished storyboards of `pipeline/example-film/`
(the running batch `2026-10-04T1825Z` excluded) - the frozen batches under
`tests/fixtures/frozen_batches/` carry `plan.json` only, no storyboard and no
pool, so they cannot be walked. No storyboard on disk predates CF-0278 by less
than a day, so none carries `length_supply`; the walk order is rebuilt from
today's pool instead (`real_*` below: the shot the run cut, placed in the old
order).

61 videos, 31 skipped (their sources left `shared/footage/`, CF-0358), 30
measured; 266 one-shot blocks, 241 of them cut from the phrase's own pool (25
came from a lower rung - topic, under the floor, the repeat - and are out of
this question).

| record as it is (241 blocks in pool) | blocks | of them held a frame |
|---|---|---|
| the cut shot is shorter than the block | 69 | 56 held overall |
| ...and a long-enough candidate sat behind it in the old order (`not_reached`) | **52** | **40** |
| ...and that candidate was neither retired nor burned-in text | 45 | 33 |

So 40 of the 56 held frames in the measured corpus had a long-enough candidate
in their pool that the rank never reached.

### The change

`fill(length_first=True)` on a one-shot block's match, its side retry and its
topic rung: `rank_by_usability(pool, ..., need=)` -> `shot_score.rank(lead=)`
ranks by `(hard, too short for the block, -usability, blur)`. Hard shots stay
last however long they are; the under-floor rung (CF-0433, "by rank, never by
length") and a stretch split's extra cuts (CF-0480) walk by rank alone; a
multi-shot block (`even`, a multi-shot swing) is untouched. The storyboard
says which order each run walked: `length_supply.rung_order` (`length_first` /
`rank`), and a long-enough candidate now shows `outcome: cut` where it used to
show `not_reached`.

### The measure after the change

The same corpus, each video's one-shot blocks walked in order under the old
and the new rank with the gates still visible offline (the one-use ledger,
retired shots as of the batch, burned-in text, the block's own recorded
refusals). The old walk is the control: it lands on the shot the run really
cut in 147 of 241 blocks (61 %) - the rest are gates that cannot be replayed
offline (the real `usable()` on the cut clip, swing sides, repeat_guard) or a
pool cache that moved since. `--mode real` (this code) and `--mode sim` (a
re-sort of the old rank) agree on all 266 blocks.

| 241 one-shot blocks in pool | old rank | length first |
|---|---|---|
| a shot shorter than the block cut (a held frame, or a split) | 70 | **51** (-19, -27 %) |
| blocks that held a frame in the run and now get a long-enough shot | 11 | **21** (+10) |
| mean usability score of the cut shot | 0.9699 | 0.9688 (-0.0011) |

42 blocks change their shot: 22 short -> long-enough (17 of them pay 0.01 of
usability, 2 pay 0.02, 2 pay 0.04, 1 nothing), 14 long -> another long one
and 3 long -> short (both the ledger: a long shot an earlier block now takes
is gone for the later one), 3 short -> another short one. Over the 42 the
mean usability goes 0.9693 -> 0.9633: 23 lower, 5 higher.

### The usability floor (the user's decision of 2026-10-04, 22:25)

Length leads only among shots at least `LENGTH_LEAD_MIN_USABILITY` = **0.5**
usable (`resolve_anchors.py`; the viewer's usability score, the one the rank
already uses). A long shot under it is ranked the ordinary way, with the
short ones, so it never jumps a clean short shot. In the code:
`shot_score.rank(lead=, lead_floor=)` counts a shot under the floor as
`lead = True`. The floor sits in the module rather than in the channel
config: no usability threshold of this stage lives there. The soft prices
themselves are in `shared/gate-prices.json`.

Re-measured with the floor (`--mode real`), the corpus does not move. Every
number in the table above is the same, and the walk with the floor, without
it (`--mode sim --no-floor`) and the real code agree on all 266 blocks. Under
today's price table (3/3/2/4 points a soft rule) a shot that is not hard
cannot fall under 0.5, and none of the 241 picks does, before or after. So on
this corpus the floor is a guard, not a change.

The block that prompted it, `2026-09-30T2210Z/vanguards-endgame-encore`
block 17, was misread in the first measure. Its pick `L2NAh3CIdig:2` scores
0.0 because it is **hard** (`screen_recording`), not because it carries a soft
price. A hard shot ranks last in both orders, so the block took it only as
the last resort. The cause is the ledger. Under the new order block 8 takes
the long `L2NAh3CIdig:0` (0.98) instead of the short `:28` (0.99). Block 16
then gets `:28` and stops holding `:2`. Block 17 finds `:0` gone and only
`:2` left. The floor does not change this, and with it block 17 still gets
`L2NAh3CIdig:2`. The measure now counts such picks apart
(`sim_*_hard_last_resort`): 6 before, 6 after.

Re-run: `scripts/measure_length_first.py --root <main checkout> --channel
example-film --out <file> --mode real --exclude-batch <running batch>` (about 80 s, one CLIP
load).

## A split goes on past three shots; no face held frozen (CF-0536)

delver of `example-film/2026-10-05T0701Z`, rejected 2026-10-05 ("неудачный стоп
кадр на 15с, 21с", `stretched_held_stills`). Both points were the held tails of
a stretch split (CF-0480): block 2 played 0.83 + 1.04 + 1.28 s of a 5.61 s
block and held the 1.28 s shot for 2.46 s; block 3 played 4.99 s of 11.2 s and
held `wIM1PDRvKSE:37` - a face in the middle of a movement, `held_motion`
motion 7.43, face 0.087, CF-0481's frozen frame - for 6.21 s. CF-0480 stopped
at three shots; `score.held_moving_face` lets 12 s of such frames go free.

* **Where a frame is held.** `shot_score.held_moment`: among the shot's
  sampled moments that read at least `held_sharpness.FLOOR` (0.53), the
  calmest, not the sharpest (the sharpest moment of a moving shot is a frame
  of the motion). Without a sharpness record, `hold_frame` holds the clip's
  calmest frame (`held_motion.calmest_moment`) when it has one under
  `held_motion.MOTION_MIN`; a clip that moves all through keeps its middle.
* **A split goes on.** After its three shots, while what is left would be held
  stretched (still_share's line) or - longer than `FROZEN_HOLD_MAX_SECONDS`
  (2 s, the same line) - only on frozen faces (`split_wants_more`), the split
  takes the phrase's next shot, up to `STRETCH_SPLIT_MAX_SHOTS_LONG` (6):
  first its own pool, then the phrase's candidates under the similarity floor
  (the matcher's pictures of this phrase; the block is then priced
  `score.low_similarity` like any block filled there, CF-0433). The record:
  `stretch_split.more` / `more_short`, `held_motion` of the held frame.
* **A frozen one-frame hold is split.** A one-frame block whose one shot would
  hold a frozen face longer than 2 s is split like a stretched one
  (`frozen_hold_wanted`, `why: frozen_frame`), and a split holds a frame that
  is not frozen before a sharper frozen one (`sharpest_last(frozen_of=)`).

Replay of delver 0701Z (the batch's anchors, today's pool and registry; the
baseline replay reproduces the batch's blocks 0-4 exactly): block 2 - four
shots (`wIM1PDRvKSE:7` added), nothing held; block 3 - five shots
(`wIM1PDRvKSE:41`, then `ZLXL1L0TfsI:37` under the floor at 0.193), held 1.25 s
of `ZLXL1L0TfsI:37` at sharpness 0.615 instead of 6.21 s of a frozen face; the
block is priced `score.low_similarity`.

`score.held_moving_face` keeps `allow_seconds` 12: the verdict cannot move it.
The rejected delver had 6.21 s of frozen faces in all; accepted videos had
more (vanguards-endgame 0705Z 11.13 s, a single frame of 5.11 s;
american-dread-story 1722Z 10.6 s; wolfhame 1757Z 8.0 s). What separates
delver is one frame held long, and that is the mechanism above, not a price.

## A blurry shot does not lead on length (CF-0537)

delver 0701Z, block 1 (5.97-11.81 s, "6секунда выглядит будто экранка"):
`ZLXL1L0TfsI:15`, a shot of the 1920x786 scope trailer, `low_sharpness` 0.5099
under the 0.57 floor. The price `score.low_sharpness` is unsigned, so the shot
was only warned and kept usability 1.0; it was the one shot of the phrase long
enough for the block, and the length lead (CF-0517) put it ahead of every
sharp shorter one - the blur tie-break comes after the lead.

`shot_score.rank(lead=)`: a shot `blur_rank()` finds blurry ranks with the
short ones (`led = True`) - behind a sharp shot of its usability score, ahead
of a short blurry one of the same score and sharpness. An order, not a price;
the usability score still comes first (a priced weak shot is not lifted over a
clean blurry one).

Replay of delver 0701Z: block 1 is now four sharp shots of the phrase
(`wIM1PDRvKSE:34, :14, :33, :7`, nothing held). Block 2 has the same phrase
("A huge indoor crowd gathered under an ornate rotunda ceiling."), and the
phrase's sharp shots are spent (used in block 1, or retired by earlier delver
videos), so block 2 now takes `ZLXL1L0TfsI:15` for 5.61 s: the order cannot
remove a soft shot the pool has nothing sharp at or above the floor to replace.
The phrase's sharp candidates sit just under the floor (0.2194, 0.2158,
0.2155 against 0.22); whether a warned-blurry shot should yield to them, and
the price of `low_sharpness`, are the user's decisions.

### A soft shot over the floor yields to a sharp one under it (CF-0537, the user's decision of 2026-10-05)

The price `score.low_sharpness` stays unsigned (warn); the order above does
the work. Where the order cannot - every cut a block got from its match is
`low_sharpness` - the phrase's measured-sharp candidates just under the
similarity floor are walked instead (`sharp_under_pool()`), and a survivor of
every gate replaces the soft cut; the block is marked `below_floor` (with
`sharp_swap`: the soft shots it replaced and their sharpness) and priced
`score.low_similarity` (-3 a block, cap -15, signed) like any block filled
under the floor.

* "Just under" is the lower bound the CF-0536 split already goes on into:
  `below_floor_pool()` - the matcher's own candidates of the phrase,
  `--score-floor` the only floor under them. No new threshold.
* Only a shot measured sharp is paid for: the pool's best-scoring
  unmeasured candidates are measured first (`shot_score.probe_unmeasured`,
  the rank's three probes and per-run ceiling, in score order - the rank's
  own probes reach only the cleanest top three). The later one-shot blocks'
  first picks are kept for them (`later_first_picks`).
* The walk is by rank, never by length - the under-floor rung's rule
  (CF-0433/CF-0290). A one-shot block that gets a short sharp shot is then
  split as usual (`stretch_split`, rung `sharp_below_floor`).
* Nothing sharp survives -> the soft cuts stay, exactly as before (the ledger
  and the placed list are given back), with a `SOFT SHOT KEPT` note.

Replay of delver 0701Z (the batch's anchors, today's pool and registry):
block 1 - four sharp shots (CF-0537 order, unchanged); block 2 (11.81-17.42) -
`wIM1PDRvKSE:45` (0.2155, 1.50 s) then `ZLXL1L0TfsI:34` (0.2128, sharp, 4.11 s),
nothing held, priced `score.low_similarity`; `ZLXL1L0TfsI:15` is not on screen.
Blocks 0 and 3-8 as before.

## A block that holds a short shot whole prefers motion - and its anchor (CF-0648)

delver `2026-10-08T1824Z`, block 7 (2.91 s, a swing; the user's "мыльный
растянутый кадр" at 18 s): `wIM1PDRvKSE:55` (1.17 s, "two older men in suits")
was held still for the whole block, x1.78, while four long-enough candidates
sat behind it - every one `low_sharpness` (ZLXL1L0TfsI:9 / :7 / :27 at
0.51-0.53, wIM1PDRvKSE:40 at 0.5666), so CF-0537 ranked them with the short
ones. A swing (like an `even` block, a block of 2 s or less, a run with
--no-stretch-split) cannot be split (CF-0480): its short shot is a frame held
for the whole block. For such a block only (`split_reachable()` false,
`held_whole`), `shot_score.rank()` gets two tiers between "leads" and "ranks
with the short ones":

| tier | what |
|---|---|
| 0 | long enough, usability >= 0.5, sharp (CF-0517, unchanged) |
| 1 | the anchor's own short shot - its description holds >= 0.9 of the phrase's words (`anchor_match`, `ANCHOR_MATCH`); usable, not blurry; only while a tier-2 shot is in the pool |
| 2 | long enough, usability >= 0.5, blurry at or above 0.55 (`MILD_BLUR_LEAD_FROM`) |
| 3 | everything else - the short ones, a long one under 0.5 or blurrier (CF-0537) |

* **0.55.** The moving clips the factory showed under the 0.57 floor: the
  user's "экранка" read 0.5099 (CF-0537, delver 0701Z block 1); accepted
  videos carry 0.5582 (vanguards-endgame 0701Z, 4.4 s) and 0.55-0.5688
  (spire-runner 1313Z / 1748Z / 2210Z, coach-hale 1748Z, WNL 1825Z).
* **The anchor.** The writer composes `visual_anchors` from the pool's
  descriptions: on 1824Z / 1208Z the anchor's own shot reads 1.0 (0.92 when
  reworded), the next best 0.2-0.8. Delver block 7's anchor is
  `wIM1PDRvKSE:21` ("a man in a decorated military uniform speaks", similarity
  0.2421 - under :55's 0.2688, which is why the old order never reached it).
  The tier exists only against tier 2: without a mildly blurry long shot the
  short ones keep their old order.
* **The record.** `length_supply.held_whole` (per rung) and
  `length_supply.not_reached` (candidates no run reached).

Replay (`scratchpad` calibration, read-only: each storyboard's own pool from
one matcher call, today's sharpness probes in memory, the recorded refusals,
the channel's retired shots by slug as of the batch, a shot shown by an
earlier block gated):

* delver 1824Z block 7: `:55` -> `wIM1PDRvKSE:21` - the shot the operator of
  `rebuilds/2026-10-09T1208Z` reached after two re-cuts (held_screen clean
  there: 0.5504 on screen). `:21` was block 10's second cut in 1824Z; block 10
  then takes its next shot.
* delver 1208Z block 7: the first pick is `:21` (no re-cut needed).
* rink-rivals block 8 (1824Z and 1208Z): unchanged - 19 offered, none long
  enough, no anchor of the phrase usable: a property of the pool, not of the
  order (CF-0648's held-screen re-cut, plan-and-gates.md, is what moves it).
* accepted: vanguards-doomsday 1824Z, vanguards-endgame / east-of-eden /
  harbourlights 0701Z - no pick changes (east-of-eden block 11 would have taken
  its anchor `tpK0D4_MF58:9` over `fdBr5KyUilU:10` before tier 1 was tied to
  tier 2; it is not). delver 1427Z and delver / rennick / coach-hale 1313Z
  predate `length_supply` (CF-0278) and cannot be replayed this way.

## A block that retells the event takes the event's own footage (CF-0545)

`weekend-night-live`, `2026-10-05T0701Z`: under "Taylor Sterling crashes the
monologue ... in front of a full Studio 8H crowd" stood `d7b1ilF5290` -
Dana Reyes on the couch of *Late Night with Sam Meadows*, a promo
interview from before the broadcast. The monologue had one source
(`KTe9OatvQas`, 8 shots), the interview fifty, and the matcher picks by
person and description. The frame judge called it another show (CF-0539),
after the render. `scripts/event_footage.py` keeps it off before any rung
(since CF-0575 the rule itself is the factory root's `shared/event_footage.py`,
loaded by path - the Content Researcher counts the event's own footage with the
same classification before the voice; this repo keeps no copy):

* **When.** The script retells a scene of the hunter's (`scene_id`, CF-0533)
  whose description names a moment on screen (monologue, sketch, cold open,
  episode, finale, scene, cameo, broadcast...). A scene that is somebody
  saying something ("X says / reveals / explains / tells") is off - there
  the interview *is* the event; so is a scene with no moment at all (a box
  office figure, a renewal).
* **What.** An *interview of another production*: nature `interview` (the
  hunter's `footage_candidates[]`, a supplement request's `candidates[]`, or
  for a pool source neither names, its title in `shared/footage/index.json`)
  on a channel that is not the work's own (`title_ref` name, its initials,
  `network`, `rights_holder`, `parent_work`). The hunter calls "Dakota
  Reyes Monologue - WNL" an interview too; its channel `Saturday Night
  Live` is the work's, so it stays.
* **Which blocks.** Every anchor whose spoken words (its `word_index` to the
  next anchor's) do not put it in the interview: "interview", "podcast",
  "talk show", "sat down with", "press tour", "late night", or the
  interview's own show / host ("Sam Meadows") keep the interview available.
* **Where.** `resolve_anchors.py` takes those candidates out of the event
  blocks' phrases right after the entity screen (CF-0348) - before the
  split opening, the regular match, the topic rung, the repeat - and
  `fill()` refuses them again; each is in `rejected_candidates` with
  CF-0545.
* **Off, and why** - no scene, a statement scene, no interview in the pool,
  or no source of the work's own (nothing to keep the blocks on: the
  storyboard says `needs_supplement`, the rule does not empty the video).
* **Record.** The storyboard's `event_footage`: `applied`, `why`, the role of
  every source, each anchor's answer, `refused`, and `short[]` - the anchors
  that had a picture over the floor before the guard and none after. Those
  go down the ladder (the event's topic footage, the repeat), never back to
  the interview, and a `WARNING: event footage (CF-0545)` line says the pool
  wants a supplement of the event's footage (CF-0345).

Priced over every rendered plan on disk (`pipeline/example-film/*/work/*` and
`rebuilds/`): the rule is on and moves a placed shot only in the two WNL
videos (1825Z: 9 cuts of `d7b1ilF5290`; 0701Z: 5), neither accepted. The 11
other videos with an interview of another show in the pool are off by the
scene (a statement, or a box office figure); 0 of the accepted videos change.

## A block that names X does not take a close face of Y (CF-0879)

wicker `2026-10-26T0841Z`: under "Four. Peter Dinklage is the basket weaver"
stood `ob-KN-uRkB0:7`, a close face from "Wicker Co-Stars Olivia Colman and
Alexander Skarsgård Watch Early Career Clips Together" (Skarsgård); under
"Elizabeth Debicki plays the tailor's" an older man. the-gilded-age
`2026-10-27T0836Z`: under "Fellowes called writing ..." an interview of a
blonde woman. CF-0877 made the frame judge see it (`mismatch: person`,
`score.judge_wrong_person`), after the render; `scripts/person_shot.py` keeps
it off at the choice of the shot:

* **Who.** The script's own list, never every capitalised run:
  `title_ref.person`, the cast pairs of `story_claims` (actor -> character,
  CF-0533/CF-0540) and their `attribution`, and the people the claims quote
  or cast ("reported Julian Fellowes as saying", "Carrie Coon was cast as",
  "X plays", "X said" - outlets and trade words cut off). A person's sex is
  read only where the script gives it: the cast character's head noun ("the
  Tailor's Wife") and the pronouns of sentences that name that person and
  nobody else of the list ("Fellowes said he was"). No cue - no sex rule.
* **Which shot.** One person in front: a description that leads with a
  close-up / portrait / interview of someone, or a face framing
  (`roi_source: faces`) or a one-person lead with no crowd, group, couple and
  no second person in the description. It is **foreign** to X when its
  source's title (hunter / registry, the record CF-0545 reads) names somebody
  of the list and not X, or when the description's sex contradicts X's. A
  block naming several people takes a shot that fits any one of them.
* **Where.** `resolve_anchors.py`, right after the event screen: an anchor
  whose words name somebody loses its foreign candidates - only when a
  non-foreign candidate over the floor stays (a crowd, a wide shot, an object,
  or X's own source); each is in `rejected_candidates` with CF-0879. With no
  replacement the foreign shot stays (`kept_for_want_of_replacement`).
* **Record.** Every storyboard and plan block carries `names_person` (the
  people its words name, `[]` for none); the storyboard's and the plan's
  `person_shot` hold the people, the refusal count, the kept anchors and
  `risky_blocks`; each risky block the plan still shows is a
  `person_shot_risk` warning in `plan.warnings` - mode `measure` (CF-0320),
  no price, no funnel code, until the user signs one. The judge's pack hands
  the names on as `named_people`.

Measured over the recorded plans since 10.10 (`pipeline/example-film/*`, 36
videos, json only): 11 videos name somebody of their list, 28 blocks do, 17
of them show one person in front, and 4 of those are somebody else's face -
wicker 0841Z blocks 10 (a woman under Skarsgård), 12 (the BAFTA interview
under Dinklage), 13 (a man under Debicki) and the-gilded-age 0836Z block 3
(a woman under Fellowes); 1 by the title, 3 by the sex. Not caught: the
gilded-age block 5 under Carrie Coon - its description is "a woman ... and a
man ... talk", the crop kept the man; the pool has no face count to see it.
