// Подставная очередь просьб оператору (`shared/operator_requests.py` фабрики, API CC-0018,
// договор 0.21.0) — с состоянием: список по статусу, новая просьба, «закрыть» и «отменить».
// Общая для Vitest (MSW, src/mocks/handlers.ts) и Playwright (tests/e2e/fixtures.ts). Тела
// ответов типизированы сгенерированными типами контракта; отказы — `RequestProblem` с `code`
// и `text_ru`, как у `REFUSALS_RU` фабрики. Данные выдуманные, но по форме как у живой
// очереди. Импорты — относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];
type R = S['OperatorRequest'];
type Code = S['RequestProblem']['code'];

export type RequestsReply =
  | { status: 200; body: S['OperatorRequests'] | R }
  | {
      status: 403 | 404 | 409 | 422 | 500;
      body: S['RequestProblem'] | S['WritesProblem'] | { detail: string };
    };

const STATUSES = ['live', 'open', 'taken', 'answered', 'closed', 'cancelled', 'all'] as const;
type Filter = (typeof STATUSES)[number];

/** «Только смотреть» в ответе записи (CC-0058), как у `api/app.py`. */
export const REQUESTS_READ_ONLY =
  'Только смотреть: это рабочая копия разработки (.../cc-api), а не рабочая фабрика';

const TEXT_MAX = 4000;
const CONTEXT_MAX = 4000;

/** `REFUSALS_RU` фабрики (тире — как у неё, ASCII). */
const RU: Record<Code, (id: string) => string> = {
  text_empty: () => 'Просьба пустая - напишите, что сделать.',
  text_too_long: () => `Просьба длиннее ${TEXT_MAX} знаков - сократите её.`,
  answer_empty: () => 'Ответ пустой - напишите текст ответа.',
  answer_too_long: () => `Ответ длиннее ${TEXT_MAX} знаков - сократите его.`,
  by_missing: () => 'Не сказано, кто это делает.',
  context_invalid: () => `Контекст просьбы не записать: длиннее ${CONTEXT_MAX} знаков.`,
  status_unknown: () =>
    '«?» - не состояние просьбы; бывают: open, taken, answered, closed, cancelled.',
  not_found: (id) => `Просьбы ${id} нет.`,
  not_taken: (id) => `Просьба ${id} ещё не взята в работу - отвечает оператор, который её взял.`,
  already_answered: (id) => `На просьбу ${id} уже ответили - второй ответ не записывается.`,
  not_answered: (id) =>
    `На просьбу ${id} ещё не ответили - закрыть её можно после ответа (или отменить).`,
  already_closed: (id) => `Просьба ${id} уже закрыта.`,
  already_cancelled: (id) => `Просьба ${id} отменена.`,
  cancel_answered: (id) => `На просьбу ${id} уже ответили - отменять нечего, её можно закрыть.`,
  no_answer: (id) => `У просьбы ${id} нет ответа - отправлять в Telegram нечего.`,
  already_delivered: (id) => `Ответ на просьбу ${id} уже дошёл - повторять не нужно.`,
};

export function problem(
  code: Code,
  id = '',
  detail = code.replace(/_/g, ' '),
): S['RequestProblem'] {
  return { detail, code, text_ru: RU[code](id) };
}

const base = (n: number, over: Partial<R>): R => ({
  id: `R${n}`,
  n,
  text: '',
  channel: null,
  context: null,
  created: null,
  created_by: 'user',
  updated: null,
  status: 'open',
  taken_by: null,
  taken_at: null,
  answer: null,
  answered_by: null,
  answered_at: null,
  closed_by: null,
  closed_at: null,
  cancelled_by: null,
  cancelled_at: null,
  notify: null,
  ...over,
});

const sent = (n: number, at: string): R['notify'] => ({
  status: 'sent',
  attempt: 1,
  key: `request:R${n}:answer`,
  reason: null,
  backends: { telegram: { ok: true } },
  at,
});

/**
 * Очередь по умолчанию (старые первыми, как у фабрики): закрытая, отменённая, две с ответом
 * (в Telegram дошёл / не дошёл), взятая оператором и открытая.
 */
export function defaultRequests(): R[] {
  return [
    base(1, {
      text: 'Проверь, почему у ExampleTech вчера не вышел вечерний ролик.',
      channel: 'example-tech',
      context: { screen: '/channels/example-tech', area: 'Каналы', channel: 'example-tech' },
      created: '2026-10-07T08:10:00Z',
      updated: '2026-10-07T12:30:00Z',
      status: 'closed',
      taken_by: 'operator',
      taken_at: '2026-10-07T08:20:00Z',
      answer: 'Слот 19:00 был занят холдом проверки прав; холд снят, ролик вышел в 21:00.',
      answered_by: 'operator',
      answered_at: '2026-10-07T09:05:00Z',
      closed_by: 'user',
      closed_at: '2026-10-07T12:30:00Z',
      notify: sent(1, '2026-10-07T09:05:03Z'),
    }),
    base(2, {
      text: 'Пересобери заставку для ExampleScience — старая слишком длинная.',
      channel: 'example-science',
      context: null,
      created: '2026-10-08T10:00:00Z',
      updated: '2026-10-08T10:40:00Z',
      status: 'cancelled',
      cancelled_by: 'user',
      cancelled_at: '2026-10-08T10:40:00Z',
    }),
    base(3, {
      text: 'Посмотри, почему в ролике «RTX 5090 melts» обрывается музыка на 0:42.',
      channel: 'example-tech',
      context: {
        screen: '/videos?batch=example-tech%2F2026-10-09&v=rtx-5090-melts',
        area: 'Ролики',
        channel: 'example-tech',
        batch: 'example-tech/2026-10-09',
        batch_title: '09.10, 06:00',
        video: 'rtx-5090-melts',
        video_title: 'RTX 5090 melts',
      },
      created: '2026-10-09T13:00:00Z',
      updated: '2026-10-09T15:12:00Z',
      status: 'answered',
      taken_by: 'operator',
      taken_at: '2026-10-09T13:04:00Z',
      answer:
        'Трек короче ролика: монтаж не зациклил подложку. Поправил шаблон, ролик пересобран — посмотрите пересборку 1.',
      answered_by: 'operator',
      answered_at: '2026-10-09T15:12:00Z',
      notify: sent(3, '2026-10-09T15:12:04Z'),
    }),
    base(4, {
      text: 'Сколько роликов ExampleFilm ждут загрузки в YouTube на этой неделе?',
      channel: null,
      context: { screen: '/publishing', area: 'Публикация' },
      created: '2026-10-10T06:30:00Z',
      updated: '2026-10-10T07:02:00Z',
      status: 'answered',
      taken_by: 'operator',
      taken_at: '2026-10-10T06:41:00Z',
      answer: 'Семь: по одному на каждый вечерний слот с 11.10 по 17.10.',
      answered_by: 'operator',
      answered_at: '2026-10-10T07:02:00Z',
      notify: {
        status: 'failed',
        attempt: 2,
        key: 'request:R4:answer#again:try2',
        reason: 'telegram: 502 Bad Gateway',
        backends: { telegram: { ok: false, error: '502 Bad Gateway' } },
        at: '2026-10-10T07:04:00Z',
      },
    }),
    base(5, {
      text: 'Сдвинь батч ExampleFilm на час позже — утром сеть занята.',
      channel: 'example-film',
      context: {
        screen: '/batches',
        area: 'Батчи',
        channel: 'example-film',
        batch: 'example-film/2026-10-10',
        batch_title: '10.10, 06:00',
      },
      created: '2026-10-10T08:15:00Z',
      updated: '2026-10-10T08:20:00Z',
      status: 'taken',
      taken_by: 'operator',
      taken_at: '2026-10-10T08:20:00Z',
    }),
    base(6, {
      text: 'Добавь в позицию ExampleFilm запрет на темы про ставки.',
      channel: 'example-film',
      context: { screen: '/channels/example-film', area: 'Каналы', channel: 'example-film' },
      created: '2026-10-10T09:00:00Z',
      updated: '2026-10-10T09:00:00Z',
    }),
  ];
}

export type RequestsBackend = {
  requests: R[];
  /** «Сейчас» подставной фабрики для `created`/`closed_at`/`cancelled_at`. */
  now: () => string;
  /** API «только смотреть»: каждая запись — 409 `not_working_factory`. */
  readOnly: boolean;
  /** Следующая запись упадёт этим ответом (один раз). */
  next: { status: 404 | 409 | 422 | 500; code: Code } | null;
  /** GET списка — этим статусом (ломать чтение). */
  listFails: number | null;
  /** Все пришедшие записи (для проверок «не слали» и тела запроса). */
  writes: { path: string; body: unknown }[];
};

export function createRequestsBackend(rs: R[] = defaultRequests()): RequestsBackend {
  return {
    requests: rs,
    now: () => '2026-10-10T10:00:00Z',
    readOnly: false,
    next: null,
    listFails: null,
    writes: [],
  };
}

const filterOf = (f: Filter) => (r: R) =>
  f === 'all'
    ? true
    : f === 'live'
      ? r.status === 'open' || r.status === 'taken' || r.status === 'answered'
      : r.status === f;

const LIVE_STATUSES = new Set(['open', 'taken', 'answered']);

/** Ответ подставного API на запрос к `/api/requests*`; `null` — не наш путь. */
export function routeRequests(
  b: RequestsBackend,
  method: string,
  url: URL,
  body: unknown,
): RequestsReply | null {
  const m = /\/api\/requests(?:\/([^/]+)(?:\/(close|cancel))?)?$/.exec(url.pathname);
  if (!m) return null;
  const [, rawId, action] = m;
  const rid = rawId ? decodeURIComponent(rawId) : null;
  if (method === 'GET') {
    if (rid) {
      if (action) return null;
      const r = b.requests.find((x) => x.id === rid);
      return r ? { status: 200, body: r } : { status: 404, body: problem('not_found', rid) };
    }
    if (b.listFails) return { status: b.listFails as 500, body: { detail: 'queue unreadable' } };
    const asked = (url.searchParams.get('status') ?? 'live') as Filter;
    if (!STATUSES.includes(asked)) return { status: 422, body: problem('status_unknown') };
    return { status: 200, body: { status: asked, requests: b.requests.filter(filterOf(asked)) } };
  }
  if (method !== 'POST' || (rid && !action)) return null;
  b.writes.push({ path: url.pathname, body });
  if (b.readOnly)
    return {
      status: 409,
      body: {
        message: REQUESTS_READ_ONLY,
        code: 'not_working_factory',
        details: ['.../cc-api', 'CC_API_WRITES=dev'],
      },
    };
  if (b.next) {
    const { status, code } = b.next;
    b.next = null;
    return { status, body: problem(code, rid ?? '') };
  }
  const at = b.now();
  if (!rid) {
    const o = (typeof body === 'object' && body !== null ? body : {}) as Record<string, unknown>;
    const text = typeof o.text === 'string' ? o.text.trim() : '';
    if (!text) return { status: 422, body: problem('text_empty') };
    if (text.length > TEXT_MAX) return { status: 422, body: problem('text_too_long') };
    if (o.context != null && JSON.stringify(o.context).length > CONTEXT_MAX)
      return { status: 422, body: problem('context_invalid') };
    const n = Math.max(0, ...b.requests.map((r) => r.n)) + 1;
    const r = base(n, {
      text,
      channel: typeof o.channel === 'string' ? o.channel : null,
      context: o.context ?? null,
      created: at,
      updated: at,
    });
    b.requests.push(r);
    return { status: 200, body: r };
  }
  const i = b.requests.findIndex((x) => x.id === rid);
  if (i < 0) return { status: 404, body: problem('not_found', rid) };
  const r = b.requests[i]!;
  if (r.status === 'closed') return { status: 409, body: problem('already_closed', rid) };
  if (r.status === 'cancelled') return { status: 409, body: problem('already_cancelled', rid) };
  if (action === 'close') {
    if (r.status !== 'answered') return { status: 409, body: problem('not_answered', rid) };
    const next: R = { ...r, status: 'closed', closed_by: 'user', closed_at: at, updated: at };
    b.requests[i] = next;
    return { status: 200, body: next };
  }
  if (!LIVE_STATUSES.has(r.status) || r.status === 'answered')
    return { status: 409, body: problem('cancel_answered', rid) };
  const next: R = {
    ...r,
    status: 'cancelled',
    cancelled_by: 'user',
    cancelled_at: at,
    updated: at,
  };
  b.requests[i] = next;
  return { status: 200, body: next };
}
