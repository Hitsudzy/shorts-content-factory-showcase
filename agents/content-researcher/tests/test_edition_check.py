#!/usr/bin/env python3
"""CF-0812: the probe's article has to be the edition the news is about.

The three cases that reached batches (see `scripts/edition_check.py`):
`Tesla Roadster` -> `Tesla Roadster (first generation)` for the new car,
`The Scarab` (2027) -> `The Scarab (1999 film)` whose prose names 2027 twice,
`Skyman: Man of Tomorrow` (2027) -> the parent hop to `Skyman (2025
film)`. And the articles that must still be taken: an unqualified title, a
`(TV series)` for the series the news is about, a `(2025 film)` the news
names.

NOTHING HERE TOUCHES THE NETWORK - the transport below answers from
dictionaries built in this file.
"""
import io
import json
import sys
import urllib.parse
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import edition_check as ec          # noqa: E402
import fact_probe as fp             # noqa: E402
import production_facts as pf       # noqa: E402
import wikipedia_api as wapi        # noqa: E402

NOW = 2026
# Two cited sentences a fact can come out of; `{y}` is the year the prose is
# about, so an article's "newest year" is whatever the test says it is.
PROSE = ("{t} is a work.\n\n== Production ==\n"
         "Filming took place in Morocco over 92 days in {y}, with a budget of "
         "$80 million.<ref>{{{{cite web|url=https://variety.com/a|title=a|date={y}-05-01}}}}</ref> "
         "The crew built 14 full-scale sets at Shepperton Studios in {y}."
         "<ref>{{{{cite web|url=https://deadline.com/b|title=b}}}}</ref>\n")


def page(title, year, extra=""):
    return {"content_model": "wikitext", "id": abs(hash(title)) % 10**6,
            "key": title.replace(" ", "_"),
            "latest": {"id": 1, "timestamp": "2026-10-01T00:00:00Z"},
            "license": {"title": "CC BY-SA 4.0", "url": "https://creativecommons.org/"},
            "title": title, "source": PROSE.format(t=title, y=year) + extra}


class Stand:
    """Search answers by query, pages by title; `asked` is every path."""

    def __init__(self, searches, pages):
        self.searches, self.pages, self.asked = searches, pages, []

    def __call__(self, url, headers, timeout=None):
        path = url[len(wapi.API_BASE):]
        self.asked.append(path)
        if path.startswith("/search"):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(path).query)["q"][0]
            hits = [{"key": t.replace(" ", "_"), "title": t, "id": i}
                    for i, t in enumerate(self.searches.get(query, []))]
            return wapi.HttpResponse(200, json.dumps({"pages": hits}), {})
        title = urllib.parse.unquote(path[len("/page/"):]).replace("_", " ")
        if title in self.pages:
            return wapi.HttpResponse(200, json.dumps(self.pages[title]), {})
        return wapi.HttpResponse(404, json.dumps({"errorKey": "rest-nonexistent-title"}), {})


def client(searches, pages):
    stand = Stand(searches, {p["title"]: p for p in pages})
    return wapi.WikipediaClient(transport=stand, sleep=lambda _s: None), stand


ROADSTER_1 = page("Tesla Roadster (first generation)", 2010,
                  " Production ended in 2012. In 2012 the last car left. In 2018 one went "
                  "to space; in 2018 it passed Mars. In November 2023, a note.")
ROADSTER_2 = page("Tesla Roadster (second generation)", 2026,
                  " Deliveries are planned for 2026. It was shown in 2025 and again in 2025.")
MUMMY_1999 = page("The Scarab (1999 film)", 1998,
                  " A fourth film is planned for 2027. The 2027 film reunites the cast.")
SKYMAN_2025 = page("Skyman (2025 film)", 2024)
ROADSTER_NEWS = "Wired explains how Tesla made its new 230-mph car 'fly'."


def lookup(name, searches, pages, **kw):
    c, stand = client(searches, pages)
    kw.setdefault("now_year", NOW)
    return pf.find_production_facts(name, client=c, limit=1, **kw), stand


# ------------------------------------------------------- the three refusals

def test_the_new_roadster_is_not_the_first_generation_car():
    result, _ = lookup("Tesla Roadster", {"Tesla Roadster": [ROADSTER_1["title"]]},
                       [ROADSTER_1], news=ROADSTER_NEWS)
    assert result["status"] == pf.STATUS_WRONG_ARTICLE
    assert result["article"]["title"] == "Tesla Roadster (first generation)"
    check = result["article_check"]
    assert check["mismatch"] == "edition"
    assert "'first generation'" in check["detail"] and "2018" in check["detail"]
    assert result["candidates"] == []


def test_the_resolver_reads_on_to_the_edition_the_news_is_about():
    result, stand = lookup("Tesla Roadster",
                           {"Tesla Roadster": [ROADSTER_1["title"], ROADSTER_2["title"]]},
                           [ROADSTER_1, ROADSTER_2], news=ROADSTER_NEWS)
    assert result["status"] == pf.STATUS_OK
    assert result["article"]["title"] == "Tesla Roadster (second generation)"
    assert result["candidates"]
    # both pages read inside the standing ceiling, nothing else asked
    assert len([p for p in stand.asked if p.startswith("/page/")]) == 2


def test_the_scarab_of_2027_is_not_the_1999_film_although_it_names_2027_twice():
    result, _ = lookup("The Scarab", {"The Scarab 2027": [MUMMY_1999["title"]]},
                       [MUMMY_1999], year=2027, work_type="film")
    assert result["status"] == pf.STATUS_WRONG_ARTICLE
    assert result["article_check"]["mismatch"] == "edition"
    assert "about 2027" in result["article_check"]["detail"]


def test_a_sequel_named_in_the_news_refuses_the_old_film_without_a_year():
    result, _ = lookup("The Scarab", {"The Scarab": [MUMMY_1999["title"]]}, [MUMMY_1999],
                       work_type="film", now_year=2000,
                       news="Example Pictures sets a sequel to The Scarab with the original cast")
    assert result["status"] == pf.STATUS_WRONG_ARTICLE
    assert "new installment" in result["article_check"]["detail"]


def test_an_old_edition_nothing_names_is_refused_even_with_no_year_and_no_news():
    result, _ = lookup("The Scarab", {"The Scarab": [MUMMY_1999["title"]]}, [MUMMY_1999],
                       work_type="film")
    assert result["status"] == pf.STATUS_WRONG_ARTICLE
    assert "older than 2025" in result["article_check"]["detail"]


def test_the_parent_hop_does_not_borrow_from_another_film():
    result, _ = lookup("Skyman: Man of Tomorrow",
                       {"Skyman": [SKYMAN_2025["title"]]}, [SKYMAN_2025],
                       year=2027, work_type="film")
    assert result["status"] == pf.STATUS_WRONG_ARTICLE
    assert result["parent_work"] == "Skyman (2025 film)"
    assert result["article_check"]["mismatch"] == "edition"


# ---------------------------------------------------- what is still taken

def test_an_unqualified_article_is_the_thing_itself():
    bunker = page("Bunker", 2019)
    result, _ = lookup("Bunker", {"Bunker": ["Bunker"]}, [bunker])
    assert result["status"] == pf.STATUS_OK
    assert result["article_check"]["mismatch"] is None


def test_a_tv_series_article_is_the_series_the_news_is_about():
    rennick = page("Rennick (TV series)", 2021)
    result, _ = lookup("Rennick", {"Rennick": ["Rennick (TV series)"]}, [rennick],
                       work_type="tv_series", news="Rennick season 4 starts filming")
    assert result["status"] == pf.STATUS_OK
    assert result["article"]["title"] == "Rennick (TV series)"


def test_a_film_of_the_year_the_news_names_is_taken():
    result, _ = lookup("Skyman", {"Skyman": [SKYMAN_2025["title"]]}, [SKYMAN_2025],
                       work_type="film", news="Skyman (2025) hits Example Max this week",
                       now_year=2030)
    assert result["status"] == pf.STATUS_OK
    assert result["article"]["title"] == "Skyman (2025 film)"


def test_a_film_of_the_topics_own_year_is_taken():
    result, _ = lookup("Skyman", {"Skyman 2025": [SKYMAN_2025["title"]]},
                       [SKYMAN_2025], year=2025, work_type="film")
    assert result["status"] == pf.STATUS_OK


def test_a_current_film_with_no_year_and_no_sequel_is_taken():
    result, _ = lookup("Skyman", {"Skyman": [SKYMAN_2025["title"]]}, [SKYMAN_2025],
                       work_type="film", news="A new trailer for Skyman is out")
    assert result["status"] == pf.STATUS_OK


# ------------------------------------------------------------ the predicate

def test_markers_are_read_the_way_the_hunter_reads_them():
    subject = ec.subject_of("Tesla Roadster", news="the first-generation car", now_year=NOW)
    assert ec.other_edition("Tesla Roadster (first generation)", "", subject) is None
    subject = ec.subject_of("Pixel", news="Google's phone", now_year=NOW)
    record = ec.other_edition("Pixel (gen 2)", "Released in 2017. In 2017 ...", subject)
    assert record and record["unnamed"] == ["gen 2"]
    for title in ("Gemini (language model)", "Fallout (American TV series)", "Sandfall"):
        assert ec.other_edition(title, "", subject) is None


def test_footnote_dates_do_not_make_an_old_article_current():
    wikitext = ("It was sold from 2008 to 2012, and in 2012 it ended."
                "<ref>{{cite web|access-date=2026-01-01|date=2026-01-01}}</ref>")
    subject = ec.subject_of("Tesla Roadster", now_year=NOW)
    assert ec.other_edition("Tesla Roadster (first generation)", wikitext, subject)


def test_the_news_of_a_batch_topic_is_its_scenes_and_headlines():
    topic = {"title_ref": {"name": "Tesla Roadster"}, "title": "New Roadster flies",
             "scenes": [{"description": ROADSTER_NEWS}],
             "evidence": {"rss_links": [{"title": "Tesla shows the Roadster", "url": "u"}]},
             "support_text": [{"kind": "work_article", "text": "first generation 2008"}]}
    news = ec.news_of_topic(topic)
    assert "230-mph" in news and "Tesla shows the Roadster" in news and "New Roadster" in news
    assert "first generation" not in news       # the article is never the news


# ------------------------------------------------------------- the probe

def test_the_probe_answers_wrong_article_with_the_reason_and_the_same_keys():
    c, _ = client({"Tesla Roadster": [ROADSTER_1["title"]]}, [ROADSTER_1])
    out = io.StringIO()
    stdin = sys.stdin
    sys.stdin = io.StringIO(json.dumps([{"topic_id": "t-5", "name": "Tesla Roadster",
                                         "news": [ROADSTER_NEWS]}]))
    try:
        code = fp.main(["--topics", "-"], client=c, out=out)
    finally:
        sys.stdin = stdin
    assert code == 0
    probe = json.loads(out.getvalue())["probes"][0]
    assert probe["outcome"] == "wrong_article" and probe["usable"] is False
    assert probe["article"] == "Tesla Roadster (first generation)"
    assert "another edition" in probe["detail"]
    assert sorted(probe) == ["article", "article_url", "asked", "candidates", "detail",
                             "has_fact", "outcome", "parent_work", "requests", "topic_id",
                             "usable"]
    assert "news" not in probe["asked"]


def test_the_probe_reads_a_batchs_news_off_the_topic():
    batch = {"topics": [{"topic_id": "t-9", "title_ref": {"name": "Skyman", "type": "film"},
                         "scenes": [{"description": "Skyman (2025) streams now"}]}]}
    topics = fp._from_batch_payload(batch)
    assert topics[0]["news"] == "Skyman (2025) streams now"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    failed = 0
    for test in TESTS:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:                      # noqa: BLE001
            failed += 1
            print(f"FAIL {test.__name__}: {exc!r}")
    print(f"{len(TESTS) - failed}/{len(TESTS)} passed")
    sys.exit(1 if failed else 0)
