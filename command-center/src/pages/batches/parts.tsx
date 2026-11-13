// Общие куски экрана «Батчи» (CC-0050…0052): отказ фабрики, имена каналов, строки сведений.
import type { ReactNode } from 'react';

import { BatchError } from '@/api/batchProblem';
import { More } from '@/components/common/More';
import { Tip } from '@/components/common/Tip';
import { cn } from '@/lib/utils';

/**
 * Отказ фабрики: её `message` — как есть, `details` и код — под «подробнее». Не её отказ
 * (сеть, 5xx без тела) — общими словами.
 */
export function Refusal({
  error,
  title,
  className,
  message,
}: {
  error: unknown;
  title?: string;
  className?: string;
  /** Своя строка вместо строки фабрики (та — под «подробнее»). */
  message?: ReactNode;
}) {
  const problem = error instanceof BatchError ? error.problem : null;
  const tech = error instanceof Error ? error.message : String(error);
  return (
    <div
      role="alert"
      data-slot="refusal"
      data-code={problem?.code}
      className={cn(
        'grid gap-1 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-3 text-[13px]',
        className,
      )}
    >
      {title ? <div className="font-semibold text-danger">{title}</div> : null}
      <p className="m-0" data-testid="refusal-message">
        {message ??
          (problem ? problem.message : 'Фабрика не ответила как положено. Попробуйте ещё раз.')}
      </p>
      <More className="mt-0.5">
        {problem ? <span>код: {problem.code}</span> : null}
        {problem && message ? <span>фабрика: {problem.message}</span> : null}
        {problem ? problem.details.map((d, i) => <span key={i}>{d}</span>) : <span>{tech}</span>}
      </More>
    </div>
  );
}

/** Строка «подпись — значение» карточки (как в обзоре каналов), подпись — с подсказкой. */
export function Row({
  label,
  tip,
  children,
  testId,
}: {
  label: string;
  tip?: string;
  children: ReactNode;
  testId?: string;
}) {
  return (
    <li
      data-testid={testId}
      className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 border-t py-[9px] first:border-t-0 first:pt-0"
    >
      {tip ? (
        <Tip content={tip}>
          <span
            tabIndex={0}
            className="w-max max-w-full text-muted-foreground underline decoration-dotted underline-offset-4"
          >
            {label}
          </span>
        </Tip>
      ) : (
        <span className="text-muted-foreground">{label}</span>
      )}
      <span className="min-w-0 text-right">{children}</span>
    </li>
  );
}
