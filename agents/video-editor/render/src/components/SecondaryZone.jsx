import React from 'react';
import {Img, OffthreadVideo, staticFile} from 'remotion';

/**
 * The second plane - the lower band of the frame.
 *
 * v2 filled this with a frozen, blurred duplicate of the picture above it and
 * a static wordmark - a third of a vertical frame doing nothing. It is now
 * opt-in and, when used, carries something live: an underlay loop, a
 * reaction, or a second asset. Left null, `main` takes the whole height.
 *
 * CF-0127: what fills it today is the brainrot underlay - a muted loop the
 * factory picks per video out of `shared/inserts/loops/` (CF-0014's rotation,
 * `shared/inserts/underlay.py`). `scripts/underlay_layer.py` writes it as
 * `plan.secondary_source`:
 *
 *   {layer: "underlay", id, kind: "clip" | "still", src, muted: true,
 *    loop: true | false, fit: "loop_or_trim" | "still", loops_needed,
 *    object_fit: "cover", span: "narration"}
 *
 * `kind` decides the element - a clip plays, an image stands for the whole
 * span. Two things about it are not the channel's to change and are held
 * here rather than read off the prop: it is **always muted** (the main
 * content in the first plane has the only audio track in the video - the
 * 2026-09-05 decision), and the picture is **cover**, so a loop of any
 * aspect fills the band instead of letterboxing inside it. `loop` says
 * whether the clip repeats; a clip longer than the span is simply cut off
 * by the Sequence Video.jsx mounts this in, which is the `loop_or_trim`
 * treatment - Remotion does the repeating, `loops_needed` only records how
 * many repeats it comes to.
 */
const src = (path) => (path.startsWith('/') ? `file://${path}` : staticFile(path));

export const SecondaryZone = ({zone, source}) => {
  if (!zone) return null;

  const box = {
    position: 'absolute',
    left: zone.x,
    top: zone.y,
    width: zone.width,
    height: zone.height,
    overflow: 'hidden',
    backgroundColor: '#000',
  };
  const media = {width: '100%', height: '100%', objectFit: source?.object_fit ?? 'cover'};

  // A band with no source is a black band, not a crash: `applied: false`
  // never gets here (Video.jsx leaves `zone` null), so this is the case of a
  // plan that asked for the band by hand.
  if (!source || !source.src) return <div style={box} />;

  return (
    <div style={box}>
      {source.kind === 'clip' ? (
        <OffthreadVideo src={src(source.src)} muted loop={source.loop !== false} style={media} />
      ) : (
        <Img src={src(source.src)} style={media} />
      )}
    </div>
  );
};
