#!/usr/bin/env python3
"""CF-0551: the topic's support text - what the story may be told from.

The user's rule (grill of 2026-10-05, CF-0546): invented facts must not be
created at all. Until 1.8 a topic reached the writer with its headline and an
RSS summary of at most 500 characters (`fetch_rss_news.py`), and the plot was
filled in by the model: the published coach-hale had "Anthony Hart played Mae",
the accepted harbourlights "Zorvath is behind the kill" (it was Sheriff Kerry
Kane). Q1 of that grill: the topic carries text. Q9: from Wikipedia only - the
work's article, its season's article, the episode descriptions - plus the RSS
summaries as they were fetched (narrowed by CF-0634: only a `read_text` feed's).
Variety / Deadline / THR / Vulture are **not**
downloaded under any User-Agent: their robots.txt names `anthropic-ai`,
`ClaudeBot` and `Claude-Web` and disallows them. Q7: a topic with no support
text for its own event leaves here, before the indexer pays for it, and its
slot goes to the next topic by rank; this stage checks that the text is
*there*, not that it is *enough* (that is CF-0552/CF-0553's).

What a topic gets, as `topic["support_text"]` (a list, in this order):

  * `work_article`    - the article the fact probe resolved for the topic
                         (`fact_probe.article`), whole, as plain text;
  * `season_article`  - for a series with a season: the season's own article,
                         found as the work article transcludes it
                         (`{{:Rennick season 4}}`, `{{:The Celebrity Traitors
                         series 2}}`), else asked for as `<Show> season N`;
  * `episode_summary` - every non-empty `ShortSummary` of the season's
                         `{{Episode list}}` rows (in the season article, else
                         in the work article - Harbourlights keeps them there), one
                         piece per episode, with its number, title and air date;
  * `tvmaze_episode`  - for a topic about an episode (below): TVmaze's
                         description of that episode, once it has aired
                         (CF-0636, below);
  * `wikidata_statement` - the work's statements on Wikidata of the channel's
                         `properties` (a date, the cast, the crew, the studio,
                         the network, an award), one sentence each
                         (CF-0637, below);
  * `rss_summary`     - the topic's own news leads, headline and summary as
                         they were fetched, with their URL - only of a feed
                         whose `use` is `read_text` (CF-0634, below);
  * `vendor_page`     - CF-0771: for a topic with **no Wikipedia article of
                         its own** (a product launched this week), the
                         company's own post - the one CF-0757 reads for the
                         fact (`vendor_page.official_links`: the topic's news
                         that is the post, a link in it, a company feed's
                         entry naming the work; CF-0810: and the release the
                         fact search found on the vendor's newsroom index,
                         `pages[].how: newsroom`) - its main text
                         (`<article>`/`<main>`, `vendor_page.html_text`), at
                         most `VENDOR_TEXT_MAX` characters, with `source`
                         `vendor_page`, `outlet` (the list's id), `publication`,
                         `title`, `url`, `fetched_at` and null revision
                         fields. Read only through `source_gate.
                         read_vendor_page` (tier 1, `ai_policy` `allowed` - the
                         rule of 08.10); a post that does not name the work is
                         no piece. It makes the state `ok` in place of the
                         missing article; a topic with an article is told from
                         the article, as before. Quotable like any piece: the
                         writer's claims cite its `id`, and `claims.py` finds
                         the quote in its `text`;
  * `own_capture_record` - CF-0567, ExampleTech only: the factory's own record
                         of an own capture (the Space `<owner>/<name>`, "Hugging
                         Face Space", the page, the capture time, the steps
                         completed), one per own capture, added by
                         `footage_candidates.py` at step 5b
                         (`own_capture_text.py`). Never the fact, never a
                         second source, never changes the state.
  * `api_demo_record` - CF-0690, ExampleTech only: the factory's own record
                         of an API demo call (the prompt sent, the model by
                         the channel's display name, "the Gemini API", the
                         day, the model's verbatim answer), one per topic
                         with an `ok` `api_demo_record`, added by
                         `fetch_api_demo.py` / `footage_candidates.py` at
                         step 5b (`api_demo_text.py`). Never a fact, never
                         counted toward the own-graphics floor, never a
                         second source, never changes the state.

**The feeds choose topics; they are not text** (CF-0634, the user's decision
of 08.10 on CF-0557 Q1, variant b). A channel's feed carries a `use`
(`channels/<id>.json` -> `sources.rss.feeds[]`, root `docs/channel-data.md`
«Sources and the AI-bot rule»): `headline_only` - headline, link and date
choose the topic and nothing of the feed reaches the writer; `read_text` -
its excerpt may be an `rss_summary` piece. example-film's four feeds (the PMC
trades - their terms forbid grounding AI on their content - and Vulture) are
`headline_only`, so a example-film topic's support text is Wikipedia's alone.
The list is `channel_data.support_feed_urls(channel)`, asked once a batch
(`fact_probe_topics.make_supporter`); without it no excerpt goes on.

**Text from a host that is not Wikipedia** is read only through
`source_gate.read_text` (CF-0634): the outlet of the channel's
`fact-sources.json` must be `use: read_text` with `ai_policy.verdict:
allowed`. The first such host is TVmaze (CF-0636): its client's gate is
`source_gate.check` with the channel's list, called before every request.

**TVmaze's episode descriptions** (CF-0636, the user's decision of 08.10 on
CF-0557 Q2). Wikipedia writes an episode's ShortSummary hours after the
broadcast; in the October measurement 7 of the 9 "an episode aired" topics
had none at the batch's hour (root `docs/sources-pool-2026-10.md`). TVmaze's
API gives each episode's description under CC BY-SA 4.0 (credited by the
publisher in the video's description). So for a topic whose leads name an
episode (`event_of`), the shared client (`shared/tvmaze/tvmaze_api.py`, found
by `_tvmaze.py`, cached in `<batch>/work/tvmaze-cache/`) is asked for the
show (`resolve_show`: the same name, and the topic's network when it knows
one - the API's best for "Bunker" is the Spanish "Búnker") and for the
episode the event names (`event_episode`). Its description becomes a
`tvmaze_episode` piece only when the episode **has aired** by the batch's
time (`tvmaze_api.aired` - TVmaze writes a synopsis before the broadcast, and
that is an announcement, not the episode) and, when Wikipedia's list resolved
the event to a row of its own, only when both name the same episode. The
piece stands in for the missing ShortSummary: an aired episode Wikipedia has
no description of yet, or one no Wikipedia episode list names, is `ok` on it.
Beside a ShortSummary it is a second source (`claim_judge.SECOND_SOURCE_KINDS`).
A channel whose fact-sources list does not name the outlet `read_text` /
`allowed` asks TVmaze nothing (`fact_probe_topics.make_supporter`); a TVmaze
that cannot be read (`TvmazeError`) leaves the Wikipedia verdict as it was -
it never makes a topic unreachable. Its requests are counted apart from
Wikipedia's (`support_check.tvmaze`, the batch's `selection.tvmaze`), at most
`MAX_TVMAZE_REQUESTS_PER_TOPIC` a topic.

**Wikidata's statements** (CF-0637, the user's decision of 08.10 on CF-0557
Q2). Once the topic's article is read, the item whose English Wikipedia
sitelink is the work's article (the show's, for a season) is found through the
shared client (`shared/wikidata/wikidata_api.py`, found by `_wikidata.py`,
cached in `<batch>/work/wikidata-cache/`; `fact_search.wikidata_lookup` -
the fact search asked it first in the same pass, so it costs nothing here) and
its statements of the channel's `properties` are `wikidata_statement` pieces:
structured, checkable, CC0 - quotable for a date, a cast, a crew, a studio, a
network or an award fact, never a second source for a fresh reveal. They
**never change the state**: a topic with no Wikipedia text stays `no_text`, a
Wikidata that cannot be read (`WikidataError`) never makes it `unreachable` -
`support_check.wikidata` says what was asked. A channel whose list does not
name the outlet `read_text` / `allowed` asks Wikidata nothing
(`fact_probe_topics.make_supporter`). At most
`MAX_WIKIDATA_REQUESTS_PER_TOPIC` requests a topic, counted apart.

Every piece has `id`, `kind`, `source`, `title`, `url`, `revision_id`,
`revised_at`, `text` (`revision_id`/`revised_at` are Wikipedia's `latest.id`
and `latest.timestamp` of the answer the text was read from - CF-0554 holds a
reveal until that text has stood for 6 hours; an RSS piece has `published_at`
instead and null revision fields; a TVmaze piece has `fetched_at` - when
its text was read - and null revision fields; a Wikidata piece the item's
revision and `modified`, `fetched_at`, and its property, value and
qualifiers).

**The topic's event.** A topic about an episode - a finale, a premiere,
"season 1 episode 8", "S4E1", "4x09", "Episode 409" (season 4 episode 9 -
`episode_number`, CF-0581) in its own leads - is about *that episode*, and
the article of the show does not tell it: the finale of Harbourlights is in no
section of the Harbourlights article but its ShortSummary. So when the leads name an
episode of a series and the episode has aired, its ShortSummary must be there;
Wikipedia writes it ~2-3 hours after the broadcast (Rennick S4E1, the Harbourlights
finale), and a batch that runs in that gap drops the topic rather than letting
the writer guess. An episode that has not aired yet is not the event (the news
is an announcement) and the work's article is the text. A topic with no event
episode needs Wikipedia text of its work - an RSS summary alone is the state
this task exists to end.

States, under `topic["support_check"]`:

  ok           - the text is there (and the event episode's, when there is one);
  no_text      - Wikipedia answered and there is none: no article of the
                 topic's own (and no company post that names the work -
                 CF-0771), an empty one, the event episode without a
                 description, or an event episode the articles do not list -
                 and TVmaze has no description of that aired episode either.
                 The topic leaves with `no_support_text`;
  unreachable  - Wikipedia could not be asked. Not "no text": the topic stays,
                 marked, and the stage report says so (the fact probe's rule
                 for its own outage, CF-0185) - the writer cannot quote what it
                 was not handed and refuses it there (CF-0552).

The network goes through the shared client (`_wikipedia.py`), cached in
`<batch>/work/wikipedia-cache/` with a short life (`CACHE_MAX_AGE_SECONDS`):
an episode description appears hours after the broadcast, so a week-old answer
that the researcher's cast check would happily reuse is the wrong answer here.
At most `MAX_REQUESTS_PER_TOPIC` page requests a topic, serial, >= 1 s apart.

Usage as a library (`fact_probe_topics.py` step 5a calls `support_topic`), or
for one topic of a batch, read-only:

    scripts/support_text.py <batch-dir|01-trend-hunter.json> --topic <topic_id>
"""
import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fact_search  # noqa: E402
import source_gate  # noqa: E402  - CF-0636: the TVmaze client's gate

SUPPORT_KEY = "support_text"
CHECK_KEY = "support_check"
REFUSAL_CODE = "no_support_text"
STAGE = "trend-hunter"
TOOL_NAME = fact_search.TOOL_NAME   # the hunter's name in the User-Agent

STATE_OK = "ok"
STATE_NO_TEXT = "no_text"
STATE_UNREACHABLE = "unreachable"

KIND_WORK = "work_article"
KIND_SEASON = "season_article"
KIND_EPISODE = "episode_summary"
KIND_RSS = "rss_summary"
KIND_TVMAZE = "tvmaze_episode"      # = shared/tvmaze/tvmaze_api.KIND_EPISODE (CF-0636)
KIND_WIKIDATA = "wikidata_statement"  # = shared/wikidata/wikidata_api.KIND_STATEMENT (CF-0637)
KIND_VENDOR = "vendor_page"         # CF-0771: the company's own post, its main text
SOURCE_VENDOR = "vendor_page"       # the piece's `source`
#: the most of one post's text a piece carries (a launch post's article is a
#: few thousand characters; a page past this is cut and says so)
VENDOR_TEXT_MAX = 20_000
#: posts read for one topic's text - the fact's ceiling (`vendor_page.PAGES_PER_TOPIC`)
VENDOR_PAGES_PER_TOPIC = 2
WIKIPEDIA_KINDS = (KIND_WORK, KIND_SEASON, KIND_EPISODE)

# An episode description is written hours after the broadcast; an answer
# older than this is asked again.
CACHE_MAX_AGE_SECONDS = 3600
MAX_REQUESTS_PER_TOPIC = 4
# CF-0636: TVmaze, counted apart - the show (`singlesearch`), then the episode
# by number or the show's episode list, and the list once more only for a
# season code that names no episode of its season (`tvmaze_api.event_episode`).
MAX_TVMAZE_REQUESTS_PER_TOPIC = 3
# CF-0637: Wikidata, counted apart - a search and at most two entity reads
# (`wikidata_api.MAX_REQUESTS_PER_TOPIC`), once a pass for the fact search and
# the support text together (`fact_search.wikidata_lookup` keeps the answer).
MAX_WIKIDATA_REQUESTS_PER_TOPIC = 3
# A day: statements change slowly (`wikidata_api.CACHE_MAX_AGE_SECONDS`).
WIKIDATA_CACHE_MAX_AGE_SECONDS = 24 * 3600

# The probe's outcomes under which its `article` is the topic's own article
# (`fact_search.ARTICLE_OUTCOMES`: not `wrong_article`, not `no_article`).
ARTICLE_OUTCOMES = fact_search.ARTICLE_OUTCOMES
UNREACHABLE_OUTCOMES = ("source_unreachable", "unreachable")

TV_TYPE_RE = re.compile(r"tv|series|show|miniseries|season", re.I)
SEASON_TITLE_RE = re.compile(r"^(?P<base>.+?)\s+(?:season|series)\s+(?P<n>\d+)$", re.I)


# --------------------------------------------------------------------------
# wikitext: balanced templates, the Episode list, plain text
# --------------------------------------------------------------------------

def _template_end(text, start):
    """Index just past the `}}` that closes the template opening at `start`."""
    depth, i, n = 0, start, len(text)
    while i < n - 1:
        pair = text[i:i + 2]
        if pair == "{{":
            depth += 1
            i += 2
            continue
        if pair == "}}":
            depth -= 1
            i += 2
            if depth == 0:
                return i
            continue
        i += 1
    return n


def _split_params(body):
    """A template's body split at its own `|` - not at a `|` inside a nested
    template or a link."""
    parts, depth_t, depth_l, cur, i = [], 0, 0, [], 0
    while i < len(body):
        two = body[i:i + 2]
        if two in ("{{", "}}", "[[", "]]"):
            depth_t += {"{{": 1, "}}": -1}.get(two, 0)
            depth_l += {"[[": 1, "]]": -1}.get(two, 0)
            cur.append(two)
            i += 2
            continue
        ch = body[i]
        if ch == "|" and depth_t == 0 and depth_l == 0:
            parts.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
        i += 1
    parts.append("".join(cur))
    return parts


EPISODE_LIST_RE = re.compile(r"\{\{\s*Episode[ _]list(?:/sublist)?\s*[|}]", re.I)
SEASON_HEADING_RE = re.compile(r"^={2,6}\s*(?:season|series)\s+(\d+)\b.*?={2,6}\s*$",
                               re.I | re.M)


def episode_rows(wikitext):
    """Every `{{Episode list}}` / `{{Episode list/sublist}}` row of the text:
    `{number, number_in_season, title, air_date, summary, season_heading}`,
    in the order written. `summary` is plain text, "" when the row has none
    (a row with only the editors' `<!-- Please limit plot summaries -->`
    comment has none)."""
    rows = []
    text = wikitext or ""
    headings = [(m.start(), int(m.group(1))) for m in SEASON_HEADING_RE.finditer(text)]
    for m in EPISODE_LIST_RE.finditer(text):
        end = _template_end(text, m.start())
        body = text[m.start() + 2:end - 2]
        fields = {}
        for part in _split_params(body)[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            fields[key.strip().lower()] = value.strip()
        season_heading = None
        for pos, number in headings:
            if pos < m.start():
                season_heading = number
        rows.append({"number": _int(fields.get("episodenumber")),
                     "number_in_season": _int(fields.get("episodenumber2")),
                     "title": plain_inline(fields.get("title") or "") or None,
                     "air_date": air_date(fields.get("originalairdate") or ""),
                     "summary": plain_inline(fields.get("shortsummary") or ""),
                     "season_heading": season_heading})
    return rows


def _int(value):
    m = re.match(r"\s*(\d+)", value or "")
    return int(m.group(1)) if m else None


_MONTHS = {m: i for i, m in enumerate(
    ("january", "february", "march", "april", "may", "june", "july", "august",
     "september", "october", "november", "december"), start=1)}


def air_date(value):
    """`YYYY-MM-DD` out of `{{Start date|2026|10|08|df=yes}}` or a written
    date ("October 8, 2026", "8 October 2026"); None when there is none."""
    m = re.search(r"\{\{\s*(?:Start|Film) date\s*\|\s*(\d{4})\s*\|\s*(\d{1,2})\s*\|\s*(\d{1,2})",
                  value or "", re.I)
    if m:
        y, mo, d = (int(x) for x in m.groups())
    else:
        text = re.sub(r"<[^>]*>|\{\{[^{}]*\}\}", " ", value or "")
        m = (re.search(r"([A-Za-z]+)\s+(\d{1,2}),?\s+(\d{4})", text)
             or re.search(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", text))
        if not m:
            return None
        a, b, y = m.groups()
        if a.isdigit():
            a, b = b, a
        mo, d, y = _MONTHS.get(a.lower()), int(b), int(y)
        if not mo:
            return None
    try:
        return dt.date(y, mo, d).isoformat()
    except ValueError:
        return None


def plain_inline(text):
    """A fragment of wikitext (an Episode list row's title or summary) as the
    reader sees it - the same reading as `plain_article` (CF-0673)."""
    return fact_search.plain_text(text)


def plain_article(wikitext):
    """The whole article as plain text: the lead and every section, headings
    kept as `== Heading ==` lines, lists as `- item`; tables, templates
    (infobox and the Episode list rows included - those are pieces of their
    own), references and the reference / link sections dropped; `{{val}}` and
    `{{convert}}` as their numbers in the page's own unit.

    CF-0673: the root's `wikipedia_api.plain_text` reads it (through
    `fact_search.plain_text`), the word templates - `{{US$|N}}`, `{{nbsp}}`,
    `{{'s}}` - included."""
    return fact_search.plain_text(wikitext)


def _undisambiguated(title):
    """`Harbourlights (TV series)` -> `Harbourlights`: the show's name as its season
    articles spell it."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", (title or "").strip())


def season_mismatch(page, work, season, transcluded):
    """Why a page asked for as a season article is not *this* work's season
    article, or None when it is. `Harbourlights season 1` is a redirect to the
    show's own article (the same text again); `A Different World season 1`
    is a redirect to the 1987 sitcom's episode list (another work: the topic
    is the 2026 series). A guessed title - not one the work's article
    transcludes - must also link back to the work's article."""
    if page is None:
        return None
    if page.get("key") == work.get("key"):
        return "a redirect to the work's own article"
    named = SEASON_TITLE_RE.match(page.get("title") or "")
    if not named or int(named.group("n")) != int(season):
        return f"resolved to {page.get('title')!r}, not a season {season} article"
    if not transcluded:
        target = (work.get("title") or "").replace("_", " ")
        links = {m.group(1).strip().replace("_", " ")
                 for m in re.finditer(r"\[\[([^\]|#]+)", page.get("wikitext") or "")}
        if target not in links:
            return f"does not link to {target!r} - another work's season"
    return None


def transcluded_season(wikitext, season):
    """The title of the season article the work article transcludes for
    season `season` (`{{:Rennick season 4}}`), or None."""
    for m in re.finditer(r"\{\{\s*:\s*([^{}|]+?)\s*\}\}", wikitext or ""):
        title = m.group(1).strip()
        found = SEASON_TITLE_RE.match(title)
        if found and int(found.group("n")) == int(season):
            return title
    return None


# --------------------------------------------------------------------------
# the topic's event
# --------------------------------------------------------------------------

_SXE_RE = re.compile(r"\bs(\d{1,2})\s?e(\d{1,3})\b", re.I)
_SEASON_EP_RE = re.compile(r"\b(?:season|series)\s+(\d+),?\s+(?:episode|ep\.?)\s+(\d+)\b", re.I)
# `4x09`: season 4, episode 9 - the episode zero-padded, as the notation prints it
_NXN_RE = re.compile(r"(?<![\w.])(\d{1,2})[x\u00d7](\d{2})(?![\w.])", re.I)
_EP_RE = re.compile(r"\b(?:episode|ep\.?)\s+(\d+)\b", re.I)
_SEASON_RE = re.compile(r"\b(?:season|series)\s+(\d+)\b", re.I)
_FINALE_RE = re.compile(r"(?<!mid-season )(?<!midseason )(?<!mid-season-)(?<!midseason-)"
                        r"(?<!mid-)\bfinale\b", re.I)
_PREMIERE_RE = re.compile(r"\bpremiere\b(?!\s+date)", re.I)
_WORD_SEASON = {"first": 1, "one": 1, "second": 2, "two": 2, "third": 3, "three": 3,
                "fourth": 4, "four": 4, "fifth": 5, "five": 5}
_SEASON_WORD_RE = re.compile(r"\b(?:season|series)\s+(" + "|".join(_WORD_SEASON) + r")\b"
                             r"|\b(" + "|".join(_WORD_SEASON) + r")\s+(?:season|series)\b", re.I)


def is_series(title_ref):
    ref = title_ref or {}
    return bool(TV_TYPE_RE.search(str(ref.get("type") or ""))) or ref.get("season") is not None


def _season_in(text):
    m = _SEASON_RE.search(text)
    if m:
        return int(m.group(1))
    m = _SEASON_WORD_RE.search(text)
    if m:
        return _WORD_SEASON[(m.group(1) or m.group(2)).lower()]
    return None


def episode_number(n, known_season):
    """`Episode 409` as the trade press writes it: `(season, episode)` when the
    number is a season-and-episode code, else None (an overall number).

    A code is read only against a season the topic already knows (its
    `title_ref.season` or the season the lead names): `SEE` - three digits,
    season 1-9, episode 01-99 - for a show of under ten known seasons;
    `SSEE` - four digits - for a show of ten or more. The code's season must
    be one the show has (1..known season). `Episode 3`, `Episode 12` are never
    codes; with no known season `Episode 409` is the 409th episode overall
    (a long-running show)."""
    if known_season is None:
        return None
    known = int(known_season)
    digits = 3 if known < 10 else 4
    if len(str(n)) != digits:
        return None
    season, episode = divmod(int(n), 100)
    if 1 <= season <= known and episode >= 1:
        return season, episode
    return None


def _phrase(text, m):
    """The words around a match, whole words, for the record."""
    start = text.rfind(" ", 0, max(0, m.start() - 25)) + 1
    end = text.find(" ", min(len(text), m.end() + 15))
    return text[start:end if end > 0 else len(text)].strip()


def event_of(title_ref, leads):
    """The episode the topic's own news is about, as the leads print it:
    `{season, episode | None, which: "number"|"finale"|"premiere", phrase}`,
    or None for a topic whose event is not an episode (a film, a renewal, a
    casting, a person). Read off headline and summary only - nothing is
    inferred from a date or a schedule."""
    ref = title_ref or {}
    if not is_series(ref):
        return None
    if fact_search.is_about_person(ref):
        return None
    default_season = ref.get("season")
    found = []
    for raw in (v for lead in leads or [] for v in (lead.get("title"), lead.get("summary")) if v):
        text = str(raw).replace("’", "'").replace("‘", "'")
        season = _season_in(text) or default_season
        for m in _SXE_RE.finditer(text):
            found.append({"season": int(m.group(1)), "episode": int(m.group(2)),
                          "which": "number", "phrase": m.group(0)})
        for m in _SEASON_EP_RE.finditer(text):
            found.append({"season": int(m.group(1)), "episode": int(m.group(2)),
                          "which": "number", "phrase": m.group(0)})
        for m in _NXN_RE.finditer(text):
            found.append({"season": int(m.group(1)), "episode": int(m.group(2)),
                          "which": "number", "phrase": m.group(0)})
        if not any(f["which"] == "number" for f in found):
            for m in _EP_RE.finditer(text):
                n = int(m.group(1))
                code = episode_number(n, season)
                if code:
                    # CF-0581: Coach Hale 1313Z "Episode 409" is S4E9 (43rd overall)
                    found.append({"season": code[0], "episode": code[1], "which": "number",
                                  "phrase": m.group(0), "code": n})
                else:
                    found.append({"season": season, "episode": n,
                                  "which": "number", "phrase": m.group(0)})
        m = _FINALE_RE.search(text)
        if m:
            found.append({"season": season, "episode": None, "which": "finale",
                          "phrase": _phrase(text, m)})
        m = _PREMIERE_RE.search(text)
        if m:
            found.append({"season": season, "episode": None, "which": "premiere",
                          "phrase": _phrase(text, m)})
    if not found:
        return None
    # A numbered episode is the most precise thing a lead can say; then the
    # finale (the newest episode of a season), then the premiere.
    order = {"number": 0, "finale": 1, "premiere": 2}
    found.sort(key=lambda f: order[f["which"]])
    return found[0]


def season_rows(rows, season, from_season_article):
    """The rows of one season: all of a season article's; of a work article,
    those under that season's heading, or all when it has no season headings."""
    if from_season_article or season is None:
        return list(rows)
    if any(r["season_heading"] is not None for r in rows):
        return [r for r in rows if r["season_heading"] == int(season)]
    return list(rows)


def resolve_event(event, rows):
    """The row of `rows` (one season) the event names, or None."""
    if not event or not rows:
        return None
    if event["which"] == "finale":
        return rows[-1]
    if event["which"] == "premiere":
        return rows[0]
    n = event["episode"]
    for r in rows:
        if r["number_in_season"] == n:
            return r
    for r in rows:
        if r["number_in_season"] is None and r["number"] == n:
            return r
    # a number read as a season code that names no row of the season may be
    # the overall number after all (`Episode 409` of a long-running show)
    # the overall number: a lead with no season (`Episode 409` of a show the
    # topic names no season of), or a code that names no row of its season
    overall = event.get("code") if event.get("code") is not None else (
        n if event.get("season") is None else None)
    if overall is not None:
        for r in rows:
            if r["number"] == overall:
                return r
    return None


# --------------------------------------------------------------------------
# pieces
# --------------------------------------------------------------------------

def article_piece(article, kind):
    return {"id": f"wikipedia:{article.get('key')}",
            "kind": kind, "source": "wikipedia",
            "title": article.get("title"), "url": article.get("url"),
            "revision_id": article.get("revision_id"),
            "revised_at": article.get("revised_at"),
            "text": plain_article(article.get("wikitext") or "")}


def episode_piece(article, row, season):
    number = row["number"] if row["number"] is not None else row["number_in_season"]
    anchor = f"#ep{number}" if number is not None else ""
    return {"id": f"wikipedia:{article.get('key')}#ep{number}",
            "kind": KIND_EPISODE, "source": "wikipedia",
            "title": row["title"], "url": (article.get("url") or "") + anchor,
            "revision_id": article.get("revision_id"),
            "revised_at": article.get("revised_at"),
            "season": season, "episode": number,
            "episode_in_season": row["number_in_season"],
            "air_date": row["air_date"], "article": article.get("title"),
            "text": row["summary"]}


def feed_of(source, entry):
    """The configured feed a lead was read from: `evidence.sources[].feed`
    (`evidence_sources.py` copies the entry's `feed_url` there), else the
    fetched entry's own `feed_url` (`fetch_rss_news.parse_rss` /
    `parse_rest(..., feed_url=)` - the channel's `sources.rss.feeds[].url`,
    a wp-json read included). None when neither says."""
    return (source or {}).get("feed") or (entry or {}).get("feed_url") or None


def rss_pieces(topic, index=None, text_feeds=None):
    """The topic's own news as it was fetched: one piece per lead, the
    summary as it is (no fetch of the article behind it - Q9).

    CF-0634 (the user's decision of 08.10, CF-0557 Q1 variant b: the feeds
    are for choosing topics): only a lead of a feed in `text_feeds` - the
    channel's `channel_data.support_feed_urls`, the feeds whose `use` is
    `read_text` - gives a piece. A lead of a `headline_only` feed, of a feed
    that is not the channel's, or of no known feed gives nothing, its title
    included. `text_feeds` empty or None is no feed at all (closed, not
    open): a caller that did not ask the channel hands no excerpt on."""
    allowed = set(text_feeds or ())
    if not allowed:
        return []
    evidence = topic.get("evidence") or {}
    out, seen = [], set()
    sources = list(evidence.get("sources") or [])
    for url in evidence.get("rss_links") or []:
        if url not in {s.get("url") for s in sources}:
            sources.append({"url": url})
    for source in sources:
        url = source.get("url")
        if not url or url in seen:
            continue
        seen.add(url)
        entry = (index or {}).get(url) or {}
        if feed_of(source, entry) not in allowed:
            continue
        summary = source.get("summary") or entry.get("summary") or ""
        title = source.get("title") or entry.get("title")
        if not (summary or title):
            continue
        out.append({"id": f"rss:{len(out) + 1}", "kind": KIND_RSS, "source": "rss",
                    "title": title, "url": url,
                    "publication": source.get("publication") or entry.get("feed"),
                    "published_at": source.get("published_at") or entry.get("published_at"),
                    "revision_id": None, "revised_at": None,
                    "text": summary})
    return out


# --------------------------------------------------------------------------
# TVmaze: the event episode's description (CF-0636)
# --------------------------------------------------------------------------

def _tv_counts(tv):
    wire = getattr(tv, "network", None)
    return tv.request_count, (wire.get("requests", 0) if isinstance(wire, dict) else 0)


def tvmaze_event(tv, tm, ref, event, now, row=None):
    """`(piece | None, record)` - TVmaze's description of the episode `event`
    names, as a support piece, when the show is the topic's series, the
    episode has aired by `now` and TVmaze has a description of it; with `row`
    (the Wikipedia row the event resolved to), only when it is the same
    episode. `record` is `support_check.tvmaze`: `{show_id, episode_id, why,
    aired, used, requests, network}` (`why` says why no piece; `error` a
    source that could not be read)."""
    record = {"show_id": None, "episode_id": None, "episode": None, "aired": None,
              "has_text": False, "used": False, "why": None, "requests": 0, "network": 0}
    sent0, wire0 = _tv_counts(tv)
    piece = None
    try:
        show, why = tm.resolve_show(tv, ref.get("name"), network=ref.get("network"))
        if show is None:
            record["why"] = why
        else:
            record["show_id"], record["show"] = show.get("id"), show.get("name")
            ep = tm.event_episode(tv, show, event)
            if ep is None:
                record["why"] = (f"TVmaze lists no episode of {show.get('name')!r} for "
                                 f"{event.get('phrase')!r} (season {event.get('season')})")
            else:
                record.update(episode_id=ep.get("id"), season=ep.get("season"),
                              episode=ep.get("number"), title=ep.get("name"),
                              airstamp=ep.get("airstamp") or ep.get("airdate"),
                              aired=bool(tm.aired(ep, now)), has_text=bool(ep.get("text")))
                same = (row is None or row.get("number_in_season") is None
                        or ep.get("season") is None or ep.get("number") is None
                        or (int(ep["season"]) == int(event.get("season") or ep["season"])
                            and int(ep["number"]) == int(row["number_in_season"])))
                if not record["aired"]:
                    when = record["airstamp"] or "on no date yet"
                    record["why"] = (f"{ep.get('name')!r} airs {when} - a description written "
                                     f"before the broadcast is not the episode's")
                elif not record["has_text"]:
                    record["why"] = f"TVmaze has no description of {ep.get('name')!r} yet"
                elif not same:
                    record["why"] = (f"TVmaze's episode is S{ep.get('season')}E{ep.get('number')}, "
                                     f"Wikipedia's list resolved the event to episode "
                                     f"{row.get('number_in_season')} of the season - not used")
                else:
                    piece = tm.episode_piece(ep, show)
                    record["used"] = True
                    record["piece"] = piece["id"]
    except tm.TvmazeError as exc:
        record["why"] = record["error"] = f"TVmaze could not be read: {exc}"
    except source_gate.SourceClosed as exc:
        record["why"] = f"TVmaze is not a readable outlet of the channel: {exc}"
    sent1, wire1 = _tv_counts(tv)
    record["requests"], record["network"] = sent1 - sent0, wire1 - wire0
    return piece, record


# --------------------------------------------------------------------------
# Wikidata: the work's statements (CF-0637)
# --------------------------------------------------------------------------

def wikidata_pieces(wdc, wd, article_title, properties, ref=None):
    """`(pieces, record)` - the statements of the channel's `properties` of
    the item whose English sitelink is `article_title` (the work's), as
    `wikidata_statement` pieces; `record` is `support_check.wikidata`:
    `{article, item, reason, error, asked, requests, network, pieces}` (a
    `WikidataError` or a closed gate is `error`, never raised; `reused` when
    the fact search of the same pass found it already)."""
    return fact_search.wikidata_lookup(wdc, wd, article_title, properties,
                                       year=(ref or {}).get("year"))


# --------------------------------------------------------------------------
# one topic
# --------------------------------------------------------------------------

def _today(now):
    if now is None:
        return dt.datetime.now(dt.timezone.utc).date()
    if isinstance(now, str):
        return dt.datetime.fromisoformat(now.replace("Z", "+00:00")).date()
    return now.date() if isinstance(now, dt.datetime) else now


_DISAMBIGUATION_TEMPLATE = re.compile(
    r"\{\{\s*(?:(?:human|place|given)\s+name\s+)?"
    r"(?:disambiguation|disambig|dab|hndis|geodis)\s*[|}]", re.IGNORECASE)


def is_disambiguation_page(wp, page):
    """CF-0824: is the page `client.page` returned a disambiguation page? The
    root's word first (`wikipedia_api.is_disambiguation`, CF-0828); a root
    older than that is asked nothing and the page's own marks are read - the
    `disambiguation` flag, `page_type`, the template in its wikitext."""
    if not page:
        return False
    judge = getattr(wp, "is_disambiguation", None)
    if callable(judge):
        return bool(judge(page))
    return bool(page.get("disambiguation") or page.get("page_type") == "disambiguation"
                or _DISAMBIGUATION_TEMPLATE.search(page.get("wikitext") or ""))


def support_topic(topic, probe_record, client, wp, index=None, leads=None, now=None,
                  text_feeds=None, tv=None, tm=None, wdc=None, wd=None, wd_properties=None,
                  vendor_reader=None):
    """`(pieces, check)` for one topic - see the module docstring.

    `client` is a `wikipedia_api.WikipediaClient` (tests hand in one on a
    recorded transport), `wp` the client module (for its `WikipediaError`).
    `leads` are the topic's news (`fact_probe_topics.leads_of_topic`); `now`
    the moment an air date is compared with (the batch's time).
    `text_feeds` are the feeds whose excerpt may be a piece (`rss_pieces`,
    CF-0634; the channel's `channel_data.support_feed_urls`) - none when not
    given. The leads still find the topic's episode (`event_of`): choosing
    which episode the news is about is selection, not support text.
    `tv` is a `tvmaze_api.TvmazeClient` (its gate the channel's list, CF-0636)
    and `tm` the client module; without them TVmaze is not asked (a channel
    whose list does not name the outlet, a test that is not about it).
    `wdc` is a `wikidata_api.WikidataClient` (its gate the channel's list,
    CF-0637), `wd` the module and `wd_properties` the channel's `{P: kind}`;
    without them Wikidata is not asked. Its pieces never change the state.
    `vendor_reader(topic, leads) -> (pieces, record)` (CF-0771, `vendor_pieces`
    bound to the pass's page client and the channel's list): asked only for a
    topic with no Wikipedia article of its own - its company's post is then
    the text (`ok`), recorded under `support_check.vendor_page`. None asks
    nothing: the state is Wikipedia's, as before."""
    ref = topic.get("title_ref") or {}
    record = probe_record or {}
    outcome = record.get("outcome")
    article_title = record.get("article")
    pieces = rss_pieces(topic, index, text_feeds)
    asked = []
    check = {"state": None, "event": None, "detail": None, "asked": asked,
             "requests": 0, "pieces": 0}
    start = client.request_count
    wd_pieces = []

    def finish(state, detail=None, wiki=()):
        check["state"] = state
        check["detail"] = detail
        check["requests"] = client.request_count - start
        out = list(wiki) + wd_pieces + pieces
        check["pieces"] = len(out)
        return out, check

    if outcome in UNREACHABLE_OUTCOMES:
        return finish(STATE_UNREACHABLE, f"the article search could not be asked "
                                         f"({record.get('detail') or outcome})")

    def no_article(detail):
        if vendor_reader is not None:
            # CF-0771: a product launched today has no article for weeks; its
            # company's own post (tier 1, `allowed`) is the text it is told from
            found, record = vendor_reader(topic, leads)
            check["vendor_page"] = record
            if found:
                return finish(STATE_OK, f"{detail}; told from the company's own post "
                                        f"({', '.join(p['url'] for p in found)})", found)
            detail += (f"; the company's own post: {record.get('outcome')} "
                       f"({record.get('where')})")
        return finish(STATE_NO_TEXT, detail)

    if outcome not in ARTICLE_OUTCOMES or not article_title:
        return no_article(f"no Wikipedia article of the topic's own (fact probe: "
                          f"{outcome or 'not asked'}, article {article_title or '-'})")
    try:
        work = client.page(article_title)
        asked.append({"title": article_title, "found": work is not None})
        if work is not None and is_disambiguation_page(wp, work):
            # CF-0824: a list of meanings is no article of the topic's own -
            # its lines are other subjects, never the topic's support text
            asked[-1]["disambiguation"] = True
            return no_article(f"the article {article_title!r} is a disambiguation page, "
                              f"not an article of the topic's own")
        if work is None or not plain_article(work.get("wikitext") or ""):
            return finish(STATE_NO_TEXT, f"the article {article_title!r} is missing or empty")
        wiki = []
        season = ref.get("season")
        event = event_of(ref, leads)
        if event and event.get("season") is not None:
            season = event["season"]
        check["event"] = event
        season_article = None
        main_article = work
        named = SEASON_TITLE_RE.match(work.get("title") or "")
        if named and is_series(ref) and (season is None or int(named.group("n")) == int(season)):
            # the probe resolved the season itself: it is the season article,
            # and the show's own article is asked for beside it
            season_article, season = work, int(named.group("n"))
            parent = client.page(named.group("base"))
            asked.append({"title": named.group("base"), "found": parent is not None})
            main_article = parent
        elif is_series(ref) and season is not None:
            transcluded = transcluded_season(work.get("wikitext"), season)
            title = (transcluded
                     or f"{_undisambiguated(work.get('title') or article_title)} season {season}")
            if client.request_count - start < MAX_REQUESTS_PER_TOPIC:
                season_article = client.page(title)
                asked.append({"title": title, "found": season_article is not None,
                              "transcluded": bool(transcluded)})
                why = season_mismatch(season_article, work, season, bool(transcluded))
                if season_article is not None and why:
                    asked[-1]["rejected"] = why
                    season_article = None
        if main_article is not None:
            wiki.append(article_piece(main_article, KIND_WORK))
        if season_article is not None:
            wiki.append(article_piece(season_article, KIND_SEASON))
        # the episodes: the season article's rows, else the work article's
        holder, rows = None, []
        if season_article is not None:
            rows = episode_rows(season_article.get("wikitext"))
            holder = season_article
        if not rows and main_article is not None:
            rows = season_rows(episode_rows(main_article.get("wikitext")), season, False)
            holder = main_article
        for row in rows:
            if row["summary"]:
                wiki.append(episode_piece(holder, row, season))
    except wp.WikipediaError as exc:
        return finish(STATE_UNREACHABLE, f"Wikipedia could not be read: {exc}")

    if wdc is not None and wd is not None and wd_properties:
        # CF-0637: the work's statements - beside Wikipedia's text, never
        # for it: the state below is decided on Wikipedia's (and TVmaze's)
        # pieces alone
        wd_title = ((main_article or {}).get("title")
                    or (named.group("base") if named else None)
                    or work.get("title") or article_title)
        found, check["wikidata"] = wikidata_pieces(wdc, wd, wd_title, wd_properties, ref)
        wd_pieces.extend(found)

    if not any(p.get("text") for p in wiki):
        return finish(STATE_NO_TEXT, "Wikipedia answered with no text for the topic", wiki)
    if event:
        row = resolve_event(event, rows)
        tv_piece, tv_record = None, None
        if tv is not None and tm is not None:
            tv_piece, tv_record = tvmaze_event(tv, tm, ref, event, now, row)
            check["tvmaze"] = tv_record
            if tv_piece is not None:
                wiki.append(tv_piece)
        if row is None and tv_piece is not None:
            event["resolved"] = {"episode": None, "episode_in_season": tv_piece["episode"],
                                 "title": tv_piece["title"], "air_date": tv_piece["air_date"],
                                 "has_summary": False, "tvmaze": tv_piece["id"]}
            return finish(STATE_OK, f"no Wikipedia episode list names the episode "
                                    f"({event['phrase']!r}) yet; it is told from TVmaze's "
                                    f"description ({tv_piece['id']})", wiki)
        if (row is None and tv_record and tv_record.get("episode_id") is not None
                and tv_record.get("aired") is False):
            event["resolved"] = {"episode": None, "episode_in_season": tv_record.get("episode"),
                                 "title": tv_record.get("title"), "air_date": None,
                                 "has_summary": False, "aired": False,
                                 "tvmaze": f"{tm.SOURCE}:episode:{tv_record['episode_id']}"}
            return finish(STATE_OK, f"the episode the news names ({tv_record.get('title')}) "
                                    f"airs {tv_record.get('airstamp')} by TVmaze - an "
                                    f"announcement, the work's text stands for it", wiki)
        if row is None:
            return finish(STATE_NO_TEXT,
                          f"the news is about an episode ({event['phrase']!r}, season "
                          f"{event.get('season')}) and no Wikipedia episode list of that season "
                          f"names it - the episode has no text to tell it from"
                          f"{' (TVmaze: ' + tv_record['why'] + ')' if (tv_record or {}).get('why') else ''}",
                          wiki)
        event["resolved"] = {"episode": row["number"], "episode_in_season": row["number_in_season"],
                             "title": row["title"], "air_date": row["air_date"],
                             "has_summary": bool(row["summary"])}
        aired = row["air_date"] is None or row["air_date"] <= _today(now).isoformat()
        if not aired:
            event["resolved"]["aired"] = False
            check["event"] = event
            return finish(STATE_OK, f"the episode the news names ({row['title']}) airs on "
                                    f"{row['air_date']} - an announcement, the work's text "
                                    f"stands for it", wiki)
        if not row["summary"] and tv_piece is not None:
            event["resolved"]["tvmaze"] = tv_piece["id"]
            return finish(STATE_OK, f"the episode the news is about ({row['title'] or row['number']}"
                                    f", season {season}) has no ShortSummary on Wikipedia yet; "
                                    f"it is told from TVmaze's description ({tv_piece['id']})",
                          wiki)
        if not row["summary"]:
            return finish(STATE_NO_TEXT,
                          f"the episode the news is about ({row['title'] or row['number']}, "
                          f"season {season}, aired {row['air_date'] or '?'}) has no ShortSummary "
                          f"on Wikipedia yet - a description is written ~2-3 h after the "
                          f"broadcast; without it (and without TVmaze's description - "
                          f"{(tv_record or {}).get('why') or 'TVmaze not asked'}) the episode's "
                          f"story has nothing to stand on",
                          wiki)
    return finish(STATE_OK, None, wiki)


def has_wikipedia_text(pieces):
    return any(p.get("source") == "wikipedia" and (p.get("text") or "").strip()
               for p in pieces or [])


def has_vendor_text(pieces):
    """CF-0771: a company's own post among the pieces."""
    return any(p.get("kind") == KIND_VENDOR and (p.get("text") or "").strip()
               for p in pieces or [])


def has_story_text(pieces):
    """Text of the topic's own that `ok` may stand on: Wikipedia's, or - a
    topic with no article of its own - the company's own post (CF-0771).
    The news summaries alone never are."""
    return has_wikipedia_text(pieces) or has_vendor_text(pieces)


# --------------------------------------------------------------------------
# the company's own post (CF-0771)
# --------------------------------------------------------------------------

def _utc_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def vendor_piece(page, outlet, n, now=None):
    """One `vendor_page` piece of a page `vendor_page.PageClient.page`
    answered: the post's main text (`<article>` / `<main>`, else the body,
    navigation and boilerplate dropped - `vendor_page.html_text`), its
    outlet, URL and title. None for a page with no text."""
    text = "\n\n".join(b.strip() for b in page.get("blocks") or [] if str(b).strip())
    if not text:
        return None
    cut = len(text) > VENDOR_TEXT_MAX
    if cut:
        text = text[:VENDOR_TEXT_MAX].rsplit("\n", 1)[0] or text[:VENDOR_TEXT_MAX]
    oid = (outlet or {}).get("id") or "vendor"
    url = page.get("final_url") or page.get("url")
    return {"id": f"{SOURCE_VENDOR}:{oid}:{n}", "kind": KIND_VENDOR, "source": SOURCE_VENDOR,
            "outlet": oid, "publication": page.get("site_name") or oid,
            "title": page.get("title") or None, "url": url,
            "revision_id": None, "revised_at": None,
            "fetched_at": page.get("fetched_at") or now or _utc_now(),
            "truncated": bool(page.get("truncated")) or cut,
            "text": text}


def vendor_pieces(topic, leads, pool_entries, sources, client, now=None,
                  pages=VENDOR_PAGES_PER_TOPIC, newsroom=None):
    """`(pieces, record)`: the company's own posts as support text for a
    topic with no Wikipedia article of its own (CF-0771).

    The posts are the ones CF-0757 reads for the fact - `vendor_page.
    official_links` (the topic's own news that is the post, a link in it, a
    company feed's entry naming the work), each through `client.page`, whose
    door is `source_gate.read_vendor_page` (tier 1, `ai_policy` `allowed`),
    cached in the batch - so a post the fact search read is not asked again.
    A post is a piece only when it names the topic's work (title or text):
    a company's other post says nothing about this story. Never raises.

    `newsroom` (CF-0810) - the releases the fact search found on the
    vendor's newsroom index (`vendor_page.lookup`'s `pages[]` with `how:
    newsroom`): asked after the official links, under the same caps and the
    same door, so a topic whose fact came off a release is told from it; the
    record then carries `newsroom` (those URLs). None changes nothing."""
    import fact_rule
    import vendor_page
    ref = topic.get("title_ref") or {}
    work = ref.get("name") or ref.get("person")
    sent0, wire0 = vendor_page.counts(client)
    links = vendor_page.official_links(work, leads, pool_entries, sources, fact_rule,
                                       fact_search.names_work)
    known = {u for u, _ in links}
    found_there = [u for u in dict.fromkeys(newsroom or [])
                   if isinstance(u, str) and u and u not in known]
    links = links + [(u, vendor_page.VIA_NEWSROOM) for u in found_there]
    out, rows, closed = [], [], []
    for url, how in links:
        if len(out) >= pages:
            break
        why = source_gate.vendor_page_refusal(url, sources)
        if why:
            closed.append({"url": url, "how": how, "why": why})
            continue
        try:
            page = client.page(url, sources)
        except source_gate.SourceClosed as exc:
            closed.append({"url": url, "how": how, "why": str(exc)})
            continue
        except vendor_page.PageError as exc:
            rows.append({"url": url, "how": how, "outcome": "cap", "detail": str(exc)})
            break
        if page.get("error"):
            rows.append({"url": url, "how": how, "outcome": "unreachable",
                         "detail": page["error"]})
            continue
        piece = vendor_piece(page, source_gate.outlet_of(url, sources), len(out) + 1, now)
        if piece is None:
            rows.append({"url": url, "how": how, "outcome": "no_text"})
            continue
        # CF-0914: the company's own post may name the work without its company
        names = vendor_page.work_names(
            work, vendor_page.row_names(source_gate.outlet_of(url, sources)),
            vendor_page.list_names(sources))
        if not any(fact_search.names_work(name, {"title": piece["title"], "summary": piece["text"]})
                   for name in names):
            rows.append({"url": url, "how": how, "outcome": "not_about_the_work"})
            continue
        out.append(piece)
        rows.append({"url": url, "how": how, "outcome": "ok", "chars": len(piece["text"]),
                     "truncated": piece["truncated"]})
    if out:
        outcome = "ok"
    elif rows:
        outcome = rows[-1]["outcome"]
    elif closed:
        outcome = "closed"
    else:
        outcome = "no_link"
    where = (", ".join(f"{(r['url'].split('/')[2] if '//' in r['url'] else r['url'])}: "
                       f"{r['outcome']}" for r in rows)
             or ("; ".join(c["why"] for c in closed[:2]) if closed
                 else "no tier-1 link in the topic's news or the pool"))
    sent1, wire1 = vendor_page.counts(client)
    record = {"asked": True, "outcome": outcome, "where": where, "links": len(links),
              "pages": rows, "closed": closed, "pieces": len(out),
              "requests": sent1 - sent0, "network": wire1 - wire0}
    if found_there:
        record["newsroom"] = found_there
    return out, record


def refusal_reason(topic, check):
    ref = topic.get("title_ref") or {}
    return (f"no support text: {check.get('detail') or 'none found'}. The story is told "
            f"only from Wikipedia (the work, its season, the episode descriptions), TVmaze's "
            f"description of an aired episode (CF-0636), the company's own post when there "
            f"is no article (CF-0771) and the news summaries of a "
            f"read_text feed (CF-0546 Q1/Q7/Q9, CF-0634); a topic with nothing about its "
            f"own event is dropped here, before the indexer pays for it - "
            f"{ref.get('name')!r}")


def client_for(batch_dir, wp, transport=None):
    """The shared client, cached in `<batch>/work/wikipedia-cache/` with this
    stage's short cache life and its own name in the User-Agent.

    CF-0559: the one client of the hunter's pass - the fact search reads the
    topic's article through it first (`fact_search.search_topic`) and the
    support text then finds that answer in the cache. `client.network` counts
    the requests that went past the cache to Wikipedia (`request_count`
    counts every request, a cache hit included) - what the stage report
    gives per topic (`fact_search.requests_of`)."""
    real = transport or wp.urllib_transport
    network = {"requests": 0}

    def counted(url, headers, timeout=wp.DEFAULT_TIMEOUT):
        network["requests"] += 1
        return real(url, headers, timeout)

    cache = Path(batch_dir) / "work" / "wikipedia-cache" if batch_dir else None
    sent = counted
    if cache:
        sent = wp.cached_transport(cache, counted, max_age_seconds=CACHE_MAX_AGE_SECONDS)
    client = wp.WikipediaClient(transport=sent, tool_name=TOOL_NAME)
    client.network = network
    return client


def tvmaze_client_for(batch_dir, tm, sources, transport=None,
                      max_age_seconds=CACHE_MAX_AGE_SECONDS):
    """CF-0636: the shared TVmaze client of the hunter's pass, cached in
    `<batch>/work/tvmaze-cache/`, the hunter's name in its User-Agent, and
    `source_gate.check` with the channel's fact-sources list `sources` as its
    gate - called before every request, a cached answer included, so the list
    (not this file) says whether TVmaze may be read. `client.network` counts
    the requests that went past the cache, as `client_for`'s does."""
    real = transport or tm.urllib_transport
    network = {"requests": 0}

    def counted(url, headers, timeout=tm.DEFAULT_TIMEOUT):
        network["requests"] += 1
        return real(url, headers, timeout)

    cache = Path(batch_dir) / "work" / "tvmaze-cache" if batch_dir else None
    client = tm.cached_client(cache, transport=counted, max_age_seconds=max_age_seconds,
                              tool_name=TOOL_NAME,
                              gate=lambda url: source_gate.check(url, sources))
    client.network = network
    return client


def wikidata_client_for(batch_dir, wd, sources, transport=None,
                        max_age_seconds=WIKIDATA_CACHE_MAX_AGE_SECONDS):
    """CF-0637: the shared Wikidata client of the hunter's pass - the fact
    search and the support text read through it - cached in
    `<batch>/work/wikidata-cache/`, the hunter's name in its User-Agent, and
    `source_gate.check` with the channel's list `sources` as its gate (asked
    before every request, a cached answer included; for the search on
    api.wikimedia.org the Wikidata site first). `client.network` counts the
    requests that went past the cache."""
    real = transport or wd.urllib_transport
    network = {"requests": 0}

    def counted(url, headers, timeout=wd.DEFAULT_TIMEOUT):
        network["requests"] += 1
        return real(url, headers, timeout)

    cache = Path(batch_dir) / wd.CACHE_REL if batch_dir else None
    client = wd.cached_client(cache, transport=counted, max_age_seconds=max_age_seconds,
                              tool_name=TOOL_NAME,
                              gate=lambda url: source_gate.check(url, sources))
    client.network = network
    return client


def wikidata_refusal(sources, wd):
    """Why the channel's list `sources` does not let Wikidata be read (None
    when it does) - asked once a pass, as `tvmaze_refusal`."""
    return source_gate.refusal(wd.SITE_BASE + "/wiki/", sources)


def wikidata_outlet(sources, wd):
    """The channel's `wikidata` outlet entry (its `properties`), or None."""
    return source_gate.outlet_of(wd.SITE_BASE + "/wiki/", sources)


def tvmaze_refusal(sources, tm):
    """Why the channel's list `sources` does not let TVmaze be read (None when
    it does) - asked once a pass, so a channel without the outlet asks TVmaze
    nothing rather than being refused at every topic."""
    return source_gate.refusal(tm.API_BASE + "/", sources)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("batch", help="batch directory or its 01-trend-hunter.json")
    ap.add_argument("--topic", required=True, help="topic_id to read the support text for")
    args = ap.parse_args(argv)
    path = Path(args.batch).expanduser()
    path = path / "01-trend-hunter.json" if path.is_dir() else path
    batch = json.loads(path.read_text())
    topic = next((t for t in batch.get("topics") or [] if t.get("topic_id") == args.topic), None)
    if topic is None:
        print(f"no topic {args.topic} in {path}", file=sys.stderr)
        return 2
    from _wikipedia import wikipedia_api as wp
    import fact_probe_topics as fp
    client = client_for(path.parent, wp)
    # the batch's channel's supporter: its read_text feeds and, when its list
    # names the outlets, TVmaze and Wikidata (CF-0634, CF-0636, CF-0637)
    supporter = fp.make_supporter(path.parent, batch, wp=wp, client=client)
    pieces, check = supporter(topic, topic.get("fact_probe"), fp.leads_of_topic(topic), None)
    print(json.dumps({"check": check, "pieces": [dict(p, text=(p.get("text") or "")[:200])
                                                 for p in pieces]},
                     ensure_ascii=False, indent=2))
    return 0 if check["state"] != STATE_NO_TEXT else 1


if __name__ == "__main__":
    sys.exit(main())
