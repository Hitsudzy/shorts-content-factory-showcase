---
name: meme-library
description: Work the factory meme library with the user — review it on the command center's «Мемы» (`/memes`: keep/drop, «можно вырезать», accept new entries), add memes found in a reference Short or screenshots (stills from Imgflip, GIFs cut from a video clip), write ~20 tags per meme, apply the user's marks. Use when the user brings a Short/screenshots with memes, asks to add, review, retag or clean up memes, or mentions the meme desk / «таблицу мемов» / «Мемы» in the center.
---

You run the **meme desk** — the user's tool for `shared/inserts/memes/`
(`CF-0391`, born in the `CF-0381` session of 2026-09-24). The script is
`scripts/meme_desk.py`; its docstring is the reference for every subcommand.
This file is the process around it. The user decides what is in the library;
you make deciding cheap and do the machine half.

## The rules you work under

- **A meme carries no rights-holder entry** (`inserts/POLICY.md`, 2026-09-24). Do not
  write `rights_holder`. `source_url` is where the file came from — required,
  because removal needs to know what it removes.
- **Sources.** Stills: Imgflip template files (`i.imgflip.com/<code>.<ext>`),
  Wikimedia Commons. GIFs: cut by you from a video clip with `add-gif`.
  **Giphy and Tenor are not sources** (their terms, not the picture's rights);
  no scraping Know Your Meme or any platform with a script.
- **Size ceiling (CF-0392):** fitted whole into the insert box
  (`inserts/meme.json` `asset_floor.fit_box_px`, 1080×1219), the file may be
  stretched at most `asset_floor.max_upscale_factor` (2.25) times —
  `min(1080 / w, 1219 / h)`. The desk and the editor refuse the same files:
  a landscape 800×450 passes (1.35), a 470×470 does not (2.30). The short side
  alone decides nothing. Imgflip's GIF templates are mp4s about 250–300 px
  high and under ~480 wide — at or past the ceiling; that is why GIFs are cut
  from a clip.
- **A GIF is inserted whole**, never `cutout: true`. Whether a still may be
  cut out along its contour is **the user's call** (ticked on the desk, «Мемы» in the center),
  never yours — do not set `cutout` yourself.
- **Downloads need the user's yes** (file, source, size) before you fetch —
  a clip from YouTube included. One yes can cover a list you named.
- **The meme is not edited** (`inserts/meme.json` honesty rules): no text
  added, no panels filled.
- **A blank caption panel is not the meme** (CF-0534). An Imgflip template
  often carries an empty white (or black) panel for text across the full
  width above or below the picture — surprised-pikachu had 760 white rows of
  1892. Fitted `contain`, it is a white strip over the video. `add-image`
  cuts such a band off on the way in (a side at least
  `asset_floor.blank_band.min_share` = 12 % of the height, `inserts/meme.json`)
  and writes it into `notes`; `status` lists files still carrying one;
  `trim-blank [--id ID] [--dry-run]` cuts it off what is already in the
  library (original kept in `_desk/originals/`, embedding recomputed, the
  stretch ceiling re-checked — a file the cut pushes past it is left whole and
  reported for the user). Cutting the empty panel is allowed; touching the
  picture or its text is not.

## Per-channel banks (CF-0393)

A channel can have its **own** bank instead of the factory's default
`shared/inserts/memes/` (ExampleFilm's cinema bank). `channels/<id>.json` →
`insert_layers.meme.bank` names it, e.g. `"shared/inserts/memes-example-tech/"`;
the folder sits beside the default one with the same layout (tracked
`index.json`, ignored media and `_desk/`) plus a tracked `candidates.json`
of templates waiting on the user's yes. The meme layer reads the named bank
and nothing else - a bank that is missing is an error, never a fallback to
the cinema bank. A channel that names no bank reads the default folder.

- Every desk subcommand takes `--channel <id>` (reads the channel's `bank`)
  or `--bank memes-<id>`: the center's «Мемы» picks the
  channel's bank on the screen; `add-image`, `apply`, `trim-blank`,
  `cutout`, `status` all work inside that bank, and embedding runs
  `index_inserts.py --bank`.
- `candidates --channel <id>` prints the bank's candidate list, re-checks the
  stretch ceiling and totals the download - that list, named in chat, is what
  the user's yes covers. A row with `in_reel_bank` is the same Imgflip file
  already in the default bank: copy it on the disk, do not download it again.
- The register is the channel's: a tech bank holds reactions a tech explainer
  needs (this is fine, two buttons, they're the same picture), not film stills.
- The desk refuses to drop an intent's `expected_leader` only in the default
  folder - the vocabulary was measured there.
- A channel's switch goes on (`insert_layers.meme.enabled`) only once its bank
  holds accepted entries; `inserts/validate_inserts.py` refuses it earlier.

## Open the desk

The desk is the command center's «Мемы» (`/memes`, http://127.0.0.1:8790/memes,
the center on its default port; CC-0035 retired the desk's own page
`meme_desk.py serve` on 8765). Point the user there and pick the channel's
bank on the screen. Marks are saved to
`shared/inserts/memes/_desk/decisions.json` as they click (untracked, like the
media); nothing is written into `index.json` until you run `apply`.

## Adding memes from a reference

The user brings a Short and screenshots of its meme moments; the big caption
on each screenshot is the word the meme was placed under — that word goes
into the tags.

1. **Name each meme.** From the picture, then `WebSearch` to confirm the
   template's name and the film/show/person. Say plainly which ones you could
   not identify; ask the user for those rather than guessing.
2. **Still → Imgflip.** `WebFetch https://imgflip.com/memesearch?q=<name>` for
   template codes; probe `https://i.imgflip.com/<code>.{jpg,png}` with a HEAD
   request for size and type. Download candidates into the scratchpad, build a
   contact sheet, and **match each against the screenshot** before adding —
   a near-miss (other scene, two-panel, watermark) is not the meme.
3. **GIF → clip.** Find the scene on YouTube
   (`yt-dlp --flat-playlist "ytsearch5:<film> <scene>"`, the footage-indexer
   venv has yt-dlp), check the clip has ≥720p (`yt-dlp -F`), then
   `meme_desk.py sheet --video <url>` for a timestamped contact sheet and the
   scene cuts. Pick a span **inside one shot** (2–3 s) so the loop does not
   jump; `add-gif` warns if the span crosses a cut. If the clip does not hold
   the moment, say so and delete the clip — do not settle for a neighbour.
4. **Add** with `add-image` / `add-gif`. Each lands as `review: pending` and
   is embedded (CLIP) at once.
   - `--description`: one sentence of what the **picture** shows — the layer
     ranks by the picture against text, so describe the frame, not the joke.
   - `--tags`: about 20, English (the narration is English), three layers —
     the reaction (`cringe`, `disbelief`), the situation it answers
     (`box office bomb`, `reboot`, `killed off`), and the words a narrator
     may say at that moment (`deadline`, `multiverse`, `oscar`) — plus the
     film/character names. The reference's caption word, translated.
   - `--notes`: where it was found (the reference Short), the film and year,
     the reference caption word, anything the user should know.
5. Tell the user what landed, what did not and why (floor, no match, not
   found), and that the new ones wait on the desk with a yellow frame.

## Applying the user's marks

1. `meme_desk.py status` — pending entries, keep/drop counts, cutout ticks
   that differ from `index.json`, and **the user's notes**. A note is an
   instruction (fix these tags, this description is wrong): act on it.
2. `meme_desk.py apply --dry-run`, then `apply`. Accepted new entries lose
   `review`; rejected new ones leave with their file; cutout ticks are written.
3. Dropping **accepted** entries needs `apply --drop`, and the desk refuses
   any meme an intent in `inserts/meme.json` defaults to (`expected_leader`).
   Rewrite that intent's `default_query`/`expected_leader` first (measured
   with `agents/video-editor/scripts/measure_insert_lead.py --scan`), and
   check `tests/test_insert_library.py` still describes the library (the
   Wikimedia-subset test counts Commons files) — rewrite a test, never loosen
   it quietly.
4. Run `python3 -m pytest -q tests/test_meme_desk.py tests/test_insert_library.py
   tests/test_insert_layers.py`, then commit (`index.json` is tracked, the
   media and `_desk/` are not). Record what changed in the library's task
   (`CF-0381` while it is open).

## Functions for the command center (CF-0693)

The center's meme desk (CC-0024) imports `scripts/meme_desk.py` and calls
functions, not the CLI. Each takes its bank as a parameter — `channel=None,
bank=None, root=<shared/inserts>, repo=<checkout>` (neither = the default
`memes/`; never a module global, so Reel and Tech calls in one process do not
mix) — prints nothing, and refuses with `MemeDeskError(code, text)` (`text`
in Russian). `status`/`apply` in the terminal are thin wrappers over them.

- `desk_state(channel, bank)` — what `status` prints, as data (`bank`,
  `entries[]`, `decisions`, `status{pending, keep, drop, cut_diff, notes,
  stale, blank_bands}`); writes nothing, not even `_desk/` or a thumbnail.
- `save_marks(decisions, channel, bank, by=, via=)` — the page's draft
  `{id: {v: keep|drop, cut: bool, note: str}}`, validated; `by`/`via` stamp
  the changed marks (`marked_by`, `marked_at`, `via`).
- `plan_apply(channel, drop=False)` (writes nothing) and
  `apply_marks(channel, drop=False)` — `apply` split in two, same guards:
  accepted entries leave only with `drop`, an intent's default never,
  `cutout` only where a mark says so.
- `thumb(channel, meme_id)` — the card's picture, made on this call.

Error codes: `bank_conflict`, `no_channel`, `bad_bank`, `bad_index`,
`bad_draft`, `bad_spec`, `bad_decisions`, `unknown_id`, `invalid_index`,
`no_file`, `thumb_failed`.

The long jobs (CF-0694) are functions too, for the center to run in the
background — same rules, the bank a parameter, nothing printed, every media
path through `bank_media` (nothing read, cut or written outside the bank).
The CLI subcommands are thin wrappers and print what they always printed.

- `cutout_available()` → `(bool, reason)` — the cutout's macOS dependency
  (Vision, macOS 14+, Video Editor's venv) behind one check (CF-0654); on
  another OS the reason says so.
- `cutout_entries(channel, ids=None, force=False, dry_run=False)` →
  `{made[{id, file, bbox_px, coverage}], refused[{id, reason}], unchanged,
  missing, outside_bank, written}` — cuts only stills the user ticked
  (`cutout: true`); never sets the flag, never cuts a GIF (an id without the
  tick or a GIF is `not_cutout`).
- `trim_blank_entries(channel, id=None, dry_run=False)` → `{trim, left,
  under, changed, originals, embedding}` — the CF-0534 pass.
- `add_image_entry(meme_id, url, source_url, description, tags, notes)` and
  `add_gif_entry(meme_id, video, start, end, description, tags, source_url,
  notes, width, fps)` → `{entry, file, size, ..., embedding}` — they
  download (the still; yt-dlp for a video URL), so they run only on the
  user's word; a refused add leaves nothing in the bank.
- `make_sheet(video, start, end, every, out)` → `{sheet, scene_cuts}` — the
  sheet is written under `<bank>/_desk/sheets/` only.

More codes: `cutout_unavailable`, `not_cutout`, `bad_ids`, `bad_entry`,
`duplicate_id`, `bad_suffix`, `no_source_url`, `file_exists`,
`download_failed`, `bad_image`, `blank_image`, `over_ceiling`,
`media_failed`, `video_failed`, `bad_span`, `invalid_entry`, `outside_bank`.
The embedding after an add or a trim is data (`embedding{done, line,
error}`), not an error: the entry is in either way.

The center's delta (CF-0760, center 0.4.1, CC-0075/CC-0076):

- `plan_add_image(...)`, `plan_add_gif(...)`, `plan_sheet(...)` — the same
  arguments as `add_image_entry` / `add_gif_entry` / `make_sheet` and the same
  refusal codes, but no network, no child and no write (not even `_desk/`).
  They return `{bank, id, file, will_fetch: url|yt-dlp|local, url, video,
  source_url, span, tags (normalised), steps, max_seconds}` (`plan_add_gif` and
  `plan_sheet` add `cached` — the URL's video is already in the bank's cache,
  no download; `plan_sheet` adds `sheet`, the absolute path, and its `span` is
  `{start_s, end_s, every_s, frames}`; `id`/`tags` are None there).
  `max_seconds` is the job's worst-case wall time: the sum of the ceilings of
  every child it would run — the fetch (30 s for a still, yt-dlp 900 s; 0 for a
  local file or a cached video), each ffmpeg (900 s), each probe (ffprobe, the
  venv's git lookup: 60 s), the embedding (1800 s). A job past it is hung.
  Example: `plan_add_gif("deal-with-it", "https://www.youtube.com/watch?v=x",
  1, 2.5, "…", "cool, sunglasses", channel="example-tech")` →
  `{bank: "memes-example-tech", id: "deal-with-it", file: "deal-with-it.gif",
  will_fetch: "yt-dlp", url: <url>, video: <url>, cached: false, source_url:
  <url>, span: {start_s: 1.0, end_s: 2.5}, tags: ["cool", "sunglasses"], steps:
  [download, scenes, cut, check, index, embedding], max_seconds: 4680}`.
- URLs are http(s) only (`bad_url`: no `file://`, no bare path). A local video
  is taken only with `local=True` and only inside the bank (`outside_bank`;
  not there: `video_failed`). A URL's video is cached in
  `<bank>/_desk/clips/<sha1(url)>.mp4` — the sheet and the GIF fetch it once.
- Limits: a still's body over 25 MB is `download_failed`; a sheet over 300
  frames is `too_many_frames` (before the fetch when `end` is given, after the
  frames are taken when it is the video's end).
- `by=None, via=None` on `cutout_entries`, `trim_blank_entries`,
  `add_image_entry`, `add_gif_entry` (`bad_who`): a stamp `<kind> <date> (by X,
  via Y)` in the entry's `notes` (a re-run replaces it) and a row `{at, by, via,
  kind, ids}` in `<bank>/_desk/jobs.jsonl`, kind `cutout` | `trim_blank` |
  `add_image` | `add_gif` (a dry run or a refused add writes no row).
- `progress=None` — a callable `(step, i, of, text)` (`bad_progress`
  otherwise; one that raises never stops the job): cutout `("cutout", i, N,
  id)`, trim `("trim", i, N, id)`, then `("embedding", 1, 1)`; add-image
  `download → check → index → embedding` (1..4 of 4); add-gif `download →
  scenes → cut → check → index → embedding` (1..6 of 6); the sheet `download →
  frames → sheet` (1..3 of 3). With `embed=False` the adds have no embedding
  step (`of` one less).
- The cutout and the trim re-read `index.json` right before their write and
  apply their results by id, so marks applied or candidates accepted meanwhile
  are kept; an entry gone during the pass is `index_changed` (the rest is
  written). A file that crashes in the middle is refused (cutout) or left
  (trim) and the pass goes on; the index is written all the same.
- The footage-indexer venv (embedding, the sheet's Pillow) and its yt-dlp are
  found from a worktree too (the main checkout's, via `git
  --git-common-dir`).

New codes: `bad_url`, `too_many_frames`, `index_changed`, `bad_progress`
(and `bad_who` on the jobs).

Background jobs (CF-0755, center 0.4.1, CC-0075/CC-0076) — the center runs a
long job as a process of its own and only reads it afterwards (the shape of
the Studio reading, `agents/analyst/studio_center.py`); there is no cancel.

- `start_job(kind, params, *, channel=None, bank=None, by, via, root, repo,
  environ=None)` → `{job_id, bank, kind, pid, log, state_file}`. `kind`:
  `cutout | trim_blank | add_image | add_gif | sheet | embed`; `params` are the
  function's own arguments (cutout `ids, force`; trim_blank `id, embed`;
  add_image `meme_id, url, source_url, description, tags, notes, embed`;
  add_gif `meme_id, video, start, end, description, tags, source_url, notes,
  width, fps, local, embed`; sheet `video, start, end, every, out, local`;
  embed none) — never channel/bank/root/repo/by/via/progress/dry_run
  (`bad_params`). `by` and `via` are required (`bad_who`). Before anything
  starts it runs the job's plan and refuses with its code: cutout →
  `cutout_available` + `cutout_entries(dry_run=True)`, trim_blank →
  `trim_blank_entries(dry_run=True)`, add_image → `plan_add_image`, add_gif →
  `plan_add_gif`, sheet → `plan_sheet`, embed → the bank is there. Then it
  writes `<bank>/_desk/jobs/<job_id>.json` (state `running`) and starts
  `python3 scripts/meme_desk.py job-run <state_file>` detached (its own
  session, output in `<job_id>.log`, cwd `repo`, environment `environ`).
- `job_status(job_id, *, channel=None, bank=None, root, repo)` → `{job_id,
  kind, bank, state: running|done|failed|interrupted, done, started_at,
  ended_at, pid, alive, progress {step, i, of, text}|None, result (the
  function's return as JSON)|None, error {code, text, en[, log_tail]}|None,
  log, by, via, params, max_seconds}` (`max_seconds` from the plan; None for
  cutout, trim and embed). `unknown_job` for an id not in the bank.
- `list_jobs(*, channel=None, bank=None, limit=20, root, repo)` — the bank's
  jobs newest first, each as `job_status` (limit 1..50, `bad_limit`).
- `active_job(*, root=None, repo, environ=None)` (CF-0761) — the machine's
  slot for the center's plan, so «занято» shows before the confirmation:
  `{job_id, kind, bank, channel, started_at, alive}` of the job in
  `active.json`, or None when there is no slot file. `alive` is the same
  lock probe as `job_status` (non-blocking); a dead job is `alive: false`, not
  None. `channel` — the one channel whose `insert_layers.meme.bank` is that
  bank, null for the shared default bank. Reads only: writes, cleans and
  locks nothing (never the slot's `.lock`).
- `job-run` puts `/opt/homebrew/bin` and `/usr/local/bin` on `PATH` when
  missing, writes each progress tick into the state file atomically, and ends
  `done` with `result`, or `failed` with the function's `MemeDeskError` code,
  `job_crashed` (an unexpected exception; the traceback is in the log and its
  tail in `error.log_tail`) or `embed_failed` (an `embed` job whose embedding
  did not happen). In the adds and the trim the embedding is a step:
  `embedding.done=false` there leaves the job `done`.
- Alive is the job's lock, not its pid: start_job takes a flock on
  `<job_id>.lock` before the state says `running` and hands it to the child;
  it is freed when the process ends, however it ends. `running` over a free
  lock is `interrupted` (`error.code` `job_interrupted`, with the log's tail).
- One job per machine: the slot is `<main checkout>/schedule/meme-desk/`
  (`active.json` + `.lock`; `MEME_DESK_JOBS_DIR` overrides) — a release
  worktree's center and the production one share it, as they share the banks.
  A second start while a job is alive is `job_running` (`.job_id` names it);
  a dead one does not block. start_job keeps the last 50 records per bank.

Job codes: `bad_kind`, `bad_params`, `job_running`, `spawn_failed`,
`unknown_job`, `bad_limit`; in `error`: `job_crashed`, `job_interrupted`,
`embed_failed` (and every code of the job's function).
