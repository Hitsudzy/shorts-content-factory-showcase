// Исполнитель батча не отвечает (CC-0094): батч `running`, а исполнителя нет в живых — он умер,
// не записав конца (перезагрузка ноутбука, kill -9, сбой). С CC-0110 фабрика говорит это сама в
// каждой строке `GET /api/batches` (`executor_alive`, `lock_held`, `executor_why` — по последнему
// скану): центр больше не спрашивает `resume/plan` в фоне (CC-0115), а читает эти поля.
import type { ResumePlan } from '@/api/batchActions';
import type { GoingBatch } from '@/api/batches';

import { spanText } from './going';

const ms = (ts: string | null | undefined): number | null => {
  if (!ts) return null;
  const t = Date.parse(ts);
  return Number.isNaN(t) ? null : t;
};

/** Что известно об исполнителе: поля строки списка или ответ `resume` (у него те же поля). */
export type ExecutorCheck = {
  status?: GoingBatch['status'];
  executor_alive?: boolean | null;
  lock_held?: boolean | null;
};

/**
 * Исполнитель не отвечает: фабрика сказала «не жив» (не null — null значит «проверка упала»),
 * его замок никто не держит, батч всё ещё `running`.
 */
export function executorGone(b: ExecutorCheck | null | undefined): boolean {
  return !!b && b.executor_alive === false && b.lock_held !== true && b.status === 'running';
}

/** Ответ `resume` как проверка исполнителя (после «Продолжить» — он новее строки списка). */
export const answerCheck = (
  r: Pick<ResumePlan, 'executor_alive' | 'lock_held' | 'status'>,
): ExecutorCheck => ({
  executor_alive: r.executor_alive,
  lock_held: r.lock_held,
  status: r.status ?? null,
});

/** Причина словами, когда фабрика своей строки не дала (замок никто не держит). */
export const GONE_REASON =
  'Исполнитель остановился, не записав конца (перезагрузка или сбой): готовое сохранено, продолжить можно с места остановки';

/** «последнее событие 7 мин назад» по часам фабрики; null — не сказать. */
export function eventAgeText(
  lastEvent: string | null | undefined,
  asOf: string | null | undefined,
): string | null {
  const last = ms(lastEvent);
  const now = ms(asOf);
  if (last == null || now == null) return null;
  return `последнее событие ${spanText(Math.max(0, (now - last) / 1000))} назад`;
}

/** Статус батча, чей исполнитель не отвечает, — одним словом (как `batchStatus`). */
export const GONE_STATUS = {
  label: 'исполнитель не отвечает',
  tone: 'danger',
  tip: 'Исполнителя батча нет в живых, а конца он не записал (перезагрузка или сбой): батч стоит, готовое сохранено, продолжить можно с места остановки',
} as const;

/** Заголовок блока «почему стоит» для такого батча. */
export const GONE_TITLE = 'Исполнитель не отвечает — батч стоит';
