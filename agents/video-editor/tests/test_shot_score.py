#!/usr/bin/env python3
"""CF-0435: a weak shot is ranked and priced, not refused (scripts/shot_score.py).

Pinned here, without ffmpeg or Vision:
  * the Editor's side agrees with the Footage Indexer's `shot_usability.py`
    (rule names, soft/hard split, the floors it copies from this repo);
  * a qc_asset.py verdict failing only on framing / brightness / resolution
    is soft, anything with a subject / black / crop-framing / tool failure is
    hard and keeps every line;
  * ranking puts clean before weak, keeps the matcher's order among equals,
    puts hard last; `on_topic: false` ranks lower but stays;
  * the plan pays one finding per soft rule per distinct shot on screen, with
    the price table's keys, and the price table carries every key.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
from _tmproot import tmp_root  # noqa: E402 - CF-0489: temp trees removed at exit
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPTS = HERE.parent / "scripts"
os.environ.setdefault("RUNLOG_BATCH", str(tmp_root("cf0435-runlog-")))
sys.path.insert(0, str(SCRIPTS))

import _score  # noqa: E402
import shot_score  # noqa: E402
from common import MIN_COVERAGE, MIN_SHORT_SIDE  # noqa: E402
from qc_asset import MIN_MEAN_LUMA  # noqa: E402


def _cached(**kw):
    base = {"roi_source": "face", "roi_coverage": 0.9, "black_fraction": 0.05,
            "mean_luma": 90, "short_side": 1080, "width": 1920, "height": 1080,
            "measured_by": "x"}
    base.update(kw)
    return base


def shot(n, **kw):
    s = {"index": n, "on_topic": True, "burned_text": False}
    cached = kw.pop("cached", None)
    s["usable_cached"] = _cached(**(cached or {}))
    s.update(kw)
    return s


def need_indexer():
    if shot_score.indexer() is None:
        print(f"SKIP: no {shot_score.SHOT_USABILITY}")
        return False
    return True


def test_the_indexer_module_loads_when_its_file_is_there():
    """CF-0451 regression: `shot_usability.py` grew `import screen_recording`
    / `import sharpness`, the by-path load raised ModuleNotFoundError and
    `indexer()` read it as "no indexer" - every other test here then SKIPped
    and the resolver stopped refusing cached black/empty frames, silently.
    A file that is there must load; its indexer siblings must not stay in
    this process's sys.modules afterwards (they would shadow later imports)."""
    if not shot_score.SHOT_USABILITY.exists():
        print(f"SKIP: no {shot_score.SHOT_USABILITY}")
        return
    before = set(sys.modules)
    shot_score._MEMO.pop("mod", None)
    mod = shot_score.indexer()
    assert mod is not None, f"{shot_score.SHOT_USABILITY} exists but did not load"
    assert callable(getattr(mod, "of", None))
    for dep in shot_score._indexer_siblings(shot_score.SHOT_USABILITY):
        assert dep not in sys.modules or dep in before, (
            f"indexer module {dep!r} leaked into sys.modules")


def test_the_indexer_module_agrees_with_this_repo():
    if not need_indexer():
        return
    mod = shot_score.indexer()
    assert tuple(mod.SOFT_RULES) == shot_score.SOFT_RULES, mod.SOFT_RULES
    assert mod.MIN_COVERAGE == MIN_COVERAGE
    assert mod.MIN_SHORT_SIDE == MIN_SHORT_SIDE
    assert mod.MIN_MEAN_LUMA == MIN_MEAN_LUMA
    import resolve_anchors as ra
    assert mod.MAX_BLACK == ra.MAX_BLACK_CLIPS


def test_every_soft_rule_is_priced_in_the_table():
    table = json.loads((_score.factory_root() / "shared" / "gate-prices.json")
                       .read_text())["rules"]
    for rule in shot_score.SOFT_RULES:
        row = table.get(shot_score.price_key(rule))
        assert row and row["mode"] == "penalty" and row["penalty"]["cap"], rule


def test_a_verdict_failing_only_soft_checks_is_shown_and_priced():
    qc = {"usable": False, "failed": ["coverage", "luma"],
          "failures": ["framing: ...", "too dark: ..."]}
    assert shot_score.split_verdict(qc) == ([], ["low_framing", "low_brightness"])
    assert shot_score.split_verdict({"usable": False, "failed": ["resolution"],
                                     "failures": ["resolution: ..."]}) \
        == ([], ["low_resolution"])
    assert shot_score.split_verdict({"usable": True}) == ([], [])


def test_a_verdict_with_any_hard_check_is_refused_whole():
    for hard in ("subject", "black", "crop_framing", "tool_timeout"):
        qc = {"usable": False, "failed": ["coverage", hard],
              "failures": ["framing: a", f"{hard}: b"]}
        assert shot_score.split_verdict(qc) == (["framing: a", f"{hard}: b"], []), hard
    # a failed verdict that names no key is not a soft one
    assert shot_score.split_verdict({"usable": False, "failures": ["x"]}) == (["x"], [])


def test_clean_before_weak_matcher_order_among_equals_hard_last():
    if not need_indexer():
        return
    lut = {
        1: shot(1, cached={"roi_coverage": 0.40}),          # weak: framing
        2: shot(2),                                          # clean
        3: shot(3, cached={"black_fraction": 0.97}),         # hard: black
        4: shot(4),                                          # clean
        5: shot(5, on_topic=False),                          # weak: off topic
    }
    pool = [{"shot": n} for n in (1, 2, 3, 4, 5)]
    ranked = [c["shot"] for c in shot_score.rank(pool, lambda c: lut[c["shot"]])]
    assert ranked == [2, 4, 1, 5, 3], ranked   # framing 3 pts < off topic 4 pts


def test_a_stale_cache_ranks_on_the_flags_alone():
    if not need_indexer():
        return
    lut = {1: shot(1, cached={"roi_coverage": 0.40}), 2: shot(2, on_topic=False)}
    pool = [{"shot": 1}, {"shot": 2}]
    ranked = shot_score.rank(pool, lambda c: lut[c["shot"]], fresh_of=lambda s: False)
    assert [c["shot"] for c in ranked] == [1, 2]
    assert shot_score.cached_hard(shot(3, cached={"roi_source": "none"}), fresh=False) == []
    assert [v["rule"] for v in shot_score.cached_hard(
        shot(3, cached={"roi_source": "none"}))] == ["empty_frame"]


def test_the_record_is_measured_soft_plus_the_flags():
    if not need_indexer():
        return
    assert shot_score.record(shot(1)) is None
    rec = shot_score.record(shot(1, on_topic=False), ["low_framing"])
    assert rec["soft"] == ["low_framing", "off_topic_shot"], rec
    assert rec["penalty"] == 7 and rec["score"] == 0.93, rec
    # an entity shot of a supplement is not off the topic (CF-0344)
    assert shot_score.record(shot(1, on_topic=False, shows_entity=True)) is None
    # the cache's own low framing is not charged: only the clip's measurement
    assert shot_score.record(shot(1, cached={"roi_coverage": 0.3})) is None


def test_the_plan_pays_once_per_weak_shot_on_screen():
    weak = {"task": "CF-0435", "soft": ["low_framing"]}
    blocks = [
        {"shot": "a:1", "usability": weak, "_start": 0.5},
        {"shot": "b:2", "_start": 5.5},
        {"shot": "c:3", "asset_kind": "sequence", "_start": 6.0,
         "cuts": [{"shot": "c:3", "usability": {"soft": ["off_topic_shot"]}},
                  {"shot": "d:4", "usability": {"soft": ["low_brightness"]}},
                  {"shot": "d:4", "held_frame": True,
                   "usability": {"soft": ["low_brightness"]}}]},
        {"shot": "a:1", "usability": weak, "_start": 9.0},   # shown again
        {"split": [{"shot": "e:5", "cuts": [
            {"shot": "e:5", "usability": {"soft": ["low_resolution"]}}]}],
         "_start": 12.0},
    ]
    found = shot_score.plan_findings(blocks, extra={(1, "b:2"): {"low_brightness"}})
    got = [(f["rule"], f["where"]["block"], f["where"]["shot"]) for f in found]
    assert got == [("score.low_framing", 0, "a:1"),
                   ("score.low_brightness", 1, "b:2"),
                   ("score.off_topic_shot", 2, "c:3"),
                   ("score.low_brightness", 2, "d:4"),
                   ("score.low_resolution", 4, "e:5")], got
    assert found[0]["hook"] is True and found[1]["hook"] is False


def test_the_price_of_weak_shots_is_capped_by_the_table():
    if _score.module() is None:
        print(f"SKIP: {_score.error()}")
        return
    found = shot_score.plan_findings(
        [{"shot": f"s:{i}", "usability": {"soft": ["low_framing"]}, "_start": 10.0 + i}
         for i in range(8)])
    block = _score.score_block(found)
    agg = block["by_rule"]["score.low_framing"]
    assert agg["raw"] == -24 and agg["charged"] == -12, agg


# --- build_render_plan's asset gate and the QC stage ----------------------------

def test_the_plans_asset_gate_prices_a_weak_picture_and_refuses_a_hard_one():
    import build_render_plan as brp
    rejected, weak, notes = [], {}, []
    brp.asset_gate(rejected, weak, notes, 2, "a.mp4",
                   {"usable": False, "failed": ["luma"], "failures": ["too dark"]},
                   "v:3", " (cut 1)")
    assert rejected == [] and weak == {(2, "v:3"): {"low_brightness"}}, (rejected, weak)
    assert notes and "weak picture" in notes[0] and "(cut 1)" in notes[0], notes
    brp.asset_gate(rejected, weak, notes, 4, "b.mp4",
                   {"usable": False, "failed": ["luma", "black"],
                    "failures": ["too dark", "dead pixels"]}, "v:4")
    assert rejected == [(4, "b.mp4", ["too dark", "dead pixels"])], rejected
    assert (4, "v:4") not in weak
    # and the plan stage prices what the gate kept
    got = shot_score.plan_findings([{"shot": "x:1"}, {"shot": "x:2"},
                                    {"shot": "v:3", "_start": 9.0}], extra=weak)
    assert [(f["rule"], f["where"]["block"]) for f in got] \
        == [("score.low_brightness", 2)], got


def test_off_topic_is_not_charged_twice_on_plan_and_qc():
    import score_log
    plan_finding = shot_score.plan_findings(
        [{"shot": "sup:4", "usability": {"soft": ["off_topic_shot"]}, "_start": 7.0}])
    plan = {"blocks": [{"start": 7.0}, {"start": 9.0}],
            "score": {"findings": plan_finding}}
    same = {"failures": ["supplement shot without the entity: block 0 (sup:4) - x"],
            "measured": {}}
    assert [f for f in score_log.qc_findings(same, plan)
            if f["rule"] == score_log.RULE_OFF_TOPIC] == []
    # a different shot on another block is still QC's to charge
    other = {"failures": ["supplement shot without the entity: block 1 (sup:9) - x"],
             "measured": {}}
    got = [f for f in score_log.qc_findings(other, plan)
           if f["rule"] == score_log.RULE_OFF_TOPIC]
    assert len(got) == 1 and got[0]["where"]["block"] == 1, got
    # and with no plan-stage price QC charges as before
    assert len([f for f in score_log.qc_findings(same, {"blocks": plan["blocks"]})
                if f["rule"] == score_log.RULE_OFF_TOPIC]) == 1


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
