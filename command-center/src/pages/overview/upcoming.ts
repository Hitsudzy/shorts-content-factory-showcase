// «Ближайшие публикации» главной (CC-0138): слоты всех каналов публикации на 3 дня вперёд — из
// тех же лент слотов, что у экрана «Публикация» (`…/queue?days=14`), без отдельного адреса.
// Канал без слота — одной строкой «слот не задан», очередь не читается — «не читается».
import { isAhead, type ChannelQueue, type QueueLine } from '@/api/publish';
import { mskDay, slotDay, slotTime } from '@/pages/publishing/format';

/** На сколько дней вперёд главная показывает слоты. */
export const UPCOMING_DAYS = 3;
const SPAN_MS = UPCOMING_DAYS * 86_400_000;

export type UpcomingSlot = {
  channel: string;
  /** UTC ISO слота. */
  at: string;
  /** Московский день — папка дня `publish/<канал>/<день>/`. */
  day: string;
  /** «завтра», «пн 12.10». */
  when: string;
  /** «01:00». */
  time: string;
  /** «МСК». */
  zone: string;
  /** Кто в слоте; null — свободен. */
  slug: string | null;
  /** Канал на паузе: свободный слот так и останется пустым. */
  paused: boolean;
};

export type UpcomingNote = { channel: string; kind: 'no-slot' | 'broken' };

export type QueueRead = { data?: ChannelQueue; pending: boolean; error: boolean };

export type Upcoming = {
  slots: UpcomingSlot[];
  /** Каналы, у которых слотов не показать: нет слота, очередь не читается. */
  notes: UpcomingNote[];
  /** Какая-то из лент ещё читается. */
  pending: boolean;
};

/** Каналам с очередью нужна лента слотов; без слота и с отказом очереди — не нужна. */
export const wantsQueue = (l: QueueLine) => !!l.slot && !l.error;

/**
 * Слоты всех каналов на `UPCOMING_DAYS` дней вперёд от часов фабрики (`as_of` ленты): только
 * ещё не наступившие, по времени, при равном времени — в порядке каналов фабрики.
 */
export function upcomingOf(
  lines: readonly QueueLine[],
  queueOf: (channel: string) => QueueRead | undefined,
): Upcoming {
  const slots: UpcomingSlot[] = [];
  const notes: UpcomingNote[] = [];
  let pending = false;
  lines.forEach((l) => {
    if (l.error) return notes.push({ channel: l.channel, kind: 'broken' });
    if (!l.slot) return notes.push({ channel: l.channel, kind: 'no-slot' });
    const r = queueOf(l.channel);
    if (!r || r.pending) {
      pending = true;
      return;
    }
    if (r.error || !r.data) return notes.push({ channel: l.channel, kind: 'broken' });
    const q = r.data;
    if (!q.slot) return notes.push({ channel: l.channel, kind: 'no-slot' });
    const until = Date.parse(q.as_of) + SPAN_MS;
    const today = mskDay(q.as_of);
    for (const s of q.slots) {
      if (!isAhead(q, s) || Date.parse(s.at) > until) continue;
      const { time, zone } = slotTime(s);
      slots.push({
        channel: q.channel,
        at: s.at,
        day: s.day,
        when: slotDay(s.day, today),
        time,
        zone,
        slug: s.taken_by ?? null,
        paused: !!q.paused,
      });
    }
  });
  const order = (c: string) => lines.findIndex((l) => l.channel === c);
  slots.sort((a, b) => Date.parse(a.at) - Date.parse(b.at) || order(a.channel) - order(b.channel));
  return { slots, notes, pending };
}

/** Что сказать о канале, у которого слотов не показать. */
export const noteText = (n: UpcomingNote) =>
  n.kind === 'no-slot' ? 'слот не задан' : 'очередь не читается';

/** Подпись свободного слота. */
export const freeSlotText = (s: Pick<UpcomingSlot, 'paused'>) =>
  s.paused ? 'свободно · канал на паузе' : 'свободно';
