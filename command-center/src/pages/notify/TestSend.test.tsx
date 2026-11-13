// Пробное сообщение (CC-0115 шаг 3, CC-0109): план — каналы по имени и что сделал бы сухой прогон,
// ничего не уходит; «да» набирает пользователь — сообщение ушло, ответ по каждому каналу; каналы
// сменились — «посмотрите план заново»; токен устарел — «План устарел».
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { notify } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

async function openPlan() {
  const user = userEvent.setup();
  renderApp('/notifications');
  const box = await screen.findByTestId('test-send');
  await user.click(within(box).getByTestId('test-send-open'));
  const dialog = await screen.findByRole('alertdialog');
  await within(dialog).findByTestId('plan-head');
  return { user, box, dialog };
}

describe('уведомления: пробное сообщение (CC-0115 шаг 3)', () => {
  it('план ничего не шлёт → «да» набрано → отправлено, ответ по каналам', async () => {
    notify.state.testAnswers.telegram = 'error: HTTP 502 Bad Gateway';
    const { user, box, dialog } = await openPlan();
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('можно отправить');
    const rows = within(dialog).getAllByTestId('test-plan-channel');
    expect(rows.map((r) => r.dataset.name)).toEqual(['log', 'macos', 'telegram']);
    expect(rows[2]).toHaveTextContent('отправит с машины');
    expect(within(dialog).getByTestId('test-plan-text')).toHaveTextContent(
      'проверка уведомлений фабрики',
    );
    expect(notify.state.testSent).toEqual([]);
    const confirm = within(dialog).getByTestId('test-send-confirm');
    expect(within(dialog).getByTestId('test-send-yes')).toHaveValue('');
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByTestId('test-send-yes'), 'да');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    const done = await within(box).findByTestId('test-send-done');
    expect(done).toHaveTextContent('Отправлено, но не дошло');
    expect(within(done).getByTestId('test-send-results')).toHaveTextContent('ошибка');
    expect(notify.state.testSent).toHaveLength(1);
    expect(notify.state.journal.at(-1)!.kind).toBe('test');
  });

  it('каналы сменились с плана — ничего не отправлено, «посмотрите план заново»', async () => {
    const { user, dialog } = await openPlan();
    notify.state.check.preview = notify.state.check.preview.slice(0, 2);
    await user.type(within(dialog).getByTestId('test-send-yes'), 'да');
    await user.click(within(dialog).getByTestId('test-send-confirm'));
    await waitFor(() =>
      expect(within(dialog).getByTestId('test-send-plan')).toHaveTextContent(
        /изменилось|изменились/,
      ),
    );
    expect(notify.state.testSent).toEqual([]);
  });

  it('отказ шины словами; токен устарел — «План устарел»', async () => {
    notify.state.next = 'factory_broken';
    const { user, dialog } = await openPlan();
    await user.type(within(dialog).getByTestId('test-send-yes'), 'да');
    await user.click(within(dialog).getByTestId('test-send-confirm'));
    expect(await within(dialog).findByTestId('act-error')).toHaveTextContent('Фабрика ответила');
    await user.click(within(dialog).getByTestId('replan'));
    await within(dialog).findByTestId('test-send-yes');
    notify.expireTokens();
    await user.type(within(dialog).getByTestId('test-send-yes'), 'да');
    await user.click(within(dialog).getByTestId('test-send-confirm'));
    await waitFor(() =>
      expect(within(dialog).getByTestId('test-send-plan')).toHaveTextContent(/устарел/),
    );
    expect(notify.state.testSent).toEqual([]);
  });

  it('ни один внешний канал не готов — план это говорит', async () => {
    notify.state.check.preview = notify.state.check.preview.map((p) =>
      p.external ? { ...p, ready: false, skip_reason: 'NOTIFY_TELEGRAM_CHAT is not set' } : p,
    );
    const { dialog } = await openPlan();
    expect(within(dialog).getByTestId('test-plan-note')).toHaveTextContent(
      'Ни один внешний канал не готов',
    );
    expect(within(dialog).getAllByTestId('test-plan-channel')[2]).toHaveTextContent('пропустит');
  });
});
