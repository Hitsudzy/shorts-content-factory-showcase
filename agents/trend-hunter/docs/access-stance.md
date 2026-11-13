# Access stance and request ceiling

What the RSS fetch relies on in the sources' `robots.txt`, what it takes, and why
the per-feed request ceiling is the number it is. The same position is written
at the top of [`scripts/fetch_rss_news.py`](../scripts/fetch_rss_news.py). The
overview is the [README](../README.md).

## The channel's AI-bot rule (CF-0557 → CF-0635 → CF-0634)

Since 2.3 the stance per feed is the channel's data, not this page: every feed of
`channels/<channel>.json` → `sources.rss.feeds` carries a `use` and an `ai_policy`
(the root's `docs/channel-data.md`, «Sources and the AI-bot rule»), and
`fetch_rss_news.py --channel <channel>` reads only what `channel_data.feed_urls` gives -
a channel whose feeds break the rule is refused, nothing is fetched. A `headline_only`
feed (example-film's four: the PMC trades, whose terms forbid grounding AI on their
content, and Vulture) chooses topics - headline, link, date, the house count - and its
excerpt never reaches the writer: `support_text.py` makes an `rss_summary` piece only of
a `read_text` feed (`channel_data.support_feed_urls`, the user's decision of 08.10);
since CF-0638 neither is a post of such a feed a fact candidate (`fact_search.news_candidates`,
"Variety reported ...") nor is its summary written into `evidence.sources[]`
(`evidence_sources.py`, `summary: null`) - the Content Researcher reads `01` whole. A
text off a host other than Wikipedia is read only through `scripts/source_gate.py`
(`use: read_text` and `allowed` in the channel's `fact-sources.json`); the first such host
is TVmaze's API (CF-0636: episode descriptions, CC BY-SA 4.0, the shared client
`shared/tvmaze/tvmaze_api.py` - one host, GET only, >= 0.5 s apart, cached for an hour in
`work/tvmaze-cache/`, its gate `source_gate.check`); then Wikidata (CF-0637: the work's
statements, CC0, the shared client `shared/wikidata/wikidata_api.py` - the Wikidata search
of api.wikimedia.org and `www.wikidata.org/wiki/Special:EntityData/<Q>.jsonld`, GET only,
>= 1 s apart, <= 3 requests a topic, cached for a day in `work/wikidata-cache/`, its gate
`source_gate.check` - the `wikidata` outlet asked before the search). The CF-0045 position
below still holds for how the feeds are read.

## Access stance and request ceiling (CF-0045 → CF-0059)

The position, decided 2026-09-03 and written into the header of `scripts/fetch_rss_news.py`
so it reads from the code:

- **What we rely on.** Under `User-agent: *` the trades' `robots.txt` (Variety, Deadline,
  THR carry the same file) disallows only `/wp-admin/`, site search, `?replytocom`,
  `/genre/` and preview URLs. Neither `/feed/` nor `/wp-json/` is disallowed for `*` —
  open by robots.txt's default, not by an explicit `Allow` line. The sitewide `Disallow: /`
  blocks are under named AI crawlers only (`anthropic-ai`, `ClaudeBot`, `Claude-Web`,
  `GPTBot`, `CCBot`, `PerplexityBot`, …). The script goes under its own honest name and
  claims to be neither a browser nor one of those. A site that wanted its REST collection
  closed to everyone would write `Disallow: /wp-json/` under `*`; none has.
- **What we take.** Title, link, publication date and an excerpt cut to 500 characters
  (`REST_FIELDS` is the whole list). Article bodies are never requested: topic selection by
  headline, not material for retelling.
- **What we send, and why that number.** `DEFAULT_MAX_REQUESTS_PER_FEED = 12`. The measured
  need for the deepest window the skill asks for (`--days 14`) is 9 requests on the busiest
  trade — one feed page plus 8 REST pages of 100 for 772 posts — so 12 is that plus a
  third: room for ~80 posts a day before the stop engages, and a hard bound of 1,200 posts
  per feed per run instead of the 2,500 the earlier, never-measured 25 allowed. The
  ceiling is an emergency stop, not a working limit: if a configured feed ever stops on
  `max_requests` rather than `covered` / `source_exhausted` at a normal `--days`, the
  default is under the need and is raised from a new measurement, not by guess.
  `--max-entries-per-feed` stays at 0 on purpose — the request ceiling already bounds
  entries, and a second default would just be a second number that can drift.
- **How the next question gets answered.** Every batch keeps the fetch's telemetry under
  `discovery.rss` in `01-trend-hunter.json` — per feed `strategy`, `requests_made`,
  `max_requests`, `stopped_because` (plus the rest of the coverage row). The five batches
  before CF-0059 kept none of it, which is why 25 could not be justified after the fact.
  The stance is source-agnostic; a feed added later inherits it as is.
- **Vulture (CF-0060, read 2026-09-03).** `vulture.com/robots.txt` has the same shape as
  the PMC file: under `User-agent: *` it disallows only `/search/`, `/search.html`,
  `/newyork/`, `/contactus/` and `*?origSession=*` — nothing that touches the feed, which
  is open by default, not by an `Allow` line. The `Disallow: /` blocks are under named
  agents only (`anthropic-ai`, `ClaudeBot`, `Claude-Web`, `Claude-User`,
  `Claude-SearchBot`, `GPTBot`-class crawlers, `python-requests`, `Scrapy`, …), and this
  script is none of them. The feed itself is served by FeedBurner, whose own `robots.txt`
  is a redirect stub; the position is taken on the publisher's file, which is the one
  that speaks for the content. Same stance, same fields, same ceiling — and the feed
  costs 2 requests a run.
