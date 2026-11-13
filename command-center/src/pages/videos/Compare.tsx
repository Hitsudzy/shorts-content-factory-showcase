// Сравнение двух версий ролика рядом (CC-0063): исходная и пересборки (`rebuilt_in` →
// `rebuilds[]`), любые две. Одни кнопки на оба `<video>`: пуск и пауза вместе, перемотка и шаг
// по кадру ставят оба на одно время (короткая версия упирается в свой конец). Ведёт левая:
// во время показа правая подтягивается к её времени, если ушла дальше 0,2 с. У каждой —
// подпись, длина, счёт кадров и приёмка. На телефоне — переключатель «какую смотреть», вторая
// версия не исчезает, а прячется и идёт в ногу, так переключение ничего не сбивает.
import { useEffect, useId, useState, type ReactNode } from 'react';

import { fpsOf, posterOf, type Video } from '@/api/videos';
import { Card, CardHead } from '@/components/common/Card';
import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';
import { inputBase } from '@/pages/channels/styles';

import { onTransportKey, onTransportKeyUp, useClip, type Clip, type Transport } from './clip';
import { acceptanceView, stepTime, timecode } from './format';
import { Controls, FrameCount, KeysHint, Screen } from './Player';

export type Version = { batch: string; label: string; sub: string; video: Video };

const DRIFT_S = 0.2;

function Pane({
  side,
  version,
  clip,
  fps,
  hidden,
  onClick,
}: {
  side: 'a' | 'b';
  version: Version;
  clip: Clip;
  fps: number;
  hidden: boolean;
  onClick: () => void;
}) {
  const view = acceptanceView(version.video.acceptance);
  return (
    <figure
      data-testid="compare-pane"
      data-side={side}
      data-batch={version.batch}
      className={cn('m-0 grid min-w-0 content-start gap-2', hidden && 'max-sm:hidden')}
    >
      <figcaption className="grid gap-1">
        <span className="flex flex-wrap items-baseline justify-between gap-x-2">
          <b className="text-[13px] font-semibold" data-testid="compare-label">
            {version.label}
          </b>
          <span className="text-xs text-muted-foreground">{version.sub}</span>
        </span>
        <span className="flex flex-wrap items-center gap-1" data-testid="compare-state">
          <StatusBadge tone={view.tone} className="rounded-sm whitespace-normal">
            {view.label}
          </StatusBadge>
          <span className="text-xs text-muted-foreground">
            {timecode(clip.meta ?? version.video.duration)}
          </span>
        </span>
      </figcaption>
      <Screen
        clip={clip}
        src={version.video.mp4.url}
        poster={posterOf(version.video.preview)}
        testId="compare-video"
        onClick={onClick}
      />
      <span className="text-xs text-muted-foreground">
        <FrameCount clip={clip} fps={fps} testId="compare-frame" />
      </span>
    </figure>
  );
}

function Pair({ a, b }: { a: Version; b: Version }) {
  const fpsA = fpsOf(null, a.video);
  const fpsB = fpsOf(null, b.video);
  const ca = useClip({ fps: fpsA, hint: a.video.duration });
  const cb = useClip({ fps: fpsB, hint: b.video.duration });
  const [shown, setShown] = useState<'a' | 'b'>('a');

  // Правая идёт в ногу с левой: во время показа подтягивается, если ушла.
  const { time: ta, playing: pa } = ca;
  const follow = cb.follow;
  useEffect(() => {
    if (pa) follow(ta, DRIFT_S);
  }, [ta, pa, follow]);

  const playing = ca.playing || cb.playing;
  const seek = (t: number) => {
    ca.seek(t);
    cb.seek(t);
  };
  const t: Transport = {
    time: ca.time,
    duration: Math.max(ca.duration, cb.duration),
    playing,
    fps: fpsA,
    toggle: () => {
      if (playing) {
        ca.pause();
        cb.pause();
        return;
      }
      const at = ca.ref.current?.currentTime ?? 0;
      cb.seek(at);
      ca.play();
      cb.play();
    },
    seek,
    step: (delta) => {
      ca.pause();
      cb.pause();
      const now = ca.ref.current?.currentTime ?? 0;
      seek(stepTime(now, delta, fpsA, t.duration));
    },
  };

  return (
    <div
      data-testid="compare-player"
      role="group"
      aria-label={`Сравнение: ${a.label} и ${b.label}`}
      tabIndex={0}
      onKeyDown={(e) => onTransportKey(t, e)}
      onKeyUp={onTransportKeyUp}
      className="grid min-w-0 gap-3 rounded-sm outline-offset-4"
    >
      <div
        role="group"
        aria-label="Какую версию смотреть"
        className="flex gap-1.5 sm:hidden"
        data-testid="compare-toggle"
      >
        {(['a', 'b'] as const).map((side) => (
          <button
            key={side}
            type="button"
            aria-pressed={shown === side}
            data-testid="compare-show"
            data-side={side}
            onClick={() => setShown(side)}
            className={cn(
              'flex-1 rounded-full border px-2.5 py-1 text-xs',
              shown === side
                ? 'border-primary bg-primary font-semibold text-primary-foreground'
                : 'text-muted-foreground',
            )}
          >
            {(side === 'a' ? a : b).label}
          </button>
        ))}
      </div>
      <div className="grid max-w-[720px] grid-cols-1 gap-3 sm:grid-cols-2">
        <Pane side="a" version={a} clip={ca} fps={fpsA} hidden={shown !== 'a'} onClick={t.toggle} />
        <Pane side="b" version={b} clip={cb} fps={fpsB} hidden={shown !== 'b'} onClick={t.toggle} />
      </div>
      <div className="grid max-w-[720px] gap-2">
        <Controls t={t} testPrefix="compare" />
        <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
          <span>Кнопки и клавиши ведут обе версии сразу.</span>
          <KeysHint />
        </div>
      </div>
    </div>
  );
}

function Side({
  label,
  value,
  versions,
  onPick,
  testId,
}: {
  label: string;
  value: number;
  versions: Version[];
  onPick: (i: number) => void;
  testId: string;
}) {
  const id = useId();
  return (
    <label htmlFor={id} className="grid min-w-0 gap-1 text-[13px]">
      <span className="text-muted-foreground">{label}</span>
      <select
        id={id}
        data-testid={testId}
        value={value}
        onChange={(e) => onPick(Number(e.target.value))}
        className={inputBase}
      >
        {versions.map((v, i) => (
          <option key={v.batch} value={i}>
            {v.label} · {v.sub}
          </option>
        ))}
      </select>
    </label>
  );
}

/** Две версии рядом: по умолчанию исходная и открытая (или последняя) пересборка. */
export function Compare({
  versions,
  opened,
  close,
}: {
  versions: Version[];
  opened: number;
  /** Ссылка «закрыть сравнение» — в шапке карточки. */
  close: ReactNode;
}) {
  const [left, setLeft] = useState(0);
  const [right, setRight] = useState(opened > 0 ? opened : versions.length - 1);
  const a = versions[left] ?? versions[0]!;
  const b = versions[right] ?? versions[versions.length - 1]!;
  return (
    <Card aria-labelledby="compare-title" data-testid="compare" className="max-sm:p-3">
      <CardHead
        eyebrow="Сравнение версий"
        title="Две версии рядом"
        titleId="compare-title"
        actions={close}
      />
      <div className="mb-3 grid max-w-[720px] grid-cols-1 gap-2 sm:grid-cols-2">
        <Side
          label="Слева"
          value={left}
          versions={versions}
          onPick={setLeft}
          testId="compare-left"
        />
        <Side
          label="Справа"
          value={right}
          versions={versions}
          onPick={setRight}
          testId="compare-right"
        />
      </div>
      {left === right ? (
        <p className="m-0 mb-3 text-[13px] text-warning" data-testid="compare-same">
          Выбрана одна и та же версия с обеих сторон.
        </p>
      ) : null}
      <Pair key={`${a.batch}|${b.batch}`} a={a} b={b} />
    </Card>
  );
}
