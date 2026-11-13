/**
 * CF-0405: the motion of a whole still meme inside its insert box.
 *
 * scripts/meme_layer.py meme_motion() decides it and writes it on the insert as
 * `motion`: `{mode: 'push_in', zoom_from, zoom_to}` - a slow push from the
 * `contain` fit, already bounded there by the file's headroom under the CF-0392
 * stretch ceiling - or `{mode: 'pan', axis: 'x'|'y', from, to}`, a slide along
 * the letterboxed axis by fractions of the box, or `{mode: 'static', why}`.
 * Anything else, or no `motion` at all (every plan written before 2026-09-26,
 * every GIF), is the still picture it always was: this returns null and the
 * insert is drawn exactly as before.
 *
 * `progress` is 0..1 over the insert's span; `box` is the picture box
 * ({width, height}) the meme is contained into. The picture box clips its
 * content when a motion is on, so neither move can reach below the box into
 * the caption band (CF-0379/CF-0394).
 *
 * Price (CF-0130's question, measured 2026-09-26): a 4 s plan, 120 frames at
 * 1080x1920, the meme over the whole block, `remotion render --concurrency=1`,
 * two runs each - static 18.58 s, push_in 19.55 s, static (small file) 18.36 s,
 * pan 19.37 s. About +0.008 s a frame, +5% on a meme block's own frames; two
 * memes of 3-5 s in a video are 180-300 frames, 1.5-2.5 s of one worker's
 * time. A CSS transform on one <Img>, no blur and no canvas - nothing like the
 * 0.36 s/frame ProceduralBg cost before CF-0130.
 */
const clamp01 = (p) => (p < 0 ? 0 : p > 1 ? 1 : p);
const lerp = (a, b, p) => a + (b - a) * p;
const num = (v) => typeof v === 'number' && Number.isFinite(v);

export const memeMotionTransform = (motion, progress, box) => {
  if (!motion || typeof motion !== 'object') return null;
  const p = clamp01(num(progress) ? progress : 0);
  if (motion.mode === 'push_in' && num(motion.zoom_to) && motion.zoom_to > 1) {
    const from = num(motion.zoom_from) ? motion.zoom_from : 1;
    return `scale(${lerp(from, motion.zoom_to, p).toFixed(5)})`;
  }
  if (motion.mode === 'pan' && num(motion.from) && num(motion.to) && box) {
    const side = motion.axis === 'x' ? box.width : box.height;
    if (!num(side)) return null;
    const px = (lerp(motion.from, motion.to, p) * side).toFixed(3);
    return motion.axis === 'x' ? `translateX(${px}px)` : `translateY(${px}px)`;
  }
  return null;
};
