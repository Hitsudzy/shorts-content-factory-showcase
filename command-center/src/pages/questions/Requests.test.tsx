// «Просьбы» в табе «Вопросы» (CC-0019): переключатель в адресе, статусы словами, ответ и
// доставка в Telegram, «закрыть» у отвеченной, «отменить» у открытой/взятой с одним
// подтверждением, история; отказ — строкой фабрики; «только смотреть» — кнопки погашены.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, requests } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const card = (rid: string) => screen.getAllByTestId('request').find((c) => c.dataset.rid === rid)!;

/** Видимый текст без «подробнее»: номера и JSON контекста живут только там. */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

async function open() {
  const user = userEvent.setup();
  renderApp('/questions?view=requests');
  await screen.findByTestId('answered-requests');
  return user;
}

describe('CC-0019: просьбы в табе «Вопросы»', () => {
  it('переключатель: «Просьбы» со счётчиком ответов, выбор — в адресе', async () => {
    const user = userEvent.setup();
    renderApp('/questions');
    await screen.findByTestId('open-questions');
    const sw = screen.getByTestId('view-requests');
    expect(sw).toHaveAttribute('aria-pressed', 'false');
    await waitFor(() => expect(sw.querySelector('[data-slot="count"]')).toHaveTextContent('2'));
    await user.click(sw);
    expect(await screen.findByTestId('answered-requests')).toBeInTheDocument();
    expect(sw).toHaveAttribute('aria-pressed', 'true');
    expect(screen.queryByTestId('open-questions')).toBeNull();
    await user.click(screen.getByTestId('view-questions'));
    expect(await screen.findByTestId('open-questions')).toBeInTheDocument();
  });

  it('сверху — с ответом, ниже — ждут оператора; статус словами, ответ, Telegram', async () => {
    await open();
    const answered = within(screen.getByTestId('answered-requests'));
    expect(answered.getAllByTestId('request').map((c) => c.dataset.rid)).toEqual(['R4', 'R3']);
    const pending = within(screen.getByTestId('pending-requests'));
    expect(pending.getAllByTestId('request').map((c) => c.dataset.rid)).toEqual(['R6', 'R5']);
    const statuses = screen
      .getAllByTestId('request')
      .map((c) => c.querySelector('[data-slot="status"]')?.textContent);
    expect(statuses).toEqual(['отвечена', 'отвечена', 'открыта', 'взята оператором']);
    const r3 = within(card('R3'));
    expect(r3.getByTestId('request-answer')).toHaveTextContent('Трек короче ролика');
    expect(r3.getByTestId('request-notify')).toHaveAttribute('data-notify', 'sent');
    expect(r3.getByTestId('request-notify')).toHaveTextContent('дошёл в Telegram');
    await waitFor(() =>
      expect(r3.getByTestId('request-context')).toHaveTextContent(
        'Откуда: Ролики · канал ExampleTech · батч 09.10, 06:00 · ролик «RTX 5090 melts»',
      ),
    );
    expect(within(card('R4')).getByTestId('request-notify')).toHaveTextContent(
      'в Telegram не дошёл',
    );
    expect(within(card('R5')).getByTestId('request-taken')).toHaveTextContent(
      'Оператор взял в работу',
    );
    // Кнопки по состоянию: «Закрыть» — у отвеченной, «Отменить…» — у открытой и взятой.
    expect(r3.getByTestId('request-close')).toBeInTheDocument();
    expect(r3.queryByTestId('request-cancel')).toBeNull();
    expect(within(card('R5')).getByTestId('request-cancel')).toBeInTheDocument();
    expect(within(card('R6')).queryByTestId('request-close')).toBeNull();
    // Номера и JSON — только под «подробнее».
    const text = plainText(screen.getByRole('main'));
    expect(text).not.toMatch(/\bR\d\b/);
    expect(text).not.toContain('"screen"');
    expect(within(card('R3')).getByTestId('request-context-json')).toHaveTextContent('"batch"');
  });

  it('«Закрыть» — просьба уходит в историю, счётчик падает', async () => {
    const user = await open();
    await user.click(within(card('R3')).getByTestId('request-close'));
    expect(await screen.findByText('Просьба закрыта')).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(screen.getByTestId('answered-requests')).getAllByTestId('request'),
      ).toHaveLength(1),
    );
    const hist = within(screen.getByTestId('requests-history'));
    await waitFor(() =>
      expect(hist.getAllByTestId('request-history-item')[0]).toHaveAttribute('data-rid', 'R3'),
    );
    expect(hist.getAllByTestId('request-history-state')[0]).toHaveTextContent('Закрыта');
    expect(requests.writes).toEqual([{ path: '/api/requests/R3/close', body: null }]);
    await waitFor(() =>
      expect(
        screen.getByTestId('view-requests').querySelector('[data-slot="count"]'),
      ).toHaveTextContent('1'),
    );
  });

  it('«Отменить…» — одно подтверждение; отказ — строкой фабрики в окне', async () => {
    const user = await open();
    requests.next = { status: 409, code: 'cancel_answered' };
    await user.click(within(card('R6')).getByTestId('request-cancel'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Отменить просьбу?');
    await user.click(within(dialog).getByTestId('request-cancel-confirm'));
    const err = await within(dialog).findByTestId('cancel-error');
    expect(err).toHaveTextContent('На просьбу R6 уже ответили');
    await user.click(within(dialog).getByTestId('request-cancel-confirm'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(await screen.findByText('Просьба отменена')).toBeInTheDocument();
    await waitFor(() =>
      expect(
        within(screen.getByTestId('requests-history'))
          .getAllByTestId('request-history-item')
          .map((x) => x.dataset.rid),
      ).toEqual(['R6', 'R2', 'R1']),
    );
  });

  it('«только смотреть»: «Закрыть» и «Отменить…» погашены, записей нет', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const user = await open();
    const close = within(card('R3')).getByTestId('request-close');
    await waitFor(() => expect(close).toHaveAttribute('data-writes', 'off'));
    await user.click(close);
    const cancel = within(card('R6')).getByTestId('request-cancel');
    expect(cancel).toHaveAttribute('aria-disabled', 'true');
    await user.click(cancel);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(requests.writes).toEqual([]);
  });

  it('очередь пуста — так и сказано', async () => {
    requests.requests = [];
    renderApp('/questions?view=requests');
    expect(await screen.findByText('Просьб к оператору нет')).toBeInTheDocument();
    expect(await screen.findByText('Закрытых просьб пока нет')).toBeInTheDocument();
  });
});
