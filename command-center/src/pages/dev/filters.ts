// Фильтры «Разработки» в адресе (CC-0124): `?q=&project=&milestone=&status=&type=&repo=&sort=`
// — ссылку можно переслать, перезагрузка их восстанавливает. Списки — через запятую, точное
// совпадение (как у API). Поиск по телу (`q`) делает API; остальное фильтруется на месте.
import type { DevTaskRow } from '@/api/dev';

import { statusRank } from './words';

export const SORTS = ['status', 'id', 'new', 'closed'] as const;
export type Sort = (typeof SORTS)[number];

export const SORT_LABEL: Record<Sort, string> = {
  status: 'по статусу',
  id: 'по номеру',
  new: 'сначала новые',
  closed: 'недавно закрытые',
};

export const DEFAULT_SORT: Sort = 'status';

export type ListKey = 'project' | 'milestone' | 'status' | 'type' | 'repo';
export const LIST_KEYS: readonly ListKey[] = ['project', 'milestone', 'status', 'type', 'repo'];

export type DevFilters = {
  q: string;
  sort: Sort;
} & Record<ListKey, string[]>;

export const EMPTY_FILTERS: DevFilters = {
  q: '',
  sort: DEFAULT_SORT,
  project: [],
  milestone: [],
  status: [],
  type: [],
  repo: [],
};

/** Значение «без вехи» / «без репо» в адресе: у задачи поле пустое. */
export const NONE = '-';

const split = (v: string | null) => [
  ...new Set(
    (v ?? '')
      .split(',')
      .map((x) => x.trim())
      .filter(Boolean),
  ),
];

export function parseFilters(p: URLSearchParams): DevFilters {
  const sort = p.get('sort');
  const f: DevFilters = {
    ...EMPTY_FILTERS,
    q: (p.get('q') ?? '').trim(),
    sort: (SORTS as readonly string[]).includes(sort ?? '') ? (sort as Sort) : DEFAULT_SORT,
  };
  for (const k of LIST_KEYS) f[k] = split(p.get(k));
  return f;
}

/**
 * Фильтры → параметры адреса: пустое и сортировка по умолчанию не пишутся, порядок ключей
 * постоянный. `keep` — посторонние параметры адреса (например `view`), они сохраняются.
 */
export function filtersToParams(f: DevFilters, keep?: URLSearchParams): URLSearchParams {
  const out = new URLSearchParams();
  if (keep)
    for (const [k, v] of keep)
      if (k !== 'q' && k !== 'sort' && !(LIST_KEYS as readonly string[]).includes(k)) out.set(k, v);
  if (f.q.trim()) out.set('q', f.q.trim());
  for (const k of LIST_KEYS) if (f[k].length) out.set(k, f[k].join(','));
  if (f.sort !== DEFAULT_SORT) out.set('sort', f.sort);
  return out;
}

/** Задан ли хоть один фильтр (сортировка не в счёт). */
export const hasFilters = (f: DevFilters) => !!f.q || LIST_KEYS.some((k) => f[k].length > 0);

/** Добавить или убрать значение списка. */
export function toggle(f: DevFilters, key: ListKey, value: string): DevFilters {
  const has = f[key].includes(value);
  return { ...f, [key]: has ? f[key].filter((v) => v !== value) : [...f[key], value] };
}

const fieldOf = (t: DevTaskRow, k: ListKey): string => {
  const v = k === 'project' ? t.project : t[k];
  return v ? v : NONE;
};

/** Фильтры списка — на месте (поиск `q` уже сделал API). */
export function applyFilters(rows: readonly DevTaskRow[], f: DevFilters): DevTaskRow[] {
  const keys = LIST_KEYS.filter((k) => f[k].length);
  if (!keys.length) return [...rows];
  return rows.filter((t) => keys.every((k) => f[k].includes(fieldOf(t, k))));
}

const num = (id: string) => Number(/\d+/.exec(id)?.[0] ?? 0);
const byId = (a: DevTaskRow, b: DevTaskRow) =>
  a.project === b.project
    ? num(a.id) - num(b.id) || a.id.localeCompare(b.id)
    : a.project === 'factory'
      ? -1
      : 1;
const desc = (a: string | null | undefined, b: string | null | undefined) =>
  (b ?? '').localeCompare(a ?? '');

export function sortRows(rows: readonly DevTaskRow[], sort: Sort): DevTaskRow[] {
  const out = [...rows];
  if (sort === 'id') return out.sort(byId);
  if (sort === 'new') return out.sort((a, b) => desc(a.created, b.created) || -byId(a, b));
  if (sort === 'closed')
    return out.sort(
      (a, b) => Number(!a.closed) - Number(!b.closed) || desc(a.closed, b.closed) || -byId(a, b),
    );
  return out.sort((a, b) => statusRank(a.status) - statusRank(b.status) || byId(a, b));
}

/** Варианты выбора и их счёт — из всех задач (без фильтра этого же ключа). */
export function optionsOf(
  rows: readonly DevTaskRow[],
  key: ListKey,
): { value: string; n: number }[] {
  const n = new Map<string, number>();
  for (const t of rows) n.set(fieldOf(t, key), (n.get(fieldOf(t, key)) ?? 0) + 1);
  return [...n]
    .map(([value, c]) => ({ value, n: c }))
    .sort((a, b) => compareValues(key, a.value, b.value));
}

/** Версии — по убыванию (новые вехи сверху), «без» — в конце; остальное — по алфавиту. */
function compareValues(key: ListKey, a: string, b: string): number {
  if (a === NONE || b === NONE) return Number(a === NONE) - Number(b === NONE);
  if (key === 'milestone') return compareVersions(b, a);
  if (key === 'status') return statusRank(a) - statusRank(b);
  if (key === 'project') return a === 'factory' ? -1 : b === 'factory' ? 1 : a.localeCompare(b);
  return a.localeCompare(b);
}

/** «2.10» > «2.9»; не числа — по алфавиту. */
export function compareVersions(a: string, b: string): number {
  const pa = a.split(/[.-]/);
  const pb = b.split(/[.-]/);
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = pa[i] ?? '';
    const y = pb[i] ?? '';
    const nx = Number(x);
    const ny = Number(y);
    const d =
      x !== '' && y !== '' && !Number.isNaN(nx) && !Number.isNaN(ny) ? nx - ny : x.localeCompare(y);
    if (d) return d;
  }
  return 0;
}
