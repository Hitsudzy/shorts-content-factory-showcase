// «Идёт сейчас» экрана «Батчи» (CC-0051): каждый открытый батч — карточкой с кинолентой
// стадий, прошло/потолок, оценкой конца, статусом и тем, что ждёт человека. Список — опрос
// `GET /api/batches` раз в `poll_s`; подробности батча — `GET /api/batches/{batch}`.
// «Остановить…»/«Продолжить…» (CC-0052) — в строке времени батча, как в макете. Исполнитель
// не отвечает (CC-0094, `useExecutor`) — «батч стоит», причина фабрики и «Продолжить с этапа…».
// Темы батча (CC-0092) — блок «Темы» и итоги этапов в киноленте; пока батч идёт, темы
// перечитываются на каждом ответе опроса списка (`tick`), своего опроса у них нет.
import { useId } from 'react';

import { useBatchTopics, useTopicsRefresh } from '@/api/batchTopics';
import { isRebuild, useBatchStages, useGoingBatches, type GoingBatch } from '@/api/batches';
import { BatchError } from '@/api/batchProblem';
import { byYou } from '@/api/humanText';
import { AskButton } from '@/components/ask/AskDialog';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { useFreshness } from '@/pages/channels/useFreshness';

import { BatchControl } from './BatchControl';
import { BatchInside } from './BatchInside';
import { CodeEditsMark, CodeEditsWarning } from './CodeEdits';
import { FootageBlock } from './Footage';
import { eventAgeText, GONE_STATUS, GONE_TITLE } from './executor';
import { FilmStrip } from './FilmStrip';
import { dateTimeMsk, timeMsk } from './format';
import { batchStatus, etaText, framesOf, spanText, stageClock, stageTitle } from './going';
import { useChannelNames } from './names';
import { batchAnchor } from './stranded';
import { frameSummaries } from './topicsText';
import { TopicsBlock } from './Topics';
import { useExecutor } from './useExecutor';
import { SkeletonCard, SkeletonFilmStrip } from '@/components/common/Skeletons';

/** Батч идёт: исполнитель работает (или батч без run-state — только по маркерам). */
const goingOn = (b: GoingBatch, gone: boolean) => !gone && (b.status === 'running' || !b.status);

function Meta({ b, asOf, gone }: { b: GoingBatch; asOf?: string | null; gone: boolean }) {
  const going = goingOn(b, gone);
  const eta = going ? etaText(b.estimate) : null;
  const start = timeMsk(b.started);
  // `fresh` списка — «событие моложе суток», не «исполнитель жив»: возраст события — словами.
  const age = eventAgeText(b.last_event, asOf);
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 font-mono text-xs text-muted-foreground">
      {start ? <span data-testid="batch-started">начат {dateTimeMsk(b.started)}</span> : null}
      {/* «идёт N» — только у идущего: у стоящего — возраст последнего события (CC-0094). */}
      {going && b.elapsed_s != null ? (
        <span data-testid="batch-elapsed">идёт {spanText(b.elapsed_s)}</span>
      ) : null}
      {eta ? (
        <Tip content={eta.tip}>
          <span
            tabIndex={0}
            data-testid="batch-eta"
            data-over={eta.over || undefined}
            className={
              eta.over
                ? 'text-warning underline decoration-dotted underline-offset-4'
                : 'underline decoration-dotted underline-offset-4'
            }
          >
            {eta.text}
          </span>
        </Tip>
      ) : null}
      {age ? <span data-testid="batch-event-age">{age}</span> : null}
    </div>
  );
}

export function OpenBatchCard({
  b,
  asOf,
  tick,
}: {
  b: GoingBatch;
  asOf?: string | null;
  /** `dataUpdatedAt` опроса списка: новый ответ — перечитать темы идущего батча. */
  tick?: number;
}) {
  const name = useChannelNames();
  const ex = useExecutor(b);
  const topics = useBatchTopics(b.batch);
  // Пролёты стадий — длительность готовых кадров ленты (CC-0126).
  const spans = useBatchStages(b.batch);
  const topicsId = `topics-${useId().replace(/[^a-zA-Z0-9]/g, '')}`;
  const st = ex.gone ? GONE_STATUS : batchStatus(b.status, b.fresh);
  const rebuild = isRebuild(b.batch);
  const clock = stageClock(b);
  const going = goingOn(b, ex.gone);
  const frames = framesOf(ex.gone ? { ...b, status: 'stopped' } : b);
  /** Кадр, где батч сейчас: «Сейчас: …» — его заголовок («Добор после судьи», CC-0150). */
  const nowFrame = frames.find((f) => f.current);
  useTopicsRefresh(b.batch, going, tick);
  const toTopics = () => {
    const el = document.getElementById(topicsId);
    el?.scrollIntoView?.({ behavior: 'smooth', block: 'start' });
    el?.focus({ preventScroll: true });
  };
  const eyebrow = rebuild
    ? 'Пересборка'
    : ex.gone
      ? 'Батч стоит'
      : b.status === 'stopped'
        ? 'Батч остановлен'
        : b.status === 'done'
          ? 'Батч закрывается'
          : 'Идёт батч';
  const titleId = `going-${b.batch.replace(/[^a-zA-Z0-9]/g, '-')}`;
  return (
    <Card
      id={batchAnchor(b.batch)}
      tabIndex={-1}
      aria-labelledby={titleId}
      data-testid="open-batch"
      data-batch={b.batch}
      className="outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <CardHead
        eyebrow={eyebrow}
        titleId={titleId}
        title={name(b.channel)}
        actions={
          <>
            <AskButton
              testId="ask-batch"
              label="Попросить"
              tip="Попросить оператора об этом батче: канал и батч подставятся сами"
              target={{
                channel: b.channel,
                batch: b.batch,
                batchTitle: `${rebuild ? 'пересборка ' : ''}${dateTimeMsk(b.started) ?? b.batch_id}`,
              }}
            />
            {rebuild ? (
              <StatusBadge
                tone="idle"
                tip="Пересборка роликов готового батча: новый прогон в отдельном каталоге"
              >
                пересборка
              </StatusBadge>
            ) : null}
            <CodeEditsMark count={b.code_edits_count} />
            <span data-testid="batch-status">
              <StatusBadge tone={st.tone} tip={st.tip}>
                {st.label}
              </StatusBadge>
            </span>
          </>
        }
      />
      <BatchControl b={b} gone={ex.gone} meta={<Meta b={b} asOf={asOf} gone={ex.gone} />} />
      <FilmStrip
        frames={frames}
        nowText={going && clock.text ? `идёт ${clock.text}` : null}
        note={ex.gone ? 'исполнитель не отвечает' : null}
        progress={going ? clock.progress : null}
        summaries={frameSummaries(topics.data)}
        onSummary={toTopics}
        spans={spans.data?.stages}
      />
      {b.stage ? (
        <p className="mt-3 mb-0 text-[13px]" data-testid="batch-stage">
          <span className="text-muted-foreground">{going ? 'Сейчас: ' : 'Встал на стадии: '}</span>
          <b className="font-semibold">{nowFrame?.title ?? stageTitle(b.stage)}</b>
          {going && clock.text ? (
            <>
              {' · '}
              {b.stage_timeout_min ? (
                <Tip content="Потолок стадии из плана прогона: дольше — фабрика считает стадию зависшей">
                  <span
                    tabIndex={0}
                    data-testid="stage-clock"
                    className="underline decoration-dotted underline-offset-4"
                  >
                    {clock.text}
                  </span>
                </Tip>
              ) : (
                <span data-testid="stage-clock">{clock.text}</span>
              )}
            </>
          ) : null}
        </p>
      ) : null}
      {ex.gone ? (
        <p
          role="status"
          data-testid="executor-gone"
          className="mt-3 mb-0 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_8%,var(--card))] p-2.5 text-[13px]"
        >
          <b className="font-semibold">{GONE_TITLE}. </b>
          {ex.reason ? <span data-testid="executor-gone-reason">{ex.reason}</span> : null}
        </p>
      ) : null}
      {b.halt_reason ? (
        <p
          role="status"
          data-testid="halt-reason"
          className="mt-3 mb-0 rounded-sm border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_8%,var(--card))] p-2.5 text-[13px]"
        >
          <b className="font-semibold">Почему стоит: </b>
          {byYou(b.halt_reason)}
        </p>
      ) : null}
      {b.state_error ? (
        <p className="mt-3 mb-0 text-[13px] text-danger">Файл состояния не читается.</p>
      ) : null}
      <CodeEditsWarning b={b} />
      <TopicsBlock
        id={topicsId}
        batch={b.batch}
        topics={topics.data}
        error={topics.isError ? topics.error : null}
      />
      <FootageBlock batch={b.batch} going={going} topics={topics.data} />
      <BatchInside
        batch={b.batch}
        needsHuman={b.needs_human ?? []}
        live={b.status === 'running' && !ex.gone}
        topics={topics.data}
      />
      <More>
        <span>батч {b.batch}</span>
        <span>
          каталог {b.dir}/{b.batch_id}
        </span>
        {b.stage ? <span>стадия фабрики {b.stage}</span> : null}
        {b.next ? <span>следующая стадия {b.next}</span> : null}
        {b.source ? <span>источник: {b.source}</span> : null}
        {b.last_event ? <span>последнее событие {b.last_event}</span> : null}
        {b.state_error ? <span>{b.state_error}</span> : null}
      </More>
    </Card>
  );
}

export function OpenBatches() {
  const going = useGoingBatches();
  const fresh = useFreshness(going.data, going.dataUpdatedAt);
  return (
    <div className="grid gap-gap" data-testid="batches-live" data-tour="open-batches">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-display text-[19px] font-semibold tracking-[.02em] uppercase">
          Идёт сейчас
        </h2>
        {fresh ? (
          <span className="text-xs text-muted-foreground" data-testid="going-fresh">
            {fresh}
          </span>
        ) : null}
      </div>
      {going.isPending ? (
        <SkeletonCard rows={1} label="Смотрю, что идёт…">
          <SkeletonFilmStrip bare frames={8} className="mt-3" />
        </SkeletonCard>
      ) : going.isError ? (
        <ErrorState
          title="Не удалось узнать, что идёт"
          error={going.error}
          onRetry={() => void going.refetch()}
        >
          {going.error instanceof BatchError && going.error.problem
            ? going.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : going.data.batches.length === 0 ? (
        <Card data-testid="no-batch">
          <EmptyState title="Сейчас батча нет">
            Следующий — по плану недели ниже. История прошлых прогонов — внизу страницы.
          </EmptyState>
        </Card>
      ) : (
        going.data.batches.map((b) => (
          <OpenBatchCard key={b.batch} b={b} asOf={going.data.as_of} tick={going.dataUpdatedAt} />
        ))
      )}
    </div>
  );
}
