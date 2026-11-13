#!/usr/bin/env python3
"""CF-0344: the source sieve judges a thin-pool supplement source by its entity.

A supplement source (CF-0338, `fetched[].supplement.entity`) is fetched *for*
an entity of the topic - for everyday-sorcery-2 that is the trailer of The Lost
City (Sandra Birch's other film), a scene of Ocean's 8, a Tonight Show
interview with Nora Kingsley. Every one of them is somebody else's work, so the
describer flags its shots `on_topic: false` honestly, and the CF-0299 sieve
would refuse all of them as `source_foreign` - the supplement cut by the sieve.

The rule pinned here: for a supplement source a shot is off topic only when it
is neither the topic's work nor shows the entity (the `shows_entity` flag, or
the description naming it). A frame of Ocean's 8 without Bullock still counts
against the source. An ordinary source is judged exactly as before.

No pytest dependency - plain asserts, run directly.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import ingest_batch as ib           # noqa: E402
import shot_schema                  # noqa: E402
import source_sieve as sv           # noqa: E402

TOPIC = "everyday-sorcery-2"


def index(descriptions, on_topic=False, burned=(), shows=None):
    """A fully flagged shots.json, one shot per description."""
    shots = []
    for i, d in enumerate(descriptions):
        s = {"index": i, "start": float(i), "end": float(i) + 1.0,
             "description": d, shot_schema.BURNED_TEXT: i in set(burned),
             shot_schema.ON_TOPIC: on_topic}
        if shows is not None:
            s[shot_schema.SHOWS_ENTITY] = i in set(shows)
        shots.append(s)
    return {"source": "/tmp/x.mp4", "shots": shots}


LOST_CITY = index([
    "Sandra Birch in a sequined jumpsuit steps out of a jeep in the jungle",
    "Close-up of Bullock laughing, mud on her face",
    "Channing Tatum alone on a riverbank, shirt torn",
    "Bullock and Tatum run through tall grass",
    "Wide aerial shot of a tropical island",
])
OCEANS_8 = index([
    "Rihanna types at a laptop in a dark loft",
    "Cate Blanchett leans on a bar counter",
    "Sandra Birch walks into the Met gala in a black gown",
    "Anne Hathaway poses on the red carpet",
    "A jewellery case opens on a diamond necklace",
])


def report(sources, supplement=None):
    """A stage report holding `sources` for the topic; `supplement` maps the
    ids fetched by a supplement to their entity."""
    supplement = supplement or {}
    fetched = []
    for vid in sources:
        f = {"video_id": vid, "topic_id": TOPIC, "path": f"/tmp/{vid}.mp4"}
        if vid in supplement:
            f["supplement"] = {"reason_code": "pool_too_thin",
                               "entity": supplement[vid]}
        fetched.append(f)
    return {"batch": "/tmp/b", "sources_by_topic": {TOPIC: list(sources)},
            "fetched": fetched, "failed": [], "aliases": [],
            "skipped_topics": []}


def test_a_supplement_shot_that_shows_the_entity_is_not_off_topic():
    rec = sv.judge(LOST_CITY, entity="Sandra Birch")
    # 3 of 5 shots show Bullock; the Tatum shot and the island do not.
    assert rec["verdict"] == sv.KEPT, rec
    assert rec["off_topic"] == 2 and rec["off_topic_shots"] == [2, 4]
    assert rec["entity_shots"] == 3
    assert rec["judged_by"] == "entity" and rec["entity"] == "Sandra Birch"


def test_the_same_source_without_the_supplement_mark_is_refused_as_before():
    rec = sv.judge(LOST_CITY)
    assert rec["verdict"] == sv.REFUSED
    assert rec["reason_code"] == ib.SIEVE_FOREIGN_CODE
    assert rec["off_topic"] == 5
    assert "judged_by" not in rec and "entity" not in rec


def test_a_shot_of_the_other_work_without_the_entity_counts_against_it():
    rec = sv.judge(OCEANS_8, entity="Sandra Birch")
    # Only the Met gala shot has Bullock; four frames of Ocean's 8 without her.
    assert rec["verdict"] == sv.REFUSED, rec
    assert rec["reason_code"] == ib.SIEVE_FOREIGN_CODE
    assert rec["off_topic_shots"] == [0, 1, 3, 4]
    assert "Sandra Birch" in rec["reason"] and "CF-0344" in rec["reason"]
    assert rec["examples"][0].startswith("0: Rihanna")


def test_the_describer_s_flag_wins_over_the_description():
    # The name is in every description, but the describer says she is in
    # only one shot (a poster on a wall, say): the flag decides.
    idx = index(["Poster with Sandra Birch's name"] * 4, shows=[0])
    rec = sv.judge(idx, entity="Sandra Birch")
    assert rec["verdict"] == sv.REFUSED and rec["off_topic_shots"] == [1, 2, 3]
    idx = index(["a woman in a gown"] * 4, shows=[0, 1, 2, 3])
    assert sv.judge(idx, entity="Sandra Birch")["verdict"] == sv.KEPT


def test_a_shot_of_the_topic_s_own_work_stays_on_topic_without_the_entity():
    # The Everyday Sorcery 2 trailer itself, fetched by a supplement for Kidman:
    # a frame without her is still the topic's work.
    idx = index(["The house on the hill at night", "Kidman at a window",
                 "Crows on a fence"], on_topic=True)
    rec = sv.judge(idx, entity="Nora Kingsley")
    assert rec["verdict"] == sv.KEPT and rec["off_topic"] == 0


def test_burned_text_is_judged_the_same_on_a_supplement_source():
    idx = index(["Kidman on the Tonight Show couch"] * 4, burned=[0, 1, 2])
    rec = sv.judge(idx, entity="Nora Kingsley")
    # CF-0435: burned text no longer refuses any source whole - a supplement
    # one included; its burned shots are listed and stay out one by one.
    assert rec["verdict"] == sv.KEPT
    assert rec["burned_text_shots"] == [0, 1, 2]
    assert sv.judge(idx, entity="Nora Kingsley", burned_share=0.5)[
        "reason_code"] == ib.SIEVE_BURNED_TEXT_CODE


def test_the_name_is_matched_as_a_word():
    s = {"description": "Bullocks grazing in a field"}
    assert not shot_schema.shows_entity(s, "Sandra Birch")
    assert shot_schema.shows_entity({"description": "BULLOCK smiles"},
                                    "Sandra Birch")
    assert shot_schema.shows_entity({"description": "Bullock's grin"},
                                    "Sandra Birch")
    assert not shot_schema.shows_entity({"description": ""}, "Sandra Birch")
    assert shot_schema.entity_names({"name": "Nora Kingsley"}) == \
        ["nora kingsley", "kidman"]


def test_shows_entity_must_be_a_boolean_and_is_not_needed_for_completeness():
    bad = {"index": 3, "start": 0.0, "end": 1.0, "shows_entity": "yes"}
    assert shot_schema.shot_problems(bad) == [
        "shot 3: shows_entity must be true or false, got 'yes'"]
    c = shot_schema.sieve_counts(LOST_CITY, entity="Sandra Birch")
    assert c["complete"] and c["decided"] == 5


def test_the_report_marks_only_the_supplement_source():
    rep = report(["own", "lostcity", "oceans"],
                 supplement={"lostcity": "Sandra Birch",
                             "oceans": {"name": "Sandra Birch",
                                        "kind": "person"}})
    own = index(["Rihanna types at a laptop"] * 3)     # foreign, not a supplement
    loaded = {"own": own, "lostcity": LOST_CITY, "oceans": OCEANS_8}
    sieved = sv.sieve_report(rep, load=loaded.get)
    by = {r["video_id"]: r for r in sieved["sources"]}
    assert by["lostcity"]["verdict"] == sv.KEPT
    assert by["oceans"]["verdict"] == sv.REFUSED
    # The ordinary source's verdict is exactly the one it had before CF-0344.
    before = sv.judge(own)
    assert by["own"] == {"video_id": "own", "topic_id": TOPIC, **before}
    assert by["own"]["verdict"] == sv.REFUSED
    assert [r["video_id"] for r in sieved["refused"][TOPIC]] == ["own", "oceans"]


def test_a_kept_supplement_source_stays_in_the_pool():
    rep = report(["a", "b", "lostcity"], supplement={"lostcity": "Sandra Birch"})
    good = index(["The Owens sisters in the kitchen"] * 3, on_topic=True)
    loaded = {"a": good, "b": good, "lostcity": LOST_CITY}
    sieved = sv.sieve_report(rep, load=loaded.get)
    out = sv.apply_sieve(rep, [], {}, sieved, top_up=False, log=lambda *_: None)
    assert out["sources_by_topic"][TOPIC] == ["a", "b", "lostcity"]
    assert out["source_sieve"]["refused"] == []


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            import traceback
            traceback.print_exc()
            print(f"FAIL {t.__name__}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
