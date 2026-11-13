// Ролики батча (CC-0012/0057 фабрики, договор 0.17.0): список роликов из `05-video-editor.json`
// с пересборками рядом, mp4 (HTTP Range), превью (кадр монтажа `frame` или лист судьи `sheet`),
// разобранная карточка публикации и что журнал приёмки знает о ролике. Только чтение: вердикт
// (`POST …/acceptance`) — CC-0062. Адреса mp4/превью/карточки API отдаёт сам (`url`, уже с
// базовым путём `<base>api`) — экран их не собирает. Отказы — `BatchError` (./batchProblem).
// Вердикт (CC-0062): `POST …/acceptance` только по нажатию — `useAccept`, после ответа список
// роликов перечитывается.
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { takeBatch } from './batchProblem';
import { batchPath, isRebuild, type BatchRun } from './batches';
import { api, ApiError, type Schemas } from './client';

export type BatchVideos = Schemas['BatchVideos'];
export type Video = Schemas['Video'];
export type VideoPreview = Schemas['Preview'];
export type VideoAcceptance = Schemas['VideoAcceptance'];
export type VideoCard = Schemas['Card'];
export type RebuildBatch = Schemas['RebuildBatch'];
export type ReasonCode = Schemas['ReasonCode'];
/** Отказ после монтажа (CC-0116): ролик собран, но фабрика его отклонила — вердикта нет. */
export type VideoRefusal = Schemas['VideoRefusal'];
/** Батч, под которым вердикт ждёт в очереди (ответ приёмки, CC-0062). */
export type BlockingBatch = Schemas['BlockingBatch'];
export type AcceptIn = Schemas['AcceptIn'];
export type AcceptResult = Schemas['AcceptResult'];
export type Verdict = AcceptIn['verdict'];

/**
 * Имя ролика для человека: название карточки, без него — имя ролика словами
 * («jwst-little-red-dots» → «Jwst little red dots»), а не латиница через дефисы.
 */
export function readableSlug(slug: string): string {
  const t = slug.replace(/[-_]+/g, ' ').trim();
  return t ? t[0]!.toUpperCase() + t.slice(1) : slug;
}
/** Название без хвоста хэштегов: «… #shorts» → «…» — для показа (CC-0128, как `title_clean` CF-0750). */
export const withoutHashtags = (t: string) => t.replace(/(?:\s+#[^\s#]+)+\s*$/u, '').trim();

/** Название ролика для показа: из карточки без « #shorts», без него — имя словами. */
export const videoTitle = (v: Pick<Video, 'slug' | 'card'>) =>
  (v.card.title && withoutHashtags(v.card.title)) || readableSlug(v.slug);

/** Код причины отказа — ключ словаря фабрики (CF-0319): латиница, цифры, подчёркивание. */
export const REASON_CODE = /^[a-z][a-z0-9_]*$/;

/** Заготовка слов вердикта: фабрика пишет вердикт только под именем ролика (CF-0328). */
export const wordsPrefill = (slug: string) => `${slug} — `;

/** Кадров в секунду, если ни карточка, ни план ролика их не сказали (монтаж фабрики — 30). */
export const DEFAULT_FPS = 30;

function pathOf(batch: string) {
  const p = batchPath(batch);
  if (!p) throw new Error(`не путь батча: ${batch}`);
  return p;
}

export async function getVideos(batch: string, signal?: AbortSignal): Promise<BatchVideos> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/videos', {
      params: { path: pathOf(batch) },
      signal,
    }),
  );
}

export async function getVideoCard(
  batch: string,
  slug: string,
  signal?: AbortSignal,
): Promise<VideoCard> {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/videos/{slug}/card', {
      params: { path: { ...pathOf(batch), slug } },
      signal,
    }),
  );
}

/** Вердикт пользователя по ролику: одна запись журнала приёмки (или очередь под батчем). */
export async function postAcceptance(
  batch: string,
  slug: string,
  body: AcceptIn,
): Promise<AcceptResult> {
  return takeBatch(
    await api.POST('/api/batches/{channel}/{batch_id}/videos/{slug}/acceptance', {
      params: { path: { ...pathOf(batch), slug } },
      body,
    }),
  );
}

export const videoKeys = {
  all: ['api', 'videos'] as const,
  list: (batch: string) => ['api', 'videos', 'list', batch] as const,
  card: (batch: string, slug: string) => ['api', 'videos', 'card', batch, slug] as const,
};

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Ролики батча: перечитываются раз в минуту (вердикт из терминала, очередь под батчем). */
export function useVideos(batch: string | null) {
  return useQuery({
    queryKey: videoKeys.list(batch ?? ''),
    queryFn: ({ signal }) => getVideos(batch!, signal),
    enabled: !!batch,
    refetchInterval: 60_000,
    refetchIntervalInBackground: false,
    retry,
  });
}

/**
 * Вердикт по ролику `slug` батча `batch` (у пересборки — её батч). После любого ответа —
 * и согласия, и отказа (список мог отстать: вердикт дали из терминала) — списки роликов
 * перечитываются: и этого батча, и источника, где пересборка видна рядом, и главная.
 */
export function useAccept(batch: string, slug: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: AcceptIn) => postAcceptance(batch, slug, body),
    onSettled: () => qc.invalidateQueries({ queryKey: [...videoKeys.all, 'list'] }),
  });
}

/** Карточка публикации ролика — по открытию ролика; нет карточки — не спрашиваем. */
export function useVideoCard(batch: string | null, slug: string | null, enabled = true) {
  return useQuery({
    queryKey: videoKeys.card(batch ?? '', slug ?? ''),
    queryFn: ({ signal }) => getVideoCard(batch!, slug!, signal),
    enabled: enabled && !!batch && !!slug,
    retry,
  });
}

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) && v > 0 ? v : null);

/** Обложка ролика: кадр монтажа как есть, или первая плитка листа судьи (сетка `grid`). */
export type Poster =
  | { kind: 'frame'; url: string }
  | { kind: 'sheet'; url: string; columns: number; rows: number }
  | { kind: 'none'; reason: string | null };

export function posterOf(p: VideoPreview | null | undefined): Poster {
  if (!p?.available || !p.url) return { kind: 'none', reason: p?.reason ?? null };
  if (p.kind === 'sheet') {
    const columns = num(p.grid?.columns) ?? 3;
    const rows = num(p.grid?.rows) ?? 2;
    return { kind: 'sheet', url: p.url, columns, rows };
  }
  return { kind: 'frame', url: p.url };
}

/**
 * Кадров в секунду ролика: из карточки (`mark.fps`) или из того, что о ролике знает список,
 * если фабрика их там скажет; иначе 30 (договор 0.17.0 fps не отдаёт).
 */
export function fpsOf(card?: VideoCard | null, video?: Video | null): number {
  const fromMark = num(card?.mark?.fps);
  const fromVideo = num((video as Record<string, unknown> | null | undefined)?.fps);
  return fromMark ?? fromVideo ?? DEFAULT_FPS;
}

/** Ролик и его версии-пересборки (`rebuilt_in` → `rebuilds[].videos`), старые сначала. */
export type VideoGroup = {
  video: Video;
  versions: { batch: string; batch_id: string; video: Video }[];
};

export function groupsOf(list: BatchVideos): VideoGroup[] {
  return list.videos.map((video) => ({
    video,
    versions: list.rebuilds.flatMap((rb) => {
      if (!video.rebuilt_in.includes(rb.batch)) return [];
      const v =
        rb.videos.find((x) => x.slug === video.slug) ??
        (video.script_id ? rb.videos.find((x) => x.script_id === video.script_id) : undefined);
      return v ? [{ batch: rb.batch, batch_id: rb.batch_id, video: v }] : [];
    }),
  }));
}

/** Батч по умолчанию — последний прогон истории (не пересборка: она видна рядом с источником). */
export function latestBatchOf(runs: BatchRun[]): string | null | undefined {
  return (runs.find((r) => r.batch && !isRebuild(r.batch)) ?? runs.find((r) => r.batch))?.batch;
}

/**
 * Ролик ждёт решения: журнал читается и вердикта нет (ни в журнале, ни в очереди). Отказанный
 * после монтажа (`refused`, CC-0116) решения не ждёт: вердикт ему не дают (409 `video_refused`).
 */
export const awaitsVerdict = (v: Video) =>
  !v.refused && !!v.acceptance && !v.acceptance.state_error && !v.acceptance.verdict;

/** Пересборка, которой заменён ролик: её батч и её версия ролика (с её вердиктом). */
export type Replacement = { batch: string; batch_id: string; video: Video };

/**
 * Ролик заменён пересборкой (CC-0088): у него самого вердикта нет, а его версию в пересборке
 * (`rebuilt_in` → `rebuilds[].videos`, та же тема — имя ролика или сценарий, ./groupsOf) вы
 * приняли. Так бывает, когда отказ первой версии оформили пересборкой, а не строкой журнала:
 * спрашивать о ней снова — повтор. Так же и с роликом, отказанным после монтажа (`refused`,
 * CC-0116): его пересборку приняли — он заменён, а не отказан. Принятых пересборок несколько — последняя. Это не логика
 * фабрики поверх фабрики: и пересборки ролика, и вердикт каждой версии отдаёт сам API.
 */
export function replacementOf(group: VideoGroup): Replacement | null {
  // Отказанный после монтажа (CC-0116), чью пересборку вы приняли, — тоже заменён ею.
  if (!group.video.refused && !awaitsVerdict(group.video)) return null;
  const hit = group.versions.findLast(
    (v) => !v.video.acceptance?.state_error && v.video.acceptance?.verdict === 'accepted',
  );
  return hit ? { batch: hit.batch, batch_id: hit.batch_id, video: hit.video } : null;
}

/** Ролики батча, заменённые принятой пересборкой: имя ролика → пересборка. */
export function replacementsOf(list: BatchVideos): Map<string, Replacement> {
  const out = new Map<string, Replacement>();
  for (const g of groupsOf(list)) {
    const r = replacementOf(g);
    if (r) out.set(g.video.slug, r);
  }
  return out;
}

/** Ролики батча, что ждут вашего решения: без вердикта и не заменённые принятой пересборкой. */
export function waitingOf(list: BatchVideos): Video[] {
  const replaced = replacementsOf(list);
  return list.videos.filter((v) => awaitsVerdict(v) && !replaced.has(v.slug));
}
