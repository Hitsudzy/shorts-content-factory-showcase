#!/usr/bin/env python3
"""CF-0438, part 2: where Trend Hunter finds the fact candidates for a topic.

Until CF-0438 the only question asked at selection was "does the Wikipedia
article have a Production / Filming / Design sentence?" (`fact_probe.py` in
the Content Researcher's tree, CF-0263), and 46 topics over 13 batches left for
the answer "no". The grill of 2026-09-29 widened the fact: any kind (a box-office
number, a casting story, a release, the reception, a scandal, news about the
people in it) from a wide list of outlets - the batch's channel's
(`<root>/channels/<id>/fact-sources.json`, CF-0627).
The topic is dropped only when *no* candidate passes the rule's requirements
(`fact_rule.check_candidate`, Q4 of that grill).

This module collects the candidates; the rule judges them. It asks two places,
and it is honest about which ones - the list of outlets a fact *may* come from
is wider than the list this stage actually *reads*:

  1. **Wikipedia, every section** - the article `fact_probe.py` already resolved
     for the topic (its search, its parent-work fallback and its
     wrong-article guard stay the one place they live). One more request per
     topic, through the factory's one Wikipedia client (`_wikipedia.py` ->
     the root's `shared/wikipedia/wikipedia_api.py`, CF-0559): `api.wikimedia.org`
     Core REST, >= 1 s between requests, the hunter's name in the User-Agent,
     its retries - the wikitext of that article. In a batch the client is the
     one the support text reads through (`support_text.client_for`, cached in
     `<batch>/work/wikipedia-cache/`), so the article read here is not asked
     for a second time there.
     Every prose sentence with a number, a date or a name becomes a candidate,
     its `kind` read off the section it stands in (Box office -> box_office,
     Release -> release, Reception / Accolades -> reception, Casting ->
     casting, Production / Filming / Design / Development -> production,
     Controversy -> scandal, the rest -> other), and the first citation of the
     sentence that is not Wikipedia itself goes in `primary_url` - so a claim
     about a person that Wikipedia took from Variety stands on Variety.
     Plot, cast lists, episode tables and reference sections are not facts and
     are not read.

  2. **The news this batch already fetched** - the `fetch_rss_news.py` output
     (`--rss`): every entry of *other* posts that names the work, from any of
     the trades the stage reads (Variety, Deadline, THR, IndieWire, Collider,
     ScreenRant...), is a candidate with `attribution` "<outlet> reported".
     The topic's own leads are not candidates - they are the news the fact
     must add to (`news_text`). Costs no request at all.
     **Only an entry of a `read_text` feed** (CF-0638, the user's decision of
     08.10, CF-0557 Q1 variant b: the feeds are for choosing topics, the
     writer gets no excerpt of them): the entry's `feed_url` must be among
     `text_feeds` - the channel's `channel_data.support_feed_urls`. An entry
     of a `headline_only` feed, of a feed that is not the channel's, or of no
     known feed gives no candidate, its headline included; `text_feeds` empty
     or None is no feed at all (closed, not open). example-film has no
     `read_text` feed, so its fact is Wikipedia's - `docs/news-facts-2026-10.md`
     measured the cost: 0 of 48 topics held their fact on a news one only.

  3. **Wikidata's statements about the work** (CF-0637, the user's decision of
     08.10 on CF-0557 Q2) - when the channel's list names the outlet
     `wikidata` `use: read_text` / `allowed` (`fact_probe_topics.make_supporter`
     opens the client then, and only then) and the article above was read:
     the item whose English Wikipedia sitelink is that article (the work's,
     for a season article) is found through the factory's one Wikidata client
     (`_wikidata.py` -> the root's `shared/wikidata/wikidata_api.py`,
     `resolve_item`: a search, at most two entity reads, <= 3 requests a
     topic, counted apart from Wikipedia's), and its statements of the
     channel's `properties` (release dates, cast, crew, studio, network,
     awards...) become candidates (`wikidata_api.candidate_of`: one English
     sentence, `source` Wikidata, a www.wikidata.org URL). Only a candidate of
     one of the channel's `kinds` that passes the rule is kept, at most
     `WIKIDATA_MAX`, one kind after another. Wikidata is not a major outlet: a
     topic about a person takes none of them (the rule's stricter half). A
     Wikidata that cannot be read is written in `asked` and nowhere else - it
     never makes the topic `source_unreachable` when Wikipedia answered. The
     same client (and its `<batch>/work/wikidata-cache/`) serves the support
     text, and the item found here is not asked for again there
     (`wikidata_lookup` keeps it on the client).

Not asked today, though the config allows them: AP, Reuters, BBC, the
Guardian, the NYT, Screen Daily, Box Office Mojo, The Numbers, studio press
sites and creator interviews found by search. The stage has no search over them
that needs no new key; a fact from one of them reaches the batch only as
Wikipedia's citation (`primary_url`) or as an RSS post that is itself on a
listed host. The writer (Content Researcher, step 2) may still bring such a
candidate itself and the same rule judges it.

  4. **The company's own post** (CF-0757, hotfix 2.4.1) - not here but in
     `vendor_page.py`, asked by `fact_probe_topics.select_batch` only when
     none of the three above gave a passing candidate: a tier-1 outlet of the
     channel's list whose `ai_policy.verdict` is `allowed`, read through
     `source_gate.read_vendor_page` (`asked[]` `source: vendor_page`).

**No other host is read except through `source_gate.read_text`** (CF-0634):
the outlet must stand in the channel's list (`sources`, which every call here
already carries) with `use: read_text` and `ai_policy.verdict: allowed`.
Nothing here reads one today - the news candidates come out of the fetch
already made, and every listed outlet but Wikipedia is `cite_only` for
example-film; CF-0636 (TVmaze) is the first reader through that door.

Stdlib only. The client is a `wikipedia_api.WikipediaClient` (`client=`);
tests hand in one on a recorded transport, so they never leave the machine.
Until CF-0559 this module had an `HttpClient` of its own and read the article
past the shared client and its cache - the same article was asked for twice a
topic, once here and once by `support_text.py`.
"""
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    # the root loads this module by path (`sources_pool_measure.py`)
    sys.path.insert(0, str(HERE))

import _sentences  # noqa: E402  - CF-0737

WIKI_SOURCE = "wikipedia"
NEWS_SOURCE = "rss_pool"
WIKIDATA_SOURCE = "wikidata"     # CF-0637: `asked[].source` of the Wikidata lookup
WIKI_READER_URL = "https://en.wikipedia.org/wiki/{key}"
# The hunter's name in the shared client's User-Agent (CF-0551, CF-0559) -
# `support_text.TOOL_NAME` is this one.
TOOL_NAME = "shorts-content-factory-trend-hunter"

# The probe's outcomes under which its `article` is the topic's own article.
# `wrong_article` names an article that is someone else's; `no_article` names
# none; `source_unreachable` could not ask. Nothing here is read as "has a
# Production section" (CF-0439): since the researcher's probe reads every
# prose section, `no_section` means the article has nothing but plot and cast
# to read - and it is still the topic's own article, so its lead is read here
# like any other; the probe's own `sections` and candidate count are not
# consulted at all, this stage reads the article itself.
ARTICLE_OUTCOMES = ("ok", "no_section", "no_candidates")

WIKI_MAX = 12        # candidates per topic taken from the article
NEWS_MAX = 6         # candidates per topic taken from the batch's news
KEEP_MAX = 8         # checked candidates written onto the topic in 01
WIKIDATA_MAX = 6     # CF-0637: candidates per topic taken from Wikidata's statements
MIN_CHARS = 40
MAX_CHARS = 320
MIN_NAME_CHARS_IN_SUMMARY = 6

# Sections that are not facts: the story itself, lists, apparatus.
SKIP_HEADING_RE = re.compile(
    r"\b(plot|synopsis|premise|summary|story|cast|characters|episodes|"
    r"see also|references|notes|external links|further reading|bibliography|"
    r"citations|sources|footnotes|track listing|gallery)\b", re.I)
# Heading -> kind, first match wins. Which kind wins among sections is
# the channel's `kinds` order (`kind_order`), and only as a tie-break (CF-0439).
HEADING_KINDS = (
    ("box_office", re.compile(r"box office|gross|commercial performance|ratings|viewership", re.I)),
    ("casting", re.compile(r"casting", re.I)),
    ("production", re.compile(r"production|filming|development|design|writing|"
                              r"pre-production|post-production|effects|cinematograph|"
                              r"music|score|costume|makeup|stunt|conception|origin", re.I)),
    ("release", re.compile(r"release|marketing|distribution|broadcast|premiere|"
                           r"home media|streaming|promotion", re.I)),
    ("reception", re.compile(r"reception|critical|accolades|awards|response|legacy|"
                             r"audience|reviews|impact", re.I)),
    ("scandal", re.compile(r"controvers|lawsuit|legal|allegation|dispute|criticism", re.I)),
    ("people_news", re.compile(r"personal life", re.I)),
)
# A tie-break and nothing more (CF-0439): the stance takes a fact of any kind,
# so which kind a fact is never beats what it has - whether it passes the
# rule, its source's tier, a number, an attribution (`fact_rule._rank` and
# `search_topic`). Only between two candidates equal on all of those does a
# production sentence go first. Pinned by tests/test_fact_search.py.
#
# CF-0627 (CF-0561): the order is the channel's - the order of `kinds` in its
# fact-sources list (`fact_rule.kinds_of(sources)`), not a list of this file's:
# a science channel's first kind is not `production`. A kind the list does
# not name sorts after every kind it does.


def kind_order(sources, fact_rule):
    """`{kind: rank}` of the channel's kinds, in the order its list gives
    them (`fact_rule.kinds_of` - a list without `kinds` raises ValueError)."""
    return {k: i for i, k in enumerate(fact_rule.kinds_of(sources))}

# News kinds, by the words of the post.
NEWS_KINDS = (
    ("box_office", re.compile(r"box office|opening weekend|grossed|\bgross\b|ticket sales|"
                              r"\$\d", re.I)),
    ("scandal", re.compile(r"lawsuit|\bsued\b|\bsues\b|arrest|accus|allegation|"
                           r"controvers|backlash|fired|misconduct", re.I)),
    ("casting", re.compile(r"\bcast\b|\bcasts\b|casting|joins|to star|to play|"
                           r"in talks to|boards", re.I)),
    ("release", re.compile(r"release date|premiere|trailer|teaser|debut|streaming on|"
                           r"sets .* date|dated|delayed|renewed|cancell?ed", re.I)),
    ("reception", re.compile(r"review|rotten tomatoes|metacritic|award|nominat|"
                             r"\bwins\b|record", re.I)),
    ("production", re.compile(r"filming|shoot|production|wrapped|director|script|"
                              r"showrunner|writers? room", re.I)),
)


# --------------------------------------------------------------------------
# the client: the factory's one (CF-0559)
# --------------------------------------------------------------------------

def wikipedia_api():
    """The shared client module, `shared/wikipedia/wikipedia_api.py` of the
    factory root, loaded on first use through `_wikipedia.py` - importing this
    module does not look for the root (`sources_pool_measure.py` of the root
    loads it by path for its constants)."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from _wikipedia import wikipedia_api as wp
    return wp


def wikidata_api():
    """CF-0637: the shared Wikidata client module (`shared/wikidata/
    wikidata_api.py` of the factory root, through `_wikidata.py`), loaded on
    first use - as `wikipedia_api()`."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from _wikidata import wikidata_api as wd
    return wd


def default_client():
    """A shared client under the hunter's name, with no cache - for a caller
    that has no batch. A pass over a batch hands in the one client it reads
    the support text through (`fact_probe_topics.select_batch`)."""
    return wikipedia_api().WikipediaClient(tool_name=TOOL_NAME)


def requests_of(client):
    """`(asked, network)` page requests this client has made so far: `asked`
    is every request the client sent (a cache hit included), `network` the
    ones that went past the cache to Wikipedia (`support_text.client_for`
    counts them; a client without that count has no cache, so every request
    it sent went out)."""
    asked = int(getattr(client, "request_count", 0) or 0)
    wire = getattr(client, "network", None)
    return asked, (int(wire["requests"]) if isinstance(wire, dict) else asked)


class Unreachable(RuntimeError):
    """The source could not be asked - never "no fact"."""


# --------------------------------------------------------------------------
# Wikipedia: every section of the resolved article
# --------------------------------------------------------------------------

def article_key(title):
    return (title or "").strip().replace(" ", "_")


def fetch_wikitext(title, client):
    """`(key, wikitext)` of the article, following one redirect page.
    `(None, None)` for an article that does not exist; raises Unreachable.

    `client` is the shared `WikipediaClient`: its `page()` follows the
    endpoint's `redirect_target` itself; a redirect page that comes back
    without one (`#REDIRECT [[...]]` in the wikitext) is followed here once,
    as this module always did."""
    wp = wikipedia_api()
    key = article_key(title)
    for _ in range(2):
        try:
            article = client.page(key)
        except (wp.WikipediaError, OSError, ValueError) as exc:
            raise Unreachable(f"wikipedia: {exc}")
        if article is None:
            return None, None
        text = article.get("wikitext") or ""
        redirect = re.match(r"\s*#redirect\s*\[\[([^\]|#]+)", text, re.I)
        if redirect:
            key = article_key(redirect.group(1))
            continue
        return article.get("key") or key, text
    return key, ""


_REF_RE = re.compile(r"<ref(?P<attrs>[^>]*?)(?:/>|>(?P<body>.*?)</ref\s*>)", re.S | re.I)
_REF_NAME_RE = re.compile(r"""name\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s/>]+))""", re.I)
_URL_RE = re.compile(r"\|\s*url\s*=\s*([^|}\s]+)", re.I)
_BARE_URL_RE = re.compile(r"https?://[^\s|}\]<]+")
_ARCHIVE_HOSTS = ("web.archive.org", "archive.today", "archive.ph", "archive.is")
_MARK = "\x00{}\x01"
_MARK_RE = re.compile(r"\x00(\d+)\x01")
_HEADING_RE = re.compile(r"^(={2,6})\s*(.+?)\s*\1\s*$", re.M)


def _ref_url(body):
    if not body:
        return None
    for match in list(_URL_RE.finditer(body)) + list(_BARE_URL_RE.finditer(body)):
        url = match.group(1) if match.re is _URL_RE else match.group(0)
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        if host and not any(host.endswith(a) for a in _ARCHIVE_HOSTS):
            return url.strip()
    return None


def _ref_name(attrs):
    m = _REF_NAME_RE.search(attrs or "")
    return next((g for g in m.groups() if g), None) if m else None


def _mask_refs(text):
    """Every <ref> becomes a marker; returns `(text, urls)`, `urls[i]` the
    cited URL of marker i (or None). Named re-uses take the named ref's URL."""
    named = {}
    for m in _REF_RE.finditer(text):
        name = _ref_name(m.group("attrs"))
        if name and m.group("body"):
            named.setdefault(name, _ref_url(m.group("body")))
    urls = []

    def repl(m):
        url = _ref_url(m.group("body")) if m.group("body") else named.get(_ref_name(m.group("attrs")))
        urls.append(url)
        return _MARK.format(len(urls) - 1)
    return _REF_RE.sub(repl, text), urls


# CF-0673: the article's prose is the root's one reading of wikitext
# (`wikipedia_api.plain_text`): it unwraps `{{val}}` and `{{convert}}` (ranges
# included) into the number in the page's own unit, the word templates
# (`{{US$|N}}` / `{{USD|N}}` as `$N`, `{{nbsp}}`, the possessive `{{'s}}` and
# `{{'}}` - `''Coach Hale''{{'s}}` is «Coach Hale's»), keeps `nowrap` / `small`,
# drops every other template, the tables, the files and the reference
# sections. The hunter keeps no reading of its own.
def plain_text(wikitext):
    """Wikitext as the reader sees it: the root's `wikipedia_api.plain_text`
    (headings as `== H ==` lines, lists as `- item`)."""
    return wikipedia_api().plain_text(wikitext or "")


def clean_wikitext(text):
    """`(text, urls)`: the article's prose with every footnote a marker
    (`_mask_refs`) and the lists out - a list item is never one statement."""
    text = re.sub(r"<!--.*?-->", "", text or "", flags=re.S)
    text, urls = _mask_refs(text)
    lines = [ln for ln in plain_text(text).split("\n") if not ln.startswith("- ")]
    return "\n".join(lines), urls


def split_sections(text):
    """`[(heading, level-2 heading, body)]`; the lead is ("Lead", "Lead")."""
    out, top = [], "Lead"
    last, heading = 0, "Lead"
    for m in _HEADING_RE.finditer(text):
        out.append((heading, top, text[last:m.start()]))
        heading = m.group(2).strip()
        if len(m.group(1)) == 2:
            top = heading
        last = m.end()
    out.append((heading, top, text[last:]))
    return out


_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])(?:\x00\d+\x01)*\s+(?=[\"'(]?[A-Z0-9])")


def split_sentences(body):
    body = re.sub(r"\s+", " ", body).strip()
    if not body:
        return []
    parts, start = [], 0
    for m in _SENTENCE_SPLIT.finditer(body):
        # the markers that follow the full stop stay with the sentence
        chunk = body[start:m.end()].strip()
        # CF-0737: a full stop after an abbreviation or an initial («Warner
        # Bros. Pictures», «Alejandro G. Iñárritu») is no sentence's end -
        # unless a footnote follows it: a reference closes a sentence.
        if not _MARK_RE.search(m.group(0)) and _sentences.abbreviation_end(chunk):
            continue
        parts.append(chunk)
        start = m.end()
    parts.append(body[start:].strip())
    return [p for p in parts if p]


# CF-0737: the hunter's own refusal on top of the root rule's verdict - a
# fact whose text is a sentence cut short (`_sentences.cut_short`) does not
# pass, whatever `fact_rule.check_candidate` said of it. The root rule reads
# the claim, not the sentence it is cut out of; until it does, the code is
# written here, after the rule's own codes.
CUT_SHORT_CODE = "cut_short"


def refuse_cut_facts(checked, check_key="check"):
    """`checked` (`fact_rule.check_candidates`' list) with every candidate
    whose text is cut short failed under CUT_SHORT_CODE (`check.passes`
    false, the code appended to `check.failures`, the reason in
    `check.cut_short`), the passing ones still first - the rule's order is
    otherwise kept."""
    out = []
    for cand in checked or []:
        check = cand.get(check_key) if isinstance(cand, dict) else None
        why = _sentences.cut_short(cand.get("text")) if isinstance(check, dict) else None
        if why:
            fails = list(check.get("failures") or [])
            if CUT_SHORT_CODE not in fails:
                fails.append(CUT_SHORT_CODE)
            cand = dict(cand)
            cand[check_key] = dict(check, passes=False, failures=fails, cut_short=why)
        out.append(cand)
    return sorted(out, key=lambda c: not ((c.get(check_key) or {}).get("passes")
                                          if isinstance(c, dict) else False))


def kind_of_heading(*headings):
    for heading in headings:
        for kind, rx in HEADING_KINDS:
            if rx.search(heading or ""):
                return kind
    return "other"


def _anchor(heading):
    return urllib.parse.quote(heading.replace(" ", "_"), safe="_()-.:")


def wiki_candidates(key, wikitext, fact_rule, sources, limit=WIKI_MAX):
    """Candidates out of an article's wikitext, in order of preference.
    `sources` is the channel's fact-sources list; its `kinds` order breaks
    ties between kinds (CF-0439, CF-0627). A sentence's `primary_url` is its
    first tier-1 ref off `do_not_take`, else its first ref off Wikipedia; where
    the list does not put Wikipedia itself on tier 1 (Tech, Science), the
    sentences with a tier-1 primary go first before the cut at `limit`
    (CF-0788). An article with no ref on tier 1 is cut as before."""
    order = kind_order(sources, fact_rule)
    text, urls = clean_wikitext(wikitext)
    found = []
    for heading, top, body in split_sections(text):
        if SKIP_HEADING_RE.search(heading) or SKIP_HEADING_RE.search(top):
            continue
        kind = kind_of_heading(heading, top)
        for sentence in split_sentences(body):
            cited = [urls[int(i)] for i in _MARK_RE.findall(sentence)
                     if int(i) < len(urls) and urls[int(i)]]
            clean = re.sub(r"\s+([,.;:])", r"\1", _MARK_RE.sub("", sentence)).strip()
            if not (MIN_CHARS <= len(clean) <= MAX_CHARS):
                continue
            if not fact_rule.has_specifics(clean):
                continue
            # The lead defines the work ("X is a British spy series") - a name
            # in it is not a fact. There a sentence has to carry a number.
            if heading == "Lead" and not re.search(r"\d", clean):
                continue
            cand = {"text": clean, "kind": kind, "source": "Wikipedia",
                    "url": WIKI_READER_URL.format(key=key) + (
                        "" if heading == "Lead" else "#" + _anchor(heading)),
                    "section": heading}
            # CF-0788: the primary is the sentence's first tier-1 ref that is
            # not on `do_not_take` (a vendor's or regulator's page cited after
            # the press); none such - the first ref off Wikipedia, as before.
            off_wiki = [u for u in cited
                        if "wikipedia.org" not in (urllib.parse.urlsplit(u).hostname or "")]
            primary = next((u for u in off_wiki if _tier_one(u, fact_rule, sources)),
                           None)
            cand["_tier_one"] = primary is not None
            primary = primary or (off_wiki[0] if off_wiki else None)
            if primary:
                cand["primary_url"] = primary
            found.append(cand)
    # Round-robin over the kinds: the best sentence of each kind first, then
    # the second of each, so that twelve sentences of one long Development
    # section do not crowd out the one box-office number (measured live on
    # `Slow Hounds`, 2026-09-29: every one of the first 12 was production).
    found.sort(key=lambda c: (order.get(c["kind"], len(order)),
                              not re.search(r"\d", c["text"])))
    seen = {}
    for cand in found:
        cand["_round"] = seen[cand["kind"]] = seen.get(cand["kind"], -1) + 1
    # Within a round a number beats no number; the kind only breaks a tie
    # (CF-0439). The cut at `limit` falls inside a round, and with the kind
    # first a numberless production sentence used to push a reception one
    # with a number out of the list before the rule ever saw it.
    found.sort(key=lambda c: (c["_round"], not re.search(r"\d", c["text"]),
                              order.get(c["kind"], len(order))))
    # CF-0788: before the cut, the sentences whose primary is tier 1 go first
    # (a stable sort: the order above holds within each half). Twelve
    # press-cited sentences used to fill the list and cut the one citing the
    # vendor's own page before the rule ever saw it (`tier2_without_primary`).
    # Only where the article itself is not tier 1: on a channel that puts
    # Wikipedia on tier 1 (example-film) every sentence already stands on it,
    # and the order stays the round-robin over the kinds above.
    if not _tier_one(WIKI_READER_URL.format(key=key), fact_rule, sources):
        found.sort(key=lambda c: not c["_tier_one"])
    for cand in found:
        del cand["_round"], cand["_tier_one"]
    return found[:limit]


def _tier_one(url, fact_rule, sources):
    """True for a URL the channel's list puts on tier 1 and not on `do_not_take`."""
    where = fact_rule.source_of(url, sources)
    return where.get("tier") == 1 and where.get("banned") is None


# --------------------------------------------------------------------------
# the batch's own news: other posts that name the work
# --------------------------------------------------------------------------

def _norm(text):
    flat = (text or "").lower()
    for a, b in (("‘", "'"), ("’", "'"), ("“", '"'), ("”", '"'), ("–", "-"), ("—", "-")):
        flat = flat.replace(a, b)
    return " " + re.sub(r"[^a-z0-9]+", " ", flat).strip() + " "


def names_work(work, entry):
    needle = _norm(work).strip()
    if not needle:
        return False
    if f" {needle} " in _norm(entry.get("title")):
        return True
    return (len(needle) >= MIN_NAME_CHARS_IN_SUMMARY
            and f" {needle} " in _norm(entry.get("summary")))


def news_kind(text):
    for kind, rx in NEWS_KINDS:
        if rx.search(text or ""):
            return kind
    return "other"


def _clean_summary(text):
    text = re.sub(r"<[^>]+>", " ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s*(?:The post .*? appeared first on .*|Read more.*|\[…\]|\[\.\.\.\])$",
                  "", text)
    return text


def news_candidates(work, rss_entries, own_urls, sources, fact_rule, limit=NEWS_MAX,
                    text_feeds=None):
    """Fact candidates out of the batch's other news - only an entry of a feed
    in `text_feeds` (the channel's `read_text` feeds, CF-0638); none given is
    none at all."""
    allowed = set(text_feeds or ())
    found, seen = [], set()
    for entry in rss_entries or []:
        if entry.get("feed_url") not in allowed:
            continue
        link = entry.get("link")
        if not link or link in own_urls or link in seen or not names_work(work, entry):
            continue
        where = fact_rule.source_of(link, sources)
        if where["banned"] or where["tier"] is None:
            continue
        summary = _clean_summary(entry.get("summary"))
        title = (entry.get("title") or "").strip()
        text = summary if len(summary) >= MIN_CHARS else title
        if len(text) > MAX_CHARS:
            cut = text[:MAX_CHARS]
            text = cut[:cut.rfind(". ") + 1] if ". " in cut else cut.rsplit(" ", 1)[0] + "…"
        if not text:
            continue
        outlet = entry.get("feed") or where["id"] or where["host"]
        outlet = re.split(r"\s+[-|–]\s+", str(outlet))[0].strip()
        seen.add(link)
        found.append({"text": text, "kind": news_kind(title + " " + summary),
                      "source": outlet, "url": link,
                      "attribution": f"{outlet} reported",
                      "headline": title or None})
    found.sort(key=lambda c: not re.search(r"\d", c["text"]))
    return found[:limit]


# --------------------------------------------------------------------------
# Wikidata: the work's statements (CF-0637)
# --------------------------------------------------------------------------

_SEASON_TITLE_RE = re.compile(r"^(?P<base>.+?)\s+(?:season|series)\s+\d+$", re.I)
LOOKUPS_ATTR = "trend_hunter_lookups"     # the per-pass memo kept on the client


def wikidata_title(title):
    """The article whose item is looked up: the work's for a season article
    (`X season 2` -> `X`), else the article itself."""
    t = str(title or "").replace("_", " ").strip()
    m = _SEASON_TITLE_RE.match(t)
    return m.group("base").strip() if m else t


def wikidata_counts(client):
    """`(sent, network)` of a Wikidata client - as `requests_of`."""
    if client is None:
        return 0, 0
    sent = int(getattr(client, "request_count", 0) or 0)
    wire = getattr(client, "network", None)
    return sent, (int(wire["requests"]) if isinstance(wire, dict) else sent)


def wikidata_lookup(client, wd, article, properties, year=None):
    """`(pieces, record)` - the statements of `properties` (`{P: kind}`, the
    channel's) of the item whose English sitelink is `article` (the work's,
    `wikidata_title`), as `wikidata_statement` pieces.

    `record` is `{article, item, reason, error, asked, requests, network,
    pieces}`: `item` the Q-id taken (None: `reason` says why), `error` a
    Wikidata that could not be read (`WikidataError`) or a list that does not
    let it be read (the gate's `SourceClosed`) - never raised: Wikidata adds
    to a topic, its absence takes nothing away. `requests` / `network` are
    what this call sent and what went past the cache (<= 3,
    `wikidata_api.MAX_REQUESTS_PER_TOPIC`).

    The answer is kept on the client for the pass (`LOOKUPS_ATTR`): the fact
    search asks first, the support text asks the same item again for nothing
    (`reused`, 0 requests)."""
    title = wikidata_title(article)
    memo = getattr(client, LOOKUPS_ATTR, None)
    if not isinstance(memo, dict):
        memo = {}
        try:
            setattr(client, LOOKUPS_ATTR, memo)
        except AttributeError:
            pass
    key = (wd.norm_title(title), year)
    if key in memo:
        pieces, record = memo[key]
        return ([dict(p) for p in pieces],
                dict(record, requests=0, network=0, reused=True))
    sent0, wire0 = wikidata_counts(client)
    record = {"article": title, "item": None, "reason": None, "error": None, "asked": [],
              "requests": 0, "network": 0, "pieces": 0}
    pieces = []
    try:
        item, reason, asked = wd.resolve_item(client, title, year=year)
        record.update(item=(item or {}).get("id"), reason=reason, asked=asked)
        if item is not None:
            record["revision_id"] = item.get("revision_id")
            pieces = wd.statement_pieces(item, properties)
            if not pieces:
                record["reason"] = (f"{item.get('id')} has no statement of the channel's "
                                    f"properties with a readable value")
    except wd.WikidataError as exc:
        record["reason"] = record["error"] = f"Wikidata could not be read: {exc}"
    except _source_closed() as exc:
        record["reason"] = record["error"] = (f"Wikidata is not a readable outlet of the "
                                              f"channel: {exc}")
    sent1, wire1 = wikidata_counts(client)
    record["requests"], record["network"] = sent1 - sent0, wire1 - wire0
    record["pieces"] = len(pieces)
    memo[key] = ([dict(p) for p in pieces], dict(record))
    return pieces, record


def _source_closed():
    """`source_gate.SourceClosed` - the gate the Wikidata client is handed
    raises it; imported here only when a lookup runs."""
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import source_gate
    return source_gate.SourceClosed


def wikidata_candidates(pieces, sources, fact_rule, wd=None, about_person=False,
                        limit=WIKIDATA_MAX):
    """The pieces as fact candidates (`wikidata_api.candidate_of`): only a
    kind the channel's list names (`kinds`) and only one that passes the rule
    (`fact_rule.check_candidate` - for a topic about a person with its
    stricter half, which Wikidata, not a major outlet, does not pass), at most
    `limit`, the channel's kinds taken in turn so one long cast list does not
    crowd out the release date."""
    wd = wd or wikidata_api()
    kinds = list(fact_rule.kinds_of(sources))
    by_kind = {}
    for piece in pieces or []:
        cand = wd.candidate_of(piece)
        if cand.get("kind") not in kinds:
            continue
        if about_person:
            cand["about_person"] = True
        if not fact_rule.check_candidate(cand, sources)["passes"]:
            continue
        cand["piece_id"] = piece.get("id")
        by_kind.setdefault(cand["kind"], []).append(cand)
    out, round_ = [], 0
    while len(out) < limit and any(len(v) > round_ for v in by_kind.values()):
        for kind in kinds:
            row = by_kind.get(kind) or []
            if len(row) > round_ and len(out) < limit:
                out.append(row[round_])
        round_ += 1
    return out


def wikidata_reader(wikidata):
    """`wikidata` as `search_topic` takes it - a callable `(article, year) ->
    (pieces, record)`, or `(client, module, properties)` - as `(read, wd)`;
    `(None, None)` when not given."""
    if wikidata is None:
        return None, None
    if callable(wikidata):
        return wikidata, getattr(wikidata, "module", None)
    wdc, wd, properties = wikidata

    def read(article, year=None):
        return wikidata_lookup(wdc, wd, article, properties, year=year)
    return read, wd


# --------------------------------------------------------------------------
# one topic
# --------------------------------------------------------------------------

def search_topic(topic, probe_record, rss_entries, own_urls, sources, fact_rule,
                 client=None, text_feeds=None, wikidata=None):
    """Every candidate this stage can find for one topic, and what it asked.

    `text_feeds` are the feeds whose entries may be a news candidate
    (`news_candidates`, CF-0638) - none when not given.

    `wikidata` (CF-0637) is the channel's Wikidata reader - `(client, module,
    properties)` or a callable `(article, year) -> (pieces, record)` - given
    only when the channel's list lets Wikidata be read; None asks it nothing.
    It is asked once the topic's article was read; what it found is in
    `asked` (`source` "wikidata") and its failure nowhere else - not in
    `error`.

    Returns `{"candidates": [...], "asked": [...], "error": str|None,
    "requests": int}`. `error` is set when a source could not be asked - with
    no passing candidate that is `source_unreachable`, and the topic is
    carried. `requests` is how many page requests the article read sent
    through `client` (0 when no article was read; a cache hit counts - the
    pass counts what reached the network, `requests_of`)."""
    ref = topic.get("title_ref") or {}
    start = requests_of(client)[0] if client is not None else 0
    work = ref.get("name")
    candidates, asked, errors = [], [], []
    record = probe_record or {}
    outcome = record.get("outcome")
    article = record.get("article")

    if outcome in fact_rule.UNREACHABLE_STATUSES:
        errors.append(f"wikipedia search: {record.get('detail') or outcome}")
        asked.append({"source": WIKI_SOURCE, "outcome": "unreachable",
                      "detail": record.get("detail")})
    elif outcome in ARTICLE_OUTCOMES and article:
        client = client or default_client()
        try:
            key, wikitext = fetch_wikitext(article, client)
        except Unreachable as exc:
            errors.append(str(exc))
            asked.append({"source": WIKI_SOURCE, "article": article,
                          "outcome": "unreachable", "detail": str(exc)})
        else:
            found = (wiki_candidates(key, wikitext or "", fact_rule, sources)
                     if key else [])
            candidates.extend(found)
            asked.append({"source": WIKI_SOURCE, "article": article,
                          "outcome": "ok" if key else "no_article",
                          "candidates": len(found)})
            read, wd = wikidata_reader(wikidata)
            if read is not None and key:
                # CF-0637: the work's statements on Wikidata - added to,
                # never instead of; a failure is written here and nowhere else
                pieces, wrec = read(key, ref.get("year"))
                found = wikidata_candidates(pieces, sources, fact_rule, wd=wd,
                                            about_person=is_about_person(ref))
                candidates.extend(found)
                asked.append({"source": WIKIDATA_SOURCE, "article": wrec.get("article"),
                              "item": wrec.get("item"),
                              "outcome": ("unreachable" if wrec.get("error")
                                          else "ok" if wrec.get("item") else "no_item"),
                              "detail": wrec.get("reason"),
                              "statements": wrec.get("pieces") or 0,
                              "candidates": len(found),
                              "requests": wrec.get("requests") or 0,
                              "network": wrec.get("network") or 0})
    else:
        asked.append({"source": WIKI_SOURCE, "article": article,
                      "outcome": outcome or "not_asked",
                      "detail": "no article of the topic's own to read"})

    if rss_entries is None:
        asked.append({"source": NEWS_SOURCE, "outcome": "not_given",
                      "detail": "no --rss output was handed to the stage"})
    else:
        found = news_candidates(work, rss_entries, own_urls, sources, fact_rule,
                                text_feeds=text_feeds)
        candidates.extend(found)
        allowed = set(text_feeds or ())
        asked.append({"source": NEWS_SOURCE, "outcome": "ok",
                      "entries": len(rss_entries), "candidates": len(found),
                      # CF-0638: how many entries came from a feed whose
                      # text may be a fact - 0 for a headline_only channel
                      "read_text_entries": sum(1 for e in rss_entries
                                               if e.get("feed_url") in allowed)})
    if is_about_person(ref):
        # CF-0439: the story is about the person, so every fact found for it
        # is a claim about a real person - held to the rule's stricter half
        # (a major outlet, never a rumour, "X said that..."), whatever
        # section or post it came from. Nothing here relaxes that.
        for cand in candidates:
            cand["about_person"] = True
    # The order the rule's own ranking keeps for its ties (`fact_rule._rank`
    # is a stable sort on passes, tier, a number): an attributed claim ("X
    # reported...") before an unattributed one, and only then the order
    # found in - a section's kind among them (CF-0439: the kind of a fact
    # never makes it better than a fact with more to it).
    candidates.sort(key=lambda c: not fact_rule.is_attributed(c))
    spent = requests_of(client)[0] - start if client is not None else 0
    return {"candidates": candidates, "asked": asked,
            "error": "; ".join(errors) or None, "requests": spent}


def is_about_person(ref):
    """A person-topic whose subject is the person, not a work (CF-0439):
    `kind: person` and `name` equal to `person`, case and punctuation aside."""
    ref = ref or {}
    if str(ref.get("kind") or "").strip().lower() != "person":
        return False
    person = _norm(ref.get("person")).strip()
    return bool(person) and _norm(ref.get("name")).strip() == person
