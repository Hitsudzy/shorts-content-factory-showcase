import React from 'react';
import {rgba} from '../lib/theme';
import {EM, appear, fitSize, itemDelay, longest, rowsOf, str, wrap} from './kit';

/** CF-0689 `comparison`: two things side by side and up to three rows, each
 *  the same point on both sides (an optional label above it). The divider
 *  grows between the columns; no "vs" or any word of the template's. */
export const Comparison = ({data, theme, t, width}) => {
  const rows = rowsOf(data, 'rows');
  const head = appear(t, 0.1, 0.5);
  const col = (width - 40) / 2;
  const nameSize = fitSize(longest([data.left, data.right]),
                           {max: 76, min: 40, width: col, em: EM.display});
  const rowCol = (width - 2 * 22 - 40) / 2;
  const valueSize = fitSize(longest(rows.flatMap((r) => [r.left, r.right])),
                            {max: 66, min: 38, width: rowCol, em: EM.card});
  const labelSize = fitSize(longest(rows.map((r) => r.label)),
                            {max: 46, min: 34, width: width - 44, em: EM.text});
  const side = (text, colour, k, align) => (
    <div style={{flex: 1, minWidth: 0, textAlign: align, opacity: k}}>
      {str(text) ? (
        <div style={{color: theme.text, fontFamily: theme.font.display, fontSize: nameSize,
                     fontWeight: 900, lineHeight: 1.05, ...wrap}}>{text}</div>
      ) : null}
      <div style={{marginTop: 12, height: 10, borderRadius: 5, background: colour,
                   width: `${k * 100}%`, marginLeft: align === 'right' ? 'auto' : 0}} />
    </div>
  );
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: 24}}>
      <div style={{display: 'flex', gap: 40, alignItems: 'flex-end'}}>
        {side(data.left, theme.accent, head, 'left')}
        {side(data.right, theme.accent2, appear(t, 0.25, 0.5), 'right')}
      </div>
      {rows.map((row, i) => {
        const k = appear(t, itemDelay(i, 0.6));
        return (
          <div key={i} data-row={i} style={{opacity: k, transform: `translateY(${(1 - k) * 30}px)`,
                                            padding: '16px 22px', borderRadius: 20,
                                            background: rgba(theme.card_ground[0], 0.9)}}>
            {str(row.label) ? (
              <div style={{color: theme.muted, fontFamily: theme.font.text, fontSize: labelSize,
                           textAlign: 'center', marginBottom: 8, ...wrap}}>{row.label}</div>
            ) : null}
            <div style={{display: 'flex', gap: 18, alignItems: 'center'}}>
              <div style={{flex: 1, minWidth: 0, color: theme.text, fontFamily: theme.font.card,
                           fontSize: valueSize, fontWeight: 800, lineHeight: 1.08, ...wrap}}>{row.left}</div>
              <div style={{width: 4, alignSelf: 'stretch', borderRadius: 2,
                           background: `linear-gradient(180deg, ${theme.accent}, ${theme.accent2})`,
                           transform: `scaleY(${k})`}} />
              <div style={{flex: 1, minWidth: 0, color: theme.text, fontFamily: theme.font.card,
                           fontSize: valueSize, fontWeight: 800, lineHeight: 1.08, textAlign: 'right',
                           ...wrap}}>{row.right}</div>
            </div>
          </div>
        );
      })}
    </div>
  );
};
