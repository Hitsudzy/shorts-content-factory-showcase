// «Упавшие батчи» экрана «Батчи» (CC-0089, `GET /api/batches/stranded`): батч встал плохо
// (failed/halted/stopped), в истории прогонов его нет и он не открыт — раньше такого не было
// видно нигде. Каждый — где и почему встал словами, держит ли он сегодняшний запуск, журнал
// стадии под «подробнее» (`…/logs/{name}`) и «Продолжить…», только если фабрика (`resume/plan`)
// согласна; иначе — её отказ словами. Пусто — блока нет. Список — раз в минуту, как история;
// проверка `resume/plan` — тихо (без слоя записи), заново на каждом ответе списка. Рядом —
// «Повторить с…» (CC-0123): заново с выбранной стадии, в том числе когда продолжить нельзя.
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, useState, type ReactNode } from 'react';

import {
  planResume,
  type RerunFromResult,
  type ResumePlan,
  type ResumeResult,
} from '@/api/batchActions';
import {
  batchKeys,
  strandedBatch,
  strandedLogName,
  useStrandedBatches,
  type StrandedBatch,
} from '@/api/batches';
import { humanReason } from '@/api/humanText';
import { probe } from '@/api/writeLock';
import { useWrites } from '@/api/writes';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { StatusBadge } from '@/components/common/Status';

import { ResumeAction, ResumeOutcome } from './BatchControl';
import { resumeText } from './actions';
import { dateTimeMsk } from './format';
import { useChannelNames, useChannelText } from './names';
import { Refusal } from './parts';
import { RerunFromAction, RerunOutcome } from './RerunFrom';
import { Tail } from './RunHistory';
import { stageName } from './stages';
import { batchAnchor, strandedHeadline, strandedVerb } from './stranded';
import { Pending } from '@/components/common/Skeletons';
import { Skeleton } from '@/components/ui/skeleton';

/** Можно ли продолжить: `resume/plan` фабрики, заново на каждом ответе списка (`tick`). */
function useResumeCheck(batch: string, tick: number, enabled: boolean) {
  const qc = useQueryClient();
  const last = useRef(tick);
  useEffect(() => {
    if (tick === last.current) return;
    last.current = tick;
    void qc.invalidateQueries({ queryKey: batchKeys.resumeCheck(batch) });
  }, [qc, batch, tick]);
  return useQuery<ResumePlan>({
    queryKey: batchKeys.resumeCheck(batch),
    queryFn: () => probe(() => planResume(batch)),
    enabled,
    retry: false,
  });
}

/**
 * «Продолжить…» и что скажет фабрика; `also` — другие действия батча («Повторить с…»): они
 * всегда в одном ряду с кнопками, сразу после «Продолжить…», а пояснение — строкой под рядом.
 */
function Resume({
  batch,
  tick,
  onDone,
  also,
}: {
  batch: string;
  tick: number;
  onDone: (r: ResumeResult) => void;
  also: ReactNode;
}) {
  const writes = useWrites();
  const check = useResumeCheck(batch, tick, writes.allowed);
  const human = useChannelText();
  // Ряд кнопок один во всех состояниях проверки: «Повторить с…» в нём не пересоздаётся (его окно
  // не закрывается, когда фабрика ответила).
  let primary: ReactNode = null;
  let note: ReactNode = null;
  // Вне рабочей фабрики проверку не спрашиваем: кнопка погашена с причиной, как все записи.
  if (!writes.allowed) primary = <ResumeAction batch={batch} onDone={onDone} />;
  else if (check.isPending)
    primary = (
      <Pending label="Спрашиваю фабрику, можно ли продолжить…" className="justify-items-start">
        <Skeleton className="h-8 w-44 rounded-lg" />
      </Pending>
    );
  else if (check.isError)
    note = <Refusal error={check.error} title="Фабрика не сказала, можно ли продолжить" />;
  else if (check.data.ok) {
    primary = <ResumeAction batch={batch} onDone={onDone} />;
    note = (
      <span className="text-[13px] text-muted-foreground" data-testid="stranded-resume-from">
        {check.data.stage
          ? `Фабрика продолжит со стадии «${stageName(check.data.stage)}».`
          : 'Фабрика продолжит с места остановки.'}
      </span>
    );
  } else
    note = (
      <p className="m-0 text-[13px]" data-testid="stranded-refusal">
        <b className="font-semibold">Продолжить нельзя: </b>
        {human(humanReason(resumeText(check.data)))}
      </p>
    );
  return (
    <>
      <div className="flex flex-wrap items-center gap-2" data-testid="stranded-actions">
        {primary}
        {also}
      </div>
      {note}
    </>
  );
}

function StrandedCard({ row, tick }: { row: StrandedBatch; tick: number }) {
  const name = useChannelNames();
  const batch = strandedBatch(row);
  const logName = strandedLogName(row);
  const { eyebrow } = strandedVerb(row.status);
  const [done, setDone] = useState<ResumeResult | null>(null);
  const [rerun, setRerun] = useState<RerunFromResult | null>(null);
  const [more, setMore] = useState(false);
  const titleId = `stranded-${row.dir.replace(/[^a-zA-Z0-9]/g, '-')}`;
  return (
    <article
      id={batch ? batchAnchor(batch) : undefined}
      tabIndex={-1}
      aria-labelledby={titleId}
      data-testid="stranded-batch"
      data-batch={batch ?? row.dir}
      className="grid min-w-0 gap-3 rounded-sm border-t py-3.5 outline-none first:border-t-0 first:pt-0 last:pb-0 focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="eyebrow">{eyebrow}</div>
          <h3 id={titleId} className="mt-0.5 text-[15px] font-semibold">
            {name(row.channel)}, {dateTimeMsk(row.created) ?? 'дата неизвестна'}
          </h3>
        </div>
        <span data-testid="stranded-holds" data-holds={row.holds_day}>
          {row.holds_day ? (
            <StatusBadge
              tone="warn"
              tip="Фабрика считает его сегодняшним батчем канала: второй сегодня она не запустит — 1 батч в сутки"
            >
              держит запуск сегодня
            </StatusBadge>
          ) : (
            <StatusBadge
              tone="idle"
              tip="Сегодняшний запуск канала он не держит: фабрика его не считает"
            >
              запуск не держит
            </StatusBadge>
          )}
        </span>
      </div>
      <div className="grid gap-3">
        <p className="m-0 text-[13px]" data-testid="stranded-headline">
          {strandedHeadline(row)}
        </p>
        {row.holds_day ? (
          <p className="m-0 text-[13px] text-muted-foreground" data-testid="stranded-holds-note">
            Пока он числится за сегодня, запуск канала вручную и по расписанию фабрика отклонит
            («сегодня батч уже был»). Продолжите его — или новый батч будет завтра.
          </p>
        ) : null}
        {batch ? (
          <div className="grid justify-items-start gap-2">
            <Resume
              batch={batch}
              tick={tick}
              onDone={setDone}
              // Повтор с выбранной стадии (CC-0123): и когда продолжить нельзя.
              also={<RerunFromAction batch={batch} onDone={setRerun} />}
            />
          </div>
        ) : (
          <p className="m-0 text-[13px] text-muted-foreground">
            Центр не умеет открыть этот батч: его каталог — под «подробнее».
          </p>
        )}
        {done ? <ResumeOutcome r={done} onClose={() => setDone(null)} /> : null}
        {rerun ? <RerunOutcome r={rerun} onClose={() => setRerun(null)} /> : null}
        <More className="mt-0" onToggle={setMore}>
          <div className="mb-2 grid gap-1.5 font-sans text-[13px] text-foreground">
            <b className="font-semibold">
              Журнал стадии{row.stage ? ` «${stageName(row.stage)}»` : ''}
            </b>
            {batch && logName ? (
              more ? (
                <Tail batch={batch} name={logName} />
              ) : null
            ) : (
              <span className="text-muted-foreground" data-testid="stranded-no-log">
                {row.log
                  ? 'Этот журнал фабрика через API не отдаёт — его путь ниже.'
                  : 'Журнала у стадии нет.'}
              </span>
            )}
          </div>
          {batch ? <span>батч {batch}</span> : null}
          <span>каталог {row.dir}</span>
          {row.status ? <span>статус run-state: {row.status}</span> : null}
          {row.stage ? <span>стадия фабрики {row.stage}</span> : null}
          {row.reason ? <span>причина: {row.reason}</span> : null}
          {row.halt_reason ? <span>halt_reason: {row.halt_reason}</span> : null}
          {row.log ? <span>журнал {row.log}</span> : null}
          {row.updated ? <span>обновлён {row.updated}</span> : null}
        </More>
      </div>
    </article>
  );
}

export function StrandedBatches() {
  const q = useStrandedBatches();
  if (!q.data) return null;
  const rows = q.data.batches;
  if (rows.length === 0 && !q.data.error) return null;
  return (
    <Card data-testid="stranded" aria-labelledby="stranded-title">
      <CardHead eyebrow="Требуют решения" title="Упавшие батчи" titleId="stranded-title" />
      <p className="mt-0 mb-3.5 max-w-[70ch] text-[13px] text-muted-foreground">
        Батч встал, не дойдя до конца, — в истории прогонов его нет. Здесь видно, где и почему, и
        можно продолжить, если фабрика согласна.
      </p>
      {q.data.error ? (
        <p className="mt-0 mb-3 text-[13px] text-warning" data-testid="stranded-read-error">
          Фабрика не смогла дочитать упавшие батчи — список может быть неполным.
        </p>
      ) : null}
      <div className="grid">
        {rows.map((r) => (
          <StrandedCard key={r.dir} row={r} tick={q.dataUpdatedAt} />
        ))}
      </div>
      {q.data.error ? (
        <More>
          <span>{q.data.error}</span>
        </More>
      ) : null}
    </Card>
  );
}
