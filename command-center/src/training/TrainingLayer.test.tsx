// Плашка и панель тренировки на всём приложении: демо-сервер — тот же обработчик, что в браузере.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { TASKS_STORAGE_KEY } from './checklist';
import { checklist, demoHandler, demoStore } from './demo';
import { resetTrainingState } from './mode';
import { PANEL_STORAGE_KEY } from './TrainingLayer';

beforeEach(() => {
  server.use(demoHandler);
  demoStore.reset();
  localStorage.removeItem(PANEL_STORAGE_KEY);
  resetTrainingState({ mode: 'training', demo: { stop: async () => {} } });
  // Страницу «держит» service worker демо-сервера — иначе сторож клиента не пустит запрос.
  Object.defineProperty(navigator, 'serviceWorker', {
    configurable: true,
    value: { controller: { scriptURL: `${window.location.origin}/mockServiceWorker.js` } },
  });
});
afterEach(() => {
  resetTrainingState();
  Reflect.deleteProperty(navigator, 'serviceWorker');
});

const task = (id: string) =>
  screen.getAllByTestId('training-task').find((t) => t.dataset.task === id)!;

describe('тренировка на экране', () => {
  it('плашка на каждом экране; панель: двенадцать заданий, отметки сами', async () => {
    const user = userEvent.setup();
    renderApp('/questions');
    const banner = await screen.findByRole('region', { name: 'Тренировка' });
    expect(within(banner).getByTestId('training-banner-text')).toHaveTextContent(
      'Тренировка — это демо, фабрика не трогается',
    );
    expect(within(banner).getByTestId('training-exit')).toHaveTextContent('Выйти из тренировки');
    const panel = await screen.findByTestId('training-panel');
    expect(within(panel).getAllByTestId('training-task')).toHaveLength(12);
    expect(within(panel).getByTestId('training-count')).toHaveTextContent('0 из 12');

    // Ответ на вопрос в демо — задание отмечено само, тост сказал какое.
    const send = (await screen.findAllByTestId('answer-send'))[0]!;
    const card = send.closest('[data-testid="question"]') as HTMLElement;
    await user.type(within(card).getByTestId('answer-text'), 'Берём второй вариант');
    await user.click(send);
    await waitFor(() => expect(task('answer')).toHaveAttribute('data-done', 'yes'));
    expect(within(panel).getByTestId('training-count')).toHaveTextContent('1 из 12');
    expect(screen.getByTestId('training-last')).toHaveTextContent(
      'Задание выполнено: Ответить на вопрос',
    );
    expect(JSON.parse(localStorage.getItem(TASKS_STORAGE_KEY)!)).toEqual(['answer']);
  });

  it('рычаги: «промотать время» и «отказ» ждут следующего «да»; «начать заново» — всё сначала', async () => {
    const user = userEvent.setup();
    renderApp('/');
    const panel = await screen.findByTestId('training-panel');
    await user.click(within(panel).getByTestId('training-expire'));
    expect(within(panel).getByTestId('training-expire')).toBeDisabled();
    expect(panel).toHaveTextContent('Следующее «да» опоздает');
    await user.click(within(panel).getByTestId('training-refuse'));
    expect(panel).toHaveTextContent('следующее «да» на «Публикации» получит отказ');
    checklist.record({ method: 'POST', path: '/api/requests', status: 200, code: null });
    await waitFor(() => expect(task('ask')).toHaveAttribute('data-done', 'yes'));

    await user.click(within(panel).getByTestId('training-reset'));
    expect(task('ask')).toHaveAttribute('data-done', 'no');
    expect(within(panel).getByTestId('training-expire')).toBeEnabled();
    expect(within(panel).getByTestId('training-refuse')).toBeEnabled();
  });

  it('панель сворачивается и помнит это; кнопка «Задания» в плашке открывает её', async () => {
    const user = userEvent.setup();
    const first = renderApp('/');
    await user.click(await screen.findByTestId('training-collapse'));
    expect(screen.queryByTestId('training-panel')).toBeNull();
    expect(localStorage.getItem(PANEL_STORAGE_KEY)).toBe('closed');
    first.unmount();
    renderApp('/');
    const toggle = await screen.findByTestId('training-tasks-toggle');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByTestId('training-panel')).toBeNull();
    await user.click(toggle);
    expect(await screen.findByTestId('training-panel')).toBeVisible();
  });

  it('вне тренировки — ни плашки, ни панели; в оглавлении тура — «Начать тренировку»', async () => {
    resetTrainingState();
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Обучение' }));
    expect(screen.getByTestId('tour-practice')).toHaveTextContent('Начать тренировку');
    expect(screen.queryByTestId('training-banner')).toBeNull();
    expect(screen.queryByTestId('training-panel')).toBeNull();
  });

  it('тренировка не запустилась — строка: центр открыт с живыми данными', async () => {
    resetTrainingState({ mode: 'live', failed: 'демо-сервер не взял страницу под себя' });
    renderApp('/');
    expect(await screen.findByTestId('training-failed')).toHaveTextContent(
      'Тренировка не запустилась: демо-сервер не взял страницу под себя. Центр открыт с живыми данными.',
    );
  });
});
