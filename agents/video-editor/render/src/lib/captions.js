/**
 * Word timings come from whisper transcribing Kokoro's own output, so they are
 * real, not proportional-by-character.
 *
 * v2 showed one word at a time ("IT", "ATE", "BITE"), which gives the eye
 * nothing to read ahead into. Words are grouped into short phrases here and the
 * spoken word is highlighted inside its phrase - the phrase supplies context,
 * the highlight supplies the rhythm.
 */
const CLAUSE_END = /[.,!?;:]$/;

const HAS_LETTERS = /[\p{L}\p{N}]/u;

/** Average advance of an upper-case Arial Black glyph, in em, and the gap
 *  Captions.jsx leaves between words. Used only to estimate how many lines a
 *  phrase wraps to - an estimate on the wide side, so a phrase is closed early
 *  rather than wrapped to a third line (CF-0394: at most two). */
export const GLYPH_EM = 0.8;
export const GAP_EM = 0.44;
const ACTIVE_EM = 1.1;

/** How many lines `words` wrap to in a row `capacityEm` wide (flex-wrap,
 *  greedy). Every word is counted at the spoken word's 1.1em, since any of
 *  them is spoken at some point while the phrase is up.
 *
 *  `padEm` (CF-0699, captionBand.js `captionBoxPadEm`): the side padding
 *  every word carries when the channel draws the active word on a pill -
 *  each word is that much wider on both sides, and the flex gap that much
 *  narrower, exactly as Captions.jsx lays the row out. 0 (no pill) counts
 *  what it always did. */
export const linesFor = (words, capacityEm, padEm = 0) => {
  let lines = 0;
  let used = 0;
  const gap = GAP_EM - padEm;
  for (const w of words) {
    const width = String(w.word).length * GLYPH_EM * ACTIVE_EM + 2 * padEm;
    if (lines === 0 || used + gap + width > capacityEm) {
      lines += 1;
      used = width;
    } else {
      used += gap + width;
    }
  }
  return lines;
};

/**
 * `fits` (CF-0394), when given, is asked before a word joins a phrase: a
 * phrase that would stop fitting with it is closed first, and the word opens
 * the next one.
 */
export const groupWords = (input, maxWords = 4, maxSeconds = 2.2, fits = null) => {
  // Reconciliation keeps the written text verbatim, dashes included, so a
  // standalone "—" arrives as its own token. It is punctuation, not a word to
  // put on screen alone.
  const words = input.filter((w) => HAS_LETTERS.test(w.word));
  const groups = [];
  let current = [];

  const flush = () => {
    if (!current.length) return;
    groups.push({
      words: current,
      start: current[0].start,
      end: current[current.length - 1].end,
    });
    current = [];
  };

  for (const w of words) {
    if (current.length && fits && !fits([...current, w])) flush();
    current.push(w);
    const span = current[current.length - 1].end - current[0].start;
    if (current.length >= maxWords || span >= maxSeconds || CLAUSE_END.test(w.word)) {
      flush();
    }
  }
  flush();
  return groups;
};

export const activeGroup = (groups, seconds) => {
  for (const g of groups) {
    if (seconds >= g.start && seconds < g.end) return g;
  }
  // Hold the neighbouring group through gaps so captions never blink out
  // mid-sentence just because the aligner found a pause.
  for (let i = 0; i < groups.length - 1; i++) {
    if (seconds >= groups[i].end && seconds < groups[i + 1].start) return groups[i];
  }
  // Nothing before the first word. Holding a group *backwards* is not the same
  // move as holding one through a pause - there is no neighbour behind the
  // first one, only a guess at what is about to be said. It cost nothing while
  // every voiceover started within a quarter second, and it broke the
  // cold_frame opening outright (CF-0050): the hook was legible on screen
  // through the whole silent beat the opening exists to hold.
  if (groups.length && seconds < groups[0].start) return null;
  return groups[groups.length - 1] ?? null;
};

export const activeWordIndex = (group, seconds) => {
  if (!group) return -1;
  for (let i = 0; i < group.words.length; i++) {
    const w = group.words[i];
    if (seconds >= w.start && seconds < w.end) return i;
  }
  return seconds >= group.end ? group.words.length - 1 : -1;
};
