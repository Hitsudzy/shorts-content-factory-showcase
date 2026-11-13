#!/usr/bin/env python3
"""CF-0646: what a held / long picture looks like ON SCREEN - a thin strip, a
body with its head out of frame, a soft source stretched and held.

The user's review of `example-film/2026-10-08T1824Z` (2026-10-09): two videos
carried pictures every automatic check had passed -

* rink-rivals 21 s (block 8): a 2.39:1 frame (1920x804) held still 5.03 s,
  shown whole on its blurred frame (`blur_fill`, CF-0436) because a 9:16 crop
  would have kept 27 % of its subject - so on screen a strip 23.5 % of the
  height, and in it only skates and legs: the players' heads are out of the
  source frame itself;
* delver 12 / 18 s (blocks 5 and 7): frames of `wIM1PDRvKSE` (a 1620x1080
  picture with no native detail - it keeps nearly all of its finest detail
  through a half-scale round trip) held still, cropped to 9:16 and stretched
  x1.78 (+ the still's Ken Burns) - soap on screen.

Why nothing caught them: `blur_fill` takes the picture out of every "is the
subject cut" gate (contain = whole) and nothing asked how thin the picture
then is; `roi_coverage` is not judged for a contained picture; CF-0465
measures the held PNG at SOURCE scale (block 7 reads 0.601, over its 0.53
floor - block 5 at 0.524 was caught and charged, -11.75, and the video still
passed); the indexer's per-shot `low_sharpness` never ran on these old-pool
shots (CF-0410). Nothing measured the picture at the scale it is shown.

**Three readings, stamped onto the held frame's block / cut** (`held_screen`,
while the picture is there - CF-0358) **and one from the plan's geometry**:

* `share` - the picture's height on screen over the screen's (contain /
  `blur_fill`: the fitted picture; cover: 1.0). From the plan, no pixels.
* `screen_sharpness` - the indexer's frame sharpness (blur effect, p90 of
  tiles, CF-0452) of the delivered 9:16 window resized to the size it is
  shown at: "soft after stretching" as one number.
* `retention` - how much of its finest detail (laplacian energy of the
  sharpest tenth of tiles) the picture keeps through a half-scale round trip
  at its own resolution. A sharp native picture loses most of it (0.10-0.30);
  an upscaled / smeared source keeps most (0.36+): "a soapy source".
* `bodies` / `headless` / `faces` - macOS Vision's human body pose on the
  delivered picture: a body whose leg joints are found and none of its head
  joints (head, neck, eyes, ears) is a person with the head out of frame.

**The rules (calibrated 2026-10-09 on 11 videos, 217 pictures: the batch
1824Z, 0701Z's rejected delver, and the accepted vanguards-doomsday 1824Z,
vanguards-endgame / east-of-eden / harbourlights 0701Z, delver 1427Z, delver /
rennick / coach-hale 1313Z):**

* `score.thin_picture` - a picture under `THIN_SHARE` of the screen's height
  held still, or on screen `LONG_SECONDS` or more. 2.39:1 reads 0.235, 2:1
  0.281, 16:9 0.317. Catches rink-rivals block 8; the thinnest accepted
  held / long picture is 0.281 (east-of-eden 0701Z block 12, 3.32 s).
  CF-0650 (2026-10-10): a contained clip that barely moves is a held
  picture to the eye. The rebuild 2026-10-09T1208Z's first pass (and 1824Z)
  showed rink-rivals block 7, `UcIvQYYW4PY:4` (16:9 shown whole: 0.317),
  standing nearly still for 3.64 s - the frame judge threw it out
  (`thin_strip`), this rule passed it. A candidate (contained, under
  `CANDIDATE_SHARE`, on screen `LONG_SECONDS`+) has its `motion` read the
  frame judge's way (`clip_motion`: grey frames `MOTION_STEP` s apart over
  the block's window, the median of the pairs' mean absolute difference,
  stamped as `screen_motion`); under `MOTION_STILL` it breaks the rule under
  `STILL_SHARE`. Calibrated on the same accepted videos plus 1208Z: the
  still clip reads 2.27; the operator's second pick `cFP-IWif0wc:39` 33.18,
  1208Z block 9 19.55, the accepted delver 1427Z clips 6.98 / 7.19 (the
  slowest accepted contained clip of 3 s or more); the accepted near-still
  clips (east-of-eden 0701Z block 10, 3.73, 2.47 s; harbourlights 0701Z blocks
  2 / 11 / 28, 0.9-2.8, under 1.8 s) are all under 3 s. A held frame keeps
  `THIN_SHARE`: east-of-eden 0701Z's 2:1 frame held 3.32 s is accepted.
* `score.held_cut_subject` - a held frame whose delivered picture shows a
  headless body and no face. Fires on rink-rivals block 8 alone of the 217.
* `score.held_soft_stretch` - a held cover frame on screen `SOFT_SECONDS` or
  more reading under `SCREEN_FLOOR` at screen scale from a source that keeps
  `RETENTION_FROM` or more of its detail. Catches delver 1824Z blocks 5 and 7
  and both held frames the user named in 0701Z's delver (wIM1PDRvKSE:34,
  :37); no accepted held frame (the nearest: rennick 1313Z block 6, 0.477 on
  screen but 0.358 retention; vanguards-doomsday block 15, 0.517 / 0.24).
  A moving soft clip (delver block 9, ZLXL1L0TfsI:19) is NOT separable this
  way - the accepted vanguards-doomsday block 1 reads the same - and is left
  to the frame judge.

**The price: none until the user signs one (CF-0320).** `mode()` reads
`shared/gate-prices.json` per rule: only a row with the user's `signature`
and a numeric penalty makes it a charge; otherwise the record says `warn`,
the plan carries it and a note, and nothing is charged. `PROPOSED` is what
the report proposes; this repo never writes a row.
"""
import json
import sys
import tempfile
from pathlib import Path

import still_share

TASK = "CF-0646"
FIELD = "held_screen"
MEASURED_BY = "CF-0646/screen-window-crete+halfscale-retention+bodypose/v1"
SCREEN = (1080, 1920)

RULE_THIN = "score.thin_picture"
RULE_CUT = "score.held_cut_subject"
RULE_SOFT = "score.held_soft_stretch"
RULES = (RULE_THIN, RULE_CUT, RULE_SOFT)

THIN_SHARE = 0.25      # picture height / screen height
LONG_SECONDS = 3.0     # a thin moving picture this long is a thin picture too
# CF-0650: a clip that barely moves is a held picture to the eye. Its motion
# is the frame judge's reading - grey frames MOTION_STEP s apart over the
# block's window, the median of the consecutive pairs' mean absolute
# difference (letterbox rows dropped). Measured only on the candidates: a
# contained picture under CANDIDATE_SHARE on screen LONG_SECONDS or more.
STILL_SHARE = 0.33     # a still clip under it (16:9 shown whole reads 0.317)
MOTION_STILL = 4.5     # grey levels; under it the clip stands still
MOTION_STEP = 0.5      # seconds between the compared frames
CANDIDATE_SHARE = 0.4
MOTION_FIELD = "screen_motion"
MOTION_TASK = "CF-0650"
MOTION_BY = "CF-0650/clip-window-0.5s-pair-mean-absdiff-median/v1"
MOTION_GRID = (192, 108)
MOTION_BAR_LUMA = 8.0
SOFT_SECONDS = 2.0     # a soft stretched frame held at least this long
SCREEN_FLOOR = 0.53    # screen-scale sharpness under it is soft
RETENTION_FROM = 0.36  # detail kept through the half-scale round trip
HELD_SOFT_FLOOR = 0.53  # held_sharpness.FLOOR (CF-0465), read without importing it

HEAD_JOINTS = ("head_joint", "neck_1_joint", "left_eye_joint", "right_eye_joint",
               "left_ear_joint", "right_ear_joint")
LEG_JOINTS = ("left_leg_joint", "right_leg_joint", "left_foot_joint",
              "right_foot_joint", "left_upLeg_joint", "right_upLeg_joint")
JOINT_CONFIDENCE = 0.3

# Proposals (unsigned). Per second for the two "how long it stands there"
# rules (the soft stretch at CF-0465's signed 5/s, the same defect read at
# screen scale), per case for the cut subject. On the batch: rink-rivals
# 87 -> 47 (-25 thin, -15 cut), delver 63.71 -> 49.16 (block 7, -14.55);
# no accepted video of the calibration loses a point.
PROPOSED = {
    RULE_THIN: {"price": 5, "per": "second", "cap": 25, "hook_mult": None},
    RULE_CUT: {"price": 15, "per": "case", "cap": 30, "hook_mult": None},
    RULE_SOFT: {"price": 5, "per": "second", "cap": 25, "hook_mult": None},
}
MODE_PENALTY = "penalty"
MODE_WARN = "warn"
PRICES_REL = Path("shared") / "gate-prices.json"


def _f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


# ------------------------------------------------------------ geometry

def picture_share(target, screen=SCREEN):
    """The picture's height on screen over the screen's: a `blur_fill` rect's
    height, a contained picture fitted whole, 1.0 for a cover crop (and for
    a target the plan does not size)."""
    target = target or {}
    rect = ((target.get("presentation") or {}).get("blur_fill") or {}).get("rect")
    if isinstance(rect, dict) and _f(rect.get("height")):
        return round(min(1.0, _f(rect["height"]) / screen[1]), 3)
    if target.get("fit") == "contain":
        ss = target.get("source_size") or {}
        w, h = _f(ss.get("width")), _f(ss.get("height"))
        if w and h:
            s = min(screen[0] / w, screen[1] / h)
            return round(min(1.0, h * s / screen[1]), 3)
    return 1.0


# ------------------------------------------------------------ the measures

def _sharpness():
    try:
        import shot_score
        return shot_score.sharpness_module()
    except Exception:  # noqa: BLE001 - no indexer: nothing measured
        return None


def _gray(path):
    from PIL import Image
    return Image.open(str(path)).convert("L")


def screen_window(img, target, screen=SCREEN):
    """The delivered window of `img` (a PIL image of the source), resized to
    the size it stands on screen at - what the viewer sees, minus Ken Burns."""
    import smart_crop
    from PIL import Image
    ss = (target or {}).get("source_size") or {}
    size = (int(ss.get("width") or img.size[0]), int(ss.get("height") or img.size[1]))
    if img.size != size:
        img = img.resize(size, Image.BICUBIC)
    focus = (target or {}).get("focus") or {"x": 0.5, "y": 0.5}
    fit = "contain" if (target or {}).get("fit") == "contain" else "cover"
    x, y, cw, ch = smart_crop.delivered_window(
        size, (focus.get("x", 0.5), focus.get("y", 0.5)),
        (target or {}).get("zoom") or 1.0, screen[0], screen[1], fit)
    crop = img.crop((int(x), int(y), int(round(x + cw)), int(round(y + ch))))
    s = min(screen[0] / cw, screen[1] / ch) if fit == "contain" else screen[1] / ch
    return crop.resize((max(1, round(cw * s)), max(1, round(ch * s))), Image.BICUBIC)


def screen_sharpness(img, target, screen=SCREEN):
    """The indexer's frame sharpness of the picture as shown, or None."""
    mod = _sharpness()
    if mod is None:
        return None
    import numpy as np
    try:
        return mod.frame_sharpness(np.asarray(screen_window(img, target, screen),
                                              np.float32))[0]
    except Exception:  # noqa: BLE001 - an unreadable picture measures nothing
        return None


def _lap2(a):
    return (-4 * a[1:-1, 1:-1] + a[:-2, 1:-1] + a[2:, 1:-1]
            + a[1:-1, :-2] + a[1:-1, 2:]) ** 2


def retention(img, tile=96, min_std=8.0, pct=10):
    """Laplacian energy the picture keeps through a half-scale round trip
    (Lanczos down, bicubic up) at its own resolution: the `pct`-th percentile
    over the tiles with detail (std >= `min_std`), i.e. its sharpest tiles.
    Letterbox bars trimmed. None when fewer than 4 tiles carry detail."""
    import numpy as np
    from PIL import Image
    g = np.asarray(img, np.float32)
    mod = _sharpness()
    if mod is not None and hasattr(mod, "_trim_bars"):
        g = mod._trim_bars(g)
    h, w = g.shape
    if h < tile + 2 or w < tile + 2:
        return None
    small = Image.fromarray(g.astype(np.uint8)).resize(
        (max(1, w // 2), max(1, h // 2)), Image.LANCZOS)
    back = np.asarray(small.resize((w, h), Image.BICUBIC), np.float32)
    la, lb = _lap2(g), _lap2(back)
    ny, nx = la.shape[0] // tile, la.shape[1] // tile

    def tiles(a):
        return a[:ny * tile, :nx * tile].reshape(ny, tile, nx, tile)
    ea, eb = tiles(la).sum(axis=(1, 3)), tiles(lb).sum(axis=(1, 3))
    sd = tiles(g[1:-1, 1:-1]).std(axis=(1, 3))
    keep = (sd >= min_std) & (ea > 0)
    if int(keep.sum()) < 4:
        return None
    return round(float(np.percentile((eb / np.maximum(ea, 1e-6))[keep], pct)), 3)


def body_pose(path):
    """`{"bodies", "headless", "faces"}` from macOS Vision on the picture at
    `path`, or None where Vision cannot be reached (another OS, no pyobjc).
    A body is headless when a leg joint is found and no head joint is."""
    try:
        import Vision
        import smart_crop
        img = smart_crop.load_cgimage(str(path))
        handler = Vision.VNImageRequestHandler.alloc().initWithCGImage_options_(img, None)
        pose = Vision.VNDetectHumanBodyPoseRequest.alloc().init()
        face = Vision.VNDetectFaceRectanglesRequest.alloc().init()
        import vision_compute  # CF-0711: CPU on an Intel Mac, never the iGPU
        vision_compute.pin_all([pose, face])
        ok = handler.performRequests_error_([pose, face], None)
        if isinstance(ok, tuple):
            ok = ok[0]
        if not ok:
            return None
        bodies = headless = 0
        for o in pose.results() or []:
            pts, _err = o.recognizedPointsForJointsGroupName_error_(
                Vision.VNHumanBodyPoseObservationJointsGroupNameAll, None)
            seen = {str(k) for k, v in (pts or {}).items()
                    if v.confidence() > JOINT_CONFIDENCE}
            bodies += 1
            if seen & set(LEG_JOINTS) and not seen & set(HEAD_JOINTS):
                headless += 1
        return {"bodies": bodies, "headless": headless,
                "faces": len(face.results() or [])}
    except Exception:  # noqa: BLE001 - no Vision: nothing found, nothing claimed
        return None


def measure(path, target, pose=None):
    """The three pixel readings of the held picture at `path` shown as
    `target` (its block's asset / its cut): `{"screen_sharpness",
    "retention", "bodies", "headless", "faces"}` (None where unreadable).
    `pose(path) -> dict|None` is `body_pose` by default."""
    pose = pose or body_pose
    out = {"screen_sharpness": None, "retention": None,
           "bodies": None, "headless": None, "faces": None}
    if not path or not Path(path).exists():
        return out
    try:
        img = _gray(path)
    except Exception:  # noqa: BLE001
        return out
    out["screen_sharpness"] = screen_sharpness(img, target)
    try:
        out["retention"] = retention(img)
    except Exception:  # noqa: BLE001
        out["retention"] = None
    try:
        from PIL import Image
        shown = screen_window(Image.open(str(path)).convert("RGB"), target)
        with tempfile.TemporaryDirectory(prefix="cf0646-") as tmp:
            p = Path(tmp) / "shown.png"
            shown.save(p)
            got = pose(str(p))
    except Exception:  # noqa: BLE001
        got = None
    if isinstance(got, dict):
        out.update({k: got.get(k) for k in ("bodies", "headless", "faces")})
    return out


# ------------------------------------------------------------ the plan

def _holder(plan, h):
    b = plan["blocks"][h["block"]]
    return b if h["cut"] is None else b["asset"]["cuts"][h["cut"]]


def _target(plan, h):
    b = plan["blocks"][h["block"]]
    if h["cut"] is None:
        return b.get("asset") or {}
    return b["asset"]["cuts"][h["cut"]]


def _resolve(src, base):
    if not src:
        return None
    p = Path(src)
    if p.exists() or base is None:
        return p
    q = Path(base) / "clips" / p.name
    return q if q.exists() else p


def _no_pool(_key):
    return None


def stamp(plan, measure_fn=None, base=None):
    """Write `held_screen` onto every held frame of the plan that has no
    record of this measure yet. `measure_fn(path, target) -> dict` is
    `measure` by default. Returns how many were stamped."""
    measure_fn = measure_fn or measure
    n = 0
    for h in still_share.held_frames(plan, _no_pool):
        holder = _holder(plan, h)
        rec = holder.get(FIELD)
        if isinstance(rec, dict) and rec.get("measured_by") == MEASURED_BY:
            continue
        path = _resolve(h["src"], base)
        got = measure_fn(str(path), _target(plan, h)) if path else {}
        holder[FIELD] = {"task": TASK, "measured_by": MEASURED_BY,
                         **{k: (got or {}).get(k) for k in
                            ("screen_sharpness", "retention", "bodies",
                             "headless", "faces")},
                         "src": str(path) if path else None}
        n += 1
    return n


# ------------------------------------------------------------ motion (CF-0650)

def frames_motion(frames):
    """`{"motion", "max", "pairs"}` of grey frames `(n, h, w)` sampled
    MOTION_STEP apart: the median (and the largest) of the consecutive pairs'
    mean absolute difference over the lit rows; None under two frames."""
    import numpy as np
    if frames is None or len(frames) < 2:
        return None
    f = np.asarray(frames, np.float32)
    lit = np.where(f.mean(axis=(0, 2)) > MOTION_BAR_LUMA)[0]
    if len(lit):
        f = f[:, int(lit[0]):int(lit[-1]) + 1]
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    return {"motion": round(float(np.median(d)), 2), "max": round(float(d.max()), 2),
            "pairs": int(len(d))}


def clip_motion(src, start, seconds):
    """`frames_motion` of the clip `src` from `start` for `seconds` (the
    window the block shows), or None when it cannot be read."""
    import subprocess
    import numpy as np
    if not src or not Path(src).exists() or not seconds or seconds <= 0:
        return None
    w, h = MOTION_GRID
    try:
        raw = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{max(0.0, start or 0.0):.3f}",
             "-t", f"{seconds:.3f}", "-i", str(src), "-vf",
             f"fps={1 / MOTION_STEP:g},scale={w}:{h},format=gray",
             "-f", "rawvideo", "-"], capture_output=True, timeout=60).stdout
    except Exception:  # noqa: BLE001 - an unreadable clip measures nothing
        return None
    n = len(raw) // (w * h)
    if n < 2:
        return None
    return frames_motion(np.frombuffer(raw[: n * w * h], np.uint8).reshape(n, h, w))


def _motion_candidate(target, seconds):
    """A picture whose stillness can break `score.thin_picture`: contained /
    on its blurred frame, under CANDIDATE_SHARE, on screen LONG_SECONDS+."""
    return (seconds >= LONG_SECONDS and picture_share(target) < CANDIDATE_SHARE
            and (target.get("fit") == "contain"
                 or ((target.get("presentation") or {}).get("blur_fill") or {}).get("rect")))


def _motion_holder(plan, i, ci):
    b = plan["blocks"][i]
    return b if ci is None else b["asset"]["cuts"][ci]


def _motion_of(plan, i, ci, s, e, target, motion_fn=None, base=None):
    """The candidate's motion record: the stamp when there is one, else
    measured now (`motion_fn(src, start, seconds)`, `clip_motion` default)."""
    rec = _motion_holder(plan, i, ci).get(MOTION_FIELD)
    if isinstance(rec, dict) and rec.get("measured_by") == MOTION_BY:
        return rec
    path = _resolve(target.get("src"), base)
    got = (motion_fn or clip_motion)(str(path) if path else None,
                                     _f(target.get("start_seconds")) or 0.0, e - s)
    return {"task": MOTION_TASK, "measured_by": MOTION_BY,
            **{k: (got or {}).get(k) for k in ("motion", "max", "pairs")},
            "src": str(path) if path else None}


def stamp_motion(plan, motion_fn=None, base=None):
    """Write `screen_motion` onto every candidate moving picture (block /
    cut) without one yet, while the clip is there (CF-0358). Returns how
    many were stamped."""
    n = 0
    for i, ci, s, e, target in _moving_pictures(plan):
        if not _motion_candidate(target, round(e - s, 3)):
            continue
        holder = _motion_holder(plan, i, ci)
        rec = holder.get(MOTION_FIELD)
        if isinstance(rec, dict) and rec.get("measured_by") == MOTION_BY:
            continue
        holder[MOTION_FIELD] = _motion_of(plan, i, ci, s, e, target, motion_fn, base)
        n += 1
    return n


def _moving_pictures(plan):
    """Every picture on screen that is not a held frame: `(block, cut, start,
    end, target)` - a block's clip, a sequence's moving cuts."""
    for i, b in enumerate(plan.get("blocks") or []):
        s, e = _f(b.get("start")), _f(b.get("end"))
        if s is None or e is None or e <= s:
            continue
        a = b.get("asset") or {}
        if a.get("kind") == "clip" and not b.get("held_frame"):
            yield i, None, s, e, a
        elif a.get("kind") == "sequence":
            t = s
            for ci, c in enumerate(a.get("cuts") or []):
                sec = _f(c.get("seconds")) or 0.0
                if not c.get("held_frame") and c.get("kind") != "still":
                    yield i, ci, t, min(e, t + sec), c
                t += sec


def _where(x):
    return f"block {x['block']}" + ("" if x["cut"] is None else f".{x['cut']}")


def record(plan, measure_fn=None, motion_fn=None, base=None):
    """The plan's record: every held frame with its readings and the rules
    it breaks, the thin moving pictures (CF-0650: with the motion of the
    candidates - `motion_fn(src, start, seconds)`, `clip_motion` default,
    read from the `screen_motion` stamp when there is one), the candidates
    read and left (`motion_read`), and the findings
    `[{"rule", "block", "cut", "start", "end", "seconds", "why"}]`."""
    frames, found, moving_read = [], [], []
    for h in still_share.held_frames(plan, _no_pool):
        holder, target = _holder(plan, h), _target(plan, h)
        rec = holder.get(FIELD)
        if not (isinstance(rec, dict) and rec.get("measured_by") == MEASURED_BY):
            rec = (measure_fn or measure)(h["src"], target) if h["src"] else {}
        sec = round(max(0.0, h["end"] - h["start"]), 3)
        share = picture_share(target)
        x = {"block": h["block"], "cut": h["cut"], "start": round(h["start"], 3),
             "end": round(h["end"], 3), "seconds": sec, "share": share,
             "fit": target.get("fit"),
             **{k: (rec or {}).get(k) for k in ("screen_sharpness", "retention",
                                                 "bodies", "headless", "faces")}}
        x["rules"] = []
        if share < THIN_SHARE:
            x["rules"].append(RULE_THIN)
            found.append({"rule": RULE_THIN, **_span(x),
                          "why": f"held picture {share:.0%} of the screen's height "
                                 f"(< {THIN_SHARE:.0%}) for {sec:.2f} s"})
        if (x["headless"] or 0) > 0 and not (x["faces"] or 0):
            x["rules"].append(RULE_CUT)
            found.append({"rule": RULE_CUT, **_span(x),
                          "why": f"held picture shows {x['headless']} body(ies) "
                                 f"with the head out of frame and no face"})
        ss, rt = x["screen_sharpness"], x["retention"]
        # one defect is not charged twice: a frame CF-0465 already finds soft
        # at source scale (`score.held_soft_frame`) is its, not this rule's
        hs = (holder.get("held_sharpness") or {}).get("value")
        x["held_soft_frame"] = bool(isinstance(hs, (int, float)) and hs < HELD_SOFT_FLOOR)
        if (target.get("fit") != "contain" and sec >= SOFT_SECONDS
                and not x["held_soft_frame"]
                and isinstance(ss, (int, float)) and ss < SCREEN_FLOOR
                and isinstance(rt, (int, float)) and rt >= RETENTION_FROM):
            x["rules"].append(RULE_SOFT)
            found.append({"rule": RULE_SOFT, **_span(x),
                          "why": f"held {sec:.2f} s at {ss} on screen (< {SCREEN_FLOOR}) "
                                 f"from a source keeping {rt} of its detail at half "
                                 f"scale (>= {RETENTION_FROM})"})
        frames.append(x)
    thin = []
    for i, ci, s, e, target in _moving_pictures(plan):
        share = picture_share(target)
        sec = round(e - s, 3)
        mo = (_motion_of(plan, i, ci, s, e, target, motion_fn, base)
              if _motion_candidate(target, sec) else None)
        motion = (mo or {}).get("motion")
        still = isinstance(motion, (int, float)) and motion < MOTION_STILL
        if sec >= LONG_SECONDS and (share < THIN_SHARE or (still and share < STILL_SHARE)):
            x = {"block": i, "cut": ci, "start": round(s, 3), "end": round(e, 3),
                 "seconds": sec, "share": share, "motion": motion, "still": still}
            thin.append(x)
            why = (f"picture {share:.0%} of the screen's height (< {THIN_SHARE:.0%}) "
                   f"for {sec:.2f} s") if share < THIN_SHARE else (
                   f"clip standing nearly still (frame-to-frame {motion} < "
                   f"{MOTION_STILL:g} at {MOTION_STEP:g} s steps) as a picture "
                   f"{share:.0%} of the screen's height (< {STILL_SHARE:.0%}) "
                   f"for {sec:.2f} s ({MOTION_TASK})")
            found.append({"rule": RULE_THIN, **_span(x), "why": why})
        elif mo is not None:
            moving_read.append({"block": i, "cut": ci, "seconds": sec, "share": share,
                                "motion": motion, "still": still})
    return {"task": TASK, "measured_by": MEASURED_BY,
            "thresholds": {"thin_share": THIN_SHARE, "long_seconds": LONG_SECONDS,
                           "soft_seconds": SOFT_SECONDS, "screen_floor": SCREEN_FLOOR,
                           "retention_from": RETENTION_FROM,
                           "still_share": STILL_SHARE, "motion_still": MOTION_STILL,
                           "motion_step": MOTION_STEP},
            "motion_measured_by": MOTION_BY,
            "frames": frames, "thin_moving": thin, "motion_read": moving_read,
            "findings": found,
            "proposed": {r: dict(p) for r, p in PROPOSED.items()}}


def _span(x):
    return {"block": x["block"], "cut": x["cut"], "start": x["start"],
            "end": x["end"], "seconds": x["seconds"]}


# ------------------------------------------------------------- the price

def _signed(row):
    sig = (row or {}).get("signature")
    return isinstance(sig, dict) and bool(sig.get("user")) and bool(sig.get("date"))


def prices_path():
    try:
        import _score
        root = _score.factory_root()
    except Exception:  # noqa: BLE001
        root = None
    return root / PRICES_REL if root else None


def mode(path=None):
    """`{rule: {"mode": penalty|warn, "price", "cap", "per", "signed"}}` for
    the three rules. Only a row with the user's `signature` and a numeric
    penalty price counts; anything else is `warn`."""
    path = path or prices_path()
    rules = {}
    if path:
        try:
            rules = (json.loads(Path(path).read_text()) or {}).get("rules") or {}
        except (OSError, ValueError, AttributeError):
            rules = {}
    out = {}
    for rule in RULES:
        row = rules.get(rule)
        m = {"mode": MODE_WARN, "price": None, "cap": None, "per": None, "signed": False}
        if _signed(row):
            pen = row.get("penalty") or {}
            price = pen.get("price")
            if isinstance(price, (int, float)) and not isinstance(price, bool):
                m = {"mode": MODE_PENALTY, "price": price, "cap": pen.get("cap"),
                     "per": pen.get("per"), "signed": True}
        out[rule] = m
    return out


def findings(rec, modes=None):
    """Score findings for the rules the table charges (signed rows only):
    units = seconds on screen for a per-second rule, 1 otherwise."""
    modes = modes or mode()
    try:
        import _score
    except Exception:  # noqa: BLE001
        return []
    out = []
    for f in rec.get("findings") or []:
        m = modes.get(f["rule"]) or {}
        if m.get("mode") != MODE_PENALTY:
            continue
        per = m.get("per") or PROPOSED[f["rule"]]["per"]
        units = f["seconds"] if "second" in str(per) else 1
        out.append(_score.finding(
            f["rule"], {"block": f["block"],
                        **({"cut": f["cut"]} if f["cut"] is not None else {}),
                        "t": f["start"]},
            units=units, hook=_score.in_hook(f["start"]), source="metric",
            note=f"{_where(f)}: {f['why']} ({TASK})"))
    return out


def describe(rec, modes=None):
    """One line: what was found and whether it is charged."""
    fs = rec.get("findings") or []
    if not fs:
        return (f"held/long pictures on screen: nothing thin, cut or soft "
                f"({len(rec.get('frames') or [])} held) ({TASK})")
    modes = modes or {}
    parts = []
    for f in fs:
        m = (modes.get(f["rule"]) or {}).get("mode", MODE_WARN)
        parts.append(f"{_where(f)} {f['rule']} [{m}{'' if m == MODE_PENALTY else ', unsigned'}]"
                     f" - {f['why']}")
    return f"held/long pictures on screen ({TASK}): " + "; ".join(parts)


def proposed_rows():
    """The rows this task proposes for `shared/gate-prices.json` - unsigned."""
    base = ("Plan stage, agents/video-editor/scripts/held_screen.py. Calibrated "
            "2026-10-09 on 11 videos / 217 pictures (batch 2026-10-08T1824Z, "
            "0701Z's rejected delver, 8 accepted videos of 1313Z/0701Z/1427Z/1824Z).")
    notes = {
        RULE_THIN: (f"CF-0646: a picture under {THIN_SHARE:.0%} of the screen's height "
                    f"(a 2.39:1 frame shown whole on its blurred frame) held still, or "
                    f"moving for {LONG_SECONDS:g} s or more; per second on screen. "
                    f"rink-rivals 1824Z block 8 (0.235, 5.03 s held); the thinnest "
                    f"accepted held/long picture 0.281. CF-0650: a contained clip "
                    f"standing nearly still (median frame-to-frame difference at "
                    f"{MOTION_STEP:g} s steps under {MOTION_STILL:g} grey levels) for "
                    f"{LONG_SECONDS:g} s or more counts under {STILL_SHARE:.0%} - "
                    f"rink-rivals 1824Z / 1208Z block 7 (UcIvQYYW4PY:4, 0.317, 2.27); "
                    f"the slowest accepted contained clip of 3 s+ reads 6.98. "),
        RULE_CUT: ("CF-0646: a held frame whose delivered picture shows a body with "
                   "leg joints and no head joint (macOS Vision body pose) and no face "
                   "- a person with the head out of frame; per case. rink-rivals "
                   "1824Z block 8 alone of 217 pictures. "),
        RULE_SOFT: (f"CF-0646: a held cover frame on screen {SOFT_SECONDS:g} s or more "
                    f"reading under {SCREEN_FLOOR} at screen scale (indexer blur effect "
                    f"p90 of the delivered window resized to its screen size) from a "
                    f"source keeping >= {RETENTION_FROM} of its finest detail through a "
                    f"half-scale round trip; per second; not a frame score.held_soft_frame "
                    f"already charges. delver 1824Z block 7 (block 5 is held_soft_frame's) and "
                    f"0701Z's wIM1PDRvKSE:34/:37 holds; no accepted held frame. "),
    }
    return {r: {"what": "block", "mode": "penalty", "penalty": dict(PROPOSED[r]),
                "detector": "auto", "note": notes[r] + base, "signature": None}
            for r in RULES}


# ------------------------------------------------------------- calibration

def main(argv=None):
    """`held_screen.py PLAN.json ...` - the readings of every held frame and
    every thin moving picture of each plan, measured now (read-only: nothing
    is written back), one line each, and the findings."""
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("plans", nargs="+")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    out = {}
    for p in args.plans:
        plan = json.loads(Path(p).read_text())
        base = Path(p).parent

        def fn(src, target, _base=base):
            return measure(str(_resolve(src, _base)), target)
        rec = record(plan, measure_fn=fn, base=base)
        out[p] = rec
        if args.json:
            continue
        print(f"== {p}")
        for x in rec["frames"]:
            print(f"  {_where(x):10} held {x['seconds']:5.2f}s {x['fit'] or '':7} "
                  f"share={x['share']:.3f} screen={x['screen_sharpness']} "
                  f"retention={x['retention']} bodies={x['bodies']} "
                  f"headless={x['headless']} faces={x['faces']} "
                  f"{','.join(x['rules'])}")
        for x in rec["thin_moving"]:
            print(f"  {_where(x):10} moving {x['seconds']:5.2f}s share={x['share']:.3f} "
                  f"motion={x.get('motion')} THIN")
        for x in rec.get("motion_read") or []:
            print(f"  {_where(x):10} moving {x['seconds']:5.2f}s share={x['share']:.3f} "
                  f"motion={x.get('motion')}")
        for f in rec["findings"]:
            print(f"  FINDING {_where(f)} {f['rule']}: {f['why']}")
    if args.json:
        print(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
