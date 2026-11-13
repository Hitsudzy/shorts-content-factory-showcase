import type { ComponentProps, ReactNode } from 'react';

import { cn } from '@/lib/utils';

/** Карточка обзора (`.card` макета). */
export function Card({ className, ...props }: ComponentProps<'section'>) {
  return (
    <section
      className={cn('min-w-0 rounded-lg border bg-card p-card text-card-foreground', className)}
      {...props}
    />
  );
}

/**
 * Имя собственное в подписи капителью (CC-0131): имя канала, банка, батча не капсится —
 * «Лента слотов · ExampleFilm», а не «… · EXAMPLE_FILM».
 */
export function Keep({ className, ...props }: ComponentProps<'span'>) {
  return <span className={cn('normal-case', className)} {...props} />;
}

/** Шапка карточки: подпись капителью, заголовок и действия справа. */
export function CardHead({
  eyebrow,
  title,
  actions,
  titleId,
}: {
  eyebrow: ReactNode;
  title: ReactNode;
  actions?: ReactNode;
  titleId?: string;
}) {
  return (
    <div className="mb-3.5 flex flex-wrap items-start justify-between gap-3">
      <div className="min-w-0">
        <div className="eyebrow">{eyebrow}</div>
        <h2 id={titleId} className="mt-0.5 text-[17px] font-semibold text-balance">
          {title}
        </h2>
      </div>
      {actions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
