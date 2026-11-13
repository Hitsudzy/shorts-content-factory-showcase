#!/usr/bin/env python3
"""CF-0130: how ProceduralBg is allowed to paint, and what it may not load.

Two properties of `render/src/components/ProceduralBg.jsx` are load-bearing
and neither is visible in a rendered frame, so neither would be caught by
looking at the output:

1. It is the floor of the degradation chain (CF-0031): it must render with
   zero external assets. A file it could fail to load would leave the chain
   without a floor.

2. CF-0130: the wash and the blobs are blurred once into offscreen canvases
   and blitted afterwards, instead of a CSS `filter: blur()` re-rasterised at
   full frame size every frame. That was the whole cost of the component -
   the block cost 0.57s per frame in Chrome's software rasteriser before and
   0.070s after, on the same machine minutes apart (work/cf0052-measure/
   results.jsonl, round `r7-*`). A CSS blur added back to a layer that is
   painted every frame silently buys that cost back, and the only sign would
   be the render clock.

Both are cheap to state as source properties, so they are stated here.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "render" / "src" / "components" / "ProceduralBg.jsx"


def source():
    return SRC.read_text()


def test_the_floor_loads_nothing():
    """No file, font or network fetch reaches this component - CF-0031."""
    text = source()
    for forbidden in ("staticFile", "<Img", "<OffthreadVideo", "<Video",
                      "fetch(", "url(", "@font-face", "new Image("):
        assert forbidden not in text, (
            f"ProceduralBg.jsx mentions {forbidden!r}: the last rung of the "
            "degradation chain must not be able to fail for want of an asset")


def test_no_css_blur_is_painted_per_frame():
    """The expensive shape CF-0130 removed: `filter: blur(...)` in a style.

    The blurs live on `ctx.filter` inside the bake helpers, which run once
    per distinct shape and are cached for the life of the page. A blur in a
    JSX style object is per frame and full size - that is the 8x this task
    bought back."""
    text = source()
    styled_blur = re.findall(r"filter:\s*[`'\"][^`'\"]*blur\(", text)
    assert not styled_blur, (
        "ProceduralBg.jsx has a CSS filter: blur() in a style object "
        f"({styled_blur}) - CF-0130 measured that as the component's entire "
        "cost; blur into an offscreen canvas once instead (see bakeWash / "
        "bakeBlob) or re-measure with work/cf0052-measure/ and say so here")


def test_the_soft_layers_are_composited_below_full_resolution():
    """The other half of the win: the canvas is smaller than the frame.

    Without this the bakes still help, but every frame would composite the
    wash and seven blobs across 1080x1920 again."""
    text = source()
    match = re.search(r"const DOWNSCALE = (\d+);", text)
    assert match, "ProceduralBg.jsx no longer declares DOWNSCALE"
    assert int(match.group(1)) >= 2, (
        "DOWNSCALE below 2 composites the soft layers at frame resolution, "
        "which is what CF-0130 removed")
    assert "/ DOWNSCALE" in text, "DOWNSCALE is declared but not applied"


def test_the_bakes_are_cached_not_rebuilt_per_frame():
    """A bake rebuilt every frame is the old cost with extra steps."""
    text = source()
    assert "const bakes = new Map()" in text, (
        "the module-scope bake cache is gone - each frame would blur its own "
        "wash and blobs again")
    for helper in ("bakeWash", "bakeBlob"):
        assert f"const {helper} = (" in text, f"{helper} is gone"
        # `const bakeWash = (` does not match `bakeWash(`, so every hit here
        # is a call, and every call has to sit inside a `baked(key, () => ..)`.
        for call in re.finditer(rf"{helper}\(", text):
            window = text[max(0, call.start() - 160):call.start()]
            assert "baked(" in window, (
                f"{helper} is called outside the `baked(...)` cache - that "
                "blurs the same shape again on every frame")


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
