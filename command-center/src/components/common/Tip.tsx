import type { ReactElement, ReactNode } from 'react';

import { Tooltip, TooltipContent, TooltipTrigger } from '@/components/ui/tooltip';

/**
 * Подсказка к элементу: показывается при наведении и при фокусе с клавиатуры.
 * Ребёнок — один элемент, способный держать фокус (кнопка, ссылка или `tabIndex={0}`).
 * `TooltipProvider` висит в Layout.
 */
export function Tip({
  content,
  children,
  side = 'bottom',
  wide = false,
}: {
  content: ReactNode;
  children: ReactElement;
  side?: 'top' | 'bottom' | 'left' | 'right';
  /** Длинное пояснение (поле конфига): шире и с переносами абзаца. */
  wide?: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent
        side={side}
        className={wide ? 'max-w-[min(360px,90vw)] leading-[1.45]' : undefined}
      >
        {content}
      </TooltipContent>
    </Tooltip>
  );
}
