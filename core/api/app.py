"""CC-0003: the FastAPI application of the command center.

    create_app(settings=None) -> FastAPI

Routes (the contract is `api/openapi.json`, checked by
`tests/test_cc_api.py`):

    GET <base>api/health     alive - cheap, the center polls it; whether it writes
                             (CC-0058: writes, writes_reason, writes_dev)
    GET <base>api/version    the factory's version, the agents' pins, the center's build
    GET <base>api/versions   CC-0030: versions and the agents (`api/versions.py`): each
                             agent's pin, HEAD, dirty, ok/why and its `scripts/agents
                             status` line verbatim; the modules (the center's build
                             stamp); every line of the CLI with its exit code; the
                             factory (README version, HEAD, branch, main); kept 30 s,
                             ?fresh=true checks again
    GET <base>api/dev/tasks  CC-0124: the development tasks of the factory (CF-*, `main` and
                             the version lines in work) and of the center (CC-*, `main` of
                             its repo), read from git (`api/dev.py`): frontmatter, archived,
                             checklist counts; ?project= &milestone= &status= &type= &repo=
                             (comma lists, exact) &q= (words in id/title/body)
    GET <base>api/dev/tasks/{id}  one task: body, checklist, related ids, its commits
    GET <base>api/dev/roadmap     ROADMAP.md of both: milestones, sprints, task ids in order
    GET <base>api/session    the token a POST carries in `X-CC-Session`
    GET  <base>api/auth/state   CC-0036: {required, logged_in} - this client has to log in
    POST <base>api/auth/login   {password} -> {logged_in: true} + the cookie `cc_auth`;
                                401 wrong_password, 429 locked {retry_after}, 409 auth_off
    POST <base>api/auth/logout  the session ended, the cookie cleared
    GET <base>api/questions  the questions to the user (CF-0652, shared/needs_you.py);
                             ?status=live (default: open + answered) | open | answered
                             | resolved | all
    POST <base>api/questions/{id}/answer   {"text", "by"?} - the user's answer, or
                             {"accept": true, "suggested_at"?} - the question's current
                             suggestion (CC-0086, CF-0703); via "center", accepted_suggestion
                             decided on a fresh read of the question
    POST <base>api/questions/{id}/resolve  {"note"?, "by"?} - mark it resolved
    GET  <base>api/requests  the user's requests to the operator (CC-0018, CF-0684,
                             shared/operator_requests.py); ?status=live (default: open +
                             taken + answered) | open | taken | answered | closed
                             | cancelled | all
    GET  <base>api/requests/{id}           one request
    POST <base>api/requests                {"text", "channel"?, "context"?} - ask the
                                           operator (by: user); queued, nothing runs
    POST <base>api/requests/{id}/close     answered -> closed (by: user)
    POST <base>api/requests/{id}/cancel    open/taken -> cancelled (by: user)
    (`next`, `answer` - it sends the answer to Telegram - and `resend` are the
    operator session's, `python3 shared/operator_requests.py ...`; no route.)

    CC-0006, a channel's config and position (`api/channels.py`):
    GET  <base>api/channels                                   the channels
    GET  <base>api/channels/{channel}                         config, position, fields, checks, lock
    POST <base>api/channels/{channel}/check                   the factory's verdict, nothing written
    PUT  <base>api/channels/{channel}                         check -> write -> one commit
    GET  <base>api/channels/{channel}/history                 the commits of its files
    POST <base>api/channels/{channel}/history/{commit}/revert one edit undone by a new commit

    CC-0008, a new channel (`shared/new_channel.py`, the template `shared/channel_template/`):
    GET  <base>api/channels/template      the inputs, defaults, notes, files; can one be made now
    POST <base>api/channels               {channel_id, display_name, language?, stance_text?,
                                          dry_run?} -
                                          check -> write -> one commit «Канал <имя>: создан
                                          (из центра)»; `dry_run` - what would be, nothing written

    CC-0044, the batch schedule and the batches (`api/batches.py`, `shared/batch_schedule.py`,
    `shared/runlog/runs_table.py`, `event_log.load_events`):
    GET  <base>api/schedule?days=N                the plan: days, channels, switch, stale_open, timer
    POST <base>api/schedule/switch                {on, note} - set_switch(on, "user", "центр: <note>");
                                                  on needs a note
    GET  <base>api/schedule/channels/{channel}    the channel's schedule settings and their history
    PUT  <base>api/schedule/channels/{channel}    {enabled?, window?, window_hours?, min_feed_days?,
                                                  batch_feed_days?, windows?, note?} -
                                                  set_channel_settings(by "user"); CC-0184:
                                                  min_feed_days the feed's horizon,
                                                  batch_feed_days the batch threshold
    GET  <base>api/batches/history?channel&limit  the runs (runs.jsonl) with who launched them
    GET  <base>api/batches/stranded?channel&limit  CC-0114: batch_schedule.stranded_batches
                                                  (CF-0723) - stopped badly, no runs.jsonl
                                                  row, not open; log_url to the log route
    GET  <base>api/batches/{channel}/{batch_id}/stages            markers, stages, logs/*.log
    GET  <base>api/batches/{channel}/{batch_id}/logs/{name}?bytes  a log's tail
    GET  <base>api/batches/{channel}/{batch_id}/footage  CC-0119: the Footage Indexer's
                                                  collection per topic (footage_progress,
                                                  CF-0715: the progress file, RUN_EVENTS or
                                                  01b), kept per state of those files

    CC-0045, the batches going (`shared/factory_state.py` `batches`,
    `run_executor.pid_alive`, `shared/needs_you.py`, RUN_EVENTS.jsonl):
    GET  <base>api/batches                        every open batch as the console shows it
                                                  (a kept scan: checked_at, age_s, checking)
    GET  <base>api/batches/{channel}/{batch_id}   its run-state.json, processes alive, questions
    GET  <base>api/batches/{channel}/{batch_id}/events?after&limit  RUN_EVENTS.jsonl by byte
                                                  cursor - poll every `poll_s` (no SSE)

    CC-0046, the launch with a confirmation (`shared/batch_schedule.py`
    `launch_check` / `manual_launch`):
    POST <base>api/batches/launch/plan            {channel} - the check (guards, argv, skipped)
                                                  and, when ok, a confirm token (120 s, once)
    POST <base>api/batches/launch                 {channel, confirm} - the check again, the same
                                                  fingerprint, then manual_launch(confirmed,
                                                  by "user (центр)"): pid, log, the journal row

    CC-0047, stop and resume with a confirmation (`shared/batch_control.py`
    `stop_check` / `stop`, `resume_check` / `resume`):
    POST <base>api/batches/{channel}/{batch_id}/stop/plan    {also_step?} - stop_check and, when
                                                  ok, a confirm token (120 s, once)
    POST <base>api/batches/{channel}/{batch_id}/stop         {confirm, also_step?} - the check
                                                  again, the same fingerprint, then
                                                  stop(confirmed, by "user (центр)"): SIGTERM
                                                  to the executor's group, waits <= 30 s
                                                  (+30 s for the step with also_step)
    POST <base>api/batches/{channel}/{batch_id}/resume/plan  resume_check and, when ok, a token
    POST <base>api/batches/{channel}/{batch_id}/resume       {confirm} - the check again, then
                                                  resume(confirmed, by "user (центр)"):
                                                  run_executor --resume detached, waits <= 15 s

    CC-0123, «повторить со стадии» with a confirmation (`shared/batch_control.py`
    `rerun_from_check` / `rerun_from`, CF-0739):
    GET  <base>api/batches/{channel}/{batch_id}/rerun-from  stages_for_rerun - each stage of
                                                  run-state.json order: status, can, why
    POST <base>api/batches/{channel}/{batch_id}/rerun-from/plan  {stage} - rerun_from_check
                                                  (by user via center): reset, kept, lines,
                                                  code + message; a token when ok (120 s)
    POST <base>api/batches/{channel}/{batch_id}/rerun-from  {confirm, note?, resume?} - the
                                                  check again, the same fingerprint, then
                                                  rerun_from(confirmed, resume_after=resume)

    CC-0048, the rebuild of chosen videos with a confirmation (`shared/batch_control.py`
    `rebuild_check` / `rebuild`, the modes off `shared/run_plan.py` `rebuild_modes`):
    GET  <base>api/batches/{channel}/{batch_id}/rebuild/modes  the channel's rebuild modes
                                                  (id, title, from_stage)
    POST <base>api/batches/{channel}/{batch_id}/rebuild/plan   {videos, mode, notes?} -
                                                  rebuild_check and, when ok, a confirm token
                                                  bound to the videos, mode and notes
    POST <base>api/batches/{channel}/{batch_id}/rebuild        {confirm} - the check again,
                                                  the same fingerprint, then rebuild(confirmed,
                                                  by "user (центр)"): pipeline/rebuilds/<ts>,
                                                  batch-start, the executor detached

    CC-0012, a batch's videos for the acceptance (`api/videos.py`: `runlog.editor_videos`,
    `shared/runlog/acceptance.py` `state` / `record_and_commit`, `publish_card.placeable`,
    `publish_note.sections` / `parse`):
    GET  <base>api/batches/{channel}/{batch_id}/videos      the videos of its 05, each with its
                                                  score line, mp4, preview, card, verdict; the
                                                  rebuilds of a source beside it; CC-0116:
                                                  the videos refused after the render too
                                                  (05 refusals[], `refused`), no verdict
    GET  <base>api/batches/{channel}/{batch_id}/videos/{slug}/mp4      video/mp4, HTTP Range
    GET  <base>api/batches/{channel}/{batch_id}/videos/{slug}/preview  the Editor's frame
                                                  videos/<slug>.jpg (image/jpeg, CF-0674), else
                                                  the frame judge's first contact sheet
                                                  (image/png)
    GET  <base>api/batches/{channel}/{batch_id}/videos/{slug}/score    CC-0125: the score log
                                      (plan.score.json, else the 05's block) - tiers, stages,
                                      findings with Russian rule names
    GET  <base>api/batches/{channel}/{batch_id}/videos/{slug}/card     the publication card,
                                                  parsed, the raw text beside
    POST <base>api/batches/{channel}/{batch_id}/videos/{slug}/acceptance {verdict yes|no|redo,
                                                  words, reason?, reason_code?, amend?} - the
                                                  user's press: acceptance.record_and_commit
                                                  (CF-0675): one commit of the record, or the
                                                  queue under an open batch (pending, HEAD
                                                  unchanged); refusals carry the factory's
                                                  code (CF-0676)
    POST <base>api/batches/{channel}/{batch_id}/videos/{slug}/withdraw/plan - CC-0107, taking
                                                  it off for good (`pool_release`): its topic,
                                                  topic_status, the pool's what-if; a token
    POST <base>api/batches/{channel}/{batch_id}/videos/{slug}/withdraw {confirm, answer} -
                                                  the user's Russian words naming it, then
                                                  record_withdrawal (nothing deleted)

    CC-0100, what a refusal costs (`api/gate_prices.py`: `shared/runlog/gate_price.py`
    price per rule), and CC-0114 the signature / decision through gate_price.sign /
    decide (CF-0721, by user via center; the factory commits the ledger):
    GET  <base>api/gate-prices?rule&window&before  `runlog gate-price --json`: per rule the
                                                  window's batches, the price, the verdict,
                                                  the signature and decision as read, what
                                                  the buttons may do (actions), ledger_sha256
    POST <base>api/gate-prices/{rule}/sign/plan {price, note, base_sha256?}  sign dry run,
                                                  a confirm token when ok (120 s, once)
    POST <base>api/gate-prices/{rule}/sign {confirm}  sign for real with the plan's base
    POST <base>api/gate-prices/{rule}/decide/plan {mode, task, note, base_sha256?}  decide
                                                  dry run, a token when ok
    POST <base>api/gate-prices/{rule}/decide {confirm}  decide for real with the plan's base

    CC-0049, seconds of a video to its storyboard blocks (`shared/batch_control.py`
    `blocks_at`, CF-0669), read only:
    GET  <base>api/batches/{channel}/{batch_id}/videos/{slug}/blocks?at=12,18,24  the block of
                                                  each second, its shots, the exclusion
                                                  (`BLOCK=SOURCE:SHOT`) for rebuild/plan's notes

    CC-0091, what each stage found and decided about the topics, while the batch runs
    (`api/topics.py`, `shared/runlog/funnel.py` `read_artifacts`), read only:
    GET  <base>api/batches/{channel}/{batch_id}/topics   the shortlist and the skipped (01),
                                                  the verdict / reserve / cut (02), footage
                                                  (pool, 01b), scripts and videos (03-06),
                                                  a Russian state line each, search_quota;
                                                  a stage not done: its block null
    GET  <base>api/batches/{channel}/{batch_id}/topics/{topic_id}  one topic: scenes, the
                                                  fact and its source, links, searches

    CC-0064, the publication side, read only (`api/publish.py`: `publish_queue`,
    `channel_pause`, `publish_card`, `studio_fields`, `api_switch`, `publication_hold`,
    `rotate`) - every route a GET, nothing written:
    GET  <base>api/publish                        every channel's queue in a line
    GET  <base>api/publish/holds?channel          open holds and the ledger's rows, each
                                                  with signable / sign_refusal (check_sign,
                                                  CC-0070)
    GET  <base>api/publish/holds/released?channel&days&limit  CC-0169: the holds lifted
                                                  (or lifted by the scene rule and put back)
                                                  lately, each with its release line
    GET  <base>api/publish/api-upload             the API-upload switch of every channel,
                                                  the warnings of enabling it
    GET  <base>api/publish/{channel}/queue?days   slot, slots taken / free, next free,
                                                  the waiting ones, pause, tomorrow, occupants
    GET  <base>api/publish/{channel}/pause        status, open row, history
    GET  <base>api/publish/{channel}/api-upload   the channel's switch and warnings
    GET  <base>api/publish/{channel}/rotation     distribution_report (+ awaiting_material)
    GET  <base>api/publish/{channel}/config       the publisher block (channel_config)
    GET  <base>api/publish/{channel}/studio       the Studio streak
    GET  <base>api/publish/{channel}/notes/{slug}?day&batch_id  a placed card: the short view, the
                                                  form, the Studio fields or why not, its
                                                  batch and the videos' routes

    CC-0070, the hold's signature (`publication_hold.check_sign` / `sign_hold`,
    CF-0687) - plan, then confirm, as the publication writes:
    POST <base>api/publish/{channel}/holds/{batch_id}/{topic_id}/sign/plan  {note} - the
                                                  hold, what compliance-checker recorded, what
                                                  signing means; a confirm token
    POST <base>api/publish/{channel}/holds/{batch_id}/{topic_id}/sign       {confirm} -
                                                  sign_hold(user, note, via=center)

    CC-0020, the statistics and the analyst, read only (`api/analytics.py`:
    `metrics_store`, `metrics.default_day`, `summary.build`, `footage_wanted.build`,
    `studio_read` `last_videos` / `due`) - every route a GET, nothing written:
    GET  <base>api/analytics                      the journal's channels: last collection run,
                                                  the days a summary was written for
    GET  <base>api/analytics/{channel}/metrics?first_days  every stored video: YouTube's
                                                  window of the first N days, the last daily
                                                  row, the last Studio read (metrics.py show)
    GET  <base>api/analytics/{channel}/videos/{video_id}   its daily rows, windows, Studio reads
    GET  <base>api/analytics/{channel}/summary?day&first_days  summary.build - the videos
                                                  beside their style, the groups' statistics
    GET  <base>api/analytics/{channel}/summary/{day}       the summary written for the day
    GET  <base>api/analytics/{channel}/footage-wanted?since&packed  footage_wanted.build
    GET  <base>api/analytics/{channel}/studio     what to read in Studio (last_videos, due),
                                                  the last visits, the latest read per video
    CC-0074, entering what Studio was read to say (`api/studio_entry.py`:
    `studio_read.parse_read` / `record(by, via)` - CF-0692):
    POST <base>api/analytics/{channel}/studio/record/plan  {read} - parse_read (nothing
                                                  written), each video's last stored read,
                                                  a confirm token (studio_read_record)
    POST <base>api/analytics/{channel}/studio/record       {confirm} - the same parse and
                                                  store, record(by user, via center)
    CC-0120, the Studio read on the user's actions (`api/studio_center.py`,
    `agents/analyst/studio_center.py`, CF-0735):
    GET  <base>api/studio/due?channel&hook        studio_read_due - due, why, the last read,
                                                  each channel, a session going; the switch
    POST <base>api/studio/read/plan               studio_read_launch(by user, via center) -
                                                  nothing started; a token when the switch
                                                  (STUDIO_READ_LAUNCH) is on - on since
                                                  the user's «да» of 17.10 (v2.8.1)
    POST <base>api/studio/read                    {confirm} - the session started detached
                                                  (a child): run id, pid, log
    GET  <base>api/studio/read/{run_id}           studio_read_result - read / no_extension /
                                                  login_needed / error / running

    CC-0022, a channel's lists, read only (`api/rights.py`: `channel_data`,
    `footage_licence`) - every route a GET, nothing written:
    GET  <base>api/channels/{channel}/rights-holders  the channel's rights-holder blacklist
    GET  <base>api/channels/{channel}/footage-origin  footage-origin.json and its errors
    GET  <base>api/channels/{channel}/fact-sources  CC-0102: fact-sources.json, its kinds,
                                                  validate_sources / source_policy_errors /
                                                  attribution_terms_errors
    GET  <base>api/channels/{channel}/affiliate   CC-0102: the config's affiliate block,
                                                  affiliate.json, channel_errors
    (CC-0114: each of the four GETs carries the file's sha256. The writes, `api/channel_lists.py` over the
    factory's checked writers, CF-0726 - plan = the writer's dry run by user via
    center and a token, confirm = the real write with the plan's base_sha256:)
    POST <base>api/channels/{channel}/fact-sources/plan  {doc, base_sha256} -
                                                  write_fact_sources(dry_run=True)
    POST <base>api/channels/{channel}/fact-sources  {confirm} - write_fact_sources, a commit
    POST <base>api/channels/{channel}/footage-origin/plan + /footage-origin  the same,
                                                  write_footage_origin
    POST <base>api/channels/{channel}/affiliate/plan + /affiliate  the same,
                                                  affiliate.write_table
    GET  <base>api/channels/{channel}/ending      CC-0101: the ending clip (end_card's
                                                  ending_path / ending_seconds / probe_ending
                                                  / check_ending), brand.json's ending
                                                  (CF-0722) and brand_ending.render_plan
    POST <base>api/channels/{channel}/ending/plan  CC-0114: the render's plan afresh, the
                                                  channel's open batches, a confirm token
    POST <base>api/channels/{channel}/ending      {confirm} - the same plan, then
                                                  brand_ending.py detached (pid, log)

    CC-0024, the meme desk of a channel (`api/memes.py`: `scripts/meme_desk.py`
    desk_state, save_marks, plan_apply, apply_marks, thumb - CF-0693):
    GET  <base>api/memes                          every channel, its bank, the desk's counts
    GET  <base>api/memes/{channel}                desk_state, the draft's / index's sha256,
                                                  each entry's media routes
    GET  <base>api/memes/{channel}/{meme_id}/media?kind=file|cut  the file inside the
                                                  bank, HTTP Range
    GET  <base>api/memes/{channel}/{meme_id}/thumb  thumb(): a still's cached JPEG, a GIF
    PUT  <base>api/memes/{channel}/marks          {decisions, base} - the whole draft,
                                                  save_marks(user, via center); `base` the
                                                  draft's sha256, else check_changed
    GET  <base>api/memes/{channel}/candidates     CC-0103: candidates.json (`meme_desk.py
                                                  candidates`), candidate_problems, the
                                                  default bank's routes, candidates_state's
                                                  status and fingerprint (accept)
    POST <base>api/memes/{channel}/candidates/accept/plan  CC-0114: {ids?, details?} -
                                                  plan_accept (CF-0725), a confirm token
    POST <base>api/memes/{channel}/candidates/accept  {confirm, answer} - the user's typed
                                                  «да» (check_accept_answer), then
                                                  accept_candidates by user via center
    POST <base>api/memes/{channel}/apply/plan     {drop?} - plan_apply, a confirm token
    POST <base>api/memes/{channel}/apply          {confirm} - the same fingerprint, then
                                                  apply_marks
    CC-0075, the desk's background jobs (`api/meme_jobs.py`: cutout_available,
    cutout_entries / trim_blank_entries dry runs, start_job, job_status, list_jobs -
    CF-0760/CF-0755); polled, not SSE; one job per machine, no cancel; while a job
    runs on a bank the marks, apply, the candidates' yes and a new start there are
    409 job_active:
    POST <base>api/memes/{channel}/cutout/plan    {ids?, force?} - cutout_available + the
                                                  dry run, a confirm token (meme_cutout)
    POST <base>api/memes/{channel}/cutout         {confirm} - the same fingerprint, then
                                                  start_job("cutout") in the launcher child
                                                  -> {job_id, poll_s, status_url}
    POST <base>api/memes/{channel}/trim/plan      {id?} - the trim's dry run, a confirm token
                                                  (meme_trim)
    POST <base>api/memes/{channel}/trim           {confirm} - start_job("trim_blank")
    POST <base>api/memes/{channel}/add-image/plan  CC-0076: {id, url, source_url,
                                                  description, tags, notes?} - http(s) only
                                                  (bad_url), plan_add_image, a token
                                                  (meme_add_image)
    POST <base>api/memes/{channel}/add-image      {confirm} - start_job("add_image")
    POST <base>api/memes/{channel}/add-gif/plan   {id, video, start, end, description, tags,
                                                  source_url?, notes?} - plan_add_gif with
                                                  local=False, a token (meme_add_gif)
    POST <base>api/memes/{channel}/add-gif        {confirm} - start_job("add_gif")
    POST <base>api/memes/{channel}/sheet/plan     {video, start?, end?, every?, out?} -
                                                  plan_sheet with local=False (meme_sheet)
    POST <base>api/memes/{channel}/sheet          {confirm} - start_job("sheet")
    POST <base>api/memes/{channel}/embed/plan     the center's own plan (the factory has no
                                                  dry one), a token (meme_embed)
    POST <base>api/memes/{channel}/embed          {confirm} - start_job("embed")
    GET  <base>api/memes/{channel}/sheets/{name}  <bank>/_desk/sheets/<name> (.jpg/.jpeg/.png,
                                                  factory.contained), HTTP Range
    GET  <base>api/memes/{channel}/jobs?limit     list_jobs, newest first, + the running one
    GET  <base>api/memes/{channel}/jobs/{job_id}  job_status + poll_s (null when done)

    CC-0026, the notifications and the user's reminders (`api/notifications.py`:
    `shared/notify.py` rows, reminders, the dry `test` and test_preview, parse_when,
    add_reminder(by, via); CC-0081 cancel_reminder(by, via)):
    GET  <base>api/notify/journal?kind&channel&limit  notify/sent.jsonl, newest last
    GET  <base>api/notify/reminders?all           the reminders queue (`remind --list`)
    GET  <base>api/notify/check                   `notify.py test` - what each backend that
                                                  is on would get (test_preview per backend,
                                                  the CLI's lines); nothing sent
    POST <base>api/notify/reminders/plan          {at, text} - parse_when, one_line,
                                                  a confirm token (notify_reminder_add)
    POST <base>api/notify/reminders               {confirm} - add_reminder(by user, via
                                                  center)
    POST <base>api/notify/reminders/{rid}/cancel/plan  the reminder, its state, what a cancel
                                                  means, a confirm token
                                                  (notify_reminder_cancel)
    POST <base>api/notify/reminders/{rid}/cancel  {confirm} - the same reminder, then
                                                  cancel_reminder(by user, via center)
    POST <base>api/notify/test-send/plan          CC-0109 (`api/notify_send.py`): the delivery
                                                  channels that are on, by name (test_preview),
                                                  a confirm token (notify_test_send)
    POST <base>api/notify/test-send               {confirm} - the same channels, then
                                                  notify.send("test", ...) once, as
                                                  `notify.py test --send`; per channel
                                                  {via, ok, detail}, masked

    CC-0028, the publisher's OAuth token and the API Data (`api/oauth.py`:
    `publisher_auth.status`, `read_state`; `api_data.status`, `plan`, `auto`,
    `apply`, the dry `revoke`; CC-0082: `revoke_result`, `auto(delete=True)`):
    GET  <base>api/oauth/token                    the token's state, term and scopes -
                                                  never its value
    GET  <base>api/oauth/api-data                 the API Data held, the revocation mark,
                                                  what the auto-run would delete now
    GET  <base>api/oauth/revoke                   `api_data.py revoke` without --yes - its
                                                  dry run; nothing reaches Google
    POST <base>api/oauth/revoke/plan              revoke_result without yes (by user via
                                                  center), a confirm token (oauth_revoke)
    POST <base>api/oauth/revoke                   {confirm} - the same dry run, then
                                                  revoke_result(yes, by user, via center)
    POST <base>api/oauth/api-data/purge/plan      {scope: all | channels, channels} - the
                                                  purge's plan, a confirm token
                                                  (api_data_purge)
    POST <base>api/oauth/api-data/purge           {confirm} - the same plan, then
                                                  apply(by user, via center)
    POST <base>api/oauth/api-data/auto/plan       auto(delete=False) - what the deletion by
                                                  term would delete, a confirm token
                                                  (api_data_auto)
    POST <base>api/oauth/api-data/auto            {confirm} - the same plan, then
                                                  auto(delete, by user, via center)

    CC-0032, maintenance and spend (`api/maintenance.py` - the factory's own
    scripts, nothing of the API's own; no absolute path leaves):
    GET  <base>api/maintenance                    which script is read, plan/confirm or
                                                  not exposed, and why
    GET  <base>api/maintenance/usage/{c}/{b}      usage_report --json (usage.read_usage,
                                                  usage.totals)
    GET  <base>api/maintenance/compare            ?manual=c/b&executor=c/b - compare_runs
                                                  --json (compare), its verdict
    GET  <base>api/maintenance/archive            archive_publish_month --dry-run
                                                  [--publish-only] - its lines, exit code
    POST <base>api/maintenance/archive/plan       CC-0104: --dry-run --json --publish-only -
                                                  the month's zip, members, what leaves
                                                  publish/; a token unless a batch is open
                                                  or the volume is missing
    POST <base>api/maintenance/archive            {confirm} - no batch open, the same dry run,
                                                  then the real run --by user --via center
    POST <base>api/maintenance/journals/plan      cleanup_batch_journals.plan - a confirm
                                                  token (batch_journals_cleanup) unless a
                                                  batch is open
    POST <base>api/maintenance/journals           {confirm} - no batch open, the same plan,
                                                  then delete(root, rows)
    GET  <base>api/maintenance/pool               CC-0105: pool_release.plan + variants -
                                                  what `runlog pool-release --json
                                                  --variants [--stale-days N]` prints
    POST <base>api/maintenance/pool/release/plan  {stale_days} - the same plan, what
                                                  --delete would remove, a confirm token
                                                  (pool_release_delete) unless a batch is open
    POST <base>api/maintenance/pool/release       {confirm} - no batch open, the same plan,
                                                  then pool_release.delete(p, root)

    GET <base>...            the built center (`frontend/dist`), index.html for
                             any path that is not a file (the router's own paths)

**The guard** (as the retired 2.2 console's, CF-0590/CF-0605), on
every request before any route:

* listening on loopback -> the client is loopback too;
* `Host` is this address (`127.0.0.1:<port>`, `localhost:<port>`, `[::1]:<port>`,
  plus `CC_API_ALLOWED_HOSTS`) - a DNS-rebinding name gets 403, GET too;
* a request that may act (anything but GET/HEAD/OPTIONS): `Origin` (or,
  without it, `Referer`) is this address or one of `CC_API_ALLOWED_ORIGINS`,
  and `X-CC-Session` is the secret of this server process
  (`secrets.token_urlsafe`, a new one per start). A page of another site cannot
  read `/api/session` (no CORS is ever answered), so it cannot know it.

A refusal is `403 {"detail", "guard"}`.

**The password** (CC-0036, CF-0616; `api/auth.py` is the whole rule): with
`CC_BIND` (a bind that is not loopback) and `CC_PASSWORD_HASH`, a client that
is not this machine (the TCP peer, never X-Forwarded-For) needs the session
cookie `cc_auth` for every route and every file of the center, except
`AUTH_OPEN_API` (auth/state, auth/login, auth/logout) and the login screen's
files (the page, `assets/`, the icons) - else `401 {detail, code:
auth_required, retry_after: null}` (`AuthProblem`), checked after the Host and
before the Origin/session checks, which stay for its writes (the login and the
logout need this Origin, not `X-CC-Session`). The Mac never logs in. A bind
that is not loopback without a hash: `create_app` and the settings refuse.

**Writes only in the working factory** (CC-0058): the factory's rule
`agents_lock.is_working_factory` (CF-0677) - the main checkout on `main` -
asked for `factory_root` and kept `factory.WORKING_FACTORY_TTL_S` (5 s; the
branch can change under the API). Every route that writes depends on
`require_writes` (a FastAPI dependency, run before the body is validated and
before any factory call); outside the working factory it answers
`409 {message: «Только смотреть: <причина>», code: not_working_factory, details}`
(`WritesProblem` - 409, not 403: the request is fine, the state of this
checkout is not, and 403 is the guard's). Allowed everywhere: every GET,
`POST /channels/{c}/check`, `POST /channels` with `dry_run: true` (the route
asks `require_writes` itself when not a dry run). `tests/test_cc_api_writes.py`
walks the app's routes: every non-GET one is guarded or in its allow-list.
The developer's `CC_API_WRITES=dev` lets a development copy write: a warning
when the app is made and one per write it lets in (logger `api.writes`), and
`/health` says `writes_dev: true`. A route that acts does it through a
function the factory already has. The questions' answer and resolve
(CF-0652, `shared/needs_you.py`) refuse with `{detail}` (`Problem`; CC-0086:
`code` too where a client acts on it - `no_suggestion`, `check_changed`); the
requests to the operator (CC-0018) with `{detail, code, text_ru}`
(`RequestProblem`, the factory's `RequestError.as_dict()`: 404 `not_found`,
422 the input, 409 a step the state does not allow); the
channel routes (CC-0006) refuse with
`{message, code, details, errors, batches}` (`ChannelProblem`) - `message`
for a human in Russian, `details` the technical lines behind «подробнее»; the
schedule and batch routes (CC-0044) with `{message, code, details}`
(`BatchProblem`).
"""
import hmac
import logging
import secrets
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Union

from fastapi import APIRouter, Body, Depends, FastAPI, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.requests import cookie_parser
from pydantic import BaseModel, ConfigDict, Field, model_validator

from . import auth as auth_mod
from . import (API_VERSION, analytics, batches, channel_lists, channels, dev, ending,
               factory,
               gate_prices,
               maintenance, meme_jobs, memes, notifications, notify_send, oauth, paths, pool,
               publish, publish_net, rights, run_summary, studio_center, studio_entry,
               topics, versions,
               videos, withdrawal)
from . import footage as footage_mod
from . import publish_stash as stash_mod
from . import publish_move as move_mod
from . import card_center as card_mod
from .settings import Settings

SESSION_HEADER = "X-CC-Session"
SAFE_METHODS = ("GET", "HEAD", "OPTIONS")
SECURITY_HEADERS = ((b"x-content-type-options", b"nosniff"), (b"x-frame-options", b"DENY"),
                    (b"referrer-policy", b"same-origin"))
TITLE = "Example command center API"
#: CC-0058: a write refused outside the working factory - the code of the problem
WRITES_CODE = "not_working_factory"
WRITES_STATUS = 409
#: CC-0058: the warnings of `CC_API_WRITES=dev` (at the start and on every write it lets in)
WRITES_LOG = logging.getLogger("api.writes")


# ---------------------------------------------------------------- the models
class Refusal(BaseModel):
    detail: str = Field(description="why, in a line")
    guard: Literal["client", "host", "origin", "session"] = Field(
        description="which check refused")


class Health(BaseModel):
    status: Literal["ok"]
    api: str = Field(description="the version of this contract (info.version)")
    writes: bool = Field(description="CC-0058: the API writes here - the working factory "
                                     "(the main checkout on main, CF-0677) or "
                                     "`CC_API_WRITES=dev`; false: only reading")
    writes_reason: Optional[str] = Field(description="why this is not the working factory, in "
                                                     "Russian (`is_working_factory`); null when "
                                                     "it is - the developer's flag does not "
                                                     "clear it")
    writes_dev: bool = Field(description="the developer's flag `CC_API_WRITES=dev` is on")


class WritesProblem(BaseModel):
    """CC-0058: a write route outside the working factory (409)."""
    message: str = Field(description="«Только смотреть: <reason>» - for a human, shown as is")
    code: Literal["not_working_factory"]
    details: List[str] = Field(description="the reason, the factory root, the flag that would "
                                           "let a development copy write")


AUTH_CODES = ("auth_required", "wrong_password", "locked", "auth_off")


class AuthProblem(BaseModel):
    """CC-0036: the login - 401 `auth_required` (any route, the guard: a client that
    is not this machine without a session), 401 `wrong_password`, 429 `locked`,
    409 `auth_off` (no CC_PASSWORD_HASH)."""
    detail: str = Field(description="why, in Russian - shown as is")
    code: Literal[AUTH_CODES] = Field(description="auth_required: show the login screen; "
                                                  "wrong_password; locked: wait retry_after; "
                                                  "auth_off: the password is not set")
    retry_after: Optional[int] = Field(None, description="locked: seconds until a login is "
                                                         "taken again (the Retry-After header too)")


class AuthState(BaseModel):
    required: bool = Field(description="this client has to log in: a password is set and it "
                                       "is not this machine (127.0.0.1/::1 never logs in)")
    logged_in: bool = Field(description="the request carries a live session cookie")


class LoginIn(BaseModel):
    password: str = Field(min_length=1, max_length=1024)


class LoginResult(BaseModel):
    logged_in: bool = Field(description="true after a login, false after a logout")


class Session(BaseModel):
    token: str = Field(description="the secret of this server process; a new one per start")
    header: str = Field(description=f"the header a POST carries it in ({SESSION_HEADER})")


class FactoryVersion(BaseModel):
    version: Optional[str] = Field(description="the line of README's first heading (runlog)")
    commit: Optional[str] = Field(description="HEAD of the root checkout; null outside git")
    dirty: Optional[bool] = Field(description="tracked files modified; null when unknown")


class AgentPin(BaseModel):
    agent: str
    path: str
    rev: str = Field(description="the pin of agents.lock.json")
    sha: Optional[str] = Field(description="the commit the pin resolves to")
    head: Optional[str] = Field(description="HEAD of the checkout")
    branch: Optional[str]
    ok: bool = Field(description="HEAD is the pin and the tree is clean - what a batch needs")
    why: Optional[str] = Field(description="why not ok")


class CenterVersion(BaseModel):
    version: Optional[str] = Field(description="`version` of frontend/package.json")
    built: bool = Field(description="dist/index.html is there")
    built_at: Optional[str] = Field(description="when index.html was built, UTC ISO")
    dist: str = Field(description="the directory served (CC_FRONTEND_DIST) - relative to the "
                                  "factory root, `.../<its last part>` outside it (CC-0097)")


class Version(BaseModel):
    api: str
    writes: bool = Field(description="as `/health`")
    writes_reason: Optional[str] = Field(description="as `/health`")
    writes_dev: bool = Field(description="as `/health`")
    factory: FactoryVersion
    agents: List[AgentPin]
    agents_error: Optional[str] = Field(description="why there are no pins (no lock...)")
    center: CenterVersion
    # CC-0155 (CF-0841): this process, as it was when it started - `factory.commit`
    # is read from git on every request, these two once, when the app was built
    started_at: Optional[str] = Field(
        None, description="CC-0155: when this API process started (its app was built), "
                          "UTC ISO with Z, e.g. \"2026-10-22T02:15:07Z\"; the same in every "
                          "answer of the process")
    commit_at_start: Optional[str] = Field(
        None, description="CC-0155: HEAD of the root checkout (full sha) when this process "
                          "started - the code it runs; null when the root was no git checkout "
                          "then")
    stale: Optional[bool] = Field(
        None, description="CC-0155: the process runs older code than the root has - code "
                          "(*.py, agents.lock.json) changed between commit_at_start and "
                          "factory.commit (restart cc-api to run the root's code); false when "
                          "the commits are the same or only data changed (the center's own "
                          "writes, a batch's records), null when either commit is unknown or "
                          "the diff failed")
    stale_paths: Optional[List[str]] = Field(
        None, description="CC-0155: the first 10 code paths (relative to the root) changed "
                          "since commit_at_start; [] when stale is false, null when it is null")


# ---------------------------------------------------------------- versions and the agents (CC-0030)
class VersionsFactory(BaseModel):
    """The root checkout (`runlog.readme_version`, `repo_state`, `root_branch_ok`,
    `release_tag`; `agents_lock.versions_in_work`)."""
    version: Optional[str] = Field(description="the version of README's first heading "
                                               "(runlog.readme_version)")
    git: bool = Field(description="the root is a git checkout")
    commit: Optional[str] = Field(description="HEAD of the root")
    branch: Optional[str] = Field(description="the root's branch; null when detached")
    main: Optional[str] = Field(description="the sha `main` of the root is at")
    dirty: Optional[List[str]] = Field(description="modified or staged code files of the root "
                                                   "(records left out, as batch-start does); "
                                                   "null when `git status` failed")
    branch_ok: bool = Field(description="the root may carry a batch: on main or release/* "
                                        "(runlog.root_branch_ok)")
    release_tag: Optional[str] = Field(
        None, description="CC-0119 (CF-0716, runlog.release_tag): the greatest release tag "
                          "vN(.N)* reachable from the branch main - not from HEAD, so every "
                          "checkout of the root answers the same - e.g. \"v2.3.3\"; null when "
                          "there is none (no git, no main, no tag on it)")
    versions_in_work: List[str] = Field(
        default_factory=list,
        description="CC-0119 (CF-0716, agents_lock.versions_in_work): the release/<v> branches "
                    "a live worktree of the root's repo has checked out (a prunable one left "
                    "out), in version order - e.g. [\"release/2.4\"]; [] when none")


class VersionsLock(BaseModel):
    path: str = Field(description="the lock, relative to the root")
    error: Optional[str] = Field(description="why there are no rows (no lock, unreadable)")


class AgentState(BaseModel):
    """One agent of the lock (`agents_lock.status`) and its line of the CLI."""
    agent: str
    path: str = Field(description="relative to the root")
    rev: str = Field(description="the pin of agents.lock.json (a tag, a branch or a sha)")
    sha: Optional[str] = Field(description="the commit the pin resolves to")
    head: Optional[str] = Field(description="the commit checked out")
    branch: Optional[str] = Field(description="null when detached")
    dirty: Optional[List[str]] = Field(description="modified or staged tracked files; null when "
                                                   "`git status` failed")
    ok: bool = Field(description="HEAD is the pin, the tree is clean, the links are sound - what "
                                 "a batch needs")
    why: Optional[str] = Field(description="why not ok, as the factory says it")
    line: Optional[str] = Field(description="its line of `scripts/agents status`, verbatim")
    mark: Optional[Literal["ok", "DIFF", "WARN"]] = Field(description="the line's first word")


class BuildStamp(BaseModel):
    """What `<module>/dist` was built from (`agents_lock.build_stamp`, read, not run)."""
    rev: Optional[str]
    sha: Optional[str]
    contract: Optional[str]
    contract_sha256: Optional[str]
    built_by: Optional[str]


class ModuleState(BaseModel):
    """One module of the lock (`agents_lock.module_status`, CF-0651) - advisory."""
    module: str
    path: str
    rev: str
    sha: Optional[str]
    head: Optional[str]
    branch: Optional[str]
    dirty: Optional[List[str]]
    built: bool = Field(description="built from HEAD under the root's contract")
    api: bool = Field(description="the root has a contract at all")
    ok: bool
    why: Optional[str]
    build: Optional[BuildStamp] = Field(description="the stamp in dist/; null when not built")
    line: Optional[str] = Field(description="its line of `scripts/agents status`, verbatim")
    mark: Optional[Literal["ok", "DIFF", "WARN"]]


class StatusLine(BaseModel):
    text: str = Field(description="the line verbatim (only the factory root's prefix cut)")
    mark: Optional[Literal["ok", "DIFF", "WARN"]] = Field(description="its first word")
    of: Literal["agent", "module", "root"] = Field(description="an agent's row, a module's, or "
                                                               "the root's own (a broken link "
                                                               "of `links.root`, paths not "
                                                               "linked yet)")
    subject: Optional[str] = Field(description="the agent or module; null for a root line")


class AgentsStatus(BaseModel):
    command: str = Field(description="what was run (`scripts/agents status`)")
    exit_code: Optional[int] = Field(description="0 on the lock, 1 a DIFF, 2 a lock error; null "
                                                 "when it did not run")
    ok: bool = Field(description="exit_code is 0")
    lines: List[StatusLine]
    stderr: Optional[str]
    error: Optional[str] = Field(description="why it did not run or answer")


class VersionsCenter(BaseModel):
    version: Optional[str] = Field(description="`version` of frontend/package.json")
    built: bool = Field(description="dist/index.html is there")
    built_at: Optional[str] = Field(description="when index.html was built, UTC ISO")
    dist: Optional[str] = Field(description="the directory served, relative to the root; null "
                                            "outside it")


class Versions(BaseModel):
    checked_at: str = Field(description="when this check ran, UTC ISO")
    cached: bool = Field(description="the kept answer of an earlier request")
    ttl_s: float = Field(description="how long a check is kept; ?fresh=true checks again")
    api: str = Field(description="this contract's version")
    factory: VersionsFactory
    lock: VersionsLock
    agents: List[AgentState]
    modules: List[ModuleState]
    status: AgentsStatus
    center: VersionsCenter


# ---------------------------------------------------------------- development tasks (CC-0124)
class DevChecklistCount(BaseModel):
    done: int = Field(description="`- [x]` lines of the body")
    total: int = Field(description="`- [ ]` and `- [x]` lines of the body (code fences left out)")


class DevTaskRow(BaseModel):
    """A task file's frontmatter (no body) and where it was read."""
    id: str = Field(description="CF-NNNN (the factory) or CC-NNNN (the center)")
    title: Optional[str] = None
    type: Optional[str] = Field(None, description="task, bug, techdebt, ...")
    status: Optional[str] = Field(None, description="open, in-progress, blocked, done, wontfix, ...")
    milestone: Optional[str] = Field(None, description="as the frontmatter says (2.3.1, 0.4, "
                                                       "backlog, hotfix, ...)")
    repo: Optional[str] = Field(None, description="the frontmatter's `repo`; empty or «—» is null")
    created: Optional[str] = None
    closed: Optional[str] = None
    dod: Optional[str] = Field(None, description="the factory's `dod` line")
    blocked_by: List[str] = Field(description="the ids of `blocked_by`, [] when none")
    extra: Dict[str, Optional[str]] = Field(description="any other frontmatter key, as written")
    project: Literal["factory", "center"]
    archived: bool = Field(description="read from tasks/archive/<v>/")
    archive: Optional[str] = Field(None, description="the archive's folder (v2.8, 0.1), null "
                                                     "when not archived")
    path: str = Field(description="the file, relative to its repo")
    branch: str = Field(description="the branch it was read from (main, release/<v>)")
    checklist: DevChecklistCount


class DevSource(BaseModel):
    project: Literal["factory", "center"]
    repo: str = Field(description="the repo read, relative to the factory root (. / frontend)")
    branch: str
    sha: Optional[str] = Field(None, description="the branch's commit; null when not read")
    error: Optional[str] = Field(None, description="why it was not read")


class DevTasks(BaseModel):
    tasks: List[DevTaskRow] = Field(description="the rows that pass the filters - the factory's "
                                                "first, then by id")
    count: int = Field(description="len(tasks)")
    total: int = Field(description="every task of both projects, before the filters")
    sources: List[DevSource] = Field(description="the branches read (main first; a version line "
                                                 "wins over main for a task on both)")


class DevChecklistItem(BaseModel):
    text: str
    done: bool


class DevRelated(BaseModel):
    id: str
    project: Literal["factory", "center"]
    title: Optional[str] = None
    status: Optional[str] = None


class DevCommit(BaseModel):
    sha: str
    date: str = Field(description="committer date, ISO 8601")
    subject: str
    project: Literal["factory", "center"] = Field(description="the repo it is in")


class DevTask(DevTaskRow):
    body: str = Field(description="the markdown after the frontmatter")
    items: List[DevChecklistItem] = Field(description="the checklist lines, in order")
    related: List[DevRelated] = Field(description="the CF-/CC- ids its text names that exist, "
                                                  "first mention first")
    commits: List[DevCommit] = Field(description="commits whose subject names the id (git log "
                                                 "--grep, both repos), newest first, at most 30")


class DevSprint(BaseModel):
    version: Optional[str] = Field(None, description="X.Y.Z of `### X.Y.Z — title`; null for a "
                                                     "heading without one (hotfixes)")
    title: str
    heading: str = Field(description="the whole heading as written")
    done: Optional[str] = Field(None, description="the date of `**DONE YYYY-MM-DD`")
    tasks: List[str] = Field(description="the ids of its tables' rows, in table order")


class DevMilestone(BaseModel):
    version: Optional[str] = Field(None, description="X.Y of `## X.Y — title`; null for a section "
                                                     "without one that has tasks (tooling)")
    title: str
    heading: str
    done: Optional[str] = None
    tasks: List[str] = Field(description="ids in its tables outside any sprint, in table order")
    sprints: List[DevSprint]


class DevRoadmap(BaseModel):
    project: Literal["factory", "center"]
    branch: Optional[str] = Field(None, description="where ROADMAP.md was read")
    sha: Optional[str] = None
    error: Optional[str] = None
    milestones: List[DevMilestone] = Field(description="in the file's order")


class DevRoadmaps(BaseModel):
    roadmaps: List[DevRoadmap] = Field(description="the factory's, then the center's (one with "
                                                   "?project=)")


class DevProblem(BaseModel):
    """A refusal of the development routes - `{message, code, details}`."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["unknown_task", "bad_project"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_DVPROBLEMS = {s: {"model": DevProblem} for s in (404, 422)}


class Question(BaseModel):
    id: str = Field(description="Q<n>, the journal's number")
    n: int
    key: str = Field(description="the event the question is about - one live question per key")
    source: str = Field(description="who asked (publisher-auth, ...)")
    channel: Optional[str]
    text: str
    link: Optional[str] = Field(description="the center's route (a stored link of the retired "
                                            "console, 8790/#anchor, or of the center's old "
                                            "port 8791 converted by notify.center_link, "
                                            "CF-0735, CC-0035)")
    created: Optional[str] = Field(description="UTC ISO")
    created_by: Optional[str]
    updated: Optional[str]
    status: Literal["open", "answered", "resolved"]
    answer: Optional[str]
    answered_by: Optional[str]
    answered_at: Optional[str]
    resolved_by: Optional[str]
    resolved_at: Optional[str]
    note: Optional[str]
    # CC-0086 (CF-0703): the suggested answer and where the answer came from
    suggestion: Optional[str] = Field(None, description="the answer the asker recommends - "
                                                        "shown in the answer box, one press "
                                                        "takes it; null: none")
    suggestion_why: Optional[str] = Field(None, description="why that answer")
    suggested_by: Optional[str] = Field(None, description="who suggested it")
    suggested_at: Optional[str] = Field(None, description="UTC ISO - which suggestion it is: "
                                                          "send it back with `accept`")
    answered_via: Optional[str] = Field(None, description="where the answer came from - "
                                                          "`center` or the source's own name; null "
                                                          "for an answer that did not say")
    accepted_suggestion: bool = Field(False, description="the answer is the suggestion the "
                                                         "question had then")


class Questions(BaseModel):
    status: str = Field(description="the filter asked")
    questions: List[Question]


class AnswerIn(BaseModel):
    text: Optional[str] = Field(None, min_length=1, description="the answer; left out with "
                                                                "`accept`")
    by: str = Field(default="user", description="who answers")
    accept: bool = Field(False, description="CC-0086: the answer is the question's current "
                                            "suggestion - the API reads it fresh, the text is "
                                            "not sent")
    suggested_at: Optional[str] = Field(None, description="with `accept`: the `suggested_at` "
                                                          "of the suggestion the user saw - "
                                                          "another one now is 409 "
                                                          "`check_changed`, nothing written")

    @model_validator(mode="after")
    def _text_or_accept(self):
        if self.accept and self.text is not None:
            raise ValueError("text or accept, not both - accept answers with the suggestion")
        if not self.accept and not (self.text or "").strip():
            raise ValueError("an answer needs a text (or accept: true)")
        return self


#: CC-0086: where an answer given in the center came from (`needs_you.answer` via)
CENTER_VIA = "center"


class ResolveIn(BaseModel):
    note: Optional[str] = Field(default=None, description="how it was resolved")
    by: str = Field(default="user", description="who resolves")


class Problem(BaseModel):
    detail: str
    code: Optional[str] = Field(None, description="CC-0086: `no_suggestion` / `check_changed` "
                                                  "of an accepted suggestion; else absent")


# ---------------------------------------------------------------- requests to the operator (CC-0018)
class RequestNotify(BaseModel):
    """The last Telegram attempt of the answer (`operator_requests`, CF-0684)."""
    status: Literal["sent", "failed"]
    attempt: Optional[int]
    key: Optional[str] = Field(description="the bus key: request:<id>:answer[#again:try<n>]")
    reason: Optional[str] = Field(description="why it failed (the token masked); null when sent")
    backends: Optional[Dict[str, Any]] = Field(description="each backend's result")
    at: Optional[str] = Field(description="UTC ISO")


class OperatorRequest(BaseModel):
    """A request of the user to the operator session (`shared/operator_requests.py`)."""
    id: str = Field(description="R<n>, the journal's number")
    n: int
    text: str = Field(description="the request as written (lines kept)")
    channel: Optional[str] = Field(description="the channel, under its current id")
    context: Optional[Any] = Field(description="what the center kept with it (the screen, "
                                               "channel, video it was asked from) - any JSON")
    created: Optional[str] = Field(description="UTC ISO")
    created_by: Optional[str]
    updated: Optional[str]
    status: Literal["open", "taken", "answered", "closed", "cancelled"] = Field(
        description="open -> taken (the operator's `next`) -> answered (`answer`) -> closed; "
                    "cancelled from open or taken")
    taken_by: Optional[str]
    taken_at: Optional[str]
    answer: Optional[str]
    answered_by: Optional[str]
    answered_at: Optional[str]
    closed_by: Optional[str]
    closed_at: Optional[str]
    cancelled_by: Optional[str]
    cancelled_at: Optional[str]
    notify: Optional[RequestNotify] = Field(description="null before the answer; then the "
                                                        "last Telegram attempt")


class OperatorRequests(BaseModel):
    status: str = Field(description="the filter asked")
    requests: List[OperatorRequest]


class OperatorRequestIn(BaseModel):
    text: str = Field(description="the request; the factory refuses an empty one "
                                  "(`text_empty`) or one over 4000 (`text_too_long`)")
    channel: Optional[str] = Field(default=None, description="the channel it is about")
    context: Optional[Any] = Field(default=None, description="where it was asked from (screen, "
                                                             "channel, video...) - any JSON up "
                                                             "to 4000 (`context_invalid`)")


class RequestProblem(BaseModel):
    """A refusal of `operator_requests` (`RequestError.as_dict()`)."""
    detail: str = Field(description="the factory's English text")
    code: Literal["text_empty", "text_too_long", "answer_empty", "answer_too_long", "by_missing",
                  "context_invalid", "status_unknown", "not_found", "not_taken",
                  "already_answered", "not_answered", "already_closed", "already_cancelled",
                  "cancel_answered", "no_answer", "already_delivered"]
    text_ru: str = Field(description="the line for a human, in Russian (REFUSALS_RU)")


# ---------------------------------------------------------------- channels (CC-0006)
class CheckLine(BaseModel):
    text: str = Field(description="the checker's line, as the factory says it (technical, "
                                  "English - behind «подробнее»)")
    field: Optional[str] = Field(description="the dotted path it names (`video_editor.x`, "
                                             "`run_plan`, `stance.position`); null when none")
    code: Optional[str] = Field(description="CC-0054: the stable reason code of the factory's "
                                            "check (`video_editor_invalid`, `run_plan_invalid`, "
                                            "...; inserts/validate_inserts.py CHECK_REASONS_RU); "
                                            "the position's and the new-channel template's "
                                            "checks too (CC-0056: `stance_invalid`, "
                                            "`stance_unreadable`, `template_has_pipeline`, "
                                            "`template_stance_path`); null only for a new "
                                            "channel's input line")
    text_ru: Optional[str] = Field(description="CC-0054: the line for a human, in Russian, the "
                                               "field and the value put in - the factory's "
                                               "(`check_finding`); a new channel's input line is "
                                               "the factory's Russian as is; null when the "
                                               "factory has no Russian for it (no line the API "
                                               "makes today, CC-0056) - show `text`")


class OpenBatch(BaseModel):
    dir: str
    channel: Optional[str] = Field(description="its channel; null for a rebuild")
    rebuild: bool
    last: Optional[str] = Field(description="its last event, UTC ISO")


class ChannelLock(BaseModel):
    locked: bool = Field(description="a batch of this channel (or a rebuild) is going: no edit "
                                     "- as of `checked_at`")
    message: Optional[str] = Field(description="why, for a human")
    batches: List[OpenBatch]
    checked_at: Optional[str] = Field(None, description="UTC ISO: the moment the scan of the open "
                                                        "batches this says began (CC-0041)")
    age_s: Optional[float] = Field(None, description="seconds since `checked_at` - a read answers "
                                                     "the last known scan, never waits for one")
    checking: bool = Field(False, description="a newer scan is going now - ask again for it; a "
                                              "save / create / revert always scans afresh")


class ChannelProblem(BaseModel):
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["unknown_channel", "not_json", "invalid", "nothing_changed", "batch_running",
                  "conflict", "dirty", "forbidden_change", "no_stance", "unknown_commit",
                  "not_revertible", "not_a_repo", "git_failed"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")
    errors: List[CheckLine] = Field(description="the factory's check lines (code `invalid`)")
    batches: List[OpenBatch] = Field(description="the batches going (code `batch_running`)")


class ChannelSummary(BaseModel):
    id: str
    display_name: Optional[str]
    former_ids: List[str]
    no_pipeline: Optional[str] = Field(description="«конвейера нет...» for a stub channel")
    stance: bool = Field(description="it has a position file")
    locked: bool
    error: Optional[str] = Field(description="the config does not read / is a broken stub")
    revision: Optional[str] = None


class ChannelList(BaseModel):
    channels: List[ChannelSummary]
    checked_at: Optional[str] = Field(None, description="of every `locked`: as ChannelLock")
    age_s: Optional[float] = None
    checking: bool = False


class ConfigField(BaseModel):
    file: Literal["config", "stance"]
    path: List[str]
    kind: Literal["object", "array", "string", "number", "boolean", "null"]
    prose: bool = Field(description="a `note` / `*_note` key: text for a human, read by no stage")
    note: Optional[str] = Field(description="the field's own prose (`<key>_note` beside it, "
                                            "`note` inside an object) - the tooltip")
    checked_by: List[str] = Field(description="the factory's checks of its block")


class ConfigCheck(BaseModel):
    block: Optional[str] = Field(description="the top-level key it reads")
    check: str = Field(description="the factory's function")
    on_stub: bool = Field(description="it runs on a channel with no pipeline too")


class ChannelDetail(BaseModel):
    id: str
    display_name: Optional[str]
    no_pipeline: Optional[str]
    revision: str = Field(description="of both files now - send it back as `base`")
    config: Dict[str, Any]
    config_text: str = Field(description="the file as it is, byte for byte")
    config_path: str
    stance: Optional[Dict[str, Any]]
    stance_text: Optional[str]
    stance_path: Optional[str]
    fields: List[ConfigField]
    checks: List[ConfigCheck]
    errors: List[CheckLine] = Field(description="what the factory's checks say of it now")
    lock: ChannelLock


class ChannelEdit(BaseModel):
    base: Optional[str] = Field(None, description="the `revision` the edit was made on; "
                                                  "another one now -> 409 conflict")
    config_text: Optional[str] = Field(None, description="the whole config, written as sent "
                                                         "(the raw-JSON editor)")
    config: Optional[Dict[str, Any]] = Field(None, description="or as an object, written "
                                                               "indent=2 (when no config_text)")
    stance_text: Optional[str] = None
    stance: Optional[Dict[str, Any]] = None
    note: Optional[str] = Field(None, description="a line for the commit's body")


class CheckResult(BaseModel):
    ok: bool
    errors: List[CheckLine]


class SaveResult(BaseModel):
    commit: str
    subject: str = Field(description="«Канал <имя>: изменено <поле> (из центра)»")
    changed: List[str] = Field(description="the dotted paths that changed")
    files: List[str]
    channel: ChannelDetail


class HistoryEntry(BaseModel):
    commit: str
    short: str
    at: str
    author: str
    subject: str
    action: Optional[Literal["edit", "revert", "create"]] = Field(
        description="a commit of the center")
    reverts: Optional[str] = Field(description="the commit a revert undid")
    files: List[str] = Field(description="every file of the commit")
    from_center: bool
    revertible: bool
    why_not: Optional[str] = Field(description="why it cannot be reverted, for a human")
    reverted_by: Optional[str]


class ChannelHistory(BaseModel):
    id: str
    files: List[str] = Field(description="the files whose commits these are")
    entries: List[HistoryEntry]


class RevertRequest(BaseModel):
    base: Optional[str] = None


# ---------------------------------------------------------------- a new channel (CC-0008)
class TemplateInput(BaseModel):
    name: Literal["channel_id", "display_name", "language"]
    label: str = Field(description="for the form, in Russian")
    required: bool
    default: Optional[str]
    pattern: Optional[str] = Field(description="the factory's regular expression, when it has one")
    note: str = Field(description="what it is and what is refused - the tooltip")


class TemplateFile(BaseModel):
    template: str = Field(description="the template's file in the factory")
    path: str = Field(description="where it goes, `{id}` the channel's id")


class ChannelTemplate(BaseModel):
    inputs: List[TemplateInput]
    files: List[TemplateFile]
    status: Optional[str] = Field(description="the new channel's `status` (no_pipeline)")
    no_pipeline: str = Field(description="«конвейера нет - батча не будет» - what it is")
    batch_schedule: Optional[Dict[str, Any]] = Field(
        description="the new channel's block - `enabled: false`, off the schedule")
    config: Dict[str, Any] = Field(description="the config template, placeholders unfilled")
    lock: ChannelLock = Field(description="a batch is going: no channel can be created now")


class NewChannel(BaseModel):
    channel_id: str
    display_name: str
    language: Optional[str] = Field(None, description="default `en`")
    stance_text: Optional[str] = Field(None, description="the whole position file "
                                       "(`channels/<id>/stance.json`) in place of the template's "
                                       "skeleton - the wizard's thesis, one commit with the "
                                       "channel (CC-0041); checked as a PUT checks it")
    dry_run: bool = Field(False, description="check and show the files, write nothing")


class NewFile(BaseModel):
    path: str
    text: str = Field(description="the file as it would be written")


class CreateResult(BaseModel):
    ok: bool = Field(description="the factory takes it (a dry run may say false)")
    dry_run: bool
    channel_id: Optional[str]
    files: List[NewFile] = Field(description="empty when the inputs are refused")
    errors: List[CheckLine] = Field(description="the inputs' and the checks' lines; field "
                                                "`channel_id` / `display_name` / `language` "
                                                "for an input")
    lock: ChannelLock
    commit: Optional[str] = Field(description="the commit made; null on a dry run")
    subject: Optional[str] = Field(description="«Канал <имя>: создан (из центра)»")
    channel: Optional[ChannelDetail] = Field(description="the channel now; null on a dry run")


_PROBLEMS = {s: {"model": ChannelProblem} for s in (400, 404, 409, 422, 500)}


# ---------------------------------------------------------------- the schedule and batches (CC-0044)
#: CF-0676: the acceptance's refusal codes (`shared/runlog/acceptance.py`
#: `REFUSALS_RU`, `AcceptanceError.code`) - the problem of a refused verdict
#: carries the factory's code as is. tests/test_cc_api_videos.py pins this
#: tuple to the factory's table.
#: CC-0123: the refusals of «повторить со стадии» (CF-0739), each with the center's
#: Russian line (`batches.RERUN_CODES`) - `refused` is already a code, and
#: `resume_failed` is no refusal (a done rerun whose resume did not go: 200).
RERUN_CODES = tuple(c for c in batches.RERUN_CODES if c not in ("refused", "resume_failed"))
#: CC-0123: a refused resume carries the factory's code (CF-0739 RESUME_CODES) -
#: the ones not among the rerun's; `exited_at_once` is no refusal (resumed: 200).
RESUME_CODES = tuple(c for c in batches.RESUME_CODES
                     if c not in RERUN_CODES and c not in ("refused", "exited_at_once"))
ACCEPTANCE_CODES = (
    "acceptance_with_check", "acceptance_with_code", "answer_is_position", "answer_missing",
    "answer_without_name", "channel_unknown", "check_unknown", "cli_commit_needs_write",
    "cli_needs_verdict", "code_shas_broken", "holds_unreadable", "key_malformed",
    "not_a_video_name", "not_committed", "nothing_to_show", "place_not_accepted",
    "place_without_row", "publish_layout_refused", "queue_not_a_verdict", "queue_unreadable",
    "record_not_a_log", "record_outside_repo", "record_unreadable", "rejection_without_code",
    "rejection_without_reason", "render_missing", "topic_mismatch", "topic_not_found",
    "verdict_already_given", "verdict_unknown", "video_not_shown",
)


class BatchProblem(BaseModel):
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal[("unknown_channel", "unknown_batch", "unknown_log", "invalid", "note_required",
                   "refused", "schedule_broken", "scan_broken", "confirm_unknown",
                   "confirm_expired", "confirm_channel", "confirm_mismatch", "check_changed",
                   "busy", "control_broken", "unknown_video", "no_mp4", "no_preview", "no_card",
                   "card_broken", "acceptance_broken", "no_plan", "unknown_topic",
                   "video_refused", "no_score",
                   "stage_broken", "answer_required", "factory_broken", "not_logged_in",
                   *ACCEPTANCE_CODES, *RERUN_CODES, *RESUME_CODES)] = Field(
        description="stable; a refused verdict carries the factory's acceptance code "
                    "(CF-0676: answer_without_name, rejection_without_reason, "
                    "verdict_already_given, ...); a refused rerun its refusal's code "
                    "(CC-0123: executor_alive, stage_not_run, earlier_failed, ...), a "
                    "refused resume the factory's resume code (batch_finished, "
                    "spawn_failed, other_batch_open, ...); CC-0176: not_logged_in - POST "
                    "/batches/launch refused, claude is not logged in (batch_schedule."
                    "login_state ok false), the batch not opened")
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_BPROBLEMS = {s: {"model": BatchProblem} for s in (404, 409, 422, 500)}


class SwitchRow(BaseModel):
    at: Optional[str] = Field(None, description="UTC ISO")
    by: Optional[str] = None
    action: Optional[Literal["enable", "disable"]] = None
    note: Optional[str] = None
    task: Optional[str] = None


class Switch(BaseModel):
    on: bool = Field(description="the tick starts the day's batch by the plan")
    line: str = Field(description="the factory's line, for a human")
    since: Optional[str] = Field(None, description="the last change, UTC ISO")
    by: Optional[str] = None
    note: Optional[str] = None
    history: List[SwitchRow] = Field(description="every change, oldest first")
    error: Optional[str] = Field(None, description="schedule/switch.json does not read (then off)")


class SwitchIn(BaseModel):
    on: bool
    note: Optional[str] = Field(None, description="required to turn it on: where and when the "
                                                  "user said «включай»; written as «центр: <note>»")


class ScheduleSettings(BaseModel):
    enabled: Optional[bool] = Field(None, description="takes part in the schedule")
    window: Optional[str] = Field(None, description="the window's start, HH:MM in `tz`")
    window_hours: Optional[Union[int, float]] = None
    min_feed_days: Optional[int] = Field(
        None, description="CC-0184 (CF-0922): the feed's horizon - how many days ahead a video "
                          "is put into a slot (publish_queue.horizon, 3 by default); no longer "
                          "the batch threshold, that is `batch_feed_days`")
    batch_feed_days: Optional[int] = Field(
        None, description="CC-0184 (CF-0922): the batch threshold in force - the tick starts a "
                          "batch when the feed covers fewer days («лента короче N дн.»). The "
                          "factory's effective value (batch_schedule.channel_settings): the "
                          "channel's own or the center's when set (never below `min_feed_days` "
                          "- the factory refuses that), otherwise its default (14) raised to "
                          "`min_feed_days`. Whether it is set is `overlay` (the center's) or "
                          "`source`; the API does not fill it in - null only with `error`, or "
                          "from a factory that does not know the key")
    tz: Optional[str] = None
    windows: Optional[List[str]] = Field(
        None, description="CC-0152 (CF-0830): the channel's windows of one day, HH:MM in `tz`, "
                          "sorted, 1-4 - they override `window` (then `window` is the first); "
                          "null: one window, `window`, as before")
    source: Optional[str] = Field(None, description="where the values come from, for a human")
    overlay: Dict[str, Any] = Field(default_factory=dict,
                                    description="what the console set (schedule/channel-settings.json)")
    error: Optional[str] = Field(None, description="the settings do not read - the rest is null")


class SettingsRow(BaseModel):
    at: Optional[str] = None
    by: Optional[str] = None
    channel: Optional[str] = None
    changes: Dict[str, List[Any]] = Field(default_factory=dict, description="{key: [old, new]}")
    note: Optional[str] = None
    task: Optional[str] = None


class ChannelSchedule(BaseModel):
    channel: str
    settings: ScheduleSettings
    history: List[SettingsRow] = Field(description="the console's changes, newest first")


class ScheduleSettingsEdit(BaseModel):
    enabled: Optional[bool] = None
    window: Optional[str] = Field(None, description="HH:MM, 00:00-23:59")
    window_hours: Optional[float] = Field(None, description="0.5-24, step 0.25")
    min_feed_days: Optional[float] = Field(None, description="the feed's horizon (CC-0184, "
                                                             "CF-0922): whole days, 1-30 (the "
                                                             "factory refuses a fraction)")
    batch_feed_days: Optional[float] = Field(
        None, description="CC-0184 (CF-0922): the batch threshold - whole days, 1-30 (the "
                          "factory refuses a fraction, 422 invalid), and not below the horizon "
                          "`min_feed_days` in force: the factory refuses that as a whole "
                          "(set_channel_settings -> window_config), 409 refused with its reason "
                          "in `details`. Left out or null: no change, as the other keys")
    windows: Optional[List[str]] = Field(
        None, description="CC-0152 (CF-0830): the channel's windows of one day - 1 to 4 "
                          "\"HH:MM\" (00:00-23:59, two digits each), the factory sorts them and "
                          "drops repeats; they override `window`. Left out: no change; null "
                          "sent explicitly or []: the key is removed (back to the one "
                          "`window`). Checked here (422 invalid) and by the factory "
                          "(batch_schedule.validate_settings); written like the other keys, "
                          "set_channel_settings by user - the CLI's `settings <ch> --windows "
                          "11:30,17:00`")
    note: Optional[str] = Field(None, description="written as «центр: <note>»")


class SettingsResult(ChannelSchedule):
    changed: Dict[str, List[Any]] = Field(description="{key: [old, new]}; empty - nothing changed, "
                                                      "no row written")


# ---------------------------------------------------------------- CF-0822 / CF-0830 (CC-0152)
class PlanBreaker(BaseModel):
    """CC-0152 (CF-0822): the repeat breaker's record of a channel -
    `batch_schedule.breakers`: the channel's last batch of the current quota
    day stopped failed / halted without spending quota. While `held`, the tick
    does not start the channel's next batch in that quota day (new code allows
    one repeat); a manual start is not held."""
    model_config = ConfigDict(extra="allow")
    channel: str = Field(description="the channel id")
    batch: str = Field(description="«<dir>/<batch_id>» of the failed batch")
    status: Optional[str] = Field(None, description="its run-state status: failed | halted")
    stage: Optional[str] = Field(None, description="the stage it stopped on")
    reason: Optional[str] = Field(None, description="why the stage stopped (the handler / "
                                                    "check it names)")
    failure: Optional[str] = Field(None, description="«<stage>: <reason>» as one line")
    quota_day: Optional[str] = Field(None, description="the quota day it holds, YYYY-MM-DD, "
                                                       "America/Los_Angeles")
    until: Optional[str] = Field(None, description="UTC ISO - the quota reset, the end of the "
                                                   "hold")
    held: bool = Field(description="true: the tick does not repeat it (the same code, or the "
                                   "failed batch's code unknown); false: the code changed - "
                                   "one repeat allowed")
    code_source: Optional[str] = Field(None, description="where the failed batch's code was "
                                                         "read: «RUN_EVENTS.jsonl (batch-start)» "
                                                         "or «schedule/launches.jsonl»; null - "
                                                         "unknown")
    code_failed: Dict[str, str] = Field(default_factory=dict,
                                        description="{repo label: short sha} the failed batch "
                                                    "ran on")
    code_now: Dict[str, str] = Field(default_factory=dict,
                                     description="{repo label: short sha} a batch would run on "
                                                 "now")
    code_changed: List[str] = Field(default_factory=list,
                                    description="the repo labels whose code moved since (empty "
                                                "while held)")
    line: Optional[str] = Field(None, description="the factory's Russian line - shown as is")


class BudgetAdmission(BaseModel):
    """CC-0152 (CF-0830): one admission record - `batch_schedule.admission`:
    may the channel (one with `windows`) take a next batch in a quota day that
    already has one, by the YouTube Search budget."""
    model_config = ConfigDict(extra="allow")
    task: Optional[str] = Field(None, description="«CF-0830»")
    channel: str = Field(description="the channel id")
    quota_day: str = Field(description="the quota day, YYYY-MM-DD, America/Los_Angeles")
    window_start: Optional[str] = Field(None, description="UTC ISO of the window asked about; "
                                                          "null - launch_check's now")
    start: Optional[str] = Field(None, description="UTC ISO the batch would start (after the "
                                                   "plan's previous batch)")
    nth: int = Field(description="which batch of the quota day it would be (2: the second)")
    batches: int = Field(description="the quota day's batches so far, the plan's own included")
    max_batches: int = Field(description="the cap of batches a quota day")
    limit: int = Field(description="search.list calls a quota day gives")
    margin: int = Field(description="kept back for a call the record misses")
    spent: int = Field(description="spent so far: recorded + unrecorded guesses + planned")
    spent_recorded: Optional[int] = Field(None, description="what the record says was spent")
    spent_unrecorded: Optional[int] = Field(None, description="the expected spend of counted "
                                                              "batches not on record yet")
    spent_planned: Optional[int] = Field(None, description="the expected spend of the plan's "
                                                           "own earlier batches")
    expected: int = Field(description="the channel's expected spend of a batch")
    expected_n: Optional[int] = Field(None, description="the batches the expectation stands on "
                                                        "(0: the default)")
    expected_line: Optional[str] = Field(None, description="the expectation, for a human")
    after: int = Field(description="spent + expected")
    left: int = Field(description="limit - spent")
    admitted: bool = Field(description="the batch may start (reason ok)")
    reason: Literal["ok", "budget", "max_batches", "busy"] = Field(
        description="ok; budget: after > limit - margin; max_batches: the cap reached; busy: "
                    "the window passes while the plan's previous batch runs")
    why: Optional[str] = Field(None, description="the factory's Russian line - shown as is")


class QuotaBudgetUnrecorded(BaseModel):
    model_config = ConfigDict(extra="allow")
    batch: Optional[str] = Field(None, description="«<dir>/<batch_id>»; null - a launch with no "
                                                   "folder yet")
    channel: Optional[str] = None
    expected: Optional[int] = Field(None, description="the channel's expected spend counted "
                                                      "for it")


class QuotaBudgetDay(BaseModel):
    """CC-0152 (CF-0830): what one quota day already holds of the Search budget
    (`batch_schedule.quota_budget`)."""
    model_config = ConfigDict(extra="allow")
    task: Optional[str] = Field(None, description="«CF-0830»")
    quota_day: str = Field(description="YYYY-MM-DD, America/Los_Angeles")
    limit: int = Field(description="search.list calls a quota day gives")
    margin: int = Field(description="kept back for a call the record misses")
    max_batches: int = Field(description="the cap of batches a quota day")
    batches: int = Field(description="the batches started in it")
    spent: int = Field(description="recorded + the expected spend of the unrecorded ones")
    spent_recorded: int = Field(description="what the record says was spent")
    unrecorded: List[QuotaBudgetUnrecorded] = Field(
        default_factory=list, description="counted batches whose spend is not on record yet")
    left: int = Field(description="limit - spent")
    held: List[str] = Field(default_factory=list, description="the factory's lines of the "
                                                              "batches it holds")


class QuotaBudget(BaseModel):
    """CC-0152 (CF-0830): the plan's `quota_budget` - the budget's values
    (`batch_schedule.QUOTA_BUDGET` + the limit), the current quota day's
    budget and the channels with `windows`."""
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    max_batches: int = Field(description="the cap of batches a quota day")
    margin: int = Field(description="kept back for a call the record misses")
    expected_batches: int = Field(description="how many last batches the expected spend is "
                                              "the median of")
    default_searches: int = Field(description="the expected spend of a channel without a "
                                              "recorded batch")
    note: Optional[str] = Field(None, alias="_note", description="the factory's note on the "
                                                                "values (English)")
    limit: int = Field(description="search.list calls a quota day gives")
    today: Optional[QuotaBudgetDay] = Field(None, description="the current quota day's budget")
    windows_channels: List[str] = Field(default_factory=list,
                                        description="the plannable channels with `windows` - "
                                                    "only they can take a next batch")


class ExpectedSearchesBatch(BaseModel):
    batch: str = Field(description="«<dir>/<batch_id>»")
    searches: int = Field(description="its search.list calls")


class ExpectedSearches(BaseModel):
    """CC-0152 (CF-0830): what the channel's next batch is expected to spend of
    the Search quota (`batch_schedule.expected_searches`)."""
    model_config = ConfigDict(extra="allow")
    channel: str
    searches: int = Field(description="the expected search.list calls")
    n: int = Field(description="the batches it stands on (0: the default)")
    batches: List[ExpectedSearchesBatch] = Field(default_factory=list,
                                                 description="those batches, oldest first")
    source: Literal["median", "default"] = Field(description="median of the last batches, or "
                                                             "the default without one")
    line: Optional[str] = Field(None, description="the factory's Russian line")


class PlanChannel(BaseModel):
    plannable: bool
    why_not: Optional[str] = Field(None, description="why the plan skips it, for a human")
    no_pipeline: Optional[bool] = None
    slot_rule: Optional[str] = None
    window: Optional[str] = None
    window_source: Optional[str] = None
    min_feed_days: Optional[int] = Field(None, description="CC-0184 (CF-0922): the feed's horizon")
    batch_feed_days: Optional[int] = Field(
        None, description="CC-0184 (CF-0922): the batch threshold in force (the factory's "
                          "effective value, as `settings.batch_feed_days`) - the plan wants a "
                          "batch when the feed covers fewer days; null from a factory that does "
                          "not know the key")
    est_wall_s: Optional[float] = Field(None, description="an estimate - the mean of the last runs")
    est_wall_n: Optional[int] = Field(None, description="the runs it stands on (0: the default)")
    est_videos: Optional[int] = None
    est_videos_n: Optional[int] = None
    queue: Optional[int] = None
    pending: Optional[int] = None
    open: List[str] = Field(default_factory=list, description="its batches going now")
    settings: ScheduleSettings
    windows: Optional[List[str]] = Field(
        None, description="CC-0152 (CF-0830): its windows of a day, HH:MM (then `window` names "
                          "them all); null: one window")
    expected_searches: Optional[ExpectedSearches] = Field(
        None, description="CC-0152 (CF-0830): its next batch's expected Search spend; null for "
                          "a channel the plan skips")
    breaker: Optional[PlanBreaker] = Field(
        None, description="CC-0152 (CF-0822): the repeat breaker's record of the channel; null "
                          "- none")


class PlanMoreBatch(BaseModel):
    """CC-0152 (CF-0830): a further batch of a planned day - a channel with
    `windows` admitted by the Search budget after the day's batch: the fields
    of a planned day (needs_batch) without `day` / `notes`, plus its
    `budget_admission`. It carries no `more` of its own."""
    model_config = ConfigDict(extra="allow")
    channel: str
    status: Literal["planned"] = "planned"
    kind: Literal["needs_batch"] = "needs_batch"
    why: Optional[str] = Field(None, description="for a human")
    window_start: Optional[str] = Field(None, description="UTC ISO - its window's start")
    window_end: Optional[str] = Field(None, description="UTC ISO - its window's end")
    quota_day: Optional[str] = Field(None, description="the quota day of window_start")
    est_end: Optional[str] = None
    est_wall_s: Optional[float] = None
    est_wall_n: Optional[int] = None
    est_videos: Optional[int] = None
    est_videos_n: Optional[int] = None
    fills: List[str] = Field(default_factory=list, description="the slots the batch fills, UTC ISO")
    covers_days: List[str] = Field(default_factory=list, description="the slot days its videos "
                                                                     "land on")
    first_empty_slot: Optional[str] = None
    budget_admission: Optional[BudgetAdmission] = Field(
        None, description="the admission that let it in (reason ok)")


class PlanDay(BaseModel):
    day: str = Field(description="the Moscow day, YYYY-MM-DD")
    channel: Optional[str] = None
    status: Literal["planned", "idle", "busy", "done"]
    why: Optional[str] = Field(None, description="for a human")
    notes: List[str] = Field(default_factory=list)
    window_start: Optional[str] = Field(None, description="UTC ISO: the batch's window on "
                                                          "needs_batch; CC-0152 (CF-0822): the "
                                                          "held channel's window on a breaker day")
    window_end: Optional[str] = Field(None, description="UTC ISO: the window's end (needs_batch, "
                                                        "a breaker day)")
    est_end: Optional[str] = None
    est_wall_s: Optional[float] = None
    est_wall_n: Optional[int] = None
    est_videos: Optional[int] = None
    est_videos_n: Optional[int] = None
    fills: List[str] = Field(default_factory=list, description="the slots the batch fills, UTC ISO")
    kind: Literal["running", "done_today", "quota_day_taken", "nobody_plannable",
                  "nobody_available", "fed", "needs_batch"] = Field(
        description="CC-0147 (CF-0785, CF-0787): the day's structured reason, next to `why` (for "
                    "a human) - one per branch of `batch_schedule.plan`, its DAY_KINDS: running "
                    "(today, busy: a batch is open), done_today (today, done: a batch of the "
                    "factory already started in the current quota day - Pacific midnight to "
                    "Pacific midnight - and no window of today lies past its reset), "
                    "quota_day_taken (done when a batch that spent quota started in that quota "
                    "day, idle when an earlier day of this plan takes it: every window of the day "
                    "that needs a batch falls in a quota day that already has its batch; "
                    "`quota_day` names it, `next_windows` gives each blocked channel's next "
                    "window), nobody_plannable (idle: no channel has a slot and a run_plan, notes "
                    "empty), nobody_available (idle: each plannable channel's window is gone or "
                    "it is paused, notes say which), fed (idle: every feed reaches its batch_feed_days - "
                    "CC-0184, CF-0922: the batch threshold, not the horizon min_feed_days), "
                    "needs_batch (planned: the day's batch). Every day carries it; read it, not "
                    "a prefix of `why`")
    quota_day: Optional[str] = Field(
        None,
        description="CC-0147 (CF-0787): the YouTube Search quota day (YYYY-MM-DD, "
                    "America/Los_Angeles - the plan's `quota_tz`) the day is about: on "
                    "done_today the current quota day that already has its batch, on "
                    "quota_day_taken the taken quota day of the first blocked window, on "
                    "needs_batch the quota day of the batch's window_start; null on running, "
                    "nobody_plannable, nobody_available and fed")
    next_windows: Dict[str, Optional[str]] = Field(
        default_factory=dict,
        description="CC-0147 (CF-0787), quota_day_taken only: channel -> UTC ISO start of its "
                    "next possible window (the first window after this day whose quota day has "
                    "no batch yet, within the factory's NEXT_WINDOW_DAYS), null when there is "
                    "none in that range - one entry per blocked channel; {} on every other kind")
    covers_days: List[str] = Field(
        default_factory=list,
        description="CC-0147 (CF-0785), needs_batch only: the slot days (YYYY-MM-DD in the "
                    "channel's slot time zone) this batch's videos land on - the days of `fills`, "
                    "ascending, no repeats; empty when no slot after the batch's end is free in "
                    "the horizon, and on every other kind")
    first_empty_slot: Optional[str] = Field(
        None,
        description="CC-0147 (CF-0785), needs_batch only: UTC ISO of the feed's first empty slot "
                    "from the window's start, before the batch - what makes this the batch's day; "
                    "not fills[0], which est_end + lead can push later; null when no slot in the "
                    "horizon is empty, and on every other kind")
    breaker: Optional[PlanBreaker] = Field(
        None,
        description="CC-0152 (CF-0822): the day is held by the repeat breaker - kind stays "
                    "nobody_available (no new kind), status idle; the record of the first held "
                    "channel, its window in window_start / window_end, next_windows {channel: "
                    "UTC ISO | null} per held channel; null on every other day")
    budget: List[BudgetAdmission] = Field(
        default_factory=list,
        description="CC-0152 (CF-0830): every admission the day's planning asked for (channels "
                    "with `windows` in a quota day that already has a batch), admitted or not; "
                    "[] when none")
    budget_admission: Optional[BudgetAdmission] = Field(
        None, description="CC-0152 (CF-0830), needs_batch: the admission that let the day's "
                          "batch in (a second batch of its quota day); null - an ordinary batch")
    more: List[PlanMoreBatch] = Field(
        default_factory=list,
        description="CC-0152 (CF-0830), needs_batch: the further batches of the same day, "
                    "after the day's batch (channels with `windows`, admitted by the budget), "
                    "in order; [] when none")


class SchedulePlan(BaseModel):
    now: str
    today: str = Field(description="the Moscow day of `now`, YYYY-MM-DD - the plan's days are "
                                   "Moscow days")
    quota_day: str = Field(description="CC-0147 (CF-0787): the YouTube Search quota day of "
                                       "`now`, YYYY-MM-DD in `quota_tz` - the factory's batch "
                                       "day (one batch per quota day)")
    quota_tz: str = Field(description="CC-0147 (CF-0787): the quota day's time zone, "
                                      "«America/Los_Angeles» (the quota resets at Pacific "
                                      "midnight)")
    per_day: int = Field(description="batches a day for the whole factory")
    switch: Switch
    stale_open: List[str] = Field(description="open batches past the freshness cap - «<channel> <id>»")
    channels: Dict[str, PlanChannel]
    days: List[PlanDay]
    breakers: Dict[str, PlanBreaker] = Field(
        default_factory=dict,
        description="CC-0152 (CF-0822): channel -> the repeat breaker's record (held or not) - "
                    "every channel whose last batch of the current quota day failed without "
                    "spending quota; {} when none")
    quota_budget: Optional[QuotaBudget] = Field(
        None, description="CC-0152 (CF-0830): the Search budget - its values, the current "
                          "quota day's budget, the channels with `windows`; null from an older "
                          "factory")
    timer: str = Field(description="the tick's timer (launchd, macOS), the factory's line")


class Launch(BaseModel):
    """A row of schedule/launches.jsonl, every key kept. `kind`: none - the
    tick's batch; manual, resume, rebuild; CC-0152 (CF-0822): repeat_held - the
    tick did NOT start the channel's batch, the repeat breaker held it (not a
    batch of the day, nothing started, pid null; with quota_day, failed_batch,
    failure, until)."""
    model_config = ConfigDict(extra="allow")
    at: Optional[str] = None
    day: Optional[str] = Field(None, description="the Moscow day")
    channel: Optional[str] = None
    by: Optional[str] = Field(None, description="`tick`, `user (центр)` for the center's "
                                                "button (`user (пульт)` in rows of the "
                                                "retired 2.2 console)")
    kind: Optional[str] = Field(None, description="null: the tick's batch; manual | resume | "
                                                  "rebuild | repeat_held (CF-0822: held, "
                                                  "nothing started)")
    why: Optional[str] = None
    pid: Optional[int] = Field(None, description="the started process; null on repeat_held")
    task: Optional[str] = None
    code: Optional[Dict[str, str]] = Field(
        None, description="CC-0152 (CF-0822): {repo label: commit} the launch started on (the "
                          "tick and the button write it); null in older rows")
    budget: Optional[BudgetAdmission] = Field(
        None, description="CC-0152 (CF-0830): the admission of a batch started as a next batch "
                          "of its quota day by the Search budget; null otherwise")
    quota_day: Optional[str] = Field(None, description="CC-0152 (CF-0822), repeat_held: the "
                                                       "quota day held")
    failed_batch: Optional[str] = Field(None, description="CC-0152 (CF-0822), repeat_held: "
                                                          "«<dir>/<batch_id>» of the failure")
    failure: Optional[str] = Field(None, description="CC-0152 (CF-0822), repeat_held: "
                                                     "«<stage>: <reason>»")
    until: Optional[str] = Field(None, description="CC-0152 (CF-0822), repeat_held: UTC ISO "
                                                   "of the quota reset, the end of the hold")
    auto: Optional[str] = Field(None, description="CC-0176 (CF-0899), resume: the tick resumed "
                                                  "a batch halted on NOT_LOGGED_IN by itself - "
                                                  "the factory's line «NOT_LOGGED_IN на "
                                                  "<stage>, <login line>»; null in other rows")


class BatchRun(BaseModel):
    model_config = ConfigDict(extra="allow")
    batch: Optional[str] = Field(None, description="«<channel>/<batch_id>» - the stages' path")
    id: Optional[str] = None
    channel: Optional[str] = None
    date: Optional[str] = None
    started: Optional[str] = None
    ended: Optional[str] = None
    videos: Optional[int] = None
    wall_s: Optional[float] = None
    outcome: Optional[str] = None
    launch: Optional[Launch] = Field(None, description="the schedule's launch of its channel and "
                                                       "day; null - started by hand in chat")


class BatchHistory(BaseModel):
    channel: Optional[str]
    runs: List[BatchRun] = Field(description="pipeline/runs.jsonl, newest first; every key of a row")
    launches: List[Launch] = Field(description="schedule/launches.jsonl, newest first")


class StrandedStage(BaseModel):
    id: Optional[str] = None
    status: Optional[str] = Field(None, description="run-state.json `stages[id].status` "
                                                    "(pending when it has none)")
    reason: Optional[str] = None


class StrandedBatch(BaseModel):
    """CC-0114: one row of `batch_schedule.stranded_batches` (CF-0723) as is,
    plus `batch`, `log_name` and `log_url`."""
    model_config = ConfigDict(extra="allow")
    batch: Optional[str] = Field(None, description="«<dir>/<batch_id>» - the path of "
                                                   "/api/batches/{channel}/{batch_id} (as "
                                                   "GoingBatch.batch); `rebuilds/<ts>` for a "
                                                   "rebuild")
    dir: str = Field(description="the batch folder, relative to the factory root "
                                 "(`pipeline/<channel>/<batch_id>`, `pipeline/rebuilds/<ts>`)")
    channel: Optional[str] = Field(None, description="its channel, under the current id")
    batch_id: str
    status: Optional[str] = Field(None, description="run-state.json: failed, halted, stopped")
    created: Optional[str] = None
    updated: Optional[str] = None
    stage: Optional[str] = Field(None, description="where it stopped")
    reason: Optional[str] = Field(None, description="that stage's reason, else the halt's, "
                                                    "else the stop's")
    log: Optional[str] = Field(None, description="the stage's step log, else the executor's "
                                                 "log of its launch - relative to the root")
    log_name: Optional[str] = Field(None, description="the `{name}` to pass to GET "
                                                      ".../batches/{channel}/{batch_id}/logs/"
                                                      "{name}; null when that route serves no "
                                                      "log of it")
    log_url: Optional[str] = Field(None, description="GET .../batches/{channel}/{batch_id}/"
                                                     "logs/{name} of `log` when that route "
                                                     "serves it (`<dir>/logs/*.log`); null: "
                                                     "no route (a launch's log, none)")
    halt_reason: Optional[str] = None
    stages: List[StrandedStage] = Field(default_factory=list,
                                        description="in the run plan's order")
    holds_day: bool = Field(description="what `started_on` counts for today (Moscow): a "
                                        "channel's batch of today that spent quota; never a "
                                        "rebuild")


class StrandedBatches(BaseModel):
    batches: List[StrandedBatch] = Field(description="the factory's selection in its order, "
                                                     "the channel's only, the first `limit`")
    as_of: str = Field(description="UTC ISO - the `now` the factory selected by")
    error: Optional[str] = Field(None, description="the factory's read failed - its exception; "
                                                   "`batches` empty")


class BatchMarker(BaseModel):
    ts: Optional[str] = None
    marker: Optional[str] = Field(None, description="batch-start | stage-start | stage-done | batch-done")
    stage: Optional[str] = None
    note: Optional[str] = None


class StageSpan(BaseModel):
    stage: Optional[str]
    started: Optional[str]
    done: Optional[str]
    open: bool
    duration_s: Optional[float]


class LogFile(BaseModel):
    name: str
    size: int
    modified: str


class BatchStages(BaseModel):
    batch: str
    channel: str
    batch_id: str
    markers: List[BatchMarker]
    stages: List[StageSpan]
    open_stages: List[Optional[str]]
    closed: bool = Field(description="closed by the factory's rule (runlog._batch_open, CF-0739): a batch-done not followed by a stage-start left open or a new batch-start; a rebuild - no stage-start left open; no markers - false")
    open_why: Optional[str] = Field(None, description="CC-0123: the factory's line why it is open («нет batch-done», «снова открыт после batch-done: стадия X начата и не закрыта (CF-0739)»), null when closed")
    logs: List[LogFile] = Field(description="<batch>/logs/*.log")


class RunSummaryFile(BaseModel):
    name: str = Field(description="RUN_SUMMARY.md")
    size: int
    modified: str
    text: str = Field(description="the Markdown batch-done wrote, as it is")


class BatchRunSummary(BaseModel):
    """CC-0099: what `runlog summary` gives for a batch - `summary.compute`
    (`--json`) and the RUN_SUMMARY.md batch-done wrote. Neither missing is an
    error: `data_note` / `file_note` say «ещё нет»."""
    batch: str
    channel: str
    batch_id: str
    file: Optional[RunSummaryFile] = Field(description="RUN_SUMMARY.md; null - not written yet")
    file_note: Optional[str] = Field(description="why there is no file (Russian)")
    data: Optional[Dict[str, Any]] = Field(
        description="summary.compute - the sections as `runlog summary --json` prints them "
                    "(batch, header, times, gaps, waits, operator, tokens, windows, resources, "
                    "funnel, scores, stopcock, monitors, ...); null - no events yet or it failed")
    data_note: Optional[str] = Field(description="why there is no data yet (Russian)")
    data_error: Optional[str] = Field(description="compute failed - the factory's error")
    computed_at: Optional[str] = Field(description="when `data` was computed (UTC)")
    cached: bool = Field(description="the batch did not change since - the kept result")
    poll_s: int = Field(description="poll a batch going no faster than this, seconds")
    funnel_reasons_ru: Dict[str, Optional[str]] = Field({}, description="CC-0113 (CF-0714): "
                                                        "every code `data.funnel` names (losses, "
                                                        "unknown_codes, its rows' reason_code) -> "
                                                        "funnel.reason_ru; null outside the "
                                                        "vocabulary. Every row of `data.funnel` "
                                                        "with a `reason_code` carries `reason_ru` "
                                                        "beside it")


class FootageTopic(BaseModel):
    """CC-0119: one topic's row of `footage_progress` (CF-0715)."""
    topic_id: str
    state: str = Field(description="queued | collecting | collected | short | refused | stopped "
                                   "(footage_progress.STATES; another value is shown as is)")
    state_ru: Optional[str] = Field(None, description="the state in Russian, as the factory "
                                                      "words it; null for a state it does not know")
    collected: Optional[int] = Field(None, description="canonical sources held (an upper bound "
                                                       "while the journal is the source)")
    needed: Optional[int] = Field(None, description="canonical sources the topic walks to")
    attempts: Optional[int] = Field(None, description="distinct candidates spent (CF-0129)")
    last_video: Optional[str] = Field(None, description="the candidate the walk took last")
    usable_shots: Optional[float] = Field(None, description="CF-0304 depth, once 01b has it")
    floor: Optional[float] = Field(None, description="CF-0304 depth floor")
    indexed_at: Optional[str] = Field(None, description="01b pool_depth.topics[].indexed_at "
                                                        "(UTC, Z)")
    reason_code: Optional[str] = Field(None, description="the funnel's code (canonical_code)")
    reason: Optional[str] = Field(None, description="its Russian line (funnel.reason_ru); null "
                                                    "for a code outside the vocabulary")
    reason_ru: Optional[str] = Field(None, description="CC-0113: = `reason` (the factory's "
                                                       "funnel.reason_ru) under the name every "
                                                       "other code of the API uses; null - no "
                                                       "code, or one outside the vocabulary")
    updated_at: Optional[str] = Field(None, description="the row's last change (UTC, Z)")


class BatchFootage(BaseModel):
    """CC-0119: the Footage Indexer's collection per topic -
    `shared/runlog/footage_progress.footage_progress(<batch>)` (CF-0715), kept
    per state of the progress file, the 01b report and RUN_EVENTS.jsonl."""
    batch: str = Field(description="<channel>/<batch_id>")
    channel: str
    batch_id: str
    source: Literal["file", "events", "report", "none"] = Field(
        description="file: <batch>/work/footage-progress.json; events: RUN_EVENTS.jsonl (a "
                    "batch of FI 2.3.2 and older, no progress file); report: 01b alone; "
                    "none: nothing yet, topics []")
    file: Optional[str] = Field(None, description="the progress file, relative to the batch")
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    finished: bool = Field(description="the 01b report settled the topics")
    running: Optional[bool] = Field(None, description="the last ingest run is open; null - "
                                                      "unknown (no run in the journal)")
    needed: Optional[int] = Field(None, description="canonical sources a topic walks to")
    topics: List[FootageTopic] = Field(description="in Trend Hunter's order")
    counts: Dict[str, int] = Field(description="{state: topics}")
    error: Optional[str] = Field(None, description="the progress file does not read (the answer "
                                                   "fell back to the journal), or the read failed")
    cached: bool = Field(description="none of the files changed since - the kept answer")
    poll_s: int = Field(description="poll a batch going no faster than this, seconds")


class LogTail(BaseModel):
    name: str
    size: int = Field(description="the file's size, bytes")
    offset: int = Field(description="where `text` begins")
    truncated: bool
    text: str


# ---------------------------------------------------------------- the topics (CC-0091)
class StageFile(BaseModel):
    stage: str = Field(description="the stage's id as the run plan names it")
    name: str = Field(description="in Russian")
    file: str = Field(description="its file in the batch directory")
    present: bool = Field(description="false: the stage has not written it yet")
    written_at: Optional[str] = Field(description="the file's mtime, UTC ISO")


#: CC-0113 (CF-0714): the one description of `reason_ru` beside a `reason_code`
_REASON_RU = ("CC-0113: the code in Russian - the factory's funnel.reason_ru (CF-0714, "
              "REASONS_RU by the code's current name); null for no code or one outside the "
              "funnel's vocabulary (show the code as it is)")

#: CC-0169 (CF-0846): `content_sensitivity_check.scenes` - which scenes of the
#: topic a content-sensitivity flag rests on.
SensitivityScenes = Optional[Union[List[str], Literal["whole_topic"]]]
_SCENES = ("CC-0169 (CF-0846): content_sensitivity_check.scenes - the topic's scene ids the "
           "flag rests on (and nothing else of the topic), or \"whole_topic\" (the topic as "
           "such, or the reading cannot say; also a damaged value - null, [], a stray value - "
           "as the factory's sensitivity_scenes.flagged_scenes reads it, fail closed); null: no "
           "check or a row written before CF-0846 (reads as the whole topic)")


class RepairCode(BaseModel):
    """CC-0171: the 06 row's gate, code and score line before / after the repair."""
    gate: Optional[str] = Field(None, description="pass | reject | incomplete")
    reason_code: Optional[str] = None
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    score_line: Optional[str] = None


class RepairBlock(BaseModel):
    """CC-0171 (CF-0881): one block the repair redid - `06 -> repairs[].blocks[]`."""
    block: Optional[int] = Field(None, description="the plan's block index (plan.json "
                                                   "blocks[i])")
    entry: Optional[str] = Field(None, description="the judge's entry: `block-14`, "
                                                   "`block-5-meme`")
    target: Optional[str] = Field(None, description="shot | meme")
    kind: Optional[str] = Field(None, description="the defect: thin_strip | smeared | "
                                                  "cut_subject | wrong_person | "
                                                  "foreign_in_hook | foreign_share")
    why: Optional[str] = Field(None, description="the judge's words about the block")


class VideoRepair(BaseModel):
    """CC-0171 (CF-0881): the one repair pass of a video the frame judge refused
    for a defect in one or two blocks - its record of `06 -> repairs[]` as
    `funnel.judge_repairs` reads it."""
    outcome: Optional[Literal["repaired", "repair_failed"]] = Field(
        None, description="repaired: re-rendered and judged ready, its 06 row replaced; "
                          "repair_failed: the refusal stands")
    reason: Optional[str] = Field(None, description="why it failed (the Editor's outcome or "
                                                    "the judge's reason); null when repaired")
    at: Optional[str] = Field(None, description="when the repair was recorded, UTC ISO Z")
    blocks: List[RepairBlock] = Field([], description="the blocks it set out to redo (<= 2)")
    before: Optional[RepairCode] = Field(None, description="the refused row")
    after: Optional[RepairCode] = Field(None, description="the row judged after the re-render; "
                                                          "null when it was not judged")
    editor_outcome: Optional[str] = Field(None, description="the Editor's: rendered | "
                                                            "no_replacement | render_failed | "
                                                            "qc_failed | failed | not_attempted")
    changed_blocks: List[int] = Field([], description="every plan block whose picture "
                                                      "changed (the judge looked at these again)")


class BatchRepairs(BaseModel):
    """CC-0171 (CF-0881): the counts of `06 -> repairs[]`."""
    repaired: int
    repair_failed: int
    videos: int = Field(description="videos with a repair record")


class RefillCompliance(BaseModel):
    """CC-0171 (CF-0882): the compliance check on the fly."""
    outcome: Optional[str] = Field(None, description="eligible | refused | not_judged")
    verdict: Optional[str] = None
    reason_code: Optional[str] = Field(None, description="02 refill_refused[] reason_code")
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    reason: Optional[str] = None


class RefillFootage(BaseModel):
    """CC-0171 (CF-0882): the Trend Hunter's facet run (01 below_shortlist_refill[])."""
    outcome: Optional[str] = Field(None, description="candidates | refused | quota | error | "
                                                     "not_walked")
    searches: Optional[int] = Field(None, description="search.list calls it spent")
    at: Optional[str] = None
    reason: Optional[str] = Field(None, description="the walk's line; refused: why the sieve "
                                                    "refused (skipped_topics[].refill_reason)")


class TopicRefill(BaseModel):
    """CC-0171 (CF-0882): what the refill from below the shortlist did with the topic."""
    outcome: str = Field(description="admitted (02 reserve[] row marked refill) | promoted "
                                     "(in 01 topics[], not admitted) | refused | quota | "
                                     "error | not_walked | eligible (passed, not walked) | "
                                     "not_judged | considered")
    round: Optional[str] = Field(None, description="first | late | judge")
    promoted: bool = Field(description="moved into 01 topics[] (`refill` mark)")
    restored: Optional[bool] = Field(None, description="topics[].refill.restored: rebuilt from "
                                                       "the row's summary, not its whole topic")
    admitted: bool = Field(description="a 02 reserve[] row with the `refill` mark")
    refused_by: Optional[Literal["compliance", "trend_hunter"]] = None
    reason: Optional[str] = Field(None, description="why it was refused (or not walked)")
    compliance: Optional[RefillCompliance] = None
    footage: Optional[RefillFootage] = None


class RefillJudged(BaseModel):
    topic_id: Optional[str] = None
    verdict: Optional[str] = None
    outcome: Optional[str] = None
    reason: Optional[str] = None


class RefillWalked(BaseModel):
    topic_id: Optional[str] = None
    outcome: Optional[str] = None
    searches: Optional[int] = None
    reason: Optional[str] = None


class RefillRound(BaseModel):
    """CC-0171 (CF-0882): one round of the refill from below the shortlist - CC-0173:
    the funnel's `below_shortlist_refill.rounds[]` (the root's record joined
    with 01 below_shortlist_refill[] and 02 refill_refused[] by `round`)."""
    round: Optional[str] = Field(None, description="first | late | judge")
    at: Optional[str] = None
    at_code: Optional[str] = None
    need: Optional[int] = Field(None, description="slots the round was to fill")
    need_why: Optional[str] = None
    outcome: Optional[str] = Field(None, description="admitted | not_needed | queue_empty | "
                                                     "search_quota | seam_failed | "
                                                     "none_eligible | no_pool")
    outcome_ru: Optional[str] = Field(None, description="CC-0173 (CF-0888): the factory's "
                                                        "Russian line of the outcome "
                                                        "(funnel.REFILL_OUTCOMES_RU); null "
                                                        "for an outcome outside it")
    why: Optional[str] = None
    queue: List[str] = Field([], description="the unspent below_shortlist topics, by rank")
    judged: List[RefillJudged] = []
    footage: List[RefillWalked] = []
    admitted: List[str] = Field([], description="topic ids admitted into 02 reserve[]")
    searches: int = Field(0, description="search.list calls the round spent")
    spent_after: Optional[int] = Field(None, description="the quota day's spend after it")
    budget_line: Optional[str] = None


class BatchRefill(BaseModel):
    """CC-0171 (CF-0882): the refill from below the shortlist."""
    record: str = Field(description="work/below-shortlist-refill.json")
    rounds: List[RefillRound]
    admitted: int = Field(description="topics admitted, all rounds")
    searches: int = Field(description="searches spent, all rounds")


class TopicState(BaseModel):
    phase: Literal["in_work", "stalled", "reserve", "dropped", "done"] = Field(
        description="in_work: waits for `stage` while the batch goes; stalled: the batch is "
                    "not going and the topic did not get to the end")
    stage: str = Field(description="the stage the line is about")
    line: str = Field(description="one Russian line - «в работе: футаж», «отсеяна: нет "
                                  "факта», «в резерве», «ролик готов»")
    reason_code: Optional[str] = Field(None, description="the stage's code, as written")
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)


class TopicSource(BaseModel):
    url: str
    title: Optional[str] = None
    publication: Optional[str] = None
    published_at: Optional[str] = None


class TopicCompliance(BaseModel):
    verdict: Optional[str] = Field(description="02 results[] / reserve[] verdict")
    place: Literal["batch", "reserve", "refused", "not_judged"] = Field(
        description="carried into the batch, held in reserve[], a verdict it does not go on "
                    "with, or no row at all")
    reason_code: Optional[str] = None
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    reason: Optional[str] = None
    rights_reason: Optional[str] = None
    rights_matched: Optional[bool] = None
    sensitivity_flagged: Optional[bool] = None
    sensitivity_notes: Optional[str] = None
    sensitivity_scenes: SensitivityScenes = Field(None, description=_SCENES)


class TopicPool(BaseModel):
    rule: Optional[str] = None
    sources: Optional[float] = None
    shots: Optional[float] = None
    retired: Optional[float] = None
    usable: Optional[float] = None
    floor: Optional[float] = None
    measured: Optional[bool] = None
    coverage: Optional[float] = None
    coverage_by: Optional[str] = None
    error: Optional[str] = None
    deep_enough: Optional[bool] = Field(None, description="usable >= floor")


class TopicDepth(BaseModel):
    sources: Optional[float] = None
    shots: Optional[float] = None
    usable_shots: Optional[float] = None
    weak_shots: Optional[float] = None
    available_shots: Optional[float] = None
    usable_seconds: Optional[float] = None
    floor: Optional[float] = None
    deep_enough: Optional[bool] = None
    measured: Optional[bool] = None
    at_source_floor: Optional[bool] = None
    exhausted: Optional[Union[str, bool]] = None
    attempts: Optional[float] = None
    error: Optional[str] = None
    indexed_at: Optional[str] = Field(None, description="CF-0715: when the indexer measured the "
                                                        "topic (UTC, Z); null in a batch before "
                                                        "2.4")


class TopicReason(BaseModel):
    reason_code: Optional[str] = None
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    reason: Optional[str] = None


class TopicIndexer(BaseModel):
    indexed_at: Optional[str] = Field(description="when 01b was written (no per-topic time)")
    registered_sources: Optional[int] = Field(description="01b sources_by_topic")
    depth: Optional[TopicDepth] = Field(description="01b pool_depth.topics[]")
    thin: bool = Field(description="in 01b pool_depth.thin[]")
    failed_downloads: int
    skipped: Optional[TopicReason] = Field(description="01b skipped_topics[]")
    warnings: List[str] = Field(description="01b warnings[].warning_code")
    substituted: bool = Field(description="a reserve topic the indexer put into a free slot")
    substitution: Optional[TopicReason] = None


class TopicFootage(BaseModel):
    pool: Optional[TopicPool] = Field(description="the Trend Hunter's measure (topics[].pool)")
    indexer: Optional[TopicIndexer] = Field(description="null: 01b not written yet")


class ScriptCompliance(BaseModel):
    verdict: Optional[str] = None
    contribution: Optional[str] = Field(None, description="contribution_check.verdict "
                                                          "(pass|block)")
    passes: Optional[bool] = None


class ScriptVideo(BaseModel):
    slug: Optional[str] = Field(description="the stem of the video; null - not built")
    qc_passed: Optional[bool] = None
    needs_you: bool = False
    score_line: Optional[str] = None
    refused: Optional[TopicReason] = Field(None, description="05 refusals[]")


class ScriptFrame(BaseModel):
    gate: Optional[str] = Field(description="pass | reject | incomplete; null - no row")
    reason_code: Optional[str] = None
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    reason: Optional[str] = None
    score_line: Optional[str] = None
    repair: Optional[VideoRepair] = Field(None, description="CC-0171 (CF-0881): its repair "
                                                            "pass after the judge; null: none")


class TopicScript(BaseModel):
    script_id: Optional[str] = None
    scene_id: Optional[str] = None
    hook: Optional[str] = None
    duration_s: Optional[float] = None
    compliance: Optional[ScriptCompliance] = Field(description="null: 04 not written yet")
    video: Optional[ScriptVideo] = Field(description="null: 05 not written yet")
    frame: Optional[ScriptFrame] = Field(description="null: 06 not written (or no video)")


class TopicSummary(BaseModel):
    topic_id: Optional[str] = None
    rank: int = Field(description="its place in the shortlist, from 1")
    title: Optional[str] = Field(description="title_ref.name")
    kind: Optional[str] = None
    type: Optional[str] = None
    year: Optional[Union[str, int]] = None
    popularity_score: Optional[float] = Field(description="signal.popularity_score")
    sources: List[TopicSource] = Field(description="evidence.sources[], then rss_links")
    scenes: int
    has_fact: Optional[bool] = Field(description="fact_probe.has_fact")
    compliance: Optional[TopicCompliance] = Field(description="null: 02 not written yet")
    footage: TopicFootage
    scripts: Optional[List[TopicScript]] = Field(description="null: 03 not written yet")
    state: TopicState
    refill: Optional[TopicRefill] = Field(None, description="CC-0171 (CF-0882): a topic the "
                                                            "refill from below the shortlist "
                                                            "touched; null: none")


class SkippedTopic(BaseModel):
    topic_id: Optional[str] = None
    title: Optional[str] = None
    kind: Optional[str] = None
    popularity_score: Optional[float] = None
    reason_code: Optional[str] = None
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    reason: Optional[str] = None
    stage: Optional[str] = None
    state: TopicState
    refill: Optional[TopicRefill] = Field(None, description="CC-0171 (CF-0882): what the "
                                                            "refill did with it; null: none")


class TopicCut(BaseModel):
    cut_at: Optional[str] = None
    shortlist_size: Optional[int] = None
    judged: Optional[int] = None
    eligible: Optional[int] = None
    carried: Optional[int] = None
    reserve: Optional[int] = None
    refused: Optional[int] = None
    held: Optional[int] = None
    target: Optional[int] = None
    target_from: Optional[str] = None
    reason_code: Optional[str] = None
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    pass_verdicts: Optional[List[str]] = None
    production_verdicts: Optional[List[str]] = None
    publish_verdicts: Optional[List[str]] = None


class ShortlistCompliance(BaseModel):
    checked_at: Optional[str] = None
    disclaimer: Optional[str] = None
    cut: Optional[TopicCut] = None


class Selection(BaseModel):
    stage: Optional[str] = None
    shortlist_size: Optional[int] = None
    scored: Optional[int] = None
    viable: Optional[int] = None
    carried: Optional[int] = None


class QuotaArticle(BaseModel):
    search_calls: Optional[float] = None
    api_units: Optional[float] = None
    what: Optional[str] = None


class SearchQuota(BaseModel):
    task: Optional[str] = None
    daily_limit_searches: Optional[float] = None
    units_per_search: Optional[float] = None
    resets_at: Optional[str] = None
    searches_before_stage: Optional[float] = None
    spent_searches: Optional[float] = Field(None, description="the search.list calls the "
                                                              "batch spent")
    spent_units: Optional[float] = None
    remaining_searches: Optional[float] = None
    remaining_units: Optional[float] = None
    spent_api_units: Optional[float] = None
    spent_units_all: Optional[float] = None
    substitutions_made: Optional[float] = None
    substitutions_affordable: Optional[float] = None
    summary_line: Optional[str] = None
    searches_by_topic: Optional[Dict[str, float]] = None
    api_units_by_key: Optional[Dict[str, float]] = None
    by_article: Optional[Dict[str, QuotaArticle]] = None


class TopicCounts(BaseModel):
    topics: int
    skipped: int
    in_work: int
    stalled: int
    reserve: int
    dropped: int
    done: int


class BatchTopics(BaseModel):
    batch: str
    channel: str
    batch_id: str
    going: bool = Field(description="run-state status new/running (not closed)")
    closed: bool
    status: Optional[str] = Field(description="run-state.json status")
    files: List[StageFile] = Field(description="every stage's file, written or not yet")
    trend_hunter_done: bool = Field(description="01-trend-hunter.json is written")
    generated_at: Optional[str] = None
    language: Optional[str] = None
    sources_used: List[str]
    selection: Optional[Selection] = None
    compliance: Optional[ShortlistCompliance] = Field(description="null: 02 not written yet")
    search_quota: Optional[SearchQuota] = Field(description="01 search_quota; null: none")
    repairs: Optional[BatchRepairs] = Field(None, description="CC-0171 (CF-0881): 06 "
                                                              "repairs[] counts; null: no pass")
    refill: Optional[BatchRefill] = Field(None, description="CC-0171 (CF-0882): the refill's "
                                                            "rounds; null: none ran")
    counts: TopicCounts
    topics: List[TopicSummary] = Field(description="01 topics[] (the shortlist), in order")
    skipped: List[SkippedTopic] = Field(description="01 skipped_topics[]")


class TitleRef(BaseModel):
    name: Optional[str] = None
    kind: Optional[str] = None
    type: Optional[str] = None
    year: Optional[Union[str, int]] = None
    season: Optional[Union[str, int]] = None
    network: Optional[str] = None
    parent_work: Optional[str] = None
    person: Optional[str] = None
    rights_holder: Optional[str] = None


class TopicScene(BaseModel):
    scene_id: Optional[str] = None
    description: Optional[str] = None
    tags: List[str]
    source_url: Optional[str] = None


class TopicVideo(BaseModel):
    video_id: Optional[str] = None
    url: Optional[str] = None
    title: Optional[str] = None
    channel_title: Optional[str] = None
    kind: Optional[str] = None
    nature: Optional[str] = None
    view_count: Optional[float] = None
    duration_seconds: Optional[float] = None


class FactProbe(BaseModel):
    outcome: Optional[str] = None
    has_fact: Optional[bool] = None
    usable: Optional[bool] = None
    article: Optional[str] = None
    article_url: Optional[str] = None
    source: Optional[str] = None
    candidates: Optional[float] = None
    detail: Optional[str] = None
    asked_at: Optional[str] = None


class FactFailureRu(BaseModel):
    code: str = Field(description="a `fact_rule.FAIL_CODES` code, as in `failures`")
    ru: Optional[str] = Field(None, description="CC-0119 (CF-0752): "
                              "`fact_rule_ru.reason_ru(code)` - the reason in Russian; "
                              "null for a code the factory has no word for")


class FactCandidate(BaseModel):
    text: Optional[str] = None
    kind: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    section: Optional[str] = None
    passes: Optional[bool] = None
    failures: List[str]
    failures_ru: List[FactFailureRu] = Field(
        default_factory=list, description="CC-0119: `{code, ru}` parallel to `failures` "
        "(same order, same length); `ru` null - the reason has no description")
    scenes: List[str]


class FactSearch(BaseModel):
    found: Optional[float] = None
    passing: Optional[float] = None
    error: Optional[str] = None


class SupportText(BaseModel):
    id: Optional[str] = None
    kind: Optional[str] = None
    source: Optional[str] = None
    title: Optional[str] = None
    url: Optional[str] = None


class SupportCheck(BaseModel):
    state: Optional[str] = None
    detail: Optional[str] = None
    pieces: Optional[float] = None
    texts: List[SupportText] = Field(description="support_text[] without the text")


class ChosenFact(BaseModel):
    script_id: Optional[str] = None
    text: Optional[str] = None
    kind: Optional[str] = None
    source: Optional[str] = None
    url: Optional[str] = None
    primary_url: Optional[str] = None
    section: Optional[str] = None


class TopicFact(BaseModel):
    probe: Optional[FactProbe] = Field(description="fact_probe")
    candidates: List[FactCandidate] = Field(description="fact_candidates[] with check.passes")
    search: Optional[FactSearch] = Field(description="fact_search")
    support: Optional[SupportCheck] = Field(description="support_check + support_text")
    chosen: List[ChosenFact] = Field(description="03 scripts[].fact - the fact a script took")


class BatchTopic(BaseModel):
    batch: str
    channel: str
    batch_id: str
    topic_id: str
    going: bool
    searches: Dict[str, float] = Field(description="search_quota.searches_by_topic of it "
                                                   "(and its `supplement:` key)")
    shortlisted: bool = Field(description="in topics[]; false - in skipped_topics[]")
    summary: Optional[TopicSummary] = Field(description="its row of /topics; null if skipped")
    skipped: Optional[SkippedTopic] = None
    title_ref: TitleRef
    scenes: List[TopicScene]
    sources: List[TopicSource]
    videos: List[TopicVideo] = Field(description="evidence.footage_candidates[]")
    fact: TopicFact


# ---------------------------------------------------------------- the batches going (CC-0045)
class GoingStage(BaseModel):
    id: Optional[str] = None
    status: Optional[str] = None
    reason: Optional[str] = Field(None, description="CC-0110: run-state.json `stages[id].reason` "
                                                    "- the executor's line («after failed stage "
                                                    "…», «step 0 (…) exited 2; log …»); null: "
                                                    "none")


_EXECUTOR_ALIVE = ("CC-0110: batch_control.executor_of `alive` - what resume/plan and stop/plan "
                   "answer as `executor_alive`; null: the check raised (see `executor_why`)")
_LOCK_HELD = ("CC-0110: batch_control.executor_of `lock_held` - some process holds "
              "run-executor.lock (the executor, or an unknown holder: CF-0667)")
_EXECUTOR_WHY = ("CC-0110: executor_lock.why of the lock's holder while it is held - the "
                 "factory's line (the executor alive, pid; or an unknown holder); null: nobody "
                 "holds it")


class Estimate(BaseModel):
    mean_wall_s: int = Field(description="the mean wall of the channel's last runs (runs.jsonl)")
    runs: int = Field(description="how many runs the mean is of")
    left_s: int = Field(description="mean_wall_s - elapsed_s, as of `as_of`: an estimate, "
                                    "negative past the mean")


class GoingBatch(BaseModel):
    """`collect._batch` - what the console shows of an open batch."""
    model_config = ConfigDict(extra="allow")
    batch: str = Field(description="«<dir>/<batch_id>» - the path of /api/batches/{channel}/"
                                   "{batch_id}; `rebuilds/<ts>` for a rebuild")
    dir: str = Field(description="relative to the factory root")
    batch_id: str
    fresh: bool = Field(description="its last event is within the sampler's cap (24 h) - what "
                                    "`runlog batch-active` counts; false: open but stale")
    last_event: Optional[str] = None
    channel: Optional[str] = Field(None, description="its channel, under the current id")
    source: Optional[str] = Field(None, description="run-state.json or the markers")
    status: Optional[str] = Field(None, description="the executor's: running, paused, halted, "
                                                    "stopped (CF-0667), failed, done, ...")
    stages: Optional[List[GoingStage]] = None
    next: Optional[str] = None
    needs_human: Optional[List[str]] = None
    halt_reason: Optional[str] = None
    state_error: Optional[str] = None
    started: Optional[str] = None
    stage: Optional[str] = Field(None, description="the stage going now")
    stage_started: Optional[str] = None
    elapsed_s: Optional[int] = Field(None, description="since the batch began, as of `as_of`")
    stage_elapsed_s: Optional[int] = None
    stage_timeout_min: Optional[float] = Field(None, description="the stage's ceiling in the "
                                                                 "run plan (`timeout_min`)")
    estimate: Optional[Estimate] = None
    executor_alive: Optional[bool] = Field(None, description=_EXECUTOR_ALIVE + " - as of the "
                                           "scan (`checked_at`)")
    lock_held: Optional[bool] = Field(None, description=_LOCK_HELD)
    executor_why: Optional[str] = Field(None, description=_EXECUTOR_WHY)
    open_why: Optional[str] = Field(None, description="CC-0123: why runlog.open_batches holds "
                                                      "it open (OpenRow.why - «нет batch-done», "
                                                      "«снова открыт после batch-done: …» "
                                                      "CF-0739, the executor alive)")
    code_edits: Optional[List[str]] = Field(None, description="CC-0111 (CF-0713): a line per "
                                            "stage that changed the factory's tracked code - "
                                            "the console's (collect: «<stage>: <repo>: "
                                            "<files>»), or from the `stage_code_edit` events "
                                            "when the state has no key («<stage>: "
                                            "stage_code_guard.describe»); [] or null: none")
    code_edits_count: int = Field(0, description="CC-0111: how many such rows - the flag of "
                                                 "the list and the home page («стадия правила "
                                                 "код фабрики», the next batch-start refuses)")


class BatchesGoing(BaseModel):
    batches: List[GoingBatch]
    as_of: Optional[str] = Field(description="UTC ISO: the moment the times were computed")
    checked_at: Optional[str] = Field(description="UTC ISO: the moment this scan began")
    age_s: float = Field(description="seconds since `checked_at` - a read answers the last "
                                     "scan, never waits for one (past the very first)")
    checking: bool = Field(description="a newer scan is going now")
    poll_s: int = Field(description="the recommended interval to ask again, seconds")


# ---------------------------------------------------------------- the launch (CC-0046)
class LaunchPlanIn(BaseModel):
    channel: str


class LaunchGuard(BaseModel):
    name: str = Field(description="channel, run_plan, voice (CF-0659: the channel's "
                                  "`voice_profile` is a TODO placeholder - refused), open, "
                                  "today, pause")
    ok: bool
    line: str = Field(description="the factory's line, in Russian - shown as is")
    batches: Optional[List[str]] = Field(None, description="CC-0110: «<dir>/<batch_id>» of the "
                                         "batches the guard is about. `open`: every fresh open "
                                         "batch (batch_schedule.open_batches, the call the "
                                         "guard decides by); `today`: launch_check's own list "
                                         "(CF-0724, started_on records -> started_batches; [] "
                                         "when none, a launch without its folder yet names "
                                         "none); another guard: what launch_check's row "
                                         "carries as `batches`, null when it carries none. The "
                                         "line is never parsed")


class LoginState(BaseModel):
    """CC-0176 (CF-0899): is `claude` logged in - the factory's
    `batch_schedule.login_state`, the tick's own check before it opens a batch
    (`claude auth status --json`, no tokens)."""
    ok: Optional[bool] = Field(None, description="true: logged in; false: not - the launch is "
                                                 "refused not_logged_in; null: unknown (no "
                                                 "binary, a timeout, an answer that says "
                                                 "neither, a root that is not the factory's) - "
                                                 "holds nothing, the launch goes on and `line` "
                                                 "is a warning")
    checked: bool = Field(False, description="`claude auth status` was asked")
    line: str = Field(description="the factory's line, in Russian - shown as is")


class LaunchPlan(BaseModel):
    channel: str
    ok: bool = Field(description="every guard holds - the batch would start")
    why: str = Field(description="the first failing guard's line, or «все защиты пройдены»")
    guards: List[LaunchGuard]
    argv: Optional[List[str]] = Field(None, description="what would be started, detached")
    today: str = Field(description="the Moscow day")
    quota_day: str = Field(description="CC-0147 (CF-0787): the YouTube Search quota day of the "
                                       "check, YYYY-MM-DD, America/Los_Angeles - the `today` "
                                       "guard asks whether a batch already started in it")
    skipped: List[str] = Field(description="the tick's checks a manual start does not make "
                                           "(CC-0152: the repeat breaker's line when it holds "
                                           "the channel - a manual start is not held)")
    breaker: Optional[PlanBreaker] = Field(
        None, description="CC-0152 (CF-0822): the channel's repeat breaker record; it never "
                          "refuses a manual start (held: a line in `skipped`); null - none")
    budget: Optional[BudgetAdmission] = Field(
        None, description="CC-0152 (CF-0830): a channel with `windows` in a quota day that "
                          "already has a batch - the admission the `today` guard decides by "
                          "(admitted: the guard holds); null otherwise")
    login: Optional[LoginState] = Field(
        None, description="CC-0176 (CF-0899): claude logged in now - told, never a guard and "
                          "not in the fingerprint (the token is the guards'); ok false: the "
                          "launch will be refused not_logged_in unless claude is logged in by "
                          "then; null in an older answer")
    fingerprint: str = Field(description="sha256 of the check - the token is bound to it")
    confirm: Optional[str] = Field(None, description="the confirm token of `POST "
                                                     "/batches/launch` - only when ok; single use")
    expires_in_s: Optional[int] = Field(None, description="the token lives this long")


class LaunchIn(BaseModel):
    channel: str
    confirm: str = Field(description="the plan's `confirm`")


class LaunchResult(BaseModel):
    ok: bool
    line: str = Field(description="the factory's line, in Russian")
    channel: str
    pid: Optional[int] = None
    log: Optional[str] = Field(None, description="the executor's output, schedule/logs/")
    row: Launch = Field(description="the row written to schedule/launches.jsonl")
    login: Optional[LoginState] = Field(
        None, description="CC-0176 (CF-0899): the login check made before the start - ok true, "
                          "or null (unknown: started anyway, `login.line` is the warning to "
                          "show); ok false never comes here (409 not_logged_in); null in an "
                          "older answer")


# ---------------------------------------------------------------- stop and resume (CC-0047)
class ControlStep(BaseModel):
    """The step the run is on (`batch_control.step_of`)."""
    model_config = ConfigDict(extra="allow")
    stage: Optional[str] = None
    run: Optional[str] = Field(None, description="its key in run-state.json `runs`")
    pid: Optional[int] = None
    pgid: Optional[int] = None
    alive: bool = False
    exit: Optional[int] = None
    log: Optional[str] = None


class ControlCheck(BaseModel):
    """`batch_control.stop_check` / `resume_check` - as the factory says it."""
    model_config = ConfigDict(extra="allow")
    action: Literal["stop", "resume"]
    ok: bool = Field(description="the action would be done")
    reason: str = Field(description="the factory's line, in Russian - shown as is")
    batch: str = Field(description="the batch directory")
    batch_id: str
    channel: Optional[str] = None
    status: Optional[str] = Field(None, description="run-state.json `status`")
    stage: Optional[str] = None
    executor_pid: Optional[int] = None
    executor_pgid: Optional[int] = None
    executor_alive: bool = False
    lock_held: bool = False
    step: Optional[ControlStep] = None
    posix: bool = Field(description="process groups here (CF-0654); without them both refuse")


class StopPlanIn(BaseModel):
    also_step: bool = Field(False, description="stop the step being run too (SIGTERM to its "
                                               "group; the resume starts it again)")


class StopPlan(ControlCheck):
    also_step: bool
    fingerprint: str = Field(description="sha256 of the check - the token is bound to it")
    confirm: Optional[str] = Field(None, description="the confirm token of `POST .../stop` - "
                                                     "only when ok; single use")
    expires_in_s: Optional[int] = Field(None, description="the token lives this long")


class StopIn(BaseModel):
    confirm: str = Field(description="the plan's `confirm`")
    also_step: Optional[bool] = Field(None, description="must be the plan's; none: the plan's")


class StopRow(BaseModel):
    """The row the stop wrote to run-state.json `stops`."""
    model_config = ConfigDict(extra="allow")
    at: Optional[str] = None
    by: Optional[str] = None
    executor_pid: Optional[int] = None
    previous_status: Optional[str] = None
    stage: Optional[str] = None
    also_step: Optional[bool] = None


class StopResult(ControlCheck):
    by: str
    also_step: bool
    stopped: bool = Field(description="run-state.json now says `stopped`")
    executor_signalled: Optional[str] = Field(None, description="whom SIGTERM went to")
    step_killed: bool
    step_left_running: bool = Field(description="the step lives on - the resume waits for it")
    stop: Optional[StopRow] = None
    resume_hint: Optional[str] = Field(None, description="the CLI line of the resume")
    reason_step: Optional[str] = Field(None, description="the step's line when it was not "
                                                         "stopped as asked")


_RESUME_CODE = Literal[tuple(batches.RESUME_CODES)]
_RESUME_CODE_DOC = ("the factory's refusal code (CF-0739 RESUME_CODES; refused from a factory "
                    "without codes); null when ok")


class ResumePlan(ControlCheck):
    code: Optional[_RESUME_CODE] = Field(None, description=_RESUME_CODE_DOC)
    message: str = Field("", description="the center's Russian line for the code (when ok: the "
                                         "factory's reason)")
    root: Optional[str] = None
    argv: Optional[List[str]] = Field(None, description="what would be started, detached")
    fingerprint: str = Field(description="sha256 of the check - the token is bound to it")
    confirm: Optional[str] = Field(None, description="the confirm token of `POST .../resume` - "
                                                     "only when ok; single use")
    expires_in_s: Optional[int] = Field(None, description="the token lives this long")


class ResumeIn(BaseModel):
    confirm: str = Field(description="the plan's `confirm`")


class ResumeResult(ControlCheck):
    code: Optional[_RESUME_CODE] = Field(None, description="exited_at_once when the executor "
                                                           "ended at once with a bad code; null "
                                                           "when ok")
    message: str = Field("", description="the center's Russian line for the code (when ok: the "
                                         "factory's reason)")
    by: str
    resumed: bool = Field(description="the executor was started")
    pid: Optional[int] = None
    log: Optional[str] = Field(None, description="the executor's output, schedule/logs/")
    row: Optional[Launch] = Field(None, description="the schedule/launches.jsonl row, "
                                                    "`kind: resume`")
    exit: Optional[int] = Field(None, description="its code when it ended before taking the lock")


# ---------------------------------------------------------------- rerun from a stage (CC-0123)
_RERUN_CODE = Literal[tuple(batches.RERUN_CODES)]


class RerunStage(BaseModel):
    """A stage «повторить со стадии» could start from."""
    stage: str = Field(description="a stage of run-state.json `order`")
    status: str = Field(description="run-state.json `stages[id].status` (pending when none)")
    can: bool = Field(description="rerun_from_check of this stage says ok now")
    why: str = Field(description="the factory's line, in Russian - shown as is")
    code: Optional[_RERUN_CODE] = Field(None, description="the refusal's code; null when can")


class RerunFromStages(BaseModel):
    """`GET .../rerun-from`: what the screen can offer - read only."""
    batch: str
    channel: Optional[str] = None
    batch_id: str
    status: Optional[str] = Field(None, description="run-state.json `status`")
    has_state: bool = Field(description="the batch has run-state.json (an executor's batch)")
    executor_alive: Optional[bool] = Field(None, description=_EXECUTOR_ALIVE)
    lock_held: Optional[bool] = Field(None, description=_LOCK_HELD)
    executor_why: Optional[str] = Field(None, description=_EXECUTOR_WHY)
    stages_for_rerun: List[RerunStage]


class RerunKept(BaseModel):
    path: str = Field(description="relative to the batch - stays on disk, the rerun overwrites it")
    stage: str = Field(description="the reset stage (or its handler) that wrote it")


class RerunFromCheck(BaseModel):
    """`batch_control.rerun_from_check` (CF-0739) - as the factory says it, with
    the refusal's code and the center's Russian line."""
    model_config = ConfigDict(extra="allow")
    action: Literal["rerun-from"]
    task: Optional[str] = Field(None, description="CF-0739")
    ok: bool = Field(description="the rerun would be done")
    reason: str = Field(description="the factory's line, in Russian - shown as is")
    code: Optional[_RERUN_CODE] = Field(None, description="the refusal's code; null when ok")
    message: str = Field(description="the center's Russian line for the code (when ok: what "
                                     "the rerun does)")
    batch: str = Field(description="the batch directory")
    batch_id: str
    channel: Optional[str] = None
    status: Optional[str] = Field(None, description="run-state.json `status`")
    stage: Optional[str] = Field(None, description="run-state.json `current.stage`")
    from_stage: Optional[str] = Field(None, description="the stage asked")
    executor_pid: Optional[int] = None
    executor_pgid: Optional[int] = None
    executor_alive: bool = False
    lock_held: bool = False
    step: Optional[ControlStep] = None
    posix: bool = Field(description="process groups here (CF-0654); without them it refuses")
    reset: List[str] = Field(description="the stages back to pending: from the stage to the end "
                                         "of the plan, `always` ones too")
    reset_status: Dict[str, str] = Field(description="each reset stage's status before")
    keys: Dict[str, List[str]] = Field(description="the run-state.json records removed: runs, "
                                                   "reruns, handlers, decisions, code_guard")
    logs: List[str] = Field(description="the step logs the rerun overwrites")
    kept: List[RerunKept] = Field(description="files the reset stages wrote - not deleted")
    lines: List[str] = Field(description="the plan for the screen, in Russian")
    root: Optional[str] = None


class RerunFromPlanIn(BaseModel):
    stage: str = Field(min_length=1, max_length=200, description="the stage to rerun from - "
                                                                 "a stage of the plan's order")


class RerunFromPlan(RerunFromCheck):
    why: str = Field(description="the factory's line (= reason)")
    stages_for_rerun: List[RerunStage] = Field(description="as GET .../rerun-from")
    fingerprint: str = Field(description="sha256 of the check - the token is bound to it")
    confirm: Optional[str] = Field(None, description="the confirm token of `POST .../rerun-from` "
                                                     "- only when ok; single use, the stage bound")
    expires_in_s: Optional[int] = Field(None, description="the token lives this long")


class RerunFromIn(BaseModel):
    confirm: str = Field(description="the plan's `confirm` (the stage is the token's)")
    note: Optional[str] = Field(None, max_length=500, description="why - one line, into "
                                                                  "manual_resets `why` and the "
                                                                  "journal")
    resume: bool = Field(False, description="start the executor right after (the factory's "
                                            "resume: run_executor --resume, detached)")


class RerunResetRow(BaseModel):
    """The row written to run-state.json `manual_resets`."""
    model_config = ConfigDict(extra="allow")
    at: Optional[str] = None
    by: Optional[str] = None
    via: Optional[str] = None
    task: Optional[str] = None
    reset: Optional[List[str]] = None
    previous_status: Optional[str] = None
    backup: Optional[str] = None
    why: Optional[str] = None


class RerunFromResult(RerunFromCheck):
    by: str = Field(description="user")
    via: str = Field(description="center")
    note: Optional[str] = None
    done: bool = Field(description="run-state.json was reset (status stopped, next the stage)")
    backup: Optional[str] = Field(None, description="run-state.before-rerun-<ts>.json")
    row: Optional[RerunResetRow] = None
    resume: Optional[Dict[str, Any]] = Field(None, description="the factory's resume dict "
                                                               "after it, when asked (as "
                                                               "ResumeResult; pid/log/exit "
                                                               "lifted out)")
    resume_asked: bool
    resumed: bool = Field(description="an executor was started after the reset")
    pid: Optional[int] = Field(None, description="the started executor's pid")
    log: Optional[str] = Field(None, description="its output, schedule/logs/")
    exit: Optional[int] = Field(None, description="its code when it ended before taking the lock")
    resume_ok: Optional[bool] = Field(None, description="null when no resume was asked")
    resume_code: Optional[_RESUME_CODE] = Field(None, description="the resume's code when it "
                                                                  "did not go (code "
                                                                  "resume_failed); null when "
                                                                  "it went or was not asked")
    resume_reason: Optional[str] = Field(None, description="the resume's line, in Russian")


# ---------------------------------------------------------------- seconds -> blocks (CC-0049)
class BlockNear(BaseModel):
    model_config = ConfigDict(extra="allow")
    block: int = Field(description="the neighbouring block (the second is within 0.5 s of the "
                                   "cut to it)")
    exclude: Optional[str] = Field(None, description="its `BLOCK=SOURCE:SHOT`, or null where the "
                                                     "editor would refuse it")


class BlockMoment(BaseModel):
    model_config = ConfigDict(extra="allow")
    at: float = Field(description="the second asked")
    block: Optional[int] = Field(None, description="the storyboard block (plan block N), null in "
                                                   "the ending or past the end")
    window: Optional[List[float]] = Field(None, description="[start, end] of that block (or the "
                                                            "ending), seconds")
    kind: Optional[str] = Field(None, description="clip, still, sequence, split, card, end_card")
    shots: List[str] = Field(description="`SOURCE:SHOT` on screen at that moment")
    ending: bool = Field(description="inside the channel's end card")
    exclude: Optional[str] = Field(None, description="`BLOCK=SOURCE:SHOT` for that moment, null "
                                                     "where the editor would refuse (`note`)")
    near: List[BlockNear] = Field(description="the neighbour block when the second is near a "
                                              "cut - not in the top-level `exclude`, offered")
    note: Optional[str] = Field(None, description="why there is nothing to exclude (Russian); "
                                                  "absent where there is an exclusion")


class VideoBlocks(BaseModel):
    """`batch_control.blocks_at` (CF-0669) - as the factory says it."""
    model_config = ConfigDict(extra="allow")
    ok: bool
    reason: str = Field(description="the factory's line (Russian)")
    batch: str = Field(description="the batch directory, the factory's")
    slug: str = Field(description="the video's slug (a script id asked: resolved)")
    plan: Optional[str] = Field(None, description="the `work/<slug>/plan.json` read")
    duration: Optional[float] = Field(None, description="the video's length with the ending, s")
    moments: List[BlockMoment] = Field(description="one per second asked, in order")
    exclude: List[str] = Field(description="the distinct `BLOCK=SOURCE:SHOT` in order - as is "
                                           "into `rebuild/plan` `notes.videos[slug].exclude`")


# ---------------------------------------------------------------- the rebuild (CC-0048)
class RebuildMode(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str = Field(description="`reedit`, `rewrite`, ... - the key of `run_plan.rebuild.modes`")
    title: str = Field(description="the plan's title of the mode")
    from_stage: Optional[str] = Field(None, description="the stage it starts at")
    doc: Optional[str] = None


class RebuildSourceVideo(BaseModel):
    """CC-0116: a video of the batch a rebuild can name - `batch_control.
    _source_videos` (CF-0727)."""
    model_config = ConfigDict(extra="allow")
    slug: Optional[str] = None
    script_id: str
    topic_id: Optional[Union[str, int]] = None
    refused: Optional[str] = Field(None, description="refused after the render: the gate (05 "
                                                     "`refusals[]`); null for a video of "
                                                     "`videos[]`")
    plan: bool = Field(False, description="`work/<slug>/plan.json` is there - a reedit has "
                                          "something to start from")


class RebuildModes(BaseModel):
    batch: str = Field(description="«<dir>/<batch_id>»")
    channel: Optional[str] = None
    batch_id: str
    modes: List[RebuildMode]
    reason: Optional[str] = Field(None, description="why there are none (Russian), else null")
    seconds_to_blocks: bool = Field(description="the factory turns seconds of the video into "
                                                "storyboard blocks (CF-0669 blocks_at): `GET "
                                                ".../videos/{slug}/blocks?at=` answers it; the "
                                                "notes' exclusions stay block numbers")
    videos: List[RebuildSourceVideo] = Field([], description="CC-0116: the batch's videos a "
                                                             "plan can name - the refused "
                                                             "after the render too")


class RebuildVideoNote(BaseModel):
    exclude: Optional[Union[List[Union[str, int]], str, int]] = Field(
        None, description="frames to exclude (reedit only): `BLOCK` or `BLOCK=SOURCE:SHOT`, "
                          "the block a number of the video's storyboard")
    note: Optional[str] = None


class RebuildNotes(BaseModel):
    text: Optional[str] = Field(None, description="a note on the whole rebuild")
    videos: Optional[Dict[str, Union[str, RebuildVideoNote]]] = Field(
        None, description="per video (slug or script_id): a note, or {exclude, note}")


class RebuildPlanIn(BaseModel):
    videos: List[str] = Field(description="slugs or script_ids of the batch's 05")
    mode: str = Field(description="a mode of `GET .../rebuild/modes`")
    notes: Optional[Union[str, RebuildNotes]] = None


class RebuildVideo(BaseModel):
    model_config = ConfigDict(extra="allow")
    slug: Optional[str] = None
    script_id: str
    topic_id: Optional[Union[str, int]] = None
    refused: Optional[str] = Field(None, description="CC-0116 (CF-0727): refused after the "
                                                     "render - the gate; null for a video of "
                                                     "`videos[]`")
    plan: Optional[bool] = Field(None, description="`work/<slug>/plan.json` is there")
    exclude: List[str] = []
    note: str = ""


class RebuildLayout(BaseModel):
    copied: List[str] = Field(description="stages before `from` - their records are copied")
    skipped: List[str] = Field(description="stages left out of a rebuild (the close)")
    run: List[str] = Field(description="stages that run")


class RebuildOf(BaseModel):
    model_config = ConfigDict(extra="allow")
    channel: Optional[str] = None
    batch_id: Optional[str] = None
    path: Optional[str] = None


class RebuildCheck(BaseModel):
    """`batch_control.rebuild_check` - as the factory says it."""
    model_config = ConfigDict(extra="allow")
    action: Literal["rebuild"]
    ok: bool = Field(description="the rebuild would be started")
    reason: str = Field(description="the factory's line, in Russian - shown as is")
    batch: str = Field(description="the source batch directory")
    batch_id: str
    channel: Optional[str] = None
    mode: Optional[str] = None
    title: Optional[str] = None
    from_stage: Optional[str] = None
    layout: Optional[RebuildLayout] = None
    copy_: List[str] = Field([], alias="copy", description="the records copied from the source")
    only_videos: List[str] = Field([], description="of them, trimmed to the chosen videos")
    work: List[str] = Field([], description="the work/ entries copied")
    videos: List[RebuildVideo] = []
    notes: Optional[str] = Field(None, description="the note on the whole rebuild")
    rebuild_of: Optional[RebuildOf] = None
    root: Optional[str] = None
    posix: bool = Field(description="process groups here (CF-0654); without them it refuses")


class RebuildPlan(RebuildCheck):
    fingerprint: str = Field(description="sha256 of the whole check - the token is bound to it")
    confirm: Optional[str] = Field(None, description="the confirm token of `POST .../rebuild` - "
                                                     "only when ok; single use; the videos, mode "
                                                     "and notes are bound to it")
    expires_in_s: Optional[int] = Field(None, description="the token lives this long")


class RebuildIn(BaseModel):
    confirm: str = Field(description="the plan's `confirm` (the videos, mode and notes are its)")


class RebuildResult(RebuildCheck):
    by: str
    started: bool = Field(description="the executor was started")
    rebuild_id: Optional[str] = Field(None, description="`<ts>` of pipeline/rebuilds/<ts>")
    rebuild_dir: Optional[str] = None
    pid: Optional[int] = None
    log: Optional[str] = Field(None, description="the executor's output, schedule/logs/")
    row: Optional[Launch] = Field(None, description="the schedule/launches.jsonl row, "
                                                    "`kind: rebuild`")
    exit: Optional[int] = Field(None, description="its code when it ended before taking the lock")
    state: Optional[str] = Field(None, description="the rebuild's run-state.json")
    argv: Optional[List[str]] = Field(None, description="what was started, detached")
    batch_start: Optional[Dict[str, Any]] = Field(None, description="`runlog batch-start "
                                                                    "--note` and its answer")


class BatchProcess(BaseModel):
    """One process the executor launched (`run-state.json` `runs.<key>`)."""
    model_config = ConfigDict(extra="allow")
    stage: Optional[str] = None
    argv: Optional[List[Any]] = None
    pid: Optional[int] = None
    pgid: Optional[int] = None
    started: Optional[str] = None
    ended: Optional[str] = None
    log: Optional[str] = Field(None, description="relative to the batch - logs/<key>.log")
    exit_file: Optional[str] = None
    exit: Optional[int] = None
    restarts: Optional[int] = None
    alive: bool = Field(description="no exit code yet and `run_executor.pid_alive` - the pid "
                                    "runs that command (ps)")


class QuietDecision(BaseModel):
    """CF-0735: a human decision the plan made quiet (`notify: quiet`): the
    default taken, a line of the batch's journal, no notification
    (run-state.json `quiet[]`; `decisions[key].by` = «default (human, quiet)»)."""
    model_config = ConfigDict(extra="allow")
    stage: Optional[str] = Field(None, description="the stage id")
    key: Optional[str] = Field(None, description="the decision's key (run-state `decisions`)")
    line: Optional[str] = Field(None, description="the Russian line, as the executor wrote it")
    took: Optional[str] = Field(None, description="the default taken")
    at: Optional[str] = Field(None, description="UTC ISO")


class CodeEditRepo(BaseModel):
    """CF-0713: one repo a stage changed (`stage_code_guard.compare`)."""
    model_config = ConfigDict(extra="allow")
    repo: Optional[str] = Field(None, description="`root` or `agents/<name>` "
                                                  "(runlog.factory_repos)")
    files: List[str] = Field([], description="tracked files the stage made dirty or changed "
                                             "again, relative to that repo")
    head_was: Optional[str] = Field(None, description="the repo's HEAD before the stage, when "
                                                      "the stage committed code")
    head_now: Optional[str] = Field(None, description="its HEAD after; null - no commit")


class StageCodeEdit(BaseModel):
    """CC-0111 (CF-0713): a batch stage changed the factory's tracked code -
    the row `run_executor.record_code_edits` writes into run-state.json
    `code_edits[]` (or the `stage_code_edit` event's fields), paths cut. The
    next `runlog batch-start` refuses the dirty tree (CF-0479)."""
    model_config = ConfigDict(extra="allow")
    stage: Optional[str] = Field(None, description="the plan stage that changed it")
    run: Optional[str] = Field(None, description="the executor's run key (`<stage>.s0`)")
    at: Optional[str] = Field(None, description="UTC ISO, when the executor saw it")
    mode: Optional[str] = Field(None, description="the rule's mode, `warn` until a price is "
                                                  "signed (stage_code_guard.MODE)")
    task: Optional[str] = Field(None, description="`CF-0713`")
    edits: List[CodeEditRepo] = Field([], description="per repo, as the factory records it")
    files: List[str] = Field([], description="every file of `edits` relative to the factory "
                                             "root (`agents/<name>/<file>` for an agent's)")
    line: Optional[str] = Field(None, description="stage_code_guard.describe(edits) - the "
                                                  "factory's one line («agents/footage-indexer: "
                                                  "scripts/source_rights.py»); null when it "
                                                  "does not load")
    source: Literal["state", "events"] = Field(description="run-state.json `code_edits[]`, or "
                                               "the journal's `stage_code_edit` events (a "
                                               "state without the key)")


class RunState(BaseModel):
    """`<batch>/run-state.json`, the executor's (CF-0203), whole - every path in
    it cut (CC-0119, `paths.clean`): `batch` and the paths inside the root
    relative (`pipeline/<channel>/<id>`), any other absolute path `.../<name>`."""
    model_config = ConfigDict(extra="allow")
    channel: Optional[str] = None
    batch: Optional[str] = None
    batch_id: Optional[str] = None
    status: Optional[str] = None
    created: Optional[str] = None
    order: Optional[List[str]] = None
    stages: Optional[Dict[str, Dict[str, Any]]] = None
    current: Optional[Dict[str, Any]] = None
    next: Optional[str] = None
    runs: Optional[Dict[str, BatchProcess]] = None
    reruns: Optional[Dict[str, Any]] = None
    needs_human: Optional[List[Dict[str, Any]]] = None
    halt_reason: Optional[str] = None
    stops: Optional[List[Dict[str, Any]]] = Field(None, description="the stops and resumes "
                                                                    "(CF-0667), when written")
    quiet: Optional[List[QuietDecision]] = Field(None, description="CF-0735: the quiet human "
                                                                   "decisions, when written "
                                                                   "(paths cut)")
    code_edits: Optional[List[Dict[str, Any]]] = Field(None, description="CF-0713: the "
                                                       "executor's rows, when written (paths "
                                                       "cut) - read them as the answer's own "
                                                       "`code_edits`")


class BatchDetail(BaseModel):
    batch: str
    channel: Optional[str] = Field(description="its channel (run-state, else the path)")
    batch_id: str
    dir: str
    state: Optional[RunState] = Field(description="null: no run-state.json (a batch of "
                                                  "markers only) or it does not read")
    state_error: Optional[str]
    status: Optional[str]
    executor_alive: Optional[bool] = Field(None, description=_EXECUTOR_ALIVE)
    lock_held: Optional[bool] = Field(None, description=_LOCK_HELD)
    executor_why: Optional[str] = Field(None, description=_EXECUTOR_WHY)
    alive: List[str] = Field(description="the keys of the processes alive now")
    questions: List[Question] = Field(description="its channel's live questions (open, "
                                                  "answered) - GET /api/questions")
    questions_error: Optional[str] = Field(None, description="null, or why the questions "
                                           "do not read in this checkout (no "
                                           "shared/needs_you.py) - `questions` is then [] "
                                           "(CC-0053)")
    quiet: List[QuietDecision] = Field([], description="CC-0120: run-state.json `quiet[]` "
                                       "(CF-0735) - the human decisions taken by default "
                                       "without a notification, a journal line each; [] "
                                       "when the key is not there (before 2.4) or no state")
    code_edits: List[StageCodeEdit] = Field([], description="CC-0111 (CF-0713): what the "
                                            "batch's stages changed in the factory's tracked "
                                            "code - run-state.json `code_edits[]`, else the "
                                            "journal's `stage_code_edit` events; [] for a batch "
                                            "before CF-0713 or a clean run")


class BatchEvent(BaseModel):
    offset: int = Field(description="the byte the line begins at")
    event: Optional[Dict[str, Any]] = Field(description="the line, parsed")
    text: Optional[str] = Field(description="a line that does not parse, cut")


class BatchEvents(BaseModel):
    batch: str
    events: List[BatchEvent]
    next: int = Field(description="the cursor of the next poll (`after`)")
    size: int = Field(description="the file's size now, bytes")
    more: bool = Field(description="whole lines past `next` are there already - ask at once")
    reset: bool = Field(description="`after` was past the end (the file was replaced): this is "
                                    "the tail")
    poll_s: int = Field(description="the recommended interval to ask again, seconds")


# ---------------------------------------------------------------- the videos (CC-0012)
class VideoFile(BaseModel):
    url: str = Field(description="GET/HEAD it - `video/mp4`, HTTP Range (206, `Content-Range`, "
                                 "416 past the end)")
    exists: bool = Field(description="`<batch>/videos/<slug>.mp4` is there")
    bytes: Optional[int] = None
    path: Optional[str] = Field(None, description="relative to the factory root")


class Preview(BaseModel):
    available: bool
    kind: Optional[Literal["frame", "sheet"]] = Field(
        None, description="`frame`: the Editor's preview frame `videos/<slug>.jpg` (CF-0674, "
                          "720 x 1280, image/jpeg); `sheet` (a video without it): the frame "
                          "judge's first contact sheet (frames of the finished video, `grid` "
                          "of `tile`s; the first tile is the first block, image/png)")
    media_type: Optional[Literal["image/jpeg", "image/png"]] = Field(
        None, description="what GET `url` answers")
    url: Optional[str] = None
    path: Optional[str] = Field(None, description="the file, relative to the factory root")
    tile: Optional[Dict[str, Any]] = Field(None, description="{width, height} of one tile, px")
    grid: Optional[Dict[str, Any]] = Field(None, description="{columns, rows} of the sheet")
    reason: Optional[str] = Field(None, description="in Russian: why there is none")


# ---------------------------------------------------------------- the card's state (CC-0127)
CARD_STATES = ("none", "building", "ready", "ruled", "not_ready")
CARD_BUILD_CODES = ("ready", "not_ready", "refused", "not_asked", "error", "running")


class CardRuling(BaseModel):
    """The user's ruling a card was taken by (`## Решение пользователя`, CF-0747)."""
    model_config = ConfigDict(extra="allow")
    by: Optional[str] = None
    via: Optional[str] = None
    words: Optional[str] = Field(None, description="the user's own words, as written")
    at: Optional[str] = Field(None, description="when, ISO UTC")


class CardBuildRun(BaseModel):
    """The last build of the video from the center (`card_center.last_run`)."""
    model_config = ConfigDict(extra="allow")
    run_id: str
    log: Optional[str] = Field(None, description="the build's log, relative to the root")
    code: str = Field(description="one of " + ", ".join(CARD_BUILD_CODES))
    word: Optional[str] = Field(None, description="the factory's Russian word for the code "
                                                  "(card_center.OUTCOME_WORDS)")
    started_at: Optional[str] = None
    by: Optional[str] = None
    via: Optional[str] = None
    auto: bool = Field(False, description="started by itself on the acceptance")


class CardState(BaseModel):
    """CC-0127: the card's state wherever the center shows a card -
    `publish_card.card_status` of its text and the last build from the center
    (a build going makes it `building`)."""
    model_config = ConfigDict(extra="allow")
    state: Literal[CARD_STATES] = Field(description="none | building | ready | ruled (taken "
                                                    "by the user's ruling) | not_ready")
    state_ru: Optional[str] = Field(None, description="the state in Russian")
    placeable: bool = Field(description="ready or ruled - what the placing reads")
    why: Optional[str] = Field(None, description="the factory's line when not placeable")
    reasons: List[str] = Field(default_factory=list,
                               description="the codes of what kept it from being ready")
    ruling: Optional[CardRuling] = None
    build: Optional[CardBuildRun] = None


class CardShort(BaseModel):
    exists: bool
    ready: bool = Field(description="`publish_card.placeable` (CF-0747): ready, or taken by the user's ruling (ruled) - what the placing reads")
    why: Optional[str] = Field(None, description="the factory's line when not ready")
    title: Optional[str] = None
    url: str = Field(description="GET it - the card parsed")
    card: Optional[CardState] = Field(None, description="CC-0127: the state (none when no "
                                                        "card); null when the card does not "
                                                        "read")


class VideoAcceptance(BaseModel):
    """`acceptance.state` (the verdict and, apart, the CF-0318 hold) and the
    row's fields - null fields when there is no verdict yet."""
    model_config = ConfigDict(extra="allow")
    entry_id: str
    slug: str
    recorded: Optional[bool] = None
    verdict: Optional[Literal["accepted", "rejected"]] = None
    accepted: Optional[bool] = None
    reason: Optional[str] = None
    reason_code: Optional[str] = None
    answer: Optional[str] = Field(None, description="the user's words, as he said them")
    answered_at: Optional[str] = Field(None, description="the day (the factory's)")
    recorded_at: Optional[str] = Field(None, description="UTC ISO (the factory's)")
    note: Optional[str] = None
    amended_because: Optional[str] = None
    history: Optional[List[Dict[str, Any]]] = None
    held: Optional[bool] = None
    hold_id: Optional[str] = None
    publishable: Optional[bool] = Field(None, description="accepted and not held - not a "
                                                          "permission to upload")
    pending: Optional[bool] = Field(None, description="the verdict waits in the queue "
                                                      "(publish/acceptance-pending.jsonl) for "
                                                      "the batch to end - shown, not yet "
                                                      "committed (CF-0675)")
    queued_at: Optional[str] = Field(None, description="UTC ISO - when it was queued")
    queued_by: Optional[str] = Field(None, description="who gave the queued verdict")
    queued_verdicts: Optional[int] = Field(None, description="more than one verdict queued "
                                                             "for the video - the last wins")
    state_error: Optional[str] = None


class UploadWithdrawn(BaseModel):
    """CC-0179 (CF-0918, `upload_records.withdraw`): the mark on a journal row -
    the video was taken off its slot in Studio into the копилка's reserve."""
    model_config = ConfigDict(extra="allow")
    at: Optional[str] = Field(None, description="when, UTC")
    by: Optional[str] = Field(None, description="who wrote it down: `user`, `driver`")
    via: Optional[str] = Field(None, description="through what: `center`, `studio`")
    task: Optional[str] = Field(None, description="\"CF-0918\"")
    from_at: Optional[str] = Field(None, description="the slot it held, ISO 8601")
    from_day: Optional[str] = Field(None, description="the Moscow day it held")
    from_note: Optional[str] = Field(None, description="where its note was")
    studio: Optional[str] = Field(None, description="what it stands at in Studio, "
                                                    "«Ограниченный доступ»")


class VideoUpload(BaseModel):
    """CC-0096: the video's live row of `publish/uploads.json` (CF-0586) - by
    its acceptance key `<channel>/<batch_id>/<slug>`, never by slug alone."""
    video_id: str = Field(description="YouTube's id, 11 characters")
    url: Optional[str] = Field(None, description="https://youtube.com/shorts/<video_id>")
    publish_day: Optional[str] = Field(None, description="`YYYY-MM-DD`, the release day in "
                                                         "Moscow time - the day folder")
    publish_at: Optional[str] = Field(None, description="the slot, ISO 8601 with its offset; "
                                                        "null when nobody wrote it down")
    uploaded_at: Optional[str] = Field(None, description="when the API upload ran (`upload.py` "
                                                         "rows); null for a Studio or backfill "
                                                         "row - the journal has no such time")
    recorded_at: Optional[str] = Field(None, description="when the row was written, UTC")
    source: Optional[str] = Field(None, description="`studio` | `api` | `backfill`")
    withdrawn: Optional[UploadWithdrawn] = Field(None, description="CC-0179: taken off the feed "
                                                                   "into the копилка's reserve "
                                                                   "- `publish_day` and "
                                                                   "`publish_at` are null then; "
                                                                   "null: not taken off")


class VideoRefusal(BaseModel):
    """CC-0116 (CF-0727): a video refused after the render - its script's last
    row of the 05's `refusals[]`, as the Editor wrote it."""
    model_config = ConfigDict(extra="allow")
    reason_code: Optional[str] = Field(None, description="`score_below_threshold`, ...")
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    reason: Optional[str] = Field(None, description="the Editor's line")
    gate: Optional[str] = Field(None, description="the gate that refused it")
    score_line: Optional[str] = Field(None, description="`F · 24 — ...` (CF-0434)")
    score: Optional[Dict[str, Any]] = Field(None, description="the score as computed "
                                                              "(start, score, tier, threshold, "
                                                              "log, ...)")
    at: Optional[str] = Field(None, description="when it was refused, ISO")


class VideoScoreShort(BaseModel):
    """CC-0125: the badge - the video's points and tier (CF-0434)."""
    tier: Optional[str] = Field(None, description="S, A, B, C, D, E or F - colour it by "
                                                  "`BatchVideos.score_model.tiers`")
    score: Optional[float] = None
    threshold: Optional[float] = Field(None, description="N - under it the video is F")
    passed: Optional[bool] = None
    stopped_at: Optional[str] = Field(None, description="the stage after which the points "
                                                        "first fell under N, or null")
    source: Literal["plan.score.json", "05"] = Field(
        description="`work/<slug>/plan.score.json` (the log), else the 05's score block "
                    "(`refusals[].score` / `videos[].score`)")
    url: str = Field(description="GET the reasoning there (`VideoScore`)")


class ScoreTier(BaseModel):
    name: str
    floor: float = Field(description="the tier starts at these points")


class ScoreModel(BaseModel):
    """CC-0125: the tiers of the score model (`shared/score/score.py`
    `load_model` over the root's `shared/gate-prices.json`)."""
    start: Optional[float] = None
    threshold: Optional[float] = None
    tiers: List[ScoreTier] = Field(description="best first; under the last floor a video is "
                                               "`below` (F) - empty when the table does not "
                                               "load (`error`)")
    below: str = "F"
    status: Optional[str] = Field(None, description="`signed` | `draft`")
    error: Optional[str] = None


class Video(BaseModel):
    slug: str = Field(description="the stem of the 05's `output_path` - the video's name; a "
                                  "refused one: the slug the factory's rebuild finds for it")
    script_id: Optional[str] = None
    qc_passed: Optional[bool] = None
    score_line: Optional[str] = Field(None, description="`B · 74 — ...` (CF-0434), shown, "
                                                        "never decided on")
    duration: Optional[float] = None
    mp4: VideoFile
    preview: Preview
    card: CardShort
    acceptance: Optional[VideoAcceptance] = Field(
        None, description="null when the record does not read (`acceptance_error`)")
    accept_url: str = Field(description="POST the user's verdict there (a refused video: 409 "
                                        "`video_refused`)")
    refused: Optional[VideoRefusal] = Field(
        None, description="CC-0116: refused after the render (05 `refusals[]`, not "
                          "`videos[]`) - its mp4 / preview / card by the same routes when "
                          "the file is there, no verdict; null for a video the run built")
    repair: Optional[VideoRepair] = Field(
        None, description="CC-0171 (CF-0881): the repair pass after the frame judge (06 "
                          "repairs[]) - null when it had none")
    upload: Optional[VideoUpload] = Field(
        None, description="its upload to YouTube (CC-0096) - null when it has none (or only a "
                          "replaced / removed one), or the journal does not read "
                          "(`uploads_error`)")
    score: Optional[VideoScoreShort] = Field(
        None, description="CC-0125: its points and tier - null when neither its log nor the "
                          "05 has a score")
    rebuilt_in: List[str] = Field(description="the rebuilds (`rebuilds/<ts>`) that made this "
                                              "video again")


class RebuildBatch(BaseModel):
    batch: str = Field(description="`rebuilds/<ts>` - the routes' path form")
    batch_id: str
    dir: str
    editor_error: Optional[str] = None
    videos: List[Video]


class RebuildSource(BaseModel):
    channel: Optional[str] = None
    batch_id: Optional[str] = None
    batch: Optional[str] = Field(None, description="`<dir>/<batch_id>` - the routes' path form")


class ReasonCode(BaseModel):
    code: str
    count: Optional[int] = None
    phrases: List[str] = []


class BatchVideos(BaseModel):
    batch: str
    channel: Optional[str] = None
    batch_id: str
    dir: str
    editor_error: Optional[str] = Field(None, description="no 05-video-editor.json, or it does "
                                                          "not read")
    rebuild_of: Optional[RebuildSource] = Field(None, description="the source, for a rebuild")
    videos: List[Video]
    rebuilds: List[RebuildBatch] = Field(description="the rebuilds of this batch, oldest first")
    reason_codes: List[ReasonCode] = Field(description="the refusal codes the record counts "
                                                       "(`acceptance.reasons`)")
    score_model: ScoreModel = Field(description="CC-0125: the tiers the badges are coloured by")
    acceptance_error: Optional[str] = Field(None, description="the record does not read")
    uploads_error: Optional[str] = Field(None, description="publish/uploads.json does not read "
                                                           "- every `upload` is then null "
                                                           "(CC-0096)")


class VideoScoreStage(BaseModel):
    stage: Optional[str] = Field(None, description="`6b`, `plan`, `render`, `qc`, `judge`")
    label_ru: Optional[str] = None
    charged: Optional[float] = Field(None, description="what the stage took off (<= 0)")
    score_after: Optional[float] = None
    tier_after: Optional[str] = None
    at: Optional[str] = None


class VideoScoreFinding(BaseModel):
    rule: Optional[str] = Field(None, description="`score.low_framing`, `score.hard.*`, ...")
    label_ru: Optional[str] = Field(None, description="the words the factory's score line "
                                                      "prints (`score.LABELS` / "
                                                      "`HARD_LABELS`, `судья: <verdict>`); "
                                                      "none there: the rule's short name")
    stage: Optional[str] = Field(None, description="the stage that found it; null for a 05 "
                                                   "block without its stages")
    block: Optional[Union[int, str]] = Field(None, description="the storyboard block")
    t: Optional[float] = Field(None, description="seconds into the video")
    shot: Optional[str] = None
    shot_ru: Optional[str] = Field(None, description="the shot for display (0.58.0): the clip's "
                                                     "file name without the `aNN_` prefix and "
                                                     "extension, `_` / `-` as spaces "
                                                     "(`a04_mine-cart.mp4` -> `mine cart`); a "
                                                     "shot id without a path as is")
    where: Dict[str, Any] = Field(default_factory=dict, description="as the log has it")
    price: Optional[float] = Field(None, description="what it cost after the cap (<= 0); null "
                                                     "for a hard or a forecast finding")
    units: Optional[float] = None
    hook: bool = Field(False, description="the hook's multiplier applied (the first 5 s)")
    capped: bool = False
    source: Optional[str] = Field(None, description="`metric`, `forecast`, ...")
    note: Optional[str] = None
    note_ru: Optional[str] = Field(None, description="the note in Russian (0.58.0, CF-0751): the "
                                                     "log row's `note_ru`, else the factory's "
                                                     "`score.note_ru` over the note (a log "
                                                     "older than CF-0751); null for the judge's "
                                                     "prose and a note no template covers")
    hard: bool = Field(description="the hard list - the video is F whatever its points")
    forecast: bool = Field(description="a forecast - left out of the score (Q17)")


class VideoScoreRule(BaseModel):
    raw: Optional[float] = None
    charged: Optional[float] = None
    cap: Optional[float] = None
    label_ru: Optional[str] = None


class VideoScore(BaseModel):
    """CC-0125: «оценка ролика» - the video's score log (CF-0434)."""
    batch: str
    slug: str
    script_id: Optional[str] = None
    source: Literal["plan.score.json", "05"]
    path: Optional[str] = Field(None, description="the log, relative to the root; null for "
                                                  "the 05")
    tier: Optional[str] = None
    score: Optional[float] = None
    start: Optional[float] = None
    threshold: Optional[float] = None
    passed: Optional[bool] = None
    stopped_at: Optional[str] = None
    stopped_at_ru: Optional[str] = None
    prices_status: Optional[str] = None
    forecast_ignored: Optional[int] = None
    tiers: List[ScoreTier] = Field(description="the model's tiers, best first (F below)")
    model_error: Optional[str] = Field(None, description="the price table does not load")
    stages: List[VideoScoreStage]
    findings: List[VideoScoreFinding]
    by_rule: Dict[str, VideoScoreRule]
    score_line: Optional[str] = None


class AcceptIn(BaseModel):
    verdict: Literal["yes", "no", "redo"] = Field(
        description="yes -> accepted; no, redo («переделать, потому что…») -> rejected")
    words: str = Field(description="the user's exact words - they name the video (CF-0328)")
    reason: Optional[str] = Field(None, description="one phrase - required for no / redo")
    reason_code: Optional[str] = Field(None, description="[a-z][a-z0-9_]* - required for no / "
                                                         "redo; none for yes")
    amend: Optional[str] = Field(None, description="why the user changed a verdict already "
                                                   "recorded (the old one goes to history)")


class RedoAnswer(BaseModel):
    queued: bool = Field(description="the request went to the operator's queue (CC-0018)")
    reason: Optional[str] = None
    request: Optional[Dict[str, Any]] = None


class BlockingBatch(BaseModel):
    """A batch going that holds an acceptance verdict in the queue (CF-0675). Not the
    open-batches item `GoingBatch` of /api/batches/going - CC-0060."""
    dir: str = Field(description="the batch or rebuild going, relative to the root")
    why: Optional[str] = Field(None, description="the factory's line: why it counts as going")


class AcceptNamesake(BaseModel):
    """CC-0152 (CF-0821): the placed video that only carries this video's name
    (another topic / fact) - this one went into the копилка by itself."""
    entry_id: Optional[str] = Field(None, description="its acceptance entry")
    publish_path: Optional[str] = Field(None, description="its place, relative")
    why: Optional[str] = Field(None, description="why the two are different videos")


class AcceptLeftOut(BaseModel):
    """CC-0152 (CF-0821): an accepted video the копилка did not get
    (`acceptance._left_out`) - also sent on the notification bus."""
    entry_id: Optional[str] = None
    slug: Optional[str] = None
    batch_id: Optional[str] = None
    code: Optional[str] = Field(None, description="the queue code: other_version_placed or a "
                                                  "refusal (slug_taken, batch_missing, "
                                                  "render_missing, channel_unknown, "
                                                  "queue_failed)")
    text_ru: Optional[str] = Field(None, description="the factory's line, opening with «НЕ В "
                                                     "КОПИЛКЕ: » - shown as is")
    alert_ru: Optional[str] = Field(None, description="the loud Russian line - shown as is")
    namesake: Optional[AcceptNamesake] = None
    notified: Optional[Dict[str, Any]] = Field(None, description="the notification bus's "
                                                                 "answer ({status, ...}); null "
                                                                 "- nothing sent")


class AcceptanceFlush(BaseModel):
    """`acceptance.commit_pending`'s answer: the queue committed before the verdict."""
    committed: bool
    commit: Optional[str] = None
    subject: Optional[str] = None
    applied: List[str] = Field(description="entry ids applied from the queue")
    conflicts: List[Dict[str, Any]] = Field(description="a video queued twice: {entry_id, won, "
                                                        "verdicts} - the last wins")
    failed: List[Dict[str, Any]] = Field(description="{entry_id, error, code, text_ru} - left "
                                                     "in the queue")
    left: int = Field(description="verdicts still queued")
    why: Optional[str] = Field(None, description="in Russian: why nothing was done")
    left_out: List[AcceptLeftOut] = Field(
        default_factory=list, description="CC-0152 (CF-0821): the applied accepted videos the "
                                          "копилка did not get; [] when none")


#: CF-0738 `acceptance.QUEUE_RU`'s codes - what the factory did with an accepted
#: video's render (CC-0122).
ACCEPT_QUEUE_CODES = ("placed", "adopted", "already_placed", "not_accepted",
                      "other_version_placed", "slug_taken", "batch_missing", "render_missing",
                      "channel_unknown", "queue_failed")


class AcceptCardBuild(BaseModel):
    """CC-0127: `card_center.short(on_accepted(...))` - the card's build the
    acceptance started (detached, idempotent), skipped (running / ready /
    ruled / off - PUBLISH_CARD_AUTOBUILD=0) or refused."""
    model_config = ConfigDict(extra="allow")
    ok: bool
    launched: bool
    skipped: Optional[str] = Field(None, description="running | ready | ruled | off")
    run_id: Optional[str] = Field(None, description="GET /publish/{c}/cards/build/{run_id}")
    log: Optional[str] = Field(None, description="the build's log, relative to the root")
    refusals: List[str] = Field(default_factory=list, description="the codes "
                                                                  "(card_center.BUILD_REFUSALS)")
    error: Optional[str] = None
    why: Optional[str] = Field(None, description="CC-0174 (CF-0891): why the build did not "
                                                 "start - the refusals' own lines "
                                                 "(card_center.refusal_line: «code: line; "
                                                 "...»), paths cut; null when it started, "
                                                 "was skipped or the factory said nothing")


class AcceptQueued(BaseModel):
    """CC-0122: where the accepted video went (CF-0738 `queued`) - the channel's
    копилка `publish/<c>/_queue/` (placed / adopted), a place it already had
    (already_placed), not this version (other_version_placed) or why it did
    not (slug_taken, batch_missing, render_missing, channel_unknown,
    queue_failed)."""
    code: str = Field(description="one of " + ", ".join(ACCEPT_QUEUE_CODES))
    text_ru: str = Field(description="the factory's Russian line - shown as is")
    publish_path: Optional[str] = Field(None, description="the row's publish_path, relative "
                                                          "(publish/<c>/_queue/<slug>.mp4)")
    ok: bool = Field(description="placed / adopted / already_placed")
    skipped: bool = Field(description="not_accepted / other_version_placed - by design")
    refused: bool = Field(description="a code a person has to look at")
    changed: bool = Field(description="the factory copied or recorded something now")
    card_build: Optional[AcceptCardBuild] = Field(
        None, description="CC-0127: the card's build started by itself on the acceptance "
                          "(card_center.on_accepted, CF-0747); null when not queued")
    left_out: bool = Field(False, description="CC-0152 (CF-0821): accepted but not in the "
                                              "копилка (other_version_placed or a refusal) - "
                                              "`text_ru` opens with «НЕ В КОПИЛКЕ: »")
    alert_ru: Optional[str] = Field(None, description="CC-0152 (CF-0821): the loud Russian line "
                                                      "of a left-out video; null otherwise")
    namesake: Optional[AcceptNamesake] = Field(
        None, description="CC-0152 (CF-0821): a placed video under the same name that is "
                          "another video; null - none")
    notified: Optional[Dict[str, Any]] = Field(
        None, description="CC-0152 (CF-0821): the notification bus's answer for a left-out "
                          "video ({status, ...}); null - nothing sent")


class AcceptResult(BaseModel):
    batch: str
    slug: str
    verdict: Literal["yes", "no", "redo"]
    row: Dict[str, Any] = Field(description="the record's row as the factory wrote it (`pending: "
                                            "true`, `queued_at` when queued)")
    log: str = Field(description="the record's file, relative to the root")
    pending: bool = Field(description="queued under an open batch: the record and HEAD "
                                      "untouched, committed after the batch (CF-0675)")
    committed: bool = Field(description="the record committed now - one commit, that file only")
    commit: Optional[str] = Field(None, description="the commit's sha")
    subject: Optional[str] = Field(None, description="«Приёмка: <slug> принят|отклонён "
                                                     "(user (центр))»")
    queue: Optional[str] = Field(None, description="the queue's file, when queued")
    batches: List[BlockingBatch] = Field(description="the batches going - why it is queued")
    flushed: Optional[AcceptanceFlush] = Field(None, description="the queue committed first "
                                                                 "(no batch going); null: "
                                                                 "there was none")
    redo: Optional[RedoAnswer] = None
    queued: Optional[AcceptQueued] = Field(None, description="CC-0122: the accepted video's "
                                                             "копилка (CF-0738); null for a "
                                                             "rejection")
    left_out: Optional[AcceptLeftOut] = Field(
        None, description="CC-0152 (CF-0821): record_and_commit's `left_out` - the accepted "
                          "video the копилка did not get; null when it did, or a rejection")
    acceptance: Optional[VideoAcceptance] = None


class WithdrawSource(BaseModel):
    video_id: str
    files: List[str] = Field(description="the source's media and sidecars in shared/footage/")
    bytes: int


class WithdrawKept(BaseModel):
    video_id: str
    blocked_by: List[str] = Field(description="what keeps it: open_batch, the statuses of the "
                                              "topics not finished")
    open_batches: List[str]
    topics: Dict[str, Optional[str]] = Field(description="every topic referencing it -> status")


class WithdrawPlan(BaseModel):
    """`pool_release`: the video's topic, what the records say of it, and the
    pool's what-if (`plan(extra_withdrawn)`) - nothing written, nothing
    deleted."""
    action: Literal["video_withdraw"]
    ok: bool = Field(description="the factory would take it")
    why: Optional[str] = Field(None, description="why not, in Russian - shown as is")
    entry_id: str = Field(description="the factory's key CHANNEL/BATCH/SLUG (the route's form)")
    topic_id: Optional[str] = Field(None, description="`Resolver.topic`")
    status: Optional[Dict[str, Any]] = Field(None, description="`topic_status` now: {status, "
                                                               "evidence}; null - no_video")
    status_after: Optional[Dict[str, Any]] = Field(None, description="with the withdrawal")
    withdrawn_before: List[Dict[str, Any]] = Field(description="the withdrawn rows of this entry")
    frees: List[WithdrawSource] = Field(description="the sources the withdrawal lets go - they "
                                                    "leave only with pool-release --delete")
    frees_bytes: int
    kept: List[WithdrawKept] = Field(description="the topic's sources still kept, and why")
    open_batches: List[str]
    journal: str = Field(description="shared/footage/release-log.jsonl")
    by: Literal["user"] = Field("user", description="CC-0117: who goes on the row "
                                                    "(record_withdrawal(by, via), CF-0720)")
    via: Literal["center"] = "center"
    deletes_now: bool = Field(description="always false: nothing leaves the disk here")
    line: str
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class WithdrawIn(BaseModel):
    confirm: str = Field(description="the plan's `confirm`")
    answer: str = Field(description="the user's own words, in Russian, naming the video (the "
                                    "factory's rule, check_answer); recorded as they are, "
                                    "by/via on the row")


class WithdrawResult(BaseModel):
    action: Literal["video_withdraw"]
    entry_id: str
    written: bool
    row: Dict[str, Any] = Field(description="the `withdrawn` row record_withdrawal appended "
                                            "(by: user, via: center on it)")
    by: Literal["user"] = "user"
    via: Literal["center"] = "center"
    journal: str
    frees: List[WithdrawSource]
    status_after: Optional[Dict[str, Any]] = None


class CardSection(BaseModel):
    name: str
    text: str


class Card(BaseModel):
    batch: str
    slug: str
    path: str
    ready: bool = Field(description="`publish_card.placeable` (CF-0747): ready, or taken by the user's ruling (ruled) - what the placing reads")
    why: Optional[str] = None
    status: Optional[str] = Field(None, description="the marker's: ready / not_ready")
    title: str
    description: str
    description_blocks: List[str] = Field(description="the description's blocks (three by the "
                                                      "rules): about, source, hashtags")
    tags: Optional[List[str]] = Field(None, description="`publish_note.parse`; null on "
                                                        "`note_error`")
    tags_raw: Optional[str] = None
    publish_at: Optional[str] = Field(None, description="UTC ISO of `## Публикация`")
    publish_section: Optional[str] = None
    contains_synthetic: Optional[bool] = None
    note_error: Optional[str] = Field(None, description="`publish_note.parse` refused the note")
    sections: List[CardSection] = Field(description="every `## section`, in order")
    problems: List[str] = []
    source: Optional[Dict[str, Any]] = None
    fact_checks: List[Dict[str, Any]] = []
    claims: Optional[Dict[str, Any]] = None
    mark: Optional[Dict[str, Any]] = Field(None, description="`publish_card.mark_of`")
    raw: str = Field(description="the card's text, for «подробнее»")
    card: Optional[CardState] = Field(None, description="CC-0127: the card's state "
                                                        "(card_status, the last build)")


# ---------------------------------------------------------------- publication (CC-0064)
class PublishProblem(BaseModel):
    """A refusal of the publication routes - `{message, code, details}` as
    `BatchProblem`; the message is the factory's line (an agent's English line
    as it is)."""
    message: str = Field(description="the factory's line - shown as is")
    code: Literal["unknown_channel", "unknown_note", "queue_broken", "pause_unreadable",
                  "holds_unreadable", "journal_unreadable", "rotation_broken", "card_broken",
                  # CC-0182 (CF-0920): two videos of the name in one place, no batch named
                  "namesakes"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_PPROBLEMS = {s: {"model": PublishProblem} for s in (404, 409, 500)}


class SlotRule(BaseModel):
    """`publish_queue.slot_config` - the channel's `publisher.slot`."""
    channel: str
    times: List[str] = Field(description="HH:MM in the channel's zone, one per slot of a day")
    tz: str = Field(description="IANA zone of the slot")
    per_day: int
    lead_hours: float = Field(description="no slot sooner than this from now")


class SlotAt(BaseModel):
    at: str = Field(description="UTC ISO")
    local: str = Field(description="ISO in the channel's zone")
    label: str = Field(description="`publish_queue.label`: «2026-10-11 01:00 МСК»")
    day: str = Field(description="the Moscow day - the folder publish/<channel>/<day>/")


class QueueSlot(SlotAt):
    taken_by: Optional[str] = Field(description="the slug in it (`table`), null when free")
    next_free: bool = Field(description="the nearest free slot past the lead (`next_free`)")


class Occupant(BaseModel):
    """`publish_queue.occupants` - a video holding a publication day."""
    slug: Optional[str] = None
    day: str
    at: Optional[str] = Field(None, description="UTC ISO; null: somewhere that day")
    sources: List[str] = Field(description="publish/<channel>/<day>/ and/or "
                                           "uploads.json:<video id>")


class WithdrawnRow(BaseModel):
    """CC-0179 (CF-0918): a journal row taken off the feed - in Studio, no slot,
    no day; it waits in the копилка as reserve."""
    slug: Optional[str] = None
    video_id: Optional[str] = None
    url: Optional[str] = None
    batch_id: Optional[str] = None
    note: Optional[str] = Field(None, description="publish/<channel>/_reserve/<slug>.md (CF-0919; "
                                                  "_queue/ until --migrate-reserve moved it)")
    withdrawn: UploadWithdrawn


class Tomorrow(BaseModel):
    """`publish_queue.tomorrow` - the orchestrator's line and its exit code."""
    code: int = Field(description="0 ok, 1 an empty slot, 2 no queue / error, 3 paused")
    state: Literal["ok", "empty", "error", "paused"]
    line: str = Field(description="the factory's line, as `publish_queue.py tomorrow` prints it")


class QueueHead(BaseModel):
    channel: str
    slot: Optional[SlotRule] = Field(description="null: the channel has no publisher.slot")
    paused: Optional[str] = Field(description="`pause_state`: why nothing is placed, null "
                                              "when not paused")
    pause_notices: List[str] = Field(description="an expired pause still on record")
    tomorrow: Optional[Tomorrow]
    next_free: Optional[SlotAt]
    next_free_error: Optional[str] = Field(description="`next_free` refused (no free slot in "
                                                       "the horizon)")
    waiting: List[str] = Field(description="`waiting`: the slugs in publish/<channel>/_queue/ "
                                           "and _reserve/ (CF-0919), each name once - two "
                                           "videos of one name (CF-0920) are one here; the "
                                           "videos and their batches: GET /publish/{c}/stash")


class QueueLine(QueueHead):
    error: Optional[str] = Field(description="the channel's queue does not read (the slot "
                                             "block, the journal) - the factory's line")


class PublishOverview(BaseModel):
    as_of: str = Field(description="UTC ISO - the clock the queue was computed at")
    channels: List[QueueLine] = Field(description="every channel `queue_channels` names")


class ChannelQueue(QueueHead):
    as_of: str
    days: int
    journal: str = Field(description="the upload journal read (publish/uploads.json)")
    slots: List[QueueSlot] = Field(description="`table`: the slots of `days` days from today")
    occupants: List[Occupant]
    withdrawn: List[WithdrawnRow] = Field(default_factory=list,
                                          description="CC-0179: the channel's videos taken off "
                                                      "the feed - no slot, no occupant: they "
                                                      "wait in the копилка as reserve")


class PauseRow(BaseModel):
    """A row of `publish/channel-pauses.json` (CF-0569)."""
    model_config = ConfigDict(extra="allow")
    pause_id: str
    channel: str
    by: str
    reason: str
    set_at: str
    until: Optional[str] = None
    cleared_at: Optional[str] = None
    cleared_by: Optional[str] = None
    clear_note: Optional[str] = None


class ChannelPause(BaseModel):
    channel: str
    as_of: str
    state: Literal["free", "paused", "expired"] = Field(description="`channel_pause.status`")
    line: str = Field(description="the factory's line (Russian)")
    row: Optional[PauseRow] = Field(description="the row the state is of")
    open_row: Optional[PauseRow] = Field(description="`open_row`: the uncleared row")
    history: List[PauseRow] = Field(description="`history`: every row, oldest first")
    registry: str


class HoldSignRefusal(BaseModel):
    """`HoldSignError.as_dict()` (CF-0687)."""
    code: Literal["no_such_hold", "already_signed", "already_resolved", "not_signable",
                  "empty_user", "empty_note", "ledger_unreadable"]
    text_ru: str = Field(description="the factory's line - shown as is")
    text: str = Field(description="its English line, for logs")


class SceneRelease(BaseModel):
    """CC-0169: `scene_release` of a ledger row - what the root's scene rule
    (`runlog scene-holds`, CF-0846) recorded when it lifted the hold."""
    model_config = ConfigDict(extra="allow")
    task: Optional[str] = Field(None, description="CF-0846")
    script_scenes: List[Optional[str]] = Field([], description="the scene ids the batch's "
                                                               "scripts of the topic took")
    scripts: List[Optional[str]] = Field([], description="those scripts' ids")
    flagged_scenes: List[str] = Field([], description="the scene ids the flag rests on")
    by: Optional[str] = Field(None, description="who lifted it - `runlog scene-holds`")
    batch_dir: Optional[str] = Field(None, description="the batch directory judged, from the "
                                                       "root")


class SceneReleaseReopened(BaseModel):
    """CC-0169: `scene_release_reopened` - the scene rule put back a hold it
    had lifted (a later round wrote a script on the flagged scene)."""
    model_config = ConfigDict(extra="allow")
    at: Optional[str] = Field(None, description="UTC ISO")
    task: Optional[str] = None
    was: Optional[SceneRelease] = Field(None, description="the release it undid")
    why: Optional[str] = Field(None, description="the factory's line (English)")
    script_scenes: List[Optional[str]] = Field([], description="the scenes the scripts take "
                                                               "now")


class HoldRow(BaseModel):
    """A row of `publish/publication-holds.json` (CF-0318) - as written."""
    model_config = ConfigDict(extra="allow")
    hold_id: Optional[str] = None
    channel: Optional[str] = None
    batch_id: Optional[str] = None
    topic_id: Optional[str] = None
    script_id: Optional[str] = None
    verdict: Optional[str] = None
    reason_code: Optional[str] = None
    reason_ru: Optional[str] = Field(None, description=_REASON_RU)
    reason: Optional[str] = None
    raised_at: Optional[str] = None
    resolved_at: Optional[str] = None
    resolved_reason: Optional[str] = None
    resolved_reason_code: Optional[str] = Field(None, description="CC-0169 (CF-0846): "
                                                "flagged_scene_not_in_script - lifted by the "
                                                "scene rule; null: anything else")
    scene_release: Optional[SceneRelease] = Field(None, description="CC-0169: the scene "
                                                  "rule's record of the lift")
    scene_release_reopened: Optional[SceneReleaseReopened] = Field(
        None, description="CC-0169: the scene rule put the hold back - it stands again")
    content_sensitivity_check: Optional[Dict[str, Any]] = Field(None, description="as the row "
                                                                                  "has it")
    sensitivity_scenes: SensitivityScenes = Field(None, description=_SCENES)
    signature: Optional[Dict[str, Any]] = Field(None, description="only a human writes it - "
                                                                  "{user, date, note, via}")
    signable: Optional[bool] = Field(None, description="CC-0070: `check_sign` lets the center "
                                                       "sign it (GET /publish/holds only)")
    sign_refusal: Optional[HoldSignRefusal] = Field(None, description="CC-0070: why not - the "
                                                                        "factory's refusal")


class PublicationHolds(BaseModel):
    channel: Optional[str] = Field(description="the channel asked, null: every channel")
    path: str
    exists: bool
    problem: Optional[str] = Field(description="the ledger does not read - fail closed "
                                               "(both lists empty, every video held)")
    open: List[HoldRow] = Field(description="`open_holds`: unresolved and unsigned")
    rows: List[HoldRow] = Field(description="`read_ledger`: every row")


class HoldRelease(BaseModel):
    """CC-0169 (CF-0846): what lifted a hold, or put it back - the line the
    center shows («Удержание снято: флаг на s2, в ролике s1, подпись не нужна»)."""
    state: Literal["released", "reopened"] = Field(
        description="released: resolved (resolved_at) - by the scene rule or anything else "
                    "(CF-0420, a later pass); reopened: the scene rule lifted it and put it "
                    "back - it stands again, unsigned")
    at: Optional[str] = Field(description="UTC ISO: resolved_at / scene_release_reopened.at")
    by: Optional[str] = Field(description="scene_release.by (`runlog scene-holds`); null: the "
                                          "row does not say")
    code: Optional[str] = Field(description="resolved_reason_code (flagged_scene_not_in_script)"
                                            "; null for a reopened row or another release")
    reason: Optional[str] = Field(description="resolved_reason / the reopen's why - the "
                                              "factory's line, as it is")
    task: Optional[str] = None
    flagged_scenes: List[str] = Field(description="the scene ids the flag rests on (reopened: "
                                                  "the row's scenes now; [] for the whole "
                                                  "topic)")
    script_scenes: List[str] = Field(description="the scene ids the video's scripts took")
    scripts: List[str] = Field(description="those scripts' ids")
    flagged_short: List[str] = Field(description="flagged_scenes without the topic's prefix "
                                                 "(s2)")
    script_short: List[str] = Field(description="script_scenes without the topic's prefix (s1)")
    signature_needed: bool = Field(description="false: released; true: reopened")
    line_ru: str = Field(description="the line in Russian - shown as is")


class ReleasedHold(HoldRow):
    release: HoldRelease


class ReleasedHolds(BaseModel):
    channel: Optional[str] = Field(description="the channel asked, null: every channel")
    path: str
    exists: bool
    problem: Optional[str] = Field(description="the ledger does not read - holds empty")
    as_of: str = Field(description="UTC ISO - now")
    since: str = Field(description="UTC ISO - now minus `days`")
    days: int
    limit: int
    total: int = Field(description="rows in the window (before `limit`)")
    released: int = Field(description="of them released")
    reopened: int = Field(description="of them reopened")
    holds: List[ReleasedHold] = Field(description="newest first, at most `limit`; a row whose "
                                                  "moment does not parse last")


class ApiSwitchRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    at: Optional[str] = None
    by: Optional[str] = None
    channel: Optional[str] = None
    action: Optional[str] = None
    note: Optional[str] = None
    warnings: List[str] = []


class ApiSwitchState(BaseModel):
    """`api_switch.channel_state` (CF-0607)."""
    model_config = ConfigDict(extra="allow")
    channel: str
    on: bool
    line: str = Field(description="the factory's line (Russian)")
    at: Optional[str] = None
    by: Optional[str] = None
    note: Optional[str] = None
    warnings: List[str] = []
    history: List[ApiSwitchRow]
    error: Optional[str] = Field(None, description="the state file does not read (then off)")


class ApiUpload(BaseModel):
    channel: Optional[str]
    path: str = Field(description="the switch's state file")
    channels: List[ApiSwitchState]
    warnings: Optional[List[str]] = Field(description="`warnings`: what enabling it would "
                                                      "warn about now")
    warnings_error: Optional[str]


class AwaitingTopic(BaseModel):
    """`rotate.awaiting_material` - a topic a refusal closed."""
    model_config = ConfigDict(extra="allow")
    script_id: Optional[str] = None
    batch_id: Optional[str] = None
    refused_at: Optional[str] = None
    state: str = Field(description="arrived / waiting / not-a-pool-question / no-baseline")
    assignable: bool
    retry_when: str = ""


class RotationReport(BaseModel):
    """`rotate.distribution_report` - what `rotate.py status` prints."""
    model_config = ConfigDict(extra="allow")
    channel: str
    eligible_pairs: List[str]
    blocked_pairs: Dict[str, Optional[str]]
    blocked_by: List[str]
    k_configured: int
    k_effective: int
    constrained: bool
    window: int
    assignments_total: int
    standing_total: int
    counts_in_window: Dict[str, int]
    counts_outside_vocabulary: Dict[str, int]
    spread: int
    no_repeat_violations: List[Any]
    rejections_upheld: int
    rejections_denied: int
    awaiting_material: List[AwaitingTopic]
    production_recoverable: Dict[str, Any]
    production_awaiting: Dict[str, Any]
    production_unrecorded: Dict[str, Any]


class ChannelRotation(BaseModel):
    channel: str
    ledger: str
    report: RotationReport


class PublisherBlock(BaseModel):
    channel: str
    ok: bool = Field(description="`publish_card.channel_config` takes the block")
    publisher: Optional[Dict[str, Any]] = Field(description="the channel's `publisher` block")
    error: Optional[str] = Field(description="its refusal - the card's templates live there")


class StudioStreak(BaseModel):
    """`studio_fields.streak`."""
    model_config = ConfigDict(extra="allow")
    streak: int = Field(description="Studio videos in a row with no hand edit")
    goal: int
    studio_videos: int
    done: bool
    run: List[Optional[str]]
    last_edited: Optional[Dict[str, Any]] = None


class ChannelStudio(BaseModel):
    channel: str
    journal: str
    journal_exists: bool
    rows: int = Field(description="the journal's rows of this channel (a row's `channel`, as "
                                  "`studio_fields.streak` reads it); 0 with no journal")
    withdrawn: List[WithdrawnRow] = Field(default_factory=list,
                                          description="CC-0179: those of the rows taken off the "
                                                      "feed into the копилка's reserve")
    streak: StudioStreak


class FormField(BaseModel):
    """`studio_fields.form_fields` - one question of Studio's form."""
    model_config = ConfigDict(extra="allow")
    value: Any = None
    studio: Optional[str] = Field(None, description="the answer as Studio words it")
    label: str
    source: str
    ask_user: Optional[str] = Field(None, description="the channel's settings are silent")


class StudioFields(BaseModel):
    """`studio_fields.prepare` - the fields as the orchestrator fills them."""
    model_config = ConfigDict(extra="allow")
    channel: str
    slug: str
    entry_id: str
    note: str
    video_file: str
    file_name: str
    title: str
    description: str
    tags: List[str]
    tags_input: str
    visibility: str
    visibility_studio: str
    schedule: Dict[str, Any] = Field(description="`schedule_of`: the slot in the slot's zone "
                                                 "as Studio's picker takes it")
    form: Dict[str, FormField]
    ask_user: List[str]
    notices: List[str]


class NoteBatch(BaseModel):
    """The batch the note's «Батч» line names (`card_batch`), its video
    (`publish_card.batch_video`)."""
    path: str = Field(description="«<dir>/<batch_id>» - the routes' form")
    dir: str
    batch_id: str
    channel: Optional[str]
    slug: Optional[str]
    script_id: Optional[str]
    topic_id: Optional[str]
    card_url: Optional[str] = Field(description="the batch's card (`api/videos.py`)")
    videos_url: Optional[str]
    error: Optional[str] = Field(description="the batch or its video is not there")


class PublishNote(BaseModel):
    channel: str
    day: str = Field(description="the bucket: YYYY-MM-DD, _queue or _reserve")
    slug: str
    path: str
    ready: bool = Field(description="`publish_card.placeable` (CF-0747): ready, or taken by the user's ruling (ruled) - what the placing reads")
    why: Optional[str] = None
    status: Optional[str] = Field(None, description="the marker's: ready / not_ready")
    title: str
    description: str
    view: str = Field(description="`publish_card.view` - what `publish_card.py show` prints")
    form: Dict[str, FormField]
    ask_user: List[str]
    studio: Optional[StudioFields] = Field(description="`studio_fields.prepare`; null when "
                                                       "it refuses")
    studio_refusal: Optional[str] = Field(description="why `prepare` refuses, the factory's "
                                                      "line")
    batch: Optional[NoteBatch]
    mark: Optional[Dict[str, Any]] = None
    raw: str
    card: Optional[CardState] = Field(None, description="CC-0127: the note's state "
                                                        "(card_status) and its batch video's last "
                                                        "build from the center")


# ---------------------------------------------------------------- publication writes (CC-0065)
class PublishWriteProblem(BaseModel):
    """A refusal of the publication writes - `{message, code, details}`; the
    message is the factory's line where it has one."""
    message: str = Field(description="for a human - shown as is")
    code: Literal["unknown_channel", "unknown_batch", "unknown_video", "invalid",
                  "note_required", "refused", "check_changed", "busy", "confirm_unknown",
                  "confirm_expired", "confirm_mismatch", "model_refused", "pause_unreadable",
                  "rotation_broken", "card_broken", "factory_broken",
                  # CC-0066: the switch, the upload, the Studio record
                  "audit_unconfirmed", "switch_unreadable", "answer_required", "unknown_note",
                  "reauthorize", "upload_failed", "uploaded_unrecorded",
                  # CC-0070: the hold's signature - `HoldSignError.code` (CF-0687), the
                  # message its `text_ru`; no_such_hold 404, empty_* 422, the rest 409
                  "no_such_hold", "already_signed", "already_resolved", "not_signable",
                  "empty_user", "empty_note", "ledger_unreadable", "holds_unreadable",
                  # CC-0106: the hand edit - the journal does not read
                  "journal_unreadable",
                  # CC-0182 (CF-0920): two videos of the name in one place, no batch named
                  "namesakes"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_PWPROBLEMS = {s: {"model": PublishWriteProblem} for s in (404, 409, 422, 500)}


class ConfirmIn(BaseModel):
    confirm: str = Field(description="the plan's `confirm` - what the plan was of is bound to it")


class PublishPlanBase(BaseModel):
    """The two steps of every publication write: the plan (read only) and a
    confirm token when it says ok - single use, `expires_in_s`, bound to the
    root, the channel, the action and the plan's input."""
    model_config = ConfigDict(extra="allow")
    action: Literal["pause_set", "pause_clear", "card_place", "card_build", "rotation_assign",
                    "rotation_reject", "rotation_refuse", "api_upload_switch", "api_upload",
                    "studio_record", "hold_sign", "studio_read_record", "studio_edited",
                    "studio_edited_undo"]
    channel: str
    ok: bool = Field(description="the factory would take it")
    why: Optional[str] = Field(None, description="why not, in Russian - shown as is")
    fingerprint: str = Field(description="sha256 of what the plan saw - the token is bound to it")
    confirm: Optional[str] = Field(None, description="the confirm token - only when ok")
    expires_in_s: Optional[int] = None


class PauseSetPlanIn(BaseModel):
    reason: str = Field(description="why - the factory requires it; stored «… (из центра)»")
    until: Optional[str] = Field(None, description="YYYY-MM-DD (00:00 МСК of that day) or ISO "
                                                   "with a zone; none: until cleared")
    replace: bool = Field(False, description="clear a standing pause and set this one")


class PauseClearPlanIn(BaseModel):
    note: Optional[str] = Field(None, description="stored «… (из центра)»")


class PausePlan(PublishPlanBase):
    state: Literal["free", "paused", "expired"] = Field(description="`channel_pause.status` now")
    line: str
    open_row: Optional[PauseRow] = None
    row: Optional[Dict[str, Any]] = Field(None, description="what is written / the row cleared")


class PauseWriteResult(BaseModel):
    action: Literal["pause_set", "pause_clear"]
    channel: str
    row: PauseRow = Field(description="the row the factory wrote / cleared")
    pause: ChannelPause = Field(description="the pause as it is now")


class CardPlacePlanIn(BaseModel):
    batch_id: str
    slug: str = Field(description="the video's slug or script_id")
    dir: Optional[str] = Field(None, description="the batch's folder under pipeline/ "
                                                 "(default: the channel; `rebuilds`)")
    day: Optional[str] = Field(None, description="YYYY-MM-DD or _queue - the folder the "
                                                 "batch's video lies in now, not the slot (CF-0857); "
                                                 "none: the batch's own video wherever it is "
                                                 "(publish_layout.of_batch), from _queue/ into "
                                                 "the next slot")
    replace: bool = False


class CardPlacePlan(PublishPlanBase):
    batch: Optional[str] = None
    slug: Optional[str] = None
    card: Optional[str] = Field(None, description="the batch's work/publish-card/<slug>.md")
    ready: Optional[bool] = None
    target: Optional[str] = Field(None, description="publish/<channel>/<bucket>/<slug>.md")
    target_exists: Optional[bool] = None
    slot: Optional[Dict[str, Any]] = Field(None, description="`publish_queue.plan_slot`: the "
                                                             "slot, day, moves, warnings; "
                                                             "CC-0179 `beyond_horizon`: slot "
                                                             "null, `note` says why - the card "
                                                             "stays in the копилка")
    paused: Optional[str] = Field(None, description="the card stays in _queue/: the pause")
    card_state: Optional[CardState] = Field(None, description="CC-0127: the batch card's "
                                                              "state; a build going refuses")


class CardPlaceResult(BaseModel):
    action: Literal["card_place"]
    channel: str
    slug: str
    path: str = Field(description="where the card is now")
    report: List[str] = Field(description="the factory's lines (PAUSED, WARNING, moved ...)")


class CardBuildPlanIn(BaseModel):
    batch_id: str
    slug: str
    dir: Optional[str] = None
    draft: Optional[Dict[str, Any]] = Field(None, description="{title, about, hashtags, tags} - "
                                                              "required: no model from the center")
    model: bool = Field(False, description="true is refused (`model_refused`) - nothing called")


class CardBuildPlan(PublishPlanBase):
    out: Optional[str] = None
    exists: Optional[bool] = None
    problems: List[str] = []


class CardBuildResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: Literal["card_build"]
    channel: str
    slug: str
    status: str = Field(description="`not_ready`: built with claims=False")
    path: str
    problems: List[Dict[str, Any]]
    mark: Dict[str, Any]
    view: str


# ---------------------------------------------------------------- the копилка (CC-0122)
STASH_PLACE_CODES = ("bad_who", "unknown_channel", "no_queue", "paused", "batch_open",
                     "empty_order", "check_changed", "dirty", "not_repo", "commit_refused",
                     "duplicate", "not_in_queue", "not_accepted", "held", "render_missing",
                     "batch_missing", "no_card", "card_building", "card_not_ready",
                     "note_differs", "no_slot", "place_failed")
STASH_REPAIR_CODES = ("not_found",)


class StashProblem(BaseModel):
    """A refusal of the копилка routes - `{message, code, details}`: the code
    the factory's (CF-0738 publish_stash / repair_queue), the center's
    (dirty, not_repo, commit_refused) or the token's; the message Russian."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal[STASH_PLACE_CODES + STASH_REPAIR_CODES
                  + ("invalid", "busy", "confirm_unknown", "confirm_expired", "confirm_mismatch",
                     "factory_broken")]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_SPROBLEMS = {s: {"model": StashProblem} for s in (404, 409, 422, 500)}


class StashCard(BaseModel):
    """The video's card: next to the video (`publish`) or still in the batch;
    CC-0127 its state (CF-0747 publish_stash._card)."""
    model_config = ConfigDict(extra="allow")
    present: bool
    where: Optional[Literal["publish", "batch"]] = None
    path: Optional[str] = Field(None, description="relative to the root")
    ready: Optional[bool] = Field(None, description="machine-ready (publish_card.card_state); "
                                                    "a ruled card is not, but is placeable")
    why_not: Optional[str] = None
    batch: Optional[str] = Field(None, description="the batch the card's «Батч» line names")
    state: Literal[CARD_STATES] = Field("none", description="none | building | ready | ruled "
                                                            "| not_ready")
    state_ru: Optional[str] = None
    placeable: bool = Field(False, description="ready or ruled - what the placing reads")
    reasons: List[str] = Field(default_factory=list)
    ruling: Optional[CardRuling] = None
    build: Optional[CardBuildRun] = None
    title: Optional[str] = Field(None, description="CF-0750: the card's `## Название` as the "
                                                   "card says it (the channel's « #shorts» "
                                                   "included); null: no card or no title")
    title_clean: Optional[str] = Field(None, description="`title` with its trailing hashtags "
                                                         "cut - for display")


class StashAge(BaseModel):
    """How long it waits, by the aging rule of CF-0741 (publish_stash.age_of):
    from the topic's dated news when there is one, else from the acceptance;
    stale strictly past 14 days - only marked, nothing refused from it. CF-0919:
    the rule is the news' - an evergreen video counts from the acceptance and is
    never stale."""
    accepted_days: Optional[int] = Field(None, description="days since the acceptance")
    news_at: Optional[str] = Field(None, description="the topic's newest dated news source "
                                                     "(01 evidence.sources[].published_at)")
    news_days: Optional[int] = None
    news_source: Optional[str] = Field(None, description="where news_at was read, or why not")
    basis: Optional[Literal["news", "accepted"]] = Field(
        None, description="what the age is counted from: `news` (the topic has a dated news "
                          "source), `accepted` (no dated news - an evergreen topic); null: "
                          "neither date on file")
    days: Optional[int] = Field(None, description="the age by `basis` (news_days or "
                                                  "accepted_days); null when unknown")
    stale: Optional[bool] = Field(None, description="days > 14 (staleness.threshold_days); "
                                                    "null when the age is unknown")


class StashKindMark(BaseModel):
    """CF-0919: a row of `publish/feed-kinds.json` - the kind set by hand."""
    model_config = ConfigDict(extra="allow")
    kind: Literal["news", "evergreen"]
    by: Optional[str] = None
    via: Optional[str] = None
    at: Optional[str] = Field(None, description="when, UTC")
    task: Optional[str] = Field(None, description="\"CF-0919\"")


class StashVideo(BaseModel):
    """One video of the pile (or of `not_queued`) as `publish_stash.stash` reads it."""
    model_config = ConfigDict(extra="allow")
    slug: str
    channel: str
    title: Optional[str] = Field(None, description="CF-0750: the card's `## Название` as the "
                                                   "card says it (the channel's « #shorts» "
                                                   "included), else the topic's `title_ref` in "
                                                   "the batch's 01; null: neither")
    title_source: Optional[Literal["card", "topic"]] = Field(
        None, description="where `title` was read: `card` | `topic`; null: no title")
    title_clean: Optional[str] = Field(None, description="`title` with its trailing hashtags "
                                                         "cut (« #shorts») - for display")
    entry_id: Optional[str] = None
    batch_id: Optional[str] = None
    verdict: Optional[str] = None
    kind: Optional[Literal["batch", "rebuild"]] = Field(None, description="null: the batch is "
                                                                          "not on disk")
    batch_dir: Optional[str] = Field(None, description="pipeline/<dir>/<batch>")
    accepted_at: Optional[str] = None
    recorded_at: Optional[str] = None
    pending: bool = Field(description="the verdict still queued under a batch")
    in_queue: bool = Field(description="in the копилка: publish/<c>/_queue/ or _reserve/ "
                                       "(false: not_queued)")
    bucket: Optional[Literal["_queue", "_reserve"]] = Field(
        None, description="CF-0919: which of the two folders - the `day` of its note; null: "
                          "not_queued, or an older factory")
    mp4: Optional[str] = Field(None, description="publish/<c>/<bucket>/<slug>.mp4")
    mp4_present: bool
    source_mp4: Optional[str] = Field(None, description="the batch's render")
    thumbnail: Optional[str] = None
    card: StashCard
    held: bool = Field(description="an unsigned publication hold (CF-0318)")
    hold_id: Optional[str] = None
    topic_id: Optional[str] = None
    age: StashAge
    feed_kind: Literal["news", "evergreen"] = Field(
        "evergreen", description="CC-0179 (CF-0919: by the video's own fact - a dated source no "
                                 "longer makes it news): `news` - words about what is to come, "
                                 "or a date ahead or a fresh one in its title, description or "
                                 "claims; `evergreen` - no aging, the reserve of the feed. "
                                 "`kind_mark` overrides the fact. An older factory's video "
                                 "reads as evergreen")
    kind_mark: Optional[StashKindMark] = Field(None, description="CF-0919: the driver's mark of "
                                                                 "the kind (`publish_stash.py "
                                                                 "kind`); null: by the fact")
    news_why: Optional[str] = Field(None, description="why it is news: the fact's words in «» "
                                                      "(a date with its reason), or "
                                                      "«вид поставлен руками...»; null: evergreen")
    stale_at: Optional[str] = Field(None, description="news only: the day it goes stale, "
                                                      "YYYY-MM-DD (a date the fact names ahead, "
                                                      "else the news date, the headline's fresh "
                                                      "date or the acceptance + 14 days); null: "
                                                      "evergreen or no date known")
    reserve: bool = Field(False, description="withdrawn from the feed (a journal row with "
                                             "`withdrawn`): in Studio already, comes back with "
                                             "no new upload")
    video_id: Optional[str] = Field(None, description="the Studio video id of a video in the "
                                                      "reserve; null otherwise")
    mp4_url: Optional[str] = Field(None, description="GET - the batch's render through "
                                                     "/batches/{dir}/{batch}/videos/{slug}/mp4; "
                                                     "null when that route would not serve it")
    preview_url: Optional[str] = Field(None, description="GET - the batch video's preview")
    videos_url: Optional[str] = Field(None, description="the batch's videos list")
    queue_code: Optional[str] = Field(None, description="not_queued: what the repair would do "
                                                        "(acceptance.queue_accepted's code)")
    queue_text_ru: Optional[str] = None
    repair: Optional[str] = Field(None, description="not_queued: the factory's command; "
                                                    "other_version: the factory's command "
                                                    "that places it as a new video "
                                                    "(`runlog acceptance --enqueue-accepted "
                                                    "--entry <entry_id> --other-version-ok "
                                                    "--apply`) - data to show, no route runs it")


class StashOtherVersion(StashVideo):
    """CC-0186 (CF-0921): an accepted row left out of the копилка as another version of a
    video already placed (`queue_code` `other_version_placed`) only because the record
    has no topic or no fact to tell a new video from a version
    (`acceptance.VERSION_UNSURE`), and nobody settled it. The driver decides: a new
    video goes in with the factory's `repair` command, a version stays out. A sure
    version and a settled row are not listed. Read only - the center shows it."""
    other_entry: Optional[str] = Field(None, description="the entry id of the placed version "
                                                         "(<channel>/<batch>/<slug>)")
    other_path: Optional[str] = Field(None, description="where the placed version is "
                                                        "(its `publish_path`)")
    other_why: Optional[str] = Field(None, description="in Russian: why the rule took it for a "
                                                       "version - here always that the record "
                                                       "has no topic or no fact to tell")


class StashStaleness(BaseModel):
    """The factory's aging rule of the pile (publish_stash.STALENESS, CF-0741)."""
    model_config = ConfigDict(extra="allow")
    rule: Optional[str] = Field(None, description="the factory task that set the rule "
                                                  "(\"CF-0741\"); null on an older factory "
                                                  "with no rule")
    decided: Optional[str] = Field(None, description="when and by whom the rule was decided")
    threshold_days: Optional[int] = Field(None, description="14 - a video older is stale")
    stale_when: Optional[str] = Field(None, description="\"days > 14\"")
    basis: Optional[str] = Field(None, description="in Russian: what the age is counted from")
    only_marks: Optional[bool] = Field(None, description="true - a stale video is only "
                                                         "marked, placing is not refused")
    note: Optional[str] = None


class StashHorizon(BaseModel):
    """CC-0179 (CF-0918, `publish_queue.horizon`): how far ahead a video is put
    into a slot by itself."""
    days: int = Field(description="the channel's min_feed_days")
    last_day: str = Field(description="the last Moscow day a slot may fall on, YYYY-MM-DD: "
                                      "today (МСК) + days")
    source: str = Field(description="where `days` was read (the channel's settings, or the "
                                    "default and why)")


class PublishStash(BaseModel):
    """`publish_stash.stash`: the channel's копилка with its details."""
    channel: str
    task: str
    now: Optional[str] = None
    count: int
    stale: int = Field(0, description="how many videos of the pile are stale (age.stale)")
    videos: List[StashVideo]
    not_queued: List[StashVideo] = Field(description="accepted rows with no place in publish/ "
                                                     "- what the repair would put in _queue/")
    other_version: List[StashOtherVersion] = Field(
        default_factory=list,
        description="CC-0186 (CF-0921): accepted rows left out as another version of a placed "
                    "video only because the rule could not tell a new video from a version - "
                    "the driver's call (a new video: the item's `repair` with "
                    "--other-version-ok; a version: stays out). Not on the notification bus; "
                    "the factory writes one line to notify/stash-events.jsonl. Empty on an "
                    "older factory")
    staleness: StashStaleness
    news: int = Field(0, description="CC-0179: how many videos of the pile are news")
    reserve: int = Field(0, description="CC-0179: how many videos of the pile are in the "
                                        "reserve (withdrawn from the feed, with a video id)")
    horizon: Optional[StashHorizon] = Field(None, description="CC-0179: the channel's horizon; "
                                                              "null on an older factory")


class StashPlaceIn(BaseModel):
    order: List[str] = Field(default_factory=list,
                             description="the slugs (or <batch>/<slug>) to place, in order - "
                                         "onto the nearest free slots; empty with `auto`. "
                                         "CC-0182 (CF-0920): with two videos of one name "
                                         "waiting only <batch>/<slug> places (bare: "
                                         "`not_in_queue` naming the batches)")
    auto: bool = Field(False, description="CC-0179 (CF-0918): name no videos - the factory's "
                                          "own order (fresh news first, then the reserve), as "
                                          "many as the free slots inside the horizon take")
    force: bool = Field(False, description="with `auto`: a stale news video may be chosen too")


class StashRefusal(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: str = Field(description="one of " + ", ".join(STASH_PLACE_CODES))
    line: Optional[str] = Field(None, description="the factory's (or the center's) line")
    message: str = Field(description="the center's Russian message for the code")
    slug: Optional[str] = Field(None, description="the video's, for a per-video refusal")


class StashPlaceItem(BaseModel):
    model_config = ConfigDict(extra="allow")
    slug: str
    batch_id: Optional[str] = None
    entry_id: Optional[str] = None
    ok: bool
    slot: Optional[str] = Field(None, description="the slot, ISO")
    day: Optional[str] = Field(None, description="the day folder (МСК day)")
    label: Optional[str] = Field(None, description="the slot as the queue says it")
    stale: Optional[bool] = Field(None, description="the video's age.stale (CF-0741, display "
                                                    "only - never a refusal); null when not "
                                                    "in the копилка or the age is unknown")
    age_days: Optional[int] = Field(None, description="the video's age.days")
    age_basis: Optional[Literal["news", "accepted"]] = Field(None, description="the video's "
                                                                               "age.basis")
    beyond_horizon: bool = Field(False, description="CC-0179: its `no_slot` is the horizon - a "
                                                    "free slot exists past it")
    feed_kind: Optional[Literal["news", "evergreen"]] = Field(None, description="CC-0179: the "
                                                                                "video's; null "
                                                                                "when not in "
                                                                                "the копилка")
    stale_at: Optional[str] = Field(None, description="CC-0179: the video's")
    reserve: bool = Field(False, description="CC-0179: from the reserve - no new upload; a "
                                             "STUDIO line in `warnings` says what Studio needs")
    video_id: Optional[str] = Field(None, description="CC-0179: of a video in the reserve")
    refusals: List[StashRefusal]
    warnings: List[str] = Field(description="the queue's candidate checks (a CF-0042 window "
                                            "swap may happen at confirm), STALE (a stale news "
                                            "video named by hand), STUDIO (a reserve video: "
                                            "«Отложенная публикация» in Studio is a human's)")
    placed: Optional[bool] = Field(None, description="confirm: placed")
    path: Optional[str] = Field(None, description="confirm: where the card is now")
    report: Optional[List[str]] = Field(None, description="confirm: the factory's lines")


class StashSkipped(BaseModel):
    """CC-0179: a video the auto placement left waiting (the factory's `skipped`)."""
    slug: str = Field(description="the video's name, plain")
    batch_id: Optional[str] = Field(None, description="CC-0182 (CF-0920): which video of the name")
    reason: str = Field(description="`stale_news` | `beyond_horizon` | CF-0919: "
                                    "`no_card` | `card_building` | `card_not_ready` | "
                                    "`note_differs` - the factory's")
    line: Optional[str] = Field(None, description="the factory's line")
    message: str = Field(description="the center's Russian message for the reason")


class StashPlaceBase(BaseModel):
    action: Literal["stash_place"]
    channel: str
    ok: bool
    dry_run: bool
    auto: bool = Field(False, description="CC-0179: the order is the factory's own choice")
    force: bool = Field(False, description="CC-0179: with auto - stale news may be chosen")
    order: List[str] = Field(description="the videos in order - the named ones, or with `auto` "
                                         "the factory's choice")
    skipped: List[StashSkipped] = Field(default_factory=list,
                                        description="CC-0179, `auto`: what waits in the копилка "
                                                    "and why; empty otherwise")
    items: List[StashPlaceItem]
    refusals: List[StashRefusal]
    lines: List[str] = Field(description="the factory's line per video; a stale one ends "
                                         "with « (устарел: N дн.)» (CF-0741)")
    base_sha256: Optional[str] = Field(None, description="publish_stash.state_sha256 of the "
                                                         "plan")
    placed: int = Field(description="plan: the videos that would place; confirm: placed")


class StashPlacePlan(StashPlaceBase):
    """The factory's place_plan (by user via center) + not_repo / dirty -
    nothing written; a token only when every video places."""
    why: Optional[str] = Field(None, description="in Russian, why no token")
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class StashPlaceResult(StashPlaceBase):
    """The placement and its one commit (the center's - place_confirm does not
    commit)."""
    written: bool
    new_sha256: Optional[str] = None
    touched: List[str] = Field(description="the files the placement changed, from the root")
    touched_from: Literal["factory", "git_status"] = Field(
        description="`factory`: place_confirm's touched; `git_status`: the status over "
                    "publish/<c>/, README, the record, the ledger after minus before")
    committed: List[str] = Field(description="what went into the commit (gitignored left out)")
    commit: Optional[str] = Field(None, description="the commit's sha; null: nothing to commit")
    by: str
    via: str


class StashRepairIn(BaseModel):
    entries: Optional[List[str]] = Field(None, description="entry ids among the channel's "
                                                           "not_queued; none: all of them")


class StashRepairItem(BaseModel):
    entry_id: Optional[str] = None
    slug: Optional[str] = None
    batch_id: Optional[str] = None
    code: str = Field(description="acceptance.queue_accepted's code (" + ", ".join(
        ACCEPT_QUEUE_CODES) + ")")
    text_ru: Optional[str] = None
    ok: Optional[bool] = None
    skipped: Optional[bool] = None
    refused: Optional[bool] = None
    changed: Optional[bool] = None
    publish_path: Optional[str] = None


class StashRepairBase(BaseModel):
    action: Literal["stash_repair"]
    channel: str
    ok: bool
    dry_run: bool
    entries: List[str]
    items: List[StashRepairItem]
    refusals: List[Dict[str, Any]] = Field(description="{code, line, message, entry_id?}")
    lines: List[str]
    sha256: Optional[str] = Field(None, description="the acceptance record's sha256")
    log: Optional[str] = None


class StashRepairPlan(StashRepairBase):
    why: Optional[str] = None
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class StashRepairResult(StashRepairBase):
    written: bool
    new_sha256: Optional[str] = None
    commit: Optional[str] = Field(None, description="the factory's commit of the record")
    by: str
    via: str


# ---------------------------------------------------------------- moving a placed video (CC-0165)
MOVE_TOP_CODES = ("bad_who", "unknown_channel", "no_queue", "empty_order", "batch_open",
                  "check_changed", "apply_failed", "commit_refused", "dirty", "not_repo")
MOVE_ITEM_CODES = ("bad_order", "duplicate", "not_found", "in_queue", "ambiguous",
                   "inconsistent", "published", "in_studio", "bad_day", "same_day",
                   "no_slot_day", "day_taken", "too_soon",
                   # CC-0179 (CF-0918 WITHDRAW_REFUSALS): only a withdraw gives these
                   "not_in_studio", "in_reserve", "not_placed", "reserve_taken")


class MoveProblem(BaseModel):
    """A refusal of the move routes - `{message, code, details}`: the
    factory's code (CF-0856 publish_move TOP_REFUSALS / ITEM_REFUSALS, CF-0918
    WITHDRAW_REFUSALS), the center's (dirty, not_repo) or the token's; the
    message Russian."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal[MOVE_TOP_CODES + MOVE_ITEM_CODES
                  + ("invalid", "busy", "confirm_unknown", "confirm_expired", "confirm_mismatch",
                     "factory_broken")]
    details: List[str] = Field(description="technical lines (behind «подробнее»); a write "
                                           "that stopped after writing ends with "
                                           "`touched: <paths>`")


_MPROBLEMS = {s: {"model": MoveProblem} for s in (404, 409, 422, 500)}


class MoveEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    slug: str = Field(description="the video's name - in a day folder of publish/<channel>/ or "
                                  "in the upload journal", max_length=400)
    batch_id: Optional[str] = Field(None, description="CC-0182 (CF-0920): which of two videos of "
                                                      "the name; none: the factory's own reading "
                                                      "(`ambiguous` when it cannot tell)",
                                    max_length=200)
    day: str = Field(description="the day it moves to, YYYY-MM-DD (the channel's slot of that "
                                 "day, the first free one)", max_length=40)


class MovePlanIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    moves: List[MoveEdit] = Field(default_factory=list, description="the videos to move, "
                                                                    "judged as one plan with "
                                                                    "the unplaces and the "
                                                                    "withdraws - the order "
                                                                    "does not matter; a video "
                                                                    "of the reserve comes back "
                                                                    "with no new upload")
    unplace: List[str] = Field(default_factory=list, description="the videos to take back into "
                                                                 "the копилка (_queue/) - only "
                                                                 "ones not in Studio; a bare "
                                                                 "name means the placed one, "
                                                                 "<batch>/<slug> names which "
                                                                 "(CC-0182)")
    withdraw: List[str] = Field(default_factory=list, description="CC-0179 (CF-0918): the videos "
                                                                  "in Studio, their slot ahead, "
                                                                  "to take off the feed into "
                                                                  "the копилка's reserve "
                                                                  "(_reserve/, CF-0919) - "
                                                                  "after Studio: «Ограниченный "
                                                                  "доступ» is set by a human; a "
                                                                  "bare name means the placed "
                                                                  "one, <batch>/<slug> names "
                                                                  "which (CC-0182)")


class MoveConfirmIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirm: str = Field(description="the plan's `confirm` - the moves, the unplaces, the "
                                     "withdraws and the plan's base_sha256 are bound to it")
    base_sha256: Optional[str] = Field(None, description="the plan's base_sha256 sent back; "
                                                         "not the token's - 409 check_changed")


class MoveRefusal(BaseModel):
    code: Literal[MOVE_TOP_CODES + MOVE_ITEM_CODES]
    line: Optional[str] = Field(None, description="the factory's (or the center's) line")
    message: str = Field(description="the center's Russian message for the code")
    slug: Optional[str] = Field(None, description="the video's, for a per-video refusal")


class MoveJournal(BaseModel):
    from_at: Optional[str] = Field(None, description="the journal row's publish_at before")
    to_at: Optional[str] = Field(None, description="the journal row's publish_at now")


class MoveItem(BaseModel):
    op: Literal["move", "unplace", "withdraw"]
    slug: str
    batch_id: Optional[str] = None
    video_id: Optional[str] = Field(None, description="the Studio video id (a live journal row)")
    in_studio: bool = Field(description="a live row of publish/uploads.json - a move rewrites "
                                        "it, an unplace is refused, a withdraw marks it")
    reserve: bool = Field(False, description="CC-0179 (CF-0918): a move of a video in the "
                                             "копилка's reserve - it comes back with no new "
                                             "upload; from_day and from_slot null")
    ok: bool
    from_day: Optional[str] = Field(None, description="the day it is on now")
    from_slot: Optional[str] = Field(None, description="its slot now, UTC ISO")
    day: Optional[str] = Field(None, description="move: the day it goes to")
    slot: Optional[str] = Field(None, description="move: the slot it takes, UTC ISO")
    label: Optional[str] = Field(None, description="move: the slot as the queue says it")
    refusals: List[MoveRefusal]
    warnings: List[str] = Field(description="the queue's candidate checks (WINDOW - never a "
                                            "refusal, the day is the user's), HORIZON (a "
                                            "day past the channel's horizon - written as "
                                            "named) and, for a video in Studio, the STUDIO "
                                            "line: the date (or «Ограниченный доступ» of a "
                                            "withdraw) in Studio is set by a human")
    path: Optional[str] = Field(None, description="confirm: where the note is now")
    journal: Optional[MoveJournal] = Field(None, description="confirm, a video in Studio: the "
                                                             "journal row's publish_at change "
                                                             "(a withdraw: to_at null; a return "
                                                             "from the reserve: from_at null)")


class MoveBase(BaseModel):
    action: Literal["publish_move"]
    channel: str
    ok: bool
    dry_run: bool
    task: Optional[str] = Field(None, description="\"CF-0856\"")
    moves: List[MoveEdit]
    unplace: List[str]
    withdraw: List[str] = Field(default_factory=list, description="CC-0179: the withdraws named")
    items: List[MoveItem] = Field(description="the unplaces first, then the withdraws, then the "
                                              "moves")
    refusals: List[MoveRefusal]
    warnings: List[str] = Field(description="the plan's own (PAUSE: the channel is paused - "
                                            "the moves are written, nothing goes out)")
    lines: List[str] = Field(description="the factory's line per edit and its warnings")
    ledger: Optional[str] = Field(None, description="why the rotation ledger is not touched")
    base_sha256: Optional[str] = Field(None, description="publish_stash.state_sha256 of the "
                                                         "plan")
    sha256: Optional[str] = Field(None, description="the state the factory saw")
    moved: int = Field(description="plan: the moves that would go; confirm: moved")
    unplaced: int = Field(description="plan: the unplaces that would go; confirm: unplaced")
    withdrawn: int = Field(0, description="CC-0179 - plan: the withdraws that would go; confirm: "
                                          "taken off the feed into the reserve")
    by: str
    via: str


class MovePlan(MoveBase):
    """The factory's move_plan (by user via center) + not_repo / dirty -
    nothing written; a token only when every edit is ok."""
    why: Optional[str] = Field(None, description="in Russian, why no token")
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class MoveResult(MoveBase):
    """The moves written and the factory's one commit of exactly the files it
    touched (move_confirm commits itself)."""
    written: bool
    new_sha256: Optional[str] = None
    commit: Optional[str] = Field(None, description="the factory's commit; null: nothing to "
                                                    "commit")
    touched: List[str] = Field(description="the files the move changed, from the root (the "
                                           "gitignored mp4s among them - never committed)")


# ---------------------------------------------------------------- the card from the center (CC-0127)
CARD_BUILD_REFUSAL_CODES = ("bad_who", "unknown_channel", "batch_missing", "unknown_video",
                            "bad_draft", "running", "spawn_failed", "batch_required",
                            "namesakes")
CARD_RULING_CODES = ("bad_who", "bad_words", "unknown_channel", "batch_missing",
                     "unknown_video", "not_accepted", "building", "no_card", "card_ready",
                     "claims_not_failed", "failing_unknown", "note_claim_failed",
                     "card_problem", "no_video", "check_changed", "place_failed",
                     "not_repo", "dirty", "commit_refused", "namesakes")


class CardCenterProblem(BaseModel):
    """A refusal of the card routes - `{message, code, details}`: the
    factory's code (card_center BUILD_REFUSALS / RULING_REFUSALS), the
    center's (batch_required, not_repo, dirty, commit_refused) or the token's;
    the message the center's Russian line, the factory's in `details`."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal[tuple(dict.fromkeys(
        CARD_BUILD_REFUSAL_CODES + CARD_RULING_CODES
        + ("invalid", "busy", "confirm_unknown", "confirm_channel", "confirm_expired",
           "confirm_mismatch", "factory_broken", "bad_run", "unknown_run")))]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_CPROBLEMS = {s: {"model": CardCenterProblem} for s in (404, 409, 422, 500)}


class CardCenterRefusal(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: str
    line: Optional[str] = Field(None, description="the factory's (or the center's) line")
    message: str = Field(description="the center's Russian line for the code")


class CardInfo(CardState):
    """`card_center.card_info`: the card of one video as the center shows it."""
    channel: str
    slug: str
    batch_id: Optional[str] = None
    path: Optional[str] = Field(None, description="the batch's work/publish-card/<slug>.md")
    refusals: List[CardCenterRefusal] = Field(default_factory=list)


class CardBuildLaunchPlanIn(BaseModel):
    batch_id: Optional[str] = Field(None, description="the batch; none - the channel's latest "
                                                      "accepted video of this slug")
    draft: Optional[Dict[str, Any]] = Field(None, description="{title, about, hashtags, tags} "
                                                              "- the model then only checks "
                                                              "the claims; none - the model "
                                                              "drafts")


class CardBuildPlanCard(CardState):
    path: Optional[str] = None


class CardBuildLaunchPlan(BaseModel):
    """What «Собрать заново» would start - nothing started; a token when ok."""
    model_config = ConfigDict(extra="allow")
    action: Literal["card_build_launch"]
    channel: str
    slug: str
    batch_id: str
    ok: bool
    dry_run: bool
    draft: Optional[Dict[str, Any]] = None
    with_draft: bool
    what: str = Field(description="in Russian: what the build does (with the model or from "
                                  "the draft)")
    replaces: Optional[str] = Field(None, description="in Russian: what happens to the card "
                                                      "there now (a ruled one loses the ruling)")
    card: CardBuildPlanCard
    problems: List[str] = Field(description="the draft's problems (validate_draft)")
    refusals: List[CardCenterRefusal]
    why: Optional[str] = None
    by: str
    via: str
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class CardBuildStarted(BaseModel):
    """`card_build_launch` by user via center - the build goes on detached."""
    model_config = ConfigDict(extra="allow")
    action: Literal["card_build_launch"]
    channel: str
    slug: str
    batch_id: str
    ok: bool
    launched: bool
    skipped: Optional[str] = None
    run_id: Optional[str] = None
    pid: Optional[int] = None
    log: Optional[str] = Field(None, description="the build's log, relative to the root")
    draft: Optional[str] = Field(None, description="the draft's file the build reads")
    card: Optional[Dict[str, Any]] = Field(None, description="{state, path} before the build")
    lines: List[str]
    by: str
    via: str
    result_url: Optional[str] = Field(None, description="GET - what the build came to")
    poll_s: Optional[int] = None


class CardBuildOutcome(BaseModel):
    """`card_build_result(run_id)` with the center's Russian line."""
    model_config = ConfigDict(extra="allow")
    run_id: Optional[str] = None
    log: Optional[str] = None
    code: Literal[CARD_BUILD_CODES]
    word: str = Field(description="the factory's word (card_center.OUTCOME_WORDS)")
    text_ru: str = Field(description="the center's line for the code")
    done: bool
    line: str
    detail: Optional[str] = None
    state: Optional[str] = Field(None, description="the card's state after the build")
    reasons: List[str] = Field(default_factory=list)
    path: Optional[str] = None
    channel: Optional[str] = None
    slug: Optional[str] = None
    batch_id: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    poll_s: Optional[int] = None


class CardRulingPlanIn(BaseModel):
    batch_id: Optional[str] = Field(None, description="the batch; none - the channel's latest "
                                                      "accepted video of this slug")
    words: str = Field(description="the user's own words of the ruling (up to 1000 chars) - "
                                   "they go into the card")


class CardFailing(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: Optional[str] = None
    where: Optional[str] = Field(None, description="claims/<field> - commentary, hook, "
                                                   "payoff, on_screen, plate")
    video: Optional[Any] = Field(None, description="the claim is of the video's own words")
    text: Optional[str] = None


class CardRulingBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: Literal["card_ruling"]
    ok: bool
    dry_run: bool
    channel: Optional[str] = None
    slug: str
    batch_id: Optional[str] = None
    by: Optional[str] = None
    via: Optional[str] = None
    words: Optional[str] = None
    base_sha256: Optional[str] = None
    sha256: Optional[str] = Field(None, description="the card and the note now - the base "
                                                    "of the confirm")
    failing: List[CardFailing] = Field(description="the video's own claims that failed")
    card: Optional[str] = Field(None, description="the batch's card")
    path: Optional[str] = Field(None, description="the note in publish/ the card goes to")
    state: Optional[str] = None
    state_ru: Optional[str] = None
    scope: str = Field(description="in Russian: the ruling covers only the video's own claims")
    refusals: List[CardCenterRefusal]
    lines: List[str]


class CardRulingPlan(CardRulingBase):
    why: Optional[str] = None
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class CardRulingResult(CardRulingBase):
    written: bool
    new_sha256: Optional[str] = None
    touched: List[str] = Field(description="the files the ruling wrote (card_center's)")
    committed: List[str] = Field(description="the ones committed (gitignored left out)")
    commit: Optional[str] = None


class RotationAssignPlanIn(BaseModel):
    batch_id: str
    script_ids: List[str]
    despite_shortage: bool = Field(False, description="the person looked at the census and "
                                                      "disagrees (rotate.py --despite-shortage)")


class RotationRejectPlanIn(BaseModel):
    script_id: str
    reason: str = Field(description="at least rotate.MIN_REASON_CHARS characters")
    rejects_rhythm: bool = False
    batch_id: Optional[str] = None


class RotationRefusePlanIn(BaseModel):
    script_id: str
    reason: str
    deficit: str = Field(description="pipeline/... plan.assetless-rung.json, from the root")
    batch_id: Optional[str] = None


class RotationPlan(PublishPlanBase):
    pass


class RotationResult(BaseModel):
    action: Literal["rotation_assign", "rotation_reject", "rotation_refuse"]
    channel: str
    result: Any = Field(description="rotate.assign / reject / refuse as it returns")


# ---------------------------------------------------------------- the switch, the upload (CC-0066)
class SwitchPlanIn(BaseModel):
    on: bool = Field(description="true - turn the API upload on, false - off")
    note: Optional[str] = Field(None, description="turning it on: required - where and when the "
                                                  "user decided (after the audit, CF-0470); "
                                                  "stored «… (из центра)»")


class SwitchConfirmIn(ConfirmIn):
    audit: Optional[str] = Field(None, description="turning it on: the user types «аудит "
                                                   "подтверждаю» (`audit_phrase` of the plan); "
                                                   "else 422 `audit_unconfirmed`")


class SwitchPlan(PublishPlanBase):
    on: bool = Field(description="what the plan turns the switch to")
    state: ApiSwitchState = Field(description="`api_switch.channel_state` now")
    line: str
    row: Dict[str, Any] = Field(description="what `set_switch` gets: channel, on, by, note")
    warnings: Optional[List[str]] = Field(None, description="turning it on: `api_switch."
                                                            "warnings` - what is not ready "
                                                            "(never a refusal)")
    audit_phrase: Optional[str] = Field(None, description="turning it on: the words the "
                                                          "confirm takes")
    path: str = Field(description="the switch's state file")


class SwitchResult(BaseModel):
    action: Literal["api_upload_switch"]
    channel: str
    on: bool
    changed: bool
    warnings: List[str] = Field(description="written into the history row on enable")
    state: ApiSwitchState


class UploadPlanIn(BaseModel):
    slug: str = Field(description="the placed note's slug - publish/<channel>/<day>/<slug>.md")
    batch_id: Optional[str] = Field(None, description="CC-0182 (CF-0920): which of two videos "
                                                      "of one name - the `batch_id` of its row "
                                                      "in GET /publish/{c}/stash; none with two "
                                                      "in one place: 409 `namesakes` naming the "
                                                      "batches")
    day: Optional[str] = Field(None, description="YYYY-MM-DD or _queue - the folder of the note, which of two "
                                                 "notes of one name; none: the one place of the "
                                                 "name not in the upload journal (two or more: "
                                                 "404 unknown_note naming the day, CF-0857)")
    entry: Optional[str] = Field(None, description="CHANNEL/BATCH/SLUG when the name was "
                                                   "accepted in several batches")


class UploadConfirmIn(ConfirmIn):
    answer: str = Field(description="the user's own answer, typed after reading `summary` and "
                                    "`tos_notice`: «да» (upload_gate.YES); else 422 "
                                    "`answer_required` and the token is not spent")


class UploadPlan(PublishPlanBase):
    slug: str
    day: str = Field(description="the note's folder: a day or _queue")
    note: str = Field(description="publish/<channel>/<day>/<slug>.md")
    video: str
    entry_id: Optional[str] = Field(None, description="the acceptance row the upload is of")
    switch: ApiSwitchState = Field(description="`api_switch.channel_state` - off: no token")
    dry_run: List[str] = Field(description="what `upload.py --dry-run` printed")
    summary: Optional[str] = Field(None, description="`upload.summary` - what the user is shown "
                                                     "before the question")
    body: Optional[Dict[str, Any]] = Field(None, description="`upload.build_body` - the request "
                                                             "body of videos.insert")
    tos_notice: Optional[str] = Field(None, description="`upload_gate.TOS_NOTICE` (CF-0618) - "
                                                        "shown before the answer")
    question: Optional[str] = None
    channel_id: Optional[str] = Field(None, description="PUBLISHER_CHANNEL_ID")
    token: Optional[str] = Field(None, description="`publisher_auth.status` - the token's line "
                                                   "(its file, never the network)")
    publish_at: Optional[str] = Field(None, description="the slot, UTC - private until then")


class UploadResult(BaseModel):
    action: Literal["api_upload"]
    channel: str
    slug: str
    row: Optional[Dict[str, Any]] = Field(description="the journal row it wrote (source api)")
    lines: List[str] = Field(description="what `upload.py` printed")
    shown: str = Field(description="what was shown before the answer: the summary, the Terms")


class StudioRecordPlanIn(BaseModel):
    slug: str = Field(description="the placed note's slug")
    batch_id: Optional[str] = Field(None, description="CC-0182 (CF-0920): which of two videos "
                                                      "of one name - the `batch_id` of its row "
                                                      "in GET /publish/{c}/stash; none with two "
                                                      "in one place: 409 `namesakes` naming the "
                                                      "batches")
    day: Optional[str] = Field(None, description="YYYY-MM-DD or _queue - the folder of the note, which of two "
                                                 "notes of one name; none: the one place of the "
                                                 "name not in the upload journal (two or more: "
                                                 "404 unknown_note naming the day, CF-0857)")
    video_id: str = Field(description="the id Studio shows (11 characters)")
    read: Dict[str, Any] = Field(description="what Studio shows after saving: {title, "
                                             "description, tags, visibility, schedule | "
                                             "publish_at, video_id?, url?} - studio_fields.py's "
                                             "read JSON")
    replaces: Optional[str] = Field(None, description="the video id a re-upload replaces")


class StudioRecordPlan(PublishPlanBase):
    slug: str
    day: str
    note: str
    video_id: str
    replaces: Optional[str] = None
    mismatches: List[Dict[str, Any]] = Field(description="`studio_fields.compare`: field, "
                                                         "expected (the card), read (Studio)")
    status: Optional[str] = Field(None, description="`record(dry_run=True)`: would-add | exists")
    row: Optional[Dict[str, Any]] = Field(None, description="the journal row it would add")


class StudioRecordResult(BaseModel):
    action: Literal["studio_record"]
    channel: str
    slug: str
    status: str = Field(description="added | exists")
    row: Dict[str, Any] = Field(description="the journal row (source studio, user_edited false)")
    ledger: Optional[Dict[str, Any]] = Field(None, description="`publish_window."
                                                               "record_published` - or its error")
    streak: StudioStreak


# ---------------------------------------------------------------- the hand edit (CC-0106)
class StudioEditedPlanIn(BaseModel):
    video_id: Optional[str] = Field(None, description="the video's id (11 characters) - or `slug`, "
                                                      "exactly one of the two")
    slug: Optional[str] = Field(None, description="the slug, when one live row of that name is "
                                                  "on the channel")
    note: Optional[str] = Field(None, description="what the user corrected; stored as "
                                                  "`user_edit_note` as given (by/via go on "
                                                  "the row: user_edited_by / user_edited_via)")


class StudioEditedPlan(PublishPlanBase):
    edited: bool = Field(description="true: the mark; false: its undo")
    video_id: Optional[str] = None
    slug: Optional[str] = None
    note: str = Field(description="the note the factory will store as given; empty - none "
                                  "given (a mark keeps the row's note, an undo drops it)")
    by: Literal["user"] = Field("user", description="CC-0117: `user_edited_by` of the row")
    via: Literal["center"] = Field("center", description="`user_edited_via` of the row")
    before: Optional[Dict[str, Any]] = Field(None, description="the journal row now")
    row: Optional[Dict[str, Any]] = Field(None, description="the row after `mark_user_edited` "
                                                            "(its own dry run, CF-0720)")
    streak: Optional[StudioStreak] = Field(None, description="`studio_fields.streak` after it")
    journal: str


class StudioEditedResult(BaseModel):
    action: Literal["studio_edited", "studio_edited_undo"]
    channel: str
    edited: bool = Field(description="`user_edited` of the row now")
    by: Literal["user"] = "user"
    via: Literal["center"] = "center"
    row: Dict[str, Any] = Field(description="the journal row `mark_user_edited` wrote")
    streak: StudioStreak


# ---------------------------------------------------------------- the hold's signature (CC-0070)
class HoldSignPlanIn(BaseModel):
    note: str = Field(description="why the video may be published - required (the factory: "
                                  "`empty_note`); stored as given, `via: center` beside it")


class HoldSignature(BaseModel):
    user: str = Field(description="who signs - `user`, as every write of the center")
    note: str
    via: Literal["center"]


class HoldSignPlan(PublishPlanBase):
    hold_id: str = Field(description="channel/batch_id/topic_id")
    batch_id: Optional[str] = None
    topic_id: Optional[str] = None
    script_id: Optional[str] = None
    verdict: Optional[str] = Field(None, description="compliance-checker's verdict (review)")
    flagged: List[str] = Field(description="what compliance-checker recorded on the row, in "
                                           "words: the verdict, the content-sensitivity check "
                                           "(flagged, notes), the rights-holder check (for "
                                           "information only), the hold's reason")
    content_sensitivity_check: Optional[Dict[str, Any]] = Field(None, description="as the row "
                                                                                  "has it")
    sensitivity_scenes: SensitivityScenes = Field(None, description=_SCENES)
    rights_holder_check: Optional[Dict[str, Any]] = Field(None, description="as the row has it")
    meaning: str = Field(description="what a signature means - shown before the confirm")
    note: str
    signature: HoldSignature = Field(description="what is written (the date at the confirm)")
    ledger: str = Field(description="the ledger's path under the root")
    ledger_fingerprint: str = Field(description="`check_sign`'s sha256 of the ledger file")
    hold: HoldRow = Field(description="the row as `check_sign` read it")


class HoldSignResult(BaseModel):
    action: Literal["hold_sign"]
    channel: str
    hold_id: str
    row: HoldRow = Field(description="the signed row (`signature {user, date, note, via}`)")
    fingerprint: str = Field(description="sha256 of the ledger as written")
    holds: PublicationHolds = Field(description="the channel's holds as they are now")


# ---------------------------------------------------------------- the statistics (CC-0020)
class AnalyticsProblem(BaseModel):
    """A refusal of the statistics routes - `{message, code, details}` as
    `BatchProblem`; the message is the factory's line (an agent's English line
    as it is)."""
    message: str = Field(description="the factory's line - shown as is")
    code: Literal["unknown_channel", "unknown_video", "bad_day", "store_unreadable",
                  "journal_unreadable", "acceptance_unreadable", "no_saved_summary",
                  "footage_unreadable"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_APROBLEMS = {s: {"model": AnalyticsProblem} for s in (404, 409, 422, 500)}

Num = Optional[Union[int, float]]


class AnalyticsChannel(BaseModel):
    channel: str
    last_run: Optional[Dict[str, Any]] = Field(
        description="the last line of analytics/<ch>/runs.jsonl (metrics.py collect): "
                    "collected_at, end_day, queried, skipped, unavailable_metrics, outcome "
                    "ok | nothing-to-ask | reauthorize | api-error | api-disabled | "
                    "all-forbidden; null - never collected")
    summary_days: List[str] = Field(description="days a summary was written for "
                                                "(analytics/<ch>/summary/<day>.json), newest first")


class AnalyticsOverview(BaseModel):
    channels: List[AnalyticsChannel] = Field(description="the upload journal's channels "
                                                         "(summary.channels_of)")
    window_days: List[int] = Field(description="metrics_store.WINDOW_DAYS - the windows "
                                               "the factory asks YouTube for")


class MetricDaily(BaseModel):
    """A row of `daily.jsonl` - YouTube Analytics' numbers of one Pacific day."""
    model_config = ConfigDict(extra="allow")
    channel: str
    video_id: str
    entry_id: Optional[str] = None
    day: str
    age: Optional[int] = Field(None, description="days since the publication")
    views: Num = None
    engagedViews: Num = None
    averageViewPercentage: Num = None
    averageViewDuration: Num = None
    likes: Num = None
    subscribersGained: Num = None
    final: bool = Field(description="3+ days before the collection day - never asked again")
    collected_at: str


class MetricWindow(BaseModel):
    """A row of `windows.jsonl` - YouTube's own totals of the first N days
    (CF-0624); from `metrics_store.window` also `from`, `to` (= start, end) and
    `days`."""
    model_config = ConfigDict(extra="allow")
    channel: str
    video_id: str
    entry_id: Optional[str] = None
    window: str = Field(description="first<N>d")
    first_days: int
    start: str
    end: str
    complete: Optional[bool] = Field(None, description="the window has all its N days")
    views: Num = None
    engagedViews: Num = None
    averageViewPercentage: Num = None
    averageViewDuration: Num = None
    likes: Num = None
    subscribersGained: Num = None
    final: bool
    collected_at: str
    source: Optional[str] = None
    days: Optional[int] = Field(None, description="its length (metrics_store.window)")


class StudioReadRow(BaseModel):
    """A row of `studio.jsonl` - what Studio was read to say (CF-0588)."""
    model_config = ConfigDict(extra="allow")
    channel: str
    video_id: str
    entry_id: Optional[str] = None
    read_at: str
    hook: str = Field(description="upload | batch-start | daily | manual")
    period_text: Optional[str] = Field(None, description="the period Studio named")
    viewed_pct: Num = None
    swiped_pct: Num = None
    raw_lines: List[str] = []
    warnings: List[str] = []
    note: Optional[str] = Field(None, description="Studio had no data yet (CF-0639)")
    recorded_at: Optional[str] = None


class VideoMetrics(BaseModel):
    video_id: str
    window: Optional[MetricWindow] = Field(description="YouTube's window of the first N "
                                                       "days; null - none stored (never "
                                                       "recombined from the daily rows)")
    daily_rows: int
    last_daily: Optional[MetricDaily]
    studio: Optional[StudioReadRow] = Field(description="the last Studio read")


class ChannelMetrics(BaseModel):
    channel: str
    first_days: int
    collected: bool = Field(description="first_days is in window_days - else no window "
                                        "exists for it")
    window_days: List[int]
    last_run: Optional[Dict[str, Any]]
    videos: List[VideoMetrics]


class VideoSeries(BaseModel):
    channel: str
    video_id: str
    daily: List[MetricDaily]
    windows: List[MetricWindow]
    studio: List[StudioReadRow]


class SummaryVideo(BaseModel):
    """`summary.video_line`: a video beside its style."""
    model_config = ConfigDict(extra="allow")
    video_id: Optional[str] = None
    entry_id: Optional[str] = None
    slug: Optional[str] = None
    published: Optional[str] = Field(None, description="the first Pacific day")
    age_days: Optional[int] = None
    removed: bool
    is_published: bool
    style: Dict[str, str] = Field(description="pattern, rhythm, hook_opener, fact_kind, "
                                              "tier - `unknown` where the profile has none")
    profile_found: bool
    profile_gap: Optional[str] = None
    window: Optional[Dict[str, Any]] = Field(None, description="days, from, to, final, "
                                                               "complete, source, views, "
                                                               "engagedViews, "
                                                               "averageViewPercentage, "
                                                               "averageViewDuration")
    api_gap: Optional[str] = Field(None, description="why a published video has no window")
    studio: Optional[Dict[str, Any]] = Field(None, description="viewed_pct, swiped_pct, "
                                                               "period_text, read_at, note")
    marks: List[str] = Field(description="the summary's marks, in Russian")


class SummaryGroup(BaseModel):
    """`summary.aggregates`: one value of a dimension - the factory's own
    statistics (`computed_by: factory`)."""
    model_config = ConfigDict(extra="allow")
    value: str
    videos: int
    computed_by: str
    not_final: int
    incomplete: int
    metrics: Dict[str, Dict[str, Any]] = Field(description="{metric: {n, median, mean, min, "
                                                           "max, stdev}}")
    small_sample: bool = Field(description="a metric under min_sample videos")


class AnalystSummary(BaseModel):
    """`summary.build` - what `summary.py daily` writes as <day>.json."""
    model_config = ConfigDict(extra="allow")
    task: str
    channel: str
    day: str
    first_days: int
    min_sample: int
    dimensions: List[str]
    metrics: List[str]
    sources: Dict[str, str]
    counts: Dict[str, int] = Field(description="videos, published, with_profile, with_api, "
                                               "with_studio, not_final")
    videos: List[SummaryVideo]
    aggregates: Dict[str, List[SummaryGroup]] = Field(description="{dimension: [group]}")
    gaps: Dict[str, List[Dict[str, Any]]] = Field(description="no_profile, no_metrics, "
                                                              "no_studio")
    aggregates_computed_by: str
    aggregates_note: str
    saved_days: List[str] = Field(description="days written under analytics/<ch>/summary/, "
                                              "newest first")
    saved: bool = Field(description="this day's summary is written")


class FootageRow(BaseModel):
    """`footage_wanted.fold` + `in_pool_now`, `where`: one thing to get."""
    model_config = ConfigDict(extra="allow")
    kind: str = Field(description="work | person | event | scene")
    name: str
    key: str
    topics: int
    batches: int
    misses: int
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    reasons: Dict[str, int]
    stages: Dict[str, int]
    examples: List[str]
    searched: List[str]
    supplement_outcomes: Dict[str, int]
    of_topics: List[str]
    topic_ids: List[str]
    batch_ids: List[str]
    packed_batches: List[str]
    in_pool_now: Optional[List[Dict[str, Any]]] = Field(None, description="pool entries "
                                                                          "naming it; null - "
                                                                          "the pool unreadable")
    where: Dict[str, Any] = Field(description="official_channels, candidates - only what the "
                                              "factory knows")


class FootageWanted(BaseModel):
    """`footage_wanted.build` - what `footage_wanted.py collect` writes."""
    model_config = ConfigDict(extra="allow")
    task: str
    channel: str
    built_at: str
    since: Optional[str] = None
    batches: Dict[str, Any] = Field(description="read, packed, first, last")
    notes: List[str]
    needs: int
    by_reason: Dict[str, int]
    rows: List[FootageRow]
    packed_read: bool = Field(description="the packed batches (Archive) were asked for")
    reasons_ru: Dict[str, Optional[str]] = Field({}, description="CC-0113: every code of "
                                                  "`by_reason` and the rows' `reasons` in "
                                                  "Russian - funnel.reason_ru (CF-0714), else "
                                                  "footage_wanted.REASONS; null - neither knows it")


class StudioVideo(BaseModel):
    video_id: str
    slug: Optional[str] = None
    entry_id: Optional[str] = None
    published: str
    studio_url: str = Field(description="its Studio analytics page (studio_read.STUDIO_VIDEO_URL)")


class StudioDue(BaseModel):
    due: bool
    line: str = Field(description="studio_read.due's line, in Russian")


class DiversityValue(BaseModel):
    value: Any = Field(description="the axis's value as the profile has it; `unknown` - no "
                                   "profile says it")
    count: int
    share: float = Field(description="count / n, rounded to 3 places")


class DiversityAxis(BaseModel):
    key: Literal["fact_kind", "pattern", "rhythm", "hook_opener"]
    label: str = Field(description="the CLI's Russian name of the axis")
    values: List[DiversityValue] = Field(description="most frequent first")


class FeedDiversity(BaseModel):
    """CC-0108: `runlog diversity --last N --json` - publish_profile.diversity
    over the acceptance log: the feed of the videos the user accepted (the
    factory's whole feed, every channel and rebuild - or one channel's,
    `?channel`, CC-0119), its last N."""
    last: int = Field(description="N as asked; 0 - the whole feed")
    channel: Optional[str] = Field(
        None, description="CC-0119 (CF-0719): the channel asked, as today's id - its rows "
                          "only, before the last N are taken; null - every channel")
    n: int = Field(description="videos counted")
    videos: List[str] = Field(description="their slugs, in the order accepted")
    read_live: List[str] = Field(
        description="no profile written yet - read from the batch now (nothing written)")
    axes: List[DiversityAxis]
    lines: List[str] = Field(description="what the CLI prints, verbatim (render_diversity)")
    log: str = Field(description="the acceptance log, relative to the root")
    log_exists: bool
    log_read: bool = Field(description="false - missing or not a JSON object: an empty feed")
    log_error: Optional[str] = Field(
        None, description="CF-0719: the log is there but broken (not JSON, not an object) - "
                          "the file and why; null when it read or is missing")


# ---------------------------------------------------------------- the gates' price (CC-0100)
class GatePriceProblem(BaseModel):
    """A refusal of `GET /gate-prices` - `{message, code, details}` as
    `BatchProblem`."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["unknown_rule", "bad_before", "factory_broken"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_GPROBLEMS = {s: {"model": GatePriceProblem} for s in (404, 422, 500)}


class GatePriceKilled(BaseModel):
    model_config = ConfigDict(extra="allow")
    item: str = Field(description="the script id of the ready video")
    slug: Optional[str] = None
    key: Optional[str] = Field(None, description="what the rule refused: the script, or its topic")
    reason: Optional[str] = Field(None, description="the rule's words")


class GatePriceBatch(BaseModel):
    """`gate_price.price_of_batch` - one batch of the window."""
    model_config = ConfigDict(extra="allow")
    batch: Optional[str] = Field(description="<channel>/<batch id>")
    basis: Optional[str] = Field(description="why this batch can price the rule")
    no_basis: Optional[str] = Field(description="why it cannot - not a price of zero")
    ready: List[str] = Field(description="the ready videos' script ids (the funnel's ready)")
    refused: List[str] = Field(description="every item the rule would have dropped")
    killed: List[GatePriceKilled] = Field(description="the ready videos among them")
    price: Optional[int] = Field(description="len(killed); null - no basis")


GATE_SIGN_REFUSALS = tuple(gate_prices.REFUSALS)


class GateRefusalWhy(BaseModel):
    code: Literal[GATE_SIGN_REFUSALS] = Field(description="the factory's refusal code "
                                                          "(gate_price.SIGN_REFUSALS)")
    message: str = Field(description="the center's Russian line for it")


class GateActions(BaseModel):
    """CC-0114: what the buttons may do with the rule now, as far as the
    ledger row says (gate_price.sign / decide's own row checks - not the
    batches: an open one is the plan's `batch_open`)."""
    in_ledger: bool = Field(description="the rule is a row of shared/gate-prices.json")
    measured_price: Optional[Union[int, float]] = Field(description="the ledger's measured price - a "
                                                        "signature must be at least it; null - "
                                                        "not measured")
    signable: bool = Field(description="not a score-model row (hard / penalty)")
    sign: bool = Field(description="a signature would be taken (at a price >= measured_price)")
    sign_refusal: Optional[GateRefusalWhy] = Field(description="why not, when sign is false")
    decide: bool = Field(description="a decision (measure / warn) would be taken")
    decide_refusal: Optional[GateRefusalWhy] = Field(description="why not, when decide is false")


class GatePriceResult(BaseModel):
    """`gate_price.price(rule)` as `runlog gate-price --json` prints it, with
    its headline and the code's mode."""
    model_config = ConfigDict(extra="allow")
    rule: str
    what: Literal["video", "topic"] = Field(description="what the rule refuses")
    note: Optional[str] = Field(None, description="the rule's own words (its task, its defect)")
    before: Optional[str] = None
    window: List[Optional[str]] = Field(description="the batches priced over, oldest first")
    batches: List[GatePriceBatch]
    ready: int = Field(description="ready videos across the batches that could price it")
    price: Optional[int] = Field(description="ready videos it would have killed; null - no "
                                             "batch could price it (not a price of zero)")
    measured_on: int
    of: int
    verdict: Literal["enforce", "warn", "penalty"]
    why: str = Field(description="the factory's line - shown as is")
    signature: Optional[Dict[str, Any]] = Field(description="the user's signature under the "
                                                            "price ({user, date, price, note}), "
                                                            "a hand-written block")
    decision: Optional[Dict[str, Any]] = Field(description="the user's recorded decision on "
                                                           "the mode ({user, date, mode, task, "
                                                           "note}), hand-written")
    headline: str = Field(description="the CLI's GATE PRICE line (gate_price.headline)")
    mode: Optional[Literal["measure", "warn"]] = Field(
        description="what the rule's code does when nothing else says (Rule.mode, CF-0472); "
                    "null - the code refuses")
    actions: GateActions = Field(description="CC-0114: what signing / deciding may do now")


class GatePriceUnregistered(BaseModel):
    """A ledger row with a user's decision and no replay (render_unregistered)."""
    rule: str
    note: Optional[str] = None
    measured: Optional[Dict[str, Any]] = Field(None, description="measured by hand")
    signature: Optional[Dict[str, Any]] = None
    decision: Dict[str, Any]
    actions: GateActions = Field(description="CC-0114: what signing / deciding may do now")


class GatePriceProposal(BaseModel):
    rule: str
    line: str = Field(description="gate_price.proposal_line - what the user would sign")
    mode_until_signed: str


class GateSigning(BaseModel):
    """Signing a price / deciding a mode from the center (CC-0114 over the
    factory's gate_price.sign / decide, CF-0721; CC-0100 had it unavailable)."""
    available: bool = Field(description="true - the routes /gate-prices/{rule}/sign and "
                                        "/decide (plan, confirm) write through the factory")
    what: str = Field(description="what can be done from the center, in Russian")
    how_today: str = Field(description="how a signature is made today, in Russian")
    factory_function: str = Field(description="the factory's writers")
    task: str = Field(description="the factory's task (CF-0721)")


class GatePriceProblemW(BaseModel):
    """A refusal of a signature's / decision's write - `{message, code,
    details}`: the code the factory's (gate_price.SIGN_REFUSALS) or the
    token's, the message Russian, the details the factory's lines."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal[GATE_SIGN_REFUSALS + ("busy", "confirm_unknown", "confirm_expired",
                                        "confirm_mismatch", "factory_broken")]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_GWPROBLEMS = {s: {"model": GatePriceProblemW} for s in (404, 409, 422, 500)}


class GateSignPlanIn(BaseModel):
    price: int = Field(description="the price signed: ready videos, at least the measured one")
    note: str = Field(description="the user's note - required")
    base_sha256: Optional[str] = Field(None, description="the GET's `ledger_sha256` the user "
                                                         "looked at; none - the ledger now")


class GateDecidePlanIn(BaseModel):
    mode: str = Field(description="measure or warn (gate_price.CODE_MODES)")
    task: str = Field(description="the task id the decision belongs to, like CF-0330")
    note: str = Field(description="the user's note - required")
    base_sha256: Optional[str] = Field(None, description="the GET's `ledger_sha256`; none - "
                                                         "the ledger now")


class GateWriteRefusal(BaseModel):
    code: str = Field(description="the factory's code (gate_price.SIGN_REFUSALS)")
    line: str = Field(description="the factory's line")
    message: str = Field(description="the center's Russian message for the code")


class GateWriteAnswer(BaseModel):
    """gate_price.sign / decide's answer (CF-0721, the CF-0726 shape)."""
    action: Literal["gate_price_sign", "gate_price_decide"]
    kind: Literal["sign", "decide"]
    rule: str
    key: Optional[Literal["signature", "decision"]] = Field(None, description="the ledger "
                                                                              "block written")
    task: Optional[str] = Field(None, description="the factory's task, CF-0721")
    ok: bool
    path: Optional[str] = Field(None, description="shared/gate-prices.json")
    base_sha256: Optional[str] = None
    sha256: Optional[str] = Field(None, description="the ledger now")
    new_sha256: Optional[str] = Field(None, description="what would be / was written")
    block: Optional[Dict[str, Any]] = Field(None, description="the block: signature {user, "
                                                              "date, price, note, via} or "
                                                              "decision {user, date, mode, "
                                                              "task, note, via}")
    refusals: List[GateWriteRefusal]
    lines: List[str] = Field(description="the factory's lines")
    by: Optional[str] = None
    via: Optional[str] = None


class GateWritePlan(GateWriteAnswer):
    """The factory's dry run (by user via center) - nothing written - and a
    confirm token when it would write."""
    dry_run: Literal[True]
    why: Optional[str] = Field(None, description="in Russian, why no token")
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class GateWriteResult(GateWriteAnswer):
    dry_run: Literal[False]
    written: bool
    commit: Optional[str] = Field(None, description="the factory's commit of the ledger alone")


class GatePrices(BaseModel):
    """CC-0100: `runlog gate-price [--rule]... [--window] [--before] --json` -
    what each refusal would have cost in ready videos over the window, read
    only (nothing written: no --write)."""
    rules: List[str] = Field(description="every registered rule (gate_price.RULES)")
    asked: List[str] = Field(description="the rules priced here")
    window: int
    before: Optional[str] = None
    window_default: int = Field(description="gate_price.WINDOW")
    pool: str = Field(description="the batches' directory, relative to the root")
    ledger: str = Field(description="shared/gate-prices.json, relative to the root")
    ledger_exists: bool
    ledger_sha256: Optional[str] = Field(None, description="CC-0114: the ledger's sha256 "
                                                           "(gate_price.ledger_sha256) - a "
                                                           "plan's base_sha256; null: no file")
    results: List[GatePriceResult]
    all_land: bool = Field(description="every verdict enforce or penalty - the CLI's exit 0")
    unregistered: List[GatePriceUnregistered] = Field(
        description="ledger rows with a decision and no replay over the window")
    proposals: List[GatePriceProposal] = Field(description="prices awaiting the user's "
                                                           "signature, not in force")
    signing: GateSigning
    computed_at: str
    cached: bool = Field(description="true - the window and the ledger unchanged since the "
                                     "last read: that answer")


class AnalyticsStudio(BaseModel):
    channel: str
    no_pipeline: Optional[str] = Field(description="the channel is a stub (CF-0562)")
    settings: Optional[Dict[str, Any]] = Field(description="analyst.studio_read: last_videos, "
                                                           "insurance_hours, hook_min_gap_hours")
    settings_error: Optional[str] = Field(description="the factory's refusal of them")
    last_videos: List[StudioVideo] = Field(description="the last N published videos, newest "
                                                       "first (studio_read.last_videos)")
    n: Optional[int]
    due: Optional[StudioDue] = Field(description="the daily insurance (studio_read.due)")
    last_visit: Optional[Dict[str, Any]] = Field(description="studio_visits.jsonl's latest")
    latest_reads: List[StudioReadRow] = Field(description="the latest read of every video read")


# ---------------------------------------------------------------- a channel's lists (CC-0022)
class RightsProblem(BaseModel):
    """A refusal of the channel-list read routes - `{message, code, details}` as
    `BatchProblem`; the message is the factory's line as it is."""
    message: str = Field(description="the factory's line - shown as is")
    code: Literal["unknown_channel", "rights_holders_unreadable",
                  "footage_origin_unreadable", "factory_broken",
                  # CC-0102: the fact sources and the affiliate table
                  "fact_sources_unreadable", "affiliate_unreadable"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_RPROBLEMS = {s: {"model": RightsProblem} for s in (404, 409, 422, 500)}


class ChannelRightsHolders(BaseModel):
    channel: str
    path: str = Field(description="channels/<ch>/rights-holder-blacklist.json")
    doc: Optional[Dict[str, Any]] = Field(description="the list as written: entries[] "
                                                      "(rights_holder, risk_level, evidence, "
                                                      "...)")
    missing: Optional[str] = Field(description="the factory's line when there is no file")
    sha256: Optional[str] = Field(None, description="CC-0114: the file's sha256 "
                                                    "(channel_list_write.list_sha256); "
                                                    "null: no file")


class ChannelFootageOrigin(BaseModel):
    channel: str
    path: str = Field(description="channels/<ch>/footage-origin.json")
    doc: Optional[Dict[str, Any]] = Field(description="licences {accepted, refused}, "
                                                      "attribution, footage_origins[], "
                                                      "official_channels[], ...")
    missing: Optional[str] = Field(description="the factory's line when there is no file")
    sha256: Optional[str] = Field(None, description="CC-0114: the file's sha256 "
                                                    "(channel_list_write.list_sha256) - the "
                                                    "write's base_sha256; null: no file")
    errors: List[str] = Field(description="footage_licence.footage_origin_errors")


class ChannelFactSources(BaseModel):
    """CC-0102: `channel_data.fact_sources` and the factory's checks of it."""
    channel: str
    path: str = Field(description="channels/<ch>/fact-sources.json")
    doc: Optional[Dict[str, Any]] = Field(description="the list as written: tiers {1, 2}, "
                                                      "any_host, do_not_take, kinds, ...")
    missing: Optional[str] = Field(description="the factory's line when there is no file")
    kinds: Optional[List[str]] = Field(None, description="channel_data.fact_kinds; null when "
                                                         "the list has none (errors say why)")
    sha256: Optional[str] = Field(None, description="CC-0114: the file's sha256 "
                                                    "(channel_list_write.list_sha256) - the "
                                                    "write's base_sha256; null: no file")
    errors: List[str] = Field(description="fact_rule.validate_sources, channel_data."
                                          "source_policy_errors (the outlets and the config's "
                                          "feeds), attribution_terms_errors - the factory's "
                                          "lines")


class ChannelAffiliate(BaseModel):
    """CC-0102: the channel's affiliate slot (`shared/affiliate.py`)."""
    channel: str
    path: str = Field(description="channels/<ch>/affiliate.json")
    enabled: bool = Field(description="affiliate.enabled - the config's switch (absent = off)")
    block: Optional[Dict[str, Any]] = Field(None, description="the config's `affiliate` block "
                                                              "{enabled, link_line, "
                                                              "disclosure}")
    doc: Optional[Dict[str, Any]] = Field(description="the table as written: programmes[], "
                                                      "products[]")
    missing: Optional[str] = Field(description="the factory's line when there is no table")
    sha256: Optional[str] = Field(None, description="CC-0114: the file's sha256 "
                                                    "(channel_list_write.list_sha256) - the "
                                                    "write's base_sha256; null: no file")
    errors: List[str] = Field(description="affiliate.channel_errors - the block and the table")


# ---------------------------------------------------------------- the channel lists' writes (CC-0114)
CHANNEL_LIST_REFUSALS = ("bad_who", "unknown_channel", "unknown_list", "invalid", "batch_open",
                         "check_changed", "locked", "not_repo", "commit_refused", "write_failed")
CHANNEL_LIST_NAMES = ("fact-sources", "footage-origin", "affiliate")
CHANNEL_LIST_ACTIONS = ("fact_sources_write", "footage_origin_write", "affiliate_write")


class ChannelListProblem(BaseModel):
    """A refusal of a channel list's write - `{message, code, details}`: the
    code the factory's (CF-0726 `write_list`) or the token's, the message
    Russian, the details the factory's lines."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal[CHANNEL_LIST_REFUSALS + ("busy", "confirm_unknown", "confirm_expired",
                                           "confirm_mismatch", "factory_broken")]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_CLPROBLEMS = {s: {"model": ChannelListProblem} for s in (404, 409, 422, 500)}


class ChannelListDocIn(BaseModel):
    doc: Dict[str, Any] = Field(description="the whole new document of the list")
    base_sha256: Optional[str] = Field(description="the `sha256` of the GET it was made from "
                                                   "(null: there was no file); another one is "
                                                   "check_changed")


class ChannelListRefusal(BaseModel):
    code: Literal[CHANNEL_LIST_REFUSALS]
    line: str = Field(description="the factory's line")
    message: str = Field(description="the center's Russian message for the code")


class ChannelListAnswer(BaseModel):
    """The factory's checked write's answer (CF-0726 `write_list`)."""
    action: Literal[CHANNEL_LIST_ACTIONS]
    channel: str
    list: Literal[CHANNEL_LIST_NAMES]
    ok: bool
    path: Optional[str] = Field(None, description="channels/<ch>/<list>.json")
    base_sha256: Optional[str] = None
    sha256: Optional[str] = Field(None, description="the file now")
    new_sha256: Optional[str] = Field(None, description="what would be / was written")
    refusals: List[ChannelListRefusal]
    lines: List[str] = Field(description="the writer's lines")
    by: Optional[str] = None
    via: Optional[str] = None


class ChannelListPlan(ChannelListAnswer):
    """The writer's dry run (by user via center) - nothing written - and a
    confirm token when it would write."""
    dry_run: Literal[True]
    changes: bool = Field(description="the document is not the file already")
    why: Optional[str] = Field(None, description="in Russian, why no token")
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class ChannelListWriteResult(ChannelListAnswer):
    dry_run: Literal[False]
    written: bool
    commit: Optional[str] = Field(None, description="the commit of exactly this file")


# ---------------------------------------------------------------- the channel's ending (CC-0101)
class EndingProblem(BaseModel):
    """A refusal of the ending routes - `{message, code, details}`; a refused
    render's code is the refusal's (`EndingRefusal.code`), its message the
    Russian line of it."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["unknown_channel", "factory_broken", "busy", "confirm_unknown",
                  "confirm_mismatch", "confirm_expired", "check_changed", "start_failed",
                  "ending_by_hand", "ending_no_generator", "ending_file_missing",
                  "ending_sha256_mismatch", "ending_invalid", "ending_args_missing",
                  "batch_open", "render_running", "plan_broken"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_ENPROBLEMS = {s: {"model": EndingProblem} for s in (404, 500)}
_ENWPROBLEMS = {s: {"model": EndingProblem} for s in (404, 409, 422, 500)}
class EndingProbe(BaseModel):
    """`end_card.probe_ending` - what ffprobe says of the clip."""
    seconds: float
    width: int
    height: int
    fps: float
    has_audio: bool


class EndingFormat(BaseModel):
    width: int
    height: int
    fps: float


class EndingCheck(BaseModel):
    """`end_card.check_ending` - the Video Editor's own check of the clip."""
    ok: bool
    error: Optional[str] = Field(description="the factory's line when it fails")
    against: EndingFormat = Field(description="the format brand_ending.py renders (W x H at "
                                              "FPS - the composition's)")


class EndingGenerator(BaseModel):
    script: Literal["scripts/brand_ending.py"]
    renders_channel: bool = Field(description="the channel is one of its BRANDS")
    motif: Optional[str] = Field(description="its frame for the channel (stars, circuit)")
    channels: List[str] = Field(description="every channel it can draw")
    frames: Optional[int]
    fps: Optional[int]
    error: Optional[str] = Field(description="why the script did not load")


class EndingNeed(BaseModel):
    """One argument of a render and where the channel's data keeps it."""
    arg: str = Field(description="brand_ending.py's flag")
    key: str = Field(description="its key in channels/<c>/brand.json (ending.render.<field>)")
    required: bool
    stored: bool = Field(description="the channel's data records it")
    value: Optional[Union[str, float]] = Field(description="as recorded (a path from the root)")
    present: Optional[bool] = Field(description="the file is in the tree (the fonts: both "
                                                "Poppins files); null for a number or nothing "
                                                "recorded")
    what: str


class EndingRefusal(BaseModel):
    """Why a render is not offered: the code in its own field, the message in
    Russian without it, the factory's line in `details`."""
    code: Literal["ending_by_hand", "ending_no_generator", "ending_file_missing",
                  "ending_sha256_mismatch", "ending_invalid", "ending_args_missing",
                  "batch_open", "render_running", "plan_broken"]
    message: str = Field(description="for a human, in Russian - shown as is")
    details: List[str] = Field(description="«<code>: <the factory's line>» and the section's "
                                           "check lines")


class EndingRunPlan(BaseModel):
    """`brand_ending.render_plan` - what a render would run (`--plan`)."""
    fonts: str = Field(description="the fonts directory, from the root")
    audio: str = Field(description="the track, from the root")
    audio_start: float
    audio_gain_db: float
    out: str = Field(description="the clip it writes, from the root")
    command: List[str] = Field(description="the ffmpeg command (paths cut)")
    sources: Dict[str, str] = Field(description="fonts|audio|audio_start|audio_gain_db|out -> "
                                                "flag | data | default")
    clip_sha256: Optional[str] = Field(description="the clip's sha256 the data records")


class EndingLastRun(BaseModel):
    """The last render of the channel this API process started."""
    pid: int
    log: str = Field(description="its log, from the root (schedule/logs/<day>-<c>-ending.log)")
    started_at: str = Field(description="UTC ISO")
    running: bool = Field(description="taken as running: within brand_ending's deadline "
                                      "(600 s) and its log names no end yet")
    commit_refused: Optional[str] = Field(None, description="CC-0161: the last `cc-commit:` "
                                                            "line of its log said `refused` - "
                                                            "git's word (paths cut); the clip "
                                                            "stays in the tree, nothing staged; "
                                                            "null otherwise")


class EndingRender(BaseModel):
    available: bool = Field(description="the factory's plan is ok - a render can be planned "
                                        "(the plan route checks the open batches too)")
    why: Optional[str] = Field(description="the refusal's Russian line; null when available")
    refusal: Optional[EndingRefusal]
    by_hand: bool = Field(description="ending.render is null: the clip was made by hand "
                                      "(ExampleFilm), nothing to render")
    plan: Optional[EndingRunPlan] = Field(description="when available")
    needs: List[EndingNeed] = Field(description="the arguments of a render (brand_ending.main)")
    sources_docs: List[str] = Field(description="the channel's SOURCES.md that tell, in prose, "
                                                "the command that made the file")
    factory_ask: Optional[str] = Field(description="what the factory should do so that the "
                                                   "refusal goes away; null: nothing")
    last_run: Optional[EndingLastRun]


class EndingDataError(BaseModel):
    code: str = Field(description="channel_data.EndingError.code (ending_invalid ...)")
    line: str = Field(description="the factory's line")


class EndingData(BaseModel):
    """`channels/<c>/brand.json` -> `ending` (channel_data.ending, CF-0722)."""
    path: str = Field(description="channels/<c>/brand.json")
    exists: bool
    section: bool = Field(description="the file has a valid `ending` section")
    clip: Optional[str] = Field(description="ending.clip, from the root")
    clip_sha256: Optional[str]
    clip_matches: Optional[bool] = Field(description="the clip's bytes are clip_sha256; null: "
                                                     "no clip or no sha recorded")
    render: Optional[Dict[str, Any]] = Field(description="ending.render as recorded (null: "
                                                         "made by hand, or no section)")
    note: Optional[str]
    errors: List[str] = Field(description="channel_data.ending_errors of the section")
    error: Optional[EndingDataError]


class ChannelEnding(BaseModel):
    """The channel's ending clip as the factory sees it (end_card.ending_path,
    ending_seconds, probe_ending, check_ending), its data (brand.json) and its
    render (brand_ending.render_plan)."""
    channel: str
    cached: bool = Field(description="kept per state of the config, the clip and the scripts")
    path: str = Field(description="where the clip is (or would be by the convention), from "
                                  "the root")
    source: Optional[Literal["config", "convention"]] = Field(
        description="video_editor.ending.path, or channels/<c>/ending.mp4; null: no clip")
    path_error: Optional[str] = Field(description="the config names a file that is not there")
    exists: bool
    bytes: Optional[int]
    mtime: Optional[str] = Field(description="UTC ISO")
    sha256: Optional[str]
    declared_seconds: Optional[float] = Field(description="narration_budget.ending_seconds")
    probe: Optional[EndingProbe]
    probe_error: Optional[str]
    check: Optional[EndingCheck]
    media_url: None = Field(description="no route of the center serves a channel's own files")
    generator: EndingGenerator
    data: EndingData
    render: EndingRender




class EndingRenderPlan(BaseModel):
    """What «отрендерить концовку» would do: the factory's plan read afresh,
    the open batches of the channel, a confirm token when nothing refuses."""
    action: Literal["ending_render"]
    channel: str
    ok: bool
    why: Optional[str] = Field(description="the refusal's Russian line")
    refusal: Optional[EndingRefusal]
    by_hand: bool
    plan: Optional[EndingRunPlan]
    argv: Optional[List[str]] = Field(description="what would start: brand_ending.py with the "
                                                  "plan's values as flags (paths cut)")
    needs: List[EndingNeed]
    batches: List[str] = Field(description="the open batches that block it")
    log_dir: Literal["schedule/logs"]
    fingerprint: str
    confirm: Optional[str] = Field(description="the token for POST /channels/{c}/ending - only "
                                               "when ok; single use")
    expires_in_s: Optional[int]


class EndingRenderResult(BaseModel):
    """The render started detached - answered at once, never waited on."""
    ok: Literal[True]
    channel: str
    pid: int
    log: str = Field(description="its log, from the root (schedule/logs/<day>-<c>-ending.log)")
    started_at: str = Field(description="UTC ISO")
    argv: List[str] = Field(description="what was started (paths cut)")
    out: str = Field(description="the clip it writes, from the root")


# ---------------------------------------------------------------- entering a Studio read (CC-0074)
class StudioWriteProblem(BaseModel):
    """A refusal of entering a Studio read - `{message, code, details}`; a
    `read_refused` message is `studio_read.ReadError`'s line as it is."""
    message: str = Field(description="shown as is")
    code: Literal["unknown_channel", "read_refused", "journal_unreadable", "store_unreadable",
                  "check_changed", "busy", "confirm_unknown", "confirm_mismatch",
                  "confirm_expired", "factory_broken"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_SWPROBLEMS = {s: {"model": StudioWriteProblem} for s in (404, 409, 422, 500)}


class StudioReadRecordPlanIn(BaseModel):
    read: Dict[str, Any] = Field(description="the read as copied from Studio - what "
                                             "`studio_read.py parse` takes: {channel, read_at "
                                             "(ISO with zone), hook: upload | batch-start | "
                                             "daily | manual, ui_language?, videos?: "
                                             "[{video_id | url, title?, period_text?, lines, "
                                             "viewed?, swiped?}]}")


class StudioParsedVideo(BaseModel):
    """`parse_read`'s row of a video - what will go into studio.jsonl."""
    model_config = ConfigDict(extra="allow")
    kind: str
    channel: str
    video_id: str
    entry_id: Optional[str] = Field(None, description="its journal entry; null: not in "
                                                      "publish/uploads.json (a warning)")
    read_at: str
    hook: str
    period_text: Optional[str] = None
    viewed_pct: Num = None
    swiped_pct: Num = None
    raw_lines: List[str] = []
    warnings: List[str] = Field([], description="what was not recognised - never guessed")
    note: Optional[str] = Field(None, description="Studio had no data yet (CF-0639)")
    title: Optional[str] = None
    stored: Optional[StudioReadRow] = Field(None, description="its last stored read "
                                                              "(metrics_store.latest_studio), "
                                                              "null when none")


class StudioUnstored(BaseModel):
    title: Optional[str] = None
    raw_lines: List[str] = []
    warnings: List[str] = []


class StudioReadRecordPlan(PublishPlanBase):
    read_at: str = Field(description="UTC")
    hook: str
    ui_language: Optional[str] = None
    videos: List[StudioParsedVideo]
    unstored: List[StudioUnstored] = Field(description="videos without an id - kept in the "
                                                       "visit line, not stored as a metric")
    warnings: List[str] = Field(description="the read's own warnings")
    recorded_by: Literal["user"]
    via: Literal["center"]


class StudioMergeCounts(BaseModel):
    added: int
    replaced: int
    unchanged: int


class StudioReadRecordResult(BaseModel):
    action: Literal["studio_read_record"]
    channel: str
    written: Literal[True]
    read_at: str
    hook: str
    recorded_by: Literal["user"]
    via: Literal["center"]
    studio: StudioMergeCounts = Field(description="`merge_studio`: the reads added, replaced, "
                                                  "left unchanged")
    visit_logged: bool = Field(description="false: a visit of this read_at was logged already")


# ---------------------------------------------------------------- the Studio read from the center (CC-0120)
class StudioCenterProblem(BaseModel):
    """A refusal of the Studio read routes - `{message, code, details}`: the
    message in Russian, the code in its own field, the factory's lines behind
    «подробнее»."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["bad_hook", "bad_channel", "bad_run", "unknown_run", "launch_off",
                  "launch_failed", "busy", "confirm_unknown", "confirm_mismatch",
                  "confirm_expired", "check_changed", "factory_broken", "bad_who",
                  "no_channels", "running", "no_claude", "spawn_failed"]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_SCPROBLEMS = {s: {"model": StudioCenterProblem} for s in (422, 500)}
_SCRPROBLEMS = {s: {"model": StudioCenterProblem} for s in (404, 422, 500)}
_SCWPROBLEMS = {s: {"model": StudioCenterProblem} for s in (409, 422, 500)}


class StudioLaunch(BaseModel):
    """May the center start a Studio read at all (`api/studio_center.py`
    STUDIO_READ_LAUNCH - on since the user's «да» of 17.10, v2.8.1)."""
    available: bool
    why: Optional[str] = Field(description="why not, in Russian; null when available")
    switch: Literal["STUDIO_READ_LAUNCH"]


class StudioReadDueChannel(BaseModel):
    channel: str
    due: bool
    why: str = Field(description="the channel's line, in Russian")
    last_read_at: Optional[str] = Field(description="UTC ISO of the last read; null: never")
    age_hours: Optional[float] = Field(description="hours since it; null: never")


class StudioReadDue(BaseModel):
    """`studio_center.studio_read_due` (CF-0735): is a Studio read due."""
    task: str
    channel: Optional[str] = Field(description="the channel asked for; null: the whole factory")
    hook: Optional[Literal["batch-start", "upload", "center-first-open-of-day"]] = Field(
        description="the occasion; null: the daily insurance alone")
    hooks: List[str]
    hook_words: Dict[str, str] = Field(description="each hook in Russian (`none`: no hook)")
    due: bool
    why: str = Field(description="the Russian line - show it beside the button")
    last_read_at: Optional[str] = Field(description="the oldest of the channels' last reads; "
                                                    "null when one was never read")
    age_hours: Optional[float] = Field(description="the greatest age; null when one was never "
                                                   "read")
    first_open_today: Optional[bool] = Field(description="center-first-open-of-day: this open "
                                                         "was the first of the Moscow day; "
                                                         "null for other hooks")
    running: Optional[str] = Field(description="the run id of a reading session still going")
    channels: List[StudioReadDueChannel]
    skipped: List[str] = Field(description="channels with nothing to read, a line each")
    launch: StudioLaunch


class StudioRefusal(BaseModel):
    code: Literal["bad_who", "no_channels", "running", "no_claude", "spawn_failed"]
    line: Optional[str] = Field(description="the factory's line")
    message: str = Field(description="the center's Russian line of the code")


class StudioReadPlan(BaseModel):
    """`studio_read_launch(by=user, via=center)` without confirm - what
    «Прочитать Studio» would start, nothing started; a token only when the
    factory says ok and the switch is on."""
    model_config = ConfigDict(extra="allow")
    action: Literal["studio_read_launch"]
    ok: bool
    why: Optional[str] = Field(description="the first refusal's Russian line, else the "
                                           "switch's why; null when it can start")
    launched: bool
    confirmed: bool
    task: str
    by: Optional[str]
    via: Optional[str]
    channels: List[str]
    argv: Optional[List[str]] = Field(description="what would start (claude -p --chrome ...)")
    run_id: None
    pid: None
    log: None
    refusals: List[StudioRefusal]
    lines: List[str] = Field(description="the factory's lines, Russian")
    launch: StudioLaunch
    fingerprint: str
    confirm: Optional[str] = Field(description="the token for POST /studio/read - only when "
                                               "ok and launch.available; single use")
    expires_in_s: Optional[int]


class StudioReadStarted(BaseModel):
    """The reading session started detached - answered at once."""
    ok: Literal[True]
    launched: bool
    run_id: Optional[str]
    pid: Optional[int]
    log: Optional[str] = Field(description="its log, from the root "
                                           "(schedule/studio-read/runs/<run_id>.log)")
    channels: List[str]
    argv: List[str]
    by: Optional[str]
    via: Optional[str]
    lines: List[str]
    poll_s: int = Field(description="ask GET /studio/read/{run_id} every so many seconds")


class StudioReadResult(BaseModel):
    """`studio_center.studio_read_result` - what the session came to."""
    run_id: Optional[str]
    log: Optional[str]
    code: Literal["read", "no_extension", "login_needed", "error", "running"]
    word: str = Field(description="OUTCOME_WORDS: прочитано / расширение не подключено / "
                                  "нужен вход / ошибка / читается")
    done: bool
    line: str = Field(description="the word and the detail, Russian")
    detail: str
    recorded: List[str] = Field(description="channels whose visit was recorded since the run "
                                            "started, via the run's via")
    poll_s: Optional[int] = Field(description="while running: ask again in so many seconds")


# ---------------------------------------------------------------- writes (CC-0058)
class WritesRefused(Exception):
    """A write route outside the working factory - before any call of the factory."""

    def __init__(self, reason, root):
        super().__init__(reason)
        self.reason, self.root = reason, root

    def body(self):
        return {"message": f"Только смотреть: {self.reason}", "code": WRITES_CODE,
                "details": [self.reason, f"factory root: {self.root}",
                            "writes only in the working factory - the main checkout on main "
                            "(agents_lock.is_working_factory, CF-0677); a development copy "
                            "writes with the developer's CC_API_WRITES=dev"]}


# ---------------------------------------------------------------- the meme desk (CC-0024)
MEME_CODES = ("unknown_channel", "unknown_id", "no_file", "no_cut", "outside_bank",
              # the desk's own (`MemeDeskError.code`, CF-0693) - the message its Russian text
              "no_channel", "bank_conflict", "bad_bank", "bad_index", "bad_draft", "bad_spec",
              "bad_decisions", "invalid_index", "thumb_failed",
              "check_changed", "busy", "confirm_unknown", "confirm_expired", "confirm_mismatch",
              "factory_broken",
              # CC-0103: the bank's candidates.json does not parse
              "bad_candidates",
              # CC-0114: the candidates' yes (plan_accept / accept_candidates, CF-0725)
              "no_candidates", "bad_ids", "bad_details", "bad_answer", "bad_who",
              "no_fingerprint", "list_changed", "bad_entry", "duplicate_id", "invalid_entry",
              # CC-0075: the background jobs (CF-0760/CF-0755) - the center's own job_active
              # and launch_failed, the desk's cutout_unavailable, not_cutout and start_job's /
              # job_status' / list_jobs' codes
              "job_active", "launch_failed", "cutout_unavailable", "not_cutout", "bad_kind",
              "bad_params", "job_running", "spawn_failed", "unknown_job", "bad_limit",
              # CC-0076: the adds, the sheet, the embed (CF-0760) - the center's own bad_url
              # (http(s) only) and the plans' / start_job's refusals
              "bad_url", "bad_suffix", "no_source_url", "file_exists", "bad_span",
              "too_many_frames", "video_failed", "download_failed", "bad_image", "blank_image",
              "over_ceiling", "media_failed", "embed_failed", "bad_progress")


class MemesProblem(BaseModel):
    """A refusal of the meme desk - `{message, code, details}`; a desk refusal
    carries its code and its Russian text (`MemeDeskError`, CF-0693): 404
    unknown_id / no_file / no_channel (and unknown_channel, no_cut,
    outside_bank), 422 bad_decisions (and unknown_id in the marks), 500
    thumb_failed / factory_broken, the rest 409 - the bank's state on disk."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal[MEME_CODES]
    details: List[str] = Field(description="technical lines (behind «подробнее»)")


_MPROBLEMS = {s: {"model": MemesProblem} for s in (404, 409, 422, 500)}


class MemeBankRow(BaseModel):
    channel: str
    bank: Optional[str] = Field(None, description="the bank's folder (`memes` = the default, "
                                                  "Reel's); null when it does not open")
    default_bank: Optional[bool] = None
    layer_enabled: Optional[bool] = Field(None, description="`insert_layers.meme.enabled` of "
                                                            "the channel's config (the factory "
                                                            "switches it); null: not set")
    entries: int
    pending: int = Field(description="entries `review: pending`")
    keep: int = Field(description="marks keep in the draft")
    drop: int = Field(description="marks drop in the draft")
    cut_diff: int = Field(description="marks whose cut differs from the index")
    stale: int = Field(description="marks of ids no longer in the bank")
    error: Optional[MemesProblem] = Field(None, description="the bank does not open")


class MemesOverview(BaseModel):
    channels: List[MemeBankRow]


class MemeUrls(BaseModel):
    file: str = Field(description="the entry's file (a GIF plays as is)")
    cut: Optional[str] = Field(None, description="the cut-out, when there is one")
    thumb: str = Field(description="the card's picture (thumb(): a still's JPEG, a GIF itself)")


class MemeEntry(BaseModel):
    """An entry of `desk_state` (CF-0693), the index's order."""
    id: str
    file: str
    gif: bool
    description: Optional[str] = None
    tags: List[str] = []
    source_url: Optional[str] = None
    notes: Optional[str] = None
    review: Optional[str] = Field(None, description="`pending` - awaiting the review")
    cutout: bool = Field(description="the index says the meme may be cut out")
    cutout_asset: Optional[Dict[str, Any]] = None
    cut_file: Optional[str] = Field(None, description="the cut-out's file in the bank")
    cut_refused: Optional[str] = Field(None, description="why a `cutout` meme has no cut-out "
                                                         "- in Russian (CF-0762)")
    cut_refused_en: Optional[str] = Field(None, description="CF-0762: the same, the record's "
                                                            "English line (behind «подробнее»)")
    clip: Optional[Dict[str, Any]] = Field(None, description="a GIF's span in its source "
                                                             "{start_s, end_s} - not a file")
    urls: MemeUrls


class MemeBlankBand(BaseModel):
    id: str
    phrase: str = Field(description="the bands in the factory's English words")
    phrase_ru: Optional[str] = Field(None, description="CF-0762: the same in Russian - what "
                                                       "the screen shows")


class MemeBlankBandError(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    error: str = Field(description="in Russian (CF-0762)")
    en: Optional[str] = Field(None, description="CF-0762: the technical line")


class MemeDeskStatus(BaseModel):
    model_config = ConfigDict(extra="allow")
    pending: List[str]
    keep: List[str]
    drop: List[str]
    cut_diff: List[str]
    notes: Dict[str, str]
    stale: List[str]
    blank_bands: List[MemeBlankBand]
    blank_band_errors: List[MemeBlankBandError]
    blank_band_min_share: float
    blank_bands_checked: bool
    blank_bands_note: Optional[str] = Field(None, description="without Pillow: why not checked "
                                                              "- in Russian")
    blank_bands_note_en: Optional[str] = Field(None, description="CF-0762: the same in English "
                                                                 "(the factory's details)")


class MemeDesk(BaseModel):
    """`desk_state` (CF-0693) and what the screen needs to use it."""
    bank: str
    default_bank: bool
    channel: str
    folder: str = Field(description="the bank's folder under the factory root")
    entries: List[MemeEntry]
    decisions: Dict[str, Any] = Field(description="the draft as saved: {id: {v, cut, note, "
                                                  "marked_by?, marked_at?, via?}}")
    status: MemeDeskStatus
    fingerprint: Optional[str] = Field(None, description="sha256 of _desk/decisions.json; null: "
                                                         "no draft - the marks' PUT `base`")
    index_fingerprint: Optional[str] = Field(None, description="sha256 of index.json")
    job: Optional["MemeJobRef"] = Field(None, description="CC-0075: the job running on the "
                                                          "bank (the center's writes there wait "
                                                          "for its end), null when none")


class MemeCopyFrom(BaseModel):
    channel: str = Field(description="the channel on the default bank whose routes serve it")
    id: str = Field(description="the entry of the default bank (`in_reel_bank`)")
    urls: MemeUrls


class MemeCandidate(BaseModel):
    """A row of candidates.json as written (CF-0393) and what the center adds."""
    model_config = ConfigDict(extra="allow")
    id: Optional[str] = None
    name: Optional[str] = None
    imgflip_id: Optional[str] = None
    url: Optional[str] = Field(None, description="the template's file at Imgflip - the API "
                                                 "never fetches it")
    width: Optional[int] = None
    height: Optional[int] = None
    stretch: Optional[float] = Field(None, description="as written in the list")
    passes_ceiling: Optional[bool] = Field(None, description="as written - the problems say "
                                                             "when it disagrees with the rule")
    bytes: Optional[int] = None
    blank_band: Optional[str] = None
    intents: Optional[List[str]] = None
    use: Optional[str] = None
    in_reel_bank: Optional[str] = Field(None, description="the same file's entry in the "
                                                          "default bank")
    stretch_now: Optional[float] = Field(None, description="upscale_factor of the size into "
                                                           "the root's fit box; null: no size")
    group: Literal["pass", "fail", "unknown"] = Field(description="by passes_ceiling, as the "
                                                                  "CLI groups them")
    copy_from: Optional[MemeCopyFrom] = Field(None, description="the default bank's entry "
                                                                "and its media routes")
    status: Optional[Literal["ready", "in_bank", "not_downloaded", "outside_bank"]] = Field(
        None, description="candidates_state (CF-0725): ready - its file lies in the bank, not "
                          "in the index yet (the only kind the yes takes); null - the state "
                          "does not read (accept.reason says why)")
    bank_file: Optional[str] = Field(None, description="the candidate's file in the bank, "
                                                       "when it is there")


class MemeCandidateTotal(BaseModel):
    files: int
    bytes: int


class MemeCandidateCounts(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    pass_: int = Field(alias="pass")
    fail: int
    unknown: int


class MemeAcceptCounts(BaseModel):
    total: int
    ready: int
    in_bank: int
    not_downloaded: int
    outside_bank: int


class MemeAccept(BaseModel):
    """CC-0114: whether the yes is open (candidates_state, CF-0725)."""
    available: bool = Field(description="false: no list, or its state does not read")
    reason: Optional[str] = Field(None, description="in Russian, why not")
    fingerprint: Optional[str] = Field(None, description="candidates_state's \"sha256:<16 hex>\" "
                                                         "of the list and the disk - what the "
                                                         "plan carries")
    counts: Optional[MemeAcceptCounts] = None
    ready: List[str] = Field(description="the ids the yes would take now")
    other_bank: List[str] = Field(description="reel_tail ids - for the default bank, not this")


class MemeAcceptDetail(BaseModel):
    description: Optional[str] = Field(None, description="the user's description of the meme")
    tags: Optional[List[str]] = Field(None, description="the user's tags (English)")
    notes: Optional[str] = None


class MemeAcceptPlanIn(BaseModel):
    ids: Optional[List[str]] = Field(None, description="the candidates the user picked; "
                                                       "omitted - every ready one")
    details: Optional[Dict[str, MemeAcceptDetail]] = Field(
        None, description="{id: {description, tags, notes}} - the user's text for the entries; "
                          "without it the factory writes the candidate record's and «rewrite "
                          "on the desk» in the notes")


class MemeAcceptIn(BaseModel):
    confirm: str = Field(description="the plan's `confirm`")
    answer: str = Field(description="what the user typed themselves - must say «да» and not "
                                    "«нет» (check_accept_answer); passed through as typed, never "
                                    "filled in by the center")


class MemeAcceptRefused(BaseModel):
    id: str
    reason: Literal["in_bank", "not_downloaded", "outside_bank", "other_bank", "no_source_url",
                    "over_ceiling", "media_failed"]
    text: str = Field(description="in Russian")


class MemeAcceptAnswer(BaseModel):
    must_contain: str
    must_not_contain: List[str]
    prompt: Optional[str] = Field(None, description="the question to show the user; null when "
                                                    "nobody would be accepted")


class MemeAcceptPlan(BaseModel):
    """plan_accept (CF-0725, by user via center) - nothing written - and a
    confirm token when someone would be accepted."""
    action: Literal["meme_candidates_accept"]
    channel: str
    bank: str
    ids: List[str] = Field(description="what was asked (all ready ones when ids was omitted)")
    accept: List[str] = Field(description="the ids the yes would take in")
    refused: List[MemeAcceptRefused]
    fingerprint: str = Field(description="the list's \"sha256:<16 hex>\" (candidates_state)")
    answer: MemeAcceptAnswer
    review: Literal["pending"] = Field(description="the new entries wait on the desk")
    downloads: int = Field(description="always 0 - nothing is downloaded here")
    by: Optional[str] = None
    via: Optional[str] = None
    dry_run: Literal[True]
    details: Optional[Dict[str, Dict[str, Any]]] = None
    ok: bool = Field(description="someone would be accepted")
    why: Optional[str] = Field(None, description="in Russian, why not")
    plan_fingerprint: str = Field(description="of the whole plan - bound to the token")
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None
    job: Optional["MemeJobRef"] = Field(None, description="CC-0075: a job running on the bank "
                                                          "- then ok is false, no token")
    machine_job: Optional["MemeJobRef"] = Field(None, description="CC-0076/CF-0761: an alive "
                                                                  "job on another bank of the "
                                                                  "machine - then ok is false")


class MemeAcceptResult(BaseModel):
    """accept_candidates (CF-0725): the entries written into index.json."""
    model_config = ConfigDict(extra="allow")
    action: Literal["meme_candidates_accept"]
    channel: str
    bank: str
    accepted: List[str]
    refused: List[MemeAcceptRefused]
    unchanged: bool = Field(description="index.json not written (nobody accepted)")
    entries: List[Dict[str, Any]] = Field(description="the index entries added (review: "
                                                      "pending)")
    fingerprint: str
    by: Optional[str] = None
    via: Optional[str] = None
    dry_run: Literal[False]
    embedding: Optional[Dict[str, Any]] = Field(None, description="the bank's embedding run "
                                                                  "{done, line, error, en, "
                                                                  "fatal}")
    answer: str = Field(description="the user's answer as typed")


class MemeCandidates(BaseModel):
    """CC-0103: the bank's candidates.json (`meme_desk.py candidates`), read only."""
    channel: str
    bank: str
    default_bank: bool
    path: str = Field(description="the file under the factory root")
    fingerprint: Optional[str] = Field(None, description="sha256 of candidates.json")
    missing: Optional[str] = Field(None, description="in Russian, when the bank has no list")
    listed: Optional[str] = None
    source: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = Field(None, description="the list's own summary, as "
                                                                "written")
    schema_note: Optional[str] = None
    fit_box: Optional[List[int]] = Field(None, description="inserts/meme.json fit_box_px")
    ceiling: Optional[float] = Field(None, description="max_upscale_factor")
    candidates: List[MemeCandidate]
    tail: List[Dict[str, Any]] = Field(description="reel_tail.candidates - for the default "
                                                   "bank, as written")
    problems: List[str] = Field(description="candidate_problems - the CLI's `problem:` lines")
    counts: MemeCandidateCounts
    download: MemeCandidateTotal = Field(description="passing ones not in the default bank")
    copy_: MemeCandidateTotal = Field(alias="copy", description="passing ones in the default "
                                                                "bank - copied, no download")
    copy_channel: Optional[str] = Field(None, description="the channel `copy_from` points at")
    copy_error: Optional[str] = Field(None, description="the default bank did not open")
    accept: MemeAccept


class MemeMarksIn(BaseModel):
    decisions: Dict[str, Dict[str, Any]] = Field(description="the whole draft {id: {v: keep|"
                                                             "drop, cut: bool, note: str}}")
    base: Optional[str] = Field(description="the `fingerprint` of the last GET or save (null: "
                                            "there was no draft); another one is check_changed")


class MemeMarksResult(BaseModel):
    channel: str
    saved: int = Field(description="marks in the saved draft")
    bank: str
    fingerprint: Optional[str] = Field(None, description="of the draft now - the next `base`")


class MemeApplyPlanIn(BaseModel):
    drop: bool = Field(False, description="also remove accepted entries marked drop (`apply "
                                          "--drop`); without it they are `held`")


class MemeRefused(BaseModel):
    id: str
    intent: str = Field(description="the intent it is the default of - never removed")


class MemeApplyBase(BaseModel):
    model_config = ConfigDict(extra="allow")
    action: Literal["meme_apply"]
    channel: str
    bank: str
    default_bank: bool
    drop: bool
    accept: List[str] = Field(description="new entries kept (review taken off)")
    cutout_changed: List[str]
    remove: List[str] = Field(description="entries removed")
    refused: List[MemeRefused]
    held: List[str] = Field(description="accepted entries marked drop that stay without `drop`")
    errors: List[str] = Field(description="the index would be invalid - not applied")
    files_to_delete: List[str] = Field(description="media files that go, under the bank")
    decisions_fingerprint: Optional[str] = None
    index_fingerprint: Optional[str] = None


class MemeApplyPlan(MemeApplyBase):
    ok: bool = Field(description="the index it would write is valid")
    why: Optional[str] = Field(None, description="why not, in Russian")
    fingerprint: str = Field(description="sha256 of index.json + decisions.json + the plan")
    confirm: Optional[str] = Field(None, description="the confirm token - only when ok")
    expires_in_s: Optional[int] = None
    job: Optional["MemeJobRef"] = Field(None, description="CC-0075: a job running on the bank "
                                                          "- then ok is false, no token")
    machine_job: Optional["MemeJobRef"] = Field(None, description="CC-0076/CF-0761: an alive "
                                                                  "job on another bank of the "
                                                                  "machine - then ok is false")


class MemeApplyResult(MemeApplyBase):
    written: Literal[True]


# ---------------------------------------------------------------- the desk's jobs (CC-0075)
MEME_JOB_KINDS = ("cutout", "trim_blank", "add_image", "add_gif", "sheet", "embed")


class MemeJobProgress(BaseModel):
    step: str = Field(description="cutout | trim | embedding | ... - the job's own step")
    i: Optional[int] = None
    of: Optional[int] = None
    text: str = Field("", description="the item (a meme id) or the step's words")


class MemeJobRef(BaseModel):
    """The running job a plan, the desk or a refusal names."""
    job_id: str
    kind: Optional[str] = None
    kind_word: Optional[str] = Field(None, description="the kind in Russian")
    bank: Optional[str] = None
    channel: Optional[str] = Field(None, description="CC-0076/CF-0761 machine_job only: the one "
                                                     "channel whose bank it is, null for the "
                                                     "shared bank")
    started_at: Optional[str] = None
    progress: Optional[MemeJobProgress] = None


MemeDesk.model_rebuild()
MemeAcceptPlan.model_rebuild()
MemeApplyPlan.model_rebuild()


class MemeJobError(BaseModel):
    model_config = ConfigDict(extra="allow")
    code: str = Field(description="the desk's code (MemeDeskError), job_crashed, "
                                  "job_interrupted, embed_failed, spawn_failed")
    text: str = Field(description="in Russian - shown as is")
    en: Optional[str] = None
    log_tail: Optional[str] = Field(None, description="the log's last lines, as text (paths "
                                                      "cut)")


class MemeJobCommit(BaseModel):
    """CF-0847: the commit of a job started with commit_on_done, made by the
    desk itself when the job ended done - committed (sha, the paths), nothing
    (no byte of its paths moved, or no git work tree: detail), refused (git's
    word | touched: <paths>; the files stay in the tree, nothing staged)."""
    model_config = ConfigDict(extra="allow")
    status: Literal["committed", "nothing", "refused"]
    sha: Optional[str] = Field(None, description="committed: the full sha")
    committed: Optional[List[str]] = Field(None, description="committed: the paths, from the "
                                                             "root")
    detail: Optional[str] = Field(None, description="refused: `<git> | touched: <paths>`; "
                                                    "nothing: why, when said")


class MemeJob(BaseModel):
    """`job_status` (CF-0755) + poll_s and the words. `result` is the job
    function's own return (cutout_entries: made / refused / unchanged / missing
    / outside_bank / written; trim_blank_entries: trim / left / under /
    changed / originals / embedding; add_image: entry / file / size /
    trim_note / trim_note_ru), each row of an entry with its `urls` (the
    cut-out: the desk's media kind=cut). CF-0762: the Russian words are what
    the screen shows - refused[].reason (+ `en`), trim[].phrase_ru (`phrase`
    stays English), add_image's trim_note_ru (`trim_note` stays English);
    progress.step of the embedding is meme_desk.EMBED_STEP_RU."""
    model_config = ConfigDict(extra="allow")
    job_id: str
    kind: Optional[str] = None
    kind_word: Optional[str] = None
    bank: Optional[str] = None
    state: Literal["running", "done", "failed", "interrupted"]
    state_word: str = Field(description="идёт | готово | не удалась | оборвалась")
    done: bool
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    pid: Optional[int] = None
    alive: bool = Field(description="its process holds the job's lock")
    progress: Optional[MemeJobProgress] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[MemeJobError] = None
    log: Optional[str] = Field(None, description="the job's log, relative to the root")
    by: Optional[str] = None
    via: Optional[str] = None
    params: Optional[Dict[str, Any]] = None
    max_seconds: Optional[float] = Field(None, description="the plan's worst-case wall time; "
                                                           "null for the cutout and the trim")
    poll_s: Optional[int] = Field(None, description="ask again in so many seconds; null: done")
    commit_on_done: Optional[bool] = Field(None, description="CF-0847: the job commits what it "
                                                             "changed when it ends done; null: "
                                                             "an older desk")
    commit: Optional[MemeJobCommit] = Field(None, description="CF-0847: that commit's outcome; "
                                                              "null: off, failed, still running "
                                                              "or an older desk")


class MemeJobs(BaseModel):
    """`list_jobs` (CF-0755), newest first."""
    channel: str
    bank: str
    running: Optional[MemeJob] = None
    jobs: List[MemeJob]
    poll_s: Optional[int] = Field(None, description="while a job runs")


class MemeJobStarted(BaseModel):
    """The job started in the background - answered at once; poll `status_url`."""
    action: Literal["meme_cutout", "meme_trim", "meme_add_image", "meme_add_gif", "meme_sheet",
                    "meme_embed"]
    channel: str
    kind: str
    bank: str
    job_id: str
    log: Optional[str] = Field(None, description="relative to the root")
    poll_s: int
    status_url: str = Field(description="GET it every poll_s seconds")


class MemeIdReason(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    reason: str = Field(description="in Russian")
    en: Optional[str] = None


class MemeJobPlanBase(BaseModel):
    """A job's plan: the factory's dry run, nothing written, and a confirm
    token (single use, expires_in_s) when ok and no job runs on the bank."""
    model_config = ConfigDict(extra="allow")
    channel: str
    bank: str
    kind: str
    dry_run: Literal[True]
    params: Dict[str, Any] = Field(description="what start_job will get")
    notes: List[str] = Field(description="in Russian - what the plan cannot say yet, what the "
                                         "user decides")
    ok: bool
    why: Optional[str] = Field(None, description="why not, in Russian")
    job: Optional[MemeJobRef] = Field(None, description="the job running on the bank")
    machine_job: Optional[MemeJobRef] = Field(None, description="CC-0076/CF-0761: an alive job "
                                                                "on another bank of the machine "
                                                                "(one per machine) - ok false")
    index_fingerprint: Optional[str] = None
    fingerprint: str = Field(description="sha256 of index.json + the dry run + the params")
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class MemeCutoutPlanIn(BaseModel):
    ids: Optional[List[str]] = Field(None, description="only these (each a `cutout: true` "
                                                       "still); none - every one")
    force: bool = Field(False, description="cut again even when the cut-out is current")


class MemeCutoutMade(BaseModel):
    id: str
    file: str = Field(description="<id>.cutout.png in the bank")
    bbox_px: Optional[List[int]] = Field(None, description="null in the plan")
    coverage: Optional[float] = Field(None, description="null in the plan")


class MemeCutoutPlan(MemeJobPlanBase):
    action: Literal["meme_cutout"]
    available: bool = Field(description="cutout_available(): this machine can cut (macOS 14+ "
                                        "Vision, Video Editor's venv)")
    available_reason: str = Field(description="what it runs on, or why not - in Russian")
    made: List[MemeCutoutMade] = Field(description="would be cut")
    refused: List[MemeIdReason] = Field(description="empty in the plan - Vision says after "
                                                    "the run")
    unchanged: List[str] = Field(description="the cut-out is current (again only with force)")
    missing: List[str]
    outside_bank: List[MemeIdReason]


class MemeTrimPlanIn(BaseModel):
    id: Optional[str] = Field(None, description="only this meme; none - the whole bank")


class MemeTrimRow(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    file: str
    size: List[int]
    trimmed_size: List[int]
    crop: List[int] = Field(description="[top rows, bottom rows] cut")
    phrase: str = Field(description="the bands in the factory's English words")
    phrase_ru: Optional[str] = Field(None, description="CF-0762: the same in Russian - what "
                                                       "the screen shows")
    stretch: float = Field(description="the upscale into the box after the cut")
    ceiling: float
    recut: Optional[bool] = Field(None, description="its cut-out must be made again")


class MemeTrimPlan(MemeJobPlanBase):
    action: Literal["meme_trim"]
    embed: bool = Field(description="the bank is embedded again after the cut")
    trim: List[MemeTrimRow] = Field(description="would be cut")
    left: List[MemeIdReason] = Field(description="not cut: a GIF, one tone, unreadable, outside")
    under: List[MemeTrimRow] = Field(description="the cut would stretch it over the ceiling - "
                                                 "left whole, the user decides")
    changed: List[str]
    originals: Optional[str] = None
    embedding: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------- the adds, the sheet, the embed (CC-0076)
class MemeAddImagePlanIn(BaseModel):
    id: str = Field(description="the new entry's id (bad_entry / duplicate_id otherwise)")
    url: str = Field(description="the still's file, http(s) only - 422 bad_url otherwise")
    source_url: str = Field(description="the page it was found on (http(s))")
    description: str
    tags: Union[List[str], str] = Field(description="a list or \"a,b,c\"")
    notes: Optional[str] = None


class MemeAddGifPlanIn(BaseModel):
    id: str = Field(description="the new entry's id")
    video: str = Field(description="the video's URL, http(s) only - the center never names a "
                                   "local file (local=False)")
    start: float = Field(description="seconds")
    end: float = Field(description="seconds, after start")
    description: str
    tags: Union[List[str], str]
    source_url: Optional[str] = Field(None, description="where the video came from; the URL "
                                                        "itself when omitted")
    notes: Optional[str] = None


class MemeSheetPlanIn(BaseModel):
    video: str = Field(description="the video's URL, http(s) only")
    start: Optional[float] = Field(None, description="seconds, default 0")
    end: Optional[float] = Field(None, description="seconds; none - the video's end")
    every: Optional[float] = Field(None, description="a frame every so many seconds, default 2")
    out: Optional[str] = Field(None, description="the sheet's name under <bank>/_desk/sheets/, "
                                                 ".jpg/.jpeg/.png, default sheet.jpg")


class MemeAddPlanBase(MemeJobPlanBase):
    """plan_add_image / plan_add_gif / plan_sheet (CF-0760): nothing fetched,
    nothing written; `steps` - the progress steps the job will report."""
    id: Optional[str] = None
    file: Optional[str] = Field(None, description="the new file's name in the bank (the "
                                                  "sheet: _desk/sheets/<out>)")
    will_fetch: Literal["url", "yt-dlp"]
    url: Optional[str] = None
    video: Optional[str] = None
    source_url: Optional[str] = None
    span: Optional[Dict[str, Any]] = Field(None, description="{start_s, end_s} (the sheet: + "
                                                             "every_s, frames | null)")
    tags: Optional[List[str]] = Field(None, description="normalised")
    steps: List[str]
    max_seconds: int = Field(description="the job's worst-case wall time")
    max_seconds_word: str = Field(description="the same in Russian, «до 33 мин»")


class MemeAddImagePlan(MemeAddPlanBase):
    action: Literal["meme_add_image"]


class MemeAddGifPlan(MemeAddPlanBase):
    action: Literal["meme_add_gif"]
    cached: bool = Field(description="the video is in <bank>/_desk/clips/ - no download")


class MemeSheetPlan(MemeAddPlanBase):
    action: Literal["meme_sheet"]
    cached: bool
    sheet: str = Field(description="the sheet's path, relative to the root")
    sheet_url: str = Field(description="where the sheet is served once the job is done")
    overwrites: bool = Field(description="a sheet of that name is there and is replaced")


class MemeEmbedPlan(MemeJobPlanBase):
    """The embed has no dry plan in the factory: the center's words, the bank
    and the step's ceiling."""
    action: Literal["meme_embed"]
    steps: List[str]
    max_seconds: int
    max_seconds_word: str


# ---------------------------------------------------------------- notifications (CC-0026)
class NotifyProblem(BaseModel):
    """A refusal of the notification routes - `{message, code, details}` as
    `BatchProblem`."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["bad_kind", "bad_time", "no_text", "refused", "check_changed",
                  "no_reminder", "not_cancellable", "confirm_unknown", "confirm_expired",
                  "confirm_mismatch", "factory_broken"]
    details: List[str] = Field(description="technical lines (behind «подробнее»); the "
                                           "factory's own line where it gave one")


_NPROBLEMS = {s: {"model": NotifyProblem} for s in (409, 422, 500)}
_NCPROBLEMS = {s: {"model": NotifyProblem} for s in (404, 409, 422, 500)}


class NotifyEvent(BaseModel):
    """One row of `notify/sent.jsonl` as stored (`notify.make_event` + the
    backends' answers), every string through `mask_token`."""
    model_config = ConfigDict(extra="allow")
    at: Optional[str] = Field(None, description="UTC ISO")
    kind: Optional[str] = Field(None, description="accept | upload | token | "
                                                  "empty_slot | run_halted | run_done | "
                                                  "needs_human | batch_started | reminder | "
                                                  "test | request_answer | hold_released "
                                                  "(CC-0169, CF-0846: a hold lifted by its "
                                                  "scene) - notify.KINDS")
    channel: Optional[str] = Field(None, description="null: the whole factory")
    key: Optional[str] = Field(None, description="the event's identity - one notification "
                                                 "per key")
    text: Optional[str] = None
    link: Optional[str] = Field(None, description="the center's route (an old row's "
                                                  "console anchor, 8790/#anchor, or "
                                                  "8791 link converted by "
                                                  "notify.center_link, CF-0735, "
                                                  "CC-0035) or a path")
    backends: Optional[Dict[str, str]] = Field(None, description="name -> «ok» | «error: …» "
                                                                 "| «skipped: …»")


class NotifyJournal(BaseModel):
    path: str = Field(description="notify/sent.jsonl (NOTIFY_STATE_DIR moves it)")
    kinds: List[str] = Field(description="the kinds of the bus (notify.KINDS)")
    total: int = Field(description="rows matching kind / channel")
    events: List[NotifyEvent] = Field(description="the last `limit` of them, newest last")


class NotifyReminder(BaseModel):
    """`notify.reminders()`'s entry, with its due time in Moscow."""
    model_config = ConfigDict(extra="allow")
    id: str = Field(description="R<n>")
    due: Optional[str] = Field(description="UTC ISO")
    due_msk: str = Field(description="«YYYY-MM-DD ЧЧ:ММ МСК» (notify.msk_text)")
    text: Optional[str] = None
    created: Optional[str] = None
    by: Optional[str] = None
    via: Optional[str] = Field(None, description="where it was added (`center`); null on the "
                                                 "rows before CF-0700 and on a CLI add")
    status: Literal["pending", "failed", "exhausted", "sent", "cancelled"]
    sent_at: Optional[str] = None
    cancelled_at: Optional[str] = None
    cancelled_by: Optional[str] = Field(None, description="who cancelled it (`user`); null when "
                                                          "not cancelled or cancelled without "
                                                          "a name")
    cancelled_via: Optional[str] = Field(None, description="where it was cancelled (`center`)")
    backends: Optional[Dict[str, Any]] = None
    attempts: int = 0
    last_try: Optional[str] = None
    reason: Optional[str] = Field(None, description="why the last try did not reach the user")


class NotifyReminders(BaseModel):
    path: str = Field(description="notify/reminders.jsonl")
    all: bool = Field(description="false: only the ones not sent and not cancelled")
    max_attempts: int = Field(description="REMINDER_MAX_ATTEMPTS - then `exhausted`")
    reminders: List[NotifyReminder] = Field(description="oldest first")


class NotifyBackendPreview(BaseModel):
    """`notify.test_preview()`'s entry (CF-0700) - one backend that is on, in
    the order of NOTIFY_BACKENDS; `would_get` through `mask_token`."""
    name: str
    known: bool = Field(description="the bus has such a backend (an unknown one is ignored "
                                    "by send)")
    external: bool = Field(description="it sends the text off this machine")
    ready: bool = Field(description="it would take the line: a local one always, an outside "
                                    "one when its addresses are in the settings")
    skip_reason: Optional[str] = Field(None, description="why it would be skipped (`no "
                                                         "NOTIFY_... in .env`, `unknown "
                                                         "backend`); null when ready")
    would_get: Optional[str] = Field(None, description="the text it would get; null for an "
                                                       "unknown backend")


class NotifyCheck(BaseModel):
    backends: List[str] = Field(description="the backends that are on (NOTIFY_BACKENDS)")
    default: List[str] = Field(description="the default when NOTIFY_BACKENDS is not set")
    external: List[str] = Field(description="those on that send the text off this machine")
    preview: List[NotifyBackendPreview] = Field(description="CC-0081: per backend that is on "
                                                            "(notify.test_preview) - read "
                                                            "this, not `lines`")
    lines: List[str] = Field(description="`notify.py test`'s lines as printed - what each "
                                         "would get, would-be-skipped ones with why; kept for "
                                         "the clients of 0.27.0")
    sent: Literal[False] = Field(description="a stand-in: nothing sent, the journal untouched")


class NotifyReminderPlanIn(BaseModel):
    at: str = Field(description="«ЧЧ:ММ» (the next such time) or «YYYY-MM-DD ЧЧ:ММ», Moscow; "
                                "a trailing МСК is fine")
    text: str = Field(description="what to remind of (one line, cut at 1000)")


class NotifyReminderPlan(BaseModel):
    """The plan of a reminder (nothing written) and its confirm token -
    single use, `expires_in_s`, bound to `at` and `text`."""
    action: Literal["notify_reminder_add"]
    ok: bool
    why: Optional[str] = None
    at: str
    due: str = Field(description="UTC ISO (notify.parse_when)")
    due_msk: str
    text: str = Field(description="as the queue will hold it (notify.one_line)")
    by: Literal["user"]
    via: Literal["center"]
    now: str = Field(description="the clock the time was read at")
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class NotifyReminderResult(BaseModel):
    action: Literal["notify_reminder_add"]
    written: Literal[True]
    created: bool = Field(description="false: the same text at the same time was already "
                                      "queued - that one, not a second")
    by: Literal["user"]
    via: Literal["center"]
    reminder: NotifyReminder


class NotifyCancelPlan(BaseModel):
    """The plan of a reminder's cancel (nothing written) and its confirm token -
    single use, `expires_in_s`, bound to the reminder as it is now."""
    action: Literal["notify_reminder_cancel"]
    ok: bool
    why: Optional[str] = None
    id: str = Field(description="R<n>")
    status: Literal["pending", "failed", "exhausted"]
    means: str = Field(description="what a cancel means, in Russian - shown as is")
    reminder: NotifyReminder
    by: Literal["user"]
    via: Literal["center"]
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class NotifyCancelResult(BaseModel):
    action: Literal["notify_reminder_cancel"]
    written: Literal[True]
    by: Literal["user"]
    via: Literal["center"]
    cancelled_at: str = Field(description="UTC ISO")
    cancelled_by: Literal["user"]
    cancelled_via: Literal["center"]
    reminder: NotifyReminder


class NotifyTestChannel(BaseModel):
    """A delivery channel that is on, by name only (notify.test_preview
    without `would_get`) - no token, no chat id, no address."""
    name: str
    known: bool = Field(description="the bus has such a backend")
    external: bool = Field(description="it sends the text off this machine")
    ready: bool = Field(description="it would take the message (an outside one: its addresses "
                                    "are in the settings)")
    skip_reason: Optional[str] = Field(None, description="why it would be skipped - names the "
                                                         "missing setting, never a value")


class NotifyTestSendRow(BaseModel):
    via: str = Field(description="the delivery channel (backend name)")
    ok: bool
    detail: str = Field(description="the bus's word: «ok» | «skipped: …» | «error: …», masked")


class NotifyTestSendPlan(BaseModel):
    """CC-0109: the plan of a test send (`notify.py test --send`) - nothing
    sent; the confirm token single use, `expires_in_s`, bound to the channels
    as they are."""
    action: Literal["notify_test_send"]
    ok: bool
    why: Optional[str] = None
    channels: List[NotifyTestChannel] = Field(description="the channels that are on, in the "
                                                          "order of NOTIFY_BACKENDS")
    names: List[str]
    outside: List[str] = Field(description="those that will send it off this machine")
    note: Optional[str] = Field(None, description="in Russian - no outside channel is ready")
    text: str = Field(description="what the probe will say (the factory's dry run; its time "
                                  "at the send)")
    would: List[NotifyTestSendRow] = Field(
        [], description="CC-0117: per channel what the factory's dry run (send_test(dry_run="
                        "True)) says - ok: «would send», else its «skipped: …»")
    would_deliver: bool = Field(False, description="what notify.delivery would say if every "
                                                   "ready channel took it")
    delivery_reason: Optional[str] = None
    by: Literal["user"]
    via: Literal["center"]
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class NotifyTestSendResult(BaseModel):
    action: Literal["notify_test_send"]
    sent: Literal[True]
    key: str = Field(description="the event's key in notify/sent.jsonl (test:<UTC ISO>)")
    at: Optional[str] = Field(None, description="UTC ISO, the journal row's")
    text: Optional[str] = Field(None, description="the text as the journal holds it")
    results: List[NotifyTestSendRow] = Field(description="per channel, in the order sent")
    delivered: bool = Field(description="notify.delivery: an outside channel said ok, or none "
                                        "was tried")
    delivery_reason: Optional[str] = Field(None, description="why not, the outside answers")
    recorded_by: bool = Field(False, description="CC-0117: the journal row carries by: user, "
                                                 "via: center (send_test(by, via), CF-0720)")
    by: Literal["user"]
    via: Literal["center"]



# ---------------------------------------------------------------- OAuth and API Data (CC-0028)
class OAuthProblem(BaseModel):
    """A refusal of the OAuth and API Data routes - `{message, code, details}`
    as `BatchProblem`."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["config_broken", "unknown_channel", "no_channels", "refused", "check_changed",
                  "busy", "confirm_unknown", "confirm_expired", "confirm_mismatch",
                  "factory_broken"]
    details: List[str] = Field(description="technical lines (behind «подробнее»); the "
                                           "factory's own line where it gave one")


_OPROBLEMS = {s: {"model": OAuthProblem} for s in (404, 409, 422, 500)}


class OAuthScopes(BaseModel):
    required: List[str] = Field(description="publisher_auth.SCOPES - one consent grants them all")
    granted: Optional[List[str]] = Field(description="granted_scopes: the state's list, else the "
                                                     "token file's `scopes` field; null: unknown")
    missing: List[str] = Field(description="the required ones the token lacks (status no-scope)")
    short: Dict[str, str] = Field(description="scope -> its short name (publisher_auth.short)")


class OAuthState(BaseModel):
    """The state file beside the token (`<token>.state.json`), the named
    fields only - it never holds a token value."""
    authorized_at: Optional[str] = Field(None, description="UTC ISO of the consent")
    expires_at: Optional[str] = Field(None, description="Testing: the consent + lifetime_days; "
                                                        "Production: null")
    oauth_mode: Optional[str] = Field(None, description="testing | production - when given")
    lifetime_days: Optional[float] = None
    scopes: Optional[List[str]] = None
    invalid_grant_at: Optional[str] = Field(None, description="the first refusal of Google "
                                                              "since the consent (CF-0618)")
    revoked_from_client_at: Optional[str] = Field(None, description="`api_data.py revoke` "
                                                                    "(CF-0619)")
    revoked_from_client_google: Optional[str] = Field(None, description="revoked | "
                                                                        "invalid_token | "
                                                                        "no token")
    revoked_from_client_by: Optional[str] = Field(None, description="who revoked (CF-0701; "
                                                                    "`user` from the center)")
    revoked_from_client_via: Optional[str] = Field(None, description="through what (`center`)")
    api_data_deleted: Optional[Dict[str, Any]] = Field(None, description="the purge after a "
                                                                         "revocation: reason, "
                                                                         "channels, at, by, via")


class OAuthToken(BaseModel):
    """`publisher_auth.py status` and the state - never a token value, a
    refresh token or a client secret."""
    kind: Literal["ok", "expires-soon", "expired", "no-auth", "no-scope", "unknown-expiry"]
    code: int = Field(description="the CLI's exit code: 0 ok, 1 expires soon, 3 re-authorize")
    line: str = Field(description="the CLI's line, as printed")
    now: str = Field(description="the clock the status was read at")
    expires_at: Optional[str] = Field(description="UTC ISO; null: no fixed term or unknown")
    hours_left: Optional[float] = None
    oauth_mode: Literal["testing", "production"] = Field(description="PUBLISHER_OAUTH_MODE now")
    token_mode: Optional[str] = Field(description="the mode the token was given in")
    lifetime_days: float = Field(description="PUBLISHER_TOKEN_LIFETIME_DAYS (Testing)")
    remind_hours: float = Field(description="PUBLISHER_TOKEN_REMIND_HOURS - expires-soon within")
    scopes: OAuthScopes
    token_present: bool = Field(description="the token file is there (its content is not read "
                                            "here)")
    client_secret_present: bool = Field(description="the OAuth client's file is there")
    state_present: bool
    state: Optional[OAuthState] = None
    authorize_command: str = Field(description="what the user runs to (re)authorize - a browser "
                                               "sign-in, not the center's")


class ApiDataRow(BaseModel):
    entry_id: Optional[str] = None
    channel: Optional[str] = None
    slug: Optional[str] = None
    batch: Optional[str] = None
    publish_day: Optional[str] = None
    video_id: Optional[str] = None


class ApiDataText(BaseModel):
    file: str
    video_id: str


class ApiDataPlan(BaseModel):
    """An `api_data.plan` as data: what a deletion removes (or would)."""
    reason: str
    channels: List[str]
    empty: bool = Field(description="api_data.is_empty - nothing to delete")
    files: List[str] = Field(description="analytics/<ch>/daily|windows|runs.jsonl")
    dirs: List[str] = Field(description="analytics/<ch>/summary")
    rows: List[ApiDataRow] = Field(description="journal rows with source api - their API "
                                               "fields go, the rest is kept")
    texts: List[ApiDataText] = Field(description="a video id in a note or publish/README.md - "
                                                 "replaced by api_data.SCRUBBED")
    journal: str
    lines: List[str] = Field(description="api_data.describe - what the CLI prints")


class ApiDataRevocation(BaseModel):
    revoked_at: str
    due_at: str = Field(description="revoked_at + PURGE_AFTER_DAYS - the auto-run deletes")
    deadline: str = Field(description="revoked_at + RETENTION_DAYS - the policy's limit")
    deleted: Optional[Dict[str, Any]] = None


class ApiDataRules(BaseModel):
    retention_days: int
    purge_after_days: int
    refresh_days: int
    stale_days: int


class ApiDataState(BaseModel):
    kind: Literal["ok", "warn", "bad"]
    line: str = Field(description="`api_data.py status`'s line")
    now: str
    config_error: Optional[str] = Field(description="the publisher's configuration does not "
                                                    "read - the revocation mark is not known")
    revocation: Optional[ApiDataRevocation] = None
    rules: ApiDataRules
    held: ApiDataPlan = Field(description="every channel's API Data - what `purge --all` "
                                          "would delete")
    due: List[ApiDataPlan] = Field(description="what the auto-run would delete now "
                                               "(auto(delete=False)): the revocation's term, "
                                               "the stale rows")
    log: str = Field(description="publish/api-data-deletions.jsonl")


class OAuthRevokeGoogle(BaseModel):
    answer: Optional[Literal["revoked", "invalid_token", "unreachable", "no token"]] = Field(
        description="Google's answer; null: a dry run (nothing asked)")
    detail: Optional[str] = Field(description="the HTTP line or the error - never the token")
    url: str = Field(description="api_data.REVOKE_URL")


class OAuthRevokeTokenFile(BaseModel):
    file: str = Field(description="the token file's path (relative to the root when inside)")
    kind: Optional[Literal["refresh token", "access token"]] = Field(
        description="what would be (was) handed to Google; null: no value")
    missing: Optional[str] = Field(description="why there is no value (no token file, ...)")
    existed: bool = Field(description="the token file was there")
    deleted: bool = Field(description="the token file was deleted (false in a dry run)")


class OAuthRevokeOutcome(BaseModel):
    """`api_data.revoke_result` (CF-0701) as it answered - never a token
    value."""
    dry_run: bool
    ok: bool = Field(description="false: Google did not answer - nothing changed")
    exit: int = Field(description="the CLI's exit code (0 ok)")
    by: Optional[str] = Field(description="who - `user` from the center")
    via: Optional[str] = Field(description="where - `center` from the center")
    google: OAuthRevokeGoogle
    token: OAuthRevokeTokenFile
    state_file: str = Field(description="the token's state file - the revocation mark")
    log: str = Field(description="publish/api-data-deletions.jsonl")
    reason: str = Field(description="`revoked from the client`")
    channels: List[str]
    items: List[str] = Field(description="api_data.describe - deleted, or that would be")
    deletion: Optional[Dict[str, Any]] = Field(description="the deletion log's row (at, reason, "
                                                           "google, by, via, ...); null: "
                                                           "nothing deleted")


class OAuthRevokePreview(BaseModel):
    dry_run: Literal[True]
    lines: List[str] = Field(description="`api_data.py revoke` without --yes, as printed")
    token_present: bool
    result: OAuthRevokeOutcome = Field(description="the same dry run as data (revoke_result, "
                                                   "by user via center)")
    plan: ApiDataPlan
    google_page: str = Field(description="where the owner revokes on Google's side")
    confirm_available: Literal[True] = Field(description="CC-0082: the center revokes - "
                                                         "POST /oauth/revoke/plan, then "
                                                         "/oauth/revoke")


class OAuthRevokePlan(BaseModel):
    """The revocation's plan (CC-0082): the factory's dry run, the API Data it
    deletes, a confirm token when there is a token file or API Data -
    nothing reaches Google."""
    action: Literal["oauth_revoke"]
    ok: bool
    why: Optional[str] = None
    result: OAuthRevokeOutcome = Field(description="revoke_result(yes=False, by user, via "
                                                   "center)")
    plan: ApiDataPlan
    google_page: str
    by: Literal["user"]
    via: Literal["center"]
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class OAuthRevokeResult(BaseModel):
    """The confirmed revocation: `revoke_result(yes=True, by user, via
    center)`'s structured result. `ok: false` (Google did not answer):
    nothing changed, the token is kept, `why` says so."""
    action: Literal["oauth_revoke"]
    ok: bool
    written: bool
    why: Optional[str] = None
    by: Literal["user"]
    via: Literal["center"]
    result: OAuthRevokeOutcome
    plan: ApiDataPlan = Field(description="the API Data the revocation deletes (as planned)")
    google_page: str
    log: str


class ApiDataPurgeIn(BaseModel):
    scope: Literal["all", "channels"] = Field(description="all: every channel (`purge --all`)")
    channels: List[str] = Field(default_factory=list, description="scope channels: the ones "
                                                                  "(`--channel C`)")


class ApiDataPurgePlan(BaseModel):
    """The purge's plan (nothing deleted) and its confirm token when there is
    something to delete - single use, `expires_in_s`, bound to the channels."""
    action: Literal["api_data_purge"]
    ok: bool
    why: Optional[str] = None
    scope: Literal["all", "channels"]
    asked: Optional[List[str]] = Field(description="the channels named; null: all")
    plan: ApiDataPlan
    by: Literal["user"]
    via: Literal["center"]
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class ApiDataPurgeResult(BaseModel):
    action: Literal["api_data_purge"]
    written: Literal[True]
    by: Literal["user"]
    via: Literal["center"]
    plan: ApiDataPlan
    record: Dict[str, Any] = Field(description="the deletion log's row (at, reason, channels, "
                                               "files, dirs, entries, texts, by, via)")
    log: str

class ApiDataAutoPlan(BaseModel):
    """What the deletion by term would delete now (CC-0082, `auto(delete=
    False)`) and a confirm token when there is something - nothing deleted."""
    action: Literal["api_data_auto"]
    ok: bool
    why: Optional[str] = None
    due: List[ApiDataPlan] = Field(description="the revocation's term past, the stale rows")
    revocation: Optional[ApiDataRevocation] = None
    by: Literal["user"]
    via: Literal["center"]
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class ApiDataAutoDone(BaseModel):
    plan: ApiDataPlan
    record: Optional[Dict[str, Any]] = Field(description="the deletion log's row (by, via)")


class ApiDataAutoResult(BaseModel):
    action: Literal["api_data_auto"]
    written: Literal[True]
    by: Literal["user"]
    via: Literal["center"]
    done: List[ApiDataAutoDone] = Field(description="auto(delete=True, by user, via center)")
    revocation: Optional[ApiDataRevocation] = Field(description="after: `deleted` names who")
    log: str



# ---------------------------------------------------------------- maintenance and spend (CC-0032)
class MaintenanceProblem(BaseModel):
    """A refusal of the maintenance routes - `{message, code, details}` as
    `BatchProblem`."""
    message: str = Field(description="for a human, in Russian - shown as is")
    code: Literal["unknown_batch", "invalid", "bad_call", "refused", "batch_open",
                  "check_changed", "busy", "confirm_unknown", "confirm_expired",
                  "confirm_mismatch", "factory_broken", "volume_missing"] = Field(
        description="volume_missing (CC-0104): the month archive's volume is not mounted - "
                    "the factory's own line in the message")
    details: List[str] = Field(description="technical lines (behind «подробнее»); the "
                                           "factory's own line where it gave one")


_MTPROBLEMS = {s: {"model": MaintenanceProblem} for s in (404, 409, 422, 500)}


class MaintenanceScript(BaseModel):
    script: str = Field(description="the factory's script, relative to the root")
    exposed: Literal["read", "plan_confirm", "none"] = Field(
        description="read: GET only; plan_confirm: a write (plan, then confirm); none: not "
                    "exposed")
    routes: List[str]
    why: str = Field(description="what the center does with it, or why not")


class Maintenance(BaseModel):
    scripts: List[MaintenanceScript]
    journals_action: Literal["batch_journals_cleanup"]
    pool_action: Literal["pool_release_delete"]
    by: Literal["user"]
    via: Literal["center"]


class UsageCounters(BaseModel):
    input: int
    cache_write: int
    cache_read: int
    output: int
    thinking: int


class UsageWindow(BaseModel):
    start: Optional[str] = None
    end: Optional[str] = None
    slack_s: Optional[float] = None


class UsageRow(BaseModel):
    """One `usage` event of the newest generation, as written (CF-0101)."""
    ts: Optional[str]
    stage: Optional[str]
    video: Optional[str]
    model: Optional[str]
    role: Optional[str]
    agent: Optional[str]
    session: Optional[str]
    calls: Optional[int]
    minutes: Optional[float]
    first: Optional[float] = Field(description="the first call, POSIX seconds")
    last: Optional[float] = Field(description="the last call, POSIX seconds")
    computed: Optional[str] = Field(description="the generation (when it was counted)")
    window: Optional[UsageWindow]
    usage: UsageCounters


class UsageTotals(BaseModel):
    """`usage.totals` (total = input + cache_write + cache_read + output)."""
    input: int
    cache_write: int
    cache_read: int
    output: int
    thinking: int
    total: int
    fresh: int
    calls: int
    cache_read_pct: float
    fresh_pct: float


class UsageReport(BaseModel):
    """`scripts/usage_report.py <batch> --json` - `usage.read_usage` and
    `usage.totals`; events only, never transcripts."""
    batch: str = Field(description="<channel>/<batch_id>")
    command: str
    events: str = Field(description="the journal read, relative to the root")
    computed: Optional[str]
    ok: bool = Field(description="false: no usage events yet (the CLI's exit 1)")
    why: Optional[str] = Field(description="the factory's hint when there are none")
    rows: List[UsageRow]
    totals: UsageTotals


class CompareLists(BaseModel):
    manual: List[str]
    executor: List[str]


class CompareCounts(BaseModel):
    manual: Dict[str, Optional[int]] = Field(description="scripts (03), videos (05), qc passed "
                                                         "(05), verdicts (06), mp4 under "
                                                         "videos/; null: no such file")
    executor: Dict[str, Optional[int]]


class CompareWall(BaseModel):
    manual: Dict[str, float] = Field(description="`## Where the wall went` of RUN_SUMMARY.md, "
                                                 "seconds per part; {} without it")
    executor: Dict[str, float]
    operator_wait_s: Dict[str, Optional[float]] = Field(
        description="waiting for a human + operator idle + unattributed, per side")


class CompareRuns(BaseModel):
    """`scripts/compare_runs.py <manual> <executor> --json` (CF-0204) - its
    `compare`."""
    command: str
    manual: str = Field(description="<channel>/<batch_id> run by hand")
    executor: str = Field(description="<channel>/<batch_id> run by the executor")
    stages: CompareLists = Field(description="the stage-start sequence of each side")
    files: CompareLists = Field(description="the contract files and records of each side")
    counts: CompareCounts = Field(description="the yield counts of each side - shown, not "
                                              "judged")
    wall: CompareWall
    defects: List[str] = Field(description="each a defect of the move")
    notes: List[str] = Field(description="a stage skipped on its condition, ...")
    same: bool = Field(description="no defect - the same stages, order and files")
    exit_code: Literal[0, 1] = Field(description="the CLI's: 0 the same, 1 a defect")


class ArchiveDryRun(BaseModel):
    """`scripts/archive_publish_month.py --dry-run` as the user runs it - its
    lines verbatim (the root's prefix cut, the volume as `<name>:`). A view:
    the write of step (a) is `ArchivePlan` -> `ArchiveResult` (CC-0104)."""
    command: str
    dry_run: Literal[True]
    monthly: bool = Field(description="the whole monthly run (b)-(d) too; false: "
                                      "--publish-only")
    exit_code: Optional[int] = Field(description="null when it did not run")
    ok: bool
    lines: List[str]
    stderr: Optional[str]
    error: Optional[str] = Field(description="why it did not run or answer")
    volume: Optional[str] = Field(description="the archive volume's name")
    confirm_available: bool = Field(
        description="CC-0104: true - step (a) (--publish-only) has a plan and a confirm "
                    "(POST /api/maintenance/archive/plan, then POST /api/maintenance/archive); "
                    "false for the whole monthly run (its steps b-d are lines only)")
    plan_action: Optional[str] = Field(None, description="the confirm's action: "
                                                         "publish_month_archive")


class ArchiveFile(BaseModel):
    """A file that leaves `publish/` (the factory's `from_publish`)."""
    path: str = Field(description="relative to the root")
    kind: str = Field(description="mp4 | md")
    bytes: int
    op: str = Field(description="git rm (a note) | delete (a video)")


class ArchiveJob(BaseModel):
    """One channel and month of the factory's `--json` document."""
    channel: str
    month: str = Field(description="YYYY-MM")
    zip: str = Field(description="the zip on the volume, as `<volume name>:<path>`")
    action: Optional[str] = Field(None, description="create | extend; null - the volume "
                                                    "is not mounted")
    old_members: int = Field(description="members already in the zip (extend)")
    members: int = Field(description="members of the zip after the run")
    bytes: Optional[int] = Field(None, description="the members' bytes")
    from_publish: List[ArchiveFile]
    day_dirs: List[str] = Field(description="the day folders removed from publish/")
    status: Optional[str] = Field(None, description="planned | moved | failed")


class ArchivePlan(BaseModel):
    """CC-0104: `archive_publish_month.py --dry-run --json --publish-only` and
    a confirm token when it can run now - nothing touched."""
    action: Literal["publish_month_archive"]
    ok: bool
    why: Optional[str] = Field(None, description="why there is no token, in Russian - the "
                                                 "factory's own line where it gave one")
    command: str
    apply_command: str = Field(description="what the confirm runs")
    today: Optional[str] = Field(None, description="the factory's day (Moscow), YYYY-MM-DD")
    volume: Optional[str] = Field(None, description="the archive volume's name")
    mounted: Optional[bool] = Field(None, description="null - no debt, not asked")
    debt: List[Dict[str, Any]] = Field(description="{channel, month, days, files} owed")
    legacy_skipped: List[Dict[str, Any]] = Field(description="months in the old folder form "
                                                             "on the volume - skipped")
    jobs: List[ArchiveJob]
    need_bytes: Optional[int] = None
    free_bytes: Optional[int] = None
    margin_bytes: Optional[int] = None
    enough_space: Optional[bool] = None
    open_batches: List[str] = Field(description="<channel>/<batch> going now - a write waits")
    lines: List[str] = Field(description="the dry run's lines")
    exit_code: Optional[int] = None
    by: Literal["user"]
    via: Literal["center"]
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class ArchiveResult(BaseModel):
    """The confirmed month archive: the factory's document of the real run
    `--publish-only --json --by user --via center`."""
    action: Literal["publish_month_archive"]
    written: Literal[True]
    by: Literal["user"]
    via: Literal["center"]
    command: str
    today: Optional[str] = None
    volume: Optional[str] = None
    jobs: List[ArchiveJob] = Field(description="each with its status: moved | failed")
    commit: Optional[Dict[str, Any]] = Field(None, description="{message, by, via} of the "
                                                               "commit the run made or put off")
    committed: bool = Field(description="the run's log says the commit was made (an open "
                                        "batch or foreign changes put it off: false)")
    exit_code: int
    lines: List[str] = Field(description="the run's lines")


class JournalRow(BaseModel):
    """One journal `cleanup_batch_journals.plan` touches."""
    rel: str = Field(description="pipeline/<channel>/<batch>/RUN_EVENTS.jsonl")
    mode: Literal["whole", "lines"] = Field(description="whole: the journal is deleted (its "
                                                        "backfill twin holds the accounting); "
                                                        "lines: foreign lines cut")
    lines: int
    bytes: int
    drop: int = Field(description="lines that go")
    drop_bytes: int
    sha: str = Field(description="sha256 of the journal as planned")
    after: int = Field(description="lines left")
    after_lines: Optional[int] = Field(None, description="CC-0117: the confirm's - what "
                                                         "`delete` reports (CF-0720)")
    after_bytes: Optional[int] = None
    applied: Optional[bool] = Field(None, description="the confirm's: written by `delete`")


class JournalTotals(BaseModel):
    journals: int
    whole: int
    whole_lines: int
    whole_bytes: int
    cut_journals: int
    cut_lines: int
    cut_bytes: int


class JournalsPlan(BaseModel):
    """`cleanup_batch_journals.plan(root)` and a confirm token when there is
    something and no batch is open - nothing touched."""
    action: Literal["batch_journals_cleanup"]
    ok: bool
    why: Optional[str] = None
    command: str
    journals: List[JournalRow]
    totals: JournalTotals
    open_batches: List[str] = Field(description="<channel>/<batch> going now - a write waits")
    log: str = Field(description="the script's log")
    by: Literal["user"]
    via: Literal["center"]
    fingerprint: str
    confirm: Optional[str] = None
    expires_in_s: Optional[int] = None


class JournalsResult(BaseModel):
    """The confirmed cleanup: `cleanup_batch_journals.delete(root, rows)`."""
    action: Literal["batch_journals_cleanup"]
    written: Literal[True]
    by: Literal["user"]
    via: Literal["center"]
    done: List[JournalRow]
    totals: JournalTotals
    backup: Optional[str] = Field(description="the copy of the originals (in $TMPDIR, "
                                              "`.../cf0530-journals-*`)")
    log: str
    lines: List[str] = Field(description="what this run wrote into the script's log")


# ---------------------------------------------------------------- the footage pool (CC-0105)
class PoolTopic(BaseModel):
    """A topic that references a source, as `pool_release.plan` says it."""
    batches: List[str] = Field(description="<channel>/<batch_id> (a rebuild rebuilds/<ts>)")
    status: str = Field(description="published, withdrawn, accepted_not_published, "
                                    "rejected_not_withdrawn, no_video")
    evidence: List[str] = Field(default_factory=list,
                                description="where the status comes from (uploads.json, "
                                            "README.md, acceptance-log, withdrawn, stale)")
    stale: Optional[bool] = Field(None, description="finished by the stale-days rule")


class PoolCandidate(BaseModel):
    batches: List[str]
    status: str


class PoolSource(BaseModel):
    """One source of `shared/footage/` - an entry of the plan's lists."""
    video_id: str
    files: List[str] = Field(description="the source's media and sidecars in shared/footage/")
    bytes: int
    topics: Optional[Dict[str, PoolTopic]] = Field(
        None, description="release / keep: every topic that references it")
    newest_batch: Optional[str] = None
    blocked_by: Optional[List[str]] = Field(
        None, description="keep: why it stays - open_batch, a live topic's status")
    open_batches: Optional[List[str]] = None
    candidate_of: Optional[Dict[str, PoolCandidate]] = Field(
        None, description="orphan: the topics it was a refused candidate of")
    untopiced_in: Optional[List[str]] = None
    kind: Optional[Literal["refused_candidate", "untopiced", "unmentioned"]] = Field(
        None, description="orphan: why no batch references it")


class PoolSum(BaseModel):
    sources: int
    bytes: int


class PoolTotals(BaseModel):
    release: PoolSum
    keep: PoolSum
    orphan: PoolSum


class PoolUnresolved(BaseModel):
    kind: str = Field(description="the record that names it (uploads.json, README.md, ...)")
    entry: str = Field(description="<channel>/<batch>/<slug> whose batch is not on this disk")


class PoolVariant(BaseModel):
    """`pool_release.variants`: what a further rule would free - not a rule."""
    rule: str
    sources: int
    bytes: int


class PoolView(BaseModel):
    """`scripts/runlog pool-release --json --variants [--stale-days N]` -
    `pool_release.plan` and `variants`; nothing written."""
    command: str
    at: str = Field(description="the plan's time (UTC ISO)")
    stale_days: Optional[int] = Field(description="the 14-day rule's N, null: not applied")
    open_batches: List[str] = Field(description="open batches and rebuilds (runlog.open_batches) "
                                                "- --delete refuses while any is")
    release: List[PoolSource] = Field(description="every topic published or withdrawn - "
                                                  "what --delete removes")
    keep: List[PoolSource] = Field(description="a live or undecided topic references it")
    orphan: List[PoolSource] = Field(description="no batch on this disk references it - never "
                                                 "deleted by --delete")
    unresolved: List[PoolUnresolved]
    pool: PoolSum = Field(description="the whole pool")
    totals: PoolTotals
    variants: List[PoolVariant] = Field(description="the user's question in numbers")
    journal: str = Field(description="shared/footage/release-log.jsonl")
    delete_action: Literal["pool_release_delete"]


class PoolReleaseIn(BaseModel):
    stale_days: Optional[int] = Field(None, description="the stale rule's N, 1..365 (the "
                                                        "monthly archive passes 14); null: not "
                                                        "applied")


class PoolReleasePlan(BaseModel):
    """What `pool-release --delete` would remove (its own `plan`) and a confirm
    token when there is something and no batch is open - nothing touched."""
    action: Literal["pool_release_delete"]
    ok: bool
    why: Optional[str] = Field(description="why there is no token")
    command: str
    at: str
    stale_days: Optional[int]
    release: List[PoolSource]
    totals: PoolSum = Field(description="what goes")
    kept: PoolSum = Field(description="what stays: a live topic references it")
    orphan: PoolSum = Field(description="what stays: no batch references it")
    open_batches: List[str] = Field(description="open batches (runlog batch-active and the "
                                                "plan's own)")
    journal: str
    by: Literal["user"]
    via: Literal["center"]
    recorded_by: Literal[True] = Field(description="the factory's `released` rows carry "
                                                   "by/via (CF-0720 delete(by, via))")
    rows: List[Dict[str, Any]] = Field(
        [], description="CC-0117: the `released` rows the factory's dry run (delete(..., "
                        "dry_run=True)) says the confirm would write; empty without a token")
    fingerprint: str
    confirm: Optional[str]
    expires_in_s: Optional[int]


class PoolReleaseResult(BaseModel):
    """The confirmed release: the same plan, then `pool_release.delete`."""
    action: Literal["pool_release_delete"]
    written: Literal[True]
    by: Literal["user"]
    via: Literal["center"]
    recorded_by: Literal[True]
    stale_days: Optional[int]
    deleted: List[str] = Field(description="the sources removed (video ids)")
    totals: PoolSum = Field(description="as planned; each row carries what was removed")
    journal: str
    rows: List[Dict[str, Any]] = Field(description="the `released` rows this run wrote")


def _writing(responses):
    """The responses of a write route: its own, and 409 may be `WritesProblem`."""
    out = dict(responses or {})
    have = (out.get(409) or {}).get("model")
    out[409] = {"model": Union[have, WritesProblem] if have else WritesProblem,
                "description": "a conflict; `not_working_factory` (CC-0058): not the working "
                               "factory - only reading"}
    return out


# ---------------------------------------------------------------- the guard
#: CC-0036: what a client that is not this machine reaches without a session -
#: the login's routes (under <base>api/) and the files the login screen loads
#: (under <base>: the page itself - any route without a dot, `index.html` - the
#: bundle `assets/`, the icons). The center's files are its code, no data.
AUTH_OPEN_API = (("GET", "/auth/state"), ("HEAD", "/auth/state"), ("POST", "/auth/login"),
                 ("POST", "/auth/logout"))
AUTH_NO_SESSION_HEADER = ("/auth/login", "/auth/logout")
OPEN_FILES = ("index.html",)
OPEN_DIRS = ("assets/",)
OPEN_PREFIXES = ("favicon", "apple-touch-icon")
AUTH_REQUIRED_RU = "Нужен вход: откройте центр и введите пароль"


class Guard:
    """ASGI middleware: the checks of the module docstring, and the security
    headers on every answer. CC-0036: a client that is not this machine needs
    the session cookie (`api/auth.py`) for everything but `AUTH_OPEN_API` and
    the login screen's files - 401 `AuthProblem` `auth_required`."""

    def __init__(self, app, settings: Settings, token: str, auth=None):
        self.app = app
        self.settings = settings
        self.token = token
        self.auth = auth or auth_mod.Auth(settings.password_hash)
        self.hosts = set(settings.allowed_hosts())
        self.origins = set(settings.allowed_origins())

    def open_without_login(self, method, path):
        s = self.settings
        api = s.api_prefix
        if path.startswith(api + "/"):
            return (method, path[len(api):]) in AUTH_OPEN_API
        if path == api or method not in ("GET", "HEAD") or not path.startswith(s.base_path):
            return False
        rel = path[len(s.base_path):]
        name = rel.rsplit("/", 1)[-1]
        return (rel in OPEN_FILES or "." not in name
                or (rel.startswith(OPEN_DIRS) and ".." not in rel.split("/"))
                or ("/" not in rel and name.startswith(OPEN_PREFIXES)))

    def refuse(self, scope, state=None):
        """(status, body) of a refusal, or None. `state` gets `refresh`: the
        session's cookie to set again."""
        s = self.settings
        client = (scope.get("client") or ("", 0))[0]
        if s.loopback_only and not (client in ("127.0.0.1", "::1") or client.startswith("127.")):
            return 403, {"detail": f"only from this machine ({s.host}), not {client!r}",
                         "guard": "client"}
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "")
        if host not in self.hosts:
            return 403, {"detail": f"Host {host!r}: not this address", "guard": "host"}
        method, path = scope["method"], scope.get("path", "")
        if self.auth.required(client):
            token = cookie_parser(headers.get("cookie", "")).get(auth_mod.COOKIE)
            ok, refresh = self.auth.check(token)
            if ok and refresh and state is not None:
                state["refresh"] = token
            if not ok and not self.open_without_login(method, path):
                return 401, {"detail": AUTH_REQUIRED_RU, "code": "auth_required",
                             "retry_after": None}
        if method in SAFE_METHODS:
            return None
        bad = self.refuse_write(method, path, headers)
        return (403, {"detail": bad[1], "guard": bad[0]}) if bad else None

    def refuse_write(self, method, path, headers):
        s = self.settings
        origin = headers.get("origin")
        if origin is not None:
            if origin.rstrip("/") not in self.origins:
                return "origin", f"Origin {origin!r}: not this center"
        else:
            ref = headers.get("referer") or ""
            if not any(ref == o or ref.startswith(o + "/") for o in self.origins):
                return "origin", "no Origin and no Referer of this center"
        if method == "POST" and path[len(s.api_prefix):] in AUTH_NO_SESSION_HEADER \
                and path.startswith(s.api_prefix + "/"):
            return None        # CC-0036: the login page has no X-CC-Session yet; Origin is checked
        got = headers.get(SESSION_HEADER.lower(), "")
        if not got or not hmac.compare_digest(got.encode(), self.token.encode()):
            return "session", f"no valid {SESSION_HEADER} (GET {s.api_prefix}/session)"
        return None

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        state = {}

        async def send_secured(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                extra = list(SECURITY_HEADERS)
                if state.get("refresh"):      # CC-0036: the sliding session's cookie, again
                    extra.append((b"set-cookie", auth_mod.cookie_header(
                        state["refresh"], self.settings.base_path).encode("latin-1")))
                message["headers"] = list(message["headers"]) + extra
            await send(message)

        bad = self.refuse(scope, state)
        if bad:
            status, body = bad
            resp = JSONResponse(body, status_code=status)
            return await resp(scope, receive, send_secured)
        return await self.app(scope, receive, send_secured)


# ---------------------------------------------------------------- the center
def _not_built(settings):
    return HTMLResponse(
        "<!doctype html><meta charset=utf-8><title>Командный центр</title>"
        "<p>Центр не собран: нет <code>index.html</code> в каталоге "
        "<code>CC_FRONTEND_DIST</code> (по умолчанию <code>frontend/dist</code>). "
        "Соберите: <code>cd frontend && npm ci && npm run build</code>.</p>"
        f"<p>API работает: <a href='{settings.api_prefix}/health'>{settings.api_prefix}/health</a></p>",
        status_code=503, headers={"Cache-Control": "no-store"})


def _center_response(settings, rel):
    dist = settings.frontend_dist
    index = dist / "index.html"
    if not index.is_file():
        return _not_built(settings)
    if rel:
        try:
            target = (dist / rel).resolve()
        except (OSError, RuntimeError):
            target = None
        if target is not None and target != dist.resolve() and \
                target.is_relative_to(dist.resolve()) and target.is_file():
            return FileResponse(target)
        if "." in Path(rel).name:      # an asset that is not there: not the page
            return Response("not found\n", status_code=404, media_type="text/plain")
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


# ---------------------------------------------------------------- the app
def create_app(settings: Optional[Settings] = None, token: Optional[str] = None,
               auth: Optional[auth_mod.Auth] = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.check_bind()          # CC-0036: not loopback without a password - no app
    token = token or secrets.token_urlsafe(32)
    # CC-0036: the sessions and the failed logins of this process (the tests give
    # their own, with a clock)
    auth = auth or auth_mod.Auth(settings.password_hash)
    prefix = settings.api_prefix
    app = FastAPI(title=TITLE, version=API_VERSION,
                  description="The API of the factory's command center (CC-0003). "
                              "Contract: api/openapi.json.",
                  openapi_url=f"{prefix}/openapi.json", docs_url=None, redoc_url=None)
    app.state.settings = settings
    app.state.token = token
    app.state.auth = auth
    # CC-0155 (CF-0841): the process as it started - once, never per request
    # (`GET /api/version` started_at / commit_at_start / stale)
    started = factory.process_start(settings.factory_root)

    # CC-0058: writes only in the working factory (`agents_lock.is_working_factory`,
    # CF-0677) - every route that writes depends on `require_writes`; the test
    # that walks the app's routes holds every non-GET route to it or to its
    # allow-list (tests/test_cc_api_writes.py).
    def writes_state():
        ok, why = factory.working_factory(settings.factory_root)
        # CC-0097: the root named by its last part, never its absolute path
        why = paths.scrub(why, paths.named(settings.factory_root)) if why else None
        return {"writes": bool(ok or settings.writes_dev), "writes_reason": why,
                "writes_dev": settings.writes_dev}

    def require_writes(request: Request):
        ok, why = factory.working_factory(settings.factory_root)
        if ok:
            return
        if settings.writes_dev:
            WRITES_LOG.warning("CC_API_WRITES=dev: %s %s writes in %s - %s",
                               request.method, request.url.path, settings.factory_root, why)
            return
        raise WritesRefused(why, settings.factory_root)

    app.state.require_writes = require_writes
    writes = [Depends(require_writes)]
    if settings.writes_dev:
        WRITES_LOG.warning("CC_API_WRITES=dev: the developer's flag is on - the API writes in %s "
                           "even if it is not the working factory (each such write is logged)",
                           settings.factory_root)

    api = APIRouter(prefix=prefix, tags=["api"], responses={
        401: {"model": AuthProblem, "description": "CC-0036: a client that is not this machine "
                                                   "without a session - `auth_required`"},
        403: {"model": Refusal, "description": "refused by the guard (Host, Origin, session)"}})

    @api.get("/health", response_model=Health, summary="alive")
    def health():
        return {"status": "ok", "api": API_VERSION, **writes_state()}

    @api.get("/version", response_model=Version,
             summary="the factory's version, the agents' pins, the center's build")
    def version():
        root = settings.factory_root
        agents, err = factory.agent_pins(root)
        center = factory.center_version(settings.frontend_dist)
        # CC-0097: no absolute path - `dist` relative to the root (or
        # `.../<name>`), the lock's words with the root's prefix cut
        center["dist"] = paths.rel(root, center["dist"])
        live = factory.factory_version(root)
        return {"api": API_VERSION, **writes_state(), "factory": live,
                "agents": paths.scrub(agents, paths.prefixes(root)),
                "agents_error": paths.scrub(err, paths.prefixes(root)), "center": center,
                **started, **dict(zip(("stale", "stale_paths"),
                                      factory.process_stale(root, started, live)))}

    @api.get("/versions", response_model=Versions,
             summary="versions and the agents: the lock, scripts/agents status, the factory, "
                     "the center (CC-0030)")
    def versions_view(fresh: bool = Query(False, description="check again, not the kept "
                                                                 "answer")):
        return versions.versions(settings.factory_root, settings.frontend_dist, fresh=fresh)

    # CC-0124: the development tasks, read only (api/dev.py)
    @api.get("/dev/tasks", response_model=DevTasks, responses=_DVPROBLEMS,
             summary="the development tasks of the factory and the center from git - "
                     "frontmatter, archived, checklist counts; filters and search (CC-0124)")
    def dev_tasks(project: Optional[str] = Query(None, description="factory | center"),
                  milestone: Optional[str] = Query(None, description="comma list, exact"),
                  status: Optional[str] = Query(None, description="comma list, exact"),
                  type: Optional[str] = Query(None, description="comma list, exact"),
                  repo: Optional[str] = Query(None, description="comma list, exact"),
                  q: Optional[str] = Query(None, description="every word in the id, the title "
                                                             "or the body, any case")):
        return dev.tasks(settings.factory_root, project=project, milestone=milestone,
                         status=status, type=type, repo=repo, q=q)

    @api.get("/dev/tasks/{task_id}", response_model=DevTask, responses=_DVPROBLEMS,
             summary="one development task: frontmatter, body, checklist, related ids, "
                     "its commits (CC-0124)")
    def dev_task(task_id: str):
        return dev.task(settings.factory_root, task_id)

    @api.get("/dev/roadmap", response_model=DevRoadmaps, responses=_DVPROBLEMS,
             summary="ROADMAP.md of the factory and the center: milestones, sprints, DONE "
                     "dates, task ids in table order (CC-0124)")
    def dev_roadmap(project: Optional[str] = Query(None, description="factory | center")):
        return dev.roadmap(settings.factory_root, project=project)

    # CC-0036: the login from the home network (api/auth.py)
    def _client(request):
        return request.client.host if request.client else ""

    def _token(request):
        return cookie_parser(request.headers.get("cookie", "")).get(auth_mod.COOKIE)

    @api.get("/auth/state", response_model=AuthState,
             summary="CC-0036: whether this client has to log in and whether it is")
    def auth_state(request: Request):
        return {"required": auth.required(_client(request)),
                "logged_in": auth.check(_token(request))[0]}

    @api.post("/auth/login", response_model=LoginResult,
              summary="CC-0036: the password -> the session cookie (HttpOnly, SameSite=Strict)",
              responses={401: {"model": AuthProblem, "description": "wrong_password"},
                         409: {"model": AuthProblem, "description": "auth_off: no "
                                                                    "CC_PASSWORD_HASH"},
                         429: {"model": AuthProblem, "description": "locked: too many wrong "
                                                                    "passwords; retry_after"}})
    def auth_login(request: Request, body: LoginIn):
        if not auth.enabled:
            return JSONResponse({"detail": "Вход по паролю не включён: нет CC_PASSWORD_HASH",
                                 "code": "auth_off", "retry_after": None}, status_code=409)
        try:
            got = auth.login(_client(request), body.password)
        except auth_mod.Locked as e:
            who = ("с этого адреса" if e.scope == "ip" else "со всех адресов сети")
            return JSONResponse(
                {"detail": f"Слишком много неверных паролей {who}: вход закрыт, попробуйте "
                           f"через {(e.retry_after + 59) // 60} мин",
                 "code": "locked", "retry_after": e.retry_after},
                status_code=429, headers={"Retry-After": str(e.retry_after)})
        if got is None:
            return JSONResponse({"detail": "Неверный пароль", "code": "wrong_password",
                                 "retry_after": None}, status_code=401)
        return JSONResponse({"logged_in": True}, headers={
            "Set-Cookie": auth_mod.cookie_header(got, settings.base_path),
            "Cache-Control": "no-store"})

    @api.post("/auth/logout", response_model=LoginResult,
              summary="CC-0036: end this session, clear its cookie")
    def auth_logout(request: Request):
        auth.logout(_token(request))
        return JSONResponse({"logged_in": False}, headers={
            "Set-Cookie": auth_mod.cookie_header("", settings.base_path, max_age=0)})

    @api.get("/session", response_model=Session, summary="the token of a POST")
    def session():
        return {"token": token, "header": SESSION_HEADER}

    @api.get("/questions", response_model=Questions,
             summary="the questions to the user (CF-0652)")
    def questions(status: Literal["live", "open", "answered", "resolved", "all"] = "live"):
        return {"status": status,
                "questions": factory.questions(settings.factory_root, status)}

    def problem(body, status):
        """CC-0098: the one way out of every refusal of the API - the
        exception handlers (ChannelFault, BatchFault, WritesRefused) and the
        factory's own refusals of the questions and requests. Its `details`
        are often an exception's text (`f"{type(e).__name__}: {e}"`) that
        carries absolute paths: the whole body goes through `paths.clean`
        here - inside the root relative, the root itself `.../<name>`, any
        other absolute path `.../<last part>`, a URL whole."""
        return JSONResponse(paths.clean(body, settings.factory_root), status_code=status)

    def _done(got):
        q, err = got
        if err:
            return problem(dict({"detail": err[1]}, **({"code": err[2]} if len(err) > 2 else {})),
                           err[0])
        return q

    problems = {404: {"model": Problem, "description": "no such question"},
                409: {"model": Problem, "description": "the question is already resolved; "
                                                       "with accept: no suggestion "
                                                       "(`no_suggestion`) or another one than "
                                                       "the user saw (`check_changed`)"}}

    @api.post("/questions/{qid}/answer", response_model=Question, responses=_writing(problems),
              dependencies=writes,
              summary="answer a question (open/answered -> answered)")
    def answer(qid: str, body: AnswerIn):
        """CC-0086: the answer `via="center"`; `accepted_suggestion` when it is the
        question's current suggestion (`accept`, or a text that is it) - read
        fresh here, not taken from the client."""
        return _done(factory.answer_question(settings.factory_root, qid, body.text, body.by,
                                             via=CENTER_VIA, accept=body.accept,
                                             suggested_at=body.suggested_at))

    @api.post("/questions/{qid}/resolve", response_model=Question,
              responses=_writing(problems), dependencies=writes,
              summary="mark a question resolved")
    def resolve(qid: str, body: ResolveIn):
        return _done(factory.resolve_question(settings.factory_root, qid, body.note, body.by))

    # CC-0018: the queue of the user's requests to the operator (CF-0684,
    # shared/operator_requests.py). The center adds, closes and cancels -
    # `by: "user"`; `next`, `answer` (it sends to Telegram) and `resend` are
    # the operator session's, through the factory's CLI - never routes here.
    def _req(got):
        r, err = got
        if err:
            return problem(err[1], err[0])
        return r

    req_404 = {404: {"model": RequestProblem, "description": "no such request (`not_found`)"}}
    req_409 = {409: {"model": RequestProblem,
                     "description": "a step the request's state does not allow "
                                    "(`not_answered`, `already_closed`, `already_cancelled`, "
                                    "`cancel_answered`, ...)"}}
    req_422 = {422: {"model": RequestProblem,
                     "description": "the input refused by the factory (`text_empty`, "
                                    "`text_too_long`, `context_invalid`, `status_unknown`); "
                                    "a malformed body is FastAPI's validation error"}}

    @api.get("/requests", response_model=OperatorRequests, responses=req_422,
             summary="the requests to the operator (CF-0684), oldest first")
    def requests_list(status: str = Query(
            "live", description="live (open + taken + answered) | open | taken | answered | "
                                "closed | cancelled | all - the factory judges it "
                                "(`status_unknown`)",
            json_schema_extra={"enum": list(factory.REQUEST_STATUSES)})):
        rs, err = factory.requests_list(settings.factory_root, status)
        if err:
            return problem(err[1], err[0])
        return {"status": status, "requests": rs}

    @api.get("/requests/{rid}", response_model=OperatorRequest, responses=req_404,
             summary="one request to the operator")
    def request_one(rid: str):
        return _req(factory.request_get(settings.factory_root, rid))

    @api.post("/requests", response_model=OperatorRequest, responses=_writing(req_422),
              dependencies=writes,
              summary="ask the operator (by: user) - the request is queued, nothing runs")
    def request_add(body: OperatorRequestIn):
        return _req(factory.request_add(settings.factory_root, body.text, "user",
                                        channel=body.channel, context=body.context))

    @api.post("/requests/{rid}/close", response_model=OperatorRequest,
              responses=_writing({**req_404, **req_409}), dependencies=writes,
              summary="close an answered request (answered -> closed, by: user)")
    def request_close(rid: str):
        return _req(factory.request_close(settings.factory_root, rid, "user"))

    @api.post("/requests/{rid}/cancel", response_model=OperatorRequest,
              responses=_writing({**req_404, **req_409}), dependencies=writes,
              summary="cancel a request not yet answered (open/taken -> cancelled, by: user)")
    def request_cancel(rid: str):
        return _req(factory.request_cancel(settings.factory_root, rid, "user"))

    root = settings.factory_root

    def clean(obj):
        """CC-0098: an answer with the factory's rows, argv and log paths (the
        batch's launch, stop, resume, rebuild; the token's revocation) through
        the one cutter - no absolute path of this machine leaves."""
        return paths.clean(obj, root)

    @api.get("/channels", response_model=ChannelList, summary="the channels")
    def channel_list():
        return channels.listing(root)

    # before /channels/{channel}: «template» is a route, not a channel
    @api.get("/channels/template", response_model=ChannelTemplate,
             summary="what a new channel is made of: inputs, defaults, notes, files (CC-0008)")
    def channel_template():
        return channels.template(root)

    @api.post("/channels", response_model=CreateResult, responses=_writing(_PROBLEMS),
              summary="a new channel: check -> write -> one commit «Канал <имя>: создан "
                      "(из центра)»; `dry_run` writes nothing")
    def channel_create(new: NewChannel, request: Request):
        if not new.dry_run:            # CC-0058: a dry run writes nothing - allowed anywhere
            require_writes(request)
        return channels.create(root, new.model_dump())

    @api.get("/channels/{channel}", response_model=ChannelDetail, responses=_PROBLEMS,
             summary="a channel's config and position, its fields, checks and lock")
    def channel_detail(channel: str):
        return channels.detail(root, channel)

    @api.post("/channels/{channel}/check", response_model=CheckResult, responses=_PROBLEMS,
              summary="the factory's checks of a candidate, nothing written")
    def channel_check(channel: str, edit: ChannelEdit):
        return channels.check(root, channel, edit.model_dump())

    @api.put("/channels/{channel}", response_model=SaveResult, responses=_writing(_PROBLEMS),
             dependencies=writes,
             summary="check -> write -> one commit «Канал <имя>: изменено <поле> (из центра)»")
    def channel_save(channel: str, edit: ChannelEdit):
        return channels.save(root, channel, edit.model_dump())

    @api.get("/channels/{channel}/history", response_model=ChannelHistory, responses=_PROBLEMS,
             summary="the commits of the channel's config and position, newest first")
    def channel_history(channel: str, limit: int = Query(50, ge=1, le=channels.HISTORY_LIMIT)):
        return channels.history(root, channel, limit)

    @api.post("/channels/{channel}/history/{commit}/revert", response_model=SaveResult,
              responses=_writing(_PROBLEMS), dependencies=writes,
              summary="undo one edit by a new commit")
    def channel_revert(channel: str, commit: str,
                       req: Optional[RevertRequest] = Body(None)):
        return channels.revert(root, channel, commit, base=req.base if req else None)

    # ------------------------------------------------ the schedule and the batches (CC-0044)
    @api.get("/schedule", response_model=SchedulePlan, responses=_BPROBLEMS,
             summary="the batch plan of the factory: days, channels, the switch, the timer")
    def schedule_plan(days: int = Query(7, ge=1, le=batches.PLAN_DAYS_MAX)):
        return batches.schedule(root, days)

    @api.post("/schedule/switch", response_model=Switch, responses=_writing(_BPROBLEMS),
              dependencies=writes,
              summary="turn the schedule on (a note required) or off - by the user")
    def schedule_switch(body: SwitchIn):
        return batches.switch(root, body.on, body.note)

    @api.get("/schedule/channels/{channel}", response_model=ChannelSchedule,
             responses=_BPROBLEMS, summary="a channel's schedule settings and their history")
    def schedule_channel(channel: str):
        return batches.channel_schedule(root, channel)

    @api.put("/schedule/channels/{channel}", response_model=SettingsResult,
             responses=_writing(_BPROBLEMS), dependencies=writes, summary="change a channel's schedule settings (the overlay, "
                                           "not git)")
    def schedule_channel_save(channel: str, edit: ScheduleSettingsEdit):
        body = edit.model_dump()
        if "windows" in edit.model_fields_set and edit.windows is None:
            body["windows"] = []                # CC-0152: an explicit null removes the key
        return batches.set_settings(root, channel, body)

    @api.get("/batches/history", response_model=BatchHistory, responses=_BPROBLEMS,
             summary="the runs, newest first, with who launched them")
    def batch_history(channel: Optional[str] = None,
                      limit: int = Query(50, ge=1, le=batches.HISTORY_LIMIT)):
        return batches.history(root, channel, limit)

    @api.get("/batches/stranded", response_model=StrandedBatches, responses=_BPROBLEMS,
             summary="the batches that stopped badly with no runs.jsonl row and not open - "
                     "batch_schedule.stranded_batches (CF-0723) as is, with log_url")
    def batch_stranded(channel: Optional[str] = None,
                       limit: int = Query(batches.STRANDED_LIMIT, ge=1,
                                          le=batches.STRANDED_LIMIT_MAX)):
        return batches.stranded(root, channel, limit, prefix)   # cleaned there: log_url is a URL

    @api.get("/batches", response_model=BatchesGoing, responses=_BPROBLEMS,
             summary="every open batch as the console shows it - stage, elapsed, ceiling, "
                     "estimate; poll every `poll_s`")
    def batches_going():
        return batches.going(root)

    @api.post("/batches/launch/plan", response_model=LaunchPlan, responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="what «запустить» would do: launch_check, and a confirm token when ok - "
                      "nothing started")
    def batch_launch_plan(body: LaunchPlanIn):
        return clean(batches.launch_plan(root, body.channel))

    @api.post("/batches/launch", response_model=LaunchResult, responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="start the batch: the plan's token, the same check, then manual_launch "
                      "(detached; answers at once)")
    def batch_launch(body: LaunchIn):
        return clean(batches.launch(root, body.channel, body.confirm))

    @api.post("/batches/{channel}/{batch_id}/stop/plan", response_model=StopPlan,
              responses=_writing(_BPROBLEMS), dependencies=writes, summary="what «остановить» would do: stop_check, and a "
                                            "confirm token when ok - nothing signalled")
    def batch_stop_plan(channel: str, batch_id: str, body: Optional[StopPlanIn] = Body(None)):
        return clean(batches.stop_plan(root, channel, batch_id, body.also_step if body else False))

    @api.post("/batches/{channel}/{batch_id}/stop", response_model=StopResult,
              responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="stop the batch: the plan's token, the same check, then batch_control.stop "
                      "(SIGTERM, waits <= grace_s; never SIGKILL)")
    def batch_stop(channel: str, batch_id: str, body: StopIn):
        return clean(batches.stop(root, channel, batch_id, body.confirm, body.also_step))

    @api.post("/batches/{channel}/{batch_id}/resume/plan", response_model=ResumePlan,
              responses=_writing(_BPROBLEMS), dependencies=writes, summary="what «продолжить» would do: resume_check, and a "
                                            "confirm token when ok - nothing started")
    def batch_resume_plan(channel: str, batch_id: str):
        return clean(batches.resume_plan(root, channel, batch_id))

    @api.post("/batches/{channel}/{batch_id}/resume", response_model=ResumeResult,
              responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="resume the batch: the plan's token, the same check, then "
                      "batch_control.resume (run_executor --resume, detached)")
    def batch_resume(channel: str, batch_id: str, body: ResumeIn):
        return clean(batches.resume(root, channel, batch_id, body.confirm))

    @api.get("/batches/{channel}/{batch_id}/rerun-from", response_model=RerunFromStages,
             responses=_BPROBLEMS, summary="what «повторить со стадии» can offer: each stage of "
                                           "run-state.json order, its status, can and why "
                                           "(rerun_from_check per stage) - read only")
    def batch_rerun_stages(channel: str, batch_id: str):
        return clean(batches.rerun_stages(root, channel, batch_id))

    @api.post("/batches/{channel}/{batch_id}/rerun-from/plan", response_model=RerunFromPlan,
              responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="what «повторить со стадии» would do: rerun_from_check (CF-0739), and a "
                      "confirm token when ok - nothing written")
    def batch_rerun_plan(channel: str, batch_id: str, body: RerunFromPlanIn):
        return clean(batches.rerun_plan(root, channel, batch_id, body.stage))

    @api.post("/batches/{channel}/{batch_id}/rerun-from", response_model=RerunFromResult,
              responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="rerun the batch from the plan's stage: the token, the same check, then "
                      "batch_control.rerun_from (by user via center; resume: run_executor "
                      "--resume detached right after)")
    def batch_rerun_from(channel: str, batch_id: str, body: RerunFromIn):
        return clean(batches.rerun_from(root, channel, batch_id, body.confirm, body.note,
                                        body.resume))

    @api.get("/batches/{channel}/{batch_id}/rebuild/modes", response_model=RebuildModes,
             responses=_BPROBLEMS, summary="the rebuild modes of the batch's channel (its run "
                                           "plan, as the factory reads it)")
    def batch_rebuild_modes(channel: str, batch_id: str):
        return clean(batches.rebuild_modes(root, channel, batch_id))

    @api.post("/batches/{channel}/{batch_id}/rebuild/plan", response_model=RebuildPlan,
              responses=_writing(_BPROBLEMS), dependencies=writes, summary="what «пересобрать» would do: rebuild_check, and a "
                                            "confirm token when ok - nothing made")
    def batch_rebuild_plan(channel: str, batch_id: str, body: RebuildPlanIn):
        notes = body.notes.model_dump(exclude_none=True) if isinstance(body.notes, BaseModel) \
            else body.notes
        return clean(batches.rebuild_plan(root, channel, batch_id, body.videos, body.mode, notes))

    @api.post("/batches/{channel}/{batch_id}/rebuild", response_model=RebuildResult,
              responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="rebuild the videos: the plan's token (its videos, mode, notes), the same "
                      "check, then batch_control.rebuild (detached; answers at once)")
    def batch_rebuild(channel: str, batch_id: str, body: RebuildIn):
        return clean(batches.rebuild(root, channel, batch_id, body.confirm))

    @api.get("/batches/{channel}/{batch_id}", response_model=BatchDetail, responses=_BPROBLEMS,
             summary="a batch's run-state.json, its processes alive, its channel's questions")
    def batch_detail(channel: str, batch_id: str):
        return batches.detail(root, channel, batch_id)

    @api.get("/batches/{channel}/{batch_id}/events", response_model=BatchEvents,
             responses=_BPROBLEMS,
             summary="RUN_EVENTS.jsonl by byte cursor: `after` = the last `next` (none: the "
                     "tail); whole lines; poll every `poll_s` (3 s), not a stream")
    def batch_events(channel: str, batch_id: str, after: Optional[int] = Query(None, ge=0),
                     limit: int = Query(batches.EVENTS_LIMIT, ge=1, le=batches.EVENTS_LIMIT_MAX)):
        return batches.events(root, channel, batch_id, after, limit)

    @api.get("/batches/{channel}/{batch_id}/stages", response_model=BatchStages,
             responses=_BPROBLEMS, summary="a batch's markers, stages and logs")
    def batch_stages(channel: str, batch_id: str):
        return batches.stages(root, channel, batch_id)

    @api.get("/batches/{channel}/{batch_id}/logs/{name}", response_model=LogTail,
             responses=_BPROBLEMS, summary="the tail of one of the batch's logs/*.log")
    def batch_log(channel: str, batch_id: str, name: str,
                  size: int = Query(batches.TAIL_DEFAULT, ge=1, le=batches.TAIL_MAX, alias="bytes")):
        return batches.log_tail(root, channel, batch_id, name, size)

    @api.get("/batches/{channel}/{batch_id}/summary", response_model=BatchRunSummary,
             responses=_BPROBLEMS, summary="the run's summary: summary.compute (runlog summary "
                                           "--json) and RUN_SUMMARY.md; missing is «ещё нет», "
                                           "not an error")
    def batch_summary(channel: str, batch_id: str):
        return clean(run_summary.summary(root, channel, batch_id))

    @api.get("/batches/{channel}/{batch_id}/footage", response_model=BatchFootage,
             responses=_BPROBLEMS, summary="the Footage Indexer's collection per topic "
                                           "(footage_progress, CF-0715): the progress file, "
                                           "RUN_EVENTS or 01b; kept per state of those files")
    def batch_footage(channel: str, batch_id: str):
        return clean(footage_mod.footage(root, channel, batch_id))

    # ------------------------------------------------ the topics (CC-0091)
    @api.get("/batches/{channel}/{batch_id}/topics", response_model=BatchTopics,
             responses=_BPROBLEMS, summary="what each stage found and decided about the "
                                           "batch's topics so far (01, 02, 01b, 03-06 as "
                                           "written; a stage not done - its block null)")
    def batch_topics(channel: str, batch_id: str):
        return topics.topics(root, channel, batch_id)

    @api.get("/batches/{channel}/{batch_id}/topics/{topic_id}", response_model=BatchTopic,
             responses=_BPROBLEMS, summary="one topic: its scenes, the fact and its source, "
                                           "links, searches - and its summary row")
    def batch_topic(channel: str, batch_id: str, topic_id: str):
        return topics.topic(root, channel, batch_id, topic_id)


    # ------------------------------------------------ the videos (CC-0012)
    @api.get("/batches/{channel}/{batch_id}/videos", response_model=BatchVideos,
             responses=_BPROBLEMS, summary="the batch's videos (05-video-editor.json), their "
                                           "verdicts, cards, files - and its rebuilds beside")
    def batch_videos(channel: str, batch_id: str):
        return videos.videos(root, channel, batch_id, prefix)

    _FILE = {404: {"model": BatchProblem}, 416: {"description": "the range is past the end"}}

    @api.head("/batches/{channel}/{batch_id}/videos/{slug}/mp4", include_in_schema=False)
    @api.get("/batches/{channel}/{batch_id}/videos/{slug}/mp4",
             response_class=FileResponse,
             responses={**_FILE, 200: {"content": {"video/mp4": {}}},
                        206: {"description": "a range", "content": {"video/mp4": {}}}},
             summary="the video, `video/mp4`, with HTTP Range")
    def batch_video_mp4(channel: str, batch_id: str, slug: str):
        return FileResponse(videos.mp4_path(root, channel, batch_id, slug),
                            media_type=videos.MP4_TYPE)

    @api.head("/batches/{channel}/{batch_id}/videos/{slug}/preview", include_in_schema=False)
    @api.get("/batches/{channel}/{batch_id}/videos/{slug}/preview",
             response_class=FileResponse,
             responses={**_FILE, 200: {"content": {"image/jpeg": {}, "image/png": {}}}},
             summary="the preview: the Editor's frame videos/<slug>.jpg (image/jpeg), else "
                     "the frame judge's first contact sheet (image/png)")
    def batch_video_preview(channel: str, batch_id: str, slug: str):
        p, media_type = videos.preview_path(root, channel, batch_id, slug)
        return FileResponse(p, media_type=media_type)

    @api.get("/batches/{channel}/{batch_id}/videos/{slug}/card", response_model=Card,
             responses=_BPROBLEMS, summary="the publication card, parsed (placeable, sections)")
    def batch_video_card(channel: str, batch_id: str, slug: str):
        return videos.card(root, channel, batch_id, slug)

    @api.get("/batches/{channel}/{batch_id}/videos/{slug}/score", response_model=VideoScore,
             responses=_BPROBLEMS, summary="the video's score and why (work/<slug>/"
                                           "plan.score.json, else the 05's block)")
    def batch_video_score(channel: str, batch_id: str, slug: str):
        return videos.score(root, channel, batch_id, slug)

    @api.get("/batches/{channel}/{batch_id}/videos/{slug}/blocks", response_model=VideoBlocks,
             response_model_exclude_unset=True, responses=_BPROBLEMS, summary="which storyboard block each second of the video "
                                           "falls in (blocks_at) - the rebuild's exclusions")
    def batch_video_blocks(channel: str, batch_id: str, slug: str,
                           at: str = Query("", description="seconds of the video, «12,18,24» "
                                                           f"(<= {batches.BLOCKS_AT_MAX}); none "
                                                           "or not seconds: 422 `invalid`")):
        return batches.blocks(root, channel, batch_id, slug, at)

    @api.post("/batches/{channel}/{batch_id}/videos/{slug}/acceptance",
              response_model=AcceptResult, responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="the user's verdict - acceptance.record_and_commit: one commit of "
                      "publish/acceptance-log.json, or queued under an open batch; only by "
                      "the user's press")
    def batch_video_accept(channel: str, batch_id: str, slug: str, body: AcceptIn):
        return videos.accept(root, channel, batch_id, slug, body.verdict, body.words,
                             body.reason, body.reason_code, body.amend)

    @api.post("/batches/{channel}/{batch_id}/videos/{slug}/withdraw/plan",
              response_model=WithdrawPlan, responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="what taking the video off for good would write: pool_release - its "
                      "topic, topic_status, the pool's what-if plan(extra_withdrawn); nothing "
                      "written, nothing deleted")
    def batch_video_withdraw_plan(channel: str, batch_id: str, slug: str):
        return withdrawal.withdraw_plan(root, channel, batch_id, slug)

    @api.post("/batches/{channel}/{batch_id}/videos/{slug}/withdraw",
              response_model=WithdrawResult, responses=_writing(_BPROBLEMS), dependencies=writes,
              summary="take the video off for good on the user's word: a Russian answer naming "
                      "it, the plan's token, the same plan, then pool_release.record_withdrawal")
    def batch_video_withdraw(channel: str, batch_id: str, slug: str, body: WithdrawIn):
        return withdrawal.withdraw(root, channel, batch_id, slug, body.confirm, body.answer)

    # ------------------------------------------------ the publication, read only (CC-0064)
    @api.get("/publish", response_model=PublishOverview, responses=_PPROBLEMS,
             summary="every channel's queue in a line (queue_channels): slot, pause, "
                     "tomorrow, next free, the waiting ones")
    def publish_overview():
        return publish.queues(root)

    @api.get("/publish/holds", response_model=PublicationHolds, responses=_PPROBLEMS,
             summary="publication holds (publication_hold.open_holds, read_ledger)")
    def publish_holds(channel: Optional[str] = Query(None, description="one channel")):
        return publish.holds(root, channel)

    @api.get("/publish/holds/released", response_model=ReleasedHolds, responses=_PPROBLEMS,
             summary="the holds lifted - or lifted by the scene rule and put back - lately "
                     "(publication_hold.read_ledger: resolved_at, resolved_reason_code, "
                     "scene_release, scene_release_reopened; CF-0846)")
    def publish_holds_released(
            channel: Optional[str] = Query(None, description="one channel"),
            days: int = Query(publish.RELEASED_DAYS, ge=1, le=publish.RELEASED_DAYS_MAX,
                              description="days back from now"),
            limit: int = Query(publish.RELEASED_LIMIT, ge=1, le=publish.RELEASED_LIMIT_MAX,
                               description="rows at most, newest first")):
        return publish.released_holds(root, channel, days, limit)

    @api.get("/publish/api-upload", response_model=ApiUpload, responses=_PPROBLEMS,
             summary="the API-upload switch of every channel and what enabling warns of "
                     "(api_switch.status, warnings)")
    def publish_api_upload():
        return publish.api_upload(root)

    @api.get("/publish/{channel}/queue", response_model=ChannelQueue, responses=_PPROBLEMS,
             summary="the channel's queue (publish_queue show / next / tomorrow)")
    def publish_queue(channel: str, days: int = Query(publish.DAYS_DEFAULT, ge=1, le=publish.DAYS_MAX,
                                                      description="days of slots from today")):
        return publish.queue(root, channel, days)

    @api.get("/publish/{channel}/pause", response_model=ChannelPause, responses=_PPROBLEMS,
             summary="the channel's pause (channel_pause.status, open_row, history)")
    def publish_pause(channel: str):
        return publish.pause(root, channel)

    @api.get("/publish/{channel}/api-upload", response_model=ApiUpload, responses=_PPROBLEMS,
             summary="the channel's API-upload switch (api_switch.channel_state, warnings)")
    def publish_channel_api_upload(channel: str):
        return publish.api_upload(root, channel)

    @api.get("/publish/{channel}/rotation", response_model=ChannelRotation,
             responses=_PPROBLEMS, summary="the rotation (rotate.distribution_report with "
                                           "awaiting_material)")
    def publish_rotation(channel: str):
        return publish.rotation(root, channel)

    @api.get("/publish/{channel}/config", response_model=PublisherBlock, responses=_PPROBLEMS,
             summary="the channel's publisher block (publish_card.channel_config)")
    def publish_config(channel: str):
        return publish.config(root, channel)

    @api.get("/publish/{channel}/studio", response_model=ChannelStudio, responses=_PPROBLEMS,
             summary="the Studio streak (studio_fields.streak over publish/uploads.json)")
    def publish_studio(channel: str):
        return publish.studio(root, channel)

    @api.get("/publish/{channel}/notes/{slug}", response_model=PublishNote,
             responses=_PPROBLEMS, summary="a placed card: the short view (publish_card.view), "
                                           "the form, the Studio fields (studio_fields.prepare)")
    def publish_note(channel: str, slug: str,
                     day: Optional[str] = Query(None, description="YYYY-MM-DD, _queue or "
                                                                  "_reserve - the folder of the "
                                                                  "note, which of two notes of "
                                                                  "one name; none: the one place "
                                                                  "of the name not in the upload "
                                                                  "journal (two or more: 404 "
                                                                  "unknown_note naming the "
                                                                  "day, CF-0857)"),
                     batch_id: Optional[str] = Query(None, description="CC-0182 (CF-0920): which "
                                                                       "of two videos of one "
                                                                       "name - the `batch_id` of "
                                                                       "its row in the stash; "
                                                                       "none with two in one "
                                                                       "folder: 409 `namesakes` "
                                                                       "naming the batches")):
        return publish.note(root, channel, slug, day, prefix, batch_id)

    # ------------------------------------------------ the statistics, read only (CC-0020)
    @api.get("/analytics", response_model=AnalyticsOverview, responses=_APROBLEMS,
             summary="the journal's channels, each with its last collection run and the days "
                     "a summary was written for")
    def analytics_overview():
        return analytics.overview(root)

    @api.get("/analytics/diversity", response_model=FeedDiversity, responses=_APROBLEMS,
             summary="the share of each fact kind, pattern, rhythm and hook opener over the "
                     "last N accepted videos (runlog diversity), nothing written")
    def analytics_diversity(last: int = Query(analytics.DIVERSITY_LAST, ge=0, le=10000,
                                              description="the last N accepted videos; "
                                                          "0 - the whole feed"),
                            channel: Optional[str] = Query(
                                None, description="CC-0119 (CF-0719): only this channel's "
                                                  "feed (a former id resolved); none - every "
                                                  "channel")):
        return clean(analytics.diversity(root, last, channel or None))

    # ------------------------------------------------ the gates' price, read only (CC-0100)
    @api.get("/gate-prices", response_model=GatePrices, responses=_GPROBLEMS,
             summary="what each refusal would have cost in ready videos over the last batches "
                     "(runlog gate-price --json), the signatures and decisions as read - "
                     "nothing written")
    def gate_price_read(rule: Optional[List[str]] = Query(None, description="a registered "
                                                                             "rule; repeatable; "
                                                                             "default every one"),
                        window: int = Query(gate_prices.WINDOW, ge=1,
                                            le=gate_prices.WINDOW_MAX,
                                            description="the last N batches"),
                        before: Optional[str] = Query(None, description="the window as it "
                                                                        "stood before this day "
                                                                        "(YYYY-MM-DD) or batch "
                                                                        "id")):
        return clean(gate_prices.prices(root, rule, window, before))

    # ------------------------------------------------ the gates' signature (CC-0114, CF-0721)
    gw = _writing(_GWPROBLEMS)

    @api.post("/gate-prices/{rule}/sign/plan", response_model=GateWritePlan, responses=gw,
              dependencies=writes,
              summary="what signing the rule's price would write: gate_price.sign dry run "
                      "(by user via center), a confirm token when ok - nothing written")
    def gate_price_sign_plan(rule: str, body: GateSignPlanIn):
        return gate_prices.plan(root, "sign", rule, {"price": body.price, "note": body.note},
                                body.base_sha256)

    @api.post("/gate-prices/{rule}/sign", response_model=GateWriteResult, responses=gw,
              dependencies=writes,
              summary="sign the rule's price: the plan's token, then gate_price.sign with the "
                      "plan's base_sha256 - the factory commits shared/gate-prices.json")
    def gate_price_sign(rule: str, body: ConfirmIn):
        return gate_prices.confirm(root, "sign", rule, body.confirm)

    @api.post("/gate-prices/{rule}/decide/plan", response_model=GateWritePlan, responses=gw,
              dependencies=writes,
              summary="what deciding the rule's mode would write: gate_price.decide dry run "
                      "(by user via center), a confirm token when ok - nothing written")
    def gate_price_decide_plan(rule: str, body: GateDecidePlanIn):
        return gate_prices.plan(root, "decide", rule,
                                {"mode": body.mode, "task": body.task, "note": body.note},
                                body.base_sha256)

    @api.post("/gate-prices/{rule}/decide", response_model=GateWriteResult, responses=gw,
              dependencies=writes,
              summary="record the decision: the plan's token, then gate_price.decide with the "
                      "plan's base_sha256 - the factory commits shared/gate-prices.json")
    def gate_price_decide(rule: str, body: ConfirmIn):
        return gate_prices.confirm(root, "decide", rule, body.confirm)

    @api.get("/analytics/{channel}/metrics", response_model=ChannelMetrics,
             responses=_APROBLEMS, summary="every stored video with YouTube's window of the "
                                           "first N days (metrics.py show), its last daily "
                                           "row and Studio read")
    def analytics_metrics(channel: str,
                          first_days: int = Query(analytics.FIRST_DAYS_DEFAULT, ge=1,
                                                  description="the window: first N days")):
        return analytics.metrics(root, channel, first_days)

    @api.get("/analytics/{channel}/videos/{video_id}", response_model=VideoSeries,
             responses=_APROBLEMS, summary="one video's daily rows, windows and Studio reads")
    def analytics_video(channel: str, video_id: str):
        return analytics.video(root, channel, video_id)

    @api.get("/analytics/{channel}/summary", response_model=AnalystSummary,
             responses=_APROBLEMS, summary="the analyst's summary by style (summary.build), "
                                           "nothing written")
    def analytics_summary(channel: str,
                          day: Optional[str] = Query(None, description="YYYY-MM-DD; none: "
                                                                       "yesterday, Pacific"),
                          first_days: int = Query(analytics.FIRST_DAYS_DEFAULT, ge=1,
                                                  description="the window: first N days")):
        return analytics.summary(root, channel, day, first_days)

    @api.get("/analytics/{channel}/summary/{day}", response_model=AnalystSummary,
             responses=_APROBLEMS, summary="the summary written for a day "
                                           "(analytics/<ch>/summary/<day>.json)")
    def analytics_saved_summary(channel: str, day: str):
        return analytics.saved_summary(root, channel, day)

    @api.get("/analytics/{channel}/footage-wanted", response_model=FootageWanted,
             responses=_APROBLEMS, summary="the footage the scripts asked for and did not get "
                                           "(footage_wanted.build), nothing written")
    def analytics_footage(channel: str,
                          since: Optional[str] = Query(None, description="only batches from "
                                                                         "this day (YYYY-MM-DD)"),
                          packed: bool = Query(False, description="also the packed batches "
                                                                  "(the archive volume)")):
        return analytics.footage(root, channel, since, packed)

    @api.get("/analytics/{channel}/studio", response_model=AnalyticsStudio,
             responses=_APROBLEMS, summary="what to read in Studio and what was read "
                                           "(studio_read plan / due, studio.jsonl)")
    def analytics_studio(channel: str):
        return analytics.studio(root, channel)

    @api.post("/analytics/{channel}/studio/record/plan", response_model=StudioReadRecordPlan,
              responses=_writing(_SWPROBLEMS), dependencies=writes,
              summary="what entering the Studio read would write (parse_read), a confirm "
                      "token - nothing written")
    def analytics_studio_record_plan(channel: str, body: StudioReadRecordPlanIn):
        return studio_entry.record_plan(root, channel, body.read)

    @api.post("/analytics/{channel}/studio/record", response_model=StudioReadRecordResult,
              responses=_writing(_SWPROBLEMS), dependencies=writes,
              summary="enter the Studio read: the plan's token, the same parse and store, "
                      "then record(by user, via center)")
    def analytics_studio_record(channel: str, body: ConfirmIn):
        return studio_entry.record(root, channel, body.confirm)

    # ------------------------------------------------ the Studio read from the center (CC-0120)
    @api.get("/studio/due", response_model=StudioReadDue, responses=_writing(_SCPROBLEMS),
             summary="is a Studio read due (studio_center.studio_read_due, CF-0735) - for a "
                     "channel or the factory, by hook; center-first-open-of-day records the "
                     "open (the factory's state file), so it needs the working factory")
    def studio_due(request: Request,
                   channel: Optional[str] = Query(None, description="one channel; none: all"),
                   hook: Optional[str] = Query(None, description="batch-start | upload | "
                                                                 "center-first-open-of-day; "
                                                                 "none: the daily insurance")):
        if hook == "center-first-open-of-day":
            require_writes(request)
        return studio_center.due(root, channel, hook)

    @api.post("/studio/read/plan", response_model=StudioReadPlan,
              responses=_writing(_SCWPROBLEMS), dependencies=writes,
              summary="what «Прочитать Studio» would start (studio_read_launch by user via "
                      "center, not confirmed) - nothing started; a token only when the "
                      "switch is on")
    def studio_read_plan():
        return studio_center.read_plan(root)

    @api.post("/studio/read", response_model=StudioReadStarted,
              responses=_writing(_SCWPROBLEMS), dependencies=writes,
              summary="start the Studio read: the switch, the plan's token, the same plan, "
                      "then studio_read_launch(confirmed) in a child - run id, pid, log")
    def studio_read_start(body: ConfirmIn):
        return studio_center.read(root, body.confirm)

    @api.get("/studio/read/{run_id}", response_model=StudioReadResult,
             responses=_SCRPROBLEMS,
             summary="what the reading session came to (studio_read_result): read / "
                     "no_extension / login_needed / error / running")
    def studio_read_outcome(run_id: str):
        return studio_center.result(root, run_id)

    # ------------------------------------------------ a channel's lists, read only (CC-0022)
    @api.get("/channels/{channel}/rights-holders", response_model=ChannelRightsHolders,
             responses=_RPROBLEMS, summary="the channel's rights-holder list "
                                           "(channel_data.rights_holders)")
    def channel_rights_holders(channel: str):
        return rights.rights_holders(root, channel)

    @api.get("/channels/{channel}/footage-origin", response_model=ChannelFootageOrigin,
             responses=_RPROBLEMS, summary="the channel's footage origins "
                                           "(channel_data.footage_origin) and their errors")
    def channel_footage_origin(channel: str):
        return rights.footage_origin(root, channel)

    @api.get("/channels/{channel}/ending", response_model=ChannelEnding,
             responses=_ENPROBLEMS,
             summary="the channel's ending clip (end_card: ending_path, ending_seconds, "
                     "probe_ending, check_ending), its data (brand.json ending) and whether "
                     "brand_ending.py can render it (render_plan) - read only")
    def channel_ending(channel: str):
        return ending.view(root, channel)

    @api.post("/channels/{channel}/ending/plan", response_model=EndingRenderPlan,
              responses=_writing(_ENWPROBLEMS), dependencies=writes,
              summary="what «отрендерить концовку» would do: brand_ending.render_plan afresh, "
                      "the channel's open batches, a confirm token when nothing refuses - "
                      "nothing rendered (CC-0114)")
    def channel_ending_plan(channel: str):
        return ending.render_plan(root, channel)

    @api.post("/channels/{channel}/ending", response_model=EndingRenderResult,
              responses=_writing(_ENWPROBLEMS), dependencies=writes,
              summary="render the ending: the plan's token, the same plan and guards, then "
                      "brand_ending.py started detached - its pid and log at once (CC-0114)")
    def channel_ending_render(channel: str, body: ConfirmIn):
        return ending.render(root, channel, body.confirm)

    # ------------------------------------------------ the publication writes (CC-0065)
    pw = _writing(_PWPROBLEMS)

    @api.post("/publish/{channel}/pause/set/plan", response_model=PausePlan, responses=pw,
              dependencies=writes, summary="what «пауза» would write (channel_pause.status), "
                                           "a confirm token when ok - nothing written")
    def publish_pause_set_plan(channel: str, body: PauseSetPlanIn):
        return publish.pause_set_plan(root, channel, body.reason, body.until, body.replace)

    @api.post("/publish/{channel}/pause/set", response_model=PauseWriteResult, responses=pw,
              dependencies=writes, summary="pause the channel: the plan's token, the same "
                                           "check, then channel_pause.set_pause")
    def publish_pause_set(channel: str, body: ConfirmIn):
        return publish.pause_set(root, channel, body.confirm)

    @api.post("/publish/{channel}/pause/clear/plan", response_model=PausePlan, responses=pw,
              dependencies=writes, summary="what «снять паузу» would do - nothing written")
    def publish_pause_clear_plan(channel: str, body: Optional[PauseClearPlanIn] = Body(None)):
        return publish.pause_clear_plan(root, channel, body.note if body else None)

    @api.post("/publish/{channel}/pause/clear", response_model=PauseWriteResult, responses=pw,
              dependencies=writes, summary="lift the pause: the plan's token, the same check, "
                                           "then channel_pause.clear_pause (the row stays)")
    def publish_pause_clear(channel: str, body: ConfirmIn):
        return publish.pause_clear(root, channel, body.confirm)

    @api.post("/publish/{channel}/card/place/plan", response_model=CardPlacePlan, responses=pw,
              dependencies=writes, summary="what «выложить карточку» would do (placeable, "
                                           "the entry, plan_slot) - nothing written")
    def publish_card_place_plan(channel: str, body: CardPlacePlanIn):
        return publish.card_place_plan(root, channel, body.batch_id, body.slug, body.day,
                                       body.replace, body.dir)

    @api.post("/publish/{channel}/card/place", response_model=CardPlaceResult, responses=pw,
              dependencies=writes, summary="place the card: the plan's token, the same check, "
                                           "then publish_card.place")
    def publish_card_place(channel: str, body: ConfirmIn):
        return publish.card_place(root, channel, body.confirm)

    # ------------------------------------------------ the копилка (CC-0122)
    @api.get("/publish/{channel}/stash", response_model=PublishStash,
             responses={s: {"model": StashProblem} for s in (404, 500)},
             summary="the channel's копилка: the accepted videos waiting in _queue/ and "
                     "_reserve/ with no slot, their details and age (publish_stash.stash, "
                     "CF-0738)")
    def publish_stash_read(channel: str):
        return stash_mod.stash(root, channel, prefix)

    @api.post("/publish/{channel}/stash/place/plan", response_model=StashPlacePlan,
              responses=_writing(_SPROBLEMS), dependencies=writes,
              summary="what placing the named videos - or, with `auto`, the factory's own "
                      "choice (CF-0918) - onto the nearest free slots would do "
                      "(publish_stash.place_plan) - nothing written; a token when all place")
    def publish_stash_place_plan(channel: str, body: StashPlaceIn):
        return stash_mod.place_plan(root, channel, body.order, body.auto, body.force)

    @api.post("/publish/{channel}/stash/place", response_model=StashPlaceResult,
              responses=_writing(_SPROBLEMS), dependencies=writes,
              summary="place them: the plan's token, the same plan, place_confirm by user via "
                      "center, then one commit of exactly the files it touched")
    def publish_stash_place(channel: str, body: ConfirmIn):
        return stash_mod.place(root, channel, body.confirm)

    @api.post("/publish/{channel}/stash/repair/plan", response_model=StashRepairPlan,
              responses=_writing(_SPROBLEMS), dependencies=writes,
              summary="what putting the channel's accepted videos with no place into _queue/ "
                      "would do (acceptance.repair_queue dry run)")
    def publish_stash_repair_plan(channel: str, body: Optional[StashRepairIn] = Body(None)):
        return stash_mod.repair_plan(root, channel, body.entries if body else None)

    @api.post("/publish/{channel}/stash/repair", response_model=StashRepairResult,
              responses=_writing(_SPROBLEMS), dependencies=writes,
              summary="put them in: the plan's token, the same dry run, then repair_queue by "
                      "user via center (the factory commits the record)")
    def publish_stash_repair(channel: str, body: ConfirmIn):
        return stash_mod.repair(root, channel, body.confirm)

    # ------------------------------------------------ moving a placed video (CC-0165)
    @api.post("/publish/{channel}/move/plan", response_model=MovePlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what moving placed videos to other days, taking ones not in Studio "
                      "back into the копилка and taking ones in Studio off the feed into its "
                      "reserve would do (publish_move.move_plan, CF-0856, CF-0918) - nothing "
                      "written; a token when every edit is ok")
    def publish_move_plan(channel: str, body: MovePlanIn):
        return move_mod.move_plan(root, channel, [m.model_dump() for m in body.moves],
                                  body.unplace, body.withdraw)

    @api.post("/publish/{channel}/move/confirm", response_model=MoveResult,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="move them: the plan's token, the same plan, move_confirm by user via "
                      "center with the plan's base_sha256 - all or nothing, the factory's one "
                      "commit")
    def publish_move_confirm(channel: str, body: MoveConfirmIn):
        return move_mod.move(root, channel, body.confirm, body.base_sha256)

    # ------------------------------------------------ the card from the center (CC-0127)
    @api.get("/publish/{channel}/cards/build/{run_id}", response_model=CardBuildOutcome,
             responses={s: {"model": CardCenterProblem} for s in (404, 422, 500)},
             summary="what a card build came to (card_center.card_build_result) - ready / "
                     "not_ready / refused / not_asked / error / running, poll_s while it runs")
    def publish_card_build_result(channel: str, run_id: str):
        return card_mod.result(root, channel, run_id)

    @api.get("/publish/{channel}/cards/{slug}", response_model=CardInfo,
             responses={s: {"model": CardCenterProblem} for s in (404, 409, 422, 500)},
             summary="the card of one video: none / building / ready / ruled / not_ready, "
                     "placeable, why, reasons, the ruling, the last build (card_center.card_info)")
    def publish_card_info(channel: str, slug: str,
                          batch_id: Optional[str] = Query(None, description="the video's batch; "
                                                                            "none: the latest "
                                                                            "accepted of the "
                                                                            "name, CC-0182: two "
                                                                            "of them waiting - "
                                                                            "409 `namesakes`")):
        return card_mod.info(root, channel, slug, batch_id)

    @api.post("/publish/{channel}/cards/{slug}/build/plan", response_model=CardBuildLaunchPlan,
              responses=_writing(_CPROBLEMS), dependencies=writes,
              summary="what «Собрать заново» would start (card_info, validate_draft) - nothing "
                      "started; a token when nothing refuses")
    def publish_card_rebuild_plan(channel: str, slug: str,
                                  body: Optional[CardBuildLaunchPlanIn] = Body(None)):
        return card_mod.build_plan(root, channel, slug, body.batch_id if body else None,
                                   body.draft if body else None, prefix)

    @api.post("/publish/{channel}/cards/{slug}/build", response_model=CardBuildStarted,
              responses=_writing(_CPROBLEMS), dependencies=writes,
              summary="start it: the plan's token, the same plan, then card_build_launch by "
                      "user via center - detached, with its log")
    def publish_card_rebuild(channel: str, slug: str, body: ConfirmIn):
        return card_mod.build(root, channel, slug, body.confirm, prefix)

    @api.post("/publish/{channel}/cards/{slug}/ruling/plan", response_model=CardRulingPlan,
              responses=_writing(_CPROBLEMS), dependencies=writes,
              summary="what the user's ruling on a card not ready only for the video's own "
                      "claims would write (card_center.ruling_plan + not_repo / dirty)")
    def publish_card_ruling_plan(channel: str, slug: str, body: CardRulingPlanIn):
        return card_mod.ruling_plan(root, channel, slug, body.batch_id, body.words)

    @api.post("/publish/{channel}/cards/{slug}/ruling", response_model=CardRulingResult,
              responses=_writing(_CPROBLEMS), dependencies=writes,
              summary="write it: the plan's token, the same plan, ruling_confirm with the "
                      "plan's sha256 by user via center, then one commit of exactly `touched`")
    def publish_card_ruling(channel: str, slug: str, body: ConfirmIn):
        return card_mod.ruling(root, channel, slug, body.confirm)

    @api.post("/publish/{channel}/card/build/plan", response_model=CardBuildPlan, responses=pw,
              dependencies=writes, summary="what «собрать карточку» would do from the given "
                                           "draft, claims=False; a model draft refused")
    def publish_card_build_plan(channel: str, body: CardBuildPlanIn):
        return publish.card_build_plan(root, channel, body.batch_id, body.slug, body.draft,
                                       body.model, body.dir)

    @api.post("/publish/{channel}/card/build", response_model=CardBuildResult, responses=pw,
              dependencies=writes, summary="build the card: the plan's token, the same check, "
                                           "then publish_card.build(draft, claims=False)")
    def publish_card_build(channel: str, body: ConfirmIn):
        return publish.card_build(root, channel, body.confirm)

    @api.post("/publish/{channel}/rotation/assign/plan", response_model=RotationPlan,
              responses=pw, dependencies=writes,
              summary="what «назначить пары» would do - nothing written")
    def publish_rotation_assign_plan(channel: str, body: RotationAssignPlanIn):
        return publish.rotation_assign_plan(root, channel, body.batch_id, body.script_ids,
                                            body.despite_shortage)

    @api.post("/publish/{channel}/rotation/assign", response_model=RotationResult,
              responses=pw, dependencies=writes,
              summary="assign: the plan's token, the same check, then rotate.assign")
    def publish_rotation_assign(channel: str, body: ConfirmIn):
        return publish.rotation_assign(root, channel, body.confirm)

    @api.post("/publish/{channel}/rotation/reject/plan", response_model=RotationPlan,
              responses=pw, dependencies=writes,
              summary="the ruling on a rejection (rotate.rule_on_rejection) - nothing written")
    def publish_rotation_reject_plan(channel: str, body: RotationRejectPlanIn):
        return publish.rotation_reject_plan(root, channel, body.script_id, body.reason,
                                            body.rejects_rhythm, body.batch_id)

    @api.post("/publish/{channel}/rotation/reject", response_model=RotationResult,
              responses=pw, dependencies=writes,
              summary="reject: the plan's token, the same ruling, then rotate.reject")
    def publish_rotation_reject(channel: str, body: ConfirmIn):
        return publish.rotation_reject(root, channel, body.confirm)

    @api.post("/publish/{channel}/rotation/refuse/plan", response_model=RotationPlan,
              responses=pw, dependencies=writes,
              summary="what a refusal for want of material would write - nothing written")
    def publish_rotation_refuse_plan(channel: str, body: RotationRefusePlanIn):
        return publish.rotation_refuse_plan(root, channel, body.script_id, body.reason,
                                            body.deficit, body.batch_id)

    @api.post("/publish/{channel}/rotation/refuse", response_model=RotationResult,
              responses=pw, dependencies=writes,
              summary="refuse: the plan's token, the same check, then rotate.refuse")
    def publish_rotation_refuse(channel: str, body: ConfirmIn):
        return publish.rotation_refuse(root, channel, body.confirm)

    # ------------------------------------------------ the hold's signature (CC-0070)
    @api.post("/publish/{channel}/holds/{batch_id}/{topic_id}/sign/plan",
              response_model=HoldSignPlan, responses=pw, dependencies=writes,
              summary="what signing the hold would write (publication_hold.check_sign): the "
                      "hold, what compliance-checker recorded, a confirm token - nothing "
                      "written")
    def publish_hold_sign_plan(channel: str, batch_id: str, topic_id: str,
                               body: HoldSignPlanIn):
        return publish.hold_sign_plan(root, channel, batch_id, topic_id, body.note)

    @api.post("/publish/{channel}/holds/{batch_id}/{topic_id}/sign",
              response_model=HoldSignResult, responses=pw, dependencies=writes,
              summary="sign the hold: the plan's token, check_sign again, then "
                      "publication_hold.sign_hold(user, note, via=center)")
    def publish_hold_sign(channel: str, batch_id: str, topic_id: str, body: ConfirmIn):
        return publish.hold_sign(root, channel, batch_id, topic_id, body.confirm)

    # ------------------------------------------------ the switch, the upload (CC-0066)
    @api.post("/publish/{channel}/api-upload/switch/plan", response_model=SwitchPlan,
              responses=pw, dependencies=writes,
              summary="what turning the API upload on / off would write (api_switch."
                      "channel_state, warnings) - nothing written")
    def publish_api_upload_switch_plan(channel: str, body: SwitchPlanIn):
        return publish_net.api_upload_switch_plan(root, channel, body.on, body.note)

    @api.post("/publish/{channel}/api-upload/switch", response_model=SwitchResult,
              responses=pw, dependencies=writes,
              summary="turn the API upload on / off: the plan's token (on: and «аудит "
                      "подтверждаю»), the same check, then api_switch.set_switch")
    def publish_api_upload_switch(channel: str, body: SwitchConfirmIn):
        return publish_net.api_upload_switch(root, channel, body.confirm, body.audit)

    @api.post("/publish/{channel}/upload/plan", response_model=UploadPlan, responses=pw,
              dependencies=writes,
              summary="what uploading through the API would do: api_switch.check, then "
                      "upload.run(dry_run=True) - nothing written, nothing sent")
    def publish_upload_plan(channel: str, body: UploadPlanIn):
        return publish_net.api_upload_plan(root, channel, body.slug, body.day, body.entry,
                                            body.batch_id)

    @api.post("/publish/{channel}/upload", response_model=UploadResult, responses=pw,
              dependencies=writes,
              summary="upload through the YouTube Data API: the user's «да», the plan's token, "
                      "the same check, then upload.run - goes to Google")
    def publish_upload(channel: str, body: UploadConfirmIn):
        return publish_net.api_upload(root, channel, body.confirm, body.answer)

    @api.post("/publish/{channel}/studio/record/plan", response_model=StudioRecordPlan,
              responses=pw, dependencies=writes,
              summary="what recording a Studio upload would write: studio_fields.verify, then "
                      "record(dry_run=True) - nothing written")
    def publish_studio_record_plan(channel: str, body: StudioRecordPlanIn):
        return publish_net.studio_record_plan(root, channel, body.slug, body.video_id, body.read,
                                              body.day, body.replaces, body.batch_id)

    @api.post("/publish/{channel}/studio/record", response_model=StudioRecordResult,
              responses=pw, dependencies=writes,
              summary="record the Studio upload: the plan's token, the same check, then "
                      "studio_fields.record (the journal row, the ledger's columns)")
    def publish_studio_record(channel: str, body: ConfirmIn):
        return publish_net.studio_record(root, channel, body.confirm)

    # ------------------------------------------------ the hand edit (CC-0106)
    @api.post("/publish/{channel}/studio/edited/plan", response_model=StudioEditedPlan,
              responses=pw, dependencies=writes,
              summary="what marking a hand edit of a Studio video would write: upload_records."
                      "mark_user_edited on a copy of the journal - nothing written")
    def publish_studio_edited_plan(channel: str, body: StudioEditedPlanIn):
        return publish_net.studio_edited_plan(root, channel, body.video_id, body.slug, body.note)

    @api.get("/channels/{channel}/fact-sources", response_model=ChannelFactSources,
             responses=_RPROBLEMS, summary="the channel's fact outlets (channel_data."
                                           "fact_sources), its kinds, the factory's checks "
                                           "and the file's sha256")
    def channel_fact_sources(channel: str):
        return rights.fact_sources(root, channel)

    @api.get("/channels/{channel}/affiliate", response_model=ChannelAffiliate,
             responses=_RPROBLEMS, summary="the channel's affiliate slot: the config's block, "
                                           "the table beside it, affiliate.channel_errors, "
                                           "the table's sha256")
    def channel_affiliate(channel: str):
        return rights.affiliate(root, channel)

    # ------------------------------------------------ the channel lists' writes (CC-0114)
    clw = _writing(_CLPROBLEMS)

    @api.post("/channels/{channel}/fact-sources/plan", response_model=ChannelListPlan,
              responses=clw, dependencies=writes,
              summary="what writing fact-sources.json would do: write_fact_sources dry run "
                      "(by user via center), a confirm token when it would write")
    def channel_fact_sources_plan(channel: str, body: ChannelListDocIn):
        return channel_lists.plan(root, channel, "fact-sources", body.doc, body.base_sha256)

    @api.post("/channels/{channel}/fact-sources", response_model=ChannelListWriteResult,
              responses=clw, dependencies=writes,
              summary="write fact-sources.json: the plan's token, then write_fact_sources "
                      "with the plan's base_sha256, one commit")
    def channel_fact_sources_write(channel: str, body: ConfirmIn):
        return channel_lists.write(root, channel, "fact-sources", body.confirm)

    @api.post("/channels/{channel}/footage-origin/plan", response_model=ChannelListPlan,
              responses=clw, dependencies=writes,
              summary="what writing footage-origin.json would do: write_footage_origin dry run "
                      "(by user via center), a confirm token when it would write")
    def channel_footage_origin_plan(channel: str, body: ChannelListDocIn):
        return channel_lists.plan(root, channel, "footage-origin", body.doc, body.base_sha256)

    @api.post("/channels/{channel}/footage-origin", response_model=ChannelListWriteResult,
              responses=clw, dependencies=writes,
              summary="write footage-origin.json: the plan's token, then write_footage_origin "
                      "with the plan's base_sha256, one commit")
    def channel_footage_origin_write(channel: str, body: ConfirmIn):
        return channel_lists.write(root, channel, "footage-origin", body.confirm)

    @api.post("/channels/{channel}/affiliate/plan", response_model=ChannelListPlan,
              responses=clw, dependencies=writes,
              summary="what writing affiliate.json would do: affiliate.write_table dry run "
                      "(by user via center), a confirm token when it would write")
    def channel_affiliate_plan(channel: str, body: ChannelListDocIn):
        return channel_lists.plan(root, channel, "affiliate", body.doc, body.base_sha256)

    @api.post("/channels/{channel}/affiliate", response_model=ChannelListWriteResult,
              responses=clw, dependencies=writes,
              summary="write affiliate.json: the plan's token, then affiliate.write_table with "
                      "the plan's base_sha256, one commit")
    def channel_affiliate_write(channel: str, body: ConfirmIn):
        return channel_lists.write(root, channel, "affiliate", body.confirm)

    @api.post("/publish/{channel}/studio/edited", response_model=StudioEditedResult,
              responses=pw, dependencies=writes,
              summary="mark the hand edit: the plan's token, the same dry run, then "
                      "upload_records.mark_user_edited (user_edited true)")
    def publish_studio_edited(channel: str, body: ConfirmIn):
        return publish_net.studio_edited(root, channel, body.confirm)

    @api.post("/publish/{channel}/studio/edited/undo/plan", response_model=StudioEditedPlan,
              responses=pw, dependencies=writes,
              summary="what taking the hand-edit mark off would write: mark_user_edited("
                      "edited=False) on a copy of the journal - nothing written")
    def publish_studio_edited_undo_plan(channel: str, body: StudioEditedPlanIn):
        return publish_net.studio_edited_undo_plan(root, channel, body.video_id, body.slug,
                                                   body.note)

    @api.post("/publish/{channel}/studio/edited/undo", response_model=StudioEditedResult,
              responses=pw, dependencies=writes,
              summary="take the mark off: the plan's token, the same dry run, then "
                      "mark_user_edited(edited=False)")
    def publish_studio_edited_undo(channel: str, body: ConfirmIn):
        return publish_net.studio_edited_undo(root, channel, body.confirm)

    # ------------------------------------------------ the meme desk (CC-0024)
    @api.get("/memes", response_model=MemesOverview, responses=_MPROBLEMS,
             summary="every channel with its meme bank and the desk's counts (desk_state)")
    def memes_overview():
        return memes.overview(root)

    @api.get("/memes/{channel}", response_model=MemeDesk, responses=_MPROBLEMS,
             summary="the channel's meme desk: desk_state, the draft's fingerprint, the media "
                     "routes - nothing written")
    def memes_state(channel: str):
        return memes.state(root, channel, prefix)

    @api.get("/memes/{channel}/candidates", response_model=MemeCandidates,
             response_model_by_alias=True, responses=_MPROBLEMS,
             summary="the bank's candidates.json - the templates waiting on the user's yes, "
                     "checked by candidate_problems, each with its candidates_state status; "
                     "accept - whether the yes is open and the list's fingerprint")
    def memes_candidates(channel: str):
        return memes.candidates(root, channel, prefix)

    @api.post("/memes/{channel}/candidates/accept/plan", response_model=MemeAcceptPlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what the yes would take into the bank (plan_accept, by user via center), "
                      "a confirm token when someone would be accepted - nothing written")
    def memes_accept_plan(channel: str, body: Optional[MemeAcceptPlanIn] = Body(None)):
        details = ({k: v.model_dump() for k, v in body.details.items()}
                   if body and body.details is not None else None)
        return memes.accept_plan(root, channel, body.ids if body else None, details)

    @api.post("/memes/{channel}/candidates/accept", response_model=MemeAcceptResult,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="the yes: the user's typed answer (check_accept_answer), the plan's "
                      "token, then accept_candidates with the plan's fingerprint")
    def memes_accept(channel: str, body: MemeAcceptIn):
        return memes.accept(root, channel, body.confirm, body.answer)

    _MFILE = {404: {"model": MemesProblem}, 409: {"model": MemesProblem},
              416: {"description": "the range is past the end"}}

    @api.head("/memes/{channel}/{meme_id}/media", include_in_schema=False)
    @api.get("/memes/{channel}/{meme_id}/media", response_class=FileResponse,
             responses={**_MFILE, 200: {"content": {"image/*": {}}},
                        206: {"description": "a range", "content": {"image/*": {}}}},
             summary="the entry's file (kind=file) or its cut-out (kind=cut), inside its "
                     "bank, with HTTP Range")
    def memes_media(channel: str, meme_id: str,
                    kind: Literal["file", "cut"] = Query("file", description="file: the "
                                                         "entry's file; cut: its cut-out")):
        return FileResponse(memes.media_path(root, channel, meme_id, kind))

    @api.head("/memes/{channel}/{meme_id}/thumb", include_in_schema=False)
    @api.get("/memes/{channel}/{meme_id}/thumb", response_class=FileResponse,
             responses={**_MFILE, 500: {"model": MemesProblem},
                        200: {"content": {"image/jpeg": {}, "image/gif": {}}}},
             summary="the card's picture: thumb() - a still's cached JPEG (made when missing "
                     "or older than the source), a GIF its own file")
    def memes_thumb(channel: str, meme_id: str):
        return FileResponse(memes.thumb_path(root, channel, meme_id))

    @api.put("/memes/{channel}/marks", response_model=MemeMarksResult,
             responses=_writing(_MPROBLEMS), dependencies=writes,
             summary="save the whole draft of marks (save_marks, by user via center) when "
                     "`base` is the draft's fingerprint now")
    def memes_marks(channel: str, body: MemeMarksIn):
        return memes.save(root, channel, body.decisions, body.base)

    @api.post("/memes/{channel}/apply/plan", response_model=MemeApplyPlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what «применить» would do (plan_apply), a confirm token when ok - "
                      "nothing written")
    def memes_apply_plan(channel: str, body: Optional[MemeApplyPlanIn] = Body(None)):
        return memes.apply_plan(root, channel, body.drop if body else False)

    @api.post("/memes/{channel}/apply", response_model=MemeApplyResult,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="apply the marks: the plan's token, the same fingerprint, then "
                      "apply_marks")
    def memes_apply(channel: str, body: ConfirmIn):
        return memes.apply(root, channel, body.confirm)

    # ------------------------------------------------ the desk's jobs (CC-0075)
    @api.post("/memes/{channel}/cutout/plan", response_model=MemeCutoutPlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what the cutout would cut (cutout_available + cutout_entries dry run), "
                      "a confirm token when the machine can cut and something would be cut - "
                      "nothing written")
    def memes_cutout_plan(channel: str, body: Optional[MemeCutoutPlanIn] = Body(None)):
        return meme_jobs.cutout_plan(root, channel, body.ids if body else None,
                                     body.force if body else False)

    @api.post("/memes/{channel}/cutout", response_model=MemeJobStarted,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="start the cutout in the background: the plan's token, the same "
                      "fingerprint, then start_job (by user via center) - poll status_url")
    def memes_cutout(channel: str, body: ConfirmIn):
        return meme_jobs.cutout(root, channel, body.confirm, prefix)

    @api.post("/memes/{channel}/trim/plan", response_model=MemeTrimPlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what the trim of blank bands would cut (trim_blank_entries dry run), a "
                      "confirm token when something would be cut - nothing written")
    def memes_trim_plan(channel: str, body: Optional[MemeTrimPlanIn] = Body(None)):
        return meme_jobs.trim_plan(root, channel, body.id if body else None)

    @api.post("/memes/{channel}/trim", response_model=MemeJobStarted,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="start the trim in the background: the plan's token, the same "
                      "fingerprint, then start_job (by user via center) - poll status_url")
    def memes_trim(channel: str, body: ConfirmIn):
        return meme_jobs.trim(root, channel, body.confirm, prefix)

    # ------------------------------------------------ the adds, the sheet, the embed (CC-0076)
    @api.post("/memes/{channel}/add-image/plan", response_model=MemeAddImagePlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what adding a still would do (plan_add_image): http(s) only, nothing "
                      "downloaded or written, a confirm token")
    def memes_add_image_plan(channel: str, body: MemeAddImagePlanIn):
        return meme_jobs.add_image_plan(root, channel, body.id, body.url, body.source_url,
                                        body.description, body.tags, body.notes)

    @api.post("/memes/{channel}/add-image", response_model=MemeJobStarted,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="start adding the still in the background: the plan's token, the same "
                      "fingerprint, then start_job(\"add_image\") - poll status_url")
    def memes_add_image(channel: str, body: ConfirmIn):
        return meme_jobs.add_image(root, channel, body.confirm, prefix)

    @api.post("/memes/{channel}/add-gif/plan", response_model=MemeAddGifPlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what cutting a GIF from a video would do (plan_add_gif, local=False): "
                      "http(s) only, nothing fetched or written, a confirm token")
    def memes_add_gif_plan(channel: str, body: MemeAddGifPlanIn):
        return meme_jobs.add_gif_plan(root, channel, body.id, body.video, body.start, body.end,
                                      body.description, body.tags, body.source_url, body.notes)

    @api.post("/memes/{channel}/add-gif", response_model=MemeJobStarted,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="start the GIF in the background: start_job(\"add_gif\") - poll "
                      "status_url")
    def memes_add_gif(channel: str, body: ConfirmIn):
        return meme_jobs.add_gif(root, channel, body.confirm, prefix)

    @api.post("/memes/{channel}/sheet/plan", response_model=MemeSheetPlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what a contact sheet of a video would do (plan_sheet, local=False): "
                      "http(s) only, nothing fetched or written, a confirm token")
    def memes_sheet_plan(channel: str, body: MemeSheetPlanIn):
        return meme_jobs.sheet_plan(root, channel, body.video, body.start, body.end,
                                    body.every, body.out, prefix)

    @api.post("/memes/{channel}/sheet", response_model=MemeJobStarted,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="start the sheet in the background: start_job(\"sheet\") - poll "
                      "status_url; the result's sheet_url serves it")
    def memes_sheet(channel: str, body: ConfirmIn):
        return meme_jobs.sheet(root, channel, body.confirm, prefix)

    @api.post("/memes/{channel}/embed/plan", response_model=MemeEmbedPlan,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="what recomputing the bank's embeddings would do - the center's own plan "
                      "(the factory has no dry one), a confirm token")
    def memes_embed_plan(channel: str):
        return meme_jobs.embed_plan(root, channel)

    @api.post("/memes/{channel}/embed", response_model=MemeJobStarted,
              responses=_writing(_MPROBLEMS), dependencies=writes,
              summary="start the embedding in the background: start_job(\"embed\") - poll "
                      "status_url")
    def memes_embed(channel: str, body: ConfirmIn):
        return meme_jobs.embed(root, channel, body.confirm, prefix)

    @api.head("/memes/{channel}/sheets/{name}", include_in_schema=False)
    @api.get("/memes/{channel}/sheets/{name}", response_class=FileResponse,
             responses={**_MFILE, 200: {"content": {"image/jpeg": {}, "image/png": {}}},
                        206: {"description": "a range", "content": {"image/*": {}}}},
             summary="a contact sheet the sheet job made: <bank>/_desk/sheets/<name> only "
                     "(.jpg/.jpeg/.png, factory.contained), with HTTP Range")
    def memes_sheet_file(channel: str, name: str):
        return FileResponse(meme_jobs.sheet_path(root, channel, name))

    @api.get("/memes/{channel}/jobs", response_model=MemeJobs, responses=_MPROBLEMS,
             summary="the bank's background jobs, newest first (list_jobs), and the running "
                     "one - nothing written")
    def memes_jobs(channel: str, limit: int = Query(meme_jobs.LIST_LIMIT,
                                                    description="1..50")):
        return meme_jobs.jobs(root, channel, limit, prefix)

    @api.get("/memes/{channel}/jobs/{job_id}", response_model=MemeJob, responses=_MPROBLEMS,
             summary="one job (job_status): running / done / failed / interrupted, its "
                     "progress, result or error; poll_s while it runs")
    def memes_job(channel: str, job_id: str):
        return meme_jobs.job(root, channel, job_id, prefix)

    # ------------------------------------------------ notifications and reminders (CC-0026)
    @api.get("/notify/journal", response_model=NotifyJournal, responses=_NPROBLEMS,
             summary="the notification journal (notify.rows) - what `notify.py list` prints")
    def notify_journal(kind: Optional[str] = Query(None, description="one kind"),
                       channel: Optional[str] = Query(None, description="one channel"),
                       limit: int = Query(20, ge=0, description="the last N; 0: every one")):
        return notifications.journal(root, kind, channel, limit)

    @api.get("/notify/reminders", response_model=NotifyReminders, responses=_NPROBLEMS,
             summary="the user's reminders (notify.reminders) - `remind --list [--all]`")
    def notify_reminders(all: bool = Query(False, description="sent and cancelled too")):
        return notifications.reminders(root, all)

    @api.get("/notify/check", response_model=NotifyCheck, responses=_NPROBLEMS,
             summary="`notify.py test`: the backends that are on, what each would get - a "
                     "stand-in, nothing sent")
    def notify_check():
        return notifications.check(root)

    @api.post("/notify/reminders/plan", response_model=NotifyReminderPlan,
              responses=_writing(_NPROBLEMS), dependencies=writes,
              summary="what «напомнить» would queue (parse_when, one_line), a confirm token - "
                      "nothing written")
    def notify_reminder_plan(body: NotifyReminderPlanIn):
        return notifications.reminder_plan(root, body.at, body.text)

    @api.post("/notify/reminders", response_model=NotifyReminderResult,
              responses=_writing(_NPROBLEMS), dependencies=writes,
              summary="queue the reminder: the plan's token, the same time, then "
                      "add_reminder(by user, via center) - nothing sent now")
    def notify_reminder_add(body: ConfirmIn):
        return notifications.reminder_add(root, body.confirm)

    @api.post("/notify/reminders/{rid}/cancel/plan", response_model=NotifyCancelPlan,
              responses=_writing(_NCPROBLEMS), dependencies=writes,
              summary="what cancelling the reminder would do (its state, what a cancel means), "
                      "a confirm token - nothing written")
    def notify_reminder_cancel_plan(rid: str):
        return notifications.reminder_cancel_plan(root, rid)

    @api.post("/notify/reminders/{rid}/cancel", response_model=NotifyCancelResult,
              responses=_writing(_NCPROBLEMS), dependencies=writes,
              summary="cancel the reminder: the plan's token, the same reminder, then "
                      "cancel_reminder(by user, via center)")
    def notify_reminder_cancel(rid: str, body: ConfirmIn):
        return notifications.reminder_cancel(root, rid, body.confirm)

    @api.post("/notify/test-send/plan", response_model=NotifyTestSendPlan,
              responses=_writing(_NPROBLEMS), dependencies=writes,
              summary="what a test message would reach (the delivery channels that are on, by "
                      "name), a confirm token - nothing sent")
    def notify_test_send_plan():
        return clean(notify_send.test_send_plan(root))

    @api.post("/notify/test-send", response_model=NotifyTestSendResult,
              responses=_writing(_NPROBLEMS), dependencies=writes,
              summary="send the test message once (notify.py test --send): the plan's token, "
                      "the same channels, then notify.send - per channel {via, ok, detail}")
    def notify_test_send(body: ConfirmIn):
        return clean(notify_send.test_send(root, body.confirm))

    # ------------------------------------------------ OAuth and API Data (CC-0028)
    @api.get("/oauth/token", response_model=OAuthToken, responses=_OPROBLEMS,
             summary="the token's state (publisher_auth.status, read_state) - never its value")
    def oauth_token():
        return oauth.token(root)

    @api.get("/oauth/api-data", response_model=ApiDataState, responses=_OPROBLEMS,
             summary="the API Data held, the revocation mark, what the auto-run would delete "
                     "(api_data.status, plan, auto without delete)")
    def oauth_api_data():
        return oauth.api_data(root)

    @api.get("/oauth/revoke", response_model=OAuthRevokePreview, responses=_OPROBLEMS,
             summary="`api_data.py revoke` without --yes: what it would do - nothing reaches "
                     "Google")
    def oauth_revoke_preview():
        return clean(oauth.revoke_preview(root))

    @api.post("/oauth/api-data/purge/plan", response_model=ApiDataPurgePlan,
              responses=_writing(_OPROBLEMS), dependencies=writes,
              summary="what `api_data.py purge` would delete, a confirm token - nothing "
                      "deleted")
    def oauth_purge_plan(body: ApiDataPurgeIn):
        return oauth.purge_plan(root, body.scope, body.channels)

    @api.post("/oauth/api-data/purge", response_model=ApiDataPurgeResult,
              responses=_writing(_OPROBLEMS), dependencies=writes,
              summary="delete the API Data: the plan's token, the same plan, then apply(by "
                      "user, via center)")
    def oauth_purge(body: ConfirmIn):
        return oauth.purge(root, body.confirm)

    @api.post("/oauth/revoke/plan", response_model=OAuthRevokePlan,
              responses=_writing(_OPROBLEMS), dependencies=writes,
              summary="what revoking the token would do (revoke_result without yes, by user "
                      "via center), a confirm token - nothing reaches Google")
    def oauth_revoke_plan():
        return clean(oauth.revoke_plan(root))

    @api.post("/oauth/revoke", response_model=OAuthRevokeResult,
              responses=_writing(_OPROBLEMS), dependencies=writes,
              summary="revoke the token: the plan's token, the same dry run, then "
                      "revoke_result(yes, by user, via center) - its structured result")
    def oauth_revoke(body: ConfirmIn):
        return clean(oauth.revoke(root, body.confirm))

    @api.post("/oauth/api-data/auto/plan", response_model=ApiDataAutoPlan,
              responses=_writing(_OPROBLEMS), dependencies=writes,
              summary="what the deletion by term would delete now (auto without delete), a "
                      "confirm token - nothing deleted")
    def oauth_auto_plan():
        return oauth.auto_plan(root)

    @api.post("/oauth/api-data/auto", response_model=ApiDataAutoResult,
              responses=_writing(_OPROBLEMS), dependencies=writes,
              summary="delete by term: the plan's token, the same plan, then auto(delete, by "
                      "user, via center)")
    def oauth_auto(body: ConfirmIn):
        return oauth.auto_delete(root, body.confirm)

    # ------------------------------------------------ maintenance and spend (CC-0032)
    @api.get("/maintenance", response_model=Maintenance,
             summary="the factory's archives, cleanups and reports - which is read, plan/"
                     "confirm or not exposed, and why (CC-0032)")
    def maintenance_view():
        return maintenance.overview()

    @api.get("/maintenance/usage/{channel}/{batch_id}", response_model=UsageReport,
             responses=_MTPROBLEMS,
             summary="a batch's spend: usage_report --json (usage.read_usage, usage.totals)")
    def maintenance_usage(channel: str, batch_id: str):
        return maintenance.usage(root, channel, batch_id)

    @api.get("/maintenance/compare", response_model=CompareRuns, responses=_MTPROBLEMS,
             summary="a batch by hand against one by the executor: compare_runs --json")
    def maintenance_compare(manual: str = Query(..., description="<channel>/<batch_id> run by "
                                                                 "hand"),
                            executor: str = Query(..., description="<channel>/<batch_id> run "
                                                                   "by the executor")):
        return maintenance.compare(root, manual, executor)

    @api.get("/maintenance/archive", response_model=ArchiveDryRun, responses=_MTPROBLEMS,
             summary="archive_publish_month --dry-run: its lines and exit code - a view (the "
                     "write of step a: POST /maintenance/archive/plan, CC-0104)")
    def maintenance_archive(monthly: bool = Query(False, description="the whole monthly run "
                                                                     "(pool, batches, $TMPDIR) "
                                                                     "too, not --publish-only")):
        return maintenance.archive(root, monthly=monthly)

    @api.post("/maintenance/archive/plan", response_model=ArchivePlan,
              responses=_writing(_MTPROBLEMS), dependencies=writes,
              summary="what the month archive (step a, --publish-only) would move: "
                      "archive_publish_month --dry-run --json - a confirm token unless a batch "
                      "is open or the volume is missing (CC-0104)")
    def maintenance_archive_plan():
        return maintenance.archive_plan(root)

    @api.post("/maintenance/archive", response_model=ArchiveResult,
              responses=_writing(_MTPROBLEMS), dependencies=writes,
              summary="run the month archive: the plan's token, no batch open, the same dry "
                      "run, then archive_publish_month --publish-only --by user --via center")
    def maintenance_archive_run(body: ConfirmIn):
        return maintenance.archive_run(root, body.confirm)

    @api.post("/maintenance/journals/plan", response_model=JournalsPlan,
              responses=_writing(_MTPROBLEMS), dependencies=writes,
              summary="what cleanup_batch_journals --delete would do (its plan), a confirm "
                      "token unless a batch is open - nothing touched")
    def maintenance_journals_plan():
        return maintenance.journals_plan(root)

    @api.post("/maintenance/journals", response_model=JournalsResult,
              responses=_writing(_MTPROBLEMS), dependencies=writes,
              summary="clean the batch journals: the plan's token, no batch open, the same "
                      "plan, then cleanup_batch_journals.delete")
    def maintenance_journals(body: ConfirmIn):
        return maintenance.journals_clean(root, body.confirm)

    @api.get("/maintenance/pool", response_model=PoolView, responses=_MTPROBLEMS,
             summary="the footage pool: pool-release --json --variants (pool_release.plan, "
                     "variants) - what a release would free, what is kept and why (CC-0105)")
    def maintenance_pool(stale_days: Optional[int] = Query(None, description="the stale rule's "
                                                                             "N, 1..365")):
        return pool.view(root, stale_days)

    @api.post("/maintenance/pool/release/plan", response_model=PoolReleasePlan,
              responses=_writing(_MTPROBLEMS), dependencies=writes,
              summary="what pool-release --delete would remove (its plan), a confirm token "
                      "unless a batch is open - nothing touched")
    def maintenance_pool_release_plan(body: Optional[PoolReleaseIn] = None):
        return pool.release_plan(root, body.stale_days if body else None)

    @api.post("/maintenance/pool/release", response_model=PoolReleaseResult,
              responses=_writing(_MTPROBLEMS), dependencies=writes,
              summary="free the pool: the plan's token, no batch open, the same plan, then "
                      "pool_release.delete")
    def maintenance_pool_release(body: ConfirmIn):
        return pool.release(root, body.confirm)

    @api.api_route("/{rest:path}", methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"],
                   include_in_schema=False)
    def api_not_found(rest: str):
        return JSONResponse({"detail": f"no such route: {prefix}/{rest}"}, status_code=404)

    app.include_router(api)

    @app.exception_handler(channels.ChannelFault)
    def channel_fault(request: Request, exc: channels.ChannelFault):
        return problem(exc.body(), exc.status)

    @app.exception_handler(WritesRefused)
    def writes_refused(request: Request, exc: WritesRefused):
        return problem(exc.body(), WRITES_STATUS)

    @app.exception_handler(batches.BatchFault)
    def batch_fault(request: Request, exc: batches.BatchFault):
        return problem(exc.body(), exc.status)

    base = settings.base_path

    @app.api_route(base + "{rel:path}", methods=["GET", "HEAD"], include_in_schema=False)
    def center(rel: str):
        return _center_response(settings, rel)

    # the guard sees every request first, a 404 too
    app.add_middleware(Guard, settings=settings, token=token, auth=auth)
    return app
