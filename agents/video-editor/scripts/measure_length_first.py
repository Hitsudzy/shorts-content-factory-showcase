#!/usr/bin/env python3
"""CF-0517: how a one-shot block's pool order plays on the corpus.

A one-shot block (`budget == 1` - every block of `hold` and `staccato`, a
one-shot swing of `alternate`) wants one clip long enough for its phrase.
Before CF-0517 `fill()` ranked its pool by usability first (CF-0435) and kept
the long-enough-first sort only among shots of one score, so a short clean
shot in front of a long, slightly weaker one won the block and the block held
a frame. CF-0517 (the user's decision of 2026-10-04) puts length first and
usability second (`rank_by_usability(..., need=...)`), hard shots still last.

This measures it on finished storyboards - read-only, nothing in a batch or in
the footage pool is written:

  * `real_*` - the record as it is: one-shot blocks whose cut shot is shorter
    than the block while a long-enough candidate sat behind it in the old
    order (what `length_supply` calls `not_reached`), and how many of those
    held a frame (`held_frame: true`);
  * `sim_old` / `sim_new` - each video's one-shot blocks walked in order under
    the old and the new rank with the gates this stage can still see offline:
    the one-use ledger, the channel's retired shots as of the batch,
    burned-in text, and the block's own recorded refusals. `sim_old` is the
    control - `sim_old_reproduces_real_pick` says how often it lands on the
    shot the run really cut; the rest are gates it cannot replay (the real
    `usable()` on the cut clip, the swing sides, repeat_guard) or a pool
    whose cache moved since.

The pools come from one matcher call for the whole corpus (one CLIP load),
`--top`/`--min-score` at the resolver's defaults; sharpness probes are off (a
shot without a cached sharpness ranks as sharp). A video whose sources left
`shared/footage/` (CF-0358's pool rule) is skipped and counted.

    measure_length_first.py --out /tmp/cf0517.json [--mode sim|real]
        [--root <factory>] --channel <id> [--exclude-batch <id> ...]

`--mode real` ranks the new order with this checkout's own
`rank_by_usability(need=...)`; `sim` re-sorts the old rank by
`(hard, too short or under LENGTH_LEAD_MIN_USABILITY)` - the two must agree,
which is a check of the code. `--no-floor` (sim) drops the 0.5 floor.
"""
import argparse
import json
import re
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import resolve_anchors as ra  # noqa: E402
import rhythm  # noqa: E402
import shot_score  # noqa: E402
import wide_place  # noqa: E402

import repo_paths  # noqa: E402

import _clip_names  # noqa: E402 - CF-0665: archive ids next to YouTube ones
STEM = re.compile(rf"({_clip_names.SOURCE_ID}):(\d+)")

ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
ap.add_argument("--out", required=True)
ap.add_argument("--mode", choices=("sim", "real"), default="sim")
ap.add_argument("--root", default=str(repo_paths.FACTORY_ROOT),
                help="the factory whose batches are read (from a release "
                     "worktree: the main checkout, where the batches run)")
# CF-0212: no channel by default - the corpus is the one you name.
ap.add_argument("--channel", required=True)
ap.add_argument("--exclude-batch", action="append", default=[],
                help="a batch still running - never read as corpus")
ap.add_argument("--no-floor", action="store_true",
                help="sim only: length leads at any usability (CF-0517 before "
                     "the user's 0.5 floor) - the measure of what the floor changed")
ap.add_argument("--matcher-cache", default=None,
                help="matcher output to reuse/write (default: <out>.matcher.json)")
args = ap.parse_args()
OUT, MODE = Path(args.out), args.mode
FLOOR = None if args.no_floor else getattr(ra, "LENGTH_LEAD_MIN_USABILITY", None)
CH = Path(args.root) / "pipeline" / args.channel
FOOT = Path(args.root) / "shared" / "footage"
# Nothing is measured on the fly: a probe would read the source and fill the
# pool's cache, and this tool writes nothing.
shot_score.sharpness_module = lambda: None
retired_reg = json.load(open(CH / "retired-shots.json")) \
    if (CH / "retired-shots.json").exists() else {"videos": {}}


def batch_time(b):
    return datetime.strptime(b, "%Y-%m-%dT%H%MZ").isoformat()


def retired_for(batch, video_key):
    """The channel's retired shots as they stood when `batch` ran."""
    t = batch_time(batch)
    out = set()
    for vk, v in retired_reg["videos"].items():
        if vk != video_key and (v.get("retired_at") or "9")[:16] < t[:16]:
            out.update(v["shots"])
    return out


videos = []
for sb in sorted(CH.glob("*/work/*/storyboard.json")):
    batch, name = sb.parts[-4], sb.parts[-2]
    if batch in args.exclude_batch or name.startswith("supplement"):
        continue
    try:
        batch_time(batch)
    except ValueError:
        continue
    s = json.load(open(sb))
    if not s.get("resolved_from_anchors"):
        continue
    stems = {m.group(1) for m in STEM.finditer(json.dumps(s))}
    used_stems = {b["shot"].split(":")[0] for b in s["blocks"]
                  if ":" in str(b.get("shot") or "")}
    if not used_stems or any(not (FOOT / f"{st}.shots.json").exists() for st in used_stems):
        videos.append({"batch": batch, "name": name, "skip": "source gone"})
        continue
    idx = sorted(str(FOOT / f"{st}.shots.json") for st in stems
                 if (FOOT / f"{st}.shots.json").exists())
    videos.append({"batch": batch, "name": name, "sb": s, "idx": idx})

live = [v for v in videos if "sb" in v]
all_idx = sorted({i for v in live for i in v["idx"]})
phrases = sorted({a["phrase"] for v in live for a in v["sb"]["anchor_supply"]})
cache = Path(args.matcher_cache) if args.matcher_cache else OUT.with_suffix(".matcher.json")
if cache.exists():
    matched = json.load(open(cache))
else:
    args = [ra.DEFAULT_INDEXER_PY, ra.MATCHER]
    for i in all_idx:
        args += ["--index", i]
    args += phrases + ["--top", str(ra.DEFAULT_TOP), "--min-score",
                       str(ra.DEFAULT_MIN_SCORE), "--json"]
    r = subprocess.run(args, capture_output=True, text=True, timeout=280)
    if r.returncode:
        sys.exit(r.stderr[-3000:])
    matched = json.loads(r.stdout)
    json.dump(matched, open(cache, "w"))
pidx = {p: i for i, p in enumerate(phrases)}
per_index = matched["results_by_index"]
maxp = matched.get("max_promoted_cards", 0)
index_data = {i: json.load(open(i)) for i in per_index}
lut = ra.shot_lookup(index_data)


def key_of(c):
    return (Path(c["source"]).stem, c["shot"])


def score_of(c, place):
    shot = lut.get((c.get("index"), c.get("shot")))
    cached = (shot or {}).get("usable_cached")
    fresh = bool(cached) and not ra._stale_cache(cached)
    k = shot_score.rank_key(shot, fresh, None, wide=ra.wide_candidate(c, place))
    return k


def new_order(pool, need, place):
    if MODE == "real":
        return ra.rank_by_usability(pool, lut, place, need=need)
    old = ra.rank_by_usability(pool, lut, place)
    floor = FLOOR

    def key(c):
        k = score_of(c, place)
        short = ra.available_seconds(c) < need
        return (k[0], short or (floor is not None and -k[1] < floor))
    return sorted(old, key=key)


rows = []
for v in live:
    s = v["sb"]
    rb = (s.get("rhythm") or {}).get("rhythm_built")
    vidx = set(v["idx"])
    vkey = f"example-film/{v['batch']}/{v['name']}"
    retired = retired_for(v["batch"], vkey)
    segs = []
    for a in s["anchor_supply"]:
        dur = a["end"] - a["start"]
        if rb in ("hold", "staccato"):
            one = True
        elif rb == "alternate":
            one = rhythm.swing_shot_budget(dur) == 1
        else:
            one = False
        if not one:
            continue
        blocks = s["blocks"][a["block_index"]:a["block_index"] + (a["block_count"] or 0)]
        if not blocks or blocks[0].get("asset_kind") not in ("clip", "still") or not blocks[0].get("shot"):
            continue
        b0 = blocks[0]
        held = any(b.get("held_frame") for b in blocks)
        cands = []
        res_i = pidx[a["phrase"]]
        for idx, results in per_index.items():
            if idx not in vidx:
                continue
            src = index_data[idx]["source"]
            for m in results[res_i]["matches"]:
                cands.append({**m, "index": idx, "source": src})
        cands = ra.order_candidates(cands, maxp)
        pool, _ = ra.screen_pool(cands, s.get("min_score", ra.DEFAULT_MIN_SCORE), None)
        need = dur
        place = wide_place.is_place_anchor(a["phrase"])
        pool = sorted(pool, key=lambda c: ra.available_seconds(c) < need)
        old = ra.rank_by_usability(pool, lut, place)
        new = new_order(pool, need, place)
        chosen = tuple(b0["shot"].split(":"))
        chosen = (chosen[0], int(chosen[1]))
        row = {"video": vkey, "seg": a["segment"], "need": round(need, 3),
               "held": held, "rhythm": rb, "chosen": b0["shot"]}
        pos = next((i for i, c in enumerate(old) if key_of(c) == chosen), None)
        if pos is None:
            row["cat"] = "outside_pool"
            rows.append(row)
            continue
        row["cat"] = "in_pool"
        refused = {(r["shot"], round(r.get("score") or 0, 4)) for r in s["rejected_candidates"]
                   if r.get("phrase") == a["phrase"]
                   and not str(r.get("reason", "")).startswith("already used elsewhere")}
        ch = old[pos]
        row["chosen_avail"] = round(ra.available_seconds(ch), 3)
        row["chosen_score"] = -score_of(ch, place)[1]
        behind_long = [c for c in old[pos + 1:] if ra.available_seconds(c) >= need]
        row["not_reached_long"] = bool(behind_long) and row["chosen_avail"] < need
        segs.append((row, old, new, refused, place, need, chosen, behind_long))
        rows.append(row)
    in_seg = {r["chosen"] for r, *_ in segs}
    fixed = {b.get("shot") for b in s["blocks"] if b.get("shot")} - in_seg
    # shots of the in-pool one-shot blocks that other blocks (e.g. a split's
    # extra cuts) also show stay fixed too
    for tag, which in (("sim_old", 1), ("sim_new", 2)):
        ledger = set(fixed)
        for seg in segs:
            row, order, refused, place, need, chosen = seg[0], seg[which], seg[3], seg[4], seg[5], seg[6]

            def gated(c):
                name = f"{key_of(c)[0]}:{c['shot']}"
                if name in ledger or name in retired:
                    return True
                if key_of(c) == chosen:
                    return False
                shot = lut.get((c["index"], c["shot"])) or {}
                # CF-0567: our own recording's text is the footage
                return ((c["shot"], round(c["score"], 4)) in refused
                        or (shot.get("burned_text") is True
                            and not _clip_names.is_own_capture_shot(shot, key_of(c)[0])))
            pick = next((c for c in order if not gated(c)), None)
            if pick is not None:
                ledger.add(f"{key_of(pick)[0]}:{pick['shot']}")
            row[tag] = f"{key_of(pick)[0]}:{pick['shot']}" if pick else None
            row[tag + "_long"] = pick is not None and ra.available_seconds(pick) >= need
            row[tag + "_score"] = -score_of(pick, place)[1] if pick else None
            # a hard shot ranks last in both orders: its 0.0 is the
            # last resort's, not a soft price length could have chosen
            row[tag + "_hard"] = bool(pick) and score_of(pick, place)[0] == 1
            row[tag + "_under_floor"] = (bool(pick) and not row[tag + "_hard"]
                                         and row[tag + "_score"] < 0.5)
        row = None
    for seg in segs:
        row, behind_long = seg[0], seg[7]
        row["not_reached_long_ungated"] = row["not_reached_long"] and any(
            f"{key_of(c)[0]}:{c['shot']}" not in retired
            and not ((lut.get((c["index"], c["shot"])) or {}).get("burned_text")
                     and not _clip_names.is_own_capture_shot(
                         lut.get((c["index"], c["shot"])), key_of(c)[0]))
            for c in behind_long)


def mean(xs):
    xs = [x for x in xs if x is not None]
    return round(statistics.mean(xs), 4) if xs else None


inp = [r for r in rows if r["cat"] == "in_pool"]
nr = [r for r in inp if r["not_reached_long"]]
nru = [r for r in inp if r["not_reached_long_ungated"]]
faithful = [r for r in inp if r["sim_old"] == r["chosen"]]
ch = [r for r in inp if r["sim_new"] != r["sim_old"]]
summary = {
    "videos_total": len(videos), "videos_measured": len(live),
    "videos_skipped_source_gone": len(videos) - len(live),
    "one_shot_blocks": len(rows), "in_pool": len(inp),
    "outside_pool": len(rows) - len(inp),
    "held_all": sum(r["held"] for r in rows),
    "held_in_pool": sum(r["held"] for r in inp),
    "real_short_chosen": sum(r["chosen_avail"] < r["need"] for r in inp),
    "real_not_reached_long": len(nr),
    "real_not_reached_long_held": sum(r["held"] for r in nr),
    "real_not_reached_long_not_retired_or_burned": len(nru),
    "real_not_reached_long_not_retired_or_burned_held": sum(r["held"] for r in nru),
    "sim_old_reproduces_real_pick": len(faithful),
    "sim_old_short": sum(not r["sim_old_long"] for r in inp),
    "sim_new_short": sum(not r["sim_new_long"] for r in inp),
    "sim_changed": len(ch),
    "sim_changed_short_to_long": sum((not r["sim_old_long"]) and r["sim_new_long"] for r in ch),
    "sim_changed_long_to_short": sum(r["sim_old_long"] and not r["sim_new_long"] for r in ch),
    "held_real_and_sim_new_long": sum(r["held"] and r["sim_new_long"] for r in inp),
    "held_real_and_sim_old_long": sum(r["held"] and r["sim_old_long"] for r in inp),
    "mean_score_real": mean(r["chosen_score"] for r in inp),
    "mean_score_sim_old": mean(r["sim_old_score"] for r in inp),
    "mean_score_sim_new": mean(r["sim_new_score"] for r in inp),
    "changed_mean_score_sim_old": mean(r["sim_old_score"] for r in ch),
    "changed_mean_score_sim_new": mean(r["sim_new_score"] for r in ch),
    "changed_score_drops": sum((r["sim_new_score"] or 0) < (r["sim_old_score"] or 0) for r in ch),
    "sim_old_hard_last_resort": sum(r["sim_old_hard"] for r in inp),
    "sim_new_hard_last_resort": sum(r["sim_new_hard"] for r in inp),
    "sim_old_soft_under_0_5": sum(r["sim_old_under_floor"] for r in inp),
    "sim_new_soft_under_0_5": sum(r["sim_new_under_floor"] for r in inp),
    "changed_score_gains": sum((r["sim_new_score"] or 0) > (r["sim_old_score"] or 0) for r in ch),
}
json.dump({"summary": summary, "rows": rows}, open(OUT, "w"), indent=1)
print(json.dumps(summary, indent=1))
