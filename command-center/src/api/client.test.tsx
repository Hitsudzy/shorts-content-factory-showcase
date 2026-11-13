import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import { http, HttpResponse } from 'msw';
import type { ReactNode } from 'react';

import { fixtures, SESSION_TOKEN } from '@/mocks/fixtures';
import { mockGet } from '@/mocks/handlers';
import { server } from '@/mocks/server';

import {
  ApiError,
  apiBaseUrl,
  getHealth,
  getSession,
  resetSession,
  sessionHeaders,
  sessionMiddleware,
} from './client';
import { useVersion } from './hooks';

afterEach(() => resetSession());

function countSessionRequests() {
  let n = 0;
  server.use(
    http.get('*/api/session', () => {
      n += 1;
      return HttpResponse.json(fixtures.session);
    }),
  );
  return () => n;
}

describe('клиент API', () => {
  it('ходит на <origin><base>/api/… и отдаёт тело по контракту', async () => {
    expect(apiBaseUrl()).toBe(window.location.origin);
    await expect(getHealth()).resolves.toEqual(fixtures.health);
  });

  it('отказ охраны превращается в ApiError с телом Refusal', async () => {
    server.use(mockGet('/api/health', { detail: 'чужой Host', guard: 'host' }, 403));
    const err = await getHealth().catch((e: unknown) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 403, refusal: { guard: 'host' } });
  });

  it('ошибка без тела — тоже ApiError', async () => {
    server.use(http.get('*/api/health', () => new HttpResponse(null, { status: 503 })));
    await expect(getHealth()).rejects.toMatchObject({ name: 'ApiError', status: 503 });
  });

  it('useVersion отдаёт версию через TanStack Query', async () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useVersion(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data?.agents[0]?.agent).toBe('footage-indexer');
  });
});

describe('токен сессии', () => {
  it('берётся из GET /api/session один раз и кладётся в заголовок из ответа', async () => {
    const requests = countSessionRequests();
    await expect(sessionHeaders()).resolves.toEqual({ 'X-CC-Session': SESSION_TOKEN });
    await getSession();
    expect(requests()).toBe(1);
  });

  it('middleware вешает его на POST, но не на GET', async () => {
    const opts = { id: '1', schemaPath: '/x', params: {}, options: {} } as never;
    const onRequest = sessionMiddleware.onRequest!;

    const post = new Request('http://localhost/api/x', { method: 'POST' });
    const sent = (await onRequest({ ...(opts as object), request: post } as never)) as Request;
    expect(sent.headers.get('X-CC-Session')).toBe(SESSION_TOKEN);

    const get = new Request('http://localhost/api/x');
    expect(await onRequest({ ...(opts as object), request: get } as never)).toBeUndefined();
  });

  it('отказ охраны `session` на POST сбрасывает токен — следующий запрос возьмёт новый', async () => {
    const requests = countSessionRequests();
    await getSession();
    const request = new Request('http://localhost/api/x', { method: 'POST' });
    const response = HttpResponse.json(
      { detail: 'старый токен', guard: 'session' },
      { status: 403 },
    );
    await sessionMiddleware.onResponse!({ request, response } as never);
    await getSession();
    expect(requests()).toBe(2);
  });
});
