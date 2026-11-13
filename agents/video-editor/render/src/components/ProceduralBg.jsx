import React, {useLayoutEffect, useRef} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';

/**
 * Background for the `typographic` style.
 *
 * `typographic` is the last rung of the degradation chain, so it must render
 * with zero external assets - if it could fail for want of a file, the chain
 * would have no floor. Everything here is computed: colors are hardcoded
 * palettes, shapes are gradients, and every position is a pure function
 * of the frame number, no `Math.random()` (which would fight determinism
 * across a multi-worker encode) and no fonts/images/files.
 *
 * CF-0032: the original version (5 blurred blobs at ~30% alpha on a near-
 * black background, drifting at a barely-perceptible speed) technically
 * satisfied "must not fail" but read to a viewer as "no background, just
 * text." This version keeps the same constraint but pushes the visual
 * budget much harder: brighter/richer gradients, faster organic motion,
 * a particle field, a periodic light sweep, and curated palettes instead
 * of one dark navy variant.
 *
 * CF-0130: how those layers are painted, not what they look like.
 *
 * CF-0052 measured this component at 32.6x realtime in Chrome's software
 * rasteriser - four times the cost of the footage it stands in for, and it
 * is the *floor* of the degradation chain, so a bad footage pool is paid for
 * twice. The same measurement ruled out the obvious suspect: the pre-CF-0032
 * version (5 blobs, no wash, no particles) was only 4.6% cheaper, so it is
 * not the number of elements. It is that every frame re-rasterised
 * full-frame CSS `filter: blur()` - one blur(90px) conic wash and seven
 * blur(42px) blobs across 1080x1920 - and a blur is the one filter whose
 * cost is the pixel count times the kernel.
 *
 * Two facts about those layers make that work avoidable:
 *
 *   - none of them changes shape. The wash is a static conic gradient that
 *     only *rotates*; a blob is a static blurred ellipse that only *moves*.
 *     So each distinct shape is blurred once into an offscreen canvas
 *     (`bakeWash` / `bakeBlob`, cached at module scope for the life of the
 *     page) and every later frame is a `drawImage` of that bitmap.
 *   - they are, after a 42-126px blur, band-limited: there is nothing in
 *     them that survives to a single pixel. So the compositing happens on a
 *     canvas at 1/DOWNSCALE of the frame and the browser scales it up. That
 *     is 16x fewer pixels to touch, and the bilinear upscale it costs is the
 *     kind of smoothing these layers are made of anyway.
 *
 * What is deliberately NOT on that canvas: the particles (small, crisp,
 * their glow is sharper than the canvas grid), the light sweep and the
 * caption scrim (plain unblurred gradients - a single pass each, already
 * cheap). Geometry, colors and timing are unchanged from the CSS version;
 * the canvas replays the same layer stack in the same order, including
 * `screen` blending of the blobs over the wash.
 */

// Deterministic string hash -> [0, 1). Used to pick a palette so a given
// video is stable across its own frames/render workers, while different
// videos (different watermark text / audio file) land on different looks.
const hashSeed = (str) => {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 100000) / 100000;
};

// Deterministic per-index pseudo-random in [0, 1) - a cheap hash-noise
// stand-in for Math.random() that still gives every particle a distinct,
// stable, non-uniform position/speed/phase.
const hash2 = (i, salt) => {
  const x = Math.sin(i * 12.9898 + salt * 78.233) * 43758.5453;
  return x - Math.floor(x);
};

// CF-0572: the palettes are the channel's. Index 0 is built from the theme
// itself ({bg, accent, accent2, accent}); the rest are the theme's optional
// `procedural_palettes` ({bg, a, b, c} each), in order - ExampleFilm's are
// the five this file used to carry (so its videos pick the same palette off
// the same seed), and a channel without the key has palette 0 only. The
// seed picks among however many there are.
const palettesFor = (theme) => [
  {bg: theme.bg, a: theme.accent, b: theme.accent2, c: theme.accent},
  ...(theme.procedural_palettes ?? []),
];

// --- CF-0130: the soft layers, painted on a canvas at 1/DOWNSCALE ---------

// 4 keeps the wash's colour boundaries (the only thing in this layer with an
// edge) visibly identical after the upscale while cutting the pixels 16x.
const DOWNSCALE = 4;

// The CSS these numbers come from, kept here so the canvas and the comment
// above cannot drift apart:
//   wash  - conic-gradient(from Xdeg at 50% 45%) + blur(90px), scale(1.4)
//   blob  - radial-gradient(circle, C_CC 0%, C_66 45%, transparent 72%)
//           + blur(42px), mixBlendMode screen
const WASH_BLUR = 90;
const WASH_SCALE = 1.4;
const WASH_ALPHA = '33';
const WASH_DEG_PER_S = 14;
const BLOB_BLUR = 42;

// Every bake is a pure function of its key, so one cache per page is enough:
// a render worker paints thousands of frames of one palette, and the bakes
// are the whole point - computed on the first frame, blitted on the rest.
const bakes = new Map();
const baked = (key, make) => {
  if (!bakes.has(key)) bakes.set(key, make());
  return bakes.get(key);
};

const surface = (w, h) => {
  const c = document.createElement('canvas');
  c.width = Math.max(1, Math.round(w));
  c.height = Math.max(1, Math.round(h));
  return c;
};

// A blur needs room to spill into or it clips against the bitmap's edge.
const margin = (blur) => Math.ceil(blur * 3);

// `${color}33` is how the CSS version wrote its alphas, and it only means
// anything for a 6-digit hex. A palette carried in from `plan.theme` could
// be any CSS colour, and where CSS would just drop an unparseable gradient,
// `addColorStop` throws - which on the floor of the degradation chain would
// be a hard failure instead of a plainer background. So: hex gets the alpha,
// anything else is used as-is.
const HEX6 = /^#[0-9a-fA-F]{6}$/;
const withAlpha = (color, alpha) => (HEX6.test(color) ? color + alpha : color);

/**
 * The rotating colour wash, blurred once.
 *
 * CSS applies `filter` in the element's own coordinates and `transform`
 * after it, so the visible blur is 90px * 1.4. A conic gradient's colour at
 * a point depends only on the angle from its centre, which is what lets the
 * whole layer be baked flat and *rotated* instead of re-blurred: the bitmap
 * is a square large enough that any rotation still covers the frame.
 */
const bakeWash = (colors, radius, blur) => {
  const m = margin(blur);
  const side = Math.ceil(radius * 2) + m * 2;
  const c = surface(side, side);
  const ctx = c.getContext('2d');
  // CSS 0deg points up and runs clockwise; canvas 0 points right.
  const g = ctx.createConicGradient(-Math.PI / 2, side / 2, side / 2);
  g.addColorStop(0, withAlpha(colors[0], WASH_ALPHA));
  g.addColorStop(1 / 3, withAlpha(colors[1], WASH_ALPHA));
  g.addColorStop(2 / 3, withAlpha(colors[2], WASH_ALPHA));
  g.addColorStop(1, withAlpha(colors[0], WASH_ALPHA));
  ctx.filter = `blur(${blur}px)`;
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, side, side);
  return c;
};

/**
 * One blob, blurred once.
 *
 * The CSS order is: paint the radial gradient, clip it to the border-radius
 * ellipse, then blur the result - so the blur spills outside the ellipse,
 * which is why the clip happens on an inner bitmap and the blur on the
 * outer one. `circle` sizes the gradient to the farthest corner of the box.
 */
const bakeBlob = (w, h, color, blur) => {
  const m = margin(blur);
  const inner = surface(w, h);
  const ictx = inner.getContext('2d');
  ictx.beginPath();
  ictx.ellipse(w / 2, h / 2, w / 2, h / 2, 0, 0, Math.PI * 2);
  ictx.clip();
  const g = ictx.createRadialGradient(w / 2, h / 2, 0, w / 2, h / 2,
                                      Math.hypot(w / 2, h / 2));
  g.addColorStop(0, withAlpha(color, 'CC'));
  g.addColorStop(0.45, withAlpha(color, '66'));
  g.addColorStop(0.72, withAlpha(color, '00'));
  ictx.fillStyle = g;
  ictx.fillRect(0, 0, w, h);

  const out = surface(w + m * 2, h + m * 2);
  const octx = out.getContext('2d');
  octx.filter = `blur(${blur}px)`;
  octx.drawImage(inner, m, m);
  return {bitmap: out, m};
};

/** Repaint the soft layers for time `t`. `w`/`h` are the element's CSS px. */
const paintSoftLayers = (canvas, w, h, palette, colors, blobs, t) => {
  const cw = canvas.width;
  const ch = canvas.height;
  const s = cw / w; // canvas pixels per CSS pixel
  const ctx = canvas.getContext('2d');
  if (!ctx) return;
  ctx.setTransform(1, 0, 0, 1, 0, 0);
  ctx.globalCompositeOperation = 'source-over';
  ctx.filter = 'none';
  ctx.fillStyle = palette.bg;
  ctx.fillRect(0, 0, cw, ch);

  // `at 50% 45%` of a layer scaled 1.4 about its own centre lands at 43% of
  // the frame's height.
  const px = cw / 2;
  const py = ch * 0.43;
  try {
  if (typeof ctx.createConicGradient === 'function') {
    const radius = Math.max(Math.hypot(px, py), Math.hypot(px, ch - py));
    const blur = WASH_BLUR * WASH_SCALE * s;
    const wash = baked(
      `wash|${Math.round(radius)}|${blur.toFixed(2)}|${colors.join(',')}`,
      () => bakeWash(colors, radius, blur),
    );
    ctx.save();
    ctx.translate(px, py);
    ctx.rotate((t * WASH_DEG_PER_S * Math.PI) / 180);
    ctx.drawImage(wash, -wash.width / 2, -wash.height / 2);
    ctx.restore();
  }

  const blobBlur = BLOB_BLUR * s;
  ctx.globalCompositeOperation = 'screen';
  for (const b of blobs) {
    const cx =
      0.5 + Math.cos(t * b.speed + b.phase) * 0.34 + Math.sin(t * b.speed2 * 0.7) * 0.09;
    const cy =
      0.5 + Math.sin(t * b.speed * 1.15 + b.phase) * 0.3 + Math.cos(t * b.speed2) * 0.08;
    const bw = Math.round(b.r * 2 * cw);
    const bh = Math.round(b.r * 2 * ch);
    const {bitmap, m} = baked(
      `blob|${bw}x${bh}|${b.color}|${blobBlur.toFixed(2)}`,
      () => bakeBlob(bw, bh, b.color, blobBlur),
    );
    ctx.drawImage(bitmap, (cx - b.r) * cw - m, (cy - b.r) * ch - m);
  }
  } catch (err) {
    // Same reasoning as `withAlpha`: this component is the floor, and a
    // background that lost its wash is still a background. Whatever was
    // painted before the throw stays; the frame is never dropped.
  }
  ctx.globalCompositeOperation = 'source-over';
};

export const ProceduralBg = ({theme, seed = ''}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const t = frame / fps;

  const palettes = palettesFor(theme);
  const palette = palettes[Math.floor(hashSeed(String(seed)) * palettes.length)];
  const colors = [palette.a, palette.b, palette.c];

  const blobs = Array.from({length: 7}, (_, i) => ({
    seed: i,
    r: 0.3 + (i % 4) * 0.09,
    speed: 0.34 + i * 0.075,
    speed2: 0.26 + i * 0.045,
    phase: (i * Math.PI * 2) / 7,
    color: colors[i % colors.length],
  }));

  const particles = Array.from({length: 26}, (_, i) => {
    const baseX = hash2(i, 1);
    const baseY = hash2(i, 2);
    const size = 3 + hash2(i, 3) * 8;
    const drift = 0.15 + hash2(i, 4) * 0.35;
    const phase = hash2(i, 5) * Math.PI * 2;
    return {i, baseX, baseY, size, drift, phase, color: colors[i % colors.length]};
  });

  // A slow light-sweep band that crosses the frame roughly every 7s, giving
  // a periodic "shine" pass instead of only ambient drift.
  const sweepPeriod = 7;
  const sweepProgress = (t % sweepPeriod) / sweepPeriod;
  const sweepPos = -30 + sweepProgress * 160;

  // CF-0130: repaint before the browser paints, every frame, with no state
  // and no async work - Remotion screenshots the frame after the commit, so
  // a layout effect is early enough and a `delayRender` would only be a way
  // to stall the encode. The element's own box is measured rather than the
  // composition's, because this component is also mounted inside a block
  // zone (AssetLayer) that is smaller than the frame.
  const canvasRef = useRef(null);
  useLayoutEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const w = rect.width || width;
    const h = rect.height || height;
    if (!(w > 0 && h > 0)) return;
    const cw = Math.max(2, Math.round(w / DOWNSCALE));
    const ch = Math.max(2, Math.round(h / DOWNSCALE));
    if (canvas.width !== cw) canvas.width = cw;
    if (canvas.height !== ch) canvas.height = ch;
    paintSoftLayers(canvas, w, h, palette, colors, blobs, t);
  });

  return (
    <AbsoluteFill style={{backgroundColor: palette.bg, overflow: 'hidden'}}>
      {/* The colour wash and the seven drifting blobs, composited small and
          scaled up - see the CF-0130 note at the top of this file. */}
      <canvas
        ref={canvasRef}
        style={{position: 'absolute', inset: 0, width: '100%', height: '100%'}}
      />

      {/* Particle field: small glowing points drifting and twinkling. Pure
          CSS, no images - each is a tiny radial-gradient dot with a glow.
          Kept off the canvas: these are the one layer with detail finer
          than the canvas grid. */}
      {particles.map((p) => {
        const px = (p.baseX + Math.sin(t * p.drift + p.phase) * 0.05) * 100;
        const py = (p.baseY + Math.cos(t * p.drift * 1.3 + p.phase) * 0.05) * 100;
        const twinkle = 0.35 + 0.65 * (0.5 + 0.5 * Math.sin(t * (0.9 + p.drift) + p.phase * 2));
        return (
          <div
            key={p.i}
            style={{
              position: 'absolute',
              left: `${px}%`,
              top: `${py}%`,
              width: p.size,
              height: p.size,
              borderRadius: '50%',
              background: p.color,
              opacity: twinkle,
              boxShadow: `0 0 ${p.size * 3}px ${p.size}px ${p.color}99`,
            }}
          />
        );
      })}

      {/* Periodic diagonal light sweep. */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(115deg, transparent calc(${sweepPos}% - 12%), ${palette.a}2E calc(${sweepPos}%), transparent calc(${sweepPos}% + 12%))`,
        }}
      />

      {/* Readability scrim, held to the lower band where captions live
          instead of washing the whole frame to near-black. */}
      <AbsoluteFill
        style={{
          background: `linear-gradient(180deg, transparent 52%, ${palette.bg}9E 76%, ${palette.bg}E6 100%)`,
        }}
      />
    </AbsoluteFill>
  );
};
