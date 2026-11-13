/**
 * CF-0572: the on-screen theme is the channel's, and it comes in the plan.
 *
 * `plan.theme` is what build_render_plan.py wrote from the channel's config
 * (`channels/<id>.json` -> `theme`, without `picked`/`note`; the root's
 * docs/channel-data.md «The theme»): every colour and face this composition
 * draws. Nothing here keeps a palette of its own - a plan without a theme
 * (built without --channel, or before CF-0572) is refused with the line
 * below, not drawn in ExampleFilm's colours.
 *
 * What stays in Video.jsx's THEME are sizes (caption size and stroke, the
 * watermark's size) - geometry, the same for every channel.
 */

/** The keys every component reads (`procedural_palettes` is optional). */
export const THEME_KEYS = [
  'bg', 'accent', 'accent2', 'text', 'muted', 'card_ground', 'end_card_ground', 'badge', 'font',
];
export const BADGE_KEYS = ['paper', 'ink', 'ink_muted', 'rule', 'accent', 'accent_ink'];
export const FONT_KEYS = ['display', 'text', 'card', 'badge'];

/**
 * CF-0699: the captions' own colours, optional. `caption_text` the base
 * words, `caption_active` the spoken word, `caption_active_box` a pill drawn
 * behind the spoken word (captionBand.js has its geometry). A channel without
 * them gets what every channel drew before: `text` and `accent`, no pill.
 * Only Captions.jsx reads them - the graphics keep `text`/`accent`.
 */
export const CAPTION_KEYS = ['caption_text', 'caption_active', 'caption_active_box'];

/** {text, active, box} the caption row draws in (`box` null: no pill). */
export const captionColours = (theme) => ({
  text: theme.caption_text ?? theme.text,
  active: theme.caption_active ?? theme.accent,
  box: theme.caption_active_box ?? null,
});

/** The plan's theme, or an Error naming what is missing. */
export const requireTheme = (plan) => {
  const theme = plan?.theme;
  if (!theme || typeof theme !== 'object') {
    throw new Error(
      'plan.theme is missing: the on-screen colours and faces are the channel\'s ' +
        '(channels/<id>.json -> theme), and this plan carries none - rebuild it with ' +
        'build_render_plan.py --channel <id> (CF-0572); there is no default palette');
  }
  const missing = [
    ...THEME_KEYS.filter((k) => theme[k] === undefined || theme[k] === null),
    ...BADGE_KEYS.filter((k) => !theme.badge?.[k]).map((k) => `badge.${k}`),
    ...FONT_KEYS.filter((k) => !theme.font?.[k]).map((k) => `font.${k}`),
  ];
  if (missing.length) {
    throw new Error(
      `plan.theme has no ${missing.join(', ')} - the plan was not built from a ` +
        'checked channel theme (CF-0572); rebuild it with build_render_plan.py --channel <id>');
  }
  return theme;
};

/**
 * `#RRGGBB` as `rgba(r,g,b,alpha)` - the exact string form the components
 * used to write by hand (EndCard's name in white at .72, comma-separated,
 * no spaces), so a channel whose text is white draws the same CSS it always
 * did. `alpha` is passed as
 * written ('.72'), not as a number, for that reason.
 */
export const rgba = (hex, alpha) => {
  const m = /^#([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(hex);
  if (!m) throw new Error(`not a #RRGGBB colour: ${hex} (CF-0572)`);
  const [r, g, b] = m.slice(1).map((h) => parseInt(h, 16));
  return `rgba(${r},${g},${b},${alpha})`;
};
