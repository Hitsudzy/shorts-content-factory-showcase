// «Разнообразие ленты» на «Статистике» (CC-0115 → CC-0108, `GET /api/analytics/diversity`):
// у последних 10 принятых роликов канала (или всей фабрики, или всей ленты целиком) — доля
// каждого вида факта, схемы сценария, ритма монтажа и первой фразы. Значения — словами
// (`styleValue`), сырые — под «подробнее» вместе со строками фабрики и слагами роликов. Журнал
// приёмки битый (`log_error`) — «журнал приёмки не читается», лента пуста.
import { useState } from 'react';

import { BatchError } from '@/api/batchProblem';
import {
  DIVERSITY_LAST,
  useDiversity,
  type DiversityAxis,
  type FeedDiversity,
} from '@/api/diversity';
import { Card, CardHead, Keep } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { Pending } from '@/components/common/Skeletons';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { plural } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';

import { DIMENSION, styleValue } from './format';

const pct = (share: number) => `${Math.round(share * 100)} %`;
const videos = (n: number) => `${n} ${plural(n, 'ролик', 'ролика', 'роликов')}`;

function Axis({ a, n }: { a: DiversityAxis; n: number }) {
  const dim = DIMENSION[a.key];
  return (
    <section
      data-testid="diversity-axis"
      data-axis={a.key}
      className="grid min-w-0 content-start gap-1.5"
    >
      <h3 className="m-0 text-[13px] font-semibold">
        {dim ? (
          <Tip content={dim.tip}>
            <span tabIndex={0} className="underline decoration-dotted underline-offset-4">
              {dim.label}
            </span>
          </Tip>
        ) : (
          a.label
        )}
      </h3>
      {a.values.length ? (
        <ul className="m-0 grid list-none gap-1 p-0">
          {a.values.map((v) => {
            const raw = String(v.value ?? 'unknown');
            return (
              <li key={raw} data-testid="diversity-value" data-value={raw}>
                <Tip content={`${v.count} из ${videos(n)}`}>
                  <span
                    tabIndex={0}
                    className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-2 gap-y-0.5 rounded-sm text-[13px] outline-offset-2"
                  >
                    <span className="min-w-0 truncate">{styleValue(raw)}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {v.count} · {pct(v.share)}
                    </span>
                    <span aria-hidden className="col-span-2 h-1.5 rounded-sm bg-muted">
                      <span
                        className="block h-full rounded-sm bg-primary"
                        style={{ width: `${Math.max(2, Math.round(v.share * 100))}%` }}
                      />
                    </span>
                  </span>
                </Tip>
              </li>
            );
          })}
        </ul>
      ) : (
        <p className="m-0 text-[13px] text-muted-foreground">—</p>
      )}
    </section>
  );
}

function Body({ d }: { d: FeedDiversity }) {
  if (d.log_error)
    return (
      <div
        role="alert"
        data-testid="diversity-log-error"
        className="grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-3 text-[13px]"
      >
        <div className="font-semibold text-danger">Журнал приёмки не читается</div>
        <p className="m-0">
          Файл, где фабрика записывает принятые ролики, есть, но битый — разнообразие считать не по
          чему. Попросите оператора его починить; что не так — под «подробнее».
        </p>
      </div>
    );
  if (!d.n)
    return (
      <EmptyState title="Принятых роликов пока нет">
        {d.log_exists
          ? 'Разнообразие появится, когда вы примете первые ролики.'
          : 'Журнала приёмки ещё нет — он появится с первым принятым роликом.'}
      </EmptyState>
    );
  return (
    <>
      {d.read_live.length ? (
        <Tip content="Профиль ролика (вид факта, схема, ритм) ещё не записан — фабрика прочитала его из батча сейчас, ничего не записывая.">
          <p
            tabIndex={0}
            data-testid="diversity-live"
            className="m-0 mb-3 w-max max-w-full text-[13px] text-muted-foreground underline decoration-dotted underline-offset-4"
          >
            У {d.read_live.length} {plural(d.read_live.length, 'ролика', 'роликов', 'роликов')}{' '}
            профиль прочитан из батча
          </p>
        </Tip>
      ) : null}
      <div className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4">
        {d.axes.map((a) => (
          <Axis key={a.key} a={a} n={d.n} />
        ))}
      </div>
    </>
  );
}

/** Переключатель из двух вариантов: выбранный подсвечен всегда, и по умолчанию тоже. */
function Segmented({
  label,
  value,
  options,
  onPick,
}: {
  label: string;
  value: boolean;
  options: { on: boolean; text: string; tip: string; testId: string }[];
  onPick: (v: boolean) => void;
}) {
  return (
    <div role="group" aria-label={label} className="flex gap-0.5 rounded-lg border bg-card p-0.5">
      {options.map((o) => (
        <Tip key={o.testId} content={o.tip}>
          <button
            type="button"
            aria-pressed={value === o.on}
            data-testid={o.testId}
            onClick={() => onPick(o.on)}
            className={cn(
              'rounded-sm px-2.5 py-1 text-xs whitespace-nowrap text-muted-foreground',
              value === o.on && 'bg-muted font-semibold text-foreground',
            )}
          >
            {o.text}
          </button>
        </Tip>
      ))}
    </div>
  );
}

function DiversitySkeleton() {
  return (
    <Pending
      label="Считаю разнообразие ленты…"
      className="grid gap-x-6 gap-y-4 sm:grid-cols-2 xl:grid-cols-4"
    >
      {Array.from({ length: 4 }, (_, i) => (
        <span key={i} className="grid content-start gap-2">
          <Skeleton className="h-3.5 w-28" />
          {Array.from({ length: 3 }, (_, j) => (
            <span key={j} className="grid gap-1">
              <Skeleton className="h-3 w-3/4" />
              <Skeleton className="h-1.5 w-full" />
            </span>
          ))}
        </span>
      ))}
    </Pending>
  );
}

export function Diversity({ channel }: { channel: string }) {
  const name = useChannelNames();
  const [all, setAll] = useState(false);
  const [whole, setWhole] = useState(false);
  const q = useDiversity(all ? null : channel, whole ? 0 : DIVERSITY_LAST);
  const n = q.data?.n;
  const scope = all ? 'вся фабрика' : name(channel);
  const eyebrow = (
    <>
      Принятые ролики · {all ? scope : <Keep>{scope}</Keep>} ·{' '}
      {whole ? 'вся лента' : `последние ${DIVERSITY_LAST}`}
      {n != null && !q.data?.log_error ? ` · посчитано ${videos(n)}` : ''}
    </>
  );
  return (
    <Card aria-labelledby="stats-diversity-title" data-testid="stats-diversity">
      <CardHead
        eyebrow={eyebrow}
        title="Разнообразие ленты"
        titleId="stats-diversity-title"
        actions={
          <>
            <Segmented
              label="Чья лента"
              value={all}
              options={[
                {
                  on: false,
                  text: name(channel),
                  tip: 'Лента только этого канала',
                  testId: 'diversity-channel',
                },
                {
                  on: true,
                  text: 'Вся фабрика',
                  tip: 'Лента всех каналов фабрики',
                  testId: 'diversity-all',
                },
              ]}
              onPick={setAll}
            />
            <Segmented
              label="Сколько роликов"
              value={whole}
              options={[
                {
                  on: false,
                  text: `Последние ${DIVERSITY_LAST}`,
                  tip: `Последние ${DIVERSITY_LAST} принятых роликов`,
                  testId: 'diversity-last',
                },
                {
                  on: true,
                  text: 'Вся лента',
                  tip: 'Все принятые ролики',
                  testId: 'diversity-whole',
                },
              ]}
              onPick={setWhole}
            />
          </>
        }
      />
      {q.isPending ? (
        <DiversitySkeleton />
      ) : q.isError ? (
        <ErrorState
          title="Разнообразие ленты не посчитать"
          error={q.error}
          onRetry={() => void q.refetch()}
        >
          {q.error instanceof BatchError && q.error.problem
            ? q.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : (
        <>
          <Body d={q.data} />
          <More>
            {q.data.log_error ? <span>ошибка: {q.data.log_error}</span> : null}
            <span>журнал: {q.data.log}</span>
            {q.data.videos.length ? <span>ролики: {q.data.videos.join(', ')}</span> : null}
            {q.data.lines.map((l, i) => (
              <span key={i}>{l}</span>
            ))}
          </More>
        </>
      )}
    </Card>
  );
}
