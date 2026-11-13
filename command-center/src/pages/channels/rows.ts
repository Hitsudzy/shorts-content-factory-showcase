// Строки редактора списка (./RowsEditor, CC-0115 шаг 3, З7): исходный объект строки (с полями,
// которых редактор не знает) и текст её полей; документ собирается обратно `rowOf`. Поле, которое
// не трогали, уходит обратно как было — `null`, число, код, флажок (CC-0129): правка одного поля
// не переписывает остальные. Ключ с точками — вложенное поле (`attribution.credit`,
// `found_by.0.how`, CC-0130): правится только оно, соседи во вложенном объекте — как были.
export type Row = Record<string, unknown>;

export type FieldSpec = {
  key: string;
  label: string;
  /**
   * `list` — строка через запятую ↔ массив строк; `select` — один из `options`; `bool` — флажок
   * (`true`/`false`; снятый флажок, которого в строке не было, ключа не добавляет); `lines` —
   * многострочное поле ↔ массив строк, одна строка — один элемент (CC-0130).
   */
  kind?: 'text' | 'list' | 'select' | 'bool' | 'lines';
  /** Поле во всю ширину строки (CC-0130). */
  wide?: boolean;
  /**
   * Значение — строка вариантов через этот знак (`pattern` фабрики: «eso|european southern
   * observatory»); поле показывает варианты через запятую и собирает обратно (CC-0130).
   */
  joined?: string;
  options?: { v: string; label: string }[];
  /** Значение поля — число (`select` уровня «1»/«2» → `1`/`2`), CC-0129. */
  num?: boolean;
  placeholder?: string;
  /** Подсказка к подписи — тултипом (CC-0131). */
  tip?: string;
  /** Подпись флажка рядом с ним (`bool`); по умолчанию «да». */
  check?: string;
  /**
   * Коды фабрики в текстовом поле → слова экрана (CC-0131: «curated» → «внесён вручную»).
   * Поле показывает слово; не тронутое слово уходит обратно кодом.
   */
  words?: Record<string, string>;
};

/** Строка в правке: исходный объект (с полями, которых редактор не знает) и текст полей. */
export type Item = { uid: number; row: Row; text: Record<string, string> };

let uidSeq = 0;

const isObj = (v: unknown): v is Record<string, unknown> =>
  !!v && typeof v === 'object' && !Array.isArray(v);

/** Значение по ключу с точками (`a.0.b`); нет — `undefined`. */
export function getAt(row: unknown, key: string): unknown {
  let cur: unknown = row;
  for (const k of key.split('.')) {
    if (Array.isArray(cur) && /^\d+$/.test(k)) cur = cur[Number(k)];
    else if (isObj(cur)) cur = cur[k];
    else return undefined;
  }
  return cur;
}

/** Есть ли ключ (с точками) в строке — даже со значением `null`. */
export function hasAt(row: unknown, key: string): boolean {
  const ks = key.split('.');
  const last = ks.pop()!;
  const parent = ks.length ? getAt(row, ks.join('.')) : row;
  if (Array.isArray(parent)) return /^\d+$/.test(last) && Number(last) < parent.length;
  return isObj(parent) && last in parent;
}

/**
 * Копия строки с новым значением по ключу с точками; `undefined` — убрать ключ. Недостающие
 * уровни создаются (число — массив), соседи на пути — как были.
 */
export function setAt<T>(row: T, key: string, value: unknown): T {
  const [k, ...rest] = key.split('.') as [string, ...string[]];
  const idx = /^\d+$/.test(k) ? Number(k) : null;
  const base: unknown = row;
  if (!rest.length) {
    if (Array.isArray(base) && idx != null) {
      const out = [...base];
      if (value === undefined) out.splice(idx, 1);
      else out[idx] = value;
      return out as T;
    }
    const out = { ...(isObj(base) ? base : {}) };
    if (value === undefined) delete out[k];
    else out[k] = value;
    return out as T;
  }
  const child = Array.isArray(base) && idx != null ? base[idx] : isObj(base) ? base[k] : undefined;
  if (value === undefined && child === undefined) return row;
  const next =
    child !== undefined && child !== null && typeof child === 'object'
      ? child
      : /^\d+$/.test(rest[0]!)
        ? []
        : {};
  const sub = setAt(next, rest.join('.'), value);
  if (Array.isArray(base) && idx != null) {
    const out = [...base];
    out[idx] = sub;
    return out as T;
  }
  return { ...(isObj(base) ? base : {}), [k]: sub } as T;
}

/** Текст поля из значения строки (флажок — «1» или пусто). */
export const textOf = (v: unknown, f: Pick<FieldSpec, 'kind' | 'words' | 'joined'>): string =>
  f.joined && typeof v === 'string'
    ? v
        .split(f.joined)
        .map((s) => s.trim())
        .filter(Boolean)
        .join(', ')
    : f.kind === 'bool'
      ? v === true
        ? '1'
        : ''
      : typeof v === 'string' && f.words?.[v]
        ? f.words[v]
        : f.kind === 'list' || f.kind === 'lines'
          ? Array.isArray(v)
            ? v.filter((x) => typeof x === 'string').join(f.kind === 'lines' ? '\n' : ', ')
            : ''
          : typeof v === 'string'
            ? v
            : v == null
              ? ''
              : String(v);

export function itemOf(row: Row, fields: FieldSpec[]): Item {
  return {
    uid: ++uidSeq,
    row,
    text: Object.fromEntries(fields.map((f) => [f.key, textOf(getAt(row, f.key), f)])),
  };
}

export const itemsOf = (rows: unknown, fields: FieldSpec[]): Item[] =>
  Array.isArray(rows)
    ? rows.filter((r): r is Row => !!r && typeof r === 'object').map((r) => itemOf(r, fields))
    : [];

/** Значение из введённого текста: слово экрана — кодом, число — числом. */
function valueOf(t: string, f: FieldSpec): unknown {
  if (f.words) {
    const code = Object.keys(f.words).find((k) => f.words![k] === t);
    if (code != null) return code;
  }
  if (f.num && /^-?\d+(\.\d+)?$/.test(t)) return Number(t);
  return t;
}

/**
 * Строка документа из правки. Не тронутое поле — как было; пустое поле — ключа нет (было —
 * убрано); снятый флажок — `false`, если ключ в строке был.
 */
export function rowOf(item: Item, fields: FieldSpec[]): Row {
  let out: Row = { ...item.row };
  for (const f of fields) {
    const raw = item.text[f.key] ?? '';
    const had = hasAt(item.row, f.key);
    if (had && raw === textOf(getAt(item.row, f.key), f)) continue;
    if (f.kind === 'bool') {
      if (raw) out = setAt(out, f.key, true);
      else if (had) out = setAt(out, f.key, false);
      continue;
    }
    const t = raw.trim();
    if (f.joined) {
      const parts = t
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean);
      out = setAt(out, f.key, parts.length ? parts.join(f.joined) : undefined);
    } else if (f.kind === 'list' || f.kind === 'lines') {
      const list = t
        .split(f.kind === 'lines' ? '\n' : ',')
        .map((s) => s.trim())
        .filter(Boolean);
      out = setAt(out, f.key, list.length ? list : undefined);
    } else out = setAt(out, f.key, t ? valueOf(t, f) : undefined);
  }
  return out;
}
