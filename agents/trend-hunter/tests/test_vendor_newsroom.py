#!/usr/bin/env python3
"""CF-0810: when a topic's news carries no tier-1 link, `vendor_page` reads
the vendor's newsroom index (a tier-1 row's `newsroom`) and takes the release
that names the work.

Batch ExampleTech 2026-10-16T0839Z lost «Porsche Mission S» as `no_fact`: no
Wikipedia article, and no link to newsroom.porsche.com in its news - while
the release sat on the newsroom's own index. These tests pin the step: the
index of a company the topic names is read through the same door and client
(an `allowed` tier-1 row only; `unknown` is never asked), a same-host link
whose text or slug names the work is read as a post and judged by the rule
as usual, an index with no such link says `newsroom_no_match`, the index
counts against the pass's ceiling, and a list with no `newsroom` behaves as
before. Nothing leaves the machine: a stand-in transport and a stand-in
list.
"""
import copy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "scripts"))

import fact_probe_topics as fp  # noqa: E402
import fact_search as fs  # noqa: E402
import support_text as st  # noqa: E402
import vendor_page as vp  # noqa: E402

rule = fp.fact_rule


def policy(verdict):
    return {"verdict": verdict, "checked_on": "2026-10-19", "checks": [], "terms_url": None}


def outlet(oid, hosts, verdict, **extra):
    return dict({"id": oid, "hosts": hosts, "use": "cite_only", "ai_policy": policy(verdict)},
                **extra)


INDEX = "https://newsroom.porsche.com/en/press-releases.html"
RELEASE = "https://newsroom.porsche.com/en/2026/products/porsche-mission-s-vision-model-43528.html"
OTHER = "https://newsroom.porsche.com/en/2026/company/porsche-q3-results-43000.html"
BRAND_INDEX = "https://www.porsche.com/international/news/"
DS_INDEX = "https://api-docs.deepseek.com/news/"
DS_RELEASE = "https://api-docs.deepseek.com/news/news251019"

# A stand-in of a tech channel's list (never the tracked file).
SOURCES = {
    "version": "test",
    "kinds": ["spec", "price", "release_date", "model_card", "benchmark", "paper", "law", "other"],
    "attributed_kinds": ["benchmark"],
    "tiers": {
        "1": [outlet("porsche", ["newsroom.porsche.com"], "allowed", newsroom=[INDEX]),
              outlet("porsche_unverified", ["porsche.com"], "unknown",
                     newsroom=[BRAND_INDEX]),
              outlet("ai_labs", ["deepseek.com"], "allowed",
                     newsroom=[{"url": DS_INDEX, "names": ["DeepSeek"]}])],
        "2": [outlet("the_verge", ["theverge.com"], "forbidden")],
    },
    "any_host": [],
    "do_not_take": [],
}


def without_newsroom(sources):
    out = copy.deepcopy(sources)
    for row in out["tiers"]["1"]:
        row.pop(vp.NEWSROOM_FIELD, None)
    return out


INDEX_PAGE = f"""<!doctype html><html><head><title>Press releases - Porsche Newsroom</title>
</head><body><nav><a href="/en.html">Home</a> <a href="#top">Top</a></nav>
<main><h1>Press releases</h1><ul>
<li><a href="/en/2026/products/porsche-mission-s-vision-model-43528.html">
   A new vision for the electric sports car</a></li>
<li><a href="{OTHER}">Porsche reports third-quarter results</a></li>
<li><a href="https://elsewhere.example/porsche-mission-s">Porsche Mission S elsewhere</a></li>
</ul></main><script>document.write('<a href="/en/x-porsche-mission-s.html">x</a>')</script>
</body></html>"""
NO_MATCH_INDEX = INDEX_PAGE.replace("porsche-mission-s-vision-model-43528",
                                    "porsche-taycan-update-43520")
RELEASE_PAGE = """<!doctype html><html><head><title>Porsche Mission S</title>
<meta property="og:site_name" content="Porsche Newsroom"></head><body><article>
<h1>Porsche Mission S: a vision of the electric sports car</h1>
<p>The Porsche Mission S has a range of up to 600 km on its 800-volt architecture.</p>
<p>It charges from 10 to 80 percent in 12 minutes at a 400 kW charger.</p>
<p>We are proud of the team that built it.</p></article></body></html>"""
DS_INDEX_PAGE = """<html><body><main><a href="/news/news251019">DeepSeek-V4.1 Flash Release</a>
<a href="/news/news250901">DeepSeek-V3.2 Release</a></main></body></html>"""
DS_RELEASE_PAGE = """<html><head><title>DeepSeek-V4.1 Flash Release</title></head><body><article>
<p>DeepSeek-V4.1 Flash supports a context window of 256,000 tokens in the API.</p>
<p>API prices start at $0.07 per million input tokens from 20 October 2026.</p>
</article></body></html>"""

PAGES = {INDEX: (200, "text/html; charset=utf-8", INDEX_PAGE),
         RELEASE: (200, "text/html; charset=utf-8", RELEASE_PAGE),
         BRAND_INDEX: (200, "text/html", INDEX_PAGE),
         DS_INDEX: (200, "text/html", DS_INDEX_PAGE),
         DS_RELEASE: (200, "text/html", DS_RELEASE_PAGE)}


class Transport:
    def __init__(self, pages):
        self.pages, self.calls = pages, []

    def __call__(self, url, headers, timeout, max_bytes, allow):
        self.calls.append(url)
        status, ctype, body = self.pages.get(url, (404, "text/html", ""))
        raw = body.encode("utf-8")
        return status, ctype, url, raw[:max_bytes], len(raw) > max_bytes


def client(pages=None, **kw):
    t = Transport(dict(PAGES, **(pages or {})))
    return vp.PageClient(transport=t, delay=0, **kw), t


LEAD = "https://www.theverge.com/news/9/porsche-mission-s"


def topic(name="Porsche Mission S", lead_title=None, summary="An electric concept car."):
    lead = {"url": LEAD, "title": lead_title or f"{name} shown in Los Angeles",
            "summary": summary}
    t = {"topic_id": "t-1", "title_ref": {"name": name, "kind": "work", "type": "car"},
         "signal": {"popularity_score": 70.0},
         "evidence": {"sources": [{"url": LEAD, "title": lead["title"]}], "rss_links": [LEAD]}}
    return t, [lead]


def lookup(t, leads, c, sources=SOURCES):
    return vp.lookup(t, leads, [], sources, rule, c, fs.names_work,
                     news_text=fp.news_text_of(leads))


# --------------------------------------------------------------------------

def test_the_index_s_links_are_read_with_their_text_scripts_aside():
    links = vp.html_links(INDEX_PAGE)
    hrefs = [x["href"] for x in links]
    assert "/en.html" in hrefs and "#top" not in hrefs
    assert not any("x-porsche-mission-s" in h for h in hrefs)
    first = next(x for x in links if "43528" in x["href"])
    assert first["text"] == "A new vision for the electric sports car"
    assert vp.html_links('<a href="/a" title="Mission S"><img src="x"></a>') \
        == [{"href": "/a", "text": "Mission S"}]


def test_a_vendor_s_newsroom_gives_the_release_that_names_the_work():
    c, t = client()
    t_, leads = topic()
    cands, asked = lookup(t_, leads, c)
    assert t.calls == [INDEX, RELEASE]                       # never OTHER, never elsewhere
    # the brand site's index is on an `unknown` row: named, never asked
    assert [x["outlet"] for x in asked["closed"]] == ["porsche_unverified"]
    assert asked["outcome"] == "ok" and asked["via"] == vp.VIA_NEWSROOM
    assert asked["pages"][0]["url"] == RELEASE and asked["pages"][0]["how"] == "newsroom"
    rec = asked["newsroom"][0]
    assert rec["index"] == INDEX and rec["outlet"] == "porsche" and rec["outcome"] == "matched"
    assert rec["matched"] == [RELEASE] and rec["links"] == 3     # /en.html, RELEASE, OTHER
    assert asked["network"] == 2 and asked["requests"] == 2
    passing = [x for x in rule.check_candidates(cands, SOURCES,
                                                news_text=fp.news_text_of(leads))
               if x[rule.CHECK_KEY]["passes"]]
    assert passing and passing[0]["url"] == RELEASE and passing[0]["source"] == "porsche"


def test_the_row_s_names_open_a_newsroom_the_work_does_not_name():
    c, t = client()
    t_, leads = topic(name="V4.1 Flash", lead_title="DeepSeek ships V4.1 Flash")
    _cands, asked = lookup(t_, leads, c)
    assert t.calls == [DS_INDEX, DS_RELEASE] and asked["via"] == "newsroom"
    assert asked["newsroom"][0]["named"] == "DeepSeek"


def test_an_index_that_names_no_release_says_newsroom_no_match():
    c, t = client({INDEX: (200, "text/html", NO_MATCH_INDEX)})
    t_, leads = topic()
    cands, asked = lookup(t_, leads, c)
    assert t.calls == [INDEX] and cands == []
    assert asked["outcome"] == vp.OUTCOME_NEWSROOM_NO_MATCH == "newsroom_no_match"
    assert asked["via"] is None and asked["newsroom"][0]["outcome"] == "newsroom_no_match"
    assert "newsroom.porsche.com/en/press-releases.html newsroom: newsroom_no_match" \
        in asked["where"], asked["where"]
    assert asked["network"] == 1


def test_an_index_of_an_unknown_outlet_is_never_asked():
    sources = copy.deepcopy(SOURCES)
    sources["tiers"]["1"][0].pop("newsroom")             # only porsche_unverified has one
    c, t = client()
    t_, leads = topic()
    _cands, asked = lookup(t_, leads, c, sources)
    assert t.calls == [] and asked["network"] == 0
    assert asked["outcome"] == "closed"
    assert asked["closed"][0]["how"] == vp.HOW_INDEX
    assert asked["closed"][0]["verdict"] == "unknown"
    assert "porsche.com: unknown" in asked["where"]


def test_an_index_off_the_row_s_own_host_is_never_asked():
    sources = copy.deepcopy(SOURCES)
    sources["tiers"]["1"][2]["newsroom"] = [{"url": "https://newsroom.porsche.com/en/ai.html",
                                            "names": ["DeepSeek"]}]
    sources["tiers"]["1"][0].pop("newsroom")
    c, t = client()
    t_, leads = topic(name="V4.1 Flash", lead_title="DeepSeek ships V4.1 Flash")
    _cands, asked = lookup(t_, leads, c, sources)
    assert t.calls == [] and asked["outcome"] == "closed"
    assert "not the row's own host" in asked["closed"][0]["why"]


def test_a_topic_that_names_no_vendor_reads_no_index():
    c, t = client()
    t_, leads = topic(name="Mission S", lead_title="A new electric concept car",
                      summary="It was shown in Los Angeles.")
    _cands, asked = lookup(t_, leads, c)
    assert t.calls == [] and asked["outcome"] == "no_link" and "via" not in asked


def test_the_index_counts_against_the_pass_s_ceiling():
    c, t = client(max_pages=1)
    t_, leads = topic()
    _cands, asked = lookup(t_, leads, c)
    assert t.calls == [INDEX] and asked["outcome"] == "cap"
    assert asked["pages"][0]["url"] == RELEASE and asked["pages"][0]["outcome"] == "cap"
    c0, t0 = client(max_pages=0)
    _cands, asked0 = lookup(t_, leads, c0)
    assert t0.calls == [] and asked0["outcome"] == "cap"
    assert asked0["newsroom"][0]["outcome"] == "cap"


def test_an_unreachable_index_is_unreachable_not_no_match():
    c, t = client({INDEX: (404, "text/html", "")})
    t_, leads = topic()
    _cands, asked = lookup(t_, leads, c)
    assert t.calls == [INDEX] and asked["outcome"] == "unreachable"
    assert "answered 404" in asked["where"]


def test_a_tier_one_link_in_the_news_keeps_the_newsroom_shut():
    c, t = client()
    t_, leads = topic(summary=f'Porsche <a href="{RELEASE}">announced</a> it.')
    _cands, asked = lookup(t_, leads, c)
    assert t.calls == [RELEASE] and "via" not in asked
    assert asked["pages"][0]["how"] == "lead_link"


def test_no_newsroom_field_leaves_no_link_and_closed_as_before():
    plain = without_newsroom(SOURCES)
    c, t = client()
    t_, leads = topic()
    _cands, asked = lookup(t_, leads, c, plain)
    assert t.calls == [] and asked["outcome"] == "no_link" and "via" not in asked
    # CF-0914: the reason names the company it could have been told from
    assert asked["where"] == ("no tier-1 link in the topic's news or the pool; named "
                              "newsroom.porsche.com: allowed, no newsroom listed, "
                              "porsche.com: unknown"), asked["where"]
    t2, leads2 = topic(summary='See <a href="https://www.porsche.com/models/mission-s/">it</a>.')
    _cands, asked2 = lookup(t2, leads2, c, plain)
    assert t.calls == [] and asked2["outcome"] == "closed" and "via" not in asked2
    assert asked2["where"] == "www.porsche.com: unknown"


def test_the_pass_keeps_the_topic_and_says_newsroom():
    t_, leads = topic()
    rss = {"entries": [{"link": LEAD, "title": leads[0]["title"], "summary": leads[0]["summary"],
                        "feed_url": "https://www.theverge.com/rss/index.xml"}]}

    def no_article(requests, **kw):
        return {"source": "wikipedia", "asked_at": "2026-10-19T08:44:00Z", "requests": 1,
                "probes": [{"topic_id": r["topic_id"], "asked": r, "outcome": "no_article",
                            "article": None, "candidates": 0, "detail": "no article"}
                           for r in requests]}

    def finder(tp, record, rss_entries, own_urls, sources, client=None):
        return fs.search_topic(tp, record, rss_entries, own_urls, sources, rule, client=None,
                               text_feeds=set())
    c, t = client()
    b = {"channel": "example-tech", "topics": [t_]}
    problems, _ = fp.select_batch(b, rss=rss, probe=no_article, finder=finder,
                                  sources=SOURCES, text_feeds=set(), vendor=c)
    assert not problems, problems
    assert [x["topic_id"] for x in b["topics"]] == ["t-1"], b.get("skipped_topics")
    per = b["selection"][fp.VENDOR_KEY]["per_topic"]["t-1"]
    assert per["via"] == "newsroom" and per["newsroom"] == [INDEX]
    assert per["pages"] == [RELEASE] and per["network"] == 2


def test_newsroom_entries_take_a_url_or_an_object_and_the_host_s_stem():
    row = outlet("x", ["example.co.uk"], "allowed", names=["Example Ltd"],
                 newsroom=["https://news.example.co.uk/press/",
                           {"url": "https://example.co.uk/media/", "names": ["Ex"]},
                           "not a url"])
    assert vp.newsroom_entries(row) == [
        ("https://news.example.co.uk/press/", ["Example Ltd", "example"]),
        ("https://example.co.uk/media/", ["Example Ltd", "Ex", "example"])]
    assert vp.host_stem("newsroom.porsche.com") == "porsche"
    assert vp.host_stem("x.ai") == "x"
    assert vp.newsroom_entries(outlet("x", ["x.ai"], "allowed",
                                      newsroom=["https://x.ai/news"])) \
        == [("https://x.ai/news", [])]                       # a 1-letter stem names nobody


# CF-0810 follow-up: generic host stems. The tier-1 rows below copy the
# `newsroom` fields (and `names`) of ExampleTech's list as the root filled
# them on 19.10 - a stand-in, never the tracked file.
REAL_ROWS = [
    outlet("google", ["google.com", "blog.google", "deepmind.google"], "allowed",
           names=["Google"],
           newsroom=["https://blog.google/innovation-and-ai/technology/ai/",
                     "https://blog.google/products-and-platforms/products/",
                     "https://deepmind.google/blog/"]),
    outlet("anthropic", ["anthropic.com"], "allowed",
           newsroom=["https://www.anthropic.com/news"]),
    outlet("meta", ["meta.com", "about.fb.com"], "allowed",
           names=["Meta", "Facebook", "Instagram", "WhatsApp"],
           newsroom=["https://about.fb.com/news/"]),
    outlet("microsoft", ["microsoft.com"], "allowed",
           newsroom=["https://news.microsoft.com/source/"]),
    outlet("amazon", ["aboutamazon.com", "aws.amazon.com"], "allowed",
           newsroom=[{"url": "https://www.aboutamazon.com/news", "names": ["Amazon"]},
                     {"url": "https://aws.amazon.com/blogs/aws/",
                      "names": ["AWS", "Amazon Web Services"]}]),
    outlet("samsung", ["samsung.com"], "allowed",
           newsroom=["https://news.samsung.com/global/latest"]),
    outlet("phone_makers", ["vivo.com", "honor.com", "asus.com", "lenovo.com"], "allowed",
           newsroom=["https://www.vivo.com/en/about-vivo/news",
                     "https://www.honor.com/global/news/",
                     "https://press.asus.com/news/",
                     "https://news.lenovo.com/pressroom/press-releases/"]),
    outlet("ev_makers", ["waymo.com", "aurora.tech"], "allowed",
           newsroom=["https://waymo.com/blog/", "https://aurora.tech/newsroom"]),
    outlet("robotics_makers", ["bostondynamics.com", "figure.ai", "unitree.com", "1x.tech"],
           "allowed",
           newsroom=[{"url": "https://bostondynamics.com/blog/", "names": ["Boston Dynamics"]},
                     {"url": "https://www.figure.ai/news", "names": ["Figure AI"]},
                     "https://www.unitree.com/news/",
                     {"url": "https://www.1x.tech/discover", "names": ["1X"]}]),
    outlet("bluesky", ["bsky.social"], "allowed", names=["Bluesky"],
           newsroom=["https://bsky.social/about/blog"]),
    outlet("porsche", ["newsroom.porsche.com"], "allowed", newsroom=[INDEX]),
    outlet("ai_labs", ["mistral.ai", "stability.ai"], "allowed",
           newsroom=["https://mistral.ai/news/",
                     {"url": "https://stability.ai/news-updates", "names": ["Stability AI"]}]),
    outlet("github", ["github.com", "github.blog"], "allowed",
           newsroom=["https://github.blog/changelog/", "https://github.blog/news-insights/"]),
]
REAL_SOURCES = dict(SOURCES, tiers={"1": REAL_ROWS, "2": []})


def opened(title, work=None):
    """The newsroom indexes a topic titled `title` would read (no limit)."""
    texts = vp.topic_texts({"title": title}, work, [])
    indexes, closed = vp.newsroom_indexes(texts, REAL_SOURCES, fs.names_work, limit=99)
    assert not closed, closed
    return [i["index"] for i in indexes]


def test_host_stems_of_the_real_index_hosts():
    stems = {}
    for row in REAL_ROWS:
        for url, _names in vp.newsroom_entries(row):
            host = vp.urllib.parse.urlsplit(url).hostname
            stems[host] = (vp.host_stem(host), vp.stem_names(host))
    assert stems == {
        "blog.google": ("google", ["google"]),            # the service label is not it
        "deepmind.google": ("deepmind", ["deepmind"]),
        "www.anthropic.com": ("anthropic", ["anthropic"]),
        "about.fb.com": ("fb", []),                         # too short - names say Meta
        "news.microsoft.com": ("microsoft", ["microsoft"]),
        "www.aboutamazon.com": ("aboutamazon", ["aboutamazon"]),
        "aws.amazon.com": ("amazon", ["amazon"]),
        "news.samsung.com": ("samsung", ["samsung"]),
        "www.vivo.com": ("vivo", ["vivo"]),
        "www.honor.com": ("honor", []),                     # an everyday word
        "press.asus.com": ("asus", ["asus"]),
        "news.lenovo.com": ("lenovo", ["lenovo"]),
        "waymo.com": ("waymo", ["waymo"]),
        "aurora.tech": ("aurora", []),
        "bostondynamics.com": ("bostondynamics", ["bostondynamics"]),
        "www.figure.ai": ("figure", []),
        "www.unitree.com": ("unitree", ["unitree"]),
        "www.1x.tech": ("1x", []),
        "bsky.social": ("bsky", ["bsky"]),
        "newsroom.porsche.com": ("porsche", ["porsche"]),
        "mistral.ai": ("mistral", ["mistral"]),
        "stability.ai": ("stability", []),
        "github.blog": ("github", ["github"]),
    }
    assert vp.host_stem("news.com") == "" and vp.stem_names("news.com") == []
    assert vp.host_stem("press.example.co.uk") == "example"


def test_a_common_word_in_a_title_opens_no_index():
    for title in ("Five blog tips for creators", "The news this week",
                  "Figure skating app tops the charts", "An honor for the cast",
                  "Aurora borealis seen over London", "Market stability returns",
                  "Press about the about page"):
        assert opened(title) == [], (title, opened(title))


def test_a_vendor_named_by_its_names_or_a_distinctive_stem_opens_its_index():
    assert opened("Figure AI's Figure 03 folds laundry") == ["https://www.figure.ai/news"]
    assert opened("Stability AI ships a new model") == ["https://stability.ai/news-updates"]
    assert opened("Aurora Innovation trucks go driverless") == []      # the row has no names
    assert opened("Honor Magic 8 Pro launches") == []                 # nor here
    google = opened("Google ships Gemini 3")
    assert google[:2] == ["https://blog.google/innovation-and-ai/technology/ai/",
                          "https://blog.google/products-and-platforms/products/"], google
    assert opened("DeepMind's new model") == ["https://deepmind.google/blog/"]
    assert opened("GitHub Copilot gets agents") == ["https://github.blog/changelog/",
                                                    "https://github.blog/news-insights/"]
    assert opened("Unitree R1 robot") == ["https://www.unitree.com/news/"]
    assert opened("Boston Dynamics Atlas") == ["https://bostondynamics.com/blog/"]


# CF-0810 follow-up: the support text (CF-0771) takes the release the fact
# search found on the newsroom index - the topic is told from it.

def test_a_release_found_on_the_newsroom_is_the_support_text():
    c, t = client()
    t_, leads = topic()
    _cands, asked = lookup(t_, leads, c)
    found = [r["url"] for r in asked["pages"] if r["how"] == vp.VIA_NEWSROOM]
    assert found == [RELEASE]
    pieces, rec = st.vendor_pieces(t_, leads, [], SOURCES, c, now="2026-10-19T09:00:00Z",
                                   newsroom=found)
    assert [p["url"] for p in pieces] == [RELEASE] and pieces[0]["outlet"] == "porsche"
    assert "600 km" in pieces[0]["text"] and pieces[0]["kind"] == st.KIND_VENDOR
    assert rec["outcome"] == "ok" and rec["newsroom"] == [RELEASE]
    assert rec["pages"][0]["how"] == "newsroom" and rec["network"] == 0    # the cache's
    assert t.calls == [INDEX, RELEASE]


def test_a_newsroom_release_passes_the_same_door_and_caps():
    c, t = client()
    t_, leads = topic()
    closed_release = "https://www.porsche.com/international/news/mission-s/"
    pieces, rec = st.vendor_pieces(t_, leads, [], SOURCES, c,
                                   newsroom=[closed_release, RELEASE, RELEASE], pages=1)
    assert [p["url"] for p in pieces] == [RELEASE]
    assert [x["url"] for x in rec["closed"]] == [closed_release]       # `unknown`: never asked
    assert t.calls == [RELEASE] and rec["newsroom"] == [closed_release, RELEASE]
    other = "https://newsroom.porsche.com/en/2026/company/porsche-q3-results-43000.html"
    pieces, rec = st.vendor_pieces(t_, leads, [], SOURCES, client(
        {other: (200, "text/html", "<article><p>Q3 results were strong in 2026.</p></article>")}
    )[0], newsroom=[other])
    assert pieces == [] and rec["pages"][0]["outcome"] == "not_about_the_work"


def test_without_a_newsroom_the_support_text_is_as_before():
    c, t = client()
    t_, leads = topic()
    before = st.vendor_pieces(t_, leads, [], SOURCES, c)
    for empty in (None, []):
        assert st.vendor_pieces(t_, leads, [], SOURCES, c, newsroom=empty) == before
    pieces, rec = before
    assert pieces == [] and rec["outcome"] == "no_link" and "newsroom" not in rec
    assert t.calls == []


class _NoWiki:
    request_count = 0

    def page(self, title):  # pragma: no cover - a no_article topic asks nothing
        raise AssertionError(f"asked Wikipedia for {title!r}")


def _pass(sources):
    t_, leads = topic()
    rss = {"entries": [{"link": LEAD, "title": leads[0]["title"], "summary": leads[0]["summary"],
                        "feed_url": "https://www.theverge.com/rss/index.xml"}]}

    def no_article(requests, **kw):
        return {"source": "wikipedia", "asked_at": "2026-10-19T08:44:00Z", "requests": 1,
                "probes": [{"topic_id": r["topic_id"], "asked": r, "outcome": "no_article",
                            "article": None, "candidates": 0, "detail": "no article"}
                           for r in requests]}

    def finder(tp, record, rss_entries, own_urls, sources, client=None):
        return fs.search_topic(tp, record, rss_entries, own_urls, sources, rule, client=None,
                               text_feeds=set())

    def supporter(tp, record, leads_, index):
        return st.support_topic(tp, record, _NoWiki(), None, index=index, leads=leads_,
                                now="2026-10-19T09:00:00Z",
                                vendor_reader=supporter.vendor_reader)
    supporter.vendor_reader = None
    c, t = client()
    b = {"channel": "example-tech", "generated_at": "2026-10-19T09:00:00Z", "topics": [t_]}
    problems, _ = fp.select_batch(b, rss=rss, probe=no_article, finder=finder,
                                  sources=sources, text_feeds=set(), vendor=c,
                                  supporter=supporter)
    assert not problems, problems
    return b, t


def test_the_pass_tells_the_topic_from_its_newsroom_release():
    b, t = _pass(SOURCES)
    assert [x["topic_id"] for x in b["topics"]] == ["t-1"], b.get("skipped_topics")
    top = b["topics"][0]
    vendor_text = [p for p in top[fp.SUPPORT_KEY] if p["kind"] == st.KIND_VENDOR]
    assert [p["url"] for p in vendor_text] == [RELEASE]
    check = top[fp.SUPPORT_CHECK_KEY]
    assert check["state"] == st.STATE_OK and check["vendor_page"]["newsroom"] == [RELEASE]
    assert t.calls == [INDEX, RELEASE]                       # the release read once


def test_the_pass_without_a_newsroom_reads_nothing_more():
    b, t = _pass(without_newsroom(SOURCES))
    assert b["topics"] == [] and t.calls == []


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
