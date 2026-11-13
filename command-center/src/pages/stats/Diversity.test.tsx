import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { analytics } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const block = () => screen.findByTestId('stats-diversity');

describe('«Статистика»: разнообразие ленты (CC-0115 → CC-0108)', () => {
  it('лента канала: оси словами, доли, сырые значения и слаги — под «подробнее»', async () => {
    renderApp('/stats?channel=example-film');
    const b = await block();
    const axes = await within(b).findAllByTestId('diversity-axis');
    expect(axes.map((a) => a.dataset.axis)).toEqual([
      'fact_kind',
      'pattern',
      'rhythm',
      'hook_opener',
    ]);
    expect(
      within(b).getByText(
        // Имя канала — своим элементом (не капсится, CC-0131): подпись целиком — по тексту узла.
        (_, el) =>
          el?.classList.contains('eyebrow') === true &&
          /^Принятые ролики · .+ · последние 10 · посчитано 9 роликов$/.test(el.textContent ?? ''),
      ),
    ).toBeInTheDocument();
    const fact = within(axes[0]!).getAllByTestId('diversity-value');
    expect(fact[0]).toHaveTextContent('съёмки5 · 56 %');
    expect(within(axes[3]!).getAllByTestId('diversity-value')[0]).toHaveTextContent('не указано');
    expect(within(b).getByTestId('diversity-live')).toHaveTextContent(
      'У 1 ролика профиль прочитан из батча',
    );
    expect(b.querySelector('details')).not.toHaveAttribute('open');
    expect(within(b).getByText(/^ролики: /)).not.toBeVisible();
    expect(analytics.state.calls).toContain('/api/analytics/diversity?last=10&channel=example-film');
  });

  it('«Вся фабрика» и «Вся лента» — другой запрос', async () => {
    const user = userEvent.setup();
    renderApp('/stats?channel=example-film');
    const b = await block();
    await within(b).findAllByTestId('diversity-axis');
    // Выбранный вариант виден и по умолчанию: «канал», «последние 10».
    expect(within(b).getByTestId('diversity-channel')).toHaveAttribute('aria-pressed', 'true');
    expect(within(b).getByTestId('diversity-last')).toHaveAttribute('aria-pressed', 'true');
    expect(within(b).getByTestId('diversity-all')).toHaveAttribute('aria-pressed', 'false');
    await user.click(within(b).getByTestId('diversity-all'));
    await waitFor(() =>
      expect(within(b).getByText(/вся фабрика · последние 10 · посчитано 10/)).toBeInTheDocument(),
    );
    await user.click(within(b).getByTestId('diversity-whole'));
    await waitFor(() =>
      expect(within(b).getByText(/вся фабрика · вся лента · посчитано 12/)).toBeInTheDocument(),
    );
    expect(analytics.state.calls).toContain('/api/analytics/diversity?last=0');
    expect(within(b).getByTestId('diversity-whole')).toHaveAttribute('aria-pressed', 'true');
    expect(within(b).getByTestId('diversity-last')).toHaveAttribute('aria-pressed', 'false');
  });

  it('журнал приёмки битый — «журнал приёмки не читается», причина под «подробнее»', async () => {
    analytics.state.diversityLog = 'broken';
    renderApp('/stats?channel=example-film');
    const b = await block();
    const err = await within(b).findByTestId('diversity-log-error');
    expect(err).toHaveTextContent('Журнал приёмки не читается');
    expect(within(b).queryByTestId('diversity-axis')).not.toBeInTheDocument();
    expect(
      within(b).getByText(/^ошибка: publish\/acceptance-log.json: not JSON/),
    ).not.toBeVisible();
  });

  it('пустая лента: журнала ещё нет', async () => {
    analytics.state.diversityLog = 'missing';
    renderApp('/stats?channel=example-film');
    const b = await block();
    expect(await within(b).findByText('Принятых роликов пока нет')).toBeInTheDocument();
    expect(b).toHaveTextContent('Журнала приёмки ещё нет');
  });
});
