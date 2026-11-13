import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { PAST, RUNNING } from '@/mocks/batches';
import { batches, channels, mockGet, publish, questions, videos } from '@/mocks/handlers';
import { fixtures } from '@/mocks/fixtures';
import { EMPTY } from '@/mocks/videos';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const pin = fixtures.version.agents[0]!;

describe('главная', () => {
  it('показывает версию фабрики и пины агентов с подставного API', async () => {
    renderApp();
    const factory = await screen.findByTestId('factory-card');
    expect(
      await within(factory).findByRole('heading', {
        name: `Версия ${fixtures.version.factory.version}`,
      }),
    ).toBeInTheDocument();
    expect(within(factory).getByText('чистая')).toBeInTheDocument();
    const agents = screen.getByTestId('agents-card');
    expect(within(agents).getByRole('heading', { name: 'Все 1 на своих пинах' })).toBeVisible();
    expect(within(agents).getByText('footage-indexer')).toBeVisible();
  });

  it('агент не на пине — предупреждение, причина в тултипе и «подробнее»', async () => {
    server.use(
      mockGet('/api/version', {
        ...fixtures.version,
        factory: { ...fixtures.version.factory, dirty: true },
        agents: [{ ...pin, ok: false, why: 'HEAD не совпадает с пином' }],
      }),
    );
    renderApp();
    const agents = await screen.findByTestId('agents-card');
    expect(
      await within(agents).findByRole('heading', { name: '1 из 1 не на пине' }),
    ).toBeInTheDocument();
    expect(within(agents).getByText('не на пине', { exact: true })).toHaveAttribute(
      'data-tone',
      'warn',
    );
    expect(within(screen.getByTestId('factory-card')).getByText('есть правки')).toBeVisible();
  });

  it('фабрика не прочитала пины — ошибка с причиной под «подробнее»', async () => {
    server.use(
      mockGet('/api/version', {
        ...fixtures.version,
        agents: [],
        agents_error: 'no agents.lock.json',
      }),
    );
    renderApp();
    const agents = await screen.findByTestId('agents-card');
    expect(await within(agents).findByRole('alert')).toHaveTextContent(
      'Фабрика не прочитала пины агентов',
    );
  });

  it('без заглушек «скоро»: все блоки живые, без примерных данных', async () => {
    renderApp();
    // Примерных данных макета нет: ни просмотров, ни роликов, ни вопросов.
    expect(screen.queryByText(/просмотров|Entourage|Wren Hollow/)).not.toBeInTheDocument();
    await screen.findByTestId('publications-slots');
    expect(screen.queryByText(/Скоро · версия/)).not.toBeInTheDocument();
  });
});

describe('главная: «Ближайшие публикации»', () => {
  it('слоты всех каналов на 3 дня: день, время МСК, канал, ролик; канал без слота — строкой', async () => {
    renderApp();
    const card = screen.getByTestId('publications-card');
    expect(within(card).getByRole('heading', { name: 'Очередь на 3 дня' })).toBeVisible();
    const rows = await within(card).findAllByTestId('publications-slot');
    expect(rows.map((r) => `${r.dataset.channel} ${r.dataset.day}`)).toEqual([
      'example-film 2026-10-11',
      'example-tech 2026-10-11',
      'example-film 2026-10-12',
      'example-tech 2026-10-12',
      'example-film 2026-10-13',
      'example-tech 2026-10-13',
    ]);
    expect(rows[0]).toHaveTextContent('завтра01:00 МСК');
    expect(within(rows[1]!).getByTestId('publications-title')).toHaveTextContent('Homepod');
    expect(within(rows[1]!).getByTestId('publications-channel')).toHaveTextContent('ExampleTech');
    // Название — из карточки дня, без « #shorts».
    await waitFor(() =>
      expect(within(rows[2]!).getByTestId('publications-title')).toHaveTextContent(
        /^Delver Was a \$160 Million Bet on Tom Carver/,
      ),
    );
    expect(within(rows[2]!).getByRole('link')).toHaveAttribute(
      'href',
      '/publishing?channel=example-film&slot=2026-10-12%2Fdigger',
    );
    // Тире не уходит в начало строки на телефоне: пробел перед ним — неразрывный.
    expect(within(card).getByTestId('publications-note').textContent).toBe(
      'ExampleScience\u00a0— слот не задан',
    );
    expect(within(card).getByRole('link', { name: 'Лента слотов' })).toHaveAttribute(
      'href',
      '/publishing',
    );
  });

  it('свободный слот — «свободно»; очередь не прочиталась — ошибка с «Повторить»', async () => {
    delete publish.channels['example-tech']!.taken[1];
    renderApp();
    const card = screen.getByTestId('publications-card');
    const free = (await within(card).findAllByTestId('publications-slot')).find(
      (r) => r.dataset.channel === 'example-tech' && !r.dataset.slug,
    )!;
    expect(free).toHaveTextContent('свободно');
    expect(within(free).getByRole('link')).toHaveAttribute(
      'href',
      '/publishing?channel=example-tech',
    );
  });

  it('очереди публикации не прочитать — ошибка и «Повторить»', async () => {
    // 4xx повтором не лечится: ошибка — сразу, без трёх повторов сети.
    server.use(
      http.get('*/api/publish', () =>
        HttpResponse.json(
          { message: 'publish/queue_channels: not JSON', code: 'queue_broken', details: [] },
          { status: 409 },
        ),
      ),
    );
    renderApp();
    const card = screen.getByTestId('publications-card');
    expect(await within(card).findByText('Очередь публикаций не прочитать')).toBeVisible();
    expect(within(card).getByRole('button', { name: 'Повторить' })).toBeVisible();
  });

  it('лента канала не читается — строка канала красным, остальные слоты на месте', async () => {
    publish.state.queueBroken['example-tech'] = 'publish/uploads.json: not JSON';
    renderApp();
    const card = screen.getByTestId('publications-card');
    await waitFor(() =>
      expect(
        within(card)
          .getAllByTestId('publications-note')
          .map((n) => n.textContent),
      ).toEqual(['ExampleScience\u00a0— слот не задан', 'ExampleTech\u00a0— очередь не читается']),
    );
    expect(
      within(card)
        .getAllByTestId('publications-slot')
        .every((r) => r.dataset.channel === 'example-film'),
    ).toBe(true);
  });
});

describe('главная: карточка «Каналы»', () => {
  it('список каналов с подставного API: состояние, ссылка в экран канала, номера — в «подробнее»', async () => {
    channels.lock('example-tech', 'Идёт батч канала example-tech.');
    renderApp();
    const card = screen.getByTestId('channels-card');
    expect(await within(card).findByRole('heading', { name: '3 канала' })).toBeInTheDocument();
    expect(within(card).queryByText(/Скоро/)).not.toBeInTheDocument();

    const reel = within(card).getByTestId('home-channel-example-film');
    expect(within(reel).getByRole('link', { name: 'ExampleFilm' })).toHaveAttribute(
      'href',
      '/channels/example-film',
    );
    expect(within(reel).getByText('в работе')).toHaveAttribute('data-tone', 'ok');
    const sci = within(card).getByTestId('home-channel-example-science');
    expect(within(sci).getByText('оформлен, конвейера пока нет')).toBeInTheDocument();
    expect(within(sci).getByText('готовится')).toHaveAttribute('data-tone', 'idle');
    const tech = within(card).getByTestId('home-channel-example-tech');
    expect(within(tech).getByText('идёт батч')).toHaveAttribute('data-tone', 'live');
    expect(within(tech).getByText('идёт батч — правка настроек закрыта')).toBeInTheDocument();

    // Идентификаторы и прежние имена — только под «подробнее».
    const more = card.querySelector('details[data-slot="more"]')!;
    expect(more).toHaveTextContent('прежние имена: legacy-film');
    expect(more).toHaveTextContent(/канал example-film · .*ревизия [0-9a-f]{12}/);
    expect(within(card).getByRole('link', { name: 'Все' })).toHaveAttribute('href', '/channels');
  });

  it('CC-0122: «в копилке N» у канала — ссылкой на его копилку', async () => {
    renderApp();
    const card = screen.getByTestId('channels-card');
    const reel = await within(card).findByTestId('home-channel-example-film');
    const n = await within(reel).findByTestId('stash-count');
    expect(n).toHaveTextContent('в копилке 4 · устарели: 1');
    expect(n).toHaveAttribute('href', '/publishing?channel=example-film');
    const sci = within(card).getByTestId('home-channel-example-science');
    expect(await within(sci).findByTestId('stash-count')).toHaveTextContent('в копилке 0');
  });

  it('канал со сломанным конфигом — метка «конфиг сломан», причина под «подробнее»', async () => {
    server.use(
      mockGet('/api/channels', {
        checking: false,
        channels: [
          {
            id: 'example-film',
            display_name: null,
            former_ids: [],
            no_pipeline: null,
            stance: false,
            locked: false,
            error: 'channels/example-film.json: Expecting value: line 1 column 1',
            revision: null,
          },
        ],
      }),
    );
    renderApp();
    const card = screen.getByTestId('channels-card');
    expect(await within(card).findByRole('heading', { name: '1 канал' })).toBeInTheDocument();
    const row = within(card).getByTestId('home-channel-example-film');
    expect(within(row).getByRole('link', { name: 'example-film' })).toBeInTheDocument();
    expect(within(row).getByText('конфиг сломан')).toHaveAttribute('data-tone', 'danger');
    expect(within(row).queryByText(/Expecting value/)).not.toBeInTheDocument();
    expect(card.querySelector('details[data-slot="more"]')).toHaveTextContent(
      'ошибка: channels/example-film.json: Expecting value',
    );
  });

  it('каналов нет — «Каналов нет»', async () => {
    server.use(mockGet('/api/channels', { checking: false, channels: [] }));
    renderApp();
    const card = screen.getByTestId('channels-card');
    expect(await within(card).findByText('Каналов нет')).toBeInTheDocument();
  });

  it('список не загрузился — ошибка с «Повторить», повтор поднимает каналы', async () => {
    let fail = true;
    server.use(
      http.get('*/api/channels', () =>
        fail ? HttpResponse.json({ detail: 'boom' }, { status: 500 }) : undefined,
      ),
    );
    renderApp();
    const card = screen.getByTestId('channels-card');
    const alert = await within(card).findByRole('alert');
    expect(alert).toHaveTextContent('Каналы не загрузились');
    fail = false;
    await userEvent.click(within(alert).getByRole('button', { name: 'Повторить' }));
    expect(await within(card).findByRole('heading', { name: '3 канала' })).toBeInTheDocument();
  });
});

describe('главная: «Ролики ждут решения» (CC-0062)', () => {
  it('ролики без вердикта последнего батча: счёт, обложки ведут в ролик, «Ждут вас»', async () => {
    renderApp();
    const card = await screen.findByTestId('reels-card');
    expect(await within(card).findByTestId('reels-count')).toHaveTextContent(
      '1 из 3 — без вердикта в последнем батче',
    );
    const items = within(card).getAllByTestId('reels-item');
    expect(items.map((i) => i.dataset.slug)).toEqual(['delver']);
    expect(within(items[0]!).getByRole('link')).toHaveAttribute(
      'href',
      `/videos?batch=${encodeURIComponent(PAST)}&v=delver`,
    );
    expect(
      within(card).getByText(/сводного адреса «ролики на приёмке по всем/),
    ).toBeInTheDocument();
    expect(screen.getByTestId('attention-text')).toHaveTextContent(
      'Роликов без вердикта в последнем батче: 1.',
    );
  });

  it('у всех роликов есть вердикт — так и сказано, обложек нет', async () => {
    videos.setAcceptance(PAST, 'delver', { verdict: 'rejected', reason: 'x', reason_code: 'x' });
    renderApp();
    const card = await screen.findByTestId('reels-card');
    expect(await within(card).findByTestId('reels-count')).toHaveTextContent(
      'В последнем батче у всех роликов уже есть вердикт.',
    );
    expect(within(card).queryAllByTestId('reels-item')).toHaveLength(0);
  });

  it('исполнитель батча умер — «батч стоит», причина, возраст события (CC-0094, CC-0110)', async () => {
    batches.killExecutor(RUNNING);
    renderApp('/');
    const card = await screen.findByTestId('home-executor-gone');
    expect(card).toHaveTextContent('Исполнитель не отвечает — батч стоит');
    expect(card).toHaveTextContent('Исполнитель остановился, не записав конца');
    const home = screen.getByTestId('batch-card');
    expect(home).toHaveAttribute('data-state', 'gone');
    expect(within(home).getByTestId('home-batch-status')).toHaveTextContent(
      'исполнитель не отвечает',
    );
    expect(within(home).getByTestId('home-batch-age')).toHaveTextContent(
      'последнее событие 7 мин назад',
    );
    expect(within(home).queryByTestId('home-batch-eta')).toBeNull();
  });
});

describe('главная: «Ждут вас» горит, только когда что-то ждёт (CC-0137)', () => {
  const strip = () => screen.getByTestId('attention');
  const link = (name: RegExp) => within(strip()).getByRole('link', { name });
  const nothingWaits = () => {
    videos.setAcceptance(PAST, 'delver', { verdict: 'rejected', reason: 'x', reason_code: 'x' });
    questions.questions = [];
  };

  it('ролик без вердикта — «Ждут вас», главная кнопка «Смотреть ролики»', async () => {
    renderApp();
    await waitFor(() => expect(strip()).toHaveAttribute('data-state', 'waiting'));
    expect(within(strip()).getByText('Ждут вас')).toBeInTheDocument();
    expect(link(/Смотреть ролики/)).toHaveAttribute('data-slot', 'button');
    expect(link(/Смотреть ролики/).className).toContain('bg-primary');
    expect(link(/К вопросам/).className).not.toContain('bg-primary');
    // CC-0138: рамка второстепенной кнопки на жёлтой полосе в тёмной теме светлее.
    expect(link(/К вопросам/).className).toContain('dark:border-[color-mix');
    // На второстепенной кнопке счётчик — жёлтый кружок.
    const count = within(link(/К вопросам/)).getByLabelText('ждут ответа: 3');
    expect(count.className).toContain('bg-primary');
    expect(count.className).not.toContain('bg-primary-foreground');
  });

  it('ждут только вопросы — главная кнопка «К вопросам»', async () => {
    videos.setAcceptance(PAST, 'delver', { verdict: 'rejected', reason: 'x', reason_code: 'x' });
    renderApp();
    await waitFor(() => expect(strip()).toHaveAttribute('data-state', 'waiting'));
    expect(screen.getByTestId('attention-text')).toHaveTextContent(
      'В последнем батче все ролики с вердиктом. Вопросов ждут вашего ответа: 3.',
    );
    expect(link(/К вопросам/).className).toContain('bg-primary');
    expect(link(/Смотреть ролики/).className).not.toContain('bg-primary');
    // CC-0138: на жёлтой главной кнопке счётчик — тёмный кружок, а не голая цифра.
    const count = within(link(/К вопросам/)).getByLabelText('ждут ответа: 3');
    expect(count.className).toContain('bg-primary-foreground');
    expect(count.className).toContain('text-primary');
  });

  it('ничего не ждёт — «Ничего не ждёт», без жёлтого, кнопки второстепенные', async () => {
    nothingWaits();
    renderApp();
    await waitFor(() => expect(strip()).toHaveAttribute('data-state', 'calm'));
    expect(within(strip()).getByText('Ничего не ждёт')).toBeInTheDocument();
    expect(within(strip()).queryByText('Ждут вас')).toBeNull();
    expect(strip()).toHaveAttribute('data-tour', 'attention');
    expect(strip().className).not.toContain('--primary');
    expect(screen.getByTestId('attention-text')).toHaveTextContent(
      'В последнем батче все ролики с вердиктом. Вопросов к вам нет.',
    );
    expect(link(/Смотреть ролики/)).toHaveAttribute('href', '/videos');
    expect(link(/К вопросам/)).toHaveAttribute('href', '/questions');
    expect(
      within(strip())
        .getAllByRole('link')
        .map((l) => l.className),
    ).not.toContainEqual(expect.stringContaining('bg-primary'));
  });

  it('в последнем батче нет роликов — «роликов нет», а не «все с вердиктом»', async () => {
    questions.questions = [];
    server.use(
      mockGet('/api/batches/history', {
        channel: null,
        runs: [
          {
            batch: EMPTY,
            id: '2026-10-07T0200Z',
            channel: 'example-tech',
            date: '2026-10-07',
            started: '2026-10-07T02:00:00Z',
            ended: '2026-10-07T02:40:00Z',
            videos: 0,
            wall_s: 2400,
            outcome: 'no_videos',
            launch: null,
          },
        ],
        launches: [],
      }),
    );
    renderApp();
    await waitFor(() => expect(strip()).toHaveAttribute('data-state', 'calm'));
    expect(screen.getByTestId('attention-text')).toHaveTextContent(
      'В последнем батче роликов нет. Вопросов к вам нет.',
    );
    expect(screen.getByTestId('attention-text')).not.toHaveTextContent('с вердиктом');
  });

  it('пока данные идут — нейтрально: ни «Ждут вас», ни «Ничего не ждёт»', () => {
    renderApp();
    expect(strip()).toHaveAttribute('data-state', 'loading');
    expect(within(strip()).getByText('Что ждёт вас')).toBeInTheDocument();
    expect(strip()).toHaveAttribute('data-tour', 'attention');
  });

  it('вопросы не прочитались — не «Ничего не ждёт», а «не удалось» и «Повторить»', async () => {
    nothingWaits();
    server.use(http.get('*/api/questions', () => new HttpResponse('down', { status: 503 })));
    renderApp();
    await waitFor(() =>
      expect(screen.getByTestId('attention-text')).toHaveTextContent(
        'В последнем батче все ролики с вердиктом. Не удалось прочитать вопросы.',
      ),
    );
    expect(strip()).toHaveAttribute('data-state', 'error');
    expect(within(strip()).queryByText('Ничего не ждёт')).toBeNull();
    expect(within(strip()).getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });
});
