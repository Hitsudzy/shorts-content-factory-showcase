#!/usr/bin/env python3
"""CF-0638, item 1: how many topics held their fact only on a news candidate.

`fact_search.news_candidates` used to make a fact candidate out of a feed
entry ("Variety reported ..."), its summary as the text. The user's decision of
08.10 (CF-0557 Q1 variant b): the feeds are for choosing topics, the writer gets
no excerpt of them - so a `headline_only` feed's entry gives no fact candidate
any more. Before that change this script asks the channel's past batches what
it costs: a topic whose every *passing* candidate was a news one would have
left as `no_fact` without it.

An analysis over the channel's real batches, read-only - not a test (a test
never reads live batches). The result is written into
`docs/news-facts-2026-10.md` by hand.

Per batch, from `01-trend-hunter.json` (`fact_candidates[]` with the rule's
`check`, recorded since CF-0438) and `03-content-researcher.json`:

  - `selected`         topics[] of the batch
  - `with_candidates`  of them, the ones with a recorded candidate list
  - `news_any`         a passing news candidate among the topic's candidates
  - `news_only`        every passing candidate a news one - the topic would
                       have become `no_fact` (the loss this task asks about)
  - `reserve_news_only` the same over `below_shortlist` reserve topics
  - `writer_used_news` scripts whose `fact` is a news candidate
  - `news_cands`       passing news candidates; `of_summary` the ones whose
                       text was the feed summary (not the headline)

A news candidate is told by what `news_candidates` writes: an `attribution`
"<outlet> reported" and a URL that is not Wikipedia's.

CF-0638 item 3 (`evidence.sources[].summary` of a `headline_only` feed is no
longer written): the summary is still read by one mechanical check, the
fact-to-scene fit (the root's `fact_scene.world_texts`, through
`check_scenes.fact_fit`, CF-0548). The replay strips every summary (example-film
has no `read_text` feed) and every news candidate and judges the fit again:

  - `sources_with_summary` evidence sources that carried a summary
  - `fit_lost`         topics that fitted a scene and would not (-> `no_fact`)
  - `first_fit_changed` topics whose first fitting passing candidate changes

    scripts/news_fact_measure.py [--root <factory checkout>] --channel example-film [--json]

`--root` is the checkout whose `pipeline/<channel>/` is read (default: the
production checkout this agent's worktree belongs to, else the agent's root).
"""
import argparse
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT = HERE.parent


def default_root():
    # <root>/.worktrees/release-x/agents/trend-hunter -> <root>
    for up in AGENT.parents:
        if up.name == ".worktrees" and (up.parent / "pipeline").is_dir():
            return up.parent
    root = AGENT.parent.parent
    return root if (root / "pipeline").is_dir() else AGENT


def is_news(cand):
    url = str((cand or {}).get("url") or "")
    return bool(cand.get("attribution")) and "wikipedia.org" not in url


def passing(cands):
    return [c for c in cands or [] if (c.get("check") or {}).get("passes")]


def of_summary(cand):
    head = (cand.get("headline") or "").strip()
    return bool(cand.get("text")) and cand.get("text") != head


def _load(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def measure_batch(batch_dir):
    hunter = _load(Path(batch_dir) / "01-trend-hunter.json") or {}
    writer = _load(Path(batch_dir) / "03-content-researcher.json") or {}
    row = {"batch": Path(batch_dir).name, "selected": 0, "with_candidates": 0,
           "news_any": 0, "news_only": 0, "reserve_news_only": 0,
           "writer_used_news": 0, "news_cands": 0, "of_summary": 0,
           "news_only_topics": [], "writer_news_topics": [],
           "sources_with_summary": 0, "fit_lost": 0, "first_fit_changed": 0,
           "fit_lost_topics": [], "first_fit_changed_topics": []}
    for topic in hunter.get("topics") or []:
        row["selected"] += 1
        cands = topic.get("fact_candidates")
        if cands is None:
            continue
        row["with_candidates"] += 1
        ok = passing(cands)
        news = [c for c in ok if is_news(c)]
        row["news_cands"] += len(news)
        row["of_summary"] += sum(1 for c in news if of_summary(c))
        if news:
            row["news_any"] += 1
            if len(news) == len(ok):
                row["news_only"] += 1
                row["news_only_topics"].append(topic.get("topic_id"))
    for skipped in hunter.get("skipped_topics") or []:
        if skipped.get("reason_code") != "below_shortlist":
            continue
        ok = passing(skipped.get("fact_candidates"))
        if ok and all(is_news(c) for c in ok):
            row["reserve_news_only"] += 1
    replay_fit(hunter, row)
    for script in writer.get("scripts") or []:
        fact = script.get("fact") or {}
        if fact and is_news(fact):
            row["writer_used_news"] += 1
            row["writer_news_topics"].append(script.get("topic_id"))
    return row


def _first_fit(annotated, scenes_key):
    for c in annotated or []:
        if (c.get("check") or {}).get("passes") and c.get(scenes_key):
            return c.get("text")
    return None


def replay_fit(hunter, row):
    """The fact-to-scene fit with the feed summaries and the news candidates
    gone, against the fit as recorded (see the module's docstring)."""
    import copy
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    import check_scenes
    key = check_scenes.fact_scene.SCENES_KEY
    tops = [t for t in hunter.get("topics") or []
            if isinstance(t.get("fact_candidates"), list) and t.get("scenes")]
    row["sources_with_summary"] = sum(1 for t in tops
                                      for s in (t.get("evidence") or {}).get("sources") or []
                                      if isinstance(s, dict) and s.get("summary"))
    stripped = copy.deepcopy(tops)
    for t in stripped:
        for s in (t.get("evidence") or {}).get("sources") or []:
            if isinstance(s, dict):
                s["summary"] = None
        t["fact_candidates"] = [c for c in t["fact_candidates"] if not is_news(c)]
    for before, after in zip(tops, stripped):
        was, was_off = check_scenes.fact_fit(copy.deepcopy(before), tops)
        now, now_off = check_scenes.fact_fit(after, stripped)
        if now_off and not was_off:
            row["fit_lost"] += 1
            row["fit_lost_topics"].append(before.get("topic_id"))
        if _first_fit(was, key) != _first_fit(now, key):
            row["first_fit_changed"] += 1
            row["first_fit_changed_topics"].append(before.get("topic_id"))


def measure(root, channel):
    rows = []
    for path in sorted(glob.glob(str(Path(root) / "pipeline" / channel / "*" / "01-trend-hunter.json"))):
        rows.append(measure_batch(Path(path).parent))
    keys = ("selected", "with_candidates", "news_any", "news_only", "reserve_news_only",
            "writer_used_news", "news_cands", "of_summary", "sources_with_summary",
            "fit_lost", "first_fit_changed")
    total = {k: sum(r[k] for r in rows) for k in keys}
    total["batches"] = len(rows)
    total["batches_with_candidates"] = sum(1 for r in rows if r["with_candidates"])
    base = total["with_candidates"]
    total["news_only_share"] = round(total["news_only"] / base, 4) if base else None
    return {"channel": channel, "root": str(root), "batches": rows, "total": total}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--channel", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    out = measure(Path(args.root) if args.root else default_root(), args.channel)
    if args.json:
        json.dump(out, sys.stdout, ensure_ascii=False, indent=1)
        print()
        return 0
    print("batch              sel cand news_any news_only reserve_only writer_news news_cands of_summary")
    for r in out["batches"]:
        print(f"{r['batch']:<18} {r['selected']:>3} {r['with_candidates']:>4} {r['news_any']:>8} "
              f"{r['news_only']:>9} {r['reserve_news_only']:>12} {r['writer_used_news']:>11} "
              f"{r['news_cands']:>10} {r['of_summary']:>10}")
    t = out["total"]
    print(f"total: {t['batches']} batches, {t['batches_with_candidates']} with candidates; "
          f"selected {t['selected']}, with candidates {t['with_candidates']}, news_any {t['news_any']}, "
          f"news_only {t['news_only']} (share {t['news_only_share']}), reserve news_only "
          f"{t['reserve_news_only']}, writer used news {t['writer_used_news']}, "
          f"news candidates {t['news_cands']} ({t['of_summary']} of a summary)")
    print(f"fit replay without feed summaries and news candidates: sources with a summary "
          f"{t['sources_with_summary']}, topics losing their fit {t['fit_lost']}, first fitting "
          f"candidate changed {t['first_fit_changed']} "
          f"{[x for r in out['batches'] for x in r['first_fit_changed_topics']]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
