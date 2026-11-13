#!/usr/bin/env python3
"""CF-0080: re-uploads of one trailer under several video_ids must be caught
before they are indexed a second time, and must not count as extra sources.

Batch 2026-09-03T2037Z: topics 002/004/006/007 each had three uploads of one
trailer; every one was fetched, shot-detected, CLIP-embedded and described
(about half of a 3h19m window), and footage_sides() then built an A-B-A-B
alternation out of two copies of the same file.

Everything here runs on synthetic clips from ffmpeg's lavfi sources - no
network, no CLIP - and the whole file takes a few seconds:

  - the same clip twice, re-encoded smaller, trimmed at the head, and sped up
    by the PAL ratio -> alias, with the offset / time scale reported;
  - a different clip of the same length -> distinct;
  - the threshold and the fingerprint kind are pinned (a change is a
    recalibration, not a tweak);
  - ingest() hands downstream canonical ids only, records the alias with the
    agreed shape, never dedups across topics, never indexes an alias;
  - the DEDUP log line has the RUN_LOG format;
  - the fingerprint sidecar is reused (never re-taken), read from the index
    header too, and evicted with the media.

No pytest dependency - plain asserts, run directly.
"""
import io
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import source_fingerprint as sf  # noqa: E402
import ingest_batch  # noqa: E402


def no_measure(vid, record=None):
    """CF-0302: the duration ceiling's measurement seam, injected away.

    `ingest()` reads how long a candidate is before it downloads it, and the
    real reader asks YouTube. Nothing in this file is about that ceiling, so
    the answer here is "nobody could tell" - which is never a refusal - and no
    request is made.
    """
    return ingest_batch.Measured(None, "metadata", "not measured in this test")

import fetch_footage  # noqa: E402

FFMPEG = sf.FFMPEG
from _tmproot import tmp_root  # noqa: E402
TMP = tmp_root("cf0080-")   # CF-0489: removed at exit
from _temp_pool import fence_cache_index  # noqa: E402
# CF-0683: fetch_footage.INDEX (rights_for, measure_candidate) on a temp pool, not the live one.
fence_cache_index(TMP / "ff-pool")
SECONDS = 14  # > 2 * MIN_OVERLAP_FRAMES / SAMPLE_FPS, with room for a 1 s trim


def ff(*args):
    out = subprocess.run([FFMPEG, "-v", "error", "-y", *args], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr


def lavfi(name, source, extra=()):
    dest = TMP / f"{name}.mp4"
    ff("-f", "lavfi", "-i", f"{source}=size=320x180:rate=25:duration={SECONDS}",
       *extra, "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(dest))
    return dest


# The clips, made once. `testsrc2` has moving colour bars and a counter;
# `testsrc` is a different picture of the same length.
A = lavfi("A", "testsrc2")
A_COPY = TMP / "A_copy.mp4"
shutil.copy(A, A_COPY)
A_REENC = TMP / "A_reenc.mp4"
ff("-i", str(A), "-vf", "scale=256:144", "-c:v", "libx264", "-preset", "ultrafast",
   "-crf", "35", "-pix_fmt", "yuv420p", str(A_REENC))
A_TRIM = TMP / "A_trim.mp4"
ff("-ss", "1", "-i", str(A), "-c:v", "libx264", "-preset", "ultrafast",
   "-pix_fmt", "yuv420p", str(A_TRIM))
A_PAL = TMP / "A_pal.mp4"   # played 25/23.976 faster, like 1RnyZgfN-JY
ff("-i", str(A), "-vf", f"setpts=PTS/{25 / 23.976},fps=25", "-c:v", "libx264",
   "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(A_PAL))
D = lavfi("D", "testsrc")

FP = {p: sf.fingerprint(p) for p in (A, A_COPY, A_REENC, A_TRIM, A_PAL, D)}


def test_identical_clip_is_alias():
    r = sf.compare(FP[A], FP[A_COPY])
    assert sf.is_duplicate(r), r
    assert r["distance"] < 1.0 and r["offset_seconds"] == 0.0 and r["time_scale"] == 1.0, r


def test_reencoded_clip_is_alias():
    r = sf.compare(FP[A], FP[A_REENC])
    assert sf.is_duplicate(r), r


def test_trimmed_clip_is_alias_with_offset():
    r = sf.compare(FP[A], FP[A_TRIM])
    assert sf.is_duplicate(r), r
    assert abs(abs(r["offset_seconds"]) - 1.0) <= 0.5, r
    r2 = sf.compare(FP[A_TRIM], FP[A])
    assert sf.is_duplicate(r2) and r2["offset_seconds"] == -r["offset_seconds"], (r, r2)


def test_pal_speed_clip_is_alias_via_time_scale():
    r = sf.compare(FP[A], FP[A_PAL])
    assert sf.is_duplicate(r), r
    assert r["time_scale"] != 1.0, r
    fixed = sf.compare(FP[A], FP[A_PAL], scales=(1.0,))
    assert fixed["distance"] > r["distance"], (fixed, r)


def test_different_clip_same_length_is_distinct():
    r = sf.compare(FP[A], FP[D])
    assert r is not None and not sf.is_duplicate(r), r
    assert r["distance"] > sf.DUPLICATE_MAX_DISTANCE + 5, r  # with margin, not at the edge


def test_threshold_and_kind_pinned():
    """Calibrated on batch 2026-09-03T2037Z: duplicates 0.9-7.5, distinct
    >= 20.2. Moving any of these is a recalibration and bumps the kind."""
    assert sf.DUPLICATE_MAX_DISTANCE == 12.0
    assert sf.FINGERPRINT_KIND == "dhash9x8-2fps-v1"
    assert sf.SAMPLE_FPS == 2 and sf.MAX_SECONDS == 300
    assert sf.MIN_OVERLAP_FRAMES == 20 and sf.DARK_LUMA == 12.0
    assert sf.TIME_SCALES == (1.0, 25 / 23.976, 23.976 / 25)
    assert FP[A]["kind"] == sf.FINGERPRINT_KIND and FP[A]["frames"] == SECONDS * sf.SAMPLE_FPS


def test_mismatched_kind_or_too_short_is_not_compared():
    other = dict(FP[A_COPY], kind="something-else")
    assert sf.compare(FP[A], other) is None
    short = dict(FP[A], hashes=FP[A]["hashes"][:6], luma=FP[A]["luma"][:6])
    assert sf.compare(FP[A], short) is None and not sf.is_duplicate(None)


def test_dark_frames_do_not_match_everything():
    black = dict(FP[A], hashes=["0" * 16] * len(FP[A]["hashes"]), luma=[0.0] * len(FP[A]["luma"]))
    assert sf.compare(black, black) is None  # nothing non-dark to align on


def test_dedup_line_format():
    line = ingest_batch.dedup_line("GyEpwGQIEZw", "SJVmeJaS44s", 1.82)
    assert line == "DEDUP GyEpwGQIEZw is a re-upload of SJVmeJaS44s (distance 1.82)"
    assert re.fullmatch(r"DEDUP \S+ is a re-upload of \S+ \(distance \d+(\.\d+)?\)", line)


def _run_ingest(topics, max_per_topic=3):
    media = {"a": A, "a2": A_REENC, "a3": A_TRIM, "d": D, "gone": None}
    fetched_ids, indexed, lines = [], [], []

    def fetch(vid, note):
        fetched_ids.append(vid)
        if media[vid] is None:
            raise RuntimeError("yt-dlp failed")
        return media[vid]

    def log(msg, file=None):
        lines.append(msg)

    # CF-0253: the pacing between downloads is real in production and
    # injected away here - these tests are about dedup, not about waiting.
    result = ingest_batch.ingest(topics, {}, "batch-x", max_per_topic, False,
                                 fetch=fetch, index=indexed.append,
                                 fingerprint=lambda p: FP[Path(p)], log=log,
                                 sleep=lambda s: None, pause=0,
                                 measure=no_measure)   # CF-0302, no network
    return result, fetched_ids, indexed, lines


def test_ingest_aliases_within_topic_and_hands_canonical_ids_downstream():
    """The alias does not count, so the walk goes on to the next candidate.

    CF-0129 made that visible: `a2` is a re-upload of `a`, so after it the
    topic still holds one source and takes `d` - and stops there, two
    canonical sources in, with `a3` never downloaded. Before the floor the
    stage took all four ids and re-uploads ate the budget.
    """
    topics = [{"topic_id": "t1", "evidence": {"youtube_video_ids": ["a", "a2", "d", "a3"]}}]
    (fetched, aliases, skipped, failed, by_topic), fetched_ids, indexed, lines = \
        _run_ingest(topics, max_per_topic=4)
    assert [f["video_id"] for f in fetched] == ["a", "d"]
    assert all(f["topic_id"] == "t1" for f in fetched)
    assert by_topic == {"t1": ["a", "d"]}
    assert fetched_ids == ["a", "a2", "d"] and "a3" not in fetched_ids
    assert [a["video_id"] for a in aliases] == ["a2"]
    assert all(a["alias_of"] == "a" for a in aliases)
    for a in aliases:
        assert set(a) >= {"topic_id", "video_id", "alias_of", "distance", "fingerprint_kind",
                          "offset_seconds", "overlap_frames", "path"}, a
        assert a["fingerprint_kind"] == sf.FINGERPRINT_KIND
        assert a["distance"] <= sf.DUPLICATE_MAX_DISTANCE
    # an alias is never indexed; the canonical is (its index does not exist yet)
    assert indexed == [A, D]
    assert [l for l in lines if l.startswith("DEDUP")] == [
        ingest_batch.dedup_line("a2", "a", aliases[0]["distance"])]
    # the topic met the floor, so nothing about it is refused
    assert not skipped and not failed


def test_ingest_never_dedups_across_topics():
    topics = [{"topic_id": "t1", "evidence": {"youtube_video_ids": ["a"]}},
              {"topic_id": "t2", "evidence": {"youtube_video_ids": ["a2"]}}]
    (fetched, aliases, _, _, by_topic), _, indexed, _ = _run_ingest(topics)
    assert [f["video_id"] for f in fetched] == ["a", "a2"] and aliases == []
    assert by_topic == {"t1": ["a"], "t2": ["a2"]}
    assert indexed == [A, A_REENC]


def test_ingest_cap_counts_ids_tried_and_failures_do_not_break_dedup():
    topics = [{"topic_id": "t1", "evidence": {"youtube_video_ids": ["gone", "a", "a2", "d"]}}]
    (fetched, aliases, _, failed, by_topic), fetched_ids, _, _ = _run_ingest(topics, 3)
    assert fetched_ids == ["gone", "a", "a2"]
    # CF-0253: a failure is a record now, not a pair - with the funnel's
    # reason code and the rung it was refused at.
    assert [f["video_id"] for f in failed] == ["gone"]
    assert failed[0]["error"] == "yt-dlp failed"
    assert failed[0]["reason_code"] == ingest_batch.FUNNEL_REASON_CODE
    assert failed[0]["refused_at"] == ingest_batch.RUNG_FIRST_PASS
    assert [f["video_id"] for f in fetched] == ["a"] and [a["video_id"] for a in aliases] == ["a2"]


def test_report_and_work_dir_alias_record():
    topics = [{"topic_id": "t1", "evidence": {"youtube_video_ids": ["a", "a2"]}}]
    (fetched, aliases, skipped, failed, by_topic), *_ = _run_ingest(topics)
    batch = TMP / "batch"
    report = ingest_batch.build_report(batch, fetched, aliases, skipped, failed, by_topic)
    assert {"fetched", "sources_by_topic", "aliases", "dedup_log", "skipped_topics",
            "failed", "note"} <= set(report)
    assert [f["video_id"] for f in report["fetched"]] == ["a"]
    assert report["dedup_log"] == [ingest_batch.dedup_line("a2", "a", aliases[0]["distance"])]
    dest = ingest_batch.write_aliases(batch, aliases)
    assert dest == batch / "work" / ingest_batch.ALIASES_FILE
    rec = json.load(open(dest))
    assert list(rec) == ["t1"] and len(rec["t1"]) == 1
    assert set(rec["t1"][0]) == {"video_id", "alias_of", "distance", "fingerprint_kind",
                                 "offset_seconds", "overlap_frames"}
    assert rec["t1"][0]["video_id"] == "a2" and rec["t1"][0]["alias_of"] == "a"


def test_sidecar_is_reused_read_from_index_header_and_evicted_with_media():
    v = TMP / "side" / "v.mp4"
    v.parent.mkdir()
    shutil.copy(A, v)
    fp = sf.load_or_make(v)
    assert sf.sidecar_path(v).exists() and fp == FP[A]
    original = sf.fingerprint
    sf.fingerprint = lambda *a, **k: (_ for _ in ()).throw(AssertionError("re-taken"))
    try:
        assert sf.load_or_make(v) == fp                       # sidecar, not ffmpeg
        sf.sidecar_path(v).unlink()
        json.dump({"shots": [], "fingerprint": fp}, open(v.with_suffix(".shots.json"), "w"))
        assert sf.load_or_make(v, save=False) == fp           # index header, not ffmpeg
        json.dump({"shots": [], "fingerprint": dict(fp, kind="old")},
                  open(v.with_suffix(".shots.json"), "w"))
        try:
            sf.load_or_make(v, save=False)
            assert False, "an old-kind fingerprint must be re-taken"
        except AssertionError as e:
            assert str(e) == "re-taken"
    finally:
        sf.fingerprint = original
    assert sf.sidecar_path(v) in fetch_footage.sidecars(v)


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
    shutil.rmtree(TMP, ignore_errors=True)
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
