#!/usr/bin/env python3
"""CF-0238: a split probe that measured "no cut" and one that did not measure
at all are two different records.

Before: probe_shot_span() put SPLIT_SCORE_FLOOR inside `select`, so a span
with no frame above it (a static one-take shot, in any codec) left the `[so]`
null output with no frame, ffmpeg 9 exited 234 ("Could not open encoder
before EOF"), and the probe read the empty file as "no cut" - the same thing
a real crash produced. Now the branch passes every frame, the floor is
applied in Python, and an ffmpeg exit or an empty series raises ProbeFailed,
which split_heterogeneous() records on the shot (`split_probe_failed`), in
split_stats (`probe_failed`) and on the script's run event.

The first three tests run real ffmpeg on clips generated into a temp dir
(nothing from the pool); the rest stub the probe. No pytest dependency.
"""
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))
import index_footage as ix  # noqa: E402
import shot_schema  # noqa: E402


def make_clip(path, spec, codec="mpeg4"):
    """A synthetic clip from lavfi `spec` - never a pool file."""
    subprocess.run([ix.FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "lavfi",
                    "-i", spec, "-c:v", codec, "-pix_fmt", "yuv420p", str(path)],
                   check=True, capture_output=True)
    return path


def has_encoder(name):
    out = subprocess.run([ix.FFMPEG, "-hide_banner", "-encoders"],
                         capture_output=True, text=True).stdout
    return f" {name} " in out


def test_a_static_span_is_measured_as_no_cut_not_failed():
    """The rc-234 case itself: no frame reaches the floor. Every codec the
    ffmpeg build can write, VP9 included when libvpx is there."""
    codecs = [("mpeg4", "mp4")] + ([("libvpx-vp9", "webm")] if has_encoder("libvpx-vp9") else [])
    for codec, ext in codecs:
        with tempfile.TemporaryDirectory() as tmp:
            clip = make_clip(Path(tmp) / f"static.{ext}",
                             "color=c=gray:s=320x180:r=25:d=6", codec)
            out = Path(tmp) / "probe"
            out.mkdir()
            frames, times, scores, lumas = ix.probe_shot_span(clip, 0.0, 6.0, out)
            assert len(frames) == ix.SPLIT_SAMPLES, (codec, len(frames))
            assert scores == [], (codec, scores)
            assert len(lumas) > 100, (codec, len(lumas))


def test_a_hard_cut_is_still_found_and_the_floor_still_applies():
    with tempfile.TemporaryDirectory() as tmp:
        black = make_clip(Path(tmp) / "a.mp4", "color=c=black:s=320x180:r=25:d=3")
        white = make_clip(Path(tmp) / "b.mp4", "color=c=white:s=320x180:r=25:d=3")
        lst = Path(tmp) / "list.txt"
        lst.write_text(f"file '{black}'\nfile '{white}'\n")
        clip = Path(tmp) / "cut.mp4"
        subprocess.run([ix.FFMPEG, "-hide_banner", "-v", "error", "-y", "-f", "concat",
                        "-safe", "0", "-i", str(lst), "-c", "copy", str(clip)],
                       check=True, capture_output=True)
        out = Path(tmp) / "probe"
        out.mkdir()
        _, _, scores, _ = ix.probe_shot_span(clip, 0.0, 6.0, out)
        assert scores, scores
        assert all(v >= ix.SPLIT_SCORE_FLOOR for _, v in scores), scores
        assert any(v >= ix.SPLIT_THRESHOLD and 2.5 < t < 3.5 for t, v in scores), scores


def test_an_unreadable_source_raises_instead_of_reading_as_no_cut():
    with tempfile.TemporaryDirectory() as tmp:
        bad = Path(tmp) / "broken.mp4"
        bad.write_bytes(b"\x00not a video\x00" * 64)
        out = Path(tmp) / "probe"
        out.mkdir()
        try:
            ix.probe_shot_span(bad, 0.0, 6.0, out)
        except ix.ProbeFailed as e:
            assert "exited" in str(e), e
        else:
            raise AssertionError("a broken source must not come back as an empty series")


class _Runlog:
    """Stands in for runlog: records annotate() calls, runs nothing."""

    def __init__(self):
        self.notes = []

    def annotate(self, **kw):
        self.notes.append(kw)


def run_split(shots, probe, profiles=None):
    saved = (ix.probe_shot_span, ix.sample_dispersion, ix.runlog)
    fake = _Runlog()
    ix.probe_shot_span = probe
    ix.sample_dispersion = lambda frames: 1.0
    ix.runlog = fake
    try:
        out, stats = ix.split_heterogeneous(Path("/nonexistent.mp4"), shots,
                                            log=lambda _m: None, profiles=profiles)
    finally:
        ix.probe_shot_span, ix.sample_dispersion, ix.runlog = saved
    return out, stats, fake.notes


def failing_probe(*_a, **_k):
    raise ix.ProbeFailed("ffmpeg exited 234: Could not open encoder before EOF")


def quiet_probe(path, start, end, out_dir, samples=ix.SPLIT_SAMPLES):
    return ["f"] * samples, [start] * samples, [], [(start, 50.0)]


def test_a_failed_probe_is_recorded_on_the_shot_the_stats_and_the_run_event():
    shots = [{"start": 0.0, "end": 12.0}, {"start": 12.0, "end": 30.0}]
    out, stats, notes = run_split(shots, failing_probe)
    assert [(s["start"], s["end"]) for s in out] == [(0.0, 12.0), (12.0, 30.0)], out
    assert all("ProbeFailed" in s["split_probe_failed"] for s in out), out
    assert stats["probe_failed"] == 2 and stats["probed"] == 2, stats
    assert notes and notes[-1]["split_probe_failed"] == 2, notes
    assert notes[-1]["split_probe_failed_first"]["start"] == 0.0, notes
    # The caller's own dicts are not mutated.
    assert "split_probe_failed" not in shots[0], shots


def test_an_honest_no_cut_leaves_no_trace():
    shots = [{"start": 0.0, "end": 12.0}]
    out, stats, notes = run_split(shots, quiet_probe)
    assert out == shots and "split_probe_failed" not in out[0], out
    assert stats["probe_failed"] == 0 and stats["probed"] == 1, stats
    assert notes == [], notes


def test_short_shots_are_never_probed_and_never_flagged():
    shots = [{"start": 0.0, "end": ix.SPLIT_MIN_SECONDS - 0.5}]
    out, stats, notes = run_split(shots, failing_probe)
    assert out == shots and stats["probe_failed"] == 0 and notes == [], (out, stats)


def test_an_index_with_and_without_the_new_fields_is_valid():
    """Old indexes have neither `probe_failed` nor `split_probe_failed`: that
    is "unknown", not an error, and the new fields do not trip the schema."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "x.mp4"
        base = {"index": 0, "start": 0.0, "end": 12.0, "tile_at": 6.0}
        old = {"source": str(src), "shots": [dict(base)]}
        new = {"source": str(src), "split_stats": {"probed": 1, "probe_failed": 1},
               "shots": [dict(base, split_probe_failed="ProbeFailed: x")]}
        for index in (old, new):
            shot_schema.require_valid(index, Path(tmp) / "x.shots.json")


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
