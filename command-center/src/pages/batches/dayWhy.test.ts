import type { PlanChannel, PlanDay, SchedulePlan } from '@/api/schedule';

import { dayWhy, daysText, nextWindowsText, notesWords, perDayText, quotaResetAt } from './dayWhy';
import { dayPill } from './format';
import dayWhySource from './dayWhy.ts?raw';
import weekPlanSource from './WeekPlan.tsx?raw';

const ch = (min: number | null, p: Partial<PlanChannel> = {}): PlanChannel => ({
  plannable: true,
  min_feed_days: min,
  settings: { enabled: true, min_feed_days: min },
  ...p,
});

const plan = (
  channels: Record<string, PlanChannel>,
  per_day = 1,
  over: Partial<SchedulePlan> = {},
): SchedulePlan =>
  ({
    now: '',
    today: '2026-10-10',
    quota_day: '2026-10-10',
    quota_tz: 'America/Los_Angeles',
    per_day,
    stale_open: [],
    channels,
    days: [],
    timer: '',
    ...over,
  }) as never;

const day = (p: Partial<PlanDay>): PlanDay => ({
  day: '2026-10-11',
  status: 'idle',
  kind: 'fed',
  covers_days: [],
  first_empty_slot: null,
  ...p,
});

const need = (p: Partial<PlanDay> = {}) =>
  day({
    status: 'planned',
    kind: 'needs_batch',
    channel: 'reel',
    why: 'лента короче 3 дн. (на 1 дн.): пусто 12.10 18:00 МСК',
    first_empty_slot: '2026-10-12T15:00:00Z',
    fills: ['2026-10-13T15:00:00Z', '2026-10-14T15:00:00Z', '2026-10-15T15:00:00Z'],
    covers_days: ['2026-10-13', '2026-10-14', '2026-10-15'],
    est_videos: 3,
    ...p,
  });

const BOTH = plan({ reel: ch(3), tech: ch(3) });
const names = (id: string) => ({ reel: 'ExampleFilm', tech: 'ExampleTech' })[id] ?? id;

describe('причина дня плана словами из `kind` (CC-0146, CC-0147)', () => {
  it('нужен батч: порог канала, первый пустой слот (не `fills[0]`), дни роликов', () => {
    const w = dayWhy(need(), BOTH);
    expect(w.text).toBe('Публикаций на 3 дня вперёд не хватает — нужен батч');
    // Первый пустой слот — из `first_empty_slot`: 12.10, хотя батч заполнит слоты с 13.10.
    expect(w.slot).toBe('Первый пустой слот: 12.10, 18:00 МСК');
    expect(w.covers).toBe('Ролики встанут в слоты 13.10–15.10');
    expect(`${w.text} ${w.slot} ${w.covers}`).not.toMatch(/дн\.|≥/);
    // Тире не начинает строку, дата со временем не рвётся (CC-0146).
    expect(`${w.text}. ${w.slot}. ${w.covers}`).not.toMatch(/ —|\n/);
    expect(w.slot).not.toMatch(/\d \d|\d МСК/);
  });

  it('нужен батч: порог из настроек; нет пустого слота и дней — без слота, «слотов нет»', () => {
    const p = plan({ reel: ch(null, { settings: { min_feed_days: 5 } }) });
    expect(dayWhy(need({ first_empty_slot: null, covers_days: [], fills: [] }), p)).toEqual({
      text: 'Публикаций на 5 дней вперёд не хватает — нужен батч',
      slot: null,
      covers: 'Свободных слотов после конца батча нет',
      next: null,
    });
    expect(dayWhy(need({ channel: 'gone' }), p).text).toBe(
      'Публикаций в ленте не хватает — нужен батч',
    );
    expect(dayWhy(need({ est_videos: 1, covers_days: ['2026-10-13'] }), p).covers).toBe(
      'Ролик встанет в слот 13.10',
    );
  });

  it('склонение порога: 1 день, 2 дня, 5 дней, 21 день', () => {
    const t = (n: number) => dayWhy(need(), plan({ reel: ch(n) })).text;
    expect(t(1)).toBe('Публикаций на 1 день вперёд не хватает — нужен батч');
    expect(t(2)).toBe('Публикаций на 2 дня вперёд не хватает — нужен батч');
    expect(t(5)).toBe('Публикаций на 5 дней вперёд не хватает — нужен батч');
    expect(t(21)).toBe('Публикаций на 21 день вперёд не хватает — нужен батч');
  });

  it('дни роликов коротко: диапазон от трёх дней, два дня и разрывы — списком', () => {
    expect(daysText([])).toBeNull();
    expect(daysText(['2026-10-18'])).toBe('18.10');
    expect(daysText(['2026-10-18', '2026-10-19'])).toBe('18.10 и 19.10');
    expect(daysText(['2026-10-20', '2026-10-18', '2026-10-19'])).toBe('18.10–20.10');
    expect(daysText(['2026-10-18', '2026-10-20', '2026-10-22'])).toBe('18.10, 20.10 и 22.10');
    expect(daysText(['2026-10-30', '2026-10-31', '2026-11-01', '2026-11-03'])).toBe(
      '30.10–01.11 и 03.11',
    );
  });

  it('батч не нужен (fed): общий порог каналов в расписании; разные пороги — без числа', () => {
    const d = day({ kind: 'fed', why: 'батч не нужен: у всех каналов лента не короче порога' });
    expect(dayWhy(d, BOTH).text).toBe('Публикаций хватает на 3 дня вперёд — батч не нужен');
    const mixed = plan({ reel: ch(3), tech: ch(4), off: ch(9, { plannable: false }) });
    expect(dayWhy(d, mixed).text).toBe('Публикаций у всех каналов хватает — батч не нужен');
    const off = plan({ reel: ch(4), off: ch(9, { plannable: false }) });
    expect(dayWhy(d, off).text).toBe('Публикаций хватает на 4 дня вперёд — батч не нужен');
    // Решает `kind`, а не начало строки фабрики.
    expect(dayWhy({ ...d, why: 'что-то новое' }, BOTH).text).toBe(
      'Публикаций хватает на 3 дня вперёд — батч не нужен',
    );
  });

  it('батч в эти сутки уже был (done_today): когда обновится квота, по МСК (CF-0787)', () => {
    const d = day({
      status: 'done',
      kind: 'done_today',
      channel: 'reel',
      quota_day: '2026-10-10',
      why: 'сутки квоты 2026-10-10 уже с батчем: reel 2026-10-10T0805Z',
    });
    // Сутки квоты 10.10 (Тихоокеанское) кончаются 11.10 в 07:00Z — 10:00 МСК.
    expect(dayWhy(d, BOTH)).toEqual({
      text: 'Батч в эти сутки квоты уже был — следующие начнутся 11.10,\u00a010:00\u00a0МСК',
      slot: null,
      covers: null,
      next: null,
    });
    // Без `quota_day` у дня — сутки плана; без суток вовсе — правило фабрики, как в шапке.
    expect(dayWhy({ ...d, quota_day: null }, BOTH).text).toContain('начнутся 11.10');
    expect(dayWhy({ ...d, quota_day: null }, plan({}, 2, { quota_day: '' })).text).toBe(
      'Батч в эти сутки квоты уже был — не больше 2 батчей в сутки на всю фабрику',
    );
  });

  it('конец суток квоты: 07:00Z летом, 08:00Z с 01.11 (тихоокеанская полночь)', () => {
    expect(quotaResetAt('2026-10-10')).toBe('2026-10-11T07:00:00Z');
    expect(quotaResetAt('2026-10-31')).toBe('2026-11-01T07:00:00Z');
    expect(quotaResetAt('2026-11-01')).toBe('2026-11-02T08:00:00Z');
    expect(quotaResetAt('нет')).toBeNull();
  });

  it('квота суток занята батчем (quota_day_taken, done): следующее окно по МСК', () => {
    const d = day({
      status: 'done',
      kind: 'quota_day_taken',
      quota_day: '2026-10-10',
      next_windows: { reel: '2026-10-11T23:00:00Z' },
      why: 'сутки квоты 2026-10-10 уже с батчем: reel окно 11.10 02:00 МСК',
    });
    expect(dayWhy(d, BOTH, names)).toEqual({
      text: 'Эти сутки квоты поиска YouTube уже занял прошлый батч — второй не запускается',
      slot: null,
      covers: null,
      next: 'Следующее окно: ExampleFilm 12.10,\u00a002:00\u00a0МСК',
    });
    // В этот день батча не было — не «батч был», а «квота занята» (его — только у done_today).
    expect(dayPill(d).label).toBe('квота занята');
    expect(dayPill(day({ status: 'done', kind: 'done_today' })).label).toBe('батч был');
    expect(dayPill(d).tip).toMatch(/100 поисков в сутки на все каналы/);
  });

  it('квота суток уйдёт на более ранний день плана (quota_day_taken, idle): каналы вместе', () => {
    const holder = need({ day: '2026-10-18', quota_day: '2026-10-18' });
    const d = day({
      day: '2026-10-19',
      status: 'idle',
      kind: 'quota_day_taken',
      quota_day: '2026-10-18',
      next_windows: {
        tech: '2026-10-19T08:30:00Z',
        reel: '2026-10-19T08:30:00Z',
        science: '2026-10-20T08:30:00Z',
      },
    });
    const p = { ...BOTH, days: [holder, d] };
    const w = dayWhy(d, p, names);
    expect(w.text).toBe(
      'Эти сутки квоты поиска YouTube займёт батч 18.10 — в этот день батча не будет',
    );
    // Одно время у двух каналов — вместе, в порядке `next_windows`; дальше — по времени.
    expect(w.next).toBe(
      'Следующие окна: ExampleTech и ExampleFilm 19.10,\u00a011:30\u00a0МСК; science 20.10,\u00a011:30\u00a0МСК',
    );
    expect(`${w.text}. ${w.next}`).not.toMatch(/ —|\n/);
    // Держателя в плане нет — без даты.
    expect(dayWhy(d, BOTH, names).text).toBe(
      'Эти сутки квоты поиска YouTube займёт батч дня раньше — в этот день батча не будет',
    );
    // Метка — своя: не «без батча» и не «некого»; подсказка объясняет квоту.
    const pill = dayPill(d);
    expect(pill.label).toBe('квота занята');
    expect(pill.label).not.toBe(dayPill(day({ kind: 'fed' })).label);
    expect(pill.label).not.toBe(dayPill(day({ kind: 'nobody_available' })).label);
    expect(pill.tip).toMatch(/100 поисков в сутки на все каналы/);
    expect(pill.tip).toMatch(/полночь по тихоокеанскому времени\u00a0— в 10:00\u00a0МСК/);
    expect(pill.tip).toMatch(/с 1\u00a0ноября до марта\u00a0— в 11:00\u00a0МСК/);
  });

  it('следующие окна: канал без окна в ближайшие дни, ни одного окна, пусто', () => {
    expect(nextWindowsText({ reel: '2026-10-19T08:30:00Z', tech: null }, names)).toBe(
      'Следующее окно: ExampleFilm 19.10,\u00a011:30\u00a0МСК; у ExampleTech в ближайшие дни окна нет',
    );
    expect(nextWindowsText({ reel: null, tech: null }, names)).toBe(
      'Следующего окна в ближайшие дни нет',
    );
    expect(nextWindowsText({})).toBeNull();
  });

  it('шапка: не больше одного / 2 / 5 / 21 батча', () => {
    expect(perDayText(1)).toBe('не больше одного батча в сутки на всю фабрику');
    expect(perDayText(2)).toBe('не больше 2 батчей в сутки на всю фабрику');
    expect(perDayText(5)).toBe('не больше 5 батчей в сутки на всю фабрику');
    expect(perDayText(21)).toBe('не больше 21 батча в сутки на всю фабрику');
  });

  it('идёт батч (running)', () => {
    const d = day({ status: 'busy', kind: 'running', channel: 'reel', why: 'день занят: …' });
    expect(dayWhy(d, BOTH)).toEqual({
      text: 'Идёт батч — второй в этот день не запускается',
      slot: null,
      covers: null,
      next: null,
    });
  });

  it('некого планировать (nobody_plannable): ни слота, ни плана запуска', () => {
    const d = day({
      kind: 'nobody_plannable',
      why: 'некого планировать: ни у одного канала нет слота и run_plan',
    });
    expect(dayWhy(d, plan({})).text).toBe(
      'Некого планировать: ни у одного канала нет слота и плана запуска',
    );
  });

  it('некого планировать в этот день (nobody_available): заметки каналов словами', () => {
    const passed = 'reel: окно 10.10 02:00 МСК сегодня прошло';
    const paused = 'tech: на паузе - пауза публикаций до 17.10 - заметка «ключи»';
    const d = day({
      kind: 'nobody_available',
      why: `некого планировать: ${passed}; ${paused}`,
      notes: [passed, paused],
    });
    expect(dayWhy(d, BOTH, names).text).toBe(
      'Некого планировать: у ExampleFilm окно в 02:00\u00a0МСК уже прошло; ' +
        'ExampleTech на паузе до 17.10\u00a0— заметка «ключи»',
    );
    expect(dayWhy({ ...d, notes: [] }, BOTH).text).toBe('Некого планировать в этот день');
  });

  it('заметки: одна причина — один раз, каналы вместе; незнакомая — как есть', () => {
    const why = 'пауза до 17.10 (заметка: «меняю ключи YouTube»)';
    expect(notesWords([`reel: на паузе - ${why}`, `tech: на паузе - ${why}`], names)).toEqual([
      'ExampleFilm и ExampleTech на паузе до 17.10 (заметка: «меняю ключи YouTube»)',
    ]);
    expect(
      notesWords(
        ['reel: окно 10.10 02:00 МСК сегодня прошло', 'tech: окно 10.10 05:30 МСК сегодня прошло'],
        names,
      ),
    ).toEqual(['у ExampleFilm и ExampleTech окна на сегодня уже прошли']);
    // Разные причины паузы — по строке; причина без слова «пауза» — после двоеточия.
    expect(
      notesWords(['reel: на паузе - ручная остановка', 'tech: на паузе - пауза до 18.10'], names),
    ).toEqual(['ExampleFilm на паузе: ручная остановка', 'ExampleTech на паузе до 18.10']);
    expect(notesWords(['tech: что-то новое - вот', 'без канала'], names)).toEqual([
      'ExampleTech: что-то новое\u00a0— вот',
      'без канала',
    ]);
  });

  it('незнакомый `kind` — нейтральная фраза', () => {
    expect(dayWhy(day({ kind: 'later' as never }), BOTH).text).toBe('В этот день батча не будет');
  });

  it('начало строки фабрики `why` больше не сравнивается (CC-0147)', () => {
    for (const src of [dayWhySource, weekPlanSource]) {
      expect(src).not.toMatch(/why\??\.startsWith/);
      expect(src).not.toMatch(/'батч не нужен'|'некого планировать'/);
    }
  });
});
