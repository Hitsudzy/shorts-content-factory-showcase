// Слова «Повторить с…» (CC-0123): статус стадии run-state и строка фабрики — для человека.
import { humanReason } from '@/api/humanText';

import { isKnownStage, stageName } from './stages';

/** Статус стадии run-state словами (в списке «Повторить с…»). */
const STATUS: Record<string, string> = {
  done: 'готово',
  ok: 'готово',
  passed: 'готово',
  running: 'шла',
  failed: 'упала',
  halted: 'встала',
  error: 'упала',
  stopped: 'остановлена',
  paused: 'на паузе',
  pending: 'ещё не шла',
  waiting: 'ещё не шла',
  skipped: 'пропущена',
};
export const rerunStatus = (s: string) => STATUS[s] ?? s;

/** Строка фабрики словами: без путей и кодов, известные стадии — по-русски в «ёлочках». */
export function rerunWhy(text: string | null | undefined): string {
  if (!text) return '';
  return humanReason(text).replace(/\b[a-z][a-z0-9]*(?:-[a-z0-9]+)+\b/g, (m) =>
    isKnownStage(m) ? `«${stageName(m)}»` : m,
  );
}
