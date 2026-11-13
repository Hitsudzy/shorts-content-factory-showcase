import { cn } from '@/lib/utils';

/**
 * Заметная строка-предупреждение: рамка цвета warning, точка слева (как «Журнала загрузок нет» на
 * «Публикации», CC-0148). Жирный — только заголовок (что случилось); что делать (`action`) —
 * обычным начертанием, как у полос «Агенты расходятся с пинами» и «API на старом коде».
 * Подробности — в «Подробнее» рядом, не здесь.
 */
export function WarnLine({
  title,
  action,
  testId,
  className,
}: {
  title: string;
  action?: string | null;
  testId?: string;
  className?: string;
}) {
  return (
    <p
      role="status"
      data-testid={testId}
      className={cn(
        'm-0 flex items-start gap-2 rounded-lg border border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-card px-3 py-2 text-[13px] text-pretty',
        className,
      )}
    >
      <span aria-hidden className="mt-[6px] size-[7px] shrink-0 rounded-full bg-warning" />
      <span className="min-w-0 [overflow-wrap:anywhere]">
        <b className="font-semibold text-warning" data-testid="warn-title">
          {title}
        </b>
        {action ? (
          <>
            {' '}
            <span className="font-normal text-muted-foreground">{action}</span>
          </>
        ) : null}
      </span>
    </p>
  );
}
