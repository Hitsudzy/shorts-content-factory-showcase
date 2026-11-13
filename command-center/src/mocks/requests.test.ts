import { createRequestsBackend, routeRequests } from './requests';

const url = (p: string) => new URL(`http://x${p}`);

describe('подставная очередь просьб', () => {
  it('live — open, taken, answered; closed/cancelled — отдельно; all — всё; чужой статус — 422', () => {
    const b = createRequestsBackend();
    const ids = (status?: string) => {
      const r = routeRequests(
        b,
        'GET',
        url(`/api/requests${status ? `?status=${status}` : ''}`),
        null,
      );
      const body = r?.body as { requests: { id: string }[] };
      return body.requests.map((x) => x.id);
    };
    expect(ids()).toEqual(['R3', 'R4', 'R5', 'R6']);
    expect(ids('answered')).toEqual(['R3', 'R4']);
    expect(ids('closed')).toEqual(['R1']);
    expect(ids('cancelled')).toEqual(['R2']);
    expect(ids('all')).toHaveLength(6);
    expect(routeRequests(b, 'GET', url('/api/requests?status=nope'), null)).toMatchObject({
      status: 422,
      body: { code: 'status_unknown' },
    });
    expect(routeRequests(b, 'GET', url('/api/requests/R6'), null)?.status).toBe(200);
    expect(routeRequests(b, 'GET', url('/api/requests/R60'), null)).toMatchObject({
      status: 404,
      body: { code: 'not_found', text_ru: 'Просьбы R60 нет.' },
    });
  });

  it('новая просьба: следующий номер, open; пустая и длинная — 422 с text_ru', () => {
    const b = createRequestsBackend();
    const post = (body: unknown) => routeRequests(b, 'POST', url('/api/requests'), body);
    expect(post({ text: '  ' })).toMatchObject({ status: 422, body: { code: 'text_empty' } });
    expect(post({ text: 'x'.repeat(4001) })).toMatchObject({
      status: 422,
      body: { code: 'text_too_long', text_ru: 'Просьба длиннее 4000 знаков - сократите её.' },
    });
    expect(post({ text: 'да', context: { x: 'y'.repeat(4000) } })).toMatchObject({
      status: 422,
      body: { code: 'context_invalid' },
    });
    const ok = post({ text: ' Проверь звук ', channel: 'example-film', context: { screen: '/' } });
    expect(ok).toMatchObject({
      status: 200,
      body: { id: 'R7', n: 7, text: 'Проверь звук', status: 'open', channel: 'example-film' },
    });
    expect(b.requests).toHaveLength(7);
  });

  it('закрыть — только отвеченную; отменить — только open/taken', () => {
    const b = createRequestsBackend();
    const post = (id: string, action: string) =>
      routeRequests(b, 'POST', url(`/api/requests/${id}/${action}`), null);
    expect(post('R6', 'close')).toMatchObject({ status: 409, body: { code: 'not_answered' } });
    expect(post('R3', 'cancel')).toMatchObject({ status: 409, body: { code: 'cancel_answered' } });
    expect(post('R1', 'close')).toMatchObject({ status: 409, body: { code: 'already_closed' } });
    expect(post('R2', 'cancel')).toMatchObject({
      status: 409,
      body: { code: 'already_cancelled' },
    });
    expect(post('R3', 'close')).toMatchObject({ status: 200, body: { status: 'closed' } });
    expect(post('R5', 'cancel')).toMatchObject({ status: 200, body: { status: 'cancelled' } });
    expect(post('R6', 'cancel')).toMatchObject({ status: 200, body: { status: 'cancelled' } });
    expect(post('R9', 'cancel')?.status).toBe(404);
  });

  it('«только смотреть» — 409 not_working_factory; записи считаются', () => {
    const b = createRequestsBackend();
    b.readOnly = true;
    expect(routeRequests(b, 'POST', url('/api/requests'), { text: 'да' })).toMatchObject({
      status: 409,
      body: { code: 'not_working_factory' },
    });
    expect(b.writes).toEqual([{ path: '/api/requests', body: { text: 'да' } }]);
    expect(b.requests).toHaveLength(6);
  });
});
