// Маленький безопасный markdown тел задач (CC-0124): заголовки, абзацы, списки (с галочками
// чеклиста), код, цитаты, таблицы, черта; в строке — `код`, **жирный**, *курсив*, ссылки и
// номера задач (CF-xxxx, CC-xxxx). Разбор — в дерево, рисует его React (`Markdown.tsx`): сырой
// HTML не вставляется никогда — `<script>` останется текстом. Ссылки — только http(s) и mailto;
// остальные (`javascript:`, относительные пути репо) — просто текст.

export type Inline =
  | { t: 'text'; v: string }
  | { t: 'code'; v: string }
  | { t: 'strong'; c: Inline[] }
  | { t: 'em'; c: Inline[] }
  | { t: 'link'; href: string; c: Inline[] }
  | { t: 'task'; id: string; range?: string };

export type ListItem = { c: Inline[]; depth: number; check: boolean | null };

export type Block =
  | { t: 'heading'; level: number; c: Inline[] }
  | { t: 'p'; c: Inline[] }
  | { t: 'ul' | 'ol'; items: ListItem[]; start: number }
  | { t: 'code'; lang: string; v: string }
  | { t: 'quote'; c: Inline[] }
  | { t: 'table'; head: Inline[][]; rows: Inline[][][] }
  | { t: 'hr' };

// Номер задачи и необязательный хвост диапазона: CC-0001…0037, CF-0601–CF-0605, CC-0001...0037.
const ID = /((?:CF|CC)-\d{4})/.source;
const RANGE = /((?:\s?[…–—]\s?|\.\.\.|-)(?:(?:CF|CC)-)?\d{4})?\b/.source;

/** Номер задачи фабрики или центра (группа 1) и хвост диапазона (группа 2). */
export const TASK_ID = new RegExp(`\\b${ID}${RANGE}`, 'g');

const SAFE_HREF = /^(?:https?:\/\/|mailto:)/i;

/** Ссылка, по которой можно перейти: http(s) и mailto. */
export const safeHref = (href: string) => (SAFE_HREF.test(href.trim()) ? href.trim() : null);

const INLINE = new RegExp(
  [
    /(`+)([^`]+?)\1/.source, // 1–2: код
    /\[([^\]\n]+)\]\(([^)\s]+)\)/.source, // 3–4: ссылка
    /\*\*(?=\S)(.+?)(?<=\S)\*\*/.source, // 5: жирный
    /__(?=\S)(.+?)(?<=\S)__/.source, // 6: жирный
    /(?<![\p{L}\p{N}*])\*(?=[^\s*])(.+?)(?<=[^\s*])\*(?!\*)/u.source, // 7: курсив
    /(?<![\p{L}\p{N}_])_(?=[^\s_])(.+?)(?<=[^\s_])_(?![\p{L}\p{N}_])/u.source, // 8: курсив
    `\\b${ID}${RANGE}`, // 9–10: номер задачи и хвост диапазона
    /(https?:\/\/[^\s<>()]*[^\s<>().,;:!?'"»])/.source, // 11: голый адрес
  ].join('|'),
  'gu',
);

export function parseInline(src: string): Inline[] {
  const out: Inline[] = [];
  const text = (v: string) => {
    if (!v) return;
    const last = out[out.length - 1];
    if (last?.t === 'text') last.v += v;
    else out.push({ t: 'text', v });
  };
  let at = 0;
  for (const m of src.matchAll(INLINE)) {
    text(src.slice(at, m.index));
    at = m.index + m[0].length;
    if (m[2] !== undefined) out.push({ t: 'code', v: m[2] });
    else if (m[3] !== undefined) {
      const href = safeHref(m[4]!);
      if (href) out.push({ t: 'link', href, c: parseInline(m[3]) });
      else
        for (const x of parseInline(m[3])) {
          if (x.t === 'text') text(x.v);
          else out.push(x);
        }
    } else if (m[5] !== undefined || m[6] !== undefined)
      out.push({ t: 'strong', c: parseInline(m[5] ?? m[6]!) });
    else if (m[7] !== undefined || m[8] !== undefined)
      out.push({ t: 'em', c: parseInline(m[7] ?? m[8]!) });
    else if (m[9] !== undefined)
      out.push(m[10] ? { t: 'task', id: m[9], range: m[10] } : { t: 'task', id: m[9] });
    else if (m[11] !== undefined)
      out.push({ t: 'link', href: m[11], c: [{ t: 'text', v: m[11] }] });
  }
  text(src.slice(at));
  return out;
}

/** Строка → текст и номера задач (подписи коммитов, заголовки). */
export type IdPart = { id: string; range?: string };

export function splitIds(src: string): (string | IdPart)[] {
  const out: (string | IdPart)[] = [];
  let at = 0;
  for (const m of src.matchAll(TASK_ID)) {
    if (m.index > at) out.push(src.slice(at, m.index));
    out.push(m[2] ? { id: m[1]!, range: m[2] } : { id: m[1]! });
    at = m.index + m[0].length;
  }
  if (at < src.length) out.push(src.slice(at));
  return out;
}

const FENCE = /^\s*(```|~~~)\s*([\w+-]*)\s*$/;
const HEADING = /^(#{1,6})\s+(.*?)\s*#*\s*$/;
const HR = /^\s*([-*_])(?:\s*\1){2,}\s*$/;
const UL = /^(\s*)[-*+]\s+(.*)$/;
const OL = /^(\s*)(\d{1,9})[.)]\s+(.*)$/;
const CHECK = /^\[([ xX])\]\s+(.*)$/;
const QUOTE = /^\s*>\s?(.*)$/;
const ROW = /^\s*\|(.*)\|\s*$/;
const SEP = /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/;

const cells = (line: string) =>
  ROW.exec(line)![1]!
    .split('|')
    .map((c) => parseInline(c.trim()));

export function parseMarkdown(src: string): Block[] {
  const lines = src.replace(/\r\n?/g, '\n').split('\n');
  const out: Block[] = [];
  let para: string[] = [];
  const flush = () => {
    if (para.length) out.push({ t: 'p', c: parseInline(para.join(' ')) });
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const fence = FENCE.exec(line);
    if (fence) {
      flush();
      const body: string[] = [];
      for (i++; i < lines.length && !lines[i]!.trim().startsWith(fence[1]!); i++)
        body.push(lines[i]!);
      out.push({ t: 'code', lang: fence[2] ?? '', v: body.join('\n') });
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    const h = HEADING.exec(line);
    if (h) {
      flush();
      out.push({ t: 'heading', level: h[1]!.length, c: parseInline(h[2]!) });
      continue;
    }
    if (HR.test(line)) {
      flush();
      out.push({ t: 'hr' });
      continue;
    }
    if (ROW.test(line) && i + 1 < lines.length && SEP.test(lines[i + 1]!)) {
      flush();
      const head = cells(line);
      const rows: Inline[][][] = [];
      for (i += 2; i < lines.length && ROW.test(lines[i]!); i++) rows.push(cells(lines[i]!));
      i--;
      out.push({ t: 'table', head, rows });
      continue;
    }
    const ul = UL.exec(line);
    const ol = ul ? null : OL.exec(line);
    if (ul || ol) {
      flush();
      const kind = ul ? 'ul' : 'ol';
      const items: ListItem[] = [];
      const start = ol ? Number(ol[2]) : 1;
      for (; i < lines.length; i++) {
        const l = lines[i]!;
        const u = UL.exec(l);
        const o = u ? null : OL.exec(l);
        const m = kind === 'ul' ? u : o;
        if (m) {
          const indent = m[1]!.replace(/\t/g, '  ').length;
          const text = (kind === 'ul' ? m[2] : m[3])!;
          const c = CHECK.exec(text);
          items.push({
            depth: Math.min(3, Math.floor(indent / 2)),
            check: c ? c[1] !== ' ' : null,
            c: parseInline(c ? c[2]! : text),
          });
          continue;
        }
        // Продолжение пункта — строка с отступом под ним.
        if (l.trim() && /^\s{2,}\S/.test(l) && !u && !o && items.length) {
          const last = items[items.length - 1]!;
          last.c.push({ t: 'text', v: ' ' }, ...parseInline(l.trim()));
          continue;
        }
        break;
      }
      i--;
      out.push({ t: kind, items, start });
      continue;
    }
    const q = QUOTE.exec(line);
    if (q) {
      flush();
      const body: string[] = [];
      for (; i < lines.length && QUOTE.test(lines[i]!); i++) body.push(QUOTE.exec(lines[i]!)![1]!);
      i--;
      out.push({ t: 'quote', c: parseInline(body.join(' ')) });
      continue;
    }
    para.push(line.trim());
  }
  flush();
  return out;
}
