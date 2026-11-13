// «Батчи» (CC-0011, разбит на три шага): (а) CC-0050 — план и расписание: план недели,
// рубильник с заметкой, окна каналов; (б) CC-0051 — идущий батч и история прогонов;
// (в) CC-0052 — действия: запуск вручную (карточка рядом с рубильником), остановить и
// продолжить (на карточке идущего батча). Упавшие батчи, которых нет ни в идущих, ни в истории,
// — блоком под идущими (CC-0089).
import { BatchError } from '@/api/batchProblem';
import { useSchedule } from '@/api/schedule';
import { ErrorState } from '@/components/common/States';
import { StatusPill } from '@/components/common/Status';

import { ChannelWindows } from './ChannelWindows';
import { switchState } from './format';
import { LaunchCard } from './LaunchCard';
import { OpenBatches } from './OpenBatches';
import { RunHistory } from './RunHistory';
import { SearchBudget } from './SearchBudget';
import { StrandedBatches } from './StrandedBatches';
import { SwitchCard } from './SwitchCard';
import { WeekPlan } from './WeekPlan';
import { Pending, SkeletonCard, SkeletonRows, SkeletonText } from '@/components/common/Skeletons';

export function Batches() {
  const plan = useSchedule();
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow">План, расписание и ход батчей</div>
          <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
            Батчи
          </h1>
        </div>
        <div className="grid justify-items-start gap-2 sm:justify-items-end">
          <p className="m-0 max-w-[52ch] text-muted-foreground sm:text-right">
            Какой канал в какой день получит батч и почему, рубильник расписания и окна каналов.
          </p>
          {plan.data ? (
            <StatusPill
              tone={plan.data.switch.on ? 'live' : 'idle'}
              tip="Рубильник расписания: включён — фабрика по расписанию сама запускает батч дня по плану"
              data-testid="header-switch"
            >
              Рубильник: {switchState(plan.data.switch).label}
            </StatusPill>
          ) : null}
        </div>
      </div>
      <OpenBatches />
      <StrandedBatches />
      {plan.isPending ? (
        <Pending
          label="Строю план…"
          className="grid-cols-1 gap-(--space-gap) md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]"
        >
          {/* Неделя: семь дней по ~90 px и «вне плана»; справа — рубильник и запуск. */}
          <SkeletonCard bare rows={0}>
            <SkeletonRows bare rows={7} height={88} gap={4} />
            <SkeletonText bare lines={4} className="mt-6" />
          </SkeletonCard>
          <div className="grid content-start gap-(--space-gap)">
            <SkeletonCard bare rows={4} />
            <SkeletonCard bare rows={5} />
          </div>
          {/* Окна каналов — под планом, во всю ширину. */}
          <div className="md:col-span-2">
            <SkeletonCard bare rows={0}>
              <SkeletonRows bare rows={3} height={120} gap={10} />
            </SkeletonCard>
          </div>
        </Pending>
      ) : plan.isError ? (
        <ErrorState
          title="Не удалось получить план батчей"
          error={plan.error}
          onRetry={() => void plan.refetch()}
        >
          {plan.error instanceof BatchError && plan.error.problem
            ? plan.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-gap md:grid-cols-[minmax(0,1.6fr)_minmax(0,1fr)]">
            <WeekPlan plan={plan.data} />
            <div className="grid content-start gap-gap">
              <SwitchCard plan={plan.data} />
              <SearchBudget plan={plan.data} />
              <LaunchCard channels={plan.data.channels} />
            </div>
          </div>
          <ChannelWindows channels={plan.data.channels} />
        </>
      )}
      <RunHistory />
    </>
  );
}
