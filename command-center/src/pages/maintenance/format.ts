// Слова экрана «Обслуживание и расход» (CC-0033): токены и байты по-русски, батч — каналом и
// временем по МСК, строки фабрики (правила пула, расхождения прогонов, счётчики) — словами.
// Строка как есть остаётся под «Подробнее» у того, кто её показывает.
import type { UsageRow } from '@/api/maintenance';
import { dateTimeMsk, plural } from '@/pages/batches/format';
import { batchIdIso } from '@/pages/batches/going';
import { stageName } from '@/pages/batches/stages';

const num = (n: number, digits = 1) =>
  new Intl.NumberFormat('ru-RU', { maximumFractionDigits: digits }).format(n);

/** «4,2 млн», «820 тыс.», «950». */
export function tokensText(n: number): string {
  if (n >= 1_000_000) return `${num(n / 1_000_000)} млн`;
  if (n >= 10_000) return `${num(n / 1_000, 0)} тыс.`;
  if (n >= 1_000) return `${num(n / 1_000)} тыс.`;
  return num(n, 0);
}

/** «1,4 ГБ», «640 МБ», «4 КБ»; перед единицей — неразрывный пробел (CC-0131). */
export function bytesText(n: number | null | undefined): string {
  if (n == null) return '—';
  const GB = 1024 ** 3;
  const MB = 1024 ** 2;
  if (n >= GB) return `${num(n / GB)}\u00a0ГБ`;
  if (n >= MB) return `${num(n / MB, 0)}\u00a0МБ`;
  if (n >= 1024) return `${num(n / 1024, 0)}\u00a0КБ`;
  return `${n}\u00a0Б`;
}

export const sourcesWord = (n: number) =>
  `${n} ${plural(n, 'источник', 'источника', 'источников')}`;
export const journalsWord = (n: number) => `${n} ${plural(n, 'журнал', 'журнала', 'журналов')}`;
export const linesWord = (n: number) => `${num(n, 0)} ${plural(n, 'строка', 'строки', 'строк')}`;
export const filesWord = (n: number) => `${n} ${plural(n, 'файл', 'файла', 'файлов')}`;
export const callsWord = (n: number) => `${num(n, 0)} ${plural(n, 'вызов', 'вызова', 'вызовов')}`;
export const defectsWord = (n: number) =>
  `${n} ${plural(n, 'расхождение', 'расхождения', 'расхождений')}`;

/** «канал/батч» → `{ channel, id }`; пересборка `rebuilds/<ts>` — тоже батч. */
export function splitBatch(batch: string): { channel: string; id: string } {
  const i = batch.indexOf('/');
  return i > 0
    ? { channel: batch.slice(0, i), id: batch.slice(i + 1) }
    : { channel: batch, id: '' };
}

/** «ExampleFilm · батч 09.10, 05:15» — канал названием, время по МСК. */
export function batchText(batch: string, name: (id: string) => string): string {
  const { channel, id } = splitBatch(batch);
  const when = dateTimeMsk(batchIdIso(id));
  return `${name(channel)} · ${when ? `батч ${when}` : 'батч'}`;
}

/** Батч из пути журнала `pipeline/<канал>/<батч>/RUN_EVENTS.jsonl`. */
export function journalBatch(rel: string): string | null {
  const m = /^pipeline\/([^/]+)\/([^/]+)\//.exec(rel);
  return m ? `${m[1]}/${m[2]}` : null;
}

/** «Opus», «Sonnet», «Haiku» — из id модели; иначе — как есть. */
export function modelName(model: string | null | undefined): string {
  const m = /(opus|sonnet|haiku)/i.exec(model ?? '');
  return m ? m[1]![0]!.toUpperCase() + m[1]!.slice(1).toLowerCase() : (model ?? '—');
}

export const tokensOf = (r: UsageRow) =>
  r.usage.input + r.usage.cache_write + r.usage.cache_read + r.usage.output;

export type StageSpend = {
  stage: string;
  title: string;
  total: number;
  calls: number;
  models: string[];
};

/** Расход по стадиям (по убыванию), модели стадии — словами. */
export function byStage(rows: UsageRow[]): StageSpend[] {
  const out = new Map<string, StageSpend>();
  for (const r of rows) {
    const id = r.stage ?? 'unknown';
    let s = out.get(id);
    if (!s) {
      s = {
        stage: id,
        title: r.stage ? stageName(r.stage) : 'Вне стадий',
        total: 0,
        calls: 0,
        models: [],
      };
      out.set(id, s);
    }
    s.total += tokensOf(r);
    s.calls += r.calls ?? 0;
    const m = modelName(r.model);
    if (!s.models.includes(m)) s.models.push(m);
  }
  return [...out.values()].sort((a, b) => b.total - a.total);
}

// ---------------------------------------------------------------- сравнение прогонов
const COUNT_LABEL: Record<string, string> = {
  'scripts (03)': 'Сценарии',
  'videos (05)': 'Ролики',
  'qc passed (05)': 'Прошли проверку',
  'verdicts (06)': 'Вердикты',
  'mp4 under videos/': 'Готовые файлы роликов',
};

export const countLabel = (key: string) => COUNT_LABEL[key] ?? key;

/** Расхождение прогона словами: «Стадия «Монтаж» прошла вручную, у исполнителя — нет». */
export function defectText(line: string): string {
  let m = /^stage (\S+): ran by hand, not by the executor/.exec(line);
  if (m) return `Стадия «${stageName(m[1])}» прошла вручную, у исполнителя её не было`;
  m = /^stage (\S+): ran by the executor, not by hand/.exec(line);
  if (m) return `Стадия «${stageName(m[1])}» прошла у исполнителя, вручную её не было`;
  m = /^stage (\S+): ran by hand, skipped by the plan/.exec(line);
  if (m) return `Стадию «${stageName(m[1])}» исполнитель пропустил по её условию — так и задумано`;
  if (/^order:/.test(line)) return 'Стадии шли в разном порядке';
  m = /^file \S+: (by hand only|executor only)/.exec(line);
  if (m)
    return m[1] === 'by hand only'
      ? 'Файл результата есть только у прогона вручную'
      : 'Файл результата есть только у исполнителя';
  return 'Расхождение — подробности в строке фабрики';
}

/** Сумма секунд «куда ушло время» прогона. */
export const wallSum = (w: Record<string, number>) => Object.values(w).reduce((a, s) => a + s, 0);

// ---------------------------------------------------------------- пул
const KEEP_WHY: Record<string, string> = {
  open_batch: 'идёт батч с этой темой',
  accepted_not_published: 'ролик принят, ещё не опубликован',
  rejected_not_withdrawn: 'ролик отклонён, но не снят',
  no_video: 'у темы ещё нет ролика',
};

export const keepWhy = (code: string) => KEEP_WHY[code] ?? 'тема ещё живая';

const TOPIC_STATUS: Record<string, string> = {
  published: 'ролик опубликован',
  withdrawn: 'ролик снят',
  ...KEEP_WHY,
};

/** Статус темы, что ссылается на источник, словами. */
export const topicStatus = (s: string) => TOPIC_STATUS[s] ?? 'тема закончена';

/** Правило-вариант пула словами (`pool_release.variants`). */
export function variantText(rule: string): string {
  let m = /^no_video older than (\d+) d$/.exec(rule);
  if (m) return `Темы без ролика старше ${m[1]} дней`;
  m = /^no_video\+rejected older than (\d+) d$/.exec(rule);
  if (m) return `Темы без ролика и отклонённые — старше ${m[1]} дней`;
  if (rule.startsWith('orphan: refused candidate of finished'))
    return 'Без хозяина: отвергнутые кандидаты законченных тем';
  m = /^orphan: refused candidate, last batch older than (\d+) d$/.exec(rule);
  if (m) return `Без хозяина: отвергнутые кандидаты, последний батч старше ${m[1]} дней`;
  if (rule.startsWith('orphan: untopiced')) return 'Без хозяина: футаж ранних батчей без темы';
  if (rule.startsWith('orphan: no batch'))
    return 'Без хозяина: ни один батч на диске о них не знает';
  if (rule === 'orphan: all') return 'Все источники без хозяина';
  return 'Другое правило';
}

/** «сентябрь 2026» из «2026-09». */
export function monthText(month: string): string {
  const d = new Date(`${month}-01T12:00:00Z`);
  if (Number.isNaN(d.getTime())) return month;
  return new Intl.DateTimeFormat('ru-RU', { month: 'long', year: 'numeric', timeZone: 'UTC' })
    .format(d)
    .replace(/\s*г\.$/, '');
}

/** Набрано ли «да» (регистр и пробелы по краям не в счёт). */
export const saidYes = (v: string) => v.trim().toLowerCase() === 'да';
