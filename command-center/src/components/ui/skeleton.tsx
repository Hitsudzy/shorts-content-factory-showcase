import type { ComponentProps } from 'react';

import { cn } from '@/lib/utils';

// Компонент shadcn/ui (стиль new-york), перенесён вручную. Цвет — токен темы `--skeleton`
// (свет/тьма, src/index.css), пульсация гасится при `prefers-reduced-motion` (CC-0121).
// Сама полоска для читалки не видна: что идёт загрузка, говорит обёртка `Pending`
// (src/components/common/Skeletons.tsx) — role="status" и «Загружаю…».
function Skeleton({ className, ...props }: ComponentProps<'span'>) {
  return (
    <span
      data-slot="skeleton"
      aria-hidden="true"
      className={cn(
        'block animate-pulse rounded-sm bg-skeleton motion-reduce:animate-none',
        className,
      )}
      {...props}
    />
  );
}

export { Skeleton };
