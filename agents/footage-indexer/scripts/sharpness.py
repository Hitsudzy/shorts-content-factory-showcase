#!/usr/bin/env python3
"""How sharp a shot is - a smeared shot named, and ranked below a sharp one
(CF-0452, 2026-10-01).

The user rejected `kaijura-minus-zero` of batch `example-film/2026-09-30T1248Z`
(acceptance log, `blurry_footage`): "плохо подобранные кадры, много
смазанного материала". The usability bundle of CF-0435 measured framing,
brightness and resolution and nothing about focus, so a soft shot of the
behind-the-scenes featurette `xiEmt197Bk8` ranked exactly like a crisp one.

**The measure.** A few frames of the shot (`FRAMES`, spread over its span),
each read in grey at the source's own resolution with the short side capped at
`SCALE` (a 4K source is brought down to what the video shows; a 720p source is
*not* blown up - `low_resolution` already charges that, and one defect is not
charged twice), the letterbox bars trimmed. Each frame is cut into tiles
(`TILES_ACROSS` across the short side); a tile flat enough to say nothing about
focus (`MIN_TILE_STD`) is skipped. On every other tile the frame is compared
with a box-blurred copy of itself - the no-reference "blur effect" of Crete et
al. (2007): a sharp tile loses much of its pixel-to-pixel variation when
blurred again, a smeared one hardly any. The tile's sharpness is the *smaller*
of its vertical and horizontal readings, so a smear along one direction (motion
blur) counts. The frame's sharpness is the `PERCENTILE`-th percentile of its
tiles: the sharpest part of the picture, so a subject in focus in front of a
blurred background (the cinematic shallow focus of `wolfhame`, accepted) reads
sharp, and a frame with nothing in focus reads soft. 0.0 is mush, ~0.9 is a
crisp graphic; real footage sits between ~0.45 and ~0.85.

**Intentional motion.** Each sampled frame is read with its next frame; the
mean absolute difference between them (`motion`, grey levels) says whether the
picture is moving there. A soft frame of a moving shot is motion blur the
viewer's eye follows in a *clip*, and it is excused there (`motion_excused`);
the same frame *held* on screen is a smeared still, and `at()` - the reading of
one moment, for a held frame - never excuses it.

**Where it is stored.** `shot["sharpness_cached"]` (see `measure()`), stamped
with `MEASURED_BY`; a record taken by another version of this measure is not
read (`is_fresh`). It is a field of its own, not a key of `usable_cached`:
that cache is fingerprinted by the bytes of `usability_probe.py` (CF-0048), and
touching it would mark every index of the pool stale.

**Nothing old is re-measured** (CF-0410, the pool is transient). New material
is measured when `index_footage.py` writes its index; a shot of the old pool
that reaches a plan is measured on the fly by whoever needs it -
`measure(video, start, end)` for a shot, `at(video, t)` for the one frame a
held still shows - and `shot_usability` judges a shot without the field as
unmeasured for this rule, never sends it to be measured.

**Price: none until the user signs one (CF-0320).** `mode()` reads
`shared/gate-prices.json`: a *signed* row `score.low_sharpness` makes the rule
soft at the row's price; without it the shot carries a `low_sharpness` entry
in `usability.warn[]` with `signed: false` and keeps its score. The Editor may
still rank a warned shot below a clean one (a ranking, not a price). The code
never writes that row.
"""
import json
import subprocess
from pathlib import Path


TASK = "CF-0452"
RULE = "low_sharpness"
FIELD = "sharpness_cached"
PRICE_KEY = f"score.{RULE}"
# Bump when the measure changes: a record stamped otherwise is not read.
MEASURED_BY = "CF-0452/crete-tiles-p90/v1"

FFMPEG = "/usr/local/opt/ffmpeg-full/bin/ffmpeg"
FFPROBE = "/usr/local/opt/ffmpeg-full/bin/ffprobe"

SCALE = 1080          # short side cap of the analysed frame (the video's width)
FRAMES = 5            # frames per shot (on the fly, `measure()`)
INDEX_FRAMES = 3      # frames per shot at indexing (~1 s a shot of 1080p)
EDGE = 0.1            # first/last sample this far into the shot (of its span)
TILES_ACROSS = 11     # tiles across the short side (96 px at 1080)
MIN_TILE_STD = 6.0    # a flatter tile says nothing about focus
MIN_TILES = 4         # fewer informative tiles: the frame is not judged
PERCENTILE = 90       # the frame's sharpness: its sharpest tenth
BLUR_TAPS = 9         # the re-blur of the blur-effect measure
MOTION_EXCUSED = 6.0  # mean |frame - next frame| above this: moving picture

# The floor, read off the accepted side and not off the rejected one
# (`measure_sharpness.py`, 2026-10-01): the 5th percentile of what the viewer
# got on screen in accepted videos - 70 distinct shots of day-drinker,
# wolfhame, backrooms (1248Z), harbourlights, vanguards-endgame (0705Z), paper-dragon,
# you-can-see-everything (1722Z), held frames and non-moving clips - is 0.568.
# Under it: 4 of those 70, and 2 of the 13 distinct shots of the rejected
# kaijura-minus-zero (xiEmt197Bk8:41 held at 0.509 mid-motion, :44 at 0.557).
# The measure finds the tail, not the whole video: kaijura's other held
# frames (0.58-0.74) sit inside the accepted range (held 0.52-0.89).
MIN_SHARPNESS = 0.57

MODE_PENALTY = "penalty"
MODE_WARN = "warn"
# The price proposed to the user; nothing charges it until a signed row does.
PROPOSED_PRICE = {"price": 3, "per": "shot", "cap": 12, "hook_mult": None}

def _fi_paths():
    """CF-0620: this directory's `_fi_paths.py`, loaded by path - video-editor's
    `shot_score` loads this module by path with the indexer's scripts/ not on
    sys.path, so a plain `import _fi_paths` would fail there."""
    import importlib.util
    path = Path(__file__).resolve().with_name("_fi_paths.py")
    spec = importlib.util.spec_from_file_location("_fi_paths", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# CF-0620: the price table of the factory this checkout belongs to (a version
# worktree's own, or FACTORY_ROOT's), not the home checkout's.
PRICES_FILE = _fi_paths().prices_file()


# ---------------------------------------------------------------- the metric

def _np():
    """numpy, imported when a frame is actually measured: `shot_usability`
    imports this module for `verdict()`/`mode()`, and every writer of an index
    imports `shot_usability` - they need no numpy for that."""
    import numpy
    return numpy


def _trim_bars(g):
    """The frame without its letterbox/pillarbox: rows and columns that are
    both dark and flat are bars."""
    np = _np()
    rows = np.where((g.mean(1) > 20) | (g.std(1) > 8))[0]
    cols = np.where((g.mean(0) > 20) | (g.std(0) > 8))[0]
    if len(rows) < 32 or len(cols) < 32:
        return g
    return g[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]


def _box(g, axis, taps=BLUR_TAPS):
    """Box blur of `taps` along one axis, same shape, edges repeated."""
    np = _np()
    n = taps // 2
    g = g if axis == 0 else g.T
    p = np.pad(g, [(n + 1, n), (0, 0)], mode="edge")
    p[0] = 0.0
    c = np.cumsum(p, axis=0, dtype=np.float32)
    out = (c[taps:] - c[:-taps]) / taps
    return out if axis == 0 else out.T


def _tile_sums(a, t):
    np = _np()
    ny, nx = a.shape[0] // t, a.shape[1] // t
    return a[:ny * t, :nx * t].reshape(ny, t, nx, t).sum(axis=(1, 3))


def frame_sharpness(gray):
    """`(sharpness, tiles)` of one grey frame (2-D array, 0..255): the
    `PERCENTILE`-th percentile of the per-tile blur-effect sharpness, and how
    many tiles were informative. `(None, n)` when fewer than `MIN_TILES`
    tiles carry any detail (a black frame, a flat card)."""
    np = _np()
    g = _trim_bars(np.asarray(gray, dtype=np.float32))
    short = min(g.shape)
    t = max(16, short // TILES_ACROSS)
    if g.shape[0] < t + 2 or g.shape[1] < t + 2:
        return None, 0
    out = []
    for axis in (0, 1):
        d = np.abs(np.diff(g, axis=axis))
        db = np.abs(np.diff(_box(g, axis), axis=axis))
        v = np.maximum(0.0, d - db)
        # back to the frame's shape so the tiles line up on both axes
        d = np.pad(d, [(0, 1) if a == axis else (0, 0) for a in (0, 1)])
        v = np.pad(v, [(0, 1) if a == axis else (0, 0) for a in (0, 1)])
        sd, sv = _tile_sums(d, t), _tile_sums(v, t)
        with np.errstate(invalid="ignore", divide="ignore"):
            out.append(np.where(sd > 0, sv / sd, np.nan))
    std = g[:(g.shape[0] // t) * t, :(g.shape[1] // t) * t].reshape(
        g.shape[0] // t, t, g.shape[1] // t, t).std(axis=(1, 3))
    s = np.minimum(out[0], out[1])
    s = s[(std >= MIN_TILE_STD) & np.isfinite(s)]
    if s.size < MIN_TILES:
        return None, int(s.size)
    return round(float(np.percentile(s, PERCENTILE)), 4), int(s.size)


def motion(a, b):
    """Mean absolute grey difference between two consecutive frames."""
    np = _np()
    if a is None or b is None or np.shape(a) != np.shape(b):
        return None
    return round(float(np.abs(np.asarray(a, np.float32)
                              - np.asarray(b, np.float32)).mean()), 2)


# ------------------------------------------------------------- the frames

def _size(video):
    r = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=width,height", "-of",
                        "csv=p=0", str(video)], capture_output=True, text=True,
                       timeout=60)
    w, h = (int(x) for x in r.stdout.strip().splitlines()[0].split(",")[:2])
    return w, h


def _analysis_size(w, h, scale=SCALE):
    short = min(scale, w, h)
    if w >= h:
        return int(round(w * short / h / 2) * 2), short
    return short, int(round(h * short / w / 2) * 2)


def read_frames(video, times, pairs=True, scale=SCALE):
    """`{t: (frame, next_frame|None)}` grey arrays at the analysis size, one
    ffmpeg for all the times (each an input of its own, seeked fast). A time
    ffmpeg cannot read is left out."""
    np = _np()
    video = str(video)
    w, h = _size(video)
    nw, nh = _analysis_size(w, h, scale)
    per = 2 if pairs else 1
    cmd = [FFMPEG, "-v", "error", "-nostdin"]
    for t in times:
        cmd += ["-ss", f"{max(0.0, float(t)):.3f}", "-i", video]
    parts = []
    for i in range(len(times)):
        parts.append(f"[{i}:v]scale={nw}:{nh},format=gray,"
                     f"trim=end_frame={per},setpts=N/TB[o{i}]")
    parts.append("".join(f"[o{i}]" for i in range(len(times)))
                 + f"concat=n={len(times)}:v=1:a=0[out]")
    # passthrough + a frame count: without them the concat's timestamps make
    # ffmpeg duplicate frames up to the output rate and read on to the end
    cmd += ["-filter_complex", ";".join(parts), "-map", "[out]",
            "-fps_mode", "passthrough", "-frames:v", str(len(times) * per),
            "-f", "rawvideo", "-pix_fmt", "gray", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=240).stdout
    size = nw * nh
    frames = [np.frombuffer(raw[i * size:(i + 1) * size], np.uint8)
              .reshape(nh, nw) for i in range(len(raw) // size)]
    out = {}
    if len(frames) == len(times) * per:
        for i, t in enumerate(times):
            f = frames[i * per]
            out[t] = (f, frames[i * per + 1] if pairs else None)
        return out
    # a short read (a time past the end, a broken stretch): one by one
    for t in times:
        if len(times) == 1:
            break
        one = read_frames(video, [t], pairs, scale)
        out.update(one)
    return out


def sample_times(start, end, n=FRAMES, edge=EDGE):
    d = max(0.0, float(end) - float(start))
    if n <= 1 or d <= 0:
        return [round(float(start) + d / 2, 3)]
    a, b = float(start) + d * edge, float(end) - d * edge
    return [round(a + (b - a) * i / (n - 1), 3) for i in range(n)]


# ------------------------------------------------------------- the record

def judge(readings):
    """The record from `[(t, sharpness|None, motion|None), ...]`."""
    rs = [(t, s, m) for t, s, m in readings if s is not None]
    if not rs:
        return {"task": TASK, "measured_by": MEASURED_BY, "value": None,
                "frames": [[t, s, m] for t, s, m in readings],
                "floor": MIN_SHARPNESS}
    vals = sorted(s for _, s, _ in rs)
    value = vals[len(vals) // 2] if len(vals) % 2 else round(
        (vals[len(vals) // 2 - 1] + vals[len(vals) // 2]) / 2, 4)
    best_t, best, _ = max(rs, key=lambda r: r[1])
    moves = [m for _, _, m in rs if m is not None]
    mot = sorted(moves)[len(moves) // 2] if moves else None
    return {"task": TASK, "measured_by": MEASURED_BY, "value": value,
            "best": best, "best_at": best_t, "motion": mot,
            "motion_excused": bool(mot is not None and mot >= MOTION_EXCUSED),
            "frames": [[t, s, m] for t, s, m in readings],
            "floor": MIN_SHARPNESS}


def measure(video, start, end, n=FRAMES):
    """The `sharpness_cached` record of the span `[start, end]` of `video`:

        {"task", "measured_by",
         "value":   median frame sharpness (None: nothing to judge),
         "best", "best_at":  the sharpest sampled frame and its time -
                    the moment to hold if the shot is held as a still,
         "motion":  median motion of the samples, "motion_excused": bool,
         "frames":  [[t, sharpness, motion], ...], "floor": MIN_SHARPNESS}

    One ffmpeg per call. Raises nothing it can help: an unreadable video gives
    `value: None`."""
    times = sample_times(start, end, n)
    try:
        got = read_frames(video, times)
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        got = {}
    readings = []
    for t in times:
        f, nxt = got.get(t, (None, None))
        s = frame_sharpness(f)[0] if f is not None else None
        readings.append((t, s, motion(f, nxt)))
    return judge(readings)


def at(video, t):
    """The sharpness of the one frame at `t` - what a held still shows.
    Same record shape as `measure()`; `motion_excused` is always False (a
    held frame does not move, so its smear is not excused)."""
    rec = measure(video, t, t, n=1)
    rec["motion_excused"] = False
    return rec


def of_shot(shot, video, n=FRAMES):
    """`measure()` over the shot's own `start`/`end`."""
    return measure(video, shot["start"], shot["end"], n)


def stamp(shot, video, n=FRAMES):
    """Measure one shot and write `shot[FIELD]`; returns the record."""
    rec = of_shot(shot, video, n)
    shot[FIELD] = rec
    return rec


def is_fresh(rec):
    return isinstance(rec, dict) and rec.get("measured_by") == MEASURED_BY


def verdict(rec, held=False, floor=None):
    """None when the record says nothing against the shot, else
    `{"rule": "low_sharpness", "value", "floor", "held"}`. A clip whose soft
    frames move (`motion_excused`) is excused; a held frame never is."""
    if not is_fresh(rec):
        return None
    value = rec.get("value")
    floor = MIN_SHARPNESS if floor is None else floor
    if not isinstance(value, (int, float)) or value >= floor:
        return None
    if rec.get("motion_excused") and not held:
        return None
    return {"rule": RULE, "value": value, "floor": floor, "held": bool(held)}


# ------------------------------------------------------------- the price

def _signed(row):
    sig = (row or {}).get("signature")
    return isinstance(sig, dict) and bool(sig.get("user")) and bool(sig.get("date"))


_MODES = {}


def mode(path=None, refresh=False):
    """`{"mode": penalty|warn, "price": n|None, "price_key", "signed"}` - what
    the signed price table says about `score.low_sharpness`. Only a row with
    the user's `signature` counts (CF-0320); anything else is `warn`."""
    key = str(path or PRICES_FILE)
    if key in _MODES and not refresh:
        return _MODES[key]
    try:
        rules = (json.loads(Path(key).read_text()) or {}).get("rules") or {}
    except (OSError, ValueError):
        rules = {}
    out = {"mode": MODE_WARN, "price": None, "price_key": PRICE_KEY,
           "signed": False}
    row = rules.get(PRICE_KEY)
    if _signed(row):
        price = (row.get("penalty") or {}).get("price")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            out = {"mode": MODE_PENALTY, "price": price,
                   "price_key": PRICE_KEY, "signed": True}
    _MODES[key] = out
    return out


def proposed_row():
    """The row this task proposes for `shared/gate-prices.json` - unsigned;
    the user signs it (or not). Printed by `measure_sharpness.py --row`."""
    return {"what": "shot", "mode": "penalty", "penalty": dict(PROPOSED_PRICE),
            "detector": "auto",
            "note": (f"CF-0452: a smeared shot - the sharpest tenth of the "
                     f"picture (p90 of its tiles, median over the frames) under "
                     f"{MIN_SHARPNESS} (blur effect, 0 mush .. 1 "
                     f"crisp; footage-indexer/scripts/sharpness.py). A soft "
                     f"clip that moves is excused (motion blur), a held frame "
                     f"never is."),
            "signature": None}
