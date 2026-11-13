/**
 * CF-0336: where the source badge and the fact strip sit, as boxes on the
 * spec's 1080x1920 canvas - a pure function, so the geometry test can run it
 * under plain node without React or Remotion.
 *
 * Until CF-0336 the anchor and the strip were at `x = 0` (spec §3 / §9),
 * written before CF-0329 learned that the Shorts player cuts ~97 px off each
 * side of the master on a 19.5:9 phone. On the widows-bay rebuild the digit
 * sat at x = 36-64 and the strip's first 3-4 letters were under the cut. Now
 * the whole element is laid out inside `safeArea` - the same object Captions,
 * Watermark and EndCard read (lib/layout.js resolveSafeArea). The strip keeps
 * its old right edge (FACT_RIGHT) and wraps at the narrower width that leaves.
 *
 * `safeArea` is in output pixels; the component scales the whole element by
 * `k = width / 1080`, so the margins are divided by `k` here to land on the
 * canvas the constants are written in.
 */
export const CANVAS_W = 1080;
export const BADGE_Y = 260;
export const ANCHOR_W = 104;
export const ANCHOR_H = 120;
export const PANEL_H = 120;
export const PANEL_PADDING = 28;
export const FACT_GAP = 12;
/** CF-0336 rework: the strip's right edge, on the canvas. Before CF-0336 the
 *  strip ran x = 0-620 and §9 promised it never passes x = 620; laying it out
 *  from the safe area's left margin must not push it further into the
 *  picture. At full field width (to x = 851) it covered the lower half of a
 *  small centred face on widows-bay block 18 (face x 446-676, y 250-480) and
 *  qc_render's CF-0294 face gate failed; ending at 620 it passes. The strip is
 *  therefore x = safeArea.left .. 620 and the text wraps at that width. */
export const FACT_RIGHT = 620;
export const FACT_SIZE = 34;
export const FACT_LINE_HEIGHT = 1.32;
/** Both vendored faces advance 0.6 em (see ComparisonLine.jsx). */
export const MONO_ADVANCE = 0.6;

/** Word-wrap `text` into lines of at most `maxChars` monospaced glyphs, the
 *  way the browser does for a normal `white-space`: break at spaces, a word
 *  longer than the line stays whole on its own line. */
export const wrapMono = (text, maxChars) => {
  const words = String(text).trim().split(/\s+/).filter(Boolean);
  const lines = [];
  let cur = '';
  for (const w of words) {
    const next = cur ? `${cur} ${w}` : w;
    if (cur && next.length > maxChars) {
      lines.push(cur);
      cur = w;
    } else {
      cur = next;
    }
  }
  if (cur) lines.push(cur);
  return lines;
};

/**
 * Boxes, on the 1080-wide canvas:
 *   field   - the safe area itself
 *   anchor  - the red square with the digit (null without a badge)
 *   numeral - the digit's advance box, centred in the anchor
 *   panel   - the paper label at its settled width (null without a badge)
 *   label / name - the two text rows inside the panel
 *   fact    - the strip (null without text); factText - its text box, with
 *             the wrapped `factLines`
 */
export const comparisonGeometry = ({line, safeArea, width}) => {
  const k = (width || CANVAS_W) / CANVAS_W;
  const left = (safeArea?.left ?? 0) / k;
  const top = (safeArea?.top ?? 0) / k;
  const innerW = (safeArea?.innerWidth ?? CANVAS_W) / k;
  const field = {x: left, y: top, w: innerW};

  const ref = line?.ref;
  const publisher = line?.publisher;
  const panelW = Math.max(0, Math.round(line?.panel_w ?? 0));
  const hasBadge = Boolean(publisher) && typeof ref === 'number' && ref > 0 && panelW > 0;
  const factText = typeof line?.text === 'string' && line.text.trim() ? line.text.trim() : null;

  const y0 = Math.max(BADGE_Y, Math.ceil(top));
  const x0 = Math.ceil(left);

  const out = {k, field, hasBadge, factText, anchor: null, numeral: null, panel: null,
    label: null, name: null, fact: null, factTextBox: null, factLines: []};

  if (hasBadge) {
    out.anchor = {x: x0, y: y0, w: ANCHOR_W, h: ANCHOR_H};
    const digits = String(ref).length;
    const numW = digits * 48 * MONO_ADVANCE;
    out.numeral = {x: x0 + (ANCHOR_W - numW) / 2, y: y0, w: numW, h: ANCHOR_H};
    out.panel = {x: x0 + ANCHOR_W, y: y0, w: panelW, h: PANEL_H};
    out.label = {x: x0 + ANCHOR_W + PANEL_PADDING, y: y0,
      w: Math.max(0, panelW - 2 * PANEL_PADDING), h: PANEL_H};
    out.name = {x: x0 + ANCHOR_W + PANEL_PADDING, y: y0,
      w: String(publisher).length * 40 * MONO_ADVANCE, h: PANEL_H};
  }
  if (factText) {
    // The strip runs from the field's left margin to FACT_RIGHT (or the
    // field's right edge, whichever is nearer); the text wraps inside it.
    const factW = Math.max(0, Math.floor(Math.min(FACT_RIGHT, left + innerW) - x0));
    const textW = Math.max(0, factW - 2 * PANEL_PADDING);
    const maxChars = Math.max(1, Math.floor(textW / (FACT_SIZE * MONO_ADVANCE)));
    const lines = wrapMono(factText, maxChars);
    const longest = lines.reduce((m, l) => Math.max(m, l.length), 0);
    const lineH = FACT_SIZE * FACT_LINE_HEIGHT;
    const y = hasBadge ? y0 + PANEL_H + FACT_GAP : y0;
    const h = 2 * PANEL_PADDING + lines.length * lineH;
    out.fact = {x: x0, y, w: factW, h};
    out.factTextBox = {x: x0 + PANEL_PADDING, y: y + PANEL_PADDING,
      w: longest * FACT_SIZE * MONO_ADVANCE, h: lines.length * lineH, textW};
    out.factLines = lines;
  }
  return out;
};
