// Обложка ролика 9:16 (`.thumb` макета «Кинозал»): кадр монтажа как есть, первая плитка листа
// судьи — вырезом через CSS (`grid` листа: размер фона = колонки × строки, позиция 0 0), без
// превью — градиент с названием. Таймкод — справа внизу, метка (Reel / пересборка) — слева вверху.
import type { ReactNode } from 'react';

import type { Poster } from '@/api/videos';
import { cn } from '@/lib/utils';

/** Первая плитка листа: фон в `columns × rows` раз больше рамки, прижат к левому верхнему углу. */
function sheetStyle(p: Extract<Poster, { kind: 'sheet' }>) {
  return {
    backgroundImage: `url("${p.url}")`,
    backgroundSize: `${p.columns * 100}% ${p.rows * 100}%`,
    backgroundPosition: '0 0',
    backgroundRepeat: 'no-repeat',
  } as const;
}

/** Картинка обложки во всю рамку (рамку задаёт родитель). */
export function PosterImage({ poster, className }: { poster: Poster; className?: string }) {
  if (poster.kind === 'frame')
    return (
      <img
        src={poster.url}
        alt=""
        data-testid="poster-frame"
        loading="lazy"
        className={cn('absolute inset-0 size-full object-cover', className)}
      />
    );
  if (poster.kind === 'sheet')
    return (
      <div
        aria-hidden
        data-testid="poster-sheet"
        className={cn('absolute inset-0', className)}
        style={sheetStyle(poster)}
      />
    );
  return null;
}

export function Cover({
  poster,
  caption,
  tag,
  time,
  className,
}: {
  poster: Poster;
  caption: string;
  tag?: ReactNode;
  time?: string;
  className?: string;
}) {
  return (
    <div
      data-slot="cover"
      data-poster={poster.kind}
      className={cn(
        'relative aspect-[9/16] w-full overflow-hidden rounded-sm bg-[linear-gradient(160deg,#654126,#280e14_55%,#08080c)]',
        className,
      )}
    >
      <PosterImage poster={poster} />
      {poster.kind === 'none' ? (
        <span className="absolute inset-x-2 top-[38%] text-center font-display text-[15px] leading-[1.1] text-white uppercase [text-shadow:0_1px_8px_#000a] [overflow-wrap:anywhere]">
          {caption}
        </span>
      ) : null}
      {tag ? (
        <span className="absolute top-1.5 left-1.5 rounded-[3px] bg-[#000a] px-1.5 py-px text-[10.5px] text-white">
          {tag}
        </span>
      ) : null}
      {time ? (
        <span className="absolute right-1.5 bottom-1.5 rounded-[3px] bg-[#000a] px-1.5 py-px font-mono text-[11px] text-white">
          {time}
        </span>
      ) : null}
    </div>
  );
}
