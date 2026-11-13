import React from 'react';
import {Composition} from 'remotion';
import {Video} from './Video';

/**
 * The composition is driven entirely by a render plan passed as inputProps;
 * this placeholder only gives `remotion studio` something to open before any
 * plan has been rendered. It deliberately references no files - importing a
 * generated plan here would break a fresh checkout.
 */
const PLACEHOLDER = {
  style: 'typographic',
  output: {width: 1080, height: 1920, fps: 30},
  safe_zones: {top: 0.12, bottom: 0.28, left: 0.116, right: 0.212},
  layout: {main: {fit: 'cover'}, secondary: null},
  watermark: {text: 'PLACEHOLDER', position: 'top-left'},
  audio: {src: null, duration: 5},
  words: [
    {word: 'Pass', start: 0, end: 0.6},
    {word: 'a', start: 0.6, end: 0.9},
    {word: 'plan', start: 0.9, end: 1.6},
    {word: 'to', start: 1.6, end: 1.9},
    {word: 'render.', start: 1.9, end: 2.8},
  ],
  blocks: [{start: 0, end: 5, intent: 'placeholder', asset: {kind: 'procedural'}}],
  punches: [],
};

export const RemotionRoot = () => (
  <Composition
    id="Video"
    component={Video}
    durationInFrames={150}
    fps={30}
    width={1080}
    height={1920}
    defaultProps={{plan: PLACEHOLDER}}
    calculateMetadata={({props}) => ({
      // CF-0117: the composition is the narration *plus* the end card, and
      // `duration.composition` is where end_card.apply_to_plan() writes that
      // sum. `audio.duration` alone is the voice-over, and a composition cut
      // to it would end on the last word - the card would be planned, drawn
      // and never reach the file. A plan without a card (built before
      // CF-0117, or without a --channel to read the phrase from) has no such
      // field and is still the length of its voice.
      durationInFrames: Math.round(
        (props.plan.duration?.composition ?? props.plan.audio.duration) *
          props.plan.output.fps),
      fps: props.plan.output.fps,
      width: props.plan.output.width,
      height: props.plan.output.height,
    })}
  />
);
