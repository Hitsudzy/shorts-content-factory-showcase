#!/usr/bin/env python3
"""CF-0674: the video's preview frame - `videos/<slug>.jpg` beside `videos/<slug>.mp4`.

The command centre's video API (root `api/videos.py`, CC-0012) shows a
preview of every video. Until this file it had only the frame judge's first
contact-sheet tile to show, and a video the judge never packed had none. The
Editor knows the finished picture better than anyone downstream, so it writes
one frame of it beside the mp4, and the API serves that file as is.

**Which frame.** The hook - what the viewer sees first, which is what a
preview is for - so the candidates are the first seconds of the video
(`CANDIDATES`, 0.6-2.6 s, every 0.4 s), tried in order of their distance from
`HOOK_AT` (1 s). A candidate is dropped when

  - it is under a card that hides the picture: an opaque insert, a comparison
    line's badge, the end card (`qc_render.cover_windows()` - the same
    reading the face gate uses, so "covered" means one thing in this repo);
  - it is at or past the end card's `start_s`, or in the last
    `TAIL_GUARD` seconds of the video (the fade out);
  - the frame is dark - mean luma under `qc_asset.MIN_MEAN_LUMA`, the floor
    QC already calls "too dark to see" (a black splice, a fade through black).

Of the rest, the sharpest wins by footage-indexer's frame sharpness
(`held_sharpness.frame_value()`, the same measure the blur gate reads); when
that measure is not there or says nothing, the one nearest 1 s wins. When the
first seconds have nothing to give, the rest of the video before the end card
is tried the same way, and when nothing at all is left no preview is written
(said, not refused: the API falls back to the judge's sheet).

**The file.** One frame of the FINISHED video (`qc_render.delivered_frame()`,
the one definition of "a frame of the render"), scaled to 720 x 1280, JPEG,
re-encoded at lower quality until it is at most `MAX_BYTES`. Written
atomically. When no frame can be had and a jpg of an OLDER render is there
(older than the mp4), it is removed - a preview of a different cut than the
mp4 it sits beside would be a lie.

**Where.** `write_batch_metadata.py`, per `--video`, straight after that
video's QC - the step every batch and every rebuild ends with
(docs/pipeline.md). A preview that cannot be made never costs the batch its
05-video-editor.json. **Only beside the batch's own video** (CF-0681): the
call writes (or removes) a jpg only for an mp4 that lies under the
`batch_dir` it records (`write_for_batch()`). A live monitor runs the same
`write_batch_metadata.py` on a temp copy of a shipped plan into a temp
`batch_dir` and hands it the REAL mp4 to read; before this rule it left
`videos/<slug>.jpg` in a live batch (2026-10-05T0701Z/harbourlights.jpg,
10.10). A batch and a rebuild always name `<batch>/videos/<slug>.mp4`
(CF-0246, `batch_layout`), so they write as before. `batch_layout.check()` counts only `*.mp4` in
`videos/`, the publisher's layout takes only `.mp4`/`.md`, the monthly
archive moves the whole batch - the jpg rides along with its mp4 everywhere.
"""
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

SUFFIX = ".jpg"
WIDTH, HEIGHT = 720, 1280
MAX_BYTES = 200_000
QUALITIES = (88, 82, 76, 70, 62, 54, 46)
HOOK_AT = 1.0
CANDIDATES = (0.6, 1.0, 1.4, 1.8, 2.2, 2.6)
LATER_STEP = 1.0          # the rest of the video, when the hook has nothing
TAIL_GUARD = 0.5          # never the last half second (the fade out)


def preview_path(mp4):
    """`videos/<slug>.jpg` for `videos/<slug>.mp4`."""
    return Path(mp4).with_suffix(SUFFIX)


def _num(x):
    return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) else None


def _limit(plan, seconds):
    """The last composition time a preview may come from: before the end card
    and the fade out."""
    limit = seconds - TAIL_GUARD
    card = (plan or {}).get("end_card")
    start = _num(card.get("start_s")) if isinstance(card, dict) else None
    if start is not None:
        limit = min(limit, start - 0.05)
    return limit


def covered(plan, at):
    """Is the picture at `at` under a card (insert, comparison line, end card)?"""
    import qc_render  # lazy: the whole QC module, only when a preview is made
    for block in (plan or {}).get("blocks") or []:
        s, e = _num(block.get("start")), _num(block.get("end"))
        if s is None or e is None or not (s <= at < e):
            continue
        try:
            windows = qc_render.cover_windows(block, plan)
        except Exception:  # noqa: BLE001 - a block the reader cannot parse covers nothing
            return False
        return any(ws <= at < we for ws, we in (c["window"] for c in windows))
    return False


def candidate_times(plan, seconds):
    """[(at, from_hook)] in the order they are tried: the hook's seconds by
    distance from HOOK_AT, then the rest of the video before the end card."""
    limit = _limit(plan, seconds)
    hook = sorted((t for t in CANDIDATES if t <= limit), key=lambda t: (abs(t - HOOK_AT), t))
    later, t = [], max(CANDIDATES) + LATER_STEP
    while t <= limit:
        later.append(round(t, 3))
        t += LATER_STEP
    return [t for t in hook if not covered(plan, t)], \
        [t for t in later if not covered(plan, t)]


def _luma(png):
    from PIL import Image
    from common import luma_pixels
    with Image.open(png) as im:
        px = luma_pixels(im.convert("L").resize((90, 160)))
    return sum(px) / len(px)


def _sharpness(png):
    try:
        import held_sharpness
        return held_sharpness.frame_value(png)
    except Exception:  # noqa: BLE001 - no measure: nearest the hook wins
        return None


def pick(video, plan, seconds, tmp, grab=None, sharp=None):
    """`{at, png, sharpness, luma, why}` of the chosen frame, or None."""
    import qc_render
    from qc_asset import MIN_MEAN_LUMA
    grab = grab or qc_render.delivered_frame
    sharp = sharp or _sharpness
    hook, later = candidate_times(plan, seconds)
    for group, label in ((hook, "hook"), (later, "later")):
        good = []
        for k, at in enumerate(group):
            png = grab(video, at, tmp, f"preview_{label}_{k}")
            if png is None:
                continue
            luma = _luma(png)
            if luma < MIN_MEAN_LUMA:
                continue
            good.append({"at": at, "png": Path(png), "luma": round(luma, 1),
                         "sharpness": sharp(png)})
            if label == "later":
                break       # past the hook the first usable frame is enough
        if not good:
            continue
        measured = [g for g in good if isinstance(g["sharpness"], (int, float))]
        if measured:
            best = max(measured, key=lambda g: g["sharpness"])
            best["why"] = f"{label}: sharpest of {len(good)} open, lit frame(s)"
        else:
            best = good[0]
            best["why"] = f"{label}: nearest {HOOK_AT:g} s of {len(good)} open, lit frame(s)"
        return best
    return None


def encode(png, dest):
    """`png` -> `dest` as a 720x1280 JPEG of at most MAX_BYTES; returns its size."""
    from PIL import Image
    dest = Path(dest)
    tmp = dest.with_name(f".{dest.name}.tmp")
    with Image.open(png) as im:
        im = im.convert("RGB")
        w, h = im.size
        # 9:16 whatever the render is: centre-crop to the aspect, then scale.
        if w * HEIGHT != h * WIDTH:
            if w * HEIGHT > h * WIDTH:
                nw = round(h * WIDTH / HEIGHT)
                im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
            else:
                nh = round(w * HEIGHT / WIDTH)
                im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im = im.resize((WIDTH, HEIGHT), Image.LANCZOS)
        for q in QUALITIES:
            im.save(tmp, "JPEG", quality=q, optimize=True, progressive=True)
            if tmp.stat().st_size <= MAX_BYTES:
                break
    os.replace(tmp, dest)
    return dest.stat().st_size


def write(mp4, plan_path, grab=None, sharp=None):
    """Write `videos/<slug>.jpg` for one rendered video.

    Returns `{path, at, bytes, why}` when written, `{path: None, reason}`
    when not. Never raises for a missing or unreadable video."""
    mp4 = Path(mp4)
    dest = preview_path(mp4)
    if not mp4.is_file():
        return {"path": None, "reason": f"no video at {mp4}"}
    try:
        plan = json.loads(Path(plan_path).read_text()) if plan_path else {}
    except (OSError, ValueError):
        plan = {}
    try:
        from common import media_duration
        seconds = media_duration(mp4)
    except Exception:  # noqa: BLE001 - an unreadable video has no preview
        seconds = 0.0
    chosen, err = None, None
    if seconds > 0:
        with tempfile.TemporaryDirectory() as tmp:
            try:
                chosen = pick(mp4, plan, seconds, tmp, grab=grab, sharp=sharp)
                if chosen is not None:
                    size = encode(chosen["png"], dest)
                    return {"path": str(dest), "at": chosen["at"], "bytes": size,
                            "why": chosen["why"]}
            except Exception as e:  # noqa: BLE001 - said by the caller, never fatal
                err = f"{type(e).__name__}: {e}"
    reason = err or ("the video has no readable duration" if seconds <= 0 else
                     "no open, lit frame before the end card")
    # A preview of an older render beside this mp4 shows a different cut.
    try:
        if dest.exists() and dest.stat().st_mtime < mp4.stat().st_mtime:
            dest.unlink()
            reason += f"; stale {dest.name} removed"
    except OSError:
        pass
    return {"path": None, "reason": reason}


def _inside(path, root):
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def write_for_batch(batch_dir, mp4, plan_path, grab=None, sharp=None):
    """`write()` for the video of the batch `batch_dir` - or nothing at all.

    CF-0681: an mp4 outside `batch_dir` belongs to another batch (a live
    monitor recording into a temp dir reads a real batch's mp4), and its
    `videos/` is not this call's to write: returns `{path: None, skipped:
    True, reason}` and touches no file. An mp4 under `batch_dir` is
    `write()` exactly."""
    batch = Path(batch_dir).resolve()
    video = Path(mp4).resolve()
    if not _inside(video, batch):
        return {"path": None, "skipped": True,
                "reason": f"{mp4} is not under the batch {batch_dir} - a preview is "
                          f"written only beside the batch's own video (CF-0681)"}
    return write(mp4, plan_path, grab=grab, sharp=sharp)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) not in (1, 2) or argv[0].startswith("-"):
        print("usage: video_preview.py <videos/slug.mp4> [<work/slug/plan.json>]",
              file=sys.stderr)
        return 2
    got = write(argv[0], argv[1] if len(argv) > 1 else None)
    print(json.dumps(got, ensure_ascii=False))
    return 0 if got.get("path") else 1


if __name__ == "__main__":
    sys.exit(main())
