#!/usr/bin/env python3
"""CF-0263: the fact lookup as a probe another stage can run.

Since the grill of 2026-09-17 (decision of CF-0260) the question "does this
topic have a production fact behind it?" is asked at **topic selection**, not
after the footage has been downloaded. A topic with no findable fact is never
chosen; the slot goes to the next candidate, and the probe's answer is written
into `skipped_topics[]` with its code, because DoD 1.4.4 item 1 allows no
silent loss. Trend Hunter (CF-0264) is the caller; this file is the handle it
calls, so that the rule, the selection rule for sentences, the ceiling of
three requests per title, the one-second floor between requests and the
`Retry-After` courtesy all stay in one place - `production_facts.py` and
`wikipedia_api.py` - instead of being re-implemented in a second agent.

**Nothing here is a second copy of anything.** This file parses arguments,
runs `production_facts.find_production_facts` through one client, and prints
what came back. A topic that falls back to the parent work it names costs two
titles' worth of requests (`wikipedia_api.MAX_REQUESTS_PER_TOPIC`, 6) and
never more.

Usage::

    # one topic
    python3 scripts/fact_probe.py --title "Rennick: Quill" --type tv_series

    # a shortlist, in one process, so the pacing is shared between them
    python3 scripts/fact_probe.py --topics topics.json
    echo '[{"name": "Wren Hollow", "type": "tv_series"}]' | \
        python3 scripts/fact_probe.py --topics -

`--topics` takes a JSON array of `{name, type, year, season, network, parent,
topic_id, news}`; only `name` is required and everything else is a hint. It
also accepts a Trend Hunter batch file (`01-trend-hunter.json`), whose
`topics[]` carry the same fields under `title_ref` (`news` is read off the
topic: its scene descriptions and evidence headlines).

**The article has to be the news's edition** (CF-0812, `edition_check.py`).
`news` is the topic's own text - headlines, summaries, scene descriptions -
and an article titled with an edition (`Tesla Roadster (first generation)`,
`The Scarab (1999 film)`) that this text, the name and the year do not name,
and that is not current or that the topic's year / a "sequel" points away
from, is not the topic's article: the next candidate is read, and when none
fits the answer is `wrong_article` with the reason in `detail` ("article ...
is about another edition (...) than the topic ..."). `news` is not echoed
under `asked`.

**The answer**, on stdout, always this shape::

    {
      "source": "wikipedia",
      "requests": 3,                      # spent on this whole run
      "probes": [
        {
          "topic_id": null,
          "asked": {"name": "Rennick: Quill", "type": "tv_series",
                    "year": null, "season": null, "network": null,
                    "parent": null},
          "outcome": "ok",                # ok | no_article | no_section |
                                          # no_candidates | wrong_article |
                                          # source_unreachable
          "has_fact": true,               # outcome == "ok"
          "usable": true,                 # has_fact, or the source was
                                          # unreachable - see below
          "article": "Rennick (TV series)",
          "article_url": "https://en.wikipedia.org/wiki/Rennick_(TV_series)",
          "candidates": 2,
          "parent_work": "Rennick (TV series)",
          "detail": null,                 # why `wrong_article`, or the error
          "requests": 3
        }
      ]
    }

**`usable` is not `has_fact`.** A source that could not be asked is not a
topic without a fact - that distinction is the whole of CF-0185's third state
and it is kept here, at the other end of the pipeline: an unreachable
Wikipedia must never quietly empty a shortlist. A caller filtering on
`has_fact` would drop every topic during an outage; one filtering on `usable`
drops none of them and lets the writer's own refusal rule judge later.

Exit codes: 0 - every topic was asked about; 2 - usage, or the source could
not be asked at all (the JSON is still printed, with `source_unreachable` on
the topics that were not reached).

Stdlib only; no venv in this repository.
"""
import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/
from production_facts import (STATUS_OK, find_production_facts,  # noqa: E402
                              topics_of_batch)
from wikipedia_api import WikipediaClient, WikipediaError  # noqa: E402
import edition_check  # noqa: E402

SOURCE = "wikipedia"
# The word the probe answers with when our side could not ask. The same word
# `fact_refusal.py` uses for that state, on purpose: one vocabulary across the
# two ends of the pipeline (CF-0185 `source_unreachable`).
OUTCOME_UNREACHABLE = "source_unreachable"

HINT_KEYS = ("name", "type", "year", "season", "network", "parent")


def probe(topic, client, limit=1, now_year=None):
    """One topic's answer, in the shape above. `limit` is 1 by default: the
    caller is asking whether a fact exists, not collecting them - the writer
    runs the full lookup later for the topics that survive. `topic["news"]`,
    when the caller gives it, is the topic's own news text the article's
    edition is held against (CF-0812); it is not echoed under `asked`."""
    answer = {"topic_id": topic.get("topic_id"),
              "asked": {key: topic.get(key) for key in HINT_KEYS},
              "outcome": None, "has_fact": False, "usable": False,
              "article": None, "article_url": None, "candidates": 0,
              "parent_work": None, "detail": None, "requests": 0}
    before = client.request_count
    try:
        result = find_production_facts(
            topic["name"], year=topic.get("year"), season=topic.get("season"),
            work_type=topic.get("type"), network=topic.get("network"),
            parent=topic.get("parent"), client=client, limit=limit,
            news=topic.get("news"), now_year=now_year)
    except WikipediaError as error:
        answer["outcome"] = OUTCOME_UNREACHABLE
        answer["usable"] = True          # not a topic without a fact
        answer["detail"] = str(error)
        answer["requests"] = client.request_count - before
        return answer
    article = result.get("article") or {}
    answer["outcome"] = result["status"]
    answer["has_fact"] = result["status"] == STATUS_OK
    answer["usable"] = answer["has_fact"]
    answer["article"] = article.get("title")
    answer["article_url"] = article.get("url")
    answer["candidates"] = len(result.get("candidates") or [])
    answer["parent_work"] = result.get("parent_work")
    answer["detail"] = (result.get("article_check") or {}).get("detail")
    # CF-0828: a `no_article` whose every candidate was a disambiguation page
    # says so, in the free-form `detail` the hunter already carries.
    if result.get("sub_reason"):
        pages = ", ".join(result.get("skipped_articles") or [])
        answer["detail"] = (f"{result['sub_reason']}"
                            + (f": {pages}" if pages else ""))
    answer["requests"] = client.request_count - before
    return answer


def topics_of(path):
    """The topics to probe, out of a JSON array or a Trend Hunter batch."""
    text = sys.stdin.read() if str(path) == "-" else Path(path).read_text()
    data = json.loads(text)
    if isinstance(data, dict) and "topics" in data:
        if str(path) == "-":
            return _from_batch_payload(data)
        return topics_of_batch(path)
    if isinstance(data, dict):
        data = [data]
    topics = []
    for item in data:
        if isinstance(item, str):
            item = {"name": item}
        if not isinstance(item, dict) or not item.get("name"):
            continue
        topic = {key: item.get(key) for key in HINT_KEYS}
        topic["topic_id"] = item.get("topic_id")
        topic["news"] = item.get("news")
        topics.append(topic)
    return topics


def _from_batch_payload(data):
    topics = []
    for topic in data.get("topics", []):
        ref = topic.get("title_ref") or {}
        if not ref.get("name"):
            continue
        topics.append({"topic_id": topic.get("topic_id"), "name": ref["name"],
                       "year": ref.get("year"), "season": ref.get("season"),
                       "type": ref.get("type"),
                       "network": ref.get("network") or ref.get("studio"),
                       "parent": ref.get("parent_work") or ref.get("parent"),
                       "news": edition_check.news_of_topic(topic)})
    return topics


def build_parser():
    parser = argparse.ArgumentParser(
        description="Does this topic have a production fact behind it? "
                    "(CF-0263; the lookup is CF-0184's, unchanged)")
    parser.add_argument("--title", help="one topic, by name")
    parser.add_argument("--type", dest="work_type",
                        help="tv_series, film - what the topic is known to be")
    parser.add_argument("--year")
    parser.add_argument("--season")
    parser.add_argument("--network", help="network or studio, when known")
    parser.add_argument("--parent",
                        help="the parent work the topic's own news name")
    parser.add_argument("--news", help="the topic's own news text (headline, summary, "
                                       "scene descriptions) - CF-0812")
    parser.add_argument("--topic-id", help="carried through to the answer")
    parser.add_argument("--topics", help="a JSON array of topics, a Trend "
                                         "Hunter batch, or `-` for stdin")
    parser.add_argument("--limit", type=int, default=1,
                        help="candidates to collect per topic (default 1: the "
                             "question is whether one exists)")
    return parser


def main(argv=None, client=None, out=None):
    out = sys.stdout if out is None else out   # CF-0915: read at the call, after _pipe_safe.guard()
    args = build_parser().parse_args(argv)
    if bool(args.title) == bool(args.topics):
        build_parser().print_usage(sys.stderr)
        print("give --title or --topics, not both and not neither",
              file=sys.stderr)
        return 2
    if args.topics:
        topics = topics_of(args.topics)
    else:
        topics = [{"topic_id": args.topic_id, "name": args.title,
                   "type": args.work_type, "year": args.year,
                   "season": args.season, "network": args.network,
                   "parent": args.parent, "news": args.news}]
    client = client or WikipediaClient()
    probes = [probe(topic, client, limit=args.limit) for topic in topics]
    payload = {"source": SOURCE,
               "asked_at": datetime.datetime.now(
                   datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
               "requests": client.request_count,
               "probes": probes}
    print(json.dumps(payload, ensure_ascii=False, indent=1), file=out)
    unreachable = any(p["outcome"] == OUTCOME_UNREACHABLE for p in probes)
    if unreachable:
        print(f"{SOURCE} unavailable: "
              f"{next(p['detail'] for p in probes if p['detail'])}",
              file=sys.stderr)
    return 2 if unreachable else 0


if __name__ == "__main__":
    import _pipe_safe  # CF-0915: a closed pipe (`| head`) is not a crash
    _pipe_safe.guard()
    sys.exit(main())
