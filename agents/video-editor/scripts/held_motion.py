#!/usr/bin/env python3
"""CF-0481: a frame of motion held still - `score.held_moving_face`.

The user rejected vanguards-doomsday of `example-film/2026-10-01T1313Z`
("много стоп-кадров в движении, растянуто и некрасиво"). The share of held /
stretched frames does not tell it from the accepted paper-dragon of
`2026-09-23T1722Z` (85.1 % against 81.4 %, CF-0474); what the eye sees is a
*person stopped mid-motion*: a podcast host frozen mid-word, mid-gesture,
while in the source shot around that frame everything moves.

**The measure (on the fly, for the held frames of the plan only - the pool
is never re-measured, CF-0358).** For every held frame (`still_share.
held_frames`: a held block, a sequence's held cut):

* `motion` - how much the source shot moves around the held moment: the
  shot is decoded at 192x108 grey, the held picture is matched to its frame
  (least mean difference, black letterbox rows dropped), and over
  `WINDOW` seconds on each side the 95th percentile of the 12 px tiles'
  mean frame-to-frame difference is taken per pair, the median of the pairs
  is the value (0-255 grey levels). A local percentile, not the global mean:
  a talking face moves in a few tiles of a still set.
* `face_area` - the largest face Vision finds on the held picture, as a
  share of the picture (`vision_client.find_roi`, faces only).

A frame is **frozen motion** when `face_area >= FACE_MIN` and
`motion >= MOTION_MIN`. The video's `frozen_seconds` is the time such frames
stand on screen.

**Read off the acceptance log (2026-10-02, the 31 plans of the log with a
plan.json + the two CF-0480 replays, this module's own measure).** Motion
alone does not separate: accepted vanguards-endgame 0705Z holds frames out of
moving shots (battle, crowds), day-drinker 2210Z too. Motion with a face
does: rejected vanguards-doomsday 1313Z 27.9 s of frozen motion as rendered,
15.8 s after CF-0480's stretch split (block 5, the bearded host talking
animatedly, 8.96 s on one frame); every accepted video 11.1 s or less
(vanguards-endgame 0705Z 11.1, american-dread-story 1722Z 10.6, wolfhame 1757Z
8.0, the rest <= 5.5). An open mouth (Vision's inner lips) adds nothing the
face does not - it is not part of the rule. `ALLOW` sits in that window
(11.1 .. 15.8 s): what is over it is the defect. The window rests on one
rejected video; margin 0.9 s above the accepted maximum.

**The price: none until the user signs one (CF-0320).** Like
`held_sharpness.py`: only a signed row `score.held_moving_face` in
`shared/gate-prices.json` makes it a penalty; without it the plan carries
the record (`held_motion`, `mode: warn`) and a note, nothing is charged.
`PROPOSED`: per second over `ALLOW`, so that the defect alone takes a clean
video (100) under N (40): doomsday 1313Z after CF-0480, 15.8 s -> 3.8 s over
-> -60.8 -> 39.2. No accepted video of the log loses a point.
"""
import json
import subprocess
from pathlib import Path

import held_sharpness
import still_share

TASK = "CF-0481"
RULE = "score.held_moving_face"
FIELD = "held_motion"               # on the block / the cut that holds
MEASURED_BY = "CF-0481/held-src-motion-tile-p95+face/v1"
MOTION_MIN = 5.0                    # grey levels, tile p95 around the held moment
FACE_MIN = 0.02                     # share of the picture the largest face takes
ALLOW = 12.0                        # seconds of frozen motion that cost nothing
WINDOW = 0.5                        # seconds each side of the held moment
GRID_W, GRID_H, TILE = 192, 108, 12
BAR_LUMA = 8.0                      # a row darker than this over the shot is letterbox
PROPOSED = {"price": 16, "per": "second", "cap": 64, "hook_mult": None,
            "allow_seconds": ALLOW}

MODE_PENALTY = held_sharpness.MODE_PENALTY
MODE_WARN = held_sharpness.MODE_WARN


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ the measure

def tile_motion(frames):
    """Median over consecutive pairs of the 95th percentile of the tiles'
    mean absolute difference (grey levels) - None under two frames.
    `frames` is a numpy array (n, h, w)."""
    import numpy as np
    if frames is None or len(frames) < 2:
        return None
    d = np.abs(np.diff(frames.astype(np.float32), axis=0))
    h = (d.shape[1] // TILE) * TILE
    w = (d.shape[2] // TILE) * TILE
    if h == 0 or w == 0:
        return float(np.median(d.mean(axis=(1, 2))))
    tiles = d[:, :h, :w].reshape(len(d), h // TILE, TILE, w // TILE, TILE).mean(axis=(2, 4))
    return float(np.median(np.percentile(tiles.reshape(len(d), -1), 95, axis=1)))


def _fps(src):
    try:
        out = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0",
                              "-show_entries", "stream=r_frame_rate", "-of", "csv=p=0",
                              str(src)], capture_output=True, text=True, timeout=30).stdout
        n, d = out.strip().split("/")
        v = float(n) / float(d)
        return v if v > 0 else None
    except Exception:  # noqa: BLE001 - unreadable: no rate
        return None


def _decode(src, start, end):
    import numpy as np
    raw = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t",
                          f"{max(0.05, end - start):.3f}", "-i", str(src), "-vf",
                          f"scale={GRID_W}:{GRID_H},format=gray", "-f", "rawvideo", "-"],
                         capture_output=True, timeout=120).stdout
    n = len(raw) // (GRID_W * GRID_H)
    return np.frombuffer(raw[: n * GRID_W * GRID_H], np.uint8).reshape(n, GRID_H, GRID_W)


# CF-0536: where a frame is held when the shot has no sharpness record to
# say (shot_score.held_moment) - the calmest moment of the cut clip instead of
# its middle, when the clip has one: a moment whose motion (this module's
# measure - the median over +-WINDOW of the tile p95 of frame differences)
# is under MOTION_MIN, the line past which a held face is frozen motion. A
# clip that moves all through keeps its middle frame: no moment of it is
# calm, and the calmest of the motion is not sharper for it. The clip's first
# and last CALM_EDGE are not offered (a cut's edges are its shot boundaries).
CALM_EDGE = 0.1


def calmest_moment(clip):
    """Seconds into `clip` of its calmest frame (least `motion` as
    `source_motion` reads it, away from the clip's edges) when that frame is
    under MOTION_MIN; None when no frame is, or the clip cannot be read or
    has fewer than 3 frames."""
    import numpy as np
    try:
        frames = _decode(clip, 0.0, 3600.0)
        fps = _fps(clip)
    except Exception:  # noqa: BLE001 - an unreadable clip has no calm moment
        return None
    if frames is None or len(frames) < 3 or not fps:
        return None
    d = np.abs(np.diff(frames.astype(np.float32), axis=0))
    h, w = (d.shape[1] // TILE) * TILE, (d.shape[2] // TILE) * TILE
    if h and w:
        tiles = d[:, :h, :w].reshape(len(d), h // TILE, TILE, w // TILE, TILE).mean(axis=(2, 4))
        pair = np.percentile(tiles.reshape(len(d), -1), 95, axis=1)
    else:
        pair = d.mean(axis=(1, 2))
    n, half = len(frames), max(1, int(round(WINDOW * fps)))
    per = np.array([np.median(pair[max(0, k - half): min(len(pair), k + half)])
                    for k in range(n)])
    lo = min(n - 2, max(1, int(n * CALM_EDGE)))
    hi = max(lo + 1, min(n - 1, n - int(n * CALM_EDGE)))
    k = lo + int(np.argmin(per[lo:hi]))
    if per[k] >= MOTION_MIN:
        return None
    return round(k / fps, 3)


def source_motion(src, start, end, picture):
    """`{"at", "match", "motion", "shot_motion"}` for the held `picture`
    lifted out of the source `src` between `start` and `end` (seconds), or
    None when the source cannot be read."""
    import numpy as np
    from PIL import Image
    try:
        frames = _decode(src, start, end).astype(np.float32)
        fps = _fps(src)
        if len(frames) < 2 or not fps:
            return None
        lit = np.where(frames.mean(axis=(0, 2)) > BAR_LUMA)[0]
        y0, y1 = (int(lit[0]), int(lit[-1]) + 1) if len(lit) else (0, GRID_H)
        frames = frames[:, y0:y1]
        pic = np.asarray(Image.open(picture).convert("L").resize((GRID_W, y1 - y0)),
                         np.float32)
        err = np.abs(frames - pic).mean(axis=(1, 2))
        k = int(np.argmin(err))
        half = max(1, int(round(WINDOW * fps)))
        win = frames[max(0, k - half): k + half + 1]
        return {"at": round(start + k / fps, 3), "match": round(float(err[k]), 1),
                "motion": _r(tile_motion(win)), "shot_motion": _r(tile_motion(frames))}
    except Exception:  # noqa: BLE001 - an unreadable source measures nothing
        return None


def _r(x, n=2):
    return None if x is None else round(x, n)


def face_area(picture):
    """The largest Vision face on `picture` as a share of it (0.0 when none,
    None when Vision cannot be asked)."""
    try:
        import vision_client
        info = vision_client.find_roi(str(picture))
    except Exception:  # noqa: BLE001 - no Vision: no face reading
        return None
    if not isinstance(info, dict):
        return None
    if info.get("roi_source") != "faces":
        return 0.0
    size = info.get("source_size") or {}
    w, h = _f(size.get("width")), _f(size.get("height"))
    if not w or not h:
        return None
    parts = info.get("roi_parts") or [info.get("roi") or {}]
    best = max(((_f(p.get("width")) or 0) * (_f(p.get("height")) or 0) for p in parts),
               default=0.0)
    return round(best / (w * h), 4)


def source_finder(dirs=None):
    """`"<video id>:<shot n>" -> (mp4, start, end)` or None, off the pool's
    `shots.json` + `<id>.mp4` in `dirs` (the pool by default)."""
    dirs = [Path(d) for d in (still_share.footage_dirs() if dirs is None else dirs)]
    shots_of = still_share.shot_reader(dirs)

    def find(key):
        span = shots_of(key)
        if not span:
            return None
        vid = str(key).rsplit(":", 1)[0]
        for d in dirs:
            mp4 = d / f"{vid}.mp4"
            if mp4.exists():
                return str(mp4), span[0], span[1]
        return None
    return find


def measure_frame(shot, picture, find):
    """The `held_motion` reading of one held frame: `{"motion", "face_area",
    "at", "match", "shot_motion"}` (values None where unmeasurable)."""
    out = {"motion": None, "face_area": None, "at": None, "match": None,
           "shot_motion": None}
    if not picture or not Path(picture).exists():
        return out
    loc = find(shot) if shot else None
    if loc:
        got = source_motion(*loc, picture)
        if got:
            out.update(got)
    out["face_area"] = face_area(picture)
    return out


def _holder(plan, h):
    b = plan["blocks"][h["block"]]
    return b if h["cut"] is None else b["asset"]["cuts"][h["cut"]]


def _no_pool(_key):
    return None


def stamp(plan, base=None, dirs=None, measure=None):
    """Write `held_motion` onto every held frame of the plan that has no
    record of this measure yet. `measure(shot, picture) -> dict` is
    `measure_frame` against the pool (`dirs`) by default; `base` - the plan's
    work dir, where `clips/` lies. Returns how many were stamped."""
    if measure is None:
        find = source_finder(dirs)

        def measure(shot, picture):
            return measure_frame(shot, picture, find)
    n = 0
    for h in still_share.held_frames(plan, _no_pool):
        holder = _holder(plan, h)
        rec = holder.get(FIELD)
        if isinstance(rec, dict) and rec.get("measured_by") == MEASURED_BY:
            continue
        path = held_sharpness._resolve(h["src"], base)
        got = measure(holder.get("shot"), str(path) if path else None) or {}
        holder[FIELD] = {"task": TASK, "measured_by": MEASURED_BY,
                         "shot": holder.get("shot"), **got}
        n += 1
    return n


def frozen(motion, face):
    return bool(isinstance(motion, (int, float)) and motion >= MOTION_MIN
                and isinstance(face, (int, float)) and face >= FACE_MIN)


def record(plan):
    """The record of the plan's held frames (stamped ones; an unstamped
    frame reads as unmeasured):

        {"rule", "motion_min", "face_min", "allow_seconds", "frames": [{"block",
          "cut", "start", "end", "seconds", "shot", "motion", "face_area",
          "frozen"}], "frozen_seconds", "over_seconds", "units", "proposed",
          "proposed_penalty"}"""
    frames = []
    for h in still_share.held_frames(plan, _no_pool):
        rec = _holder(plan, h).get(FIELD)
        rec = rec if isinstance(rec, dict) and rec.get("measured_by") == MEASURED_BY else {}
        m, fa = rec.get("motion"), rec.get("face_area")
        frames.append({"block": h["block"], "cut": h["cut"],
                       "start": round(h["start"], 3), "end": round(h["end"], 3),
                       "seconds": round(max(0.0, h["end"] - h["start"]), 3),
                       "shot": rec.get("shot"), "motion": m, "face_area": fa,
                       "frozen": frozen(m, fa)})
    secs = round(sum(x["seconds"] for x in frames if x["frozen"]), 3)
    over = round(max(0.0, secs - ALLOW), 3)
    return {"task": TASK, "rule": RULE, "motion_min": MOTION_MIN, "face_min": FACE_MIN,
            "allow_seconds": ALLOW, "frames": frames, "frozen_seconds": secs,
            "over_seconds": over, "units": round(over, 2), "proposed": dict(PROPOSED),
            "proposed_penalty": round(-min(PROPOSED["cap"], over * PROPOSED["price"]), 2) or 0.0}


# ------------------------------------------------------------- the price

def mode(path=None):
    """`{"mode": penalty|warn, "price", "cap", "signed"}` for
    `score.held_moving_face` - only a row with the user's `signature` and a
    numeric price counts; anything else is `warn`."""
    path = path or held_sharpness.prices_path()
    rules = {}
    if path:
        try:
            data = json.loads(Path(path).read_text()) or {}
            rules = data.get("rules") or (data.get("score") or {}).get("rules") or {}
        except (OSError, ValueError, AttributeError):
            rules = {}
    row = rules.get(RULE)
    out = {"mode": MODE_WARN, "price": None, "cap": None, "signed": False}
    if held_sharpness._signed(row):
        pen = row.get("penalty") or {}
        price = pen.get("price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            out = {"mode": MODE_PENALTY, "price": price, "cap": pen.get("cap"),
                   "signed": True}
    return out


def findings(rec, mode_rec=None):
    """One score finding for the video (units = seconds of frozen motion
    over `ALLOW`, placed on the longest frozen frame) - only in `penalty`
    mode; `[]` while the row is not signed or nothing is over."""
    mode_rec = mode_rec or mode()
    if mode_rec.get("mode") != MODE_PENALTY or not rec.get("over_seconds"):
        return []
    try:
        import _score
    except Exception:  # noqa: BLE001
        return []
    top = max((x for x in rec["frames"] if x["frozen"]), key=lambda x: x["seconds"])
    return [_score.finding(
        RULE, {"block": top["block"], **({"cut": top["cut"]} if top["cut"] is not None else {}),
               "t": top["start"]},
        units=rec["over_seconds"], hook=_score.in_hook(top["start"]), source="metric",
        note=(f"{rec['frozen_seconds']:.2f} s of faces held still out of moving shots, "
              f"{rec['over_seconds']:.2f} s over {ALLOW:g} s (CF-0481)"))]


def describe(rec, mode_rec=None):
    """`held moving faces: 15.80 s (block 5 8.96 s motion 5.6 face 0.07, ...)
    - 3.80 s over 12 s, warn (unsigned), would cost -60.8 ...`."""
    fr = sorted((x for x in rec.get("frames") or [] if x["frozen"]),
                key=lambda x: -x["seconds"])
    if not fr:
        return (f"held moving faces: none ({len(rec.get('frames') or [])} held, "
                f"motion >= {MOTION_MIN:g} with a face >= {FACE_MIN:g})")
    parts = ", ".join(f"block {x['block']}{'' if x['cut'] is None else '.' + str(x['cut'])} "
                      f"{x['seconds']:.2f} s motion {x['motion']} face {x['face_area']}"
                      for x in fr)
    m = (mode_rec or {}).get("mode", MODE_WARN)
    if not rec["over_seconds"]:
        tail = f"within the {ALLOW:g} s allowed"
    elif m == MODE_PENALTY:
        tail = f"{rec['over_seconds']:.2f} s over {ALLOW:g} s, charged at the signed price"
    else:
        tail = (f"{rec['over_seconds']:.2f} s over {ALLOW:g} s, warn (unsigned), would cost "
                f"{rec['proposed_penalty']:g} at the proposed {PROPOSED['price']}/s "
                f"cap {PROPOSED['cap']}")
    return f"held moving faces: {rec['frozen_seconds']:.2f} s ({parts}) - {tail} ({RULE})"


def proposed_row():
    """The row this task proposes for `shared/gate-prices.json` - unsigned."""
    return {"what": "video", "mode": "penalty", "penalty": dict(PROPOSED),
            "detector": "auto",
            "note": (f"CF-0481: a face held still out of a moving shot - per held frame, the "
                     f"source shot's motion around the held moment (tile p95 of frame "
                     f"differences, +-{WINDOW:g} s) >= {MOTION_MIN:g} and the largest Vision "
                     f"face >= {FACE_MIN:g} of the picture; per second of such frames on "
                     f"screen over {ALLOW:g} s. Plan stage, agents/video-editor/scripts/"
                     f"held_motion.py. Measured 2026-10-02 on the acceptance log: "
                     f"vanguards-doomsday 1313Z 27.9 s (15.8 s after CF-0480), every accepted "
                     f"video <= 11.1 s (vanguards-endgame 0705Z)."),
            "signature": None}


def main(argv=None):
    """`held_motion.py PLAN [--row]` - measure (unless stamped) and print."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("plan", nargs="?")
    ap.add_argument("--footage", action="append", help="pool dir (default: the factory's)")
    ap.add_argument("--row", action="store_true", help="print the proposed price row")
    a = ap.parse_args(argv)
    if a.row:
        print(json.dumps({RULE: proposed_row()}, ensure_ascii=False, indent=2))
        return 0
    if not a.plan:
        ap.error("PLAN is required")
    plan = json.loads(Path(a.plan).read_text())
    stamp(plan, base=Path(a.plan).parent, dirs=a.footage)
    rec = record(plan)
    for x in rec["frames"]:
        print(f"  block {x['block']:>2} cut {str(x['cut']):>4} {x['seconds']:5.2f} s "
              f"{x['shot']} motion {x['motion']} face {x['face_area']} "
              f"{'FROZEN' if x['frozen'] else ''}")
    print(describe(rec, mode()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
