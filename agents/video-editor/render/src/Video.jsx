import React from 'react';
import {AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {AssetLayer} from './components/AssetLayer';
import {SecondaryZone} from './components/SecondaryZone';
import {ProceduralBg} from './components/ProceduralBg';
import {Captions} from './components/Captions';
import {ComparisonLine} from './components/ComparisonLine';
import {reserveTopFor} from './lib/graphicClear';
import {EndCard} from './components/EndCard';
import {FootageCredit} from './components/FootageCredit';
import {Watermark} from './components/Watermark';
import {resolveZones, resolveSafeArea} from './lib/layout';
import {requireTheme} from './lib/theme';

/**
 * Sizes only (CF-0572): every colour and face is the channel's and comes in
 * `plan.theme` (lib/theme.js) - a plan without one is refused, not drawn in
 * some other channel's palette.
 */
const THEME = {
  captionSize: 78,
  captionStroke: 9,
  watermarkSize: 30,
};

const CROSSFADE = 0.35;

/** Emphasis words get a short scale bump - the only "motion" a still can offer. */
const punchAt = (punches, t) => {
  let p = 1;
  for (const at of punches ?? []) {
    const d = t - at;
    if (d >= -0.06 && d <= 0.34) {
      p = Math.max(p, 1 + 0.055 * Math.sin(((d + 0.06) / 0.4) * Math.PI));
    }
  }
  return p;
};

/** Blocks crossfade rather than butt-joining: concat had no way to do this.
 *
 * `hardCutAt` (CF-0141) is the second the video cuts to the channel's ending
 * clip, or null when it does not. The block that ends there keeps its
 * opacity instead of fading out: there is nothing of ours to dissolve into,
 * and the fade would be a dissolve to the composition's near-black
 * background - which is exactly the 0.17 s of measured black CF-0117 found
 * on its first render and papered over by mounting the card early. The card
 * could be mounted early because the card was ours to start whenever we
 * liked; a finished clip cannot, because the 0.35 s lead would spend
 * somebody else's opening frames under our dissolve. So the fix moves to the
 * other side of the seam: the outgoing block holds, the clip cuts in over it
 * at full opacity, and the block's Sequence runs on underneath (it is
 * mounted CROSSFADE past its own end) so no rounding of the mount frame can
 * open a one-frame hole between them.
 */
/**
 * CF-0811: a block whose meme continues the span the block before it began
 * (meme_layer.py build_span() lays one meme over consecutive blocks, the same
 * `insert.span` on each) does not dissolve in: the picture under the seam is
 * the same picture at the same moment of its motion, and a dissolve of a
 * picture into itself is a dip in brightness the viewer reads as a flicker.
 */
export const continuesMemeSpan = (block) => {
  const ins = block && block.insert;
  const span = ins && ins.span;
  if (!span || typeof span.start_s !== 'number') return false;
  const from = typeof ins.start_s === 'number' ? ins.start_s : block.start;
  return span.start_s < block.start - 1e-6 && from <= block.start + 1e-6;
};

const blockOpacity = (block, t, hardCutAt = null) => {
  const inFade = continuesMemeSpan(block) ? 1 : interpolate(
    t, [block.start - CROSSFADE, block.start], [0, 1], {
      extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
    });
  if (hardCutAt !== null && block.end >= hardCutAt - 1e-6) return inFade;
  const outFade = interpolate(t, [block.end - CROSSFADE, block.end], [1, 0], {
    extrapolateLeft: 'clamp', extrapolateRight: 'clamp',
  });
  return Math.min(inFade, outFade);
};

export const Video = ({plan}) => {
  const frame = useCurrentFrame();
  const {fps, width, height, durationInFrames} = useVideoConfig();
  const t = frame / fps;

  const theme = {...THEME, ...requireTheme(plan)};
  const zones = resolveZones(plan.layout, {width, height});
  const safeArea = resolveSafeArea(plan.safe_zones, {width, height});
  const punch = punchAt(plan.punches, t);

  // CF-0117: the end card - the channel's logo and signature phrase, held for
  // the seconds CF-0087 budgets, after the last word of the narration. It is
  // the only thing in the composition that outlives the voice-over (Root.jsx
  // sizes the composition from plan.duration.composition), and it owns the
  // frame while it is up: the watermark and the captions are hidden under it
  // below, and the comparison lines are already clipped to the narration's
  // own duration. Declared before the caption ranges, which read it.
  // The card is mounted CROSSFADE early and holds its full seconds after
  // that, so its 0.3 s fade-in happens *over* the last block's own fade-out
  // instead of after it. Found on the first render: with the card starting
  // exactly at start_s, the block faded to the composition's background and
  // the card faded up out of it - 0.17 s of measured full black between the
  // last frame of the video and the channel's signature, a blink the eye
  // reads as the file having ended. Same trick, and the same constant, as
  // the blocks use to crossfade into each other.
  //
  // CF-0141: and the lead is 0 when the ending is the channel's own clip.
  // The CROSSFADE lead below exists to hide a dissolve to background; a clip
  // needs no dissolve (blockOpacity() holds the outgoing block instead), and
  // giving it one would fade up over its first 10 frames and run its
  // Sequence 0.35 s longer than the file, leaving the tail on a frozen last
  // frame. Two numbers, one decision: `cardLead` is both the mount offset
  // and the extra length, so they cannot come apart.
  const card = plan.end_card ?? null;
  const isClipEnding = card?.variant === 'clip';
  const cardLead = isClipEnding ? 0 : CROSSFADE;
  const hardCutAt = isClipEnding ? card.start_s : null;
  const cardFrom = card ? Math.max(0, Math.round((card.start_s - cardLead) * fps)) : 0;
  const cardFrames = card
    ? Math.max(1, Math.round((card.seconds + cardLead) * fps))
    : 0;
  const onCard = card ? frame >= cardFrom : false;

  // CF-0071: our word-by-word captions are hidden for the span of any
  // block carrying an insert (composition.our_captions="hidden" in
  // inserts/proof.json) - a screenshot already carries its own text, and
  // stacking ours on top double-captions the frame the same way burned-in
  // subtitles used to before detect_text_band.py existed. Driven by the
  // presence of `block.insert`, not by `insert.kind === "proof"`
  // specifically, so CF-0067's meme layer gets the same suppression
  // CF-0379: and it is the *kind* of insert that decides, which is why this
  // reads `insert.captions` rather than the presence of an insert. (CF-0390:
  // since 2026-09-24 a proof card leaves them on as well - inserts/proof.json
  // says `shown` and the band gives way to the card's text; a plan written
  // before that still says `hidden` and is still obeyed.) A meme does not: it is a
  // reaction to the block, not evidence for the sentence, so it carries
  // neither the line being spoken nor any obligation to replace it, and for
  // the length of the insert the viewer was losing our words altogether
  // (found by the user, 2026-09-24). `inserts/meme.json` says
  // `composition.our_captions: "shown"` and this code obeys the field - a
  // plan whose insert still says "hidden" is still hidden, as it should be.
  //
  // CF-0244: for the span the insert is actually up for, which is the block
  // only when the insert has no window of its own. A proof card now carries
  // one (`insert.start_s`/`end_s`, the part of the block the fact's line
  // covers), and the captions have to come back with the block's own picture
  // when the card goes - the reason they are hidden is that the document on
  // screen carries its own text, and once it is gone that reason is gone too.
  const hiddenCaptionRanges = (plan.blocks ?? [])
    .filter((block) => block.insert && block.insert.captions !== 'shown')
    .map((block) => ({
      start: block.insert.start_s ?? block.start,
      end: block.insert.end_s ?? block.end,
    }));

  // CF-0117: and the card's own span, from the frame it starts dissolving in
  // on. The last word ends before it, so this suppresses nothing in practice -
  // it is the guarantee that a caption can never be caught over the
  // signature, whatever the alignment says.
  // CF-0394: and nothing about where the band sits. CF-0379/CF-0390 raised it
  // clear of a meme or a proof card for the insert's span; the band is now
  // fixed at the top of the bottom dead zone for the whole video and the
  // insert is fitted above it instead (lib/captionBand.js insertBox, read by
  // AssetLayer.jsx).
  const cardRanges = card
    ? [...hiddenCaptionRanges,
       {start: cardFrom / fps, end: card.start_s + card.seconds}]
    : hiddenCaptionRanges;

  // CF-0127: how long the second plane's underlay runs - to the frame the
  // end card is mounted on, or to the end of the composition when there is
  // no card. Zero (a card mounted at frame 0, which nothing plans) means no
  // band at all rather than a one-frame flash of one.
  const underlayFrames = card ? cardFrom : durationInFrames;

  const isTypographic = plan.style === 'typographic';

  // One block on its own timeline (see the Sequence note inside).
  const renderBlock = (block, index) => {
    const opacity = blockOpacity(block, t, hardCutAt);
    if (opacity <= 0.001) return null;

    // Each block gets its own timeline. Mounted as a plain layer for the
    // whole composition, a clip's internal playback starts at frame 0 of
    // the video, so by the time the block is visible the clip has long
    // ended and sits on its last frame - five of six shots rendered as
    // stills. Sequence restarts local time at the block's own start.
    const from = Math.max(0, Math.round((block.start - CROSSFADE) * fps));
    const durationInFrames = Math.max(
      1, Math.round((block.end - block.start + CROSSFADE * 2) * fps));

    return (
      <Sequence key={index} from={from} durationInFrames={durationInFrames} layout="none">
        <AbsoluteFill style={{opacity}}>
          <AssetLayer
            block={{...block, index}}
            theme={theme}
            zone={zones.main}
            safeArea={safeArea}
            punch={punch}
            durationInFrames={durationInFrames}
            mountFrom={from}
            reserveTop={block.asset?.kind === 'own_graphic'
              ? reserveTopFor(block, plan.comparison_lines, safeArea, width, CROSSFADE)
              : null}
          />
        </AbsoluteFill>
      </Sequence>
    );
  };

  return (
    <AbsoluteFill style={{backgroundColor: theme.bg}}>
      {isTypographic ? (
        <>
          <ProceduralBg
            theme={theme}
            seed={`${plan.watermark?.text ?? ''}|${plan.audio?.src ?? ''}`}
          />
          {/* CF-0689: a graphic the factory drew is the video's footage, not
              a picture the typographic drop flattens - its blocks are drawn
              over the procedural ground (build_render_plan.py keeps them
              `own_graphic` under a whole-video typographic style). */}
          {plan.blocks.map((block, index) =>
            block.asset?.kind === 'own_graphic' ? renderBlock(block, index) : null)}
        </>
      ) : (
        <>
          {plan.blocks.map((block, index) => renderBlock(block, index))}
        </>
      )}

      {/* CF-0127: the second plane - the brainrot underlay. `zones.secondary`
          is the band `layout.secondary` asks for, and it is null on every
          plan whose underlay layer did not apply (which is every plan built
          before CF-0127, and every video on a channel with the switch off):
          then `main` keeps the whole height and this renders nothing at all.
          Mounted outside the style branch above, so a `typographic` video
          gets the same second plane over its procedural background, and
          under the captions (CF-0394: with no scrim now - their stroke is
          what keeps them readable over a moving loop). Everything else in the composition is above it: captions,
          comparison lines, block inserts (memes, proofs), the watermark and
          the end card.

          The Sequence is the end-card decision (CF-0117): the band runs for
          the narration and stops at the frame the card is *mounted* on, not
          at `card.start_s`. The card owns the frame it is on - the
          watermark and the captions are already hidden under it - and a
          loop still moving under the channel's signature reads as the file
          not having ended. `plan["duration"]["actual"]` is what
          underlay_layer sized the loop against, and this is that span. */}
      {zones.secondary && underlayFrames > 0 ? (
        <Sequence from={0} durationInFrames={underlayFrames} layout="none">
          <SecondaryZone zone={zones.secondary} source={plan.secondary_source} />
        </Sequence>
      ) : null}

      {/* CF-0394: no readability scrim under the captions any more - the
          user's call of 2026-09-25 (variant D). It darkened the lower third
          of every frame; the stroke (Captions.jsx) carries the contrast on
          its own, and qc_render's caption_contrast still records it. */}

      {/* CF-0116 / CF-0186: our wording of the video's production fact,
          and the badge naming its source, for the window of the beat that
          speaks it. A layer of its own, above the picture and below the
          captions - the captions keep running underneath it, which is the
          point: the narration is one device and the annotation is another.
          Mounted per line as its own Sequence so the fade is local to the
          window; `hiddenCaptionRanges` above is untouched by it (a line is
          our text over our footage, not a document that carries its own).
          CF-0117: a line ends at the card's first frame at the latest. Its
          own window is clamped to `duration.actual` - the voice-over's
          length, which is exactly `card.start_s` - so the last beat's line
          runs to the narration's end and the card is now mounted CROSSFADE
          *before* that: without this clip an annotation sits over the
          signature for the whole dissolve. A line with nothing left before
          the card is not mounted at all. */}
      {(plan.comparison_lines ?? []).map((line, i) => {
        const from = Math.max(0, Math.round(line.start_s * fps));
        const until = card ? Math.min(Math.round(line.end_s * fps), cardFrom) : Math.round(line.end_s * fps);
        if (until <= from) return null;
        const durationInFrames = Math.max(1, until - from);
        return (
          <Sequence
            key={line.fact_id ?? i}
            from={from}
            durationInFrames={durationInFrames}
            layout="none"
          >
            <ComparisonLine
              line={line}
              safeArea={safeArea}
              theme={theme}
              durationInFrames={durationInFrames}
            />
          </Sequence>
        );
      })}

      {/* CF-0664: the footage owner's credit over its shots, where the
          origin's terms want it on the picture. Clipped to the card's mount
          frame the way the comparison lines are: the card owns its frame. */}
      {(plan.credit_overlays ?? []).map((credit, i) => {
        const from = Math.max(0, Math.round(credit.start_s * fps));
        const until = card ? Math.min(Math.round(credit.end_s * fps), cardFrom) : Math.round(credit.end_s * fps);
        if (until <= from) return null;
        return (
          <Sequence key={`credit-${i}`} from={from} durationInFrames={until - from} layout="none">
            <FootageCredit credit={credit} watermark={plan.watermark} safeArea={safeArea} theme={theme} />
          </Sequence>
        );
      })}

      <Captions
        words={plan.words}
        safeArea={safeArea}
        theme={isTypographic ? {...theme, captionSize: theme.captionSize * 1.25} : theme}
        hiddenRanges={cardRanges}
      />
      {/* The watermark is the channel's mark riding on the footage; the end
          card is the channel's mark, full frame. Two of them on one frame
          would read as a template rather than as a signature, so the
          watermark stops where the card starts. */}
      {onCard ? null : (
        <Watermark watermark={plan.watermark} safeArea={safeArea} theme={theme} />
      )}

      {card ? (
        <Sequence from={cardFrom} durationInFrames={cardFrames} layout="none">
          {/* CF-0695: the clip's own track, levelled to the same loudness
              target as our mix by one static volume build_soundtrack.py
              measured and recorded (audio.loudness.ending.volume). Absent
              (an older plan, a clip whose audio could not be measured) = 1. */}
          <EndCard card={card} safeArea={safeArea} theme={theme}
            volume={plan.audio?.loudness?.ending?.volume ?? 1} />
        </Sequence>
      ) : null}

      {plan.audio?.src ? (
        <Audio src={plan.audio.src.startsWith('/') ? `file://${plan.audio.src}` : staticFile(plan.audio.src)} />
      ) : null}
    </AbsoluteFill>
  );
};
