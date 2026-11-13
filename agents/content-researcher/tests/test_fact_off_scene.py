#!/usr/bin/env python3
"""CF-0548: the writer's fact is about the topic's own scene, not about the
segment next to it. WNL 0701Z cut down: the topic is Taylor Sterling walking into
Dana Reyes's monologue; the best candidate the hunter carried was the cold
open of the same broadcast.

  * `production_facts.py --from-batch` offers only candidates that fit a scene
    (each with its `scenes`), lists the rest as `off_scene:` rejections, and
    says `off_scene_only` when none is left;
  * `fact_refusal.py` refuses such a topic as no_fact even though the hunter
    settled it - a plain settled emptiness is still only a warning;
  * `check_production_fact.py` refuses a script whose fact is not about its
    `scene_id` (`fact_off_scene`).
Offline, stdlib only."""
import copy
import json
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import check_production_fact as cpf  # noqa: E402
import fact_refusal as fr  # noqa: E402
import production_facts as pf  # noqa: E402
from _factrule import fact_rule  # noqa: E402

DEADLINE = "https://deadline.com/2026/10/taylor-sterling-joins-wnl-host-dana-reyes-1237146104/"
PASS = {"passes": True, "failures": [], "kind": "other", "tier": 1}

COLD_OPEN = {"text": "In the Oct. 3 cold open on “Weekend Night Live,” Andrew Dismukes and "
                     "Ashley Padilla play Republican strategists building buzz for their party.",
             "kind": "other", "source": "Variety", "attribution": "Variety reported",
             "url": "https://variety.com/2026/tv/news/wnl-cold-open/", "check": dict(PASS)}
BACKSTORY = {"text": "Dana Reyes appeared in Taylor Sterling's “Patient Zero” music video, "
                     "Variety reported.",
             "kind": "people_news", "source": "Variety", "attribution": "Variety reported",
             "url": "https://variety.com/2026/music/news/patient-zero-video/",
             "check": dict(PASS, kind="people_news")}
SETTLED = {"rule": fact_rule.RULE_ID, "version": fact_rule.RULE_VERSION, "state": "found",
           "decided_by": "trend-hunter", "settled": True, "drops": False, "status": "ok"}


def wnl_topic(candidates):
    return {"topic_id": "lf-2026-10-05-003",
            "title_ref": {"name": "Weekend Night Live", "kind": "person",
                          "type": "tv_series", "person": "Dana Reyes"},
            "evidence": {"sources": [{"url": DEADLINE,
                                      "title": "Taylor Sterling Joins ‘WNL’ Host Dana Reyes "
                                               "During Opening Monologue"}]},
            "scenes": [{"scene_id": "lf-2026-10-05-003-s1", "source_url": DEADLINE,
                        "description": "Taylor Sterling surprised Dana Reyes by joining her "
                                       "opening monologue on 'Weekend Night Live' - payback "
                                       "for Reyes's cameo in Swift's 'Patient Zero' video."}],
            "fact_probe": {"fact_rule": dict(SETTLED)},
            "fact_candidates": candidates}


def batch_topic(candidates):
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "01-trend-hunter.json"
        path.write_text(json.dumps({"topics": [wnl_topic(candidates)]}))
        topic, = pf.topics_of_batch(path)
    return topic


def test_the_cold_open_is_not_offered_and_the_backstory_is():
    result = pf.result_from_batch(batch_topic([COLD_OPEN, BACKSTORY]))
    assert result["status"] == pf.STATUS_OK
    assert [c["text"] for c in result["candidates"]] == [BACKSTORY["text"]]
    assert result["candidates"][0]["scenes"] == ["lf-2026-10-05-003-s1"]
    assert result["fact"]["text"] == BACKSTORY["text"]
    assert result["off_scene"] == 1 and result["off_scene_only"] is False
    off, = [r for r in result["rejected"] if r["reason"].startswith("off_scene:")]
    assert "other_segment" in off["reason"] and off["text"] == COLD_OPEN["text"]


def test_only_the_cold_open_leaves_no_candidate():
    result = pf.result_from_batch(batch_topic([COLD_OPEN]))
    assert result["status"] == pf.STATUS_NO_CANDIDATES
    assert result["candidates"] == [] and result["fact"] is None
    assert result["off_scene_only"] is True
    lines = []
    pf.print_result(result, out=lines.append)
    assert any("OFF SCENE 1" in ln and "no_fact" in ln for ln in lines), lines


def test_a_batch_without_scenes_is_offered_as_before():
    topic = batch_topic([COLD_OPEN])
    topic["scene_topic"] = dict(topic["scene_topic"], scenes=[])
    result = pf.result_from_batch(topic)
    assert result["status"] == pf.STATUS_OK and result["off_scene"] == 0


def rule_on():
    """CF-0513: the rule on, set on a copy of the channel's config - not read
    off the committed switch (the channel's decision is pinned at the root,
    tests/test_production_fact_refusal.py)."""
    cfg = copy.deepcopy(json.loads(fr.channel_config_path("example-film", fr.find_root()).read_text()))
    key = fr.validator().FACT_REFUSAL_KEY
    cfg[key]["enabled"] = True
    source = cfg.setdefault("sources", {}).get(cfg[key]["fact_source"])
    if not (isinstance(source, dict) and source.get("enabled") is True):
        cfg["sources"][cfg[key]["fact_source"]] = {"enabled": True}
    rule = fr.load_rule(cfg=cfg)
    assert rule is not None and rule.enabled
    return rule


def test_an_off_scene_topic_is_refused_although_it_was_settled():
    rule = rule_on()
    lookup = pf.result_from_batch(batch_topic([COLD_OPEN]))
    decision = fr.plan([lookup], rule, {lookup["topic_id"]: dict(SETTLED)})
    skip, = decision["skipped"]
    assert skip["reason_code"] == fact_rule.REFUSAL_CODE == "no_fact"
    assert "CF-0548" in skip["reason"]
    assert decision["settled"] == [] and decision["proceed"] == []


def test_a_settled_plain_emptiness_is_still_only_kept():
    rule = rule_on()
    lookup = pf.result_from_batch(batch_topic([]))
    assert lookup["off_scene_only"] is False
    decision = fr.plan([lookup], rule, {lookup["topic_id"]: dict(SETTLED)})
    assert decision["skipped"] == [] and decision["settled"] == [lookup["topic_id"]]


def test_the_gate_refuses_a_fact_off_the_scripts_scene():
    topics = [wnl_topic([COLD_OPEN, BACKSTORY])]
    script = {"script_id": "x", "topic_id": "lf-2026-10-05-003",
              "scene_id": "lf-2026-10-05-003-s1",
              "fact": fact_rule.fact_record(COLD_OPEN)}
    line, = cpf.off_scene_lines(script, topics)
    assert line.startswith("fact: fact_off_scene") and "cold_open" in line
    script["fact"] = fact_rule.fact_record(BACKSTORY)
    assert cpf.off_scene_lines(script, topics) == []
    assert cpf.off_scene_lines(dict(script, fact=fact_rule.fact_record(COLD_OPEN)), None) == []


def test_the_gate_reads_the_01_beside_the_03():
    with tempfile.TemporaryDirectory() as tmp:
        assert cpf.hunter_topics(tmp) is None
        (Path(tmp) / "01-trend-hunter.json").write_text(json.dumps({"topics": [wnl_topic([])]}))
        assert [t["topic_id"] for t in cpf.hunter_topics(tmp)] == ["lf-2026-10-05-003"]
    assert cpf.hunter_topics(None) is None


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
