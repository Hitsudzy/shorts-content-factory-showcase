#!/usr/bin/env python3
"""CF-0071: `rendered_quote` - typeset a proof's quotation as our own card.

inserts/proof.json capture_methods[rendered_quote].behaviour, executed:
the channel's own typography and colours (CF-0572: the channel's theme,
`channels/<id>.json` -> `theme` - bg, text, accent, muted and the card face
`font.card`) on our own background - an extension of the CF-0041 `card`. No chrome, no logo, no avatar, no verification mark, no
reply/like furniture, no screenshot-like frame: a rendered quote must look
like ours (honesty_rules), never like the outlet's page or an X post card.

What the card shows, and nothing else (behaviour.must_show minus the URL,
which goes on the block's sourcing line - behaviour.url_placement):

    verbatim_text       the words the document carries, unedited
    author_or_outlet    the publication's shown name or the @handle
    posted_at           the document's date

The renderer's return value is its own bookkeeping of every string drawn -
`lines[]` with role, text and pixel box - so that a test can assert the
card carries exactly those fields without OCR, and so that the legibility
gate's reading of the same file has something to be compared against.

Deterministic: same inputs, same theme, same font, same bytes. The face is
the theme's `font.card` stack resolved family by family to a system file
(FAMILY_FILES - Helvetica is `Helvetica.ttc` #1, the face CardLayer.jsx
draws), its generic tail to FONT_CANDIDATES, a Pillow DejaVu fallback last;
the face used is reported in the result. There is no default theme: the
card is the channel's or it is not drawn (CF-0572).

Fails as the contract says (QuoteError.reason):
    source_incomplete   a mandatory attribution field is empty
    too_long            len(verbatim_text) > PROOF_MAX_VERBATIM_CHARS
    illegible           the text wraps to more than PROOF_MAX_LINES lines

Usage:
    render_quote.py <out.png> --channel example-film --text "..." --author "Variety" \
        --posted-at 2026-09-01
"""
import argparse
import json
import re
import sys
from pathlib import Path

from common import (PROOF_CARD_HEIGHT, PROOF_CARD_WIDTH, PROOF_MAX_LINES,
                    PROOF_MAX_VERBATIM_CHARS)
from _runlog import runlog, video_script, video_attempt  # noqa: E402 - CF-0107 run accounting

# CF-0572: the card's colours are the channel's theme (`theme=`, required):
# these four keys of it are drawn. There is no default palette here - the
# literal defaults and the regex over Video.jsx this file used to keep were
# ExampleFilm's colours standing in for every channel.
THEME_KEYS = ("bg", "text", "accent", "muted")

# A family of a CSS stack (`theme.font.card`) -> the system files that carry
# its bold face, (path, index). Helvetica.ttc index 1 is Helvetica Bold on
# macOS - the face CardLayer.jsx's `font.card` draws for ExampleFilm.
FAMILY_FILES = {
    "Helvetica": [("/System/Library/Fonts/Helvetica.ttc", 1)],
    "Helvetica Neue": [("/System/Library/Fonts/HelveticaNeue.ttc", 1)],
    "Arial": [("/Library/Fonts/Arial Bold.ttf", 0),
              ("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 0)],
    "DejaVu Sans": [("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0)],
}

# A generic family at the end of a stack (sans-serif), or no stack at all
# (frame_judge_pack's contact sheet): the platform's bold sans, in order.
FONT_CANDIDATES = [
    # (path, index) - Helvetica.ttc index 1 is Helvetica Bold on macOS.
    ("/System/Library/Fonts/Helvetica.ttc", 1),
    ("/System/Library/Fonts/HelveticaNeue.ttc", 1),
    ("/Library/Fonts/Arial Bold.ttf", 0),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 0),
]

MARGIN = 96
BAR_WIDTH = 16
BAR_GAP = 40
# Sizes chosen against the legibility gate as it measures: Vision boxes the
# glyphs, not the em square (a line of digits at 44px reads as ~36px), and
# the floor is 39px on the delivered 1080x1920 frame - the card is delivered
# at its own scale (1080 wide), so the smallest face here has to box above
# 39px natively. 58px digits box at ~47px.
QUOTE_SIZE = 80
AUTHOR_SIZE = 60
DATE_SIZE = 58
LINE_SPACING = 1.22
ATTRIBUTION_GAP = 64

ISO_DATETIME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T")


class QuoteError(Exception):
    """A card that could not be typeset honestly; `reason` is the outcome."""

    def __init__(self, reason, detail=""):
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason
        self.detail = detail


def stack_families(stack):
    """The families of a CSS font-family stack, unquoted, in order."""
    return [f.strip().strip('"').strip("'") for f in str(stack or "").split(",")
            if f.strip()]


def font_files(stack=None):
    """(path, index) to try for `stack`: each named family's files in the
    stack's order, then FONT_CANDIDATES (the generic tail, or no stack)."""
    files = []
    for family in stack_families(stack):
        files.extend(FAMILY_FILES.get(family, []))
    files.extend(c for c in FONT_CANDIDATES if c not in files)
    return files


def card_theme(theme):
    """The four colours and the card face the card draws, from the
    channel's theme; a QuoteError(no_theme) when there is none."""
    if not isinstance(theme, dict):
        raise QuoteError("no_theme", "the card's colours are the channel's theme "
                                     "(channels/<id>.json -> theme); none was given (CF-0572)")
    missing = [k for k in THEME_KEYS if not theme.get(k)]
    if missing:
        raise QuoteError("no_theme", f"the theme has no {', '.join(missing)} (CF-0572)")
    return {**{k: theme[k] for k in THEME_KEYS},
            "font": (theme.get("font") or {}).get("card")}


def load_font(size, stack=None):
    """(ImageFont, name) - the first face of `stack` (a CSS font-family
    stack, `theme.font.card`) that opens, else Pillow's bundled DejaVu, else
    the built-in bitmap face at `size`."""
    from PIL import ImageFont
    for path, index in font_files(stack):
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size, index=index), f"{Path(path).name}#{index}"
            except OSError:
                continue
    try:
        return ImageFont.truetype("DejaVuSans-Bold.ttf", size), "DejaVuSans-Bold.ttf"
    except OSError:
        return ImageFont.load_default(size), "pillow-default"


def shown_date(posted_at):
    """The date as drawn: an ISO datetime shows its date part, anything else
    is shown as given. Cutting the clock off a timestamp is not editing the
    document's words - posted_at is an attribution field, not the quote."""
    s = str(posted_at or "").strip()
    m = ISO_DATETIME_RE.match(s)
    return m.group(1) if m else s


def wrap(text, font, max_width, draw):
    """Greedy word wrap on the font's own measurement. A single word wider
    than the column is kept whole (never hyphenated: the words are the
    document's) and overflows, which the legibility gate will then see."""
    words = text.split()
    lines, cur = [], ""
    for w in words:
        cand = f"{cur} {w}".strip()
        if cur and draw.textlength(cand, font=font) > max_width:
            lines.append(cur)
            cur = w
        else:
            cur = cand
    if cur:
        lines.append(cur)
    return lines


def render_quote_card(verbatim_text, author_or_outlet, posted_at, dest,
                      width=PROOF_CARD_WIDTH, height=PROOF_CARD_HEIGHT, *, theme):
    """Draw the card to `dest` (PNG) in the channel's `theme` (its
    `channels/<id>.json` theme block: bg, text, accent, muted, font.card).
    Returns the bookkeeping dict:
    {file, width, height, font, theme, lines: [{role, text, size, box}]}.
    Raises QuoteError(no_theme | source_incomplete | too_long | illegible)."""
    theme = card_theme(theme)
    text = (verbatim_text or "").strip()
    author = (author_or_outlet or "").strip()
    date = shown_date(posted_at)
    if not text or not author or not date:
        missing = [n for n, v in (("verbatim_text", text), ("author_or_outlet", author),
                                  ("posted_at", date)) if not v]
        raise QuoteError("source_incomplete", ", ".join(missing))
    if len(text) > PROOF_MAX_VERBATIM_CHARS:
        raise QuoteError("too_long", f"{len(text)} > {PROOF_MAX_VERBATIM_CHARS}")

    from PIL import Image, ImageDraw
    img = Image.new("RGB", (width, height), theme["bg"])
    draw = ImageDraw.Draw(img)
    quote_font, font_name = load_font(QUOTE_SIZE, theme["font"])
    author_font, _ = load_font(AUTHOR_SIZE, theme["font"])
    date_font, _ = load_font(DATE_SIZE, theme["font"])

    text_x = MARGIN + BAR_WIDTH + BAR_GAP
    column = width - text_x - MARGIN
    quote_lines = wrap(text, quote_font, column, draw)
    if len(quote_lines) > PROOF_MAX_LINES:
        raise QuoteError("illegible", f"{len(quote_lines)} lines > {PROOF_MAX_LINES}")

    quote_step = int(QUOTE_SIZE * LINE_SPACING)
    block_h = (len(quote_lines) * quote_step + ATTRIBUTION_GAP
               + int(AUTHOR_SIZE * LINE_SPACING) + int(DATE_SIZE * LINE_SPACING))
    y = max(MARGIN, (height - block_h) // 2)
    top = y

    lines = []

    def put(role, s, font, size, colour):
        nonlocal y
        draw.text((text_x, y), s, font=font, fill=colour)
        bbox = draw.textbbox((text_x, y), s, font=font)
        lines.append({"role": role, "text": s, "size": size, "box": [int(v) for v in bbox]})
        y += int(size * LINE_SPACING)

    for line in quote_lines:
        put("verbatim", line, quote_font, QUOTE_SIZE, theme["text"])
    y += ATTRIBUTION_GAP
    put("author_or_outlet", author, author_font, AUTHOR_SIZE, theme["accent"])
    put("posted_at", date, date_font, DATE_SIZE, theme["muted"])

    # The one piece of furniture: our accent bar beside the quotation. Ours,
    # not a platform's - no frame, no avatar circle, no verification mark.
    draw.rectangle([MARGIN, top, MARGIN + BAR_WIDTH, y - int(DATE_SIZE * (LINE_SPACING - 1))],
                   fill=theme["accent"])

    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest, format="PNG", optimize=False)
    return {"file": str(dest.resolve()), "width": width, "height": height,
            "font": font_name, "theme": theme, "lines": lines,
            "verbatim_text": text, "author_or_outlet": author, "posted_at": date}


def main(argv=None):
    ap = argparse.ArgumentParser(description="typeset a proof quotation as our own card")
    ap.add_argument("out")
    ap.add_argument("--channel", required=True,
                    help="the channel whose theme the card is drawn in (CF-0572)")
    ap.add_argument("--root", default=None, help="factory root (default: this checkout's)")
    ap.add_argument("--text", required=True)
    ap.add_argument("--author", required=True, help="publication name or @handle")
    ap.add_argument("--posted-at", required=True)
    a = ap.parse_args(argv)
    runlog.annotate(**video_attempt(a.out))  # CF-0107
    from _channel_data import channel_data
    try:
        theme = channel_data.theme(a.channel, a.root)
    except channel_data.ChannelDataError as e:
        print(json.dumps({"ok": False, "reason": "no_theme", "detail": str(e)}))
        return 1
    try:
        info = render_quote_card(a.text, a.author, a.posted_at, a.out, theme=theme)
    except QuoteError as e:
        print(json.dumps({"ok": False, "reason": e.reason, "detail": e.detail}))
        return 1
    print(json.dumps({"ok": True, **{k: v for k, v in info.items() if k != "theme"}},
                     ensure_ascii=False, indent=2))
    return 0


@video_script("video-editor", "quote", name="render_quote.py")
def cli():
    """CF-0107/CF-0177: start/done|failed around main(), both halves of the
    pair carrying the slug and the ledger's attempt - `video_script` reads
    them off the command line before the start line is written. main() stays
    bare for in-process callers and tests."""
    sys.exit(main())


if __name__ == "__main__":
    cli()
