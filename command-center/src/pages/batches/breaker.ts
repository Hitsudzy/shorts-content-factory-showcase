// Размыкатель повторов (CF-0822 фабрики, CC-0152) словами. Если батч упал, не потратив квоту
// поиска, тик не запускает следующий батч этого канала в те же сутки квоты, пока код фабрики
// (HEAD корня и агентов) тот же. Новый код разрешает один повтор. Ручной запуск размыкатель не
// держит. Запись фабрики — `PlanBreaker` (день плана, канал, проверка ручного запуска); строка
// `repeat_held` журнала запусков — «тик не повторил», это не батч. Строка фабрики `line` —
// под «Подробнее».
import type { Launch } from '@/api/batches';
import type { Schemas } from '@/api/client';

import { dateTimeMsk } from './format';
import { batchIdIso } from './going';
import { stageName } from './stages';

export { BREAKER_TIP, breakerBadge } from './format';

export type PlanBreaker = Schemas['PlanBreaker'];

type Name = (id: string) => string;

const nbsp = (s: string) => s.replaceAll(' ', '\u00a0');

/** «10.10, 02:05 МСК» — время батча по его id (`<канал>/2026-10-09T2305Z`); null — не id. */
export function batchWhen(batch: string | null | undefined): string | null {
  const id = (batch ?? '').split('/').at(-1);
  const when = dateTimeMsk(batchIdIso(id));
  return when ? nbsp(`${when} МСК`) : null;
}

/** Стадия из «<стадия>: <причина>» (`failure`), если `stage` не пришла отдельно. */
const stageOf = (stage: string | null | undefined, failure: string | null | undefined) =>
  stage || (failure ? failure.split(':')[0]!.trim() : '') || null;

/** «батч 10.10, 02:05 МСК упал на «Поиск трендов»». */
function fellText(batch: string | null | undefined, stage: string | null) {
  const when = batchWhen(batch);
  return `батч${when ? ` ${when}` : ''} упал${stage ? ` на «${stageName(stage)}»` : ''}`;
}

/**
 * День плана под размыкателем (и плашка канала): «Повтор ExampleFilm придержан: батч 10.10,
 * 02:05 МСК упал на «Поиск трендов», не потратив квоту. Следующий запуск — после нового кода
 * или в новые сутки квоты, с 11.10, 10:00 МСК». Код сменился (`held: false`) — «…фабрика разрешит
 * один повтор».
 */
export function breakerText(b: PlanBreaker, name: Name = (id) => id): string {
  const who = name(b.channel);
  const fell = fellText(b.batch, stageOf(b.stage, b.failure));
  if (!b.held)
    return `Батч ${who}: ${fell}, не потратив квоту, но код с тех пор сменился\u00a0— фабрика разрешит один повтор`;
  const until = dateTimeMsk(b.until);
  const next = until
    ? `после нового кода или в новые сутки квоты, с ${nbsp(`${until} МСК`)}`
    : 'после нового кода или в новые сутки квоты';
  return `Повтор ${who} придержан: ${fell}, не потратив квоту. Следующий запуск\u00a0— ${next}`;
}

/** Пометка проверки ручного запуска: размыкатель держит тик, но не кнопку. */
export function manualBreakerText(b: PlanBreaker, name: Name = (id) => id): string {
  const fell = fellText(b.batch, stageOf(b.stage, b.failure));
  return b.held
    ? `Фабрика сама не повторит ${name(b.channel)} в эти сутки квоты: ${fell}, не потратив квоту, код тот же. Ручной запуск защита от повтора не останавливает\u00a0— батч стартует`
    : `${name(b.channel)}: ${fell}, не потратив квоту; код сменился\u00a0— фабрика разрешит один повтор. Ручной запуск защита от повтора не останавливает`;
}

/** Строка журнала запусков «тик не повторил» (`kind: repeat_held`) — не батч. */
export const isHeldLaunch = (l: Pick<Launch, 'kind'> | null | undefined) =>
  l?.kind === 'repeat_held';

/** «Фабрика не повторила батч 07.10, 05:00 МСК: он упал на «Поиск трендов», не потратив квоту, код тот же». */
export function heldLaunchText(l: Launch): string {
  const when = batchWhen(l.failed_batch);
  const stage = stageOf(null, l.failure);
  return (
    `Фабрика не повторила батч${when ? ` ${when}` : ''}: он упал` +
    `${stage ? ` на «${stageName(stage)}»` : ''}, не потратив квоту, код тот же. Батча не было`
  );
}
