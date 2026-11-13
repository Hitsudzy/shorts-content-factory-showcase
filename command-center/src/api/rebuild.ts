// Пересборка роликов готового батча (CC-0048/0049 фабрики, договор 0.17.0). Чтение: режимы из
// плана канала (`…/rebuild/modes`) и секунды ролика → блоки раскадровки (`…/videos/{slug}/
// blocks?at=12,18,24` — `blocks_at` как есть: `near` у склейки, `note` там, где исключить
// нельзя). Запись — в два вызова, как у остальных действий (./batchActions): план
// (`…/rebuild/plan {videos, mode, notes}` → проверка фабрики + одноразовый токен) и «да»
// (`…/rebuild {confirm}` — больше ничего: ролики, режим и замечания — токена). Исключения
// кадров — номерами блоков и только в режиме, который их берёт (`reedit`).
import { useQuery } from '@tanstack/react-query';

import { PLAN_TIMEOUT_MS, within } from './batchActions';
import { batchPath } from './batches';
import { takeBatch } from './batchProblem';
import { api, ApiError, type Schemas } from './client';

export type RebuildModes = Schemas['RebuildModes'];
export type RebuildMode = Schemas['RebuildMode'];
export type VideoBlocks = Schemas['VideoBlocks'];
export type BlockMoment = Schemas['BlockMoment'];
export type RebuildPlanIn = Schemas['RebuildPlanIn'];
export type RebuildPlan = Schemas['RebuildPlan'];
export type RebuildResult = Schemas['RebuildResult'];

/** Режимы, где монтаж берёт исключения кадров (CF-0668): остальные пишут сценарий заново. */
export const EXCLUDE_MODES = new Set(['reedit']);
/** Сколько секунд фабрика переводит за раз (`at`: 1–20 чисел). */
export const MAX_SECONDS = 20;

function pathOf(batch: string) {
  const p = batchPath(batch);
  if (!p) throw new Error(`не путь батча: ${batch}`);
  return p;
}

export async function getRebuildModes(batch: string, signal?: AbortSignal) {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/rebuild/modes', {
      params: { path: pathOf(batch) },
      signal,
    }),
  );
}

export async function getBlocks(batch: string, slug: string, at: number[], signal?: AbortSignal) {
  return takeBatch(
    await api.GET('/api/batches/{channel}/{batch_id}/videos/{slug}/blocks', {
      params: { path: { ...pathOf(batch), slug }, query: { at: at.join(',') } },
      signal,
    }),
  );
}

export function planRebuild(batch: string, body: RebuildPlanIn, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/rebuild/plan', {
        params: { path: pathOf(batch) },
        body,
        signal,
      }),
    ),
  );
}

export function startRebuild(batch: string, confirm: string, ms = PLAN_TIMEOUT_MS) {
  return within(ms, async (signal) =>
    takeBatch(
      await api.POST('/api/batches/{channel}/{batch_id}/rebuild', {
        params: { path: pathOf(batch) },
        body: { confirm },
        signal,
      }),
    ),
  );
}

export const rebuildKeys = {
  modes: (batch: string) => ['api', 'rebuild', 'modes', batch] as const,
  blocks: (batch: string, slug: string, at: string) =>
    ['api', 'rebuild', 'blocks', batch, slug, at] as const,
};

const retry = (n: number, e: unknown) =>
  !(e instanceof ApiError && e.status >= 400 && e.status < 500) && n < 3;

/** Режимы пересборки батча — когда открыта подготовка пересборки. */
export function useRebuildModes(batch: string, enabled: boolean) {
  return useQuery({
    queryKey: rebuildKeys.modes(batch),
    queryFn: ({ signal }) => getRebuildModes(batch, signal),
    enabled,
    staleTime: 5 * 60_000,
    retry,
  });
}

/** Что на экране в эти секунды ролика (`null` — ещё не спрашивали). */
export function useBlocks(batch: string, slug: string, at: number[] | null) {
  return useQuery({
    queryKey: rebuildKeys.blocks(batch, slug, at?.join(',') ?? ''),
    queryFn: ({ signal }) => getBlocks(batch, slug, at!, signal),
    enabled: !!at?.length,
    staleTime: 5 * 60_000,
    retry,
  });
}

/**
 * «12 18 24», «12, 18, 24», «12,18,24», «0:12 1:05», «12с» → секунды. Дробь — точкой или
 * запятой с одной цифрой после неё («12.5», «12,5»); список — пробелами, «;» или запятыми.
 */
export function parseSeconds(text: string): { at: number[] } | { error: string } {
  const parts = text
    .replace(/,(?!\d(?!\d))|;/g, ' ')
    .split(/\s+/)
    .map((x) => x.trim())
    .filter(Boolean);
  if (!parts.length) return { error: 'Напишите секунды ролика, например «12 18 24».' };
  if (parts.length > MAX_SECONDS) return { error: `Не больше ${MAX_SECONDS} секунд за раз.` };
  const at: number[] = [];
  for (const p of parts) {
    const s = p.replace(/\s*(с|сек|s)\.?$/i, '').replace(',', '.');
    const mm = s.match(/^(\d+):([0-5]?\d(?:\.\d+)?)$/);
    const v = mm ? Number(mm[1]) * 60 + Number(mm[2]) : /^\d+(\.\d+)?$/.test(s) ? Number(s) : NaN;
    if (!Number.isFinite(v))
      return { error: `«${p}» — не секунды. Пишите так: 12 18 24 или 1:05.` };
    if (!at.includes(v)) at.push(v);
  }
  return { at };
}

/** Тело плана: замечание ко всей пересборке и по ролику — исключения (только `reedit`). */
export function planBody({
  slug,
  mode,
  text,
  exclude,
  seconds,
}: {
  slug: string;
  mode: string;
  text: string;
  exclude: string[];
  seconds: number[];
}): RebuildPlanIn {
  const canExclude = EXCLUDE_MODES.has(mode);
  const ex = canExclude ? exclude : [];
  const note = seconds.length
    ? `замечания на секундах ${seconds.map((s) => String(s).replace('.', ',')).join(', ')}`
    : null;
  const per = ex.length || note ? { [slug]: { exclude: ex, note } } : null;
  return {
    videos: [slug],
    mode,
    notes: { text: text.trim() || null, videos: per },
  };
}
