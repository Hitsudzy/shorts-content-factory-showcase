// CC-0152 (фабрика 2.20, договор 0.69.0): размыкатель повторов, бюджет поиска и второй батч,
// несколько окон канала — слова центра и подставное расписание.
import type { Launch } from '@/api/batches';
import type { PlanDay, SchedulePlan } from '@/api/schedule';
import { nbShort } from '@/api/humanText';
import { REPEAT_HELD } from '@/mocks/batches';
import {
  createScheduleBackend,
  MOCK_BREAKER,
  MOCK_SPENT_TODAY,
  validateSettings,
} from '@/mocks/schedule';

import {
  BREAKER_TIP,
  batchWhen,
  breakerBadge,
  breakerText,
  heldLaunchText,
  isHeldLaunch,
  manualBreakerText,
} from './breaker';
import {
  ADMISSION_REASON,
  admissionText,
  budgetLines,
  heldBatches,
  heldText,
  type BudgetAdmission,
  type QuotaBudgetDay,
} from './budget';
import { dayWhy } from './dayWhy';
import { changesText, dayPill } from './format';
import { draftOf, editOf, windowsList } from './windowDraft';

const NAME = (id: string) => ({ 'example-film': 'ExampleFilm', 'example-tech': 'ExampleTech' })[id] ?? id;

describe('CC-0152: размыкатель повторов словами (CF-0822)', () => {
  it('день плана: канал, время батча по МСК, стадия по имени, конец удержания', () => {
    expect(batchWhen(MOCK_BREAKER.batch)).toBe('10.10,\u00a002:05\u00a0МСК');
    expect(breakerText(MOCK_BREAKER, NAME)).toBe(
      'Повтор ExampleFilm придержан: батч 10.10,\u00a002:05\u00a0МСК упал на «Поиск трендов», ' +
        'не потратив квоту. Следующий запуск\u00a0— после нового кода или в новые сутки квоты, ' +
        'с 11.10,\u00a010:00\u00a0МСК',
    );
  });

  it('стадия из `failure`, если `stage` нет; без времени и стадии — без них', () => {
    expect(
      breakerText({ ...MOCK_BREAKER, stage: null, failure: 'batch-start: exit 2' }, NAME),
    ).toContain('упал на «Старт батча»');
    expect(
      breakerText(
        { ...MOCK_BREAKER, batch: 'example-film/x', stage: null, failure: null, until: null },
        NAME,
      ),
    ).toBe(
      'Повтор ExampleFilm придержан: батч упал, не потратив квоту. Следующий запуск\u00a0— после нового кода или в новые сутки квоты',
    );
  });

  it('код сменился — один повтор разрешён', () => {
    const b = { ...MOCK_BREAKER, held: false, code_changed: ['root'] };
    expect(breakerText(b, NAME)).toBe(
      'Батч ExampleFilm: батч 10.10,\u00a002:05\u00a0МСК упал на «Поиск трендов», не потратив квоту, но код с тех пор сменился\u00a0— фабрика разрешит один повтор',
    );
    expect(breakerBadge(b).label).toBe('повтор разрешён');
  });

  it('метка дня — «повтор придержан» с правилом в подсказке', () => {
    const d = { status: 'idle', kind: 'nobody_available', breaker: MOCK_BREAKER } as const;
    expect(dayPill(d)).toEqual({ label: 'повтор придержан', tone: 'warn', tip: BREAKER_TIP });
    expect(dayPill({ status: 'idle', kind: 'nobody_available' }).label).toBe('некого');
    expect(BREAKER_TIP).toBe(
      'Защита от повтора: если батч упал, не потратив квоту поиска, фабрика не запускает его снова в те же сутки квоты, пока код не изменится. После нового кода разрешён один повтор. Ручной запуск защита не останавливает',
    );
  });

  it('dayWhy дня под размыкателем: пересказ записи и следующее окно, не «некого»', () => {
    const d: PlanDay = {
      day: '2026-10-11',
      status: 'idle',
      kind: 'nobody_available',
      breaker: MOCK_BREAKER,
      next_windows: { 'example-film': '2026-10-11T23:00:00Z' },
      notes: [MOCK_BREAKER.line!],
      covers_days: [],
      first_empty_slot: null,
    };
    const w = dayWhy(d, { channels: {}, days: [d] } as unknown as SchedulePlan, NAME);
    expect(w.text).toBe(breakerText(MOCK_BREAKER, NAME));
    expect(w.text).not.toContain('Некого');
    expect(w.next).toBe('Следующее окно: ExampleFilm 12.10,\u00a002:00\u00a0МСК');
  });

  it('проверка ручного запуска: размыкатель кнопку не держит', () => {
    expect(manualBreakerText(MOCK_BREAKER, NAME)).toBe(
      'Фабрика сама не повторит ExampleFilm в эти сутки квоты: батч 10.10,\u00a002:05\u00a0МСК упал на «Поиск трендов», не потратив квоту, код тот же. Ручной запуск защита от повтора не останавливает\u00a0— батч стартует',
    );
  });

  it('строка журнала `repeat_held` — не батч, словами', () => {
    expect(isHeldLaunch(REPEAT_HELD)).toBe(true);
    expect(isHeldLaunch({ kind: 'manual' } as Launch)).toBe(false);
    expect(isHeldLaunch(null)).toBe(false);
    expect(heldLaunchText(REPEAT_HELD)).toBe(
      'Фабрика не повторила батч 07.10,\u00a005:00\u00a0МСК: он упал на «Поиск трендов», не потратив квоту, код тот же. Батча не было',
    );
  });
});

const adm = (p: Partial<BudgetAdmission>): BudgetAdmission => ({
  channel: 'example-tech',
  quota_day: '2026-10-11',
  nth: 2,
  batches: 1,
  max_batches: 2,
  limit: 100,
  margin: 5,
  spent: 64,
  expected: 18,
  after: 82,
  left: 36,
  admitted: true,
  reason: 'ok',
  ...p,
});

describe('CC-0152: бюджет поиска и второй батч (CF-0830)', () => {
  it('причина допуска словами — четыре причины', () => {
    expect(
      Object.fromEntries(Object.entries(ADMISSION_REASON).map(([k, v]) => [k, v.label])),
    ).toEqual({
      ok: 'допущен по бюджету',
      budget: 'не хватит бюджета поиска',
      max_batches: 'лимит батчей в сутки',
      busy: 'занято другим батчем',
    });
    expect(admissionText(adm({}))).toBe(
      'допущен по бюджету: потрачено 64 + ожидается 18 = 82 из 95',
    );
    expect(admissionText(adm({ reason: 'budget', admitted: false, spent: 82, after: 100 }))).toBe(
      'не хватит бюджета поиска: потрачено 82 + ожидается 18 = 100, а можно не больше 95',
    );
    expect(admissionText(adm({ reason: 'max_batches', admitted: false, batches: 2 }))).toBe(
      'лимит батчей в сутки: уже 2 из 2',
    );
    expect(
      admissionText(adm({ reason: 'busy', admitted: false, start: '2026-10-12T07:12:00Z' })),
    ).toBe('занято другим батчем: окно пройдёт, пока он идёт (до\u00a010:12\u00a0МСК)');
  });

  it('блок бюджета: лимит, потрачено (с ожидаемым у батчей без записи), осталось, батчи', () => {
    const t: QuotaBudgetDay = {
      quota_day: '2026-10-10',
      limit: 100,
      margin: 5,
      max_batches: 2,
      batches: 1,
      spent: 82,
      spent_recorded: 82,
      left: 18,
    };
    expect(budgetLines(t)).toEqual({
      limit: '100 поисков, из них 5 в запасе',
      spent: '82',
      left: '13 до запаса (всего 18)',
      batches: '1 из 2',
    });
    expect(
      budgetLines({
        ...t,
        spent: 64,
        spent_recorded: 0,
        unrecorded: [{ batch: 'b', expected: 64 }],
        left: 36,
      }).spent,
    ).toBe('64: записано 0 + ожидается 64 у батча без записи');
    expect(budgetLines({ ...t, spent: 103, left: -3 }).left).toBe('0 до запаса (всего 0)');
  });

  it('батчи суток (CC-0157): строка запуска приклеивается к батчу — без «тиком» и ISO', () => {
    const text = (held: string[]) => heldBatches(held).map((h) => heldText(h, NAME));
    // Живой случай 21.10: папка батча и строка журнала запусков того же батча.
    expect(
      text([
        'example-film 2026-10-21T0837Z (pipeline/runs.jsonl)',
        'example-film запущен тиком 2026-10-21T08:37:02Z (schedule/launches.jsonl)',
      ]),
    ).toEqual(['ExampleFilm · 21.10, 11:37 — запустило расписание']);
    // Ручной запуск; запуск без папки — отдельный батч со временем запуска.
    expect(
      text([
        'example-tech 2026-10-21T0230Z (pipeline/)',
        'example-tech запущен вручную (центр) 2026-10-21T02:31:10Z (schedule/launches.jsonl)',
        'example-film запущен тиком 2026-10-21T14:00:05Z (schedule/launches.jsonl)',
      ]),
    ).toEqual([
      'ExampleTech · 21.10, 05:30 — запуск вручную',
      'ExampleFilm · 21.10, 17:00 — запустило расписание',
    ]);
    // Запуск далеко от папки того же канала — это другой батч.
    expect(
      text([
        'example-film 2026-10-21T0837Z (pipeline/runs.jsonl)',
        'example-film запущен тиком 2026-10-21T14:00:05Z (schedule/launches.jsonl)',
      ]),
    ).toEqual(['ExampleFilm · 21.10, 11:37', 'ExampleFilm · 21.10, 17:00 — запустило расписание']);
    // Без времени запуска — к батчу канала; нераспознанная строка — как раньше.
    expect(
      text([
        'example-film 2026-10-21T0837Z (pipeline/)',
        'example-film запущен тиком None (schedule/launches.jsonl)',
        'что-то новое у фабрики (x)',
      ]),
    ).toEqual(['ExampleFilm · 21.10, 11:37 — запустило расписание', 'что-то новое у фабрики']);
  });

  it('мок: бюджет суток квоты всегда, сцена бюджета — отказ сегодня и второй батч дня', () => {
    const b = createScheduleBackend();
    const plain = b.plan(7);
    if (plain.status !== 200) throw new Error('plan');
    expect(plain.body.quota_budget?.today).toMatchObject({
      spent: MOCK_SPENT_TODAY,
      left: 100 - MOCK_SPENT_TODAY,
      batches: 1,
    });
    expect(plain.body.days.some((d) => d.more?.length || d.budget?.length)).toBe(false);
    expect(plain.body.breakers).toEqual({});

    b.setScene({ budget: true });
    const p = b.plan(7);
    if (p.status !== 200) throw new Error('plan');
    expect(p.body.quota_budget?.windows_channels).toEqual(['example-film', 'example-tech']);
    expect(p.body.channels['example-tech']!.windows).toEqual(['05:30', '17:00']);
    const today = p.body.days[0]!;
    expect(today.budget?.map((a) => [a.channel, a.reason, a.after])).toEqual([
      ['example-film', 'budget', 146],
    ]);
    const second = p.body.days.find((d) => d.more?.length)!;
    expect(second.channel).toBe('example-film');
    expect(second.more!.map((m) => [m.channel, m.budget_admission?.reason])).toEqual([
      ['example-tech', 'ok'],
    ]);
    expect(second.more![0]!.budget_admission).toMatchObject({ nth: 2, spent: 64, after: 82 });
  });

  it('мок: сцена размыкателя — день 11.10 под размыкателем, канал с записью', () => {
    const b = createScheduleBackend();
    b.setScene({ breaker: true });
    const p = b.plan(7);
    if (p.status !== 200) throw new Error('plan');
    const held = p.body.days.filter((d) => d.breaker);
    expect(held.map((d) => [d.day, d.kind])).toEqual([['2026-10-11', 'nobody_available']]);
    expect(held[0]!.next_windows).toEqual({ 'example-film': '2026-10-11T23:00:00Z' });
    expect(p.body.breakers?.example-film?.held).toBe(true);
    expect(p.body.channels['example-film']!.breaker?.batch).toBe(MOCK_BREAKER.batch);
    expect(p.body.quota_budget?.today?.spent).toBe(0);
  });
});

describe('CC-0152: однобуквенные предлоги не висят', () => {
  it('nbShort: после «с», «в», «и» отдельным словом — неразрывный пробел', () => {
    expect(nbShort('встанут в слоты 12.10, с 11.10 и дальше')).toBe(
      'встанут в\u00a0слоты 12.10, с\u00a011.10 и\u00a0дальше',
    );
    expect(nbShort('С 11.10 (в 10:00)')).toBe('С\u00a011.10 (в\u00a010:00)');
    expect(nbShort('весь вес сок')).toBe('весь вес сок');
    expect(nbShort('слово в')).toBe('слово в');
  });
});

describe('CC-0152: несколько окон канала (CF-0830)', () => {
  const s = { enabled: true, window: '05:30', window_hours: 3, min_feed_days: 3 };

  it('черновик и тело PUT: окна — списком, пустое без окон — не трогать, с окнами — снять', () => {
    expect(windowsList(' 05:30,17:00 ; 21:15 ')).toEqual(['05:30', '17:00', '21:15']);
    const d = draftOf({ ...s, windows: ['05:30', '17:00'] });
    expect(d.windows).toBe('05:30, 17:00');
    expect(editOf(d, true).windows).toEqual(['05:30', '17:00']);
    expect(editOf({ ...d, windows: '' }, true).windows).toEqual([]);
    expect('windows' in editOf({ ...draftOf(s), windows: ' ' }, false)).toBe(false);
  });

  it('«что поменялось»: окна списком, снятые — прочерк', () => {
    expect(changesText({ windows: [null, ['05:30', '17:00']] })).toEqual([
      'окна: — → 05:30, 17:00',
    ]);
    expect(changesText({ windows: [['05:30'], null] })).toEqual(['окна: 05:30 → —']);
  });

  it('мок: проверка фабрики — по порядку, без повторов, не больше 4, ЧЧ:ММ', () => {
    expect(validateSettings({ windows: ['17:00', '05:30', '17:00'] })).toEqual({
      windows: ['05:30', '17:00'],
    });
    expect(validateSettings({ windows: [] })).toEqual({ windows: null });
    expect(() => validateSettings({ windows: ['5:30'] })).toThrow(
      "окна запуска: '5:30' - время ЧЧ:ММ, 00:00-23:59",
    );
  });

  it('мок PUT: записать, 422 — больше 4 и не время, снять', () => {
    const b = createScheduleBackend();
    const ok = b.save('example-tech', { windows: ['05:30', '17:00'] });
    expect(ok.status).toBe(200);
    if (ok.status !== 200) return;
    expect(ok.body.changed).toEqual({ windows: [null, ['05:30', '17:00']] });
    expect(ok.body.settings.windows).toEqual(['05:30', '17:00']);
    const many = b.save('example-tech', { windows: ['01:00', '02:00', '03:00', '04:00', '05:00'] });
    expect(many).toMatchObject({
      status: 422,
      body: { code: 'invalid', message: 'Настройка не принята: окна запуска - не больше 4.' },
    });
    const bad = b.save('example-tech', { windows: ['25:00'] });
    expect(bad).toMatchObject({
      status: 422,
      body: {
        message: "Настройка не принята: окна запуска: '25:00' - время ЧЧ:ММ, 00:00-23:59.",
      },
    });
    const off = b.save('example-tech', { windows: [] });
    expect(off.status === 200 && off.body.changed).toEqual({
      windows: [['05:30', '17:00'], null],
    });
    const same = b.save('example-tech', { window: '05:30' });
    expect(same.status === 200 && same.body.changed).toEqual({});
  });
});
