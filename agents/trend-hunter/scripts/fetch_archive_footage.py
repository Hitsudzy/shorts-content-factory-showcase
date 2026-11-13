#!/usr/bin/env python3
"""CF-0665 (TH-3 of the root's docs/science-footage.md) - footage candidates of
a science story out of two archives that publish files with their licence:
the NASA Image and Video Library and Wikimedia Commons. No key, no YouTube
quota, nothing downloaded here.

Why. A science story's best footage is often not on YouTube at all, or is
there only as a re-upload nobody can license: NASA's library holds the
centres' own cuts (launch, b-roll, animation, briefing) as plain files, and
Commons holds files whose licence is machine-readable per file. A candidate
from either is a file the indexer can fetch directly (FI-1), with a licence
and a credit line known before download - what the card (PUB-1) and the
on-screen credit (VE-1) need.

Which channels. Only a channel whose `channels/<id>/footage-origin.json` names
these origins with `found_by[].how == "archive_api"` (ExampleScience: `nasa`,
`nasa_jpl`, `wikimedia_commons`). ExampleFilm names none: the script says so
and writes nothing, so its footage path is the one it had.

What is asked, per topic (a story topic only - `topic_relevance.is_story`):
the story's forms (`topic_relevance.story_forms`, CF-0662), at most
MAX_QUERIES of them, spaceless copies skipped;

  * NASA: `GET images-api.nasa.gov/search?q=<form>&media_type=video` - the
    item's `nasa_id`, `title`, `date_created`, `center`, `description`,
    `keywords`, `photographer`; then its manifest (the item's own `href`,
    `collection.json`: the list of renditions) and its `metadata.json`
    (duration, picture size, the embedded credit). The rendition is
    `~orig.mp4` when it fits under the byte ceiling (MAX_DOWNLOAD_BYTES), else
    `~large.mp4`, else `~medium.mp4` - its size is the file's own
    `Content-Length` (one HEAD). Licence: public domain (a work of NASA), read
    as `PD-USGov-NASA`; credit `NASA/<centre>` (JPL: `NASA/JPL-Caltech`), or
    the item's own credit when it names NASA ("NASA/Frank Michaux"). An item
    whose own credit names somebody else and not NASA is that owner's
    (footage-origin.json, NASA's third caveat): its licence reads as that
    credit, which the channel's rule refuses (`licence_refused`).
  * Commons: `action=query&generator=search&gsrnamespace=6&gsrsearch=<form>
    filetype:video&prop=imageinfo&iiprop=url|size|mime|extmetadata` - one
    call. Licence `extmetadata.LicenseShortName` (+ `NonFree`), judged by the
    channel's rule (`shared/footage_licence.py` `licence_of`, CF-0662: NC, ND,
    non-free are refused there); credit `Artist` with the HTML stripped, else
    `Credit`; the link is the file page. A file over the byte ceiling or not a
    video is skipped here, with the reason in the signal.

Only the items whose own title, description or "channel" name the story
(`topic_relevance.names_work`, the rule `footage_candidates.py` applies first)
are looked at further - the manifest and metadata calls are spent on those.

Output: a signal of `fetch_youtube_signal.py`'s shape (`source: "archive"`,
`searches: 0` - the YouTube ledger charges nothing), every video with
`video_id` `nasa:<nasa_id>` / `commons:<pageid>`, `kind: "archive"`,
`download_url`, `media_type`, `bytes`, `duration_seconds` (null when nobody
said), `licence_short_name` / `licence_non_free`, `credit`, `source_url`,
`archive_origin` (the `footage_origins[].id`) and `archive` (rendition,
picture size, centre, the caveats of CF-0564 that apply). `footage_candidates.py`
picks from it as from any signal - two `--signal` files of one topic are one
pool - and puts the archive candidates first for a story topic.

Usage (from the agent root):
  scripts/fetch_archive_footage.py --batch <batch-dir> \\
      [--out-dir <batch-dir>/work/archive] [--topic <id>]   # archive-<topic_id>.json
  scripts/fetch_archive_footage.py "Artemis II" --channel example-science \\
      [--type mission] [--subject ...]                       # one story by hand
"""
import argparse
import html
import json
import re
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from _runlog import runlog  # noqa: E402
import footage_origin  # noqa: E402
import topic_relevance  # noqa: E402

SOURCE = "archive"
KIND = "archive"
NASA = "nasa_images"
COMMONS = "wikimedia_commons"
# footage_origins[].id -> the archive that answers for it
ARCHIVE_OF_ORIGIN = {"nasa": NASA, "nasa_jpl": NASA, "wikimedia_commons": COMMONS}
ARCHIVE_API = "archive_api"

NASA_SEARCH = "https://images-api.nasa.gov/search"
NASA_DETAILS = "https://images.nasa.gov/details/{nasa_id}"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
# Wikimedia asks for a descriptive User-Agent (meta.wikimedia.org User-Agent policy).
USER_AGENT = ("ExampleFootagehunter/1.0 (trend-hunter fetch_archive_footage.py; "
              "archive footage search for a science channel) python-requests")
TIMEOUT = 30

MAX_QUERIES = 2          # story forms asked per archive
MAX_RESULTS = 12         # items per archive per topic that are looked at further
# A file larger than this is not offered for direct download: NASA falls back
# to a smaller rendition, Commons skips the file. 500 MB holds a 4K NASA cut of
# ~3 min (153 MiB for 54 s) and every Commons file of the Artemis II answer but
# the 551 MB, 28-minute flight-day highlights.
MAX_DOWNLOAD_BYTES = 500 * 1024 * 1024
NASA_RENDITIONS = ("orig", "large", "medium")

NASA_LICENCE = "PD-USGov-NASA"
NASA_CENTRES = {           # centre code -> the credit NASA itself writes
    "HQ": "NASA", "JPL": "NASA/JPL-Caltech", "GSFC": "NASA/Goddard", "KSC": "NASA/Kennedy",
    "JSC": "NASA/Reyes", "MSFC": "NASA/Marshall", "ARC": "NASA/Ames",
    "LARC": "NASA/Langley", "GRC": "NASA/Glenn", "AFRC": "NASA/Armstrong",
    "SSC": "NASA/Stennis", "WSTF": "NASA/White Sands", "WFF": "NASA/Wallops",
}
NASA_WORDS = ("nasa", "jpl", "caltech")
# Partners whose material turns up inside NASA's cuts - named in an item's
# credit, keywords or caption they are a caveat on the candidate, not a refusal.
PARTNER_RE = re.compile(
    r"\b(esa|european space agency|csa|canadian space agency|jaxa|spacex|boeing|"
    r"lockheed( martin)?|northrop( grumman)?|blue origin|roscosmos|stsci|"
    r"axiom|sierra space)\b", re.I)
CAPTION_CREDIT_RE = re.compile(
    r"\b(?:(?:video|image|footage|animation|photo)\s+)?(?:credits?|courtesy(?: of)?)\s*[:\-]?\s*"
    r"([A-Z][^\n.;|]{1,80})")
NASA_CAVEATS = [
    "insignia: NASA's meatball, worm and seal are not public domain - never in our "
    "thumbnail, title card or brand (footage-origin.json footage_origins[nasa].caveats)",
    "people: an astronaut or employee on screen - no use that suggests NASA's endorsement, "
    "no likeness on our thumbnail or title",
]

HTML_TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")


class ArchiveError(Exception):
    pass


class Http:
    """The two calls this script makes. A test hands in a stand-in with the
    same two methods (`tests/test_archive_footage.py`), so no test reaches the
    network."""

    def __init__(self, session=None):
        import requests
        self.session = session or requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.calls = 0

    def json(self, url, params=None):
        self.calls += 1
        resp = self.session.get(url, params=params, timeout=TIMEOUT)
        if resp.status_code != 200:
            raise ArchiveError(f"{url}: HTTP {resp.status_code}")
        return resp.json()

    def head(self, url):
        """-> (status, content_length or None, content_type or None)."""
        self.calls += 1
        resp = self.session.head(url, timeout=TIMEOUT, allow_redirects=True)
        size = resp.headers.get("Content-Length")
        return (resp.status_code, int(size) if size and size.isdigit() else None,
                resp.headers.get("Content-Type"))


# --------------------------------------------------------------------------
# which archives a channel reads, and with which queries
# --------------------------------------------------------------------------

def archive_origins(config):
    """-> {archive: [footage_origins ids]} of the channel - the origins its
    footage-origin.json finds through `archive_api` and this script knows.
    Empty for a channel without them (ExampleFilm)."""
    out = {}
    for o in (config or {}).get("footage_origins") or []:
        oid = o.get("id")
        if oid not in ARCHIVE_OF_ORIGIN:
            continue
        if any((f or {}).get("how") == ARCHIVE_API for f in o.get("found_by") or []):
            out.setdefault(ARCHIVE_OF_ORIGIN[oid], []).append(oid)
    return out


def queries_of(title_ref, limit=MAX_QUERIES):
    """The story's forms to ask an archive, spaceless copies of an earlier
    form skipped ('artemisii' after 'artemis ii')."""
    out, flat = [], set()
    for form in topic_relevance.story_forms(title_ref):
        if form.replace(" ", "") in flat and " " not in form:
            continue
        flat.add(form.replace(" ", ""))
        out.append(form)
        if len(out) >= limit:
            break
    return out


# --------------------------------------------------------------------------
# small readers
# --------------------------------------------------------------------------

def strip_html(text):
    """'<a href="...">NASA</a>' -> 'NASA'; entities unescaped, spaces folded."""
    if text is None:
        return None
    return SPACES.sub(" ", html.unescape(HTML_TAG.sub(" ", str(text)))).strip() or None


def _quote_url(url):
    """An archive URL as written ('http://images-assets.nasa.gov/video/A B/A B~orig.mp4')
    -> one a client can fetch: https, the path percent-encoded, no tracking query."""
    parts = urllib.parse.urlsplit(str(url))
    path = urllib.parse.quote(urllib.parse.unquote(parts.path), safe="/~()-_.,'!")
    return urllib.parse.urlunsplit(("https", parts.netloc, path, "", ""))


def duration_from_meta(meta):
    """NASA's metadata.json -> seconds, or None. 'QuickTime:Duration' is
    '0:01:16' or '35.2 s'; 'XMP:Duration' is {Scale, Value}."""
    meta = meta or {}
    for key in ("QuickTime:Duration", "QuickTime:MediaDuration", "Composite:Duration"):
        raw = str(meta.get(key) or "").strip()
        m = re.fullmatch(r"(\d+):(\d{1,2}):(\d{1,2}(?:\.\d+)?)", raw)
        if m:
            secs = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
            if secs > 0:
                return round(secs, 3)
        m = re.fullmatch(r"(\d+(?:\.\d+)?)\s*s", raw)
        if m and float(m.group(1)) > 0:
            return round(float(m.group(1)), 3)
    xmp = meta.get("XMP:Duration")
    if isinstance(xmp, dict):
        try:
            secs = float(xmp.get("Value")) * float(xmp.get("Scale"))
            if secs > 0:
                return round(secs, 3)
        except (TypeError, ValueError):
            pass
    return None


def size_from_meta(meta):
    """'Composite:ImageSize' '608x1080' -> (608, 1080), else (None, None)."""
    m = re.fullmatch(r"(\d+)\s*[x×]\s*(\d+)", str((meta or {}).get("Composite:ImageSize") or ""))
    return (int(m.group(1)), int(m.group(2))) if m else (None, None)


def _names_nasa(text):
    words = re.findall(r"[a-z]+", str(text or "").lower())
    return any(w in NASA_WORDS for w in words)


def _blank(value):
    return not str(value or "").strip() or str(value).strip().lower() in ("n/a", "none", "-")


def nasa_credit(data, meta, centre):
    """-> (credit, third_party_owner or None, partners). The item's own credit
    (photographer, XMP:Credit, a 'Credit:' line of its caption) when it names
    NASA; else NASA/<centre>. A credit that names somebody and not NASA is the
    owner's material (footage-origin.json: third-party material inside NASA
    media is not NASA's to give)."""
    meta = meta or {}
    own = [x for x in (data.get("photographer"), meta.get("XMP:Credit"),
                       meta.get("AVAIL:Photographer")) if not _blank(x)]
    own += [m.strip() for m in CAPTION_CREDIT_RE.findall(str(data.get("description") or ""))]
    partners = sorted({m.group(0) for x in own + [" ".join(data.get("keywords") or [])]
                       for m in PARTNER_RE.finditer(str(x))}, key=str.lower)
    third = next((x for x in own if not _names_nasa(x)), None)
    named = next((x.strip() for x in own if _names_nasa(x)), None)
    if third and not named:
        return None, third.strip(), partners
    if named and re.match(r"^\s*nasa\b", named, re.I):
        return SPACES.sub(" ", named.replace("/ ", "/")), None, partners
    centre = str(centre or "").strip().upper()
    return NASA_CENTRES.get(centre) or (f"NASA/{centre}" if centre else "NASA"), None, partners


# --------------------------------------------------------------------------
# NASA Image and Video Library
# --------------------------------------------------------------------------

def nasa_search(http, query):
    """-> the search's items (first page, up to 100)."""
    data = http.json(NASA_SEARCH, params={"q": query, "media_type": "video"})
    return list(((data or {}).get("collection") or {}).get("items") or [])


def _nasa_files(manifest):
    """collection.json (a list of URLs, or the asset endpoint's
    {collection: {items: [{href}]}}) -> {rendition: url} of the mp4s, and the
    metadata.json URL."""
    if isinstance(manifest, dict):
        manifest = [i.get("href") for i in ((manifest.get("collection") or {}).get("items") or [])]
    files, meta = {}, None
    for url in manifest or []:
        url = str(url or "")
        m = re.search(r"~([a-z]+)\.mp4$", url)
        if m:
            files.setdefault(m.group(1), url)
        elif url.endswith("/metadata.json"):
            meta = url
    return files, meta


def pick_rendition(http, files, max_bytes=MAX_DOWNLOAD_BYTES):
    """-> (rendition, url, bytes, media_type, tried) - the first of
    NASA_RENDITIONS that answers and fits under `max_bytes`, or Nones."""
    tried = []
    for name in NASA_RENDITIONS:
        if name not in files:
            continue
        url = _quote_url(files[name])
        status, size, ctype = http.head(url)
        tried.append({"rendition": name, "status": status, "bytes": size})
        if status != 200 or (size is not None and size > max_bytes):
            continue
        return name, url, size, (ctype or "video/mp4").split(";")[0].strip(), tried
    return None, None, None, None, tried


def nasa_record(item, http, origins, max_bytes=MAX_DOWNLOAD_BYTES):
    """One search item -> (record, None) or (None, skip_reason). Spends the
    manifest, metadata and HEAD calls."""
    data = ((item or {}).get("data") or [{}])[0]
    nasa_id = data.get("nasa_id")
    if not nasa_id:
        return None, "no nasa_id"
    centre = str(data.get("center") or "").strip()
    origin = "nasa_jpl" if centre.upper() == "JPL" and "nasa_jpl" in origins else (
        "nasa" if "nasa" in origins else ("nasa_jpl" if centre.upper() == "JPL" else None))
    if origin is None:
        return None, f"centre {centre!r} is not an origin this channel lists"
    try:
        files, meta_url = _nasa_files(http.json(_quote_url(item["href"])))
    except (ArchiveError, KeyError, ValueError) as exc:
        return None, f"no manifest: {exc}"
    if not files:
        return None, "the manifest lists no mp4"
    meta = {}
    if meta_url:
        try:
            meta = http.json(_quote_url(meta_url)) or {}
        except (ArchiveError, ValueError):
            meta = {}
    rendition, url, size, mime, tried = pick_rendition(http, files, max_bytes)
    if url is None:
        seen = ", ".join(f"{t['rendition']} HTTP {t['status']} {t['bytes']} B" for t in tried)
        return None, f"no rendition answers under {max_bytes} bytes ({seen or 'none listed'})"
    credit, third, partners = nasa_credit(data, meta, centre)
    width, height = size_from_meta(meta)
    caveats = list(NASA_CAVEATS)
    if partners:
        caveats.append(f"partners named ({', '.join(partners)}): their material may be inside "
                       f"the cut - not NASA's to give (footage-origin.json, CF-0564)")
    if third:
        caveats.append(f"the item's own credit is {third!r}, not NASA - that owner's material")
    licence_name = (NASA_LICENCE if not third
                    else f"credit {third} (third-party material inside NASA media)")
    keywords = [str(k) for k in data.get("keywords") or [] if str(k).strip()]
    return {
        "video_id": f"nasa:{nasa_id}",
        "kind": KIND,
        # NASA titles are often file names ("ARTEMIS II CREW TEASER_30"):
        # the underscores read as spaces, so a word in them is a word
        "title": str(data.get("title") or nasa_id).replace("_", " ").strip(),
        "description": str(data.get("description") or "")[:500],
        "channel_title": f"NASA Image and Video Library ({centre or 'NASA'})",
        "channel_id": None,
        "published_at": data.get("date_created"),
        "duration_seconds": duration_from_meta(meta),
        "view_count": None,
        "facets": [NASA],
        "yt_license": None,
        "keywords": keywords,
        "licence_short_name": licence_name,
        "licence_non_free": False,
        "licence_read_from": ("a NASA item (NASA's media guidelines: not subject to copyright "
                              "in the US) - the library carries no per-file licence"
                              if not third else
                              "the item's own credit names a non-NASA owner"),
        "licence_url": None,
        "credit": credit,
        "source_url": NASA_DETAILS.format(nasa_id=urllib.parse.quote(nasa_id, safe="")),
        "download_url": url,
        "media_type": mime,
        "bytes": size,
        "archive_origin": origin,
        "archive_official": True,
        # the picture size is the original's (metadata.json); the rendition
        # taken may be smaller (`~large`, `~medium`)
        "archive": {"name": NASA, "id": nasa_id, "rendition": rendition, "renditions_tried": tried,
                    "orig_width": width, "orig_height": height, "centre": centre or None,
                    "caveats": caveats},
    }, None


# --------------------------------------------------------------------------
# Wikimedia Commons
# --------------------------------------------------------------------------

COMMONS_EXTMETA = ("LicenseShortName|LicenseUrl|Artist|Credit|NonFree|UsageTerms|"
                   "ImageDescription|AttributionRequired")


def commons_search(http, query, limit=MAX_RESULTS * 2):
    """-> the File pages of one search, in the search's own order."""
    data = http.json(COMMONS_API, params={
        "action": "query", "format": "json", "formatversion": "2",
        "generator": "search", "gsrnamespace": "6", "gsrsearch": f"{query} filetype:video",
        "gsrlimit": str(limit), "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata",
        "iiextmetadatafilter": COMMONS_EXTMETA})
    pages = list((((data or {}).get("query") or {}).get("pages")) or [])
    return sorted(pages, key=lambda p: p.get("index") or 0)


HREF_RE = re.compile(r'href="([^"]+)"')


def artist_credit(raw):
    """Commons' Artist field -> the credit line it gives: its text with the
    HTML stripped, or - when the text is only a footnote mark ('[1]', an
    autonumbered link to the author's page) - that link, as the file page
    shows it. None when it gives neither."""
    text = strip_html(raw)
    if text and re.search(r"[^\W\d_]{2,}", text):
        return text
    m = HREF_RE.search(str(raw or ""))
    if m:
        href = html.unescape(m.group(1))
        return ("https:" + href) if href.startswith("//") else href
    return None


def _em(extmeta, key):
    return ((extmeta or {}).get(key) or {}).get("value")


def _truthy(value):
    return str(value or "").strip().lower() in ("true", "1", "yes")


def commons_title(title):
    """'File:Artemis II Launch 2026.webm' -> 'Artemis II Launch 2026'."""
    t = re.sub(r"^File:", "", str(title or ""))
    return re.sub(r"\.[A-Za-z0-9]{2,5}$", "", t).replace("_", " ").strip()


def commons_record(page, origins, max_bytes=MAX_DOWNLOAD_BYTES):
    """One File page -> (record, None) or (None, skip_reason). No call."""
    if "wikimedia_commons" not in origins:
        return None, "the channel does not list wikimedia_commons"
    info = ((page or {}).get("imageinfo") or [{}])[0]
    em = info.get("extmetadata") or {}
    mime = info.get("mime")
    # an Ogg Theora file is `application/ogg`; a picture size tells it from audio
    if not (str(mime or "").startswith("video/") or (
            mime == "application/ogg" and (info.get("width") or 0) > 0)):
        return None, f"not a video ({mime})"
    size = info.get("size")
    if isinstance(size, int) and size > max_bytes:
        return None, f"{size} bytes, over the {max_bytes}-byte ceiling of a direct download"
    url = info.get("url")
    if not url:
        return None, "no file URL"
    artist = artist_credit(_em(em, "Artist"))
    credit_line = strip_html(_em(em, "Credit"))
    credit = artist or credit_line
    width, height = info.get("width"), info.get("height")
    title = commons_title(page.get("title"))
    caveats = []
    if credit and re.match(r"^uploaded by\b", credit, re.I):
        caveats.append(f"the Artist field names only the uploader ({credit!r}) - the file "
                       f"page's source line says whose footage it is")
    if not credit:
        caveats.append("no Artist and no Credit on the file - no credit line to print")
    elif artist and artist.startswith("http"):
        caveats.append(f"the Artist field is only a link - the credit is that link ({artist})")
    if re.search(r"\b360\s*(°|deg|degree)?", title, re.I) or (
            isinstance(width, int) and isinstance(height, int) and height and width == 2 * height
            and width >= 3840):
        caveats.append("360° (equirectangular) video - not a flat picture")
    duration = info.get("duration")
    return {
        "video_id": f"commons:{page.get('pageid')}",
        "kind": KIND,
        "title": title,
        "description": (strip_html(_em(em, "ImageDescription")) or "")[:500],
        "channel_title": "Wikimedia Commons" + (f": {credit[:80]}" if credit else ""),
        "channel_id": None,
        "published_at": None,
        "duration_seconds": round(float(duration), 3) if isinstance(duration, (int, float))
        and duration > 0 else None,
        "view_count": None,
        "facets": [COMMONS],
        "yt_license": None,
        "keywords": [],
        "licence_short_name": strip_html(_em(em, "LicenseShortName")) or "",
        "licence_non_free": _truthy(_em(em, "NonFree")),
        "licence_read_from": "the file's own licence on Commons (extmetadata LicenseShortName)",
        "licence_url": strip_html(_em(em, "LicenseUrl")),
        "credit": credit,
        "source_url": info.get("descriptionurl"),
        "download_url": _quote_url(url),
        "media_type": mime,
        "bytes": size if isinstance(size, int) else None,
        "archive_origin": "wikimedia_commons",
        "archive_official": False,
        "archive": {"name": COMMONS, "id": page.get("pageid"), "rendition": "original",
                    "width": width, "height": height, "file_title": page.get("title"),
                    "source_credit": credit_line,
                    "usage_terms": strip_html(_em(em, "UsageTerms")),
                    "attribution_required": _truthy(_em(em, "AttributionRequired")),
                    "caveats": caveats},
    }, None


# --------------------------------------------------------------------------
# one topic
# --------------------------------------------------------------------------

def _named(record, forms):
    field, _ = topic_relevance.names_work(record, forms)
    return field is not None


def topic_archive(title_ref, http, config, max_results=MAX_RESULTS,
                  max_bytes=MAX_DOWNLOAD_BYTES):
    """-> the archive signal of one topic. A topic that is not a story, or a
    channel without archive origins, gets an empty signal saying why."""
    ref = title_ref if isinstance(title_ref, dict) else {"name": title_ref}
    head = {"source": SOURCE, "query": ref.get("name"), "facets_used": [], "searches": 0,
            "videos": [], "skipped": [], "archive_read": {}}
    archives = archive_origins(config)
    if not archives:
        head["not_searched"] = ("the channel's footage-origin.json names no archive origin "
                                "(nasa / nasa_jpl / wikimedia_commons with found_by archive_api)")
        return head
    if not topic_relevance.is_story(ref):
        head["not_searched"] = ("not a story topic (title_ref.type / subjects, CF-0662) - "
                                "the archives are asked for a story's subjects only")
        return head
    forms = topic_relevance.story_forms(ref)
    queries = queries_of(ref)
    if not queries:
        head["not_searched"] = "the story has no form to ask an archive with"
        return head
    seen = set()
    for archive, origins in archives.items():
        read = {"queries": queries, "hits": 0, "named": 0, "kept": 0, "errors": []}
        head["archive_read"][archive] = read
        looked = 0
        for q in queries:
            try:
                items = nasa_search(http, q) if archive == NASA else commons_search(http, q)
            except Exception as exc:  # noqa: BLE001 - one archive down is a note, not a stop
                read["errors"].append(f"{q!r}: {exc}")
                continue
            read["hits"] += len(items)
            for item in items:
                if looked >= max_results:
                    break
                if archive == NASA:
                    d = ((item or {}).get("data") or [{}])[0]
                    key, probe = f"nasa:{d.get('nasa_id')}", {
                        "title": d.get("title"), "description": d.get("description"),
                        "channel_title": "NASA"}
                else:
                    key, probe = f"commons:{item.get('pageid')}", {
                        "title": commons_title(item.get("title")),
                        "description": strip_html(_em(((item.get("imageinfo") or [{}])[0])
                                                      .get("extmetadata"), "ImageDescription")),
                        "channel_title": "Wikimedia Commons"}
                if key in seen:
                    continue
                seen.add(key)
                if not _named(probe, forms):
                    continue
                read["named"] += 1
                looked += 1
                rec, why = (nasa_record(item, http, origins, max_bytes) if archive == NASA
                            else commons_record(item, origins, max_bytes))
                if rec is None:
                    head["skipped"].append({"video_id": key, "title": probe.get("title"),
                                            "reason": why})
                    continue
                read["kept"] += 1
                head["videos"].append(rec)
    return head


def batch_story_topics(batch, wanted=()):
    for topic in (batch or {}).get("topics") or []:
        tid = topic.get("topic_id")
        if wanted and tid not in wanted:
            continue
        yield tid, dict(topic.get("title_ref") or {})


def summary_line(tid, sig):
    parts = [f"{a}: {r['kept']} kept of {r['named']} naming it ({r['hits']} hits"
             + (f", {len(r['errors'])} errors" if r["errors"] else "") + ")"
             for a, r in (sig.get("archive_read") or {}).items()]
    return f"archive-footage {tid}: " + ("; ".join(parts) or sig.get("not_searched") or "-")


@runlog.script("trend-hunter", "archive-footage", name="fetch_archive_footage.py")
def main(argv=None, http=None):
    import footage_candidates as fc
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("query", nargs="?", help="a story's name, without --batch")
    ap.add_argument("--type", default="science_story",
                    help="without --batch: the story's title_ref.type (default science_story)")
    ap.add_argument("--subject", action="append", help="without --batch: title_ref.subjects")
    ap.add_argument("--batch", help="batch dir or 01-trend-hunter.json: one signal per topic")
    ap.add_argument("--out-dir", help="with --batch: where archive-<topic_id>.json go")
    ap.add_argument("--topic", action="append", help="with --batch: only these topic ids")
    ap.add_argument("--channel", help="the channel (with --batch: the batch's `channel`)")
    ap.add_argument("--max-results", type=int, default=MAX_RESULTS)
    ap.add_argument("--max-bytes", type=int, default=MAX_DOWNLOAD_BYTES)
    args = ap.parse_args(argv)
    batch = path = None
    if args.batch:
        path = fc._batch_path(args.batch)
        batch = json.loads(Path(path).read_text())
    channel = args.channel or (fc._batch_channel(batch) if batch is not None else None)
    try:
        config = footage_origin.load_config(channel)
    except footage_origin.ConfigError as exc:
        print(json.dumps({"error": f"footage origin: {exc}"}), file=sys.stderr)
        return 2
    if not archive_origins(config):
        print(json.dumps({"channel": config["channel"], "searches": 0, "topics": [],
                          "not_searched": "the channel names no archive origin - nothing "
                                          "to ask, nothing written"}, indent=2))
        return 0
    http = http or Http()
    if batch is not None:
        out_dir = Path(args.out_dir or Path(path).parent / "work" / "archive")
        out_dir.mkdir(parents=True, exist_ok=True)
        summary = []
        for tid, ref in batch_story_topics(batch, set(args.topic or [])):
            sig = topic_archive(ref, http, config, args.max_results, args.max_bytes)
            target = out_dir / f"archive-{tid}.json"
            target.write_text(json.dumps(sig, ensure_ascii=False, indent=2))
            print(summary_line(tid, sig), file=sys.stderr)
            summary.append({"topic_id": tid, "file": str(target), "candidates": len(sig["videos"]),
                            "not_searched": sig.get("not_searched"),
                            "archive_read": sig["archive_read"]})
        print(json.dumps({"searches": 0, "http_calls": getattr(http, "calls", None),
                          "topics": summary}, ensure_ascii=False, indent=2))
        return 0
    if not args.query:
        ap.error("a story's name, or --batch")
    ref = {"name": args.query, "type": args.type, "subjects": list(args.subject or [])}
    sig = topic_archive(ref, http, config, args.max_results, args.max_bytes)
    print(summary_line(args.query, sig), file=sys.stderr)
    print(json.dumps(sig, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
