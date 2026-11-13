#!/usr/bin/env python3
"""CF-0435: the pool's depth keeps a weak shot (low framing, brightness,
resolution, off topic) and counts it in `weak`, apart from `usable` - which is
CLEAN shots only and the one number the floor reads, so weak material never
stops the walk from fetching a better source. `available(depth)` =
usable + weak is the writer's "how much material is there". A black, empty or
burned-text shot is in neither. The Editor's own pre-cut gate still decides
the cut questions (moment mark, length) and the CF-0275 text veto.

Needs the Video Editor's checkout beside this repo (as test_pool_depth_floor
does); nothing is measured - the shots carry their `usable_cached` inline.
"""
import json
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import pool_depth as pd  # noqa: E402


def cache(**kw):
    c = {"short_side": 1080, "width": 1920, "height": 1080,
         "roi_source": "face", "roi_coverage": 0.9, "black_fraction": 0.05,
         "mean_luma": 110.0}
    c.update(kw)
    return c


def shot(i, **kw):
    s = {"index": i, "start": 3.0 * i, "end": 3.0 * i + 3.0,
         "description": "d", "burned_text": False, "on_topic": True,
         "usable_cached": cache()}
    s.update(kw)
    return s


def fresh_everything(editor):
    """Every cache reads as current: the stamps here are made up, and the
    freshness rule (CF-0048) is not what these tests are about."""
    real = getattr(editor, "_stale_cache", None)
    editor._stale_cache = lambda cached: False
    return real


def screen(shots):
    editor = pd.editor_module()
    assert editor is not None, pd.import_error()
    real = fresh_everything(editor)
    try:
        return pd.screen_shots(shots, detail=True)
    finally:
        editor._stale_cache = real


def test_weak_shots_are_counted_and_marked():
    shots = [shot(0),
             shot(1, usable_cached=cache(mean_luma=12.0)),       # dark
             shot(2, usable_cached=cache(roi_coverage=0.3)),     # framing
             shot(3, usable_cached=cache(width=640, height=360,
                                         short_side=360)),       # low-res
             shot(4, on_topic=False)]                            # off topic
    usable, seconds, cards, weak = screen(shots)
    # one clean shot, four weak ones: kept and counted, but not as clean
    assert (usable, weak) == (1, 4), (usable, weak)
    assert seconds > 0


def test_black_empty_and_burned_shots_are_not_counted():
    shots = [shot(0),
             shot(1, usable_cached=cache(black_fraction=0.97, mean_luma=2.0)),
             shot(2, usable_cached=cache(roi_source="none", roi_coverage=0.0)),
             shot(3, burned_text=True)]
    usable, _seconds, _cards, weak = screen(shots)
    assert (usable, weak) == (1, 0), (usable, weak)


def test_the_cut_questions_still_refuse():
    # 0.3 s of shot is too short to cut, whatever its usability says.
    shots = [shot(0), {**shot(1), "end": 3.3}]
    usable, _s, _c, _w = screen(shots)
    assert usable == 1


def test_a_stale_cache_is_read_as_no_measurement():
    editor = pd.editor_module()
    assert editor is not None, pd.import_error()
    real = getattr(editor, "_stale_cache", None)
    editor._stale_cache = lambda cached: True
    try:
        usable, _s, _c, weak = pd.screen_shots(
            [shot(0, usable_cached=cache(black_fraction=0.99, mean_luma=1.0))],
            detail=True)
    finally:
        editor._stale_cache = real
    # the black frame is not believed, exactly as precut_refusal ignores a
    # stale cache: kept, and not weak either (nothing measured to be weak on)
    assert (usable, weak) == (1, 0)


def test_the_report_carries_weak_shots_per_topic_and_source():
    editor = pd.editor_module()
    assert editor is not None, pd.import_error()
    real = fresh_everything(editor)
    try:
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "v1.shots.json").write_text(json.dumps({
                "source": "v1.mp4",
                "shots": [shot(0), shot(1, on_topic=False),
                          shot(2, burned_text=True)]}))
            pd.forget()
            depth = pd.topic_depth("t", ["v1"], cache=d)
    finally:
        editor._stale_cache = real
    assert depth.measured, depth.error
    assert (depth.usable, depth.weak) == (1, 1), depth
    assert pd.available(depth) == 2
    rec = pd.depth_record(depth)
    assert rec["usable_shots"] == 1 and rec["weak_shots"] == 1, rec
    assert rec["available_shots"] == 2, rec
    assert rec["per_source"][0]["weak_shots"] == 1
    assert rec["per_source"][0]["available_shots"] == 2
    assert "weak" in pd.depth_line(depth)
    assert "weak_shots" in pd.pool_depth_report([rec])["measure"]


def test_weak_shots_never_make_a_pool_deep_enough():
    """The review fix: a pool deep only in weak shots still goes for its next
    candidate - the floor reads clean shots, weak ones are only reported."""
    s = pd.SourceDepth("v", 100, 10, 30.0, 0, None, 90)
    t = pd.TopicDepth("t", 2, 100, 10, 30.0, True, None, [s], 90)
    assert pd.available(t) == 100 and not pd.deep_enough(t)
    rec = pd.depth_record(t)
    assert (rec["usable_shots"], rec["weak_shots"], rec["available_shots"],
            rec["deep_enough"]) == (10, 90, 100, False), rec
    assert "+90 weak, 100 available" in pd.depth_line(t)


def test_the_skill_names_the_three_numbers_and_their_readers():
    """SKILL.md and this file say the same thing: `usable_shots` is clean and
    the floor's, `weak_shots` apart, `available_shots` the sum."""
    skill = (SCRIPTS.parent / ".claude" / "skills" / "footage-indexer"
             / "SKILL.md").read_text()
    for field in ("`usable_shots`** - CLEAN shots", "`weak_shots`**",
                  "`available_shots`** = `usable_shots + weak_shots`"):
        assert field in skill, field
    assert "never `usable_shots`" in skill
    rec = pd.depth_record(pd.TopicDepth("t", 1, 3, 1, 3.0, True, None, [], 1))
    assert {"usable_shots", "weak_shots", "available_shots"} <= set(rec)


def test_old_positional_depth_records_still_build():
    # Callers and tests build these positionally; `weak` defaults to 0.
    s = pd.SourceDepth("v", 10, 5, 9.0, 0, None)
    t = pd.TopicDepth("t", 1, 10, 5, 9.0, True, None, [s])
    assert s.weak == 0 and t.weak == 0
    assert pd.depth_record(t)["weak_shots"] == 0


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
