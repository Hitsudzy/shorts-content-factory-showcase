#!/usr/bin/env python3
"""CF-0337: the same picture, or one that looks like it, may not come back
while the viewer still remembers it.

What the user rejected (widows-bay, 2026-09-23)
-----------------------------------------------
"Several takes of one frame in the first 5 seconds look strange." In the plan
(`pipeline/rebuilds/2026-09-23T0725Z`) blocks 0-2 were `hG2tH_gTvRI:14`,
`hG2tH_gTvRI:11`, and `hG2tH_gTvRI:14` again (CF-0137's emergency repeat) -
two different shot numbers, but one camera set-up on one audience, and then
the first one a second time 1.60 s after it left the screen.
`EmergencyReuseBudget.allow()` refused the repeat only when it would be the
*adjacent* block; one block in between was enough to let it through. And
nothing anywhere compared two *different* shots for looking the same.

The instrument
--------------
A clip's signature is three 32x18 greyscale frames (15 %, 50 % and 85 % of
the span actually shown), and the similarity of two clips is the best Pearson
correlation over the 3x3 frame pairs. Greyscale at that size keeps the layout
of a set-up (where the stage, the crowd, the light are) and drops everything
a re-cut of the same set-up changes; three samples catch a pan that passes
through the same view. It reads the *clip* (the plan's `asset.src`), not the
rendered frame, because the rendered frame carries the captions, the
watermark and the fact strip, which are the same over every block and lift
every pair towards one another.

Why not the index's CLIP embeddings: they describe what a shot is *of*, and
within one source nearly everything is of the same thing. Measured on the
same pairs: widows-bay 14/11 = 0.965, but the accepted outrider's
`KXuteMhFyV0:4`/`:2` (0.96 s apart) = 0.952, and every source of the batch has
unrelated pairs above 0.93. There is no threshold between those.

The numbers (measured 2026-09-23 on the clips of every example-film plan that
still has them, pairs within 12 s)
-------------------------------------------------------------------------
                                              similarity   gap
  widows-bay 0725Z  blocks 0/2  14 vs 14         0.997     1.60 s  rejected
                    blocks 6/7   1 vs 12         0.941     0.00 s
                    blocks 16/17 15 vs 0         0.907     0.00 s
                    blocks 0/1  14 vs 11         0.901     0.00 s  rejected
                    blocks 1/2  11 vs 14         0.895     0.00 s  rejected
  outrider (published, accepted) - highest      0.581     0.96 s
                    next                         0.496     1.91 s
  mormon-wives-comeback (one interview camera)   0.97-0.98 0-12 s

NEAR_DUPLICATE_SIMILARITY = 0.85 sits under the lowest pair the user named
(0.895) and 0.27 above the highest pair of the one video he accepted and
published. The single-camera interview in mormon-wives-comeback is above it
everywhere; that video is not on the accepted list, and a talking head cut
into eight blocks is the same "several takes of one frame".

MIN_REPEAT_GAP_SECONDS = 5.0 is the user's own window ("in the first 5
seconds") and the distance of the rejected repeat was 1.60 s. Measured as
the gap between the end of one showing and the start of the next, i.e. at
least five seconds of other pictures in between - about three blocks at the
channel's 1.4-2.0 s cadence, so the picture is gone from short-term memory
rather than merely off the screen for one cut. The accepted outrider has no
pair of the same source within 5 s above 0.58, so the rule costs it nothing.

Both rules apply to the same source only (a shot number is only unique
inside its source, and two different sources are two different cameras; the
task names "neighbouring shots of one source"), and to every pick - the
regular fill, the topic-footage rung and the emergency repeat alike.

CF-0461: two sources that are one trailer
-----------------------------------------
"Two different sources are two different cameras" is false when the topic
carries the same trailer uploaded twice. you-can-see-everything
(`example-film/2026-10-01T0200Z`, rejected: "the same frame twice in a row,
blocks 0-1, 2-3, 4-5") had `HvW_N5p1q44` (149 s) and `jsw92T7KpqM` (143 s),
one video under two ids, and the editor put the same moment from both side
by side. Neither rule saw it: different keys, different sources.

The instrument is the same signature, compared *frame by frame in order*
(`copy_similarity()`: the lowest of the 15/50/85 % pair correlations, or for
a still the lowest against every frame of the other). The best-of-nine
`similarity()` cannot tell a copy from a cut that merely passes through the
same instant: wolfhame 2210Z (accepted) blocks 5/6 `CL1EFACsWag:15` /
`cmjpadVj-Vk:15` reach 0.9985 best-of-nine because the 85 % frame of one is
the 15 % frame of the other - the next block carries on where the previous
left off, a continuation, not a second showing - and aligned they are 0.71.
A copy matches at every sample point.

The numbers (measured 2026-10-01 on every cross-source pair, whole video, of
every accepted example-film plan whose clips are still on disk: outrider
1541Z, american-dread-story 1722Z/2210Z/0200Z, vanguards-endgame and
harbourlights 0705Z, backrooms, kaijura-minus-zero, primetime and wolfhame 2210Z;
the 1722Z you-can-see-everything had no clips left)
-------------------------------------------------------------------------
                                              aligned  best-of-9   gap
  you-can-see-everything 0200Z blocks 4/5      0.9998    0.9998   0.00 s  rejected
                               blocks 0/1      0.9993    0.9998   0.00 s  rejected
                               blocks 2/3      0.9916    1.0000   0.00 s  rejected
                               blocks 9/11     0.9793    0.9992   4.19 s  (shot 3 of both)
  accepted - highest: primetime 13/14          0.9543    0.9713   0.00 s  (clip vs held still)
                      backrooms 2/3            0.9160    0.9416   0.00 s
                      wolfhame 6/11             0.7935    0.8151   8.83 s
                      primetime 15/19          0.6919    0.9914   6.50 s
                      wolfhame 5/6              0.7054    0.9985   0.00 s

COPY_SIMILARITY = 0.97 sits 0.016 above the highest accepted pair and 0.009
under the weakest copy pair of the rejected video (9/11, the same shot 3 of
both uploads, which the user did not name but is the same footage twice
4.19 s apart). The task's own guess, 0.98-0.99, would let 9/11 through.

The window is the whole video, not MIN_REPEAT_GAP_SECONDS. The 5 s window
is for a *look-alike* - another moment of the same set-up fades from memory
in a few cuts; an identical moment is recognised. And a copy under another
id is a repeat the shot ledger cannot see: CF-0137's reuse is once per video
and recorded in the plan, while the copy would be a free, unrecorded second
showing anywhere. So it is held to the ledger's scope, the video. It costs
the accepted plans nothing (no accepted pair reaches 0.97 at any distance).
A copy is reported as kind `repeat` (`score.repeated_shot`), with
`copy: True`, so the score and the qc gate treat it as the same shot shown
twice.
"""
import math
import subprocess
from pathlib import Path

NEAR_DUPLICATE_SIMILARITY = 0.85
COPY_SIMILARITY = 0.97
MIN_REPEAT_GAP_SECONDS = 5.0

SIGNATURE_SIZE = (32, 18)
SIGNATURE_POINTS = (0.15, 0.5, 0.85)

STILL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def _frame(path, at, ffmpeg_bin):
    w, h = SIGNATURE_SIZE
    args = [ffmpeg_bin, "-v", "error", "-nostdin"]
    if at is not None:
        args += ["-ss", f"{max(0.0, at):.3f}"]
    args += ["-i", str(path), "-frames:v", "1",
             "-vf", f"scale={w}:{h},format=gray", "-f", "rawvideo", "-"]
    try:
        out = subprocess.run(args, capture_output=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if len(out) != w * h:
        return None
    return list(out)


def signature(path, seconds=None, ffmpeg_bin=None, offset=0.0):
    """Three small greyscale frames of the clip at `path` over
    [offset, offset + seconds], or one frame for a still. None when nothing
    could be read - the caller treats an unread clip as unmeasured, never as
    a duplicate."""
    if not path or not Path(path).exists():
        return None
    if ffmpeg_bin is None:
        from common import FFMPEG as ffmpeg_bin
    if Path(path).suffix.lower() in STILL_SUFFIXES or not seconds:
        f = _frame(path, None if Path(path).suffix.lower() in STILL_SUFFIXES
                   else offset, ffmpeg_bin)
        return [f] if f else None
    frames = [_frame(path, offset + seconds * q, ffmpeg_bin)
              for q in SIGNATURE_POINTS]
    frames = [f for f in frames if f]
    return frames or None


def _corr(a, b):
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    sab = saa = sbb = 0.0
    for x, y in zip(a, b):
        dx, dy = x - ma, y - mb
        sab += dx * dy
        saa += dx * dx
        sbb += dy * dy
    if saa <= 0 or sbb <= 0:
        # A flat frame (black, one colour) has no layout to compare; two of
        # them are identical to the eye, one against a picture is not.
        return 1.0 if saa <= 0 and sbb <= 0 else 0.0
    return sab / math.sqrt(saa * sbb)


def similarity(sig_a, sig_b):
    """Best correlation over every frame pair, or None when either side is
    unmeasured."""
    if not sig_a or not sig_b:
        return None
    return max(_corr(a, b) for a in sig_a for b in sig_b)


def copy_similarity(sig_a, sig_b):
    """CF-0461: how far two clips are the same footage at every sample
    point - the lowest correlation of the frames paired in order (15 % with
    15 %, ...), or, when the two read a different number of frames (a still,
    a partly read clip), the lowest over every pair. None when either side
    is unmeasured."""
    if not sig_a or not sig_b:
        return None
    if len(sig_a) == len(sig_b):
        return min(_corr(a, b) for a, b in zip(sig_a, sig_b))
    return min(_corr(a, b) for a in sig_a for b in sig_b)


def source_of(key):
    """The source part of a shot key: `(source, shot)` tuple or "stem:shot"."""
    if isinstance(key, (tuple, list)):
        return Path(str(key[0])).stem
    return str(key).rsplit(":", 1)[0] if key else None


def gap(a, b):
    """Seconds between two spans, 0 when they touch or overlap."""
    return max(0.0, max(a["start"], b["start"]) - min(a["end"], b["end"]))


def conflict(placed, cand, min_gap=MIN_REPEAT_GAP_SECONDS,
             threshold=NEAR_DUPLICATE_SIMILARITY,
             copy_threshold=COPY_SIMILARITY):
    """The first showing in `placed` that `cand` may not stand this close to,
    as a record, or None.

    Every entry (and `cand`) is `{"key", "start", "end", "sig"}`; `key` is
    anything source_of() reads. Same key within `min_gap` is a `repeat`;
    another source whose clip is the same footage (copy_similarity() >=
    `copy_threshold`, CF-0461) anywhere in the video is a `repeat` with
    `copy: True`; same source and similarity >= `threshold` within `min_gap`
    is a `near_duplicate`. A repeat is reported before a look-alike; within a
    kind, nearest in time first, so the reason names the picture the viewer
    saw last."""
    by_gap = sorted(placed, key=lambda p: gap(p, cand))
    near = [p for p in by_gap if gap(p, cand) < min_gap]
    # A repeat outranks a look-alike: it is the stronger statement, and the
    # one CF-0137's emergency rung has to be told about by name.
    for p in near:
        if _same_key(p["key"], cand["key"]):
            return {"kind": "repeat", "other": p,
                    "gap": round(gap(p, cand), 2), "similarity": 1.0}
    # CF-0461: the same footage from another upload of the same video - the
    # same shot to the viewer, at any distance (see the module docstring).
    for p in by_gap:
        if source_of(p["key"]) == source_of(cand["key"]):
            continue
        s = copy_similarity(p.get("sig"), cand.get("sig"))
        if s is not None and s >= copy_threshold:
            return {"kind": "repeat", "copy": True, "other": p,
                    "gap": round(gap(p, cand), 2), "similarity": round(s, 4)}
    for p in near:
        g = round(gap(p, cand), 2)
        if source_of(p["key"]) != source_of(cand["key"]):
            continue
        s = similarity(p.get("sig"), cand.get("sig"))
        if s is not None and s >= threshold:
            return {"kind": "near_duplicate", "other": p, "gap": g,
                    "similarity": round(s, 3)}
    return None


def _same_key(a, b):
    def norm(k):
        if isinstance(k, (tuple, list)):
            return f"{Path(str(k[0])).stem}:{int(k[1])}"
        return str(k)
    return norm(a) == norm(b)


def describe(c, label=None):
    other = c["other"]
    who = label or f"{other['key']}"
    if c.get("copy"):
        return (f"the same footage as {who} from another source ("
                f"{c['similarity']:.3f} >= {COPY_SIMILARITY} frame by frame: "
                f"two uploads of one video) shown {c['gap']:.2f}s before - a "
                f"copy is the same shot, once per video (CF-0461)")
    if c["kind"] == "repeat":
        return (f"the same shot {who} left the screen {c['gap']:.2f}s before - "
                f"a repeat has to wait {MIN_REPEAT_GAP_SECONDS:.0f}s of other "
                f"pictures (CF-0337)")
    return (f"looks like {who} ({c['similarity']:.3f} >= "
            f"{NEAR_DUPLICATE_SIMILARITY} of the same source) shown "
            f"{c['gap']:.2f}s before - a near-duplicate has to wait "
            f"{MIN_REPEAT_GAP_SECONDS:.0f}s (CF-0337)")


def plan_showings(plan, ffmpeg_bin=None, measure=True):
    """One entry per block that shows a clip or a still from a source shot:
    `{"block", "key", "start", "end", "sig"}`. `measure=False` skips the
    signatures (the same-shot rule needs none)."""
    out = []
    for i, b in enumerate(plan.get("blocks") or []):
        key = b.get("shot")
        asset = b.get("asset") if isinstance(b.get("asset"), dict) else {}
        if not key or asset.get("kind") not in ("clip", "still"):
            continue
        start, end = float(b["start"]), float(b["end"])
        sig = None
        if measure:
            sig = signature(asset.get("src"), end - start, ffmpeg_bin,
                            offset=float(asset.get("start_seconds") or 0.0))
        out.append({"block": i, "key": key, "start": start, "end": end,
                    "sig": sig})
    return out


def plan_violations(plan, ffmpeg_bin=None, measure=True):
    """Every pair of blocks in a plan that breaks any rule - qc_render's
    reading of a finished video. Each is `{kind, blocks, shots, gap,
    similarity}`; `unmeasured` counts the showings whose clip could not be
    read (the near-duplicate rule was not applied to them)."""
    showings = plan_showings(plan, ffmpeg_bin, measure)
    found = []
    for j, cur in enumerate(showings):
        c = conflict(showings[:j], cur)
        if c:
            found.append({"kind": c["kind"],
                          "blocks": [c["other"]["block"], cur["block"]],
                          "shots": [c["other"]["key"], cur["key"]],
                          "gap": c["gap"], "similarity": c["similarity"],
                          **({"copy": True} if c.get("copy") else {})})
    return {"violations": found,
            "showings": len(showings),
            "unmeasured": sum(1 for s in showings if measure and not s["sig"]),
            "min_gap_seconds": MIN_REPEAT_GAP_SECONDS,
            "near_duplicate_similarity": NEAR_DUPLICATE_SIMILARITY,
            "copy_similarity": COPY_SIMILARITY}
