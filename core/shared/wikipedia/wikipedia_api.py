#!/usr/bin/env python3
"""CF-0184/CF-0237: the source the script's fact is looked up in - Wikipedia.

**Where it lives (CF-0551, 2026-10-05).** Until 1.8 this file was
`agents/content-researcher/scripts/wikipedia_api.py`. Since CF-0551 the Trend
Hunter reads Wikipedia too (the topic's support text, `support_text[]` in
`01`), and two clients of one source would be two etiquettes, so the client
moved to the factory root's shared layer: `shared/wikipedia/wikipedia_api.py`.
Every user loads this one file - the Content Researcher's
`scripts/wikipedia_api.py` is now a loader that hands this module out under
the same import name, `shared/factrule/story_claims.py` loads it by path, and
the hunter's `scripts/_wikipedia.py` does the same. They all register it in
`sys.modules` under one name (`MODULE_NAME`), so within one process there is
one module object and one `WikipediaError` class to catch. CF-0551 also added
`revision_id` to `article_of` (the `latest.id` of the same answer - CF-0554
needs the revision a text was read from, not only its date) and moved the
disk cache at the transport seam here from `story_claims.py`
(`cached_transport`, `<batch>/work/wikipedia-cache/`). A caller names itself
in the User-Agent (`WikipediaClient(tool_name=...)`); the default is the
researcher's name, as before.

Since CF-0181 a script retells a story and owes it **one concrete fact the
story does not carry** - of any kind since CF-0439 (production, box office,
release, casting, reception, a scandal, news about the people) - and CF-0183
made that fact a required field (`production_fact`) with a gate of its own.
The fact has to come from a source of its own - a fact lifted out of the coverage being retold is the
retelling again - and this module is that source's client.

**Why Wikipedia and nothing else** (the grill of 2026-09-11, Q1 round 4):
a free API with a published etiquette, a free licence, article text with
footnotes to the primary source, and a machine-readable structure. IMDb
Trivia is out - its terms forbid scraping and CF-0114 forbids automated
acquisition from other people's platforms anyway. TMDB is not resurrected
(dropped 2026-08-28: the free tier wants a personal certification with a real
name, phone and address).

**Which of the encyclopedia's APIs** (CF-0237, decided 2026-09-15): the
Wikimedia **Core REST API** on ``api.wikimedia.org``, not the action API on
``en.wikipedia.org/w/api.php``. The reason is not performance: the action API
sits under ``Disallow: /w/`` in ``en.wikipedia.org/robots.txt``, and rather
than write our own reading of somebody else's file into a decision, the client
moved to the host where that file does not exist at all (``GET
api.wikimedia.org/robots.txt`` is a 301 to the Wikimedia APIs documentation,
checked 2026-09-15). The payload is the same wikitext, so **the transport
moved and nothing else did**: the section tree, the candidate rule, the shape
of the result and the empty-result codes are part 1's, untouched.

**What this client does on the network**, in full, because the crawler
position (CF-0045 / CF-0059) is written from it:

* one host, ``https://api.wikimedia.org``, over HTTPS, GET only;
* two endpoints: ``/core/v1/wikipedia/en/search/page`` to find the article and
  ``/core/v1/wikipedia/en/page/<title>`` to read its wikitext. Nothing is
  POSTed, no account is used, no page is edited, no HTML page is fetched,
  nothing is crawled by following links;
* at most ``MAX_REQUESTS_PER_TITLE`` (3) requests per title: one search and at
  most ``MAX_ARTICLE_READS`` (2) page requests - and a redirect hop spends one
  of those two, it is not a free extra;
* a User-Agent that names the tool and carries a contact, as the Wikimedia
  User-Agent policy requires - never a browser's, never a forged one;
* serial requests only, with a floor of ``MIN_INTERVAL_SECONDS`` (1 s) between
  two requests from one client;
* ``Retry-After`` honoured on 429 and 503, at most ``MAX_RETRIES`` times.

**No `maxlag`.** The action API's back-off handle is a parameter of
``api.php``; the Core REST endpoints do not take it, and a client that sent it
anyway would be pretending to a courtesy it is not performing. So it is gone,
and the load this client puts on the source is held down by the two things
that do work here: the serial floor between requests and the ceiling per
title, plus honouring the server's own ``Retry-After`` when it asks for room.

**Licence and URL come with the data.** The page answer carries ``license``
(CC BY-SA 4.0, url and title) and ``key`` - the exact URL form of the title -
so the human article URL the proofs layer shows (CF-0071) is built from what
the API returned, not guessed from the string we searched for. (``html_url``,
which the ``/bare`` variant of the endpoint carries, is *not* that URL: it
points at ``/w/rest.php/v1/page/<key>/html``, the REST rendering, which is not
a page a person is sent to. It is deliberately not used.)

**Contact in the User-Agent.** The policy wants a way to reach the operator.
Set ``WIKIPEDIA_CONTACT`` (an email or a URL) and it goes into the header; the
default is this project's public repository, which is a valid contact under
the policy. Nothing else about the operator is ever sent.

Errors, and what is *not* one: a title with no article, or an article with no
section a fact can come out of, is an **empty result**, not an exception - CF-0185's
refusal rule reads that emptiness, and a client that raised instead would
break it. A network failure, a 4xx/5xx that survives the retries, or a
malformed answer **is** an exception (`WikipediaError`): a run that could not
reach the source must not look like a title that has no facts.

Usage as a library::

    from wikipedia_api import WikipediaClient, resolve_article
    client = WikipediaClient()
    article = resolve_article(client, "Bunker", year=2026)

Stdlib only: this repository has no venv and this module is imported by the
gate scripts' neighbours, so it must run on a bare python3.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request

# The Core REST API of the Wikimedia APIs gateway, English Wikipedia.
API_BASE = "https://api.wikimedia.org/core/v1/wikipedia/en"
PAGE_PATH = "/page"                     # + /<title> -> {source, license, key}
SEARCH_PATH = "/search/page"            # ?q=&limit= -> {pages: [...]}
# Where a person is sent - the article itself, not an API answer.
ARTICLE_BASE = "https://en.wikipedia.org/wiki/"
# The outlet's shown name, for the document record a proof shows (CF-0241).
# It lives here rather than in production_facts.py because this module is the
# one that knows which site it is talking to.
SITE_NAME = "Wikipedia"

# The Wikimedia User-Agent policy: identify the tool and give a contact. The
# version is this file's contract version, not the repo's.
TOOL_NAME = "shorts-content-factory-content-researcher"
TOOL_VERSION = "2.0"
DEFAULT_CONTACT = "https://example.com/shorts-content-factory"
CONTACT_ENV = "WIKIPEDIA_CONTACT"

# API etiquette. The Core REST endpoints take no `maxlag` (that is an
# `api.php` parameter), so what holds the load down is serial requests a
# second apart, the ceiling per title, and the server's own Retry-After.
MIN_INTERVAL_SECONDS = 1.0
DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5
RETRY_STATUS = (429, 500, 502, 503, 504)

# The ceiling per title, declared rather than implied: one search plus at most
# two page requests. A title that needs more is reported unresolved.
MAX_REQUESTS_PER_TITLE = 3
SEARCH_LIMIT = 5
MAX_ARTICLE_READS = 2

# CF-0263: the one place a topic may cost more than one title's worth of
# requests. A spin-off with no article of its own falls back to the parent
# work **named in the topic** (`Rennick: Quill` -> `Rennick`), and a parent
# is a second title, not a free extra: it is searched and read exactly like
# the first one. So the ceiling per *topic* is two titles' worth and is
# declared here rather than left to emerge - one fallback, never a chain.
MAX_TITLES_PER_TOPIC = 2
MAX_REQUESTS_PER_TOPIC = MAX_REQUESTS_PER_TITLE * MAX_TITLES_PER_TOPIC

# Titles that carry the name but are never the film or the series.
DISAMBIGUATION_NOISE = ("disambiguation", "soundtrack", "album", "novel",
                        "video game", "comics", "character", "franchise",
                        "book", "song", "band", "play")
# Parentheticals that say "this is the title itself".
TITLE_KIND_HINTS = ("film", "movie", "tv series", "television series",
                    "miniseries", "series", "season", "tv special")

# -- what kind of work an article is about (CF-0263) -----------------------
# The lookup used to hand back whatever article the search resolved to, and a
# fact off the wrong article passes every checker downstream: compliance
# judges how concrete a sentence is, not what it is about. So the resolved
# article is now held against what the topic is known to be.
#
# **Which signal, measured 2026-09-17** on the 19 articles this lookup
# resolved to for the grill's title list: the article's own infobox template
# separated every one of them correctly. The fourteen past works came back
# `Infobox television` (Slow Hounds, Widow's Bay, DTF St. Louis, Hacks, The
# Pitt, Coach Hale, Pine Park, Dexter: Resurrection, The Real Housewives of
# New York City, Quill) or `Infobox film` (Spire-Runner: Fresh Dawn,
# Everyday Sorcery 2, The Long Voyage (2026 film), Bunker (2026 film), You Can See
# Everything) - matching their type in 19 cases out of 19 - while the two
# wrong resolutions the grill named declared themselves: `Michael J. Fox` is
# `Infobox person` and `The Michael J. Fox Foundation` is
# `Infobox organization`. The title's disambiguator is the second signal and
# is kept because it carries one thing the infobox does not: `Wren Hollow
# (film series)` is `Infobox film` like any film, and only `(film series)`
# says it is the franchise rather than a work. The first sentence was not
# used - it is prose, and the two signals above already answer.
#
# **Only the kind refuses.** Year and network/studio are accepted, are used
# to aim the search and the ranking, and are reported back - but a mismatch
# on them does not make a `wrong_article`, because nothing has been measured
# that says it should: a topic's year is the year of the news and an
# article's is the year of release, and a network on Wikipedia is a wikilink
# in whatever form the editor left it (`Example Network`, `Example Max`, `Max`). Refusing on
# an unmeasured signal would lose topics that have a fact.
INFOBOX_RE = re.compile(r"\{\{\s*[Ii]nfobox[\s_]+([^\n|}]+)")

# Infobox template name (lowercased, first word(s)) -> what it is about.
# Prefix match, longest-looking first; an unknown template is unknown, never
# a mismatch.
INFOBOX_KINDS = (
    ("television", "tv_series"),
    ("tv ", "tv_series"),
    ("film", "film"),
    ("person", "person"),
    ("biography", "person"),
    ("musical artist", "person"),
    ("organization", "organization"),
    ("organisation", "organization"),
    ("company", "organization"),
    ("charity", "organization"),
    ("video game", "video_game"),
    ("book", "book"),
    ("novel", "book"),
    ("album", "album"),
    ("song", "album"),
)

# The disambiguator in the title -> what it is about. Order matters: `film
# series` is a franchise and not a film, and `TV series` is a series and not
# the bare word `series`.
TITLE_KINDS = (
    (re.compile(r"\b(?:film|movie|media|book|novel)\s+(?:series|franchise)\b"
                r"|\bfranchise\b", re.I), "franchise"),
    (re.compile(r"\b(?:tv|television)\s+(?:series|programme|program|show|special|"
                r"miniseries|film)\b|\bminiseries\b|\bweb series\b|\bseason\s*\d",
                re.I), "tv_series"),
    (re.compile(r"\bfilm\b|\bmovie\b", re.I), "film"),
    (re.compile(r"\bnovel\b|\bbook\b", re.I), "book"),
    (re.compile(r"\balbum\b|\bsong\b", re.I), "album"),
    (re.compile(r"\bvideo game\b", re.I), "video_game"),
    (re.compile(r"\bcharacter\b", re.I), "character"),
)

# The topic types this lookup is asked about, and the article kinds each one
# accepts. A type outside this table verifies nothing - a caller that knows
# something we have no reading for must not have its topic refused for it.
WORK_TYPES = {
    "tv_series": ("tv_series",),
    "tv_show": ("tv_series",),
    "television": ("tv_series",),
    "series": ("tv_series",),
    "miniseries": ("tv_series",),
    "film": ("film",),
    "movie": ("film",),
}

# Infobox fields that name who made or aired the thing - reported beside the
# verdict so an operator can see what the article says, never a refusal.
INFOBOX_NETWORK_FIELDS = ("network", "channel", "studio", "company",
                          "production_company", "distributor", "label")


class WikipediaError(RuntimeError):
    """The source could not be read. Never raised for 'no article' or 'no
    section to read' - those are empty results, see the module docstring."""


class HttpResponse:
    """What a transport hands back. Small on purpose: the retry logic needs a
    status and a body, and the tests need to hand both over without a socket."""

    def __init__(self, status, body, headers=None):
        self.status = int(status)
        self.body = body
        self.headers = headers or {}

    def header(self, name, default=None):
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default


def contact():
    """The contact string that goes into the User-Agent."""
    configured = (os.environ.get(CONTACT_ENV) or "").strip()
    return configured or DEFAULT_CONTACT


def user_agent(tool_name=None):
    """`Tool/Version (contact) runtime` - the shape the Wikimedia policy asks
    for. Honest: it names this tool, it is not a browser's and not one of the
    named AI crawlers. `tool_name` is the calling stage's own name (CF-0551:
    the hunter says it is the hunter); the default is the researcher's."""
    return (f"{tool_name or TOOL_NAME}/{TOOL_VERSION} ({contact()}) "
            f"python-urllib/{sys.version_info.major}.{sys.version_info.minor}")


def page_path(title):
    """The path of one article's endpoint. The title goes into the path, so it
    is escaped whole - a colon or a slash in a title is part of the title, not
    of the URL's structure."""
    key = title.strip().replace(" ", "_")
    return f"{PAGE_PATH}/{urllib.parse.quote(key, safe='')}"


def urllib_transport(url, headers, timeout=DEFAULT_TIMEOUT):
    """The real network. Returns an HttpResponse for any HTTP status - the
    retry logic upstairs decides what a 429 means - and raises WikipediaError
    only when there was no answer at all."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return HttpResponse(response.status, body, dict(response.headers))
    except urllib.error.HTTPError as error:      # an answer, just not a 200
        body = error.read().decode("utf-8", "replace") if error.fp else ""
        return HttpResponse(error.code, body, dict(error.headers or {}))
    except (urllib.error.URLError, OSError) as error:
        raise WikipediaError(f"could not reach {url}: {error}") from error


class WikipediaClient:
    """Serial, rate-limited, retrying GET client for the Core REST API.

    `transport` is injectable for one reason: the test suite must never touch
    the network (a test that goes out is a defect, not an acceptance), so the
    tests hand in recorded answers through this seam. Its signature is
    ``(url, headers, timeout) -> HttpResponse``.
    """

    def __init__(self, transport=None, api_base=API_BASE,
                 min_interval=MIN_INTERVAL_SECONDS, timeout=DEFAULT_TIMEOUT,
                 max_retries=MAX_RETRIES, sleep=time.sleep, clock=time.monotonic,
                 tool_name=None):
        self.transport = transport or urllib_transport
        self.tool_name = tool_name
        self.api_base = api_base.rstrip("/")
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._last_request_at = None
        self.request_count = 0
        self.waited_seconds = 0.0

    # -- the etiquette ----------------------------------------------------
    def _respect_interval(self):
        if self._last_request_at is None:
            return
        elapsed = self._clock() - self._last_request_at
        remaining = self.min_interval - elapsed
        if remaining > 0:
            self.waited_seconds += remaining
            self._sleep(remaining)

    def _retry_delay(self, response, attempt):
        after = response.header("Retry-After")
        if after:
            try:
                return max(0.0, float(str(after).strip()))
            except ValueError:
                pass
        return RETRY_BACKOFF_SECONDS * attempt

    def url(self, path, params=None):
        url = self.api_base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    # -- one call ---------------------------------------------------------
    def fetch(self, path, params=None):
        """One request, with the etiquette and without the retries: waits out
        the interval floor, sends the User-Agent, counts itself. Whatever the
        server answered comes back as it is - `get` decides what it means."""
        url = self.url(path, params)
        headers = {"User-Agent": user_agent(self.tool_name),
                   "Accept": "application/json",
                   "Accept-Encoding": "identity"}
        self._respect_interval()
        response = self.transport(url, headers, self.timeout)
        self._last_request_at = self._clock()
        self.request_count += 1
        return response

    def get(self, path, params=None, missing_ok=False):
        """One API call with the retries. Returns the decoded JSON; `None`
        when the answer was a 404 and the caller said a missing thing is an
        empty result. Anything else that is not a 200 raises."""
        last_problem = None
        for attempt in range(1, self.max_retries + 1):
            response = self.fetch(path, params)
            if response.status == 200:
                try:
                    return json.loads(response.body)
                except ValueError as error:
                    raise WikipediaError(
                        f"the API answered something that is not JSON: {error}")
            if response.status == 404 and missing_ok:
                return None
            if response.status in RETRY_STATUS:
                last_problem = f"HTTP {response.status}"
            else:
                raise WikipediaError(
                    f"HTTP {response.status} from {self.url(path, params)}"
                    f"{_rest_error(response.body)}")
            if attempt < self.max_retries:
                self._sleep(self._retry_delay(response, attempt))
        raise WikipediaError(
            f"gave up after {self.max_retries} attempts ({last_problem}) "
            f"on {self.url(path, params)}")

    # -- the two endpoints ------------------------------------------------
    def search(self, query, limit=SEARCH_LIMIT):
        """Article titles matching `query`, best first. [] when nothing
        matches - not an error."""
        payload = self.get(SEARCH_PATH, {"q": query, "limit": limit})
        pages = payload.get("pages") or []
        return [page["title"] for page in pages if page.get("title")]

    def page(self, title, follow_redirect=True):
        """`{title, key, pageid, wikitext, url, license, requests}` for one
        article, or None when there is no such page (a missing article is an
        empty result, not an error).

        The endpoint answers with the wikitext in `source` - the heading tree
        is read out of it by `production_facts.split_sections`, so no rendered
        HTML and no separate table-of-contents call are needed.

        A redirect is not followed by the endpoint (it answers with the
        redirect page itself and a `redirect_target`), so it is followed here,
        once, and the hop is counted in `requests`: the ceiling per title is a
        ceiling on requests, not on articles.
        """
        payload = self.get(page_path(title), missing_ok=True)
        if payload is None:
            return None
        spent = 1
        target = _redirect_target(payload)
        if target and follow_redirect:
            hop = self.get(page_path(target), missing_ok=True)
            spent += 1
            if hop is not None:
                payload = hop
        return article_of(payload, spent)


def article_of(payload, requests=1):
    """The page answer as this module hands it on - the shape the rest of the
    pipeline reads, and the seam the tests build an article through. `url` is built from the
    API's own `key`, and the licence is the one the answer declared.

    `revised_at` is `latest.timestamp` of the same answer (CF-0241) - the
    revision the wikitext below was read from. It costs no second request:
    the endpoint sends it in the body this module already parses for the
    section text, and until CF-0241 it was simply dropped. None when the
    answer carried none - an absent date is written as null, never as an
    empty string, because a proof showing a blank date is worse than one that
    says it has none.

    `revision_id` is `latest.id` of the same answer (CF-0551) - the revision
    itself, so a later stage can ask whether the text it was handed still
    stands (CF-0554). None when the answer carried none.

    `page_type` is the answer's own `type` (CF-0828) - the REST endpoints
    that send one say `disambiguation` for a page that lists meanings - and
    `disambiguation` is true when either that field or the page's own
    template (`_DISAMBIGUATION_PAGE`) says the page is one. Until CF-0828 the
    field was dropped and a bare name (`Amazon`, `Mercury`) was read as an
    article and came back `no_section`."""
    key = payload.get("key") or (payload.get("title") or "").replace(" ", "_")
    latest = payload.get("latest")
    wikitext = payload.get("source") or ""
    page_type = payload.get("type") or None
    return {"title": payload.get("title") or key.replace("_", " "),
            "key": key,
            "pageid": payload.get("id"),
            "wikitext": wikitext,
            "page_type": page_type,
            "disambiguation": (page_type == PAGE_TYPE_DISAMBIGUATION
                               or bool(_DISAMBIGUATION_PAGE.search(wikitext))),
            "url": article_url(key),
            "license": payload.get("license") or None,
            "revised_at": (latest or {}).get("timestamp") or None,
            "revision_id": (latest or {}).get("id") or None,
            "requests": requests}


def document_of(article, heading=None):
    """The document a proof would show for this article, in the shape the
    proof layer names its source with (inserts/proof.json script_contract ->
    script_shape.proofs[].source, minus `handle`, which belongs to a post).

    CF-0241: the proof layer has to put the publication, the date and the URL
    on screen, and before this the fact carried the URL alone. `published_at`
    is the revision date rather than a publication date, because a reference
    work does not have one and the date the viewer is owed is the one the
    text on screen was current at. Every field is None rather than "" when
    the answer did not carry it.
    """
    url = article.get("url") or None
    return {"url": anchored(url, heading) if (url and heading) else url,
            "publication": SITE_NAME,
            "title": article.get("title") or None,
            "published_at": article.get("revised_at") or None}


def _redirect_target(payload):
    """The title a redirect page points at, out of `redirect_target`
    (`/w/rest.php/v1/page/Soprano?redirect=no`), or None."""
    target = payload.get("redirect_target")
    if not isinstance(target, str) or not target:
        return None
    path = urllib.parse.urlparse(target).path
    tail = path.rsplit("/page/", 1)[-1].rsplit("/", 1)[-1]
    return urllib.parse.unquote(tail) or None


def _rest_error(body):
    """The REST error message, when the body carried one - so a refusal says
    what the source said and not only its number."""
    try:
        payload = json.loads(body or "")
    except ValueError:
        return ""
    if not isinstance(payload, dict):
        return ""
    said = ((payload.get("messageTranslations") or {}).get("en")
            or payload.get("errorKey") or payload.get("message"))
    return f": {said}" if said else ""


def article_url(title, anchor=None):
    """The human URL of an article - what the fact is shown with on screen."""
    url = ARTICLE_BASE + urllib.parse.quote(title.replace(" ", "_"), safe="/:()',!$&+;=@")
    if anchor:
        url += "#" + section_anchor(anchor)
    return url


def anchored(url, heading):
    """An article URL with a section anchor on it. The URL comes from the API
    answer's `key`, so this never re-guesses the title's URL form."""
    return f"{url}#{section_anchor(heading)}" if heading else url


def section_anchor(heading):
    """MediaWiki's anchor for a heading - spaces to underscores. Good enough
    for the plain headings (Production, Box office, Release);
    the fancier escaping only matters for headings with punctuation."""
    return urllib.parse.quote(re.sub(r"\s+", "_", heading.strip()),
                              safe="_-.()'!$&+;=@:")


# -- finding the right article --------------------------------------------
def _parenthetical(title):
    found = re.search(r"\(([^)]*)\)\s*$", title)
    return found.group(1).lower() if found else ""


def bare_title(title):
    """An article title reduced to the name of the work: its disambiguator
    off, a leading article off, case and spacing flattened. `Bunker (2026
    film)` and `The Bunker` both come back `bunker`; `The Michael J. Fox Show`
    comes back `michael j. fox show`, which is not `michael j. fox`."""
    text = re.sub(r"\s*\([^)]*\)\s*$", "", (title or "").strip())
    text = re.sub(r"^(?:the|a|an)\s+", "", text.strip(), flags=re.I)
    return re.sub(r"\s+", " ", text).strip().lower()


def title_kind(title):
    """What the title's own disambiguator says this article is about, or None
    when it carries no disambiguator we can read. `Wren Hollow (film series)`
    is a `franchise`, `Rennick (TV series)` a `tv_series`."""
    inside = _parenthetical(title or "")
    if not inside:
        return None
    for pattern, kind in TITLE_KINDS:
        if pattern.search(inside):
            return kind
    return None


def infobox_name(wikitext):
    """The name of the article's first infobox template, lowercased - the
    article's own word for what it is. None when it has no infobox."""
    match = INFOBOX_RE.search(wikitext or "")
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group(1)).strip().strip("|").lower()
    return name or None


def infobox_kind(wikitext):
    """What the first infobox says the article is about, or None for a
    template we have no reading for. Unknown is never a mismatch."""
    name = infobox_name(wikitext)
    if not name:
        return None
    for prefix, kind in INFOBOX_KINDS:
        if name.startswith(prefix):
            return kind
    return None


def _infobox_body(wikitext):
    """The text of the first infobox template, braces balanced."""
    match = INFOBOX_RE.search(wikitext or "")
    if not match:
        return ""
    start = match.start()
    depth, index = 0, start
    while index < len(wikitext):
        if wikitext.startswith("{{", index):
            depth += 1
            index += 2
        elif wikitext.startswith("}}", index):
            depth -= 1
            index += 2
            if depth == 0:
                return wikitext[start:index]
        else:
            index += 1
    return wikitext[start:start + 4000]


def _field_values(body, field):
    """Every value the infobox gives `field`, cut at the next field rather
    than at the next `|`: a value is routinely a `[[link|shown name]]` or a
    `{{Plainlist|...}}`, and both carry pipes of their own."""
    values = []
    for match in re.finditer(r"\|\s*" + field + r"\s*=", body, re.I):
        index, depth, start = match.end(), 0, match.end()
        while index < len(body):
            if body.startswith(("[[", "{{"), index):
                depth += 1
                index += 2
                continue
            if body.startswith(("]]", "}}"), index):
                depth -= 1
                index += 2
                if depth < 0:                 # the end of the infobox itself
                    break
                continue
            if depth == 0 and body[index] == "|":
                break
            index += 1
        values.append(body[start:index])
    return values


def infobox_networks(wikitext):
    """Who the infobox says made or aired it - the values of its network,
    studio and company fields, as plain strings. Reported beside a verdict,
    never used to refuse one (see the note above the tables)."""
    body = _infobox_body(wikitext)
    found = []
    for field in INFOBOX_NETWORK_FIELDS:
        for value in _field_values(body, field):
            # A footnote in a network field is a whole citation template with
            # commas and pipes in it, and a piece of one is not a broadcaster.
            value = re.sub(r"<ref[^>]*/>", " ", value, flags=re.I)
            value = re.sub(r"<ref[^>]*>.*?</ref\s*>", " ", value,
                           flags=re.I | re.S)
            value = re.sub(r"\{\{\s*(?:plainlist|ubl|unbulleted list|hlist|"
                           r"flatlist|nowrap)\s*\|?", " ", value, flags=re.I)
            previous = None                   # the rest of the templates, whole
            while previous != value:
                previous = value
                value = re.sub(r"\{\{[^{}]*\}\}", " ", value)
            value = re.sub(r"\[\[(?:[^\]|]*\|)?([^\]|]*)\]\]", r"\1", value)
            value = re.sub(r"<[^>]+>", " ", value)
            for piece in re.split(r"\s*(?:,|\band\b|\*|\n)\s*", value):
                piece = re.sub(r"\s+", " ", piece).strip(" '\"*|")
                if not piece or "{" in piece or "}" in piece or "[" in piece:
                    continue          # a template the field opened, not a name
                if piece.lower() not in {"none", "n/a"}:
                    found.append(piece)
    seen, unique = set(), []
    for item in found:
        if item.lower() not in seen:
            seen.add(item.lower())
            unique.append(item)
    return unique[:6]


def verify_article(article, work_type=None, year=None, network=None):
    """Is this the article about the work the topic is about?

    Returns a record of the check - what was wanted, what the article says it
    is, and `mismatch`: the name of the signal that contradicts the topic, or
    None when nothing does. **`type` is the only signal that can contradict**;
    the year and the network are read and reported so that an operator can
    see them, because nothing measured says they may refuse (see the note
    above `INFOBOX_RE`).

    Silence is not a mismatch: an article with no infobox we can read and no
    disambiguator, or a topic with no type, verifies to None. The refusal
    rule is hard enough already - it may only fire on a signal that says
    *this is something else*, never on one that says nothing.
    """
    wikitext = (article or {}).get("wikitext", "")
    from_title = title_kind((article or {}).get("title", ""))
    from_box = infobox_kind(wikitext)
    check = {
        "wanted": {"type": work_type or None,
                   "year": str(year) if year else None,
                   "network": network or None},
        "found": {"title_kind": from_title, "infobox": infobox_name(wikitext),
                  "infobox_kind": from_box,
                  "networks": infobox_networks(wikitext)},
        "mismatch": None,
        "detail": None,
    }
    allowed = WORK_TYPES.get((work_type or "").strip().lower())
    if not allowed:
        return check
    for kind, where in ((from_title, "title"), (from_box, "infobox")):
        if kind is not None and kind not in allowed:
            check["mismatch"] = "type"
            check["detail"] = (
                f"the topic is a {work_type}, and the {where} of "
                f"{(article or {}).get('title')!r} says it is a {kind}")
            return check
    return check


def matches_topic(article, work_type=None, year=None, network=None):
    """True when nothing about this article contradicts the topic."""
    return verify_article(article, work_type, year, network)["mismatch"] is None


def rank_candidates(titles, name, year=None, season=None, work_type=None):
    """Order search hits by how likely each is to be *this* title's article.

    The disambiguator carries almost all of the signal: `Bunker (2026 film)`
    beats `Bunker` (a fortification) for a film called Bunker, and
    `Bunker (disambiguation)` is never the answer. Returns (title, score)
    best first; titles that are certainly something else are dropped.

    CF-0263: when the topic says what kind of work it is, a disambiguator
    that agrees is worth more than the search engine's own order and one that
    contradicts sinks the title - measured on `Wren Hollow`, whose search
    answer carries both `(film series)` (first) and `(TV series)` (fourth),
    and where the plain ranking took the franchise for a topic about the Example Network
    series. The contradicting title is sunk rather than dropped, so that a
    topic whose only hits are the wrong kind still resolves to one and comes
    back as `wrong_article` naming it, instead of as a bare `no_article`.
    """
    wanted = name.strip().lower()
    allowed = WORK_TYPES.get((work_type or "").strip().lower())
    ranked = []
    for position, title in enumerate(titles):
        low = title.strip().lower()
        inside = _parenthetical(title)
        if any(noise in inside for noise in DISAMBIGUATION_NOISE):
            continue
        if low != wanted and not low.startswith(wanted) and wanted not in low:
            continue
        score = 0.0
        if low == wanted:
            score += 2
        if any(hint in inside for hint in TITLE_KIND_HINTS):
            score += 3
        if year and str(year) in inside:
            score += 4
        if season and f"season {season}" in low:
            score += 2
        if allowed:
            kind = title_kind(title)
            if kind is not None:
                score += 4 if kind in allowed else -10
        score -= position * 0.1          # the search engine's own order, faintly
        ranked.append((title, score))
    # CF-0263: when the search answer holds articles named after the work
    # itself, the ones merely *containing* its name are a different work and
    # are not read at all. `Michael J. Fox` is a person, and the two requests
    # this module is allowed to spend used to go on to `The Michael J. Fox
    # Show` and `The Michael J. Fox Foundation` - neighbours of the name, not
    # the thing asked about. Measured: all fourteen works of the 2026-09-17
    # list resolved to an article named after them, bare or disambiguated, so
    # this narrowing costs none of them; when nothing is named after the work
    # nothing is dropped and the ranking is CF-0184's as it was.
    named = [pair for pair in ranked if bare_title(pair[0]) == bare_title(name)]
    if named:
        ranked = named
    ranked.sort(key=lambda pair: -pair[1])
    return ranked


def search_query(name, year=None, season=None):
    """What we ask the search for. The year and the word `film` are hints, not
    filters - the search treats them as terms, and `rank_candidates` does the
    real choosing."""
    parts = [name]
    if year:
        parts.append(str(year))
    if season:
        parts.append(f"season {season}")
    return " ".join(parts)


# A disambiguation page says so in a template of its own - `{{Disambiguation}}`
# and its short names, and the kinds of it Wikipedia keeps for names and
# places (`{{Human name disambiguation}}`, `{{Place name disambiguation}}`).
# `{{Disambiguation needed}}` is an inline tag in an ordinary article and does
# not match: the template's name has to end right after the word.
_DISAMBIGUATION_PAGE = re.compile(
    r"\{\{\s*(?:(?:human|place|given)\s+name\s+)?"
    r"(?:disambiguation|disambig|dab|hndis|geodis)\s*[|}]", re.I)
# CF-0828: the REST `type` of such a page, and the sub-reason a `no_article`
# carries when every candidate read was one.
PAGE_TYPE_DISAMBIGUATION = "disambiguation"
NO_ARTICLE_DISAMBIGUATION = "disambiguation"


def is_disambiguation(article):
    """CF-0828: is this page a list of meanings rather than an article? True
    when `article_of` marked it, when its `page_type` says so (an article
    built by hand), or when its wikitext carries the template."""
    if not article:
        return False
    return bool(article.get("disambiguation")
                or article.get("page_type") == PAGE_TYPE_DISAMBIGUATION
                or _DISAMBIGUATION_PAGE.search(article.get("wikitext") or ""))


def _title_key(title):
    """A title as MediaWiki compares two: underscores are spaces, the first
    letter's case does not count."""
    text = re.sub(r"\s+", " ", (title or "").replace("_", " ")).strip()
    return text[:1].upper() + text[1:]


def redirect_article(client, name, work_type=None, skipped=None):
    """CF-0790: the article Wikipedia's own redirect of `name` points at, or
    None.

    The ranking (`rank_candidates`) keeps only the hits whose title carries
    the topic's name - right for a film (`Bunker (2026 film)`), wrong for a
    science or tech topic named the way the news names it. Batch
    ExampleScience 2026-10-17T0817Z lost `Comet 67P` and `negative leap
    second` as `no_article` although the search's first hit was the article
    (`67P/Churyumov-Gerasimenko`, `Leap second`): neither title carries the
    name, so both were dropped. Wikipedia's editors keep a redirect from
    such a name to its article (`Comet 67P`, `Negative leap second`), and a
    redirect is their statement that the name *is* that article - not a guess
    off a search's order. So when nothing ranks, the name itself is asked
    as a page (`client.page` follows the redirect: two requests, inside
    `MAX_REQUESTS_PER_TITLE` beside the search) and its target is taken -
    only a redirect: a page that answers under the name itself is not one
    the search missed, and a target that is a disambiguation (or another
    `DISAMBIGUATION_NOISE` title) is no article of the topic.

    A screen work (`work_type` in `WORK_TYPES`: film, series) is not asked:
    its ranking and its parent fallback (`production_facts`, CF-0263) are
    measured as they are, and a film's name redirecting to its franchise is
    the parent hop's job, not this one's.

    `skipped` (CF-0828), when a list is passed, gets a disambiguation target
    (`{"title", "reason": "disambiguation"}`), so the caller can say why the
    name came back without an article."""
    if (work_type or "").strip().lower() in WORK_TYPES:
        return None
    title = _title_key(name)
    if not title:
        return None
    article = client.page(title)
    if article is None:
        return None
    if _title_key(article.get("title")) == title:
        return None          # the name's own page, or a redirect left unfollowed
    if is_disambiguation(article):
        if skipped is not None:
            skipped.append({"title": article.get("title"),
                            "reason": NO_ARTICLE_DISAMBIGUATION})
        return None
    if any(noise in _parenthetical(article.get("title") or "")
           for noise in DISAMBIGUATION_NOISE):
        return None
    return article


def resolve_article(client, name, year=None, season=None, accept=None,
                    max_reads=MAX_ARTICLE_READS, work_type=None, seen=None,
                    skipped=None):
    """The article for a title, or None when there is no plausible one.

    `accept(article)` - optional - lets the caller say "this one has what I
    came for" (since CF-0439: it is about the work and has a section a fact
    of any kind can come out of - not a Production section in particular,
    which is `production_facts.has_fact_section`); when it says no, the
    next-best candidate
    is read, up to `max_reads` **page requests** (a redirect hop is one of
    them). The last article read is returned even when nobody accepted it, so
    the caller can report *why* it is empty (no section) rather than only
    *that* it is.

    `work_type` is the topic's kind, which steers the ranking (CF-0263).
    `seen`, when a list is passed, collects every article actually read, in
    rank order - the caller needs them to say which of several emptinesses a
    title ran into, and they cost nothing extra: they are already in hand.

    CF-0790: when the search has hits and none of them carries the name,
    Wikipedia's own redirect of the name is asked (`redirect_article`) - for
    a topic that is not a screen work. A search with no hit at all asks
    nothing more (the search indexes redirects too).

    CF-0828: a disambiguation page (`is_disambiguation`: the REST `type` or
    the page's own template) is not an article. It is not handed to
    `accept`, not put in `seen` and never returned as the last article read -
    the next candidate of the ranking is read instead (the page's request
    still counts against `max_reads`). The bare name of a company or a planet
    (`Amazon`, `Mercury`) is such a page, and until CF-0828 it came back as
    the article and its owner reported `no_section`. `skipped`, when a list
    is passed, collects `{"title", "reason": "disambiguation"}` for every
    such page, so a caller handed None can say `no_article` *because* every
    candidate was one (`NO_ARTICLE_DISAMBIGUATION`).
    """
    titles = client.search(search_query(name, year, season))
    ranked = rank_candidates(titles, name, year, season, work_type=work_type)
    if not ranked:
        if not titles:
            return None          # the search indexes redirects: none is there
        article = redirect_article(client, name, work_type=work_type,
                                   skipped=skipped)
        if article is not None and seen is not None:
            seen.append(article)
        return article
    last = None
    spent = 0
    for title, _score in ranked:
        if spent >= max_reads:
            break
        article = client.page(title)
        spent += article.get("requests", 1) if article else 1
        if article is None:
            continue
        if is_disambiguation(article):
            if skipped is not None:
                skipped.append({"title": article.get("title"),
                                "reason": NO_ARTICLE_DISAMBIGUATION})
            continue
        last = article
        if seen is not None:
            seen.append(article)
        if accept is None or accept(article):
            return article
    return last


# ------------------------------------------------- the cache (CF-0533 / CF-0551)
# Moved here from `shared/factrule/story_claims.py` with the client (CF-0551),
# so the hunter's support text and the researcher's cast check share one cache
# directory per batch and one way of keeping answers. A cached answer older
# than CACHE_MAX_AGE_SECONDS is asked again; None in a call = never expires.
CACHE_REL = os.path.join("work", "wikipedia-cache")
CACHE_MAX_AGE_SECONDS = 7 * 24 * 3600
CACHED_STATUSES = (200, 404)

# The one name every loader registers this file under (CF-0551) - see the
# module docstring.
MODULE_NAME = "factory_wikipedia_api"


def cache_name(url):
    """The file one answer is kept in: readable, and unique by a hash."""
    tail = url.split("/core/v1/wikipedia/", 1)[-1]
    readable = re.sub(r"[^A-Za-z0-9._+-]+", "_", tail)[:100].strip("_")
    return f"{readable}-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}.json"


def cached_transport(cache_dir, transport=None,
                     max_age_seconds=CACHE_MAX_AGE_SECONDS, clock=time.time):
    """A `(url, headers, timeout) -> HttpResponse` transport for
    `WikipediaClient` that serves recorded answers from `cache_dir` and
    records the 200s and 404s it fetches. A stale answer is asked again; when
    asking fails (`WikipediaError`) the stale one is served rather than
    nothing. `transport` defaults to `urllib_transport`."""
    real = transport or urllib_transport
    directory = os.fspath(cache_dir)

    def _transport(url, headers, timeout=DEFAULT_TIMEOUT):
        path = os.path.join(directory, cache_name(url))
        held = None
        if os.path.isfile(path):
            try:
                with open(path, encoding="utf-8") as fh:
                    held = json.load(fh)
            except ValueError:
                held = None
        if held and held.get("url") == url:
            age = clock() - float(held.get("fetched_at_epoch") or 0)
            if max_age_seconds is None or age <= max_age_seconds:
                return HttpResponse(held["status"], held["body"])
        try:
            response = real(url, headers, timeout)
        except WikipediaError:
            if held and held.get("url") == url:
                return HttpResponse(held["status"], held["body"])
            raise
        if response.status in CACHED_STATUSES:
            os.makedirs(directory, exist_ok=True)
            now = clock()
            record = {"url": url, "status": response.status, "body": response.body,
                      "fetched_at_epoch": now,
                      "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))}
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False)
            os.replace(tmp, path)
        return response

    return _transport


def cached_client(cache_dir=None, transport=None, **kw):
    """A client whose network goes through the cache (when given)."""
    if cache_dir:
        transport = cached_transport(cache_dir, transport)
    return WikipediaClient(transport=transport, **kw)


# --------------------------------------------------------------------------
# CF-0673: an article as plain text, with its measured numbers kept
# --------------------------------------------------------------------------
#
# The page a `scale` stand-in is read from (shared/factrule/scale_support.py)
# writes its numbers in templates: the Sun's «{{val|1391400|u=km|fmt=commas}}»,
# the grapefruit's «{{convert|10|to|15|cm|in|0|abbr=on}}». A plain text that
# strips every template loses exactly the number the step looks for, so
# `plain_text` unwraps the number templates into their words in the page's own
# unit (never the converted one) and strips the rest. The hunter's
# `fact_search.plain_text` and the researcher's
# `production_facts.clean_wikitext` read through it already; the words their
# own wrappers used to unwrap first - the possessive (`{{'s}}`, `{{'}}`), the
# non-breaking space (`{{nbsp}}`) and money (`{{US$|N}}`, `{{USD|N}}`) - are
# unwrapped here too, so a wrapper is no longer needed.

PLAIN_DROP_SECTIONS_RE = re.compile(
    r"^(references|notes|footnotes|citations|sources|external links|see also|"
    r"further reading|bibliography)\b", re.I)
PLAIN_TEXT_TEMPLATES = ("nowrap", "nobr", "small", "smaller", "big", "nobold", "noitalic",
                        "abbr", "lang")
CONVERT_RANGE_WORDS = {"to": "to", "-": "to", "–": "to", "—": "to", "&ndash;": "to",
                       "and": "to", "to(-)": "to", "and(-)": "to", "or": "or",
                       "x": "by", "by": "by", "×": "by"}
_E_UNIT_RE = re.compile(r"^e(\d{1,2})(.*)$")
_PLAIN_NUMBER_RE = re.compile(r"^[+-]?\d[\d,]*(?:\.\d+)?$")
_INNER_TEMPLATE_RE = re.compile(r"\{\{([^{}]*)\}\}", re.S)
# The possessive's apostrophe (`{{'s}}`, `{{'}}`) goes through the reading as
# this mark and comes back at the end: written as `'` straight away it would
# join the italics' `''` before it (`''Coach Hale''{{'s}}` -> `'''s`) and go
# with them as markup - «Ted Lassos».
_APOSTROPHE = "\x02"
MONEY_TEMPLATES = {"us$": "$", "usd": "$"}


def _template_params(body):
    """(name, positional, named) of one template body without nested ones."""
    parts = [p.strip() for p in body.split("|")]
    name = parts[0].strip().lower().replace("_", " ")
    positional, named = [], {}
    for p in parts[1:]:
        key, eq, value = p.partition("=")
        if eq and re.match(r"^[A-Za-z][\w ]*$", key.strip()):
            named[key.strip().lower()] = value.strip()
        else:
            positional.append(p)
    return name, positional, named


def _scaled(number, exponent):
    """«1.39» x 10^6 as «1390000»: exact decimal arithmetic, no float noise,
    no thousands commas (the reader of numbers takes both)."""
    import decimal
    try:
        value = decimal.Decimal(number.replace(",", "")) * (decimal.Decimal(10) ** int(exponent))
    except (decimal.InvalidOperation, ValueError):
        return number
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def _with_commas(number):
    whole, dot, frac = number.replace(",", "").partition(".")
    sign = "-" if whole.startswith("-") else ""
    whole = whole.lstrip("+-")
    return sign + f"{int(whole):,}" + (dot + frac if dot else "") if whole.isdigit() else number


def _unit_and_exponent(unit):
    m = _E_UNIT_RE.match(unit or "")
    return (m.group(2), m.group(1)) if m else (unit, None)


def _expand_val(positional, named):
    if not positional or not _PLAIN_NUMBER_RE.match(positional[0]):
        return ""
    number = positional[0]
    if named.get("e"):
        number = _scaled(number, named["e"])
    elif named.get("fmt", "").lower() == "commas":
        number = _with_commas(number)
    unit = named.get("u") or named.get("ul") or ""
    return f"{number} {unit}".strip()


def _expand_convert(positional):
    if not positional or not _PLAIN_NUMBER_RE.match(positional[0]):
        return ""
    numbers, joiner, rest = [positional[0]], None, positional[1:]
    while len(rest) >= 2 and rest[0].lower() in CONVERT_RANGE_WORDS and \
            _PLAIN_NUMBER_RE.match(rest[1]):
        joiner = CONVERT_RANGE_WORDS[rest[0].lower()]
        numbers.append(rest[1])
        rest = rest[2:]
    unit, exponent = _unit_and_exponent(rest[0] if rest else "")
    if exponent:
        numbers = [_scaled(n, exponent) for n in numbers]
    said = f" {joiner} ".join(numbers) if joiner else numbers[0]
    return f"{said} {unit}".strip()


def _expand_template(match):
    body = match.group(1).strip()
    if body in ("'s", "'"):
        return _APOSTROPHE + body[1:]
    name, positional, named = _template_params(match.group(1))
    if name == "nbsp":
        return " "
    if name in MONEY_TEMPLATES:
        return f"{MONEY_TEMPLATES[name]}{positional[0]}" if positional and positional[0] else ""
    if name == "val":
        return _expand_val(positional, named)
    if name in ("convert", "cvt"):
        return _expand_convert(positional)
    if name in PLAIN_TEXT_TEMPLATES and positional:
        return positional[-1] if name == "lang" else positional[0]
    return ""


def _resolve_links(text):
    """[[a|b]] -> b, [[a]] -> a, innermost first; files, images and categories
    go whole once their captions' own links are resolved."""
    link = re.compile(r"\[\[(?!(?:File|Image|Category):)(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]", re.I)
    media = re.compile(r"\[\[(?:File|Image|Category):[^\[\]]*\]\]", re.I)
    for _ in range(10):
        new = media.sub("", link.sub(r"\1", text))
        if new == text:
            break
        text = new
    return text


def _plain_inline(text):
    text = re.sub(r"\[https?://\S+\s+([^\]]*)\]", r"\1", text)
    text = re.sub(r"\[https?://\S+\]", "", text)
    text = re.sub(r"'{2,5}", "", text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = (text.replace("&nbsp;", " ").replace("&ndash;", "–").replace("&mdash;", "—")
            .replace("&minus;", "-").replace("&amp;", "&"))
    text = re.sub(r"&[a-z]+;", " ", text)
    return re.sub(r"[ \t]+", " ", text).strip()


def plain_text(wikitext):
    """An article's wikitext as the reader sees its prose (CF-0673):

    * comments and footnotes (`<ref .../>`, `<ref>...</ref>`) out;
    * `{{val|N|u=UNIT}}` -> «N UNIT» (`e=6` multiplies, `fmt=commas` puts the
      commas in), `{{convert|N|UNIT|...}}` -> «N UNIT», `{{convert|A|to|B|
      UNIT|...}}` (and `-`, `–`, `and`) -> «A to B UNIT» - the page's own
      unit, never the converted one; a unit like `e6km` gives the number in
      full, «1390000 km», so a number reader reads it;
    * the word templates keep their word: `{{'s}}` -> «'s», `{{'}}` -> «'»
      (also right after italics: `''Coach Hale''{{'s}}` -> «Coach Hale's»),
      `{{nbsp}}` -> a space, `{{US$|N}}` / `{{USD|N}}` -> «$N»;
    * `nowrap` / `small` / ... keep their text, every other template goes
      (the infobox, the navboxes, the citations);
    * `[[a|b]]` -> b, files and categories out, tables out;
    * headings kept as `== Heading ==` lines (a quote's section is read from
      them), lists as `- item`, the reference / link sections dropped.
    """
    text = re.sub(r"<!--.*?-->", "", wikitext or "", flags=re.S)
    text = re.sub(r"<ref[^>/]*/\s*>", "", text, flags=re.I)
    text = re.sub(r"<ref[^>]*>.*?</ref\s*>", "", text, flags=re.S | re.I)
    text = re.sub(r"</?(?:onlyinclude|noinclude|includeonly)>", "", text, flags=re.I)
    text = _resolve_links(text)
    for _ in range(20):
        new = _INNER_TEMPLATE_RE.sub(_expand_template, text)
        if new == text:
            break
        text = new
    text = _resolve_links(text)
    out, depth, dropping = [], 0, False
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("{|"):
            depth += 1
            continue
        if depth:
            if stripped.startswith("|}"):
                depth -= 1
            continue
        heading = re.match(r"^(={2,6})\s*(.+?)\s*\1$", stripped)
        if heading:
            title = _plain_inline(heading.group(2))
            level = len(heading.group(1))
            if level == 2:
                dropping = bool(PLAIN_DROP_SECTIONS_RE.match(title))
            if not dropping:
                out.append(f"\n{'=' * level} {title} {'=' * level}")
            continue
        if dropping or not stripped or stripped.startswith("__"):
            continue
        bullet = re.match(r"^[*#:;]+\s*", stripped)
        body = _plain_inline(stripped[bullet.end():] if bullet else stripped)
        if body:
            out.append(("- " + body) if bullet else body)
    return re.sub(r"\n{3,}", "\n\n", "\n".join(out)).strip().replace(_APOSTROPHE, "'")
