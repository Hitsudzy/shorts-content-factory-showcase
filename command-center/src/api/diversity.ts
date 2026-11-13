// Разнообразие ленты (CC-0108 фабрики, CC-0115 центра): `GET /api/analytics/diversity` — что
// печатает `runlog diversity --last N --json`: доля каждого вида факта, схемы, ритма и первой
// фразы у последних N принятых роликов — всей фабрики или одного канала (`?channel=`, CC-0119).
// Журнала приёмки нет — пустая лента (`log_exists: false`); есть, но битый — тоже пустая, и
// `log_error` называет файл и почему. Только чтение, без опроса (лента меняется приёмкой).
import { useQuery } from '@tanstack/react-query';

import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type FeedDiversity = Schemas['FeedDiversity'];
export type DiversityAxis = Schemas['DiversityAxis'];

/** Сколько последних роликов по умолчанию (`publish_profile.DEFAULT_LAST`). */
export const DIVERSITY_LAST = 10;

export async function getDiversity(
  channel: string | null,
  last: number,
  signal?: AbortSignal,
): Promise<FeedDiversity> {
  return takeBatch(
    await api.GET('/api/analytics/diversity', {
      params: { query: channel ? { last, channel } : { last } },
      signal,
    }),
  );
}

export const diversityKey = (channel: string | null, last: number) =>
  ['api', 'analytics', 'diversity', channel ?? '*', last] as const;

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** `channel` null — вся лента фабрики; `last` 0 — вся лента целиком. */
export function useDiversity(channel: string | null, last = DIVERSITY_LAST) {
  return useQuery({
    queryKey: diversityKey(channel, last),
    queryFn: ({ signal }) => getDiversity(channel, last, signal),
    retry,
  });
}
