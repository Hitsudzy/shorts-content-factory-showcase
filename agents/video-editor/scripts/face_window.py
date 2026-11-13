#!/usr/bin/env python3
"""CF-0535: the face window is chosen over the span the block shows, by what
the block says - not off one frame at 0.5 s.

`weekend-night-live` of `example-film/2026-10-05T0701Z`, block 5 (23.20-30.13
s, `KTe9OatvQas:5`, "The woman in the red dress stands on stage beside another
woman..."): the 9:16 window sat on two WNL band members for seven seconds and
the host was outside it. What Vision saw: at the probe frame (0.5 s into the
clip) the host is turned away from the camera, so the only faces in the frame
are the band's - two small faces (98 and 79 px of a 736 px frame) at x
1364-1635, which fit one window together, so the union was framed (focus x
0.781). From ~2 s on the host turns round: her face is the largest in the
frame (179 px, centre of the frame) - but the render holds the framing taken
off the probe frame for the whole clip (build_render_plan.framing()), so
nothing that happens after 0.5 s is ever looked at. The CF-0292 rule (largest
face, near-ties by the centre) was not wrong - it was asked about one frame
where the heroine has no face.

**The mechanism.** For a `faces` clip the planner looks at a few more frames
across the span the block actually shows (`SPAN_POINTS` of it, besides the
probe), takes each frame's own framing (smart_crop.analyse, the same rules) as
a candidate window, and keeps the distinct ones. When there is only one, the
plan is as before. When there are several, the one chosen is:

1. the window whose picture matches the block's `intent` - CLIP cosine of the
   window cut out of every sampled frame against the intent text, averaged
   over the frames (the window is held the whole block, so it is judged on the
   whole block), when it leads every other candidate by `CLIP_MARGIN`;
2. otherwise, among the candidates within `CLIP_MARGIN` of the best (all of
   them when CLIP is unavailable or the block has no intent), the one holding
   the largest face seen across the span - CF-0292's rule asked about the
   span, not about one frame - with near-ties (`FACE_TIE_RATIO`) left on the
   probe's own framing, so a shot that was framed fine does not move on noise.

**The check (warn, no price - CF-0320).** The chosen window's CLIP score
against the intent is set beside the uncropped frame's: a window that scores
`WARN_GAP` or more below the whole frame has cut away what the block talks
about (the hero does not fit a 9:16 window - the case for a wide plan or
another shot, CF-0292/0294). It is recorded on the asset (`face_window`) and
in the plan's notes; nothing is charged and nothing is refused until the user
signs a price (`PROPOSED`).

Pure Python apart from clip_similarity(), which loads CLIP (torch /
transformers) lazily - smart_crop's model, shared through its globals.
"""
import re

import smart_crop

TASK = "CF-0535"
FIELD = "face_window"
RULE = "plan.face_window_off_intent"
# Where in the shown span the extra frames are taken, as fractions of it.
SPAN_POINTS = (0.3, 0.6, 0.9)
# Two sampled frames closer than this (s) are one frame.
MIN_GAP_SECONDS = 0.25
# Two windows are the same candidate when they share at least this share of
# the window's width (the window is always the full source height or a zoom
# of it - the horizontal position is the choice).
SAME_WINDOW_OVERLAP = 0.5
# CLIP lead (cosine) one window needs over every other to be chosen on the
# intent alone. WNL 0701Z block 5: host window 0.228 vs band window 0.211
# (mean of 4 frames) - 0.017; single-frame differences of B/32 on one picture
# run to ~0.005 either way, so the margin is twice that.
CLIP_MARGIN = 0.01
FACE_TIE_RATIO = smart_crop.FACE_TIE_RATIO
# The check: the window scores this much below the uncropped frame.
WARN_GAP = 0.03
PROPOSED = {"price": None, "note": "warn only until the user signs a price"}

_SUFFIX = re.compile(r"\s*\(shot \d+, score [0-9.]+\)\s*$")


def intent_text(intent):
    """The block's intent without the resolver's `(shot N, score X)` tail."""
    return _SUFFIX.sub("", intent or "").strip()


def span_offsets(asset_start, shown_seconds, clip_seconds, probe_offset):
    """Clip-time offsets to sample: the probe first, then `SPAN_POINTS` of the
    span the block shows (capped at the clip's own length - a stretched clip
    shows no more of itself than it has)."""
    span = shown_seconds or 0.0
    if clip_seconds:
        span = min(span, max(0.0, clip_seconds - asset_start))
    probe = asset_start + probe_offset
    out = [probe]
    for f in SPAN_POINTS:
        t = asset_start + span * f
        if clip_seconds:
            t = min(t, max(0.0, clip_seconds - 0.05))
        if all(abs(t - o) >= MIN_GAP_SECONDS for o in out):
            out.append(round(t, 3))
    return out


def window_of(info, aspect_w, aspect_h, fit="cover"):
    """The source rectangle the render shows for `info`'s own framing."""
    size = info["source_size"]
    return smart_crop.delivered_window(
        (size["width"], size["height"]), smart_crop.focus_point(info),
        info.get("zoom", 1.0), aspect_w, aspect_h, fit)


def _faces(info):
    if info.get("roi_source") != "faces":
        return []
    parts = info.get("roi_parts") or [info["roi"]]
    return [(p["x"], p["y"], p["width"], p["height"]) for p in parts]


def _overlap(a, b):
    lo, hi = max(a[0], b[0]), min(a[0] + a[2], b[0] + b[2])
    return max(0.0, hi - lo) / min(a[2], b[2]) if min(a[2], b[2]) else 0.0


def candidates(frames, aspect_w, aspect_h):
    """Distinct windows out of `frames` = [(t, path, info)]: the probe's
    first, then every frame whose own `faces` framing is a different window."""
    out = []
    for t, _path, info in frames:
        if not info or info.get("roi_source") != "faces" or "roi" not in info:
            continue
        win = window_of(info, aspect_w, aspect_h)
        if any(_overlap(win, c["window"]) >= SAME_WINDOW_OVERLAP for c in out):
            continue
        out.append({"t": t, "info": info, "window": win})
    return out


def largest_face_in(window, frames):
    """Area of the largest face, over every sampled frame, whose centre lies
    inside `window`."""
    best = 0.0
    for _t, _path, info in frames:
        for x, y, w, h in _faces(info or {}):
            cx, cy = x + w / 2, y + h / 2
            if (window[0] <= cx <= window[0] + window[2]
                    and window[1] <= cy <= window[1] + window[3]):
                best = max(best, w * h)
    return best


def clip_similarity(paths, windows, text):
    """CLIP cosine of `text` against each window of each picture - `[[cos per
    window] per path]`. A window is (x, y, w, h) in source pixels, or None for
    the whole picture. The model is smart_crop's (classify_animated), loaded
    once per process and shared through its module globals - smart_crop.py
    itself is not touched, its code is in the usability cache's key
    (cache_fingerprint.py)."""
    import torch
    from PIL import Image
    from transformers import CLIPModel, CLIPProcessor
    if smart_crop._CLIP_MODEL is None:
        smart_crop._CLIP_MODEL = CLIPModel.from_pretrained(
            smart_crop.CLIP_MODEL_NAME).eval()
        smart_crop._CLIP_PROC = CLIPProcessor.from_pretrained(
            smart_crop.CLIP_MODEL_NAME)
    model, proc = smart_crop._CLIP_MODEL, smart_crop._CLIP_PROC
    crops = []
    for path in paths:
        image = Image.open(path).convert("RGB")
        for win in windows:
            crops.append(image if win is None else image.crop(
                (int(win[0]), int(win[1]), int(win[0] + win[2]),
                 int(win[1] + win[3]))))
    with torch.no_grad():
        te = model.get_text_features(**proc(text=[text], return_tensors="pt",
                                            padding=True, truncation=True))
        ie = model.get_image_features(**proc(images=crops, return_tensors="pt"))
    te = te / te.norm(dim=-1, keepdim=True)
    ie = ie / ie.norm(dim=-1, keepdim=True)
    sims = (ie @ te.T)[:, 0].tolist()
    n = len(windows)
    return [sims[k * n:(k + 1) * n] for k in range(len(paths))]


def clip_scores(frames, windows, text):
    """Mean CLIP cosine of each window (cut out of every frame) against
    `text`, plus the uncropped frames' mean as the last element; None when
    CLIP is unavailable."""
    try:
        sims = clip_similarity(
            [path for _t, path, _i in frames], list(windows) + [None], text)
    except Exception:  # noqa: BLE001 - no CLIP: the face rule decides
        return None
    return [round(sum(col) / len(col), 4) for col in zip(*sims)] if sims else None


def choose(cands, faces, scores):
    """Index of the chosen candidate and why: `intent` (CLIP lead),
    `face` (largest face among the CLIP near-ties), or `probe`."""
    n = len(cands)
    if n < 2:
        return 0, "probe"
    pool = list(range(n))
    if scores:
        best = max(pool, key=lambda k: scores[k])
        rest = [scores[k] for k in pool if k != best]
        if scores[best] - max(rest) >= CLIP_MARGIN:
            return best, "intent"
        pool = [k for k in pool if scores[best] - scores[k] < CLIP_MARGIN]
    big = max(pool, key=lambda k: faces[k])
    if 0 in pool and faces[0] >= faces[big] * FACE_TIE_RATIO:
        return 0, "probe"
    return big, ("face" if big != 0 else "probe")


def reframe(frames, intent, aspect_w, aspect_h, score=clip_scores):
    """The record for one `faces` clip: `frames` = [(t, path, info)] with the
    probe first. Returns None when there is nothing to choose and nothing to
    check (no faces on the probe, or one window and no intent)."""
    cands = candidates(frames, aspect_w, aspect_h)
    if not cands or cands[0]["t"] != frames[0][0]:
        return None
    text = intent_text(intent)
    faces = [largest_face_in(c["window"], frames) for c in cands]
    # One window: the check alone is asked, on the probe frame (a CLIP pass
    # per frame is most of this module's cost and there is nothing to choose).
    scored = frames if len(cands) > 1 else frames[:1]
    scores = score(scored, [c["window"] for c in cands], text) if text else None
    full = None
    if scores:
        scores, full = scores[:-1], scores[-1]
    k, by = choose(cands, faces, scores)
    chosen = cands[k]
    gap = (round(full - scores[k], 4)
           if scores is not None and full is not None else None)
    info = chosen["info"]
    return {
        "task": TASK,
        "probes": [t for t, _p, _i in frames],
        "candidates": [{"t": c["t"],
                        "focus": dict(zip("xy", smart_crop.focus_point(c["info"]))),
                        "zoom": c["info"].get("zoom", 1.0),
                        "largest_face": round(f),
                        "clip": None if scores is None else scores[j]}
                       for j, (c, f) in enumerate(zip(cands, faces))],
        "chosen": k,
        "by": by,
        "moved": k != 0,
        "info": info,
        "clip_full": full,
        "gap": gap,
        "verdict": "warn" if gap is not None and gap >= WARN_GAP else "ok",
        "mode": "warn",
    }


def public(rec):
    """The record as it goes into the plan (without the chosen frame's
    analyse() dict)."""
    return {k: v for k, v in rec.items() if k != "info"}


def describe(i, rec):
    """Plan notes for block `i`."""
    out = []
    c = rec["candidates"]
    if rec["moved"]:
        a, b = c[0], c[rec["chosen"]]
        out.append(
            f"block {i}: face window moved off the probe frame's framing "
            f"(focus x {a['focus']['x']:.3f}, largest face {a['largest_face']} px2, "
            f"CLIP {a['clip']}) to the one at {b['t']:.2f}s (focus x "
            f"{b['focus']['x']:.3f}, largest face {b['largest_face']} px2, CLIP "
            f"{b['clip']}) - by {rec['by']} ({TASK})")
    if rec["verdict"] == "warn":
        out.append(
            f"block {i}: the face window scores {rec['gap']:.3f} below the whole "
            f"frame against the intent (CLIP) - the window may cut away what the "
            f"block describes; warn only, no price ({RULE}, {TASK})")
    return out
