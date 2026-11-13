// Подставные данные «Уведомлений и напоминаний» (CC-0026 фабрики, договор 0.27.0): журнал
// `notify/sent.jsonl` (23 строки, новые в конце; у Telegram — одна ошибка и одна строка «пропущено»;
// CC-0188: `upload` — только журнал, `uploaded` и `accepted`, у `accepted` — многострочный `body`),
// очередь напоминаний `notify/reminders.jsonl` (ждут, не дошло — ещё попытка, попытки кончились,
// отправлено, отменено) и вывод сухой проверки `notify.py test` — строки CLI как напечатаны.
// Часы фабрики — `NOTIFY_NOW` (12 октября 2026, 18:40 МСК). Импорты — относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export const NOTIFY_NOW = '2026-10-12T15:40:00Z';

export const KINDS = [
  'accept',
  'upload',
  'token',
  'empty_slot',
  'run_halted',
  'run_done',
  'needs_human',
  'batch_started',
  'reminder',
  'test',
  'request_answer',
  'hold_released',
  'accepted',
  'uploaded',
] as const;

/** Попыток доставки напоминания, после них — `exhausted` (REMINDER_MAX_ATTEMPTS). */
export const MAX_ATTEMPTS = 8;

const OK = { log: 'ok', telegram: 'ok' };
const DASH = 'http://127.0.0.1:8790/';

const ev = (
  at: string,
  kind: string,
  channel: string | null,
  key: string,
  text: string,
  link: string | null = DASH,
  backends: Record<string, string> = OK,
): S['NotifyEvent'] => ({ at, kind, channel, key, text, link, backends });

/** Обычные дни: батч запущен → закончен → ролики ждут «да» (по три на день, 5–8 октября). */
function routine(): S['NotifyEvent'][] {
  const out: S['NotifyEvent'][] = [];
  const days = ['2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08'];
  const chans = ['example-film', 'example-tech', 'example-science', 'example-film'];
  days.forEach((d, i) => {
    const c = chans[i]!;
    const id = `${d}T0200Z`;
    out.push(
      ev(`${d}T02:00:04Z`, 'batch_started', c, `batch:${c}/${id}:started`, `Батч ${c} начался`),
      ev(
        `${d}T03:12:40Z`,
        'run_done',
        c,
        `run:${c}/${id}:done`,
        `Батч ${c} закончен: 3 ролика готовы`,
        `${DASH}#batches`,
      ),
      ev(
        `${d}T03:12:44Z`,
        'accept',
        c,
        `accept:${c}/${id}`,
        `3 ролика ${c} ждут вашего «да»`,
        `${DASH}#videos`,
      ),
    );
  });
  return out;
}

export const JOURNAL: S['NotifyEvent'][] = [
  ...routine(),
  ev(
    '2026-10-09T02:00:03Z',
    'batch_started',
    'example-tech',
    'batch:example-tech/2026-10-09T0200Z:started',
    'Батч example-tech начался',
  ),
  ev(
    '2026-10-09T02:41:17Z',
    'run_halted',
    'example-tech',
    'run:example-tech/2026-10-09T0200Z:halted',
    'Батч example-tech остановился на стадии footage: не хватило футажа на сцену 4',
    `${DASH}#batches`,
    { log: 'ok', telegram: 'error: HTTP 502 Bad Gateway' },
  ),
  ev(
    '2026-10-09T09:00:00Z',
    'token',
    null,
    'token:youtube:7d',
    'Токен YouTube истекает через 7 дней — переразрешите заранее',
    'docs/youtube-oauth.md',
  ),
  ev(
    '2026-10-10T18:00:00Z',
    'empty_slot',
    'example-science',
    'slot:example-science:2026-10-11',
    'Завтра у example-science пустой слот публикации',
    `${DASH}#publishing`,
    { log: 'ok', telegram: 'skipped: NOTIFY_TELEGRAM_CHAT is not set' },
  ),
  ev(
    '2026-10-11T07:00:00Z',
    'reminder',
    null,
    'reminder:R1',
    'Проверить вкладку «Авторские права» в Studio',
    null,
  ),
  ev(
    '2026-10-11T10:22:31Z',
    'upload',
    'example-film',
    'upload:example-film/2026-10-08T0200Z/a2',
    'Файл для Studio готов: «Арракис за 60 секунд» — перетащите его в Studio',
    'pipeline/example-film/2026-10-08T0200Z/final/a2.mp4',
    { log: 'ok' },
  ),
  {
    ...ev(
      '2026-10-11T10:40:12Z',
      'uploaded',
      'example-film',
      'uploaded:example-film/2026-10-08T0200Z/a2',
      'Залито в Studio: «Арракис за 60 секунд» — выйдет 13 октября в 18:00 МСК',
      `${DASH}#publishing`,
    ),
    publish_at: '2026-10-13T15:00:00Z',
  },
  ev(
    '2026-10-11T14:03:09Z',
    'request_answer',
    null,
    'request:Q-17:answer',
    'Оператор ответил на вашу просьбу «поменять музыку в ролике про Песчаный шторм»',
    `${DASH}#questions`,
  ),
  {
    ...ev(
      '2026-10-12T03:20:05Z',
      'accepted',
      'example-tech',
      'accepted:example-tech/2026-10-12T0200Z',
      'Приёмка батча example-tech: 2 ролика из 3 приняты',
      `${DASH}#videos`,
    ),
    body: [
      'Приёмка example-tech · 12.10',
      'Принято: 2 из 3',
      '  • «Чип за 60 секунд» — принят',
      '  • «Почему SSD стареют» — принят',
      '  • «Квантовый ноутбук» — не принят: голос обрезан на сцене 3',
    ].join('\n'),
  },
  ev(
    '2026-10-12T08:30:00Z',
    'needs_human',
    'example-tech',
    'needs:example-tech:rotation',
    'Фабрике нужен человек: ротация example-tech исчерпала пары',
    `${DASH}#channels`,
  ),
  ev(
    '2026-10-12T12:15:42Z',
    'test',
    null,
    'test',
    'пробное сообщение фабрики (12.10 15:15): уведомления доходят',
    DASH,
  ),
];

const rem = (r: Partial<S['NotifyReminder']> & Pick<S['NotifyReminder'], 'id' | 'due'>) =>
  ({
    text: null,
    created: null,
    by: 'user',
    status: 'pending',
    sent_at: null,
    cancelled_at: null,
    backends: null,
    attempts: 0,
    last_try: null,
    reason: null,
    ...r,
    due_msk: '',
  }) as S['NotifyReminder'];

/** Очередь напоминаний — oldest first (порядок добавления). `due_msk` проставляет бэкенд. */
export const REMINDERS: S['NotifyReminder'][] = [
  rem({
    id: 'R1',
    due: '2026-10-11T07:00:00Z',
    text: 'Проверить вкладку «Авторские права» в Studio',
    created: '2026-10-10T19:12:00Z',
    status: 'sent',
    sent_at: '2026-10-11T07:00:00Z',
    backends: { log: 'ok', telegram: 'ok' },
    attempts: 1,
    last_try: '2026-10-11T07:00:00Z',
  }),
  rem({
    id: 'R2',
    due: '2026-10-11T16:00:00Z',
    text: 'Посмотреть ролики Science перед выходными',
    created: '2026-10-10T19:20:00Z',
    status: 'cancelled',
    cancelled_at: '2026-10-11T09:02:00Z',
  }),
  rem({
    id: 'R3',
    due: '2026-10-12T11:00:00Z',
    text: 'Ответить на вопрос фабрики про пары ротации Tech',
    created: '2026-10-12T06:40:00Z',
    status: 'failed',
    backends: { log: 'ok', telegram: 'error: HTTP 502 Bad Gateway' },
    attempts: 2,
    last_try: '2026-10-12T11:05:00Z',
    reason: 'telegram: error: HTTP 502 Bad Gateway',
  }),
  rem({
    id: 'R4',
    due: '2026-10-11T18:00:00Z',
    text: 'Переразрешить токен YouTube',
    created: '2026-10-09T09:05:00Z',
    status: 'exhausted',
    backends: { log: 'ok', telegram: 'error: Unauthorized (bot token is invalid)' },
    attempts: MAX_ATTEMPTS,
    last_try: '2026-10-12T01:40:00Z',
    reason: 'telegram: error: Unauthorized (bot token is invalid)',
  }),
  rem({
    id: 'R5',
    due: '2026-10-12T18:00:00Z',
    text: 'Принять ролики Reel до вечерней публикации',
    created: '2026-10-12T09:15:00Z',
  }),
  rem({
    id: 'R6',
    due: '2026-10-13T07:00:00Z',
    text: 'Внести цифры Studio по роликам Tech за неделю',
    created: '2026-10-12T12:20:00Z',
  }),
];

/** Вывод сухой `notify.py test`, как напечатан: журнал, включённые, что получил бы каждый. */
export const CHECK: S['NotifyCheck'] = {
  backends: ['log', 'macos', 'telegram'],
  default: ['log'],
  external: ['telegram'],
  lines: [
    'journal: notify/sent.jsonl',
    'backends on: log, macos, telegram (NOTIFY_BACKENDS; default log)',
    "  log: would get 'проверка уведомлений фабрики -> http://127.0.0.1:8790/'",
    "  macos: would get 'проверка уведомлений фабрики -> http://127.0.0.1:8790/'",
    "  telegram: would get 'Фабрика · run_done\\nпроверка уведомлений фабрики\\nпульт' - SENDS THE TEXT TO AN OUTSIDE SERVICE",
    'nothing sent (a stand-in backend; the journal is untouched)',
  ],
  // CC-0089 (договор 0.38.0): то же по бэкендам — данными.
  preview: [
    {
      name: 'log',
      known: true,
      external: false,
      ready: true,
      skip_reason: null,
      would_get: 'проверка уведомлений фабрики -> http://127.0.0.1:8790/',
    },
    {
      name: 'macos',
      known: true,
      external: false,
      ready: true,
      skip_reason: null,
      would_get: 'проверка уведомлений фабрики -> http://127.0.0.1:8790/',
    },
    {
      name: 'telegram',
      known: true,
      external: true,
      ready: true,
      skip_reason: null,
      would_get: 'Фабрика · run_done\nпроверка уведомлений фабрики\nпульт',
    },
  ],
  sent: false,
};

/** Проверка, где Telegram включён, но без адреса — его пропустили бы. */
export const CHECK_SKIPPED: S['NotifyCheck'] = {
  backends: ['log', 'telegram'],
  default: ['log'],
  external: ['telegram'],
  lines: [
    'journal: notify/sent.jsonl',
    'backends on: log, telegram (NOTIFY_BACKENDS; default log)',
    "  log: would get 'проверка уведомлений фабрики -> http://127.0.0.1:8790/'",
    "  telegram: would get 'Фабрика · run_done\\nпроверка уведомлений фабрики\\nпульт' - would be skipped (NOTIFY_TELEGRAM_CHAT is not set)",
    'nothing sent (a stand-in backend; the journal is untouched)',
  ],
  preview: [
    {
      name: 'log',
      known: true,
      external: false,
      ready: true,
      skip_reason: null,
      would_get: 'проверка уведомлений фабрики -> http://127.0.0.1:8790/',
    },
    {
      name: 'telegram',
      known: true,
      external: true,
      ready: false,
      skip_reason: 'no NOTIFY_TELEGRAM_CHAT in .env',
      would_get: 'Фабрика · run_done\nпроверка уведомлений фабрики\nпульт',
    },
  ],
  sent: false,
};
