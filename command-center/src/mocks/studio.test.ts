import { createStudioBackend, LAUNCH_OFF_WHY, routeStudio } from './studio';

type Body = Record<string, unknown> & {
  due?: boolean;
  ok?: boolean;
  why?: string | null;
  confirm?: string | null;
  code?: string;
  done?: boolean;
  word?: string;
  run_id?: string;
  launch?: { available: boolean; why: string | null };
  recorded?: string[];
};

const call = (
  b: ReturnType<typeof createStudioBackend>,
  method: string,
  path: string,
  body: unknown = null,
) => {
  const r = routeStudio(b, method, new URL(`http://x${path}`), body)!;
  return { status: r.status, body: r.body as Body };
};

describe('подставное чтение Studio', () => {
  it('по умолчанию запуск выключен: план виден без токена, «да» — 409 launch_off', () => {
    const b = createStudioBackend();
    const due = call(b, 'GET', '/api/studio/due?hook=batch-start');
    expect(due.status).toBe(200);
    expect(due.body).toMatchObject({
      due: false,
      launch: { available: false, why: LAUNCH_OFF_WHY },
    });
    const plan = call(b, 'POST', '/api/studio/read/plan');
    expect(plan.body).toMatchObject({ ok: true, confirm: null, why: LAUNCH_OFF_WHY });
    expect(call(b, 'POST', '/api/studio/read', { confirm: 'x' })).toMatchObject({
      status: 409,
      body: { code: 'launch_off' },
    });
  });

  it('запуск включён: токен, сессия «читается», затем итог; прочитано — «пора» гаснет', () => {
    const b = createStudioBackend();
    b.setLaunch(true);
    b.setDue(true);
    expect(call(b, 'GET', '/api/studio/due?hook=upload').body.due).toBe(true);
    const plan = call(b, 'POST', '/api/studio/read/plan').body;
    expect(plan.confirm).toBeTruthy();
    const started = call(b, 'POST', '/api/studio/read', { confirm: plan.confirm });
    expect(started.status).toBe(200);
    const id = started.body.run_id!;
    expect(call(b, 'GET', '/api/studio/due').body).toMatchObject({ running: id });
    expect(call(b, 'GET', `/api/studio/read/${id}`).body).toMatchObject({
      done: false,
      code: 'running',
    });
    expect(call(b, 'GET', `/api/studio/read/${id}`).body).toMatchObject({
      done: true,
      code: 'read',
      word: 'прочитано',
    });
    expect(call(b, 'GET', '/api/studio/due?hook=upload').body).toMatchObject({
      due: false,
      running: null,
    });
    // Токен одноразовый.
    expect(call(b, 'POST', '/api/studio/read', { confirm: plan.confirm }).body.code).toBe(
      'confirm_unknown',
    );
  });

  it('исходы «расширение не подключено» и «нужен вход»; отказ фабрики в плане; не рабочая фабрика', () => {
    const b = createStudioBackend();
    b.setLaunch(true);
    b.setDue(true);
    b.state.pollsToDone = 0;
    for (const [code, word] of [
      ['no_extension', 'расширение не подключено'],
      ['login_needed', 'нужен вход'],
    ] as const) {
      b.setOutcome(code);
      const c = call(b, 'POST', '/api/studio/read/plan').body.confirm;
      const id = call(b, 'POST', '/api/studio/read', { confirm: c }).body.run_id!;
      expect(call(b, 'GET', `/api/studio/read/${id}`).body).toMatchObject({
        done: true,
        code,
        word,
      });
      // Не прочитано — «пора» не гаснет ни по одному хуку, возраст прежний.
      expect(call(b, 'GET', '/api/studio/due?hook=center-first-open-of-day').body).toMatchObject({
        due: true,
        running: null,
        age_hours: 30,
      });
      expect(call(b, 'GET', '/api/studio/due?hook=upload').body.due).toBe(true);
    }
    b.state.refuse = 'no_claude';
    expect(call(b, 'POST', '/api/studio/read/plan').body).toMatchObject({
      ok: false,
      confirm: null,
    });
    b.state.readOnly = true;
    expect(call(b, 'GET', '/api/studio/due?hook=center-first-open-of-day').status).toBe(409);
    expect(call(b, 'GET', '/api/studio/due?hook=nope').body.code).toBe('bad_hook');
  });
});
