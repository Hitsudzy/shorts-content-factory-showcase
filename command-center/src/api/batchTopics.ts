// Темы батча (CC-0091/0092): что нашёл трендхантер и что с каждой темой решили этапы дальше —
// `GET /api/batches/{channel}/{batch_id}/topics` (сводка) и `…/topics/{topic_id}` (одна тема:
// сцены, факт и источник, ссылки). Своего опроса нет: пока батч идёт, темы обновляются вместе
// с остальным экраном батча — `useTopicsRefresh` перечитывает их на каждом ответе опроса
// списка идущих батчей (CC-0092: «нового фонового опроса не заводить»). Отказы — `BatchError`
// (битый файл этапа — `stage_broken`).
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { batchPath } from './batches';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type BatchTopics = Schemas['BatchTopics'];
export type BatchTopic = Schemas['BatchTopic'];
export type TopicSummary = Schemas['TopicSummary'];
export type SkippedTopic = Schemas['SkippedTopic'];
export type TopicState = Schemas['TopicState'];
export type SearchQuota = Schemas['SearchQuota'];

function pathOf(batch: string) {
  const p = batchPath(batch);
  if (!p) throw new Error(`не путь батча: ${batch}`);
  return p;
}

export async function getTopics(batch: string, signal?: AbortSignal): Promise<BatchTopics> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/topics', {
      params: { path: pathOf(batch) },
      signal,
    }),
  );
}

export async function getTopic(
  batch: string,
  topicId: string,
  signal?: AbortSignal,
): Promise<BatchTopic> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/topics/{topic_id}', {
      params: { path: { ...pathOf(batch), topic_id: topicId } },
      signal,
    }),
  );
}

export const topicKeys = {
  /** Всё о темах батча: сводка и открытые темы — перечитываются вместе. */
  batch: (batch: string) => ['api', 'batches', 'topics', batch] as const,
  list: (batch: string) => ['api', 'batches', 'topics', batch, 'list'] as const,
  one: (batch: string, topicId: string) =>
    ['api', 'batches', 'topics', batch, 'one', topicId] as const,
};

/** Отказ фабрики 4xx (нет батча, битый файл этапа) — сразу: повтор ответа не изменит. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Сводка тем батча — без опроса (обновляет `useTopicsRefresh`). */
export function useBatchTopics(batch: string) {
  return useQuery({
    queryKey: topicKeys.list(batch),
    queryFn: ({ signal }) => getTopics(batch, signal),
    retry,
  });
}

/** Одна тема — только пока открыта (`enabled`), без опроса. */
export function useBatchTopic(batch: string, topicId: string | null) {
  return useQuery({
    queryKey: topicKeys.one(batch, topicId ?? ''),
    queryFn: ({ signal }) => getTopic(batch, topicId!, signal),
    enabled: !!topicId,
    retry,
  });
}

/**
 * Пока батч идёт (`going`), каждый новый ответ опроса экрана (`tick` — его `dataUpdatedAt`)
 * перечитывает темы батча: сводку и открытые темы. Первый ответ не считается — темы и так
 * читаются при показе.
 */
export function useTopicsRefresh(batch: string, going: boolean, tick: number | undefined) {
  const qc = useQueryClient();
  const last = useRef(tick);
  useEffect(() => {
    if (tick === last.current) return;
    last.current = tick;
    if (going) void qc.invalidateQueries({ queryKey: topicKeys.batch(batch) });
  }, [qc, batch, going, tick]);
}
