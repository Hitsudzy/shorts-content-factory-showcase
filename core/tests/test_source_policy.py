#!/usr/bin/env python3
"""CF-0557: the outlets' AI-bot policy - robots.txt read for the AI agents
(`shared/source_policy.py`) and the rule that ties an outlet's `use` to the
verdict (`shared/channel_data.py` `source_policy_errors`).

Every robots.txt here is a fixture string and every fetch a stand-in; the
channels are stand-in roots in temp directories. The one tracked file read is
example-film's own channel data (docs/test-hygiene.md: a tracked channel file
is not live data). Nothing touches the network - the CLI's real fetch is never
called.
"""
import importlib.util
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


sp = _load("source_policy_under_test", ROOT / "shared" / "source_policy.py")
cd = _load("channel_data_for_source_policy_test", ROOT / "shared" / "channel_data.py")

# The shape of Variety / Deadline / THR's file (re-read 2026-10-08): `*`
# keeps only admin and search paths, the AI crawlers get `Disallow: /`.
TRADE_ROBOTS = """\
User-agent: *
Disallow: /wp-admin/
Disallow: /*?s=
Disallow: /search
Allow: /wp-admin/admin-ajax.php

User-agent: anthropic-ai
Disallow: /

User-agent: ClaudeBot
User-agent: Claude-Web
Disallow: /

User-agent: GPTBot
Disallow: /

Sitemap: https://example-trade.com/sitemap.xml
"""
# Wikipedia's shape: the API paths closed to every crawler, articles open,
# no AI agent named.
WIKI_ROBOTS = """\
User-agent: MJ12bot
Disallow: /

User-agent: *
Allow: /w/api.php?action=mobileview&
Disallow: /w/
Disallow: /api/
Disallow: /wiki/Special:
"""
# A wire service that closes everything to everyone.
CLOSED_ROBOTS = "User-agent: *\nDisallow: /\n"


def fake_fetch(table, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return table.get(url, (404, "text/html", ""))
    return fetch


def ok(text):
    return (200, "text/plain", text)


# ------------------------------------------------------------- the parser
def test_the_trade_file_is_open_to_everyone_and_closed_to_the_ai_bots():
    got = sp.read_robots(TRADE_ROBOTS, "/feed/")
    assert got["any_agent"] is True
    assert {"anthropic-ai", "ClaudeBot", "Claude-Web", "GPTBot"} <= set(got["ai_agents_blocked"])
    # an agent the file does not name falls to `*`
    assert "CCBot" not in got["ai_agents_blocked"]
    assert sp.read_robots(TRADE_ROBOTS, "/search?q=x")["any_agent"] is False


def test_the_three_named_agents_are_in_the_one_list():
    for agent in ("anthropic-ai", "ClaudeBot", "Claude-Web"):
        assert agent in sp.AI_AGENTS
    assert len(set(a.lower() for a in sp.AI_AGENTS)) == len(sp.AI_AGENTS)


# CF-0635 (the user's decision of 08.10): only Anthropic's bots or `*` close a
# site; a ban on another company's AI bot is reported and does not count.
OTHERS_ONLY_ROBOTS = """\
User-agent: *
Disallow: /wp-admin/

User-agent: GPTBot
User-agent: CCBot
User-agent: Google-Extended
Disallow: /
"""
CLAUDE_USER_ROBOTS = "User-agent: Claude-User\nDisallow: /\n"
# `*` closed, ClaudeBot let in by name: `*` still closes the site
STAR_CLOSED_CLAUDE_OPEN = "User-agent: *\nDisallow: /\n\nUser-agent: ClaudeBot\nAllow: /\n"


def test_the_anthropic_agents_decide_and_the_other_ai_bots_are_only_reported():
    assert sp.ANTHROPIC_AGENTS == ("anthropic-ai", "ClaudeBot", "Claude-Web",
                                   "Claude-User", "Claude-SearchBot")
    assert sp.AI_AGENTS[:5] == sp.ANTHROPIC_AGENTS and len(sp.AI_AGENTS) == 17
    got = sp.read_robots(OTHERS_ONLY_ROBOTS, "/")
    assert got["any_agent"] is True and got["anthropic_blocked"] == []
    assert set(got["ai_agents_blocked"]) == {"GPTBot", "CCBot", "Google-Extended"}
    assert sp.verdict_of(got) == "allowed"
    url = "https://others.com/robots.txt"
    row = sp.check_url(url, "/", fake_fetch({url: ok(OTHERS_ONLY_ROBOTS)}))
    assert row["verdict"] == "allowed" and len(row["ai_agents_blocked"]) == 3


def test_one_anthropic_agent_or_every_agent_closes_the_site():
    trade = sp.read_robots(TRADE_ROBOTS, "/feed/")
    assert trade["anthropic_blocked"] == ["anthropic-ai", "ClaudeBot", "Claude-Web"]
    assert sp.verdict_of(trade) == "forbidden"
    user = sp.read_robots(CLAUDE_USER_ROBOTS, "/")
    assert user["anthropic_blocked"] == ["Claude-User"] and sp.verdict_of(user) == "forbidden"
    star = sp.read_robots(STAR_CLOSED_CLAUDE_OPEN, "/")
    assert star["any_agent"] is False and "ClaudeBot" not in star["anthropic_blocked"]
    assert sp.verdict_of(star) == "forbidden"
    assert sp.verdict_of(sp.read_robots(CLOSED_ROBOTS, "/")) == "forbidden"
    # a path the `*` group closes is closed, a path it leaves open is not
    assert sp.verdict_of(sp.read_robots(OTHERS_ONLY_ROBOTS, "/wp-admin/x")) == "forbidden"


def test_longest_match_wins_and_allow_wins_a_tie():
    g = sp.parse_robots("User-agent: *\nDisallow: /a\nAllow: /a/b\nAllow: /c\nDisallow: /c\n")
    assert sp.allowed(g, "x", "/a/z") is False
    assert sp.allowed(g, "x", "/a/b/c") is True
    assert sp.allowed(g, "x", "/c") is True          # same length: Allow
    assert sp.allowed(g, "x", "/robots.txt") is True


def test_wildcards_and_the_end_anchor():
    g = sp.parse_robots("User-agent: *\nDisallow: /*.pdf$\nDisallow: /*?s=\n")
    assert sp.allowed(g, "x", "/doc.pdf") is False
    assert sp.allowed(g, "x", "/doc.pdf?x=1") is True
    assert sp.allowed(g, "x", "/page?s=term") is False
    assert sp.allowed(g, "x", "/page") is True


# CF-0637: the lines of www.wikidata.org/robots.txt (read 2026-10-08) that
# decide what the Wikidata client may read - the shared Wikimedia `*` group
# closes /w/ and /wiki/Special:, the Wikidata lines reopen the entity data
# with a format extension and nothing else.
WIKIDATA_ROBOTS = """User-agent: MJ12bot
Disallow: /

User-agent: *
Allow: /w/api.php?action=mobileview&
Allow: /w/load.php?
Disallow: /w/
Disallow: /api/
Disallow: /wiki/Special:
Disallow: /wiki/Special%3A
Disallow: /wiki/Special:EntityData/
Allow: /wiki/Special:EntityData/*.
Disallow: /wiki/Special:ItemByTitle/
"""


def test_wikidata_opens_the_entity_data_with_an_extension_and_closes_the_api():
    groups = sp.parse_robots(WIKIDATA_ROBOTS)
    for path in ("/wiki/Special:EntityData/Q96407897.jsonld",
                 "/wiki/Special:EntityData/Q96407897.json", "/wiki/Q96407897"):
        assert sp.allowed(groups, "*", path), path
        assert sp.verdict_of(sp.read_robots(WIKIDATA_ROBOTS, path)) == "allowed", path
    for path in ("/wiki/Special:EntityData/Q96407897", "/w/api.php?action=wbgetentities",
                 "/wiki/Special:ItemByTitle/enwiki/Coach_Hale", "/w/rest.php/wikibase/v1/entities"):
        assert not sp.allowed(groups, "*", path), path
        assert sp.verdict_of(sp.read_robots(WIKIDATA_ROBOTS, path)) == "forbidden", path


def test_agents_match_by_product_token_case_insensitive_not_by_substring():
    g = sp.parse_robots("User-agent: claudebot/1.0\nDisallow: /\n\nUser-agent: Claude\nDisallow: /x\n")
    assert sp.allowed(g, "ClaudeBot", "/") is False
    assert sp.allowed(g, "Claude-Web", "/") is True   # `Claude` is not `Claude-Web`
    assert sp.allowed(g, "Claude", "/x") is False


def test_groups_naming_the_same_agent_are_merged_and_empty_disallow_allows():
    g = sp.parse_robots("User-agent: GPTBot\nDisallow: /a\n\nUser-agent: GPTBot\nDisallow: /b\n"
                        "\nUser-agent: *\nDisallow:\n")
    assert sp.allowed(g, "GPTBot", "/a") is False and sp.allowed(g, "GPTBot", "/b") is False
    assert sp.allowed(g, "anyone", "/a") is True


def test_no_group_at_all_allows_everything():
    assert sp.read_robots("# nothing here\n", "/") == {"any_agent": True, "anthropic_blocked": [],
                                                       "ai_agents_blocked": []}


# ---------------------------------------------------------- one robots.txt
def test_statuses_404_is_no_file_others_are_unknown():
    url = "https://e.com/robots.txt"
    assert sp.check_url(url, "/", fake_fetch({url: (404, "", "")}))["verdict"] == "allowed"
    assert sp.check_url(url, "/", fake_fetch({url: (410, "", "")}))["verdict"] == "allowed"
    for answer in ((403, "", ""), (401, "", ""), (503, "", ""), (None, "", "URLError: down")):
        row = sp.check_url(url, "/", fake_fetch({url: answer}))
        assert row["verdict"] == "unknown" and row["any_agent"] is None, row


def test_an_html_page_instead_of_robots_is_unknown_not_permission():
    """api.wikimedia.org answers its robots.txt with the wiki's HTML page."""
    url = "https://api.e.org/robots.txt"
    row = sp.check_url(url, "/", fake_fetch({url: (200, "text/html; charset=UTF-8",
                                                     "<!DOCTYPE html><html>...")}))
    assert row["verdict"] == "unknown"


def test_the_policy_takes_the_worst_verdict_and_keeps_what_a_person_wrote():
    checks = [{"verdict": "allowed"}, {"verdict": "unknown"}]
    pol = sp.policy(checks, "2026-10-08", keep={"terms_url": "https://t", "terms_note": "n",
                                               "check_paths": ["/wiki/"], "verdict": "allowed"})
    assert pol["verdict"] == "unknown" and pol["checked_on"] == "2026-10-08"
    assert pol["terms_url"] == "https://t" and pol["terms_note"] == "n"
    assert pol["check_paths"] == ["/wiki/"] and pol["agents"] == sp.AI_AGENTS_VERSION
    assert sp.policy(checks + [{"verdict": "forbidden"}], "d")["verdict"] == "forbidden"
    assert sp.policy([{"verdict": "allowed"}], "d")["terms_url"] is None


# ---------------------------------------------------------- the channel
def make_root(tmp, feeds=None, tiers=None, extra=None):
    root = Path(tmp)
    (root / "patterns").mkdir()
    (root / "patterns" / "validate_patterns.py").write_text("", encoding="utf-8")
    ch = root / "channels"
    (ch / "alpha").mkdir(parents=True)
    cfg = {"channel_id": "alpha", "note": "«кавычки» stay raw",
           "sources": {"rss": {"enabled": True, "house_ceil": 2,
                               "feeds": feeds if feeds is not None else [
                                   {"url": "https://trade.com/feed/", "site": "trade.com",
                                    "house": "h1", "use": "headline_only"},
                                   {"url": "https://feeds.feedburner.com/x/mag", "site": "mag.com",
                                    "house": "h2", "use": "headline_only"}]}}}
    cfg.update(extra or {})
    (ch / "alpha.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False) + "\n",
                                   encoding="utf-8")
    (ch / "alpha" / "fact-sources.json").write_text(json.dumps({
        "kinds": ["discovery", "other"],
        "tiers": tiers if tiers is not None else {
            "1": [{"id": "wiki", "hosts": ["wiki.org", "api.wiki.org"], "use": "read_text",
                   "ai_policy": {"check_hosts": ["en.wiki.org"], "check_paths": ["/wiki/"],
                                 "terms_url": "https://wiki.org/terms"}},
                  {"id": "trade", "hosts": ["trade.com"], "use": "cite_only"}],
            "2": [{"id": "wire", "hosts": ["wire.com"], "use": "cite_only"}]}},
        indent=2) + "\n", encoding="utf-8")
    (ch / "beta").mkdir()
    (ch / "beta.json").write_text(json.dumps({"channel_id": "beta"}), encoding="utf-8")
    return root


ROBOTS = {
    "https://en.wiki.org/robots.txt": ok(WIKI_ROBOTS),
    "https://trade.com/robots.txt": ok(TRADE_ROBOTS),
    "https://mag.com/robots.txt": ok(TRADE_ROBOTS),
    "https://wire.com/robots.txt": ok(CLOSED_ROBOTS),
}


def test_check_channel_reads_each_robots_once_and_checks_the_right_paths():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        calls = []
        rows, sources, config = sp.check_channel("alpha", fake_fetch(ROBOTS, calls),
                                                 "2026-10-08", root)
        assert sorted(calls) == sorted(set(calls)), calls        # one fetch per file
        wiki, trade = sources["tiers"]["1"]
        assert wiki["ai_policy"]["verdict"] == "allowed"
        assert [c["robots_url"] for c in wiki["ai_policy"]["checks"]] == \
            ["https://en.wiki.org/robots.txt"]
        assert wiki["ai_policy"]["terms_url"] == "https://wiki.org/terms"
        assert trade["ai_policy"]["verdict"] == "forbidden"
        wire = sources["tiers"]["2"][0]["ai_policy"]
        assert wire["checks"][0]["any_agent"] is False and wire["verdict"] == "forbidden"
        feed_trade, feed_mag = config["sources"]["rss"]["feeds"]
        assert feed_trade["ai_policy"]["checks"][0]["path"] == "/feed/"
        # a feed served elsewhere is judged on the publisher's file, site root
        assert feed_mag["ai_policy"]["checks"][0]["robots_url"] == "https://mag.com/robots.txt"
        assert feed_mag["ai_policy"]["checks"][0]["path"] == "/"
        assert {r["id"]: r["verdict"] for r in rows}["mag.com"] == "forbidden"


def test_write_puts_the_policy_in_and_leaves_the_rest_of_the_files_as_they_were():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)
        cfg_path = root / "channels" / "alpha.json"
        before = cfg_path.read_text(encoding="utf-8")
        assert sp.main(["check", "alpha", "--write", "--root", str(root)],
                       fetch=fake_fetch(ROBOTS), today="2026-10-08") == 0
        after = cfg_path.read_text(encoding="utf-8")
        head = before[:before.index('"feeds"')]
        assert after.startswith(head) and "«кавычки» stay raw" in after
        assert cd.source_policy_errors("alpha", root) == []
        assert cd.feeds("alpha", root)[0]["ai_policy"]["checked_on"] == "2026-10-08"
        assert cd.fact_sources("alpha", root)["tiers"]["2"][0]["ai_policy"]["verdict"] == "forbidden"


def test_write_reports_a_rule_break_with_a_non_zero_exit():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, tiers={"1": [{"id": "trade", "hosts": ["trade.com"],
                                            "use": "read_text"}]})
        assert sp.main(["check", "alpha", "--write", "--root", str(root)],
                       fetch=fake_fetch(ROBOTS), today="2026-10-08") == 1


def test_replace_value_touches_only_the_value():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "x.json"
        text = ('{\n  "a": "\\u00ab escaped \\u00bb",\n  "b": "«raw»",\n'
                '  "c": {\n    "d": [1, 2],\n    "e": {"f": 1}\n  },\n  "g": true\n}\n')
        path.write_text(text, encoding="utf-8")
        sp.replace_value(path, ("c", "e"), {"f": 2, "h": ["x"]})
        new = path.read_text(encoding="utf-8")
        assert new.startswith('{\n  "a": "\\u00ab escaped \\u00bb",\n  "b": "«raw»",')
        assert json.loads(new)["c"] == {"d": [1, 2], "e": {"f": 2, "h": ["x"]}}
        assert new.endswith('  "g": true\n}\n')


# ------------------------------------------------------------ the rule
def policy_of(verdict, any_agent=True):
    return {"verdict": verdict, "checked_on": "2026-10-08",
            "checks": [{"robots_url": "https://x/robots.txt", "any_agent": any_agent}]}


def test_text_is_read_only_from_an_allowed_outlet():
    rule = cd.entry_policy_errors
    for uses in (cd.TIER_USES, cd.FEED_USES):
        assert rule({"use": "read_text", "ai_policy": policy_of("allowed")}, "e", uses) == []
        for verdict in ("forbidden", "unknown"):
            errs = rule({"use": "read_text", "ai_policy": policy_of(verdict)}, "e", uses)
            assert errs and "must be `allowed`" in errs[0], errs


def test_a_forbidden_outlet_stands_as_a_headline_feed_or_citation():
    rule = cd.entry_policy_errors
    assert rule({"use": "headline_only", "ai_policy": policy_of("forbidden")},
                "f", cd.FEED_USES) == []
    assert rule({"use": "cite_only", "ai_policy": policy_of("forbidden")},
                "t", cd.TIER_USES) == []


def test_the_roles_are_three_and_each_belongs_where_it_means_something():
    """CF-0635: `rss_annotation_only` is gone (a forbidden outlet's excerpt
    no longer reaches the writer); a feed is `headline_only` or `read_text`,
    a tier outlet `read_text` or `cite_only`."""
    assert set(cd.SOURCE_USES) == {"read_text", "headline_only", "cite_only"}
    assert cd.FEED_USES == ("headline_only", "read_text")
    assert cd.TIER_USES == ("read_text", "cite_only")
    rule = cd.entry_policy_errors
    old = rule({"use": "rss_annotation_only", "ai_policy": policy_of("forbidden")},
               "f", cd.FEED_USES)
    assert old and "not one of headline_only, read_text" in old[0], old
    assert rule({"use": "headline_only", "ai_policy": policy_of("allowed")}, "t", cd.TIER_USES)


def test_a_feed_closed_to_every_agent_is_not_read_but_may_be_cited():
    rule = cd.entry_policy_errors
    errs = rule({"use": "headline_only", "ai_policy": policy_of("forbidden", False)},
                "f", cd.FEED_USES)
    assert errs and "every agent" in errs[0]
    assert rule({"use": "cite_only", "ai_policy": policy_of("forbidden", False)},
                "t", cd.TIER_USES) == []


def test_an_entry_without_use_or_policy_or_with_a_wrong_use_is_an_error():
    rule = cd.entry_policy_errors
    assert "`use`" in rule({"ai_policy": policy_of("allowed")}, "e", cd.TIER_USES)[0]
    assert "source_policy.py" in rule({"use": "cite_only"}, "e", cd.TIER_USES)[0]
    assert rule({"use": "cite_only", "ai_policy": policy_of("allowed")}, "f", cd.FEED_USES)
    bad = dict(policy_of("allowed"), verdict="maybe", checked_on="08.10")
    assert len(rule({"use": "cite_only", "ai_policy": bad}, "e", cd.TIER_USES)) == 2


def test_feed_urls_refuses_a_channel_that_breaks_the_rule_and_a_stub_has_nothing():
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp)          # no ai_policy written yet
        assert cd.source_policy_errors("alpha", root)
        try:
            cd.feed_urls("alpha", root)
        except cd.ChannelDataError as exc:
            assert "ai_policy" in str(exc)
        else:
            raise AssertionError("feed_urls read a channel that breaks the rule")
        assert cd.feeds("beta", root) == [] and cd.source_policy_errors("beta", root) == []
        sp.main(["check", "alpha", "--write", "--root", str(root)],
                fetch=fake_fetch(ROBOTS), today="2026-10-08")
        assert cd.feed_urls("alpha", root) == ["https://trade.com/feed/",
                                               "https://feeds.feedburner.com/x/mag"]


def test_only_a_text_feed_gives_the_writer_its_excerpt():
    """`support_feed_urls`: the feeds whose excerpt may go into the support
    text - a `read_text` feed of an allowed outlet, never a `headline_only`
    one; a channel that breaks the rule is refused, as by `feed_urls`."""
    feeds = [{"url": "https://trade.com/feed/", "site": "trade.com", "house": "h1",
              "use": "headline_only"},
             {"url": "https://open.com/feed/", "site": "open.com", "house": "h3",
              "use": "read_text"}]
    robots = dict(ROBOTS, **{"https://open.com/robots.txt": ok(OTHERS_ONLY_ROBOTS)})
    with tempfile.TemporaryDirectory() as tmp:
        root = make_root(tmp, feeds=feeds)
        try:
            cd.support_feed_urls("alpha", root)
        except cd.ChannelDataError:
            pass
        else:
            raise AssertionError("support_feed_urls read a channel without ai_policy")
        assert sp.main(["check", "alpha", "--write", "--root", str(root)],
                       fetch=fake_fetch(robots), today="2026-10-08") == 0
        assert cd.feed_urls("alpha", root) == ["https://trade.com/feed/",
                                               "https://open.com/feed/"]
        assert cd.support_feed_urls("alpha", root) == ["https://open.com/feed/"]
        assert cd.support_feed_urls("beta", root) == []


# ------------------------------------------------------ example-film itself
def test_example_film_keeps_the_rule():
    assert cd.source_policy_errors("example-film", ROOT) == []


def test_example_film_reads_text_only_from_wikipedia_tvmaze_wikidata_and_feeds_only_for_headlines():
    sources = cd.fact_sources("example-film", ROOT)
    readers = [row["id"] for rows in sources["tiers"].values() for row in rows
               if row["use"] in cd.TEXT_USES]
    # CF-0636 (the user's decision of 08.10 on CF-0557 Q2): TVmaze's episode
    # descriptions, read through its API - no robots.txt there, CC BY-SA
    # CF-0637 (the same decision): Wikidata's statements, CC0, read as
    # Special:EntityData/<Q>.jsonld - the one Special: path its robots.txt
    # opens to every agent
    assert readers == ["wikipedia", "tvmaze", "wikidata"]
    wikidata = [row for rows in sources["tiers"].values() for row in rows
                if row["id"] == "wikidata"][0]
    assert wikidata["hosts"] == ["www.wikidata.org"]
    assert wikidata["ai_policy"]["verdict"] == "allowed"
    assert {c["path"] for c in wikidata["ai_policy"]["checks"]} >= {
        "/wiki/Special:EntityData/Q96407897.jsonld"}
    # every property the channel reads names one of its kinds of fact
    assert set(wikidata["properties"].values()) <= set(sources["kinds"])
    tvmaze = [row for rows in sources["tiers"].values() for row in rows
              if row["id"] == "tvmaze"][0]
    assert "api.tvmaze.com" in tvmaze["hosts"]
    assert tvmaze["ai_policy"]["verdict"] == "allowed"
    assert {c["robots_url"]: c["status"] for c in tvmaze["ai_policy"]["checks"]}[
        "https://api.tvmaze.com/robots.txt"] == 404
    # the user's decision of 08.10 (CF-0635): the PMC and Vulture feeds choose
    # topics, their excerpts are not the writer's support text
    for feed in cd.feeds("example-film", ROOT):
        assert feed["use"] == "headline_only", feed["site"]
    assert cd.support_feed_urls("example-film", ROOT) == []
    # the four trade feeds the CF-0546 grill named close themselves to
    # Anthropic's bots (re-read under the CF-0635 rule)
    verdicts = {f["site"]: f["ai_policy"]["verdict"] for f in cd.feeds("example-film", ROOT)}
    assert verdicts == {"variety.com": "forbidden", "deadline.com": "forbidden",
                        "hollywoodreporter.com": "forbidden", "vulture.com": "forbidden"}




# --------------------------------------- CF-0810: terms read, or named only
def _row_policy(verdict, **extra):
    pol = policy_of(verdict)
    pol.update(extra)
    return {"id": "v", "hosts": ["v.com"], "use": "cite_only", "ai_policy": pol}


def test_a_row_whose_terms_were_not_read_is_never_allowed():
    rule = cd.entry_policy_errors
    unread = _row_policy("allowed", terms_read=False)
    errs = rule(unread, "e", cd.TIER_USES)
    assert errs and "terms_read` is false" in errs[0] and "named only" in errs[0], errs
    # named only: unknown or forbidden with unread terms is what it should be
    for verdict in ("unknown", "forbidden"):
        assert rule(_row_policy(verdict, terms_read=False), "e", cd.TIER_USES) == []
    # read terms say what they say; the rows allowed before CF-0810 keep theirs
    assert rule(_row_policy("allowed", terms_read=True, terms_note="no AI ban"),
                "e", cd.TIER_USES) == []
    assert rule(_row_policy("allowed", terms_read="unrecorded"), "e", cd.TIER_USES) == []
    # a stand-in without the marker still reads (the agents' frozen lists)
    assert rule(_row_policy("allowed"), "e", cd.TIER_USES) == []


def test_the_terms_marker_has_three_values_and_true_needs_its_note():
    rule = cd.entry_policy_errors
    for bad in ("yes", 1, None, "read"):
        errs = rule(_row_policy("unknown", terms_read=bad), "e", cd.TIER_USES)
        assert errs and "terms_read` is" in errs[0], (bad, errs)
    for note in (None, "", "  "):
        pol = {"terms_read": True}
        if note is not None:
            pol["terms_note"] = note
        errs = rule(_row_policy("allowed", **pol), "e", cd.TIER_USES)
        assert errs and "no `terms_note`" in errs[0], errs


def test_the_root_validator_wants_every_tier_one_row_to_say_whether_its_terms_were_read():
    tried = "CF-0816, 2026-10-24: not read - the terms page answers 403"
    doc = {"tiers": {"1": [_row_policy("allowed", terms_read="unrecorded", terms_note=tried),
                           dict(_row_policy("unknown"), id="named")],
                     "2": [dict(_row_policy("allowed"), id="tier2")]}}
    errs = cd.terms_marker_errors("alpha", doc)
    assert len(errs) == 1 and "tiers.1[named]" in errs[0] and "terms_read" in errs[0], errs
    assert cd.terms_marker_errors("alpha", None) == []


def test_an_allowed_row_left_unrecorded_says_why_its_terms_were_not_read():
    """CF-0816: the rows made `allowed` by robots.txt before CF-0810 had their
    terms read on 24.10; one still "unrecorded" is one whose terms page could
    not be read, and its note says so - no allowed row is left without a word
    on its terms."""
    def errs(**pol):
        return cd.terms_marker_errors("alpha", {"tiers": {"1": [_row_policy("allowed", **pol)]}})
    assert errs(terms_read="unrecorded")
    assert errs(terms_read="unrecorded", terms_note="read 24.10: no AI ban")
    msg = errs(terms_read="unrecorded")[0]
    assert "tiers.1[v]" in msg and "not read" in msg and "CF-0816" in msg, msg
    for note in ("not read - 403 Cloudflare",
                 "CF-0816, 2026-10-24: not read - the page is drawn by script"):
        assert errs(terms_read="unrecorded", terms_note=note) == [], note
    # read, or named only: nothing more to say here
    assert errs(terms_read=True, terms_note="no AI or scraping clause") == []
    unknown = {"tiers": {"1": [_row_policy("unknown", terms_read="unrecorded")]}}
    assert cd.terms_marker_errors("alpha", unknown) == []


def test_a_ban_in_the_terms_closes_the_row_whatever_robots_txt_says():
    """CF-0816: terms that ban robots, scraping or AI use close the outlet
    (the rule of 08.10, TMDB): `terms_verdict: "forbidden"` needs the terms
    read and the verdict forbidden."""
    rule = cd.entry_policy_errors
    note = "read: «You may not use any robot, spider ... to access the Site»"
    closed = _row_policy("forbidden", terms_read=True, terms_note=note,
                         terms_verdict="forbidden")
    assert rule(closed, "e", cd.TIER_USES) == []
    errs = rule(dict(closed, ai_policy=dict(closed["ai_policy"], verdict="allowed")),
                "e", cd.TIER_USES)
    assert errs and "terms forbid it" in errs[0] and "CF-0816" in errs[0], errs
    for marker in (False, "unrecorded"):
        pol = dict(closed["ai_policy"], terms_read=marker)
        errs = rule(dict(closed, ai_policy=pol), "e", cd.TIER_USES)
        assert errs and "is not true" in errs[0], (marker, errs)
    errs = rule(_row_policy("forbidden", terms_read=True, terms_note=note,
                            terms_verdict="allowed"), "e", cd.TIER_USES)
    assert errs and "terms_verdict` is 'allowed'" in errs[0], errs


def test_a_recheck_keeps_a_row_the_terms_closed_forbidden():
    with tempfile.TemporaryDirectory() as tmp:
        pol = {"terms_url": "https://open.com/terms", "terms_read": True,
               "terms_note": "read: robots and scrapers banned", "terms_verdict": "forbidden"}
        root = make_root(tmp, feeds=[], tiers={"1": [
            {"id": "vendor", "hosts": ["open.com"], "use": "cite_only", "ai_policy": pol}]})
        rows, sources, _ = sp.check_channel("alpha", fake_fetch(OPEN), "2026-10-24", root)
        got = sources["tiers"]["1"][0]["ai_policy"]
        assert got["checks"][0]["verdict"] == "allowed"          # robots.txt itself is open
        assert got["verdict"] == "forbidden" and got["terms_verdict"] == "forbidden"
        assert "terms ban" in got["held"] and "CF-0816" in got["held"], got
        assert rows[0]["held"] is True
        assert sp.main(["check", "alpha", "--write", "--root", str(root)],
                       fetch=fake_fetch(OPEN), today="2026-10-24") == 0
        written = cd.fact_sources("alpha", root)["tiers"]["1"][0]["ai_policy"]
        assert written["verdict"] == "forbidden" and written["terms_verdict"] == "forbidden"
        assert cd.source_policy_errors("alpha", root) == []
        # robots.txt closed too: forbidden on its own, nothing held
        closed = dict(ROBOTS, **{"https://open.com/robots.txt": ok(CLOSED_ROBOTS)})
        _, sources, _ = sp.check_channel("alpha", fake_fetch(closed), "2026-10-24", root)
        got = sources["tiers"]["1"][0]["ai_policy"]
        assert got["verdict"] == "forbidden" and "held" not in got


def _unread_root(tmp, marker):
    pol = {"terms_url": None}
    if marker is not None:
        pol["terms_read"] = marker
    if marker is True:
        pol["terms_note"] = "read: no AI or scraping ban"
    return make_root(tmp, feeds=[], tiers={"1": [
        {"id": "wiki", "hosts": ["wiki.org"], "use": "read_text",
         "ai_policy": {"check_hosts": ["en.wiki.org"], "check_paths": ["/wiki/"],
                       "terms_read": True, "terms_note": "CC BY-SA"}},
        {"id": "vendor", "hosts": ["open.com"], "use": "cite_only", "ai_policy": pol}]})


OPEN = dict(ROBOTS, **{"https://open.com/robots.txt": ok("User-agent: *\nAllow: /\n")})


def test_a_recheck_never_turns_a_named_only_row_readable():
    with tempfile.TemporaryDirectory() as tmp:
        root = _unread_root(tmp, False)
        rows, sources, _ = sp.check_channel("alpha", fake_fetch(OPEN), "2026-10-19", root)
        pol = sources["tiers"]["1"][1]["ai_policy"]
        assert pol["checks"][0]["verdict"] == "allowed"     # robots.txt itself is open
        assert pol["verdict"] == "unknown" and pol["terms_read"] is False
        assert "terms were not read" in pol["held"], pol
        assert {r["id"]: r["held"] for r in rows} == {"wiki": False, "vendor": True}
        # written: the file keeps the row named only, and the rule is kept
        assert sp.main(["check", "alpha", "--write", "--root", str(root)],
                       fetch=fake_fetch(OPEN), today="2026-10-19") == 0
        written = cd.fact_sources("alpha", root)["tiers"]["1"][1]["ai_policy"]
        assert written["verdict"] == "unknown" and written["terms_read"] is False
        assert cd.source_policy_errors("alpha", root) == []


def test_a_recheck_opens_a_row_once_its_terms_are_read_or_it_predates_the_record():
    for marker in (True, "unrecorded", None):
        with tempfile.TemporaryDirectory() as tmp:
            root = _unread_root(tmp, marker)
            _, sources, _ = sp.check_channel("alpha", fake_fetch(OPEN), "2026-10-19", root)
            pol = sources["tiers"]["1"][1]["ai_policy"]
            assert pol["verdict"] == "allowed" and "held" not in pol, (marker, pol)
            assert pol.get("terms_read", None) == marker
    # a held row is held only while robots.txt is open - closed stays forbidden
    with tempfile.TemporaryDirectory() as tmp:
        root = _unread_root(tmp, False)
        closed = dict(ROBOTS, **{"https://open.com/robots.txt": ok(CLOSED_ROBOTS)})
        _, sources, _ = sp.check_channel("alpha", fake_fetch(closed), "2026-10-19", root)
        pol = sources["tiers"]["1"][1]["ai_policy"]
        assert pol["verdict"] == "forbidden" and "held" not in pol


def test_every_channel_says_whether_its_tier_one_terms_were_read():
    """The real lists: every tier-1 row carries `terms_read`; the rows named
    only for unread terms (CF-0792, CF-0810, the `_unverified` splits of
    CF-0757) say false, so no re-check opens them."""
    for channel in ("example-film", "example-science", "example-tech"):
        sources = cd.fact_sources(channel, ROOT)
        assert cd.terms_marker_errors(channel, sources) == [], channel
        assert cd.source_policy_errors(channel, ROOT) == [], channel
        for row in sources["tiers"]["1"]:
            pol = row["ai_policy"]
            if pol["verdict"] != "allowed":
                assert pol["terms_read"] in (True, False), (channel, row["id"])
            if row["id"].endswith("_unverified") or row["id"] in (
                    "blue_origin", "epic_games", "meta_named_unread"):
                assert pol["terms_read"] is False, (channel, row["id"])
    tech = {r["id"]: r["ai_policy"] for r in cd.fact_sources("example-tech", ROOT)["tiers"]["1"]}
    assert tech["porsche"]["terms_read"] is True and tech["porsche"]["verdict"] == "allowed"


def test_the_rows_allowed_before_the_record_had_their_terms_read():
    """CF-0816: the 36 tier-1 rows made `allowed` by robots.txt before CF-0810
    (21 Tech, 15 Science) had their terms read on 24.10. Each is read (true,
    with what the terms say), closed by a ban in them (`terms_verdict`
    forbidden, the clause quoted - the rule of 08.10), or still "unrecorded"
    with a note saying why the page could not be read; Reel had none."""
    seen = {}
    for channel in ("example-tech", "example-science"):
        src = cd.fact_sources(channel, ROOT)
        # CF-0914 moved Tech's list on (new vendor rows); CF-0816 stays in its history
        assert src["version"] == {"example-tech": "CF-0914", "example-science": "CF-0816"}[channel], \
            channel
        assert any(h.startswith("CF-0816") for h in src["version_history"]), channel
        for row in src["tiers"]["1"]:
            pol = row["ai_policy"]
            if "CF-0816" not in (pol.get("terms_note") or ""):
                continue
            seen[(channel, row["id"])] = pol
            if pol["terms_read"] == "unrecorded":
                assert pol["verdict"] == "allowed" and "not read - " in pol["terms_note"], row["id"]
                assert "terms_verdict" not in pol, row["id"]
            else:
                assert pol["terms_read"] is True, row["id"]
            if pol.get("terms_verdict") == "forbidden":
                assert pol["verdict"] == "forbidden" and "«" in pol["terms_note"], row["id"]
                assert "newsroom" not in row, row["id"]
            # robots.txt itself stays open on every one of them
            assert all(c["verdict"] == "allowed" for c in pol["checks"]), row["id"]
    closed = {k for k, p in seen.items() if p.get("terms_verdict") == "forbidden"}
    unread = {k for k, p in seen.items() if p["terms_read"] == "unrecorded"}
    tech = lambda *ids: {("example-tech", i) for i in ids}
    sci = lambda *ids: {("example-science", i) for i in ids}
    assert closed == tech("apple", "anthropic", "amazon", "nvidia", "samsung", "ev_makers",
                          "phone_makers_terms_closed", "robotics_makers_terms_closed",
                          "ai_labs_terms_closed") | sci("aps"), closed
    assert unread == tech("openai", "meta", "acm", "chipmakers_terms_unread",
                          "phone_makers_terms_unread", "ev_makers_terms_unread",
                          "robotics_makers_terms_unread", "ai_labs_terms_unread",
                          "benchmark_orgs_terms_unread") \
        | sci("pnas", "aanda", "agu", "royal_society", "oup"), unread
    assert len({k for k in seen if k[0] == "example-science"}) == 15
    # nothing is left "unrecorded" without a word on it, in any channel
    for channel in ("example-film", "example-science", "example-tech"):
        for row in cd.fact_sources(channel, ROOT)["tiers"]["1"]:
            pol = row["ai_policy"]
            if pol.get("terms_read") == "unrecorded":
                assert "not read - " in (pol.get("terms_note") or ""), (channel, row["id"])




def main():
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  ok  {name}")
        except Exception as exc:  # noqa: BLE001
            failed += 1
            print(f"FAIL  {name}: {type(exc).__name__}: {exc}")
    print(f"{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
