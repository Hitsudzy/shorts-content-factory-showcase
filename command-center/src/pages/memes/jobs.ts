// Слова и опрос фоновой задачи банка мемов (CC-0132; их же берёт CC-0133): какой шаг идёт,
// как назвать задачу, почему запись закрыта, и `useBankJob` — какую задачу показывать. Блок
// задачи — ./Job.tsx.
import { useEffect, useRef, useState } from 'react';

import { problemCode } from '@/api/batchProblem';
import { useAfterMemes } from '@/api/memes';
import { useMemeJob, useMemeJobs, type MemeJob, type MemeJobRef } from '@/api/memeJobs';
import { NO_REASON_TEXT } from '@/api/reasonRu';

import { memeName, quoted } from './format';

/** Шаг задачи (`progress.step`) словами; незнакомый — словами вида задачи. */
export const STEP_WORDS: Record<string, string> = {
  cutout: 'Вырезаю фон',
  trim: 'Обрезаю поля',
  trim_blank: 'Обрезаю поля',
  embedding: 'Пересчитываю признаки для поиска похожих мемов',
  embed: 'Считаю признаки для поиска похожих мемов',
  add_image: 'Добавляю картинку',
  add_gif: 'Делаю гифку',
  // CC-0133: шаги добавлений и листа кадров
  download: 'Скачиваю',
  check: 'Проверяю файл',
  index: 'Записываю в банк',
  scenes: 'Ищу смены сцен',
  cut: 'Нарезаю GIF',
  frames: 'Извлекаю кадры',
  sheet: 'Склеиваю лист кадров',
};

/** Задачи, у которых «i из N» — шаги, а не мемы (CC-0133): добавления, лист, признаки. */
export const STEP_KINDS: ReadonlySet<string> = new Set(['add_image', 'add_gif', 'sheet', 'embed']);

type Prog = { step: string; text?: string | null } | null | undefined;

/** Шаг словами; видео из кэша банка не «скачивается», а берётся. */
export function stepWord(p: Prog): string | null {
  if (!p) return null;
  if (p.step === 'download' && p.text && !/^https?:\/\//.test(p.text)) return 'Беру видео';
  return STEP_WORDS[p.step] ?? null;
}

/**
 * Строка хода рядом с шагом: у вырезки и обрезки — имя мема, у задач по шагам — как есть (адрес,
 * «из кэша банка»), id новой записи — именем; у признаков строка повторяет шаг — не нужна.
 */
export function stepText(job: { kind?: string | null }, p: Prog): string | null {
  const t = p?.text?.trim();
  if (!t) return null;
  if (p!.step === 'embedding') return null;
  if (!STEP_KINDS.has(job.kind ?? '')) return quoted(t);
  if (p!.step === 'index') return quoted(t);
  return t;
}

export const cap = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : s);
export const hasCyrillic = (s: string) => /[а-яё]/i.test(s);

/** Как назвать задачу человеку: «вырезка фона»; без слов фабрики — «фоновая задача». */
export const jobWord = (j: { kind_word?: string | null } | null | undefined) =>
  j?.kind_word?.trim() || 'фоновая задача';

/** Почему запись банка закрыта, пока задача идёт (отмены нет). */
export const busyWhy = (j: { kind_word?: string | null }) =>
  `Идёт ${jobWord(j)}\u00a0— дождитесь её конца: отмены нет`;

/** Строка фабрики о провале задачи; без русских слов — «причина без описания». */
export const errorWords = (text: string | null | undefined) =>
  text && hasCyrillic(text) ? text : NO_REASON_TEXT;

/**
 * Задача банка канала: какую показывать и идёт ли она. `watch(id)` — после «да» (ответ
 * `MemeJobStarted`); `close()` — убрать законченную. Законченная остаётся на виду, пока её не
 * скроют, — даже когда список задач и стол её уже не называют.
 */
export function useBankJob(channel: string, deskJob: MemeJobRef | null | undefined) {
  const list = useMemeJobs(channel);
  const [watched, setWatched] = useState<string | null>(null);
  const [dismissed, setDismissed] = useState<string | null>(null);
  const found = list.data?.running?.job_id ?? deskJob?.job_id ?? null;
  // Нашли идущую задачу (страницу открыли посреди неё) — держим её до «скрыть».
  if (!watched && found && found !== dismissed) setWatched(found);
  const id = watched;
  const q = useMemeJob(channel, id);
  const job = q.data && q.data.job_id === id ? q.data : null;
  const after = useAfterMemes();
  const refreshed = useRef(new Set<string>());
  useEffect(() => {
    if (!job?.done || refreshed.current.has(job.job_id)) return;
    refreshed.current.add(job.job_id);
    void after();
  }, [job, after]);
  const code: string | null = q.isError ? (problemCode(q.error) ?? null) : null;
  const running: MemeJobRef | MemeJob | null = job
    ? job.done
      ? null
      : job
    : (deskJob ?? list.data?.running ?? null);
  return {
    job,
    running,
    /** Задачу спросить не вышло (кроме «такой задачи нет» — тогда показывать нечего). */
    error: q.isError && code !== 'unknown_job' ? q.error : null,
    lost: code === 'unknown_job',
    watch: (jobId: string) => {
      setDismissed(null);
      setWatched(jobId);
    },
    close: () => {
      setDismissed(id);
      setWatched(null);
    },
  };
}

/**
 * CC-0161: фабрика сохранила итог задачи, но git отказал в коммите — в папке фабрики остались
 * незаписанные правки. Словами для человека, без «коммита»; слово git — под «подробнее».
 */
export const COMMIT_REFUSED_TITLE =
  'Результат сохранён, но фабрика не смогла записать его в историю изменений\u00a0— в её папке остались незаписанные правки.';

/** Что делать человеку — обычным начертанием после заголовка строки. */
export const TELL_FACTORY = 'Скажите фабрике.';

export type JobCommitView =
  | { kind: 'refused'; title: string; action: string; detail: string | null }
  | { kind: 'committed'; text: string; sha: string | null }
  | null;

/**
 * Коммит итога задачи (`commit`, CF-0847) для человека: отказ git — заметной строкой (слово git —
 * под «подробнее»), коммит — приглушённым «записано в историю» (короткий sha — под «подробнее»);
 * «нечего коммитить» и старый стол без коммита — ничего.
 */
export function jobCommitView(job: { commit?: MemeJob['commit'] }): JobCommitView {
  const c = job.commit;
  if (!c) return null;
  if (c.status === 'refused')
    return {
      kind: 'refused',
      title: COMMIT_REFUSED_TITLE,
      action: TELL_FACTORY,
      detail: c.detail?.trim() || null,
    };
  if (c.status === 'committed')
    return {
      kind: 'committed',
      text: 'записано в историю',
      sha: c.sha ? c.sha.slice(0, 7) : null,
    };
  return null;
}

const escape = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

/**
 * Id мемов в строке фабрики — именами, как на столе: «distracted-boyfriend» → «Distracted
 * boyfriend» (сам id — под «подробнее»).
 */
export function namesIn(text: string, ids: readonly string[]): string {
  if (!ids.length) return text;
  // Один проход: имя, уже вставленное вместо длинного id, короткий id не трогает.
  const alt = [...ids]
    .sort((a, b) => b.length - a.length)
    .map(escape)
    .join('|');
  const re = new RegExp(`«(${alt})»|'(${alt})'|(?<![\\w-])(${alt})(?![\\w-])`, 'g');
  return text.replace(
    re,
    (_m, a?: string, b?: string, c?: string) => `«${memeName((a ?? b ?? c)!)}»`,
  );
}

/**
 * Заметка плана для человека: папка оригиналов банка — словами, прочие пути — «папка банка»
 * (пути — под «подробнее»), id мемов — именами.
 */
export function humanNote(text: string, ids: readonly string[] = []): string {
  const plain = text
    .replace(/(?:в\s+)?_desk\/originals\/?(?:\s+банка)?/g, 'в папке оригиналов банка')
    .replace(/(?<![\p{L}\d])[\w.-]*\/[\w./-]*[\w/-]/gu, 'папке банка');
  return namesIn(plain, ids);
}

/**
 * Причина после « — » — со строчной: «Распознавание не нашло…» → «распознавание не нашло…».
 * Только обычное слово (заглавная, за ней строчная кириллица); «GIF», «ЦРУ», имена латиницей —
 * как есть.
 */
export const afterDash = (s: string) =>
  /^[А-ЯЁ][а-яё]/.test(s) ? s[0]!.toLowerCase() + s.slice(1) : s;
