#!/usr/bin/env python3
"""CF-0332: what running sources side by side buys on this machine - measured.

CF-0112 priced parallelism by Amdahl on frozen runs, with Vision taken as the
serial part because its calls never overlapped. They never overlapped because
the sources never did: a sequential run cannot show whether Vision *would*
serialize. This harness makes the question an experiment instead of a formula.

It cuts K short clips out of real pool sources (stream copy, nothing is
re-encoded and nothing in `shared/footage` is written), then indexes the same
clips with `index_footage.py` at N workers for each N asked for, each N in its
own copy of the clips and its own throw-away runlog batch. Per N it reports the
wall, the per-tool unions read by `indexer_cost.Run` (the reader CF-0112 and
CF-0331 used), the largest number of Vision calls seen at one instant, and the
share of frame cutting in the machine work.

`--vision shared` sends every worker to one warm Vision worker (the production
shape since CF-0029/CF-0058: one process, one connection at a time).
`--vision per-worker` gives each slot its own worker through
`VISION_WORKER_SOCKET`, which is the knob CF-0058 left for exactly this.
Both use private sockets, so a warm worker of a real run is never touched.

    .venv/bin/python3 scripts/measure_source_parallelism.py \
        --sources 4 --clip-seconds 12 --workers 1,2,4 --vision shared

Keep a sample under the 5-minute budget: indexing costs ~20 s of machine time
per shot after CF-0331, and a 12 s clip holds 2-5 shots.
"""
import argparse
import concurrent.futures as cf
import json
import os
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import indexer_cost  # noqa: E402
from _fi_paths import factory_root, venv_bin as _venv_bin  # noqa: E402 - CF-0267

ROOT = factory_root()
POOL = ROOT / "shared" / "footage"
VENV_PY = _venv_bin("python3")  # CF-0267: a worktree has no .venv of its own
FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
FFPROBE = shutil.which("ffprobe") or "ffprobe"

# The ops CF-0112 counted as frame cutting: every ffmpeg leaf of the indexer.
FRAME_TOOL = "ffmpeg"
VISION_TOOL = "vision"
# One clip's index may not take longer than this (a sample, not a production run).
INDEX_TIMEOUT_S = int(os.environ.get("CF0332_INDEX_TIMEOUT_S", 1800))


def duration(path):
    out = subprocess.run([FFPROBE, "-v", "error", "-show_entries", "format=duration",
                          "-of", "csv=p=0", str(path)],
                         capture_output=True, text=True, timeout=30)
    try:
        return float(out.stdout.strip())
    except ValueError:
        return 0.0


def cut_clips(k, seconds, seed, into):
    """K clips of `seconds` from K different pool sources that carry an index,
    taken from the middle of the source so an opening card is not all of it."""
    pool = sorted(p for p in POOL.glob("*.mp4") if p.with_suffix(".shots.json").exists())
    rng = random.Random(seed)
    rng.shuffle(pool)
    clips = []
    for src in pool:
        if len(clips) >= k:
            break
        d = duration(src)
        if d < seconds * 3:
            continue
        start = d * 0.4
        dest = into / f"{src.stem}.mp4"
        r = subprocess.run([FFMPEG, "-y", "-nostdin", "-v", "error", "-ss", f"{start:.2f}",
                            "-i", str(src), "-t", str(seconds), "-c", "copy",
                            "-avoid_negative_ts", "make_zero", str(dest)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode == 0 and dest.exists() and duration(dest) > seconds * 0.5:
            clips.append(dest)
    return clips


def index_all(clips, workers, vision, batch, stamp):
    """Index every clip, `workers` at a time. Returns (wall, [rc...])."""
    base = dict(os.environ)
    base["RUNLOG_BATCH"] = str(batch)
    base.pop("RUNLOG_PARENT", None)

    def one(args):
        slot, clip = args
        env = dict(base)
        if vision == "per-worker":
            env["VISION_WORKER_SOCKET"] = f"/tmp/scf-cf0332-{stamp}-w{slot}.sock"
        else:
            env["VISION_WORKER_SOCKET"] = f"/tmp/scf-cf0332-{stamp}-shared.sock"
        r = subprocess.run([str(VENV_PY), str(HERE / "index_footage.py"), str(clip)],
                           capture_output=True, text=True, env=env, timeout=INDEX_TIMEOUT_S)
        return r.returncode, r.stderr.strip().splitlines()[-1:] if r.returncode else []

    t0 = time.perf_counter()
    # A slot per worker: clip i goes to slot i % workers, so a per-worker Vision
    # socket is only ever used by one index process at a time.
    with cf.ThreadPoolExecutor(max_workers=workers) as ex:
        rcs = list(ex.map(one, [(i % workers, c) for i, c in enumerate(clips)]))
    return time.perf_counter() - t0, rcs


def read(batch):
    run = indexer_cost.Run(batch)
    tools = run.tools()
    real = run.real()
    vision_spans = [c["span"] for c in real if c["tool"] == VISION_TOOL]
    all_spans = [c["span"] for c in real]
    union = indexer_cost.union_s(all_spans)
    shots = sum(run.shots().values())
    ops = run.ops()
    return {
        "shots": shots,
        "machine_union_s": union,
        "busy_sum_s": sum(c["dur"] for c in real),
        "ffmpeg_union_s": (tools.get(FRAME_TOOL) or {}).get("union_s", 0.0),
        "vision_union_s": (tools.get(VISION_TOOL) or {}).get("union_s", 0.0),
        "vision_busy_s": (tools.get(VISION_TOOL) or {}).get("busy_s", 0.0),
        "vision_max_par": indexer_cost.max_concurrency(vision_spans) if vision_spans else 0,
        "full_frame_busy_s": (ops.get("shot-full-frame") or {}).get("busy_s", 0.0),
        "full_frame_p50_s": (ops.get("shot-full-frame") or {}).get("p50"),
        "vision_text_regions_p50_s": (ops.get("vision-text_regions") or {}).get("p50"),
    }


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--sources", type=int, default=4)
    p.add_argument("--clip-seconds", type=float, default=12.0)
    p.add_argument("--workers", default="1,2,4")
    p.add_argument("--vision", choices=("shared", "per-worker"), default="shared")
    p.add_argument("--seed", type=int, default=332)
    p.add_argument("--keep", help="directory to keep the clips and batches in")
    p.add_argument("--json", help="write the rows here as JSON")
    a = p.parse_args(argv)

    work = Path(a.keep) if a.keep else Path(tempfile.mkdtemp(prefix="cf0332-"))
    work.mkdir(parents=True, exist_ok=True)
    clips_dir = work / "clips"
    clips_dir.mkdir(exist_ok=True)
    clips = sorted(clips_dir.glob("*.mp4")) or cut_clips(a.sources, a.clip_seconds,
                                                          a.seed, clips_dir)
    print(f"{len(clips)} clips of {a.clip_seconds:g} s in {clips_dir}: "
          + ", ".join(c.stem for c in clips))
    rows = []
    stamp = f"{os.getpid()}"
    for n in [int(x) for x in a.workers.split(",") if x.strip()]:
        run_dir = work / f"n{n}-{a.vision}"
        if run_dir.exists():
            shutil.rmtree(run_dir)
        run_dir.mkdir()
        batch = run_dir / "batch"
        batch.mkdir()
        mine = []
        for c in clips:
            dest = run_dir / c.name
            shutil.copy2(c, dest)
            mine.append(dest)
        wall, rcs = index_all(mine, n, a.vision, batch, stamp)
        row = {"workers": n, "vision": a.vision, "sources": len(mine),
               "wall_s": round(wall, 2), "failed": [r for r in rcs if r[0] != 0]}
        try:
            row.update(read(batch))
        except Exception as e:                 # a reader failure is not the run's
            row["read_error"] = f"{type(e).__name__}: {e}"
        rows.append(row)
        print(json.dumps(row, default=str))
    if rows and rows[0].get("wall_s"):
        base = rows[0]["wall_s"]
        print("\nworkers  wall     vs N=1   shots  machine  ffmpeg  vision  vision-par  full-frame p50")
        for r in rows:
            print(f"{r['workers']:>7}  {r['wall_s']:6.1f}s  {100 * (r['wall_s'] / base - 1):+6.1f}%"
                  f"  {r.get('shots', '?'):>5}  {r.get('machine_union_s', 0):6.1f}s"
                  f"  {r.get('ffmpeg_union_s', 0):6.1f}s  {r.get('vision_union_s', 0):6.1f}s"
                  f"  {r.get('vision_max_par', '?'):>10}  {r.get('full_frame_p50_s') or 0:.2f}s")
    if a.json:
        Path(a.json).write_text(json.dumps(rows, indent=2, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
