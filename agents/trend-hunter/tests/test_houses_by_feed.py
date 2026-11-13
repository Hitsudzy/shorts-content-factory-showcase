#!/usr/bin/env python3
"""CF-0753: a link's house is the house of the feed that carried it.

example-tech/2026-10-15T1854Z died three times in `score_candidates.py
--houses` (and 2026-10-16T0702Z twice) on Hacker News entries: the aggregator's
feed (`news.ycombinator.com/rss`, house `ycombinator`) links each entry to the
story itself - research.meta.ai, citizenlab.ca, support.withings.com - and the
domain rule raised `ValueError: ... is not a site of any feed`, taking the
candidate's other houses with it. Pinned here: the fetch's `feed_url` decides
(the same rule as candidate_pool.py, CF-0772), the domain is the fallback, a
link nothing places is reported and never a crash, and a company's own feed
(`kind: vendor`) adds no house. Stand-in configs and fetches only; no network,
no live channel files.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))

import score_candidates as sc  # noqa: E402

HN = "https://news.ycombinator.com/rss"
CONFIG = {"sources": {"rss": {"house_ceil": 2, "feeds": [
    {"url": "https://www.theverge.com/rss/index.xml", "site": "theverge.com", "house": "pmc"},
    {"url": "https://techcrunch.com/feed/", "site": "techcrunch.com", "house": "regent"},
    {"url": HN, "site": "news.ycombinator.com", "house": "ycombinator"},
    {"url": "https://huggingface.co/blog/feed.xml", "site": "huggingface.co", "house": "huggingface"},
    {"url": "https://about.fb.com/feed/", "site": "about.fb.com", "house": "meta", "kind": "vendor"},
]}}}

VERGE = "https://www.theverge.com/news/1012293/meta-apple-muse-spark-open-ai-model-mlx"
META_RESEARCH = "https://research.meta.ai/blog/muse-spark-open"     # an HN entry, 1854Z
HF = "https://huggingface.co/blog/meta-muse-spark-open"
WITHINGS = ("https://support.withings.com/hc/en-us/community/posts/51887047154577-"
            "Unacceptable-Apple-Health-Sync-is-now-behind-a-99-year-paywall-for-new-accounts")
FETCH = {"source": "rss", "entries": [
    {"feed": "The Verge", "feed_url": "https://www.theverge.com/rss/index.xml", "link": VERGE},
    {"feed": "Hacker News", "feed_url": HN, "link": META_RESEARCH + "/"},   # trailing slash
    {"feed": "Hacker News", "feed_url": HN, "link": WITHINGS},
    {"feed": "Hugging Face", "feed_url": "https://huggingface.co/blog/feed.xml", "link": HF},
    {"feed": "Meta Newsroom", "feed_url": "https://about.fb.com/feed/",
     "link": "https://about.fb.com/news/2026/10/muse-spark-open/"},
]}


def test_an_aggregator_entry_is_the_house_of_its_feed_not_of_its_domain():
    found = sc.attribute_links([VERGE, META_RESEARCH, HF], CONFIG,
                               sc.entry_feeds(FETCH["entries"]))
    assert found["houses"] == {"pmc", "ycombinator", "huggingface"}, found
    assert found["unattributed"] == []


def test_a_link_nothing_places_is_reported_and_the_other_houses_stay():
    """The 1854Z call without a fetch: research.meta.ai is on no `site`. It is
    listed, the Verge and Hugging Face links still count - no ValueError."""
    found = sc.attribute_links([VERGE, META_RESEARCH, HF], CONFIG)
    assert found["houses"] == {"pmc", "huggingface"}, found
    assert found["unattributed"] == [META_RESEARCH]


def test_a_company_s_own_feed_adds_no_house_by_feed_or_by_domain():
    link = "https://about.fb.com/news/2026/10/muse-spark-open/"
    for feeds in (sc.entry_feeds(FETCH["entries"]), None):
        found = sc.attribute_links([link, VERGE], CONFIG, feeds)
        assert found["houses"] == {"pmc"} and found["vendor_feeds"] == {"meta"}, found


def test_the_domain_rule_still_refuses_an_unknown_site():
    """house_for_link keeps raising: its callers catch it (attribute_links,
    fetch_channel_feeds) - a guess is never made."""
    try:
        sc.house_for_link(META_RESEARCH, sc.feed_houses(CONFIG))
    except ValueError:
        return
    raise AssertionError("research.meta.ai was attributed to a house the config never lists")


def _cli(argv):
    out, err = io.StringIO(), io.StringIO()
    old = sys.argv
    sys.argv = ["score_candidates.py", *argv]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = sc._main()
    finally:
        sys.argv = old
    return code, out.getvalue(), err.getvalue()


def test_the_houses_command_takes_the_fetch_and_never_crashes():
    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "example-tech.json"
        config.write_text(json.dumps(CONFIG))
        rss = Path(tmp) / "rss.json"
        rss.write_text(json.dumps(FETCH))
        # the 0702Z call: Withings' forum post (HN) next to The Verge
        code, out, err = _cli(["--houses", WITHINGS, VERGE, "--channel-config", str(config),
                               "--rss", str(rss)])
        assert code == 0, err
        got = json.loads(out)
        assert got["houses"] == ["pmc", "ycombinator"] and got["distinct_rss_houses"] == 2, got
        assert got["unattributed_links"] == [] and err == "", (got, err)
        # the same call with no fetch: counted, listed, warned - exit 0
        code, out, err = _cli(["--houses", WITHINGS, VERGE, "--channel-config", str(config)])
        got = json.loads(out)
        assert code == 0 and got["houses"] == ["pmc"], got
        assert got["unattributed_links"] == [WITHINGS], got
        assert "support.withings.com" in err and "--rss" in err, err


def test_a_replayed_topic_is_attributed_by_its_evidence_sources_feed():
    topic = {"evidence": {"rss_links": [VERGE, META_RESEARCH],
                          "sources": [{"url": VERGE, "feed": "https://www.theverge.com/rss/index.xml"},
                                      {"url": META_RESEARCH, "feed": HN}]}}
    found = sc.attribute_links(topic["evidence"]["rss_links"], CONFIG, sc.topic_link_feeds(topic))
    assert found["houses"] == {"pmc", "ycombinator"}, found


def test_fetch_channel_feeds_reads_an_aggregator_link_by_its_feed():
    import fetch_channel_feeds as fcf
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / "channels").mkdir()
        (Path(tmp) / "channels" / "example-tech.json").write_text(json.dumps(CONFIG))
        topic = {"evidence": {"rss_links": [META_RESEARCH, "https://about.fb.com/news/x/"],
                              "sources": [{"url": META_RESEARCH, "feed": HN},
                                          {"url": "https://about.fb.com/news/x/",
                                           "feed": "https://about.fb.com/feed/"}]}}
        got = fcf.topic_houses(topic, "example-tech", root=tmp)
        assert got == ["ycombinator", "meta"], got


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
        except AssertionError as exc:
            failures += 1
            print(f"  FAIL {name}: {exc}")
    print(f"\n{ran - failures}/{ran} passed")
    sys.exit(1 if failures else 0)
