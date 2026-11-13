// Слова экрана «Вопросы»: кто спросил (источник журнала — имя скрипта фабрики) и в каком
// состоянии вопрос. Имя скрипта на экран не выходит — только под «подробнее»; незнакомый
// источник называется как есть (новый скрипт фабрики не должен прятать свой вопрос).
import type { Question, QuestionStatus } from '@/api/questions';
import type { Tone } from '@/components/common/Status';

const SOURCES: Record<string, { name: string; tip: string }> = {
  'publisher-auth': {
    name: 'Доступ к YouTube',
    tip: 'Публикатор: срок разрешения на загрузку роликов в YouTube',
  },
  'analyst-metrics': { name: 'Аналитик', tip: 'Аналитик: просмотры, удержание и выводы по ним' },
  'footage-indexer': { name: 'Футаж', tip: 'Индексатор футажа: фильтр исходных роликов' },
  'studio-read': {
    name: 'Чтение Studio',
    tip: 'Чтение YouTube Studio канала: просмотры и удержание роликов',
  },
  'trend-hunter': { name: 'Охотник за трендами', tip: 'Охотник за трендами: выбор тем дня' },
  'content-researcher': { name: 'Исследование', tip: 'Исследователь: факты и источники темы' },
  'video-editor': { name: 'Монтаж', tip: 'Монтаж ролика и проверка кадров' },
  'archive-publish-month': {
    name: 'Архив публикаций',
    tip: 'Ежемесячный архив публикаций: что не хватает для сборки',
  },
  'needs-you-md': {
    name: 'Из старого списка',
    tip: 'Перенесено из прежнего списка NEEDS-YOU в журнал вопросов',
  },
};

/** Кто спросил — словами. */
export function sourceName(source: string): string {
  return SOURCES[source]?.name ?? source;
}

/** Подсказка к источнику; у незнакомого — общая. */
export function sourceTip(source: string): string {
  return SOURCES[source]?.tip ?? 'Скрипт фабрики, который задал вопрос';
}

export const STATUS: Record<QuestionStatus, { label: string; tone: Tone; tip: string }> = {
  open: {
    label: 'ждёт ответа',
    tone: 'warn',
    tip: 'Фабрика ждёт вашего ответа. Напишите его прямо в карточке',
  },
  answered: {
    label: 'ответ отправлен',
    tone: 'live',
    tip: 'Ответ записан в журнал фабрики. Когда всё сделано — отметьте вопрос решённым',
  },
  resolved: { label: 'решён', tone: 'ok', tip: 'Вопрос закрыт и лежит в истории' },
};

const time = (iso: string | null) => (iso ? Date.parse(iso) || 0 : 0);

/** Открытые — новые сверху; отвеченные — по времени ответа, новые сверху. */
export function liveOrder(a: Question, b: Question): number {
  if (a.status !== b.status) return a.status === 'open' ? -1 : 1;
  const key = (q: Question) => time(q.status === 'answered' ? q.answered_at : q.created);
  return key(b) - key(a) || b.n - a.n;
}

/** История — по времени «решено», новые сверху. */
export function historyOrder(a: Question, b: Question): number {
  return time(b.resolved_at ?? b.updated) - time(a.resolved_at ?? a.updated) || b.n - a.n;
}

/** Значение фильтра канала у вопросов без канала. */
export const NO_CHANNEL = '-';

/** Подходит ли вопрос под фильтры экрана (пустой фильтр — любой). */
export function matches(q: Question, source: string, channel: string): boolean {
  if (source && q.source !== source) return false;
  if (channel && (q.channel ?? NO_CHANNEL) !== channel) return false;
  return true;
}

/** Кто предложил ответ — словами: оператор (Claude) или скрипт, который спросил (CC-0086). */
export function suggesterName(by: string | null | undefined): string | null {
  if (!by) return null;
  if (by === 'operator' || by === 'claude') return 'оператор';
  return sourceName(by);
}

/**
 * Пометка у ответа (CC-0086): принято ли предложение или ответ свой. `null` — у вопроса не было
 * предложения и ответ не сказал, откуда пришёл, — различать нечего.
 */
export function answerKind(q: Question): { label: string; tip: string } | null {
  if (!q.answer) return null;
  if (q.accepted_suggestion)
    return {
      label: 'принято предложение',
      tip: 'Ответ — предложенное решение, принятое как есть',
    };
  if (q.suggestion || q.answered_via)
    return { label: 'свой ответ', tip: 'Ответ написан своими словами, а не взят из предложения' };
  return null;
}

/** Откуда пришёл ответ (`answered_via`) — словами, для «подробнее». */
export function viaName(via: string | null | undefined): string | null {
  if (!via) return null;
  if (via === 'center') return 'из центра';
  if (via === 'telegram') return 'из Telegram';
  return via;
}

/**
 * Строка «Ждут вас» на главной: сколько вопросов ждут ответа. `null` — список не пришёл.
 * «к» не остаётся в конце строки на телефоне (CC-0138): пробел после него — неразрывный.
 */
export function questionsLine(n: number | null): string {
  if (n === null) return 'Вопросы к\u00a0вам — на экране «Вопросы».';
  if (!n) return 'Вопросов к\u00a0вам нет.';
  return `Вопросов ждут вашего ответа: ${n}.`;
}
