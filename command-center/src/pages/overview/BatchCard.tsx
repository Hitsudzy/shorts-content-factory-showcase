// «Идёт батч» главной (CC-0051): кинолента стадий идущего батча по `GET /api/batches`, как
// в макете «Кинозал». Подробности, события и история — на экране «Батчи». Нет батча —
// честное «сейчас батча нет». Исполнитель не отвечает (CC-0094) — тот же статус, что на
// «Батчах»: «батч стоит», причина фабрики; «Продолжить» — на экране «Батчи».
import { byYou } from '@/api/humanText';
import { Link } from 'react-router';

import { isRebuild, useGoingBatches, type GoingBatch } from '@/api/batches';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';
import { CodeEditsMark } from '@/pages/batches/CodeEdits';
import { FilmStrip } from '@/pages/batches/FilmStrip';
import { timeMsk } from '@/pages/batches/format';
import { eventAgeText, GONE_STATUS, GONE_TITLE } from '@/pages/batches/executor';
import { batchStatus, etaText, framesOf, stageClock } from '@/pages/batches/going';
import { useChannelNames } from '@/pages/batches/names';
import { useExecutor } from '@/pages/batches/useExecutor';

const IDLE = framesOf({ stages: null, stage: null, status: null });

/** Какой батч показать первым: идущий и свежий, потом остальные — как прислала фабрика. */
function pick(list: GoingBatch[]): GoingBatch | null {
  return list.find((b) => b.status === 'running' && b.fresh) ?? list[0] ?? null;
}

const toBatches = (
  <Button asChild variant="ghost">
    <Link to="/batches">К батчам</Link>
  </Button>
);

export function BatchCard() {
  const going = useGoingBatches();
  const name = useChannelNames();
  const b = going.data ? pick(going.data.batches) : null;
  const others = going.data ? going.data.batches.length - (b ? 1 : 0) : 0;
  const asOf = going.data?.as_of;
  const ex = useExecutor(b);

  if (!b) {
    return (
      <Card
        aria-labelledby="batch-title"
        data-testid="batch-card"
        data-tour="home-batch"
        data-state="none"
      >
        <CardHead
          eyebrow="Батч"
          title={going.isPending ? 'Смотрю, что идёт…' : 'Сейчас батча нет'}
          titleId="batch-title"
          actions={toBatches}
        />
        <FilmStrip frames={IDLE} label="Стадии батча — сейчас не идёт" />
        {going.isError ? (
          <div className="mt-3">
            <ErrorState
              title="Не удалось узнать, идёт ли батч"
              error={going.error}
              onRetry={() => void going.refetch()}
            />
          </div>
        ) : going.data ? (
          <p className="mt-3 mb-0 text-muted-foreground">
            Следующий батч — по плану недели на экране «Батчи».
          </p>
        ) : null}
      </Card>
    );
  }

  const st = ex.gone ? GONE_STATUS : batchStatus(b.status, b.fresh);
  const goingOn = !ex.gone && (b.status === 'running' || !b.status);
  const eta = goingOn ? etaText(b.estimate) : null;
  const age = eventAgeText(b.last_event, asOf);
  const clock = stageClock(b);
  const rebuild = isRebuild(b.batch);
  return (
    <Card
      aria-labelledby="batch-title"
      data-testid="batch-card"
      data-tour="home-batch"
      data-state={ex.gone ? 'gone' : 'going'}
    >
      <CardHead
        eyebrow={
          rebuild
            ? 'Идёт пересборка'
            : ex.gone
              ? 'Батч стоит'
              : b.status === 'stopped'
                ? 'Батч остановлен'
                : 'Идёт батч'
        }
        title={name(b.channel)}
        titleId="batch-title"
        actions={
          <>
            <span className="font-mono text-xs text-muted-foreground" data-testid="home-batch-meta">
              {timeMsk(b.started) ? `начат ${timeMsk(b.started)}` : null}
              {eta ? (
                <>
                  {timeMsk(b.started) ? ' · ' : null}
                  <Tip content={eta.tip}>
                    <span
                      tabIndex={0}
                      data-testid="home-batch-eta"
                      className={
                        eta.over
                          ? 'text-warning underline decoration-dotted underline-offset-4'
                          : 'underline decoration-dotted underline-offset-4'
                      }
                    >
                      {eta.text}
                    </span>
                  </Tip>
                </>
              ) : null}
              {age ? (
                <span data-testid="home-batch-age">
                  {timeMsk(b.started) || eta ? ' · ' : null}
                  {age}
                </span>
              ) : null}
            </span>
            <CodeEditsMark count={b.code_edits_count} />
            <span data-testid="home-batch-status">
              <StatusBadge tone={st.tone} tip={st.tip}>
                {st.label}
              </StatusBadge>
            </span>
            {toBatches}
          </>
        }
      />
      <FilmStrip
        frames={framesOf(ex.gone ? { ...b, status: 'stopped' } : b)}
        nowText={goingOn && clock.text ? `идёт ${clock.text}` : null}
        note={ex.gone ? 'исполнитель не отвечает' : null}
        progress={goingOn ? clock.progress : null}
      />
      {ex.gone ? (
        <p className="mt-3 mb-0 text-[13px]" role="status" data-testid="home-executor-gone">
          <b className="font-semibold">{GONE_TITLE}. </b>
          {ex.reason ? <>{ex.reason}. </> : null}
          Продолжить — на экране «Батчи».
        </p>
      ) : null}
      {b.halt_reason ? (
        <p className="mt-3 mb-0 text-[13px]">
          <b className="font-semibold">Почему стоит: </b>
          {byYou(b.halt_reason)}
        </p>
      ) : null}
      {b.code_edits_count ? (
        <p className="mt-3 mb-0 text-[13px] text-danger" data-testid="home-code-edits">
          Стадия батча изменила код фабрики — следующий батч не запустится, пока правку не разберут.
          Подробности — на экране «Батчи».
        </p>
      ) : null}
      {b.needs_human?.length ? (
        <p className="mt-3 mb-0 text-[13px] text-primary-text" data-testid="home-batch-needs">
          Ждёт вас: {b.needs_human.length} — подробности на экране «Батчи».
        </p>
      ) : null}
      {others > 0 ? (
        <p className="mt-2 mb-0 text-xs text-muted-foreground">
          Ещё открыто батчей: {others} — на экране «Батчи».
        </p>
      ) : null}
      <More>
        <span>батч {b.batch}</span>
        {b.stage ? <span>стадия фабрики {b.stage}</span> : null}
      </More>
    </Card>
  );
}
