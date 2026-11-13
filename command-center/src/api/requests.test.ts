import { http, HttpResponse } from 'msw';

import { requests } from '@/mocks/handlers';
import { server } from '@/mocks/server';

import {
  cancelRequest,
  closeRequest,
  createRequest,
  getRequests,
  RequestError,
  requestErrorText,
} from './requests';

async function refusal(p: Promise<unknown>): Promise<RequestError> {
  try {
    await p;
  } catch (e) {
    if (e instanceof RequestError) return e;
    throw e;
  }
  throw new Error('ждали отказа');
}

describe('API просьб', () => {
  it('список, новая просьба без `by`, закрыть и отменить', async () => {
    expect((await getRequests()).requests.map((r) => r.id)).toEqual(['R3', 'R4', 'R5', 'R6']);
    const r = await createRequest({ text: 'Проверь звук', context: { screen: '/videos' } });
    expect(r).toMatchObject({ id: 'R7', status: 'open' });
    expect(requests.writes[0]).toEqual({
      path: '/api/requests',
      body: { text: 'Проверь звук', context: { screen: '/videos' } },
    });
    expect((await closeRequest('R3')).status).toBe('closed');
    expect((await cancelRequest('R5')).status).toBe('cancelled');
  });

  it('отказ фабрики — код и text_ru; строка по-английски — под «подробнее»', async () => {
    const e = await refusal(closeRequest('R6'));
    expect(e.status).toBe(409);
    expect(e.code).toBe('not_answered');
    expect(e.textRu).toContain('ещё не ответили');
    const t = requestErrorText(e, 'close');
    expect(t).toMatchObject({ title: 'Просьба не закрыта', gone: true });
    expect(t.text).toBe(e.textRu);
    expect(t.detail).toContain('409 /api/requests/R6/close: not answered');
  });

  it('«только смотреть» — словами фабрики, без «подробнее»', async () => {
    requests.readOnly = true;
    const e = await refusal(createRequest({ text: 'да' }));
    expect(e.readOnly).toBe(true);
    const t = requestErrorText(e, 'create');
    expect(t.text).toMatch(/^Только смотреть: /);
    expect(t.detail).toBeNull();
  });

  it('чужой отказ и нет связи — общими словами', async () => {
    server.use(http.post('*/api/requests', () => HttpResponse.json({ oops: 1 }, { status: 500 })));
    const e = await refusal(createRequest({ text: 'да' }));
    expect(requestErrorText(e, 'create').text).toMatch(/Фабрика не смогла записать/);
    expect(requestErrorText(new TypeError('Failed to fetch'), 'cancel')).toMatchObject({
      title: 'Просьба не отменена',
      text: expect.stringMatching(/Нет связи с API/) as unknown,
    });
  });
});
