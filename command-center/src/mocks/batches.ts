// Подставные батчи фабрики (CC-0044/0045) — с состоянием: идущий батч, остановленная
// пересборка, файл событий с курсором (`more`/`reset`), история прогонов, стадии и журналы.
// Общий для Vitest (MSW, src/mocks/handlers.ts) и Playwright (tests/e2e/fixtures.ts). Тела
// ответов типизированы сгенерированными типами контракта; курсор и хвост журнала — по
// правилам `api/batches.py` (целые строки, байтовые смещения). Данные выдуманные, но по
// форме как у живой фабрики. Импорты — относительные.
import type { components } from '../api/schema.gen';
import { createActions, routeActions } from './batchActions';
import { LEVEL_STAGE, topicReply, topicsReply, type TopicsLevel } from './batchTopics';
import { summaryReply, type SummaryKind } from './runSummary';
import type { BatchReply } from './schedule';
import { MOCK_NOW } from './schedule';

type S = components['schemas'];

const notFound = (code: 'unknown_batch' | 'unknown_log', message: string): BatchReply<never> => ({
  status: 404,
  body: { message, code, details: [] },
});

const bytes = (s: string) => new TextEncoder().encode(s).length;
const at = (min: number) =>
  new Date(Date.parse(MOCK_NOW) + min * 60_000).toISOString().replace('.000Z', 'Z');

/** Путь идущего батча, остановленной пересборки и прогонов истории. */
export const RUNNING = 'example-film/2026-10-10T0530Z';
export const STOPPED = 'rebuilds/2026-10-10T0410Z';
export const PAST = 'example-film/2026-10-09T0215Z';
export const PAST_REBUILD = 'rebuilds/2026-10-08T1208Z';

/**
 * Порядок стадий плана прогона — как у живой фабрики (run_plan батча
 * example-science/2026-10-12T2001Z, CC-0090): футаж раньше исследования, резерв и добор — после.
 */
export const ORDER = [
  'studio-read-due',
  'rights-check',
  'batch-start',
  'pool-maintenance',
  'trend-hunter',
  'compliance-shortlist',
  'footage-indexer',
  'content-researcher',
  'footage-indexer-reserve',
  'content-researcher-reserve',
  'thin-pool-supplement',
  'plan-check-after-supplement',
  'footage-indexer-reserve-late',
  'content-researcher-reserve-late',
  'thin-pool-supplement-late',
  'plan-check-after-supplement-late',
  'compliance-scripts',
  'video-editor',
  'frame-judge',
  'batch-done',
  'monitors',
  'triage',
  'rotation-backfill',
  'footage-wanted',
  'commit-records',
] as const;

/** Резерв и добор (стадии 9–16 плана): в подставных прогонах не понадобились. */
const NOT_NEEDED_IDS = new Set<string>(ORDER.slice(8, 16));

/**
 * Стадии упавшего батча — как в run-state.json живого example-science/2026-10-12T1908Z (CC-0095):
 * batch-start упал, всё основное после него фабрика пометила `skipped` («after failed stage
 * batch-start»), стадии закрытия (batch-done, monitors, triage) тоже упали, хвост
 * (rotation-backfill, footage-wanted, commit-records) прошёл.
 */
export const FAILED_AT_START_STAGES: { id: string; status: string }[] = ORDER.map((id, i) => {
  const at = ORDER.indexOf('batch-start');
  if (i < at) return { id, status: 'done' };
  if (i === at) return { id, status: 'failed' };
  if (id === 'batch-done' || id === 'monitors' || id === 'triage') return { id, status: 'failed' };
  if (id === 'rotation-backfill' || id === 'footage-wanted' || id === 'commit-records')
    return { id, status: 'done' };
  return { id, status: 'skipped' };
});

/**
 * План с машинной стадией CF-0707 (CC-0111): роликов на проверку нет — `frame-judge-empty`
 * записала пустой итог, `frame-judge` пропущена с причиной; батч закрывается (идёт batch-done).
 */
export const EMPTY_JUDGE_STAGES: { id: string; status: string }[] = ORDER.flatMap((id) =>
  id === 'frame-judge' ? ['frame-judge-empty', id] : [id],
).map((id) => {
  const i = ORDER.indexOf(id as (typeof ORDER)[number]);
  const close = ORDER.indexOf('batch-done');
  const status =
    id === 'frame-judge'
      ? 'skipped'
      : id === 'batch-done'
        ? 'running'
        : i > close
          ? 'pending'
          : NOT_NEEDED_IDS.has(id)
            ? 'skipped'
            : 'done';
  return { id, status };
});

/**
 * Раунд добора из резерва после отказа судьи кадра (фабрика 2.16, CF-0798/0802, CC-0150): семь
 * стадий `*-judge` между `frame-judge` и `batch-done` в плане каждого канала. Все — `updates`;
 * без `reserve_after_judge` фабрика их пропускает.
 */
export const JUDGE_ROUND = [
  'footage-indexer-reserve-judge',
  'content-researcher-reserve-judge',
  'thin-pool-supplement-judge',
  'plan-check-after-supplement-judge',
  'compliance-scripts-judge',
  'video-editor-judge',
  'frame-judge-judge',
] as const;

/** План прогона фабрики 2.16: `ORDER` с раундом добора после судьи кадра. */
export const ORDER_JUDGE: string[] = ORDER.flatMap((id) =>
  id === 'frame-judge' ? [id, ...JUDGE_ROUND] : [id],
);

/**
 * Стадии плана 2.16: до `current` — готово (резерв и добор основного прохода — `skipped`, раунд
 * после судьи — по `round`: стадии из него готовы, остальные — `skipped`), `current` — идёт,
 * дальше — ждёт.
 */
const judgePlan = (current: string, round: readonly string[]) =>
  ORDER_JUDGE.map((id, i) => {
    const c = ORDER_JUDGE.indexOf(current);
    const spare = NOT_NEEDED_IDS.has(id) || (JUDGE_ROUND as readonly string[]).includes(id);
    const before = spare && !round.includes(id) ? 'skipped' : 'done';
    return { id, status: i < c ? before : i === c ? 'running' : 'pending' };
  });

/** Идёт проверка кадров: раунд добора впереди — «только если нужно». */
export const JUDGE_ROUND_AHEAD_STAGES = judgePlan('frame-judge', []);

/** Судья кадра роликам не отказал: раунд добора пропущен, батч закрывается. */
export const JUDGE_ROUND_SKIPPED_STAGES = judgePlan('batch-done', []);

/**
 * Судья кадра отказал: раунд добора идёт — резерв футажа и сценариев взяты, проверка сценариев
 * прошла, идёт монтаж повтора; добор тонкого пула не понадобился.
 */
export const JUDGE_ROUND_GOING_STAGES = judgePlan('video-editor-judge', [
  'footage-indexer-reserve-judge',
  'content-researcher-reserve-judge',
  'compliance-scripts-judge',
]);

/** Раунд добора после судьи прошёл (повторная проверка кадров тоже), батч закрывается. */
export const JUDGE_ROUND_DONE_STAGES = judgePlan('batch-done', [
  'footage-indexer-reserve-judge',
  'content-researcher-reserve-judge',
  'compliance-scripts-judge',
  'video-editor-judge',
  'frame-judge-judge',
]);

/**
 * Упавшие батчи (CC-0089, `GET /api/batches/stranded`): батч остановился плохо, в истории его
 * нет и он не открыт. Первый — как живой example-science/2026-10-12T1908Z: упал на batch-start,
 * держит день («1 батч в сутки»), продолжить можно. Второй — вчерашний, остановлен на
 * trend-hunter, день не держит, фабрика продолжать отказывает. По умолчанию их нет:
 * `strand()` (тренировка, сценарии и скриншоты CC-0089).
 */
export const STRANDED_FAILED = 'example-science/2026-10-10T0405Z';
export const STRANDED_STOPPED = 'example-film/2026-10-09T1410Z';
/** Отказ `resume/plan` второго — словами фабрики. */
export const STRANDED_REFUSAL =
  'батч вчерашний (2026-10-09): день батча прошёл, темы и квота поиска - уже не его; продолжать нельзя, запустите новый батч';
export const STRANDED_REASON =
  'step 0 (runlog batch-start) exited 2; log logs/batch-start.s0.a0.log';

/**
 * Правка кода стадией (CC-0111, CF-0713) — как ночью 12–13.10: разметка футажа сама добавила
 * блокировку в `scripts/source_rights.py` своего агента, не закоммитив.
 */
export const FOOTAGE_CODE_EDIT: S['StageCodeEdit'] = {
  stage: 'footage-indexer',
  run: 'footage-indexer.s0',
  at: '2026-10-10T06:41:12Z',
  mode: 'warn',
  task: 'CF-0713',
  edits: [
    {
      repo: 'agents/footage-indexer',
      files: ['scripts/source_rights.py'],
      head_was: null,
      head_now: null,
    },
  ],
  files: ['agents/footage-indexer/scripts/source_rights.py'],
  line: 'agents/footage-indexer: scripts/source_rights.py',
  source: 'state',
};

/** Правка с коммитом: проверка сценариев закоммитила свою правку в корень фабрики. */
export const SCRIPTS_CODE_EDIT: S['StageCodeEdit'] = {
  stage: 'compliance-scripts',
  run: 'compliance-scripts.s0',
  at: '2026-10-10T07:12:40Z',
  mode: 'warn',
  task: 'CF-0713',
  edits: [
    {
      repo: 'root',
      files: ['shared/runlog/funnel.py', 'shared/compliance/claims_check.py'],
      head_was: '4f1c2a9e0b7d5c3a1f8e6d4b2a0c9e7f5d3b1a08',
      head_now: '9a8b7c6d5e4f3a2b1c0d9e8f7a6b5c4d3e2f1a0b',
    },
  ],
  files: ['shared/runlog/funnel.py', 'shared/compliance/claims_check.py'],
  line: 'root: shared/runlog/funnel.py, shared/compliance/claims_check.py (commit 4f1c2a9e0b..9a8b7c6d5e)',
  source: 'events',
};

/** Строка списка батчей для правки (консоль: «<стадия>: <репо>: <файлы>»). */
const codeEditLine = (e: S['StageCodeEdit']) =>
  `${e.stage ?? '?'}: ${e.edits.map((r) => `${r.repo ?? '?'}: ${r.files.join(', ')}`).join('; ')}`;

/** Резерв и добор в этих прогонах не понадобились: фабрика пишет им `skipped`. */
const NOT_NEEDED = NOT_NEEDED_IDS;
/** Стадии, которые прогон действительно запускал (пролёты `…/stages`). */
const RAN: string[] = ORDER.filter((id) => !NOT_NEEDED.has(id));

const stagesUpTo = (current: string, status: string) =>
  ORDER.map((id) => {
    const i = ORDER.indexOf(id);
    const c = ORDER.indexOf(current as (typeof ORDER)[number]);
    const before = NOT_NEEDED.has(id) ? 'skipped' : 'done';
    return { id, status: i < c ? before : i === c ? status : 'pending' };
  });

type Open = {
  going: S['BatchesGoing']['batches'][number];
  state: S['RunState'];
  questions: S['Question'][];
  /** Строки RUN_EVENTS.jsonl. */
  lines: string[];
  logs: Record<string, string>;
  /** Исполнитель умер, не записав конца (CC-0094): см. `ActionTarget.dead`. */
  dead?: boolean;
  /** Стадии правили код фабрики (CC-0111, CF-0713 `code_edits[]`). */
  codeEdits?: S['StageCodeEdit'][];
};

type Past = { run: S['BatchRun']; logs: Record<string, string>; stages: string[] };

const event = (n: number, stage: string, status: string, extra: Record<string, unknown> = {}) =>
  JSON.stringify({
    ts: at(-60 + n),
    kind: n % 7 === 0 ? 'marker' : 'step',
    stage,
    video: n % 3 ? 'vanguards-doomsday' : 'delver',
    step: n % 7 === 0 ? null : `edit-${n}`,
    status,
    duration_s: n % 7 === 0 ? null : 12.5,
    id: `e${String(n).padStart(5, '0')}`,
    ...extra,
  });

const LOG_LINES = (stage: string, n: number) =>
  Array.from(
    { length: n },
    (_, i) =>
      `${at(-30 + i / 10)} [${stage}] шаг ${i + 1}: ${i % 5 === 4 ? 'WARN медленный ответ' : 'ok'}`,
  ).join('\n') + '\n';

const question = (): S['Question'] => ({
  id: 'Q41',
  n: 41,
  key: 'studio-read@example-film',
  source: 'studio-read',
  channel: 'example-film',
  text: 'Студия YouTube давно не читалась: открыть её в Chrome и разрешить чтение?',
  link: null,
  created: at(-80),
  created_by: 'run-executor',
  updated: at(-80),
  status: 'open',
  answer: null,
  answered_by: null,
  answered_at: null,
  resolved_by: null,
  resolved_at: null,
  note: null,
  suggestion: null,
  suggestion_why: null,
  suggested_by: null,
  suggested_at: null,
  answered_via: null,
  accepted_suggestion: false,
});

function running(): Open {
  const stages = stagesUpTo('video-editor', 'running');
  return {
    going: {
      batch: RUNNING,
      code_edits: null,
      code_edits_count: 0,
      dir: 'pipeline/example-film',
      batch_id: '2026-10-10T0530Z',
      fresh: true,
      last_event: at(-1),
      channel: 'example-film',
      source: 'run-state.json (CF-0203)',
      status: 'running',
      stages,
      next: 'frame-judge',
      needs_human: ['studio-read: skipped_no_permission'],
      halt_reason: null,
      state_error: null,
      started: at(-90),
      stage: 'video-editor',
      stage_started: at(-20),
      elapsed_s: 90 * 60,
      stage_elapsed_s: 20 * 60,
      stage_timeout_min: 90,
      estimate: { mean_wall_s: 150 * 60, runs: 5, left_s: 60 * 60 },
    },
    state: {
      channel: 'example-film',
      batch: `pipeline/${RUNNING}`,
      batch_id: '2026-10-10T0530Z',
      status: 'running',
      created: at(-90),
      order: [...ORDER],
      stages: Object.fromEntries(stages.map((s) => [s.id, { status: s.status }])),
      current: { stage: 'video-editor' },
      next: 'frame-judge',
      runs: {
        'content-researcher.s0.a0': {
          stage: 'content-researcher',
          pid: 4101,
          pgid: 4101,
          started: at(-60),
          ended: at(-35),
          log: 'logs/content-researcher.s0.a0.log',
          exit: 0,
          restarts: 0,
          alive: false,
        },
        'video-editor.s0.a0': {
          stage: 'video-editor',
          pid: 4188,
          pgid: 4188,
          started: at(-20),
          ended: null,
          log: 'logs/video-editor.s0.a0.log',
          exit: null,
          restarts: 1,
          alive: true,
        },
      },
      reruns: { 'video-editor.s0': 1 },
      needs_human: [
        {
          stage: 'studio-read',
          key: 'studio-read@studio-read-due.s0.a0',
          question: 'Студия канала давно не читалась: есть ли Chrome и разрешение?',
          took: 'skipped_no_permission',
          at: at(-90),
        },
      ],
      halt_reason: null,
      stops: null,
    },
    questions: [question()],
    lines: Array.from({ length: 30 }, (_, i) => event(i, 'video-editor', 'ok')),
    logs: {
      'video-editor.s0.a0.log': LOG_LINES('video-editor', 400),
      'content-researcher.s0.a0.log': LOG_LINES('content-researcher', 12),
    },
  };
}

/** Батч, только что запущенный центром: первая стадия, исполнитель и шаг живы. */
function launchedRun(channel: string, batchId: string): Open {
  const r = running();
  const batch = `${channel}/${batchId}`;
  const stages = stagesUpTo('trend-hunter', 'running');
  return {
    ...r,
    going: {
      ...r.going,
      batch,
      dir: `pipeline/${channel}`,
      batch_id: batchId,
      channel,
      last_event: MOCK_NOW,
      stages,
      stage: 'trend-hunter',
      next: 'compliance-shortlist',
      needs_human: [],
      started: MOCK_NOW,
      stage_started: MOCK_NOW,
      elapsed_s: 0,
      stage_elapsed_s: 0,
      estimate: { mean_wall_s: 150 * 60, runs: 5, left_s: 150 * 60 },
    },
    state: {
      ...r.state,
      channel,
      batch: `pipeline/${batch}`,
      batch_id: batchId,
      created: MOCK_NOW,
      stages: Object.fromEntries(stages.map((s) => [s.id, { status: s.status }])),
      current: { stage: 'trend-hunter' },
      next: 'compliance-shortlist',
      runs: {
        'trend-hunter.s0.a0': {
          stage: 'trend-hunter',
          pid: 5210,
          pgid: 5210,
          started: MOCK_NOW,
          ended: null,
          log: 'logs/trend-hunter.s0.a0.log',
          exit: null,
          restarts: 0,
          alive: true,
        },
      },
      reruns: null,
      needs_human: null,
    },
    questions: [],
    lines: Array.from({ length: 3 }, (_, i) => event(i, 'trend-hunter', 'ok')),
    logs: { 'trend-hunter.s0.a0.log': LOG_LINES('trend-hunter', 5) },
  };
}

function stopped(): Open {
  const stages = stagesUpTo('video-editor', 'stopped');
  return {
    going: {
      batch: STOPPED,
      code_edits: null,
      code_edits_count: 0,
      dir: 'pipeline/rebuilds',
      batch_id: '2026-10-10T0410Z',
      fresh: true,
      last_event: at(-150),
      channel: 'example-tech',
      source: 'run-state.json (CF-0203)',
      status: 'stopped',
      stages,
      next: 'video-editor',
      needs_human: [],
      halt_reason: 'остановлен пользователем (центр): ждёт «продолжить»',
      state_error: null,
      started: at(-170),
      stage: 'video-editor',
      stage_started: at(-160),
      elapsed_s: 170 * 60,
      stage_elapsed_s: 160 * 60,
      stage_timeout_min: 90,
      estimate: { mean_wall_s: 100 * 60, runs: 2, left_s: -70 * 60 },
    },
    state: {
      channel: 'example-tech',
      batch: `pipeline/${STOPPED}`,
      batch_id: '2026-10-10T0410Z',
      status: 'stopped',
      created: at(-170),
      order: [...ORDER],
      stages: Object.fromEntries(stages.map((s) => [s.id, { status: s.status }])),
      current: { stage: 'video-editor' },
      next: 'video-editor',
      runs: {
        'video-editor.s0.a0': {
          stage: 'video-editor',
          pid: 3920,
          pgid: 3920,
          started: at(-160),
          ended: at(-150),
          log: 'logs/video-editor.s0.a0.log',
          exit: -15,
          restarts: 0,
          alive: false,
        },
      },
      reruns: null,
      needs_human: null,
      halt_reason: 'остановлен пользователем (центр): ждёт «продолжить»',
      stops: [
        {
          at: at(-150),
          by: 'user (центр)',
          task: 'CF-0667',
          executor_pid: 3901,
          executor_pgid: 3901,
          previous_status: 'running',
          stage: 'video-editor',
          also_step: true,
          step: { run: 'video-editor.s0.a0', pid: 3920, killed: true, left_running: false },
        },
      ],
      rebuild: {
        task: 'CF-0668',
        mode: 'reedit',
        title: 'Перемонтаж',
        of: {
          channel: 'example-tech',
          batch_id: '2026-10-08T0200Z',
          path: 'pipeline/example-tech/2026-10-08T0200Z',
        },
        videos: [{ slug: 'quiet-keyboards' }, { slug: 'usb-c-myths' }],
        notes: 'короче вступление',
        by: 'user (центр)',
        at: at(-171),
      },
    },
    questions: [],
    lines: Array.from({ length: 8 }, (_, i) => event(i, 'video-editor', 'ok')),
    logs: { 'video-editor.s0.a0.log': LOG_LINES('video-editor', 6) },
  };
}

/** Упавший батч: строка списка идущих (для действий), run-state, журналы и строка `stranded`. */
type Strand = Open & {
  holdsDay: boolean;
  /** Отказ `resume/plan`; нет — продолжить можно. */
  refuse?: string;
  reason: string | null;
  /** Журнал стадии — имя в `logs/` батча. */
  logName: string | null;
  created: string;
  updated: string;
};

const BATCH_START_LOG = [
  '[runlog] batch-start example-science 2026-10-10T0405Z',
  '[runlog] checking the working tree before the batch',
  'error: the working tree is not clean (2 paths) - commit or revert them first:',
  '  M channels/example-science/rights-holder-blacklist.json',
  '  ?? channels/example-science/rights-check.2026-10-10.json',
  '[runlog] batch-start refused: dirty tree after rights-check (CF-0704)',
  'exit 2',
  '',
].join('\n');

function strandedFailed(): Strand {
  const id = '2026-10-10T0405Z';
  const stages = FAILED_AT_START_STAGES.map((s) => ({
    ...s,
    reason:
      s.id === 'batch-start'
        ? STRANDED_REASON
        : s.status === 'skipped'
          ? 'after failed stage batch-start'
          : null,
  }));
  return {
    going: {
      batch: STRANDED_FAILED,
      code_edits: null,
      code_edits_count: 0,
      dir: 'pipeline/example-science',
      batch_id: id,
      fresh: false,
      last_event: null,
      channel: 'example-science',
      source: 'run-state.json (CF-0203)',
      status: 'failed',
      stages,
      next: 'batch-start',
      needs_human: [],
      halt_reason: null,
      state_error: null,
      started: at(-175),
      stage: 'batch-start',
      stage_started: at(-174),
      elapsed_s: null,
      stage_elapsed_s: null,
      stage_timeout_min: 10,
      estimate: null,
    },
    state: {
      channel: 'example-science',
      batch: `pipeline/${STRANDED_FAILED}`,
      batch_id: id,
      status: 'failed',
      created: at(-176),
      order: [...ORDER],
      stages: Object.fromEntries(stages.map((s) => [s.id, { status: s.status, reason: s.reason }])),
      current: { stage: 'batch-start' },
      next: 'batch-start',
      runs: {
        'batch-start.s0.a0': {
          stage: 'batch-start',
          pid: 3810,
          pgid: 3810,
          started: at(-174),
          ended: at(-174),
          log: 'logs/batch-start.s0.a0.log',
          exit: 2,
          restarts: 0,
          alive: false,
        },
      },
      reruns: null,
      needs_human: null,
      halt_reason: null,
    },
    questions: [],
    lines: [],
    logs: { 'batch-start.s0.a0.log': BATCH_START_LOG },
    holdsDay: true,
    reason: STRANDED_REASON,
    logName: 'batch-start.s0.a0.log',
    created: at(-176),
    updated: at(-170),
  };
}

function strandedStopped(): Strand {
  const id = '2026-10-09T1410Z';
  const stages = stagesUpTo('trend-hunter', 'stopped').map((s) => ({ ...s, reason: null }));
  const halt = 'остановлен пользователем (центр): ждёт «продолжить»';
  return {
    going: {
      batch: STRANDED_STOPPED,
      code_edits: null,
      code_edits_count: 0,
      dir: 'pipeline/example-film',
      batch_id: id,
      fresh: false,
      last_event: at(-1000),
      channel: 'example-film',
      source: 'run-state.json (CF-0203)',
      status: 'stopped',
      stages,
      next: 'trend-hunter',
      needs_human: [],
      halt_reason: halt,
      state_error: null,
      started: at(-1010),
      stage: 'trend-hunter',
      stage_started: at(-1005),
      elapsed_s: null,
      stage_elapsed_s: null,
      stage_timeout_min: 40,
      estimate: null,
    },
    state: {
      channel: 'example-film',
      batch: `pipeline/${STRANDED_STOPPED}`,
      batch_id: id,
      status: 'stopped',
      created: at(-1010),
      order: [...ORDER],
      stages: Object.fromEntries(stages.map((s) => [s.id, { status: s.status }])),
      current: { stage: 'trend-hunter' },
      next: 'trend-hunter',
      runs: {},
      reruns: null,
      needs_human: null,
      halt_reason: halt,
    },
    questions: [],
    lines: [],
    logs: { 'trend-hunter.s0.a0.log': LOG_LINES('trend-hunter', 4) },
    holdsDay: false,
    refuse: STRANDED_REFUSAL,
    reason: halt,
    logName: 'trend-hunter.s0.a0.log',
    created: at(-1010),
    updated: at(-1000),
  };
}

/** Строка `GET /api/batches/stranded` упавшего батча — как `batch_schedule.stranded_batches`. */
function strandedRow(s: Strand): S['StrandedBatch'] {
  const dir = `${s.going.dir}/${s.going.batch_id}`;
  return {
    dir,
    batch: s.going.batch,
    log_name: s.logName ?? null,
    channel: s.going.channel ?? null,
    batch_id: s.going.batch_id,
    status: s.going.status ?? null,
    created: s.created,
    updated: s.updated,
    stage: s.going.stage ?? null,
    reason: s.reason,
    log: s.logName ? `${dir}/logs/${s.logName}` : null,
    log_url: s.logName ? `/api/batches/${s.going.batch}/logs/${s.logName}` : null,
    halt_reason: s.going.halt_reason ?? null,
    stages: (s.going.stages ?? []).map((g) => ({
      id: g.id ?? null,
      status: g.status ?? null,
      reason: g.reason ?? null,
    })),
    holds_day: s.holdsDay,
  };
}

function history(): Past[] {
  const run = (
    batch: string,
    channel: string,
    started: string,
    wall: number | null,
    outcome: string | null,
    launch: S['Launch'] | null,
    videos: number | null,
  ): S['BatchRun'] => ({
    batch,
    id: batch.split('/')[1]!,
    channel,
    date: started.slice(0, 10),
    started,
    ended: wall == null ? null : new Date(Date.parse(started) + wall * 1000).toISOString(),
    videos,
    wall_s: wall,
    outcome,
    launch,
  });
  const all = [...RAN];
  return [
    {
      run: run(
        PAST,
        'example-film',
        '2026-10-09T02:15:00Z',
        8619.6,
        'videos',
        {
          at: '2026-10-09T02:14:58Z',
          day: '2026-10-09',
          channel: 'example-film',
          by: 'tick',
          kind: 'schedule',
          why: 'лента короче 3 дн.',
        },
        3,
      ),
      stages: all,
      logs: {
        'video-editor.s0.a0.log': LOG_LINES('video-editor', 2000),
        'batch-start.s0.a0.log': 'batch-start ok\n',
        // Длинное имя и строка без пробелов — как у живой фабрики (телефон не должен ехать вбок).
        'plan-check-after-supplement.content-researcher-reserve.s0.a0.log': `argv=${'~/factory/agents/content-researcher/'.repeat(4)}\n`,
      },
    },
    {
      run: run(
        PAST_REBUILD,
        'example-film',
        '2026-10-08T12:08:00Z',
        3120,
        'videos',
        {
          at: '2026-10-08T12:07:40Z',
          day: '2026-10-08',
          channel: 'example-film',
          by: 'user (центр)',
          kind: 'rebuild',
          why: null,
        },
        2,
      ),
      stages: ['batch-start', 'video-editor', 'frame-judge', 'batch-done'],
      logs: { 'video-editor.s0.a0.log': LOG_LINES('video-editor', 20) },
    },
    {
      run: run(
        'example-tech/2026-10-07T0200Z',
        'example-tech',
        '2026-10-07T02:00:00Z',
        1500,
        'no_material',
        {
          at: '2026-10-07T01:59:50Z',
          day: '2026-10-07',
          channel: 'example-tech',
          by: 'user (пульт)',
          kind: 'manual',
          why: null,
        },
        0,
      ),
      stages: ['batch-start', 'pool-maintenance', 'trend-hunter', 'batch-done'],
      logs: {},
    },
    {
      run: run(
        'example-film/2026-10-06T0210Z',
        'example-film',
        '2026-10-06T02:10:00Z',
        10230,
        null,
        null,
        4,
      ),
      stages: all,
      logs: { 'trend-hunter.s0.a0.log': LOG_LINES('trend-hunter', 5) },
    },
  ];
}

const DAY = 86_400_000;

/**
 * Строка журнала запусков «тик не повторил» (CF-0822, CC-0152): ручной батч ExampleTech 07.10
 * кончился на поиске трендов без трат квоты, и в окне 07:30 МСК тик его не повторил — код тот же.
 */
export const REPEAT_HELD: S['Launch'] = {
  at: '2026-10-07T04:30:05Z',
  day: '2026-10-07',
  channel: 'example-tech',
  by: 'tick',
  kind: 'repeat_held',
  why: 'example-tech: повтор того же отказа не запущен - батч 2026-10-07T0200Z упал без трат квоты (failed на trend-hunter: handler exit 1), код тот же; следующий батч example-tech - после сброса квоты 07.10 10:00 МСК, по «запускай» или после смены кода (CF-0822)',
  pid: null,
  task: 'CF-0822',
  code: { root: '4f1c2a9', 'agents/trend-hunter': '81d0e3b' },
  quota_day: '2026-10-06',
  failed_batch: 'example-tech/2026-10-07T0200Z',
  failure: 'trend-hunter: handler exit 1',
  until: '2026-10-07T07:00:00Z',
};

/**
 * Строка журнала запусков «тик продолжил сам» (CC-0176, CF-0899): прошлый батч ExampleFilm 09.10
 * встал на сценариях — claude был не залогинен; со входом тик продолжил его сам (`auto`).
 */
export const AUTO_RESUME: S['Launch'] = {
  at: '2026-10-09T03:05:02Z',
  day: '2026-10-09',
  channel: 'example-film',
  by: 'tick',
  kind: 'resume',
  why: 'example-film/2026-10-09T0215Z: продолжен после входа в claude',
  pid: 4321,
  task: 'CF-0899',
  auto: 'NOT_LOGGED_IN на content-researcher, claude залогинен',
};

/** Маркеры и пролёты стадий прогона: каждая стадия — 10 мин от начала. */
function stagesOf(
  batch: string,
  started: string,
  ids: string[],
  openFrom: number | null,
  logs: Record<string, string>,
): S['BatchStages'] {
  const t = (i: number) => new Date(Date.parse(started) + i * 600_000).toISOString();
  const markers: S['BatchMarker'][] = [
    { ts: t(0), marker: 'batch-start', stage: null, note: null },
  ];
  const spans: S['StageSpan'][] = [];
  ids.forEach((stage, i) => {
    if (openFrom != null && i > openFrom) return;
    markers.push({ ts: t(i), marker: 'stage-start', stage, note: null });
    const open = openFrom != null && i === openFrom;
    if (!open) markers.push({ ts: t(i + 1), marker: 'stage-done', stage, note: null });
    spans.push({
      stage,
      started: t(i),
      done: open ? null : t(i + 1),
      open,
      duration_s: open ? null : 600,
    });
  });
  const closed = openFrom == null;
  if (closed) markers.push({ ts: t(ids.length), marker: 'batch-done', stage: null, note: null });
  const [channel, batch_id] = batch.split('/') as [string, string];
  return {
    batch,
    channel,
    batch_id,
    markers,
    stages: spans,
    open_stages: spans.filter((s) => s.open).map((s) => s.stage),
    closed,
    open_why: closed ? null : 'нет batch-done',
    logs: Object.entries(logs).map(([name, text]) => ({
      name,
      size: bytes(text),
      modified: new Date(Date.parse(started) + DAY / 8).toISOString(),
    })),
  };
}

/** Строки файла событий с их байтовыми смещениями. */
function offsets(lines: string[]) {
  let off = 0;
  return lines.map((line) => {
    const o = off;
    off += bytes(line) + 1;
    return { offset: o, line, end: off };
  });
}

type FootageTopic = S['FootageTopic'];

/**
 * Сбор футажа по темам идущего батча (CC-0119, CF-0715 `footage_progress`): одна тема собрана,
 * одна собирается, одной не хватило кадров, одна отказана, одна ждёт (её нет среди тем батча —
 * имя по id словами).
 */
export function footageTopics(): FootageTopic[] {
  const row = (t: Partial<FootageTopic> & Pick<FootageTopic, 'topic_id' | 'state'>) => ({
    state_ru: null,
    collected: null,
    needed: 4,
    attempts: null,
    last_video: null,
    usable_shots: null,
    floor: 12,
    indexed_at: null,
    reason_code: null,
    reason_ru: null,
    reason: null,
    updated_at: at(-3),
    ...t,
  });
  return [
    row({
      topic_id: 'vanguards-doomsday',
      state: 'collected',
      state_ru: 'собрано',
      collected: 4,
      attempts: 5,
      last_video: 'Vanguards: Doomsday — Teaser',
      usable_shots: 31,
      indexed_at: at(-20),
    }),
    row({
      topic_id: 'delver',
      state: 'collecting',
      state_ru: 'собирается',
      collected: 2,
      attempts: 3,
      last_video: 'Delver — First Look',
    }),
    row({
      topic_id: 'partition-s3',
      state: 'short',
      state_ru: 'не хватило',
      collected: 3,
      attempts: 9,
      last_video: 'Partition Season 3 — Date Announcement',
      usable_shots: 7,
      reason_code: 'pool_too_thin',
      reason_ru: 'пул тоньше сценария',
      reason: 'пригодных кадров меньше порога: 7 из 12',
    }),
    row({
      topic_id: 'the-running-man',
      state: 'refused',
      state_ru: 'отказано',
      collected: 0,
      attempts: 4,
      reason_code: 'licence_refused',
      reason: 'у всех найденных роликов лицензия не подходит каналу',
    }),
    row({
      topic_id: 'one-battle-after-another',
      state: 'queued',
      state_ru: 'в очереди',
      collected: 0,
    }),
  ];
}

export function createBatchesBackend() {
  let open: Open[] = [running(), stopped()];
  /** Упавшие батчи (CC-0089): по умолчанию нет, `strand()` — два. */
  let stranded: Strand[] = [];
  const past = history();
  /** Прошлые прогоны, где стадия начата и не закрыта (CC-0123: «оборвалась»): батч → номер стадии. */
  const cut = new Map<string, number>();
  /** CC-0176: в журнале запусков есть строка «тик продолжил сам» (`AUTO_RESUME`). */
  let autoResume = false;
  let checking = false;
  /** Каждый запрос событий: `after` (null — без него). */
  const eventCalls: (number | null)[] = [];
  let n = 1000;

  const find = (batch: string): Open | Strand | undefined =>
    open.find((b) => b.going.batch === batch) ?? stranded.find((b) => b.going.batch === batch);
  const pastOf = (batch: string) => past.find((p) => p.run.batch === batch);
  /**
   * Докуда дошли темы батча (src/mocks/batchTopics.ts): идущий — сценарии проверены, монтаж
   * идёт; прошлый — до проверки кадров; прогон «нет материала» — трендхантер отсеял всё; один
   * прогон — с битым файлом этапа. Остальные (пересборки, только что запущенный) — темы ещё
   * не найдены.
   */
  const topicLevels: Record<string, TopicsLevel> = {
    [RUNNING]: '04',
    [PAST]: 'full',
    'example-tech/2026-10-07T0200Z': 'nothing',
    'example-film/2026-10-06T0210Z': 'broken',
  };
  const topicCalls: string[] = [];
  /** CC-0172: батчи с ремонтом роликов и добором тем (договор 0.75.0); у остальных — null. */
  const funnel = new Set<string>();
  /** CC-0175: батчи, у которых записи раундов добора нет (`refill.rounds` пуст). */
  const noRounds = new Set<string>();
  /**
   * Сводка прогона (CC-0115): прошлый — с замечаниями, «нет материала» — чистый, пересборка —
   * событий ещё нет, битый прогон — посчитать не вышло. Остальные — чистые; правка — `setSummary`.
   */
  const summaryKinds = new Map<string, SummaryKind>([
    [PAST, 'full'],
    ['example-tech/2026-10-07T0200Z', 'clean'],
    [PAST_REBUILD, 'none'],
    ['example-film/2026-10-06T0210Z', 'broken'],
  ]);
  const summaryCalls: string[] = [];
  /** Сбор футажа по батчам (CC-0119): идущий — по файлу прогресса; правка — `setFootage`. */
  const footage = new Map<string, Partial<S['BatchFootage']>>([
    [RUNNING, { source: 'file', running: true, topics: footageTopics() }],
  ]);
  const footageCalls: string[] = [];
  const whereOf = (batch: string) => {
    const b = find(batch);
    const p = pastOf(batch);
    if (!b && !p) return null;
    const [channel, batch_id] = batch.split('/') as [string, string];
    const status = b ? (b.state.status ?? null) : 'done';
    return { batch, channel, batch_id, going: status === 'running' || status === 'new', status };
  };
  const actions = createActions({
    list: () => open,
    find,
    launched: (channel, batchId) => {
      open = [launchedRun(channel, batchId), ...open];
    },
    // Продолженный упавший батч снова открыт: из «упавших» — в список идущих.
    resumed: (batch) => {
      const s = stranded.find((x) => x.going.batch === batch);
      if (!s) return;
      stranded = stranded.filter((x) => x !== s);
      open = [s, ...open];
    },
    holdingDay: (channel) =>
      stranded.filter((s) => s.holdsDay && s.going.channel === channel).map((s) => s.going),
    hasRunPlan: (channel) => stranded.some((s) => s.going.channel === channel),
  });

  return {
    eventCalls,
    /** Каждый запрос тем: `<батч>` или `<батч>#<тема>`. */
    topicCalls,
    summaryCalls,
    setSummary(batch: string, kind: SummaryKind) {
      summaryKinds.set(batch, kind);
    },
    /** CC-0172: у батча есть ремонт роликов и добор тем ниже шорт-листа (на уровне `full`). */
    setFunnel(batch: string, on = true) {
      if (on) funnel.add(batch);
      else funnel.delete(batch);
    },
    /** CC-0175: у батча с добором нет записи раундов — `refill` пустой (`rounds: []`), не null. */
    setRefillNoRounds(batch: string, on = true) {
      if (on) noRounds.add(batch);
      else noRounds.delete(batch);
    },
    /** Темы батча дошли до `level` (`broken` — битый файл этапа). */
    setTopics(batch: string, level: TopicsLevel) {
      topicLevels[batch] = level;
      // Идущий батч встаёт на стадию, которая идёт при таких темах: лента, процессы и строки
      // тем говорят одно (CC-0092).
      const b = find(batch);
      const stage = LEVEL_STAGE[level];
      if (!b || !stage || b.going.status !== 'running') return;
      const stages = stagesUpTo(stage, 'running');
      const next =
        stages.find(
          (s, i) => i > ORDER.indexOf(stage as (typeof ORDER)[number]) && !NOT_NEEDED.has(s.id),
        )?.id ?? null;
      b.going = { ...b.going, stages, stage, next };
      b.state = {
        ...b.state,
        stages: Object.fromEntries(stages.map((s) => [s.id, { status: s.status }])),
        current: { stage },
        next,
        runs: {
          [`${stage}.s0.a0`]: {
            stage,
            pid: 4300,
            pgid: 4300,
            started: at(-10),
            ended: null,
            log: `logs/${stage}.s0.a0.log`,
            exit: null,
            restarts: 0,
            alive: true,
          },
        },
      };
      b.lines = b.lines.map((l) => l.replace(/"stage":"[^"]*"/, `"stage":"${stage}"`));
    },
    /** Действия: запуск, остановить, продолжить (src/mocks/batchActions.ts) и их ручки. */
    actions,
    /** Упавшие батчи (CC-0089): упал на batch-start и держит день; остановлен вчера. */
    strand() {
      stranded = [strandedFailed(), strandedStopped()];
    },
    /**
     * У прошлого прогона `batch` стадия номер `at` начата, а конца нет (как футаж Reel 13.10:
     * батч кончился, стадия числится «идущей») — `…/stages` отдаёт её открытой.
     */
    cutStage(batch: string, at: number) {
      cut.set(batch, at);
    },
    /** Каждый запрос футажа: `<батч>`. */
    footageCalls,
    /** Сбор футажа батча `batch` (CC-0119): поля ответа поверх нынешних. */
    setFootage(batch: string, patch: Partial<S['BatchFootage']>) {
      footage.set(batch, { ...footage.get(batch), ...patch });
    },
    /** Тихие решения плана в run-state батча (CC-0120, CF-0735 `quiet[]`). */
    setQuiet(batch: string, rows: S['QuietDecision'][]) {
      const b = find(batch);
      if (b) b.state = { ...b.state, quiet: rows };
    },
    /** Стадии батча `batch` правили код фабрики (CC-0111): строки `code_edits` и пометка списка. */
    setCodeEdits(batch: string, rows: S['StageCodeEdit'][]) {
      const b = find(batch);
      if (!b) return;
      b.codeEdits = rows;
      b.going = {
        ...b.going,
        code_edits: rows.length ? rows.map(codeEditLine) : null,
        code_edits_count: rows.length,
      };
      b.state = { ...b.state, code_edits: rows.length ? rows : null };
    },
    /** Список пуст: «сейчас батча нет». */
    closeAll() {
      open = [];
    },
    /** В журнале запусков — строка «тик продолжил сам» (CC-0176, `AUTO_RESUME`). */
    setAutoResume(on = true) {
      autoResume = on;
    },
    setChecking(v: boolean) {
      checking = v;
    },
    /** Поправить строку списка идущего батча (стадия, оценка, статус…). */
    patch(batch: string, going: Partial<S['BatchesGoing']['batches'][number]>) {
      const b = find(batch);
      if (b) b.going = { ...b.going, ...going };
    },
    /**
     * Исполнитель батча умер, не записав конца (CC-0094, как example-science/2026-10-12T2001Z
     * после перезагрузки 12.10): `status` остаётся `running`, `fresh` — true, живых процессов
     * нет, последнее событие — `minutesAgo` минут назад.
     */
    killExecutor(batch: string, minutesAgo = 7) {
      const b = find(batch)!;
      b.dead = true;
      // Продолжит с недоделанной стадии: `next` у run-state — она же.
      b.going = { ...b.going, last_event: at(-minutesAgo), next: b.going.stage ?? b.going.next };
      const runs = b.state.runs ?? {};
      b.state = {
        ...b.state,
        runs: Object.fromEntries(Object.entries(runs).map(([k, r]) => [k, { ...r, alive: false }])),
      };
    },
    /** Дописать `count` строк в файл событий батча. */
    append(batch: string, count: number) {
      const b = find(batch)!;
      for (let i = 0; i < count; i++)
        b.lines.push(event(n++, b.going.stage ?? 'video-editor', 'ok'));
    },
    /** Файл событий заменён коротким (курсор окажется за концом → `reset`). */
    replace(batch: string, count: number) {
      const b = find(batch)!;
      b.lines = Array.from({ length: count }, () =>
        event(n++, b.going.stage ?? 'video-editor', 'restart', { note: 'новый файл' }),
      );
    },

    going(): BatchReply<S['BatchesGoing']> {
      return {
        status: 200,
        body: {
          // CC-0110: жив ли исполнитель — по последнему скану (`killExecutor` — умер).
          batches: open.map((b) => {
            const alive = b.going.status === 'running' && !b.dead;
            return {
              open_why: 'нет batch-done',
              ...b.going,
              executor_alive: alive,
              lock_held: alive,
              executor_why: alive ? 'the executor holds run-executor.lock (pid 4242), alive' : null,
            };
          }),
          as_of: MOCK_NOW,
          checked_at: at(-0.2),
          age_s: 12,
          checking,
          poll_s: 15,
        },
      };
    },

    detail(batch: string): BatchReply<S['BatchDetail']> {
      const b = find(batch);
      if (!b) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      const runs = b.state.runs ?? {};
      return {
        status: 200,
        body: {
          batch,
          channel: b.going.channel ?? null,
          batch_id: b.going.batch_id,
          dir: `${b.going.dir}/${b.going.batch_id}`,
          state: b.state,
          state_error: null,
          status: b.state.status ?? null,
          alive: Object.keys(runs).filter((k) => runs[k]!.alive),
          questions: b.questions,
          quiet: b.state.quiet ?? [],
          code_edits: b.codeEdits ?? [],
        },
      };
    },

    events(batch: string, after: number | null, limit = 200): BatchReply<S['BatchEvents']> {
      const b = find(batch);
      if (!b) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      eventCalls.push(after);
      const rows = offsets(b.lines);
      const size = rows.at(-1)?.end ?? 0;
      const reset = after != null && after > size;
      const tail = after == null || reset;
      const from = tail ? rows : rows.filter((r) => r.offset >= after);
      const got = tail ? from.slice(-limit) : from.slice(0, limit);
      const more = !tail && from.length > limit;
      return {
        status: 200,
        body: {
          batch,
          events: got.map((r) => ({
            offset: r.offset,
            event: JSON.parse(r.line) as Record<string, unknown>,
            text: null,
          })),
          next: got.at(-1)?.end ?? (tail ? 0 : after),
          size,
          more,
          reset,
          poll_s: 3,
        },
      };
    },

    stranded(limit = 20, channel: string | null = null): BatchReply<S['StrandedBatches']> {
      return {
        status: 200,
        body: {
          batches: stranded
            .filter((s) => !channel || s.going.channel === channel)
            .slice(0, limit)
            .map(strandedRow),
          as_of: MOCK_NOW,
          error: null,
        },
      };
    },

    history(limit = 50, channel: string | null = null): BatchReply<S['BatchHistory']> {
      const runs = past
        .map((p) => p.run)
        .filter((r) => !channel || r.channel === channel)
        .slice(0, limit);
      return {
        status: 200,
        body: {
          channel,
          runs,
          // CF-0822: строка «тик не повторил» (`repeat_held`) — запуск без батча, у прогонов её нет.
          launches: [
            ...runs.flatMap((r) => (r.launch ? [r.launch] : [])),
            ...(!channel || channel === REPEAT_HELD.channel ? [REPEAT_HELD] : []),
            // CC-0176: resume-строка, которую тик продолжил сам, — по `setAutoResume()`.
            ...(autoResume && (!channel || channel === AUTO_RESUME.channel) ? [AUTO_RESUME] : []),
          ].sort((a, b) => Date.parse(b.at ?? '') - Date.parse(a.at ?? '')),
        },
      };
    },

    summary(batch: string): BatchReply<S['BatchRunSummary']> {
      if (!whereOf(batch)) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      summaryCalls.push(batch);
      return { status: 200, body: summaryReply(batch, summaryKinds.get(batch) ?? 'clean') };
    },

    topics(batch: string): BatchReply<S['BatchTopics']> {
      const w = whereOf(batch);
      if (!w) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      topicCalls.push(batch);
      return topicsReply(w, topicLevels[batch] ?? 'none', funnel.has(batch), noRounds.has(batch));
    },

    topic(batch: string, topicId: string): BatchReply<S['BatchTopic']> {
      const w = whereOf(batch);
      if (!w) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      topicCalls.push(`${batch}#${topicId}`);
      return topicReply(w, topicLevels[batch] ?? 'none', topicId, funnel.has(batch));
    },

    footage(batch: string): BatchReply<S['BatchFootage']> {
      const w = whereOf(batch);
      if (!w) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      footageCalls.push(batch);
      const f = footage.get(batch) ?? {};
      const topics = f.topics ?? [];
      const counts: Record<string, number> = {};
      for (const t of topics) counts[t.state] = (counts[t.state] ?? 0) + 1;
      return {
        status: 200,
        body: {
          batch,
          channel: w.channel,
          batch_id: w.batch_id,
          source: 'none',
          file: f.source === 'file' ? 'work/footage-progress.json' : null,
          started_at: topics.length ? at(-40) : null,
          updated_at: topics.length ? at(-1) : null,
          finished: false,
          running: topics.length ? w.going : null,
          needed: topics.length ? 4 : null,
          counts,
          error: null,
          cached: false,
          poll_s: 1,
          ...f,
          topics,
        },
      };
    },

    stages(batch: string): BatchReply<S['BatchStages']> {
      const p = pastOf(batch);
      if (p)
        return {
          status: 200,
          body: stagesOf(batch, p.run.started!, p.stages, cut.get(batch) ?? null, p.logs),
        };
      const b = find(batch);
      if (!b) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      const cur = RAN.indexOf(b.going.stage ?? '');
      return { status: 200, body: stagesOf(batch, b.going.started!, RAN, cur, b.logs) };
    },

    log(batch: string, name: string, size = 65536): BatchReply<S['LogTail']> {
      const logs = pastOf(batch)?.logs ?? find(batch)?.logs;
      if (!logs) return notFound('unknown_batch', `Батча «${batch}» нет.`);
      const text = logs[name];
      if (text == null) return notFound('unknown_log', `Журнала «${name}» у батча ${batch} нет.`);
      const raw = new TextEncoder().encode(text);
      let start = Math.max(0, raw.length - size);
      if (start > 0) {
        const nl = raw.indexOf(10, start);
        if (nl >= 0 && nl < raw.length - 1) start = nl + 1;
      }
      return {
        status: 200,
        body: {
          name,
          size: raw.length,
          offset: start,
          truncated: start > 0,
          text: new TextDecoder().decode(raw.slice(start)),
        },
      };
    },
  };
}

export type BatchesBackend = ReturnType<typeof createBatchesBackend>;

/** Ответ подставных батчей на запрос, null — адрес не их. */
export function routeBatches(
  backend: BatchesBackend,
  method: string,
  url: URL,
  body: unknown = null,
): BatchReply<unknown> | null {
  const act = routeActions(backend.actions, method, url, body);
  if (act) return act;
  const m = url.pathname.match(
    /\/api\/batches(?:\/(history|stranded)|\/([^/]+)\/([^/]+)(?:\/(events|stages|footage|summary|topics(?:\/([^/]+))?|logs\/([^/]+)))?)?$/,
  );
  if (!m || method !== 'GET') return null;
  const [, hist, dir, id, sub, topic, log] = m;
  const q = url.searchParams;
  const num = (k: string) => (q.get(k) == null ? undefined : Number(q.get(k)));
  if (hist === 'stranded') return backend.stranded(num('limit'), q.get('channel'));
  if (hist) return backend.history(num('limit'), q.get('channel'));
  if (!dir) return backend.going();
  const batch = `${decodeURIComponent(dir)}/${decodeURIComponent(id!)}`;
  if (!sub) return backend.detail(batch);
  if (sub === 'events') return backend.events(batch, num('after') ?? null, num('limit'));
  if (sub === 'stages') return backend.stages(batch);
  if (sub === 'footage') return backend.footage(batch);
  if (sub === 'summary') return backend.summary(batch);
  if (topic) return backend.topic(batch, decodeURIComponent(topic));
  if (sub === 'topics') return backend.topics(batch);
  return backend.log(batch, decodeURIComponent(log!), num('bytes'));
}
