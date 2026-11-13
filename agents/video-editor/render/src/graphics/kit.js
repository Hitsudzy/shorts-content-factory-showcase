/**
 * CF-0689: what every own-graphic template shares - the clock, the easing,
 * the box the graphic is laid out in, and the type sizes.
 *
 * A template draws ONLY the strings of `asset.data` (and the source line in
 * `asset.caption`): no default label, unit, date or word of its own - every
 * string on the frame is a value of the script backed by its claims
 * (shared/own_graphic.py). Colours come only from `theme` (plan.theme).
 *
 * Pure, imports nothing but `interpolate`, so the markup test can render it.
 */
import {interpolate, Easing} from 'remotion';

/** Seconds of the graphic's own animation at this frame: the block's local
 *  time plus `offset_seconds` (a run the rhythm cut in two continues). */
export const graphicTime = (frame, fps, asset) =>
  frame / fps + (Number(asset?.offset_seconds) || 0);

const ease = Easing.out(Easing.cubic);

/** 0 -> 1 over `dur` seconds from `delay`, eased, clamped. */
export const appear = (t, delay, dur = 0.45) =>
  interpolate(t, [delay, delay + dur], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: ease,
  });

/** Where the n-th item of a list comes in (seconds). */
export const STAGGER = 0.2;
export const FIRST = 0.15;
export const itemDelay = (n, head = FIRST) => head + n * STAGGER;

/** The brand label's room and the content box live in lib/graphicClear.js
 *  since CF-0923 (pure, so the geometry test can run them under node; the
 *  box now also clears a comparison line on screen with the graphic). */
export {LABEL_CLEAR, contentBox} from '../lib/graphicClear';

/** The content panel's padding and border (GraphicLayer): the inner width a
 *  template lays its text out in is the box width less these. */
export const PANEL_PAD = 30;
export const PANEL_BORDER = 3;
export const innerWidth = (box) => Math.max(1, box.width - 2 * (PANEL_PAD + PANEL_BORDER));
/** CF-0690: the inner height (api_chat sizes its type to it). */
export const innerHeight = (box) => Math.max(1, box.height - 2 * (PANEL_PAD + PANEL_BORDER));

/** Type sizes at 1080 px wide - large enough to read on a phone. */
export const SIZE = {title: 100, big: 170, value: 70, label: 48, caption: 36};

/** Average glyph advance as a share of the font size, per face role - for
 *  `fitSize`'s estimate (Arial Black is wide, Helvetica narrower); on the
 *  generous side, so a string sized to one line stays on one line. */
export const EM = {display: 0.74, card: 0.62, text: 0.56};

/**
 * The font size a string is drawn at: the rule for every template is shrink
 * to one line first, wrap only at the floor. As large as `max`, small enough
 * that the string fits one line of `width` (an estimate off the face's
 * average advance), never under `min` - only a string too long for one line
 * at `min` wraps. A short value is drawn big.
 */
export const fitSize = (text, {max, min, width, em = EM.card}) => {
  const n = Math.max(1, String(text ?? '').length);
  const fit = (width * 0.9) / (n * em);
  return Math.round(Math.max(min, Math.min(max, fit)));
};

/** The longest string of a list (the size a column of them shares). */
export const longest = (xs) => xs.reduce((a, b) => (String(b ?? '').length > String(a ?? '').length ? b : a), '');

/** A text block that wraps inside its box rather than running off it. */
export const wrap = {overflowWrap: 'anywhere', wordBreak: 'normal', whiteSpace: 'normal'};

/** Rows of a list field, objects only (the order is checked upstream). */
export const rowsOf = (data, key) =>
  (Array.isArray(data?.[key]) ? data[key] : []).filter((r) => r && typeof r === 'object');

/** A string field, or null - never a placeholder. */
export const str = (v) => (typeof v === 'string' && v.trim() ? v : null);
