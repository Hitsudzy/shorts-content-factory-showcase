import React from 'react';
import {rgba} from '../lib/theme';
import {EM, appear, fitSize, itemDelay, longest, rowsOf, str, wrap} from './kit';

/** CF-0689 `timeline`: two to five dated events in order, centred. The spine
 *  draws down, each event lands on it in turn and its dot keeps pulsing.
 *  Up to three events stack the date over its label; four or five set them
 *  side by side so the column stays above the caption band. */
export const Timeline = ({data, theme, t, width}) => {
  const events = rowsOf(data, 'events');
  const spine = appear(t, 0.1, 0.25 + events.length * 0.22);
  const tight = events.length >= 4;
  const textW = width - 70;
  const dateW = tight ? textW * 0.36 : textW;
  const labelW = tight ? textW - dateW - 20 : textW;
  const dateSize = fitSize(longest(events.map((e) => e.date)),
                           {max: tight ? 52 : 72, min: 34, width: dateW, em: EM.card});
  const labelSize = fitSize(longest(events.map((e) => e.label)),
                            {max: tight ? 42 : 54, min: 32, width: labelW, em: EM.text});
  return (
    <div style={{position: 'relative', paddingLeft: 70, alignSelf: 'center', maxWidth: '100%',
                 boxSizing: 'border-box'}}>
      <div style={{position: 'absolute', left: 22, top: 12, width: 8, borderRadius: 4,
                   height: `calc(${(spine * 100).toFixed(2)}% - 24px)`,
                   background: `linear-gradient(180deg, ${theme.accent}, ${theme.accent2})`}} />
      <div style={{display: 'flex', flexDirection: 'column', gap: tight ? 22 : 32}}>
        {events.map((ev, i) => {
          const k = appear(t, itemDelay(i, 0.25), 0.45);
          const pulse = 1 + 0.18 * Math.max(0, Math.sin((t - i * 0.4) * 3.2)) * k;
          return (
            <div key={i} data-row={i} style={{position: 'relative', opacity: k,
                                              transform: `translateX(${(1 - k) * 40}px)`,
                                              display: tight ? 'flex' : 'block', gap: 20,
                                              alignItems: 'baseline'}}>
              <div style={{position: 'absolute', left: -62, top: tight ? 4 : 12, width: 32,
                           height: 32, borderRadius: 16, background: theme.bg,
                           border: `6px solid ${theme.accent}`, transform: `scale(${pulse})`,
                           boxShadow: `0 0 0 6px ${rgba(theme.accent2, 0.35)}`}} />
              {str(ev.date) ? (
                <div style={{color: theme.accent, fontFamily: theme.font.card, fontSize: dateSize,
                             fontWeight: 900, lineHeight: 1.08,
                             ...(tight ? {width: dateW, flexShrink: 0} : {}), ...wrap}}>{ev.date}</div>
              ) : null}
              {str(ev.label) ? (
                <div style={{color: theme.text, fontFamily: theme.font.text, fontSize: labelSize,
                             lineHeight: 1.15, marginTop: tight ? 0 : 6, minWidth: 0,
                             ...wrap}}>{ev.label}</div>
              ) : null}
            </div>
          );
        })}
      </div>
    </div>
  );
};
