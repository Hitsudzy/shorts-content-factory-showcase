// Место тренировки в шапке (CC-0073) — в основном куске, но без демо-кода: плашка и панель
// заданий грузятся лениво, только если вкладка в тренировке. Не запустилась — короткая строка,
// что центр открыт с живыми данными.
import { lazy, Suspense, useState } from 'react';

import { cn } from '@/lib/utils';

import { trainingState } from './mode';

const TrainingLayer = lazy(() => import('./TrainingLayer'));

export const BANNER_TEXT = 'Тренировка — это демо, фабрика не трогается';

/** Пока панель грузится — та же плашка, без кнопок: смысл виден с первого кадра. */
function BannerFallback({ className }: { className?: string }) {
  return (
    <div
      data-testid="training-banner"
      className="border-t border-[color-mix(in_srgb,var(--primary)_45%,var(--border))] bg-[color-mix(in_srgb,var(--primary)_12%,var(--background))]"
    >
      <p className={cn('m-0 py-2 text-[13px] font-semibold', className)}>{BANNER_TEXT}</p>
    </div>
  );
}

export function TrainingSlot({ className }: { className?: string }) {
  const s = trainingState();
  const [hidden, setHidden] = useState(false);
  if (s.mode === 'training')
    return (
      <Suspense fallback={<BannerFallback className={className} />}>
        <TrainingLayer className={className} />
      </Suspense>
    );
  if (!s.failed || hidden) return null;
  return (
    <div
      role="status"
      data-testid="training-failed"
      className="border-t border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_10%,var(--background))]"
    >
      <div
        className={cn('flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-[13px]', className)}
      >
        <p className="m-0 min-w-0 flex-1 [overflow-wrap:anywhere]">
          <b className="font-semibold text-warning">Тренировка не запустилась:</b> {s.failed}. Центр
          открыт с живыми данными.
        </p>
        <button
          type="button"
          className="cursor-pointer text-xs text-primary-text underline-offset-4 hover:underline"
          onClick={() => setHidden(true)}
        >
          Понятно
        </button>
      </div>
    </div>
  );
}
