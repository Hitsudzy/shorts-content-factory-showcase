#!/usr/bin/env python3
"""CF-0163: the merged-shot signal read off a *profile of the usability
verdict* taken along a shot, instead of off one frame of it.

`CF-0156` set out to prove that `usable()`'s verdict jumping between
neighbouring frames of the same shot was measurement noise, and measured the
opposite: the jumps are a true report about the material, and in a large part
of the cases the material is bad because the "shot" is not one shot. Those
merged shots survived `CF-0105`'s split - the pool was re-indexed after it and
the joins inside the shots are still there - because `CF-0105`'s two signals
(CLIP dispersion over 8 samples, windowed luma step) are blind to a cut that
keeps the palette and the global composition but moves the *subject*.

The verdict profile is not blind to it, because the planner's window is fixed
for the whole shot: the moment the subject jumps to a new place in frame, that
one window stops covering it and the verdict flips - while the frame itself
still crops perfectly on its own.

Everything here is pure, so `index_footage.py`'s wiring and the tests can be
driven from recorded profiles without ffmpeg or Vision.

Profile row schema (what `usability_probe.probe_profile()` emits and what the
recorded `/tmp/cf0155-probe-profile/*.json` rows already carry):

    {"t": seconds from the shot's start,
     "roi": roi_source, the detector that found the subject,
     "cov": the frame's coverage under *its own* optimal window,
     "plan_ok": the verdict under the planner's fixed window,
     "plan_cov": coverage under that fixed window,
     "luma": mean luma of the frame (YAVG, 16-235)}
"""

# ---------------------------------------------------------------------------
# The thresholds. Every number below was read off the 24-shot profile CF-0156
# recorded (`/tmp/cf0155-probe-profile/`, step 0.5s, 401 transitions between
# neighbouring frames, 48 verdict flips); `measure_verdict_instability.py`
# re-derived all of them from that directory and printed the sweep. That
# directory is gone, and the script left the tree in CF-0498 (2026-10-03):
# Archive:shorts-content-factory-cleanup-1.6/footage-indexer-code-2026-10-03.zip.
# ---------------------------------------------------------------------------

# Gate 1 - the detector must not have changed across the pair. Of the 48
# flips, 26 (54%) happen with `roi_source` identical on both sides; the other
# 22 are the measurer switching modes (faces <-> saliency <-> animation_center
# and back, e.g. x9wMFCMXCRE s025 flapping animation_center/saliency three
# times in 1.5s with a luma move of 0.3-0.7). Only the first group is evidence
# about the material, so a changed detector disqualifies a transition outright
# rather than being weighed against anything.

# Gate 2a - recomposition. `CF-0156`'s sharpest observation: in 17 of the 48
# flips *both* frames crop perfectly on their own (own coverage >= 0.9) and
# only the planner's fixed window fails. That is a subject that moved across
# the frame, which within one continuous take it cannot do in 0.5s.
OWN_COV_FLOOR = 0.9

# ...but only when the detector found a subject at all. `animation_center` is
# what it reports when it did not, and then "the subject moved" has no
# meaning: what moves is a caption or a logo appearing over a picture that
# never changed. Measured on the frames (CF-0163's review of the four leaders,
# two independent passes): every recomposition seam on an `animation_center`
# frame in CF-0156's sample is a title graphic - all three of them, all in
# ADi1iextoUM s034, which is one continuous overhead shot of a hockey face-off
# with the show's titles fading in over it. The joins that *are* real on
# `animation_center` frames (kMsiD1Nky5I s006 t=3.0 and t=5.0, two of the
# seven edits its frame review found) all come through the luma gate below,
# so nothing true is lost by barring this one.
SUBJECTLESS_ROI = ("animation_center",)

# How far the planner-window coverage has to swing for that to count. Measured
# over the stable-detector flips on a subject detector with both own coverages
# above the floor, sorted: 1.00, 1.00, 0.66, 0.64, 0.38, 0.38 | 0.09, 0.06,
# 0.00, 0.00, 0.00. One wide gap, 0.09 -> 0.38, separating the six
# recomposition flips from the five that are the gate dithering around its own
# edge (UcIvQYYW4PY s002 t=10.5 at 0.09, iSWP2feb4rw s013 t=6.0 at 0.06, and
# three where the planner window sees exactly the same coverage on both sides
# and the verdict flipped on some other criterion). 0.30 is the round value
# inside that gap.
PLAN_COV_STEP = 0.30

# Gate 2b - brightness step. The corroboration for the cut that changes the
# exposure rather than the layout (dark scene -> lit scene), which is also the
# only evidence available when the subject leaves the frame entirely and own
# coverage collapses with it. Frame-to-frame at the profile's own step, not
# `index_footage.luma_steps()`'s windowed median - the profile is sampled
# every 0.5s and there is no window to take a median over, so the number is a
# different measurement and gets its own threshold.
#
# Measured over the stable-detector flips, sorted: 88.9, 65.8, 37.0, 18.9,
# 13.1, 12.2, 10.5, 10.5, 10.1, 9.3 | 7.5, 7.3, 7.1, 3.8, 3.5, 3.2, 2.6, 2.3,
# 2.1, 0.5, 0.3, 0.2, 0.1, 0.0. The gap 7.5 -> 9.3 is where the character of
# the flip changes: below it sit three flips (M9NWvGZViCg s014 t=1.0,
# 7EY3QyPTEso s014 t=1.0, Ho10_4IX1jE s011 t=1.0) whose coverage - own *and*
# planner - and black fraction are unchanged to two decimals across the pair,
# i.e. the same picture with the gate dithering; above it sits pOY-Q5DXfcI
# s000 t=10.0, a genuine dark-to-lit cut (black fraction 0.69 -> 0.54). 8.0
# sits inside that gap, and is the same figure CF-0156 used when it counted
# "brightness jump > 8" as an indirect sign of a join.
LUMA_STEP = 8.0

# The move also has to be a *step* and not a ramp. This is the same mistake
# CF-0105 made and measured its way out of one signal earlier: a difference
# between two neighbouring samples cannot tell a cut from a fade, and a fade
# is exactly what opens a lot of shots. ADi1iextoUM s034 fades up from black
# over its first two seconds (19.6 -> 56.6 -> 105.8 -> 171.6 -> 192.1 YAVG)
# and produced two seams on a shot the frame review found to be one unbroken
# take. CF-0105 answered it with a median over a window; a profile sampled
# every 0.5s has no window to take a median over, so the shape is read
# directly: how much of this move is *continued*, in the same direction, by
# the move before or after it.
#
# Measured over every luma seam in CF-0156's sample, against the frame review:
# the four confirmed joins score 0.00, 0.00, 0.00, 0.01 and the two confirmed
# non-joins score 0.75 and 1.33 (unreviewed ones: 0.00, 0.00, 0.01, 1.01).
# The gap runs 0.01 -> 0.75; 0.5 sits inside it and means the plain thing -
# half the move carried on in the same direction, so the level was travelling,
# not stepping.
LUMA_RAMP_SHARE = 0.5

# How many corroborated seams make the shot merged. One is enough and is what
# the leaders demand: pOY-Q5DXfcI s000 - a shot CF-0156 lists among the four
# with a join - has exactly one stable-detector flip in its whole 12s. Raising
# this to 2 would leave it whole. Nothing is lost by the low bar because the
# corroboration gates above already do the separating: on the 24 recorded
# shots, every shot with zero seams also has zero flips worth looking at, and
# the two controls that must stay whole (H-43VeYGiPM s008, 8JQ45AWDgPE s000)
# score 0 - as does W4mvmBXg9Nc s001, CF-0105's press-conference one-take,
# whose two stable-detector flips move the luma by 0.0 and 0.1 and never have
# both own coverages above the floor.
MERGED_MIN_SEAMS = 1


def _flip(a, b):
    """Does the verdict flip across this pair, with the detector unchanged."""
    return a["plan_ok"] != b["plan_ok"] and a.get("roi") == b.get("roi")


def ramp_share(a, b, before=None, after=None):
    """How much of the luma move from `a` to `b` is continued, in the same
    direction, by the move before or after it. 0.0 when the level reversed or
    held (a step); 1.0 when the neighbouring move is just as big and the same
    way (a fade in progress). `before`/`after` are the rows either side, or
    None at the ends of the profile. Pure."""
    d = b.get("luma", 0.0) - a.get("luma", 0.0)
    if not d:
        return 0.0
    neighbours = []
    if before is not None:
        neighbours.append(a.get("luma", 0.0) - before.get("luma", 0.0))
    if after is not None:
        neighbours.append(after.get("luma", 0.0) - b.get("luma", 0.0))
    return max([n / d for n in neighbours if n / d > 0] or [0.0])


def seam(a, b, before=None, after=None):
    """The seam this pair of neighbouring profile rows is evidence of, or
    None. `b`'s time is the seam's time: the first frame of the new scene is
    where a head belongs (same convention as `index_footage.luma_steps()`).
    `before`/`after` are the rows either side of the pair; without them the
    luma gate cannot tell a step from a fade and is applied unshaped.
    Pure."""
    if not _flip(a, b):
        return None
    luma_step = abs(b.get("luma", 0.0) - a.get("luma", 0.0))
    plan_cov_step = abs(b.get("plan_cov", 0.0) - a.get("plan_cov", 0.0))
    recomposed = (a.get("roi") not in SUBJECTLESS_ROI
                  and min(a.get("cov", 0.0), b.get("cov", 0.0)) >= OWN_COV_FLOOR
                  and plan_cov_step >= PLAN_COV_STEP)
    share = ramp_share(a, b, before, after)
    why = []
    if recomposed:
        why.append("recompose")
    if luma_step >= LUMA_STEP and share < LUMA_RAMP_SHARE:
        why.append("luma")
    if not why:
        return None
    return {"t": round(float(b["t"]), 3), "why": why,
            "luma_step": round(luma_step, 1),
            "luma_ramp": round(share, 2),
            "plan_cov_step": round(plan_cov_step, 3),
            "roi": a.get("roi")}


def seams(rows):
    """Every seam in a profile, in time order. Pure."""
    out = []
    for i in range(len(rows) - 1):
        s = seam(rows[i], rows[i + 1],
                 rows[i - 1] if i > 0 else None,
                 rows[i + 2] if i + 2 < len(rows) else None)
        if s:
            out.append(s)
    return out


def instability(rows):
    """The shot-level verdict on a profile: how unstable it is and whether
    that instability is a join. Shaped like `index_footage.heterogeneity()`
    so the two read alike in a log line and in `shots.json`. Pure."""
    flips = sum(1 for a, b in zip(rows, rows[1:]) if a["plan_ok"] != b["plan_ok"])
    stable = sum(1 for a, b in zip(rows, rows[1:]) if _flip(a, b))
    found = seams(rows)
    return {"frames": len(rows), "flips": flips, "stable_flips": stable,
            "seams": [s["t"] for s in found],
            "seam_reasons": sorted({w for s in found for w in s["why"]}),
            "merged": len(found) >= MERGED_MIN_SEAMS}


def seam_times(rows, start=0.0):
    """Seam times on the source's own timeline - what `split_points()` wants.
    Pure."""
    return [round(start + s["t"], 3) for s in seams(rows)]


# ---------------------------------------------------------------------------
# Reading profiles somebody else recorded.
#
# The indexer does not take the profile itself - see the CF-0163 block in
# `index_footage.py` for the cost that decided that - it reads the files the
# probe run already wrote: one json per shot, named `<source>_s<NNN>.json`,
# carrying the shot's `start` on the source's timeline and its `rows`.
#
# Shots are matched by *span*, never by the `NNN` in the name: the profile was
# recorded against a previous index's shot list, and the whole point of this
# signal is that this index's list will differ.
# ---------------------------------------------------------------------------

# How far outside a shot a profile's span may sit and still be that shot's.
# One profile step, so that a shot boundary that moved by a frame or two
# between indexes still matches and one that moved by a scene does not.
SPAN_TOLERANCE = 0.5


def load_dir(directory, stem=None):
    """Every recorded profile in `directory` (for source `stem`, if given),
    as [{"start", "end", "rows"}] in time order. Files that are not profiles
    are skipped in silence - the directory is a probe run's output, not a
    curated input."""
    import json
    from pathlib import Path

    out = []
    for f in sorted(Path(directory).glob("*.json")):
        if stem and not f.stem.startswith(stem + "_s"):
            continue
        try:
            d = json.load(open(f))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(d, dict) or not isinstance(d.get("rows"), list) or not d["rows"]:
            continue
        start = float(d.get("start", 0.0))
        span = d.get("dur")
        if span is None:
            span = max(float(r["t"]) for r in d["rows"])
        out.append({"start": start, "end": round(start + float(span), 3),
                    "rows": d["rows"], "name": f.stem})
    return sorted(out, key=lambda p: p["start"])


def within(profiles, start, end, tolerance=SPAN_TOLERANCE):
    """The profiles whose span lies inside [start, end]. Pure."""
    return [p for p in (profiles or [])
            if p["start"] >= start - tolerance and p["end"] <= end + tolerance]


def source_seams(profiles):
    """Seam times on the source timeline over a list of profiles. Pure."""
    return sorted({t for p in (profiles or []) for t in seam_times(p["rows"], p["start"])})
