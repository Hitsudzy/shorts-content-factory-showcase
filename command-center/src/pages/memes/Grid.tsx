// Сетка мемов банка (CC-0025): картинка карточки (`thumb` фабрики; у GIF — сама гифка, она
// стоит на первом кадре и играет при наведении или фокусе), имя, состояние и пара меток.
// Нажатие открывает мем в просмотре.
import { useEffect, useRef, useState } from 'react';

import type { MemeEntry } from '@/api/memes';
import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';

import { cutOf, stateOf, type Mark } from './draft';
import { memeName, STATE } from './format';

/** Шахматка под прозрачной вырезкой. */
export const checker =
  'bg-[repeating-conic-gradient(color-mix(in_srgb,var(--muted-foreground)_25%,transparent)_0_25%,transparent_0_50%)] bg-[length:16px_16px]';

/**
 * GIF на первом кадре: картинка рисуется на холст, пока не наведут (или не сфокусируют
 * карточку) — тогда играет сама гифка. Холст не нарисовался (браузер не смог) — гифка играет.
 */
function GifThumb({ src, playing }: { src: string; playing: boolean }) {
  const img = useRef<HTMLImageElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [still, setStill] = useState(false);
  const draw = () => {
    const i = img.current;
    const c = canvas.current;
    if (!i || !c || !i.naturalWidth) return;
    try {
      c.width = i.naturalWidth;
      c.height = i.naturalHeight;
      const ctx = c.getContext('2d');
      if (!ctx) return;
      ctx.drawImage(i, 0, 0);
      setStill(true);
    } catch {
      setStill(false);
    }
  };
  useEffect(() => {
    if (img.current?.complete) draw();
  }, []);
  const frozen = still && !playing;
  return (
    <>
      <img
        ref={img}
        src={src}
        alt=""
        loading="lazy"
        onLoad={draw}
        className={cn('max-h-full max-w-full object-contain', frozen && 'invisible absolute')}
      />
      <canvas
        ref={canvas}
        aria-hidden
        className={cn('max-h-full max-w-full object-contain', !frozen && 'hidden')}
      />
    </>
  );
}

export function MemeThumb({
  entry,
  playing = false,
  className,
}: {
  entry: MemeEntry;
  playing?: boolean;
  className?: string;
}) {
  return (
    <div
      className={cn(
        'relative grid aspect-[4/3] place-items-center overflow-hidden rounded-sm bg-muted',
        className,
      )}
    >
      {entry.gif ? (
        <GifThumb src={entry.urls.thumb} playing={playing} />
      ) : (
        <img
          src={entry.urls.thumb}
          alt=""
          loading="lazy"
          className="max-h-full max-w-full object-contain"
        />
      )}
    </div>
  );
}

export function MemeCard({
  entry,
  mark,
  changed,
  selected,
  onOpen,
}: {
  entry: MemeEntry;
  mark: Mark | undefined;
  changed: boolean;
  selected: boolean;
  onOpen: () => void;
}) {
  const [hover, setHover] = useState(false);
  const state = stateOf(entry, mark);
  const s = STATE[state];
  const tags = entry.tags ?? [];
  return (
    <li className="min-w-0" data-testid="meme" data-id={entry.id} data-state={state}>
      <button
        type="button"
        onClick={onOpen}
        onPointerEnter={() => setHover(true)}
        onPointerLeave={() => setHover(false)}
        onFocus={() => setHover(true)}
        onBlur={() => setHover(false)}
        aria-current={selected ? 'true' : undefined}
        aria-label={`${memeName(entry.id)} — ${s.label.toLowerCase()}${entry.gif ? ', гифка' : ''}`}
        className={cn(
          'grid w-full scroll-mb-28 gap-1.5 rounded-sm p-1 text-left outline-offset-2',
          selected && 'bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] ring-1 ring-primary',
        )}
      >
        <span className="relative block">
          <MemeThumb
            entry={entry}
            playing={hover}
            className={cn(state === 'drop' && 'opacity-45')}
          />
          <span className="absolute top-1.5 left-1.5 flex flex-wrap gap-1">
            <StatusBadge tone={s.tone} className="bg-card/90 backdrop-blur-sm">
              {s.label}
            </StatusBadge>
            {entry.gif ? (
              <span className="rounded-full border bg-card/90 px-1.5 py-0.5 font-mono text-[10px]">
                GIF
              </span>
            ) : null}
          </span>
          {changed ? (
            <span
              data-testid="meme-unsaved"
              className="absolute top-1.5 right-1.5 rounded-full bg-primary px-1.5 py-0.5 text-[10px] font-semibold text-primary-foreground"
            >
              не сохранено
            </span>
          ) : null}
          {cutOf(entry, mark) ? (
            <span className="absolute right-1.5 bottom-1.5 rounded-full border bg-card/90 px-1.5 py-0.5 text-[10px]">
              можно вырезать
            </span>
          ) : null}
        </span>
        <span className="text-[13px] leading-[1.3] font-medium [overflow-wrap:anywhere]">
          {memeName(entry.id)}
        </span>
        {tags.length ? (
          <span className="truncate text-[11px] text-muted-foreground">
            {tags.slice(0, 3).join(' · ')}
            {tags.length > 3 ? ` · ещё ${tags.length - 3}` : ''}
          </span>
        ) : null}
      </button>
    </li>
  );
}
