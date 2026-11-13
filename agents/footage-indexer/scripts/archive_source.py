"""CF-0665 (FI-1 of the root's docs/science-footage.md): an archive file -
the NASA Image and Video Library or Wikimedia Commons - fetched directly.

The Trend Hunter (TH-3, `scripts/fetch_archive_footage.py`) offers a science
story's archive files as footage candidates beside the YouTube ones:

    evidence.footage_candidates[] = {video_id: "nasa:<nasa_id>" | "commons:<pageid>",
        download_url (https), media_type (video/mp4 | video/webm | application/ogg),
        bytes (<= 500 MB), duration_seconds (or null), source_url (the file's page),
        credit, licence (CF-0662), footage_origin, origin (official | unknown),
        archive {name, id, rendition, caveats, ...}, ...}

None of it goes through yt-dlp: no player client, no session state.
What this module does instead, for `fetch_footage.py --archive-json`:

  * **ids** - `nasa:<id>` / `commons:<pageid>` is the Trend Hunter's name; on
    disk, in the cache index and in every report of this stage the source is
    its *file id* `nasa-<id>` / `commons-<pageid>` (`file_id()`): no `:` (the
    `<source>:<shot>` keys of the Video Editor split on it) and no `/`, and the
    same `<id>.mp4` / `<id>.shots.json` naming every reader already assumes.
    `ingest_batch.walk_state()` translates once, at the walk's entrance; the
    Trend Hunter's id rides along as `candidate_id`.
  * **the licence, read again** (`recheck()`) - Commons: the file page's
    `extmetadata` (`LicenseShortName`, `NonFree`, `Artist`) judged by the
    root's `licence_of` against the channel's lists; NASA: the item's
    `metadata.json`, whose credit says whether the item is still NASA's own.
    A licence that is not the one the candidate was judged on is
    `licence_changed`, with both versions; a re-read that does not answer
    decides nothing (recorded, the download goes on - the candidate was judged
    on the archive's own word when it was found).
  * **the download** (`download()`) - one HTTP(S) stream with a size ceiling
    (the candidate's own 500 MB), a whole-download time ceiling, the
    `Content-Length` and the `Content-Type` checked, into the per-fetch temp
    dir `fetch_footage.sweep_partials()` already cleans.
  * **mp4** (`to_mp4()`) - yt-dlp is asked for `--merge-output-format mp4`, so
    every source in the pool has always been `<id>.mp4` and every reader (the
    index, the Editor, `pool_release`) expects it. WebM and Ogg are re-encoded
    by ffmpeg (H.264 + AAC); an mp4 taller than the height ceiling yt-dlp is
    held to (`--max-height`, 1080) is scaled down the same way; any other mp4
    is moved as it is.

Binaries come from the environment (`FFMPEG` / `FFPROBE`, else PATH), never a
Homebrew keg (CF-0654). The network is reached through one `opener` seam
(`urllib.request.urlopen` by default), so a test hands in a stand-in and never
touches it.
"""
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from html import unescape
from pathlib import Path

ARCHIVES = {"nasa": "nasa_images", "commons": "wikimedia_commons"}
CANDIDATE_ID_RE = re.compile(r"^(nasa|commons):(.+)$")
FILE_ID_RE = re.compile(r"^(nasa|commons)-([A-Za-z0-9_-]+)$")
UNSAFE = re.compile(r"[^A-Za-z0-9_-]")

# The Trend Hunter's own ceiling (fetch_archive_footage.MAX_DOWNLOAD_BYTES): a
# file larger than this is never offered, so one larger on the wire is not
# the file that was offered.
MAX_BYTES = 500 * 1024 * 1024
# The whole download, start to last byte. 500 MB at the slowest rate measured
# from here (Commons, ~2 MB/s) is ~250 s; four times that is a stalled server.
TIMEOUT_SECONDS = 1200
READ_TIMEOUT_SECONDS = 60       # one socket read
API_TIMEOUT_SECONDS = 30
CHUNK = 1024 * 1024
MAX_HEIGHT = 1080

MEDIA_TYPES = {"video/mp4": ".mp4", "video/webm": ".webm", "application/ogg": ".ogv",
               "video/ogg": ".ogv"}
# What a CDN may say for any file; the container is then ffprobe's to tell.
GENERIC_TYPES = ("application/octet-stream", "binary/octet-stream")

COMMONS_API = "https://commons.wikimedia.org/w/api.php"
COMMONS_RECHECK = "LicenseShortName|NonFree|Artist"
NASA_LICENCE = "PD-USGov-NASA"
NASA_WORDS = ("nasa", "jpl", "caltech")
# The Trend Hunter's own credit fields of metadata.json (fetch_archive_footage.
# nasa_credit) - read the same way, so the re-read answers the same question.
NASA_CREDIT_KEYS = ("XMP:Credit", "AVAIL:Photographer")
# Wikimedia asks for a descriptive User-Agent (meta.wikimedia.org User-Agent policy).
USER_AGENT = ("ExampleFootageindexer/1.0 (footage-indexer fetch_footage.py; archive "
              "footage download for a science channel) python-urllib")

LICENCE_CHANGED_CODE = "licence_changed"

HTML_TAG = re.compile(r"<[^>]+>")
SPACES = re.compile(r"\s+")


class ArchiveError(RuntimeError):
    """A download or a probe that did not give a usable file."""


# ---------------------------------------------------------------------------
# ids
# ---------------------------------------------------------------------------

def archive_of(vid):
    """'nasa' / 'commons' for an archive id in either form, else None."""
    s = str(vid or "")
    m = CANDIDATE_ID_RE.match(s) or FILE_ID_RE.match(s)
    return m.group(1) if m else None


def is_archive(vid):
    return archive_of(vid) is not None


def file_id(vid):
    """The id a source is kept under: `nasa:<id>` -> `nasa-<id>` (every
    character outside [A-Za-z0-9_-] made `_`); a file id or a YouTube id is
    returned as it is."""
    s = str(vid or "")
    m = CANDIDATE_ID_RE.match(s)
    if not m:
        return s
    return f"{m.group(1)}-{UNSAFE.sub('_', m.group(2))}"


def archive_item_id(record):
    """The archive's own id of the item (NASA's nasa_id, Commons' pageid)."""
    rec = record if isinstance(record, dict) else {}
    arch = rec.get("archive") if isinstance(rec.get("archive"), dict) else {}
    if arch.get("id") not in (None, ""):
        return str(arch["id"])
    m = CANDIDATE_ID_RE.match(str(rec.get("candidate_id") or rec.get("video_id") or ""))
    return m.group(2) if m else None


# ---------------------------------------------------------------------------
# binaries and the network seam
# ---------------------------------------------------------------------------

def ffmpeg_bin():
    return os.environ.get("FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def ffprobe_bin():
    return os.environ.get("FFPROBE") or shutil.which("ffprobe") or "ffprobe"


def _request(url):
    return urllib.request.Request(url, headers={"User-Agent": USER_AGENT})


def http_json(url, params=None, opener=None, timeout=API_TIMEOUT_SECONDS):
    """GET `url` (with `params`) -> the decoded JSON. Raises ArchiveError."""
    opener = opener or urllib.request.urlopen
    if params:
        url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
    try:
        with opener(_request(url), timeout=timeout) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if status != 200:
                raise ArchiveError(f"{url}: HTTP {status}")
            return json.loads(resp.read().decode("utf-8"))
    except ArchiveError:
        raise
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise ArchiveError(f"{url}: {type(exc).__name__}: {exc}") from None


# ---------------------------------------------------------------------------
# the licence, read again
# ---------------------------------------------------------------------------

def strip_html(text):
    return SPACES.sub(" ", unescape(HTML_TAG.sub(" ", str(text or "")))).strip()


def _truthy(value):
    return str(value or "").strip().lower() in ("true", "1", "yes")


def _norm(name):
    return " ".join(re.findall(r"[0-9a-z]+", str(name or "").lower()))


def _names_nasa(text):
    w = set(re.findall(r"[a-z]+", str(text or "").lower()))
    return any(n in w for n in NASA_WORDS)


def _was(record):
    block = record.get("licence") if isinstance(record.get("licence"), dict) else {}
    return {"short_name": block.get("short_name"), "licence": block.get("id"),
            "accepted": block.get("accepted"), "credit": record.get("credit")}


def recheck_commons(record, licences=None, rule=None, opener=None):
    """The Commons file's licence as the file page says it now."""
    out = {"archive": "commons", "read": False, "was": _was(record), "now": None,
           "changed": False, "reason": None, "error": None}
    pageid = archive_item_id(record)
    if not pageid:
        out["error"] = "no pageid on the candidate"
        return out
    try:
        data = http_json(COMMONS_API, {
            "action": "query", "format": "json", "formatversion": "2",
            "pageids": pageid, "prop": "imageinfo", "iiprop": "extmetadata",
            "iiextmetadatafilter": COMMONS_RECHECK}, opener=opener)
        page = ((data.get("query") or {}).get("pages") or [{}])[0]
        if page.get("missing") or page.get("invalid"):
            raise ArchiveError(f"page {pageid} is not on Commons any more")
        em = ((page.get("imageinfo") or [{}])[0]).get("extmetadata") or {}
    except (ArchiveError, AttributeError, IndexError, TypeError) as exc:
        out["error"] = str(exc)
        return out

    def em_value(key):
        return (em.get(key) or {}).get("value") if isinstance(em.get(key), dict) else None

    now = {"short_name": strip_html(em_value("LicenseShortName")) or None,
           "non_free": _truthy(em_value("NonFree")),
           "artist": strip_html(em_value("Artist")) or None}
    was = out["was"]
    if rule is not None and licences:
        v = rule.licence_of(now["short_name"] or "", licences, non_free=now["non_free"])
        now.update(licence=v.get("id"), accepted=bool(v.get("accepted")))
        changed = now["licence"] != was["licence"] or not now["accepted"]
    else:
        # The channel's lists are not at hand: the names themselves.
        now.update(licence=None, accepted=None)
        changed = now["non_free"] or _norm(now["short_name"]) != _norm(was["short_name"])
    out.update(read=True, now=now, changed=bool(changed))
    if changed:
        out["reason"] = (f"the file's licence is now {now['short_name']!r}"
                         + (" (non-free)" if now["non_free"] else "")
                         + f", the candidate was judged on {was['short_name']!r}")
    return out


def nasa_metadata_url(record):
    """`metadata.json` beside the rendition in the item's asset directory
    (`https://images-assets.nasa.gov/video/<id>/<id>~large.mp4` ->
    `.../video/<id>/metadata.json`)."""
    url = str((record or {}).get("download_url") or "")
    if "/" not in url:
        return None
    return url.rsplit("/", 1)[0] + "/metadata.json"


def recheck_nasa(record, opener=None):
    """The NASA item's credit as its `metadata.json` says it now. The item
    stops being NASA's to give when its credit names somebody else and not
    NASA (footage-origin.json: third-party material inside NASA media) - the
    one direction that matters: a candidate judged as NASA's own whose credit
    now names another owner is `changed`."""
    out = {"archive": "nasa", "read": False, "was": _was(record), "now": None,
           "changed": False, "reason": None, "error": None}
    url = nasa_metadata_url(record)
    if not url:
        out["error"] = "no download_url to find metadata.json beside"
        return out
    try:
        meta = http_json(url, opener=opener)
        if not isinstance(meta, dict):
            raise ArchiveError(f"{url}: not an object")
    except ArchiveError as exc:
        out["error"] = str(exc)
        return out
    own = [strip_html(meta.get(k)) for k in NASA_CREDIT_KEYS if strip_html(meta.get(k))]
    third = next((c for c in own if not _names_nasa(c)), None)
    named = next((c for c in own if _names_nasa(c)), None)
    now_third = bool(third and not named)
    was = out["was"]
    was_nasa = _norm(was["short_name"]) == _norm(NASA_LICENCE)
    now = {"short_name": NASA_LICENCE if not now_third
           else f"credit {third} (third-party material inside NASA media)",
           "credit": named or third, "third_party": third if now_third else None}
    out.update(read=True, now=now, changed=bool(was_nasa and now_third))
    if out["changed"]:
        out["reason"] = (f"the item's credit now names {third!r} and not NASA - "
                         f"third-party material; the candidate was judged as "
                         f"{was['short_name']!r}")
    return out


def recheck(record, licences=None, rule=None, opener=None):
    """-> the re-read of the candidate's licence (see the module doc)."""
    kind = archive_of((record or {}).get("candidate_id") or (record or {}).get("video_id"))
    if kind == "commons":
        return recheck_commons(record, licences=licences, rule=rule, opener=opener)
    if kind == "nasa":
        return recheck_nasa(record, opener=opener)
    return {"archive": kind, "read": False, "changed": False,
            "error": "not an archive candidate"}


# ---------------------------------------------------------------------------
# the download
# ---------------------------------------------------------------------------

def suffix_for(media_type, url=""):
    mt = str(media_type or "").split(";")[0].strip().lower()
    if mt in MEDIA_TYPES:
        return MEDIA_TYPES[mt]
    ext = Path(urllib.parse.urlparse(str(url)).path).suffix.lower()
    return ext if ext in (".mp4", ".webm", ".ogv", ".ogg") else ".bin"


def download(url, dest, max_bytes=MAX_BYTES, timeout=TIMEOUT_SECONDS, opener=None,
             clock=time.monotonic):
    """Stream `url` into `dest`. -> {bytes, content_type, content_length,
    seconds}. Raises ArchiveError - and leaves `dest` for the caller's cleanup
    - on a status other than 200, a type that is not a video, a length over
    `max_bytes` (announced or counted), a download longer than `timeout`
    seconds, or fewer bytes than `Content-Length` announced."""
    if not str(url).lower().startswith(("https://", "http://")):
        raise ArchiveError(f"not an HTTP(S) address: {url!r}")
    opener = opener or urllib.request.urlopen
    t0 = clock()
    try:
        resp = opener(_request(url), timeout=READ_TIMEOUT_SECONDS)
    except urllib.error.HTTPError as exc:
        raise ArchiveError(f"HTTP {exc.code} for {url}") from None
    except (urllib.error.URLError, OSError) as exc:
        raise ArchiveError(f"{url}: {type(exc).__name__}: {exc}") from None
    total = 0
    with resp:
        status = getattr(resp, "status", None) or resp.getcode()
        if status != 200:
            raise ArchiveError(f"HTTP {status} for {url}")
        headers = resp.headers
        ctype = str(headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype not in MEDIA_TYPES and ctype not in GENERIC_TYPES:
            raise ArchiveError(f"{url} answered {ctype or 'no Content-Type'}, not a video")
        raw_len = str(headers.get("Content-Length") or "").strip()
        clen = int(raw_len) if raw_len.isdigit() else None
        if clen is not None and clen > max_bytes:
            raise ArchiveError(f"{url} is {clen} bytes, over the {max_bytes}-byte ceiling")
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        with open(dest, "wb") as fh:
            while True:
                try:
                    chunk = resp.read(CHUNK)
                except (OSError, ValueError) as exc:
                    raise ArchiveError(f"{url}: read failed after {total} bytes: {exc}") from None
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise ArchiveError(f"{url} passed the {max_bytes}-byte ceiling "
                                       f"mid-download")
                fh.write(chunk)
                if clock() - t0 > timeout:
                    raise ArchiveError(f"{url} took over {timeout} s ({total} bytes "
                                       f"so far) - stopped")
    if clen is not None and total != clen:
        raise ArchiveError(f"{url}: {total} bytes came, Content-Length said {clen}")
    if total == 0:
        raise ArchiveError(f"{url}: an empty answer")
    return {"bytes": total, "content_type": ctype, "content_length": clen,
            "seconds": round(clock() - t0, 2)}


def probe(path, runner=subprocess.run):
    """-> {duration, width, height, vcodec, format} of the first video stream,
    or None when ffprobe cannot read the file or it holds no picture."""
    try:
        out = runner([ffprobe_bin(), "-v", "error", "-print_format", "json",
                      "-show_format", "-show_streams", str(path)],
                     capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if out.returncode != 0:
        return None
    try:
        data = json.loads(out.stdout or "{}")
    except ValueError:
        return None
    video = next((s for s in data.get("streams") or []
                  if s.get("codec_type") == "video"
                  and not (s.get("disposition") or {}).get("attached_pic")), None)
    if video is None:
        return None
    fmt = data.get("format") or {}
    try:
        duration = float(fmt.get("duration") or video.get("duration") or 0) or None
    except (TypeError, ValueError):
        duration = None
    return {"duration": duration, "width": video.get("width"), "height": video.get("height"),
            "vcodec": video.get("codec_name"), "format": fmt.get("format_name")}


def needs_encode(path, info, max_height=MAX_HEIGHT):
    """Whether `path` must go through ffmpeg to be a pool mp4."""
    fmt = str((info or {}).get("format") or "")
    is_mp4 = Path(path).suffix.lower() == ".mp4" or "mp4" in fmt.split(",")
    tall = bool((info or {}).get("height") and max_height
                and int(info["height"]) > int(max_height))
    return not is_mp4 or tall


def to_mp4(src, dst, info=None, max_height=MAX_HEIGHT, runner=subprocess.run,
           timeout=1800):
    """`src` -> `dst` (an mp4). Re-encoded (H.264 + AAC, at most `max_height`
    high) when `needs_encode()`, else moved. Returns whether it re-encoded.
    Raises ArchiveError when ffmpeg does not leave a non-empty `dst`."""
    src, dst = Path(src), Path(dst)
    if not needs_encode(src, info, max_height):
        shutil.move(str(src), str(dst))
        return False
    scale = f"scale=-2:'min({int(max_height)},ih)'" if max_height else "scale=-2:ih"
    cmd = [ffmpeg_bin(), "-y", "-nostdin", "-v", "error", "-i", str(src),
           "-map", "0:v:0", "-map", "0:a:0?", "-vf", scale + ",format=yuv420p",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
           "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)]
    try:
        out = runner(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ArchiveError(f"ffmpeg did not finish: {exc}") from None
    if out.returncode != 0 or not dst.is_file() or dst.stat().st_size == 0:
        tail = (out.stderr or "").strip().splitlines()[-1:] or ["no stderr"]
        raise ArchiveError(f"ffmpeg exit {out.returncode} turning {src.name} into mp4: "
                           f"{tail[0]}")
    src.unlink(missing_ok=True)
    return True
