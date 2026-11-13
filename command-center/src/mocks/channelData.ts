// Подставные данные канала для вкладки «Данные канала» (CC-0115 → CC-0101/0102): концовка
// (`GET /api/channels/{c}/ending`), источники фактов (`…/fact-sources`) и партнёрские ссылки
// (`…/affiliate`). Reel — концовка вручную, полный список источников; Tech — концовка не собрана
// (нет файла, рендер можно запустить), партнёрка выключена, две ссылки; Science — список
// источников с ошибкой фабрики, партнёрской таблицы нет. `state.broken` — список не читается
// (409). Импорты — относительные (общий для Vitest, Playwright и тренировки).
import type { components } from '../api/schema.gen';

import { createListWrites, routeListWrites, standInSha } from './channelLists';

type S = components['schemas'];
type Reply<T> = { status: number; body: T };
type Doc = Record<string, unknown>;
/** Записанное из центра поверх подставных файлов: `список канал` → документ. */
type Over = Record<string, unknown>;

const hand = (c: string): S['ChannelEnding'] => ({
  channel: c,
  cached: true,
  path: `channels/${c}/ending.mp4`,
  source: 'convention',
  path_error: null,
  exists: true,
  bytes: 1_482_113,
  mtime: '2026-09-12T10:20:00Z',
  sha256: 'ab'.repeat(32),
  declared_seconds: 3,
  probe: { seconds: 3.04, width: 1080, height: 1920, fps: 30, has_audio: true },
  probe_error: null,
  check: { ok: true, error: null, against: { width: 1080, height: 1920, fps: 30 } },
  media_url: null,
  generator: {
    script: 'scripts/brand_ending.py',
    renders_channel: false,
    motif: null,
    channels: ['example-science', 'example-tech'],
    frames: 90,
    fps: 30,
    error: null,
  },
  data: {
    path: `channels/${c}/brand.json`,
    exists: true,
    section: true,
    clip: `channels/${c}/ending.mp4`,
    clip_sha256: 'ab'.repeat(32),
    clip_matches: true,
    render: null,
    note: 'made by hand in 2.1',
    errors: [],
    error: null,
  },
  render: {
    available: false,
    why: 'Концовка канала собрана вручную — пересобирать её из бренда нечем.',
    refusal: {
      code: 'ending_by_hand',
      message: 'Концовка канала собрана вручную — пересобирать её из бренда нечем.',
      details: ['ending_by_hand: ending.render is null'],
    },
    by_hand: true,
    plan: null,
    needs: [],
    sources_docs: [`channels/${c}/brand/SOURCES.md`],
    factory_ask: null,
    last_run: null,
  },
});

const missing = (c: string): S['ChannelEnding'] => {
  const h = hand(c);
  return {
    ...h,
    path: `channels/${c}/ending.mp4`,
    exists: false,
    bytes: null,
    mtime: null,
    sha256: null,
    probe: null,
    check: null,
    generator: { ...h.generator, renders_channel: true, motif: 'circuit' },
    data: {
      ...h.data,
      clip: null,
      clip_sha256: null,
      clip_matches: null,
      render: { motif: 'circuit' },
      note: null,
    },
    render: {
      ...h.render,
      available: true,
      why: null,
      refusal: null,
      by_hand: false,
      needs: [
        {
          arg: '--font',
          key: 'ending.render.font',
          required: true,
          stored: true,
          value: 'shared/fonts/Poppins-Bold.ttf',
          present: true,
          what: 'шрифт надписи',
        },
      ],
    },
  };
};

/** Проверка robots.txt для ИИ-ботов, как её пишет фабрика (`source_policy.py check`). */
const aiPolicy = (h: string, verdict = 'allowed') => ({
  verdict,
  checked_on: '2026-10-08',
  checks: [{ robots_url: `https://${h}/robots.txt`, any_agent: true, ai_agents_closed: [] }],
  terms_url: null,
});

const host = (id: string, hosts: string[], extra: Record<string, unknown> = {}) => ({
  id,
  kind: 'trade',
  hosts,
  major_outlet: true,
  use: 'cite_only',
  ai_policy: aiPolicy(hosts[0]!),
  ...extra,
});

export const REEL_SOURCES = {
  version: 'CF-0561',
  kinds: ['production', 'box_office', 'casting', 'release', 'reception', 'scandal', 'other'],
  tiers: {
    '1': [
      // Неизвестное редактору поле (`sections`) — правка по строкам его не теряет (CC-0129).
      host('wikipedia', ['wikipedia.org'], {
        kind: 'encyclopedia',
        major_outlet: false,
        use: 'read_text',
        note: 'Все разделы: съёмки, выход, приём зрителей',
        sections: ['Production', 'Filming', 'Release'],
      }),
      host('variety', ['variety.com']),
      host('hollywood_reporter', ['hollywoodreporter.com']),
      host('deadline', ['deadline.com']),
      host('reuters', ['reuters.com'], { kind: 'news' }),
      host('box_office_mojo', ['boxofficemojo.com'], { kind: 'numbers', major_outlet: false }),
    ],
    '2': [
      host('collider', ['collider.com'], {
        kind: 'entertainment',
        major_outlet: false,
        ai_policy: aiPolicy('collider.com', 'forbidden'),
      }),
      host('screenrant', ['screenrant.com'], { kind: 'entertainment', major_outlet: false }),
    ],
  },
  any_host: [
    {
      source_type: 'creator_interview',
      tier: 1,
      requires: 'quote',
      note: 'Интервью создателя с прямой речью',
    },
    { source_type: 'studio_press', tier: 1, requires: null, note: 'Официальные пресс-материалы' },
  ],
  do_not_take: [
    { id: 'imdb_trivia', hosts: ['imdb.com'], path_contains: ['/trivia', '/goofs'] },
    { id: 'reddit', hosts: ['reddit.com', 'redd.it'] },
    { id: 'fan_wiki', hosts: ['fandom.com', 'wikia.com'] },
  ],
};

function factSources(c: string, over?: Over): S['ChannelFactSources'] {
  const science = c === 'example-science';
  const base = factSourcesBase(c, science);
  const doc = over?.[`fact-sources ${c}`];
  return doc ? { ...base, doc: doc as Doc, sha256: standInSha(doc), errors: [] } : base;
}

function factSourcesBase(c: string, science: boolean): S['ChannelFactSources'] {
  return {
    channel: c,
    path: `channels/${c}/fact-sources.json`,
    doc: science
      ? {
          ...REEL_SOURCES,
          kinds: [
            'measurement',
            'discovery',
            'mission',
            'record',
            'history',
            'other',
            'eclipse_chase',
          ],
          tiers: {
            '1': [
              host('nasa', ['nasa.gov', 'science.nasa.gov'], {
                kind: 'agency',
                ai_output_terms: {
                  terms_url: 'https://www.nasa.gov/nasa-brand-center/images-and-media/',
                  forbidden: [
                    {
                      id: 'according_to_nasa',
                      phrase: 'according to NASA',
                      pattern: '\\baccording to nasa\\b',
                      why: 'NASA terms: references like «according to NASA» are prohibited in AI products',
                    },
                  ],
                },
              }),
            ],
          },
        }
      : REEL_SOURCES,
    missing: null,
    kinds: science ? null : REEL_SOURCES.kinds,
    sha256: 'cd'.repeat(32),
    errors: science
      ? [
          "fact-sources.json: kinds 'eclipse_chase' is not a fact kind the rule knows",
          'sources.rss.feeds[0] https://example.org/feed: the host forbids AI bots in robots.txt',
        ]
      : [],
  };
}

function affiliate(c: string, over?: Over): S['ChannelAffiliate'] {
  const base = affiliateBase(c);
  const doc = over?.[`affiliate ${c}`];
  return doc
    ? { ...base, doc: doc as Doc, missing: null, sha256: standInSha(doc), errors: [] }
    : base;
}

function affiliateBase(c: string): S['ChannelAffiliate'] {
  if (c !== 'example-tech')
    return {
      channel: c,
      path: `channels/${c}/affiliate.json`,
      enabled: false,
      block: null,
      doc: null,
      missing: `channels/${c}/affiliate.json: no such file`,
      sha256: null,
      errors: [],
    };
  return {
    channel: c,
    path: `channels/${c}/affiliate.json`,
    enabled: false,
    block: {
      enabled: false,
      link_line: 'Link to {product} (affiliate): {url}',
      disclosure: {
        default: 'This is an affiliate link: the channel may earn a commission from it.',
      },
    },
    doc: {
      channel_id: c,
      programmes: [
        {
          id: 'amazon-us',
          name: 'Amazon Associates (US)',
          network: 'amazon_associates',
          tag: 'example-20',
          added_by: 'user',
          added_at: '2026-10-06',
        },
      ],
      products: [
        {
          id: 'pixel-10',
          names: ['Pixel 10 Pro', 'Pixel 10'],
          url: 'https://amzn.to/x?tag=example-20',
          programme: 'amazon-us',
          added_by: 'user',
          added_at: '2026-10-06',
        },
        {
          id: 'quest-4',
          names: ['Meta Quest 4'],
          aliases: ['Quest 4'],
          url: 'https://amzn.to/y?tag=example-20',
          programme: 'amazon-us',
          added_by: 'user',
          added_at: '2026-10-07',
        },
      ],
    },
    missing: null,
    sha256: 'ef'.repeat(32),
    errors: [],
  };
}

type EndingCode = S['EndingProblem']['code'];

export function createChannelDataState() {
  const over: Over = {};
  const ending = {
    life: 120,
    /** Код отказа плана концовки (`batch_open`, `render_running`…). */
    refuse: null as EndingCode | null,
    /** Код отказа «да» (`start_failed`…). */
    actRefuse: null as EndingCode | null,
    tokens: new Map<string, { c: string; expires: number }>(),
    started: [] as string[],
    seq: 0,
    /**
     * CC-0161: последняя сборка концовки канала (`render.last_run`) — например, собрана, но git
     * отказал в коммите (`ENDING_COMMIT_REFUSED`); канала нет — `null`, как по умолчанию.
     */
    lastRun: {} as Record<string, S['EndingLastRun']>,
  };
  const lists = createListWrites({
    read: (c, list) => {
      const d = list === 'fact-sources' ? factSources(c, over) : affiliate(c, over);
      return { doc: d.doc, sha: d.sha256 ?? null };
    },
    write: (c, list, doc) => {
      over[`${list} ${c}`] = doc;
    },
    // Лента новостей Science закрыта robots.txt для всех — проверка фабрики не пропустит список,
    // что бы в нём ни правили (CC-0129: ошибка проверки фабрики словами).
    errors: (c, list) =>
      list === 'fact-sources' && c === 'example-science'
        ? [
            'example-science sources.rss.feeds[example.org]: robots.txt closes it to every agent (`*`) - it is not read at all, whatever the use (the CF-0045 stance)',
          ]
        : [],
  });
  return { broken: false, calls: [] as string[], over, lists, ending };
}
export type ChannelDataState = ReturnType<typeof createChannelDataState>;

/** CC-0161: сборка концовки кончилась, клип в дереве, но git отказал в коммите `ending.mp4`. */
export const ENDING_COMMIT_REFUSED = (c: string): S['EndingLastRun'] => ({
  pid: 4242,
  log: `schedule/logs/2026-10-22-${c}-ending.log`,
  started_at: '2026-10-22T09:40:00Z',
  running: false,
  commit_refused: "fatal: Unable to create '.git/index.lock': File exists.",
});

const baseEnding = (c: string) => (c === 'example-film' ? hand(c) : missing(c));

/** Концовка канала; с `lastRun` — какой её оставила последняя сборка (кончилась — клип есть). */
function endingOf(c: string, state?: ChannelDataState): S['ChannelEnding'] {
  const e = baseEnding(c);
  const run = state?.ending.lastRun[c];
  if (!run) return e;
  const h = hand(c);
  const made = run.running
    ? {}
    : {
        exists: true,
        bytes: h.bytes,
        mtime: '2026-10-22T09:41:00Z',
        sha256: h.sha256,
        probe: h.probe,
        check: h.check,
      };
  return { ...e, ...made, render: { ...e.render, last_run: run } };
}

const endingProblem = (status: number, code: EndingCode, message: string, details: string[]) => ({
  status,
  body: { message, code, details } satisfies S['EndingProblem'],
});

function endingPlan(state: ChannelDataState, c: string): Reply<S['EndingRenderPlan']> {
  const e = endingOf(c, state);
  const r = e.render;
  const st = state.ending;
  const refusal: S['EndingRefusal'] | null =
    r.refusal ??
    (st.refuse
      ? {
          code: st.refuse as S['EndingRefusal']['code'],
          message:
            st.refuse === 'batch_open'
              ? 'Идёт батч канала — концовку соберём после него.'
              : st.refuse === 'render_running'
                ? 'Концовка уже собирается — дождитесь конца.'
                : 'Фабрика не даёт собрать концовку.',
          details: [`${st.refuse}: the factory's line`],
        }
      : null);
  let confirm: string | null = null;
  if (!refusal) {
    confirm = `ending-${++st.seq}`;
    st.tokens.set(confirm, { c, expires: Date.now() + st.life * 1000 });
  }
  return {
    status: 200,
    body: {
      action: 'ending_render',
      channel: c,
      ok: !refusal,
      why: refusal?.message ?? null,
      refusal,
      by_hand: r.by_hand,
      plan: r.plan,
      argv: refusal ? null : ['scripts/brand_ending.py', '--channel', c, '--motif', 'circuit'],
      needs: r.needs,
      batches: st.refuse === 'batch_open' ? [`${c}/2026-10-14T0200Z`] : [],
      log_dir: 'schedule/logs',
      fingerprint: `fp-ending-${c}`,
      confirm,
      expires_in_s: confirm ? st.life : null,
    },
  };
}

function endingAct(
  state: ChannelDataState,
  c: string,
  raw: unknown,
): Reply<S['EndingRenderResult'] | S['EndingProblem']> {
  const st = state.ending;
  const token = (raw as { confirm?: string } | null)?.confirm ?? '';
  const got = st.tokens.get(token);
  st.tokens.delete(token);
  if (!got || got.c !== c)
    return endingProblem(
      409,
      'confirm_unknown',
      'Подтверждение не найдено - запросите план заново.',
      ['no such confirm token'],
    );
  if (got.expires <= Date.now())
    return endingProblem(
      409,
      'confirm_expired',
      'Подтверждение устарело - запросите план заново.',
      ['expired'],
    );
  if (st.actRefuse)
    return endingProblem(
      st.actRefuse === 'start_failed' ? 500 : 409,
      st.actRefuse,
      st.actRefuse === 'start_failed'
        ? 'Рендер концовки не запустился - посмотрите журнал.'
        : 'Фабрика не запустила рендер концовки.',
      [`${st.actRefuse}: brand_ending.py`],
    );
  st.started.push(c);
  return {
    status: 200,
    body: {
      ok: true,
      channel: c,
      pid: 4242,
      log: `schedule/logs/2026-10-14-${c}-ending.log`,
      started_at: '2026-10-14T08:00:00Z',
      argv: ['scripts/brand_ending.py', '--channel', c, '--motif', 'circuit'],
      out: `channels/${c}/ending.mp4`,
    },
  };
}

/**
 * `GET /api/channels/{c}/(ending|fact-sources|affiliate)`, правка источников фактов и партнёрских
 * ссылок (./channelLists) и сборка концовки (`POST …/ending[/plan]`); null — адрес не этот.
 */
export function routeChannelData(
  state: ChannelDataState,
  known: (c: string) => boolean,
  method: string,
  url: URL,
  body: unknown = null,
): Reply<unknown> | null {
  const list = routeListWrites(state.lists, ['fact-sources', 'affiliate'], method, url, body);
  if (list) return list;
  const end = url.pathname.match(/\/api\/channels\/([^/]+)\/ending(\/plan)?$/);
  if (end && method === 'POST') {
    const c = decodeURIComponent(end[1]!);
    if (!known(c)) return endingProblem(404, 'unknown_channel', `Канала «${c}» нет.`, []);
    return end[2] ? endingPlan(state, c) : endingAct(state, c, body);
  }
  const m = url.pathname.match(/\/api\/channels\/([^/]+)\/(ending|fact-sources|affiliate)$/);
  if (!m || method !== 'GET') return null;
  const c = decodeURIComponent(m[1]!);
  const what = m[2]!;
  state.calls.push(`${what} ${c}`);
  if (!known(c))
    return {
      status: 404,
      body: { message: `Канала «${c}» нет.`, code: 'unknown_channel', details: [] },
    };
  if (state.broken && what !== 'ending')
    return {
      status: 409,
      body: {
        message: 'Список канала не читается.',
        code: what === 'fact-sources' ? 'fact_sources_unreadable' : 'affiliate_unreadable',
        details: [`channels/${c}/${what}.json: Expecting value: line 1 column 1`],
      },
    };
  if (what === 'ending') return { status: 200, body: endingOf(c, state) };
  if (what === 'fact-sources') return { status: 200, body: factSources(c, state.over) };
  return { status: 200, body: affiliate(c, state.over) };
}
