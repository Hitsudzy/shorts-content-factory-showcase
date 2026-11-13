#!/usr/bin/env python3
"""CF-0787: the YouTube Search quota day - the factory's batch day - and what
the batches of one quota day spent of it.

The limit that binds a batch is `defaultSearchListPerDayPerProject`: **100
`search.list` calls a day** per Google project, reset at **Pacific midnight**
(CF-0288, agents/trend-hunter/scripts/search_quota.py). In UTC that is 07:00Z
while PDT is in force and 08:00Z under PST (from the first Sunday of
November; on 2026-11-01), so the day is computed in `America/Los_Angeles` by
zoneinfo and never as a fixed offset. `shared/batch_schedule.py` counts its
«one batch a day for the whole factory» on this day, not on the Moscow
calendar day: on 17.10 a Science batch started at 11:17 МСК (after the 10:00
МСК reset) and the planned Reel window 18.10 02:00 МСК (23:00Z 17.10) fell in
the same quota day.

What a batch spent is read off its own records, the larger of two, the rule
`search_quota` has followed since CF-0313:

  * `01-trend-hunter.json` -> `search_quota`: `spent_searches` minus
    `searches_before_stage` (that part was spent by the batches before it,
    which are counted on their own);
  * `RUN_EVENTS.jsonl`: the `youtube-api` `search` child starts under it.

`day_spend` sums that over every batch (not a rebuild - it searches nothing
and carries the source's 01 - and not `backfill/`) whose id starts in the
quota day, the running one left out: the number `run_executor.py` hands the
trend-hunter stage as `--searches-spent` (`searches_before_stage`), so no
person has to pass it.
"""
import json
import re
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:                                             # pragma: no cover
    from backports.zoneinfo import ZoneInfo                     # type: ignore

TASK = "CF-0787"
QUOTA_TZ = "America/Los_Angeles"     # the Search quota resets at Pacific midnight
SEARCH_CALLS_PER_DAY = 100           # search_quota.SEARCH_CALLS_PER_DAY
QUOTA_STAGE = "trend-hunter"         # the stage that spends the Search quota
BATCH_FILE = "01-trend-hunter.json"
QUOTA_KEY = "search_quota"
EVENTS_FILE = "RUN_EVENTS.jsonl"
SEARCH_TOOL, SEARCH_VERB = "youtube-api", "search"
NOT_BATCH_GROUPS = ("backfill", "rebuilds")
BATCH_ID_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T(\d{2})(\d{2})Z")


def zone():
    return ZoneInfo(QUOTA_TZ)


def _utc(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def quota_day(dt):
    """The quota day of the moment `dt`: its date in America/Los_Angeles."""
    return _utc(dt).astimezone(zone()).date()


def bounds(qd):
    """`(start, end)` in UTC of the quota day `qd` - Pacific midnight to the
    next one (23 or 25 hours on the days the clocks change)."""
    z = zone()
    start = datetime.combine(qd, time(0), tzinfo=z)
    end = datetime.combine(qd + timedelta(days=1), time(0), tzinfo=z)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def batch_start(batch_id):
    m = BATCH_ID_RE.match(str(batch_id or ""))
    if not m:
        return None
    return datetime.fromisoformat(f"{m.group(1)}T{m.group(2)}:{m.group(3)}:00+00:00")


def _int(v):
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


def searches_from_file(batch_dir):
    """This batch's own `search.list` calls by its 01, or None without one."""
    try:
        doc = json.loads((Path(batch_dir) / BATCH_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    block = doc.get(QUOTA_KEY) if isinstance(doc, dict) else None
    if not isinstance(block, dict) or _int(block.get("spent_searches")) is None:
        return None
    return max(0, block["spent_searches"] - (_int(block.get("searches_before_stage")) or 0))


def searches_from_events(batch_dir):
    """The `youtube-api search` calls the batch's run log recorded, or None
    without a run log (search_quota.spend_from_events, the total only)."""
    path = Path(batch_dir) / EVENTS_FILE
    if not path.is_file():
        return None
    n = 0
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                if SEARCH_TOOL not in line or '"start"' not in line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                argv = row.get("argv") if isinstance(row, dict) else None
                if row.get("kind") == "child" and row.get("status") == "start" \
                        and row.get("tool") == SEARCH_TOOL and isinstance(argv, list) \
                        and len(argv) > 1 and argv[1] == SEARCH_VERB:
                    n += 1
    except OSError:
        return None
    return n


def batch_searches(batch_dir):
    """`(searches, source)` of one batch: the larger of its 01 and its run log;
    `(0, None)` when neither says anything."""
    f, e = searches_from_file(batch_dir), searches_from_events(batch_dir)
    if f is None and e is None:
        return 0, None
    if e is None or (f is not None and f >= e):
        return f, f"{BATCH_FILE} -> {QUOTA_KEY}"
    return e, EVENTS_FILE


def day_batches(root, qd, exclude=None):
    """The batch folders under `<root>/pipeline/<channel>/` whose id starts in
    the quota day `qd`, `exclude` (the running batch) left out, by start."""
    pipe = Path(root) / "pipeline"
    if not pipe.is_dir():
        return []
    skip = Path(exclude).resolve() if exclude else None
    out = []
    for d in pipe.glob("*/*"):
        if d.parent.name in NOT_BATCH_GROUPS or not d.is_dir():
            continue
        t = batch_start(d.name)
        if t is None or quota_day(t) != qd:
            continue
        if skip is not None and d.resolve() == skip:
            continue
        out.append((t, d))
    return [d for _t, d in sorted(out)]


def day_spend(root, qd=None, exclude=None, now=None):
    """What the quota day `qd` (default: the one of `now`) spent before the
    batch `exclude`: `{quota_day, start, end, searches, batches: [{batch,
    searches, source}]}` - `searches` is the stage's `searches_before_stage`."""
    if qd is None:
        qd = quota_day(now or datetime.now(timezone.utc))
    rows, total = [], 0
    for d in day_batches(root, qd, exclude):
        n, src = batch_searches(d)
        total += n
        rows.append({"batch": f"{d.parent.name}/{d.name}", "searches": n, "source": src})
    s, e = bounds(qd)
    return {"task": TASK, "quota_day": qd.isoformat(), "tz": QUOTA_TZ,
            "start": s.strftime("%Y-%m-%dT%H:%M:%SZ"), "end": e.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "searches": total, "limit": SEARCH_CALLS_PER_DAY, "batches": rows}


def prompt_lines(spend):
    """The lines the trend-hunter stage's prompt carries (run_executor)."""
    s = spend
    who = "; ".join(f"{b['batch']} {b['searches']}" + (f" ({b['source']})" if b["source"] else "")
                    for b in s["batches"]) or "no other batch of this quota day"
    return [
        f"YouTube Search quota ({TASK}): this quota day ({s['quota_day']}, Pacific midnight "
        f"to Pacific midnight, {s['start']} - {s['end']}) already spent {s['searches']} of "
        f"its {s['limit']} `search.list` calls in other batches: {who}.",
        f"  searches_spent: {s['searches']}",
        f"Pass `--searches-spent {s['searches']}` to every script of this stage that takes it "
        f"(scripts/footage_candidates.py, scripts/refill_topics.py, the supplement): it is "
        f"the batch's `searches_before_stage`, counted by the executor - do not change it.",
    ]
