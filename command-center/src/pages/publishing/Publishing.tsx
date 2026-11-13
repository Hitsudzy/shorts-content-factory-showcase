// «Публикация» (CC-0067 — первый шаг экрана CC-0015): каналы с завтрашним слотом в строку
// (`GET /api/publish`), выбранный канал — лента слотов на 14 дней, карточка для Studio с
// «скопировать» у каждого поля, холды (только чтение) и состояние канала: пауза, переключатель
// API-загрузки, ротация, серия Studio. Канал и слот — в адресе (`?channel=…&slot=<день>/<имя>`).
// Записи без сети (CC-0068): пауза и ротация — в состоянии канала, карточка (разместить в слот,
// собрать из черновика) — под карточкой для Studio. CC-0069: переключатель API-загрузки — в
// состоянии канала, загрузка на YouTube и «загружено через Studio» — под карточкой для Studio.
// CC-0122: копилка канала (принятые без слота, размещение пачкой) — над лентой, «в копилке N» —
// у каждого канала; имя канала — в заголовках ленты и «Для Studio».
// CC-0148: «журнала загрузок нет» — одной строкой про фабрику над каналами (журнал один на всех).
import { Link, useSearchParams } from 'react-router';

import { BatchError } from '@/api/batchProblem';
import {
  defaultSlot,
  usePublishOverview,
  useNote,
  useQueue,
  useStudio,
  type PublishOverview,
  type QueueLine,
} from '@/api/publish';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { EmptyState, ErrorState } from '@/components/common/States';
import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';
import { dateTimeMsk } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { Avatar } from '@/pages/channels/identity';

import { CardWrites } from './CardWrites';
import { JOURNAL_MISSING } from './emptyDays';
import { ChannelStatus } from './ChannelStatus';
import { Feed } from './Feed';
import { lineState, mskDay, slotDay, slotKey, slotTime } from './format';
import { Holds } from './Holds';
import { Stash } from './Stash';
import { StashCount } from './StashCount';
import { StudioCard } from './StudioCard';
import { UploadWrites } from './UploadWrites';
import { Pending, SkeletonCard, SkeletonRows } from '@/components/common/Skeletons';

/** Канал по умолчанию: первый, у кого есть очередь (слот и читается); иначе первый. */
function defaultChannel(o: PublishOverview): string | null {
  return (o.channels.find((c) => c.slot && !c.error) ?? o.channels[0])?.channel ?? null;
}

/**
 * «Журнала загрузок нет» — одна строка про фабрику (CC-0148). Журнал один на всю фабрику
 * (publish/uploads.json), `journal_exists` у всех каналов один и тот же: читается у канала по
 * умолчанию (`useStudio`, тот же запрос, что у его состояния), чтобы при переключении каналов строка
 * не пропадала и не повторялась.
 */
function JournalMissing({ channel }: { channel: string }) {
  const studio = useStudio(channel);
  if (studio.data?.journal_exists !== false) return null;
  return (
    <p
      role="status"
      data-testid="journal-missing"
      className="m-0 flex items-start gap-2 rounded-lg border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-card px-3 py-2 text-[13px] font-medium text-pretty text-warning"
    >
      <span aria-hidden className="mt-[6px] size-[7px] shrink-0 rounded-full bg-warning" />
      <span className="min-w-0">{JOURNAL_MISSING}</span>
    </p>
  );
}

function lineSub(l: QueueLine, today: string): string {
  if (l.error) return 'Очередь канала не читается';
  if (!l.slot) return 'Слот публикации не задан';
  if (l.paused) return 'Публикации на паузе';
  const parts: string[] = [];
  if (l.next_free) {
    const { time } = slotTime(l.next_free);
    parts.push(`свободный слот: ${slotDay(l.next_free.day, today)}, ${time}`);
  } else parts.push('свободных слотов впереди нет');
  return parts.join(' · ');
}

function Channels({ o, current }: { o: PublishOverview; current: string }) {
  const name = useChannelNames();
  const today = mskDay(o.as_of);
  return (
    <Card aria-labelledby="channels-title" data-testid="publish-channels">
      <CardHead
        eyebrow={`Каналы · данные на ${dateTimeMsk(o.as_of) ?? o.as_of}`}
        title="Очереди публикации"
        titleId="channels-title"
      />
      <ul className="m-0 grid list-none gap-2 p-0 sm:grid-cols-3">
        {o.channels.map((l) => {
          const st = lineState(l);
          const on = l.channel === current;
          return (
            <li key={l.channel} data-testid="publish-channel" data-channel={l.channel}>
              <Link
                to={{ search: `?channel=${encodeURIComponent(l.channel)}` }}
                aria-current={on ? 'true' : undefined}
                className={cn(
                  'grid h-full grid-cols-[auto_minmax(0,1fr)] items-start gap-3 rounded-sm border p-3 outline-offset-2 hover:border-muted-foreground',
                  on &&
                    'border-primary bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] hover:border-primary',
                )}
              >
                <Avatar id={l.channel} name={name(l.channel)} />
                <span className="grid min-w-0 gap-1">
                  <span className="font-semibold">{name(l.channel)}</span>
                  <span className="text-xs text-muted-foreground">{lineSub(l, today)}</span>
                  <StashCount channel={l.channel} />
                  <span>
                    <StatusBadge tone={st.tone}>{st.label}</StatusBadge>
                  </span>
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
      <More>
        {o.channels.map((l) => (
          <span key={l.channel}>
            {l.channel}: {l.error ?? l.tomorrow?.line ?? '—'}
          </span>
        ))}
      </More>
    </Card>
  );
}

function ChannelPublishing({ channel }: { channel: string }) {
  const q = useQueue(channel);
  const [params] = useSearchParams();
  const asked = params.get('slot');
  const fallback = q.data ? defaultSlot(q.data) : undefined;
  const selected = asked ?? (fallback ? slotKey(fallback) : null);
  const [day, slug] = selected ? (selected.split('/') as [string, string]) : [null, null];
  // CC-0183: тёзки копилки: имя не единственно, какой из двух — `&batch=<id батча>` рядом со `slot`.
  const batch = (asked && params.get('batch')) || null;
  const note = useNote(channel, slug || null, day, batch);
  return (
    <>
      <Stash channel={channel} />
      <div className="grid gap-gap lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
        {q.isPending ? (
          <SkeletonCard rows={0} label="Читаю ленту слотов…">
            <SkeletonRows bare rows={6} height={44} />
          </SkeletonCard>
        ) : q.isError ? (
          <Card>
            <ErrorState
              title="Ленту слотов не прочитать"
              error={q.error}
              onRetry={() => void q.refetch()}
            >
              {q.error instanceof BatchError && q.error.problem
                ? 'Фабрика не смогла прочитать очередь канала.'
                : 'Проверьте, что API фабрики запущен.'}
            </ErrorState>
          </Card>
        ) : (
          <Feed q={q.data} selected={selected} />
        )}
        <div className="grid content-start gap-gap">
          <StudioCard channel={channel} slug={slug || null} day={day} batchId={batch} />
          <UploadWrites
            channel={channel}
            note={note.data}
            batchId={batch}
            selected={!!slug}
            failed={note.isError}
          />
          <CardWrites channel={channel} note={note.data} waiting={q.data?.waiting ?? []} />
        </div>
      </div>
      <div className="grid gap-gap md:grid-cols-2">
        <Holds channel={channel} />
        <ChannelStatus channel={channel} />
      </div>
    </>
  );
}

export function Publishing() {
  const overview = usePublishOverview();
  const [params] = useSearchParams();
  const channel = params.get('channel') ?? (overview.data ? defaultChannel(overview.data) : null);
  return (
    <>
      <div>
        <div className="eyebrow">Слоты, поля для Studio, холды</div>
        <h1 className="font-display text-[26px] font-semibold tracking-[.02em] uppercase">
          Публикация
        </h1>
      </div>
      {overview.isPending ? (
        <Pending label="Читаю очереди каналов…" className="gap-(--space-gap)">
          <SkeletonCard bare rows={2} />
          <SkeletonCard bare rows={0}>
            <SkeletonRows bare rows={3} height={64} />
          </SkeletonCard>
          <div className="grid gap-(--space-gap) lg:grid-cols-[minmax(0,1.15fr)_minmax(0,1fr)]">
            <SkeletonCard bare rows={0}>
              <SkeletonRows bare rows={6} height={44} />
            </SkeletonCard>
            <SkeletonCard bare rows={5} />
          </div>
        </Pending>
      ) : !overview.data ? (
        // CC-0164: упал только опрос — экран канала не пересоздаётся (отметки копилки, окна).
        <ErrorState
          title="Очереди публикации не прочитать"
          error={overview.error}
          onRetry={() => void overview.refetch()}
        >
          Проверьте, что API фабрики запущен.
        </ErrorState>
      ) : !channel ? (
        <EmptyState title="Каналов публикации нет">
          Ни у одного канала фабрики нет очереди публикации.
        </EmptyState>
      ) : (
        <>
          <JournalMissing channel={defaultChannel(overview.data) ?? channel} />
          <Channels o={overview.data} current={channel} />
          <ChannelPublishing key={channel} channel={channel} />
        </>
      )}
    </>
  );
}
