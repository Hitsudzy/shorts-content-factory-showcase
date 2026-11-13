# CF-0914: the vendors behind the `vendor_page=no_link` refusals (ExampleTech, 25.10-02.11)

This is input for the root worker that owns `channels/example-tech/fact-sources.json`. The
Trend Hunter does not edit that file. Each domain below still needs its robots.txt and terms
checked against the source rule of 08.10 before it gets `ai_policy.verdict: allowed`. Being
on this list is not permission.

## What the records say

There are seven Tech batches from 2026-10-25 to 2026-11-02, counting the 2026-11-02T0909Z
re-run. Between them they hold **157 `no_fact` refusals with `vendor_page=no_link`** and 20
with `newsroom_no_match`: 177 records, 170 distinct topics. Repeats held by the no_fact
memory (45 records) are not counted.

Why the CF-0810 newsroom path did not fire for them, replayed with
`scripts/vendor_feed_replay.py` against today's list:

| why | topics |
|---|---|
| no tier-1 company is named at all (the vendor is not on the list, or the story is not a company announcement: settlements, IPO coverage, breaches, reviews) | 114 |
| a tier-1 company is named, but its verdict is not `allowed`: anthropic.com/claude.com 18, apple.com 5, nvidia.com 4, samsung.com, tesla.com, waymo.com, rivian.com, cohere.com 1 each. Named only, never read, and that stays the rule | 32 |
| an `allowed` row is named but lists no `newsroom`: openai.com 7, intel.com, micron.com, qualcomm.com 1 each | 10 |
| a newsroom index was read and no link on it named the work's whole name: google 4, meta 6, lenovo 2, github 1, mistral 1 | 14 |

Three causes sit in the code and are fixed by CF-0914:
1. An index could only be HTML, so a vendor's RSS feed could not be used.
2. A release was matched only by the work's whole name. "GM Smart Driver" never matches a
   GM post titled "Smart Driver".
3. The reason did not say which company was named.

The rest is list data, below.

## Changes to rows already on the list (no new domains)

| row | change | checked 2026-11-02 with the hunter's User-Agent |
|---|---|---|
| `openai` | `newsroom: ["https://openai.com/news/rss.xml"]` | feed 200 `text/xml`, 1341 items; robots `*` Allow /. **Posts answer 403** to the hunter: with CF-0914 a post is told from its feed entry |
| `google` | add `https://blog.google/rss/` to `newsroom` | 200 `application/xml`, 20 items |
| `microsoft` | `names: ["Microsoft", "Windows", "Xbox", "Azure", "Copilot"]`; optionally `https://news.microsoft.com/source/feed/` in `newsroom` | feed 200 `application/rss+xml`. "Azure" and "Windows 11 Xbox mode" never named the company |
| `ai_labs_terms_unread` (x.ai) | `names: ["xAI", "Grok"]` | x.ai/news answers 403; no feed known. Covers 3 topics (Grok Republicans, Grok Odyssey, Jess Asato xAI) |
| `chipmakers*` (intel, micron, qualcomm) | a newsroom each, if their terms allow | newsroom.intel.com 200 (feed path not checked); micron.com/about/blog 200; investors.micron.com 403 |

## Vendor domains not yet tier-1

"Checked" means one GET with the hunter's User-Agent on 2026-11-02 (status and content type
only). Robots.txt was read for nscale, redditinc and news.gm.com only. **Every other row still
needs robots.txt and terms.**

| company | domain(s) | newsroom / blog | feed | checked | refused topics (distinct) |
|---|---|---|---|---|---|
| General Motors | news.gm.com (gm.com) | https://news.gm.com/home.html | none found | 200 HTML. robots: allowlist style with no `*` group; Claude-SearchBot named with crawl-delay 10; ClaudeBot not named. Root to judge | Smart Driver, GM Smart Driver data, GM Smart Driver, GM driver data settlement (4) |
| Nscale | nscale.com | https://www.nscale.com/blog | none found | 200 HTML; robots.txt empty | Nvidia Nscale, Nscale West Virginia data center (2) |
| Reddit | redditinc.com | https://redditinc.com/news | https://redditinc.com/news/rss.xml | feed 200 `text/xml`; robots `*` disallows previews only | Reddit, Reddit logged-in-only (2) |
| Valve | steampowered.com, valvesoftware.com | https://store.steampowered.com/news/ | https://store.steampowered.com/feeds/news/ | feed 200 `text/xml` | Valve HLX, Steam Frame, F-Stop (3) |
| Cursor (Anysphere) | cursor.com | https://cursor.com/blog | not found | 200 HTML | Cursor Marketplace and the "Anthropic VS Code extension on Cursor" stories (4) |
| Anduril | anduril.com | https://www.anduril.com/news | not found | 200 HTML | Warhound Anduril, BlueChip (2) |
| Salesforce | salesforce.com | https://www.salesforce.com/news/ | /news/feed/ answers 302 (target not checked) | - | Salesforce Rune acquisition, Salesforce Rune (2) |
| Boom Supersonic | boomsupersonic.com | https://boomsupersonic.com/news | not found | 200 HTML. Give `names: ["Boom Supersonic"]` only: "boom" is an everyday word | Boom Supersonic airliner, Boom Supersonic (2) |
| Nissan | usa.nissannews.com | https://usa.nissannews.com/en-US/releases | not found | 303 (target not checked) | 2027 Nissan Rogue Hybrid (2 titles) |
| DoorDash | about.doordash.com | https://about.doordash.com/en-us/news | not found | **403** to the hunter | DoorDash AI agents, Instacart DoorDash (2) |
| Ford | media.ford.com | https://media.ford.com/content/fordmedia/fna/us/en/news.html | not found | 301 (target not checked); www.ford.com/news 200 | Ford Fathom (1) |
| LG Electronics | lgnewsroom.com | https://www.lgnewsroom.com/ | https://www.lgnewsroom.com/feed/ answers 301 | lg.com/us/press-release 200 | LG B6 OLED (1) |
| Vizio | vizio.com | not checked | - | - | Vizio Mini LED TV (1) |
| TikTok | newsroom.tiktok.com | https://newsroom.tiktok.com/en-us | not found | 301 | TikTok super app (1) |
| Toyota | pressroom.toyota.com | https://pressroom.toyota.com/ | https://pressroom.toyota.com/feed/ | feed 200 RSS | Waymo Toyota bZ4X (1) |
| Raspberry Pi | raspberrypi.com | https://www.raspberrypi.com/news/ | https://www.raspberrypi.com/news/feed/ | feed 200 RSS | Raspberry Pi Zero 3W (1) |
| Oura | ouraring.com | https://ouraring.com/blog/ | https://ouraring.com/blog/feed/ | feed 200 RSS | Oura (1) |
| Railway | blog.railway.com, railway.com | https://blog.railway.com/ | https://blog.railway.com/rss.xml | feed 200 RSS | Railway (1) |
| Tailscale | tailscale.com | https://tailscale.com/blog | https://tailscale.com/blog/index.xml | feed 200 `text/xml` | Tailscale SSH (1): **the topic's lead is the vendor's own post** |
| Cerebras | cerebras.ai | https://www.cerebras.ai/blog | not found | 200 HTML | Cerebras Deploys Trillion-Parameter AI (1): **lead is the post** |
| Trigger.dev | trigger.dev | https://trigger.dev/blog | not found | 200 HTML | Trigger.dev (1): **lead is the post** |
| Ghostty | ghostty.org | https://ghostty.org/docs/install/release-notes | not found | 200 HTML | Ghostty 1.4 (1): **lead is the post** |
| Quest Diagnostics | newsroom.questdiagnostics.com | https://newsroom.questdiagnostics.com/ | not found | 200 HTML | Quest Diagnostics breach (1) |

Seen once each, URLs not checked, low priority: Granola (granola.ai), Northflank
(northflank.com; the lead was status.northflank.com), Firezone (firezone.dev; lead of
"sans-IO"/"Sanstun"), Artificial Analysis (artificialanalysis.ai; lead of "Index v5"),
Fujifilm, Jackery, BioLite, Seoul Viosys, Daytona, The Browser Company (Arc), Guidewire,
Thrive Holdings, Zest AI, Instacart, Bank of America, Python Software Foundation (python.org),
the Tor Project.

Every row needs `names` that are the company's own words and not everyday English. A name like
"Boom" turns "AI spending boom" into a Boom Supersonic topic. CF-0914 also never cuts another
listed company's name off a work.

## Replay (records only, no network in the replay itself)

`scripts/vendor_feed_replay.py --root <factory> --channel example-tech --since 2026-10-25
--until 2026-11-02`. Run once with today's list, then with a copy that adds the rows above as
`allowed`, plus the openai and google feeds and the microsoft/xai names. For five vendors,
copies hand-read on 2026-11-02 (openai feed, blog.google feed, news.gm.com index, nscale blog,
redditinc feed) were passed with `--feeds`. Distinct topics, 170 refused:

| verdict | today's list | with the proposals |
|---|---|---|
| `pool_link`: the vendor's own post is reached directly (its lead or a pool entry) | 0 | 4 (Cerebras, Tailscale, Ghostty, Trigger.dev) |
| `feed_match`: a saved feed or index names the work | 0 | 0 |
| `feed_no_match`: read, nothing names the work (OpenAI 7: reports, not OpenAI posts; GM 4: the Smart Driver settlement is not on GM's newsroom; Google 4; Reddit 4, two of them Apple HomeView stories whose lead mentions Reddit; Nscale 2) | 0 | 21 |
| `feed_unsaved`: would be read, outcome unknown | 14 | 38 |
| `named_closed` | 32 | 23 |
| `named_unindexed` | 10 | 5 |
| `unnamed` | 114 | 79 |

Ceiling: with the proposals, **42 of 170 refused topics reach a vendor page or feed** (4 + 38).
Of the 21 checked against live copies, none had a post that names the work. Most of the 157 are
press stories the company itself never posts (settlements, IPO coverage, funding reports,
breaches), or are told about a `forbidden` vendor. The surest gain is the 4 topics whose lead
is the vendor's own post: they need only their domain on tier 1. Whether a post's sentences
pass the fact rule is not replayed, because the posts were not saved.
