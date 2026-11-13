#!/usr/bin/env python3
"""What the CF-0452 sharpness measure reads on the shots of named videos - the
distribution the floor and the proposed price come from (CF-0320).

Read-only. For each video it reads `pipeline/<channel>/<batch>/work/<slug>/
plan.json`, takes every block's shot (`"<source>:<index>"`), and measures it
twice from the pool's own file (`shared/footage/<source>.mp4`, span from
`<source>.shots.json`):

  whole    `sharpness.measure()` over the shot's own span - what the index
           records for new material;
  screen   what the viewer got: a held frame (`held_frame`) is
           `sharpness.at(cut_at)`, a clip is `measure()` over
           `[cut_at, cut_at + block length]` inside the shot.

It measures only the shots of the videos it is given - tens of shots, never
the pool (the pool is transient, CF-0410). A source whose file is gone is
reported `gone`, not guessed. The verdict of each video is the user's, from
`publish/acceptance-log.json`, or the one given on the command line.

Usage:
    measure_sharpness.py [--channel example-film] [--json]
        [--row]                      # print the proposed price row and stop
        BATCH/SLUG[=accepted|rejected] ...

Default videos (no arguments): the CF-0452 set - kaijura-minus-zero of
2026-09-27T0929Z and 2026-09-30T1248Z (rejected, `blurry_footage`) against
day-drinker, wolfhame, backrooms of 2026-09-30T1248Z (accepted).
"""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPTS))
import sharpness  # noqa: E402

from _fi_paths import checkout_root  # noqa: E402 - CF-0620

ROOT = checkout_root()  # CF-0620: this checkout's factory (or FACTORY_ROOT), not the home checkout
POOL = ROOT / "shared" / "footage"
ACCEPTANCE = ROOT / "publish" / "acceptance-log.json"

DEFAULT_VIDEOS = [
    "2026-09-27T0929Z/kaijura-minus-zero=rejected",
    "2026-09-30T1248Z/kaijura-minus-zero=rejected",
    "2026-09-30T1248Z/day-drinker=accepted",
    "2026-09-30T1248Z/wolfhame=accepted",
    "2026-09-30T1248Z/backrooms=accepted",
]


def _load(path):
    try:
        return json.loads(Path(path).read_text())
    except (OSError, ValueError):
        return None


def verdicts(path=ACCEPTANCE):
    out = {}
    for a in (_load(path) or {}).get("acceptances") or []:
        out[a.get("entry_id")] = a.get("verdict")
    return out


def _shot_span(source, index, pool):
    data = _load(pool / f"{source}.shots.json") or {}
    for s in data.get("shots") or []:
        if s.get("index") == index:
            return float(s["start"]), float(s["end"])
    return None


def blocks_of(plan):
    """`[(block_no, shot_key, held, cut_at, length)]` of a plan's blocks that
    name a shot."""
    out = []
    for i, b in enumerate((plan or {}).get("blocks") or []):
        key = b.get("shot")
        if not key or ":" not in str(key):
            continue
        out.append((i, key, bool(b.get("held_frame")), b.get("cut_at"),
                    round(float(b["end"]) - float(b["start"]), 3)))
    return out


def measure_block(key, held, cut_at, length, pool=POOL):
    source, idx = key.rsplit(":", 1)
    video = pool / f"{source}.mp4"
    span = _shot_span(source, int(idx), pool)
    if span is None or not video.exists():
        return {"gone": True}
    start, end = span
    shot = sharpness.measure(video, start, end)
    if held and cut_at is not None:
        screen = sharpness.at(video, float(cut_at))
    else:
        a = float(cut_at) if cut_at is not None else start
        a = min(max(a, start), end)
        b = min(end, a + max(0.2, length or 0.0))
        screen = sharpness.measure(video, a, b, n=3)
    return {"span": [start, end], "whole": shot, "screen": screen,
            "flag_shot": bool(sharpness.verdict(shot)),
            "flag_screen": bool(sharpness.verdict(screen, held=held))}


def measure_video(batch_slug, verdict, channel, root=ROOT, pool=POOL,
                  workers=4):
    batch, slug = batch_slug.split("/", 1)
    plan = _load(root / "pipeline" / channel / batch / "work" / slug
                 / "plan.json")
    if plan is None:
        return {"video": batch_slug, "verdict": verdict, "plan_gone": True,
                "blocks": []}
    todo = blocks_of(plan)
    with ThreadPoolExecutor(max_workers=workers) as ex:
        res = list(ex.map(lambda b: measure_block(b[1], b[2], b[3], b[4],
                                                  pool), todo))
    blocks = []
    for (i, key, held, cut_at, length), r in zip(todo, res):
        blocks.append({"block": i, "shot": key, "held": held,
                       "cut_at": cut_at, "length": length, **r})
    return {"video": batch_slug, "verdict": verdict, "blocks": blocks}


def _v(rec):
    return (rec or {}).get("value")


def distribution(videos):
    """`{verdict: {"held": [...], "clip": [...], "shot": [...]}}` of the
    screen readings by presentation and of the shot readings, sorted, one
    reading per distinct shot of a video."""
    out = {}
    for v in videos:
        d = out.setdefault(v["verdict"], {"held": [], "clip": [], "shot": []})
        seen = set()
        for b in v["blocks"]:
            if b.get("gone") or b["shot"] in seen:
                continue
            seen.add(b["shot"])
            if _v(b["screen"]) is not None:
                d["held" if b["held"] else "clip"].append(_v(b["screen"]))
            if _v(b["whole"]) is not None:
                d["shot"].append(_v(b["whole"]))
    for d in out.values():
        for k in d:
            d[k].sort()
    return out


def _fmt(x):
    return "  -  " if x is None else f"{x:.3f}"


def report(videos):
    lines = []
    for v in videos:
        lines.append(f"== {v['video']}  ({v['verdict']})"
                     + ("  PLAN GONE" if v.get("plan_gone") else ""))
        for b in v["blocks"]:
            if b.get("gone"):
                lines.append(f"  b{b['block']:02d} {b['shot']:<18} gone")
                continue
            sh, sc = b["whole"], b["screen"]
            lines.append(
                f"  b{b['block']:02d} {b['shot']:<18} "
                f"{'held' if b['held'] else 'clip'} "
                f"shot {_fmt(_v(sh))} (best {_fmt(sh.get('best'))} "
                f"motion {sh.get('motion')}) "
                f"screen {_fmt(_v(sc))}"
                + ("  <- low_sharpness" if b["flag_screen"] else ""))
    lines.append("")
    lines.append(f"distribution (floor {sharpness.MIN_SHARPNESS}; "
                 "one reading per distinct shot):")
    for verdict, d in sorted(distribution(videos).items()):
        for k in ("held", "clip", "shot"):
            xs = d[k]
            under = sum(1 for x in xs if x < sharpness.MIN_SHARPNESS)
            lines.append(f"  {verdict:<9} {k:<5} n={len(xs):2d} "
                         f"under={under:2d}  "
                         + " ".join(f"{x:.2f}" for x in xs))
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("videos", nargs="*")
    p.add_argument("--channel", default="example-film")
    p.add_argument("--json", action="store_true")
    p.add_argument("--row", action="store_true",
                   help="print the proposed (unsigned) price row and stop")
    a = p.parse_args(argv)
    if a.row:
        print(json.dumps({sharpness.PRICE_KEY: sharpness.proposed_row()},
                         ensure_ascii=False, indent=2))
        return 0
    known = verdicts()
    videos = []
    for spec in a.videos or DEFAULT_VIDEOS:
        batch_slug, _, verdict = spec.partition("=")
        verdict = verdict or known.get(f"{a.channel}/{batch_slug}") or "unknown"
        videos.append(measure_video(batch_slug, verdict, a.channel))
    if a.json:
        print(json.dumps({"videos": videos,
                          "distribution": distribution(videos)},
                         ensure_ascii=False, indent=1))
    else:
        print(report(videos))
    return 0


if __name__ == "__main__":
    sys.exit(main())
