// Фоновые задачи банка мемов (CC-0075 API, договор 0.62.0): вырезка фона (`…/cutout/plan` →
// `…/cutout {confirm}`) и обрезка пустых полей (`…/trim/plan` → `…/trim {confirm}`). План ничего
// не пишет: что сделает фабрика и почему нет (`ok`/`why`, `available_reason` у вырезки); «да»
// запускает задачу в фоне и сразу отвечает `MemeJobStarted` — дальше центр опрашивает задачу
// (`…/jobs/{job_id}`, это и есть `status_url`) раз в `poll_s` секунд, пока `done`. Список задач
// банка (`…/jobs`) — чтобы перезагруженная страница нашла свою идущую задачу. Одна задача на
// банк (и на машину): пока она идёт, отметки и «применить» отвечают `job_active`.
import { useQuery } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';
import { writeProblemText } from './publishWrites';

export type MemeJob = Schemas['MemeJob'];
export type MemeJobs = Schemas['MemeJobs'];
export type MemeJobRef = Schemas['MemeJobRef'];
export type MemeJobStarted = Schemas['MemeJobStarted'];
export type MemeJobProgress = Schemas['MemeJobProgress'];
export type MemeJobError = Schemas['MemeJobError'];
export type MemeCutoutPlan = Schemas['MemeCutoutPlan'];
export type MemeTrimPlan = Schemas['MemeTrimPlan'];
export type MemeTrimRow = Schemas['MemeTrimRow'];
export type MemeIdReason = Schemas['MemeIdReason'];
export type MemeUrls = Schemas['MemeUrls'];

export type CutoutBody = { ids?: string[] | null; force?: boolean };
export type TrimBody = { id?: string | null };

export function planCutout(channel: string, body: CutoutBody, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/cutout/plan', {
        params: { path: { channel } },
        body: { ids: body.ids ?? null, force: !!body.force },
        signal,
      }),
    ),
  );
}

export function startCutout(channel: string, confirm: string, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/cutout', {
        params: { path: { channel } },
        body: { confirm },
        signal,
      }),
    ),
  );
}

export function planTrim(channel: string, body: TrimBody, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/trim/plan', {
        params: { path: { channel } },
        body: { id: body.id ?? null },
        signal,
      }),
    ),
  );
}

export function startTrim(channel: string, confirm: string, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/trim', {
        params: { path: { channel } },
        body: { confirm },
        signal,
      }),
    ),
  );
}

export async function getMemeJobs(channel: string, signal?: AbortSignal): Promise<MemeJobs> {
  return takeBatch(
    await api.GET('/api/memes/{channel}/jobs', {
      params: { path: { channel }, query: { limit: 20 } },
      signal,
    }),
  );
}

/** Одна задача — `status_url` из `MemeJobStarted` (`/api/memes/{channel}/jobs/{job_id}`). */
export async function getMemeJob(
  channel: string,
  jobId: string,
  signal?: AbortSignal,
): Promise<MemeJob> {
  return takeBatch(
    await api.GET('/api/memes/{channel}/jobs/{job_id}', {
      params: { path: { channel, job_id: jobId } },
      signal,
    }),
  );
}

export const memeJobKeys = {
  list: (channel: string) => ['api', 'memes', 'jobs', channel] as const,
  one: (channel: string, id: string) => ['api', 'memes', 'job', channel, id] as const,
};

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Через сколько спросить снова: `poll_s` задачи, пока она идёт (по умолчанию 3 с). */
export const pollMs = (job: { done?: boolean; poll_s?: number | null } | undefined) =>
  job && !job.done ? Math.max(0.05, job.poll_s ?? 3) * 1000 : false;

/** Задачи банка канала: идущая (`running`) и последние, новые сверху. */
export function useMemeJobs(channel: string) {
  return useQuery({
    queryKey: memeJobKeys.list(channel),
    queryFn: ({ signal }) => getMemeJobs(channel, signal),
    retry,
  });
}

/** Ход задачи: опрос раз в `poll_s`, пока не `done`; `null` — ничего не опрашивать. */
export function useMemeJob(channel: string, jobId: string | null) {
  return useQuery({
    queryKey: memeJobKeys.one(channel, jobId ?? ''),
    queryFn: ({ signal }) => getMemeJob(channel, jobId!, signal),
    enabled: !!jobId,
    retry,
    refetchInterval: (q) => pollMs(q.state.data),
    refetchIntervalInBackground: true,
  });
}

// ---- итоги задач (`result` — что вернула функция задачи; форма у каждого вида своя)

type Row = { id: string; urls?: MemeUrls | null };

export type CutoutResult = {
  made: (Row & { file?: string; bbox_px?: number[] | null; coverage?: number | null })[];
  refused: (Row & { reason: string; en?: string | null })[];
  unchanged: string[];
  missing: string[];
  outside_bank: MemeIdReason[];
  written?: boolean;
};

export type TrimResult = {
  trim: MemeTrimRow[];
  left: MemeIdReason[];
  under: MemeTrimRow[];
  changed: string[];
  originals?: string | null;
  embedding?: {
    done?: boolean;
    line?: string | null;
    error?: string | null;
    en?: string | null;
    fatal?: boolean;
  } | null;
};

const arr = <T>(v: unknown): T[] => (Array.isArray(v) ? (v as T[]) : []);

/** `result` вырезки — списки всегда массивы (чужое поле не роняет экран). */
export function cutoutResult(r: Record<string, unknown> | null | undefined): CutoutResult {
  return {
    made: arr(r?.made),
    refused: arr(r?.refused),
    unchanged: arr(r?.unchanged),
    missing: arr(r?.missing),
    outside_bank: arr(r?.outside_bank),
    written: typeof r?.written === 'boolean' ? r.written : undefined,
  };
}

/** `result` обрезки полей. */
export function trimResult(r: Record<string, unknown> | null | undefined): TrimResult {
  const e = r?.embedding;
  return {
    trim: arr(r?.trim),
    left: arr(r?.left),
    under: arr(r?.under),
    changed: arr(r?.changed),
    originals: typeof r?.originals === 'string' ? r.originals : null,
    embedding: e && typeof e === 'object' ? (e as TrimResult['embedding']) : null,
  };
}

// ---- отказы словами (строка фабрики показывается под заголовком как есть)

const MEME_JOB_TEXT: Record<string, string> = {
  job_active: 'На банке идёт задача — дождитесь её конца',
  job_running: 'На машине уже идёт задача — одна задача на машину',
  cutout_unavailable: 'Вырезка на этой машине недоступна',
  check_changed: 'Банк изменился с плана — посмотрите план заново',
  confirm_unknown: 'Подтверждение не найдено — посмотрите план заново',
  confirm_expired: 'Подтверждение устарело — посмотрите план заново',
  confirm_mismatch: 'Подтверждение от другого плана — посмотрите план заново',
  spawn_failed: 'Фабрика не смогла запустить задачу',
  launch_failed: 'Фабрика не смогла запустить задачу',
  busy: 'Идёт другая запись банка мемов — подождите и нажмите ещё раз',
  not_cutout: 'У мема нет отметки «можно вырезать»',
  bad_ids: 'Выберите хотя бы один мем',
  unknown_id: 'Такого мема в банке нет',
  unknown_channel: 'Такого канала на фабрике нет',
  unknown_job: 'Такой задачи у банка нет',
  factory_broken: 'Стол мемов ответил ошибкой — посмотрите банк, прежде чем повторять',
  // CC-0133: добавление картинки и GIF, лист кадров (заголовок отказа; строка фабрики — под ним)
  bad_url: 'Нужна ссылка http(s)://…',
  bad_suffix: 'Такой файл фабрика не берёт',
  no_source_url: 'Нужна ссылка на страницу, где файл найден',
  bad_span: 'Отрезок задан неверно',
  too_many_frames: 'Слишком много кадров для одного листа',
  bad_entry: 'Мем описан не полностью',
  duplicate_id: 'Мем не добавлен',
  file_exists: 'Такой файл уже лежит в банке',
  video_failed: 'Видео не получилось взять',
  download_failed: 'Файл не скачался',
  bad_image: 'Это не картинка',
  blank_image: 'Картинка залита одним тоном',
  over_ceiling: 'Картинка слишком мелкая',
  media_failed: 'Файл не обработался',
  embed_failed: 'Признаки для поиска похожих мемов не пересчитались',
  bad_params: 'Поля заданы неверно',
  outside_bank: 'Писать можно только внутри банка',
};

export const memeJobProblemText = (code: string | null | undefined): string =>
  (code && MEME_JOB_TEXT[code]) || writeProblemText(code);
