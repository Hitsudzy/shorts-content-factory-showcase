#!/usr/bin/env python3
"""CF-0637: the factory's Wikidata client - structured facts as support text.

**Why Wikidata** (the user's decision of 2026-10-08 on CF-0557, Q2). A fact
the viewer can check - a release date, who is in the cast, who directed it,
the studio, the network, an award - is a *statement* on Wikidata: one
property, one value, its qualifiers (a character role, a date, a place), the
item's revision. The data is **CC0** (no attribution owed, so no credit line
in a video's description), read under the Wikimedia User-Agent policy - the
Wikipedia client's etiquette. Wikidata gives no fresh grosses and no plots:
it confirms the structured facts of a topic, it does not tell its news.
The channel's list says it may be read: `channels/example-film/fact-sources.json`,
outlet `wikidata`, `use: read_text`, verdict `allowed`
(`shared/source_policy.py`); its `properties` say which properties the channel
reads and the kind of fact each one is.

**Why a client of its own, beside the Wikipedia one** (`shared/wikipedia/
wikipedia_api.py`). That client speaks the Core REST API of Wikipedia's wikitext
and its whole machinery is about articles (sections, infoboxes, redirects);
the Core REST page of a Wikidata item is the entity's raw JSON - every
language, and the values as bare Q-ids with no names. What makes a statement
readable is the item's RDF in JSON-LD (`Special:EntityData/<Q>.jsonld`): one
answer carries every statement with its qualifiers *and* the English label of
every item a value names (Jason Sudeikis, Apple TV, the award). So this file
keeps the Wikipedia client's shape and etiquette (the same User-Agent policy
and contact variable, the same serial floor, the same cache record) and adds
nothing to that client: two clients of two APIs, one etiquette. A repository
loads this one file by path and registers it under `MODULE_NAME` in
`sys.modules` (the pattern of the hunter's `scripts/_wikipedia.py`); it keeps
no copy.

**What this client does on the network**, in full:

* two hosts over HTTPS, GET only, nothing POSTed, no account, nothing crawled:
  - ``https://api.wikimedia.org/core/v1/wikidata/search/page?q=&limit=`` - the
    Wikidata search of the Wikimedia API gateway (the host the Wikipedia
    client already reads; its robots.txt is a 301 to the API's
    documentation), to find the item of the topic's work;
  - ``https://www.wikidata.org/wiki/Special:EntityData/<Q>.jsonld`` - one
    item. ``www.wikidata.org/robots.txt`` closes ``/w/``, ``/api/`` and
    ``/wiki/Special:`` to every agent and explicitly reopens
    ``/wiki/Special:EntityData/*.`` - the entity data with a format
    extension, the one path read here. The action API (``wbgetentities``),
    the Wikibase REST API (``/w/rest.php``), ``Special:ItemByTitle`` and SPARQL
    (``query.wikidata.org/sparql``, disallowed to ``*``) are not used;
* at most ``MAX_REQUESTS_PER_TOPIC`` (3) requests for one work: one search
  (a second, unfiltered one only when the first found nothing) and at most
  ``MAX_ENTITY_READS`` (2) entity reads, within the three;
* serial requests at least ``MIN_INTERVAL_SECONDS`` (1 s) apart, ``Retry-After``
  honoured on 429 / 5xx at most ``MAX_RETRIES`` times;
* a User-Agent that names the calling stage and carries a contact
  (``WIKIPEDIA_CONTACT``, the Wikimedia policy's), gzip accepted.

**Which item is the topic's.** The hunter knows the topic's English Wikipedia
article (`fact_probe`'s resolved title). The search asks for that title's
bare name among films and television works (``haswbstatement:P31=...``),
ranks the hits by the year and the kind the title names, and an item is
taken only when **its English Wikipedia sitelink is that article** - the
search proposes, the sitelink decides; a wrong item is never read for facts.

**A gate before every request.** `WikidataClient(gate=...)` takes a callable
``gate(url)`` that raises when the URL may not be read; it is called before
each request, a cached answer included. A request to a host that is not
Wikidata's own (the search on ``api.wikimedia.org``) first asks the gate for
``ENTITY_SITE_URL`` too, so the channel's `wikidata` outlet - not the
gateway's `wikipedia` one - decides whether Wikidata is read at all. The
hunter hands in `source_gate.check(url, sources)` with the channel's list.

**Errors, and what is not one.** No item for the title, an item whose
sitelink is another article, a property with no statement: empty results.
A network failure, a status that survives the retries, a body that is not
JSON is a `WikidataError` - a run that could not reach the source must not
look like a work with no facts.

**The cache** (`cached_transport`, `<batch>/work/wikidata-cache/`): one JSON
file per request, ``{url, status, body, fetched_at_epoch, fetched_at}`` - the
Wikipedia and TVmaze caches' record. An answer older than
``CACHE_MAX_AGE_SECONDS`` (24 h - statements change slowly) is asked again and
served stale only when asking fails.

**The piece** (`statement_pieces`): one `wikidata_statement` per statement the
channel reads - the support-text contract of the hunter's `support_text.py`
(`id`, `kind`, `source`, `title`, `url`, `revision_id`, `revised_at`, `text`)
plus the statement itself: ``{entity, entity_label, property,
property_label, value, value_label, value_type, qualifiers, fact_kind,
data_url, fetched_at, license}``. Its id is
``wikidata:<Q>:<P>:<value>``, its `url` the item's page at the property,
its `text` one plain English sentence rendered from the statement
(`sentence`) - what the writer quotes and the claim judge matches. The claim
layer (`shared/factrule/claims.py`, `claim_judge.py`) reads it as a quotable
piece, never as a reveal's second source. `candidate_of` turns a piece into a
fact candidate for `fact_rule.check_candidate` (its URL on www.wikidata.org
is the channel's tier 1 outlet).

Stdlib only.
"""
import datetime as dt
import gzip
import hashlib
import html
import json
import os
import re
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request

SEARCH_BASE = "https://api.wikimedia.org/core/v1/wikidata"
SEARCH_PATH = "/search/page"                       # ?q=&limit= -> {pages: [...]}
SITE_BASE = "https://www.wikidata.org"
SITE_HOST = "www.wikidata.org"
ENTITY_DATA_PATH = "/wiki/Special:EntityData/{id}.jsonld"
ENTITY_PAGE = SITE_BASE + "/wiki/{id}"
ENTITY_SITE_URL = SITE_BASE + "/wiki/"             # what the gate is asked for any Wikidata read
ENTITY_PREFIX = "http://www.wikidata.org/entity/"
ENWIKI = "https://en.wikipedia.org/"
SITE_NAME = "Wikidata"
SOURCE = "wikidata"                                # a piece's `source`
KIND_STATEMENT = "wikidata_statement"              # a piece's `kind`
LICENSE = {"title": "CC0 1.0",
           "url": "https://creativecommons.org/publicdomain/zero/1.0/"}
TERMS_URL = "https://www.wikidata.org/wiki/Wikidata:Licensing"

TOOL_NAME = "shorts-content-factory"
TOOL_VERSION = "2.3"
DEFAULT_CONTACT = "https://example.com/shorts-content-factory"
CONTACT_ENV = "WIKIPEDIA_CONTACT"                  # the Wikimedia policy's contact, one for both clients

MIN_INTERVAL_SECONDS = 1.0
DEFAULT_TIMEOUT = 30
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 5
RETRY_STATUS = (429, 500, 502, 503, 504)

MAX_REQUESTS_PER_TOPIC = 3
MAX_ENTITY_READS = 2
SEARCH_LIMIT = 5

CACHE_REL = os.path.join("work", "wikidata-cache")
CACHE_MAX_AGE_SECONDS = 24 * 3600
CACHED_STATUSES = (200, 404)

# The one name every loader registers this file under - see the docstring.
MODULE_NAME = "factory_wikidata_api"

# `instance of` classes a topic's work is searched among: film, television
# series, miniseries, television program, web series, television film,
# animated film, animated series, anime television series, documentary film,
# reality television, television special. The search proposes; the sitelink
# decides - a class missing here costs the unfiltered second search.
WORK_CLASSES = ("Q11424", "Q5398426", "Q1259759", "Q15416", "Q526877", "Q506240",
                "Q202866", "Q581714", "Q63952888", "Q93204", "Q182415", "Q1261214")

# The properties this client renders, with their English label (the item's
# answer carries the label too; this is the fallback) - the channel's
# `properties` choose among them and give each its kind of fact.
PROPERTY_LABELS = {
    "P577": "publication date", "P580": "start time", "P582": "end time",
    "P161": "cast member", "P57": "director", "P58": "screenwriter",
    "P170": "creator", "P162": "producer", "P86": "composer",
    "P272": "production company", "P750": "distributed by",
    "P449": "original broadcaster", "P166": "award received",
    "P1411": "nominated for", "P2437": "number of seasons",
    "P1113": "number of episodes", "P2142": "box office", "P2130": "cost",
}
# How many statements of one property become pieces (best first).
PER_PROPERTY_MAX = {"P161": 8, "P166": 6, "P1411": 4, "P577": 4}
PER_PROPERTY_DEFAULT = 3
MAX_PIECES = 30

# Qualifiers a sentence uses.
Q_ROLE = ("P453", "P4633")           # character role, name of the character role
Q_PLACE = ("P291", "P3005")          # place of publication, valid in place
Q_WHEN = "P585"                      # point in time
Q_CRITERION = "P1013"                # criterion used

UNIT_ONE = "Q199"
UNIT_SYMBOLS = {"Q4917": "$", "Q25224": "£", "Q4916": "€"}


class WikidataError(RuntimeError):
    """The source could not be read. Never raised for 'no such item' or 'no
    such statement' - those are empty results."""


class HttpResponse:
    """What a transport hands back: a status, a body, the headers, and the
    moment the answer was fetched (a cached answer keeps its own)."""

    def __init__(self, status, body, headers=None, fetched_at=None):
        self.status = int(status)
        self.body = body
        self.headers = headers or {}
        self.fetched_at = fetched_at

    def header(self, name, default=None):
        for key, value in self.headers.items():
            if key.lower() == name.lower():
                return value
        return default


def iso(epoch):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def contact():
    configured = (os.environ.get(CONTACT_ENV) or "").strip()
    return configured or DEFAULT_CONTACT


def user_agent(tool_name=None):
    """`Tool/Version (contact) runtime` - the calling stage names itself."""
    return (f"{tool_name or TOOL_NAME}/{TOOL_VERSION} ({contact()}) "
            f"python-urllib/{sys.version_info.major}.{sys.version_info.minor}")


def _decode(raw, encoding):
    if (encoding or "").lower() == "gzip" or raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def urllib_transport(url, headers, timeout=DEFAULT_TIMEOUT):
    """The real network. An HttpResponse for any HTTP status; WikidataError
    only when there was no answer at all."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = _decode(response.read(), response.headers.get("Content-Encoding"))
            return HttpResponse(response.status, body, dict(response.headers),
                                fetched_at=iso(time.time()))
    except urllib.error.HTTPError as error:
        raw = error.read() if error.fp else b""
        body = _decode(raw, (error.headers or {}).get("Content-Encoding")) if raw else ""
        return HttpResponse(error.code, body, dict(error.headers or {}),
                            fetched_at=iso(time.time()))
    except (urllib.error.URLError, OSError) as error:
        raise WikidataError(f"could not reach {url}: {error}") from error


class WikidataClient:
    """Serial, rate-limited, retrying GET client for Wikidata.

    `transport` - ``(url, headers, timeout) -> HttpResponse`` - is the seam the
    tests hand recorded answers through (a test never goes to the network).
    `gate` - ``gate(url)`` - is called before every request and raises when
    the URL may not be read (the hunter's `source_gate.check`)."""

    def __init__(self, transport=None, search_base=SEARCH_BASE, site_base=SITE_BASE,
                 min_interval=MIN_INTERVAL_SECONDS, timeout=DEFAULT_TIMEOUT,
                 max_retries=MAX_RETRIES, sleep=time.sleep, clock=time.monotonic,
                 tool_name=None, gate=None, wall=time.time):
        self.transport = transport or urllib_transport
        self.search_base = search_base.rstrip("/")
        self.site_base = site_base.rstrip("/")
        self.min_interval = min_interval
        self.timeout = timeout
        self.max_retries = max_retries
        self.tool_name = tool_name
        self.gate = gate
        self._sleep = sleep
        self._clock = clock
        self._wall = wall
        self._last_request_at = None
        self.request_count = 0
        self.waited_seconds = 0.0
        self.last_fetched_at = None

    def _respect_interval(self):
        if self._last_request_at is None:
            return
        remaining = self.min_interval - (self._clock() - self._last_request_at)
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

    def gate_urls(self, url):
        """What the gate is asked before `url`: Wikidata's own site first
        when the request goes to another host (the gateway's search)."""
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        site_host = (urllib.parse.urlsplit(self.site_base).hostname or "").lower()
        return [url] if host == site_host else [self.site_base + "/wiki/", url]

    def fetch(self, url):
        """One request with the gate and the etiquette, without the retries."""
        if self.gate is not None:
            for asked in self.gate_urls(url):
                self.gate(asked)
        headers = {"User-Agent": user_agent(self.tool_name),
                   "Accept": "application/ld+json, application/json",
                   "Accept-Encoding": "gzip"}
        self._respect_interval()
        response = self.transport(url, headers, self.timeout)
        self._last_request_at = self._clock()
        self.request_count += 1
        return response

    def get(self, url, missing_ok=False):
        """The decoded JSON of one call with the retries; None for a 404 when
        `missing_ok`. Sets `last_fetched_at` to the answer's own moment."""
        last_problem = None
        for attempt in range(1, self.max_retries + 1):
            response = self.fetch(url)
            fetched = getattr(response, "fetched_at", None) or iso(self._wall())
            if response.status == 200:
                try:
                    payload = json.loads(response.body)
                except ValueError as error:
                    raise WikidataError(f"{url} answered something that is not JSON: {error}")
                self.last_fetched_at = fetched
                return payload
            if response.status == 404 and missing_ok:
                self.last_fetched_at = fetched
                return None
            if response.status in RETRY_STATUS:
                last_problem = f"HTTP {response.status}"
            else:
                raise WikidataError(f"HTTP {response.status} from {url}")
            if attempt < self.max_retries:
                self._sleep(self._retry_delay(response, attempt))
        raise WikidataError(f"gave up after {self.max_retries} attempts ({last_problem}) on {url}")

    # -- the endpoints ----------------------------------------------------
    def search_url(self, query, limit=SEARCH_LIMIT):
        return (self.search_base + SEARCH_PATH + "?"
                + urllib.parse.urlencode({"q": query, "limit": int(limit)}))

    def entity_url(self, qid):
        return self.site_base + ENTITY_DATA_PATH.format(id=qid)

    def search(self, query, limit=SEARCH_LIMIT):
        """The search's hits, `[{"id": "Q..", "description": ...}]` - items
        only, in the search's order."""
        payload = self.get(self.search_url(query, limit), missing_ok=True) or {}
        out = []
        for page in payload.get("pages") or []:
            key = str((page or {}).get("key") or "")
            if re.fullmatch(r"Q\d+", key):
                out.append({"id": key, "description": plain(page.get("excerpt")
                                                            or page.get("description"))})
        return out

    def entity(self, qid):
        """One item (`entity_of`), or None when Wikidata has no such item."""
        if not re.fullmatch(r"Q\d+", str(qid or "")):
            raise ValueError(f"not an item id: {qid!r}")
        payload = self.get(self.entity_url(qid), missing_ok=True)
        if not payload:
            return None
        return entity_of(payload, qid, self.last_fetched_at)


# --------------------------------------------------------------------------
# reading the item's JSON-LD
# --------------------------------------------------------------------------

_TAG_RE = re.compile(r"<[^>]+>")


def plain(text):
    """A search excerpt as plain text: tags gone, entities decoded."""
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(_TAG_RE.sub("", str(text)))).strip()


def _merge(nodes, node):
    held = nodes.setdefault(node.get("@id"), {})
    for key, value in node.items():
        if key not in held:
            held[key] = value
        elif held[key] != value:
            have = held[key] if isinstance(held[key], list) else [held[key]]
            add = value if isinstance(value, list) else [value]
            held[key] = have + [v for v in add if v not in have]


def _as_list(value):
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _ref(value):
    """An @id reference as a string."""
    if isinstance(value, dict):
        return value.get("@id") or value.get("@value")
    return value


def _literal(value):
    if isinstance(value, dict):
        return value.get("@value")
    return value


LABEL_LANGS = ("en", "mul", "en-gb", "en-us", "en-ca")


def lang_value(value, langs=LABEL_LANGS):
    """The English text of a JSON-LD language map (`[{@language, @value}]`)."""
    found = {}
    for v in _as_list(value):
        if isinstance(v, dict):
            found.setdefault(v.get("@language"), v.get("@value"))
        elif isinstance(v, str):
            found.setdefault(None, v)
    for lang in langs:
        if found.get(lang):
            return found[lang]
    return found.get(None)


def _qid(ref):
    """`wd:Q42` / `http://www.wikidata.org/entity/Q42` -> `Q42`, else None."""
    ref = str(ref or "")
    m = re.fullmatch(r"(?:wd:|" + re.escape(ENTITY_PREFIX) + r")([QP]\d+)", ref)
    return m.group(1) if m else None


def _term_iri(context, key):
    """What a compact key stands for: `P453` -> `pq:P453` (from the context),
    `ps:P161` -> itself."""
    term = (context or {}).get(key)
    if isinstance(term, dict) and term.get("@id"):
        return term["@id"]
    if isinstance(term, str):
        return term
    return key


def _time_text(value):
    m = re.match(r"^\+?(-?\d{1,4})-(\d{2})-(\d{2})", str(value or ""))
    if not m:
        return None
    year, month, day = int(m.group(1)), int(m.group(2)), int(m.group(3))
    return f"{year:04d}-{max(month, 1):02d}-{max(day, 1):02d}" if year > 0 else None


def _value(raw, value_node, labels):
    """One statement or qualifier value: `{value, type, value_label,
    precision?, unit?, unit_label?}`, or None for unknown / no value."""
    ref = _ref(raw)
    qid = _qid(ref)
    node = value_node or {}
    vtype = node.get("@type")
    if qid:
        return {"value": qid, "type": "item", "value_label": labels.get(qid)}
    if vtype == "wikibase:TimeValue" or (isinstance(ref, str) and re.match(
            r"^-?\d{4}-\d{2}-\d{2}T", ref)):
        day = _time_text(node.get("timeValue") or ref)
        if day is None:
            return None
        precision = int(node.get("timePrecision") or 11)
        return {"value": day, "type": "time", "precision": precision,
                "value_label": date_text(day, precision)}
    if vtype == "wikibase:QuantityValue" or (isinstance(ref, str) and re.fullmatch(
            r"[+-]?\d+(?:\.\d+)?", ref)):
        amount = str(node.get("quantityAmount") or ref)
        unit = _qid(node.get("quantityUnit")) if node.get("quantityUnit") else None
        unit = None if unit == UNIT_ONE else unit
        out = {"value": amount.lstrip("+"), "type": "quantity", "unit": unit,
               "unit_label": labels.get(unit) if unit else None}
        out["value_label"] = quantity_text(out)
        return out
    if isinstance(raw, dict) and raw.get("@value") is not None:
        return {"value": raw["@value"], "type": "string", "value_label": raw["@value"],
                "language": raw.get("@language")}
    if isinstance(ref, str) and ref and not ref.startswith("_:"):
        return {"value": ref, "type": "string", "value_label": ref}
    return None


def entity_of(payload, qid=None, fetched_at=None):
    """The item of a `Special:EntityData/<Q>.jsonld` answer, as this module
    hands it on: `{id, label, description, url, data_url, revision_id,
    modified, enwiki: {title, url} | None, instance_of: [labels], work:
    film | series | None, statements: {P: [statement]}, fetched_at}`. A
    statement is `{id, property, rank, best, value, type, value_label,
    precision?, unit?, unit_label?, qualifiers: {P: [value]}}`; only
    statements whose value is known are kept (`unknown value` / `no value`
    are not facts)."""
    context = (payload or {}).get("@context") or {}
    nodes = {}
    for node in (payload or {}).get("@graph") or []:
        if isinstance(node, dict) and node.get("@id"):
            _merge(nodes, node)
    data = next((n for i, n in nodes.items() if str(i).startswith("data:") and n.get("about")),
                {})
    main_id = _ref(data.get("about")) or (f"wd:{qid}" if qid else None)
    main_q = _qid(main_id) or qid
    main = nodes.get(main_id) or nodes.get(f"wd:{main_q}") or {}
    labels = {}
    for nid, node in nodes.items():
        q = _qid(nid)
        if q:
            label = lang_value(node.get("label")) or lang_value(node.get("name"))
            if label:
                labels[q] = label
    enwiki = None
    for nid, node in nodes.items():
        types = _as_list(node.get("@type"))
        if "schema:Article" in types and _ref(node.get("about")) == main_id \
                and _ref(node.get("isPartOf")) == ENWIKI:
            title = lang_value(node.get("name"), ("en",)) or urllib.parse.unquote(
                str(nid).rsplit("/wiki/", 1)[-1]).replace("_", " ")
            enwiki = {"title": title, "url": nid}
    statements = {}
    for key, ids in main.items():
        m = re.fullmatch(r"p:(P\d+)", _term_iri(context, key) if key.startswith("p:") else key)
        if not m:
            continue
        prop = m.group(1)
        for sid in _as_list(ids):
            st = nodes.get(_ref(sid)) or {}
            rec = _statement(st, prop, context, nodes, labels)
            if rec is not None:
                statements.setdefault(prop, []).append(rec)
    instance = [labels.get(s["value"]) or s["value"] for s in statements.get("P31") or []
                if s["type"] == "item" and s["best"]]
    work = None
    joined = " ".join(instance).lower()
    if re.search(r"series|television|programme|program|show|miniseries", joined):
        work = "series"
    elif "film" in joined:
        work = "film"
    revision = data.get("version")
    return {"id": main_q, "label": labels.get(main_q) or main_q,
            "description": lang_value(main.get("description")),
            "url": ENTITY_PAGE.format(id=main_q),
            "data_url": SITE_BASE + ENTITY_DATA_PATH.format(id=main_q),
            "revision_id": int(revision) if str(revision or "").isdigit() else revision,
            "modified": _literal(data.get("dateModified")),
            "enwiki": enwiki, "instance_of": instance, "work": work,
            "labels": labels, "statements": statements, "fetched_at": fetched_at}


def _statement(st, prop, context, nodes, labels):
    if not st:
        return None
    raw = st.get(f"ps:{prop}")
    if raw is None:
        return None
    vnode = nodes.get(_ref(st.get(f"psv:{prop}"))) if st.get(f"psv:{prop}") else None
    main = _value(raw if not isinstance(raw, list) else raw[0], vnode, labels)
    if main is None:
        return None
    rank = str(_ref(st.get("rank")) or "").replace("wikibase:", "").replace("Rank", "").lower()
    rec = {"id": str(st.get("@id") or "").replace("wds:", ""), "property": prop,
           "rank": rank or "normal",
           "best": "wikibase:BestRank" in _as_list(st.get("@type")),
           **main, "qualifiers": {}}
    for key, value in st.items():
        iri = _term_iri(context, key)
        m = re.fullmatch(r"pq:(P\d+)", iri)
        if not m:
            continue
        qprop = m.group(1)
        vnodes = [nodes.get(_ref(v)) for v in _as_list(st.get(f"pqv:{qprop}"))]
        for i, item in enumerate(_as_list(value)):
            q = _value(item, vnodes[i] if i < len(vnodes) else None, labels)
            if q is not None:
                rec["qualifiers"].setdefault(qprop, []).append(q)
    return rec


# --------------------------------------------------------------------------
# finding the topic's item
# --------------------------------------------------------------------------

def norm_title(title):
    """An article title for comparison: underscores, the first letter's case
    and Unicode form do not count."""
    t = unicodedata.normalize("NFC", urllib.parse.unquote(str(title or ""))).replace("_", " ")
    t = re.sub(r"\s+", " ", t).strip()
    return (t[:1].upper() + t[1:]) if t else t


def bare_title(title):
    """`Bunker (2026 film)` -> `Bunker`."""
    return re.sub(r"\s*\([^)]*\)\s*$", "", norm_title(title)).strip()


def title_year(title):
    m = re.search(r"\((?:[^)]*\b)?(\d{4})\b[^)]*\)\s*$", norm_title(title))
    return int(m.group(1)) if m else None


def title_work(title):
    m = re.search(r"\(([^)]*)\)\s*$", norm_title(title))
    low = (m.group(1) if m else "").lower()
    if "film" in low or "movie" in low:
        return "film"
    if re.search(r"series|season|tv|miniseries|show", low):
        return "series"
    return None


def search_query(title, classes=WORK_CLASSES):
    """The search for a work: its bare name among films and TV works."""
    name = bare_title(title)
    if not classes:
        return name
    return f"{name} haswbstatement:" + "|".join(f"P31={c}" for c in classes)


_SEASON_ITEM_RE = re.compile(r"\b(?:season|series) of\b", re.I)


def rank_hits(hits, year=None, work=None, season=False):
    """The hits in the order they are read: the title's year in the
    description, then its kind of work, a season item last unless a season
    is wanted - the search's own order breaks ties."""
    def score(pair):
        i, hit = pair
        desc = (hit.get("description") or "").lower()
        s = 0
        if year and str(year) in desc:
            s -= 4
        if work == "film" and "film" in desc:
            s -= 2
        if work == "series" and re.search(r"series|television|show", desc):
            s -= 2
        if not season and _SEASON_ITEM_RE.search(desc):
            s += 6
        return (s, i)
    return [h for _, h in sorted(enumerate(hits or []), key=score)]


def resolve_item(client, article, year=None, work=None, max_requests=MAX_REQUESTS_PER_TOPIC,
                 max_reads=MAX_ENTITY_READS):
    """`(item | None, reason | None, asked)` - the item whose English
    Wikipedia sitelink is `article` (the topic's resolved article title).
    `asked` lists what was asked, in order (`search` / `entity` records)."""
    title = norm_title(article)
    if not title:
        return None, "no article to look the item up by", []
    year = year or title_year(title)
    work = work or title_work(title)
    season = bool(re.search(r"\b(season|series)\s+\d+\b", title, re.I))
    asked, spent = [], 0
    hits = client.search(search_query(title))
    spent += 1
    asked.append({"what": "search", "query": search_query(title), "hits": len(hits)})
    if not hits and spent < max_requests - 1:
        hits = client.search(bare_title(title))
        spent += 1
        asked.append({"what": "search", "query": bare_title(title), "hits": len(hits)})
    if not hits:
        return None, f"Wikidata's search has no item for {bare_title(title)!r}", asked
    reads = 0
    seen = []
    for hit in rank_hits(hits, year, work, season):
        if reads >= max_reads or spent >= max_requests:
            break
        item = client.entity(hit["id"])
        reads += 1
        spent += 1
        link = ((item or {}).get("enwiki") or {}).get("title")
        asked.append({"what": "entity", "id": hit["id"], "enwiki": link})
        if item and norm_title(link) == title:
            return item, None, asked
        seen.append(f"{hit['id']} ({link or 'no English article'})")
    return None, (f"no item read links the English article {title!r}: "
                  + (", ".join(seen) or "nothing read")), asked


# --------------------------------------------------------------------------
# statements as sentences
# --------------------------------------------------------------------------

_MONTH_NAMES = ("January", "February", "March", "April", "May", "June", "July",
                "August", "September", "October", "November", "December")


def date_text(day, precision=11):
    """`2020-08-14` at day precision -> `August 14, 2020`; month -> `August
    2020`; a year or coarser -> `2020`."""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(day or ""))
    if not m:
        return str(day or "")
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if precision >= 11:
        return f"{_MONTH_NAMES[mo - 1]} {d}, {y}"
    if precision == 10:
        return f"{_MONTH_NAMES[mo - 1]} {y}"
    return str(y)


def _on(value):
    """`on August 14, 2020` / `in August 2020` / `in 2020`."""
    text = (value or {}).get("value_label") or ""
    return f"on {text}" if (value or {}).get("precision", 11) >= 11 else f"in {text}"


def _number(amount):
    try:
        n = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    return f"{int(n):,}" if n == int(n) else f"{n:,.2f}"


def quantity_text(q):
    """`+43` -> `43`; a sum in US dollars -> `$123,456`; another unit by its
    label."""
    amount = _number(q.get("value"))
    unit = q.get("unit")
    if unit in UNIT_SYMBOLS:
        return f"{UNIT_SYMBOLS[unit]}{amount}"
    if unit and q.get("unit_label"):
        return f"{amount} {q['unit_label']}"
    return amount


def _label(v):
    return (v or {}).get("value_label") or (v or {}).get("value") or ""


def _first(st, *props):
    for p in props:
        got = (st.get("qualifiers") or {}).get(p) or []
        if got:
            return got[0]
    return None


def _the(name):
    return name if re.match(r"(?i)the\s", name or "") else f"the {name}"


def sentence(entity, st):
    """One statement as one plain English sentence - what the writer quotes.
    Every name, date and number in it is the statement's own."""
    e = (entity or {}).get("label") or (entity or {}).get("id")
    p = st.get("property")
    v = _label(st)
    when = _first(st, Q_WHEN)
    in_year = f" in {when['value_label'][-4:]}" if when and when.get("type") == "time" else ""
    as_of = f" as of {when['value_label']}" if when and when.get("type") == "time" else ""
    series = (entity or {}).get("work") == "series"
    if p == "P577":
        place = _first(st, *Q_PLACE)
        where = ""
        if place:   # a country, or a festival the film premiered at
            name = _label(place)
            where = f" at {_the(name)}" if re.search(r"(?i)festival", name) else f" in {name}"
        return f"{e} was released {_on(st)}{where}."
    if p == "P580":
        return f"{e} {'began airing' if series else 'started'} {_on(st)}."
    if p == "P582":
        return f"{e} {'ended its run' if series else 'ended'} {_on(st)}."
    if p == "P161":
        role = _first(st, *Q_ROLE)
        return f"{v} is in the cast of {e}" + (f" as {_label(role)}" if role else "") + "."
    if p == "P57":
        return f"{e} was directed by {v}."
    if p == "P58":
        return f"{e} was written by {v}."
    if p == "P170":
        return f"{e} was created by {v}."
    if p == "P162":
        return f"{v} is a producer of {e}."
    if p == "P86":
        return f"The music of {e} is by {v}."
    if p == "P272":
        return f"{e} was produced by {v}."
    if p == "P750":
        return f"{e} is distributed by {v}."
    if p == "P449":
        return f"{e} was originally broadcast on {v}."
    if p in ("P166", "P1411"):
        winner = _first(st, "P1346")
        work = _first(st, "P1686")
        tail = ""
        if winner and _label(winner) != e:
            tail = f" (winner: {_label(winner)})"
        elif work and _label(work) != e:
            tail = f" (for {_label(work)})"
        verb = "received" if p == "P166" else "was nominated for"
        return f"{e} {verb} {_the(v)}{in_year}{tail}."
    if p in ("P2437", "P1113"):
        noun = "season" if p == "P2437" else "episode"
        return f"{e} has {v} {noun}{'' if str(st.get('value')) == '1' else 's'}{as_of}."
    if p == "P2142":
        crit = _first(st, Q_CRITERION)
        place = _first(st, *Q_PLACE)
        notes = ", ".join(x for x in (_label(crit) if crit else "", _label(place) if place else "") if x)
        return f"{e} grossed {v}" + (f" ({notes})" if notes else "") + f"{as_of}."
    if p == "P2130":
        return f"{e} cost {v} to make{as_of}."
    label = st.get("property_label") or PROPERTY_LABELS.get(p) or p
    return f"{e} - {label}: {v}."


def _value_key(st):
    v = str(st.get("value") or "")
    if st.get("type") in ("item", "time", "quantity"):
        return v
    return hashlib.sha1(v.encode("utf-8")).hexdigest()[:8]


def _order(statements):
    """Best rank first (preferred before normal); awards and nominations
    newest first; otherwise the item's own order (billing, for a cast)."""
    def when(st):
        w = _first(st, Q_WHEN)
        return (w or {}).get("value") or ""
    best = [s for s in statements if s.get("best")] or \
        [s for s in statements if s.get("rank") != "deprecated"]
    rank = {"preferred": 0, "normal": 1}
    out = sorted(best, key=lambda s: rank.get(s.get("rank"), 2))
    if statements and statements[0].get("property") in ("P166", "P1411"):
        out = sorted(out, key=when, reverse=True)       # stable: rank kept within a date
    return out


def piece_id(entity, st, seen=None):
    base = f"{SOURCE}:{entity['id']}:{st['property']}:{_value_key(st)}"
    if seen is None:
        return base
    n = seen.get(base, 0) + 1
    seen[base] = n
    return base if n == 1 else f"{base}~{n}"


def _qualifiers_out(st):
    return {p: [{k: q.get(k) for k in ("value", "type", "value_label", "precision")
                 if q.get(k) is not None} for q in qs]
            for p, qs in (st.get("qualifiers") or {}).items()}


def statement_piece(entity, st, fact_kind=None, seen=None):
    """One statement as a support-text piece (the contract in the module
    docstring)."""
    prop = st["property"]
    plabel = (entity.get("labels") or {}).get(prop) or PROPERTY_LABELS.get(prop) or prop
    rec = dict(st, property_label=plabel)
    return {"id": piece_id(entity, st, seen), "kind": KIND_STATEMENT, "source": SOURCE,
            "publication": SITE_NAME,
            "title": f"{entity.get('label')} - {plabel}",
            "entity": entity.get("id"), "entity_label": entity.get("label"),
            "property": prop, "property_label": plabel,
            "value": st.get("value"), "value_label": st.get("value_label"),
            "value_type": st.get("type"), "qualifiers": _qualifiers_out(st),
            "fact_kind": fact_kind,
            "url": f"{entity.get('url')}#{prop}", "data_url": entity.get("data_url"),
            "revision_id": entity.get("revision_id"), "revised_at": entity.get("modified"),
            "fetched_at": entity.get("fetched_at"), "license": dict(LICENSE),
            "text": sentence(entity, rec)}


def statement_pieces(entity, properties, per_property=None, max_pieces=MAX_PIECES):
    """The item's statements of `properties` (an ordered `{P: fact kind}` -
    the channel's `properties`, `properties_of`) as pieces, property by
    property in that order, at most `per_property` of each (default
    `PER_PROPERTY_MAX`, else `PER_PROPERTY_DEFAULT`) and `max_pieces` in all.
    A statement whose value has no label (an item Wikidata names by id only)
    is not a sentence anyone can check - it is left out."""
    if not entity:
        return []
    limits = dict(PER_PROPERTY_MAX)
    if isinstance(per_property, dict):
        limits.update(per_property)
    out, seen = [], {}
    for prop, kind in (properties or {}).items():
        cap = per_property if isinstance(per_property, int) else limits.get(prop, PER_PROPERTY_DEFAULT)
        taken = 0
        for st in _order((entity.get("statements") or {}).get(prop) or []):
            if taken >= cap or len(out) >= max_pieces:
                break
            if st.get("type") == "item" and not st.get("value_label"):
                continue
            out.append(statement_piece(entity, st, kind, seen))
            taken += 1
    return out


def properties_of(entry):
    """The channel's `properties` of its `wikidata` outlet (`{P: kind}`, in
    the file's order) - {} when the outlet names none."""
    props = (entry or {}).get("properties") if isinstance(entry, dict) else None
    if not isinstance(props, dict):
        return {}
    return {p: k for p, k in props.items()
            if re.fullmatch(r"P\d+", str(p)) and isinstance(k, str) and k.strip()}


def candidate_of(piece):
    """A piece as a fact candidate for `fact_rule.check_candidate`: its
    sentence, its kind of fact, `source` Wikidata, its URL on
    www.wikidata.org (the channel's tier 1 outlet), its value and date as
    the finder's `specifics`."""
    p = piece or {}
    specifics = [x for x in (p.get("value_label"),) if x]
    for qs in (p.get("qualifiers") or {}).values():
        specifics.extend(q.get("value_label") for q in qs if q.get("value_label"))
    return {"text": p.get("text"), "kind": p.get("fact_kind") or "other",
            "source": SITE_NAME, "url": p.get("url"), "specifics": specifics,
            "section": p.get("property_label")}


def is_wikidata_piece(piece):
    p = piece or {}
    return (p.get("kind") == KIND_STATEMENT or p.get("source") == SOURCE
            or str(p.get("id") or "").startswith(SOURCE + ":"))


# --------------------------------------------------------------------------
# the cache
# --------------------------------------------------------------------------

def cache_name(url):
    """The file one answer is kept in: readable, and unique by a hash."""
    tail = url.split("://", 1)[-1].split("/", 1)[-1]
    readable = re.sub(r"[^A-Za-z0-9._+-]+", "_", tail)[:100].strip("_")
    return f"{readable}-{hashlib.sha1(url.encode('utf-8')).hexdigest()[:10]}.json"


def cached_transport(cache_dir, transport=None, max_age_seconds=CACHE_MAX_AGE_SECONDS,
                     clock=time.time):
    """A transport that serves recorded answers from `cache_dir` and records
    the 200s and 404s it fetches. A stale answer is asked again; when asking
    fails (`WikidataError`) the stale one is served rather than nothing.
    `max_age_seconds=None` never expires (a recorded fixture)."""
    real = transport or urllib_transport
    directory = os.fspath(cache_dir)

    def _held(path, url):
        if not os.path.isfile(path):
            return None
        try:
            with open(path, encoding="utf-8") as fh:
                held = json.load(fh)
        except (OSError, ValueError):
            return None
        return held if isinstance(held, dict) and held.get("url") == url else None

    def _response(held):
        return HttpResponse(held["status"], held["body"],
                            fetched_at=held.get("fetched_at")
                            or iso(float(held.get("fetched_at_epoch") or 0)))

    def _transport(url, headers, timeout=DEFAULT_TIMEOUT):
        path = os.path.join(directory, cache_name(url))
        held = _held(path, url)
        if held:
            age = clock() - float(held.get("fetched_at_epoch") or 0)
            if max_age_seconds is None or age <= max_age_seconds:
                return _response(held)
        try:
            response = real(url, headers, timeout)
        except WikidataError:
            if held:
                return _response(held)
            raise
        if response.status in CACHED_STATUSES:
            os.makedirs(directory, exist_ok=True)
            now = clock()
            record = {"url": url, "status": response.status, "body": response.body,
                      "fetched_at_epoch": now, "fetched_at": iso(now)}
            fd, tmp = tempfile.mkstemp(dir=directory, suffix=".tmp")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(record, fh, ensure_ascii=False)
            os.replace(tmp, path)
            response.fetched_at = record["fetched_at"]
        return response

    return _transport


def cached_client(cache_dir=None, transport=None, max_age_seconds=CACHE_MAX_AGE_SECONDS,
                  **kw):
    """A client whose network goes through the cache (when given)."""
    if cache_dir:
        transport = cached_transport(cache_dir, transport, max_age_seconds=max_age_seconds)
    return WikidataClient(transport=transport, **kw)
