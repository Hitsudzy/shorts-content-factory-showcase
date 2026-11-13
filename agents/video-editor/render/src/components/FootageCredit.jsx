import React from 'react';

/**
 * CF-0664 (VE-1): the credit of the footage's owner over its shots -
 * `plan.credit_overlays[]` (scripts/footage_credits.py), one per run of
 * blocks showing a source whose origin's terms want the credit on the picture
 * (ESA, ESA/Hubble, ESO: CC BY / BY-SA, «clearly and visibly»).
 *
 * Small, in the safe area, in the top corner opposite the watermark (the
 * fact badge and strip are on the watermark's side, the captions at the
 * bottom), in the channel's `muted` colour and text face - plan.theme
 * (CF-0572) - with the watermark's shadow so it reads over any picture. The
 * words are the planner's; nothing here composes or shortens them.
 */
const OPPOSITE = {
  'top-left': 'right',
  'bottom-left': 'right',
  'top-right': 'left',
  'bottom-right': 'left',
};

export const CREDIT_SIZE_RATIO = 0.75;

export const FootageCredit = ({credit, watermark, safeArea, theme}) => {
  const lines = credit?.lines ?? [];
  if (!lines.length) return null;
  const side = OPPOSITE[watermark?.position] ?? 'right';
  return (
    <div
      style={{
        position: 'absolute',
        top: safeArea.top,
        [side]: safeArea[side],
        textAlign: side,
        fontFamily: theme.font.text,
        fontSize: Math.round(theme.watermarkSize * CREDIT_SIZE_RATIO),
        lineHeight: 1.25,
        color: theme.muted,
        textShadow: '0 2px 8px rgba(0,0,0,.7)',
      }}
    >
      {lines.map((line, i) => (
        <div key={i}>{line}</div>
      ))}
    </div>
  );
};
