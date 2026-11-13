// Подставной вход (CC-0036 фабрики; экран — CC-0037): `GET /api/auth/state`, `POST /api/auth/login`,
// `POST /api/auth/logout` и охрана остального API. Общий для Vitest (MSW, src/mocks/handlers.ts) и
// Playwright (tests/e2e/fixtures.ts). Импорты — относительные.
//
// По умолчанию — Mac: вход не нужен (`required: false`), охрана всех пускает — существующие тесты
// живут как раньше. Ручки теста (`state`) или готовые состояния `authPreset(…)`:
//   `mac`    — с Mac (127.0.0.1): входа нет;
//   `lan`    — домашняя сеть, не вошли: всё, кроме `/api/auth/*`, — 401 `auth_required`;
//   `wrong`  — как `lan`, и любой пароль неверный;
//   `locked` — как `lan`, и вход заблокирован на `lockedFor` секунд (429 + Retry-After);
//   `off`    — пароль на сервере не задан: вход отвечает 409 `auth_off`.
// Верный пароль — `AUTH_PASSWORD`; после `lockAfter` неверных подряд — блокировка на `lockFor` с.
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export const AUTH_PASSWORD = 'дом-пароль';

export type AuthPreset = 'mac' | 'lan' | 'wrong' | 'locked' | 'off';

export type AuthMockState = {
  /** Этому браузеру нужен вход (не Mac и пароль задан). */
  required: boolean;
  loggedIn: boolean;
  /** Верный пароль; null — неверен любой. */
  password: string | null;
  /** Пароль на сервере не задан: вход — 409 `auth_off`. */
  off: boolean;
  /** Вход заблокирован ещё на столько секунд; null — нет. */
  lockedFor: number | null;
  /** Неверных подряд до блокировки; null — без блокировки. */
  lockAfter: number | null;
  lockFor: number;
  fails: number;
  /** «МЕТОД путь» каждого запроса к `/api/auth/*`. */
  calls: string[];
};

export type AuthReply =
  | { status: 200; body: S['AuthState'] | S['LoginResult'] }
  | { status: 401 | 409 | 429; body: S['AuthProblem']; headers?: Record<string, string> }
  | { status: 422; body: { detail: string } };

export function createAuthBackend() {
  const state: AuthMockState = {
    required: false,
    loggedIn: false,
    password: AUTH_PASSWORD,
    off: false,
    lockedFor: null,
    lockAfter: 5,
    lockFor: 300,
    fails: 0,
    calls: [],
  };
  return { state };
}

export type AuthBackend = ReturnType<typeof createAuthBackend>;

/** Готовое состояние входа (см. шапку файла). */
export function authPreset(b: AuthBackend, preset: AuthPreset): AuthBackend {
  const s = b.state;
  // `off`: экран входа уже открыт, а пароль на сервере сняли — вход отвечает 409.
  s.required = preset !== 'mac';
  s.loggedIn = false;
  s.password = preset === 'wrong' ? null : AUTH_PASSWORD;
  s.off = preset === 'off';
  s.lockedFor = preset === 'locked' ? 300 : null;
  s.fails = 0;
  return b;
}

export const AUTH_REQUIRED_BODY: S['AuthProblem'] = {
  detail: 'Нужен вход: откройте центр и введите пароль',
  code: 'auth_required',
  retry_after: null,
};

/** Охрана: без входа из сети закрыто всё API, кроме `/api/auth/*`. null — пропустить. */
export function guardAuth(b: AuthBackend, url: URL): AuthReply | null {
  const s = b.state;
  if (!s.required || s.loggedIn || s.off) return null;
  if (/\/api\/auth\//.test(url.pathname)) return null;
  return { status: 401, body: AUTH_REQUIRED_BODY };
}

function locked(seconds: number): AuthReply {
  return {
    status: 429,
    body: {
      detail: `Слишком много попыток. Попробуйте через ${Math.ceil(seconds / 60)} мин`,
      code: 'locked',
      retry_after: seconds,
    },
    headers: { 'Retry-After': String(seconds) },
  };
}

export function routeAuth(
  b: AuthBackend,
  method: string,
  url: URL,
  body: unknown,
): AuthReply | null {
  const m = /\/api\/auth\/(state|login|logout)$/.exec(url.pathname);
  if (!m) return null;
  const s = b.state;
  s.calls.push(`${method} ${url.pathname}`);
  const what = m[1];
  if (what === 'state' && method === 'GET')
    return { status: 200, body: { required: s.required, logged_in: s.loggedIn } };
  if (what === 'logout' && method === 'POST') {
    s.loggedIn = false;
    return { status: 200, body: { logged_in: false } };
  }
  if (what !== 'login' || method !== 'POST') return null;
  if (s.off)
    return {
      status: 409,
      body: { detail: 'Вход выключен: пароль не задан', code: 'auth_off', retry_after: null },
    };
  const password = (body as { password?: unknown } | null)?.password;
  if (typeof password !== 'string' || !password)
    return { status: 422, body: { detail: 'password: field required' } };
  if (s.lockedFor !== null) return locked(s.lockedFor);
  if (s.password === null || password !== s.password) {
    s.fails += 1;
    if (s.lockAfter !== null && s.fails >= s.lockAfter) {
      s.lockedFor = s.lockFor;
      return locked(s.lockedFor);
    }
    return {
      status: 401,
      body: { detail: 'Неверный пароль', code: 'wrong_password', retry_after: null },
    };
  }
  s.fails = 0;
  s.loggedIn = true;
  return { status: 200, body: { logged_in: true } };
}
