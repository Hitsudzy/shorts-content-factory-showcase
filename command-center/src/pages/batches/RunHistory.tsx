// История прогонов (CC-0044, `GET /api/batches/history`): длительность, итог, кто запустил.
// Раскрытие прогона — его стадии с длительностями (`…/stages`) и журналы; хвост журнала —
// по выбору (`…/logs/{name}?bytes=`), с честным «показан конец» при `truncated`. Стадия с началом
// и без конца у батча, который сейчас не идёт, — «оборвалась», не «идёт» (CC-0123); `open_why` —
// под «подробнее». Строки журнала запусков без своего прогона — «фабрика не повторила»
// (`repeat_held`, CF-0822) и «продолжен тиком сам» (resume с `auto`, CC-0177) — между прогонами.
import { useId, useState } from 'react';
import { Link } from 'react-router';

import {
  HISTORY_LIMIT,
  isRebuild,
  TAIL_BYTES,
  useBatchHistory,
  useBatchStages,
  useGoingBatches,
  useLogTail,
  type BatchRun,
  type Launch,
} from '@/api/batches';
import { BatchError } from '@/api/batchProblem';
import { useBatchTopics } from '@/api/batchTopics';
import { nbShort } from '@/api/humanText';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { BREAKER_TIP, dateTimeMsk } from './format';
import { heldLaunchText, isHeldLaunch } from './breaker';
import { launchedBy, outcomeText, sizeText, spanText } from './going';
import { autoResumeText } from './login';
import { Ticked } from './Ticked';
import { stageName } from './stages';
import { logLabel, nameOf } from './words';
import { useChannelNames } from './names';
import { Refusal } from './parts';
import { RunSummaryBlock } from './RunSummary';
import { TopicsBlock } from './Topics';
import { SkeletonRows, SkeletonText } from '@/components/common/Skeletons';

/** Хвост журнала батча по имени (`…/logs/{name}`); им же — журнал стадии упавшего батча. */
export function Tail({ batch, name }: { batch: string; name: string }) {
  const tail = useLogTail(batch, name);
  if (tail.isPending) return <SkeletonText lines={4} lineHeight={18} label="Читаю журнал…" />;
  if (tail.isError) return <Refusal error={tail.error} title="Журнал не читается" />;
  const t = tail.data;
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5" data-testid="log-tail">
      <div className="flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground">
        <span data-testid="log-tail-note">
          {t.truncated
            ? `Показан конец: последние ${sizeText(t.size - t.offset)} из ${sizeText(t.size)}`
            : `Журнал целиком, ${sizeText(t.size)}`}
        </span>
        <Button size="sm" variant="ghost" onClick={() => void tail.refetch()}>
          Обновить
        </Button>
      </div>
      <pre className="m-0 max-h-80 overflow-auto rounded-sm border bg-background p-2.5 font-mono text-[11.5px] leading-[1.45] break-all whitespace-pre-wrap">
        {t.text || 'Журнал пуст.'}
      </pre>
      <More className="mt-0">
        <span>
          {t.name}: с байта {t.offset} из {t.size}
          {t.truncated ? ` (спрошено ${TAIL_BYTES} байт, начало — с целой строки)` : ''}
        </span>
      </More>
    </div>
  );
}

/** Стадия без конца в батче, который сейчас не идёт: «оборвалась» (CC-0123). */
const CUT_TIP =
  'Стадия начата, а отметки конца нет: батч дальше не идёт — стадия оборвалась (упала или её процесс остановили)';

function RunStages({ batch }: { batch: string }) {
  const stages = useBatchStages(batch);
  // Идёт ли батч сейчас (снова открыт после повтора — CF-0739): только тогда открытая стадия «идёт».
  const going = useGoingBatches().data?.batches.find((b) => b.batch === batch);
  const live = !!going && going.status === 'running' && going.executor_alive !== false;
  const [log, setLog] = useState<string | null>(null);
  if (stages.isPending)
    return <SkeletonRows rows={4} height={30} gap={0} bordered={false} label="Читаю стадии…" />;
  if (stages.isError) return <Refusal error={stages.error} title="Стадии не читаются" />;
  const s = stages.data;
  const chosen = s.logs.find((l) => l.name === log) ?? null;
  return (
    <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-3" data-testid="run-stages">
      {!s.closed ? (
        <p className="m-0 text-[13px] text-warning" data-testid="run-open">
          Батч не закрыт
          {s.open_stages.length
            ? ` — ${live ? 'идут' : 'оборвались'}: ${s.open_stages
                .filter(Boolean)
                .map((x) => stageName(x as string))
                .join(', ')}`
            : ''}
        </p>
      ) : null}
      {s.stages.length ? (
        <ol className="m-0 grid list-none gap-0 p-0 text-[13px]">
          {s.stages.map((sp, i) => (
            <li
              key={`${sp.stage}-${i}`}
              data-testid="run-stage"
              className="grid grid-cols-[minmax(0,1fr)_auto] gap-2 border-t py-1.5 first:border-t-0"
            >
              <span className="min-w-0" data-stage={sp.stage}>
                {nameOf(sp.stage)}
              </span>
              {sp.open && !live ? (
                <Tip content={CUT_TIP}>
                  <span
                    tabIndex={0}
                    data-testid="run-stage-cut"
                    className="text-right text-warning underline decoration-dotted underline-offset-4"
                  >
                    оборвалась
                  </span>
                </Tip>
              ) : (
                <span className={cn('text-right', sp.open && 'text-primary-text')}>
                  {sp.open ? 'идёт' : (spanText(sp.duration_s) ?? '—')}
                </span>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p className="m-0 text-muted-foreground">Отметок стадий нет.</p>
      )}
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5">
        <h4 className="text-[13px] font-semibold">Журналы</h4>
        {s.logs.length ? (
          <div className="flex flex-wrap gap-1.5" role="group" aria-label="Журналы прогона">
            {s.logs.map((l) => (
              <Button
                key={l.name}
                size="sm"
                variant={l.name === log ? 'default' : 'outline'}
                aria-pressed={l.name === log}
                data-testid="log-button"
                data-log={l.name}
                className="h-auto min-h-[28px] max-w-full py-1 text-left whitespace-normal"
                onClick={() => setLog(l.name === log ? null : l.name)}
              >
                <span className="min-w-0">{logLabel(l.name)}</span>
                <span className="text-xs opacity-70">{sizeText(l.size)}</span>
              </Button>
            ))}
          </div>
        ) : (
          <p className="m-0 text-muted-foreground">Журналов у прогона нет.</p>
        )}
        {chosen ? <Tail batch={batch} name={chosen.name} /> : null}
      </div>
      {s.open_why || s.stages.length || s.logs.length ? (
        <More className="mt-0">
          {s.open_why ? <span>почему не закрыт: {s.open_why}</span> : null}
          {s.open_why && s.open_stages.length ? (
            <span>открыты: {s.open_stages.join(', ')}</span>
          ) : null}
          {s.stages.length ? <span>стадии: {s.stages.map((x) => x.stage).join(', ')}</span> : null}
          {s.logs.length ? <span>журналы: {s.logs.map((l) => l.name).join(', ')}</span> : null}
        </More>
      ) : null}
    </div>
  );
}

/** Темы прошлого прогона (CC-0092): прогон закрыт — читаются один раз, без обновления. */
function RunTopics({ batch }: { batch: string }) {
  const topics = useBatchTopics(batch);
  return (
    <TopicsBlock batch={batch} topics={topics.data} error={topics.isError ? topics.error : null} />
  );
}

function RunRow({ run }: { run: BatchRun }) {
  const name = useChannelNames();
  const [open, setOpen] = useState(false);
  const panel = useId();
  const by = launchedBy(run.launch);
  const out = outcomeText(run.outcome, run.videos);
  const rebuild = isRebuild(run.batch) || run.launch?.kind === 'rebuild';
  return (
    <li data-testid="run" data-batch={run.batch ?? undefined} className="border-t first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          disabled={!run.batch}
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 basis-[14rem] items-center gap-2 text-left disabled:cursor-default"
        >
          <span
            aria-hidden
            className={cn('text-muted-foreground transition-transform', open && 'rotate-90')}
          >
            ›
          </span>
          <span className="min-w-0">
            <b className="font-semibold">{name(run.channel)}</b>
            <span className="ml-2 text-muted-foreground">
              {dateTimeMsk(run.started) ?? run.date ?? '—'}
            </span>
          </span>
        </button>
        {rebuild ? (
          <StatusBadge tone="idle" tip="Пересборка роликов готового батча">
            пересборка
          </StatusBadge>
        ) : null}
        <span className="font-mono text-xs" data-testid="run-duration">
          {spanText(run.wall_s) ?? '—'}
        </span>
        <span data-testid="run-outcome">
          <StatusBadge tone={out.tone}>{out.label}</StatusBadge>
        </span>
        <Tip content={by.tip}>
          <span
            tabIndex={0}
            data-testid="run-by"
            className="text-xs text-muted-foreground underline decoration-dotted underline-offset-4"
          >
            {by.label}
          </span>
        </Tip>
      </div>
      <div id={panel} hidden={!open} className="pb-3 pl-5">
        {open && run.batch ? (
          <>
            <RunStages batch={run.batch} />
            <RunSummaryBlock batch={run.batch} />
            <RunTopics batch={run.batch} />
            {run.videos !== 0 ? (
              <Link
                to={{
                  pathname: '/videos',
                  search: `?${new URLSearchParams({ batch: run.batch })}`,
                }}
                data-testid="run-videos"
                className="mt-3 inline-block text-[13px] text-primary-text underline-offset-4 hover:underline"
              >
                Ролики батча{run.videos ? ` (${run.videos})` : ''} →
              </Link>
            ) : null}
            <More>
              <span>батч {run.batch}</span>
              {run.launch?.why ? <span>почему запущен: {run.launch.why}</span> : null}
              {run.launch?.by ? <span>launch.by: {run.launch.by}</span> : null}
            </More>
          </>
        ) : null}
      </div>
    </li>
  );
}

/**
 * Строка «фабрика не повторила» (`kind: repeat_held`, CF-0822): приглушённая, не прогон. Свёрнута
 * той же высоты, что строка прогона (страница истории — HISTORY_LIMIT строк, скелетон держит
 * столько же, CC-0121): канал, время, метка; предложение и строка фабрики — по раскрытию.
 */
function HeldRow({ l }: { l: Launch }) {
  const name = useChannelNames();
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <li data-testid="run-held" className="border-t text-muted-foreground first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 basis-[14rem] items-center gap-2 text-left"
        >
          <span aria-hidden className={cn('transition-transform', open && 'rotate-90')}>
            ›
          </span>
          <span className="min-w-0">
            <b className="font-semibold">{l.channel ? name(l.channel) : '—'}</b>
            <span className="ml-2">{dateTimeMsk(l.at) ?? l.day ?? '—'}</span>
          </span>
        </button>
        <StatusBadge tone="idle" tip={BREAKER_TIP}>
          повтор придержан
        </StatusBadge>
      </div>
      <div id={panel} hidden={!open} className="pb-3 pl-5 text-[13px]">
        <p className="m-0" data-testid="run-held-text">
          {nbShort(heldLaunchText(l))}
        </p>
        <More className="mt-0.5">
          {l.why ? <span>фабрика: {l.why}</span> : null}
          {l.failed_batch ? <span>упавший батч: {l.failed_batch}</span> : null}
          {l.failure ? <span>где упал: {l.failure}</span> : null}
          {l.quota_day ? <span>сутки квоты: {l.quota_day}</span> : null}
        </More>
      </div>
    </li>
  );
}

/**
 * Строка «продолжен тиком сам» (resume с `auto`, CC-0177 по CF-0899): батч стоял без входа
 * Claude, тик продолжил его сам. Свёрнута той же высоты, что строка прогона; пометка — с
 * подсказкой (строка `auto` словами центра), сама строка фабрики — под «подробнее».
 */
function AutoRow({ l }: { l: Launch }) {
  const name = useChannelNames();
  const [open, setOpen] = useState(false);
  const panel = useId();
  const text = autoResumeText(l.auto);
  return (
    <li data-testid="run-auto" className="border-t first:border-t-0">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 py-2.5">
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panel}
          onClick={() => setOpen((v) => !v)}
          className="flex min-w-0 flex-1 basis-[14rem] items-center gap-2 text-left"
        >
          <span
            aria-hidden
            className={cn('text-muted-foreground transition-transform', open && 'rotate-90')}
          >
            ›
          </span>
          <span className="min-w-0">
            <b className="font-semibold">{l.channel ? name(l.channel) : '—'}</b>
            <span className="ml-2 text-muted-foreground">{dateTimeMsk(l.at) ?? l.day ?? '—'}</span>
          </span>
        </button>
        <span data-testid="run-auto-badge">
          <StatusBadge tone="idle" tip={<Ticked text={text} />}>
            продолжен тиком сам
          </StatusBadge>
        </span>
      </div>
      <div id={panel} hidden={!open} className="pb-3 pl-5 text-[13px]">
        <p className="m-0" data-testid="run-auto-text">
          <Ticked text={nbShort(text)} />
        </p>
        <More className="mt-0.5">
          <span>фабрика: {l.auto}</span>
          {l.why ? <span>почему: {l.why}</span> : null}
          {l.pid != null ? <span>pid {l.pid}</span> : null}
          {l.by ? <span>launch.by: {l.by}</span> : null}
        </More>
      </div>
    </li>
  );
}

type HistoryRow = { run: BatchRun } | { held: Launch } | { auto: Launch };

const startOf = (x: HistoryRow) =>
  Date.parse(('run' in x ? x.run.started : 'held' in x ? x.held.at : x.auto.at) ?? '') || 0;

/**
 * Прогоны и строки «фабрика не повторила» / «продолжен тиком сам» вместе, новые сверху (у
 * прогонов порядок фабрики). Страница — не больше HISTORY_LIMIT строк, как у скелетона: такая
 * строка вытесняет самый старый прогон страницы, а не удлиняет её.
 */
function withLaunches(runs: BatchRun[], launches: Launch[]) {
  const rows: HistoryRow[] = runs.map((run) => ({ run }));
  const extra: HistoryRow[] = launches.flatMap((l): HistoryRow[] =>
    isHeldLaunch(l) ? [{ held: l }] : l.auto ? [{ auto: l }] : [],
  );
  for (const x of extra) {
    const t = startOf(x);
    const i = rows.findIndex((r) => startOf(r) < t);
    rows.splice(i < 0 ? rows.length : i, 0, x);
  }
  return rows.slice(0, Math.max(HISTORY_LIMIT, runs.length));
}

export function RunHistory() {
  const history = useBatchHistory();
  return (
    <Card aria-labelledby="history-title" data-testid="batch-history">
      <CardHead eyebrow="История" title="Прошлые прогоны" titleId="history-title" />
      {history.isPending ? (
        // Страница истории — HISTORY_LIMIT строк по 43 px через черту: столько и придёт.
        <SkeletonRows
          rows={HISTORY_LIMIT}
          height={43}
          gap={1}
          bordered={false}
          label="Читаю историю…"
        />
      ) : history.isError ? (
        <ErrorState
          title="Историю прогонов не прочитать"
          error={history.error}
          onRetry={() => void history.refetch()}
        >
          {history.error instanceof BatchError && history.error.problem
            ? history.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : history.data.runs.length === 0 ? (
        <EmptyState title="Прогонов ещё не было" />
      ) : (
        <ul className="m-0 list-none p-0">
          {withLaunches(history.data.runs, history.data.launches ?? []).map((x, i) =>
            'run' in x ? (
              <RunRow key={x.run.batch ?? `${x.run.id}-${i}`} run={x.run} />
            ) : 'held' in x ? (
              <HeldRow key={`held-${x.held.at}-${i}`} l={x.held} />
            ) : (
              <AutoRow key={`auto-${x.auto.at}-${i}`} l={x.auto} />
            ),
          )}
        </ul>
      )}
    </Card>
  );
}
