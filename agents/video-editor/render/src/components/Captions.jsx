import React from 'react';
import {useCurrentFrame, useVideoConfig} from 'remotion';
import {groupWords, activeGroup, activeWordIndex, linesFor, GAP_EM} from '../lib/captions';
import {
  bandBottom, captionFontSize, captionStrokeWidth, CAPTION_LINE_HEIGHT,
  CAPTION_MAX_LINES, CAPTION_MAX_SECONDS, CAPTION_MAX_WORDS,
  CAPTION_BOX_PAD_X_EM, CAPTION_BOX_PAD_Y_EM, CAPTION_BOX_RADIUS_EM, captionBoxPadEm,
} from '../lib/captionBand';
import {captionColours} from '../lib/theme';

/**
 * Phrase-with-highlight captions, pinned inside the safe area so platform UI
 * never covers them.
 *
 * CF-0394 (variant D, the user's pick of 2026-09-25): small type, at most two
 * lines, the band's foot flush with the top of the bottom dead zone, and it
 * never moves - lib/captionBand.js has the numbers and the reasoning.
 */
export const Captions = ({words, safeArea, theme, hiddenRanges}) => {
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();
  const t = frame / fps;
  const fontSize = captionFontSize(theme);
  const stroke = captionStrokeWidth(theme);
  // CF-0699: the captions' own colours (default: text/accent) and the
  // optional pill behind the spoken word - captionBand.js says how a pill
  // keeps the row from sliding sideways.
  const colours = captionColours(theme);
  const padEm = captionBoxPadEm(colours.box);

  // Every hook runs before the first `return null` below. Found by CF-0117's
  // first render: with the useMemo *after* the hiddenRanges return, the frame
  // on which a hidden range opens rendered two hooks where the frame before
  // it rendered three, and React threw #300 ("rendered fewer hooks than
  // expected") - the whole render died at the moment the end card came up.
  // The same trap was waiting under CF-0071's insert ranges, which no real
  // plan had exercised yet. Hooks first, then the early returns.
  // CF-0394: phrases short enough to stay within two lines at this size -
  // closed by word count, by time, and by the estimated wrap, whichever
  // comes first.
  const capacityEm = safeArea.innerWidth / fontSize;
  const groups = React.useMemo(
    () => groupWords(words, CAPTION_MAX_WORDS, CAPTION_MAX_SECONDS,
      (phrase) => linesFor(phrase, capacityEm, padEm) <= CAPTION_MAX_LINES),
    [words, capacityEm, padEm]);

  // CF-0071: quiet for the span of any block Video.jsx flagged via
  // hiddenRanges (a block carrying a proof insert, and since CF-0117 the end
  // card's own span - nothing of ours draws over the channel's signature).
  // This component does not know what an insert is, only when to go quiet -
  // the same reason Video.jsx computes the ranges generically off the
  // insert's `captions` field rather than a hard-coded kind. CF-0379: that
  // field is what CF-0067's meme now answers differently - a meme leaves the
  // captions on (and since CF-0390 a proof card too).
  if ((hiddenRanges ?? []).some((r) => t >= r.start && t < r.end)) return null;

  // CF-0394: one place for the whole video. CF-0379/CF-0390 raised the band
  // clear of an insert for its span; the user saw that as the captions
  // jumping, and now the insert is fitted above the band instead
  // (captionBand.js insertBox, AssetLayer.jsx). `bottom` anchors the row's
  // own foot, so a two-line phrase grows upward from the dead zone - the box
  // has no fixed height and no overflow clip (the scratch fork's fixed
  // 2-line box cut the top line: flex-wrap sizes its lines from the items,
  // not from line-height, and the spoken word's 1.1em made them taller).
  const bottom = bandBottom(safeArea);

  const group = activeGroup(groups, t);
  if (!group) return null;

  const active = activeWordIndex(group, t);

  return (
    <div
      style={{
        position: 'absolute',
        left: safeArea.left,
        width: safeArea.innerWidth,
        bottom,
        display: 'flex',
        flexWrap: 'wrap',
        justifyContent: 'center',
        alignItems: 'flex-end',
        // The stroke grows each glyph outward, so the gap has to clear
        // twice the stroke width before any space is actually visible.
        // CF-0699: with a pill every word carries its side padding, and the
        // gap gives the same amount back.
        gap: colours.box ? `${GAP_EM - padEm}em` : '0.44em',
        // CF-0572: the channel's display face (plan.theme.font.display).
        fontFamily: theme.font.display,
        fontSize,
        lineHeight: CAPTION_LINE_HEIGHT,
        textTransform: 'uppercase',
      }}
    >
      {group.words.map((w, i) => {
        const isActive = i === active;
        if (colours.box) {
          // CF-0699: the pill. Every word is laid out the same (padding on
          // both sides, cancelled vertically, no size bump), so the row is
          // as wide whichever word is spoken; only the spoken one gets the
          // ground, and loses the stroke - the pill carries its contrast.
          return (
            <span
              key={`${group.start}-${i}`}
              style={{
                color: isActive ? colours.active : colours.text,
                ...(isActive ? {} : {WebkitTextStroke: `${stroke}px #000000`}),
                paintOrder: 'stroke fill',
                fontSize: '1em',
                transition: 'none',
                display: 'inline-block',
                padding: `${CAPTION_BOX_PAD_Y_EM}em ${CAPTION_BOX_PAD_X_EM}em`,
                margin: `-${CAPTION_BOX_PAD_Y_EM}em 0`,
                ...(isActive ? {
                  backgroundColor: colours.box,
                  borderRadius: `${CAPTION_BOX_RADIUS_EM}em`,
                } : {}),
              }}
            >
              {w.word}
            </span>
          );
        }
        return (
          <span
            key={`${group.start}-${i}`}
            style={{
              // CF-0572: both colours are the channel's; the black stroke
              // under them is the same for every channel.
              // CF-0699: caption_active/caption_text when the channel sets
              // them (lib/theme.js captionColours).
              color: isActive ? colours.active : colours.text,
              WebkitTextStroke: `${stroke}px #000000`,
              paintOrder: 'stroke fill',
              // Emphasis is font size, not transform. A transform does not
              // reflow, so a scaled word grew over its neighbour by 5% of its
              // own width - which no fixed gap can clear, because the overflow
              // scales with word length. "THE TRANSLATION." rendered glued.
              fontSize: isActive ? '1.1em' : '1em',
              transition: 'none',
              display: 'inline-block',
            }}
          >
            {w.word}
          </span>
        );
      })}
    </div>
  );
};
