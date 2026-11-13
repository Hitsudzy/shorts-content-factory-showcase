// Черновик отметок стола мемов в центре (CC-0025): отметки правятся здесь, в браузере, и уходят
// в фабрику только по «Сохранить отметки» — целиком, с отпечатком `base` того черновика, от
// которого их правили. Чужие изменения (другая вкладка, стол в терминале) центр не затирает:
// фабрика отвечает `check_changed`, а центр предлагает загрузить отметки заново.
//
// Здесь — чистые функции (что поменялось, тело сохранения, состояние мема) и хранилище
// черновиков по банкам: каналы одного банка делят один черновик фабрики, значит, и здесь он один.
import { useSyncExternalStore } from 'react';

import type { MemeDesk, MemeEntry } from '@/api/memes';

export type Verdict = 'keep' | 'drop';
/** Отметка без подписи «кто и когда»: то, что правит человек. */
export type Mark = { v?: Verdict; cut?: boolean; note?: string };
export type Marks = Record<string, Mark>;

/** `{v, cut, note}` из отметки стола; чужие и испорченные поля отбрасываются. */
export function coreOf(d: unknown): Mark {
  if (typeof d !== 'object' || d === null) return {};
  const x = d as Record<string, unknown>;
  const m: Mark = {};
  if (x.v === 'keep' || x.v === 'drop') m.v = x.v;
  if (typeof x.cut === 'boolean') m.cut = x.cut;
  if (typeof x.note === 'string') m.note = x.note;
  return m;
}

export function marksOf(decisions: Record<string, unknown> | null | undefined): Marks {
  const out: Marks = {};
  for (const [id, d] of Object.entries(decisions ?? {})) out[id] = coreOf(d);
  return out;
}

const isEmpty = (m: Mark | undefined) =>
  !m || (m.v === undefined && m.cut === undefined && m.note === undefined);

export function sameMark(a: Mark | undefined, b: Mark | undefined): boolean {
  if (isEmpty(a) && isEmpty(b)) return true;
  return a?.v === b?.v && a?.cut === b?.cut && a?.note === b?.note;
}

/** Мемы, чья отметка в черновике центра не та, что сохранена. */
export function changedIds(local: Marks, saved: Marks): string[] {
  const ids = new Set([...Object.keys(local), ...Object.keys(saved)]);
  return [...ids].filter((id) => !sameMark(local[id], saved[id])).sort();
}

function put(marks: Marks, id: string, m: Mark): Marks {
  const next = { ...marks };
  if (isEmpty(m)) delete next[id];
  else next[id] = m;
  return next;
}

/**
 * «Оставить» / «Убрать»: кнопкой то же ещё раз — снять решение (как на столе фабрики);
 * клавишей (`toggle: false`) — только поставить: быстрый разбор не снимает решений.
 */
export function withVerdict(marks: Marks, id: string, v: Verdict, toggle = true): Marks {
  const cur = marks[id] ?? {};
  const m: Mark = { ...cur };
  if (cur.v === v && toggle) delete m.v;
  else m.v = v;
  return put(marks, id, m);
}

/** Действует ли «можно вырезать»: у GIF — никогда (гифка идёт только целиком). */
export function cutOf(entry: Pick<MemeEntry, 'gif' | 'cutout'>, mark: Mark | undefined): boolean {
  return !entry.gif && (mark?.cut ?? entry.cutout);
}

/**
 * Пойдёт в ролик целиком (CC-0143, «только целиком» доски 8765): ровно обратное `cutOf` — не
 * отмечен «можно вырезать» с учётом черновика, и всякий GIF. Отказ фабрики по готовой вырезке
 * (`cut_refused`) отметку не снимает: такой мем остаётся под «С вырезкой», как и сама отметка.
 */
export function wholeOf(entry: Pick<MemeEntry, 'gif' | 'cutout'>, mark: Mark | undefined): boolean {
  return !cutOf(entry, mark);
}

/**
 * Переключить «можно вырезать». Вернулись к тому, что сохранено без отметки `cut`, — отметку
 * `cut` убираем: так черновик снова равен сохранённому, а не «изменён на то же самое».
 */
export function withCut(
  marks: Marks,
  saved: Mark | undefined,
  entry: Pick<MemeEntry, 'id' | 'gif' | 'cutout'>,
): Marks {
  if (entry.gif) return marks;
  const want = !cutOf(entry, marks[entry.id]);
  const m: Mark = { ...(marks[entry.id] ?? {}) };
  if (saved?.cut === undefined && want === entry.cutout) delete m.cut;
  else m.cut = want;
  return put(marks, entry.id, m);
}

/** Заметка к мему; пустая — без заметки. */
export function withNote(marks: Marks, id: string, note: string): Marks {
  const m: Mark = { ...(marks[id] ?? {}) };
  if (note === '') delete m.note;
  else m.note = note;
  return put(marks, id, m);
}

/** Тело `PUT …/marks`: черновик целиком, без мемов, которых в банке нет, и без пустых отметок. */
export function bodyOf(local: Marks, ids: ReadonlySet<string>): Record<string, Mark> {
  const out: Record<string, Mark> = {};
  for (const [id, m] of Object.entries(local)) if (ids.has(id) && !isEmpty(m)) out[id] = m;
  return out;
}

/** Отметки мемов, которых в банке уже нет (уйдут при сохранении). */
export function staleIds(local: Marks, ids: ReadonlySet<string>): string[] {
  return Object.keys(local)
    .filter((id) => !ids.has(id))
    .sort();
}

/** Что с мемом сейчас: новый без решения, оставить, убрать или уже в библиотеке. */
export type MemeState = 'new' | 'keep' | 'drop' | 'in';

export function stateOf(entry: Pick<MemeEntry, 'review'>, mark: Mark | undefined): MemeState {
  if (mark?.v === 'keep') return 'keep';
  if (mark?.v === 'drop') return 'drop';
  return entry.review === 'pending' ? 'new' : 'in';
}

// ---- Хранилище черновиков по банкам ----

export type Draft = {
  /** Отпечаток черновика фабрики, от которого правим (`null` — черновика не было). */
  base: string | null;
  /** Сохранённые отметки (как в фабрике на момент `base`). */
  saved: Marks;
  /** Отметки центра. */
  local: Marks;
  /** Черновик в фабрике поменялся мимо этой страницы, а у нас есть несохранённое. */
  conflict: boolean;
};

const drafts = new Map<string, Draft>();
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((l) => l());

export const isDirty = (d: Draft) => changedIds(d.local, d.saved).length > 0;

function fresh(desk: MemeDesk): Draft {
  const saved = marksOf(desk.decisions);
  return { base: desk.fingerprint ?? null, saved, local: saved, conflict: false };
}

export const draftStore = {
  get: (bank: string): Draft | undefined => drafts.get(bank),
  subscribe(l: () => void) {
    listeners.add(l);
    return () => {
      listeners.delete(l);
    };
  },
  /**
   * Пришёл стол из фабрики. Нет несохранённого — черновик центра становится фабричным. Есть, а
   * отпечаток уже другой, — не трогаем ничего своего и отмечаем, что черновик поменяли мимо нас.
   */
  sync(desk: MemeDesk) {
    const cur = drafts.get(desk.bank);
    const fp = desk.fingerprint ?? null;
    if (!cur || !isDirty(cur)) {
      const next = fresh(desk);
      if (cur && cur.base === next.base && !changedIds(cur.saved, next.saved).length) return;
      drafts.set(desk.bank, next);
    } else if (fp !== cur.base && !cur.conflict) {
      drafts.set(desk.bank, { ...cur, conflict: true });
    } else return;
    emit();
  },
  edit(bank: string, desk: MemeDesk, fn: (local: Marks, saved: Marks) => Marks) {
    const cur = drafts.get(bank) ?? fresh(desk);
    drafts.set(bank, { ...cur, local: fn(cur.local, cur.saved) });
    emit();
  },
  /** Сохранено: новый `base`, сохранённое — то, что ушло (правки во время сохранения остаются). */
  saved(bank: string, base: string | null, sent: Marks) {
    const cur = drafts.get(bank);
    if (!cur) return;
    drafts.set(bank, { ...cur, base, saved: sent, conflict: false });
    emit();
  },
  /** Фабрика ответила `check_changed`. */
  conflict(bank: string) {
    const cur = drafts.get(bank);
    if (!cur || cur.conflict) return;
    drafts.set(bank, { ...cur, conflict: true });
    emit();
  },
  /** «Загрузить заново»: свои несохранённые отметки — прочь, черновик — фабричный. */
  replace(desk: MemeDesk) {
    drafts.set(desk.bank, fresh(desk));
    emit();
  },
  /** Есть ли где-нибудь несохранённое (предупредить при уходе со страницы). */
  anyDirty: () => [...drafts.values()].some(isDirty),
};

/** Для тестов: забыть все черновики. */
export function resetMemeDrafts(): void {
  drafts.clear();
  emit();
}

/** Черновик банка; пока его нет — фабричный со стола. */
export function useDraft(desk: MemeDesk | undefined): Draft | null {
  const bank = desk?.bank ?? '';
  const d = useSyncExternalStore(draftStore.subscribe, () => draftStore.get(bank));
  if (!desk) return null;
  return d ?? fresh(desk);
}
