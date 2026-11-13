import { createMemesBackend, routeMemes } from './memes';

const url = (p: string) => new URL(`http://x${p}`);
const call = (
  b: ReturnType<typeof createMemesBackend>,
  method: string,
  path: string,
  body: unknown = null,
) => routeMemes(b, method, url(path), body)! as { status: number; body: Record<string, unknown> };

const TECH = '/api/memes/example-tech';

describe('подставные задачи банка мемов', () => {
  it('вырезка: план без записи, «да» запускает задачу, опросы — «i из N», итог перечитывается', () => {
    const b = createMemesBackend();
    const plan = call(b, 'POST', `${TECH}/cutout/plan`, { ids: null, force: false });
    expect(plan.status).toBe(200);
    expect(plan.body.ok).toBe(true);
    expect((plan.body.made as { id: string }[]).map((m) => m.id)).toEqual(['distracted-boyfriend']);
    expect(plan.body.unchanged).toEqual(['drake-hotline-bling', 'roll-safe']);
    const started = call(b, 'POST', `${TECH}/cutout`, { confirm: plan.body.confirm });
    expect(started.status).toBe(200);
    const id = started.body.job_id as string;
    expect(started.body.status_url).toBe(`${TECH}/jobs/${id}`);
    // Пока идёт: стол знает задачу, отметки и «применить» закрыты, планы — ok:false.
    expect(b.desk('example-tech').job?.job_id).toBe(id);
    expect(call(b, 'PUT', `${TECH}/marks`, { decisions: {}, base: null }).body.code).toBe(
      'job_active',
    );
    const again = call(b, 'POST', `${TECH}/trim/plan`, {});
    expect(again.body.ok).toBe(false);
    expect((again.body.job as { job_id: string }).job_id).toBe(id);
    const list = call(b, 'GET', `${TECH}/jobs?limit=20`);
    expect((list.body.running as { job_id: string }).job_id).toBe(id);

    const p1 = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    expect(p1.state).toBe('running');
    expect(p1.progress).toMatchObject({ step: 'cutout', i: 1, of: 1 });
    const end = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    expect(end).toMatchObject({ state: 'done', state_word: 'готово', done: true, poll_s: null });
    expect((end.result as { made: { id: string }[] }).made[0]!.id).toBe('distracted-boyfriend');
    expect(b.desk('example-tech').job).toBeNull();
    expect(
      b.desk('example-tech').entries.find((e) => e.id === 'distracted-boyfriend')!.urls.cut,
    ).toMatch(/kind=cut$/);
  });

  it('CC-0161: коммит итога — по умолчанию нет; refused и committed — как пишет стол', () => {
    const run = (commit: 'refused' | 'committed' | null) => {
      const b = createMemesBackend();
      b.jobs.state.commit = commit;
      const plan = call(b, 'POST', `${TECH}/cutout/plan`, {});
      const id = call(b, 'POST', `${TECH}/cutout`, { confirm: plan.body.confirm }).body.job_id;
      let job = call(b, 'GET', `${TECH}/jobs/${id as string}`).body;
      while (!job.done) job = call(b, 'GET', `${TECH}/jobs/${id as string}`).body;
      return job;
    };
    expect(run(null)).toMatchObject({ commit_on_done: null, commit: null });
    expect(run('refused')).toMatchObject({
      commit_on_done: true,
      commit: {
        status: 'refused',
        sha: null,
        detail: expect.stringMatching(/^fatal: .*touched: /),
      },
    });
    const ok = run('committed');
    expect(ok.commit).toMatchObject({ status: 'committed', detail: null });
    expect((ok.commit as { sha: string }).sha).toHaveLength(40);
    expect((ok.commit as { committed: string[] }).committed[0]).toMatch(/index\.json$/);
  });

  it('Vision недоступен: план говорит словами, запуск — cutout_unavailable', () => {
    const b = createMemesBackend();
    b.jobs.state.vision = { available: false, reason: 'нужна macOS 14 или новее' };
    const plan = call(b, 'POST', `${TECH}/cutout/plan`, {});
    expect(plan.body).toMatchObject({ ok: false, available: false, confirm: null });
    expect(plan.body.why).toBe('Вырезка на этой машине недоступна: нужна macOS 14 или новее');
  });

  it('обрезка: trim и under по потолку, отказы — failed и interrupted, задача на другом банке', () => {
    const b = createMemesBackend();
    const plan = call(b, 'POST', `${TECH}/trim/plan`, {});
    expect((plan.body.trim as { id: string }[]).map((r) => r.id)).toEqual(['two-buttons']);
    expect((plan.body.under as { id: string }[]).map((r) => r.id)).toEqual(['grus-plan']);
    b.jobs.state.outcome = 'failed';
    const id = call(b, 'POST', `${TECH}/trim`, { confirm: plan.body.confirm }).body
      .job_id as string;
    call(b, 'GET', `${TECH}/jobs/${id}`);
    const failed = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    expect(failed).toMatchObject({ state: 'failed', done: true });
    expect((failed.error as { text: string }).text).toMatch(/Задача упала/);

    b.jobs.state.outcome = 'interrupted';
    b.jobs.seed('example-tech', 'trim_blank');
    const run = call(b, 'GET', `${TECH}/jobs`).body.running as { job_id: string };
    call(b, 'GET', `${TECH}/jobs/${run.job_id}`);
    expect(call(b, 'GET', `${TECH}/jobs/${run.job_id}`).body.state).toBe('interrupted');

    b.jobs.state.elsewhere = {
      job_id: 'job-x',
      kind: 'cutout',
      kind_word: 'вырезка фона',
      bank: 'memes',
    };
    const busy = call(b, 'POST', `${TECH}/cutout/plan`, {});
    expect(busy.body.ok).toBe(false);
    expect(busy.body.why).toMatch(/одна задача на машину/);
    expect(call(b, 'GET', `${TECH}/jobs/nope`).status).toBe(404);
  });

  it('добавить картинку: отказы до плана, план без записи, задача по шагам, новая запись pending', () => {
    const b = createMemesBackend();
    const body = {
      id: 'success-kid',
      url: 'https://i.imgflip.com/success-kid.jpg',
      source_url: 'https://imgflip.com/memetemplate/success-kid',
      description: 'Собака в горящей комнате',
      tags: 'спокойствие, пожар',
    };
    expect(
      call(b, 'POST', `${TECH}/add-image/plan`, { ...body, url: 'file:///x.jpg' }).body.code,
    ).toBe('bad_url');
    expect(
      call(b, 'POST', `${TECH}/add-image/plan`, { ...body, url: 'https://x.org/a.gif' }).body.code,
    ).toBe('bad_suffix');
    const dup = call(b, 'POST', `${TECH}/add-image/plan`, { ...body, id: 'roll-safe' });
    expect(dup).toMatchObject({ status: 409, body: { code: 'duplicate_id' } });
    const plan = call(b, 'POST', `${TECH}/add-image/plan`, body);
    expect(plan.body).toMatchObject({
      ok: true,
      action: 'meme_add_image',
      file: 'success-kid.jpg',
      tags: ['спокойствие', 'пожар'],
      steps: ['download', 'check', 'index', 'embedding'],
      max_seconds_word: 'до 4 мин',
    });
    expect((plan.body.notes as string[])[0]).toMatch(/^Будет скачана картинка https:/);
    const n = b.desk('example-tech').entries.length;
    const started = call(b, 'POST', `${TECH}/add-image`, { confirm: plan.body.confirm });
    expect(started.body).toMatchObject({ action: 'meme_add_image', kind: 'add_image' });
    const id = started.body.job_id as string;
    const steps = [];
    for (let i = 0; i < 4; i++) {
      const j = call(b, 'GET', `${TECH}/jobs/${id}`).body;
      if (j.done) break;
      steps.push((j.progress as { step: string }).step);
    }
    expect(steps).toEqual(['check', 'index', 'embedding']);
    const end = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    expect(end.state).toBe('done');
    const r = end.result as { entry: { id: string; review: string; urls: { thumb: string } } };
    expect(r.entry).toMatchObject({ id: 'success-kid', review: 'pending' });
    expect(r.entry.urls.thumb).toBe(`${TECH}/success-kid/thumb`);
    expect(b.desk('example-tech').entries.length).toBe(n + 1);
    expect(call(b, 'POST', `${TECH}/add-image/plan`, body).body.code).toBe('duplicate_id');
  });

  it('лист кадров: план, отказы, итог со сменами сцен и картинкой; GIF по отрезку — cuts_inside', () => {
    const b = createMemesBackend();
    const video = 'https://www.youtube.com/watch?v=abc';
    expect(call(b, 'POST', `${TECH}/sheet/plan`, { video, end: 700, every: 2 }).body.code).toBe(
      'too_many_frames',
    );
    expect(call(b, 'POST', `${TECH}/sheet/plan`, { video, out: '../x.jpg' }).body.code).toBe(
      'bad_params',
    );
    const plan = call(b, 'POST', `${TECH}/sheet/plan`, { video, start: 0, end: 40, every: 2 });
    expect(plan.body).toMatchObject({
      ok: true,
      cached: false,
      overwrites: false,
      span: { start_s: 0, end_s: 40, every_s: 2, frames: 20 },
      sheet_url: `${TECH}/sheets/sheet.jpg`,
    });
    expect(call(b, 'GET', `${TECH}/sheets/sheet.jpg`).body.code).toBe('no_file');
    const id = call(b, 'POST', `${TECH}/sheet`, { confirm: plan.body.confirm }).body.job_id;
    let j = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    while (!j.done) j = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    expect(j.result).toMatchObject({
      sheet_url: `${TECH}/sheets/sheet.jpg`,
      scene_cuts: [12.4, 27],
    });
    expect(routeMemes(b, 'GET', url(`${TECH}/sheets/sheet.jpg`), null)).toMatchObject({
      status: 200,
      file: 'contact-sheet.jpg',
    });
    expect(call(b, 'POST', `${TECH}/sheet/plan`, { video }).body.overwrites).toBe(true);

    const gif = call(b, 'POST', `${TECH}/add-gif/plan`, {
      id: 'dog-turns',
      video,
      start: 10,
      end: 14,
      description: 'Собака оборачивается',
      tags: ['собака'],
    });
    expect(gif.body).toMatchObject({
      ok: true,
      span: { start_s: 10, end_s: 14 },
      source_url: video,
    });
    expect(
      call(b, 'POST', `${TECH}/add-gif/plan`, {
        ...(gif.body.params as object),
        id: 'x',
        start: 5,
        end: 4,
      }).body.code,
    ).toBe('bad_span');
    const gid = call(b, 'POST', `${TECH}/add-gif`, { confirm: gif.body.confirm }).body.job_id;
    let g = call(b, 'GET', `${TECH}/jobs/${gid}`).body;
    while (!g.done) g = call(b, 'GET', `${TECH}/jobs/${gid}`).body;
    expect(g.result).toMatchObject({
      duration_s: 4,
      cuts_inside: [12.4],
      entry: { id: 'dog-turns' },
    });
  });

  it('признаки: план центра, запуск, провал словами фабрики; на идущей задаче план — ok:false', () => {
    const b = createMemesBackend();
    const plan = call(b, 'POST', `${TECH}/embed/plan`, null);
    expect(plan.body).toMatchObject({ ok: true, steps: ['embedding'], action: 'meme_embed' });
    b.jobs.state.outcome = 'failed';
    const id = call(b, 'POST', `${TECH}/embed`, { confirm: plan.body.confirm }).body.job_id;
    expect(call(b, 'POST', `${TECH}/add-image/plan`, {}).body.code).toBe('bad_url');
    expect(call(b, 'POST', `${TECH}/embed/plan`, null).body.ok).toBe(false);
    let j = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    while (!j.done) j = call(b, 'GET', `${TECH}/jobs/${id}`).body;
    expect(j).toMatchObject({ state: 'failed', error: { code: 'embed_failed' } });
  });
});
