// Батчи фабрики (CC-0044/0045): идущие батчи, один батч, его события по курсору, история
// прогонов, стадии прогона и хвост журнала. Только чтение. Адрес батча — поле `batch`
// ответа («<каталог>/<batch_id>»; пересборка — `rebuilds/<ts>`), никогда не `channel`.
// Опросы — TanStack Query `refetchInterval` с паузой, которую советует фабрика (`poll_s`);
// на скрытой вкладке и после ухода со страницы опрос стоит (`refetchIntervalInBackground:
// false`, нет наблюдателей — нет опроса). Отказы — `BatchError` (./batchProblem).
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { feedDelay, pullFeed, type BatchEvents, type Feed } from './eventsFeed';

export type BatchesGoing = Schemas['BatchesGoing'];
export type GoingBatch = Schemas['GoingBatch'];
export type GoingStage = Schemas['GoingStage'];
export type BatchDetail = Schemas['BatchDetail'];
export type RunState = Schemas['RunState'];
export type BatchProcess = Schemas['BatchProcess'];
export type BatchQuestion = Schemas['Question'];
export type BatchHistory = Schemas['BatchHistory'];
export type BatchRun = Schemas['BatchRun'];
export type Launch = Schemas['Launch'];
export type BatchStages = Schemas['BatchStages'];
export type StageSpan = Schemas['StageSpan'];
export type LogFile = Schemas['LogFile'];
export type LogTail = Schemas['LogTail'];
export type StrandedBatches = Schemas['StrandedBatches'];
export type StrandedBatch = Schemas['StrandedBatch'];
export type BatchFootage = Schemas['BatchFootage'];
export type FootageTopic = Schemas['FootageTopic'];

/** Пауза опроса списка, если фабрика её не сказала (договор: `poll_s` = 15). */
export const LIST_POLL_S = 15;
/** Пауза опроса ленты событий по умолчанию (договор: `poll_s` = 3). */
export const EVENTS_POLL_S = 3;
/** Прогонов в истории экрана. */
export const HISTORY_LIMIT = 20;
/** Упавших батчей на экране (договор: `limit` по умолчанию 20). */
export const STRANDED_LIMIT = 20;
/** Сколько байт хвоста журнала спрашивать. */
export const TAIL_BYTES = 32 * 1024;

/** «example-film/2026-10-08T1824Z» → части пути API; null — не путь батча. */
export function batchPath(batch: string | null | undefined) {
  if (!batch) return null;
  const i = batch.indexOf('/');
  if (i <= 0 || i === batch.length - 1 || batch.indexOf('/', i + 1) >= 0) return null;
  return { channel: batch.slice(0, i), batch_id: batch.slice(i + 1) };
}

/** Пересборка роликов готового батча (CC-0048): её каталог — `rebuilds/<ts>`. */
export const isRebuild = (batch: string | null | undefined) => !!batch?.startsWith('rebuilds/');

/**
 * Путь API упавшего батча (CC-0089 → CC-0115): `batch` строки фабрики, как у идущих
 * (`<канал>/<batch_id>`, `rebuilds/<ts>`), — центр его из каталога больше не выводит. null —
 * фабрика пути не дала или он не путь батча (центру его не открыть).
 */
export function strandedBatch(row: Pick<StrandedBatch, 'batch'>): string | null {
  return row.batch && batchPath(row.batch) ? row.batch : null;
}

/** Имя журнала стадии упавшего батча для `…/logs/{name}` — `log_name` фабрики; null — нет. */
export function strandedLogName(row: Pick<StrandedBatch, 'log_name'>): string | null {
  return row.log_name || null;
}

function pathOf(batch: string) {
  const p = batchPath(batch);
  if (!p) throw new Error(`не путь батча: ${batch}`);
  return p;
}

export async function getGoing(signal?: AbortSignal): Promise<BatchesGoing> {
  return takeBatch(await api.GET('/api/batches', { signal }));
}

export async function getBatch(batch: string, signal?: AbortSignal): Promise<BatchDetail> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}', {
      params: { path: pathOf(batch) },
      signal,
    }),
  );
}

export async function getEvents(
  batch: string,
  after: number | null,
  signal?: AbortSignal,
): Promise<BatchEvents> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/events', {
      params: { path: pathOf(batch), query: after == null ? {} : { after } },
      signal,
    }),
  );
}

export async function getHistory(
  limit = HISTORY_LIMIT,
  channel?: string,
  signal?: AbortSignal,
): Promise<BatchHistory> {
  return takeBatch(
    await api.GET('/api/batches/history', {
      params: { query: channel ? { limit, channel } : { limit } },
      signal,
    }),
  );
}

export async function getStranded(
  limit = STRANDED_LIMIT,
  signal?: AbortSignal,
): Promise<StrandedBatches> {
  return takeBatch(
    await api.GET('/api/batches/stranded', { params: { query: { limit } }, signal }),
  );
}

export async function getStages(batch: string, signal?: AbortSignal): Promise<BatchStages> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/stages', {
      params: { path: pathOf(batch) },
      signal,
    }),
  );
}

/** Сбор футажа по темам (CC-0119, CF-0715 `footage_progress`). */
export async function getFootage(batch: string, signal?: AbortSignal): Promise<BatchFootage> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/footage', {
      params: { path: pathOf(batch) },
      signal,
    }),
  );
}

export async function getLogTail(
  batch: string,
  name: string,
  bytes = TAIL_BYTES,
  signal?: AbortSignal,
): Promise<LogTail> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/logs/{name}', {
      params: { path: { ...pathOf(batch), name }, query: { bytes } },
      signal,
    }),
  );
}

export const batchKeys = {
  all: ['api', 'batches'] as const,
  going: ['api', 'batches', 'going'] as const,
  one: (batch: string) => ['api', 'batches', 'one', batch] as const,
  events: (batch: string) => ['api', 'batches', 'events', batch] as const,
  history: (limit: number) => ['api', 'batches', 'history', limit] as const,
  /** Упавшие батчи (CC-0089). */
  stranded: ['api', 'batches', 'stranded'] as const,
  /** Можно ли продолжить упавший батч — `resume/plan` (CC-0089). */
  resumeCheck: (batch: string) => ['api', 'batches', 'resume-check', batch] as const,
  stages: (batch: string) => ['api', 'batches', 'stages', batch] as const,
  /** Сбор футажа по темам (CC-0119). */
  footage: (batch: string) => ['api', 'batches', 'footage', batch] as const,
  /** Жив ли исполнитель батча — фоновая проверка `resume/plan` (CC-0094). */
  executor: (batch: string) => ['api', 'batches', 'executor', batch] as const,
  log: (batch: string, name: string, bytes: number) =>
    ['api', 'batches', 'log', batch, name, bytes] as const,
};

/**
 * Повтор при сбое: сеть и 5xx — до трёх раз; отказ фабрики 4xx (нет батча, нет журнала) —
 * сразу, повтор ответа не изменит. Опрос всё равно спросит снова в свой срок.
 */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

const sec = (s: number | null | undefined, fallback: number) => Math.max(1, s ?? fallback) * 1000;

/** Идущие батчи: опрос раз в `poll_s` (15 с), только пока вкладка видна. */
export function useGoingBatches() {
  return useQuery({
    queryKey: batchKeys.going,
    queryFn: ({ signal }) => getGoing(signal),
    refetchInterval: (q) => sec(q.state.data?.poll_s, LIST_POLL_S),
    refetchIntervalInBackground: false,
    retry,
  });
}

/**
 * Один батч (run-state целиком, процессы, вопросы) — с тем же шагом, что список. `enabled`
 * false — не спрашивать (главная спрашивает только об идущем батче, CC-0094).
 */
export function useBatch(batch: string, enabled = true) {
  return useQuery({
    queryKey: batchKeys.one(batch),
    queryFn: ({ signal }) => getBatch(batch, signal),
    enabled,
    refetchInterval: LIST_POLL_S * 1000,
    refetchIntervalInBackground: false,
    retry,
  });
}

/**
 * Лента событий батча по курсору: каждый опрос продолжает с `next` прошлого (лента — в кэше
 * запроса), при `more` — дочитывает сразу, при `reset` — начинает заново. Опрос — раз в
 * `poll_s` (3 с), только пока лента на экране и вкладка видна.
 */
export function useBatchEvents(batch: string, enabled = true) {
  const qc = useQueryClient();
  const key = batchKeys.events(batch);
  return useQuery<Feed>({
    queryKey: key,
    queryFn: ({ signal }) =>
      pullFeed(qc.getQueryData<Feed>(key), (after) => getEvents(batch, after, signal)),
    enabled,
    staleTime: 0,
    structuralSharing: false,
    refetchInterval: (q) => feedDelay(q.state.data, EVENTS_POLL_S),
    refetchIntervalInBackground: false,
    retry,
  });
}

/** История прогонов (все каналы, новые сверху): раз в минуту. */
export function useBatchHistory(limit = HISTORY_LIMIT) {
  return useQuery({
    queryKey: batchKeys.history(limit),
    queryFn: ({ signal }) => getHistory(limit, undefined, signal),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    retry,
  });
}

/**
 * Упавшие батчи (все каналы, новые сверху): раз в минуту, как история — это тоже прошлые
 * батчи, а не идущие.
 */
export function useStrandedBatches() {
  return useQuery({
    queryKey: batchKeys.stranded,
    queryFn: ({ signal }) => getStranded(STRANDED_LIMIT, signal),
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    retry,
  });
}

/** Стадии прогона: пока батч не закрыт (`closed` false) — опрос раз в 15 с. */
export function useBatchStages(batch: string) {
  return useQuery({
    queryKey: batchKeys.stages(batch),
    queryFn: ({ signal }) => getStages(batch, signal),
    refetchInterval: (q) => (q.state.data?.closed ? false : LIST_POLL_S * 1000),
    refetchIntervalInBackground: false,
    retry,
  });
}

/**
 * Сбор футажа по темам (CC-0119): пока батч идёт (`going`) и сбор не закончен — опрос раз в
 * `poll_s` фабрики; закончен или батч стоит — один раз, без опроса.
 */
export function useBatchFootage(batch: string, going: boolean) {
  return useQuery({
    queryKey: batchKeys.footage(batch),
    queryFn: ({ signal }) => getFootage(batch, signal),
    refetchInterval: (q) =>
      going && !q.state.data?.finished ? sec(q.state.data?.poll_s, LIST_POLL_S) : false,
    refetchIntervalInBackground: false,
    retry,
  });
}

/** Хвост журнала прогона — по запросу, без опроса («Обновить» — руками). */
export function useLogTail(batch: string, name: string, bytes = TAIL_BYTES) {
  return useQuery({
    queryKey: batchKeys.log(batch, name, bytes),
    queryFn: ({ signal }) => getLogTail(batch, name, bytes, signal),
    staleTime: Infinity,
    retry,
  });
}
