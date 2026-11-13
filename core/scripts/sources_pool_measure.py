#!/usr/bin/env python3
"""CF-0557, item 2: how many topics the Wikipedia-only support text costs the
channel, and of which kinds. An analysis over the channel's real batches,
read-only - not a test (docs/test-hygiene.md: a test never reads live
batches); its result is written into docs/sources-pool-2026-10.md by hand.

Two counts:

  1. **Direct.** Topics that left the Trend Hunter with `no_support_text`
     (`support_text.REFUSAL_CODE`, CF-0551) in a batch made on 1.8 or later -
     `skipped_topics[].reason_code` of `01-trend-hunter.json`, plus any topic
     whose `support_check.state` is `no_text`.
  2. **Replay of the offline half of the rule on every batch.** The 1.8 rule
     (`agents/trend-hunter/scripts/support_text.py`) drops a topic with no
     Wikipedia article of its own, and one whose leads name an aired episode
     until that episode's ShortSummary is written. The first half is decided
     by the fact probe every batch since CF-0263 recorded (`fact_probe.
     outcome` outside `fact_search.ARTICLE_OUTCOMES`, not an outage) - so it
     is counted exactly. The second half needs Wikipedia as it stood at the
     batch's hour, which is gone: those topics are counted as *at risk*
     (`support_text.event_of` on the leads the batch kept), not as drops.

Kinds: the topic's `title_ref` (`kind` work/person, `type` film/tv_series)
and a coarse kind of event read off the title and the leads (award show /
telecast, late-night or sketch show, reality / competition, box office,
episode, other).

    python3 scripts/sources_pool_measure.py [--root <factory checkout>]
        --channel example-film [--since 2026-10-06] [--json]

`--root` is the checkout whose `pipeline/<channel>/` is read (default: the
production checkout this worktree belongs to, else this checkout). The agent
code is read from this checkout's `agents/trend-hunter/scripts`.
"""
import argparse
import collections
import glob
import importlib.util
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
HUNTER = REPO / "agents" / "trend-hunter" / "scripts"
RELEASE_1_8 = "2026-10-06"   # CHANGELOG: v1.8 - 2026-10-06

EVENT_KINDS = (
    ("late_night_sketch", re.compile(r"\b(weekend night live|wnl|late show|tonight show|"
                                     r"late night|kimmel|colbert|fallon|monologue|sketch)\b", re.I)),
    ("reality_competition", re.compile(r"\b(love island|bachelor(?:ette)?|survivor|big brother|"
                                       r"traitors|dancing with the stars|idol|reality|reunion|"
                                       r"real housewives|drag race|the voice)\b", re.I)),
    ("award_show", re.compile(r"\b(awards?|emmys?|oscars?|golden globes?|telecast|ceremony|"
                              r"festival|gala|upfronts?)\b", re.I)),
    ("box_office", re.compile(r"\b(box office|opening weekend|grosses?|ticket sales)\b", re.I)),
)


def _load(name, path):
    if str(path.parent) not in sys.path:
        sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def default_root():
    # .worktrees/release-x/ -> the production checkout two levels up
    prod = REPO.parent.parent
    if REPO.parent.name == ".worktrees" and (prod / "pipeline").is_dir():
        return prod
    return REPO


def records(batch):
    """Every topic the batch probed: selected and skipped, with its probe."""
    for t in batch.get("topics") or []:
        yield "selected", None, t, t
    for s in batch.get("skipped_topics") or []:
        inner = s.get("topic") or {}
        merged = dict(inner)
        merged.setdefault("title_ref", inner.get("title_ref") or {})
        merged["fact_probe"] = s.get("fact_probe") or inner.get("fact_probe")
        merged.setdefault("title", s.get("title"))
        yield "skipped", s.get("reason_code"), s, merged


def leads_of(topic):
    ev = topic.get("evidence") or {}
    leads = [{"title": s.get("title"), "summary": s.get("summary")}
             for s in ev.get("sources") or []]
    if not leads:
        leads = [{"title": u.rsplit("/", 2)[-2].replace("-", " "), "summary": None}
                 for u in ev.get("rss_links") or [] if u.count("/") > 3]
    return leads


def event_kind(topic, leads, episode):
    """The coarse kind of the topic's event. The show kinds are read off the
    topic's own name and title (a lead that mentions the Emmys does not make
    Coach Hale an award show); box office also off the leads."""
    tr = topic.get("title_ref") or {}
    own = " ".join(str(v) for v in (topic.get("title"), tr.get("name")) if v)
    lead_text = " ".join(str(v) for lead in leads for v in (lead.get("title"), lead.get("summary")) if v)
    for name, rx in EVENT_KINDS:
        if rx.search(own) or (name == "box_office" and rx.search(lead_text)):
            return name
    if episode:
        return "episode"
    if tr.get("kind") == "person":
        return "person"
    return "other"


def _key(row):
    return re.sub(r"\W+", " ", str(row["title"] or "")).strip().lower()


def unique(rows):
    """One row per topic (the batches re-run on the same pool repeat it)."""
    seen = {}
    for r in rows:
        seen.setdefault(_key(r), dict(r, batches=[]))["batches"].append(r["batch"])
    return list(seen.values())


def measure(root, channel, since):
    support = _load("support_text_for_measure", HUNTER / "support_text.py")
    fact_search = sys.modules.get("fact_search") or _load("fact_search", HUNTER / "fact_search.py")
    article_ok = set(fact_search.ARTICLE_OUTCOMES)
    unreachable = set(support.UNREACHABLE_OUTCOMES)
    batches = sorted(glob.glob(str(Path(root) / "pipeline" / channel / "*" / "01-trend-hunter.json")))
    out = {"root": str(root), "channel": channel, "since": since, "batches": len(batches),
           "batches_since": [], "direct": [], "replay": collections.Counter(),
           "dropped": [], "at_risk": [], "kinds_dropped": collections.Counter(),
           "kinds_at_risk": collections.Counter(), "kinds_all": collections.Counter(),
           "topics": 0, "first": None, "last": None, "probed": []}
    for path in batches:
        bid = Path(path).parent.name
        out["first"] = out["first"] or bid
        out["last"] = bid
        batch = json.loads(Path(path).read_text(encoding="utf-8"))
        after = bid[:10] >= since
        if after:
            out["batches_since"].append(bid)
        for where, code, raw, topic in records(batch):
            out["topics"] += 1
            check = (topic.get(support.CHECK_KEY) or {})
            if code == support.REFUSAL_CODE or check.get("state") == support.STATE_NO_TEXT:
                out["direct"].append({"batch": bid, "title": topic.get("title")})
            probe = topic.get("fact_probe") or {}
            outcome = probe.get("outcome")
            tr = topic.get("title_ref") or {}
            leads = leads_of(topic)
            episode = support.event_of(tr, leads) if tr else None
            kind = event_kind(topic, leads, episode)
            row = {"batch": bid, "where": where, "reason_code": code,
                   "title": topic.get("title") or tr.get("name"), "outcome": outcome,
                   "type": tr.get("type"), "ref_kind": tr.get("kind"), "event": kind,
                   "episode": (episode or {}).get("phrase")}
            if outcome is None:
                out["replay"]["no_probe"] += 1
                continue
            out["kinds_all"][kind] += 1
            out["probed"].append(row)
            if outcome in unreachable:
                out["replay"]["unreachable"] += 1
            elif outcome not in article_ok:
                out["replay"]["drop_no_article"] += 1
                out["dropped"].append(row)
                out["kinds_dropped"][kind] += 1
            elif episode:
                out["replay"]["at_risk_episode"] += 1
                out["at_risk"].append(row)
                out["kinds_at_risk"][kind] += 1
            else:
                out["replay"]["has_article"] += 1
    for name in ("probed", "dropped", "at_risk"):
        out[f"unique_{name}"] = unique(out[name])
    for name in ("dropped", "at_risk"):
        out[f"unique_kinds_{name}"] = collections.Counter(r["event"] for r in out[f"unique_{name}"])
    out["unique_kinds_all"] = collections.Counter(r["event"] for r in out["unique_probed"])
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", default=None)
    ap.add_argument("--channel", required=True,
                    help="the channel whose batches are read (no default: CF-0213)")
    ap.add_argument("--since", default=RELEASE_1_8)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    out = measure(Path(args.root) if args.root else default_root(), args.channel, args.since)
    if args.json:
        print(json.dumps(out, indent=2, ensure_ascii=False, default=dict))
        return 0
    print(f"batches {out['batches']} ({out['first']} .. {out['last']}), topics {out['topics']}")
    print(f"batches since {out['since']}: {len(out['batches_since'])} {out['batches_since']}")
    print(f"direct no_support_text: {len(out['direct'])}")
    print(f"replay: {dict(out['replay'])}")
    print(f"kinds, all probed: {dict(out['kinds_all'])}")
    print(f"kinds, dropped (no article): {dict(out['kinds_dropped'])}")
    print(f"kinds, at risk (aired episode): {dict(out['kinds_at_risk'])}")
    print(f"unique topics probed {len(out['unique_probed'])}, dropped {len(out['unique_dropped'])}, "
          f"at risk {len(out['unique_at_risk'])}")
    print(f"unique kinds, all: {dict(out['unique_kinds_all'])}")
    print(f"unique kinds, dropped: {dict(out['unique_kinds_dropped'])}")
    print(f"unique kinds, at risk: {dict(out['unique_kinds_at_risk'])}")
    for label, rows in (("DROPPED", out["unique_dropped"]), ("AT RISK", out["unique_at_risk"])):
        for r in rows:
            print(f"{label:8} x{len(r['batches'])} {r['batches'][0]} {r['where']:8} {r['event']:20} "
                  f"{r['outcome']:14} {r['reason_code']!s:18} {r['title']!s:.50} | {r['episode'] or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
