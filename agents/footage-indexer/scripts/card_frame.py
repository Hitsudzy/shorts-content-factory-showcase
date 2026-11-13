"""CF-0093: is the text on this frame a card's text, or a caption on a picture?

`probe_card_text()` in index_footage.py used to count a sampled frame as
card evidence whenever Vision found enough text on it (CARD_TEXT_AREA_THRESHOLD
of the frame). Burned-in subtitles clear that bar as easily as a title does -
a two-line caption at 1080p is ~0.03-0.08 of the frame - so every captioned
photo, talking head and game still in the 2026-09-03T2037Z pool with a CLIP
similarity above CARD_THRESHOLD_LOW came out `is_card` (UaWVjS5SId4 s28,
ScKvReYRZ-A s0, _m4e4oWFmac s1/13/16/26 - and, beyond the task's own list,
most of the captioned Wren Hollow trailer 1RnyZgfN-JY). "Text on screen" is
not the signal; "text that *is* the picture" is.

Two cheap measurements, taken on the same frame and the same Vision boxes
the probe already has, separate the two on every real shot measured
(numbers below are from shared/footage, frames cropped to the picture the
way usability_probe.py crops them):

  headline text - some text line is at least HEADLINE_MIN_HEIGHT of the
    frame tall (and wider than it is tall, so a book spine or an envelope's
    rotated address does not count). Card text measured 0.106 (a tabloid
    front-page card), 0.114-0.15 (Rapid & Reckless logo), 0.119-0.129 ('BASED
    ON A TRUE STORY'), 0.168-0.191 ('164 FEET'), 0.16-0.53 (studio logos,
    name cards, 'EASTER EGGS', 'EAST OF EDEN'). Captions and overlays
    measured 0.035-0.048 (God of War stills), 0.052-0.055 (Le Monde
    subtitles, Example Network trailer captions), 0.063-0.077 (a lower third, letterboxed
    captions), 0.090 (an 'INTEGRITY' wall sign inside a selfie - the highest
    non-card line seen, and the same class of risk CF-0010 accepted for
    "CAPTAIN BOINKY'S ARCADE").

  flat background - one colour covers at least FLAT_DOMINANT_SHARE of the
    picture outside the text boxes. This is what admits a card whose text is
    small: 'A NEW Example Network ORIGINAL SERIES' in gold serif is only 0.057-0.074 tall
    but sits on black (0.86-0.90 dominant), 'THIS FALL' on near-black
    (0.76-0.93), 'THEY BROKE THE NEWS' on newsprint (0.98-0.99). Pictures
    with captions measured 0.15-0.45 (game stills, a selfie, the Le Monde
    talking head at 0.32-0.34, envelope and script close-ups at 0.25-0.34) -
    the Le Monde clip is the reason this is a colour share and not an edge
    density: a close-up face on a plain blue backdrop has as few edges as a
    logo card (0.029-0.031 vs Example+'s 0.028-0.030), but nothing like
    its one dominant colour.

A frame with enough text is `card` if either holds and `caption` if neither
does; a frame without enough text is neither. index_footage.flag_cards()
turns the per-shot rates of the two into the decision. Pure PIL/numpy on
purpose - no Vision, no video-editor imports - so the classification is
testable on synthetic frames without the worker.
"""
import numpy as np
from PIL import Image

# Persistent per-frame overlays (a streaming platform's corner watermark, a
# season/episode caption) measured 0.004-0.009 fractional area in accurate-
# mode Vision text scans on real footage; genuine title/end-card text
# measured 0.02-0.15. The gap between the two is wide enough that this does
# not need to sit close to either side. (CF-0010; moved here from
# index_footage.py with the rest of the per-frame text judgement.)
CARD_TEXT_AREA_THRESHOLD = 0.015

# The shortest card line measured is 0.106 (ZZ_urA56pJE s33's tabloid
# headline); the tallest caption/overlay line 0.090 (UaWVjS5SId4 s28's wall
# sign). 0.10 sits between the two - a narrow gap, ~17px at 1080p, but the
# sign is in-scene text on a photo, which is the residual risk any text
# signal carries (see CF-0010), and that shot is also caught by the frame
# not being flat. Re-tune from measured data if a real card comes in under
# this, not by guessing.
HEADLINE_MIN_HEIGHT = 0.10

# Dominant-colour share of the non-text picture. Flat cards measured
# 0.76-1.0 on solid or near-black grounds, 0.68 on Example+'s blue,
# 0.60-0.75 on a caption-over-dark-scene card frame; pictures with captions
# measured 0.15-0.45. Gradient splash screens (Example Max purple, 0.23-0.25)
# fall below this but carry headline-size text, which is the other route in.
FLAT_DOMINANT_SHARE = 0.60

# Frames are shrunk to this width before the colour histogram - the share is
# a global property and does not need the source's resolution.
ANALYSIS_WIDTH = 320
# 8 levels per channel (bins 32 wide): coarse enough that film grain and
# compression noise on a black or blue card stay in one bin, fine enough
# that a photo's tones do not collapse into one.
COLOUR_LEVELS = 8
# Text boxes are grown by this fraction of the frame on every side before
# masking, so the glyphs' own anti-aliased edges do not count as picture.
TEXT_MASK_PAD = 0.01

# CF-0413: "a person with branding at the edge is not a card" (the user's
# rule of 2026-09-28). The podcast 3oy35kY7guU puts its logo and a name
# plate in the lower corners of every interview shot; the logo line is
# headline-sized (0.15-0.19 of the frame), so every frame read as card text
# and nine close-ups of the guest went into the backrooms rebuild
# letterboxed as cards. Two numbers, measured per card-reading frame
# (is_branding() below):
#
#   PERSON_MIN_FACE_HEIGHT - the tallest face on the frame, as a share of
#     its height. On 4 sampled frames of each interview close-up the faces
#     measured 0.18-0.39 (the guest's own, 0.183-0.295, are the lowest). The
#     title card over a scene in the same source ('Backrooms' over a gasping
#     woman, s4) has its only face at 0.11-0.17 - a figure in the picture,
#     not the frame's subject. 0.15 keeps most of those frames out; the one
#     at 0.169 is held by the second number.
#
#   BRANDING_MAX_KEPT - share of the card-making text inside the 9:16 cover
#     window the renderer points at that person (smart_crop's own window,
#     computed by the caller). The branding measured 0.0 on every one of
#     64 sampled interview frames; the podcast's own intro/outro card (the
#     host's photo with 'with Christina Jeurling Birro' under the logo)
#     0.38-0.39, the 'Backrooms' title 0.58-0.63. At or below 0.2 the text
#     is beside the person, and the reel's crop of the frame is the person.
#
# Checked read-only on 28 `is_card` shots of 28 other pool sources (16 with a
# face on the tile, 6 saliency, 6 animation; 4 samples each): 25 still read
# as cards under the old rule today, and 24 of those keep the flag under
# this one - cast cards (a name under the actor, kept 0.78-0.79), credits
# over a scene, a lower third under a speaker (kept 0.68-0.69), logos, text
# on black. The one that flips is the same class as the podcast:
# faEZRX9eg8Q s49, a commentator on his bed with a picture-in-picture
# poster beside him (face 0.26-0.27, kept 0.0 on all four frames).
PERSON_MIN_FACE_HEIGHT = 0.15
BRANDING_MAX_KEPT = 0.2


def text_area(regions):
    """Total fractional area of Vision's text boxes (as they may overlap,
    this can exceed 1.0 on a text-wall frame; it is only compared to a
    small threshold)."""
    return sum(r["width"] * r["height"] for r in regions)


def has_headline(regions):
    """Some text line is card-sized: at least HEADLINE_MIN_HEIGHT of the
    frame tall and at least as wide as it is tall. The width condition drops
    rotated text - a book spine or a hand-addressed envelope produces a tall,
    narrow box, not a headline."""
    return any(r["height"] >= HEADLINE_MIN_HEIGHT and r["width"] >= r["height"]
               for r in regions)


def _text_mask(shape, regions):
    """True where the frame is picture, False inside (padded) text boxes."""
    h, w = shape
    mask = np.ones((h, w), dtype=bool)
    for r in regions:
        top = max(0.0, r["top"] - TEXT_MASK_PAD)
        bottom = min(1.0, r["bottom"] + TEXT_MASK_PAD)
        left = max(0.0, r["left"] - TEXT_MASK_PAD)
        right = min(1.0, r["left"] + r["width"] + TEXT_MASK_PAD)
        mask[int(top * h):int(bottom * h) + 1, int(left * w):int(right * w) + 1] = False
    return mask


def dominant_colour_share(image, regions=()):
    """Share of the non-text pixels that fall in the single most populated
    colour bin. 1.0 for a solid card; a photo spreads over many bins.

    `image` is a path or a PIL image. A frame whose text boxes cover
    everything has no picture to judge and reads as flat (1.0): a wall of
    text is a card's kind of frame, not a photo's.
    """
    im = image if isinstance(image, Image.Image) else Image.open(image)
    im = im.convert("RGB")
    w, h = im.size
    small = im.resize((ANALYSIS_WIDTH, max(1, round(ANALYSIS_WIDTH * h / w))))
    px = np.asarray(small)
    mask = _text_mask(px.shape[:2], regions)
    picture = px[mask]
    if picture.size == 0:
        return 1.0
    q = (picture.astype(np.int32) * COLOUR_LEVELS) // 256
    bins = (q[:, 0] * COLOUR_LEVELS + q[:, 1]) * COLOUR_LEVELS + q[:, 2]
    counts = np.bincount(bins, minlength=COLOUR_LEVELS ** 3)
    return float(counts.max()) / float(bins.size)


def card_text(regions):
    """The text that makes a frame read as a card: its headline-sized lines
    when it has any (that is the route it came in by), every line otherwise
    (the flat-ground route, where the text as a whole is the card)."""
    headlines = [r for r in regions
                 if r["height"] >= HEADLINE_MIN_HEIGHT and r["width"] >= r["height"]]
    return headlines or list(regions)


def kept_in_window(regions, window):
    """Share of `regions`' area inside `window` ((x, y, w, h), fractions of
    the frame) - smart_crop.text_kept()'s arithmetic on fractional
    coordinates, so this file stays free of video-editor imports. None when
    the regions have no area at all."""
    x, y, w, h = window
    total = kept = 0.0
    for r in regions:
        bx0, bx1 = r["left"], r["left"] + r["width"]
        by0, by1 = r["top"], r.get("bottom", r["top"] + r["height"])
        total += (bx1 - bx0) * (by1 - by0)
        ix = max(0.0, min(bx1, x + w) - max(bx0, x))
        iy = max(0.0, min(by1, y + h) - max(by0, y))
        kept += ix * iy
    return kept / total if total else None


def is_branding(regions, person):
    """CF-0413: is this card-reading frame a person with branding at the
    edge rather than a card?

    `person` is None (no face on the frame) or {"face_height": the tallest
    face as a fraction of the frame height, "window": the 9:16 cover window
    the renderer points at that person, (x, y, w, h) as fractions}.

    Branding when a face of at least PERSON_MIN_FACE_HEIGHT is on the frame
    and at most BRANDING_MAX_KEPT of the card-making text (card_text()) falls
    inside the person's window: the text sits beside the person, and the
    reel's own crop of this frame is the person, not the text. A poster or a
    title whose text crosses the person's column, or a title over a wide
    scene with a small figure, stays a card.
    """
    if not person or person.get("face_height", 0.0) < PERSON_MIN_FACE_HEIGHT:
        return False
    kept = kept_in_window(card_text(regions), person["window"])
    return kept is not None and kept <= BRANDING_MAX_KEPT


def classify_frame(image, regions):
    """One sampled frame's verdict: "card", "caption", or None.

    None: not enough text on the frame for either reading (a corner
    watermark, or no text at all) - the frame says nothing about cards.
    "card": card-sized text, or text on a flat ground.
    "caption": enough text, but caption-sized and on a picture.
    """
    area = text_area(regions)
    if area < CARD_TEXT_AREA_THRESHOLD:
        return {"verdict": None, "text_area": area, "headline": False, "dominant_share": None}
    headline = has_headline(regions)
    share = dominant_colour_share(image, regions)
    flat = share >= FLAT_DOMINANT_SHARE
    return {"verdict": "card" if (headline or flat) else "caption",
            "text_area": area, "headline": headline, "dominant_share": share}
