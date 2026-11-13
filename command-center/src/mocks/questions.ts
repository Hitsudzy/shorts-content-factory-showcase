// Подставной журнал вопросов (CF-0652 фабрики, API CC-0016) — с состоянием: список по статусу,
// ответ и «решено». Общий для Vitest (MSW, src/mocks/handlers.ts) и Playwright
// (tests/e2e/fixtures.ts). Тела ответов типизированы сгенерированными типами контракта; строки
// отказов — как у `api/factory.py` / `shared/needs_you.py` (`{detail}` по-английски). Данные
// выдуманные, но по форме как у живой фабрики. Импорты — относительные.
import type { components } from '../api/schema.gen';

type S = components['schemas'];
type Q = S['Question'];

export type QuestionsReply =
  | { status: 200; body: S['Questions'] | Q }
  | { status: 403 | 404 | 409 | 422 | 500; body: S['Problem'] | S['WritesProblem'] };

const STATUSES = ['live', 'open', 'answered', 'resolved', 'all'] as const;
type Filter = (typeof STATUSES)[number];

/** «Только смотреть» в ответе записи (CC-0058), как у `api/app.py`. */
export const QUESTIONS_READ_ONLY =
  'Только смотреть: это рабочая копия разработки (.../cc-api), а не рабочая фабрика';

const base = (n: number, over: Partial<Q>): Q => ({
  id: `Q${n}`,
  n,
  key: `key:${n}`,
  source: 'trend-hunter',
  channel: null,
  text: '',
  link: null,
  created: null,
  created_by: null,
  updated: null,
  status: 'open',
  answer: null,
  answered_by: null,
  answered_at: null,
  resolved_by: null,
  resolved_at: null,
  note: null,
  // CC-0086 (договор 0.42.0): предложенный ответ того, кто спросил, и как ответили.
  suggestion: null,
  suggestion_why: null,
  suggested_by: null,
  suggested_at: null,
  answered_via: null,
  accepted_suggestion: false,
  ...over,
});

/**
 * Журнал по умолчанию: 3 открытых, 1 с ответом, 3 решённых; старые первыми, как у фабрики.
 * CC-0086: у двух открытых (Q8, Q9) есть предложенный ответ, у Q6 — нет; Q7 отвечен своим
 * текстом при предложении, Q5 — принятым предложением; у Q8 предложение обновится прямо перед
 * первым «принять» (`revise`) — отказ `check_changed`.
 */
export function defaultQuestions(): Q[] {
  return [
    base(3, {
      key: 'needs-you-md:3f2a1b0c9d8e',
      source: 'needs-you-md',
      channel: 'example-film',
      text: 'Шапку канала ExampleFilm обновить под осенний сезон или оставить летнюю?',
      created: '2026-10-02T09:15:00Z',
      created_by: 'needs-you-md',
      updated: '2026-10-03T08:00:00Z',
      status: 'resolved',
      answer: 'Оставить летнюю до конца октября.',
      answered_by: 'user',
      answered_at: '2026-10-02T18:40:00Z',
      resolved_by: 'user',
      resolved_at: '2026-10-03T08:00:00Z',
      note: 'шапку не трогаем',
    }),
    base(4, {
      key: 'archive:publish-debt:2026-09',
      source: 'archive-publish-month',
      channel: null,
      text: 'Архив публикаций за сентябрь не собран: 3 ролика без отметки Studio. Собрать без них?',
      created: '2026-10-01T03:00:00Z',
      created_by: 'archive-publish-month',
      updated: '2026-10-05T03:00:00Z',
      status: 'resolved',
      resolved_by: 'archive-publish-month',
      resolved_at: '2026-10-05T03:00:00Z',
      note: 'отметки Studio внесены, архив собран',
    }),
    base(5, {
      key: 'footage:example-science:2026-10-06-source',
      source: 'footage-indexer',
      channel: 'example-science',
      text: 'У ролика «Example Short A» источник с неясной лицензией. Оставить кадры или заменить?',
      created: '2026-10-06T11:20:00Z',
      created_by: 'footage-indexer',
      updated: '2026-10-07T10:05:00Z',
      status: 'resolved',
      answer: 'Заменить кадры.',
      answered_by: 'user',
      answered_at: '2026-10-06T19:02:00Z',
      suggestion: 'Заменить кадры.',
      suggestion_why:
        'Лицензия источника не подтверждена; замена кадров дешевле, чем ждать ответа правообладателя.',
      suggested_by: 'operator',
      suggested_at: '2026-10-06T11:40:00Z',
      answered_via: 'center',
      accepted_suggestion: true,
      resolved_by: 'user',
      resolved_at: '2026-10-07T10:05:00Z',
    }),
    base(6, {
      key: 'oauth-token:example-film:2026-10-13',
      source: 'publisher-auth',
      channel: 'example-film',
      text: 'Доступ к YouTube у канала ExampleFilm истекает 13.10 — переразрешите его в терминале, иначе загрузки встанут.',
      link: 'agents/publisher/publisher_auth.py',
      created: '2026-10-09T06:00:00Z',
      created_by: 'publisher-auth',
      updated: '2026-10-10T06:00:00Z',
    }),
    base(7, {
      key: 'analyst:example-film:retention-drop',
      source: 'analyst-metrics',
      channel: 'example-film',
      text: 'Удержание на первых 3 секундах упало с 71 % до 58 % за неделю. Сменить шаблон заставки или подождать ещё неделю?',
      created: '2026-10-09T15:30:00Z',
      created_by: 'analyst-metrics',
      updated: '2026-10-09T20:10:00Z',
      status: 'answered',
      answer: 'Подождать неделю, потом решим.',
      answered_by: 'user',
      answered_at: '2026-10-09T20:10:00Z',
      suggestion: 'Сменить шаблон заставки на «вопрос в первом кадре».',
      suggestion_why:
        'Падение началось в день смены шаблона; на ExampleTech «вопрос в первом кадре» держит 70 %.',
      suggested_by: 'analyst-metrics',
      suggested_at: '2026-10-09T15:30:00Z',
      answered_via: 'center',
      accepted_suggestion: false,
    }),
    base(8, {
      key: 'sieve:example-tech:2026-10-10-rtx',
      source: 'footage-indexer',
      channel: 'example-tech',
      text: 'Для темы «RTX 5090 melts» фильтр футажа отверг 9 из 11 роликов. Взять тему с двумя источниками или снять её?',
      created: '2026-10-10T05:12:00Z',
      created_by: 'footage-indexer',
      updated: '2026-10-10T05:12:00Z',
      suggestion: 'Снять тему: двух источников мало на 30 секунд без повторов.',
      suggestion_why:
        'Из двух оставшихся роликов один — трейлер с логотипом; на 30 секунд кадры пойдут по кругу.',
      suggested_by: 'operator',
      suggested_at: '2026-10-10T05:20:00Z',
    }),
    base(9, {
      key: 'trend:example-film:2026-10-10-pick5',
      source: 'trend-hunter',
      channel: 'example-film',
      text: 'Выше порога 45 сегодня только 4 темы. Взять пятой Entourage (43,8)?',
      created: '2026-10-10T06:40:00Z',
      created_by: 'trend-hunter',
      updated: '2026-10-10T06:40:00Z',
      suggestion: 'Да, взять Entourage пятой.',
      suggestion_why:
        '43,8 — меньше двух пунктов до порога, а без пятой темы батч не доберёт план недели.',
      suggested_by: 'trend-hunter',
      suggested_at: '2026-10-10T06:40:00Z',
    }),
  ];
}

export type QuestionsBackend = {
  questions: Q[];
  /** «Сейчас» подставной фабрики для `answered_at`/`resolved_at`. */
  now: () => string;
  /** API «только смотреть»: каждая запись — 409 `not_working_factory`. */
  readOnly: boolean;
  /** Следующая запись упадёт этим ответом (один раз); `code` — как у `Problem.code`. */
  next: { status: 403 | 404 | 409 | 422 | 500; detail: string; code?: string } | null;
  /**
   * CC-0086: предложение вопроса обновится прямо перед следующим «принять» (один раз) — тот, кто
   * спросил, передумал, пока человек читал: API отвечает 409 `check_changed`, ничего не пишет.
   */
  revise: Record<
    string,
    Pick<Q, 'suggestion' | 'suggestion_why' | 'suggested_by' | 'suggested_at'>
  >;
  /** GET списка — этим статусом (ломать чтение). */
  listFails: number | null;
  /** Сколько раз пришла запись (для проверок «не слали»). */
  writes: { path: string; body: unknown }[];
};

export function createQuestionsBackend(qs: Q[] = defaultQuestions()): QuestionsBackend {
  return {
    questions: qs,
    now: () => '2026-10-10T07:00:00Z',
    readOnly: false,
    next: null,
    revise: {
      Q8: {
        suggestion: 'Снять тему и взять запасную «Pixel 10 battery» из вчерашних трендов.',
        suggestion_why:
          'Двух источников мало на 30 секунд, а у запасной темы 6 роликов и балл 47,2.',
        suggested_by: 'operator',
        suggested_at: '2026-10-10T06:55:00Z',
      },
    },
    listFails: null,
    writes: [],
  };
}

const filterOf = (f: Filter) => (q: Q) =>
  f === 'all' ? true : f === 'live' ? q.status !== 'resolved' : q.status === f;

function text(body: unknown, key: string): string | null {
  if (typeof body !== 'object' || body === null) return null;
  const v = (body as Record<string, unknown>)[key];
  return typeof v === 'string' ? v : null;
}

/** Ответ подставного API на запрос к `/api/questions*`; `null` — не наш путь. */
export function routeQuestions(
  b: QuestionsBackend,
  method: string,
  url: URL,
  body: unknown,
): QuestionsReply | null {
  const m = /\/api\/questions(?:\/([^/]+)\/(answer|resolve))?$/.exec(url.pathname);
  if (!m) return null;
  const [, rawId, action] = m;
  if (!action) {
    if (method !== 'GET') return null;
    if (b.listFails) return { status: b.listFails as 500, body: { detail: 'journal unreadable' } };
    const asked = (url.searchParams.get('status') ?? 'live') as Filter;
    if (!STATUSES.includes(asked)) return null;
    return {
      status: 200,
      body: { status: asked, questions: b.questions.filter(filterOf(asked)) },
    };
  }
  if (method !== 'POST') return null;
  const qid = decodeURIComponent(rawId!);
  b.writes.push({ path: url.pathname, body });
  if (b.readOnly)
    return {
      status: 409,
      body: {
        message: QUESTIONS_READ_ONLY,
        code: 'not_working_factory',
        details: ['.../cc-api', 'CC_API_WRITES=dev'],
      },
    };
  if (b.next) {
    const { status, detail, code } = b.next;
    b.next = null;
    return { status, body: code ? { detail, code } : { detail } };
  }
  const i = b.questions.findIndex((q) => q.id === qid);
  if (i < 0) return { status: 404, body: { detail: `no question ${qid}` } };
  const q = b.questions[i]!;
  const by = text(body, 'by') ?? 'user';
  const at = b.now();
  if (action === 'answer') {
    // CC-0086 (договор 0.42.0): `{accept: true, suggested_at?}` — ответ предложением, которое
    // фабрика читает заново; `text` и `accept` вместе — 422; `accepted_suggestion` решает фабрика.
    const accept =
      typeof body === 'object' && body !== null && (body as { accept?: unknown }).accept === true;
    const given = (text(body, 'text') ?? '').trim();
    if (accept && given)
      return { status: 422, body: { detail: 'an answer is a text or the suggestion, not both' } };
    if (!accept && !given) return { status: 422, body: { detail: 'an answer needs a text' } };
    if (q.status === 'resolved')
      return { status: 409, body: { detail: `question ${qid} is already resolved` } };
    const fold = (t: string) => t.replace(/\s+/g, ' ').trim();
    const revised = accept ? b.revise[qid] : undefined;
    if (revised) {
      delete b.revise[qid];
      b.questions[i] = { ...q, ...revised, updated: at };
      return {
        status: 409,
        body: { detail: `the suggestion of ${qid} changed`, code: 'check_changed' },
      };
    }
    if (accept && !q.suggestion)
      return {
        status: 409,
        body: { detail: `question ${qid} has no suggestion`, code: 'no_suggestion' },
      };
    const seen = text(body, 'suggested_at');
    if (accept && seen !== null && seen !== q.suggested_at)
      return {
        status: 409,
        body: { detail: `the suggestion of ${qid} changed`, code: 'check_changed' },
      };
    const answer = accept ? q.suggestion! : given;
    const next: Q = {
      ...q,
      status: 'answered',
      answer,
      answered_by: by,
      answered_at: at,
      answered_via: 'center',
      accepted_suggestion: !!q.suggestion && fold(answer) === fold(q.suggestion),
      updated: at,
    };
    b.questions[i] = next;
    return { status: 200, body: next };
  }
  if (q.status === 'resolved')
    return { status: 409, body: { detail: `question ${qid} is already resolved` } };
  const next: Q = {
    ...q,
    status: 'resolved',
    resolved_by: by,
    resolved_at: at,
    note: text(body, 'note'),
    updated: at,
  };
  b.questions[i] = next;
  return { status: 200, body: next };
}
