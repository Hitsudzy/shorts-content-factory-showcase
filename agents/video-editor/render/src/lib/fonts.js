import React from 'react';
import {cancelRender, continueRender, delayRender, staticFile} from 'remotion';

/**
 * CF-0164 §5: the source badge's typography, loaded from the repo and never
 * from the network.
 *
 * Courier Prime is the spec's font - a typewriter face drawn for screenplays,
 * which is the whole reference the badge leans on - with IBM Plex Mono named
 * as its reserve. Both are vendored under `render/public/fonts` (OFL, the
 * licences are next to them) for two reasons the render depends on:
 *
 *   offline        a render must not need Google's CDN to be up, and a
 *                  machine with no route to it must produce the same frame;
 *   deterministic  a webfont that arrives late renders one frame in Courier
 *                  and the next in the fallback. `delayRender` below holds
 *                  the frame until the faces are in `document.fonts`, so
 *                  every frame is drawn with the same metrics.
 *
 * The reserve is not decoration either. **Courier Prime has no U+2193 (↓)**
 * - checked in its cmap, the glyph is simply absent - and the label the spec
 * fixes is `SOURCE ↓ DESC`. So the arrow is drawn from IBM Plex Mono (which
 * has it, at the same 0.6 em advance) and is asked for by name in
 * ComparisonLine.jsx rather than left to per-character fallback, which would
 * otherwise depend on what the rendering machine happens to have installed.
 */

/** family, weight, file. Both weights of both families: the label is Regular,
 *  the publication's name and the numeral are Bold, and a synthesised bold
 *  ("faux bold", what a browser does when the weight is missing) is a
 *  different width - which would put the panel's own measured width, decided
 *  in comparison_line.py, out by a few pixels. */
export const BADGE_FACES = [
  {family: 'Courier Prime', weight: '400', file: 'fonts/CourierPrime-Regular.ttf'},
  {family: 'Courier Prime', weight: '700', file: 'fonts/CourierPrime-Bold.ttf'},
  {family: 'IBM Plex Mono', weight: '400', file: 'fonts/IBMPlexMono-Regular.ttf'},
  {family: 'IBM Plex Mono', weight: '700', file: 'fonts/IBMPlexMono-Bold.ttf'},
];

/** CF-0572: the badge's stack is the channel's (`plan.theme.font.badge`;
 *  ExampleFilm's is the spec's order - Courier Prime, then the reserve, then
 *  whatever monospace exists, the last one a floor, not a plan). The faces
 *  above are the ones this render vendors and loads for any channel; a
 *  channel naming another face first is refused by the planner
 *  (comparison_line.badge_font_error), because the panel's width is measured
 *  there for these two. */
/** The one family that carries the arrow. */
export const BADGE_ARROW_STACK = '"IBM Plex Mono", monospace';

let pending = null;

/** Registers both families once per page. Idempotent: every mounted badge
 *  awaits the same promise, so a video with four badges loads four files,
 *  not sixteen. */
export const loadBadgeFonts = () => {
  if (pending) return pending;
  if (typeof FontFace === 'undefined' || typeof document === 'undefined') {
    pending = Promise.resolve();
    return pending;
  }
  pending = Promise.all(
    BADGE_FACES.map(async ({family, weight, file}) => {
      const face = new FontFace(family, `url(${staticFile(file)}) format("truetype")`, {
        weight,
        style: 'normal',
      });
      await face.load();
      document.fonts.add(face);
    }),
  );
  return pending;
};

/** The hook a component uses: the frame is held until the faces are in.
 *  Failure is a cancelled render rather than a frame in the wrong font - a
 *  badge is a claim about a source, and a claim set in Helvetica is a
 *  different badge from the one the user approved. */
export const useBadgeFonts = () => {
  const [handle] = React.useState(() => delayRender('CF-0164 source badge fonts'));
  React.useEffect(() => {
    let live = true;
    loadBadgeFonts()
      .then(() => {
        if (live) continueRender(handle);
      })
      .catch((err) => cancelRender(err));
    return () => {
      live = false;
    };
  }, [handle]);
};
