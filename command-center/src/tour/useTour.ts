import { createContext, useContext } from 'react';

import type { TourProgress } from './progress';

export type TourApi = {
  /** Открыть оглавление тура. */
  openMenu: () => void;
  /** Начать тур с шага `index`. */
  start: (index: number) => void;
  /** Убрать строку «Пройдите короткое обучение» с главной. */
  dismissInvite: () => void;
  progress: TourProgress;
};

export const TourContext = createContext<TourApi | null>(null);

/** Тур «Обучение»; вне `TourProvider` (отдельные тесты экранов) — null. */
export const useTour = (): TourApi | null => useContext(TourContext);
