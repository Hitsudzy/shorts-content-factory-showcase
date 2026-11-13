// Контекст окна «попросить оператора» (провайдер — ./AskDialog.tsx, висит в Layout).
import { createContext, useContext } from 'react';

import type { AskTarget } from './target';

export const AskOpenContext = createContext<((target?: AskTarget) => void) | null>(null);

/** Открыть окно просьбы с подставленным контекстом; вне провайдера — `null`. */
export function useAsk(): ((target?: AskTarget) => void) | null {
  return useContext(AskOpenContext);
}
