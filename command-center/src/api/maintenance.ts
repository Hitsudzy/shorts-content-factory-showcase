// Обслуживание и расход (CC-0032 / CC-0104 / CC-0105 фабрики, договор 0.58.0; экран — CC-0033).
// Чтения: что фабрика открывает центру (`GET /api/maintenance` — по каждому скрипту: чтение,
// план → «да» или не открыт, и почему), расход батча в токенах (`GET …/usage/{c}/{b}` —
// `usage_report.py --json`; событий ещё нет — `ok: false` и подсказка фабрики), сравнение батча
// вручную с батчем исполнителя (`GET …/compare?manual=c/b&executor=c/b` — `compare_runs.py`),
// пул футажа (`GET …/pool[?stale_days=N]` — что освободит уборка, что остаётся и почему) и сухой
// прогон месячного архива (`GET …/archive` — его строки и код выхода). Записи — план с токеном
// (120 с, одноразовый) и «да» `{confirm}`: уборка журналов батчей (`…/journals/plan` →
// `…/journals`), освобождение пула (`…/pool/release/plan {stale_days}` → `…/pool/release`) и
// месячный архив, шаг (а) — месяц уходит из publish/ на диск архива (`…/archive/plan` →
// `…/archive`, идёт до часа). Пока открыт батч — токена нет (`open_batches`), «да» —
// `batch_open`. Отказы — `MaintenanceProblem {message, code, details}` (разбирает `takeBatch`),
// словами — `maintenanceProblemText`.
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type Maintenance = Schemas['Maintenance'];
export type MaintenanceScript = Schemas['MaintenanceScript'];
export type MaintenanceProblem = Schemas['MaintenanceProblem'];
export type UsageReport = Schemas['UsageReport'];
export type UsageRow = Schemas['UsageRow'];
export type UsageTotals = Schemas['UsageTotals'];
export type CompareRuns = Schemas['CompareRuns'];
export type PoolView = Schemas['PoolView'];
export type PoolSource = Schemas['PoolSource'];
export type PoolSum = Schemas['PoolSum'];
export type PoolVariant = Schemas['PoolVariant'];
export type PoolReleasePlan = Schemas['PoolReleasePlan'];
export type PoolReleaseResult = Schemas['PoolReleaseResult'];
export type JournalsPlan = Schemas['JournalsPlan'];
export type JournalsResult = Schemas['JournalsResult'];
export type JournalRow = Schemas['JournalRow'];
export type ArchiveDryRun = Schemas['ArchiveDryRun'];
export type ArchivePlan = Schemas['ArchivePlan'];
export type ArchiveResult = Schemas['ArchiveResult'];
export type ArchiveJob = Schemas['ArchiveJob'];

/** Срок жизни подтверждения у фабрики, с. */
export const CONFIRM_LIFE_S = 120;
/** Настоящий прогон архива идёт до часа (`ARCHIVE_APPLY_TIMEOUT_S` фабрики) — ждём с запасом. */
export const ARCHIVE_TIMEOUT_MS = 65 * 60_000;
/** Правило «законченная тема» по давности, дней (его же берёт месячный архив). */
export const STALE_DAYS = 14;

export async function getMaintenance(signal?: AbortSignal): Promise<Maintenance> {
  return takeBatch(await api.GET('/api/maintenance', { signal }));
}

/** «example-film/2026-10-09T0215Z» → расход батча. */
export async function getUsage(batch: string, signal?: AbortSignal): Promise<UsageReport> {
  const i = batch.indexOf('/');
  return takeBatch(
    await api.GET('/api/maintenance/usage/{channel}/{batch_id}', {
      params: { path: { channel: batch.slice(0, i), batch_id: batch.slice(i + 1) } },
      signal,
    }),
  );
}

export async function getCompare(
  manual: string,
  executor: string,
  signal?: AbortSignal,
): Promise<CompareRuns> {
  return takeBatch(
    await api.GET('/api/maintenance/compare', {
      params: { query: { manual, executor } },
      signal,
    }),
  );
}

export async function getPool(staleDays: number | null, signal?: AbortSignal): Promise<PoolView> {
  return takeBatch(
    await api.GET('/api/maintenance/pool', {
      params: { query: staleDays == null ? {} : { stale_days: staleDays } },
      signal,
    }),
  );
}

export async function getArchive(signal?: AbortSignal): Promise<ArchiveDryRun> {
  return takeBatch(await api.GET('/api/maintenance/archive', { signal }));
}

const call = <T>(fn: (signal: AbortSignal) => Promise<T>, ms = PLAN_TIMEOUT_MS) => within(ms, fn);

export const planJournals = () =>
  call(async (signal) => takeBatch(await api.POST('/api/maintenance/journals/plan', { signal })));

export const cleanJournals = (confirm: string) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/maintenance/journals', { body: { confirm }, signal })),
  );

export const planPoolRelease = (staleDays: number | null) =>
  call(async (signal) =>
    takeBatch(
      await api.POST('/api/maintenance/pool/release/plan', {
        body: { stale_days: staleDays },
        signal,
      }),
    ),
  );

export const releasePool = (confirm: string) =>
  call(async (signal) =>
    takeBatch(await api.POST('/api/maintenance/pool/release', { body: { confirm }, signal })),
  );

export const planArchive = () =>
  call(async (signal) => takeBatch(await api.POST('/api/maintenance/archive/plan', { signal })));

export const runArchive = (confirm: string, ms = ARCHIVE_TIMEOUT_MS) =>
  call(
    async (signal) =>
      takeBatch(await api.POST('/api/maintenance/archive', { body: { confirm }, signal })),
    ms,
  );

export const maintenanceKeys = {
  all: ['api', 'maintenance'] as const,
  overview: ['api', 'maintenance', 'overview'] as const,
  usage: (batch: string) => ['api', 'maintenance', 'usage', batch] as const,
  compare: (manual: string, executor: string) =>
    ['api', 'maintenance', 'compare', manual, executor] as const,
  pool: (staleDays: number | null) => ['api', 'maintenance', 'pool', staleDays] as const,
  archive: ['api', 'maintenance', 'archive'] as const,
};

/** Отказ 4xx (вид неизвестен) повтором не лечится; сеть и 5xx — до трёх раз. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Что фабрика открывает центру: меняется только с выпуском — без опроса. */
export function useMaintenance() {
  return useQuery({
    queryKey: maintenanceKeys.overview,
    queryFn: ({ signal }) => getMaintenance(signal),
    staleTime: 5 * 60_000,
    retry,
  });
}

/** Расход батча: прошлый батч не меняется, идущий — дописывается; перечитываем раз в минуту. */
export function useUsage(batch: string | null) {
  return useQuery({
    queryKey: maintenanceKeys.usage(batch ?? ''),
    queryFn: ({ signal }) => getUsage(batch!, signal),
    enabled: !!batch,
    staleTime: 60_000,
    retry,
  });
}

/** Сравнение двух прошлых батчей: только по кнопке, без опроса. */
export function useCompare(pair: { manual: string; executor: string } | null) {
  return useQuery({
    queryKey: maintenanceKeys.compare(pair?.manual ?? '', pair?.executor ?? ''),
    queryFn: ({ signal }) => getCompare(pair!.manual, pair!.executor, signal),
    enabled: !!pair,
    staleTime: Infinity,
    retry,
  });
}

/** Пул футажа: меняется с каждым батчем — раз в пять минут и при возврате на вкладку. */
export function usePool(staleDays: number | null) {
  return useQuery({
    queryKey: maintenanceKeys.pool(staleDays),
    queryFn: ({ signal }) => getPool(staleDays, signal),
    refetchInterval: 5 * 60_000,
    refetchIntervalInBackground: false,
    retry,
  });
}

/** Сухой прогон архива — небыстрый (скрипт фабрики): без опроса. */
export function useArchive() {
  return useQuery({
    queryKey: maintenanceKeys.archive,
    queryFn: ({ signal }) => getArchive(signal),
    staleTime: 5 * 60_000,
    retry,
  });
}

/** После уборки (и отказа «да») перечитать всё про обслуживание. */
export function useAfterMaintenance() {
  const qc = useQueryClient();
  return () => void qc.invalidateQueries({ queryKey: maintenanceKeys.all });
}

// ---------------------------------------------------------------- слова
const MAINTENANCE_PROBLEM_TEXT: Record<string, string> = {
  unknown_batch: 'Такого батча на фабрике нет',
  invalid: 'Батч указан не так — выберите его из списка',
  bad_call: 'Эти два батча не сравнить — выберите другие',
  refused: 'Делать уже нечего — фабрика ничего не тронула',
  batch_open: 'Идёт батч — уборки и архив ждут, пока он закончится',
  check_changed: 'С момента плана что-то изменилось — посмотрите план заново',
  busy: 'Идёт другая уборка — подождите и нажмите ещё раз',
  factory_broken: 'Фабрика ответила ошибкой — посмотрите состояние, прежде чем повторять',
  volume_missing: 'Диск архива не подключён — подключите его и запросите план заново',
};

export const maintenanceProblemText = (code: string | null | undefined): string =>
  (code && MAINTENANCE_PROBLEM_TEXT[code]) || writeProblemText(code);
