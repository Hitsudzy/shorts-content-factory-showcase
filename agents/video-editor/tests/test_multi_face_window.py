#!/usr/bin/env python3
"""CF-0292: a 9:16 window laid on the gap between two people, scored 0.895.

The last block of `delver.mp4` (batch 2026-09-18T2232Z, 35.17-44.125s, the
longest block in the video) is a wide two-shot: Tom Carver on a stool at
x=0.33 of a 1920x1080 frame, his interviewer at x=0.70, an empty hangar
between them. Vision found both faces, `_find_roi` merged them into one
679px-wide union box, `crop_for_aspect` centred the 607px cover window on that
box's centroid - and the centroid is the hangar. The delivered frame contained
no face at all (the viewer: "only the hosts' legs left"), while `roi_coverage`
reported 0.895 and every gate let it through, because 0.895 was the honest
answer to "how much of the union box is inside the window" and nobody was
asking "is a person on screen".

The numbers below are that frame's real Vision output, measured once and
pinned here (`smart_crop._find_roi` on
`work/delver/clips/s07_held_a07_fkuxNGbx1qk_s045.png`); no Vision, no images,
no ffmpeg in this file, so the arithmetic that decides a shot's fate is
checkable without the batch. The regression half pins the two shapes that must
NOT move: one face, and a group that fits in the window whole.

No pytest - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import smart_crop  # noqa: E402
import qc_asset  # noqa: E402
from common import MIN_COVERAGE  # noqa: E402

# The real frame: 1920x1080, two faces, as analyse() rounds them.
DELVER_SIZE = (1920, 1080)
CRUISE = (631, 417, 67, 67)        # x=0.33 of the frame
INTERVIEWER = (1241, 392, 69, 69)  # x=0.70 of the frame
DELVER_FACES = [CRUISE, INTERVIEWER]
# What _find_roi merged them into, and what the plan was built from.
DELVER_UNION = (631, 392, 679, 92)
# plan.json's own numbers for that block, before this fix.
PLAN_FOCUS = (0.5055, 0.3456)
PLAN_COVERAGE = 0.895
PLAN_ZOOM = 1.0


def _vision(roi, parts, size=DELVER_SIZE, source="faces"):
    """An analyse()-shaped dict, as vision_client hands one to the gate."""
    return {
        "source_size": {"width": size[0], "height": size[1]},
        "roi_source": source,
        "roi": smart_crop.roi_dict(roi),
        "roi_parts": [smart_crop.roi_dict(p) for p in parts] if len(parts) > 1 else None,
        "roi_coverage": PLAN_COVERAGE,
        "zoom": PLAN_ZOOM,
    }


def test_old_measure_really_did_report_0_895_on_an_empty_window():
    """The defect, pinned: the union box's dimension product - the number the
    plan carried - passes the floor comfortably for this frame."""
    rect, contained, zoom = smart_crop.crop_for_aspect(
        DELVER_UNION, DELVER_SIZE, 9, 16, single_subject=False)
    product = (min(DELVER_UNION[2], rect[2]) * min(DELVER_UNION[3], rect[3])
               / (DELVER_UNION[2] * DELVER_UNION[3]))
    assert round(product, 3) == PLAN_COVERAGE, (
        f"expected the plan's own 0.895, got {product:.3f} - the fixture no "
        f"longer reproduces the batch it was taken from")
    assert product > MIN_COVERAGE, "the frame passed the gate; that is the bug"
    assert not contained


def test_new_measure_fails_the_same_window():
    """Measured over the faces instead of over their union, the window the
    viewer actually got keeps barely half of the better-served face - under
    the floor, which is the verdict that was missing."""
    coverage = smart_crop.faces_coverage(
        DELVER_FACES, DELVER_SIZE, PLAN_FOCUS, PLAN_ZOOM, 9, 16)
    assert round(coverage, 3) == 0.515, f"expected 0.515, got {coverage:.3f}"
    assert coverage < MIN_COVERAGE

    # And neither face is anywhere near whole in it: the window catches the
    # inner edge of each head and nothing else.
    per_face = [smart_crop.window_coverage(f, DELVER_SIZE, PLAN_FOCUS, PLAN_ZOOM, 9, 16)
                for f in DELVER_FACES]
    assert all(c < MIN_COVERAGE for c in per_face), per_face


def test_window_moves_off_the_gap_onto_a_face():
    """Step two: the window is built around one face, and that face is in it
    whole. The two heads are the same size to within Vision's noise, so the
    tie goes to the one nearer the frame's centre - Cruise."""
    chosen = smart_crop.window_face(DELVER_FACES, DELVER_SIZE, 9, 16)
    assert chosen == CRUISE, f"expected the centre-most of two tied faces, got {chosen}"

    info = _vision(chosen, DELVER_FACES)
    focus = smart_crop.focus_point(info)
    assert abs(focus[0] - 0.3461) < 0.001, focus
    coverage = smart_crop.subject_coverage(info, focus, PLAN_ZOOM, 9, 16)
    assert coverage == 1.0, f"the chosen face must be whole in its own window, got {coverage}"

    x, y, w, h = smart_crop.delivered_window(DELVER_SIZE, focus, PLAN_ZOOM, 9, 16)
    assert x <= CRUISE[0] and CRUISE[0] + CRUISE[2] <= x + w, (
        f"face {CRUISE} is not inside the delivered window {(x, y, w, h)}")
    # The old window started at 663px, i.e. past the right edge of that face.
    assert x < 663, f"window did not move off the gap: x={x}"


def test_planner_and_gate_agree_on_the_moved_window():
    """The plan points where the measure was taken: build_render_plan.framing()
    reads focus_point() off the same narrowed ROI, and qc_asset judging a frame
    against that window gets the face measure, not the union one."""
    import build_render_plan
    info = _vision(CRUISE, DELVER_FACES)
    info["roi_coverage"] = 1.0
    framed = build_render_plan.framing(info)
    assert abs(framed["focus"]["x"] - 0.3461) < 0.001, framed

    judged = qc_asset.against_window(
        dict(info), "9:16", (framed["focus"]["x"], framed["focus"]["y"]),
        framed["zoom"], "cover")
    assert judged["roi_coverage"] == 1.0, judged["roi_coverage"]

    # The same frame judged against the window the *old* plan used fails.
    stale = qc_asset.against_window(dict(info), "9:16", PLAN_FOCUS, PLAN_ZOOM, "cover")
    assert stale["roi_coverage"] == 0.515, stale["roi_coverage"]
    assert stale["roi_coverage"] < MIN_COVERAGE


def test_under_the_floor_is_unusable_for_cover():
    """A frame whose best-served face is still under the floor fails the gate
    on `coverage` - the keyed verdict resolve_anchors.py reads to move on to
    the next candidate (CF-0290), not a silent pass."""
    info = _vision(DELVER_UNION, DELVER_FACES)
    judged = qc_asset.against_window(dict(info), "9:16", PLAN_FOCUS, PLAN_ZOOM, "cover")
    verdict = qc_asset.evaluate(judged, black=0.1, mean_luma=120.0,
                                min_short_side=0, min_coverage=MIN_COVERAGE,
                                max_black=0.9, min_mean_luma=30)
    assert not verdict["usable"], verdict
    assert "coverage" in verdict["failed"], verdict["failed"]


# --- regressions: the shapes that must not move -------------------------

SINGLE_FACE = (701, 166, 303, 303)     # still_08, rapid-reckless batch (CF-0033)
SINGLE_SIZE = (1920, 816)


def test_single_face_is_untouched():
    """One face has no parts to choose between: no narrowing, no face measure,
    the same window and the same coverage as before CF-0292."""
    assert smart_crop.window_face([SINGLE_FACE], SINGLE_SIZE, 9, 16) is None
    rect, contained, zoom = smart_crop.crop_for_aspect(
        SINGLE_FACE, SINGLE_SIZE, 9, 16, single_subject=True)
    assert (rect[2], rect[3]) == (459, 816) and zoom == 1.0 and contained
    coverage = smart_crop.own_coverage(SINGLE_FACE, rect, SINGLE_SIZE, "faces",
                                       [SINGLE_FACE], zoom, 9, 16)
    assert coverage == 1.0

    info = _vision(SINGLE_FACE, [SINGLE_FACE], SINGLE_SIZE)
    assert info["roi_parts"] is None, "a lone face is the ROI, not a part of it"
    focus = smart_crop.focus_point(info)
    assert smart_crop.subject_coverage(info, focus, 1.0, 9, 16) == \
        smart_crop.window_coverage(SINGLE_FACE, SINGLE_SIZE, focus, 1.0, 9, 16)


# A tight two-shot: both heads inside a 607px window with room to spare, the
# shape CF-0033's "leave the union alone" rule was right about.
TIGHT_PAIR = [(820, 300, 90, 90), (1010, 315, 86, 86)]
TIGHT_UNION = (820, 300, 276, 101)


def test_tight_group_keeps_its_union_framing():
    assert smart_crop.window_face(TIGHT_PAIR, DELVER_SIZE, 9, 16) is None, (
        "a group that fits in the window must keep the union framing")
    rect, contained, zoom = smart_crop.crop_for_aspect(
        TIGHT_UNION, DELVER_SIZE, 9, 16, single_subject=False)
    assert (rect[2], rect[3]) == (608, 1080) and zoom == 1.0 and contained
    coverage = smart_crop.own_coverage(TIGHT_UNION, rect, DELVER_SIZE, "faces",
                                       TIGHT_PAIR, zoom, 9, 16)
    assert coverage == 1.0, f"both faces are whole in this window, got {coverage}"


def test_best_served_face_is_the_measure_not_the_total_area():
    """A window holding one person whole is a good shot of that person. The
    other face being outside it is the price of a 9:16 window, not a half
    failure - a total-area measure would have scored this 0.5 and refused a
    frame with a perfectly framed face in it."""
    focus = (0.3461, 0.3571)
    coverage = smart_crop.faces_coverage(DELVER_FACES, DELVER_SIZE, focus, 1.0, 9, 16)
    assert coverage == 1.0
    left_out = smart_crop.window_coverage(INTERVIEWER, DELVER_SIZE, focus, 1.0, 9, 16)
    assert left_out == 0.0, "the interviewer really is outside that window"


def test_saliency_and_empty_parts_fall_back_to_the_roi_box():
    """Only faces get the face measure. A saliency box has no parts, and a
    dict from an older measurement carries none either - both must answer
    exactly as window_coverage() always did."""
    info = _vision(DELVER_UNION, DELVER_FACES, source="saliency")
    focus = smart_crop.focus_point(info)
    assert smart_crop.subject_coverage(info, focus, 1.0, 9, 16) == \
        smart_crop.window_coverage(DELVER_UNION, DELVER_SIZE, focus, 1.0, 9, 16)

    legacy = _vision(DELVER_UNION, [DELVER_UNION])  # no roi_parts key at all
    legacy.pop("roi_parts")
    assert smart_crop.subject_coverage(legacy, PLAN_FOCUS, 1.0, 9, 16) == \
        smart_crop.window_coverage(DELVER_UNION, DELVER_SIZE, PLAN_FOCUS, 1.0, 9, 16)


def test_cache_fingerprint_moved_with_the_measuring_code():
    """CF-0029/CF-0048: the cached numbers in shots.json were made by the old
    measure, and the fingerprint over the measuring sources is what stops them
    passing as current. smart_crop.py and qc_asset.py are both in that set, so
    this change invalidates them by construction - pinned here because the set
    is a list someone could shorten."""
    import cache_fingerprint
    names = {Path(p).name for p in cache_fingerprint.USABILITY_SOURCES}
    assert {"smart_crop.py", "qc_asset.py"} <= names, names


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
