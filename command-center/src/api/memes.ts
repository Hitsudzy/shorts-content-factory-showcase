// Стол мемов канала (CC-0024 фабрики, договор 0.24.0). Чтение: банки по каналам (`/api/memes`)
// и стол канала (`/api/memes/{channel}` — записи банка, черновик отметок и его отпечаток
// `fingerprint`, сводка `status`). Записи: черновик отметок целиком (`PUT …/marks {decisions,
// base}`; `base` — отпечаток, от которого черновик правили, чужой — `check_changed`, ничего не
// записано) и «применить разбор» в два шага: план (`…/apply/plan {drop}` → проверка и токен) и
// «да» (`…/apply {confirm}`). Отказы — `{message, code, details}`, как у батчей (./batchProblem).
import { useQuery, useQueryClient } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type MemesOverview = Schemas['MemesOverview'];
export type MemeBankRow = Schemas['MemeBankRow'];
export type MemeDesk = Schemas['MemeDesk'];
export type MemeEntry = Schemas['MemeEntry'];
export type MemeDeskStatus = Schemas['MemeDeskStatus'];
export type MemeApplyPlan = Schemas['MemeApplyPlan'];
export type MemeApplyResult = Schemas['MemeApplyResult'];
export type MemeMarksResult = Schemas['MemeMarksResult'];
export type MemesProblem = Schemas['MemesProblem'];

/** Отметка черновика, как её хранит стол: `{v, cut, note}`; кто и когда — если ставил центр. */
export type SavedMark = {
  v?: 'keep' | 'drop';
  cut?: boolean;
  note?: string;
  marked_by?: string;
  marked_at?: string;
  via?: string;
};

export async function getMemesOverview(signal?: AbortSignal): Promise<MemesOverview> {
  return takeBatch(await api.GET('/api/memes', { signal }));
}

export async function getMemeDesk(channel: string, signal?: AbortSignal): Promise<MemeDesk> {
  return takeBatch(
    await api.GET('/api/memes/{channel}', { params: { path: { channel } }, signal }),
  );
}

/** Черновик целиком; `base` — отпечаток, от которого его правили (`null` — черновика не было). */
export function putMarks(
  channel: string,
  decisions: Record<string, Record<string, unknown>>,
  base: string | null,
  ms = PLAN_TIMEOUT_MS,
): Promise<MemeMarksResult> {
  return within(ms, async (signal) =>
    takeBatch(
      await api.PUT('/api/memes/{channel}/marks', {
        params: { path: { channel } },
        body: { decisions, base },
        signal,
      }),
    ),
  );
}

export function planApply(channel: string, drop: boolean, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/apply/plan', {
        params: { path: { channel } },
        body: { drop },
        signal,
      }),
    ),
  );
}

export function applyMarks(channel: string, confirm: string, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/apply', {
        params: { path: { channel } },
        body: { confirm },
        signal,
      }),
    ),
  );
}

export const memeKeys = {
  all: ['api', 'memes'] as const,
  overview: ['api', 'memes', 'overview'] as const,
  desk: (channel: string) => ['api', 'memes', 'desk', channel] as const,
};

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Банки мемов по каналам со счётчиками стола. */
export function useMemesOverview() {
  return useQuery({
    queryKey: memeKeys.overview,
    queryFn: ({ signal }) => getMemesOverview(signal),
    retry,
  });
}

/** Стол мемов канала: записи, черновик отметок и его отпечаток. */
export function useMemeDesk(channel: string | null) {
  return useQuery({
    queryKey: memeKeys.desk(channel ?? ''),
    queryFn: ({ signal }) => getMemeDesk(channel!, signal),
    enabled: !!channel,
    retry,
  });
}

/** После записи: перечитать обзор банков и столы (каналы одного банка делят черновик). */
export function useAfterMemes() {
  const qc = useQueryClient();
  return () => qc.invalidateQueries({ queryKey: memeKeys.all });
}
