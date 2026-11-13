import React from 'react';
import {AbsoluteFill, interpolate, useCurrentFrame, useVideoConfig} from 'remotion';

/**
 * A deliberate text card (`asset_kind: card`, CF-0041).
 *
 * Not the same thing as `ProceduralBg`, even though neither loads a file. The
 * procedural background is the *floor* of the degradation chain - where a block
 * lands when its footage failed a gate - and it exists so the chain cannot fail
 * for want of an asset. A card is where a block was aimed on purpose: the
 * `count_card` opening of the `list` pattern puts the number the script promises
 * on screen in the first second, which is the fastest statement of that pattern
 * available. If both rendered the same way, `style_delivered` could not tell a
 * deliberate card from a video that ran out of footage - which is the whole
 * reason CF-0015 asked for a separate kind rather than reusing `typographic`.
 *
 * The factory draws this itself, so there is no source file, no rights to
 * clear, no asset gate and no crop (CF-0012's reading of this class). Nothing
 * here reads a font file or an image either: same constraint the procedural
 * background works under, for the same reason.
 */
export const CardLayer = ({block, zone, safeArea, theme, durationInFrames}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const local = durationInFrames
    ? frame / durationInFrames
    : (frame / fps - block.start) / Math.max(0.001, block.end - block.start);

  const text = block.asset.text ?? '';
  // A slow push in, so the card is not a dead frame next to moving footage.
  const scale = interpolate(local, [0, 1], [1.0, 1.05]);
  // The rule under the number sweeps out over the first third of the block.
  const ruleWidth = interpolate(local, [0, 0.33], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  // CF-0336: the card's text is laid out inside the safe area, the same
  // object the captions and the watermark read - the old `0 8%` side padding
  // (86 px) sat under the Shorts player's ~97 px cut on each side. The margins
  // are the frame's, taken relative to this zone (the main zone can be
  // shorter than the frame when a second plane is up).
  const pad = safeArea
    ? {
        paddingLeft: Math.max(0, safeArea.left - zone.x),
        paddingRight: Math.max(0, safeArea.right - (width - zone.x - zone.width)),
        paddingTop: Math.max(0, safeArea.top - zone.y),
        paddingBottom: Math.max(0, safeArea.bottom - (height - zone.y - zone.height)),
      }
    : {padding: '0 8%', paddingBottom: '22%'};

  return (
    <div
      style={{
        position: 'absolute',
        left: zone.x,
        top: zone.y,
        width: zone.width,
        height: zone.height,
        overflow: 'hidden',
        // CF-0572: the ground, the quote, the rule and the face are the
        // channel's (plan.theme): bg, card_ground (centre -> edge), accent,
        // accent2 -> accent, font.card.
        backgroundColor: theme.bg,
      }}
    >
      <AbsoluteFill
        style={{
          background:
            `radial-gradient(circle at 50% 42%, ${theme.card_ground[0]} 0%, ` +
            `${theme.card_ground[1]} 55%, ${theme.card_ground[2]} 100%)`,
        }}
      />
      <AbsoluteFill
        style={{
          transform: `scale(${scale})`,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          // The caption band owns the bottom of the frame, so the card's own
          // text sits above it rather than fighting the burned-in captions.
          ...pad,
          boxSizing: 'border-box',
        }}
      >
        <div
          style={{
            color: theme.accent,
            fontFamily: theme.font.card,
            fontWeight: 900,
            fontSize: 132,
            lineHeight: 1.05,
            letterSpacing: '-0.02em',
            textAlign: 'center',
            textTransform: 'uppercase',
            textShadow: '0 10px 40px rgba(0,0,0,0.55)',
          }}
        >
          {text}
        </div>
        <div
          style={{
            marginTop: 42,
            height: 12,
            width: `${ruleWidth * 46}%`,
            borderRadius: 6,
            background: `linear-gradient(90deg, ${theme.accent2}, ${theme.accent})`,
          }}
        />
      </AbsoluteFill>
    </div>
  );
};
