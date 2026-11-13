// Подставное «Обслуживание и расход» (CC-0032 / CC-0104 / CC-0105 фабрики, договор 0.58.0; экран —
// CC-0033). Общий для Vitest (MSW, src/mocks/handlers.ts), Playwright (tests/e2e/fixtures.ts) и
// тренировки (src/training/demo.ts). Данные — ./maintenanceData. Чтения: что фабрика открывает
// центру, расход батча (нет событий — `ok: false` с подсказкой; не тот батч — 404
// `unknown_batch`, не «канал/батч» — 422 `invalid`), сравнение прогонов (один и тот же батч —
// 422 `bad_call`), пул футажа (`?stale_days=14` заканчивает старую тему без ролика) и сухой
// прогон архива. Записи — план с токеном (`life` с, одноразовый) и «да» `{confirm}`: журналы,
// пул, архив. Токен сгорает при любом исходе, кроме `busy`; чужой токен — `confirm_mismatch`.
// Ручки теста: `refuse` (чтение → 500 `factory_broken`), `openBatches` (идёт батч: план без
// токена, «да» — 409 `batch_open`), `volumeMissing` (диск архива не подключён: план без токена,
// «да» — 409 `volume_missing`), `next` (исход следующего «да»), `readOnly` (каждый POST — 409
// `not_working_factory`), `life`, `expireTokens()`, `calls`, `written`. Импорты — относительные.
import type { components } from '../api/schema.gen';
import {
  ARCHIVE_FREE,
  ARCHIVE_JOBS,
  COMPARABLE,
  compareOf,
  JOURNALS,
  JOURNALS_LOG,
  MAINT_AT,
  MAINT_TODAY,
  POOL,
  POOL_VARIANTS,
  USAGE,
  USAGE_NONE,
  USAGE_WHY,
  usageTotals,
  VOLUME,
} from './maintenanceData';

type S = components['schemas'];
type Code = S['MaintenanceProblem']['code'] | 'not_working_factory';
type Status = 404 | 409 | 422 | 500;

export type MaintenanceReply =
  | { status: 200; body: unknown }
  | { status: Status; body: { message: string; code: Code; details: string[] } };

export type MaintenancePart = 'overview' | 'usage' | 'compare' | 'pool' | 'archive';
export type MaintenanceOutcome = 'check_changed' | 'refused' | 'busy' | 'factory_broken';
type Action = 'batch_journals_cleanup' | 'pool_release_delete' | 'publish_month_archive';

class Fault extends Error {
  readonly status: Status;
  readonly code: Code;
  readonly details: string[];
  constructor(status: Status, code: Code, message: string, details: string[]) {
    super(message);
    this.status = status;
    this.code = code;
    this.details = details;
  }
}

const deep = <T>(x: T): T => structuredClone(x);
const ok = (body: unknown): MaintenanceReply => ({ status: 200, body });
const BY = { by: 'user', via: 'center' } as const;
const POOL_JOURNAL = 'shared/footage/release-log.jsonl';
const FACTORY_LINES: Record<MaintenancePart, string> = {
  overview: 'the maintenance overview could not be built',
  usage:
    'usage_report: Traceback (most recent call last): ... OSError: [Errno 5] Input/output error',
  compare: 'compare_runs: Traceback (most recent call last): ... KeyError: stages',
  pool: 'pool-release: Traceback (most recent call last): ... OSError: [Errno 5] Input/output error',
  archive: 'archive_publish_month.py --dry-run exited 2: volume probe failed',
};

const SCRIPTS: S['MaintenanceScript'][] = [
  {
    script: 'scripts/usage_report.py',
    exposed: 'read',
    routes: ['GET /api/maintenance/usage/{channel}/{batch_id}'],
    why: 'расход батча в токенах — как печатает --json',
  },
  {
    script: 'scripts/compare_runs.py',
    exposed: 'read',
    routes: ['GET /api/maintenance/compare'],
    why: 'батч вручную против батча исполнителя: стадии, порядок, файлы',
  },
  {
    script: 'scripts/archive_publish_month.py',
    exposed: 'plan_confirm',
    routes: [
      'GET /api/maintenance/archive',
      'POST /api/maintenance/archive/plan',
      'POST /api/maintenance/archive',
    ],
    why: 'шаг (а): прошлый месяц уходит из publish/ на диск архива; шаги пула, старых батчей и $TMPDIR из центра не запускаются',
  },
  {
    script: 'scripts/cleanup_batch_journals.py',
    exposed: 'plan_confirm',
    routes: ['POST /api/maintenance/journals/plan', 'POST /api/maintenance/journals'],
    why: 'чужие строки журналов батчей — план, потом «да»',
  },
  {
    script: 'scripts/runlog pool-release',
    exposed: 'plan_confirm',
    routes: [
      'GET /api/maintenance/pool',
      'POST /api/maintenance/pool/release/plan',
      'POST /api/maintenance/pool/release',
    ],
    why: 'футаж законченных тем — план, потом «да»',
  },
  {
    script: 'scripts/cleanup_tmpdir.sh',
    exposed: 'none',
    routes: [],
    why: 'не открыт: чистит $TMPDIR машины, а не дерево фабрики, которое показывает центр, и устроен под macOS; $TMPDIR уже чистит шаг (d) месячного архива',
  },
  {
    script: 'scripts/cleanup_1_6_archive.sh',
    exposed: 'none',
    routes: [],
    why: 'не открыт: разовый перенос 04.10 без сухого прогона',
  },
];

const sum = (l: S['PoolSource'][]): S['PoolSum'] => ({
  sources: l.length,
  bytes: l.reduce((a, s) => a + s.bytes, 0),
});

export function createMaintenanceBackend() {
  const state = {
    /** Сломанные чтения: часть → 500 `factory_broken`. */
    refuse: {} as Partial<Record<MaintenancePart, true>>,
    /** Идущие батчи «канал/батч»: записи ждут (план без токена, «да» — `batch_open`). */
    openBatches: [] as string[],
    /** Диск архива не подключён. */
    volumeMissing: false,
    /** Исход следующего «да» (одноразово). */
    next: null as MaintenanceOutcome | null,
    /** API не на рабочей фабрике: каждый POST — 409 `not_working_factory`. */
    readOnly: false,
    /** Срок жизни токена подтверждения, секунд (у фабрики — 120). */
    life: 120,
    /** Каждый запрос: «МЕТОД путь». */
    calls: [] as string[],
    /** Что сделано из центра. */
    written: { journals: 0, released: [] as string[], archived: [] as string[] },
    usage: deep(USAGE),
    journals: deep(JOURNALS),
    pool: deep(POOL),
    jobs: deep(ARCHIVE_JOBS),
  };
  const tokens = new Map<
    string,
    { action: Action; fp: string; expires: number; staleDays: number | null }
  >();
  let n = 0;

  const refuse = (part: MaintenancePart) => {
    if (state.refuse[part])
      throw new Fault(500, 'factory_broken', 'Фабрика не ответила как положено.', [
        FACTORY_LINES[part],
      ]);
  };

  const batchRef = (ref: string, what = 'батч') => {
    if (!/^[a-z][a-z0-9-]*\/\d{4}-\d\d-\d\dT\d{4}Z$/.test(ref))
      throw new Fault(422, 'invalid', `${what}: ждём «<канал>/<батч>», дано «${ref}».`, [
        `not a <channel>/<batch_id>: ${ref}`,
      ]);
    if (!state.usage[ref] && !USAGE_NONE.includes(ref) && !COMPARABLE.includes(ref))
      throw new Fault(404, 'unknown_batch', `Батча ${ref} на фабрике нет.`, [
        `pipeline/${ref}: no such directory`,
      ]);
  };

  // -------------------------------------------------------------- чтения
  function overview(): MaintenanceReply {
    refuse('overview');
    return ok({
      scripts: deep(SCRIPTS),
      journals_action: 'batch_journals_cleanup',
      pool_action: 'pool_release_delete',
      ...BY,
    } satisfies S['Maintenance']);
  }

  function usage(channel: string, batchId: string): MaintenanceReply {
    refuse('usage');
    const batch = `${channel}/${batchId}`;
    batchRef(batch);
    const list = state.usage[batch] ?? [];
    return ok({
      batch,
      command: `scripts/usage_report.py ${batch} --json`,
      events: `pipeline/${batch}/RUN_EVENTS.jsonl`,
      computed: list.length ? (list[0]!.computed ?? null) : null,
      ok: list.length > 0,
      why: list.length ? null : USAGE_WHY.replace('<batch>', batch),
      rows: deep(list),
      totals: usageTotals(list),
    } satisfies S['UsageReport']);
  }

  function compare(manual: string | null, executor: string | null): MaintenanceReply {
    refuse('compare');
    if (!manual || !executor)
      throw new Fault(422, 'bad_call', 'Сравнение не составлено: нужны оба батча.', [
        'manual and executor are required',
      ]);
    batchRef(manual, 'manual');
    batchRef(executor, 'executor');
    if (manual === executor)
      throw new Fault(422, 'bad_call', 'Сравнение не составлено: это один и тот же батч.', [
        'manual == executor',
      ]);
    if (!COMPARABLE.includes(manual) || !COMPARABLE.includes(executor))
      throw new Fault(404, 'unknown_batch', 'У батча нет журнала стадий — сравнивать нечего.', [
        'RUN_EVENTS.jsonl missing',
      ]);
    return ok(compareOf(manual, executor));
  }

  /** `pool_release.plan`: с правилом давности старая тема без ролика заканчивается. */
  function poolPlan(staleDays: number | null) {
    const release = deep(state.pool.release);
    const keep: S['PoolSource'][] = [];
    for (const s of deep(state.pool.keep)) {
      const stale =
        staleDays != null && s.blocked_by?.length === 1 && s.blocked_by[0] === 'no_video';
      if (stale) {
        for (const t of Object.values(s.topics ?? {})) {
          t.stale = true;
          t.evidence = [
            ...(t.evidence ?? []),
            `stale: ${t.status}, every batch older than ${staleDays} d`,
          ];
        }
        release.push({ ...s, blocked_by: [] });
      } else {
        const going = Object.values(s.topics ?? {})
          .flatMap((t) => t.batches)
          .filter((b) => state.openBatches.includes(b));
        keep.push(
          going.length
            ? { ...s, blocked_by: ['open_batch', ...(s.blocked_by ?? [])], open_batches: going }
            : s,
        );
      }
    }
    return { release, keep, orphan: deep(state.pool.orphan) };
  }

  function pool(staleDays: number | null): MaintenanceReply {
    refuse('pool');
    const p = poolPlan(staleDays);
    return ok({
      command: `scripts/runlog pool-release --json --variants${staleDays == null ? '' : ` --stale-days ${staleDays}`}`,
      at: MAINT_AT,
      stale_days: staleDays,
      open_batches: [...state.openBatches],
      release: p.release,
      keep: p.keep,
      orphan: p.orphan,
      unresolved: [{ kind: 'uploads.json', entry: 'example-film/2026-08-30T0210Z/reel-moray-eel' }],
      pool: sum([...p.release, ...p.keep, ...p.orphan]),
      totals: { release: sum(p.release), keep: sum(p.keep), orphan: sum(p.orphan) },
      variants: POOL_VARIANTS(p.orphan),
      journal: POOL_JOURNAL,
      delete_action: 'pool_release_delete',
    } satisfies S['PoolView']);
  }

  const debt = () =>
    state.jobs.map((j) => ({
      channel: j.channel,
      month: j.month,
      days: j.day_dirs.length,
      files: j.from_publish.length,
    }));

  const archiveLines = (): string[] =>
    state.volumeMissing
      ? [`archive volume ${VOLUME}: not mounted`, 'nothing done (dry run)']
      : state.jobs.length
        ? [
            ...state.jobs.flatMap((j) => [
              `${j.channel} ${j.month}: ${j.from_publish.length} file(s), ${j.day_dirs.length} day dir(s) -> ${j.zip} (${j.action})`,
            ]),
            `${VOLUME}: free ${Math.round(ARCHIVE_FREE / 1024 ** 3)} GB`,
            'nothing done (dry run)',
          ]
        : ['nothing owed: publish/ holds this month only', 'nothing done (dry run)'];

  function archive(monthly: boolean): MaintenanceReply {
    refuse('archive');
    return ok({
      command: `scripts/archive_publish_month.py --dry-run${monthly ? '' : ' --publish-only'}`,
      dry_run: true,
      monthly,
      exit_code: state.volumeMissing ? 3 : 0,
      ok: !state.volumeMissing,
      lines: archiveLines(),
      stderr: null,
      error: state.volumeMissing ? `том ${VOLUME} не подключён` : null,
      volume: VOLUME,
      confirm_available: !monthly,
      plan_action: monthly ? null : 'publish_month_archive',
    } satisfies S['ArchiveDryRun']);
  }

  // -------------------------------------------------------------- записи
  const guard = () => {
    if (state.readOnly)
      throw new Fault(
        409,
        'not_working_factory',
        'Только смотреть: рабочая копия на ветке cc-api, а не main',
        ['CC_API_WRITES is off'],
      );
  };

  const mint = (action: Action, fp: string, can: boolean, staleDays: number | null = null) => {
    if (!can) return { confirm: null, expires_in_s: null };
    n += 1;
    const confirm = `maint-${action}-${n}`;
    tokens.set(confirm, { action, fp, expires: Date.now() + state.life * 1000, staleDays });
    return { confirm, expires_in_s: state.life };
  };

  const goingWhy = () =>
    state.openBatches.length
      ? `Открыт батч (${state.openBatches.join(', ')}) - запись подождёт, пока он закончится.`
      : null;

  /** «да»: токен сгорает при любом исходе, кроме `busy`. */
  function spend(raw: unknown, action: Action) {
    guard();
    const next = state.next;
    state.next = null;
    if (next === 'busy')
      throw new Fault(409, 'busy', 'Идёт другая уборка - подождите и нажмите ещё раз.', [
        'the maintenance lock was not free; the token is not spent',
      ]);
    const token = (raw as { confirm?: string } | null)?.confirm ?? '';
    const got = tokens.get(token);
    tokens.delete(token);
    if (!got)
      throw new Fault(
        409,
        'confirm_unknown',
        'Подтверждение не найдено или уже использовано - запросите план заново.',
        ['no such confirm token in this API process (used, unknown, or the server restarted)'],
      );
    if (got.action !== action)
      throw new Fault(409, 'confirm_mismatch', 'Подтверждение выдано другому действию.', [
        `token of ${got.action}, not ${action}`,
      ]);
    if (got.expires <= Date.now())
      throw new Fault(
        409,
        'confirm_expired',
        'Подтверждение устарело (живёт 120 с) - запросите план заново.',
        ['expired'],
      );
    if (state.openBatches.length)
      throw new Fault(409, 'batch_open', goingWhy()!, ['runlog batch-active: 1']);
    return { got, next };
  }

  const changed = (what: string) =>
    new Fault(
      409,
      'check_changed',
      `${what} изменились с момента плана - ничего не сделано; посмотрите план заново.`,
      ['the fingerprint differs from the plan'],
    );

  const broken = (line: string) =>
    new Fault(
      500,
      'factory_broken',
      'Фабрика ответила ошибкой посреди уборки - посмотрите состояние, прежде чем повторять.',
      [line],
    );

  function journalTotals(rows: S['JournalRow'][]): S['JournalTotals'] {
    const whole = rows.filter((r) => r.mode === 'whole');
    const cut = rows.filter((r) => r.mode === 'lines');
    return {
      journals: rows.length,
      whole: whole.length,
      whole_lines: whole.reduce((a, r) => a + r.lines, 0),
      whole_bytes: whole.reduce((a, r) => a + r.bytes, 0),
      cut_journals: cut.length,
      cut_lines: cut.reduce((a, r) => a + r.drop, 0),
      cut_bytes: cut.reduce((a, r) => a + r.drop_bytes, 0),
    };
  }

  function journalsPlan(): MaintenanceReply {
    guard();
    const rows = deep(state.journals);
    const going = goingWhy();
    const can = rows.length > 0 && !going;
    const fp = JSON.stringify(rows.map((r) => r.sha));
    return ok({
      action: 'batch_journals_cleanup',
      ok: can,
      why: going ?? (rows.length ? null : 'Чистить нечего - чужих строк в журналах нет.'),
      command: 'scripts/cleanup_batch_journals.py --delete',
      journals: rows,
      totals: journalTotals(rows),
      open_batches: [...state.openBatches],
      log: JOURNALS_LOG,
      ...BY,
      fingerprint: fp,
      ...mint('batch_journals_cleanup', fp, can),
    } satisfies S['JournalsPlan']);
  }

  function journalsClean(raw: unknown): MaintenanceReply {
    const { got, next } = spend(raw, 'batch_journals_cleanup');
    if (next === 'refused') state.journals = [];
    if (!state.journals.length)
      throw new Fault(409, 'refused', 'Чистить уже нечего - журналы не тронуты.', [
        'plan is empty',
      ]);
    if (next === 'check_changed' || JSON.stringify(state.journals.map((r) => r.sha)) !== got.fp)
      throw changed('Журналы');
    if (next === 'factory_broken') throw broken('OSError: [Errno 28] No space left on device');
    const done = state.journals.map((r) => ({
      ...r,
      after_lines: r.mode === 'whole' ? 0 : r.after,
      after_bytes: r.mode === 'whole' ? 0 : r.bytes - r.drop_bytes,
      applied: true,
    }));
    state.journals = [];
    state.written.journals += done.length;
    return ok({
      action: 'batch_journals_cleanup',
      written: true,
      ...BY,
      done,
      totals: journalTotals(done),
      backup: '.../cf0530-journals-20261014T091500',
      log: JOURNALS_LOG,
      lines: [
        `2026-10-14T09:15:00Z кто: by user, via center`,
        ...done.map((r) => `${r.rel}: ${r.mode} -${r.drop} line(s), ${r.after_lines} left`),
      ],
    } satisfies S['JournalsResult']);
  }

  const poolFp = (release: S['PoolSource'][]) =>
    JSON.stringify(release.map((s) => [s.video_id, s.bytes]));

  const releaseRows = (release: S['PoolSource'][], staleDays: number | null) =>
    release.map((s) => ({
      ts: MAINT_AT,
      event: 'released',
      video_id: s.video_id,
      files: s.files,
      bytes: s.bytes,
      stale_days: staleDays,
      ...BY,
    }));

  function poolReleasePlan(raw: unknown): MaintenanceReply {
    guard();
    const sd = (raw as { stale_days?: unknown } | null)?.stale_days;
    const staleDays = typeof sd === 'number' ? sd : null;
    if (staleDays != null && (staleDays < 1 || staleDays > 365))
      throw new Fault(422, 'invalid', 'Давность — от 1 до 365 дней.', [`stale_days=${staleDays}`]);
    const p = poolPlan(staleDays);
    const going = goingWhy();
    const can = p.release.length > 0 && !going;
    const fp = poolFp(p.release);
    const token = mint('pool_release_delete', fp, can, staleDays);
    return ok({
      action: 'pool_release_delete',
      ok: can,
      why: going ?? (p.release.length ? null : 'Освобождать нечего - законченных тем в пуле нет.'),
      command: `scripts/runlog pool-release --delete${staleDays == null ? '' : ` --stale-days ${staleDays}`}`,
      at: MAINT_AT,
      stale_days: staleDays,
      release: p.release,
      totals: sum(p.release),
      kept: sum(p.keep),
      orphan: sum(p.orphan),
      open_batches: [...state.openBatches],
      journal: POOL_JOURNAL,
      ...BY,
      recorded_by: true,
      rows: can ? releaseRows(p.release, staleDays) : [],
      fingerprint: fp,
      ...token,
    } satisfies S['PoolReleasePlan']);
  }

  function poolRelease(raw: unknown): MaintenanceReply {
    const { got, next } = spend(raw, 'pool_release_delete');
    if (next === 'refused') state.pool.release = [];
    const p = poolPlan(got.staleDays);
    if (!p.release.length)
      throw new Fault(409, 'refused', 'Освобождать уже нечего - пул не тронут.', ['plan is empty']);
    if (next === 'check_changed' || poolFp(p.release) !== got.fp) throw changed('Источники пула');
    if (next === 'factory_broken') throw broken('OSError: [Errno 1] Operation not permitted');
    const gone = new Set(p.release.map((s) => s.video_id));
    state.pool.release = [];
    state.pool.keep = state.pool.keep.filter((s) => !gone.has(s.video_id));
    state.written.released.push(...gone);
    return ok({
      action: 'pool_release_delete',
      written: true,
      ...BY,
      recorded_by: true,
      stale_days: got.staleDays,
      deleted: [...gone],
      totals: sum(p.release),
      journal: POOL_JOURNAL,
      rows: releaseRows(p.release, got.staleDays),
    } satisfies S['PoolReleaseResult']);
  }

  const archiveFp = () => JSON.stringify(state.jobs.map((j) => [j.channel, j.month, j.members]));

  function archivePlan(): MaintenanceReply {
    guard();
    const owed = state.jobs.length > 0;
    const going = goingWhy();
    const need = state.jobs.reduce((a, j) => a + (j.bytes ?? 0), 0);
    const missing = owed && state.volumeMissing;
    const can = owed && !going && !missing;
    const fp = archiveFp();
    return ok({
      action: 'publish_month_archive',
      ok: can,
      why: missing
        ? `Том архива ${VOLUME} не подключён - подключите диск и запросите план заново.`
        : (going ?? (owed ? null : 'Архивировать нечего - в publish/ только этот месяц.')),
      command: 'scripts/archive_publish_month.py --dry-run --json --publish-only',
      apply_command:
        'scripts/archive_publish_month.py --publish-only --json --by user --via center',
      today: MAINT_TODAY,
      volume: VOLUME,
      mounted: owed ? !state.volumeMissing : null,
      debt: debt(),
      legacy_skipped: [],
      jobs: deep(state.jobs).map((j) => (missing ? { ...j, action: null } : j)),
      need_bytes: owed ? need : null,
      free_bytes: owed && !missing ? ARCHIVE_FREE : null,
      margin_bytes: owed && !missing ? 2 * 1024 ** 3 : null,
      enough_space: owed && !missing ? true : null,
      open_batches: [...state.openBatches],
      lines: archiveLines(),
      exit_code: missing ? 3 : 0,
      ...BY,
      fingerprint: fp,
      ...mint('publish_month_archive', fp, can),
    } satisfies S['ArchivePlan']);
  }

  function archiveRun(raw: unknown): MaintenanceReply {
    const { got, next } = spend(raw, 'publish_month_archive');
    if (state.volumeMissing)
      throw new Fault(
        409,
        'volume_missing',
        `Фабрика отказала: том архива ${VOLUME} не подключён.`,
        [`archive volume ${VOLUME}: not mounted`],
      );
    if (next === 'refused') state.jobs = [];
    if (!state.jobs.length)
      throw new Fault(409, 'refused', 'Архивировать уже нечего - publish/ не тронут.', ['no debt']);
    if (next === 'check_changed' || archiveFp() !== got.fp)
      throw changed('Месяц в publish/ или том архива');
    if (next === 'factory_broken')
      throw new Fault(
        500,
        'factory_broken',
        'Месячный архив не завершился - посмотрите publish/ и том архива, прежде чем повторять.',
        ['zip verify failed: CRC mismatch'],
      );
    const jobs = state.jobs.map((j) => ({ ...j, status: 'moved' }));
    state.written.archived.push(...jobs.map((j) => `${j.channel}/${j.month}`));
    state.jobs = [];
    return ok({
      action: 'publish_month_archive',
      written: true,
      ...BY,
      command: 'scripts/archive_publish_month.py --publish-only --json --by user --via center',
      today: MAINT_TODAY,
      volume: VOLUME,
      jobs,
      commit: { message: 'archive: publish 2026-09 -> Archive', ...BY },
      committed: true,
      exit_code: 0,
      lines: jobs.map(
        (j) => `${j.channel} ${j.month}: moved ${j.from_publish.length} file(s) -> ${j.zip}`,
      ),
    } satisfies S['ArchiveResult']);
  }

  /** Все выданные токены устарели (как будто прошло 120 с) — «да» получит `confirm_expired`. */
  const expireTokens = () => {
    for (const t of tokens.values()) t.expires = 0;
  };

  return {
    state,
    overview,
    usage,
    compare,
    pool,
    archive,
    journalsPlan,
    journalsClean,
    poolReleasePlan,
    poolRelease,
    archivePlan,
    archiveRun,
    expireTokens,
  };
}

export type MaintenanceBackend = ReturnType<typeof createMaintenanceBackend>;

/** Ответ на запрос к API обслуживания или `null`, если запрос не к нему. */
export function routeMaintenance(
  backend: MaintenanceBackend,
  method: string,
  url: URL,
  body: unknown,
): MaintenanceReply | null {
  const m = url.pathname.match(
    /\/api\/maintenance(?:\/(compare|pool|archive|archive\/plan|journals|journals\/plan|pool\/release|pool\/release\/plan|usage\/([^/]+)\/([^/]+)))?$/,
  );
  if (!m) return null;
  backend.state.calls.push(`${method} ${url.pathname}`);
  const q = url.searchParams;
  try {
    const what = m[1] ?? '';
    if (method === 'GET') {
      if (what === '') return backend.overview();
      if (what.startsWith('usage/'))
        return backend.usage(decodeURIComponent(m[2]!), decodeURIComponent(m[3]!));
      if (what === 'compare') return backend.compare(q.get('manual'), q.get('executor'));
      if (what === 'pool') {
        const sd = q.get('stale_days');
        return backend.pool(sd ? Number(sd) : null);
      }
      if (what === 'archive') return backend.archive(q.get('monthly') === 'true');
      return null;
    }
    if (method === 'POST') {
      if (what === 'journals/plan') return backend.journalsPlan();
      if (what === 'journals') return backend.journalsClean(body);
      if (what === 'pool/release/plan') return backend.poolReleasePlan(body);
      if (what === 'pool/release') return backend.poolRelease(body);
      if (what === 'archive/plan') return backend.archivePlan();
      if (what === 'archive') return backend.archiveRun(body);
    }
    return null;
  } catch (e) {
    if (e instanceof Fault)
      return { status: e.status, body: { message: e.message, code: e.code, details: e.details } };
    throw e;
  }
}
