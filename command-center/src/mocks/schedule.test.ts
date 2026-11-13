import { BatchError } from '@/api/batchProblem';
import {
  getChannelSchedule,
  getSchedule,
  saveChannelSchedule,
  setSwitch,
  type SchedulePlan,
} from '@/api/schedule';

import { schedule } from './handlers';
import {
  ALL_FED_DAY,
  NO_SLOT,
  NOTE_REQUIRED,
  PAUSE_WHY,
  PAUSED_DAY,
  QUOTA_TAKEN_DAY,
  createScheduleBackend,
  validateSettings,
} from './schedule';

async function refusal(p: Promise<unknown>): Promise<BatchError> {
  const e = await p.then(
    () => null,
    (x: unknown) => x,
  );
  expect(e).toBeInstanceOf(BatchError);
  return e as BatchError;
}

describe('подставное расписание батчей (клиент → MSW → мок со состоянием)', () => {
  it('план на 7 дней: дни, каналы, рубильник выключен, строка таймера', async () => {
    const p = await getSchedule(7);
    expect(p.days).toHaveLength(7);
    expect(p.days[0]!.status).toBe('done');
    expect(p.days.some((d) => d.status === 'planned')).toBe(true);
    expect(p.channels['example-film']!.plannable).toBe(true);
    expect(p.channels['example-tech']!.plannable).toBe(true);
    expect(p.channels['example-science']!).toMatchObject({ plannable: false, why_not: NO_SLOT });
    // Оба канала в расписании берут дни: самая короткая лента — первой; в один день батч
    // не нужен никому (CC-0146) — день без канала.
    expect(new Set(p.days.map((d) => d.channel))).toEqual(
      new Set(['example-film', 'example-tech', null]),
    );
    expect(p.days[ALL_FED_DAY]).toMatchObject({ status: 'idle', channel: null });
    expect(p.days[ALL_FED_DAY]!.why).toMatch(/^батч не нужен: /);
    // Ветка дня — `kind` (CC-0147); у дня с батчем — его дни и первый пустой слот.
    expect(p.days.map((d) => d.kind)).toEqual([
      'done_today',
      'quota_day_taken',
      'needs_batch',
      'needs_batch',
      'needs_batch',
      'fed',
      'nobody_available',
    ]);
    // Сутки квоты поиска YouTube (CF-0787): батч уже был в сутках 10.10, окна 11.10 — в них же;
    // следующее окно ExampleFilm — 12.10 02:00 МСК (сутки 11.10), ExampleTech батч не нужен.
    expect(p).toMatchObject({ quota_day: '2026-10-10', quota_tz: 'America/Los_Angeles' });
    expect(p.days[0]).toMatchObject({ quota_day: '2026-10-10', next_windows: {} });
    expect(p.days[QUOTA_TAKEN_DAY]).toMatchObject({
      status: 'done',
      channel: null,
      quota_day: '2026-10-10',
      next_windows: { 'example-film': '2026-10-11T23:00:00Z' },
    });
    expect(p.days.map((d) => d.quota_day)).toEqual([
      '2026-10-10',
      '2026-10-10',
      '2026-10-11',
      '2026-10-12',
      '2026-10-13',
      null,
      null,
    ]);
    for (const d of p.days.filter((x) => x.kind !== 'quota_day_taken'))
      expect(d.next_windows).toEqual({});
    expect(p.days[PAUSED_DAY]!.notes).toEqual([
      `example-film: на паузе - ${PAUSE_WHY}`,
      `example-tech: на паузе - ${PAUSE_WHY}`,
    ]);
    expect(p.days[2]).toMatchObject({
      first_empty_slot: '2026-10-12T15:00:00Z',
      fills: ['2026-10-12T15:00:00Z', '2026-10-13T15:00:00Z', '2026-10-14T15:00:00Z'],
      covers_days: ['2026-10-12', '2026-10-13', '2026-10-14'],
    });
    for (const d of p.days.filter((x) => x.kind !== 'needs_batch'))
      expect(d).toMatchObject({ covers_days: [], first_empty_slot: null });
    expect(p.switch.on).toBe(false);
    expect(p.timer).toMatch(/таймер тика/);
  });

  it('ветки дня: идёт батч (running), окна прошли (nobody_available), никого (nobody_plannable)', () => {
    const b = createScheduleBackend();
    b.setRunning({ channel: 'example-tech', id: '2026-10-10T0230Z' });
    const busy = (b.plan(2).body as SchedulePlan).days[0]!;
    expect(busy).toMatchObject({ status: 'busy', kind: 'running', channel: 'example-tech' });
    b.setRunning(null);
    b.setDoneToday(false);
    const today = (b.plan(2).body as SchedulePlan).days[0]!;
    expect(today).toMatchObject({ status: 'idle', kind: 'nobody_available' });
    expect(today.notes).toEqual([
      'example-film: окно 10.10 02:00 МСК сегодня прошло',
      'example-tech: окно 10.10 05:30 МСК сегодня прошло',
    ]);
    // Батча в сутках квоты 10.10 не было — окно 11.10 свободно, сутки берёт день плана.
    expect((b.plan(2).body as SchedulePlan).days[1]).toMatchObject({
      kind: 'needs_batch',
      quota_day: '2026-10-10',
    });
    b.save('example-film', { enabled: false });
    b.save('example-tech', { enabled: false });
    const none = (b.plan(3).body as SchedulePlan).days;
    expect(none.map((d) => d.kind)).toEqual([
      'nobody_plannable',
      'nobody_plannable',
      'nobody_plannable',
    ]);
    expect(none.every((d) => !d.notes?.length)).toBe(true);
  });

  it('рубильник: включить без заметки — 422 note_required, с заметкой — включён', async () => {
    const e = await refusal(setSwitch({ on: true, note: '  ' }));
    expect(e.status).toBe(422);
    expect(e.problem?.code).toBe('note_required');
    expect(e.message).toBe(NOTE_REQUIRED);
    expect(schedule.writes).toHaveLength(0);

    const on = await setSwitch({ on: true, note: 'в чате 10.10 сказал «включай»' });
    expect(on.on).toBe(true);
    expect(on.note).toBe('центр: в чате 10.10 сказал «включай»');
    expect((await getSchedule()).switch.on).toBe(true);
    // Выключить можно и без заметки.
    expect((await setSwitch({ on: false })).on).toBe(false);
  });

  it('окно канала: сохранение, «ничего не поменялось», 422 invalid, источник и пульт', async () => {
    const before = await getChannelSchedule('example-film');
    expect(before.settings.overlay).toEqual({});
    expect(before.settings.source).toBe('channels/example-film.json batch_schedule');

    const r = await saveChannelSchedule('example-film', { window: '03:30', window_hours: 2.5 });
    expect(r.changed).toEqual({ window: ['02:00', '03:30'], window_hours: [3, 2.5] });
    expect(r.settings.overlay).toEqual({ window: '03:30', window_hours: 2.5 });
    expect(r.settings.source).toMatch(/пульт/);
    expect(r.history).toHaveLength(1);

    const same = await saveChannelSchedule('example-film', { window: '03:30' });
    expect(same.changed).toEqual({});
    expect(same.history).toHaveLength(1);

    const e = await refusal(saveChannelSchedule('example-film', { window_hours: 0.3 }));
    expect(e.status).toBe(422);
    expect(e.problem?.code).toBe('invalid');
    expect(e.message).toBe('Настройка не принята: длительность окна 0.3: от 0.5 до 24 ч');

    const plan = await getSchedule();
    const planned = plan.days.find((d) => d.status === 'planned')!;
    expect(planned.window_start).toMatch(/T00:30:00Z$/);
  });

  it('неизвестный канал — 404 unknown_channel', async () => {
    const e = await refusal(getChannelSchedule('nope'));
    expect(e.status).toBe(404);
    expect(e.problem?.code).toBe('unknown_channel');
  });

  it('проверка значений — как у фабрики', () => {
    expect(() => validateSettings({ window: '24:00' })).toThrow(/ЧЧ:ММ/);
    expect(() => validateSettings({ window_hours: 1.1 })).toThrow(/шаг 0.25/);
    expect(() => validateSettings({ min_feed_days: 31 })).toThrow(/от 1 до 30/);
    expect(() => validateSettings({ min_feed_days: 2.5 })).toThrow(/целое/);
    expect(validateSettings({ window: '07:05', min_feed_days: 4 })).toEqual({
      window: '07:05',
      min_feed_days: 4,
    });
    expect(() => validateSettings({ batch_feed_days: 0 })).toThrow(
      'порог батча 0: целое число дней от 1 до 30',
    );
    expect(() => validateSettings({ batch_feed_days: 31 })).toThrow(/от 1 до 30/);
    expect(() => validateSettings({ batch_feed_days: 2.5 })).toThrow(/целое/);
    expect(validateSettings({ batch_feed_days: 7 })).toEqual({ batch_feed_days: 7 });
  });

  it('CC-0185: порог батча — в силе, задан ли — по пульту и файлу канала; ниже горизонта — 409', async () => {
    // Наука без блока в файле: порог по умолчанию фабрики, 14 дн.
    const sci = await getChannelSchedule('example-science');
    expect(sci.settings).toMatchObject({ min_feed_days: 3, batch_feed_days: 14, overlay: {} });
    expect(sci.settings.source).toBe('по умолчанию');
    // Горизонт выше 14 — порог по умолчанию поднимается до него.
    const up = await saveChannelSchedule('example-science', { min_feed_days: 20 });
    expect(up.settings.batch_feed_days).toBe(20);
    expect(up.settings.overlay).toEqual({ min_feed_days: 20 });

    // Reel: порог задан в файле канала (3 дн.), в плане рядом с горизонтом.
    const plan = await getSchedule();
    expect(plan.channels['example-film']).toMatchObject({ min_feed_days: 3, batch_feed_days: 3 });
    expect(plan.channels['example-film']!.settings.batch_feed_days).toBe(3);

    const r = await saveChannelSchedule('example-film', { batch_feed_days: 5 });
    expect(r.changed).toEqual({ batch_feed_days: [3, 5] });
    expect(r.settings).toMatchObject({ batch_feed_days: 5, overlay: { batch_feed_days: 5 } });

    // Порог ниже горизонта — фабрика не принимает целиком: 409 refused её словами.
    const writes = schedule.writes.length;
    const e = await refusal(saveChannelSchedule('example-film', { batch_feed_days: 2 }));
    expect(e.status).toBe(409);
    expect(e.problem?.code).toBe('refused');
    expect(e.message).toBe(
      'Фабрика не приняла настройки расписания канала example-film: порог батча не меньше горизонта ленты - порог батча 2 дн., горизонт ленты 3 дн.',
    );
    // И когда горизонт поднимают выше уже заданного порога.
    const e2 = await refusal(saveChannelSchedule('example-film', { min_feed_days: 6 }));
    expect(e2.status).toBe(409);
    expect(e2.message).toMatch(/порог батча 5 дн\., горизонт ленты 6 дн\.$/);
    expect(schedule.writes).toHaveLength(writes);
    expect((await getChannelSchedule('example-film')).settings.batch_feed_days).toBe(5);
  });
});
