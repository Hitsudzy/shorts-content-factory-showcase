import React from 'react';
import {rgba} from '../lib/theme';
import {EM, appear, fitSize, longest, str, wrap} from './kit';

const STEP_GAP = 0.5;   // seconds between one box and the next

/** CF-0689 `how_it_works`: two to five boxes joined by arrows, in order, an
 *  optional title above, centred. Each arrow draws itself from one box to
 *  the next before the next box comes in; the arrows carry no words. The
 *  more steps, the tighter the type (five boxes of 28 characters and a
 *  two-line title stay above the caption band - measured on a render). */
export const HowItWorks = ({data, theme, t, width}) => {
  const title = str(data.title);
  const steps = (Array.isArray(data.steps) ? data.steps : []).filter(str);
  const head = appear(t, 0.1, 0.5);
  const base = title ? 0.4 : 0.15;
  const n = steps.length;
  const fit = n >= 5 ? {max: 44, pad: '10px 20px', arrow: 34, title: 64}
    : n === 4 ? {max: 52, pad: '14px 22px', arrow: 44, title: 72}
      : {max: 62, pad: '20px 26px', arrow: 60, title: 84};
  const stepSize = fitSize(longest(steps), {max: fit.max, min: 34, width: width - 60,
                                            em: EM.card});
  return (
    <div style={{display: 'flex', flexDirection: 'column', alignItems: 'stretch'}}>
      {title ? (
        <div style={{opacity: head, transform: `translateY(${(1 - head) * 30}px)`, color: theme.text,
                     fontFamily: theme.font.display, fontWeight: 900, lineHeight: 1.05,
                     textAlign: 'center', marginBottom: 22,
                     fontSize: fitSize(title, {max: fit.title, min: 44, width,
                                               em: EM.display}),
                     ...wrap}}>{title}</div>
      ) : null}
      {steps.map((step, i) => {
        const at = base + i * STEP_GAP;
        const k = appear(t, at, 0.4);
        const draw = appear(t, at + 0.25, 0.3);
        const live = 0.5 + 0.5 * Math.sin((t - at) * 2.6);
        return (
          <React.Fragment key={i}>
            <div data-row={i} style={{opacity: k, transform: `scale(${0.9 + 0.1 * k})`,
                                      padding: fit.pad, borderRadius: 20,
                                      background: rgba(theme.card_ground[0], 0.92),
                                      border: `4px solid ${rgba(theme.accent2, 0.6 + 0.4 * live * k)}`,
                                      color: theme.text, fontFamily: theme.font.card,
                                      fontSize: stepSize, fontWeight: 800, lineHeight: 1.12,
                                      textAlign: 'center', ...wrap}}>{step}</div>
            {i < steps.length - 1 ? (
              <svg data-arrow={i} width="100%" height={fit.arrow} viewBox="0 0 100 64"
                   preserveAspectRatio="xMidYMid meet" style={{display: 'block'}}>
                <line x1="50" y1="4" x2="50" y2="48" stroke={theme.accent} strokeWidth="6"
                      strokeLinecap="round" strokeDasharray="44"
                      strokeDashoffset={(44 * (1 - draw)).toFixed(2)} />
                <path d="M38 42 L50 60 L62 42" fill="none" stroke={theme.accent} strokeWidth="6"
                      strokeLinecap="round" strokeLinejoin="round" opacity={draw >= 0.95 ? 1 : 0} />
              </svg>
            ) : null}
          </React.Fragment>
        );
      })}
    </div>
  );
};
