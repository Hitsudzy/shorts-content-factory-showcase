// Подставная оценка роликов (CC-0125): ролик на каждый тир, полный журнал с прогнозом и потолком,
// отказанный — из 05 с жёсткой находкой, без оценки — 404 `no_score`; слова и ступени тиров.
import { BatchError } from '@/api/batchProblem';
import { getVideoScore, scoreLabel, tierLevel, tierOf } from '@/api/score';
import { getVideos } from '@/api/videos';
import { groupFindings, momentHref, price, pricesText, whereText } from '@/pages/videos/scoreWords';

import { PAST } from './batches';
import { SCORE_FULL, SCORE_HARD, SCORE_MODEL, SCORE_MOMENT_T } from './score';
import { OLDER, SCIENCE } from './videos';

/** Обязательные поля находки, что словам не важны. */
const F = { hook: false, capped: false };

describe('оценка ролика словами', () => {
  it('ступень тира — по месту в модели, ниже — F, неизвестный — null', () => {
    const t = SCORE_MODEL.tiers;
    expect(t.map((x) => tierLevel(x.name, t))).toEqual([1, 2, 3, 4, 5]);
    expect(tierLevel('F', t)).toBe('f');
    expect(tierLevel('Q', t)).toBeNull();
    expect(tierLevel(null, t)).toBeNull();
    // Модель из трёх тиров: нижний — тоже пятая ступень, а не третья.
    const three = [
      { name: 'A', floor: 80 },
      { name: 'B', floor: 60 },
      { name: 'C', floor: 40 },
    ];
    expect(three.map((x) => tierLevel(x.name, three))).toEqual([1, 3, 5]);
    expect(tierOf(86, t)).toBe('A');
    expect(tierOf(12, t)).toBe('F');
    expect(scoreLabel({ tier: 'A', score: 86 })).toBe('A · 86');
    expect(scoreLabel({ tier: 'B', score: 70.5 })).toBe('B · 70,5');
  });

  it('где, цена, статус цен, «к моменту»', () => {
    expect(price(-6)).toBe('−6');
    expect(pricesText('signed')).toMatch(/подписаны/);
    expect(pricesText('draft')).toMatch(/черновик/);
    expect(pricesText(null)).toBeNull();
    expect(
      whereText({
        ...F,
        hard: false,
        forecast: false,
        t: 12.4,
        where: { blocks: [3, 4] },
        shot: '/pool/clips/a04.mp4',
      }),
    ).toBe('блоки 3, 4 · на 0:12 · кадр «a04»');
    expect(momentHref('/videos?batch=a%2Fb&v=s', 12.4)).toBe('/videos?batch=a%2Fb&v=s&t=12.4');
    const g = groupFindings([
      { ...F, hard: false, forecast: false, price: -3 },
      { ...F, hard: true, forecast: false },
      { ...F, hard: false, forecast: true },
      { ...F, hard: false, forecast: false, price: -10 },
    ]);
    expect(g.hard).toHaveLength(1);
    expect(g.forecast).toHaveLength(1);
    expect(g.penalties.map((f) => f.price)).toEqual([-10, -3]);
  });
});

describe('подставная оценка', () => {
  it('у списка батча — модель счёта, у роликов — тир и баллы', async () => {
    const past = await getVideos(PAST);
    expect(past.score_model.tiers.map((t) => t.name)).toEqual(['S', 'A', 'B', 'C', 'D']);
    const tiers = new Set<string>();
    for (const b of [PAST, OLDER, SCIENCE])
      for (const v of (await getVideos(b)).videos) if (v.score?.tier) tiers.add(v.score.tier);
    expect([...tiers].sort()).toEqual(['A', 'B', 'C', 'D', 'F', 'S']);
    const adenot = (await getVideos(SCIENCE)).videos.find((v) => v.slug === SCORE_HARD)!;
    expect(adenot.score).toMatchObject({ tier: 'F', score: 24, passed: false, source: '05' });
  });

  it('полный журнал: пять стадий, находка со временем и потолком, прогноз', async () => {
    const s = await getVideoScore(PAST, SCORE_FULL);
    expect(s.stages.map((x) => x.stage)).toEqual(['6b', 'plan', 'render', 'qc', 'judge']);
    expect(s.stages.at(-1)!.score_after).toBe(s.score);
    expect(s.findings.some((f) => f.t === SCORE_MOMENT_T && f.capped)).toBe(true);
    expect(s.findings.filter((f) => f.forecast)).toHaveLength(1);
    expect(s.prices_status).toBe('signed');
  });

  it('отказанный — из 05, жёсткая находка; без оценки — 404 no_score', async () => {
    const s = await getVideoScore(SCIENCE, SCORE_HARD);
    expect(s.source).toBe('05');
    expect(s.findings.filter((f) => f.hard)).toHaveLength(1);
    expect(s.stopped_at_ru).toBeTruthy();
    const err = await getVideoScore(SCIENCE, 'jwst-little-red-dots').catch((e: unknown) => e);
    expect(err).toBeInstanceOf(BatchError);
    expect((err as BatchError).problem?.code).toBe('no_score');
  });
});
