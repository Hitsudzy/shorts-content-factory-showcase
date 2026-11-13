#!/usr/bin/env python3
"""CF-0554: how long the Wikipedia text under a plot reveal has stood -
`shared/factrule/reveal_age.py`.

No network: the client's transport is a stand-in that answers the two
endpoints (`/page/<title>/history`, `/revision/<id>`) out of a synthetic
history modelled on the Harbourlights finale (Q10 of the grill of 2026-10-05): the
episode's description is written ~2-3 h after the broadcast (03:13 UTC on
05.10), the 0701Z batch checks at 07:01 - 3.8 hours later - and the rebuild
at 12:44 is past the 6 hours. The wikitext is a short stand-in, not a copy
of the article."""
import importlib.util
import json
import sys
import tempfile
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FR = ROOT / "shared" / "factrule"
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _tmproot import tmp_root  # noqa: E402

TMP = tmp_root("reveal-age-test-")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ra = _load("reveal_age_cf0554", FR / "reveal_age.py")
wp = ra.wikipedia_api()

KEY = "Harbourlights_(TV_series)"
OLD = ("{{Episode list\n|EpisodeNumber=8\n|Title=Dirt and Stars\n|ShortSummary=\n}}\n"
       "'''''Harbourlights''''' is an American superhero television series.")
SUMMARY = ("{{Episode list\n|EpisodeNumber=8\n|Title=Dirt and Stars\n|ShortSummary="
           "John learns from [[Zorvath]] that Noah freed him. During the game, John tells "
           "Kerry he knows she ''killed'' [[Hal Garrett|Hal]] to protect Noah.<ref name=\"x\" />\n"
           "}}\n'''''Harbourlights''''' is an American superhero television series.")
REWORDED = SUMMARY.replace("she ''killed'' [[Hal Garrett|Hal]]", "someone killed Hal")
QUOTE = "she killed Hal to protect Noah"
PIECE = {"id": f"wikipedia:{KEY}#ep8", "kind": "episode_summary", "source": "wikipedia",
         "revision_id": 104, "revised_at": "2026-10-05T06:48:00Z",
         "text": "John learns from Zorvath that Noah freed him. During the game, John tells "
                 "Kerry he knows she killed Hal to protect Noah."}

HISTORY = [  # oldest first: (id, time, text)
    (100, "2026-10-04T20:00:00Z", OLD),
    (101, "2026-10-05T00:40:00Z", OLD),
    (102, "2026-10-05T03:13:00Z", SUMMARY),       # the description is written
    (103, "2026-10-05T05:00:00Z", SUMMARY + "\n[[Category:x]]"),
    (104, "2026-10-05T06:48:00Z", SUMMARY + "\n[[Category:y]]"),   # the hunter read this
    (105, "2026-10-05T09:27:00Z", SUMMARY + "\nHal Jordan's killer."),
    (106, "2026-10-05T09:46:00Z", SUMMARY + "\n[[Category:y]]"),   # undone
]
WITH_REVERT = HISTORY[:5] + [(105, "2026-10-05T09:27:00Z", REWORDED),
                             (106, "2026-10-05T09:46:00Z", SUMMARY)]


class Wiki:
    """The two endpoints over a list of (id, time, wikitext), 3 a page."""

    def __init__(self, history, per_page=3, down=False):
        self.history = history
        self.per_page = per_page
        self.down = down
        self.urls = []

    def __call__(self, url, headers, timeout=None):
        self.urls.append(url)
        if self.down:
            raise wp.WikipediaError("could not reach the API")
        assert url.startswith(wp.API_BASE), url
        assert "shorts-content-factory" in headers["User-Agent"]
        u = urllib.parse.urlparse(url)
        path = urllib.parse.unquote(u.path[len(urllib.parse.urlparse(wp.API_BASE).path):])
        if path.startswith("/revision/"):
            rid = int(path.rsplit("/", 1)[-1])
            for i, t, text in self.history:
                if i == rid:
                    return wp.HttpResponse(200, json.dumps({"id": i, "timestamp": t,
                                                            "source": text}))
            return wp.HttpResponse(404, "{}")
        assert path == f"/page/{KEY}/history", path
        older = urllib.parse.parse_qs(u.query).get("older_than")
        revs = list(reversed(self.history))
        if older:
            revs = [r for r in revs if r[0] < int(older[0])]
        page = revs[:self.per_page]
        body = {"revisions": [{"id": i, "timestamp": t, "comment": "", "delta": 0}
                              for i, t, _ in page]}
        if len(revs) > self.per_page:
            body["older"] = f"https://en.wikipedia.org/w/rest.php/v1/page/x/history?older_than={page[-1][0]}"
        return wp.HttpResponse(200, json.dumps(body))


def revisions(history=HISTORY, **kw):
    wiki = Wiki(history, **kw)
    client = wp.WikipediaClient(transport=wiki, min_interval=0, sleep=lambda s: None,
                                tool_name=ra.TOOL_NAME)
    return ra.Revisions(client, wp), wiki


def test_the_0701z_batch_finds_the_description_3_8_hours_old():
    revs, _ = revisions()
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T07:01:00Z")
    assert age["state"] == "fresh" and age["stable"] is False, age
    assert age["since_revision"] == 102 and age["since"] == "2026-10-05T03:13:00Z", age
    assert age["age_h"] == 3.8, age


def test_the_1244z_rebuild_finds_it_settled():
    revs, _ = revisions()
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T12:44:00Z")
    assert age["state"] == "stable" and age["stable"] is True, age
    assert age["age_at_least"] is True and age["age_h"] >= 6, age
    # the base (103, in effect at 06:44) and every revision since: 104, 105, 106
    assert age["reads"] == 4, age


def test_a_quote_taken_out_and_put_back_inside_the_window_is_not_settled():
    revs, _ = revisions(WITH_REVERT)
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T12:44:00Z")
    assert age["state"] == "reverted" and not age["stable"], age
    assert age["since_revision"] == 106, age


def test_a_quote_taken_out_after_the_hunter_read_it_is_gone():
    revs, _ = revisions(WITH_REVERT[:6])
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T12:44:00Z")
    assert age["state"] == "gone" and not age["stable"], age


def test_revisions_after_the_check_do_not_exist_for_it():
    revs, _ = revisions(WITH_REVERT)
    # at 09:00 the revert of 09:27 has not happened yet; base 03:00 is r101
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T09:00:00Z")
    assert age["state"] == "fresh" and age["since_revision"] == 102, age


def test_a_replay_before_the_hunter_read_the_words_finds_them_not_written():
    revs, _ = revisions(HISTORY[:2] + [(102, "2026-10-05T03:13:00Z", REWORDED)] + HISTORY[3:])
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T04:00:00Z")
    assert age["state"] == "fresh" and age["age_h"] == 0.0, age


def test_wikitext_is_read_as_its_words():
    assert ra.contains(SUMMARY, QUOTE)
    assert ra.contains(SUMMARY, "John learns from Zorvath that Noah freed him.")
    assert ra.contains("He is {{nowrap|Kerry Kane}}'s son.", "he is Kerry Kane's son")
    assert not ra.contains(REWORDED, QUOTE)
    assert not ra.contains(SUMMARY, "Zorvath killed Hal")
    assert ra.page_key(PIECE) == KEY
    assert ra.page_key({"id": "rss:1", "source": "rss"}) is None


def test_an_unreadable_quote_and_an_unreachable_source_are_not_stable():
    revs, _ = revisions()
    age = ra.quote_age(revs, PIECE, "Hal was shot by the sheriff", now="2026-10-05T12:44:00Z")
    assert age["state"] == "unreadable" and not age["stable"], age
    revs, _ = revisions(down=True)
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T12:44:00Z")
    assert age["state"] == "unreachable" and not age["stable"], age
    revs, _ = revisions()
    age = ra.quote_age(revs, {"id": "rss:1", "source": "rss"}, QUOTE)
    assert age["state"] == "no_page" and not age["stable"]


def test_a_churning_article_is_unsettled_and_reads_are_capped():
    many = [(1, "2026-10-04T20:00:00Z", SUMMARY)] + [
        (10 + i, f"2026-10-05T{7 + i // 10:02d}:{(i % 10) * 5:02d}:00Z", SUMMARY)
        for i in range(ra.MAX_REVISION_READS + 5)]
    revs, wiki = revisions(many, per_page=20)
    age = ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T12:59:00Z")
    assert age["state"] == "unsettled" and not age["stable"], age
    assert sum("/revision/" in u for u in wiki.urls) <= 2, len(wiki.urls)


def test_the_cache_keeps_revisions_and_asks_history_again():
    cache = Path(tempfile.mkdtemp(prefix="cache-", dir=TMP))
    wiki = Wiki(HISTORY)
    revs = ra.revisions_for(cache, transport=wiki, min_interval=0)
    ra.quote_age(revs, PIECE, QUOTE, now="2026-10-05T12:44:00Z")
    first = len(wiki.urls)
    revs2 = ra.revisions_for(cache, transport=wiki, min_interval=0)
    age = ra.quote_age(revs2, PIECE, QUOTE, now="2026-10-05T12:44:00Z")
    assert age["stable"] and len(wiki.urls) == first, "a second run went out again"
    assert any("history" in p.name for p in cache.iterdir())


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"ok   {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
