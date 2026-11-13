#!/usr/bin/env python3
"""CF-0823: a candidate the fact rule refused with `no_fact` is not asked about
again, nor searched for, for the channel's next few days of batches.

Where it was found (`docs/analysis/funnel-2026-10-21.md` of the root): over
04-20.10 ExampleTech refused 24 topics with `no_fact` (tier2_without_primary
15, no_article 8), and the same candidates came back batch after batch -
Character.AI five times in five batches, Tesla Roadster, Apple HomeView and
Gemini 4 Argon twice each. Every one of them had been paid for with the
scoring pass's `search.list` before the probe said no. The probe now runs
before the scoring (`fact_probe_topics.py --before-scoring`), and this memory
is its other half: a refusal of the last `scope.no_fact_memory_days` days
(3 when the channel says nothing; 0 turns it off) is not probed again either.

What it is not. The user's rule of 2026-10-07 ("хайп-повторы не ограничивать")
stands: only a `no_fact` is remembered - a topic that had a fact, was made,
was below the threshold or past the shortlist is never held back by this - and
a remembered refusal is not renewed by the batches it holds a candidate back
in: once the days are over the candidate is probed again, so a story whose
fact appeared since (an article written, a company's post published) gets
its chance.

Where it lives. Beside the channel's other memory between batches,
`<pipeline>/<channel>/no-fact-memory.json` (`PIPELINE_DIR` wins over
`<root>/pipeline`, as for `published_before.py` and `retired-shots.json`) -
under `pipeline/`, so out of git like the batches it is read from:

    {"task": "CF-0823", "channel": "example-tech",
     "entries": [{"key": " character ai ", "name": "Character.AI",
                  "channel": "example-tech", "batch": "2026-10-20T1448Z",
                  "topic_id": "...", "refused_at": "2026-10-20T14:58:00Z",
                  "subreason": "tier2_without_primary", "article": "...",
                  "reason": "no fact: ..."}]}

`key` is the candidate's normalised name (`key_of`: lowercased, punctuation
to spaces) - the topic's `title_ref.name`, and its `person` for a person
topic; a candidate is held back when any of its names is a remembered key.
`subreason` says why there was no fact (`subreason_of`): the probe's own
outcome when it found no article to read (`no_article`, `wrong_article`,
`edition`...), else the commonest failure of its checked candidates
(`tier2_without_primary`, `retells_news`...). Entries older than
`KEEP_DAYS` are dropped when the file is written.

Usage (read-only):

    scripts/no_fact_memory.py <channel> [--days N] [--json]
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _channel_ids import resolve_channel  # noqa: E402  - CF-0835 (CF-0197)

TASK = "CF-0823"
FILE_NAME = "no-fact-memory.json"
PIPELINE_ENV = "PIPELINE_DIR"
NO_FACT_CODE = "no_fact"
#: the channel's key under `scope` and its default (the task of 21.10)
DAYS_KEY = "no_fact_memory_days"
DEFAULT_DAYS = 3
#: how long an entry stays in the file at all - an audit trail, not a rule
KEEP_DAYS = 30
#: the keys a refusal row gets from this module
MEMORY_KEY = "fact_memory"         # the remembered entry a candidate was held back by
BEFORE_SCORING_KEY = "before_scoring"
MEMORY_SOURCE = "no_fact_memory"

_APOSTROPHES = str.maketrans({"‘": "'", "’": "'", "“": '"',
                              "”": '"', "–": "-", "—": "-"})


def key_of(text):
    """The normalised name a candidate is remembered under (the same shape as
    `fact_probe_topics.normalise`: whole words between spaces)."""
    if not text or not str(text).strip():
        return None
    flat = str(text).translate(_APOSTROPHES).lower()
    flat = re.sub(r"[^a-z0-9]+", " ", flat).strip()
    return f" {flat} " if flat else None


def names_of(topic):
    """The keys of a topic (or of a pool candidate, which has only `name`)."""
    topic = topic or {}
    ref = topic.get("title_ref") or {}
    keys = []
    for name in (ref.get("name"), ref.get("person"), topic.get("name")):
        key = key_of(name)
        if key and key not in keys:
            keys.append(key)
    return keys


def parse_time(value):
    if not value:
        return None
    try:
        text = str(value).strip().replace("Z", "+00:00")
        moment = datetime.fromisoformat(text)
    except ValueError:
        m = re.match(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})Z$", str(value).strip())
        if not m:
            return None
        moment = datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:00+00:00")
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def _iso(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_utc():
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# the channel's number and the file
# --------------------------------------------------------------------------

def days_of(config, key=DAYS_KEY, default=DEFAULT_DAYS):
    """(`scope.no_fact_memory_days` of a channel config - or the `scope` key
    given, CF-0876's thin-pool memory reads its own - where it came from, a
    note or None). Absent or not a whole number >= 0: the default."""
    scope = (config or {}).get("scope") or {}
    value = scope.get(key)
    if value is None:
        return default, "default", None
    try:
        days = int(value)
        if isinstance(value, bool) or days < 0 or days != value:
            raise ValueError
    except (TypeError, ValueError):
        return default, "default", (f"scope.{key} is {value!r}, not a whole number "
                                    f">= 0; using {default}")
    return days, "channel", None


def pipeline_dir(root):
    env = os.environ.get(PIPELINE_ENV)
    return Path(env).expanduser() if env else Path(root) / "pipeline"


def memory_path(root, channel):
    return pipeline_dir(root) / str(channel) / FILE_NAME


def read_entries(path):
    """The file's entries; a missing or unreadable file is an empty memory
    (a memory that cannot be read holds nothing back - the probe asks)."""
    try:
        data = json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return []
    rows = data.get("entries") if isinstance(data, dict) else None
    return [r for r in rows or [] if isinstance(r, dict) and r.get("key")]


class Memory:
    """The channel's remembered `no_fact` refusals, as of `now`."""

    def __init__(self, entries, days=DEFAULT_DAYS, now=None, batch=None, path=None,
                 channel=None, days_from="default", root=None):
        self.days = int(days)
        self.now = now or now_utc()
        self.batch = batch
        self.path = str(path) if path else None
        self.channel = channel
        self.days_from = days_from
        self.entries = list(entries or [])
        since = self.now - timedelta(days=self.days)
        self.live = {}
        for entry in self.entries:
            at = parse_time(entry.get("refused_at"))
            if self.days <= 0 or at is None or at < since or at > self.now:
                continue
            if batch and entry.get("batch") == batch:
                continue            # this batch's own refusals are its own business
            # an entry's channel is frozen on the day it was refused: one written
            # before a rename carries the former id (CF-0835, CF-0197)
            if channel and entry.get("channel") is not None \
                    and resolve_channel(entry.get("channel"), root) != channel:
                continue
            best = self.live.get(entry["key"])
            if best is None or parse_time(best.get("refused_at")) < at:
                self.live[entry["key"]] = entry

    def hit(self, topic):
        """The remembered entry that holds this topic (or pool candidate)
        back, or None."""
        for key in names_of(topic):
            if key in self.live:
                return self.live[key]
        return None

    def block(self):
        """What a batch file says about the memory it was read against."""
        return {"task": TASK, "path": self.path, "days": self.days,
                "days_from": self.days_from, "as_of": _iso(self.now),
                "live_entries": len(self.live)}


def load(root, channel, config=None, now=None, batch=None):
    """The channel's memory as of `now` (default: the clock). `config` is the
    channel config the number of days is read from."""
    days, origin, _ = days_of(config)
    channel = resolve_channel(channel, root)
    path = memory_path(root, channel)
    return Memory(read_entries(path), days=days, now=now, batch=batch, path=path,
                  channel=channel, days_from=origin, root=root)


# --------------------------------------------------------------------------
# what a refusal says
# --------------------------------------------------------------------------

def subreason_of(row):
    """Why a `no_fact` row had no fact, in one code: the probe's outcome when
    it did not resolve an article to read, else the commonest failure of the
    checked candidates, else what the probe answered."""
    probe = row.get("fact_probe") or {}
    if probe.get("source") == MEMORY_SOURCE:
        return probe.get("outcome")
    check = probe.get("article_check") or {}
    if check.get("mismatch") == "edition" or "about another edition" in str(
            probe.get("detail") or ""):
        return "edition"
    outcome = probe.get("outcome")
    fails = {}
    for cand in row.get("fact_candidates") or []:
        for code in ((cand or {}).get("check") or {}).get("failures") or []:
            fails[code] = fails.get(code, 0) + 1
    if outcome and outcome != "ok" and not fails:
        return outcome
    if fails:
        return sorted(fails.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
    return outcome or "no_candidates"


def entries_of(rows, channel, batch, at):
    """New memory entries for the `no_fact` refusals among `rows` - not for
    one a remembered refusal produced (that would renew it forever)."""
    out = []
    for row in rows or []:
        if not isinstance(row, dict) or row.get("reason_code") != NO_FACT_CODE:
            continue
        if row.get(MEMORY_KEY):
            continue
        ref = (row.get("topic") or {}).get("title_ref") or {}
        names = [row.get("title"), ref.get("person")]
        keys = []
        for name in names:
            key = key_of(name)
            if key and key not in keys:
                keys.append(key)
        probe = row.get("fact_probe") or {}
        for key in keys:
            out.append({"key": key, "name": row.get("title"), "channel": channel,
                        "batch": batch, "topic_id": row.get("topic_id"),
                        "refused_at": _iso(at), "subreason": subreason_of(row),
                        "article": probe.get("article"),
                        BEFORE_SCORING_KEY: bool(row.get(BEFORE_SCORING_KEY)),
                        "reason": str(row.get("reason") or "")[:300]})
    return out


def record(root, channel, rows, batch, now=None):
    """Add the `no_fact` refusals of `rows` to the channel's memory file
    (one entry per key and batch - a second pass over the same batch adds
    nothing) and drop entries older than `KEEP_DAYS`. -> entries added."""
    at = now or now_utc()
    path = memory_path(root, channel)
    entries = read_entries(path)
    seen = {(e.get("key"), e.get("batch")) for e in entries}
    added = [e for e in entries_of(rows, channel, batch, at)
             if (e["key"], e["batch"]) not in seen]
    if not added:
        return []
    for entry in added:
        seen.add((entry["key"], entry["batch"]))
    since = at - timedelta(days=KEEP_DAYS)
    kept = [e for e in entries if (parse_time(e.get("refused_at")) or at) >= since]
    doc = {"task": TASK, "channel": channel,
           "note": (f"no_fact refusals of the channel's batches (CF-0823): a candidate "
                    f"here is neither probed nor searched again for scope.{DAYS_KEY} days "
                    f"(default {DEFAULT_DAYS}); entries older than {KEEP_DAYS} days are "
                    f"dropped. Written by fact_probe_topics.py --write."),
           "entries": kept + added}
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n")
    tmp.replace(path)
    return added


def remembered_refusal(topic, entry, days):
    """The `skipped_topics[]` row of a candidate the memory holds back: a
    `no_fact` (the funnel's word for it - the fact rule's verdict, given
    earlier), with the remembered entry beside it instead of a fresh probe."""
    ref = topic.get("title_ref") or {}
    reason = (f"no fact: refused with no_fact on {entry.get('refused_at')} in batch "
              f"{entry.get('batch')} ({entry.get('subreason')}) - within the channel's "
              f"{DAYS_KEY} ({days}), so it is neither probed nor searched again (CF-0823)")
    probe = {"source": MEMORY_SOURCE, "outcome": entry.get("subreason") or NO_FACT_CODE,
             "article": entry.get("article"), "asked_at": None, "usable": False,
             "has_fact": False, "remembered": dict(entry),
             "fact_rule": {"settled": True, "remembered": True}}
    kind = ref.get("kind")
    return {"topic_id": topic.get("topic_id"), "reason_code": NO_FACT_CODE,
            "reason": reason, "stage": "trend-hunter", "title": ref.get("name"),
            "kind": kind or None, "popularity_score": None, "fact_probe": probe,
            MEMORY_KEY: dict(entry), BEFORE_SCORING_KEY: True}


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("channel")
    ap.add_argument("--days", type=int, default=None,
                    help="override the channel's scope.no_fact_memory_days")
    ap.add_argument("--root", help="the factory root (default: FACTORY_ROOT / the tree's)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.root:
        root = Path(args.root).expanduser()
    else:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _runlog import factory_root
        root = factory_root()
    config = None
    try:
        config = json.loads((root / "channels" / f"{args.channel}.json").read_text())
    except (OSError, ValueError):
        pass
    if args.days is not None:
        config = {"scope": {DAYS_KEY: args.days}}
    mem = load(root, args.channel, config)
    rows = sorted(mem.live.values(), key=lambda e: e.get("refused_at") or "")
    if args.json:
        print(json.dumps({"memory": mem.block(), "live": rows}, ensure_ascii=False, indent=2))
    else:
        print(f"{mem.path}: {len(rows)} candidate(s) held back for {mem.days} day(s) "
              f"({mem.days_from})")
        for e in rows:
            print(f"  {e.get('refused_at')}  {e.get('name')!r}  {e.get('subreason')}  "
                  f"[{e.get('batch')}]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
