// Подставная копилка (src/mocks/stash.ts) держит форму фабрики: ролики с давностью и «устарел»,
// `not_queued`, план без токена при отказе хоть одного ролика, «да» раскладывает по ближайшим
// свободным слотам ленты и коммитит; `dirty`/`batch_open` — отказ строкой, `commit_refused` —
// разложено без коммита; доложить в копилку — `not_queued` переходит в ролики.
import { BatchError, problemCode } from '@/api/batchProblem';
import { getQueue } from '@/api/publish';
import {
  getStash,
  planStashAuto,
  planStashPlace,
  planStashRepair,
  stashPlace,
  stashRepair,
  STASH_PROBLEM_TEXT,
} from '@/api/stash';
import snapshot from '@/api/openapi.snapshot.json';

import { publish } from './handlers';
import { REEL, SCIENCE, TECH } from './publish';
import {
  NOT_QUEUED,
  STASH_EVERGREEN,
  STASH_FRESH_NEWS,
  STASH_HELD,
  STASH_NO_CARD,
  STASH_NOT_READY,
  STASH_RESERVE,
  STASH_RESERVE_ID,
  STASH_STALE,
} from './stash';

const refused = async (p: Promise<unknown>) => {
  const e = await p.then(
    () => null,
    (x: unknown) => x,
  );
  expect(e).toBeInstanceOf(BatchError);
  return problemCode(e);
};

describe('подставная копилка', () => {
  it('Reel: четыре ролика — под холдом, устаревший, с неготовой и с собирающейся карточкой; один не в копилке', async () => {
    const s = await getStash(REEL);
    expect(s.count).toBe(4);
    expect(s.stale).toBe(1);
    expect(s.staleness.threshold_days).toBe(14);
    const by = Object.fromEntries(s.videos.map((v) => [v.slug, v]));
    expect(by[STASH_HELD]!.held).toBe(true);
    expect(by[STASH_STALE]!.age).toMatchObject({ basis: 'news', stale: true });
    expect(by[STASH_STALE]!.age.days).toBeGreaterThan(14);
    expect(by[STASH_NOT_READY]!.card).toMatchObject({ ready: false });
    expect(by[STASH_NOT_READY]!.age.basis).toBe('accepted');
    expect(s.not_queued.map((v) => v.slug)).toEqual([NOT_QUEUED]);
    expect(s.not_queued[0]).toMatchObject({ in_queue: false, queue_code: 'placed' });
    // Science — пустая копилка.
    expect((await getStash(SCIENCE)).count).toBe(0);
    expect(await refused(getStash('nope'))).toBe('unknown_channel');
  });

  it('план с отказом по ролику — без токена; без отказа — токен, «да» раскладывает и коммитит', async () => {
    const bad = await planStashPlace(REEL, [STASH_STALE, STASH_NOT_READY]);
    expect(bad.ok).toBe(false);
    expect(bad.confirm).toBeNull();
    expect(bad.items[0]).toMatchObject({ ok: true, stale: true });
    expect(bad.items[1]!.refusals.map((r) => r.code)).toEqual(['card_not_ready']);
    expect(bad.lines[0]).toMatch(/устарел: \d+ дн\./);

    const plan = await planStashPlace(REEL, [STASH_STALE]);
    expect(plan.ok).toBe(true);
    expect(plan.confirm).toBeTruthy();
    const day = plan.items[0]!.day!;
    const r = await stashPlace(REEL, plan.confirm!);
    expect(r.placed).toBe(1);
    expect(r.commit).toBeTruthy();
    expect(r.committed).toContain(`publish/${REEL}/${day}/${STASH_STALE}.md`);
    expect((await getStash(REEL)).count).toBe(3);
    const q = await getQueue(REEL);
    expect(q.slots.find((x) => x.day === day)?.taken_by).toBe(STASH_STALE);
    // Токен одноразовый.
    expect(await refused(stashPlace(REEL, plan.confirm!))).toBe('confirm_unknown');
  });

  it('dirty и batch_open — отказ строкой в плане; commit_refused — 409 после размещения', async () => {
    publish.stash.state.next = 'dirty';
    const dirty = await planStashPlace(REEL, [STASH_STALE]);
    expect(dirty.ok).toBe(false);
    expect(dirty.refusals.map((x) => x.code)).toEqual(['dirty']);
    expect(dirty.why).toBeTruthy();

    const plan = await planStashPlace(REEL, [STASH_STALE]);
    publish.stash.state.next = 'commit_refused';
    expect(await refused(stashPlace(REEL, plan.confirm!))).toBe('commit_refused');
    expect((await getStash(REEL)).count).toBe(3);
    expect(await refused(planStashPlace(REEL, []))).toBe('empty_order');
    expect(await refused(planStashPlace(SCIENCE, [STASH_STALE]))).toBe('no_queue');
    publish.channels[TECH]!.pause = { ...publish.channels[SCIENCE]!.pause!, channel: TECH };
    expect(await refused(planStashPlace(TECH, [STASH_STALE]))).toBe('paused');
  });

  it('доложить в копилку: not_queued становится роликом копилки', async () => {
    const plan = await planStashRepair(REEL, null);
    expect(plan.ok).toBe(true);
    expect(plan.items[0]).toMatchObject({ slug: NOT_QUEUED, code: 'placed' });
    const r = await stashRepair(REEL, plan.confirm!);
    expect(r.written).toBe(true);
    const s = await getStash(REEL);
    expect(s.not_queued).toEqual([]);
    expect(s.videos.map((v) => v.slug)).toContain(NOT_QUEUED);
  });

  it('у каждого кода отказа копилки из контракта — слова', () => {
    const schemas = snapshot.components.schemas as unknown as Record<
      string,
      { properties: { code: { enum: string[] } } }
    >;
    for (const c of schemas.StashProblem!.properties.code.enum)
      expect(STASH_PROBLEM_TEXT[c], c).toBeTruthy();
  });
});

describe('CC-0180: политика ленты в копилке', () => {
  it('без политики — ответ прежней фабрики: всё бессрочное, запаса и горизонта нет', async () => {
    const s = await getStash(REEL);
    expect(s).toMatchObject({ news: 0, reserve: 0, horizon: null });
    expect(new Set(s.videos.map((v) => v.feed_kind))).toEqual(new Set(['evergreen']));
    expect(s.videos.every((v) => v.reserve === false && v.bucket === '_queue')).toBe(true);
  });

  it('новости, запас, горизонт; авто-раскладка: свежие новости первыми, устаревшая ждёт', async () => {
    publish.feedPolicy({ noCard: true });
    const s = await getStash(REEL);
    expect(s).toMatchObject({ news: 3, reserve: 1, horizon: { days: 3, last_day: '2026-10-13' } });
    const plan = await planStashAuto(REEL, false);
    expect(plan).toMatchObject({ auto: true, force: false, ok: true });
    expect(plan.order).toEqual([STASH_FRESH_NEWS]);
    const why = Object.fromEntries((plan.skipped ?? []).map((x) => [x.slug, x.reason]));
    expect(why).toMatchObject({
      [STASH_STALE]: 'stale_news',
      [STASH_NO_CARD]: 'no_card',
      [STASH_EVERGREEN]: 'beyond_horizon',
    });
    const r = await stashPlace(REEL, plan.confirm!);
    expect(r).toMatchObject({ auto: true, placed: 1 });
    expect(r.skipped?.length).toBe(plan.skipped?.length);
  });

  it('`force`: устаревшая новость идёт в план со строкой STALE', async () => {
    publish.feedPolicy({ days: 5 });
    const plan = await planStashAuto(REEL, true);
    expect(plan.force).toBe(true);
    expect(plan.order[0]).toBe(STASH_STALE);
    const stale = plan.items.find((i) => i.slug === STASH_STALE)!;
    expect(stale.warnings[0]).toMatch(/^STALE /);
    expect(stale).toMatchObject({ feed_kind: 'news' });
  });

  it('ролик запаса в плане: `reserve`, строка STUDIO; разложен — снова в ленте без новой загрузки', async () => {
    publish.feedPolicy();
    const plan = await planStashPlace(REEL, [`2026-09-24T0200Z/${STASH_RESERVE}`]);
    expect(plan.ok).toBe(true);
    expect(plan.items[0]).toMatchObject({ reserve: true, video_id: STASH_RESERVE_ID });
    expect(plan.items[0]!.warnings[0]).toMatch(/^STUDIO .*on its slot/);
    await stashPlace(REEL, plan.confirm!);
    const q = await getQueue(REEL, 14);
    expect(q.withdrawn).toEqual([]);
    expect(q.occupants.find((o) => o.slug === STASH_RESERVE)?.sources.join()).toContain(
      `uploads.json:${STASH_RESERVE_ID}`,
    );
  });

  it('нечего ставить: `ok:false`, код `empty_order`, токена нет', async () => {
    publish.fillReelDays();
    publish.feedPolicy({ days: 0 });
    const plan = await planStashAuto(REEL, false);
    expect(plan).toMatchObject({ ok: false, confirm: null });
    expect(plan.refusals[0]!.code).toBe('empty_order');
  });
});
