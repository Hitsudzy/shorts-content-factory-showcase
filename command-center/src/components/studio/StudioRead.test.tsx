// CC-0120: «Прочитать Studio» — хук первого открытия за день подсвечивает кнопку в шапке
// (с CC-0151 — в окошке кнопки шапки);
// выключенный запуск — кнопка погашена с причиной, план виден; включённый — «да», опрос, итог.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { LAUNCH_OFF_WHY } from '@/mocks/studio';
import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, studio } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { ageText, outcomeTone } from './studioWords';

const FIRST = 'center-first-open-of-day';
type User = ReturnType<typeof userEvent.setup>;

/** CC-0151: блок хука первого открытия — в окошке кнопки «Пора прочитать Studio» в шапке. */
async function banner(user: User) {
  if (!screen.queryByTestId('studio-pop'))
    await user.click(await screen.findByTestId('studio-pop-open'));
  return within(await screen.findByTestId('studio-pop')).getByTestId('studio-due');
}

async function readFlow(user: User, box: HTMLElement) {
  await user.click(within(box).getByTestId('studio-read-open'));
  const dialog = await screen.findByRole('alertdialog');
  await within(dialog).findByTestId('studio-plan');
  await waitFor(() => expect(within(dialog).getByTestId('studio-read-confirm')).toBeEnabled());
  await user.click(within(dialog).getByTestId('studio-read-confirm'));
  await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
}

describe('CC-0120: чтение Studio по кнопке', () => {
  it('слова: возраст чтения и тон итога', () => {
    expect(ageText(null)).toBe('Studio ещё ни разу не читали');
    expect(ageText(0.4)).toBe('последнее чтение меньше часа назад');
    expect(ageText(30)).toBe('последнее чтение 30 ч назад');
    expect(ageText(72)).toBe('последнее чтение 3 дн назад');
    expect(outcomeTone('read')).toBe('ok');
    expect(outcomeTone('login_needed')).toBe('warn');
    expect(outcomeTone('error')).toBe('danger');
  });

  it('не пора — в шапке ничего; хук первого открытия спрошен один раз', async () => {
    renderApp('/');
    await waitFor(() => expect(studio.calls).toContain(`GET due?hook=${FIRST}`));
    expect(screen.queryByTestId('studio-due')).toBeNull();
    expect(screen.queryByTestId('studio-pop-open')).toBeNull();
    expect(studio.calls.filter((c) => c === `GET due?hook=${FIRST}`)).toHaveLength(1);
  });

  it('пора, запуск выключен: кнопка погашена с причиной, план виден, «да» недоступно', async () => {
    studio.setDue(true, [FIRST]);
    const user = userEvent.setup();
    renderApp('/');
    const box = await banner(user);
    expect(within(box).getByTestId('studio-why')).toHaveTextContent('Studio не читали 30 ч');
    expect(within(box).getByTestId('studio-hook')).toHaveTextContent(
      'первое открытие центра за день',
    );
    expect(within(box).getByTestId('studio-read-open')).toBeDisabled();
    expect(within(box).getByTestId('studio-launch-off')).toHaveTextContent(LAUNCH_OFF_WHY);

    await user.click(within(box).getByTestId('studio-read-plan'));
    const dialog = await screen.findByRole('alertdialog');
    await within(dialog).findByTestId('studio-plan');
    expect(within(dialog).getAllByTestId('studio-plan-channel')).toHaveLength(3);
    expect(within(dialog).getByTestId('studio-plan-chrome')).toHaveTextContent(
      'Только чтение в вашем Chrome',
    );
    expect(within(dialog).getByTestId('studio-plan-off')).toHaveTextContent(
      'первый запуск делается вместе с вами',
    );
    expect(within(dialog).getByTestId('studio-read-confirm')).toBeDisabled();
    expect(studio.calls).not.toContain('POST read');
  });

  it('запуск включён: «да» → «читается» → «прочитано», полоса гаснет после «Скрыть»', async () => {
    studio.setDue(true, [FIRST]);
    studio.setLaunch(true);
    const user = userEvent.setup();
    renderApp('/');
    const box = await banner(user);
    await readFlow(user, box);
    expect(await screen.findByTestId('studio-reading')).toBeInTheDocument();
    const result = await screen.findByTestId('studio-result');
    expect(result).toHaveAttribute('data-code', 'read');
    // Слово итога — на значке, строка его не повторяет.
    expect(result).toHaveTextContent('Studio: прочитано');
    expect(within(result).getByTestId('studio-result-line')).not.toHaveTextContent(/^прочитано/);
    expect(studio.calls).toContain('POST read');
    await user.click(within(result).getByTestId('studio-result-close'));
    await waitFor(() => expect(screen.queryByTestId('studio-due')).toBeNull());
    expect(screen.queryByTestId('studio-pop-open')).toBeNull();
  });

  it.each([
    ['no_extension', 'расширение не подключено'],
    ['login_needed', 'нужен вход'],
    ['error', 'ошибка'],
  ] as const)('исход %s — одной строкой «%s»', async (code, word) => {
    studio.setDue(true, [FIRST]);
    studio.setLaunch(true);
    studio.setOutcome(code);
    studio.state.pollsToDone = 0;
    const user = userEvent.setup();
    renderApp('/');
    await readFlow(user, await banner(user));
    const result = await screen.findByTestId('studio-result');
    expect(result).toHaveAttribute('data-code', code);
    expect(result).toHaveTextContent(`Studio: ${word}`);
    expect(within(result).getByTestId('studio-result-line')).not.toHaveTextContent(
      new RegExp(`^${word}`),
    );
    // Что сделать — один раз; «Подробнее» у полосы — одно (ревью экранов).
    if (code !== 'error')
      expect(within(result).queryByTestId('studio-result-next')).not.toBeInTheDocument();
    expect(within(screen.getByTestId('studio-due')).getAllByText('Подробнее')).toHaveLength(1);
    // Не прочитано — после «Скрыть» итога нет, а «пора» остаётся (перечитано после итога).
    await user.click(within(result).getByTestId('studio-result-close'));
    await waitFor(() => expect(screen.queryByTestId('studio-result')).toBeNull());
    expect(await screen.findByTestId('studio-due')).toHaveAttribute('data-due', 'true');
    expect(studio.calls.filter((c) => c === `GET due?hook=${FIRST}`).length).toBeGreaterThan(1);
  });

  it('отказ фабрики в плане — её словами, «да» недоступно', async () => {
    studio.setDue(true, [FIRST]);
    studio.setLaunch(true);
    studio.state.refuse = 'no_claude';
    const user = userEvent.setup();
    renderApp('/');
    const box = await banner(user);
    await user.click(within(box).getByTestId('studio-read-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('studio-plan-why')).toHaveTextContent(
      'Claude Code не найден',
    );
    expect(within(dialog).getByTestId('studio-read-confirm')).toBeDisabled();
  });

  it('не рабочая фабрика: хук первого открытия не спрашивается вовсе', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    studio.setDue(true);
    renderApp('/');
    await screen.findByTestId('read-only-banner');
    expect(studio.calls).not.toContain(`GET due?hook=${FIRST}`);
    expect(screen.queryByTestId('studio-due')).toBeNull();
  });

  it('409 «не рабочая фабрика» на хуке — тихо: ни полосы, ни ошибки', async () => {
    studio.setDue(true);
    studio.state.readOnly = true;
    renderApp('/');
    await waitFor(() => expect(studio.calls).toContain(`GET due?hook=${FIRST}`));
    expect(screen.queryByTestId('studio-due')).toBeNull();
    expect(screen.queryByRole('alert')).toBeNull();
  });
});
