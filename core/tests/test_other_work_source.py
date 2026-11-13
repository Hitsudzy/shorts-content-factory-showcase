#!/usr/bin/env python3
"""CF-0927: `shared/other_work_source.py` - the frame judge's copy of
trend-hunter's CF-0924 rule: a shot whose upload's title is about another
work is not the screen-work topic's own footage, official channel or not.

Titles are the ones of Reel 2026-11-08T1117Z (Jon Marrow cut from Example Pictures's
Karōshi trailer) and of CF-0924's own config sightings; no batch, no network.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "shared"))

import other_work_source as ow                                       # noqa: E402

WICK = {"name": "Jon Marrow", "kind": "work", "type": "film"}
ODYSSEY = {"name": "The Long Voyage", "kind": "work", "type": "film"}
KAROSHI = "Karōshi (2027) Official Trailer - Teo Yoo, Isabel May, Giancarlo Esposito, Cynthia Erivo"


def up(title, channel="Example Pictures", origin="official", **extra):
    return dict({"video_id": "jQHoAsDcjVU", "title": title, "channel_title": channel,
                 "origin": origin}, **extra)


def test_the_official_upload_of_another_film_is_another_work():
    """08.11: the whole Jon Marrow Short was Example Pictures's Karōshi trailer."""
    hit = ow.check(up(KAROSHI), WICK)
    assert hit["branch"] == "official_other_work" and hit["title_subject"] == "Karōshi"
    assert (hit["mismatch"], hit["rule"], hit["work"]) == ("work", ow.RULE, "Jon Marrow")
    assert "Karōshi" in hit["why"] and "Jon Marrow" in hit["why"]


def test_a_title_that_names_the_work_only_as_a_credit_is_another_work_whatever_the_origin():
    hit = ow.check(up("Karōshi Rilis Trailer Perdana, Film Baru dari Produser Jon Marrow",
                      channel="The Opinion of Generations ", origin=None), WICK)
    assert hit["branch"] == "credit" and hit["title_subject"].startswith("Karōshi")
    hit = ow.check(up("From the producer of Jon Marrow: Karōshi | Official Trailer"), WICK)
    assert hit["branch"] == "credit" and hit["title_subject"] == "Karōshi"
    assert ow.check(up("Resident Dread – Official Teaser Trailer. From Zach Cregger, director "
                       "of Weapons and Barbarian."),
                    {"name": "Resident Dread", "kind": "work", "type": "film"}) is None, \
        "a title that names its own work first and credits others is the work"


def test_the_works_own_official_trailer_stays_the_work():
    for title in ("Jon Marrow: Chapter 4 – Official Trailer",
                  "JON MARROW: CHAPTER 4 (2023) Official Trailer",
                  "Official Trailer 2 | Example Pictures",          # a generic label is not another work
                  "カロウシ 予告編"):                           # another script: unknown is not other
        assert ow.check(up(title), WICK) is None, title
    assert ow.check(up("Official Trailer", channel="Jon Marrow"), WICK) is None, \
        "the work's own channel"


def test_the_work_under_its_directors_name_is_the_work():
    for title in ("A Christopher Nolan Film | Official Trailer",
                  "From Christopher Nolan | Official Teaser",
                  "Christopher Nolan's The Long Voyage | Official Trailer"):
        assert ow.check(up(title, channel="Example Pictures"), ODYSSEY) is None, title


def test_only_a_screen_work_and_only_an_official_head_are_read():
    assert ow.check(up("The new iPad mini", channel="Apple"),
                    {"name": "Apple Intelligence", "kind": "work", "type": "product"}) is None
    assert ow.check(up(KAROSHI), {"name": "Artemis II", "type": "mission"}) is None
    assert ow.check(up("Keanu Reeves on set | Interview", channel="Fan", origin=None), WICK) is None, \
        "an unofficial upload not naming the work is CF-0924's work_not_in_title upstream"
    assert ow.check(up(""), WICK) is None and ow.check(None, WICK) is None


def test_the_trend_hunters_own_flag_is_taken_as_it_is():
    hit = ow.check(up("whatever"), WICK, ready_subject="Karōshi")
    assert hit["branch"] == "trend_hunter" and hit["title_subject"] == "Karōshi"


def test_the_forms_of_a_work_are_the_trend_hunters():
    assert ow.work_forms(WICK) == ["jon marrow", "jonmarrow"]
    assert ow.work_forms({"name": "Vanguards: Doomsday"})[:3] == ["vanguards doomsday", "vanguards",
                                                                 "doomsday"]
    assert "odyssey" in ow.work_forms(ODYSSEY)
    assert ow.work_forms({"name": "Everyday Sorcery 2"})[:2] == ["everyday sorcery 2", "everyday sorcery"]


if __name__ == "__main__":
    import inspect
    fns = [f for n, f in sorted(globals().items()) if n.startswith("test_") and inspect.isfunction(f)]
    for f in fns:
        f()
        print("ok", f.__name__)
    print(f"{len(fns)}/{len(fns)} passed")
