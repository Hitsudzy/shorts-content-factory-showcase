// Прогресс тура в этом браузере (localStorage). Хранилища может не быть (приватное окно,
// запрет сайта) — тогда тур работает так же, просто не помнит, где остановились.
import { SECTIONS, STEPS, type SectionId } from './steps';

export const TOUR_STORAGE_KEY = 'cc-tour';

export type TourProgress = {
  /** Шаги, которые зритель уже видел. */
  seen: string[];
  /** Шаг, на котором тур закрыли в прошлый раз. */
  last: string | null;
  /** Дошёл до последнего шага. */
  finished: boolean;
  /** Убрал строку «Пройдите короткое обучение» с главной. */
  dismissed: boolean;
};

export const EMPTY_PROGRESS: TourProgress = {
  seen: [],
  last: null,
  finished: false,
  dismissed: false,
};

const KNOWN = new Set(STEPS.map((s) => s.id));

/** Разбор сохранённого: чужое и испорченное отбрасывается, неизвестные шаги — тоже. */
export function parseProgress(raw: string | null): TourProgress {
  if (!raw) return EMPTY_PROGRESS;
  try {
    const v = JSON.parse(raw) as Partial<Record<keyof TourProgress, unknown>> | null;
    if (!v || typeof v !== 'object') return EMPTY_PROGRESS;
    const seen = Array.isArray(v.seen)
      ? [...new Set(v.seen.filter((s): s is string => typeof s === 'string' && KNOWN.has(s)))]
      : [];
    const last = typeof v.last === 'string' && KNOWN.has(v.last) ? v.last : null;
    return { seen, last, finished: v.finished === true, dismissed: v.dismissed === true };
  } catch {
    return EMPTY_PROGRESS;
  }
}

export function loadProgress(): TourProgress {
  try {
    return parseProgress(localStorage.getItem(TOUR_STORAGE_KEY));
  } catch {
    return EMPTY_PROGRESS;
  }
}

export function saveProgress(p: TourProgress): void {
  try {
    localStorage.setItem(TOUR_STORAGE_KEY, JSON.stringify(p));
  } catch {
    // Не запомнили — тур всё равно работает до перезагрузки.
  }
}

/** Отметить шаг увиденным и последним. */
export function markSeen(p: TourProgress, id: string): TourProgress {
  const seen = p.seen.includes(id) ? p.seen : [...p.seen, id];
  const finished = p.finished || id === STEPS[STEPS.length - 1]!.id;
  if (seen === p.seen && p.last === id && finished === p.finished) return p;
  return { ...p, seen, last: id, finished };
}

/** «Пройти заново»: всё забыть, кроме того, что строку на главной уже убрали. */
export const restartProgress = (p: TourProgress): TourProgress => ({
  ...EMPTY_PROGRESS,
  dismissed: p.dismissed || p.seen.length > 0,
});

/** Сколько шагов раздела зритель видел. */
export function sectionSeen(p: TourProgress, id: SectionId): { seen: number; total: number } {
  const steps = STEPS.filter((s) => s.section === id);
  return { seen: steps.filter((s) => p.seen.includes(s.id)).length, total: steps.length };
}

/** Строку на главной показывать, пока тур не начинали и её не убрали. */
export const showInvite = (p: TourProgress): boolean => !p.dismissed && p.seen.length === 0;

/** Номер шага, с которого продолжать (null — продолжать нечего). */
export function resumeIndex(p: TourProgress): number | null {
  if (p.finished || !p.last) return null;
  const i = STEPS.findIndex((s) => s.id === p.last);
  return i >= 0 ? i : null;
}

/** Все разделы пройдены. */
export const allSeen = (p: TourProgress): boolean =>
  SECTIONS.every((s) => {
    const r = sectionSeen(p, s.id);
    return r.seen === r.total;
  });
