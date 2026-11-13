#!/usr/bin/env python3
"""CF-0674: the Editor writes `videos/<slug>.jpg` beside `videos/<slug>.mp4`.

All on synthetic media built with ffmpeg's lavfi sources in a temp tree (no
real batch, no pool, no network):

- a 9:16 render -> a 720x1280 JPEG of at most 200 KB from the hook's seconds;
- a 16:9 render -> still 720x1280 (centre crop to the aspect);
- no video -> no error and no file;
- black opening seconds -> the frame comes from after them, never the black;
- the end card / an opaque insert over the hook -> the frame is not under it;
- of the open, lit hook frames the sharpest wins, else the one nearest 1 s;
- nothing usable -> a jpg of an older render is removed, a newer one kept;
- write_batch_metadata writes it on a batch and on a rebuild, and
  batch_layout.check() says nothing about the jpg (it counts only mp4).
"""
import _isolated_runlog  # noqa: F401,E402 - run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402
import contextlib
import io
import json
import os
import subprocess
import sys
import time
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
TMP = tmp_root("cf0674-preview-")
os.environ.setdefault("RUNLOG_BATCH", str(TMP / "runlog"))
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import video_preview  # noqa: E402
import batch_layout  # noqa: E402
from common import FFMPEG  # noqa: E402

_n = [0]


def _dir():
    _n[0] += 1
    d = TMP / f"case{_n[0]}"
    d.mkdir(parents=True)
    return d


def _ffmpeg(*args):
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", *args],
                   check=True, capture_output=True)


def render(path, seconds=5.0, size="1080x1920", black=0.0):
    """A rendered-video stand-in: `black` seconds of black, then testsrc2."""
    path.parent.mkdir(parents=True, exist_ok=True)
    src = f"testsrc2=duration={seconds - black}:size={size}:rate=25"
    if black:
        _ffmpeg("-f", "lavfi", "-i", f"color=c=black:duration={black}:size={size}:rate=25",
                "-f", "lavfi", "-i", src,
                "-filter_complex", "[0:v][1:v]concat=n=2:v=1[v]", "-map", "[v]",
                "-pix_fmt", "yuv420p", "-c:v", "libx264", "-preset", "ultrafast", str(path))
    else:
        _ffmpeg("-f", "lavfi", "-i", src, "-pix_fmt", "yuv420p", "-c:v", "libx264",
                "-preset", "ultrafast", str(path))
    return path


def plan_file(path, seconds=5.0, blocks=None, end_card=None):
    plan = {"style": "motion",
            "blocks": blocks if blocks is not None else
            [{"start": 0.0, "end": seconds, "asset": {"kind": "clip"}}],
            "duration": {"total": seconds}, "output": {"width": 1080, "height": 1920}}
    if end_card:
        plan["end_card"] = end_card
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(plan))
    return path


def _size(p):
    from PIL import Image
    with Image.open(p) as im:
        return im.size, im.format


def no_sharp(_png):
    return None


def test_9x16_render_gives_a_720x1280_jpeg_from_the_hook():
    d = _dir()
    mp4 = render(d / "videos" / "slug-a.mp4")
    got = video_preview.write(mp4, plan_file(d / "work" / "slug-a" / "plan.json"),
                              sharp=no_sharp)
    jpg = d / "videos" / "slug-a.jpg"
    assert got["path"] == str(jpg), got
    assert _size(jpg) == ((720, 1280), "JPEG")
    assert 0 < jpg.stat().st_size <= video_preview.MAX_BYTES, jpg.stat().st_size
    assert got["at"] == 1.0, got          # nothing to choose by: nearest 1 s


def test_16x9_render_is_cropped_to_9x16():
    d = _dir()
    mp4 = render(d / "videos" / "wide.mp4", size="1280x720")
    got = video_preview.write(mp4, plan_file(d / "plan.json"), sharp=no_sharp)
    assert got["path"], got
    assert _size(got["path"]) == ((720, 1280), "JPEG")


def test_no_video_is_no_error_and_no_file():
    d = _dir()
    got = video_preview.write(d / "videos" / "missing.mp4", d / "nope.json")
    assert got["path"] is None and "no video" in got["reason"], got
    assert not (d / "videos" / "missing.jpg").exists()
    # an unreadable mp4 (not a video) - no error either
    bad = d / "videos" / "bad.mp4"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(b"x")
    got = video_preview.write(bad, None)
    assert got["path"] is None, got
    assert not (d / "videos" / "bad.jpg").exists()


def test_black_opening_is_skipped():
    d = _dir()
    mp4 = render(d / "videos" / "dark.mp4", seconds=7.0, black=3.0)
    got = video_preview.write(mp4, plan_file(d / "plan.json", 7.0), sharp=no_sharp)
    assert got["path"], got
    assert got["at"] > 3.0 and got["why"].startswith("later"), got


def test_frame_is_never_on_the_end_card():
    d = _dir()
    mp4 = render(d / "videos" / "short.mp4", seconds=5.0)
    plan = plan_file(d / "plan.json", 5.0, end_card={"start_s": 1.2})
    hook, later = video_preview.candidate_times(json.loads(plan.read_text()), 5.0)
    assert hook == [1.0, 0.6] and later == [], (hook, later)
    got = video_preview.write(mp4, plan, sharp=no_sharp)
    assert got["at"] < 1.2, got
    # and never in the fade out of a video without a card
    hook, later = video_preview.candidate_times({"blocks": []}, 1.5)
    assert max(hook) <= 1.0 and later == [], hook


def test_frame_is_not_under_an_insert():
    d = _dir()
    mp4 = render(d / "videos" / "ins.mp4", seconds=5.0)
    blocks = [{"start": 0.0, "end": 2.0, "asset": {"kind": "clip", "src": "a.mp4"},
               "insert": {"kind": "proof", "src": str(mp4), "render_src": "proof.png"}},
              {"start": 2.0, "end": 5.0, "asset": {"kind": "clip", "src": "b.mp4"}}]
    plan = json.loads(plan_file(d / "plan.json", 5.0, blocks=blocks).read_text())
    import qc_render
    assert qc_render.insert_window(blocks[0]) == (0.0, 2.0)
    hook, _ = video_preview.candidate_times(plan, 5.0)
    assert all(t >= 2.0 for t in hook), hook


def test_sharpest_open_frame_wins():
    d = _dir()
    mp4 = render(d / "videos" / "sharp.mp4")
    marks = {}

    def grab(video, at, tmp, tag):
        import qc_render
        p = qc_render.delivered_frame(video, at, tmp, tag)
        marks[str(p)] = at
        return p

    got = video_preview.write(mp4, plan_file(d / "plan.json"), grab=grab,
                              sharp=lambda png: 100.0 if marks[str(png)] == 2.2 else 10.0)
    assert got["at"] == 2.2 and "sharpest" in got["why"], got


def test_stale_preview_of_an_older_render_is_removed():
    d = _dir()
    mp4 = render(d / "videos" / "all-black.mp4", seconds=3.0, black=2.9)
    jpg = d / "videos" / "all-black.jpg"
    jpg.write_bytes(b"old")
    old = time.time() - 600
    os.utime(jpg, (old, old))
    got = video_preview.write(mp4, plan_file(d / "plan.json", 3.0), sharp=no_sharp)
    assert got["path"] is None and "stale" in got["reason"], got
    assert not jpg.exists()
    # a jpg newer than the mp4 is not this function's to remove
    jpg.write_bytes(b"newer")
    got = video_preview.write(mp4, plan_file(d / "plan.json", 3.0), sharp=no_sharp)
    assert got["path"] is None and jpg.exists(), got


def _metadata(batch, videos):
    import write_batch_metadata as wbm
    argv = ["write_batch_metadata.py", str(batch), "--channel", "example-film",
            "--retired-shots", str(batch / "retired.json"),
            "--acceptance-log", str(batch / "acceptance.json")]
    for v in videos:
        argv += ["--video", *map(str, v)]
    out, err = io.StringIO(), io.StringIO()
    real = (wbm.qc_report, sys.argv, batch_layout.checkouts, video_preview._sharpness)
    wbm.qc_report = lambda video, plan: {"passed": True, "failures": [], "notes": [],
                                         "measured": {}}
    batch_layout.checkouts = lambda: []
    video_preview._sharpness = no_sharp
    sys.argv = argv
    code = 0
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            wbm.main()
    except SystemExit as e:
        code = e.code
    finally:
        wbm.qc_report, sys.argv, batch_layout.checkouts, video_preview._sharpness = real
    return code, out.getvalue(), err.getvalue()


def test_write_batch_metadata_writes_it_on_a_batch_and_a_rebuild():
    d = _dir()
    for batch in (d / "pipeline" / "example-film" / "2026-10-10T0000Z",
                  d / "pipeline" / "rebuilds" / "2026-10-10T0100Z"):
        mp4 = render(batch / "videos" / "slug-b.mp4")
        plan = plan_file(batch / "work" / "slug-b" / "plan.json")
        code, _out, err = _metadata(batch, [("s1", plan, mp4)])
        assert code in (0, None), err
        jpg = batch / "videos" / "slug-b.jpg"
        assert jpg.exists(), err
        assert "METADATA: preview ->" in err, err
        assert _size(jpg) == ((720, 1280), "JPEG")
        # the layout check counts mp4 only - the jpg is no finding
        assert batch_layout.check(batch, roots=[]) == [], batch_layout.check(batch, roots=[])
        assert "LAYOUT" not in err, err


def test_write_batch_metadata_without_a_readable_video_still_writes_the_record():
    d = _dir()
    batch = d / "pipeline" / "example-film" / "2026-10-10T0200Z"
    mp4 = batch / "videos" / "slug-c.mp4"
    mp4.parent.mkdir(parents=True)
    mp4.write_bytes(b"x")
    plan = plan_file(batch / "work" / "slug-c" / "plan.json")
    code, _out, err = _metadata(batch, [("s1", plan, mp4)])
    assert code in (0, None), err
    assert (batch / "05-video-editor.json").exists()
    assert "no preview for s1 (CF-0674)" in err, err
    assert not (batch / "videos" / "slug-c.jpg").exists()


# --------------------------------------------------------------------------
# CF-0681: a live monitor records a REAL batch's mp4 into a temp batch_dir -
# the other batch's videos/ is not this call's to write
# --------------------------------------------------------------------------

def tree_bytes(root):
    """{relative path: (sha256, mtime_ns)} of every file under root - the
    whole tree, byte for byte."""
    import hashlib
    out = {}
    for f in sorted(Path(root).rglob("*")):
        if f.is_file():
            out[str(f.relative_to(root))] = (hashlib.sha256(f.read_bytes()).hexdigest(),
                                            f.stat().st_mtime_ns)
    return out


def _live_shaped_tree(d, stale_jpg=False):
    """A stand-in factory root with one shipped batch: its plan and its mp4
    (and, with `stale_jpg`, a preview OLDER than the mp4 - the file write()
    would remove beside its own video)."""
    batch = d / "factory" / "pipeline" / "example-film" / "2026-10-05T0701Z"
    mp4 = render(batch / "videos" / "harbourlights.mp4")
    plan = plan_file(batch / "work" / "harbourlights" / "plan.json")
    if stale_jpg:
        jpg = batch / "videos" / "harbourlights.jpg"
        jpg.write_bytes(b"an older render's preview")
        old = mp4.stat().st_mtime - 3600
        os.utime(jpg, (old, old))
    return d / "factory", batch, mp4, plan


def test_write_for_batch_skips_an_mp4_outside_the_batch():
    d = _dir()
    root, batch, mp4, plan = _live_shaped_tree(d, stale_jpg=True)
    before = tree_bytes(root)
    elsewhere = d / "monitor-tmp"
    elsewhere.mkdir()
    got = video_preview.write_for_batch(elsewhere, mp4, plan, sharp=no_sharp)
    assert got["path"] is None and got.get("skipped"), got
    assert "CF-0681" in got["reason"], got
    assert tree_bytes(root) == before, "write_for_batch touched another batch"
    # ...and under its own batch it is write() exactly: the stale jpg goes,
    # a fresh one takes its place.
    got = video_preview.write_for_batch(batch, mp4, plan, sharp=no_sharp)
    assert got["path"] == str(batch / "videos" / "harbourlights.jpg"), got
    assert _size(batch / "videos" / "harbourlights.jpg") == ((720, 1280), "JPEG")


def test_write_batch_metadata_into_a_temp_dir_leaves_the_real_batch_byte_for_byte():
    """The live monitors' shape (test_degrade_blocks, test_rhythm_execution):
    a temp copy of a shipped plan, the shipped mp4 read in place, the record
    written into a temp batch_dir, FACTORY_ROOT on a stand-in tree. The
    shipped batch is the same tree, byte for byte, after the call - no
    `videos/<slug>.jpg` written, no older one removed."""
    d = _dir()
    root, batch, mp4, plan = _live_shaped_tree(d, stale_jpg=True)
    out = d / "monitor-tmp"
    out.mkdir()
    copy = out / "plan.json"
    copy.write_text(plan.read_text())
    before = tree_bytes(root)
    saved = os.environ.get("FACTORY_ROOT")
    os.environ["FACTORY_ROOT"] = str(root)
    try:
        code, _out, err = _metadata(out, [("harbourlights", copy, mp4)])
    finally:
        if saved is None:
            os.environ.pop("FACTORY_ROOT", None)
        else:
            os.environ["FACTORY_ROOT"] = saved
    assert code in (0, None), err
    assert (out / "05-video-editor.json").exists(), err
    assert "preview not written for harbourlights" in err and "CF-0681" in err, err
    assert "METADATA: preview ->" not in err, err
    after = tree_bytes(root)
    assert after == before, ("write_batch_metadata wrote the batch it only reads: "
                             f"{sorted(set(after) ^ set(before)) or 'changed bytes'}")


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
