// Подставные данные статистики (CC-0020 фабрики, договор 0.23.0): ролики ExampleFilm с окнами
// YouTube «первые 7 дней», дневными строками и чтениями Studio; ExampleTech — окно 7 дней для
// канала не собирается (`collected: false`), чтение Studio не настроено; ExampleScience — сбор
// ещё ни разу не запускался, роликов нет. Числа выдуманные, но по форме — как у `metrics.py`,
// `summary.py`, `footage_wanted.py`, `studio_read.py`. Импорты — относительные (Playwright).
import type { components } from '../api/schema.gen';
import { REEL, SCIENCE, TECH } from './publish';

type S = components['schemas'];

export const ANALYTICS_CHANNELS = [REEL, TECH, SCIENCE] as const;

/** День последнего сбора: вчера по Тихоокеанскому относительно MOCK_NOW (10.10, 07:00 UTC). */
export const END_DAY = '2026-10-09';
const COLLECTED_AT = '2026-10-10T06:12:00Z';
/** Окончательное — 3+ дня до дня сбора (10.10): по 06.10 включительно. */
const FINAL_UNTIL = '2026-10-06';

const addDays = (day: string, n: number) => {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
};

type Style = Record<'pattern' | 'rhythm' | 'hook_opener' | 'fact_kind' | 'tier', string>;

/** Ролик канала: публикация, окно 7 дней (null — окна нет), Studio, профиль стиля. */
export type MockVideo = {
  video_id: string;
  slug: string;
  batch: string;
  published: string;
  /** Просмотры за 7 дней и остальные числа окна; null — окна YouTube ещё нет. */
  win: {
    views: number;
    engaged: number;
    avp: number;
    avd: number;
    likes: number;
    subs: number;
  } | null;
  studio: { viewed: number | null; swiped: number | null; read_at: string; note?: string } | null;
  style: Style | null;
  profileGap?: string;
};

const style = (
  pattern: string,
  rhythm: string,
  hook_opener: string,
  fact_kind: string,
  tier: string,
): Style => ({ pattern, rhythm, hook_opener, fact_kind, tier });

/** Ролики ExampleFilm, старые сверху. */
export const REEL_VIDEOS: MockVideo[] = [
  {
    video_id: 'hR4c9xQe1aA',
    slug: 'rink-rivals',
    batch: '2026-09-27T0200Z',
    published: '2026-09-28',
    win: { views: 48210, engaged: 31400, avp: 71.2, avd: 24.8, likes: 2140, subs: 186 },
    studio: { viewed: 64.1, swiped: 35.9, read_at: '2026-10-08T18:40:00Z' },
    style: style('contrast', 'staccato', 'wildest-fact', 'casting', 'A'),
  },
  {
    video_id: 'dG7kLm2pQ0s',
    slug: 'delver',
    batch: '2026-09-28T0200Z',
    published: '2026-09-29',
    win: { views: 12650, engaged: 7810, avp: 58.4, avd: 19.1, likes: 402, subs: 22 },
    studio: { viewed: 51.3, swiped: 48.7, read_at: '2026-10-08T18:40:00Z' },
    style: style('list', 'even', 'number-first', 'box_office', 'C'),
  },
  {
    video_id: 'aV3nDd8sQwE',
    slug: 'vanguards-doomsday',
    batch: '2026-09-29T0200Z',
    published: '2026-09-30',
    win: { views: 30880, engaged: 20100, avp: 66.0, avd: 22.7, likes: 1310, subs: 95 },
    studio: { viewed: 59.0, swiped: 41.0, read_at: '2026-10-08T18:40:00Z' },
    style: style('contrast', 'hold', 'real-reason', 'release', 'B'),
  },
  {
    video_id: 'hP2cAs7tNg1',
    slug: 'wren-hollow-casting',
    batch: '2026-09-30T0200Z',
    published: '2026-10-01',
    win: { views: 9420, engaged: 5170, avp: 49.8, avd: 16.2, likes: 238, subs: 9 },
    studio: { viewed: 44.6, swiped: 55.4, read_at: '2026-10-08T18:40:00Z' },
    style: style('list', 'staccato', 'number-first', 'casting', 'F'),
  },
  {
    video_id: 'fF11rElDt5x',
    slug: 'rapid-reckless-11',
    batch: '2026-10-01T0200Z',
    published: '2026-10-02',
    win: { views: 18300, engaged: 11950, avp: 62.5, avd: 21.0, likes: 760, subs: 41 },
    studio: { viewed: 55.2, swiped: null, read_at: '2026-10-08T18:40:00Z' },
    style: style('explainer', 'hold', 'unknown', 'production', 'B'),
  },
  {
    video_id: 'tL0uS2bRk9m',
    slug: 'the-last-ember-s2',
    batch: '2026-10-03T0200Z',
    published: '2026-10-04',
    win: { views: 15120, engaged: 9880, avp: 60.9, avd: 20.3, likes: 590, subs: 33 },
    studio: {
      viewed: null,
      swiped: null,
      read_at: '2026-10-08T18:40:00Z',
      note: 'Studio: недостаточно данных',
    },
    style: style('moment-breakdown', 'even', 'wildest-fact', 'production', 'A'),
  },
  {
    video_id: 'sN7gWz4oPc2',
    slug: 'odd-quarter-finale',
    batch: '2026-10-05T0200Z',
    published: '2026-10-06',
    win: { views: 6240, engaged: 3980, avp: 57.1, avd: 18.4, likes: 201, subs: 12 },
    studio: null,
    style: style('list', 'hold', 'real-reason', 'release', 'unknown'),
  },
  {
    video_id: 'dN3vEr5mTh8',
    slug: 'sandfall-messiah',
    batch: '2026-10-07T0200Z',
    published: '2026-10-08',
    win: null,
    studio: null,
    style: null,
    profileGap: 'нет строки приёмки',
  },
];

/** Ролики ExampleTech: дневные строки есть, окна 7 дней фабрика для канала не собирает. */
export const TECH_VIDEOS: MockVideo[] = [
  {
    video_id: 'rTx5090mLt1',
    slug: 'rtx-5090-melts',
    batch: '2026-10-05T0600Z',
    published: '2026-10-06',
    win: null,
    studio: null,
    style: style('explainer', 'even', 'sounds-made-up', 'production', 'B'),
  },
  {
    video_id: 'iPh18fLd2kQ',
    slug: 'iphone-18-fold',
    batch: '2026-10-07T0600Z',
    published: '2026-10-08',
    win: null,
    studio: null,
    style: style('list', 'staccato', 'number-first', 'release', 'C'),
  },
];

/** Доли просмотров 7 дней по дням: как обычно падает шорт. */
const SHARES = [0.34, 0.22, 0.15, 0.11, 0.08, 0.06, 0.04];

const entryOf = (ch: string, v: MockVideo) => `${ch}/${v.batch}/${v.slug}`;

/** Дневные строки ролика с публикации по END_DAY. Tech — свои просмотры, без окна. */
export function dailyRows(ch: string, v: MockVideo): S['MetricDaily'][] {
  const base = v.win?.views ?? (ch === TECH ? 2600 : 3000);
  const ratio = v.win ? v.win.engaged / v.win.views : 0.6;
  const rows: S['MetricDaily'][] = [];
  for (let age = 0, day = v.published; day <= END_DAY; age += 1, day = addDays(day, 1)) {
    const views = Math.round(base * (SHARES[age] ?? 0.015));
    rows.push({
      channel: ch,
      video_id: v.video_id,
      entry_id: entryOf(ch, v),
      day,
      age,
      views,
      engagedViews: Math.round(views * ratio),
      averageViewPercentage: v.win ? Math.round((v.win.avp - age * 0.6) * 10) / 10 : 55.4,
      averageViewDuration: v.win ? Math.round((v.win.avd - age * 0.2) * 10) / 10 : 18.8,
      likes: Math.round(views * 0.04),
      subscribersGained: Math.round(views * 0.003),
      final: day <= FINAL_UNTIL,
      collected_at: COLLECTED_AT,
    });
  }
  return rows;
}

/** Окно YouTube «первые 7 дней»: полное — если все 7 дней уже прошли к END_DAY. */
export function windowRow(ch: string, v: MockVideo): S['MetricWindow'] | null {
  if (!v.win) return null;
  const end = addDays(v.published, 6);
  const complete = end <= END_DAY;
  const to = complete ? end : END_DAY;
  return {
    channel: ch,
    video_id: v.video_id,
    entry_id: entryOf(ch, v),
    window: 'first7d',
    first_days: 7,
    start: v.published,
    end: to,
    complete,
    views: v.win.views,
    engagedViews: v.win.engaged,
    averageViewPercentage: v.win.avp,
    averageViewDuration: v.win.avd,
    likes: v.win.likes,
    subscribersGained: v.win.subs,
    final: to <= FINAL_UNTIL,
    collected_at: COLLECTED_AT,
    source: 'youtube-analytics reports.query, no dimensions',
    days: complete ? 7 : dailyRows(ch, v).length,
  };
}

export function studioRow(ch: string, v: MockVideo): S['StudioReadRow'] | null {
  if (!v.studio) return null;
  return {
    channel: ch,
    video_id: v.video_id,
    entry_id: entryOf(ch, v),
    read_at: v.studio.read_at,
    hook: 'daily',
    period_text: 'С момента публикации',
    viewed_pct: v.studio.viewed,
    swiped_pct: v.studio.swiped,
    raw_lines: ['Досмотрели', `${v.studio.viewed ?? '—'} %`],
    warnings: [],
    note: v.studio.note ?? null,
    recorded_at: v.studio.read_at,
  };
}

export const LAST_RUN: Record<string, Record<string, unknown> | null> = {
  [REEL]: {
    collected_at: COLLECTED_AT,
    end_day: END_DAY,
    queried: REEL_VIDEOS.map((v) => v.video_id),
    skipped: [],
    rows: { added: 8, replaced: 6, unchanged: 41 },
    unavailable_metrics: {},
    outcome: 'ok',
  },
  [TECH]: {
    collected_at: COLLECTED_AT,
    end_day: END_DAY,
    queried: TECH_VIDEOS.map((v) => v.video_id),
    skipped: [],
    rows: { added: 2, replaced: 2, unchanged: 3 },
    unavailable_metrics: {},
    outcome: 'ok',
  },
  [SCIENCE]: null,
};

// ---------------------------------------------------------------- сводка аналитика

const DIMENSIONS = ['pattern', 'rhythm', 'hook_opener', 'fact_kind', 'tier'] as const;
const METRICS = ['engagedViews', 'averageViewPercentage', 'viewed_pct'] as const;
export const MIN_SAMPLE = 20;

const r2 = (x: number) => Math.round(x * 100) / 100;

function stats(values: (number | null | undefined)[]) {
  const v = values.filter((x): x is number => typeof x === 'number').sort((a, b) => a - b);
  if (!v.length) return { n: 0, median: null, mean: null, min: null, max: null, stdev: null };
  const mid = Math.floor(v.length / 2);
  const median = v.length % 2 ? v[mid]! : (v[mid - 1]! + v[mid]!) / 2;
  const mean = v.reduce((a, b) => a + b, 0) / v.length;
  const stdev =
    v.length >= 2 ? Math.sqrt(v.reduce((a, b) => a + (b - mean) ** 2, 0) / (v.length - 1)) : null;
  return {
    n: v.length,
    median: r2(median),
    mean: r2(mean),
    min: r2(v[0]!),
    max: r2(v[v.length - 1]!),
    stdev: stdev === null ? null : r2(stdev),
  };
}

function videoLine(ch: string, v: MockVideo, collected: boolean): S['SummaryVideo'] {
  const w = collected ? windowRow(ch, v) : null;
  const st = v.studio;
  const published = v.published <= END_DAY;
  const marks: string[] = [];
  if (!v.style) marks.push('нет профиля');
  if (published && !w) marks.push('нет метрик API');
  if (w && !w.final) marks.push('не оконч.');
  if (w && !w.complete) marks.push('окно < 7 д');
  if (published && !st) marks.push('нет чтения Studio');
  else if (st?.note) marks.push('Studio: недостаточно данных');
  return {
    video_id: v.video_id,
    entry_id: entryOf(ch, v),
    slug: v.slug,
    published: v.published,
    age_days: Math.round(
      (Date.parse(`${END_DAY}T00:00:00Z`) - Date.parse(`${v.published}T00:00:00Z`)) / 86_400_000,
    ),
    removed: false,
    is_published: published,
    style: v.style ?? {
      pattern: 'unknown',
      rhythm: 'unknown',
      hook_opener: 'unknown',
      fact_kind: 'unknown',
      tier: 'unknown',
    },
    profile_found: !!v.style,
    profile_gap: v.style ? null : (v.profileGap ?? 'у строки приёмки нет profile'),
    window: w
      ? {
          days: w.days,
          from: w.start,
          to: w.end,
          final: w.final,
          complete: w.complete,
          source: w.source,
          views: w.views,
          engagedViews: w.engagedViews,
          averageViewPercentage: w.averageViewPercentage,
          averageViewDuration: w.averageViewDuration,
        }
      : null,
    api_gap:
      w || !published
        ? null
        : collected
          ? 'нет окна YouTube за 7 д в windows.jsonl (collect его ещё не спросил) - из дневных строк не пересчитывается'
          : 'окно 7 д не собирается для канала (metrics_store.WINDOW_DAYS)',
    studio: st
      ? {
          viewed_pct: st.viewed,
          swiped_pct: st.swiped,
          period_text: 'С момента публикации',
          read_at: st.read_at,
          note: st.note ?? null,
        }
      : null,
    marks,
  };
}

const metricOf = (ln: S['SummaryVideo'], m: (typeof METRICS)[number]) =>
  m === 'viewed_pct'
    ? ((ln.studio?.viewed_pct as number | null | undefined) ?? null)
    : ((ln.window?.[m] as number | null | undefined) ?? null);

/** `summary.build`: та же форма, что пишет `summary.py daily`. */
export function buildSummary(
  ch: string,
  vids: MockVideo[],
  day: string,
  collected: boolean,
  savedDays: string[],
): S['AnalystSummary'] {
  const lines = vids.filter((v) => v.published <= day).map((v) => videoLine(ch, v, collected));
  const counted = lines.filter((l) => l.is_published);
  const aggregates: S['AnalystSummary']['aggregates'] = {};
  for (const dim of DIMENSIONS) {
    const values = [...new Set(counted.map((l) => l.style[dim] ?? 'unknown'))].sort((a, b) =>
      a === 'unknown' ? 1 : b === 'unknown' ? -1 : a.localeCompare(b),
    );
    aggregates[dim] = values.map((value) => {
      const members = counted.filter((l) => l.style[dim] === value);
      const metrics = Object.fromEntries(
        METRICS.map((m) => [m, stats(members.map((l) => metricOf(l, m)))]),
      );
      return {
        value,
        videos: members.length,
        computed_by: 'factory',
        not_final: members.filter((l) => l.window && !l.window.final).length,
        incomplete: members.filter((l) => l.window && !l.window.complete).length,
        metrics,
        small_sample: Object.values(metrics).some((s) => s.n < MIN_SAMPLE),
      };
    });
  }
  return {
    task: 'analyst-summary',
    channel: ch,
    day,
    first_days: 7,
    min_sample: MIN_SAMPLE,
    dimensions: [...DIMENSIONS],
    metrics: [...METRICS],
    sources: {
      videos: 'publish/uploads.json',
      style: 'publish/acceptance-log.json profile (CF-0440)',
      api: `analytics/${ch}/windows.jsonl, window: first 7 day(s) as YouTube Analytics computed it (reports.query without dimensions, CF-0624), ending <= ${day}`,
      studio: `analytics/${ch}/studio.jsonl, last read up to ${day}`,
    },
    counts: {
      videos: lines.length,
      published: counted.length,
      with_profile: lines.filter((l) => l.profile_found).length,
      with_api: lines.filter((l) => l.window).length,
      with_studio: lines.filter((l) => l.studio).length,
      not_final: lines.filter((l) => l.window && !l.window.final).length,
    },
    videos: lines,
    aggregates,
    gaps: {
      no_profile: lines
        .filter((l) => !l.profile_found)
        .map((l) => ({ video_id: l.video_id, entry_id: l.entry_id, why: l.profile_gap })),
      no_metrics: lines
        .filter((l) => !l.window)
        .map((l) => ({
          video_id: l.video_id,
          entry_id: l.entry_id,
          why: l.is_published ? l.api_gap : 'ещё не вышел',
        })),
      no_studio: lines
        .filter((l) => l.is_published && !l.studio)
        .map((l) => ({ video_id: l.video_id, entry_id: l.entry_id })),
    },
    aggregates_computed_by: 'factory',
    aggregates_note:
      'посчитано фабрикой: статистики групп по числам YouTube Analytics роликов этого же владельца (III.E.2.a); исходные числа YouTube - по роликам в таблице «Ролики» и в windows.jsonl',
    saved_days: savedDays,
    saved: savedDays.includes(day),
  };
}

// ---------------------------------------------------------------- нужный футаж

type Row = S['FootageRow'];

const row = (r: Partial<Row> & Pick<Row, 'kind' | 'name' | 'reasons' | 'stages'>): Row => {
  const misses = Object.values(r.reasons).reduce((a, b) => a + b, 0);
  return {
    key: r.name.toLowerCase(),
    topics: 1,
    batches: 1,
    misses,
    first_seen: '2026-10-05T0200Z',
    last_seen: '2026-10-09T0200Z',
    examples: [],
    searched: [],
    supplement_outcomes: {},
    of_topics: [r.name],
    topic_ids: ['lf-2026-10-09-003'],
    batch_ids: ['2026-10-09T0200Z'],
    packed_batches: [],
    in_pool_now: [],
    where: { official_channels: [], candidates: [] },
    ...r,
  };
};

export const FOOTAGE_ROWS: Row[] = [
  row({
    kind: 'work',
    name: 'Rink Rivals',
    topics: 2,
    batches: 2,
    reasons: { anchor_no_picture: 3, pool_too_thin: 2 },
    stages: { editor: 3, scripts: 2 },
    examples: ['Шейн и Илья на льду, финальная сцена', 'постер второго сезона'],
    first_seen: '2026-10-03T0200Z',
    batch_ids: ['2026-10-03T0200Z', '2026-10-09T0200Z'],
    where: {
      official_channels: [{ title: 'Examplevue', id: 'UCcraveOfficial01', for: 'Examplevue' }],
      candidates: [
        {
          video_id: 'hRtrl0Official',
          title: 'Rink Rivals | Official Trailer | Examplevue',
          channel_title: 'Examplevue',
          origin: 'official',
          nature: 'trailer',
          in_pool: false,
        },
      ],
    },
  }),
  row({
    kind: 'person',
    name: 'Diego Marlow',
    reasons: { frame_contradicts: 2 },
    stages: { 'frame-judge': 2 },
    examples: ['диктор называет Педро Паскаля, а в кадре — другой актёр'],
  }),
  row({
    kind: 'event',
    name: 'Orbit Awards 2026',
    reasons: { event_footage_short: 1 },
    stages: { scripts: 1 },
    examples: ['красная дорожка, вручение'],
    in_pool_now: [{ id: 'yt-sat26-red', title: 'Orbit Awards 2026 — red carpet highlights' }],
  }),
  row({
    kind: 'scene',
    name: 'Vanguards: Doomsday — трон Дума',
    reasons: { visual_claim_uncovered: 2 },
    stages: { scripts: 2 },
    examples: ['строка сценария «вот трон, на котором сидит Дум»'],
  }),
  row({
    kind: 'work',
    name: 'Rapid & Reckless 11',
    reasons: { rights_exclusion: 1 },
    stages: { hunter: 1 },
    where: {
      official_channels: [],
      candidates: [
        {
          video_id: 'ff11Teaser0x',
          title: 'RAPID X: Part 2 — teaser (fan upload)',
          channel_title: 'ClipReel Fan',
          origin: 'candidate',
          nature: 'teaser',
          in_pool: true,
        },
      ],
    },
  }),
];

/** Строка, которую видно только с упакованными батчами (архив-том). */
export const PACKED_ROW: Row = row({
  kind: 'work',
  name: 'The Last Ember S2',
  reasons: { no_source: 2 },
  stages: { hunter: 2 },
  first_seen: '2026-09-12T0200Z',
  last_seen: '2026-09-14T0200Z',
  batch_ids: [],
  packed_batches: ['2026-09-12T0200Z', '2026-09-14T0200Z'],
  examples: ['сцена с Элли и Джоэлом в музее'],
});

// ---------------------------------------------------------------- Studio

export const STUDIO_SETTINGS = { last_videos: 5, insurance_hours: 24, hook_min_gap_hours: 6 };
export const STUDIO_URL = (id: string) =>
  `https://studio.youtube.com/video/${id}/analytics/tab-overview/period-default`;
export const LAST_VISIT = {
  read_at: '2026-10-08T18:40:00Z',
  hook: 'daily',
  ui_language: 'ru',
  recorded_at: '2026-10-08T18:52:00Z',
  videos_read: 6,
  videos_stored: 6,
  unstored: [],
  metrics_unrecognised: [],
  metrics_not_ready: ['tL0uS2bRk9m'],
  warnings: [],
};
