# How the shortlist is chosen

Operator documentation of the Trend Hunter: which topics leave the selection and
why, how a freed slot is refilled, the fact and the footage pool at selection,
and the popularity score. The overview is the [README](../README.md); the
procedure the stage follows is
[`SKILL.md`](../.claude/skills/trend-hunter/SKILL.md).

## A video already made is not a new topic (CF-0019)

Batch `example-film/2026-09-29T0705Z`, finding 5 of its review: Backrooms (published
28.09) and Wolfhame (29.09) came back as new topic ids; Backrooms took a slot of the five
and Wolfhame was the reserve. Nothing compared a topic with `publish/`.

`scripts/published_before.py` builds the registry of made videos: every slug of
`publish/acceptance-log.json` whose **latest** verdict is `accepted` (a rejected video is
not made; widows-bay's accepted → rejected → accepted counts), plus a `publish/<slug>.md`
with its `.mp4` and no log row. Each video's topic — `title_ref` and its news — is read
back out of the `01` of the batch it came from (`batch_artifact`, the log's
`channel/batch_id`, every `pipeline/...` the `.md` names; `PIPELINE_DIR` wins over
`<root>/pipeline`); a row with no `topic_id` is resolved by its slug against the batch's
topic names (`outrider-doune-castle` → *Outrider: Blood of My Blood*).

Step 5a (`fact_probe_topics.py`) compares every topic with the registry after the persons
and **before the probe**:

| the topic and the made video | what happens |
|---|---|
| same work, a shared news article (`evidence.sources` / `rss_links`, URL without scheme, `www.`, query) | `skipped_topics[]`, `reason_code: already_published`, not probed; its slot goes to the next topic by score |
| same work, other articles | kept, `topics[].published_before`, `WARNING published_before` line |
| same work, the made video's news unknown (topic not found) or matched by slug only | kept and marked (`story: unknown`, `same_work_unverified`) |
| another season / another installment of the franchise | kept and marked (`other_season`, `same_franchise`) |

Why the article is the test of "the same story": the hunter has no fact yet (the writer
picks it), so the story a topic *is* is the news it was found by. On 0705Z Backrooms
carries the very same three articles as the topic `-014` it was made from (Variety,
Deadline, THR of 26.09), Wolfhame the very same two as `-011` — the "new fact" was the
writer's, the news was the old one. Both leave; Vanguards: Doomsday is marked
(`same_franchise` with the accepted Endgame of the same batch). A new story about the same
work with another fact is the grill's to decide (2.0.4) and is only marked until then.
The pattern-repeat window (CF-0042) is not this.

`selection.published` says what the registry held (`videos`, `unresolved`, `errors`) and
what it did (`dropped`, `marked`); `--check` refuses a carried topic whose mark says "same
work, same story" and an `already_published` row that does not name the video it repeats.
`--no-published` switches the comparison off for a replay. The code is new in the root's
funnel vocabulary.

## The slot a refusal frees is refilled from the reserve (CF-0313)
Until 2026-09-22 that refusal left the slot empty: step 5a cut the shortlist and nothing
promoted a `below_shortlist` topic in its place, so the loss was paid out of the slack
between the shortlist (8) and the batch target (5). CF-0309 made the refusals common
enough that the slack stops covering them.

Now `footage_candidates.py` answers its own loss the way the indexer answers one
(CF-0306): the next reserve topic **by rank** goes back into `topics[]` and is walked
through step 5b like any other topic — the same four sieves, the same floor, the same
refusal if its own pool is thin, in which case the slot is freed again and offered to the
next one. Compliance judges it on its first pass, because it is in `topics[]` before the
compliance stage opens the file, and `cut_shortlist.py` (CF-0265) ranks it by `topics[]`
order — last, which is what it is.

Two things make it possible and one makes it finite:

- `fact_probe_topics.py` keeps the **whole topic** on the `below_shortlist` row (`topic`)
  and the `rank` it was cut at. A summary cannot be put back into a batch: `title_ref` is
  what compliance judges. A batch written before CF-0313 carries neither, and
  `restore_reserve_topic()` rebuilds what it can from the summary and `fact_probe.asked`
  (the entry says `restored: true`; what such a record misses is the topic's own
  `evidence` and `rights_holder`).
- `footage_substitution` in the batch file records the whole thing: `substitutions[]` (who
  replaced whom, with what code the replaced topic died, `outcome`), `unmatched[]` (a slot
  nothing could fill: `reserve_exhausted`, or `search_quota_exhausted` when the day will
  not pay), `remaining[]` (the untouched reserve). The replaced topic's own row gains
  `replaced_by_topic`, and the promoted topic's `below_shortlist` row is removed — a spare
  that was used is not a spare, and the funnel counts that column.
- **The price.** One substitution is one facet run: 6 `search.list` calls of the 100 the
  API allows a project per day (CF-0288). `search_quota.py` counts what the batch spent —
  from the searches handed in and from the batch's own run log — and
  `search_quota.substitutions_affordable` is the remainder divided by the price. It is
  never a literal, and it is written into the artifact beside the numbers it came from.
  What the same quota day spent outside this batch is `--searches-spent N`.

The facet run is a network call the script does not make, so a substitution it decides
without one is written `outcome: "pending_search"` with the exact command; re-running
`footage_candidates.py` with that search completes the same entry. Re-runs are idempotent:
a loss already answered is never answered twice, and a reserve topic already spent is
never offered twice. `selection` is step 5a's record of its own pass and is not rewritten
here — what the batch holds is `topics[]` and `skipped_topics[]`.

## Later in the batch: the topics below the shortlist (CF-0882)

CF-0313 refills a slot inside this stage. When the batch loses topics later -
compliance's cut, the Footage Indexer's reserve rounds, the frame judge - and the
reserve (`02 -> reserve[]`) is spent, the root's refill round
(`shared/below_shortlist.py`, plan stages `reserve-below-shortlist{,-late,-judge}`) takes
the next `below_shortlist` topics by rank: compliance judges them on the fly, then calls
`scripts/promote_below_shortlist.py <batch> --topics a,b --max-searches K --result <path>`
here. Nobody runs it by hand.

Per topic, in order: the official channels' feeds first (`fetch_channel_feeds.topic_feed`,
no `search.list` - a topic the feeds cover costs 0); only when they give fewer than the
floor, the channel's facet run (`fetch_youtube_signal.run_signal`, the channel's facets and
search cache, every call a `youtube-api search` event, so the day's ledger the root reads
stays true); then the same sieves and floor as step 5b. `K` is the most `search.list`
calls the call may make in all, read off the day's quota by the root; a topic whose run
the rest does not pay for is `quota` and is not searched at all (the cache's answers are
free, so a cached run fits even `K = 0`).

A topic with a pool moves into `topics[]` with `"refill": {"task": "CF-0882"}` and its
`rank`, and its `below_shortlist` row leaves `skipped_topics[]`; a refused one keeps the
row, marked `refill_outcome: refused` with `refill_reason`. Every topic gets one row in
`below_shortlist_refill[]` (`topic_id`, `outcome`, `searches`, `at`, `reason`) - the row
compliance's `admit` finds the topic by - and what was spent goes into `search_quota`
(the topic's key for the facet run, `<topic>:feeds` for the feed read). A second call for
the same topic searches nothing.

## This stage never waits for a person (CF-0317)

In an autonomous run no stage has the right to block on a decision that needs the user.
Whatever would have been a question is a recorded outcome with a code, and the batch goes
on; the person reads it afterwards. The register of those points is the root's —
`shared/runlog/no_waiting.py`, listed by `runlog no-waiting --list --json` — and two of
them are this stage's. Neither code is spelled twice: a second spelling is unreadable to
`no_waiting.classify()` and to the `pipeline/runs.jsonl` row.

- **No `YOUTUBE_API_KEY` in the environment nor in the repo's `.env`** (`hunter_missing_api_key` →
  `missing_api_key_skip`). The `Inputs` line used to say "stop and tell the user". A key
  that is not in the environment is a fact about the machine, not about the batch, and it
  cannot appear inside a run — so the wait could only end at the keyboard. The stage now
  writes no `01-trend-hunter.json`, closes with
  `stage-done --note "missing YOUTUBE_API_KEY, batch not attempted"`, and the batch ends
  there. The next scheduled run tries again. The prohibition behind the old sentence is
  untouched: **do not fabricate data** — an empty stage with a recorded reason is the
  correct output, a batch written from memory is not.

- **The day's YouTube Search quota will not pay for a topic's facet run**
  (`hunter_quota_resume` → `footage_evidence_quota`). This is the one that was paid for in
  real time. On `example-film/2026-09-19T0116Z` step 5b widened the footage of 3 of 8 topics
  before the 100 `search.list` calls of the day ran out; the stage closed at 01:26 and
  reopened at 07:06 "resumed after the YouTube search quota reset" — **5 h 40 m 11 s** of a
  39 h 42 m run spent in front of somebody else's clock. Nothing in the procedure said to
  wait, and nothing said not to: `fill_batch` kept such a topic in `topics[]` and recorded a
  *problem* telling the operator to run `--facets` for it, which on a spent day was
  unobeyable inside the run. Now `no_search_yet()` asks the settled ledger. A day that can
  still pay means the search was simply not handed in, and the message names the command; a
  day that cannot is nobody's decision — the topic leaves `topics[]` into `skipped_topics[]`
  with `footage_evidence_quota`, the funnel counts the loss, and the batch is at compliance
  a minute later. The searches the day can still pay for go to the topics that rank first,
  and the reserve is untouched, since a substitution costs a facet run too.

`tests/test_no_waiting.py` replays the batch of the incident out of its own artifact: the
three topics that were paid for, the five that were waited for.

## The fact decides the selection (CF-0264, CF-0438, CF-0439)

The channel refuses a video with no concrete, verifiable fact the story does not carry —
of any kind since CF-0439 (until then: about how the thing was made), over the whole of
Hollywood: people, films, series, animation. The kind of a fact never makes it better:
candidates rank by whether they pass the rule, the source's tier, a number and an
attribution, and the order of the channel's `kinds` (`fact_search.kind_order`, CF-0627;
production first for example-film) only breaks a tie between
candidates equal on all of those. That rule
is not this repository's — it is the channel's stance and the writer's refusal
(CF-0185) — but since the grill of 2026-09-17 (decision of CF-0260) the **question is
asked here**, at topic selection, instead of after the footage has been downloaded. On
`example-film/2026-09-16T2148Z` the rule took three of four topics off the batch after the
indexer had fetched and indexed six sources for them, ~36 minutes of 48.

The order of the stage is **fact check → scoring → persons → probe → shortlist**, and the
last three but the cut are `scripts/fact_probe_topics.py`. CF-0823 (2026-10-21) put the
fact check before the scoring search too: the drafted candidates go through the same fact
search (`--before-scoring`, no support text, registry, pool or cut) and one without a fact
leaves `no_fact` with `before_scoring: true` before its `search.list` is paid for; the
channel's memory of `no_fact` refusals (`scripts/no_fact_memory.py`,
`pipeline/<channel>/no-fact-memory.json`, `scope.no_fact_memory_days`, 3 by default) holds a
candidate refused in the last days back without a probe. CF-0876 (2026-10-27) holds back
the same way a work the channel's Researcher refused `pool_too_thin` at **0 clean shots**
(of at least one indexed source) in its last `scope.thin_pool_memory_days` (3) days of
batches - Mudform four batches running on ExampleFilm 24-26.10, 102 weak shots and the
same three sources each time: `scripts/thin_pool_memory.py` reads the earlier batches'
`03-content-researcher.json` / `01b-footage-index.json` / `01-trend-hunter.json`
(read-only, nothing is written), keys the work like the no-fact memory, and lets it
through only when the shared pool holds a source for it none of the refusing batches had.
A held work leaves as `pool_too_thin` with `thin_pool_memory` and `before_scoring: true`,
and `refill_topics.py` does not pick it (`refill.thin_pool_skipped`). `prescreen.totals` of
the batch counts the searches both memories saved. The full pass then runs over the scored ones as below:

- **Persons.** A story about a person is the channel's story in its own right (CF-0439,
  `channels/example-film/stance.json` → `persons`), so nothing is refused here any more:
  `person_without_work` (CF-0260/CF-0264) is not written since 2026-09-29 and is only read
  in older batches. When the topic's own news leads (the headlines in `evidence.sources`,
  plus the RSS summaries when `--rss` is passed) **name** a work, the work goes in
  `title_ref.name`, the person in `title_ref.person`, and the fact is looked up for the
  work, as before. Otherwise the subject is the person: `title_ref.name` is the person's
  name, and the probe asks by name alone (no `type` / `year` / `network` held against a
  biography). The filmography guard stays — the work's own string has to occur in the
  leads; a work that came from a filmography is taken out of `title_ref.name` and the
  person looked up instead, with a note in the stage report. For a person subject every
  candidate is `about_person: true`, i.e. held to the rule's stricter half (a major outlet,
  never a rumour, "X reported that…") — unchanged, not relaxed.
- **The probe.** Every remaining candidate, in descending score, is asked about through the
  Content Researcher's own lookup (`agents/content-researcher/scripts/fact_probe.py`,
  CF-0263) — one subprocess for the whole list, so one client paces it; no copy of the
  lookup lives here. Since CF-0438 the probe only resolves the article: the candidates are
  every section of it plus the batch's own news (`fact_search.py`; since CF-0638 only a
  post of a `read_text` feed - a `headline_only` feed's post is no candidate), each checked by
  `fact_rule.check_candidates`, written onto the topic as `fact_candidates` (best first,
  each with its `check`). The topic leaves with `no_fact` only when no candidate passes and
  every source answered, with the probe's answer, the search record and the failed
  candidates beside it. Before CF-0438 `no_article`, `no_section`, `no_candidates` and
  `wrong_article` took it off with `no_production_fact` - 46 topics over 13 batches.
  Since CF-0439 the probe's `no_section` means "nothing but plot and cast", not "no
  Production"; this stage never reads the probe's `sections` for a verdict — it reads the
  article (`ok` / `no_section` / `no_candidates`) itself.
  **The filter is `usable`, not `has_fact`:** `source_unreachable` means "we could not
  ask", and a shortlist filtered on `has_fact` would empty itself during a Wikipedia
  outage.

  Since CF-0323 the filter is not this stage's own predicate. The state comes from
  `scripts/fact_rule.py` - the same `classify`/`drops` the writer's refusal applies after
  the footage is indexed, over the same statuses, the same `wrong_article` and the same
  "an empty candidate list is part of the emptiness" - and not from the `usable` flag the
  probe writes, which is the other implementation's conclusion. The decision is written
  onto the topic as `fact_probe.fact_rule` (`state`, `settled`, which rule and which
  version), and `settled` is what says the question has been answered at the earliest
  stage that could observe it: true for every state but `source_unreachable`, which is the
  one answer that can change between two askings and the one a later stage is meant to ask
  about again. Over the frozen pool the split is 29 `no_production_fact` losses, 26 of them
  taken here for nothing and 3 taken after the indexer - all three in
  `example-film/2026-09-16T2148Z`, before this stage asked at all, paid with 6 of that
  batch's 8 indexed sources (`scripts/fact_rule_replay.py`).
- **The shortlist.** The first `scope.shortlist_size` viable topics in score order (8 when
  the key is absent; the channel config is read, never written, by this repository). The
  cut to `scope.max_titles_per_batch` happens after compliance (CF-0265), so a topic
  compliance takes off the batch has a replacement — on 2026-09-16 it did not. What is past
  the cut is `below_shortlist` in `skipped_topics[]`: unused reserve, recorded rather than
  dropped in silence — and since CF-0313 the row carries its `rank` and the topic itself,
  because step 5b puts it back into the batch when a refusal frees a slot.

Every carried topic keeps `fact_probe` (outcome, article, `article_url`, candidates,
`parent_work`, what was asked and when) so the writer reads the fact out of the same
article this stage was answered from, and `selection` counts the whole pass. The probe
costs no API quota and about a minute for 15 candidates; the footage fan-out that follows
it costs 600 units a topic, which is why it runs second.

## Hype × pool: the shortlist asks the footage pool first (CF-0325)

Grill of 2026-09-22 (Q4): `shared/footage` held 133 downloaded, cut and described sources,
and no production path of this stage read them — topics were chosen on RSS and popularity,
and the indexer then fetched footage for them from scratch. Grill "формат канала"
(2026-09-29, Q8): **the hunter ranks topics by hype × pool**; the fact is only the threshold
"at least one fact passes".

`scripts/fact_probe_topics.py` (step 5a) asks `scripts/pool_coverage.py` about every viable
topic right before the cut:

- **Matched by title / franchise, never by `video_id`.** Phrases: `title_ref.name`,
  `parent_work` / `parent`, `person`, and the name before `:` / ` - ` (the franchise), each
  at least 4 characters, as whole words in the source's title in `shared/footage/index.json`
  (`by: "title"`), or through the earlier topic the source was fetched for — `note: "batch X,
  topic Y"`, the name read from `pipeline/*/X/01-trend-hunter.json` (`by: "topic"`).
- **Counted the Editor's way, minus what is spent.** The matched sources go through
  `footage-indexer/scripts/pool_depth.screen_shots` (the Video Editor's pre-cut gate, the
  CF-0304 number), run by `scripts/pool_screen.py` under the indexer's venv because the gate
  needs PIL; shots listed in `pipeline/<channel>/retired-shots.json` (CF-0397, already in a
  finished video) are removed first. If the gate cannot be run, `usable` is null and the
  coverage falls back to the source count; the note says so.
- **The formula:**

  ```
  coverage   = min(1, usable / 60)       # 60 = pool_depth.POOL_DEPTH_FLOOR, where the indexer stops fetching
               (min(1, sources / 2) when usable is unmeasured; 2 = the CF-0129 floor)
  rank_score = popularity_score × (1 + 0.5 × coverage)
  ```

  Why a bounded bonus and not a product with zero: a fresh hot topic with nothing in the
  pool keeps its whole score (×1), so the pool never removes a topic and never introduces
  one — it only reorders the topics that came in on today's news above
  `min_popularity_score`, which is what keeps the factory from chewing its archive (the
  user's objection). A topic whose pool is already at the indexer's stopping depth
  outranks a pool-less one only when its hype is ≥ 2/3 of the other's (1/1.5): views come
  from the hype (AHS 1.4k, Widow's Bay 1k), the pool is allowed to break near-ties and lift
  a topic across the shortlist line, not to overturn a clear hype lead.
- **Written down.** `topics[].pool` on every viable topic (`sources`, `shots`, `retired`,
  `usable`, `measured`, `floor`, `coverage`, `coverage_by`, `factor`, `rank_score`,
  `phrases`, `matched[] {video_id, title, by, usable, host_show?}`, `host_show_skipped`,
  `host_show_error`, `error`), kept inside the reserve rows' `topic`, and `selection.pool` (`with_pool`, `measured`, `reordered`, the formula).
  `topics[]` is in `rank_score` order and `--check` holds it to that; a batch without
  `pool` is checked on the bare score as before. `--no-pool` cuts on the score alone.
- **Somebody else's host show is no pool (CF-0817).** A matched source the Footage Indexer's
  pool reuse would refuse as a host show (`host_show.judge()` on the pool's title and
  uploader, `official` from the channel's footage_origin list, the exceptions read off the
  topic's `title_ref`) is left out of the count and listed under `pool.host_show_skipped`
  (video ids): Fallon with Tom Carver (`ZLXL1L0TfsI`) earns Delver no bonus, the Delver
  trailer still does. A source kept under an exception counts and its `matched[]` row says
  which (`host_show: subject_is_guest | topic_is_the_show`); a verdict that could not be had
  skips the source too (`host_show_error`).
- **Freshness is the ingest queue's (CF-0324), not this run's.** The pool is filled with what
  the hunter finds today; this stage never waits for it. The pool is transient (CF-0358:
  from 1.5 sources are deleted after publication) — a topic whose sources are gone just
  reads a thinner pool. Look up a title by hand: `.venv/bin/python scripts/pool_coverage.py
  "The Diplomat"`.

**The measurement** (`scripts/pool_coverage_replay.py --channel example-film` - the channel is required since CF-0213; 2026-09-29, ~7 s): every frozen batch
of the channel (`pipeline/example-film/*`, `pipeline/legacy-film/*`) against the pool as
it stood **when that batch started** (sources fetched and shots retired before the batch id's
time). The artifacts carry **15 topic-level losses** under the three codes — 9
`no_second_source`, 6 `pool_too_thin`, 0 topic-level `fetch_failed` (the 26 `fetch_failed`
records are per-candidate download failures in `01b.failed[]`, not lost topics; the grill's
"24 of 101" counted over a different set of records and is not reproducible from the files):

| code | lost | pool already held it | ranked out by hype × pool | removed |
|---|---|---|---|---|
| `no_second_source` | 9 | 6 | 1 | 7 |
| `pool_too_thin` | 6 | 5 | 0 | 5 |
| **total** | **15** | **11** | **1** | **12** |

"Pool already held it": ≥ 2 sources of the title in the pool before the batch fetched a byte
(`no_second_source`) or ≥ 60 usable shots of it (`pool_too_thin`) — Wren Hollow lost
`pool_too_thin` twice with 195 and 215 usable shots of the franchise already indexed,
Rennick, Harbourlights, Delver and Silent Tide the same way. "Ranked out": the re-cut moves it past
the batch target of 5 (My Hero Academia, 2026-09-22T1001Z, rank 5 → 6). Not removed: The
Diplomat, Cliff Booth (nothing in the pool before) and Pine Park (2 sources, 7 usable).

What the 11 say, read honestly: the pool **had** the footage and the downstream stages did not
use it, because the indexer and the writer count only the sources fetched for *this* batch's
topic. This stage now ranks on the pool and writes `topics[].pool.matched`; the losses go away
only when the Footage Indexer also registers those matched sources as the topic's canonical
sources before it downloads (a footage-indexer change, not this repo's). The match is
franchise-level (a Wren Hollow film trailer matches the Example Network series), which is right for a
ranking bonus and needs `topic_relevance`-style judgement before it becomes a topic's footage.
Caveat: the replay screens with today's cached verdicts and cannot see sources deleted since,
so it can undercount the pool a batch had, never overcount it.

## Scoring: houses, not entries (CF-0038 → CF-0060)

`scripts/score_candidates.py` scores on two absolute components. The view component is
CF-0038's log scale (floor 5k, ceiling 10M, 30.3 points a decade). The RSS component
since CF-0060 is the number of distinct **publishing houses** whose feeds carried the
topic, against a ceiling equal to the number of houses in the channel config (2: PMC for
Variety/Deadline/THR, Lupa Systems for Vulture). The feed → house map is
`sources.rss.feeds[].house` in `channels/example-film.json`; entries are attributed by
link domain (`site`), and `score_candidates.py --houses <links> --channel-config <channel>` does the counting (no default channel, CF-0213).
Since CF-0753 the feed that carried the entry decides first (`--rss <fetch output>`; a
batch's `evidence.sources[].feed` on a replay), the domain only for a link the fetch does
not hold: an aggregator (Hacker News on ExampleTech) links each entry to the story's own
site, which no `site` lists - three `--houses` calls died on that in
example-tech/2026-10-15T1854Z. A link nothing places is listed (`unattributed_links`) and
counted as no house, never a crash; a `kind: vendor` feed adds no house, as in
`candidate_pool.py`.

Why: three PMC entries used to score as three confirmations and reach the old threshold
of 40 with zero video audience (AMC Leawood Films 2026-08-31, Entourage 2026-09-02 -
both exactly 40.0). As one house they score 20.0. `min_popularity_score` was re-derived
by the CF-0038 rule (highest threshold at which no pool collapses to one topic) over the
five written batches plus a fresh 2026-09-03 pool: **45**, bounded as before by
2026-08-31T2155Z. A one-house story needs ~119k views, a two-house story ~9.4k, and
coverage alone never clears it. Working in `tasks/CF-0060-*.md`; pinned by
`tests/test_scoring_scale.py`, whose fixture carries all six pools with provenance.
