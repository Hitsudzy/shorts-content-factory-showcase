// Контекст тоста (провайдер — ./Toast.tsx): показать короткое подтверждение внизу экрана.
import { createContext, useContext } from 'react';

export type ToastTone = 'ok' | 'danger';

export const ToastContext = createContext<((text: string, tone?: ToastTone) => void) | null>(null);

/** Сколько тост висит, мс. */
export const TOAST_MS = 2200;

const noop = () => undefined;

/** Показать тост; вне провайдера — ничего (компонент не обязан знать, где он висит). */
export function useToast(): (text: string, tone?: ToastTone) => void {
  return useContext(ToastContext) ?? noop;
}
