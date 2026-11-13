import React from 'react';
import {rgba} from '../lib/theme';
import {EM, appear, fitSize, str, wrap} from './kit';

/** CF-0689 `price_date`: a product with its price and / or its release date
 *  and one short note, centred. The price lands as it is written - never
 *  counted up through numbers that are not it - and as big as it fits. */
export const PriceDate = ({data, theme, t, width}) => {
  const product = str(data.product);
  const price = str(data.price);
  const date = str(data.date);
  const note = str(data.note);
  const a = appear(t, 0.1, 0.5);
  const p = appear(t, 0.45, 0.55);
  const d = appear(t, price ? 0.8 : 0.45, 0.5);
  const n = appear(t, 1.1, 0.5);
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: 30, alignItems: 'center',
                 textAlign: 'center'}}>
      {product ? (
        <div style={{opacity: a, transform: `translateY(${(1 - a) * 30}px)`, color: theme.text,
                     fontFamily: theme.font.display, fontWeight: 900, lineHeight: 1.05,
                     fontSize: fitSize(product, {max: 100, min: 56, width, em: EM.display}),
                     ...wrap}}>{product}</div>
      ) : null}
      {price ? (
        <div style={{opacity: p, transform: `scale(${0.82 + 0.18 * p})`,
                     color: theme.accent, fontFamily: theme.font.display, fontWeight: 900,
                     lineHeight: 1,
                     fontSize: fitSize(price, {max: 190, min: 72, width, em: EM.display}),
                     ...wrap}}>{price}</div>
      ) : null}
      {date ? (
        <div style={{opacity: d, transform: `translateY(${(1 - d) * 24}px)`,
                     padding: '14px 30px', borderRadius: 999, maxWidth: '100%', boxSizing: 'border-box',
                     border: `5px solid ${theme.accent2}`, background: rgba(theme.card_ground[0], 0.9),
                     color: theme.text, fontFamily: theme.font.card, fontWeight: 800,
                     fontSize: fitSize(date, {max: 70, min: 42, width: width - 80, em: EM.card}),
                     ...wrap}}>{date}</div>
      ) : null}
      {note ? (
        <div style={{opacity: n, color: theme.muted, fontFamily: theme.font.text, lineHeight: 1.18,
                     fontSize: fitSize(note, {max: 52, min: 38, width, em: EM.text}),
                     ...wrap}}>{note}</div>
      ) : null}
    </div>
  );
};
