#!/usr/bin/env python3
"""CF-0828: a Wikipedia disambiguation page is not an article.

`resolve_article` used to read the bare name of a company or a planet
(`Amazon`, `Mercury`) - a page that lists meanings - as the topic's article;
its owner then found no section a fact comes out of and reported `no_section`
instead of reading the real article. Now `article_of` keeps the REST `type`
and marks the page (`disambiguation`), and `resolve_article` reads the next
candidate of the ranking, noting the page in `skipped`; when every candidate
was one the answer is None, and `skipped` is the caller's sub-reason for its
`no_article`.

Synthetic Core REST answers through a scripted transport - nothing here asks
the network or reads live data."""
import importlib.util
import json
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
WIKIPEDIA_API = ROOT / "shared" / "wikipedia" / "wikipedia_api.py"


def _load():
    spec = importlib.util.spec_from_file_location("wikipedia_api_cf0828", WIKIPEDIA_API)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


wp = _load()

DAB_TEXT = ("'''Amazon''' most often refers to:\n* [[Amazon (company)]]\n"
            "* [[Amazon River]]\n== Other uses ==\n* [[Amazons]]\n{{disambiguation}}\n")
ARTICLE_TEXT = ("'''X''' is a thing.\n== History ==\nIn 2015 it was seen.<ref>"
                "https://example.org/a</ref>\n")


class Scripted:
    """A transport answering by path: the search, a page, or 404; every URL
    asked is kept."""

    def __init__(self, search=(), pages=None):
        self.search = list(search)
        self.pages = dict(pages or {})
        self.asked = []

    def __call__(self, url, headers, timeout=None):
        self.asked.append(url)
        path = unquote(urlparse(url).path)
        if path.endswith("/search/page"):
            body = {"pages": [{"title": t} for t in self.search]}
            return wp.HttpResponse(200, json.dumps(body))
        title = path.rsplit("/page/", 1)[-1].replace("_", " ")
        if title in self.pages:
            return wp.HttpResponse(200, json.dumps(self.pages[title]))
        return wp.HttpResponse(404, json.dumps({"messageTranslations": {"en": "not found"}}))


def page(title, text=ARTICLE_TEXT, page_type=None):
    body = {"title": title, "key": title.replace(" ", "_"), "id": 1, "source": text,
            "license": {"title": "CC BY-SA 4.0"}}
    if page_type:
        body["type"] = page_type
    return body


def client_for(**kw):
    t = Scripted(**kw)
    c = wp.WikipediaClient(transport=t, min_interval=0)
    c.fake = t
    return c


def pages_asked(c):
    return [unquote(urlparse(u).path).rsplit("/page/", 1)[-1]
            for u in c.fake.asked if "/search/" not in u]


# ------------------------------------------------------------ the page itself
def test_the_template_marks_a_disambiguation_page():
    a = wp.article_of(page("Amazon", DAB_TEXT))
    assert a["disambiguation"] is True
    assert a["page_type"] is None
    assert wp.is_disambiguation(a)


def test_the_rest_type_alone_marks_it():
    a = wp.article_of(page("Mercury", "'''Mercury''' may refer to:", page_type="disambiguation"))
    assert a["page_type"] == "disambiguation"
    assert a["disambiguation"] is True


def test_the_name_kinds_of_the_template_mark_it_too():
    for template in ("{{Human name disambiguation}}", "{{Place name disambiguation|x}}",
                     "{{dab}}", "{{Disambig}}", "{{hndis|Smith, John}}", "{{geodis}}"):
        assert wp.article_of(page("X", "'''X''' may be:\n" + template))["disambiguation"], template


def test_an_ordinary_article_is_not_one():
    a = wp.article_of(page("Amazon (company)"))
    assert a["disambiguation"] is False
    assert not wp.is_disambiguation(a)


def test_an_inline_disambiguation_needed_tag_is_not_the_template():
    text = ARTICLE_TEXT + "He joined [[Mercury]]{{Disambiguation needed|date=May 2026}}.\n"
    assert wp.article_of(page("Somebody", text))["disambiguation"] is False


def test_a_hand_built_article_is_judged_by_its_wikitext():
    assert wp.is_disambiguation({"title": "Amazon", "wikitext": DAB_TEXT})
    assert wp.is_disambiguation({"title": "Amazon", "page_type": "disambiguation"})
    assert not wp.is_disambiguation(None)


# ----------------------------------------------------------- the resolver
def test_the_bare_name_gives_way_to_the_next_candidate():
    c = client_for(search=["Amazon", "Amazon (company)", "Amazon River"],
                   pages={"Amazon": page("Amazon", DAB_TEXT),
                          "Amazon (company)": page("Amazon (company)")})
    seen, skipped = [], []
    a = wp.resolve_article(c, "Amazon", work_type="company", seen=seen, skipped=skipped)
    assert a["title"] == "Amazon (company)"
    assert [x["title"] for x in seen] == ["Amazon (company)"]
    assert skipped == [{"title": "Amazon", "reason": wp.NO_ARTICLE_DISAMBIGUATION}]
    assert pages_asked(c) == ["Amazon", "Amazon_(company)"]


def test_the_rest_type_page_is_skipped_as_well():
    c = client_for(search=["Mercury", "Mercury (planet)"],
                   pages={"Mercury": page("Mercury", "'''Mercury''' may be:",
                                          page_type="disambiguation"),
                          "Mercury (planet)": page("Mercury (planet)")})
    assert wp.resolve_article(c, "Mercury")["title"] == "Mercury (planet)"


def test_accept_is_never_asked_about_a_disambiguation_page():
    c = client_for(search=["Amazon", "Amazon (company)"],
                   pages={"Amazon": page("Amazon", DAB_TEXT),
                          "Amazon (company)": page("Amazon (company)")})
    judged = []
    wp.resolve_article(c, "Amazon", accept=lambda art: judged.append(art["title"]) or False)
    assert judged == ["Amazon (company)"]


def test_the_last_article_returned_is_never_the_disambiguation_page():
    # The real article is read first and refused; the page after it is a
    # disambiguation - the article is what comes back, as the last one read.
    c = client_for(search=["Mercury (planet)", "Mercury"],
                   pages={"Mercury": page("Mercury", DAB_TEXT),
                          "Mercury (planet)": page("Mercury (planet)")})
    a = wp.resolve_article(c, "Mercury", accept=lambda art: False, max_reads=3)
    assert a["title"] == "Mercury (planet)"


def test_only_disambiguation_pages_is_no_article_with_the_reason():
    c = client_for(search=["Amazon", "Amazon (disambiguation)"],
                   pages={"Amazon": page("Amazon", DAB_TEXT)})
    skipped = []
    assert wp.resolve_article(c, "Amazon", skipped=skipped) is None
    assert [s["reason"] for s in skipped] == ["disambiguation"]


def test_the_disambiguation_page_counts_against_the_reads():
    c = client_for(search=["Mercury", "Mercury (planet)", "Mercury (element)"],
                   pages={"Mercury": page("Mercury", DAB_TEXT),
                          "Mercury (planet)": page("Mercury (planet)"),
                          "Mercury (element)": page("Mercury (element)")})
    wp.resolve_article(c, "Mercury", accept=lambda art: False)
    assert len(pages_asked(c)) == wp.MAX_ARTICLE_READS
    assert c.request_count <= wp.MAX_REQUESTS_PER_TITLE


def test_without_skipped_the_resolver_still_works():
    c = client_for(search=["Amazon"], pages={"Amazon": page("Amazon", DAB_TEXT)})
    assert wp.resolve_article(c, "Amazon") is None


def test_a_redirect_to_a_disambiguation_is_noted_in_skipped():
    c = client_for(search=["Planet Mercury facts"],
                   pages={"Odd name": {"title": "x", "key": "x", "source": "#REDIRECT [[Mercury]]",
                                       "redirect_target": "/w/rest.php/v1/page/Mercury?redirect=no"},
                          "Mercury": page("Mercury", DAB_TEXT)})
    skipped = []
    assert wp.resolve_article(c, "odd name", skipped=skipped) is None
    assert skipped == [{"title": "Mercury", "reason": "disambiguation"}]


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
