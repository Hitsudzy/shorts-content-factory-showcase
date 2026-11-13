import { delay, http, HttpResponse } from 'msw';

import { SESSION_TOKEN } from '@/mocks/fixtures';
import { server } from '@/mocks/server';

import { ActionTimeout, needsReplan, planLaunch, stop } from './batchActions';
import { BatchError } from './batchProblem';
import { resetSession } from './client';

afterEach(() => resetSession());

describe('клиент действий над батчами', () => {
  it('запись идёт с токеном сессии; отказ фабрики — BatchError с её сообщением', async () => {
    let header: string | null = null;
    server.use(
      http.post('*/api/batches/launch/plan', ({ request }) => {
        header = request.headers.get('X-CC-Session');
        return HttpResponse.json(
          { message: 'Канала «x» нет.', code: 'unknown_channel', details: [] },
          { status: 404 },
        );
      }),
    );
    const e = await planLaunch('x').catch((err: unknown) => err);
    expect(header).toBe(SESSION_TOKEN);
    expect(e).toBeInstanceOf(BatchError);
    expect((e as BatchError).message).toBe('Канала «x» нет.');
    expect(needsReplan(e)).toBe(false);
  });

  it('план заново — на confirm_* и check_changed, не на busy и refused', () => {
    const err = (code: string) =>
      new BatchError(409, 'x', { message: 'x', code: code as never, details: [] });
    for (const c of ['confirm_unknown', 'confirm_expired', 'confirm_channel', 'confirm_mismatch'])
      expect(needsReplan(err(c))).toBe(true);
    expect(needsReplan(err('check_changed'))).toBe(true);
    expect(needsReplan(err('busy'))).toBe(false);
    expect(needsReplan(err('refused'))).toBe(false);
    expect(needsReplan(new Error('сеть'))).toBe(false);
  });

  it('остановка не ждёт вечно: по потолку — ActionTimeout', async () => {
    server.use(
      http.post('*/api/batches/:channel/:id/stop', async () => {
        await delay(2_000);
        return HttpResponse.json({});
      }),
    );
    const e = await stop('example-film/2026-10-10T0530Z', 'tok', false, 50).catch(
      (err: unknown) => err,
    );
    expect(e).toBeInstanceOf(ActionTimeout);
  });
});
