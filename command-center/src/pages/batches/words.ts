// Коды карточки батча словами (CC-0118): стадии, агенты и источники вопросов, что сделал
// исполнитель без человека (`took`), код выхода процесса, итог события ленты, тема по слагу.
// Правило ROADMAP «для человека»: на виду — русские слова, сам код — только под «подробнее».
// Незнакомый код не выходит на экран как есть — у каждого словаря есть запасное слово.
import type { BatchTopics } from '@/api/batchTopics';
import { readableSlug } from '@/api/videos';
import type { BatchEvent } from '@/api/eventsFeed';
import type { Tone } from '@/components/common/Status';
import { sourceName } from '@/pages/questions/format';

import { eventLine } from './going';
import { hasKind, isKnownStage, stageName, stageTitle } from './stages';

/** Строка — код фабрики (латиница без пробелов: `skipped_no_permission`, `studio-read`). */
export const isCode = (s: string): boolean => /^[A-Za-z0-9_.:@/-]+$/.test(s);

const hasCyrillic = (s: string) => /[а-яё]/i.test(s);

/** Агенты и скрипты фабрики, которых нет среди стадий run_plan и источников вопросов. */
const AGENTS: Record<string, string> = {
  'run-executor': 'Исполнитель',
  'compliance-checker': 'Проверка на риски',
  publisher: 'Публикатор',
  'meme-maker': 'Мемы',
  notify: 'Уведомления',
};

/** Запасное имя незнакомого шага фабрики. */
export const UNKNOWN_STEP = 'Шаг фабрики';

/**
 * Стадия, агент или скрипт фабрики словами: словарь стадий run_plan, агенты, источники
 * вопросов, вид кадра по имени; ничего не подошло — «Шаг фабрики».
 */
export function nameOf(id: string | null | undefined): string {
  if (!id) return UNKNOWN_STEP;
  if (isKnownStage(id)) return stageName(id);
  if (AGENTS[id]) return AGENTS[id];
  const source = sourceName(id);
  if (source !== id) return source;
  if (hasKind(id)) return stageTitle(id);
  return isCode(id) ? UNKNOWN_STEP : id;
}

/**
 * Журнал стадии словами: `video-editor.s0.a1.log` → «Монтаж · попытка 2»,
 * `plan-check-after-supplement.content-researcher-reserve.s0.a0.log` → «Проверка плана после
 * добора: Резерв сценариев». Шаг (`sN`) — только когда он не первый; имя файла — под «подробнее».
 */
export function logLabel(file: string): string {
  const parts = file.replace(/\.log$/, '').split('.');
  let step = 0;
  let attempt = 0;
  const names: string[] = [];
  for (const p of parts) {
    const s = /^s(\d+)$/.exec(p);
    const a = /^a(\d+)$/.exec(p);
    if (s) step = Number(s[1]);
    else if (a) attempt = Number(a[1]);
    else if (p) names.push(nameOf(p));
  }
  const head = names.length ? names.join(': ') : UNKNOWN_STEP;
  return [head, step ? `шаг ${step + 1}` : '', attempt ? `попытка ${attempt + 1}` : '']
    .filter(Boolean)
    .join(' · ');
}

/** Что исполнитель сделал сам, не дождавшись человека (`needs_human[].took`). */
const TOOK: Record<string, string> = {
  skipped_no_permission: 'пропустил шаг — нет разрешения',
  skipped_no_chrome: 'пропустил шаг — нет Chrome',
  skipped_no_login: 'пропустил шаг — нет входа в аккаунт',
  skipped_timeout: 'пропустил шаг — вышло время',
  skipped: 'пропустил шаг',
  timeout: 'не дождался — вышло время',
  default: 'взял значение по умолчанию',
  used_default: 'взял значение по умолчанию',
  deferred: 'отложил шаг до вас',
  continued: 'продолжил без ответа',
};

export function tookText(code: string): string {
  if (!isCode(code)) return code;
  const known = TOOK[code];
  if (known) return known;
  if (/^skip/.test(code)) return 'пропустил шаг';
  if (/default/.test(code)) return 'взял значение по умолчанию';
  return 'решил сам, не дожидаясь вас';
}

/**
 * Строка списка `needs_human` батча («studio-read: skipped_no_permission») словами. Строку,
 * написанную для человека, — как есть.
 */
export function needsLine(s: string): string {
  const m = /^([A-Za-z0-9._@-]+):\s*([A-Za-z0-9_.-]+)$/.exec(s.trim());
  if (m?.[1] && m[2]) return `${nameOf(m[1])}: исполнитель пошёл дальше — ${tookText(m[2])}`;
  return isCode(s) ? 'Исполнитель отложил шаг до вас' : s;
}

/** Процесс исполнителя: жив / завершён / завершён с ошибкой (сам код — в «подробнее»). */
export function exitText(exit: number | null | undefined): { label: string; tone: Tone } {
  if (exit == null) return { label: 'не работает', tone: 'idle' };
  return exit === 0
    ? { label: 'завершён', tone: 'ok' }
    : { label: 'завершён с ошибкой', tone: 'warn' };
}

/**
 * Итоги событий. Первыми — статусы, которые фабрика на деле пишет в RUN_EVENTS.jsonl (выборка
 * драйвера по четырём последним батчам, 13.10): start, done, failed, stage-start, stage-done,
 * batch-start, batch-resume, batch-done, red; дальше — запасные похожие формы.
 */
const RESULTS: [RegExp, string, Tone][] = [
  [/^stage[-_]start(ed)?$/, 'этап начат', 'live'],
  [/^stage[-_]done$/, 'этап готов', 'ok'],
  [/^batch[-_]start(ed)?$/, 'батч начат', 'live'],
  [/^batch[-_]resume[d]?$/, 'батч продолжен', 'live'],
  [/^batch[-_]done$/, 'батч закрыт', 'ok'],
  [/^red$/, 'красная проверка', 'danger'],
  [/^(ok|done|passed|pass|success|finished|complete[d]?)$/, 'готово', 'ok'],
  [/^(start|started|running|begin)$/, 'начал', 'live'],
  [/^(restart|restarted)$/, 'перезапуск', 'warn'],
  [/^(retry|rerun)$/, 'повтор', 'warn'],
  [/^(skip|skipped|not[-_]needed|noop)$/, 'пропущен', 'idle'],
  [/^(fail|failed|error|crashed)$/, 'ошибка', 'danger'],
  [/^timeout$/, 'вышло время', 'danger'],
  [/^(stopped|paused|halted)$/, 'остановлен', 'warn'],
  [/^(warn|warning)$/, 'предупреждение', 'warn'],
  [/^(pending|waiting)$/, 'ждёт', 'idle'],
];

/** Итог события без `status` (у фабрики таких строк много) — нейтральное слово. */
export const NO_STATUS = { label: 'запись', tone: 'idle' as Tone };

/** Итог события ленты (`status`) словами; незнакомый код — «другой итог». */
export function resultText(status: string): { label: string; tone: Tone } {
  if (!isCode(status)) return { label: status, tone: 'idle' };
  const hit = RESULTS.find(([re]) => re.test(status.toLowerCase()));
  return hit ? { label: hit[1], tone: hit[2] } : { label: 'другой итог', tone: 'idle' };
}

/** Названия тем батча по их id и слагам роликов (данные тем, CC-0092). */
export function topicNames(topics: BatchTopics | null | undefined): Map<string, string> {
  const out = new Map<string, string>();
  for (const t of topics?.topics ?? []) {
    if (!t.title) continue;
    if (t.topic_id) out.set(t.topic_id, t.title);
    for (const s of t.scripts ?? []) if (s.video?.slug) out.set(s.video.slug, t.title);
  }
  for (const t of topics?.skipped ?? []) if (t.title && t.topic_id) out.set(t.topic_id, t.title);
  return out;
}

/** Тема по слагу: название из данных тем, иначе слаг словами (`readableSlug`, CC-0116). */
export const topicName = (slug: string, names: Map<string, string>): string =>
  names.get(slug) ?? readableSlug(slug);

const str = (v: unknown) => (typeof v === 'string' && v ? v : null);

export type EventParts = {
  time: string;
  /** «Монтаж · Vanguards: Doomsday» — стадия и тема словами. */
  what: string;
  /** Пояснение фабрики, если оно написано по-русски. */
  note: string | null;
  result: { label: string; tone: Tone } | null;
  marker: boolean;
  /** Строка как есть — для «подробнее»: «video-editor · vanguards-doomsday · edit-29 — ok». */
  raw: string;
};

/** Событие ленты словами: время · стадия · тема · итог; коды и id — в `raw`. */
export function eventParts(e: BatchEvent, names: Map<string, string>): EventParts {
  const line = eventLine(e);
  if (!e.event) {
    return {
      time: line.time,
      what: 'Запись журнала',
      note: null,
      result: null,
      marker: false,
      raw: line.text,
    };
  }
  const ev = e.event;
  const kind = str(ev.kind);
  const stage = str(ev.stage);
  const video = str(ev.video);
  const status = str(ev.status);
  const note = str(ev.note);
  const head = stage
    ? nameOf(stage)
    : kind === 'marker'
      ? 'Отметка'
      : kind === 'step'
        ? 'Шаг'
        : 'Событие';
  return {
    time: line.time,
    what: [head, video ? topicName(video, names) : null].filter(Boolean).join(' · '),
    note: note && hasCyrillic(note) ? note : null,
    result: status ? resultText(status) : NO_STATUS,
    marker: line.marker,
    raw: line.text,
  };
}
