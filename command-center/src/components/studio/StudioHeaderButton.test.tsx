// CC-0151: «Пора прочитать Studio» — кнопка в шапке вместо полосы: видна при том же условии,
// что и полоса раньше; окошко открывается и закрывается по Esc, клику вне и крестику, фокус
// уходит в окошко и возвращается на кнопку; «да» чтения — прежнее окно подтверждения.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { studio } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const FIRST = 'center-first-open-of-day';
const opener = () => screen.findByRole('button', { name: 'Пора прочитать Studio' });

describe('CC-0151: кнопка «Пора прочитать Studio» в шапке', () => {
  it('не пора — кнопки нет, полосы под шапкой нет', async () => {
    renderApp('/');
    await waitFor(() => expect(studio.calls).toContain(`GET due?hook=${FIRST}`));
    expect(screen.queryByTestId('studio-pop-open')).toBeNull();
    expect(screen.queryByTestId('studio-banner')).toBeNull();
  });

  it('пора — кнопка в шапке с меткой, окошко закрыто, страница без полосы', async () => {
    studio.setDue(true, [FIRST]);
    renderApp('/');
    const btn = await opener();
    expect(btn.closest('header')).not.toBeNull();
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    expect(btn).toHaveAttribute('aria-haspopup', 'dialog');
    expect(within(btn).getByTestId('studio-pop-mark')).toBeInTheDocument();
    expect(screen.queryByTestId('studio-pop')).toBeNull();
    expect(screen.queryByTestId('studio-due')).toBeNull();
    expect(screen.queryByTestId('studio-banner')).toBeNull();
  });

  it('нажатие — окошко с причиной, поводом и кнопкой чтения; фокус в окошке', async () => {
    studio.setDue(true, [FIRST]);
    const user = userEvent.setup();
    renderApp('/');
    const btn = await opener();
    await user.click(btn);
    const pop = await screen.findByRole('dialog', { name: 'Пора прочитать Studio' });
    expect(btn).toHaveAttribute('aria-expanded', 'true');
    expect(btn.getAttribute('aria-controls')).toBe(pop.id);
    expect(pop).toHaveFocus();
    expect(within(pop).getByTestId('studio-why')).toHaveTextContent('Studio не читали 30 ч');
    // Возраст — только в строке фабрики, второй строкой — повод (ревью CC-0151).
    expect(within(pop).queryByTestId('studio-age')).toBeNull();
    expect(within(pop).getByRole('region', { name: 'Почему пора' })).not.toHaveTextContent(
      /последнее чтение/i,
    );
    expect(within(pop).getByTestId('studio-hook')).toHaveTextContent(
      /^Повод: первое открытие центра за день$/,
    );
    expect(within(pop).getByTestId('studio-read-open')).toBeInTheDocument();
  });

  it.each([
    ['Esc', async (user: ReturnType<typeof userEvent.setup>) => user.keyboard('{Escape}')],
    [
      'крестик',
      async (user: ReturnType<typeof userEvent.setup>) =>
        user.click(screen.getByRole('button', { name: 'Закрыть' })),
    ],
    [
      'клик вне окошка',
      async (user: ReturnType<typeof userEvent.setup>) => user.click(document.body),
    ],
    [
      'повторное нажатие кнопки',
      async (user: ReturnType<typeof userEvent.setup>) =>
        user.click(screen.getByTestId('studio-pop-open')),
    ],
  ] as const)('закрывается: %s — фокус на кнопке', async (_, act) => {
    studio.setDue(true, [FIRST]);
    const user = userEvent.setup();
    renderApp('/');
    const btn = await opener();
    await user.click(btn);
    await screen.findByRole('dialog', { name: 'Пора прочитать Studio' });
    await act(user);
    await waitFor(() => expect(screen.queryByTestId('studio-pop')).toBeNull());
    expect(btn).toHaveAttribute('aria-expanded', 'false');
    expect(btn).toHaveFocus();
  });

  it('Esc в окне подтверждения закрывает только его, окошко остаётся', async () => {
    studio.setDue(true, [FIRST]);
    studio.setLaunch(true);
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await opener());
    const pop = await screen.findByTestId('studio-pop');
    await user.click(within(pop).getByTestId('studio-read-open'));
    const confirm = await screen.findByRole('alertdialog');
    await within(confirm).findByTestId('studio-plan');
    // Подтверждение не заполнено заранее: «да» — только по нажатию.
    expect(studio.calls).not.toContain('POST read');
    await user.keyboard('{Escape}');
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(screen.getByTestId('studio-pop')).toBeInTheDocument();
  });

  it('«да» из окошка — чтение идёт, итог в окошке; «Скрыть» убирает кнопку', async () => {
    studio.setDue(true, [FIRST]);
    studio.setLaunch(true);
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await opener());
    const pop = await screen.findByTestId('studio-pop');
    await user.click(within(pop).getByTestId('studio-read-open'));
    const confirm = await screen.findByRole('alertdialog');
    await within(confirm).findByTestId('studio-plan');
    await waitFor(() => expect(within(confirm).getByTestId('studio-read-confirm')).toBeEnabled());
    await user.click(within(confirm).getByTestId('studio-read-confirm'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(screen.getByTestId('studio-pop')).toBeInTheDocument();
    const result = await within(pop).findByTestId('studio-result');
    expect(result).toHaveAttribute('data-code', 'read');
    expect(studio.calls).toContain('POST read');
    await user.click(within(result).getByTestId('studio-result-close'));
    await waitFor(() => expect(screen.queryByTestId('studio-pop-open')).toBeNull());
    expect(screen.queryByTestId('studio-pop')).toBeNull();
  });
});
