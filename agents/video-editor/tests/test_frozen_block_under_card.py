#!/usr/bin/env python3
"""CF-0459: a clip block hidden whole under an opaque card is not a frozen one.

Batch example-film/2026-10-01T0200Z, you-can-see-everything block 9
(27.97-32.09s, shot jsw92T7KpqM:3): the block carries a proof insert for its
whole span, which AssetLayer.jsx draws "fitted whole on black" over the
block's picture zone. The band frozen_blocks() measures is black under it from
the block's first frame to its last, the sweep read that as a still and
score_log charged `score.frozen_block` (-20) for a render that was exactly what
the plan asked for. subject_blocks() had stopped asking a face of the same
block (CF-0363/CF-0442); the freeze gate had not been told.

What these tests hold in place:

  * a clip block an opaque insert hides whole is not judged at all;
  * a block an insert hides in part is judged on the part left open - a still
    there is still caught, a still under the card is not;
  * the gate is not weaker anywhere else: the same render with no card still
    fails, a comparison line (a badge over part of the band, the clip playing
    around it) excuses nothing, and neither does a cutout meme, or an insert
    on a block kind the renderer never mounts one on.

Videos are synthesized with ffmpeg's `tpad=stop_mode=clone` (the pixel
signature of a held last frame), the same way test_partly_frozen_block.py
does it - no Remotion render.

No pytest - plain asserts, run through tests/run_tests.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import repo_paths  # noqa: E402,F401 - CF-0125: paths outside this repo

import qc_render  # noqa: E402
from common import FFMPEG  # noqa: E402

SIZE = "540x960"
RATE = 25


def _ffmpeg(*args):
    subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", *args], check=True)


def _moving(path, seconds):
    _ffmpeg("-f", "lavfi",
            "-i", f"testsrc2=duration={seconds}:size={SIZE}:rate={RATE}",
            "-pix_fmt", "yuv420p", str(path))
    return str(path)


def _moving_then_frozen(path, moving_seconds, frozen_seconds):
    _ffmpeg("-f", "lavfi",
            "-i", f"testsrc2=duration={moving_seconds}:size={SIZE}:rate={RATE}",
            "-vf", f"tpad=stop_mode=clone:stop_duration={frozen_seconds}",
            "-pix_fmt", "yuv420p", str(path))
    return str(path)


def _block(start, end, src, insert=None):
    b = {"start": start, "end": end,
         "asset": {"kind": "clip", "src": src, "start_seconds": 0}}
    if insert is not None:
        b["insert"] = insert
    return b


def _proof(start_s=None, end_s=None, **extra):
    ins = {"kind": "proof", "proof_id": "p1", "capture_path": "/proof.png",
           "fit": "contain", "background": "black", **extra}
    if start_s is not None:
        ins["start_s"], ins["end_s"] = start_s, end_s
    return ins


class _Render:
    """One render shared by the video tests: 3s of motion, then the picture
    held for 6s - block 0 (0-3s) alive, block 1 (3-9s) a still wherever it is
    not covered. Block 1's clip is a 1s file asked for 6s, so an uncovered
    still there is a fault (playback ran out), never excused by the source."""
    _dir = None

    @classmethod
    def get(cls):
        if cls._dir is None:
            cls._dir = tempfile.TemporaryDirectory()
            tmp = Path(cls._dir.name)
            cls.clip0 = _moving(tmp / "c0.mp4", 3.0)
            cls.clip1 = _moving(tmp / "c1.mp4", 1.0)
            cls.video = _moving_then_frozen(tmp / "render.mp4", 3.0, 6.0)
        return cls


def _frozen(plan):
    r = _Render.get()
    return qc_render.frozen_blocks(r.video, plan)


# --------------------------------------------------------------------------
# What counts as a card over the picture (no video)
# --------------------------------------------------------------------------

def test_an_opaque_insert_over_a_clip_block_covers_it():
    b = _block(27.97, 32.09, "/c.mp4", _proof())
    covers = qc_render.freeze_covers(b, b, {})
    assert [c["window"] for c in covers] == [(27.97, 32.09)], covers
    assert qc_render.open_pieces(b, covers) == []


def test_a_comparison_line_is_not_a_cover_for_the_freeze_gate():
    """It is a badge and a strip over part of the band; the clip keeps
    playing around it. 0200Z block 8 sits under one and was rightly judged."""
    b = _block(25.85, 27.97, "/c.mp4")
    plan = {"comparison_lines": [{"start_s": 25.82, "end_s": 34.44}]}
    # The subject gate does count it (a card over a face is the norm) ...
    assert qc_render.cover_windows(b, plan)
    # ... the freeze gate does not.
    assert qc_render.freeze_covers(b, b, plan) == []


def test_the_end_card_covers():
    b = _block(38.0, 42.0, "/c.mp4")
    covers = qc_render.freeze_covers(b, b, {"end_card": {"start_s": 40.1}})
    assert [c["window"] for c in covers] == [(40.1, 42.0)], covers


def test_a_transparent_or_cutout_insert_is_not_a_cover():
    clear = _block(0.0, 4.0, "/c.mp4", _proof(background="transparent"))
    assert qc_render.freeze_covers(clear, clear, {}) == []
    cutout = _block(0.0, 4.0, "/c.mp4", {
        "kind": "meme", "file": "/m.gif", "placement": "cutout_in_corner",
        "cutout": {"rect": [0, 0, 10, 10], "image": "/m.png",
                   "render_src": "/m.webm"}})
    assert qc_render.freeze_covers(cutout, cutout, {}) == []


def test_an_insert_on_a_block_the_renderer_mounts_none_on_is_not_a_cover():
    """AssetLayer.jsx returns for a split before InsertLayer: an insert in its
    plan is never drawn, so it hides nothing. CF-0811: a sequence is no longer
    one of them - the insert is asked first, so a proof or a meme on a
    stretch-split block is on screen and covers the cuts under it."""
    b = {"start": 0.0, "end": 4.0, "asset": {"kind": "split"}, "insert": _proof()}
    cut = {**b, "asset": {"kind": "clip", "src": "/c.mp4"}}
    assert qc_render.freeze_covers(b, cut, {}) == []
    seq = {"start": 0.0, "end": 4.0, "asset": {"kind": "sequence", "cuts": [
        {"kind": "clip", "src": "/c.mp4", "seconds": 4.0}]}, "insert": _proof()}
    got = qc_render.freeze_covers(seq, {**seq, "asset": seq["asset"]["cuts"][0]}, {})
    assert [c["layer"] for c in got] == ["insert"], got


def test_a_bare_insert_marker_is_not_a_cover():
    """No picture behind it - a request answered `no_asset`."""
    b = _block(0.0, 4.0, "/c.mp4", {"kind": "meme"})
    assert qc_render.freeze_covers(b, b, {}) == []


# --------------------------------------------------------------------------
# The render gate
# --------------------------------------------------------------------------

def test_control_the_uncovered_still_is_caught():
    """The gate this task must not weaken: the same render, no card."""
    r = _Render.get()
    recs = _frozen({"blocks": [_block(0.0, 3.0, r.clip0),
                               _block(3.0, 9.0, r.clip1)]})
    assert [x["index"] for x in recs] == [1], recs
    assert recs[0]["fault"], recs
    assert "judged_span" not in recs[0] and "covered_by" not in recs[0], recs


def test_a_clip_block_wholly_under_a_proof_card_is_not_frozen():
    """0200Z you-can-see-everything block 9, to scale."""
    r = _Render.get()
    recs = _frozen({"blocks": [_block(0.0, 3.0, r.clip0),
                               _block(3.0, 9.0, r.clip1, _proof())]})
    assert recs == [], recs


def test_a_still_under_the_card_part_is_not_charged():
    """The card is up for the held stretch; what is open moves."""
    r = _Render.get()
    recs = _frozen({"blocks": [_block(0.0, 9.0, r.clip0, _proof(3.0, 9.0))]})
    assert recs == [], recs


def test_a_still_on_the_open_part_is_still_caught():
    """The card hides 0-3.5s; the 5.5s held after it is on screen."""
    r = _Render.get()
    recs = _frozen({"blocks": [_block(0.0, 9.0, r.clip1, _proof(0.0, 3.5))]})
    assert [x["index"] for x in recs] == [0], recs
    rec = recs[0]
    assert rec["fault"], rec
    assert rec["still_run"] >= qc_render.MAX_HELD_RUN, rec
    assert rec["still_run_at"] >= 3.5 - 1e-6, rec
    assert rec["judged_span"] == [[3.5, 9.0]], rec
    assert rec["covered_by"][0]["kind"] == "proof", rec


def test_open_pieces_on_both_sides_of_a_card_are_both_judged():
    """A card in the middle (1-2.5s) leaves 0-1s and 2.5-9s; the still is in
    the second piece and is caught there."""
    r = _Render.get()
    recs = _frozen({"blocks": [_block(0.0, 9.0, r.clip1, _proof(1.0, 2.5))]})
    assert [x["index"] for x in recs] == [0], recs
    assert recs[0]["judged_span"] == [[0.0, 1.0], [2.5, 9.0]], recs
    assert recs[0]["still_run_at"] >= 2.5 - 1e-6, recs


def test_a_comparison_line_over_a_still_excuses_nothing():
    r = _Render.get()
    recs = _frozen({"blocks": [_block(0.0, 3.0, r.clip0),
                               _block(3.0, 9.0, r.clip1)],
                    "comparison_lines": [{"start_s": 2.0, "end_s": 9.0}]})
    assert [x["index"] for x in recs] == [1], recs
    assert recs[0]["fault"], recs


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
