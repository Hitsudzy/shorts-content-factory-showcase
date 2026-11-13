// Пустые дни ленты (CC-0142, как у ленты в пульте 2.2): за окно ленты от сегодняшнего московского
// дня — дни, где у канала есть слот впереди, но ни один слот этого дня не занят. Считается из
// `slots` очереди как есть: день — `slot.day` фабрики (московский), занят — `slot.taken_by`,
// впереди — `slot.at` не раньше `as_of`. Сегодняшний слот, который уже прошёл, не считается.
import { FEED_DAYS, type ChannelQueue } from '@/api/publish';
import { plural } from '@/pages/batches/format';

import { mskDay } from './format';

const NBSP = ' ';

function addDays(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/**
 * Пустые дни (`YYYY-MM-DD`, по порядку) за `days` дней с сегодняшнего московского; null — графика
 * нет (у канала нет слота или фабрика не нашла слотов): тогда строки у ленты нет.
 */
export function emptyDays(
  q: Pick<ChannelQueue, 'slot' | 'slots' | 'as_of' | 'days'>,
  /** CC-0180: последний день горизонта ленты: дальше него пустой день — не пропуск, а запас. */
  lastDay?: string | null,
): string[] | null {
  if (!q.slot || !q.slots.length) return null;
  const today = mskDay(q.as_of);
  const window = addDays(today, (q.days || FEED_DAYS) - 1);
  const end = lastDay && lastDay < window ? lastDay : window;
  const now = Date.parse(q.as_of);
  const byDay = new Map<string, { ahead: boolean; taken: boolean }>();
  for (const s of q.slots) {
    if (s.day < today || s.day > end) continue;
    const d = byDay.get(s.day) ?? { ahead: false, taken: false };
    if (Date.parse(s.at) >= now) d.ahead = true;
    if (s.taken_by) d.taken = true;
    byDay.set(s.day, d);
  }
  return [...byDay]
    .filter(([, d]) => d.ahead && !d.taken)
    .map(([day]) => day)
    .sort();
}

/** «2 недели», «неделю», «10 дней» — окно ленты словами (число с неразрывным пробелом). */
export function periodText(days: number): string {
  if (days % 7 === 0) {
    const w = days / 7;
    return w === 1 ? 'неделю' : `${w}${NBSP}${plural(w, 'неделю', 'недели', 'недель')}`;
  }
  return `${days}${NBSP}${plural(days, 'день', 'дня', 'дней')}`;
}

const ddmm = (day: string) => `${day.slice(8, 10)}.${day.slice(5, 7)}`;

/**
 * «Пустых дней за 2 недели: 3 — 19.10, 22.10, 25.10»; ни одного — «Пустых дней за 2 недели нет».
 * Перед тире — неразрывный пробел: тире не начинает строку.
 */
export function emptyDaysText(list: string[], days = FEED_DAYS): string {
  const over = `за ${periodText(days)}`;
  if (!list.length) return `Пустых дней ${over} нет`;
  return `Пустых дней ${over}: ${list.length}${NBSP}— ${list.map(ddmm).join(', ')}`;
}

/**
 * Предупреждение, когда журнала загрузок (publish/uploads.json) нет (`journal_exists`). Журнал один
 * на фабрику — строка одна над каналами «Публикации», не у ленты канала (CC-0148).
 */
export const JOURNAL_MISSING = `Журнала загрузок нет${NBSP}— фабрика не видит, что уже выложено`;

/**
 * У канала ещё нет строк в журнале загрузок (`rows` — 0 при `journal_exists`), CC-0149. Журнал один
 * на фабрику, строки помечены каналом; когда журнала нет вовсе, говорит плашка над каналами (CC-0148).
 */
export const JOURNAL_NO_ROWS = 'У канала ещё нет записей в журнале загрузок';
