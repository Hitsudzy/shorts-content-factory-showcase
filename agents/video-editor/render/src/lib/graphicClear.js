/**
 * CF-0923: an own graphic (GraphicLayer.jsx) and the comparison line
 * (ComparisonLine.jsx: the source badge «[1] Wikipedia» and the fact strip
 * under it) never share a pixel.
 *
 * Found on Tech 08.11 (pipeline/example-tech/2026-11-08T0832Z: airbnb,
 * anthropic, claude-code, github - every block our own graphic). The line is
 * pinned at the top-left of the safe area (y 260 .. ~630 on the 1080 canvas,
 * x 126 .. 620); the graphic's panel was centred in a box that starts at
 * safeArea.top + LABEL_CLEAR (y 300), so a card of two or three rows put its
 * title right under the strip for the 3-5 s the line holds. The frame judge
 * does not read overlaps between our own layers, so all four shipped with it.
 *
 * The rule is a layout, not a nudge: while a comparison line is on screen
 * over a graphic block (any overlap of the line's window with the block's
 * mounted span, crossfades included), the graphic's content box starts
 * CLEAR_GAP below the line's lowest box. The panel is fitted into that box
 * (GraphicLayer scales it down when it is taller), so no row count can push
 * the title back up under the strip.
 *
 * Pure (imports only the other pure geometry modules), so the geometry test
 * runs it under plain node: tests/test_graphic_clear_geometry.py.
 */
import {comparisonGeometry} from './comparisonGeometry.js';
import {bandTop, INSERT_GAP} from './captionBand.js';

/** Output px between the comparison line's lowest box and the graphic box. */
export const CLEAR_GAP = 28;

/** Room left under the top of the safe area for the channel's brand label
 *  (Watermark.jsx: 30 px type at safeArea.top) before the graphic starts. */
export const LABEL_CLEAR = 70;

/** The lowest edge, in output px, of everything a comparison line draws (the
 *  badge's anchor and panel, the fact strip), or null when it draws nothing. */
export const comparisonLineBottom = (line, safeArea, width) => {
  const g = comparisonGeometry({line, safeArea, width});
  const boxes = [g.anchor, g.panel, g.fact].filter(Boolean);
  if (!boxes.length) return null;
  return Math.ceil(Math.max(...boxes.map((b) => b.y + b.h)) * g.k);
};

/** Whether a line's window [start_s, end_s) meets the block's mounted span
 *  [start - pad, end + pad) - `pad` is the render's crossfade. */
export const lineOverBlock = (line, block, pad = 0) => {
  const ls = Number(line?.start_s);
  const le = Number(line?.end_s);
  const bs = Number(block?.start) - pad;
  const be = Number(block?.end) + pad;
  if (![ls, le, bs, be].every(Number.isFinite)) return false;
  return ls < be && le > bs;
};

/** The y (output px) the block's graphic must start below, or null when no
 *  comparison line is on screen with it. */
export const reserveTopFor = (block, lines, safeArea, width, pad = 0) => {
  let bottom = null;
  for (const line of lines ?? []) {
    if (!lineOverBlock(line, block, pad)) continue;
    const b = comparisonLineBottom(line, safeArea, width);
    if (b != null && (bottom == null || b > bottom)) bottom = b;
  }
  return bottom == null ? null : bottom + CLEAR_GAP;
};

/**
 * The box the graphic's content is laid out in: the safe area (the player's
 * side and top cuts, like CardLayer) under the brand label and, at the foot,
 * a gap above the caption band - the band owns the bottom of the frame. With
 * `reserveTop` (CF-0923) it starts no higher than that line. The content is
 * centred in it, both ways, and fitted into it (GraphicLayer).
 */
export const contentBox = (zone, safeArea, width, height, reserveTop = null) => {
  if (!safeArea) {
    return {x: zone.x + width * 0.08, y: zone.y + height * 0.1,
            width: zone.width - width * 0.16, height: zone.height * 0.62};
  }
  const left = Math.max(zone.x, safeArea.left);
  const right = Math.min(zone.x + zone.width, width - safeArea.right);
  let top = Math.max(zone.y, safeArea.top + LABEL_CLEAR);
  if (Number.isFinite(reserveTop)) top = Math.max(top, reserveTop);
  const foot = Math.min(zone.y + zone.height,
                        bandTop(safeArea, height) - Math.round(height * INSERT_GAP));
  return {x: left, y: top, width: Math.max(1, right - left), height: Math.max(1, foot - top)};
};

/** The scale that fits a panel of `naturalH` into a box `boxH` tall (never
 *  above 1: a panel that fits is drawn at its own size). */
export const fitScale = (naturalH, boxH) =>
  (naturalH > 0 && boxH > 0 && naturalH > boxH ? boxH / naturalH : 1);

/**
 * Where the panel actually lands: centred in the box both ways, scaled about
 * its own centre by fitScale - the rectangle GraphicLayer draws. Its top is
 * the top of the title row (SpecCard and the other templates open with it).
 */
export const panelRect = (box, naturalH) => {
  const s = fitScale(naturalH, box.height);
  const w = box.width * s;
  const h = naturalH * s;
  return {x: box.x + (box.width - w) / 2, y: box.y + (box.height - h) / 2, width: w, height: h,
          scale: s};
};
