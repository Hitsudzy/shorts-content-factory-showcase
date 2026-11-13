// Видимость «Прочитать Studio» по хуку (CC-0120) — одна на все места; кнопка в шапке (CC-0151)
// берёт её же, условие не повторяется.
import { useState } from 'react';

import { useStudioDue, type StudioHook, type StudioReadDue } from '@/api/studioRead';

export type Run = { id: string; pollS: number | null };

export type StudioDueState = {
  /** Ответ хука, пока блок виден («пора», идёт чтение, итог не скрыт); иначе `null`. */
  due: StudioReadDue | null;
  run: Run | null;
  setRun: (run: Run | null) => void;
};

/**
 * Видимость блока «Прочитать Studio» по хуку — одна на все места (полоса в «Публикации», окно
 * запуска, кнопка в шапке, CC-0151): виден, когда хук говорит «пора», пока идёт чтение и пока
 * не скрыт его итог. `enabled` false — хук не спрашивать. Ошибка хука — тихо: блока нет.
 */
export function useStudioDueState(
  hook: StudioHook,
  { channel = null, enabled = true }: { channel?: string | null; enabled?: boolean } = {},
): StudioDueState {
  const q = useStudioDue(hook, { channel, enabled });
  const [run, setRun] = useState<Run | null>(null);
  const due = q.data;
  const running = due?.running ?? null;
  // Сессия идёт (запущена в другом месте центра) — держим её у себя, чтобы итог не пропал,
  // когда «пора» погаснет (состояние правится при отрисовке, без эффекта).
  if (running && !run) setRun({ id: running, pollS: null });
  return { due: due && (due.due || !!due.running || !!run) ? due : null, run, setRun };
}

/** Слово повода хука («первое открытие центра за день») или `null`. */
export function hookWordOf(due: StudioReadDue): string | null {
  return due.hook ? (due.hook_words[due.hook] ?? null) : null;
}
