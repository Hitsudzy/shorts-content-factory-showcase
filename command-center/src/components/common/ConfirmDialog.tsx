import { useRef, useState, type ReactElement, type ReactNode } from 'react';

import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog';
import { useWrites } from '@/api/writes';
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

import { useMoreBelow } from './useMoreBelow';
import { WriteButton, WriteGate } from './WriteButton';

/**
 * Подтверждение действия, которое ждёт ответа фабрики: в отличие от `ConfirmAction`, окно не
 * закрывается на «да» само — его закрывает тот, кто держит `open`, когда фабрика согласилась.
 * Отказ (`error`) показывается тут же, в окне, а введённое (`children`: заметка и т. п.) остаётся.
 * Окно — для записи в фабрику (CC-0059): вне рабочей фабрики триггер погашен с причиной и окно
 * не открывается (ни плана, ни токена не просим); «да» — `WriteButton`.
 * CC-0087: окно закрылось — фокус возвращается на кнопку, но её подсказка не всплывает (иначе
 * она висит поверх итога записи). Длинное окно прокручивается под липким подвалом — пока ниже
 * есть ещё текст, над подвалом видно «Ниже ещё ↓».
 */
export function ConfirmDialog({
  open,
  onOpenChange,
  trigger,
  title,
  description,
  children,
  error,
  confirmLabel,
  pendingLabel,
  pending = false,
  danger = false,
  confirmDisabled = false,
  confirmTestId,
  tip,
  extraActions,
  onConfirm,
  onCloseAutoFocus,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactElement;
  title: string;
  description: ReactNode;
  children?: ReactNode;
  /** Отказ фабрики — показывается в окне, окно остаётся открытым. */
  error?: ReactNode;
  confirmLabel: string;
  pendingLabel?: string;
  pending?: boolean;
  danger?: boolean;
  /** «Да» недоступно (нет токена, истёк срок…), окно открыто. */
  confirmDisabled?: boolean;
  confirmTestId?: string;
  /** Подсказка к кнопке, что открывает окно. */
  tip?: ReactNode;
  /** Ещё кнопки рядом с «Отмена» (например, «Проверить заново»). */
  extraActions?: ReactNode;
  onConfirm: () => void;
  /** Окно закрылось — куда вернуть фокус (`preventDefault` — не на кнопку, что его открыла). */
  onCloseAutoFocus?: (e: Event) => void;
}) {
  const writes = useWrites();
  const [tipOpen, setTipOpen] = useState(false);
  // Фокус, который окно вернуло на кнопку при закрытии, подсказку не открывает.
  const quiet = useRef(false);
  const [body, setBody] = useState<HTMLDivElement | null>(null);
  const below = useMoreBelow(body);
  const opener = <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>;
  return (
    <AlertDialog open={open} onOpenChange={(v) => (pending ? undefined : onOpenChange(v))}>
      {!writes.allowed ? (
        <WriteGate>{trigger}</WriteGate>
      ) : tip ? (
        <Tooltip
          open={tipOpen && !open}
          onOpenChange={(v) => setTipOpen(v && !quiet.current && !open)}
        >
          <TooltipTrigger asChild>{opener}</TooltipTrigger>
          <TooltipContent side="bottom">{tip}</TooltipContent>
        </Tooltip>
      ) : (
        opener
      )}
      <AlertDialogContent
        ref={setBody}
        onCloseAutoFocus={(e) => {
          setTipOpen(false);
          quiet.current = true;
          setTimeout(() => (quiet.current = false), 0);
          onCloseAutoFocus?.(e);
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        {children}
        {error}
        <AlertDialogFooter>
          {below ? (
            <div
              aria-hidden
              data-testid="dialog-more-below"
              className="pointer-events-none absolute inset-x-0 bottom-full flex h-8 items-center justify-center border-t bg-card text-[13px] font-medium text-foreground shadow-[0_-10px_14px_-6px_var(--card)]"
            >
              Ниже ещё ↓
            </div>
          ) : null}
          <AlertDialogCancel disabled={pending}>Отмена</AlertDialogCancel>
          {extraActions}
          <WriteButton
            variant={danger ? 'destructive' : 'default'}
            disabled={pending || confirmDisabled}
            data-testid={confirmTestId}
            aria-busy={pending || undefined}
            onClick={onConfirm}
          >
            {pending ? (pendingLabel ?? confirmLabel) : confirmLabel}
          </WriteButton>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
