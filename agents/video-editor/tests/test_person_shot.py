#!/usr/bin/env python3
"""CF-0879: a block that names person X does not take a close face of Y.

Stand-ins frozen out of two batches - nothing here reads the live tree:

* wicker 0841Z (`pipeline/example-film/2026-10-26T0841Z`): under "Four. Peter
  Dinklage is the basket weaver" stood `ob-KN-uRkB0:7`, a close face from
  "Wicker Co-Stars Olivia Colman and Alexander Skarsgård Watch Early Career
  Clips Together | BAFTA" (Skarsgård);
* the-gilded-age 0836Z (`2026-10-27T0836Z`): under "Then Carrie Coon was
  cast as Bertha Russell" a lone mustached man; under "Fellowes called
  writing ..." an interview of a blonde woman.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS = AGENT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import person_shot as ps  # noqa: E402
import frame_judge_pack as pack  # noqa: E402

# ----------------------------------------------------------------- stand-ins
WICKER = {
    "title_ref": {"name": "Wicker", "person": None},
    "hook": "Before you watch Wicker, know this: six quick things about the film.",
    "commentary": ("Three. Olivia Colman plays that fisherwoman, and Alexander "
                   "Skarsgård plays the wicker husband. Four. Peter Dinklage is the "
                   "basket weaver, Elizabeth Debicki plays the tailor's wife, and "
                   "Richard E. Grant is the doctor."),
    "story_claims": [
        {"kind": "cast", "actor": "Olivia Colman", "character": "the Fisherwoman"},
        {"kind": "cast", "actor": "Alexander Skarsgård", "character": "the Wicker Husband"},
        {"kind": "cast", "actor": "Peter Dinklage", "character": "the Basket Weaver"},
        {"kind": "cast", "actor": "Elizabeth Debicki", "character": "the Tailor's Wife"},
        {"kind": "cast", "actor": "Richard E. Grant", "character": "the Doctor"},
    ],
    "claims": [],
}
GILDED = {
    "title_ref": {"name": "The Gilded Age", "person": None},
    "hook": ("The one detail in The Gilded Age that changes everything: in twenty "
             "twelve, Julian Fellowes said he was working on a Downton Abbey spin-off."),
    "commentary": ("Fellowes called writing The Gilded Age the fulfillment of a "
                   "personal dream. Then Carrie Coon was cast as Bertha Russell to "
                   "replace Peet because of delays caused by the COVID-19 pandemic."),
    "story_claims": [{"kind": "cast", "actor": "Carrie Coon",
                      "character": "Bertha Russell"}],
    "claims": [
        {"text": "In September twenty twelve, The Daily Telegraph reported Julian "
                 "Fellowes as saying that he was working on a spin-off prequel.",
         "support": [{"quote": "In September 2012, The Daily Telegraph reported "
                               "Julian Fellowes as saying that he was working on a "
                               "spin-off prequel of Downton Abbey."}]},
        {"text": "Then Carrie Coon was cast as Bertha Russell to replace Peet.",
         "support": [{"quote": "In April 2020, Carrie Coon was cast as Bertha Russell "
                               "to replace Peet. This caused the costuming team to "
                               "change their approach, using the way Coon presents "
                               "herself as inspiration for more metallic-colored "
                               "dresses."}]},
        {"text": "Example Network has since renewed the series.",
         "support": [{"quote": "The Daily Telegraph reported the move."}]},
    ],
}
BAFTA = ("Wicker Co-Stars Olivia Colman and Alexander Skarsgård Watch Early Career "
         "Clips Together | BAFTA")
TRAILER = "Wicker Final Trailer (2026)"
GILDED_TRAILER = "The Gilded Age Season 4 | Official Trailer | Example Max"


def _shot(description, roi="faces"):
    return {"description": description, "usable_cached": {"roi_source": roi}}


SHOTS = {
    ("ob-KN-uRkB0", 7): _shot("close-up of the man in a white polo biting his "
                              "fingernail, woman's curly hair in the foreground"),
    ("7ZOpGdJAKEk", 33): _shot("A wicker structure stands in a sunlit field.",
                               roi="saliency"),
    ("7ZOpGdJAKEk", 20): _shot("An older man in a vest dabs his mouth with a napkin "
                               "at a table.", roi="saliency"),
    ("MqRa6X31lUk", 40): _shot("A dark-haired man with a moustache in period "
                               "costume, in profile."),
    ("MqRa6X31lUk", 8): _shot("Crowded ballroom scene with dancers in period "
                              "costume.", roi="saliency"),
    ("BtecPpi4U7o", 27): _shot("Interview of a blonde woman in a blue patterned "
                               "jacket gesturing as she talks."),
}
TITLES = {"ob-KN-uRkB0": BAFTA, "7ZOpGdJAKEk": TRAILER, "MqRa6X31lUk": GILDED_TRAILER,
          "BtecPpi4U7o": "The Gilded Age | Invitation to Set | Example Max"}


def _cand(key, score):
    vid, n = key.rsplit(":", 1)
    return {"index": vid, "shot": int(n), "source": f"/pool/{vid}.mp4", "score": score}


def _screen(matches, names, people):
    return ps.screen_matches(
        matches, names, lambda c: SHOTS.get((c["index"], c["shot"])),
        lambda c: TITLES.get(c["index"]), people, 0.22)


# --------------------------------------------------------------- the people
def test_the_people_are_the_scripts_own_list_with_their_sex():
    w = {p["name"]: p for p in ps.script_people(WICKER)}
    assert list(w) == ["Olivia Colman", "Alexander Skarsgård", "Peter Dinklage",
                       "Elizabeth Debicki", "Richard E. Grant"], list(w)
    assert {n: p["gender"] for n, p in w.items()} == {
        "Olivia Colman": "f", "Alexander Skarsgård": "m", "Peter Dinklage": None,
        "Elizabeth Debicki": "f", "Richard E. Grant": None}
    assert all(p["from"] == "cast" for p in w.values())


def test_claims_bring_the_quoted_and_the_cast_never_an_outlet():
    g = {p["name"]: p for p in ps.script_people(GILDED)}
    assert list(g) == ["Carrie Coon", "Julian Fellowes"], list(g)
    assert g["Carrie Coon"]["gender"] == "f"          # "presents herself"
    assert g["Julian Fellowes"]["gender"] == "m"      # "said he was working"
    assert g["Julian Fellowes"]["from"] == "claims"
    # "The Daily Telegraph reported" is an outlet; "Then Carrie Coon" loses "Then"
    assert ps._clean_name("The Daily Telegraph") is None
    assert ps._clean_name("Then Carrie Coon") == "Carrie Coon"
    assert ps._clean_name("CEO Dario Amodei") == "Dario Amodei"


def test_names_are_read_by_the_list_not_by_capital_letters():
    people = ps.script_people(WICKER)
    assert ps.names_in("Four. Peter Dinklage is the basket weaver,", people) == [
        "Peter Dinklage"]
    # whisper drops the accent; a lone surname is enough when capitalised
    assert ps.names_in("and Alexander Skarsgard plays", people) == ["Alexander Skarsgård"]
    assert ps.names_in("Grant is the doctor", people) == ["Richard E. Grant"]
    assert ps.names_in("a grant from the studio", people) == []
    # a capitalised stranger is nobody of the list
    assert ps.names_in("Ursula Wills wrote The Wicker Husband", people) == []


def test_a_single_person_shot_and_its_sex():
    assert ps.single_person(SHOTS[("ob-KN-uRkB0", 7)])
    assert ps.single_person(SHOTS[("7ZOpGdJAKEk", 20)])        # leads with one man
    assert not ps.single_person(SHOTS[("7ZOpGdJAKEk", 33)])    # a thing
    assert not ps.single_person(SHOTS[("MqRa6X31lUk", 8)])     # a crowd
    assert not ps.single_person(_shot("Two men sit across a table."))
    # a set with two people is no face in front, even framed on faces
    # (gilded-age 0836Z block 1, measured: BtecPpi4U7o:4)
    assert not ps.single_person(_shot("Behind the scenes, a camera operator and a "
                                      "monitor while an actress in a period gown acts"))
    # ... while a close-up says so in its own words (wicker 0841Z, ob-KN-uRkB0:7)
    assert ps.single_person(_shot("close-up of the man biting his fingernail, "
                                  "woman's curly hair in the foreground", roi="saliency"))
    assert ps.description_sex(SHOTS[("MqRa6X31lUk", 40)]["description"]) == "m"
    assert ps.description_sex(SHOTS[("BtecPpi4U7o", 27)]["description"]) == "f"
    assert ps.description_sex(SHOTS[("ob-KN-uRkB0", 7)]["description"]) is None


# ------------------------------------------------------------- the two cases
def test_wicker_skarsgard_interview_is_not_placed_under_dinklage():
    people = ps.script_people(WICKER)
    matches = [{"phrase": "a basket weaver at work",
                "candidates": [_cand("ob-KN-uRkB0:7", 0.31),
                               _cand("7ZOpGdJAKEk:33", 0.25)]}]
    refused, kept = _screen(matches, [["Peter Dinklage"]], people)
    assert [c["shot"] for c in matches[0]["candidates"]] == [33], matches
    assert [r["shot"] for r in refused] == [7] and not kept
    assert "Olivia Colman, Alexander Skarsgård's, not Peter Dinklage's" in refused[0]["reason"]
    assert "CF-0879" in refused[0]["reason"]


def test_the_same_interview_is_kept_under_the_names_its_title_carries():
    people = ps.script_people(WICKER)
    matches = [{"phrase": "the two stars",
                "candidates": [_cand("ob-KN-uRkB0:7", 0.31),
                               _cand("7ZOpGdJAKEk:33", 0.25)]}]
    refused, _ = _screen(matches, [["Olivia Colman", "Alexander Skarsgård"]], people)
    assert refused == [] and len(matches[0]["candidates"]) == 2


def test_no_replacement_over_the_floor_keeps_the_face_and_says_so():
    people = ps.script_people(WICKER)
    matches = [{"phrase": "a basket weaver at work",
                "candidates": [_cand("ob-KN-uRkB0:7", 0.31),
                               _cand("7ZOpGdJAKEk:33", 0.18)]}]   # under 0.22
    refused, kept = _screen(matches, [["Peter Dinklage"]], people)
    assert refused == [] and len(matches[0]["candidates"]) == 2
    assert kept == [{"phrase": "a basket weaver at work",
                     "names_person": ["Peter Dinklage"],
                     "shots": [7]}], kept


def test_gilded_age_lone_man_is_not_placed_under_carrie_coon():
    people = ps.script_people(GILDED)
    matches = [{"phrase": "a couple in white costume",
                "candidates": [_cand("MqRa6X31lUk:40", 0.30),
                               _cand("MqRa6X31lUk:8", 0.24)]},
               {"phrase": "a writer at his desk",
                "candidates": [_cand("BtecPpi4U7o:27", 0.30),
                               _cand("MqRa6X31lUk:8", 0.23)]}]
    refused, kept = _screen(matches, [["Carrie Coon"], ["Julian Fellowes"]], people)
    assert [c["shot"] for c in matches[0]["candidates"]] == [8]
    assert [c["shot"] for c in matches[1]["candidates"]] == [8]
    assert "the description shows a man and Carrie Coon is a woman" in refused[0]["reason"]
    assert "the description shows a woman and Julian Fellowes is a man" in refused[1]["reason"]
    assert not kept


def test_a_block_naming_two_people_takes_a_shot_of_either():
    people = ps.script_people(WICKER)
    shot = SHOTS[("7ZOpGdJAKEk", 20)]           # an older man
    assert ps.risk(shot, TRAILER, ["Elizabeth Debicki"], people)
    assert ps.risk(shot, TRAILER, ["Elizabeth Debicki", "Richard E. Grant"], people) == []
    assert ps.risk(shot, TRAILER, [], people) == []


def test_unnamed_anchors_are_never_screened():
    people = ps.script_people(WICKER)
    matches = [{"phrase": "x", "candidates": [_cand("ob-KN-uRkB0:7", 0.31),
                                              _cand("7ZOpGdJAKEk:33", 0.25)]}]
    assert _screen(matches, [[]], people) == ([], [])
    assert len(matches[0]["candidates"]) == 2


# ------------------------------------------------- the storyboard and the plan
WORDS = [{"word": w, "start": i * 0.5, "end": i * 0.5 + 0.5} for i, w in
         enumerate("Four. Peter Dinklage is the basket weaver, Elizabeth Debicki "
                   "plays the tailor's wife".split())]


def _by_key(vid, n):
    return SHOTS.get((vid, int(n)))


def test_block_risks_stamp_the_names_and_find_the_foreign_face():
    people = ps.script_people(WICKER)
    blocks = [{"_start": 0.0, "_end": 3.5, "shot": "ob-KN-uRkB0:7"},
              {"_start": 3.5, "_end": 6.0, "shot": "7ZOpGdJAKEk:33",
               "asset": {"kind": "sequence",
                         "cuts": [{"shot": "7ZOpGdJAKEk:33"}, {"shot": "7ZOpGdJAKEk:20"}]}},
              {"_start": 6.0, "_end": 9.0, "shot": "7ZOpGdJAKEk:33"}]
    risky = ps.block_risks(blocks, WORDS, people, _by_key, TITLES.get)
    assert [b[ps.FIELD] for b in blocks] == [
        ["Peter Dinklage"], ["Elizabeth Debicki"], []], blocks
    assert [(r["block"], r["shot"]) for r in risky] == [
        (0, "ob-KN-uRkB0:7"), (1, "7ZOpGdJAKEk:20")], risky
    rec = ps.record(people, [], [], risky)
    assert rec["mode"] == "measure" and rec["task"] == "CF-0879"


def test_the_plan_carries_the_names_and_warns_without_a_price():
    import build_render_plan as brp  # noqa: E402 - imported here, it is heavy
    assert brp.carry_rhythm({"shot": "a:1", ps.FIELD: ["Peter Dinklage"]})[ps.FIELD] == [
        "Peter Dinklage"]
    risky = [{"block": 0, "names_person": ["Peter Dinklage"], "shot": "ob-KN-uRkB0:7",
              "reasons": ["Peter Dinklage: its source is titled ..."]},
             {"block": 1, "names_person": ["Elizabeth Debicki"], "shot": "7ZOpGdJAKEk:20",
              "reasons": ["..."]}]
    story = {"script_id": "s1", ps.RECORD: ps.record([], [], [], risky)}
    # block 1 was re-cut since: it no longer shows the measured shot
    blocks = [{"shot": "ob-KN-uRkB0:7", "asset": {"kind": "clip"}},
              {"shot": "7ZOpGdJAKEk:33", "asset": {"kind": "clip"}}]

    class Args:
        script_id = "s1"
        output = "/nonexistent/plan.json"
    warnings = []
    rec = brp.person_shot_warnings(Args, story, blocks, warnings)
    assert rec is story[ps.RECORD]
    assert len(warnings) == 1, warnings
    w = warnings[0]
    assert (w["gate"], w["severity"], w["mode"], w["block"]) == (
        "person_shot_risk", "warn", "measure", 0)
    assert "reason_code" not in w       # a measured rule, never a funnel loss
    assert brp.person_shot_warnings(Args, {}, blocks, []) is None


def test_the_judge_pack_names_the_people_of_every_judged_entry():
    words = [{"word": w, "start": i * 1.0, "end": i * 1.0 + 1.0} for i, w in
             enumerate("Peter Dinklage weaves and Carrie Coon sings".split())]
    insert = {"kind": "proof", "proof_id": "p1", "start_s": 3.0, "end_s": 6.0,
              "capture_path": "/w/p.png", "source_url": "https://x"}
    plan = {"words": words, "blocks": [
        {"start": 0.0, "end": 6.0, "asset": {"kind": "clip"}, "shot": "a:1",
         ps.FIELD: ["Peter Dinklage", "Carrie Coon"], "insert": insert},
        {"start": 6.0, "end": 7.0, "asset": {"kind": "procedural"}}],
        ps.RECORD: {"people": [{"name": "Peter Dinklage"}, {"name": "Carrie Coon"}]},
        "proof": {"proofs": [{"proof_id": "p1"}]}}
    entries = pack.entries_for(plan, 7.0)
    by_id = {e["id"]: e for e in entries}
    assert by_id["block-0"]["named_people"] == ["Peter Dinklage", "Carrie Coon"]
    assert by_id["block-0-proof"]["named_people"] == ["Carrie Coon"], by_id
    assert "named_people" not in by_id["block-1"]           # not judged
    # a plan from before CF-0879: judged entries say nobody
    old = {"words": words, "blocks": [{"start": 0.0, "end": 3.0,
                                       "asset": {"kind": "clip"}, "shot": "a:1"}]}
    assert pack.entries_for(old, 3.0)[0]["named_people"] == []


def test_main_screens_before_any_rung_and_records_it():
    src = (SCRIPTS / "resolve_anchors.py").read_text()
    main = src.split("def main():")[1]
    screen = main.index("person_shot.screen_matches(")
    assert main.index("event_footage.screen_matches(") < screen
    assert screen < main.index("rhythm.normalize_order(load_order(")
    assert screen < main.index("build_split_opening(")
    assert "rejected_candidates.extend(person_refused)" in main
    assert main.index("person_shot.block_risks(") < main.index("json.dump(out,")
    assert "person_shot.RECORD: person_shot.record(" in main


# ------------------------------------------- CF-0913: people behind the camera
# Stand-ins frozen out of the Reel batches 29.10-01.11, where the frame judge
# wrote `contradicts`/`person` under a name the editor's list did not hold:
# klara-and-the-sun 0832Z block 2 ("Taika Waititi directed Klara and the Sun."
# over a young cast member from "Klara and the Sun (2026) | Official Trailer"),
# pride-and-prejudice 1025Z ("written by Dolly Alderton" over an actress in
# costume), sandfall-part-three 0841Z (Linus Sandgren, director of photography,
# over a lead's close-up), the-famine-trials 0841Z (casting directors).
KLARA = {
    "title_ref": {"name": "Klara and the Sun", "person": None},
    "hook": "Klara and the Sun opened at number two this weekend.",
    "commentary": "Taika Waititi directed Klara and the Sun. It made twelve million.",
    "story_claims": [],
    "claims": [{"text": "Taika Waititi directed Klara and the Sun.",
                "support": [{"quote": "directed by Taika Waititi"}]}],
}
KLARA_TRAILER = "Klara and the Sun (2026) | Official Trailer | ALMI"
CREW_SHOTS = {
    ("kjJI0wHxXHM", 6): _shot("A smiling young man in a grey uniform shirt "
                              "speaking."),
    ("kjJI0wHxXHM", 2): _shot("A sunlit city street seen from a shop window.",
                              roi="saliency"),
    ("wtW1interv", 3): _shot("Interview of a man with a moustache in a dark "
                             "shirt talking about the film."),
}
CREW_TITLES = {"kjJI0wHxXHM": KLARA_TRAILER,
               "wtW1interv": "Taika Waititi on directing Klara and the Sun"}


def _crew_screen(matches, names, people):
    return ps.screen_matches(
        matches, names, lambda c: CREW_SHOTS.get((c["index"], c["shot"])),
        lambda c: CREW_TITLES.get(c["index"]), people, 0.22)


def _roles(script):
    return {p["name"]: p["role"] for p in ps.script_people(script)}


def _script(*texts, cast=()):
    return {"title_ref": {"name": "X", "person": None}, "hook": "", "payoff": "",
            "commentary": " ".join(texts),
            "story_claims": [{"kind": "cast", "actor": a, "character": c}
                             for a, c in cast],
            "claims": []}


def test_a_director_is_on_the_list_as_crew():
    assert _roles(KLARA) == {"Taika Waititi": "crew"}, _roles(KLARA)


def test_the_jobs_behind_the_camera_are_read_in_both_orders():
    r = _roles(_script(
        "Terry Matalas created it, and he serves as showrunner and a director.",
        "ExampleStream's Pride and Prejudice is written by Dolly Alderton.",
        "Two. Linus Sandgren replaced Greig Fraser as director of photography.",
        "It was co-written, directed, and co-produced by Alejandro González Iñárritu.",
        "Casting directors Debra Zane and Dylan Jury began casting in December."))
    for name in ("Terry Matalas", "Dolly Alderton", "Linus Sandgren",
                 "Alejandro González Iñárritu", "Debra Zane", "Dylan Jury"):
        assert r.get(name) == "crew", (name, r)
    assert "Two. Linus Sandgren" not in r, r


def test_an_actor_who_also_directs_is_cast_not_crew():
    r = _roles(_script("Sacha Baron Cohen wrote, produced, directed and stars in "
                       "the film as Ali G."))
    assert r == {"Sacha Baron Cohen": "cast"}, r
    r = _roles(_script("Taika Waititi directed it.",
                       cast=[("Taika Waititi", "Hitler")]))
    assert r == {"Taika Waititi": "cast"}, r


def test_a_comma_ends_the_list_of_a_job():
    # famine-trials 1033Z: Jennifer Lawrence is no director
    r = _roles(_script('Collaborating with director Francis Lawrence, Jennifer '
                       'Lawrence said: "Maybe we already have."'))
    assert r.get("Francis Lawrence") == "crew", r
    assert r.get("Jennifer Lawrence") is None, r


def test_a_shared_surname_is_not_the_same_person():
    people = [{"name": "Jennifer Lawrence", "role": None, "gender": None},
              {"name": "Francis Lawrence", "role": "crew", "gender": None}]
    # "Lawrence" names both; the face may be hers, so nothing is foreign
    shot = _shot("A blonde woman in a sequined fascinator.")
    assert ps.risk(shot, "Featurette", ["Jennifer Lawrence", "Francis Lawrence"],
                   people) == []


def test_klara_trailer_face_is_not_placed_under_the_director():
    people = ps.script_people(KLARA)
    matches = [{"phrase": "a young man in a grey uniform",
                "candidates": [_cand("kjJI0wHxXHM:6", 0.23),
                               _cand("kjJI0wHxXHM:2", 0.22)]}]
    refused, kept = _crew_screen(matches, [["Taika Waititi"]], people)
    assert [c["shot"] for c in matches[0]["candidates"]] == [2], matches
    assert [r["shot"] for r in refused] == [6] and not kept
    assert "behind the camera" in refused[0]["reason"]
    assert "CF-0913" in refused[0]["reason"]


def test_the_directors_own_interview_stays_under_the_director():
    people = ps.script_people(KLARA)
    matches = [{"phrase": "the director talks",
                "candidates": [_cand("wtW1interv:3", 0.30),
                               _cand("kjJI0wHxXHM:2", 0.24)]}]
    refused, _ = _crew_screen(matches, [["Taika Waititi"]], people)
    assert refused == [] and len(matches[0]["candidates"]) == 2


def test_no_replacement_keeps_the_trailer_face_and_measures_it():
    people = ps.script_people(KLARA)
    matches = [{"phrase": "a young man in a grey uniform",
                "candidates": [_cand("kjJI0wHxXHM:6", 0.23)]}]
    refused, kept = _crew_screen(matches, [["Taika Waititi"]], people)
    assert refused == [] and kept[0]["shots"] == [6], kept


def test_cast_names_keep_their_trailer_faces():
    people = ps.script_people(_script("Emma Corrin plays Elizabeth Bennet.",
                                      cast=[("Emma Corrin", "Elizabeth Bennet")]))
    shot = _shot("A freckled curly-haired woman in period costume.")
    assert ps.risk(shot, "Pride and Prejudice | Official Trailer | ExampleStream",
                   ["Emma Corrin"], people) == []


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
