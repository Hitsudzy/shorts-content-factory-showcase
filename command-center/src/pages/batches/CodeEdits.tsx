// Стадия батча изменила код фабрики (CC-0111, CF-0713): исполнитель сравнивает репозитории до и
// после LLM-стадии и пишет, что она поменяла (`run-state.json code_edits[]`, событие
// `stage_code_edit`). Пока правка не разобрана, следующий `runlog batch-start` откажет: дерево
// фабрики грязное (CF-0479). Экран батча — заметное предупреждение со стадией словами и файлами
// плашками кода; список «Батчи» и главная — пометка по `code_edits_count`. Строка фабрики,
// источник, задача и коммиты — под «Подробнее».
import { useBatch, type GoingBatch } from '@/api/batches';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';

import {
  CODE_EDITS_CONSEQUENCE,
  CODE_EDITS_TIP,
  editFiles,
  editHead,
  type StageCodeEdit,
} from './codeEditsText';
import { dateTimeMsk, plural } from './format';

/** Пометка списка «Батчи» и главной: `code_edits_count > 0`. */
export function CodeEditsMark({ count }: { count: number | null | undefined }) {
  if (!count) return null;
  return (
    <span data-testid="code-edits-mark">
      <StatusBadge tone="danger" tip={CODE_EDITS_TIP}>
        {count > 1 ? `правки кода:\u00a0${count}` : 'правка кода'}
      </StatusBadge>
    </span>
  );
}

const SOURCE: Record<StageCodeEdit['source'], string> = {
  state: 'из файла состояния (run-state.json code_edits)',
  events: 'из журнала событий (stage_code_edit)',
};

const short = (sha: string | null | undefined) => (sha ? sha.slice(0, 10) : '—');

function Files({ files }: { files: string[] }) {
  if (!files.length) return null;
  return (
    <ul
      className="m-0 mt-1 flex list-none flex-wrap gap-1 p-0"
      aria-label="Изменённые файлы"
      data-testid="code-edit-files"
    >
      {files.map((f) => (
        <li key={f} className="min-w-0">
          <code
            data-testid="code-edit-file"
            className="inline-block max-w-full rounded-sm border bg-background px-1.5 py-0.5 font-mono text-[12px] [overflow-wrap:anywhere]"
          >
            {f}
          </code>
        </li>
      ))}
    </ul>
  );
}

/**
 * Предупреждение на экране батча: строки `BatchDetail.code_edits`; пока подробности не пришли —
 * по строкам списка (`GoingBatch.code_edits`), их текст — под «Подробнее».
 */
export function CodeEditsWarning({
  b,
}: {
  b: Pick<GoingBatch, 'batch' | 'code_edits' | 'code_edits_count'>;
}) {
  const detail = useBatch(b.batch).data;
  const rows = detail?.code_edits ?? [];
  const lines = b.code_edits ?? [];
  if (!rows.length && !lines.length && !b.code_edits_count) return null;
  const n = rows.length || b.code_edits_count || lines.length;
  return (
    <section
      role="alert"
      aria-label="Стадия изменила код фабрики"
      data-testid="code-edits"
      className="mt-3 grid gap-2 rounded-sm border border-[color-mix(in_srgb,var(--danger)_45%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_8%,var(--card))] p-2.5 text-[13px]"
    >
      {rows.length ? (
        <ul className="m-0 grid list-none gap-2 p-0">
          {rows.map((e, i) => {
            const when = dateTimeMsk(e.at);
            return (
              <li
                key={`${e.run ?? e.stage ?? ''}-${i}`}
                data-testid="code-edit"
                data-stage={e.stage}
              >
                <b className="font-semibold">{editHead(e)}:</b>
                {when ? <span className="ml-1 text-xs text-muted-foreground">{when}</span> : null}
                <Files files={editFiles(e)} />
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="m-0" data-testid="code-edit">
          <b className="font-semibold">
            {n > 1
              ? `Стадии батча меняли код фабрики: ${n}\u00a0${plural(n, 'раз', 'раза', 'раз')}`
              : 'Стадия батча изменила код фабрики'}
          </b>
        </p>
      )}
      <p className="m-0" data-testid="code-edits-consequence">
        {CODE_EDITS_CONSEQUENCE}
      </p>
      <More className="mt-0">
        {rows.map((e, i) => (
          <span key={`d-${i}`} className="grid gap-0.5">
            <span>
              {[e.stage, e.run, e.task, e.mode ? `режим ${e.mode}` : null, e.at]
                .filter(Boolean)
                .join(' · ')}
            </span>
            {e.line ? <span>строка фабрики: {e.line}</span> : null}
            <span>источник: {SOURCE[e.source] ?? e.source}</span>
            {e.edits
              .filter((r) => r.head_was || r.head_now)
              .map((r, j) => (
                <span key={j}>
                  {r.repo ?? 'репозиторий'}: коммит {short(r.head_was)} → {short(r.head_now)}
                </span>
              ))}
            {typeof e.note === 'string' && e.note ? <span>{e.note}</span> : null}
          </span>
        ))}
        {!rows.length ? lines.map((l, i) => <span key={`l-${i}`}>{l}</span>) : null}
      </More>
    </section>
  );
}
