#!/usr/bin/env python3
"""CF-0665 (FI-1 of the root's docs/science-footage.md): an archive candidate
(`nasa:<id>` / `commons:<pageid>`, the Trend Hunter's TH-3) is downloaded
directly from its `download_url`, not through yt-dlp.

Pinned here, offline, on stand-ins - the network is a fake `urlopen`, ffprobe
and ffmpeg are a fake `subprocess.run` (one test asks the local ffmpeg to turn
a WebM it generates itself into mp4, and passes as skipped without one), the
cache and the factory root are temp directories:

  - ids: `nasa:<id>` -> `nasa-<id>`, `commons:<pageid>` -> `commons-<pageid>`,
    unsafe characters made `_`; the partial sweep knows their partials and
    never their sidecars;
  - `download()`: a stream with the size ceiling (announced and counted), the
    time ceiling, the type check, a short answer and an HTTP error refused;
  - the licence read again: Commons' extmetadata judged by the root rule, NASA's
    metadata.json credit; a change is `changed` with both versions, a re-read
    that does not answer decides nothing;
  - `fetch_footage.py --archive-json`: WebM re-encoded to `<file id>.mp4`, a
    1080p mp4 moved as it is, NASA marked official and Commons not, the cache
    entry with `candidate_id`, the archive block and the re-read; a changed
    licence (exit LICENCE_CHANGED_EXIT, nothing downloaded); the length
    ceiling before (the candidate's length) and after (ffprobe's); a failed
    download leaves nothing; a second fetch is a cache hit by file id;
  - ingest: the walk takes the file ids, hands the candidate record to the
    fetch, writes `candidate_id` on `fetched[]`; a `licence_changed` refusal
    spends no attempt and is no lost download; `fetch_source` builds the
    archive command.

No pytest dependency - plain asserts, run directly.
"""
import io
import json
import shutil
import subprocess
import sys
import tempfile
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(HERE))

import archive_source as arc        # noqa: E402
import fetch_footage as ff          # noqa: E402
import ingest_batch as ib           # noqa: E402
import source_rights as sr          # noqa: E402
from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("cf0665-")

LICENCES = {
    "accepted": [
        {"id": "public_domain", "attribution": "requested", "share_alike": False,
         "matches": ["public domain", "pd"]},
        {"id": "cc_by", "attribution": "required", "share_alike": False,
         "matches": ["cc by"]},
        {"id": "cc_by_sa", "attribution": "required", "share_alike": True,
         "matches": ["cc by-sa"]},
    ],
    "refused": [
        {"id": "noncommercial", "what": "NC", "tokens": ["nc"]},
        {"id": "noderivatives", "what": "ND", "tokens": ["nd"]},
        {"id": "non_free", "what": "non-free", "tokens": ["non-free"]},
    ],
}


def block(short_name, lid, accepted=True):
    return {"id": lid, "accepted": accepted, "judged": True, "short_name": short_name,
            "read_from": "test", "yt_license": None, "origin": None, "attribution": None,
            "share_alike": None, "license_url": None, "reason": None}


COMMONS = {
    "video_id": "commons:183761853", "kind": "archive", "nature": "science",
    "origin": "unknown", "title": "Artemis II launch", "channel_title": "Wikimedia Commons: Jane Doe",
    "duration_seconds": 12.0, "credit": "Jane Doe", "footage_origin": "wikimedia_commons",
    "licence": block("CC BY-SA 4.0", "cc_by_sa"),
    "source_url": "https://commons.wikimedia.org/wiki/File:Artemis_II_launch.webm",
    "download_url": "https://upload.wikimedia.org/wikipedia/commons/a/ab/Artemis_II_launch.webm",
    "media_type": "video/webm", "bytes": 4096,
    "archive": {"name": "wikimedia_commons", "id": 183761853, "rendition": "original",
                "caveats": []},
}
NASA = {
    "video_id": "nasa:art001m1203451716", "kind": "archive", "nature": "science",
    "origin": "official", "title": "Artemis II crew teaser",
    "channel_title": "NASA Image and Video Library (JSC)", "duration_seconds": None,
    "credit": "NASA/Reyes", "footage_origin": "nasa",
    "licence": block("PD-USGov-NASA", "public_domain"),
    "source_url": "https://images.nasa.gov/details/art001m1203451716",
    "download_url": ("https://images-assets.nasa.gov/video/art001m1203451716/"
                     "art001m1203451716~large.mp4"),
    "media_type": "video/mp4", "bytes": 2048,
    "archive": {"name": "nasa_images", "id": "art001m1203451716", "rendition": "large",
                "caveats": []},
}


# --------------------------------------------------------------------------
# stand-ins
# --------------------------------------------------------------------------

class Resp:
    def __init__(self, body=b"", status=200, ctype="video/webm", length="auto"):
        self.body, self.status, self.pos = body, status, 0
        self.headers = {"Content-Type": ctype}
        if length == "auto":
            self.headers["Content-Length"] = str(len(body))
        elif length is not None:
            self.headers["Content-Length"] = str(length)

    def getcode(self):
        return self.status

    def read(self, n=-1):
        if n is None or n < 0:
            n = len(self.body) - self.pos
        chunk = self.body[self.pos:self.pos + n]
        self.pos += len(chunk)
        return chunk

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Net:
    """A fake urlopen: `routes` maps a URL prefix to a Resp factory (or an
    exception); every URL asked is kept in `asked`."""

    def __init__(self, routes):
        self.routes, self.asked = routes, []

    def __call__(self, req, timeout=None):
        url = req.full_url if hasattr(req, "full_url") else str(req)
        self.asked.append(url)
        for prefix, answer in self.routes.items():
            if url.startswith(prefix):
                got = answer() if callable(answer) else answer
                if isinstance(got, Exception):
                    raise got
                return got
        raise urllib.error.URLError(f"no route for {url}")


def commons_api(short_name="CC BY-SA 4.0", non_free="", artist="Jane Doe"):
    page = {"pageid": 183761853, "imageinfo": [{"extmetadata": {
        "LicenseShortName": {"value": short_name}, "NonFree": {"value": non_free},
        "Artist": {"value": f"<a href='//x'>{artist}</a>"}}}]}
    body = json.dumps({"query": {"pages": [page]}}).encode()
    return lambda: Resp(body, ctype="application/json")


def nasa_meta(credit="NASA/Reyes"):
    body = json.dumps({"XMP:Credit": credit, "AVAIL:Center": "JSC"}).encode()
    return lambda: Resp(body, ctype="application/json")


class Tools:
    """A fake subprocess.run for ffprobe / ffmpeg."""

    def __init__(self, fmt="matroska,webm", height=720, duration=12.0, video=True,
                 ffmpeg_ok=True):
        self.fmt, self.height, self.duration = fmt, height, duration
        self.video, self.ffmpeg_ok, self.calls = video, ffmpeg_ok, []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if "ffprobe" in Path(cmd[0]).name:
            streams = ([{"codec_type": "video", "codec_name": "vp9", "width": 1280,
                         "height": self.height}] if self.video else
                       [{"codec_type": "audio", "codec_name": "vorbis"}])
            return SimpleNamespace(returncode=0, stderr="", stdout=json.dumps(
                {"streams": streams, "format": {"format_name": self.fmt,
                                                "duration": str(self.duration)}}))
        if self.ffmpeg_ok:
            Path(cmd[-1]).write_bytes(b"mp4" * 100)
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=1, stdout="", stderr="Invalid data found")


def run_fetch(cand, net, tools, extra=(), cache=None, licences=LICENCES):
    """fetch_footage.main() in-process on the archive path; (code, out, err, cache)."""
    cache = cache or Path(tempfile.mkdtemp(dir=TMP))
    root = Path(tempfile.mkdtemp(dir=TMP))          # no rights-exclusions.json: nobody out
    old = (ff.CACHE, ff.INDEX, ff.ARCHIVE_OPENER, ff.ARCHIVE_RUNNER)
    ff.CACHE, ff.INDEX = cache, cache / "index.json"
    ff.ARCHIVE_OPENER, ff.ARCHIVE_RUNNER = net, tools
    argv = ["fetch_footage.py", cand["source_url"], "--archive-json", json.dumps(cand),
            "--rights-root", str(root), *extra]
    if licences is not None:
        argv += ["--licences-json", json.dumps(licences)]
    argv, sys.argv = sys.argv, argv
    out, err, code = io.StringIO(), io.StringIO(), 0
    try:
        with redirect_stdout(out), redirect_stderr(err):
            try:
                ff.main()
            except SystemExit as e:
                if isinstance(e.code, str):
                    print(e.code, file=sys.stderr)
                    code = 1
                else:
                    code = e.code or 0
    finally:
        sys.argv = argv
        ff.CACHE, ff.INDEX, ff.ARCHIVE_OPENER, ff.ARCHIVE_RUNNER = old
    return code, out.getvalue(), err.getvalue(), cache


def entries(cache):
    p = cache / "index.json"
    return json.loads(p.read_text())["entries"] if p.exists() else []


def leftovers(cache):
    return sorted(p.name for p in cache.iterdir() if p.name != "index.json")


# --------------------------------------------------------------------------
# ids
# --------------------------------------------------------------------------

def test_file_ids():
    assert arc.file_id("nasa:art001m1203451716") == "nasa-art001m1203451716"
    assert arc.file_id("commons:183761853") == "commons-183761853"
    assert arc.file_id("nasa:KSC 2026.01/x") == "nasa-KSC_2026_01_x"
    assert arc.file_id("nasa-abc") == "nasa-abc"
    assert arc.file_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert arc.archive_of("nasa:x") == arc.archive_of("nasa-x") == "nasa"
    assert arc.archive_of("commons-1") == "commons" and not arc.is_archive("dQw4w9WgXcQ")
    # no ':' and no '/' - the Video Editor's `<source>:<shot>` keys stay two parts
    fid = arc.file_id("nasa:a:b/c")
    assert ":" not in fid and "/" not in fid
    assert f"{fid}:12".rsplit(":", 1)[0] == fid and f"{fid}:12".split(":")[0] == fid


def test_the_sweep_knows_archive_partials_and_never_their_sidecars():
    cache = Path(tempfile.mkdtemp(dir=TMP))
    keep = ["commons-1.mp4", "commons-1.shots.json", "commons-1.contact.jpg",
            "nasa-x_y.fingerprint.json"]
    junk = ["commons-1.webm.part", "nasa-x_y.temp.mp4"]
    for n in keep + junk:
        (cache / n).write_bytes(b"x")
    old = ff.CACHE
    ff.CACHE = cache
    try:
        removed = ff.sweep_partials(log=lambda m: None)
    finally:
        ff.CACHE = old
    assert sorted(n for n, _ in removed) == sorted(junk), removed
    assert leftovers(cache) == sorted(keep)


# --------------------------------------------------------------------------
# download()
# --------------------------------------------------------------------------

def _dest():
    return Path(tempfile.mkdtemp(dir=TMP)) / "f.part"


def test_download_streams_a_video():
    body = b"v" * (3 * arc.CHUNK + 5)
    got = arc.download("https://x/a.webm", _dest(), opener=Net({"https://x": lambda: Resp(body)}))
    assert got["bytes"] == len(body) and got["content_type"] == "video/webm", got


def test_download_refusals():
    cases = [
        (Resp(b"<html>", ctype="text/html"), "not a video"),
        (Resp(b"v" * 10, length=11), "Content-Length said 11"),
        (Resp(b"v" * 10, length=None, ctype="application/octet-stream"), None),
        (Resp(b"", ctype="video/mp4"), "empty answer"),
        (Resp(b"v", status=206), "HTTP 206"),
    ]
    for resp, want in cases:
        net = Net({"https://x": lambda r=resp: r})
        try:
            arc.download("https://x/a", _dest(), opener=net)
            assert want is None, want
        except arc.ArchiveError as exc:
            assert want and want in str(exc), (want, exc)
    # over the ceiling: announced, then counted without an announcement
    for length in ("auto", None):
        net = Net({"https://x": lambda length=length: Resp(b"v" * 50, length=length)})
        try:
            arc.download("https://x/a", _dest(), max_bytes=20, opener=net)
            raise AssertionError("over the ceiling was taken")
        except arc.ArchiveError as exc:
            assert "ceiling" in str(exc), exc
    # an HTTP error and a non-HTTP address
    net = Net({"https://x": urllib.error.HTTPError("https://x/a", 404, "nf", {}, None)})
    try:
        arc.download("https://x/a", _dest(), opener=net)
        raise AssertionError("404 was taken")
    except arc.ArchiveError as exc:
        assert "HTTP 404" in str(exc)
    try:
        arc.download("file:///etc/passwd", _dest(), opener=net)
        raise AssertionError("file:// was taken")
    except arc.ArchiveError as exc:
        assert "not an HTTP(S) address" in str(exc)


def test_download_time_ceiling():
    ticks = iter(range(0, 10_000, 100))
    net = Net({"https://x": lambda: Resp(b"v" * (5 * arc.CHUNK))})
    try:
        arc.download("https://x/a", _dest(), timeout=250, opener=net,
                     clock=lambda: next(ticks))
        raise AssertionError("a stalled download was waited for")
    except arc.ArchiveError as exc:
        assert "took over 250 s" in str(exc), exc


# --------------------------------------------------------------------------
# the licence read again
# --------------------------------------------------------------------------

def test_commons_recheck():
    rule = sr.licence_rule()
    assert rule is not None, "the root's shared/footage_licence.py is not reachable"
    same = arc.recheck(COMMONS, LICENCES, rule, opener=Net({arc.COMMONS_API: commons_api()}))
    assert same["read"] and not same["changed"], same
    assert same["now"]["licence"] == "cc_by_sa" and same["now"]["artist"] == "Jane Doe", same
    nc = arc.recheck(COMMONS, LICENCES, rule,
                     opener=Net({arc.COMMONS_API: commons_api("CC BY-NC-SA 4.0")}))
    assert nc["changed"] and nc["was"]["short_name"] == "CC BY-SA 4.0", nc
    assert nc["now"]["short_name"] == "CC BY-NC-SA 4.0" and "CC BY-NC-SA" in nc["reason"], nc
    nf = arc.recheck(COMMONS, LICENCES, rule,
                     opener=Net({arc.COMMONS_API: commons_api(non_free="true")}))
    assert nf["changed"] and nf["now"]["non_free"] is True, nf
    # without the lists: the names themselves
    plain = arc.recheck(COMMONS, None, None, opener=Net({arc.COMMONS_API: commons_api()}))
    assert plain["read"] and not plain["changed"], plain
    other = arc.recheck(COMMONS, None, None,
                        opener=Net({arc.COMMONS_API: commons_api("CC BY 4.0")}))
    assert other["changed"], other
    # an archive that does not answer decides nothing
    gone = arc.recheck(COMMONS, LICENCES, rule, opener=Net({}))
    assert gone["read"] is False and gone["changed"] is False and gone["error"], gone


def test_nasa_recheck():
    url = arc.nasa_metadata_url(NASA)
    assert url == ("https://images-assets.nasa.gov/video/art001m1203451716/"
                   "metadata.json"), url
    ok = arc.recheck(NASA, opener=Net({url: nasa_meta()}))
    assert ok["read"] and not ok["changed"] and ok["now"]["credit"] == "NASA/Reyes", ok
    third = arc.recheck(NASA, opener=Net({url: nasa_meta("ESA/ATG medialab")}))
    assert third["changed"] and third["now"]["third_party"] == "ESA/ATG medialab", third
    assert third["was"]["short_name"] == "PD-USGov-NASA", third
    both = arc.recheck(NASA, opener=Net({url: nasa_meta("NASA/ESA")}))
    assert not both["changed"], both
    silent = arc.recheck(NASA, opener=Net({url: nasa_meta("")}))
    assert silent["read"] and not silent["changed"], silent


# --------------------------------------------------------------------------
# fetch_footage.py --archive-json
# --------------------------------------------------------------------------

def test_a_commons_webm_becomes_its_file_id_mp4():
    net = Net({arc.COMMONS_API: commons_api(),
               "https://upload.wikimedia.org": lambda: Resp(b"w" * 4096)})
    tools = Tools()
    rights = sr.rights_of("commons-183761853", COMMONS, {"licences": LICENCES})
    code, out, err, cache = run_fetch(COMMONS, net, tools,
                                      extra=["--rights-json", json.dumps(rights)])
    assert code == 0, (code, err)
    final = cache / "commons-183761853.mp4"
    assert out.strip() == f"fetched -> {final}", out
    assert final.is_file() and leftovers(cache) == ["commons-183761853.mp4"], leftovers(cache)
    [e] = entries(cache)
    assert e["id"] == "commons-183761853" and e["candidate_id"] == "commons:183761853", e
    assert e["url"] == COMMONS["source_url"] and e["official_channel"] is False, e
    assert e["archive"]["re_encoded"] is True and e["archive"]["bytes"] == 4096, e
    assert e["licence_recheck"]["read"] and not e["licence_recheck"]["changed"], e
    assert e["rights"]["licence"] == "cc_by_sa" and e["rights"]["credit"] == "Jane Doe", e
    assert e["rights"]["licence_recheck"]["now"]["licence"] == "cc_by_sa", e
    # ffmpeg was asked for H.264 at most 1080 high, from the WebM
    enc = next(c for c in tools.calls if "ffprobe" not in Path(c[0]).name)
    assert "libx264" in enc and enc[-1].endswith("commons-183761853.staged.mp4"), enc
    # no yt-dlp: only the API and the file were asked
    assert [u.split("?")[0] for u in net.asked] == [arc.COMMONS_API, COMMONS["download_url"]]
    # the second fetch is the cache's, by file id - nothing asked
    net2 = Net({})
    code, out, err, cache = run_fetch(COMMONS, net2, Tools(), cache=cache)
    assert code == 0 and out.startswith("cached -> "), (code, out, err)
    assert net2.asked == [], net2.asked


def test_a_nasa_1080p_mp4_is_moved_and_official():
    meta = arc.nasa_metadata_url(NASA)
    net = Net({meta: nasa_meta(),
               NASA["download_url"]: lambda: Resp(b"n" * 2048, ctype="video/mp4")})
    tools = Tools(fmt="mov,mp4,m4a,3gp,3g2,mj2", height=1080, duration=30.0)
    code, out, err, cache = run_fetch(NASA, net, tools, extra=["--official"])
    assert code == 0, (code, err)
    [e] = entries(cache)
    assert e["id"] == "nasa-art001m1203451716" and e["official_channel"] is True, e
    assert e["archive"]["re_encoded"] is False and e["duration"] == 30.0, e
    assert (cache / "nasa-art001m1203451716.mp4").read_bytes() == b"n" * 2048
    assert all("ffprobe" in Path(c[0]).name for c in tools.calls), tools.calls
    # a 4K one is scaled down to the height ceiling, the way yt-dlp is held to it
    tall = Tools(fmt="mov,mp4,m4a,3gp,3g2,mj2", height=2160)
    net = Net({meta: nasa_meta(),
               NASA["download_url"]: lambda: Resp(b"n" * 2048, ctype="video/mp4")})
    code, out, err, cache = run_fetch(NASA, net, tall)
    assert code == 0 and entries(cache)[0]["archive"]["re_encoded"] is True, (code, err)


def test_a_changed_licence_is_refused_before_the_download():
    net = Net({arc.COMMONS_API: commons_api("CC BY-NC 4.0"),
               "https://upload.wikimedia.org": lambda: Resp(b"w" * 4096)})
    code, out, err, cache = run_fetch(COMMONS, net, Tools())
    assert code == ff.LICENCE_CHANGED_EXIT, (code, err)
    rec = ff.parse_licence_changed(err)
    assert rec and rec["reason_code"] == "licence_changed", err
    assert rec["was"]["short_name"] == "CC BY-SA 4.0" and rec["now"]["short_name"] == "CC BY-NC 4.0"
    assert rec["video_id"] == "commons-183761853" and rec["candidate_id"] == "commons:183761853"
    assert not any(u.startswith("https://upload") for u in net.asked), net.asked
    assert entries(cache) == [] and leftovers(cache) == [], leftovers(cache)


def test_an_unread_licence_does_not_stop_the_download():
    net = Net({"https://upload.wikimedia.org": lambda: Resp(b"w" * 4096)})
    code, out, err, cache = run_fetch(COMMONS, net, Tools())
    assert code == 0, (code, err)
    assert "not read again" in err and entries(cache)[0]["licence_recheck"]["read"] is False


def test_the_length_ceiling_before_and_after():
    long_cand = dict(COMMONS, duration_seconds=900.0)
    net = Net({})
    code, out, err, cache = run_fetch(long_cand, net, Tools(), extra=["--max-duration", "600"])
    assert code == ff.TOO_LONG_EXIT and ff.parse_too_long(err) == (900, 600), (code, err)
    assert net.asked == [] and entries(cache) == [], net.asked
    # no length on the candidate: ffprobe's, after the download, and nothing kept
    meta = arc.nasa_metadata_url(NASA)
    net = Net({meta: nasa_meta(),
               NASA["download_url"]: lambda: Resp(b"n" * 2048, ctype="video/mp4")})
    code, out, err, cache = run_fetch(NASA, net, Tools(fmt="mp4", duration=900.0),
                                      extra=["--max-duration", "600"])
    assert code == ff.TOO_LONG_EXIT and ff.parse_too_long(err) == (900, 600), (code, err)
    assert entries(cache) == [] and leftovers(cache) == [], leftovers(cache)


def test_a_failed_download_leaves_nothing():
    net = Net({arc.COMMONS_API: commons_api(),
               "https://upload.wikimedia.org": lambda: Resp(b"w" * 10, length=4096)})
    code, out, err, cache = run_fetch(COMMONS, net, Tools())
    assert code == 1 and "archive download failed for commons-183761853" in err, err
    assert "CLEANUP commons-183761853" in err, err
    assert entries(cache) == [] and leftovers(cache) == [], leftovers(cache)
    # a file with no picture (an Ogg that is only sound)
    net = Net({arc.COMMONS_API: commons_api(),
               "https://upload.wikimedia.org": lambda: Resp(b"w" * 4096,
                                                            ctype="application/ogg")})
    code, out, err, cache = run_fetch(dict(COMMONS, media_type="application/ogg"), net,
                                      Tools(video=False))
    assert code == 1 and "no picture" in err and leftovers(cache) == [], err
    # ffmpeg that fails
    net = Net({arc.COMMONS_API: commons_api(),
               "https://upload.wikimedia.org": lambda: Resp(b"w" * 4096)})
    code, out, err, cache = run_fetch(COMMONS, net, Tools(ffmpeg_ok=False))
    assert code == 1 and "ffmpeg exit 1" in err and leftovers(cache) == [], err


def test_the_local_ffmpeg_turns_a_webm_into_mp4():
    """The one real conversion: a 1 s WebM made here, never fetched."""
    ffmpeg, ffprobe = arc.ffmpeg_bin(), arc.ffprobe_bin()
    if not (shutil.which(ffmpeg) or Path(ffmpeg).is_file()):
        print("  (skipped: no ffmpeg on this machine)")
        return
    d = Path(tempfile.mkdtemp(dir=TMP))
    src = d / "commons-1.webm"
    made = subprocess.run([ffmpeg, "-v", "error", "-f", "lavfi", "-i",
                           "testsrc=size=320x180:rate=10", "-t", "1", "-c:v", "libvpx",
                           str(src)], capture_output=True, text=True, timeout=120)
    if made.returncode != 0:
        print(f"  (skipped: this ffmpeg makes no WebM: {made.stderr.strip()[-80:]})")
        return
    info = arc.probe(src)
    assert info and info["height"] == 180 and "webm" in info["format"], info
    dst = d / "commons-1.mp4"
    assert arc.to_mp4(src, dst, info) is True
    out = arc.probe(dst)
    assert out and out["vcodec"] == "h264" and "mp4" in out["format"], out
    assert not src.exists()


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------

def _topic():
    return {"topic_id": "001", "evidence": {
        "youtube_video_ids": [COMMONS["video_id"], NASA["video_id"]],
        "footage_candidates": [COMMONS, NASA]}}


def test_candidate_records_and_the_walk_use_file_ids():
    recs = ib.candidate_records(_topic())
    assert sorted(recs) == ["commons-183761853", "nasa-art001m1203451716"], recs
    assert recs["nasa-art001m1203451716"]["candidate_id"] == "nasa:art001m1203451716"
    st = ib.walk_state(_topic())
    assert list(st["queue"]) == ["commons-183761853", "nasa-art001m1203451716"], st


def test_ingest_fetches_archive_files_under_their_file_ids():
    cache = Path(tempfile.mkdtemp(dir=TMP))
    old = (ff.CACHE, ff.INDEX)
    ff.CACHE, ff.INDEX = cache, cache / "index.json"
    asked = []

    def fetch(vid, note, rights=None, record=None, licences=None):
        asked.append({"vid": vid, "record": record, "licences": licences})
        p = cache / f"{vid}.mp4"
        p.write_bytes(b"\0" * 2_500_000)
        return ib.FetchResult(str(p), False)

    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            fetched, _a, _s, failed, by_topic = ib.ingest(
                [_topic()], {}, "b", 4, True, fetch=fetch, index=lambda p: None,
                fingerprint=lambda p: None, log=lambda m, file=None: None,
                sleep=lambda s: None, pause=0, wanted=2,
                origins={"licences": LICENCES})
    finally:
        ff.CACHE, ff.INDEX = old
    assert not failed, failed
    assert by_topic["001"] == ["commons-183761853", "nasa-art001m1203451716"], by_topic
    assert [a["vid"] for a in asked] == by_topic["001"], asked
    assert asked[0]["record"]["candidate_id"] == "commons:183761853", asked[0]
    assert asked[0]["licences"] == LICENCES, asked[0]
    got = {f["video_id"]: f for f in fetched}
    assert got["nasa-art001m1203451716"]["candidate_id"] == "nasa:art001m1203451716", got
    assert got["commons-183761853"]["rights"]["licence"] == "cc_by_sa", got
    assert got["commons-183761853"]["path"].endswith("commons-183761853.mp4")


def test_ingest_records_a_changed_licence_without_spending_the_attempt():
    cache = Path(tempfile.mkdtemp(dir=TMP))
    old = (ff.CACHE, ff.INDEX)
    ff.CACHE, ff.INDEX = cache, cache / "index.json"
    asked = []

    def fetch(vid, note, rights=None, record=None, licences=None):
        asked.append(vid)
        if vid.startswith("commons-"):
            raise ib.LicenceChanged("the file's licence is now 'CC BY-NC 4.0'", {
                "reason": "the file's licence is now 'CC BY-NC 4.0'",
                "was": {"short_name": "CC BY-SA 4.0"},
                "now": {"short_name": "CC BY-NC 4.0"}})
        p = cache / f"{vid}.mp4"
        p.write_bytes(b"\0" * 2_500_000)
        return ib.FetchResult(str(p), False)

    lines = []
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            fetched, _a, _s, failed, by_topic = ib.ingest(
                [_topic()], {}, "b", 1, True, fetch=fetch, index=lambda p: None,
                fingerprint=lambda p: None, log=lambda m, file=None: lines.append(m),
                sleep=lambda s: None, pause=0, wanted=1,
                origins={"licences": LICENCES})
    finally:
        ff.CACHE, ff.INDEX = old
    # the one attempt the cap allows went to NASA - the refusal spent none
    assert asked == ["commons-183761853", "nasa-art001m1203451716"], asked
    assert by_topic["001"] == ["nasa-art001m1203451716"], by_topic
    [rec] = failed
    assert rec["reason_code"] == "licence_changed" and rec["attempt_spent"] is False, rec
    assert rec["candidate_id"] == "commons:183761853", rec
    assert rec["licence_was"]["short_name"] == "CC BY-SA 4.0", rec
    assert rec["licence_now"]["short_name"] == "CC BY-NC 4.0", rec
    assert any(l.startswith("LICENCE commons-183761853 not taken for 001") for l in lines)
    out = ib.split_losses([rec])
    assert out["lost"] == [] and out["index_failed"] == [], out


def test_measure_never_asks_youtube_about_an_archive_file():
    cache = Path(tempfile.mkdtemp(dir=TMP))
    old = (ff.CACHE, ff.INDEX)
    ff.CACHE, ff.INDEX = cache, cache / "index.json"

    def probe(*a, **k):
        raise AssertionError("yt-dlp was asked about an archive file")

    try:
        m = ib.measure_candidate("nasa-art001m1203451716", dict(NASA), probe=probe)
        assert m.seconds is None and m.source == ib.ARCHIVE_MEASURE, m
        m = ib.measure_candidate("commons-183761853", dict(COMMONS), probe=probe)
        assert m.seconds == 12.0 and m.source == "candidate", m
        # a cached archive file answers by its id
        media = cache / "nasa-art001m1203451716.mp4"
        media.write_bytes(b"m")
        (cache / "index.json").write_text(json.dumps({"entries": [
            {"id": "nasa-art001m1203451716", "url": NASA["source_url"],
             "path": str(media), "duration": 41.0}]}))
        m = ib.measure_candidate("nasa-art001m1203451716", dict(NASA), probe=probe)
        assert m.seconds == 41.0 and m.source == "cache", m
        assert ib.cached_already("nasa-art001m1203451716") is True
        assert ib.cached_already("commons-183761853") is False
    finally:
        ff.CACHE, ff.INDEX = old


def test_fetch_source_builds_the_archive_command():
    seen = {}
    answer = {"code": 0, "stderr": ""}

    def run_child(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=answer["code"], stdout="fetched -> /x/nasa-a.mp4\n",
                               stderr=answer["stderr"], timed_out=False)

    saved = ib.runlog.run_child
    ib.runlog.run_child = run_child
    try:
        rec = dict(NASA, candidate_id=NASA["video_id"])
        ib.fetch_source("nasa-art001m1203451716", "n", max_seconds=600,
                        record=rec, licences=LICENCES)
        cmd = seen["cmd"]
        assert cmd[2] == NASA["source_url"], cmd
        assert "--official" in cmd, cmd
        assert json.loads(cmd[cmd.index("--archive-json") + 1])["candidate_id"] == \
            "nasa:art001m1203451716"
        assert json.loads(cmd[cmd.index("--licences-json") + 1]) == LICENCES
        assert cmd[cmd.index("--max-duration") + 1] == "600"
        rec = dict(COMMONS, candidate_id=COMMONS["video_id"])
        ib.fetch_source("commons-183761853", "n", record=rec)
        assert "--official" not in seen["cmd"], seen["cmd"]
        # exit LICENCE_CHANGED_EXIT -> LicenceChanged with the record
        answer.update(code=ff.LICENCE_CHANGED_EXIT, stderr=ff.licence_changed_line(
            {"reason": "now NC", "was": {"short_name": "a"}, "now": {"short_name": "b"}}))
        try:
            ib.fetch_source("commons-183761853", "n", record=rec)
            raise AssertionError("no LicenceChanged")
        except ib.LicenceChanged as exc:
            assert exc.record["now"]["short_name"] == "b" and str(exc) == "now NC"
        # a YouTube id still goes the yt-dlp way
        answer.update(code=0, stderr="")
        ib.fetch_source("dQw4w9WgXcQ", "n")
        assert "--archive-json" not in seen["cmd"]
        assert seen["cmd"][2] == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    finally:
        ib.runlog.run_child = saved


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")
             and callable(v) and v.__module__ == __name__]
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
