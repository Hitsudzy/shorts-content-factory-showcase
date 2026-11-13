#!/usr/bin/env python3
"""CF-0791: the root's shot rule (`shared/score/shot_guard.py`) is asked by the
pre-cut filter, in the channel's mode.

ExampleScience's voyager-1 (`2026-10-17T0817Z`) lost 36 points to the frame
judge on seven blocks of one NASA lecture: charts and slides *inside* the 9:16
window (cached `text_regions` 13..25, which CF-0275's "panel outside the
window" clause lets through by design) and shots under 600 px on the short
side. What these tests hold in place:

  * a shot with 25 text regions and a 492 px short side leaves the pool before
    the cut in `fail`, with the root's own sentence in the refusal record, and
    `cached_verdict()` does not excuse it either;
  * in `warn` (every channel until the user signs `fail`) the same shot stays,
    and the storyboard's `shot_guard` record says what was found on it;
  * our own screen recording with 18 regions stays - exempt by kind, by its id
    or by the pool's `source_kind`;
  * an anchor whose only candidate the guard took out is the usual unresolved
    anchor (`plan_check` reads it as `absent`), not a new kind of hole;
  * a root without the module refuses nothing.

Stand-ins only: hand-made shots.json entries and settings blocks, a tmp root
for the channel file. No pool, no batch, no network.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

from _tmproot import tmp_root  # noqa: E402

import _score  # noqa: E402
import cache_fingerprint  # noqa: E402
import plan_check  # noqa: E402
import resolve_anchors as ra  # noqa: E402

TMP = tmp_root("ve-shot-guard-")
THRESHOLDS = (720, 0.65, ra.MAX_BLACK_CLIPS)


def cached(**over):
    """A shot that clears every other cached check: the text inside the window
    (nothing cut, nothing outside), lit, a subject found, freshly stamped."""
    base = {"short_side": 1080, "width": 1920, "height": 1080,
            "roi_source": "faces", "roi_coverage": 0.90,
            "black_fraction": 0.01, "mean_luma": 140.0,
            "text_regions": 0, "text_area": 0.0, "text_outside_crop": 0.0,
            "text_cut_by_crop": 0.0, "text_cut_area": 0.0,
            "measured_by": cache_fingerprint.usability_fingerprint()}
    base.update(over)
    return base


def shot(n, **over):
    extra = over.pop("extra", {})
    return {"index": n, "start": 0.0, "end": 12.0, "is_card": False,
            "crop_bottom_cached": 0.0, "usable_cached": cached(**over), **extra}


# voyager-1's slide: a plasma-wave chart inside the window, 492 px short side
SLIDE = dict(text_regions=25, text_area=0.18, text_outside_crop=0.10,
             short_side=492, width=874, height=492)
SLIDE_ID = "commons-64290655:7"


def cand_for(sid, s, score=0.31):
    vid, n = sid.rsplit(":", 1)
    return {"index": f"{vid}.shots.json", "shot": int(n), "source": f"/pool/{vid}.mp4",
            "start": s["start"], "end": s["end"], "score": score, "moment_at": None}


def test_the_slide_leaves_the_pool_in_fail_with_its_own_sentence():
    ra.configure_shot_guard(cfg={"mode": "fail"})
    s = shot(7, **SLIDE)
    why = ra.precut_cache_refusal(s, *THRESHOLDS, shot_id=SLIDE_ID)
    assert why and why.startswith("text_panel_in_window: 25 text regions"), why
    assert "under_resolution_floor: short side 492 px" in why, why
    # through the one screening every caller shares (CF-0140): the record
    # `rejected_candidates` and the coverage preflight carry
    _at, _o, _span, refusal = ra.precut_refusal(cand_for(SLIDE_ID, s), s, *THRESHOLDS)
    assert refusal is not None
    assert refusal["cause"] == ra.CAUSE_FOOTAGE_UNUSABLE
    assert refusal["record"]["reason"] == why, refusal
    assert refusal["record"]["score"] == 0.31
    # and nothing further down `cached_verdict()` excuses it
    assert ra.cached_verdict(s, s["usable_cached"], *THRESHOLDS, shot_id=SLIDE_ID) is True
    assert ra.probably_unusable(s, *THRESHOLDS, shot_id=SLIDE_ID) is True


def test_the_slide_stays_in_warn_and_the_storyboard_says_so():
    ra.configure_shot_guard(cfg={"mode": "warn"})
    s = shot(7, **SLIDE)
    assert ra.precut_cache_refusal(s, *THRESHOLDS, shot_id=SLIDE_ID) is None
    assert ra.precut_refusal(cand_for(SLIDE_ID, s), s, *THRESHOLDS)[3] is None
    rec = ra.shot_guard_record([{"shot": SLIDE_ID}, {"shot": "other:1"}], [])
    assert rec["mode"] == "warn" and rec["refused"] == 0, rec
    rules = sorted(f["rule"] for f in rec["findings"])
    assert rules == ["text_panel_in_window", "under_resolution_floor"], rec
    assert all(f["shot"] == SLIDE_ID and f["refuses"] is False for f in rec["findings"])


def test_a_clean_shot_and_a_shot_not_shown_are_not_recorded():
    ra.configure_shot_guard(cfg={"mode": "warn"})
    ra.precut_cache_refusal(shot(1), *THRESHOLDS, shot_id="clean:1")
    ra.precut_cache_refusal(shot(7, **SLIDE), *THRESHOLDS, shot_id=SLIDE_ID)
    # the slide was looked at but not put on screen
    rec = ra.shot_guard_record([{"shot": "clean:1"}], [])
    assert rec["findings"] == [], rec


def test_our_own_recording_keeps_its_interface_text():
    ra.configure_shot_guard(cfg={"mode": "fail"})
    by_id = shot(3, text_regions=18, text_area=0.30)
    assert ra.precut_cache_refusal(
        by_id, *THRESHOLDS, shot_id="own_capture-acme-demo-20261011t120000z:3") is None
    # the pool may say the kind only in the shot's own record
    by_kind = shot(3, text_regions=18, text_area=0.30,
                   extra={"source_kind": "own_capture"})
    assert ra.precut_cache_refusal(by_kind, *THRESHOLDS, shot_id="weird-id:3") is None
    # the same numbers on somebody else's footage leave the pool
    theirs = shot(3, text_regions=18, text_area=0.30)
    why = ra.precut_cache_refusal(theirs, *THRESHOLDS, shot_id="H6RXVb_J5J4:3")
    assert why and why.startswith("text_panel_in_window: 18"), why


def test_an_anchor_left_with_no_candidate_is_the_usual_hole():
    ra.configure_shot_guard(cfg={"mode": "fail"})
    s = shot(7, **SLIDE)
    refusal = ra.precut_refusal(cand_for(SLIDE_ID, s), s, *THRESHOLDS)[3]
    rejected = [{"phrase": "plasma waves", "shot": 7, **refusal["record"]}]
    verdict = ra.gate_verdict("plasma waves", [], rejected, 0, 1, 0.22)
    assert verdict["found_after_gate"] is False
    assert "text_panel_in_window" in verdict["reason"], verdict
    assert plan_check.classify_unresolved(verdict["reason"]) == "absent"
    supply = ra.candidate_supply("plasma waves", [cand_for(SLIDE_ID, s)], [],
                                 rejected, 0.22)
    assert supply["code"] == ra.POOL_OFFERED_REFUSED, supply
    rec = ra.shot_guard_record([], rejected)
    assert rec["refused"] == 1 and rec["mode"] == "fail", rec


def test_the_channel_mode_is_read_from_the_channel_file():
    root = TMP / "root"
    (root / "channels").mkdir(parents=True, exist_ok=True)
    (root / "channels" / "standin.json").write_text(json.dumps(
        {"video_editor": {"shot_guard": {"mode": "fail", "min_short_side": 480}}}))
    cfg = ra.configure_shot_guard("standin", root=root)
    assert cfg["mode"] == "fail" and cfg["min_short_side"] == 480, cfg
    # the floor is the channel's own number: 492 px clears 480
    why = ra.precut_cache_refusal(shot(7, **SLIDE), *THRESHOLDS, shot_id=SLIDE_ID)
    assert why and why.startswith("text_panel_in_window") \
        and "under_resolution_floor" not in why, why
    assert ra.shot_guard_record([], [])["channel"] == "standin"
    # a channel without the block runs on the module's defaults (`warn`)
    cfg = ra.configure_shot_guard("missing", root=root)
    assert cfg["mode"] == "warn", cfg
    # an unusable block is said and falls back to the defaults, never lost
    (root / "channels" / "broken.json").write_text(json.dumps(
        {"video_editor": {"shot_guard": {"mode": "loud"}}}))
    cfg = ra.configure_shot_guard("broken", root=root)
    assert cfg["mode"] == "warn" and ra.shot_guard_record([], [])["error"], cfg


def test_a_root_without_the_module_refuses_nothing():
    saved = (_score._GUARD, _score._GUARD_ERR)
    try:
        _score._GUARD, _score._GUARD_ERR = None, "shot guard not found: stand-in"
        assert ra.configure_shot_guard(cfg={"mode": "fail"}) is None
        assert ra.precut_cache_refusal(shot(7, **SLIDE), *THRESHOLDS,
                                       shot_id=SLIDE_ID) is None
        rec = ra.shot_guard_record([{"shot": SLIDE_ID}], [])
        assert rec["mode"] is None and "stand-in" in rec["error"], rec
    finally:
        _score._GUARD, _score._GUARD_ERR = saved
        ra.configure_shot_guard(cfg={"mode": "warn"})


def test_off_asks_nothing():
    ra.configure_shot_guard(cfg={"mode": "off"})
    assert ra.precut_cache_refusal(shot(7, **SLIDE), *THRESHOLDS, shot_id=SLIDE_ID) is None
    assert ra.shot_guard_record([{"shot": SLIDE_ID}], [])["findings"] == []


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
