// «Ближайшие публикации» главной (CC-0138): слоты всех каналов на 3 дня вперёд — день, время по
// Москве, канал и ролик (название карточки дня, без неё — имя словами) или «свободно». Канал без
// слота — строкой «слот не задан». Данные — те же очереди, что у экрана «Публикация»
// (`GET /api/publish` и `…/{канал}/queue?days=14`); строка ведёт в его ленту.
import { Link } from 'react-router';

import {
  slotsWithNote,
  useNotesOf,
  usePublishOverview,
  useQueues,
  type ChannelQueue,
} from '@/api/publish';
import { nbDashes } from '@/api/humanText';
import { readableSlug, withoutHashtags } from '@/api/videos';
import { Card, CardHead } from '@/components/common/Card';
import { More } from '@/components/common/More';
import { SkeletonRows } from '@/components/common/Skeletons';
import { ErrorState } from '@/components/common/States';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { dateTimeMsk } from '@/pages/batches/format';
import { useChannelNames } from '@/pages/batches/names';
import { slotKey } from '@/pages/publishing/format';

import {
  freeSlotText,
  noteText,
  upcomingOf,
  UPCOMING_DAYS,
  wantsQueue,
  type UpcomingSlot,
} from './upcoming';

const href = (s: UpcomingSlot) => {
  const p = new URLSearchParams({ channel: s.channel });
  if (s.slug) p.set('slot', slotKey({ day: s.day, taken_by: s.slug }));
  return `/publishing?${p.toString()}`;
};

export function PublicationsCard({ className }: { className?: string }) {
  const o = usePublishOverview();
  const name = useChannelNames();
  const lines = o.data?.channels ?? [];
  const wanted = lines.filter(wantsQueue).map((l) => l.channel);
  const reads = useQueues(wanted);
  const queues = new Map<string, (typeof reads)[number]>(wanted.map((c, i) => [c, reads[i]!]));
  const u = upcomingOf(lines, (c) => {
    const r = queues.get(c);
    return r ? { data: r.data, pending: r.isPending, error: r.isError } : undefined;
  });
  const shown = new Set(u.slots.map((s) => `${s.channel}/${s.day}/${s.slug ?? ''}`));
  const cards = useNotesOf(
    reads
      .flatMap((r) => (r.data ? slotsWithNote(r.data).map((w) => ({ ...w, q: r.data })) : []))
      .filter((w) => shown.has(`${w.q.channel}/${w.day}/${w.slug}`))
      .map((w) => ({ channel: w.q.channel, slug: w.slug, day: w.day })),
  );
  const titleOf = (s: UpcomingSlot) => {
    if (!s.slug) return null;
    const t = cards(s.channel, s.day, s.slug)?.note?.title;
    // Тире названия не начинает строку на телефоне: пробел перед ним — неразрывный.
    return nbDashes((t && withoutHashtags(t)) || readableSlug(s.slug));
  };
  const failed = reads.find((r) => r.isError && !r.data);
  return (
    <Card
      aria-labelledby="publications-title"
      className={className}
      data-testid="publications-card"
      data-state={
        o.isPending || u.pending
          ? 'loading'
          : o.isError
            ? 'error'
            : u.slots.length
              ? 'slots'
              : 'empty'
      }
    >
      <CardHead
        eyebrow="Ближайшие публикации"
        title={`Очередь на ${UPCOMING_DAYS} дня`}
        titleId="publications-title"
        actions={
          <Button asChild variant="ghost">
            <Link to="/publishing">Лента слотов</Link>
          </Button>
        }
      />
      {o.isPending || (u.pending && !u.slots.length) ? (
        <SkeletonRows rows={3} height={44} gap={0} label="Читаю очередь публикаций…" />
      ) : o.isError ? (
        <ErrorState
          title="Очередь публикаций не прочитать"
          error={o.error}
          onRetry={() => void o.refetch()}
        />
      ) : !lines.length ? (
        <p className="m-0 text-muted-foreground" data-testid="publications-none">
          Каналов с публикацией пока нет.
        </p>
      ) : (
        <div className="grid gap-3">
          {u.slots.length ? (
            <ul className="m-0 grid list-none p-0" data-testid="publications-slots">
              {u.slots.map((s) => {
                const title = titleOf(s);
                return (
                  <li
                    key={`${s.channel}/${s.at}`}
                    data-testid="publications-slot"
                    data-channel={s.channel}
                    data-day={s.day}
                    data-slug={s.slug ?? ''}
                    className="border-t first:border-t-0"
                  >
                    <Link
                      to={href(s)}
                      className="grid grid-cols-[6.5rem_minmax(0,1fr)] items-start gap-x-3 rounded-sm py-2.5 outline-offset-2 hover:text-primary-text"
                    >
                      {/* Сначала день, под ним время; колонка — под самую длинную подпись («пн 12.10»,
                          «01:00 МСК»), чтобы названия всех строк начинались на одной линии. */}
                      <span className="grid gap-0.5 whitespace-nowrap">
                        <b
                          className="text-[15px] leading-tight font-semibold text-foreground"
                          data-testid="publications-when"
                        >
                          {s.when}
                        </b>
                        <span
                          className="font-mono text-[12.5px] text-muted-foreground"
                          data-testid="publications-time"
                        >
                          {`${s.time} ${s.zone}`.trim()}
                        </span>
                      </span>
                      <span className="grid min-w-0 gap-0.5">
                        <span
                          data-testid="publications-title"
                          className={cn(
                            'leading-tight font-semibold text-pretty [overflow-wrap:anywhere]',
                            !title && 'font-normal text-muted-foreground',
                          )}
                        >
                          {title ?? freeSlotText(s)}
                        </span>
                        <span
                          className="text-xs text-muted-foreground"
                          data-testid="publications-channel"
                        >
                          {name(s.channel)}
                        </span>
                      </span>
                    </Link>
                  </li>
                );
              })}
            </ul>
          ) : lines.some(wantsQueue) && !u.pending ? (
            <p className="m-0 text-muted-foreground" data-testid="publications-empty">
              На ближайшие {UPCOMING_DAYS} дня слотов нет.
            </p>
          ) : null}
          {u.notes.length ? (
            <ul
              className="m-0 grid list-none gap-1 p-0 text-[13px]"
              data-testid="publications-notes"
            >
              {u.notes.map((n) => (
                <li
                  key={n.channel}
                  data-testid="publications-note"
                  data-channel={n.channel}
                  data-kind={n.kind}
                  className={n.kind === 'broken' ? 'text-danger' : 'text-muted-foreground'}
                >
                  {nbDashes(`${name(n.channel)} — ${noteText(n)}`)}
                </li>
              ))}
            </ul>
          ) : null}
          {failed ? (
            <div>
              <Button size="sm" onClick={() => void failed.refetch()}>
                Повторить
              </Button>
            </div>
          ) : null}
          <More className="mt-0">
            <span>данные на {dateTimeMsk(o.data.as_of) ?? o.data.as_of}</span>
            {lines.map((l) => (
              <span key={l.channel}>
                {l.channel}: {l.error ?? l.tomorrow?.line ?? '—'}
              </span>
            ))}
            {reads.map((r) => (r.data ? <QueueDetails key={r.data.channel} q={r.data} /> : null))}
          </More>
        </div>
      )}
    </Card>
  );
}

function QueueDetails({ q }: { q: ChannelQueue }) {
  return q.pause_notices.length || q.paused ? (
    <>
      {q.paused ? <span>{`${q.channel}: ${q.paused}`}</span> : null}
      {q.pause_notices.map((n) => (
        <span key={n}>{`${q.channel}: ${n}`}</span>
      ))}
    </>
  ) : null;
}
