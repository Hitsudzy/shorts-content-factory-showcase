#!/usr/bin/env python3
"""CF-0923: the comparison line (source badge + fact strip) never crosses an
own graphic's title, whatever the card's row count.

Found on Tech 08.11 (pipeline/example-tech/2026-11-08T0832Z): on airbnb,
anthropic, claude-code and github - every block our own graphic - the badge
«[1] Wikipedia» and the strip under it sat over the card's title for the
3-5 s the line holds. The graphic was centred in a box starting at
safeArea.top + 70 and knew nothing of the line pinned at y 260 .. ~630.

The boxes come from `render/src/lib/graphicClear.js` (with the
comparisonGeometry.js and captionBand.js it imports) - the same pure functions
Video.jsx and GraphicLayer.jsx lay the frame out with - run under plain node,
no browser, no render. The four lines are the batch's own (plan.json
comparison_lines[], copied here; the test reads no batch).

Run: python3 tests/test_graphic_clear_geometry.py
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import json
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
W, H = 1080, 1920
CROSSFADE = 0.35  # Video.jsx

# The batch's four lines (comparison_lines[] of each plan.json, 08.11).
TECH_0811 = [
    {"fact_id": "production_fact", "text": "GitHub reported more than 420 million repositories",
     "start_s": 4.54, "end_s": 8.08, "ref": 1, "publisher": "Wikipedia", "panel_w": 314},
    {"fact_id": "production_fact", "text": "Series A shares sold for $0.21 each, split adjusted",
     "start_s": 29.62, "end_s": 39.24, "ref": 1, "publisher": "Wikipedia", "panel_w": 314},
    {"fact_id": "production_fact", "text": "AMD to invest up to $5 billion in Anthropic",
     "start_s": 8.34, "end_s": 13.25, "ref": 1, "publisher": "Wikipedia", "panel_w": 314},
    {"fact_id": "production_fact",
     "text": "Sept. 2026: Cowork tab folded into regular conversations",
     "start_s": 36.72, "end_s": 40.3, "ref": 1, "publisher": "Wikipedia", "panel_w": 314},
]

# The panel's layout height for 1..4 spec-card rows and a title that wraps
# (SpecCard + GraphicLayer padding, estimated generously), then panels far
# taller than any box - the fit has to hold for every one of them.
PANEL_HEIGHTS = [300, 420, 597, 795, 857, 1000, 1400, 2400]


def safe_area_px(zones, width, height):
    """lib/layout.js resolveSafeArea, line for line."""
    l, r, t, b = zones["left"], zones["right"], zones["top"], zones["bottom"]
    return {"top": round(height * t), "bottom": round(height * b),
            "left": round(width * l), "right": round(width * r),
            "innerWidth": round(width * (1 - l - r))}


RUNNER = r"""
import {comparisonGeometry} from './comparisonGeometry.js';
import {reserveTopFor, contentBox, panelRect, lineOverBlock} from './graphicClear.js';
const cases = JSON.parse(process.argv[2]);
const out = cases.map((c) => {
  const zone = {x: 0, y: 0, width: c.width, height: c.height};
  const line = c.line;
  const block = c.block;
  const g = line ? comparisonGeometry({line, safeArea: c.safeArea, width: c.width}) : null;
  const plaque = g ? [g.anchor, g.panel, g.fact].filter(Boolean).map((b) => ({
    x: b.x * g.k, y: b.y * g.k, w: b.w * g.k, h: b.h * g.k})) : [];
  const reserve = reserveTopFor(block, line ? [line] : [], c.safeArea, c.width, c.pad);
  const box = contentBox(zone, c.safeArea, c.width, c.height, c.noReserve ? null : reserve);
  const panels = c.heights.map((h) => panelRect(box, h));
  return {plaque, reserve, box, panels, over: line ? lineOverBlock(line, block, c.pad) : false};
});
console.log(JSON.stringify(out));
"""


def run(cases):
    with tempfile.TemporaryDirectory() as tmp:
        for name in ("graphicClear.js", "comparisonGeometry.js", "captionBand.js"):
            shutil.copy(RENDER_SRC / "lib" / name, Path(tmp) / name)
        (Path(tmp) / "package.json").write_text('{"type": "module"}')
        (Path(tmp) / "run.js").write_text(RUNNER)
        out = subprocess.run([NODE, "run.js", json.dumps(cases)],
                             capture_output=True, text=True, timeout=60, cwd=tmp)
        assert out.returncode == 0, out.stderr
        return json.loads(out.stdout)


def case(line, block=None, heights=PANEL_HEIGHTS, zones=None, no_reserve=False):
    sa = safe_area_px(zones or safe_area.safe_zones(), W, H)
    block = block or {"start": line["start_s"], "end": line["end_s"]}
    return {"line": line, "block": block, "safeArea": sa, "width": W, "height": H,
            "pad": CROSSFADE, "heights": heights, "noReserve": no_reserve}


def crosses(a, b):
    """Two rectangles share a pixel (a: x/y/w/h, b: x/y/width/height)."""
    return (a["x"] < b["x"] + b["width"] and b["x"] < a["x"] + a["w"]
            and a["y"] < b["y"] + b["height"] and b["y"] < a["y"] + a["h"])


def title_row(panel):
    """The panel's top strip - where every template draws its title. Taken as
    the whole top third, which is more than any title row."""
    return {"x": panel["x"], "y": panel["y"], "width": panel["width"],
            "height": panel["height"] / 3}


def _assert_clear(results, lines):
    for line, res in zip(lines, results):
        assert res["over"], line
        assert res["plaque"], line
        for panel in res["panels"]:
            for p in res["plaque"]:
                assert not crosses(p, panel), (line["text"], p, panel)
                assert not crosses(p, title_row(panel)), (line["text"], p, panel)
            # and the fit keeps the panel inside its box - above the caption band
            box = res["box"]
            assert panel["y"] >= box["y"] - 1e-6, (panel, box)
            assert panel["y"] + panel["height"] <= box["y"] + box["height"] + 1e-6, (panel, box)


def test_tech_0811_lines_clear_every_card():
    """The batch's four lines: no card of any row count crosses the badge or
    the strip, and every card stays inside its box."""
    lines = TECH_0811
    _assert_clear(run([case(l) for l in lines]), lines)


def test_the_old_layout_is_what_this_refuses():
    """The check can fail: the box as it was (no reserve) puts a two-row
    card's title under the github strip - the defect itself."""
    res, = run([case(TECH_0811[0], heights=[597], no_reserve=True)])
    panel = res["panels"][0]
    assert any(crosses(p, title_row(panel)) for p in res["plaque"]), (res["plaque"], panel)


def test_any_strip_length_and_badge_alone_or_strip_alone():
    """From a one-word fact to the planner's FACT_MAX_CHARS ceiling, with the
    badge, without it, and the badge with no fact; and the lowest safe area
    the 1080 canvas can be laid out with (the other platforms' zones)."""
    lines = []
    for n in (1, 15, 30, 45, cline.FACT_MAX_CHARS):
        text = ("word " * 40)[: n].strip() or "w"
        lines.append({"text": text, "start_s": 1.0, "end_s": 4.0,
                      "ref": 1, "publisher": "Wikipedia", "panel_w": 314})
        lines.append({"text": text, "start_s": 1.0, "end_s": 4.0})
    lines.append({"text": "", "start_s": 1.0, "end_s": 4.0,
                  "ref": 3, "publisher": "The Verge", "panel_w": cline.PANEL_MAX_W})
    cases = [case(l) for l in lines]
    cases += [case(l, zones={"top": 0.16, "bottom": 0.30, "left": 0.12, "right": 0.22})
              for l in lines]
    _assert_clear(run(cases), lines + lines)


def test_the_reserve_follows_the_line_in_time():
    """A block the line is never on screen with keeps the old box (the title
    is centred where it always was); a block it meets - even only in the
    crossfade - gets the box below the line."""
    gh = TECH_0811[0]  # 4.54-8.08
    before = {"start": 0.0, "end": 4.0}      # ends 0.54s before the line, past the crossfade
    fade_in = {"start": 8.30, "end": 10.65}  # starts 0.22s after it: the crossfade meets it
    after = {"start": 9.0, "end": 12.0}
    res = run([case(gh, before, [597]), case(gh, fade_in, [597]), case(gh, after, [597])])
    assert res[0]["reserve"] is None and not res[0]["over"], res[0]
    assert res[1]["reserve"] is not None and res[1]["over"], res[1]
    assert res[2]["reserve"] is None, res[2]
    plain, = run([case(gh, before, [597], no_reserve=True)])
    assert res[0]["box"] == plain["box"]
    assert res[1]["box"]["y"] >= max(p["y"] + p["h"] for p in res[1]["plaque"])


def test_the_render_reads_it():
    """Video.jsx passes the reserve to every own-graphic block and
    GraphicLayer lays its box out with it and fits the panel into it - the
    pure functions above are the frame's, not a mirror of it."""
    video = (RENDER_SRC / "Video.jsx").read_text()
    layer = (RENDER_SRC / "components" / "GraphicLayer.jsx").read_text()
    asset = (RENDER_SRC / "components" / "AssetLayer.jsx").read_text()
    kit = (RENDER_SRC / "graphics" / "kit.js").read_text()
    assert "reserveTopFor(block, plan.comparison_lines, safeArea, width, CROSSFADE)" in video
    assert "reserveTop={reserveTop}" in asset
    assert "contentBox(zone, safeArea, width, height, reserveTop)" in layer
    assert "fitScale(el.offsetHeight, box.height)" in layer
    assert "export {LABEL_CLEAR, contentBox} from '../lib/graphicClear'" in kit


TESTS = [v for k, v in dict(globals()).items() if k.startswith("test_")]

if __name__ == "__main__":
    if not NODE:
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
