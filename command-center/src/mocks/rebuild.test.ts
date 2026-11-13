import { describe, expect, it } from 'vitest';

import { PAST } from './batches';
import { createVideosBackend, routeVideos } from './videos';

const url = (p: string) => new URL(`http://127.0.0.1/api/batches/${PAST}${p}`);

describe('подставная пересборка', () => {
  it('секунды Delver: 12 — блок 4 рядом с 5, 18 — 7, 24 — 9; концовка и сплит — с note', () => {
    const b = createVideosBackend();
    const r = routeVideos(b, 'GET', url('/videos/delver/blocks?at=12,18,24,28,42'));
    const body = (r as { body: { moments: Record<string, unknown>[]; exclude: string[] } }).body;
    expect(body.exclude).toEqual(['4=wIM1PDRvKSE:32', '7=wIM1PDRvKSE:55', '9=ZLXL1L0TfsI:19']);
    expect(body.moments[0]).toMatchObject({ block: 4, near: [{ block: 5 }] });
    expect(body.moments.map((m) => m.block)).toEqual([4, 7, 9, 10, null]);
    expect(body.moments[3]).toMatchObject({ exclude: null, note: expect.any(String) });
    expect(body.moments[4]).toMatchObject({ ending: true, exclude: null });
    expect(routeVideos(b, 'GET', url('/videos/delver/blocks?at=x'))).toMatchObject({
      status: 422,
    });
  });

  it('план → токен → «да»; busy токен не тратит; повтор — confirm_unknown; старт не удался', () => {
    const b = createVideosBackend();
    const plan = (body: unknown) =>
      routeVideos(b, 'POST', url('/rebuild/plan'), {}, body) as {
        body: { ok: boolean; confirm: string | null; reason: string };
      };
    const yes = (confirm: string | null) =>
      routeVideos(b, 'POST', url('/rebuild'), {}, { confirm }) as {
        status: number;
        body: Record<string, unknown>;
      };
    const ex = { videos: { delver: { exclude: ['4=wIM1PDRvKSE:32'] } } };
    expect(plan({ videos: ['delver'], mode: 'rewrite', notes: ex }).body.ok).toBe(false);
    const p = plan({ videos: ['delver'], mode: 'reedit', notes: ex }).body;
    expect(p.ok).toBe(true);
    b.rebuild.state.next = 'busy';
    expect(yes(p.confirm)).toMatchObject({ status: 409, body: { code: 'busy' } });
    b.rebuild.state.next = 'ok';
    expect(yes(p.confirm)).toMatchObject({ status: 200, body: { ok: true, started: true } });
    expect(yes(p.confirm)).toMatchObject({ status: 409, body: { code: 'confirm_unknown' } });
    b.rebuild.state.next = 'start_failed';
    const q = plan({ videos: ['delver'], mode: 'reedit' }).body;
    expect(yes(q.confirm)).toMatchObject({
      status: 200,
      body: {
        ok: false,
        started: false,
        state: 'pipeline/rebuilds/2026-10-10T1930Z/run-state.json',
      },
    });
  });
});
