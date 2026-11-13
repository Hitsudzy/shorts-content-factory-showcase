#!/usr/bin/env python3
"""CF-0275: a shot whose text the delivered 9:16 window cuts in half is
refused before it is cut, and the refusal says so by name.

The defect is the first DoD-of-the-video violation found by eye (batch
`example-film/2026-09-17T1901Z`, `mormon-wives-comeback`, 26-31s): two
split-screen shots of a commentary video where `cover` on the host's face
keeps half of the left-hand text panel - a Vulture article in shot 9 of
`-3NpUXI5juI`, a phone thread in shot 54 - so the render shows words ending
mid-glyph and our captions land on somebody else's interface.

Every number below is the *real* measurement CF-0275's indexer half made on
real pool frames (25 shots, 6 sources, 2026-09-18), copied from the task
file's «Замер» table, which is the provenance of this fixture:
`tasks/CF-0275-split-screen-text-cut-by-vertical-crop.md`. Nothing here is
synthetic, so the thresholds are pinned against the material they were chosen
on rather than against numbers written to make them pass.

What these tests hold in place:

  * both shots of the defect are refused, and each by the clause that can
    actually see it - shot 9 by cut area, shot 54 (which cuts no region at
    all: the window's edge landed 7px past the end of the line) by the
    text-panel clause;
  * ordinary footage stays usable, including the three traps in the
    measurement - the one-region SUBSCRIBE plate that scores `text_cut_by_crop`
    1.000, the ordinary shot at 0.932 `text_outside_crop`, and the
    split-screen whose left half is a photograph, not text;
  * cards are excluded before any threshold (they are delivered `contain`,
    so there is no window to be cut by);
  * an index that never measured this is not condemned by it;
  * the refusal reaches `rejected_candidates` / the coverage preflight under
    the name `text_cut_by_crop`, not as the generic cached-usability sentence.

No pytest - plain asserts, run through tests/run_tests.py, same shape as
test_prefilter_resolution_geometry.py.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import cache_fingerprint  # noqa: E402
import resolve_anchors  # noqa: E402

THRESHOLDS = (720, 0.65, resolve_anchors.MAX_BLACK_CLIPS)

# Vision numbers that clear every *other* check comfortably, so every
# assertion below turns on the text axis alone. The geometry is the real one
# of both defect shots (1920x1080 landscape).
CLEAN_OTHER_CHECKS = {
    "short_side": 1080, "width": 1920, "height": 1080,
    "roi_source": "faces", "roi_coverage": 0.90,
    "black_fraction": 0.008, "mean_luma": 164.3,
}

# --- the measurement, verbatim -------------------------------------------
# name -> (text_regions, text_area, text_outside_crop, text_cut_by_crop,
#          text_cut_area, is_card)
# `None` where the probe found no text at all: measured, nothing to cut.
MEASURED = {
    # the two shots the operator found by eye
    "-3NpUXI5juI:9":  (20, 0.1459, 0.761, 0.300, 0.0968, False),
    "-3NpUXI5juI:54": (23, 0.0284, 0.9705, 0.000, 0.0000, False),
    # the same construction in the same video - a text panel beside the host
    "-3NpUXI5juI:4":  (18, 0.0702, 0.667, 0.278, 0.0516, False),
    "-3NpUXI5juI:20": (9, 0.1085, 0.940, 0.444, 0.0751, False),
    # ordinary shots of the same video: the host talking to camera
    "-3NpUXI5juI:37": (3, 0.0172, 0.440, 0.667, 0.0139, False),
    "-3NpUXI5juI:40": (1, 0.0174, 0.411, 1.000, 0.0174, False),
    "-3NpUXI5juI:42": (1, 0.0174, 0.262, 1.000, 0.0174, False),
    "-3NpUXI5juI:59": (3, 0.0173, 0.439, 0.667, 0.0139, False),
    "-3NpUXI5juI:56": (0, None, None, None, None, False),
    "-3NpUXI5juI:58": (0, None, None, None, None, False),
    # split screens whose other half is a photograph, not text
    "-3NpUXI5juI:8":  (0, None, None, None, None, False),
    "-3NpUXI5juI:31": (16, 0.0185, 0.983, 0.4375, 0.0020, False),
    # other sources of the pool
    "m9R6j1KLRbQ:1":  (14, 0.0570, 0.853, 0.071, 0.0003, False),
    "m9R6j1KLRbQ:3":  (5, 0.0481, 0.932, 0.000, 0.0000, False),
    "m9R6j1KLRbQ:12": (1, 0.0025, 1.000, 0.000, 0.0000, False),
    "PgPdzyiQ_oQ:17": (1, 0.0263, 0.000, 0.000, 0.0000, False),
    "PgPdzyiQ_oQ:34": (1, 0.0205, 0.000, 0.000, 0.0000, False),
    "3fa-PJ3UQpg:7":  (4, 0.0483, 0.560, 0.250, 0.0422, False),
    "3fa-PJ3UQpg:21": (5, 0.0512, 0.585, 0.200, 0.0422, False),
    "5oYeeUNkif8:43": (0, None, None, None, None, False),
    "QE0W5UW2qxE:27": (3, 0.0083, 1.000, 0.000, 0.0000, False),
    # cards: delivered `contain`, so these numbers describe a window no render
    # of theirs will ever use
    "m9R6j1KLRbQ:0":  (3, 0.0548, 0.201, 1.000, 0.0548, True),
    "-3NpUXI5juI:14": (9, 0.1723, 0.995, 0.000, 0.0000, True),
    "-3NpUXI5juI:47": (4, 0.0881, 0.889, 0.500, 0.0857, True),
    "-3NpUXI5juI:51": (9, 0.1723, 0.989, 0.111, 0.0494, True),
}

# The task's mandatory positives, plus the two shots of the same construction
# in the same video that the rule is expected to take with them.
MUST_REFUSE = ("-3NpUXI5juI:9", "-3NpUXI5juI:54", "-3NpUXI5juI:4", "-3NpUXI5juI:20")
MUST_KEEP = tuple(n for n in MEASURED if n not in MUST_REFUSE)


def shot(name, **extra):
    """The candidate a resolver would hold for this measured shot: cached
    numbers stamped by the code running now, so nothing here turns on
    staleness (CF-0048 has its own test)."""
    regions, area, outside, cut, cut_area, is_card = MEASURED[name]
    cached = dict(CLEAN_OTHER_CHECKS,
                  measured_by=cache_fingerprint.usability_fingerprint(),
                  text_regions=regions, text_area=area,
                  text_outside_crop=outside, text_cut_by_crop=cut,
                  text_cut_area=cut_area)
    if is_card:
        # A card is dark on purpose and answers for it with its own ink
        # (CF-0047); without this the card assertions below would turn on
        # darkness instead of on text.
        cached["card_ink_fraction"] = 0.30
    return {"index": "x.shots.json", "shot": int(name.split(":")[1]),
            "start": 10.0, "end": 40.0, "is_card": is_card,
            "crop_bottom_cached": 0.0, "usable_cached": cached, **extra}


# --- the rule on the measurement ------------------------------------------

def test_both_shots_of_the_defect_are_refused():
    """The task's mandatory positives. Shot 9 is a panel the window cuts;
    shot 54 is a panel the window stands beside - and each is caught by the
    clause that can see it, which is why there are two."""
    nine = resolve_anchors.text_cut_refusal(shot("-3NpUXI5juI:9"),
                                            shot("-3NpUXI5juI:9")["usable_cached"])
    assert nine and "9.7% of the frame" in nine, nine
    fifty_four = resolve_anchors.text_cut_refusal(
        shot("-3NpUXI5juI:54"), shot("-3NpUXI5juI:54")["usable_cached"])
    assert fifty_four and "23 text regions" in fifty_four, fifty_four
    for name in MUST_REFUSE:
        s = shot(name)
        assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]), name
        assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is True, name


def test_ordinary_footage_of_the_whole_measurement_stays_usable():
    """Every other shot measured, including the two `m9R6j1KLRbQ` shots the
    task names as negatives outright."""
    for name in MUST_KEEP:
        s = shot(name)
        assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]) is None, name
        assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False, name


def test_the_region_share_alone_would_have_condemned_the_host_talking():
    """Why `text_cut_area` and not `text_cut_by_crop`: shots 40 and 42 hold
    one region each - the host's own SUBSCRIBE plate - the window clips it,
    and they score a perfect 1.000, higher than either shot of the real
    defect. The share of the frame tells them apart by two orders of
    magnitude."""
    for name in ("-3NpUXI5juI:40", "-3NpUXI5juI:42"):
        regions, _area, _outside, cut, cut_area, _card = MEASURED[name]
        assert regions == 1 and cut == 1.000
        assert cut_area < MEASURED["-3NpUXI5juI:9"][4] / 5
        s = shot(name)
        assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]) is None


def test_the_outside_share_alone_would_have_condemned_ordinary_shots():
    """Why the panel clause needs the region count too: text the window shows
    *none* of breaks nothing, and three perfectly ordinary shots sit at or
    near 1.000 `text_outside_crop`. What separates shot 54 from them is that
    23 regions is a document, not a caption."""
    for name in ("m9R6j1KLRbQ:12", "QE0W5UW2qxE:27", "-3NpUXI5juI:31"):
        _regions, _area, outside, _cut, _cut_area, _card = MEASURED[name]
        assert outside >= resolve_anchors.TEXT_PANEL_OUTSIDE_MIN - 0.02
        s = shot(name)
        assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]) is None, name


def test_the_thresholds_sit_inside_the_gaps_the_measurement_left():
    """The thresholds are not free parameters: they are pinned between the
    worst negative and the weakest positive of the measurement, so moving
    either one has to break this test first and argue with the numbers."""
    cards = {n for n, m in MEASURED.items() if m[5]}
    cut_areas = {n: m[4] for n, m in MEASURED.items()
                 if n not in cards and m[4] is not None}
    weakest_positive = min(cut_areas[n] for n in MUST_REFUSE if cut_areas[n] > 0)
    worst_negative = max(cut_areas[n] for n in cut_areas if n not in MUST_REFUSE)
    assert worst_negative == 0.0422, worst_negative   # the NBC lower-third
    assert weakest_positive == 0.0516, weakest_positive
    assert worst_negative < resolve_anchors.TEXT_CUT_AREA_MAX < weakest_positive

    # The panel clause: shot 54 is the only shot in the measurement that meets
    # both halves of it, cards included.
    meets = {n for n, (regions, _a, outside, _c, _ca, _card) in MEASURED.items()
             if outside is not None
             and outside >= resolve_anchors.TEXT_PANEL_OUTSIDE_MIN
             and regions >= resolve_anchors.TEXT_PANEL_REGIONS_MIN}
    assert meets == {"-3NpUXI5juI:54"}, meets


# --- the reading rules from the indexer's contract ------------------------

def test_a_card_is_excluded_before_the_threshold():
    """A card is delivered `contain` (`common.delivery_fit`): the window is
    the whole frame, nothing is cut, and the `cover` numbers measured for it
    are simply about a window it will never be shown in. Both cards that would
    otherwise trip a clause are checked - by cut area and by the panel
    clause."""
    for name in ("m9R6j1KLRbQ:0", "-3NpUXI5juI:47"):
        assert MEASURED[name][4] > resolve_anchors.TEXT_CUT_AREA_MAX
        s = shot(name)
        assert s["is_card"] is True
        assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]) is None, name
        # and the same numbers on a non-card *are* refused, so the exemption
        # is the card-ness and nothing else
        del s["is_card"]
        assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]), name


def test_an_index_that_never_measured_this_is_not_condemned_by_it():
    """A missing key is not `null` (CF-0047's rule for `card_ink_fraction`,
    restated in CF-0275's contract): an index built before CF-0275 never asked
    the question, and until the pool is remeasured that is every index in it.
    "Unknown" is not "doomed"."""
    s = shot("-3NpUXI5juI:9")
    for key in ("text_regions", "text_area", "text_outside_crop",
                "text_cut_by_crop", "text_cut_area"):
        del s["usable_cached"][key]
    assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]) is None
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False


def test_measured_and_textless_is_not_condemned_either():
    """`text_regions: 0` with four nulls is the other state: the probe ran and
    found no text. Nothing to cut."""
    s = shot("-3NpUXI5juI:56")
    assert s["usable_cached"]["text_regions"] == 0
    assert s["usable_cached"]["text_cut_area"] is None
    assert resolve_anchors.text_cut_refusal(s, s["usable_cached"]) is None


def test_a_cache_this_checkout_cannot_vouch_for_still_decides_nothing():
    """CF-0048 stands in front of the new rule as it does in front of the old
    one: numbers some other version of the measuring code produced are not
    believed, however damning they look."""
    s = shot("-3NpUXI5juI:9")
    s["usable_cached"]["measured_by"] = "0000deadbeef"
    assert resolve_anchors.probably_unusable(s, *THRESHOLDS) is False
    assert resolve_anchors.precut_cache_refusal(s, *THRESHOLDS) is None


# --- how the refusal lands ------------------------------------------------

def test_the_refusal_is_named_where_a_block_records_it():
    """`precut_refusal()` is the one screening every caller shares
    (CF-0140), and what it writes is what `rejected_candidates` and
    `anchor_coverage.py`'s `refusals[]` carry. The new refusal has to arrive
    under its own name: an operator who sees a block change picture reads
    this sentence, and "pre-filtered by cached shot usability" would send them
    looking at the pool instead of at the framing."""
    s = shot("-3NpUXI5juI:9")
    cand = {"index": s["index"], "shot": s["shot"], "source": "-3NpUXI5juI.mp4",
            "start": s["start"], "end": s["end"], "score": 0.309, "moment_at": None}
    _at, _origin, _span, refusal = resolve_anchors.precut_refusal(
        cand, s, *THRESHOLDS)
    assert refusal is not None
    assert refusal["cause"] == resolve_anchors.CAUSE_FOOTAGE_UNUSABLE
    assert refusal["record"]["reason"].startswith(
        resolve_anchors.REASON_TEXT_CUT_BY_CROP), refusal["record"]["reason"]
    assert refusal["record"]["score"] == 0.309
    assert refusal["log"] is None


def test_the_other_cached_refusal_keeps_its_own_sentence():
    """The generic cached-usability refusal is untouched - CF-0029's sentence
    is what three other tests and every past storyboard read."""
    s = shot("m9R6j1KLRbQ:3")
    s["usable_cached"]["black_fraction"] = 0.99
    s["usable_cached"]["mean_luma"] = 3.0
    # CF-0435: the sentence gains the hard rule that fired after a dash;
    # its head - what every past storyboard reads - is unchanged.
    why = resolve_anchors.precut_cache_refusal(s, *THRESHOLDS)
    assert why.startswith("pre-filtered by cached shot usability, not cut - "
                          "black_frame"), why


def test_remeasure_sees_the_same_opinion_as_the_resolver():
    """`remeasure_usability.py` asks `cached_verdict()` directly for what a
    remeasure changes about the pre-filter's opinion (CF-0048), so the text
    rule has to live inside it and not only in the wrapper - otherwise the
    remeasure report would understate exactly the shots this task is about."""
    s = shot("-3NpUXI5juI:54")
    assert resolve_anchors.cached_verdict(s, s["usable_cached"], *THRESHOLDS) is True
    clean = shot("m9R6j1KLRbQ:3")
    assert resolve_anchors.cached_verdict(
        clean, clean["usable_cached"], *THRESHOLDS) is False


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
