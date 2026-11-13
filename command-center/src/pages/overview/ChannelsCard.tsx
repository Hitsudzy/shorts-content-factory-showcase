// Карточка «Каналы» главной на живом `/api/channels`: каждый канал одной строкой (`.list`
// макета) — аватар, имя-ссылка в экран канала, что с ним сейчас, метка состояния и «в копилке N»
// (CC-0122: принятые ролики без слота — ссылкой на копилку канала на «Публикации»).
// Имена файлов, прежние имена и ревизии — только под «подробнее».
import type { ReactNode } from 'react';
import { Link } from 'react-router';

import { useChannels, type ChannelSummary } from '@/api/channels';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/button';
import { Avatar, ChannelState } from '@/pages/channels/identity';
import { channelName, channelsCount } from '@/pages/channels/names';
import { StashCount } from '@/pages/publishing/StashCount';
import { SkeletonList } from '@/components/common/Skeletons';

/**
 * Что сейчас с каналом — одной короткой фразой под именем: в узкой карточке она не переносится,
 * и строка канала той же высоты, что строка скелетона (CC-0121). Пояснение длиннее — в подсказке
 * значка состояния.
 */
function channelLine(c: ChannelSummary): string {
  if (c.error) return 'конфиг не читается — фабрика с каналом не работает';
  if (c.locked) return 'идёт батч — правка настроек закрыта';
  if (c.no_pipeline) return 'оформлен, конвейера пока нет';
  return 'конвейер есть';
}

function ChannelRow({ c }: { c: ChannelSummary }) {
  const name = channelName(c);
  return (
    <li
      data-testid={`home-channel-${c.id}`}
      className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-3 border-t py-[11px] first:border-t-0 first:pt-0"
    >
      <Avatar id={c.id} name={name} />
      <div className="min-w-0">
        <Link
          to={`/channels/${encodeURIComponent(c.id)}`}
          className="block truncate font-semibold hover:text-primary-text hover:underline"
        >
          {name}
        </Link>
        <div className="text-xs text-muted-foreground">{channelLine(c)}</div>
        <StashCount channel={c.id} link className="block" />
      </div>
      <ChannelState c={c} />
    </li>
  );
}

function moreLine(c: ChannelSummary): string {
  const parts = [`канал ${c.id}`];
  if (c.former_ids.length) parts.push(`прежние имена: ${c.former_ids.join(', ')}`);
  if (c.revision) parts.push(`ревизия ${c.revision.slice(0, 12)}`);
  if (c.no_pipeline) parts.push(c.no_pipeline);
  if (c.error) parts.push(`ошибка: ${c.error}`);
  return parts.join(' · ');
}

export function ChannelsCard({ className }: { className?: string }) {
  const list = useChannels();

  let title: ReactNode = 'Каналы Example';
  let body: ReactNode;
  if (list.isPending)
    body = (
      // Строка канала: имя, что с ним, «в копилке N» — две мелкие строки под именем.
      <SkeletonList rows={3} avatar sub={2} more label="Загружаю каналы…" />
    );
  else if (list.isError)
    body = (
      <ErrorState
        title="Каналы не загрузились"
        error={list.error}
        onRetry={() => void list.refetch()}
      >
        Центр не получил список каналов. Проверьте, что API фабрики запущен, и повторите.
      </ErrorState>
    );
  else if (list.data.length === 0)
    body = <EmptyState title="Каналов нет">В фабрике не нашлось ни одного канала.</EmptyState>;
  else {
    title = channelsCount(list.data.length);
    body = (
      <>
        <ul className="m-0 grid list-none p-0">
          {list.data.map((c) => (
            <ChannelRow key={c.id} c={c} />
          ))}
        </ul>
        <More>
          {list.data.map((c) => (
            <span key={c.id}>{moreLine(c)}</span>
          ))}
        </More>
      </>
    );
  }

  return (
    <Card aria-labelledby="channels-title" className={className} data-testid="channels-card">
      <CardHead
        eyebrow="Каналы"
        title={title}
        titleId="channels-title"
        actions={
          <Button asChild variant="ghost">
            <Link to="/channels">Все</Link>
          </Button>
        }
      />
      {body}
    </Card>
  );
}
