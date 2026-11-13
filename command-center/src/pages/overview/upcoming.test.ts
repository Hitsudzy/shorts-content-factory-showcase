// «Ближайшие публикации» главной (CC-0138): какие слоты попадают в 3 дня и что сказать о канале.
import type { ChannelQueue, QueueLine } from '@/api/publish';
import { createPublishBackend, REEL, SCIENCE, TECH, TECH_QUEUE, UPLOADED } from '@/mocks/publish';

import { freeSlotText, noteText, upcomingOf, wantsQueue, type QueueRead } from './upcoming';

function world() {
  const b = createPublishBackend();
  const o = b.overview();
  if (o.status !== 200) throw new Error('overview');
  const queue = (c: string): QueueRead => {
    const r = b.queue(c);
    return r.status === 200
      ? { data: r.body, pending: false, error: false }
      : { pending: false, error: true };
  };
  return { b, lines: o.body.channels, queue };
}

describe('ближайшие публикации: слоты на 3 дня', () => {
  it('как на фабрике 16.10: Reel и Tech по 01:00 три дня подряд, у Science слота нет', () => {
    const { lines, queue } = world();
    const u = upcomingOf(lines, queue);
    expect(u.pending).toBe(false);
    // Сегодняшний слот 01:00 уже прошёл (сейчас 10:00 МСК), 14.10 — дальше трёх дней.
    expect(u.slots.map((s) => `${s.day} ${s.time} ${s.channel} ${s.slug}`)).toEqual([
      `2026-10-11 01:00 ${REEL} ${UPLOADED}`,
      `2026-10-11 01:00 ${TECH} ${TECH_QUEUE[0]}`,
      `2026-10-12 01:00 ${REEL} delver`,
      `2026-10-12 01:00 ${TECH} ${TECH_QUEUE[1]}`,
      `2026-10-13 01:00 ${REEL} vanguards-doomsday`,
      `2026-10-13 01:00 ${TECH} ${TECH_QUEUE[2]}`,
    ]);
    expect(u.slots[0]).toMatchObject({ when: 'завтра', zone: 'МСК', paused: false });
    expect(u.slots[2]!.when).toBe('пн 12.10');
    expect(u.notes).toEqual([{ channel: SCIENCE, kind: 'no-slot' }]);
    expect(noteText(u.notes[0]!)).toBe('слот не задан');
  });

  it('свободный слот — «свободно», у канала на паузе — с пометкой', () => {
    const { b, lines, queue } = world();
    delete b.channels[TECH]!.taken[1];
    const free = upcomingOf(lines, queue).slots.find((s) => s.channel === TECH && !s.slug)!;
    expect(free.day).toBe('2026-10-12');
    expect(freeSlotText(free)).toBe('свободно');
    b.channels[TECH]!.pause = { ...b.channels[SCIENCE]!.pause!, channel: TECH };
    const paused = upcomingOf(lines, queue).slots.find((s) => s.channel === TECH && !s.slug)!;
    expect(freeSlotText(paused)).toBe('свободно · канал на паузе');
  });

  it('лента ещё читается — ждём; не прочиталась или отказ в строке канала — «очередь не читается»', () => {
    const { lines, queue } = world();
    const pending = upcomingOf(lines, (c) =>
      c === TECH ? { pending: true, error: false } : queue(c),
    );
    expect(pending.pending).toBe(true);
    expect(pending.slots.every((s) => s.channel === REEL)).toBe(true);

    const failed = upcomingOf(lines, (c) =>
      c === TECH ? { pending: false, error: true } : queue(c),
    );
    expect(failed.notes).toContainEqual({ channel: TECH, kind: 'broken' });
    expect(noteText({ channel: TECH, kind: 'broken' })).toBe('очередь не читается');

    const broken: QueueLine[] = lines.map((l) => (l.channel === REEL ? { ...l, error: 'x' } : l));
    expect(wantsQueue(broken[0]!)).toBe(false);
    expect(upcomingOf(broken, queue).notes[0]).toEqual({ channel: REEL, kind: 'broken' });
  });

  it('на 3 дня слотов нет — пусто; прошедший слот не показывается', () => {
    const { lines, queue } = world();
    const late = (c: string): QueueRead => {
      const r = queue(c);
      return r.data
        ? { ...r, data: { ...r.data, as_of: '2026-12-01T00:00:00Z' } as ChannelQueue }
        : r;
    };
    expect(upcomingOf(lines, late).slots).toEqual([]);
  });
});
