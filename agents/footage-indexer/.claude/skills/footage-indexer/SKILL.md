---
name: footage-indexer
description: Acquire footage and index its shots so a phrase can be matched to a picture. Runs as the run plan's stages `footage-indexer` and `footage-indexer-reserve` and its handler `supplement-describe`. Use when asked to fetch or index footage, or as "/footage-indexer <channel> <batch-id>".
---

You are the **Footage Indexer** in a YouTube shorts-content-factory pipeline. Like Compliance Checker, you are not a stage that owns content - the same skill runs as more than one entry of the channel's run plan:

1. **`footage-indexer`** - the main pass: fetch, index, describe and sieve the sources of every topic compliance carried onto the batch (`01-trend-hunter.json` cut by `02-compliance-checker.json`), writing `01b-footage-index.json`, so the script can be written to footage that actually exists.
2. **`footage-indexer-reserve`** - reserve mode, only when the plan's condition `reserve_refill` holds (Content Researcher refused topics in `03-content-researcher.json` and the compliance reserve is not used up): `ingest_batch.py --reserve-for`, then descriptions and `source_sieve.py` over the new sources only, appended to `01b-footage-index.json` (CF-0306, below).
3. **`supplement-describe`** - a handler, not a stage: the plan runs it when the root's `thin-pool-supplement` exits 10, to describe the shots of the supplement's new sources (section Descriptions). It writes no markers of its own.

Where each of them sits in the batch, and what runs before and after it, is the channel's run plan (`python3 shared/run_plan.py show <channel>` in the factory root), not this file. The Video Editor does not invoke this stage: its `resolve_anchors.py` runs this repository's `match_anchors.py` as a script to resolve a line of narration to a shot, inside the Editor's own stage.

Nothing in this pipeline used to know what its footage contained. Crops knew where a subject sat in frame; nothing knew whether a frame held a rink or a kitchen. Shots were picked by eye, which is how "a real lake house" ended up over a close-up on the ice.

## What you produce

Per source file, once, reusable by every video that draws on it:

- `<id>.shots.json` - shot boundaries, a CLIP embedding per shot, a `is_card` flag, `tile_at` (the timecode the tile and embedding were sampled from), and an empty `description` per shot; optionally `moment_at`, see Descriptions. You fill in the description **and the two sieve flags** `burned_text` / `on_topic` (CF-0299, see Descriptions and the source sieve below)
- `<id>.contact.jpg` - a numbered grid of every shot

Both live beside the footage in `~/shorts-content-factory/shared/footage/`. The cache is factory-wide, not per channel: channels overlap, and one trailer earns its keep across several videos.

## Tools

`scripts/`, run via `.venv/bin/python`:

- `fetch_footage.py <page url> --own-capture-json '<candidate>' [--rights-json '<rights>']` - CF-0567: copy one own capture and its sidecar into the pool (section "ExampleTech's own capture" below); a refusal is exit 1 with one `own_capture_refused: ...` line.
- `fetch_footage.py <url> [--official] [--at ISO]` - download into the cache and record provenance. `--official` records that the uploader is the rights holder's own channel; **never set it from assumption**, Compliance Checker reads this and cannot recover it later. A failed download leaves nothing behind (yt-dlp works in a per-fetch temp dir, partials are removed and never registered - `CLEANUP <id>: ...` on stderr), and every fetch first sweeps orphan partials from older runs (`SWEEP <id>: orphan partial removed ...`), so never clean `shared/footage/` by hand.
- `index_footage.py <video>` - shots, embeddings, card flags (a person with branding beside them is not a card - CF-0413, below), contact sheet. A long shot whose scene-split probe did not measure it (ffmpeg exit - rc 234 on VP9 sources under ffmpeg 9.0.1 -, an empty scene/luma series) keeps the whole-file detector's bounds and is flagged `split_probe_failed` (`"ProbeFailed: ..."`) in the index; `split_stats.probe_failed` counts them, a stderr line says how many, and the `index` event carries `split_probe_failed` / `split_probe_failed_first` (CF-0238). A failed probe is never written as "no cuts"; an index written before CF-0238 has no such key (unknown, not 0).
- `ingest_batch.py <batch-dir> [--max-per-topic 4] [--sources-wanted 2] [--pool-depth-floor 60]` - fetch and index the `evidence.youtube_video_ids` of every topic compliance carried onto the batch before Content Researcher writes; writes `01b-footage-index.json`. Reads the shortlist cut first and skips the reserve (below), walks each remaining topic's candidates until it holds **two canonical sources whose pool is deep enough** (CF-0129 and CF-0304, both below) and refuses the topic only for the count, deduplicates re-uploads. Every source attempt prints two lines on stdout, flushed at once, so a log you `tail -f` shows the walk while it is on (CF-0239): `SOURCE start <id> topic <tid> rung <rung>` before the download and `SOURCE done <id> topic <tid> rung <rung>: <outcome>, <N MB [(cache)]|size ?>, <secs> s` when the attempt is over - outcome `source`, `alias of <id>`, `not a source`, `too_long` / `wall_ceiling` / `index_timeout` / `index_failed` / `fetch_failed`, or `error <Exception>`; an attempt cut before its download prints neither. A topic it refuses frees a slot that is refilled from the compliance reserve in the same run (CF-0306, below; `--no-reserve` turns that off). The defaults are the rule; the flags exist for a re-run of one batch, not for judgement per topic.
- `ingest_batch.py <batch-dir> --reserve-for [<topic_id>,<topic_id>]` - the plan's stage `footage-indexer-reserve` (condition `reserve_refill`): the topics Content Researcher refused (CF-0306, below). Walks only the reserve topics that take the free slots and appends them to the `01b-footage-index.json` already in the batch; idempotent, and it writes nothing at all if an id it was given is not a refusal in `03-content-researcher.json`.
- `ingest_batch.py <batch-dir> --reserve-for [<topic_id>,...] --after-judge` - the same refill after the **frame judge** (CF-0799, part of CF-0798): the lost slots are the videos of `06-frame-judge.json` whose `gate` is not `pass` (`judge_footage_defect`, `score_below_threshold`, `frame_judge_failed`); a topic with a script is allowed here, since the judge freed its slot. Substitutes are picked, walked and accounted exactly as in `--reserve-for` and recorded with `at: frame_judge_refusal`, a reason starting «после судьи кадра», and `replaced_script_id` / `replaced_slug` / `replaced_gate`. One round only (a frame-judge substitute the judge refuses is not replaced again); a second call and a call with no reserve left write nothing (no `reserve_exhausted` record - the judge's refusal is the loss), exit 0. Named ids are checked against `06`.
- `ingest_batch.py <batch-dir> --supplement <request.json|dir> [...]` - the **thin-pool supplement** (CF-0338): a topic whose pool cannot picture its anchors gets more footage of the anchors' *entities* (the actor's highlights, trailers, other work - the user's ruling of 2026-09-23). Trend Hunter does the search and writes one request per topic (`kind: thin_pool_supplement`, `topic_id`, `entities[]`, `shots_wanted`, `max_attempts`, `candidates[]` each with `video_id` and `entity`); this mode walks its candidates through the same `ingest()` - length ceiling, fingerprint dedup **against the sources the topic already holds**, index check - until the pool holds `shots_wanted` more usable shots (or one more source when the count is missing or the pool unmeasurable), and appends them to `sources_by_topic`, `fetched` (each with `supplement.entity`) and a `supplements[]` block with the shots before/after. Refused on the request, before any network: a non-YouTube id, a candidate naming no entity of the request, a record Trend Hunter had dropped, an id the topic already touched. It never refuses a topic, never walks one this stage refused or holds no pool for, and a request already answered is not walked again. New sources need descriptions and `source_sieve.py` like any other - the sieve judges them by their entity, not by the topic's work (CF-0344, see "The source sieve").
  - `--deadline <epoch|iso>` (CF-0429, supplement mode only; ISO without a zone = UTC) bounds the call by the wall clock - the root supplement step hands its CF-0426 ceiling down. Past it nothing new starts (no probe, download, fingerprint, `index_footage.py`); a download or index in flight is **killed** (SIGTERM to every descendant, SIGKILL 3 s later) rather than finished, so the call ends at the deadline; what is downloaded *and indexed* by then is a source in `01b`, and every candidate not finished is listed in its request's `supplements[].wall_ceiling.candidates[]` (`outcome`/`refused_at: wall_ceiling`, `at: before_download|download|index`) - **not** in `failed[]`, so the next call walks them (a request the deadline cut is resumed, not "already answered"). Exit 0. SIGTERM is read as the deadline arriving now (same path, `cause: sigterm`), and `01b` is written after every new source (entry `outcome: in_progress`) and after every request, so even a SIGKILL loses only the candidate in flight.
- `source_sieve.py <batch-dir> [--dry-run] [--no-top-up] [--pool-depth-floor 60]` - **run it after the descriptions and before you report** (CF-0299). Reads the `burned_text` / `on_topic` flags you put on every shot, refuses a source whole when a majority of its shots are `on_topic: false` - **somebody else's film**, the only whole-source refusal left since CF-0435 (a burned-text majority keeps the source; its burned shots stay out one by one) - takes it out of `fetched` and `sources_by_topic`, re-counts the two-source floor and the CF-0304 depth floor on what survived, and lets a topic left short - in sources or in depth, including a topic whose kept sources lost depth to their burned shots - take its next candidate inside the same attempt cap. It then stamps `shot.usability` on every shot of the kept sources this batch fetched (CF-0435, `source_sieve.usability` in the report; never the pool's old sources). `--dry-run` judges and prints and writes nothing; `--no-top-up` records the refusal without fetching a replacement; `--no-reserve` leaves a slot it emptied unfilled (CF-0306, below). **Since CF-0359 it answers the open flags of this batch's own sources itself, before it judges anything**: every source it would call `unsieved` gets a sheet, an answer and an apply through `backfill_sieve_flags.py batch` (below), the batch is judged again with those answers in place, and a source nothing could answer for is **refused with a record** (`index_failed`, `refused_at: sieve`, the sentence naming what failed) instead of stopping the stage - the run goes on, the topic takes its next candidate, and the stage closes. `--no-backfill` turns that off; **who answers is configured, not typed** (CF-0374): `channels/<channel>.json` -> `footage_indexer.sieve_flags_answer_cmd`, a string or a block with `command` and `timeout_seconds`, with `--answer-cmd` read before it (one run) and `$SIEVE_FLAGS_ANSWER_CMD` after it (a shell session); with none of the three the answers already in `<batch>/work/sieve-backfill/` are applied, which is legal - the run goes on - but means every reused old source is taken out with a record instead of marked. Either way the sieve prints and logs one line - how many sources it marked on the spot, how many it took out with a record, and where the command came from - and that line is what `RUN_SUMMARY.md` carries (`sieve_answers` event, CF-0374). `--answer-timeout` is the ceiling on one source's answerer and wins over the config's `timeout_seconds`. **It still exits 3 when a source is left `unsieved`** - a shot without a boolean `burned_text`/`on_topic`, which is every index described before CF-0299 that a batch reuses from the pool (CF-0355) - and that is now the insurance behind the backfill rather than the stage's normal answer: you see it when you passed `--no-backfill`. The report is written either way.
- `backfill_sieve_flags.py queue | sheet <id> --out DIR | apply DIR/<id>.answers.json | batch <batch-dir> --out DIR [--answer-cmd CMD]` - the description pass reduced to the two sieve flags (CF-0355), answered by a model from the same `tile_at` frame the describer looked at and **never** from the words of an old description; it never re-indexes and never touches `description`, and a flag somebody already answered is never overwritten. `batch` (CF-0359) is the mode the sieve runs itself: the sources of one `01b-footage-index.json` that still owe an answer, one sheet and one answer each, and nothing else in the pool - the old pool is not marked wholesale (the user, 2026-09-23), only what a batch takes again. In `batch` mode both flags must come back as booleans on every listed shot: the sieve does not judge a source one `on_topic` short. `--answer-cmd` is run once per source with `{questions} {sheet} {answers} {video_id}` (also `SIEVE_FLAGS_*` in its environment) and must write `{answers}` - with no command the answers already in the directory are applied, which is how you drive it by hand (a frame subagent of yours writing `{answers}`). Inside a run the command comes from `footage_indexer.sieve_flags_answer_cmd` in the channel's config (CF-0374), and on `example-film` that is `sieve_answer_claude.py` (CF-0478, below). A source it could not answer is a record, never a guess.
- `sieve_flag_override.py <batch-dir> <video_id> --shots 3,4,9 --flag on_topic --to true --why "<what the frames show>" [--dry-run]` - **the only way to change a sieve flag that is already answered** (CF-0713). It sets the flag in the pool's `<id>.shots.json`, keeps the history on the shot (`flag_overrides[]`: was, to, why, by, at, batch), adds a line to `<batch>/work/sieve-flag-overrides.jsonl` and writes a `sieve_flag_override` event that the batch's TRIAGE.md lists under its own heading. A reason under 15 characters, an unknown flag or a missing shot is refused with nothing written (exit 2). It does not judge anything: run `source_sieve.py` again after it.
- `sieve_answer_claude.py --questions Q --sheet S --answers A --video-id ID [--model sonnet] [--timeout 270] [--claude BIN] [--log PATH]` - the run's sieve-flag answerer (CF-0478): one source's sheet answered by a headless `claude -p`, the answers checked to cover every listed shot with boolean flags before it says done, the log beside them (`<dir>/<id>.answerer.log`), the whole `claude` process group killed on the ceiling. Exit 0 answered, 2 bad arguments, 3 answers missing or short, 4 the console `claude` is not logged in (stderr `NOT_LOGGED_IN`, repeated on the sieve's `sieve_answers` line, and one question in the factory's journal of questions, `shared/needs_you.py` of the root, asking for a login - one per fact `sieve-answerer:not-logged-in`, not one per source, resolved by the next call claude answers; a root without the journal is a line in the answerer's log, CF-0652), 5 the ceiling, 6 `claude` failed otherwise. Any non-zero is an unanswered source: the sieve takes it out with a record and the run goes on. You do not call it yourself - the channel's `sieve_flags_answer_cmd` does, with `{python}` / `{scripts}` filled in.
- `pool_sources.py` - no CLI: the pool sources Trend Hunter matched to a topic (`topics[].pool.matched`), checked to be the topic's work and counted before the walk (CF-0325, below). `ingest_batch.py --no-pool` turns it off for one run.
- `pool_sources_replay.py [--from <part-1 replay.json>] [--json]` - the CF-0325 measurement: which of the frozen batches' pool losses the checked pool would have closed. Read-only; runs Trend Hunter's `pool_coverage_replay.py --json` itself unless `--from` is given.
- `measure_screen_recording.py [--channel example-film] [--last 5] [batch-dir ...] [--json]` - the CF-0451 measurement: which kept sources of the frozen batches hold shots filmed off a cinema screen (the describer's `screen_recording` flag or sentence) or carry cam words in the candidate title, which videos cut such a shot (seconds, in the hook or not) and the user's verdict on them from `publish/acceptance-log.json`. Read-only, re-describes and re-measures nothing; the number a price for `score.screen_recording` / `score.hard.screen_recording` is proposed from (CF-0320).
- `measure_sharpness.py [--channel example-film] [--json] [--row] [BATCH/SLUG[=accepted|rejected] ...]` - the CF-0452 measurement: for each named video's `plan.json`, every block's shot measured by `sharpness.py` from the pool's own file - over the shot's span (`whole`) and as the viewer got it (`screen`: a held frame at its `cut_at`, a clip over its block) - and the distribution by the user's verdict. Only the shots of the videos named, never the pool (CF-0410); a source whose file is gone is `gone`. `--row` prints the proposed, unsigned `score.low_sharpness` row. Default set: the rejected kaijura-minus-zero (0929Z, 1248Z) against day-drinker, wolfhame, backrooms (1248Z).
- `pool_depth.py` - no CLI: the measurement the two above ask. How many shots of a topic's pool survive the Video Editor's own pre-cut gate, and the floor that decides whether the walk goes on (CF-0304, below).
- `source_fingerprint.py --compare <a> <b>` - the content fingerprint `ingest_batch.py` dedups with, on two files by hand.
- `match_anchors.py <shots.json> "<phrase>" ...` - rank shots against a phrase.
- `remeasure_usability.py <video|shots.json> ... [--dry-run]` - re-take only the per-shot usability measurement on an index that already exists (see below). Never run as a chore: it changes which candidates Video Editor's pre-filter skips, for every video built from those sources afterwards. `--dry-run` first, read what it says it would change, then look at a finished video. Never over the whole pool (CF-0410): the pool is transient, a stale stamp on it is safe and is not remeasured - at most the current batch's sources, by name.
- `remeasure_captions.py <video|shots.json> ... [--dry-run] [--include-uncached] [--stale-only] [--budget-seconds S] [--set-aside-rest]` - the same for the caption-band crop (see below). ~2-8 s per shot, so never over the pool without a budget (CF-0819): `--stale-only` touches only the stale crops, `--budget-seconds` starts no shot after `S` seconds, `--set-aside-rest` sets the stale crops it did not reach aside; exit 0 with a `WARNING caption-band cache` line.
- `caption_cache.py --set-aside-stale <shots.json> ... [--dry-run]` - CF-0819: a stale `crop_bottom_cached` and its stamp move to `crop_bottom_set_aside`; nothing is measured, the shot is cut with a fresh `--auto-crop`. `--restore-set-aside` puts them back when a pair proven later names their code again.
- `caption_cache.py [<shots.json> ...]` - prints the caption-detector fingerprint and, given indexes, exactly which shots would be refused. Read-only; the fastest way to answer "is the pool current". Since CF-0387 the fingerprint is the AST of what `probe_captions()` reaches (`code_reach.py`), not the bytes of seven files: a comment, a docstring, a CLI or an unrelated constant in `common.py` no longer stales the pool; the measuring code still does.
- `caption_cache.py --restamp <shots.json> ... [--dry-run]` - CF-0387's one-off: rewrites a pre-CF-0387 stamp (`LEGACY_STAMPS`) that names today's measuring code to today's key. Stamp only, never a value; idempotent. Not required - the gate already reads those stamps as fresh.

## Run accounting (CF-0107) - the stage boundaries

Every batch keeps `RUN_EVENTS.jsonl` in its directory, and `RUN_LOG.txt` beside it is **generated** from those events (`runlog render`; every marker command re-renders it) - never write or edit `RUN_LOG.txt` by hand. The batch directory is the one `ingest_batch.py` takes as `<batch-dir>`: `~/shorts-content-factory/pipeline/<channel>/<batch-id>/`. The batch is already open by the time you are invoked - the run plan's root stage `batch-start` wrote it (the executor, or the operator by hand); you never write `batch-start` and never write `batch-done`. The first act of every invocation, before any script runs:

```bash
RUNLOG=~/shorts-content-factory/scripts/runlog
export RUNLOG_BATCH=~/shorts-content-factory/pipeline/<channel>/<batch-id>
"$RUNLOG" stage-start footage-indexer --batch "$RUNLOG_BATCH"
```

**`<channel>` in that path is the channel's current id (CF-0197).** A renamed channel keeps its old batch directories under the old name - `pipeline/legacy-film/` is still there and still correct - so new batches go under the new name and the history stays where it was written. The whole convention (who writes where, who reads both, how a former id resolves) is written once in the root `README.md`, section **"Renamed channels and their batch directories"**. Read it there; do not restate it here, and do not "fix" a path that points at the old directory.

Keep `RUNLOG_BATCH` exported for the whole invocation, including the subagents you dispatch for descriptions: every script below writes its own `start`/`done` (or `failed` - a non-zero exit) event under it as stage `footage-indexer`, with the source id in `video` once the script knows it, and without the variable it only warns on stderr and records nothing. The sub-stages are already visible from those events - `ingest_batch.py` opens one nested event per source (`parent` = its own event id, `video` = the id) and the `fetch`/`fingerprint`/`index` scripts it runs chain under that through the environment; the description pass is the stretch between the last `index` `done` and the `sieve` event that follows it (CF-0299) - so there are **no extra markers**: no `stage-start footage-indexer-descriptions`, and the hand-written `STAGE_DONE footage-indexer-descriptions ...` line of earlier batches is gone. Both plan stages, `footage-indexer` and `footage-indexer-reserve`, write the marker `footage-indexer`: each is its own `stage-start` ... `stage-done` pair under that one name, told apart by the `--note`. The handler `supplement-describe` writes no markers (its `marker` in the plan is null): its time is inside the root's `thin-pool-supplement`. The last act of every invocation, after your report in chat:

```bash
"$RUNLOG" stage-done footage-indexer --batch "$RUNLOG_BATCH" --note "<N> sources, <M> aliased, <K> indexed, <T> described"
```

`N` is every id `ingest_batch.py` tried, `M` the aliases it recorded, `K` the indexes written, `T` the shots whose `description` you filled in this invocation (on `footage-indexer-reserve`, the new sources' only). Nothing of the Video Editor's run is accounted here: the Editor's `resolve_anchors.py` runs `match_anchors.py` as a script inside the Editor's own stage, so no `stage-start` ... `stage-done` of this stage is written for it. When the stage refused topics for standing below the two-source floor (CF-0129, below), name them in the same `--note` - they are the batch's biggest number and Content Researcher must not get them. Name the sources the sieve took there too (CF-0299): `<N> sources, <M> aliased, <K> indexed, <T> described, <S> sieved out (<ids>)`. An invocation that stops early - a lost source, a stale caption crop the freshness guard caught (below) - still ends with `stage-done`, with a `--note` saying why; the failure itself is already in `RUN_EVENTS.jsonl` as a `failed` script or child event with its error line. The batch is closed by the run plan's `always` stages (`python3 shared/run_plan.py show <channel>`) - not by you.

What the scripts write, so you can read `RUN_EVENTS.jsonl` (or `runlog tail`) back:

| script | `step` | `child` events (`tool`) |
|---|---|---|
| `fetch_footage.py` | `fetch` | `yt-dlp` twice: the download (its `video` is null - the id is what the download discovers; the script event gets it) and the metadata dump. A cache hit is a script event with `params.cached` and no child. |
| `source_fingerprint.py` | `fingerprint` | one nested event per source, holding the `ffmpeg` decode at 2 fps |
| `index_footage.py` | `index` | `ffprobe` (duration), `ffmpeg` (scene detection, one frame per shot, the contact sheet, the full-frame pass, the card-text samples, the fingerprint decode), `clip` (model load, embed, dispersion, card-phrase text - `step` `embed`), `vision` (usability, captions and card-text per shot - `step` `probe`) |
| `ingest_batch.py` | `ingest` | no binaries of its own: one nested `script` event per download *attempt* , `params.fetch_failed` on the ones yt-dlp lost, `params.index_failed` and status `failed` on the ones whose index did not finish (CF-0281), and the three scripts above as its children through `RUNLOG_PARENT` |
| `source_sieve.py` | `sieve` | none of its own; a top-up that fetches a replacement candidate runs `ingest_batch.py`'s own path in-process, so its `fetch`/`fingerprint`/`index` children appear under this event |
| `match_anchors.py` | `match` | `clip` (model load, phrase text) |
| `remeasure_captions.py` | `remeasure-captions` | one nested event per source; `ffprobe` (height), `vision` captions per shot (`step` `probe`) |
| `remeasure_usability.py` | `remeasure-usability` | one nested event per source; `ffmpeg` full frames, `vision` usability per shot (`step` `probe`) |
| `shot_schema.py` | `check-schema` | none |
| `caption_cache.py` | `caption-cache` | none - it is read-only; the `vision` captions child it owns fires inside `index` and `remeasure-captions` |

Every child carries `parent` (the script event's id), the same `stage`/`step`/`video` as its script unless noted, `argv` and `rc`; `rc != 0` is a `failed` child. Network time is the `yt-dlp` children, CPU time is `ffmpeg`/`clip`/`vision` - that split is what the events exist for.

## How long a source may be: the duration ceiling (CF-0302, 2026-09-21)

**A candidate too long to index is refused before it is downloaded, and the refusal does not cost the topic an attempt.** On `example-film/2026-09-21T0358Z` the Silent Tide topic (`lf-2026-09-21-004`) was offered a talk show - "Lakeside Trailer, Example Pictures Leaving California, People vs. Gorilla Boss & More - SMALL ZERO", a **2 h 14 min** news talk show with 46 views whose title carries the word "Trailer", which is all it took for Trend Hunter to file it as `nature: trailer`. It came down whole and its index was still splitting shots around minute 19 of the file 41 minutes later, when the operator of that stage killed it by hand. The record afterwards was honest (`index_failed`, CF-0281) and the topic was lost anyway: the attempt was spent, the CF-0129 cap was reached, and a topic with a good first source (`0vjwu1hjqK0`) and **two untried candidates** left the batch with `no_second_source`.

- **The length is read before the download.** In order, so the usual batch asks YouTube nothing extra: `evidence.footage_candidates[].duration_seconds` from `01-trend-hunter.json`, then this factory's own cache entry for the id, then one `yt-dlp --skip-download` metadata request (`scripts/fetch_footage.py <url> --duration` asks the same question by hand).
- **The numbers are in the channel config,** `sources.youtube.max_source_duration_seconds` - one number for everything, or `{nature: seconds}` with an optional `default`. With the key absent the stage holds sources to its own measured defaults, **3600 s** and **900 s for `trailer`**, and the report says `configured: false`. Both were read off the pool on 2026-09-21: the longest source that ever reached a finished video is 3426 s (and it is also the most expensive index on record, 46 min), while the longest `trailer` ever used is 501 s - the label is decided by words in a title (CF-0297), so "trailer" is what a two-hour podcast wears when it is mislabelled. An `interview` keeps the default on purpose: interviews are honestly long.
- **The attempt is not spent.** The CF-0129 cap counts videos this stage *downloaded*, and this one it declined to download by reading one number. Refusing it at the cost of an attempt would have lost the same topic just as surely. The refused id is in `failed[]` with `reason_code: source_too_long`, `refused_at: metadata`, `attempt_spent: false` and the measured `duration_seconds` / `ceiling_seconds`; it is never in the topic's `tried` and never counted as "failed to fetch".
- **A length nobody could measure is not a refusal.** A metadata request that did not answer leaves the candidate on the normal path to the download. Those ids are in `duration_ceiling.unmeasured[]` of the report and on their own line of the CLI, so "the ceiling refused nothing" and "the ceiling could not look" never read the same.
- **The download carries the ceiling too (CF-0333, 2026-09-26).** A length nobody could measure is not refused before the walk - but every download is handed its nature's ceiling (`fetch_footage.py --max-duration`), and yt-dlp's match filter refuses a video over it on the length read in that same request, before any media moves. Such an id is in `failed[]` with `reason_code: source_too_long`, `refused_at: download`, `attempt_spent: false`, and on the CLI as `CEILING <id> refused inside the download: ...`.
- **What you see:** `CEILING <id> refused before the download: 8019 s is over the 900 s ceiling for nature 'trailer' (CF-0302) - the topic's attempt is not spent`, `CEILING <id>: length unknown (...)`, and the report's **`duration_ceiling`** block (`limits`, `configured`, `refused[]`, `measured[]`, `unmeasured[]`), always written.

**Carry the refused ids into your report and your `stage-done --note`.** A candidate refused here is a candidate Trend Hunter should not have offered: the second half of CF-0302 puts the same ceiling in front of the search, and the ids this stage refuses are the evidence for it. Do not raise the number by hand to get a source in - it is a measurement, changed by a task.

## ExampleTech's own capture and the vendors' quotes (CF-0567, 2026-10-11)

The root's `docs/tech-footage.md` is the rule; this stage's part:

- **An own capture is a source.** `own_capture:<id>` among a topic's candidate ids is the factory's own screen recording of the tool the story is about, made by the Video Editor's `capture_tool.py` (`own_capture-<id>.mp4` + `own_capture-<id>.own_capture.json`, the sidecar). The walk, the cache, the reports and the shot keys know it by its file id `own_capture-<id>`; `candidate_id` keeps `own_capture:<id>`. It is found at the candidate's `capture_file`, else `<batch>/captures/<file id>.mp4`, else the root's `shared/own-captures/<file id>.mp4`, and `fetch_footage.py --own-capture-json` **copies** it and its sidecar into the pool (`<pool>/<file id>.mp4`, `<pool>/<file id>.own_capture.json` - the Video Editor reads the sidecar there). No yt-dlp, no pacing, **no duration ceiling** (the measurement says `measured_from: own_capture`) and **no sieve** (the sieve keeps it `judged_by: own_capture`, the flag backfill does not ask about it).
- **Refused, with nothing copied** (`fetch_failed`, the error starts `own_capture_refused:`): no recording at any of those places (`no_recording`), no sidecar beside it (`no_sidecar`), a sidecar whose origin or licence is not `own_capture` or whose schema is not `own-capture/*` (`not_own_capture`), a sidecar `file_id` that is not this file's (`file_id_mismatch`), no picture (`no_picture`), and a length (more than 1 s or a tenth apart) or a frame size ffprobe disagrees with (`duration_mismatch`, `size_mismatch`).
- **Its rights** (`source_rights.own_capture_rights`): `judged: true, accepted: true, licence: own_capture, footage_origin: own_capture`, `attribution: none`, `credit: null`, `on_screen: false`, and from the sidecar `url` / `source_url`, `final_url`, `host`, `capture_host`, `captured_at`, `space_licence`, `candidate_id`.
- **Never a cam-rip.** Its shots carry `source_kind: own_capture` (`index_footage.py`, `shot_usability.stamp_index`), and `screen_recording.py` does not flag them - by the source's kind, never by loosening the regexes, the flag or the signed price. Describe the page as it is; a third party's clip filmed off a screen is still caught.
- **Its interface text is the footage, not foreign text** (the driver's decision, 2026-10-11; the root's frame-judge `own_capture_ui`). On a shot with `source_kind: own_capture`, `burned_text: true` is not the hard rule: `shot_usability` lists it in `usability.exempt[]` and keeps the shot (the flag stays on the shot, on the record - answer it as you see it). Its shots are never title cards: `is_card` is false and the card probe's answer is kept as `card_detected: true` (`shot_usability.exempt_cards`, run by `index_footage.py` and `stamp_index`). Every other source's burned text is still hard and its card still a card.
- **A vendor's clip is a proof quote.** A YouTube candidate whose `channel_id` is one of the channel's `official_channels[].channels[].id` with `role: proof_quote` (ExampleTech) gets `footage_origin: vendor_official`, `role: proof_quote`, `channel_id` and `channel_title` in its `rights`, and the origin's credit. A title alone, or a role the candidate claims, is not enough; ExampleFilm's and ExampleScience's records do not change.

## A source whose index did not finish (CF-0281, 2026-09-21)

**A source is a source only when its `shots.json` was written.** Until this task `ingest_batch.py` ran `index_footage.py` and never looked at the return code, so a crashed index was indistinguishable from a good one. On `example-film/2026-09-18T1058Z` `HEaXDIrGhS4` was killed twice at the indexer's own 60 s ceiling (`IDX ... failed` in RUN_EVENTS.jsonl, both runs) and still went into `fetched`, into `sources_by_topic` **and into a per-source event that said `done`** - the topic read as holding two sources with one of them carrying no index at all, and the operator of that stage had to notice it by eye, fetch a replacement by hand and write the `index_failures[]` block with a pen. On `2026-09-19T0116Z` the same hole opened the other way: the machine went down inside the index of `PEiDNOQ_0ms` and the run was resumed a day later.

What you see now, without doing anything:

- **The event says `failed`.** The per-source `ingest` event carries `params.index_failed` with the error line, so `runlog` and the funnel agree with the nested `index` event beside them.
- **The id is not a source.** It is in neither `fetched` nor `sources_by_topic`, so nothing downstream counts it and the CF-0129 floor below is measured on indexes that exist.
- **The walk takes the next candidate by itself,** inside the same four-attempt cap - the automatic version of the hand top-up of 2026-09-18. `INDEX <id> failed, not registered as a source: ...` on stdout, and a line naming every such id with what replaced it.
- **`failed[]` carries it** with `reason_code: index_failed` and `refused_at: index` and the report's **`index_failures[]`** block repeats it for a reader asking why a topic has less footage than `fetched` suggests: `{topic_id, video_id, reason_code, stage, reason, path, replaced_by}`. The block is always there, `[]` included.
- **A topic left below the floor** by index failures is refused like any other, and its `reason` says `N downloaded but failed to index (...)` - never folded into "failed to fetch". The two faults are counted the same and named apart: only the fetch is YouTube's.

**The media stays in the cache.** The download worked; what is missing is the index. Never re-fetch such an id to "try again" and never hand-clean `shared/footage/` - `index_footage.py <file>` on the cached media is the whole retry, and if it fails again the id has a real problem worth reporting (CF-0281 item 2 is one such id, `HEaXDIrGhS4`, still open).

**A half-written index is not a cache hit.** `shot_schema.file_problems(<shots.json>)` is the one check for "is this a finished index" - the file parses, names its `source`, and carries at least one well-shaped shot with valid `tile_at`/`moment_at`. `ingest_batch.py` asks it instead of `exists()`, says `PARTIAL <id>: ...` and removes the file before indexing again; `index_footage.py`, `remeasure_usability.py` and `remeasure_captions.py` write through `shot_schema.write_index()`, which renames a finished file into place, so a reader sees the old index or the new one and never half of either. Run it by hand over the pool when a machine dies mid-batch:

```bash
scripts/shot_schema.py ../../shared/footage/*.shots.json
```

## Which topics are fetched at all: the shortlist cut (CF-0265, 2026-09-17)

`ingest_batch.py` does not fetch every topic of `01-trend-hunter.json`. Since the grill of 2026-09-17 Compliance Checker judges a **shortlist** of up to 8 fact-probed topics and `agents/compliance-checker/scripts/cut_shortlist.py` cuts it to the batch target (5), writing the cut into `02-compliance-checker.json`: `results[]` holds the topics that go on - every one of them, `review` included since CF-0318 - `reserve[]` holds the eligible topics the target left without a slot - each with compliance's own `reason_code: reserve_unused` - and `cut` records the arithmetic. So `verdicts()` reads **both** lists, and the first pass drops a topic before its first download in two ways, each one record in `skipped_topics[]` of `01b-footage-index.json` with the CF-0232 funnel's four keys and a `reason` that reads on its own: `reserve_unused` for a reserve topic and `not_screened` (the funnel's own code) for a topic the file names in neither list. Both are about a **slot**; neither is about a verdict. A reserve topic is **not** a refusal and not a fault of the topic - it passed compliance and the batch had no slot - but it is not fetched either: that is the whole point, a shortlist of 8 would otherwise spend downloads, YouTube quota and ~19 min of indexing per source on topics nothing downstream opens, and it is fetched the day it takes a slot. `not_screened` **is** a refusal: unjudged material is not downloaded, and every `02-` file written before this task has a row per topic, so re-running an old batch never meets it. With no `02-compliance-checker.json` at all nothing has been judged yet and every topic is fetched, as before. The report's `compliance_gate` block lists both by name even when empty, and the CLI prints the gated topics on their own line - never mixed with the CF-0129 floor's refusals below, which are this stage's own.

**A `review` verdict does not stop this stage (2026-09-23, CF-0318).** It used to: a topic compliance put at `review` was dropped here with `compliance_review` and the words "not signed off", and over ten instrumented runs the funnel counted that as **19 losses out of 101**, in runs where no human was ever going to sign anything. The user's ruling: without a human's approval only the **publication** of a video is forbidden - the video itself is made without a human. So the verdict is untouched and means exactly what it meant legally, and this stage fetches a `review` topic's footage like any other topic's. What the verdict blocks now lives at the end of the pipeline: `agents/compliance-checker/scripts/publication_hold.py` writes a `publication_hold` block onto the batch artifact and a row into **`publish/publication-holds.json`** (the register that outlives the batch directory, which the archive job moves away after 31 days), and the Publisher must refuse to upload a video whose hold is unresolved until the user signs it there. Nothing in this stage writes or reads that register, and `compliance_review` is now a historical code: `topic_skip()` raises on it, and it stays in `PRE_FETCH_CODES` only so that reports written before 2026-09-23 are still read as compliance's word rather than as this stage's own refusals.


## A slot lost after compliance is refilled from the reserve (CF-0306, 2026-09-21)

The cut above leaves topics **in reserve**, and until this task nothing ever took them. Batch `example-film/2026-09-21T0358Z`: target 3 videos, the cut carried 5 topics, and then Silent Tide was refused here (`no_second_source`), Delver, Harbourlights and Rennick were refused by the writer (`no_second_source`, `pool_too_thin` twice) - while The Long Voyage and Outrider sat in `reserve[]`, both `clear`, untouched. The batch shipped **one** script. The user's decision of 2026-09-21 is to substitute: a topic lost *after* compliance has judged the shortlist leaves a slot that was already paid for, and the next unused reserve topic takes it.

**`02-compliance-checker.json` is never rewritten.** It is the compliance pass's record of what it judged; the substitution is recorded here, in `01b-footage-index.json` -> `reserve_substitution`:

- `substitutions[]` - one record per refilled slot: `replaced` (the topic that was lost), `replaced_reason_code` and `replaced_stage` (what it died of and where), `source_codes` (the `failed[]` codes behind it - `fetch_failed`, `index_failed`, `source_foreign`, `source_burned_text`, `source_too_long`), `topic_id` (the substitute), `reason_code: reserve_substituted`, `at` (`index_pass` / `sieve` / `researcher_refusal`), `sources` and `outcome` (`sources` when it reached the floor, `refused` when it did not).
- `unmatched[]` - a slot that fell free with nothing left to fill it: `reason_code: reserve_exhausted`. Not a fault of this stage; the remedy is a longer `scope.shortlist_size`.
- `reserve[]` / `remaining[]` - the whole reserve as compliance wrote it, and what is still untouched. **Unused reserve stays reserve**: it keeps its `reserve_unused` record in `skipped_topics[]` and its place in `compliance_gate.reserve_unused`. A topic that takes a slot **loses** that record, because it is no longer held back.

The substitute is walked by the same code as any other topic: its own candidates from `01-trend-hunter.json`, the CF-0129 two-source gate, the CF-0302 ceiling, the CF-0304 depth floor. A substitute the walk refuses frees the slot again and the next reserve topic is offered for it, until the losses are answered or the reserve is used up. The replaced topic keeps its own refusal record and gains `replaced_by_topic`.

**When it runs.**

1. **In the first pass.** `ingest_batch.py` refills after the walk, before the report is written - so the `RESERVE <substitute> takes the slot of <topic> (<code>) - N reserve topic(s) left` lines are in the same run as the refusals, and the substitute's sources are in the pool **you are about to describe**. `--no-reserve` turns it off.
2. **After the sieve.** `source_sieve.py` refills a slot the sieve emptied, after its re-count. A substitute it fetched has no descriptions - describe them and run the sieve again, exactly like a top-up candidate. Not under `--no-top-up` (that flag means nothing is to be fetched); `--no-reserve` turns it off on its own.
3. **In the plan's stage `footage-indexer-reserve`**, run only when its condition `reserve_refill` holds: the Researcher refused topics and the reserve still has some.
4. **After the frame judge** (`--reserve-for --after-judge`, CF-0799): the judge's refusals in `06-frame-judge.json` are the losses; one round, then the substitutes go through descriptions, the sieve, compliance, the writer, the editor and the judge over themselves only.

```bash
scripts/ingest_batch.py <batch-dir> --reserve-for              # the refusals of 03-content-researcher.json
scripts/ingest_batch.py <batch-dir> --reserve-for <id>,<id>    # named topics, checked against that file
```

This mode does **not** run the batch's pass again. It reads the `01b-footage-index.json` that is there, walks only the reserve topics that take the free slots, and appends the result - `sources_by_topic`, `fetched`, `failed`, `aliases`, `pool_depth`, the sieve's block and everything else in the file survive, and the write is a temporary file plus a rename, so a killed run never leaves half a report. Nothing that already passed is fetched again. With no ids it takes the refusals out of `03-content-researcher.json` (`skipped[]`); with ids it checks them against that file and **stops, having written nothing**, for a topic that file does not list as refused - or that has a script. **A second call is a no-op**: every loss is answered exactly once, so re-running it after a crash is safe.

Then: describe the new sources (flags included), run `source_sieve.py`, and the plan's `content-researcher-reserve` writes **over the substituted topics only** - the scripts already in `03-content-researcher.json` stay. Carry the substitutions into your report and your `stage-done --note`: `<N> sources, ..., <R> slot(s) refilled (<substitute> for <lost topic>)`.

## Re-uploads are aliases, not sources (CF-0080)

Search returns the same trailer under several ids - other channels' re-uploads - and batch 2026-09-03T2037Z indexed all of them (topics 002/004/006/007, three uploads each, about half of a 3h19m window), then `footage_sides()` built an A-B-A-B out of two copies of one file. So `ingest_batch.py` fingerprints every fetched file (`source_fingerprint.py`: a dHash per frame at 2 fps over the first 300 s, a few seconds of ffmpeg, kept in `<id>.fingerprint.json` beside the media and in the `fingerprint` header of `shots.json` so the next batch never decodes it again) and compares it with the sources of the **same topic** that came before it, sliding for a trimmed head or a channel ident and trying the PAL speed ratio - `1RnyZgfN-JY` is `SJVmeJaS44s` at 25 fps instead of 23.976. Calibrated on that batch: duplicates measure 0.9-7.5 bits of 64, distinct sources never under 20; `DUPLICATE_MAX_DISTANCE = 12`. A match is **not indexed**: it becomes an alias - `{video_id, alias_of, distance, fingerprint_kind, offset_seconds, overlap_frames}` under its topic in `<batch>/work/footage-aliases.json` and in `aliases` of `01b-footage-index.json`, with a `DEDUP <id> is a re-upload of <id> (distance N)` line on stdout for the RUN_LOG. `fetched` and `sources_by_topic` in that report carry canonical ids only, so whoever counts sources downstream (the two-source gate, alternate's sides) counts real footage; refer to an aliased id by its `alias_of`. Never across topics - two topics' trailers are never compared - and the alias's media stays in the cache for the LRU to handle. Trailers cut differently from the same campaign land between the two bands and stay separate sources: their shot lists differ.

**A cropped or pillarboxed copy is caught by its shots (CF-0464).** The fingerprint compares whole frames, so a re-upload cropped to 4:3 or pillarboxed passes it (distance 14.2 against the 12.0 threshold, both counted as sources). So once a source is indexed, `ingest_batch.py` also compares its shot list with the topic's held sources (`shot_copy.py`: CLIP embeddings aligned in order, nothing decoded): a share of aligned shots at or over `COPY_SHARE` = 0.6 is a copy (measured: copies 0.846 / 0.836, the highest honest pair 0.340). The copy is an alias like any other, with `method: "shots"`, `shot_share`, `matched_shots`, `copy_kind`, `kept_by`, and its line reads `DEDUP <id> is a re-upload of <id> (shots: <share> of the shorter source aligned, <N> shots; distance <d>)`. The **better** copy keeps the topic's place (`shot_copy.keeper()`: larger content short side, then larger frame, then longer indexed footage, then the first held) - when that is the newcomer it replaces the held one in `sources_by_topic` and `fetched`, the held one becomes the alias (`kept_by: quality`), and the topic's count and pool depth hold one source, not two. Pool sources are checked the same way; a source an earlier pass handed in is never replaced. `shot_copy.py <a> <b>` / `shot_copy.py --topics <01b>` compares by hand.

## The source sieve: a source refused for what is in it (CF-0299, 2026-09-21)

**The order of this stage, since this task.** `ingest_batch.py` fetches and indexes -> **you describe every shot** -> `source_sieve.py` -> you report. The sieve is step 2 of three. Step 1 is Trend Hunter's, which picks candidates by title and channel and cannot see a frame; step 3 is the two-source floor below, which counts sources. Between them there was nothing, and batch `example-film/2026-09-21T0358Z` is what that costs:

- **`9a7i4LHHZNs`**, offered as the second source of a topic about the film *Delver*, is "Fred Perry's Animated Antarctic Press Universe Trailer" - a comic-universe reel with GD, Ninja High School and Dragon Arms title cards and not one frame of the film. It passed the floor here, cost 21 minutes of indexing and a whole description subagent, and was refused by the writer with `no_second_source` after the stage had been paid for.
- **`bYKJxZYd66o`**, Coach Hale's first source, is a vertical interview Short with a dating-app promo in it and captions across the **middle** of the frame. The frame judge rejected the finished render over six of them - after the script, the TTS and the render.

**Why you answer this and not a detector.** The measurement that looks like it should already know sits on every shot and says the opposite of the truth. Share of shots with `usable_cached.text_outside_crop > 0`, same pool: `JzA-WopbYnc` (real Coach Hale scenes, good) **0.60**, `bYKJxZYd66o` (the one that killed the render) **0.00**. The good source measures worse, because its subtitles are in the bottom band the 9:16 caption crop removes (CF-0275) and the interview's are where the crop never looks. You are reading every tile anyway; this is the one question only you can answer.

**What you put on every shot you describe.** Two booleans, beside `description`:

- **`burned_text`** - somebody else's text is burned into this shot and **will still be there after the 9:16 caption crop**: a caption or subtitle outside the bottom band, a title card, an end card, a screenshot of a website. `false` for a subtitle in the bottom band (the crop takes it off - that is what CF-0275 measured), `false` for a **studio's corner logo** (the user's decision, DoD item 2), and `false` for text that is part of the pictured world - a sign on a wall, a name embossed on a prop. Quote the text in the `description` when you set it: the refusal is built out of those sentences and is read with no other file open.
- **`on_topic`** - this shot pictures the topic's own work: its scenes, its people, its making. `false` for a shot of something else entirely - another film, a comic-universe trailer, an app's website.
- **`screen_recording`** (CF-0451, optional) - this shot is **a screen filmed from the room**, the cinema "экранка": the big screen seen from the stalls with the audience's heads across it, the dark auditorium around it, the screen's edge or its keystoned perspective, moiré, a phone pointed at a TV. `false` for the work's own image - including a scene the work *sets* in a cinema, a TV that is part of the pictured world in the work's own shot, a talk-show or awards audience, a concert's video wall. Put it on every shot when you can; absent, your sentence answers for you (`screen_recording.DESCRIPTION_RE` - "audience silhouettes watching a screen", "audience reaction", "filmed off the screen"), so **say it in the description** when you see it: that is how the pool as it stands is read, and how `L2NAh3CIdig` (the official *Endgame: Encore* trailer whose "AUDIENCE REACTION / OPENING NIGHT" shots 2-5 the user rejected vanguards-endgame-encore for, acceptance log `cam_rip_footage`) is caught - by the describer's own words, four shots of 38 and nothing else in the pool. **Not a refusal and not a price** until the user signs one (CF-0320): the sieve keeps the source and writes one `screen_recording` warning per kept source into `warnings[]` (the shots, how they were found, and cam words in the candidate's title - `camrip`, `HDCAM`, `audience reaction`, `filmed in the cinema` - if any), and the shot carries it in `usability.warn[]` at its old score. A signed `score.hard.screen_recording` row in `shared/gate-prices.json` makes the shot hard, a signed `score.screen_recording` a soft rule at its price - nothing in the code writes either row. **An own capture is exempt by its kind (CF-0567):** the shots of ExampleTech's own screen recording (`own_capture-<id>`) carry `source_kind: own_capture` and are never flagged, whatever you answer - describe the page as it is.

Both on **every** shot, `true` ones included. A source with the flags on some of its shots is **not judged at all** (`unsieved`), because the share is measured over every shot and a half-flagged index would read as whatever you happened to look at. `scripts/shot_schema.py <shots.json>` prints the coverage and refuses anything that is not a boolean.

**A supplement source is judged by its entity (CF-0344).** A source whose `fetched[]` record carries `supplement.entity` (the thin-pool supplement, CF-0338) was fetched *for* that entity - Sandra Birch's other film, a Tonight Show interview with Nora Kingsley - so it is another work by design, and you flag `on_topic` on it as honestly as anywhere else (`false` for a frame of The Lost Harbor). Add a third boolean on its shots: **`shows_entity`** - the entity is seen in this shot or named by it; `false` for a frame of the same film without them (Ocean's 8 with no Bullock in it). Name the entity in the `description` when it is there: without the flag, a description naming it (full name or a person's surname, as a word) is what the sieve reads. For such a source a shot counts off topic only when it is neither the topic's work nor shows the entity (and a shot that shows the entity is not charged `score.off_topic_shot` either); the 0.5 threshold and the whole-source rule are unchanged, and its record in `source_sieve.sources[]` says `judged_by: entity` and lists `off_topic_shots` - the shots without the entity. Ordinary sources: exactly as below.

**The rule the script executes.** A source is refused **whole** when a majority - more than **0.5** - of its shots carry `on_topic: false` (`source_foreign`: somebody else's film, the score model's hard `score.hard.foreign_work_footage`). **Since CF-0435 (grill of 2026-09-29, Q19 step 4, Q24) that is the only whole-source refusal.** A majority of `burned_text: true` (`source_burned_text` until then) keeps the source: its burned shots are listed on its record (`burned_text_shots`) and stay out **one by one** - the pool depth does not count them, the Editor does not cut them - until the grill "вшитый текст" decides which text can stay or be covered; its clean shots stay in the pool. In a kept source an `on_topic: false` shot is no longer lost either: it is a weak shot (`score.off_topic_shot`, see "Shot usability" below). Why a foreign film goes whole, never shot by shot: the floor counts sources, and a source that is three-quarters somebody else's film is not made usable by its good quarter - the anchors would land in the quarter and the render would show the rest. `on_topic` is asked first, so `9a7i4LHHZNs` is refused for being another work rather than for its title cards, which is the true answer about it. The threshold is read off the pool, not chosen: every source that had to go under CF-0299 measures **1.000** on one of the two shares, every source that has to stay **0.048** or below on both, and 0.5 is the middle of the empty band between them (the eight sources and their flags are in `tests/fixtures/cf0299_sieve_flags.json`).

**What it does to the batch.** A refused id leaves `fetched` and `sources_by_topic` and lands in `failed[]` with its code and `refused_at: "sieve"`, beside `index`. The report gains a `source_sieve` block - the thresholds, a record per source with both shares, `refused[]` and `unsieved[]` - and, since CF-0359, a `sieve_backfill` block: which of the batch's sources were answered for on the spot, by what answerer, and which could not be (`failed[]` there, with the sentence the refusal quotes). Both are written even when the sieve refused nothing, because "the sieve cleared this batch" and "nobody sieved it" must not read the same. Then the floor of CF-0129 is counted again on what survived, and a topic left short **takes its next candidate inside the same four-attempt cap**, counted across the batch and not per invocation: a candidate it already tried is never tried twice and a source the sieve took is never registered again.

**What you do.**

1. Describe every shot of every source, flags included.
2. `scripts/source_sieve.py <batch-dir>` - or `--dry-run` first if you want to read the verdicts before anything moves.
3. **A source it refused is gone. Do not argue with it by hand** and never edit `sources_by_topic` with a pen. If you believe it is wrong, say so in your report with the shot numbers: the thresholds are a measurement and are changed by a task, not by an invocation.
4. **A replacement it fetched has no descriptions yet.** `SIEVE <topic> ... takes its next candidate` on stdout means one more source to describe - describe it and run the sieve again. That loop ends when every source of every topic is `kept`.
5. A topic the sieve left with **no** kept source is in `skipped_topics[]` exactly like any other refusal of this stage, and the same rule applies: **it is not handed to Content Researcher**. A topic left with **one** kept source is settled by the floor's mode (CF-0419, below): under `warn` - the user's decision of 2026-09-28 - it stays in the batch with a `no_second_source` entry in `warnings[]`; only under `enforce` is it refused. Its slot, though, is refilled from the reserve in the same run (CF-0306 above) - a `RESERVE ...` line means one more topic in the batch, whose sources have no descriptions yet. Its `reason` names the source that was taken and what was seen in it; carry the count and the ids into your report and your `stage-done --note`.
6. Every id `source_sieve.py` names as `unsieved` is a description pass you have not finished. Finish it before you report - an unsieved source goes to the writer unjudged, which is the state this task exists to end. Since CF-0359 you will normally see none: the sieve answers the open flags of the batch's own sources first (`BACKFILL ...` / `SIEVE backfill (CF-0359) ...` on stdout) and takes out with a record the one it could not answer. Read those lines and carry them into your report - a source lost that way is a source lost, even though the run went on; and if you ran `--no-backfill`, the exit code is back to being yours to clear.

**A reused old source does not stop the stage (CF-0359, 2026-09-23).** CF-0355's exit code was right about the danger and wrong about the cost: a batch that takes an old pool source again - the same official trailer, indexed before CF-0299 - could not close the stage, and a run that cannot close waits for a human, which DoD 1 of milestone 1.4.5 forbids. The old pool is not being marked either: 2708 shots in 82 sources of dead topics, and after publication the sources are deleted anyway (CF-0358, the user's ruling of 2026-09-23). So the marking happens inside the sieve run and only over the sources that batch took, and the failure of the marking is a refusal with a record rather than a stop: no mp4 left to take frames from, an answerer that died or sat past its ceiling, answers that did not cover every shot - each takes that one source out of the batch (`sieve_backfill` block in the report, `failed[]` record with `index_failed` and `refused_at: sieve`) and the run carries on with the top-up and the floor mode settling the topic. The code is `index_failed` on purpose: since CF-0299 the two flags are part of a finished description pass, so an index that cannot be sieved is ours and unfinished, and the funnel already knows that word.

**The sieve's host-show guard (CF-0817).** A held source somebody already found to be another people's host show - its `fetched[]` record carries `host_show.refused` (the pool check's mark), or Trend Hunter's candidate record of the same id for the topic does (`footage_candidates_dropped` with `reason_code: host_show`) - is refused here without reading its shots: `source_sieve.sources[]` record with `verdict: refused`, `reason_code: host_show`, `signals` and the verdict under `host_show`, `judged_by: host_show`; it leaves `fetched` / `sources_by_topic` into `failed[]` (`reason_code: host_show`, `refused_at: sieve`) and the topic takes its next candidate like after any sieve refusal. Neither should happen any more (the pool check refuses first, Trend Hunter no longer offers one); this is the guard. A topic that loses **everything** to it is refused as `source_foreign` - `host_show` is a source's word, not one of `TOPIC_REFUSAL_CODES` or the funnel's. The block's `host_show` part says `refused` (here), `refused_at_pool` (from the `pool_sources` block) and `host_show_unknown` / `unknown` (held pool sources whose entry had no title or uploader).

## Two sources is a count, not a pool: the depth floor (CF-0304, 2026-09-21)

**A topic that holds its two canonical sources and a pool the Video Editor would throw away goes on taking candidates.** On `example-film/2026-09-21T0358Z` Harbourlights (`lf-2026-09-21-002`) came out of this stage with two sources and 117 indexed shots, Rennick (`lf-2026-09-21-005`) with two sources and 29 - both counted as done, both refused by Content Researcher with `pool_too_thin`, because once the Editor's own gates are applied those pools carry 14 and 16 distinct usable samples where a 45-60 s narration needs 4-5 anchors plus the CF-0274 margin of 12. Four and a half hours of indexing, a written scene and a production fact each, and **four untried candidates per topic** that were never downloaded because the count said "two, done".

- **The measure** is `pool_depth.py`: how many shots of the topic's pool survive `resolve_anchors.precut_refusal(..., need=None)` - the Video Editor's own pre-cut gate, imported from its scripts and never copied - for the cut questions (a valid `moment_at`, at least `MIN_CUT_SECONDS` of shot to cut) and the CF-0275 `text_cut_by_crop` veto. **Since CF-0435 the usability bundle is not a refusal here**: a shot is out only on a hard rule of `shot_usability.py` (black past the Editor's clip ceiling, no subject at all, `burned_text: true`); a shot under the framing/brightness/resolution floor or flagged `on_topic: false` is **weak** - kept in the pool at a price, but not part of the floor. A stale `measured_by` stamp is read as no measurement (flags only), as the Editor reads it. Every topic and source record carries three numbers, each with one reader:
  - **`usable_shots`** - CLEAN shots: no hard and no soft rule. The only number held against the floor (`deep_enough()`), and the one Content Researcher quotes against it. A pool deep only in weak shots still goes for its next candidate: the Editor *may* take a weak shot at a price when nothing better exists, and this stage never stops looking for the better one because of it. `usable_seconds` and `usable_cards` are over the clean shots too.
  - **`weak_shots`** - shots with soft violations only. In the pool, never in the floor.
  - **`available_shots`** = `usable_shots + weak_shots` - everything the Editor can put on screen at all. What the writer/resolver reads as "how much material is there on this topic", so a pool thin on clean shots but holding weak ones is not mistaken for an empty one.
  - A burned-text shot is in none of the three. The `DEPTH` line shows `(+N weak, M available, CF-0435)` when there are weak shots.
- **The floor is 60 usable (clean) shots** (`POOL_DEPTH_FLOOR`, `--pool-depth-floor`). Over the seven live `example-film` batches (measured before CF-0435, when the count was the Editor's pre-cut gate alone and burned-text shots still counted), the topics that reached a finished video measure 61, 83, 96, 106, 110, 141; the topics refused for pool depth measure 7, 23, 27, 34, 36, 59. Nothing lies between, and every other candidate measure overlaps on the same topics (usable seconds: thinnest video 289.3 against deepest refusal 503.4; usable non-card shots: 55 against 57). It is a measurement, changed by a task - do not move it by hand to get a topic through.
- **It is never a refusal here.** The count is an *upper bound* on the distinct usable samples the writer measures against real anchors - it cannot see the similarity floor, because before a script there are no phrases to score against - and on this batch that bound was loose by 2.6x (Harbourlights 36 -> 14). So `pool_too_thin` stays with the stage that has the anchors. A topic that never reaches the floor goes to Content Researcher exactly as it would have.
- **Since CF-0435 the replay numbers moved, and the walk takes more, never less.** On the same batch today: Harbourlights 30 clean + 77 weak (107 available) - under the floor, takes its third candidate as before; Rennick 5 clean (its 15 title cards are `burned_text`) - takes a third and a fourth; Coach Hale 51 clean (`bYKJxZYd66o` is a captioned 608 px portrait source, 43 of 45 shots burned) - takes a third where it used to stop at two; `9a7i4LHHZNs`, the source the writer called useless, 0 clean and 38 weak. That is the sieve's own rule: a topic thinned by burned shots is re-walked for depth.
- **What you see:** `DEPTH <topic_id> 30 usable shot(s) of 117 over 2 source(s) (+77 weak, 107 available, CF-0435), 57s, floor is 60` while the walk takes another candidate, and `DEPTH <topic_id> keeps a thin pool: ... - it is NOT refused here` once it runs out. The report gains a **`pool_depth`** block, always written: `floor`, `measure`, `topics[]` (one per topic, with `usable_shots`, `weak_shots`, `available_shots`, `usable_seconds`, `per_source[]` and `exhausted`), `thin[]` (at the source floor, under the depth floor, nothing left to try) and `unmeasured[]` (the depth could not be computed and the walk stopped at the source floor, as before CF-0304).
- **The cost is bounded by what already bounded it**: the CF-0129 four-attempt cap, the CF-0302 duration ceiling and the candidate list. A third source costs about 14 min of this stage (median pool source 139 s at the batch's measured ~6.0 min of indexing per minute of source).
- `source_sieve.py` settles its top-up against the same floor: a source taken out is a pool made shallower, and a topic left with its two sources and a thin pool takes its next candidate too.
- **A burned-text topic is walked once, and only while the batch works on it (CF-0456).** Before this task every run of the sieve re-walked every topic whose burned shots left it under the floor - the counts were on the records, "already walked" was nowhere - and on the 2026-09-30T1248Z repeat that re-downloaded NvKt1-z08do for `lf-2026-09-27-001` until the step's 30-minute ceiling killed the run; that topic had been lost at `scripts` and replaced from the reserve hours before. Now: (1) every burned topic the sieve decides gets a mark in `source_sieve.burned_settled` - `outcome` (`walked`, `deep_enough`, or `walk_started`, written into `01b` on disk **before** the download so a run killed inside the walk does not repeat it) and the burned-shot count per source. The next run prints `SIEVE <topic> was walked ... settled, not walked again` and leaves it; only a source that gained burned shots since (a new source described) makes it walk once more, inside the same attempt cap. `--no-top-up` marks nothing. (2) A topic the batch no longer works on - `reserve_substitution.substitutions[].replaced` in `01b`, or `skipped[]` of `03-content-researcher.json` - is never walked: `SIEVE <topic> is no longer worked on by this batch (...) - not topped up`; a source the sieve refuses there still leaves the counts, with no top-up and no new refusal record. (3) `--only-topics t1,t2` judges, answers and walks only the named topics; every other topic's records in `source_sieve` are carried over from the last run as they were.

**Carry `pool_depth.thin[]` into your report and your `stage-done --note`.** It is the one thing that says "the writer is about to refuse this topic for the pool, not for the writing" while there is still a batch to do something about it.

## What the pool already holds is counted first (CF-0325, 2026-09-29)

**A topic starts its walk holding the pool sources Trend Hunter matched to it, once they are shown to be its work.** Trend Hunter writes `topics[].pool` (CF-0325 part 1, `agents/trend-hunter/scripts/pool_coverage.py`): the sources in `shared/footage/index.json` whose title names the topic, or that were fetched for an earlier topic of the same name. Until this task the indexer never read it and fetched every topic from scratch - Wren Hollow was refused `pool_too_thin` twice with 195 and 215 usable shots of the franchise in the pool.

- **The checks, in order**, each one a reason written down when it refuses: `media` - the `.mp4` and the finished `.shots.json` are still in the cache (the pool is transient, CF-0358; `pool_media_gone`); `work` - Trend Hunter's own candidate checks run in its own process (`pool_work_check.py`): CF-0272 `wrong_work` (the title names no form of the work - a Harbourlights preview for Wren Hollow), CF-0309 `not_the_works_footage`, CF-0297 `unofficial_source` (a fan-made concept trailer for Silent Tide), and `other_installment` - the title names the work only by its franchise stem or `parent_work`, never by the full name or the subtitle (an Vanguards: Endgame trailer for Vanguards: Doomsday, the judge's `wrong_work_footage` on batch 2026-09-29T0705Z) - the same rule as Trend Hunter's candidate sieve, asked of its `topic_relevance.installment_forms` (CF-0444; a name with nothing left after the franchise is not a reason to refuse); `sieve` - the CF-0299 verdict over the source's own flags. A source nobody could check (`pool_not_checked`: no Trend Hunter checkout, a crashed check) is **never counted**. A source not yet sieved is counted and answered by `source_sieve.py`'s backfill like any other source of the batch.
- **Somebody else's host show is not reused (CF-0817, 2026-10-20).** A viewer wrote "Stop stealing content" under the Reel vanguards-doomsday, and the user ruled: other people's podcast, interview and talk-show hosts are not backdrop under our voice. The audit (CF-0818) found the sources came in **through this pool reuse** - the Fallon interview `ZLXL1L0TfsI` (Tom Carver) counted for Delver, Zenith's own "Countdown to Vanguards: Doomsday Official Podcast" `nSWnovHSDaY` / `xe3qx0kXArA` for Vanguards: Doomsday - because the checks above ask only "is it the work". So `pool_work_check.py` asks one more question of every source the work check lets through: Trend Hunter's own `host_show.judge()` (`agents/trend-hunter/scripts/host_show.py`, its lists in `agents/trend-hunter/config/host_show.json` - read there, never copied here) over the pool entry's title and uploader, with the channel's official list for `official` (an official channel does **not** exempt a podcast) and the topic's `title_ref` for the two exceptions: the topic is about the person the title names (`subject_is_guest`), or the topic is the show (`topic_is_the_show`). A host show is refused with `reason_code: host_show`, `check: host_show`, Trend Hunter's verdict with its `signals` on the record, and barred from the walk. Trend Hunter's own verdict on the same id (a candidate it dropped with `host_show`, it saw the nature the pool does not keep) refuses too. A verdict with no host-show answer is `pool_not_checked`; a Trend Hunter checkout without the classifier is an `error` naming CF-0817 and the `POOL host-show check unavailable` line - **nothing is counted**, never a quiet pass. A pool entry with no title or uploader the lists cannot call a host show is counted as before and marked `host_show_unknown` (the fields it lacked; per topic and in total in the `pool_sources` block, carried onto its `fetched[]` record). The stage prints `N pool source(s) refused as somebody else's host show (CF-0817), M counted with no title or uploader to judge`. Replayed over the production batches on 2026-10-20 (read-only): 31 of 150 `from_pool` admissions in 11 batches would now be refused - `ZLXL1L0TfsI` x10, `xe3qx0kXArA` x7, `nSWnovHSDaY` x6, Sam Meadows / Dana Reyes `d7b1ilF5290` x4 (WNL), Fallon / Florence Pugh `gfaACr_Adbc` x4 (Spire-Runner: Fresh Dawn); 5 of 251 pool entries lack a title or uploader (3 of them own captures).
- **What a counted source does:** it is registered before the walk, deduped against the topic's other pool sources by the CF-0080 fingerprint, and goes into `fetched[]` with `from_pool: true` and into `sources_by_topic` - so the two-source floor and the CF-0304 depth floor count it and the walk downloads only what is missing. It is not fetched or indexed again. A pool id that is also a candidate is not walked a second time and costs no attempt.
- **What a refused source does:** it is not counted, and when the refusal is about the video (every code but `pool_media_gone` / `pool_not_checked`) it is also put into the topic's `tried` for free, so the walk does not admit through the candidate list what the check refused.
- **What you see:** `POOL <topic_id> counts N pool source(s) before any download: ...`, one `POOL <id> not counted for <topic> (<code>, <check>): <reason>` per refusal, and in `01b-footage-index.json` a **`pool_sources`** block - per topic `matched`, `counted` and every source with its `outcome` (`counted` / `refused` / `aliased` / `not_walked`), `check`, `reason_code` and `reason`. Carry the refusals into your report: a refused pool source is the pool's title match being wrong, which Trend Hunter's ranking still counted.
- **Not in `--reserve-for` / `--supplement`:** a reserve substitute and a supplement are walked from their candidates as before.
- **Measured** (`pool_sources_replay.py`, 2026-09-29, over part 1's 15 frozen pool losses): the check refused 21 matched sources (11 `wrong_work`, 4 `not_the_works_footage`, 4 `source_burned_text` - counted since CF-0435, which keeps a burned-text source -, 2 `unofficial_source`; `other_installment` has no case among these 15 - its case is the Doomsday batch of 2026-09-29) and the rest would have closed **8 of 15** losses before a download - Wren Hollow x2, Harbourlights x2, Rennick x3, Delver (2026-09-21T1541Z). Two honest caveats: almost none of the old pool carries sieve flags yet, so all 8 rest on the batch's own sieve backfill clearing them (0 of 15 on already-cleared sources alone), and the three Rennick closures lean on `wS6wtevVlmc`, which CF-0299 measured as another film (`tests/fixtures/cf0299_sieve_flags.json`) - the backfill would refuse it and the walk would fetch the second source. The realistic count is **5 of 15**.

## Two canonical sources per topic; one is a warning, not a refusal (CF-0129, CF-0419)

**The floor's mode (CF-0419, the user, 2026-09-28): `warn`.** The rule is `footage_indexer.no_second_source`, and its switch is where `runlog triage` reads every rule's mode - `channels/<channel>.json` -> `footage_indexer.no_second_source` (a string, or `{"mode": ..., "note": ...}`). `warn` / `measure` / `off` keep a topic that holds **one** canonical source in the batch with a `warnings[]` entry (`warning_code: no_second_source`, `rule: footage_indexer.no_second_source`, `severity: warn`, the counts in `numbers`); `enforce` / `fail` / `refuse` refuse it as described below. Precedence: the run's `--no-second-source` flag (`--two-source-gate` is its CF-0362 spelling), then that key, then the Editor's `video_editor.two_source_gate` for a channel that never set the key (CF-0362), then `warn`. A typo is silence and falls through - never a refusal. `two_source_floor` in `01b` records `rule`, `mode`, `mode_from`, `refused` and `warned`, and stdout says `N topic(s) short of a second source kept with a warning (...)`. Before this the switch did not exist at that path, so the triage called the rule `hard-wired` and filed `unpriced_refusal:footage_indexer.no_second_source` on every batch (CF-0408) while the stage, under `measure`, had refused nothing. A topic with **no** source is refused in every mode - there is nothing to cut.

**Carry the warned topics into your report and your `stage-done --note`** (the ids and their source counts): a one-source topic is a video the Content Researcher and the Editor will make on one source, and the Editor's own `two_source_gate` decides what happens to it there.

What follows is the walk, which is unchanged - it still aims for two sources - and the refusal, which now happens only under `enforce`.

The two-source gate lives in the Video Editor and is now on `enforce`, so a topic that ends up with one source is a video that is refused **after** a script, a TTS pass and an anchor resolve have been spent on it. The measurement that settled it (CF-0118, 2026-09-07): 5 of 13 videos with footage passed the gate, and in batch 2026-09-03T2037Z **0 of 4** - because each topic's "three sources" were three re-uploads of one teaser, which the fingerprint above collapses into one. Independence is by that fingerprint, never by `video_id`.

**Since CF-0299 the floor counts only sources that got through the sieve above.** `ingest_batch.py` counts the files it fetched, which is all it can know at the time - the descriptions the sieve reads do not exist yet. `source_sieve.py` counts again afterwards, on what survived, and that second count is the one the writer meets. So a topic can be refused *after* the indexing, and a topic can take a further candidate after it: the cap below is spent across the whole batch, not per pass.

So `ingest_batch.py` does not take the first N ids of a topic. It walks `evidence.youtube_video_ids` **in order** - Trend Hunter orders them round-robin by nature of footage since 2026-09-16, so the first two are the likeliest independent pair - and stops as soon as the topic holds `SOURCES_WANTED = 2` canonical sources after dedup. A candidate that turns out to be a re-upload costs an attempt, does not count, and the walk goes on to the next one. A candidate whose index did not finish (CF-0281, above) is the same: it costs its attempt, does not count, and the walk goes on. The ceiling is `MAX_ATTEMPTS_PER_TOPIC = 4`.

**An attempt is one distinct candidate video.**

A `same_cut` re-upload from `evidence.footage_candidates` is a stand-in for a candidate **that is not there at all** (a real per-video failure), taking its place in the queue for one attempt. It is never a second source - it is the same cut, and the dedup would collapse it.

**The refusal (under `enforce` only).** A topic still below the floor at the end of the stage goes into `skipped_topics[]` of `01b-footage-index.json`, in the CF-0232 funnel's shape, with a `FLOOR <topic_id> refused: ...` line on stdout for the RUN_LOG:

```json
{"topic_id": "003", "reason_code": "no_second_source", "stage": "footage-indexer",
 "reason": "1 canonical source(s) after CF-0080 dedup, floor is 2 (CF-0129); 3 of 4 candidate(s) tried; 2 were re-uploads of sources it already had (t2, t3); ...",
 "wanted": 2, "sources": ["t1"], "attempts": 3, "candidates": ["t1", "t2", "t3", "iv"],
 "tried": ["t1", "t2", "t3"], "unused": ["iv"], "aliased": ["t2", "t3"], "failed": [],
 "index_failed": [], "candidate_shortfall": null}
```

The funnel copies `reason` into its `detail` verbatim, so that sentence is written to be read on its own, and the step it explains is `two_sources` - the one that has to say why a topic never reached `scripts`. `reason_code` is `no_second_source` when the topic holds at least one source, which is what the floor is about; a topic that got **nothing** takes the code that says what actually happened instead - `fetch_failed` or `index_failed` when its candidates were tried and lost, `no_source` when there was nothing to try - so the record and the funnel's own count of `sources_by_topic` never contradict each other. `failed` and `index_failed` are the two ways a candidate was lost, kept apart (CF-0281), and the code follows the whole of the topic's loss: `index_failed` when **every** candidate came down and could not be indexed - our failure, fixed here - and `fetch_failed` as soon as one of them was a download YouTube refused, so a mixed loss is never rounded down to our half of it. The funnel knows both words (`shared/runlog/funnel.py` `FUNNEL_CODES`) and its `two_sources` step splits the same `failed[]` by `reason_code` the same way. Whichever code wins, the `reason` sentence names every fault that happened. `two_source_floor` in the same report carries the two numbers and the list of refused topics.

**What this means for you.** A topic in `skipped_topics[]` is **not handed to Content Researcher** - not as a thin topic, not "with a note". Under `warn` a one-source topic is not in `skipped_topics[]` at all: it is in `sources_by_topic` and in `warnings[]`, and it goes on. Its single source stays indexed and in the cache (it is real footage, and the next batch may use it), and the topic itself is a loss this stage has already explained. Tell the user the count and the ids in your report and in `stage-done --note`; a batch that loses several topics this way is a Trend Hunter pool problem (`evidence.footage_candidate_shortfall` usually says so already, and the refusal quotes it), not something to fix by lowering the floor.

Batches written before 2026-09-16 have no `footage_candidates` or `footage_candidate_shortfall`: that is "nothing was said about the candidates", not "there are none". Their ids are walked exactly as they are - and a topic that carries only one id is refused, which is the true answer about it, not a regression.

## A topic kept on own graphics passes the floor (CF-0689, 2026-10-12)

ExampleTech's base footage is the graphics the Video Editor draws from the script's facts at the edit (the `own_graphic` origin of `channels/example-tech/footage-origin.json`, the root's `shared/own_graphic.py`): never fetched, never in the pool, never indexed here. Trend Hunter keeps such a channel's topic with 0-1 footage candidates when its support text holds enough quotable facts, and says so in `evidence.own_graphic_footing` (`origin`, `quotable_facts`, `floor`, `meets_floor`, ...); its `evidence.youtube_video_ids` may be empty.

The floor above would refuse that topic - `no_source` with nothing to try, `no_second_source` with one source, `fetch_failed` / `index_failed` / a sieve code when what it had was lost - before Content Researcher, who writes it an all-graphic script, ever saw it. So the floor lets it through, **only when both hold**: the channel's footage-origin.json names an origin under the `own_graphic` licence (`source_rights.own_graphic_origin`), and the topic's `own_graphic_footing.meets_floor` is `true`. Then, in any floor mode (`warn` and `enforce` alike):

- the topic is not in `skipped_topics[]` and gets no `no_second_source` / `pool_too_thin` warning;
- `01b-footage-index.json` -> `own_graphic_footing` carries `origin`, `eligible` (every topic whose footing is met) and `kept[]` - one `{topic_id, note: "kept on own graphics", origin, sources, quotable_facts, floor, detail, refusal_it_replaces: {reason_code, reason}}` per topic the floor would have refused; `two_source_floor.kept_on_own_graphics` lists their ids;
- stdout says `OWN GRAPHICS <topic_id> kept: ...` per topic and one summary line (`ingest_batch.py` and `source_sieve.py`) - carry it into `stage-done --note`;
- a reserve substitute kept this way holds its slot (the reserve does not offer it to the next topic). Whatever a pool source of the topic lost is still in `failed[]` as before.

A Tech topic without `meets_floor`, and every ExampleFilm and ExampleScience topic (no `own_graphic` origin, whatever a topic's footing says), is floored exactly as described above. Tests: `tests/test_own_graphic_floor.py`.

## Writing anchor phrases - the thing that decides whether this works

**Describe the frame, not the concept.** This is the whole skill.

Measured on the same shot of a lakeside deck:

| phrase | score |
|---|---|
| "a wooden cottage house by a lake" | 0.188 - not found |
| "two people sitting on a deck overlooking a lake with trees" | 0.264 - found |

The scene is "the cottage" and a person would call it that, but no house appears in frame - two people sit on a deck with water behind them. CLIP answered correctly both times. When a phrase comes back unmatched, suspect the phrase before you suspect the footage.

Anchors only work for **things that can be photographed**. "The rivalry was never the point" has no picture; do not write an anchor for it.

## Scores

They are relative, not absolute. CLIP always ranks something first, even when nothing depicts the phrase. `--min-score` (default 0.22) is what converts a weak best match into an honest "no footage for this", which the caller records rather than papers over. Observed: a solid match sits around 0.26-0.32, a real miss around 0.18-0.20. The gap is narrow - treat a score near the threshold as a question, not an answer.

## Descriptions

`index_footage.py` leaves `description` empty on purpose: an unwritten description is visibly missing, a guessed one is not. Read the contact sheet and fill them in - Content Researcher needs plain language, not vectors, to write to the footage.

**Every shot you describe also gets `burned_text` and `on_topic` (CF-0299).** They are two booleans beside the description, `on_topic` decides whether the whole source stays in the batch (a majority of `false` is somebody else's film) and, on a kept source, which shots are charged `score.off_topic_shot`; `burned_text: true` keeps that one shot out (CF-0435); the rule for each is in "The source sieve" above - read it before you dispatch the subagents, and put it in their instructions. The flags are not optional and not "when it seems relevant": a source flagged on some of its shots is not judged at all. Quote the burned-in text in the description when you set `burned_text: true`; the source's record quotes those sentences, and the grill "вшитый текст" will read them.

**An answered flag is the describer's, and you never flip an answered flag by hand (CF-0713).** Not with Edit, not with `jq` or a Python one-liner over `shots.json`, and never because of what the sieve would do to the source: batch 2001Z flipped nine `on_topic: false` shots to `true` so that three interview sources would not be refused, and only its last message said so. If you are sure from the frame that a describer's answer is wrong, change it through `sieve_flag_override.py` with the reason (what the frame shows) - the override is allowed and costs nothing, it only may not be silent - and run `source_sieve.py` again. A source that still goes is a refusal doing its job; say so in the report.

**The tile is not the head.** Each contact-sheet tile is the shot's *midpoint* frame, and `tile_at` on the shot says exactly which second that is. Video Editor cuts a clip from the shot's `start` unless told otherwise - so for a 20-second shot you are describing second 10 and the render will show second 0 (CF-0081: this is how a described card never reached the screen). CF-0105 splits shots whose picture actually changes, so for most shots head and tile look alike and there is nothing to do. When they do not - the thing you describe appears some seconds in, you pulled a frame by timecode to see it, or the tile shows a card that the head of the same shot does not - write the timecode of that moment into the shot's `moment_at` (absolute seconds in the source, same unit as `start`/`end`, and inside them). Video Editor then builds the clip window around that mark instead of from the head (CF-0106). Rules:

- `moment_at` is the describer's mark, never the indexer's: set it only when you know the described moment is not the head. Do not copy `tile_at` into it as a habit - that moves every cut to the middle of its shot for nothing.
- Leave it out (or `null`) for the ordinary case; absent means "cut from the head", exactly as before. Every index written before this field existed is valid as it is.
- It must lie within the shot's own `[start, end]`. `scripts/shot_schema.py <shots.json>` checks an index you just edited; `match_anchors.py` refuses a bad mark with the shot named, before anything is cut.

## Shot usability: a score, not a refusal (CF-0435)

Up to CF-0435 the usability bundle was a gate: a shot under a floor was thrown away before any script (batch `0929Z`: 699 raw shots, 541 after the sieve, **294** after the bundle - 42 % reached the writer). Since the grill of 2026-09-29 (Q19 step 4) it is a score: a weak shot stays in the pool, the Editor ranks by the score and takes the best shot it has, and the video pays the score model (CF-0432, `shared/gate-prices.json`) for every weak shot that reaches the screen. `scripts/shot_usability.py` is the one place the rules live; every shot of an index written through `shot_schema.write_index()` (new material, and any index a batch rewrites) and every shot of the kept sources the sieve stamps carries the record:

```json
"usability": {
  "task": "CF-0435", "score": 0.97, "penalty": 3,
  "soft": [{"rule": "low_framing", "price_key": "score.low_framing", "price": 3, "value": 0.52, "floor": 0.65}],
  "hard": [],
  "measured": true, "measured_by": "<usable_cached.measured_by>"
}
```

- **soft** (in the pool, at a cost; `rule` = the score model's key without `score.`): `low_framing` (`roi_coverage` < 0.65), `low_brightness` (`mean_luma` < 28, a lit title card excused as `qc_asset` excuses it), `low_resolution` (short side < 720), `off_topic_shot` (`on_topic: false` and the shot does not show a supplement's entity).
- **hard** (out, shot by shot): `black_frame` (`black_fraction` > 0.90 - the Editor's own ceiling for a clip, `MAX_BLACK_CLIPS`; not qc_asset's 0.35 for a still, which a fade or a night scene crosses), `empty_frame` (`roi_source: none` - nothing on screen to look at), `burned_text` (`price_key` `score.hard.foreign_text`, until the grill "вшитый текст").
- **warn** (CF-0451; in the pool, no cost): `screen_recording` - the shot is a screen filmed from the room (the describer's flag, else its sentence), `signed: false`, `by: flag|description`. It moves to **hard** on a signed `score.hard.screen_recording` row, to **soft** at the row's price on a signed `score.screen_recording` row (`screen_recording.mode()`); `summary()` counts it as `warned` and in `by_rule`.
- **warn** (CF-0452; in the pool, no cost): `low_sharpness` - the shot is smeared: its **`sharpness_cached.value`** under `sharpness.MIN_SHARPNESS` (0.57), `signed: false`, `proposed_price: 3`. A soft clip whose frames move (`motion_excused`, motion blur the eye follows) is not warned. It moves to **soft** at the row's price on a signed `score.low_sharpness` row (`sharpness.mode()`); nothing in the code writes that row. The record also carries `sharpness` (the value, or `null` unmeasured) - a ranking key between otherwise equal shots.
- **In the pool depth** (`pool_depth.py`, section "Two sources is a count, not a pool" above) a weak shot is `weak_shots` and `available_shots`, never `usable_shots`: the floor that fetches another source reads clean shots only.
- `score` = `1 - penalty/100` with the table's prices (the draft prices when the file cannot be read), 0.0 on any hard rule - a ranking key between shots, not the video's score.
- **Nothing is re-measured** (CF-0410, the pool is transient). A shot of the old pool without the field is judged on the fly by `shot_usability.of(shot)` from what it already stores; a shot with no `usable_cached` is judged on its flags alone (`measured: false`). Never run `remeasure_usability.py` over the pool to get the field.
- The floors are copies of the Editor's constants (`common.MIN_COVERAGE`, `common.MIN_SHORT_SIDE`, `qc_asset.MIN_MEAN_LUMA`, `qc_asset.MIN_CARD_INK_FRACTION`, `resolve_anchors.MAX_BLACK_CLIPS`); `tests/test_shot_usability.py` fails when one moves there.

## Sharpness: measured on new material and on the fly, never over the pool (CF-0452, 2026-10-01)

The user rejected kaijura-minus-zero (1248Z, `blurry_footage`: "много смазанного материала"); the usability bundle measured no focus. `scripts/sharpness.py` does:

- **The measure.** A few frames of the span, grey, at the source's own resolution with the short side capped at 1080 (a 720p source is not blown up - `low_resolution` charges that), letterbox trimmed, cut into tiles; on each tile with detail the blur effect of Crete et al. (how much pixel-to-pixel variation a re-blur still takes away; the smaller of the vertical and horizontal readings, so a one-way smear counts). A frame reads the 90th percentile of its tiles - the sharpest part, so a subject in focus before a blurred background (the shallow focus of wolfhame) reads sharp. Scale 0 (mush) .. ~0.9 (a crisp graphic); footage sits 0.45-0.85. Each sample is read with its next frame: `motion` (mean grey difference) over `MOTION_EXCUSED` (6) marks a moving picture.
- **The field.** `shot["sharpness_cached"] = {"task": "CF-0452", "measured_by": sharpness.MEASURED_BY, "value": <median frame>, "best": <sharpest sample>, "best_at": <its time, s>, "motion", "motion_excused", "frames": [[t, sharpness, motion], ...], "floor": 0.57}`. A field of its own, **not** a key of `usable_cached` (whose stamp is the bytes of `usability_probe.py`, CF-0048 - touching it would stale the whole pool). A record of another `MEASURED_BY` is not read.
- **Who measures.** `index_footage.py` stamps every shot of new material (3 frames a shot, one ffmpeg). The old pool is **not** re-measured - a shot without the field is simply not judged on this rule. A shot that reaches a plan is measured on the fly by whoever needs it: `sharpness.measure(video, start, end)` for a clip's span, `sharpness.at(video, t)` for the one frame a held still shows (never motion-excused: a held frame does not move), `sharpness.of_shot(shot, video)` / `sharpness.stamp(shot, video)` over the shot's own span, `sharpness.verdict(rec, held=...)` for the rule. `best_at` is the sharpest sampled moment - the frame to hold when the shot is held.
- **The floor** is read off the accepted side: the 5th percentile of the on-screen readings of 70 distinct shots of seven accepted videos (0.568; `tests/fixtures/cf0452_sharpness.json` holds them and the test holds the constant to them). Under it: 4 of those 70, and 2 of the 13 shots of kaijura (`xiEmt197Bk8:41`, held at 0.509 mid-motion, and `:44`). **It finds the tail, not the video**: kaijura's other held frames (0.58-0.74) sit inside the accepted range, and the rendered kaijura (median 0.57) is about as sharp as the accepted harbourlights and vanguards-endgame (0.59).
- **Price: none until the user signs one (CF-0320)** - a warning in `usability.warn[]`, see "Shot usability" above.

## The cached measurements go stale, visibly (CF-0048)

`shots.json` carries two measurements taken once at index time instead of once
per candidate (CF-0029): `usable_cached` (resolution/subject/darkness) and
`crop_bottom_cached` (burned-in subtitles). Raw numbers, not verdicts - moving a
*threshold* needs no re-index. But a raw number is the output of code, and the
code moves: the whole pool was measured on 2026-09-01 at 01:01-01:49 and
CF-0004 changed how animated frames are framed at 08:57 the same morning, after
which the pipeline was skipping good shots - mostly title cards - on numbers it
would no longer produce.

So `usable_cached` now records `measured_by`, a fingerprint of the measuring
code. `resolve_anchors.py` ignores a cache it did not make and checks those
candidates for real (slower, never wrong), and says so on stderr. That is the
whole answer for the pool: it is transient (CF-0358 - sources are deleted after
publication, the old pool is not processed in bulk), so a stale usability stamp
on it is **not remeasured** (CF-0410). `tests/test_usability_cache_freshness.py`
fails only on the sources of the current batch (`$RUNLOG_BATCH/01b-footage-
index.json` -> `fetched`) and prints the rest of the pool as one line,
`usability: stale, not remeasured - ...`; if a remeasure is wanted at all, it is
those batch sources by name, never `shared/footage/*.shots.json` (~2.3 s a shot,
hours for the pool - run 2026-09-27T0929Z lost one to it).

`crop_bottom_cached` carries the same kind of stamp (CF-0055), in a sibling key
`crop_bottom_measured_by`, over its own list of files - the caption detector
ages independently of the usability path, and a change to one must not
invalidate the other. What is different is what happens on a mismatch. This
number is handed to `prepare_clip.py --crop-bottom` and decides the geometry of
a real clip, so there is no cheap honest fallback: measuring fresh per candidate
was measured at 3.19s -> 13.32s per cut (+8-17 min per video), which is the
saving CF-0029 exists for. So a mismatch **stops the run** instead - the refusal
fires in `match_anchors.py`, before a single clip is cut, and names the command
that clears it. A shot with no cached crop at all is not a mismatch: `cut()`
sends those to a fresh `--auto-crop`, which is always correct.

**The pool is never re-measured in bulk (CF-0819).** Tech 2026-10-20T0831Z made
0 videos: a neutral edit nobody had paired (CF-0815's `errors="replace"` on
ffprobe's text) moved the key, every crop read stale, and pool-maintenance
re-measured the whole pool for 2 h until its ceiling failed the batch. A
stale crop is now cleared in one of two ways, neither of them a bulk measure:

- **Pair the edit** when it cannot move a number: an entry in
  `caption_cache.NEUTRAL_EDITS` naming the commit, its kind
  (`device-pin`, `decode-replace`) and why, proven over git by
  `tests/test_caption_cache_freshness.py`. The pool reads current again with
  nothing written.
- **Set it aside**: `caption_cache.py --set-aside-stale <shots.json> ...` moves
  the stale value and its stamp into `crop_bottom_set_aside` and the shot reads
  as "no cached crop" - a fresh `--auto-crop` at cut time, ~10 s per candidate
  the batch actually cuts. `caption_cache.py --restore-set-aside` puts them
  back once a pair proven later names their code again.
  `remeasure_captions.py --stale-only --budget-seconds S --set-aside-rest`
  re-measures what fits in `S` seconds and sets the rest aside, exit 0, with a
  `WARNING caption-band cache: ...` line on stderr and
  `caption_set_aside`/`caption_over_budget` on its journal event.

## What the 9:16 crop does to somebody else's text (CF-0275)

A split-screen is the commonest shape of commentary footage: the host in the
right half of a 16:9 frame, an article or a phone screenshot in the left. The
`cover` crop keeps a 608-px strip centred on the host's face, so the article is
not removed - it is sliced down its middle, and the montage shows half-words
under our own captions. Nothing in `usable_cached` could see that:
`roi_coverage` is high *because* the face survives, which is the point.

So `usable_cached` also carries, from one accurate-mode Vision scan of the
whole frame, what the delivered 9:16 window does to the text on it:
`text_regions` (how many Vision found), `text_area` (their area as a fraction
of the frame), `text_outside_crop` (the share of that area the window does not
show), `text_cut_by_crop` (the share of regions the window's edge runs through)
and `text_cut_area` (those severed regions as a fraction of the frame).

Three things to know when reading them:

- **`text_cut_area`, not `text_cut_by_crop`, is the comparable number.** A
  share of a count is meaningless at the counts Vision returns - an ordinary
  talking head whose one recognised region is the channel's own SUBSCRIBE
  banner scores 1.0.
- **`text_regions: 0` with the rest null** means "measured, no text on this
  frame". The keys being *absent* means the index predates CF-0275 and never
  asked - opposite answers, told apart by the key's presence, the same rule
  `card_ink_fraction` follows.
- **The window is `cover`, always.** A card is delivered `contain`
  (`common.delivery_fit`), i.e. whole, so nothing of it is cut and these
  numbers do not describe it. A reader has to drop `is_card` shots before
  applying any threshold.

## Check the pool's freshness before the batch, not inside it: `pool-maintenance` checks, this stage guards (CF-0151, CF-0173)

**The check of the whole pool is the run plan's stage `pool-maintenance`, not
this one.** The executor runs it with the batch open and before the first
agent stage (`python3 shared/run_plan.py show <channel>` in the factory root
says where): `shared/run_checks.py captions-stale` - this repository's
`caption_cache.survey()` as an exit code, under this repository's interpreter -
over `shared/footage/*.shots.json`; on exit 1 the plan's handler
`pool-remeasure-captions` re-takes the stale crops
(`run_checks.py captions-remeasure`, i.e. `remeasure_captions.py` over the
stale indexes) and the check runs again. Since CF-0819 that call is meant to
carry `--stale-only --budget-seconds <minutes> --set-aside-rest`, so a moved
key costs minutes and a warning, never the batch (the root half is the
factory's `shared/run_checks.py`). Then
`tests/test_usability_cache_freshness.py`: a stale usability pool closes the
stage with the note "usability: stale, not remeasured" and is never
re-measured (CF-0410). That work is accounted under its own
`pool-maintenance` markers, never `footage-indexer`: the repair walks the
whole pool, does not depend on this batch's topics, and billed to this stage
it would add its time to `indexer_s` in the runs table and make every run
before a repair look faster than every run after it, for no reason anyone
could see. The full rule is in the factory's `docs/run-accounting.md`,
section "`pool-maintenance` — the work before the first stage".

**What stays here is a guard, the first step of the stage `footage-indexer`,
before anything is fetched or indexed:**

```
scripts/caption_cache.py ../../shared/footage/*.shots.json
```

1.3 s over the whole 47-source pool (measured 2026-09-14). It prints either
"every cached caption crop is current" or the refusal, with the exact
`remeasure_captions.py` line that clears it. Normally it says current -
`pool-maintenance` has just made it so - and the guard costs nothing.

It is kept because of *what* ages this cache. A stamp is `digest()` over the
bytes of the seven files that make the measurement, and **five of them live in
`agents/video-editor/scripts/`** - `detect_text_band.py`, `vision_client.py`,
`vision_worker.py`, `common.py`, `repo_paths.py`. Nothing in this repository
has to change for this repository's whole pool to go stale; somebody else's
commit to a probe helper, or to run accounting, does it - and such a commit
can land between `pool-maintenance` and this stage. It does not age with time
and it does not age gradually: on 2026-09-08 all 980 cached shots in the pool
carried one single old stamp, because one change had invalidated every one of
them at once.

Before CF-0140 that was discovered at resolve time, after TTS, and cost one
degraded block. Now the Editor's coverage preflight and the Researcher's gate
both stand on this cache, so a stale pool is no longer a degradation - the
batch cannot go on, and it finds out after the topics are picked. 1.3 s at the
front of this stage buys that back.

**When the guard refuses, the repair is still `pool-maintenance`'s, not this
stage's.** Close this stage first and run the repair under its own markers:

```bash
"$RUNLOG" stage-done footage-indexer --batch "$RUNLOG_BATCH" --note "pool stale, repairing under pool-maintenance"
"$RUNLOG" stage-start pool-maintenance --batch "$RUNLOG_BATCH"
RUNLOG_STAGE=pool-maintenance scripts/caption_cache.py --set-aside-stale ../../shared/footage/*.shots.json
"$RUNLOG" stage-done pool-maintenance --batch "$RUNLOG_BATCH" --note "caption: <N> stale crops set aside (CF-0819)"
```

`RUNLOG_STAGE` relabels the `script` and `child` events of those runs (markers
are never relabelled - a marker's stage is what you typed). Then `stage-start
footage-indexer` again and carry on: this stage is already allowed to open more
than once per batch. There is no pool-wide `remeasure_usability.py` here
either (CF-0410): the caption remeasure stays the only pool repair, because a
stale caption crop stops the run.

**Do not let anything re-measure the pool automatically.** The check is cheap;
the repair is no longer expensive either, but it is still not a cache-warming
chore: it changes the geometry of every clip cut from those sources from then
on, which is the thing CF-0055 insists somebody looks at - and on 2026-09-14
the full-pool re-measure moved **241 of 980** cached crops, 34 of them across
the 720px resolution floor. That is a real change to what `usable()` accepts,
and it is exactly what wants a human's eye.

The price, re-measured 2026-09-14 **after CF-0225**: the whole 47-source pool,
1411 shots, `--jobs 6 --include-uncached`, **51.7 minutes** wall - 2.20 s per
shot. Before CF-0225 the same work was ~33 s per shot serially and ~9.6 s at
`--jobs 6` (~2.6 h for 980 shots). Re-measuring the pool is now an hour you
schedule, not a day you avoid.

Note what that did to `--jobs`. CF-0225 collapsed the eight ffmpeg seeks into
one pass, so the *divisible* part of the cost is largely gone and what is left
is the single warm Vision worker, which does not divide. During the 51.7-minute
run only 2-4 ffmpeg processes were alive at a time while the Vision worker sat
at ~0.8 of a core, and one source measured **serially** ran at 2.45 s per shot
against the pool's 2.20 s per shot at `--jobs 6`. `--jobs` is close to spent as
a lever; the next real saving is in the Vision worker, not in more processes.

## A person with branding at the edge is not a card (CF-0413, 2026-09-28)

`is_card` is the script's call, never yours: CLIP similarity to the card phrases plus a Vision text probe on 8-20 frames of the shot. A card is a frame whose text or graphics *are* the content - a title, a poster, a slide, words on black. Video Editor delivers a card whole (`contain`, letterboxed), so a wrong `is_card` puts the whole frame, somebody's overlay included, on screen.

The user's rule of 2026-09-28: **an interview's branding is not a card.** The podcast `3oy35kY7guU` keeps its logo and a name plate in the lower corners of every interview shot; the logo line is headline-sized, every frame read as card text, and nine close-ups of the guest went into the backrooms rebuild as letterboxed cards. Since this task, a frame that reads as a card is asked one more question: is there a face at least **0.15** of the frame tall, and does at most **0.2** of the card text fall inside the 9:16 window the renderer points at that person? Then the text is beside the person, the frame counts as **branding**, not card text, and the shot records it as `branding_hit_rate` next to `card_text_hit_rate` / `caption_hit_rate`. Branding frames never carry a shot to `is_card`, and for the high-CLIP veto they count as captions do. A title that crosses the person, a name under an actor on a cast card, or a title over a wide scene with a small figure in it stays a card.

What does not change: `burned_text` is yours and is judged exactly as before (see the sieve above) - dropping the card flag does not make the overlay somebody else's text any less. Do not flip `is_card` by hand in `shots.json`, and do not re-index the old pool to apply this: sources are deleted after publishing, and the rule reaches every source indexed from here on.

## Limits, known and unfixed

- **Card flagging separates cleanly on some sources and not others.** In one trailer the cards scored 0.27-0.32 against a median of 0.22; in a dialogue clip the end cards scored 0.24 against real shots at 0.23. The threshold catches high-contrast cards and misses subtle ones - the asset gate downstream catches most of the rest. Do not raise the threshold to chase the stragglers, you will start discarding real shots.
- CLIP ranks by resemblance and knows nothing about whether a shot is *usable* - it once returned a frame that was 98% black. Whoever consumes a match must gate the cut before accepting it.
- Anchors are English-only; that is what the model was trained on.
