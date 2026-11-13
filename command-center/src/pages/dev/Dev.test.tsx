import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { dev } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const groups = async () => {
  await screen.findAllByTestId('dev-group');
  return screen.getAllByTestId('dev-group');
};

describe('«Разработка» (CC-0124)', () => {
  it('список: текущие вехи сверху, сделанные свёрнуты, прогресс вехи; кнопок записи нет', async () => {
    renderApp('/dev');
    expect(await screen.findByRole('heading', { level: 1, name: 'Разработка' })).toBeVisible();
    const g = await groups();
    expect(g.map((x) => x.getAttribute('data-key'))).toEqual([
      'factory|2.9',
      'center|1.1',
      'factory|3.0',
      'center|1.2',
      'factory|',
      'center|1.0',
      'factory|2.8',
    ]);
    expect(g[0]).toHaveAttribute('data-open', 'true');
    expect(g[5]).not.toHaveAttribute('data-open');
    expect(within(g[0]!).getByTestId('group-progress')).toHaveTextContent(/^сделано 4 из 10/);
    expect(within(g[0]!).getByTestId('group-checklist')).toHaveTextContent(
      /^пункты чеклистов: \d+ из \d+$/,
    );
    // Номер и диапазон в заголовке задачи — неразрывным куском (CF-0626: «CC-0001…0037»).
    expect(screen.getAllByTestId('task-id-text').map((s) => s.textContent)).toContain(
      'CC-0001…0037',
    );
    expect(within(g[0]!).getByText('текущая')).toBeVisible();
    expect(within(g[6]!).getByText('сделана 14.10')).toBeVisible();
    expect(within(g[6]!).queryAllByTestId('task-row')).toHaveLength(0);
    await userEvent.click(within(g[6]!).getByRole('button', { expanded: false }));
    expect(within(g[6]!).getAllByTestId('task-row')).toHaveLength(5);
    expect(screen.getByTestId('dev-count')).toHaveTextContent('Всего 35 задач');
    expect(screen.getByTestId('dev-sources')).toHaveTextContent('фабрика — main 9c41e07');
    expect(screen.queryByRole('button', { name: /сохранить|изменить|закрыть задачу/i })).toBeNull();
  });

  it('фильтры из адреса: статус и проект; сброс', async () => {
    renderApp('/dev?status=blocked,needs-you&project=center');
    await groups();
    await waitFor(() =>
      expect(screen.getAllByTestId('task-row').map((r) => r.getAttribute('data-id'))).toEqual([
        'CC-0150',
        'CC-0151',
      ]),
    );
    expect(screen.getByTestId('dev-count')).toHaveTextContent('Нашлось 2 задачи из 35');
    // С фильтром прогресс — по выборке, и подпись это говорит.
    expect(screen.getByTestId('group-progress')).toHaveTextContent(
      /^в выборке: 2 · сделано 0 из 2$/,
    );
    expect(screen.getByTestId('dev-project-center')).toHaveAttribute('aria-pressed', 'true');
    await userEvent.click(screen.getByTestId('dev-reset'));
    await waitFor(() => expect(screen.getByTestId('dev-count')).toHaveTextContent('Всего 35'));
  });

  it('поиск — у API, по телу; пустой результат — спокойное «ничего не нашлось»', async () => {
    renderApp('/dev');
    await groups();
    await userEvent.type(screen.getByTestId('dev-search'), 'связка');
    await waitFor(() =>
      expect(screen.getAllByTestId('task-row').map((r) => r.getAttribute('data-id'))).toEqual([
        'CC-0150',
      ]),
    );
    expect(dev.state.calls).toContain('/api/dev/tasks?q=%D1%81%D0%B2%D1%8F%D0%B7%D0%BA%D0%B0');
    await userEvent.type(screen.getByTestId('dev-search'), ' марсоход');
    expect(await screen.findByText('Ничего не нашлось')).toBeVisible();
  });

  it('карточка: тело markdown, чеклист, связанные, история; номер в тексте ведёт на карточку', async () => {
    renderApp('/dev/CC-0124');
    expect(await screen.findByTestId('task-title')).toHaveTextContent('Вкладка «Разработка»');
    expect(screen.getByTestId('task-checklist')).toHaveTextContent('сделано 2 из 4');
    const body = screen.getByTestId('task-body');
    expect(within(body).getByRole('heading', { name: 'Описание' })).toBeVisible();
    const related = screen.getByTestId('task-related');
    expect(
      within(related)
        .getAllByTestId('task-link')
        .map((a) => a.textContent),
    ).toEqual(['CC-0037', 'CF-0626']);
    expect(within(screen.getByTestId('task-history')).getAllByRole('listitem')).toHaveLength(2);
    await userEvent.click(within(body).getAllByRole('link', { name: 'CF-0626' })[0]!);
    await waitFor(() =>
      expect(screen.getByTestId('task-title')).toHaveTextContent('Командный центр'),
    );
  });

  it('сырой HTML в теле — текстом: ни script, ни img, javascript: — не ссылка', async () => {
    renderApp('/dev/CF-0635');
    const body = await screen.findByTestId('task-body');
    expect(body).toHaveTextContent('<script>alert(1)</script>');
    expect(body).toHaveTextContent('<img src=x onerror=alert(2)>');
    expect(body.querySelectorAll('script, img, a[href^="javascript"]')).toHaveLength(0);
  });

  it('неизвестная задача — «задачи нет», без повторов запроса', async () => {
    renderApp('/dev/CF-9999');
    expect(
      await screen.findByRole('heading', { level: 1, name: 'Задачи CF-9999 нет' }),
    ).toBeVisible();
    expect(dev.state.calls.filter((c) => c.endsWith('CF-9999'))).toHaveLength(1);
  });

  it('дорожная карта: вехи по порядку, текущая отмечена, задачи — ссылками со статусом', async () => {
    renderApp('/dev?view=roadmap&project=factory');
    const maps = await screen.findAllByTestId('roadmap');
    expect(maps.map((m) => m.getAttribute('data-project'))).toEqual(['factory']);
    const ms = within(maps[0]!).getAllByTestId('roadmap-milestone');
    expect(ms.map((m) => m.getAttribute('data-version'))).toEqual(['2.8', '2.9', '3.0']);
    expect(ms[1]).toHaveAttribute('data-current', 'true');
    expect(within(ms[1]!).getAllByTestId('roadmap-sprint')).toHaveLength(2);
    await waitFor(() =>
      expect(within(ms[1]!).getAllByTestId('task-status').length).toBeGreaterThan(5),
    );
    // Файл и коммит — приглушённой строкой внизу, не в заголовке.
    expect(within(maps[0]!).getByTestId('roadmap-source')).toHaveTextContent(
      'Прочитано из git: ROADMAP.md · main 9c41e07',
    );
    expect(screen.getByTestId('dev-readonly')).toHaveTextContent(
      'Только просмотр: статусы задач меняет фабрика сама, центр их не правит.',
    );
    expect(document.body).not.toHaveTextContent(/драйвер/i);
  });
});
