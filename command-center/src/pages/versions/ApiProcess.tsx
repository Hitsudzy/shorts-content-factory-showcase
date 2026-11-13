// Полоса «процесс API» экрана «Версии и агенты» (CC-0155): когда запущен cc-api и не отстал ли он
// от кода фабрики. Читает `GET /api/version` (тот же запрос, что шапка и главная). Отстал —
// предупреждение тоном «внимание» и что сделать; на текущем коде или не сверить — тихой строкой.
// Коммиты и изменённые файлы — только под «Подробнее».
import { useVersion } from '@/api/hooks';
import { More } from '@/components/common/More';

import {
  apiFreshness,
  apiStartedText,
  FRESH_TEXT,
  shortCommit,
  STALE_ACTION,
  STALE_TITLE,
  UNKNOWN_TEXT,
} from './apiProcessText';
import { DRIFT_STYLE } from './format';

export function ApiProcess() {
  const q = useVersion();
  if (!q.data) return null;
  const v = q.data;
  const state = apiFreshness(v);
  if (!state) return null;
  // Время запуска — на виду; под «Подробнее» — только коммиты и файлы, без повтора времени.
  const started = apiStartedText(v, { commit: false });
  const atStart = shortCommit(v.commit_at_start);
  const now = shortCommit(v.factory.commit);

  if (state === 'stale') {
    const paths = v.stale_paths ?? [];
    return (
      <div
        role="status"
        className="grid gap-2 rounded-lg border border-l-[3px] px-4 py-3 text-[13px]"
        style={DRIFT_STYLE}
        data-testid="versions-api-process"
        data-state="stale"
      >
        {/* Длинный заголовок переносится, а точка остаётся в его первой строке — как у полосы
            «Агенты расходятся с пинами» (там заголовок короткий и помещается рядом с точкой). */}
        <div>
          <span
            aria-hidden
            className="relative -top-px mr-2 inline-block size-[7px] rounded-full bg-warning align-middle"
          />
          <b className="font-semibold">{STALE_TITLE}</b>{' '}
          <span className="ml-1 text-muted-foreground">{STALE_ACTION}</span>
        </div>
        {started ? <span className="text-xs text-muted-foreground">{started}</span> : null}
        <More className="mt-0" label="Подробнее: что изменилось">
          {atStart ? <span>на коммите {atStart}</span> : null}
          {now ? <span>сейчас у фабрики: {now}</span> : null}
          {paths.length ? (
            <>
              <span>изменился код:</span>
              {paths.map((p) => (
                <span key={p} data-testid="versions-api-stale-path">
                  {p}
                </span>
              ))}
            </>
          ) : null}
        </More>
      </div>
    );
  }

  return (
    <div
      className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-lg border px-4 py-2 text-xs text-muted-foreground"
      data-testid="versions-api-process"
      data-state={state}
    >
      <span
        aria-hidden
        className={`size-[7px] rounded-full ${state === 'fresh' ? 'bg-success' : 'bg-muted-foreground/50'}`}
      />
      <span>
        {started ?? 'API запущен'} · {state === 'fresh' ? FRESH_TEXT : UNKNOWN_TEXT}
      </span>
      {atStart ? (
        <More className="mt-0 basis-full">
          <span>на коммите {atStart}</span>
          {now ? <span>сейчас у фабрики: {now}</span> : null}
        </More>
      ) : null}
    </div>
  );
}
