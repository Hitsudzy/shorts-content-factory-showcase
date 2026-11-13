# How a topic gets its candidate footage

Operator documentation of the Trend Hunter: what the RSS fetch reaches, and how a
topic's candidate footage pool is built and sieved. The overview is the
[README](../README.md); the procedure the stage follows is
[`SKILL.md`](../.claude/skills/trend-hunter/SKILL.md).

## RSS depth (CF-0007)

`--days` on `fetch_rss_news.py` is a depth request, not a filter. Variety/Deadline/THR each
serve 10–12 items on `/feed/` covering ~3 hours, so until 2026-09-02 every `--days` value
returned the same ~32 entries. The script now walks each source backwards until the window is
covered: the WordPress REST collection (`/wp-json/wp/v2/posts`, 100 posts/request) where the
site leaves it open, `?paged=N` on the feed otherwise.

Measured across the three configured trades (2026-09-02 under CF-0007, re-measured
2026-09-03 under CF-0059 with per-feed telemetry):

| | entries | requests (total) | per feed | wall time |
| --- | --- | --- | --- | --- |
| `--no-deep` (old behaviour) | 32 | 3 | 1 / 1 / 1 | ~2s |
| `--days 3` (2026-09-02) | 389 | 9 | — | 12s |
| `--days 3` (2026-09-03) | 649 | 11 | 4 / 4 / 3 | 16s |
| `--days 14` (2026-09-02) | 2024 | 25 | — | 42s |
| `--days 14` (2026-09-03) | 2090 | 25 | 9 / 9 / 7 | 48s |

Per feed = Variety / Deadline / THR; all `wp-rest`, all stopped on `covered`. Anything the
sources cannot deliver is reported, never silently truncated — see the `coverage` and
`warnings` keys in the output, and the stderr lines. Politeness knobs: `--delay` (default
0.5s), `--max-requests-per-feed` (default 12, see below), `--timeout`.

Vulture (added 2026-09-03, CF-0060) is a different shape and measured separately: its feed
is a FeedBurner address (`https://feeds.feedburner.com/nymag/vulture`; the site-side
`/rss`, `/feed`, `/rss/index.xml` are all 404 and there is no WP REST collection), so the
collector takes the `?paged=N` path, FeedBurner answers page 2 with the same page, and the
`added == 0` guard stops it: **`rss-paged`, 2 requests, `source_exhausted`, 20 entries,
~1 day covered, at `--days 3` and `--days 14` alike**. A four-feed `--days 3` run is
672 entries in 13 requests. That row always reports `window_complete: false`; that is the
feed's shape, not a shortfall.

## The candidate floor: three sources per topic (CF-0129)

Every topic leaves this stage with **at least three candidate footage ids of different
natures**, or with a record in the artifact saying how many there were and why there were
not three. Candidates, not guarantees: independence is decided after download by the
CF-0080 fingerprint, and discovery cannot compute a fingerprint on a video it has not
fetched. The indexer (`agents/footage-indexer/ingest_batch.py`) walks the list until two
canonical sources survive deduplication, at most four attempts, and refuses the topic
with `no_second_source` if they do not.

Why three and why "of different natures". On 2026-09-03T2037Z the gate passed on 0 of 4
videos: every topic's real footage was one trailer, because three uploads of one teaser
are one source after deduplication (`GyEpwGQIEZw` / `SJVmeJaS44s`, distance 1.82). On
2026-09-09 the stage wrote one id per topic on all eight; on 2026-09-15, one to four.
So the pool is widened where differently-shot material actually lives — a second trailer,
a press interview, an episode clip, a making-of — by one search per facet
(`fetch_youtube_signal.py --facets`), and the picking is done by
`scripts/footage_candidates.py`, which collapses same-cut uploads and orders the rest
round-robin across natures so the indexer's first two attempts are two different kinds of
footage.

The facet search is **off by default**, and that is not a convenience: the CF-0038 view
scale is calibrated on the bare query's view sum, so the scoring pass stays one search
per candidate and only the **shortlisted** titles (`scope.shortlist_size`, 8 since
CF-0264 — and only after the fact probe below has passed them) get the facet fan-out.
Quota, at the Data API's 100 units a search: ≤ 20 candidates scored = 2,000, plus 8 titles
× 6 searches = 4,800, against a 10,000/day key. The limit that actually binds is the other
one — **100 `search.list` calls a day** per project, reset at 07:00 UTC (CF-0288) — and a
batch is ~68 of them; `scripts/search_quota.py` counts them and the batch file carries the
count (`search_quota`), because a substitution (CF-0313) is spent out of what is left.

A thin topic is thin **in the artifact**: `evidence.footage_candidate_shortfall` carries
the counts (videos seen, distinct cuts, uploads collapsed as the same cut, natures, the
facets searched) and a reason. A topic with no candidate at all is refused by this stage —
out of `topics[]`, into `skipped_topics[]` with `reason_code: no_source`, the vocabulary
of the root funnel (`shared/runlog/funnel.py`, CF-0232) — so the loss is counted instead
of looking like a topic nobody searched for.

## Relevance is not independence (CF-0272)

The floor above counts *candidates*; this counts whether a candidate is the topic's at
all. The YouTube Data API's `q` is a relevance search, not a filter: it answers a query
with video it considers related through the channel and the network as readily as through
the words. On the topic "Wren Hollow" (the Example Max series) that put five Example Max promos
for **other Example Max shows** into the pool in two batches running
(`2026-09-17T1901Z`, `2026-09-18T1058Z`), and because the pool is ordered by view count
inside each nature, the two biggest — `RgptVRnT4XI` and `-05WmSAmLK4`, "Harbourlights", 2.49M
and 2.08M views — led the list ahead of the real candidates at 19K and 97K. The indexer
spent both canonical downloads on them and the researcher dropped the topic
(`pool_too_thin`, 0/6 anchors). The two-source gate could not help: two Harbourlights uploads
are genuinely independent footage, so the CF-0080 fingerprint passes them. Independence is
not relevance.

So `scripts/topic_relevance.py` asks one question of every upload before any of it is
ranked: **does it name the topic's work?** Whole words, normalised by
`fact_probe_topics.normalise` (the same normalisation the fact probe resolves `title_ref`
with), against the name, the stem and the subtitle around a colon, `parent_work`, each of
those without a leading article or a trailing sequel number, the space-less form a hashtag
uses, and acronyms of three letters or more. A person-topic is matched on its **work** and
never on the person (CF-0264). What fails is dropped with `reason_code: wrong_work` into
`evidence.footage_candidates_dropped`, does not count towards the floor of three, and —
because the drop happens before grouping and ranking — is replaced by the next real
candidate rather than costing the topic a slot.

Measured over the 340 videos of the eight search pools of `2026-09-18T1058Z`: 31 dropped,
of which 21 are another work (including every exclusion the operator had been making by
hand) and 10 are the price: eight titles written only in another language or another
script ("Jogos Vorazes", "ГАРРИ ПОТТЕР", 哈利波特) and two that name the Kardashian family
rather than the show. No topic came near the floor: the thinnest
pool still held 22 candidates that name their work. The cases are pinned one by one in
`tests/test_topic_relevance.py`, on records copied out of both batches.

The same rule runs on the **scoring** pass, where an unrelated video inflates the score
instead of the footage: 5.2M of Wren Hollow's 10.6M gathered views were other shows'.
Its exclusions go to `evidence.excluded_evidence` — a field SKILL.md had asked for since
CF-0038 and which no batch filled, because the operator was making the call in his head.
`footage_candidates.py --check` now fails a batch that carries neither field, and prints
every drop it reads.

## Naming the work is not being the work (CF-0297)

CF-0272 above asks whether a candidate is *about* the topic. It cannot ask who shot it,
and on `2026-09-19T0116Z` that was the whole batch. All five topics passed the two-source
gate, one script came out, and what the indexer had actually been handed became visible
only when it described the shots: `WQEC_tH0UP8` is a fan "Official-Style Fanmade Concept
Trailer" (Luucy Ai), `PEiDNOQ_0ms` a blogger's game capture (`#VRGaming`), `QJ1WSiMUVFA` a
captioned nostalgia compilation (`#fyp #viral`), `Cym8eElO6c0` a podcast recording that
yielded one static frame in 31.8 seconds. Four topics of five died downstream on
`thin_scene` / `no_second_source`. Every one of those uploads names its work, and every
one claims a nature of shoot the title rules believe.

So `scripts/footage_origin.py` asks the third question, off the same metadata the search
already returned, before anything is grouped or ranked:

- **`official`** — the channel is a studio's, a streamer's, a network's or a distributor's.
  Read off `channel_title` only; "| Example Studios" inside a *title* is what a re-upload
  copies first, which is the CF-0272 lesson.
- **`unofficial`** — a word in the title, the description or the channel name says the
  upload is somebody's video *about* the work: fan made, concept, gameplay, edit,
  reaction, parody, a short-form repost (`#fyp`/`#viral`/`#foryou`/tiktok), a podcast. It
  leaves the pool with `reason_code: unofficial_source` into
  `evidence.footage_candidates_dropped`, beside the `wrong_work` drops and for the same
  reason: a drop that is recorded is a drop that can be argued with.
- **`unknown`** — neither. Offered, because most honest footage on YouTube comes from
  channels no list will ever hold (`qQNEtu7Uh_c`, "Fooji Aswang Stories", was Rennick's
  usable source), but after every official upload of its own nature.

The answer is written on every candidate as `footage_candidates[].origin`, and `--check`
fails a batch that offers an `unofficial` one.

Both lists — the official channels and the stop words — are **data**, not code: the
official channels are the channel's own list (`<root>/channels/<channel>/footage-origin.json`,
CF-0627 - a science channel's official sources are not film studios), the stop words the
common rule (`config/footage_origin.json`), because they are appended to every time a batch shows a
distributor or a genre nobody had seen. Two rules in that file are decisions of the user
(2026-09-20) and not mechanics: **an official channel is never sieved** (a word in a
Example Studios title is not evidence about a Example Studios upload, and losing the official
trailer to a stop word would be the sieve eating what it exists to protect), and a
studio's small corner logo is not a DoD item 2 violation — burnt-in subtitles, titles and
captions are — which is why `official` is a preference and not a requirement.

Every stop word carries `seen_in`: the real upload, out of a real pool, it was read off.
The price is measured rather than claimed. Over the **46 videos the footage indexer has
ever fetched as a canonical source** in this project, the whole list hits five: the four
fan uploads above and `eTvRCugVK1Q` ("Rennick didn't die 🔥 #rennick #reacherseason4
#foryou", `2026-09-16T2148Z`), which is the same kind of upload. `#shorts` is deliberately
**not** a stop word — it says the upload is vertical and nothing else, and four honest
candidates of the 0116Z pools carry it. On the replay of the whole batch all eight topics
keep at least the two links the gate needs; the numbers are in
`tests/test_footage_origin.py`, on a fixture copied out of the artifacts.

The fifth bad source, `wS6wtevVlmc` (JoBlo Action 4K), claims nothing a stop word can
read — the indexer found out what it was by describing its shots. The sieve is honest
about that and only re-ranks it: Rennick's pool held `FzTtOz1KJ1c` (Prime Video Canada),
so the official clip now leads that nature and the JoBlo upload falls from the second id
the indexer tries to the fourth. Catching it for what it is belongs to the indexer and
the frame judge — `CF-0299`.

## A trailer that lasts two hours is not a trailer (CF-0302)

The nature of a candidate is read off its title, and titles lie. On `2026-09-21T0358Z`
`Lv_GOa6HXVA` — "Lakeside Trailer, Example Pictures Leaving California, People vs. Gorilla
Grodd & More - SMALL ZERO", a 2 h 14 min news podcast with 46 views — was offered as a
`trailer`, because the word is in its title. The indexer downloaded it, was still
splitting its shots 41 minutes later when the run was killed by hand, and the topic died
with `no_second_source`, its attempt budget gone and two untried candidates left over.

The length is the one thing that could have said so, and it comes free: the footage pass
already calls `videos.list`, the Data API charges that call **per call and not per part**,
and `contentDetails.duration` is in the answer. So `fetch_youtube_signal.py` now asks for
`snippet,statistics,contentDetails,status` and writes `duration_seconds` (and, since CF-0662, `yt_license` - `status.license`, `youtube` | `creativeCommon` | null) on every video record
(ISO 8601 → whole seconds; a live stream's or an unstarted premiere's `P0D` → `null`), and
`footage_candidates.py` does two things with it:

- **carries it** into the artifact as `footage_candidates[].duration_seconds`, which is
  where `ingest_batch.measure_candidate` looks first, so the indexer holds the same ceiling
  without one extra request to YouTube;
- **sieves on it** — an upload longer than the ceiling its own nature is held to leaves the
  pool with `reason_code: source_too_long` into `evidence.footage_candidates_dropped`,
  carrying the measured length, the ceiling and the nature. Like the two sieves above it
  happens before grouping and before ranking, so the next real candidate moves up and the
  topic loses no slot.

The numbers are the channel's, not the script's: `channels/<id>.json` →
`sources.youtube.max_source_duration_seconds`, one number or `{nature: seconds}` with an
optional `default`, read exactly the way the indexer reads the same key. For example-film
they are `{"default": 3600, "trailer": 900}`, measured over the 93 accepted sources of
eight batches — 3600 is above the longest source that ever reached a finished video
(3426 s) and below both incidents (4307 s `CF-0281`, 8019 s here); 900 for `trailer`
because that label is put on by one word in a title and the longest trailer ever actually
used is 501 s. `interview` stays on the default on purpose.

An upload nobody measured is **never** dropped — unknown is not long — and a candidate
record written before this task has no `duration_seconds` at all, which `--check` reads as
the older artifact it is rather than as a fault, the same leniency `origin` got on CF-0297.

## A talk about the work is not the work (CF-0309)

`2026-09-21T1541Z` was the first run in which every source the indexer touched came back
with a verdict of the CF-0299 content sieve. It reached 25 candidates: **9 survived, 14
were refused on their content**, 2 could not be fetched. The stage ran 5 h 37 min — every
refused candidate had been paid for in full (the download, ~6 min of indexing per minute
of source, the shot describer) — and four topics died because their good candidates ran
out before their four attempts did.

Nine of the fourteen said what they were in the hunter's own artifact, before a frame was
fetched. So `scripts/footage_sieve.py` asks the fourth question, off the same metadata,
in the same place as the other three — before grouping, before ranking, so a dropped
upload costs the topic no slot:

| rule | what it reads | took of 16 bad | cost of 9 good |
|---|---|---|---|
| `work_not_in_title` | the title names no form of the work **in itself** — CF-0272 accepts the description and the channel too, which is right for a signal and wrong for footage | 3 | 0 |
| `other_works_name` | the name is an article and a noun, the title never says the whole of it, and the bare noun is the tail of another title ("The NFL Odyssey") | 1 | 0 |
| `news_wrap` | three comma-separated items or more, two of them a piece of film news | 1 | 0 |
| `hashtag_title` | hashtags are half of the title or more | 2 | 0 |
| `opinion` | a word that makes the title an argument: "review", "update", "why" | 2 | 0 |
| `press_outlet` | the channel is a film-press or entertainment-news outlet | 2 | 0 |
| **together** | | **10** | **0** |

The drop is `reason_code: not_the_works_footage` into `evidence.footage_candidates_dropped`,
with the rule's name and what was read in the reason. **An official channel is never
sieved**, CF-0297's rule unchanged: `FzTtOz1KJ1c` (Prime Video Canada) was refused for
burned-in credits in 65 % of its shots, and no word in its title says so — that one is the
frame judge's.

**One exception, CF-0924 — `other_work_title`, read for every channel, official included.**
Reel `2026-11-08T1117Z`: the Jon Marrow topic was cut from `jQHoAsDcjVU` "Karōshi (2027)
Official Trailer" (Example Pictures) — a film *from the producer of* Jon Marrow; refused at
acceptance `wrong_work_footage`, the ninth refusal with that code. Two branches:

- *a credit, not a subject* — every naming of the work in the title follows the marketing
  credit formula (`config/footage_sieve.json` `credit_phrases`: "from the producer of",
  "From Zach Cregger, director of", "dari Produser"); the subject is what stands before the
  credit. One naming outside a credit keeps the upload ("Resident Dread – Official Teaser
  Trailer. From Zach Cregger, director of Weapons and Barbarian" is kept);
- *an official upload of another work* — a film or series topic only, the title and the
  channel name no form of the work, and the title's head (text before the first separator)
  holds a Latin word that is not a cut label. A head in another script is unknown, not other.

The drop carries `rule: "other_work_title"` and `title_subject` (what the title is about).
Measured over 42 batches of `pipeline/example*` (1243 candidates, 2026-11-09): it takes 3 —
both Karōshi uploads and `9iCJd_X-zYs` "The Gilded Age Season 4" offered for *Wren Hollow* —
and no candidate of the work. Tests: `tests/test_other_work_title.py`.

The measurement is a fixture, `tests/fixtures/footage_sieve_1541z.json`: the indexer's
verdict on every candidate of that batch, plus the two ids CF-0297/CF-0299 named with
their reasons — 9 good against 16 bad. `tests/test_footage_sieve.py` holds every rule to
both its numbers. **The set is small**, and no rule is in it for its count: each one is a
mechanism statable in a sentence without the data. Measured and left out, with their
numbers: `origin != official` (15 of 16, but **4 of 9** good), `view_count < 1000` (4, and
**2 of 9** — the CLIPREEL cut that survived the sieve had 3 views), a non-official
`interview` (2, and **1 of 9** — that one is the classifier misreading a trailer), `how`
in the title (0), and `official_claim` (2, but its only unique catch was `mtZjyyslZ_s`
against a loss this set cannot measure: an honest reupload that keeps the studio's title).

Since the same task a topic left with **fewer than two** candidates is refused here
(`skipped_topics[]`, `reason_code: no_source`) rather than at the indexer: one candidate
cannot produce the two canonical sources the gate needs.

## Somebody else's host is not our backdrop (CF-0817)

A viewer wrote under the Reel `vanguards-doomsday`: "Stop stealing content. Especially from
the basement yard podcast". Its 2026-10-11 video ran 16 of 16 clips out of Zenith's own
"Countdown to Vanguards: Doomsday Official Podcast" (`nSWnovHSDaY`, `xe3qx0kXArA`), the
2026-10-19 one 10 of 25 (`pdAeUavzpE8`, `nSWnovHSDaY`). The audit (CF-0818, root
`docs/audit-talking-hosts-2026-10-20.md`) found ten published videos with somebody's couch
under our voice - Fallon with Tom Carver for Delver (`ZLXL1L0TfsI`, 8 of 10 clips), Kimmel
with Jessica Chastain for Other Mommy (`uTi2Yiz-8vs`), Sam Meadows with Dana Reyes for
WNL (`d7b1ilF5290`), LIVE with Kelly and Mark with Jessica Lange for American Dread Story
(`keeX8htyf3I`) - and eight of the nine sources came out of this stage's
`evidence.footage_candidates`, already labelled `interview` or `commentary`. They passed
because every sieve before exempts an official channel, and Zenith Entertainment, Jimmy
Kimmel Live and The Evening Show are on the channel's official list.

The user's rule of 2026-10-20: other people's podcast, interview and talk-show hosts are
not backdrop under our voice; trailers, official clips, featurettes and on-set footage stay.
`scripts/host_show.py` over `config/host_show.json` is the last sieve of the footage pass
(`select_candidates`) and of the supplement (`footage_supplement.sieve`), before grouping:

| signal | read on | note |
|---|---|---|
| `show` | title or channel name | named programmes: Fallon / The Evening Show, Kimmel, Colbert / The Late Show, Sam Meadows / Late Night, Graham Norton, Hot Ones, Kelly and Mark, The View, TODAY, GMA, CBS Mornings, Kelly Clarkson, Drew Barrymore, Jennifer Hudson, Ellen, The Late Late Show, Conan, The Daily Show, WWHL, Basement Yard, Pop Culture Confidential, Happy Sad Confused, Actors on Actors; the press-interview outlets (Collider, Etalk, ET, Access Hollywood, Jake's Takes, ScreenSlam) on the channel name only |
| `format` | title or channel name | podcast, talk show, late night, morning show, interview, press junket, roundtable; reaction and review / commentary **not on an official channel** - there they are promo words ("Social Review", "Fan Reactions") |
| `nature` | the classifier | `interview` / `commentary`, only off a channel that is not official and only when read off the title or the room - a studio's "Talk about hanging by a thread" is a promo, a premiere arrival read "interview" off its description is event footage |
| `facets` | the search | nature `unknown` and only talk facets (interview, press conference, podcast) found it |

**`origin: official` does not exempt** a show or a format word: the Zenith podcast is
Zenith's. A show matched on the channel name alone does not take the work's own cut the
channel re-uploaded - a trailer; for a press outlet also a clip or a promo ("Paper Dragon |
Official Trailer" on Showbiz Evening is the trailer). The drop is
`reason_code: host_show` into `evidence.footage_candidates_dropped` (the supplement's
`candidates_dropped`), with the verdict under `host_show`; the shortfall counts it as
`dropped_host_show`.

**One exception**, off existing fields only - no guessing: the topic is about a person and
the upload's **title** names that person - their own interview (`subject_is_guest`). A topic
is about a person when `title_ref.kind` is `person` and its `name` is that person (CF-0439's
"a story about the person"; "Weekend Night Live" with `person: Dana Reyes` is a story
about the work, and Sam Meadows' couch is not its footage), or when the supplement searched
a `kind: person` entity (the uncovered anchor is about them: Danny Vermette's own interview
on Pop Culture Confidential for backrooms). Mechanically also: the topic's own name names
the show (`topic_is_the_show`). The kept candidate carries `host_show: {refused: false,
exception, subject, signals, reason}`; every other candidate `host_show: null`.

Measured on the CF-0309 labelled set (`tests/fixtures/footage_sieve_1541z.json`): the rule
takes 9 of the 16 bad (most already taken by an earlier sieve) and 1 of the 9 good -
`ZLXL1L0TfsI`, the Fallon couch, good by its frames and out by the user's rule. Replayed over
the written batches (`scripts/host_show.py <batch>`, which reads `footage_candidates`) it
refuses every audited source wherever it stood among the candidates - `nSWnovHSDaY`,
`xe3qx0kXArA`, `pdAeUavzpE8`, `ZLXL1L0TfsI`, `d7b1ilF5290`, `uTi2Yiz-8vs`, `KRUYAuhFpi4`,
`keeX8htyf3I` (`3oy35kY7guU` came through the supplement and is covered there). In the
later batches several of them reached the video only through the pool (`topics[].pool.matched`,
the indexer's `from_pool`). That reuse is closed by the footage indexer's `pool_sources.vet()`,
which does not read `config/host_show.json` itself: its `scripts/pool_work_check.py` runs as a
separate process under this agent's venv and calls `host_show.judge()` on the pool's title and
uploader, with `official` from the channel's footage_origin list and the topic's `title_ref` for
the exceptions (the replay: 31 of 150 `from_pool` admissions refused - `ZLXL1L0TfsI`,
`xe3qx0kXArA`, `nSWnovHSDaY`, `d7b1ilF5290`, `gfaACr_Adbc`). This stage's pool bonus asks the
same way and skips them (`topics[].pool.host_show_skipped`). `judge()` is thereby a cross-agent
interface: its signature and verdict keys stay stable. The tests are `tests/test_host_show.py` on trimmed real candidates
(`tests/fixtures/host_show_cf0817.json`).

## One franchise, two films, one candidate list (CF-0444)

`2026-09-29T0705Z` had Vanguards: Endgame (`-004`) and Vanguards: Doomsday (`-005`) in one
batch. The feed read (CF-0361) matched Zenith's uploads for both by the stem "Vanguards",
which `work_forms` counts as naming either film, and both topics left step 5b with the
same six ids. Doomsday was built on Endgame's trailers and rejected by the frame judge
(`wrong_work_footage`) after three renders — the first stage to notice.

`select_candidates` now drops, right after the CF-0272 rule and before ranking, an upload
whose **own title** names the work only by the colon stem or the `parent_work`
(`reason_code: other_installment`, official channels not exempt). The forms are
`topic_relevance.installment_forms` — the one place the rule lives; the indexer's pool
check (`footage-indexer/scripts/pool_work_check.py`, CF-0325) asks the same forms of a pool
source and `tests/test_other_installment.py` holds the two together. A sequel number alone
does not trigger it (a sequel's press says "returning to Everyday Sorcery").
Replayed on 0705Z's own feed reads: Endgame keeps its Encore trailers and featurette,
Doomsday gets only uploads titled Doomsday, the two lists share no id. A topic the rule
leaves with fewer than two candidates walks the ordinary ladder — its feed file asks for
the facet search (`fallback_search`), then `no_source` and the reserve.

Two topics that still end with the same set of ids are written to
`footage_candidates_shared` in the batch file (`reason_code: same_candidate_list`) and
printed as a `WARNING` line in a fill and in `--check` — a warning for the step-8 report,
not a failed check.

## The title names the number, the description does not outrank it (CF-0577)

`KTe9OatvQas` "Dana Reyes Monologue - WNL", uploaded by Weekend Night Live, was
written `nature: interview` on `2026-10-04T1825Z` and `2026-10-05T0701Z`. Not because a
search facet found it (`facets` is never read by the classifier — "Mean, Scary
Girlfriend - WNL" was found by the trailer facet and stays `unknown`), but because
`classify()` used to read title + channel + the head of the description as one string
against the rules in rule order, and an WNL description says the host "talks about"
something. The writer and the sieve read that nature as it is; the video editor
had to work around it by the work's own channel (CF-0545).

`classify()` now reads in order of trust, and the first reading that says something
decides (`classify_with_source()` also returns which one):

1. **title** — the KIND_RULES; a monologue, a sketch and a Weekend Update segment are
   numbers of the show (`episode`), and "breaks down" / "dishes on" is a person talking
   (`interview`);
2. **room** — a talk show named as a trailing `| ...` tag of the title or as the
   uploader's channel (`TALK_SHOW_RE`: "Late Night with Sam Meadows", "The Evening Show
   Starring Jim Fenwick", …) is an `interview`. A show named at the head of the title is
   the subject, not the room ("The Late Show with Stephen Colbert Wins Outstanding
   Variety Series | 78th Emmy Awards | NBC");
3. **description** — its first 240 characters;
4. **channel** — the words of the channel's name, last: "Scene Flix Studios" and "Red
   Carpet Trailers" say nothing about one upload.

Price on history (all 24 `pipeline/example-film/*/01-trend-hunter.json`, 1031 candidate
records, read only): a written batch keeps no descriptions, so only the records the
title or the room decide can be replayed with certainty — **19 records (13 uploads) in
9 batches change nature**: 6 interview→episode (the WNL monologue ×2, "Quill … | Clip |
Prime Video", "Blood of my Blood Season 2 Episode 2 Trailer" ×2, "Tom Holland and
Christopher Nolan almost spoil a scene"), 4 featurette→interview (Zach Cregger "Breaks
Down Scenes" ×3, "Producers Dish On…"), 2 interview→trailer ("The Diplomat Season 4 |
Official Trailer" from the channel Red Carpet Trailers, "Rennick Season 5 Teaser"),
2 episode→promo (MobLand 2x02 Promo), 2 commentary→episode (a reupload of the WNL
monologue), 1 episode→trailer (My Hero Academia teaser), 1 featurette→episode (American
Horror Story "First Look"), 1 unknown→interview (a Tonight Show short). The other 232
records that are not `unknown` were decided by the description or the channel's words,
and those readings still apply when the title and the room are silent.
