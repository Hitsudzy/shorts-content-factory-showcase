// Подставной перенос (src/mocks/publishMove.ts) держит форму фабрики CC-0165: пачка судится
// целиком («25→24, 26→25 и 24-й в копилку» проходит, без возврата — `day_taken`), в копилку —
// только ролик не в Studio (`in_studio`), перенос ролика в Studio — строка STUDIO и правка
// журнала; токен только у годного плана; `check_changed` и `batch_open` — на «да»; 422.
import { BatchError, problemCode } from '@/api/batchProblem';
import { getQueue } from '@/api/publish';
import { confirmMove, planMove, type MoveBody } from '@/api/publishMove';
import { getStash } from '@/api/stash';
import { getVideos } from '@/api/videos';
import { stashBatch } from '@/pages/publishing/stashWords';

import { publish } from './handlers';
import { NOT_READY, PLACED, READY, REEL, UPLOADED } from './publish';
import { STASH_RESERVE, STASH_RESERVE_ID } from './stash';

const refused = async (p: Promise<unknown>) => {
  const e = await p.then(
    () => null,
    (x: unknown) => x,
  );
  expect(e).toBeInstanceOf(BatchError);
  return { code: problemCode(e), status: (e as BatchError).status };
};

const dayOf = async (slug: string) =>
  (await getQueue(REEL, 14)).slots.find((s) => s.taken_by === slug)?.day ?? null;

describe('подставной перенос', () => {
  it('сдвиг 23.10: все с 14.10 на день раньше и 13.10 в копилку — одним планом, «да» переставляет ленту', async () => {
    const fillers = publish.fillReelDays();
    expect(fillers[0]).toBe('filler-1');
    const moves = [
      { slug: 'filler-1', day: '2026-10-13' },
      { slug: NOT_READY, day: '2026-10-14' },
      { slug: 'filler-2', day: '2026-10-15' },
    ];
    // Без возврата 13-го: переносы стоят друг за другом — отказаны все (`day_taken`).
    const no = await planMove(REEL, { moves, unplace: [] });
    expect(no.ok).toBe(false);
    expect(no.confirm).toBeNull();
    expect(no.items.map((i) => i.refusals[0]?.code)).toEqual([
      'day_taken',
      'day_taken',
      'day_taken',
    ]);
    // С возвратом и в любом порядке — годен.
    const plan = await planMove(REEL, { moves: [...moves].reverse(), unplace: [READY] });
    expect(plan.ok).toBe(true);
    expect(plan.confirm).toBeTruthy();
    expect(plan.items[0]).toMatchObject({ op: 'unplace', slug: READY, in_studio: false });
    expect(plan.moved).toBe(3);
    expect(plan.unplaced).toBe(1);
    const r = await confirmMove(REEL, plan.confirm!, plan.base_sha256);
    expect(r.written).toBe(true);
    expect(r.commit).toBeTruthy();
    expect(await dayOf('filler-1')).toBe('2026-10-13');
    expect(await dayOf(NOT_READY)).toBe('2026-10-14');
    expect(await dayOf(READY)).toBeNull();
    expect((await getStash(REEL)).videos.map((v) => v.slug)).toContain(READY);
    expect(publish.move.state.written).toHaveLength(1);
  });

  it('ролик в Studio: в копилку — `in_studio`; перенос — строка STUDIO и правка журнала', async () => {
    const no = await planMove(REEL, { moves: [], unplace: [PLACED] });
    expect(no.ok).toBe(false);
    expect(no.items[0]!.refusals[0]).toMatchObject({ code: 'in_studio', slug: PLACED });
    expect(no.items[0]!.refusals[0]!.message).toMatch(/уже в Studio/);
    const plan = await planMove(REEL, {
      moves: [{ slug: PLACED, day: '2026-10-14' }],
      unplace: [],
    });
    expect(plan.ok).toBe(true);
    expect(plan.items[0]!.warnings[0]).toMatch(/^STUDIO delver/);
    const r = await confirmMove(REEL, plan.confirm!, plan.base_sha256);
    expect(r.items[0]!.journal).toMatchObject({
      from_at: '2026-10-11T22:00:00Z',
      to_at: '2026-10-13T22:00:00Z',
    });
    expect(r.touched).toContain('publish/uploads.json');
    expect(await dayOf(PLACED)).toBe('2026-10-14');
    expect(await dayOf(UPLOADED)).toBe('2026-10-11');
  });

  it('данные изменились с плана — 409 check_changed; батч — только на «да»; 422 и только смотреть', async () => {
    const body: MoveBody = { moves: [{ slug: NOT_READY, day: '2026-10-14' }], unplace: [] };
    const plan = await planMove(REEL, body);
    expect(await refused(confirmMove(REEL, plan.confirm!, 'sha256:other'))).toMatchObject({
      code: 'check_changed',
      status: 409,
    });
    const again = await planMove(REEL, body);
    expect(again.refusals).toEqual([]);
    publish.move.state.next = 'batch_open';
    expect(await refused(confirmMove(REEL, again.confirm!, again.base_sha256))).toMatchObject({
      code: 'batch_open',
    });
    const extra = { moves: [], unplace: [], extra: 1 } as unknown as MoveBody;
    expect(await refused(planMove(REEL, extra))).toMatchObject({ code: 'invalid', status: 422 });
    const many = Array.from({ length: 61 }, (_, i) => `v${i}`);
    expect(await refused(planMove(REEL, { moves: [], unplace: many }))).toMatchObject({
      status: 422,
    });
    publish.writes.state.readOnly = true;
    expect(await refused(planMove(REEL, { moves: [], unplace: [READY] }))).toMatchObject({
      code: 'not_working_factory',
    });
  });
});

describe('CC-0180: снятие из ленты и возврат из запаса', () => {
  const FREE = '2026-10-13';

  it('снять ролик из Studio: строка STUDIO, журнал от дня к null, ролик — в запасе и в `withdrawn`', async () => {
    publish.feedPolicy();
    const plan = await planMove(REEL, { moves: [], unplace: [], withdraw: [PLACED] });
    expect(plan).toMatchObject({ ok: true, withdrawn: 1, moved: 0, unplaced: 0 });
    expect(plan.items[0]).toMatchObject({ op: 'withdraw', slug: PLACED, reserve: false });
    expect(plan.items[0]!.warnings[0]).toMatch(/^STUDIO .*taken off its schedule/);
    const r = await confirmMove(REEL, plan.confirm!, plan.base_sha256);
    expect(r).toMatchObject({ written: true, withdrawn: 1 });
    expect(r.items[0]!.journal).toMatchObject({ to_at: null });
    expect(r.items[0]!.journal!.from_at).toBeTruthy();
    const q = await getQueue(REEL, 14);
    expect(q.occupants.map((o) => o.slug)).not.toContain(PLACED);
    expect(q.withdrawn?.map((w) => w.slug)).toContain(PLACED);
    const stash = await getStash(REEL);
    expect(stash.videos.find((v) => v.slug === PLACED)).toMatchObject({
      reserve: true,
      bucket: '_reserve',
    });
  });

  it('снятый ролик в копилке — на батче, который отдаёт список роликов (за ним идёт оценка строки)', async () => {
    publish.feedPolicy();
    const plan = await planMove(REEL, { moves: [], unplace: [], withdraw: [PLACED] });
    await confirmMove(REEL, plan.confirm!, plan.base_sha256);
    const row = (await getStash(REEL)).videos.find((v) => v.slug === PLACED)!;
    await expect(getVideos(stashBatch(row)!)).resolves.toBeTruthy();
  });

  it('день снятого можно занять в этом же плане', async () => {
    const plan = await planMove(REEL, {
      moves: [{ slug: READY, day: '2026-10-12' }],
      unplace: [],
      withdraw: [PLACED],
    });
    expect(plan.ok).toBe(true);
    expect(plan.confirm).toBeTruthy();
    expect(plan.items.map((i) => i.op)).toEqual(['withdraw', 'move']);
  });

  it('отказы снятия: `not_in_studio`, `in_reserve`; план без токена, `why` и `refusals` с отказом', async () => {
    publish.feedPolicy();
    const notIn = await planMove(REEL, { moves: [], unplace: [], withdraw: [NOT_READY] });
    expect(notIn).toMatchObject({ ok: false, confirm: null });
    expect(notIn.refusals[0]).toMatchObject({ code: 'not_in_studio', slug: NOT_READY });
    expect(notIn.why).toBe(notIn.refusals[0]!.message);
    const twice = await planMove(REEL, { moves: [], unplace: [], withdraw: [STASH_RESERVE] });
    expect(twice.items[0]!.refusals[0]!.code).toBe('in_reserve');
  });

  it('возврат из запаса: `reserve`, без дня откуда, журнал от null, строка без новой загрузки', async () => {
    publish.feedPolicy();
    const plan = await planMove(REEL, {
      moves: [{ slug: STASH_RESERVE, day: FREE }],
      unplace: [],
    });
    expect(plan.ok).toBe(true);
    expect(plan.items[0]).toMatchObject({
      op: 'move',
      reserve: true,
      from_day: null,
      video_id: STASH_RESERVE_ID,
    });
    expect(plan.items[0]!.warnings.join()).toMatch(/^STUDIO .*comes back from the копилка/);
    const r = await confirmMove(REEL, plan.confirm!, plan.base_sha256);
    expect(r.items[0]!.journal).toMatchObject({ from_at: null });
    const q = await getQueue(REEL, 14);
    expect(q.withdrawn).toEqual([]);
    expect(q.slots.find((s) => s.day === FREE)?.taken_by).toBe(STASH_RESERVE);
    expect((await getStash(REEL)).videos.map((v) => v.slug)).not.toContain(STASH_RESERVE);
  });

  it('день за горизонтом: строка HORIZON, но не отказ', async () => {
    publish.feedPolicy();
    const plan = await planMove(REEL, {
      moves: [{ slug: NOT_READY, day: '2026-10-20' }],
      unplace: [],
    });
    expect(plan.ok).toBe(true);
    expect(plan.items[0]!.warnings[0]).toMatch(/^HORIZON /);
  });
});
