#!/usr/bin/env python3
"""CF-0345: the thin-pool supplement step of a batch - its place in the run is
held by the code, not by a paragraph.

The user's ruling of 2026-09-23 (CF-0338): an anchor the topic's own sources
cannot picture is answered by *more footage of the anchor's entity*, fetched
before the Video Editor - never by dropping the topic. Four repositories each
own a piece of it, and this module is the root's: the order.

    Content Researcher   the pool gates warn `pool_too_thin` (CF-0575: and
                         `event_footage_short`) and, with
                         `--write`, lay a request skeleton at
                         `<batch>/work/supplement-requests/<topic_id>.json`
                         (CF-0342, `_supplement_request.py`)
    thin-pool-supplement (this step, a stage that is nobody's turn)
      1. hunter          `footage_candidates.py --supplement <req>... --search
                         --write` - fills `candidates[]`, spends the batch's
                         search quota (CF-0343)
      2. indexer         `ingest_batch.py <batch> --supplement <req>...` -
                         fetch, index, `supplements[]` in 01b (CF-0338a)
      3. consumed        the filled request moves to
                         `supplement-requests/consumed/` (below: why)
      4. descriptions    every shot of the new sources gets `description`,
                         `burned_text`, `on_topic`, `shows_entity` - an LLM
                         operator's work, the one step this script cannot do;
                         it stops with exit 10 and names the sources
      5. sieve           `source_sieve.py <batch> --no-top-up` - judges a
                         supplement source by its entity (CF-0344); fetches
                         nothing (CF-0454, `SIEVE_NO_FETCH`)
      6. recheck         the three pool gates again with `--write`
                         (coverage `--out`, sides, block capacity), so
                         `warnings[]` in 03 says what the pool holds now
    plan check again     `plan_check_loop.py <batch> --write --after-supplement`
                         (CF-0422, the Researcher's) - the scripts step 6b
                         deferred for this step, on the enlarged pool; only
                         here is a plan still not built `plan_unassembled`
    Compliance (second pass) -> Video Editor

**Why the request moves before the recheck** (the driver's note on CF-0342).
A pool gate run with `--write` rewrites the topic's skeleton whole - it is the
researcher's `sync()`, and a skeleton has no `candidates`. Run after the
hunter it would erase the candidates the hunter paid search quota for, and
with them the record of what was fetched and why. The choice was between
teaching `sync()` to merge (a change in `agents/content-researcher`) and not
letting the recheck see the filled file at all; the second needs no other
repository and keeps both facts: `consumed/<topic>.json` is the answered
request with its candidates, and a skeleton the recheck writes afresh for a
topic that is still thin is a *new* request - the input of the future ingest
queue (CF-0324 / CF-0099, not built yet: until then this directory is that
input). A topic gets one round per batch: once it is in this step's record, a
fresh skeleton for it is not pending, so the step cannot loop on a pool that
more footage did not fix.

**A supplement never drops a topic.** Every failure inside the step - no
candidate found, the quota spent, a fetch refused, a gate that could not
answer - is written into the record as a warning and the step still ends
`done`. The gates themselves only warn on the pool since CF-0330.

**A failed tool is not an answer** (CF-0350). The hunter needs
`YOUTUBE_API_KEY`; the step takes it the way the Trend Hunter's own stage
does - the environment first, else `agents/trend-hunter/.env` (the README's
`set -a; source .env`), handed to the hunter's process only and never
printed. With neither the hunter is not started at all. That, a hunter that
did not answer (did not start, exit other than 0/1, left the request
untouched, or every search it ran failed - no network, a refused key), and an
indexer that did not exit 0 are *tool failures*: the request stays in
`supplement-requests/` (not `consumed/`), the topic's record counts a failed
attempt, and the step exits 3 (4 when the key is missing) - `pending`, so the
stages after it are still refused. A round is spent only by an answer. The
retry is bounded: after `MAX_TOOL_ATTEMPTS` failed attempts the topic is
`skipped` - a warning in the record, the request left where it lies for the
future ingest queue, the stages after it open. A supplement never drops a
topic, and neither does its failure: it never blocks for ever either. A
hunter that answered "nothing found" (exit 1 with its searches run) is an
answer - the request is consumed as before.

**A wall-clock ceiling per batch** (CF-0426, the user's decision of
2026-09-28): `channels/<channel>.json -> supplement.max_wall_seconds`, else
1800. The first call stamps `started_at` and `wall_ceiling_seconds` into the
record; the clock runs across every call - the describing between exit 10 and
the next call included. It is checked at the start of each call and before
the hunter, the indexer and the descriptions, and the hunter runs with what
is left as its timeout, the sieve with that but at least SIEVE_GRACE_SECONDS
(CF-0454, below), the ingest up to its deadline (below)
(`_run` kills the whole process group). Spent, the step closes with exit 0 (`_close_at_ceiling`):
every topic waiting or fetched-but-unfinished is `skipped`, `outcome:
wall_ceiling`, a warning, no attempt counted, the request left in place; a
supplement source not yet described and sieved is taken out of the pool the
sieve's way (`_withdraw_unsieved`, see `WITHDRAWN_CODE`). Never a drop.

**The ceiling stops new work, not work done** (CF-0454, run 1248Z: the sieve
was killed at the ceiling re-walking another topic, and both described
supplement sources were withdrawn). A call that finds the ceiling spent with
a topic fetched and sent to be described skips only what still waits and
runs the sieve anyway, with at least `SIEVE_GRACE_SECONDS`; the sieve fetches
nothing (`--no-top-up`). What it kept stays and its topic finishes with the
recheck (`finished_past_ceiling` in the record); only a source it still
calls `unsieved` is withdrawn, and a topic left with none is `skipped`.

**The indexer's deadline inside the ceiling** (CF-0429, run 1126Z: the
ceiling came inside the ingest, the kill lost every download). The indexer
runs with `--deadline` = start + ceiling - a reserve (`indexer_reserve()`:
max(600 s, ceiling/3), at most half the ceiling - 10 min at 30; why in the
comment above `INDEXER_TASK`) for the describing, the sieve and the recheck,
and its process timeout is only a net 60 s past it. Past the deadline no
hunter or indexer is started - what waits is skipped `wall_ceiling`, and the
step closes as at the ceiling unless a topic already fetched owes its
descriptions. What a cut ingest got into `01b` (`supplements[].wall_ceiling`,
or `in_progress` from a killed call) is kept: those topics stay `fetched` and
go on to exit 10 and the sieve (`indexer_cut` on the topic, `indexer_deadline`
in the record); a topic nothing of which got in is `skipped` `wall_ceiling`;
only when nothing of any request got in does the step close here. A source
whose describing overruns the reserve is still withdrawn at the ceiling.

**The order is enforced where CF-0322 put the stop-cock**: `runlog.marker()`
refuses `stage-start` of the stages after the Researcher (`GATED_STAGES`)
while `verdict()` is `pending` or `describing` - exit 2, with `--anyway
REASON` recorded rather than a switch. A batch with no request never sees the
step: `none` is the state, and nothing is refused. The same gate then holds
those stages while the Researcher's `--pending-after-supplement` names a
deferred script (CF-0422, `plan_blocks()`); a batch with no 03 or a checkout
without the Researcher's script is not refused. When the step ends done and
such scripts wait, it prints the `--after-supplement` command - it does not
run it: that loop may need the writer's anchor edits.

**A verification rerun that may not search** (CF-0494, run 1748Z: the user
agreed a rerun "without search or download", the step had no such mode, the
orchestrator asked mid-run and the batch stood 1h43m). The mode is said at
the start, by the script: `runlog batch-start --rerun no-search` writes
`rerun: {"mode": "no_search"}` into the batch-start event, and this step reads
it there (`rerun_mode()`). On such a batch every pending request is closed at
once, before the clock and before any tool: `skipped`, `outcome:
rerun_no_search`, a warning, the request left in place, one `rerun-no-search`
entry in the record's `runs` - nothing searched, nothing fetched, nobody
asked. Never a drop: the topic goes on with its pool as it is. The mode is
never inferred from a note, and a record written by hand is not the mode.

**A topic that is no longer in the batch is not searched for** (CF-0826, the
funnel review of 2026-10-21: of 122 `search.list` calls the step spent on
Reel from 04 to 20.10, 74 went to topics that never became videos). A topic
is alive while 03 lists it in `scripts[]` (a script deferred at 6b for this
step is still there, CF-0422); refused, `skipped[]` or taken off by a gate,
it is gone. At the start of every call, before the clock and before any
tool, each pending request of a topic not in `scripts[]` is closed:
`skipped`, `outcome: topic_dropped`, why (03's `skipped[]` reason_code when
it names one), the request left where it lies, one `topic-dropped` entry in
the record's `runs`. Without a readable 03 nothing is closed this way - the
step cannot tell, and it searches as before.

**A channel may switch the step off** (CF-0842, the user's decision of
2026-10-21, Q2: ExampleTech's supplement gave 0 shots to 9 videos and spent
search quota, docs/analysis/supplement-review-2026-10.md).
`channels/<channel>.json -> supplement.enabled: false` (absent = on; schema:
patterns/validate_patterns.py::validate_supplement_block) closes every
pending request at the start of every call, before the clock and before any
tool, the CF-0494 way: `skipped`, `outcome: supplement_disabled`, a warning,
the request left where it lies, one `supplement-disabled` entry in the
record's `runs` - nothing searched, nothing fetched. The run plan is not
changed (ExampleTech's graph stays ExampleFilm's): the step still opens on a
request and ends `done` at once. The Researcher's check after it
(`plan_check_loop.py --after-supplement`) then settles the scripts 6b
deferred on the pool they already have - one plan check, no quota; that check
is owed anyway, the supplement would only have grown its pool.

**A topic too thin to save is not searched for** (CF-0845, the user's
signature of 2026-10-21, Q8: over six batches with a supplement no topic with
7 usable shots or fewer was saved by it - the one save had 96). A pending
request of a topic whose pool holds fewer clean usable shots than the
channel's `content_researcher.min_usable_shots_for_script` (default 10, 0 =
off; the count is the indexer's own `01b pool_depth.topics[].usable_shots`,
read by `thin_topic.py`) is closed at the start of every call, before the
clock and before any tool, the CF-0842 way: `skipped`, `outcome: too_thin`,
`usable_shots_before` and the floor, a warning, the request left where it
lies, one `too-thin` entry in the record's `runs` - nothing searched, nothing
fetched. A topic the indexer never measured is searched for as before. The
Researcher drops such a topic before its first plan check anyway
(`thin_topic.py`, `pool_too_thin`), so this is the step's own half of the
rule, for a request written before that drop or by a writer without it.

State lives in the batch's own artifacts, never in the events:
`work/supplement-requests/*.json` (pending requests) and
`work/supplement-step.json` (this step's record).

CLI: `scripts/thin_pool_supplement.py <batch> [--dry-run] [--json]`. Exit 0 -
done or nothing to do (a skipped topic included, the wall ceiling too); 10 - descriptions owed, run
again after them; 3 - a tool failed, the request is kept, run again; 4 - no
`YOUTUBE_API_KEY` in the environment nor in the hunter's `.env`, nothing was
started, run again once it is there; 2 - bad call. Stdlib only.
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

TASK = "CF-0345"
STAGE = "thin-pool-supplement"
KIND = "thin_pool_supplement"
REQUEST_DIR = Path("work") / "supplement-requests"
CONSUMED = "consumed"
RECORD = Path("work") / "supplement-step.json"
RECHECK_DIR = Path("work") / "supplement-recheck"
INDEX_FILE = "01b-footage-index.json"
SCRIPTS_FILE = "03-content-researcher.json"
# The warning codes a request is laid for (the request's `reason_code`): the
# pool too thin for the script (CF-0342), and - CF-0575 - the event's own
# footage too short for the words that retell it (`event_footage_short`, the
# Researcher's gate `event_footage`; the request then also carries `event`,
# `natures_wanted` [episode, trailer] and `natures_refused` [interview]).
# Neither is a funnel loss: a supplement never drops a topic.
WARNING_CODES = ("pool_too_thin", "event_footage_short")

NONE, PENDING, DESCRIBING, DONE = "none", "pending", "describing", "done"
BLOCKING = (PENDING, DESCRIBING)
# The stages that come after the Researcher's and read its pool. The
# Researcher itself and the Indexer are not here: the CF-0306 reserve loop
# runs them again after the Researcher, and it may lay requests of its own.
GATED_STAGES = ("compliance-checker", "video-editor", "frame-judge", "publisher")

EXIT_DONE, EXIT_USAGE, EXIT_DESCRIBE = 0, 2, 10
EXIT_TOOL_FAILED, EXIT_NO_KEY = 3, 4

# CF-0350: the hunter's key, and how many failed attempts a topic gets before
# it goes on without its supplement.
API_KEY = "YOUTUBE_API_KEY"
HUNTER_ENV = Path("agents") / "trend-hunter" / ".env"
MAX_TOOL_ATTEMPTS = 2
NO_KEY = "missing_api_key"

# The order of the step, as step names; `advance()` walks it and the tests
# read it. `descriptions` is the stop between the two halves.
STEPS = ("hunter", "indexer", "consumed", "descriptions", "sieve",
         "recheck-coverage", "recheck-sides", "recheck-blocks")

PH_FETCHED, PH_DONE = "fetched", "done"
# CF-0350: `failed` - a tool failed, the request is kept and taken again;
# `skipped` - MAX_TOOL_ATTEMPTS failed, the topic goes on without it.
PH_FAILED, PH_SKIPPED = "failed", "skipped"

# CF-0426 (the user's decision of 2026-09-28): the wall-clock ceiling of the
# whole step per batch, from `channels/<channel>.json -> supplement.
# max_wall_seconds` (schema: patterns/validate_patterns.py::
# validate_supplement_block), else this default. It is counted from the step's
# first `advance()` - `started_at` in the record - across every call of it.
WALL_TASK = "CF-0426"
WALL_KEY_PATH = ("supplement", "max_wall_seconds")
DEFAULT_WALL_SECONDS = 1800
WALL_CEILING = "wall_ceiling"
CHANNEL_IDS = Path("shared") / "channel_ids.py"

# CF-0429: the indexer's deadline inside that ceiling. Run 1126Z (2026-09-28):
# the ceiling came inside `ingest_batch.py --supplement`, the root killed it at
# its timeout and every download of the call was lost (01b was written once,
# at the end). The indexer now takes `--deadline` (footage-indexer 2843668):
# past it nothing new starts, a download/index in flight is killed, and what
# got in is written to 01b. The deadline is the ceiling less a reserve for what
# must still happen after the indexer *inside the same ceiling* - the
# orchestrator describing the new shots (exit 10), the sieve, the three
# rechecks - or a source that got in is withdrawn at the ceiling undescribed.
#
# The reserve, measured on the runs that went through the whole step (the
# record's step times and RUN_EVENTS): indexer end -> last recheck was
# 8.5 min (1722Z, 1 new source), 13.4 min (rebuild 1344Z, 1 source), 17.8 min
# (0929Z, 3 sources). Almost all of it is the describing: the sieve on
# described shots took 0.1-0.7 s and the three rechecks 8-54 s. So the reserve
# is the describing of about one source: `max(600 s, ceiling / 3)` - 10 min at
# the 30-min ceiling covers the median single source (7.7 min of describing +
# under a minute of machine time) and scales with a larger ceiling, which
# fetches more. It is capped at half the ceiling so a small ceiling still
# leaves the indexer a window. More would starve the indexer (one source took
# 5.6-24 min to fetch and index in those runs); a source whose describing
# overruns is withdrawn at the ceiling as before (`_withdraw_unsieved`), its
# media and index staying in the cache.
INDEXER_TASK = "CF-0429"
INDEXER_RESERVE_MIN_SECONDS = 600
INDEXER_RESERVE_SHARE = 1 / 3
INDEXER_RESERVE_MAX_SHARE = 0.5
# The root's process timeout on the indexer is only a safety net behind the
# deadline: the indexer kills its children 3 s after the deadline and writes
# 01b per request, so it is killed from outside only this long past it (and
# never past half the reserve).
INDEXER_DEADLINE_GRACE_SECONDS = 60

# CF-0454: the ceiling stops new work, it does not throw away work done (as
# CF-0429 does for the indexer). Once a source is fetched and the orchestrator
# was sent to describe it (exit 10), what is left - the sieve judging the
# descriptions and the three rechecks - is finishing that work, not new work:
# a call that finds the ceiling spent with such a topic still runs the sieve,
# and the sieve always gets at least this long (a no-fetch sieve on described
# shots took well under a second on 1722Z/1344Z/0929Z, and its flag backfill,
# when some shot was left unanswered, one answerer call per source). Only a
# source the sieve still calls `unsieved` - not described after all - is
# withdrawn at the ceiling; one it kept stays in the pool.
SIEVE_TASK = "CF-0454"
SIEVE_GRACE_SECONDS = 300

# CF-0494: the mode `runlog batch-start --rerun no-search` writes into the
# batch-start event, and the outcome a request is closed with on such a batch.
RERUN_TASK = "CF-0494"
RERUN_NO_SEARCH_MODE = "no_search"
RERUN_NO_SEARCH = "rerun_no_search"

# CF-0826: the outcome a request of a topic gone from 03's `scripts[]` is
# closed with - nothing searched, nothing fetched for it.
DROPPED_TASK = "CF-0826"
TOPIC_DROPPED = "topic_dropped"

# CF-0842: the channel's switch of the step and the outcome a request is
# closed with when it is off - nothing searched, nothing fetched.
ENABLED_TASK = "CF-0842"
ENABLED_KEY_PATH = ("supplement", "enabled")
SUPPLEMENT_DISABLED = "supplement_disabled"

# CF-0845: the outcome a request of a topic under the channel's floor of
# usable shots is closed with - nothing searched, nothing fetched.
TOO_THIN_TASK = "CF-0845"
TOO_THIN = "too_thin"


def _root(root=None):
    if root:
        return Path(root)
    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2]


def _abs(path):
    """CF-0366: absolute, without resolving symlinks - an absolute path the
    caller gave stays as it was."""
    return Path(os.path.abspath(path))


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(epoch):
    return datetime.fromtimestamp(epoch, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def request_files(batch_dir):
    """`[(path, request)]` of the requests lying in the directory's top level
    (not `consumed/`), in name order."""
    d = Path(batch_dir) / REQUEST_DIR
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.glob("*.json")):
        req = _read(p)
        if isinstance(req, dict) and req.get("kind") == KIND and req.get("topic_id"):
            out.append((p, req))
    return out


def record(batch_dir):
    r = _read(Path(batch_dir) / RECORD)
    if not isinstance(r, dict):
        r = {}
    r.setdefault("task", TASK)
    r.setdefault("topics", {})
    r.setdefault("runs", [])
    return r


def verdict(batch_dir):
    """The step's state over the batch's own artifacts.

        none        no request and no record: the step does not run
        pending     a request for a topic this step has not taken yet
        describing  requests fetched, their sources owe descriptions/the sieve
        done        every topic taken is finished
    """
    rec = record(batch_dir)
    topics = rec["topics"]
    pending = [str(p) for p, r in request_files(batch_dir) if not _taken(topics, r["topic_id"])]
    fetched = sorted(t for t, v in topics.items() if v.get("phase") == PH_FETCHED)
    if pending:
        state = PENDING
    elif fetched:
        state = DESCRIBING
    elif topics:
        state = DONE
    else:
        state = NONE
    return {"state": state, "pending": pending, "describing": fetched,
            "done": sorted(t for t, v in topics.items() if v.get("phase") == PH_DONE),
            "skipped": sorted(t for t, v in topics.items() if v.get("phase") == PH_SKIPPED),
            "failed": sorted(t for t, v in topics.items() if v.get("phase") == PH_FAILED),
            "reason": _reason(state, pending, fetched)}


def _taken(topics, tid):
    """A topic's round is taken once it has an answer or has given up; a
    `failed` attempt leaves its request pending (CF-0350)."""
    return tid in topics and topics[tid].get("phase") != PH_FAILED


def _reason(state, pending, fetched):
    if state == PENDING:
        return (f"{len(pending)} thin-pool supplement request(s) not answered yet - run "
                f"`scripts/thin_pool_supplement.py <batch>` (CF-0345); a tool that "
                f"fails {MAX_TOOL_ATTEMPTS} times lets the topic go on without it (CF-0350)")
    if state == DESCRIBING:
        return (f"the supplement of {', '.join(fetched)} owes shot descriptions and the "
                f"sieve - describe the new sources, then run "
                f"`scripts/thin_pool_supplement.py <batch>` again (CF-0345)")
    if state == DONE:
        return "the thin-pool supplement step is finished"
    return "no thin-pool supplement request: the step does not run"


def blocks(stage, batch_dir):
    """The refusal line for `runlog stage-start <stage>`, or None."""
    if stage not in GATED_STAGES:
        return None
    v = verdict(batch_dir)
    if v["state"] not in BLOCKING:
        return None
    return v


# --------------------------------------------------------------------------
# CF-0426: the wall-clock ceiling of the step
# --------------------------------------------------------------------------

def resolve_channel(name, root=None):
    """A channel id as it is today (a renamed channel's old name resolved
    through `shared/channel_ids.py`); the name unchanged when that cannot be
    loaded."""
    path = _root(root) / CHANNEL_IDS
    if not name or not path.is_file():
        return name
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("channel_ids_for_supplement", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.resolve_channel(name, root=_root(root)) or name
    except Exception:                                   # noqa: BLE001
        return name


def batch_channel(batch_dir, root=None):
    """The batch's channel: `01-trend-hunter.json -> channel`, else the name
    of the batch's parent directory (`pipeline/<channel>/<batch>`)."""
    bdir = _abs(batch_dir)
    th = _read(bdir / "01-trend-hunter.json")
    th = th if isinstance(th, dict) else {}
    return resolve_channel(th.get("channel") or bdir.parent.name, root)


def wall_ceiling_seconds(batch_dir, root=None):
    """-> `(seconds, source)`: the channel's `supplement.max_wall_seconds`,
    or `DEFAULT_WALL_SECONDS` when the config, the block or a usable value is
    missing (the schema refuses such a value; the reader never stops a run
    over it)."""
    channel = batch_channel(batch_dir, root)
    cfg = _read(_root(root) / "channels" / f"{channel}.json") if channel else None
    v = cfg
    for k in WALL_KEY_PATH:
        v = v.get(k) if isinstance(v, dict) else None
    if isinstance(v, int) and not isinstance(v, bool) and v > 0:
        return v, f"channels/{channel}.json {'.'.join(WALL_KEY_PATH)}"
    return DEFAULT_WALL_SECONDS, "default"


def supplement_enabled(batch_dir, root=None):
    """CF-0842: -> `(enabled, source)`. Off only on a literal `false` in the
    channel's `supplement.enabled`; absent, unreadable or any other value is
    on (the schema refuses a non-boolean - the reader never stops a run over
    it, and never switches the step off by accident)."""
    channel = batch_channel(batch_dir, root)
    cfg = _read(_root(root) / "channels" / f"{channel}.json") if channel else None
    v = cfg
    for k in ENABLED_KEY_PATH:
        v = v.get(k) if isinstance(v, dict) else None
    if v is False:
        return False, f"channels/{channel}.json {'.'.join(ENABLED_KEY_PATH)}"
    return True, "default"


def _start_clock(rec, bdir, root, clock):
    """Stamp the step's start and ceiling into the record on its first call;
    a record that has them keeps them (the ceiling is per batch)."""
    if rec.get("started_epoch") is not None:
        return False
    now = clock()
    secs, source = wall_ceiling_seconds(bdir, root)
    rec.update(started_at=_iso(now), started_epoch=now,
               wall_ceiling_seconds=secs, wall_ceiling_from=source)
    return True


def _elapsed(rec, clock):
    return clock() - float(rec.get("started_epoch") or clock())


def _remaining(rec, clock):
    return float(rec.get("wall_ceiling_seconds") or DEFAULT_WALL_SECONDS) - _elapsed(rec, clock)


def _spent(rec, clock):
    return _remaining(rec, clock) <= 0


def _ceiling(rec):
    return float(rec.get("wall_ceiling_seconds") or DEFAULT_WALL_SECONDS)


def indexer_reserve(ceiling):
    """CF-0429: the seconds of the ceiling kept for after the indexer (see
    `INDEXER_RESERVE_MIN_SECONDS`)."""
    c = float(ceiling)
    return min(max(INDEXER_RESERVE_MIN_SECONDS, c * INDEXER_RESERVE_SHARE),
               c * INDEXER_RESERVE_MAX_SHARE)


def indexer_deadline(rec):
    """CF-0429: the epoch the indexer is handed as `--deadline` - the step's
    start + its ceiling - the reserve; None before the clock is started."""
    if rec.get("started_epoch") is None:
        return None
    c = _ceiling(rec)
    return float(rec["started_epoch"]) + c - indexer_reserve(c)


def _indexer_timeout(rec, clock, deadline):
    """The process timeout of the indexer: a little past its deadline (the
    safety net behind it), never the other way round."""
    grace = min(INDEXER_DEADLINE_GRACE_SECONDS, indexer_reserve(_ceiling(rec)) / 2)
    return max(1.0, deadline - clock() + grace)


def _deadline_why(rec, clock):
    c = _ceiling(rec)
    d = indexer_deadline(rec)
    return (f"{WALL_CEILING}: the indexer's deadline {_iso(d)} has passed - the step's "
            f"ceiling of {c:.0f}s less {indexer_reserve(c):.0f}s kept for describing, the "
            f"sieve and the recheck ({_elapsed(rec, clock):.0f}s since "
            f"{rec.get('started_at')}) - {INDEXER_TASK}")


# CF-0426: how a supplement source the ceiling left undescribed or unsieved is
# taken out of its topic's pool. The mechanism is the sieve's own
# (`source_sieve.apply_sieve` / `refuse_unanswered`): out of `sources_by_topic`
# (what the Researcher's gates and the Video Editor's resolve read) and out of
# `fetched`, into `failed[]` - where `topic_tried()` bars it from ever being
# walked again. The code is the one the sieve gives a source it could not get
# answered (CF-0359: `index_failed` - "an index that cannot be sieved is ours,
# unfinished"), deliberately not a new word the funnel and
# `TOPIC_REFUSAL_CODES` would not know; `refused_at` and `withdrawn` say it
# was the ceiling.
#
# CF-0429 looked again at "bars it from ever being walked again": the
# indexer's `topic_tried()` reads `failed[]` without looking at the code, so a
# repeat request for the topic *in this batch* refuses a withdrawn id as
# `already_tried` although its media and index sit in the cache. That is
# intended and does not work against CF-0429's goal (what the deadline let in
# reaches the pool): (1) this step gives a topic one round per batch - a topic
# closed at the ceiling is `skipped`, taken, and never asked for again here;
# (2) the indexer treats the ids a cut call *did* get the same way on resume
# (in `sources_by_topic` -> tried), so a withdrawn id is simply "touched by
# this batch"; (3) a source is withdrawn only because nobody had time to
# describe it, and walking it again in this batch would bring back the same
# undescribed source; (4) `01b` is per batch - a later batch starts with no
# `failed[]` and gets the media from the cache for nothing. Should the future
# ingest queue (CF-0324 / CF-0099) want to re-offer such ids within a batch,
# the rows already carry their own marker (`withdrawn: wall_ceiling`,
# `refused_at: wall_ceiling`) and the filter belongs in `topic_tried()`.
WITHDRAWN_CODE = "index_failed"
WITHDRAWN_REASON = (
    "a thin-pool supplement source fetched for this topic and not yet described "
    "and sieved when the supplement step's wall-clock ceiling was spent "
    "({ceiling}s, CF-0426): an unjudged source is not sent to the writer (that is "
    "what the sieve is for), so it is taken out of the pool with this record and "
    "the topic goes on with the pool it had before the supplement")


def _withdraw_unsieved(bdir, rec, tids, ceiling):
    """Take the supplement sources of `tids` that the sieve has not kept out
    of the pool in `01b`; -> `{topic: [video_id]}` of what was taken."""
    path = Path(bdir) / INDEX_FILE
    idx = _read(path)
    if not isinstance(idx, dict):
        return {}
    sieve = idx.get("source_sieve") or {}
    kept = {s.get("video_id") for s in sieve.get("sources") or []
            if isinstance(s, dict) and s.get("verdict") == "kept"}
    entries = [e for e in idx.get("supplements") or []
               if isinstance(e, dict) and e.get("topic_id") in tids]
    sbt = idx.get("sources_by_topic") or {}
    reason = WITHDRAWN_REASON.format(ceiling=ceiling)
    taken = {}
    for tid in tids:
        new = list((rec["topics"].get(tid) or {}).get("new_sources") or [])
        for e in entries:
            if e.get("topic_id") == tid:
                new += [v for v in e.get("new_sources") or [] if v not in new]
        held = list(sbt.get(tid) or [])
        out = [v for v in new if v in held and v not in kept]
        if out:
            taken[tid] = out
    if not taken:
        return {}
    pairs = {(t, v) for t, vs in taken.items() for v in vs}
    ids = {v for _, v in pairs}
    idx["sources_by_topic"] = {t: [v for v in vs or [] if (t, v) not in pairs]
                               for t, vs in sbt.items()}
    idx["fetched"] = [f for f in idx.get("fetched") or []
                      if (f.get("topic_id"), f.get("video_id")) not in pairs]
    idx["failed"] = list(idx.get("failed") or []) + [
        {"video_id": v, "topic_id": t, "error": reason, "reason_code": WITHDRAWN_CODE,
         "refused_at": WALL_CEILING, "withdrawn": WALL_CEILING,
         "task": WALL_TASK,
         "attempts": [{"rung": WALL_CEILING, "error": reason}]}
        for t, v in sorted(pairs)]
    if isinstance(sieve.get("unsieved"), list):
        sieve["unsieved"] = [v for v in sieve["unsieved"] if v not in ids]
    for e in entries:
        gone = taken.get(e.get("topic_id")) or []
        mine = [v for v in e.get("new_sources") or [] if v in gone]
        if mine:
            e["withdrawn"] = mine
            e["withdrawn_code"] = WALL_CEILING
    _write(path, idx)
    return taken


def _skip_waiting(bdir, rec, why, hunted=(), failed=None):
    """Every topic still waiting (a request not taken, a `failed` retry)
    becomes `skipped`, `outcome: wall_ceiling`, a warning; the request is left
    where it lies. -> the topics."""
    failed = failed or {}
    closed = []
    for p, r in request_files(bdir):
        tid = r["topic_id"]
        if _taken(rec["topics"], tid):
            continue
        prev = rec["topics"].get(tid) or {}
        failures = list(prev.get("tool_failures") or [])
        if tid in failed:
            failures.append({"at": _now(), "reason": failed[tid]})
        x = {"phase": PH_SKIPPED, "outcome": WALL_CEILING, "request": str(p),
             "skipped_at": _now(), "attempts": len(failures),
             "hunted": bool(prev.get("hunted") or tid in hunted),
             "warnings": [f"supplement skipped - the topic goes on without it; {why}"]}
        if failures:
            x["tool_failures"] = failures
        rec["topics"][tid] = x
        closed.append(tid)
    return closed


def _deadline_passed(bdir, rec, log, out, clock, at, hunted=(), failed=None):
    """CF-0429: the indexer's deadline has passed before `at` - nothing that
    still waits can be fetched in this step, so it is not searched for either.
    With no topic fetched and owing its descriptions the step closes as at the
    ceiling (`_close_at_ceiling`, -> its answer). Otherwise only the waiting
    topics are skipped and the fetched ones go on to their descriptions and
    the sieve in the reserve: -> None."""
    why = _deadline_why(rec, clock)
    if not any(x.get("phase") == PH_FETCHED for x in rec["topics"].values()):
        return _close_at_ceiling(bdir, rec, log, out, clock, at, hunted, failed, why=why)
    closed = _skip_waiting(bdir, rec, why, hunted, failed)
    log.append({"step": "indexer-deadline", "at_step": at, "topics": sorted(closed),
                "at": _now()})
    for tid in sorted(closed):
        out(f"{STAGE}: {tid} skipped - WARNING {rec['topics'][tid]['warnings'][-1]}")
    return None


def _close_at_ceiling(bdir, rec, log, out, clock, at, hunted=(), failed=None, why=None):
    """The ceiling is spent: close the step without dropping a topic.

    Every topic still waiting (a request not taken, a `failed` retry) and
    every topic fetched but not finished becomes `skipped` with `outcome:
    wall_ceiling` and a warning, as `_fail` does after `MAX_TOOL_ATTEMPTS`.
    A request is left where it lies (not `consumed/`): the input of the
    future ingest queue, as for a tool that gave up. `verdict()` counts
    `skipped` as finished, so the stages after the step open. `at` names the
    point the ceiling was met; `hunted`/`failed` are what this very call
    learned about the pending topics before it. -> `(EXIT_DONE, verdict)`."""
    why = why or _ceiling_why(rec, clock, at)
    closed = _skip_waiting(bdir, rec, why, hunted, failed)
    fetched = [t for t, x in rec["topics"].items() if x.get("phase") == PH_FETCHED]
    shut, withdrawn = _close_fetched(bdir, rec, fetched, why, keep_sieved=False)
    closed += shut
    rec.pop("awaiting_descriptions", None)
    _stamp_ceiling(rec, clock, at, closed, withdrawn, log)
    rec["runs"].append({"half": WALL_CEILING, "at": _now(), "steps": list(log)})
    _write(bdir / RECORD, rec)
    for tid in sorted(closed):
        out(f"{STAGE}: {tid} skipped - WARNING {rec['topics'][tid]['warnings'][-1]}")
    return EXIT_DONE, verdict(bdir)


def _ceiling_why(rec, clock, at):
    return (f"{WALL_CEILING}: the step's wall-clock ceiling of "
            f"{rec.get('wall_ceiling_seconds')}s is spent ({_elapsed(rec, clock):.0f}s since "
            f"{rec.get('started_at')}, at {at}) - {WALL_TASK}")


def _close_fetched(bdir, rec, tids, why, keep_sieved):
    """The ceiling is spent over the fetched topics `tids`: their supplement
    sources the sieve has not kept are withdrawn (`_withdraw_unsieved`) and
    the topic is `skipped` `wall_ceiling`. With `keep_sieved` (CF-0454: the
    sieve has just judged the described sources) a topic still holding a
    source the sieve kept is not closed - it stays `fetched` and finishes
    like any other, the withdrawn ones noted. -> `(skipped, withdrawn)`."""
    withdrawn = _withdraw_unsieved(bdir, rec, list(tids), rec.get("wall_ceiling_seconds"))
    idx = _read(Path(bdir) / INDEX_FILE)
    sbt = (idx.get("sources_by_topic") if isinstance(idx, dict) else None) or {}
    closed = []
    for tid in tids:
        x = rec["topics"][tid]
        vids = withdrawn.get(tid) or []
        if vids:
            x["withdrawn_sources"] = vids
        still = [v for v in x.get("new_sources") or [] if v in (sbt.get(tid) or [])]
        if keep_sieved and still:
            if vids:
                x.setdefault("warnings", []).append(
                    f"{len(vids)} supplement source(s) still not described when the ceiling "
                    f"was spent taken out of the pool ({', '.join(vids)}): {INDEX_FILE} "
                    f"failed[] reason_code {WITHDRAWN_CODE}, refused_at {WALL_CEILING}; the "
                    f"{len(still)} the sieve kept stay ({', '.join(still)}) - {SIEVE_TASK}")
            continue
        x.update(phase=PH_SKIPPED, fetch_outcome=x.get("outcome"), outcome=WALL_CEILING,
                 skipped_at=_now())
        x.setdefault("warnings", []).append(
            f"supplement closed before its sources were described and sieved - the "
            f"topic goes on with the pool it had; {why}")
        if vids:
            x["warnings"].append(
                f"{len(vids)} supplement source(s) not described/sieved taken out of the "
                f"pool ({', '.join(vids)}): {INDEX_FILE} failed[] reason_code "
                f"{WITHDRAWN_CODE}, refused_at {WALL_CEILING}")
        closed.append(tid)
    return closed, withdrawn


def _stamp_ceiling(rec, clock, at, closed, withdrawn, log):
    rec["wall_ceiling"] = {"reached_at": _now(), "at": at,
                           "elapsed_seconds": round(_elapsed(rec, clock)),
                           "ceiling_seconds": rec.get("wall_ceiling_seconds"),
                           "topics": sorted(closed), "withdrawn_sources": withdrawn}
    log.append({"step": "wall-ceiling", "at_step": at, "topics": sorted(closed),
                "withdrawn": withdrawn, "at": _now()})


# --------------------------------------------------------------------------
# CF-0422: the plan check after the supplement
# --------------------------------------------------------------------------
#
# Step 6b of the Researcher (`plan_check_loop.py --write`, CF-0411) does not
# drop a script whose topic has an open supplement request: it defers it
# (`deferred_for_supplement`). After this step the orchestrator runs
# `plan_check_loop.py <batch> --write --after-supplement` on the enlarged
# pool - only there is a plan still not built `plan_unassembled`. Until that
# check has settled every deferred script, the stages after the Researcher
# stay closed, by the same marker gate and the same `--anyway`. The answer is
# the Researcher's own (`--pending-after-supplement --json`); a batch with no
# 03, or a checkout without the Researcher's script, is not refused - as the
# supplement step itself is not refused when it cannot read its state.

PLAN_TASK = "CF-0422"
PLAN_LOOP = Path("agents") / "content-researcher" / "scripts" / "plan_check_loop.py"
PLAN_PENDING_TIMEOUT_S = 120


def plan_check_command(batch_dir, root=None):
    """argv of the check after the supplement, with the Researcher's interpreter."""
    root = _abs(_root(root))
    return [_py(root, "content-researcher"), str(root / PLAN_LOOP), str(_abs(batch_dir)),
            "--write", "--after-supplement"]


def plan_check_pending(batch_dir, root=None):
    """`[{script_id, topic_id, slug, ...}]` of the scripts deferred at 6b that
    the check after the supplement has not settled; `[]` none; None when it
    cannot be answered (no 03, no plan_check_loop.py, the query failed)."""
    root = _abs(_root(root))
    bdir = _abs(batch_dir)
    script = root / PLAN_LOOP
    if not (bdir / SCRIPTS_FILE).is_file() or not script.is_file():
        return None
    try:
        p = subprocess.run([_py(root, "content-researcher"), str(script), str(bdir),
                            "--pending-after-supplement", "--json"],
                           cwd=str(root), text=True, capture_output=True,
                           timeout=PLAN_PENDING_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode not in (0, 1):
        return None
    try:
        rows = json.loads(p.stdout).get("pending")
    except (ValueError, AttributeError):
        return None
    return rows if isinstance(rows, list) else None


def plan_blocks(stage, batch_dir, root=None):
    """The CF-0422 refusal of `runlog stage-start <stage>`, or None:
    `{"pending": [rows], "command": str, "reason": str}`."""
    if stage not in GATED_STAGES:
        return None
    rows = plan_check_pending(batch_dir, root)
    if not rows:
        return None
    cmd = " ".join(plan_check_command(batch_dir, root))
    names = ", ".join(f"{r.get('script_id')} ({r.get('slug')})" for r in rows)
    reason = (f"{len(rows)} script(s) deferred at step 6b for the thin-pool supplement "
              f"still owe the plan check after it ({PLAN_TASK}): {names} - run `{cmd}` "
              f"(exit 1: edit the anchors it names and run it again; exit 5: the "
              f"supplement of a topic is not closed yet - finish "
              f"`scripts/thin_pool_supplement.py <batch>` first)")
    return {"pending": rows, "command": cmd, "reason": reason}


# --------------------------------------------------------------------------
# the commands
# --------------------------------------------------------------------------

def _py(root, agent):
    venv = root / "agents" / agent / ".venv" / "bin" / "python3"
    return str(venv) if venv.exists() else sys.executable


# CF-0454: the sieve of this step judges; it fetches nothing. Run 1248Z
# (2026-09-30): the step's sieve (`source_sieve.py <batch>`, the whole batch)
# spent 854 s of the ceiling and was killed at it - not on the two supplement
# sources (their flag answers took under a second: "nothing to mark") but in
# `apply_sieve`'s top-up of another topic, lf-2026-09-27-001: a kept source
# with burned-text shots (CF-0435) and a pool of 57 usable shots under the
# depth floor of 60 made the sieve re-walk that topic, download NvKt1-z08do at
# 14:40 and index it until 14:51 - for a topic the Researcher had already lost
# at `scripts` and the reserve had replaced. The kill then withdrew both
# described supplement sources. A top-up or a reserve substitution is the
# Indexer stage's business (its own sieve run, before the Researcher); after
# the Researcher it can only buy footage no script reads, inside this step's
# ceiling. `--no-top-up` is the sieve's own switch for exactly that - "judge,
# record, refuse, no download", and no reserve either (`source_sieve.main`) -
# so the footage-indexer needs no change for it. A supplement source the sieve
# refuses leaves its topic with the pool it had, as the step always promised
# (one round per topic per batch).
SIEVE_NO_FETCH = "--no-top-up"


def commands(batch_dir, root=None, requests=(), deadline=None):
    """`{step: (argv, cwd)}` for the machine steps, from the checkout's own
    agents. `requests` are the request files of this round.

    CF-0366: every path is made absolute here - the hunter and the indexer
    run from their own directories (`cwd`), so a batch or a request given
    relative to the caller's directory is not found there (batch 1722Z: the
    hunter's `No such file or directory` burned attempt 1/2).

    CF-0429: `deadline` (epoch seconds) is handed to the indexer as
    `--deadline`, whole seconds rounded down."""
    root = _abs(_root(root))
    batch_dir = _abs(batch_dir)
    requests = [_abs(r) for r in requests]
    b = str(batch_dir)
    hunter = root / "agents" / "trend-hunter"
    indexer = root / "agents" / "footage-indexer"
    writer = root / "agents" / "content-researcher" / "scripts"
    reqs = [str(r) for r in requests]
    s03 = str(Path(batch_dir) / SCRIPTS_FILE)
    cov = str(Path(batch_dir) / RECHECK_DIR / "coverage.json")
    sup = [a for r in reqs for a in ("--supplement", r)]
    dl = ["--deadline", str(int(deadline))] if deadline is not None else []
    py_w = _py(root, "content-researcher")
    return {
        "hunter": ([_py(root, "trend-hunter"), "scripts/footage_candidates.py", *sup,
                    "--search", "--write"], hunter),
        "indexer": ([_py(root, "footage-indexer"), "scripts/ingest_batch.py", b, *dl,
                     "--supplement", *reqs], indexer),
        "sieve": ([_py(root, "footage-indexer"), "scripts/source_sieve.py", b,
                   SIEVE_NO_FETCH], indexer),
        "recheck-coverage": ([py_w, str(writer / "check_anchor_coverage.py"), s03,
                              "--write", "--out", cov], root),
        "recheck-sides": ([py_w, str(writer / "check_alternate_sides.py"), s03,
                           "--reports", cov, "--write"], root),
        "recheck-blocks": ([py_w, str(writer / "check_block_capacity.py"), s03,
                            "--reports", cov, "--write"], root),
    }


def read_env_file(path):
    """`KEY=VALUE` lines of a dotenv file as `set -a; source` reads the plain
    ones: comments, blanks and `export ` skipped, one layer of quotes off."""
    out = {}
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].strip()
        k, v = line.split("=", 1)
        k, v = k.strip(), v.strip()
        if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
            v = v[1:-1]
        if k:
            out[k] = v
    return out


def hunter_env(root=None):
    """-> `(env, source)`: the environment the hunter runs in and where its
    `YOUTUBE_API_KEY` came from (`"environment"`, the `.env` path, or None
    when there is none). The key's value is never returned apart from `env`."""
    env = dict(os.environ)
    if env.get(API_KEY):
        return env, "environment"
    path = _root(root) / HUNTER_ENV
    vals = read_env_file(path)
    if not vals.get(API_KEY):
        return env, None
    for k, v in vals.items():
        if not env.get(k):
            env[k] = v
    return env, str(HUNTER_ENV)


def _redact(text, env):
    key = (env or {}).get(API_KEY) or os.environ.get(API_KEY)
    return text.replace(key, "<redacted>") if key and text else text


def _proc_group():
    """`shared/proc_group.py` by path (CF-0655), loaded only when a kill is needed."""
    import importlib.util  # noqa: PLC0415
    name = "factory_proc_group_cf0655"
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).resolve().parent.parent / "proc_group.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _kill_group(p, grace=10):
    """CF-0426: a step past its timeout is killed with everything it started
    (the indexer's yt-dlp and ffmpeg, the sieve's answerer) - `subprocess.run`
    would kill only the direct child and wait on the pipes the rest hold.
    CF-0655: the grace is for the whole group, not for the direct child - a
    grandchild that caught SIGTERM gets SIGKILL once it is over."""
    import signal
    pg = _proc_group()
    out, done = ("", ""), False
    t0 = time.monotonic()
    pg.signal_group(p.pid, signal.SIGTERM)
    try:
        out, done = p.communicate(timeout=grace), True
    except subprocess.TimeoutExpired:
        pass
    left = max(0.0, grace - (time.monotonic() - t0))
    if not pg.wait_gone(p.pid, left, reap=p.poll):
        pg.signal_group(p.pid, signal.SIGKILL)
        pg.wait_gone(p.pid, pg.KILL_WAIT_S, reap=p.poll)
    if not done:
        try:
            out = p.communicate(timeout=pg.KILL_WAIT_S)
        except subprocess.TimeoutExpired:
            pass
    return out[0] or "", out[1] or ""


def child_env(env=None):
    """CF-0541: the environment a step's child gets, with `RUNLOG_BATCH`
    absolute. The hunter and the indexer run with `cwd=agents/<agent>`; a
    relative batch inherited from the operator's shell
    (`RUNLOG_BATCH=pipeline/example-film/<batch>`) was read from there and
    their events were lost (0701Z: `[runlog] event not written
    (FileNotFoundError: .../agents/trend-hunter/pipeline/...)`)."""
    env = dict(env if env is not None else os.environ, RUNLOG_STAGE=STAGE)
    try:
        here = str(Path(__file__).resolve().parent)
        if here not in sys.path:
            sys.path.insert(0, here)
        import runlog                                   # noqa: E402 - lazy: runlog imports us
        runlog.normalize_batch_env(env)
    except Exception:                                   # noqa: BLE001 - accounting never breaks the step
        if env.get("RUNLOG_BATCH") and not os.path.isabs(env["RUNLOG_BATCH"]):
            env["RUNLOG_BATCH"] = os.path.abspath(os.path.expanduser(env["RUNLOG_BATCH"]))
    return env


def _run(argv, cwd, env=None, timeout=None):
    env = child_env(env)
    p = subprocess.Popen(argv, cwd=str(cwd), env=env, text=True, stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, start_new_session=True)
    try:
        so, se = p.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        so, se = _kill_group(p)
        sys.stdout.write(_redact(so or "", env))
        sys.stderr.write(_redact(se or "", env))
        raise
    sys.stdout.write(_redact(so, env))
    sys.stderr.write(_redact(se, env))
    return p.returncode


# CF-0229: the ceiling of one recheck step (the content-researcher's pool
# gates over 03). They ran with none: `_run(timeout=None)` is communicate()
# with no deadline. Measured 03.10 over the 21 recheck steps in
# work/supplement-step.json of every batch on disk: the slowest took 50 s
# (recheck-coverage, 2026-09-27T0929Z); x1.4 throttling x2 is 140 s, so 600 s
# is a hang, not slow work. A step killed at it is logged `timed_out` like any
# other and the recheck reads whatever the gate managed to write.
RECHECK_TIMEOUT_SECONDS = 600


# `_step`'s answer for a step killed at its timeout (CF-0426) - not an exit
# code, not a tool failure: the step's wall-clock ceiling was met inside it.
TIMED_OUT = "timeout"


def _step(log, name, argv, cwd, run, env=None, timeout=None):
    kw = {}
    if env is not None:
        kw["env"] = env
    if timeout is not None:
        kw["timeout"] = timeout
    err = None
    try:
        code = run(argv, cwd, **kw)
    except subprocess.TimeoutExpired:
        code = TIMED_OUT
    except (OSError, subprocess.SubprocessError) as e:
        code, err = None, f"{e.__class__.__name__}: {e}"
    row = {"step": name, "argv": [str(a) for a in argv],
           "exit": None if code == TIMED_OUT else code, "at": _now()}
    if timeout is not None:
        row["timeout_seconds"] = round(timeout)
    if code == TIMED_OUT:
        row["timed_out"] = True
    if err:
        row["error"] = err
    log.append(row)
    return code


def _budget(rec, clock):
    """The timeout of a step: what is left of the ceiling, at least 1 s."""
    return max(1.0, _remaining(rec, clock))


def _warnings(batch_dir, topics):
    """`{topic: [gate...]}` of the pool warnings (`WARNING_CODES`) 03 carries now."""
    d = _read(Path(batch_dir) / SCRIPTS_FILE) or {}
    out = {t: [] for t in topics}
    for w in d.get("warnings") or []:
        if isinstance(w, dict) and w.get("topic_id") in out \
                and w.get("warning_code") in WARNING_CODES:
            out[w["topic_id"]].append(w.get("gate"))
    return out


def _supplement_count(batch_dir):
    idx = _read(Path(batch_dir) / INDEX_FILE)
    return len(idx.get("supplements") or []) if isinstance(idx, dict) else 0


# The indexer's word for an entry it flushed mid-walk (a call killed before it
# finished the request) - footage-indexer `ingest_batch.IN_PROGRESS`.
IN_PROGRESS = "in_progress"


def _indexer_answers(batch_dir, tids, since, killed):
    """CF-0429: what this call's indexer wrote for `tids` -> `(fresh, cut)`.

    `fresh` - `{topic: entry}`, the last `supplements[]` entry appended after
    index `since` (the count before the call). `cut` - `{topic: block}` for
    each topic the deadline cut: its entry carries `wall_ceiling`, or its
    outcome is `wall_ceiling`/`in_progress`, or (`killed`: the root's timeout
    took the call) it has no entry at all. The block keeps what got in
    (`new_sources`) and the candidates the cut took."""
    idx = _read(Path(batch_dir) / INDEX_FILE)
    rows = (idx.get("supplements") or []) if isinstance(idx, dict) else []
    fresh = {}
    for e in rows[since:]:
        if isinstance(e, dict) and e.get("topic_id") in tids:
            fresh[e["topic_id"]] = e
    cut = {}
    for tid in tids:
        e = fresh.get(tid)
        if e is None and not killed:
            continue
        e = e or {}
        wall = e.get(WALL_CEILING) if isinstance(e.get(WALL_CEILING), dict) else {}
        if e and not wall and e.get("outcome") not in (WALL_CEILING, IN_PROGRESS):
            continue
        cut[tid] = {
            "task": INDEXER_TASK,
            "cause": wall.get("cause") or ("root_timeout" if killed else "deadline"),
            "deadline": wall.get("deadline"), "reached_at": wall.get("reached_at") or _now(),
            "entry_outcome": e.get("outcome"),
            "new_sources": list(e.get("new_sources") or []),
            "candidates": [c.get("video_id") for c in wall.get("candidates") or []
                           if isinstance(c, dict)]}
    return fresh, cut


def _supplement_entries(batch_dir):
    idx = _read(Path(batch_dir) / INDEX_FILE) or {}
    by = {}
    for e in idx.get("supplements") or []:
        if isinstance(e, dict) and e.get("topic_id"):
            by[e["topic_id"]] = e                   # the last answer wins
    return idx, by


def _dropped(batch_dir, topics):
    """Topics of this step that 03 refused - only to be reported: the step
    itself never writes a refusal, and a topic listed here was refused by a
    gate for a reason the pool gates still refuse on (no indexed source)."""
    d = _read(Path(batch_dir) / SCRIPTS_FILE) or {}
    return sorted({s.get("topic_id") for s in d.get("skipped") or []
                   if isinstance(s, dict) and s.get("topic_id") in topics})


def _failed_searches(req):
    """The searches of a filled request that failed (`search_failed`)."""
    block = (req or {}).get("search") or {}
    return [u for u in block.get("searches_unrun") or []
            if isinstance(u, dict) and u.get("reason_code") == "search_failed"]


def _hunter_note(path):
    """A warning for an answered request with no candidates whose searches
    partly failed, or None (CF-0414). The hunter's exit code belongs to the
    whole run (exit 1 = some request of it had every search fail), so it is
    never pinned on a topic; a request left empty after searches that ran is
    an answer, not a warning."""
    req = _read(path) or {}
    if req.get("candidates"):
        return None
    failed = _failed_searches(req)
    if not failed:
        return None
    return (f"hunter: {len(failed)} search(es) failed, no candidates: "
            f"{str(failed[0].get('reason') or '')[:200]}")


def _hunter_failed(code, path, before):
    """Why the hunter gave this request no answer, or None when it did
    (CF-0350). Exit 0 covers empty requests too; exit 1 means some request
    of the run had every search fail (CF-0414) - this finds which."""
    if code is None:
        return "the hunter did not start"
    if code not in (0, 1):
        return f"hunter exit {code}"
    try:
        now = Path(path).read_bytes()
    except OSError:
        return "the request is gone after the hunter"
    req = _read(path) or {}
    if req.get("candidates"):
        return None
    if code and now == before:
        return f"hunter exit {code} and the request untouched"
    failed = _failed_searches(req)
    if failed and not (req.get("search") or {}).get("searches"):
        return (f"every search failed ({len(failed)}): "
                f"{str(failed[0].get('reason') or '')[:200]}")
    return None


def _fail(rec, tid, request, why, hunted):
    """Count a failed attempt of a topic; -> its phase after it."""
    prev = rec["topics"].get(tid) or {}
    failures = list(prev.get("tool_failures") or []) + [{"at": _now(), "reason": why}]
    x = {"phase": PH_FAILED, "request": str(request), "attempts": len(failures),
         "tool_failures": failures, "hunted": bool(prev.get("hunted") or hunted),
         "warnings": []}
    if len(failures) >= MAX_TOOL_ATTEMPTS:
        x.update(phase=PH_SKIPPED, outcome="tool_failed", skipped_at=_now(),
                 warnings=[f"supplement skipped after {len(failures)} failed attempt(s) - "
                           f"the topic goes on without it; last: {why}"])
    rec["topics"][tid] = x
    return x["phase"]


def rerun_mode(batch_dir):
    """CF-0494: the rerun mode of the batch from its own batch-start event
    (`runlog.rerun_mode`), or None - no events, no batch-start, no flag."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import runlog                                   # noqa: E402 - lazy: runlog imports us
        return runlog.rerun_mode(runlog.read_events(_abs(batch_dir)))
    except Exception:                                   # noqa: BLE001
        return None


def _close_no_search(bdir, rec, out):
    """CF-0494: every pending request of a `--rerun no-search` batch becomes
    `skipped`, `outcome: rerun_no_search`, with no tool started and no clock;
    the request stays where it lies. -> the closed topic ids."""
    pending = [(p, r) for p, r in request_files(bdir)
               if not _taken(rec["topics"], r["topic_id"])]
    closed = []
    for p, r in pending:
        tid = r["topic_id"]
        prev = rec["topics"].get(tid) or {}
        rec["topics"][tid] = {
            "phase": PH_SKIPPED, "outcome": RERUN_NO_SEARCH, "request": str(p),
            "skipped_at": _now(), "attempts": len(prev.get("tool_failures") or []),
            "rerun": RERUN_NO_SEARCH_MODE,
            "warnings": [f"supplement skipped - the batch is a verification rerun opened "
                         f"with `runlog batch-start --rerun no-search` ({RERUN_TASK}): "
                         f"nothing searched or fetched, the topic goes on with its pool "
                         f"as it is"]}
        if prev.get("tool_failures"):
            rec["topics"][tid]["tool_failures"] = list(prev["tool_failures"])
        closed.append(tid)
        out(f"{STAGE}: {tid} skipped - {RERUN_NO_SEARCH} ({RERUN_TASK})")
    if closed:
        rec["runs"].append({"half": "rerun-no-search", "at": _now(), "steps": [
            {"step": "rerun-no-search", "mode": RERUN_NO_SEARCH_MODE,
             "from": "batch-start --rerun no-search", "topics": sorted(closed),
             "at": _now()}]})
        _write(bdir / RECORD, rec)
    return closed


def _close_disabled(bdir, rec, out, source):
    """CF-0842: every pending request of a channel whose supplement is off
    becomes `skipped`, `outcome: supplement_disabled`, with no tool started
    and no clock; the request stays where it lies. -> the closed topic ids."""
    pending = [(p, r) for p, r in request_files(bdir)
               if not _taken(rec["topics"], r["topic_id"])]
    closed = []
    for p, r in pending:
        tid = r["topic_id"]
        prev = rec["topics"].get(tid) or {}
        rec["topics"][tid] = {
            "phase": PH_SKIPPED, "outcome": SUPPLEMENT_DISABLED, "request": str(p),
            "skipped_at": _now(), "attempts": len(prev.get("tool_failures") or []),
            "disabled_by": source,
            "warnings": [f"supplement skipped - the channel switched the step off "
                         f"({source}: false, {ENABLED_TASK}): nothing searched or "
                         f"fetched, the topic goes on with its pool as it is"]}
        for k in ("tool_failures", "hunted"):
            if prev.get(k):
                rec["topics"][tid][k] = prev[k]
        closed.append(tid)
        out(f"{STAGE}: {tid} skipped - {SUPPLEMENT_DISABLED} ({source})")
    if closed:
        rec["runs"].append({"half": "supplement-disabled", "at": _now(), "steps": [
            {"step": "supplement-disabled", "task": ENABLED_TASK, "from": source,
             "topics": sorted(closed), "at": _now()}]})
        _write(bdir / RECORD, rec)
    return closed


def too_thin_topics(batch_dir, root=None):
    """CF-0845: `{topic_id: row}` of the measured topics under the channel's
    floor of usable shots (`thin_topic.thin_topics`); {} when the rule is
    off or nothing is measured."""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import thin_topic                                   # noqa: E402 - lazy: it imports us
    return {r["topic_id"]: r for r in thin_topic.thin_topics(batch_dir, root)}


def _close_too_thin(bdir, rec, out, root=None):
    """CF-0845: every pending request of a topic under the channel's floor of
    usable shots becomes `skipped`, `outcome: too_thin`, with no tool started
    and no clock; the request stays where it lies. -> the closed topic ids."""
    thin = too_thin_topics(bdir, root)
    pending = [(p, r) for p, r in request_files(bdir)
               if not _taken(rec["topics"], r["topic_id"]) and r["topic_id"] in thin]
    closed = []
    for p, r in pending:
        tid = r["topic_id"]
        row = thin[tid]
        prev = rec["topics"].get(tid) or {}
        rec["topics"][tid] = {
            "phase": PH_SKIPPED, "outcome": TOO_THIN, "request": str(p),
            "skipped_at": _now(), "attempts": len(prev.get("tool_failures") or []),
            "usable_shots_before": row["usable_shots"], "min_usable_shots": row["floor"],
            "floor_from": row["floor_from"],
            "warnings": [f"supplement skipped - {row['usable_shots']} usable shot(s) in the "
                         f"topic's pool, under the floor of {row['floor']} "
                         f"({row['floor_from']}, {TOO_THIN_TASK}): no topic this thin was "
                         f"ever saved by a supplement - nothing searched or fetched"]}
        for k in ("tool_failures", "hunted"):
            if prev.get(k):
                rec["topics"][tid][k] = prev[k]
        closed.append(tid)
        out(f"{STAGE}: {tid} skipped - {TOO_THIN} ({row['usable_shots']} usable < "
            f"{row['floor']})")
    if closed:
        rec["runs"].append({"half": "too-thin", "at": _now(), "steps": [
            {"step": "too-thin", "task": TOO_THIN_TASK, "topics": sorted(closed),
             "usable_shots": {t: thin[t]["usable_shots"] for t in sorted(closed)},
             "floor": thin[closed[0]]["floor"], "from": thin[closed[0]]["floor_from"],
             "at": _now()}]})
        _write(bdir / RECORD, rec)
    return closed


def live_topics(batch_dir):
    """CF-0826: `{topic_id}` 03 lists in `scripts[]`, or None when 03 cannot
    be read (absent, not JSON, no `scripts` list) - then nobody is called
    dropped."""
    d = _read(Path(batch_dir) / SCRIPTS_FILE)
    scripts = d.get("scripts") if isinstance(d, dict) else None
    if not isinstance(scripts, list):
        return None
    return {s.get("topic_id") for s in scripts if isinstance(s, dict) and s.get("topic_id")}


def _drop_reasons(batch_dir):
    """`{topic_id: reason_code}` from 03's `skipped[]` (the last entry wins)."""
    d = _read(Path(batch_dir) / SCRIPTS_FILE) or {}
    out = {}
    for s in (d.get("skipped") or []) if isinstance(d, dict) else []:
        if isinstance(s, dict) and s.get("topic_id"):
            out[s["topic_id"]] = s.get("reason_code") or s.get("reason") or "skipped"
    return out


def _close_dropped(bdir, rec, out):
    """CF-0826: every pending request of a topic not in 03's `scripts[]`
    becomes `skipped`, `outcome: topic_dropped`, with no tool started and no
    clock; the request stays where it lies. -> the closed topic ids."""
    live = live_topics(bdir)
    if live is None:
        return []
    pending = [(p, r) for p, r in request_files(bdir)
               if not _taken(rec["topics"], r["topic_id"]) and r["topic_id"] not in live]
    if not pending:
        return []
    reasons = _drop_reasons(bdir)
    closed, why = [], {}
    for p, r in pending:
        tid = r["topic_id"]
        prev = rec["topics"].get(tid) or {}
        why[tid] = (f"03 skipped[] {reasons[tid]}" if tid in reasons
                    else "not in 03 scripts[]")
        rec["topics"][tid] = {
            "phase": PH_SKIPPED, "outcome": TOPIC_DROPPED, "request": str(p),
            "skipped_at": _now(), "attempts": len(prev.get("tool_failures") or []),
            "dropped": why[tid],
            "warnings": [f"supplement skipped - the topic is no longer in the batch "
                         f"({why[tid]}, {DROPPED_TASK}): nothing searched or fetched "
                         f"for it"]}
        for k in ("tool_failures", "hunted"):
            if prev.get(k):
                rec["topics"][tid][k] = prev[k]
        closed.append(tid)
        out(f"{STAGE}: {tid} skipped - {TOPIC_DROPPED} ({why[tid]})")
    rec["runs"].append({"half": "topic-dropped", "at": _now(), "steps": [
        {"step": "topic-dropped", "task": DROPPED_TASK, "topics": sorted(closed),
         "why": why, "at": _now()}]})
    _write(bdir / RECORD, rec)
    return closed


def advance(batch_dir, root=None, run=None, out=print, clock=None):
    """Do the next part of the step. Returns `(exit_code, verdict)`.

    `run(argv, cwd) -> exit code` is the command runner (a subprocess by
    default; the tests hand in a recorder). `clock() -> epoch seconds` is the
    wall clock the CF-0426 ceiling is counted on (`time.time` by default; the
    tests hand in a fake one)."""
    run = run or _run
    clock = clock or time.time
    bdir = _abs(batch_dir)                  # CF-0366: see `commands`
    rec = record(bdir)
    log = []
    v = verdict(bdir)
    if v["state"] == NONE:
        out(f"{STAGE}: no request under {REQUEST_DIR}/ - the step is skipped")
        return EXIT_DONE, v
    if v["state"] == DONE:
        out(f"{STAGE}: already done for {', '.join(v['done'])}")
        return EXIT_DONE, v
    if v["state"] == PENDING:                                           # CF-0842
        on, source = supplement_enabled(bdir, root)
        if not on:
            _close_disabled(bdir, rec, out, source)
            v = verdict(bdir)
            if v["state"] == DONE:
                return EXIT_DONE, v
    if v["state"] == PENDING and rerun_mode(bdir) == RERUN_NO_SEARCH_MODE:   # CF-0494
        _close_no_search(bdir, rec, out)
        v = verdict(bdir)
        if v["state"] == DONE:
            return EXIT_DONE, v
    if v["state"] == PENDING and _close_dropped(bdir, rec, out):   # CF-0826
        v = verdict(bdir)
        if v["state"] == DONE:
            return EXIT_DONE, v
    if v["state"] == PENDING and _close_too_thin(bdir, rec, out, root):   # CF-0845
        v = verdict(bdir)
        if v["state"] == DONE:
            return EXIT_DONE, v
    if _start_clock(rec, bdir, root, clock):
        _write(bdir / RECORD, rec)
    if _spent(rec, clock):                  # CF-0426
        if not any(x.get("phase") == PH_FETCHED for x in rec["topics"].values()):
            return _close_at_ceiling(bdir, rec, log, out, clock, "start")
        # CF-0454: the fetched topics were sent to be described - their sieve
        # finishes that work below. Only what still waits is closed here.
        why = _ceiling_why(rec, clock, "start")
        closed = _skip_waiting(bdir, rec, why)
        log.append({"step": "wall-ceiling-waiting", "at_step": "start",
                    "topics": sorted(closed), "at": _now()})
        for tid in sorted(closed):
            out(f"{STAGE}: {tid} skipped - WARNING {rec['topics'][tid]['warnings'][-1]}")

    # -- first half: fetch what the pending requests ask for -------------
    pending = [(p, r) for p, r in request_files(bdir)
               if not _taken(rec["topics"], r["topic_id"])]
    code_first = EXIT_DONE
    # This call took requests: what it fetches - and a retry's topics fetched
    # on the call before it, never sent to be described - owe descriptions
    # first, even when the deadline below skips the requests themselves.
    took = bool(pending)
    deadline = indexer_deadline(rec)        # CF-0429
    if pending and clock() >= deadline:
        # The indexer's window is gone: what waits is not searched for (no
        # quota spent on what cannot be fetched) - closed, or skipped while
        # topics already fetched go on to their descriptions.
        hunted0 = {r["topic_id"] for _, r in pending
                   if (rec["topics"].get(r["topic_id"]) or {}).get("hunted")}
        at = "indexer" if hunted0 == {r["topic_id"] for _, r in pending} else "hunter"
        closed = _deadline_passed(bdir, rec, log, out, clock, at, hunted0)
        if closed is not None:
            return closed
        pending = []
    if pending:
        tids = [r["topic_id"] for _, r in pending]
        before = _warnings(bdir, tids)
        failed = {}                                 # topic -> why, this call
        hunted, notes = set(), {}                  # notes: topic -> hunter warning
        # A topic whose hunter answered on an earlier attempt (the indexer
        # failed after it) is not searched again: its quota is spent.
        to_hunt = [(p, r) for p, r in pending
                   if not (rec["topics"].get(r["topic_id"]) or {}).get("hunted")]
        hunted |= {r["topic_id"] for p, r in pending} - {r["topic_id"] for p, r in to_hunt}
        h = 0
        if to_hunt:
            env, source = hunter_env(root)
            if source is None:
                h = None
                why = (f"{NO_KEY}: no {API_KEY} in the environment nor in "
                       f"{HUNTER_ENV} - the hunter was not started")
                log.append({"step": "hunter", "skipped": why, "at": _now()})
                for _, r in to_hunt:
                    failed[r["topic_id"]] = why
            else:
                snap = {}
                for p, _ in to_hunt:
                    try:
                        snap[p] = p.read_bytes()
                    except OSError:
                        snap[p] = None
                h = _step(log, "hunter", *commands(bdir, root, [p for p, _ in to_hunt])["hunter"],
                          run, env=env, timeout=_budget(rec, clock))
                log[-1]["key_from"] = source
                if h == TIMED_OUT:
                    return _close_at_ceiling(bdir, rec, log, out, clock, "hunter", hunted)
                for p, r in to_hunt:
                    why = _hunter_failed(h, p, snap[p])
                    if why:
                        failed[r["topic_id"]] = _redact(why, env)
                    else:
                        hunted.add(r["topic_id"])
                        note = _hunter_note(p)
                        if note:
                            notes[r["topic_id"]] = _redact(note, env)
        answered = [(p, r) for p, r in pending if r["topic_id"] not in failed]
        if answered and clock() >= deadline:
            # CF-0429: the hunter ran into the indexer's deadline.
            closed = _deadline_passed(bdir, rec, log, out, clock, "indexer", hunted, failed)
            if closed is not None:
                return closed
            answered, failed = [], {}
        fresh, cut = {}, {}
        if answered:
            # CF-0426/CF-0429: the longest part of the step (42 min in 0929Z)
            # runs up to its deadline - the ceiling less the reserve for the
            # describing, the sieve and the recheck; the process timeout is
            # only the net a little behind it.
            since = _supplement_count(bdir)
            i = _step(log, "indexer",
                      *commands(bdir, root, [p for p, _ in answered], deadline)["indexer"],
                      run, timeout=_indexer_timeout(rec, clock, deadline))
            log[-1].update(deadline=_iso(deadline), deadline_epoch=int(deadline),
                           reserve_seconds=round(indexer_reserve(_ceiling(rec))))
            if i in (0, TIMED_OUT):
                # CF-0429: the deadline (or, behind it, the timeout) may have
                # cut the call. What got into 01b before it is kept and goes
                # on to the descriptions and the sieve like any new source;
                # only when nothing of any request got in is the step closed
                # here, as at the ceiling.
                tids_a = [r["topic_id"] for _, r in answered]
                fresh, cut = _indexer_answers(bdir, tids_a, since, i == TIMED_OUT)
                if cut and all(t in cut and not cut[t]["new_sources"] for t in tids_a):
                    closed = _deadline_passed(bdir, rec, log, out, clock, "indexer",
                                              hunted, failed)
                    if closed is not None:
                        return closed
                    answered, failed, cut = [], {}, {}
                i = 0
            if i != 0:
                for _, r in answered:
                    failed[r["topic_id"]] = ("the indexer did not start" if i is None
                                             else f"indexer exit {i}")
                answered = []
        cdir = bdir / REQUEST_DIR / CONSUMED
        cdir.mkdir(parents=True, exist_ok=True)
        for p, _ in answered:
            if p.exists():
                os.replace(p, cdir / p.name)
        log.append({"step": "consumed", "moved": [p.name for p, _ in answered],
                    "kept": [p.name for p, r in pending if r["topic_id"] in failed],
                    "at": _now()})
        _, entries = _supplement_entries(bdir)
        for (p, r) in answered:
            tid = r["topic_id"]
            e = fresh.get(tid) or ({} if tid in cut else entries.get(tid)) or {}
            prev = rec["topics"].get(tid) or {}
            warn = [f"tool failed before: {f['reason']}" for f in prev.get("tool_failures") or []]
            if tid in notes:
                warn.append(notes[tid])
            if not e:
                warn.append("the indexer wrote no supplements[] entry")
            rec["topics"][tid] = {
                "phase": PH_FETCHED, "request": str(cdir / p.name),
                "fetched_at": _now(), "warnings_before": before.get(tid, []),
                "outcome": e.get("outcome"), "new_sources": list(e.get("new_sources") or []),
                "shots_before": e.get("shots_before"), "shots_after": e.get("shots_after"),
                "shots_added": e.get("shots_added"),
                "covers_shortfall": e.get("covers_shortfall"), "warnings": warn,
                **({"tool_failures": prev["tool_failures"]} if prev.get("tool_failures") else {})}
        if cut:
            _carry_cut(rec, cut, _deadline_why(rec, clock), out)
        retry = []
        for p, r in pending:
            tid = r["topic_id"]
            if tid not in failed:
                continue
            phase = _fail(rec, tid, p, failed[tid], tid in hunted)
            x = rec["topics"][tid]
            if phase == PH_FAILED:
                retry.append(tid)
                out(f"{STAGE}: {tid} - tool failure, attempt {x['attempts']}/"
                    f"{MAX_TOOL_ATTEMPTS}: {failed[tid]}; the request stays in "
                    f"{REQUEST_DIR}/, run the step again")
            else:
                out(f"{STAGE}: {tid} skipped - WARNING {x['warnings'][0]}")
        if retry and clock() >= deadline:
            # CF-0429: a retry could not be fetched any more - skipped now
            # rather than exit 3, so what was fetched goes on to be described.
            closed = _skip_waiting(bdir, rec, _deadline_why(rec, clock))
            log.append({"step": "indexer-deadline", "at_step": "retry",
                        "topics": sorted(closed), "at": _now()})
            for tid in sorted(closed):
                out(f"{STAGE}: {tid} skipped - WARNING {rec['topics'][tid]['warnings'][-1]}")
            retry = []
        rec["runs"].append({"half": "fetch", "at": _now(), "steps": log})
        _write(bdir / RECORD, rec)
        log = []
        if retry:
            only_key = all(failed[t].startswith(NO_KEY) for t in retry)
            code_first = EXIT_NO_KEY if only_key else EXIT_TOOL_FAILED

    if code_first != EXIT_DONE:
        return code_first, verdict(bdir)

    fetched = {t: x for t, x in rec["topics"].items() if x.get("phase") == PH_FETCHED}
    if not fetched:
        return EXIT_DONE, verdict(bdir)
    new = sorted({s for x in fetched.values() for s in x.get("new_sources") or []})

    # -- second half: sieve and recheck, only once the shots are described
    if new:
        want = set(new)
        if took:
            # Sources fetched this very call carry no descriptions yet; with
            # the ceiling spent nobody is asked to describe them (CF-0426).
            if _spent(rec, clock):
                return _close_at_ceiling(bdir, rec, log, out, clock, "descriptions")
            return _describe(bdir, rec, sorted(want), out)
        # CF-0454: the orchestrator was sent to describe them - the sieve that
        # judges the descriptions finishes done work and runs past a spent
        # ceiling too, with at least SIEVE_GRACE_SECONDS; it fetches nothing
        # (SIEVE_NO_FETCH).
        if _step(log, "sieve", *commands(bdir, root)["sieve"], run,
                 timeout=max(_budget(rec, clock), SIEVE_GRACE_SECONDS)) == TIMED_OUT:
            return _close_at_ceiling(bdir, rec, log, out, clock, "sieve")
        log[-1]["grace_seconds"] = SIEVE_GRACE_SECONDS
        idx, entries = _supplement_entries(bdir)
        unsieved = set((idx.get("source_sieve") or {}).get("unsieved") or [])
        owed = sorted(want & unsieved)
        if owed and not _spent(rec, clock):
            rec["runs"].append({"half": "sieve", "at": _now(), "steps": log})
            _write(bdir / RECORD, rec)
            return _describe(bdir, rec, owed, out)
        if owed:
            # CF-0454: past the ceiling only the sources still undescribed
            # are withdrawn; what the sieve kept stays and its topic finishes.
            owing = sorted(t for t, x in fetched.items()
                           if set(x.get("new_sources") or []) & set(owed))
            closed, withdrawn = _close_fetched(bdir, rec, owing,
                                               _ceiling_why(rec, clock, "sieve"),
                                               keep_sieved=True)
            rec.pop("awaiting_descriptions", None)
            _stamp_ceiling(rec, clock, "sieve", closed, withdrawn, log)
            for tid in closed:
                out(f"{STAGE}: {tid} skipped - WARNING {rec['topics'][tid]['warnings'][-1]}")
                fetched.pop(tid)
            if not fetched:
                rec["runs"].append({"half": WALL_CEILING, "at": _now(), "steps": list(log)})
                _write(bdir / RECORD, rec)
                return EXIT_DONE, verdict(bdir)
            idx, entries = _supplement_entries(bdir)
        cmds = commands(bdir, root)
        (bdir / RECHECK_DIR).mkdir(parents=True, exist_ok=True)
        for name in ("recheck-coverage", "recheck-sides", "recheck-blocks"):
            _step(log, name, *cmds[name], run, timeout=RECHECK_TIMEOUT_SECONDS)
        refused = set((idx.get("source_sieve") or {}).get("refused") or [])
    else:
        refused = set()
        log.append({"step": "recheck", "skipped": "no new source - the pool did not change",
                    "at": _now()})

    if new and _spent(rec, clock):
        # CF-0454: finished past the ceiling - the sieve and the recheck of
        # sources already described, not new work; said in the record.
        rec["finished_past_ceiling"] = {
            "task": SIEVE_TASK, "at": _now(), "elapsed_seconds": round(_elapsed(rec, clock)),
            "ceiling_seconds": rec.get("wall_ceiling_seconds"), "topics": sorted(fetched)}
    rec.pop("awaiting_descriptions", None)
    after = _warnings(bdir, list(fetched))
    dropped = _dropped(bdir, list(fetched))
    for tid, x in fetched.items():
        x["phase"] = PH_DONE
        x["done_at"] = _now()
        x["warnings_after"] = after.get(tid, []) if new else x.get("warnings_before", [])
        x["sieve_refused"] = sorted(refused & set(x.get("new_sources") or []))
        for row in log:
            if row.get("exit"):
                x["warnings"].append(f"{row['step']} exit {row['exit']}")
        if tid in dropped:
            x["warnings"].append("03 lists the topic in skipped[] - not by this step")
    rec["runs"].append({"half": "finish", "at": _now(), "steps": log})
    _write(bdir / RECORD, rec)
    v = verdict(bdir)
    for tid, x in sorted(fetched.items()):
        out(f"{STAGE}: {tid} done - {x.get('outcome')}, {len(x.get('new_sources') or [])} "
            f"new source(s), pool warnings {len(x['warnings_before'])} -> "
            f"{len(x['warnings_after'])}"
            + (f"; WARNING {'; '.join(x['warnings'])}" if x["warnings"] else ""))
    return EXIT_DONE, v


def _carry_cut(rec, cut, why, out):
    """CF-0429: the topics the indexer's deadline cut, after their requests
    were consumed and their records written `fetched`. A topic with sources
    that got in stays `fetched` - they go on to the descriptions and the
    sieve like any new source, the cut noted; a topic with none is `skipped`
    `wall_ceiling`, as at the ceiling. The step's record keeps the cut under
    `indexer_deadline`."""
    for tid, c in sorted(cut.items()):
        x = rec["topics"][tid]
        x["indexer_cut"] = c
        n, ids = len(c["candidates"]), ", ".join(c["candidates"])
        took = f"{n} candidate(s) not finished" + (f" ({ids})" if ids else "")
        if x.get("new_sources"):
            if x.get("outcome") in (IN_PROGRESS, WALL_CEILING, None):
                x["fetch_outcome"], x["outcome"] = x.get("outcome"), "sources"
            x["warnings"].append(
                f"{WALL_CEILING}: the indexer's deadline cut the request ({c['cause']}), "
                f"{took}; the {len(x['new_sources'])} source(s) that got in go on to "
                f"descriptions and the sieve - {INDEXER_TASK}")
        else:
            x.update(phase=PH_SKIPPED, fetch_outcome=x.get("outcome"), outcome=WALL_CEILING,
                     skipped_at=_now())
            x["warnings"].append(
                f"supplement skipped - no source of the topic got in before the indexer's "
                f"deadline ({c['cause']}, {took}); the topic goes on with the pool it had; "
                f"{why}")
            out(f"{STAGE}: {tid} skipped - WARNING {x['warnings'][-1]}")
    rec["indexer_deadline"] = {
        "task": INDEXER_TASK, "reached_at": _now(),
        "deadline": _iso(indexer_deadline(rec)),
        "reserve_seconds": round(indexer_reserve(_ceiling(rec))),
        "topics": sorted(cut),
        "carried_forward": {t: c["new_sources"] for t, c in sorted(cut.items())
                            if c["new_sources"]},
        "skipped": sorted(t for t, c in cut.items() if not c["new_sources"])}


def _describe(bdir, rec, ids, out):
    rec["awaiting_descriptions"] = ids
    _write(bdir / RECORD, rec)
    out(f"{STAGE}: describe every shot of {', '.join(ids)} (description, burned_text, "
        f"on_topic, shows_entity - agents/footage-indexer SKILL.md, CF-0344), then run "
        f"`scripts/thin_pool_supplement.py {bdir}` again")
    return EXIT_DESCRIBE, verdict(bdir)


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog="thin_pool_supplement.py",
                                 description="CF-0345: the thin-pool supplement step")
    ap.add_argument("batch")
    ap.add_argument("--dry-run", action="store_true",
                    help="print the state and the commands of the next round, run nothing")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--root", default=None)
    ns = ap.parse_args(argv)
    bdir = _abs(ns.batch)                   # CF-0366: see `commands`
    os.environ.update({k: v for k, v in child_env().items()
                       if k == "RUNLOG_BATCH"})     # CF-0541: before any child
    if not (bdir / SCRIPTS_FILE).is_file():
        print(f"{STAGE}: no {SCRIPTS_FILE} in {bdir} - the step runs after the "
              f"Content Researcher", file=sys.stderr)
        return EXIT_USAGE
    if ns.dry_run:
        v = verdict(bdir)
        pend = [Path(p) for p in v["pending"]]
        cmds = commands(bdir, ns.root, pend, indexer_deadline(record(bdir)))
        on, source = supplement_enabled(bdir, ns.root)             # CF-0842
        waiting = {r["topic_id"] for p, r in request_files(bdir) if str(p) in v["pending"]}
        thin = sorted(set(too_thin_topics(bdir, ns.root)) & waiting)          # CF-0845
        plan = {"verdict": v, "steps": list(STEPS), "rerun": rerun_mode(bdir),
                "enabled": on, "enabled_from": source, "too_thin": thin,
                "commands": {k: " ".join(a) for k, (a, _) in cmds.items()}}
        print(json.dumps(plan, indent=2, ensure_ascii=False) if ns.json
              else f"{STAGE}: {v['state']} - {v['reason']}"
              + (f" [{source}: false - the pending requests are closed "
                 f"{SUPPLEMENT_DISABLED}, nothing is run]"
                 if not on and v["state"] == PENDING else "")
              + (f" [rerun {plan['rerun']}: the pending requests are closed "
                 f"{RERUN_NO_SEARCH}, nothing is run]"
                 if on and plan["rerun"] == RERUN_NO_SEARCH_MODE and v["state"] == PENDING
                 else "")
              + (f" [{', '.join(thin)}: under the channel's floor of usable shots - "
                 f"closed {TOO_THIN}, not searched]" if on and thin else ""))
        return EXIT_DONE
    code, v = advance(bdir, ns.root)
    nxt = next_after_step(bdir, ns.root) if code == EXIT_DONE else None
    if ns.json:
        if nxt:
            v = dict(v, plan_check_after_supplement=nxt)
        print(json.dumps(v, indent=2, ensure_ascii=False))
    elif nxt:
        print(nxt["line"])
    return code


def next_after_step(batch_dir, root=None):
    """CF-0422: once the step is done, the command that comes next when step
    6b deferred scripts for it - `{"pending": [script_id], "command", "line"}`,
    or None. Informative only: this step never runs it, because that loop may
    stop for the writer's anchor edits."""
    rows = plan_check_pending(batch_dir, root)
    if not rows:
        return None
    cmd = " ".join(plan_check_command(batch_dir, root))
    ids = [r.get("script_id") for r in rows]
    return {"pending": ids, "command": cmd,
            "line": (f"{STAGE}: next - {len(ids)} script(s) deferred at step 6b wait for "
                     f"the plan check after the supplement ({PLAN_TASK}): "
                     f"{', '.join(map(str, ids))}. Run: {cmd}")}


if __name__ == "__main__":
    sys.exit(main())
