// Вход Claude перед ручным запуском (CC-0177 по CC-0176, CF-0899): план сообщает `login`
// (`ok` true / false / null) — это сведения, не защита; «да» без входа получает 409
// `not_logged_in`, токен потрачен. У resume-строк журнала запусков, которые тик продолжил сам
// после входа, — `auto` («NOT_LOGGED_IN на <stage>, <строка входа>»).
import type { Schemas } from '@/api/client';
import { humanDashes } from '@/api/humanText';

import { stageName } from './stages';

export type LoginState = Schemas['LoginState'];

/** Код отказа «да» без входа (CC-0176). */
export const NOT_LOGGED_IN = 'not_logged_in';

/** Как войти — одна строка для плана и отказа. */
export const LOGIN_HOW = 'в терминале `claude`, затем `/login`';

/** Вход проверен и его нет: «да» придержано до новой проверки. */
export const loginMissing = (l: LoginState | null | undefined) => l?.ok === false;

/** Вход не проверить (`ok: null`): запуск возможен, строка — мягкое предупреждение. */
export const loginUnknown = (l: LoginState | null | undefined) => !!l && l.ok == null;

const upper = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : s);

/**
 * «Вход не проверен: <строка фабрики>» — без повтора хвоста «- вход не проверен» самой строки;
 * строка, которая уже говорит «вход … не проверялся», — как есть.
 */
export function loginUnknownText(line: string | null | undefined): string {
  const bare = (line ?? '').replace(/\s+-\s+вход не проверен\.?\s*$/i, '').trim();
  if (!bare) return 'Вход в Claude не проверен';
  if (/^вход\s.*не провер/i.test(bare)) return humanDashes(upper(bare));
  return `Вход в Claude не проверен: ${humanDashes(bare)}`;
}

/**
 * Строка плана без входа: что сделать, чтобы «Запустить» стала доступна. Строка фабрики
 * (`claude auth status`…) техническая — она под «подробнее».
 */
export const LOGIN_MISSING_TEXT = `Claude не залогинен. Войдите — ${LOGIN_HOW} — и нажмите «Проверить снова».`;

/** Отказ «да» `not_logged_in` словами центра; строка фабрики — под «подробнее». */
export const NOT_LOGGED_IN_TEXT = `Claude не залогинен. Войдите — ${LOGIN_HOW} — батч не открыт.`;

/**
 * `auto` resume-строки: «NOT_LOGGED_IN на <stage>, <строка входа>» → словами центра. Строка
 * другого вида — как есть (тире по-русски).
 */
export function autoResumeText(auto: string | null | undefined): string {
  const said = (auto ?? '').trim();
  const m = said.match(/^NOT_LOGGED_IN на ([^,]+?)\s*,\s*(.*)$/);
  if (!m) return humanDashes(said);
  const stage = m[1]!.trim();
  const now = m[2]!.trim();
  return (
    `Батч стоял на «${stageName(stage)}»: Claude был не залогинен. ` +
    `Тик продолжил его сам${now ? ` — ${humanDashes(now)}` : ''}.`
  );
}

/** Куски строки: чётные — текст, нечётные — код. Непарный хвост — текстом с кавычкой. */
export function tickParts(text: string): { code: boolean; text: string }[] {
  const parts = text.split('`');
  if (parts.length % 2 === 0) {
    // непарная кавычка: последний кусок склеиваем обратно с ней
    const tail = parts.splice(-2, 2).join('`');
    parts.push(tail);
  }
  return parts
    .map((t, i) => ({ code: i % 2 === 1, text: t }))
    .filter((p) => p.code || p.text !== '');
}
