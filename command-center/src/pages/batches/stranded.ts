// Упавшие батчи (CC-0089, `GET /api/batches/stranded`): слова строки и ссылки из отказа защиты
// запуска на батч. Строку причины фабрика пишет для себя («step 0 (runlog batch-start) exited
// 2; log …»): узнаваемые — словами, русская — как есть без путей, остальное — общими словами;
// сама строка — только под «подробнее».
import type { LaunchGuard } from '@/api/batchActions';
import { strandedBatch, type GoingBatch, type StrandedBatch } from '@/api/batches';
import { humanReason } from '@/api/humanText';

import { dateTimeMsk } from './format';
import { stageName } from './stages';

/** Якорь карточки батча на экране «Батчи» — сюда ведут ссылки из окна запуска. */
export const batchAnchor = (batch: string) => `batch-${batch.replace(/[^a-zA-Z0-9]/g, '-')}`;

/** Как батч встал — по `status` run-state. */
export function strandedVerb(status: string | null | undefined) {
  if (status === 'failed') return { eyebrow: 'Батч упал', verb: 'Упал' };
  if (status === 'stopped') return { eyebrow: 'Батч остановлен', verb: 'Остановлен' };
  return { eyebrow: 'Батч встал', verb: 'Встал' };
}

/** Причина остановки словами (сырая строка — под «подробнее»). */
export function strandedReasonText(reason: string | null | undefined): string {
  const r = reason?.trim();
  if (!r) return 'причину фабрика не записала';
  if (/^step \d+ \(.*\) exited -?\d+/.test(r))
    return 'команда стадии завершилась с ошибкой — что именно, видно в журнале стадии';
  if (/timed? ?out|timeout/i.test(r)) return 'стадия не уложилась в отведённое ей время';
  const after = r.match(/^after failed stage (\S+)/);
  if (after) return `стадия пропущена: до неё упала стадия «${stageName(after[1])}»`;
  if (/killed|SIG(TERM|KILL)|signal/i.test(r)) return 'процесс стадии остановлен сигналом';
  if (/[а-яё]/i.test(r)) return humanReason(r);
  return 'фабрика записала причину по-своему — она под «подробнее», детали — в журнале стадии';
}

/** «Упал на стадии «Старт батча» — команда стадии завершилась с ошибкой…» */
export function strandedHeadline(row: Pick<StrandedBatch, 'status' | 'stage' | 'reason'>) {
  const { verb } = strandedVerb(row.status);
  const where = row.stage
    ? `${verb} на стадии «${stageName(row.stage)}»`
    : `${verb} до первой стадии`;
  return `${where} — ${strandedReasonText(row.reason)}`;
}

export type GuardLink =
  | { batch: string; kind: 'stranded'; row: StrandedBatch }
  | { batch: string; kind: 'open'; going: GoingBatch }
  | { batch: string; kind: 'unknown' };

/**
 * На какие батчи ссылается отказ защиты запуска — `batches` защиты (у `today` фабрика называет
 * их сама, CF-0724; запасного пути по `holds_day` больше нет). Пройденная защита — ни на что.
 */
export function guardLinks(
  g: Pick<LaunchGuard, 'name' | 'ok' | 'batches'>,
  stranded: readonly StrandedBatch[],
  going: readonly GoingBatch[],
): GuardLink[] {
  if (g.ok) return [];
  const named = g.batches ?? [];
  return [...new Set(named)].map((batch): GuardLink => {
    const row = stranded.find((r) => strandedBatch(r) === batch);
    if (row) return { batch, kind: 'stranded', row };
    const open = going.find((b) => b.batch === batch);
    if (open) return { batch, kind: 'open', going: open };
    return { batch, kind: 'unknown' };
  });
}

/** Когда был батч, к которому ведёт ссылка: начат (идущий) или создан (упавший). */
export function linkWhen(l: GuardLink | undefined): string | null {
  if (l?.kind === 'stranded') return dateTimeMsk(l.row.created);
  if (l?.kind === 'open') return dateTimeMsk(l.going.started);
  return null;
}

/** Защиты, которые центр говорит своими словами; строка фабрики — под «подробнее». */
const KNOWN_GUARDS = new Set(['today', 'open']);
export const isKnownGuard = (name: string) => KNOWN_GUARDS.has(name);

/**
 * Строка защиты запуска для основного вида. `today` и `open` — словами центра, с датой батча, к
 * которому ведёт ссылка (строку фабрики центр не разбирает); остальные — строка фабрики без
 * путей и кодов, даты словами (`humanReason`).
 */
export function guardText(
  g: Pick<LaunchGuard, 'name' | 'ok' | 'line'>,
  links: readonly GuardLink[] = [],
): string {
  const when = linkWhen(links[0]);
  if (g.name === 'today')
    return g.ok
      ? 'Сегодня батча канала ещё не было'
      : `Сегодня батч канала уже был${when ? ` (${when})` : ''} — в сутки разрешён один`;
  if (g.name === 'open')
    return g.ok
      ? 'Открытых батчей у канала нет'
      : `У канала уже открыт батч${when ? ` (начат ${when})` : ''} — второй не запустить, пока он не закроется`;
  return humanReason(g.line);
}
