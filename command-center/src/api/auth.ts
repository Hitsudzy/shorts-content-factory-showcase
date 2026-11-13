// Вход и выход (CC-0037, ручки CC-0036 контракта 0.65.0). Мимо клиента `api`: вход идёт без
// X-CC-Session (токен сессии сервера до входа не получить — `/api/session` закрыт) и не под
// замком записей. Куку ставит и хранит браузер (HttpOnly) — здесь её не видно.
import { setAuth } from '@/auth/store';

import { apiBaseUrl, resetSession, type Schemas } from './client';

export type AuthState = Schemas['AuthState'];
export type AuthProblem = Schemas['AuthProblem'];

/** Чем кончился вход: ok — центр открывается; иначе — что сказать человеку. */
export type LoginOutcome =
  | { ok: true }
  | { ok: false; kind: 'empty' | 'wrong' | 'off' | 'refused' | 'failed'; message: string }
  | { ok: false; kind: 'locked'; message: string; retryAfter: number };

const url = (path: string) => `${apiBaseUrl()}${path}`;

const JSON_HEADERS = { Accept: 'application/json', 'Content-Type': 'application/json' };

async function readJson(res: Response): Promise<Record<string, unknown> | null> {
  try {
    const body: unknown = await res.json();
    return typeof body === 'object' && body !== null ? (body as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

const text = (x: unknown): string | null => (typeof x === 'string' && x.trim() ? x : null);

/** `GET /api/auth/state`: нужен ли вход этому браузеру. */
export async function getAuthState(signal?: AbortSignal): Promise<AuthState> {
  const res = await fetch(url('/api/auth/state'), {
    headers: { Accept: 'application/json' },
    credentials: 'same-origin',
    signal,
  });
  const body = await readJson(res);
  if (!res.ok || typeof body?.required !== 'boolean' || typeof body.logged_in !== 'boolean')
    throw new Error(`${res.status} /api/auth/state`);
  return { required: body.required, logged_in: body.logged_in };
}

/**
 * Первый запрос центра — до `/api/session`, `/api/health` и прочего: без входа они 401.
 * Сервер старше контракта 0.65 или не ответил — центр открывается как раньше (вход не нужен);
 * если всё-таки нужен, первый же 401 `auth_required` уведёт на экран входа.
 */
export async function bootAuth({ training = false }: { training?: boolean } = {}): Promise<void> {
  // Тренировка (CC-0073): запросы — только в демо-сервер, живой API не спрашиваем и о входе.
  if (training) {
    setAuth({ view: 'app', required: false, loggedIn: false, reason: null });
    return;
  }
  try {
    const s = await getAuthState();
    setAuth({
      view: s.required && !s.logged_in ? 'login' : 'app',
      required: s.required,
      loggedIn: s.logged_in,
      reason: s.required && !s.logged_in ? 'boot' : null,
    });
  } catch {
    setAuth({ view: 'app', required: false, loggedIn: false, reason: null });
  }
}

/** Секунды блокировки: поле `retry_after` тела, иначе заголовок Retry-After, иначе минута. */
function retryAfterOf(res: Response, body: Record<string, unknown> | null): number {
  const fromBody = body?.retry_after;
  if (typeof fromBody === 'number' && fromBody > 0) return Math.ceil(fromBody);
  const header = Number(res.headers.get('Retry-After'));
  return Number.isFinite(header) && header > 0 ? Math.ceil(header) : 60;
}

/** `POST /api/auth/login`: пароль → кука сессии. */
export async function login(password: string): Promise<LoginOutcome> {
  if (!password.trim()) return { ok: false, kind: 'empty', message: 'Введите пароль' };
  let res: Response;
  try {
    res = await fetch(url('/api/auth/login'), {
      method: 'POST',
      headers: JSON_HEADERS,
      credentials: 'same-origin',
      body: JSON.stringify({ password }),
    });
  } catch {
    return {
      ok: false,
      kind: 'failed',
      message: 'Центр не ответил. Проверьте, что Mac включён и вы в домашней сети',
    };
  }
  const body = await readJson(res);
  if (res.ok && body?.logged_in === true) {
    resetSession();
    setAuth({ view: 'app', required: true, loggedIn: true, reason: null });
    return { ok: true };
  }
  const code = body?.code;
  if (res.status === 401 || code === 'wrong_password')
    return { ok: false, kind: 'wrong', message: text(body?.detail) ?? 'Неверный пароль' };
  if (res.status === 429 || code === 'locked')
    return {
      ok: false,
      kind: 'locked',
      message: text(body?.detail) ?? 'Слишком много попыток',
      retryAfter: retryAfterOf(res, body),
    };
  if (res.status === 409 || code === 'auth_off')
    return {
      ok: false,
      kind: 'off',
      message:
        'Пароль на сервере не задан, поэтому вход из домашней сети выключен. Откройте центр на Mac',
    };
  if (res.status === 422) return { ok: false, kind: 'empty', message: 'Введите пароль' };
  if (res.status === 403)
    return {
      ok: false,
      kind: 'refused',
      message: text(body?.detail) ?? 'Сервер не принял запрос с этой страницы. Обновите её',
    };
  return {
    ok: false,
    kind: 'failed',
    message: `Вход не удался: сервер ответил ошибкой ${res.status}. Попробуйте ещё раз`,
  };
}

/** `POST /api/auth/logout`: кука снята — экран входа. Не ответил — тоже вход: куку снимет сервер. */
export async function logout(): Promise<void> {
  try {
    await fetch(url('/api/auth/logout'), {
      method: 'POST',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    });
  } catch {
    // Сеть пропала — показываем вход всё равно: без куки центр дальше не пустят.
  }
  resetSession();
  setAuth({ view: 'login', loggedIn: false, reason: 'logout' });
}
