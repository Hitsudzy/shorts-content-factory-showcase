// «Каналы»: обзор всех каналов фабрики — состояние, расписание, пауза, ближайшая публикация.
import { Link } from 'react-router';

import { useChannel, useChannelList, type ChannelSummary } from '@/api/channels';
import { Card } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Tip } from '@/components/common/Tip';
import { Button } from '@/components/ui/button';

import { Avatar, ChannelState } from './identity';
import { channelName, channelsCount } from './names';
import { OverviewRows } from './parts';
import { useFreshness } from './useFreshness';
import { Pending, SkeletonCard, SkeletonList } from '@/components/common/Skeletons';

function ChannelCard({ c, fresh }: { c: ChannelSummary; fresh: string | null }) {
  // Карточка канала нужна ради расписания из конфига; её же потом откроет экран канала.
  // Блокировку здесь показывает список (он и переспрашивает), карточки — нет: они тяжёлые.
  const detail = useChannel(c.error ? undefined : c.id, { recheck: false });
  const name = channelName(c);
  return (
    <Card
      aria-labelledby={`ch-${c.id}`}
      data-testid={`channel-${c.id}`}
      data-tour="channel-card"
      className="grid content-start gap-3.5"
    >
      <div className="flex items-center gap-3">
        <Avatar id={c.id} name={name} />
        <div className="min-w-0 flex-1">
          <h2 id={`ch-${c.id}`} className="text-[17px] font-semibold">
            {name}
          </h2>
          <div className="text-xs text-muted-foreground">
            {c.no_pipeline ? 'оформлен, конвейера пока нет' : 'конвейер есть'}
          </div>
        </div>
        <ChannelState c={c} />
      </div>
      {c.error ? (
        <ErrorState title="Конфиг канала не читается">{c.error}</ErrorState>
      ) : (
        <ul className="m-0 grid list-none p-0">
          <OverviewRows
            channel={c.id}
            summary={c}
            detail={detail.data}
            loading={detail.isPending}
            failed={detail.isError}
            fresh={fresh}
          />
        </ul>
      )}
      <div className="flex flex-wrap gap-2">
        <Button asChild variant="default">
          <Link to={`/channels/${encodeURIComponent(c.id)}`} data-tour="channel-open">
            Открыть настройки
          </Link>
        </Button>
        <Button asChild variant="ghost">
          <Link to={`/channels/${encodeURIComponent(c.id)}?tab=history`}>История правок</Link>
        </Button>
      </div>
      <More className="mt-0">
        <span>канал: {c.id}</span>
        {c.former_ids.length ? <span>прежние имена: {c.former_ids.join(', ')}</span> : null}
        {c.no_pipeline ? <span>{c.no_pipeline}</span> : null}
        {c.revision ? <span>ревизия: {c.revision}</span> : null}
        {fresh ? <span>батчи: {fresh}</span> : null}
      </More>
    </Card>
  );
}

export function ChannelsList() {
  const list = useChannelList();
  const fresh = useFreshness(list.data, list.dataUpdatedAt);
  const all = list.data?.channels;
  return (
    <>
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <div className="eyebrow" data-testid="channels-count">
            {all ? channelsCount(all.length) : 'Каналы фабрики'}
          </div>
          <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
            Каналы
          </h1>
        </div>
        <div className="grid justify-items-start gap-2 sm:justify-items-end">
          <p className="m-0 max-w-[52ch] text-muted-foreground sm:text-right">
            Настройки каналов, их расписание и история правок. Пока идёт батч канала, его правка
            закрыта.
          </p>
          <Tip content="Мастер по шагам: фабрика сделает канал по своему шаблону — без конвейера и вне расписания">
            <Button asChild variant="default">
              <Link to="/channels/new">+ Новый канал</Link>
            </Button>
          </Tip>
        </div>
      </div>
      {list.isPending ? (
        <Pending label="Загружаю каналы…" className="gap-(--space-gap)">
          {[0, 1, 2].map((i) => (
            <SkeletonCard key={i} bare rows={0}>
              <SkeletonList bare rows={1} avatar sub={1} />
              <SkeletonList bare rows={4} badge={false} className="mt-3" />
            </SkeletonCard>
          ))}
        </Pending>
      ) : list.isError ? (
        <ErrorState
          title="Не удалось загрузить каналы"
          error={list.error}
          onRetry={() => void list.refetch()}
        >
          Проверьте, что API фабрики запущен.
        </ErrorState>
      ) : list.data.channels.length === 0 ? (
        <EmptyState title="Каналов нет">В фабрике не нашлось ни одного канала.</EmptyState>
      ) : (
        <div className="grid grid-cols-1 gap-gap sm:grid-cols-2 md:grid-cols-3">
          {list.data.channels.map((c) => (
            <ChannelCard key={c.id} c={c} fresh={fresh} />
          ))}
        </div>
      )}
    </>
  );
}
