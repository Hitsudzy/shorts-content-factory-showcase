import { createBatchesBackend, PAST, routeBatches, RUNNING, STOPPED } from './batches';

const get = (b: ReturnType<typeof createBatchesBackend>, path: string) =>
  routeBatches(b, 'GET', new URL(`http://x${path}`));

type Body = Record<string, unknown> & {
  events?: { offset: number }[];
  next?: number;
  more?: boolean;
  reset?: boolean;
};

describe('подставные батчи', () => {
  it('маршруты: список, батч (и пересборка), история, стадии, журнал; запись — не их', () => {
    const b = createBatchesBackend();
    const going = get(b, '/api/batches')!.body as {
      batches: { batch: string; open_why?: string | null }[];
    };
    expect(going.batches.map((x) => x.batch)).toEqual([RUNNING, STOPPED]);
    expect(going.batches[0]!.open_why).toBe('нет batch-done');
    expect(get(b, `/api/batches/${STOPPED}`)!.status).toBe(200);
    expect(get(b, `/api/batches/${STOPPED}`)!.body).toMatchObject({ quiet: [] });
    expect(get(b, '/api/batches/history?limit=2')!.body).toMatchObject({ runs: [{}, {}] });
    expect(get(b, `/api/batches/${PAST}/stages`)!.body).toMatchObject({
      closed: true,
      open_why: null,
    });
    expect(get(b, `/api/batches/${RUNNING}/stages`)!.body).toMatchObject({
      closed: false,
      open_why: 'нет batch-done',
      open_stages: ['video-editor'],
    });
    expect(get(b, '/api/batches/x/y')!.status).toBe(404);
    expect(routeBatches(b, 'PUT', new URL(`http://x/api/batches/${RUNNING}/stop`))).toBeNull();
  });

  it('события: хвост без after, more при limit, reset после замены файла', () => {
    const b = createBatchesBackend();
    const tail = get(b, `/api/batches/${RUNNING}/events`)!.body as Body;
    expect(tail.events).toHaveLength(30);
    expect(tail.reset).toBe(false);
    b.append(RUNNING, 5);
    const page = get(b, `/api/batches/${RUNNING}/events?after=${tail.next}&limit=2`)!.body as Body;
    expect(page.events).toHaveLength(2);
    expect(page.more).toBe(true);
    expect(page.events![0]!.offset).toBe(tail.next);
    b.replace(RUNNING, 3);
    const reset = get(b, `/api/batches/${RUNNING}/events?after=${page.next}`)!.body as Body;
    expect(reset.reset).toBe(true);
    expect(reset.events).toHaveLength(3);
    expect(reset.events![0]!.offset).toBe(0);
    expect(b.eventCalls).toEqual([null, tail.next, page.next]);
  });

  it('хвост журнала: с целой строки, truncated и offset', () => {
    const b = createBatchesBackend();
    const t = get(b, `/api/batches/${PAST}/logs/video-editor.s0.a0.log?bytes=200`)!.body as {
      truncated: boolean;
      offset: number;
      size: number;
      text: string;
    };
    expect(t.truncated).toBe(true);
    expect(t.offset).toBeGreaterThan(0);
    expect(t.size).toBeGreaterThan(t.offset);
    expect(t.text.startsWith('2026-')).toBe(true);
    const whole = get(b, `/api/batches/${PAST}/logs/batch-start.s0.a0.log`)!.body;
    expect(whole).toMatchObject({ truncated: false, offset: 0 });
    expect(get(b, `/api/batches/${PAST}/logs/nope.log`)!.status).toBe(404);
  });

  it('футаж по темам (CC-0119): идущий — по файлу, счётчики по состояниям; прошлый — пусто', () => {
    const b = createBatchesBackend();
    const f = get(b, `/api/batches/${RUNNING}/footage`)!.body as {
      source: string;
      running: boolean | null;
      topics: { topic_id: string; state: string }[];
      counts: Record<string, number>;
    };
    expect(f.source).toBe('file');
    expect(f.running).toBe(true);
    expect(f.topics.map((t) => t.state)).toEqual([
      'collected',
      'collecting',
      'short',
      'refused',
      'queued',
    ]);
    expect(f.counts).toMatchObject({ collected: 1, short: 1 });
    expect(get(b, `/api/batches/${PAST}/footage`)!.body).toMatchObject({
      source: 'none',
      topics: [],
    });
    b.setFootage(PAST, { source: 'events' });
    expect(get(b, `/api/batches/${PAST}/footage`)!.body).toMatchObject({ source: 'events' });
    expect(get(b, '/api/batches/nope/x/footage')!.status).toBe(404);
  });
});
