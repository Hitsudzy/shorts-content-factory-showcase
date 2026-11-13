#!/usr/bin/env python3
"""CF-0757: when Wikipedia and the feeds give no fact, the hunter reads the
company's own post (tier 1 of the channel's list) - and only an outlet whose
`ai_policy.verdict` is `allowed`.

Batch ExampleTech 2026-10-15T1854Z lost Apple HomeView and Gemini 4 Argon as
`no_fact`: no Wikipedia article for a product launched that day, and no step
that opened apple.com / blog.google. These tests pin the step: the post is
found by the news' own link, by a lead that is the post, by a company feed's
entry; a `forbidden` or `unknown` outlet is never asked; a number off the
page passes the rule like any tier-1 candidate; an empty page leaves the
topic `no_fact` as before, with `vendor_page=...` in the reason. Nothing
leaves the machine: the page client runs on a stand-in transport and the
channel's list is a stand-in dict.
"""
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import fact_probe_topics as fp  # noqa: E402
import fact_search as fs  # noqa: E402
import source_gate  # noqa: E402
import vendor_page as vp  # noqa: E402

rule = fp.fact_rule


def policy(verdict):
    return {"verdict": verdict, "checked_on": "2026-10-15", "checks": [], "terms_url": None}


def outlet(oid, hosts, verdict, use="cite_only"):
    return {"id": oid, "hosts": hosts, "use": use, "ai_policy": policy(verdict)}


# A stand-in of a tech channel's list (the shape of channels/example-tech/
# fact-sources.json; never the tracked file).
SOURCES = {
    "version": "test",
    "kinds": ["spec", "price", "release_date", "model_card", "benchmark", "paper", "law", "other"],
    "attributed_kinds": ["benchmark"],
    "tiers": {
        "1": [outlet("openai", ["openai.com"], "allowed"),
              outlet("apple", ["apple.com"], "allowed"),
              outlet("google", ["blog.google", "deepmind.google"], "unknown"),
              outlet("lawmakers", ["congress.gov"], "forbidden"),
              outlet("wikipedia_stand_in", ["wiki.example"], "allowed", use="read_text")],
        "2": [outlet("the_verge", ["theverge.com"], "forbidden"),
              outlet("engadget", ["engadget.com"], "allowed")],
    },
    "any_host": [],
    "do_not_take": [{"id": "banned", "hosts": ["openai.com"], "path_contains": ["/forum/"]}],
}

POST = "https://openai.com/index/introducing-gpt-x/"
PAGE = """<!doctype html><html><head><title>Introducing GPT-X | OpenAI</title>
<meta property="og:site_name" content="OpenAI"><script>var price = "$999 a year";</script></head>
<body><nav>Pricing for 2026 plans starts at 5 dollars.</nav>
<header>Menu 2026</header>
<article><h1>Introducing GPT-X</h1>
<p>Today we are releasing GPT-X to everyone.</p>
<p>GPT-X has a context window of 400,000 tokens. ChatGPT Plus costs $20 per month in 150 countries.</p>
<p>We think people will love it, and we are proud of the team.</p>
</article>
<footer>Copyright 2026 OpenAI. All rights reserved.</footer></body></html>"""
EMPTY_PAGE = "<html><head><title>OpenAI</title></head><body><p>Loading...</p></body></html>"


class Transport:
    """`urllib_transport`'s signature on a {url: (status, content_type, body)}
    map; `calls` are the URLs asked, with what the client sent."""

    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url, headers, timeout, max_bytes, allow):
        self.calls.append({"url": url, "headers": dict(headers), "timeout": timeout,
                           "max_bytes": max_bytes})
        status, ctype, body = self.pages.get(url, (404, "text/html", ""))
        raw = body.encode("utf-8")
        return status, ctype, url, raw[:max_bytes], len(raw) > max_bytes


def client(pages=None, cache_dir=None, **kw):
    t = Transport(pages if pages is not None else {POST: (200, "text/html; charset=utf-8", PAGE)})
    c = vp.PageClient(cache_dir=cache_dir, transport=t, delay=0, **kw)
    return c, t


def topic(topic_id="t-1", name="GPT-X", leads=(), summary=None):
    sources = [{"url": url, "title": f"{name} is here"} for url in leads]
    return {"topic_id": topic_id,
            "title_ref": {"name": name, "kind": "work", "type": "ai_model"},
            "signal": {"popularity_score": 70.0},
            "evidence": {"sources": sources, "rss_links": [s["url"] for s in sources]}}


def rss_of(entries):
    return {"entries": entries}


def no_article(requests, **kw):
    return {"source": "wikipedia", "asked_at": "2026-10-15T18:54:00Z", "requests": 1,
            "probes": [{"topic_id": r["topic_id"], "asked": r, "outcome": "no_article",
                        "article": None, "candidates": 0, "detail": "no article"}
                       for r in requests]}


def finder(t, record, rss_entries, own_urls, sources, client=None):
    return fs.search_topic(t, record, rss_entries, own_urls, sources, rule, client=None,
                           text_feeds=set())


def select(topics, vendor, rss=None):
    b = {"channel": "example-tech", "topics": topics}
    problems, _notes = fp.select_batch(b, rss=rss, probe=no_article, finder=finder,
                                       sources=SOURCES, text_feeds=set(), vendor=vendor)
    assert not problems, problems
    return b


def lead_summary(url, summary):
    return {"link": url, "title": "GPT-X is here", "summary": summary,
            "feed_url": "https://www.theverge.com/rss/index.xml"}


# --------------------------------------------------------------------------
# the door
# --------------------------------------------------------------------------

def test_the_door_opens_only_a_tier_one_outlet_whose_verdict_is_allowed():
    assert source_gate.vendor_page_refusal(POST, SOURCES) is None
    assert source_gate.vendor_page_refusal("https://www.apple.com/newsroom/x/", SOURCES) is None
    for url, word in (("https://blog.google/products/gemini/x/", "'unknown'"),
                      ("https://www.congress.gov/bill/x", "'forbidden'"),
                      ("https://www.engadget.com/x.html", "tier-1"),
                      ("https://example.org/x", "tier-1"),
                      ("https://openai.com/forum/x", "does not take")):
        why = source_gate.vendor_page_refusal(url, SOURCES)
        assert why and word in why, (url, why)
    assert "no fact-sources list" in source_gate.vendor_page_refusal(POST, None)


def test_the_list_is_data_a_verdict_turned_allowed_opens_the_outlet():
    opened = {**SOURCES, "tiers": {**SOURCES["tiers"], "1": [
        dict(r, ai_policy=policy("allowed")) if r["id"] == "google" else r
        for r in SOURCES["tiers"]["1"]]}}
    url = "https://blog.google/products/gemini/x/"
    assert source_gate.vendor_page_refusal(url, SOURCES)
    assert source_gate.vendor_page_refusal(url, opened) is None


def test_a_closed_outlet_is_never_asked_by_the_client():
    c, t = client()
    for url in ("https://blog.google/products/gemini/x/", "https://www.congress.gov/bill/x"):
        try:
            c.page(url, SOURCES)
        except source_gate.SourceClosed:
            pass
        else:
            raise AssertionError(f"{url} was read")
    assert t.calls == [] and c.network["requests"] == 0 and c.request_count == 0


def test_a_redirect_off_the_outlet_is_not_followed():
    hop = vp._GatedRedirect(lambda u: source_gate.vendor_page_refusal(u, SOURCES))
    try:
        hop.redirect_request(None, None, 302, "Found", {}, "https://blog.google/x/")
    except vp.PageError as exc:
        assert "redirected to https://blog.google/x/" in str(exc)
    else:
        raise AssertionError("a hop to an unknown outlet was followed")


def test_the_transport_is_reached_only_through_the_vendor_door():
    """`vendor_page.py` hands its transport to `source_gate.read_vendor_page`
    and calls it nowhere else - no page is read past the door."""
    import ast
    tree = ast.parse((HERE.parent / "scripts" / "vendor_page.py").read_text())
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)]
    direct = [n for n in calls if isinstance(n.func, ast.Attribute)
              and n.func.attr == "transport"]
    assert direct == []
    doors = [n for n in calls if isinstance(n.func, ast.Attribute)
             and n.func.attr == "read_vendor_page"]
    assert len(doors) == 1


# --------------------------------------------------------------------------
# the client
# --------------------------------------------------------------------------

def test_the_client_names_the_factory_sets_a_timeout_and_a_size_cap():
    c, t = client()
    page = c.page(POST, SOURCES)
    call = t.calls[0]
    assert call["headers"]["User-Agent"] == vp.USER_AGENT
    assert "shorts-content-factory" in vp.USER_AGENT and "Mozilla" not in vp.USER_AGENT
    assert call["timeout"] == vp.TIMEOUT and call["max_bytes"] == vp.MAX_BYTES
    assert page["error"] is None and page["title"] == "Introducing GPT-X | OpenAI"
    assert page["site_name"] == "OpenAI"


def test_a_page_past_the_size_cap_is_cut_and_marked():
    c, _t = client(max_bytes=300)
    page = c.page(POST, SOURCES)
    assert page["truncated"] is True and page["error"] is None


def test_not_an_html_page_or_an_error_is_written_not_raised():
    c, _t = client({POST: (200, "application/pdf", "%PDF"),
                    "https://openai.com/index/gone/": (403, "text/html", "")})
    assert "not an HTML page" in c.page(POST, SOURCES)["error"]
    assert c.page("https://openai.com/index/gone/", SOURCES)["error"] == "answered 403"


def test_a_page_is_read_once_a_batch_and_kept_for_the_next_process():
    with tempfile.TemporaryDirectory() as tmp:
        c, t = client(cache_dir=tmp)
        c.page(POST, SOURCES)
        c.page(POST, SOURCES)
        assert len(t.calls) == 1 and c.request_count == 2 and c.network["requests"] == 1
        again, t2 = client(cache_dir=tmp)            # a refill round's process
        assert again.page(POST, SOURCES)["blocks"] == c.page(POST, SOURCES)["blocks"]
        assert t2.calls == [] and again.network["requests"] == 0
        assert vp.client_for(tmp).cache_dir == Path(tmp) / "work" / vp.CACHE_DIR


def test_the_batch_ceiling_asks_nothing_past_it():
    c, t = client(max_pages=0)
    try:
        c.page(POST, SOURCES)
    except vp.PageError as exc:
        assert "MAX_PAGES_PER_BATCH" in str(exc)
    else:
        raise AssertionError("read past the ceiling")
    assert t.calls == []


class Flaky:
    """CF-0790: a transport that fails the way the network did on 10-17
    (`answers`: an exception to raise or a status to answer, in turn), then
    answers the page."""

    def __init__(self, *answers):
        self.answers, self.calls = list(answers), []

    def __call__(self, url, headers, timeout, max_bytes, allow):
        self.calls.append(url)
        if self.answers:
            a = self.answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return a, "text/html", url, b"", False
        raw = PAGE.encode("utf-8")
        return 200, "text/html; charset=utf-8", url, raw, False


TIMED_OUT = "URLError: <urlopen error timed out>"


def flaky_client(*answers, **kw):
    t = Flaky(*answers)
    slept = []
    c = vp.PageClient(transport=t, delay=0, sleep=slept.append, **kw)
    return c, t, slept


def test_a_connect_timeout_is_asked_again_and_the_page_is_read():
    # the 10-17T0817Z science.nasa.gov failure, then the answer of 10-18
    c, t, slept = flaky_client(vp.NetworkError(TIMED_OUT))
    page = c.page(POST, SOURCES)
    assert page["error"] is None and page["title"] == "Introducing GPT-X | OpenAI", page
    assert page["attempts"] == 2 and len(t.calls) == 2 and c.network["requests"] == 2
    assert slept == [vp.RETRY_DELAYS[0]], slept


def test_a_network_that_stays_down_is_unreachable_after_the_retries():
    c, t, slept = flaky_client(*[vp.NetworkError(TIMED_OUT)] * 5)
    page = c.page(POST, SOURCES)
    assert page["error"] == TIMED_OUT and page["attempts"] == vp.RETRIES + 1
    assert len(t.calls) == vp.RETRIES + 1 and slept == list(vp.RETRY_DELAYS[:vp.RETRIES])
    assert c.page(POST, SOURCES) is page and len(t.calls) == vp.RETRIES + 1  # not asked twice


def test_a_server_s_later_is_asked_again_a_refusal_is_not():
    c, t, _s = flaky_client(503, 429)
    assert c.page(POST, SOURCES)["error"] is None and len(t.calls) == 3
    for status in (403, 404):
        c, t, slept = flaky_client(status)
        assert c.page(POST, SOURCES)["error"] == f"answered {status}"
        assert len(t.calls) == 1 and slept == []


def test_a_redirect_off_the_outlet_is_not_asked_again():
    c, t, slept = flaky_client(vp.PageError("redirected to https://evil.example/: closed"))
    page = c.page(POST, SOURCES)
    assert page["error"].startswith("redirected to") and len(t.calls) == 1 and slept == []


def test_the_retries_stay_under_the_batch_ceiling():
    c, t, _s = flaky_client(*[vp.NetworkError(TIMED_OUT)] * 5, max_pages=2)
    page = c.page(POST, SOURCES)
    assert page["error"] == TIMED_OUT and len(t.calls) == 2 and c.network["requests"] == 2


def test_the_real_transport_calls_a_timeout_a_network_error():
    # urllib's own exception, through `urllib_transport`, without a socket
    import urllib.error
    import urllib.request

    class Opener:
        def open(self, req, timeout=None):
            raise urllib.error.URLError("timed out")

    real = urllib.request.build_opener
    urllib.request.build_opener = lambda *a: Opener()
    try:
        vp.urllib_transport(POST, {}, 1, 10, lambda u: None)
    except vp.NetworkError as exc:
        assert "timed out" in str(exc)
    else:
        raise AssertionError("no NetworkError")
    finally:
        urllib.request.build_opener = real


def test_the_page_s_prose_is_read_without_scripts_navigation_and_footer():
    text = " ".join(vp.html_text(PAGE)["blocks"])
    assert "400,000 tokens" in text and "$20 per month" in text
    for gone in ("$999", "starts at 5 dollars", "Menu 2026", "All rights reserved"):
        assert gone not in text, gone


# --------------------------------------------------------------------------
# the candidates
# --------------------------------------------------------------------------

def test_a_sentence_with_a_number_is_a_candidate_an_opinion_is_not():
    page = vp.PageClient(transport=Transport({POST: (200, "text/html", PAGE)}), delay=0).page(
        POST, SOURCES)
    cands = vp.page_candidates(page, "GPT-X", source_gate.outlet_of(POST, SOURCES))
    texts = [c["text"] for c in cands]
    assert "GPT-X has a context window of 400,000 tokens." in texts
    assert "ChatGPT Plus costs $20 per month in 150 countries." in texts
    assert not any("proud of the team" in t for t in texts)
    first = cands[0]
    assert first["text"].startswith("GPT-X")                  # names the work: first
    assert first["url"] == POST and first["source"] == "openai"
    assert first["kind"] == "model_card" and first["attribution"] == "OpenAI says"
    price = next(c for c in cands if "$20" in c["text"])
    assert price["kind"] == "price"


# --------------------------------------------------------------------------
# the step in the pass
# --------------------------------------------------------------------------

def test_the_post_linked_from_the_news_gives_the_fact_and_keeps_the_topic():
    lead = "https://www.theverge.com/news/1/gpt-x"
    rss = rss_of([lead_summary(lead, f'OpenAI <a href="{POST}">announced</a> GPT-X today.')])
    c, t = client()
    b = select([topic(leads=[lead])], c, rss=rss)
    assert [x["topic_id"] for x in b["topics"]] == ["t-1"]
    kept = b["topics"][0]
    passing = [x for x in kept[fp.CANDIDATES_KEY] if x["check"]["passes"]]
    assert passing and passing[0]["url"] == POST and passing[0]["check"]["tier"] == 1
    asked = kept[fp.SEARCH_KEY]["asked"][-1]
    assert asked["source"] == vp.VENDOR_SOURCE and asked["outcome"] == "ok"
    assert asked["pages"][0]["how"] == "lead_link"
    assert [x["url"] for x in t.calls] == [POST]              # the forbidden lead: never
    block = b["selection"][fp.VENDOR_KEY]
    assert block["asked"] is True and block["network"] == 1 and block["used"] == 1
    assert block["per_topic"]["t-1"]["pages"] == [POST]


def test_a_lead_that_is_the_post_itself_is_read():
    c, t = client()
    b = select([topic(leads=[POST])], c)
    assert b["topics"] and [x["url"] for x in t.calls] == [POST]
    assert b["topics"][0][fp.SEARCH_KEY]["asked"][-1]["pages"][0]["how"] == "lead"


def test_a_company_feed_s_entry_that_names_the_work_is_read():
    lead = "https://www.theverge.com/news/2/gpt-x"
    rss = rss_of([lead_summary(lead, "OpenAI shipped a new model."),
                  {"link": POST, "title": "Introducing GPT-X", "summary": "",
                   "feed_url": "https://openai.com/news/rss.xml"},
                  {"link": "https://openai.com/index/other/", "title": "Something else",
                   "summary": "", "feed_url": "https://openai.com/news/rss.xml"}])
    c, t = client()
    b = select([topic(leads=[lead])], c, rss=rss)
    assert b["topics"] and [x["url"] for x in t.calls] == [POST]
    assert b["topics"][0][fp.SEARCH_KEY]["asked"][-1]["pages"][0]["how"] == "vendor_feed"


def test_forbidden_and_unknown_outlets_are_never_asked_and_the_reason_says_so():
    lead = "https://www.theverge.com/news/3/gemini"
    rss = rss_of([lead_summary(lead, 'See <a href="https://blog.google/products/gemini/x/">'
                                     'the post</a> and https://www.congress.gov/bill/123.')])
    c, t = client()
    b = select([topic(name="Gemini 4 Argon", leads=[lead])], c, rss=rss)
    assert t.calls == [] and b["topics"] == []
    row = b["skipped_topics"][0]
    assert row["reason_code"] == "no_fact"
    asked = row[fp.SEARCH_KEY]["asked"][-1]
    assert asked["outcome"] == "closed" and asked["network"] == 0
    assert "vendor_page=closed(0)[blog.google: unknown, www.congress.gov: forbidden]" \
        in row["reason"], row["reason"]
    assert "searched " in row["reason"]


def test_an_empty_page_leaves_the_old_no_fact():
    c, t = client({POST: (200, "text/html", EMPTY_PAGE)})
    b = select([topic(leads=[POST])], c)
    assert b["topics"] == [] and len(t.calls) == 1
    row = b["skipped_topics"][0]
    assert row["reason_code"] == "no_fact"
    assert "vendor_page=no_candidates(0)[openai.com: no_candidates]" in row["reason"]


def test_no_tier_one_link_reads_nothing_and_says_so():
    c, t = client()
    b = select([topic(leads=["https://www.theverge.com/news/4/x"])], c)
    assert t.calls == [] and b["skipped_topics"][0]["reason_code"] == "no_fact"
    assert "vendor_page=no_link(0)[no tier-1 link" in b["skipped_topics"][0]["reason"]


def test_the_page_s_fact_meets_the_same_rule_a_retold_news_line_fails():
    page = PAGE.replace("<p>GPT-X has a context window of 400,000 tokens. "
                        "ChatGPT Plus costs $20 per month in 150 countries.</p>",
                        "<p>GPT-X is available to 150 countries from 14 October 2026.</p>")
    lead = "https://www.theverge.com/news/5/gpt-x"
    rss = rss_of([dict(lead_summary(lead, f'GPT-X is available to 150 countries from '
                                          f'14 October 2026, <a href="{POST}">OpenAI said</a>.'),
                       title="GPT-X is available to 150 countries from 14 October 2026")])
    c, _t = client({POST: (200, "text/html", page)})
    b = select([topic(leads=[lead])], c, rss=rss)
    row = b["skipped_topics"][0]
    assert row["reason_code"] == "no_fact"
    fails = [x["check"]["failures"] for x in row[fp.CANDIDATES_KEY] if x.get("vendor_page")]
    assert fails and all("retells_news" in f for f in fails)


def test_a_topic_that_already_has_a_fact_reads_no_page():
    lead = "https://www.engadget.com/gpt-x.html"
    found = {"text": "GPT-X has 12 billion parameters, OpenAI said in its model card.",
             "kind": "model_card", "source": "openai", "url": POST}

    def has_fact(t, record, rss_entries, own_urls, sources, client=None):
        return {"candidates": [dict(found)], "asked": [], "error": None, "requests": 0}
    c, t = client()
    b = {"channel": "example-tech", "topics": [topic(leads=[lead, POST])]}
    problems, _ = fp.select_batch(b, probe=no_article, finder=has_fact, sources=SOURCES,
                                  text_feeds=set(), vendor=c)
    assert not problems and b["topics"] and t.calls == []
    assert b["selection"][fp.VENDOR_KEY]["topics"] == 0


def test_two_topics_with_one_post_read_it_once():
    c, t = client()
    b = select([topic("t-1", leads=[POST]), topic("t-2", leads=[POST])], c)
    assert len(t.calls) == 1
    block = b["selection"][fp.VENDOR_KEY]
    assert block["network"] == 1 and block["sent"] == 2


def test_no_client_asks_no_page():
    b = {"channel": "example-tech", "topics": [topic(leads=[POST])]}
    problems, _ = fp.select_batch(b, probe=no_article, finder=finder, sources=SOURCES,
                                  text_feeds=set())
    assert not problems and b["skipped_topics"][0]["reason_code"] == "no_fact"
    assert b["selection"][fp.VENDOR_KEY]["asked"] is False
    assert "vendor_page" not in b["skipped_topics"][0]["reason"]


def test_an_outlet_with_its_own_reader_and_a_front_page_are_not_vendor_posts():
    links = vp.official_links("GPT-X", [{"url": "https://wiki.example/wiki/GPT-X"},
                                        {"url": "https://openai.com/"},
                                        {"url": POST}], [], SOURCES, rule, fs.names_work)
    assert links == [(POST, "lead")]


if __name__ == "__main__":
    failures = 0
    ran = 0
    for name, fn in sorted(list(globals().items())):
        if not name.startswith("test_") or not callable(fn):
            continue
        ran += 1
        try:
            fn()
            print(f"  ok   {name}")
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
        except Exception as exc:  # noqa: BLE001 - a crash is a failure, not an abort
            failures += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
