import React from 'react';
import {OffthreadVideo, Img, Sequence, staticFile, useVideoConfig} from 'remotion';

/**
 * Both sides of a comparison in one frame (`asset_kind: split`, CF-0050).
 *
 * This is the `side_by_side` opening of the `contrast` pattern: the axis is
 * stated by the picture before the words finish naming it. It is a composition,
 * not a parameter - one block with two assets, which nothing else in the plan
 * has - which is why it is its own component rather than a flag on AssetLayer.
 *
 * **Stacked, not left and right.** A 9:16 frame split down the middle leaves
 * each side 540x1920 (0.28:1) against source footage that is 2.35:1: a cover
 * crop would keep about 12% of each shot's width and both sides would be
 * unreadable slivers. Split across, each half is 1080x957 (1.13:1) - *wider*
 * than the 9:16 window every other block is framed in, so a subject that
 * survived the full-frame crop survives this one with room to spare. The seam
 * width and the halves' geometry are computed in build_render_plan.py
 * (SPLIT_SEAM_PX / split_half_size) and arrive on the asset; the two have to
 * agree, because `focus` and `zoom` on each half were computed for exactly
 * these dimensions by smart_crop.py, asked about the half's own aspect.
 *
 * CF-0075: a half is a sequence of pictures (`cuts`), not one - distinct
 * clips back to back, then at most a short held frame (the resolver caps it
 * at OPENING_MAX_STATIC_SECONDS). Each cut is mounted for its own span with
 * its own framing, computed by build_render_plan.py for the half's geometry.
 * A half without `cuts` (a plan from before) is one picture for the block.
 *
 * No Ken Burns, no punch, no drift, unlike AssetLayer. Two moving pictures
 * side by side already give the eye more than one shot's worth of movement,
 * and a slow push on each half moving in opposite directions reads as a fault
 * rather than as a gesture. `focus` and `zoom` are still honoured: they are
 * framing, not motion.
 */
const src = (path) => (path.startsWith('/') ? `file://${path}` : staticFile(path));

const Picture = ({cut, box}) => {
  const {fps} = useVideoConfig();
  const focus = cut.focus ?? {x: 0.5, y: 0.5};
  const objectPosition = `${(focus.x * 100).toFixed(1)}% ${(focus.y * 100).toFixed(1)}%`;
  const common = {
    width: '100%',
    height: '100%',
    objectFit: cut.fit === 'contain' ? 'contain' : 'cover',
    objectPosition,
  };
  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        top: 0,
        width: box.width,
        height: box.height,
        overflow: 'hidden',
        backgroundColor: '#000',
        transform: `scale(${cut.zoom ?? 1})`,
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
    </div>
  );
};

const Half = ({half, box}) => {
  const {fps} = useVideoConfig();
  const cuts = half.cuts && half.cuts.length > 0 ? half.cuts : [half];
  return (
    <div
      style={{
        position: 'absolute',
        left: box.x,
        top: box.y,
        width: box.width,
        height: box.height,
        overflow: 'hidden',
        backgroundColor: '#000',
      }}
    >
      {cuts.map((cut, k) => {
        const from = Math.round((cut.from_seconds ?? 0) * fps);
        const frames = cut.seconds != null ? Math.max(1, Math.round(cut.seconds * fps)) : undefined;
        return (
          <Sequence key={k} from={from} durationInFrames={frames} layout="none">
            <Picture cut={cut} box={box} />
          </Sequence>
        );
      })}
    </div>
  );
};

export const SplitLayer = ({block, zone, theme}) => {
  const asset = block.asset;
  const seam = asset.seam_px ?? 6;
  const halfHeight = Math.floor((zone.height - seam) / 2);

  return (
    <div
      style={{
        position: 'absolute',
        left: zone.x,
        top: zone.y,
        width: zone.width,
        height: zone.height,
        overflow: 'hidden',
        // CF-0572: the seam and any uncovered edge show the channel's ground.
        backgroundColor: theme.bg,
      }}
    >
      {(asset.sides ?? []).slice(0, 2).map((half, i) => (
        <Half
          key={half.side ?? i}
          half={half}
          box={{
            x: 0,
            y: i === 0 ? 0 : halfHeight + seam,
            width: zone.width,
            height: halfHeight,
          }}
        />
      ))}
    </div>
  );
};
