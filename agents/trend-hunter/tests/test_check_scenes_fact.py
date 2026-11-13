#!/usr/bin/env python3
"""CF-0548: check_scenes.py --write judges the topic's fact candidates against
its final scenes; a topic whose every passing candidate is about another
segment (WNL 0701Z: the cold open under the monologue) leaves as no_fact
before indexing. Offline, stdlib only."""
import copy
import sys
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import check_scenes as cs  # noqa: E402

DEADLINE = "https://deadline.com/2026/10/taylor-sterling-joins-wnl-host-dana-reyes-1237146104/"
PASS = {"passes": True, "failures": [], "kind": "other", "tier": 1}
COLD_OPEN = {"text": "In the Oct. 3 cold open on “Weekend Night Live,” Andrew Dismukes and "
                     "Ashley Padilla play Republican strategists.",
             "kind": "other", "source": "Variety", "attribution": "Variety reported",
             "url": "https://variety.com/2026/tv/news/wnl-cold-open/", "check": dict(PASS)}
BACKSTORY = {"text": "Dana Reyes appeared in Taylor Sterling's “Patient Zero” music video, "
                     "Variety reported.", "kind": "people_news", "source": "Variety",
             "url": "https://variety.com/2026/music/news/patient-zero/", "check": dict(PASS)}
FAILING = {"text": "something", "kind": "other", "source": "x", "url": "https://x.example/",
           "check": {"passes": False, "failures": ["no_specifics"]}}


def wnl(candidates):
    return {"topic_id": "lf-2026-10-05-003",
            "title_ref": {"name": "Weekend Night Live", "kind": "person",
                          "type": "tv_series", "person": "Dana Reyes"},
            "evidence": {"sources": [{"url": DEADLINE, "publication": "Deadline",
                                      "title": "Taylor Sterling Joins ‘WNL’ Host Dana Reyes "
                                               "During Opening Monologue",
                                      "summary": "Taylor Sterling gave Dana Reyes payback for "
                                                 "appearing in her “Patient Zero” music video."}]},
            "scenes": [{"scene_id": "lf-2026-10-05-003-s1", "source_url": DEADLINE,
                        "description": "Taylor Sterling surprised Dana Reyes by joining her "
                                       "opening monologue on 'Weekend Night Live'."}],
            "fact_probe": {"fact_rule": {"rule": "production_fact_refusal", "state": "found",
                                         "settled": True, "drops": False, "status": "ok"}},
            "fact_candidates": candidates}


def test_an_off_scene_only_topic_leaves_as_no_fact_on_write():
    batch = {"topics": [wnl([COLD_OPEN, FAILING])], "skipped_topics": []}
    lines, problems = cs.run_batch(batch, write=True)
    assert problems == [] and batch["topics"] == []
    row, = batch["skipped_topics"]
    assert row["reason_code"] == "no_fact" and "CF-0548" in row["reason"]
    assert "other_segment" in row["reason"]
    assert row["fact_probe"]["fact_rule"]["state"] == "not_found"
    assert row["fact_probe"]["fact_rule"]["drops"] is True
    assert any("NO_FACT" in ln for ln in lines)


def test_a_topic_with_one_fitting_candidate_stays_annotated():
    batch = {"topics": [wnl([COLD_OPEN, BACKSTORY])]}
    lines, problems = cs.run_batch(batch, write=True)
    assert problems == [] and len(batch["topics"]) == 1
    cold, back = batch["topics"][0]["fact_candidates"]
    assert cold[cs.fact_scene.SCENES_KEY] == []
    assert "other_segment" in cold[cs.fact_scene.FIT_KEY]["lf-2026-10-05-003-s1"]
    assert back[cs.fact_scene.SCENES_KEY] == ["lf-2026-10-05-003-s1"]
    assert "skipped_topics" not in batch


def test_dry_run_and_check_name_the_topic_and_change_nothing():
    batch = {"topics": [wnl([COLD_OPEN])]}
    before = copy.deepcopy(batch)
    _, problems = cs.run_batch(batch, write=False)
    assert batch == before
    assert len(problems) == 1 and "No fact about the topic itself" in problems[0]
    assert cs.check_facts(batch) == problems


def test_no_candidates_or_no_passing_ones_is_not_this_rules_business():
    for cands in ([], [FAILING]):
        batch = {"topics": [wnl(cands)]}
        cs.run_batch(batch, write=True)
        assert len(batch["topics"]) == 1, cands
    old = wnl([COLD_OPEN])
    del old["fact_candidates"]
    assert cs.fact_fit(old, [old]) == (None, False)


if __name__ == "__main__":
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
