"""CF-0352: a wide shot of a place is not a badly framed shot.

Anchor v4 of everyday-sorcery-2 (a white Victorian house) had three pool shots
of that house at roi_coverage 0.33-0.40 (saliency boxes - no face): the 0.65
floor made each one `low_framing`. For a place anchor and a shot whose subject
box is not a face, coverage is no rule; for a person it stays."""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import wide_place  # noqa: E402

HOUSE = ("a white Victorian-style house with a wraparound porch and "
         "surrounding trees in daylight")


def test_the_house_of_everyday_sorcery_2_is_a_place():
    assert wide_place.is_place_anchor(HOUSE)
    assert wide_place.is_place_anchor(
        "the interior wooden framework of a house under construction, exposed beams")
    assert wide_place.is_place_anchor("a wide view of dark hills at dusk")
    assert wide_place.is_place_anchor(
        "an aerial establishing shot of a coastal city skyline with a large "
        "suspension bridge crossing the water")


def test_a_person_a_creature_a_vehicle_or_a_name_is_not():
    for phrase in (
            "two women standing in a wood-paneled room, name captions reading "
            "Nora Kingsley and Sandra Birch",
            "a red-and-blue-suited hero standing tall, facing the camera on a "
            "tiled path under open sky",
            "Kaijura looming beside a tall stone clock tower building amid "
            "smoke and fire in a city",
            "Vision, a metallic android with a glowing gem in his forehead, "
            "standing amid a blue-lit night cityscape",
            "a funeral gathering outside a stone church, villagers in cloaks "
            "stand around open graves",
            "a biplane trailing colored smoke banks low over a stadium track",
            "a close-up of a car's headlight and front grille parked on an "
            "ordinary street",
            "a close-up of Florence Pugh mid-sentence",
            "a bright full moon in a dark night sky",
    ):
        assert not wide_place.is_place_anchor(phrase), phrase


def test_a_face_keeps_its_gate():
    assert wide_place.wide_ok("saliency")
    assert wide_place.wide_ok("animation_center")
    assert not wide_place.wide_ok("faces")
    assert not wide_place.wide_ok("none")
    assert not wide_place.wide_ok(None)


def test_the_pool_record_loses_low_framing_only():
    u = {"task": "CF-0435", "score": 0.95, "penalty": 5,
         "soft": [{"rule": "low_framing", "price": 3},
                  {"rule": "low_resolution", "price": 2}], "hard": []}
    out = wide_place.waive_record(u)
    assert [v["rule"] for v in out["soft"]] == ["low_resolution"]
    assert out["penalty"] == 2 and out["score"] == 0.98
    assert u["penalty"] == 5, "the input is not changed"
    clean = {"soft": [], "hard": [], "penalty": 0, "score": 1.0}
    assert wide_place.waive_record(clean) is clean


def test_a_saliency_verdict_loses_coverage_a_face_verdict_does_not():
    qc = {"usable": False, "failed": ["coverage"], "roi_source": "saliency",
          "roi_coverage": 0.39,
          "failures": ["framing: a focus-aware crop keeps only 39% of the subject (< 65%)"]}
    out, cov = wide_place.waive_qc(qc)
    assert out["usable"] and out["failed"] == [] and out["failures"] == []
    assert cov == 0.39
    assert qc["failed"] == ["coverage"]
    face = dict(qc, roi_source="faces")
    assert wide_place.waive_qc(face) == (face, None)
    both = dict(qc, failed=["coverage", "luma"],
                failures=qc["failures"] + ["luma: too dark"])
    out, _ = wide_place.waive_qc(both)
    assert not out.get("usable") and out["failed"] == ["luma"]
    assert out["failures"] == ["luma: too dark"]


def test_the_mark_is_a_warning_not_a_price():
    rec = wide_place.mark(None, 0.392, "saliency")
    assert rec["soft"] == [] and rec["penalty"] == 0
    assert rec["warn"] == ["wide_place_shot"]
    assert rec["wide_place"] == {"task": "CF-0352", "coverage": 0.392,
                                 "roi_source": "saliency"}
    assert wide_place.waived(rec)
    weak = wide_place.mark({"soft": ["low_brightness"], "penalty": 3}, 0.3)
    assert weak["soft"] == ["low_brightness"] and weak["penalty"] == 3
    assert not wide_place.waived({"soft": ["low_framing"]})



# --- the resolver ------------------------------------------------------------

import json  # noqa: E402
import os  # noqa: E402
import tempfile  # noqa: E402
from types import SimpleNamespace  # noqa: E402

os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0352-runlog-")))

import cache_fingerprint  # noqa: E402
import resolve_anchors as ra  # noqa: E402
import shot_score  # noqa: E402

IDX = "/idx/v.shots.json"


def _shot(n, roi_source="saliency", cover=0.39):
    return {"index": n, "start": 0.0, "end": 8.0, "on_topic": True,
            "burned_text": False,
            "usable_cached": {"roi_source": roi_source, "roi_coverage": cover,
                              "black_fraction": 0.05, "mean_luma": 100.0,
                              "short_side": 1080, "width": 1920, "height": 1080,
                              "measured_by": cache_fingerprint.usability_fingerprint()}}


def _cand(n, score, **kw):
    return {"shot": n, "start": 0.0, "end": 8.0, "score": score, "card": False,
            "index": IDX, "source": "/src/vCOn4RibD1g.mp4", **kw}


def _ranked(pool, lut, place):
    saved = shot_score.SHARPNESS_PROBES_PER_RANK
    real = shot_score.rank

    def no_probe(*a, **k):
        k["probes"] = 0
        return real(*a, **k)
    shot_score.rank = no_probe
    try:
        return [c["shot"] for c in ra.rank_by_usability(pool, lut, place)]
    finally:
        shot_score.rank = real
        shot_score.SHARPNESS_PROBES_PER_RANK = saved


def test_a_place_anchor_ranks_its_wide_house_first():
    """vCOn4RibD1g:24 (0.2896, coverage 0.39, saliency) against a clean shot
    of something else that also cleared the floor: for the house it is no
    longer `low_framing`, so the matcher's order holds."""
    if shot_score.indexer() is None:
        print("SKIP: no footage-indexer")
        return
    lut = {(IDX, 24): _shot(24), (IDX, 7): _shot(7, "faces", 0.9)}
    pool = [_cand(24, 0.2896), _cand(7, 0.23)]
    assert _ranked(pool, lut, place=False) == [7, 24]
    assert _ranked(pool, lut, place=True) == [24, 7]


def test_a_face_or_a_topic_rung_keeps_low_framing():
    if shot_score.indexer() is None:
        print("SKIP: no footage-indexer")
        return
    lut = {(IDX, 1): _shot(1, "faces", 0.4), (IDX, 2): _shot(2, "faces", 0.9)}
    assert _ranked([_cand(1, 0.3), _cand(2, 0.25)], lut, place=True) == [2, 1]
    lut = {(IDX, 1): _shot(1), (IDX, 2): _shot(2, "faces", 0.9)}
    pool = [_cand(1, 0.0, topic_rung="topic_pool"),
            _cand(2, 0.0, topic_rung="topic_pool")]
    assert _ranked(pool, lut, place=True) == [2, 1]


def _verdict(roi_source, cover):
    ok = cover >= 0.65
    return {"usable": ok, "failed": [] if ok else ["coverage"],
            "failures": [] if ok else [f"framing: a focus-aware crop keeps only "
                                       f"{cover:.0%} of the subject (< 65%)"],
            "roi_source": roi_source, "roi_coverage": cover,
            "coverage_window": {"focus": {"x": 0.5, "y": 0.5}, "zoom": 1.0}}


def _usable(verdict, wide):
    saved = ra.grab_frames, ra.run_tool
    with tempfile.TemporaryDirectory() as tmp:
        probes = []
        for k in range(ra.PROBE_FRAMES):
            p = Path(tmp) / f"p{k}.png"
            p.write_bytes(b"")
            probes.append(str(p))
        ra.grab_frames = lambda *a, **k: probes
        ra.run_tool = lambda *a, **k: SimpleNamespace(stdout=json.dumps(verdict),
                                                      stderr="")
        soft = []
        try:
            import contextlib
            import io
            with contextlib.redirect_stderr(io.StringIO()):
                ok, failures = ra.usable(str(Path(tmp) / "c.mp4"), 3.0, 720, 0.65,
                                         0.9, soft_out=soft, wide_out=wide)
        finally:
            ra.grab_frames, ra.run_tool = saved
    return ok, soft


def test_the_cut_clip_of_a_place_is_not_low_framing():
    wide = []
    ok, soft = _usable(_verdict("saliency", 0.39), wide)
    assert ok and soft == [], soft
    assert wide and wide[0] == (0.39, "saliency")
    rec = ra.wide_record(None, wide)
    assert rec["soft"] == [] and rec["warn"] == ["wide_place_shot"]
    assert rec["wide_place"]["coverage"] == 0.39
    # the same clip for a person's anchor (no wide_out) is priced, as before
    ok, soft = _usable(_verdict("saliency", 0.39), None)
    assert ok and soft == ["low_framing"], soft
    # and a face is priced even for a place
    wide = []
    ok, soft = _usable(_verdict("faces", 0.39), wide)
    assert ok and soft == ["low_framing"] and wide == [], (soft, wide)
    assert ra.wide_record({"soft": ["low_framing"]}, wide) == {"soft": ["low_framing"]}


def test_the_waived_record_survives_the_held_frame_sharpness_pass():
    rec = ra.wide_record(None, [(0.33, "saliency")])
    again = shot_score.with_sharpness(rec, None)
    assert again and wide_place.waived(again) and again["soft"] == []
    assert again["penalty"] == 0



# --- the plan ----------------------------------------------------------------

def test_the_plan_neither_prices_nor_blur_fills_a_marked_wide_place():
    import build_render_plan as brp
    rec = ra.wide_record(None, [(0.39, "saliency")])
    info = {"qc": _verdict("saliency", 0.39), "roi_coverage": 0.39}
    notes = []
    brp.waive_wide_place(info, rec, notes, 3)
    assert info["qc"]["usable"] and info["qc"]["failed"] == []
    assert notes and "wide view of a place" in notes[0] and "CF-0352" in notes[0]
    rejected, weak = [], {}
    brp.asset_gate(rejected, weak, notes, 3, "a.mp4", info["qc"], "vCOn4RibD1g:24")
    assert rejected == [] and weak == {}, weak
    target, presented = {"source_size": {"width": 1920, "height": 1080}}, {}
    shown = brp.present_picture(target, info, None, rec,
                                {"x": 0, "y": 0, "width": 1080, "height": 1400},
                                presented, notes, 3, "vCOn4RibD1g:24")
    assert shown == {} and "fit" not in target and presented == {}
    assert shot_score.plan_findings([{"shot": "vCOn4RibD1g:24", "usability": rec,
                                      "_start": 1.0}], extra=weak) == []


def test_the_plan_keeps_the_floor_for_an_unmarked_picture_or_a_face():
    import build_render_plan as brp
    for rec, roi in ((None, "saliency"),
                     (ra.wide_record(None, [(0.39, "saliency")]), "faces")):
        info = {"qc": _verdict(roi, 0.39)}
        notes = []
        brp.waive_wide_place(info, rec, notes, 3)
        assert info["qc"]["failed"] == ["coverage"] and notes == []
        weak = {}
        brp.asset_gate([], weak, notes, 3, "a.mp4", info["qc"], "v:1")
        assert weak == {(3, "v:1"): {"low_framing"}}


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
