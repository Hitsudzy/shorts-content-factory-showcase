import {
  FAILED_AT_START_STAGES,
  JUDGE_ROUND,
  JUDGE_ROUND_DONE_STAGES,
  JUDGE_ROUND_GOING_STAGES,
  JUDGE_ROUND_SKIPPED_STAGES,
} from '@/mocks/batches';

import {
  batchesInText,
  batchStatus,
  clockSpan,
  etaText,
  frameSpent,
  framesOf,
  isSpare,
  isConditional,
  kindOf,
  launchedBy,
  markUnreached,
  outcomeText,
  sizeText,
  spanText,
  stageTitle,
} from './going';
import { isJudgeRound, isKnownStage, repeatOf, stageName } from './stages';

/** План прогона живой фабрики (example-science/2026-10-12T2001Z), в порядке запуска. */
const ORDER = [
  'studio-read-due',
  'rights-check',
  'batch-start',
  'pool-maintenance',
  'trend-hunter',
  'compliance-shortlist',
  'footage-indexer',
  'content-researcher',
  'footage-indexer-reserve',
  'content-researcher-reserve',
  'thin-pool-supplement',
  'plan-check-after-supplement',
  'footage-indexer-reserve-late',
  'content-researcher-reserve-late',
  'thin-pool-supplement-late',
  'plan-check-after-supplement-late',
  'compliance-scripts',
  'video-editor',
  'frame-judge',
  'batch-done',
  'monitors',
  'triage',
  'rotation-backfill',
  'footage-wanted',
  'commit-records',
];

/** До `cur` — готово (условные — `skipped`, если `ranExtra` их не называет), дальше — ждёт. */
const upTo = (cur: string, status = 'running', ranExtra: string[] = []) =>
  ORDER.map((id, i) => {
    const c = ORDER.indexOf(cur);
    const before = isConditional(id) && !ranExtra.includes(id) ? 'skipped' : 'done';
    return { id, status: i < c ? before : i === c ? status : 'pending' };
  });

const titles = (f: ReturnType<typeof framesOf>) => f.map((x) => `${x.n} ${x.title}`);
const states = (f: ReturnType<typeof framesOf>) => f.map((x) => x.state);

describe('кинолента: кадры в порядке плана прогона (CC-0090)', () => {
  it('стадии ложатся в свои виды кадров; условные — по имени', () => {
    expect(kindOf('trend-hunter')).toBe('trends');
    expect(kindOf('rights-check')).toBe('trends');
    expect(kindOf('footage-indexer')).toBe('footage');
    expect(kindOf('content-researcher')).toBe('research');
    expect(kindOf('compliance-scripts')).toBe('scripts');
    expect(kindOf('video-editor')).toBe('edit');
    expect(kindOf('frame-judge')).toBe('judge');
    expect(kindOf('batch-done')).toBe('accept');
    expect(kindOf('unknown-step', 'edit')).toBe('edit');
    for (const id of [
      'footage-indexer-reserve',
      'content-researcher-reserve',
      'thin-pool-supplement',
      'plan-check-after-supplement',
      'content-researcher-reserve-late',
      'plan-check-after-supplement-late',
    ])
      expect(isConditional(id)).toBe(true);
    expect(isConditional('footage-indexer')).toBe(false);
    expect(stageTitle('content-researcher-reserve')).toBe('Добор');
    expect(stageTitle('footage-indexer')).toBe('Футаж');
  });

  it('порядок кадров — порядок `stages`: футаж раньше исследования, номера подряд', () => {
    const f = framesOf({
      stages: upTo('footage-indexer'),
      stage: 'footage-indexer',
      status: 'running',
    });
    expect(titles(f)).toEqual([
      '1 Тренды',
      '2 Футаж',
      '3 Исследование',
      '4 Добор',
      '5 Проверка сценариев',
      '6 Монтаж',
      '7 Проверка кадров',
      '8 На приёмку',
    ]);
    // Как в живом батче 2001Z: идёт футаж — исследование ждёт после него, без перескока.
    expect(states(f)).toEqual(['done', 'now', 'wait', 'opt', 'wait', 'wait', 'wait', 'wait']);
    expect(f[1]!.stages).toEqual(['footage-indexer']);
    expect(f[3]!.stages).toHaveLength(8);
    expect(f[7]!.stages).toEqual([
      'batch-done',
      'monitors',
      'triage',
      'rotation-backfill',
      'footage-wanted',
      'commit-records',
    ]);
  });

  it('другой порядок в плане — другой порядок кадров (центр не переставляет)', () => {
    const stages = ['batch-start', 'trend-hunter', 'content-researcher', 'footage-indexer'].map(
      (id) => ({ id, status: 'pending' }),
    );
    const f = framesOf({ stages, stage: null, status: 'running' });
    expect(f.slice(0, 3).map((x) => x.kind)).toEqual(['trends', 'research', 'footage']);
  });

  it('добор не понадобился: батч прошёл его, не запустив, — «не понадобился», не «ждёт»', () => {
    const f = framesOf({ stages: upTo('video-editor'), stage: 'video-editor', status: 'running' });
    expect(states(f)).toEqual(['done', 'done', 'done', 'unneeded', 'done', 'now', 'wait', 'wait']);
    // Всё ещё «pending» у условных, но дальше уже идут — тоже «не понадобился».
    const pending = upTo('video-editor').map((s) =>
      isConditional(s.id) ? { ...s, status: 'pending' } : s,
    );
    expect(framesOf({ stages: pending, stage: 'video-editor', status: 'running' })[3]!.state).toBe(
      'unneeded',
    );
  });

  it('добор запускался — «готово»; идёт — текущий кадр', () => {
    const ran = framesOf({
      stages: upTo('video-editor', 'running', [
        'thin-pool-supplement',
        'plan-check-after-supplement',
      ]),
      stage: 'video-editor',
      status: 'running',
    });
    expect(ran[3]!.state).toBe('done');
    const now = framesOf({
      stages: upTo('thin-pool-supplement'),
      stage: 'thin-pool-supplement',
      status: 'running',
    });
    expect(states(now).slice(0, 5)).toEqual(['done', 'done', 'done', 'now', 'wait']);
  });

  it('остановлен и упал — текущий кадр «остановлено» / «ошибка»', () => {
    const s = framesOf({
      stages: upTo('video-editor', 'stopped'),
      stage: 'video-editor',
      status: 'stopped',
    });
    expect(s[5]!.state).toBe('stopped');
    const b = framesOf({
      stages: upTo('frame-judge', 'failed'),
      stage: 'frame-judge',
      status: 'failed',
    });
    expect(b[6]!.state).toBe('bad');
  });

  it('пересборка от монтажа: ранних стадий в плане нет — «не в этом прогоне» на обычных местах', () => {
    const stages = ['batch-start', 'video-editor', 'frame-judge', 'batch-done'].map((id) => ({
      id,
      status: id === 'batch-start' ? 'done' : id === 'video-editor' ? 'running' : 'pending',
    }));
    const f = framesOf({ stages, stage: 'video-editor', status: 'running' });
    expect(f.map((x) => x.kind)).toEqual([
      'trends',
      'footage',
      'research',
      'scripts',
      'edit',
      'judge',
      'accept',
    ]);
    expect(states(f)).toEqual(['done', 'skip', 'skip', 'skip', 'now', 'wait', 'wait']);
  });

  it('батч готов: добор без запуска — «не понадобился», остальное — готово', () => {
    const stages = upTo('commit-records', 'done');
    const f = framesOf({ stages, stage: null, status: 'done' });
    expect(states(f)).toEqual(['done', 'done', 'done', 'unneeded', 'done', 'done', 'done', 'done']);
  });

  it('без run-state (только маркеры): обычный порядок, до текущего — готово, добор — «если нужно»', () => {
    const f = framesOf({ stages: null, stage: 'frame-judge', status: null });
    expect(f.map((x) => x.title)).toEqual([
      'Тренды',
      'Футаж',
      'Исследование',
      'Добор',
      'Проверка сценариев',
      'Монтаж',
      'Проверка кадров',
      'На приёмку',
    ]);
    expect(states(f)).toEqual(['done', 'done', 'done', 'opt', 'done', 'done', 'now', 'wait']);
  });
});

/** План с машинной стадией CF-0707: `frame-judge-empty` перед `frame-judge`. */
const WITH_EMPTY = ORDER.flatMap((id) => (id === 'frame-judge' ? ['frame-judge-empty', id] : [id]));
const plan = (statuses: Record<string, string>, rest = 'done') =>
  WITH_EMPTY.map((id) => ({
    id,
    status: statuses[id] ?? (isConditional(id) ? 'skipped' : rest),
  }));

describe('кинолента: «нечего проверять» и незнакомые стадии (CC-0111)', () => {
  it('`frame-judge-empty` — в кадр «Проверка кадров», не отдельный кадр', () => {
    expect(kindOf('frame-judge-empty')).toBe('judge');
    expect(stageTitle('frame-judge-empty')).toBe('Проверка кадров');
    expect(stageName('frame-judge-empty')).toBe('Проверка кадров: нечего проверять');
    expect(isKnownStage('frame-judge-empty')).toBe(true);
  });

  it('пустой итог готов, судья пропущен — один готовый кадр «нечего проверять», не пропуск', () => {
    const f = framesOf({
      stages: plan({ 'frame-judge-empty': 'done', 'frame-judge': 'skipped' }),
      stage: 'batch-done',
      status: 'done',
    });
    expect(titles(f)).toEqual([
      '1 Тренды',
      '2 Футаж',
      '3 Исследование',
      '4 Добор',
      '5 Проверка сценариев',
      '6 Монтаж',
      '7 Проверка кадров',
      '8 На приёмку',
    ]);
    const judge = f.find((x) => x.kind === 'judge')!;
    expect(judge).toMatchObject({ state: 'done', empty: true });
    expect(judge.stages).toEqual(['frame-judge-empty', 'frame-judge']);
    expect(f.filter((x) => x.kind === 'judge')).toHaveLength(1);
  });

  it('ролики были: пустой итог пропущен, судья отработал — обычный готовый кадр', () => {
    const f = framesOf({
      stages: plan({ 'frame-judge-empty': 'skipped', 'frame-judge': 'done' }),
      stage: 'batch-done',
      status: 'done',
    });
    const judge = f.find((x) => x.kind === 'judge')!;
    expect(judge.state).toBe('done');
    expect(judge.empty).toBeUndefined();
  });

  it('идёт: пустой итог готов, судья ещё ждёт — 1 из 2 шагов, без «нечего проверять»', () => {
    const f = framesOf({
      stages: plan({ 'frame-judge-empty': 'done', 'frame-judge': 'pending' }, 'pending').map(
        (s, i) => (i < WITH_EMPTY.indexOf('frame-judge-empty') ? { ...s, status: 'done' } : s),
      ),
      stage: 'frame-judge',
      status: 'running',
    });
    const judge = f.find((x) => x.kind === 'judge')!;
    expect(judge).toMatchObject({ state: 'now', current: true });
    expect(judge.empty).toBeUndefined();
  });

  it('незнакомая стадия не ломает нумерацию: номера подряд, кадров столько же', () => {
    const base = framesOf({
      stages: upTo('video-editor'),
      stage: 'video-editor',
      status: 'running',
    });
    const odd = upTo('video-editor').flatMap((s) =>
      s.id === 'compliance-scripts'
        ? [s, { id: 'mystery-step-2026', status: 'done' }]
        : s.id === 'studio-read-due'
          ? [{ id: 'zz-unknown', status: 'done' }, s]
          : [s],
    );
    const f = framesOf({ stages: odd, stage: 'video-editor', status: 'running' });
    expect(f.map((x) => x.n)).toEqual(f.map((_, i) => i + 1));
    expect(titles(f)).toEqual(titles(base));
    expect(states(f)).toEqual(states(base));
    // Незнакомая — в кадре соседа слева; первой в плане — в «Трендах».
    expect(f.find((x) => x.stages.includes('mystery-step-2026'))!.kind).toBe('scripts');
    expect(f[0]!.stages[0]).toBe('zz-unknown');
    // Незнакомая стадия, на которой батч сейчас, — тоже не ломает: текущий кадр — по её виду.
    const now = framesOf({ stages: odd, stage: 'never-heard-of', status: 'running' });
    expect(now.map((x) => x.n)).toEqual(now.map((_, i) => i + 1));
  });
});

describe('кинолента: законченное видно сразу (CC-0126)', () => {
  const EXTRA_RAN = ['thin-pool-supplement', 'plan-check-after-supplement'];

  it('запасные шаги: `*-reserve` и `*-late`', () => {
    expect(isSpare('footage-indexer-reserve')).toBe(true);
    expect(isSpare('thin-pool-supplement-late')).toBe(true);
    expect(isSpare('thin-pool-supplement')).toBe(false);
    expect(isSpare('video-editor')).toBe(false);
  });

  it('добор прошёл, запасные не понадобились — «готово» и сколько запасных не понадобилось', () => {
    const f = framesOf({
      stages: upTo('video-editor', 'running', EXTRA_RAN),
      stage: 'video-editor',
      status: 'running',
    });
    expect(f[3]).toMatchObject({ state: 'done', spare: 6 });
    expect(f[3]!.more).toBeUndefined();
    // Как у Reel 1411Z: запасные так и остались pending, а батч ушёл дальше — тоже не понадобились.
    const pending = upTo('video-editor', 'running', EXTRA_RAN).map((s) =>
      isSpare(s.id) ? { ...s, status: 'pending' } : s,
    );
    expect(
      framesOf({ stages: pending, stage: 'video-editor', status: 'running' })[3],
    ).toMatchObject({ state: 'done', spare: 6 });
  });

  it('запасные ещё могут пойти — «готово, возможен добор», не «2 из 4 шагов»', () => {
    const at = ORDER.indexOf('plan-check-after-supplement');
    const stages = ORDER.map((id, i) => ({
      id,
      status: i <= at && (!isConditional(id) || EXTRA_RAN.includes(id)) ? 'done' : 'pending',
    }));
    const f = framesOf({ stages, stage: null, status: 'running' });
    expect(f[3]).toMatchObject({ state: 'done', more: true });
    expect(f[3]!.spare).toBeUndefined();
  });

  it('идёт добор — «вернулся»; батч вернулся в ранний этап — тоже', () => {
    const now = framesOf({
      stages: upTo('thin-pool-supplement'),
      stage: 'thin-pool-supplement',
      status: 'running',
    });
    expect(now[3]).toMatchObject({ state: 'now', returned: true });
    const stages = [
      { id: 'batch-start', status: 'done' },
      { id: 'footage-indexer', status: 'running' },
      { id: 'content-researcher', status: 'done' },
      { id: 'video-editor', status: 'pending' },
    ];
    const back = framesOf({ stages, stage: 'footage-indexer', status: 'running' });
    expect(back[1]).toMatchObject({ kind: 'footage', state: 'now', returned: true });
    expect(back[2]).toMatchObject({ kind: 'research', state: 'done' });
    // Обычный ход — не «вернулся».
    const plain = framesOf({
      stages: upTo('video-editor'),
      stage: 'video-editor',
      status: 'running',
    });
    expect(plain[5]!.returned).toBeUndefined();
  });

  it('длительность кадра — сумма закончившихся пролётов его стадий', () => {
    const f = framesOf({ stages: upTo('video-editor'), stage: 'video-editor', status: 'running' });
    const spans = [
      { stage: 'batch-start', started: null, done: null, open: false, duration_s: 600 },
      { stage: 'trend-hunter', started: null, done: null, open: false, duration_s: 3300 },
      { stage: 'video-editor', started: null, done: null, open: true, duration_s: null },
    ];
    expect(clockSpan(frameSpent(f[0]!, spans))).toBe('1\u00a0ч 05\u00a0мин');
    expect(frameSpent(f[5]!, spans)).toBeNull();
    expect(frameSpent(f[0]!, null)).toBeNull();
    expect(clockSpan(3600)).toBe('1\u00a0ч');
    expect(clockSpan(25 * 60)).toBe('25\u00a0мин');
    // Число и единица не рвутся на строки (CC-0150, ревью экранов); между частями — обычный пробел.
    expect(clockSpan(5400)).toBe('1\u00a0ч 30\u00a0мин');
    expect(spanText(5400)).toBe('1\u00a0ч 30\u00a0мин');
    expect(clockSpan(10)).toBe('меньше минуты');
  });
});

describe('упавший батч: пропущенное после падения — «не дошёл» (CC-0095)', () => {
  it('настоящий example-science/2026-10-12T1908Z: после batch-start — ни одного ✓', () => {
    const f = framesOf({ stages: FAILED_AT_START_STAGES, stage: null, status: 'failed' });
    expect(titles(f)).toEqual([
      '1 Тренды',
      '2 Футаж',
      '3 Исследование',
      '4 Добор',
      '5 Проверка сценариев',
      '6 Монтаж',
      '7 Проверка кадров',
      '8 На приёмку',
    ]);
    expect(states(f)).toEqual([
      'bad',
      'unreached',
      'unreached',
      'unreached',
      'unreached',
      'unreached',
      'unreached',
      'bad',
    ]);
    expect(f.filter((x) => x.state === 'done')).toEqual([]);
    // Стадии «сейчас» нет (`current` null): ни один кадр не текущий.
    expect(f.filter((x) => x.current)).toEqual([]);
  });

  it('skipped до места падения не трогает: условные — «не понадобился», дальше — «не дошёл»', () => {
    const cur = ORDER.indexOf('video-editor');
    const stages = ORDER.map((id, i) => ({
      id,
      status: i < cur ? (isConditional(id) ? 'skipped' : 'done') : i === cur ? 'failed' : 'skipped',
    }));
    const marked = markUnreached(stages);
    expect(marked.find((s) => s.id === 'footage-indexer-reserve')?.status).toBe('skipped');
    expect(marked.find((s) => s.id === 'frame-judge')?.status).toBe('unreached');
    const f = framesOf({ stages, stage: null, status: 'failed' });
    expect(states(f)).toEqual([
      'done',
      'done',
      'done',
      'unneeded',
      'done',
      'bad',
      'unreached',
      'unreached',
    ]);
  });

  it('остановленная стадия — тоже место, дальше которого батч не дошёл', () => {
    const cur = ORDER.indexOf('compliance-scripts');
    const stages = ORDER.map((id, i) => ({
      id,
      status: i < cur ? 'done' : i === cur ? 'stopped' : 'skipped',
    }));
    const f = framesOf({ stages, stage: 'compliance-scripts', status: 'stopped' });
    expect(states(f)).toEqual([
      'done',
      'done',
      'done',
      'done',
      'stopped',
      'unreached',
      'unreached',
      'unreached',
    ]);
  });

  it('кадр: часть стадий готова, остальные не дошли — «часть», без ✓', () => {
    const stages = [
      { id: 'batch-start', status: 'done' },
      { id: 'video-editor', status: 'failed' },
      { id: 'batch-done', status: 'done' },
      { id: 'monitors', status: 'skipped' },
    ];
    const accept = framesOf({ stages, stage: null, status: 'failed' }).find(
      (x) => x.kind === 'accept',
    );
    expect(accept).toMatchObject({ state: 'part', done: 1, total: 2 });
  });

  it('без падения skipped остаётся как было', () => {
    const stages = upTo('commit-records', 'done');
    expect(markUnreached(stages)).toBe(stages);
  });
});

describe('слова батча', () => {
  it('оценка конца: left_s < 0 — «дольше обычного»', () => {
    expect(etaText({ mean_wall_s: 9000, runs: 5, left_s: 3600 })).toMatchObject({
      text: 'осталось ≈ 1\u00a0ч',
      over: false,
    });
    const over = etaText({ mean_wall_s: 6000, runs: 1, left_s: -1200 })!;
    expect(over).toMatchObject({ text: 'дольше обычного на 20\u00a0мин', over: true });
    expect(over.tip).toContain('Оценка по 1 прогону');
    expect(etaText(null)).toBeNull();
  });

  it('кто запустил: таймер, пульт, центр, null — «вручную в чате»', () => {
    expect(launchedBy({ by: 'tick' }).label).toBe('таймер');
    expect(launchedBy({ by: 'user (пульт)' }).label).toBe('пульт');
    expect(launchedBy({ by: 'user (центр)' }).label).toBe('центр');
    expect(launchedBy(null).label).toBe('вручную в чате');
  });

  it('статус, итог, длительность', () => {
    expect(batchStatus('stopped').label).toBe('остановлен');
    expect(batchStatus('running', false).tone).toBe('warn');
    expect(outcomeText('videos', 3).label).toBe('готово: 3 ролика');
    expect(outcomeText(null, null).label).toBe('итог не записан');
    expect(spanText(8619.6)).toBe('2\u00a0ч 24\u00a0мин');
    expect(spanText(20)).toBe('меньше минуты');
  });
});

describe('батч в тексте фабрики — каналом и временем (ревью экранов CC-0123)', () => {
  const name = (id: string) => (id === 'example-film' ? 'ExampleFilm' : id);
  it('«example-film 2026-10-09T2305Z» → «ExampleFilm · батч 10.10, 02:05» (МСК)', () => {
    expect(
      batchesInText('сегодня батч уже был: example-film 2026-10-09T2305Z - 1 батч в сутки', name),
    ).toBe('сегодня батч уже был: ExampleFilm · батч 10.10, 02:05 - 1 батч в сутки');
    expect(batchesInText('батч example-film/2026-10-09T2305Z упал', name)).toBe(
      'батч ExampleFilm · батч 10.10, 02:05 упал',
    );
    expect(batchesInText('без батча', name)).toBe('без батча');
  });
});

describe('размер журнала (CC-0131)', () => {
  it('перед единицей — неразрывный пробел: «262 Б» не рвётся на чипе', () => {
    expect(sizeText(262)).toBe('262\u00a0Б');
    expect(sizeText(12 * 1024)).toBe('12\u00a0КБ');
    expect(sizeText(1.4 * 1024 * 1024)).toBe('1,4\u00a0МБ');
  });
});

describe('кинолента: добор после отказа судьи кадра (CC-0150, фабрика 2.16)', () => {
  const NINE = [
    '1 Тренды',
    '2 Футаж',
    '3 Исследование',
    '4 Добор',
    '5 Проверка сценариев',
    '6 Монтаж',
    '7 Проверка кадров',
    '8 Добор после судьи',
    '9 На приёмку',
  ];

  it('`*-judge` — повтор стадии без суффикса: условный, запасной, кадр «Добор»', () => {
    for (const id of JUDGE_ROUND) {
      expect(isConditional(id)).toBe(true);
      expect(isSpare(id)).toBe(true);
      expect(isJudgeRound(id)).toBe(true);
      expect(kindOf(id)).toBe('extra');
      expect(isKnownStage(id)).toBe(true);
      expect(stageName(id)).toMatch(/ \(повтор после отказа судьи кадра\)$/);
    }
    expect(repeatOf('frame-judge-judge')).toEqual({
      kind: 'judge',
      base: 'frame-judge',
      label: 'повтор после отказа судьи кадра',
    });
    expect(stageName('footage-indexer-reserve-judge')).toBe(
      'Резерв футажа (повтор после отказа судьи кадра)',
    );
    // Сама `frame-judge` кончается на `-judge`, но она не повтор.
    expect(repeatOf('frame-judge')).toBeNull();
    expect(isConditional('frame-judge')).toBe(false);
    expect(isSpare('frame-judge')).toBe(false);
    expect(kindOf('frame-judge')).toBe('judge');
    expect(stageName('frame-judge')).toBe('Проверка кадров');
    // Повтор незнакомой стадии `-judge` не узнаётся; поздний повтор — как раньше, у любой.
    expect(repeatOf('mystery-judge')).toBeNull();
    expect(repeatOf('mystery-late')).toMatchObject({ kind: 'late', base: 'mystery' });
    // Пометки двух повторов различаются.
    expect(stageName('video-editor-late')).toBe('Монтаж (поздний повтор)');
    expect(stageName('video-editor-judge')).toBe('Монтаж (повтор после отказа судьи кадра)');
  });

  it('раунд пропущен: свой кадр «Добор после судьи» между проверкой кадров и приёмкой — «не понадобился»', () => {
    const f = framesOf({
      stages: JUDGE_ROUND_SKIPPED_STAGES,
      stage: 'batch-done',
      status: 'running',
    });
    expect(titles(f)).toEqual(NINE);
    expect(states(f)).toEqual([
      'done',
      'done',
      'done',
      'unneeded',
      'done',
      'done',
      'done',
      'unneeded',
      'now',
    ]);
    expect(f[7]).toMatchObject({ kind: 'extra', judge: true, stages: [...JUDGE_ROUND] });
    expect(f[7]!.tip).toContain('Судья кадра отказал роликам');
    // Обычный «Добор» — без пометки раунда.
    expect(f[3]!.judge).toBeUndefined();
    expect(f[3]!.title).toBe('Добор');
  });

  it('раунд идёт: кадр «Добор после судьи» — текущий, батч вернулся за добором', () => {
    const f = framesOf({
      stages: JUDGE_ROUND_GOING_STAGES,
      stage: 'video-editor-judge',
      status: 'running',
    });
    expect(titles(f)).toEqual(NINE);
    expect(f[7]).toMatchObject({ state: 'now', current: true, returned: true, done: 5 });
    expect(f[6]!.state).toBe('done');
    expect(f[8]!.state).toBe('wait');
  });

  it('раунд прошёл: «готово», добор тонкого пула не понадобился — два запасных шага', () => {
    const f = framesOf({ stages: JUDGE_ROUND_DONE_STAGES, stage: 'batch-done', status: 'running' });
    expect(titles(f)).toEqual(NINE);
    expect(f[7]).toMatchObject({ state: 'done', judge: true, spare: 2 });
    expect(f[8]!.state).toBe('now');
  });

  it('батч ещё на проверке кадров: раунд впереди — «только если нужно»', () => {
    const stages = JUDGE_ROUND_SKIPPED_STAGES.map((s) =>
      s.id === 'frame-judge'
        ? { ...s, status: 'running' }
        : isJudgeRound(s.id) || s.id === 'batch-done'
          ? { ...s, status: 'pending' }
          : s,
    );
    const f = framesOf({ stages, stage: 'frame-judge', status: 'running' });
    expect(f[6]!.state).toBe('now');
    expect(f[7]!.state).toBe('opt');
  });
});
