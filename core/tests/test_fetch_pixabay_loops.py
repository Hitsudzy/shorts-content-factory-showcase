#!/usr/bin/env python3
"""CF-0142: scripts/fetch_pixabay_loops.py - the underlay library from Pixabay.

No network and no live data: the API and the CDN are a fake opener, ffmpeg
is a stand-in copy, every library is a temp tree. What is checked:

* a dry run (the default) asks the API and writes nothing - no file, no
  index change;
* the selection keeps the topic honest (a clip without a `require` tag or
  with an `avoid` tag is not taken), drops people / brands / generated
  clips, short or long ones, and picks the smallest landscape rendition of
  at least 1920x1080;
* the key never reaches stdout, a cache file or an error message;
* the API's terms: an answer is cached and reused for 24 h (a second run
  makes no request), a stale one is asked again, the sliding window pauses
  before the 91st call in 60 s, and X-RateLimit-Remaining 0 pauses;
* --fetch writes entries the library schema accepts, with the provenance
  POLICY.md asks for, the licence and the user's decision of 2026-10-11;
  media may live in another folder, linked beside the index by an absolute
  symlink; a re-run adds nothing.
"""
import contextlib
import io
import json
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "shared" / "inserts"))
sys.path.insert(0, str(ROOT / "scripts"))

from _tmproot import tmp_root  # noqa: E402
import inserts_lib as lib  # noqa: E402
import fetch_pixabay_loops as fpl  # noqa: E402

KEY = "test-key-0123456789abcdef"
TMP = tmp_root("cf0142-")


def rendition(w, h, size, url):
    return {"url": url, "width": w, "height": h, "size": size, "thumbnail": url + ".jpg"}


def hit(hid, tags, duration=20, user="Somebody", renditions=None):
    renditions = renditions or {
        "large": rendition(3840, 2160, 50_000_000, f"https://cdn.example/{hid}-large.mp4"),
        "medium": rendition(1920, 1080, 9_000_000, f"https://cdn.example/{hid}-medium.mp4"),
        "small": rendition(1280, 720, 4_000_000, f"https://cdn.example/{hid}-small.mp4"),
    }
    return {"id": hid, "pageURL": f"https://pixabay.com/videos/id-{hid}/", "tags": tags,
            "duration": duration, "user": user, "user_id": hid * 10, "videos": renditions}


class FakeResp(io.BytesIO):
    def __init__(self, body, headers=None):
        super().__init__(body)
        self.headers = headers or {}

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class FakeNet:
    """The API and the CDN in one opener; records every URL it is asked for."""

    def __init__(self, hits_by_query, remaining="99"):
        self.hits_by_query = hits_by_query
        self.remaining = remaining
        self.urls = []

    def __call__(self, url, timeout=None):
        self.urls.append(url)
        if url.startswith(fpl.API_URL):
            from urllib.parse import parse_qs, urlparse
            q = parse_qs(urlparse(url).query)["q"][0]
            hits = self.hits_by_query.get(q, [])
            return FakeResp(json.dumps({"total": len(hits), "hits": hits}).encode(),
                            {"X-RateLimit-Remaining": self.remaining, "X-RateLimit-Reset": "7"})
        return FakeResp(b"\x00\x00\x00\x18ftypmp42" + url.encode())

    def api_calls(self):
        return [u for u in self.urls if u.startswith(fpl.API_URL)]


TOPICS = [
    {"slug": "sand", "query": "kinetic sand", "take": 2, "require": ["kinetic sand"],
     "description": "Kinetic sand being cut in close-up.", "tags": ["satisfying", "sand"]},
    {"slug": "slime", "query": "slime", "take": 1, "require": ["slime"], "avoid": ["snail"],
     "description": "Slime stretched in close-up.", "tags": ["satisfying", "slime"]},
]
HITS = {
    "kinetic sand": [
        hit(1, "kinetic sand, cutting"),
        hit(2, "kinetic sand, woman, hands"),         # a person
        hit(3, "beach, sand"),                        # off topic: no require tag
        hit(4, "kinetic sand, asmr", duration=3),     # too short
        hit(5, "kinetic sand, ai generated"),         # generated
        hit(6, "kinetic sand, macro", renditions={    # portrait only
            "large": rendition(1080, 1920, 5_000_000, "https://cdn.example/6.mp4")}),
        hit(7, "kinetic sand, macro"),
    ],
    "slime": [hit(8, "slime, snail"), hit(9, "slime, toy")],
}


def run(argv, net, env=None):
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        rc = fpl.main(argv, environ=env if env is not None else {fpl.KEY_ENV: KEY}, opener=net)
    return rc, out.getvalue()


def library(name):
    root = TMP / name / "inserts"
    (root / "loops").mkdir(parents=True)
    lib.save_index(lib.empty_index("loop"), "loop", root)
    return root


def fake_remux(src, dst):
    shutil.copyfile(src, dst)


def with_topics(fn):
    def wrapper():
        saved = fpl.TOPICS[:]
        fpl.TOPICS[:] = TOPICS
        defaults = fpl.plan.__defaults__
        fpl.plan.__defaults__ = (TOPICS,) + defaults[1:]
        saved_fetch = fpl.fetch.__defaults__
        # remux and measure are stand-ins: no ffmpeg in a test
        d = list(saved_fetch)
        d[2] = fake_remux
        d[3] = lambda p: 12.5
        d[1] = lambda s: None
        fpl.fetch.__defaults__ = tuple(d)
        try:
            fn()
        finally:
            fpl.TOPICS[:] = saved
            fpl.plan.__defaults__ = defaults
            fpl.fetch.__defaults__ = saved_fetch
    wrapper.__name__ = fn.__name__
    return wrapper


@with_topics
def test_dry_run_is_the_default_and_writes_nothing():
    root = library("dry")
    before = (root / "loops" / "index.json").read_text()
    net = FakeNet(HITS)
    rc, out = run(["--root", str(root), "--cache-dir", str(TMP / "dry-cache")], net)
    assert rc == 0, out
    assert "dry run" in out and "pixabay-1-sand" in out and "pixabay-7-sand" in out
    assert (root / "loops" / "index.json").read_text() == before
    assert sorted(p.name for p in (root / "loops").iterdir()) == ["index.json"]
    assert all(u.startswith(fpl.API_URL) for u in net.urls), "a dry run downloads nothing"


@with_topics
def test_selection_keeps_topic_people_brands_duration_and_rendition_rules():
    client = fpl.Client(KEY, TMP / "sel-cache", opener=FakeNet(HITS), log=lambda *a: None)
    chosen = fpl.plan(client, log=lambda *a: None)
    ids = [h["id"] for _, h in chosen]
    assert ids == [1, 7, 9], ids
    name, rend = fpl.pick_rendition(hit(1, "x"))
    assert (name, rend["width"], rend["height"]) == ("medium", 1920, 1080)
    assert fpl.why_not(HITS["kinetic sand"][5]).startswith("no landscape rendition")
    assert "snail" in fpl.why_not(HITS["slime"][0], TOPICS[1])


@with_topics
def test_key_never_reaches_output_cache_or_errors():
    net = FakeNet(HITS)
    cache = TMP / "key-cache"
    rc, out = run(["--root", str(library("key")), "--cache-dir", str(cache)], net)
    assert rc == 0 and KEY not in out
    assert all(f"key={KEY}" in u for u in net.api_calls()), "the key goes into the request"
    for f in cache.iterdir():
        assert KEY not in f.read_text(), f

    import urllib.error

    def failing(url, timeout=None):
        raise urllib.error.HTTPError(url, 400, "bad", {}, None)
    client = fpl.Client(KEY, TMP / "key-cache-2", opener=failing, log=lambda *a: None)
    try:
        client.search(q="x")
    except fpl.PixabayError as exc:
        assert KEY not in str(exc) and "400" in str(exc)
    else:
        raise AssertionError("an HTTP error must raise PixabayError")


def test_key_from_env_file_when_not_in_environment():
    env_file = TMP / "dotenv"
    env_file.write_text(f"OTHER=1\n{fpl.KEY_ENV}=\"{KEY}\"\n")
    assert fpl.api_key({}, env_file) == KEY
    assert fpl.api_key({fpl.KEY_ENV: "from-env"}, env_file) == "from-env"


def test_answers_are_cached_for_24_hours():
    now = [1_000_000.0]
    net = FakeNet(HITS)
    cache = TMP / "ttl-cache"
    mk = lambda: fpl.Client(KEY, cache, clock=lambda: now[0], opener=net, log=lambda *a: None)
    mk().search(q="slime")
    mk().search(q="slime")
    assert len(net.api_calls()) == 1, "a second ask within 24 h is served from the cache"
    now[0] += fpl.CACHE_TTL_S + 1
    mk().search(q="slime")
    assert len(net.api_calls()) == 2, "a stale answer is asked again"


def test_rate_window_and_remaining_zero_pause():
    now = [0.0]
    slept = []

    def sleep(s):
        slept.append(s)
        now[0] += s
    net = FakeNet({})
    client = fpl.Client(KEY, TMP / "rate-cache", clock=lambda: now[0], sleep=sleep,
                        opener=net, log=lambda *a: None)
    for i in range(fpl.API_MAX_PER_WINDOW):
        client.search(q=f"q{i}")
    assert not slept
    client.search(q="one more")
    assert slept and slept[0] >= 59, slept
    assert fpl.API_MAX_PER_WINDOW < 100

    slept.clear()
    zero = fpl.Client(KEY, TMP / "rate-cache-0", clock=lambda: now[0], sleep=sleep,
                      opener=FakeNet({}, remaining="0"), log=lambda *a: None)
    zero.search(q="z")
    assert slept == [7.5], slept


@with_topics
def test_fetch_writes_valid_provenance_links_media_and_is_idempotent():
    root = library("fetch")
    media = TMP / "fetch" / "working-copy-loops"
    net = FakeNet(HITS)
    argv = ["--root", str(root), "--media-dir", str(media), "--cache-dir", str(TMP / "f-cache"),
            "--fetch"]
    rc, out = run(argv, net)
    assert rc == 0, out
    index = lib.load_index("loop", root)
    assert lib.validate_index(index, "loop", root / "loops") == []
    ids = sorted(e["id"] for e in index["entries"])
    assert ids == ["pixabay-1-sand", "pixabay-7-sand", "pixabay-9-slime"], ids
    e = next(e for e in index["entries"] if e["id"] == "pixabay-9-slime")
    assert e["source_url"] == "https://pixabay.com/videos/id-9/"
    assert e["rights_holder"].startswith("Somebody (Pixabay contributor")
    assert e["licence"].startswith("Pixabay Content License")
    assert e["download_url"] == "https://cdn.example/9-medium.mp4"
    assert e["duration_s"] == 12.5 and e["added"] == fpl.date.today().isoformat()
    assert "2026-10-11" in e["notes"] and "question 20" in e["notes"] and "pixabay_id 9" in e["notes"]
    assert "slime" in e["tags"] and "toy" in e["tags"]
    link = root / "loops" / e["file"]
    assert link.is_symlink() and link.resolve() == (media / e["file"]).resolve()
    assert Path(str(link.readlink())).is_absolute()
    assert (media / e["file"]).read_bytes().endswith(b"9-medium.mp4")

    downloads = len(net.urls) - len(net.api_calls())
    rc, out = run(argv, net)
    assert rc == 0 and len(lib.load_index("loop", root)["entries"]) == 3
    assert len(net.urls) - len(net.api_calls()) == downloads, "a re-run downloads nothing"
    assert len(net.api_calls()) == 2, "and asks the API nothing: the cache answers"


@with_topics
def test_limit_caps_one_run():
    root = library("limit")
    rc, out = run(["--root", str(root), "--cache-dir", str(TMP / "l-cache"), "--fetch",
                   "--limit", "1"], FakeNet(HITS))
    assert rc == 0 and len(lib.load_index("loop", root)["entries"]) == 1
    assert fpl.MAX_BATCH <= 30


def test_shipped_topics_are_well_formed():
    slugs = [t["slug"] for t in fpl.TOPICS]
    assert len(slugs) == len(set(slugs))
    total = sum(t["take"] for t in fpl.TOPICS)
    assert 20 <= total <= fpl.MAX_BATCH + 4, total
    for t in fpl.TOPICS:
        assert t["description"].strip() and t["require"] and lib.ID_RE.match(t["slug"]), t


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
