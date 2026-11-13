import type { ChannelSummary } from '@/api/channels';
import type { PublishOverview, QueueLine } from '@/api/publish';
import type { PlanChannel, SchedulePlan } from '@/api/schedule';

import { OFF_REASON_TEXT, offReason, offSchedule } from './offSchedule';

const IN: PlanChannel = { plannable: true, settings: { enabled: true } };
const out = (p: Partial<PlanChannel> = {}, enabled: boolean | null = true): PlanChannel => ({
  plannable: false,
  why_not: 'строка фабрики',
  no_pipeline: false,
  ...p,
  settings: { enabled, ...p.settings },
});

const plan = (channels: Record<string, PlanChannel>): SchedulePlan =>
  ({ now: '', today: '', per_day: 1, stale_open: [], channels, days: [], timer: '' }) as never;

const summary = (id: string, p: Partial<ChannelSummary> = {}): ChannelSummary => ({
  id,
  display_name: id,
  former_ids: [],
  no_pipeline: null,
  stance: false,
  locked: false,
  error: null,
  ...p,
});

const line = (channel: string, p: Partial<QueueLine> = {}): QueueLine =>
  ({ channel, slot: { rule: 'x' }, error: null, ...p }) as never;
const queues = (...lines: QueueLine[]): PublishOverview => ({ as_of: '', channels: lines });

describe('каналы вне расписания: какая причина (CC-0140)', () => {
  const list = [summary('reel'), summary('tech'), summary('science')];

  it('в плане — не вне расписания; вне — по порядку списка каналов', () => {
    const p = plan({ science: out(), reel: IN, tech: out({}, false) });
    const off = offSchedule(p, list, queues(line('reel'), line('tech'), line('science')));
    expect(off.map((c) => c.id)).toEqual(['tech', 'science']);
    expect(off[0]).toMatchObject({
      reason: 'disabled',
      factory: 'строка фабрики',
      hasWindow: true,
    });
  });

  it('нет слота публикации: `slot: null` в очередях или канала в очередях нет', () => {
    const p = plan({ reel: IN, science: out() });
    expect(offReason('science', p, list, queues(line('science', { slot: null })))).toBe('no_slot');
    expect(offReason('science', p, list, queues(line('reel')))).toBe('no_slot');
    // Сломанный блок публикации: о слоте не знаем — не «нет слота».
    expect(
      offReason('science', p, list, queues(line('science', { slot: null, error: 'сломан' }))),
    ).toBe('unknown');
    // Очереди ещё не пришли — о слоте молчим.
    expect(offReason('science', p, list, undefined)).toBe('unknown');
  });

  it('порядок как у плана фабрики: конфиг → конвейер → слот → выключено', () => {
    const p = plan({ tech: out({ no_pipeline: true }, false) });
    const none = queues();
    expect(offReason('tech', p, [summary('tech', { error: 'не читается' })], none)).toBe(
      'config_error',
    );
    expect(offReason('tech', p, list, none)).toBe('no_pipeline');
    const off = plan({ tech: out({}, false) });
    expect(offReason('tech', off, list, none)).toBe('no_slot');
    expect(offReason('tech', off, list, queues(line('tech')))).toBe('disabled');
  });

  it('конвейер: план главнее списка каналов; списку верим, когда канала в плане нет', () => {
    const stub = [summary('science', { no_pipeline: 'конвейера нет' })];
    const q = queues(line('science'));
    expect(offReason('science', plan({ science: out() }), stub, q)).toBe('unknown');
    expect(offReason('science', plan({}), stub, q)).toBe('no_pipeline');
  });

  it('канал, которого в плане нет, — тоже строка, без ссылки на окно', () => {
    const off = offSchedule(plan({ reel: IN }), [...list, summary('new')], queues(line('reel')));
    expect(off.map((c) => [c.id, c.reason, c.hasWindow, c.factory])).toEqual([
      ['tech', 'no_slot', false, null],
      ['science', 'no_slot', false, null],
      ['new', 'no_slot', false, null],
    ]);
  });

  it('старое имя канала из плана — тот же канал списка, второй строки нет', () => {
    const off = offSchedule(
      plan({ old: out({}, false) }),
      [summary('reel', { former_ids: ['old'] })],
      queues(line('old')),
    );
    expect(off.map((c) => [c.id, c.reason])).toEqual([['old', 'disabled']]);
  });

  it('тексты причин — простыми словами', () => {
    expect(OFF_REASON_TEXT).toEqual({
      config_error: 'настройки канала не читаются',
      no_pipeline: 'у канала нет конвейера',
      no_slot: 'нет слота публикации',
      disabled: 'расписание батчей канала выключено',
      unknown: 'вне расписания батчей',
    });
  });
});
