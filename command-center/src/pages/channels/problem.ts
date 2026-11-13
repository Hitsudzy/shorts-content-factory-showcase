// Отказ или итог проверки в одном виде для панели «Что сказала фабрика».
import { ChannelError, type CheckLine } from '@/api/channels';

export type Problem = {
  tone: 'danger' | 'warn' | 'ok';
  title: string;
  message?: string | null;
  errors: readonly CheckLine[];
  details: readonly string[];
  /** Код отказа фабрики (`conflict`, `batch_running`, …), если это отказ. */
  code?: string;
};

/**
 * Отказ 409 `batch_running` на записи. Чтения (карточка, список, шаблон) говорят о батчах по
 * прошлому скану фабрики, а запись сканирует заново — так «открыто» на экране может
 * кончиться этим отказом. Объясняем, что случилось и что ничего не потеряно.
 */
export const BATCH_STARTED =
  'Экран показывал «открыто» по прошлой проверке батчей, а при записи фабрика проверила заново и нашла идущий батч. Ничего не записано, ваши правки на месте — повторите, когда батч закончится.';

export function problemOf(e: unknown, title: string): Problem {
  if (e instanceof ChannelError && e.problem) {
    const batch = e.problem.code === 'batch_running';
    return {
      tone: batch || e.problem.code === 'conflict' ? 'warn' : 'danger',
      title: batch ? `${title}: идёт батч` : title,
      code: e.problem.code,
      message: batch ? `${e.problem.message} ${BATCH_STARTED}` : e.problem.message,
      errors: e.problem.errors,
      details: [
        `код: ${e.problem.code}`,
        ...e.problem.details,
        ...e.problem.batches.map((b) => `батч: ${b.dir}`),
      ],
    };
  }
  return {
    tone: 'danger',
    title,
    message: 'Фабрика не ответила как положено. Попробуйте ещё раз чуть позже.',
    errors: [],
    details: [e instanceof Error ? e.message : String(e)],
  };
}
