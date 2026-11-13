// Бюджет поиска суток квоты и второй батч (CF-0830 фабрики, CC-0152) словами. Квота поиска
// YouTube — одна на все каналы; канал с несколькими окнами (`windows`) может взять следующий
// батч в сутки квоты, где батч уже есть, если потрачено + ожидаемое у канала не больше
// «лимит − запас» и батчей в эти сутки меньше потолка. Запись допуска (`BudgetAdmission`) —
// причина словами; строка фабрики `why` — под «Подробнее».
import type { Schemas } from '@/api/client';
import type { Tone } from '@/components/common/Status';

import { dateTimeMsk, plural, timeMsk } from './format';
import { batchIdIso, batchesInText } from './going';

export type BudgetAdmission = Schemas['BudgetAdmission'];
export type QuotaBudget = Schemas['QuotaBudget'];
export type QuotaBudgetDay = Schemas['QuotaBudgetDay'];

export const searchesWord = (n: number) => `${n} ${plural(n, 'поиск', 'поиска', 'поисков')}`;
export const batchesWord = (n: number) => `${n} ${plural(n, 'батч', 'батча', 'батчей')}`;

/** Подсказка блока бюджета: квота общая на все каналы. */
export const BUDGET_TIP =
  'Квота поиска YouTube общая на все каналы: 100 поисков в сутки квоты. Обычно её хватает на один ' +
  'батч. Второй батч в те же сутки фабрика запускает только каналу с несколькими окнами и только ' +
  'если потраченное плюс ожидаемое у канала не больше лимита минус запас';

/** Причина допуска одним словосочетанием. */
export const ADMISSION_REASON: Record<BudgetAdmission['reason'], { label: string; tone: Tone }> = {
  ok: { label: 'допущен по бюджету', tone: 'ok' },
  budget: { label: 'не хватит бюджета поиска', tone: 'warn' },
  max_batches: { label: 'лимит батчей в сутки', tone: 'idle' },
  busy: { label: 'занято другим батчем', tone: 'idle' },
};

/**
 * Допуск словами: причина и короткий расчёт. «допущен по бюджету: потрачено 64 + ожидается 18 =
 * 82 из 95»; «не хватит бюджета поиска: потрачено 82 + ожидается 18 = 100, а можно не больше 95»; «лимит
 * батчей в сутки: уже 2 из 2»; «занято другим батчем: окно пройдёт, пока он идёт (до 10:12 МСК)».
 */
export function admissionText(a: BudgetAdmission): string {
  const label = ADMISSION_REASON[a.reason]?.label ?? 'допуск неизвестен';
  const cap = a.limit - a.margin;
  const sum = `потрачено ${a.spent} + ожидается ${a.expected} = ${a.after}`;
  switch (a.reason) {
    case 'ok':
      return `${label}: ${sum} из ${cap}`;
    case 'budget':
      return `${label}: ${sum}, а можно не больше ${cap}`;
    case 'max_batches':
      return `${label}: уже ${a.batches} из ${a.max_batches}`;
    case 'busy': {
      const end = timeMsk(a.start);
      return `${label}: окно пройдёт, пока он идёт${end ? ` (до\u00a0${end}\u00a0МСК)` : ''}`;
    }
    default:
      return label;
  }
}

/**
 * Блок бюджета суток квоты: лимит, потрачено, осталось, батчи — строками. «Осталось» — то, чем
 * решает допуск: лимит − запас − потрачено (не меньше 0), и в скобках всего до лимита.
 */
export function budgetLines(t: QuotaBudgetDay): {
  limit: string;
  spent: string;
  left: string;
  batches: string;
} {
  const unrecorded = t.spent - t.spent_recorded;
  return {
    limit: `${searchesWord(t.limit)}, из них ${t.margin} в запасе`,
    spent: unrecorded
      ? `${t.spent}: записано ${t.spent_recorded} + ожидается ${unrecorded} у ${
          t.unrecorded?.length === 1
            ? 'батча без записи'
            : `${t.unrecorded?.length ?? 0} ${plural(t.unrecorded?.length ?? 0, 'батча', 'батчей', 'батчей')} без записи`
        }`
      : `${t.spent}`,
    left: `${Math.max(0, t.limit - t.margin - t.spent)} до запаса (всего ${Math.max(0, t.left)})`,
    batches: `${t.batches} из ${t.max_batches}`,
  };
}

/** Батч суток квоты из строк `held` фабрики: канал, начало (ISO) и кто запустил. */
export type HeldBatch = {
  channel: string;
  at: string | null;
  by: 'tick' | 'manual' | null;
};

/** Кто запустил батч суток — словами (как `launchedBy`: `tick` — таймер расписания). */
export const HELD_BY: Record<NonNullable<HeldBatch['by']>, string> = {
  tick: 'запустило расписание',
  manual: 'запуск вручную',
};

/** «example-film 2026-10-09T2305Z (pipeline/runs.jsonl)», «example-film 2026-10-09T2305Z (pipeline/)». */
const HELD_BATCH = /^([a-z][a-z0-9_-]*)[ /](\d{4}-\d{2}-\d{2}T\d{4}Z)(?:\s|$)/;
/** «example-film запущен тиком 2026-10-21T08:37:02Z (schedule/launches.jsonl)»; «… вручную (центр) …». */
const HELD_LAUNCH = /^(\S+) запущен (тиком|вручную)(?: \([^)]*\))? (\S+)/;
/** Строка запуска и папка батча — один батч, если их время ближе этого. */
const PAIR_MS = 15 * 60_000;

const msOf = (iso: string | null) => {
  const t = iso ? Date.parse(iso) : NaN;
  return Number.isNaN(t) ? null : t;
};

/**
 * Строки `held` фабрики — батчами. Строку журнала запусков («запущен тиком …») фабрика пишет рядом
 * со строкой папки того же батча, так что «кто запустил» приклеивается к батчу канала с ближайшим
 * временем; запуск без папки — отдельный батч. Нераспознанная строка остаётся строкой.
 */
export function heldBatches(held: readonly string[]): (HeldBatch | string)[] {
  const out: (HeldBatch | string)[] = [];
  const launches: HeldBatch[] = [];
  for (const line of held) {
    const b = HELD_BATCH.exec(line);
    if (b) {
      out.push({ channel: b[1]!, at: batchIdIso(b[2]!), by: null });
      continue;
    }
    const l = HELD_LAUNCH.exec(line);
    if (l) {
      const at = l[3]!;
      launches.push({
        channel: l[1]!,
        at: msOf(at) == null ? null : at,
        by: l[2] === 'тиком' ? 'tick' : 'manual',
      });
      continue;
    }
    out.push(line);
  }
  for (const l of launches) {
    const t = msOf(l.at);
    let best: HeldBatch | null = null;
    let gap = Infinity;
    for (const x of out) {
      if (typeof x === 'string' || x.channel !== l.channel || x.by) continue;
      const d = t == null ? 0 : Math.abs((msOf(x.at) ?? Infinity) - t);
      if (d <= PAIR_MS && d < gap) {
        best = x;
        gap = d;
      }
    }
    if (best) best.by = l.by;
    else out.push(l);
  }
  return out;
}

/** Батч суток одной строкой: «ExampleFilm · 21.10, 11:37 — запустило расписание». */
export function heldText(h: HeldBatch | string, name: (id: string) => string): string {
  if (typeof h === 'string')
    return batchesInText(h.replace(/\s*\([^)]*\)\s*$/, ''), name).replace(/ · батч /g, ' · ');
  const when = dateTimeMsk(h.at);
  return `${name(h.channel)}${when ? ` · ${when}` : ''}${h.by ? ` — ${HELD_BY[h.by]}` : ''}`;
}
