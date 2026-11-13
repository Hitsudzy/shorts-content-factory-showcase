import { createNotifyBackend, mskText, parseWhen, routeNotify } from './notify';

const at = (p: string) => new URL(`http://x${p}`);
type B = ReturnType<typeof createNotifyBackend>;
const get = (b: B, p: string) => routeNotify(b, 'GET', at(p), null);
const post = (b: B, p: string, body: unknown) => routeNotify(b, 'POST', at(p), body);
const NOW = '2026-10-12T15:40:00Z'; // 18:40 МСК

describe('подставные уведомления и напоминания', () => {
  it('время по Москве: «ЧЧ:ММ» — ближайшее, дата — не в прошлом', () => {
    expect(parseWhen('21:00', NOW)).toBe('2026-10-12T18:00:00Z');
    expect(parseWhen('09:30 МСК', NOW)).toBe('2026-10-13T06:30:00Z');
    expect(parseWhen('2026-10-20 10:00', NOW)).toBe('2026-10-20T07:00:00Z');
    expect(() => parseWhen('2026-10-01 10:00', NOW)).toThrow(/has passed/);
    expect(() => parseWhen('25:00', NOW)).toThrow(/no such time/);
    expect(() => parseWhen('завтра', NOW)).toThrow(/expected/);
    expect(mskText('2026-10-12T18:00:00Z')).toBe('2026-10-12 21:00 МСК');
  });

  it('журнал: последние 20 из 23, новые в конце; фильтр по виду и каналу; 0 — все', () => {
    const b = createNotifyBackend();
    const j = get(b, '/api/notify/journal?limit=20')!.body as {
      total: number;
      events: { kind: string }[];
      kinds: string[];
    };
    expect(j.total).toBe(23);
    expect(j.events).toHaveLength(20);
    expect(j.events.at(-1)!.kind).toBe('test');
    expect(j.kinds).toContain('reminder');
    const all = get(b, '/api/notify/journal?limit=0')!.body as { events: unknown[] };
    expect(all.events).toHaveLength(23);
    const tech = get(b, '/api/notify/journal?limit=0&channel=example-tech&kind=run_halted')!
      .body as { total: number };
    expect(tech.total).toBe(1);
    const bad = get(b, '/api/notify/journal?kind=nope');
    expect(bad?.status).toBe(422);
    expect(bad?.body).toMatchObject({ code: 'bad_kind' });
  });

  it('напоминания: без all — ждут и не дошедшие; с all — ещё отправленное и отменённое', () => {
    const b = createNotifyBackend();
    const now = get(b, '/api/notify/reminders?all=false')!.body as {
      reminders: { id: string; status: string; due_msk: string }[];
    };
    expect(now.reminders.map((r) => `${r.id}:${r.status}`)).toEqual([
      'R3:failed',
      'R4:exhausted',
      'R5:pending',
      'R6:pending',
    ]);
    expect(now.reminders[2]!.due_msk).toBe('2026-10-12 21:00 МСК');
    const all = get(b, '/api/notify/reminders?all=true')!.body as { reminders: unknown[] };
    expect(all.reminders).toHaveLength(6);
  });

  it('проверка — строки CLI, ничего не отправлено; сломанное чтение — 500', () => {
    const b = createNotifyBackend();
    const c = get(b, '/api/notify/check')!.body as { lines: string[]; sent: boolean };
    expect(c.sent).toBe(false);
    expect(c.lines.at(-1)).toContain('nothing sent');
    b.state.refuse.check = true;
    expect(get(b, '/api/notify/check')).toMatchObject({
      status: 500,
      body: { code: 'factory_broken' },
    });
  });

  it('план → «да» ставит; токен одноразовый; тот же текст на то же время — created false', () => {
    const b = createNotifyBackend();
    const p = post(b, '/api/notify/reminders/plan', {
      at: '21:00',
      text: '  Позвонить \n монтажёру ',
    })!.body as { due: string; text: string; confirm: string; due_msk: string };
    expect(p.due).toBe('2026-10-12T18:00:00Z');
    expect(p.text).toBe('Позвонить монтажёру');
    expect(b.state.written).toEqual([]);
    const r = post(b, '/api/notify/reminders', { confirm: p.confirm })!.body as {
      created: boolean;
      reminder: { id: string; status: string };
    };
    expect(r).toMatchObject({ created: true, reminder: { id: 'R7', status: 'pending' } });
    expect(post(b, '/api/notify/reminders', { confirm: p.confirm })?.body).toMatchObject({
      code: 'confirm_unknown',
    });
    const again = post(b, '/api/notify/reminders/plan', {
      at: '21:00',
      text: 'Позвонить монтажёру',
    })!.body as { confirm: string };
    expect(post(b, '/api/notify/reminders', { confirm: again.confirm })?.body).toMatchObject({
      created: false,
      reminder: { id: 'R7' },
    });
    expect(b.state.written).toEqual(['R7']);
  });

  it('отказы: время, текст, сдвиг времени, истёкший токен, только смотреть', () => {
    const b = createNotifyBackend();
    expect(post(b, '/api/notify/reminders/plan', { at: 'вечером', text: 'x' })).toMatchObject({
      status: 422,
      body: { code: 'bad_time' },
    });
    expect(post(b, '/api/notify/reminders/plan', { at: '21:00', text: '  ' })).toMatchObject({
      status: 422,
      body: { code: 'no_text' },
    });
    const p = post(b, '/api/notify/reminders/plan', { at: '19:00', text: 'x' })!.body as {
      confirm: string;
    };
    b.state.now = '2026-10-12T16:30:00Z'; // 19:30 МСК — «19:00» уже завтра
    expect(post(b, '/api/notify/reminders', { confirm: p.confirm })?.body).toMatchObject({
      code: 'check_changed',
    });
    const q = post(b, '/api/notify/reminders/plan', { at: '21:00', text: 'x' })!.body as {
      confirm: string;
    };
    b.expireTokens();
    expect(post(b, '/api/notify/reminders', { confirm: q.confirm })?.body).toMatchObject({
      code: 'confirm_expired',
    });
    b.state.readOnly = true;
    expect(post(b, '/api/notify/reminders/plan', { at: '21:00', text: 'x' })).toMatchObject({
      status: 409,
      body: { code: 'not_working_factory' },
    });
  });

  it('не к нему — null', () => {
    const b = createNotifyBackend();
    expect(routeNotify(b, 'GET', at('/api/channels/example-film/rights-holders'), null)).toBeNull();
    expect(routeNotify(b, 'DELETE', at('/api/notify/reminders'), null)).toBeNull();
    expect(routeNotify(b, 'GET', at('/api/notify/reminders/R5/cancel'), null)).toBeNull();
  });

  it('отмена (CC-0087): план → «да» отменяет из центра; отправленное и отменённое — отказ', () => {
    const b = createNotifyBackend();
    const plan = post(b, '/api/notify/reminders/R5/cancel/plan', null);
    expect(plan).toMatchObject({ status: 200, body: { ok: true, id: 'R5', status: 'pending' } });
    const confirm = (plan!.body as { confirm: string }).confirm;
    expect(post(b, '/api/notify/reminders/R6/cancel', { confirm })).toMatchObject({
      status: 409,
      body: { code: 'confirm_mismatch' },
    });
    const plan2 = post(b, '/api/notify/reminders/R5/cancel/plan', null);
    const done = post(b, '/api/notify/reminders/R5/cancel', {
      confirm: (plan2!.body as { confirm: string }).confirm,
    });
    expect(done).toMatchObject({
      status: 200,
      body: { cancelled_by: 'user', cancelled_via: 'center', reminder: { status: 'cancelled' } },
    });
    expect(post(b, '/api/notify/reminders/R5/cancel/plan', null)).toMatchObject({
      status: 409,
      body: { code: 'not_cancellable' },
    });
    expect(post(b, '/api/notify/reminders/R1/cancel/plan', null)).toMatchObject({
      status: 409,
      body: { code: 'not_cancellable' },
    });
    expect(post(b, '/api/notify/reminders/R99/cancel/plan', null)).toMatchObject({
      status: 404,
      body: { code: 'no_reminder' },
    });
    const plan3 = post(b, '/api/notify/reminders/R6/cancel/plan', null);
    b.state.next = 'sent_meanwhile';
    expect(
      post(b, '/api/notify/reminders/R6/cancel', {
        confirm: (plan3!.body as { confirm: string }).confirm,
      }),
    ).toMatchObject({ status: 409, body: { code: 'not_cancellable' } });
  });
});
