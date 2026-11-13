// CC-0059: единственный способ нарисовать кнопку, которая пишет в фабрику. Когда API не на
// рабочей фабрике (`useWrites().allowed === false`), кнопка погашена (`aria-disabled`, клик
// и отправка формы не проходят), а тултип называет причину фабрики. Своя причина погасить
// (`why`: идёт батч, нет правок…) работает так же; `tip` — подсказка доступной кнопки.
import { cloneElement, type ComponentProps, type ReactElement, type ReactNode } from 'react';

import { readOnlyTip, useWrites } from '@/api/writes';
import { Button } from '@/components/ui/button';

import { Tip } from './Tip';

type Gated = ComponentProps<'button'> & { 'data-writes'?: string };

/**
 * Обёртка над одним элементом-кнопкой (`Button`, триггер окна): гасит его, если писать нельзя
 * или есть своя причина `why`. `ConfirmDialog` гасит так свой триггер сам.
 */
export function WriteGate({
  children,
  why,
  tip,
  wide = false,
}: {
  /** Один элемент-кнопка: ему ставятся `aria-disabled`, `type="button"` и глухой `onClick`. */
  children: ReactElement;
  why?: ReactNode;
  tip?: ReactNode;
  wide?: boolean;
}) {
  const w = useWrites();
  const reason = w.allowed ? why : readOnlyTip(w.reason ?? '');
  if (reason) {
    return (
      <Tip content={reason} wide={wide}>
        {cloneElement(children as ReactElement<Gated>, {
          disabled: false,
          'aria-disabled': true,
          'data-writes': w.allowed ? undefined : 'off',
          type: 'button',
          onClick: (e) => e.preventDefault(),
        })}
      </Tip>
    );
  }
  return tip ? (
    <Tip content={tip} wide={wide}>
      {children}
    </Tip>
  ) : (
    children
  );
}

/** `Button`, который пишет в фабрику: погашен вне рабочей фабрики (см. `WriteGate`). */
export function WriteButton({
  why,
  tip,
  ...props
}: ComponentProps<typeof Button> & { why?: ReactNode; tip?: ReactNode }) {
  return (
    <WriteGate why={why} tip={tip}>
      <Button {...props} />
    </WriteGate>
  );
}
