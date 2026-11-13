// «Статистика и аналитик» (CC-0021, API — CC-0020, договор 0.23.0) — только чтение: каналы со
// сбором статистики (`GET /api/analytics`), у выбранного — ролики с окном YouTube «первые 7
// дней», график ролика по дням, сводка аналитика по стилю, «нужный футаж» и чтение Studio.
// Канал, ролик и день сводки — в адресе (`?channel=…&video=…&day=…`). Ничего не пишет: ввод
// прочитанного в Studio появится со своим API.
import { Link, useSearchParams } from 'react-router';

import { BatchError } from '@/api/batchProblem';
import {
  useAnalytics,
  useMetrics,
  type AnalyticsChannel,
  type AnalyticsOverview,
} from '@/api/analytics';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';
import { dateTimeMsk } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { Avatar } from '@/pages/channels/identity';

import { Diversity } from './Diversity';
import { Footage } from './Footage';
import { GatePrices } from './GatePrices';
import { runState, shortDay } from './format';
import { StudioBlock } from './StudioBlock';
import { Summary } from './Summary';
import { VideoDetail } from './VideoDetail';
import { VideosTable } from './VideosTable';
import { Pending, SkeletonCard, SkeletonList, SkeletonTable } from '@/components/common/Skeletons';

/** Канал по умолчанию: первый, у кого сбор уже был; иначе первый. */
function defaultChannel(o: AnalyticsOverview): string | null {
  return (o.channels.find((c) => c.last_run) ?? o.channels[0])?.channel ?? null;
}

function channelSub(c: AnalyticsChannel): string {
  const r = c.last_run;
  if (!r) return 'Сбор статистики ещё не запускался';
  const at = dateTimeMsk(typeof r.collected_at === 'string' ? r.collected_at : null);
  const parts = [`сбор ${at ?? '—'}`];
  if (typeof r.end_day === 'string') parts.push(`числа по ${shortDay(r.end_day)}`);
  parts.push(c.summary_days.length ? `сводок: ${c.summary_days.length}` : 'сводок пока нет');
  return parts.join(' · ');
}

function Channels({ o, current }: { o: AnalyticsOverview; current: string }) {
  const name = useChannelNames();
  return (
    <Card aria-labelledby="stats-channels-title" data-testid="stats-channels">
      <CardHead
        eyebrow={`Каналы · окно первых ${o.window_days.join(', ')} дней`}
        title="Статистика каналов"
        titleId="stats-channels-title"
      />
      <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-3">
        {o.channels.map((c) => {
          const st = runState(c.last_run);
          const on = c.channel === current;
          return (
            <li key={c.channel} data-testid="stats-channel" data-channel={c.channel}>
              <Link
                to={{ search: `?channel=${encodeURIComponent(c.channel)}` }}
                aria-current={on ? 'true' : undefined}
                className={cn(
                  'grid h-full grid-cols-[auto_minmax(0,1fr)] items-start gap-3 rounded-sm border p-3 outline-offset-2 hover:border-muted-foreground',
                  on &&
                    'border-primary bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] hover:border-primary',
                )}
              >
                <Avatar id={c.channel} name={name(c.channel)} />
                <span className="grid min-w-0 gap-1">
                  <span className="font-semibold">{name(c.channel)}</span>
                  <span className="text-xs text-muted-foreground">{channelSub(c)}</span>
                  <span>
                    <StatusBadge tone={st.tone} tip={st.tip}>
                      {st.label}
                    </StatusBadge>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      <More>
        {o.channels.map((c) => (
          <span key={c.channel}>
            {c.channel}: {c.last_run ? JSON.stringify(c.last_run) : 'runs.jsonl пуст'}
          </span>
        ))}
      </More>
    </Card>
  );
}

function ChannelStats({ c }: { c: AnalyticsChannel }) {
  const m = useMetrics(c.channel);
  const [params] = useSearchParams();
  const video = params.get('video');
  return (
    <>
      {!c.last_run ? (
        <p
          data-testid="never-collected"
          className="m-0 rounded-sm border border-dashed p-3 text-muted-foreground"
        >
          Фабрика ещё ни разу не спрашивала у YouTube статистику этого канала. Числа появятся после
          первого ежедневного сбора.
        </p>
      ) : null}
      {m.isPending ? (
        <SkeletonCard rows={0} label="Читаю числа роликов…">
          <SkeletonTable bare rows={6} cols={5} />
        </SkeletonCard>
      ) : m.isError ? (
        <Card>
          <ErrorState
            title="Числа роликов не прочитать"
            error={m.error}
            onRetry={() => void m.refetch()}
          >
            {m.error instanceof BatchError && m.error.problem
              ? m.error.problem.message
              : 'Проверьте, что API фабрики запущен.'}
          </ErrorState>
        </Card>
      ) : (
        <VideosTable m={m.data} selected={video} />
      )}
      <div className="grid gap-gap lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {video ? (
          <VideoDetail key={video} channel={c.channel} videoId={video} />
        ) : (
          <Card data-testid="stats-video-hint">
            <EmptyState title="Выберите ролик">
              Нажмите на ролик в таблице — здесь появятся его числа и просмотры по дням.
            </EmptyState>
          </Card>
        )}
        <StudioBlock channel={c.channel} />
      </div>
      <Summary channel={c.channel} savedDays={c.summary_days} />
      <Diversity channel={c.channel} />
      <Footage channel={c.channel} />
    </>
  );
}

export function Stats() {
  const overview = useAnalytics();
  const [params] = useSearchParams();
  const asked = params.get('channel');
  const channel = asked ?? (overview.data ? defaultChannel(overview.data) : null);
  const current = overview.data?.channels.find((c) => c.channel === channel) ?? null;
  return (
    <>
      <div>
        <div className="eyebrow">Просмотры, удержание, выводы аналитика</div>
        <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
          Статистика и аналитик
        </h1>
      </div>
      {overview.isPending ? (
        <Pending label="Читаю статистику каналов…" className="gap-(--space-gap)">
          <SkeletonList bare rows={3} avatar sub={1} />
          <SkeletonCard bare rows={4} />
          <SkeletonCard bare rows={0}>
            <SkeletonTable bare rows={6} cols={5} />
          </SkeletonCard>
        </Pending>
      ) : overview.isError ? (
        <ErrorState
          title="Статистику не прочитать"
          error={overview.error}
          onRetry={() => void overview.refetch()}
        >
          {overview.error instanceof BatchError && overview.error.problem
            ? overview.error.problem.message
            : 'Проверьте, что API фабрики запущен.'}
        </ErrorState>
      ) : !overview.data.channels.length ? (
        <EmptyState title="Статистики пока нет">
          Ни один канал ещё ничего не опубликовал — собирать числа не по чему.
        </EmptyState>
      ) : !current ? (
        <>
          <Channels o={overview.data} current={channel ?? ''} />
          <EmptyState title="Такого канала в статистике нет">
            Выберите канал из списка выше.
          </EmptyState>
        </>
      ) : (
        <>
          <Channels o={overview.data} current={current.channel} />
          <ChannelStats key={current.channel} c={current} />
          <GatePrices />
        </>
      )}
    </>
  );
}
