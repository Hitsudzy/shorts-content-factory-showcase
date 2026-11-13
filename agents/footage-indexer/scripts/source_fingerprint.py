#!/usr/bin/env python3
"""Content fingerprint of a source, so a re-upload is recognised before it is
indexed a second time (CF-0080).

Search returns the same trailer under several `video_id`s - other channels'
re-uploads - and `ingest_batch.py` used to fetch and index every one of them:
shot detection, CLIP, Vision descriptions, all over again on footage that had
been indexed minutes earlier under another id. In the 2026-09-03T2037Z batch
that was a good part of a 3h19m indexing window, and worse, the "sources"
count lied to every gate that counts sources (the two-source gate, alternate's
footage_sides()) - three ids, one piece of footage.

The fingerprint is deliberately cheap and deliberately not a shot index: one
dHash (8x8 bits from a 9x8 grey thumbnail) per sampled frame, SAMPLE_FPS times
a second, over at most MAX_SECONDS of the file, plus the mean luma of that
thumbnail so black frames - fades, leaders, cards' backgrounds - can be left
out of the comparison, where they would match anything. Two fingerprints are
compared by sliding one over the other (a re-upload may carry a channel ident
or a trimmed head) and taking, at the best alignment, the mean Hamming
distance between the aligned non-dark frames. That number is the `distance`
the alias record and the DEDUP log line carry.

Calibrated on the real duplicates of batch 2026-09-03T2037Z (see the
constants below for the numbers); the threshold is pinned by a test.

Usage:
    source_fingerprint.py <video> [<video> ...]   - print the fingerprint(s)
    source_fingerprint.py --compare <a> <b>       - print distance/offset
"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # scripts/ - for _runlog
from _runlog import runlog  # noqa: E402

FFMPEG = "/usr/local/opt/ffmpeg-full/bin/ffmpeg"

# Bumped whenever anything below changes what the hashes look like: a stored
# fingerprint of another kind is never compared, it is re-taken.
FINGERPRINT_KIND = "dhash9x8-2fps-v1"
SAMPLE_FPS = 2
# A re-upload of a 45-minute episode is a re-upload in its first five minutes
# too; decoding beyond that buys nothing and costs the whole file's decode.
MAX_SECONDS = 300
# Thumbnail geometry of a dHash: 9 columns compared pairwise -> 8 bits per
# row, 8 rows -> 64 bits per frame.
THUMB_W, THUMB_H = 9, 8
HASH_BITS = (THUMB_W - 1) * THUMB_H

# Frames whose thumbnail averages darker than this (0-255) are ignored when
# two fingerprints are aligned: an all-black frame hashes to all-zeros and is
# 0 bits away from every other black frame in every other trailer.
DARK_LUMA = 12.0
# The fewest non-dark aligned frames an alignment may rest on. Below this a
# short vertical clip can "align" with a few similar frames of anything.
MIN_OVERLAP_FRAMES = 20
# A re-upload is not always at the same speed: 1RnyZgfN-JY (25 fps, 141 s)
# is SJVmeJaS44s (23.976 fps, 147 s) with a PAL speed-up, every shot boundary
# x1.043, and at a fixed offset the two measure 23.7 - "distinct". So the
# other fingerprint is also tried resampled by these ratios (nearest frame),
# and the best of the three alignments counts. 25/23.976 covers 25/24 too
# (0.3 frame of drift over 300 frames).
TIME_SCALES = (1.0, 25 / 23.976, 23.976 / 25)
# Mean Hamming distance (bits of 64, over the aligned non-dark frames) at or
# below which two sources are the same footage. Calibrated on the 23 sources
# of batch 2026-09-03T2037Z, full decode at 2 fps: the 12 same-trailer pairs
# of topics 002/004/006/007 measured 0.9-6.5 at scale 1.0 and 7.3-7.5 for
# the two PAL pairs once time-scaled; the 10 distinct pairs within topics
# 001/003/005/008 and 28 cross-topic pairs never came below 20.2 (most
# 24-32). 12 sits 4.5 above the worst duplicate and 8.2 below the nearest
# distinct pair. Trailers that share
# shots but are cut differently would land in between and are, correctly,
# *not* aliases: their shot lists differ.
DUPLICATE_MAX_DISTANCE = 12.0
# The sidecar every fetched source gets, next to the media, so the next batch
# compares without decoding again. Evicted with the media (fetch_footage.py
# sidecars()).
SIDECAR_SUFFIX = ".fingerprint.json"


def sidecar_path(video):
    return Path(video).with_suffix(SIDECAR_SUFFIX)


def _grab(video, max_seconds=MAX_SECONDS):
    """Grey 9x8 thumbnails at SAMPLE_FPS as an (n, 8, 9) uint8 array."""
    cmd = [FFMPEG, "-v", "error", "-threads", "4",
           "-t", str(max_seconds), "-i", str(video),
           "-vf", f"fps={SAMPLE_FPS},scale={THUMB_W}:{THUMB_H}:flags=area,format=gray",
           "-f", "rawvideo", "-"]
    # CF-0107: the one decode this fingerprint costs, as a `child` event
    # (tool ffmpeg) under whichever script asked - ingest_batch.py's own
    # event or index_footage.py's.
    out = runlog.run_child(cmd, tool="ffmpeg", capture_output=True)
    if out.returncode != 0:
        raise RuntimeError(f"ffmpeg failed on {video}: "
                           f"{out.stderr.decode(errors='replace').strip()[-300:]}")
    raw = np.frombuffer(out.stdout, dtype=np.uint8)
    n = len(raw) // (THUMB_W * THUMB_H)
    return raw[:n * THUMB_W * THUMB_H].reshape(n, THUMB_H, THUMB_W)


def hashes_from_thumbs(thumbs):
    """dHash per thumbnail (hex string) and mean luma per thumbnail."""
    t = thumbs.astype(np.int16)
    bits = (t[:, :, 1:] > t[:, :, :-1]).reshape(len(t), HASH_BITS).astype(np.uint8)
    packed = np.packbits(bits, axis=1)  # (n, 8) big-endian bytes
    hexes = [row.tobytes().hex() for row in packed]
    luma = [round(float(x), 1) for x in t.reshape(len(t), -1).mean(axis=1)]
    return hexes, luma


def fingerprint(video, max_seconds=MAX_SECONDS):
    """Fingerprint a media file. Cheap: one thumbnail per sampled frame."""
    thumbs = _grab(video, max_seconds)
    hexes, luma = hashes_from_thumbs(thumbs)
    return {"kind": FINGERPRINT_KIND, "fps": SAMPLE_FPS,
            "max_seconds": max_seconds, "frames": len(hexes),
            "hashes": hexes, "luma": luma}


def _stored(video):
    """A current-kind fingerprint already on disk: the sidecar, or the
    `fingerprint` header of an existing index. None if neither."""
    side = sidecar_path(video)
    candidates = [(side, lambda d: d),
                  (Path(video).with_suffix(".shots.json"), lambda d: d.get("fingerprint"))]
    for path, pick in candidates:
        if not path.exists():
            continue
        try:
            fp = pick(json.load(open(path)))
        except (OSError, ValueError):
            continue
        if isinstance(fp, dict) and fp.get("kind") == FINGERPRINT_KIND and "hashes" in fp:
            return fp
    return None


def load_or_make(video, save=True):
    """The stored fingerprint (sidecar or index header) if it is of the
    current kind, else a fresh one, written to the sidecar unless save=False."""
    fp = _stored(video)
    if fp is not None:
        return fp
    fp = fingerprint(video)
    if save:
        json.dump(fp, open(sidecar_path(video), "w"))
    return fp


def _bits(hexes):
    if not hexes:
        return np.zeros((0, HASH_BITS), dtype=np.int32)
    raw = np.frombuffer(bytes.fromhex("".join(hexes)), dtype=np.uint8)
    return np.unpackbits(raw.reshape(len(hexes), HASH_BITS // 8), axis=1).astype(np.int32)


def _resample(bits, luma, scale):
    """Frames of a sequence played `scale` times faster, nearest-frame."""
    if scale == 1.0:
        return bits, luma
    n = int(len(bits) / scale)
    idx = np.minimum(np.round(np.arange(n) * scale).astype(int), len(bits) - 1)
    return bits[idx], luma[idx]


def _best_offset(a, la, b, lb, dark_luma, min_overlap):
    # Hamming between every frame of a and every frame of b, via popcounts:
    # |x xor y| = |x| + |y| - 2 x.y for 0/1 vectors.
    ham = a.sum(1)[:, None] + b.sum(1)[None, :] - 2 * (a @ b.T)
    valid = (la[:, None] >= dark_luma) & (lb[None, :] >= dark_luma)
    best = None
    for d in range(-(len(b) - 1), len(a)):
        v = np.diagonal(valid, offset=-d)
        n = int(v.sum())
        if n < min_overlap:
            continue
        m = float(np.diagonal(ham, offset=-d)[v].mean())
        if best is None or m < best[0]:
            best = (m, d, n)
    return best


def compare(fa, fb, dark_luma=DARK_LUMA, min_overlap=MIN_OVERLAP_FRAMES,
            scales=TIME_SCALES):
    """Best alignment of two fingerprints.

    Returns {"distance", "offset_seconds", "overlap_frames", "time_scale"} -
    distance is the mean Hamming distance over the aligned non-dark frames at
    the offset (and playback-speed ratio, see TIME_SCALES) where it is
    smallest; None if the two never overlap on min_overlap non-dark frames (a
    7-second short against a trailer, or a mismatched fingerprint kind),
    which counts as "not the same footage".
    """
    if fa.get("kind") != fb.get("kind"):
        return None
    a, b0 = _bits(fa["hashes"]), _bits(fb["hashes"])
    if len(a) == 0 or len(b0) == 0:
        return None
    la = np.asarray(fa["luma"], dtype=float)
    lb0 = np.asarray(fb["luma"], dtype=float)
    fps = fa.get("fps", SAMPLE_FPS)
    best = None
    for scale in scales:
        b, lb = _resample(b0, lb0, scale)
        if len(b) == 0:
            continue
        r = _best_offset(a, la, b, lb, dark_luma, min_overlap)
        if r is not None and (best is None or r[0] < best["distance"]):
            best = {"distance": round(r[0], 2), "offset_seconds": r[1] / fps,
                    "overlap_frames": r[2], "time_scale": round(scale, 4)}
    return best


def is_duplicate(cmp, max_distance=DUPLICATE_MAX_DISTANCE):
    return cmp is not None and cmp["distance"] <= max_distance


def main():
    args = sys.argv[1:]
    if not args:
        sys.exit(__doc__)
    if args[0] == "--compare":
        if len(args) != 3:
            sys.exit("--compare <a> <b>")
        fa, fb = load_or_make(args[1], save=False), load_or_make(args[2], save=False)
        r = compare(fa, fb)
        verdict = "DUPLICATE" if is_duplicate(r) else "distinct"
        print(f"{verdict} {r}")
        return
    for v in args:
        # One nested event per source, so a multi-file call still shows the
        # time per video (CF-0107).
        with runlog.run("footage-indexer", "fingerprint", video=Path(v).stem,
                        name="source_fingerprint.py"):
            fp = load_or_make(v, save=False)
        print(json.dumps({k: fp[k] for k in ("kind", "fps", "frames")} | {"video": v}))


@runlog.script("footage-indexer", "fingerprint", name="source_fingerprint.py")
def cli():
    """CF-0107: start/done|failed around main(); a usage error exits 2 -> failed."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
