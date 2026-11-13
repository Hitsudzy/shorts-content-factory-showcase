#!/usr/bin/env python3
"""CF-0712: a split block's halves are probed over their whole picture.

sophie-adenot (example-science 2026-10-12T2001Z) was refused at 24 from a plan
of 86: one finding, "frozen hook block 0" (-62). Block 0 was a `side_by_side`
opening; side a was an aurora seen from orbit, a clip that moves from its
first frame. The render moved too - over the top half it read 9-10 - but the
probe for side a was a fixed `crop=iw:ih*0.18` (the top 36% of the half), and
there the picture is black space with a sliver of aurora: 0.65-0.94, under
MIN_BLOCK_MOTION for 2.1 s. The second look (freeze_verdict) compared the
whole source frame (9.9) against that band and called the faithful render a
freeze.

The same fixed band reached ~57 px into the caption band on side b, so words
changing there could pass a frozen side b as moving.

Pinned here, on synthetic media (no live data): the band geometry follows the
plan (main zone, seam, caption band); a render whose upper half is still only
in its top third is not a freeze (and the old band did read it as one); a
really frozen half is still caught; side b's band never sees the captions.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import meme_captions  # noqa: E402
import qc_render  # noqa: E402
from common import FFMPEG, MAX_HELD_RUN  # noqa: E402
import _synthetic_media as syn  # noqa: E402

W, H = 540, 960
SEAM = 6
HALF = (H - SEAM) // 2                 # 477
SECONDS = 3.0
OLD_SIDE_A_VF = "crop=iw:ih*0.18:0:0,scale=200:-2"     # the band before CF-0712
OLD_SIDE_B_VF = "crop=iw:ih*0.18:0:ih*0.5,scale=200:-2"


def _plan(blocks=(), **extra):
    return {"output": {"width": W, "height": H, "fps": 25},
            "layout": {"main": {"fit": "cover"}, "secondary": None},
            "blocks": list(blocks), **extra}


def _split_block(src_a, src_b, end=2.88):
    side = lambda s, src: {"side": s, "kind": "clip", "src": src,
                           "start_seconds": 0, "seconds": end, "held_frame": False}
    return {"start": 0.0, "end": end,
            "asset": {"kind": "split", "seam_px": SEAM,
                      "sides": [side("a", src_a), side("b", src_b)]}}


def _render(path, layers):
    """A W x H render: black ground, then each `(source, w, h, y)` overlaid
    full width at `y`. `source` is 'moving' (testsrc2) or 'held' (one
    testsrc2 frame cloned for the whole render)."""
    inputs, chain, last = [], [], "0:v"
    inputs += ["-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:d={SECONDS}:r=25"]
    for k, (kind, w, h, y) in enumerate(layers, start=1):
        if kind == "moving":
            inputs += ["-f", "lavfi", "-i", f"testsrc2=duration={SECONDS}:size={w}x{h}:rate=25"]
            chain.append(f"[{k}:v]null[l{k}]")
        else:
            inputs += ["-f", "lavfi", "-i", f"testsrc2=duration=0.04:size={w}x{h}:rate=25"]
            chain.append(f"[{k}:v]tpad=stop_mode=clone:stop_duration={SECONDS}[l{k}]")
        chain.append(f"[{last}][l{k}]overlay=0:{y}:shortest=0[o{k}]")
        last = f"o{k}"
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", *inputs,
                    "-filter_complex", ";".join(chain), "-map", f"[{last}]",
                    "-t", str(SECONDS), "-pix_fmt", "yuv420p", "-c:v", "libx264",
                    "-preset", "ultrafast", str(path)], check=True, capture_output=True)
    return str(path)


def _band():
    _, y, _, h = meme_captions.band_box(_plan())
    return y, y + h


# --------------------------------------------------------------------------
# geometry
# --------------------------------------------------------------------------
def test_side_a_is_the_whole_upper_half_and_side_b_stops_above_the_captions():
    band_top, band_bottom = _band()
    assert qc_render.split_probe_band(_plan(), 0, SEAM) == (0, HALF)
    top, height = qc_render.split_probe_band(_plan(), 1, SEAM)
    assert top == HALF + SEAM, top
    assert top + height == band_top, (top, height, band_top)
    # The bar the old fixed band crossed: side b's probe never reaches the band.
    assert top + height <= band_top < band_bottom


def test_the_production_frame_geometry():
    """1080x1920 with no secondary zone - the frame sophie-adenot was built
    for; a bare block with no plan gets the same answer."""
    plan = {"output": {"width": 1080, "height": 1920}}
    assert qc_render.split_probe_band(plan, 0, 6) == (0, 957)
    assert qc_render.split_probe_band(None, 0) == (0, 957)
    top, height = qc_render.split_probe_band(plan, 1, 6)
    _, band_y, _, _ = meme_captions.band_box(plan)
    assert (top, top + height) == (963, band_y), (top, height, band_y)
    vf = qc_render.split_probe_vf(plan, 1, 6)
    assert vf == f"crop=iw:{(band_y - 964) - (band_y - 964) % 2}:0:964,scale=200:-2", vf


def test_the_halves_follow_a_secondary_zone():
    plan = _plan(layout={"main": {"fit": "cover"}, "secondary": {"height": 0.28}})
    _, _, _, zh = meme_captions.main_zone(plan)
    half = (zh - SEAM) // 2
    top, height = qc_render.split_probe_band(plan, 1, SEAM)
    assert top == half + SEAM and top + height <= half * 2 + SEAM, (top, height, zh)


def test_probe_targets_hand_each_side_its_own_band():
    block = _split_block("a.mp4", "b.mp4")
    vfs = [t[1] for t in qc_render.probe_targets(block, 0, _plan())]
    assert vfs == [qc_render.split_probe_vf(_plan(), 0, SEAM),
                   qc_render.split_probe_vf(_plan(), 1, SEAM)], vfs


# --------------------------------------------------------------------------
# the measurement, on synthetic renders
# --------------------------------------------------------------------------
def test_a_half_still_only_in_its_top_third_is_not_a_freeze():
    """sophie-adenot's shape: the top ~36% of side a is motionless (space),
    the rest of the half moves, the source clip moves. The old band read a
    freeze there; the half as a whole is not one."""
    band_top, _ = _band()
    sky = int(HALF * 0.36) + 4
    with tempfile.TemporaryDirectory() as tmp:
        src = syn.moving_clip(Path(tmp) / "src.mp4", SECONDS)
        video = _render(Path(tmp) / "render.mp4",
                        [("moving", W, HALF - sky, sky),
                         ("moving", W, band_top - (HALF + SEAM), HALF + SEAM)])
        old = qc_render.motion_timeline(video, OLD_SIDE_A_VF, SECONDS)
        rs, re_, _ = qc_render.longest_still_run(old, 0.0, 2.88)
        assert re_ - rs >= MAX_HELD_RUN, ("the fixture no longer reproduces the "
                                          f"CF-0712 false freeze: {old}")
        records = qc_render.frozen_blocks(video, _plan([_split_block(src, src)]))
        assert records == [], records


def test_a_really_frozen_upper_half_is_still_caught():
    band_top, _ = _band()
    with tempfile.TemporaryDirectory() as tmp:
        src = syn.moving_clip(Path(tmp) / "src.mp4", SECONDS)
        video = _render(Path(tmp) / "render.mp4",
                        [("held", W, HALF, 0),
                         ("moving", W, band_top - (HALF + SEAM), HALF + SEAM)])
        records = qc_render.frozen_blocks(video, _plan([_split_block(src, src)]))
        assert [(r["index"], r["side"], r["fault"]) for r in records] == [(0, "a", True)], records


def test_captions_moving_under_a_frozen_side_b_do_not_hide_it():
    """Side b frozen, the caption band alive (words changing): the old band
    overlapped the captions and read motion; the new one stops above them."""
    band_top, band_bottom = _band()
    with tempfile.TemporaryDirectory() as tmp:
        src = syn.moving_clip(Path(tmp) / "src.mp4", SECONDS)
        video = _render(Path(tmp) / "render.mp4",
                        [("moving", W, HALF, 0),
                         ("held", W, H - (HALF + SEAM), HALF + SEAM),
                         ("moving", W, band_bottom - band_top, band_top)])
        old = qc_render.motion_timeline(video, OLD_SIDE_B_VF, SECONDS)
        assert max(m for _, m in old[:8]) >= qc_render.MIN_BLOCK_MOTION, old
        records = qc_render.frozen_blocks(video, _plan([_split_block(src, src)]))
        assert [(r["index"], r["side"], r["fault"]) for r in records] == [(0, "b", True)], records


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
