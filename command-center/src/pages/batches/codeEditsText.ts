// Слова правки кода стадией (CC-0111, CF-0713): что будет дальше, имя стадии, файлы от корня
// фабрики. Экран — CodeEdits.tsx.
import type { BatchDetail } from '@/api/batches';

import { stageTitle } from './stages';
import { nameOf } from './words';

export type StageCodeEdit = BatchDetail['code_edits'][number];

/** Что будет дальше — смысл правила фабрики (stage_code_guard, CF-0713 → batch-start CF-0479). */
export const CODE_EDITS_CONSEQUENCE =
  'Следующий батч не запустится, пока правку не закоммитят или не откатят. Этот прогон фабрика не останавливает, только предупреждает.';

export const CODE_EDITS_TIP =
  'Стадия батча изменила код фабрики. Пока правку не закоммитят или не откатят, следующий батч не запустится — подробности на экране «Батчи».';

/** Файлы правки от корня фабрики: `files`, иначе собранные из `edits` (`agents/<имя>/<файл>`). */
export function editFiles(e: StageCodeEdit): string[] {
  if (e.files.length) return e.files;
  return e.edits.flatMap((r) =>
    r.files.map((f) => (r.repo && r.repo !== 'root' ? `${r.repo}/${f}` : f)),
  );
}

/**
 * Стадия словами — одно правило: имя стадии плана и в скобках кадр киноленты, где она стоит
 * (тот же `stageTitle`, что и у ленты): «Стадия «Разметка футажа» (кадр «Футаж») изменила код
 * фабрики». Имя совпадает с кадром («Монтаж») — без скобок.
 */
export function editHead(e: StageCodeEdit): string {
  if (!e.stage) return 'Стадия батча изменила код фабрики';
  const name = nameOf(e.stage);
  const frame = stageTitle(e.stage);
  const where = frame && frame !== name ? ` (кадр «${frame}»)` : '';
  return `Стадия «${name}»${where} изменила код фабрики`;
}
