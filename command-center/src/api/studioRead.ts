// Чтение YouTube Studio по кнопке (CC-0120, фабрика CF-0735, договор 0.49+). Хуки «пора ли» —
// `GET /api/studio/due?hook=` — только подсвечивают кнопку «Прочитать Studio», сами ничего не
// запускают: первое открытие центра за день (раз на загрузку приложения, не на опросе), окно
// запуска батча (`batch-start`) и карточка загрузки ролика (`upload`). Клик — план
// `POST /api/studio/read/plan` (что прочитает, нужен ли вход), «да» с токеном — `POST
// /api/studio/read {confirm}` (сессия Claude с Chrome пользователя стартует отдельно и сразу
// отвечает), итог — опрос `GET /api/studio/read/{run_id}` раз в `poll_s`, пока не `done`.
// Запуск на API выключен выключателем (`launch.available: false`, STUDIO_READ_LAUNCH): первый
// настоящий запуск делается вместе с пользователем — кнопка погашена, план виден.
// Отказы — `StudioCenterProblem {message, code, details}`, та же форма, что у батчей:
// `BatchError` (./batchProblem), чтобы окно подтверждения было общим (`useConfirmFlow`).
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { within } from './batchActions';
import { BatchError, takeBatch } from './batchProblem';
import { api, ApiError, NOT_WORKING_FACTORY, type Schemas } from './client';
import { useHealth } from './hooks';
import { writesOf } from './writes';

export type StudioReadDue = Schemas['StudioReadDue'];
export type StudioReadDueChannel = Schemas['StudioReadDueChannel'];
export type StudioLaunch = Schemas['StudioLaunch'];
export type StudioReadPlan = Schemas['StudioReadPlan'];
export type StudioReadStarted = Schemas['StudioReadStarted'];
export type StudioReadResult = Schemas['StudioReadResult'];
export type StudioRefusal = Schemas['StudioRefusal'];
export type StudioCenterProblem = Schemas['StudioCenterProblem'];
export type StudioHook = NonNullable<StudioReadDue['hook']>;

/** Хук первого открытия центра за день: пишет `center-opens.json` — нужна рабочая фабрика. */
export const FIRST_OPEN: StudioHook = 'center-first-open-of-day';

/** Пауза опроса итога, если фабрика её не сказала. */
export const READ_POLL_S = 5;
/** План и запуск отвечают сразу (сессия стартует отдельно). */
export const STUDIO_TIMEOUT_MS = 30_000;

export const studioKeys = {
  all: ['api', 'studio'] as const,
  due: (hook: StudioHook | null, channel: string | null) =>
    ['api', 'studio', 'due', hook ?? 'none', channel ?? '*'] as const,
  run: (runId: string) => ['api', 'studio', 'run', runId] as const,
};

export async function getStudioDue(
  hook: StudioHook | null,
  channel: string | null = null,
  signal?: AbortSignal,
): Promise<StudioReadDue> {
  const query: { hook?: StudioHook; channel?: string } = {};
  if (hook) query.hook = hook;
  if (channel) query.channel = channel;
  return takeBatch(await api.GET('/api/studio/due', { params: { query }, signal }));
}

export function planStudioRead(ms = STUDIO_TIMEOUT_MS): Promise<StudioReadPlan> {
  // Поля плана, что до запуска всегда null (`run_id`, `pid`, `log`), openapi-fetch из типа
  // ответа выкидывает — тип берём из схемы.
  return within(
    ms,
    async (signal) =>
      takeBatch(await api.POST('/api/studio/read/plan', { signal })) as StudioReadPlan,
  );
}

export function startStudioRead(
  confirm: string,
  ms = STUDIO_TIMEOUT_MS,
): Promise<StudioReadStarted> {
  return within(ms, async (signal) =>
    takeBatch(await api.POST('/api/studio/read', { body: { confirm }, signal })),
  );
}

export async function getStudioReadResult(
  runId: string,
  signal?: AbortSignal,
): Promise<StudioReadResult> {
  return takeBatch(
    await api.GET('/api/studio/read/{run_id}', { params: { path: { run_id: runId } }, signal }),
  );
}

/** Отказ «не рабочая фабрика» (409): хук пропускается тихо — кнопки нет, тревоги нет. */
export const isReadOnlyRefusal = (e: unknown) =>
  e instanceof ApiError &&
  e.status === 409 &&
  (!(e instanceof BatchError) || !e.problem || (e.problem.code as string) === NOT_WORKING_FACTORY);

/**
 * Пора ли читать Studio по хуку. Первое открытие за день — один раз на загрузку приложения
 * (ответ не устаревает, не перечитывается на фокусе), и только на рабочей фабрике: этот хук
 * пишет. Остальные хуки — пока их место на экране (`enabled`), без опроса. Ошибка — тихо: хук
 * только подсвечивает кнопку, без него центр работает как обычно.
 */
export function useStudioDue(
  hook: StudioHook | null,
  { channel = null, enabled = true }: { channel?: string | null; enabled?: boolean } = {},
) {
  const health = useHealth().data;
  const first = hook === FIRST_OPEN;
  // Первое открытие — только когда health пришёл и пишет: иначе 409 зря (и в консоли).
  const firstOk = !!health && writesOf(health).allowed;
  return useQuery({
    queryKey: studioKeys.due(hook, channel),
    queryFn: ({ signal }) => getStudioDue(hook, channel, signal),
    enabled: enabled && (!first || firstOk),
    staleTime: first ? Infinity : 60_000,
    gcTime: first ? Infinity : undefined,
    refetchOnWindowFocus: false,
    retry: false,
  });
}

/**
 * Итог сессии чтения: опрос раз в `poll_s`, пока `done` нет. `runId` null — не спрашивать.
 * Когда сессия кончилась — перечитать «пора ли» (у хуков теперь свежее чтение).
 */
export function useStudioReadRun(runId: string | null, pollS: number | null = null) {
  const qc = useQueryClient();
  return useQuery({
    queryKey: studioKeys.run(runId ?? ''),
    queryFn: async ({ signal }) => {
      const r = await getStudioReadResult(runId!, signal);
      if (r.done) void qc.invalidateQueries({ queryKey: [...studioKeys.all, 'due'] });
      return r;
    },
    enabled: !!runId,
    staleTime: 0,
    refetchOnWindowFocus: false,
    refetchInterval: (q) =>
      q.state.data?.done ? false : Math.max(1, q.state.data?.poll_s ?? pollS ?? READ_POLL_S) * 1000,
    refetchIntervalInBackground: false,
    retry: (n, e) => !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3,
  });
}
