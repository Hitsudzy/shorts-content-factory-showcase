import type { ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

import { More } from './More';

/**
 * «Скоро»: раздел или блок, которому ещё нет данных в API. Говорит простыми словами, в какой
 * версии центра он появится. `page` — во весь экран (заглушка таба), иначе — внутри карточки.
 */
export function Soon({
  version,
  title,
  children,
  page = false,
  className,
}: {
  version: string;
  title?: ReactNode;
  children: ReactNode;
  page?: boolean;
  className?: string;
}) {
  const Heading = page ? 'h1' : 'h3';
  return (
    <div
      data-slot="soon"
      className={cn(
        'grid justify-items-center gap-2 text-center',
        page ? 'px-6 py-14' : 'rounded-sm border border-dashed px-4 py-6',
        className,
      )}
    >
      <div className="eyebrow text-primary-text">Скоро · версия {version}</div>
      {title ? (
        <Heading className={cn('font-semibold text-balance', page ? 'text-[17px]' : 'text-sm')}>
          {title}
        </Heading>
      ) : null}
      <p className="m-0 max-w-[46ch] text-muted-foreground">{children}</p>
    </div>
  );
}

/** Пусто: данные пришли, но показывать нечего. */
export function EmptyState({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div
      data-slot="empty"
      className="grid justify-items-center gap-1 rounded-sm border border-dashed px-4 py-6 text-center"
    >
      <div className="text-sm font-semibold">{title}</div>
      {children ? <p className="m-0 max-w-[46ch] text-muted-foreground">{children}</p> : null}
    </div>
  );
}

/**
 * Ошибка загрузки: что не так — по-человечески, техническая причина — под «подробнее»,
 * и кнопка «Повторить», если повтор имеет смысл.
 */
export function ErrorState({
  title,
  children,
  error,
  onRetry,
}: {
  title: ReactNode;
  children?: ReactNode;
  error?: unknown;
  onRetry?: () => void;
}) {
  const detail = error instanceof Error ? error.message : error ? String(error) : null;
  return (
    <div
      role="alert"
      data-slot="error"
      className="grid gap-2 rounded-sm border border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-[color-mix(in_srgb,var(--danger)_7%,var(--card))] p-3"
    >
      <div className="font-semibold text-danger">{title}</div>
      {children ? <p className="m-0 text-muted-foreground">{children}</p> : null}
      {onRetry ? (
        <div>
          <Button size="sm" onClick={onRetry}>
            Повторить
          </Button>
        </div>
      ) : null}
      {detail ? (
        <More className="mt-0">
          <span>{detail}</span>
        </More>
      ) : null}
    </div>
  );
}
