// Ролик, отказанный после монтажа (CC-0116, договор 0.42.0): фабрика его отрендерила, но сама
// отклонила (05 `refusals[]`), API отдаёт его в `videos[]` с `refused`. Здесь — его причина
// словами человека: «оценка ниже порога после штрафов: 24 из 40 — зависший кадр (1 блок, хук)». Строится из
// того, что отдал API (`score_line`, `score`, `reason`), коды и ворота — только под «подробнее».
import { FALLBACK_REASON, plainReason } from '@/api/plainReason';
import type { VideoRefusal } from '@/api/videos';

/** Ответ фабрики на вердикт отказанному ролику (409 `video_refused`) — простыми словами. */
export const VIDEO_REFUSED_TEXT =
  'Вердикт не записан: этот ролик не прошёл проверку после монтажа — решения он не ждёт. Его можно пересобрать.';

const num = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) ? v : null);
const hasCyrillic = (s: string) => /[а-яё]/i.test(s);

/** Отказ без строки фабрики (или только ворота отказа): общая строка, код — под «подробнее». */
const GENERIC = 'не прошёл проверку после монтажа';

/**
 * Что отказало — словами фабрики (CC-0113): `reason_ru` — строка `funnel.REASONS_RU` для кода
 * отказа (05 `refusals[]`, CC-0116). Своих подписей кодов здесь нет: без строки фабрики (код вне
 * словаря, только ворота) — общая строка, код и ворота — под «подробнее».
 */
export function refusalKind(r: Pick<VideoRefusal, 'reason_ru'> | string | null | undefined) {
  if (!r || typeof r === 'string') return GENERIC;
  return r.reason_ru?.trim().replace(/\.$/, '') || GENERIC;
}

/** Хвост строки оценки «F · 24 — −6 полоса…, −62 зависший кадр (1 блок, хук)» — после «—». */
function scoreTail(line: string | null | undefined): string | null {
  const m = line?.match(/\s[—–-]\s+(.+)$/);
  return m ? m[1]!.trim() : null;
}

/** Части хвоста через запятую — запятые в скобках («(1 блок, хук)») не делят. */
function splitTop(text: string): string[] {
  const out: string[] = [];
  let depth = 0;
  let cur = '';
  for (const ch of text) {
    if (ch === '(') depth += 1;
    if (ch === ')') depth = Math.max(0, depth - 1);
    if (ch === ',' && depth === 0) {
      out.push(cur.trim());
      cur = '';
    } else cur += ch;
  }
  if (cur.trim()) out.push(cur.trim());
  return out;
}

export type Penalty = { price: number; text: string; raw: string };

/**
 * Штрафы оценки из её строки, как их написала фабрика: «−62 зависший кадр (1 блок, хук)» →
 * {price: 62, text: «зависший кадр (1 блок, хук)»}. Что не читается как штраф — пропускается.
 */
export function penaltiesOf(r: VideoRefusal): Penalty[] {
  const tail = scoreTail(r.score_line);
  if (!tail) return [];
  return splitTop(tail).flatMap((raw) => {
    const m = raw.match(/^[−–-]\s*(\d+(?:[.,]\d+)?)\s+(.+)$/);
    return m ? [{ price: Number(m[1]!.replace(',', '.')), text: m[2]!.trim(), raw }] : [];
  });
}

/** Оценка из строки «F · 24 — …», если в `score` её нет. */
function scoreOfLine(line: string | null | undefined): number | null {
  const m = line?.match(/·\s*(\d+(?:[.,]\d+)?)/);
  return m ? Number(m[1]!.replace(',', '.')) : null;
}

const lowerFirst = (s: string) => (s ? s[0]!.toLowerCase() + s.slice(1) : s);
const upperFirst = (s: string) => (s ? s[0]!.toUpperCase() + s.slice(1) : s);

/** Главное в оценке: самый большой штраф её строки, иначе весь хвост после «—». */
function mainWhy(r: VideoRefusal): string | null {
  const top = penaltiesOf(r).reduce<Penalty | null>(
    (best, p) => (!best || p.price > best.price ? p : best),
    null,
  );
  return top?.text ?? scoreTail(r.score_line);
}

/**
 * «оценка ниже порога после штрафов: 24 из 40 — зависший кадр (1 блок, хук)». Оценка и порог — из
 * `score` (оценка — и из строки оценки), пояснение — слова фабрики: самый большой штраф строки
 * оценки, без неё — строка монтажа, если она по-русски (по-английски она — под «подробнее»).
 * Своего текста здесь нет.
 */
export function refusalLine(r: VideoRefusal): string {
  const kind = refusalKind(r);
  const score = num(r.score?.score) ?? scoreOfLine(r.score_line);
  const threshold = num(r.score?.threshold);
  const numbers =
    score != null && threshold != null
      ? `${score} из ${threshold}`
      : score != null
        ? `оценка ${score}`
        : null;
  const reason = r.reason?.trim() ?? '';
  const why = mainWhy(r) ?? (reason && hasCyrillic(reason) ? reason.replace(/\.$/, '') : null);
  const tail = why ? ` — ${lowerFirst(why)}` : '';
  return numbers ? `${kind}: ${numbers}${tail}` : `${kind}${tail}`;
}

/** То же с большой буквы — для отдельной строки. */
export const refusalSentence = (r: VideoRefusal) => upperFirst(refusalLine(r));

/**
 * Текст фабрики без путей (`plainReason`): в журнале оценки `note` и `where.shot` бывают
 * абсолютными путями (`/home/…/clips/a06_….mp4`) — их не видно даже под «подробнее».
 * Пустая после этого строка — пустая (а не запасная причина `plainReason`).
 */
export function noPaths(text: string): string {
  const out = plainReason(text);
  return out === FALLBACK_REASON && !text.includes(FALLBACK_REASON) ? '' : out;
}

/** Путь файла → его имя («/home/…/clips/a06_x.mp4» → «a06_x.mp4»); не путь — как есть. */
const fileName = (v: string) => (/[/\\]/.test(v) ? (v.split(/[/\\]/).pop() ?? '') : v);

function whereText(where: unknown): string {
  if (!where || typeof where !== 'object') return '';
  return Object.entries(where as Record<string, unknown>)
    .filter(([, v]) => v != null && v !== '')
    .map(([k, v]) => `${k} ${typeof v === 'string' ? fileName(v) : JSON.stringify(v)}`)
    .join(', ');
}

/** Журнал оценки (`score.log`) строками для «подробнее» — без абсолютных путей. */
export function scoreLogLines(r: VideoRefusal): string[] {
  const log = r.score?.log;
  if (!Array.isArray(log)) return [];
  return (log as unknown[]).flatMap((e) => {
    if (typeof e === 'string') return noPaths(e) ? [noPaths(e)] : [];
    if (!e || typeof e !== 'object') return [];
    const o = e as Record<string, unknown>;
    const head = [
      typeof o.price === 'number' ? String(o.price) : null,
      typeof o.rule === 'string' ? o.rule : null,
      o.hook ? 'хук' : null,
      whereText(o.where) || null,
    ]
      .filter(Boolean)
      .join(' · ');
    const note = typeof o.note === 'string' ? noPaths(o.note) : '';
    const line = noPaths([head, note].filter(Boolean).join(': '));
    return line ? [line] : [];
  });
}

/** Строка монтажа не вошла в слова (она по-английски или её заменила строка оценки) — без путей. */
export function reasonLeftOut(r: VideoRefusal): string | null {
  const reason = r.reason?.trim();
  if (!reason) return null;
  if (refusalLine(r).includes(lowerFirst(reason.replace(/\.$/, '')))) return null;
  return noPaths(reason) || null;
}
