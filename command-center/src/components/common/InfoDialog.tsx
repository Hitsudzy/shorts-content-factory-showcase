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
import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';
import { cn } from '@/lib/utils';

import { useMoreBelow } from './useMoreBelow';

/**
 * Окно «только прочитать» (CC-0125, разбор оценки ролика): тот же вид, что у `ConfirmDialog`, —
 * липкий подвал с «Закрыть» и «Ниже ещё ↓», пока ниже есть текст, — но без записи. Окно
 * закрылось — фокус возвращается на кнопку, её подсказка не всплывает поверх страницы.
 */
export function InfoDialog({
  open,
  onOpenChange,
  trigger,
  tip,
  title,
  description,
  children,
  testId,
  wide = false,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  trigger: ReactElement;
  /** Подсказка к кнопке, что открывает окно. */
  tip?: ReactNode;
  title: string;
  description?: ReactNode;
  children?: ReactNode;
  testId?: string;
  /** Шире обычного (разбор с длинными строками). */
  wide?: boolean;
}) {
  const [tipOpen, setTipOpen] = useState(false);
  const quiet = useRef(false);
  const [body, setBody] = useState<HTMLDivElement | null>(null);
  const below = useMoreBelow(body);
  const opener = <AlertDialogTrigger asChild>{trigger}</AlertDialogTrigger>;
  return (
    <AlertDialog open={open} onOpenChange={onOpenChange}>
      {tip ? (
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
        data-testid={testId}
        className={cn(wide && 'max-w-xl')}
        onCloseAutoFocus={() => {
          setTipOpen(false);
          quiet.current = true;
          setTimeout(() => (quiet.current = false), 0);
        }}
      >
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          {description ? (
            <AlertDialogDescription>{description}</AlertDialogDescription>
          ) : (
            <AlertDialogDescription className="sr-only">{title}</AlertDialogDescription>
          )}
        </AlertDialogHeader>
        {children}
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
          <AlertDialogCancel data-testid="dialog-close">Закрыть</AlertDialogCancel>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}
