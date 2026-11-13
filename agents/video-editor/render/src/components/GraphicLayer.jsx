import React, {useLayoutEffect, useRef, useState} from 'react';
import {AbsoluteFill, useCurrentFrame, useVideoConfig} from 'remotion';
import {CircuitTraces} from '../graphics/CircuitTraces';
import {SpecCard} from '../graphics/SpecCard';
import {Comparison} from '../graphics/Comparison';
import {PriceDate} from '../graphics/PriceDate';
import {Benchmark} from '../graphics/Benchmark';
import {Timeline} from '../graphics/Timeline';
import {HowItWorks} from '../graphics/HowItWorks';
import {ApiChat} from '../graphics/ApiChat';
import {rgba} from '../lib/theme';
import {fitScale} from '../lib/graphicClear';
import {PANEL_BORDER, PANEL_PAD, SIZE, appear, contentBox, graphicTime, innerHeight, innerWidth, str, wrap} from '../graphics/kit';

/**
 * CF-0689: a graphic the factory draws itself from the script's facts
 * (`asset.kind: "own_graphic"`) - ExampleTech's base footage.
 *
 * Not a card and not the procedural rung: it is the video's footage, built by
 * build_render_plan.py from the script's `graphics[]` order after
 * shared/own_graphic.py passed it. What is drawn:
 *
 *   - the ground: the channel's bg and card_ground, and CircuitTraces - the
 *     brand's circuit-board motif with pulses that keep moving for the whole
 *     block (qc_render.py fails a graphic that stands still);
 *   - the template's content (graphics/*.jsx) on a panel of its own ground -
 *     the traces run in the free frame around it, never through a word -
 *     centred in the safe area between the brand label and the caption band
 *     (graphics/kit.js contentBox), across its full width, animated in;
 *   - the source line (`asset.caption`, «According to X») at its foot.
 *
 * CF-0923: `reserveTop` (Video.jsx, lib/graphicClear.js reserveTopFor) is the
 * line under a comparison line that is on screen with this block - the box
 * starts below it, and the panel is scaled down about its centre when it is
 * taller than the box, so neither the title nor any row can reach back up
 * under the source badge or the fact strip. The scale reads the panel's
 * layout height (offsetHeight ignores transforms, so it is stable from frame
 * to frame) and is 1 for every panel that fits.
 *
 * Every string on the frame is a string of `asset.data` or the caption - the
 * templates add no words, units or dates of their own. CF-0690's `api_chat`
 * (graphics/ApiChat.jsx) is the seventh: a model's verbatim answer on the
 * record of the call, in our own neutral chat, with no caption. Colours only from
 * `theme` (plan.theme). No file, no font file, no image.
 */
export const TEMPLATES = {
  spec_card: SpecCard,
  comparison: Comparison,
  price_date: PriceDate,
  benchmark: Benchmark,
  timeline: Timeline,
  how_it_works: HowItWorks,
  // CF-0690: a model's real answer through its API, in our own chat
  api_chat: ApiChat,
};

export const GraphicLayer = ({block, zone, safeArea, theme, reserveTop = null}) => {
  const frame = useCurrentFrame();
  const {fps, width, height} = useVideoConfig();
  const asset = block.asset || {};
  const t = graphicTime(frame, fps, asset);
  const box = contentBox(zone, safeArea, width, height, reserveTop);
  const panelRef = useRef(null);
  const [scale, setScale] = useState(1);
  useLayoutEffect(() => {
    const el = panelRef.current;
    if (!el) return;
    const s = fitScale(el.offsetHeight, box.height);
    if (Math.abs(s - scale) > 0.001) setScale(s);
  });
  const Template = TEMPLATES[asset.template];
  const caption = str(asset.caption);
  return (
    <div
      data-graphic={asset.graphic_id}
      style={{
        position: 'absolute', left: zone.x, top: zone.y, width: zone.width, height: zone.height,
        overflow: 'hidden', backgroundColor: theme.bg,
      }}
    >
      <AbsoluteFill
        style={{
          background:
            `radial-gradient(circle at 50% 38%, ${theme.card_ground[0]} 0%, ` +
            `${theme.card_ground[1]} 55%, ${theme.card_ground[2]} 100%)`,
        }}
      />
      <CircuitTraces theme={theme} seed={asset.graphic_id ?? block.index ?? 0} t={t}
                     width={zone.width} height={zone.height} />
      <div
        style={{
          position: 'absolute', left: box.x - zone.x, top: box.y - zone.y,
          width: box.width, height: box.height, boxSizing: 'border-box',
          display: 'flex', flexDirection: 'column', justifyContent: 'center',
        }}
      >
        {/* The panel: the content's own ground, so no trace or pad crosses a
            word; its feathered edge masks the traces right around it. */}
        <div
          data-panel="1"
          ref={panelRef}
          style={{
            width: '100%', boxSizing: 'border-box', flexShrink: 0,
            transform: scale < 1 ? `scale(${scale})` : undefined, transformOrigin: '50% 50%', padding: PANEL_PAD, borderRadius: 30,
            background: rgba(theme.bg, 0.94),
            border: `${PANEL_BORDER}px solid ${rgba(theme.accent2, 0.5)}`,
            boxShadow: `0 0 36px 22px ${rgba(theme.bg, 0.82)}`,
            display: 'flex', flexDirection: 'column', gap: 30,
          }}
        >
          {Template ? <Template data={asset.data || {}} asset={asset} theme={theme} t={t}
                                width={innerWidth(box)}
                                height={innerHeight(box) - (caption ? 80 : 0)} /> : null}
          {caption ? (
            <div data-caption="1" style={{color: theme.muted, fontFamily: theme.font.text,
                                          fontSize: SIZE.caption, fontStyle: 'italic',
                                          textAlign: 'center',
                                          opacity: appear(t, 1.2, 0.5), ...wrap}}>{caption}</div>
          ) : null}
        </div>
      </div>
    </div>
  );
};
