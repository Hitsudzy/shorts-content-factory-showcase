# Pipeline

How a script becomes a video, step by step. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

The operator documentation of the Video Editor, one file per subject:

| document | what is in it |
|---|---|
| [`pipeline.md`](pipeline.md) | the steps from the script to the render, the hard asset gate, the narration's length |
| [`narration-length.md`](narration-length.md) | how long a script may be: the estimate, the chunk cliff, the ceilings and the band, the pace |
| [`plan-and-gates.md`](plan-and-gates.md) | the anchor preflight, the anchors, the gates that warn, refusals before the render, the plan built before the handoff |
| [`empty-block-ladder.md`](empty-block-ladder.md) | the ladder under a block that could not be filled |
| [`on-screen-rules.md`](on-screen-rules.md) | the blooper relaxation, the hero in the frame, inset panels, memes and proof cards over captions, the caption band |
| [`frame-judge-pack.md`](frame-judge-pack.md) | the pack the frame judge is handed |
| [`background-bed.md`](background-bed.md) | the background bed, the mix the render builds, and the loudness it ends at (CF-0695) |
| [`retired-shots.md`](retired-shots.md) | one shot, one video per channel |
| [`render-speed.md`](render-speed.md) | what a render costs, generated from the measurement |
| [`source-badge-spec.md`](source-badge-spec.md) | the source-badge specification |

A section that says "below" or "above" may point into a neighbouring file of
this list.

Since CF-0411 the steps from the voice to `plan.json` run first in the Content Researcher's stage (`scripts/plan_check.py check`); this stage renders a plan checked there and skips a script refused there (`plan_check.py reuse`) - see **The plan is built before the handoff** below.

The reserve round after the frame judge (CF-0798) invokes this stage with `mode: new-only`: it renders only the scripts `scripts/pending_scripts.py <batch>` lists (cleared in `04`, in neither `videos[]` nor `refusals[]` of `05`) and records them with `write_batch_metadata.py --new-only`, which refuses to rewrite an entry `05` already holds - see SKILL.md, **Mode `new-only`** (CF-0802).

When the frame judge refused a video for a defect in one or two blocks (a thin strip, a smeared or cut subject, the wrong person, foreign text in the hook), the root's repair round (CF-0881, `shared/judge_repair.py`) asks this repository to mend it before the reserve round replaces the topic: `scripts/repair_blocks.py <batch> --request work/repair-requests.json --result work/repair-results.json` excludes the refused shot on its block (`resolve_anchors.py --exclude-candidate`, the storyboard's own resolve - the topic's indexed pool, no search) or takes the refused meme off, builds the plan, renders, QCs, re-packs the judge's frames and rewrites the video's row with `write_batch_metadata.py --repair`. One pass; anything short of a rendered, QC-clean video is put back from `work/<slug>/repair/before/` and the refusal stands. The judge then looks only at the blocks the result names in `changed_blocks`.

A rebuild (`pipeline/rebuilds/<ts>`) is opened with `scripts/runlog batch-start` off a clean `main` and wrapped in `stage-start`/`stage-done video-editor`, never `batch-done` - see SKILL.md, **Rebuild (Пересборка)** (CF-0401). It is closed by the same `scripts/write_batch_metadata.py pipeline/rebuilds/<ts> --video ...` as a batch and has its own `05-video-editor.json` (CF-0416): the source batch's channel, `rebuild_of`, `score`/`score_line`, and `judge_admitted_despite` on a video whose QC failed only on cosmetic rules (`channels/<id>.json#video_editor.qc_cosmetic_rules`, default `meme_caption_blank_blocks`) - `qc.passed` is never edited.

```
script (with its visual_anchors[])
   │
   ├──► script_anchors preflight   can the pool picture them? no ──► WARNING, goes on
   │                               (CF-0330; recorded in anchor_preflight.warning.json)
   ▼
synthesize_voiceover ──► align_words ──► script_anchors spec ──┐
                                         phrase verbatim,      │
                                         beat_text ► word_index▼
                                  resolve_anchors ──► storyboard.json
                                     │  rhythm.py builds the block plan
                                     │  from the ordered (pattern, rhythm)
                                     ▼
fetch_footage ──► prepare_clip ──► build_render_plan ──► render_video ──► qc_render
                                     │  runs qc_asset          │  build_soundtrack (CF-0423)
                                     │  refuses bad assets     └─► Remotion
                                     ▼
                                  plan.json
```

`build_render_plan.py` will not write a plan that contains a rejected asset.
That is deliberate: the gate is hard, not advisory.

The same holds for the narration's length (CF-0087). `scripts/narration_length.py`
runs on `voice.wav` straight after synthesis: voice + the channel's end card
(`narration_budget` in `channels/<channel>.json`, one level above `agents/`,
read the way `patterns/` is) against the 55s target and the 60s ceiling. Over
the target is a `NARRATION OVER TARGET` line on stderr; over the ceiling is
exit 2 - the script goes back to Content Researcher, nothing downstream is
built. `build_render_plan.py --channel <channel>` holds the same line and
refuses the plan (`NARRATION OVER CEILING - plan not written`), so a batch
that skipped the TTS-stage check still stops before render. The record - total,
target, ceiling, the delta against the script's own `narration.estimated_seconds`
(`--estimated-seconds`) - is `duration.narration` in the plan and, through
`write_batch_metadata.py`, in `05-video-editor.json`.
