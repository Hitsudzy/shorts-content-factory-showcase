#!/usr/bin/env python3
"""CF-0824: the support text's Wikipedia read (`support_text.support_topic`,
`client.page(article)`) does not take a disambiguation page as the topic's
article. The probe may hand over a title whose page is a list of meanings
(CF-0828 found such pages passing for articles); its lines are other
subjects, so the topic is read as one with no article of its own - no
support text, or the company's own post when the channel reads those.

Stand-in client, no network: `page` answers from a dict.
"""
import sys
import types
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import support_text as st  # noqa: E402
from _wikipedia import wikipedia_api as wp  # noqa: E402

DAB = {"title": "Mercury", "disambiguation": True,
       "wikitext": "'''Mercury''' may refer to:\n* [[Mercury (planet)]]\n* [[Mercury (element)]]\n"
                   "{{disambiguation}}"}
DAB_BY_TEMPLATE = {"title": "Mercury",
                   "wikitext": "'''Mercury''' may refer to:\n* [[Mercury (planet)]]\n"
                               "{{Disambiguation|geo}}"}
TOPIC = {"topic_id": "t-mercury",
         "title_ref": {"name": "Mercury", "kind": "work", "type": "film"},
         "evidence": {"sources": []}}


class PageClient:
    def __init__(self, pages):
        self.pages = pages
        self.request_count = 0

    def page(self, title):
        self.request_count += 1
        return self.pages.get(title)


def _support(page, module=wp, vendor_reader=None):
    client = PageClient({"Mercury": page})
    return st.support_topic(TOPIC, {"outcome": "ok", "article": "Mercury"}, client, module,
                            leads=[], now="2026-10-21T10:00:00Z",
                            vendor_reader=vendor_reader)


def test_a_disambiguation_page_is_no_support_text():
    pieces, check = _support(DAB)
    assert check["state"] == st.STATE_NO_TEXT, check
    assert "disambiguation" in check["detail"], check
    assert check["asked"] == [{"title": "Mercury", "found": True, "disambiguation": True}]
    assert not st.has_wikipedia_text(pieces)


def test_the_template_alone_marks_it_and_an_older_root_is_read_by_the_page():
    # the root's own judge, on the template only
    _, check = _support(DAB_BY_TEMPLATE)
    assert check["state"] == st.STATE_NO_TEXT and "disambiguation" in check["detail"], check
    # a client module without `is_disambiguation` (a root before CF-0828)
    old_root = types.SimpleNamespace(WikipediaError=getattr(wp, "WikipediaError", Exception))
    for page in (DAB, DAB_BY_TEMPLATE):
        _, check = _support(page, module=old_root)
        assert check["state"] == st.STATE_NO_TEXT and "disambiguation" in check["detail"], check


def test_a_disambiguation_page_falls_to_the_companys_post_like_no_article():
    calls = []

    def reader(topic, leads):
        calls.append(topic["topic_id"])
        return ([{"kind": "vendor_page", "url": "https://example.com/post", "text": "x"}],
                {"outcome": "ok", "where": "example.com"})

    pieces, check = _support(DAB, vendor_reader=reader)
    assert calls == ["t-mercury"], calls
    assert check["state"] == st.STATE_OK and "disambiguation" in check["detail"], check
    assert [p["url"] for p in pieces] == ["https://example.com/post"]


def test_an_ordinary_article_is_still_read():
    page = {"title": "Mercury", "wikitext": "'''Mercury''' is a 2026 film. It stars someone. "
                                            "It was released on 3 October 2026."}
    assert not st.is_disambiguation_page(wp, page)
    _, check = _support(page)
    assert "disambiguation" not in (check["detail"] or ""), check
    assert check["asked"][0] == {"title": "Mercury", "found": True}, check


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_"):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
