// Перенос размещённых роликов словами и правками (CC-0166): кто размещён впереди (из ленты),
// пачка «все с дня N — на день раньше или позже» (её собирает центр, судит фабрика целиком),
// подпись дня для выбора. CC-0180: отказы правки словами центра (сообщение фабрики — если оно
// по-русски; неизвестный код — запасной текст).
import { NAMESAKES_TEXT } from '@/api/batchProblem';
import { isAhead, isUploaded, occupantOf, type ChannelQueue } from '@/api/publish';
import type { MoveBody, MoveEdit } from '@/api/publishMove';

import { slotDay } from './format';

/**
 * Размещённый впереди ролик ленты: день, название, уже ли он в Studio (строка журнала). `batchId` —
 * только если тёзка лежит в копилке (CC-0183): тогда запись называет ролик с батчем.
 */
export type Placed = {
  slug: string;
  day: string;
  title: string;
  inStudio: boolean;
  batchId?: string | null;
};

/** Ролики ленты, чей слот ещё впереди, — по дням. */
export function placedOf(
  q: ChannelQueue,
  titleOf: (slug: string) => string,
  batchOf?: (slug: string, day: string) => string | null | undefined,
): Placed[] {
  return q.slots
    .filter((s) => s.taken_by && isAhead(q, s))
    .map((s) => ({
      slug: s.taken_by!,
      day: s.day,
      title: titleOf(s.taken_by!),
      inStudio: isUploaded(occupantOf(q, s)),
      batchId: batchOf?.(s.taken_by!, s.day) ?? null,
    }))
    .sort((a, b) => a.day.localeCompare(b.day));
}

/** CC-0183: правка переноса; батч — только когда он назван (есть тёзка), иначе как раньше. */
export const moveEdit = (slug: string, day: string, batchId?: string | null): MoveEdit =>
  batchId ? { slug, batch_id: batchId, day } : { slug, day };

/** CC-0183: имя в `unplace` и `withdraw` — строки: `<батч>/<имя>`, когда батч назван. */
export const moveName = (slug: string, batchId?: string | null) =>
  batchId ? `${batchId}/${slug}` : slug;

/** День `day` (`YYYY-MM-DD`) со сдвигом на `n` дней. */
export function addDay(day: string, n: number): string {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}

/**
 * Сдвиг очереди одним планом: все ролики с дня `from` — на `by` дней; `unplaceBefore` — ролики
 * дня перед `from` (при сдвиге раньше их день нужен первому из сдвинутых) — в копилку.
 */
export function shiftBody(
  placed: Placed[],
  from: string,
  by: -1 | 1,
  unplaceBefore: boolean,
): MoveBody {
  const before = addDay(from, -1);
  return {
    moves: placed
      .filter((p) => p.day >= from)
      .map((p) => moveEdit(p.slug, addDay(p.day, by), p.batchId)),
    unplace:
      by === -1 && unplaceBefore
        ? placed.filter((p) => p.day === before).map((p) => moveName(p.slug, p.batchId))
        : [],
  };
}

/** Дни ленты впереди (без повторов) — куда можно перенести. */
export function daysAhead(q: ChannelQueue): string[] {
  return [...new Set(q.slots.filter((s) => isAhead(q, s)).map((s) => s.day))];
}

/**
 * «вт 14.10 — свободен» / «ср 15.10 — занят: Название» для выбора дня; день дальше последнего дня
 * горизонта (`lastDay`, CC-0180) — с пометкой «за горизонтом».
 */
export function dayChoice(
  day: string,
  today: string,
  placed: Placed[],
  lastDay?: string | null,
): string {
  const there = placed.filter((p) => p.day === day);
  const beyond = lastDay && day > lastDay ? ', за горизонтом' : '';
  return there.length
    ? `${slotDay(day, today)} — занят: ${there.map((p) => p.title).join(', ')}${beyond}`
    : `${slotDay(day, today)} — свободен${beyond}`;
}

/** Отказы снятия и возврата из запаса словами центра — если фабрика не сказала по-русски. */
const MOVE_REFUSAL_WORDS: Record<string, string> = {
  not_in_studio:
    'Ролика нет в Studio — снимать из ленты нечего; его можно вернуть в копилку обычным снятием со слота.',
  in_reserve: 'Ролик уже снят из ленты и лежит в запасе — вернуть его можно переносом на день.',
  not_placed: 'Журнал загрузок знает ролик, а в папке дня его нет — сначала поправьте запись.',
  published: 'Слот ролика уже прошёл — опубликованный ролик не переносится и не снимается.',
  reserve_taken: 'Место занято роликом из запаса — выберите другой день.',
  ambiguous: 'Фабрика не поняла, какой из роликов с этим именем имеется в виду — нужен батч.',
  namesakes: NAMESAKES_TEXT,
};

/** Отказ правки для человека: сообщение фабрики по-русски, иначе слова по коду, иначе запасной. */
export function moveRefusalText(r: { code: string; message?: string | null }): string {
  if (r.message && /[а-яё]/i.test(r.message)) return r.message;
  return MOVE_REFUSAL_WORDS[r.code] ?? 'Фабрика отказала — причина в «Подробнее».';
}
