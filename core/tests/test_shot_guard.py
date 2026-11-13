#!/usr/bin/env python3
"""CF-0791: the shot pool checked before the render (shared/score/shot_guard.py).

ExampleScience's voyager-1 (2026-10-17T0817Z) was cut by the frame judge for
foreign text on 7 blocks - slides of one NASA lecture whose cached
`text_regions` were 13-25, inside the 9:16 window where the Editor's pre-cut
text rule (CF-0275) does not look - and its worst shots were 492-590 px on the
short side. These checks hold the rule on stand-ins shaped like those shots
and like the accepted ones that sit nearest the lines (an own recording with
18 regions, a trailer frame with 12, a letterboxed 608 px shot). Nothing here
reads the real pool or a real batch.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared" / "score"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import shot_guard as G   # noqa: E402
from _tmproot import tmp_root   # noqa: E402

TMP = tmp_root("shot-guard-test-")


def shot(index, regions=0, short=1080, motion=2.0, area=None, outside=None):
    cached = {"short_side": short, "text_regions": regions}
    if area is not None:
        cached["text_area"] = area
    if outside is not None:
        cached["text_outside_crop"] = outside
    return {"index": index, "start": index * 2.0, "end": index * 2.0 + 2.0,
            "usable_cached": cached, "sharpness_cached": {"motion": motion}}


def pool_with(name, videos):
    d = TMP / name
    d.mkdir(parents=True, exist_ok=True)
    for vid, shots in videos.items():
        (d / f"{vid}.shots.json").write_text(json.dumps({"shots": shots}))
    return G.Pool(d)


def fail_cfg(**over):
    return G.config({"mode": "fail", **over})


# --- the per-shot rule ---------------------------------------------------

def test_a_chart_inside_the_window_is_taken_out_in_fail():
    chart = shot(44, regions=25, short=720, area=0.0299, outside=0.4352)
    reason = G.shot_refusal(chart, fail_cfg(), "commons-64290655:44")
    assert reason and reason.startswith(G.TEXT_PANEL), reason


def test_the_line_sits_at_thirteen_regions():
    assert G.shot_refusal(shot(1, regions=13), fail_cfg(), "v:1")
    # the accepted trailer frame nearest the line (rink-rivals, 12)
    assert G.shot_refusal(shot(1, regions=12), fail_cfg(), "v:1") is None


def test_our_own_recording_is_exempt_by_kind():
    capture = shot(0, regions=18, area=0.2099, motion=0.0)
    sid = "own_capture-ysharma-chatgpt4-20261016t084415z:0"
    assert G.shot_findings(capture, fail_cfg(), sid) == []


def test_the_resolution_floor_spares_the_lowest_accepted_shot():
    assert G.shot_refusal(shot(1, short=608), fail_cfg(), "v:1") is None
    reason = G.shot_refusal(shot(1, short=492), fail_cfg(), "v:1")
    assert reason and reason.startswith(G.UNDER_FLOOR), reason


def test_warn_records_and_refuses_nothing_and_off_records_nothing():
    chart = shot(1, regions=25, short=492)
    warn = G.shot_findings(chart, G.config(), "v:1")
    assert {f["rule"] for f in warn} == {G.TEXT_PANEL, G.UNDER_FLOOR}
    assert not any(f["refuses"] for f in warn)
    assert G.shot_refusal(chart, G.config(), "v:1") is None
    assert G.shot_findings(chart, G.config({"mode": "off"}), "v:1") == []


def test_a_shot_with_no_cached_measurement_says_nothing():
    assert G.shot_findings({"index": 3}, fail_cfg(), "v:3") == []


def test_the_channel_overrides_the_line():
    cfg = fail_cfg(text_panel_regions_min=30, min_short_side=480)
    assert G.shot_refusal(shot(1, regions=25, short=492), cfg, "v:1") is None


# --- the configuration -----------------------------------------------------

def test_a_bad_block_is_refused_with_its_reason():
    errs = G.validate_config({"mode": "enforce", "min_short_side": 0,
                              "hook_min_motion": -1, "regions": 3})
    joined = " | ".join(errs)
    for word in ("mode", "min_short_side", "hook_min_motion", "'regions'"):
        assert word in joined, joined
    try:
        G.config({"mode": "enforce"})
    except G.ShotGuardError:
        pass
    else:
        raise AssertionError("an illegal mode was taken")


def test_prose_is_admitted():
    assert G.validate_config({"note": "x", "mode_note": "y", "mode": "warn"}) == []


def test_the_channel_file_is_read_and_a_missing_block_is_the_defaults():
    root = TMP / "root-cfg"
    (root / "channels").mkdir(parents=True, exist_ok=True)
    (root / "channels" / "sci.json").write_text(json.dumps(
        {"video_editor": {"shot_guard": {"mode": "fail", "min_short_side": 640}}}))
    (root / "channels" / "reel.json").write_text(json.dumps({"video_editor": {}}))
    sci = G.channel_config("sci", root)
    assert sci["mode"] == "fail" and sci["min_short_side"] == 640
    assert sci["text_panel_regions_min"] == G.DEFAULTS["text_panel_regions_min"]
    assert G.channel_config("reel", root) == G.DEFAULTS
    assert G.channel_config("nobody", root) == G.DEFAULTS


# --- the plan --------------------------------------------------------------

def voyager_like():
    """A plan shaped like voyager-1's: a slide hook, a sequence with a low
    chart, a split, and a chart block; length_supply lists a candidate the
    planner did not show (it must not be read as shown)."""
    return {"blocks": [
        {"start": 0.0, "end": 1.5, "shot": "lec:19",
         "asset": {"kind": "clip", "shot": "lec:19"}},
        {"start": 1.5, "end": 3.7, "shot": "lec:32",
         "asset": {"kind": "clip", "shot": "lec:32"},
         "length_supply": {"long_enough": [{"shot": "lec:44"}]}},
        {"start": 7.45, "end": 9.69, "asset": {"kind": "sequence", "cuts": [
            {"kind": "clip", "shot": "rec:6"}, {"kind": "clip", "shot": "lec:29"}]}},
        {"start": 25.6, "end": 27.2, "shot": "lec:44",
         "asset": {"kind": "clip", "shot": "lec:44"}},
        {"start": 30.0, "end": 32.0, "asset": {"kind": "split", "sides": [
            {"side": "a", "kind": "clip", "shot": "rec:7"},
            {"side": "b", "kind": "clip", "shot": "gone:1"}]}},
        {"start": 32.0, "end": 34.0, "asset": {"kind": "card"}},
    ]}


def voyager_pool(name):
    return pool_with(name, {
        "lec": [shot(19, motion=0.0), shot(32, motion=0.0),
                shot(29, regions=13, short=590, motion=0.0, area=0.0823),
                shot(44, regions=25, short=720, motion=0.0)],
        "rec": [shot(6, short=714, motion=7.94), shot(7, short=714, motion=1.04)],
    })


def test_plan_shots_reads_what_the_block_shows_and_not_its_candidates():
    plan = voyager_like()
    assert G.plan_shots(plan["blocks"][1]) == ["lec:32"]
    assert G.plan_shots(plan["blocks"][2]) == ["rec:6", "lec:29"]
    assert G.plan_shots(plan["blocks"][4]) == ["rec:7", "gone:1"]
    assert G.plan_shots(plan["blocks"][5]) == []


def test_the_audit_finds_the_charts_the_floor_and_the_slide_hook():
    res = G.audit_plan(voyager_like(), voyager_pool("audit"), fail_cfg())
    by = {}
    for f in res["findings"]:
        by.setdefault(f["rule"], set()).add(f["block"])
    assert by[G.TEXT_PANEL] == {2, 3}, by
    assert by[G.UNDER_FLOOR] == {2}, by
    assert by[G.STATIC_HOOK] == {0, 1}, by
    assert res["refuses"] is True
    assert not any(f["refuses"] for f in res["findings"] if f["rule"] == G.STATIC_HOOK)
    assert res["unmeasured"] == ["gone:1"] and res["shots"] == 7


def test_a_moving_shot_in_the_hook_block_clears_it():
    plan = {"blocks": [{"start": 0.0, "end": 2.0, "asset": {"kind": "split", "sides": [
        {"kind": "clip", "shot": "lec:19"}, {"kind": "clip", "shot": "rec:6"}]}}]}
    res = G.audit_plan(plan, voyager_pool("hook"), fail_cfg())
    assert res["findings"] == [], res


def test_a_still_after_the_hook_is_not_a_static_hook():
    plan = {"blocks": [{"start": 6.0, "end": 8.0, "asset": {"kind": "clip", "shot": "lec:19"}}]}
    assert G.audit_plan(plan, voyager_pool("late"), fail_cfg())["findings"] == []


def test_in_warn_the_audit_refuses_nothing():
    res = G.audit_plan(voyager_like(), voyager_pool("warn"), G.config())
    assert res["findings"] and res["refuses"] is False


# --- the offline measurement ------------------------------------------------

def batch(name, plans, judge=None, refusals=None, boards=None):
    bd = TMP / "pipeline" / "sci" / name
    for slug, plan in plans.items():
        (bd / "work" / slug).mkdir(parents=True, exist_ok=True)
        (bd / "work" / slug / "plan.json").write_text(json.dumps(plan))
        sid = (boards or {}).get(slug)
        if sid:
            (bd / "work" / slug / "storyboard.json").write_text(json.dumps({"script_id": sid}))
    if judge is not None:
        (bd / "06-frame-judge.json").write_text(json.dumps({"videos": judge}))
    (bd / "05-video-editor.json").write_text(json.dumps(
        {"videos": [], "refusals": refusals or []}))
    return bd


def test_measure_sets_the_guard_beside_what_happened():
    clean = {"blocks": [{"start": 0.0, "end": 3.0, "asset": {"kind": "clip", "shot": "rec:6"}}]}
    bd = batch("b1", {"voyager": voyager_like(), "artemis": clean, "lost": clean},
               judge=[{"slug": "voyager", "gate": "reject", "reason_code": "score_below_threshold",
                       "score": {"score": 29, "log": [
                           {"rule": "score.judge_foreign", "where": {"block": "block-3"}},
                           {"rule": "score.judge_foreign", "where": {"block": "block-4"}},
                           {"rule": "score.low_resolution", "where": {"block": 2}}]}},
                      {"slug": "artemis", "gate": "pass", "score": {"score": 66, "log": []}}],
               refusals=[{"script_id": "s-lost", "reason_code": "score_below_threshold",
                          "numbers": {"score": 24}}],
               boards={"lost": "s-lost"})
    rows = {r["slug"]: r for r in G.measure([bd], voyager_pool("measure"),
                                            cfg_for=lambda ch: G.config())}
    v = rows["voyager"]
    assert v["outcome"] == "reject" and v["score"] == 29
    assert v["refuses"] is True, "measure judges every channel as if it were in fail"
    assert v["text_panel_blocks"] == [2, 3] and v["judge_foreign_blocks"] == [3, 4]
    assert v["text_panel_caught"] == [3]
    assert v["taken_out"] == 2      # lec:29 (chart + floor) and lec:44
    assert rows["artemis"]["outcome"] == "pass" and rows["artemis"]["refuses"] is False
    assert rows["lost"]["outcome"] == "refused" and rows["lost"]["score"] == 24


def test_the_cli_prints_one_line_per_plan_and_the_tally():
    import contextlib
    import io
    bd = batch("b2", {"voyager": voyager_like()}, judge=[])
    pool_dir = voyager_pool("cli").dir
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = G.main(["measure", str(bd), "--pool", str(pool_dir), "--root", str(TMP / "nowhere")])
    out = buf.getvalue()
    assert code == 0
    assert "sci/b2 voyager: not judged - would take out 2 shot(s)" in out, out
    assert "the guard would change the cut of 1; of them accepted by the judge: 0" in out, out
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = G.main(["shot", str(pool_dir / "lec.shots.json"), "44", "--root", str(TMP / "nowhere")])
    got = json.loads(buf.getvalue())
    assert code == 0 and got["shot"] == "lec:44" and got["mode"] == "warn"
    assert got["refusal"] is None and got["findings"][0]["rule"] == G.TEXT_PANEL


if __name__ == "__main__":
    tests = [(k, v) for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            print(f"FAIL {name}: {e.__class__.__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
