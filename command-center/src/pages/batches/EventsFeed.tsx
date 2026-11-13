// Лента событий батча (CC-0045, `GET …/events` по курсору): последние строки
// RUN_EVENTS.jsonl, новые сверху. Опрос идёт, только пока лента раскрыта (и вкладка видна);
// в памяти — не больше EVENTS_KEEP строк; `reset` фабрики — лента начинается заново.
// Строка — одна на событие (CC-0118): «время · стадия · тема · итог» словами, на узком экране
// усекается многоточием; слаги, id шагов и коды итога — под «подробнее» под лентой.
// Жирные строки — отметки стадий (`kind: marker`): под лентой — легенда (CC-0126).
import { useMemo, useState } from 'react';

import type { BatchTopics } from '@/api/batchTopics';
import { useBatchEvents } from '@/api/batches';
import { EVENTS_KEEP } from '@/api/eventsFeed';
import { More } from '@/components/common/More';
import type { Tone } from '@/components/common/Status';
import { cn } from '@/lib/utils';

import { Refusal } from './parts';
import { eventParts, topicNames } from './words';
import { SkeletonRows } from '@/components/common/Skeletons';

const TONE_TEXT: Record<Tone, string> = {
  ok: 'text-success',
  live: 'text-primary-text',
  warn: 'text-warning',
  danger: 'text-danger',
  idle: 'text-muted-foreground',
};

/** Сколько последних строк показывать на экране (в памяти — до EVENTS_KEEP). */
const SHOWN = 100;

function Feed({ batch, topics }: { batch: string; topics?: BatchTopics }) {
  const feed = useBatchEvents(batch);
  const names = useMemo(() => topicNames(topics), [topics]);
  if (feed.isPending)
    return (
      <SkeletonRows
        rows={6}
        height={27}
        gap={0}
        bordered={false}
        className="rounded-sm border bg-background px-3"
        label="Читаю события…"
      />
    );
  if (feed.isError && !feed.data) return <Refusal error={feed.error} title="События не читаются" />;
  const lines = feed.data.lines;
  const shown = lines
    .slice(-SHOWN)
    .reverse()
    .map((e) => ({ e, p: eventParts(e, names) }));
  return (
    <div className="grid gap-2">
      {feed.data.resets ? (
        <p role="status" data-testid="events-reset" className="m-0 text-xs text-warning">
          Файл событий начался заново — лента перечитана с начала нового файла.
        </p>
      ) : null}
      {shown.length ? (
        <ol
          data-testid="events-list"
          className="m-0 grid max-h-72 list-none gap-0 overflow-y-auto rounded-sm border bg-background p-0 text-xs"
        >
          {shown.map(({ e, p }) => {
            const what = p.note ? `${p.what} (${p.note})` : p.what;
            return (
              <li
                key={e.offset}
                data-testid="event-line"
                data-offset={e.offset}
                data-marker={p.marker || undefined}
                title={[p.time, p.marker ? 'отметка стадии' : null, what, p.result?.label]
                  .filter(Boolean)
                  .join(' · ')}
                className={cn(
                  'flex items-baseline gap-2 border-t px-2.5 py-1 whitespace-nowrap first:border-t-0',
                  p.marker && 'font-semibold text-primary-text',
                )}
              >
                <span className="shrink-0 font-mono text-[11.5px] text-muted-foreground tabular-nums">
                  {p.time}
                </span>
                <span className="min-w-0 flex-1 truncate">{what}</span>
                {p.result ? (
                  <span
                    data-testid="event-result"
                    className={cn('shrink-0', TONE_TEXT[p.result.tone])}
                  >
                    {p.result.label}
                  </span>
                ) : null}
              </li>
            );
          })}
        </ol>
      ) : (
        <p className="m-0 text-muted-foreground">Событий пока нет.</p>
      )}
      {shown.some((x) => x.p.marker) ? (
        <p className="m-0 text-xs text-muted-foreground" data-testid="events-legend">
          <b className="font-semibold text-primary-text">Жирным</b> — отметки стадий: стадия
          началась или закончилась. Остальные строки — шаги внутри стадии.
        </p>
      ) : null}
      <p className="m-0 text-xs text-muted-foreground" data-testid="events-count">
        {lines.length > SHOWN
          ? `Показаны последние ${SHOWN} из ${lines.length} строк в памяти`
          : `Строк: ${lines.length}`}
        {feed.data.dropped ? ` · старше выброшены (держу последние ${EVENTS_KEEP})` : null}
      </p>
      {shown.length ? (
        <More className="mt-0" label="Подробнее: строки как есть">
          {shown.map(({ e, p }) => (
            <span key={e.offset}>
              {p.time} {p.raw}
            </span>
          ))}
        </More>
      ) : null}
    </div>
  );
}

/** Раскрывающаяся лента: открыта сразу у идущего батча, опрос — только пока открыта. */
export function EventsFeed({
  batch,
  open: initial,
  topics,
}: {
  batch: string;
  open: boolean;
  topics?: BatchTopics;
}) {
  const [open, setOpen] = useState(initial);
  return (
    <details
      open={open}
      onToggle={(e) => setOpen(e.currentTarget.open)}
      data-testid="events-feed"
      className="mt-3"
    >
      <summary className="w-max cursor-pointer text-[13px] font-semibold">События батча</summary>
      <div className="mt-2">{open ? <Feed batch={batch} topics={topics} /> : null}</div>
    </details>
  );
}
