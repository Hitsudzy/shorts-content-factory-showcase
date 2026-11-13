// Новые мемы и лист кадров (CC-0133 → CC-0076 API, договор 0.62.0): «добавить картинку» по
// ссылке, «добавить GIF из видео» (отрезок по секундам), «контактный лист кадров» видео и
// «пересчитать признаки для поиска похожих мемов». Каждое — два шага, как вырезка фона: план
// фабрики без сети и без записи (что скачается, куда ляжет, худшее время `max_seconds_word`) →
// «да» запускает фоновую задачу (`MemeJobStarted`), её ход и итог — блок задачи на столе
// (`./memeJobs.ts`). Ссылки — только http(s): центр проверяет это сам до плана (`bad_url`), но
// решает API. Готовый лист кадров отдаёт `GET …/sheets/{name}` (`sheet_url` итога).
import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { takeBatch } from './batchProblem';
import { api, type Schemas } from './client';
import type { MemeUrls } from './memeJobs';

export type MemeAddImagePlan = Schemas['MemeAddImagePlan'];
export type MemeAddGifPlan = Schemas['MemeAddGifPlan'];
export type MemeSheetPlan = Schemas['MemeSheetPlan'];
export type MemeEmbedPlan = Schemas['MemeEmbedPlan'];
export type AddImageBody = Schemas['MemeAddImagePlanIn'];
export type AddGifBody = Schemas['MemeAddGifPlanIn'];
export type SheetBody = Schemas['MemeSheetPlanIn'];

type Path =
  | '/api/memes/{channel}/add-image'
  | '/api/memes/{channel}/add-gif'
  | '/api/memes/{channel}/sheet'
  | '/api/memes/{channel}/embed';

function confirmOf(path: Path) {
  return (channel: string, confirm: string, ms = PLAN_TIMEOUT_MS) =>
    within(ms, async (signal) =>
      takeBatch(await api.POST(path, { params: { path: { channel } }, body: { confirm }, signal })),
    );
}

export function planAddImage(channel: string, body: AddImageBody, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/add-image/plan', {
        params: { path: { channel } },
        body,
        signal,
      }),
    ),
  );
}

export function planAddGif(channel: string, body: AddGifBody, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/add-gif/plan', {
        params: { path: { channel } },
        body,
        signal,
      }),
    ),
  );
}

export function planSheet(channel: string, body: SheetBody, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/sheet/plan', {
        params: { path: { channel } },
        body,
        signal,
      }),
    ),
  );
}

export function planEmbed(channel: string, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/memes/{channel}/embed/plan', {
        params: { path: { channel } },
        signal,
      }),
    ),
  );
}

export const startAddImage = confirmOf('/api/memes/{channel}/add-image');
export const startAddGif = confirmOf('/api/memes/{channel}/add-gif');
export const startSheet = confirmOf('/api/memes/{channel}/sheet');
export const startEmbed = confirmOf('/api/memes/{channel}/embed');

// ---- проверки полей до плана (решает API; здесь — подсказка словами, чтобы не звать фабрику зря)

/** Адрес http(s) с хостом и без пробелов — как `_http` центра. */
export function isHttpUrl(value: string): boolean {
  const v = value.trim();
  if (!v || /\s/.test(v)) return false;
  try {
    const u = new URL(v);
    return (u.protocol === 'http:' || u.protocol === 'https:') && !!u.hostname;
  } catch {
    return false;
  }
}

/** Id нового мема — как `ID_RE` банка: строчная латиница, цифры, дефис, подчёркивание. */
export const MEME_ID_RE = /^[a-z0-9][a-z0-9_-]*$/;

/** «a, b ,c» → ['a', 'b', 'c'] (пустые выкинуты), как `_tags_of` фабрики. */
export const tagsOf = (s: string) =>
  s
    .split(',')
    .map((t) => t.trim())
    .filter(Boolean);

/** Секунды из поля: «12,5» и «12.5»; пусто или не число — `null`. */
export function seconds(s: string): number | null {
  const v = s.trim().replace(',', '.');
  if (!v) return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
}

/** Сколько кадров в листе — как `sheet_frames` фабрики; конец не задан — `null`. */
export function sheetFrames(start: number, end: number | null, every: number): number | null {
  if (end === null || !(every > 0)) return null;
  return Math.max(1, Math.ceil((end - start) / every - 1e-9));
}

/** Столбцов в листе кадров у фабрики (`SHEET_SCRIPT`: cols=10). */
export const SHEET_COLS = 10;
/** Больше кадров в одном листе фабрика не делает (`too_many_frames`). */
export const MAX_SHEET_FRAMES = 300;

// ---- итоги задач

export type EmbeddingOutcome = {
  done?: boolean;
  line?: string | null;
  error?: string | null;
  en?: string | null;
  fatal?: boolean;
} | null;

export type AddedEntry = {
  id: string;
  file?: string;
  description?: string;
  tags?: string[];
  review?: string;
  source_url?: string;
  clip?: { start_s?: number; end_s?: number } | null;
  urls?: MemeUrls | null;
};

export type AddResult = {
  entry: AddedEntry | null;
  file: string | null;
  size: number[] | null;
  /** Пометка о срезе пустой полосы: у фабрики по-английски; русская — `trim_note_ru`. */
  trimNote: string | null;
  trimNoteRu: string | null;
  durationS: number | null;
  cutsInside: number[];
  embedding: EmbeddingOutcome;
};

export type SheetResult = {
  sheet: string | null;
  sheetUrl: string | null;
  sceneCuts: number[];
};

const nums = (v: unknown): number[] =>
  Array.isArray(v) ? v.filter((x): x is number => typeof x === 'number') : [];
const str = (v: unknown) => (typeof v === 'string' && v ? v : null);

/** `result` добавления картинки или GIF; чужое поле не роняет экран. */
export function addResult(r: Record<string, unknown> | null | undefined): AddResult {
  const e = r?.entry;
  const emb = r?.embedding;
  return {
    entry:
      e && typeof e === 'object' && typeof (e as AddedEntry).id === 'string'
        ? (e as AddedEntry)
        : null,
    file: str(r?.file),
    size: nums(r?.size).length >= 2 ? nums(r?.size) : null,
    trimNote: str(r?.trim_note),
    trimNoteRu: str(r?.trim_note_ru),
    durationS: typeof r?.duration_s === 'number' ? r.duration_s : null,
    cutsInside: nums(r?.cuts_inside),
    embedding: emb && typeof emb === 'object' ? (emb as EmbeddingOutcome) : null,
  };
}

/** `result` листа кадров. */
export function sheetResult(r: Record<string, unknown> | null | undefined): SheetResult {
  return {
    sheet: str(r?.sheet),
    sheetUrl: str(r?.sheet_url),
    sceneCuts: nums(r?.scene_cuts),
  };
}

/** Параметры листа из `job.params` (что ушло фабрике): видео, начало, конец, шаг. */
export function sheetParams(p: Record<string, unknown> | null | undefined) {
  const n = (v: unknown, d: number | null) => (typeof v === 'number' ? v : d);
  return {
    video: str(p?.video),
    start: n(p?.start, 0) ?? 0,
    end: n(p?.end, null),
    every: n(p?.every, 2) ?? 2,
  };
}
