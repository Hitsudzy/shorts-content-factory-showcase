// Подставные темы батча (CC-0091/0092): сводка `…/topics` и одна тема `…/topics/{topic_id}`
// на любом этапе батча — только 01 (трендхантер), 01+02 (проверка тем), футаж (01b),
// сценарии (03), их проверка (04), монтаж (05) и проверка кадров (06); `broken` — битый файл
// этапа (`stage_broken`), `none` — трендхантер ещё не закончил, `nothing` — трендхантер
// отсеял всё («нет материала»). Три темы в работе и три
// отсеянных — как «нашёл 3 темы, 3 отсеял». Тела типизированы контрактом; общий для Vitest,
// Playwright и тренировки (через src/mocks/batches.ts). Импорты — относительные.
import type { components } from '../api/schema.gen';
import type { BatchReply } from './schedule';

type S = components['schemas'];

/** Докуда дошёл батч: какие файлы этапов уже записаны. */
export type TopicsLevel =
  'none' | 'nothing' | '01' | '02' | '01b' | '03' | '04' | '05' | 'full' | 'broken';

/**
 * Стадия, которая идёт у батча, когда темы на уровне `level` (первая, чей файл ещё не записан):
 * подставной батч ставится на неё, чтобы лента и строки тем говорили одно (src/mocks/batches.ts).
 */
export const LEVEL_STAGE: Partial<Record<TopicsLevel, string>> = {
  none: 'trend-hunter',
  '01': 'compliance-shortlist',
  '02': 'footage-indexer',
  '01b': 'content-researcher',
  '03': 'compliance-scripts',
  '04': 'video-editor',
  '05': 'frame-judge',
  full: 'batch-done',
};

const ORDER: TopicsLevel[] = ['none', '01', '02', '01b', '03', '04', '05', 'full'];
const reached = (level: TopicsLevel, stage: TopicsLevel) =>
  ORDER.indexOf(level) >= ORDER.indexOf(stage);

const FILES: { stage: string; name: string; file: string; level: TopicsLevel }[] = [
  { stage: 'trend-hunter', name: 'Поиск тем', file: '01-trend-hunter.json', level: '01' },
  {
    stage: 'compliance-shortlist',
    name: 'Проверка тем',
    file: '02-compliance-shortlist.json',
    level: '02',
  },
  { stage: 'footage-indexer', name: 'Футаж', file: '01b-footage-indexer.json', level: '01b' },
  {
    stage: 'content-researcher',
    name: 'Сценарии',
    file: '03-content-researcher.json',
    level: '03',
  },
  {
    stage: 'compliance-scripts',
    name: 'Проверка сценариев',
    file: '04-compliance-scripts.json',
    level: '04',
  },
  { stage: 'video-editor', name: 'Монтаж', file: '05-video-editor.json', level: '05' },
  { stage: 'frame-judge', name: 'Проверка кадров', file: '06-frame-judge.json', level: 'full' },
];

type Seed = {
  id: string;
  title: string;
  kind: string;
  type: string;
  year: number;
  score: number;
  sources: S['TopicSource'][];
  scenes: S['TopicScene'][];
  /** 02: в батч или в резерв. */
  place: 'batch' | 'reserve';
  pool: { shots: number; usable: number; floor: number };
  /** 06: кадры прошли. */
  frames: boolean;
  hook: string;
  fact: { text: string; source: string; url: string };
  videos: S['TopicVideo'][];
  searches: number;
  /** 02: флаг чувствительности (CC-0170): заметка и сцены (`sensitivity_scenes`). */
  sensitivity?: { notes: string; scenes: string[] | 'whole_topic' };
};

const SEEDS: Seed[] = [
  {
    id: 'vanguards-doomsday',
    title: 'Vanguards: Doomsday',
    kind: 'film',
    type: 'movie',
    year: 2026,
    score: 82,
    sources: [
      {
        url: 'https://variety.com/2026/film/news/vanguards-doomsday-trailer-record-1236200001/',
        title: 'Трейлер «Вангвардов» побил рекорд просмотров за сутки',
        publication: 'Variety',
        published_at: '2026-10-09T18:20:00Z',
      },
      {
        url: 'https://deadline.com/2026/10/vanguards-doomsday-box-office-tracking-1236100002/',
        title: 'Прогноз сборов первого уикенда',
        publication: 'Deadline',
        published_at: '2026-10-09T21:05:00Z',
      },
    ],
    scenes: [
      {
        scene_id: 'sc1',
        description: 'Доктор Дум впервые без маски — кадр из трейлера',
        tags: ['трейлер', 'злодей'],
        source_url: 'https://www.youtube.com/watch?v=dd0001',
      },
      {
        scene_id: 'sc2',
        description: 'Сбор команды на руинах Нью-Йорка',
        tags: ['команда'],
        source_url: 'https://www.youtube.com/watch?v=dd0001',
      },
      {
        scene_id: 'sc3',
        description: 'Тор и Капитан Америка спорят о плане',
        tags: ['диалог'],
        source_url: null,
      },
      {
        scene_id: 'sc4',
        description: 'Финальный кадр трейлера: портал над городом',
        tags: ['финал'],
        source_url: 'https://www.youtube.com/watch?v=dd0002',
      },
    ],
    place: 'batch',
    pool: { shots: 64, usable: 41, floor: 24 },
    frames: true,
    hook: 'Роберт Дауни-младший вернулся — но не как Железный человек',
    fact: {
      text: 'Трейлер набрал 202 млн просмотров за 24 часа — рекорд Zenith',
      source: 'Variety',
      url: 'https://variety.com/2026/film/news/vanguards-doomsday-trailer-record-1236200001/',
    },
    videos: [
      {
        video_id: 'dd0001',
        url: 'https://www.youtube.com/watch?v=dd0001',
        title: 'Vanguards: Doomsday — Official Trailer',
        channel_title: 'Zenith Entertainment',
        kind: 'trailer',
        nature: 'official',
        view_count: 202_000_000,
        duration_seconds: 152,
      },
      {
        video_id: 'dd0002',
        url: 'https://www.youtube.com/watch?v=dd0002',
        title: 'Vanguards: Doomsday — Teaser',
        channel_title: 'Zenith Entertainment',
        kind: 'teaser',
        nature: 'official',
        view_count: 48_000_000,
        duration_seconds: 64,
      },
    ],
    searches: 4,
  },
  {
    id: 'delver',
    title: 'Delver',
    sensitivity: { notes: 'кадры обвала с пострадавшими', scenes: ['sc2', 'sc3'] },
    kind: 'film',
    type: 'movie',
    year: 2026,
    score: 67,
    sources: [
      {
        url: 'https://www.hollywoodreporter.com/movies/movie-news/delver-tom-carver-first-look-1236300003/',
        title: 'Первые кадры нового фильма Ибарры с Томом Карвером',
        publication: 'The Hollywood Reporter',
        published_at: '2026-10-08T15:00:00Z',
      },
    ],
    scenes: [
      {
        scene_id: 'sc1',
        description: 'Том Карвер в роли нефтяника посреди пустыни',
        tags: ['первые кадры'],
        source_url: 'https://www.youtube.com/watch?v=dg0001',
      },
      {
        scene_id: 'sc2',
        description: 'Взрыв буровой вышки',
        tags: ['экшен'],
        source_url: 'https://www.youtube.com/watch?v=dg0001',
      },
    ],
    place: 'batch',
    pool: { shots: 30, usable: 18, floor: 24 },
    frames: false,
    hook: 'Том Карвер впервые за 20 лет снялся не в боевике',
    fact: {
      text: 'Съёмки шли 94 дня в пустыне Нью-Мексико',
      source: 'The Hollywood Reporter',
      url: 'https://www.hollywoodreporter.com/movies/movie-news/delver-tom-carver-first-look-1236300003/',
    },
    videos: [
      {
        video_id: 'dg0001',
        url: 'https://www.youtube.com/watch?v=dg0001',
        title: 'Delver — First Look',
        channel_title: 'Example Studios',
        kind: 'trailer',
        nature: 'official',
        view_count: 6_400_000,
        duration_seconds: 98,
      },
    ],
    searches: 3,
  },
  {
    id: 'partition-s3',
    title: 'Partition',
    sensitivity: { notes: 'сцены насилия в офисе', scenes: 'whole_topic' },
    kind: 'series',
    type: 'tv',
    year: 2026,
    score: 58,
    sources: [
      {
        url: 'https://www.indiewire.com/news/partition-season-3-production-1235400004/',
        title: 'Третий сезон «Раздела» начали снимать',
        publication: 'IndieWire',
        published_at: '2026-10-07T12:30:00Z',
      },
    ],
    scenes: [
      {
        scene_id: 'sc1',
        description: 'Коридоры Lumon в тизере третьего сезона',
        tags: ['тизер'],
        source_url: null,
      },
    ],
    place: 'reserve',
    pool: { shots: 22, usable: 20, floor: 24 },
    frames: false,
    hook: '',
    fact: {
      text: 'Сезон снимают в той же офисной декорации, что и первые два',
      source: 'IndieWire',
      url: 'https://www.indiewire.com/news/partition-season-3-production-1235400004/',
    },
    videos: [],
    searches: 2,
  },
];

const SKIPPED: Omit<S['SkippedTopic'], 'state'>[] = [
  {
    topic_id: 'the-running-man',
    title: 'The Running Man',
    kind: 'film',
    popularity_score: 61,
    reason_code: 'no_fact',
    reason_ru: 'за темой не нашлось факта, проходящего правило фактов',
    reason: 'no verifiable fact in the sources',
    stage: 'trend-hunter',
  },
  {
    topic_id: 'wicked-for-good',
    title: 'Charmed: For Good',
    kind: 'film',
    popularity_score: 38,
    reason_code: 'low_signal',
    reason_ru: null,
    reason: 'popularity 38 below the channel floor 45',
    stage: 'trend-hunter',
  },
  {
    topic_id: 'odd-quarter-5',
    title: 'Odd Quarter 5',
    kind: 'series',
    popularity_score: 74,
    reason_code: 'recently_used',
    reason_ru: null,
    reason: 'covered by the channel 6 days ago',
    stage: 'trend-hunter',
  },
];

const SKIPPED_LINE: Record<string, string> = {
  no_fact: 'отсеяна: нет факта',
  low_signal: 'отсеяна: слабый сигнал',
  recently_used: 'отсеяна: тема была недавно',
  thin_pool: 'отсеяна: мало футажа',
};

/**
 * CC-0172 (договор 0.75.0): ремонт роликов после судьи кадров (CF-0881) и добор тем ниже
 * шорт-листа (CF-0882) — только у батча, которому их включили (`setFunnel`), и только когда
 * темы дошли до конца (`full`). У остальных (старые батчи) поля — null.
 */
const REPAIRED: S['VideoRepair'] = {
  outcome: 'repaired',
  reason: null,
  at: '2026-10-09T03:12:00Z',
  blocks: [
    {
      block: 5,
      entry: 'block-5',
      target: 'shot',
      kind: 'thin_strip',
      why: 'thin black strip along the top edge',
    },
    {
      block: 14,
      entry: 'block-14',
      target: 'shot',
      kind: 'thin_strip',
      why: 'letterbox strip at the bottom',
    },
  ],
  before: {
    gate: 'reject',
    reason_code: 'judge_footage_defect',
    reason_ru: 'судья кадров нашёл брак футажа из жёсткого списка',
    score_line: 'кадры 0.52',
  },
  after: { gate: 'pass', reason_code: null, reason_ru: null, score_line: 'кадры 0.88' },
  editor_outcome: 'rendered',
  changed_blocks: [5, 14],
};

const REPAIR_FAILED: S['VideoRepair'] = {
  outcome: 'repair_failed',
  reason: 'замены для блока 9 в пуле не нашлось',
  at: '2026-10-09T03:20:00Z',
  blocks: [
    {
      block: 9,
      entry: 'block-9',
      target: 'shot',
      kind: 'wrong_person',
      why: 'another actor in the shot',
    },
  ],
  before: {
    gate: 'reject',
    reason_code: 'judge_footage_defect',
    reason_ru: 'судья кадров нашёл брак футажа из жёсткого списка',
    score_line: 'кадры 0.41',
  },
  after: null,
  editor_outcome: 'no_replacement',
  changed_blocks: [],
};

/** Ремонт ролика темы в батче с ремонтом: `vanguards-doomsday` — удался, `delver` — нет. */
export const FUNNEL_REPAIRS: Record<string, S['VideoRepair']> = {
  'vanguards-doomsday': REPAIRED,
  delver: REPAIR_FAILED,
};

/** Добор темы из списка тем: `partition-s3` подана в резерв добором (поздний раунд). */
const TOPIC_REFILL: Record<string, S['TopicRefill']> = {
  'partition-s3': {
    outcome: 'admitted',
    round: 'first',
    promoted: false,
    restored: null,
    admitted: true,
    refused_by: null,
    reason: null,
    compliance: {
      outcome: 'eligible',
      verdict: 'pass',
      reason_code: null,
      reason_ru: null,
      reason: null,
    },
    footage: { outcome: 'candidates', searches: 3, at: '2026-10-09T02:41:00Z', reason: null },
  },
};

/** Отсеянные ниже шорт-листа, до которых дошёл добор: отказ проверки темы и «до темы не дошли». */
const REFILL_SKIPPED: S['SkippedTopic'][] = [
  {
    topic_id: 'tron-ares',
    title: 'Grid: Ares',
    kind: 'film',
    popularity_score: 55,
    reason_code: 'below_shortlist',
    reason_ru: null,
    reason: 'rank 5 below the shortlist of 3',
    stage: 'trend-hunter',
    state: {
      phase: 'dropped',
      stage: 'compliance-shortlist',
      line: 'не вошла в шорт-лист; добор: отказ (права на трейлер не подтверждены)',
      reason_code: 'below_shortlist',
      reason_ru: null,
    },
    refill: {
      outcome: 'refused',
      round: 'first',
      promoted: false,
      restored: null,
      admitted: false,
      refused_by: 'compliance',
      reason: 'rights not confirmed',
      compliance: {
        outcome: 'refused',
        verdict: 'refuse',
        reason_code: 'rights_unconfirmed',
        reason_ru: 'права на трейлер не подтверждены',
        reason: 'no rights record for the trailer',
      },
      footage: null,
    },
  },
  {
    topic_id: 'one-battle-after-another',
    title: 'One Battle After Another',
    kind: 'film',
    popularity_score: 52,
    reason_code: 'below_shortlist',
    reason_ru: null,
    reason: 'rank 6 below the shortlist of 3',
    stage: 'trend-hunter',
    state: {
      phase: 'dropped',
      stage: 'trend-hunter',
      line: 'не вошла в шорт-лист',
      reason_code: 'below_shortlist',
      reason_ru: null,
    },
    refill: {
      outcome: 'quota',
      round: 'judge',
      promoted: false,
      restored: null,
      admitted: false,
      refused_by: null,
      reason: 'search quota exhausted',
      compliance: {
        outcome: 'eligible',
        verdict: 'pass',
        reason_code: null,
        reason_ru: null,
        reason: null,
      },
      footage: {
        outcome: 'quota',
        searches: 1,
        at: '2026-10-09T03:25:00Z',
        reason: 'search.list quota left: 0',
      },
    },
  },
];

const REFILL: S['BatchRefill'] = {
  record: 'work/below-shortlist-refill.json',
  admitted: 1,
  searches: 4,
  rounds: [
    {
      round: 'first',
      at: '2026-10-09T02:40:00Z',
      at_code: 'after_compliance',
      need: 1,
      need_why: 'шорт-лист дал 2 темы из 3',
      outcome: 'admitted',
      why: null,
      queue: ['partition-s3', 'tron-ares', 'one-battle-after-another'],
      judged: [
        { topic_id: 'partition-s3', verdict: 'pass', outcome: 'eligible', reason: null },
        {
          topic_id: 'tron-ares',
          verdict: 'refuse',
          outcome: 'refused',
          reason: 'no rights record for the trailer',
        },
      ],
      footage: [{ topic_id: 'partition-s3', outcome: 'candidates', searches: 3, reason: null }],
      admitted: ['partition-s3'],
      searches: 3,
      spent_after: 43,
      budget_line: 'search.list: 3 calls this round, 57 left today',
    },
    {
      round: 'judge',
      at: '2026-10-09T03:25:00Z',
      at_code: 'after_frame_judge',
      need: 1,
      need_why: 'судья кадров отказал ролику delver',
      outcome: 'search_quota',
      // CC-0175 (договор 0.76.0): строка исхода от фабрики; у первого раунда её нет — центр
      // переводит код сам.
      outcome_ru: 'квота поиска на сегодня кончилась',
      why: 'квоты поиска на тему не хватило',
      queue: ['one-battle-after-another'],
      judged: [
        {
          topic_id: 'one-battle-after-another',
          verdict: 'pass',
          outcome: 'eligible',
          reason: null,
        },
      ],
      footage: [
        {
          topic_id: 'one-battle-after-another',
          outcome: 'quota',
          searches: 1,
          reason: 'search.list quota left: 0',
        },
      ],
      admitted: [],
      searches: 1,
      spent_after: 44,
      budget_line: 'search.list: 1 call this round, 0 left today',
    },
  ],
};

/**
 * CC-0175 (договор 0.76.0): записи раундов нет, а строки добора у тем есть — API отдаёт пустой
 * добор, а не null. Центр сводку «подано 0, поисков 0» не показывает.
 */
export const REFILL_NO_ROUNDS: S['BatchRefill'] = {
  record: 'work/below-shortlist-refill.json',
  admitted: 0,
  searches: 0,
  rounds: [],
};

/** Следующий этап темы в батче на уровне `level` (её «в работе: …»). */
function nextStage(level: TopicsLevel): { stage: string; line: string } {
  if (level === '01') return { stage: 'compliance-shortlist', line: 'проверка темы' };
  if (level === '02') return { stage: 'footage-indexer', line: 'футаж' };
  if (level === '01b') return { stage: 'content-researcher', line: 'сценарий' };
  if (level === '03') return { stage: 'compliance-scripts', line: 'проверка сценария' };
  if (level === '04') return { stage: 'video-editor', line: 'монтаж' };
  return { stage: 'frame-judge', line: 'проверка кадров' };
}

function stateOf(seed: Seed, level: TopicsLevel, going: boolean, funnel = false): S['TopicState'] {
  if (reached(level, '02') && seed.place === 'reserve')
    return {
      phase: 'reserve',
      stage: 'compliance-shortlist',
      line: 'в резерве',
      reason_code: null,
    };
  if (level === 'full') {
    const repair = funnel ? FUNNEL_REPAIRS[seed.id] : undefined;
    return seed.frames
      ? {
          phase: 'done',
          stage: 'frame-judge',
          line: repair ? 'ролик готов после ремонта' : 'ролик готов',
          reason_code: null,
        }
      : {
          phase: 'dropped',
          stage: 'frame-judge',
          line: `отсеяна: не прошла проверку кадров${repair ? '; ремонт не удался' : ''}`,
          reason_code: 'judge_footage_defect',
          reason_ru: 'судья кадров нашёл брак футажа из жёсткого списка',
        };
  }
  const next = nextStage(level);
  if (!going)
    return { phase: 'stalled', stage: next.stage, line: `встала: ${next.line}`, reason_code: null };
  return {
    phase: 'in_work',
    stage: next.stage,
    line: `в работе: ${next.line}`,
    reason_code: null,
  };
}

const ref = (s: Seed): S['TitleRef'] => ({
  name: s.title,
  kind: s.kind,
  type: s.type,
  year: s.year,
  season: s.kind === 'series' ? 3 : null,
  network: s.kind === 'series' ? 'Apple TV+' : null,
  parent_work: null,
  person: null,
  rights_holder: null,
});

function summaryOf(
  seed: Seed,
  rank: number,
  level: TopicsLevel,
  going: boolean,
  funnel = false,
): S['TopicSummary'] {
  const full = funnel && level === 'full';
  const inBatch = seed.place === 'batch';
  const deep = seed.pool.usable >= seed.pool.floor;
  const scripted = reached(level, '03') && inBatch;
  return {
    topic_id: seed.id,
    rank,
    title: seed.title,
    kind: seed.kind,
    type: seed.type,
    year: seed.year,
    popularity_score: seed.score,
    sources: seed.sources,
    scenes: seed.scenes.length,
    has_fact: true,
    compliance: reached(level, '02')
      ? {
          verdict: inBatch ? 'pass' : 'hold',
          place: seed.place,
          reason_code: inBatch ? null : 'batch_full',
          reason_ru: null,
          reason: inBatch ? null : 'батч уже набран — тема ждёт в резерве',
          rights_reason: inBatch ? 'трейлер студии, фрагменты до 5 с' : null,
          rights_matched: true,
          sensitivity_flagged: !!seed.sensitivity,
          sensitivity_notes: seed.sensitivity?.notes ?? null,
          sensitivity_scenes: seed.sensitivity?.scenes ?? null,
        }
      : null,
    footage: {
      pool: {
        rule: 'usable >= floor',
        sources: seed.videos.length,
        shots: seed.pool.shots,
        retired: 2,
        usable: seed.pool.usable,
        floor: seed.pool.floor,
        measured: true,
        coverage: 0.8,
        coverage_by: 'shots',
        error: null,
        deep_enough: deep,
      },
      indexer:
        reached(level, '01b') && inBatch
          ? {
              indexed_at: '2026-10-10T05:58:00Z',
              registered_sources: seed.videos.length,
              depth: {
                sources: seed.videos.length,
                shots: seed.pool.shots + 6,
                usable_shots: seed.pool.usable + 4,
                weak_shots: 5,
                available_shots: seed.pool.usable + 4,
                usable_seconds: (seed.pool.usable + 4) * 2.5,
                floor: seed.pool.floor,
                deep_enough: seed.pool.usable + 4 >= seed.pool.floor,
                measured: true,
                at_source_floor: false,
                exhausted: false,
                attempts: 1,
                error: null,
              },
              thin: seed.pool.usable + 4 < seed.pool.floor,
              failed_downloads: deep ? 0 : 1,
              skipped: null,
              warnings: deep ? [] : ['thin_pool'],
              substituted: false,
              substitution: null,
            }
          : null,
    },
    scripts: scripted
      ? [
          {
            script_id: `${seed.id}-s1`,
            scene_id: 'sc1',
            hook: seed.hook,
            duration_s: 48,
            compliance: reached(level, '04')
              ? { verdict: 'pass', contribution: 'pass', passes: true }
              : null,
            video: reached(level, '05')
              ? {
                  slug: seed.id,
                  qc_passed: true,
                  needs_you: false,
                  score_line: 'QC 0.91',
                  refused: null,
                }
              : null,
            frame:
              level === 'full'
                ? seed.frames
                  ? {
                      gate: 'pass',
                      reason_code: null,
                      reason: null,
                      score_line: 'кадры 0.88',
                      repair: (full && FUNNEL_REPAIRS[seed.id]) || null,
                    }
                  : {
                      gate: 'reject',
                      reason_code: 'judge_footage_defect',
                      reason_ru: 'судья кадров нашёл брак футажа из жёсткого списка',
                      reason: 'в 3 кадрах виден водяной знак канала-источника',
                      score_line: 'кадры 0.41',
                      repair: (full && FUNNEL_REPAIRS[seed.id]) || null,
                    }
                : null,
          },
        ]
      : reached(level, '03')
        ? []
        : null,
    state: stateOf(seed, level, going, full),
    refill: (full && TOPIC_REFILL[seed.id]) || null,
  };
}

/** Отсеянные трендхантером; `all` — он отсеял и темы, которые иначе взял бы (мало футажа). */
const skippedOf = (all = false, funnel = false): S['SkippedTopic'][] => [
  ...[
    ...SKIPPED,
    ...(all
      ? SEEDS.map((s) => ({
          topic_id: s.id,
          title: s.title,
          kind: s.kind,
          popularity_score: s.score,
          reason_code: 'thin_pool',
          reason_ru: null,
          reason: `usable shots ${s.pool.usable} below the floor ${s.pool.floor}`,
          stage: 'trend-hunter',
        }))
      : []),
  ].map((s): S['SkippedTopic'] => ({
    ...s,
    state: {
      phase: 'dropped',
      stage: 'trend-hunter',
      line: SKIPPED_LINE[s.reason_code ?? ''] ?? 'отсеяна',
      reason_code: s.reason_code ?? null,
      reason_ru: s.reason_ru ?? null,
    },
    refill: null,
  })),
  ...(funnel ? REFILL_SKIPPED : []),
];

const quota = (): S['SearchQuota'] => ({
  task: 'trend-hunter',
  daily_limit_searches: 100,
  units_per_search: 100,
  resets_at: '2026-10-11T07:00:00Z',
  searches_before_stage: 31,
  spent_searches: 9,
  spent_units: 900,
  remaining_searches: 60,
  remaining_units: 6000,
  spent_api_units: 920,
  spent_units_all: 4020,
  substitutions_made: 0,
  substitutions_affordable: 6,
  summary_line: 'search.list: 9 calls (900 units) this batch, 60 left today',
  searches_by_topic: Object.fromEntries(SEEDS.map((s) => [s.id, s.searches])),
  api_units_by_key: { primary: 920 },
  by_article: null,
});

const notFound = (code: 'unknown_batch' | 'unknown_topic', message: string): BatchReply<never> => ({
  status: 404,
  body: { message, code, details: [] },
});

const broken = (batch: string): BatchReply<never> => ({
  status: 409,
  body: {
    message: 'Данные этапа «Проверка тем» не читаются — темы батча показать нельзя.',
    code: 'stage_broken',
    details: [
      `pipeline/${batch}/02-compliance-shortlist.json`,
      'JSONDecodeError: Expecting value: line 1 column 1 (char 0)',
    ],
  },
});

type Where = {
  batch: string;
  channel: string;
  batch_id: string;
  going: boolean;
  status: string | null;
};

/** Сводка тем батча на уровне `level`. */
export function topicsReply(
  w: Where,
  level: TopicsLevel,
  funnel = false,
  noRounds = false,
): BatchReply<S['BatchTopics']> {
  if (level === 'broken') return broken(w.batch);
  const full = funnel && level === 'full';
  const empty = level === 'nothing';
  const has01 = empty || reached(level, '01');
  if (empty) level = '01';
  return {
    status: 200,
    body: {
      batch: w.batch,
      channel: w.channel,
      batch_id: w.batch_id,
      going: w.going,
      closed: !w.going,
      status: w.status,
      files: FILES.map((f) => ({
        stage: f.stage,
        name: f.name,
        file: f.file,
        present: reached(level, f.level),
        written_at: reached(level, f.level) ? '2026-10-10T06:00:00Z' : null,
      })),
      trend_hunter_done: has01,
      generated_at: has01 ? '2026-10-10T05:41:00Z' : null,
      language: has01 ? 'en' : null,
      sources_used: has01 ? ['rss', 'youtube'] : [],
      selection: has01
        ? {
            stage: 'trend-hunter',
            shortlist_size: empty ? 0 : 3,
            scored: 6,
            viable: empty ? 0 : 4,
            carried: empty ? 0 : 3,
          }
        : null,
      compliance: reached(level, '02')
        ? {
            checked_at: '2026-10-10T05:49:00Z',
            disclaimer: null,
            cut: {
              cut_at: '2026-10-10T05:49:00Z',
              shortlist_size: 3,
              judged: 3,
              eligible: 3,
              carried: 2,
              reserve: 1,
              refused: 0,
              held: 0,
              target: 2,
              target_from: 'channel.videos_per_batch',
              reason_code: null,
              pass_verdicts: ['pass'],
              production_verdicts: ['pass'],
              publish_verdicts: ['pass'],
            },
          }
        : null,
      search_quota: has01 ? quota() : null,
      repairs: full ? { repaired: 1, repair_failed: 1, videos: 2 } : null,
      refill: full ? (noRounds ? REFILL_NO_ROUNDS : REFILL) : null,
      counts: empty
        ? { topics: 0, skipped: 6, in_work: 0, stalled: 0, reserve: 0, dropped: 0, done: 0 }
        : countsOf(level, w.going, full),
      topics: has01 && !empty ? SEEDS.map((s, i) => summaryOf(s, i + 1, level, w.going, full)) : [],
      skipped: has01 ? skippedOf(empty, full) : [],
    },
  };
}

function countsOf(level: TopicsLevel, going: boolean, funnel = false): S['TopicCounts'] {
  const c = { topics: 0, skipped: 0, in_work: 0, stalled: 0, reserve: 0, dropped: 0, done: 0 };
  if (!reached(level, '01')) return c;
  c.topics = SEEDS.length;
  c.skipped = SKIPPED.length + (funnel ? REFILL_SKIPPED.length : 0);
  for (const s of SEEDS) c[stateOf(s, level, going, funnel).phase] += 1;
  return c;
}

/** Одна тема батча на уровне `level` (отсеянная — тоже). */
export function topicReply(
  w: Where,
  level: TopicsLevel,
  topicId: string,
  funnel = false,
): BatchReply<S['BatchTopic']> {
  if (level === 'broken') return broken(w.batch);
  const full = funnel && level === 'full';
  if (!reached(level, '01')) return notFound('unknown_topic', `Темы «${topicId}» в батче нет.`);
  const base = { batch: w.batch, channel: w.channel, batch_id: w.batch_id, going: w.going };
  const i = SEEDS.findIndex((s) => s.id === topicId);
  if (i >= 0) {
    const seed = SEEDS[i]!;
    const summary = summaryOf(seed, i + 1, level, w.going, full);
    return {
      status: 200,
      body: {
        ...base,
        topic_id: topicId,
        searches: { [seed.id]: seed.searches },
        shortlisted: true,
        summary,
        skipped: null,
        title_ref: ref(seed),
        scenes: seed.scenes,
        sources: seed.sources,
        videos: seed.videos,
        fact: {
          probe: {
            outcome: 'found',
            has_fact: true,
            usable: true,
            article: seed.sources[0]?.title ?? null,
            article_url: seed.fact.url,
            source: seed.fact.source,
            candidates: 3,
            detail: null,
            asked_at: '2026-10-10T05:39:00Z',
          },
          // CC-0119 (договор 0.60.0): `failures_ru` — слова фабрики (`fact_rule_ru.reason_ru`)
          // рядом с кодами; у старого кода `tier` слов нет — `ru: null`.
          candidates: [
            {
              text: seed.fact.text,
              kind: 'number',
              source: seed.fact.source,
              url: seed.fact.url,
              section: 'lead',
              passes: true,
              failures: [],
              failures_ru: [],
              scenes: ['sc1'],
            },
            {
              text: 'Фильм самый дорогой в истории студии',
              kind: 'claim',
              source: seed.fact.source,
              url: seed.fact.url,
              section: 'body',
              passes: false,
              failures: ['no_specifics', 'tier'],
              failures_ru: [
                {
                  code: 'no_specifics',
                  ru: 'нет конкретики (числа, даты или имени) - похоже на мнение',
                },
                { code: 'tier', ru: null },
              ],
              scenes: [],
            },
            {
              text: 'Сборы первого уик-энда превысили',
              kind: 'number',
              source: seed.fact.source,
              url: seed.fact.url,
              section: 'body',
              passes: false,
              failures: ['cut_short'],
              failures_ru: [{ code: 'cut_short', ru: 'предложение обрезано' }],
              scenes: [],
            },
          ],
          search: { found: 3, passing: 1, error: null },
          support: {
            state: 'supported',
            detail: 'факт найден в тексте статьи',
            pieces: 1,
            texts: [
              {
                id: 'st1',
                kind: 'article',
                source: seed.fact.source,
                title: seed.sources[0]?.title ?? null,
                url: seed.fact.url,
              },
            ],
          },
          chosen:
            summary.scripts && summary.scripts.length
              ? [
                  {
                    script_id: `${seed.id}-s1`,
                    text: seed.fact.text,
                    kind: 'number',
                    source: seed.fact.source,
                    url: seed.fact.url,
                    primary_url: null,
                    section: 'lead',
                  },
                ]
              : [],
        },
      },
    };
  }
  const sk = skippedOf(false, full).find((s) => s.topic_id === topicId);
  if (!sk) return notFound('unknown_topic', `Темы «${topicId}» в батче нет.`);
  return {
    status: 200,
    body: {
      ...base,
      topic_id: topicId,
      searches: {},
      shortlisted: false,
      summary: null,
      skipped: sk,
      title_ref: {
        name: sk.title ?? null,
        kind: sk.kind ?? null,
        type: null,
        year: null,
        season: null,
        network: null,
        parent_work: null,
        person: null,
        rights_holder: null,
      },
      scenes: [],
      sources: [],
      videos: [],
      fact: {
        probe:
          sk.reason_code === 'no_fact'
            ? {
                outcome: 'no_fact',
                has_fact: false,
                usable: false,
                article: null,
                article_url: null,
                source: null,
                candidates: 0,
                detail: 'в статьях нет проверяемого факта',
                asked_at: '2026-10-10T05:38:00Z',
              }
            : null,
        candidates: [],
        search: null,
        support: null,
        chosen: [],
      },
    },
  };
}
