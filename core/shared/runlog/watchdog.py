#!/usr/bin/env python3
"""CF-0316: the watchdog over one operation of a stage.

On `example-film/2026-09-19T0116Z` the last event was
`footage-indexer/index PEiDNOQ_0ms start` and the next one came **28h30m40s**
later: wall 39h42m, real work 2h45m (6.9 %). Nobody was being asked anything -
the silence began in the middle of a binary call. This module is the ceiling
that stretch did not have.

What it kills, and what it does not
-----------------------------------
The user's decision (grill 2026-09-22, Q18): **a run is never dropped.** The
watchdog takes down one **operation** - one source, one child call - and the
stage goes on to the next one; the attempt ceiling of the topic is not spent.
A kill is therefore not a new gate in the sense of CF-0320: the topic loses a
source, not its life. (The day a kill can take a whole topic down, that *is* a
new gate and its price gets measured by `runlog gate-price` first.)

Hung, or long and honest
------------------------
The watchdog does not time an operation. It times its **silence**: the stretch
with no event of the operation's own subtree in `RUN_EVENTS.jsonl`. An honest
operation of any length talks - `index_footage.py` writes three thousand child
events while it works on a source - so a ceiling on silence cannot kill honest
work, while a ceiling on duration can and eventually will. A leaf binary call
writes nothing, so for it silence is its whole run and the two rules coincide.

Signs of life are **events only** (`kind: script` / `kind: child` under the
operation). Sampler samples are deliberately not a sign: CF-0339 taught the
sampler to leave after ten idle minutes of the run, so after an idle stretch
there are no samples to read and a sampler-based watchdog would kill the first
operation that survived one.

Where the ceilings come from (the arithmetic)
---------------------------------------------
Material: the three frozen runs CF-0112 measured (`2026-09-22T1001Z`,
`2026-09-21T1541Z`, `2026-09-21T0358Z`), re-read by
`scripts/watchdog_threshold.py`, which prints every number below.

*Measured silence inside honest `index_footage.py` operations* - 36 operations,
durations up to 52m40s, ~3 000 events each:

    p50 14.4 s    p90 78.7 s    max 209.5 s

*CF-0331 correction.* CF-0112's numbers are older than CF-0331, which stopped
`shot-full-frame` from launching one ffmpeg per sampled frame: p50 7.53 s ->
1.38 s per shot, **5.24x**. Carried over literally, CF-0112's own proposal
(ceiling on *duration*: max 52m40s x 3 = 2h40m) is 1.41x too soft - re-measured
with the same reader, the 36 operations lose 28.9 % of their time
(9h14m13s -> 6h34m09s, max 52m40s -> 37m19s), and the same x3 rule would now
read **1h52m**. That is the cost of taking a number from before the fix.
CF-0331 does **not** move the ceiling below, and that is the point of measuring
silence rather than duration: the worst honest silence is set by the longest
single binary call, and CF-0331 shortened frame grabbing, not the whole-file
scan. Two of the ten worst windows are `shot-full-frame` calls and they drop
54.5 s -> 10.4 s and 42.9 s -> 8.2 s; the worst window, 209.5 s, is not one.

*The ceiling on an operation's silence.* Not the observed maximum - the worst
**honest** silence the code is allowed to produce, which is larger:

    worst honest leaf that may run inside an operation
        a whole-file `source-scenedetect` scan. CF-0112 measured the ratio
        "seconds of scan per second of source" at 0.014..0.333; the channel's
        own duration ceiling (`ingest_batch.duration_ceiling`, 3600 s) bounds
        the source:                     0.333 x 3600 =        1200 s
    unlogged python around a leaf
        worst observed silence 209.5 s minus the worst bounded leaf CF-0112
        measured (`shot-split-probe`, 111.3 s):                 ~100 s
                                                          ------------
    worst honest silence                                        1300 s
    x 1.4 for thermal throttling (CF-0052, the factor CF-0128 uses)
                                                              = 1820 s
    rounded up to the next whole minute        SILENCE_CEILING_S = 1860 s (31 min)

Rounded **up**, not down to a prettier half-hour: a ceiling below the worst
honest silence is a watchdog that kills honest work, which the user's own words
call worse than no watchdog at all.

The safety margin is 1.4 and not CF-0112's 3 because the 1300 s is already a
worst case twice over (the worst measured ratio on the longest source the
channel permits), not an observed maximum. Against what was actually measured
the margin is **8.9x** (1860 / 209.5), and against the p90 of honest operations
**23.6x**. Against the incident: the 28h30m40s silence is cut at 31 minutes,
**55x** sooner, and the stage moves to the next source.

*Leaf ceilings* (CF-0112's level 1, unchanged by CF-0331 - it made the median
frame grab cheap, not the worst call):

    bounded by one shot   max 111.3 s (`shot-split-probe`) x 3 -> 360 s
    download (`yt-dlp`)   max 494.3 s x 3                     -> 1500 s
    whole-file scan       1.0 x source seconds, never below 120 s
                          (an absolute number here kills honest work: 1262 s on
                          a 2h14m source was real work, not a hang)

A caller that names no class gets `SILENCE_CEILING_S`, so that the rule of the
CF-0077..CF-0135 series - not one child call without a ceiling - holds by
default instead of by review.

The outcome code and the statistics
-----------------------------------
A killed operation is not a silent `None`: the child event goes out with
`status: failed`, `rc: "<step-or-tool>_timeout"` (`index_timeout` for the
incident that started this) and a `watchdog` block naming the source, the
silence and the ceiling. `detect()` reads those back out of a finished run and
`render()` puts them in `RUN_SUMMARY.md` under their own heading. By the rule
of CF-0319 a kill is an **авария**, not a funnel loss: it is always a task for
the post-run triage, never a number in the funnel.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import runlog  # noqa: E402

__all__ = ["SILENCE_CEILING_S", "SHOT_CALL_CEILING_S", "DOWNLOAD_CEILING_S",
           "SCAN_MIN_CEILING_S", "SCAN_RATIO", "POLL_S", "RC_TIMEOUT",
           "WATCHDOG_KEY", "CLASSES", "ceiling_for", "scan_ceiling", "outcome_code",
           "is_kill", "Liveness", "detect", "headline", "render", "main"]

# --- the ceilings (arithmetic in the module docstring) ---------------------
SILENCE_CEILING_S = 1860.0      # one operation: 1300 s worst honest silence x 1.4, rounded up
SHOT_CALL_CEILING_S = 360.0     # one call bounded by one shot: 111.3 s x 3
DOWNLOAD_CEILING_S = 1500.0     # yt-dlp: 494.3 s x 3
SCAN_MIN_CEILING_S = 120.0      # a whole-file scan never gets less than this
SCAN_RATIO = 1.0                # ... and otherwise 1.0 x the source's own seconds

CLASSES = {                     # what a caller may name instead of a number
    "operation": SILENCE_CEILING_S,
    "shot": SHOT_CALL_CEILING_S,
    "download": DOWNLOAD_CEILING_S,
    "scan": None,               # needs the source length - use scan_ceiling()
}

POLL_S = 5.0                    # how often the silence is re-read
RC_TIMEOUT = 124                # the return code timeout(1) uses, for the caller
WATCHDOG_KEY = "watchdog"       # the event key carrying the kill
CODE_SUFFIX = "_timeout"


def ceiling_for(spec=None, *, step=None, tool=None, source_seconds=None):
    """Seconds of silence this call is allowed. `spec` is a number, a class
    name from CLASSES, or None for the default operation ceiling."""
    if isinstance(spec, (int, float)) and not isinstance(spec, bool):
        return float(spec)
    if isinstance(spec, str):
        if spec == "scan":
            return scan_ceiling(source_seconds)
        if spec in CLASSES and CLASSES[spec] is not None:
            return float(CLASSES[spec])
        raise ValueError(f"unknown watchdog class {spec!r}; known: {sorted(CLASSES)}")
    return SILENCE_CEILING_S


def scan_ceiling(source_seconds=None):
    """A pass over the whole file: 1.0 x its length, never below 120 s."""
    try:
        s = float(source_seconds or 0.0)
    except (TypeError, ValueError):
        s = 0.0
    return max(SCAN_MIN_CEILING_S, SCAN_RATIO * s)


def outcome_code(step=None, tool=None):
    """`index_timeout`, `fetch_timeout`, `yt-dlp_timeout` - the operation that
    was taken down, plus the suffix. Never a bare "timeout": the post-run triage
    is supposed to be able to tell which operation the run lost."""
    name = (step or tool or "operation")
    name = str(name).strip().replace(" ", "-") or "operation"
    return f"{name}{CODE_SUFFIX}"


def is_kill(event):
    """True for an event this module wrote a kill into."""
    return bool(isinstance(event, dict) and event.get(WATCHDOG_KEY))


# --------------------------------------------------------------------------
# liveness: has the operation's own subtree written anything since the last look
# --------------------------------------------------------------------------

class Liveness:
    """Signs of life of one launched process, read from RUN_EVENTS.jsonl.

    An event counts as the operation's own when it was written by the launched
    process (`pid`) or hangs under an event that was - so a grandchild binary
    counts too. Events of other stages running beside it do not: a watchdog
    that took the whole file's growth for life would never fire in a batch that
    has anything else going on.

    Samples are not read at all - see the module docstring (CF-0339).
    """

    LIVE_KINDS = (runlog.KIND_SCRIPT, runlog.KIND_CHILD)

    def __init__(self, batch_dir, pid=None):
        self.path = None
        self.offset = 0
        self.pids = {int(pid)} if pid else set()
        self.ids = set()
        try:
            if batch_dir:
                # CF-0251: a closed batch's activity goes beside its journal
                self.path = (runlog.write_path(batch_dir, runlog.KIND_SCRIPT)
                             or Path(batch_dir) / runlog.EVENTS_FILE)
                self.offset = self.path.stat().st_size if self.path.exists() else 0
        except OSError:
            self.path = None

    def poll(self):
        """True when the operation wrote at least one event since the last poll."""
        if self.path is None:
            return False
        try:
            size = self.path.stat().st_size
        except OSError:
            return False
        if size <= self.offset:
            if size < self.offset:                    # rotated or rewritten
                self.offset = size
            return False
        alive = False
        try:
            with open(self.path, "rb") as fh:
                fh.seek(self.offset)
                chunk = fh.read(size - self.offset)
                self.offset = size
        except OSError:
            return False
        tail = chunk.decode("utf-8", errors="replace")
        if not tail.endswith("\n"):                   # a half-written line: re-read it next time
            cut = tail.rfind("\n")
            if cut < 0:
                self.offset -= len(chunk)
                return False
            self.offset -= len(tail[cut + 1:].encode("utf-8"))
            tail = tail[:cut + 1]
        for line in tail.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if e.get("kind") not in self.LIVE_KINDS:
                continue
            own = (e.get("pid") in self.pids) or (e.get("parent") in self.ids)
            if own:
                alive = True
                if e.get("id"):
                    self.ids.add(e["id"])
                if e.get("pid"):
                    self.pids.add(e["pid"])
        return alive


def wait(proc, ceiling_s, liveness=None, poll_s=None, now=time.monotonic, sleep=None):
    """Wait for `proc` while it shows signs of life. Returns (returncode, silent_s):
    the return code, or None when the ceiling was reached and the caller has to
    take the process down. `silent_s` is how long it had been quiet by then.

    Between two reads of the silence the wait blocks on the process itself
    (`proc.wait(timeout=...)`), so an exit is seen the moment it happens, not on
    the next read - a 0.2 s ffprobe used to cost a whole POLL_S (CF-0395).
    The silence is still re-read once per `poll_s` (module POLL_S by default,
    read at call time). A test passes `sleep` to drive the loop by hand; the
    exit is then seen on the next read, as before."""
    if poll_s is None:
        poll_s = POLL_S
    t_life = now()
    while True:
        rc = proc.poll()
        if rc is not None:
            return rc, now() - t_life
        if liveness is not None and liveness.poll():
            t_life = now()
        silent = now() - t_life
        if silent >= ceiling_s:
            return None, silent
        pause = min(poll_s, max(0.01, ceiling_s - silent))
        if sleep is not None:
            sleep(pause)
            continue
        try:
            proc.wait(timeout=pause)
        except subprocess.TimeoutExpired:
            pass


# --------------------------------------------------------------------------
# reading the kills back out of a finished run
# --------------------------------------------------------------------------

def detect(batch_dir=None, events=None):
    """Every operation the watchdog took down in this run, in time order."""
    evs = events if events is not None else runlog.read_events(batch_dir)
    out = []
    for e in evs:
        w = e.get(WATCHDOG_KEY) if isinstance(e, dict) else None
        if not w:
            continue
        out.append({"ts": e.get("ts"), "stage": e.get("stage"), "step": e.get("step"),
                    "video": e.get("video") or w.get("source"),
                    "tool": e.get("tool"), "code": w.get("code") or e.get("rc"),
                    "silent_s": w.get("silent_s"), "ceiling_s": w.get("ceiling_s"),
                    "ran_s": e.get("duration_s"), "source": w.get("source"),
                    "attempt_spent": False})
    out.sort(key=lambda r: r["ts"] or "")
    return out


def headline(rows):
    """The one line near the top of the summary. None unless something was killed."""
    if not rows:
        return None
    codes = sorted({r["code"] for r in rows if r["code"]})
    return (f"**watchdog: {len(rows)} operation(s) taken down** "
            f"({', '.join(f'`{c}`' for c in codes)}) - CF-0316; by the rule of CF-0319 "
            f"every one of them is a task for the post-run triage, not a funnel number")


def render(rows):
    """The block of the summary. [] unless something was killed."""
    if not rows:
        return []
    L = ["", "## Operations the watchdog took down (CF-0316)", "",
         f"{len(rows)} operation(s) went quiet past their ceiling and were taken down. The run "
         "was **not** dropped and no attempt of the topic was spent: the stage lost one source "
         "and went on to the next. Each line is an авария by the rule of CF-0319 - always a "
         "task, never a funnel loss.", "",
         "| when | stage / step | source | code | silent | ceiling | ran |",
         "|---|---|---|---|---|---|---|"]
    for r in rows:
        L.append(f"| {r['ts'] or '?'} | {r['stage'] or '?'} / {r['step'] or r['tool'] or '?'} "
                 f"| {r['source'] or r['video'] or '-'} | `{r['code']}` "
                 f"| {_secs(r['silent_s'])} | {_secs(r['ceiling_s'])} | {_secs(r['ran_s'])} |")
    L.append("")
    return L


def _secs(v):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return "?"
    return f"{int(round(v))} s" if v < 600 else f"{int(v // 3600)}h{int(v % 3600) // 60:02d}m"


def main(argv=None):
    """`runlog watchdog [--batch DIR] [--json]` - what this run lost to the watchdog."""
    argv = list(sys.argv[1:] if argv is None else argv)
    batch = None
    as_json = "--json" in argv
    if "--batch" in argv:
        batch = argv[argv.index("--batch") + 1]
    rows = detect(batch or os.environ.get(runlog.BATCH_ENV))
    if as_json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
    else:
        for r in rows:
            print(f"{r['ts']} {r['stage']}/{r['step'] or r['tool']} {r['source'] or '-'} "
                  f"{r['code']} silent={_secs(r['silent_s'])} ceiling={_secs(r['ceiling_s'])}")
        if not rows:
            print("no operation was taken down by the watchdog")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
