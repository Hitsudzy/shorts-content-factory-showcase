// Подставное разнообразие ленты (CC-0115 → CC-0108, `GET /api/analytics/diversity`): лента
// принятых роликов Reel и Tech (у Science — пусто), вся фабрика — обе. `last` 0 — вся лента.
// Виды журнала: `ok`, `missing` (журнала нет), `broken` (битый — `log_error`). Импорты —
// относительные (общий для Vitest, Playwright и тренировки).
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export type DiversityLog = 'ok' | 'missing' | 'broken';

type Row = { slug: string; channel: string; f: string; p: string; r: string; h: string | null };

/** В порядке приёмки, старые сначала. */
const FEED: Row[] = [
  {
    slug: 'sandfall-part-three',
    channel: 'example-film',
    f: 'production',
    p: 'list',
    r: 'even',
    h: null,
  },
  {
    slug: 'nolan-odyssey',
    channel: 'example-film',
    f: 'production',
    p: 'explainer',
    r: 'hold',
    h: 'real-reason',
  },
  {
    slug: 'quantum-chip',
    channel: 'example-tech',
    f: 'release',
    p: 'explainer',
    r: 'staccato',
    h: 'number-first',
  },
  {
    slug: 'nightwatch-two',
    channel: 'example-film',
    f: 'casting',
    p: 'contrast',
    r: 'alternate',
    h: 'wildest-fact',
  },
  {
    slug: 'pixel-fold',
    channel: 'example-tech',
    f: 'release',
    p: 'list',
    r: 'even',
    h: 'one-detail',
  },
  {
    slug: 'avatar-four',
    channel: 'example-film',
    f: 'box_office',
    p: 'moment-breakdown',
    r: 'alternate',
    h: null,
  },
  {
    slug: 'blue hours',
    channel: 'example-film',
    f: 'production',
    p: 'list',
    r: 'staccato',
    h: 'sounds-made-up',
  },
  {
    slug: 'mission-final',
    channel: 'example-film',
    f: 'box_office',
    p: 'list',
    r: 'hold',
    h: 'number-first',
  },
  {
    slug: 'gpt-glasses',
    channel: 'example-tech',
    f: 'production',
    p: 'contrast',
    r: 'alternate',
    h: null,
  },
  {
    slug: 'skyman',
    channel: 'example-film',
    f: 'production',
    p: 'explainer',
    r: 'even',
    h: 'real-reason',
  },
  {
    slug: 'the-nightwatch-part-ii',
    channel: 'example-film',
    f: 'casting',
    p: 'list',
    r: 'alternate',
    h: 'wildest-fact',
  },
  {
    slug: 'weekend-night-live',
    channel: 'example-film',
    f: 'production',
    p: 'explainer',
    r: 'hold',
    h: null,
  },
];

const AXES: [S['DiversityAxis']['key'], string, keyof Row][] = [
  ['fact_kind', 'вид факта', 'f'],
  ['pattern', 'паттерн', 'p'],
  ['rhythm', 'ритм', 'r'],
  ['hook_opener', 'зачин хука', 'h'],
];

export function diversityReply(
  channel: string | null,
  last: number,
  log: DiversityLog = 'ok',
): S['FeedDiversity'] {
  const rows = log === 'ok' ? FEED.filter((r) => !channel || r.channel === channel) : [];
  const taken = last > 0 ? rows.slice(-last) : rows;
  const n = taken.length;
  const axes = AXES.map(([key, label, field]) => {
    const counts = new Map<string, number>();
    for (const r of taken) {
      const v = (r[field] as string | null) ?? 'unknown';
      counts.set(v, (counts.get(v) ?? 0) + 1);
    }
    const values = [...counts]
      .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
      .map(([value, count]) => ({ value, count, share: Math.round((count / n) * 1000) / 1000 }));
    return { key, label, values };
  });
  const where = channel ? ` канала ${channel}` : '';
  return {
    last,
    channel,
    n,
    videos: taken.map((r) => r.slug),
    read_live: n > 2 ? [taken[n - 1]!.slug] : [],
    axes,
    lines: [
      `Разнообразие ленты${where}: последние ${n} роликов (${taken.map((r) => r.slug).join(', ') || 'нет'})`,
      ...axes.map(
        (a) =>
          `  ${a.label}: ${a.values.map((v) => `${v.value} ${v.count} (${Math.round(v.share * 100)}%)`).join(', ') || '-'}`,
      ),
    ],
    log: 'publish/acceptance-log.json',
    log_exists: log !== 'missing',
    log_read: log === 'ok',
    log_error:
      log === 'broken'
        ? 'publish/acceptance-log.json: not JSON (Expecting value: line 1 column 1 (char 0))'
        : null,
  };
}
