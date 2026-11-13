// «Разработка» (CC-0124, договор 0.66.0) — только чтение: задачи фабрики и центра из git
// (фронтматтер, архив, счёт чеклиста), одна задача (тело markdown, чеклист, связи, коммиты) и
// дорожные карты обоих `ROADMAP.md`. Статусы правят драйверы — центр ничего не пишет.
//
// Список берётся целиком (~930 задач, только фронтматтер) и фильтруется на месте: так счёт по
// фильтрам и варианты выбора видны сразу. Поиск по телу (`q`) — у API: тел в списке нет.
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { api, ApiError, unwrap, type Schemas } from './client';

export type DevTaskRow = Schemas['DevTaskRow'];
export type DevTask = Schemas['DevTask'];
export type DevTasks = Schemas['DevTasks'];
export type DevSource = Schemas['DevSource'];
export type DevRoadmap = Schemas['DevRoadmap'];
export type DevMilestone = Schemas['DevMilestone'];
export type DevSprint = Schemas['DevSprint'];
export type DevRelated = Schemas['DevRelated'];
export type DevCommit = Schemas['DevCommit'];

export const devKeys = {
  all: ['dev'] as const,
  tasks: (q: string) => ['dev', 'tasks', q] as const,
  task: (id: string) => ['dev', 'task', id] as const,
  roadmap: ['dev', 'roadmap'] as const,
};

/** Задачи читаются из git по sha веток — минуту держим ответ, без опроса. */
const STALE_MS = 60_000;

/** 404 «задачи нет» — ответ, а не сбой: не повторяем. */
const retry = (n: number, e: unknown) => !(e instanceof ApiError && e.status === 404) && n < 2;

export async function getDevTasks(q = '', signal?: AbortSignal): Promise<DevTasks> {
  return unwrap(await api.GET('/api/dev/tasks', { params: { query: q ? { q } : {} }, signal }));
}

export async function getDevTask(id: string, signal?: AbortSignal): Promise<DevTask> {
  return unwrap(
    await api.GET('/api/dev/tasks/{task_id}', { params: { path: { task_id: id } }, signal }),
  );
}

export async function getDevRoadmap(signal?: AbortSignal): Promise<DevRoadmap[]> {
  return unwrap(await api.GET('/api/dev/roadmap', { signal })).roadmaps;
}

/** Все задачи (без `q`) или найденные по `q` — пока ищется новое, видно прежнее. */
export function useDevTasks(q = '') {
  return useQuery({
    queryKey: devKeys.tasks(q),
    queryFn: ({ signal }) => getDevTasks(q, signal),
    staleTime: STALE_MS,
    placeholderData: keepPreviousData,
  });
}

export function useDevTask(id: string) {
  return useQuery({
    queryKey: devKeys.task(id),
    queryFn: ({ signal }) => getDevTask(id, signal),
    staleTime: STALE_MS,
    retry,
  });
}

export function useDevRoadmap() {
  return useQuery({
    queryKey: devKeys.roadmap,
    queryFn: ({ signal }) => getDevRoadmap(signal),
    staleTime: STALE_MS,
  });
}

/** Ответ «задачи нет» (404 `unknown_task`). */
export const isUnknownTask = (e: unknown) => e instanceof ApiError && e.status === 404;
