import React from 'react';

/**
 * The channel's mark: `plan.watermark.text` is the channel's `display_name`
 * (scripts/channel_watermark.py, CF-0212), kept inside the safe area so no
 * platform's UI sits on top of it. Drawn in capitals - the planner writes
 * the text in capitals for that reason, and a plan without a channel carries
 * `watermark: null`, which draws nothing.
 */
const CORNERS = {
  'top-left': (s) => ({top: s.top, left: s.left}),
  'top-right': (s) => ({top: s.top, right: s.right}),
  'bottom-left': (s) => ({bottom: s.bottom, left: s.left}),
  'bottom-right': (s) => ({bottom: s.bottom, right: s.right}),
};

export const Watermark = ({watermark, safeArea, theme}) => {
  if (!watermark?.text) return null;
  const place = CORNERS[watermark.position] ?? CORNERS['top-left'];

  return (
    <div
      style={{
        position: 'absolute',
        ...place(safeArea),
        // CF-0572: the channel's display face and text colour at CC (80%)
        // alpha - plan.theme; the shadow is the same for every channel.
        fontFamily: theme.font.display,
        fontSize: theme.watermarkSize,
        letterSpacing: '0.06em',
        color: `${theme.text}CC`,
        textShadow: '0 2px 10px rgba(0,0,0,.6)',
        textTransform: 'uppercase',
      }}
    >
      {watermark.text}
    </div>
  );
};
