import React from 'react';
import {rgba} from '../lib/theme';
import {EM, appear, fitSize, itemDelay, longest, rowsOf, str, wrap} from './kit';

/** CF-0689 `spec_card`: a product and up to four of its specs (label: value),
 *  the rows coming in one after another. Draws `data` and nothing else.
 *  Type is fitted to the panel's width (kit.fitSize): a short name is big. */
export const SpecCard = ({data, theme, t, width}) => {
  const product = str(data.product);
  const rows = rowsOf(data, 'rows');
  const head = appear(t, 0.1, 0.5);
  const many = rows.length >= 4;
  const rowW = width - 2 * 26 - 10;
  const titleSize = fitSize(product, {max: 104, min: 56, width, em: EM.display});
  const labelSize = fitSize(longest(rows.map((r) => r.label)),
                            {max: many ? 42 : 48, min: 34, width: rowW, em: EM.text});
  const valueSize = fitSize(longest(rows.map((r) => r.value)),
                            {max: many ? 62 : 74, min: 44, width: rowW, em: EM.card});
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: many ? 18 : 24}}>
      {product ? (
        <div style={{opacity: head, transform: `translateY(${(1 - head) * 30}px)`,
                     textAlign: 'center'}}>
          <div style={{color: theme.text, fontFamily: theme.font.display, fontSize: titleSize,
                       fontWeight: 900, lineHeight: 1.05, ...wrap}}>{product}</div>
          <div style={{margin: '16px auto 0', height: 10, borderRadius: 5,
                       width: `${appear(t, 0.3, 0.7) * 70}%`,
                       background: `linear-gradient(90deg, ${theme.accent2}, ${theme.accent})`}} />
        </div>
      ) : null}
      {rows.map((row, i) => {
        const k = appear(t, itemDelay(i, 0.55));
        return (
          <div key={i} data-row={i} style={{
            opacity: k, transform: `translateX(${(1 - k) * 48}px)`,
            padding: many ? '14px 26px' : '18px 26px', borderRadius: 20,
            background: rgba(theme.card_ground[0], 0.9),
            borderLeft: `10px solid ${theme.accent}`,
          }}>
            {str(row.label) ? (
              <div style={{color: theme.muted, fontFamily: theme.font.text, fontSize: labelSize,
                           lineHeight: 1.12, ...wrap}}>{row.label}</div>
            ) : null}
            {str(row.value) ? (
              <div style={{color: theme.text, fontFamily: theme.font.card, fontSize: valueSize,
                           fontWeight: 800, lineHeight: 1.08, marginTop: 4, ...wrap}}>{row.value}</div>
            ) : null}
          </div>
        );
      })}
    </div>
  );
};
