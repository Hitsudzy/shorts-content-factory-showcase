import { createMemesBackend, routeMemes } from './memes';
import { TECH_BANK } from './memesData';

const url = (p: string) => new URL(`http://x${p}`);
const call = (
  b: ReturnType<typeof createMemesBackend>,
  method: string,
  path: string,
  body: unknown = null,
) => routeMemes(b, method, url(path), body)!;

describe('подставной стол мемов', () => {
  it('обзор: каналы с банками; Reel и Science делят банк по умолчанию', () => {
    const b = createMemesBackend();
    const r = call(b, 'GET', '/api/memes');
    const rows = (r as { body: { channels: { channel: string; bank: string; pending: number }[] } })
      .body.channels;
    expect(rows.map((x) => [x.channel, x.bank])).toEqual([
      ['example-film', 'memes'],
      ['example-science', 'memes'],
      ['example-tech', 'memes-example-tech'],
    ]);
    expect(rows[2]!.pending).toBe(35);
  });

  it('стол Tech: 35 на разборе, GIF, отметка исчезнувшего мема, пустые полосы, отказ вырезки', () => {
    const d = createMemesBackend().desk('example-tech');
    expect(d.entries).toHaveLength(35);
    expect(d.entries.filter((e) => e.gif).length).toBe(4);
    expect(d.status.stale).toEqual(['old-sticker']);
    expect(d.status.blank_bands.map((x) => x.id)).toEqual(['grus-plan', 'two-buttons']);
    const boy = d.entries.find((e) => e.id === 'distracted-boyfriend')!;
    expect(boy.cut_refused).toMatch(/передний план/);
    expect(boy.cut_refused_en).toMatch(/foreground/);
    expect(boy.urls.cut).toBeNull();
    expect(d.entries.find((e) => e.id === 'roll-safe')!.urls.cut).toMatch(/kind=cut$/);
    expect(d.fingerprint).toBeTruthy();
  });

  it('сохранение: base цепочкой, чужой base — check_changed, лишний id — unknown_id', () => {
    const b = createMemesBackend();
    const d = b.desk('example-tech');
    const stale = call(b, 'PUT', '/api/memes/example-tech/marks', {
      decisions: { 'old-sticker': { v: 'drop' } },
      base: d.fingerprint,
    });
    expect(stale.status).toBe(422);
    expect((stale as { body: { code: string } }).body.code).toBe('unknown_id');

    const ok = call(b, 'PUT', '/api/memes/example-tech/marks', {
      decisions: { 'bell-curve': { v: 'keep' } },
      base: d.fingerprint,
    }) as { status: number; body: { fingerprint: string } };
    expect(ok.status).toBe(200);
    expect(ok.body.fingerprint).not.toBe(d.fingerprint);
    const after = b.desk('example-tech');
    expect(after.fingerprint).toBe(ok.body.fingerprint);
    expect(after.decisions['bell-curve']).toMatchObject({ v: 'keep', via: 'center' });

    const again = call(b, 'PUT', '/api/memes/example-tech/marks', {
      decisions: {},
      base: d.fingerprint,
    });
    expect((again as { body: { code: string } }).body.code).toBe('check_changed');
  });

  it('применить: план с токеном, «да» — принятые без review, убранные — прочь', () => {
    const b = createMemesBackend();
    const d = b.desk('example-tech');
    call(b, 'PUT', '/api/memes/example-tech/marks', {
      decisions: { 'bell-curve': { v: 'keep' }, 'evil-kermit': { v: 'drop' } },
      base: d.fingerprint,
    });
    const p = call(b, 'POST', '/api/memes/example-tech/apply/plan', { drop: false }) as {
      body: { ok: boolean; confirm: string; accept: string[]; remove: string[] };
    };
    expect(p.body).toMatchObject({ ok: true, accept: ['bell-curve'], remove: ['evil-kermit'] });
    const r = call(b, 'POST', '/api/memes/example-tech/apply', { confirm: p.body.confirm });
    expect(r.status).toBe(200);
    const after = b.desk('example-tech');
    expect(after.entries).toHaveLength(34);
    expect(after.entries.find((e) => e.id === 'bell-curve')!.review).toBeNull();
    const twice = call(b, 'POST', '/api/memes/example-tech/apply', { confirm: p.body.confirm });
    expect((twice as { body: { code: string } }).body.code).toBe('confirm_unknown');
  });

  it('«да» после чужой правки — check_changed; истёкший токен — confirm_expired', () => {
    const b = createMemesBackend();
    const p = call(b, 'POST', '/api/memes/example-tech/apply/plan', {}) as {
      body: { confirm: string };
    };
    b.editElsewhere(TECH_BANK, 'bell-curve', { v: 'keep' });
    const r = call(b, 'POST', '/api/memes/example-tech/apply', { confirm: p.body.confirm });
    expect((r as { body: { code: string } }).body.code).toBe('check_changed');
    const p2 = call(b, 'POST', '/api/memes/example-tech/apply/plan', {}) as {
      body: { confirm: string };
    };
    b.expireTokens();
    const r2 = call(b, 'POST', '/api/memes/example-tech/apply', { confirm: p2.body.confirm });
    expect((r2 as { body: { code: string } }).body.code).toBe('confirm_expired');
  });

  it('образец намерения в банке по умолчанию не убирается; принятый с «убрать» — held', () => {
    const b = createMemesBackend();
    const d = b.desk('example-film');
    call(b, 'PUT', '/api/memes/example-film/marks', {
      decisions: { 'disaster-girl': { v: 'drop' }, 'epic-handshake': { v: 'drop' } },
      base: d.fingerprint,
    });
    const p = call(b, 'POST', '/api/memes/example-film/apply/plan', { drop: true }) as {
      body: { refused: unknown[]; remove: string[] };
    };
    expect(p.body.refused).toEqual([{ id: 'disaster-girl', intent: 'disaster' }]);
    expect(p.body.remove).toEqual(['epic-handshake']);
    const held = call(b, 'POST', '/api/memes/example-film/apply/plan', { drop: false }) as {
      body: { held: string[]; remove: string[] };
    };
    expect(held.body).toMatchObject({ held: ['epic-handshake'], remove: [] });
  });

  it('картинки: GIF — сам файл, вырезка — png, нет вырезки — no_cut; чужой канал — 404', () => {
    const b = createMemesBackend();
    expect(call(b, 'GET', '/api/memes/example-tech/this-is-fine/thumb')).toMatchObject({
      file: 'meme.gif',
    });
    expect(call(b, 'GET', '/api/memes/example-tech/roll-safe/media?kind=cut')).toMatchObject({
      file: 'cut.png',
    });
    expect(call(b, 'GET', '/api/memes/example-tech/bell-curve/media?kind=cut').status).toBe(404);
    expect(call(b, 'GET', '/api/memes/nope').status).toBe(404);
    expect(routeMemes(b, 'GET', url('/api/batches'), null)).toBeNull();
  });
});
