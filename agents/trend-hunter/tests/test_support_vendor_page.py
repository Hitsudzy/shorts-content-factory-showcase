#!/usr/bin/env python3
"""CF-0771: a topic with no Wikipedia article of its own is told from its
company's own post.

Batch ExampleTech 2026-10-16T0702Z: Gemini 4 Argon and Muse Spark Open left as
`no_support_text` - "no Wikipedia article of the topic's own" - although the
fact search (CF-0757) had read Gemini 4 Argon's post on deepmind.google and
found seven passing facts there. A product launched this week has no article
for weeks; the channel's list names the company's page its first source.

These tests pin the step: the post the fact search reads is the support text
(`vendor_page` piece: source, outlet, url, title, the post's main text), read
through the same door (tier 1, `allowed`) and the same cache - not asked
twice; a closed outlet, a page that does not name the work, or no link leaves
the old `no_support_text`; a topic with an article is told from the article
as before. Nothing leaves the machine: the page client runs on the stand-in
transport of `test_vendor_page.py` and the channel's list is its stand-in.
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import fact_probe_topics as fp  # noqa: E402
import support_text as st  # noqa: E402
import test_vendor_page as tv  # noqa: E402  - the stand-in list, page, transport, probe

GOOGLE_POST = "https://deepmind.google/blog/introducing-gpt-x/"


class NoWiki:
    """The Wikipedia client of a topic with no article: never asked."""
    request_count = 0

    def page(self, title):  # pragma: no cover - a no_article topic asks nothing
        raise AssertionError(f"asked Wikipedia for {title!r}")


def make_supporter():
    def supporter(topic, record, leads, index):
        return st.support_topic(topic, record, NoWiki(), None, index=index, leads=leads,
                                now="2026-10-16T07:05:00Z",
                                vendor_reader=supporter.vendor_reader)
    supporter.vendor_reader = None
    return supporter


def select(topics, vendor, rss=None, supporter=None):
    b = {"channel": "example-tech", "generated_at": "2026-10-16T07:05:00Z", "topics": topics}
    problems, _ = fp.select_batch(b, rss=rss, probe=tv.no_article, finder=tv.finder,
                                  sources=tv.SOURCES, text_feeds=set(), vendor=vendor,
                                  supporter=supporter or make_supporter())
    assert not problems, problems
    return b


# --------------------------------------------------------------------------
# the piece
# --------------------------------------------------------------------------

def test_the_post_is_a_piece_with_its_source_url_title_and_main_text():
    c, t = tv.client()
    pieces, rec = st.vendor_pieces(tv.topic(leads=[tv.POST]), [{"url": tv.POST}], [],
                                   tv.SOURCES, c, now="2026-10-16T07:05:00Z")
    assert rec["outcome"] == "ok" and rec["pieces"] == 1 and rec["network"] == 1
    (p,) = pieces
    assert p["kind"] == st.KIND_VENDOR and p["source"] == st.SOURCE_VENDOR
    assert p["id"] == "vendor_page:openai:1" and p["outlet"] == "openai"
    assert p["url"] == tv.POST and p["title"] == "Introducing GPT-X | OpenAI"
    assert p["publication"] == "OpenAI" and p["fetched_at"] == "2026-10-16T07:05:00Z"
    assert p["revision_id"] is None and p["revised_at"] is None
    # the post's own words, quotable: the article, not the menu, the script or the footer
    assert "context window of 400,000 tokens" in p["text"]
    assert "$999" not in p["text"] and "Menu" not in p["text"] and "Copyright" not in p["text"]


def test_a_closed_outlet_is_never_asked_and_gives_no_text():
    c, t = tv.client({GOOGLE_POST: (200, "text/html", tv.PAGE)})
    pieces, rec = st.vendor_pieces(tv.topic(leads=[GOOGLE_POST]), [{"url": GOOGLE_POST}], [],
                                   tv.SOURCES, c)
    assert pieces == [] and t.calls == []
    assert rec["outcome"] == "closed" and "unknown" in rec["where"]


def test_a_post_that_does_not_name_the_work_is_no_piece():
    c, t = tv.client()
    pieces, rec = st.vendor_pieces(tv.topic(name="Sora Max", leads=[tv.POST]),
                                   [{"url": tv.POST}], [], tv.SOURCES, c)
    assert pieces == [] and rec["outcome"] == "not_about_the_work"


def test_no_link_asks_nothing():
    c, t = tv.client()
    lead = "https://www.theverge.com/news/1/gpt-x"
    pieces, rec = st.vendor_pieces(tv.topic(leads=[lead]), [{"url": lead}], [], tv.SOURCES, c)
    assert pieces == [] and rec["outcome"] == "no_link" and t.calls == []


# --------------------------------------------------------------------------
# the state
# --------------------------------------------------------------------------

def test_no_article_with_the_companys_post_is_ok_on_the_post():
    piece = {"id": "vendor_page:openai:1", "kind": st.KIND_VENDOR, "source": st.SOURCE_VENDOR,
             "url": tv.POST, "text": "GPT-X has a context window of 400,000 tokens."}
    pieces, check = st.support_topic(
        tv.topic(), {"outcome": "no_article", "article": None}, NoWiki(), None,
        vendor_reader=lambda t, leads: ([piece], {"outcome": "ok", "where": "openai.com: ok"}))
    assert check["state"] == st.STATE_OK and pieces == [piece]
    assert "company's own post" in check["detail"] and check["vendor_page"]["outcome"] == "ok"
    assert st.has_story_text(pieces) and not st.has_wikipedia_text(pieces)


def test_no_article_and_no_post_is_the_old_no_support_text_with_the_why():
    pieces, check = st.support_topic(
        tv.topic(), {"outcome": "no_article", "article": None}, NoWiki(), None,
        vendor_reader=lambda t, leads: ([], {"outcome": "closed",
                                              "where": "deepmind.google: unknown"}))
    assert check["state"] == st.STATE_NO_TEXT and pieces == []
    assert "deepmind.google: unknown" in check["detail"]
    reason = st.refusal_reason(tv.topic(), check)
    assert reason.startswith("no support text: no Wikipedia article") and "CF-0771" in reason


def test_without_a_reader_nothing_changes():
    pieces, check = st.support_topic(tv.topic(), {"outcome": "no_article", "article": None},
                                     NoWiki(), None)
    assert check["state"] == st.STATE_NO_TEXT and "vendor_page" not in check


def test_the_news_summaries_alone_are_still_not_story_text():
    rss = [{"id": "rss:1", "kind": st.KIND_RSS, "source": "rss", "text": "GPT-X is out."}]
    assert not st.has_story_text(rss)


# --------------------------------------------------------------------------
# the pass
# --------------------------------------------------------------------------

def test_the_incident_shape_is_carried_on_the_post_the_fact_was_read_from():
    """0702Z's Gemini 4 Argon: no article, the post read for the fact - now
    the topic is carried and its text is that post, read once."""
    c, t = tv.client()
    b = select([tv.topic(leads=[tv.POST])], c)
    assert [x["topic_id"] for x in b["topics"]] == ["t-1"], b.get("skipped_topics")
    kept = b["topics"][0]
    check = kept[fp.SUPPORT_CHECK_KEY]
    assert check["state"] == st.STATE_OK and check["vendor_page"]["outcome"] == "ok"
    assert [p["kind"] for p in kept[fp.SUPPORT_KEY]] == [st.KIND_VENDOR]
    assert [x["url"] for x in t.calls] == [tv.POST]          # the fact's read, reused
    block = b["selection"][fp.VENDOR_KEY]
    assert block["text_used"] == 1 and block["used"] == 1 and block["network"] == 1
    assert block["per_topic"]["t-1"]["support_text"]["pieces"] == 1
    assert b["selection"][fp.SUPPORT_KEY]["carried_with_vendor_text"] == 1
    assert fp.check_batch(b) == []


def test_without_a_page_client_the_topic_leaves_as_before():
    """No page client - no fact from the post either; nothing here changes
    a pass that reads no company page."""
    b = select([tv.topic(leads=[tv.POST])], None)
    assert b["topics"] == []
    assert {r["reason_code"] for r in b["skipped_topics"]} == {fp.FACT_REFUSAL_CODE}


def test_an_ok_state_on_news_summaries_alone_still_fails_the_check():
    c, _ = tv.client()
    b = select([tv.topic(leads=[tv.POST])], c)
    kept = b["topics"][0]
    kept[fp.SUPPORT_KEY] = [{"id": "rss:1", "kind": st.KIND_RSS, "source": "rss",
                             "text": "GPT-X is out."}]
    assert any("company's own post" in p for p in fp.check_batch(b))


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
