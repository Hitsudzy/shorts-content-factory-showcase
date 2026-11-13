// Тур «Обучение» в приложении (CC-0072): вход с главной и из шапки, оглавление, шаги,
// клавиатура, прогресс в браузере. Тур только показывает — ни одного запроса, кроме чтения.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { tourTiming } from './engine';
import { TOUR_STORAGE_KEY } from './progress';
import { STEPS, sectionStart, stepLabel } from './steps';

const writes: string[] = [];
const onRequest = ({ request }: { request: Request }) => {
  if (request.method !== 'GET') writes.push(`${request.method} ${request.url}`);
};

beforeEach(() => {
  localStorage.clear();
  writes.length = 0;
  server.events.on('request:start', onRequest);
});
afterEach(() => {
  server.events.removeListener('request:start', onRequest);
  expect(writes, 'тур не пишет').toEqual([]);
});

const card = () => screen.getByTestId('tour-card');
const stepOf = () => card().getAttribute('data-step');

describe('CC-0072: тур «Обучение»', () => {
  it('строка на главной запускает тур с первого шага; фокус — на подсказке', async () => {
    const user = userEvent.setup();
    renderApp('/');
    const invite = await screen.findByTestId('tour-invite');
    expect(invite).toHaveTextContent('Пройдите короткое обучение');
    await user.click(within(invite).getByRole('button', { name: 'Начать обучение' }));
    expect(stepOf()).toBe(STEPS[0]!.id);
    expect(screen.getByTestId('tour-count')).toHaveTextContent(stepLabel(0));
    expect(screen.getByRole('dialog', { name: STEPS[0]!.title })).toBe(card());
    await waitFor(() => expect(card()).toHaveFocus());
  });

  it('«Дальше», «Назад», стрелки; Esc закрывает и возвращает фокус на кнопку', async () => {
    const user = userEvent.setup();
    renderApp('/');
    const open = await screen.findByRole('button', { name: 'Обучение' });
    await user.click(open);
    await user.click(within(screen.getByTestId('tour-contents')).getByTestId('tour-restart'));
    expect(screen.getByTestId('tour-back')).toBeDisabled();
    await user.click(screen.getByTestId('tour-next'));
    expect(stepOf()).toBe(STEPS[1]!.id);
    await user.keyboard('{ArrowRight}');
    expect(stepOf()).toBe(STEPS[2]!.id);
    await user.keyboard('{ArrowLeft}');
    await user.click(screen.getByTestId('tour-back'));
    expect(stepOf()).toBe(STEPS[0]!.id);
    await user.keyboard('{Escape}');
    expect(screen.queryByTestId('tour')).toBeNull();
    await waitFor(() => expect(open).toHaveFocus());
  });

  it('Tab не уходит из подсказки', async () => {
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByTestId('tour-invite-start'));
    const layer = screen.getByTestId('tour');
    for (let i = 0; i < 8; i++) {
      await user.tab();
      expect(layer.contains(document.activeElement)).toBe(true);
    }
    await user.tab({ shift: true });
    expect(layer.contains(document.activeElement)).toBe(true);
  });

  it('оглавление: любой раздел, «Тренировка» — вход, прогресс помнится, «Пройти заново»', async () => {
    const user = userEvent.setup();
    const first = renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Обучение' }));
    const menu = screen.getByTestId('tour-contents');
    expect(within(menu).getAllByTestId('tour-section')).toHaveLength(7);
    expect(within(menu).getByTestId('tour-practice')).toHaveTextContent(
      'ТренировкаНачать тренировку',
    );
    expect(within(menu).getByTestId('tour-practice')).toHaveAttribute('data-training', 'off');
    await user.click(
      within(menu)
        .getAllByTestId('tour-section')
        .find((b) => b.dataset.section === 'basics')!,
    );
    expect(stepOf()).toBe(STEPS[sectionStart('basics')]!.id);
    await user.click(screen.getByTestId('tour-next'));
    await user.click(screen.getByTestId('tour-skip'));
    expect(screen.queryByTestId('tour')).toBeNull();
    const saved = JSON.parse(localStorage.getItem(TOUR_STORAGE_KEY)!) as { last: string };
    expect(saved.last).toBe(STEPS[sectionStart('basics') + 1]!.id);
    first.unmount();

    // Новый заход: строки на главной нет, оглавление предлагает продолжить.
    renderApp('/');
    await screen.findByTestId('attention');
    expect(screen.queryByTestId('tour-invite')).toBeNull();
    await user.click(screen.getByRole('button', { name: 'Обучение' }));
    const again = screen.getByTestId('tour-contents');
    expect(within(again).getByTestId('tour-resume')).toHaveTextContent(
      `Продолжить: Общие приёмы, шаг ${stepLabel(sectionStart('basics') + 1)}`,
    );
    expect(
      within(again)
        .getAllByTestId('tour-section')
        .find((b) => b.dataset.section === 'basics'),
    ).toHaveTextContent(`2 из ${STEPS.filter((s) => s.section === 'basics').length}`);
    await user.click(within(again).getByTestId('tour-restart'));
    expect(stepOf()).toBe(STEPS[0]!.id);
    const restarted = JSON.parse(localStorage.getItem(TOUR_STORAGE_KEY)!) as { seen: string[] };
    expect(restarted.seen).toEqual([STEPS[0]!.id]);
  });

  it('последний шаг предлагает «Начать тренировку»', async () => {
    localStorage.setItem(
      TOUR_STORAGE_KEY,
      JSON.stringify({ seen: [], last: STEPS.at(-2)!.id, finished: false, dismissed: true }),
    );
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByRole('button', { name: 'Обучение' }));
    await user.click(screen.getByTestId('tour-resume'));
    expect(screen.queryByTestId('tour-practice-start')).toBeNull();
    await user.keyboard('{ArrowRight}');
    await waitFor(() => expect(stepOf()).toBe(STEPS.at(-1)!.id));
    expect(screen.getByTestId('tour-practice-start')).toHaveTextContent('Начать тренировку');
  });

  it('«Не сейчас» убирает строку с главной насовсем', async () => {
    const user = userEvent.setup();
    const first = renderApp('/');
    await user.click(await screen.findByTestId('tour-invite-dismiss'));
    expect(screen.queryByTestId('tour-invite')).toBeNull();
    first.unmount();
    renderApp('/');
    await screen.findByTestId('attention');
    expect(screen.queryByTestId('tour-invite')).toBeNull();
  });

  it('без хранилища тур работает', async () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('denied');
    });
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('denied');
    });
    try {
      const user = userEvent.setup();
      renderApp('/');
      await user.click(await screen.findByTestId('tour-invite-start'));
      await user.click(screen.getByTestId('tour-next'));
      expect(stepOf()).toBe(STEPS[1]!.id);
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });

  it('цели нет на экране — шаг объясняет словами', async () => {
    const wait = tourTiming.waitMs;
    tourTiming.waitMs = 300;
    try {
      const user = userEvent.setup();
      renderApp('/');
      await user.click(await screen.findByTestId('tour-invite-start'));
      // jsdom не раскладывает страницу: у целей нет размеров — значит, «на экране нет».
      await user.click(screen.getByTestId('tour-next'));
      await user.click(screen.getByTestId('tour-next'));
      expect(stepOf()).toBe('attention');
      expect(card()).toHaveAttribute('data-target', 'pending');
      await waitFor(() => expect(card()).toHaveAttribute('data-target', 'missing'));
      expect(screen.getByTestId('tour-missing')).toHaveTextContent(STEPS[2]!.missing!);
    } finally {
      tourTiming.waitMs = wait;
    }
  });
});
