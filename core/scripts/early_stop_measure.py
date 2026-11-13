#!/usr/bin/env python3
"""CF-0838: what an early stop of a hopeless source would have saved - a
replay over the batches' records, read-only. Not a test (docs/test-hygiene.md:
a test never reads live batches); its result is written into
docs/analysis/early-stop-2026-10.md by hand.

The rule replayed: "the first K shots of a source (in index order) all carry
the hard usability rule `burned_text` -> the rest of the source is not
indexed". Nothing is measured again: no Vision, no footage, no usability or
caption cache is touched. Three records are read:

  * `RUN_EVENTS.jsonl` of each batch - every `index_footage.py` run (both the
    Footage Indexer and the thin-pool supplement), its wall time, and the
    start of each shot's probe loop (the first Vision call on
    `shot_NNN_full.png`). A shot's loop time is the gap to the next shot's
    start; the last shot gets the run's median gap (the gap to the end of the
    run carries the run's tail, which an early stop does not save). The
    per-shot preparation done before the loop for every shot at once
    (thumbnail, numbered frame, full frame) is counted separately, as `prep`.
  * `shared/footage/<id>.shots.json` - the shot's verdict as it is written
    there (`usability.hard[].rule`, and clean/weak/out by the same
    `pool_depth.screen_shots` the walk's depth floor reads). It is checked
    against the batch-time record in `01b-footage-index.json`
    (`source_sieve.sources[].burned_text_shots`, `pool_depth.topics[].
    per_source`), and a source whose file differs from it is reported.
  * every `05-video-editor.json` from 2026-10-10 on - which (source, shot)
    pairs reached a finished video.

    python3 scripts/early_stop_measure.py [--root <factory checkout>]
        [--since 2026-10-10] [--until 2026-10-21] [--k 6 8 10 12] [--json]

Run it with the Footage Indexer's venv (it imports `pool_depth`), e.g.
`<root>/agents/footage-indexer/.venv/bin/python`. The agent code is read
from this checkout's `agents/footage-indexer/scripts`.
"""
import argparse
import collections
import datetime as dt
import glob
import json
import re
import statistics
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CHANNELS = ("example-film", "example-tech")
HARD_RULE = "burned_text"
SHOT_FULL = re.compile(r"shot_(\d+)_full\.png$")
SHOT_PREP = re.compile(r"/(?:shot_\d+|numbered/n_\d+)\.png$")
CLIP_SRC = re.compile(r"/[a-z]\d{2}_(.+?)_s(\d{3})[^/]*\.mp4$")


def default_root():
    # .worktrees/release-x/ -> the production checkout two levels up
    prod = REPO.parent.parent
    if REPO.parent.name == ".worktrees" and (prod / "pipeline").is_dir():
        return prod
    return REPO


def load_pool_depth():
    scripts = REPO / "agents" / "footage-indexer" / "scripts"
    sys.path.insert(0, str(scripts))
    import pool_depth  # noqa: E402
    return pool_depth


def ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def batches(root, since, until):
    for ch in CHANNELS:
        for d in sorted(glob.glob(str(root / "pipeline" / ch / "2026-*"))):
            name = Path(d).name
            if since <= name[:10] <= until and Path(d, "RUN_EVENTS.jsonl").exists():
                yield ch, Path(d)


def index_runs(batch):
    """Every index_footage.py run of the batch, with per-shot loop starts."""
    runs = {}                      # pid -> run
    with open(batch / "RUN_EVENTS.jsonl") as fh:
        events = [json.loads(line) for line in fh if line.strip()]
    for e in events:
        if e.get("kind") == "script" and e.get("name") == "index_footage.py":
            pid = e.get("pid")
            if e.get("status") == "start":
                args = ((e.get("params") or {}).get("args") or [])
                path = Path(args[0]) if args else None
                runs[pid] = {"pid": pid, "stage": e.get("stage"),
                             "video_id": path.stem if path else None,
                             "path": str(path) if path else None,
                             "start": ts(e["ts"]), "end": None,
                             "duration_s": None, "shot_start": {},
                             "prep_s": 0.0}
            elif pid in runs:
                runs[pid]["end"] = ts(e["ts"])
                runs[pid]["duration_s"] = e.get("duration_s")
                runs[pid]["status"] = e.get("status")
    for e in events:
        run = runs.get(e.get("pid"))
        if run is None or e.get("kind") != "child":
            continue
        argv = e.get("argv") or []
        if e.get("tool") == "vision" and e.get("status") == "start":
            m = SHOT_FULL.search(argv[2] if len(argv) > 2 else "")
            if m:
                n = int(m.group(1))
                t = ts(e["ts"])
                if n not in run["shot_start"] or t < run["shot_start"][n]:
                    run["shot_start"][n] = t
        elif e.get("tool") == "ffmpeg" and e.get("status") == "done":
            if (argv[:2] == ["ffmpeg", "full-frames"]
                    or (argv and SHOT_PREP.search(argv[-1]))):
                run["prep_s"] += float(e.get("duration_s") or 0.0)
    return [r for r in runs.values() if r["end"] is not None]


def loop_seconds(run):
    """`{shot: seconds}` of the per-shot probe loop of one run."""
    starts = sorted(run["shot_start"].items())
    out = {}
    for (n, t), (_n2, t2) in zip(starts, starts[1:]):
        out[n] = (t2 - t).total_seconds()
    if starts:
        med = statistics.median(out.values()) if out else (
            run["end"] - starts[-1][1]).total_seconds()
        out[starts[-1][0]] = med
    return out


def shot_verdicts(pool_depth, shots):
    out = []
    for shot in shots:
        usable, _sec, _cards, weak = pool_depth.screen_shots([shot], detail=True)
        hard = [h.get("rule") for h in ((shot.get("usability") or {})
                                        .get("hard") or [])]
        out.append({"cls": "clean" if usable else ("weak" if weak else "out"),
                    "burned_hard": HARD_RULE in hard, "hard": hard})
    return out


def used_shots(root, since):
    """`{video_id: {shot, ...}}` of every clip that reached a finished video."""
    used = collections.defaultdict(set)
    for ch in CHANNELS:
        for f in glob.glob(str(root / "pipeline" / ch / "2026-*" /
                               "05-video-editor.json")):
            if Path(f).parent.name[:10] < since:
                continue
            try:
                d = json.load(open(f))
            except (OSError, ValueError):
                continue
            for v in d.get("videos") or []:
                for a in v.get("assets") or []:
                    for s in _strings(a):
                        m = CLIP_SRC.search(s)
                        if m:
                            used[m.group(1)].add(int(m.group(2)))
    return used


def _strings(o):
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def batch_record(batch):
    """Batch-time facts from 01b: sieve burned lists, per-source depth,
    topic depth and the topic each source belongs to."""
    try:
        d = json.load(open(batch / "01b-footage-index.json"))
    except (OSError, ValueError):
        return {}, {}, {}, None
    sieve = {s.get("video_id"): s for s in
             ((d.get("source_sieve") or {}).get("sources") or [])}
    per_source, topics = {}, {}
    pd = d.get("pool_depth") or {}
    for t in pd.get("topics") or []:
        topics[t["topic_id"]] = t
        for s in t.get("per_source") or []:
            per_source[s.get("video_id")] = dict(s, topic_id=t["topic_id"])
    return sieve, per_source, topics, pd.get("floor")


def stop_at(verdicts, k, burned=None):
    """True when the first `k` shots all carry the hard `burned_text` rule
    and there is something left to skip. `burned` - the batch-time set of
    burned shot indexes (the sieve's record) - wins over `verdicts`."""
    if burned is None:
        burned = {i for i, v in enumerate(verdicts) if v["burned_hard"]}
    return len(verdicts) > k and all(i in burned for i in range(k))


def burned_prefix(n, burned):
    i = 0
    while i < n and i in burned:
        i += 1
    return i


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=None)
    ap.add_argument("--since", default="2026-10-10")
    ap.add_argument("--until", default="2026-10-21")
    ap.add_argument("--k", type=int, nargs="+", default=[6, 8, 10, 12])
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    root = Path(a.root) if a.root else default_root()
    pool_depth = load_pool_depth()
    used = used_shots(root, a.since)

    sources = []                 # one row per index run in the window
    topic_rows = []              # one row per topic of 01b pool_depth
    verdict_cache = {}
    for ch, batch in batches(root, a.since, a.until):
        sieve, per_source, topics, floor = batch_record(batch)
        for run in index_runs(batch):
            vid = run["video_id"]
            shots_path = Path(run["path"]).with_suffix(".shots.json")
            row = {"channel": ch, "batch": batch.name, "stage": run["stage"],
                   "video_id": vid, "run_s": run["duration_s"],
                   "prep_s": round(run["prep_s"], 1),
                   "topic_id": (per_source.get(vid) or {}).get("topic_id"),
                   "used_shots": sorted(used.get(vid, ())),
                   "problems": []}
            loop = loop_seconds(run)
            row["loop_s"] = round(sum(loop.values()), 1)
            try:
                shots = json.load(open(shots_path)).get("shots") or []
            except (OSError, ValueError):
                row["problems"].append("no shots.json")
                shots = None
            if shots is not None:
                if vid not in verdict_cache:
                    verdict_cache[vid] = shot_verdicts(pool_depth, shots)
                ver = verdict_cache[vid]
                row["shots"] = len(ver)
                row["clean"] = sum(v["cls"] == "clean" for v in ver)
                row["weak"] = sum(v["cls"] == "weak" for v in ver)
                row["burned_hard"] = sum(v["burned_hard"] for v in ver)
                if loop and len(loop) != len(ver):
                    row["problems"].append(
                        f"loop shots {len(loop)} != index shots {len(ver)}")
                # batch-time cross-check
                s = sieve.get(vid)
                now = {i for i, v in enumerate(ver) if v["burned_hard"]}
                burned, row["trigger_from"] = now, "shots.json"
                if s and s.get("burned_text_shots") is not None:
                    burned = set(s["burned_text_shots"])
                    row["trigger_from"] = "sieve"
                    if now != burned:
                        row["problems"].append(
                            f"burned now {len(now)} vs sieve {len(burned)}")
                row["burned_prefix"] = burned_prefix(len(ver), burned)
                p = per_source.get(vid)
                if p and (p.get("usable_shots"), p.get("weak_shots")) != (
                        row["clean"], row["weak"]):
                    row["problems"].append(
                        f"clean/weak now {row['clean']}/{row['weak']} vs "
                        f"01b {p.get('usable_shots')}/{p.get('weak_shots')}")
                row["k"] = {}
                for k in a.k:
                    if not stop_at(ver, k, burned):
                        continue
                    rest = range(k, len(ver))
                    if loop and len(loop) == len(ver):
                        saved = sum(loop.get(i, 0.0) for i in rest)
                    else:
                        saved = (row["loop_s"] / max(len(loop), 1)) * len(rest)
                    row["k"][k] = {
                        "shots_saved": len(rest),
                        "loop_s_saved": round(saved, 1),
                        "prep_s_saved": round(run["prep_s"] * len(rest)
                                              / max(len(ver), 1), 1),
                        "clean_lost": sum(ver[i]["cls"] == "clean" for i in rest),
                        "weak_lost": sum(ver[i]["cls"] == "weak" for i in rest),
                        "used_lost": sorted(i for i in row["used_shots"] if i >= k),
                    }
            sources.append(row)
        for tid, t in topics.items():
            lost = {k: 0 for k in a.k}
            for s in t.get("per_source") or []:
                ver = verdict_cache.get(s.get("video_id"))
                if ver is None:
                    p = Path(root / "shared" / "footage" /
                             f"{s.get('video_id')}.shots.json")
                    try:
                        ver = shot_verdicts(pool_depth, json.load(open(p))
                                            .get("shots") or [])
                    except (OSError, ValueError):
                        continue
                    verdict_cache[s.get("video_id")] = ver
                for k in a.k:
                    if stop_at(ver, k):
                        lost[k] += sum(v["cls"] == "clean" for v in ver[k:])
            topic_rows.append({
                "channel": ch, "batch": batch.name, "topic_id": tid,
                "usable": t.get("usable_shots"), "floor": t.get("floor", floor),
                "deep_enough": t.get("deep_enough"), "clean_lost": lost,
                "flips": {k: bool(t.get("deep_enough") and t.get("usable_shots")
                                  is not None
                                  and t["usable_shots"] - lost[k]
                                  < (t.get("floor") or floor or 0))
                          for k in a.k}})

    if a.json:
        print(json.dumps({"sources": sources, "topics": topic_rows},
                         indent=1, default=str))
        return
    report(sources, topic_rows, a.k)


def report(sources, topics, ks):
    total_run = sum(r["run_s"] or 0 for r in sources) / 60
    total_loop = sum(r["loop_s"] for r in sources) / 60
    zero = [r for r in sources if r.get("shots") is not None and r["clean"] == 0]
    print(f"index runs: {len(sources)} in "
          f"{len({(r['channel'], r['batch']) for r in sources})} batches; "
          f"run time {total_run:.0f} min, of it probe loop {total_loop:.0f} min")
    print(f"runs with 0 clean shots: {len(zero)}, "
          f"{sum(r['run_s'] or 0 for r in zero) / 60:.0f} min; "
          f"of them reached a video: "
          f"{sum(bool(r['used_shots']) for r in zero)}")
    print(f"runs without shots.json: "
          f"{sum('no shots.json' in r['problems'] for r in sources)}; "
          f"with a mismatch: "
          f"{sum(bool(r['problems']) for r in sources)}")
    print()
    print("K | stopped | shots saved | loop min | +prep min | clean lost | "
          "weak lost | stopped srcs in videos | used shots lost | flips")
    for k in ks:
        hit = [r for r in sources if k in (r.get("k") or {})]
        g = lambda f: sum(r["k"][k][f] for r in hit)  # noqa: E731
        print(f"{k} | {len(hit)} | {g('shots_saved')} | "
              f"{g('loop_s_saved') / 60:.1f} | {g('prep_s_saved') / 60:.1f} | "
              f"{g('clean_lost')} | {g('weak_lost')} | "
              f"{sum(bool(r['used_shots']) for r in hit)} | "
              f"{sum(len(r['k'][k]['used_lost']) for r in hit)} | "
              f"{sum(t['flips'][k] for t in topics)}")
    print()
    for r in sources:
        ks_hit = ",".join(str(k) for k in ks if k in (r.get("k") or {}))
        print(f"{r['channel'][6:]} {r['batch']} {r['stage'][:9]:9} "
              f"{r['video_id']} shots={r.get('shots')} clean={r.get('clean')} "
              f"weak={r.get('weak')} burned={r.get('burned_hard')} "
              f"run={(r['run_s'] or 0) / 60:.1f}m loop={r['loop_s'] / 60:.1f}m "
              f"used={len(r['used_shots'])} prefix={r.get('burned_prefix')} "
              f"stop@[{ks_hit}] "
              f"{'; '.join(r['problems'])}")


if __name__ == "__main__":
    main()
