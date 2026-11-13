#!/usr/bin/env python3
"""CF-0329: the safe area must survive the player's own cut, not just its overlays.

The regression is the channel's first published Short (`jLolLMW5AbI`,
2026-09-23): a 1080x1920 master shown full-height on a phone narrower than
9:16 loses the sides, the left safe zone was 0.04, and the left edge of the
proof card, the captions and the watermark went off-screen. Every plan this
factory wrote between 2026-08-28 and that day carried the same 0.04.

No pytest dependency - plain asserts, run directly (matches this directory's
other tests).
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import safe_area  # noqa: E402

PASS, FAIL = [], []


def check(name, cond, detail=""):
    (PASS if cond else FAIL).append(name)
    print(("PASS " if cond else "FAIL ") + name + (f" - {detail}" if detail and not cond else ""))


def test_the_cut_is_geometry_not_taste():
    """VISIBLE_WIDTH and CROP_PER_SIDE follow from the two aspects, nothing else."""
    want_visible = safe_area.NARROWEST_SCREEN_ASPECT / safe_area.FRAME_ASPECT
    check("the visible width is the ratio of the two aspects",
          abs(safe_area.VISIBLE_WIDTH - want_visible) < 1e-12)
    check("the cut is what is left over, halved",
          abs(safe_area.CROP_PER_SIDE - (1 - want_visible) / 2) < 1e-12)
    # 20:9 against 9:16 keeps four fifths of the width - the number this
    # module is built on, spelled out so a silent edit of either aspect fails
    # here rather than in a render three days later.
    check("20:9 keeps 0.80 of the frame's width and cuts 0.10 per side",
          abs(safe_area.VISIBLE_WIDTH - 0.80) < 1e-9
          and abs(safe_area.CROP_PER_SIDE - 0.10) < 1e-9,
          f"visible={safe_area.VISIBLE_WIDTH}, cut={safe_area.CROP_PER_SIDE}")


def test_both_side_zones_clear_the_cut():
    z = safe_area.safe_zones()
    for side in ("left", "right"):
        check(f"the {side} zone clears the cut",
              z[side] >= safe_area.CROP_PER_SIDE,
              f"{side}={z[side]} < {safe_area.CROP_PER_SIDE}")
    check("the side zones are the cut plus the overlay, converted to frame fractions",
          abs(z["left"] - (safe_area.CROP_PER_SIDE
                           + safe_area.OVERLAY["left"] * safe_area.VISIBLE_WIDTH)) < 5e-5
          and abs(z["right"] - (safe_area.CROP_PER_SIDE
                                + safe_area.OVERLAY["right"] * safe_area.VISIBLE_WIDTH)) < 5e-5)
    check("the vertical zones are overlay only - nothing is cut off the height",
          z["top"] == round(safe_area.OVERLAY["top"], 4)
          and z["bottom"] == round(safe_area.OVERLAY["bottom"], 4))
    check("something is left to draw in",
          1 - z["left"] - z["right"] > 0.6 and 1 - z["top"] - z["bottom"] > 0.5,
          f"inner {1 - z['left'] - z['right']:.3f} x {1 - z['top'] - z['bottom']:.3f}")


def test_the_published_defect_is_refused():
    """The exact numbers every pre-CF-0329 plan carried must not pass."""
    shipped = {"top": 0.06, "bottom": 0.18, "left": 0.04, "right": 0.16}
    bad = safe_area.survives_the_cut(shipped)
    sides = [s for s, _, _ in bad]
    check("the safe zones of every video shipped before 2026-09-23 are refused",
          "left" in sides, f"survives_the_cut said {bad}")
    check("the right zone of those plans was wide enough on its own",
          "right" not in sides, f"survives_the_cut said {bad}")
    check("today's zones pass", safe_area.survives_the_cut(safe_area.safe_zones()) == [])
    check("a plan that names no zone at all falls through to the default, not to a failure",
          safe_area.survives_the_cut(None) == []
          and safe_area.survives_the_cut({}) == [])
    check("a side the plan does not name is left to the default",
          safe_area.survives_the_cut({"left": 0.2}) == [])
    check("a side the plan names too narrow is refused even when the other is fine",
          [s for s, _, _ in safe_area.survives_the_cut({"left": 0.2, "right": 0.05})] == ["right"])


def test_the_planner_writes_the_derived_zones():
    """No second copy of the numbers in the planner - it asks this module."""
    src = (Path(__file__).resolve().parents[1] / "scripts" / "build_render_plan.py").read_text()
    check("the planner calls safe_area.safe_zones()", "safe_area.safe_zones()" in src)
    check("the planner no longer types the pre-CF-0329 numbers",
          '"left": 0.04' not in src)


if __name__ == "__main__":
    import traceback
    for name, fn in [(k, v) for k, v in list(globals().items()) if k.startswith("test_")]:
        try:
            fn()
        except Exception:
            FAIL.append(name)
            print(f"FAIL {name}")
            traceback.print_exc()
    print(f"\n{len(PASS)}/{len(PASS) + len(FAIL)} passed")
    sys.exit(1 if FAIL else 0)
