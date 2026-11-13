/**
 * Slot geometry.
 *
 * Zones are named - `main`, `secondary`, `caption_band` - because the QC gate
 * and the degradation chain need to talk about them ("the crop severed the
 * subject in `main`"). Free-form layers would make both impossible.
 *
 * Heights are fractions of the frame. A null `secondary` gives its height back
 * to `main`, which is the "nothing to put there, go full-bleed" case.
 */
export const resolveZones = (layout, {width, height}) => {
  const main = layout?.main ?? {};
  const secondary = layout?.secondary ?? null;

  const secondaryH = secondary ? Math.round(height * (secondary.height ?? 0.28)) : 0;
  const mainH = height - secondaryH;

  return {
    main: {x: 0, y: 0, width, height: mainH, fit: main.fit ?? 'cover'},
    secondary: secondary
      ? {x: 0, y: mainH, width, height: secondaryH, kind: secondary.kind ?? 'blur'}
      : null,
  };
};

/**
 * Safe zones are two things added together, and CF-0329 is what it cost to
 * learn that: what the platform *draws on top* (the Shorts header, the
 * right-hand rail, the handle and comment bar) **and what the platform cuts
 * off**. A 9:16 master shown full-height on a 20:9 phone loses 10 % of its
 * width off each side, and until 2026-09-23 the left zone was 0.04 - inside
 * the cut, on every video this factory ever made. The numbers are derived in
 * scripts/safe_area.py; the defaults below mirror it for a plan that arrives
 * without them and must stay in step with it.
 *
 * We still render one master and keep everything meaningful inside the
 * intersection, so the same file survives Shorts, TikTok and Reels without
 * per-platform variants.
 */
export const resolveSafeArea = (safeZones, {width, height}) => {
  const t = safeZones?.top ?? 0.12;
  const b = safeZones?.bottom ?? 0.28;
  const l = safeZones?.left ?? 0.116;
  const r = safeZones?.right ?? 0.212;
  return {
    top: Math.round(height * t),
    bottom: Math.round(height * b),
    left: Math.round(width * l),
    right: Math.round(width * r),
    innerWidth: Math.round(width * (1 - l - r)),
  };
};

/** Which block covers this moment, and how far into it we are. */
export const blockAt = (blocks, seconds) => {
  for (let i = 0; i < blocks.length; i++) {
    const b = blocks[i];
    if (seconds >= b.start && seconds < b.end) {
      return {block: b, index: i, progress: (seconds - b.start) / (b.end - b.start)};
    }
  }
  const last = blocks[blocks.length - 1];
  return {block: last, index: blocks.length - 1, progress: 1};
};
