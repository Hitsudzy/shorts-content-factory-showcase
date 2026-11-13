#!/usr/bin/env python3
"""CF-0575: the event-footage rule is one module at the root
(`shared/event_footage.py`), and its writer's half - `scope()`: which anchors
retell the hunter's on-screen scene, which sources are the event itself.

Frozen data: WNL `pipeline/example-film/2026-10-05T0701Z` (the same the Video
Editor's `tests/test_event_footage.py` pins): the monologue is `KTe9OatvQas`;
the cold open and the Kart Rally trailer are the work's own and not the
monologue; `d7b1ilF5290` is Late Night's interview. Offline, stdlib only.
"""
import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("event_footage_shared",
                                               ROOT / "shared" / "event_footage.py")
ef = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ef)

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


def _scope(words=WORDS_0701Z, **kw):
    args = dict(spec=SPEC, source_ids=POOL, texts=words, hunter=HUNTER,
                registry=REGISTRY)
    args.update(kw)
    return ef.scope(args.pop("spec"), args.pop("source_ids"), args.pop("texts"), **args)


def test_wnl_0701z_the_monologue_is_one_source_and_five_anchors():
    s = _scope()
    assert s["active"] and s["moment"] == "monologue", s
    assert s["event_sources"] == ["KTe9OatvQas"], s["event_sources"]
    assert s["interview"] == ["d7b1ilF5290"], s["interview"]
    # v5 names the cold open, v6 "a completely separate sketch": another segment
    assert s["event_anchors"] == [0, 1, 2, 3, 6], s["anchors"]
    assert "cold open" in s["anchors"][4]["why"] and "sketch" in s["anchors"][5]["why"]


def test_the_scene_names_the_monologue_before_the_cameo():
    desc = HUNTER["topics"][0]["scenes"][0]["description"]
    assert ef.moments_in(desc) == ["monologue", "cameo"]
    assert ef.scene_moment(desc) == "monologue"
    assert ef.scene_moment("The finale reveals who killed Laura") is None


def test_no_own_title_names_the_moment_every_own_source_is_the_event():
    hunter = {"topics": [dict(HUNTER["topics"][0], scenes=[{
        "scene_id": SCENE, "description": "The season finale episode ends on a cliffhanger"}])]}
    s = _scope(hunter=hunter)
    assert s["active"] and s["moment"] is None
    assert sorted(s["event_sources"]) == sorted(["JmTwSOlQz8g", "KTe9OatvQas", "UiIRlg4Xr5w"])
    # with no segment named, no anchor is "another segment"
    assert s["event_anchors"] == [0, 1, 2, 3, 4, 5, 6]


def test_words_that_put_the_block_in_the_interview_are_not_the_event():
    words = list(WORDS_0701Z)
    words[6] = "She told Sam Meadows in an interview it was her birthday."
    s = _scope(words=words)
    assert 6 not in s["event_anchors"]
    assert "interview" in s["anchors"][6]["why"]


def test_off_when_the_editor_rule_is_off():
    # a statement scene: the interview is the event
    hunter = {"topics": [dict(HUNTER["topics"][0], scenes=[{
        "scene_id": SCENE, "description": "Dana Reyes says Swift is her therapist"}])]}
    s = _scope(hunter=hunter)
    assert not s["active"] and not s["needs_supplement"] and s["event_anchors"] == []
    # no interview of another production in the pool
    s = _scope(source_ids=["JmTwSOlQz8g", "KTe9OatvQas"])
    assert not s["active"] and s["event_anchors"] == []


def test_no_own_source_is_a_request_not_a_count():
    s = _scope(source_ids=["d7b1ilF5290"])
    assert not s["active"] and s["needs_supplement"]
    assert s["event_sources"] == [] and s["event_anchors"] == [0, 1, 2, 3, 6]


def test_source_id_reads_the_shapes_the_preflight_writes():
    assert ef.source_id("KTe9OatvQas:3") == "KTe9OatvQas"
    assert ef.source_id("/x/shared/footage/KTe9OatvQas.shots.json") == "KTe9OatvQas"
    assert ef.source_id("/x/shared/footage/KTe9OatvQas.mp4") == "KTe9OatvQas"
    assert ef.source_id(None) is None


def test_the_video_editor_keeps_no_copy():
    """The Editor's `scripts/event_footage.py` loads this file by path; a
    second copy of the classification is the defect CF-0575 removed. Skipped
    out loud when the Editor's checkout is not beside the root."""
    ve = ROOT / "agents" / "video-editor" / "scripts" / "event_footage.py"
    if not ve.is_file():
        print(f"  skip: {ve} is not here")
        return
    text = ve.read_text()
    assert 'SHARED_REL = Path("shared") / "event_footage.py"' in text, \
        "the Editor does not load the root's module"
    for name in ("def classify", "def build", "def block_rule", "INTERVIEW_TITLE_RE ="):
        assert name not in text, f"the Editor keeps its own {name!r}"



# CF-0576: the seven anchors' pictures (`phrase`) of 0701Z.
PHRASES_0701Z = [
    "Wide shot of the Weekend Night Live Studio 8H stage past the dark audience, a "
    "glowing archway and string-light marquee framing the set, a figure in a long red "
    "dress standing far upstage.",
    "A woman in a long, fitted red dress walking down a short runway-like stage toward "
    "a packed, applauding studio audience.",
    "A woman in a sleeveless red dress stands centre stage facing the camera, hands "
    "clasped, delivering the monologue.",
    "The woman in the red dress stands on stage beside another woman in a light plaid "
    "or check outfit, both facing the audience.",
    "Two cast members stand in a studio set backed by an American flag and a large "
    "blue-and-red Republican National Committee seal.",
    "A wide shot of three people on the RNC-seal set, one with a hand on hip, one "
    "gesturing, one speaking animatedly.",
    "Sam Meadows in a white tuxedo jacket and Dana Reyes in a black dress meet and "
    "shake hands as she walks out to greet him.",
]


def test_cf0576_wnl_0701z_the_sam_meadows_anchor_under_the_monologue_payoff():
    s = _scope(phrases=PHRASES_0701Z)
    assert s["foreign_interview_anchors"] == [6], s["anchors"]
    assert "sam meadows" in s["anchors"][6]["interview_picture"]["why"]
    assert s["show_names"] == ["late night with sam meadows", "sam meadows"]
    # the monologue's own pictures are not an interview's
    assert all("interview_picture" not in a for a in s["anchors"][:6])


def test_cf0576_an_interview_picture_under_words_that_name_it_is_allowed():
    words = list(WORDS_0701Z)
    for w in ("Days earlier on Late Night, Reyes had already teased the birthday.",
              "Sam Meadows got the first hint of it a week before.",
              "On a talk show couch she had sworn nothing was planned."):
        words[6] = w
        s = _scope(words=words, phrases=PHRASES_0701Z)
        assert s["foreign_interview_anchors"] == [], (w, s["anchors"][6])
        assert "allowed" in s["anchors"][6]["interview_picture"]["why"]


def test_cf0576_talk_show_furniture_is_an_interview_picture():
    guard = {"interview": ["d7b1ilF5290"], "show_names": ["late night with sam meadows",
                                                          "sam meadows"]}
    for phrase in ("A woman on a talk-show guest couch laughing beside the host's desk",
                   "Dana Reyes in an interview, seated, gesturing",
                   "The Late Night set: a desk, a city skyline backdrop"):
        assert ef.pictures_interview(guard, phrase)[0], phrase
    for phrase in ("A late-night city street in the rain",
                   "The WNL host stands centre stage in a red dress"):
        assert not ef.pictures_interview(guard, phrase)[0], phrase
    # no interview of another production in the pool - nothing to picture
    assert not ef.pictures_interview({"interview": []}, "Sam Meadows at his desk")[0]


def test_cf0576_off_where_the_rule_is_off():
    hunter = {"topics": [dict(HUNTER["topics"][0], scenes=[{
        "scene_id": SCENE, "description": "Dana Reyes says Swift is her therapist"}])]}
    s = _scope(hunter=hunter, phrases=PHRASES_0701Z)
    assert s["foreign_interview_anchors"] == []
    # needs_supplement (no own source): the words still decide
    s = _scope(source_ids=["d7b1ilF5290"], phrases=PHRASES_0701Z)
    assert s["foreign_interview_anchors"] == [6]
    # no phrases given (CF-0575's callers): no picture is judged
    assert _scope()["foreign_interview_anchors"] == []



def test_cf0576_the_best_shot_says_which_interview():
    guard = {"interview": ["d7b1ilF5290"], "show_names": ["late night with sam meadows",
                                                          "sam meadows"]}
    # 1901Z: "an on-camera interview" whose best shot is the work's own featurette
    phrase = "a blonde woman smiling during an on-camera interview against a sunlit window"
    assert not ef.pictures_interview(guard, phrase, ["EK473pb9cH0:3", "d7b1ilF5290:1"])[0]
    assert ef.pictures_interview(guard, phrase, [])[0]         # no shot: the words decide
    # a phrase with no interview word whose best shot is the foreign interview
    yes, why = ef.pictures_interview(guard, "A woman in a black dress laughing on a couch",
                                     ["d7b1ilF5290:7", "KTe9OatvQas:1"])
    assert yes and "d7b1ilF5290:7" in why
    # 0701Z with the preflight's samples: still v7 only
    samples = [["KTe9OatvQas:0"], ["KTe9OatvQas:1"], ["KTe9OatvQas:2"], ["KTe9OatvQas:1"],
               ["JmTwSOlQz8g:13"], ["JmTwSOlQz8g:5"], ["d7b1ilF5290:1"]]
    s = _scope(phrases=PHRASES_0701Z, samples=samples)
    assert s["foreign_interview_anchors"] == [6], s["anchors"]


def test_archive_candidate_reaches_its_pool_file_by_candidate_id():
    """CF-0665: the hunter names an archive candidate `nasa:<id>` /
    `commons:<pageid>`; the pool keeps it as `nasa-<id>` / `commons-<pageid>`
    with the hunter's id as `candidate_id` in the registry. Its nature and
    title must land on the file id the Editor picks."""
    topic = {"topic_id": "sci-1", "evidence": {"footage_candidates": [
        {"video_id": "nasa:PIA 25.1", "nature": "interview", "title": "Engineer interview",
         "channel_title": None},
        {"video_id": "commons:777", "nature": "explainer", "title": "Orbit animation"},
        {"video_id": "nasa:jsc2024", "nature": "launch", "title": "Liftoff"},
    ]}}
    registry = {"entries": [
        # the indexer's file id, with the hunter's id beside it
        {"id": "nasa-PIA_25_1", "candidate_id": "nasa:PIA 25.1", "title": "PIA 25.1",
         "uploader": ""},
        {"id": "commons-777", "candidate_id": "commons:777", "title": "File:Orbit.webm"},
    ]}
    recs = ef.source_records(topic, [], registry)
    assert recs["nasa-PIA_25_1"]["nature"] == "interview", recs
    assert recs["nasa-PIA_25_1"]["title"] == "Engineer interview", recs
    assert recs["commons-777"]["nature"] == "explainer", recs
    # not in the registry yet: keyed by the indexer's own naming rule
    assert recs["nasa-jsc2024"]["nature"] == "launch", recs
    assert not any(":" in k for k in recs), recs
    # and the classification reads it under the file id
    role, _why = ef.classify("nasa-PIA_25_1", recs["nasa-PIA_25_1"], ef.own_names(None))
    assert role == "interview"
    assert ef.FOOTAGE_IDS.archive_file_id("commons:12 3") == "commons-12_3"
    assert ef.FOOTAGE_IDS.is_pool_file_id("nasa-PIA_25_1")


if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
