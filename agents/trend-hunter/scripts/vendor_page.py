#!/usr/bin/env python3
"""CF-0757: the fact from the company's own page.

Batch ExampleTech 2026-10-15T1854Z lost Apple HomeView and Gemini 4 Argon as
`no_fact`: a product launched today has no Wikipedia article, and the fact
search (`fact_search.py`) read only Wikipedia and the short excerpts of the
`read_text` feeds. The channel's own rule (grill Q17, `channels/example-tech/
fact-sources.json` tier 1: apple.com, blog.google, openai.com...) names the
company's page as the fact's first source - and nothing opened it. The user,
15.10: «берём» (hotfix 2.4.1).

**When.** In `fact_probe_topics.select_batch`, after Wikipedia, Wikidata and
the batch's news (`rss_pool`) were searched and checked, and **only when no
candidate passed** the fact rule - before the topic leaves as `no_fact`. A
topic that already has a fact asks nothing here.

**Which page** (`official_links`), in this order, at most `PAGES_PER_TOPIC`
read a topic:

  1. the topic's own news that *is* the company's post - a lead
     (`evidence.sources[].url`, `evidence.rss_links`) on a tier-1 host;
  2. a link inside the topic's own news - an `href` / bare URL in a lead's
     summary (the RSS output's, `evidence.sources[].summary`) on a tier-1
     host: the trade's "announced in a blog post" link;
  3. an entry of the batch's pool (`fetch_rss_news.py` output, every feed -
     the companies' own feeds: OpenAI News, Google DeepMind, Apple Newsroom)
     whose link is on a tier-1 host and that names the topic's work
     (`fact_search.names_work`: the title, or a summary long enough).

A site's front page (no path) is no post and is never read.

**The newsroom index** (CF-0810, `newsroom_lookup`). Batch ExampleTech
2026-10-16T0839Z lost «Porsche Mission S» as `no_fact`: its news linked no
tier-1 page, while the release sat on newsroom.porsche.com's own index. So
when the three places above give **no link at all**, a tier-1 row of the list
may carry `newsroom` - a list of the vendor's press-release index URLs on
the row's own host, each a URL string or `{"url": <index>, "names":
[...]}` - and an optional row-level `names` (the company's names as the news
writes them). An index is read when the topic names its company: one of the
row's `names`, the item's `names` or the index host's stem (`host_stem`:
`newsroom.porsche.com` -> `porsche`, `blog.google` -> `google` - a service
label of `SERVICE_LABELS` is never the stem; at least `MIN_STEM_CHARS`, and
never an everyday word of `COMMON_WORD_STEMS` such as `figure` or `honor`,
whose company only its `names` name) is a whole word (`fact_search.names_work`) of the work's name, the topic's title or a
lead's headline or summary. Only through the same door as a post: an index
on a row whose verdict is not `allowed`, or off the row's own host, is never
asked (`closed[]`, `how: newsroom_index`). At most `INDEXES_PER_TOPIC` 2
indexes a topic; each is a read of the client (cache, User-Agent, ceiling of
the pass). Off the index, the links on its own host (front pages and the
index aside) whose text or slug names the work (`names_work(work, ...)`,
the work's whole name) are read as posts (`pages[].how: newsroom`), at most
`PAGES_PER_TOPIC` as above, their sentences judged by the rule as usual.
The row says `via: newsroom` and `newsroom[]` (`index`, `outlet`, `named`,
`outcome` `matched` / `newsroom_no_match` / `unreachable` / `cap`, `links`,
`matched`, `detail`); an index read with no such link makes the outcome
`newsroom_no_match`. A list with no `newsroom` field reads as before.

**The vendor's feed** (CF-0914). Batch ExampleTech 2026-11-02T0838Z selected
0 of 42 topics, 25 of them `vendor_page=no_link`: fresh company news ("OpenAI
AI compute campuses", "GM Smart Driver") whose trade coverage links no tier-1
page. What kept the newsroom path shut, and is open now:

  - an index is read with `PageClient.page(..., index=True)`, so a
    `newsroom` item may be the vendor's **RSS / Atom feed**
    (`openai.com/news/rss.xml`): an XML answer is parsed by `feed_entries`
    (a feed that declares entities is never parsed), and `feed_releases`
    takes its entries whose link is on the row's own outlet and whose title,
    slug or summary names the work (`newsroom[].kind`: `feed` / `index`);
  - a release, a pool entry of the company's own feed and the support
    text's post are matched by the work's name **with or without the
    company's own name** (`work_names`: "GM Smart Driver" -> "Smart Driver"
    on GM's outlet only; the rest must be a name - `MIN_REST_CHARS`, never
    one everyday word);
  - a post that refuses the client (openai.com answers 403 to it, its feed
    does not) is told from its **feed entry's own text** (`pages[].read:
    feed_entry`), judged by the same rule;
  - a `no_link` reason **names the company** the topic names and why its
    page was not read (`named_outlets`: `...; named openai.com: allowed, no
    newsroom listed, apple.com: forbidden`) - the list to extend is then
    in the record.

Nothing reads a site beyond the listed index or feed and the posts it names;
a `newsroom` URL is the root's data (`channels/<id>/fact-sources.json`), on
the row's own host, read only when the row is `allowed`.

**Which host.** Only through `source_gate.read_vendor_page`: a **tier-1**
outlet of the channel's list whose `ai_policy.verdict` is `allowed` (the
source rule of 08.10 - robots.txt does not close it to Anthropic's agents or
to `*`; terms that forbid AI write `forbidden`). `unknown` is not permission
and `forbidden` is never asked; an outlet the factory already reads with a
client of its own (`use: read_text` - Wikipedia, TVmaze, Wikidata) is not
read again here. The list is data: when the root re-checks an outlet to
`allowed`, its pages are read with no change in this file. Every redirect hop
is put through the same door (`_GatedRedirect`): a post that redirects off
the outlet is not followed.

**The client** (`PageClient`): stdlib `urllib`, the hunter's User-Agent
(`USER_AGENT`, the factory's name and contact - never a browser's),
`TIMEOUT` seconds, at most `MAX_BYTES` read (the rest is cut, the page is
marked `truncated`), only an HTML answer (`text/html`, XHTML), `DELAY`
seconds between two requests, at most `MAX_PAGES_PER_BATCH` network reads a
pass. A page is read once a batch: the answer is kept in memory and, with a
batch, in `<batch>/work/vendor-page-cache/` (the plain text, not the HTML),
so a refill round (`refill_topics.py`, CF-0756) asks nothing again.
`request_count` counts every page asked (a cache hit included), `network`
`{"requests": n}` the ones that went out - `selection.vendor_page` in the
batch file.

**A network failure is asked again** (CF-0790). Batch ExampleScience
2026-10-17T0817Z lost Comet 67P's NASA page as `unreachable` on one connect
timeout (`URLError: <urlopen error timed out>`); the same client read the
same page on 18.10 in half a second. So a failure of the network
(`NetworkError`: no answer, a timeout, a reset) and a server's "later"
(`RETRY_STATUS`: 429, 500, 502, 503, 504) are asked again up to `RETRIES`
times, `RETRY_DELAYS` seconds apart - every attempt a network read of its
own, under `MAX_PAGES_PER_BATCH` like the first. A refusal is not retried: a
403/404, a page that is not HTML, a redirect off the outlet. The page record
says how many attempts it took (`attempts`).

**The candidates** (`page_candidates`): the page's prose (`html_text`:
`<article>` / `<main>` when they hold the text, else the body; scripts,
styles, navigation, header, footer, forms and asides dropped), split into
sentences (`_sentences.split_sentences`, CF-0737 - never cut at an
abbreviation or an initial); a sentence of `MIN_CHARS`..`MAX_CHARS` with a
number or a month in it (a price, a date, a spec) is a candidate, cookie and
legal lines aside; its `kind` read off its words (`VENDOR_KINDS`: price,
release_date, spec, benchmark, model_card, paper - the channel's kinds; any
other is the rule's `other`); `url` the page, `source` the outlet's id,
`attribution` "<site> says". The sentences that name the topic's work go
first. Each one is then judged by `fact_rule.check_candidates` like any
other candidate - nothing here relaxes the rule: a sentence that retells the
news, has no specifics, or reads as cut short fails as before.

**What it writes.** One `fact_search.asked[]` row, `source: vendor_page`,
`outcome` `ok` (a candidate passed) / `no_candidates` (pages read, none
passed) / `no_link` (no tier-1 link at all) / `closed` (links, none on an
`allowed` outlet) / `unreachable` (pages could not be read) / `cap` (the
batch's ceiling) / `newsroom_no_match` (CF-0810: a newsroom index read, no
release on it names the work), `candidates`, `pages[]`, `closed[]`,
`via` and `newsroom[]` (when an index was asked), `requests`,
`network`, and `where` - the hosts it read or why it could not - which the
`no_fact` reason prints: `searched wikipedia=no_article(0), rss_pool=ok(0),
vendor_page=closed(0)[blog.google: unknown]`. A page that cannot be read is
written there and nowhere else: it never makes a topic
`source_unreachable`.

Stdlib only; `transport=` is the tests' seam (they never leave the machine).
"""
import hashlib
import html
import html.parser
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import _sentences  # noqa: E402
import source_gate  # noqa: E402

VENDOR_SOURCE = "vendor_page"          # `fact_search.asked[].source`
SELECTION_KEY = "vendor_page"          # `selection.vendor_page`
CACHE_DIR = "vendor-page-cache"        # under `<batch>/work/`
USER_AGENT = ("shorts-content-factory-trend-hunter/1.0 "
              "(+https://example.com/shorts-content-factory)")
TIMEOUT = 15                           # seconds a request
RETRIES = 2                            # CF-0790: a network failure asked again
RETRY_DELAYS = (3.0, 10.0)             # seconds before the 1st, 2nd retry
RETRY_STATUS = (429, 500, 502, 503, 504)
MAX_BYTES = 2_000_000                  # bytes read off one page
DELAY = 1.0                            # seconds between two requests
PAGES_PER_TOPIC = 2                    # pages read for one topic
LINKS_PER_TOPIC = 8                    # links considered for one topic
MAX_PAGES_PER_BATCH = 40               # network reads in one pass
VENDOR_MAX = 8                         # candidates taken off one page
MIN_CHARS = 40
MAX_CHARS = 320
HTML_TYPES = ("text/html", "application/xhtml+xml")
# CF-0914: a newsroom index may be the vendor's RSS / Atom feed
FEED_TYPES = ("application/rss+xml", "application/atom+xml", "application/rdf+xml",
              "application/xml", "text/xml")
INDEX_ACCEPT = ("text/html,application/xhtml+xml,application/rss+xml,application/atom+xml,"
                "application/xml;q=0.9,text/xml;q=0.9")
FEED_ENTRIES_MAX = 200                 # entries kept off one feed (newest as written)
FEED_SUMMARY_MAX = 1000                # characters of an entry's summary kept
FEED_TEXT_MAX = 4000                   # characters of an entry's full text kept
MIN_REST_CHARS = 4                     # the work's name with its company cut off, at least
COMMON_WORDS = HERE.parent / "config" / "common_words.txt"
# the rest of a work's name that is never a name of its own, whatever the vocabulary says
GENERIC_REST_WORDS = frozenset({
    "stock", "shares", "earnings", "ipo", "ceo", "layoffs", "lawsuit", "news", "update",
    "deal", "app", "apps", "results", "funding", "breach", "hack", "outage"})
VIA_FEED_ENTRY = "feed_entry"          # `pages[].read` of a post told from its feed entry
# CF-0810: the vendor's newsroom index, read when the news carries no link
NEWSROOM_FIELD = "newsroom"            # a tier-1 row's press-release index URLs
NAMES_FIELD = "names"                  # a tier-1 row's company names (optional)
INDEXES_PER_TOPIC = 2                  # newsroom indexes read for one topic
INDEX_LINKS_MAX = 1000                 # links kept off one page
MIN_STEM_CHARS = 3                     # a host's stem shorter than this names nobody
# CF-0810 follow-up: a host's stem names the company only when it is the
# company's word. A service label (`blog.google`, `news.example.com`) is never
# the stem - the label to its right is, unless that is a generic TLD-like
# label too (`news.com` has no stem). Extend either list as hosts come.
SERVICE_LABELS = frozenset({
    "www", "blog", "blogs", "news", "newsroom", "press", "pressroom", "about",
    "investors", "investor", "ir", "media", "corporate", "global"})
GENERIC_TLD_LABELS = frozenset({
    "com", "org", "net", "co", "ac", "gov", "edu", "io", "ai", "tech", "dev", "app",
    "social", "blog", "news", "info", "biz", "site", "online", "cloud"})
# A stem that is an everyday English word ("Figure skating", "Aurora borealis")
# never opens the index by itself - the row's or the item's `names` must.
COMMON_WORD_STEMS = frozenset({
    "aurora", "figure", "honor", "stability", "nothing", "signal", "notion", "ring",
    "nest", "block", "square", "snap", "arm", "zoom"})
VIA_NEWSROOM = "newsroom"              # `asked.via`, `pages[].how` of a release found there
HOW_INDEX = "newsroom_index"           # `closed[].how` of an index the door refused

OUTCOME_OK = "ok"
OUTCOME_NO_CANDIDATES = "no_candidates"
OUTCOME_NO_LINK = "no_link"
OUTCOME_CLOSED = "closed"
OUTCOME_UNREACHABLE = "unreachable"
OUTCOME_CAP = "cap"
OUTCOME_NEWSROOM_NO_MATCH = "newsroom_no_match"    # CF-0810: an index read, no release named

_MONTHS = ("january", "february", "march", "april", "may", "june", "july", "august",
           "september", "october", "november", "december")
_MONTH_RE = re.compile(r"\b(?:" + "|".join(m.capitalize() for m in _MONTHS)
                       + r"|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sept?|Oct|Nov|Dec)\b")
# A page's own boilerplate - never a fact.
_BOILER_RE = re.compile(r"cookie|privacy|copyright|©|all rights reserved|terms of (?:use|service)|"
                        r"subscribe|sign up|newsletter|javascript|trademark", re.I)
# The kind of a sentence, first match wins (the channel's kinds; a kind the
# channel does not name becomes the rule's `other`).
VENDOR_KINDS = (
    ("price", re.compile(r"[$€£¥]\s?\d|\b\d[\d,.]*\s?(?:usd|dollars|euros)\b|\bpric(?:e|ed|ing)\b|"
                         r"\bcosts?\b|per month|/month|subscription", re.I)),
    ("benchmark", re.compile(r"benchmark|\bscor(?:e|es|ed)\b|SWE-bench|MMLU|GPQA|ARC-AGI|"
                             r"leaderboard|state[- ]of[- ]the[- ]art", re.I)),
    ("release_date", re.compile(r"\bavailable\b|\blaunch(?:es|ed|ing)?\b|\bships?\b|"
                                r"\brolling out\b|\brolls out\b|\bpre-?orders?\b|\bstarting\b|"
                                r"\bbegins?\b|\brelease[sd]?\b", re.I)),
    ("model_card", re.compile(r"context window|\bparameters?\b|\btokens?\b|training data|"
                              r"model card|knowledge cutoff", re.I)),
    ("spec", re.compile(r"\b\d[\d,.]*\s?(?:gb|tb|mb|ghz|mhz|mah|wh|kwh|nm|mm|cm|inch(?:es)?|"
                        r"-inch|hz|fps|mp|w|kg|g|hours?|miles|km|cores?|tops|teraflops|"
                        r"petaflops|x)\b|\bchip\b|\bbattery\b|\bdisplay\b|\bprocessor\b", re.I)),
    ("paper", re.compile(r"\bpaper\b|arxiv|peer-reviewed|\bpublished in\b", re.I)),
)


class PageError(RuntimeError):
    """The page could not be read - never "no fact"."""


class NetworkError(PageError):
    """Nothing came back from the network (no connection, a timeout, a
    reset) - the one `PageError` asked again (CF-0790)."""


# --------------------------------------------------------------------------
# the page as text
# --------------------------------------------------------------------------

_SKIP_TAGS = frozenset(("script", "style", "noscript", "svg", "nav", "header", "footer", "form",
                        "aside", "button", "template", "iframe", "select", "dialog"))
_BLOCK_TAGS = frozenset(("p", "div", "li", "ul", "ol", "br", "section", "article", "main",
                         "h1", "h2", "h3", "h4", "h5", "h6", "tr", "td", "th", "table",
                         "figcaption", "blockquote", "dd", "dt", "hr", "pre"))
_VOID_TAGS = frozenset(("br", "hr", "img", "meta", "link", "input", "source", "wbr", "area",
                        "base", "col", "embed", "param", "track"))


class _Reader(html.parser.HTMLParser):
    """Blocks of text of a page, the whole body's and the `<article>` /
    `<main>` part's apart, plus its title and site name."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.skip = 0
        self.inside = 0            # depth inside <article>/<main>
        self.body, self.main = [], []
        self.title, self.site_name, self._in_title = "", "", False

    def _break(self):
        for blocks in (self.body, self.main) if self.inside else (self.body,):
            if blocks and blocks[-1] != "":
                blocks.append("")

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if tag == "meta":
                a = dict(attrs)
                if (a.get("property") or a.get("name") or "").lower() == "og:site_name":
                    self.site_name = (a.get("content") or "").strip()
            elif tag in _BLOCK_TAGS:
                self._break()
            return
        if tag in _SKIP_TAGS:
            self.skip += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in ("article", "main"):
            self.inside += 1
        if tag in _BLOCK_TAGS:
            self._break()

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in _VOID_TAGS:
            return
        if tag in _SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
            return
        if tag == "title":
            self._in_title = False
        if tag in _BLOCK_TAGS:
            self._break()
        if tag in ("article", "main"):
            self.inside = max(0, self.inside - 1)

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self.skip:
            return
        for blocks in (self.body, self.main) if self.inside else (self.body,):
            if not blocks or blocks[-1] == "":
                blocks.append(data)
            else:
                blocks[-1] += data


def _blocks(parts):
    out = []
    for part in parts:
        text = re.sub(r"\s+", " ", html.unescape(part or "")).strip()
        if text:
            out.append(text)
    return out


class _Anchors(html.parser.HTMLParser):
    """Every `<a href>` of a page with its text - navigation, header and
    teasers included (a newsroom index lists its releases anywhere), scripts
    and styles aside. CF-0810."""

    def __init__(self, limit):
        super().__init__(convert_charrefs=True)
        self.limit, self.links = limit, []
        self._href, self._label, self._text, self._skip = None, "", [], 0

    def _close(self):
        if self._href is not None and len(self.links) < self.limit:
            text = re.sub(r"\s+", " ", "".join(self._text)).strip() or self._label
            self.links.append({"href": self._href, "text": text})
        self._href, self._label, self._text = None, "", []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style", "template"):
            self._skip += 1
            return
        if tag == "a":
            self._close()
            a = dict(attrs)
            href = (a.get("href") or "").strip()
            if href and not href.startswith(("#", "javascript:", "mailto:", "tel:")):
                self._href = href
                self._label = re.sub(r"\s+", " ", a.get("title") or a.get("aria-label")
                                     or "").strip()

    def handle_endtag(self, tag):
        if tag in ("script", "style", "template"):
            self._skip = max(0, self._skip - 1)
        elif tag == "a":
            self._close()

    def handle_data(self, data):
        if self._href is not None and not self._skip:
            self._text.append(data)


def html_links(markup, limit=None):
    """`[{"href", "text"}]` - the page's links as written (`href` not yet
    resolved against the page's URL), at most `INDEX_LINKS_MAX`. CF-0810:
    what a newsroom index (`newsroom_lookup`) is read for."""
    reader = _Anchors(INDEX_LINKS_MAX if limit is None else limit)
    try:
        reader.feed(markup or "")
        reader.close()
    except Exception:  # noqa: BLE001 - a broken page is read as far as it parses
        pass
    reader._close()
    return reader.links


def html_text(markup):
    """`{"title", "site_name", "blocks"}` of an HTML page: its prose blocks -
    the `<article>` / `<main>` part when it holds at least 200 characters,
    else the whole body - with scripts, styles, navigation, header, footer,
    forms and asides dropped."""
    reader = _Reader()
    try:
        reader.feed(markup or "")
        reader.close()
    except Exception:  # noqa: BLE001 - a broken page is read as far as it parses
        pass
    main, body = _blocks(reader.main), _blocks(reader.body)
    blocks = main if sum(len(b) for b in main) >= 200 else body
    return {"title": re.sub(r"\s+", " ", reader.title).strip(),
            "site_name": reader.site_name, "blocks": blocks}


def _local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def _plain(element, limit):
    """An element's text as plain words - an escaped-HTML summary's tags
    dropped, entities read, whitespace one space - cut at `limit`."""
    text = "".join(element.itertext()) if element is not None else ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", html.unescape(text)).strip()
    return text[:limit]


def feed_entries(raw, limit=FEED_ENTRIES_MAX):
    """CF-0914: `[{"title", "link", "summary", "text", "published"}]` of an
    RSS 2.0 / RDF / Atom feed, in the feed's order, at most `limit`; None
    when the answer is no feed. `summary` - the entry's description / summary
    (`FEED_SUMMARY_MAX`), `text` - its longest text field (`content:encoded`,
    Atom `content`, else the summary; `FEED_TEXT_MAX`). A feed that declares
    entities is never parsed (nothing is expanded)."""
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    if b"<!ENTITY" in (raw or b"").upper():
        return None
    try:
        root = ET.fromstring(raw or b"")
    except (ET.ParseError, ValueError):
        return None
    if _local(root.tag) not in ("rss", "feed", "rdf"):
        return None
    out = []
    for el in root.iter():
        if _local(el.tag) not in ("item", "entry"):
            continue
        rec = {"title": "", "link": "", "summary": "", "text": "", "published": ""}
        for child in el:
            name = _local(child.tag)
            if name == "title" and not rec["title"]:
                rec["title"] = _plain(child, 500)
            elif name == "link" and not rec["link"]:
                href = (child.get("href") or "").strip()
                if href and (child.get("rel") or "alternate") == "alternate":
                    rec["link"] = href
                elif not href and (child.text or "").strip():
                    rec["link"] = child.text.strip()
            elif name in ("description", "summary") and not rec["summary"]:
                rec["summary"] = _plain(child, FEED_SUMMARY_MAX)
            elif name in ("encoded", "content"):
                text = _plain(child, FEED_TEXT_MAX)
                if len(text) > len(rec["text"]):
                    rec["text"] = text
            elif name in ("pubdate", "published", "updated", "date") and not rec["published"]:
                rec["published"] = (child.text or "").strip()
        if not rec["text"]:
            rec["text"] = rec["summary"]
        if rec["link"]:
            out.append(rec)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# the client
# --------------------------------------------------------------------------

class _GatedRedirect(urllib.request.HTTPRedirectHandler):
    """Every redirect hop goes through the same door as the first URL."""

    def __init__(self, allow):
        super().__init__()
        self.allow = allow

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        why = self.allow(newurl)
        if why:
            raise PageError(f"redirected to {newurl}: {why}")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def urllib_transport(url, headers, timeout, max_bytes, allow):
    """The real network: `(status, content_type, final_url, body_bytes,
    truncated)`. `allow(url)` is asked before every redirect hop (None: may
    go). Raises PageError when nothing came back."""
    opener = urllib.request.build_opener(_GatedRedirect(allow))
    req = urllib.request.Request(url, headers=headers)
    try:
        with opener.open(req, timeout=timeout) as resp:  # noqa: S310 - gated https pages
            body = resp.read(max_bytes + 1)
            return (resp.status, resp.headers.get("Content-Type", ""), resp.geturl(),
                    body[:max_bytes], len(body) > max_bytes)
    except urllib.error.HTTPError as exc:
        return exc.code, (exc.headers.get("Content-Type", "") if exc.headers else ""), url, b"", False
    except (urllib.error.URLError, OSError) as exc:
        raise NetworkError(f"{type(exc).__name__}: {exc}")
    except ValueError as exc:
        raise PageError(f"{type(exc).__name__}: {exc}")


def _charset(content_type):
    m = re.search(r"charset=([\w-]+)", content_type or "", re.I)
    return m.group(1) if m else "utf-8"


class PageClient:
    """Reads a company's own page as text, through the vendor door, once a
    batch. `cache_dir` keeps the answers across processes (a refill round);
    `transport` is the tests' seam (`urllib_transport`'s signature)."""

    def __init__(self, cache_dir=None, transport=None, timeout=TIMEOUT, max_bytes=MAX_BYTES,
                 delay=DELAY, max_pages=MAX_PAGES_PER_BATCH, sleep=time.sleep,
                 clock=time.monotonic, retries=RETRIES, retry_delays=RETRY_DELAYS):
        self.cache_dir = Path(cache_dir) if cache_dir else None
        self.transport = transport or urllib_transport
        self.timeout, self.max_bytes, self.delay = timeout, max_bytes, delay
        self.max_pages = max_pages
        self.retries, self.retry_delays = int(retries), tuple(retry_delays or ())
        self.sleep, self.clock = sleep, clock
        self.request_count = 0                 # pages asked, a cache hit included
        self.network = {"requests": 0}         # pages that went out
        self._memo = {}
        self._last = None

    def _failed(self, url, error, attempts):
        """The record of a page nothing could be read off - kept in memory
        (not asked twice in one pass), never on disk."""
        page = {"url": url, "final_url": url, "status": None, "title": "", "site_name": "",
                "blocks": [], "truncated": False, "error": error, "attempts": attempts}
        self._memo[url] = page
        return page

    def _cache_path(self, url):
        if self.cache_dir is None:
            return None
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest() + ".json")

    def cached(self, url):
        """The kept answer of `url`, or None."""
        if url in self._memo:
            return self._memo[url]
        path = self._cache_path(url)
        if path is not None and path.exists():
            try:
                page = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                return None
            if isinstance(page, dict) and page.get("url") == url:
                self._memo[url] = page
                return page
        return None

    def page(self, url, sources, index=False):
        """`{"url", "final_url", "status", "title", "site_name", "blocks",
        "truncated", "error"}` of `url`; `error` set when it could not be read
        (an HTTP error, not an HTML page). Raises `source_gate.SourceClosed`
        when the outlet may not be read (nothing is asked) and `PageError`
        when the batch's ceiling is reached or nothing came back.

        `index` (CF-0914): the URL is a newsroom index, which may also be the
        vendor's RSS / Atom feed - an XML answer is then read as a feed
        (`feed_entries`: the page gets `feed: true` and `entries`, no
        blocks); a post is read only as HTML, as before."""
        why = source_gate.vendor_page_refusal(url, sources)
        if why:
            raise source_gate.SourceClosed(why)
        self.request_count += 1
        kept = self.cached(url)
        if kept is not None:
            return kept
        if self.network["requests"] >= self.max_pages:
            raise PageError(f"the pass read {self.max_pages} pages already "
                            f"(MAX_PAGES_PER_BATCH) - not asked")
        if self._last is not None and self.delay:
            wait = self.delay - (self.clock() - self._last)
            if wait > 0:
                self.sleep(wait)
        headers = {"User-Agent": USER_AGENT,
                   "Accept": INDEX_ACCEPT if index else "text/html,application/xhtml+xml"}
        attempts = 0
        while True:
            self.network["requests"] += 1
            attempts += 1
            failure = None
            try:
                status, ctype, final, body, truncated = source_gate.read_vendor_page(
                    url, sources, self.transport, headers, self.timeout, self.max_bytes,
                    lambda u: source_gate.vendor_page_refusal(u, sources))
            except NetworkError as exc:
                failure = str(exc)
            except PageError as exc:          # a refusal (a redirect off the outlet)
                return self._failed(url, str(exc), attempts)
            finally:
                self._last = self.clock()
            if failure is None and status not in RETRY_STATUS:
                break
            # CF-0790: the network or the server's "later" - asked again,
            # each attempt a read of its own under the pass's ceiling
            if attempts > self.retries or self.network["requests"] >= self.max_pages:
                if failure is not None:
                    return self._failed(url, failure, attempts)
                break
            delays = self.retry_delays or (0,)
            self.sleep(delays[min(attempts - 1, len(delays) - 1)])
        page = {"url": url, "final_url": final or url, "status": status, "title": "",
                "site_name": "", "blocks": [], "truncated": bool(truncated), "error": None,
                "attempts": attempts}
        if status != 200:
            page["error"] = f"answered {status}"
        elif index and any(t in (ctype or "").lower() for t in FEED_TYPES):
            entries = feed_entries(body or b"")
            if entries is None:
                page["error"] = f"not a readable RSS / Atom feed ({ctype})"
            else:
                page.update(feed=True, entries=entries)
        elif not any(t in (ctype or "").lower() for t in HTML_TYPES):
            page["error"] = f"not an HTML page ({ctype or 'no Content-Type'})"
        else:
            markup = (body or b"").decode(_charset(ctype), "replace")
            page.update(html_text(markup))
            page["links"] = html_links(markup)       # CF-0810: a newsroom index's releases
        self._memo[url] = page
        path = self._cache_path(url)
        if path is not None and page["error"] is None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(json.dumps(page, ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
        return page


def client_for(batch_dir, transport=None):
    """The pass's client, its cache in `<batch>/work/vendor-page-cache/`."""
    return PageClient(cache_dir=Path(batch_dir) / "work" / CACHE_DIR, transport=transport)


def counts(client):
    """`(sent, network)` of a client - as `fact_search.requests_of`."""
    if client is None:
        return 0, 0
    return int(client.request_count), int(client.network["requests"])


# --------------------------------------------------------------------------
# which page
# --------------------------------------------------------------------------

_HREF_RE = re.compile(r"""href\s*=\s*["']([^"']+)["']""", re.I)
_BARE_RE = re.compile(r"https?://[^\s\"'<>()\]]+")


def _clean_url(url):
    url = html.unescape(str(url or "")).strip().rstrip(".,;:")
    try:
        parts = urllib.parse.urlsplit(url)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def _is_front_page(url):
    path = urllib.parse.urlsplit(url).path or "/"
    return path.strip("/") == ""


def links_in(text):
    """Every URL of an HTML or plain text, in order."""
    found = []
    for m in list(_HREF_RE.finditer(text or "")) + list(_BARE_RE.finditer(text or "")):
        url = _clean_url(m.group(1) if m.re is _HREF_RE else m.group(0))
        if url and url not in found:
            found.append(url)
    return found


def _tier_one(url, sources, fact_rule):
    where = fact_rule.source_of(url, sources)
    return not where["banned"] and where["tier"] == source_gate.VENDOR_TIER


def _own_reader(url, sources):
    """An outlet the factory reads with a client of its own (`use:
    read_text` - Wikipedia, TVmaze, Wikidata): not read again here."""
    row = source_gate.outlet_of(url, sources)
    return isinstance(row, dict) and row.get("use") == "read_text"


def official_links(work, leads, pool_entries, sources, fact_rule, names_work,
                   limit=LINKS_PER_TOPIC):
    """`[(url, how)]` - the company's posts this topic may be told from, on a
    tier-1 host of the list, front pages aside, in the order of the module
    docstring: `lead` (the topic's own news is the post), `lead_link` (a link
    in a lead's summary), `vendor_feed` (a pool entry that names the work).
    Whether the outlet may be read is the door's question, not this one."""
    out, seen = [], set()

    def add(url, how):
        url = _clean_url(url)
        if (not url or url in seen or _is_front_page(url)
                or not _tier_one(url, sources, fact_rule) or _own_reader(url, sources)):
            return
        seen.add(url)
        out.append((url, how))

    for lead in leads or []:
        add(lead.get("url"), "lead")
    for lead in leads or []:
        for url in links_in(lead.get("summary")):
            add(url, "lead_link")
    for entry in pool_entries or []:
        link = entry.get("link")
        if not work or not _tier_one(link, sources, fact_rule):
            continue
        # CF-0914: the company's own feed may name the work without its
        # company ("Smart Driver" in GM's feed for "GM Smart Driver")
        names = work_names(work, row_names(source_gate.outlet_of(link, sources)),
                           list_names(sources))
        if any(names_work(name, entry) for name in names):
            add(link, "vendor_feed")
    return out[:limit]


# --------------------------------------------------------------------------
# the candidates of one page
# --------------------------------------------------------------------------

def sentence_kind(text):
    for kind, rx in VENDOR_KINDS:
        if rx.search(text or ""):
            return kind
    return "other"


def _norm(text):
    return " " + re.sub(r"[^a-z0-9]+", " ", str(text or "").lower()).strip() + " "


def page_candidates(page, work, outlet, limit=VENDOR_MAX):
    """Fact candidates off one page: whole sentences of `MIN_CHARS`..
    `MAX_CHARS` with a number or a month, boilerplate aside; those that name
    `work` first, then in the page's order. `outlet` is the list's row of the
    page's host (its id is the candidate's `source`)."""
    site = (page.get("site_name") or (outlet or {}).get("id") or "").strip()
    url = page.get("final_url") or page.get("url")
    needle = _norm(work).strip()
    found, seen = [], set()
    for block in page.get("blocks") or []:
        for sentence in _sentences.split_sentences(block):
            text = sentence.strip()
            if not (MIN_CHARS <= len(text) <= MAX_CHARS) or text[-1:] not in ".!?":
                continue
            if not (re.search(r"\d", text) or _MONTH_RE.search(text)):
                continue
            if _BOILER_RE.search(text) or text in seen:
                continue
            seen.add(text)
            found.append({"text": text, "kind": sentence_kind(text),
                          "source": (outlet or {}).get("id") or site, "url": url,
                          "attribution": f"{site} says" if site else None,
                          "headline": page.get("title") or None,
                          "vendor_page": True,
                          "_named": bool(needle) and f" {needle} " in _norm(text)})
    found.sort(key=lambda c: not c["_named"])
    for cand in found:
        del cand["_named"]
    return found[:limit]


# --------------------------------------------------------------------------
# CF-0810: the vendor's newsroom index
# --------------------------------------------------------------------------

def _bare_host(url):
    host = (urllib.parse.urlsplit(url or "").hostname or "").lower()
    return host[4:] if host.startswith("www.") else host


def host_stem(host):
    """The company's word in a host: `newsroom.porsche.com` -> `porsche`,
    `deepseek.com` -> `deepseek`, `news.example.co.uk` -> `example`,
    `blog.google` -> `google` (a service label is never the stem, the label
    to its right is), `news.com` -> `` (nothing but service and TLD-like
    labels)."""
    labels = [x for x in (host or "").lower().split(".") if x and x != "www"]
    if (len(labels) >= 3 and len(labels[-1]) == 2
            and labels[-2] in ("co", "com", "ac", "org", "net", "gov")):
        at = len(labels) - 3
    elif len(labels) >= 2:
        at = len(labels) - 2
    else:
        return labels[0] if labels and labels[0] not in SERVICE_LABELS else ""
    while at < len(labels) and labels[at] in SERVICE_LABELS:
        at += 1
    if at >= len(labels) or (at == len(labels) - 1 and labels[at] in GENERIC_TLD_LABELS):
        return ""
    return labels[at]


def stem_names(host):
    """The host's stem as a name the topic may name the company by - none
    when it is shorter than `MIN_STEM_CHARS` or an everyday word
    (`COMMON_WORD_STEMS`: such a company is named by its row's `names`)."""
    stem = host_stem(host)
    return [stem] if len(stem) >= MIN_STEM_CHARS and stem not in COMMON_WORD_STEMS else []


def _str_list(value):
    if isinstance(value, str):
        value = [value]
    return [str(x).strip() for x in value or [] if isinstance(x, str) and x.strip()]


def newsroom_entries(row):
    """`[(index_url, names)]` of a tier-1 row's `newsroom` field: a list
    whose item is an index URL, or `{"url": <index URL>, "names": [...]}`.
    `names` - the row's own `names` (optional), the item's, and the stem of
    the index's host (`stem_names`: `host_stem`, at least `MIN_STEM_CHARS`,
    not an everyday word of `COMMON_WORD_STEMS`)."""
    if not isinstance(row, dict):
        return []
    field = row.get(NEWSROOM_FIELD)
    if isinstance(field, (str, dict)):
        field = [field]
    out = []
    for item in field if isinstance(field, list) else []:
        url, extra = (item.get("url"), item.get(NAMES_FIELD)) if isinstance(item, dict) \
            else (item, None)
        url = _clean_url(url) if isinstance(url, str) else None
        if not url:
            continue
        names = _str_list(row.get(NAMES_FIELD)) + _str_list(extra)
        names += stem_names(urllib.parse.urlsplit(url).hostname)
        seen, uniq = set(), []
        for name in names:
            if name.lower() not in seen:
                seen.add(name.lower())
                uniq.append(name)
        out.append((url, uniq))
    return out


def row_names(row):
    """CF-0914: every name a tier-1 row's company goes by - the row's
    `names`, its newsroom items' `names` and the stem of each of its hosts
    (`stem_names`)."""
    if not isinstance(row, dict):
        return []
    names = _str_list(row.get(NAMES_FIELD))
    field = row.get(NEWSROOM_FIELD)
    for item in field if isinstance(field, list) else [field]:
        if isinstance(item, dict):
            names += _str_list(item.get(NAMES_FIELD))
    for host in _str_list(row.get("hosts")):
        names += stem_names(host)
    seen, out = set(), []
    for name in names:
        if name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


_COMMON = None


def _common_words():
    global _COMMON
    if _COMMON is None:
        try:
            lines = COMMON_WORDS.read_text(encoding="utf-8").splitlines()
        except OSError:
            lines = []
        _COMMON = {w.strip().lower() for w in lines if w.strip() and not w.startswith("#")}
    return _COMMON


def list_names(sources):
    """Every company name of the list's tier-1 rows (`row_names`), lower
    case - a rest that is one of them is another company, not a work."""
    out = set()
    for row in ((sources or {}).get("tiers") or {}).get(str(source_gate.VENDOR_TIER)) or []:
        out.update(_norm(n).strip() for n in row_names(row))
    out.discard("")
    return out


def release_names(work, company_names, others=()):
    """CF-0914: the names a release on the company's own index or feed is
    matched by - `work_names` less any that is the company's own name: a
    topic whose work *is* the company ("Reddit") is not told from whichever
    post of its newsroom names the company."""
    own = {_norm(n).strip() for n in company_names or []}
    return [n for n in work_names(work, company_names, others) if _norm(n).strip() not in own]


def work_names(work, company_names, others=()):
    """CF-0914: the names the company's own post may name the work by - the
    work's whole name, and, when it starts with one of `company_names` (or
    its possessive) or ends with one, the rest of it: GM's newsroom writes
    "Smart Driver", not "GM Smart Driver"; Apple's "HomeView", not "Apple's
    HomeView". The rest counts only as a name of its own - at least
    `MIN_REST_CHARS` characters, and not one everyday word of
    `config/common_words.txt` ("Intel stock" stays whole), and not another
    company of the list (`others`: "Nvidia Nscale" on Nscale's outlet is
    not "Nvidia"). Only the post's
    own company is cut off, so nothing here widens another vendor's match;
    the fact rule judges the sentences as before."""
    out = [work] if isinstance(work, str) and work.strip() else []
    whole = _norm(work).strip()
    if not whole:
        return out
    for name in company_names or []:
        key = _norm(name).strip()
        if not key or key == whole:
            continue
        rest = None
        for prefix in (key + " s ", key + " "):
            if whole.startswith(prefix):
                rest = whole[len(prefix):]
                break
        if rest is None and whole.endswith(" " + key):
            rest = whole[:-len(key) - 1]
        rest = (rest or "").strip()
        if len(rest) < MIN_REST_CHARS or rest in others or (" " not in rest and (
                rest in _common_words() or rest in GENERIC_REST_WORDS)):
            continue
        if rest not in [_norm(x).strip() for x in out]:
            out.append(rest)
    return out


def topic_texts(topic, work, leads):
    """What the topic says about itself - where a company must be named for
    its newsroom to be read: the work's name, the topic's title, its leads'
    headlines and summaries."""
    texts = [work, topic.get("title")]
    for lead in leads or []:
        texts += [lead.get("title"), lead.get("summary")]
    return [t for t in texts if isinstance(t, str) and t.strip()]


def newsroom_indexes(texts, sources, names_work, limit=INDEXES_PER_TOPIC):
    """`(indexes, closed)` - the newsroom indexes of the tier-1 rows whose
    company the topic names (`names_work(name, {"title": text})` - the same
    whole-word match a feed entry gets), each `{"index", "outlet", "named"}`;
    an index the vendor door refuses (a verdict not `allowed`, a host off the
    row's own) goes to `closed` and is never asked."""
    indexes, closed = [], []
    for row in ((sources or {}).get("tiers") or {}).get(str(source_gate.VENDOR_TIER)) or []:
        for url, names in newsroom_entries(row):
            named = next((n for n in names
                          if any(names_work(n, {"title": t}) for t in texts)), None)
            if named is None:
                continue
            owner = source_gate.outlet_of(url, sources) or {}
            why = source_gate.vendor_page_refusal(url, sources)
            if not why and owner.get("id") != row.get("id"):
                why = (f"{_bare_host(url)}: the newsroom index of {row.get('id')} is listed "
                       f"under {owner.get('id') or 'no outlet'} - not the row's own host")
            if why:
                verdict = (owner.get("ai_policy") or {}).get("verdict") if owner else None
                closed.append({"url": url, "how": HOW_INDEX,
                               "host": urllib.parse.urlsplit(url).hostname,
                               "outlet": row.get("id"), "verdict": verdict, "why": why})
                continue
            if url not in [i["index"] for i in indexes]:
                indexes.append({"index": url, "outlet": row.get("id"), "named": named,
                                "company": row_names(row) + [n for n in names
                                                             if n not in row_names(row)]})
    return indexes[:limit], closed


def named_outlets(texts, sources, names_work):
    """CF-0914: `[{"outlet", "named", "verdict", "newsroom"}]` - every tier-1
    row whose company the topic names (`row_names`, the same whole-word
    match as `newsroom_indexes`), whether or not it lists a newsroom: what
    the `no_link` reason says, so a refusal names the company it could have
    been told from and why it was not ("openai.com: allowed, no newsroom
    listed", "apple.com: forbidden")."""
    out = []
    for row in ((sources or {}).get("tiers") or {}).get(str(source_gate.VENDOR_TIER)) or []:
        if not isinstance(row, dict) or row.get("use") == "read_text":
            continue
        names = [n for n in row_names(row)
                 if n in _str_list(row.get(NAMES_FIELD)) or n.lower() not in _common_words()]
        named = next((n for n in names
                      if any(names_work(n, {"title": t}) for t in texts)), None)
        if named is None:
            continue
        hosts = _str_list(row.get("hosts"))
        host = next((h for h in hosts if host_stem(h) == named.lower()), hosts[0] if hosts else None)
        out.append({"outlet": row.get("id"), "named": named, "host": host,
                    "verdict": (row.get("ai_policy") or {}).get("verdict"),
                    "newsroom": bool(newsroom_entries(row))})
    return out


def _named_where(named):
    """The `where` words of `named_outlets`."""
    parts = []
    for n in named:
        if n["verdict"] != "allowed":
            parts.append(f"{n['host']}: {n['verdict'] or 'no verdict'}")
        elif not n["newsroom"]:
            parts.append(f"{n['host']}: allowed, no newsroom listed")
    return ", ".join(parts)


def newsroom_releases(page, index_url, work, names_work, limit=LINKS_PER_TOPIC, names=None):
    """`(urls, same_host)` - the index's links on its own host (front pages
    and the index aside) whose text or slug names the work
    (`names_work(work, {"title": ...})`: the work's whole name, or, CF-0914,
    one of `names` - `work_names`, the work without the index's own company),
    and how many same-host links it had."""
    names = list(names or [work])
    base = page.get("final_url") or index_url
    host = _bare_host(base)
    skip = {_clean_url(index_url), _clean_url(base)}
    found, same_host, seen = [], 0, set()
    for link in page.get("links") or []:
        url = _clean_url(urllib.parse.urljoin(base, (link or {}).get("href") or ""))
        if not url or url in skip or url in seen or _bare_host(url) != host \
                or _is_front_page(url):
            continue
        seen.add(url)
        same_host += 1
        slug = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rstrip("/")
                                    .rsplit("/", 1)[-1])
        slug = re.sub(r"\.(?:s?html?|php|aspx?)$", "", slug, flags=re.I)
        if any(names_work(name, {"title": link.get("text") or ""})
               or names_work(name, {"title": slug.replace("-", " ").replace("_", " ")})
               for name in names):
            found.append(url)
    return found[:limit], same_host


def feed_releases(page, index_url, outlet_id, sources, names, names_work,
                  limit=LINKS_PER_TOPIC):
    """CF-0914: `(urls, own, entries)` off a newsroom index that is a feed -
    its entries whose link is on the index row's own outlet (front pages and
    the index aside) and whose title, link slug or summary names the work
    (`names`: `work_names`; a summary only for a name of
    `fact_search.MIN_NAME_CHARS_IN_SUMMARY` or more - `names_work`), how
    many of its entries were on the outlet, and `{url: entry}` of the ones
    taken (a post that refuses the client is told from its entry)."""
    skip = {_clean_url(index_url), _clean_url(page.get("final_url") or index_url)}
    found, own, entries = [], 0, {}
    for entry in page.get("entries") or []:
        url = _clean_url(urllib.parse.urljoin(page.get("final_url") or index_url,
                                              entry.get("link") or ""))
        if not url or url in skip or url in entries or _is_front_page(url):
            continue
        row = source_gate.outlet_of(url, sources)
        if not isinstance(row, dict) or row.get("id") != outlet_id:
            continue
        own += 1
        slug = urllib.parse.unquote(urllib.parse.urlsplit(url).path.rstrip("/")
                                    .rsplit("/", 1)[-1])
        slug = re.sub(r"\.(?:s?html?|php|aspx?)$", "", slug, flags=re.I)
        slug = slug.replace("-", " ").replace("_", " ")
        if any(names_work(name, {"title": entry.get("title") or "",
                                 "summary": entry.get("summary") or ""})
               or names_work(name, {"title": slug}) for name in names):
            if len(found) < limit:
                found.append(url)
                entries[url] = entry
    return found, own, entries


def newsroom_lookup(topic, work, leads, sources, client, names_work, want=PAGES_PER_TOPIC):
    """`(links, records, closed)` for a topic whose news carries no tier-1
    link: the newsroom indexes of the companies it names
    (`newsroom_indexes`) read through `client` - the same door, User-Agent,
    cache and pass ceiling as a post - until `want` releases naming the work
    are found. `links` `[(url, "newsroom")]`; `records` one per index asked
    (`{"index", "outlet", "named", "outcome", "links", "matched", "detail"}`,
    `outcome` `matched` / `newsroom_no_match` / `unreachable` / `cap`).

    CF-0914: an index may be the vendor's feed (`kind: feed`, else
    `index`); its entries are matched by `feed_releases`, the work's name
    with or without the company's (`work_names`) - an HTML index's links
    too. The fourth value is `{url: feed entry}` of the releases a feed gave
    (`lookup` tells a post that refuses the client from its entry)."""
    if not work or client is None:
        return [], [], [], {}
    indexes, closed = newsroom_indexes(topic_texts(topic, work, leads), sources, names_work)
    links, records, entries = [], [], {}
    for item in indexes:
        if len(links) >= want:
            break
        company = item.pop("company", None) or []
        rec = dict(item, outcome=None, links=0, matched=[], detail=None)
        names = release_names(work, company, list_names(sources))
        try:
            page = client.page(item["index"], sources, index=True)
        except source_gate.SourceClosed as exc:
            closed.append({"url": item["index"], "how": HOW_INDEX, "why": str(exc)})
            continue
        except PageError as exc:
            records.append(dict(rec, outcome=OUTCOME_CAP, detail=str(exc)))
            break
        if page.get("error"):
            records.append(dict(rec, outcome=OUTCOME_UNREACHABLE, detail=page["error"]))
            continue
        if page.get("feed"):
            rec["kind"] = "feed"
            found, same_host, taken = feed_releases(page, item["index"], item["outlet"],
                                                    sources, names, names_work)
            for url, entry in taken.items():
                entries.setdefault(url, entry)
        else:
            rec["kind"] = "index"
            found, same_host = newsroom_releases(page, item["index"], work, names_work,
                                                 names=names)
        found = [u for u in found if u not in [x for x, _ in links]]
        rec.update(links=same_host, matched=found)
        if found:
            rec["outcome"] = "matched"
            links += [(u, VIA_NEWSROOM) for u in found]
        else:
            rec["outcome"] = OUTCOME_NEWSROOM_NO_MATCH
            rec["detail"] = f"no release names {work!r} among {same_host} link(s)"
        records.append(rec)
    return links[:LINKS_PER_TOPIC], records, closed, entries


# --------------------------------------------------------------------------
# one topic
# --------------------------------------------------------------------------

def lookup(topic, leads, pool_entries, sources, fact_rule, client, names_work,
           news_text=None, about_person=False, pages=PAGES_PER_TOPIC):
    """`(candidates, asked)` for one topic that has no passing fact yet: the
    company's posts (`official_links`) read through `client` until one gives
    a candidate that passes the rule (`fact_rule.check_candidate`, with the
    topic's news) or `pages` were read. `asked` is the `fact_search.asked[]`
    row (module docstring). Never raises for a page or a closed outlet."""
    ref = topic.get("title_ref") or {}
    work = ref.get("name") or ref.get("person")
    sent0, wire0 = counts(client)
    links = official_links(work, leads, pool_entries, sources, fact_rule, names_work)
    rows, closed, candidates = [], [], []
    via, newsroom, feed_items = None, [], {}
    if not links:
        # CF-0810: no tier-1 link anywhere - the company's newsroom index
        # (CF-0914: or its feed)
        links, newsroom, closed, feed_items = newsroom_lookup(topic, work, leads, sources,
                                                              client, names_work, want=pages)
        via = VIA_NEWSROOM if links else None
    passed, read, cap = False, 0, False
    for url, how in links:
        if read >= pages or passed:
            break
        why = source_gate.vendor_page_refusal(url, sources)
        if why:
            where = fact_rule.source_of(url, sources)
            verdict = ((source_gate.outlet_of(url, sources) or {}).get("ai_policy") or {}).get(
                "verdict")
            closed.append({"url": url, "how": how, "host": where["host"],
                           "outlet": where["id"], "verdict": verdict, "why": why})
            continue
        read += 1
        try:
            page = client.page(url, sources)
        except source_gate.SourceClosed as exc:      # the door said no at the client
            closed.append({"url": url, "how": how, "why": str(exc)})
            continue
        except PageError as exc:
            cap = True
            rows.append({"url": url, "how": how, "outcome": OUTCOME_CAP, "detail": str(exc),
                         "candidates": 0})
            break
        read_from = None
        if page.get("error"):
            entry = feed_items.get(url)
            if not entry or len(entry.get("text") or "") < MIN_CHARS:
                rows.append({"url": url, "how": how, "outcome": OUTCOME_UNREACHABLE,
                             "detail": page["error"], "candidates": 0})
                continue
            # CF-0914: the post refuses the client (openai.com answers 403 to
            # it, its feed does not) - the vendor's own words in its feed's
            # entry, read through the same door, are the page
            read_from = page["error"]
            page = {"url": url, "final_url": url, "title": entry.get("title") or "",
                    "site_name": "", "blocks": [entry["text"]], "truncated": False}
        found = page_candidates(page, work, source_gate.outlet_of(url, sources))
        if about_person:
            for cand in found:
                cand["about_person"] = True
        passing = sum(1 for c in found
                      if fact_rule.check_candidate(c, sources, news_text)["passes"])
        passed = passing > 0
        candidates.extend(found)
        row = {"url": url, "how": how, "outcome": OUTCOME_OK if passing
               else OUTCOME_NO_CANDIDATES, "candidates": len(found),
               "passing": passing, "truncated": bool(page.get("truncated")),
               "title": page.get("title") or None}
        if read_from:
            row.update(read=VIA_FEED_ENTRY, detail=f"post {read_from}; told from its feed entry")
        rows.append(row)
    index_outcomes = {r["outcome"] for r in newsroom}
    if passed:
        outcome = OUTCOME_OK
    elif any(r["outcome"] == OUTCOME_NO_CANDIDATES for r in rows):
        outcome = OUTCOME_NO_CANDIDATES
    elif cap or OUTCOME_CAP in index_outcomes:
        outcome = OUTCOME_CAP
    elif rows or OUTCOME_UNREACHABLE in index_outcomes:
        outcome = OUTCOME_UNREACHABLE
    elif OUTCOME_NEWSROOM_NO_MATCH in index_outcomes:
        outcome = OUTCOME_NEWSROOM_NO_MATCH
    elif closed:
        outcome = OUTCOME_CLOSED
    else:
        outcome = OUTCOME_NO_LINK
    unread = [r for r in newsroom if r["outcome"] != "matched"]
    if rows or unread:
        where = ", ".join(
            [f"{urllib.parse.urlsplit(r['url']).hostname}: {r['outcome']}"
             + (f" ({r['detail']})" if r.get("detail") else "") for r in rows]
            + [f"{_bare_host(r['index'])}{urllib.parse.urlsplit(r['index']).path} "
               f"newsroom: {r['outcome']}" + (f" ({r['detail']})" if r.get("detail") else "")
               for r in unread])
    elif closed:
        where = ", ".join(sorted({f"{c.get('host')}: {c.get('verdict') or 'closed'}"
                                  for c in closed}))
    else:
        where = "no tier-1 link in the topic's news or the pool"
        # CF-0914: which company the topic names, and why its page was not read
        named = _named_where(named_outlets(topic_texts(topic, work, leads), sources,
                                           names_work)) if work else ""
        if named:
            where += f"; named {named}"
    sent1, wire1 = counts(client)
    asked = {"source": VENDOR_SOURCE, "outcome": outcome, "candidates": len(candidates),
             "passing_pages": sum(1 for r in rows if r.get("passing")),
             "links": len(links), "pages": rows, "closed": closed, "where": where,
             "requests": sent1 - sent0, "network": wire1 - wire0}
    if newsroom or via:
        asked["via"] = via
        asked["newsroom"] = newsroom
    return candidates, asked
