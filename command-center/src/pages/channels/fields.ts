// Чистая логика экрана каналов: блоки формы из `fields[]` фабрики, правка текста файла без
// переформатирования (jsonc-parser), привязка строк проверки к полям, понятные ошибки JSON.
import {
  applyEdits,
  modify,
  parse,
  printParseErrorCode,
  type JSONPath,
  type ParseError,
} from 'jsonc-parser';

import type { ChannelDetail, CheckLine, ConfigField } from '@/api/channels';

export type FileKind = ConfigField['file'];

/** Ключ поля в картах ошибок и черновиков: `config:scope.min_popularity_score`. */
export const fieldKey = (file: FileKind, path: readonly string[]) => `${file}:${path.join('.')}`;

/** Узел формы: поле и его вложенные поля (у объектов). Пояснения (`*_note`) — не поля. */
export type FieldNode = { field: ConfigField; children: FieldNode[] };

/** Блок формы — один ключ верхнего уровня; простые ключи верхнего уровня — в «Основное». */
export type Block = {
  id: string;
  file: FileKind;
  /** Ключ верхнего уровня; null — «Основное» (простые значения верхнего уровня). */
  key: string | null;
  field: ConfigField | null;
  nodes: FieldNode[];
};

const isContainer = (f: ConfigField) => f.kind === 'object';

export function buildBlocks(fields: readonly ConfigField[], file: FileKind): Block[] {
  const rows = fields.filter((f) => f.file === file && !f.prose);
  const byParent = new Map<string, ConfigField[]>();
  for (const f of rows) {
    const parent = f.path.slice(0, -1).join('.');
    byParent.set(parent, [...(byParent.get(parent) ?? []), f]);
  }
  const nodes = (f: ConfigField): FieldNode => ({
    field: f,
    children: isContainer(f) ? (byParent.get(f.path.join('.')) ?? []).map(nodes) : [],
  });
  const top = byParent.get('') ?? [];
  const simple = top.filter((f) => !isContainer(f));
  const blocks: Block[] = [];
  if (simple.length) {
    blocks.push({
      id: `${file}:`,
      file,
      key: null,
      field: null,
      nodes: simple.map((f) => ({ field: f, children: [] })),
    });
  }
  for (const f of top.filter(isContainer)) {
    blocks.push({ id: fieldKey(file, f.path), file, key: f.path[0]!, field: f, nodes: [nodes(f)] });
  }
  return blocks;
}

/** Все поля-листья блока (то, что правится), в порядке формы. */
export function leaves(nodes: readonly FieldNode[]): ConfigField[] {
  return nodes.flatMap((n) => (n.children.length ? leaves(n.children) : [n.field]));
}

/** Подпись ключа: `min_popularity_score` → «min popularity score». */
export const keyLabel = (key: string) => key.replaceAll('_', ' ');

/** Путь поля для человека: «scope → min popularity score». */
export const pathLabel = (path: readonly string[]) => path.map(keyLabel).join(' → ');

const TASK_PREFIX = /^(?:CF|CC)-\d{3,5}\b(?:\s*\([^)]*\))?\s*[:.,;-]?\s*/;
const TIP_MAX = 360;

/**
 * Пояснение поля для тултипа: без номера задачи в начале (номера — только под «подробнее»)
 * и не длиннее пары фраз. `full` — исходный текст, `trimmed` — что-то убрали.
 */
export function noteTip(note: string | null): {
  tip: string | null;
  full: string;
  trimmed: boolean;
} {
  if (!note) return { tip: null, full: '', trimmed: false };
  let tip = note.replace(TASK_PREFIX, '').trim();
  if (tip.length > TIP_MAX) {
    const cut = tip.slice(0, TIP_MAX);
    const stop = Math.max(cut.lastIndexOf('. '), cut.lastIndexOf('; '));
    tip = (stop > 120 ? cut.slice(0, stop + 1) : cut.replace(/\s+\S*$/, '')) + ' …';
  }
  if (tip.length && tip[0] !== tip[0]!.toUpperCase()) tip = tip[0]!.toUpperCase() + tip.slice(1);
  return { tip: tip || null, full: note, trimmed: tip !== note };
}

export const KIND_LABEL: Record<ConfigField['kind'], string> = {
  object: 'группа полей',
  array: 'список (JSON)',
  string: 'текст',
  number: 'число',
  boolean: 'да / нет',
  null: 'пусто (JSON)',
};

/** Поля, которые из центра не меняются (фабрика откажет `forbidden_change`). */
export function lockedReason(field: ConfigField): string | null {
  const p = field.path.join('.');
  if (p === 'channel_id')
    return 'Имя канала меняется переименованием канала в фабрике, а не правкой из центра.';
  if (field.file === 'config' && p === 'stance')
    return 'Путь к файлу позиции меняется в репозитории фабрики, а не из центра.';
  return null;
}

export function valueAt(doc: unknown, path: readonly string[]): unknown {
  let cur = doc;
  for (const k of path) {
    if (typeof cur !== 'object' || cur === null) return undefined;
    cur = (cur as Record<string, unknown>)[k];
  }
  return cur;
}

/** Отступ файла (пробелы или таб и сколько) — чтобы вставленное легло так же, как остальное. */
function indentOf(text: string): { insertSpaces: boolean; tabSize: number } {
  const m = text.match(/\n([ \t]+)"/);
  if (!m) return { insertSpaces: true, tabSize: 2 };
  return m[1]!.startsWith('\t')
    ? { insertSpaces: false, tabSize: 1 }
    : { insertSpaces: true, tabSize: m[1]!.length };
}

/**
 * Новое значение поля в тексте файла: меняются только байты этого значения, остальное
 * (порядок ключей, переносы, строчные массивы) остаётся как было.
 */
export function setValue(text: string, path: readonly string[], value: unknown): string {
  const edits = modify(text, path as JSONPath, value, {
    formattingOptions: { ...indentOf(text), eol: '\n' },
  });
  return applyEdits(text, edits);
}

const PARSE_ERROR_RU: Record<string, string> = {
  InvalidSymbol: 'лишний или непонятный символ',
  InvalidNumberFormat: 'число записано неправильно',
  PropertyNameExpected: 'ждали имя поля в кавычках',
  ValueExpected: 'ждали значение',
  ColonExpected: 'после имени поля нужно двоеточие',
  CommaExpected: 'между полями нужна запятая',
  CloseBraceExpected: 'не хватает закрывающей фигурной скобки }',
  CloseBracketExpected: 'не хватает закрывающей квадратной скобки ]',
  EndOfFileExpected: 'после конца JSON есть лишний текст',
  InvalidCommentToken: 'комментарии в JSON не допускаются',
  UnexpectedEndOfComment: 'комментарий не закрыт',
  UnexpectedEndOfString: 'строка не закрыта кавычкой',
  UnexpectedEndOfNumber: 'число оборвано',
  InvalidUnicode: 'неправильный символ \\u…',
  InvalidEscapeCharacter: 'неправильная обратная косая черта в строке',
  InvalidCharacter: 'недопустимый символ в строке (перенос строки — только как \\n)',
};

export type JsonProblem = {
  offset: number;
  length: number;
  line: number;
  column: number;
  text: string;
};

/** Ошибки синтаксиса JSON — по-русски, со строкой и столбцом. Пусто — JSON читается. */
export function jsonProblems(text: string): JsonProblem[] {
  const errors: ParseError[] = [];
  const doc: unknown = parse(text, errors, { allowTrailingComma: false, disallowComments: true });
  const out = errors.map((e) => {
    const before = text.slice(0, e.offset);
    const line = before.split('\n').length;
    const column = e.offset - before.lastIndexOf('\n');
    const what = PARSE_ERROR_RU[printParseErrorCode(e.error)] ?? 'ошибка в записи JSON';
    return { offset: e.offset, length: e.length, line, column, text: what };
  });
  if (!out.length && (typeof doc !== 'object' || doc === null || Array.isArray(doc))) {
    out.push({
      offset: 0,
      length: 1,
      line: 1,
      column: 1,
      text: 'весь файл должен быть одним объектом в фигурных скобках { … }',
    });
  }
  return out;
}

/** На какое поле указывает строка проверки (`field` фабрики — путь через точку). */
export function errorTarget(field: string | null): { file: FileKind; path: string[] } | null {
  if (!field) return null;
  if (field.startsWith('stance.')) return { file: 'stance', path: field.slice(7).split('.') };
  return { file: 'config', path: field.split('.') };
}

/** Ключи всех полей, которые строка проверки задевает: само поле и его предки. */
export function errorKeys(lines: readonly CheckLine[]): Set<string> {
  const out = new Set<string>();
  for (const l of lines) {
    const t = errorTarget(l.field);
    if (!t) continue;
    for (let i = 1; i <= t.path.length; i++) out.add(fieldKey(t.file, t.path.slice(0, i)));
  }
  return out;
}

/**
 * Строка проверки для человека. `where` — подпись поля формы, куда она ведёт (по `field`;
 * null — канал целиком). Есть русская строка фабрики (`text_ru`, CC-0054) — она и есть `why`,
 * поле и значение в ней уже названы (`ru`). Нет (проверка позиции, строка без своей причины) —
 * запасной путь: `why` — английский текст проверки без технической приставки `<файл>.<путь>:`,
 * а поле называет `where`. Английская строка и код причины — под «подробнее» (`checkDetail`).
 */
export function humanCheck(line: CheckLine): { where: string | null; why: string; ru: boolean } {
  const t = errorTarget(line.field);
  const where = t ? `${t.file === 'stance' ? 'Позиция: ' : ''}${pathLabel(t.path)}` : null;
  if (line.text_ru) return { where, why: line.text_ru, ru: true };
  const colon = line.text.indexOf(': ');
  const head = colon > 0 ? line.text.slice(0, colon) : '';
  const why = colon > 0 && !/\s/.test(head) ? line.text.slice(colon + 2) : line.text;
  return { where, why: why.charAt(0).toUpperCase() + why.slice(1), ru: false };
}

/** Строка проверки для «подробнее»: английский текст фабрики и код причины, если он есть. */
export function checkDetail(line: CheckLine): string {
  return line.code ? `${line.text} (код причины: ${line.code})` : line.text;
}

/** Что изменилось в черновике по сравнению с файлом: ключи листьев, значения которых другие. */
export function changedKeys(
  fields: readonly ConfigField[],
  docs: Record<FileKind, unknown>,
  saved: Record<FileKind, unknown>,
): Set<string> {
  const out = new Set<string>();
  for (const f of fields) {
    if (f.prose || f.kind === 'object') continue;
    const a = JSON.stringify(valueAt(docs[f.file], f.path));
    const b = JSON.stringify(valueAt(saved[f.file], f.path));
    if (a !== b) {
      for (let i = 1; i <= f.path.length; i++) out.add(fieldKey(f.file, f.path.slice(0, i)));
    }
  }
  return out;
}

/** Разобрать текст файла; null — не JSON-объект. */
export function readDoc(text: string | null): Record<string, unknown> | null {
  if (text === null) return null;
  try {
    const d: unknown = JSON.parse(text);
    return typeof d === 'object' && d !== null && !Array.isArray(d)
      ? (d as Record<string, unknown>)
      : null;
  } catch {
    return null;
  }
}

export { channelName } from './names';

type BatchSchedule = {
  window?: unknown;
  tz?: unknown;
  window_hours?: unknown;
  min_feed_days?: unknown;
};

/** Расписание батчей — как оно записано в конфиге (`batch_schedule`), без своих расчётов. */
export function scheduleText(detail: ChannelDetail | undefined): string | null {
  const s = detail?.config.batch_schedule as BatchSchedule | undefined;
  if (!s || typeof s !== 'object') return null;
  const parts: string[] = [];
  if (typeof s.window === 'string') {
    parts.push(
      typeof s.window_hours === 'number'
        ? `окно с ${s.window} на ${s.window_hours} ч`
        : `окно с ${s.window}`,
    );
  }
  if (typeof s.tz === 'string') parts.push(s.tz);
  return parts.length ? parts.join(' · ') : null;
}
