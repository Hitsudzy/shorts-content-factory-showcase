// CC-0059: режим записи в шапке — плашка «Только смотреть», когда API не на рабочей фабрике,
// и значок «режим разработки», когда рабочая копия пишет по флагу `CC_API_WRITES=dev`.
import { plainReason, useWrites, useWritesRefusalWatch } from '@/api/writes';
import { StatusPill } from '@/components/common/Status';
import { cn } from '@/lib/utils';

/** Плашка под строкой шапки; заодно слушает отказы `not_working_factory` посреди сессии. */
export function ReadOnlyBanner({ className }: { className?: string }) {
  useWritesRefusalWatch();
  const w = useWrites();
  if (w.allowed) return null;
  const raw = w.reason ?? '';
  const plain = plainReason(raw);
  return (
    <div
      role="status"
      data-testid="read-only-banner"
      data-tour="read-only"
      className="border-t border-[color-mix(in_srgb,var(--warning)_40%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_10%,var(--background))]"
    >
      <div className={cn('grid gap-1 py-2 text-[13px]', className)}>
        {/* Причина простыми словами, на телефоне — в две строки; строка фабрики — под «что это значит». */}
        <p className="m-0 [overflow-wrap:anywhere]">
          <b className="font-semibold text-warning">Только смотреть:</b>{' '}
          <span data-testid="read-only-reason">{plain}</span>
        </p>
        <details className="text-xs text-muted-foreground" data-testid="read-only-more">
          <summary className="w-max cursor-pointer text-primary-text">Что это значит</summary>
          <p className="m-0 mt-1 max-w-[72ch]">
            Этот API запущен не на рабочей фабрике (её основной копии на ветке main), поэтому центр
            ничего в фабрике не меняет: сохранение и откат каналов, создание канала, рубильник,
            окна, запуск, остановка и продолжение батчей, вердикты приёмки роликов выключены.
            Смотреть можно всё, проверки правок работают. Причина — слово самой фабрики. Чтобы
            менять, откройте центр, запущенный на рабочей фабрике.
          </p>
          {plain !== raw ? (
            <p
              className="m-0 mt-1 font-mono [overflow-wrap:anywhere]"
              data-testid="read-only-reason-raw"
            >
              Строка фабрики: {raw}
            </p>
          ) : null}
        </details>
      </div>
    </div>
  );
}

/** Значок «режим разработки»: пишет рабочая копия по флагу `CC_API_WRITES=dev`. */
export function DevWritesBadge({ className }: { className?: string }) {
  const w = useWrites();
  if (!w.allowed || !w.dev) return null;
  return (
    <StatusPill
      tone="warn"
      data-testid="writes-dev"
      className={className}
      tip={`Записи разрешены флагом разработки CC_API_WRITES=dev: центр меняет не рабочую фабрику, а ту копию, где запущен API${w.devReason ? ` — ${w.devReason}` : ''}`}
    >
      режим разработки
    </StatusPill>
  );
}
