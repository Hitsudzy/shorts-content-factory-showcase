// Состояние входа (CC-0037): нужен ли этому браузеру вход и выполнен ли он. Сервер решает сам
// (`GET /api/auth/state`, CC-0036): с Mac (127.0.0.1) вход не нужен никогда, из домашней сети —
// по паролю, сессия — в HttpOnly-куке. Здесь — только то, какой экран показать: центр или вход.
// Модуль без импортов клиента API: клиент сам сообщает сюда об отказе 401 `auth_required`.
import { useSyncExternalStore } from 'react';

/** `app` — центр; `login` — экран входа; `checking` — ещё не спросили сервер. */
export type AuthView = 'checking' | 'app' | 'login';

/** Почему показан вход: при загрузке, вход истёк посреди работы, вышли сами. */
export type LoginReason = 'boot' | 'expired' | 'logout';

export type AuthSnapshot = {
  view: AuthView;
  /** Этому браузеру нужен вход (домашняя сеть); с Mac — false, и кнопки «Выйти» нет. */
  required: boolean;
  loggedIn: boolean;
  reason: LoginReason | null;
};

/** Код отказа API, по которому центр уходит на экран входа. */
export const AUTH_REQUIRED = 'auth_required';

const INITIAL: AuthSnapshot = { view: 'checking', required: false, loggedIn: false, reason: null };

let snap: AuthSnapshot = INITIAL;
const listeners = new Set<() => void>();

export function authSnapshot(): AuthSnapshot {
  return snap;
}

export function setAuth(next: Partial<AuthSnapshot>): void {
  const merged = { ...snap, ...next };
  if (
    merged.view === snap.view &&
    merged.required === snap.required &&
    merged.loggedIn === snap.loggedIn &&
    merged.reason === snap.reason
  )
    return;
  snap = merged;
  for (const l of listeners) l();
}

export function subscribeAuth(listener: () => void): () => void {
  listeners.add(listener);
  return () => {
    listeners.delete(listener);
  };
}

/** Состояние входа для компонентов. */
export function useAuth(): AuthSnapshot {
  return useSyncExternalStore(subscribeAuth, authSnapshot, authSnapshot);
}

/** Тест начинает с чистого листа. */
export function resetAuth(next: AuthSnapshot = INITIAL): void {
  snap = next;
  for (const l of listeners) l();
}

/** Сервер не пустил без входа: на экран входа; адрес страницы остаётся — после входа вернёмся. */
export function authRequired(): void {
  if (snap.view === 'login') return;
  setAuth({ view: 'login', required: true, loggedIn: false, reason: 'expired' });
}

/**
 * Посмотреть ответ API: 401 с кодом `auth_required` — вход истёк или его не было. Остальные 401
 * (`wrong_password` при входе) — не про это. Тело читается из копии: ответ уходит дальше целым.
 */
export function watchUnauthorized(response: Response): Response {
  if (response.status !== 401) return response;
  void response
    .clone()
    .json()
    .then((body: unknown) => {
      if ((body as { code?: unknown } | null)?.code === AUTH_REQUIRED) authRequired();
    })
    .catch(() => undefined);
  return response;
}
