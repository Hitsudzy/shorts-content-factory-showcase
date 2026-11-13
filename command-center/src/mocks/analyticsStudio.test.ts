import { createAnalyticsBackend, routeAnalytics } from './analytics';

const C = 'example-film';
const at = (p: string) => new URL(`http://x${p}`);
type Backend = ReturnType<typeof createAnalyticsBackend>;
const get = (b: Backend, p: string) => routeAnalytics(b, 'GET', at(p));
const post = (b: Backend, p: string, body: unknown) => routeAnalytics(b, 'POST', at(p), body);
const plan = (b: Backend, body: unknown) =>
  post(b, `/api/analytics/${C}/studio/record/plan`, body)!;
const record = (b: Backend, confirm: string) =>
  post(b, `/api/analytics/${C}/studio/record`, { confirm })!;
const tokenOf = (r: { body: unknown }) => (r.body as { confirm: string }).confirm;

const read = (over: Record<string, unknown> = {}) => ({
  channel: C,
  read_at: '2026-10-10T10:00:00+03:00',
  hook: 'manual',
  ui_language: 'ru',
  videos: [
    {
      video_id: 'dN3vEr5mTh8',
      period_text: 'С момента публикации',
      lines: ['Досмотрели', '72,4 %', 'Пролистали', '27,6 %'],
    },
    { video_id: 'tL0uS2bRk9m', lines: ['Продолжили смотреть'] },
  ],
  rights: { read: true, items: [] },
  ...over,
});

describe('подставной ввод чтения Studio (CC-0074)', () => {
  it('план: доли из строк, замечания, «было», токен — ничего не записано', () => {
    const b = createAnalyticsBackend();
    const r = plan(b, { read: read() });
    expect(r.status).toBe(200);
    const p = r.body as {
      confirm: string;
      read_at: string;
      videos: {
        viewed_pct: number | null;
        swiped_pct: number | null;
        warnings: string[];
        stored: unknown;
      }[];
    };
    expect(p.read_at).toBe('2026-10-10T07:00:00Z');
    expect(p.confirm).toBeTruthy();
    expect(p.videos[0]).toMatchObject({ viewed_pct: 72.4, swiped_pct: 27.6, warnings: [] });
    expect(p.videos[0]!.stored).toBeNull();
    expect(p.videos[1]!.viewed_pct).toBeNull();
    expect(p.videos[1]!.warnings).toEqual([
      'viewed: not recognised in the lines',
      'period_text: the period the shares cover was not copied',
    ]);
    expect(p.videos[1]!.stored).toMatchObject({ note: 'Studio: недостаточно данных' });
    expect(b.entry.state.written).toEqual([]);
  });

  it('«да»: чтения легли, посещение записано, GET видит новое; повтор — unchanged', () => {
    const b = createAnalyticsBackend();
    const r = record(b, tokenOf(plan(b, { read: read() })));
    expect(r.status).toBe(200);
    expect(r.body).toMatchObject({
      studio: { added: 2, replaced: 0, unchanged: 0 },
      visit_logged: true,
    });
    const st = get(b, `/api/analytics/${C}/studio`)!.body as {
      due: { due: boolean };
      latest_reads: { video_id: string; viewed_pct: number | null }[];
    };
    expect(st.due.due).toBe(false);
    expect(st.latest_reads.find((x) => x.video_id === 'dN3vEr5mTh8')?.viewed_pct).toBe(72.4);
    const again = tokenOf(plan(b, { read: read() }));
    expect(record(b, again).body).toMatchObject({
      studio: { added: 0, unchanged: 2 },
      visit_logged: false,
    });
    // Токен одноразовый.
    expect(record(b, again).body).toMatchObject({ code: 'confirm_unknown' });
  });

  it('отказы: чужой ролик, нет зоны; занято — токен цел; истёк; только смотреть', () => {
    const b = createAnalyticsBackend();
    expect(
      plan(b, { read: read({ videos: [{ video_id: 'rTx5090mLt1', lines: [] }] }) }),
    ).toMatchObject({
      status: 422,
      body: { code: 'read_refused', message: expect.stringContaining('of channel example-tech') },
    });
    expect(plan(b, { read: read({ read_at: '2026-10-10T10:00:00' }) }).body).toMatchObject({
      code: 'read_refused',
      message: expect.stringContaining('no zone'),
    });
    const t = tokenOf(plan(b, { read: read() }));
    b.entry.state.next = 'busy';
    expect(record(b, t).body).toMatchObject({ code: 'busy' });
    b.entry.expireTokens();
    expect(record(b, t).body).toMatchObject({ code: 'confirm_expired' });
    b.entry.state.planNext = 'journal_unreadable';
    expect(plan(b, { read: read() })).toMatchObject({
      status: 409,
      body: { code: 'journal_unreadable' },
    });
    b.entry.state.readOnly = true;
    expect(plan(b, { read: read() })).toMatchObject({
      status: 409,
      body: { code: 'not_working_factory' },
    });
    expect(b.entry.state.written).toEqual([]);
  });

  it('проверка изменилась между планом и «да» — check_changed', () => {
    const b = createAnalyticsBackend();
    const first = tokenOf(plan(b, { read: read() }));
    const other = tokenOf(plan(b, { read: read({ read_at: '2026-10-10T11:00:00+03:00' }) }));
    expect(record(b, other).status).toBe(200);
    expect(record(b, first).body).toMatchObject({ code: 'check_changed' });
  });
});
