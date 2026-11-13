// Подставное расписание батчей (CC-0044 фабрики) — с состоянием: план на N дней, рубильник
// с заметкой и окна каналов. Общий для Vitest (MSW, src/mocks/handlers.ts) и Playwright
// (tests/e2e/fixtures.ts). Тела ответов типизированы сгенерированными типами контракта;
// строки отказов и `why` — как у `shared/batch_schedule.py` / `api/batches.py`. Данные
// выдуманные, но по форме как у живой фабрики. Импорты — относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export type BatchReply<T> =
  { status: 200; body: T } | { status: 404 | 409 | 422 | 500; body: S['BatchProblem'] };

const problem = (
  status: 404 | 409 | 422 | 500,
  code: S['BatchProblem']['code'],
  message: string,
  details: string[] = [],
): BatchReply<never> => ({ status, body: { message, code, details } });

/** «Сейчас» подставной фабрики: 10.10.2026 10:00 МСК. */
export const MOCK_NOW = '2026-10-10T07:00:00Z';
/** День плана (от сегодня), когда батч не нужен никому: 15.10. */
export const ALL_FED_DAY = 5;
/** День плана (от сегодня), когда оба канала на паузе — некого планировать: 16.10 (CC-0147). */
export const PAUSED_DAY = 6;
/** Причина паузы каналов в день PAUSED_DAY — как у `queue().paused` фабрики, выдуманная. */
export const PAUSE_WHY = 'пауза до 17.10 (заметка: «меняю ключи YouTube»)';
const TZ = 'Europe/Moscow';
/** Сутки квоты поиска YouTube (CF-0787): тихоокеанские, сброс в полночь там. */
export const QUOTA_TZ = 'America/Los_Angeles';
/** Сколько дней после дня фабрика ищет следующее окно канала (`NEXT_WINDOW_DAYS`). */
const NEXT_WINDOW_DAYS = 7;
const quotaFmt = new Intl.DateTimeFormat('en-CA', {
  timeZone: QUOTA_TZ,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
});
/** Сутки квоты момента `at` — YYYY-MM-DD по Тихоокеанскому времени. */
export const quotaDayOf = (at: Date | string) => quotaFmt.format(new Date(at));
/** Сутки квоты «сейчас» подставной фабрики: 10.10 (MOCK_NOW — ровно тихоокеанская полночь). */
export const MOCK_QUOTA_DAY = quotaDayOf(MOCK_NOW);
/**
 * День плана (от сегодня), чьи окна попадают в сутки квоты, которые уже взял сегодняшний батч
 * (`quota_day_taken`, `done`, CC-0147): 11.10 — окна 02:00 и 05:30 МСК ещё в сутках квоты 10.10.
 */
export const QUOTA_TAKEN_DAY = 1;
const MSK_OFFSET_H = 3;
const KEYS = [
  'enabled',
  'window',
  'window_hours',
  'min_feed_days',
  'batch_feed_days',
  'windows',
] as const;
type Key = (typeof KEYS)[number];
type Values = {
  enabled: boolean;
  window: string;
  window_hours: number;
  /** CF-0922: горизонт ленты — на сколько дней вперёд ролики встают в слоты. */
  min_feed_days: number;
  /**
   * CF-0922: порог батча — тик запускает батч, когда лента короче. Нет — не задан нигде: в силе
   * {@link BATCH_FEED_DEFAULT}, поднятый до горизонта.
   */
  batch_feed_days?: number;
  /** CF-0830: окна канала в сутках, 1–4 «ЧЧ:ММ»; перекрывают `window`; null — одно окно. */
  windows: string[] | null;
};

const DEFAULTS: Values = {
  enabled: true,
  window: '02:00',
  window_hours: 3,
  min_feed_days: 3,
  windows: null,
};
/** Порог батча фабрики по умолчанию (`batch_schedule.DEFAULTS`, CF-0922): API его не отдаёт. */
export const BATCH_FEED_DEFAULT = 14;
/** Порог батча в силе: свой (канала или пульта), иначе по умолчанию, поднятый до горизонта. */
export const thresholdOf = (v: Pick<Values, 'min_feed_days' | 'batch_feed_days'>) =>
  v.batch_feed_days ?? Math.max(BATCH_FEED_DEFAULT, v.min_feed_days);
/** Окон у канала не больше (`batch_schedule.MAX_WINDOWS`). */
export const MAX_WINDOWS = 4;
/** Бюджет поиска суток квоты (`batch_schedule.QUOTA_BUDGET`, CF-0830). */
export const QUOTA_BUDGET = {
  max_batches: 2,
  margin: 5,
  expected_batches: 3,
  default_searches: 85,
  _note:
    'CF-0830 (21.10, the user: two batches a quota day when the Search budget allows). A channel with `windows` gets a next batch in a quota day that already has one when spent + expected <= limit - margin',
  limit: 100,
};
/** Сутки квоты «сегодня»: батч ExampleFilm 02:05 МСК потратил 82 поиска. */
export const MOCK_SPENT_TODAY = 82;
/** Батч, что держит сегодняшние сутки квоты (и упал под размыкателем в сцене `breaker`). */
export const TODAY_BATCH = 'example-film/2026-10-09T2305Z';
/** Ожидаемый расход поиска на батч канала (`expected_searches`): медиана последних трёх. */
const EXPECTED: Record<string, { searches: number; n: number; batches: number[] }> = {
  'example-film': { searches: 64, n: 3, batches: [58, 64, 71] },
  'example-tech': { searches: 18, n: 3, batches: [15, 18, 22] },
};
/** Окна каналов в сцене бюджета (CC-0152): по два окна у ExampleFilm и ExampleTech. */
export const BUDGET_WINDOWS: Record<string, string[]> = {
  'example-film': ['02:00', '17:00'],
  'example-tech': ['05:30', '17:00'],
};
/** Запись размыкателя повторов (CF-0822) сцены `breaker`: сегодняшний батч упал без трат квоты. */
export const MOCK_BREAKER: S['PlanBreaker'] = {
  channel: 'example-film',
  batch: TODAY_BATCH,
  status: 'failed',
  stage: 'trend-hunter',
  reason: 'handler exit 1 (yt-dlp: HTTP 403 до первого поиска)',
  failure: 'trend-hunter: handler exit 1 (yt-dlp: HTTP 403 до первого поиска)',
  quota_day: '2026-10-10',
  until: '2026-10-11T07:00:00Z',
  held: true,
  code_source: 'RUN_EVENTS.jsonl (batch-start)',
  code_failed: { root: '4f1c2a9', 'agents/trend-hunter': '81d0e3b' },
  code_now: { root: '4f1c2a9', 'agents/trend-hunter': '81d0e3b' },
  code_changed: [],
  line: 'example-film: повтор того же отказа не запущен - батч 2026-10-09T2305Z упал без трат квоты (failed на trend-hunter: handler exit 1 (yt-dlp: HTTP 403 до первого поиска)), код тот же; следующий батч example-film - после сброса квоты 11.10 10:00 МСК, по «запускай» или после смены кода (CF-0822)',
};
const SETTINGS_FILE = 'schedule/channel-settings.json';
const NO_PIPELINE = 'конвейера нет - батча не будет';
/** Как `batch_schedule._channel_state` у канала без `publisher.slot`. */
export const NO_SLOT =
  'нет publisher.slot - у канала нет очереди публикаций (CF-0587), планировать нечего';
const SWITCH_OFF_LINE =
  'переключатель ВЫКЛЮЧЕН (не включался): батчи по расписанию не запускаются, батч - по «запускай» вручную';
export const NOTE_REQUIRED =
  'Чтобы включить расписание, нужна заметка: где и когда пользователь сказал «включай».';
export const TIMER_LINE =
  'таймер тика НЕ установлен (нет /home/factory/Library/LaunchAgents/com.example-film.batch-schedule.plist): батчи по расписанию и удаление API Data по сроку (CF-0618) держатся на ручных запусках - `python3 shared/batch_schedule.py install-timer --print`';

type Channel = {
  id: string;
  /** Блок `batch_schedule` конфига канала (null — блока нет, значения по умолчанию). */
  block: Values | null;
  pipeline: boolean;
  /** Есть `publisher.slot` — у канала есть очередь публикаций. */
  slot: boolean;
  /** Лента сегодня: слоты (18:00 МСК, раз в день) заняты на столько дней от сегодня. */
  feed: number;
  overlay: Partial<Values>;
  est: { wall_s: number; wall_n: number; videos: number; videos_n: number };
  queue: number;
  pending: number;
};

const iso = (d: Date) => d.toISOString().replace('.000Z', 'Z');
const pyRepr = (v: unknown) => (typeof v === 'string' ? `'${v}'` : String(v));

/** Проверка значений пульта — тексты как у `batch_schedule.validate_settings`. */
export function validateSettings(changes: Partial<Record<Key, unknown>>): Partial<Values> {
  const out: Partial<Values> = {};
  const num = (v: unknown, what: string) => {
    if (typeof v === 'boolean') throw new Error(`${what}: a number, not ${v ? 'True' : 'False'}`);
    const x = typeof v === 'number' ? v : Number(String(v).trim().replace(',', '.'));
    if (Number.isNaN(x)) throw new Error(`${what}: не число (${pyRepr(v)})`);
    return x;
  };
  for (const [k, v] of Object.entries(changes)) {
    if (k === 'enabled') {
      if (typeof v !== 'boolean')
        throw new Error(`участие в расписании: ${pyRepr(v)} - да или нет`);
      out.enabled = v;
    } else if (k === 'window') {
      const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(String(v).trim());
      if (!m) throw new Error(`начало окна ${pyRepr(v)}: время ЧЧ:ММ, 00:00-23:59`);
      out.window = `${m[1]}:${m[2]}`;
    } else if (k === 'window_hours') {
      const x = num(v, 'длительность окна');
      if (!(x >= 0.5 && x <= 24)) throw new Error(`длительность окна ${pyRepr(v)}: от 0.5 до 24 ч`);
      if (Math.abs(x * 4 - Math.round(x * 4)) > 1e-9)
        throw new Error(`длительность окна ${pyRepr(v)}: шаг 0.25 ч`);
      out.window_hours = x;
    } else if (k === 'windows') {
      // CF-0830: None/[]/"" — снова одно окно `window`; иначе 1–4 «ЧЧ:ММ», по порядку, без повторов.
      const items = Array.isArray(v)
        ? (v as unknown[])
        : String(v ?? '')
            .trim()
            .split(/[,;\s]+/)
            .filter(Boolean);
      if (!items.length) {
        out.windows = null;
        continue;
      }
      const got = new Set<string>();
      for (const x of items) {
        const m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(String(x).trim());
        if (!m) throw new Error(`окна запуска: ${pyRepr(x)} - время ЧЧ:ММ, 00:00-23:59`);
        got.add(`${m[1]}:${m[2]}`);
      }
      if (got.size > MAX_WINDOWS) throw new Error(`окна запуска: не больше ${MAX_WINDOWS}`);
      out.windows = [...got].sort();
    } else if (k === 'min_feed_days') {
      const x = num(v, 'порог ленты');
      if (x !== Math.trunc(x) || x < 1 || x > 30)
        throw new Error(`порог ленты ${pyRepr(v)}: целое число дней от 1 до 30`);
      out.min_feed_days = x;
    } else if (k === 'batch_feed_days') {
      // CF-0922: не меньше горизонта — проверяет фабрика целиком (window_config), 409.
      const x = num(v, 'порог батча');
      if (x !== Math.trunc(x) || x < 1 || x > 30)
        throw new Error(`порог батча ${pyRepr(v)}: целое число дней от 1 до 30`);
      out.batch_feed_days = x;
    } else {
      throw new Error(`unknown setting '${k}' (only ${KEYS.join(', ')})`);
    }
  }
  return out;
}

/**
 * Подставное расписание: рубильник выключен; ExampleFilm (окно 02:00 + 3 ч) и ExampleTech
 * (05:30 + 3 ч) в расписании, у ExampleScience нет слота публикации — план её не берёт (как у
 * живой фабрики 16.10).
 */
export function createScheduleBackend() {
  const now = new Date(MOCK_NOW);
  const channels: Channel[] = [
    {
      id: 'example-film',
      // CF-0922: порог батча задан в файле канала — 3 дн., как горизонт (неделя плана прежняя).
      block: { ...DEFAULTS, batch_feed_days: 3 },
      pipeline: true,
      slot: true,
      feed: 2,
      overlay: {},
      est: { wall_s: 15_120, wall_n: 5, videos: 3, videos_n: 0 },
      queue: 6,
      pending: 2,
    },
    {
      id: 'example-science',
      block: null,
      pipeline: true,
      slot: false,
      feed: 0,
      overlay: {},
      est: { wall_s: 14_400, wall_n: 0, videos: 3, videos_n: 0 },
      queue: 0,
      pending: 0,
    },
    {
      id: 'example-tech',
      block: { ...DEFAULTS, window: '05:30', batch_feed_days: 3 },
      pipeline: true,
      slot: true,
      feed: 5,
      overlay: {},
      est: { wall_s: 14_400, wall_n: 2, videos: 3, videos_n: 0 },
      queue: 3,
      pending: 1,
    },
  ];
  const sw: { history: S['SwitchRow'][]; on: boolean } = { history: [], on: false };
  /** Идёт батч (день 0 — `busy`, CC-0147): «<канал> <id>»; null — не идёт. */
  let running: { channel: string; id: string } | null = null;
  const settingsHistory: S['SettingsRow'][] = [];
  let staleOpen: string[] = [];
  /**
   * Батч уже был в текущих сутках квоты (день 0 — `done`, `done_today`): сутки квоты 10.10
   * заняты, и окна 11.10 (они ещё в этих сутках) — `quota_day_taken`.
   */
  let doneToday = true;
  const writes: { kind: 'switch' | 'settings'; body: unknown }[] = [];
  /**
   * Сцены CC-0152 (по умолчанию выключены — неделя прежняя): `breaker` — сегодняшний батч
   * ExampleFilm упал без трат квоты, размыкатель держит его повтор (день 11.10); `budget` — у
   * ExampleFilm и ExampleTech по два окна: второй батч дня по бюджету поиска и отказ по бюджету.
   */
  const scene = { breaker: false, budget: false };
  let tick = 0;
  const stamp = () => iso(new Date(now.getTime() + ++tick * 1000));

  const find = (id: string) => channels.find((c) => c.id === id);
  const values = (c: Channel): Values => ({ ...DEFAULTS, ...(c.block ?? {}), ...c.overlay });
  /** Окна канала в сутках: `windows`, иначе одно `window` (CF-0830). */
  const windowsOf = (v: Values) => v.windows ?? [v.window];
  const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

  /** Бюджет поиска сегодняшних суток квоты (`quota_budget(qd)` фабрики). */
  const budgetToday = (): S['QuotaBudgetDay'] => {
    const base = {
      task: 'CF-0830',
      quota_day: MOCK_QUOTA_DAY,
      limit: QUOTA_BUDGET.limit,
      margin: QUOTA_BUDGET.margin,
      max_batches: QUOTA_BUDGET.max_batches,
    };
    if (running) {
      // Идущий батч расход ещё не записал: в «потрачено» — его ожидаемый расход.
      const exp = expectedOf(running.channel).searches;
      return {
        ...base,
        batches: 1,
        spent: exp,
        spent_recorded: 0,
        unrecorded: [
          { batch: `${running.channel}/${running.id}`, channel: running.channel, expected: exp },
        ],
        left: QUOTA_BUDGET.limit - exp,
        held: [`${running.channel} ${running.id} (pipeline/runs.jsonl)`],
      };
    }
    if (!doneToday && !scene.breaker)
      return {
        ...base,
        batches: 0,
        spent: 0,
        spent_recorded: 0,
        unrecorded: [],
        left: 100,
        held: [],
      };
    // Сцена размыкателя: батч упал до первого поиска — квота не потрачена.
    const spent = scene.breaker ? 0 : MOCK_SPENT_TODAY;
    return {
      ...base,
      batches: 1,
      spent,
      spent_recorded: spent,
      unrecorded: [],
      left: QUOTA_BUDGET.limit - spent,
      // Как у фабрики: строка папки батча и строка журнала запусков того же батча (CC-0157).
      held: [
        `${TODAY_BATCH.replace('/', ' ')} (pipeline/runs.jsonl)`,
        'example-film запущен тиком 2026-10-09T23:05:02Z (schedule/launches.jsonl)',
      ],
    };
  };

  /** Запись допуска (`admission` фабрики) следующего батча канала в сутки квоты `qd`. */
  const admission = (a: {
    channel: string;
    qd: string;
    windowStart: Date;
    start: Date;
    windowEnd: Date;
    spent: number;
    batches: number;
    planned: number;
    booked: number;
  }): S['BudgetAdmission'] => {
    const { limit, margin, max_batches: cap } = QUOTA_BUDGET;
    const e = expectedOf(a.channel);
    const count = a.batches + a.booked;
    const spent = a.spent + a.planned;
    const after = spent + e.searches;
    const nth = count + 1;
    const span = `сутки квоты YouTube ${a.qd.slice(8, 10)}.${a.qd.slice(5, 7)}`;
    const sums =
      `потрачено ${spent}` +
      (a.planned ? ` (из них по плану ${a.planned})` : '') +
      ` + ожидается ${e.searches} (${a.channel}: ${e.line}) = ${after}`;
    const reason: S['BudgetAdmission']['reason'] =
      count >= cap
        ? 'max_batches'
        : after > limit - margin
          ? 'budget'
          : a.start >= a.windowEnd
            ? 'busy'
            : 'ok';
    const why = {
      max_batches: `${nth}-й батч в ${span} не допущен: потолок ${cap} батча в сутки квоты уже набран (${count})`,
      budget: `${nth}-й батч в ${span} не допущен по бюджету поиска: ${sums} > ${limit - margin} (${limit} − запас ${margin}); остаток ${limit - spent}`,
      busy: `${nth}-й батч в ${span} не допущен: окно ${fmt(a.windowStart)} проходит, пока идёт батч плана (конец ~${fmt(a.start)})`,
      ok: `${nth}-й батч в ${span} допущен по бюджету поиска: ${sums} ≤ ${limit - margin} (${limit} − запас ${margin})`,
    }[reason];
    return {
      task: 'CF-0830',
      channel: a.channel,
      quota_day: a.qd,
      window_start: iso(a.windowStart),
      start: iso(a.start),
      nth,
      batches: count,
      max_batches: cap,
      limit,
      margin,
      spent,
      spent_recorded: a.spent,
      spent_unrecorded: 0,
      spent_planned: a.planned,
      expected: e.searches,
      expected_n: e.n,
      expected_line: e.line,
      after,
      left: limit - spent,
      admitted: reason === 'ok',
      reason,
      why,
    };
  };
  const sourceOf = (c: Channel) => {
    const base = c.block ? `channels/${c.id}.json batch_schedule` : 'по умолчанию';
    const mine = Object.keys(c.overlay).sort();
    return mine.length ? `${base} + пульт (${SETTINGS_FILE}: ${mine.join(', ')})` : base;
  };
  const settingsOf = (c: Channel): S['ScheduleSettings'] => ({
    ...values(c),
    // CF-0922: всегда порог в силе; задан ли — по `overlay` и `source`.
    batch_feed_days: thresholdOf(values(c)),
    // С `windows` фабрика отдаёт первым окном `window` (CF-0830).
    window: windowsOf(values(c))[0]!,
    tz: TZ,
    source: sourceOf(c),
    overlay: { ...c.overlay },
  });

  const switchOf = (): S['Switch'] => {
    const last = sw.history.at(-1);
    if (!last) return { on: false, line: SWITCH_OFF_LINE, history: [] };
    const who = `${last.by} ${last.at}${last.note ? ` - ${last.note}` : ''}`;
    return {
      on: sw.on,
      line: sw.on
        ? `переключатель ВКЛЮЧЁН (${who}): тик запускает батч дня по плану`
        : `переключатель ВЫКЛЮЧЕН (${who}): батчи по расписанию не запускаются, батч - по «запускай» вручную`,
      since: last.at ?? null,
      by: last.by ?? null,
      note: last.note ?? null,
      history: [...sw.history],
    };
  };

  const whyNot = (c: Channel): string | null => {
    if (!c.pipeline) return NO_PIPELINE;
    if (!c.slot) return NO_SLOT;
    if (!values(c).enabled)
      return `не участвует в расписании (${sourceOf(c)}) - батч только вручную`;
    return null;
  };

  const expectedOf = (id: string): S['ExpectedSearches'] => {
    const e = EXPECTED[id];
    if (!e)
      return {
        channel: id,
        searches: QUOTA_BUDGET.default_searches,
        n: 0,
        batches: [],
        source: 'default',
        line: `${QUOTA_BUDGET.default_searches} (по умолчанию: батчей с записанным расходом поиска ещё нет)`,
      };
    return {
      channel: id,
      searches: e.searches,
      n: e.n,
      batches: e.batches.map((n, i) => ({ batch: `${id}/2026-10-0${7 + i}T0200Z`, searches: n })),
      source: 'median',
      line: `${e.searches} (медиана ${e.n} последн. батчей: ${e.batches.join(', ')})`,
    };
  };
  const breakerOf = (id: string) =>
    scene.breaker && id === MOCK_BREAKER.channel ? { ...MOCK_BREAKER } : null;

  const channelOut = (c: Channel): S['PlanChannel'] => {
    const why = whyNot(c);
    if (why)
      return {
        plannable: false,
        why_not: why,
        no_pipeline: !c.pipeline,
        settings: settingsOf(c),
        breaker: breakerOf(c.id),
      };
    const v = values(c);
    return {
      plannable: true,
      slot_rule: '1/день в 18:00 Europe/Moscow',
      window: `${windowsOf(v).join(', ')} ${TZ} + ${v.window_hours} ч`,
      windows: v.windows,
      expected_searches: expectedOf(c.id),
      breaker: breakerOf(c.id),
      window_source: sourceOf(c),
      min_feed_days: v.min_feed_days,
      batch_feed_days: thresholdOf(v),
      est_wall_s: c.est.wall_s,
      est_wall_n: c.est.wall_n,
      est_videos: c.est.videos,
      est_videos_n: c.est.videos_n,
      queue: c.queue,
      pending: c.pending,
      open: [],
      settings: settingsOf(c),
    };
  };

  /** Окно канала в день `day` (YYYY-MM-DD), UTC. */
  const windowOn = (day: string, v: Values, at: string = windowsOf(v)[0]!) => {
    const [h, m] = at.split(':').map(Number) as [number, number];
    const start = new Date(`${day}T00:00:00Z`);
    start.setUTCHours(h - MSK_OFFSET_H, m);
    return { start, end: new Date(start.getTime() + v.window_hours * 3_600_000) };
  };
  const fmt = (d: Date) => {
    const msk = new Date(d.getTime() + MSK_OFFSET_H * 3_600_000);
    const p = (n: number) => String(n).padStart(2, '0');
    return `${p(msk.getUTCDate())}.${p(msk.getUTCMonth() + 1)} ${p(msk.getUTCHours())}:${p(msk.getUTCMinutes())} МСК`;
  };

  const plan = (days: number): S['SchedulePlan'] => {
    const today = MOCK_NOW.slice(0, 10);
    const out: S['PlanDay'][] = [];
    // Ленты каналов по дням (CC-0147): слот — 18:00 МСК раз в день, занятые — московские дни.
    // Сегодня у ExampleFilm заняты 2 дня, у ExampleTech — 4; батч дня занимает слоты с первого
    // свободного после своего конца + час, и следующий день видит ленту уже с ними. Так день
    // ALL_FED_DAY выходит «батч не нужен» сам (CC-0146), а батчи соседних дней не делят слоты.
    const addDays = (day: string, n: number) => {
      const t = new Date(`${day}T00:00:00Z`);
      t.setUTCDate(t.getUTCDate() + n);
      return t.toISOString().slice(0, 10);
    };
    const slotAt = (day: string) => new Date(`${day}T${String(18 - MSK_OFFSET_H)}:00:00Z`);
    const mskDay = (at: Date) =>
      iso(new Date(at.getTime() + MSK_OFFSET_H * 3_600_000)).slice(0, 10);
    const taken = new Map(
      channels.map((c) => [
        c.id,
        new Set(Array.from({ length: c.feed }, (_, k) => addDays(today, k))),
      ]),
    );
    /** Первый свободный слот канала не раньше `at` (горизонт — 120 дней). */
    const freeFrom = (id: string, at: Date) => {
      for (let day = mskDay(at), k = 0; k < 120; day = addDays(day, 1), k++)
        if (slotAt(day) >= at && !taken.get(id)!.has(day)) return day;
      return null;
    };
    /** Сутки квоты с батчем: `batch` — батч фабрики уже был, `plan` — его берёт день плана. */
    const held = new Map<string, 'batch' | 'plan'>();
    // Сцена размыкателя: сегодняшний батч упал без трат квоты — сутки квоты им не заняты.
    if (doneToday && !running && !scene.breaker) held.set(MOCK_QUOTA_DAY, 'batch');
    /** Второй батч дня по бюджету (сцена `budget`) — один раз, в первый день с батчем ExampleFilm. */
    let moreDone = false;
    for (let i = 0; i < days; i++) {
      const d = new Date(`${today}T00:00:00Z`);
      d.setUTCDate(d.getUTCDate() + i);
      const day = d.toISOString().slice(0, 10);
      if (i === 0 && running) {
        out.push({
          day,
          channel: running.channel,
          status: 'busy',
          kind: 'running',
          quota_day: null,
          next_windows: {},
          covers_days: [],
          first_empty_slot: null,
          why: `день занят: идёт батч ${running.channel} ${running.id} - второй не запускается (runlog batch-active)`,
          notes: [],
        });
        continue;
      }
      if (i === 0 && doneToday && !scene.breaker) {
        // Сцена бюджета: второе окно ExampleFilm сегодня (17:00) — по бюджету не допущено.
        const reel = find('example-film')!;
        const second = values(reel).windows?.[1];
        const w = second ? windowOn(day, values(reel), second) : null;
        const budget =
          scene.budget && w
            ? [
                admission({
                  channel: reel.id,
                  qd: MOCK_QUOTA_DAY,
                  windowStart: w.start,
                  start: w.start,
                  windowEnd: w.end,
                  spent: MOCK_SPENT_TODAY,
                  batches: 1,
                  planned: 0,
                  booked: 0,
                }),
              ]
            : [];
        out.push({
          ...(budget.length ? { budget } : {}),
          day,
          channel: 'example-film',
          status: 'done',
          kind: 'done_today',
          quota_day: MOCK_QUOTA_DAY,
          next_windows: {},
          covers_days: [],
          first_empty_slot: null,
          why: `сутки квоты ${MOCK_QUOTA_DAY} уже с батчем: example-film 2026-10-09T2305Z - 1 батч в сутки квоты YouTube Search на фабрику`,
          notes: [],
        });
        continue;
      }
      const notes: string[] = [];
      /** Каналы, которым батч нужен, но окно — в уже занятых сутках квоты. */
      const blocked: { c: Channel; start: Date; q: string }[] = [];
      /** Повтор упавшего батча, который держит размыкатель (CF-0822, сцена `breaker`). */
      const repeat: { c: Channel; start: Date; end: Date }[] = [];
      const cands: {
        c: Channel;
        start: Date;
        end: Date;
        cov: number;
        need: boolean;
        fe: string | null;
      }[] = [];
      for (const c of channels) {
        if (whyNot(c)) continue;
        const v = values(c);
        const { start, end } = windowOn(day, v);
        if (end <= now) {
          notes.push(`${c.id}: окно ${fmt(start)} сегодня прошло`);
          continue;
        }
        if (i === PAUSED_DAY) {
          notes.push(`${c.id}: на паузе - ${PAUSE_WHY}`);
          continue;
        }
        const fe = freeFrom(c.id, start);
        let cov = 0;
        for (const t of taken.get(c.id)!) if (slotAt(t) >= start && (!fe || t < fe)) cov++;
        const need = cov < thresholdOf(v); // CF-0922: порог батча, не горизонт
        const q = quotaDayOf(start > now ? start : now);
        if (need && scene.breaker && c.id === MOCK_BREAKER.channel && q === MOCK_QUOTA_DAY) {
          notes.push(MOCK_BREAKER.line!);
          repeat.push({ c, start, end });
          continue;
        }
        if (need && held.has(q)) {
          blocked.push({ c, start, q });
          continue;
        }
        cands.push({ c, start, end, cov, need, fe });
        if (!need)
          notes.push(
            `${c.id}: лента на ${cov} дн. вперёд (≥ порога батча ${thresholdOf(v)})` +
              (fe ? `, пусто ${fmt(slotAt(fe))}` : '') +
              ' - батч не нужен',
          );
      }
      // День — каналу с самым ранним пустым слотом; поровну — по алфавиту канала.
      const x = cands
        .filter((y) => y.need)
        .sort(
          (a, b) => (a.fe ?? '~').localeCompare(b.fe ?? '~') || a.c.id.localeCompare(b.c.id),
        )[0];
      if (!x && repeat.length && !blocked.length) {
        // День под размыкателем: kind остаётся `nobody_available`, рядом — запись `breaker`.
        const b = repeat[0]!;
        const next = (c: Channel) => {
          for (let k = 1; k <= NEXT_WINDOW_DAYS; k++) {
            const w = windowOn(addDays(day, k), values(c));
            const q = quotaDayOf(w.start);
            if (q !== MOCK_QUOTA_DAY && !held.has(q)) return iso(w.start);
          }
          return null;
        };
        out.push({
          day,
          channel: null,
          status: 'idle',
          kind: 'nobody_available',
          quota_day: null,
          window_start: iso(b.start),
          window_end: iso(b.end),
          breaker: { ...MOCK_BREAKER },
          next_windows: Object.fromEntries(repeat.map((y) => [y.c.id, next(y.c)])),
          covers_days: [],
          first_empty_slot: null,
          why: `некого планировать: ${notes.join('; ')}`,
          notes,
        });
        continue;
      }
      if (!x && blocked.length) {
        // Все окна дня, кому нужен батч, — в сутках квоты с батчем (CF-0787): `done` — его взял
        // батч фабрики, `idle` — более ранний день этого плана. Следующее окно — первое после
        // дня в свободных сутках квоты, не дальше NEXT_WINDOW_DAYS.
        const first = [...blocked].sort((a, b) => a.start.getTime() - b.start.getTime())[0]!;
        const next = (c: Channel) => {
          for (let k = 1; k <= NEXT_WINDOW_DAYS; k++) {
            const w = windowOn(addDays(day, k), values(c));
            if (!held.has(quotaDayOf(w.start))) return iso(w.start);
          }
          return null;
        };
        out.push({
          day,
          channel: null,
          status: held.get(first.q) === 'batch' ? 'done' : 'idle',
          kind: 'quota_day_taken',
          quota_day: first.q,
          next_windows: Object.fromEntries(blocked.map((b) => [b.c.id, next(b.c)])),
          covers_days: [],
          first_empty_slot: null,
          why:
            `сутки квоты ${first.q} уже с батчем` +
            (held.get(first.q) === 'batch' ? '' : ' (день плана раньше)') +
            `: ${blocked.map((b) => `${b.c.id} окно ${fmt(b.start)}`).join('; ')} - батч не запускается`,
          notes,
        });
        continue;
      }
      if (!x) {
        out.push({
          day,
          channel: null,
          status: 'idle',
          kind: !cands.length ? (notes.length ? 'nobody_available' : 'nobody_plannable') : 'fed',
          quota_day: null,
          next_windows: {},
          covers_days: [],
          first_empty_slot: null,
          why: !cands.length
            ? notes.length
              ? `некого планировать: ${notes.join('; ')}`
              : 'некого планировать: ни у одного канала нет слота и run_plan'
            : 'батч не нужен: у всех каналов лента не короче порога батча',
          notes,
        });
        continue;
      }
      const start = x.start > now ? x.start : now;
      const end = new Date(start.getTime() + x.c.est.wall_s * 1000);
      // Первый пустой слот ленты (`first_empty_slot`); батч заполняет свободные слоты с первого
      // после своего конца + час на выкладку (`fills`, как у фабрики: бывает позже пустого слота,
      // CC-0147) и занимает их — следующий день видит ленту уже с ними. `covers_days` — их дни.
      const empty = x.fe ? slotAt(x.fe) : null;
      const covers: string[] = [];
      for (let k = 0; k < x.c.est.videos; k++) {
        const f = freeFrom(x.c.id, new Date(end.getTime() + 3_600_000));
        if (!f) break;
        taken.get(x.c.id)!.add(f);
        covers.push(f);
      }
      const fills = covers.map((f) => iso(slotAt(f)));
      const q = quotaDayOf(start);
      held.set(q, 'plan');
      // Сцена бюджета (CF-0830): после батча ExampleFilm — батч ExampleTech во втором окне тех же
      // суток квоты, допущенный по бюджету поиска.
      const more: S['PlanMoreBatch'][] = [];
      const tech = find('example-tech')!;
      if (scene.budget && !moreDone && x.c.id === 'example-film' && values(tech).windows) {
        moreDone = true;
        const w = windowOn(day, values(tech));
        const at = end > w.start ? end : w.start;
        const a = admission({
          channel: tech.id,
          qd: q,
          windowStart: w.start,
          start: at,
          windowEnd: w.end,
          spent: 0,
          batches: 0,
          planned: expectedOf(x.c.id).searches,
          booked: 1,
        });
        const fin = new Date(at.getTime() + tech.est.wall_s * 1000);
        const cov: string[] = [];
        for (let k = 0; k < tech.est.videos; k++) {
          const f = freeFrom(tech.id, new Date(fin.getTime() + 3_600_000));
          if (!f) break;
          taken.get(tech.id)!.add(f);
          cov.push(f);
        }
        more.push({
          channel: tech.id,
          status: 'planned',
          kind: 'needs_batch',
          why: `второй батч ${fmt(w.start)}: ${a.why}`,
          window_start: iso(w.start),
          window_end: iso(w.end),
          quota_day: q,
          est_end: iso(fin),
          est_wall_s: tech.est.wall_s,
          est_wall_n: tech.est.wall_n,
          est_videos: tech.est.videos,
          est_videos_n: tech.est.videos_n,
          fills: cov.map((f) => iso(slotAt(f))),
          covers_days: cov,
          first_empty_slot: null,
          budget_admission: a,
        });
      }
      out.push({
        ...(more.length ? { more, budget: more.map((m) => m.budget_admission!) } : {}),
        day,
        channel: x.c.id,
        status: 'planned',
        kind: 'needs_batch',
        quota_day: q,
        next_windows: {},
        first_empty_slot: empty ? iso(empty) : null,
        covers_days: covers,
        why:
          `лента короче ${thresholdOf(values(x.c))} дн. (на ${x.cov} дн.)` +
          (empty ? `: пусто ${fmt(empty)}` : ''),
        notes,
        window_start: iso(x.start),
        window_end: iso(x.end),
        est_end: iso(end),
        est_wall_s: x.c.est.wall_s,
        est_wall_n: x.c.est.wall_n,
        est_videos: x.c.est.videos,
        est_videos_n: x.c.est.videos_n,
        fills,
      });
    }
    return {
      now: MOCK_NOW,
      today,
      quota_day: MOCK_QUOTA_DAY,
      quota_tz: QUOTA_TZ,
      per_day: 1,
      switch: switchOf(),
      stale_open: [...staleOpen],
      breakers: scene.breaker ? { [MOCK_BREAKER.channel]: { ...MOCK_BREAKER } } : {},
      quota_budget: {
        ...QUOTA_BUDGET,
        today: budgetToday(),
        windows_channels: channels.filter((c) => !whyNot(c) && values(c).windows).map((c) => c.id),
      },
      channels: Object.fromEntries(channels.map((c) => [c.id, channelOut(c)])),
      days: out,
      timer: TIMER_LINE,
    };
  };

  return {
    writes,
    /** Открытые батчи старше потолка свежести — «<канал> <id>». */
    setStaleOpen(list: string[]) {
      staleOpen = list;
    },
    /**
     * Сцены CC-0152: `breaker` — размыкатель держит повтор ExampleFilm; `budget` — по два окна у
     * ExampleFilm и ExampleTech (в конфиге канала): второй батч дня и отказ по бюджету.
     */
    setScene(next: Partial<typeof scene>) {
      Object.assign(scene, next);
      for (const c of channels) {
        if (!c.block || !BUDGET_WINDOWS[c.id]) continue;
        c.block = { ...c.block, windows: scene.budget ? [...BUDGET_WINDOWS[c.id]!] : null };
      }
    },
    setDoneToday(v: boolean) {
      doneToday = v;
    },
    /** Идёт батч канала (день 0 — `busy`, `running`); null — не идёт. */
    setRunning(v: { channel: string; id: string } | null) {
      running = v;
    },
    plan(days = 7): BatchReply<S['SchedulePlan']> {
      if (!Number.isInteger(days) || days < 1 || days > 31)
        return problem(422, 'invalid', 'days: от 1 до 31', [`days=${days}`]);
      return { status: 200, body: plan(days) };
    },
    setSwitch(body: Partial<S['SwitchIn']>): BatchReply<S['Switch']> {
      const on = body.on === true;
      if (on && !(body.note ?? '').trim())
        return problem(422, 'note_required', NOTE_REQUIRED, [
          'set_switch(on=True) needs a note (ENABLE_BY: user)',
        ]);
      writes.push({ kind: 'switch', body });
      const note = (body.note ?? '').trim();
      sw.on = on;
      sw.history.push({
        at: stamp(),
        by: 'user',
        action: on ? 'enable' : 'disable',
        note: note ? `центр: ${note}` : 'центр',
        task: 'CF-0592',
      });
      return { status: 200, body: switchOf() };
    },
    channel(id: string): BatchReply<S['ChannelSchedule']> {
      const c = find(id);
      if (!c)
        return problem(404, 'unknown_channel', `Канала «${id}» нет в фабрике.`, [
          `no channels/${id}.json`,
        ]);
      return {
        status: 200,
        body: {
          channel: c.id,
          settings: settingsOf(c),
          history: settingsHistory.filter((r) => r.channel === c.id),
        },
      };
    },
    save(id: string, body: Partial<S['ScheduleSettingsEdit']>): BatchReply<S['SettingsResult']> {
      const c = find(id);
      if (!c)
        return problem(404, 'unknown_channel', `Канала «${id}» нет в фабрике.`, [
          `no channels/${id}.json`,
        ]);
      const asked: Partial<Record<Key, unknown>> = {};
      for (const k of KEYS) if (body[k] != null) asked[k] = body[k];
      // CC-0152: явный null у `windows` API превращает в [] — снять окна; [] — тоже снять.
      if ('windows' in body && body.windows == null) asked.windows = [];
      if (asked.windows !== undefined) {
        // Своя проверка API до фабрики (`api/batches.py` `_windows`).
        const w = asked.windows;
        if (!Array.isArray(w))
          return problem(
            422,
            'invalid',
            'Настройка не принята: окна запуска - список времён ЧЧ:ММ.',
            [`windows ${pyRepr(w)}: not a list`],
          );
        if (w.length > MAX_WINDOWS)
          return problem(
            422,
            'invalid',
            `Настройка не принята: окна запуска - не больше ${MAX_WINDOWS}.`,
            [`windows: ${w.length} values, at most ${MAX_WINDOWS}`],
          );
        for (const x of w)
          if (typeof x !== 'string' || !/^([01]\d|2[0-3]):([0-5]\d)$/.test(x.trim()))
            return problem(
              422,
              'invalid',
              `Настройка не принята: окна запуска: ${pyRepr(x)} - время ЧЧ:ММ, 00:00-23:59.`,
              [`windows ${pyRepr(x)}: not HH:MM (00:00-23:59)`],
            );
      }
      let fresh: Partial<Values>;
      try {
        fresh = validateSettings(asked);
      } catch (e) {
        const msg = (e as Error).message;
        return problem(422, 'invalid', `Настройка не принята: ${msg}`, [msg]);
      }
      // Сравнение — со значениями в силе (порог батча — в силе, CF-0922).
      const before = { ...values(c), batch_feed_days: thresholdOf(values(c)) };
      const changed: Record<string, unknown[]> = {};
      for (const k of KEYS) {
        if (fresh[k] === undefined || same(fresh[k], before[k])) continue;
        changed[k] = [before[k], fresh[k]];
      }
      if (Object.keys(changed).length) {
        // Пульт держит только то, что отличается от файла канала (порог — с файла в силе).
        const raw = { ...DEFAULTS, ...(c.block ?? {}) };
        const base = { ...raw, batch_feed_days: thresholdOf(raw) };
        const next = { ...c.overlay, ...fresh };
        const overlay = Object.fromEntries(
          Object.entries(next).filter(([k, v]) => !same(base[k as Key], v)),
        ) as Partial<Values>;
        // Целиком, до записи (`window_config`): порог батча не меньше горизонта ленты (CF-0922).
        const trial: Values = { ...raw, ...overlay };
        if (trial.batch_feed_days != null && trial.batch_feed_days < trial.min_feed_days) {
          const [b, m] = [trial.batch_feed_days, trial.min_feed_days];
          return problem(
            409,
            'refused',
            `Фабрика не приняла настройки расписания канала ${c.id}: порог батча не меньше горизонта ленты - порог батча ${b} дн., горизонт ленты ${m} дн.`,
            [
              `${SETTINGS_FILE}: ${c.id} / channels/${c.id}.json: batch_schedule.batch_feed_days ${b} < min_feed_days ${m}: порог батча не меньше горизонта ленты (CF-0922)`,
            ],
          );
        }
        writes.push({ kind: 'settings', body });
        c.overlay = overlay;
        const note = (body.note ?? '').trim();
        settingsHistory.unshift({
          at: stamp(),
          by: 'user',
          channel: c.id,
          changes: changed,
          note: note ? `центр: ${note}` : 'центр',
          task: 'CF-0605',
        });
      }
      return {
        status: 200,
        body: {
          channel: c.id,
          changed,
          settings: settingsOf(c),
          history: settingsHistory.filter((r) => r.channel === c.id),
        },
      };
    },
  };
}

export type ScheduleBackend = ReturnType<typeof createScheduleBackend>;

/** Маршрутизация `/api/schedule*`; null — не этот адрес или метод. */
export function routeSchedule(
  backend: ScheduleBackend,
  method: string,
  url: URL,
  body: unknown,
): BatchReply<unknown> | null {
  const m = url.pathname.match(/\/api\/schedule(?:\/(switch)|\/channels\/([^/]+))?$/);
  if (!m) return null;
  const [, sw, raw] = m;
  if (sw) return method === 'POST' ? backend.setSwitch((body ?? {}) as S['SwitchIn']) : null;
  if (raw) {
    const id = decodeURIComponent(raw);
    if (method === 'GET') return backend.channel(id);
    if (method === 'PUT') return backend.save(id, (body ?? {}) as S['ScheduleSettingsEdit']);
    return null;
  }
  if (method !== 'GET') return null;
  return backend.plan(Number(url.searchParams.get('days') ?? 7));
}
