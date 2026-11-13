// Тема центра: тёмная по умолчанию, светлая по выбору зрителя (запоминается в этом браузере).
//
// prefers-color-scheme сознательно не учитывается: тёмная тема — это вид роликов фабрики
// (фон #0B0B12, жёлтый «Ge»), центр — их продолжение (docs/design.md → «Почему такой цвет»).
// Светлая — осознанный выбор зрителя, а не настройка системы.
import { useSyncExternalStore } from 'react';

export type Theme = 'dark' | 'light';

export const THEME_STORAGE_KEY = 'cc-theme';
export const DEFAULT_THEME: Theme = 'dark';

const listeners = new Set<() => void>();

/** Сохранённая тема; хранилище может быть недоступно (приватное окно, запрет) — тогда тёмная. */
export function readSavedTheme(): Theme {
  try {
    return localStorage.getItem(THEME_STORAGE_KEY) === 'light' ? 'light' : DEFAULT_THEME;
  } catch {
    return DEFAULT_THEME;
  }
}

export function currentTheme(): Theme {
  return document.documentElement.dataset.theme === 'light' ? 'light' : 'dark';
}

/** Ставит `data-theme` на <html>; токены светлой темы висят на `:root[data-theme='light']`. */
export function applyTheme(theme: Theme): void {
  document.documentElement.dataset.theme = theme;
  for (const l of listeners) l();
}

export function setTheme(theme: Theme): void {
  try {
    localStorage.setItem(THEME_STORAGE_KEY, theme);
  } catch {
    // Не запомнили — тема всё равно сменится до перезагрузки.
  }
  applyTheme(theme);
}

/** Забыть выбор зрителя: тема возвращается к тёмной. */
export function resetTheme(): void {
  try {
    localStorage.removeItem(THEME_STORAGE_KEY);
  } catch {
    // нечего забывать
  }
  applyTheme(DEFAULT_THEME);
}

function subscribe(listener: () => void) {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

export function useTheme(): Theme {
  return useSyncExternalStore(subscribe, currentTheme, () => DEFAULT_THEME);
}
