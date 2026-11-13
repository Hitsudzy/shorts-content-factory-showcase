// «в копилке N» у канала (CC-0122): карточки каналов «Публикации» и строка канала на главной.
// Тот же кэш, что у блока «Копилка» (`useStash`, один запрос на канал); не прочиталась —
// ничего (у канала без очереди публикации копилки нет). Отдельным модулем: главная не тянет
// за собой экран «Публикация».
import { Link } from 'react-router';

import { useStash } from '@/api/stash';
import { cn } from '@/lib/utils';

export function StashCount({
  channel,
  link = false,
  className,
}: {
  channel: string;
  /** Ссылкой на копилку канала на экране «Публикация» (с главной). */
  link?: boolean;
  className?: string;
}) {
  const q = useStash(channel);
  if (!q.data) return null;
  const { count, stale } = q.data;
  const text = `в копилке ${count}${stale ? ` · устарели: ${stale}` : ''}`;
  const props = {
    'data-testid': 'stash-count',
    'data-channel': channel,
    'data-count': count,
    className: cn('text-xs', count ? 'text-foreground' : 'text-muted-foreground', className),
  };
  return link ? (
    <Link
      to={`/publishing?channel=${encodeURIComponent(channel)}`}
      {...props}
      className={cn(props.className, 'w-max hover:text-primary-text hover:underline')}
    >
      {text}
    </Link>
  ) : (
    <span {...props}>{text}</span>
  );
}
