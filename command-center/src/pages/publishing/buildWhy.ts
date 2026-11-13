// CC-0175 (договор 0.76.0, CC-0174 / CF-0891): почему приёмка не запустила автосборку карточки —
// `queued.card_build.why`, строка фабрики `card_center.refusal_line` вида «code: line; code: line»
// (абсолютные пути API уже вырезал). Части разбираем: у строки есть русский текст — показываем его,
// иначе — код словами центра, иначе — строку как есть. Коды — только под «подробнее».
import { CARD_PROBLEM_TEXT } from '@/api/cards';

import { REASON_TEXT } from './cardWords';

export type BuildWhyPart = {
  /** Код отказа (`card_center.BUILD_REFUSALS`); у части без «code:» — null. */
  code: string | null;
  /** Строка фабрики после кода (как пришла). */
  line: string;
};

const CODE = /^([a-z][a-z0-9_]*)\s*:\s*/;
const CYRILLIC = /[А-Яа-яЁё]/;

/**
 * «code: line; code: line» → части. Делим только по «;», за которой идёт новый «code:», — точка
 * с запятой внутри строки фабрики часть не рвёт. Пусто / null — [].
 */
export function parseBuildWhy(why: string | null | undefined): BuildWhyPart[] {
  const s = why?.trim();
  if (!s) return [];
  return s
    .split(/;\s*(?=[a-z][a-z0-9_]*\s*:)/)
    .map((chunk) => chunk.trim().replace(/;$/, '').trim())
    .filter(Boolean)
    .map((chunk) => {
      const m = CODE.exec(chunk);
      return m
        ? { code: m[1]!, line: chunk.slice(m[0].length).trim() }
        : { code: null, line: chunk };
    });
}

const lowerFirst = (s: string) => (s ? s[0]!.toLowerCase() + s.slice(1) : s);
const bare = (s: string) => s.trim().replace(/[.;\s]+$/, '');

/** Код отказа сборки словами центра (отказы записи, затем `reasons` карточки); не знаем — null. */
const codeText = (code: string | null | undefined): string | null =>
  (code && (CARD_PROBLEM_TEXT[code] ?? REASON_TEXT[code])) || null;

/** Коды `card_build.refusals` словами, через «; », повторы — один раз (ответ без `why`). */
export function buildRefusalsText(codes: readonly string[]): string {
  return [...new Set(codes.map((c) => lowerFirst(bare(codeText(c) ?? 'фабрика отказала'))))].join(
    '; ',
  );
}

/** Одна часть словами: русская строка фабрики → она; иначе код словами центра; иначе строка. */
export function buildWhyPartText(p: BuildWhyPart): string {
  if (CYRILLIC.test(p.line)) return bare(p.line);
  const known = codeText(p.code);
  if (known) return bare(known);
  return bare(p.line) || 'фабрика отказала';
}

/** Причины словами через «; » (с маленькой буквы — встают после двоеточия); нет `why` — null. */
export function buildWhyText(why: string | null | undefined): string | null {
  const parts = parseBuildWhy(why);
  if (!parts.length) return null;
  return [...new Set(parts.map((p) => lowerFirst(buildWhyPartText(p))))].join('; ');
}
