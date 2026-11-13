import React from 'react';
import {AbsoluteFill, Img, OffthreadVideo, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {rgba} from '../lib/theme';

/**
 * CF-0117 / CF-0141: how the video ends.
 *
 * CF-0141 put a third variant on top of the two below, and it is the one
 * that ships: `clip` - a finished mp4 the channel brings with it, played
 * whole. The two drawn variants stay as the floor for a channel that has no
 * such file. Nothing about the clip is composed here: it is somebody else's
 * finished piece, approved before it reached the factory, and this component
 * puts it on the frame and gets out of the way.
 *
 * CF-0117: the end card - the channel signing the video.
 *
 * A full-frame card after the last word of the narration, the same in every
 * video: the channel's logo (or, without one, its name) and the signature
 * phrase `scripts/end_card.py` read out of the stance document. Its whole
 * value is that it never changes, so there is no per-video variation here at
 * all. Nothing on this card comes from the script.
 *
 * Two variants, and the second is the floor:
 *   `logo`          the logo centred, the phrase beneath it.
 *   `typographic`   the phrase large, the channel name small underneath.
 * The typographic one depends on no file, exactly like the `typographic`
 * style at the bottom of the degradation chain: the last frame of the video
 * is the worst place to discover a missing asset.
 *
 * CF-0186: `card.text` may be null, and that is a state and not a fault. A
 * channel may sign with nothing - example-film is the first that does - and
 * the card is then its logo, or its name set at the size the phrase used to
 * hold. `end_card.py` plans no card at all when there is neither, so this
 * component never has to draw an empty slate.
 *
 * Everything else on the frame stops here. `Video.jsx` hides the watermark
 * and the captions for the card's span and cuts a CF-0116 comparison line
 * off at the card's first frame - the watermark is the channel's mark riding
 * on somebody else's footage, and this card *is* the channel's mark, full
 * frame - two of them on one frame would read as a template, not as a
 * signature. Note that "the card's span" starts where the card is *mounted*,
 * CROSSFADE before `start_s`, not at `start_s` itself: a line clamped to the
 * narration's end would otherwise sit over the whole dissolve.
 *
 * The ground is deliberately a lifted slate rather than the composition's
 * near-black `theme.bg`. Two reasons, and both are load-bearing: a card is a
 * held frame for three seconds, which on black reads as the video having
 * ended early; and `qc_render.py`'s black-run gate fails any stretch over
 * 0.4 s that is 98% near-black, so a card on the near-black ground would be
 * a render this repo's own gate calls a glitch.
 *
 * CF-0572: that lifted ground is the channel's `theme.end_card_ground`
 * (centre -> edge), the text `theme.text` (the name under a phrase at .72 -
 * `rgba(r,g,b,.72)`, the exact CSS ExampleFilm's white was written as), the
 * phrase in `theme.font.text` and the name in `theme.font.display`.
 */
const FADE_IN_SECONDS = 0.3;

/** Staged (`job/…`) or absolute - the same rule AssetLayer.jsx uses. */
const src = (path) => (path.startsWith('/') ? `file://${path}` : staticFile(path));

export const EndCard = ({card, safeArea, theme, volume = 1}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();

  // CF-0141: the channel's own finished clip. Played whole, at full opacity
  // from its first frame - Video.jsx mounts this Sequence at `start_s`
  // exactly and holds the last block up underneath instead of dissolving
  // into it, so there is a hard cut here and no fade of ours over somebody
  // else's opening frames.
  //
  // **No `muted`, and that is deliberate.** Every other OffthreadVideo in
  // this repo (AssetLayer, SplitLayer, SecondaryZone) is muted, because
  // every one of them is stock footage whose own audio would fight the
  // voice-over and the bed. This one is the exception decision 2 of CF-0141
  // made: the clip arrives with a track that was mixed for it, that track is
  // what the viewer is meant to hear, and build_soundtrack.py fades the bed
  // to silence by the time it starts rather than mixing under it. Muting
  // this would deliver an ending that is silent by construction, and the
  // render gate does not measure this interval (decision 3), so nothing
  // downstream would tell you. If you are here because "why is this one not
  // muted" - that is why; end_card.py refuses a clip with no audio stream
  // for the same reason.
  //
  // CF-0695: played at a static `volume` - the gain build_soundtrack.py
  // measured to bring the clip's track to the channel's loudness target
  // (-14 LUFS by default; the three Example endings read about -10.6 LUFS
  // with true peaks near 0 dBTP, so in practice about -3.5 dB). One number
  // for the whole clip, never a curve: the clip keeps its own mix, only its
  // level is matched to the video it closes.
  if (card?.variant === 'clip' && card.path) {
    return (
      <AbsoluteFill>
        <OffthreadVideo
          src={src(card.path)}
          volume={volume}
          style={{width: '100%', height: '100%', objectFit: 'cover'}}
        />
      </AbsoluteFill>
    );
  }

  // CF-0186: the phrase is one of the three things that can be on the card,
  // no longer the one that has to be. A channel that signs with nothing gets
  // its logo, or its own name, and end_card.py plans no card at all when it
  // has neither - so this guard asks "is there anything to draw" rather than
  // "is there a phrase".
  const hasSomething = Boolean(card?.text)
    || Boolean(card?.variant === 'logo' && card?.logo_path)
    || Boolean(card?.channel_name);
  if (!hasSomething) return null;

  const fade = Math.max(1, Math.round(FADE_IN_SECONDS * fps));
  // Fade in only. The card holds to the last frame: a fade-out at the end
  // would spend the closing beat on black and put a black run under the gate.
  const opacity = interpolate(frame, [0, fade], [0, 1], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });
  // The one piece of motion: the phrase settles the last few pixels as it
  // arrives, so the cut into the card is not a hard swap.
  const rise = interpolate(frame, [0, Math.round(fade * 1.6)], [Math.round(height * 0.012), 0], {
    extrapolateLeft: 'clamp',
    extrapolateRight: 'clamp',
  });

  const isLogo = card.variant === 'logo' && card.logo_path;
  const caption = theme.captionSize ?? 78;
  const phraseSize = Math.round(caption * (isLogo ? 0.62 : 0.82));

  return (
    <div
      style={{
        position: 'absolute',
        inset: 0,
        // Lifted slate, brightest under the phrase - see the note above on
        // why this is not theme.bg.
        background:
          `radial-gradient(120% 80% at 50% 46%, ${theme.end_card_ground[0]} 0%, ` +
          `${theme.end_card_ground[1]} 46%, ${theme.end_card_ground[2]} 100%)`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        paddingLeft: safeArea.left,
        paddingRight: safeArea.left,
        paddingTop: safeArea.top,
        paddingBottom: safeArea.bottom,
        opacity,
      }}
    >
      {isLogo ? (
        <Img
          src={src(card.logo_path)}
          style={{
            width: 'auto',
            height: 'auto',
            maxWidth: Math.round(width * 0.56),
            maxHeight: Math.round(height * 0.26),
            objectFit: 'contain',
            marginBottom: Math.round(height * 0.045),
          }}
        />
      ) : null}

      {/* The accent rule: the one mark the channel already uses (the same
          theme.accent as the comparison line's left edge), here as a short
          bar over the phrase. */}
      <div
        style={{
          width: Math.round(width * 0.14),
          height: 6,
          backgroundColor: theme.accent,
          marginBottom: Math.round(height * 0.028),
          opacity: 0.95,
        }}
      />

      {card.text ? (
        <div
          style={{
            transform: `translateY(${rise}px)`,
            maxWidth: safeArea.innerWidth + safeArea.right - safeArea.left,
            fontFamily: theme.font.text,
            fontWeight: 700,
            fontSize: phraseSize,
            lineHeight: 1.2,
            letterSpacing: '-0.012em',
            textAlign: 'center',
            color: theme.text,
            // Sentence case, as the stance wrote it. The captions shout; the
            // card does not - it is the last thing on screen and has three
            // seconds to be read once.
            textShadow: '0 4px 30px rgba(0,0,0,.45)',
          }}
        >
          {card.text}
        </div>
      ) : null}

      {(!isLogo || !card.text) && card.channel_name ? (
        <div
          style={{
            // CF-0186: with no phrase the name is what the card is, so it
            // carries the arrival motion the phrase used to and is set at the
            // size the hierarchy needs - a name whispered under nothing reads
            // as a card that failed to load. With a phrase it is unchanged.
            transform: card.text ? undefined : `translateY(${rise}px)`,
            marginTop: card.text ? Math.round(height * 0.034) : 0,
            fontFamily: theme.font.display,
            // Read on the first render at 0.32x: the name was small enough
            // that the hierarchy under the phrase went soft. It is the
            // channel's own name on the channel's own card - it may be
            // quieter than the phrase, not nearly absent.
            fontSize: Math.round(caption * (card.text ? 0.38 : 0.62)),
            letterSpacing: '0.2em',
            textTransform: 'uppercase',
            color: card.text ? rgba(theme.text, '.72') : theme.text,
          }}
        >
          {card.channel_name}
        </div>
      ) : null}
    </div>
  );
};
