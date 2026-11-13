import {
  createBatchesBackend,
  routeBatches,
  RUNNING,
  STOPPED,
  STRANDED_FAILED,
  STRANDED_REFUSAL,
  STRANDED_STOPPED,
} from './batches';

type Body = Record<string, unknown> & {
  ok?: boolean;
  confirm?: string | null;
  code?: string;
  message?: string;
  reason?: string;
  guards?: { name: string; ok: boolean; line: string }[];
  batches?: { batch: string; status: string }[];
};

const post = (b: ReturnType<typeof createBatchesBackend>, path: string, body: unknown = null) => {
  const r = routeBatches(b, 'POST', new URL(`http://x${path}`), body)!;
  return { status: r.status, body: r.body as Body };
};
const list = (b: ReturnType<typeof createBatchesBackend>) =>
  (routeBatches(b, 'GET', new URL('http://x/api/batches'))!.body as Body).batches!;

describe('подставные действия над батчами', () => {
  it('запуск: открытый батч канала — отказ в плане без токена; без него — токен, запуск, батч в списке', () => {
    const b = createBatchesBackend();
    const refused = post(b, '/api/batches/launch/plan', { channel: 'example-film' });
    expect(refused.body.ok).toBe(false);
    expect(refused.body.confirm).toBeNull();
    expect(refused.body.guards!.find((g) => g.name === 'open')!.ok).toBe(false);
    b.closeAll();
    const plan = post(b, '/api/batches/launch/plan', { channel: 'example-film' });
    expect(plan.body).toMatchObject({ ok: true, why: 'все защиты пройдены', expires_in_s: 120 });
    const done = post(b, '/api/batches/launch', {
      channel: 'example-film',
      confirm: plan.body.confirm,
    });
    expect(done.status).toBe(200);
    expect(done.body.ok).toBe(true);
    expect(list(b)[0]!.status).toBe('running');
    // Токен одноразовый.
    const again = post(b, '/api/batches/launch', {
      channel: 'example-film',
      confirm: plan.body.confirm,
    });
    expect(again.body.code).toBe('confirm_unknown');
  });

  it('устаревший токен, check_changed, «1 батч в сутки», busy не тратит токен', () => {
    const b = createBatchesBackend();
    b.closeAll();
    const plan = () => post(b, '/api/batches/launch/plan', { channel: 'example-film' }).body;
    const go = (confirm: unknown) =>
      post(b, '/api/batches/launch', { channel: 'example-film', confirm });
    const p1 = plan();
    b.actions.expireTokens();
    expect(go(p1.confirm).body.code).toBe('confirm_expired');
    b.actions.failNext('launch', 'check_changed');
    expect(go(plan().confirm).body.code).toBe('check_changed');
    const p3 = plan();
    b.actions.failNext('launch', 'busy');
    expect(go(p3.confirm).body.code).toBe('busy');
    b.actions.startedToday('example-film');
    const r = go(p3.confirm);
    expect(r.status).toBe(409);
    expect(r.body.code).toBe('refused');
    expect(r.body.message).toContain('1 батч в сутки');
    expect(go(plan().confirm).body.code).toBe('confirm_unknown');
  });

  it('остановка: план с шагом, «и шаг» в токене, ok:false с kill -9, затем остановлен', () => {
    const b = createBatchesBackend();
    const plan = post(b, `/api/batches/${RUNNING}/stop/plan`, { also_step: false }).body;
    expect(plan).toMatchObject({ ok: true, step: { alive: true, run: 'video-editor.s0.a0' } });
    const mismatch = post(b, `/api/batches/${RUNNING}/stop`, {
      confirm: plan.confirm,
      also_step: true,
    });
    expect(mismatch.body.code).toBe('confirm_mismatch');
    b.actions.setStopOutcome('survived');
    const p2 = post(b, `/api/batches/${RUNNING}/stop/plan`, { also_step: false }).body;
    const survived = post(b, `/api/batches/${RUNNING}/stop`, { confirm: p2.confirm });
    expect(survived.status).toBe(200);
    expect(survived.body.ok).toBe(false);
    expect(survived.body.reason).toMatch(/kill -9 -\d+/);
    b.actions.setStopOutcome('stopped');
    const p3 = post(b, `/api/batches/${RUNNING}/stop/plan`, { also_step: false }).body;
    const ok = post(b, `/api/batches/${RUNNING}/stop`, { confirm: p3.confirm, also_step: false });
    expect(ok.body).toMatchObject({ ok: true, stopped: true, step_left_running: true });
    expect(list(b).find((x) => x.batch === RUNNING)!.status).toBe('stopped');
    expect(post(b, `/api/batches/${RUNNING}/stop/plan`).body.ok).toBe(false);
  });

  it('продолжить пересборку: план, «да», снова идёт; идущий — отказ в плане', () => {
    const b = createBatchesBackend();
    expect(post(b, `/api/batches/${RUNNING}/resume/plan`).body.ok).toBe(false);
    const plan = post(b, `/api/batches/${STOPPED}/resume/plan`).body;
    expect(plan.ok).toBe(true);
    const r = post(b, `/api/batches/${STOPPED}/resume`, { confirm: plan.confirm });
    expect(r.body).toMatchObject({ ok: true, resumed: true });
    expect(list(b).find((x) => x.batch === STOPPED)!.status).toBe('running');
  });

  it('упавшие батчи (CC-0089): список, журнал стадии, продолжить одного и отказ другому, защита «сегодня»', () => {
    const b = createBatchesBackend();
    const stranded = () =>
      routeBatches(b, 'GET', new URL('http://x/api/batches/stranded'))!.body as {
        batches: { dir: string; holds_day: boolean; log_url: string | null; stage: string }[];
      };
    expect(stranded().batches).toEqual([]);
    b.strand();
    const rows = stranded().batches;
    expect(rows.map((r) => [r.dir, r.holds_day, r.stage])).toEqual([
      [`pipeline/${STRANDED_FAILED}`, true, 'batch-start'],
      [`pipeline/${STRANDED_STOPPED}`, false, 'trend-hunter'],
    ]);
    const log = routeBatches(b, 'GET', new URL(`http://x${rows[0]!.log_url}`))!;
    expect(log.status).toBe(200);
    expect((log.body as { text: string }).text).toContain('working tree is not clean');
    // Не в списке идущих.
    expect(list(b).map((x) => x.batch)).toEqual([RUNNING, STOPPED]);

    // Держит день: «сегодня» отказывает, батч назван только в строке (как у фабрики).
    const lp = post(b, '/api/batches/launch/plan', { channel: 'example-science' }).body;
    const today = lp.guards!.find((g) => g.name === 'today')!;
    expect(today).toMatchObject({ ok: false, batches: ['example-science/2026-10-10T0405Z'] });
    expect(today.line).toContain('2026-10-10T0405Z');
    expect(lp.guards!.find((g) => g.name === 'run_plan')!.ok).toBe(true);
    const open = post(b, '/api/batches/launch/plan', { channel: 'example-film' }).body.guards!;
    expect(open.find((g) => g.name === 'open')).toMatchObject({ ok: false, batches: [RUNNING] });

    const refused = post(b, `/api/batches/${STRANDED_STOPPED}/resume/plan`).body;
    // Договор 0.54: у отказа код фабрики (старая фабрика без кода — `refused`) и строка центра.
    expect(refused).toMatchObject({
      ok: false,
      reason: STRANDED_REFUSAL,
      confirm: null,
      code: 'refused',
      message: 'Фабрика отказала в продолжении батча.',
    });
    expect(post(b, `/api/batches/${RUNNING}/resume/plan`).body).toMatchObject({
      ok: false,
      code: 'executor_alive',
    });
    const plan = post(b, `/api/batches/${STRANDED_FAILED}/resume/plan`).body;
    expect(plan).toMatchObject({ ok: true, code: null, message: plan.reason });
    expect(
      post(b, `/api/batches/${STRANDED_FAILED}/resume`, { confirm: plan.confirm }).body,
    ).toMatchObject({
      ok: true,
      code: null,
    });
    // Строка `stranded` несёт путь батча и имя журнала (договор 0.54, CC-0089).
    expect(stranded().batches[0]).toMatchObject({
      batch: STRANDED_STOPPED,
      log_name: 'trend-hunter.s0.a0.log',
    });
    expect(stranded().batches.map((r) => r.dir)).toEqual([`pipeline/${STRANDED_STOPPED}`]);
    expect(list(b)[0]).toMatchObject({ batch: STRANDED_FAILED, status: 'running' });
  });
});

describe('подставной повтор со стадии (CC-0123, CF-0739)', () => {
  type Stage = { stage: string; status: string; can: boolean; why: string; code: string | null };
  const get = (b: ReturnType<typeof createBatchesBackend>, batch: string) => {
    const r = routeBatches(b, 'GET', new URL(`http://x/api/batches/${batch}/rerun-from`))!;
    return r.body as { stages_for_rerun: Stage[]; executor_alive: boolean };
  };

  it('стадии: идущий — все закрыты (исполнитель жив); остановленный — шедшие можно, ранние и не шедшие — нет', () => {
    const b = createBatchesBackend();
    const running = get(b, RUNNING);
    expect(running.executor_alive).toBe(true);
    expect(running.stages_for_rerun.every((s) => !s.can && s.code === 'executor_alive')).toBe(true);
    const stopped = get(b, STOPPED).stages_for_rerun;
    const by = (id: string) => stopped.find((s) => s.stage === id)!;
    expect(by('batch-start')).toMatchObject({ can: false, code: 'stage_opens_batch' });
    expect(by('content-researcher')).toMatchObject({ can: true, code: null });
    expect(by('video-editor')).toMatchObject({ can: true, status: 'stopped' });
    expect(by('frame-judge')).toMatchObject({ can: false, code: 'stage_not_run' });
    expect(by('footage-indexer-reserve')).toMatchObject({ can: false, code: 'stage_not_run' });
  });

  it('упал на batch-start: дальше — «раньше упала другая стадия»', () => {
    const b = createBatchesBackend();
    b.strand();
    const st = get(b, STRANDED_FAILED).stages_for_rerun;
    expect(st.some((s) => s.can)).toBe(false);
    expect(st.find((s) => s.stage === 'monitors')).toMatchObject({ code: 'earlier_failed' });
  });

  it('план: что сбросится, что останется, токен к стадии; «да» — сброс, бэкап, батч стоит', () => {
    const b = createBatchesBackend();
    const plan = post(b, `/api/batches/${STOPPED}/rerun-from/plan`, {
      stage: 'content-researcher',
    });
    expect(plan.body.ok).toBe(true);
    expect(plan.body.reset).toEqual(['content-researcher', 'compliance-scripts', 'video-editor']);
    expect(plan.body.kept).toContainEqual({
      stage: 'trend-hunter',
      path: 'pipeline/rebuilds/2026-10-10T0410Z/trends.json',
    });
    const refused = post(b, `/api/batches/${STOPPED}/rerun-from/plan`, { stage: 'frame-judge' });
    expect(refused.body).toMatchObject({ ok: false, confirm: null, code: 'stage_not_run' });
    const done = post(b, `/api/batches/${STOPPED}/rerun-from`, {
      confirm: plan.body.confirm,
      note: 'сценарии заново',
    });
    expect(done.body).toMatchObject({
      ok: true,
      done: true,
      resumed: false,
      note: 'сценарии заново',
    });
    expect(done.body.backup).toContain('run-state.before-rerun-');
    const going = list(b).find((x) => x.batch === STOPPED) as unknown as {
      status: string;
      next: string;
      stages: { id: string; status: string }[];
    };
    expect(going).toMatchObject({ status: 'stopped', next: 'content-researcher' });
    expect(going.stages.find((s) => s.id === 'video-editor')!.status).toBe('pending');
    // Токен одноразовый.
    expect(
      post(b, `/api/batches/${STOPPED}/rerun-from`, { confirm: plan.body.confirm }).body.code,
    ).toBe('confirm_unknown');
  });

  it('«сразу продолжить»: продолжен с pid и журналом; не вышло — resume_failed, сброс остаётся', () => {
    const b = createBatchesBackend();
    const go = (resume: boolean, stage: string) => {
      const p = post(b, `/api/batches/${STOPPED}/rerun-from/plan`, { stage });
      return post(b, `/api/batches/${STOPPED}/rerun-from`, { confirm: p.body.confirm, resume });
    };
    b.actions.setRerunResume('failed');
    const failed = go(true, 'video-editor').body;
    expect(failed).toMatchObject({
      ok: true,
      done: true,
      code: 'resume_failed',
      resume_ok: false,
      resume_code: 'locked',
      resumed: false,
    });
    expect(failed.message).toContain('продолжить не вышло');
    // Сброшенная стадия снова ждёт — повторить с неё уже нечего; с ранней — можно.
    expect(get(b, STOPPED).stages_for_rerun.find((s) => s.stage === 'video-editor')).toMatchObject({
      can: false,
      code: 'stage_not_run',
    });
    b.actions.setRerunResume('ok');
    const ok = go(true, 'content-researcher').body;
    expect(ok).toMatchObject({ ok: true, resumed: true, resume_ok: true, code: null });
    expect(ok.pid).toEqual(expect.any(Number));
    expect(list(b).find((x) => x.batch === STOPPED)!.status).toBe('running');
  });
});
