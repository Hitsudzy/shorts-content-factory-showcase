import React from 'react';
import {AbsoluteFill, Img, Loop, OffthreadVideo, Sequence, interpolate, staticFile, useCurrentFrame, useVideoConfig} from 'remotion';
import {CardLayer} from './CardLayer';
import {GraphicLayer} from './GraphicLayer';
import {ProceduralBg} from './ProceduralBg';
import {SplitLayer} from './SplitLayer';
import {containedPictureBox, insertBox} from '../lib/captionBand';
import {memeMotionTransform} from '../lib/memeMotion';

/**
 * One block's visual.
 *
 * Three things v2 got wrong are fixed here:
 *  - the crop follows the subject (`focus`, from smart_crop.py) instead of the
 *    geometric centre, and ffmpeg's zoompan default of x=0,y=0 - which pulled
 *    every shot into the top-left corner - is gone;
 *  - the Ken Burns direction alternates per block, so a montage stops feeling
 *    like the same move repeated;
 *  - `fit: contain` exists, because a 9:16 full-bleed crop of a landscape
 *    source discards a third of the picture. When smart_crop reports poor
 *    coverage the plan asks for contain and the subject survives.
 */
const src = (path) => (path.startsWith('/') ? `file://${path}` : staticFile(path));

/**
 * CF-0436: presentation instead of a price. `asset.presentation` is written by
 * build_render_plan.py (shot_score.py's model) and is absent on every other
 * picture, which then renders exactly as before.
 *   - `luma_lift: {gain}` - a dark picture multiplied up, CSS brightness();
 *     the plan measured the same arithmetic on its probe (PIL Brightness).
 *   - `blur_fill: {rect, blur_px, bg_scale, bg_dim}` - a wide picture the 9:16
 *     crop would cut, shown whole in `rect` (output px, over the insert box so
 *     it ends above the caption band) on a blurred, enlarged, dimmed copy of
 *     the same frame. No Ken Burns, no punch, no zoom: like any contained
 *     picture, the whole frame is the framing.
 */
const lumaFilter = (holder) => {
  const gain = Number(holder?.presentation?.luma_lift?.gain);
  return gain > 1 ? `brightness(${gain})` : undefined;
};

const Media = ({holder, style}) => {
  const {fps} = useVideoConfig();
  return holder.kind === 'clip' ? (
    <OffthreadVideo
      src={src(holder.src)}
      trimBefore={Math.round((holder.start_seconds ?? 0) * fps)}
      muted
      style={style}
    />
  ) : (
    <Img src={src(holder.src)} style={style} />
  );
};

const BlurFill = ({holder, zone, safeArea}) => {
  const {height} = useVideoConfig();
  const detail = holder.presentation.blur_fill;
  const rect = detail.rect
    ?? containedPictureBox(holder.source_size, insertBox(zone, safeArea, height))
    ?? {x: zone.x, y: zone.y, width: zone.width, height: zone.height};
  const filter = lumaFilter(holder);
  const ground = [filter, `blur(${detail.blur_px ?? 48}px)`,
                  `brightness(${detail.bg_dim ?? 0.55})`].filter(Boolean).join(' ');
  return (
    <div
      style={{
        position: 'absolute',
        left: zone.x,
        top: zone.y,
        width: zone.width,
        height: zone.height,
        overflow: 'hidden',
        backgroundColor: '#000',
      }}
    >
      <AbsoluteFill style={{transform: `scale(${detail.bg_scale ?? 1.15})`}}>
        <Media holder={holder}
               style={{width: '100%', height: '100%', objectFit: 'cover', filter: ground}} />
      </AbsoluteFill>
      <div
        style={{
          position: 'absolute',
          left: rect.x - zone.x,
          top: rect.y - zone.y,
          width: rect.width,
          height: rect.height,
          overflow: 'hidden',
        }}
      >
        <Media holder={holder}
               style={{width: '100%', height: '100%', objectFit: 'contain', filter}} />
      </div>
    </div>
  );
};

/**
 * One picture of a multi-shot swing block (CF-0120), mounted for its own span.
 *
 * No Ken Burns and no punch, for the reason SplitLayer gives: the block already
 * changes picture inside itself, and a push that restarts on every cut reads as
 * a fault rather than as a gesture. `focus`, `zoom` and `fit` are honoured -
 * they are framing, computed for this cut by build_render_plan.py, not motion.
 */
const SequenceCut = ({cut, zone, safeArea}) => {
  const {fps} = useVideoConfig();
  if (cut.presentation?.blur_fill) {
    return <BlurFill holder={cut} zone={zone} safeArea={safeArea} />;
  }
  const focus = cut.focus ?? {x: 0.5, y: 0.45};
  const objectPosition = `${(focus.x * 100).toFixed(1)}% ${(focus.y * 100).toFixed(1)}%`;
  const fit = cut.fit === 'contain' ? 'contain' : 'cover';
  const common = {width: '100%', height: '100%', objectFit: fit, objectPosition,
                  filter: lumaFilter(cut)};
  return (
    <div
      style={{
        position: 'absolute',
        left: zone.x,
        top: zone.y,
        width: zone.width,
        height: zone.height,
        overflow: 'hidden',
        backgroundColor: '#000',
      }}
    >
      <AbsoluteFill
        style={{
          transform: `scale(${fit === 'contain' ? 1 : (cut.zoom ?? 1)})`,
          transformOrigin: objectPosition,
        }}
      >
        {cut.kind === 'clip' ? (
          <OffthreadVideo
            src={src(cut.src)}
            trimBefore={Math.round((cut.start_seconds ?? 0) * fps)}
            muted
            style={common}
          />
        ) : (
          <Img src={src(cut.src)} style={common} />
        )}
      </AbsoluteFill>
    </div>
  );
};

/**
 * CF-0811: 0..1 of the way through a meme span (meme_layer.py build_span())
 * at absolute composition frame `absFrame`, or null for an insert that is
 * not laid over a span.
 */
export const spanProgress = (insert, absFrame, fps) => {
  const span = insert && insert.span;
  if (!span || typeof span.start_s !== 'number' || typeof span.end_s !== 'number'
      || !(span.end_s > span.start_s) || !fps) return null;
  return (absFrame / fps - span.start_s) / (span.end_s - span.start_s);
};

/**
 * A block's insert - a proof capture or a reaction meme - fitted whole on
 * black. Its own component since CF-0244, because it is no longer always the
 * whole of a block: a proof card is mounted for the window the plan gives it
 * and the block's ordinary asset carries the rest.
 */
const InsertLayer = ({insert, zone, safeArea, durationInFrames, absFrom = 0}) => {
  const {height, fps} = useVideoConfig();
  const frame = useCurrentFrame();
  const box = {
    position: 'absolute',
    left: zone.x,
    top: zone.y,
    width: zone.width,
    height: zone.height,
    overflow: 'hidden',
    backgroundColor: '#000',
  };
  // CF-0394: the black ground covers the whole zone, the picture only the
  // part of it that ends above the caption band - the band stays where it
  // always is and the insert makes room for it, not the other way round.
  const fit = insertBox(zone, safeArea, height);
  const picture = {
    position: 'absolute',
    left: fit.x - zone.x,
    top: fit.y - zone.y,
    width: fit.width,
    height: fit.height,
  };
  const contain = {width: '100%', height: '100%', objectFit: 'contain'};
  if (insert.kind === 'meme' && insert.animated && insert.loop_seconds) {
    return <AnimatedMeme insert={insert} box={box} picture={picture} contain={contain}
                         absFrom={absFrom} />;
  }
  const file = insert.kind === 'meme' ? insert.render_src : insert.capture_path;
  // CF-0405: a whole still meme moves inside its box - a push-in or a pan
  // (lib/memeMotion.js, decided by meme_layer.py meme_motion()). Only a meme
  // that carries the whole block gets it (`durationInFrames` is passed only
  // then); a proof card and a GIF stay as they were. The picture box clips
  // while it moves, so the push never reaches the caption band below it.
  // CF-0811: a meme laid over a span of blocks moves once over the whole
  // span - its progress is read off the composition's clock against
  // `insert.span`, so each block of the span draws the same moment of the
  // same move and the seams between them do not show.
  const across = spanProgress(insert, absFrom + frame, fps);
  const progress = across !== null ? across
    : durationInFrames ? frame / durationInFrames : null;
  const transform = insert.kind === 'meme' && !insert.animated && progress !== null
    ? memeMotionTransform(insert.motion, progress, fit)
    : null;
  if (transform) {
    return (
      <div style={box}>
        <div style={{...picture, overflow: 'hidden'}}>
          <Img src={src(file)} style={{...contain, transform, transformOrigin: '50% 50%'}} />
        </div>
      </div>
    );
  }
  return (
    <div style={box}>
      <div style={picture}>
        <Img src={src(file)} style={contain} />
      </div>
    </div>
  );
};

/**
 * CF-0404: a meme with an accepted CF-0403 cutout, laid over the block's own
 * shot - on the face under the words, or in a corner (meme_layer.py
 * cutout_placement()). `cutout.rect` is the drawn figure in output px, clipped
 * to itself; `cutout.image` is the whole transparent PNG around it. No black
 * ground and no motion: the shot underneath is the picture and it moves on
 * its own. meme_layer keeps the rect inside the insert box, so the caption
 * band under it stays ours.
 */
const CutoutLayer = ({cutout}) => {
  const {rect, image} = cutout;
  return (
    <div style={{position: 'absolute', left: rect.x, top: rect.y, width: rect.width,
                 height: rect.height, overflow: 'hidden'}}>
      <Img src={src(cutout.render_src)}
           style={{position: 'absolute', left: image.x - rect.x, top: image.y - rect.y,
                   width: image.width, height: image.height, maxWidth: 'none'}} />
    </div>
  );
};

const isCutout = (insert) => insert && insert.kind === 'meme' && insert.cutout
  && insert.cutout.rect && insert.cutout.image && insert.cutout.render_src
  && (insert.placement === 'cutout_on_subject' || insert.placement === 'cutout_in_corner');

const AnimatedMeme = ({insert, box, picture, contain, absFrom = 0}) => {
  const {fps} = useVideoConfig();
  const loopFrames = Math.max(1, Math.round(insert.loop_seconds * fps));
  const loop = (
    <Loop durationInFrames={loopFrames} layout="none">
      <OffthreadVideo src={src(insert.render_src)} muted style={contain} />
    </Loop>
  );
  // CF-0811: over a span the loop keeps the span's clock, not the block's -
  // otherwise it would restart at every block boundary inside the span.
  // The phase is taken modulo the loop, so a block mounted CROSSFADE ahead of
  // the span's start draws the same frame as the block after it.
  const span = insert.span;
  const lead = span && typeof span.start_s === 'number'
    ? (((absFrom - Math.round(span.start_s * fps)) % loopFrames) + loopFrames) % loopFrames
    : 0;
  return (
    <div style={box}>
      <div style={picture}>
        {lead > 0 ? <Sequence from={-lead} layout="none">{loop}</Sequence> : loop}
      </div>
    </div>
  );
};

/**
 * CF-0244: the window an insert is up for, in the block Sequence's own frames,
 * or `null` for "the whole block" - which is what a meme still gets, and what
 * every plan built before CF-0244 gets, because neither carries a window.
 *
 * `atHead` / `atTail` are not an optimisation. The block's Sequence is mounted
 * CROSSFADE early and released CROSSFADE late (Video.jsx), and a card whose
 * window runs to the block's own edge should ride those dissolves exactly as it
 * did when it was the whole block - otherwise the block's asset would flash for
 * the 10 frames of the lead before the card cut in over it.
 */
const insertSpan = (insert, block, mountFrom, durationInFrames, fps) => {
  if (!insert) return null;
  const {start_s: s, end_s: e} = insert;
  if (typeof s !== 'number' || typeof e !== 'number') return null;
  const atHead = s <= block.start + 1e-6;
  const atTail = e >= block.end - 1e-6;
  if (atHead && atTail) return null;
  const from = atHead ? 0 : Math.max(0, Math.round(s * fps) - (mountFrom ?? 0));
  const until = atTail
    ? durationInFrames
    : Math.max(from + 1, Math.round(e * fps) - (mountFrom ?? 0));
  return {from, frames: Math.max(1, until - from)};
};

export const AssetLayer = ({block, zone, safeArea, theme, punch, durationInFrames, mountFrom,
                            reserveTop = null}) => {
  // Rendered inside a Sequence, so this frame counter is relative to the block,
  // which is also what makes the clip play from its own first frame.
  const frame = useCurrentFrame();
  const {fps} = useVideoConfig();

  const asset = block.asset;

  // CF-0041: a deliberate text card is drawn, not sourced - no file, no crop,
  // no Ken Burns over a picture that is not there. It leaves before any of the
  // framing arithmetic below, which all assumes an image or a clip.
  if (asset.kind === 'card') {
    return <CardLayer block={block} zone={zone} safeArea={safeArea} theme={theme} durationInFrames={durationInFrames} />;
  }

  // CF-0689: a graphic the factory draws from the script's facts - drawn, not
  // sourced, like a card; it carries no insert over itself either (qc_render
  // _NO_INSERT_LAYER_KINDS).
  if (asset.kind === 'own_graphic') {
    // CF-0923: clear of a comparison line on screen with it (Video.jsx).
    return <GraphicLayer block={block} zone={zone} safeArea={safeArea} theme={theme}
                         reserveTop={reserveTop} />;
  }

  // CF-0050: the side_by_side opening is one block with two assets, so none of
  // the single-asset framing below applies to it - each half was framed for the
  // half's own geometry by build_render_plan.py, not for the 9:16 frame.
  if (asset.kind === 'split') {
    return <SplitLayer block={block} zone={zone} theme={theme} />;
  }

  // CF-0811: the insert is asked before a `sequence` and a `procedural`
  // block, not after. Until 2026-10-19 both returned above this branch, so a
  // meme M1 put on an unresolved (procedural) block, a CF-0138 hole fill, and
  // any meme on a CF-0480 stretch-split block - the usual shape of a block at
  // the 3 s floor on a list - were in the plan and never on screen. The block
  // under a windowed insert is drawn by the recursion below with `insert:
  // null`, which reaches the sequence/procedural branches as before.
  // CF-0071: a proof insert is a captured document (a screenshot of a trade
  // announcement, etc.), fitted whole on black - inserts/proof.json's
  // `composition`: fit=contain, background=black, ken_burns=false,
  // punch=false, smart_crop=false. It sits beside `asset` rather than
  // replacing it (build_render_plan.py's build_proof_insert never touches
  // asset_kind - see degradation.never_substitute), so this checks
  // `block.insert` ahead of the framing arithmetic below rather than a new
  // asset.kind branch. A capture is evidence, not a photo with a subject to
  // crop into: no Ken Burns drift, no emphasis punch, no smart_crop zoom -
  // all of it assumes a picture, and this is a page of text held still so it
  // can be read, the same reasoning CF-0047 already applied to a title card.
  // CF-0067: a reaction meme (inserts/meme.json `composition`) - a still or a
  // silent GIF from the factory library, fitted whole on black. It carries no
  // window and so is still the whole block (insertSpan returns null for it -
  // a meme is a reaction to the block, not evidence for a sentence, and there
  // is no second element it has to agree with). Same shape as the proof and
  // for the same reason: the block's
  // own asset is untouched in the plan (build_render_plan.py merges `insert`
  // beside it, meme_layer.apply_to_plan), and this branch leaves ahead of the
  // framing arithmetic so nothing below applies - no Ken Burns, no emphasis
  // punch, no smart_crop focus: a contained frame zoomed is letterboxing
  // zoomed. A GIF arrives as `render_src` = the silent mp4 meme_layer.py cut
  // from it (Remotion's <Img> holds a GIF on its first frame and
  // @remotion/gif is not a dependency here), looped to the block by <Loop>
  // at its own length - never slowed or stretched - and cut at the block's
  // end by the enclosing Sequence. Our captions go quiet over the span the
  // insert is actually up for, in Video.jsx (hiddenCaptionRanges reads
  // `block.insert` and, since CF-0244, its window when it has one).
  // CF-0244: and it is up for the window the plan gives it, not for the block.
  // A proof card used to inherit its length from its block, because `insert`
  // was a field on a block and a block is a span - so on everyday-sorcery-2 the
  // card sat on for 4.80 s after the fact's line had gone, our captions hidden
  // under it (they are hidden because the document carries its own text), and
  // 98.1% of that frame's pixels measured under blackdetect's threshold. The
  // QC gate called it a black screen and was right. The plan now says when the
  // card comes and goes (proof_layer.bind_to_lines: the part of the block the
  // fact's own line covers), and the block's ordinary asset - kept on the
  // block by the storyboard contract for exactly this - carries the rest.
  // CF-0404: a cutout does not replace the block's picture - the block is
  // drawn exactly as it would be without a meme, and the figure over it.
  if (isCutout(block.insert)) {
    return (
      <>
        <AssetLayer
          block={{...block, insert: null}}
          zone={zone}
          safeArea={safeArea}
          theme={theme}
          punch={punch}
          durationInFrames={durationInFrames}
          mountFrom={mountFrom}
        />
        <CutoutLayer cutout={block.insert.cutout} />
      </>
    );
  }
  // A bare marker (no picture behind it - a request answered `no_asset`) on
  // a sequence or a procedural block leaves it to its own branch, as before;
  // qc_render.insert_window() draws the same line (insert_has_picture).
  const drawnOver = block.insert && (
    (asset.kind !== 'sequence' && asset.kind !== 'procedural')
    || Boolean(block.insert.render_src || block.insert.capture_path));
  if (drawnOver) {
    const span = insertSpan(block.insert, block, mountFrom, durationInFrames, fps);
    if (span === null) {
      return <InsertLayer insert={block.insert} zone={zone} safeArea={safeArea}
                          durationInFrames={durationInFrames} absFrom={mountFrom ?? 0} />;
    }
    return (
      <>
        <AssetLayer
          block={{...block, insert: null}}
          zone={zone}
          safeArea={safeArea}
          theme={theme}
          punch={punch}
          durationInFrames={durationInFrames}
          mountFrom={mountFrom}
        />
        <Sequence from={span.from} durationInFrames={span.frames} layout="none">
          <InsertLayer insert={block.insert} zone={zone} safeArea={safeArea}
                       absFrom={(mountFrom ?? 0) + span.from} />
        </Sequence>
      </>
    );
  }

  // CF-0120: one crossing of the axis cut from several distinct shots of that
  // side - pictures one after another, where `split` is two at once. Each cut
  // is mounted for its own span with its own framing; the block boundary is
  // untouched, which is the whole point (a block is still one crossing, and
  // `swap_ratio` is still measured over blocks).
  if (asset.kind === 'sequence') {
    const cuts = asset.cuts && asset.cuts.length > 0 ? asset.cuts : [asset];
    let at = 0;
    return (
      <>
        {cuts.map((cut, k) => {
          const from = at;
          const frames = Math.max(1, Math.round((cut.seconds ?? 0) * fps));
          at += frames;
          return (
            <Sequence
              key={`${cut.src}-${k}`}
              from={from}
              durationInFrames={k === cuts.length - 1 ? undefined : frames}
            >
              <SequenceCut cut={cut} zone={zone} safeArea={safeArea} />
            </Sequence>
          );
        })}
      </>
    );
  }

  // A single block dropped to the typographic rung (CF-0031's per-block
  // degradation) also has no file. Without this it fell through to <Img> with
  // an undefined src and took the whole render down - the path was covered by
  // plan-level tests and had never actually been rendered until CF-0041 needed
  // a degraded plan on screen. `typographic` as a *whole-video* style is still
  // handled in Video.jsx, which paints one background for the composition
  // rather than one per block.
  if (asset.kind === 'procedural') {
    return (
      <div
        style={{
          position: 'absolute',
          left: zone.x,
          top: zone.y,
          width: zone.width,
          height: zone.height,
          overflow: 'hidden',
        }}
      >
        {/* CF-0572: the channel's theme (Video.jsx -> plan.theme), the
            same palettes as the whole-video procedural ground. */}
        <ProceduralBg theme={theme} seed={`${block.index ?? 0}|${asset.kind}`} />
      </div>
    );
  }

  // CF-0436: a wide picture shown whole on its own blurred frame.
  if (asset.presentation?.blur_fill) {
    return <BlurFill holder={asset} zone={zone} safeArea={safeArea} />;
  }

  const local = durationInFrames
    ? frame / durationInFrames
    : (frame / fps - block.start) / Math.max(0.001, block.end - block.start);

  // Alternate the move so consecutive shots don't repeat the same gesture.
  // Footage already moves on its own, so it gets a far gentler push than a
  // still does - a full Ken Burns on top of real motion just crops heads.
  const zoomsIn = (block.index ?? 0) % 2 === 0;
  const span = asset.kind === 'clip' ? 0.03 : 0.12;
  const base = zoomsIn
    ? interpolate(local, [0, 1], [1.0, 1.0 + span])
    : interpolate(local, [0, 1], [1.0 + span, 1.0]);
  const drift = asset.kind === 'clip'
    ? 0
    : interpolate(local, [0, 1], [0, zoomsIn ? -1.2 : 1.2]);

  const focus = asset.focus ?? {x: 0.5, y: 0.45};
  const objectPosition = `${(focus.x * 100).toFixed(1)}% ${(focus.y * 100).toFixed(1)}%`;
  const fit = asset.fit === 'contain' ? 'contain' : 'cover';
  // CF-0033: object-fit:cover always frames the source's full height once it
  // is wider than the target aspect (this pipeline's 2.35:1 footage cropped
  // to 9:16 always is), regardless of how small the actual subject's ROI is.
  // smart_crop.py's build_render_plan.py caller detects when a single
  // subject's own bounding box didn't need that much height and computes
  // `zoom` (>=1) for exactly that case - applied here as an extra factor on
  // top of the Ken Burns scale, anchored at the same focus point cover
  // already centres on, so it tightens toward the subject instead of the
  // frame centre.
  const zoom = asset.zoom ?? 1;

  // CF-0047: a title/end card is fitted whole so its wordmark survives, which
  // means any scale above 1 would immediately start cutting it off again -
  // Ken Burns, the emphasis punch and `zoom` are all suppressed for a
  // contained asset, and so is the vertical drift. A graphic that exists to
  // be read holds still; there is no framing left to spare.
  const contained = fit === 'contain';
  const scale = contained ? 1 : base * punch * zoom;
  const shift = contained ? 0 : drift;

  const common = {
    width: '100%',
    height: '100%',
    objectFit: fit,
    objectPosition,
    filter: lumaFilter(asset),   // CF-0436: luma_lift, undefined otherwise
  };

  return (
    <div
      style={{
        position: 'absolute',
        left: zone.x,
        top: zone.y,
        width: zone.width,
        height: zone.height,
        overflow: 'hidden',
        backgroundColor: '#000',
      }}
    >
      <AbsoluteFill
        style={{
          transform: `scale(${scale}) translateY(${shift}%)`,
          transformOrigin: `${(focus.x * 100).toFixed(1)}% ${(focus.y * 100).toFixed(1)}%`,
        }}
      >
        {asset.kind === 'clip' ? (
          <OffthreadVideo
            src={src(asset.src)}
            trimBefore={Math.round((asset.start_seconds ?? 0) * fps)}
            muted
            style={common}
          />
        ) : (
          <Img src={src(asset.src)} style={common} />
        )}
      </AbsoluteFill>
    </div>
  );
};
