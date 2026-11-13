// Плеер ролика: `<video src={mp4.url}>` — перемотку браузер делает сам по HTTP Range (API
// отдаёт 206). Свои кнопки и полоса перемотки, шаг ±1 кадр (1/fps), клавиши: пробел — пуск и
// пауза, ← → — секунда, `,` `.` — кадр. Обложка: кадр монтажа — `poster` как есть, лист судьи —
// его первая плитка поверх видео, пока ролик не запускали и не перематывали. Другой ролик —
// другой плеер (родитель ставит `key`), состояние с нуля. Счёт кадров — по метаданным файла
// (./clip): до них — «≈» из длительности списка. Кнопки и клавиши — общие с сравнением версий.
import { useEffect, type ReactNode } from 'react';

import type { Poster } from '@/api/videos';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { onTransportKey, onTransportKeyUp, useClip, type Clip, type Transport } from './clip';
import { PosterImage } from './Cover';
import { frameLabel, timecodeFine } from './format';

const KEYS_TIP = 'Пробел — пуск и пауза · ← → — на секунду · , и . — на кадр назад и вперёд';

/** Полоса перемотки, «Смотреть/Пауза», шаг кадра и время. */
export function Controls({ t, testPrefix = 'player' }: { t: Transport; testPrefix?: string }) {
  return (
    <>
      <input
        type="range"
        aria-label="Перемотка"
        data-testid={`${testPrefix}-seek`}
        min={0}
        max={t.duration || 0}
        step={1 / t.fps}
        value={Math.min(t.time, t.duration || 0)}
        onChange={(e) => t.seek(Number(e.target.value))}
        className="w-full accent-[var(--primary)]"
      />
      <div className="flex flex-wrap items-center gap-1.5">
        <Button
          size="sm"
          variant={t.playing ? 'outline' : 'default'}
          data-testid={`${testPrefix}-play`}
          aria-label={t.playing ? 'Пауза' : 'Смотреть'}
          onClick={t.toggle}
        >
          {t.playing ? 'Пауза' : 'Смотреть'}
        </Button>
        <Tip content="Кадр назад (клавиша ,)">
          <Button
            size="sm"
            variant="ghost"
            data-testid={`${testPrefix}-prev`}
            aria-label="Кадр назад"
            onClick={() => t.step(-1)}
          >
            ‹ кадр
          </Button>
        </Tip>
        <Tip content="Кадр вперёд (клавиша .)">
          <Button
            size="sm"
            variant="ghost"
            data-testid={`${testPrefix}-next`}
            aria-label="Кадр вперёд"
            onClick={() => t.step(1)}
          >
            кадр ›
          </Button>
        </Tip>
        <span
          className="ml-auto font-mono text-xs text-muted-foreground"
          data-testid={`${testPrefix}-time`}
        >
          {timecodeFine(t.time)} / {timecodeFine(t.duration)}
        </span>
      </div>
    </>
  );
}

export function KeysHint() {
  return (
    <Tip content={KEYS_TIP} wide>
      <span
        tabIndex={0}
        data-testid="player-keys"
        className={cn('underline decoration-dotted underline-offset-4')}
      >
        клавиши
      </span>
    </Tip>
  );
}

/** «кадр 32 из 90 · 30 к/с»; `data-meta` — длина уже из файла (тесты ждут его, а не гадают). */
export function FrameCount({ clip, fps, testId }: { clip: Clip; fps: number; testId: string }) {
  return (
    <span data-testid={testId} data-fps={fps} data-meta={clip.meta != null ? '1' : '0'}>
      {frameLabel(clip.time, fps, clip.meta, clip.approx)} · {fps} к/с
    </span>
  );
}

/** Окно 9:16 с видео, обложкой-листом и строкой «не открывается». */
export function Screen({
  clip,
  src,
  poster,
  testId,
  onClick,
  children,
}: {
  clip: Clip;
  src: string;
  poster: Poster;
  testId: string;
  onClick: () => void;
  children?: ReactNode;
}) {
  return (
    <div className="relative aspect-[9/16] w-full overflow-hidden rounded-sm bg-black">
      <video
        {...clip.videoProps}
        src={src}
        poster={poster.kind === 'frame' ? poster.url : undefined}
        data-testid={testId}
        className="absolute inset-0 size-full object-contain"
        onClick={onClick}
      />
      {poster.kind === 'sheet' && !clip.touched ? (
        <PosterImage poster={poster} className="pointer-events-none" />
      ) : null}
      {clip.failed ? (
        <p
          role="alert"
          className="absolute inset-x-2 bottom-2 m-0 rounded-sm bg-[#000c] p-2 text-[13px] text-white"
        >
          Видео не открывается в этом браузере. Попробуйте ещё раз или откройте файл из «подробнее».
        </p>
      ) : null}
      {children}
    </div>
  );
}

export function Player({
  src,
  poster,
  fps,
  duration: hint,
  title,
  seekTo,
}: {
  src: string;
  poster: Poster;
  fps: number;
  duration?: number | null;
  title: string;
  /** CC-0125: встать на время (находка оценки «к моменту ▶»); `n` — номер просьбы, повтор тоже. */
  seekTo?: { t: number; n: number } | null;
}) {
  const clip = useClip({ fps, hint });
  const { seek, pause } = clip;
  useEffect(() => {
    if (!seekTo) return;
    pause();
    seek(seekTo.t);
  }, [seekTo, seek, pause]);
  const t: Transport = {
    time: clip.time,
    duration: clip.duration,
    playing: clip.playing,
    fps,
    toggle: clip.toggle,
    seek: clip.seek,
    step: clip.step,
  };
  return (
    <div
      data-testid="player"
      data-tour="player"
      role="group"
      aria-label={`Плеер: ${title}`}
      tabIndex={0}
      onKeyDown={(e) => onTransportKey(t, e)}
      onKeyUp={onTransportKeyUp}
      className="grid min-w-0 gap-2 rounded-sm outline-offset-4"
    >
      <Screen clip={clip} src={src} poster={poster} testId="player-video" onClick={clip.toggle} />
      <Controls t={t} />
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <FrameCount clip={clip} fps={fps} testId="player-frame" />
        <KeysHint />
      </div>
    </div>
  );
}
