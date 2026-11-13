import { describe, expect, it } from 'vitest';

import type { components } from '@/api/schema.gen';

import { createBatchesBackend, PAST, routeBatches, RUNNING, STOPPED } from './batches';

type S = components['schemas'];

const get = (path: string) => {
  const b = createBatchesBackend();
  return { b, reply: routeBatches(b, 'GET', new URL(`http://x${path}`)) };
};

describe('подставные темы батча', () => {
  it('идущий батч: темы до проверки сценариев, отсеянные, расход поиска', () => {
    const { reply } = get(`/api/batches/${RUNNING}/topics`);
    expect(reply?.status).toBe(200);
    const t = reply!.body as S['BatchTopics'];
    expect(t.going).toBe(true);
    expect(t.trend_hunter_done).toBe(true);
    expect(t.topics).toHaveLength(3);
    expect(t.skipped).toHaveLength(3);
    expect(t.topics[0]!.scripts![0]!.compliance?.passes).toBe(true);
    expect(t.topics[0]!.scripts![0]!.video).toBeNull();
    expect(t.topics[2]!.state.phase).toBe('reserve');
    expect(t.search_quota?.spent_searches).toBe(9);
    expect(t.files.find((f) => f.stage === 'video-editor')?.present).toBe(false);
  });

  it('уровни: только 01, 01+02, всё; закрытый батч — «встала»', () => {
    const b = createBatchesBackend();
    const topics = (batch: string) =>
      routeBatches(b, 'GET', new URL(`http://x/api/batches/${batch}/topics`))!
        .body as S['BatchTopics'];
    b.setTopics(RUNNING, '01');
    expect(topics(RUNNING).topics[0]!.compliance).toBeNull();
    expect(topics(RUNNING).topics[0]!.state.line).toBe('в работе: проверка темы');
    b.setTopics(RUNNING, '02');
    expect(topics(RUNNING).topics[0]!.compliance?.place).toBe('batch');
    expect(topics(RUNNING).topics[0]!.footage.indexer).toBeNull();
    expect(topics(RUNNING).topics[0]!.state.line).toBe('в работе: футаж');
    const past = topics(PAST);
    expect(past.going).toBe(false);
    expect(past.topics.map((x) => x.state.phase)).toEqual(['done', 'dropped', 'reserve']);
    b.setTopics(PAST, '03');
    expect(topics(PAST).topics[0]!.state.phase).toBe('stalled');
    expect(topics(STOPPED).trend_hunter_done).toBe(false);
    const empty = topics('example-tech/2026-10-07T0200Z');
    expect(empty.topics).toEqual([]);
    expect(empty.skipped).toHaveLength(6);
  });

  it('идущий батч встаёт на стадию своих тем: лента и строки тем говорят одно', () => {
    const b = createBatchesBackend();
    b.setTopics(RUNNING, '02');
    const g = (
      routeBatches(b, 'GET', new URL('http://x/api/batches'))!.body as S['BatchesGoing']
    ).batches.find((x) => x.batch === RUNNING)!;
    expect(g.stage).toBe('footage-indexer');
    expect(g.stages?.find((s) => s.id === 'footage-indexer')?.status).toBe('running');
    expect(g.stages?.find((s) => s.id === 'compliance-shortlist')?.status).toBe('done');
    expect(g.next).toBe('content-researcher');
  });

  it('битый файл этапа — stage_broken', () => {
    const b = createBatchesBackend();
    b.setTopics(RUNNING, 'broken');
    const r = routeBatches(b, 'GET', new URL(`http://x/api/batches/${RUNNING}/topics`));
    expect(r?.status).toBe(409);
    expect((r!.body as S['BatchProblem']).code).toBe('stage_broken');
  });

  it('одна тема: сцены и факт; отсеянная — с причиной; нет такой — unknown_topic', () => {
    const one = get(`/api/batches/${RUNNING}/topics/vanguards-doomsday`).reply!;
    expect(one.status).toBe(200);
    const t = one.body as S['BatchTopic'];
    expect(t.scenes).toHaveLength(4);
    expect(t.fact.chosen[0]?.text).toContain('202 млн');
    const sk = get(`/api/batches/${RUNNING}/topics/the-running-man`).reply!;
    expect((sk.body as S['BatchTopic']).skipped?.reason_code).toBe('no_fact');
    const none = get(`/api/batches/${RUNNING}/topics/nope`).reply!;
    expect(none.status).toBe(404);
    expect((none.body as S['BatchProblem']).code).toBe('unknown_topic');
  });
});
