// Состояние тура: закрыт, открыто оглавление или идёт шаг с номером `index`.
import { markSeen, restartProgress, type TourProgress } from './progress';
import { STEPS } from './steps';

export type TourState = { mode: 'closed' | 'menu' | 'step'; index: number };

export type TourAction =
  | { type: 'menu' }
  | { type: 'start'; index: number }
  | { type: 'next' }
  | { type: 'back' }
  | { type: 'close' };

/** Сколько ждать цель шага (данные грузятся), прежде чем объяснить словами; тесты сокращают. */
export const tourTiming = { waitMs: 6000 };

export const CLOSED: TourState = { mode: 'closed', index: 0 };

export function reduceTour(s: TourState, a: TourAction, total: number = STEPS.length): TourState {
  switch (a.type) {
    case 'menu':
      return { mode: 'menu', index: s.index };
    case 'start':
      return { mode: 'step', index: Math.max(0, Math.min(a.index, total - 1)) };
    case 'next':
      if (s.mode !== 'step') return s;
      // После последнего шага тур закрывается.
      return s.index >= total - 1
        ? { mode: 'closed', index: s.index }
        : { mode: 'step', index: s.index + 1 };
    case 'back':
      if (s.mode !== 'step' || s.index === 0) return s;
      return { mode: 'step', index: s.index - 1 };
    case 'close':
      return { mode: 'closed', index: s.index };
  }
}

/** Тур вместе с прогрессом: увиденный шаг сразу попадает в прогресс. */
export type TourModel = { tour: TourState; progress: TourProgress };

export type TourModelAction = TourAction | { type: 'dismiss' } | { type: 'restart' };

export function reduceModel(m: TourModel, a: TourModelAction): TourModel {
  if (a.type === 'dismiss')
    return m.progress.dismissed ? m : { ...m, progress: { ...m.progress, dismissed: true } };
  if (a.type === 'restart') {
    const tour: TourState = { mode: 'step', index: 0 };
    return { tour, progress: markSeen(restartProgress(m.progress), STEPS[0]!.id) };
  }
  const tour = reduceTour(m.tour, a);
  const progress = tour.mode === 'step' ? markSeen(m.progress, STEPS[tour.index]!.id) : m.progress;
  return tour === m.tour && progress === m.progress ? m : { tour, progress };
}
