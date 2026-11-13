import {
  createChecklist,
  detect,
  markDone,
  parseDone,
  TASKS,
  TASKS_STORAGE_KEY,
  type WriteEvent,
} from './checklist';

const post = (path: string, status = 200, code: string | null = null): WriteEvent => ({
  method: 'POST',
  path,
  status,
  code,
});

function memory(broken = false) {
  const m = new Map<string, string>();
  const guard = () => {
    if (broken) throw new DOMException('denied', 'SecurityError');
  };
  return {
    m,
    getItem: (k: string) => {
      guard();
      return m.get(k) ?? null;
    },
    setItem: (k: string, v: string) => {
      guard();
      m.set(k, v);
    },
    removeItem: (k: string) => {
      guard();
      m.delete(k);
    },
  };
}

describe('задания тренировки: что закрывает ответ демо-сервера', () => {
  it('каждое задание — своим ответом; планы и чтение ничего не закрывают', () => {
    const b = '/api/batches/example-film/2026-10-09T0215Z';
    expect(detect(post(`${b}/videos/delver/acceptance`))).toEqual(['accept']);
    expect(detect(post('/api/publish/example-film/pause/set'))).toEqual(['pause', 'confirm']);
    expect(detect(post('/api/publish/example-film/pause/set/plan'))).toEqual([]);
    expect(detect(post('/api/publish/example-film/card/place'))).toEqual(['card', 'confirm']);
    expect(detect(post('/api/questions/Q9/answer'))).toEqual(['answer']);
    expect(detect(post('/api/requests'))).toEqual(['ask']);
    expect(detect(post('/api/requests/R1/cancel'))).toEqual([]);
    expect(detect(post('/api/publish/example-film/upload'))).toEqual(['upload', 'confirm']);
    expect(detect(post('/api/publish/example-film/holds/2026-10-09T0215Z/t-7/sign'))).toEqual([
      'hold',
      'confirm',
    ]);
    expect(detect(post('/api/publish/example-film/holds/2026-10-09T0215Z/t-7/sign/plan'))).toEqual(
      [],
    );
    expect(detect(post(`${b}/stop`))).toEqual(['confirm']);
    expect(detect(post('/api/batches/launch'))).toEqual(['confirm']);
    expect(detect({ ...post('/api/memes/example-tech/marks'), method: 'PUT' })).toEqual(['meme']);
    expect(detect(post('/api/memes/example-tech/apply/plan'))).toEqual([]);
    expect(detect(post('/api/memes/example-tech/apply'))).toEqual(['confirm']);
    expect(detect(post('/api/analytics/example-film/studio/record'))).toEqual(['studio', 'confirm']);
    expect(detect(post('/api/analytics/example-film/studio/record/plan'))).toEqual([]);
    expect(detect({ method: 'GET', path: '/api/requests', status: 200, code: null })).toEqual([]);
  });

  it('«план устарел» — по коду; прочий отказ записи — «отказ фабрики»', () => {
    expect(detect(post('/api/publish/example-film/pause/set', 409, 'confirm_expired'))).toEqual([
      'expired',
    ]);
    expect(detect(post('/api/publish/example-film/pause/set', 409, 'refused'))).toEqual(['refused']);
    expect(detect(post('/api/questions/Q9/answer', 409, null))).toEqual(['refused']);
    expect(detect(post('/api/publish/example-film/upload', 500, 'factory_broken'))).toEqual([
      'refused',
    ]);
  });
});

describe('отметки: в браузере, в порядке списка, без падений', () => {
  it('разбор сохранённого: мусор, чужие и повторы отброшены', () => {
    expect(parseDone(null)).toEqual([]);
    expect(parseDone('{oops')).toEqual([]);
    expect(parseDone('{"a":1}')).toEqual([]);
    expect(parseDone('["hold","nope","accept","accept",3]')).toEqual(['accept', 'hold']);
  });

  it('markDone: тот же массив, если нового нет; порядок — как в списке', () => {
    const a = markDone([], ['ask']);
    expect(markDone(a, ['ask'])).toBe(a);
    expect(markDone(a, ['accept'])).toEqual(['accept', 'ask']);
  });

  it('createChecklist: пишет в хранилище, сообщает подписчикам, «начать заново» — пусто', () => {
    const s = memory();
    const c = createChecklist(s);
    const seen = vi.fn();
    c.subscribe(seen);
    expect(c.record(post('/api/requests'))).toEqual(['ask']);
    expect(c.record(post('/api/requests'))).toEqual([]);
    expect(seen).toHaveBeenCalledTimes(1);
    expect(JSON.parse(s.m.get(TASKS_STORAGE_KEY)!)).toEqual(['ask']);
    expect(createChecklist(s).get()).toEqual(['ask']);
    c.reset();
    expect(c.get()).toEqual([]);
    expect(s.m.get(TASKS_STORAGE_KEY)).toBe('[]');
  });

  it('хранилище бросает или его нет — отметки живут в памяти', () => {
    for (const s of [memory(true), null]) {
      const c = createChecklist(s);
      expect(c.get()).toEqual([]);
      c.record(post('/api/requests'));
      expect(c.get()).toEqual(['ask']);
      c.reset();
      expect(c.get()).toEqual([]);
    }
  });

  it('двенадцать заданий; «только демо» — загрузка на YouTube и подпись холда', () => {
    expect(TASKS).toHaveLength(12);
    expect(TASKS.filter((t) => t.demoOnly).map((t) => t.id)).toEqual(['upload', 'hold']);
  });
});
