import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';

import { cn } from '@/lib/utils';

// Компонент shadcn/ui (стиль new-york), перенесён вручную, чтобы сборка не зависела от сети;
// варианты подогнаны под кнопки макета «Кинозал» (`.btn`, `.btn.primary`, `.btn.ghost`,
// `.btn.danger-ghost`, `.icon-btn` в docs/mockups/a-kinozal.html).
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-1.5 rounded-lg border text-[13px] font-medium whitespace-nowrap transition-colors outline-none motion-reduce:transition-none disabled:pointer-events-none disabled:opacity-50 aria-disabled:cursor-not-allowed aria-disabled:opacity-60 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default:
          'border-primary bg-primary font-semibold text-primary-foreground hover:bg-primary/90 dark:disabled:opacity-35',
        outline: 'border-border bg-card hover:border-muted-foreground',
        ghost: 'border-border bg-transparent hover:border-muted-foreground',
        destructive:
          'border-[color-mix(in_srgb,var(--danger)_40%,var(--border))] bg-transparent text-danger hover:border-danger',
        link: 'border-transparent text-primary-text underline-offset-4 hover:underline',
      },
      size: {
        default: 'h-[34px] px-3',
        sm: 'h-[28px] px-2.5 text-xs',
        icon: 'size-[34px] bg-card',
      },
    },
    defaultVariants: {
      variant: 'outline',
      size: 'default',
    },
  },
);

function Button({
  className,
  variant,
  size,
  asChild = false,
  type = 'button',
  ...props
}: React.ComponentProps<'button'> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot : 'button';

  return (
    <Comp
      data-slot="button"
      type={asChild ? undefined : type}
      className={cn(buttonVariants({ variant, size, className }))}
      {...props}
    />
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export { Button, buttonVariants };
