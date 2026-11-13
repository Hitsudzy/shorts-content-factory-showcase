// Shared pieces of the pages: a read in progress / a read that failed look the same in every block.
import type { UseQueryResult } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { BatchError } from '@/api/batchProblem';
import { SkeletonText } from '@/components/common/Skeletons';
import { ErrorState } from '@/components/common/States';

/**
 * Until the answer arrives - a skeleton of the same height as the block (`skeleton`, three lines of
 * text by default; `reading` is the screen-reader label); a refusal - in the factory's words;
 * otherwise - `children(data)` (CC-0121).
 */
export function Loaded<T>({
  q,
  reading,
  failed,
  skeleton,
  children,
}: {
  q: UseQueryResult<T, unknown>;
  reading: string;
  failed: string;
  /** The block's shape while reading: a preset from `Skeletons` with `label={reading}`. */
  skeleton?: ReactNode;
  children: (data: T) => ReactNode;
}) {
  // By default - four lines 17 px apart: that is how tall a typical block of facts is (136 px).
  if (q.isPending)
    return <>{skeleton ?? <SkeletonText lines={4} className="gap-[17px]" label={reading} />}</>;
  if (q.isError) return <Refused title={failed} error={q.error} onRetry={() => void q.refetch()} />;
  return <>{children(q.data)}</>;
}

/** A refusal of the API: the factory's line as is, the technical lines under "more". */
export function Refused({
  title,
  error,
  onRetry,
}: {
  title: string;
  error: unknown;
  onRetry?: () => void;
}) {
  const problem = error instanceof BatchError ? error.problem : null;
  return (
    <ErrorState
      title={title}
      error={problem ? [problem.code, ...problem.details].join(' · ') : error}
      onRetry={onRetry}
    >
      {problem ? problem.message : 'Проверьте, что API фабрики запущен.'}
    </ErrorState>
  );
}

/** A "label - value" row in a card. */
export function Fact({ label, children }: { label: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-0.5">
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className="m-0">{children}</dd>
    </div>
  );
}
