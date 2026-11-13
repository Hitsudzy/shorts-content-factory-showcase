#!/usr/bin/env python3
"""CF-0122/CF-0155: what resolve_anchors.usable() probes on a cut clip, and
against which window it judges what it finds.

The defect this file was written for (CF-0122): the gate probed 0.5s and
`max(0.6, seconds / 2)`, so the second frame moved with the block length the
rhythm happened to ask for. Measured on the real clip (SJVmeJaS44s shot 1,
4.922-23.398s, cut at its head, qc_asset.py at every 0.25s, 2026-09-06):

    0.00-0.50s  fade-in, Vision finds nothing  -> animation_center, cov 1.00  PASS
    0.60-2.75s  wide compartment, no face      -> saliency,   cov 0.30-0.52  FAIL
    3.00-5.25s  face found                     -> faces,      cov 0.69-1.00  PASS
    5.50-7.25s  face lost again                -> saliency,   cov 0.26-0.32  FAIL

so a 6.25s block (probes 0.5 and 3.12) passed and a 5.41s block of the very
same clip failed - RUN_LOG.txt:27 of the 2026-09-03T2037Z run.

CF-0155 replaced that with two things, and this file pins both:

  1. The probes are PROBE_FRAMES frames of the window the block will actually
     show, taken in ONE ffmpeg pass and positioned by the clip alone. The
     first of them is PROBE_OFFSET, the frame build_render_plan.py frames the
     whole asset from.

  2. Every probe is judged against *that* frame's window - the rectangle the
     renderer will really display - and not against its own best crop. The
     first call asks qc_asset.py for `--window self` and the framing it
     answers with is carried onto every later call as `--window x,y`. Before
     CF-0155 each frame was measured against a window nothing downstream
     uses, which is why the verdict followed Vision's detector switching
     between neighbouring frames rather than the picture.

  3. The invariant that follows, and that CF-0122 could only record as an
     expected failure: showing MORE of the same clip cannot make it MORE
     usable. Every frame the shorter window probed is inside the longer one's
     window, and the rule is still "every probed frame passes", so a clip
     that failed short cannot pass long.

qc_asset.py and ffmpeg are faked: the profile above is replayed by offset, so
the test needs neither Vision nor a clip on disk and runs in milliseconds.
What the fake answers is a *per-frame* verdict; which window that verdict was
measured against is asserted from the argv the gate builds, which is the half
of CF-0155 a replayed profile cannot express.

No pytest dependency - plain asserts, run directly.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))

import resolve_anchors  # noqa: E402

# Measured qc_asset.py verdicts along the cut clip (seconds -> usable).
# Between the samples the profile is piecewise constant, which is what the
# real clip did at 0.25s resolution.
MEASURED_PROFILE = [
    (0.00, True), (0.60, False), (3.00, True), (5.50, False), (7.50, False),
]

# The framing the fake planner frame hands back - build_render_plan.framing()'s
# `focus`/`zoom`, which is what the renderer points this clip with.
WINDOW_FOCUS = (0.31, 0.44)
WINDOW_ZOOM = 1.0


def frame_is_usable(offset):
    verdict = MEASURED_PROFILE[0][1]
    for t, ok in MEASURED_PROFILE:
        if offset >= t:
            verdict = ok
    return verdict


class FakeGate:
    """Stands in for subprocess.run inside resolve_anchors.usable(): the
    ffmpeg call "extracts" its frames in one pass (creating the pngs so the
    gate finds them) and the qc_asset.py calls answer from the measured
    profile, keyed by which of those frames is being judged.

    `passes` records the ffmpeg passes, `offsets` the moments they sampled and
    `windows` the `--window` argument each qc_asset.py call carried."""

    def __init__(self, failed="subject"):
        # CF-0435: which qc_asset.py check the profile's bad frames fail. A
        # framing miss (`coverage`) is soft now - the clip is shown and
        # priced - so the monotonicity pins below are asked of a hard miss
        # (`subject`) for the verdict and of the soft one for its price.
        self.failed = failed
        self.passes = []
        self.offsets = []
        self.windows = []

    def __call__(self, cmd, **kw):
        cmd = [str(c) for c in cmd]
        if "-frames:v" in cmd:
            first = float(cmd[cmd.index("-ss") + 1])
            step = float(cmd[cmd.index("-vf") + 1].split("fps=1/")[1])
            count = int(cmd[cmd.index("-frames:v") + 1])
            self.passes.append({"first": first, "step": round(step, 3), "count": count})
            self.offsets = [round(first + k * step, 3) for k in range(count)]
            for k in range(count):
                Path(cmd[-1].replace("%02d", f"{k + 1:02d}")).write_bytes(b"png")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        assert cmd[1].endswith("qc_asset.py"), cmd
        index = int(re.search(r"\.probe_(\d+)\.png$", cmd[2]).group(1)) - 1
        window = cmd[cmd.index("--window") + 1] if "--window" in cmd else None
        self.windows.append(window)
        ok = frame_is_usable(self.offsets[index])
        verdict = {"usable": ok, "failed": [] if ok else [self.failed],
                   "failures": [] if ok else [
                       f"framing: the window this block is framed with keeps 30% "
                       f"of the subject at {self.offsets[index]:.1f}s"],
                   "relaxations": [],
                   "coverage_window": {"focus": {"x": WINDOW_FOCUS[0],
                                                 "y": WINDOW_FOCUS[1]},
                                       "zoom": WINDOW_ZOOM, "fit": "cover"}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(verdict), "")


def gate(seconds, fake=None, soft=None):
    fake = fake or FakeGate()
    real = resolve_anchors.subprocess.run
    resolve_anchors.subprocess.run = fake
    try:
        with tempfile.TemporaryDirectory() as d:
            clip = Path(d) / "a01_SJVmeJaS44s_s001.mp4"
            clip.write_bytes(b"mp4")
            ok, failures = resolve_anchors.usable(str(clip), seconds, 720, 0.65, 0.9,
                                                  soft_out=soft)
            leftover = sorted(p.name for p in Path(d).glob("*.png"))
    finally:
        resolve_anchors.subprocess.run = real
    return ok, failures, fake, leftover


# --- 1. what the gate probes ------------------------------------------------

def test_the_probes_are_the_window_the_block_will_show():
    """PROBE_FRAMES frames from PROBE_OFFSET to the end of the block, and the
    planner's own frame is the first of them - every other probe is judged
    against the window taken from it."""
    for seconds in (6.25, 5.41, 17.6):
        _, _, fake, _ = gate(seconds)
        expected = resolve_anchors.probe_offsets(seconds)
        assert len(expected) == resolve_anchors.PROBE_FRAMES, expected
        assert expected[0] == resolve_anchors.PROBE_OFFSET, expected
        assert fake.offsets == expected, (fake.offsets, expected)
        assert expected[-1] < seconds, expected


def test_the_frames_cost_one_ffmpeg_pass():
    """CF-0155's budget: four frames of one clip in one pass, not one seek per
    frame - which is what made four frames cheaper than the two the gate used
    to take."""
    _, _, fake, leftover = gate(6.25)
    assert len(fake.passes) == 1, fake.passes
    assert fake.passes[0]["count"] == resolve_anchors.PROBE_FRAMES, fake.passes
    assert leftover == [], f"probe frames left behind: {leftover}"


def test_every_probe_after_the_first_is_judged_against_the_planners_window():
    """The whole of CF-0155: the first probe is the frame build_render_plan.py
    frames the asset from (`--window self`), and its answer - not each frame's
    own best crop - is what the rest are measured against."""
    _, _, fake, _ = gate(17.6)
    assert fake.windows[0] == "self", fake.windows
    assert len(fake.windows) > 1, fake.windows
    assert all(w == f"{WINDOW_FOCUS[0]},{WINDOW_FOCUS[1]}" for w in fake.windows[1:]), \
        fake.windows


# --- 2. what it does with them ----------------------------------------------

def test_run_log_27_no_longer_follows_the_block_length():
    """The lengths of RUN_LOG.txt:27, which used to split into passes and
    failures on one clip. All of their windows contain the 0.6-3.0s stretch
    where this clip has no subject the framing keeps, so all of them fail -
    one clip, one answer."""
    verdicts = {seconds: gate(seconds)[0] for seconds in
                (2.68, 4.17, 5.33, 5.41, 6.25, 7.2, 17.6)}
    assert set(verdicts.values()) == {False}, verdicts
    _, failures, _, _ = gate(6.25)
    assert failures and "framing" in failures[0], failures
    # CF-0435: the same profile failing on framing alone is a weak clip, not
    # an unusable one - every length is shown, and every length is priced
    # the same (one clip, one answer, now about its price).
    for seconds in (2.68, 4.17, 5.33, 5.41, 6.25, 7.2, 17.6):
        soft = []
        ok, failures, _, _ = gate(seconds, FakeGate("coverage"), soft)
        assert ok and failures == [] and soft == ["low_framing"], (seconds, soft)


def test_more_of_the_same_clip_cannot_be_more_usable():
    """Monotonicity over the cut window (CF-0122's expected failure, now a real
    check): [0, 5.41s] of this clip is unusable, so [0, 6.25s] - the same
    stretch and more - cannot be usable. It used to be, because 6.25/2 happened
    to land on the one stretch where Vision finds a face."""
    assert not gate(5.41)[0]
    assert not gate(6.25)[0], (
        "the 6.25s window of a clip whose 5.41s window failed passed the gate: "
        "the verdict follows the requested length, not the clip")
    seen_failure = False
    for tenths in range(10, 200):
        ok = gate(tenths / 10)[0]
        assert not (seen_failure and ok), (
            f"{tenths / 10}s of this clip passed after a shorter window of it "
            f"failed - the verdict is not monotone in the block length")
        seen_failure = seen_failure or not ok
    assert seen_failure
    # CF-0435: nor can more of the same clip be *less weak*.
    seen_soft = False
    for tenths in range(10, 200):
        soft = []
        gate(tenths / 10, FakeGate("coverage"), soft)
        assert not (seen_soft and not soft), (
            f"{tenths / 10}s of this clip lost the framing price a shorter "
            f"window of it carried")
        seen_soft = seen_soft or bool(soft)
    assert seen_soft


def test_a_clip_that_is_good_all_through_still_passes():
    """The gate did not simply get stricter about everything: a clip whose
    every probed frame passes is accepted, and it is accepted at every
    length."""
    real_profile = MEASURED_PROFILE[:]
    try:
        MEASURED_PROFILE[:] = [(0.0, True)]
        assert all(gate(seconds)[0] for seconds in (2.68, 6.25, 17.6))
    finally:
        MEASURED_PROFILE[:] = real_profile


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    failed = 0
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except Exception:
            failed += 1
            print(f"FAIL {t.__name__}")
            traceback.print_exc()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
