#!/usr/bin/env python3
"""CF-0914: a vendor's newsroom index may be its RSS / Atom feed, and the
company's own post may name the work without the company's name.

Batch ExampleTech 2026-11-02T0838Z selected 0 of 42 topics: 25 left as
`vendor_page=no_link` - "OpenAI AI compute campuses", "GM Smart Driver",
"Nscale West Virginia data center"... - fresh company news with no Wikipedia
article, whose trade coverage links no tier-1 page. The newsroom path of
CF-0810 read an HTML index only, matched a release only by the work's whole
name ("GM Smart Driver" - which GM's own newsroom never writes), and the
reason did not say which company the topic named. These tests pin the step:
an index that answers XML is read as a feed (the same door, client, cache and
ceiling), its entries on the row's own outlet are matched by the work's name
with or without the company's, a post that refuses the client (openai.com
answers 403, its feed does not) is told from its entry, a feed that declares
entities is never parsed, and a `no_link` reason names the company and why
it was not read. The fact rule itself is not touched. Nothing leaves the
machine: a stand-in transport and a stand-in list.
"""
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
    return {"verdict": verdict, "checked_on": "2026-11-02", "checks": [], "terms_url": None}


def outlet(oid, hosts, verdict, **extra):
    return dict({"id": oid, "hosts": hosts, "use": "cite_only", "ai_policy": policy(verdict)},
                **extra)


GM_FEED = "https://news.gm.com/feed.rss"
GM_POST = "https://news.gm.com/home.detail.html/Pages/news/us/en/2026/oct/smart-driver-update.html"
GM_OTHER = "https://news.gm.com/home.detail.html/Pages/news/us/en/2026/oct/q3-results.html"
OAI_FEED = "https://openai.com/news/rss.xml"
OAI_POST = "https://openai.com/index/ai-compute-campuses"
APPLE_FEED = "https://www.apple.com/newsroom/rss-feed.rss"

# A stand-in of a tech channel's list (never the tracked file).
SOURCES = {
    "version": "test",
    "kinds": ["spec", "price", "release_date", "model_card", "benchmark", "paper", "law", "other"],
    "attributed_kinds": ["benchmark"],
    "tiers": {
        "1": [outlet("gm", ["news.gm.com"], "allowed", newsroom=[GM_FEED], names=["GM"]),
              outlet("openai", ["openai.com"], "allowed", newsroom=[OAI_FEED]),
              outlet("apple", ["apple.com"], "forbidden", newsroom=[APPLE_FEED]),
              outlet("intel", ["intel.com"], "allowed")],
        "2": [outlet("ars_technica", ["arstechnica.com"], "forbidden")],
    },
    "any_host": [],
    "do_not_take": [],
}

GM_RSS = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/"><channel>
<title>GM Newsroom</title><link>https://news.gm.com/</link>
<item><title>Third-quarter results</title><link>{GM_OTHER}</link>
  <description>GM reports its third-quarter results.</description></item>
<item><title>An update on the Smart Driver program</title><link>{GM_POST}</link>
  <description>&lt;p&gt;What changes for customers.&lt;/p&gt;</description>
  <pubDate>Fri, 30 Oct 2026 14:00:00 GMT</pubDate></item>
<item><title>Smart Driver elsewhere</title><link>https://elsewhere.example/smart-driver</link></item>
<item><title>Home</title><link>https://news.gm.com/</link></item>
</channel></rss>"""
GM_PAGE = """<!doctype html><html><head><title>An update on the Smart Driver program</title>
<meta property="og:site_name" content="GM Newsroom"></head><body><article>
<h1>An update on the Smart Driver program</h1>
<p>GM ended the Smart Driver program in April 2024 and stopped sharing driving data.</p>
<p>The settlement covers about 1.8 million vehicles sold between 2015 and 2024.</p>
<p>We remain committed to our customers.</p></article></body></html>"""
OAI_ATOM = f"""<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"><title>OpenAI News</title>
<entry><title>Our AI compute campuses</title>
  <link rel="alternate" href="{OAI_POST}"/>
  <summary type="html">&lt;p&gt;Why we call our data centers campuses.&lt;/p&gt;</summary>
  <content type="html">&lt;p&gt;The first AI compute campus in Abilene, Texas will draw
  1.2 gigawatts when it is complete in 2027.&lt;/p&gt;</content>
  <updated>2026-11-01T10:00:00Z</updated></entry>
</feed>"""
ENTITY_RSS = """<?xml version="1.0"?><!DOCTYPE rss [<!ENTITY a "aaaaaaaa">]>
<rss><channel><item><title>&a;</title><link>https://news.gm.com/x</link></item></channel></rss>"""

PAGES = {GM_FEED: (200, "application/rss+xml; charset=utf-8", GM_RSS),
         GM_POST: (200, "text/html; charset=utf-8", GM_PAGE),
         OAI_FEED: (200, "text/xml; charset=utf-8", OAI_ATOM),
         OAI_POST: (403, "text/html", "Just a moment...")}


class Transport:
    def __init__(self, pages):
        self.pages, self.calls, self.headers = pages, [], []

    def __call__(self, url, headers, timeout, max_bytes, allow):
        self.calls.append(url)
        self.headers.append(headers)
        status, ctype, body = self.pages.get(url, (404, "text/html", ""))
        raw = body.encode("utf-8")
        return status, ctype, url, raw[:max_bytes], len(raw) > max_bytes


def client(pages=None, **kw):
    t = Transport(dict(PAGES, **(pages or {})))
    return vp.PageClient(transport=t, delay=0, **kw), t


LEAD = "https://arstechnica.com/cars/2026/10/gm-to-pay-220-million-smart-driver/"


def topic(name="GM Smart Driver", lead_title="GM to pay $220 million after selling "
          "customer Smart Driver data", summary="A settlement with the FTC."):
    lead = {"url": LEAD, "title": lead_title, "summary": summary}
    t = {"topic_id": "t-1", "title_ref": {"name": name, "kind": "work", "type": "product"},
         "signal": {"popularity_score": 70.0},
         "evidence": {"sources": [{"url": LEAD, "title": lead_title}], "rss_links": [LEAD]}}
    return t, [lead]


def lookup(t, leads, c, sources=SOURCES, pool=()):
    return vp.lookup(t, leads, list(pool), sources, rule, c, fs.names_work,
                     news_text=fp.news_text_of(leads))


def passing(cands, leads, sources=SOURCES):
    return [x for x in rule.check_candidates(cands, sources, news_text=fp.news_text_of(leads))
            if x[rule.CHECK_KEY]["passes"]]


# --------------------------------------------------------------------------

def test_an_rss_and_an_atom_feed_are_read_as_entries():
    gm = vp.feed_entries(GM_RSS.encode("utf-8"))
    assert [e["link"] for e in gm][:2] == [GM_OTHER, GM_POST] and len(gm) == 4
    assert gm[1]["title"] == "An update on the Smart Driver program"
    assert gm[1]["summary"] == "What changes for customers."          # escaped HTML read
    assert gm[1]["published"].startswith("Fri, 30 Oct 2026")
    oai = vp.feed_entries(OAI_ATOM)
    assert oai[0]["link"] == OAI_POST and oai[0]["summary"].startswith("Why we call")
    assert "1.2 gigawatts" in oai[0]["text"]                             # Atom content
    assert vp.feed_entries(b"<html><body>no feed</body></html>") is None
    assert vp.feed_entries(b"not xml at all <") is None
    assert vp.feed_entries(ENTITY_RSS) is None                           # nothing expanded


def test_the_work_s_name_without_its_company():
    assert vp.work_names("GM Smart Driver", ["GM"]) == ["GM Smart Driver", "smart driver"]
    assert vp.work_names("Apple's HomeView", ["Apple"]) == ["Apple's HomeView", "homeview"]
    assert vp.work_names("Nscale West Virginia data center", ["nscale"])[1] == \
        "west virginia data center"
    assert vp.work_names("Smart Driver GM", ["GM"])[1] == "smart driver"
    # the rest is no name of its own: too short, or one everyday word
    assert vp.work_names("Intel stock", ["intel"]) == ["Intel stock"]
    assert vp.work_names("OpenAI Jev", ["openai"]) == ["OpenAI Jev"]
    assert vp.work_names("Google Wi-Fi", ["google"]) == ["Google Wi-Fi", "wi fi"]
    # another company's name is never cut
    assert vp.work_names("GM Smart Driver", ["Ford"]) == ["GM Smart Driver"]
    # nor is another company of the list a work
    assert vp.work_names("Nvidia Nscale", ["nscale"]) == ["Nvidia Nscale", "nvidia"]
    assert vp.work_names("Nvidia Nscale", ["nscale"], {"nvidia"}) == ["Nvidia Nscale"]
    assert "openai" in vp.list_names(SOURCES) and "gm" in vp.list_names(SOURCES)
    # a work that is the company itself names no release of its own newsroom
    assert vp.release_names("Reddit", ["Reddit"]) == []
    assert vp.release_names("GM Smart Driver", ["GM"]) == ["GM Smart Driver", "smart driver"]
    assert vp.row_names(SOURCES["tiers"]["1"][0]) == ["GM"]          # "gm" is too short a stem
    assert vp.row_names(SOURCES["tiers"]["1"][1]) == ["openai"]


def test_a_feed_index_gives_the_release_that_names_the_work_without_its_company():
    c, t = client()
    t_, leads = topic()
    cands, asked = lookup(t_, leads, c)
    assert t.calls == [GM_FEED, GM_POST]                 # never GM_OTHER, never elsewhere
    assert "application/rss+xml" in t.headers[0]["Accept"]
    assert t.headers[1]["Accept"] == "text/html,application/xhtml+xml"   # a post is HTML only
    assert asked["outcome"] == "ok" and asked["via"] == vp.VIA_NEWSROOM
    rec = asked["newsroom"][0]
    assert rec["kind"] == "feed" and rec["outcome"] == "matched" and rec["named"] == "GM"
    assert rec["matched"] == [GM_POST] and rec["links"] == 2       # GM_OTHER, GM_POST
    assert "company" not in rec
    assert asked["pages"][0]["url"] == GM_POST and asked["pages"][0]["how"] == "newsroom"
    good = passing(cands, leads)
    assert good and good[0]["url"] == GM_POST and good[0]["source"] == "gm"


def test_a_feed_with_no_entry_naming_the_work_says_newsroom_no_match():
    c, t = client()
    t_, leads = topic(name="GM Ultium battery", lead_title="GM shows its Ultium battery")
    cands, asked = lookup(t_, leads, c)
    assert t.calls == [GM_FEED] and cands == []
    assert asked["outcome"] == "newsroom_no_match"
    assert asked["newsroom"][0]["kind"] == "feed"
    assert "news.gm.com/feed.rss newsroom: newsroom_no_match" in asked["where"]


def test_a_post_that_refuses_the_client_is_told_from_its_feed_entry():
    c, t = client()
    t_, leads = topic(name="OpenAI AI compute campuses",
                      lead_title="OpenAI might rebrand its data centers as AI compute campuses",
                      summary="A report.")
    cands, asked = lookup(t_, leads, c)
    assert t.calls == [OAI_FEED, OAI_POST]
    row = asked["pages"][0]
    assert row["url"] == OAI_POST and row["read"] == vp.VIA_FEED_ENTRY == "feed_entry"
    assert "answered 403" in row["detail"] and row["outcome"] == "ok"
    good = passing(cands, leads)
    assert good and "1.2 gigawatts" in good[0]["text"] and good[0]["url"] == OAI_POST
    # an entry with no text of its own is no page: the post stays unreachable
    thin = OAI_ATOM.replace("<content", "<x").replace("</content>", "</x>")
    c2, _t2 = client({OAI_FEED: (200, "application/atom+xml", thin)})
    _c, asked2 = lookup(t_, leads, c2)
    assert asked2["pages"][0]["outcome"] == "unreachable" and asked2["outcome"] == "unreachable"


def test_a_topic_whose_work_is_the_company_takes_no_post_of_its_feed():
    c, t = client()
    t_, leads = topic(name="GM", lead_title="GM to pay $220 million")
    _c, asked = lookup(t_, leads, c)
    assert t.calls == [GM_FEED] and asked["outcome"] == "newsroom_no_match"


def test_a_feed_that_declares_entities_is_unreachable_not_parsed():
    c, t = client({GM_FEED: (200, "application/rss+xml", ENTITY_RSS)})
    t_, leads = topic()
    _c, asked = lookup(t_, leads, c)
    assert t.calls == [GM_FEED] and asked["outcome"] == "unreachable"
    assert "not a readable RSS / Atom feed" in asked["newsroom"][0]["detail"]


def test_an_xml_post_is_still_no_page_and_the_feed_is_cached():
    c, t = client({GM_POST: (200, "application/rss+xml", GM_RSS)})
    assert "not an HTML page" in c.page(GM_POST, SOURCES)["error"]
    first = c.page(GM_FEED, SOURCES, index=True)
    assert first["feed"] and len(first["entries"]) == 4
    assert c.page(GM_FEED, SOURCES, index=True) is first and t.calls.count(GM_FEED) == 1


def test_a_feed_on_a_forbidden_row_is_never_asked():
    c, t = client({APPLE_FEED: (200, "application/rss+xml", GM_RSS)})
    t_, leads = topic(name="Apple HomeView", lead_title="Apple's HomeView could add cameras")
    _c, asked = lookup(t_, leads, c)
    assert t.calls == [] and asked["outcome"] == "closed"
    assert asked["closed"][0]["how"] == vp.HOW_INDEX and asked["closed"][0]["verdict"] == \
        "forbidden"


def test_a_no_link_reason_names_the_company_and_why_it_was_not_read():
    c, t = client()
    t_, leads = topic(name="Intel 18A", lead_title="Intel ships 18A chips")
    _c, asked = lookup(t_, leads, c)
    assert t.calls == [] and asked["outcome"] == "no_link"
    assert asked["where"] == ("no tier-1 link in the topic's news or the pool; named "
                              "intel.com: allowed, no newsroom listed"), asked["where"]
    t2, leads2 = topic(name="Nscale data center", lead_title="Nscale builds in West Virginia")
    _c, asked2 = lookup(t2, leads2, c)
    assert asked2["where"] == "no tier-1 link in the topic's news or the pool"


def test_a_pool_entry_of_the_company_s_own_feed_names_the_work_without_its_company():
    c, t = client()
    t_, leads = topic()
    pool = [{"link": GM_POST, "title": "An update on the Smart Driver program",
             "summary": "", "feed_url": GM_FEED},
            {"link": GM_OTHER, "title": "Third-quarter results", "summary": "",
             "feed_url": GM_FEED}]
    links = vp.official_links("GM Smart Driver", leads, pool, SOURCES, rule, fs.names_work)
    assert links == [(GM_POST, "vendor_feed")]
    # the cut is the post's own company only: OpenAI's feed does not get GM's
    other = [{"link": "https://openai.com/index/smart-driver", "title": "Smart Driver",
              "summary": "", "feed_url": OAI_FEED}]
    assert vp.official_links("GM Smart Driver", leads, other, SOURCES, rule,
                             fs.names_work) == []


def test_the_support_text_takes_a_post_that_names_the_work_without_its_company():
    c, t = client()
    t_, leads = topic()
    pieces, rec = st.vendor_pieces(t_, leads, [], SOURCES, c, newsroom=[GM_POST])
    assert len(pieces) == 1 and pieces[0]["url"] == GM_POST, rec


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok   {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"  FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
