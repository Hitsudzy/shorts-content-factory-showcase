#!/usr/bin/env python3
"""CF-0336: no text element of a comparison line leaves the safe area.

Found on the widows-bay rebuild (pipeline/rebuilds/2026-09-23T0725Z): the
source badge's digit at x = 36-64 and the fact strip at x = 25-580, while the
safe area CF-0329 derived is x 125.3-851.0 - the digit and the first 3-4
letters of the fact were under the Shorts player's cut. The component drew
the element from `left: 0` and never read the margins.

The boxes come from `render/src/lib/comparisonGeometry.js`, the same pure
function ComparisonLine.jsx lays itself out with, run here under plain node:
checking a Python mirror of it would prove the mirror, not the frame. The safe
area is built exactly as lib/layout.js resolveSafeArea builds it, from the
zones scripts/safe_area.py derives.

Run: python3 tests/test_comparison_line_geometry.py
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
import random
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
AGENT_ROOT = HERE.parent
RENDER_SRC = AGENT_ROOT / "render" / "src"
sys.path.insert(0, str(AGENT_ROOT / "scripts"))

import comparison_line as cline  # noqa: E402
import safe_area  # noqa: E402

NODE = shutil.which("node")

# The line CF-0336 was found on, as the planner wrote it (plan.json of the
# widows-bay rebuild, 2026-09-23T0725Z).
WIDOWS_BAY = {
    "fact_id": "production_fact",
    "text": "Interiors were built at New England Studios, Devens, MA",
    "ref": 1, "publisher": "Wikipedia", "panel_w": 314,
}


def safe_area_px(zones, width, height):
    """lib/layout.js resolveSafeArea, line for line."""
    l, r, t, b = zones["left"], zones["right"], zones["top"], zones["bottom"]
    return {
        "top": round(height * t), "bottom": round(height * b),
        "left": round(width * l), "right": round(width * r),
        "innerWidth": round(width * (1 - l - r)),
    }


def geometry(cases):
    """Run comparisonGeometry() under node for every (line, safeArea, width)."""
    with tempfile.TemporaryDirectory() as tmp:
        mod = Path(tmp) / "comparisonGeometry.mjs"
        shutil.copy(RENDER_SRC / "lib" / "comparisonGeometry.js", mod)
        runner = Path(tmp) / "run.mjs"
        runner.write_text(
            "import {comparisonGeometry} from './comparisonGeometry.mjs';\n"
            "const cases = JSON.parse(process.argv[2]);\n"
            "console.log(JSON.stringify(cases.map((c) => comparisonGeometry(c))));\n")
        out = subprocess.run([NODE, str(runner), json.dumps(cases)],
                             capture_output=True, text=True, timeout=60, cwd=tmp)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)


TEXT_BOXES = ("numeral", "label", "name", "factTextBox")


def outside(geo, height_canvas, bottom_canvas):
    """Every text box that leaves the field, with how far, on the 1080 canvas."""
    f = geo["field"]
    x_min, x_max = f["x"], f["x"] + f["w"]
    y_min, y_max = f["y"], height_canvas - bottom_canvas
    bad = []
    for name in TEXT_BOXES:
        box = geo.get(name)
        if not box:
            continue
        if box["x"] < x_min - 1e-6:
            bad.append(f"{name}: x={box['x']:.1f} < {x_min:.1f}")
        if box["x"] + box["w"] > x_max + 1e-6:
            bad.append(f"{name}: right={box['x'] + box['w']:.1f} > {x_max:.1f}")
        if box["y"] < y_min - 1e-6:
            bad.append(f"{name}: y={box['y']:.1f} < {y_min:.1f}")
        if box["y"] + box["h"] > y_max + 1e-6:
            bad.append(f"{name}: bottom={box['y'] + box['h']:.1f} > {y_max:.1f}")
    return bad


def _check(lines, width=1080, height=1920, zones=None):
    zones = zones or safe_area.safe_zones()
    sa = safe_area_px(zones, width, height)
    geos = geometry([{"line": l, "safeArea": sa, "width": width} for l in lines])
    k = width / 1080
    for line, geo in zip(lines, geos):
        bad = outside(geo, height / k, sa["bottom"] / k)
        assert not bad, f"{line.get('text') or line.get('publisher')!r}: {bad}"
    return geos


def test_widows_bay_is_inside_the_field():
    """The defect's own line: the digit and every letter of the fact inside
    x 125.3-851.0 (the task's acceptance numbers)."""
    geo, = _check([WIDOWS_BAY])
    # (the field is whole pixels, as resolveSafeArea rounds it: 125, 726)
    assert geo["anchor"]["x"] >= 125 and geo["fact"]["x"] >= 125
    assert geo["numeral"]["x"] > 125.28, geo["numeral"]
    right = geo["factTextBox"]["x"] + geo["factTextBox"]["w"]
    assert right <= 851.0, right
    # the strip ends at x = 620 as it did before CF-0336, so it wraps at
    # 495 - 2*28 = 439 px: 21 glyphs of 20.4 px, three lines for this fact
    assert geo["fact"]["x"] + geo["fact"]["w"] == 620, geo["fact"]
    assert geo["factTextBox"]["textW"] == 439
    assert len(geo["factLines"]) == 3, geo["factLines"]


def test_the_old_geometry_is_what_this_refuses():
    """The check can fail: a field starting at x = 0 would have passed the
    old component, and against the real field its digit is outside."""
    sa0 = safe_area_px({"left": 0, "right": 0, "top": 0.12, "bottom": 0.28}, 1080, 1920)
    geo, = geometry([{"line": WIDOWS_BAY, "safeArea": sa0, "width": 1080}])
    real = safe_area_px(safe_area.safe_zones(), 1080, 1920)
    geo["field"] = {"x": real["left"], "y": real["top"], "w": real["innerWidth"]}
    bad = outside(geo, 1920, real["bottom"])
    assert any(b.startswith("numeral: x=") for b in bad), bad
    assert any(b.startswith("factTextBox: x=") for b in bad), bad


def test_the_widest_badge_and_the_longest_fact_fit():
    """The planner's two ceilings: a panel of PANEL_MAX_W and a fact of
    FACT_MAX_CHARS, with and without the badge, and a tenth-source digit."""
    name = "W" * int((cline.PANEL_MAX_W - 2 * cline.PANEL_PADDING)
                     / (cline.NAME_SIZE * cline.MONO_ADVANCE))
    rng = random.Random(336)
    words = ("the", "studio", "built", "interiors", "Massachusetts", "in", "a",
             "former", "army", "base", "sets", "were", "Devens,", "MA")
    facts = []
    for _ in range(40):
        t = ""
        while True:
            w = rng.choice(words)
            if len(t) + 1 + len(w) > cline.FACT_MAX_CHARS:
                break
            t = f"{t} {w}".strip()
        facts.append(t)
    lines = [{"text": f, "ref": 9, "publisher": name, "panel_w": cline.PANEL_MAX_W}
             for f in facts]
    lines += [{"text": f} for f in facts[:10]]
    lines += [{"ref": 9, "publisher": name, "panel_w": cline.PANEL_MAX_W}]
    _check(lines)


def test_the_margins_scale_with_the_composition():
    """A composition other than 1080 wide: the component scales by
    width / 1080, and the margins are divided back onto the canvas."""
    _check([WIDOWS_BAY], width=720, height=1280)


def test_the_strip_covers_no_more_of_the_picture_than_before():
    """CF-0336 rework. The strip at full field width (to x = 851) covered the
    lower half of a small centred face on widows-bay block 18 and qc_render's
    face gate (CF-0294) failed where the pre-CF-0336 render passed. Moving
    the element right by the left margin is the fix; widening it into the
    centre of the picture is not. The strip's right edge stays where it was
    before CF-0336 (x = 620), for every fact the planner can write, with and
    without the badge."""
    lines = [WIDOWS_BAY, {"text": WIDOWS_BAY["text"]},
             {"text": "x" * 20 + " " + "y" * 20 + " " + "z" * 18,
              "ref": 3, "publisher": "Variety", "panel_w": 224}]
    for geo in _check(lines):
        assert geo["fact"]["x"] + geo["fact"]["w"] <= 620, geo["fact"]
        # and the strip's height stays far above the caption band
        assert geo["fact"]["y"] + geo["fact"]["h"] < 900, geo["fact"]


def test_the_component_draws_the_geometry():
    """The boxes above are the ones drawn: the anchor, the panel and the
    strip are placed from comparisonGeometry, and nothing is flush with
    x = 0 any more."""
    comp = (RENDER_SRC / "components" / "ComparisonLine.jsx").read_text()
    video = (RENDER_SRC / "Video.jsx").read_text()
    assert "comparisonGeometry({line, safeArea, width})" in comp
    for placed in ("left: geo.anchor.x", "left: geo.panel.x", "left: geo.fact.x",
                   "top: geo.fact.y"):
        assert placed in comp, placed
    assert "<ComparisonLine" in video and "safeArea={safeArea}" in \
        video.split("<ComparisonLine")[1].split("/>")[0]


TESTS = [v for k, v in dict(globals()).items() if k.startswith("test_")]

if __name__ == "__main__":
    if not NODE:
        # Not a skip: without node none of these checks ran, and the runner
        # has to see them as missing rather than as a green 0/0.
        print("FAIL: node is not on PATH - the geometry is JavaScript")
        print(f"0/{len(TESTS)} passed")
        sys.exit(1)
    passed = 0
    for fn in TESTS:
        try:
            fn()
            print(f"PASS {fn.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL {fn.__name__}: {e}")
    print(f"\n{passed}/{len(TESTS)} passed")
    sys.exit(0 if passed == len(TESTS) else 1)
