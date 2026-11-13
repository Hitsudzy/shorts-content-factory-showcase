// CC-0177 (по CC-0176, договор 0.77.0): вход Claude в окне «Запустить батч» — план без входа
// придерживает «да», неизвестный вход — мягкое предупреждение (и в итоге запуска), отказ
// `not_logged_in` — текст фабрики и «Проверить снова»; история — «продолжен тиком сам».
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { LOGIN_NO, LOGIN_OK, LOGIN_UNKNOWN } from '@/mocks/batchActions';
import { AUTO_RESUME } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const openLaunch = async (user: ReturnType<typeof userEvent.setup>) => {
  renderApp('/batches');
  const card = await screen.findByTestId('batches-actions');
  await user.click(within(card).getByTestId('launch-open'));
  const dialog = await screen.findByRole('alertdialog');
  await within(dialog).findByTestId('launch-why');
  return { card, dialog };
};

describe('CC-0177: вход Claude при ручном запуске', () => {
  it('вход есть — ничего лишнего: ни строки входа, ни «Проверить снова»', async () => {
    batches.closeAll();
    const user = userEvent.setup();
    const { dialog } = await openLaunch(user);
    expect(within(dialog).queryByTestId('launch-login')).toBeNull();
    expect(within(dialog).queryByTestId('login-recheck')).toBeNull();
    expect(within(dialog).getByTestId('launch-confirm')).toBeEnabled();
  });

  it('план без входа: строка сразу, «Запустить» придержана; войти и «Проверить снова»', async () => {
    batches.closeAll();
    batches.actions.setLogin(LOGIN_NO);
    const user = userEvent.setup();
    const { dialog } = await openLaunch(user);
    const line = within(dialog).getByTestId('launch-login');
    expect(line).toHaveAttribute('data-login', 'missing');
    // на виду — слова центра, команды моноширинно и без кавычек; строка фабрики — под «подробнее»
    expect(line).toHaveTextContent(
      'Claude не залогинен. Войдите — в терминале claude, затем /login — и нажмите «Проверить снова».',
    );
    expect(Array.from(line.querySelectorAll('code')).map((c) => c.textContent)).toEqual([
      'claude',
      '/login',
    ]);
    expect(line).not.toHaveTextContent('`');
    expect(line).not.toHaveTextContent('auth status');
    expect(within(dialog).getByText(`вход claude: ${LOGIN_NO.line}`)).toBeInTheDocument();
    // защиты пройдены, но бейдж не зелёный
    const badge = within(dialog).getByText('запуск придержан: нет входа в Claude');
    expect(badge.closest('[data-tone]')).toHaveAttribute('data-tone', 'warn');
    expect(line).toHaveTextContent('нажмите «Проверить снова»');
    // защиты пройдены, но «да» придержано, без отсчёта
    expect(within(dialog).getByTestId('launch-why')).toHaveTextContent('все защиты пройдены');
    const go = within(dialog).getByTestId('launch-confirm');
    expect(go).toBeDisabled();
    expect(go).toHaveTextContent(/^Запустить$/);
    expect(within(dialog).queryByTestId('plan-life')).toBeNull();
    expect(within(dialog).queryByTestId('replan')).toBeNull();
    batches.actions.setLogin(LOGIN_OK);
    await user.click(within(dialog).getByTestId('login-recheck'));
    await waitFor(() => expect(within(dialog).getByTestId('launch-confirm')).toBeEnabled());
    expect(within(dialog).queryByTestId('launch-login')).toBeNull();
    expect(batches.actions.writes.map((w) => w.path)).toEqual(['launch/plan', 'launch/plan']);
  });

  it('вход не проверить: мягкое предупреждение, «Запустить» доступна; оно же у «Батч запущен»', async () => {
    batches.closeAll();
    batches.actions.setLogin(LOGIN_UNKNOWN);
    const user = userEvent.setup();
    const { card, dialog } = await openLaunch(user);
    const warn = within(dialog).getByTestId('launch-login');
    expect(warn).toHaveAttribute('data-login', 'unknown');
    expect(warn).toHaveTextContent(/^Вход в Claude не проверен: claude не найден$/);
    expect(within(dialog).getByTestId('launch-confirm')).toBeEnabled();
    await user.click(within(dialog).getByTestId('launch-confirm'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    const done = within(card).getByTestId('launch-done');
    expect(within(done).getByText('Батч запущен')).toBeInTheDocument();
    expect(within(done).getByTestId('launch-login-warn')).toHaveTextContent(
      'Вход в Claude не проверен: claude не найден',
    );
  });

  it('отказ «да» not_logged_in: текст фабрики без шума, токен потрачен, «Проверить снова»', async () => {
    batches.closeAll();
    const user = userEvent.setup();
    const { dialog } = await openLaunch(user);
    // вход пропал после плана
    batches.actions.setLogin(LOGIN_NO);
    await user.click(within(dialog).getByTestId('launch-confirm'));
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveAttribute('data-code', 'not_logged_in');
    expect(err).toHaveTextContent('Батч не запущен: нет входа в Claude');
    const msg = within(err).getByTestId('refusal-message');
    expect(msg).toHaveTextContent(
      'Claude не залогинен. Войдите — в терминале claude, затем /login — батч не открыт.',
    );
    expect(msg.querySelectorAll('code')).toHaveLength(2);
    expect(msg).not.toHaveTextContent('`');
    expect(msg).not.toHaveTextContent('войди');
    // бейдж — не зелёный, «Запустить» неактивна и без отсчёта
    expect(
      within(dialog).getByText('запуск придержан: нет входа в Claude').closest('[data-tone]'),
    ).toHaveAttribute('data-tone', 'warn');
    expect(within(dialog).getByTestId('launch-confirm')).toHaveTextContent(/^Запустить$/);
    // код — только под «подробнее»
    const details = within(err).getByText('Подробнее').closest('details')!;
    expect(details).not.toHaveAttribute('open');
    expect(within(details).getByText('код: not_logged_in')).toBeInTheDocument();
    expect(within(err).getByTestId('login-note')).toHaveTextContent('Подтверждение потрачено');
    expect(within(dialog).getByTestId('launch-confirm')).toBeDisabled();
    expect(within(dialog).queryByTestId('replan')).toBeNull();
    batches.actions.setLogin(LOGIN_OK);
    await user.click(within(dialog).getByTestId('login-recheck'));
    await waitFor(() => expect(within(dialog).getByTestId('launch-confirm')).toBeEnabled());
    expect(within(dialog).queryByTestId('act-error')).toBeNull();
    expect(batches.actions.writes.map((w) => w.path)).toEqual([
      'launch/plan',
      'launch',
      'launch/plan',
    ]);
  });

  it('история: resume с `auto` — «продолжен тиком сам», строка фабрики в подсказке и под «подробнее»', async () => {
    batches.setAutoResume();
    const user = userEvent.setup();
    renderApp('/batches');
    const history = await screen.findByTestId('batch-history');
    const row = await within(history).findByTestId('run-auto');
    expect(within(row).getByTestId('run-auto-badge')).toHaveTextContent('продолжен тиком сам');
    expect(within(row).getByTestId('run-auto-text')).not.toBeVisible();
    await user.click(within(row).getAllByRole('button')[0]!);
    expect(within(row).getByTestId('run-auto-text')).toHaveTextContent(
      'Батч стоял на «Исследование и сценарии»: Claude был не залогинен. Тик продолжил его сам',
    );
    expect(within(row).getByText(`фабрика: ${AUTO_RESUME.auto}`)).toBeInTheDocument();
  });

  it('история без `auto` — строк «продолжен тиком сам» нет', async () => {
    renderApp('/batches');
    const history = await screen.findByTestId('batch-history');
    await within(history).findAllByTestId('run');
    expect(within(history).queryByTestId('run-auto')).toBeNull();
  });
});
