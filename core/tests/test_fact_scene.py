#!/usr/bin/env python3
"""CF-0548: the video's fact is about the topic's own scene, not about the
segment next to it (`shared/factrule/fact_scene.py`). The fixtures are the
WNL / Verity / Delver topics of `example-film/2026-10-05T0701Z`, cut down to
the fields the rule reads. Offline, stdlib only."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODULE = ROOT / "shared" / "factrule" / "fact_scene.py"


def _load():
    spec = importlib.util.spec_from_file_location("fact_scene_cf0548", MODULE)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fs = _load()

DEADLINE_SWIFT = "https://deadline.com/2026/10/taylor-sterling-joins-wnl-host-dana-reyes-1237146104/"

WNL = {
    "topic_id": "lf-2026-10-05-003",
    "title_ref": {"name": "Weekend Night Live", "kind": "person", "type": "tv_series",
                  "person": "Dana Reyes"},
    "evidence": {"sources": [
        {"url": DEADLINE_SWIFT,
         "title": "Taylor Sterling Joins ‘WNL’ Host Dana Reyes During Opening Monologue",
         "summary": "Taylor Sterling gave Dana Reyes some pretty sweet payback for appearing "
                    "in her “Patient Zero” music video."},
        {"url": "http://www.vulture.com/article/weekend-night-live-recap.html",
         "title": "Weekend Night Live Recap: Dana Reyes’s Third Time Isn’t a Charm",
         "summary": "Dana Reyes’s subdued performance does little to liven up what feels "
                    "like a sleepy start to the season."}]},
    "scenes": [
        {"scene_id": "lf-2026-10-05-003-s1", "source_url": DEADLINE_SWIFT,
         "description": "Taylor Sterling surprised Dana Reyes by joining her opening monologue "
                        "on 'Weekend Night Live' — payback for Reyes's cameo in Swift's "
                        "'Patient Zero' music video, and maybe a birthday gift too, since "
                        "Reyes turns 37 on Sunday."},
        {"scene_id": "lf-2026-10-05-003-s3",
         "source_url": "http://www.vulture.com/article/weekend-night-live-recap.html",
         "description": "Vulture's recap calls Dana Reyes's third time hosting 'Saturday "
                        "Night Live' a disappointment."}],
}

COLD_OPEN = {"text": "In the Oct. 3 cold open on “Weekend Night Live,” Andrew Dismukes and "
                     "Ashley Padilla play Republican strategists who have their work cut out "
                     "for them building buzz for their party.",
             "kind": "other", "source": "Variety", "attribution": "Variety reported",
             "url": "https://variety.com/2026/tv/news/wnl-pete-hegseth-cold-open/"}
SHOW_HISTORY = {"text": "The show's premiere was hosted by George Carlin on NBC on October "
                        "11, 1975, under the original title NBC's Saturday Night.",
                "kind": "other", "source": "Wikipedia", "section": "Lead",
                "url": "https://en.wikipedia.org/wiki/Weekend_Night_Live"}
SHOW_RATINGS = {"text": "As of 2018, thirteen of the show's lowest-rated seasons occurred in "
                        "the 2000s.", "kind": "box_office", "source": "Wikipedia",
                "section": "Ratings", "url": "https://en.wikipedia.org/wiki/Weekend_Night_Live"}
BACKSTORY = {"text": "Dana Reyes appeared in Taylor Sterling's “Patient Zero” music video "
                     "released in September 2026, Variety reported.",
             "kind": "people_news", "source": "Variety", "attribution": "Variety reported",
             "url": "https://variety.com/2026/music/news/patient-zero-video/"}

VERITY = {
    "topic_id": "lf-2026-10-05-005",
    "title_ref": {"name": "Verity", "kind": "work", "type": "film",
                  "rights_holder": "Amazon MGM Studios"},
    "scenes": [{"scene_id": "v-s1", "description": "Colleen Hoover's 'Verity' opened to $62.5 "
                "million worldwide — the second-best global debut for a Hoover adaptation."},
               {"scene_id": "v-s2", "description": "'Verity' scored a $32 million opening "
                "weekend debut, far outpacing 'Delver's dismal $8 million start."}],
}
DELVER = {"topic_id": "lf-2026-10-05-002",
          "title_ref": {"name": "Delver", "kind": "work", "type": "film"},
          "scenes": [{"scene_id": "d-s1", "description": "Tom Carver's 'Delver' posts his "
                      "lowest opening in 19 years, debuting to just $8 million."}]}
BATCH = [WNL, VERITY, DELVER]

DELVER_WEEKEND = {"text": "Example Studios’ very original, very expensive auteur feature, Delver, "
                          "opened to $8M, the lowest for Tom Carver since 2007.",
                  "kind": "box_office", "source": "Deadline", "attribution": "Deadline reported",
                  "url": "https://deadline.com/2026/10/box-office-verity-delver/"}
SWIFT_IN_VERITY = {"text": "Taylor Sterling joined the Verity actress during her opening "
                           "monologue tonight on Weekend Night Live.",
                   "kind": "casting", "source": "Deadline", "attribution": "Deadline reported",
                   "url": DEADLINE_SWIFT}
VERITY_PRODUCTION = {"text": "A film adaptation of Colleen Hoover's 2018 novel Verity was "
                             "being developed by Nick Antosca and Alex Hedlund.",
                     "kind": "production", "source": "Wikipedia", "section": "Production",
                     "url": "https://en.wikipedia.org/wiki/Verity_(film)#Production"}


def _fit(cand, topic, scene_index=0):
    return fs.fits_scene(cand, topic["scenes"][scene_index], topic,
                         fs.other_subjects(topic, BATCH))


# ------------------------------------------------------------------ WNL 0701Z
def test_the_cold_open_is_not_the_monologue():
    v = _fit(COLD_OPEN, WNL)
    assert not v["fits"]
    assert v["shape"] == fs.SHAPE_EVENT
    assert fs.FAIL_OTHER_SEGMENT in v["failures"]
    assert fs.FAIL_NAMES_OUTSIDE_SCENE in v["failures"]
    assert v["segments"] == {"fact": ["cold_open"], "scene": ["monologue"]}
    assert any("Dismukes" in n for n in v["outside"])


def test_the_cold_open_fits_no_scene_of_the_topic():
    """Not the monologue, and not the episode-as-a-whole scene either: its
    performers are nobody of the scene."""
    out = fs.annotate([COLD_OPEN], WNL, BATCH)
    assert out[0][fs.SCENES_KEY] == []
    assert fs.FAIL_NAMES_OUTSIDE_SCENE in out[0][fs.FIT_KEY]["lf-2026-10-05-003-s3"]


def test_the_show_history_is_not_tonights_moment():
    for cand in (SHOW_HISTORY, SHOW_RATINGS):
        v = _fit(cand, WNL)
        assert not v["fits"], cand["text"]
        assert fs.FAIL_NOT_ABOUT_SCENE in v["failures"]
    assert "George Carlin" in _fit(SHOW_HISTORY, WNL)["outside"]


def test_the_direct_backstory_of_the_moment_fits():
    v = _fit(BACKSTORY, WNL)
    assert v["fits"], v


def test_annotate_keeps_order_and_best_for_scene_takes_the_first_that_fits():
    out = fs.annotate([COLD_OPEN, SHOW_HISTORY, BACKSTORY], WNL, BATCH)
    assert [c["text"] for c in out] == [c["text"] for c in (COLD_OPEN, SHOW_HISTORY, BACKSTORY)]
    assert fs.best_for_scene(out, "lf-2026-10-05-003-s1")["text"] == BACKSTORY["text"]
    assert fs.best_for_scene(out[:2], "lf-2026-10-05-003-s1") is None
    assert fs.failure_summary(out[0])[:2] == [fs.FAIL_OTHER_SEGMENT, fs.FAIL_NAMES_OUTSIDE_SCENE]


# ------------------------------------------------------------------ work topics
def test_another_topic_of_the_batch_is_not_this_ones_fact():
    v = _fit(DELVER_WEEKEND, VERITY)
    assert fs.FAIL_OTHER_TOPIC in v["failures"] and v["foreign"] == ["Delver"]
    v = _fit(SWIFT_IN_VERITY, VERITY)
    assert fs.FAIL_OTHER_TOPIC in v["failures"] and v["foreign"] == ["Weekend Night Live"]


def test_a_scene_that_names_the_other_work_still_wants_the_fact_about_its_own():
    """'Verity outpaced Delver' may say Delver - a fact about Delver alone is
    still not Verity's."""
    v = _fit(DELVER_WEEKEND, VERITY, 1)
    assert v["failures"] == [fs.FAIL_NOT_ABOUT_SCENE]


def test_the_works_own_article_is_its_backstory():
    """Wikipedia sentences of the topic's own article: the names of the work's
    own history (its producers) are not held to the scene."""
    v = _fit(VERITY_PRODUCTION, VERITY)
    assert v["fits"] and v["shape"] == fs.SHAPE_WORK
    assert any("Nick Antosca" in n for n in v["outside"])  # reported, not failed


def test_a_lead_sentence_without_a_section_is_the_works_own_text_too():
    """The accepted Primetime (2026-09-30T2210Z): a Wikipedia lead sentence,
    no `section` in its record, under a scene about Chris Hansen's verdict."""
    topic = {"title_ref": {"name": "Primetime", "kind": "work", "type": "film",
                           "rights_holder": "B25 Films"},
             "scenes": [{"scene_id": "p-s1", "description": "Chris Hansen finally saw "
                         "'Primetime' and graded Robert Pattinson's performance a 'D'."}]}
    fact = {"text": "The film premiered in the main competition of the 83rd Venice "
                    "International Film Festival on September 5, 2026.",
            "source": "Wikipedia", "url": "https://en.wikipedia.org/wiki/Primetime_(film)"}
    assert fs.fits_scene(fact, topic["scenes"][0], topic)["fits"]
    assert fs.own_article_candidate({"url": "https://en.wikipedia.org/wiki/X"})
    assert not fs.own_article_candidate({"source": "Variety", "url": "https://variety.com/x"})


def test_the_same_fact_is_its_own_topics():
    assert _fit(DELVER_WEEKEND, DELVER)["fits"]


# ------------------------------------------------------------------ the parts
def test_segments_and_their_compatibility():
    assert fs.segments("the WNL cold open mocked") == {"cold_open"}
    assert fs.segments("during her opening monologue") == {"monologue"}
    assert fs.segments("promised her a musical number") == set()
    assert fs.same_segment({"cold_open"}, {"sketch"})
    assert not fs.same_segment({"cold_open"}, {"monologue"})
    assert fs.same_segment(set(), {"monologue"}) and fs.same_segment({"monologue"}, set())


def test_a_film_scene_naming_a_monologue_is_still_a_work():
    topic = {"title_ref": {"name": "Delver", "kind": "work", "type": "film"}}
    assert fs.shape(topic, {"description": "the villain's monologue"}) == fs.SHAPE_WORK
    show = {"title_ref": {"name": "Weekend Night Live", "kind": "work", "type": "tv_series"}}
    assert fs.shape(show, {"description": "the cold open mocked Hegseth"}) == fs.SHAPE_EVENT


def test_proper_names():
    names = fs.proper_names("SUNDAY AM WRITETHRU: After Saturday update Example Studios’ feature, "
                            "Delver, opened to $8M. In December 2022, Gunn stated it on "
                            "“Weekend Night Live.”")
    assert names == ["Example Studios", "Delver", "Gunn", "Weekend Night Live"]
    assert fs.proper_names("Ratings entered a decline.") == []
    assert fs.name_in("Tom Carver", fs.fold("Cruise said"), {"cruise", "said"})
    assert fs.name_in("Weekend Night Live", fs.fold("WNL host"), {"wnl", "host"})


def test_the_gate_reads_the_scripts_scene():
    script = {"scene_id": "lf-2026-10-05-003-s1"}
    v = fs.fact_fits_script(COLD_OPEN, script, WNL, BATCH)
    assert v is not None and not v["fits"]
    assert fs.fact_fits_script(COLD_OPEN, {"scene_id": "nope"}, WNL, BATCH) is None


if __name__ == "__main__":
    import sys
    import traceback
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:                          # noqa: BLE001
            failed += 1
            traceback.print_exc()
            print(f"FAIL {name}: {e.__class__.__name__}: {str(e)[:300]}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
