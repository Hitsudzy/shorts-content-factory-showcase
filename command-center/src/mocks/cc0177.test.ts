// CC-0177 (по CC-0176, договор 0.77.0): подставной вход Claude в проверке и запуске,
// отказ `not_logged_in` с потраченным токеном, resume-строка с `auto` в истории.
import { LOGIN_NO, LOGIN_OK, LOGIN_UNKNOWN, NOT_LOGGED_IN_MESSAGE } from './batchActions';
import { AUTO_RESUME, createBatchesBackend, routeBatches } from './batches';

type Reply = { status: number; body: Record<string, unknown> };
const post = (b: ReturnType<typeof createBatchesBackend>, path: string, body: unknown) =>
  routeBatches(b, 'POST', new URL(`http://x/api/batches/${path}`), body) as Reply;

const fresh = () => {
  const b = createBatchesBackend();
  b.closeAll();
  return b;
};

describe('CC-0177: подставной вход Claude', () => {
  it('план несёт `login` во всех трёх видах; по умолчанию — залогинен', () => {
    const b = fresh();
    expect(post(b, 'launch/plan', { channel: 'example-film' }).body.login).toEqual(LOGIN_OK);
    for (const s of [LOGIN_NO, LOGIN_UNKNOWN, LOGIN_OK]) {
      b.actions.setLogin(s);
      const p = post(b, 'launch/plan', { channel: 'example-film' }).body;
      expect(p.login).toEqual(s);
      // вход — не защита: план годен и токен выдан
      expect(p.ok).toBe(true);
      expect(p.confirm).toBeTruthy();
    }
  });

  it('без входа «да» — 409 not_logged_in, батч не открыт, токен потрачен', () => {
    const b = fresh();
    b.actions.setLogin(LOGIN_NO);
    const confirm = post(b, 'launch/plan', { channel: 'example-film' }).body.confirm;
    const r = post(b, 'launch', { channel: 'example-film', confirm });
    expect(r.status).toBe(409);
    expect(r.body.code).toBe('not_logged_in');
    expect(r.body.message).toBe(NOT_LOGGED_IN_MESSAGE);
    expect(b.going().body).toMatchObject({ batches: [] });
    b.actions.setLogin(LOGIN_OK);
    const again = post(b, 'launch', { channel: 'example-film', confirm });
    expect(again.body.code).toBe('confirm_unknown');
  });

  it('вход неизвестен — батч запущен, `login` ответа — предупреждение', () => {
    const b = fresh();
    b.actions.setLogin(LOGIN_UNKNOWN);
    const confirm = post(b, 'launch/plan', { channel: 'example-film' }).body.confirm;
    const r = post(b, 'launch', { channel: 'example-film', confirm });
    expect(r.status).toBe(200);
    expect(r.body.login).toEqual(LOGIN_UNKNOWN);
  });

  it('история: строка «тик продолжил сам» — только по setAutoResume и у своего канала', () => {
    const b = createBatchesBackend();
    type H = { launches: { auto?: string | null }[] };
    expect((b.history(50).body as H).launches.some((l) => l.auto)).toBe(false);
    b.setAutoResume();
    expect((b.history(50).body as H).launches.filter((l) => l.auto)).toEqual([AUTO_RESUME]);
    expect((b.history(50, 'example-tech').body as H).launches.some((l) => l.auto)).toBe(false);
    expect(AUTO_RESUME.kind).toBe('resume');
  });
});
