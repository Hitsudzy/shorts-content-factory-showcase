// Тост (`#toast` макета «Кинозал»): короткое подтверждение внизу экрана, само гаснет. Живая
// область `role="status"` — экранный диктор прочтёт его и без фокуса. Провайдер висит в Layout.
import { useCallback, useEffect, useRef, useState } from 'react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

import { TOAST_MS, ToastContext, type ToastTone } from './useToast';

type Toast = { id: number; text: string; tone: ToastTone };

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toast, setToast] = useState<Toast | null>(null);
  const seq = useRef(0);
  const show = useCallback((text: string, tone: ToastTone = 'ok') => {
    seq.current += 1;
    setToast({ id: seq.current, text, tone });
  }, []);
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(null), TOAST_MS);
    return () => clearTimeout(t);
  }, [toast]);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div
        role="status"
        aria-live="polite"
        data-testid="toast"
        data-tone={toast?.tone}
        className={cn(
          'pointer-events-none fixed bottom-[max(24px,var(--toast-offset,0px))] left-1/2 z-[60] max-w-[min(92vw,420px)] -translate-x-1/2 rounded-lg bg-popover px-3.5 py-2 text-[13px] text-popover-foreground shadow-lg transition-opacity',
          toast ? 'opacity-100' : 'opacity-0',
          toast?.tone === 'danger' && 'text-danger',
        )}
      >
        {toast ? <span key={toast.id}>{toast.text}</span> : null}
      </div>
    </ToastContext.Provider>
  );
}
