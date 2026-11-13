// Строки «Ближайшая публикация» и «Пауза» обзора канала (CC-0138): слова по ленте и паузе.
import type { ChannelPause } from '@/api/publish';
import { createPublishBackend, REEL, SCIENCE, TECH, TECH_QUEUE, UPLOADED } from '@/mocks/publish';

import { NEAREST_WORDS, nearestOf, pauseView, publishingHref } from './publishRows';

const queueOf = (b: ReturnType<typeof createPublishBackend>, c: string) => {
  const r = b.queue(c);
  if (r.status !== 200) throw new Error('queue');
  return r.body;
};

describe('обзор канала: ближайшая публикация', () => {
  it('ближайший занятый слот впереди: день, время МСК и ролик', () => {
    const b = createPublishBackend();
    expect(nearestOf(queueOf(b, TECH))).toMatchObject({
      kind: 'slot',
      slug: TECH_QUEUE[0],
      text: 'завтра, 01:00 МСК',
    });
    expect(nearestOf(queueOf(b, REEL))).toMatchObject({ kind: 'slot', slug: UPLOADED });
  });

  it('первые дни свободны — берёт первый занятый дальше; прошедший слот не в счёт', () => {
    const b = createPublishBackend();
    b.channels[TECH]!.taken = { 3: 'later' };
    expect(nearestOf(queueOf(b, TECH))).toMatchObject({
      slug: 'later',
      text: 'ср 14.10, 01:00 МСК',
    });
    const q = queueOf(b, TECH);
    expect(nearestOf({ ...q, as_of: '2026-10-15T00:00:00Z' }).kind).toBe('empty');
  });

  it('слота нет — «слот не задан», очередь пуста — «в очереди пусто»', () => {
    const b = createPublishBackend();
    expect(nearestOf(queueOf(b, SCIENCE)).kind).toBe('no-slot');
    b.channels[TECH]!.taken = {};
    expect(nearestOf(queueOf(b, TECH)).kind).toBe('empty');
    expect(NEAREST_WORDS).toEqual({ 'no-slot': 'слот не задан', empty: 'в очереди пусто' });
  });

  it('адрес «Публикации» канала и слота', () => {
    expect(publishingHref(TECH)).toBe('/publishing?channel=example-tech');
    expect(publishingHref(TECH, { day: '2026-10-11', slug: 'homepod' })).toBe(
      '/publishing?channel=example-tech&slot=2026-10-11%2Fhomepod',
    );
  });
});

describe('обзор канала: пауза', () => {
  const base: ChannelPause = {
    channel: TECH,
    as_of: '2026-10-10T07:00:00Z',
    state: 'free',
    line: 'free',
    row: null,
    open_row: null,
    history: [],
    registry: 'publish/channel-pauses.json',
  };
  const row = {
    pause_id: 'p',
    channel: TECH,
    by: 'user',
    reason: 'x',
    set_at: '2026-10-08T12:00:00Z',
    until: null,
    cleared_at: null,
    cleared_by: null,
    clear_note: null,
  };

  it('нет паузы — «нет», ссылка «поставить»', () => {
    expect(pauseView(base)).toEqual({ text: 'нет', action: 'поставить', tone: 'ok' });
  });

  it('на паузе — без срока или до какого времени по Москве, ссылка «снять»', () => {
    expect(pauseView({ ...base, state: 'paused', row })).toMatchObject({
      text: 'на паузе, без срока',
      action: 'снять',
    });
    expect(
      pauseView({ ...base, state: 'paused', row: { ...row, until: '2026-10-19T22:00:00Z' } }).text,
    ).toBe('на паузе до 20.10, 01:00');
  });

  it('срок прошёл — словами', () => {
    expect(pauseView({ ...base, state: 'expired', row }).text).toBe('срок паузы прошёл');
  });
});
