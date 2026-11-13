/**
 * CF-0394: where the caption band sits, and where an insert goes around it.
 *
 * The user's pick of 2026-09-25 (four styles side by side on `paper-dragon`,
 * the complaint: the captions jump and take up too much of the screen). The
 * jump had two causes, both gone now:
 *
 *   - CF-0379/CF-0390 raised the band clear of a meme or a proof card for the
 *     insert's span - a jerk of up to ~38% of the frame height and back;
 *   - 78 px type on up to four words wrapped into a varying number of lines,
 *     and the block recentred itself every time the count changed.
 *
 * Variant D, which three videos were published with on 2026-09-25 from a
 * scratch fork before it landed here:
 *
 *   - small type (CAPTION_SCALE of the theme's size, ~50 px), phrases of at
 *     most CAPTION_MAX_WORDS words that fit in CAPTION_MAX_LINES lines;
 *   - the band's foot flush with the top of the player's bottom dead zone
 *     (`safeArea.bottom`, scripts/safe_area.py OVERLAY["bottom"] = 0.28, CF-0329),
 *     with no foot of its own above it - a second line grows upward;
 *   - the band never moves, whatever is on the frame;
 *   - no scrim under it - the stroke alone carries the contrast.
 *
 * So the frame is shared the other way round from CF-0379: an insert (a meme,
 * a proof card) no longer has the whole block's zone to itself, it is fitted
 * into the part of the zone that ends a gap above the band (`insertBox`), and
 * the band stays where it always is. The black ground the insert is drawn on
 * still covers the whole zone - the band sits on that ground, under the
 * picture, instead of across it.
 *
 * Pure, and it imports nothing, so a test can run it under plain node the way
 * CF-0336 runs comparisonGeometry.js; scripts/meme_captions.py mirrors it for
 * the render QC and is checked against it.
 */

/** The caption type as a share of `theme.captionSize` (78 -> 50 px). */
export const CAPTION_SCALE = 0.64;

/** A phrase is at most this many words, this many seconds, this many lines. */
export const CAPTION_MAX_WORDS = 3;
export const CAPTION_MAX_SECONDS = 1.8;
export const CAPTION_MAX_LINES = 2;

/** CSS line-height of the caption row. */
export const CAPTION_LINE_HEIGHT = 1.08;

/** How tall the band is taken to be, as a fraction of the frame height: two
 *  lines of the small type with the spoken word's 1.1em bump and the stroke
 *  (2 x 55 px x 1.08 = 119 px, 134 px reserved at 1920). The same number the
 *  render QC measures the band over (meme_captions.BAND_HEIGHT). */
export const BAND_HEIGHT = 0.07;

/** The gap an insert keeps above the band's top, as a fraction of the frame
 *  height. */
export const INSERT_GAP = 0.015;

/**
 * CF-0699 (the user, 12.10: on ExampleTech the cyan active word did not stand
 * out from the base words): a channel may set its caption colours apart from
 * the graphics' (`theme.caption_text`, `theme.caption_active`, lib/theme.js
 * `captionColours`) and may draw the active word on a rounded pill
 * (`theme.caption_active_box`). The pill's padding, in the caption's em.
 *
 * With a pill the row reserves the side padding on every word, not only on
 * the spoken one (transparent there), and the spoken word keeps the row's
 * size (no 1.1em bump): so every word is as wide whether it is spoken or not
 * and the line never slides sideways when the highlight moves on. The flex
 * gap shrinks by the same padding, so two base words stand as far apart as
 * the padding and the shrunk gap add up to, and the pill's edge keeps the
 * row's old 0.44em clearance from its neighbour's glyphs. Vertically the
 * padding is cancelled by an equal negative margin - the pill reaches a
 * little above and below the line box and the band stays as tall as it was.
 */
export const CAPTION_BOX_PAD_Y_EM = 0.08;
export const CAPTION_BOX_PAD_X_EM = 0.22;
export const CAPTION_BOX_RADIUS_EM = 0.2;

/** The side padding every word of the row carries, in caption em: the
 *  pill's when the channel draws one, else 0 (lib/captions.js `linesFor`
 *  counts it). */
export const captionBoxPadEm = (box) => (box ? CAPTION_BOX_PAD_X_EM : 0);

export const captionFontSize = (theme) => Math.round(theme.captionSize * CAPTION_SCALE);

export const captionStrokeWidth = (theme) =>
  Math.max(1, Math.round(theme.captionStroke * CAPTION_SCALE));

/** The band's distance from the foot of the frame, in output px: the top of
 *  the bottom dead zone, always. */
export const bandBottom = (safeArea) => safeArea.bottom;

/** The band's top edge, in output px from the top of the frame. */
export const bandTop = (safeArea, height) =>
  height - bandBottom(safeArea) - Math.round(height * BAND_HEIGHT);

/**
 * The box an insert's picture is fitted into: the block's zone, cut off a gap
 * above the band's top. A zone that already ends above that line (a second
 * plane under it) is left as it is.
 */
export const insertBox = (zone, safeArea, height) => {
  const limit = bandTop(safeArea, height) - Math.round(height * INSERT_GAP);
  const bottom = Math.min(zone.y + zone.height, limit);
  return {x: zone.x, y: zone.y, width: zone.width, height: Math.max(1, bottom - zone.y)};
};

/** The rectangle a `contain`-fitted picture of `source` actually occupies
 *  inside `box`, or null when the source's size is unknown. */
export const containedPictureBox = (source, box) => {
  const sw = Number(source?.width);
  const sh = Number(source?.height);
  if (!(sw > 0) || !(sh > 0) || !box || !(box.width > 0) || !(box.height > 0)) return null;
  const scale = Math.min(box.width / sw, box.height / sh);
  const w = sw * scale;
  const h = sh * scale;
  return {
    x: box.x + (box.width - w) / 2,
    y: box.y + (box.height - h) / 2,
    width: w,
    height: h,
  };
};
