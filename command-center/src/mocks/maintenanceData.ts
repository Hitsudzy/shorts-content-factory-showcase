// Данные подставного «Обслуживания и расхода» (CC-0033): как у живой фабрики 14.10 — расход
// батчей ExampleFilm, ExampleTech и ExampleScience по стадиям и моделям, пары прогонов «вручную
// против исполнителя», пул футажа (что освободит уборка, что держат живые темы, сироты), журналы
// батчей с чужими строками и долг месячного архива за сентябрь на диске Archive. Импорты —
// относительные (берут и тесты Playwright).
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export const MAINT_TODAY = '2026-10-14';
export const MAINT_AT = '2026-10-14T09:12:00Z';
export const VOLUME = 'Archive';

/** Батчи с расходом: прошлые батчи истории (src/mocks/batches.ts) и батч Science. */
export const REEL_EXEC = 'example-film/2026-10-09T0215Z';
export const REEL_HAND = 'example-film/2026-10-06T0210Z';
export const TECH_EXEC = 'example-tech/2026-10-07T0200Z';
export const SCIENCE = 'example-science/2026-10-08T0300Z';

const MODEL = {
  opus: 'claude-opus-4-5',
  sonnet: 'claude-sonnet-4-5',
  haiku: 'claude-haiku-4-5',
} as const;

type Spend = [
  stage: string,
  model: keyof typeof MODEL,
  role: string,
  calls: number,
  minutes: number,
  input: number,
  cacheWrite: number,
  cacheRead: number,
  output: number,
  thinking: number,
];

function rows(batch: string, started: string, spend: Spend[]): S['UsageRow'][] {
  let t = Date.parse(started) / 1000;
  return spend.map(([stage, model, role, calls, minutes, input, cw, cr, output, thinking]) => {
    const first = t;
    t += minutes * 60;
    return {
      ts: new Date(t * 1000).toISOString(),
      stage,
      video: null,
      model: MODEL[model],
      role,
      agent: stage,
      session: `${batch.split('/')[1]}-${stage}`,
      calls,
      minutes,
      first,
      last: t,
      computed: '2026-10-13T22:40:00Z',
      window: {
        start: new Date(first * 1000).toISOString(),
        end: new Date(t * 1000).toISOString(),
        slack_s: 30,
      },
      usage: { input, cache_write: cw, cache_read: cr, output, thinking },
    };
  });
}

/** Строки `usage` по батчам; батча нет здесь — событий расхода ещё нет (`ok: false`). */
export const USAGE: Record<string, S['UsageRow'][]> = {
  [REEL_EXEC]: rows(REEL_EXEC, '2026-10-09T02:15:00Z', [
    ['trend-hunter', 'sonnet', 'main', 46, 14.2, 38_400, 92_100, 1_420_000, 21_800, 8_900],
    ['compliance-shortlist', 'haiku', 'main', 12, 3.1, 9_100, 18_600, 210_000, 4_200, 0],
    ['footage-indexer', 'haiku', 'main', 88, 22.5, 61_000, 120_400, 980_000, 33_500, 0],
    ['content-researcher', 'opus', 'main', 64, 31.8, 72_300, 240_800, 2_860_000, 58_100, 41_600],
    ['content-researcher', 'sonnet', 'subagent', 38, 12.4, 28_900, 66_200, 640_000, 19_700, 6_300],
    ['compliance-scripts', 'sonnet', 'main', 21, 6.7, 14_200, 31_000, 380_000, 9_800, 3_100],
    ['video-editor', 'opus', 'main', 52, 41.3, 55_600, 188_300, 2_140_000, 47_900, 22_400],
    ['frame-judge', 'sonnet', 'main', 30, 9.6, 41_800, 52_700, 520_000, 12_600, 4_800],
  ]),
  [TECH_EXEC]: rows(TECH_EXEC, '2026-10-07T02:00:00Z', [
    ['pool-maintenance', 'haiku', 'main', 6, 1.2, 4_300, 9_800, 61_000, 1_900, 0],
    ['trend-hunter', 'sonnet', 'main', 51, 17.9, 44_100, 101_300, 1_610_000, 24_700, 9_800],
  ]),
  [SCIENCE]: rows(SCIENCE, '2026-10-08T03:00:00Z', [
    ['trend-hunter', 'sonnet', 'main', 39, 12.1, 31_200, 84_000, 1_180_000, 18_300, 7_100],
    ['footage-indexer', 'haiku', 'main', 71, 18.4, 49_800, 99_200, 790_000, 27_400, 0],
    ['content-researcher', 'opus', 'main', 58, 29.0, 66_100, 221_500, 2_510_000, 51_200, 36_900],
    ['video-editor', 'opus', 'main', 47, 37.6, 50_200, 171_800, 1_930_000, 43_300, 19_800],
    ['frame-judge', 'sonnet', 'main', 27, 8.8, 37_400, 47_900, 470_000, 11_100, 4_100],
  ]),
};

/** Батчи, о которых фабрика знает, но расход не посчитан (прогон до учёта расхода). */
export const USAGE_NONE = [REEL_HAND];

export const USAGE_WHY =
  'no usage events yet - run scripts/usage_from_transcripts.py <batch> --write first';

export function usageTotals(list: S['UsageRow'][]): S['UsageTotals'] {
  const sum = (k: keyof S['UsageCounters']) => list.reduce((a, r) => a + r.usage[k], 0);
  const input = sum('input');
  const cache_write = sum('cache_write');
  const cache_read = sum('cache_read');
  const output = sum('output');
  const total = input + cache_write + cache_read + output;
  const fresh = input + cache_write + output;
  const pct = (n: number) => (total ? Math.round((n / total) * 1000) / 10 : 0);
  return {
    input,
    cache_write,
    cache_read,
    output,
    thinking: sum('thinking'),
    total,
    fresh,
    calls: list.reduce((a, r) => a + (r.calls ?? 0), 0),
    cache_read_pct: pct(cache_read),
    fresh_pct: pct(fresh),
  };
}

// ---------------------------------------------------------------- сравнение прогонов
const STAGES_FULL = [
  'batch-start',
  'pool-maintenance',
  'trend-hunter',
  'compliance-shortlist',
  'footage-indexer',
  'content-researcher',
  'compliance-scripts',
  'video-editor',
  'frame-judge',
  'batch-done',
];
const FILES = [
  '01_trends.json',
  '02_footage.json',
  '03_scripts.json',
  '04_compliance.json',
  '05_videos.json',
  '06_verdicts.json',
  'RUN_SUMMARY.md',
];

type Side = {
  stages: string[];
  files: string[];
  counts: Record<string, number | null>;
  wall: Record<string, number>;
  wait: number | null;
};

const SIDES: Record<string, Side> = {
  [REEL_HAND]: {
    stages: STAGES_FULL,
    files: FILES,
    counts: {
      'scripts (03)': 5,
      'videos (05)': 4,
      'qc passed (05)': 4,
      'verdicts (06)': 4,
      'mp4 under videos/': 4,
    },
    wall: { stages: 8_940, 'waiting for a human': 1_020, 'operator idle': 270 },
    wait: 1_290,
  },
  [REEL_EXEC]: {
    stages: STAGES_FULL,
    files: FILES,
    counts: {
      'scripts (03)': 4,
      'videos (05)': 3,
      'qc passed (05)': 3,
      'verdicts (06)': 3,
      'mp4 under videos/': 3,
    },
    wall: { stages: 8_320, 'waiting for a human': 0, 'operator idle': 0, unattributed: 300 },
    wait: 300,
  },
  [TECH_EXEC]: {
    stages: ['batch-start', 'pool-maintenance', 'trend-hunter', 'batch-done'],
    files: ['01_trends.json', 'RUN_SUMMARY.md'],
    counts: {
      'scripts (03)': null,
      'videos (05)': null,
      'qc passed (05)': null,
      'verdicts (06)': null,
      'mp4 under videos/': 0,
    },
    wall: { stages: 1_380, unattributed: 120 },
    wait: 120,
  },
  [SCIENCE]: {
    stages: STAGES_FULL.filter((s) => s !== 'compliance-shortlist'),
    files: FILES,
    counts: {
      'scripts (03)': 4,
      'videos (05)': 4,
      'qc passed (05)': 3,
      'verdicts (06)': 4,
      'mp4 under videos/': 4,
    },
    wall: { stages: 7_610, 'waiting for a human': 0, unattributed: 240 },
    wait: 240,
  },
};

export const COMPARABLE = Object.keys(SIDES);

/** `compare_runs.compare` двух батчей: стадии, файлы, выход, время — как у фабрики. */
export function compareOf(manual: string, executor: string): S['CompareRuns'] {
  const m = SIDES[manual]!;
  const e = SIDES[executor]!;
  const defects: string[] = [];
  const notes: string[] = [];
  for (const s of m.stages)
    if (!e.stages.includes(s)) {
      if (s === 'compliance-shortlist')
        notes.push(`stage ${s}: ran by hand, skipped by the plan on its condition (shortlist off)`);
      else defects.push(`stage ${s}: ran by hand, not by the executor`);
    }
  for (const s of e.stages)
    if (!m.stages.includes(s)) defects.push(`stage ${s}: ran by the executor, not by hand`);
  for (const f of [...new Set([...m.files, ...e.files])].sort()) {
    const side = !e.files.includes(f)
      ? 'by hand only'
      : !m.files.includes(f)
        ? 'executor only'
        : null;
    if (side) defects.push(`file ${f}: ${side}`);
  }
  return {
    command: `scripts/compare_runs.py ${manual} ${executor} --json`,
    manual,
    executor,
    stages: { manual: m.stages, executor: e.stages },
    files: { manual: m.files, executor: e.files },
    counts: { manual: m.counts, executor: e.counts },
    wall: {
      manual: m.wall,
      executor: e.wall,
      operator_wait_s: { manual: m.wait, executor: e.wait },
    },
    defects,
    notes,
    same: defects.length === 0,
    exit_code: defects.length ? 1 : 0,
  };
}

// ---------------------------------------------------------------- пул футажа
const GB = 1024 ** 3;
const MB = 1024 ** 2;

const src = (
  video_id: string,
  bytes: number,
  extra: Partial<S['PoolSource']> = {},
): S['PoolSource'] => ({
  video_id,
  files: [`shared/footage/${video_id}.mp4`, `shared/footage/${video_id}.info.json`],
  bytes,
  ...extra,
});

const topic = (
  batches: string[],
  status: string,
  evidence: string[],
  stale: boolean | null = null,
): S['PoolTopic'] => ({ batches, status, evidence, stale });

/** Источники пула: `release` — темы закончены, `keep` — их держит живая тема, `orphan` — ничья. */
export const POOL = {
  release: [
    src('yt-8Hq2LmA0', Math.round(1.42 * GB), {
      topics: {
        'reel-octopus-camouflage': topic([REEL_HAND], 'published', ['uploads.json']),
      },
      newest_batch: REEL_HAND,
      blocked_by: [],
    }),
    src('yt-Qz7vBn31', Math.round(0.86 * GB), {
      topics: {
        'tech-solid-state-battery': topic([TECH_EXEC], 'withdrawn', ['withdrawn']),
      },
      newest_batch: TECH_EXEC,
      blocked_by: [],
    }),
    src('yt-Lm4cX9pe', 640 * MB, {
      topics: {
        'reel-mantis-shrimp-punch': topic([REEL_HAND], 'published', ['uploads.json', 'README.md']),
        'reel-pistol-shrimp': topic([REEL_EXEC], 'published', ['uploads.json']),
      },
      newest_batch: REEL_EXEC,
      blocked_by: [],
    }),
  ],
  keep: [
    src('yt-Rt6uWk02', Math.round(1.1 * GB), {
      topics: {
        'reel-axolotl-regeneration': topic([REEL_EXEC], 'accepted_not_published', [
          'acceptance-log',
        ]),
      },
      newest_batch: REEL_EXEC,
      blocked_by: ['accepted_not_published'],
    }),
    src('yt-Ab9sKd44', 720 * MB, {
      topics: {
        'science-tardigrade-space': topic([SCIENCE], 'accepted_not_published', ['acceptance-log']),
      },
      newest_batch: SCIENCE,
      blocked_by: ['accepted_not_published'],
    }),
    // Тема без ролика из батча старше двух недель: правило «давности» её заканчивает.
    src('yt-Vn3pYe88', 930 * MB, {
      topics: {
        'reel-cuttlefish-hypnosis': topic(['example-film/2026-09-24T0210Z'], 'no_video', [
          'README.md',
        ]),
      },
      newest_batch: 'example-film/2026-09-24T0210Z',
      blocked_by: ['no_video'],
    }),
  ],
  orphan: [
    src('yt-Ke2oPz17', 410 * MB, {
      candidate_of: {
        'science-black-hole-sound': { batches: [SCIENCE], status: 'published' },
      },
      newest_batch: SCIENCE,
      kind: 'refused_candidate',
    }),
    src('yt-Xx0aaB55', 260 * MB, { kind: 'unmentioned' }),
  ],
};

export const POOL_VARIANTS = (orphan: S['PoolSource'][]): S['PoolVariant'][] => {
  const sum = (l: S['PoolSource'][]) => l.reduce((a, s) => a + s.bytes, 0);
  const refused = orphan.filter((s) => s.kind === 'refused_candidate');
  const untopiced = orphan.filter((s) => s.kind === 'untopiced');
  const unmentioned = orphan.filter((s) => s.kind === 'unmentioned');
  return [
    { rule: 'no_video older than 14 d', sources: 1, bytes: 930 * MB },
    { rule: 'no_video+rejected older than 14 d', sources: 1, bytes: 930 * MB },
    {
      rule: 'orphan: refused candidate of finished topics only',
      sources: refused.length,
      bytes: sum(refused),
    },
    {
      rule: 'orphan: untopiced (early batches, fetched[] without a topic)',
      sources: untopiced.length,
      bytes: sum(untopiced),
    },
    {
      rule: 'orphan: no batch on disk mentions it',
      sources: unmentioned.length,
      bytes: sum(unmentioned),
    },
    { rule: 'orphan: all', sources: orphan.length, bytes: sum(orphan) },
  ];
};

// ---------------------------------------------------------------- журналы батчей
const journal = (
  batch: string,
  mode: 'whole' | 'lines',
  lines: number,
  drop: number,
  bytesPerLine: number,
): S['JournalRow'] => ({
  rel: `pipeline/${batch}/RUN_EVENTS.jsonl`,
  mode,
  lines,
  bytes: lines * bytesPerLine,
  drop,
  drop_bytes: drop * bytesPerLine,
  sha: `${batch.replace(/\W/g, '').slice(-12)}a4f0c2e91b7d`.padEnd(64, '0'),
  after: lines - drop,
});

export const JOURNALS: S['JournalRow'][] = [
  journal(REEL_EXEC, 'lines', 1_840, 212, 310),
  journal(SCIENCE, 'whole', 960, 960, 290),
  journal(TECH_EXEC, 'lines', 410, 38, 305),
];

export const JOURNALS_LOG = 'pipeline/cleanup-batch-journals.log';

// ---------------------------------------------------------------- месячный архив
const file = (path: string, bytes: number): S['ArchiveFile'] => ({
  path,
  kind: path.endsWith('.mp4') ? 'mp4' : 'md',
  bytes,
  op: path.endsWith('.mp4') ? 'delete' : 'git rm',
});

function job(channel: string, days: string[], perDay: number): S['ArchiveJob'] {
  const from_publish = days.flatMap((d) => [
    ...Array.from({ length: perDay }, (_, i) =>
      file(`publish/${channel}/${d}/${channel}-${d}-${i + 1}.mp4`, 38 * MB + i * 3 * MB),
    ),
    file(`publish/${channel}/${d}/NOTES.md`, 4_200),
  ]);
  return {
    channel,
    month: '2026-09',
    zip: `${VOLUME}:shorts-content-factory-publish/${channel}/2026-09.zip`,
    action: channel === 'example-film' ? 'extend' : 'create',
    old_members: channel === 'example-film' ? 12 : 0,
    members: (channel === 'example-film' ? 12 : 0) + from_publish.length,
    bytes: from_publish.reduce((a, f) => a + f.bytes, 0),
    from_publish,
    day_dirs: days.map((d) => `publish/${channel}/${d}`),
    status: 'planned',
  };
}

const sept = (from: number, to: number) =>
  Array.from({ length: to - from + 1 }, (_, i) => `2026-09-${String(from + i).padStart(2, '0')}`);

export const ARCHIVE_JOBS: S['ArchiveJob'][] = [
  job('example-film', sept(22, 30), 3),
  job('example-science', sept(26, 30), 2),
  job('example-tech', sept(28, 30), 2),
];

export const ARCHIVE_FREE = 412 * GB;
