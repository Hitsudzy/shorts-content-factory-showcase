#!/usr/bin/env python3
"""CF-0403: the foreground of one still meme, cut out by macOS Vision.

    <video-editor venv python> scripts/meme_cutout_vision.py SRC OUT.png [--grid N]

Runs under Video Editor's venv - the one interpreter in the factory with
pyobjc Vision/Quartz, Pillow and numpy (the same venv the indexer's warm
Vision worker runs under). It is called by `scripts/meme_desk.py cutout`,
which runs under the system python3 and does not import any of this.

Vision's `VNGenerateForegroundInstanceMaskRequest` (macOS 14+) returns every
foreground instance it sees; all of them are kept - a meme with two people
is cut as two people. The mask is soft (0..1); it becomes the alpha channel
as is. OUT.png is the source cropped to the silhouette's bounding box, RGBA,
written only when the mask is not empty. Local, no network.

Prints one JSON object on stdout:
    size       [w, h] of the source
    instances  how many foreground instances Vision returned
    coverage   fraction of the frame under the silhouette (alpha >= 0.5)
    bbox       [x, y, w, h] of the silhouette in source pixels, or null
    soft       fraction of the silhouette's pixels with 0.1 < alpha < 0.9
    grid       the thresholded mask downsampled to at most N px on the long
               side, as rows of "0"/"1" - what meme_desk.py judges the cut on
    out        OUT path, or null when nothing was written
Exit 0 with this JSON whenever Vision answered, even with an empty mask - the
judgement belongs to the caller. Non-zero only when the file cannot be read
or Vision itself failed.
"""
import argparse
import json
import sys

GRID = 96


def vision_mask(path):
    """(alpha float32 HxW in 0..1, instance count) for the image at path."""
    import numpy as np
    import Quartz
    import Vision
    from Foundation import NSURL

    url = NSURL.fileURLWithPath_(str(path))
    handler = Vision.VNImageRequestHandler.alloc().initWithURL_options_(url, {})
    req = Vision.VNGenerateForegroundInstanceMaskRequest.alloc().init()
    ok, err = handler.performRequests_error_([req], None)
    if not ok:
        raise SystemExit(f"Vision request failed: {err}")
    results = req.results() or []
    if not results:
        return None, 0
    obs = results[0]
    inst = obs.allInstances()
    n = inst.count()
    if n == 0:
        return None, 0
    buf, err = obs.generateScaledMaskForImageForInstances_fromRequestHandler_error_(
        inst, handler, None)
    if buf is None:
        raise SystemExit(f"Vision mask failed: {err}")
    Quartz.CVPixelBufferLockBaseAddress(buf, 0)
    try:
        w = Quartz.CVPixelBufferGetWidth(buf)
        h = Quartz.CVPixelBufferGetHeight(buf)
        stride = Quartz.CVPixelBufferGetBytesPerRow(buf)
        base = Quartz.CVPixelBufferGetBaseAddress(buf)
        raw = bytes(base.as_buffer(stride * h))
    finally:
        Quartz.CVPixelBufferUnlockBaseAddress(buf, 0)
    rows = np.frombuffer(raw, dtype=np.float32).reshape(h, stride // 4)
    return np.clip(rows[:, :w].copy(), 0.0, 1.0), n


def grid_rows(solid, n=GRID):
    """The boolean mask as at most n px on the long side, '0'/'1' rows. A
    cell is foreground when at least half of the pixels it covers are."""
    import numpy as np
    h, w = solid.shape
    scale = max(h, w) / n if max(h, w) > n else 1.0
    gh, gw = max(1, round(h / scale)), max(1, round(w / scale))
    ys = np.linspace(0, h, gh + 1).astype(int)
    xs = np.linspace(0, w, gw + 1).astype(int)
    out = []
    for i in range(gh):
        band = solid[ys[i]:max(ys[i + 1], ys[i] + 1)]
        out.append("".join("1" if band[:, xs[j]:max(xs[j + 1], xs[j] + 1)].mean() >= 0.5 else "0"
                           for j in range(gw)))
    return out


def describe(src, out_png, alpha, instances, grid=GRID):
    """The JSON record for a mask, writing the cropped RGBA to out_png when
    the mask is not empty. Split from vision_mask() so a test can feed a
    synthetic mask."""
    import numpy as np
    from PIL import Image
    img = Image.open(src).convert("RGB")
    w, h = img.size
    rec = {"size": [w, h], "instances": instances, "coverage": 0.0, "bbox": None,
           "soft": 0.0, "grid": [], "out": None}
    if alpha is None:
        rec["grid"] = ["0" * min(w, grid)]
        return rec
    if alpha.shape != (h, w):
        alpha = np.asarray(Image.fromarray((alpha * 255).astype("uint8")).resize((w, h)),
                           dtype=np.float32) / 255.0
    solid = alpha >= 0.5
    rec["coverage"] = round(float(solid.mean()), 4)
    rec["grid"] = grid_rows(solid, grid)
    if not solid.any():
        return rec
    fg = alpha > 0.1
    rec["soft"] = round(float(((alpha > 0.1) & (alpha < 0.9)).sum() / max(1, fg.sum())), 4)
    ys, xs = np.nonzero(fg)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()) + 1, int(ys.min()), int(ys.max()) + 1
    rec["bbox"] = [x0, y0, x1 - x0, y1 - y0]
    rgba = np.dstack([np.asarray(img), (alpha * 255).round().astype("uint8")])
    Image.fromarray(rgba[y0:y1, x0:x1], "RGBA").save(out_png, optimize=True)
    rec["out"] = str(out_png)
    return rec


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("src")
    ap.add_argument("out")
    ap.add_argument("--grid", type=int, default=GRID)
    a = ap.parse_args(argv)
    alpha, n = vision_mask(a.src)
    print(json.dumps(describe(a.src, a.out, alpha, n, a.grid)))


if __name__ == "__main__":
    sys.exit(main())
