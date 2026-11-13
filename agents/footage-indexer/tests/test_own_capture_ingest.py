#!/usr/bin/env python3
"""CF-0567 (FI step of the root's docs/tech-footage.md): ExampleTech's own
screen recording (`own_capture:<id>`, the Video Editor's capture_tool.py) is
taken into the pool as a source, and a vendor's official clip gets the
`vendor_official` rights.

Pinned here, offline, in temp trees (a temp pool fenced the CF-0683 way, a
temp capture inbox, a stand-in footage-origin document - nothing of the live
pool or the live channels is read):

  - ids: `own_capture:<id>` -> `own_capture-<id>`, back again; the walk and
    the candidate records use the file id and keep `candidate_id`;
  - `fetch_footage.py --own-capture-json`: a tiny mp4 made by the local ffmpeg
    (1080x1920, 2 s) and its sidecar are copied into the pool as
    `<file id>.mp4` / `<file id>.own_capture.json`; the cache entry carries
    the id, the candidate id, the sidecar summary and the rights; a second
    fetch is a cache hit; the sidecar goes with the mp4 on eviction;
  - the refusals: no recording, no sidecar, an origin that is not
    own_capture, a sidecar file_id that is not this file's, a length and a
    frame size ffprobe disagrees with - each with nothing in the pool;
  - the rights record: licence and origin own_capture, no credit, the page and
    the host from the sidecar;
  - vendor clips: a candidate from a `proof_quote` channel gets
    `footage_origin: vendor_official`, `role: proof_quote`, `channel_id`;
    ExampleFilm and ExampleScience records do not change;
  - ingest: the fetch gets the candidate with the recording found in the
    batch's captures/ dir, no ceiling; the ceiling
    and the measure never touch an own capture; `fetch_source` builds the
    copy command.

No pytest dependency - plain asserts, run directly.
"""
import copy
import io
import json
import shutil
import subprocess
import sys
import tempfile
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
import own_capture_source as oc     # noqa: E402
import source_rights as sr          # noqa: E402
from _temp_pool import fence_cache_index  # noqa: E402
from _tmproot import tmp_root       # noqa: E402

TMP = tmp_root("cf0567-")
ROOT = TMP / "root"                              # a stand-in factory root
POOL = fence_cache_index(ROOT / "pool" / "media")   # inbox: ROOT/shared/own-captures
ib.CACHE = POOL

CID = "own_capture:acme-fox-demo-20261011t120000z"
FID = "own_capture-acme-fox-demo-20261011t120000z"
PAGE = "https://acme-fox-demo.hf.space/"


def sidecar(**over):
    rec = {"schema": "own-capture/1", "id": CID, "file_id": FID, "file": f"{FID}.mp4",
           "origin": "own_capture", "licence": "own_capture",
           "found_by": {"how": "screen_capture", "ref": "capture_hosts"},
           "url": PAGE, "final_url": PAGE, "host": "acme-fox-demo.hf.space",
           "capture_host": "hf.space",
           "host_entry": {"host": "hf.space", "use": "capture", "sign_in": False},
           "capture_allowed": {"allowed": True}, "robots": {"verdict": "allowed"},
           "space": {"space": "acme/fox-demo", "licence": "mit"},
           "steps": [], "steps_done": [], "duration_s": 2.0, "max_seconds": 30.0,
           "capped": False, "fps": 30, "width": 1080, "height": 1920, "frames": 60,
           "captured_at": "2026-10-11T12:00:00Z", "user_agent": "Example",
           "channel": "example-tech", "recorder": "capture_tool.py (CF-0567)"}
    rec.update(over)
    return rec


_MP4 = {}


def ffmpeg_ok():
    try:
        out = subprocess.run([arc.ffmpeg_bin(), "-version"], capture_output=True, timeout=30)
        return out.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def tiny_mp4():
    """A 2 s 1080x1920 H.264 at 30 fps, made once by the local ffmpeg."""
    if "p" not in _MP4:
        d = Path(tempfile.mkdtemp(dir=TMP))
        p = d / "tiny.mp4"
        out = subprocess.run([arc.ffmpeg_bin(), "-v", "error", "-y", "-f", "lavfi", "-i",
                              "color=c=navy:s=1080x1920:d=2:r=30", "-c:v", "libx264",
                              "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(p)],
                             capture_output=True, text=True, timeout=120)
        assert out.returncode == 0 and p.is_file(), out.stderr
        _MP4["p"] = p
    return _MP4["p"]


def capture_dir(side=True, side_rec=None, fid=FID):
    """A recorder's out_dir holding `<fid>.mp4` and (optionally) its sidecar."""
    d = Path(tempfile.mkdtemp(dir=TMP))
    shutil.copyfile(tiny_mp4(), d / f"{fid}.mp4")
    if side:
        (d / f"{fid}{oc.SIDECAR_SUFFIX}").write_text(json.dumps(side_rec or sidecar()))
    return d


def run_fetch(cand, cache=None, extra=()):
    """fetch_footage.main() in-process on the own-capture path; (code, out, err, cache)."""
    cache = cache or Path(tempfile.mkdtemp(dir=TMP)) / "pool" / "media"
    cache.mkdir(parents=True, exist_ok=True)
    old = (ff.CACHE, ff.INDEX)
    ff.CACHE, ff.INDEX = cache, cache / "index.json"
    argv = ["fetch_footage.py", PAGE, "--own-capture-json", json.dumps(cand), *extra]
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
        ff.CACHE, ff.INDEX = old
    return code, out.getvalue(), err.getvalue(), cache


def entries(cache):
    p = cache / "index.json"
    return json.loads(p.read_text())["entries"] if p.exists() else []


def media(cache):
    return sorted(p.name for p in cache.iterdir() if p.name != "index.json")


# --------------------------------------------------------------------------
# ids
# --------------------------------------------------------------------------

def test_ids():
    assert oc.is_own_capture(CID) and oc.is_own_capture(FID)
    assert not oc.is_own_capture("own_capture:") and not oc.is_own_capture("dQw4w9WgXcQ")
    assert not oc.is_own_capture("nasa-abc")
    assert oc.file_id(CID) == FID and oc.file_id(FID) == FID
    assert oc.file_id("own_capture:a b/c") == "own_capture-a_b_c"
    assert oc.candidate_name(FID) == CID and oc.candidate_name(CID) == CID
    assert ib.source_file_id(CID) == FID
    assert ib.source_file_id("nasa:x y") == "nasa-x_y"
    assert ib.source_file_id("dQw4w9WgXcQ") == "dQw4w9WgXcQ"
    assert oc.sidecar_path(Path("/p") / f"{FID}.mp4").name == f"{FID}.own_capture.json"


def test_walk_and_records_use_the_file_id():
    topic = {"topic_id": "001", "evidence": {
        "youtube_video_ids": [CID, "dQw4w9WgXcQ"],
        "footage_candidates": [{"video_id": CID, "kind": "own_capture",
                                "source_url": PAGE},
                               {"video_id": "dQw4w9WgXcQ"}]}}
    recs = ib.candidate_records(topic)
    assert sorted(recs) == ["dQw4w9WgXcQ", FID], recs
    assert recs[FID]["candidate_id"] == CID, recs
    st = ib.walk_state(topic)
    assert list(st["queue"]) == [FID, "dQw4w9WgXcQ"], st


# --------------------------------------------------------------------------
# fetch_footage.py --own-capture-json
# --------------------------------------------------------------------------

def test_a_capture_is_copied_into_the_pool():
    if not ffmpeg_ok():
        print("SKIP: no local ffmpeg")
        return
    d = capture_dir()
    rights = sr.own_capture_rights(FID, None, sidecar())
    cand = {"video_id": CID, "candidate_id": CID, "capture_file": str(d / f"{FID}.mp4"),
            "title": "Fox demo"}
    code, out, err, cache = run_fetch(cand, extra=["--rights-json", json.dumps(rights)])
    assert code == 0, (out, err)
    assert out.strip() == f"fetched -> {cache / (FID + '.mp4')}", out
    assert media(cache) == [f"{FID}.mp4", f"{FID}.own_capture.json"], media(cache)
    assert json.loads((cache / f"{FID}.own_capture.json").read_text()) == sidecar()
    # the recorder's copy stays where it was
    assert (d / f"{FID}.mp4").is_file() and (d / f"{FID}.own_capture.json").is_file()
    [e] = entries(cache)
    assert e["id"] == FID and e["candidate_id"] == CID and e["url"] == PAGE, e
    assert e["official_channel"] is True and abs(e["duration"] - 2.0) < 0.2, e
    assert e["own_capture"]["capture_host"] == "hf.space", e
    assert e["own_capture"]["space_licence"] == "mit", e
    assert e["rights"]["licence"] == "own_capture", e
    # a second fetch is a cache hit by file id
    code, out, err, _ = run_fetch(cand, cache=cache)
    assert code == 0 and out.startswith("cached -> "), (out, err)
    assert len(entries(cache)) == 1
    # the sidecar goes with the mp4 when the pool evicts it
    assert ff.sidecars(cache / f"{FID}.mp4")[-1] == cache / f"{FID}.own_capture.json"
    assert not any(p.name.endswith(".own_capture.json")
                   for p in ff.sidecars(cache / "dQw4w9WgXcQ.mp4"))


def test_the_inbox_is_the_fallback():
    if not ffmpeg_ok():
        print("SKIP: no local ffmpeg")
        return
    root = Path(tempfile.mkdtemp(dir=TMP))
    cache = root / "pool" / "media"           # the inbox is <root>/shared/own-captures
    inbox = root / "shared" / "own-captures"
    inbox.mkdir(parents=True)
    shutil.copyfile(tiny_mp4(), inbox / f"{FID}.mp4")
    (inbox / f"{FID}.own_capture.json").write_text(json.dumps(sidecar()))
    code, out, err, _ = run_fetch({"video_id": CID}, cache=cache)
    assert code == 0 and out.startswith("fetched -> "), (out, err)
    assert (cache / f"{FID}.mp4").is_file()


def _refused(cand, code_word, cache=None):
    code, out, err, cache = run_fetch(cand, cache=cache)
    assert code != 0, (out, err)
    assert "own_capture_refused" in err and code_word in err, err
    assert media(cache) == [], media(cache)
    assert entries(cache) == []
    return err


def test_the_refusals():
    if not ffmpeg_ok():
        print("SKIP: no local ffmpeg")
        return
    # no recording anywhere
    _refused({"video_id": CID, "capture_file": str(TMP / "nowhere.mp4")}, oc.NO_RECORDING)
    # no sidecar beside it
    d = capture_dir(side=False)
    _refused({"video_id": CID, "capture_file": str(d / f"{FID}.mp4")}, oc.NO_SIDECAR)
    # an origin that is not ours
    d = capture_dir(side_rec=sidecar(origin="vendor_official"))
    _refused({"video_id": CID, "capture_file": str(d / f"{FID}.mp4")}, oc.NOT_OWN_CAPTURE)
    d = capture_dir(side_rec=sidecar(licence="cc_by"))
    _refused({"video_id": CID, "capture_file": str(d / f"{FID}.mp4")}, oc.NOT_OWN_CAPTURE)
    # a sidecar that describes another recording
    d = capture_dir(side_rec=sidecar(file_id="own_capture-other-20261011t000000z"))
    _refused({"video_id": CID, "capture_file": str(d / f"{FID}.mp4")}, oc.FILE_ID_MISMATCH)
    # ffprobe disagrees on the length
    d = capture_dir(side_rec=sidecar(duration_s=12.0))
    err = _refused({"video_id": CID, "capture_file": str(d / f"{FID}.mp4")},
                   oc.DURATION_MISMATCH)
    assert "12.0 s" in err, err
    # ... and on the frame size
    d = capture_dir(side_rec=sidecar(width=720, height=1280))
    _refused({"video_id": CID, "capture_file": str(d / f"{FID}.mp4")}, oc.SIZE_MISMATCH)
    # a file with no picture in it
    d = Path(tempfile.mkdtemp(dir=TMP))
    (d / f"{FID}.mp4").write_bytes(b"not a video at all")
    (d / f"{FID}.own_capture.json").write_text(json.dumps(sidecar()))
    _refused({"video_id": CID, "capture_file": str(d / f"{FID}.mp4")}, oc.NO_PICTURE)


def test_the_refusal_rules_without_ffmpeg():
    assert oc.sidecar_refusals(FID, None)[0][0] == oc.NO_SIDECAR
    assert oc.sidecar_refusals(FID, sidecar()) == []
    assert [c for c, _ in oc.sidecar_refusals(FID, sidecar(schema="other/1"))] == \
        [oc.NOT_OWN_CAPTURE]
    info = {"duration": 2.03, "width": 1080, "height": 1920}
    assert oc.probe_refusals(FID, sidecar(), info) == []
    # a frame or two apart is the same take; a second and a half is not
    assert oc.probe_refusals(FID, sidecar(duration_s=2.9), info) == []
    assert [c for c, _ in oc.probe_refusals(FID, sidecar(duration_s=3.6), info)] == \
        [oc.DURATION_MISMATCH]
    # a long take is held to a tenth of its length
    long_info = dict(info, duration=27.5)
    assert oc.probe_refusals(FID, sidecar(duration_s=30.0), long_info) == []
    assert oc.probe_refusals(FID, sidecar(duration_s=None), info)[0][0] == oc.DURATION_MISMATCH
    assert oc.probe_refusals(FID, sidecar(), None)[0][0] == oc.NO_PICTURE


# --------------------------------------------------------------------------
# rights
# --------------------------------------------------------------------------

TECH = {
    "footage_origins": [
        {"id": "own_capture", "licence": "own_capture",
         "attribution": {"required": False, "requested": False,
                         "credit": "none - our own recording", "where": "description",
                         "on_screen": False}},
        {"id": "vendor_official", "licence": "youtube_official_upload",
         "attribution": {"required": False, "requested": True,
                         "credit": "the channel's name and the video's link",
                         "where": "description", "on_screen": False}}],
    "official_channels": [
        {"pattern": "openai", "origin": "vendor_official", "role": "proof_quote",
         "seen_as": "OpenAI",
         "channels": [{"id": "UCexample000000000000040", "title": "OpenAI"}]}],
}
# ExampleScience / ExampleFilm: official channels without a role.
SCIENCE = {"footage_origins": [{"id": "nasa", "attribution": {"credit": "NASA"}}],
           "official_channels": [{"pattern": "nasa", "origin": "official",
                                  "channels": [{"id": "UCexample000000000000010"}]}]}
REEL = {"official_channels": [{"pattern": "zenith",
                               "channels": [{"id": "UCexample000000000000070"}]}]}

BASE_KEYS = {"judged", "accepted", "licence", "short_name", "license_url",
             "attribution", "share_alike", "footage_origin", "credit", "credit_from",
             "on_screen", "where", "source_url", "upload_origin", "reason", "read_from"}


def test_own_capture_rights():
    r = sr.own_capture_rights(FID, {"video_id": CID}, sidecar(), TECH)
    assert r["judged"] is True and r["accepted"] is True, r
    assert r["licence"] == "own_capture" and r["footage_origin"] == "own_capture", r
    assert r["credit"] is None and r["credit_from"] is None and r["attribution"] == "none", r
    assert r["url"] == PAGE and r["source_url"] == PAGE, r
    assert r["capture_host"] == "hf.space" and r["host"] == "acme-fox-demo.hf.space", r
    assert r["captured_at"] == "2026-10-11T12:00:00Z" and r["space_licence"] == "mit", r
    assert r["candidate_id"] == CID and r["read_from"] == "sidecar", r
    assert sr.is_own_capture_rights(r)
    # without the sidecar: the candidate's page, the same kind
    r = sr.own_capture_rights(CID, {"source_url": PAGE}, None, None)
    assert r["licence"] == "own_capture" and r["url"] == PAGE, r
    assert r["read_from"] == "candidate" and r["candidate_id"] == CID, r
    # an own capture is never refused on its licence
    assert sr.refusal(FID, {"video_id": CID}, TECH) is None


def test_vendor_official_rights():
    cand = {"video_id": "abcDEF12345", "channel_id": "UCexample000000000000040",
            "channel_title": "OpenAI"}
    r = sr.rights_of("abcDEF12345", cand, TECH)
    assert r["footage_origin"] == "vendor_official", r
    assert r["role"] == "proof_quote" and r["channel_id"] == "UCexample000000000000040", r
    assert r["channel_title"] == "OpenAI", r
    assert r["credit"] == "the channel's name and the video's link", r
    assert r["credit_from"] == "footage_origins" and r["where"] == "description", r
    # anyone else's upload, or a title alone, is not a quote source
    for c in ({"channel_id": "UCsomeoneelse000000000"}, {"channel_title": "OpenAI"},
              {"role": "proof_quote"}):
        r = sr.rights_of("abcDEF12345", c, TECH)
        assert "role" not in r and r["footage_origin"] is None, r


def test_reel_and_science_records_do_not_change():
    cands = [
        {"video_id": "abcDEF12345", "channel_id": "UCexample000000000000010",
         "footage_origin": "nasa", "origin": "official"},
        {"video_id": "abcDEF12345", "channel_id": "UCexample000000000000070"},
        {"video_id": "abcDEF12345", "licence": {"id": "cc_by", "judged": True,
                                                "accepted": True, "short_name": "CC BY"}},
        {},
    ]
    for doc in (SCIENCE, REEL, {}, None):
        for cand in cands:
            got = sr.rights_of("abcDEF12345", cand, doc)
            assert set(got) == BASE_KEYS, (doc, cand, got)
            without = (None if doc is None
                       else {k: v for k, v in doc.items() if k != "official_channels"})
            assert got == sr.rights_of("abcDEF12345", cand, without), (doc, cand)


# --------------------------------------------------------------------------
# ingest
# --------------------------------------------------------------------------

def _topic(extra=None):
    cand = {"video_id": CID, "kind": "own_capture", "source_url": PAGE,
            "title": "Fox demo", "nature": "demo", "duration_seconds": 99999,
            "channel_title": "Somebody"}
    cand.update(extra or {})
    return {"topic_id": "001", "evidence": {"youtube_video_ids": [CID],
                                            "footage_candidates": [cand]}}


def test_ingest_takes_an_own_capture():
    batch = Path(tempfile.mkdtemp(dir=TMP))
    captures = batch / "captures"
    captures.mkdir()
    (captures / f"{FID}.mp4").write_bytes(b"\0" * 1024)
    (captures / f"{FID}.own_capture.json").write_text(json.dumps(sidecar()))
    asked = []

    def fetch(vid, note, rights=None, record=None, licences=None,
              max_seconds=None):
        asked.append({"vid": vid, "record": record,
                      "max_seconds": max_seconds, "rights": rights})
        p = POOL / f"{vid}.mp4"
        p.write_bytes(b"\0" * 2_500_000)
        return ib.FetchResult(str(p), False)

    def measure(*a, **k):
        raise AssertionError("an own capture was measured")

    old = ib.CAPTURE_DIRS
    ib.CAPTURE_DIRS = ib.capture_dirs(batch_dir=batch)
    tight = ib.Ceiling(limits={"default": 60}, configured=True, config_path=None, key=None)
    measurements = []
    try:
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            fetched, _a, _s, failed, by_topic = ib.ingest(
                [_topic()], {}, "b", 4, True, fetch=fetch, index=lambda p: None,
                fingerprint=lambda p: None, log=lambda m, file=None: None,
                sleep=lambda s: None, pause=0, wanted=1,
                ceiling=tight,
                measure=measure, measurements=measurements, origins=TECH)
    finally:
        ib.CAPTURE_DIRS = old
    assert not failed, failed
    assert by_topic["001"] == [FID], by_topic
    [a] = asked
    assert a["vid"] == FID and a["max_seconds"] is None, a
    assert a["record"]["capture_file"] == str(captures / f"{FID}.mp4"), a
    assert a["record"]["candidate_id"] == CID, a
    assert a["rights"]["licence"] == "own_capture", a
    assert a["rights"]["capture_host"] == "hf.space", a
    [f] = fetched
    assert f["candidate_id"] == CID and f["rights"]["footage_origin"] == "own_capture", f
    assert f["rights"]["url"] == PAGE and f["rights"]["credit"] is None, f
    [m] = measurements
    assert m["measured_from"] == "own_capture" and m["ceiling_seconds"] is None, m
    assert ib.measure_candidate(FID, {}).source == ib.OWN_CAPTURE_MEASURE


def test_fetch_source_builds_the_copy_command():
    seen = {}

    def run_child(cmd, **kw):
        seen["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout=f"fetched -> /x/{FID}.mp4\n",
                               stderr="", timed_out=False)

    saved = ib.runlog.run_child
    ib.runlog.run_child = run_child
    d = Path(tempfile.mkdtemp(dir=TMP))
    (d / f"{FID}.mp4").write_bytes(b"x")
    old = ib.CAPTURE_DIRS
    ib.CAPTURE_DIRS = [d]
    try:
        rights = sr.own_capture_rights(FID, None, sidecar())
        res = ib.fetch_source(FID, "n", max_seconds=60, rights=rights,
                              record={"video_id": CID, "source_url": PAGE})
        cmd = seen["cmd"]
        assert res.path == f"/x/{FID}.mp4", res
        assert cmd[2] == PAGE, cmd
        for flag in ("--max-duration", "--archive-json"):
            assert flag not in cmd, (flag, cmd)
        rec = json.loads(cmd[cmd.index("--own-capture-json") + 1])
        assert rec["capture_file"] == str(d / f"{FID}.mp4") and rec["candidate_id"] == CID
        assert json.loads(cmd[cmd.index("--rights-json") + 1])["licence"] == "own_capture"
    finally:
        ib.runlog.run_child = saved
        ib.CAPTURE_DIRS = old


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
