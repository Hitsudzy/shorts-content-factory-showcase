// Статистика и аналитик (CC-0020 фабрики, договор 0.23.0) — только чтение: каналы со сбором
// статистики (`GET /api/analytics`), окно YouTube «первые N дней» по роликам канала
// (`…/metrics`), дневные строки ролика (`…/videos/{id}`), сводка аналитика по стилю
// (`…/summary`, сохранённая — `…/summary/{day}`), «нужный футаж» (`…/footage-wanted`, упакованные
// батчи — только по явной кнопке: это медленно) и чтение Studio (`…/studio`). Ничего не пишет:
// ввод прочитанного в Studio (CC-0074, договор 0.25.0) — ./studioEntry.
// Отказы — `AnalyticsProblem {message, code, details}`, их разбирает `takeBatch` (./batchProblem).
import { useQuery } from '@tanstack/react-query';

import { BatchError, takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type AnalyticsOverview = Schemas['AnalyticsOverview'];
export type AnalyticsChannel = Schemas['AnalyticsChannel'];
export type ChannelMetrics = Schemas['ChannelMetrics'];
export type VideoMetrics = Schemas['VideoMetrics'];
export type MetricDaily = Schemas['MetricDaily'];
export type MetricWindow = Schemas['MetricWindow'];
export type StudioReadRow = Schemas['StudioReadRow'];
export type VideoSeries = Schemas['VideoSeries'];
export type AnalystSummary = Schemas['AnalystSummary'];
export type SummaryVideo = Schemas['SummaryVideo'];
export type SummaryGroup = Schemas['SummaryGroup'];
export type FootageWanted = Schemas['FootageWanted'];
export type FootageRow = Schemas['FootageRow'];
export type AnalyticsStudio = Schemas['AnalyticsStudio'];
export type StudioVideo = Schemas['StudioVideo'];
export type AnalyticsProblem = Schemas['AnalyticsProblem'];

/** Код отказа статистики, если ошибка — её отказ (`AnalyticsProblem`). */
export function analyticsCode(e: unknown): AnalyticsProblem['code'] | null {
  return e instanceof BatchError
    ? ((e.problem?.code as AnalyticsProblem['code'] | undefined) ?? null)
    : null;
}

/** Окно по умолчанию — первые 7 дней (`metrics_store.WINDOW_DAYS`, `--first-days`). */
export const FIRST_DAYS = 7;

const path = (channel: string) => ({ path: { channel } });

export async function getAnalytics(signal?: AbortSignal): Promise<AnalyticsOverview> {
  return takeBatch(await api.GET('/api/analytics', { signal }));
}

export async function getMetrics(
  channel: string,
  firstDays = FIRST_DAYS,
  signal?: AbortSignal,
): Promise<ChannelMetrics> {
  return takeBatch(
    await api.GET('/api/analytics/{channel}/metrics', {
      params: { ...path(channel), query: { first_days: firstDays } },
      signal,
    }),
  );
}

export async function getVideoSeries(
  channel: string,
  videoId: string,
  signal?: AbortSignal,
): Promise<VideoSeries> {
  return takeBatch(
    await api.GET('/api/analytics/{channel}/videos/{video_id}', {
      params: { path: { channel, video_id: videoId } },
      signal,
    }),
  );
}

/** Сводка: `day` — сохранённая за этот день; null — посчитанная сейчас (за вчера по Тихоокеанскому). */
export async function getSummary(
  channel: string,
  day: string | null,
  firstDays = FIRST_DAYS,
  signal?: AbortSignal,
): Promise<AnalystSummary> {
  if (day)
    return takeBatch(
      await api.GET('/api/analytics/{channel}/summary/{day}', {
        params: { path: { channel, day } },
        signal,
      }),
    );
  return takeBatch(
    await api.GET('/api/analytics/{channel}/summary', {
      params: { ...path(channel), query: { first_days: firstDays } },
      signal,
    }),
  );
}

export async function getFootageWanted(
  channel: string,
  packed: boolean,
  signal?: AbortSignal,
): Promise<FootageWanted> {
  return takeBatch(
    await api.GET('/api/analytics/{channel}/footage-wanted', {
      params: { ...path(channel), query: { packed } },
      signal,
    }),
  );
}

export async function getAnalyticsStudio(
  channel: string,
  signal?: AbortSignal,
): Promise<AnalyticsStudio> {
  return takeBatch(
    await api.GET('/api/analytics/{channel}/studio', { params: path(channel), signal }),
  );
}

export const analyticsKeys = {
  all: ['api', 'analytics'] as const,
  overview: ['api', 'analytics', 'overview'] as const,
  metrics: (c: string, n: number) => ['api', 'analytics', 'metrics', c, n] as const,
  video: (c: string, v: string) => ['api', 'analytics', 'video', c, v] as const,
  summary: (c: string, day: string | null, n: number) =>
    ['api', 'analytics', 'summary', c, day ?? '', n] as const,
  footage: (c: string, packed: boolean) => ['api', 'analytics', 'footage', c, packed] as const,
  studio: (c: string) => ['api', 'analytics', 'studio', c] as const,
};

/** Отказ 4xx (канала нет, хранилище не читается) повтором не лечится; сеть и 5xx — до трёх раз. */
const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/**
 * Статистику собирает фабрика раз в сутки, а чтение Studio — человек: опрашивать часто незачем.
 * Перечитываем раз в 5 минут и при возврате на вкладку.
 */
const slow = { refetchInterval: 300_000, refetchIntervalInBackground: false, retry } as const;

export function useAnalytics() {
  return useQuery({
    queryKey: analyticsKeys.overview,
    queryFn: ({ signal }) => getAnalytics(signal),
    ...slow,
  });
}

export function useMetrics(channel: string | null, firstDays = FIRST_DAYS) {
  return useQuery({
    queryKey: analyticsKeys.metrics(channel ?? '', firstDays),
    queryFn: ({ signal }) => getMetrics(channel!, firstDays, signal),
    enabled: !!channel,
    ...slow,
  });
}

export function useVideoSeries(channel: string | null, videoId: string | null) {
  return useQuery({
    queryKey: analyticsKeys.video(channel ?? '', videoId ?? ''),
    queryFn: ({ signal }) => getVideoSeries(channel!, videoId!, signal),
    enabled: !!channel && !!videoId,
    ...slow,
  });
}

export function useSummary(channel: string | null, day: string | null, firstDays = FIRST_DAYS) {
  return useQuery({
    queryKey: analyticsKeys.summary(channel ?? '', day, firstDays),
    queryFn: ({ signal }) => getSummary(channel!, day, firstDays, signal),
    enabled: !!channel,
    ...slow,
  });
}

/**
 * «Нужный футаж». С `packed` фабрика читает ещё и упакованные батчи (архив-том) — это долго,
 * поэтому такой запрос только по кнопке и без опроса.
 */
export function useFootageWanted(channel: string | null, packed = false) {
  return useQuery({
    queryKey: analyticsKeys.footage(channel ?? '', packed),
    queryFn: ({ signal }) => getFootageWanted(channel!, packed, signal),
    enabled: !!channel,
    retry,
    ...(packed ? { staleTime: Infinity } : { refetchInterval: 300_000 }),
    refetchIntervalInBackground: false,
  });
}

export function useAnalyticsStudio(channel: string | null) {
  return useQuery({
    queryKey: analyticsKeys.studio(channel ?? ''),
    queryFn: ({ signal }) => getAnalyticsStudio(channel!, signal),
    enabled: !!channel,
    ...slow,
  });
}
