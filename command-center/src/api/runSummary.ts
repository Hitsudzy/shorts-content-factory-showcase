// Сводка прогона батча (CC-0099 фабрики, CC-0115 центра): `GET /api/batches/{c}/{b}/summary` —
// то, что даёт `runlog summary`: разделы данными (`data`, как `--json`) и RUN_SUMMARY.md, если
// batch-done его уже написал (`file`). Ни то, ни другое не ошибка, когда их нет: `data_note` /
// `file_note` — «ещё нет»; посчитать не вышло — `data_error` (файл, если есть, всё равно приходит).
// Считается долго (весь журнал прогона): центр спрашивает один раз, когда прогон раскрыт.
import { useQuery } from '@tanstack/react-query';

import { batchPath } from './batches';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type BatchRunSummary = Schemas['BatchRunSummary'];

export async function getRunSummary(batch: string, signal?: AbortSignal): Promise<BatchRunSummary> {
  const path = batchPath(batch);
  if (!path) throw new Error(`не путь батча: ${batch}`);
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/summary', { params: { path }, signal }),
  );
}

export const runSummaryKey = (batch: string) => ['api', 'batches', 'summary', batch] as const;

/** Отказ 4xx (нет батча) — сразу: повтор ответа не изменит. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 2;

/** Сводка прогона — один раз, без опроса (прогон закрыт); `enabled` — пока раскрыт. */
export function useRunSummary(batch: string, enabled = true) {
  return useQuery({
    queryKey: runSummaryKey(batch),
    queryFn: ({ signal }) => getRunSummary(batch, signal),
    enabled,
    retry,
    staleTime: 5 * 60_000,
  });
}
