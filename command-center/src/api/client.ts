// Тонкий клиент API фабрики поверх типов из контракта (CC-0004). Типы — `schema.gen.ts`,
// сгенерированный `npm run api:types` из `api/openapi.json`; руками ничего не описываем.
// API всегда на том же origin, что и приложение (`<base>api/…`): в проде его раздаёт
// FastAPI фабрики, в dev — прокси Vite (CC_API_URL).
import createClient, { type Middleware } from 'openapi-fetch';

import { watchUnauthorized } from '../auth/store';
import { guardedFetch } from '../training/mode';

import type { components, paths } from './schema.gen';
import { lockLabel, trackWrite } from './writeLock';

export type Schemas = components['schemas'];
export type Health = Schemas['Health'];
export type Version = Schemas['Version'];
export type AgentPin = Schemas['AgentPin'];
export type Session = Schemas['Session'];
export type Refusal = Schemas['Refusal'];
export type WritesProblem = Schemas['WritesProblem'];

export class ApiError extends Error {
  readonly status: number;
  /** Тело отказа охраны API (403: Host, Origin, сессия), если оно пришло. */
  readonly refusal: Refusal | null;

  constructor(status: number, message: string, refusal: Refusal | null = null) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.refusal = refusal;
  }
}

/** Корень, к которому клеятся пути контракта (`/api/…`): origin + базовый путь без `/` в конце. */
export function apiBaseUrl(): string {
  const base = import.meta.env.BASE_URL.replace(/\/$/, '');
  return new URL(window.location.href).origin + base;
}

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

let session: Promise<Session> | null = null;

/** Токен сессии сервера API (`GET /api/session`); один запрос на процесс сервера. */
export function getSession(): Promise<Session> {
  session ??= api
    .GET('/api/session')
    .then(unwrap)
    .catch((e: unknown) => {
      session = null;
      throw e;
    });
  return session;
}

/** Забыть токен: сервер перезапущен (новый токен) или тест начинает с чистого листа. */
export function resetSession(): void {
  session = null;
}

/** Заголовок с токеном сессии для POST и прочих не-GET: `{ 'X-CC-Session': '…' }`. */
export async function sessionHeaders(): Promise<Record<string, string>> {
  const s = await getSession();
  return { [s.header]: s.token };
}

/** Отказ записи вне рабочей фабрики (CC-0058): 409 `{code: 'not_working_factory', message}`. */
export const NOT_WORKING_FACTORY = 'not_working_factory';

type ReadOnlyListener = (message: string) => void;
const readOnlyListeners = new Set<ReadOnlyListener>();

/**
 * Подписка на отказ `not_working_factory` любой записи (CC-0059): например, ветка фабрики
 * сменилась в пределах кэша API. Подписчик — `useWritesRefusalWatch` (перечитать health).
 */
export function onReadOnlyRefusal(listener: ReadOnlyListener): () => void {
  readOnlyListeners.add(listener);
  return () => {
    readOnlyListeners.delete(listener);
  };
}

/** Вешает токен сессии на каждый не-GET запрос; отказ охраны `session` сбрасывает токен. */
export const sessionMiddleware: Middleware = {
  async onRequest({ request }) {
    if (SAFE_METHODS.has(request.method)) return undefined;
    for (const [name, value] of Object.entries(await sessionHeaders())) {
      request.headers.set(name, value);
    }
    return request;
  },
  async onResponse({ request, response }) {
    if (SAFE_METHODS.has(request.method)) return undefined;
    if (response.status === 409) {
      const body = (await response
        .clone()
        .json()
        .catch(() => null)) as { code?: unknown; message?: unknown } | null;
      if (body?.code === NOT_WORKING_FACTORY) {
        const message = typeof body.message === 'string' ? body.message : '';
        for (const listener of readOnlyListeners) listener(message);
      }
      return undefined;
    }
    if (response.status !== 403) return undefined;
    const body = (await response
      .clone()
      .json()
      .catch(() => null)) as Partial<Refusal> | null;
    if (body?.guard === 'session') resetSession();
    return undefined;
  },
};

export const api = createClient<paths>({
  baseUrl: apiBaseUrl(),
  // fetch берём в момент запроса, а не при создании клиента: MSW в тестах подменяет его позже.
  // В тренировке (CC-0073) запрос уходит только через демо-сервер — иначе не уходит вовсе.
  // CC-0037: 401 `auth_required` любого запроса — одно место: центр уходит на экран входа.
  fetch: (request) => guardedFetch(request).then(watchUnauthorized),
  headers: { Accept: 'application/json' },
});
api.use(sessionMiddleware);

// CC-0084: каждая запись — под учётом записей в полёте (слой `WriteLock` замораживает центр).
// Обёртка на самих методах, а не middleware: снимается при любом исходе, в том числе когда
// запрос не ушёл (токен сессии не получен) или ответ не разобрался.
type Send = (path: string, init?: { body?: unknown }) => Promise<unknown>;
for (const method of ['POST', 'PUT', 'PATCH', 'DELETE'] as const) {
  const methods = api as unknown as Record<typeof method, Send>;
  const send = methods[method].bind(api);
  methods[method] = (path, init) =>
    trackWrite(lockLabel(method, path, init?.body), () => send(path, init));
}

type Result<T> = { data?: T; error?: unknown; response: Response };

/** Данные успешного ответа или ApiError (с телом отказа охраны, если это он). */
export function unwrap<T>({ data, error, response }: Result<T>): T {
  if (response.ok && data !== undefined) return data;
  const refusal = isRefusal(error) ? error : null;
  const what = `${response.status} ${new URL(response.url || 'http://x/').pathname}`;
  throw new ApiError(response.status, refusal ? `${what}: ${refusal.detail}` : what, refusal);
}

function isRefusal(x: unknown): x is Refusal {
  return typeof x === 'object' && x !== null && 'guard' in x && 'detail' in x;
}

export async function getHealth(signal?: AbortSignal): Promise<Health> {
  return unwrap(await api.GET('/api/health', { signal }));
}

export async function getVersion(signal?: AbortSignal): Promise<Version> {
  return unwrap(await api.GET('/api/version', { signal }));
}
