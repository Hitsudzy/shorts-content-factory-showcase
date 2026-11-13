#!/usr/bin/env python3
"""CF-0112: what a source costs in the Footage Indexer, split into the parts
that make up the cost - and read off frozen runs, not off a stopwatch.

The defect this answers, from the re-estimate of 2026-09-22. The stage eats
75-86 % of a run's live time and we promised a ceiling of 10 x N topics
(CF-0321) without knowing what one topic costs. The only number anyone ever
quoted was a division: 24 sources in 4h15m, so "10.6 minutes a source". That
number is a *wall* divided by a count, and the stage runs several workers at
once, so it is not the price of a source and it cannot be split into network,
frames, CLIP and Vision by dividing it further.

**This module is a reader, not a second accounting layer.** Everything it says
comes out of `pipeline/<channel>/<batch>/RUN_EVENTS.jsonl`, the file the
run-accounting of CF-0107..CF-0110 already writes: `kind="child"` events carry
`tool` (`yt-dlp`, `ffmpeg`, `clip`, `vision`, `ffprobe`), `step`, `video`,
`pid`, a start and a done/failed with `duration_s`. Same shape as
`shared/runlog/gate_price.py` and `no_waiting.py`: frozen artifacts in, numbers
out, nothing measured live and nothing written back.

**The arithmetic warning, and what this module does about it.** Summing
`duration_s` over the stage gives 5.18 h inside a 4.25 h wall on
`2026-09-22T1001Z` - 122 % - for the same reason the old `indexer_s` read
127 % and 286 %: concurrent workers. A sum of overlapping intervals is not a
share of anything. So every share here is computed over the **union** of
intervals (`union_s`), and a sum is only ever reported as `busy_s`, next to
the union, and never divided by the wall. Three quantities, kept apart:

* `busy_s`  - naive sum of durations. Work performed. Exceeds the wall.
* `union_s` - wall-clock seconds during which at least one such interval ran.
  This is the only number that may be divided by the wall.
* `solo_s`  - wall-clock seconds during which that tool ran and no other tool
  ran. What removing the tool entirely would give back; the rest of its
  `union_s` is hidden behind something else.

**Machine time against operator time.** Inside the stage wall, every instant is
one of three things, and the split is the input CF-0095 is waiting for:

* `child`  - a binary is running (yt-dlp / ffmpeg / clip / vision / ffprobe);
* `script` - one of this repo's scripts is running but no binary is: Python-side
  work (decoding, numpy, writing `shots.json`);
* `idle`   - neither. No process of the stage is doing anything. The LLM
  operator is deciding what to run next, or standing.

`idle` is measured, not guessed: it is the complement of the script and child
intervals inside the stage window. `idle_spans()` returns them longest first,
which is what makes an operator stall visible as one number rather than a feel.

**The watchdog threshold (CF-0316) is read off the tail, not chosen.** For each
tool, `quantiles()` gives the distribution of one call's duration over the runs
given, and `watchdog()` turns it into a ceiling: the rule is `max(observed) x
SAFETY`, rounded up to a round number, per tool - a ceiling below an observed
honest call would kill healthy work, and one far above the observed maximum
would never fire. The number is therefore a function of the measured runs and
moves when they move; it is not a constant somebody liked.

Usage:

    python3 scripts/indexer_cost.py                    # the three fresh runs
    python3 scripts/indexer_cost.py <batch-dir> ...    # named runs
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

STAGE = "footage-indexer"
EVENTS = "RUN_EVENTS.jsonl"

# CF-0316: how far above the slowest honest call a watchdog ceiling sits. A
# call is killed only when it is past anything the frozen runs have ever shown
# by this factor, so the ceiling never fires on work that merely ran long.
SAFETY = 3.0

# The runs the re-estimate of 2026-09-22 named as the material. Frozen; the
# 2026-09-15T1034Z original and pipeline/rebuilds/ are deliberately not here.
DEFAULT_RUNS = (
    "pipeline/example-film/2026-09-22T1001Z",
    "pipeline/example-film/2026-09-21T1541Z",
    "pipeline/example-film/2026-09-21T0358Z",
)


# The operation classes the stage actually runs, in the order they cost. A
# class is what a watchdog would time (CF-0316), which is why it is finer than
# the tool: one `ffmpeg` covers a 0.4 s pad and a 21-minute whole-file scan.
# `scope`: "shot" - work bounded by one shot, independent of source length;
#          "source" - a pass over the whole file, growing with its length.
OPS = (
    ("ffmpeg", "shot-full-frame", "shot", "-vf crop=", None),
    # CF-0331: the card probe's frame grab became one call per shot instead of
    # one per sample. With bars to crop it still reads `-vf crop=` above; with
    # none, the select grid is the only thing left to recognise it by (before
    # CF-0331 that case fell through to ffmpeg-other, so old runs are read
    # exactly as they were). probe_shot_span()'s own select reads
    # `select='if(isnan(` and `select='gte(scene`, neither of which is this.
    ("ffmpeg", "shot-full-frame", "shot", "select='gte(t,", None),
    ("ffmpeg", "shot-cropdetect", "shot", "cropdetect=", None),
    ("ffmpeg", "shot-thumbs", "shot", "-vf fps=1/", None),
    ("ffmpeg", "shot-split-probe", "shot", "select='gte(scene", None),
    ("ffmpeg", "shot-clip-frame", "shot", "-vf scale=336", None),
    ("ffmpeg", "shot-contact-cell", "shot", "force_original_aspect_ratio", None),
    ("ffmpeg", "source-scenedetect", "source", "select='gt(scene", None),
    ("ffmpeg", "source-fingerprint", "source", "scale=9:8", None),
    ("ffmpeg", "source-contact-tile", "source", "tile=", None),
)


def op_of(tool, argv, params):
    """The operation class of one child call - finer than the tool, which is
    the granularity a watchdog needs."""
    if not argv:
        return f"{tool}:?"
    if tool == "ffmpeg" and not argv[0].startswith("/"):
        return "wrapper:" + " ".join(argv[:2])
    if tool == "vision":
        probe = params.get("probe") or (argv[1] if len(argv) > 1 else "?")
        return f"vision-{probe}"
    if tool == "clip":
        return "clip-" + (argv[1] if len(argv) > 1 else "?")
    joined = " ".join(argv)
    if tool == "ffmpeg":
        for _, name, _, needle, _ in OPS:
            if needle in joined:
                return name
        return "ffmpeg-other"
    return tool


def op_scope(name):
    for _, n, scope, _, _ in OPS:
        if n == name:
            return scope
    return "shot" if name.startswith(("vision-", "clip-")) else "source"


def factory_root():
    """The factory root - the nearest ancestor holding shared/runlog/."""
    import os

    env = os.environ.get("FACTORY_ROOT")
    if env:
        return Path(env).expanduser().resolve()
    for p in Path(__file__).resolve().parents:
        if (p / "shared" / "runlog" / "runlog.py").is_file():
            return p
    raise RuntimeError("factory root not found: set FACTORY_ROOT")


def ts(raw):
    """An event timestamp as epoch seconds."""
    return datetime.fromisoformat(raw.replace("Z", "+00:00")).replace(
        tzinfo=timezone.utc
    ).timestamp()


# ---------------------------------------------------------------- intervals

def union_s(spans):
    """Wall-clock seconds covered by at least one of the spans. The only
    quantity in this module that may be divided by a wall."""
    if not spans:
        return 0.0
    total, cur_a, cur_b = 0.0, None, None
    for a, b in sorted(spans):
        if cur_b is None or a > cur_b:
            if cur_b is not None:
                total += cur_b - cur_a
            cur_a, cur_b = a, b
        elif b > cur_b:
            cur_b = b
    return total + (cur_b - cur_a)


def subtract(spans, minus):
    """The spans with every instant covered by `minus` removed."""
    cuts = merge(minus)
    out = []
    for a, b in merge(spans):
        for ca, cb in cuts:
            if cb <= a or ca >= b:
                continue
            if ca > a:
                out.append((a, min(ca, b)))
            a = max(a, cb)
            if a >= b:
                break
        if a < b:
            out.append((a, b))
    return [s for s in out if s[1] > s[0]]


def merge(spans):
    """Overlapping spans merged into disjoint ones, in order."""
    out = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            if b > out[-1][1]:
                out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def intersect(spans, window):
    """The spans clipped to a window."""
    wa, wb = window
    out = [(max(a, wa), min(b, wb)) for a, b in spans]
    return [s for s in out if s[1] > s[0]]


EPS = 1e-3


def mark_leaves(calls):
    """Mark every call `leaf` unless a shorter call of the same process ran
    wholly inside it. Only leaves may be summed; see `Run._calls`.

    CF-0160: a journal written after the root recorded nesting carries `depth`
    on every child and points a nested child's `parent` at its wrapper; there
    the record is read as is (a call is a leaf when no call names it as
    parent). Older journals have no `depth` and keep the geometry below."""
    if calls and all(c.get("depth") is not None and c.get("id") for c in calls):
        held = {}
        for c in calls:
            if c["depth"] >= 1:
                held[c.get("parent")] = held.get(c.get("parent"), 0) + 1
        for c in calls:
            c["inner"] = held.get(c["id"], 0)
            c["leaf"] = c["inner"] == 0
        return calls
    order = sorted(range(len(calls)), key=lambda i: (calls[i]["span"][0], -calls[i]["span"][1]))
    for c in calls:
        c["leaf"] = True
        c["inner"] = 0
    for oi, i in enumerate(order):
        a, b = calls[i]["span"]
        for j in order[oi + 1:]:
            qa, qb = calls[j]["span"]
            if qa > b:
                break
            if (
                calls[j]["pid"] == calls[i]["pid"]
                and qa >= a - EPS
                and qb <= b + EPS
                and (qb - qa) < (b - a) - EPS
            ):
                calls[i]["leaf"] = False
                calls[i]["inner"] += 1
    return calls


def max_concurrency(spans):
    """The largest number of the spans running at the same instant."""
    edges = sorted([(a, 1) for a, _ in spans] + [(b, -1) for _, b in spans])
    cur = best = 0
    for _, d in edges:
        cur += d
        best = max(best, cur)
    return best


# ------------------------------------------------------------------- a run

class Run:
    """One frozen batch, read for what the Footage Indexer did in it."""

    def __init__(self, batch_dir):
        self.dir = Path(batch_dir)
        self.name = self.dir.name
        self.channel = self.dir.parent.name
        events = [json.loads(l) for l in (self.dir / EVENTS).open()]
        self.events = [e for e in events if e.get("stage") == STAGE]
        self.batch_span = self._batch_span(events)
        self.windows = self._windows()
        self.wall_s = sum(b - a for a, b in self.windows)
        self.calls = self._calls()
        self.scripts = self._scripts()

    def _batch_span(self, events):
        a = b = None
        for e in events:
            if e.get("status") == "batch-start":
                a = ts(e["ts"])
            if e.get("status") == "batch-done":
                b = ts(e["ts"])
        return (a, b) if a and b else None

    def _windows(self):
        """The stage's own windows: stage-start .. stage-done. A stage can be
        entered more than once in a run, so this is a list."""
        out, open_at = [], None
        for e in self.events:
            if e["kind"] != "marker":
                continue
            if e["status"] == "stage-start":
                open_at = ts(e["ts"])
            elif e["status"] == "stage-done" and open_at is not None:
                out.append((open_at, ts(e["ts"])))
                open_at = None
        return out

    def _pair(self, kind):
        """start/done events of one kind paired by their shared id."""
        opened, out = {}, []
        for e in self.events:
            if e["kind"] != kind:
                continue
            if e["status"] == "start":
                opened[e["id"]] = e
            elif e["status"] in ("done", "failed"):
                s = opened.pop(e["id"], None)
                if s is None:
                    continue
                out.append((ts(s["ts"]), ts(e["ts"]), e))
        return out

    def _calls(self):
        """Every `child` event, marked `leaf` or not.

        **The one thing that has to be got right here.** A `child` event is not
        always a process: `runlog.child(...)` also wraps *groups*, and the
        groups nest. On `2026-09-22T1001Z` the 469 `vision card-text` events
        (43.6 min) each hold their own `vision text_regions` events (42.1 min
        of the 43.6); `vision captions` (26.0 min) holds 469 `ffmpeg fps=1/N`
        (13.3) and 3738 `vision text_boxes` (12.7), which is all of it; `vision
        usability` holds `find_roi` and more `text_regions`; `ffmpeg
        full-frames` and `ffmpeg cropdetect` are bare labels over the real
        `cropdetect=` calls. Summing every event therefore counts the same
        seconds up to three times - that, and not only the two workers, is why
        the naive sum reads 122 % of the wall.

        So containment is computed here, geometrically (the log has no field
        for it: `parent` points at the script, not at the enclosing call), and
        only **leaves** are summed. A leaf is an event with no shorter event of
        the same pid inside its span. The leaf sum comes to 206 of the 215
        union minutes on that run; the rest is a group's own overhead.
        (CF-0160: journals written after the root recorded nesting carry
        `depth` and the wrapper's id as `parent`; `mark_leaves` reads those
        as recorded and keeps the geometry for the frozen runs.)

        In the runs measured here one leaf is still a group: `ffmpeg -ss <t>
        ... -frames:v 1` is a single event over 8-20 unlogged `ffmpeg` runs,
        one per sampled frame, and the `<t>` in its argv is the placeholder
        that gives it away. It was the stage's single most expensive item, so
        the report says so rather than pretending it is one process.

        CF-0331 closed that: the card probe's frames now come from one real
        ffmpeg call per shot, so in runs made after it a `shot-full-frame`
        leaf is one process and the `<t>` placeholder is gone. The reading of
        the frozen runs above is unchanged - the note stays because the report
        still prints it for them."""
        out = []
        for a, b, e in self._pair("child"):
            argv = e.get("argv") or []
            out.append(
                {
                    "span": (a, b),
                    "dur": b - a,
                    "tool": e.get("tool") or "?",
                    "step": e.get("step"),
                    "video": e.get("video"),
                    "status": e["status"],
                    "probe": (e.get("params") or {}).get("probe"),
                    "argv": argv,
                    "pid": e.get("pid"),
                    "id": e.get("id"),
                    "parent": e.get("parent"),
                    "depth": e.get("depth"),
                    "op": op_of(e.get("tool"), argv, (e.get("params") or {})),
                }
            )
        return mark_leaves(out)

    def _scripts(self):
        out = []
        for a, b, e in self._pair("script"):
            out.append(
                {
                    "span": (a, b),
                    "dur": b - a,
                    "name": e.get("name"),
                    "step": e.get("step"),
                    "video": e.get("video"),
                    "status": e["status"],
                }
            )
        return out

    # -------------------------------------------------------------- reading

    def real(self):
        """The leaves - the only calls that may be summed."""
        return [c for c in self.calls if c["leaf"]]

    def groups(self):
        """The calls that hold other calls: their seconds are their children's,
        counted once in `real()` and never added here."""
        return [c for c in self.calls if not c["leaf"]]

    def tools(self):
        """Per tool: calls, busy sum, union coverage, solo coverage."""
        calls = self.real()
        names = sorted({c["tool"] for c in calls})
        spans = {t: [c["span"] for c in calls if c["tool"] == t] for t in names}
        out = {}
        for t in names:
            others = [s for u in names if u != t for s in spans[u]]
            mine = intersect(spans[t], self.windows[0]) if self.windows else spans[t]
            out[t] = {
                "n": len(spans[t]),
                "failed": sum(
                    1 for c in calls if c["tool"] == t and c["status"] == "failed"
                ),
                "busy_s": sum(c["dur"] for c in calls if c["tool"] == t),
                "union_s": union_s(mine),
                "solo_s": sum(b - a for a, b in subtract(mine, others)),
                "max_par": max_concurrency(spans[t]),
            }
        return out

    def occupancy(self):
        """The stage wall split three ways: a binary runs / only a script runs /
        nothing of the stage runs."""
        child = [c["span"] for c in self.calls]
        script = [s["span"] for s in self.scripts]
        win = self.windows
        busy = union_s([s for w in win for s in intersect(child, w)])
        scripted = union_s([s for w in win for s in intersect(script, w)])
        script_only = union_s(
            [s for w in win for s in intersect(subtract(script, child), w)]
        )
        return {
            "wall_s": self.wall_s,
            "child_s": busy,
            "script_only_s": script_only,
            "idle_s": self.wall_s - busy - script_only,
            "script_union_s": scripted,
            "child_busy_sum_s": sum(c["dur"] for c in self.calls),
            "max_par": max_concurrency(child),
        }

    def idle_spans(self):
        """Instants inside the stage when no script and no binary of the stage
        was running, longest first. This is the operator's own time."""
        work = [c["span"] for c in self.calls] + [s["span"] for s in self.scripts]
        out = []
        for w in self.windows:
            out += subtract([w], work)
        return sorted(out, key=lambda s: s[1] - s[0], reverse=True)

    def ops(self):
        """Per operation class: calls, busy sum, and the distribution of one
        call. This is the table a watchdog threshold is read off."""
        out = {}
        for c in self.real():
            row = out.setdefault(
                c["op"], {"n": 0, "busy_s": 0.0, "dur": [], "scope": op_scope(c["op"])}
            )
            row["n"] += 1
            row["busy_s"] += c["dur"]
            row["dur"].append(c["dur"])
        for row in out.values():
            row.update(quantiles(row["dur"]))
        return out

    def shots(self):
        """Shots processed per source, counted from the events themselves -
        one `shot-full-frame` call per shot - rather than from `shots.json`,
        which later runs rewrite."""
        out = {}
        for c in self.real():
            if c["op"] == "shot-full-frame" and c["video"]:
                out[c["video"]] = out.get(c["video"], 0) + 1
        return out

    def sources(self):
        """Per source: the union of its own calls, split by tool. A source's
        cost is a union, never a sum - Vision runs several calls at once on the
        same source."""
        calls = self.real()
        shots = self.shots()
        vids = sorted({c["video"] for c in calls if c["video"]})
        out = {}
        for v in vids:
            mine = [c for c in calls if c["video"] == v]
            spans = [c["span"] for c in mine]
            row = {
                "union_s": union_s(spans),
                "busy_s": sum(c["dur"] for c in mine),
                "span_s": max(b for _, b in spans) - min(a for a, _ in spans),
                "n": len(mine),
                "shots": shots.get(v, 0),
                "tools": {},
            }
            for t in sorted({c["tool"] for c in mine}):
                ts_ = [c["span"] for c in mine if c["tool"] == t]
                row["tools"][t] = {
                    "n": len(ts_),
                    "union_s": union_s(ts_),
                    "busy_s": sum(c["dur"] for c in mine if c["tool"] == t),
                }
            out[v] = row
        return out

    def fetches(self):
        """Fetches, which are the stage's only network: one per yt-dlp call."""
        return [c for c in self.calls if c["tool"] == "yt-dlp"]

    def operator_windows(self):
        """LLM usage records of this stage, as the accounting wrote them.

        Deduplicated: `usage` is recomputed and appended more than once in a
        run, so the same (agent, first, last, calls) record appears twice in
        `RUN_EVENTS.jsonl` and a naive sum doubles every LLM minute."""
        out, seen = [], set()
        for e in self.events:
            if e["kind"] != "usage":
                continue
            key = (e.get("agent"), e.get("first"), e.get("last"), e.get("calls"))
            if key in seen:
                continue
            seen.add(key)
            out.append(
                {
                    "role": e.get("role"),
                    "agent": e.get("agent"),
                    "model": e.get("model"),
                    "calls": e.get("calls"),
                    "minutes": e.get("minutes") or 0.0,
                    "first": e.get("first"),
                    "last": e.get("last"),
                }
            )
        return out

    def llm(self):
        """The LLM side of the stage, split the way CF-0095 needs it: the one
        stage operator against the per-source description subagents.

        `role == "operator"` records are the run's own top-level operator and
        are left out - they are a second view of the same minutes, not extra
        work."""
        stage, describe = [], []
        for w in self.operator_windows():
            if w["role"] != "subagent":
                continue
            name = w["agent"] or ""
            (stage if "perator" in name or "\u043f\u0435\u0440\u0430\u0442\u043e\u0440" in name
             else describe).append(w)
        return {
            "stage_operator_min": sum(w["minutes"] for w in stage),
            "stage_operator_calls": sum(w["calls"] or 0 for w in stage),
            "describe_min": sum(w["minutes"] for w in describe),
            "describe_calls": sum(w["calls"] or 0 for w in describe),
            "describe_agents": len(describe),
        }


# ------------------------------------------------------------- distribution

def quantiles(values, points=(0.5, 0.9, 0.95, 0.99, 1.0)):
    """Order statistics of a sample, nearest-rank."""
    if not values:
        return {p: None for p in points}
    v = sorted(values)
    out = {}
    for p in points:
        k = max(0, min(len(v) - 1, int(round(p * len(v))) - 1))
        out[p] = v[k]
    return out


# CF-0316: the one operation whose honest cost grows without bound with the
# source, so an absolute ceiling on it is either useless or lethal. Everything
# else in the stage is bounded by one shot or by `-t`.
RATE_OPS = ("source-scenedetect",)

# The stage's own scripts are the second level: `index_footage.py` is exactly
# "one source being indexed", which is the wording of CF-0316. `ingest_batch.py`
# is the stage itself and is not an operation, so it gets no ceiling here.
NOT_AN_OPERATION = ("ingest_batch.py",)


def script_watchdog(runs, safety=SAFETY):
    """Ceilings for the second level: one script run - one source fetched, one
    source indexed, one sieve pass."""
    per = {}
    for r in runs:
        for sc in r.scripts:
            if sc["name"] in NOT_AN_OPERATION:
                continue
            per.setdefault((sc["name"], sc["step"]), []).append(sc["dur"])
    out = {}
    for key, vals in sorted(per.items(), key=lambda kv: -max(kv[1])):
        q = quantiles(vals)
        out[key] = {
            "n": len(vals),
            "p50": q[0.5],
            "p90": q[0.9],
            "max": q[1.0],
            "ceiling_s": _round_up(q[1.0] * safety),
        }
    return out


def blanket(runs, safety=SAFETY):
    """One ceiling for every *bounded* binary call - the number the common
    child-launch layer can carry without knowing which call it is running.

    Read off the slowest bounded call in the frozen runs (a `shot-split-probe`
    at 111.3 s over 31808 calls), times `safety`. The unbounded ones -
    `RATE_OPS` and the download - are excluded by construction and get their
    own rule, because folding them in would raise this to 3900 s and a 3900 s
    ceiling on a 0.4 s call is not a watchdog."""
    vals = [
        c["dur"]
        for r in runs
        for c in r.real()
        if c["op"] not in RATE_OPS and c["tool"] != "yt-dlp"
    ]
    return {"n": len(vals), "max": max(vals), "ceiling_s": _round_up(max(vals) * safety)}


def watchdog(runs, safety=SAFETY):
    """CF-0316: how long an operation may run before it is killed - two levels,
    because the task names two ("a call of a binary", "a source indexed longer
    than the threshold").

    Derived, not chosen. The ceiling is the slowest such operation the frozen
    runs hold, times `safety`, rounded up to a readable step. Below the
    observed maximum a ceiling kills honest work; far above it, it never fires.

    The classes are `op_of`, not the tool: per tool, `ffmpeg` mixes a 0.4 s pad
    with a whole-file scan that honestly ran 21 minutes, and one ceiling over
    that mixture is 3900 s - useless as a watchdog, because the 0.4 s call
    would be allowed to hang for over an hour. Per class the same data gives
    60 s for the pad and 3900 s for the scan.

    `source` is the second level: the span from a source's first call to its
    last, which is what "a source indexed longer than the threshold" means."""
    per, spans = {}, []
    for r in runs:
        for c in r.real():
            per.setdefault(c["op"], []).append(c["dur"])
        for v, row in r.sources().items():
            if row["shots"]:  # a source that was actually indexed
                spans.append(row["span_s"])
    out = {}
    for op, vals in sorted(per.items(), key=lambda kv: -max(kv[1])):
        q = quantiles(vals)
        out[op] = {
            "level": "call",
            "scope": op_scope(op),
            "n": len(vals),
            "p50": q[0.5],
            "p90": q[0.9],
            "p99": q[0.99],
            "max": q[1.0],
            "ceiling_s": _round_up(q[1.0] * safety),
        }
    q = quantiles(spans)
    out["SOURCE (whole index of one source)"] = {
        "level": "source",
        "scope": "source",
        "n": len(spans),
        "p50": q[0.5],
        "p90": q[0.9],
        "p99": q[0.99],
        "max": q[1.0],
        "ceiling_s": _round_up(q[1.0] * safety),
    }
    return out


def price(runs):
    """What one source costs, and what N of them would cost.

    The unit is **a shot, not a source and not a minute of source**. Measured
    over the three frozen runs: cost against source length scatters 1.6x-31x
    and says nothing, because every source is cut to at most `max_shots`
    shots; cost against shot count is steady. So:

        machine seconds for a source ~ shots x PER_SHOT + per-source passes

    and `shots` is bounded by the cap, which is what makes a ceiling on topics
    computable at all (CF-0321)."""
    wall = sum(r.wall_s for r in runs)
    machine = sum(r.occupancy()["child_s"] for r in runs)
    idle = sum(r.occupancy()["idle_s"] for r in runs)
    shots = sum(sum(d["shots"] for d in r.sources().values()) for r in runs)
    indexed = sum(
        sum(1 for d in r.sources().values() if d["shots"]) for r in runs
    )
    touched = sum(len(r.sources()) for r in runs)
    return {
        "wall_s": wall,
        "machine_s": machine,
        "idle_s": idle,
        "shots": shots,
        "indexed": indexed,
        "touched": touched,
        "per_shot_s": machine / shots,
        "shots_per_source": shots / indexed,
        "machine_per_source_s": machine / indexed,
        "wall_per_source_s": wall / touched,
        "idle_share": idle / wall,
    }


def forecast(p, sources, shots_per_source=None):
    """Wall hours for `sources` sources at the measured rates. `None` uses the
    measured average shots per source; pass the cap to price the worst case."""
    n = shots_per_source or p["shots_per_source"]
    machine = sources * n * p["per_shot_s"]
    return {
        "machine_s": machine,
        "wall_s": machine / (1 - p["idle_share"]),
        "shots_per_source": n,
    }


def _round_up(x):
    """Up to the next readable step: 10 s below a minute, 30 s below ten
    minutes, 60 s below an hour, 300 s above."""
    for limit, step in ((60, 10), (600, 30), (3600, 60)):
        if x <= limit:
            return int(step * -(-x // step))
    return int(300 * -(-x // 300))


# -------------------------------------------------------------------- main

def _hm(s):
    s = int(s)
    return f"{s // 3600}h{s % 3600 // 60:02d}m{s % 60:02d}s"


def report(runs, out=sys.stdout):
    w = out.write
    for r in runs:
        occ = r.occupancy()
        w(f"\n=== {r.channel}/{r.name}  stage wall {_hm(occ['wall_s'])}\n")
        w(
            f"  occupancy: child {_hm(occ['child_s'])} "
            f"({occ['child_s'] / occ['wall_s'] * 100:.1f} %), "
            f"script-only {_hm(occ['script_only_s'])} "
            f"({occ['script_only_s'] / occ['wall_s'] * 100:.1f} %), "
            f"idle {_hm(occ['idle_s'])} "
            f"({occ['idle_s'] / occ['wall_s'] * 100:.1f} %); "
            f"sum of children {_hm(occ['child_busy_sum_s'])} "
            f"({occ['child_busy_sum_s'] / occ['wall_s'] * 100:.0f} % of wall - "
            f"a sum, not a share), max {occ['max_par']} at once\n"
        )
        w(f"  {'tool':8s} {'n':>6s} {'busy':>10s} {'union':>10s} {'%wall':>7s} "
          f"{'solo':>10s} {'par':>4s}\n")
        for t, d in sorted(
            r.tools().items(), key=lambda kv: -kv[1]["union_s"]
        ):
            w(
                f"  {t:8s} {d['n']:6d} {_hm(d['busy_s']):>10s} "
                f"{_hm(d['union_s']):>10s} "
                f"{d['union_s'] / occ['wall_s'] * 100:6.1f}% "
                f"{_hm(d['solo_s']):>10s} {d['max_par']:4d}\n"
            )
        w(f"  {'operation':20s} {'scope':7s} {'n':>6s} {'busy':>9s} "
          f"{'mean':>7s} {'p50':>7s} {'p99':>8s} {'max':>9s}\n")
        for op, d in sorted(r.ops().items(), key=lambda kv: -kv[1]["busy_s"]):
            w(
                f"  {op:20s} {d['scope']:7s} {d['n']:6d} "
                f"{d['busy_s'] / 60:8.1f}m {d['busy_s'] / d['n']:6.2f}s "
                f"{d[0.5]:6.2f}s {d[0.99]:7.2f}s {d[1.0]:8.1f}s\n"
            )
        grp = r.groups()
        if grp:
            top = sorted(
                {c["op"] for c in grp},
                key=lambda o: -sum(c["dur"] for c in grp if c["op"] == o),
            )[:5]
            w(
                f"  (+ {len(grp)} group events over these, "
                f"{sum(c['dur'] for c in grp) / 60:.1f}m of already-counted "
                f"seconds, not added: {', '.join(top)})\n"
            )
        src = r.sources()
        if src:
            indexed = {v: d for v, d in src.items() if d["shots"]}
            per = sorted(v["union_s"] for v in indexed.values())
            shots = sum(v["shots"] for v in indexed.values())
            w(
                f"  sources: {len(src)} touched, {len(indexed)} indexed, "
                f"{shots} shots; machine time per indexed source "
                f"median {_hm(per[len(per) // 2])}, max {_hm(per[-1])}, "
                f"mean {_hm(sum(per) / len(per))}; "
                f"per shot {sum(per) / shots:.1f}s; "
                f"wall/source touched {_hm(occ['wall_s'] / len(src))}\n"
            )
        idle = r.idle_spans()
        if idle:
            top = [_hm(b - a) for a, b in idle[:3]]
            w(f"  idle spans: {len(idle)}, longest {', '.join(top)}\n")
        d = r.llm()
        w(
            f"  LLM inside the stage: stage operator "
            f"{d['stage_operator_min']:.0f} min / {d['stage_operator_calls']} calls, "
            f"{d['describe_agents']} shot-description subagents "
            f"{d['describe_min']:.0f} min / {d['describe_calls']} calls "
            f"(they overlap the machine work; the idle above is where they ran "
            f"alone)\n"
        )

    p = price(runs)
    w(
        f"\n=== the price of a source, over {len(runs)} runs\n"
        f"  wall {_hm(p['wall_s'])}, machine {_hm(p['machine_s'])} "
        f"({p['machine_s'] / p['wall_s'] * 100:.1f} %), "
        f"idle {_hm(p['idle_s'])} ({p['idle_share'] * 100:.1f} %)\n"
        f"  {p['touched']} sources touched, {p['indexed']} indexed, "
        f"{p['shots']} shots -> {p['shots_per_source']:.1f} shots a source\n"
        f"  machine per shot {p['per_shot_s']:.1f}s; "
        f"machine per indexed source {_hm(p['machine_per_source_s'])}; "
        f"wall per source touched {_hm(p['wall_per_source_s'])}\n"
    )
    for n in (20, 40, 60):
        avg = forecast(p, n)
        cap = forecast(p, n, 60)
        w(
            f"  {n:3d} sources: {avg['wall_s'] / 3600:5.1f} h wall at the "
            f"measured {p['shots_per_source']:.0f} shots a source, "
            f"{cap['wall_s'] / 3600:5.1f} h at the 60-shot cap\n"
        )

    b = blanket(runs)
    w(
        f"\n=== watchdog (CF-0316)\n"
        f"  level 1, one bounded binary call: slowest of {b['n']} was "
        f"{b['max']:.1f}s -> one ceiling of {b['ceiling_s']}s for all of them\n"
        f"  level 1, the unbounded ones: source-scenedetect scales with the "
        f"source (see the report), yt-dlp with the bytes\n"
        f"  level 2, one script run:\n"
    )
    for (name, step), d in script_watchdog(runs).items():
        w(
            f"    {name:20s} {str(step):14s} n={d['n']:4d} "
            f"p50={_hm(d['p50']):>9s} p90={_hm(d['p90']):>9s} "
            f"max={_hm(d['max']):>9s} -> ceiling {_hm(d['ceiling_s'])}\n"
        )
    w("\n  per operation class, for reference:\n")
    for op, d in watchdog(runs).items():
        w(
            f"  {op:38s} n={d['n']:6d} p50={d['p50']:7.2f}s "
            f"p99={d['p99']:9.2f}s max={d['max']:9.2f}s "
            f"-> ceiling {d['ceiling_s']:5d}s\n"
        )


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    root = factory_root()
    dirs = [Path(a) for a in argv] or [root / d for d in DEFAULT_RUNS]
    report([Run(d) for d in dirs])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
