// Действия над батчами (CC-0046/0047 фабрики): запуск канала, остановить и продолжить батч.
// Каждое — в два вызова: план (проверка фабрики + одноразовый токен подтверждения на
// `expires_in_s`) и само действие с этим токеном. Записи — через общий клиент
// (`X-CC-Session`, Origin ставит браузер). Отказы — `BatchError` (./batchProblem). У
// остановки и продолжения итог судится по `ok` ответа 200, а не по коду: 200 `ok:false` —
// фабрика уже что-то сделала (сигнал ушёл, исполнитель стартовал), но не до конца.
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { batchKeys } from './batches';
import { BatchError, takeBatch } from './batchProblem';
import { api, type Schemas } from './client';

export type LaunchPlan = Schemas['LaunchPlan'];
export type LaunchGuard = Schemas['LaunchGuard'];
export type LaunchResult = Schemas['LaunchResult'];
export type StopPlan = Schemas['StopPlan'];
export type StopResult = Schemas['StopResult'];
export type ResumePlan = Schemas['ResumePlan'];
export type ResumeResult = Schemas['ResumeResult'];
export type RerunFromStages = Schemas['RerunFromStages'];
export type RerunStage = Schemas['RerunStage'];
export type RerunFromPlan = Schemas['RerunFromPlan'];
export type RerunFromResult = Schemas['RerunFromResult'];

/** Остановка ждёт исполнитель до 30 с (и шаг ещё до 30 с): клиент ждёт ответа ~70 с. */
export const STOP_TIMEOUT_MS = 70_000;
/** Продолжение ждёт замок исполнителя до 15 с. */
export const RESUME_TIMEOUT_MS = 15_000;
/** План и запуск отвечают сразу; дольше — фабрика не ответила. */
export const PLAN_TIMEOUT_MS = 30_000;
/** Повтор со стадии: сброс сразу, «сразу продолжить» ждёт замок исполнителя ещё до 15 с. */
export const RERUN_TIMEOUT_MS = 30_000;

/** Фабрика не ответила за отведённое время: что с батчем — смотреть по его состоянию. */
export class ActionTimeout extends Error {
  readonly ms: number;
  constructor(ms: number) {
    super(`фабрика не ответила за ${Math.round(ms / 1000)} с`);
    this.name = 'ActionTimeout';
    this.ms = ms;
  }
}

function pathOf(batch: string) {
  const i = batch.indexOf('/');
  if (i <= 0 || i === batch.length - 1 || batch.indexOf('/', i + 1) >= 0)
    throw new Error(`не путь батча: ${batch}`);
  return { channel: batch.slice(0, i), batch_id: batch.slice(i + 1) };
}

/** Вызов с потолком времени: по истечении — `ActionTimeout`, а не вечное «жду». */
export async function within<T>(ms: number, call: (signal: AbortSignal) => Promise<T>): Promise<T> {
  const signal = AbortSignal.timeout(ms);
  try {
    return await call(signal);
  } catch (e) {
    if (signal.aborted) throw new ActionTimeout(ms);
    throw e;
  }
}

export function planLaunch(channel: string, ms = PLAN_TIMEOUT_MS): Promise<LaunchPlan> {
  return within(ms, async (signal) =>
    takeBatch(await api.POST('/api/batches/launch/plan', { body: { channel }, signal })),
  );
}

export function launch(
  channel: string,
  confirm: string,
  ms = PLAN_TIMEOUT_MS,
): Promise<LaunchResult> {
  return within(ms, async (signal) =>
    takeBatch(await api.POST('/api/batches/launch', { body: { channel, confirm }, signal })),
  );
}

export function planStop(batch: string, alsoStep = false, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/stop/plan', {
        params: { path: pathOf(batch) },
        body: { also_step: alsoStep },
        signal,
      }),
    ),
  );
}

export function stop(batch: string, confirm: string, alsoStep: boolean, ms = STOP_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/stop', {
        params: { path: pathOf(batch) },
        body: { confirm, also_step: alsoStep },
        signal,
      }),
    ),
  );
}

export function planResume(batch: string, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/resume/plan', {
        params: { path: pathOf(batch) },
        signal,
      }),
    ),
  );
}

export function resume(batch: string, confirm: string, ms = RESUME_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/resume', {
        params: { path: pathOf(batch) },
        body: { confirm },
        signal,
      }),
    ),
  );
}

/** Какие стадии можно повторить (CC-0123, CF-0739): по каждой — можно ли и почему; только чтение. */
export async function getRerunStages(batch: string, signal?: AbortSignal) {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/rerun-from', {
      params: { path: pathOf(batch) },
      signal,
    }),
  );
}

/** Что сделает повтор со стадии `stage`: что сбросится, что останется, токен — когда можно. */
export function planRerunFrom(batch: string, stage: string, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/rerun-from/plan', {
        params: { path: pathOf(batch) },
        body: { stage },
        signal,
      }),
    ),
  );
}

/** Повторить батч со стадии плана (токен привязан к ней); `resume` — сразу продолжить. */
export function rerunFrom(
  batch: string,
  confirm: string,
  opts: { note?: string | null; resume?: boolean } = {},
  ms = RERUN_TIMEOUT_MS,
) {
  const note = opts.note?.trim() || null;
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/rerun-from', {
        params: { path: pathOf(batch) },
        body: { confirm, resume: !!opts.resume, ...(note ? { note } : {}) },
        signal,
      }),
    ),
  );
}

/** Стадии для «Повторить с…» — читаются, пока окно открыто (`enabled`), без опроса. */
export function useRerunStages(batch: string, enabled: boolean) {
  return useQuery({
    queryKey: ['api', 'batches', 'rerun-from', batch] as const,
    queryFn: ({ signal }) => getRerunStages(batch, signal),
    enabled,
    retry: false,
    staleTime: 0,
  });
}

/**
 * Отказы, после которых план надо взять заново: токен не найден, устарел, не для того
 * канала/действия или проверка с момента плана изменилась. `busy` сюда не входит — токен
 * не потрачен, нажать можно ещё раз; `refused` — тоже нет: это ответ фабрики по существу.
 */
export const REPLAN_CODES = new Set([
  'confirm_unknown',
  'confirm_expired',
  'confirm_channel',
  'confirm_mismatch',
  'check_changed',
]);

export const needsReplan = (e: unknown) =>
  e instanceof BatchError && !!e.problem && REPLAN_CODES.has(e.problem.code);

/** После действия перечитать список открытых батчей, упавшие, сам батч и историю. */
export function useAfterAction() {
  const qc = useQueryClient();
  return (batch?: string | null) => {
    void qc.invalidateQueries({ queryKey: batchKeys.going });
    void qc.invalidateQueries({ queryKey: [...batchKeys.all, 'history'] });
    void qc.invalidateQueries({ queryKey: batchKeys.stranded });
    void qc.invalidateQueries({ queryKey: [...batchKeys.all, 'resume-check'] });
    void qc.invalidateQueries({ queryKey: [...batchKeys.all, 'rerun-from'] });
    if (batch) {
      void qc.invalidateQueries({ queryKey: batchKeys.one(batch) });
      void qc.invalidateQueries({ queryKey: batchKeys.stages(batch) });
    }
    void qc.invalidateQueries({ queryKey: ['api', 'schedule'] });
  };
}
