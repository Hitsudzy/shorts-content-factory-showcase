// API каналов (CC-0006 фабрики): список, карточка, проверка, сохранение, история, «вернуть».
// Отказы — `ChannelProblem` с русским `message` (показывается как есть) и техническими
// `details` (только под «подробнее»).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, ApiError, type Schemas } from './client';
import { recheckWhileChecking } from './freshness';

export type ChannelSummary = Schemas['ChannelSummary'];
export type ChannelList = Schemas['ChannelList'];
export type ChannelDetail = Schemas['ChannelDetail'];
export type ConfigField = Schemas['ConfigField'];
export type CheckLine = Schemas['CheckLine'];
export type CheckResult = Schemas['CheckResult'];
export type ChannelEdit = Schemas['ChannelEdit'];
export type ChannelHistory = Schemas['ChannelHistory'];
export type HistoryEntry = Schemas['HistoryEntry'];
export type SaveResult = Schemas['SaveResult'];
export type ChannelProblem = Schemas['ChannelProblem'];
export type ChannelLock = Schemas['ChannelLock'];
export type ChannelTemplate = Schemas['ChannelTemplate'];
export type TemplateInput = Schemas['TemplateInput'];
export type NewChannel = Schemas['NewChannel'];
export type CreateResult = Schemas['CreateResult'];

/** Отказ API каналов: `problem` — тело `ChannelProblem`, если пришло оно. */
export class ChannelError extends ApiError {
  readonly problem: ChannelProblem | null;

  constructor(status: number, message: string, problem: ChannelProblem | null) {
    super(status, message);
    this.name = 'ChannelError';
    this.problem = problem;
  }
}

type LooseProblem = Omit<ChannelProblem, 'errors' | 'batches' | 'details'> &
  Partial<Pick<ChannelProblem, 'errors' | 'batches' | 'details'>>;

function isProblem(x: unknown): x is LooseProblem {
  return typeof x === 'object' && x !== null && 'code' in x && 'message' in x;
}

type Result<T> = { data?: T; error?: unknown; response: Response };

function take<T>({ data, error, response }: Result<T>): T {
  if (response.ok && data !== undefined) return data;
  // Отказ «только смотреть» (409 `not_working_factory`, CC-0058) — `WritesProblem` без
  // `errors`/`batches`: дополняем пустыми, чтобы экраны каналов читали его как любой отказ.
  const problem = isProblem(error)
    ? {
        ...error,
        errors: error.errors ?? [],
        batches: error.batches ?? [],
        details: error.details ?? [],
      }
    : null;
  const where = `${response.status} ${new URL(response.url || 'http://x/').pathname}`;
  const refusal =
    typeof error === 'object' && error !== null && 'detail' in error
      ? String((error as { detail: unknown }).detail)
      : null;
  throw new ChannelError(
    response.status,
    problem ? problem.message : refusal ? `${where}: ${refusal}` : where,
    problem,
  );
}

const path = (channel: string) => ({ params: { path: { channel } } });

/** Все каналы и свежесть их `locked` (`checked_at`, `age_s`, `checking` — одни на весь список). */
export async function getChannels(signal?: AbortSignal): Promise<ChannelList> {
  return take(await api.GET('/api/channels', { signal }));
}

export async function getChannel(channel: string, signal?: AbortSignal): Promise<ChannelDetail> {
  return take(await api.GET('/api/channels/{channel}', { ...path(channel), signal }));
}

export async function checkChannel(channel: string, body: ChannelEdit): Promise<CheckResult> {
  return take(await api.POST('/api/channels/{channel}/check', { ...path(channel), body }));
}

export async function saveChannel(channel: string, body: ChannelEdit): Promise<SaveResult> {
  return take(await api.PUT('/api/channels/{channel}', { ...path(channel), body }));
}

export async function getHistory(
  channel: string,
  limit = 30,
  signal?: AbortSignal,
): Promise<ChannelHistory> {
  return take(
    await api.GET('/api/channels/{channel}/history', {
      params: { path: { channel }, query: { limit } },
      signal,
    }),
  );
}

export async function revertCommit(
  channel: string,
  commit: string,
  base: string,
): Promise<SaveResult> {
  return take(
    await api.POST('/api/channels/{channel}/history/{commit}/revert', {
      params: { path: { channel, commit } },
      body: { base },
    }),
  );
}

/** Шаблон нового канала (CC-0008 фабрики): входы, их пояснения, файлы, можно ли создать сейчас. */
export async function getTemplate(signal?: AbortSignal): Promise<ChannelTemplate> {
  return take(await api.GET('/api/channels/template', { signal }));
}

/**
 * Новый канал. `dry_run: true` — проверить и показать файлы, ничего не записав (всегда 200,
 * ошибки входов — в `errors` с `field`); без него — один коммит трёх файлов или отказ.
 */
export async function createChannel(body: NewChannel, signal?: AbortSignal): Promise<CreateResult> {
  return take(await api.POST('/api/channels', { body, signal }));
}

export const channelKeys = {
  template: ['api', 'channels', 'template'] as const,
  list: ['api', 'channels'] as const,
  detail: (id: string) => ['api', 'channels', id] as const,
  history: (id: string) => ['api', 'channels', id, 'history'] as const,
};

// Пока фабрика сканирует батчи (`checking`), ответ — прошлый итог: тихо переспросить.
const recheckList = recheckWhileChecking<ChannelList>((l) => l);
const recheckDetail = recheckWhileChecking<ChannelDetail>((d) => d.lock);
const recheckTemplate = recheckWhileChecking<ChannelTemplate>((t) => t.lock);
const selectChannels = (l: ChannelList) => l.channels;

/** Список каналов со свежестью блокировок. */
export function useChannelList() {
  return useQuery({
    queryKey: channelKeys.list,
    queryFn: ({ signal }) => getChannels(signal),
    refetchInterval: recheckList,
  });
}

/** Только каналы (главная). Тот же запрос, что и `useChannelList`. */
export function useChannels() {
  return useQuery({
    queryKey: channelKeys.list,
    queryFn: ({ signal }) => getChannels(signal),
    refetchInterval: recheckList,
    select: selectChannels,
  });
}

/**
 * Карточка канала. Ответ тяжёлый (у example-film ~480 КБ: весь конфиг, текст файла,
 * описание полей), поэтому сам не перезапрашивается: только по явному «обновить», после
 * сохранения (ответ сохранения несёт свежую карточку) и — на экране канала (`recheck`) —
 * пока фабрика заново сканирует батчи (`lock.checking`), с растущей паузой.
 */
export function useChannel(id: string | undefined, { recheck = true }: { recheck?: boolean } = {}) {
  return useQuery({
    queryKey: channelKeys.detail(id ?? ''),
    queryFn: ({ signal }) => getChannel(id!, signal),
    enabled: !!id,
    staleTime: Infinity,
    refetchInterval: recheck ? recheckDetail : false,
    // Один повтор — только на сбой сервера (5xx); «нет такого канала» не повторяем.
    retry: (n, e) => n < 1 && e instanceof ApiError && e.status >= 500,
  });
}

export function useHistory(id: string, enabled = true) {
  return useQuery({
    queryKey: channelKeys.history(id),
    queryFn: ({ signal }) => getHistory(id, 30, signal),
    enabled,
    retry: false,
  });
}

/** Отказ записи «идёт батч» (409 `batch_running`). */
export function isBatchRunning(e: unknown): boolean {
  return e instanceof ChannelError && e.problem?.code === 'batch_running';
}

/**
 * После сохранения или «вернуть»: свежая карточка из ответа, список и история — заново.
 * Отказ «идёт батч» — запись нашла батч, которого чтение ещё не видело: карточку и список
 * перечитать, чтобы экран показал блокировку (черновик остаётся: ревизия та же).
 */
function useAfterWrite(id: string) {
  const qc = useQueryClient();
  return {
    onSuccess: (r: SaveResult) => {
      qc.setQueryData(channelKeys.detail(id), r.channel);
      void qc.invalidateQueries({ queryKey: channelKeys.list, exact: true });
      void qc.invalidateQueries({ queryKey: channelKeys.history(id) });
    },
    onError: (e: unknown) => {
      if (!isBatchRunning(e)) return;
      void qc.invalidateQueries({ queryKey: channelKeys.detail(id) });
      void qc.invalidateQueries({ queryKey: channelKeys.list, exact: true });
    },
  };
}

export function useCheckChannel(id: string) {
  return useMutation({ mutationFn: (body: ChannelEdit) => checkChannel(id, body) });
}

export function useSaveChannel(id: string) {
  const after = useAfterWrite(id);
  return useMutation({
    mutationFn: (body: ChannelEdit) => saveChannel(id, body),
    ...after,
  });
}

export function useRevertCommit(id: string) {
  const after = useAfterWrite(id);
  return useMutation({
    mutationFn: ({ commit, base }: { commit: string; base: string }) =>
      revertCommit(id, commit, base),
    ...after,
  });
}

/**
 * Шаблон нового канала. Батчи фабрика в ответе не ищет — говорит последний известный итог
 * (`lock.checked_at`, `age_s`); пока идёт новый скан (`lock.checking`), шаблон тихо
 * переспрашивается. Мастер перечитывает его ещё на шаге «Создать»; само создание всё равно
 * проверяет батчи заново.
 */
export function useChannelTemplate() {
  return useQuery({
    queryKey: channelKeys.template,
    queryFn: ({ signal }) => getTemplate(signal),
    staleTime: Infinity,
    refetchOnWindowFocus: false,
    refetchInterval: recheckTemplate,
  });
}
