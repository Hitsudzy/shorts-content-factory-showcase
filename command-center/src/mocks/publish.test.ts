// Подставная публикация (src/mocks/publish.ts) держит форму фабрики: лента на N дней,
// один «ближайший свободный», занявшие слот есть в `occupants`, карточки находятся по дню,
// отказы — `{message, code, details}`; записи без сети — src/mocks/publishWrites.test.ts.
import { getHolds, getNote, getPublishOverview, getQueue, getReleasedHolds } from '@/api/publish';
import { BatchError } from '@/api/batchProblem';

import { publish } from './handlers';
import {
  createPublishBackend,
  NOT_READY,
  PLACED,
  READY,
  REEL,
  routePublish,
  SCENE_RELEASED,
  SCENE_REOPENED,
  SCIENCE,
  TECH,
  TECH_QUEUE,
  WAITING,
} from './publish';

describe('подставная публикация', () => {
  it('лента ExampleFilm: 14 дней, один ближайший свободный, занятые — в occupants', () => {
    const b = createPublishBackend();
    const r = b.queue(REEL, 14);
    if (r.status !== 200) throw new Error('queue');
    expect(r.body.slots).toHaveLength(14);
    expect(r.body.slots.filter((s) => s.next_free)).toHaveLength(1);
    const taken = r.body.slots.filter((s) => s.taken_by);
    expect(taken.map((s) => s.taken_by)).toContain(PLACED);
    for (const s of taken)
      expect(r.body.occupants.some((o) => o.slug === s.taken_by && o.day === s.day)).toBe(true);
    expect(r.body.waiting).toEqual([WAITING]);
    expect(r.body.slots[0]!.label).toBe('2026-10-10 01:00 МСК');
    expect(r.body.slots[0]!.taken_by).toBeNull();
    expect(r.body.slots[1]!.label).toBe('2026-10-11 01:00 МСК');
  });

  it('пауза держит ленту пустой, а канал без слота — без ленты', () => {
    const b = createPublishBackend();
    b.channels[TECH]!.pause = { ...b.channels[SCIENCE]!.pause!, channel: TECH };
    const tech = b.queue(TECH);
    const sci = b.queue(SCIENCE);
    if (sci.status !== 200 || tech.status !== 200) throw new Error('queue');
    expect(tech.body.paused).toBeTruthy();
    expect(tech.body.tomorrow?.state).toBe('paused');
    expect(tech.body.slots.some((s) => s.next_free)).toBe(false);
    expect(sci.body.slot).toBeNull();
    expect(sci.body.slots).toEqual([]);
  });

  it('канал из списка каналов, которого нет в очередях (только что создан), — пустая очередь и без паузы', () => {
    const b = createPublishBackend();
    expect(b.queue('example-new')).toMatchObject({ status: 404 });
    b.state.elsewhere = (c) => c === 'example-new';
    const q = b.queue('example-new');
    const p = b.pause('example-new');
    if (q.status !== 200 || p.status !== 200) throw new Error('adopt');
    expect(q.body).toMatchObject({ slot: null, slots: [], occupants: [], paused: null });
    expect(p.body).toMatchObject({ state: 'free', row: null });
    // В строку очередей фабрики (`queue_channels`) он не попадает.
    const o = b.overview();
    if (o.status !== 200) throw new Error('overview');
    expect(o.body.channels.map((c) => c.channel)).not.toContain('example-new');
    expect(b.queue('nope')).toMatchObject({ status: 404 });
  });

  it('ExampleTech как на фабрике 16.10: 01:00 МСК, три дня подряд в YouTube, четвёртый свободен', () => {
    const b = createPublishBackend();
    const r = b.queue(TECH);
    if (r.status !== 200) throw new Error('queue');
    expect(r.body.slot).toMatchObject({ times: ['01:00'], tz: 'Europe/Moscow', per_day: 1 });
    expect(r.body.slots.slice(1, 5).map((s) => s.taken_by)).toEqual([...TECH_QUEUE, null]);
    expect(r.body.slots[4]!.next_free).toBe(true);
    expect(r.body.paused).toBeNull();
  });

  it('CC-0149: строки журнала канала — `studio.rows`; журнала нет — ноль у всех', () => {
    const b = createPublishBackend();
    const rows = (c: string) => {
      const r = b.studio(c);
      if (r.status !== 200) throw new Error('studio');
      return [r.body.journal_exists, r.body.rows];
    };
    // Reel: 6 строк Studio в журнале; Tech: три ролика очереди из журнала; Science: ни одной.
    expect(rows(REEL)).toEqual([true, 6]);
    expect(rows(TECH)).toEqual([true, 3]);
    expect(rows(SCIENCE)).toEqual([true, 0]);
    b.state.journalMissing = true;
    expect(rows(REEL)).toEqual([false, 0]);
  });

  it('карточки: готовая с полями Studio, неготовая — с отказом, чужое имя — 404', () => {
    const b = createPublishBackend();
    const ready = b.note(REEL, READY, null);
    const not = b.note(REEL, NOT_READY, null);
    if (ready.status !== 200 || not.status !== 200) throw new Error('note');
    expect(ready.body.studio?.schedule).toMatchObject({ time: '01:00' });
    expect(ready.body.ask_user).toEqual(['language']);
    expect(not.body.studio).toBeNull();
    expect(not.body.studio_refusal).toContain('не готова');
    expect(b.note(REEL, 'nope', null)).toMatchObject({
      status: 404,
      body: { code: 'unknown_note' },
    });
  });

  it('маршруты: GET и записи; незнакомая запись — нет; неизвестный канал — 404', () => {
    const b = createPublishBackend();
    const at = (p: string) => new URL(`http://x${p}`);
    expect(routePublish(b, 'POST', at(`/api/publish/${REEL}/nope/plan`), {})).toBeNull();
    expect(routePublish(b, 'POST', at(`/api/publish/${REEL}/upload/plan`), {})).toMatchObject({
      status: 404,
      body: { code: 'unknown_note' },
    });
    expect(routePublish(b, 'PUT', at(`/api/publish/${REEL}/pause`))).toBeNull();
    expect(
      routePublish(b, 'POST', at(`/api/publish/${REEL}/pause/set/plan`), { reason: 'причина' }),
    ).toMatchObject({ status: 200, body: { ok: true } });
    expect(routePublish(b, 'GET', at('/api/publish/nope/queue'))).toMatchObject({ status: 404 });
    expect(routePublish(b, 'GET', at(`/api/publish/holds?channel=${REEL}`))).toMatchObject({
      status: 200,
    });
  });

  it('CC-0170: снятые холды — снятие по сцене, снова поставленное, вся тема, пустой список', async () => {
    const t = await getReleasedHolds(TECH);
    expect([t.days, t.limit, t.total, t.released, t.reopened]).toEqual([14, 50, 3, 2, 1]);
    expect(t.holds.map((h) => [h.topic_id, h.release.state])).toEqual([
      [SCENE_REOPENED.topic_id, 'reopened'],
      [SCENE_RELEASED.topic_id, 'released'],
      ['tvtc-2026-10-07-002', 'released'],
    ]);
    const [reopened, scene, whole] = t.holds;
    expect(scene!.release).toMatchObject({
      code: 'flagged_scene_not_in_script',
      flagged_short: ['s2'],
      script_short: ['s1'],
      signature_needed: false,
      line_ru: 'Удержание снято: флаг на s2, в ролике s1, подпись не нужна',
    });
    expect(scene!.signable).toBe(false);
    expect(reopened!.release).toMatchObject({ signature_needed: true, code: null });
    expect(reopened!.release.line_ru).toBe(
      'Удержание снова стоит: флаг на s2, в ролике s2, нужна подпись',
    );
    expect(whole!.sensitivity_scenes).toBe('whole_topic');
    // Снова поставленный — и в открытых GET /holds.
    expect((await getHolds(TECH)).open.map((h) => h.topic_id)).toEqual([SCENE_REOPENED.topic_id]);
    const sc = await getReleasedHolds(SCIENCE);
    expect([sc.total, sc.holds]).toEqual([0, []]);
    // Окно: за 1 день до 10.10 07:00 — ничего из Tech (последнее — 09.10 05:30).
    expect((await getReleasedHolds(TECH, 1)).total).toBe(0);
  });

  it('клиент через MSW: обзор, лента, холды и отказ очереди', async () => {
    const all = await getPublishOverview();
    expect(all.channels.map((c) => c.channel)).toEqual([REEL, SCIENCE, TECH]);
    const q = await getQueue(REEL);
    expect(q.days).toBe(14);
    const h = await getHolds(REEL);
    expect(h.open).toHaveLength(2);
    expect(h.rows).toHaveLength(3);
    const n = await getNote(REEL, PLACED, q.slots[2]!.day);
    expect(n.studio?.notices[0]).toContain('уже загружен');
    publish.state.queueBroken[REEL] = 'publish/uploads.json: not JSON';
    await expect(getQueue(REEL)).rejects.toBeInstanceOf(BatchError);
    expect(publish.state.calls.some((c) => c.includes('days=14'))).toBe(true);
  });
});
