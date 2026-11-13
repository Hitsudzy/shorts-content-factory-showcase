// CC-0120: хуки «запуск батча» (окно запуска) и «загрузка» (карточка загрузки) — только
// подсвечивают «Прочитать Studio»; запуск батча Studio не ждёт.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { REEL } from '@/mocks/publish';
import { studio } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

describe('CC-0120: хуки действий подсвечивают «Прочитать Studio»', () => {
  it('окно запуска батча: пора — подсвеченная кнопка с причиной; запуск по-прежнему доступен', async () => {
    studio.setDue(true, ['batch-start']);
    const user = userEvent.setup();
    renderApp('/batches');
    await user.click(await screen.findByTestId('launch-open'));
    const dialog = await screen.findByRole('alertdialog');
    const due = await within(dialog).findByTestId('studio-due');
    expect(due).toHaveAttribute('data-hook', 'batch-start');
    expect(within(due).getByTestId('studio-hook')).toHaveTextContent('запуск батча');
    expect(within(due).getByTestId('studio-age')).toHaveTextContent('30 ч назад');
    expect(studio.calls).toContain('GET due?hook=batch-start');
    await within(dialog).findByTestId('launch-plan');
    // Чтение Studio не трогается само.
    expect(studio.calls).not.toContain('POST plan');
  });

  it('окно запуска: не пора — блока нет; хук спрошен только при открытии окна', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    await screen.findByTestId('launch-open');
    expect(studio.calls).not.toContain('GET due?hook=batch-start');
    await user.click(screen.getByTestId('launch-open'));
    const dialog = await screen.findByRole('alertdialog');
    await waitFor(() => expect(studio.calls).toContain('GET due?hook=batch-start'));
    expect(within(dialog).queryByTestId('studio-due')).toBeNull();
  });

  it('карточка загрузки: пора — подсвеченная кнопка с причиной и возрастом чтения', async () => {
    studio.setDue(true, ['upload']);
    renderApp(`/publishing?channel=${REEL}`);
    const card = await screen.findByTestId('upload-writes');
    const due = await within(card).findByTestId('studio-due');
    expect(due).toHaveAttribute('data-hook', 'upload');
    expect(within(due).getByTestId('studio-why')).toHaveTextContent('пора проверить досмотры');
    expect(within(due).getByTestId('studio-read-open')).toBeDisabled();
  });
});
