import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { Tip } from './Tip';

/** Смысл статуса: «готов», «холд», «остановлено», «ждёт», «идёт сейчас». */
export type Tone = 'ok' | 'warn' | 'danger' | 'idle' | 'live';

const BADGE_TONE: Record<Tone, string> = {
  ok: 'text-success border-[color-mix(in_srgb,var(--success)_40%,var(--border))]',
  warn: 'text-warning border-[color-mix(in_srgb,var(--warning)_40%,var(--border))]',
  danger: 'text-danger border-[color-mix(in_srgb,var(--danger)_40%,var(--border))]',
  idle: 'text-muted-foreground border-border',
  live: 'text-primary-text border-[color-mix(in_srgb,var(--primary)_40%,var(--border))]',
};

const DOT_TONE: Record<Tone, string> = {
  ok: 'bg-success',
  warn: 'bg-warning',
  danger: 'bg-danger',
  idle: 'bg-muted-foreground',
  live: 'bg-primary pulse-dot',
};

/** Статус-метка (`.state` макета): короткое слово в рамке цвета смысла, с подсказкой. */
export function StatusBadge({
  tone,
  tip,
  children,
  className,
}: {
  tone: Tone;
  tip?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  const badge = (
    <span
      data-slot="status"
      data-tone={tone}
      tabIndex={tip ? 0 : undefined}
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs whitespace-nowrap',
        BADGE_TONE[tone],
        className,
      )}
    >
      {children}
    </span>
  );
  return tip ? <Tip content={tip}>{badge}</Tip> : badge;
}

/** Пилюля с точкой (`.pill` макета) — статусы в шапке. */
export function StatusPill({
  tone,
  tip,
  children,
  className,
  ...rest
}: {
  tone: Tone;
  tip?: ReactNode;
  children: ReactNode;
  className?: string;
  'data-testid'?: string;
}) {
  const pill = (
    <span
      data-tone={tone}
      tabIndex={tip ? 0 : undefined}
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-[3px] text-xs whitespace-nowrap text-muted-foreground',
        className,
      )}
      {...rest}
    >
      <span aria-hidden className={cn('size-[7px] shrink-0 rounded-full', DOT_TONE[tone])} />
      {children}
    </span>
  );
  return tip ? <Tip content={tip}>{pill}</Tip> : pill;
}
