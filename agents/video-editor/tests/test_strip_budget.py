#!/usr/bin/env python3
"""CF-0903: the plan does not pile strips on the blurred ground past the
signed allowance when its own probe says the crop keeps the subject.

The user's refusal `narrow_strip_on_blur` (13 by 30.10, more than any other
code) is a video whose pictures stand as narrow strips on their blurred frame
for a third of it or more. The replay of the 12 refused plans (18.10-30.10):
most of the strip seconds were pictures shown `blur_fill` because the pool's
cached record (one frame of the shot) said `low_framing`, while the plan's
own probe of the cut clip kept the subject in the 9:16 crop.

Pinned here, without ffmpeg, Vision or Remotion:
  * present_picture() says who found the framing low (`framed_by`): this
    probe, or the pool's record alone;
  * past STRIP_ALLOW_SECONDS of strip, the record-only blur_fills go back to
    the crop, longest first, until the strip is within the allowance; a
    blur_fill the probe asked for stays; under the allowance nothing moves;
  * the plan stage charges the taken-back picture its low_framing again (no
    presentation), and says so in the notes;
  * a stand-in of crystal-lake 1505Z's plan (16:9 trailer, 58 % strip):
    under a third after the take-back.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0903-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import shot_score  # noqa: E402
from shot_score import BLUR_FILL, LUMA_LIFT, LOW_FRAMING  # noqa: E402

RECT_169 = {"x": 0, "y": 306, "width": 1080, "height": 608}     # 16:9 whole: 0.317
RECT_239 = {"x": 0, "y": 384, "width": 1080, "height": 452}     # 2.39:1: 0.235


def _blur(rect, by, extra=None):
    d = {"rect": dict(rect), "blur_px": 48, "bg_scale": 1.15, "bg_dim": 0.55,
         shot_score.FRAMED_BY: by}
    out = {BLUR_FILL: d}
    out.update(extra or {})
    return out


def _clip(shot, pres=None, ss=(1920, 1080)):
    a = {"kind": "clip", "src": f"/x/{shot}.mp4", "fit": "cover",
         "focus": {"x": 0.5, "y": 0.4}, "source_size": {"width": ss[0], "height": ss[1]}}
    if pres:
        a["presentation"] = pres
        a["fit"] = "contain"
    return a


def _block(s, e, shot, pres=None):
    return {"start": s, "end": e, "shot": shot, "asset": _clip(shot, pres)}


def _strip_seconds(blocks):
    return round(sum(sec for _i, _c, t, sec, _s in shot_score._strip_pieces(blocks)
                     if shot_score.strip_share(t) < shot_score.STRIP_SHARE), 3)


def _qc(failed, luma=90.0):
    return {"usable": not failed, "failed": failed,
            "failures": [f"{k}: weak" for k in failed], "mean_luma": luma}


def test_the_allowance_is_the_signed_price():
    assert shot_score.STRIP_ALLOW_SECONDS == 5.0
    assert shot_score.STRIP_SHARE == 0.33
    assert shot_score.strip_share({"presentation": {BLUR_FILL: {"rect": RECT_169}}}) == 0.317
    assert abs(shot_score.strip_share(_clip("a", ss=(1920, 804)) | {"fit": "contain"}) - 0.235) < 0.002
    assert shot_score.strip_share(_clip("a")) == 1.0


def test_present_picture_says_who_found_the_framing_low():
    import build_render_plan as brp
    import meme_captions
    box = meme_captions.insert_box({"output": {"width": 1080, "height": 1920}})
    with tempfile.TemporaryDirectory() as tmp:
        from PIL import Image
        probe = str(Path(tmp) / "p.png")
        Image.new("RGB", (320, 180), (90, 90, 90)).save(probe)
        # the probe keeps the subject, the pool's record says low_framing
        a = _clip("r")
        got = brp.present_picture(a, {"qc": _qc([]), "roi_coverage": 1.0}, probe,
                                  {"soft": [LOW_FRAMING]}, box, {}, [], 1, "r")
        assert got[BLUR_FILL][shot_score.FRAMED_BY] == shot_score.FRAMED_BY_RECORD, got
        # the probe's own crop cuts the subject
        b = _clip("p")
        got = brp.present_picture(b, {"qc": _qc(["coverage"]), "roi_coverage": 0.3},
                                  probe, {"soft": [LOW_FRAMING]}, box, {}, [], 2, "p")
        assert got[BLUR_FILL][shot_score.FRAMED_BY] == shot_score.FRAMED_BY_PROBE, got


def test_past_the_allowance_record_only_strips_go_back_to_the_crop():
    blocks = [
        _block(0.0, 3.0, "v:1", _blur(RECT_169, "pool_record")),
        _block(3.0, 7.0, "v:2", _blur(RECT_169, "pool_record", {LUMA_LIFT: {"gain": 1.5}})),
        _block(7.0, 9.0, "v:3", _blur(RECT_169, "probe")),
        _block(9.0, 11.0, "v:4", _blur(RECT_239, "pool_record")),
        _block(11.0, 14.0, "v:5"),
    ]
    assert _strip_seconds(blocks) == 11.0
    rec = shot_score.take_back_strips(blocks)
    assert rec["seconds_before"] == 11.0
    # longest record-only first: v:2 (4 s) -> 7 s, v:1 (3 s) -> 4 s <= 5
    assert [t["shot"] for t in rec["taken_back"]] == ["v:2", "v:1"], rec
    assert rec["seconds_after"] == 4.0 == _strip_seconds(blocks)
    assert rec["kept_by_probe_seconds"] == 2.0
    a2 = blocks[1]["asset"]
    assert a2["fit"] == "cover" and a2["presentation"] == {LUMA_LIFT: {"gain": 1.5}}
    a1 = blocks[0]["asset"]
    assert a1["fit"] == "cover" and "presentation" not in a1
    # the probe's own blur_fill and the short record-only one stay
    assert blocks[2]["asset"]["fit"] == "contain"
    assert blocks[3]["asset"]["fit"] == "contain"


def test_a_sequence_cut_is_taken_back_on_its_own_seconds():
    cuts = [dict(_clip("q:1", _blur(RECT_169, "pool_record")), seconds=4.0, shot="q:1"),
            dict(_clip("q:2", _blur(RECT_169, "pool_record")), seconds=3.0, shot="q:2"),
            dict(_clip("q:3"), seconds=2.0, shot="q:3")]
    blocks = [{"start": 0.0, "end": 9.0, "shot": "q:1",
               "asset": {"kind": "sequence", "cuts": cuts}}]
    rec = shot_score.take_back_strips(blocks)
    assert [(t["block"], t["cut"], t["shot"]) for t in rec["taken_back"]] == [(0, 0, "q:1")]
    assert rec["seconds_after"] == 3.0
    assert cuts[0]["fit"] == "cover" and cuts[1]["fit"] == "contain"


def test_under_the_allowance_nothing_moves_and_a_covered_block_does_not_count():
    blocks = [_block(0.0, 3.0, "v:1", _blur(RECT_169, "pool_record")),
              _block(3.0, 8.0, "v:2", _blur(RECT_169, "pool_record"))]
    blocks[1]["insert"] = {"kind": "proof", "placement": "box"}
    rec = shot_score.take_back_strips(blocks)
    assert rec["seconds_before"] == 3.0 and rec["taken_back"] == []
    assert blocks[0]["asset"]["fit"] == "contain"
    # a blur_fill with no `framed_by` (a plan before CF-0903) is never moved
    old = [_block(0.0, 9.0, "v:1", {BLUR_FILL: {"rect": RECT_169}})]
    old[0]["asset"]["fit"] = "contain"
    assert shot_score.take_back_strips(old)["taken_back"] == []


def test_the_plan_stage_charges_the_taken_back_picture_its_framing():
    import build_render_plan as brp
    blocks = [_block(0.0, 4.0, "v:1", _blur(RECT_169, "pool_record")),
              _block(4.0, 8.0, "v:2", _blur(RECT_169, "probe"))]
    presented = {(0, "v:1"): {BLUR_FILL}, (1, "v:2"): {BLUR_FILL}}
    notes = []
    rec = brp.take_back_strips(blocks, presented, notes)
    assert [t["shot"] for t in rec["taken_back"]] == ["v:1"]
    assert presented == {(1, "v:2"): {BLUR_FILL}}, presented
    assert any("blur_fill taken back" in n and "CF-0903" in n for n in notes), notes
    story = [{"_start": 0.0, "shot": "v:1", "usability": {"soft": [LOW_FRAMING]}},
             {"_start": 4.0, "shot": "v:2", "usability": {"soft": [LOW_FRAMING]}}]
    found = shot_score.plan_findings(story, presented=presented,
                                     finding=lambda r, w, hook=False, note=None: (r, w["shot"]),
                                     in_hook=lambda t: False)
    assert found == [("score.low_framing", "v:1")], found
    pres = shot_score.presentation_findings(
        blocks, finding=lambda r, w, hook=False, note=None: (r, w.get("shot")),
        in_hook=lambda t: False, priced=lambda k: True)
    assert [r for r, _ in pres] == ["score.presentation_blur_fill"], pres


def test_a_crystal_lake_like_plan_falls_under_a_third():
    """crystal-lake 1505Z: one 16:9 trailer, 25.0 s of 43.3 s on the blurred
    ground; 16.9 s of it record-only (the probe kept the subject), 8.1 s
    asked for by the probe."""
    spans = [(4.05, 6.18, "pool_record"), (8.72, 11.81, "pool_record"),
             (11.81, 15.2, "probe"), (15.2, 18.53, "pool_record"),
             (18.53, 21.0, "pool_record"), (24.45, 29.27, "probe"),
             (32.96, 36.2, "pool_record")]
    blocks, t = [], 0.0
    for s, e, by in spans:
        if s > t:
            blocks.append(_block(t, s, f"c:{len(blocks)}"))
        blocks.append(_block(s, e, f"c:{len(blocks)}", _blur(RECT_169, by)))
        t = e
    blocks.append(_block(t, 43.3, "c:end"))
    before = _strip_seconds(blocks)
    assert before / 43.3 > 0.5, before
    rec = shot_score.take_back_strips(blocks)
    after = _strip_seconds(blocks)
    assert after == rec["seconds_after"]
    assert after / 43.3 < 1 / 3, (before, after)
    assert rec["kept_by_probe_seconds"] == round(3.39 + 4.82, 3)


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items())
             if k.startswith("test_") and callable(v)]
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
