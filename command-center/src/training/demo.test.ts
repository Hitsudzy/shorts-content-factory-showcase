// Обработчик демо-сервера тренировки — тот же, что в браузере крутит service worker; здесь его
// подставляет MSW для Node. Весь `/api/` отвечает он сам: неизвестное — 501, а не сеть.
import { problemCode } from '@/api/batchProblem';
import { getHealth } from '@/api/client';
import { getPause } from '@/api/publish';
import { getTopic, getTopics } from '@/api/batchTopics';
import { getStranded } from '@/api/batches';
import { planResume } from '@/api/batchActions';
import { pauseSet, planPauseSet } from '@/api/publishWrites';
import { PAST, RUNNING, STRANDED_FAILED, STRANDED_STOPPED } from '@/mocks/batches';
import { server } from '@/mocks/server';
import { REEL } from '@/mocks/publish';

import { checklist, demoHandler, demoStore } from './demo';

const REASON = 'тренировка: пробую паузу';

beforeEach(() => {
  server.use(demoHandler);
  demoStore.reset();
});

const code = (p: Promise<unknown>) =>
  p.then(
    () => null,
    (e: unknown) => problemCode(e),
  );

describe('демо-сервер тренировки', () => {
  it('темы батчей на разных этапах (CC-0092): идущий, прошлый, битый файл этапа', async () => {
    const going = await getTopics(RUNNING);
    expect(going.topics.map((t) => t.state.line)).toContain('в резерве');
    expect(going.skipped).toHaveLength(3);
    expect((await getTopics(PAST)).topics[0]!.state.phase).toBe('done');
    expect((await getTopic(RUNNING, 'delver')).scenes.length).toBeGreaterThan(0);
    expect(await code(getTopics('example-film/2026-10-06T0210Z'))).toBe('stage_broken');
  });

  it('упавшие батчи (CC-0089): видны, один можно продолжить, другому фабрика отказывает', async () => {
    const s = await getStranded();
    expect(s.batches.map((b) => [b.dir, b.holds_day])).toEqual([
      [`pipeline/${STRANDED_FAILED}`, true],
      [`pipeline/${STRANDED_STOPPED}`, false],
    ]);
    expect((await planResume(STRANDED_FAILED)).ok).toBe(true);
    expect((await planResume(STRANDED_STOPPED)).ok).toBe(false);
  });

  it('читает демо-фабрику; записи пишут в неё; задание отмечается само', async () => {
    expect((await getHealth()).writes).toBe(true);
    const plan = await planPauseSet(REEL, { reason: REASON });
    expect(checklist.get()).toEqual([]);
    await pauseSet(REEL, plan.confirm!);
    expect((await getPause(REEL)).state).toBe('paused');
    expect(checklist.get()).toEqual(['pause', 'confirm']);
  });

  it('«промотать время»: следующее «да» — «план устарел», потом всё как обычно', async () => {
    demoStore.expireNext();
    expect(demoStore.get().levers.expireNext).toBe(true);
    const plan = await planPauseSet(REEL, { reason: REASON });
    expect(await code(pauseSet(REEL, plan.confirm!))).toBe('confirm_expired');
    expect(demoStore.get().levers.expireNext).toBe(false);
    expect(checklist.get()).toEqual(['expired']);
    const again = await planPauseSet(REEL, { reason: REASON });
    await pauseSet(REEL, again.confirm!);
    expect((await getPause(REEL)).state).toBe('paused');
  });

  it('«следующее «да» — отказ»: отказ фабрики, записи нет', async () => {
    demoStore.refuseNext();
    expect(demoStore.get().refuseNext).toBe(true);
    const plan = await planPauseSet(REEL, { reason: REASON });
    expect(await code(pauseSet(REEL, plan.confirm!))).toBe('refused');
    expect(demoStore.get().refuseNext).toBe(false);
    expect((await getPause(REEL)).state).toBe('free');
    expect(checklist.get()).toEqual(['refused']);
  });

  it('оба рычага: «да» опоздало — отказ не потрачен, достаётся следующему «да»', async () => {
    demoStore.expireNext();
    demoStore.refuseNext();
    const plan = await planPauseSet(REEL, { reason: REASON });
    expect(await code(pauseSet(REEL, plan.confirm!))).toBe('confirm_expired');
    expect(demoStore.get().refuseNext).toBe(true);
    const again = await planPauseSet(REEL, { reason: REASON });
    expect(await code(pauseSet(REEL, again.confirm!))).toBe('refused');
    expect(checklist.get()).toEqual(['expired', 'refused']);
  });

  it('неизвестный адрес API — 501 от самого демо-сервера', async () => {
    const r = await fetch(new URL('/api/nothing-here', window.location.href));
    expect(r.status).toBe(501);
    expect(await r.json()).toEqual({ detail: 'В тренировке у демо-фабрики нет такого ответа.' });
  });

  it('«начать заново» — свежая демо-фабрика и пустые отметки', async () => {
    const plan = await planPauseSet(REEL, { reason: REASON });
    await pauseSet(REEL, plan.confirm!);
    const before = demoStore.get().generation;
    demoStore.reset();
    expect(demoStore.get().generation).toBe(before + 1);
    expect((await getPause(REEL)).state).toBe('free');
    expect(checklist.get()).toEqual([]);
  });

  it('загрузка на YouTube в демо доступна сразу: API-загрузка канала включена', () => {
    expect(demoStore.get().world.publish.writes.state.switches[REEL]?.on).toBe(true);
  });
});
