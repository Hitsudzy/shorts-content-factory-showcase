#!/usr/bin/env python3
"""Two indexed sources of one topic that are the same video, by their shot lists (CF-0464).

CF-0080's content fingerprint (`source_fingerprint.py`) catches a re-upload
before it is indexed - one dHash of the *whole frame* twice a second. It
misses a re-upload whose frame was changed: `you-can-see-everything`
(`2026-10-01T0200Z`, topic `lf-2026-09-23-004`) held `HvW_N5p1q44`
(1440x1080, 148 s) and `jsw92T7KpqM` (1920x1080, 142 s) - one trailer, one
upload cropped to 4:3 - at fingerprint distance 14.2 against the 12.0 line,
so both were indexed, both counted as a source for the two-source gate and
the pool depth, and the Video Editor put the same shot from both uploads
side by side (CF-0461 then taught `repeat_guard` to refuse that inside one
video). This module is the pool-level answer: once both are indexed, are
their shot lists the same shot list?

The measure
-----------
Every shot of a `shots.json` carries a CLIP embedding (`index_footage.py`).
Two shots *match* when their embeddings' cosine is >= SHOT_MATCH_COSINE and
their durations differ by at most DURATION_TOLERANCE of the longer one - a
copy keeps the cut, so a shot keeps its length (a PAL speed-up changes it by
4 %). The matches are then *aligned*: the heaviest chain of matches that
keeps the order of both lists (a weighted longest common subsequence, each
match weighing the shorter duration of the two), so a few shared shots in a
teaser and a trailer cut in another order never add up to a copy. `share` is
the matched seconds over the indexed seconds of the shorter source - a
cut-down of a trailer is that trailer's copy - and a pair is a copy at
`share >= COPY_SHARE` with at least MIN_MATCHED_SHOTS matches.

It costs nothing to take: the embeddings are in the index already, no frame
is decoded. That is also why it is not `repeat_guard.copy_similarity()`
(CF-0461), the measure the task first pointed at - that one correlates grey
32x18 thumbnails of the *full frame*, which is right for the Editor's clips
(cut and cropped to the same 9:16 frame) and wrong for the raw uploads: on
the 43 aligned shot pairs of the 0200Z copy it read -0.09..0.92 (the 4:3
crop moves every pixel), on the second copy 0.31..1.00, and an honest
pair's shared end card read 0.999. And it decodes three frames per shot -
93 s for the 0200Z pair against milliseconds here.

Calibration (2026-10-02, every pair of sources one topic held in
`pipeline/*/*/01b-footage-index.json` with both indexes in the pool - 100
pairs): the two copies found measure share 0.846 (`HvW_N5p1q44` /
`jsw92T7KpqM`, 43 of 53 shots aligned) and 0.836 (`KxaTwLfhahw` 1920x1080 /
`kw0YhiqOPFg` 1544x1080, `2026-09-30T2210Z` topic `lf-2026-09-27-009`, 29
of 37); the highest honest pair 0.340 (`5IcLeqlF6QU` / `5VAFuHcqDKI`, two
cuts sharing their last two shots - the title card), then 0.309, 0.254, and
86 of the 100 under 0.2. COPY_SHARE = 0.6 sits 0.24 under the weaker copy
and 0.26 over the strongest honest pair. Not 0.97 (the task's first guess,
CF-0461's frame line): a copy never aligns all its shots - the detector
splits a shot differently in the two uploads and an end card differs - so a
share near 1 would miss both copies.

Which one is kept: `keeper()` - the larger content short side (`usable_cached`
of the index, what every resolution floor reads), then the larger frame, then
the longer indexed footage, then the first one held.

Usage:
    shot_copy.py <a.shots.json|id> <b.shots.json|id>     - compare two sources
    shot_copy.py --topics <01b-footage-index.json> ...    - every topic's pairs
"""
import itertools
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _fi_paths import pool_dir  # noqa: E402 - CF-0620

CACHE = pool_dir()  # CF-0620: this checkout's factory (or FACTORY_ROOT), not the home checkout

# Bumped whenever anything below changes what `share` means.
COPY_KIND = "clip-aligned-shots-v1"
SHOT_MATCH_COSINE = 0.95
DURATION_TOLERANCE = 0.2
COPY_SHARE = 0.6
MIN_MATCHED_SHOTS = 5
METHOD = "shots"          # the `method` of an alias record this module decided


def load_index(index):
    """A shots.json as a dict: a dict passes through, a path or a bare video id
    (looked up in the pool) is read. None when it cannot be read."""
    if isinstance(index, dict):
        return index
    p = Path(index)
    if not p.suffix and not p.exists():
        p = CACHE / f"{index}.shots.json"
    try:
        return json.loads(p.read_text())
    except (OSError, ValueError):
        return None


def index_path_for(media):
    """`<id>.shots.json` beside a source's media file."""
    return Path(media).with_suffix(".shots.json")


def _shots(index):
    """(durations, unit embeddings) of the shots that carry an embedding."""
    rows = [s for s in (index or {}).get("shots") or ()
            if isinstance(s, dict) and s.get("embedding")
            and s.get("end") is not None and s.get("start") is not None]
    if not rows:
        return None, None
    dur = np.array([float(s["end"]) - float(s["start"]) for s in rows])
    emb = np.array([s["embedding"] for s in rows], dtype=float)
    norm = np.linalg.norm(emb, axis=1, keepdims=True)
    norm[norm == 0] = 1.0
    return dur, emb / norm


def _align(ok, weight):
    """Heaviest order-keeping chain of allowed pairs: (weight, [(i, j), ...])."""
    n, m = ok.shape
    best = np.zeros((n + 1, m + 1))
    step = np.zeros((n, m), dtype=np.int8)   # 0 skip a, 1 skip b, 2 match
    for i in range(n):
        for j in range(m):
            skip_a, skip_b = best[i, j + 1], best[i + 1, j]
            v, s = (skip_a, 0) if skip_a >= skip_b else (skip_b, 1)
            if ok[i, j] and best[i, j] + weight[i, j] > v:
                v, s = best[i, j] + weight[i, j], 2
            best[i + 1, j + 1], step[i, j] = v, s
    pairs, i, j = [], n - 1, m - 1
    while i >= 0 and j >= 0:
        s = step[i, j]
        if s == 2:
            pairs.append((i, j))
            i, j = i - 1, j - 1
        elif s == 0:
            i -= 1
        else:
            j -= 1
    return float(best[n, m]), pairs[::-1]


def compare(index_a, index_b, cosine=SHOT_MATCH_COSINE,
            tolerance=DURATION_TOLERANCE):
    """How much of the shorter source's shot list the other one repeats, in
    order. None when either index is unreadable, has no embeddings, or the
    two were embedded by different models (their cosines mean nothing)."""
    a, b = load_index(index_a), load_index(index_b)
    if not a or not b:
        return None
    if a.get("model") and b.get("model") and a["model"] != b["model"]:
        return None
    da, ea = _shots(a)
    db, eb = _shots(b)
    if da is None or db is None:
        return None
    sim = ea @ eb.T
    longer = np.maximum(da[:, None], db[None, :])
    ok = (sim >= cosine) & (np.abs(da[:, None] - db[None, :]) <= tolerance * longer)
    weight = np.minimum(da[:, None], db[None, :])
    matched, pairs = _align(ok, weight)
    base = min(float(da.sum()), float(db.sum()))
    share = matched / base if base > 0 else 0.0
    return {"kind": COPY_KIND, "share": round(share, 3),
            "matched_shots": len(pairs), "shots": [len(da), len(db)],
            "matched_seconds": round(matched, 1),
            "min_cosine": (round(float(min(sim[i, j] for i, j in pairs)), 4)
                           if pairs else None)}


def is_copy(cmp, share=COPY_SHARE, min_shots=MIN_MATCHED_SHOTS):
    return (cmp is not None and cmp["share"] >= share
            and cmp["matched_shots"] >= min_shots)


def quality(index):
    """(content short side, frame pixels, indexed seconds) - larger is better."""
    idx = load_index(index) or {}
    short = pixels = 0
    seconds = 0.0
    for s in idx.get("shots") or ():
        if not isinstance(s, dict):
            continue
        u = s.get("usable_cached") or {}
        short = max(short, int(u.get("short_side") or 0))
        pixels = max(pixels, int(u.get("width") or 0) * int(u.get("height") or 0))
        try:
            seconds += float(s["end"]) - float(s["start"])
        except (KeyError, TypeError, ValueError):
            pass
    return short, pixels, round(seconds, 1)


def keeper(held, newcomer):
    """"newcomer" when the newly indexed copy is the better one to keep (see
    the module docstring), "held" otherwise - a tie keeps what is held."""
    return "newcomer" if quality(newcomer) > quality(held) else "held"


def topic_pairs(report_paths, cache=CACHE):
    """[(share, a, b, cmp, where)] for every pair of sources a topic held."""
    seen, out = set(), []
    for rp in report_paths:
        try:
            rep = json.loads(Path(rp).read_text())
        except (OSError, ValueError):
            continue
        where = Path(rp).parent.name
        for tid, vids in (rep.get("sources_by_topic") or {}).items():
            for a, b in itertools.combinations(sorted(set(vids)), 2):
                if (a, b) in seen:
                    continue
                seen.add((a, b))
                cmp = compare(Path(cache) / f"{a}.shots.json",
                              Path(cache) / f"{b}.shots.json")
                if cmp is not None:
                    out.append((cmp["share"], a, b, cmp, f"{where} {tid}"))
    return sorted(out, key=lambda r: -r[0])


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args:
        sys.exit(__doc__)
    if args[0] == "--topics":
        rows = topic_pairs(args[1:])
        for share, a, b, cmp, where in rows:
            verdict = "COPY" if is_copy(cmp) else "distinct"
            print(f"{share:.3f} {verdict:8s} {a} {b} "
                  f"{cmp['matched_shots']}/{min(cmp['shots'])} shots  {where}")
        print(f"{len(rows)} pairs, {sum(is_copy(r[3]) for r in rows)} copies")
        return 0
    if len(args) != 2:
        sys.exit("shot_copy.py <a> <b>")
    cmp = compare(args[0], args[1])
    if cmp is None:
        print("unmeasured (an index missing, no embeddings, or two models)")
        return 1
    print(f"{'COPY' if is_copy(cmp) else 'distinct'} {json.dumps(cmp)}")
    if is_copy(cmp):
        keep = keeper(args[0], args[1])
        print(f"keep {'the second' if keep == 'newcomer' else 'the first'}: "
              f"{quality(args[0])} vs {quality(args[1])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
