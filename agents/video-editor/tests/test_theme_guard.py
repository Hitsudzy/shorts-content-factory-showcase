#!/usr/bin/env python3
"""CF-0572: the guard - no channel's palette is written into the code.

The on-screen theme is channel data (`channels/<id>.json` -> `theme`, carried
in `plan.theme`); before CF-0572 ExampleFilm's palette was literals across
render/src/ and scripts/render_quote.py, and so every channel's. Locked:

  * no colour of ExampleFilm's theme (REEL_FROZEN of the root: bg, accents,
    text grounds, the badge's six, the procedural palettes) appears in any
    .js/.jsx/.mjs/.py of render/src/ or scripts/ - comments included, a
    colour named in a comment is the next literal. White and black are the
    common exception (the captions' black stroke, shadows, a meme caption's
    white) - but in render/src/ no *quoted* white is left either: the text
    colour is `theme.text`;
  * Video.jsx's THEME keeps sizes only; render_quote.py has no palette of
    its own and does not read Video.jsx;
  * the guard sees a planted literal (it is not passing by looking nowhere).

Reads this repo's own source files only - no live data, no network.
"""
import _isolated_runlog  # noqa: F401,E402 - CF-0482: run accounting never lands in a real batch
import re
import sys
import tempfile
from pathlib import Path

from test_channel_theme import REEL_FROZEN  # noqa: E402

AGENT_ROOT = Path(__file__).resolve().parent.parent
SCANNED = (AGENT_ROOT / "render" / "src", AGENT_ROOT / "scripts")
SUFFIXES = {".js", ".jsx", ".mjs", ".py"}
#: shared by every channel: the stroke and the shadows are black, a meme
#: caption is white (meme_captions.py) - not a channel's palette.
COMMON = {"#000000", "#FFFFFF"}
HEX = re.compile(r"#[0-9A-Fa-f]{6}\b")
QUOTED_WHITE = re.compile(r"""['"`]\s*(#FFFFFF|#ffffff|rgba\(\s*255\s*,\s*255\s*,\s*255)""")


def reel_colours():
    found = set()

    def walk(v):
        if isinstance(v, str) and HEX.fullmatch(v):
            found.add(v.upper())
        elif isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
    walk(REEL_FROZEN)
    return found


FORBIDDEN = reel_colours() - COMMON


def sources(bases=SCANNED):
    for base in bases:
        for p in sorted(Path(base).rglob("*")):
            if p.suffix in SUFFIXES and "__pycache__" not in p.parts and p.is_file():
                yield p


def hits(bases=SCANNED, render_src=SCANNED[0]):
    out = []
    for p in sources(bases):
        for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            for c in HEX.findall(line):
                if c.upper() in FORBIDDEN:
                    out.append(f"{p}:{n}: {c}")
            if Path(render_src) in p.parents and QUOTED_WHITE.search(line):
                out.append(f"{p}:{n}: quoted white (the text colour is theme.text)")
    return out


def test_the_reel_palette_has_colours_to_look_for():
    assert len(FORBIDDEN) >= 30, sorted(FORBIDDEN)
    for c in ("#0B0B12", "#FFE23D", "#7C5CFF", "#B9B9C6", "#EDE5D0", "#2E2418",
              "#8A7A5C", "#C9BFA4", "#C4442E", "#F4EEDD", "#262646", "#241A4D", "#FF4D97"):
        assert c in FORBIDDEN, c


def test_the_guard_sees_a_planted_literal():
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "src"
        src.mkdir()
        (src / "A.jsx").write_text("const x = {color: '#ffe23d'};\nconst y = '#FFFFFF';\n"
                                   "// the stroke is #000000\n")
        (src / "b.py").write_text("BG = (11, 11, 18)  # not a hex\nOK = '#123456'\n")
        found = hits((src,), render_src=src)
        assert len(found) == 2 and "#ffe23d" in found[0] and "quoted white" in found[1], found


def test_no_channel_palette_in_the_code():
    found = hits()
    assert not found, "colour literals of a channel's theme in the code (CF-0572):\n" + \
        "\n".join(str(h) for h in found)


def test_video_theme_is_sizes_only_and_render_quote_has_no_palette():
    video = (AGENT_ROOT / "render" / "src" / "Video.jsx").read_text()
    body = re.search(r"const THEME = \{(.*?)\};", video, re.S)
    assert body, "Video.jsx THEME"
    keys = set(re.findall(r"(\w+)\s*:", body.group(1)))
    assert keys == {"captionSize", "captionStroke", "watermarkSize"}, keys
    assert "requireTheme(plan)" in video
    quote = (AGENT_ROOT / "scripts" / "render_quote.py").read_text()
    for gone in ("DEFAULT_THEME", "theme_from_render", "Video.jsx THEME"):
        assert gone not in quote, gone


if __name__ == "__main__":
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_") and callable(v)]
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
