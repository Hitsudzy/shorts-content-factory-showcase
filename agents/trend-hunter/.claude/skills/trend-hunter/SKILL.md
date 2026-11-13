---
name: trend-hunter
description: Run one Trend Hunter batch for a given channel — scan entertainment news + YouTube signal, and output a scene-tagged topic list to the shared pipeline. Use when asked to run/hunt trends, or invoked as "/trend-hunter <channel>".
---

You are the **Trend Hunter** agent in a YouTube shorts-content-factory pipeline. Your job each batch: find currently popular TV-show topics and break each one into candidate short-form scenes tagged by emotional register, so the next agent (Content Researcher) has a ready shortlist instead of raw material.

You do **not** decide licensing or rights risk — that's Compliance Checker's job, a separate stage of the run plan. Just attach the metadata it will need (rights holder if evidenced, source links).

You do **not** self-schedule. You run once per invocation, when the run plan's executor (or the user) asks for a batch.

**No TMDB.** TMDB was evaluated and dropped: its free tier is restricted to non-commercial use and the commercial tier is not worth it for this pipeline. Discovery and metadata come entirely from RSS + YouTube. If you don't see a `tmdb` source in the channel config, that's expected — don't try to call TMDB scripts (the parked code is no longer in the repo).

## Inputs

- `channel` argument — **required, no default** (CF-0213). Load its config from `../../channels/<channel>.json` (relative to this skill = `~/shorts-content-factory/channels/<channel>.json`). Invoked without a channel, stop and say so: do not pick one, and never fall back to the channel of an earlier batch - a second channel's run under the first one's config would gather topics by the wrong feeds, threshold and `content_type` without a word. The scripts refuse the same way: `score_candidates.py` without a channel (no `--channel-config` and no `channel` field in the batch), `fact_probe_topics.py` on a batch with no `channel` field, `pool_coverage.py` / `pool_coverage_replay.py` without `--channel` all exit 2.

**`<channel>` in every path below is the channel's current id (CF-0197).** A renamed channel keeps its old batch directories under the old name - `pipeline/legacy-film/` is still there and still correct - so the batch you are about to write goes under `pipeline/example-film/` while the seven batches of August-September 2026 stay where they were written. That split is the convention, not a mistake to repair: it is written once in the root `README.md`, section **"Renamed channels and their batch directories"**. Read it there; do not restate it here, do not create the batch under the old directory, and do not move the old one. A former id handed to you - on the command line, or as the `"channel"` field frozen inside a batch file written before the rename - resolves through `scripts/_channel_ids.py`.
- API key `YOUTUBE_API_KEY` — do not fabricate data. **The scripts find it themselves** (CF-0360): the environment first, else this repo's own `.env` (`agents/trend-hunter/.env`), through the one helper `scripts/_apikey.py`. Do not `source .env`, do not `cat`/`grep` it and never print the value; just run the scripts. "Missing" means a script exited with `missing YOUTUBE_API_KEY` — the key is in neither place — not that `$YOUTUBE_API_KEY` is empty in your shell.

  **If it is missing, this stage does not ask and does not wait** (CF-0317). A key absent
  from both the environment and the repo's `.env` is a fact about the machine, not about this batch, and nothing that
  happens inside the run can change it, so there is nothing to wait for. No
  `01-trend-hunter.json` is written, nothing is invented in its place, and the stage closes
  on the spot:

  ```bash
  "$RUNLOG" stage-done trend-hunter --batch "$RUNLOG_BATCH" \
      --note "missing YOUTUBE_API_KEY, batch not attempted"
  ```

  The batch ends there with the code `missing_api_key_skip` — the register's word for this
  point (`shared/runlog/no_waiting.py`, `hunter_missing_api_key`), which is why the note is
  written as it stands above: `trend-hunter` has two points in that register, and the note is
  what tells them apart. Name the key in it and do not use the word *quota*, which belongs to
  the other one. Say the same sentence in chat, in plain text, and stop. The next scheduled
  run tries again — a key that appears in the environment appears between runs, never inside
  one.

  What does **not** change is the prohibition: do not fabricate data. A batch written from
  memory, invented video ids or topics without a search behind them are worse than no batch,
  because everything downstream treats them as measurements. An empty stage with a recorded
  reason is the correct output here.

## Procedure

**Run accounting (CF-0107) - the stage boundaries.** Every batch keeps
`RUN_EVENTS.jsonl` in its directory, and `RUN_LOG.txt` beside it is **generated** from
those events (`runlog render`; every marker command re-renders it) - never write or edit
`RUN_LOG.txt` by hand. The batch directory is the one this stage writes into:
`~/shorts-content-factory/pipeline/<channel>/<batch_id>/` (step 7's path). Under the
run plan it is the `Batch directory:` line of the prompt, and the batch is already
open when you are invoked: the plan's root stage `batch-start` wrote it (the
executor, or the operator by hand) - you never write `batch-start` and never write
`batch-done`. Where this stage sits in the batch, and what runs before and after
it, is the channel's run plan (`python3 shared/run_plan.py show <channel>` in the
factory root), not this file. The first act of the stage, before step 1:

```bash
RUNLOG=~/shorts-content-factory/scripts/runlog
export RUNLOG_BATCH=~/shorts-content-factory/pipeline/<channel>/<batch_id>
"$RUNLOG" stage-start trend-hunter --batch "$RUNLOG_BATCH"
```

Only when the hunter is run **outside the plan** (by hand, on its own, with no
batch directory given) do you compute `batch_id` now (step 7's format), create the
directory and open the batch yourself, before the `stage-start` above:

```bash
mkdir -p "$RUNLOG_BATCH"
grep -q '"batch-start"' "$RUNLOG_BATCH/RUN_EVENTS.jsonl" 2>/dev/null || "$RUNLOG" batch-start --batch "$RUNLOG_BATCH"
```

Keep `RUNLOG_BATCH` exported for the whole stage: the scripts below write their own
`start`/`done` (or `failed`) events under it - `fetch_rss_news.py` as step `fetch-rss`
with one `child` event per feed, `fetch_youtube_signal.py` as `youtube-signal` with one
child per Data API call, `score_candidates.py` as `score`, `fact_probe_topics.py` as
`fact-probe` with one child event for the probe subprocess it runs in the Content
Researcher's tree, `evidence_sources.py` as
`evidence-sources`, `check_scenes.py` as `check-scenes`, `footage_candidates.py` as `footage-candidates` - and without the
variable they only warn on stderr and record nothing. (The `python -c` one-liners that call `popularity_score` and
`batch_discovery_record` are pure functions; they leave no event, by design.) The last
act of the stage is in step 8. A stage that stops early still ends with `stage-done`,
with a `--note` saying why.

1. **Load channel config.** Read `scope`, `sources`, `tag_taxonomy`, `scoring_weights`.

2. **Discover candidates from news (RSS).**
   ```bash
   mkdir -p <batch-dir>/work && .venv/bin/python scripts/fetch_rss_news.py \
     --channel <batch channel> > <batch-dir>/work/rss.json
   ```

   **The window and the file are the channel's and the batch's (CF-0789).** Do not type
   `--days`: without it the script reaches back the channel's `sources.rss.discovery_days`
   (ExampleScience 7 - its eight feeds gave 102 entries in three days on 2026-10-17, against
   ExampleFilm's ~470) and 3 for a channel that says nothing; the output says which in
   `requested_days_from` (`channel` / `default`; `flag` only for a replay that typed it). The
   fetch goes to `<batch-dir>/work/rss.json`, not to `/tmp`: it stays with the batch, so the
   pool and the houses can be re-read and re-measured from the batch alone.

   `--channel` is the batch's channel (CF-0634): the script reads that channel's feeds
   itself, through the root's `shared/channel_data.py` (`feed_urls`) - do not type the URLs.
   A channel whose feeds break the factory's AI-bot rule (root `docs/channel-data.md`,
   «Sources and the AI-bot rule»: a feed without `use` / `ai_policy`, a `read_text` feed
   whose verdict is not `allowed`, a feed robots.txt closes to every agent) or that has no
   feeds is refused with exit 2 and nothing is fetched: stop the stage and say which feed
   and why - do not fall back to `--feeds` with the list typed by hand (`--feeds` is for a
   replay of one feed). Each feed carries a `use`: `headline_only` (example-film's four: the
   PMC trades and Vulture) means its entries choose topics - headline, link, date, the house
   count - and its excerpt never reaches the writer (step 5a's `rss_summary`); `read_text`
   means its excerpt may.

   Since CF-0060 each entry of `sources.rss.feeds` is an object, not a bare URL: `url` is
   the unit of collection, `site` is the domain the entries link to,
   and `house` is the publishing house that owns the newsroom (the unit of counting, step
   4). Read `sources.rss.feeds_note` and `sources.rss.houses` once - Variety, Deadline and
   THR are all one house (PMC); Vulture is the other (Lupa Systems).

   `--days` is a real depth request now (CF-0007, fixed 2026-09-02): the script walks each
   trade backwards — WordPress REST at 100 posts a request where the site allows it,
   `?paged=N` on the feed otherwise — until the window is covered. It is no longer a filter
   over a front page that only ever held ~3 hours of news. Roughly what to expect against
   the three PMC trades (measured 2026-09-03, CF-0059): **`--days 3` ≈ 650 entries in
   11 requests (~16s, 3–4 per feed), `--days 14` ≈ 2100 entries in 25 requests (~48s, 7–9
   per feed)**; Vulture adds ~20 entries in exactly 2 requests at any `--days` (CF-0060,
   measured the same day: 672 entries / 13 requests on `--days 3`). The per-feed ceiling
   `--max-requests-per-feed` defaults to 12, which is the
   measured 14-day need of 9 plus a third; it is an emergency stop, and a healthy run never
   touches it. Redirect the output to a file and read that rather than letting a megabyte of
   JSON land in the transcript. `--summary-chars` trims the payload
   further if you need it to, but do not go below ~400 by reflex: the verbatim rights-holder
   string step 7 needs ("Ketchup Entertainment's theatrical rescue of Example Studios Animation's
   ...") often sits late in a summary, and cutting it off turns a real `rights_holder` into a
   `null`.

   **Read `warnings` and `coverage` before you read `entries`.** `coverage` reports per feed
   what was actually reached: `requested_days` vs `covered_days`, `window_complete`, and
   `stopped_because`. If a feed reports `window_complete: false`, say so in your step-8
   report — the pool is smaller than the flag implies, and that is a fact about the batch,
   not a detail. One standing exception: **Vulture's row always reads `strategy:
   rss-paged`, `requests_made: 2`, `stopped_because: source_exhausted`, `window_complete:
   false`, ~1 day covered** - its FeedBurner feed is the front page only and ignores
   `?paged=N` (see the feed's `note` in the channel config). That is the expected shape of
   that feed, not a shortfall to report as a finding; mention it in one clause and move on.
   Anything *else* on that row (a fetch error, 0 entries) is a finding. `source_exhausted`
   on a PMC trade means the source genuinely has no more; `fetch_error`
   means treat the batch as incomplete (see Notes). `max_requests` on a configured feed at a
   normal `--days` is a finding, not a knob to turn: it means the default ceiling in
   `scripts/fetch_rss_news.py` is under the real need. Re-run this batch with a bigger
   `--max-requests-per-feed`, and say in your step-8 report what the feed actually needed
   so the constant gets re-derived from a measurement (CF-0059) - do not leave the fix on
   a flag nobody sees.

   **ExampleTech: the pool is the script's, not yours (CF-0772).** On 2026-10-16T0702Z the
   feeds gave 236 entries and the pool read off them by hand held 21 candidates; the refill
   emptied it in one round. For ExampleTech you do **not** extract candidates by reading:
   right after the fetch, build the pool from the whole RSS output -

   ```bash
   .venv/bin/python scripts/candidate_pool.py build <batch-dir> \
     --rss <batch-dir>/work/rss.json --channel <batch channel> --write
   ```

   It writes `<batch-dir>/work/candidate-pool.json` (step 5's pool and step 5a+'s): every
   entry that names a product, a model or a company is a candidate, entries naming one subject
   are one candidate (`name`, `name_kind` `product` / `names` / `company`, `headline`,
   `headlines[]`, `rss_links`, `vendor_links`, `pool_id`), shop offers and entries naming
   nothing are dropped and counted (`dropped`). `distinct_rss_houses` / `distinct_rss_entries`
   are computed there, by the feed that carried each entry: a company's own feed (`kind:
   vendor` in `sources.rss.feeds[]`, CF-0770 - Apple Newsroom, The Keyword, OpenAI News...)
   adds **no** house - its post rides along in `rss_links` / `vendor_links` as the topic's
   lead for `vendor_page`, and a candidate only such a feed carries has 0 houses
   (`vendor_only`) and scores on its views. Do not recount houses with `score_candidates.py
   --houses`, and do not add, drop, merge or rename candidates in the file - which entries
   are candidates is the script's. Expect ~170 candidates on a weekday's three days (0702Z's
   feeds: 236 entries -> 170; 1854Z's: 221 -> 161).

   **Your one decision over the pool is scope.** List it once
   (`.venv/bin/python scripts/candidate_pool.py list <batch-dir>` - one line a candidate:
   `pool_id`, houses, entries, kind, name, headline) and mark, in one call, every candidate
   outside `scope.content_type` or inside `scope.exclude` - politics, science that is not
   technology, a film or a TV show, a feed's own event or newsletter ("Disrupt 2026", "The
   Download"), a person's essay, a crypto story:

   ```bash
   .venv/bin/python scripts/candidate_pool.py mark <batch-dir> \
     --out-of-scope p009="MIT's newsletter, not a story" --out-of-scope p037="politics" ...
   ```

   The reason is required and stays in the file; a marked candidate is never scored and the
   refill never takes it. In doubt leave it in - the threshold and the fact rule judge it.
   The names come off the headline's capitals, so a few are clumsy ("Chromium Google", "Mess"):
   a clumsy name of a real tech story stays in; a name that is no subject at all is out of
   scope with the reason "no subject". The rest of step 2 below (reading the entries, the
   houses by `--houses`) is the other channels'; for ExampleTech only its rights-holder
   sentence applies, read off `headlines[]`.

   Read the entries and extract candidates. **A candidate is not only a TV series.** As of
   2026-08-31 this channel covers series, film, animation, production stories and cinema
   celebrity news — read `scope.content_type` and `scope.exclude` from the channel config
   rather than assuming, since that list is where the scope actually lives.

   A candidate is anything with **a specific moment or claim to build a video around**: a
   title, a production story, a named figure in film. What disqualifies a candidate is
   vagueness, not category. "A cast member said something surprising about a scene" is a
   candidate; "a studio reorganised its distribution arm" is not, whatever it is about.

   Respect `scope.exclude`. The trades carry a great deal of sport, music and politics that
   has nothing to do with film — the previous narrow rule filtered those out as a side
   effect, and the widened scope does not.

   A candidate counts if a feed entry names it explicitly. For each candidate keep the
   list of entry links that name it, and from those links derive **two numbers**: the
   distinct entries (informational) and the distinct **publishing houses** (what step 4
   scores). Don't attribute a link to a house by eye - the map is in the channel config and
   the module reads it:

   ```bash
   .venv/bin/python scripts/score_candidates.py --houses <link> [<link> ...] --channel-config <channel> \
     --rss <batch-dir>/work/rss.json
   # -> {"distinct_rss_houses": 2, "houses": ["lupa", "pmc"], "distinct_rss_entries": 4,
   #     "vendor_feeds": [], "unattributed_links": []}
   ```

   Three Variety/Deadline/THR entries on one story are **one** house (all PMC, CF-0046);
   one Vulture entry next to them makes two. Always pass `--rss` (the fetch above): a link
   is the house of the **feed that carried it** (CF-0753) - an aggregator such as Hacker
   News links its entries to the story itself (research.meta.ai, citizenlab.ca), so its
   link's domain is on no feed's `site`, and before CF-0753 such a link killed the call
   (example-tech 2026-10-15T1854Z, three candidates). The domain decides only a link the
   fetch does not hold; a company's own feed (`kind: vendor`) adds no house
   (`vendor_feeds`). Pass only the feed entries' own links. A link that neither the fetch
   nor a `site` places is counted as nothing, listed in `unattributed_links` and warned on
   stderr - say so in your step-8 report (the config may have fallen behind the feeds, or a
   link that is no feed entry got into the list).

   Also note whether the entry gives a rights holder (feeds like Variety/Deadline routinely say "ExampleStream has...", "Example+ greenlit...", "Example Network's..." — capture that string verbatim when present, otherwise leave `rights_holder` null; don't guess).

3a. **The fact before the search (CF-0823) — free, and first.** The scoring pass below pays
   one `search.list` a candidate, and the fact rule of step 5a used to be asked only after
   it: over 04-20.10 ExampleTech paid the search for 24 candidates the rule then refused with
   `no_fact` (Character.AI five times in five batches). So the candidates step 3 is about
   to search are asked for their fact first. Take the same candidates step 3 names below
   (the first ~20; **ExampleTech:** `candidate_pool.py list <batch-dir> --limit 20`) and
   write each as a **draft topic** into `topics[]` of the batch file - step 7's schema, the
   `topic_id`, `title_ref` exactly as step 5a needs it (`name`, `kind`, `type`, `person`,
   `parent_work`, `rights_holder`... - the same rules, below), `evidence.sources` /
   `evidence.rss_links` (the leads), **no `signal` yet** - then:

   ```bash
   .venv/bin/python scripts/fact_probe_topics.py <batch-dir> \
     --rss <batch-dir>/work/rss.json --before-scoring --write
   ```

   It takes only the drafts with no `signal.popularity_score` and puts them through step
   5a's fact search as it is (persons, the probe, Wikipedia / Wikidata / the batch's news /
   the company's own post, the rule) - not the support text, the publish registry, the pool
   or the cut, which stay step 5a's. Before that it reads the channel's **memory of `no_fact`
   refusals** (`scripts/no_fact_memory.py`, `pipeline/<channel>/no-fact-memory.json`, out of
   git): a candidate refused with `no_fact` in the last `scope.no_fact_memory_days` days (3
   when the channel says nothing; 0 turns it off) is held back without a probe. A draft
   without a fact - or held back - leaves `topics[]` as a `no_fact` row of `skipped_topics[]`
   with `before_scoring: true` (a held one carries `fact_memory`: the batch, date and
   subreason it was refused with); the rest stay, marked `prescreen`, and are the only ones
   step 3 searches. An unreachable source refuses nobody here either: such a draft stays and
   is scored. Only `no_fact` is remembered and a remembered refusal is never renewed by the
   batches it holds a candidate back in, so a story whose fact appeared since is asked again
   after the days run out; a topic that has a fact is never held back (the user's rule:
   hype repeats are not limited). `--write` adds every `no_fact` of a pass - this one's and
   step 5a's - to the memory (`scripts/no_fact_memory.py <channel>` prints what it holds).
   The same pass reads the channel's **memory of empty pools** (CF-0876,
   `scripts/thin_pool_memory.py`): a work the Researcher refused `pool_too_thin` at **0
   clean shots** (of at least one indexed source) in the channel's batches of the last
   `scope.thin_pool_memory_days` days (3; 0 turns it off) is held back without a probe or a
   search - it leaves as `pool_too_thin` with `thin_pool_memory` (the batch, the weak
   shots, how many refusals) and `before_scoring: true`, and the refill of step 5a+ does not
   pick it (`refill.thin_pool_skipped`). Nothing is written for it: it is read out of the
   earlier batches' `03` / `01b` / `01`. A work the shared pool took a new source for since
   (one none of the refusing batches had) goes through as usual (`prescreen.thin_pool_memory
   .released`); a work with one clean shot or more was thin, not empty, and is never held.
   Do not put a held work back by hand (`scripts/thin_pool_memory.py <channel>` prints the
   memory).
   The batch carries the ledger as **`prescreen`**: `passes[]` (`drafts`, `probed`,
   `held_by_memory[]`, `refused_by_probe[]` with each one's `subreason`, `passed`,
   `unsettled`), `memory` (`days`, `path`, `live_entries`) and `totals` (`prescreened`,
   `refused_by_probe`, `refused_by_memory`, `skipped_by_memory_at_refill`,
   `filtered_before_scoring`, `search_calls_saved`, `api_units_saved`) with its
   `summary_line`; the day's `search_quota` shows the same saving on the scoring article's
   row as `saved_search_calls` (`scoring_saved`). Do not search a candidate this pass
   refused, and do not put it back.

3. **Gather per-title signal (YouTube) — the scoring pass.** For each draft step 3a left in `topics[]` (the candidates are the first ~20 before scoring, to control API usage - the refill of step 5a+ takes the pool past it until the probe has judged the channel's `scope.min_scored_candidates`, CF-0789; **ExampleTech, CF-0772:** the first ~20 candidates of the pool in its order, `out_of_scope` ones skipped - `candidate_pool.py list <batch-dir> --limit 20` prints exactly those; the search is the candidate's `name` as it stands, except a `company` candidate, whose search is the company and the story's object as the headline names it in two or three words - "ExampleStream layoffs", not "ExampleStream", or the company's whole week of videos is scored as the story):
   `.venv/bin/python scripts/fetch_youtube_signal.py "<title>" --days <scope.popularity_window_days>`
   Keep the returned video titles/descriptions/view counts — this is your evidence base for scene reasoning in step 6, not just a score input.
   **The search cache (CF-0824).** `fetch_youtube_signal.py` answers a query it asked within
   the TTL from the channel's cache (`<pipeline>/<channel>/youtube-search-cache.json`, out of
   git, shared by the channel's batches; found by the batch of `RUNLOG_BATCH`, or
   `--channel <channel>`): 24 h for this scoring pass, 72 h for the footage passes (5b and the
   supplement) - the channel's `scope.search_cache_scoring_hours` /
   `scope.search_cache_footage_hours`. A cached answer is not a `search.list` call and is not
   charged to the day's quota: the output's `searches` counts real calls only and
   `cached_searches` the rest; the `search_quota` block keeps them as
   `cached_search_calls`. `videos.list` is never cached, so the view counts are always
   today's. `--no-cache` asks YouTube anyway (only when a cached list is known to be wrong).
   The score goes onto the draft (`signal.popularity_score`, step 4) - a draft step 3a let
   through and nobody scored stops step 5a (`fact_probe_topics.py` refuses the batch, CF-0823).

   **No `--facets` here.** The CF-0038 view scale is calibrated on the bare query's view
   sum, so this pass is one search per title and its sum is what step 4 scores. The
   facet fan-out that widens the *footage* pool is step 5b, after the cap, and its view
   sum is a different quantity that must never be fed to the score.

4. **Score each candidate (0–100 composite).** Don't hand-roll the arithmetic — call the module, which carries the calibrated constants; the house ceiling is the channel's (`sources.rss.house_ceil` of `channels/<channel>.json`, CF-0627 — there is no default one):

   ```bash
   .venv/bin/python -c "import sys; sys.path.insert(0,'scripts'); import score_candidates as s; \
     c = s.load_channel_config('<channel>'); \
     print(s.popularity_score(<views_after_exclusions>, <distinct_rss_houses>, <distinct_rss_entries>, \
                              rss_ceil=s.house_ceil_of(c)))"
   ```

   Both scales are **absolute**, not normalised inside this batch's pool (CF-0038,
   implementing the decision in CF-0005). That is the whole point: a score means the
   same thing in every batch, so a pool of three is measured with the same ruler as a
   pool of thirty, and `scope.min_popularity_score` filters on popularity rather than on
   rank position.

   ```
   youtube_view_signal = clamp(0, 100, 100 * log10(V / 5_000) / log10(10_000_000 / 5_000))
   rss_mention_signal  = clamp(0, 100, 100 * houses / 2)
   popularity_score    = weighted sum via scope.scoring_weights (0.6 / 0.4)
   ```

   `V` is the view sum **after** the false-positive exclusions below; an unfiltered sum
   is a different quantity and the constants are not calibrated for it. `houses` is the
   number of distinct **publishing houses** from step 2 - not entries, not feeds. Reading
   of the numbers: 5,000 views over the whole 7-day search is the floor at which a title
   has no video audience worth filming; 10M is the ceiling, just above the strongest
   genuine signal ever measured here (7.16M), so a viral outlier clamps at 100 instead of
   redefining the scale for everyone else; every 10x in views is worth 30.3 points; 2
   houses means every independent newsroom in the pool ran the story (CF-0060 - PMC's
   three trades are one house, so the ceiling is the number of houses in the config, and
   it is deliberately *not* the number of feeds). One house scores 50, not 0 — a
   candidate is discovered *by* an RSS entry, so one house is the baseline, and scoring
   it 0 would put back the zero floor this scale exists to remove.

   View scale calibrated 2026-09-02 across all 42 candidates in the five existing batches
   (`tasks/CF-0038-absolute-log-scoring.md`); house counting and the threshold re-derived
   2026-09-03 over those five plus a fresh pool (`tasks/CF-0060-*.md`); both pinned by
   `tests/test_scoring_scale.py`. **Do not adjust the constants inside a batch run.** If
   the scale looks wrong on real data, say so in your step-8 report and leave it — moving
   a floor or a ceiling silently makes every past score incomparable.

   Two consequences worth knowing before you read your own output: on a healthy batch
   (deep RSS window, ~12 candidates) most candidates clear the threshold and
   `scope.max_titles_per_batch` is what actually limits the batch, not the threshold. And
   coverage alone never clears it any more: one house with no video audience is 20.0,
   both houses 40.0, against a threshold of 45 - a one-house story needs ~119k views, a
   two-house story ~9.4k. Before CF-0060 three PMC entries reached the old threshold of
   40 on their own; that was the hole `CF-0046` measured, and it is closed by counting
   houses, not by a special case. Don't invent your own cutoff on top of this either.

**False positives in the YouTube signal are computed, not eyeballed (CF-0272).** A search
answers `q` through the channel and the network as readily as through the words: "Heated
Rivalry" matched an MMA clip with 2M views and a speedrunning channel; "Wren Hollow"
matched five Example Max promos for *Harbourlights* and *WAR*, 5.2M views of another show inside
Wren Hollow's 10.6M. Do not decide this by eye and do not leave the decision in your
reasoning — on 2026-09-18T1058Z seven uploads were excluded across four topics and the
artifact recorded none of it. Run the rule over the scoring pass's own output:

```bash
.venv/bin/python scripts/topic_relevance.py /tmp/signal-<slug>.json \
  --name "<title_ref.name>" [--parent "<parent_work>"] [--kind person --person "<person>"]
# -> {"videos_seen": 53, "named_the_work": 43,
#     "youtube_views_after_exclusions": 5039535, "excluded_evidence": [ ... ]}
```

`youtube_views_after_exclusions` is the number step 4 scores; `excluded_evidence` is copied
into the topic's `evidence` **as it comes**, including when it is `[]`. The field is not
optional: a topic without it does not say whether anything was taken out of its sum, and
`footage_candidates.py --check` fails the batch for it.

The rule is "the video names the topic's work somewhere in its own metadata" — title, else
description, else the channel's name, never the network. It does not know about instalments
or years, so a genuine false positive it cannot see (a clip from *Resident Dread: Extinction*
(2007) under the 2026 reboot, as on 2026-09-17T1901Z) is still yours to add to
`excluded_evidence`, with its own reason. Add to the list the script prints; do not replace it.

5. **Filter.** Drop titles below `scope.min_popularity_score` - take their drafts out of `topics[]` (their score stays in the candidate pool below). Do **not** cap here: what survives the threshold goes into step 5a in descending score, and the cut is the shortlist step 5a makes. `scope.max_titles_per_batch` (5) is still the batch's target, but it is applied **after compliance** (CF-0265) — a topic compliance takes off the batch has to be replaceable, and on 2026-09-16 Spire-Runner took a slot, compliance took it off, and there was no replacement.

   **Write the candidate pool (CF-0756).** Every candidate step 2 found - the ones you scored
   *and* the ones past step 3's cap that you did not - goes into
   `<batch-dir>/work/candidate-pool.json`; step 5a+ refills the batch from it:

   ```json
   {"candidates": [
     {"name": "RTX Spark", "popularity_score": 66.3, "distinct_rss_houses": 1,
      "distinct_rss_entries": 1, "rss_links": ["https://..."], "topic_id": "lf-2026-10-15-004"},
     {"name": "Apple Vision Air", "popularity_score": null, "distinct_rss_houses": 2,
      "distinct_rss_entries": 3, "rss_links": ["https://..."], "topic_id": null}
   ]}
   ```

   `popularity_score` is the step-4 score of a candidate you scored (above the threshold or
   below it) and `null` for one you did not search yet; `topic_id` is set for the ones that went
   into the draft. A scored candidate is never scored again.

   **ExampleTech (CF-0772): the pool is already written - do not write it by hand.** Put
   your scores and topic ids into it, every scored candidate, one call:

   ```bash
   .venv/bin/python scripts/candidate_pool.py mark <batch-dir> \
     --score p001=89.0 --topic p001=lf-2026-10-16-001 --score p007=23.5 ...
   ```

   (`KEY` is the `pool_id`, or the exact `name`.) A candidate the pool carries under a name
   you searched differently ("ExampleStream" searched as "ExampleStream layoffs") is marked by its
   `pool_id`; the topic's `title_ref.name` is what you searched.

5a. **The fact, before the footage — persons, the fact search, the shortlist (CF-0264, CF-0438).**
   The order of this stage is **fact check (3a) → scoring → persons → fact search → shortlist**,
   and this step is the middle two: the drafts step 3a let through and step 3 scored are
   judged again here, now with the support text, the publish registry, the pool and the cut
   (the fact search over them is the same and its answers are read through the same
   caches). It is not optional and not a weight: a topic with **no fact that passes the
   fact rule** is never selected.

   **CF-0438 (grill of 2026-09-29).** The fact is no longer only "how it was made": any kind —
   production, box office, release, casting, reception, a scandal, news about the people in
   it — from the batch's channel's list of outlets, `<root>/channels/<channel>/fact-sources.json`
   (CF-0627; its `kinds` are the channel's kinds of fact) (Wikipedia, every
   section; Variety, THR, Deadline, IndieWire, Screen Daily; AP, Reuters, BBC, the Guardian,
   the NYT; Box Office Mojo, The Numbers; creator interviews with direct speech; studio press;
   tier 2 Collider / ScreenRant / EW only with the original's link; never IMDb trivia, Reddit,
   fan wikis, tabloids). Each candidate is checked by `fact_rule.check_candidate` against the
   four requirements (a listed source with a link; specifics, not an opinion; adds what the
   topic's own news does not say; about a real person — a major outlet and "X reported
   that…"). The topic leaves only when **not one** candidate passes and every source answered.

   Why it is here and not at the writer. The channel's stance (`channels/<channel>.json`,
   `production_fact_refusal`, and `channels/example-film/stance.json`) is "retell the story and
   add one concrete, verifiable fact of **any kind** that the story does not carry" (CF-0439;
   until then "…about how the thing was made"), over the whole of Hollywood — people, films,
   series, animation; no fact, no video. Which kind the fact is makes it neither better nor
   worse: the candidates are ranked by whether they pass, the source's tier, a number and an
   attribution, and the kind (the order of the channel's `kinds`, `fact_search.kind_order`;
   production first for example-film) only breaks a tie
   between candidates equal on all of those. On 2026-09-16T2148Z the rule took three of four
   topics off the batch **after** the indexer had downloaded and indexed six sources for
   them — ~36 minutes of 48; so the question is asked here (grill of 2026-09-17, decision of
   CF-0260). The refusal at the writer stays as the backstop.

   The draft batch file is step 3a's (step 7's schema, without `evidence.youtube_video_ids` —
   those come in 5b); after step 5 it holds every scored candidate above the threshold in
   `topics[]`, then:

   ```bash
   .venv/bin/python scripts/fact_probe_topics.py <batch-dir> \
     --rss <batch-dir>/work/rss.json --write
   ```

   What it needs from you in `title_ref`, and will not guess:
   - **`kind`**: `"work"` or `"person"`. The script refuses the whole batch (changing nothing)
     if a topic does not say, because what the fact is looked up for, and how strictly it is
     judged, depends on it.
   - **A science story** (ExampleScience, CF-0662) has no work: its `title_ref.name` is the
     story's subject as its footage would name it - the mission, spacecraft, object or
     phenomenon ("Artemis II", "James Webb Space Telescope", "Comet C/2025 A6 (Lemmon)",
     "Northern lights"), not the headline - and its **`type`** is one of `mission`,
     `spacecraft`, `telescope`, `celestial_object`, `phenomenon`, `discovery`, `place`,
     `science_story`. **`subjects`** lists the other names the headline gives the same
     subject ("Webb", "JWST", "aurora", "Orion"); never an agency ("NASA", "ESA") or a
     generic word ("space", "comet") - those are dropped anyway, they would keep every
     upload of the channel. These are the forms its uploads are kept by
     (`topic_relevance.story_forms`): the trailing number is part of a mission's name
     (an "Artemis I" upload is not Artemis II footage; "Artemis 2" is), a parenthesised
     name counts on its own. `rights_holder` / `network` stay null - the house the story
     came from is what reads the agency's channels deep (step 5b).
   - **`type`** (`tv_series`, `film`), **`year`**, **`season`**, **`network`** (falls back to
     `rights_holder`) — what the topic is known to be. The probe checks the article it found
     against the **type**; year and network only steer the search. A search that resolves to
     the wrong work is `wrong_article` and counts as no fact (2026-09-16: "Wren Hollow"
     resolved to the film series, not the Example Network series, and that fact would have passed every
     checker downstream while being about the wrong thing).
   - **`parent_work`** for a spin-off or a sequel with no article of its own — **only** when
     the topic's own news name it. `Rennick: Quill` has no article; `Rennick (TV series)`
     has the fact, and the headlines say "Prime Video's New 'Rennick' Spinoff", so the parent
     is honest and the writer's lead-in says "in the main series…". A parent the leads do not
     name is dropped from the question, and the script says so.
   - **`person`** for `kind: "person"`, plus **`name`**: the work the video is about when the
     topic's own news leads **name** one (the headlines in `evidence.sources`, plus the
     summaries when you pass `--rss`), otherwise the person's own name. **A story about a
     person is the channel's story in its own right** (CF-0439, `stance.json` → `persons`):
     no work is needed, and `person_without_work` (CF-0260) is no longer applied. What stays
     is the other half of that rule — never fill `name` from a filmography: "Michael J. Fox
     received an ovation at the Emmys" plus a fact about the shooting schedule of *Shrinking*
     is a fact about the wrong thing. The script checks the work's own string against the
     leads; a work they do not print is taken out of `name`, the person is looked up instead
     (by name alone — no `type` / `year` / `network` held against a biography), and the stage
     report says which work was dropped. When the subject is the person, **every** candidate
     is a claim about a real person (`about_person: true`) and has to meet the rule's stricter
     requirement: a major outlet, never a rumour, put as "X reported that…" — that is not
     relaxed for a person story, it is what a person story stands on.

   What it does: persons first, then one `fact_probe.py` subprocess for the whole list in
   score order (shared pacing; ~1 s a request, 3 a title, 6 with a parent — 15 candidates is
   about a minute and costs no API quota). The probe now only **resolves the article** (its
   search, parent fallback and wrong-article guard). Then `scripts/fact_search.py` looks for
   the candidates, per topic:
   - **Wikipedia, every section** of the article the probe resolved (`ok`, `no_section`,
     `no_candidates` — never a `wrong_article`; since CF-0439 the probe's `no_section` means
     "nothing but plot and cast", not "no Production", and its `sections` are never read for
     a verdict — this stage reads the article itself): one more request a topic on
     `api.wikimedia.org` (≥ 1 s apart). Every prose sentence with a number, a date or a name,
     its `kind` from the section (Box office, Release, Reception, Casting, Production /
     Filming / Development, Controversy…), as `primary_url` its first citation the channel's
     fact-sources put on tier 1 and not on `do_not_take` (a vendor's or regulator's page cited
     after the press), else its first non-Wikipedia citation (CF-0788). Twelve are kept a
     topic, a round-robin over the kinds; where the list has Wikipedia itself on tier 2
     (example-tech, example-science) the sentences with a tier-1 `primary_url` go first before
     that cut, so a press-cited dozen no longer pushes out the one the rule would pass.
     Plot, cast lists, episode tables and references are not read.
   - **The batch's own news** (`--rss`): other posts that name the work, on a listed host,
     with `attribution: "<outlet> reported"`. The topic's own leads are not candidates — they
     are the news the fact has to add to. Free: no request. **Only a post of a `read_text`
     feed** (CF-0638, `channel_data.support_feed_urls`): a `headline_only` feed's post gives
     no candidate, its headline included — example-film's four are all `headline_only`, so its
     facts are Wikipedia's (`docs/news-facts-2026-10.md`: 0 of 48 topics lost for it).
   What is **actually asked today** is those two. AP, Reuters, BBC, Guardian, NYT, Screen
   Daily, Box Office Mojo, The Numbers, studio press and interviews are allowed by the list
   but not searched: they reach a batch only as Wikipedia's cited `primary_url`, or as an RSS
   post on a listed host (the channel's feeds are Variety, Deadline, THR — Vulture is not on
   the list, so its posts are never candidates). So pass `--rss` always: without it only
   Wikipedia is read.

   Then the cut to `scope.shortlist_size` (8 when the key is absent — read, never written by
   this repo). The channel's switch is `production_fact_refusal.enabled`: off, nothing is
   dropped for want of a fact (the candidates are still written).

   **The cut is on hype × pool (CF-0325, decision Q8 of the grill "формат канала",
   2026-09-29).** Before cutting, the script asks `scripts/pool_coverage.py` what
   `shared/footage` already holds for every viable topic — by **title / franchise**, never by
   `video_id`: the topic's name, its `parent_work`, the person, and the part of the name before
   a `:` ("Rennick: Quill" → "Rennick"), as whole words in a source's title in
   `index.json`, or through the earlier topic the source was fetched for (`note`: "batch X,
   topic Y"). The matched sources are screened with the Video Editor's own pre-cut gate
   (`footage-indexer/scripts/pool_depth.screen_shots`, run by `scripts/pool_screen.py` under the
   indexer's venv), **minus shots already spent on a finished video**
   (`pipeline/<channel>/retired-shots.json`, CF-0397). Then:

   ```
   coverage   = min(1, usable / 60)            # pool_depth's floor: at 60 the indexer stops fetching
                (min(1, sources / 2) when the gate could not be run - said in a note)
   rank_score = popularity_score × (1 + 0.5 × coverage)
   ```

   The pool is a **bonus bounded at ×1.5, never below ×1**: a fresh hot topic with nothing in
   the pool keeps its whole score, so the pool never takes a topic off the batch and never
   brings in one that is not in today's news (the factory does not chew its archive); a fully
   pooled topic beats a pool-less one only when its hype is at least 2/3 of the other's. The
   views come from the hype; the pool breaks near-ties and lifts a topic across the line.
   Every viable topic carries the answer as **`topics[].pool`** (`sources`, `shots`,
   `retired`, `usable`, `measured`, `coverage`, `coverage_by`, `factor`, `rank_score`,
   `phrases`, `matched[]` with `by: ["title" | "topic"]`, `host_show_skipped`,
   `host_show_error`), the reserve rows keep it inside
   `topic`, `batch.selection.pool` says whether the pool reordered anything, and `topics[]`
   is in `rank_score` order (`--check` checks that). A pool source that is somebody else's
   host show (CF-0817, `host_show.judge()` asked as the indexer's pool reuse asks it) earns
   no bonus: it is left out of the count and its id goes to `pool.host_show_skipped`; one
   kept under an exception counts with `host_show` on its `matched[]` row. A pool that cannot be read is a note, not
   a refusal: the cut falls back to the score. `--no-pool` cuts on the score alone.
   Freshness is not this step's job and it waits for nothing: what the hunter finds today
   reaches the pool through the ingest queue (CF-0324) — this run asks what is already there.
   The measurement behind it is in `docs/selection.md` ("Hype × pool").

   **Already made (CF-0019).** Between the persons and the probe the script compares every
   topic with the videos the factory has made and the user accepted
   (`scripts/published_before.py`: `<root>/publish/acceptance-log.json`, latest verdict
   per slug, `publish/<slug>.md`, each video's topic read back out of its source batch's
   `01`). **The same work told from the same news** — the topic shares a news article URL
   with the made video's topic — leaves with `already_published` before it is probed, and
   its slot goes to the next topic by score. **The same work with another story**, the made
   video's news unknown, another season or another installment of the franchise stays and
   carries **`topics[].published_before`** (`slug`, `video`, `topic_id`, `batch`,
   `relation`: `same_work` / `other_season` / `same_franchise` / `same_work_unverified`,
   `story`: `same` / `different` / `unknown`, `shared_sources`), and the script prints a
   `WARNING published_before` line for it. A video the user rejected is not made. Whether a
   new story about the same work should leave too is the grill's to decide (2.0.4) — until
   then only the same story is dropped; do not drop a marked topic by hand.
   `selection.published` holds `videos`, `unresolved`, `errors`, `dropped`, `marked`.
   `scripts/published_before.py <batch-dir>` prints the same decision without writing.

   **Every `reason_code` in `skipped_topics[]` is a word of the topic funnel's vocabulary**
   (root `shared/runlog/funnel.py` `FUNNEL_CODES`) - the ones the scripts write, and the
   ones this file names for a hand-made refusal. Never coin one (CF-0708): `check_scenes.py
   --check` runs `scripts/skipped_codes.py`, which refuses a code outside the vocabulary
   and an old word (`no_production_fact`, `no_dated_source`) the funnel only reads in old
   batches, naming the code to write instead. A code this repo's own scripts write always
   passes it - read from the scripts themselves, not from a list - including
   `footage_evidence_quota` (CF-0317, below), which the funnel counts as a loss of the topic
   (CF-0714).

   The codes it writes into `skipped_topics[]`:
   - `already_published` (CF-0019) — the same work and the same news as a video already
     made; the row carries the match under `published_before`;
   - `person_without_work` — **not written since CF-0439** (a person story is the channel's
     own); batches before 2026-09-29 carry it and are still read;
   - `no_fact` (`no_production_fact` before CF-0438 — old batches are still read under it,
     it is never written again) — no candidate passed the fact rule and every source answered.
     The row carries the probe's answer (`fact_probe`: which article, which outcome), where
     the stage looked (`fact_search.asked`) and every checked candidate with its failures
     (`fact_candidates[].check.failures`: `no_specifics`, `retells_news`,
     `source_unlisted`, `person_unattributed`…);
   - `no_support_text` (CF-0551) — the topic has no support text for its own event: no
     Wikipedia article of its own and no company post that names it (CF-0771, below), or the episode its news is about (a finale, a premiere,
     "season 2 episode 3") has aired and has no `ShortSummary` yet — Wikipedia writes it
     ~2–3 h after the broadcast — and TVmaze has no description of it either (CF-0636).
     The row carries `support_check` (what was asked, the event,
     why there was no text). It leaves before the cut, so the next topic by rank takes the
     slot;
   - `below_shortlist` — viable, in score order past the shortlist. Unused reserve, not a
     fault of the topic, and recorded because DoD 1.4.4 item 1 allows no silent loss.
     Since CF-0313 (2026-09-22) the row carries its `rank` and the **whole topic** under
     `topic`, because step 5b puts it back into the batch when a slot falls free; do not
     strip either by hand.

   **An unreachable source never drops a topic.** `source_unreachable` means "we could not
   ask", not "this topic has no fact": when no candidate passes and the probe or the article
   read could not be made, the topic stays with `fact_probe.fact_rule.settled: false`, and the
   writer's rule judges it later. A shortlist filtered on `has_fact` would empty itself during a Wikipedia
   outage and the batch would look like a day with no news. If the probe could not be run at
   all, the script says so in a note and drops nobody — that batch was not actually filtered,
   and your step-8 report has to say so.

   Every carried topic keeps `topic["fact_probe"]` (outcome, `article`, `article_url`,
   `candidates`, `parent_work`, what was asked, when, and the rule's decision under
   `fact_rule`) and, since CF-0438, **`topic["fact_candidates"]`** — up to 8 checked
   candidates, best first (passing, tier 1 before tier 2, a number before none), each
   `{text, kind, source, url, [primary_url, attribution, section, headline], check: {passes,
   failures, kind, tier, source_id, about_person}}` — plus `topic["fact_search"]` (`asked[]`
   per source, `error`, `found`, `passing`). The Content Researcher takes its fact from
   `fact_candidates` at step 2 (`fact_rule.best_candidate`) instead of searching again.

   **The company's own post (CF-0757).** A topic with no passing candidate after Wikipedia,
   Wikidata and the batch's news is not dropped yet: the same `fact_probe_topics.py` pass
   reads the official post of the company the story is about - nothing for you to run or
   pass. The post is found in the topic's own news (a lead that *is* the post, or a link
   inside a lead's summary) or in the pool's company feeds (OpenAI News, Google DeepMind,
   Apple Newsroom: an entry that names the work), always on a **tier-1** host of the
   channel's `fact-sources.json` whose `ai_policy.verdict` is `allowed`
   (`source_gate.read_vendor_page`; `unknown` and `forbidden` outlets are never asked, a
   front page is no post), at most 2 pages a topic and 40 a pass, cached in
   `work/vendor-page-cache/`. When the news and the pool carry no tier-1 link at all
   (CF-0810), the pass reads the newsroom index of a company the topic names - a tier-1
   row's `newsroom` (index URLs on its own `allowed` host; the company is named when the
   row's `names` or the index host's word - `porsche`, `google` of blog.google; never a
   service label like blog/news/press, never an everyday word like figure/honor/aurora,
   whose company only `names` name - is a whole word of the work's name,
   the title or a lead) - and reads the release on it whose link text or slug names the
   work (the index counts against the 40); its row says `via: newsroom`, and an index with
   no such release ends in `newsroom_no_match`. Its sentences with a number, a price or a date are candidates
   (`url` the company's page, tier 1) judged by the same rule - a line that only retells the
   news still fails. Write it so `title_ref.name` is the product's name as the company
   prints it (`Gemini 4 Argon`, not "Google's new model"): a feed entry is matched on it.
   `fact_search.asked[]` gets a `vendor_page` row (`outcome` `ok` / `no_candidates` /
   `no_link` / `closed` / `unreachable` / `cap` / `newsroom_no_match`, `pages[]`,
   `closed[]`, `where`, and `via` / `newsroom[]` when an index was read), and a
   `no_fact` reason ends in it, e.g. `searched wikipedia=no_article(0), rss_pool=ok(0),
   vendor_page=closed(0)[blog.google: unknown]` - in your step-8 report name such a topic
   with that bracket: it says which company page was missing or closed.
   `batch["selection"]["vendor_page"]` counts the pages (`sent`, `network`, `topics`,
   `used`, `per_topic`). A page that could not be read never makes a topic
   `source_unreachable`.

   **The company's post as the support text (CF-0771).** On 2026-10-16T0702Z Gemini 4 Argon
   had seven passing facts from deepmind.google and still left `no_support_text`: a product
   launched this week has no Wikipedia article, and the support text was Wikipedia's only.
   Now, for a topic with **no Wikipedia article of its own**, the same pass takes the
   company's own post - the one the fact is read from, found the same way (CF-0810: the
   release found on the vendor's newsroom index too, `support_check.vendor_page.newsroom`),
   through the same door (tier 1, `allowed`) and cache, so it is not asked again - as the topic's support
   text: a `vendor_page` piece (`id` `vendor_page:<outlet>:<n>`, `source: vendor_page`,
   `outlet`, `publication`, `title`, `url`, `fetched_at`, `text` = the post's main text,
   `<article>`/`<main>` without menus, scripts and footers). A post that does not name the
   work is no piece. The state is `ok` and `support_check.detail` says "told from the company's
   own post (<url>)"; `support_check.vendor_page` records what was read. The writer quotes it
   by its `id` like any piece and the claims check finds the quote in its `text` - nothing is
   relaxed: a claim the post does not say has no footing. A topic **with** an article is told
   from the article as before; a closed outlet (`unknown` / `forbidden`), no tier-1 link or no
   post naming the work leaves the old `no_support_text`, its detail ending in the post's
   outcome (`the company's own post: closed (...)`). Nothing for you to run: it is inside
   `fact_probe_topics.py`. `selection.vendor_page.text_used` counts the topics carried on a
   post, `selection.support_text.carried_with_vendor_text` the carried ones with no
   Wikipedia text.

   **Support text (CF-0551).** Since 1.8 every topic the fact rule kept also carries
   **`topic["support_text"]`** — the text its story may be told from, and the only text
   (CF-0546, the user's rule: no invented facts): the work's Wikipedia article whole as plain
   text (`work_article`), its season's article (`season_article` — the one the show's article
   transcludes, `{{:Rennick season 4}}`, else `<Show> season N`), every non-empty episode
   `ShortSummary` of that season (`episode_summary`, with `season`, `episode`, `air_date`), and
   the news leads' RSS summaries exactly as fetched (`rss_summary`) - only of a feed whose
   `use` is `read_text` (`channel_data.support_feed_urls`, CF-0634); a lead of a
   `headline_only` feed (all four of example-film's) gives no piece at all, so a example-film
   topic's support text is Wikipedia's alone. **TVmaze (CF-0636):** for a topic whose leads
   name an episode, the root's TVmaze client (`shared/tvmaze/tvmaze_api.py`, cached in
   `work/tvmaze-cache/`) finds the show — the same name, and the topic's network when it has
   one — and that episode; once it **has aired** by the batch's time its description is a
   `tvmaze_episode` piece (`id` `tvmaze:episode:<N>`, `source` `tvmaze`, `fetched_at`, CC BY-SA
   4.0 — the publisher credits it). An aired episode Wikipedia has no `ShortSummary` of yet,
   or one no Wikipedia episode list names, is `ok` on that piece instead of leaving; a
   synopsis TVmaze wrote before the broadcast is not used. Only for a channel whose
   `fact-sources.json` names the `tvmaze` outlet `read_text` / `allowed` (the client's gate is
   `source_gate.check`); a TVmaze that cannot be read leaves Wikipedia's verdict as it was
   (`support_check.tvmaze.error`). **Wikidata (CF-0637):** for a channel whose list names the
   `wikidata` outlet `read_text` / `allowed`, the root's Wikidata client
   (`shared/wikidata/wikidata_api.py`, cached in `work/wikidata-cache/`) finds the item whose
   English sitelink is the topic's article (the work's for a season; <= 3 requests a topic,
   one lookup for the fact search and the support text) and reads its statements of the
   outlet's `properties`: up to `WIKIDATA_MAX` passing candidates of the channel's kinds in
   `fact_candidates` (`source` Wikidata - not a major outlet, so never for a person topic)
   and `wikidata_statement` pieces (`id` `wikidata:<Q>:<P>:<value>`, one sentence each, CC0 -
   no credit line) in `support_text`. They never change `support_check.state`, and a Wikidata
   that cannot be read is only `support_check.wikidata.error` / `fact_search.asked[]`, never
   `source_unreachable`. Each piece has `id`,
   `kind`, `source`, `title`, `url`, `revision_id`, `revised_at`, `text`. No article of
   Variety / Deadline / THR / Vulture is ever downloaded (their robots.txt disallows the AI
   crawlers by name) — their headline is all this stage takes of them, and it only chooses
   the topic. Any text read from a host other than Wikipedia goes through
   `scripts/source_gate.py` first: the outlet of the channel's `fact-sources.json` must be
   `use: read_text` with `ai_policy.verdict: allowed`, else the read is refused. `topic["support_check"]`
   says `ok`, `no_text` (refused, above) or `unreachable` (Wikipedia could not be asked — the
   topic stays and your step-8 report names it). It is read by `scripts/support_text.py`
   through the root's shared client (`shared/wikipedia/wikipedia_api.py`, cached in
   `work/wikipedia-cache/` for an hour); `--no-support` skips it, for replays only. The fact
   search reads the topic's article through the same client and cache (CF-0559), so the
   article is asked for once a topic; `batch["selection"]["wikipedia"]` counts the requests
   (`per_topic.<topic_id>.network` — what went to Wikipedia; `fact_search` / `support_text` —
   what each sent, cache hits included); `batch["selection"]["tvmaze"]` counts TVmaze's
   apart (`asked`, `refusal`, `sent`, `network`, `topics`, `used`, `per_topic`), and
   `batch["selection"]["wikidata"]` Wikidata's (the same fields; `per_topic` `{item, sent,
   network, candidates, pieces, reason}`).
   `scripts/support_text.py <batch-dir> --topic <id>` prints one topic's pieces without
   writing. `batch["selection"]` counts the
   pass. Re-check after the batch file is complete:

   ```bash
   .venv/bin/python scripts/fact_probe_topics.py <batch-dir> --check
   ```

5a+. **Refill to the target — rounds over the same pool (CF-0756). Not optional: run it after
   every 5a pass, before 5b, until it says `done`.** On 2026-10-15 the first ExampleTech batch
   scored twelve candidates, five cleared the threshold, the fact rule took four off, and the
   batch went on with one topic - the hunter had chosen once and never went back to the pool.
   Now it goes back: while the fact rule leaves fewer than the channel's `scope.target_topics`
   (5) - **or while the probe has judged fewer candidates than the channel's
   `scope.min_scored_candidates` (12 when the channel says nothing - ExampleFilm's level,
   CF-0789)** - the next candidates of the same pool are scored and judged, round by round, within
   `scope.max_refill_rounds` (3) rounds and `scope.max_refill_search_calls` (40) search calls
   on top of the first pass, and never into the day's quota the footage step needs. The rule is
   not softened for it: a refilled topic goes through the same `fact_probe_topics.py` pass.

   ```bash
   .venv/bin/python scripts/refill_topics.py <batch-dir> --write [--searches-spent N]
   ```

   It prints one of two answers:

   - `{"action": "score", "round": k, "candidates": [...]}` - a round is open. For **each**
     candidate: step 3a first (CF-0823) - draft it into `topics[]` with the `topic_id` the
     candidate carries (`title_ref` with `kind` / `type` as 5a needs, `evidence`, no
     `signal`) and run `fact_probe_topics.py <batch-dir> --rss ... --before-scoring --write`;
     then, for the drafts it left only, step 3's bare search (`fetch_youtube_signal.py
     "<name>" --days ...`, no `--facets` - one search call each), step 4's score onto the
     draft, step 5's threshold (a draft below it leaves `topics[]`). Then run 5a again over
     the whole batch (`fact_probe_topics.py <batch-dir> --rss ... --write`) and call
     `refill_topics.py` again. If step 3a refused **every** pick, search nothing and call
     `refill_topics.py` again at once - the round closes by itself (`closed_by: prescreen`).
     If **not one** searched candidate of the round cleared the threshold, do not rerun 5a:
     call `refill_topics.py <batch-dir> --write --none-passed` instead. Calling it again
     without either changes nothing and hands back the same open round.
   - `{"action": "done", "stopped_because": ...}` - go on to 5b with what the batch carries.
     `target_met` (both targets: the topics and the scored count), `pool_empty` (no unevaluated candidate left), `rounds`, `search_cap` or
     `quota` (the day's search calls, less 6 for each target topic's facet run, pay for none).

   Which candidates and how many is the script's, not yours: unscored ones only, best RSS
   signal first (houses, then entries), never a name or id the batch has already judged or an
   earlier round took, never one the channel's `no_fact` memory holds back (CF-0823: the ones
   a round passed over for it are `refill.memory_skipped` and the action's `memory_skipped`); as many as the first pass's yield says it takes to reach the target,
   spread over the rounds left, never past the cap, the quota or the pool. `--searches-spent` is
   the same number you give `footage_candidates.py` (what the quota day spent outside this
   batch). The batch file carries the loop as `refill`: `rounds`, `searched` (the picks, or the
   run log's scoring searches since the refill began when that is more), `added` (topics carried
   now that were not before it) with `added_topic_ids`, `stopped_because`, `below_min`,
   `refused` (all of `skipped_topics[]` by code - `selection` counts only the last pass),
   `round_log[]` (each round's picks, `need`, `yield`, `closed_by`, what it added), `quota`,
   `params` (with `from`: the channel's or the default) and `summary_line`. **CF-0823:** a pick
   step 3a refused costs no search - a round's `searches_planned` is its `picks` less its
   `prescreened`, `searched` and the cap count only what was searched, the yield and the pass
   rate are over searched candidates, and a round takes `ceil(want / survival)` picks
   (`survival` - the batch's share of pre-checked candidates that passed, floor 0.25 - in
   `round_log[]`) within the very same caps. A batch below the
   channel's `scope.min_topics` (3) goes on all the same, and its summary line starts with
   `WARNING below_min_topics`.

   **The scored target and the ledger (CF-0789).** `refill.scored` counts every candidate the
   probe has judged over every pass (topics carried + this stage's refusals) - not
   `selection.scored`, which is the last pass's input only - **and never a refusal step 3a
   made before the search (CF-0823)**: the minimum is met with candidates that were searched
   and judged, the next candidates of the pool make up for the ones the fact took off. A batch at its five topics but
   short of `min_scored_candidates` keeps refilling: a round then takes
   `ceil(scored still needed / pass rate)` candidates, the pass rate being the batch's own
   (scored / evaluated) - within the same rounds, cap and footage reserve. The viable past the
   shortlist are its reserve (`below_shortlist`), which is the point: a slot a later stage
   empties has a topic to take. Stopped short of it, the summary line ends `below the channel's
   min_scored_candidates N: M scored` and `refill.below_scored` is true. `refill.sources` is
   where the candidates came from and what they cost: per feed of the fetch its entries,
   requests and covered days; per house the pool's candidates, out-of-scope, prescreened
   (refused before their search, CF-0823), evaluated (one scoring search each), scored and
   viable; and `totals` with `scoring_search_calls` and
   `scoring_api_units`. A hand-written pool (every channel but ExampleTech) is attributed by its
   `rss_links` against the feeds' `site` - so keep every candidate's links in it.


5b. **Widen the footage pool — three candidate sources per shortlisted title (CF-0129).**
   This step is not optional and it is not your judgement call: a topic leaves this stage
   with **at least three candidate footage ids of different natures**, or with a record in
   the artifact saying how many there were and why there were not three.

   **It runs over the shortlist step 5a produced, and over nothing else.** The probe is free
   and this is not: never spend a facet run on a topic that has no fact behind it. That is
   the whole order — fact check, scoring, persons, probe, shortlist, *then* footage.

   Why it exists. The two-source gate downstream needs two *independent* sources per
   video, and independence is the CF-0080 fingerprint of the downloaded file, not the
   `video_id`: three uploads of one teaser are **one** source (`GyEpwGQIEZw` /
   `SJVmeJaS44s`, distance 1.82), which is how 2026-09-03T2037Z passed the gate on 0 of 4
   videos. You cannot fingerprint a video you have not downloaded, so your job is to hand
   the indexer material that is *differently shot* - a second trailer, a press interview,
   an episode clip, a making-of, behind-the-scenes - and let it pick the two canonical
   ones. Three rather than two: the third is what pays for one of them collapsing.

   **Feeds first, search only where the feeds were not enough (CF-0361, 2026-09-24).**
   The footage the factory keeps is an upload of a studio's or network's own channel, and
   those channels are a registry of ids - the channel's own, `<root>/channels/<channel>/footage-origin.json`
   (CF-0627; `footage_origin.load_config(<the batch's channel>)`). Their uploads are
   read without `search.list`: the RSS feed of every registered channel (0 units), the
   uploads playlist of the topic's rights holder / network, the licensed distributors and
   any channel whose feed already names the work (1 unit per 50), `videos.list` on the
   uploads whose **title** names the work (1 unit per 50). Since CF-0662 the **publishing
   house** a topic came from (its `rss_links` / `sources` by the channel's
   `sources.rss.feeds[].house`) names owners too: a science story out of NASA's or ESA's
   feed reads that agency's official channels deep, as a film's rights holder reads the
   studio's (the feed file's `channels.houses`; one query by hand: `--house nasa`).
   One call for the whole shortlist:

   ```bash
   .venv/bin/python scripts/fetch_channel_feeds.py --batch <batch-dir> \
     --out-dir <batch-dir>/work/feeds          # one feed-<topic_id>.json per topic
   ```

   Why: on 2026-09-23 77 of the day's 91 searches went to footage and the quota ran out
   mid-batch, and what the facet runs of `2026-09-23T1722Z` brought was a political talk
   show for *Paper Dragon* (the idiom), a mobile game for *Delver*, podcasts and a reaction
   channel for *Mormon Wives* - while the rights holders' own channels held 3, 29, 0 and
   45 (*Spire-Runner*, whose search pool had no official upload and died on burned-in text)
   uploads naming the work. Replayed over that batch the feeds cost 54 units and **no
   search**, against the 42 searches (4 200 units) the facet runs cost.

   A feed that does not answer (CF-0661: on 2026-10-10 every `feeds/videos.xml` answered
   404) is read by the same call through yt-dlp - the channel's uploads playlist, flat, 15
   latest, 0 units, no download. The call prints one
   `youtube-feeds-read: RSS a/n (...); yt-dlp b/k; unread c` line and its JSON carries
   `feed_read`; every feed file carries it too and step 5b's `--write` copies it into the
   topic's `evidence.footage_feed_read`. `unread` above zero is said in the stage report -
   those channels gave nothing, and a `fallback_search` topic may owe it to them.

   Only for a topic whose feed file says `"fallback_search": true` (fewer than two
   candidates - it would be refused without a search; on 1722Z: *Mormon Wives*, whose
   Hulu uploads did not name it) spend the facet run - the bare title plus one search per
   facet of the channel (CF-0825): `scope.footage_facets` of `channels/<channel>.json`; no
   key = `scripts/fetch_youtube_signal.py` FOOTAGE_FACETS (trailer, teaser, interview, clip
   scene, behind the scenes - 6 calls, ExampleFilm), `[]` = the bare title alone (1 call),
   a list = 1 + its length (ExampleTech: `["keynote"]`, 2 calls). Do not pass a list of
   your own - the bare `--facets` is the channel's; the output's `facets_from` and
   `searches` say what was spent:

   ```bash
   .venv/bin/python scripts/fetch_youtube_signal.py "<title>" --channel <channel> \
     --days <scope.popularity_window_days> --facets > /tmp/footage-<slug>.json
   ```

   **A science story also asks the archives (CF-0665).** For a channel whose
   `footage-origin.json` names the archive origins (ExampleScience: the NASA Image and
   Video Library, Wikimedia Commons) run, once for the shortlist - 0 YouTube units,
   nothing downloaded, a channel without them (ExampleFilm) gets "nothing to ask" and no
   files:

   ```bash
   .venv/bin/python scripts/fetch_archive_footage.py --batch <batch-dir> \
     --out-dir <batch-dir>/work/archive        # one archive-<topic_id>.json per topic
   ```

   Every file it finds is a direct download (`download_url`, `media_type`, `bytes`) with
   its licence (NASA: public domain; Commons: the file's own `LicenseShortName`) and its
   credit line (`credit`: `NASA/<centre>` or the item's own; Commons' `Artist`). Hand each
   `archive-<topic_id>.json` to `footage_candidates.py` beside the topic's feed file
   (`--signal <batch-dir>/work/archive/archive-<topic_id>.json:<topic_id>`); for a story
   the archive files lead the candidate list. Say in the step-8 report how many each
   archive gave (`evidence.footage_archive_read`) and any `licence_refused` among them.
   The indexer fetches `download_url` directly (FI-1, `fetch_footage.py --archive-json`):
   the file is kept as `nasa-<id>` / `commons-<pageid>`, its licence is read again before
   the download (`licence_changed` when it moved).

   **A Tech topic is recorded (CF-0567).** For a channel whose `footage-origin.json` names
   the `own_capture` origin (ExampleTech; ExampleFilm and ExampleScience get "nothing to
   record" and no files) run, once for the shortlist - 0 YouTube units:

   ```bash
   .venv/bin/python scripts/fetch_own_capture.py --batch <batch-dir>
     # one work/capture/capture-<topic_id>.json per topic, recordings in <batch-dir>/captures/
   ```

   It searches the public Hugging Face API (no key) for the topic's tool (`title_ref.tool`
   / `model` / `name`), keeps the Spaces whose id names it - the vendor's own org first -
   reads each one's card and records only a Space that is running, public and names a
   licence, on its own `*.hf.space` app (the channel's `capture_hosts` rule) **and shows the
   news's subject** (CF-0813, `subject_verdict`: the maker's own org - an exact org, its
   Hugging Face org or the name plus `-ai`/`labs`..., never a longer word that only starts
   with it - is taken; else a stop word in the Space's name or card - game, lander, toy, fan,
   parody, meme, quiz, simulator... - refuses it, and the card's description must name the
   tool or its title name it as a demo/playground/chat; anything else is refused
   `own_capture_other_subject` in `capture_read.refusals` - the 0844Z Tesla Roadster got a
   lunar-lander toy before this), with the Video Editor's recorder (`agents/video-editor/scripts/capture_tool.py`): wait for the app,
   click the first example (or type a short neutral prompt), run it, wait for the output, a
   short scroll. At most 2 recordings per topic and 6 per batch. The recorder's policy
   refusals (`robots_disallowed`, `space_no_licence`, `host_closed`...) are final and land in
   the signal's `capture_read`; a recorder that cannot run (`no_browser`) stops the pass -
   say it in the step-8 report. Hand each `capture-<topic_id>.json` to `footage_candidates.py`
   beside the topic's feed file (`--signal <batch-dir>/work/capture/capture-<topic_id>.json:<topic_id>`):
   the own captures (`own_capture:<id>`, `kind: own_capture`, nature `demo`, `role: base`,
   `capture_file` = the recording) lead the candidate list, and the indexer ingests the
   recording that is already there. On such a channel one own capture alone keeps the topic
   (it meets the refusal floor by itself - our footage, and the editor's two-source gate never
   counts recordings); vendor quotes alone get no such pass. Each own capture also becomes a
   `support_text` piece (`id: own-capture-<capture id>`, `kind: own_capture_record`): our record
   of the Space, the page, the capture time and the completed steps - what the demo's
   "running in a public Hugging Face Space, <owner>/<name>" quotes; never the fact. The vendors' uploads off the official channels are
   `role: proof_quote` (with their `channel_id`) - short quotes, never the base. Say in the
   step-8 report how many topics were recorded and every topic whose
   `evidence.footage_base.only_proof_quotes` is true (`proof_quotes_only`: not a demo).

   **A topic about a listed model gets its demo via API (CF-0690).** For a channel whose
   `footage-origin.json` names the `api_demo` origin (ExampleTech; the others get "nothing to
   ask" and nothing written) run, once for the shortlist, right after the own capture and
   before `footage_candidates.py`:

   ```bash
   .venv/bin/python scripts/fetch_api_demo.py --batch <batch-dir>
     # topic["api_demo_record"] for an ok call, evidence.api_demo_read for every topic,
     # one work/api_demo/api-demo-<topic_id>.json per call (the cache)
   ```

   Only a topic whose own model (`title_ref.tool` / `model` / `name`, then `aliases`) is on
   the channel's `api_demo.models` list is asked - a GPT topic never gets a Gemini demo. **The
   prompts need the user's approval:** while the block has no `prompts_approved: true` (its
   `prompts_note` says "awaiting the user's approval") nothing is asked and every listed
   topic gets `prompts_not_approved`; pass `--prompts-approved` only when the user approved
   the list in this conversation - never on your own. One prompt per topic (the same on
   every rerun), at most `max_calls_per_batch` (3) calls per batch, serial, the block's
   interval and timeout; an answered call is cached and never asked again. No key
   (`GEMINI_API_KEY` in the environment or the root's `.env`) - every topic is `skipped`
   with `no GEMINI_API_KEY (environment or .env)`; a refused answer (SAFETY, RECITATION, a
   refusal phrase), a rate limit (stops the pass) or an API error - a note, no demo, never a
   failed batch. Never print, read or ask for the key: only `key_source` is ever shown. An
   ok call becomes `api_demo_record` `{record_id: "api-demo-<topic>", protocol}` and a
   `support_text` piece (`kind: api_demo_record`, `not_a_fact: true`: "On <date> the factory
   sent this prompt to <model> through the Gemini API: «...». <model> answered: «...».") -
   the footing of an `api_chat` graphic the script may order; **the answer is never a fact**
   and never counts toward the own-graphics floor. Say in the step-8 report how many topics
   got a record and each `evidence.api_demo_read.status` other than `ok` /
   `model_not_listed`.

   Then let the script pick the candidates - do not type ids into the batch file by hand,
   and do not "pick three" by eye from the search output. Hand it every feed file, and for
   a fallback topic the search file **as well** - two `--signal` files for one topic are
   one pool, and the ledger charges only the search (a feed signal says `searches: 0`):

   ```bash
   .venv/bin/python scripts/footage_candidates.py <batch-dir> \
     --signal <batch-dir>/work/feeds/feed-<topic_id>.json:<topic_id> ... \
     [--signal /tmp/footage-<slug>.json:<topic_id>] --write
   ```

   A `--signal` whose file is not there stops the call with `--signal <arg>: no signal
   file <path>` (CF-0198) - it is no longer opened as `<path>:<topic_id>` and reported as
   that.

   When you build the `--signal` list in a shell loop, write each binding **braced and
   quoted**: `args+=(--signal "${f}:${t}")`, `args+=(--signal "${f}:lf-2026-10-25-${k}")`.
   Never `$f:$t` with a letter after the colon - the shell is zsh, and `$f:t...` there is
   `$f` with the `:t` (tail) modifier: it drops the directory and the colon, and the call
   gets `footage-003.jsonvsm-2026-10-25-003` (example-tech/2026-10-25T0934Z). Such a value
   is refused with exit 2 and the cause named, before anything is written (CF-0862);
   rebuild the list braced and run the call again - the topic is not dropped by it.

   **The licence (CF-0662).** Every candidate carries `licence` - what it may be taken
   under: YouTube's own `status.license` (`creativeCommon` reads as CC BY), else an
   official channel's upload or anyone's upload - and `footage_origin` (the
   `footage_origins[].id` of the official channel it is on: `nasa`, `esa`...; null off the
   list). A channel whose `footage-origin.json` lists `licences` (ExampleScience) judges it
   with the factory's rule (`shared/footage_licence.py`): an upload under a licence the
   channel refuses leaves the pool as `licence_refused` in `footage_candidates_dropped`,
   before grouping, and never reaches the indexer; say the count in the step-8 report.
   ExampleFilm lists none - `licence.judged: false`, nothing is refused. The upload's
   **nature** is the channel's kind set too (`footage_kinds`): a science channel's are
   briefing, lecture, interview, animation, b-roll, explainer, mission footage (launch,
   landing, docking, flyby...), trailer; a tech channel's (`footage_kinds: tech`, or a channel
   with the `own_capture` origin that names none - ExampleTech) are our own capture (`demo`),
   the vendor's demo, launch film, product shot, keynote, explainer, interview, trailer; a
   film's are as below.

   Officiality is by the channel's **id** now (`channel_id` on every record): an upload
   of a channel that only *calls* itself a studio is `unknown` and its origin reason says
   so. A regional channel of a registered studio that shows up this way is added to the
   registry by id, with the upload it was read off - never by hand in the batch.

   It drops the uploads that name no form of the topic's work (the same rule as step 4,
   CF-0272), then the uploads whose title names it only by the franchise's stem or parent
   - another installment (CF-0444), then the uploads that are somebody's video **about** the work rather than
   footage of it (CF-0297: fan made, concept, gameplay, edit, reaction, parody, a
   short-form repost, a podcast - the stop words of `config/footage_origin.json`), then the uploads that are
   **longer than the ceiling their nature is held to** (CF-0302), then the uploads whose
   own title says they are a **talk about** the work rather than a cut of it (CF-0309),
   classifies what is left
   by the nature of the shoot, collapses uploads of the same cut into one candidate (this
   is the part that stops "three ids" from being three reuploads), orders the rest
   round-robin across natures - official channels first inside each nature - so the
   indexer's first two attempts are two different kinds of real footage, and writes
   `evidence.youtube_video_ids` plus the parallel `evidence.footage_candidates`. It exits
   non-zero and lists what it could not satisfy.

   What to do with what it says:
   - **`footage_candidates[].origin`** (CF-0297) - `official` / `unofficial` / `unknown`.
     A pool that is entirely `unknown` is not a problem and not something to fix by hand;
     a topic whose *first* two links are `unknown` is worth a line in step 8, because
     that is the shape the batch of `2026-09-19T0116Z` had when it handed the indexer a
     fan concept trailer and a game capture as Silent Tide's two canonical sources. Never
     edit this field, and never re-add an upload the sieve dropped: if the list is wrong,
     the fix is a line in `config/footage_origin.json` (a stop word) or in the channel's
     `channels/<channel>/footage-origin.json` (an official channel) with the title it was read off.
   - **`footage_candidates[].duration_seconds` and the ceiling** (CF-0302, 2026-09-21) -
     how long the upload is, read off `contentDetails.duration` in the footage pass (free:
     `videos.list` is charged per call, not per part) and carried into the artifact so the
     indexer holds the same ceiling without asking YouTube again. An upload longer than the
     ceiling its nature is held to never becomes a candidate: it is dropped here, before
     the round-robin, with `reason_code: "source_too_long"` and the measured length in the
     record. The numbers are the channel's, in `channels/<id>.json` ->
     `sources.youtube.max_source_duration_seconds` (`{"default": 3600, "trailer": 900}` for
     example-film, measured over 93 accepted sources) - change them there, never in the
     script and never by hand in the batch. This exists because on `2026-09-21T0358Z` a
     2 h 14 min news podcast with 46 views (`Lv_GOa6HXVA`, "Lakeside Trailer, Example Pictures
     Leaving California ... SMALL ZERO") was offered as a `trailer` on the strength of one
     word in its title; the indexer downloaded it, was still indexing it 41 minutes later,
     and the topic died with its attempt budget gone. `duration_seconds: null` means the
     API said nothing usable (a live stream, a premiere) and is **not** a reason to drop an
     upload - unknown is not long.
   - **The title sieve** (CF-0309, 2026-09-22) - six rules on what the upload's own title
     and channel say, `reason_code: "not_the_works_footage"`: the title names no form of
     the work **in itself** (CF-0272 accepts the description and the channel too, which is
     right for a signal and not for footage); the work's word appears only as the tail of
     another name ("The NFL Odyssey" for *The Long Voyage*); the title is a news round-up of
     three works or more; hashtags are half the title or more; the title carries a word of
     opinion or of news ("review", "update", "why"); the channel is a film-press outlet
     (`collider`, `etalk`). A seventh, `other_work_title` (CF-0924), runs for official
     channels too: the title names the work only as a credit ("Karōshi ... dari Produser
     Jon Marrow", "from the producer of Jon Marrow"), or an official upload for a film/series
     topic is titled with another work ("Karōshi (2027) Official Trailer" for *Jon Marrow*)
     - the drop carries `rule` and `title_subject`; never hand-restore such a candidate. Why: on `2026-09-21T1541Z` the indexer reached 25 candidates,
     refused 14 of them on their content and ran 5 h 37 min, and four topics died because
     their good candidates ran out before their four attempts did - nine of those refusals
     said what they were in the title. Measured on that run's verdicts as a labelled set
     (9 good against 16 bad, `tests/fixtures/footage_sieve_1541z.json`): the six rules take
     10 of the 16 and **0 of the 9**, and `tests/test_footage_sieve.py` holds each rule to
     both numbers. The word lists are `config/footage_sieve.json`, every entry carrying the
     upload it was read off - same discipline as CF-0297, and the same rule above it: an
     official channel is never sieved. If a drop is wrong, the fix is a line in that
     config, never a hand-added id.
   - **Somebody else's host is not our backdrop** (CF-0817, the user's yes of 2026-10-20) -
     the last sieve, `scripts/host_show.py` over `config/host_show.json`,
     `reason_code: "host_show"`, **official channels included**. An upload is a host show
     when its title or channel names a show (`shows`: Fallon / The Evening Show, Kimmel,
     Colbert / The Late Show, Sam Meadows / Late Night, Graham Norton, Hot Ones, Kelly and
     Mark, The View, TODAY, GMA, the press-interview outlets...) or says the format
     (`formats`: podcast, talk show, late night, morning show, interview, press junket,
     roundtable, and - not on an official channel, where they are promo words - reaction,
     review / commentary), or its nature is `interview` / `commentary` read off the title
     or the room on a channel that is not official, or (nature `unknown`) only talk facets
     found it. A show matched on the channel name alone does not take the work's own cut
     the channel re-uploaded (a trailer; for a press outlet also a clip and a promo). Why:
     a viewer wrote "Stop stealing content. Especially from the basement yard podcast" under
     the Reel `vanguards-doomsday` - 16 of 16 clips of the 2026-10-11 video were Zenith's own
     "Countdown to Vanguards: Doomsday Official Podcast"; the CF-0818 audit found ten
     published videos with somebody's couch under our voice (Fallon for Delver, Kimmel for
     Other Mommy, Sam Meadows for WNL, Kelly and Mark for American Dread Story), eight of
     the nine sources out of this list. **One exception**, off existing fields only: the
     topic is about a person (`title_ref.kind: "person"` whose `name` is that person - a
     person-topic named after a work, "Weekend Night Live" with `person: Dana Reyes`,
     is about the work) or the supplement searched a `kind: person` entity, and the
     upload's **title** names that person - their own interview (`subject_is_guest`).
     Mechanically also: the topic's own name names the show (`topic_is_the_show`). The kept
     candidate carries `host_show` (`refused: false`, `exception`, `subject`, `signals`,
     `reason`); on every other candidate `host_show` is `null`. A wrong drop is a line in
     the config, never a hand-added id.
   - **Another installment of the franchise** (CF-0444, 2026-09-30) - when the topic's name
     has a colon stem ("Vanguards: Doomsday") or a `parent_work` ("Outrider: Blood of My
     Blood" / "Outrider"), an upload whose **own title** names the work only by that stem
     or parent - never by the full name or the subtitle - is dropped with
     `reason_code: "other_installment"`, official channels included. Why: on
     `2026-09-29T0705Z` the feed read matched Zenith's uploads for both Vanguards topics by
     the stem "Vanguards", Endgame (`-004`) and Doomsday (`-005`) left 5b with the same six
     ids, and the frame judge rejected Doomsday with `wrong_work_footage` after three
     renders - nothing before it noticed. The rule is `topic_relevance.installment_forms`,
     the same forms the indexer's pool check asks of a pool source (CF-0325,
     `pool_work_check.py`); a sequel number alone ("Everyday Sorcery 2") does not trigger it,
     because a sequel's press names the original. A topic the rule leaves with fewer than
     two candidates is **not** built on the other film's list: its feed file says
     `fallback_search: true`, so run its facet search as for any thin feed, and if that
     does not reach two either, the script refuses it with `no_source` and the reserve
     takes the slot (CF-0313) - the ordinary ladder, nothing to decide by hand.
   - **`footage_candidates_shared` in the batch file** (CF-0444) - one entry per set of
     topics whose `youtube_video_ids` are the same ids (`reason_code:
     "same_candidate_list"`), `[]` when every list is the topic's own. The script prints it
     as a `WARNING same_candidate_list` line, in a fill and in `--check`; it does not fail
     the batch (two works can honestly share an upload), but it is a line in your step-8
     report, word for word, and the first thing to look at: at most one of those topics is
     looking at its own footage.
   - **`evidence.footage_candidates_dropped`** - the uploads it took out, one record each
     with the view count and `reason_code: "wrong_work"` (another work, CF-0272),
     `"other_installment"` (another film of the franchise, CF-0444),
     `"unofficial_source"` (not footage of it, CF-0297), `"source_too_long"` (over the
     ceiling, CF-0302), `"not_the_works_footage"` (a talk about the work, CF-0309),
     `"host_show"` (a podcast, interview or talk show, CF-0817 - the record carries the
     verdict under `host_show` with the signals). Read
     them: a
     drop is the script saying the search was answered through the channel rather than
     through the words, and on Wren Hollow that was the two ids the indexer would have
     spent both canonical downloads on. The drop happens before the round-robin, so the
     next real candidate moves up and the topic loses no slot. Name the count in step 8.
     If a drop is wrong - a genuine candidate whose title only prints a localised name -
     say so in step 8; do not re-add it by hand, because a hand-added id is an id no
     record stands behind and `--check` fails it.
   - **`evidence.footage_candidate_shortfall` on a topic** - fewer than three candidates,
     or all of one nature - is a fact about the topic, not an error to work around. Leave
     it in the artifact and name the topic in your step-8 report. Do **not** pad the list
     with more uploads of the same cut to reach three: that is exactly the pool that
     measured as one source.
   - **A topic left with fewer than two candidates** is refused by this stage (CF-0309,
     2026-09-22; it used to be "no candidate at all"): the script takes it out of
     `topics[]` and records it in `skipped_topics[]` with `reason_code: "no_source"`, so
     the loss is counted by the topic funnel instead of being silent. One candidate cannot
     produce the two canonical sources the gate needs, and finding that out at the indexer
     costs a download and ~6 min of indexing per minute of source. Say so in step 8.
   - **On a channel that draws its own graphics the floor has a second way through**
     (CF-0689, the user's decision of 12.10). When the channel's `footage-origin.json` names
     the `own_graphic` origin (ExampleTech: its base footage is the graphics the Video Editor
     draws from the script's facts, root `shared/own_graphic.py`), a topic with fewer than two
     candidates - none at all included - is kept when its `support_text` holds at least
     **3 quotable facts**: distinct sentences with a figure or a date, read by the root rule's
     own `parse_numbers` / `parse_dates` (the parser the writer's check later holds each
     graphic value to). Never counted: the factory's `own_capture_record` and
     `api_demo_record` pieces (a number in a model's API answer is the model's), a number
     inside the topic's own name ("Gemini 2.5 Pro") or glued to one ("GPT-5"), a version
     ("2.5.1"), a "sentence" over 400 characters (a flattened table), and (CF-0809) any
     sentence of a Wikipedia article about **another edition of the thing than the news** -
     a title qualified by a generation, an ordinal, "original" or a year ("Tesla Roadster
     (first generation)" for the new Roadster) that the topic's own text (`title_ref`, title,
     scene descriptions, news pieces) does not name and whose newest year (the qualifier's,
     or one the article names at least twice) is older than the batch's year minus one; such
     a piece is listed under the footing's `other_subject[]` and its note. Three because an
     all-graphic Short is several graphics, each value its own verbatim quote, and one may
     fail the claim judge. Every topic of such a channel carries
     `evidence.own_graphic_footing` (`quotable_facts`, `floor`, `meets_floor`, up to five
     `examples` with their piece id, `note` - "own graphics: N quotable fact(s) ..."); a
     topic kept this way gets the note `kept on own graphics - ...`, and a refused one's
     `skipped_topics[]` reason ends with the same `note`. No candidates and fewer than three
     facts: refused with `no_source` as before. A topic kept on graphics has no own capture
     under it, so it is never a «демо» - the Content Researcher's `check_demo.py` and the
     Video Editor's `demo_own_capture` gate hold that, not this floor. ExampleFilm and
     ExampleScience (no `own_graphic` origin) keep the count floor exactly. Say in step 8
     which topics were kept on graphics and with how many facts.
   - **That refusal frees the slot, and the script refills it from the reserve** (CF-0313,
     2026-09-22; until it the slot stayed empty and the loss was paid out of the slack
     between the shortlist of 8 and the batch target of 5). The next `below_shortlist`
     topic by rank goes back into `topics[]` and is walked through 5b like any other topic
     of the batch. What it writes is `footage_substitution` in the batch file:
     `substitutions[]` (who replaced whom, with what code the replaced topic died, how the
     substitute ended up), `unmatched[]` (a slot nothing could fill — `reserve_exhausted`
     when the reserve is spent, `search_quota_exhausted` when the day's searches will not
     pay for another facet run) and `remaining[]` (the reserve nobody touched). The
     replaced topic's own record gains `replaced_by_topic`.

     **A substitution costs a facet run, so it may need a second pass from you.** The
     script does not search; when the substitute has no footage search yet its entry is
     written with `outcome: "pending_search"` and the exact command in `facet_search`. Run
     it, then re-run `footage_candidates.py` with that file added to `--signal`: the same
     entry is completed, the topic enters `topics[]`, and nothing is written twice. Hand in
     every earlier search again — a re-run is idempotent. An entry that stays
     `pending_search` in the artifact is a slot you left empty, so either complete it now or
     say so in step 8 — the second pass is a second pass of this stage, minutes later, never
     a return after the quota resets (CF-0317).

     Three things not to do: do not write scenes (step 6) for a substitute before it has
     candidates; do not re-sort or hand-edit `skipped_topics[]` (the reserve queue is its
     `rank`, and the promoted topic's row is removed by the script, not by you); do not
     rewrite `selection` — it is step 5a's record of the pass that cut the shortlist, and
     what the batch holds now is `topics[]` plus `skipped_topics[]`.

     Compliance judges the substitute on its **first** pass, because it is in `topics[]`
     before the compliance stage opens the file; `cut_shortlist.py` (CF-0265) ranks it by
     `topics[]` order, which puts it last — it is the topic the cut had no room for.

     If a run loses more than three topics here, say so in step 8 — that is the shortlist
     and the reserve both gone.

     The `below_shortlist` rows you leave are also the root's queue later in the batch
     (CF-0882): when compliance's reserve is spent, the root's refill round calls
     `scripts/promote_below_shortlist.py` on the next of them (feeds first, a facet run
     only within the day's search budget, the same sieves). That is the plan's stage, not
     a step of yours - do not run it here, and do not prune the rows "for tidiness".
   - If a title's pool is thin because the search never saw its material, a wider
     `--days` on the facet run is a reasonable thing to try once; a fabricated id is not.

   Budget, since the shortlist is 8 titles (CF-0264) and a search costs 100 quota units:
   ≤ 20 scoring searches (2,000) plus 8 titles × 6 searches (4,800) against a 10,000/day
   key — 6,800 of 10,000, where five titles cost 5,000. The extra 1,800 is what the shortlist
   costs, and it buys compliance a batch it can take three topics off without emptying it;
   against it, 2026-09-16 spent six downloads and ~36 minutes indexing three topics that had
   no fact and were never going to be written. Fewer topics with a wider pool each is still
   the deliberate trade; do not spend the saving on more titles, and do not run a facet
   search for a topic step 5a refused.

   **The limit that actually binds is the other one** (CF-0288, counted since CF-0313): the
   API allows **100 `search.list` calls a day** per project, reset at 07:00 UTC, and a batch
   is ~68 of them. The script keeps the count in `search_quota` in the batch file —
   `spent_searches`, `remaining_searches`, `substitution_price_searches` (6) and
   `substitutions_affordable`, which is the remainder divided by the price and is the cap on
   substitutions for this batch. It counts what it can see: the searches handed to it, and
   the run log of the batch directory. Anything the same quota day spent that it cannot see —
   the scoring pass in another session, an earlier batch of the day — is yours to pass:

   ```bash
   .venv/bin/python scripts/footage_candidates.py <batch-dir> --signal ... --write \
       --searches-spent 20
   ```

   **What the day went on, by article** (CF-0368). The same block splits the spend four
   ways, because the four are not the same money: `by_article.scoring` (one bare
   `search.list` per candidate topic), `by_article.footage_feeds` (CF-0361/CF-0369 —
   `playlistItems`/`videos`/`channels` at **1 unit a call**, no `search.list` and so no claim
   on the day's 100), `by_article.footage_search` (step 5b's facet runs) and
   `by_article.supplement` (CF-0343). Each row carries `search_calls`, `api_units` and the
   `units` of both together; `spent_searches` is the rows plus `searches_before_stage` and
   nothing else. The CLI prints one line per article after the `search quota:` line, and the
   same split goes into the run log as a `quota` event, which is what puts it into
   `RUN_SUMMARY.md`. This is a **measurement, not a budget**: nothing is capped per article
   and no call is refused because an article ran dry (decision 2026-09-23 — the cache and the
   per-article division wait until the measurement shows a shortage). Measured on
   2026-09-22T1001Z: scoring 20 calls, footage search 48 (8 facet runs), feeds 0, supplement
   0 — 68 of 100, plus 33 units of 1-unit calls.

   Read the `search quota:` line it prints before you decide anything. The one thing a spent
   day is never is a reason to wait (CF-0317). It ends two ways, and neither of them is a
   question for a person:

   - **A topic still in `topics[]` with no facet run behind it, on a day that will not pay
     for one**, leaves the batch here, exactly as a topic under the candidate floor does:
     the script takes it out of `topics[]` and records it in `skipped_topics[]` with
     `reason_code: "footage_evidence_quota"`, so the loss is counted by the topic funnel
     instead of being carried to compliance as a topic with no footage. The searches the day
     *can* still pay for go to the topics that rank first. Do **not** run the facet searches
     "after the reset" and do not leave the stage open until then: the reset is on its own
     clock — `resets_at` in the `search_quota` block, hours away — and no batch is paid for
     standing in front of it. The next scheduled run starts with a full day and finds these
     titles again if they are still trending.
   - **A slot nothing refilled, `search_quota_exhausted`**, is the same fact about the
     reserve: the slot stays empty, the batch goes to compliance one topic short, and that
     belongs in step 8 word for word.

   This is the point the run `example-film/2026-09-19T0116Z` was lost at. Its step 5b widened
   the footage of 3 of 8 topics before the day's calls ran out, and the batch then sat from
   01:26 to 07:06 — 5 h 40 m of an autonomous run — waiting for the quota to come back for
   the other five. Under the rule above those five are five recorded losses and the batch is
   at compliance a minute later.

   **Supplement mode — footage of an entity for a thin pool (CF-0343).** Not part of a
   fresh run's step 5b: it runs later in the batch, when the writer's pool gates warned
   `pool_too_thin` and left a request skeleton in
   `<batch>/work/supplement-requests/<topic_id>.json` (CF-0342). Fill it:

       .venv/bin/python scripts/footage_candidates.py \
           --supplement <batch>/work/supplement-requests/ --search --write

   (`--plan` prints the searches and spends nothing; `--signal <file>` hands in a
   `fetch_youtube_signal.py` output instead of searching.)

   **What the supplement looks for (CF-0426, the user, 2026-09-28).** In this order: the
   topic's own footage → its people **as themselves** (interview, press tour / press
   conference, red carpet, award) → reels of that same kind. **Another work is never looked
   for** — not by search, not as "<person> <work>" (that path, CF-0343's rule 2, is gone:
   four runs gave 3 downloads the sieve refused and 0 frames, and a frame of another film in
   another role leaves the viewer unsure which film the video is about), not off the feeds.
   A `show`/`work` entity that is not the topic's work goes to `search.entities_skipped[]`
   as `foreign_work`. **The one exception — a film of the topic's franchise the narrator
   names himself** (in the script's hook / commentary / payoff in `03-content-researcher.json`,
   or in the request's anchors' `beat_text`): it is the topic's frame, searched as a work
   (`franchise: true`); unnamed, it is `foreign_work`. The franchise's short form is never
   the work: "Vanguards: Infinity War" is not "Vanguards: Endgame Encore", "Everyday Sorcery"
   is not "Everyday Sorcery 2", a film's `parent_work` is its prequel, and two names that
   only share initials are two works (CF-0425). The filled request says what the narration
   named in `search.narration`. Only a person, a place or a work is searched: any other
   `kind` (`thing` — the Infinity Stones —, `event`, a kind not known yet) goes to
   `entities_skipped[]` (`kind_not_searched` / `event`), never searched as a person
   (CF-0425). The batch's own `work/feeds/feed-<topic>.json` is reused for free — its units
   were charged once by the pass that wrote it, so the supplement charges `supplement-feeds`
   only for the feeds it reads itself (CF-0425).

   **Feeds first here too (CF-0369, 2026-09-24).** An entity that is a **work** — the
   topic's own work, or a franchise film the narrator names — is read off the
   registered official channels' upload feeds before a single `search.list` call is spent
   (`fetch_channel_feeds.topic_feed()`, the same registry as step 5b): trailers, teasers
   and clips of that work, 0 search calls. The batch's own `work/feeds/feed-<topic_id>.json`
   from step 5b is reused for the topic's own work, so that half is free. A **person**
   and a **place** (filming) are not on any work's upload feed and go to the search. A feed
   read matches the franchise's short form too, so **a feed upload is kept only when its
   title names the topic's own work, or names a person of the topic and reads as that
   person as themselves** (then it is that person's candidate); another work's trailer,
   clip or podcast off the same channel is `foreign_work_footage` (CF-0426).
   Feeds that gave fewer than 2 candidates are **not a refusal**: the work's search
   runs exactly as before. **The 2 are counted after the pool (CF-0414):** an upload the
   topic's pool already holds — the footage pass's ids, the indexer's `sources_by_topic` /
   `fetched` / `aliases` / earlier supplement offers, `work/footage-aliases.json` — or a
   same-cut re-upload of one is `already_in_pool`, not a candidate (0929Z: Wolfhame's feed
   gave 4, all 4 the topic's own sources, the search was skipped and the request came back
   empty). `search.feeds[]` carries `kept`, `in_pool`, `new_candidates`; a topic's own work
   the feeds did not cover is searched **before** the people under the 16-call cap.
   **Exit code (CF-0414):** 0 when every request was filled and written — an empty one too,
   with a `no candidates for <topic>: <why>` line and the reasons on the request; 1 only when
   a request's searches all failed (`search_failed`, none read) and it has no candidates; 2
   for an unreadable request. (Before, any empty request made the whole run exit 1 and the
   root's step wrote `hunter exit 1` on every topic of the run.) The
   filled request records `search.feeds[]`,
   `search.feeds_unread[]`, `search.feeds_covered`, `search.feed_api_units` and
   `search.search_calls_saved_by_feeds`; a work the feeds covered is in
   `search.searches_skipped[]` as `covered_by_feeds`. `--no-feeds` is the pre-CF-0369
   behaviour, `--feed-signal <file>` hands in a `fetch_channel_feeds.py` output,
   `--feed-pages 0` reads the RSS feeds only (no key, no units).

   Per entity the search (for whoever is left): the topic's work — its bare name plus
   trailer / clip / interview; a **person — only interview / press conference / red carpet /
   award, with no bare-name query** (`fetch_youtube_signal.py --no-bare`: 4 calls; the bare
   name brought 0929Z other films' trailers); a place only as "<place> <topic's work>"
   filming — a bare place name is ambiguous — over ten years. The result goes through the
   same four sieves with "names the **entity**" in place of "names the work" (an upload that
   does not name the entity is `wrong_entity`; a work search's upload that names the work
   only by its franchise's short form is `foreign_work_footage`) — **and an upload found
   for a person whose title names no form of the topic's work passes only as the person as
   themselves** (CF-0414, widened by CF-0426): `fc.classify` interview, or the title / the
   channel names an interview, press conference or tour, red carpet, premiere, award,
   festival or talk show. A cut of a work — trailer, teaser, promo, scene clip, a fan edit
   or scene pack of a role — is `foreign_work_footage`; anything that says neither (a "best
   moments" reel, a court clip) is `person_not_as_self`; both are dropped before the
   download (0929Z: the Ebenezer trailer for Johnny Depp 87% off in the indexer's source
   sieve, Civil War's airport scene for Iron Man 85% — an hour of download and description
   for nothing). It writes at most `max_attempts` × 2 `candidates[]` —
   `video_id, entity, nature, origin, duration_seconds, query` — which the indexer reads
   with `ingest_batch.py --supplement`. Searches cost the batch's quota ledger
   (`search_quota.supplement:<topic_id>`, at most 16 per request); what the remainder does
   not pay for is listed in `search.searches_skipped[]`.

6. **Reason about candidate scenes (this is the part only you can do — not scriptable).** A topic step 5b substituted in from the reserve (CF-0313) is a surviving title like any other and needs its scenes written here — it has none, because step 5a cut it before step 6 ever ran. For each surviving title, read through the YouTube video titles/descriptions and the RSS snippet(s) you gathered — including step 5b's facet run, which is usually where the specific moments are named (an interview names the scene the cast was asked about, a clip's title names the beat). Identify specific moments/scenes people are actually discussing (named characters, plot beats, specific episodes if mentioned) — do not invent a scene that isn't evidenced by the signal you gathered. For each identified scene:
   - **Pick its one source first (CF-0533).** Every scene carries `source_url`: exactly one URL, one of the topic's own `evidence.sources[].url` (the RSS articles - a YouTube title can point you at a moment, but it is not a source a scene can cite). Read that source's `title` and `summary` in `evidence.sources[]` (the RSS summary the fetch gave, written there by `evidence_sources.py`). **CF-0638:** `summary` is `null` for a source of a `headline_only` feed (all of example-film's) - write that scene from the headline alone, and do not take the excerpt out of the fetch's output instead: a feed's text is for choosing the topic, and nothing of it reaches the writer, the scene's description included.
   - Write a short `description` (1–2 sentences, factual — what happens / what's being discussed, not commentary) **from that one source only**. Every person, character, place and outlet you name must be printed in its title or summary. **Never join two headlines into one event**, even when they are about the same episode and the same day: two articles are two scenes, each with its own `source_url`, or one of them is left out. On `example-film/2026-10-01T1313Z` two Deadline headlines - Mae's death (an interview with Annette Bramwell) and a tribute to Anthony Hart (who played Rupert) - became one scene, "a send-off for the Crown & Anchor pub owner, as a tribute after actor Anthony Hart's death", and the published video said Anthony Hart played Mae. Do not add what you know about the work either (who plays whom, who died): what the source does not say, the scene does not say.
   - **Write the scenes through a quoted heredoc (CF-0736).** Whatever writes `scenes[]` into the batch file - a `python3 - <<'EOF'` block, a `cat > file <<'EOF'`, an Edit - its text must reach the file as typed. Quote the heredoc's word (`<<'EOF'`, never `<<EOF` / `<<E`) and hand the batch directory to the script through the environment (`B=<batch-dir> python3 - <<'EOF'` and `os.environ["B"]` inside), never through `$B` in the script's text; never put a description in a double-quoted shell string (`echo "..."`, `-c "..."`). An unquoted heredoc lets the shell expand every `$` in it: on `example-film/2026-10-13T1411Z` the scenes went in through `python3 - <<E`, zsh read «$27.5» and «$5.5» as its positional parameters, and Other Mommy's scene said «tops the box office with .5 million while The Social Reckoning flops with a .5 million debut». Step 7's `check_scenes.py` names such a scene `figure_lost` (a number with no digit before its point, an amount of the source with its first digit gone, a «million» with no number where the source prints one) - rewrite it with the amount copied from the source.
   - **Who did it only when the source links it (CF-0543).** A name being in the source is not the source saying what the name did. The accepted `harbourlights` (`example-film/2026-10-05T0701Z`) said "Zorvath is behind the kill" out of Variety's "Hal Garrett's Killer and Manhunter Revealed, Zorvath Creates [SPOILER], …" - a list of items, not a link; Hal Garrett was shot by Sheriff Kerry Kane. Make somebody the doer of a killing or a betrayal ("X killed Y", "X is behind Y's death", "the killer is X") only when one clause of the source's title or summary says exactly that. A headline with `[SPOILER]` hides the "who": the scene says the killer **is revealed**, never who ("The finale reveals who killed Hal Garrett").
   - Tag it with 1–2 tags from `tag_taxonomy` (`emotional`, `funny`, `controversial`, `character_analysis`, `relationship_moments`).
   - If a title has strong overall signal but no specific scene is evidenced by your sources, output one scene with `"tags": ["general"]` and a description of the overall discussion — don't force specificity you don't have. A `general` scene has a `source_url` too, and the same rule: its description is what that one source says.
   - `scripts/check_scenes.py` (step 7) holds the source mechanically: a scene without its one `source_url` among the topic's sources is not written, and a topic left without scenes gets a `general` scene made of its source's headline, verbatim. The names and the "who did it" are no longer checked against the headline (CF-0556 retired CF-0533's name check and CF-0543's link check after the claims exam): what the video finally says is quoted from the topic's `support_text` and judged at the writer's stage by the root's claim judge. The two rules above are still yours - a glued scene sends the writer after a story the text does not tell, and the topic is lost there.

7. **Write the batch file.** `batch_id` is the batch directory's name - `YYYY-MM-DDTHHMMZ` (UTC, minute precision); under the plan the executor named it, outside the plan you computed it before step 1. Write to:
   `~/shorts-content-factory/pipeline/<channel>/<batch_id>/01-trend-hunter.json`
   (create directories as needed). Schema (the `lf-` id prefix below is
   deliberate and did **not** follow the channel rename to `example-film` - ids
   already minted downstream keep it, CF-0180):

   ```json
   {
     "batch_id": "2026-08-29T0800Z",
     "channel": "example-film",
     "language": "en",
     "generated_at": "2026-08-29T08:00:00Z",
     "sources_used": ["rss", "youtube"],
     "discovery": {
       "rss": {
         "source": "rss",
         "generated_at": "2026-08-29T07:58:10+00:00",
         "requested_days": 3,
         "window_start": "2026-08-26T07:58:10+00:00",
         "max_requests_per_feed": 12,
         "total_requests": 11,
         "coverage": [
           {
             "feed": "Variety",
             "feed_url": "https://variety.com/feed/",
             "strategy": "wp-rest",
             "requests_made": 4,
             "max_requests": 12,
             "entries": 234,
             "newest_at": "2026-08-29T07:40:00+00:00",
             "oldest_at": "2026-08-26T08:05:00+00:00",
             "requested_days": 3,
             "covered_days": 2.98,
             "window_complete": true,
             "stopped_because": "covered",
             "error": null
           }
         ],
         "warnings": []
       }
     },
     "topics": [
       {
         "topic_id": "lf-2026-08-29-001",
         "title_ref": {
           "name": "Cuttle Game",
           "kind": "work",
           "type": "tv_series",
           "year": null,
           "season": null,
           "network": "ExampleStream",
           "parent_work": null,
           "person": null,
           "rights_holder": "ExampleStream"
         },
         "fact_probe": {
           "outcome": "ok", "has_fact": true, "usable": true,
           "article": "Cuttle Game", "article_url": "https://en.wikipedia.org/wiki/Cuttle_Game",
           "candidates": 1, "parent_work": null, "detail": null, "requests": 3,
           "source": "wikipedia", "asked_at": "2026-08-29T07:59:00Z",
           "asked": { "name": "Cuttle Game", "type": "tv_series", "year": null,
                      "season": null, "network": "ExampleStream", "parent": null }
         },
         "signal": {
           "popularity_score": 92.8,
           "components": { "youtube_view_signal": 88.0, "rss_mention_signal": 100.0 },
           "raw": { "youtube_views_after_exclusions": 2749193, "distinct_rss_houses": 2, "distinct_rss_entries": 5 }
         },
         "evidence": {
           "youtube_video_ids": ["abc123", "def456", "ghi789"],
           "footage_candidates": [
             { "video_id": "abc123", "kind": "teaser", "nature": "trailer",
               "origin": "official", "footage_origin": null,
               "licence": { "id": "youtube_official_upload", "judged": false, "accepted": null,
                            "short_name": "youtube official upload", "origin": null, "...": "CF-0662" },
               "title": "<the upload's title as the search gave it>",
               "channel_title": "Example Studios", "view_count": 4200000,
               "duration_seconds": 152,
               "facets": ["title", "trailer"], "same_cut": ["def456reupload"],
               "why": "teaser; official - the channel 'Example Studios' is an official studio ('example studios'); 3 uploads of the same cut collapsed into one candidate" }
           ],
           "footage_candidates_dropped": [
             { "video_id": "xyz789", "title": "Harbourlights | Midseason Trailer | Example Max",
               "channel_title": "Example Max", "view_count": 2078310,
               "reason_code": "wrong_work",
               "reason": "names no form of the topic's work ... (CF-0272)" },
             { "video_id": "WQEC_tH0UP8", "title": "SILENT TIDE 2: AFTERMATH | Official-Style Fanmade Concept Trailer | Brad Pitt | 2027",
               "channel_title": "Luucy Ai", "view_count": 118000,
               "reason_code": "unofficial_source",
               "reason": "its title says 'Fanmade' - ... (fan_made, CF-0297)" },
             { "video_id": "Lv_GOa6HXVA", "title": "Lakeside Trailer, Example Pictures Leaving California ... - SMALL ZERO",
               "channel_title": "Small Zero", "view_count": 46,
               "reason_code": "source_too_long",
               "reason": "8019 s long - over the 900 s ceiling this channel holds nature 'trailer' to (sources.youtube.max_source_duration_seconds, CF-0302) ...",
               "duration_seconds": 8019, "ceiling_seconds": 900, "nature": "trailer" }
           ],
           "footage_candidate_shortfall": null,
           "excluded_evidence": [],
           "rss_links": ["https://variety.com/..."],
           "sources": [
             { "url": "https://variety.com/...", "title": "<headline exactly as the feed gave it>",
               "publication": "Variety", "published_at": "2026-08-29T14:02:11+00:00",
               "feed": "https://variety.com/feed/",
               "summary": "<the RSS summary exactly as the fetch gave it - a read_text feed's only; null for a headline_only feed (CF-0638)>" }
           ]
         },
         "scenes": [
           {
             "scene_id": "lf-2026-08-29-001-s1",
             "description": "...",
             "tags": ["emotional", "character_analysis"],
             "source_url": "https://variety.com/..."
           }
         ],
         "scenes_dropped": [
           { "scene_id": "lf-2026-08-29-001-s2", "description": "...", "tags": ["emotional"],
             "source_url": "https://variety.com/other/", "reason_code": "source_not_in_evidence",
             "stage": "trend-hunter",
             "reason": "lf-2026-08-29-001-s2: source_url 'https://variety.com/other/' is not one of the topic's evidence.sources[].url (CF-0533)" }
         ]
       }
     ],
     "selection": {
       "stage": "trend-hunter", "shortlist_size": 8, "scored": 10, "viable": 9, "carried": 8,
       "refused": { "no_fact": 1, "below_shortlist": 1 },
       "fact_probe": { "source": "wikipedia", "asked_at": "2026-08-29T07:59:00Z",
                       "requests": 27, "limit": 1, "probed": 10 },
       "published": { "asked": true, "log": "<root>/publish/acceptance-log.json",
                      "videos": 9, "unresolved": [], "errors": [], "dropped": 0, "marked": 0 }
     },
     "skipped_topics": [
       { "topic_id": "lf-2026-08-29-004", "reason_code": "no_source",
         "reason": "no filmable video found for this topic in the footage search - 12 video(s) seen",
         "stage": "trend-hunter", "replaced_by_topic": "lf-2026-08-29-009" },
       { "topic_id": "lf-2026-08-29-007", "reason_code": "no_fact",
         "reason": "no fact: wikipedia answered 'no_article' (article: -); searched wikipedia=no_article(0), rss_pool=ok(0); 0 candidate(s), none passes the fact rule (none found)",
         "stage": "trend-hunter", "title": "Rennick: Quill", "kind": "work",
         "popularity_score": 80.2,
         "fact_probe": { "outcome": "no_article", "has_fact": false, "usable": false,
                         "article": null, "article_url": null, "candidates": 0,
                         "parent_work": null, "detail": null, "requests": 3,
                         "source": "wikipedia", "asked_at": "2026-08-29T07:59:00Z",
                         "asked": { "name": "Rennick: Quill", "type": "tv_series",
                                    "year": null, "season": null, "network": "Prime Video",
                                    "parent": null } } },
       { "topic_id": "lf-2026-08-29-010", "reason_code": "below_shortlist",
         "reason": "viable but past the shortlist: rank 10 of 11 by score ... unused reserve",
         "stage": "trend-hunter", "title": "MobLand", "kind": "work",
         "popularity_score": 61.4, "rank": 10,
         "fact_probe": { "outcome": "ok", "usable": true, "...": "..." },
         "topic": { "topic_id": "lf-2026-08-29-010", "title_ref": { "...": "..." },
                    "signal": { "...": "..." }, "evidence": { "...": "..." },
                    "fact_probe": { "...": "..." } } }
     ],
     "footage_substitution": {
       "task": "CF-0313",
       "substitutions": [
         { "replaced": "lf-2026-08-29-004", "replaced_reason_code": "no_source",
           "replaced_stage": "trend-hunter", "replaced_reason": "no filmable video found ...",
           "topic_id": "lf-2026-08-29-009", "rank": 9, "title": "Everyday Sorcery 2",
           "reason_code": "reserve_substituted", "stage": "trend-hunter",
           "at": "footage_candidates", "restored": false, "promoted": true,
           "outcome": "candidates", "candidates": 6, "price_searches": 6,
           "reason": "lf-2026-08-29-009 takes the shortlist slot of lf-2026-08-29-004 ..." }
       ],
       "unmatched": [
         { "replaced": "lf-2026-08-29-005", "replaced_reason_code": "no_source",
           "replaced_stage": "trend-hunter", "topic_id": null,
           "reason_code": "search_quota_exhausted", "stage": "trend-hunter",
           "at": "footage_candidates", "remaining_searches": 2,
           "reason": "... the day has 2 of 100 left (CF-0288, CF-0313) ..." }
       ],
       "remaining": ["lf-2026-08-29-010"],
       "note": "CF-0313. A topic this stage refuses at step 5b ..."
     },
     "search_quota": {
       "task": "CF-0313",
       "searches_by_topic": { "lf-2026-08-29-001": 6, "lf-2026-08-29-009": 6 },
       "searches_before_stage": 20, "substitutions_made": 1,
       "daily_limit_searches": 100, "units_per_search": 100,
       "resets_at": "07:00Z (Pacific midnight, summer)",
       "searches_from_signals": 54, "searches_from_run_events": null,
       "spent_searches": 74, "spent_units": 7400,
       "remaining_searches": 26, "remaining_units": 2600,
       "substitution_price_searches": 6, "substitution_price_units": 600,
       "substitutions_affordable": 4,
       "note": "CF-0313. The `search.list` calls this batch is known to have spent ..."
     }
   }
   ```

   `title_ref.kind` / `type` / `year` / `network` / `parent_work` / `person`, `fact_probe` and
   `selection` are step 5a's (CF-0264) — `kind` and the rest of `title_ref` are yours to fill
   before it runs, the other two are written by `scripts/fact_probe_topics.py` and never by
   hand; so are `fact_candidates` and `fact_search` (CF-0438), `support_text` and `support_check`
   (CF-0551), and so is `pool` (CF-0325, written
   by the same script at the cut; do not re-sort `topics[]` by hand - its order is `pool.rank_score`). `skipped_topics[]` is written
   by two scripts now: step 5a (`already_published`, `no_fact`, `no_support_text`, `below_shortlist`;
   `person_without_work` until CF-0439; step 3a's `pool_too_thin` from the thin-pool memory,
   CF-0876) and step
   5b (`no_source`); both append, neither rewrites the other's rows. A `no_fact` row (or an
   old `no_production_fact` one) without its `fact_probe` is a refusal nobody can audit, and
   `--check` says so.

   `evidence.youtube_video_ids`, `evidence.footage_candidates`,
   `evidence.footage_candidates_dropped`, `evidence.footage_candidate_shortfall` and
   `skipped_topics` are step 5b's output and
   are written by `scripts/footage_candidates.py`, never by hand - one record per id, same
   order, same strings, the record's fields copied from the search's own row. `skipped_topics`
   is only there when this stage refused a topic; `footage_candidate_shortfall` is `null` on
   a topic that made the floor; `footage_candidates_dropped` is `[]` on a topic nothing was
   dropped from, and absent from neither. `evidence.excluded_evidence` is step 4's own list
   (CF-0272) and is likewise a field, empty or not, never a remark in your report. After the
   batch file is complete, re-check them:

   ```bash
   .venv/bin/python scripts/footage_candidates.py <batch-dir> --check
   ```

   It exits non-zero on a topic under the floor with nothing recorded about it, on ids with
   no candidate records behind them, on records that drifted out of step with the ids, on a
   refusal with no reason or no code, and on a topic whose `footage_candidates_dropped` or
   `excluded_evidence` was never written down. It prints every drop it read, so `--check`
   on a finished batch is also how you see what the relevance rule took out of it.

   `discovery.rss` is not optional either (CF-0059). It is the RSS fetch's own output with
   `entries` removed - every other key verbatim, one `coverage` row per configured feed.
   Produce it mechanically rather than retyping it:

   ```bash
   .venv/bin/python -c "import json, sys; sys.path.insert(0, 'scripts'); import fetch_rss_news as r; \
     print(json.dumps(r.batch_discovery_record(json.load(open('<batch-dir>/work/rss.json'))), indent=2))"
   ```

   The rows carry `strategy`, `requests_made`, `max_requests` and `stopped_because` per
   feed. Five batches were written without them, and when CF-0045 asked whether the
   request ceiling matched the need, nobody could answer from the batches - the ceiling
   is judged by exactly these numbers, so every batch keeps them. Since CF-0060 there are
   four rows (three PMC trades and Vulture); nothing here is per-outlet.

   `evidence.sources` (CF-0071) is the documentary trail behind `rss_links`: one object
   per link, same strings, same order, carrying the headline, the outlet's masthead, the
   publication date and the feed URL exactly as the RSS fetch recorded them - the
   Content Researcher copies these into a proof's source, so a source whose `title` or
   `published_at` is `null` is unusable for a proof. Never type these by hand; after the
   batch file has its `rss_links`, fill and check the field from the fetch's output:

   ```bash
   .venv/bin/python scripts/evidence_sources.py <batch-dir> --rss <batch-dir>/work/rss.json --write
   ```

   It exits non-zero and lists every record it could not complete (a link the fetch
   never saw, a feed entry without a date). Either cite a different link or drop that
   one from `rss_links`; do not fill the gap yourself. **A topic whose every link was
   dropped this way has no source** and leaves `topics[]` for `skipped_topics[]` with
   **`reason_code: "no_source"`** (CF-0708), the reason naming the link and the field it
   lacked (`its only news link <url> has no published_at in its feed - uncitable`). Never
   coin a code for it: on `example-science/2026-10-12T2001Z` a hand-written
   `no_dated_source` reached the funnel as an unknown code and turned the batch's live
   monitor red. (Since CF-0708 an RSS 1.0 feed's `dc:date` - Nature's - is read as the
   entry's date, so this should now be rare.) Since CF-0533 each record also
   carries `summary` - the RSS summary the fetch gave, or `null` - because that is the
   text a scene is checked against. Since CF-0638 the summary is written only for a feed
   whose `use` is `read_text` (the batch's channel's `channel_data.support_feed_urls`, asked
   by the script itself); a `headline_only` feed's record carries `summary: null`, and
   `--check` names a summary of such a feed.

   **Then hold every scene to its one source (CF-0533)** - after `evidence.sources` is
   written, before the stage is closed:

   ```bash
   .venv/bin/python scripts/check_scenes.py <batch-dir>           # dry run: what would fail
   .venv/bin/python scripts/check_scenes.py <batch-dir> --write   # drop the failures, general fallback
   .venv/bin/python scripts/check_scenes.py <batch-dir> --check   # the finished batch, exit 0 (also the skipped_topics[] codes, CF-0708)
   ```

   For every scene: `source_url` is set and is one of the topic's `evidence.sources[].url`
   (`no_source_url`, `source_not_in_evidence`), and its figures are its source's - not
   `figure_lost`, an amount the shell ate (CF-0736, step 6's quoted heredoc). Run the dry
   run first and fix a failing scene by citing its own source - never a second URL - and a
   `figure_lost` one by rewriting it through a quoted heredoc. What still fails at `--write`
   leaves `scenes[]` for `scenes_dropped[]` with its code and reason; a topic left without
   scenes gets step 6's `general` scene, whose description is its source's headline
   verbatim. `scenes_dropped` is absent on a topic nothing was dropped from. (Until
   CF-0556 this step also read every proper name of a description against its source's
   headline - `name_not_in_source` - and a doer against one clause of it -
   `reveal_not_in_source`, CF-0543; both were retired after the claims exam of
   2026-10-06, and old batches may still carry those codes in `scenes_dropped`.)

   **The same `--write` then judges the topic's fact against the scenes that stayed**
   (`CF-0548`, the root's `shared/factrule/fact_scene.py`, loaded by path). WNL `0701Z`:
   the scenes were Taylor Sterling walking into Dana Reyes's monologue, and the best
   candidate the topic carried was the cold open of the same broadcast - the video told
   the neighbouring sketch as its fact. Every `fact_candidates[]` entry gets `scenes` (the
   scene ids it is about) and `scene_fit` (`{scene_id: codes}`: `other_segment`,
   `names_outside_scene`, `not_about_scene`, `other_topic`). A topic none of whose passing
   candidates fits any of its scenes leaves `topics[]` for `skipped_topics[]` as **`no_fact`**
   with a `NO_FACT` line - here, before its footage is indexed - and its
   `fact_probe.fact_rule` is rewritten `not_found`. Do not write a scene just to give a stray
   fact a home: a scene stands on its own source (above), and a topic whose only facts are
   about the story next door is a topic without a fact. Name every such topic in the step 8
   report with the codes its reason gives.

   `signal.raw` is not optional. It records the inputs the score was computed from -
   `youtube_views_after_exclusions` and `distinct_rss_houses` are what the score is made
   of, `distinct_rss_entries` is kept alongside for the record - so a batch can be
   re-scored later without re-querying YouTube. The CF-0038 calibration had to
   reconstruct these numbers for four of the five existing batches because they were
   never written down, and CF-0060 had to recover house counts from `evidence.rss_links`
   for all five. `scripts/score_candidates.py <batch-dir>` replays a batch against the
   current scale and needs exactly this field. Its `--channel-config` takes a channel id
   or a path to the JSON; anything shaped like a path (a `/`, a leading `~`, a `.json`
   suffix) is read as one, and a path that is not there is `no channel config file <path>
   (the argument is a path, not a channel id)` - never a second `.json` glued onto it as
   an id (CF-0198). An id with no `channels/<id>.json` is refused the same way, naming
   both readings. Without the flag the batch's own `channel` field is used; a batch with
   neither is refused - there is no default channel (CF-0213).

   There is no `popularity_score_linear`. It existed on 2026-08-30T2329Z only as a
   parallel record while the choice of scale was open; CF-0005 settled it and CF-0038
   removed the field. Don't reintroduce a second score under any name — one number per
   topic, on the scale in step 4.

   `title_ref.rights_holder` is `null` when no RSS entry explicitly named one — leave it null, don't guess. **This field is whatever entity the RSS text names verbatim (often the distribution platform, e.g. "Example+"), not necessarily the true underlying IP owner** — e.g. a Pokemon-branded show distributed on Example+ is still Nintendo/The Pokemon Company's IP for enforcement purposes. Don't try to resolve the "real" owner yourself; just report what the source says and let Compliance Checker do that reasoning downstream (it found exactly this gap on 2026-08-28's first batch).

8. **Report back in chat and close the stage.** Summarize what you wrote (N topics, M scenes, path to the batch file) in plain text. Don't just silently write the file. Say per topic how many footage candidates it carries and of which natures, name every topic with a `footage_candidate_shortfall` (with the reason the record gives), say how many uploads were dropped as another work, how many as another installment of the franchise (`other_installment`, CF-0444), how many as not footage of it, how many as too long, how many as a talk about the work, how many as a host show (`host_show`, CF-0817 - name every candidate kept under its exception, with the person) and how many were dropped (`footage_candidates_dropped`, `wrong_work` / `unofficial_source` / `source_too_long` / `not_the_works_footage` / `host_show`; for a `source_too_long` give the measured length and the ceiling, CF-0302; for a `not_the_works_footage` name the rule the reason gives, CF-0309), quote every `WARNING same_candidate_list` line (`footage_candidates_shared`, CF-0444: two topics with one candidate list), name every topic whose first two links are both `origin: "unknown"` (CF-0297: that is the shape a batch has when the indexer is about to spend both canonical downloads on fan uploads), say how many views left each topic's sum through `excluded_evidence`, and name every topic this stage refused into `skipped_topics[]` - a thin pool and a refusal are findings about the batch, not details. Name separately every topic that left with `footage_evidence_quota` (CF-0317: the day's searches would not pay for its facet run) and say what the `search_quota` block says was left; if there is one, the `stage-done` note below says so too, in these words: `N topics left without footage evidence, the day's search quota would not pay for them (footage_evidence_quota)` - the word *quota* in it is what files this stage's record under the right point of `shared/runlog/no_waiting.py`. For step 5a specifically: how many topics left as already made (`already_published`, CF-0019 - name each with the video it repeats) and quote every `WARNING published_before` line (a topic kept although the factory already made a video of its work - say which video and whether the story is `different` or `unknown`); how many candidates were probed, how many were refused under each of the codes, and, for a `no_fact`, which article the search resolved to and why its candidates failed (`fact_search`, `fact_candidates[].check.failures`); for the carried ones, how many stand on a passing candidate (`selection.fact_rule.with_fact`); how many left with `no_support_text` (CF-0551 - name each with the `support_check.detail`: no article, or which episode has no description yet) and name every carried topic whose `support_check.state` is `unreachable` (it carries no Wikipedia text and the writer will refuse it). Give the Wikipedia requests of the pass (CF-0559): `selection.wikipedia.network` in all, `max_network_per_topic`, and every topic whose `per_topic.<id>.network` is above 2 with its number (the article and its season are two; more means a redirect hop or a guessed season title) - and say it when `counted` is false (the pass ran without the shared client and the number is not known). Give TVmaze's apart (CF-0636): `selection.tvmaze.network`, how many topics asked it and on how many its description was used (`used`), and its `refusal` when `asked` is false; Wikidata's the same way (CF-0637): `selection.wikidata.network`, how many topics found their item and were `used`, its `refusal` when `asked` is false; the companies' pages the same way (CF-0757): `selection.vendor_page.network`, how many topics asked a page and on how many it gave the passing fact (`used`), on how many it was the support text (`text_used`, CF-0771 - name those topics: their story is told from the company's post alone), and every `no_fact` whose `vendor_page` bracket says `closed` (the outlet's `ai_policy` is not `allowed` - a root re-check can open it). The article search of the probe is not in it: that is `selection.fact_probe.requests`. Say what the pool did to the cut (CF-0325): how many viable topics the pool already held footage for (`selection.pool.with_pool`), whether it reordered the shortlist (`selection.pool.reordered`) and which topic it lifted, and say it out loud when the pool could not be screened (`selection.pool.error`, `topics[].pool.measured: false`) - that batch was ranked on source counts, not on usable shots. Two of these have to be said out loud rather than counted: a batch where the probe was **unreachable** (nothing was actually filtered — the writer's rule will do it later, after the footage has been paid for) and a shortlist that came out **shorter than `scope.shortlist_size`** (the pool, not the rule, is what ran out). Say how many scenes `check_scenes.py` dropped and on which names (`scenes_dropped`, CF-0533), and name every topic that left on the `general` fallback - a video made from a headline is a thinner video, and the reason it is thin is that the scene said more than its source. Quote `refill.summary_line` (CF-0756, step 5a+) word for word - how many topics of the target, in how many rounds and search calls, and why the refill stopped - and when it did not stop on `target_met`, the `stage-done` note carries the same line, so a thin batch says why it is thin. Say how many searches the channel's cache answered (`search_quota.cached_search_calls`, CF-0824 - not spent, and not in `spent_searches`). Quote `prescreen.summary_line` (CF-0823, step 3a) word for word - how many candidates were pre-checked, refused by the probe and held back by the `no_fact` memory, and how many scoring searches that saved - and name every held-back candidate with the batch and date it was refused in. Give `refill.sources.totals` in one line (CF-0789): RSS entries and requests, candidates, out of scope, evaluated, scored, viable, untouched, scoring search calls - and the house that gave the most scored candidates; a pool whose `unattributed` row is large lost its links. Then, as the last act of the stage:

   ```bash
   "$RUNLOG" stage-done trend-hunter --batch "$RUNLOG_BATCH" --note "<N> topics, <M> scenes"
   ```

   This re-renders `RUN_LOG.txt` from the events; it is the only way that file gets
   written. Closing the batch is not this stage's: the run plan closes it with its
   `always` stages (`python3 shared/run_plan.py show <channel>`) - never write
   `batch-done` yourself.

## Notes

- If an API call fails (rate limit, bad key), report the specific failure — don't silently drop that source and pretend the batch is complete. The failure is also in `RUN_EVENTS.jsonl` as a `failed` script or child event with its error line; that is the record, your report is the explanation. Close the stage with `stage-done` and a `--note` naming the failure all the same.
- RSS is now your only discovery mechanism (not just a secondary signal) — if the configured feeds turn up nothing usable for a batch (slow news day), say so rather than forcing candidates. Widening `--days` on the RSS fetch, or adding more feeds to the channel config, is a reasonable fix to propose — but propose it, don't silently change scope on your own.
- The RSS fetch identifies itself as `shorts-content-factory/trend-hunter`. Don't dress it up as a browser and don't raise the request rate to save a few seconds. The position - what in the sources' `robots.txt` we rely on (nothing under `User-agent: *` disallows the feed or `/wp-json/`; the sitewide blocks are on named AI crawlers only - the same shape on the PMC trades and on Vulture), what we take (title, link, date, excerpt ≤ 500 chars; never article bodies) and why the per-feed ceiling is 12 - is written at the top of `scripts/fetch_rss_news.py` and in `docs/access-stance.md` (CF-0045 / CF-0059 / CF-0060). `--delay` and `--max-requests-per-feed` are how the script stays a well-behaved reader of that; change the numbers only from a measurement.
- Never fabricate scene descriptions beyond what your gathered signal supports — Content Researcher and Compliance Checker downstream depend on this being grounded, not invented.
