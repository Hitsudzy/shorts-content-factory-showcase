#!/usr/bin/env python3
"""CF-0204: hold a batch run by the executor against the last batch run by hand.

    python3 scripts/compare_runs.py <manual batch dir> <executor batch dir> [--root DIR] [--json]

CF-0204 item 2: the first batch the executor runs (`shared/run_executor.py`,
CF-0203) is held against the last manual one - **the same stages, in the same
order, with the same output**. A difference is a defect of the move, not an
improvement. The topics, footage and videos of two batches never match, so
"the same output" means the same *kind* of output: the same contract files and
the same records of the run. Item 4 is read off the same two directories:
how much of each wall went on waiting for the operator (CF-0070, the
`## Where the wall went` table of `RUN_SUMMARY.md`, CF-0257).

What is compared:

* **stages** - the `stage-start` markers of `RUN_EVENTS.jsonl` in order. An
  attempt the executor closed with `stage-done --note "restarted (CF-0204)..."`
  is not a stage: it is a run that died and was started again. A stage only
  one side ran is a defect, unless the executor's `run-state.json` says the
  plan skipped it on its condition (`when: ...`). A conditional stage is
  then a property of that batch's material - the reserve loop, the thin-pool
  supplement - and is listed, not counted as a defect;
* **order** - the stages both sides ran, as a sequence (repeats counted, so the
  two compliance passes and a second Indexer call are kept apart);
* **output** - the numbered contract files (`01-*.json`, `01b-*.json`, ...),
  `RUN_SUMMARY.md`, `TRIAGE.md`, `MONITORS.txt`, and the counts that show the
  run's yield (scripts in `03`, videos in `05`, `qc.passed` among them, verdicts in
  `06`, `*.mp4` under `videos/`). A file only one side has is a defect, unless
  the stage that writes it was skipped on its condition; the counts are shown
  and not judged;
* **wall** - each part of `## Where the wall went` side by side, and the
  operator's share: waiting for a human + operator idle + unattributed (the
  orchestrator between stages).

Exit 0 - the same stages in the same order with the same files; 1 - a defect
(each one printed); 2 - a bad call (a directory without `RUN_EVENTS.jsonl`).
Read-only. Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT / "shared") not in sys.path:
    sys.path.insert(0, str(ROOT / "shared"))

EVENTS = "RUN_EVENTS.jsonl"
STATE = "run-state.json"
SUMMARY = "RUN_SUMMARY.md"
RESTARTED = "restarted (CF-0204)"
RECORDS = ("RUN_SUMMARY.md", "TRIAGE.md", "MONITORS.txt")
CONTRACT = re.compile(r"^\d\d[a-z]?-[a-z0-9-]+\.json$")
WALL_PARTS = ("gaps", "busy", "waiting for a human", "operator", "operator idle",
              "unattributed", "= wall")
OPERATOR_WAIT = ("waiting for a human", "operator idle", "unattributed")


class BadCall(Exception):
    pass


# --------------------------------------------------------------------------
# reading one batch

def read_events(batch):
    f = Path(batch) / EVENTS
    if not f.is_file():
        raise BadCall(f"{batch}: no {EVENTS}")
    out = []
    for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if isinstance(e, dict):
            out.append(e)
    return out


def stage_sequence(events):
    """The stages a run ran, in start order. An attempt closed as restarted
    (CF-0204) is dropped: the stage it belonged to starts again after it."""
    starts, open_ = [], {}
    for e in events:
        if e.get("kind") != "marker":
            continue
        st, status = e.get("stage"), e.get("status")
        if status == "stage-start":
            open_[st] = len(starts)
            starts.append({"stage": st, "restarted": False})
        elif status == "stage-done" and st in open_:
            if str(e.get("note") or "").startswith(RESTARTED):
                starts[open_[st]]["restarted"] = True
            open_.pop(st, None)
    return [s["stage"] for s in starts if not s["restarted"]]


def _count(doc, *keys):
    for k in keys:
        v = (doc or {}).get(k) if isinstance(doc, dict) else None
        if isinstance(v, list):
            return len(v)
    return None


def output_of(batch):
    batch = Path(batch)
    files = sorted(p.name for p in batch.iterdir()
                   if p.is_file() and (CONTRACT.match(p.name) or p.name in RECORDS))
    counts = {}

    def load(pattern):
        hits = sorted(batch.glob(pattern))
        if not hits:
            return None
        try:
            return json.loads(hits[0].read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    d03, d05, d06 = load("03-*.json"), load("05-*.json"), load("06-*.json")
    counts["scripts (03)"] = _count(d03, "scripts")
    counts["videos (05)"] = _count(d05, "videos")
    if isinstance(d05, dict) and isinstance(d05.get("videos"), list):
        counts["qc passed (05)"] = sum(1 for v in d05["videos"] if isinstance(v, dict)
                                       and isinstance(v.get("qc"), dict)
                                       and v["qc"].get("passed") is True)
    counts["verdicts (06)"] = _count(d06, "videos", "verdicts", "results")
    counts["mp4 under videos/"] = len(list((batch / "videos").glob("*.mp4"))) \
        if (batch / "videos").is_dir() else 0
    return files, counts


_DUR = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+(?:\.\d+)?)s)?$")


def seconds(text):
    m = _DUR.match(text.strip())
    if not m or not text.strip() or not any(m.groups()):
        return None
    h, mi, s = m.groups()
    return int(h or 0) * 3600 + int(mi or 0) * 60 + float(s or 0)


def wall_of(batch):
    """{part: seconds} from the `## Where the wall went` table; {} if none."""
    f = Path(batch) / SUMMARY
    try:
        text = f.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if "## Where the wall went" not in text:
        return {}
    sec = text.split("## Where the wall went", 1)[1].split("\n## ", 1)[0]
    out = {}
    for part, time_ in re.findall(r"^\|\s*([^|]+?)\s*\|\s*([0-9hms.]+)\s*\|", sec, re.M):
        if part in WALL_PARTS:
            v = seconds(time_)
            if v is not None:
                out[part] = v
    return out


def skipped_by_condition(batch, root=None):
    """({marker or stage id: reason}, {file: stage id}) of the plan stages the
    executor skipped on their `when` - from its run-state.json and the
    channel's plan (the markers and the `produces` of those stages)."""
    try:
        state = json.loads((Path(batch) / STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}, {}
    by_id = {}
    try:
        import channel_ids  # noqa: PLC0415
        import run_plan  # noqa: PLC0415
        where = root or state.get("root") or ROOT
        # a run-state written before a rename carries the old id (CF-0250)
        plan = run_plan.load(channel_ids.resolve_channel(state.get("channel"), where), where)
        by_id = {s["id"]: s for s in plan.get("stages", []) if isinstance(s, dict)}
    except Exception:                                   # noqa: BLE001
        by_id = {}
    names, files = {}, {}
    for sid, ss in (state.get("stages") or {}).items():
        reason = str(ss.get("reason") or "")
        if ss.get("status") == "skipped" and reason.startswith("when:"):
            names[sid] = reason
            st = by_id.get(sid) or {}
            if st.get("marker"):
                names.setdefault(st["marker"], f"{sid} {reason}")
            for f in st.get("produces") or []:
                files[f] = sid
    return names, files


# --------------------------------------------------------------------------
# comparing

def _numbered(seq):
    seen, out = {}, []
    for s in seq:
        seen[s] = seen.get(s, 0) + 1
        out.append(f"{s}#{seen[s]}")
    return out


def compare(manual, executor, root=None):
    m_seq = stage_sequence(read_events(manual))
    e_seq = stage_sequence(read_events(executor))
    skipped, skipped_files = skipped_by_condition(executor, root)
    m_num, e_num = _numbered(m_seq), _numbered(e_seq)
    defects, notes = [], []

    only_m = [s for s in m_num if s not in e_num]
    only_e = [s for s in e_num if s not in m_num]
    for s in only_m:
        name = s.split("#")[0]
        if name in skipped:
            notes.append(f"stage {s}: ran by hand, skipped by the plan on its condition "
                         f"({skipped[name]})")
        else:
            defects.append(f"stage {s}: ran by hand, not by the executor")
    for s in only_e:
        defects.append(f"stage {s}: ran by the executor, not by hand")
    common_m = [s for s in m_num if s in e_num]
    common_e = [s for s in e_num if s in m_num]
    if common_m != common_e:
        defects.append("order: by hand " + " > ".join(common_m) + " | executor "
                       + " > ".join(common_e))

    m_files, m_counts = output_of(manual)
    e_files, e_counts = output_of(executor)
    for f in sorted(set(m_files) ^ set(e_files)):
        side = "by hand only" if f in m_files else "executor only"
        if side == "by hand only" and f in skipped_files:
            notes.append(f"file {f}: {side} - its stage {skipped_files[f]} was skipped "
                         f"on its condition")
        else:
            defects.append(f"file {f}: {side}")

    m_wall, e_wall = wall_of(manual), wall_of(executor)
    return {
        "manual": str(manual), "executor": str(executor),
        "stages": {"manual": m_seq, "executor": e_seq},
        "files": {"manual": m_files, "executor": e_files},
        "counts": {"manual": m_counts, "executor": e_counts},
        "wall": {"manual": m_wall, "executor": e_wall,
                 "operator_wait_s": {"manual": _wait(m_wall), "executor": _wait(e_wall)}},
        "defects": defects, "notes": notes,
    }


def _wait(wall):
    if not wall:
        return None
    return sum(wall.get(p, 0.0) for p in OPERATOR_WAIT)


def fmt(s):
    if s is None:
        return "-"
    s = int(round(s))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}h{m:02d}m{sec:02d}s" if h else f"{m}m{sec:02d}s"


def report_lines(r):
    lines = [f"compare_runs: by hand {r['manual']}", f"              executor {r['executor']}", "",
             "stages, by hand:  " + (" > ".join(r["stages"]["manual"]) or "(none)"),
             "stages, executor: " + (" > ".join(r["stages"]["executor"]) or "(none)"), "",
             f"{'output':<22} {'by hand':>10} {'executor':>10}"]
    for k in r["counts"]["manual"]:
        a, b = r["counts"]["manual"].get(k), r["counts"]["executor"].get(k)
        lines.append(f"{k:<22} {'-' if a is None else a:>10} {'-' if b is None else b:>10}")
    lines += ["", f"{'wall (CF-0070)':<22} {'by hand':>10} {'executor':>10}"]
    for p in WALL_PARTS:
        a, b = r["wall"]["manual"].get(p), r["wall"]["executor"].get(p)
        if a is not None or b is not None:
            lines.append(f"{p:<22} {fmt(a):>10} {fmt(b):>10}")
    w = r["wall"]["operator_wait_s"]
    lines.append(f"{'operator wait':<22} {fmt(w['manual']):>10} {fmt(w['executor']):>10}"
                 f"   (waiting for a human + operator idle + unattributed)")
    lines.append("")
    for n in r["notes"]:
        lines.append(f"note   {n}")
    for d in r["defects"]:
        lines.append(f"DEFECT {d}")
    lines.append(f"verdict: {'the same stages, order and files' if not r['defects'] else str(len(r['defects'])) + ' defect(s) of the move'}")
    return lines


def main(argv=None):
    ap = argparse.ArgumentParser(prog="compare_runs.py", description=__doc__.split("\n\n")[0])
    ap.add_argument("manual", help="the last batch run by hand")
    ap.add_argument("executor", help="the batch run by shared/run_executor.py")
    ap.add_argument("--root", default=None, help="the factory root the channel plan is read from")
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    try:
        r = compare(Path(ns.manual), Path(ns.executor), ns.root)
    except BadCall as e:
        print(f"compare_runs: {e}", file=sys.stderr)
        return 2
    if ns.json:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    else:
        print("\n".join(report_lines(r)))
    return 1 if r["defects"] else 0


if __name__ == "__main__":
    sys.exit(main())
