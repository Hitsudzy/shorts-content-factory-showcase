// Подставные карточки без оператора (src/mocks/cards.ts, CC-0127): состояние у каждой карточки
// (сведения, копилка, лента, ролики), «Собрать заново» — план (решение пропадёт) → «да» → два
// опроса «собирается» → итог; «Принять своим решением» — только свои утверждения ролика,
// утверждение названия — `note_claim_failed`; размещение копилки — по `placeable`, сборка —
// отказ `card_building`; приёмка запускает сборку (`queued.card_build`).
import { BatchError, problemCode } from '@/api/batchProblem';
import snapshot from '@/api/openapi.snapshot.json';
import {
  CARD_PROBLEM_TEXT,
  cardBuild,
  cardRuling,
  getCardBuildResult,
  getCardInfo,
  planCardBuild,
  planCardRuling,
} from '@/api/cards';
import { getStash, planStashPlace } from '@/api/stash';
import { getVideos, postAcceptance } from '@/api/videos';

import { PAST } from './batches';
import {
  AUTO_RUN,
  CARD_BUILDING,
  CARD_OWN_FAIL,
  CARD_READY,
  CARD_RULED,
  CARD_TITLE_FAIL,
  RULED_WORDS,
} from './cards';
import { publish } from './handlers';
import { REEL } from './publish';
import { SCIENCE } from './videos';

const refused = async (p: Promise<unknown>) => {
  const e = await p.then(
    () => null,
    (x: unknown) => x,
  );
  expect(e).toBeInstanceOf(BatchError);
  return problemCode(e);
};

describe('подставные карточки', () => {
  it('состояния: готова, решением, собирается, не готова; в копилке ruled — placeable, но не ready', async () => {
    expect((await getCardInfo(REEL, CARD_READY, null)).state).toBe('ready');
    const ruled = await getCardInfo(REEL, CARD_RULED, null);
    expect(ruled).toMatchObject({ state: 'ruled', placeable: true });
    expect(ruled.ruling?.words).toBe(RULED_WORDS);
    expect((await getCardInfo(REEL, CARD_BUILDING, null)).build?.run_id).toBe(
      AUTO_RUN(CARD_BUILDING),
    );
    expect(await getCardInfo(REEL, CARD_OWN_FAIL, null)).toMatchObject({
      state: 'not_ready',
      placeable: false,
      reasons: ['claims_failed'],
    });
    const s = await getStash(REEL);
    const byslug = new Map(s.videos.map((v) => [v.slug, v.card]));
    expect(byslug.get(CARD_RULED)).toMatchObject({ state: 'ruled', placeable: true, ready: false });
    expect(byslug.get(CARD_BUILDING)).toMatchObject({ state: 'building', placeable: false });
    expect(await refused(getCardInfo(REEL, 'nobody', null))).toBe('unknown_video');
  });

  it('у роликов батча и в ленте — тот же блок состояния', async () => {
    const past = await getVideos(PAST);
    const vanguards = past.videos.find((v) => v.slug === CARD_TITLE_FAIL)!;
    expect(vanguards.card.card?.state).toBe('not_ready');
    expect(past.videos.find((v) => v.slug === 'rink-rivals')!.card.card?.state).toBe('ready');
  });

  it('«Собрать заново»: план говорит, что решение пропадёт → «да» → два опроса «собирается» → готова', async () => {
    const plan = await planCardBuild(REEL, CARD_RULED, { batch_id: null });
    expect(plan.ok).toBe(true);
    expect(plan.replaces).toMatch(/решение пропадёт/);
    const started = await cardBuild(REEL, CARD_RULED, plan.confirm!);
    expect(started).toMatchObject({ launched: true, poll_s: 1 });
    expect((await getCardInfo(REEL, CARD_RULED, null)).state).toBe('building');
    const r1 = await getCardBuildResult(REEL, started.run_id!);
    const r2 = await getCardBuildResult(REEL, started.run_id!);
    expect([r1.done, r2.done]).toEqual([false, false]);
    const r3 = await getCardBuildResult(REEL, started.run_id!);
    expect(r3).toMatchObject({ done: true, code: 'ready' });
    expect(r3.text_ru).toMatch(/готова/);
    expect((await getCardInfo(REEL, CARD_RULED, null)).state).toBe('ready');
    // Пока собирается — второй сборки план не даёт.
    const busy = await planCardBuild(REEL, CARD_BUILDING, { batch_id: null });
    expect(busy.ok).toBe(false);
    expect(busy.refusals[0]!.code).toBe('running');
  });

  it('«Принять своим решением»: свои утверждения → план с failing и scope → «да» → ruled', async () => {
    expect(await refused(planCardRuling(REEL, CARD_OWN_FAIL, { batch_id: null, words: ' ' }))).toBe(
      'bad_words',
    );
    const plan = await planCardRuling(REEL, CARD_OWN_FAIL, {
      batch_id: null,
      words: 'Цифра из Variety, проверил сам',
    });
    expect(plan.ok).toBe(true);
    expect(plan.failing.map((f) => f.where)).toEqual(['claims/commentary', 'claims/on_screen']);
    expect(plan.scope).toMatch(/только слова самого ролика/);
    const done = await cardRuling(REEL, CARD_OWN_FAIL, plan.confirm!);
    expect(done).toMatchObject({ written: true, commit: expect.any(String) });
    expect((await getCardInfo(REEL, CARD_OWN_FAIL, null)).state).toBe('ruled');
    // В копилке теперь его можно разложить.
    const s = await getStash(REEL);
    expect(s.videos.find((v) => v.slug === CARD_OWN_FAIL)!.card.placeable).toBe(true);
  });

  it('утверждение названия не прошло — note_claim_failed; commit_refused — 409', async () => {
    const plan = await planCardRuling(REEL, CARD_TITLE_FAIL, {
      batch_id: '2026-10-09T0215Z',
      words: 'беру',
    });
    expect(plan.ok).toBe(false);
    expect(plan.refusals[0]!.code).toBe('note_claim_failed');
    expect(plan.confirm).toBeNull();
    const ok = await planCardRuling(REEL, CARD_OWN_FAIL, { batch_id: null, words: 'беру' });
    publish.cards.state.next = 'commit_refused';
    expect(await refused(cardRuling(REEL, CARD_OWN_FAIL, ok.confirm!))).toBe('commit_refused');
  });

  it('копилка: собирающаяся карточка — отказ card_building, решением — раскладывается', async () => {
    const plan = await planStashPlace(REEL, [CARD_BUILDING, CARD_RULED]);
    const items = new Map(plan.items.map((i) => [i.slug, i]));
    expect(items.get(CARD_BUILDING)!.refusals[0]!.code).toBe('card_building');
    expect(items.get(CARD_RULED)!.ok).toBe(true);
  });

  it('приёмка запускает сборку карточки: queued.card_build, опрос — тот же', async () => {
    const r = await postAcceptance(SCIENCE, 'mars-sample-return', {
      verdict: 'yes',
      words: 'mars-sample-return — да',
    });
    expect(r.queued?.card_build).toMatchObject({ launched: true });
    const id = r.queued!.card_build!.run_id!;
    const runs = [];
    for (let i = 0; i < 3; i++) runs.push(await getCardBuildResult('example-science', id));
    expect(runs.map((x) => x.done)).toEqual([false, false, true]);
  });

  it('у каждого кода отказа карточек из контракта — слова', () => {
    const schemas = snapshot.components.schemas as unknown as Record<
      string,
      { properties: { code: { enum: string[] } } }
    >;
    for (const c of schemas.CardCenterProblem!.properties.code.enum)
      expect(CARD_PROBLEM_TEXT[c], c).toBeTruthy();
  });
});
