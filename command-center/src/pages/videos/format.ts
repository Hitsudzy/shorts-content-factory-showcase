// Слова экрана «Ролики»: таймкоды, кадры, что журнал приёмки знает о ролике.
import type { VideoAcceptance } from '@/api/videos';
import type { Tone } from '@/components/common/Status';

/** 44.9 → «0:44»; null — «—». */
export function timecode(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '—';
  const s = Math.floor(seconds);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

/** Время с долей секунды для плеера: 12.0333 → «0:12.03». */
export function timecodeFine(seconds: number): string {
  const s = Math.max(0, seconds);
  const whole = Math.floor(s);
  const cs = Math.floor((s - whole) * 100);
  return `${timecode(whole)}.${String(cs).padStart(2, '0')}`;
}

/** Номер кадра (с 1) на времени `t` при `fps`. */
export const frameAt = (t: number, fps: number) => Math.floor(t * fps + 1e-6) + 1;

/**
 * «кадр 32 из 90» — когда длина пришла из метаданных файла; «кадр 32 из ≈1236» — пока есть
 * только длительность из списка роликов (файл может оказаться другой длины); «кадр 32» — без неё.
 */
export function frameLabel(t: number, fps: number, meta: number | null, approx: number | null) {
  const n = `кадр ${frameAt(t, fps)}`;
  if (meta) return `${n} из ${Math.ceil(meta * fps - 1e-6)}`;
  if (approx) return `${n} из ≈${Math.ceil(approx * fps - 1e-6)}`;
  return n;
}

/**
 * Время ровно на кадре: от `t` на `delta` кадров, в пределах [0, duration]. Середина кадра,
 * а не его край, — так браузер не показывает соседний кадр из-за округления.
 */
export function stepTime(t: number, delta: number, fps: number, duration: number): number {
  const n = Math.max(0, Math.floor(t * fps + 1e-6) + delta);
  const last = duration > 0 ? Math.max(0, Math.ceil(duration * fps) - 1) : Infinity;
  return (Math.min(n, last) + 0.5) / fps;
}

export type AcceptanceView = {
  label: string;
  tone: Tone;
  tip: string;
  /** Есть вердикт (в журнале или в очереди). */
  decided: boolean;
  pending: boolean;
};

/** Что журнал приёмки знает о ролике — словами человека (null — журнал не читается). */
export function acceptanceView(a: VideoAcceptance | null | undefined): AcceptanceView {
  if (!a || a.state_error) {
    return {
      label: 'журнал не читается',
      tone: 'danger',
      tip: 'Журнал приёмки не читается — вердикт не показать. Подробности — ниже.',
      decided: false,
      pending: false,
    };
  }
  const redo = a.verdict === 'rejected' && /передел/i.test(a.note ?? '');
  const base =
    a.verdict === 'accepted'
      ? a.held
        ? {
            label: 'принят · холд',
            tone: 'warn' as const,
            tip: 'Принят, но держится холдом: не уйдёт, пока холд не снимут',
          }
        : { label: 'принят', tone: 'ok' as const, tip: 'Вы приняли ролик' }
      : a.verdict === 'rejected'
        ? redo
          ? { label: 'на переделку', tone: 'warn' as const, tip: 'Вы вернули ролик на переделку' }
          : { label: 'отклонён', tone: 'danger' as const, tip: 'Вы сняли ролик' }
        : {
            label: 'ждёт решения',
            tone: 'live' as const,
            tip: 'Вердикта ещё нет: ролик ждёт вашего решения',
          };
  if (a.pending && a.verdict) {
    return {
      label: `${base.label} · ждёт конца батча`,
      tone: 'warn',
      tip: 'Вердикт записан и ждёт в очереди, пока идёт батч: фабрика закоммитит его, когда батч закончится',
      decided: true,
      pending: true,
    };
  }
  return { ...base, decided: !!a.verdict, pending: false };
}

/**
 * Ролик без вердикта, чью пересборку вы приняли (CC-0088): решения он не ждёт — плашка вместо
 * «ждёт решения».
 */
export const REPLACED_VIEW: AcceptanceView = {
  label: 'заменён пересборкой',
  tone: 'idle',
  tip: 'Вердикта у этой версии нет, но её пересборку вы приняли — решения она не ждёт',
  decided: false,
  pending: false,
};

/**
 * Ролик отказан после монтажа (CC-0116): фабрика сама его отклонила — вердикт не нужен, его
 * можно пересобрать. Плашка вместо «ждёт решения».
 */
export const REFUSED_VIEW: AcceptanceView = {
  label: 'отказан после монтажа',
  tone: 'danger',
  tip: 'Ролик собран, но фабрика отклонила его после монтажа: вердикт ему не нужен, его можно пересобрать',
  decided: false,
  pending: false,
};

/** «2026-10-13» → «13.10». */
export function shortDay(day: string): string {
  const m = day.match(/^\d{4}-(\d{2})-(\d{2})$/);
  return m ? `${m[2]}.${m[1]}` : day;
}
