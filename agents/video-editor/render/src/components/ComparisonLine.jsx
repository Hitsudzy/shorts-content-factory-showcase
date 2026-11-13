import React from 'react';
import {Easing, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';
import {BADGE_ARROW_STACK, useBadgeFonts} from '../lib/fonts';
import {
  ANCHOR_H, ANCHOR_W, BADGE_Y, CANVAS_W, FACT_LINE_HEIGHT, FACT_SIZE, MONO_ADVANCE,
  PANEL_H, PANEL_PADDING, comparisonGeometry,
} from '../lib/comparisonGeometry';

/**
 * CF-0164 / CF-0186: the source badge and the fact strip -
 * docs/source-badge-spec.md, §§1-7 and §9.
 *
 * What the badge is (§1-2). Two rectangles that come and go together: a red
 * anchor flush with the left edge carrying one digit, and a cream paper
 * label that runs out from under it. The digit is the key that joins this
 * frame to the numbered source block in the description (CF-0017); the label
 * says `SOURCE ↓ DESC` above the publication's own name. Nothing else goes
 * inside the panel.
 *
 * What CF-0186 added beside it (§9). The element used to be the source and
 * only the source, because the thing being sourced - a comparison between
 * what was announced and what the footage shows - was already spoken and
 * subtitled. That position is cancelled (CF-0181), and what the element now
 * annotates is the video's one production fact (CF-0183). The fact is the
 * thing the viewer is meant to come away with, so it is on the frame: a
 * paper strip of its own under the panel, `line.text`, at most 60 characters
 * and never truncated. The panel is untouched - §2's rule that nothing else
 * goes inside it still holds.
 *
 * Either half may be absent. A fact with no publication to name draws the
 * strip alone, in the badge's place; a fact whose wording will not fit the
 * screen's budget draws the badge alone, exactly as before CF-0186. With
 * neither, comparison_line.py writes no line at all.
 *
 * What the badge replaced, and why none of it survives (the user's verdict
 * on CF-0157, 2026-09-09: "форма не принята, визуал меняется целиком"): the
 * translucent kicker card, the accent rule down its left edge, the two rows
 * of `on_screen`, the boxed numeral beside the word SOURCE and the row
 * reading "fact-check in the description". None of that comes back with the
 * strip: one row of ours, on the same paper, under the panel and not inside
 * it.
 *
 * Where the numbers come from. Every dimension in §3 is on a 1080x1920
 * canvas, so they are written here as the constants they are and the whole
 * badge is scaled by `width / 1080` if a composition is ever a different
 * size. Two numbers are *not* decided here: `line.panel_w` (the width of the
 * label, and the refusal when a name will not fit it) and `line.publisher`
 * (the name itself, from the channel's table) both come from the planner -
 * see comparison_line.publisher_of(). This component measures nothing, which
 * is what makes §7's integer-pixel promise keepable: the width is one
 * integer, rounded per frame off one number that never changes.
 *
 * The character of the movement (§6) is the point of the whole redraw. The
 * label overshoots its width and comes back - "ощущение массы, как у
 * механики кассетной деки" - while the exit is short and has no overshoot at
 * all. The text is deliberately *not* welded to the moving edge: it fades in
 * 120 ms late, because letters riding the edge read as rubber.
 *
 * Not implemented, by the user's decision recorded in the spec's header: the
 * "Наложение срабатываний" section (the odometer digit, the cross-faded
 * name, the width that travels to a new W). comparison_line.resolve_
 * overlaps() keeps two lines off one frame, so the case cannot arise.
 */

// --------------------------------------------------------------------------
// §3 geometry, on the spec's 1080x1920 canvas. The badge's and the strip's
// numbers live in lib/comparisonGeometry since CF-0336, which also places the
// element inside the safe area: the spec's `x = 0` predates CF-0329 and sat
// under the player's cut.
// --------------------------------------------------------------------------
const RULE_H = 2;
/** §3's table gives baselines, not box tops: the label sits on y = 300 and
 *  the name on y = 348, both inside a panel whose top is y = 260. (The
 *  table's 28px padding is the horizontal one - it is exactly the `+56` in
 *  `W = text_width + 56`. Vertically it cannot be meant literally: a 30px
 *  line whose baseline is 40px below the panel's top already has its
 *  cap-height above 28px of padding.) */
const LABEL_BASELINE = 300 - BADGE_Y;   // 40
const NAME_BASELINE = 348 - BADGE_Y;    // 88

// §4, and every one of them opaque: `alpha = 1.0` is a rule, not a default.
// The footage under the badge is different in every video and only a solid
// fill gives contrast without looking at the frame first.
// CF-0572: the six colours (paper, ink, ink_muted, rule, accent, accent_ink)
// and the face are the channel's - `plan.theme.badge` and
// `plan.theme.font.badge`, read in the component below. ExampleFilm's are
// the spec's cream/brown/red and Courier Prime; the root's validator holds
// every channel's pairs to the same contrast floors (docs/channel-data.md).

// §5 typography. The label is the only string in the badge that never
// changes; by the second badge it is read as a sign rather than as words.
const LABEL_TEXT = 'SOURCE ↓ DESC';
/** Split around the arrow, which is the one glyph that has to be drawn in a
 *  box of its own - see BADGE_ARROW_STACK. The string above stays whole so
 *  that it reads here as what it is on screen, and so that it is the same
 *  literal comparison_line.LABEL_TEXT measures. */
const LABEL_ARROW = '↓';
const [LABEL_BEFORE, LABEL_AFTER] = LABEL_TEXT.split(LABEL_ARROW);
const LABEL_SIZE = 30;
const LABEL_TRACKING = 2;
const NAME_SIZE = 40;
const NUMERAL_SIZE = 48;

// --------------------------------------------------------------------------
// CF-0186: the fact strip
// --------------------------------------------------------------------------
/** Our wording of the production fact, on a paper strip under the badge.
 *
 *  Why there is one at all. CF-0186 moved this element off the cancelled
 *  comparison beat and onto the fact CF-0183 puts in the script, and made
 *  the fact - not the source - the thing the viewer is meant to come away
 *  with. §2 of docs/source-badge-spec.md says the panel itself carries
 *  nothing but the label and the masthead, and it still does: the fact is a
 *  strip of its own, below the panel and outside it, and the panel is
 *  untouched.
 *
 *  It is drawn only when the script gives a wording short enough to read in
 *  the beat - comparison_line.FACT_MAX_CHARS, 60 characters, the same budget
 *  the on-screen wording has had since CF-0116. Nothing here measures or
 *  truncates anything: too long and the planner writes no `text` at all.
 *
 *  Geometry (CF-0336): from the safe area's left margin, like the anchor,
 *  to x = 620 as before (FACT_RIGHT) - the text wraps there - and low enough that with the badge above it the
 *  stack still ends far above y = 900, where the Shorts interface starts. */

/** Both vendored faces are monospaced at 0.6 em (Courier Prime 1228/2048,
 *  IBM Plex Mono 600/1000). The arrow is given that advance explicitly
 *  because Courier Prime has no U+2193 at all and the glyph therefore comes
 *  from the reserve family - forcing the box makes the label's width the
 *  same number comparison_line.text_width() computed, whatever supplies the
 *  glyph. */
/** Where a baseline sits inside a line box of `line-height: 1em`, for
 *  Courier Prime: (1 - (ascent + descent)) / 2 + ascent, with the font's own
 *  hhea/typo metrics (1600 and -700 per 2048 em, and it sets USE_TYPO_
 *  METRICS, so both agree). This is how a baseline from §3 is turned into a
 *  `top`. */
const BASELINE_IN_EM = (1 - (1600 + 700) / 2048) / 2 + 1600 / 2048;
/** Cap height, Courier Prime Bold (OS/2 sCapHeight 1187/2048). The numeral
 *  is centred on the anchor optically - the cap box centred, not the line
 *  box, which would sit the digit visibly high. */
const CAP_IN_EM = 1187 / 2048;

// --------------------------------------------------------------------------
// §6 movement
// --------------------------------------------------------------------------
/** Fallbacks for a plan built before CF-0164; the planner owns both
 *  (comparison_line.MOVE_IN_SECONDS / MOVE_OUT_SECONDS = 0.38 / 0.24). */
const MOVE_IN_SECONDS = 0.38;
const MOVE_OUT_SECONDS = 0.24;

/** The spec's arrival curve. Its y overshoots to 1.0529 at x = 0.626, and
 *  that overshoot *is* the brief: the label runs past its width and settles
 *  back (31px past on a 584px panel - visible at a glance, which the
 *  acceptance list asks for). */
const EASE_ARRIVE = Easing.bezier(0.34, 1.4, 0.64, 1);
/** The exit, §6: no overshoot, and drier than the arrival. */
const EASE_LEAVE = Easing.bezier(0.5, 0, 0.75, 0);
/** The anchor's two halves. §6 asks for `0.7 -> 1.06 -> 1` *and* names the
 *  arrival curve, and the two cannot both be taken literally: that curve
 *  applied to a 0.7->1 scale peaks at 1.016, not at 1.06. The keyframes are
 *  the explicit numbers, so they win, and the curve contributes its shape -
 *  the peak is placed at x = 0.626, where the curve's own peak is, the rise
 *  uses the same handles with the overshoot taken out of y, and the settle
 *  back to 1 is a plain symmetric ease. */
const ANCHOR_PEAK = 1.06;
const ANCHOR_PEAK_AT = 0.626;
const EASE_ANCHOR_RISE = Easing.bezier(0.34, 1, 0.64, 1);
const EASE_ANCHOR_SETTLE = Easing.bezier(0.4, 0, 0.6, 1);

/** §6 in fractions of the phase, so that a movement the planner had to
 *  shorten (a beat 0.2 s into the video gets a 0.2 s arrival) keeps the same
 *  choreography instead of losing its last act. */
const ANCHOR_IN = 300 / 380;
const TEXT_IN_FROM = 120 / 380;
const TEXT_IN_TO = 260 / 380;
const TEXT_OUT = 100 / 240;
const ANCHOR_OUT_FROM = 40 / 240;
const ANCHOR_OUT_TO = 240 / 240;

const clamp01 = (x) => Math.min(1, Math.max(0, x));
const seconds = (value, fallback) => (typeof value === 'number' && value >= 0 ? value : fallback);

export const ComparisonLine = ({line, safeArea, theme, durationInFrames}) => {
  const frame = useCurrentFrame();
  const {fps, width} = useVideoConfig();
  useBadgeFonts();
  // CF-0572: the badge's palette and face, the channel's (plan.theme).
  const {
    paper: PAPER, ink: INK, ink_muted: INK_MUTED, rule: RULE,
    accent: ACCENT, accent_ink: ACCENT_INK,
  } = theme.badge;
  const badgeFont = theme.font.badge;

  // CF-0186: two halves, and either may be absent.
  //
  // The badge is a numbered pointer at a named publication, or it is not
  // drawn - all three of `publisher`, `ref` and `panel_w` or none of it.
  // The fact strip is our wording of the production fact, `line.text`, or it
  // is not drawn. The planner already refuses to write a line that has
  // neither (SKIP_NOTHING_TO_DRAW), so the guard below is against an old
  // plan, not a policy.
  const ref = line?.ref;
  const publisher = line?.publisher;
  const panelW = Math.max(0, Math.round(line?.panel_w ?? 0));
  const hasBadge = Boolean(publisher) && typeof ref === 'number' && ref > 0 && panelW > 0;
  const factText = typeof line?.text === 'string' && line.text.trim() ? line.text.trim() : null;
  if (!hasBadge && !factText) return null;
  // CF-0336: every box comes off the safe area, the same object the captions
  // and the watermark read.
  const geo = comparisonGeometry({line, safeArea, width});

  const total = Math.max(1, durationInFrames ?? 1) / fps;
  // The movement never eats the rest: it is what gives way when the mounted
  // range is short (CF-0117 clips the last line to the end card's first
  // frame).
  const inS = Math.min(seconds(line.move_in_s, MOVE_IN_SECONDS), total / 2);
  const outS = Math.min(seconds(line.move_out_s, MOVE_OUT_SECONDS), Math.max(0, total - inS));
  const t = frame / fps;
  const outFrom = total - outS;

  // Arrival, 0 -> 1 over `inS`, and the departure as a separate progression
  // so the two never blend into one soft dissolve.
  const arrive = inS > 0 ? clamp01(t / inS) : 1;
  const leave = outS > 0 ? clamp01((t - outFrom) / outS) : 0;

  // §7: the width is a whole number of pixels on every frame. A subpixel
  // edge shimmers once YouTube has compressed the frame.
  const growth = interpolate(arrive, [0, 1], [0, 1], {
    easing: EASE_ARRIVE, extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const shrink = interpolate(leave, [0, 1], [1, 0], {
    easing: EASE_LEAVE, extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  // The two phases are chosen, never blended: `Math.min` of them would clamp
  // the arrival's overshoot to 1 - which is exactly the character §6 asks
  // for, and it would be gone with no test able to see it. They cannot
  // overlap anyway: the planner keeps `move_in + rest + move_out` inside the
  // window and this component clips both to the mounted range.
  const reveal = Math.max(0, leave > 0 ? shrink : growth);
  const drawnW = Math.round(panelW * reveal);
  // The fact strip is revealed by the same edge on the same curve, so the
  // two rectangles read as one object coming out from under the anchor
  // rather than as two elements that happen to share a cue.
  const factW = geo.fact ? geo.fact.w : 0;
  const drawnFactW = Math.round(factW * reveal);

  // The anchor: a tick out with a real overshoot on the way in, and on the
  // way out it starts 40 ms after the panel and is the last thing gone.
  const anchorIn = inS > 0 ? clamp01(t / (inS * ANCHOR_IN)) : 1;
  const anchorScaleIn = anchorIn <= ANCHOR_PEAK_AT
    ? interpolate(anchorIn, [0, ANCHOR_PEAK_AT], [0.7, ANCHOR_PEAK], {
        easing: EASE_ANCHOR_RISE, extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      })
    : interpolate(anchorIn, [ANCHOR_PEAK_AT, 1], [ANCHOR_PEAK, 1], {
        easing: EASE_ANCHOR_SETTLE, extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
      });
  const anchorOut = interpolate(leave, [ANCHOR_OUT_FROM, ANCHOR_OUT_TO], [0, 1], {
    easing: EASE_LEAVE, extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const anchorScale = anchorScaleIn + (0.7 - anchorScaleIn) * anchorOut;
  const anchorOpacity = 1 - anchorOut;

  // The text is its own event: in 120 ms after the edge starts, out ahead of
  // it. Linear both ways - a curve on an opacity this short only makes the
  // start or the end of it vague.
  const textIn = interpolate(arrive, [TEXT_IN_FROM, TEXT_IN_TO], [0, 1], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const textOut = interpolate(leave, [0, TEXT_OUT], [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  const textOpacity = Math.min(textIn, textOut);

  const k = width / CANVAS_W;
  const rowStyle = (size, weight, color) => ({
    position: 'absolute',
    left: PANEL_PADDING,
    fontFamily: badgeFont,
    fontSize: size,
    fontWeight: weight,
    lineHeight: `${size}px`,
    color,
    whiteSpace: 'pre',
  });

  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: CANVAS_W,
        transform: `scale(${k})`,
        transformOrigin: '0 0',
      }}
    >
      {/* §1: the label, running out from under the anchor. Clipped rather
          than squeezed - the text inside keeps its own width, so the edge
          travels over finished typography instead of stretching it. */}
      {hasBadge ? (
      <>
      <div
        style={{
          position: 'absolute',
          left: geo.panel.x,
          top: geo.panel.y,
          width: drawnW,
          height: PANEL_H,
          background: PAPER,
          overflow: 'hidden',
          // §3: 2px rules top and bottom, "во всю ширину" - which during the
          // arrival is the width the panel has *on this frame*, overshoot
          // included, so the label reads as one object rather than as a
          // ruled card sliding out of a plain one.
          boxSizing: 'border-box',
          borderTop: `${RULE_H}px solid ${RULE}`,
          borderBottom: `${RULE_H}px solid ${RULE}`,
        }}
      >
        <div style={{position: 'absolute', left: 0, top: -RULE_H, width: panelW,
          height: PANEL_H}}>
          <div style={{opacity: textOpacity}}>
            <div
              style={{
                ...rowStyle(LABEL_SIZE, 400, INK_MUTED),
                top: LABEL_BASELINE - LABEL_SIZE * BASELINE_IN_EM,
                letterSpacing: `${LABEL_TRACKING}px`,
                // CSS puts a letter-space after the last glyph too; the
                // planner's width counts the gaps between glyphs only.
                marginRight: -LABEL_TRACKING,
              }}
            >
              {LABEL_BEFORE}
              <span
                style={{
                  display: 'inline-block',
                  width: LABEL_SIZE * MONO_ADVANCE,
                  textAlign: 'center',
                  fontFamily: BADGE_ARROW_STACK,
                }}
              >
                {LABEL_ARROW}
              </span>
              {LABEL_AFTER}
            </div>
            {/* §2: the name is the badge's centre of meaning, and it is set
                below the label and larger than it on purpose - in peripheral
                vision the eye should catch the masthead first. */}
            <div
              style={{
                ...rowStyle(NAME_SIZE, 700, INK),
                top: NAME_BASELINE - NAME_SIZE * BASELINE_IN_EM,
              }}
            >
              {publisher}
            </div>
          </div>
        </div>
      </div>

      {/* §1: the anchor, flush with the safe area's left margin (CF-0336), over the label's left
          end. Scaled from its left edge so it grows into the frame rather
          than out of the middle of nowhere. */}
      <div
        style={{
          position: 'absolute',
          left: geo.anchor.x,
          top: geo.anchor.y,
          width: ANCHOR_W,
          height: ANCHOR_H,
          background: ACCENT,
          opacity: anchorOpacity,
          transform: `scale(${anchorScale})`,
          transformOrigin: '0% 50%',
        }}
      >
        <div
          style={{
            position: 'absolute',
            left: 0,
            top: ANCHOR_H / 2 + (NUMERAL_SIZE * CAP_IN_EM) / 2
              - NUMERAL_SIZE * BASELINE_IN_EM,
            width: ANCHOR_W,
            textAlign: 'center',
            fontFamily: badgeFont,
            fontWeight: 700,
            fontSize: NUMERAL_SIZE,
            lineHeight: `${NUMERAL_SIZE}px`,
            color: ACCENT_INK,
          }}
        >
          {ref}
        </div>
      </div>
      </>
      ) : null}

      {/* CF-0186: the fact. Our wording of what the voice is saying at this
          moment, on the same paper and in the same ink as the badge, under
          it - or in its place when there is no source to name. Revealed by
          the same edge on the same curve; the text inside keeps its own
          width and wraps once, so the edge travels over finished typography
          exactly as it does over the label. */}
      {factText ? (
        <div
          style={{
            position: 'absolute',
            left: geo.fact.x,
            top: geo.fact.y,
            width: drawnFactW,
            background: PAPER,
            overflow: 'hidden',
            boxSizing: 'border-box',
            borderTop: `${RULE_H}px solid ${RULE}`,
            borderBottom: `${RULE_H}px solid ${RULE}`,
          }}
        >
          <div style={{width: factW, boxSizing: 'border-box',
            padding: `${PANEL_PADDING - RULE_H}px ${PANEL_PADDING}px`}}>
            <div
              style={{
                opacity: textOpacity,
                fontFamily: badgeFont,
                fontWeight: 700,
                fontSize: FACT_SIZE,
                lineHeight: FACT_LINE_HEIGHT,
                color: INK,
              }}
            >
              {factText}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
};
