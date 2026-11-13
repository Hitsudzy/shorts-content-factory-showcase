import React from 'react';
import {rgba} from '../lib/theme';
import {EM, appear, fitSize, itemDelay, longest, rowsOf, str, wrap} from './kit';

/** CF-0689 `benchmark`: one metric and two to five contenders as bars. Each
 *  bar grows to its share of the largest score - `asset.bars`, read by the
 *  plan off the scores themselves (shared/own_graphic.py parse_numbers); a
 *  score that cannot be read draws every bar full, implying no ranking. The
 *  score itself appears, big, as written once its bar has grown. The source
 *  line («According to X») is the layer's caption. */
export const Benchmark = ({data, asset, theme, t, width}) => {
  const metric = str(data.metric);
  const rows = rowsOf(data, 'rows');
  const bars = Array.isArray(asset?.bars) && asset.bars.length === rows.length ? asset.bars : null;
  const head = appear(t, 0.1, 0.5);
  const many = rows.length >= 4;
  const scoreSize = fitSize(longest(rows.map((r) => r.score)),
                            {max: many ? 64 : 80, min: 44, width: width * 0.4, em: EM.display});
  const nameSize = fitSize(longest(rows.map((r) => r.name)),
                           {max: many ? 44 : 52, min: 34, width: width * 0.6, em: EM.text});
  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: many ? 16 : 24}}>
      {metric ? (
        <div style={{opacity: head, transform: `translateY(${(1 - head) * 30}px)`, color: theme.text,
                     fontFamily: theme.font.display, fontWeight: 900, lineHeight: 1.05,
                     textAlign: 'center',
                     fontSize: fitSize(metric, {max: 84, min: 48, width, em: EM.display}),
                     ...wrap}}>{metric}</div>
      ) : null}
      {rows.map((row, i) => {
        const start = itemDelay(i, 0.45);
        const k = appear(t, start, 0.35);
        const grow = appear(t, start + 0.1, 0.9);
        const share = bars ? Math.max(0.04, Math.min(1, Number(bars[i]) || 0)) : 1;
        const top = bars && Number(bars[i]) >= 0.999;
        return (
          <div key={i} data-row={i} style={{opacity: k}}>
            <div style={{display: 'flex', justifyContent: 'space-between', alignItems: 'flex-end',
                         gap: 18}}>
              <div style={{color: theme.text, fontFamily: theme.font.text, fontSize: nameSize,
                           fontWeight: 700, lineHeight: 1.1, minWidth: 0, ...wrap}}>{row.name}</div>
              <div style={{color: top ? theme.accent : theme.text, fontFamily: theme.font.display,
                           fontSize: scoreSize, fontWeight: 900, lineHeight: 1, whiteSpace: 'nowrap',
                           opacity: appear(t, start + 0.7, 0.35)}}>{row.score}</div>
            </div>
            <div style={{marginTop: 8, height: many ? 30 : 40, borderRadius: 20,
                         background: rgba(theme.accent2, 0.22), overflow: 'hidden'}}>
              <div data-bar={i} style={{height: '100%', borderRadius: 20,
                                        width: `${(share * grow * 100).toFixed(2)}%`,
                                        background: `linear-gradient(90deg, ${theme.accent2}, ${theme.accent})`}} />
            </div>
          </div>
        );
      })}
    </div>
  );
};
