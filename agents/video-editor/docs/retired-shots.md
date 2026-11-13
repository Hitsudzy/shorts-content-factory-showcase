# Retired shots: one shot, one video per channel (CF-0397)

Why a shot shown in one video is not offered to the next. The overview is the [README](../README.md); the procedure the stage
follows is [`SKILL.md`](../.claude/skills/video-editor/SKILL.md).

DoD item 6 forbids a sample twice inside one video (`rhythm.ShotLedger`).
Across videos the channel remembers too: `pipeline/<channel>/retired-shots.json`
lists, per ready video (`<channel>/<batch>/<slug>`), the shots it shows
(`<video_id>:<shot>`, as `plan.json` names them).

* **Written** by `write_batch_metadata.py` every time it writes
  `05-video-editor.json`: the batch's entries are synced to its `videos[]`, so
  a video that goes to the user retires its shots and a video the batch drops
  (CF-0270) gives them back. A rebuild (`pipeline/rebuilds/<ts>`) retires into
  the channel its 05 record names. `--retired-shots PATH` overrides; a batch
  outside `pipeline/` writes none.
* **Only a video that goes to the user retires** (CF-0443): the frame judge
  takes it (the root's `funnel.judge_candidate`: `qc.passed` with no
  `needs_you`, or `judge_admitted_despite`), `score.passed` is not false
  (CF-0434) and, once the batch has a `06-frame-judge.json`, the judge did not
  `reject` it. A QC-failed, NEEDS-YOU or tier-F video in `videos[]` keeps its
  shots on offer; stderr says `shots not retired (CF-0443): <slug> - <why>`.
* **What comes back returns** (CF-0443): every write reads
  `publish/acceptance-log.json` (CF-0523: `$ACCEPTANCE_LOG` or
  `write_batch_metadata.py --acceptance-log` names another file; the tests
  point it at a temp path). A video the user rejected moves from
  `videos{}` to `returned{}` (`returned_at`, `returned_by: acceptance`,
  `reason`) and its shots are on offer again; an accepted one stays retired,
  and retires even if the rule above held it. With no verdict, a judge
  `reject` read off an earlier batch's 06 returns the shots
  (`returned_by: frame_judge`). A verdict that changes moves the entry back.
  A rebuild answers to `rebuilds/<ts>/<slug>` in the log.
* **Read** by `resolve_anchors.py` before the first shot is chosen, through
  `ShotLedger(retired=...)` - every shot-choice path already asks the ledger.
  A retired candidate is refused with its own `rejected_candidates` line
  (`... (CF-0397)`), not counted against the in-video cap; the storyboard
  carries `retired_shots: {registry, exempt, also_exempt, retired, refused}`.
  Only the video's own entry (`<channel>/<batch>/<slug>`: a re-render, another
  attempt, `--exclude-candidate`) and, for a `pipeline/rebuilds/<ts>` rebuild,
  the entry of the video it rebuilds (`also_exempt`: its 05 `rebuild_of`, else
  the batch its copied 03/01 name) never refuse. Another batch's video on the
  same slug does (CF-0532: until 05.10 every entry of the slug was exempt, and
  `delver`/`rennick` of 1825Z took 15 and 19 shots back from earlier `delver`/
  `rennick` videos - "literally the same footage, new text on top"). A rebuild
  resolved with no `--channel` reads its channel off the same records, not the
  directory name `rebuilds`.
  The source is never retired - its other shots stay on offer.
* A block the rule empties takes the same path as a block the in-video cap
  empties: unresolved, its time carried on, the render plan's rungs after it.
* `scripts/retired_shots.py backfill pipeline/<channel> --also pipeline/rebuilds`
  rebuilds the registry from the ready videos on disk (idempotent; a batch
  whose `work/` is gone is read off its record's asset names).
  `... cost pipeline/<channel> --last 5 --also pipeline/rebuilds` prices the
  rule on history (CF-0320).
