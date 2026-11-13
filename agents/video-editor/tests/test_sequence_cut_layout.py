#!/usr/bin/env python3
"""CF-0893: the freeze and brightness gates lay a `sequence` block out cut by
cut on the cuts' own screen time - the layout the subject gate got in CF-0892.

Video.jsx mounts every block RENDER_CROSSFADE (0.35 s) before its `start`
(clamped at zero) and AssetLayer.jsx starts cut k `sum(seconds before it)`
after that mount. frozen_blocks() (through probe_targets()) and
lifted_pictures() walked the cuts from `block.start` instead, so each cut
boundary they judged sat 0.35 s after the real one: the last 0.35 s of cut
k's window was cut k+1's picture, and the first 0.35 s of cut k+1 was judged
as nobody's. A frozen head of cut k+1 could hide under the threshold that
way (the stand-in below: 1.85 s still from the real cut, 1.50 s of it seen).

No media, no ffmpeg: the render's motion sweep and the brightness probe are
stand-ins (monkeypatched), and a source clip is an empty file in a tmp dir
whose duration is a stand-in too.
"""
import _isolated_runlog  # noqa: F401,E402 - run accounting never lands in a real batch
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "scripts"))
sys.path.insert(0, str(HERE))

import qc_render  # noqa: E402
from common import (MAX_HELD_RUN, PROBE_GAP, RENDER_CROSSFADE,  # noqa: E402
                    source_time)

EPS = 1e-6


def _seq(start, end, cuts):
    return {"start": start, "end": end,
            "asset": {"kind": "sequence", "cuts": cuts}}


def _clip(seconds, src="/a.mp4", **kw):
    return {"kind": "clip", "seconds": seconds, "src": src, **kw}


def _close(a, b):
    return abs(a - b) < EPS


class patched:
    """Swap module attributes for the length of a `with`."""

    def __init__(self, mod, **names):
        self.mod, self.names, self.old = mod, names, {}

    def __enter__(self):
        for k, v in self.names.items():
            self.old[k] = getattr(self.mod, k)
            setattr(self.mod, k, v)
        return self

    def __exit__(self, *exc):
        for k, v in self.old.items():
            setattr(self.mod, k, v)


# --------------------------------------------------------------------------
# the layout
# --------------------------------------------------------------------------

def test_cuts_are_laid_out_from_the_mount_not_from_block_start():
    block = _seq(10.0, 16.0, [_clip(3.0), _clip(2.0), _clip(1.5)])
    lay = qc_render.sequence_cuts(block)
    mount = 10.0 - RENDER_CROSSFADE
    want = [(0, mount, 10.0, mount + 3.0),
            (1, mount + 3.0, mount + 3.0, mount + 5.0),
            (2, mount + 5.0, mount + 5.0, 16.0)]
    got = [(k, on, s, e) for k, _cut, on, s, e in lay]
    assert all(g[0] == w[0] and all(_close(x, y) for x, y in zip(g[1:], w[1:]))
               for g, w in zip(got, want)) and len(got) == 3, got


def test_the_opening_block_mounts_at_zero():
    lay = qc_render.sequence_cuts(_seq(0.1, 4.0, [_clip(1.0), _clip(3.0)]))
    (_, _, on0, s0, e0), (_, _, on1, s1, e1) = lay
    assert (on0, s0) == (0.0, 0.1) and _close(e0, 1.0), lay
    assert _close(on1, 1.0) and _close(s1, 1.0) and e1 == 4.0, lay


def test_every_gate_reads_the_same_cut_windows():
    """probe_targets (the freeze gate), lifted_pictures (brightness) and
    subject_pictures (CF-0892) agree on where each cut is on screen."""
    face = {"roi_source": "faces", "focus": {"x": 0.5, "y": 0.4},
            "presentation": {"luma_lift": {"gain": 1.3}}}
    block = _seq(10.0, 16.0, [_clip(3.0, **face), _clip(2.0, **face),
                              _clip(1.5, **face)])
    lay = [(s, e) for _k, _c, _on, s, e in qc_render.sequence_cuts(block)]
    freeze = [(b["start"], b["end"]) for b, *_ in qc_render.probe_targets(block, 0)]
    lift = [(s, e) for _i, _k, s, e, _h in
            qc_render.lifted_pictures({"blocks": [block]})]
    subj = [(v["start"], v["end"]) for _k, v, _src in
            qc_render.subject_pictures(block)]
    assert freeze == lay == lift == subj, (freeze, lay, lift, subj)


def test_a_cut_is_read_on_its_own_clip_clock():
    """The freeze gate's second look reads the source where the render is:
    at the cut's first on-screen second, start_seconds plus the time since
    the cut was mounted."""
    block = _seq(10.0, 16.0, [_clip(3.0, start_seconds=7.0),
                              _clip(3.0, start_seconds=5.0)])
    (c0, *_), (c1, *_) = qc_render.probe_targets(block, 2)
    clock0 = {**c0, "start": c0["clock_start"]}
    clock1 = {**c1, "start": c1["clock_start"]}
    # cut 0 has been playing for the crossfade when the block's own seconds begin
    assert _close(source_time(clock0, 10.0), 7.0 + RENDER_CROSSFADE)
    assert _close(source_time(clock1, c1["start"]), 5.0), c1
    # the same clocks the subject gate anchors its cuts with
    subj = qc_render.sequence_cuts(block)
    assert _close(c1["clock_start"], subj[1][2] + RENDER_CROSSFADE)


def test_the_freeze_verdict_reads_the_cut_clock():
    """A cut whose clip ran out is told how far the block played it on the
    cut's own clock (3.35 s here), not on its span's (3.70 s)."""
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "clip.mp4"
        src.write_bytes(b"")
        block = _seq(10.0, 16.0, [_clip(3.0, src=str(src)),
                                  _clip(3.0, src=str(src))])
        _c0, (c1, *_rest) = qc_render.probe_targets(block, 0)
        with patched(qc_render, media_duration=lambda _p: 0.1):
            fault, reason, _m = qc_render.freeze_verdict(
                c1, qc_render.probe_times(c1), tmp, "t")
    assert fault is True and "plays it to 3.35s" in reason, reason


# --------------------------------------------------------------------------
# the freeze gate at a cut boundary
# --------------------------------------------------------------------------

def _timeline(still, start=9.0, end=16.0, step=0.05):
    """A stand-in for motion_timeline(): a window every `step` s, still when
    it lies wholly inside one of the `still` stretches, moving otherwise (a
    window across a cut measures the cut)."""
    out, t = [], start
    while t + PROBE_GAP <= end + EPS:
        quiet = any(a - EPS <= t and t + PROBE_GAP <= b + EPS for a, b in still)
        out.append((round(t, 3), 0.2 if quiet else 5.0))
        t += step
    return out


def test_a_frozen_head_of_the_next_cut_is_caught_at_the_real_boundary():
    """Cut 1 is on screen from 12.65 s (10.0 - 0.35 + 3.0) and stuck for its
    first 1.85 s - over MAX_HELD_RUN. Walked from block.start the gate saw
    only 13.00-14.50 of it (1.50 s, under) and passed it; on the real layout
    it is caught, named cut 1, from 12.65 s."""
    real_cut = 10.0 - RENDER_CROSSFADE + 3.0
    still = [(real_cut, real_cut + 1.85)]
    assert 1.85 >= MAX_HELD_RUN > 1.85 - RENDER_CROSSFADE
    block = _seq(10.0, 16.0, [_clip(3.0), _clip(3.0)])
    asked = []

    def verdict(blk, _times, _tmp, tag):
        asked.append((tag, blk["start"], blk["end"]))
        return True, "stand-in", None

    with patched(qc_render, motion_timeline=lambda *_a, **_k: _timeline(still),
                 freeze_verdict=verdict):
        rows = qc_render.frozen_blocks("unused.mp4", {"blocks": [block]})
    assert [r.get("cut") for r in rows] == [1], rows
    assert rows[0]["still_run_at"] == round(real_cut, 2), rows
    assert rows[0]["still_run"] >= MAX_HELD_RUN, rows
    assert [a[0] for a in asked] == ["b0c1"] and _close(asked[0][1], real_cut), asked


def test_a_moving_cut_is_not_charged_with_the_next_ones_still_tail():
    """Cut 0 moves for all of its real screen time; the 0.35 s after its real
    end is cut 1 (still). Nothing is recorded against cut 0."""
    real_cut = 10.0 - RENDER_CROSSFADE + 3.0
    block = _seq(10.0, 16.0, [_clip(3.0), _clip(3.0)])
    with patched(qc_render,
                 motion_timeline=lambda *_a, **_k: _timeline([(real_cut, 16.0)]),
                 freeze_verdict=lambda *_a: (True, "stand-in", None)):
        rows = qc_render.frozen_blocks("unused.mp4", {"blocks": [block]})
    assert [r.get("cut") for r in rows] == [1], rows


# --------------------------------------------------------------------------
# the brightness gate
# --------------------------------------------------------------------------

def test_a_lifted_cut_is_sampled_inside_its_own_screen_time():
    """Cut 1's three brightness samples land between 12.65 s and 16.0 s - none
    of them on cut 0, none of them on the 0.35 s the old walk lost."""
    lifted = {"presentation": {"luma_lift": {"gain": 1.4, "luma_before": 20,
                                             "luma_after": 28}}}
    block = _seq(10.0, 16.0, [_clip(3.0), _clip(3.0, **lifted)])
    seen = []

    def luma(_video, at, _vf, _tmp, _tag):
        seen.append(at)
        return 40.0

    with patched(qc_render, region_luma=luma):
        [rec] = qc_render.lifted_blocks("unused.mp4", {"blocks": [block]})
    real_cut = 10.0 - RENDER_CROSSFADE + 3.0
    span = 16.0 - real_cut
    want = [round(real_cut + span * f, 3) for f in qc_render.LIFT_PROBE_FRACTIONS]
    assert seen == want, (seen, want)
    assert rec["cut"] == 1 and rec["at"] == round(real_cut + span / 2, 3), rec


def test_plain_blocks_are_untouched():
    clip = {"start": 4.0, "end": 7.0,
            "asset": {"kind": "clip", "src": "/a.mp4",
                      "presentation": {"luma_lift": {"gain": 1.2}}}}
    [(blk, _vf, tag, _side)] = qc_render.probe_targets(clip, 3)
    assert blk is clip and tag == "b3"
    assert qc_render.lifted_pictures({"blocks": [clip]}) == [
        (0, None, 4.0, 7.0, clip["asset"])]


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
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
