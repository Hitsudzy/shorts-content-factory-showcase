#!/usr/bin/env python3
"""CF-0436: presentation instead of a price - the penalty is what the viewer sees.

Pinned here, without ffmpeg, Vision or Remotion:
  * the Editor's comparison: a weak picture is shown `blur_fill` (framing) or
    `luma_lift` (brightness) only when the presentation costs less than the
    soft rule it removes; a frame the capped gain cannot lift stays as it is;
  * a shown picture pays the presentation, not the soft rule, on the plan
    stage; a rule the root's table does not price yet is left out of the log;
  * ranking prices a fixable weak shot at its presentation;
  * the blur_fill rectangle is the whole picture over the insert box;
  * QC: a blur_fill block's motion is measured on the picture, not on the
    blurred ground; the subject gate stands down for it; a luma_lift block's
    lifted brightness is measured, and a lift that failed is priced on QC.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0436-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import shot_score  # noqa: E402
from shot_score import BLUR_FILL, LUMA_LIFT, LOW_FRAMING, LOW_BRIGHTNESS  # noqa: E402


def _finding(rule, where, hook=False, note=None):
    return {"rule": rule, "where": where, "hook": hook, "note": note}


def _hook(t):
    return False


def test_the_luma_floor_is_qc_assets():
    import qc_asset
    assert shot_score.LUMA_FLOOR == qc_asset.MIN_MEAN_LUMA


def test_luma_gain_lifts_to_the_target_and_gives_up_under_the_cap():
    assert shot_score.luma_gain(20) == 2.0          # 20 -> 40
    assert shot_score.luma_gain(12) == 3.0          # capped, 36 >= 28
    assert shot_score.luma_gain(9) is None          # 27 < 28 even at the cap
    assert shot_score.luma_gain(None) is None
    assert shot_score.luma_gain(50) == 1.0          # nothing to lift


def test_the_editor_takes_a_presentation_only_when_it_is_cheaper():
    assert shot_score.worth(BLUR_FILL) and shot_score.worth(LUMA_LIFT)
    got = shot_score.choose([LOW_FRAMING, LOW_BRIGHTNESS], luma=20)
    assert got == {BLUR_FILL: {}, LUMA_LIFT: {"gain": 2.0}}, got
    assert shot_score.choose([LOW_BRIGHTNESS], luma=8) == {}   # cannot be lifted
    assert shot_score.choose(["low_resolution"], luma=80) == {}
    # a presentation priced at the soft rule's own price is not worth it
    saved = dict(shot_score._MEMO)
    try:
        shot_score._MEMO["rules"] = {"score.presentation_blur_fill":
                                     {"penalty": {"price": 3}}}
        assert shot_score.choose([LOW_FRAMING]) == {}
        assert LUMA_LIFT in shot_score.choose([LOW_BRIGHTNESS], luma=20)
    finally:
        shot_score._MEMO.clear()
        shot_score._MEMO.update(saved)


def test_a_presented_picture_pays_the_presentation_not_the_rule():
    story = [{"shot": "s1", "_start": 1.0,
              "usability": {"soft": [LOW_FRAMING, "off_topic_shot"]}},
             {"shot": "s2", "_start": 4.0, "usability": {"soft": [LOW_BRIGHTNESS]}}]
    plain = shot_score.plan_findings(story, finding=_finding, in_hook=_hook)
    assert sorted(f["rule"] for f in plain) == [
        "score.low_brightness", "score.low_framing", "score.off_topic_shot"]
    shown = shot_score.plan_findings(
        story, finding=_finding, in_hook=_hook,
        presented={(0, "s1"): {BLUR_FILL}, (1, "s2"): {LUMA_LIFT}})
    assert [f["rule"] for f in shown] == ["score.off_topic_shot"], shown
    plan = [{"start": 1.0, "asset": {"kind": "clip", "shot": "s1",
                                     "presentation": {BLUR_FILL: {"rect": {}}}}},
            {"start": 4.0, "asset": {"kind": "sequence", "cuts": [
                {"shot": "s2", "presentation": {LUMA_LIFT: {"gain": 2.0}}},
                {"shot": "s3"}]}},
            {"start": 7.0, "asset": {"kind": "clip", "shot": "s1",
                                     "presentation": {BLUR_FILL: {"rect": {}}}}}]
    priced = shot_score.presentation_findings(plan, finding=_finding,
                                              in_hook=_hook, priced=lambda k: True)
    assert [(f["rule"], f["where"]["block"]) for f in priced] == [
        ("score.presentation_blur_fill", 0), ("score.presentation_luma_lift", 1)]
    # a key the root's table does not carry yet stays out of the log
    assert shot_score.presentation_findings(plan, finding=_finding, in_hook=_hook,
                                            priced=lambda k: False) == []


def test_ranking_prices_a_fixable_weak_shot_at_its_presentation():
    framing = {"soft": [{"rule": LOW_FRAMING, "price": 3, "value": 0.4}], "hard": []}
    dark_liftable = {"soft": [{"rule": LOW_BRIGHTNESS, "price": 3, "value": 20}], "hard": []}
    dark_dead = {"soft": [{"rule": LOW_BRIGHTNESS, "price": 3, "value": 5}], "hard": []}
    off_topic = {"soft": [{"rule": "off_topic_shot", "price": 4}], "hard": []}
    k = shot_score.viewer_rank_key
    assert k(framing)[:2] == (0, -0.99) and k(dark_liftable)[:2] == (0, -0.99)
    assert k(dark_dead)[:2] == (0, -0.97)
    assert k(framing) < k(dark_dead) < k(off_topic)
    assert k({"soft": [], "hard": [{"rule": "black_frame"}], "score": 0.0})[0] == 1
    assert k(None) == (0, -1.0, 0.0)


def test_the_blur_fill_rect_is_the_whole_picture_over_the_insert_box():
    import meme_captions
    plan = {"output": {"width": 1080, "height": 1920}}
    box = meme_captions.insert_box(plan)
    rect = shot_score.blur_fill_rect({"width": 1920, "height": 816}, box)
    assert rect["width"] == 1080 and rect["x"] == 0
    assert rect["y"] > 0 and rect["y"] + rect["height"] <= box[1] + box[3]
    tall = shot_score.blur_fill_rect({"width": 1000, "height": 2000}, box)
    assert tall["height"] == box[3] and tall["width"] < 1080
    assert shot_score.blur_fill_rect({}, box) is None
    detail = shot_score.blur_fill_detail({"width": 1920, "height": 1080}, box)
    assert set(detail) == {"rect", "blur_px", "bg_scale", "bg_dim"}


def _probe(tmp, value, size=(320, 136)):
    from PIL import Image
    path = Path(tmp) / f"probe_{value}.png"
    Image.new("RGB", size, (value, value, value)).save(path)
    return str(path)


def _qc(failed, luma):
    return {"usable": not failed, "failed": failed,
            "failures": [f"{k}: weak" for k in failed], "mean_luma": luma}


def test_luma_lift_raises_the_measured_brightness():
    import qc_asset
    with tempfile.TemporaryDirectory() as tmp:
        p = _probe(tmp, 18)
        _black, before = qc_asset.luma_stats(p)
        after = qc_asset.lifted_luma(p, shot_score.luma_gain(before))
    assert before < shot_score.LUMA_FLOOR <= after, (before, after)
    assert abs(after - shot_score.LUMA_LIFT_TARGET) < 2


def test_the_plan_shows_a_weak_picture_and_records_what_it_showed():
    import build_render_plan as brp
    import meme_captions
    box = meme_captions.insert_box({"output": {"width": 1080, "height": 1920}})
    with tempfile.TemporaryDirectory() as tmp:
        probe = _probe(tmp, 18)
        # wide and dark: both presentations, fit goes contain
        asset = {"kind": "clip", "fit": "cover",
                 "source_size": {"width": 1920, "height": 816}}
        presented, notes = {}, []
        shown = brp.present_picture(asset, {"qc": _qc(["coverage", "luma"], 18.0),
                                            "roi_coverage": 0.4},
                                    probe, None, box, presented, notes, 3, "s9")
        assert set(shown) == {BLUR_FILL, LUMA_LIFT}, shown
        assert asset["fit"] == "contain" and asset["presentation"] is shown
        assert shown[LUMA_LIFT]["luma_after"] >= shot_score.LUMA_FLOOR
        assert presented == {(3, "s9"): {BLUR_FILL, LUMA_LIFT}}
        assert "CF-0436" in notes[0]
        # the resolver's record counts too: framing measured on the cut clip
        asset2 = {"kind": "clip", "fit": "cover",
                  "source_size": {"width": 1920, "height": 1080}}
        got = brp.present_picture(asset2, {"qc": _qc([], 90.0)}, probe,
                                  {"soft": [LOW_FRAMING]}, box, presented, [], 4, "s2")
        assert set(got) == {BLUR_FILL} and asset2["fit"] == "contain"
        # a hard verdict and a card are left alone
        for a, qc in (({"fit": "cover", "source_size": {"width": 10, "height": 5}},
                       _qc(["coverage", "subject"], 18.0)),
                      ({"fit": "contain", "source_size": {"width": 10, "height": 5}},
                       _qc(["coverage"], 90.0))):
            assert brp.present_picture(a, {"qc": qc}, probe, None, box, {}, [], 0, "x") == {}
            assert "presentation" not in a
        # a frame the capped gain cannot lift is shown as it is
        black = _probe(tmp, 6)
        a = {"fit": "cover", "source_size": {"width": 1920, "height": 1080}}
        assert brp.present_picture(a, {"qc": _qc(["luma"], 6.0)}, black, None,
                                   box, {}, [], 0, "x") == {}


RECT = {"x": 0, "y": 600, "width": 1080, "height": 460}


def _render(tmp, name, fg_luma=None):
    """A 1080x1920, 3 s stand-in for a render: a still grey ground and, in
    RECT, a moving test pattern (or a flat patch of `fg_luma`)."""
    from common import FFMPEG
    import subprocess
    out = Path(tmp) / name
    if fg_luma is None:
        fg = "testsrc2=size=1080x460:rate=10"
    else:
        v = f"0x{fg_luma:02x}{fg_luma:02x}{fg_luma:02x}"
        fg = f"color=c={v}:size=1080x460:rate=10"
    subprocess.run([FFMPEG, "-y", "-loglevel", "error",
                    "-f", "lavfi", "-i", "color=c=0x404040:size=1080x1920:rate=10",
                    "-f", "lavfi", "-i", fg,
                    "-filter_complex", f"[0][1]overlay=0:{RECT['y']}:shortest=1",
                    "-t", "3", "-pix_fmt", "yuv420p", str(out)],
                   check=True, timeout=120)
    return str(out)


def test_qc_measures_a_blur_fill_block_on_its_picture_not_its_ground():
    import qc_render
    asset = {"kind": "clip", "src": "/nonexistent.mp4", "fit": "contain",
             "presentation": {BLUR_FILL: {"rect": RECT}}}
    vf = qc_render.picture_vf(asset)
    assert vf.startswith("crop=1080:460:0:600"), vf
    assert qc_render.picture_vf({"kind": "clip"}) == qc_render.RENDER_PROBE_VF
    [(_, got_vf, _, _)] = qc_render.probe_targets({"start": 0, "end": 3, "asset": asset}, 0)
    assert got_vf == vf
    seq = {"start": 0, "end": 3, "asset": {"kind": "sequence", "cuts": [
        {"kind": "clip", "seconds": 1.5, "src": "a.mp4"},
        {"kind": "clip", "seconds": 1.5, "src": "b.mp4", **asset}]}}
    vfs = [t[1] for t in qc_render.probe_targets(seq, 1)]
    assert vfs == [qc_render.RENDER_PROBE_VF, vf], vfs
    with tempfile.TemporaryDirectory() as tmp:
        video = _render(tmp, "moving_centre.mp4")
        shown = {"blocks": [{"start": 0.0, "end": 3.0, "asset": asset}]}
        assert qc_render.frozen_blocks(video, shown) == []
        # the same render judged on the top band reads the still ground
        cover = {"blocks": [{"start": 0.0, "end": 3.0,
                             "asset": {"kind": "clip", "src": "/nonexistent.mp4"}}]}
        got = qc_render.frozen_blocks(video, cover)
        assert got and got[0]["index"] == 0, got


def test_the_subject_gate_stands_down_for_a_blur_fill_block():
    import qc_render
    plan = {"output": {"width": 1080, "height": 1920}, "blocks": [
        {"start": 0.0, "end": 3.0, "asset": {
            "kind": "clip", "src": "/nonexistent.mp4", "roi_source": "faces",
            "focus": {"x": 0.5, "y": 0.4}, "fit": "contain",
            "presentation": {BLUR_FILL: {"rect": RECT}}}}]}
    assert qc_render.subject_blocks("/nonexistent-render.mp4", plan) == []


def test_qc_measures_a_lifted_picture_on_the_render_and_prices_a_failed_lift():
    import qc_render
    import score_log
    lifted = {"kind": "clip", "src": "/nonexistent.mp4", "fit": "contain",
              "presentation": {BLUR_FILL: {"rect": RECT},
                               LUMA_LIFT: {"gain": 2.0, "luma_before": 18.0,
                                           "luma_after": 36.0}}}
    plan = {"output": {"width": 1080, "height": 1920},
            "blocks": [{"start": 0.0, "end": 3.0, "asset": lifted}]}
    with tempfile.TemporaryDirectory() as tmp:
        bright = qc_render.lifted_blocks(_render(tmp, "lifted.mp4", fg_luma=60), plan)
        dark = qc_render.lifted_blocks(_render(tmp, "dark.mp4", fg_luma=12), plan)
    assert len(bright) == 1 and not bright[0]["fault"], bright
    assert bright[0]["luma_render"] > shot_score.LUMA_FLOOR
    assert dark[0]["fault"] and dark[0]["luma_render"] < shot_score.LUMA_FLOOR, dark
    assert qc_render.lifted_blocks("/x.mp4", {"blocks": [
        {"start": 0, "end": 1, "asset": {"kind": "clip"}}]}) == []
    res = {"measured": {"lifted_blocks": dark}, "failures": []}
    rules = [f["rule"] for f in score_log.qc_findings(res, plan)]
    assert rules == ["score.low_brightness"], rules
    res = {"measured": {"lifted_blocks": bright}, "failures": []}
    assert score_log.qc_findings(res, plan) == []


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
