#!/usr/bin/env python3
"""CF-0142: fill the underlay library shared/inserts/loops/ from Pixabay.

    python3 scripts/fetch_pixabay_loops.py                       # dry run: the plan
    python3 scripts/fetch_pixabay_loops.py --fetch               # download + index entries
    python3 scripts/fetch_pixabay_loops.py --fetch --media-dir /path/to/working-copy/shared/inserts/loops
    python3 scripts/index_inserts.py --kind loop                 # then: CLIP vectors

Why Pixabay, and under what decision
------------------------------------
The grill of 2026-10-07 (Q13) named Pixabay as the source of the "face of
the channel" libraries (loops, sounds, music). Pixabay's robots.txt
disallows ClaudeBot from `/` and `*` from `/api/`, which closes a source
under the rule of 2026-10-08 (CF-0557). On 2026-10-11 the user answered
question 20 "продолжаем работать с Pixabay как есть": an exception to that
rule for Pixabay only, through the API with the user's key and within the
API's own terms. USER_DECISION below is that reference; it is written into
every entry's `notes`.

The API's terms this script keeps (https://pixabay.com/api/docs/):
  * at most 100 requests per 60 s - a sliding window of API_MAX_PER_WINDOW
    calls, and a stop until X-RateLimit-Reset when the server says none
    are left;
  * results cached for 24 h - every search answer is stored under
    --cache-dir and reused for CACHE_TTL_S, a dry run included, so a dry
    run followed by --fetch asks the API once;
  * no systematic mass downloads - one curated batch (TOPICS, at most
    MAX_BATCH files a run), one download at a time with a pause;
  * no permanent hotlinking - files are downloaded and stored.

The licence is the Pixabay Content License: free commercial use and
modification, no attribution required, no standalone redistribution
(a muted loop under our own composition is not standalone). It is written
as `licence` of every entry; `rights_holder` is the Pixabay contributor
(the blacklist reads it), `source_url` the clip's Pixabay page,
`download_url` the file the API gave (scripts/fetch_inserts.py restores a
missing file from it - with its sound track; the underlay mutes it anyway).

What a loop is (CF-0014, inserts/POLICY.md): a silent, "satisfying" second
plane under the main content. The underlay takes a band
SECONDARY_HEIGHT = 0.28 of the 1080x1920 frame (agents/video-editor,
underlay_layer.py) - a landscape strip - so a clip qualifies when its
chosen rendition is landscape and at least MIN_WIDTH x MIN_HEIGHT, it is
MIN_SECONDS..MAX_SECONDS long, and none of its tags names a person or a
brand (people under the main content compete with it; a brand makes the
licence's trademark clause apply). The sound track is removed on download
(ffmpeg -an, stream copy), so the file itself is silent.

Media and index may live apart: `--media-dir` is where files go (the
working copy's library, which git does not track), the index is the one
under `--root` (a version worktree's, which git does track); when the two
folders differ, an absolute symlink to each file is placed beside the index,
the same shape `scripts/agents sync` links `shared/inserts/*/*` with.

The key is PIXABAY_API_KEY from the environment, else from `<repo>/.env`.
It is never printed, logged or written: it goes into the request only, and
errors are reported without the URL.

Stdlib only (plus ffmpeg/ffprobe on PATH for --fetch).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "shared" / "inserts"))
import inserts_lib as lib  # noqa: E402

KIND = "loop"
API_URL = "https://pixabay.com/api/videos/"
KEY_ENV = "PIXABAY_API_KEY"
USER_AGENT = ("shorts-content-factory/CF-0142 fetch_pixabay_loops "
              "(https://github.com/example-user/shorts-content-factory)")
LICENCE = "Pixabay Content License (https://pixabay.com/service/license-summary/)"
USER_DECISION = ("source used under the user's decision of 2026-10-11 (question 20, "
                 "\"продолжаем работать с Pixabay как есть\"): an exception for Pixabay "
                 "only to the robots rule of 2026-10-08 (CF-0557), API with a key within "
                 "its terms - CF-0142")

API_MAX_PER_WINDOW = 90          # under Pixabay's 100 / 60 s, with margin
API_WINDOW_S = 60.0
CACHE_TTL_S = 24 * 3600          # "Requests must be cached for 24 hours."
DOWNLOAD_DELAY_S = 1.5
TIMEOUT_S = 120
MAX_BYTES = 60 * 1024 * 1024     # under fetch_inserts.MAX_BYTES (64 MB): restorable
MAX_BATCH = 30                   # one curated batch, never a mass download
MIN_WIDTH, MIN_HEIGHT = 1920, 1080
MIN_SECONDS, MAX_SECONDS = 6, 60
RENDITIONS = ("medium", "large", "small", "tiny")   # medium is 1080p for 4K sources
DEFAULT_CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") \
    / "shorts-content-factory" / "pixabay"

# Tags that make a clip unfit for the second plane: a person (competes with
# the main content; recognisable people are the licence's other clause) or
# a brand (the licence's trademark clause).
EXCLUDED_TAGS = {
    "woman", "women", "man", "men", "girl", "boy", "people", "person", "child",
    "children", "kid", "kids", "face", "portrait", "model", "baby", "family",
    "couple", "selfie", "dancer", "dance",
    "logo", "brand", "advertising", "text", "typography", "christmas", "flag",
    # A generated "microscope" or "nebula" passes for a real one; decoration
    # or not, the factory does not show a fake as a document.
    "ai generated", "ai-generated", "generative ai",
}

# Clips a person looked at and turned down (frame check of the fetched
# batch); a re-run never takes them again. id -> why.
EXCLUDED_IDS = {
    27803: "2026-10-11 frame check: yellow ink on black reads as fire, not ink in water",
    27800: "2026-10-11 frame check: the same series, flame-like shapes half the clip",
}

# The curated batch. `description` is written by a person and is what a text
# query is matched against (inserts_lib schema); the clip's own Pixabay tags
# are added to `tags`. `take` clips per topic, best by popularity first.
# Pixabay's search is loose ("slime" finds snails), so a clip counts for a
# topic only when one of its tags contains a `require` term and none
# contains an `avoid` term - that is what keeps the description true.
TOPICS = [
    {"slug": "kinetic-sand", "query": "kinetic sand", "take": 2, "require": ["kinetic sand"],
     "description": "Kinetic sand being cut, pressed or crumbled in close-up - a "
                    "classic satisfying loop for the second plane.",
     "tags": ["satisfying", "sand", "asmr", "close-up"]},
    {"slug": "slime", "query": "slime toy", "take": 2, "require": ["slime"],
     "avoid": ["snail", "slug", "nudibranch", "mollusk", "alien", "monster", "character",
               "eyeball"],
     "description": "Colourful slime stretched, poked and folded in close-up - "
                    "a tactile satisfying loop.",
     "tags": ["satisfying", "slime", "asmr", "texture"]},
    {"slug": "paint-pour", "query": "acrylic pouring", "take": 2,
     "require": ["acrylic", "paint"],
     "description": "Paint poured and mixing into swirling colour patterns - a "
                    "slow satisfying loop.",
     "tags": ["satisfying", "paint", "colour", "fluid"]},
    {"slug": "ink-in-water", "query": "ink in water", "take": 1, "require": ["ink"],
     "description": "Ink blooming and curling through clear water - a soft "
                    "abstract loop.",
     "tags": ["satisfying", "ink", "water", "abstract"]},
    {"slug": "domino", "query": "domino", "take": 2, "require": ["domino"],
     "avoid": ["jenga"],
     "description": "Dominoes toppling in a chain - a satisfying cause-and-effect "
                    "loop.",
     "tags": ["satisfying", "domino", "chain reaction"]},
    {"slug": "pottery-wheel", "query": "pottery wheel clay", "take": 2,
     "require": ["pottery"],
     "description": "Clay turning on a hollow's wheel as it takes shape - a calm, "
                    "hypnotic loop.",
     "tags": ["satisfying", "pottery", "clay", "craft"]},
    {"slug": "lava-lamp", "query": "lava lamp", "take": 2, "require": ["lava lamp"],
     "description": "Wax blobs rising and falling in a lava lamp - a slow, "
                    "hypnotic loop.",
     "tags": ["satisfying", "lava lamp", "retro", "hypnotic"]},
    {"slug": "fluid-abstract", "query": "abstract fluid", "take": 2,
     "require": ["fluid"],
     "description": "Abstract fluid shapes flowing and morphing - a colourful "
                    "background loop.",
     "tags": ["abstract", "fluid", "background", "colour"]},
    {"slug": "plexus", "query": "plexus technology", "take": 2, "require": ["plexus"],
     "description": "Glowing points joined by lines drifting through dark space - "
                    "a technology-flavoured abstract loop.",
     "tags": ["abstract", "technology", "network", "background"]},
    {"slug": "nebula", "query": "nebula space", "take": 2, "require": ["nebula"],
     "description": "A slow flight through glowing nebula clouds and stars - a "
                    "space background loop.",
     "tags": ["space", "nebula", "stars", "science"]},
    {"slug": "pov-drive", "query": "pov driving", "take": 2, "require": ["driv"],
     "avoid": ["drone"],
     "description": "A point-of-view drive along a road - the endless-runner "
                    "rhythm of a gameplay loop without anybody's game.",
     "tags": ["pov", "driving", "road", "motion"]},
    {"slug": "roller-coaster", "query": "roller coaster", "take": 2,
     "require": ["roller coaster", "rollercoaster"],
     "description": "A roller coaster racing along its track - a fast motion "
                    "loop.",
     "tags": ["pov", "roller coaster", "ride", "motion"]},
    {"slug": "marble-run", "query": "marble run", "take": 2,
     "require": ["marble run", "marbles"],
     "description": "Marbles rolling down a track or run - a satisfying "
                    "mechanical loop.",
     "tags": ["satisfying", "marble", "mechanical", "toy"]},
    {"slug": "soap-bubbles", "query": "soap bubbles", "take": 2, "require": ["bubble"],
     "description": "Soap bubbles shimmering, drifting or freezing into ice "
                    "crystals - a light, slow loop.",
     "tags": ["satisfying", "bubbles", "colour", "light"]},
    {"slug": "hourglass", "query": "hourglass sand", "take": 2, "require": ["hourglass"],
     "description": "Sand running through an hourglass - a slow, ticking loop.",
     "tags": ["satisfying", "hourglass", "sand", "time"]},
    {"slug": "cells", "query": "cells microscope", "take": 2, "require": ["cell"],
     "description": "Cells or microorganisms moving under a microscope - a "
                    "science background loop.",
     "tags": ["science", "microscope", "cells", "biology"]},
]


# --------------------------------------------------------------------------
# key
# --------------------------------------------------------------------------

def read_env_file(path):
    """KEY=VALUE lines of a .env file (shared/notify.py's reading)."""
    out = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def api_key(environ=None, env_file=None):
    env = os.environ if environ is None else environ
    if env.get(KEY_ENV):
        return env[KEY_ENV]
    key = read_env_file(env_file or REPO / ".env").get(KEY_ENV)
    if not key:
        raise SystemExit(f"{KEY_ENV} is not set (environment or {env_file or REPO / '.env'})")
    return key


# --------------------------------------------------------------------------
# API client: rate window + 24 h cache
# --------------------------------------------------------------------------

class PixabayError(RuntimeError):
    """An API failure, reported without the request URL (it holds the key)."""


def _open(url, timeout=TIMEOUT_S):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=timeout)


class Client:
    def __init__(self, key, cache_dir=DEFAULT_CACHE, clock=time.time, sleep=time.sleep,
                 opener=_open, log=print):
        self._key = key
        self.cache_dir = Path(cache_dir)
        self.clock, self.sleep, self.opener, self.log = clock, sleep, opener, log
        self.calls = deque()
        self.api_calls = 0
        self.cache_hits = 0

    @staticmethod
    def cache_key(params):
        blob = json.dumps(sorted(params.items()), ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:32]

    def _cached(self, params):
        f = self.cache_dir / f"{self.cache_key(params)}.json"
        try:
            rec = json.loads(f.read_text())
        except (OSError, ValueError):
            return None
        if self.clock() - rec.get("fetched_at", 0) > CACHE_TTL_S:
            return None
        return rec.get("response")

    def _store(self, params, response):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        f = self.cache_dir / f"{self.cache_key(params)}.json"
        f.write_text(json.dumps({"fetched_at": self.clock(), "params": params,
                                 "response": response}, ensure_ascii=False))

    def _wait_for_window(self):
        now = self.clock()
        while self.calls and now - self.calls[0] >= API_WINDOW_S:
            self.calls.popleft()
        if len(self.calls) >= API_MAX_PER_WINDOW:
            pause = API_WINDOW_S - (now - self.calls[0]) + 0.5
            self.log(f"  rate window full: pausing {pause:.0f} s")
            self.sleep(pause)

    def search(self, **params):
        """One /api/videos/ search; `params` never include the key, so the
        cache file and every message are key-free."""
        hit = self._cached(params)
        if hit is not None:
            self.cache_hits += 1
            return hit
        self._wait_for_window()
        url = API_URL + "?" + urllib.parse.urlencode({"key": self._key, **params})
        try:
            with self.opener(url) as resp:
                body = resp.read()
                remaining = resp.headers.get("X-RateLimit-Remaining")
                reset = resp.headers.get("X-RateLimit-Reset")
        except urllib.error.HTTPError as exc:
            raise PixabayError(f"Pixabay API answered HTTP {exc.code} for q={params.get('q')!r}") \
                from None
        except (urllib.error.URLError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise PixabayError(f"Pixabay API unreachable for q={params.get('q')!r}: "
                               f"{type(reason).__name__}") from None
        self.calls.append(self.clock())
        self.api_calls += 1
        try:
            response = json.loads(body)
        except ValueError:
            raise PixabayError(f"Pixabay API answered non-JSON for q={params.get('q')!r}") from None
        self._store(params, response)
        if remaining is not None and str(remaining).strip() == "0":
            pause = float(reset or API_WINDOW_S) + 0.5
            self.log(f"  X-RateLimit-Remaining is 0: pausing {pause:.0f} s")
            self.sleep(pause)
        return response


# --------------------------------------------------------------------------
# selection
# --------------------------------------------------------------------------

def hit_tags(hit):
    return [t.strip().lower() for t in str(hit.get("tags", "")).split(",") if t.strip()]


def pick_rendition(hit):
    """The smallest rendition that is landscape and at least MIN_WIDTH x
    MIN_HEIGHT and under MAX_BYTES, as (name, info) - or None."""
    videos = hit.get("videos") or {}
    fits = []
    for name in RENDITIONS:
        v = videos.get(name) or {}
        w, h, size = v.get("width") or 0, v.get("height") or 0, v.get("size") or 0
        if v.get("url") and w >= MIN_WIDTH and h >= MIN_HEIGHT and w >= h \
                and 0 < size <= MAX_BYTES:
            fits.append((w * h, size, name, v))
    if not fits:
        return None
    fits.sort(key=lambda x: (x[0], x[1]))
    return fits[0][2], fits[0][3]


def why_not(hit, topic=None):
    """None when the clip qualifies (for the topic, when given), else why not."""
    tags = hit_tags(hit)
    if topic is not None:
        req, avoid = topic.get("require") or [], topic.get("avoid") or []
        if req and not any(r in t for t in tags for r in req):
            return f"no tag with {' / '.join(req)}"
        bad = sorted({t for t in tags for a in avoid if a in t})
        if bad:
            return f"off-topic tag(s) {', '.join(bad)}"
    d = hit.get("duration") or 0
    if not MIN_SECONDS <= d <= MAX_SECONDS:
        return f"duration {d} s outside {MIN_SECONDS}..{MAX_SECONDS}"
    bad = sorted(set(hit_tags(hit)) & EXCLUDED_TAGS)
    if bad:
        return f"tag(s) {', '.join(bad)}"
    if pick_rendition(hit) is None:
        return f"no landscape rendition >= {MIN_WIDTH}x{MIN_HEIGHT} under {MAX_BYTES // 2**20} MB"
    return None


def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def entry_id(topic, hit):
    return f"pixabay-{hit['id']}-{topic['slug']}"


def make_entry(topic, hit, today):
    name, rend = pick_rendition(hit)
    eid = entry_id(topic, hit)
    own = [t for t in hit_tags(hit) if t not in topic["tags"]]
    user = str(hit.get("user") or "").strip() or f"user {hit.get('user_id')}"
    return {
        "id": eid,
        "file": f"{eid}.mp4",
        "kind": KIND,
        "description": topic["description"],
        "tags": list(topic["tags"]) + own,
        "source_url": hit["pageURL"],
        "rights_holder": f"{user} (Pixabay contributor, user_id {hit.get('user_id')})",
        "added": today,
        "licence": LICENCE,
        "medium": None,
        "download_url": rend["url"],
        "duration_s": float(hit.get("duration") or 0) or None,
        "notes": (f"pixabay_id {hit['id']}; rendition {name} {rend['width']}x{rend['height']}, "
                  f"{rend['size']} bytes as served, sound track removed on download "
                  f"(ffmpeg -an); fetched {today}; {USER_DECISION}"),
    }


def plan(client, topics=TOPICS, known_ids=(), limit=MAX_BATCH, log=print):
    """[(topic, hit)] to fetch: per topic the `take` most popular clips that
    qualify, not already in the index and not picked by an earlier topic."""
    chosen, seen = [], set()
    known = set(known_ids)
    for topic in topics:
        resp = client.search(q=topic["query"], video_type="all", safesearch="true",
                             order="popular", per_page=30, min_width=MIN_WIDTH,
                             min_height=MIN_HEIGHT)
        hits = resp.get("hits") or []
        took, already = 0, 0
        for hit in hits:
            if took >= topic["take"] or len(chosen) >= limit:
                break
            if hit.get("id") in seen or hit.get("id") in EXCLUDED_IDS:
                continue
            if entry_id(topic, hit) in known:
                seen.add(hit.get("id"))
                already += 1
                took += 1
                continue
            reason = why_not(hit, topic)
            if reason:
                continue
            seen.add(hit["id"])
            chosen.append((topic, hit))
            took += 1
        log(f"{topic['slug']}: {len(hits)} hit(s), {took - already} new"
            f"{f', {already} already indexed' if already else ''}")
    return chosen


# --------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------

def strip_audio(src, dst):
    """Copy the video stream only: the file in the library is silent."""
    out = subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-c:v", "copy",
                          "-movflags", "+faststart", str(dst)],
                         capture_output=True, text=True, timeout=300)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg could not remux {src.name}: {out.stderr.strip()[:300]}")


def download(url, target, opener=_open):
    tmp = target.with_name(target.name + ".part")
    with opener(url) as resp:
        body = resp.read(MAX_BYTES + 1)
    if len(body) > MAX_BYTES:
        raise RuntimeError(f"{target.name}: over {MAX_BYTES} bytes")
    tmp.write_bytes(body)
    return tmp


def link_beside_index(media_file, index_folder):
    """Absolute symlink to the file next to the index, when they differ."""
    link = Path(index_folder) / media_file.name
    if Path(index_folder).resolve() == media_file.parent.resolve():
        return None
    if link.is_symlink() or link.exists():
        if link.is_symlink() and link.resolve() == media_file.resolve():
            return link
        link.unlink()
    link.symlink_to(media_file.resolve())
    return link


def fetch(chosen, root, media_dir, today, opener=_open, sleep=time.sleep,
          remux=strip_audio, measure=lib.measure_duration, log=print):
    """Download, silence, measure, link and record each chosen clip.
    The index is written once, at the end, and only valid entries reach it."""
    index_folder = lib.folder_for(KIND, root)
    media_dir = Path(media_dir)
    media_dir.mkdir(parents=True, exist_ok=True)
    index = lib.load_index(KIND, root)
    ids = {e.get("id") for e in index["entries"]}
    added, failed, total = [], [], 0
    for i, (topic, hit) in enumerate(chosen):
        entry = make_entry(topic, hit, today)
        if entry["id"] in ids:
            continue
        target = media_dir / entry["file"]
        try:
            if not target.exists():
                part = download(entry["download_url"], target, opener)
                try:
                    remux(part, target)
                finally:
                    part.unlink(missing_ok=True)
            try:
                entry["duration_s"] = round(measure(target), 3)
            except Exception:  # noqa: BLE001 - the API's own duration stays
                pass
            link_beside_index(target, index_folder)
            errs = lib.validate_entry(entry, KIND, index_folder)
            if errs:
                raise RuntimeError("; ".join(errs))
        except Exception as exc:  # noqa: BLE001
            failed.append(entry["id"])
            log(f"  FAILED {entry['id']}: {exc}")
            continue
        size = target.stat().st_size
        total += size
        index["entries"].append(entry)
        ids.add(entry["id"])
        added.append(entry["id"])
        log(f"  fetched {entry['id']}: {size // 1024} KB, {entry['duration_s']} s")
        if i < len(chosen) - 1:
            sleep(DOWNLOAD_DELAY_S)
    if added:
        errs = lib.validate_index(index, KIND)
        if errs:
            raise RuntimeError("index would not validate: " + "; ".join(errs))
        lib.save_index(index, KIND, root)
    return added, failed, total


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None, environ=None, opener=_open):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--fetch", action="store_true", help="download (default: dry run)")
    ap.add_argument("--root", default=str(lib.INSERTS_ROOT),
                    help="library root whose loops/index.json is written")
    ap.add_argument("--media-dir", help="where the files go (default: the index's folder)")
    ap.add_argument("--cache-dir", default=str(DEFAULT_CACHE), help="24 h API cache")
    ap.add_argument("--limit", type=int, default=MAX_BATCH,
                    help=f"files this run, at most {MAX_BATCH}")
    ap.add_argument("--env-file", help="where PIXABAY_API_KEY is read when not in the environment")
    args = ap.parse_args(argv)
    limit = max(0, min(args.limit, MAX_BATCH))
    root = Path(args.root).resolve()
    media_dir = Path(args.media_dir).resolve() if args.media_dir else lib.folder_for(KIND, root)
    today = date.today().isoformat()

    key = api_key(environ, args.env_file)
    client = Client(key, args.cache_dir, opener=opener)
    known = [e.get("id") for e in lib.load_index(KIND, root)["entries"]]
    chosen = plan(client, known_ids=known, limit=limit)
    print(f"plan: {len(chosen)} new clip(s); API calls {client.api_calls}, "
          f"cache hits {client.cache_hits}")
    for topic, hit in chosen:
        name, rend = pick_rendition(hit)
        print(f"  {entry_id(topic, hit)}: {hit.get('duration')} s, {name} "
              f"{rend['width']}x{rend['height']}, {rend['size'] // 1024} KB, "
              f"by {hit.get('user')} - {hit.get('pageURL')} [{hit.get('tags')}]")
    if not args.fetch:
        print("dry run: nothing downloaded (--fetch to download)")
        return 0
    added, failed, total = fetch(chosen, root, media_dir, today, opener=opener)
    print(f"fetched {len(added)} file(s), {total / 2**20:.1f} MB into {media_dir}; "
          f"{len(failed)} failed")
    if added:
        print("next: python3 scripts/index_inserts.py --kind loop   (CLIP vectors)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
