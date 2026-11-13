// Оценка ролика (CC-0125; фабрика CF-0434, договор 0.55.0+): у ролика — кратко `Video.score`
// (тир, баллы, порог, прошёл, на какой стадии упал ниже порога), у списка батча — модель счёта
// `BatchVideos.score_model` (тиры лучший первым, ниже последнего — `below`, «F»); весь разбор —
// `GET /api/batches/{c}/{b}/videos/{slug}/score` (`VideoScore`: стадии, находки, статус цен).
// Цвета тиров не зашиты: место тира в списке модели → ступень 1…5, ниже — F (токены темы
// `--tier-1…5`, `--tier-f` в index.css). Только чтение.
import { useQuery } from '@tanstack/react-query';

import { takeBatch } from './batchProblem';
import { batchPath } from './batches';
import { api, ApiError, type Schemas } from './client';
import { videoKeys } from './videos';

export type VideoScore = Schemas['VideoScore'];
export type VideoScoreShort = Schemas['VideoScoreShort'];
export type ScoreModel = Schemas['ScoreModel'];
export type ScoreTier = Schemas['ScoreTier'];
export type VideoScoreStage = Schemas['VideoScoreStage'];
export type VideoScoreFinding = Schemas['VideoScoreFinding'];

/** Ступень цвета тира: 1 — лучший … 5 — нижний проходной, `f` — ниже всех, null — неизвестен. */
export type TierLevel = 1 | 2 | 3 | 4 | 5 | 'f' | null;

/**
 * Ступень тира по модели: место в списке (лучший первым), растянутое на пять ступеней — так у
 * модели из трёх тиров нижний тоже «оранжевый», а не «зелёный». Ниже последнего — F.
 */
export function tierLevel(
  tier: string | null | undefined,
  tiers: readonly ScoreTier[] | null | undefined,
  below = 'F',
): TierLevel {
  if (!tier) return null;
  if (tier === below || tier === 'F') return 'f';
  const list = tiers ?? [];
  const i = list.findIndex((t) => t.name === tier);
  if (i < 0) return null;
  if (list.length <= 1) return 1;
  return (1 + Math.round((i * 4) / (list.length - 1))) as 1 | 2 | 3 | 4 | 5;
}

/** Тир по баллам, если API его не назвал: первый, чей порог не выше баллов, иначе — `below`. */
export function tierOf(
  score: number | null | undefined,
  tiers: readonly ScoreTier[] | null | undefined,
  below = 'F',
): string | null {
  if (typeof score !== 'number') return null;
  return (tiers ?? []).find((t) => score >= t.floor)?.name ?? below;
}

/** «A · 86»; без баллов — только буква. */
export function scoreLabel(s: Pick<VideoScoreShort, 'tier' | 'score'>): string {
  const pts = typeof s.score === 'number' ? fmtPoints(s.score) : null;
  return [s.tier ?? '?', pts].filter(Boolean).join(' · ');
}

/** Баллы без лишних нулей: 86, 85,5. */
export function fmtPoints(n: number): string {
  return Number.isInteger(n) ? String(n) : n.toFixed(1).replace('.', ',');
}

export const scoreKey = (batch: string, slug: string) =>
  [...videoKeys.all, 'score', batch, slug] as const;

export async function getVideoScore(
  batch: string,
  slug: string,
  signal?: AbortSignal,
): Promise<VideoScore> {
  const p = batchPath(batch);
  if (!p) throw new Error(`не путь батча: ${batch}`);
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/videos/{slug}/score', {
      params: { path: { ...p, slug } },
      signal,
    }),
  );
}

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Разбор оценки — только когда окно открыто (`enabled`); свежий пять минут. */
export function useVideoScore(batch: string, slug: string, enabled: boolean) {
  return useQuery({
    queryKey: scoreKey(batch, slug),
    queryFn: ({ signal }) => getVideoScore(batch, slug, signal),
    enabled,
    staleTime: 5 * 60_000,
    retry,
  });
}
