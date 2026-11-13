// CC-0037: состояние входа, перехват 401 `auth_required` клиентом API, экран входа и ворота.
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, render, renderHook, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { bootAuth, login, logout } from '@/api/auth';
import { getHealth, resetSession, sessionHeaders } from '@/api/client';
import { auth } from '@/mocks/handlers';
import { AUTH_PASSWORD, authPreset } from '@/mocks/auth';
import { server } from '@/mocks/server';

import { AuthGate } from './AuthGate';
import { clock, lockedText } from './lockText';
import { authRequired, authSnapshot, resetAuth, useAuth, watchUnauthorized } from './store';

describe('useAuth и загрузка', () => {
  it('с Mac (по умолчанию): центр без входа, «Выйти» не нужен', async () => {
    const { result } = renderHook(() => useAuth());
    expect(result.current.view).toBe('checking');
    await act(() => bootAuth());
    expect(result.current).toMatchObject({ view: 'app', required: false });
    expect(auth.state.calls).toEqual(['GET /api/auth/state']);
  });

  it('домашняя сеть без входа: экран входа, причина — загрузка', async () => {
    authPreset(auth, 'lan');
    const { result } = renderHook(() => useAuth());
    await act(() => bootAuth());
    expect(result.current).toMatchObject({
      view: 'login',
      required: true,
      loggedIn: false,
      reason: 'boot',
    });
  });

  it('домашняя сеть, уже вошли: центр, «Выйти» есть', async () => {
    authPreset(auth, 'lan');
    auth.state.loggedIn = true;
    await bootAuth();
    expect(authSnapshot()).toMatchObject({ view: 'app', required: true, loggedIn: true });
  });

  it('сервер старше контракта (нет ручки) — центр открывается как раньше', async () => {
    server.use(
      http.get('*/api/auth/state', () =>
        HttpResponse.json({ detail: 'Not Found' }, { status: 404 }),
      ),
    );
    await bootAuth();
    expect(authSnapshot()).toMatchObject({ view: 'app', required: false });
  });

  it('тренировка: живой API о входе не спрашиваем', async () => {
    await bootAuth({ training: true });
    expect(authSnapshot().view).toBe('app');
    expect(auth.state.calls).toEqual([]);
  });
});

describe('401 auth_required → вход', () => {
  it('любой запрос клиента API с 401 auth_required уводит на вход, адрес не трогает', async () => {
    resetAuth({ view: 'app', required: true, loggedIn: true, reason: null });
    authPreset(auth, 'lan');
    window.history.replaceState(null, '', '/videos?channel=example-tech');
    await expect(getHealth()).rejects.toMatchObject({ status: 401 });
    await waitFor(() => expect(authSnapshot().view).toBe('login'));
    expect(authSnapshot()).toMatchObject({ required: true, loggedIn: false, reason: 'expired' });
    expect(window.location.pathname + window.location.search).toBe('/videos?channel=example-tech');
  });

  it('запись без входа: токен сессии (`/api/session`) не получить — тоже вход', async () => {
    resetAuth({ view: 'app', required: true, loggedIn: true, reason: null });
    authPreset(auth, 'lan');
    resetSession();
    await expect(sessionHeaders()).rejects.toMatchObject({ status: 401 });
    await waitFor(() => expect(authSnapshot().view).toBe('login'));
  });

  it('другой 401 (не auth_required) — не про вход', async () => {
    resetAuth({ view: 'app', required: true, loggedIn: true, reason: null });
    watchUnauthorized(
      HttpResponse.json({ detail: 'Неверный пароль', code: 'wrong_password' }, { status: 401 }),
    );
    watchUnauthorized(new Response('oops', { status: 401 }));
    await new Promise((r) => setTimeout(r, 20));
    expect(authSnapshot().view).toBe('app');
  });

  it('уже на входе — повторный отказ причину не меняет', () => {
    resetAuth({ view: 'login', required: true, loggedIn: false, reason: 'logout' });
    authRequired();
    expect(authSnapshot().reason).toBe('logout');
  });
});

describe('вход и выход', () => {
  beforeEach(() => authPreset(auth, 'lan'));

  it('пустой пароль — без запроса', async () => {
    expect(await login('  ')).toMatchObject({ ok: false, kind: 'empty' });
    expect(auth.state.calls).toEqual([]);
  });

  it('верный пароль — центр; неверный — «Неверный пароль»', async () => {
    expect(await login('не тот')).toEqual({ ok: false, kind: 'wrong', message: 'Неверный пароль' });
    expect(await login(AUTH_PASSWORD)).toEqual({ ok: true });
    expect(authSnapshot()).toMatchObject({ view: 'app', loggedIn: true, required: true });
  });

  it('блокировка: секунды из retry_after', async () => {
    authPreset(auth, 'locked');
    auth.state.lockedFor = 125;
    expect(await login('что-то')).toMatchObject({ ok: false, kind: 'locked', retryAfter: 125 });
  });

  it('пять неверных подряд — блокировка', async () => {
    for (let i = 0; i < 4; i++) expect((await login('x')).ok).toBe(false);
    expect(await login('x')).toMatchObject({ kind: 'locked', retryAfter: 300 });
  });

  it('пароль на сервере не задан — 409 простыми словами', async () => {
    authPreset(auth, 'off');
    const out = await login('что-то');
    expect(out).toMatchObject({ ok: false, kind: 'off' });
    expect(!out.ok && out.message).toMatch(/Пароль на сервере не задан/);
  });

  it('выход — экран входа', async () => {
    auth.state.loggedIn = true;
    resetAuth({ view: 'app', required: true, loggedIn: true, reason: null });
    await logout();
    expect(authSnapshot()).toMatchObject({ view: 'login', loggedIn: false, reason: 'logout' });
    expect(auth.state.loggedIn).toBe(false);
  });
});

describe('подписи блокировки', () => {
  it('минуты вверх, часы m:ss', () => {
    expect(lockedText(300)).toBe('Слишком много попыток. Попробуйте через\u00a05\u00a0мин');
    expect(lockedText(61)).toBe('Слишком много попыток. Попробуйте через\u00a02\u00a0мин');
    expect(lockedText(5)).toBe('Слишком много попыток. Попробуйте через\u00a01\u00a0мин');
    expect(clock(125)).toBe('2:05');
    expect(clock(0.2)).toBe('0:01');
  });
});

function renderGate(load = () => Promise.resolve(<p>центр открыт</p>)) {
  const once = load();
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <AuthGate load={() => once} />
    </QueryClientProvider>,
  );
}

describe('ворота и экран входа', () => {
  it('Mac: сразу центр, экрана входа нет', async () => {
    await bootAuth();
    renderGate();
    expect(await screen.findByText('центр открыт')).toBeInTheDocument();
    expect(screen.queryByTestId('login-screen')).toBeNull();
  });

  it('сеть: вход → неверный → верный → центр; центр до входа не грузится', async () => {
    authPreset(auth, 'lan');
    await bootAuth();
    let loaded = 0;
    renderGate(() => {
      loaded += 1;
      return Promise.resolve(<p>центр открыт</p>);
    });
    expect(screen.getByRole('heading', { name: 'Командный центр Example' })).toBeInTheDocument();
    expect(
      screen.getByText('Вход нужен только из домашней сети; на Mac центр открывается без пароля'),
    ).toBeInTheDocument();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: 'Войти' }));
    expect(screen.getByRole('alert')).toHaveTextContent('Введите пароль');
    expect(auth.state.calls).toEqual(['GET /api/auth/state']);

    const field = screen.getByLabelText('Пароль');
    expect(field).toHaveAttribute('type', 'password');
    await user.click(screen.getByRole('button', { name: 'Показать пароль' }));
    expect(field).toHaveAttribute('type', 'text');

    await user.type(field, 'не тот{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent('Неверный пароль');
    expect(field).toHaveAttribute('aria-invalid', 'true');
    await user.clear(field);
    await user.type(field, `${AUTH_PASSWORD}{Enter}`);
    expect(await screen.findByText('центр открыт')).toBeInTheDocument();
    expect(loaded).toBe(1);
  });

  it('блокировка: текст с минутами, таймер идёт, кнопка выключена', async () => {
    authPreset(auth, 'locked');
    auth.state.lockedFor = 62;
    await bootAuth();
    renderGate();
    const user = userEvent.setup();
    await user.type(screen.getByLabelText('Пароль'), 'что-то{Enter}');
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Слишком много попыток. Попробуйте через 2 мин',
    );
    expect(screen.getByTestId('lock-timer')).toHaveTextContent('Осталось 1:02');
    expect(screen.getByRole('button', { name: 'Войти' })).toBeDisabled();
    expect(screen.getByLabelText('Пароль')).toBeDisabled();
    await waitFor(
      () => expect(screen.getByTestId('lock-timer')).toHaveTextContent('Осталось 1:01'),
      {
        timeout: 3000,
      },
    );
  });

  it('вход истёк посреди работы — подпись про ту же страницу', async () => {
    resetAuth({ view: 'app', required: true, loggedIn: true, reason: null });
    renderGate();
    expect(await screen.findByText('центр открыт')).toBeInTheDocument();
    act(() => authRequired());
    expect(await screen.findByTestId('login-note')).toHaveTextContent(
      'Вход истёк. Введите пароль — центр откроется на той же странице',
    );
  });
});
