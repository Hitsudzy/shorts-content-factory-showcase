import * as AlertDialog from '@radix-ui/react-alert-dialog';
import { act, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { createMemoryRouter, Link, Outlet, RouterProvider } from 'react-router';

import { beginWrite, PLAN_TITLE } from '@/api/writeLock';

import { WriteLock } from './WriteLock';

const SAVE = { title: 'Сохраняю отметки…', kind: 'write' as const };

function Page() {
  const [clicks, setClicks] = useState(0);
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setClicks((n) => n + 1)}>
        Сохранить
      </button>
      <span data-testid="clicks">{clicks}</span>
      <input aria-label="Поле" />
      <Link to="/other">Другой таб</Link>
      <AlertDialog.Root open={open} onOpenChange={setOpen}>
        <AlertDialog.Trigger>Открыть окно</AlertDialog.Trigger>
        <AlertDialog.Portal>
          <AlertDialog.Content aria-describedby={undefined}>
            <AlertDialog.Title>Окно подтверждения</AlertDialog.Title>
            <AlertDialog.Action>да</AlertDialog.Action>
          </AlertDialog.Content>
        </AlertDialog.Portal>
      </AlertDialog.Root>
    </>
  );
}

function setup() {
  const router = createMemoryRouter(
    [
      {
        element: (
          <>
            <WriteLock />
            <Outlet />
          </>
        ),
        children: [
          { path: '/', element: <Page /> },
          { path: '/other', element: <p>Другая страница</p> },
        ],
      },
    ],
    { initialEntries: ['/'] },
  );
  render(<RouterProvider router={router} />);
  // Проверка `pointer-events` user-event выключена: клик должен дойти до слоя и там застрять.
  return { router, user: userEvent.setup({ pointerEventsCheck: 0 }) };
}

describe('WriteLock: интерфейс замирает, пока идёт запись', () => {
  it('без записи слоя нет', () => {
    setup();
    expect(screen.queryByTestId('write-lock')).toBeNull();
  });

  it('запись в полёте: слой с подписью, aria-busy, фокус в слое; ответ — слоя нет, фокус на месте', async () => {
    const { user } = setup();
    const save = screen.getByRole('button', { name: 'Сохранить' });
    await user.click(save);
    expect(screen.getByTestId('clicks')).toHaveTextContent('1');
    expect(save).toHaveFocus();

    let end!: () => void;
    act(() => {
      end = beginWrite(SAVE);
    });
    const layer = screen.getByTestId('write-lock');
    expect(layer).toHaveAttribute('aria-busy', 'true');
    expect(layer).toHaveAttribute('aria-modal', 'true');
    expect(screen.getByTestId('write-lock-title')).toHaveTextContent('Сохраняю отметки…');
    expect(layer).toHaveFocus();

    act(() => end());
    expect(screen.queryByTestId('write-lock')).toBeNull();
    expect(save).toHaveFocus();
  });

  it('клики и клавиши не проходят, Tab не уводит фокус, Esc слой не снимает', async () => {
    const { user } = setup();
    let end!: () => void;
    act(() => {
      end = beginWrite(SAVE);
    });
    const layer = screen.getByTestId('write-lock');

    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(screen.getByTestId('clicks')).toHaveTextContent('0');

    await user.keyboard('{Tab}{Tab}');
    expect(layer).toHaveFocus();
    await user.keyboard('{Escape}');
    expect(screen.getByTestId('write-lock')).toBeInTheDocument();

    // Фокус, уведённый кодом, возвращается в слой; ввод в поле не проходит.
    act(() => screen.getByLabelText('Поле').focus());
    expect(layer).toHaveFocus();
    await user.type(screen.getByLabelText('Поле'), 'abc', { skipClick: true });
    expect(screen.getByLabelText('Поле')).toHaveValue('');

    act(() => end());
    await user.click(screen.getByRole('button', { name: 'Сохранить' }));
    expect(screen.getByTestId('clicks')).toHaveTextContent('1');
  });

  it('переходы по маршрутам не проходят, пока запись в полёте', async () => {
    const { router, user } = setup();
    let end!: () => void;
    act(() => {
      end = beginWrite(SAVE);
    });
    await user.click(screen.getByRole('link', { name: 'Другой таб' }));
    await act(() => router.navigate('/other'));
    expect(router.state.location.pathname).toBe('/');

    act(() => end());
    await act(() => router.navigate('/other'));
    expect(router.state.location.pathname).toBe('/other');
  });

  it('открытое окно Radix: Esc и клик по слою его не закрывают, фокус не утягивает назад', async () => {
    const { user } = setup();
    await user.click(screen.getByRole('button', { name: 'Открыть окно' }));
    const dialog = await screen.findByRole('alertdialog');
    let end!: () => void;
    act(() => {
      end = beginWrite({ title: 'Применяю разбор…', kind: 'write' });
    });
    const layer = screen.getByTestId('write-lock');
    expect(layer).toHaveFocus();
    await user.keyboard('{Escape}');
    await user.click(layer);
    expect(screen.getByRole('alertdialog')).toBe(dialog);
    expect(layer).toHaveFocus();
    act(() => end());
    expect(screen.queryByTestId('write-lock')).toBeNull();
    expect(screen.getByRole('alertdialog')).toBe(dialog);
  });

  it('план — «Готовлю план…», ничего ещё не записано', () => {
    setup();
    act(() => {
      beginWrite({ title: PLAN_TITLE, kind: 'plan' });
    });
    expect(screen.getByTestId('write-lock')).toHaveAttribute('data-kind', 'plan');
    expect(screen.getByTestId('write-lock')).toHaveTextContent('пока ничего не записано');
  });

  it('долгая запись: «до 20 минут», вкладку закрыть можно — браузер переспросит', () => {
    setup();
    let end!: () => void;
    act(() => {
      end = beginWrite({
        title: 'Загружаю ролик на YouTube…',
        kind: 'write',
        upToMs: 20 * 60_000,
      });
    });
    expect(screen.getByTestId('write-lock-long')).toHaveTextContent(
      'Это может занять до 20 минут. Вкладку можно закрыть — запись продолжится на фабрике.',
    );
    const leave = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(true);

    act(() => end());
    const after = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(after);
    expect(after.defaultPrevented).toBe(false);
  });

  it('текст слоя — без трёх точек; дуга спиннера — контрастный акцент primary-text (CC-0093)', () => {
    setup();
    act(() => {
      beginWrite({
        title: 'Загружаю ролик на YouTube…',
        kind: 'write',
        upToMs: 20 * 60_000,
      });
      beginWrite({ title: PLAN_TITLE, kind: 'plan' });
    });
    expect(screen.getByTestId('write-lock').textContent).not.toContain('...');
    const spinner = screen.getByTestId('write-lock-spinner');
    expect(spinner.className).toContain('border-t-primary-text');
    expect(spinner.className).not.toMatch(/border-t-primary(\s|$)/);
  });

  it('обычная запись вкладку не держит', () => {
    setup();
    act(() => {
      beginWrite(SAVE);
    });
    expect(screen.queryByTestId('write-lock-long')).toBeNull();
    const leave = new Event('beforeunload', { cancelable: true });
    window.dispatchEvent(leave);
    expect(leave.defaultPrevented).toBe(false);
  });
});
