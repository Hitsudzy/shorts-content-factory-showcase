// Слова истории переключателя API-загрузки (CC-0141): кто, что, порядок строк — для
// ./SwitchHistory.
import type { ApiSwitchState } from '@/api/publish';

export type SwitchHistoryRow = ApiSwitchState['history'][number];

/** Сколько последних строк показать. */
export const HISTORY_SHOWN = 5;

/**
 * Кто переключил — словами: `user` — вы, `user (центр)` — вы из центра, `system` — фабрика;
 * иное как есть.
 */
export function switchWho(by: string | null | undefined): string {
  const s = (by ?? '').trim();
  if (!s) return 'кто — не записано';
  if (s === 'user') return 'вы';
  if (s === 'user (центр)') return 'вы, из центра';
  if (s === 'system') return 'фабрика';
  return s;
}

/** Что сделали: `on` — включена, `off` — выключена; незнакомое — как есть. */
export function switchAction(action: string | null | undefined): string {
  if (action === 'on') return 'включена';
  if (action === 'off') return 'выключена';
  return action?.trim() || 'действие не записано';
}

const time = (r: SwitchHistoryRow) => {
  const t = r.at ? Date.parse(r.at) : NaN;
  return Number.isNaN(t) ? -Infinity : t;
};

/** Последние `n` строк, новые сверху: по `at`; без даты — в конце, в обратном порядке записи. */
export function latestSwitches(
  rows: readonly SwitchHistoryRow[],
  n = HISTORY_SHOWN,
): SwitchHistoryRow[] {
  return [...rows]
    .reverse()
    .sort((a, b) => time(b) - time(a))
    .slice(0, n);
}
