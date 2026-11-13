import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mockGet, schedule } from '@/mocks/handlers';
import { NOTE_REQUIRED } from '@/mocks/schedule';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { changesText, dayLabel, durationText, estimateBasis, timerState } from './format';
import { editOf } from './windowDraft';

describe('«Батчи» (а): план и расписание', () => {
  it('таб «Батчи» открывает экран, а не «скоро»', async () => {
    renderApp('/batches');
    expect(await screen.findByRole('heading', { name: 'Батчи', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Батчи' })).toHaveAttribute('aria-current', 'page');
    // Ход батчей — живой (CC-0051), действия — ещё заглушка (CC-0052).
    expect(screen.getByTestId('batches-live')).toHaveTextContent('Идёт сейчас');
    expect(await screen.findByTestId('batches-actions')).toHaveTextContent('Запуск вручную');
  });

  it('план недели: дни, окно, оценки с пометкой, каналы вне плана, таймер', async () => {
    renderApp('/batches');
    const plan = await screen.findByTestId('week-plan');
    const days = within(plan)
      .getAllByRole('listitem')
      .filter((li) => li.dataset.status);
    expect(days).toHaveLength(7);
    expect(days[0]).toHaveAttribute('data-status', 'done');
    expect(days[0]).toHaveTextContent('сегодня');
    // Причина дня — словами (CC-0146); строка фабрики — только под «Подробнее».
    expect(
      within(plan).getByText('План на 7 дней · не больше одного батча в сутки на всю фабрику'),
    ).toBeInTheDocument();
    // «Сутки» — сутки квоты поиска YouTube (CF-0787): когда обновится — по МСК.
    expect(within(days[0]!).getByTestId('day-why')).toHaveTextContent(
      'Батч в эти сутки квоты уже был — следующие начнутся 11.10, 10:00 МСК',
    );
    const factory = within(days[0]!).getByTestId('day-factory');
    expect(factory).toHaveTextContent('1 батч в сутки квоты YouTube Search на фабрику');
    expect(factory.closest('details')!.open).toBe(false);

    // Окна 11.10 (02:00 и 05:30 МСК) — ещё в сутках квоты 10.10, их уже взял батч (CC-0147).
    const taken = screen.getByTestId('day-2026-10-11');
    expect(taken).toHaveAttribute('data-kind', 'quota_day_taken');
    expect(taken).toHaveAttribute('data-status', 'done');
    expect(within(taken).getByText('квота занята')).toHaveAttribute('data-tone', 'idle');
    expect(within(taken).queryByText('батч был')).toBeNull();
    // Имена каналов приходят отдельным запросом — ждём их.
    await waitFor(() =>
      expect(within(taken).getByTestId('day-why')).toHaveTextContent(
        'Эти сутки квоты поиска YouTube уже занял прошлый батч — второй не запускается. Следующее окно: ExampleFilm 12.10, 02:00 МСК',
      ),
    );

    const planned = screen.getByTestId('day-2026-10-12');
    expect(planned).toHaveAttribute('data-status', 'planned');
    expect(within(planned).getByTestId('day-window')).toHaveTextContent('окно 02:00–05:00 МСК');
    expect(within(planned).getByTestId('day-est-end')).toHaveAttribute('data-basis', 'runs');
    expect(within(planned).getByTestId('day-est-videos')).toHaveTextContent('по умолчанию');
    expect(within(planned).getByTestId('day-why')).toHaveTextContent(
      'Публикаций на 3 дня вперёд не хватает — нужен батч. Первый пустой слот: 12.10, 18:00 МСК. Ролики встанут в слоты 12.10–14.10',
    );
    // Причина — из `kind` дня (CC-0147): день с батчем, «батч не нужен», «некого планировать».
    expect(days.map((li) => li.dataset.kind)).toEqual([
      'done_today',
      'quota_day_taken',
      'needs_batch',
      'needs_batch',
      'needs_batch',
      'fed',
      'nobody_available',
    ]);
    await waitFor(() =>
      expect(within(days[6]!).getByTestId('day-why')).toHaveTextContent(
        'Некого планировать: ExampleFilm и ExampleTech на паузе до 17.10 (заметка: «меняю ключи YouTube»)',
      ),
    );
    expect(within(days[6]!).queryByTestId('day-notes')).toBeNull();
    // Метка дня: «некого» — не «без батча» (тот у дня, когда публикаций хватает), CC-0147.
    expect(within(days[6]!).getByText('некого')).toHaveAttribute('data-tone', 'warn');
    expect(within(days[5]!).getByText('без батча')).toHaveAttribute('data-tone', 'idle');
    expect(within(planned).getByTestId('day-why').textContent).toContain('не хватает\u00a0— нужен');
    expect(within(planned).getByTestId('day-notes').closest('details')!.open).toBe(false);
    const fed = screen.getByTestId('day-2026-10-15');
    expect(fed).toHaveAttribute('data-status', 'idle');
    expect(within(fed).getByTestId('day-why')).toHaveTextContent(
      'Публикаций хватает на 3 дня вперёд — батч не нужен',
    );
    // Ни одной строки фабрики на виду: «дн.», «≥» — только внутри «Подробнее».
    for (const why of within(plan).getAllByTestId('day-why'))
      expect(why.textContent).not.toMatch(/дн\.|≥|1 батч/);

    await userEvent.click(document.body);
    within(planned).getByTestId('day-est-end').focus();
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Оценка по 5 прогонам');

    // Вне расписания (CC-0140): ExampleScience без слота публикации — строка с причиной словами.
    const science = await screen.findByTestId('why-not-example-science');
    await waitFor(() =>
      expect(science).toHaveTextContent('ExampleScience — вне расписания: нет слота публикации'),
    );
    expect(science).toHaveAttribute('data-reason', 'no_slot');
    expect(screen.queryByTestId('why-not-example-tech')).not.toBeInTheDocument();
    expect(screen.queryByTestId('why-not-example-film')).not.toBeInTheDocument();
    expect(screen.getByTestId('switch-timer')).toHaveTextContent('не установлен');
  });

  it('открытые батчи старше потолка свежести — предупреждение, id — под «подробнее»', async () => {
    schedule.setStaleOpen(['example-film 2026-10-08T0205Z']);
    renderApp('/batches');
    const stale = await screen.findByTestId('stale-open');
    expect(stale).toHaveTextContent('Один открытый батч давно молчит');
    expect(screen.getByText('example-film 2026-10-08T0205Z').closest('details')!.open).toBe(false);
  });

  it('рубильник: без заметки — отказ фабрики как есть, с заметкой — включено', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    await user.click(await screen.findByTestId('switch-toggle'));
    const dialog = await screen.findByRole('alertdialog', { name: 'Включить расписание?' });
    await user.click(within(dialog).getByRole('button', { name: 'Включить' }));
    expect(await within(dialog).findByTestId('refusal-message')).toHaveTextContent(NOTE_REQUIRED);
    expect(schedule.writes).toHaveLength(0);

    await user.type(within(dialog).getByTestId('switch-note-input'), 'в чате 10.10 сказал включай');
    await user.click(within(dialog).getByRole('button', { name: 'Включить' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument());
    expect(schedule.writes).toEqual([
      { kind: 'switch', body: { on: true, note: 'в чате 10.10 сказал включай' } },
    ]);
    expect(await screen.findByTestId('header-switch')).toHaveTextContent('Рубильник: включено');
    expect(screen.getByTestId('switch-note')).toHaveTextContent('в чате 10.10 сказал включай');
    expect(screen.getByTestId('switch-toggle')).toHaveTextContent('Выключить расписание');
  });

  it('рубильник: «Отмена» ничего не пишет', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    await user.click(await screen.findByTestId('switch-toggle'));
    await user.click(await screen.findByRole('button', { name: 'Отмена' }));
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(schedule.writes).toHaveLength(0);
  });

  it('окно канала: сохранение, «ничего не поменялось», 422 как есть', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const card = await screen.findByTestId('window-example-film');
    const win = await within(card).findByTestId('win-window');
    expect(win).toHaveValue('02:00');

    await user.clear(win);
    await user.type(win, '03:30');
    await user.click(within(card).getByTestId('win-save'));
    const saved = await within(card).findByTestId('win-saved');
    expect(saved).toHaveTextContent('начало окна: 02:00 → 03:30');
    expect(within(card).getByTestId('win-overlay')).toHaveTextContent('{"window":"03:30"}');
    expect(within(card).getByTestId('win-source')).toHaveTextContent('пульт');

    await user.click(within(card).getByTestId('win-save'));
    expect(await within(card).findByTestId('win-unchanged')).toHaveTextContent(
      'Ничего не поменялось',
    );

    const hours = within(card).getByTestId('win-hours');
    await user.clear(hours);
    await user.type(hours, '0.3');
    await user.click(within(card).getByTestId('win-save'));
    expect(await within(card).findByTestId('refusal-message')).toHaveTextContent(
      'Настройка не принята: длительность окна 0.3: от 0.5 до 24 ч',
    );
    // Черновик на месте — можно поправить и сохранить.
    expect(hours).toHaveValue(0.3);
  });

  it('план не строится — сообщение фабрики и «повторить»', async () => {
    server.use(
      mockGet(
        '/api/schedule',
        {
          message: 'План батчей не строится - фабрика ответила ошибкой.',
          code: 'schedule_broken',
          details: ['ValueError: boom'],
        },
        500,
      ),
    );
    renderApp('/batches');
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('План батчей не строится - фабрика ответила ошибкой.');
    expect(screen.getByRole('button', { name: 'Повторить' })).toBeInTheDocument();
  });
});

describe('слова экрана «Батчи»', () => {
  it('день, длительность, оценка, таймер, перемены', () => {
    expect(dayLabel('2026-10-10', '2026-10-10')).toEqual({
      weekday: 'сб',
      date: '10.10',
      rel: 'сегодня',
    });
    expect(dayLabel('2026-10-12', '2026-10-10').rel).toBeNull();
    expect(durationText(15_120)).toBe('≈ 4 ч 12 мин');
    expect(durationText(3600)).toBe('≈ 1 ч');
    expect(estimateBasis(0)).toMatch(/^По умолчанию/);
    expect(estimateBasis(1)).toMatch(/^Оценка по 1 прогону/);
    expect(estimateBasis(null)).toBeNull();
    expect(timerState('таймер тика установлен (/x.plist)').label).toBe('установлен');
    expect(timerState('таймер тика НЕ установлен (нет /x)').label).toBe('не установлен');
    expect(timerState('таймер тика не проверяется на этой ОС (linux)').tone).toBe('idle');
    expect(changesText({ enabled: [true, false], window_hours: [3, 2.5] })).toEqual([
      'участие в расписании: да → нет',
      'длительность окна: 3 ч → 2.5 ч',
    ]);
  });

  it('тело PUT: числа из полей, пустое — не задано', () => {
    expect(
      editOf({
        enabled: true,
        window: ' 03:30 ',
        window_hours: '2,5',
        min_feed_days: '',
        batch_feed_days: '',
        windows: '',
        note: '',
      }),
    ).toEqual({
      enabled: true,
      window: '03:30',
      window_hours: 2.5,
      min_feed_days: null,
      note: null,
    });
  });
});
