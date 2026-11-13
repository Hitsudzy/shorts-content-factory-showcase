import React from 'react';
import {rgba} from '../lib/theme';
import {EM, appear, fitSize, str} from './kit';

/**
 * CF-0690 `api_chat` - "a demo via API": the topic's model answered one of
 * the channel's fixed prompts through its official API (the Trend Hunter's
 * call, kept as the topic's `api_demo_record`), and this is that REAL answer
 * drawn in the factory's own neutral chat - ExampleTech's theme, our panel,
 * no vendor's look: no logo, no avatar, no name of anyone's chat app.
 *
 * What is drawn, and nothing else (the root's shared/own_graphic.py
 * `viewer_text` is the same three lines):
 *
 *   - the header: `data.model_label` ("<display name> · via API", from the
 *     API's own modelVersion) and `data.date` when the order has one;
 *   - our prompt bubble: `data.prompt`, typed in character by character;
 *   - a short "thinking" pulse (three dots - shapes, no word);
 *   - the answer bubble: `data.answer` revealed word by word, then held.
 *
 * Every string is the data string exactly - the answer is never quoted,
 * never given a "…" of ours, never reworded; line breaks are kept
 * (pre-wrap). While a string is being typed or revealed, its rest is laid out
 * already but invisible, so the bubbles never grow and the panel never jumps;
 * the text nodes of the frame always add up to the data strings.
 *
 * The clock is `asset.chat_timing` (own_graphic_plan.chat_timing: scaled to
 * the block's run so the whole answer stands for at least 1.5 s); a plan
 * without it gets `defaultTiming` - the same unscaled numbers.
 *
 * Type is fitted to the actual strings by `chatSizes`: from large (prompt 54,
 * answer 64, label 44 px) down until the full prompt and the full answer fit
 * the panel's inner box - the safe area above the caption band; the worst
 * case (a 160-character prompt and a 280-character answer) still fits.
 * The answer bubble is reserved at its final size from the start (no jump)
 * but has no fill until its first word: while the model "thinks" only a faint
 * outline holds the place around the dots.
 */

/** The unscaled clock (= own_graphic_plan.py's IDEAL_* / LEAD). */
export const LEAD = 0.5;
const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
const words = (s) => (String(s ?? '').match(/\S+/g) || []).length;

export const defaultTiming = (data) => {
  const type = clamp(String(data?.prompt ?? '').length / 40, 0.8, 3.0);
  const think = 0.9;
  const reveal = clamp(words(data?.answer) / 6, 1.0, 4.0);
  return {type_start: LEAD, type_seconds: type, think_seconds: think, reveal_seconds: reveal,
          answer_full_at: LEAD + type + think + reveal};
};

const timingOf = (asset, data) => {
  const t = asset?.chat_timing;
  const ok = t && ['type_start', 'type_seconds', 'think_seconds', 'reveal_seconds']
    .every((k) => Number.isFinite(Number(t[k])));
  if (!ok) return defaultTiming(data);
  return {type_start: Number(t.type_start), type_seconds: Number(t.type_seconds),
          think_seconds: Number(t.think_seconds), reveal_seconds: Number(t.reveal_seconds)};
};

/** A glyph's advance as a share of the font size - Helvetica/Arial's metrics
 *  by class, on the generous side (the estimate must not under-count). */
const advance = (ch) => {
  if (ch === ' ') return 0.28;
  if ('iljI.,:;!|\'`'.includes(ch)) return 0.28;
  if ('frt()[]-"'.includes(ch)) return 0.36;
  if ('mw'.includes(ch)) return 0.84;
  if ('MW@%'.includes(ch)) return 0.94;
  if (/[A-Z]/.test(ch)) return 0.72;
  if (/[0-9]/.test(ch)) return 0.56;
  return 0.55;
};
const textWidth = (text, size) => {
  let w = 0;
  for (const ch of text) w += advance(ch);
  return w * size;
};

/** Lines of `text` at `size` in a column `width` px wide: a greedy word wrap
 *  as the browser does it (each data line break starts a line; a word longer
 *  than the line is broken - overflow-wrap: anywhere). */
export const wrapLines = (text, size, width) => {
  const room = width * 0.99;
  let n = 0;
  for (const para of String(text ?? '').split('\n')) {
    let line = 0;
    n += 1;
    for (const word of para.split(' ')) {
      const w = textWidth(word, size);
      const sp = line > 0 ? textWidth(' ', size) : 0;
      if (line > 0 && line + sp + w > room) {
        n += 1;
        line = 0;
      }
      if (w > room) {
        n += Math.floor(w / room);
        line = w % room;
      } else {
        line += (line > 0 ? sp : 0) + w;
      }
    }
  }
  return n;
};

/** Bubble paddings and the share of the width a bubble may take. */
const PAD_X = 26;
const PAD_Y = 18;
const PROMPT_SHARE = 0.9;
const ANSWER_BORDER = 6;
const GAP = 24;
const LINE = 1.24;

/** The type's largest sizes (px at 1080 wide) and its floors. */
export const MAX = {head: 44, prompt: 54, answer: 64};
export const MIN = {head: 30, prompt: 26, answer: 30};

/** The font sizes of the header, the prompt and the answer, fitted to the
 *  actual strings: from MAX down, together, until the full prompt and the
 *  full answer (wrapped as the browser would, `wrapLines`) fit `height` -
 *  never under MIN. A short chat is drawn big; only the worst case is small. */
export const chatSizes = (data, width, height) => {
  const label = [str(data.model_label), str(data.date)].filter(Boolean).join('   ');
  const head = fitSize(label, {max: MAX.head, min: MIN.head, width: width - 40, em: EM.card});
  const headH = wrapLines(label, head, width - 40) * head * 1.15;
  const promptW = width * PROMPT_SHARE - 2 * PAD_X - 4;
  const answerW = width - 2 * PAD_X - ANSWER_BORDER - 4;
  for (let k = 1; k > 0; k -= 0.02) {
    const p = Math.max(MIN.prompt, Math.round(MAX.prompt * k));
    const a = Math.max(MIN.answer, Math.round(MAX.answer * k));
    const h = headH + 4 + 3 * GAP
      + wrapLines(data.prompt, p, promptW) * p * LINE + 2 * PAD_Y + 4
      + wrapLines(data.answer, a, answerW) * a * LINE + 2 * PAD_Y;
    if (h <= height * 0.99 || (p === MIN.prompt && a === MIN.answer)) {
      return {head, prompt: p, answer: a};
    }
  }
  return {head, prompt: MIN.prompt, answer: MIN.answer};
};

/** `text` split at `n` characters: [shown, rest] - adding up to `text`. */
const splitAt = (text, n) => [text.slice(0, n), text.slice(n)];

/** The end index of each word of `text` (with the space after it). */
const wordEnds = (text) => Array.from(text.matchAll(/\S+\s*/g), (m) => m.index + m[0].length);

const pre = {whiteSpace: 'pre-wrap', overflowWrap: 'anywhere', wordBreak: 'normal'};

export const ApiChat = ({data, asset, theme, t, width, height}) => {
  const label = str(data.model_label);
  const date = str(data.date);
  const prompt = typeof data.prompt === 'string' ? data.prompt : '';
  const answer = typeof data.answer === 'string' ? data.answer : '';
  const clock = timingOf(asset, data);
  const sizes = chatSizes(data, width, height || width * 1.3);

  const typeEnd = clock.type_start + clock.type_seconds;
  const thinkEnd = typeEnd + clock.think_seconds;
  const revealEnd = thinkEnd + clock.reveal_seconds;

  // The prompt, character by character.
  const typedK = clamp((t - clock.type_start) / Math.max(0.01, clock.type_seconds), 0, 1);
  const [typed, untyped] = splitAt(prompt, Math.round(typedK * prompt.length));
  const typing = t < typeEnd;

  // The answer, word by word: the words in, the one coming in, the rest.
  const ends = wordEnds(answer);
  const revealK = clamp((t - thinkEnd) / Math.max(0.01, clock.reveal_seconds), 0, 1);
  const pos = revealK * ends.length;
  const whole = Math.min(ends.length, Math.floor(pos));
  const shownEnd = whole > 0 ? ends[whole - 1] : 0;
  const nextEnd = whole < ends.length ? ends[whole] : answer.length;
  const fade = whole < ends.length ? pos - whole : 0;
  const shown = revealK >= 1 ? answer : answer.slice(0, shownEnd);
  const coming = revealK >= 1 ? '' : answer.slice(shownEnd, nextEnd);
  const rest = revealK >= 1 ? '' : answer.slice(nextEnd);

  const head = appear(t, 0.05, 0.45);
  const promptIn = appear(t, 0.2, 0.35);
  const answerIn = appear(t, typeEnd, 0.3);
  const thinking = t >= typeEnd && t < thinkEnd + 0.2;
  // the reserved answer bubble is filled from its first word on
  const fill = appear(t, thinkEnd, 0.3);
  const thinkOut = 1 - appear(t, thinkEnd, 0.2);
  const blink = Math.floor(t * 2.5) % 2 === 0 ? 1 : 0.35;
  // The header's live dot breathes for the whole block (the frame is never
  // a still, beside the traces' pulses).
  const live = 0.55 + 0.45 * Math.sin(t * Math.PI * 1.4);

  return (
    <div style={{display: 'flex', flexDirection: 'column', gap: GAP}}>
      <div style={{opacity: head, transform: `translateY(${(1 - head) * 24}px)`,
                   display: 'flex', alignItems: 'center', gap: 16}}>
        <div style={{width: 18, height: 18, borderRadius: 9, flex: '0 0 auto',
                     background: theme.accent, opacity: live,
                     boxShadow: `0 0 ${10 + 8 * live}px ${rgba(theme.accent, 0.6)}`}} />
        {label ? (
          <div style={{color: theme.text, fontFamily: theme.font.card, fontSize: sizes.head,
                       fontWeight: 800, lineHeight: 1.15, flex: '1 1 auto', ...pre}}>{label}</div>
        ) : null}
        {date ? (
          <div style={{color: theme.muted, fontFamily: theme.font.text,
                       fontSize: Math.round(sizes.head * 0.72), flex: '0 0 auto'}}>{date}</div>
        ) : null}
      </div>
      <div style={{height: 4, borderRadius: 2, marginTop: -10,
                   width: `${appear(t, 0.2, 0.6) * 100}%`,
                   background: `linear-gradient(90deg, ${theme.accent2}, ${theme.accent})`}} />

      <div data-chat="prompt" style={{
        alignSelf: 'flex-end', maxWidth: `${PROMPT_SHARE * 100}%`, boxSizing: 'border-box',
        padding: `${PAD_Y}px ${PAD_X}px`, borderRadius: '28px 28px 8px 28px',
        background: rgba(theme.accent2, 0.24), border: `2px solid ${rgba(theme.accent2, 0.7)}`,
        opacity: promptIn, transform: `translateY(${(1 - promptIn) * 20}px)`,
        color: theme.text, fontFamily: theme.font.text, fontSize: sizes.prompt,
        lineHeight: LINE, ...pre,
      }}>
        {typed ? <span>{typed}</span> : null}
        {typing ? (
          <span style={{display: 'inline-block', width: 7, height: '1.05em', marginLeft: 3,
                        verticalAlign: '-0.12em', background: theme.accent, opacity: blink}} />
        ) : null}
        {untyped ? <span style={{opacity: 0}}>{untyped}</span> : null}
      </div>

      <div data-chat="answer" style={{
        position: 'relative', alignSelf: 'stretch', boxSizing: 'border-box',
        padding: `${PAD_Y}px ${PAD_X}px`, borderRadius: '8px 28px 28px 28px',
        background: rgba(theme.card_ground[0], 0.95 * fill),
        borderLeft: `${ANSWER_BORDER}px solid ${rgba(theme.accent, 0.25 + 0.75 * fill)}`,
        opacity: answerIn, transform: `translateY(${(1 - answerIn) * 20}px)`,
        color: theme.text, fontFamily: theme.font.text, fontSize: sizes.answer,
        lineHeight: LINE, ...pre,
      }}>
        {thinking ? (
          <div data-chat="thinking" style={{position: 'absolute', left: PAD_X, top: PAD_Y + 6,
                                            display: 'flex', gap: 14, opacity: thinkOut}}>
            {[0, 1, 2].map((i) => {
              const k = 0.5 + 0.5 * Math.sin(t * Math.PI * 4 - i * 0.9);
              return (
                <div key={i} style={{width: 18, height: 18, borderRadius: 9,
                                     background: theme.accent, opacity: 0.35 + 0.65 * k,
                                     transform: `translateY(${-8 * k}px)`}} />
              );
            })}
          </div>
        ) : null}
        {shown ? <span>{shown}</span> : null}
        {coming ? <span style={{opacity: fade}}>{coming}</span> : null}
        {rest ? <span style={{opacity: 0}}>{rest}</span> : null}
      </div>
    </div>
  );
};
