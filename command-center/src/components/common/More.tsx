import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * «Подробнее»: сюда и только сюда прячутся номера задач, пути, коммиты и прочие
 * идентификаторы (ROADMAP → Правила → «Для человека»). Моноширинно, переносится по символам.
 */
export function More({
  children,
  label = 'Подробнее',
  className,
  onToggle,
}: {
  children: ReactNode;
  label?: string;
  className?: string;
  /** Раскрыли или свернули — например, чтобы читать журнал только раскрытым. */
  onToggle?: (open: boolean) => void;
}) {
  return (
    <details
      data-slot="more"
      onToggle={onToggle ? (e) => onToggle(e.currentTarget.open) : undefined}
      data-tour="more"
      className={cn('mt-3 text-xs text-muted-foreground', className)}
    >
      <summary className="w-max cursor-pointer text-primary-text">{label}</summary>
      <div className="mt-1.5 grid gap-0.5 font-mono [overflow-wrap:anywhere]">{children}</div>
    </details>
  );
}
