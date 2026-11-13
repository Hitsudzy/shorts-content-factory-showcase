import { cn } from '@/lib/utils';

/**
 * Счётчик (`.badge` макета): число в акцентном кружке — на табе «Вопросы» и на «К вопросам».
 * Ноль и неизвестное (`null`) не рисуются. `label` — что считается, для экранного диктора;
 * `decorative` — число скрыто от диктора (имя таба остаётся «Вопросы», счёт — в его тултипе).
 */
export function CountBadge({
  n,
  label,
  small = false,
  decorative = false,
  className,
}: {
  n: number | null | undefined;
  label: string;
  small?: boolean;
  decorative?: boolean;
  className?: string;
}) {
  if (!n) return null;
  return (
    <span
      data-slot="count"
      aria-label={decorative ? undefined : `${label}: ${n}`}
      aria-hidden={decorative || undefined}
      className={cn(
        'inline-grid place-items-center rounded-full bg-primary px-[5px] font-mono font-semibold text-primary-foreground',
        small ? 'h-4 min-w-4 text-[10px]' : 'h-[18px] min-w-[18px] text-[11px]',
        className,
      )}
    >
      {n}
    </span>
  );
}
