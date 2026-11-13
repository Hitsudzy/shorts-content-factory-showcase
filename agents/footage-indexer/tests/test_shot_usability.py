#!/usr/bin/env python3
"""CF-0435: a weak shot stays in the pool with a score and its soft
violations; only a black, empty or burned-text shot is taken out.

Pure checks over `shot_usability.assess()` plus one over the one writer
(`shot_schema.write_index`) and one that holds the copied floors equal to the
Video Editor's own constants. No Vision, no ffmpeg, nothing re-measured.
"""
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import shot_schema  # noqa: E402
import shot_usability as su  # noqa: E402

PRICES = {su.LOW_FRAMING: 3, su.LOW_BRIGHTNESS: 3, su.LOW_RESOLUTION: 2,
          su.OFF_TOPIC_SHOT: 4}


def cached(**kw):
    base = {"measured_by": "abc", "short_side": 1080, "width": 1920,
            "height": 1080, "roi_source": "face", "roi_coverage": 0.9,
            "black_fraction": 0.05, "mean_luma": 110.0}
    base.update(kw)
    return base


def shot(**kw):
    s = {"index": 0, "start": 0.0, "end": 3.0, "description": "x",
         "burned_text": False, "on_topic": True,
         "usable_cached": cached()}
    s.update(kw)
    return s


def rules(u, key):
    return [v["rule"] for v in u[key]]


def test_a_clean_shot_scores_one_and_carries_nothing():
    u = su.assess(shot(), price_table=PRICES)
    assert u["score"] == 1.0 and u["penalty"] == 0, u
    assert u["soft"] == [] and u["hard"] == [] and u["measured"] is True
    assert u["task"] == "CF-0435" and u["measured_by"] == "abc"


def test_low_brightness_framing_resolution_are_soft_and_priced():
    s = shot(usable_cached=cached(mean_luma=12.0, roi_coverage=0.4,
                                  width=640, height=360, short_side=360))
    u = su.assess(s, price_table=PRICES)
    assert u["hard"] == [], u
    assert rules(u, "soft") == [su.LOW_FRAMING, su.LOW_BRIGHTNESS,
                                su.LOW_RESOLUTION], u
    assert u["penalty"] == 8 and u["score"] == 0.92, u
    framing = u["soft"][0]
    assert framing == {"rule": "low_framing", "value": 0.4, "floor": 0.65,
                       "price_key": "score.low_framing", "price": 3}, framing
    assert not su.is_hard(s) and su.is_weak(s)


def test_off_topic_is_a_penalty_not_an_exclusion():
    u = su.assess(shot(on_topic=False), price_table=PRICES)
    assert u["hard"] == [] and rules(u, "soft") == [su.OFF_TOPIC_SHOT], u
    assert u["soft"][0]["price_key"] == "score.off_topic_shot"
    assert u["score"] == 0.96


def test_a_supplement_shot_showing_its_entity_is_not_off_topic():
    u = su.assess(shot(on_topic=False, shows_entity=True), price_table=PRICES)
    assert u["soft"] == [], u


def test_a_black_frame_is_hard():
    u = su.assess(shot(usable_cached=cached(black_fraction=0.97,
                                            mean_luma=3.0)),
                  price_table=PRICES)
    assert rules(u, "hard") == [su.BLACK_FRAME] and u["score"] == 0.0, u
    assert u["hard"][0]["ceiling"] == su.MAX_BLACK


def test_a_letterbox_dark_shot_under_the_clip_ceiling_stays():
    # 0.5 near-black is over qc_asset's 0.35 for a still and under the
    # Editor's 0.90 for a clip: a fade, a night scene - weak, not gone.
    u = su.assess(shot(usable_cached=cached(black_fraction=0.5,
                                            mean_luma=20.0)),
                  price_table=PRICES)
    assert u["hard"] == [] and rules(u, "soft") == [su.LOW_BRIGHTNESS], u


def test_an_empty_frame_is_hard():
    u = su.assess(shot(usable_cached=cached(roi_source="none",
                                            roi_coverage=0.0)),
                  price_table=PRICES)
    assert rules(u, "hard") == [su.EMPTY_FRAME], u
    assert su.LOW_FRAMING not in rules(u, "soft")


def test_a_lit_card_is_excused_the_darkness_rules():
    s = shot(is_card=True, usable_cached=cached(
        black_fraction=0.95, mean_luma=9.0, card_ink_fraction=0.08))
    u = su.assess(s, price_table=PRICES)
    assert u["hard"] == [] and u["soft"] == [], u


def test_burned_text_stays_out_shot_by_shot():
    u = su.assess(shot(burned_text=True), price_table=PRICES)
    assert rules(u, "hard") == [su.BURNED_TEXT], u
    assert u["hard"][0]["price_key"] == "score.hard.foreign_text"


def test_no_cache_is_judged_on_flags_and_never_remeasured():
    s = shot(on_topic=False)
    del s["usable_cached"]
    u = su.assess(s, price_table=PRICES)
    assert u["measured"] is False and rules(u, "soft") == [su.OFF_TOPIC_SHOT]
    # a caller that distrusts a stale cache asks for the flags alone
    s2 = shot(usable_cached=cached(mean_luma=5.0, black_fraction=0.99))
    u2 = su.assess(s2, measurements=False, price_table=PRICES)
    assert u2["measured"] is False and u2["hard"] == [] and u2["soft"] == []


def test_prices_come_from_the_table_and_fall_back_to_the_draft():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "gate-prices.json"
        p.write_text(json.dumps({"rules": {
            "score.low_framing": {"penalty": {"price": 7}}}}))
        got = su.prices(p, refresh=True)
        assert got[su.LOW_FRAMING] == 7 and got[su.LOW_RESOLUTION] == 2, got
        missing = su.prices(Path(d) / "nope.json", refresh=True)
        assert missing == su.DEFAULT_PRICES


def test_the_live_price_table_names_every_soft_rule():
    if not su.PRICES_FILE.exists():
        print("  (skip: no shared/gate-prices.json beside this checkout)")
        return
    rules_ = json.loads(su.PRICES_FILE.read_text())["rules"]
    for r in su.SOFT_RULES:
        assert su.price_key(r) in rules_, r
    for key in su.HARD_PRICE_KEYS.values():
        assert key in rules_, key


def test_write_index_stamps_every_shot():
    idx = {"source": "v.mp4", "shots": [
        shot(index=0), shot(index=1, on_topic=False),
        shot(index=2, usable_cached=cached(black_fraction=0.99))]}
    with tempfile.TemporaryDirectory() as d:
        dest = Path(d) / "v.shots.json"
        shot_schema.write_index(dest, idx)
        back = json.loads(dest.read_text())["shots"]
    assert [s["usability"]["hard"] != [] for s in back] == [False, False, True]
    assert back[1]["usability"]["soft"][0]["rule"] == "off_topic_shot"
    assert back[0]["usability"]["score"] == 1.0


def test_summary_counts_clean_weak_hard():
    out = su.summary([shot(), shot(on_topic=False), shot(burned_text=True)])
    assert (out["clean"], out["weak"], out["hard"]) == (1, 1, 1), out
    assert out["by_rule"] == {"off_topic_shot": 1, "burned_text": 1}, out


def test_the_floors_are_the_video_editors_own():
    import pool_depth
    editor = pool_depth.editor_module()
    if editor is None:
        print(f"  (skip: video-editor not importable: {pool_depth.import_error()})")
        return
    assert editor.MIN_COVERAGE == su.MIN_COVERAGE
    assert editor.MIN_SHORT_SIDE == su.MIN_SHORT_SIDE
    assert editor.MAX_BLACK_CLIPS == su.MAX_BLACK
    qc = sys.modules.get("qc_asset")
    if qc is not None:
        assert qc.MIN_MEAN_LUMA == su.MIN_MEAN_LUMA
        assert qc.MIN_CARD_INK_FRACTION == su.MIN_CARD_INK_FRACTION
    else:
        text = (pool_depth.VIDEO_EDITOR_SCRIPTS / "qc_asset.py").read_text()
        assert f"MIN_MEAN_LUMA = {su.MIN_MEAN_LUMA}\n" in text
        assert f"MIN_CARD_INK_FRACTION = {su.MIN_CARD_INK_FRACTION}\n" in text


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
