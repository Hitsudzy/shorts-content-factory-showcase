import { http, HttpResponse } from 'msw';

import { server } from '@/mocks/server';

import { planResume, PLAN_TIMEOUT_MS, STOP_TIMEOUT_MS } from './batchActions';
import { api, getHealth } from './client';
import snapshot from './openapi.snapshot.json';
import { ARCHIVE_TIMEOUT_MS } from './maintenance';
import { UPLOAD_TIMEOUT_MS } from './publishWrites';
import {
  FALLBACK_TITLE,
  getWritesInFlight,
  PLAN_TITLE,
  probe,
  trackWrite,
  upToText,
  WRITE_LABELS,
  writeLabel,
} from './writeLock';

const WRITE_METHODS = ['post', 'put', 'patch', 'delete'];

/** Ответ, который держим, пока тест не отпустит. */
function held() {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  return { gate, release };
}

describe('writeLabel: подпись записи по маршруту договора', () => {
  it('каждая запись договора (кроме планов) — в таблице подписей', () => {
    const missing: string[] = [];
    for (const [path, ops] of Object.entries(snapshot.paths as Record<string, object>)) {
      for (const m of Object.keys(ops)) {
        if (!WRITE_METHODS.includes(m) || path.endsWith('/plan')) continue;
        const key = `${m.toUpperCase()} ${path}`;
        if (!(key in WRITE_LABELS)) missing.push(key);
      }
    }
    expect(missing).toEqual([]);
  });

  it('чтения и записи, которые ничего не пишут, — без слоя', () => {
    expect(writeLabel('GET', '/api/memes/{channel}')).toBeNull();
    expect(writeLabel('POST', '/api/channels/{channel}/check', {})).toBeNull();
    expect(writeLabel('POST', '/api/channels', { channel_id: 'x', dry_run: true })).toBeNull();
    expect(writeLabel('POST', '/api/channels', { channel_id: 'x', dry_run: false })).toEqual({
      title: 'Создаю канал на фабрике…',
      kind: 'write',
    });
  });

  it('план — коротко «Готовлю план…», запись — словами действия', () => {
    expect(writeLabel('POST', '/api/memes/{channel}/apply/plan')).toEqual({
      title: PLAN_TITLE,
      kind: 'plan',
    });
    expect(writeLabel('POST', '/api/memes/{channel}/apply')).toEqual({
      title: 'Применяю разбор…',
      kind: 'write',
    });
    expect(writeLabel('put', '/api/memes/{channel}/marks')?.title).toBe('Сохраняю отметки…');
    expect(writeLabel('POST', '/api/unknown/route')?.title).toBe(FALLBACK_TITLE);
  });

  it('подписи — с одним символом «…», не с тремя точками (CC-0093)', () => {
    const titles = [
      PLAN_TITLE,
      FALLBACK_TITLE,
      ...Object.values(WRITE_LABELS).flatMap((e) =>
        e === null ? [] : [typeof e === 'string' ? e : e.title],
      ),
    ];
    expect(titles.filter((t) => t.includes('...'))).toEqual([]);
    expect(titles.filter((t) => !t.endsWith('…'))).toEqual([]);
  });

  it('долгие записи — с потолком центра: загрузка, остановка, пересборка', () => {
    expect(writeLabel('POST', '/api/publish/{channel}/upload')?.upToMs).toBe(UPLOAD_TIMEOUT_MS);
    expect(writeLabel('POST', '/api/batches/{channel}/{batch_id}/stop')?.upToMs).toBe(
      STOP_TIMEOUT_MS,
    );
    expect(writeLabel('POST', '/api/batches/{channel}/{batch_id}/rebuild')?.upToMs).toBe(
      PLAN_TIMEOUT_MS,
    );
    expect(writeLabel('POST', '/api/maintenance/archive')?.upToMs).toBe(ARCHIVE_TIMEOUT_MS);
    expect(writeLabel('POST', '/api/questions/{qid}/answer')?.upToMs).toBeUndefined();
  });

  it('upToText: потолок словами', () => {
    expect(upToText(20 * 60_000)).toBe('до 20 минут');
    expect(upToText(60_000)).toBe('до 1 минуты');
    expect(upToText(2 * 60_000)).toBe('до 2 минут');
    expect(upToText(70_000)).toBe('до 70 секунд');
    expect(upToText(30_000)).toBe('до 30 секунд');
    expect(upToText(21_000)).toBe('до 21 секунды');
  });
});

describe('учёт записей в полёте', () => {
  it('trackWrite: запись видна, пока идёт, и снимается при успехе и при отказе', async () => {
    const label = { title: 'Сохраняю отметки…', kind: 'write' as const };
    const a = held();
    const ok = trackWrite(label, () => a.gate.then(() => 1));
    expect(getWritesInFlight().map((w) => w.title)).toEqual(['Сохраняю отметки…']);
    a.release();
    await expect(ok).resolves.toBe(1);
    expect(getWritesInFlight()).toEqual([]);

    const bad = trackWrite(label, () => Promise.reject(new Error('отказ')));
    expect(getWritesInFlight()).toHaveLength(1);
    await expect(bad).rejects.toThrow('отказ');
    expect(getWritesInFlight()).toEqual([]);
  });

  it('без подписи (null) — не учитывается', async () => {
    await trackWrite(null, async () => {
      expect(getWritesInFlight()).toEqual([]);
    });
  });

  it('клиент api: PUT в полёте учтён с подписью маршрута, ответ снимает', async () => {
    const h = held();
    server.use(
      http.put('*/api/memes/:channel/marks', async () => {
        await h.gate;
        return HttpResponse.json({ ok: true });
      }),
    );
    const p = api.PUT('/api/memes/{channel}/marks', {
      params: { path: { channel: 'example-tech' } },
      body: { decisions: {}, base: null },
    });
    expect(getWritesInFlight().map((w) => w.title)).toEqual(['Сохраняю отметки…']);
    h.release();
    await p;
    expect(getWritesInFlight()).toEqual([]);
  });

  it('клиент api: отказ фабрики (409) и обрыв сети тоже снимают', async () => {
    server.use(
      http.post('*/api/memes/:channel/apply', () =>
        HttpResponse.json({ code: 'busy', message: 'занято' }, { status: 409 }),
      ),
      http.post('*/api/questions/:qid/answer', () => HttpResponse.error()),
    );
    const refused = api.POST('/api/memes/{channel}/apply', {
      params: { path: { channel: 'example-tech' } },
      body: { confirm: 't' },
    });
    expect(getWritesInFlight()).toHaveLength(1);
    expect((await refused).response.status).toBe(409);
    expect(getWritesInFlight()).toEqual([]);

    const broken = api.POST('/api/questions/{qid}/answer', {
      params: { path: { qid: 'q1' } },
      body: { text: 'да', by: 'user', accept: false },
    });
    expect(getWritesInFlight().map((w) => w.title)).toEqual(['Записываю ответ на вопрос…']);
    await expect(broken).rejects.toThrow();
    expect(getWritesInFlight()).toEqual([]);
  });

  it('фоновая проверка (probe): план без слоя, запись под probe — всё равно под слоем (CC-0094)', async () => {
    const quiet = probe(() => planResume('example-film/2026-10-10T0530Z'));
    expect(getWritesInFlight()).toEqual([]);
    await quiet;
    const loud = planResume('example-film/2026-10-10T0530Z');
    expect(getWritesInFlight().map((w) => w.title)).toEqual([PLAN_TITLE]);
    await loud;
    server.use(http.put('*/api/memes/:channel/marks', () => HttpResponse.json({ ok: true })));
    const write = probe(() =>
      api.PUT('/api/memes/{channel}/marks', {
        params: { path: { channel: 'example-tech' } },
        body: { decisions: {}, base: null },
      }),
    );
    expect(getWritesInFlight().map((w) => w.title)).toEqual(['Сохраняю отметки…']);
    await write;
    expect(getWritesInFlight()).toEqual([]);
  });

  it('чтения (GET) не учитываются', async () => {
    const p = getHealth();
    expect(getWritesInFlight()).toEqual([]);
    await p;
  });
});
