#!/usr/bin/env python3
"""CF-0545: a block that retells the event takes the event's own footage.

The case: `weekend-night-live` of `pipeline/example-film/2026-10-05T0701Z` -
under the words about Taylor Sterling walking into Dana Reyes's WNL
monologue stood `d7b1ilF5290`, Dana Reyes on the couch of *Late Night
with Sam Meadows*. Everything below is frozen out of that batch (the
hunter's candidates, the registry's uploader, the scene, the spoken words of
each anchor) - no read of the live tree.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import sys
import tempfile
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import event_footage as ef  # noqa: E402

TOPIC = "lf-2026-10-05-003"
SCENE = "lf-2026-10-05-003-s1"
WNL_REF = {"name": "Weekend Night Live", "kind": "person", "type": "tv_series",
           "network": None, "parent_work": None, "person": "Dana Reyes",
           "rights_holder": None}
SPEC = {"topic_id": TOPIC, "scene_id": SCENE, "title_ref": WNL_REF}
HUNTER = {"topics": [{
    "topic_id": TOPIC, "title_ref": WNL_REF,
    "scenes": [{"scene_id": SCENE, "description": (
        "Taylor Sterling surprised Dana Reyes by joining her opening monologue "
        "on 'Weekend Night Live' — payback for Reyes's cameo in Swift's "
        "'Patient Zero' music video, and maybe a birthday gift too, since "
        "Reyes turns 37 on Sunday.")}],
    "evidence": {"footage_candidates": [
        {"video_id": "JmTwSOlQz8g", "nature": "episode", "channel_title":
         "Weekend Night Live", "title": "Republican Midterm Ads Cold Open - WNL"},
        # the hunter calls the monologue itself an interview (a query facet)
        {"video_id": "KTe9OatvQas", "nature": "interview", "channel_title":
         "Weekend Night Live", "title": "Dana Reyes Monologue - WNL"},
        {"video_id": "d7b1ilF5290", "nature": "interview", "channel_title":
         "Late Night with Sam Meadows", "title": (
             "Dana Reyes Is Hosting WNL on Her Birthday, Talks Filming with "
             "Taylor Sterling in Patient Zero Video")},
    ]}}]}
# UiIRlg4Xr5w came into the pool from an earlier batch: only the registry names it.
REGISTRY = {"entries": [
    {"id": "UiIRlg4Xr5w", "title": "Example Network Kart Rally Trailer - WNL",
     "uploader": "Weekend Night Live"},
    {"id": "d7b1ilF5290", "title": "Dana Reyes Is Hosting WNL on Her "
     "Birthday, Talks Filming with Taylor Sterling in Patient Zero Video",
     "uploader": "Late Night with Sam Meadows"},
]}
POOL = ["JmTwSOlQz8g", "KTe9OatvQas", "d7b1ilF5290", "UiIRlg4Xr5w"]
# The spoken words of each of the seven anchors of 0701Z (word_index to the next).
WORDS_0701Z = [
    "The most talked-about WNL moment right now has a detail almost nobody "
    "mentions: Taylor Sterling didn't just show up, she walked straight into "
    "Dana Reyes's monologue.",
    "Taylor Sterling crashes the monologue just as Dana Reyes is joking about "
    "her own string of failed relationships, no introduction, no cue, Swift "
    "just walks out",
    "mid-joke in front of a full Studio 8H crowd and takes it over. Reyes "
    "calls her, quote, my literal therapist, the audience loses it, and Swift",
    "throws in a shout-out of her own, yet Vulture's own recap still calls the "
    "rest of the hour a sleepy start to the season, with Swift's",
    "entrance standing out as the one moment that actually landed. Here's the "
    "part the recaps skip entirely: Variety reported that the same night's "
    "cold open ran",
    "a completely separate sketch, two performers playing Republican "
    "strategists sweating over election buzz for their party, all of it "
    "minutes before Swift ever walked out.",
    "One monologue, two different segments worth remembering, and only one of "
    "them is the reason everyone's still talking today.",
]
# What 0701Z placed: block start -> shot (the plan), with the anchor it served.
PLACED_0701Z = [(0, "KTe9OatvQas:2"), (1, "KTe9OatvQas:4"), (1, "d7b1ilF5290:7"),
                (2, "d7b1ilF5290:57"), (2, "d7b1ilF5290:17"), (3, "KTe9OatvQas:5"),
                (4, "JmTwSOlQz8g:13"), (5, "JmTwSOlQz8g:5"), (6, "d7b1ilF5290:2"),
                (6, "d7b1ilF5290:58")]


def _guard(spec=SPEC, hunter=HUNTER, pool=POOL, registry=REGISTRY, reqs=None):
    return ef.build(spec, pool, hunter, registry, reqs)


def test_own_names_carry_the_initials():
    assert ef.own_names(WNL_REF) == ["weekend night live", "wnl"]
    names = ef.own_names({"name": "Vanguards: Endgame",
                          "rights_holder": "Example Animation/Zenith Studios"})
    assert "example animation" in names and "zenith" in names, names
    assert ef.is_own_channel("Zenith Entertainment", names)
    assert ef.is_own_channel("Example Studios", ef.own_names(
        {"name": "Delver", "rights_holder": "Example Studios"}))
    assert not ef.is_own_channel("Late Night with Sam Meadows",
                                 ef.own_names(WNL_REF))


def test_sources_of_0701Z_are_sorted_by_whose_they_are():
    g = _guard()
    roles = {v: r["role"] for v, r in g["sources"].items()}
    assert roles == {"JmTwSOlQz8g": "own", "KTe9OatvQas": "own",
                     "d7b1ilF5290": "interview", "UiIRlg4Xr5w": "own"}, roles
    # the monologue is the work's own by its channel, whatever the hunter said
    assert "work's own" in g["sources"]["KTe9OatvQas"]["why"]
    assert g["interview"] == ["d7b1ilF5290"]
    assert "sam meadows" in g["show_names"]
    assert g["applied"] and g["scene_kind"] == "on_screen", g


def test_a_registry_only_source_is_read_by_its_title():
    names = ef.own_names(WNL_REF)
    rec = {"title": "Tom Carver Says Taylor Sterling Was Schooling Him, Talks Wild "
                    "Delver Transformation", "uploader": "The Evening Show "
                    "Starring Jim Fenwick", "nature": None}
    assert ef.classify("x", rec, names)[0] == "interview"
    rec = {"title": "DELVER Official Trailer #2 (2026, Tom Carver)",
           "uploader": "Trailer World", "nature": None}
    assert ef.classify("x", rec, names)[0] == "own"
    assert ef.classify("x", {"title": "Reaction!", "uploader": "Some Guy",
                             "nature": "commentary"}, names)[0] == "other"
    assert ef.classify("x", None, names)[0] == "other"


def test_scene_kinds():
    assert ef.scene_kind(HUNTER["topics"][0]["scenes"][0]["description"]) == "on_screen"
    assert ef.scene_kind("Florence Pugh says her casting happened because Tom "
                         "Holland personally named her.") == "statement"
    assert ef.scene_kind("Director Alejandro G. Inarritu reveals the film was "
                         "originally titled 'Blah, Blah, Blah'.") == "statement"
    # the finale is a moment on screen even when it "reveals"
    assert ef.scene_kind("The finale reveals who killed Hal Garrett and unveils "
                         "Manhunter.") == "on_screen"
    assert ef.scene_kind("Tom Carver's 'Delver' posts his lowest opening in 19 "
                         "years, debuting to just $8 million.") == "other"
    assert ef.scene_kind("") is None


def test_the_rule_is_off_and_says_why():
    g = _guard(spec={**SPEC, "scene_id": None})
    assert not g["applied"] and "no scene" in g["why"]
    hunter = json.loads(json.dumps(HUNTER))
    hunter["topics"][0]["scenes"][0]["description"] = (
        "Dana Reyes tells Sam Meadows she filmed with Taylor Sterling.")
    g = _guard(hunter=hunter)
    assert not g["applied"] and g["scene_kind"] == "statement", g
    g = _guard(pool=["JmTwSOlQz8g", "KTe9OatvQas"])
    assert not g["applied"] and "no interview" in g["why"]
    g = _guard(pool=["d7b1ilF5290"])
    assert not g["applied"] and g.get("needs_supplement") and "CF-0345" in g["why"]
    g = _guard(spec={**SPEC, "scene_id": "nope"})
    assert not g["applied"] and "not in the hunter" in g["why"]


def test_every_0701Z_anchor_retells_the_event():
    g = _guard()
    dec = [ef.block_rule(g, t) for t in WORDS_0701Z]
    assert all(d[0] for d in dec), dec


def test_words_that_say_interview_keep_it():
    g = _guard()
    for text in ("she told Sam Meadows all about it",
                 "Reyes said in an interview that she was nervous",
                 "on Late Night she laughed it off",
                 "on a podcast last week"):
        ok, why = ef.block_rule(g, text)
        assert not ok and why, (text, why)
    assert ef.block_rule({"applied": False}, "anything") == (False, None)


def test_0701Z_interview_cuts_are_refused_and_the_monologue_kept():
    g = _guard()
    dec = [ef.block_rule(g, t) for t in WORDS_0701Z]
    refused = [shot for ai, shot in PLACED_0701Z
               if ef.refusal(g, dec[ai][0], shot.split(":")[0])]
    assert refused == ["d7b1ilF5290:7", "d7b1ilF5290:57", "d7b1ilF5290:17",
                       "d7b1ilF5290:2", "d7b1ilF5290:58"], refused
    why = ef.refusal(g, True, "/f/d7b1ilF5290.mp4")
    assert "Late Night with Sam Meadows" in why and "CF-0545" in why
    assert ef.refusal(g, False, "d7b1ilF5290") is None


def test_screen_matches_strips_only_event_blocks():
    g = _guard()
    def cand(vid, n, score):
        return {"source": f"/f/{vid}.mp4", "shot": n, "score": score, "index": vid}
    matches = [
        {"phrase": "red dress centre stage",
         "candidates": [cand("d7b1ilF5290", 57, 0.27), cand("KTe9OatvQas", 6, 0.20)]},
        {"phrase": "Sam Meadows greets her",
         "candidates": [cand("d7b1ilF5290", 2, 0.31)]},
    ]
    dec = [ef.block_rule(g, WORDS_0701Z[2]),
           ef.block_rule(g, "she told Sam Meadows on Late Night")]
    refused = ef.screen_matches(matches, dec, g, min_score=0.22)
    assert [r["shot"] for r in refused] == [57]
    assert [c["shot"] for c in matches[0]["candidates"]] == [6]
    assert matches[0]["found"] is False        # 0.20 under 0.22
    assert [c["shot"] for c in matches[1]["candidates"]] == [2]
    assert ef.screen_matches(matches, dec, {"applied": False}) == []


def test_batch_inputs_read_hunter_registry_and_supplements():
    with tempfile.TemporaryDirectory() as tmp:
        batch, foot = Path(tmp) / "b", Path(tmp) / "f"
        (batch / "work" / "supplement-requests" / "consumed").mkdir(parents=True)
        foot.mkdir()
        (batch / "01-trend-hunter.json").write_text(json.dumps(HUNTER))
        (foot / "index.json").write_text(json.dumps(REGISTRY))
        (batch / "work" / "supplement-requests" / "consumed" / "t.json").write_text(
            json.dumps({"candidates": [{"video_id": "KimmelClip1", "nature":
                                        "interview", "channel_title":
                                        "Jimmy Kimmel Live", "title": "X"}]}))
        hunter, registry, reqs = ef.batch_inputs(batch, foot)
        assert hunter == HUNTER and registry == REGISTRY and len(reqs) == 1
        g = ef.build(SPEC, POOL + ["KimmelClip1"], hunter, registry, reqs)
        assert g["sources"]["KimmelClip1"]["role"] == "interview"
        assert ef.batch_inputs(None, None) == (None, None, [])


# --- the wiring in resolve_anchors ------------------------------------------

def _ra():
    import resolve_anchors
    return resolve_anchors


def test_script_of_order_reads_one_script_or_the_whole_file():
    ra = _ra()
    with tempfile.TemporaryDirectory() as tmp:
        one = Path(tmp) / "order.json"
        one.write_text(json.dumps({**SPEC, "script_id": "s1", "pattern": {}}))
        assert ra.script_of_order(str(one))["scene_id"] == SCENE
        whole = Path(tmp) / "03.json"
        whole.write_text(json.dumps({"scripts": [
            {"script_id": "s0", "scene_id": "x"}, {**SPEC, "script_id": "s1"}]}))
        assert ra.script_of_order(str(whole), "s1")["scene_id"] == SCENE
        assert ra.script_of_order(str(whole), "nope") == {}
    assert ra.script_of_order(json.dumps(SPEC))["topic_id"] == TOPIC
    assert ra.script_of_order(None) == {}
    assert ra.script_of_order("/no/such/file.json") == {}


def test_event_guard_for_finds_the_batch_and_the_registry():
    ra = _ra()
    with tempfile.TemporaryDirectory() as tmp:
        batch, foot = Path(tmp) / "batch", Path(tmp) / "footage"
        (batch / "work" / "wnl" / "clips").mkdir(parents=True)
        foot.mkdir()
        (batch / "01b-footage-index.json").write_text("{}")
        (batch / "01-trend-hunter.json").write_text(json.dumps(HUNTER))
        (foot / "index.json").write_text(json.dumps(REGISTRY))
        index_data = {f"{foot}/{v}.shots.json": {"source": f"{foot}/{v}.mp4",
                                                 "shots": []} for v in POOL}
        g = ra.event_guard_for(SPEC, index_data, batch / "01b-footage-index.json")
        assert g["applied"] and g["interview"] == ["d7b1ilF5290"], g
        assert g["sources"]["UiIRlg4Xr5w"]["role"] == "own"
        g = ra.event_guard_for(SPEC, index_data, None)   # outside a batch
        assert not g["applied"]


def test_event_record_names_the_short_blocks():
    ra = _ra()
    g = _guard()
    anchors = [{"anchor_id": f"v{i+1}", "word_index": i * 10,
                "phrase": f"p{i}"} for i in range(3)]
    dec = [(True, "its words retell the event"),
           (True, "its words retell the event"),
           (False, "its words name the interview's show ('sam meadows')")]
    refused = [{"phrase": "p0", "shot": 57}, {"phrase": "p1", "shot": 7}]
    matches = [{"found": False}, {"found": True}, {"found": True}]
    rec = ra.event_footage_record(g, anchors, dec, refused,
                                  [True, True, True], matches)
    assert rec["applied"] and rec["refused"] == 2
    assert [b["retells_event"] for b in rec["blocks"]] == [True, True, False]
    assert [x["anchor_id"] for x in rec["short"]] == ["v1"]
    assert rec["needs_supplement"] and "CF-0345" in rec["short"][0]["reason"]
    off = ra.event_footage_record({"applied": False, "why": "w"}, anchors, dec,
                                  [], [True] * 3, matches)
    assert off["blocks"] == [] and not off["needs_supplement"]


def test_event_decisions_read_each_anchors_words():
    ra = _ra()
    g = _guard()
    words = [{"word": w} for w in
             "Swift walks out mid-joke . She told Sam Meadows later".split()]
    anchors = [{"word_index": 0}, {"word_index": 5}]
    assert [d[0] for d in ra.event_decisions(g, anchors, words)] == [True, False]


def test_main_screens_before_any_rung_and_fill_asks_again():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    main = src.split("def main():")[1]
    screen = main.index("event_footage.screen_matches(")
    assert main.index("entity_guard.screen_matches(") < screen
    assert screen < main.index("rhythm.normalize_order(load_order(")
    assert screen < main.index("build_split_opening(")
    assert "rejected_candidates.extend(event_refused)" in main
    fill = main.split("def fill(")[1]
    assert fill.index("entity_guard.refusal(") < fill.index("event_footage.refusal(")
    assert '"event_footage": event_footage_record(' in main


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
