import React from 'react';
import {rgba} from '../lib/theme';

/**
 * CF-0689: the ground of every own graphic - ExampleTech's circuit-board
 * motif (the brand's banner and ending: traces with pads, cyan pulses
 * travelling along them), drawn from `theme` only.
 *
 * It never stops: pulses run along every trace and a soft sheen sweeps
 * across the frame for the whole block, so a graphic is never a still -
 * qc_render.py probes the top band of an own-graphic block for a still run
 * exactly as it does a clip. No text, no image, no blur filter (the
 * software rasteriser's expensive path, CF-0130); every position is a pure
 * function of `t` and of `seed`.
 */

/** A small deterministic generator: the same seed, the same board. */
const rng = (seed) => {
  let h = 2166136261;
  for (const ch of String(seed)) {
    h ^= ch.charCodeAt(0);
    h = Math.imul(h, 16777619);
  }
  return () => {
    h ^= h << 13; h ^= h >>> 17; h ^= h << 5;
    return ((h >>> 0) % 100000) / 100000;
  };
};

/** Orthogonal traces from the edges inward, each a polyline with a pad at its
 *  inner end. Coordinates in px of a width x height board. */
export const traces = (seed, width, height, count = 14) => {
  const r = rng(seed);
  const out = [];
  for (let i = 0; i < count; i += 1) {
    const fromLeft = i % 2 === 0;
    const y0 = Math.round(height * (0.04 + 0.92 * ((i + r() * 0.8) / count)));
    const x0 = fromLeft ? -20 : width + 20;
    const run1 = width * (0.12 + r() * 0.22);
    const x1 = fromLeft ? x0 + run1 : x0 - run1;
    const dy = height * (r() - 0.5) * 0.12;
    const x2 = fromLeft ? x1 + Math.abs(dy) : x1 - Math.abs(dy);
    const y2 = y0 + dy;
    const run2 = width * (0.06 + r() * 0.14);
    const x3 = fromLeft ? x2 + run2 : x2 - run2;
    const pts = [[x0, y0], [x1, y0], [x2, y2], [x3, y2]];
    let length = 0;
    for (let k = 1; k < pts.length; k += 1) {
      length += Math.hypot(pts[k][0] - pts[k - 1][0], pts[k][1] - pts[k - 1][1]);
    }
    out.push({pts, length, speed: 0.45 + r() * 0.35, phase: r()});
  }
  return out;
};

export const CircuitTraces = ({theme, seed, t, width, height}) => {
  const board = traces(seed, width, height);
  // The sheen: two soft vertical bands of the accent crossing the frame left
  // to right, half a sweep apart - so one is always on the frame, in every
  // horizontal band of it (measured on a real render: one band alone left
  // ~0.9 s of every sweep to the pulses only, at the probe's floor).
  const SWEEP = 2.6;
  const band = width * 0.42;
  const sheens = [0, 0.5].map((k) => -band + (((t / SWEEP) + k) % 1) * (width + band * 2));
  const gid = `og-sheen-${String(seed).replace(/[^a-z0-9]/gi, '')}`;
  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`}
         style={{position: 'absolute', left: 0, top: 0}}>
      <defs>
        <linearGradient id={gid} x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor={theme.accent} stopOpacity="0" />
          <stop offset="0.5" stopColor={theme.accent} stopOpacity="0.16" />
          <stop offset="1" stopColor={theme.accent} stopOpacity="0" />
        </linearGradient>
      </defs>
      {board.map((tr, i) => {
        const d = tr.pts.map(([x, y], k) => `${k ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`).join(' ');
        const [px, py] = tr.pts[tr.pts.length - 1];
        // Two pulses a trace, running inward and starting over.
        const head = ((t * tr.speed + tr.phase) % 1) * (tr.length + 160);
        const head2 = ((t * tr.speed + tr.phase + 0.5) % 1) * (tr.length + 160);
        const glow = 0.45 + 0.35 * Math.sin(t * 2.4 + i);
        return (
          <g key={i}>
            <path d={d} fill="none" stroke={rgba(theme.accent2, 0.42)} strokeWidth={5}
                  strokeLinejoin="round" />
            {[head, head2].map((h, k) => (
              <path key={k} d={d} fill="none" stroke={theme.accent} strokeWidth={7}
                    strokeLinecap="round" strokeLinejoin="round"
                    strokeDasharray={`140 ${tr.length + 400}`}
                    strokeDashoffset={(140 - h).toFixed(1)} opacity={0.85} />
            ))}
            <circle cx={px} cy={py} r={13} fill={theme.bg}
                    stroke={rgba(theme.accent2, 0.9)} strokeWidth={5} />
            <circle cx={px} cy={py} r={6} fill={theme.accent} opacity={glow} />
          </g>
        );
      })}
      {sheens.map((sx, k) => (
        <rect key={k} x={sx.toFixed(1)} y={0} width={band} height={height} fill={`url(#${gid})`} />
      ))}
    </svg>
  );
};
