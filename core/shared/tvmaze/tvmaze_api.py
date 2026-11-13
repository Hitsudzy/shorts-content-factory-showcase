#!/usr/bin/env python3
"""CF-0636: the factory's TVmaze client - episode descriptions as support text.

**Why TVmaze** (the user's decision of 2026-10-08 on CF-0557, Q2). A topic
about an episode that has just aired is told from the episode's own
description, and Wikipedia writes its `ShortSummary` hours after the
broadcast: in the October measurement (`docs/sources-pool-2026-10.md`) 7 of
the 9 "an episode aired" topics had no Wikipedia text at the batch's hour.
TVmaze's API gives each episode's summary, its air date and its show, under
**CC BY-SA 4.0** - "for any purpose", as long as TVmaze is credited with a
link back and ShareAlike is kept (https://www.tvmaze.com/api#licensing,
read 2026-10-08). The API host has no robots.txt (`api.tvmaze.com/robots.txt`
answers 404); `www.tvmaze.com/robots.txt` names no AI agent. The channel's
list says it may be read: `channels/example-film/fact-sources.json`, outlet
`tvmaze`, `use: read_text`, verdict `allowed` (`shared/source_policy.py`).

**Where it lives.** In the root's shared layer beside the Wikipedia client
(`shared/wikipedia/wikipedia_api.py`) and in its shape, so the Trend Hunter
(the topic's support text) and the Content Researcher can share one client,
one etiquette and one cache. A repository loads this one file by path and
registers it under `MODULE_NAME` in `sys.modules` (the pattern of the
hunter's `scripts/_wikipedia.py`); it keeps no copy.

**What this client does on the network**, in full:

* one host, ``https://api.tvmaze.com``, over HTTPS, GET only - never the
  site's HTML pages, no account, no API key, nothing crawled;
* four endpoints: ``/singlesearch/shows?q=`` (the one best show for a name),
  ``/shows/<id>`` (one show), ``/shows/<id>/episodebynumber?season=&number=``
  (one episode) and ``/shows/<id>/episodes`` (a show's episode list);
* serial requests, at least ``MIN_INTERVAL_SECONDS`` (0.5 s) apart: the API
  allows "at least 20 calls every 10 seconds per IP" - this client never asks
  for more than that;
* a 429 (and a 5xx) is retried after ``Retry-After`` (else a few seconds),
  at most ``MAX_RETRIES`` times, as the API's own page asks;
* a User-Agent that names the calling stage and carries a contact (the API
  asks for one that identifies the application) - never a browser's.

**A gate before every request.** `TvmazeClient(gate=...)` takes a callable
``gate(url)`` that raises when the URL may not be read; it is called before
each request, a cached answer included, and its exception goes up as it is.
The hunter hands in its `source_gate.check(url, sources)` with the channel's
fact-sources list (CF-0634), so the list - not this file - says whether
TVmaze may be read.

**Errors, and what is not one.** No show of that name, no episode of that
number: an empty result (``None``), not an exception - the API answers 404
for both. A network failure, a status that survives the retries or a body
that is not JSON is a `TvmazeError`: a run that could not reach the source
must not look like a show without episodes.

**The cache** (`cached_transport`, `<batch>/work/tvmaze-cache/`): one JSON
file per request, ``{url, status, body, fetched_at_epoch, fetched_at}`` - the
same record as the Wikipedia cache. An answer older than
``CACHE_MAX_AGE_SECONDS`` (1 h - an episode's summary appears after the
broadcast; TVmaze's own edge caches 60 min) is asked again, and served stale
only when asking fails. Every answer carries the moment it was fetched
(`HttpResponse.fetched_at`, `client.last_fetched_at`) and so does every piece
(`fetched_at`): an episode description has no revision id, and the time it
was read is what the claim check and the note can name.

**The piece** (`episode_piece`) is the support-text contract of
`agents/trend-hunter/scripts/support_text.py` (`id`, `kind`, `source`,
`title`, `url`, `revision_id`, `revised_at`, `text`) with kind
``tvmaze_episode`` and source ``tvmaze``; the claim layer
(`shared/factrule/claims.py`, `claim_judge.py`) reads it as a quotable piece
and as a second source for a fresh reveal, and the publisher credits it in
the video's description (`agents/publisher/publish_card.py`).

Stdlib only.
"""
import datetime as dt
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

API_BASE = "https://api.tvmaze.com"
SITE_BASE = "https://www.tvmaze.com"
SITE_NAME = "TVmaze"
SOURCE = "tvmaze"                        # a piece's `source`
KIND_EPISODE = "tvmaze_episode"          # a piece's `kind`
LICENSE = {"title": "CC BY-SA 4.0",
           "url": "https://creativecommons.org/licenses/by-sa/4.0/"}
TERMS_URL = "https://www.tvmaze.com/api#licensing"

SINGLESEARCH_PATH = "/singlesearch/shows"            # ?q= -> show | 404
SHOW_PATH = "/shows/{id}"                            # -> show | 404
EPISODE_BY_NUMBER_PATH = "/shows/{id}/episodebynumber"   # ?season=&number= -> episode | 404
EPISODES_PATH = "/shows/{id}/episodes"               # -> [episode]

TOOL_NAME = "shorts-content-factory"
TOOL_VERSION = "2.3"
DEFAULT_CONTACT = "https://example.com/shorts-content-factory"
CONTACT_ENV = "TVMAZE_CONTACT"

# "at least 20 calls every 10 seconds per IP address" - 0.5 s apart is 20.
MIN_INTERVAL_SECONDS = 0.5
DEFAULT_TIMEOUT = 20
MAX_RETRIES = 3
RETRY_BACKOFF_SECONDS = 3
RETRY_STATUS = (429, 500, 502, 503, 504)

CACHE_REL = os.path.join("work", "tvmaze-cache")
CACHE_MAX_AGE_SECONDS = 3600
CACHED_STATUSES = (200, 404)

# The one name every loader registers this file under - see the docstring.
MODULE_NAME = "factory_tvmaze_api"


class TvmazeError(RuntimeError):
    """The source could not be read. Never raised for 'no such show' or 'no
    such episode' - those are empty results."""


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


def urllib_transport(url, headers, timeout=DEFAULT_TIMEOUT):
    """The real network. An HttpResponse for any HTTP status; TvmazeError
    only when there was no answer at all."""
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
            return HttpResponse(response.status, body, dict(response.headers),
                                fetched_at=iso(time.time()))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", "replace") if error.fp else ""
        return HttpResponse(error.code, body, dict(error.headers or {}),
                            fetched_at=iso(time.time()))
    except (urllib.error.URLError, OSError) as error:
        raise TvmazeError(f"could not reach {url}: {error}") from error


class TvmazeClient:
    """Serial, rate-limited, retrying GET client for the TVmaze API.

    `transport` - ``(url, headers, timeout) -> HttpResponse`` - is the seam the
    tests hand recorded answers through (a test never goes to the network).
    `gate` - ``gate(url)`` - is called before every request and raises when
    the URL may not be read (the hunter's `source_gate.check`)."""

    def __init__(self, transport=None, api_base=API_BASE,
                 min_interval=MIN_INTERVAL_SECONDS, timeout=DEFAULT_TIMEOUT,
                 max_retries=MAX_RETRIES, sleep=time.sleep, clock=time.monotonic,
                 tool_name=None, gate=None, wall=time.time):
        self.transport = transport or urllib_transport
        self.api_base = api_base.rstrip("/")
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

    def url(self, path, params=None):
        url = self.api_base + path
        if params:
            url += "?" + urllib.parse.urlencode(params)
        return url

    def fetch(self, path, params=None):
        """One request with the gate and the etiquette, without the retries."""
        url = self.url(path, params)
        if self.gate is not None:
            self.gate(url)
        headers = {"User-Agent": user_agent(self.tool_name),
                   "Accept": "application/json",
                   "Accept-Encoding": "identity"}
        self._respect_interval()
        response = self.transport(url, headers, self.timeout)
        self._last_request_at = self._clock()
        self.request_count += 1
        return response

    def get(self, path, params=None, missing_ok=False):
        """The decoded JSON of one call with the retries; None for a 404 when
        `missing_ok`. Sets `last_fetched_at` to the answer's own moment."""
        last_problem = None
        for attempt in range(1, self.max_retries + 1):
            response = self.fetch(path, params)
            fetched = getattr(response, "fetched_at", None) or iso(self._wall())
            if response.status == 200:
                try:
                    payload = json.loads(response.body)
                except ValueError as error:
                    raise TvmazeError(f"the API answered something that is not JSON: {error}")
                self.last_fetched_at = fetched
                return payload
            if response.status == 404 and missing_ok:
                self.last_fetched_at = fetched
                return None
            if response.status in RETRY_STATUS:
                last_problem = f"HTTP {response.status}"
            else:
                raise TvmazeError(f"HTTP {response.status} from {self.url(path, params)}")
            if attempt < self.max_retries:
                self._sleep(self._retry_delay(response, attempt))
        raise TvmazeError(f"gave up after {self.max_retries} attempts ({last_problem}) "
                          f"on {self.url(path, params)}")

    # -- the endpoints ----------------------------------------------------
    def search_show(self, name):
        """The API's one best show for `name` (`show_of`), or None."""
        payload = self.get(SINGLESEARCH_PATH, {"q": name}, missing_ok=True)
        return show_of(payload, self.last_fetched_at) if payload else None

    def show(self, show_id):
        payload = self.get(SHOW_PATH.format(id=int(show_id)), missing_ok=True)
        return show_of(payload, self.last_fetched_at) if payload else None

    def episode_by_number(self, show, season, number):
        """One episode (`episode_of`) of `show` (a `show_of` dict or an id), or
        None when the show has no such episode."""
        show_id = show["id"] if isinstance(show, dict) else int(show)
        payload = self.get(EPISODE_BY_NUMBER_PATH.format(id=show_id),
                           {"season": int(season), "number": int(number)}, missing_ok=True)
        if not payload:
            return None
        return episode_of(payload, show if isinstance(show, dict) else None,
                          self.last_fetched_at)

    def episodes(self, show, specials=False):
        """Every episode of `show` in the API's order (season, number); the
        specials (no number) only when asked."""
        show_id = show["id"] if isinstance(show, dict) else int(show)
        payload = self.get(EPISODES_PATH.format(id=show_id), missing_ok=True) or []
        out = [episode_of(p, show if isinstance(show, dict) else None, self.last_fetched_at)
               for p in payload if isinstance(p, dict)]
        return out if specials else [e for e in out if e["number"] is not None]


# --------------------------------------------------------------------------
# shapes
# --------------------------------------------------------------------------

_BLOCK_RE = re.compile(r"(?i)</p\s*>|<br\s*/?>|</li\s*>|</h\d\s*>")
_TAG_RE = re.compile(r"<[^>]+>")


def plain_text(summary_html):
    """TVmaze's summary HTML as plain text: a paragraph per line, tags gone,
    entities decoded, spaces collapsed. '' for None."""
    if not summary_html:
        return ""
    text = _BLOCK_RE.sub("\n", str(summary_html))
    text = html.unescape(_TAG_RE.sub("", text))
    lines = [re.sub(r"[ \t\r\f\v]+", " ", ln).strip() for ln in text.split("\n")]
    return "\n".join(ln for ln in lines if ln)


def _api_link(payload):
    return (((payload or {}).get("_links") or {}).get("self") or {}).get("href")


def show_of(payload, fetched_at=None):
    """The show as this module hands it on."""
    p = payload or {}
    network = (p.get("network") or {}).get("name")
    web = (p.get("webChannel") or {}).get("name")
    country = ((p.get("network") or {}).get("country") or {}).get("code") or \
        ((p.get("webChannel") or {}).get("country") or {}).get("code")
    return {"id": p.get("id"), "name": p.get("name"), "url": p.get("url"),
            "api_url": _api_link(p) or (f"{API_BASE}/shows/{p['id']}" if p.get("id") else None),
            "type": p.get("type"), "language": p.get("language"), "status": p.get("status"),
            "premiered": p.get("premiered"), "ended": p.get("ended"),
            "network": network, "web_channel": web, "country": country,
            "imdb": (p.get("externals") or {}).get("imdb"),
            "text": plain_text(p.get("summary")), "fetched_at": fetched_at}


def episode_of(payload, show=None, fetched_at=None):
    """One episode as this module hands it on: `text` is the summary as plain
    text ('' when TVmaze has none yet), `url` the site's episode page (the
    page a person is sent to, the attribution link)."""
    p = payload or {}
    show_link = ((p.get("_links") or {}).get("show") or {})
    show_id = (show or {}).get("id")
    if show_id is None:
        m = re.search(r"/shows/(\d+)", show_link.get("href") or "")
        show_id = int(m.group(1)) if m else None
    return {"id": p.get("id"), "show_id": show_id,
            "show": (show or {}).get("name") or show_link.get("name"),
            "show_url": (show or {}).get("url"),
            "season": p.get("season"), "number": p.get("number"),
            "name": p.get("name"), "type": p.get("type"),
            "airdate": p.get("airdate") or None, "airstamp": p.get("airstamp") or None,
            "runtime": p.get("runtime"), "url": p.get("url"),
            "api_url": _api_link(p) or (f"{API_BASE}/episodes/{p['id']}" if p.get("id") else None),
            "summary_html": p.get("summary"), "text": plain_text(p.get("summary")),
            "fetched_at": fetched_at}


def _parse_time(value):
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=dt.timezone.utc)
    if isinstance(value, dt.date):
        return dt.datetime(value.year, value.month, value.day, tzinfo=dt.timezone.utc)
    if not value:
        return None
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=dt.timezone.utc)


def aired(episode, now=None):
    """Has the episode aired by `now` (default: the clock)? Its `airstamp`
    when TVmaze has one, else the end of its `airdate`; an episode with no
    date has not aired (TBA)."""
    now_t = _parse_time(now) or dt.datetime.now(dt.timezone.utc)
    stamp = _parse_time((episode or {}).get("airstamp"))
    if stamp is None:
        day = (episode or {}).get("airdate")
        if not day:
            return False
        stamp = _parse_time(day)
        if stamp is None:
            return False
        stamp = stamp + dt.timedelta(days=1)
    return stamp <= now_t


# --------------------------------------------------------------------------
# finding the topic's show and episode
# --------------------------------------------------------------------------

def norm_name(name):
    """A show name for comparison: case, accents, punctuation, a leading
    'The' and a year in brackets do not count."""
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    s = s.casefold().replace("&", " and ")
    s = re.sub(r"\(\s*\d{4}\s*\)", " ", s)
    s = re.sub(r"[^\w]+", " ", s).strip()
    s = re.sub(r"^the\s+", "", s)
    return re.sub(r"\s+", " ", s)


def show_mismatch(show, name, network=None):
    """Why `show` is not the series named `name` (on `network`) - None when it
    is. The name must be the same name (`norm_name`); a network, when the
    topic knows one, must be the show's network or web channel (either
    containing the other: 'Example Network' / 'Example Max', 'Prime Video' / 'Amazon Prime
    Video')."""
    if not show:
        return "no show"
    if norm_name(show.get("name")) != norm_name(name):
        return f"the API's best show for {name!r} is {show.get('name')!r}"
    if network:
        want = norm_name(network)
        have = [norm_name(n) for n in (show.get("network"), show.get("web_channel")) if n]
        if have and not any(want in h or h in want for h in have):
            return (f"{show.get('name')!r} airs on {', '.join(n for n in (show.get('network'), show.get('web_channel')) if n)}, "
                    f"the topic says {network!r}")
    return None


def resolve_show(client, name, network=None):
    """`(show | None, reason | None)` - the API's best show for `name`, kept
    only when it is that series (`show_mismatch`)."""
    show = client.search_show(name)
    if show is None:
        return None, f"TVmaze has no show for {name!r}"
    why = show_mismatch(show, name, network)
    return (None, why) if why else (show, None)


def season_episodes(episodes, season):
    """The regular episodes of one season, in order."""
    return [e for e in episodes or [] if e.get("season") == int(season)
            and e.get("number") is not None]


def event_episode(client, show, event):
    """The episode a topic's event names, or None. `event` is the hunter's
    `support_text.event_of` record: `{season, episode, which: number |
    finale | premiere, code?}`. A numbered episode of a season is asked for by
    number (`episodebynumber`, one request); a finale is the last listed
    episode of the season and a premiere the first (the episode list, one
    request). An overall number - a lead with no season, or a season code
    (`Episode 409`) that names no episode of its season - is the episode at
    that place among the show's regular episodes."""
    if not event:
        return None
    which = event.get("which")
    season = event.get("season")
    number = event.get("episode")
    if which == "number" and number is not None and season is not None:
        found = client.episode_by_number(show, int(season), int(number))
        if found is not None or event.get("code") is None:
            return found
    overall = event.get("code") if event.get("code") is not None else (
        number if which == "number" and season is None else None)
    if which == "number" and overall is None:
        return None
    if which in ("finale", "premiere") and season is None:
        return None
    every = client.episodes(show)
    if overall is not None:
        return every[int(overall) - 1] if 1 <= int(overall) <= len(every) else None
    rows = season_episodes(every, season)
    if not rows:
        return None
    return rows[-1] if which == "finale" else rows[0]


def piece_id(episode):
    return f"{SOURCE}:episode:{episode.get('id')}"


def episode_piece(episode, show=None):
    """The episode as a support-text piece (`support_text.py`'s contract):
    `{id, kind, source, publication, title, show, url, api_url, revision_id,
    revised_at, fetched_at, season, episode, episode_in_season, air_date,
    airstamp, license, text}`. `title` is the episode's name, `url` the site's
    episode page; there is no revision - `fetched_at` is when the text was
    read."""
    e = episode or {}
    return {"id": piece_id(e), "kind": KIND_EPISODE, "source": SOURCE,
            "publication": SITE_NAME,
            "title": e.get("name"), "show": e.get("show") or (show or {}).get("name"),
            "url": e.get("url"), "api_url": e.get("api_url"),
            "revision_id": None, "revised_at": None, "fetched_at": e.get("fetched_at"),
            "season": e.get("season"), "episode": e.get("number"),
            "episode_in_season": e.get("number"),
            "air_date": e.get("airdate"), "airstamp": e.get("airstamp"),
            "license": dict(LICENSE), "text": e.get("text") or ""}


def is_tvmaze_piece(piece):
    """Is a support-text piece TVmaze's (by its kind, its source or its id)?"""
    p = piece or {}
    return (p.get("kind") == KIND_EPISODE or p.get("source") == SOURCE
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
    fails (`TvmazeError`) the stale one is served rather than nothing.
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
        except TvmazeError:
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
    return TvmazeClient(transport=transport, **kw)
