// «Публикация» (CC-0067): каналы с завтрашним слотом, лента на 14 дней, карточка для Studio с
// «скопировать» (тост, клавиатура), холды и переключатель — только чтение (записи — CC-0068,
// ./PublishingWrites.test.tsx).
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { defaultSlot } from '@/api/publish';
import { publish } from '@/mocks/handlers';
import {
  createPublishBackend,
  NOT_READY,
  PLACED,
  READY,
  REEL,
  SCIENCE,
  TECH,
  UPLOADED,
} from '@/mocks/publish';
import { renderApp } from '@/test/renderApp';

import { freeText, slotTitle } from './feedWords';
import { lineState, mskDay, slotDay, slotRuleText, slotTime } from './format';

describe('публикация: слова', () => {
  it('CC-0128: кто в слоте — название карточки без хэштегов, иначе слаг словами; прошедший — «слот прошёл»', () => {
    const slot = (taken_by: string | null, day = '2026-10-15') =>
      ({
        at: `${day}T22:00:00Z`,
        day,
        label: `${day} 01:00 МСК`,
        local: '01:00',
        taken_by,
        next_free: false,
      }) as Parameters<typeof slotTitle>[0];
    expect(slotTitle(slot('rink-rivals'), undefined)).toBe('Rink rivals');
    expect(
      slotTitle(slot('x'), { pending: false, note: { title: 'Real Title #shorts' } } as never),
    ).toBe('Real Title');
    expect(slotTitle(slot(null), undefined)).toBeNull();
    const q = { as_of: '2026-10-14T12:00:00Z' } as Parameters<typeof freeText>[0];
    expect(freeText(q, slot(null, '2026-10-13'), 'МСК')).toBe('МСК · слот прошёл');
    expect(freeText(q, slot(null, '2026-10-20'), 'МСК')).toBe('МСК · ждёт принятый ролик');
    expect(freeText(q, slot('x', '2026-10-13'), 'МСК')).toBe('МСК');
  });

  it('время и день слота, правило слота', () => {
    const s = { local: '2026-10-11T01:00:00+03:00', label: '2026-10-11 01:00 МСК' };
    expect(slotTime(s)).toEqual({ time: '01:00', zone: 'МСК' });
    expect(slotDay('2026-10-11', '2026-10-10')).toBe('завтра');
    expect(slotDay('2026-10-13', '2026-10-10')).toBe('вт 13.10');
    expect(mskDay('2026-10-10T22:00:00Z')).toBe('2026-10-11');
    expect(
      slotRuleText({
        channel: REEL,
        times: ['01:00'],
        tz: 'Europe/Moscow',
        per_day: 1,
        lead_hours: 12,
      }),
    ).toBe('01:00 МСК · 1 в день · не раньше чем через 12 ч');
  });

  it('состояние канала по завтрашнему слоту', () => {
    const base = {
      channel: REEL,
      slot: null,
      paused: null,
      pause_notices: [],
      tomorrow: null,
      next_free: null,
      next_free_error: null,
      waiting: [],
      error: null,
    };
    expect(lineState(base).label).toBe('нет слота');
    expect(lineState({ ...base, error: 'x' }).tone).toBe('danger');
    const slot = {
      channel: REEL,
      times: ['01:00'],
      tz: 'Europe/Moscow',
      per_day: 1,
      lead_hours: 12,
    };
    expect(lineState({ ...base, slot, paused: 'user' }).label).toBe('на паузе');
    expect(
      lineState({ ...base, slot, tomorrow: { code: 1, state: 'empty', line: '' } }).label,
    ).toBe('завтра пусто');
  });
});

describe('публикация: какой слот открыть сам', () => {
  const q = (() => {
    const r = createPublishBackend().queue(REEL);
    if (r.status !== 200) throw new Error('queue');
    return r.body;
  })();

  it('ближайший незагруженный; все загружены — ближайший впереди с карточкой; прошедшие — нет', () => {
    expect(defaultSlot(q)?.taken_by).toBe(READY);
    const allUp = {
      ...q,
      occupants: q.occupants.map((o) => ({ ...o, sources: [...o.sources, 'uploads.json:x'] })),
    };
    expect(defaultSlot(allUp)?.taken_by).toBe(PLACED);
    expect(defaultSlot({ ...q, as_of: '2026-12-01T00:00:00Z' })).toBeUndefined();
  });
});

describe('экран «Публикация»', () => {
  it('таб ведёт на экран, а не на заглушку; канал по умолчанию — первый с очередью', async () => {
    renderApp('/');
    await userEvent.click(screen.getByRole('link', { name: 'Публикация' }));
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Публикация' }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Скоро · версия/)).not.toBeInTheDocument();
    const list = await screen.findAllByTestId('publish-channel');
    expect(list.map((l) => l.dataset.channel)).toEqual([REEL, SCIENCE, TECH]);
    expect(within(list[0]!).getByRole('link')).toHaveAttribute('aria-current', 'true');
    expect(within(list[1]!).getByText('нет слота')).toBeInTheDocument();
    expect(within(list[2]!).getByText('завтра занято')).toBeInTheDocument();
  });

  it('лента: 14 слотов, загруженный, готовый, неготовый, ближайший свободный', async () => {
    renderApp('/publishing');
    const feed = await screen.findByTestId('slot-feed');
    await waitFor(() => expect(within(feed).getAllByTestId('slot')).toHaveLength(14));
    const state = (slug: string) =>
      within(feed)
        .getAllByTestId('slot')
        .find((s) => s.dataset.slug === slug)?.dataset.state;
    await waitFor(() => expect(state(READY)).toBe('готов'));
    expect(state(UPLOADED)).toBe('загружен');
    expect(state(PLACED)).toBe('загружен');
    expect(state(NOT_READY)).toBe('не готов');
    const free = within(feed)
      .getAllByTestId('slot')
      .filter((s) => s.dataset.state === 'ближайший свободный');
    expect(free).toHaveLength(1);
    // Лента фабрики начинается с сегодня: сегодняшний слот 01:00 уже прошёл.
    const past = within(feed).getAllByTestId('slot')[0]!;
    expect(past).toHaveAttribute('data-state', 'прошёл');
    // CC-0128: прошедший свободный слот не «ждёт принятый ролик».
    expect(within(past).getByTestId('slot-sub')).toHaveTextContent('МСК · слот прошёл');
    expect(past).not.toHaveTextContent('ждёт принятый ролик');
    // CC-0139: сначала день, под ним время с поясом — у занятых и свободных строк одинаково.
    expect(within(past).getByTestId('slot-day')).toHaveTextContent('сегодня');
    expect(within(past).getByTestId('slot-time')).toHaveTextContent('01:00 МСК');
    for (const row of within(feed).getAllByTestId('slot')) {
      const day = within(row).getByTestId('slot-day');
      const time = within(row).getByTestId('slot-time');
      expect(day.compareDocumentPosition(time) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    }
    // Ни одна строка не называет ролик голым слагом.
    for (const row of within(feed).getAllByTestId('slot')) {
      const slug = row.dataset.slug;
      if (slug) expect(within(row).getByTestId('slot-title').textContent).not.toBe(slug);
    }
    expect(feed).not.toHaveTextContent('#shorts');
    expect(within(feed).getByTestId('slot-rule')).toHaveTextContent('01:00 МСК');
    // Названия — из карточек, имена роликов — только под «подробнее».
    expect(within(feed).getByText(/Vanguards: Doomsday Moved Again/)).toBeInTheDocument();
    // «Ждут слота» — те же ролики, что в копилке: в ленте строки нет, только под «подробнее».
    expect(within(feed).getByTestId('waiting')).toHaveTextContent('это ролики копилки выше');
    expect(within(feed).queryByText(/Ждут слота в очереди/)).toBeNull();
  });

  it('CC-0122: имя канала — в заголовке ленты и в «Для Studio»', async () => {
    renderApp(`/publishing?channel=${REEL}`);
    const feed = await screen.findByTestId('slot-feed');
    await waitFor(() =>
      expect(within(feed).getByTestId('feed-channel')).toHaveTextContent('ExampleFilm'),
    );
    expect(
      within(screen.getByTestId('studio-card')).getByTestId('studio-channel'),
    ).toHaveTextContent('ExampleFilm');
    // CC-0131: подпись капителью, а имя канала — как пишется.
    expect(within(feed).getByTestId('feed-channel')).toHaveClass('normal-case');
    expect(within(screen.getByTestId('studio-card')).getByTestId('studio-channel')).toHaveClass(
      'normal-case',
    );
  });

  it('карточка по умолчанию — ближайший незагруженный ролик; поля копируются с тостом', async () => {
    const user = userEvent.setup();
    renderApp('/publishing');
    const card = await screen.findByTestId('studio-card');
    await waitFor(() => expect(card).toHaveAttribute('data-slug', READY));
    await within(card).findByText(/Vanguards: Doomsday Moved Again/, { selector: 'h2' });
    const keys = within(card)
      .getAllByTestId('studio-field')
      .map((f) => f.dataset.field);
    expect(keys).toEqual(
      expect.arrayContaining([
        'file',
        'title',
        'description',
        'tags',
        'visibility',
        'date',
        'time',
        'zone',
      ]),
    );
    // Язык настройки канала не называют — «спросить вас», без кнопки.
    const ask = within(card).getByTestId('studio-ask');
    expect(ask).toHaveAttribute('data-field', 'language');
    expect(within(ask).queryByRole('button')).not.toBeInTheDocument();

    await user.click(within(card).getByRole('button', { name: 'Скопировать: Теги' }));
    expect(await navigator.clipboard.readText()).toBe(
      'Vanguards Doomsday, Zenith, MCU, release date, Russo brothers',
    );
    expect(screen.getByTestId('toast')).toHaveTextContent('Скопировано: Теги');

    // С клавиатуры: фокус на кнопке времени и Enter.
    const time = within(card).getByRole('button', { name: 'Скопировать: Время' });
    time.focus();
    await user.keyboard('{Enter}');
    expect(await navigator.clipboard.readText()).toBe('01:00');
    expect(screen.getByTestId('toast')).toHaveTextContent('Скопировано: Время');
  });

  it('выбор слота открывает его карточку; неготовая — с отказом и тем, что есть', async () => {
    const user = userEvent.setup();
    renderApp('/publishing');
    const feed = await screen.findByTestId('slot-feed');
    const row = await waitFor(() => {
      const r = within(feed)
        .getAllByTestId('slot')
        .find((s) => s.dataset.slug === NOT_READY);
      if (!r) throw new Error('нет слота');
      return r;
    });
    await user.click(within(row).getByRole('link'));
    const card = screen.getByTestId('studio-card');
    await waitFor(() => expect(card).toHaveAttribute('data-slug', NOT_READY));
    expect(await within(card).findByTestId('studio-refusal')).toHaveTextContent(
      'Поля для Studio не готовы',
    );
    expect(within(card).getByRole('button', { name: 'Скопировать: Название' })).toBeInTheDocument();
    expect(within(card).getAllByTestId('studio-field')).toHaveLength(2 + 5);
  });

  it('загруженный ролик: поля — для сверки', async () => {
    renderApp(`/publishing?slot=2026-10-12/${PLACED}`);
    const card = await screen.findByTestId('studio-card');
    expect(await within(card).findByTestId('studio-notices')).toHaveTextContent(
      'уже загружен в YouTube',
    );
  });

  it('холды и записи — свёрнутыми раскрывашками, без единого POST', async () => {
    renderApp('/publishing');
    const holds = await screen.findByTestId('holds');
    expect(await within(holds).findByText('Открытых: 2')).toBeInTheDocument();
    expect(within(holds).getAllByTestId('hold')[1]).toHaveTextContent('права на трейлер');
    expect(within(holds).getByTestId('holds-resolved')).toHaveTextContent('Снятые раньше: 1');
    const status = screen.getByTestId('channel-status');
    await within(status).findByText('идут');
    expect(within(status).getByTestId('state-api-upload')).toHaveTextContent('выключена');
    expect(await within(status).findByTestId('api-warnings')).toHaveTextContent(
      'ещё не прошло аудит',
    );
    expect(within(status).getByTestId('state-rotation')).toHaveTextContent('урезана');
    expect(within(status).getByTestId('state-studio')).toHaveTextContent('2 из 5');
    // Подпись холда (CC-0071), пауза, ротация (CC-0068) и переключатель (CC-0069) — свёрнутыми
    // раскрывашками; загрузка — кнопкой, что открывает план. Пока их не трогать, ни одного POST.
    expect(within(holds).getByTestId('hold-sign-toggle')).toHaveAttribute('aria-expanded', 'false');
    expect(within(status).getByTestId('switch-on-toggle')).toHaveAttribute(
      'aria-expanded',
      'false',
    );
    expect(within(status).queryByTestId('switch-on-open')).not.toBeInTheDocument();
    expect(publish.state.calls.every((c) => c.startsWith('/api/publish'))).toBe(true);
    expect(publish.writes.state.calls).toEqual([]);
  });

  it('канал на паузе: пауза словами, свободных слотов не ищет', async () => {
    publish.channels[TECH]!.pause = { ...publish.channels[SCIENCE]!.pause!, channel: TECH };
    renderApp(`/publishing?channel=${TECH}`);
    const status = await screen.findByTestId('channel-status');
    expect(await within(status).findByText('на паузе')).toBeInTheDocument();
    expect(within(status).getByTestId('state-pause')).toHaveTextContent('канал ещё не запущен');
    const feed = await screen.findByTestId('slot-feed');
    await waitFor(() =>
      expect(within(feed).getAllByTestId('slot')[4]).toHaveAttribute('data-state', 'пауза'),
    );
    expect(screen.getByTestId('studio-card')).toHaveTextContent('Ролик не выбран');
  });

  it('канал без слота: слова вместо ленты', async () => {
    renderApp(`/publishing?channel=${SCIENCE}`);
    expect(await screen.findByText('У канала нет слота публикации')).toBeInTheDocument();
  });

  it('канал без настроек ротации: слова, строка фабрики — под «подробнее»', async () => {
    renderApp(`/publishing?channel=${TECH}`);
    const rot = await screen.findByTestId('state-rotation');
    expect(await within(rot).findByTestId('state-failed')).toHaveTextContent(
      'Фабрика не может прочитать ротацию канала',
    );
    expect(
      within(rot)
        .getByText(/^channel 'example-tech': patterns\.rotation is missing/)
        .closest('details'),
    ).not.toHaveAttribute('open');
  });

  it('отказы: очередь не читается, реестр холдов сломан', async () => {
    publish.state.queueBroken[REEL] =
      'publish/uploads.json: not JSON - журнал загрузок не читается';
    publish.state.holdsProblem = 'publish/publication-holds.json: not JSON';
    renderApp(`/publishing?channel=${REEL}`);
    expect(await screen.findByText('Ленту слотов не прочитать')).toBeInTheDocument();
    expect(await screen.findByTestId('holds-problem')).toHaveTextContent(
      'фабрика держит каждый ролик',
    );
  });
});
