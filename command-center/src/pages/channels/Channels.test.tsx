import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { REEL_CONFIG_TEXT, revisionOf, REEL_STANCE_TEXT } from '@/mocks/channels';

import { channels } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

// Первый заход грузит ленивый кусок страницы: под нагрузкой это дольше секунды —
// findBy* ждут до общего потолка src/test/timeouts.ts, тесты здесь длинные, отсюда 30 с.
describe('экран «Каналы»', { timeout: 30_000 }, () => {
  it('обзор: состояние, расписание из конфига, пауза и ближайшая публикация', async () => {
    channels.lock(
      'example-tech',
      'Идёт батч канала example-tech: пока он не закончится, конфиг менять нельзя.',
    );
    renderApp('/channels');
    expect(await screen.findByTestId('channel-example-film')).toBeInTheDocument();
    expect(screen.getByTestId('channels-count')).toHaveTextContent('3 канала');

    const reel = screen.getByTestId('channel-example-film');
    expect(within(reel).getByText('в работе')).toBeInTheDocument();
    expect(await within(reel).findByTestId('schedule')).toHaveTextContent(
      'окно с 02:00 на 3 ч · Europe/Moscow',
    );
    // CC-0138: пауза и ближайшая публикация — живые, из «Публикации», без номеров версий.
    expect(await within(reel).findByTestId('pause-row')).toHaveTextContent('нет · поставить');
    expect(await within(reel).findByTestId('nearest-row')).toHaveTextContent(
      'завтра, 01:00 МСК · Rink rivals',
    );
    expect(within(reel).queryByText(/\(0\.\d\)/)).not.toBeInTheDocument();

    const tech = screen.getByTestId('channel-example-tech');
    expect(within(tech).getByText('идёт батч')).toBeInTheDocument();
    expect(within(tech).getByText('закрыта, идёт батч')).toBeInTheDocument();
    expect(await within(tech).findByText('нет — батча не будет')).toBeInTheDocument();
    expect(await within(tech).findByTestId('nearest-row')).toHaveTextContent(
      'завтра, 01:00 МСК · Homepod',
    );
    const sci = screen.getByTestId('channel-example-science');
    expect(within(sci).getByText('готовится')).toBeInTheDocument();
    expect(await within(sci).findByTestId('pause-row')).toHaveTextContent(
      'на паузе, без срока · снять',
    );
    expect(
      within(sci).getByRole('link', { name: 'снять паузу в разделе «Публикация»' }),
    ).toHaveAttribute('href', '/publishing?channel=example-science');
    expect(await within(sci).findByTestId('nearest-row')).toHaveTextContent('слот не задан');
  });

  it('правка поля: проверка с ошибкой на поле → исправление → сохранение с base и тем же форматом → история → «вернуть»', async () => {
    const user = userEvent.setup();
    renderApp('/channels/example-film');
    expect(
      await screen.findByRole('heading', { name: 'ExampleFilm', level: 1 }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: /^scope,/ }));
    const score = screen.getByLabelText('min popularity score');
    await user.clear(score);
    await user.type(score, '450');
    expect(screen.getByTestId('draft-state')).toHaveTextContent('изменено полей: 1');

    await user.click(screen.getByRole('button', { name: 'Проверить' }));
    const result = await screen.findByTestId('check-result');
    expect(result).toHaveTextContent('Проверка не пройдена');
    // Русская строка фабрики (`text_ru`): поле и значение названы в ней; английская — под «подробнее».
    const ru =
      'Настройки сценариста, поле scope.min_popularity_score (сейчас 450): значение не подходит сценаристу - он его не прочтёт.';
    expect(result).toHaveTextContent(ru);
    expect(result).not.toHaveTextContent('Поле «scope → min popularity score»');
    expect(
      within(result).getByRole('button', { name: 'К полю в форме «scope → min popularity score»' }),
    ).toBeInTheDocument();
    const more = result.querySelector('details')!;
    expect(more).toHaveTextContent(
      'example-film.json.scope.min_popularity_score: must be a number from 0 to 100, got 450 (код причины: content_researcher_invalid)',
    );
    expect(score.closest('[data-field]')).toHaveAttribute('data-invalid', 'true');
    expect(score.closest('[data-field]')).toHaveTextContent(ru);

    await user.clear(score);
    await user.type(score, '50');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(await screen.findByTestId('saved')).toHaveTextContent(
      'изменено scope.min_popularity_score',
    );

    const put = channels.writes.find((w) => w.kind === 'save')!.body as Record<string, unknown>;
    expect(put.base).toBe(revisionOf(REEL_CONFIG_TEXT, REEL_STANCE_TEXT));
    expect(put.config_text).toBe(
      REEL_CONFIG_TEXT.replace('"min_popularity_score": 45', '"min_popularity_score": 50'),
    );
    expect(put).not.toHaveProperty('config');

    await user.click(screen.getByRole('tab', { name: 'История' }));
    const list = await screen.findByRole('list', { name: 'История правок' });
    const first = within(list).getAllByRole('listitem')[0]!;
    expect(first).toHaveTextContent('из центра');
    await user.click(within(first).getByRole('button', { name: 'Вернуть' }));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByRole('button', { name: 'Вернуть' }));
    expect(await screen.findByTestId('revert-done')).toHaveTextContent('Возвращено');
    await waitFor(() =>
      expect(channels.writes.at(-1)).toMatchObject({
        kind: 'revert',
        body: { base: expect.any(String) },
      }),
    );
  });

  it('идёт батч: объяснение, поля и «сохранить» закрыты', async () => {
    channels.lock(
      'example-film',
      'Идёт батч канала example-film: пока он не закончится, конфиг менять нельзя.',
    );
    const user = userEvent.setup();
    renderApp('/channels/example-film');
    expect(await screen.findByTestId('lock-banner')).toHaveTextContent(
      'Идёт батч канала example-film',
    );
    await user.click(screen.getByRole('button', { name: /^scope,/ }));
    expect(screen.getByLabelText('min popularity score')).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Сохранить' })).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('фабрика сканирует батчи: свежесть под «подробнее», тихий переспрос находит батч', async () => {
    const msg = 'Идёт батч канала example-film: пока он не закончится, конфиг менять нельзя.';
    channels.scan({ age_s: 40, checking: 1 });
    channels.lock('example-film', msg, false); // прошлый скан батча ещё не видел
    renderApp('/channels/example-film');
    expect(await screen.findByTestId('lock-fresh')).toHaveTextContent(
      'батчи: проверено 40 с назад, фабрика уже проверяет заново',
    );
    expect(screen.queryByTestId('lock-banner')).toBeNull();
    // Новый скан кончился и нашёл батч: переспрос через ~3 с показывает его без «Загружаю».
    channels.lock('example-film', msg, true);
    channels.scan({ age_s: 0.4 });
    expect(await screen.findByTestId('lock-banner')).toHaveTextContent(msg);
    expect(screen.getByTestId('lock-fresh')).toHaveTextContent(/^батчи: проверено \d с назад$/);
    expect(screen.queryByText('Загружаю канал…')).toBeNull();
  });

  it('устаревшее «открыто»: сохранение кончается 409 batch_running — по-человечески, черновик цел', async () => {
    const msg = 'Идёт батч канала example-film: пока он не закончится, конфиг менять нельзя.';
    channels.lock('example-film', msg, false);
    const user = userEvent.setup();
    renderApp('/channels/example-film');
    await user.click(await screen.findByRole('button', { name: /^scope,/ }));
    const score = screen.getByLabelText('min popularity score');
    await user.clear(score);
    await user.type(score, '50');
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    const result = await screen.findByTestId('check-result');
    expect(result).toHaveTextContent('Не сохранено: идёт батч');
    expect(result).toHaveTextContent('при записи фабрика проверила заново и нашла идущий батч');
    expect(result).toHaveTextContent('ваши правки на месте');
    // Карточка перечитана: теперь и чтение видит батч.
    expect(await screen.findByTestId('lock-banner')).toHaveTextContent(msg);
    expect(screen.getByTestId('draft-state')).toHaveTextContent('изменено полей: 1');
  });
});
