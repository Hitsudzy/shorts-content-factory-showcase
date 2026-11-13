// Подставное обслуживание (CC-0033): расход, сравнение, пул, журналы, архив; токены plan → «да»
// и ручки теста — как у фабрики (CC-0032 / CC-0104 / CC-0105).
import { createMaintenanceBackend, routeMaintenance, type MaintenanceBackend } from './maintenance';
import { REEL_EXEC, REEL_HAND, SCIENCE, TECH_EXEC } from './maintenanceData';

type Body = Record<string, unknown> & { code?: string; confirm?: string | null; ok?: boolean };

const ask = (b: MaintenanceBackend, method: string, path: string, body: unknown = null) => {
  const r = routeMaintenance(b, method, new URL(`http://x${path}`), body);
  if (!r) throw new Error(`не наш путь: ${path}`);
  return { status: r.status, body: r.body as Body };
};

describe('подставное обслуживание', () => {
  it('расход: батч с событиями — строки и итоги, без событий — ok: false и подсказка', () => {
    const b = createMaintenanceBackend();
    const reel = ask(b, 'GET', `/api/maintenance/usage/${REEL_EXEC}`);
    expect(reel.status).toBe(200);
    const t = reel.body.totals as {
      total: number;
      input: number;
      cache_write: number;
      cache_read: number;
      output: number;
    };
    expect(t.total).toBe(t.input + t.cache_write + t.cache_read + t.output);
    expect(reel.body.ok).toBe(true);
    const none = ask(b, 'GET', `/api/maintenance/usage/${REEL_HAND}`);
    expect(none.body.ok).toBe(false);
    expect(none.body.why).toMatch(/usage_from_transcripts/);
    expect(ask(b, 'GET', '/api/maintenance/usage/example-film/2026-01-01T0000Z').body.code).toBe(
      'unknown_batch',
    );
    expect(ask(b, 'GET', '/api/maintenance/usage/example-film/latest').body.code).toBe('invalid');
  });

  it('сравнение: та же пара — одинаково, Reel против Tech — расхождения, один батч — bad_call', () => {
    const b = createMaintenanceBackend();
    const same = ask(
      b,
      'GET',
      `/api/maintenance/compare?manual=${REEL_HAND}&executor=${REEL_EXEC}`,
    );
    expect(same.body.same).toBe(true);
    const diff = ask(
      b,
      'GET',
      `/api/maintenance/compare?manual=${REEL_HAND}&executor=${TECH_EXEC}`,
    );
    expect(diff.body.same).toBe(false);
    expect((diff.body.defects as string[]).length).toBeGreaterThan(0);
    expect(
      ask(b, 'GET', `/api/maintenance/compare?manual=${SCIENCE}&executor=${SCIENCE}`).body.code,
    ).toBe('bad_call');
  });

  it('пул: правило давности переводит старую тему без ролика в «освободит»', () => {
    const b = createMaintenanceBackend();
    const plain = ask(b, 'GET', '/api/maintenance/pool').body as {
      totals: { release: { sources: number } };
    };
    const stale = ask(b, 'GET', '/api/maintenance/pool?stale_days=14').body as typeof plain;
    expect(plain.totals.release.sources).toBe(3);
    expect(stale.totals.release.sources).toBe(4);
  });

  it('пул: план → «да» освобождает, токен одноразовый', () => {
    const b = createMaintenanceBackend();
    const plan = ask(b, 'POST', '/api/maintenance/pool/release/plan', { stale_days: null });
    expect(plan.body.ok).toBe(true);
    const done = ask(b, 'POST', '/api/maintenance/pool/release', { confirm: plan.body.confirm });
    expect(done.status).toBe(200);
    expect(done.body.deleted).toHaveLength(3);
    expect(b.state.written.released).toHaveLength(3);
    const again = ask(b, 'POST', '/api/maintenance/pool/release', { confirm: plan.body.confirm });
    expect(again.body.code).toBe('confirm_unknown');
    const empty = ask(b, 'POST', '/api/maintenance/pool/release/plan', {});
    expect(empty.body.ok).toBe(false);
    expect(empty.body.confirm).toBeNull();
  });

  it('идёт батч: план без токена, старый токен — batch_open', () => {
    const b = createMaintenanceBackend();
    const plan = ask(b, 'POST', '/api/maintenance/journals/plan');
    b.state.openBatches = ['example-science/2026-10-14T0300Z'];
    expect(
      ask(b, 'POST', '/api/maintenance/journals', { confirm: plan.body.confirm }).body.code,
    ).toBe('batch_open');
    const now = ask(b, 'POST', '/api/maintenance/journals/plan');
    expect(now.body.ok).toBe(false);
    expect(now.body.why).toMatch(/Открыт батч/);
  });

  it('архив: план → «да» переносит сентябрь; диск не подключён — volume_missing', () => {
    const b = createMaintenanceBackend();
    const plan = ask(b, 'POST', '/api/maintenance/archive/plan');
    expect(plan.body.ok).toBe(true);
    expect(plan.body.jobs).toHaveLength(3);
    const done = ask(b, 'POST', '/api/maintenance/archive', { confirm: plan.body.confirm });
    expect(done.body.committed).toBe(true);
    expect(ask(b, 'POST', '/api/maintenance/archive/plan').body.ok).toBe(false);

    const c = createMaintenanceBackend();
    const p2 = ask(c, 'POST', '/api/maintenance/archive/plan');
    c.state.volumeMissing = true;
    expect(ask(c, 'POST', '/api/maintenance/archive', { confirm: p2.body.confirm }).body.code).toBe(
      'volume_missing',
    );
  });

  it('токены: чужое действие — mismatch, устарел — expired, busy токен не тратит', () => {
    const b = createMaintenanceBackend();
    const plan = ask(b, 'POST', '/api/maintenance/journals/plan');
    expect(
      ask(b, 'POST', '/api/maintenance/archive', { confirm: plan.body.confirm }).body.code,
    ).toBe('confirm_mismatch');
    const p2 = ask(b, 'POST', '/api/maintenance/journals/plan');
    b.state.next = 'busy';
    expect(
      ask(b, 'POST', '/api/maintenance/journals', { confirm: p2.body.confirm }).body.code,
    ).toBe('busy');
    b.expireTokens();
    expect(
      ask(b, 'POST', '/api/maintenance/journals', { confirm: p2.body.confirm }).body.code,
    ).toBe('confirm_expired');
  });

  it('ручки: отказ чтения — 500, только смотреть — 409 not_working_factory', () => {
    const b = createMaintenanceBackend();
    b.state.refuse.pool = true;
    expect(ask(b, 'GET', '/api/maintenance/pool').status).toBe(500);
    b.state.readOnly = true;
    expect(ask(b, 'POST', '/api/maintenance/archive/plan').body.code).toBe('not_working_factory');
    expect(ask(b, 'GET', '/api/maintenance').status).toBe(200);
  });
});
