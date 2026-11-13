import * as React from 'react';
import * as TooltipPrimitive from '@radix-ui/react-tooltip';

import { cn } from '@/lib/utils';

// Компонент shadcn/ui (new-york), перенесён вручную (без сети). Цвета — как `#tip` макета:
// фон --popover, текст 12px, тень, без стрелки.

function TooltipProvider({
  delayDuration = 250,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Provider>) {
  return (
    <TooltipPrimitive.Provider
      data-slot="tooltip-provider"
      delayDuration={delayDuration}
      {...props}
    />
  );
}

function Tooltip(props: React.ComponentProps<typeof TooltipPrimitive.Root>) {
  return <TooltipPrimitive.Root data-slot="tooltip" {...props} />;
}

function TooltipTrigger(props: React.ComponentProps<typeof TooltipPrimitive.Trigger>) {
  return <TooltipPrimitive.Trigger data-slot="tooltip-trigger" {...props} />;
}

function TooltipContent({
  className,
  sideOffset = 8,
  collisionPadding = 8,
  children,
  ...props
}: React.ComponentProps<typeof TooltipPrimitive.Content>) {
  return (
    <TooltipPrimitive.Portal>
      <TooltipPrimitive.Content
        data-slot="tooltip-content"
        sideOffset={sideOffset}
        collisionPadding={collisionPadding}
        className={cn(
          'z-50 max-w-[260px] rounded-sm bg-popover px-[9px] py-1.5 text-xs text-popover-foreground shadow-[0_6px_24px_#0006]',
          // CC-0083: закрытая подсказка уходит из DOM сразу, без анимации выхода. Пока Radix
          // ждёт конец такой анимации (на занятой машине — сотни мс), невидимая уже подсказка
          // держит свой слой и съедает Escape (`preventDefault`): Escape человека не закрывал
          // просмотр мема. С `animation: none` Presence снимает её в том же коммите.
          'animate-in fade-in-0 data-[state=closed]:animate-none',
          className,
        )}
        {...props}
      >
        {children}
      </TooltipPrimitive.Content>
    </TooltipPrimitive.Portal>
  );
}

export { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger };
