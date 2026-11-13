#!/usr/bin/env python3
"""CF-0914: the vendor-feed path replayed on a channel's batch records - no
network.

For every topic a batch refused as `no_fact` with `vendor_page=no_link` or
`newsroom_no_match` (the no_fact memory's repeats aside), it rebuilds what
`vendor_page.lookup` sees - the work's name, the topic's leads (the
candidate pool's headlines, the RSS output's summaries) and the batch's pool
- and says what the CF-0914 path would do with the channel's list, plus the
rows of `--assume` (the vendor domains proposed for tier 1, as list rows):

  pool_link      a pool entry of the company's own feed now names the work
                 (`official_links` with `work_names`);
  feed_match     a newsroom index / feed of an `allowed` row the topic names
                 would be read and a saved copy of it (`--feeds`) has an
                 entry or link naming the work;
  feed_no_match  read, nothing there names the work;
  feed_unsaved   would be read, no saved copy to judge it by;
  named_closed   the topic names a tier-1 company whose verdict is not
                 `allowed` - named, never read;
  named_unindexed  an `allowed` row is named, it lists no newsroom / feed;
  unnamed        no tier-1 company is named.

`--feeds` is a JSON map `{index_url: saved_file}` of copies read by hand
(read-only, public pages); an XML copy is read as a feed, HTML as an index.
Whether a matched release's sentences pass the fact rule is not judged here
(the post itself is not saved) - `feed_match` is the topics that reach a
vendor page, the ceiling of what the path can give.

    python3 scripts/vendor_feed_replay.py --root <factory> --channel example-tech \\
        --since 2026-10-25 --until 2026-11-02 [--assume rows.json] [--feeds map.json]
"""
import argparse
import collections
import copy
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import fact_rule  # noqa: E402
import fact_search  # noqa: E402
import vendor_page as vp  # noqa: E402

REFUSED = ("no_link", "newsroom_no_match")
_VP_RE = re.compile(r"vendor_page=(\w+)\(")


def refused_topics(batch_dir):
    """`[(skipped_record, outcome)]` of a batch's `vendor_page` refusals."""
    path = Path(batch_dir) / "01-trend-hunter.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for rec in data.get("skipped_topics") or []:
        if rec.get("reason_code") != "no_fact":
            continue
        if (rec.get("fact_probe") or {}).get("source") == "no_fact_memory":
            continue
        m = _VP_RE.search(rec.get("reason") or "")
        if m and m.group(1) in REFUSED:
            out.append((rec, m.group(1)))
    return out


def batch_news(batch_dir):
    """`(pool_entries, leads_by_key)` of a batch: the RSS output's entries and,
    per topic id / lower-case name, the candidate pool's headlines with the
    RSS summaries."""
    work = Path(batch_dir) / "work"
    try:
        rss = json.loads((work / "rss.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rss = {}
    entries = rss.get("entries") or []
    by_link = {e.get("link"): e for e in entries if e.get("link")}
    try:
        pool = json.loads((work / "candidate-pool.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pool = {}
    leads = {}
    for cand in pool.get("candidates") or []:
        rows = []
        for head in cand.get("headlines") or []:
            entry = by_link.get(head.get("link")) or {}
            rows.append({"url": head.get("link"), "title": head.get("title"),
                         "summary": entry.get("summary")})
        for key in (cand.get("topic_id"), (cand.get("name") or "").lower()):
            if key:
                leads.setdefault(key, rows)
    return entries, leads


def load_saved(feeds_map):
    """`{index_url: page}` of the hand-saved copies, read the way the client
    reads an index (XML -> feed entries, else HTML links)."""
    out = {}
    for url, file in (feeds_map or {}).items():
        try:
            raw = Path(file).read_bytes()
        except OSError:
            continue
        entries = vp.feed_entries(raw) if raw.lstrip()[:200].lower().startswith(
            (b"<?xml", b"<rss", b"<feed", b"<rdf")) else None
        if entries is not None:
            out[url] = {"url": url, "final_url": url, "feed": True, "entries": entries}
        else:
            out[url] = {"url": url, "final_url": url,
                        "links": vp.html_links(raw.decode("utf-8", "replace"))}
    return out


def classify(rec, leads, pool_entries, sources, saved):
    """`(verdict, detail)` of one refused topic under the CF-0914 path."""
    work = ((rec.get("fact_probe") or {}).get("asked") or {}).get("name") or rec.get("title")
    topic = {"topic_id": rec.get("topic_id"), "title": rec.get("title"),
             "title_ref": {"name": work}}
    names_work = fact_search.names_work
    links = vp.official_links(work, leads, pool_entries, sources, fact_rule, names_work)
    if links:
        return "pool_link", [u for u, _ in links]
    texts = vp.topic_texts(topic, work, leads)
    indexes, closed = vp.newsroom_indexes(texts, sources, names_work, limit=99)
    if indexes:
        seen = []
        for item in indexes:
            page = saved.get(item["index"])
            if page is None:
                continue
            seen.append(item["index"])
            names = vp.release_names(work, item.get("company") or [], vp.list_names(sources))
            if page.get("feed"):
                found, _own, _e = vp.feed_releases(page, item["index"], item["outlet"],
                                                   sources, names, names_work)
            else:
                found, _own = vp.newsroom_releases(page, item["index"], work, names_work,
                                                   names=names)
            if found:
                return "feed_match", found
        if seen:
            return "feed_no_match", seen
        return "feed_unsaved", [i["index"] for i in indexes]
    named = vp.named_outlets(texts, sources, names_work)
    if any(n["verdict"] != "allowed" for n in named) or closed:
        return "named_closed", sorted({n["host"] for n in named if n["verdict"] != "allowed"}
                                      | {c.get("host") for c in closed})
    if named:
        return "named_unindexed", [n["host"] for n in named]
    return "unnamed", []


def with_rows(sources, rows):
    out = copy.deepcopy(sources)
    tier = out.setdefault("tiers", {}).setdefault("1", [])
    for row in rows or []:
        tier[:] = [r for r in tier if r.get("id") != row.get("id")]
        tier.append(row)
    return out


def replay(batch_dirs, sources, saved):
    rows, seen = [], set()
    for bdir in batch_dirs:
        pool_entries, leads_by = batch_news(bdir)
        for rec, outcome in refused_topics(bdir):
            leads = leads_by.get(rec.get("topic_id")) or \
                leads_by.get((rec.get("title") or "").lower()) or []
            verdict, detail = classify(rec, leads, pool_entries, sources, saved)
            key = vp._norm(rec.get("title")).strip()
            rows.append({"batch": Path(bdir).name, "topic_id": rec.get("topic_id"),
                         "title": rec.get("title"), "was": outcome, "now": verdict,
                         "detail": detail, "repeat": key in seen})
            seen.add(key)
    return rows


def summary(rows):
    total = collections.Counter(r["now"] for r in rows)
    unique = collections.Counter(r["now"] for r in rows if not r["repeat"])
    return {"refused": len(rows), "unique_topics": sum(1 for r in rows if not r["repeat"]),
            "by_verdict": dict(total), "unique_by_verdict": dict(unique)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", required=True, help="the factory checkout (pipeline/, channels/)")
    ap.add_argument("--channel", required=True)
    ap.add_argument("--sources", help="the fact-sources list (default: the root's)")
    ap.add_argument("--since", default="")
    ap.add_argument("--until", default="9999")
    ap.add_argument("--assume", help="JSON list of tier-1 rows to add (proposed vendors)")
    ap.add_argument("--feeds", help="JSON map {index_url: saved copy}")
    ap.add_argument("--rows", action="store_true", help="print every topic's row")
    args = ap.parse_args(argv)
    root = Path(args.root)
    sources = json.loads(Path(args.sources or root / "channels" / args.channel
                              / "fact-sources.json").read_text(encoding="utf-8"))
    if args.assume:
        sources = with_rows(sources, json.loads(Path(args.assume).read_text(encoding="utf-8")))
    saved = load_saved(json.loads(Path(args.feeds).read_text(encoding="utf-8"))
                       if args.feeds else {})
    pipe = root / "pipeline" / args.channel
    batches = sorted(d for d in pipe.iterdir()
                     if d.is_dir() and args.since <= d.name[:10] <= args.until)
    rows = replay(batches, sources, saved)
    out = {"batches": [b.name for b in batches], **summary(rows)}
    if args.rows:
        out["rows"] = rows
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
