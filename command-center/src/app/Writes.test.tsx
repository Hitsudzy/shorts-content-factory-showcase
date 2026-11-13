// CC-0059: режим «только смотреть» — плашка в шапке, кнопки записи погашены с причиной,
// планы не спрашиваются; значок разработки; отказ `not_working_factory` посреди сессии.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { RUNNING } from '@/mocks/batches';
import { fixtures, READ_ONLY_REASON, writesModes } from '@/mocks/fixtures';
import { channels, mockGet } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const mode = (m: keyof typeof writesModes) =>
  server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes[m] }));

/** Не-GET запросы к API за тест (кроме сессии). */
function writesSent() {
  const sent: string[] = [];
  server.events.on('request:start', ({ request }) => {
    if (request.method !== 'GET') sent.push(`${request.method} ${new URL(request.url).pathname}`);
  });
  return sent;
}

const expectOff = (el: HTMLElement) => {
  expect(el).toHaveAttribute('aria-disabled', 'true');
  expect(el).toHaveAttribute('data-writes', 'off');
};

describe('CC-0059: запись только на рабочей фабрике', () => {
  afterEach(() => server.events.removeAllListeners());

  it('рабочая фабрика: ни плашки, ни значка, кнопки записи живые', async () => {
    renderApp('/batches');
    const toggle = await screen.findByTestId('switch-toggle');
    expect(toggle).not.toHaveAttribute('data-writes');
    expect(screen.queryByTestId('read-only-banner')).toBeNull();
    expect(screen.queryByTestId('writes-dev')).toBeNull();
  });

  it('только смотреть: плашка с причиной фабрики и «что это значит»', async () => {
    mode('off');
    renderApp('/');
    const banner = await screen.findByTestId('read-only-banner');
    // Простыми словами, путь к папке — только под «Что это значит».
    expect(banner).toHaveTextContent(
      'Только смотреть: это рабочая копия разработки, а не рабочая фабрика',
    );
    expect(within(banner).getByTestId('read-only-reason')).not.toHaveTextContent('/');
    const more = within(banner).getByTestId('read-only-more');
    expect(within(more).getByTestId('read-only-reason-raw')).toHaveTextContent(READ_ONLY_REASON);
    expect(more).toHaveTextContent('не на рабочей фабрике');
    expect((more as HTMLDetailsElement).open).toBe(false);
  });

  it('только смотреть: «Батчи» — рубильник, запуск, стоп, окна погашены, планов не просим', async () => {
    mode('off');
    const sent = writesSent();
    const user = userEvent.setup();
    renderApp('/batches');
    const toggle = await screen.findByTestId('switch-toggle');
    await waitFor(() => expectOff(toggle));
    await user.click(toggle);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    toggle.focus();
    expect(await screen.findByRole('tooltip')).toHaveTextContent(
      `Только смотреть: ${READ_ONLY_REASON}`,
    );

    const launch = await screen.findByTestId('launch-open');
    expectOff(launch);
    await user.click(launch);
    expect(screen.queryByRole('alertdialog')).toBeNull();

    await waitFor(() =>
      expect(
        screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === RUNNING),
      ).toBeTruthy(),
    );
    const card = screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === RUNNING)!;
    const stop = within(card).getByTestId('stop-open');
    expectOff(stop);
    await user.click(stop);
    expect(screen.queryByRole('alertdialog')).toBeNull();

    const save = (await screen.findAllByTestId('win-save'))[0]!;
    expectOff(save);
    await user.click(save);

    expect(sent).toEqual([]);
  });

  it('только смотреть: канал — «Проверить» можно, «Сохранить» и «Вернуть» погашены', async () => {
    mode('off');
    const sent = writesSent();
    const user = userEvent.setup();
    renderApp('/channels/example-film');
    await screen.findByRole('heading', { name: 'ExampleFilm', level: 1 });
    await user.click(screen.getByRole('button', { name: /^scope,/ }));
    const score = screen.getByLabelText('min popularity score');
    await user.clear(score);
    await user.type(score, '450');

    const save = screen.getByTestId('channel-save');
    expectOff(save);
    await user.click(save);
    await user.click(screen.getByRole('button', { name: 'Проверить' }));
    expect(await screen.findByTestId('check-result')).toBeInTheDocument();
    expect(sent).toEqual(['POST /api/channels/example-film/check']);

    await user.click(screen.getByRole('tab', { name: 'История' }));
    const list = await screen.findByRole('list', { name: 'История правок' });
    const reverts = within(list).getAllByRole('button', { name: 'Вернуть' });
    expect(reverts.length).toBeGreaterThan(0);
    for (const r of reverts) expectOff(r);
  });

  it('только смотреть: «Новый канал» — проверка (dry-run) работает, «Создать» погашена', async () => {
    mode('off');
    const user = userEvent.setup();
    renderApp('/channels/new');
    await user.type(await screen.findByLabelText('Идентификатор'), 'example-food');
    await user.type(screen.getByLabelText('Название'), 'ExampleFood');
    expect(await screen.findByTestId('dry-run-ok')).toBeInTheDocument();
    await user.click(screen.getByRole('button', { name: /Далее: Тематика и позиция/ }));
    await user.click(screen.getByRole('button', { name: 'Шаг 6: Проверка' }));
    await user.click(screen.getByRole('button', { name: /Далее: Создать/ }));
    const create = screen.getByTestId('create');
    expectOff(create);
    expect(screen.getByTestId('create-why')).toHaveTextContent(READ_ONLY_REASON);
    await user.click(create);
    expect(channels.writes).toEqual([]);
  });

  it('флаг разработки: значок «режим разработки», запись разрешена', async () => {
    mode('dev');
    renderApp('/batches');
    const badge = await screen.findByTestId('writes-dev');
    expect(badge).toHaveTextContent('режим разработки');
    expect(screen.queryByTestId('read-only-banner')).toBeNull();
    expect(await screen.findByTestId('switch-toggle')).not.toHaveAttribute('data-writes');
  });

  it('409 not_working_factory посреди сессии: message как есть, health перечитан, кнопки гаснут', async () => {
    const message = `Только смотреть: основной чекаут не на main (cc/api)`;
    let healthAsked = 0;
    let off = false;
    server.use(
      http.get('*/api/health', () => {
        healthAsked++;
        return HttpResponse.json(
          off
            ? {
                ...fixtures.health,
                writes: false,
                writes_reason: 'основной чекаут не на main (cc/api)',
                writes_dev: false,
              }
            : fixtures.health,
        );
      }),
      http.post('*/api/schedule/switch', () => {
        off = true;
        return HttpResponse.json(
          { message, code: 'not_working_factory', details: ['основной чекаут не на main'] },
          { status: 409 },
        );
      }),
    );
    const user = userEvent.setup();
    renderApp('/batches');
    const toggle = await screen.findByTestId('switch-toggle');
    expect(toggle).not.toHaveAttribute('data-writes');
    await user.click(toggle);
    const dialog = await screen.findByRole('alertdialog');
    await user.type(within(dialog).getByTestId('switch-note-input'), 'в чате сказал включай');
    const before = healthAsked;
    await user.click(within(dialog).getByRole('button', { name: 'Включить' }));

    expect(await within(dialog).findByTestId('refusal-message')).toHaveTextContent(message);
    await waitFor(() => expect(healthAsked).toBeGreaterThan(before));
    expect(await screen.findByTestId('read-only-banner')).toHaveTextContent(
      'основной чекаут не на main (cc/api)',
    );
    expectOff(within(dialog).getByRole('button', { name: 'Включить' }));
  });
});
