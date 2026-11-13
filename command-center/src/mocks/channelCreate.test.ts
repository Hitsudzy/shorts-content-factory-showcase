import { createChannelsBackend, routeChannels } from './channels';

const url = (p: string) => new URL(`http://x${p}`);
const count = (b: ReturnType<typeof createChannelsBackend>) => {
  const r = b.list();
  return r.status === 200 ? r.body.channels.length : -1;
};

describe('подставная фабрика: новый канал', () => {
  it('шаблон отвечает по своему пути, а не как канал «template»', () => {
    const b = createChannelsBackend();
    const r = routeChannels(b, 'GET', url('/api/channels/template'), null);
    expect(r?.status).toBe(200);
    expect(r?.body).toMatchObject({ status: 'no_pipeline', lock: { locked: false } });
  });

  it('dry-run: ошибки входов с полем, ничего не пишет; создание — канал, история, без конвейера', () => {
    const b = createChannelsBackend();
    const bad = b.create({ channel_id: 'ExampleFilm', display_name: 'ExampleFilm', dry_run: true });
    expect(bad.status).toBe(200);
    if (bad.status !== 200) return;
    expect(bad.body.ok).toBe(false);
    expect(bad.body.errors.map((e) => e.field)).toEqual(['channel_id', 'display_name']);
    expect(bad.body.files).toEqual([]);
    expect(b.writes).toEqual([]);

    const dry = b.create({ channel_id: 'example-food', display_name: 'ExampleFood', dry_run: true });
    if (dry.status !== 200) throw new Error('dry run');
    expect(dry.body.files.map((f) => f.path)).toEqual([
      'channels/example-food.json',
      'channels/example-food/stance.json',
      'channels/example-food/brand/description.md',
    ]);
    expect(count(b)).toBe(3);

    const made = b.create({ channel_id: 'example-food', display_name: 'ExampleFood' });
    if (made.status !== 200) throw new Error('create');
    expect(made.body.subject).toBe('Канал ExampleFood: создан (из центра)');
    expect(made.body.channel?.no_pipeline).toBe('конвейера нет - батча не будет');
    expect(made.body.channel?.config_text).toBe(dry.body.files[0]!.text);
    expect(count(b)).toBe(4);
    expect(b.history('example-food').body).toMatchObject({ entries: [{ action: 'create' }] });
  });

  it('идёт любой батч — создание 409 batch_running, dry-run говорит про блокировку', () => {
    const b = createChannelsBackend();
    b.lock('example-tech', 'идёт батч');
    const dry = b.create({ channel_id: 'example-food', display_name: 'ExampleFood', dry_run: true });
    expect(dry.body).toMatchObject({ ok: true, lock: { locked: true } });
    const r = b.create({ channel_id: 'example-food', display_name: 'ExampleFood' });
    expect(r).toMatchObject({ status: 409, body: { code: 'batch_running' } });
  });
});

describe('подставная фабрика: договор 0.5.0 (CC-0041)', () => {
  it('свежесть в каждом lock и в списке; `checking` — на заданное число чтений', () => {
    const b = createChannelsBackend();
    b.scan({ checked_at: '2026-10-10T09:00:00Z', age_s: 12, checking: 2 });
    expect(b.list().body).toMatchObject({
      checked_at: '2026-10-10T09:00:00Z',
      age_s: 12,
      checking: true,
    });
    expect(b.detail('example-film').body).toMatchObject({ lock: { age_s: 12, checking: true } });
    expect(b.template().body).toMatchObject({ lock: { checking: false } });
  });

  it('«устаревшее открыто»: чтение батча не видит, запись — 409 batch_running', () => {
    const b = createChannelsBackend();
    b.lock('example-film', 'Идёт батч канала example-film.', false);
    expect(b.detail('example-film').body).toMatchObject({ lock: { locked: false } });
    const r = b.save('example-film', { config_text: '{}', base: null, note: null });
    expect(r).toMatchObject({ status: 409, body: { code: 'batch_running' } });
    b.lock('example-film', null);
    b.openBatch('Идёт пересборка.', false);
    expect(b.template().body).toMatchObject({ lock: { locked: false } });
    const made = b.create({ channel_id: 'example-food', display_name: 'ExampleFood' });
    expect(made).toMatchObject({ status: 409, body: { code: 'batch_running' } });
  });

  it('позиция мастера (`stance_text`) — в файлах создания; чужой channel_id — поле stance.channel_id', () => {
    const b = createChannelsBackend();
    const text = '{\n  "channel_id": "example-food",\n  "thesis": "x"\n}\n';
    const ok = b.create({
      channel_id: 'example-food',
      display_name: 'ExampleFood',
      stance_text: text,
    });
    if (ok.status !== 200) throw new Error('create');
    expect(ok.body.channel?.stance_text).toBe(text);
    const bad = b.create({
      channel_id: 'example-fish',
      display_name: 'ExampleFish',
      stance_text: '{"channel_id": "other"}',
      dry_run: true,
    });
    expect(bad.body).toMatchObject({ ok: false, errors: [{ field: 'stance.channel_id' }] });
    const broken = b.create({
      channel_id: 'example-fish',
      display_name: 'ExampleFish',
      stance_text: '{',
    });
    expect(broken).toMatchObject({ status: 422, body: { errors: [{ field: 'stance' }] } });
  });

  it('`new` — служебное имя и для фабрики', () => {
    const b = createChannelsBackend();
    const r = b.create({ channel_id: 'new', display_name: 'Новый', dry_run: true });
    expect(r.body).toMatchObject({
      ok: false,
      errors: [{ field: 'channel_id', text: "channel_id: 'new' - служебное имя, не канал" }],
    });
  });
});
