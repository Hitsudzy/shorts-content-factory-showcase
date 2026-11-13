// Один `<video>` плеера (CC-0061/0063): время, пуск/пауза, перемотка и шаг по кадру. Длина
// ролика — из метаданных mp4 (`loadedmetadata`/`durationchange`): только она даёт «кадр N из M».
// До них — длительность из списка роликов, помеченная «≈» (файл может быть другой длины), или
// никакой. Метаданные, пришедшие раньше, чем React повесил обработчик, читаются при монтировании.
// Сравнение версий (./Compare) держит два таких и водит их одними кнопками.
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type SyntheticEvent,
} from 'react';

import { stepTime } from './format';

const finite = (d: number) => (Number.isFinite(d) && d > 0 ? d : null);

export type Clip = ReturnType<typeof useClip>;

export function useClip({ fps, hint }: { fps: number; hint?: number | null }) {
  const ref = useRef<HTMLVideoElement>(null);
  const [time, setTime] = useState(0);
  const [meta, setMeta] = useState<number | null>(null);
  const [playing, setPlaying] = useState(false);
  const [touched, setTouched] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const el = ref.current;
    if (el && el.readyState >= 1) setMeta(finite(el.duration));
  }, []);

  const approx = meta == null && hint != null && hint > 0 ? hint : null;
  /** Длина для полосы перемотки и счёта: метаданные или подсказка списка (≈). */
  const duration = meta ?? approx ?? 0;

  const end = useCallback(() => {
    const el = ref.current;
    return (el && finite(el.duration)) ?? duration;
  }, [duration]);

  const seek = useCallback(
    (t: number) => {
      const el = ref.current;
      if (!el) return;
      const e = end();
      el.currentTime = Math.min(Math.max(0, t), e || t);
      setTime(el.currentTime);
      setTouched(true);
    },
    [end],
  );

  /** Подтянуться к времени `t`, если ушли дальше `tol` (сравнение: правая идёт за левой). */
  const follow = useCallback((t: number, tol: number) => {
    const el = ref.current;
    if (!el || el.ended) return;
    const e = finite(el.duration);
    if (e != null && t > e) return;
    if (Math.abs(el.currentTime - t) > tol) el.currentTime = t;
  }, []);

  const pause = useCallback(() => ref.current?.pause(), []);
  const play = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    setTouched(true);
    void el.play().catch(() => setPlaying(false));
  }, []);
  const toggle = useCallback(() => {
    const el = ref.current;
    if (!el) return;
    if (el.paused) play();
    else el.pause();
  }, [play]);
  const step = useCallback(
    (delta: number) => {
      const el = ref.current;
      if (!el) return;
      el.pause();
      seek(stepTime(el.currentTime, delta, fps, end()));
    },
    [fps, seek, end],
  );

  const onMeta = (e: SyntheticEvent<HTMLVideoElement>) => {
    const d = finite(e.currentTarget.duration);
    if (d) setMeta(d);
  };
  const videoProps = {
    ref,
    preload: 'metadata' as const,
    playsInline: true,
    onLoadedMetadata: onMeta,
    onDurationChange: onMeta,
    onTimeUpdate: (e: SyntheticEvent<HTMLVideoElement>) => setTime(e.currentTarget.currentTime),
    onSeeked: (e: SyntheticEvent<HTMLVideoElement>) => setTime(e.currentTarget.currentTime),
    onPlay: () => {
      setPlaying(true);
      setTouched(true);
    },
    onPause: () => setPlaying(false),
    onEnded: () => setPlaying(false),
    onError: () => setFailed(true),
  };

  return {
    ref,
    time,
    meta,
    approx,
    duration,
    playing,
    touched,
    failed,
    seek,
    step,
    play,
    pause,
    toggle,
    follow,
    videoProps,
  };
}

/** Что умеют кнопки и клавиши: у одного ролика — его `<video>`, у сравнения — оба сразу. */
export type Transport = {
  time: number;
  duration: number;
  playing: boolean;
  fps: number;
  toggle: () => void;
  seek: (t: number) => void;
  step: (delta: number) => void;
};

export function onTransportKey(t: Transport, e: KeyboardEvent<HTMLElement>) {
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  const act: Record<string, () => void> = {
    ' ': t.toggle,
    ArrowLeft: () => t.seek(t.time - 1),
    ArrowRight: () => t.seek(t.time + 1),
    ',': () => t.step(-1),
    '.': () => t.step(1),
  };
  const fn = act[e.key];
  if (!fn) return;
  e.preventDefault();
  fn();
}

// Пробел на кнопке браузер «нажимает» на отпускании — пуск уже сделан на нажатии.
export const onTransportKeyUp = (e: KeyboardEvent<HTMLElement>) => {
  if (e.key === ' ') e.preventDefault();
};
