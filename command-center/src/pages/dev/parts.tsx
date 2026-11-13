// Общие кусочки «Разработки» (CC-0124): ссылка на задачу, метка статуса, полоса прогресса.
import { Fragment, type ReactNode } from 'react';
import { Link, useLocation } from 'react-router';

import { StatusBadge } from '@/components/common/Status';
import { cn } from '@/lib/utils';

import { splitIds } from './markdown';
import { statusWord } from './words';

/** Откуда открыли карточку: «← К списку» вернёт к тем же фильтрам. */
export type FromState = { from?: string };

/** Номер задачи — ссылка на её карточку `/dev/<id>`; фильтры списка — в `state`. */
export function TaskLink({
  id,
  children,
  className,
}: {
  id: string;
  children?: ReactNode;
  className?: string;
}) {
  const loc = useLocation();
  const from = (loc.state as FromState | null)?.from;
  const state: FromState = {
    from: loc.pathname.replace(/\/$/, '').endsWith('/dev') ? loc.search : from,
  };
  return (
    <Link
      to={`/dev/${encodeURIComponent(id)}`}
      state={state}
      data-testid="task-link"
      data-id={id}
      className={cn(
        'rounded-sm font-mono text-[0.95em] whitespace-nowrap text-primary-text underline-offset-2 hover:underline',
        className,
      )}
    >
      {children ?? id}
    </Link>
  );
}

/** Номер задачи — ссылка; диапазон (CC-0001…0037) — одним куском, не рвётся на дефисе. */
export function IdToken({ id, range }: { id: string; range?: string }) {
  if (!range) return <TaskLink id={id} />;
  return (
    <span className="whitespace-nowrap" data-testid="task-range">
      <TaskLink id={id} />
      <span className="font-mono text-[0.95em]">{range}</span>
    </span>
  );
}

/** Текст, где номера задач — ссылки (подписи коммитов). */
export function WithIds({ text }: { text: string }) {
  return (
    <>
      {splitIds(text).map((p, i) =>
        typeof p === 'string' ? (
          <Fragment key={i}>{p}</Fragment>
        ) : (
          <IdToken key={i} id={p.id} range={p.range} />
        ),
      )}
    </>
  );
}

/** Простой текст (заголовок), где номер задачи или диапазон не переносится на дефисе. */
export function IdText({ text }: { text: string }) {
  return (
    <>
      {splitIds(text).map((p, i) =>
        typeof p === 'string' ? (
          <Fragment key={i}>{p}</Fragment>
        ) : (
          <span key={i} className="whitespace-nowrap" data-testid="task-id-text">
            {p.id + (p.range ?? '')}
          </span>
        ),
      )}
    </>
  );
}

export function TaskStatus({
  status,
  className,
}: {
  status: string | null | undefined;
  className?: string;
}) {
  const w = statusWord(status);
  return (
    <StatusBadge
      tone={w.tone}
      // «Открыта» — живая задача: текст в полный цвет, не приглушённый (контраст на тёмной).
      // «Не делаем» — закрыта без работы: текст чуть тише, рамка пунктиром (контраст ≥ 4.5).
      className={cn(
        status === 'open' && 'border-muted-foreground/60 text-foreground',
        status === 'wontfix' &&
          'border-dashed border-muted-foreground/70 text-[color-mix(in_srgb,var(--foreground)_75%,var(--card))]',
        className,
      )}
    >
      <span data-testid="task-status" data-status={status ?? ''}>
        {w.label}
      </span>
    </StatusBadge>
  );
}

/** Полоса «сделано N из M»: доля — цветом «готово». */
export function Bar({ done, total, label }: { done: number; total: number; label: string }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={total}
      aria-valuenow={done}
      className="h-1.5 w-full min-w-16 overflow-hidden rounded-full bg-[color-mix(in_srgb,var(--muted-foreground)_18%,transparent)]"
    >
      <div className="h-full rounded-full bg-success" style={{ width: `${pct}%` }} />
    </div>
  );
}
