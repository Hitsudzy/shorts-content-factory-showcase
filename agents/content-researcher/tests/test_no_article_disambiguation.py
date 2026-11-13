#!/usr/bin/env python3
"""CF-0828: the fact lookup does not take a disambiguation page for the
topic's article.

The bare name of a company or a planet (`Amazon`, `Mercury`) is a Wikipedia
page that lists meanings. Until CF-0828 `resolve_article` handed it back as
the article, `has_fact_section` found nothing in it and the topic was lost as
`no_section`. Now the next candidate of the ranking is read, and when every
candidate was such a page the lookup says `no_article` with the sub-reason
`sub_reason: disambiguation` - on the probe's `detail` and on the
refusal's `fact_lookup` too. The status itself stays `no_article`: it is the
word the channel's `not_found` and the root's schema pin.

Synthetic Core REST answers through a scripted transport - nothing here asks
the network or reads live data."""
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import unquote, urlparse

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import fact_probe as fp             # noqa: E402
import fact_refusal                 # noqa: E402
import production_facts as pf       # noqa: E402
import wikipedia_api as wapi        # noqa: E402

DAB_TEXT = ("'''Amazon''' most often refers to:\n* [[Amazon (company)]]\n"
            "* [[Amazon River]]\n== Other uses ==\n* [[Amazons]]\n{{disambiguation}}\n")
COMPANY_TEXT = (
    "'''Amazon.com, Inc.''' is an American technology company.\n"
    "== History ==\n"
    "Amazon was founded by Jeff Bezos in Bellevue, Washington, on July 5, 1994."
    "<ref>{{cite web |url=https://example.org/amazon-history |title=History}}</ref>\n"
    "== Products and services ==\n"
    "In 2007 the company released the first Kindle e-reader for $399, which sold "
    "out in five and a half hours.<ref>{{cite web |url=https://example.org/kindle "
    "|title=Kindle}}</ref>\n")


class Scripted:
    def __init__(self, search=(), pages=None):
        self.search = list(search)
        self.pages = dict(pages or {})
        self.asked = []

    def __call__(self, url, headers, timeout=None):
        self.asked.append(url)
        path = unquote(urlparse(url).path)
        if path.endswith("/search/page"):
            body = {"pages": [{"title": t} for t in self.search]}
            return wapi.HttpResponse(200, json.dumps(body), {})
        title = path.rsplit("/page/", 1)[-1].replace("_", " ")
        if title in self.pages:
            return wapi.HttpResponse(200, json.dumps(self.pages[title]), {})
        return wapi.HttpResponse(404, json.dumps({"errorKey": "rest-nonexistent-title"}), {})


def page(title, text, page_type=None):
    body = {"title": title, "key": title.replace(" ", "_"), "id": 7, "source": text,
            "license": {"title": "CC BY-SA 4.0"}}
    if page_type:
        body["type"] = page_type
    return body


def client(**kw):
    return wapi.WikipediaClient(transport=Scripted(**kw), sleep=lambda _s: None)


def only_disambiguation():
    return client(search=["Amazon"], pages={"Amazon": page("Amazon", DAB_TEXT)})


def disambiguation_then_company():
    return client(search=["Amazon", "Amazon (company)"],
                  pages={"Amazon": page("Amazon", DAB_TEXT),
                         "Amazon (company)": page("Amazon (company)", COMPANY_TEXT)})


def test_the_bare_name_is_not_read_as_an_article_with_no_section():
    result = pf.find_production_facts("Amazon", client=disambiguation_then_company())
    assert result["status"] != pf.STATUS_NO_SECTION
    assert result["article"]["title"] == "Amazon (company)"
    assert "sub_reason" not in result


def test_only_disambiguation_pages_is_no_article_with_the_sub_reason():
    result = pf.find_production_facts("Amazon", client=only_disambiguation())
    assert result["status"] == pf.STATUS_NO_ARTICLE
    assert result["article"] is None and result["article_check"] is None
    assert result["sub_reason"] == pf.NO_ARTICLE_REASON_DISAMBIGUATION == "disambiguation"
    assert result["skipped_articles"] == ["Amazon"]


def test_the_rest_type_alone_is_enough():
    c = client(search=["Mercury"],
               pages={"Mercury": page("Mercury", "'''Mercury''' may refer to:",
                                      page_type="disambiguation")})
    result = pf.find_production_facts("Mercury", client=c)
    assert result["status"] == pf.STATUS_NO_ARTICLE
    assert result["sub_reason"] == "disambiguation"


def test_a_plain_no_article_carries_no_sub_reason():
    result = pf.find_production_facts("Qwerty Zzz", client=client(search=[]))
    assert result["status"] == pf.STATUS_NO_ARTICLE
    assert "sub_reason" not in result


def test_the_status_stays_a_word_the_schema_pins():
    # patterns/validate_patterns.py FACT_REFUSAL_STATUSES - the sub-reason is
    # not a fourth status.
    result = pf.find_production_facts("Amazon", client=only_disambiguation())
    assert result["status"] in ("no_article", "no_section", "no_candidates")


def test_the_probe_says_why_in_its_detail():
    answer = fp.probe({"topic_id": "t1", "name": "Amazon"}, only_disambiguation())
    assert answer["outcome"] == "no_article"
    assert answer["detail"] == "disambiguation: Amazon"
    assert answer["usable"] is False


def test_the_refusal_record_carries_the_sub_reason():
    lookup = pf.find_production_facts("Amazon", client=only_disambiguation())
    rule = SimpleNamespace(fact_source="wikipedia", candidates_field="candidates")
    record = fact_refusal._lookup_record(lookup, rule)
    assert record["status"] == "no_article"
    assert record["sub_reason"] == "disambiguation"


def test_a_refusal_without_the_sub_reason_is_written_as_before():
    lookup = pf.find_production_facts("Qwerty Zzz", client=client(search=[]))
    rule = SimpleNamespace(fact_source="wikipedia", candidates_field="candidates")
    assert "sub_reason" not in fact_refusal._lookup_record(lookup, rule)


if __name__ == "__main__":
    import traceback
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
