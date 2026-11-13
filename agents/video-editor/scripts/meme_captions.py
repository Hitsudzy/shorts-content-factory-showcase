"""CF-0379: a meme is up and not one word of ours is on the frame.

CF-0394 (2026-09-25): the band no longer moves for an insert - it is fixed at
the top of the bottom dead zone and the insert is fitted above it. So the band
this gate reads is the same band on every frame, and `insert_box()` says where
the insert's picture is.

The defect this answers is the one the user found on 2026-09-24: for the whole
length of a reaction meme the word-by-word captions were gone, because the
renderer hid them for *any* insert (CF-0071's rule, written for the proof layer
where it is right). CF-0379 turns them back on under a meme and moves the
caption band clear of it. This module is the gate that says whether that
actually reached the pixels: a block carrying an insert that promises our
captions (`insert.captions == "shown"`), with words being spoken over it and no
caption ink anywhere in the band, is a defect and is caught before a human is
shown the video.

Two halves, kept apart on purpose:

* the geometry - where the band is while the insert is up - which is a mirror of
  `render/src/lib/captionBand.js` and of `lib/layout.js` resolveZones /
  resolveSafeArea, the functions the renderer lays itself out with. The mirror
  is tested against the real module under node (tests/test_meme_captions.py),
  because a Python copy proves itself and nothing else;
* the verdict - `ink` / `blank` - from one number, the share of the band's
  pixels that are caption-white. Deliberately crude in the safe direction: a
  bright meme can only push the number *up*, so this gate's mistake is to miss
  a defect, never to kill a good video.

The mode is configuration and not code (CF-0320, the same shape CF-0327 gave
`panel_in_frame`): a new refusal's price in ready videos is measured after the
code exists, by `runlog gate-price --rule video_editor.meme_captions` over the
frozen batches, and until that answer is in a channel can carry the rule as a
warning. The rows are written on every render in every mode - a measurement
only taken when the gate fires could never be priced.
"""
import os

# --------------------------------------------------------------------------
# configuration
# --------------------------------------------------------------------------

#: The rule's name, for `runlog gate-price` and for the batch record.
RULE = "video_editor.meme_captions"

MODE_FAIL, MODE_WARN, MODE_OFF = "fail", "warn", "off"
MODES = (MODE_FAIL, MODE_WARN, MODE_OFF)
DEFAULT_MODE = MODE_FAIL

#: Keys on the plan's `qc_thresholds` and, upstream, in the channel's
#: `video_editor` block. One name, spelled once.
MODE_KEY = "meme_captions_mode"
INK_KEY = "meme_captions_min_ink"

#: The escape hatch for a replay over frozen artefacts, which must not be
#: steered by whatever mode the batch's own plan happened to carry.
MODE_ENV = "CF_MEME_CAPTIONS_MODE"

#: A pixel at least this bright (0-255 luma) is caption fill. The type is
#: #FFFFFF with a black stroke around it, so its core saturates; footage and
#: memes reach it too, which is why this gate only ever reads "something white
#: is there" and never "that white thing is a word".
WHITE_LUMA = 250

#: CF-0572: the caption fill is the channel's `theme.text` now (Captions.jsx),
#: which need not be pure white (ExampleTech/Science set an off-white at luma
#: ~241). The floor follows it: the fill's own luma minus the same 5 the white
#: floor keeps under 255, never above WHITE_LUMA - so ExampleFilm's white is
#: measured at 250 exactly as before, and a plan without a theme (a replay
#: over frozen artefacts) too.
WHITE_MARGIN = 5

#: The share of the band's pixels that has to be caption-white before the band
#: counts as carrying a word. Two lines of caption type across the safe width
#: measure 3-8 % of the band; a frame with no captions at all and a contained
#: meme measures 0. The floor sits an order of magnitude below the signal so
#: that a single short word still clears it.
MIN_INK = 0.0015

#: The caption band's height and the gap an insert keeps above it, as
#: fractions of the frame - captionBand.js BAND_HEIGHT and INSERT_GAP. The
#: band's foot is the top of the bottom dead zone itself (CF-0394).
BAND_HEIGHT = 0.07
INSERT_GAP = 0.015

INK, BLANK = "ink", "blank"


def mode_of(plan, default=DEFAULT_MODE):
    """`fail` / `warn` / `off` for this plan, from configuration only.

    Order: the environment (a replay asking for one mode), then the plan's
    `qc_thresholds`, then the default. An unrecognised value falls back to the
    default rather than to "off" - a typo must not disable a gate.
    """
    raw = os.environ.get(MODE_ENV)
    if raw is None:
        raw = ((plan or {}).get("qc_thresholds") or {}).get(MODE_KEY)
    if raw is None:
        return default
    value = str(raw).strip().lower()
    return value if value in MODES else default


def floor_of(plan, default=MIN_INK):
    """The caption-white share the band has to reach."""
    raw = ((plan or {}).get("qc_thresholds") or {}).get(INK_KEY)
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if 0.0 < value <= 1.0 else default


# --------------------------------------------------------------------------
# geometry - the mirror of the renderer's own
# --------------------------------------------------------------------------

def main_zone(plan):
    """`(x, y, width, height)` of the zone a block's insert is drawn into -
    lib/layout.js resolveZones, line for line: a `secondary` band takes its
    height off the bottom of `main`, and no band leaves `main` the frame."""
    out = plan["output"]
    width, height = out["width"], out["height"]
    secondary = ((plan.get("layout") or {}).get("secondary")) or None
    secondary_h = round(height * (secondary.get("height", 0.28))) if secondary else 0
    return (0, 0, width, height - secondary_h)


def safe_px(plan):
    """The player's safe area in output pixels - resolveSafeArea, over the
    plan's own `safe_zones` and scripts/safe_area.py's numbers for a plan
    that carries none (CF-0329: the margins are the player's, not the
    frame's)."""
    import safe_area as sa

    out = plan["output"]
    width, height = out["width"], out["height"]
    zones = sa.safe_zones()
    declared = plan.get("safe_zones") or {}
    t = declared.get("top", zones["top"])
    b = declared.get("bottom", zones["bottom"])
    l = declared.get("left", zones["left"])
    r = declared.get("right", zones["right"])
    return {"top": round(height * t), "bottom": round(height * b),
            "left": round(width * l), "right": round(width * r),
            "innerWidth": round(width * (1 - l - r))}


def band_top(plan):
    """The caption band's top edge, in output px - captionBand.js bandTop()."""
    height = plan["output"]["height"]
    return height - safe_px(plan)["bottom"] - round(height * BAND_HEIGHT)


def insert_box(plan):
    """`(x, y, width, height)` an insert's picture is fitted into - the main
    zone cut a gap above the band's top, captionBand.js insertBox()."""
    x, y, w, h = main_zone(plan)
    limit = band_top(plan) - round(plan["output"]["height"] * INSERT_GAP)
    return (x, y, w, max(1, min(y + h, limit) - y))


def contained_picture(source_size, zone):
    """The rectangle a `contain`-fitted picture of `source_size` occupies in
    `zone`, or None when the size is unknown - captionBand.js
    containedPictureBox()."""
    if not source_size:
        return None
    try:
        sw, sh = float(source_size["width"]), float(source_size["height"])
    except (KeyError, TypeError, ValueError):
        return None
    x, y, zw, zh = zone
    if sw <= 0 or sh <= 0 or zw <= 0 or zh <= 0:
        return None
    scale = min(zw / sw, zh / sh)
    w, h = sw * scale, sh * scale
    return {"x": x + (zw - w) / 2, "y": y + (zh - h) / 2, "width": w, "height": h}


def band_box(plan, insert=None):
    """`(x, y, w, h)` of the caption band, in output pixels - its place above
    the bottom dead zone and Captions.jsx's own left/width.

    `insert` is accepted and ignored: since CF-0394 the band is in one place
    for the whole video, and the insert is what makes room.
    """
    out = plan["output"]
    width, height = out["width"], out["height"]
    safe = safe_px(plan)
    band_h = round(height * BAND_HEIGHT)
    y = max(0, band_top(plan))
    return (safe["left"], y, min(safe["innerWidth"], width - safe["left"]),
            min(band_h, height - y))


# --------------------------------------------------------------------------
# the measurement
# --------------------------------------------------------------------------

def fill_luma(hex6):
    """0-255 luma of `#RRGGBB` the way PIL's convert("L") computes it
    (ITU-R 601-2: 299/587/114), or None for anything else."""
    if not isinstance(hex6, str) or len(hex6) != 7 or not hex6.startswith("#"):
        return None
    try:
        r, g, b = (int(hex6[i:i + 2], 16) for i in (1, 3, 5))
    except ValueError:
        return None
    return (r * 299 + g * 587 + b * 114) / 1000


def ink_luma(plan):
    """The caption-white floor for `plan`: its `theme.text` luma less
    WHITE_MARGIN, capped at WHITE_LUMA; WHITE_LUMA without a theme."""
    theme = (plan or {}).get("theme") if isinstance(plan, dict) else None
    luma = fill_luma((theme or {}).get("text")) if isinstance(theme, dict) else None
    if luma is None:
        return WHITE_LUMA
    return min(WHITE_LUMA, int(luma) - WHITE_MARGIN)


def ink_fraction(pixels, white=WHITE_LUMA):
    """Share of `pixels` (luma, 0-255) at or above `white`."""
    if not pixels:
        return 0.0
    return sum(1 for p in pixels if p >= white) / len(pixels)


def verdict(ink, floor=MIN_INK):
    """`ink` when the band carries something of ours, `blank` when it is
    empty. Two answers and no third: this gate has exactly one opinion."""
    return INK if ink >= floor else BLANK


def captioned_insert(block):
    """True when this block's insert promises our captions and is one this
    gate was priced on.

    The field decides whether captions are due; the kind decides whether this
    gate judges them. CF-0390 (2026-09-24) turned a proof card's captions on
    as well, and since CF-0394 its band is the meme's band - but the rule's
    price in ready videos was measured on memes alone, and judging a proof
    here would be a new refusal with no price. So this gate stays where it
    was measured."""
    insert = (block or {}).get("insert")
    return (bool(insert) and insert.get("captions") == "shown"
            and insert.get("kind") != "proof")


def insert_span(block):
    """`(start, end)` the insert is up for - its own window when it has one
    (CF-0244), the block otherwise."""
    insert = block["insert"]
    start = insert.get("start_s")
    end = insert.get("end_s")
    return (block["start"] if start is None else start,
            block["end"] if end is None else end)


def spoken_moment(words, start, end):
    """When to look: the middle of the longest word spoken inside
    `start`-`end`, or None when the narration says nothing there.

    A silent stretch is not a defect - there is no caption due - and a moment
    picked off the clock instead of off the words would accuse the gap between
    two phrases of having lost a line that was never there.
    """
    best = None
    for w in words or []:
        s, e = max(start, w.get("start", 0.0)), min(end, w.get("end", 0.0))
        if e - s <= 0:
            continue
        if best is None or (e - s) > (best[1] - best[0]):
            best = (s, e)
    if best is None:
        return None
    return round((best[0] + best[1]) / 2, 2)
