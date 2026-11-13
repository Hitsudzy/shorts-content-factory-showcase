// CC-0037: вход по паролю из домашней сети, выход, понятные ошибки; с Mac вход не нужен.
// Подставной API входа — src/mocks/auth.ts (`authMode`: mac | lan | wrong | locked | off).
// До входа центр не трогает закрытое API: ни `/api/session`, ни `/api/health`, ни `contract.json`.
// Отказ 401/429 браузер сам пишет в консоль («status of 401») — других ошибок быть не должно.
import type { Page } from '@playwright/test';

import { AUTH_PASSWORD } from '../../src/mocks/auth';
import { expect, noSideScroll, onlyHttp, test } from './fixtures';

const tabs = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });

/** Все запросы страницы (пути), чтобы проверить: до входа — только вход и статика. */
function requested(page: Page): string[] {
  const seen: string[] = [];
  page.on('request', (r) => seen.push(new URL(r.url()).pathname));
  return seen;
}

const closed = (paths: string[]) =>
  paths.filter((p) => /\/api\/(?!auth\/)|contract\.json$|mockServiceWorker\.js$/.test(p));

async function signIn(page: Page, password: string) {
  const field = page.getByLabel('Пароль', { exact: true });
  await field.fill(password);
  await page.getByRole('button', { name: 'Войти' }).click();
}

test('с Mac: центр сразу, без экрана входа и без «Выйти»', async ({ page, apiHits }) => {
  await page.goto('/');
  await expect(page.getByTestId('attention')).toBeVisible();
  await expect(page.getByTestId('login-screen')).toHaveCount(0);
  await expect(page.getByTestId('logout')).toHaveCount(0);
  expect(apiHits[0]).toBe('GET /api/auth/state');
});

test.describe('домашняя сеть', () => {
  test.use({ authMode: 'lan', expectCleanConsole: false });

  test('вход: экран без закрытого API → неверный пароль → верный → центр с «Выйти»', async ({
    page,
    auth,
    consoleErrors,
  }) => {
    const seen = requested(page);
    await page.goto('/');
    const screen = page.getByTestId('login-screen');
    await expect(screen.getByRole('heading', { name: 'Командный центр Example' })).toBeVisible();
    await expect(screen).toContainText(
      'Вход нужен только из домашней сети; на Mac центр открывается без пароля',
    );
    await expect(page.getByLabel('Пароль', { exact: true })).toBeFocused();
    expect(closed(seen), 'до входа закрытое API не трогаем').toEqual([]);

    // Пустой — без запроса.
    const slot = page.getByTestId('login-error-slot');
    const before = (await slot.boundingBox())!.height;
    await page.getByRole('button', { name: 'Войти' }).click();
    await expect(page.getByTestId('login-error')).toHaveText('Введите пароль');
    // Место под ошибку зарезервировано: карточка не прыгает.
    expect((await slot.boundingBox())!.height).toBe(before);
    expect(auth.state.calls).toEqual(['GET /api/auth/state']);

    // Показать/скрыть.
    const field = page.getByLabel('Пароль', { exact: true });
    await field.fill('не тот');
    await expect(field).toHaveAttribute('type', 'password');
    await page.getByRole('button', { name: 'Показать пароль' }).click();
    await expect(field).toHaveAttribute('type', 'text');
    await page.getByRole('button', { name: 'Скрыть пароль' }).click();
    await expect(field).toHaveAttribute('type', 'password');

    await page.getByRole('button', { name: 'Войти' }).click();
    await expect(page.getByTestId('login-error')).toHaveText('Неверный пароль');
    await expect(page.getByTestId('login-error')).toHaveAttribute('data-kind', 'wrong');
    expect(closed(seen)).toEqual([]);

    await signIn(page, AUTH_PASSWORD);
    await expect(page.getByTestId('attention')).toBeVisible();
    await expect(page.getByTestId('login-screen')).toHaveCount(0);
    await expect(page.getByTestId('logout')).toBeVisible();
    // После входа — как раньше: центр читает API.
    await expect.poll(() => seen.includes('/api/health')).toBe(true);
    onlyHttp(consoleErrors, 401);
  });

  test('блокировка: минуты, живой отсчёт, кнопка выключена до конца', async ({
    page,
    auth,
    consoleErrors,
  }) => {
    auth.state.lockedFor = 65;
    await page.clock.install();
    await page.goto('/');
    await signIn(page, 'что-то');
    const error = page.getByTestId('login-error');
    await expect(error).toContainText('Слишком много попыток. Попробуйте через 2 мин');
    await expect(page.getByTestId('lock-timer')).toHaveText('Осталось 1:05');
    const button = page.getByRole('button', { name: 'Войти' });
    await expect(button).toBeDisabled();
    // Выключенная «Войти» — приглушённым фоном, не прозрачностью: подпись читается.
    await expect(button).toHaveCSS('opacity', '1');
    await expect(button).toHaveCSS('color', 'rgb(145, 145, 164)');
    await expect(button).toHaveCSS('background-color', 'rgb(27, 27, 38)');
    // Поле выключено тоже: Enter не нажать, кольца фокуса нет.
    await expect(page.getByLabel('Пароль', { exact: true })).toBeDisabled();

    await page.clock.runFor(10_000);
    await expect(page.getByTestId('lock-timer')).toHaveText('Осталось 0:55');
    await expect(error).toContainText('через 1 мин');
    expect(auth.state.calls.filter((c) => c.startsWith('POST'))).toHaveLength(1);

    auth.state.lockedFor = null;
    await page.clock.runFor(56_000);
    await expect(error).toHaveCount(0);
    await expect(button).toBeEnabled();
    await expect(page.getByLabel('Пароль', { exact: true })).toBeFocused();
    await signIn(page, AUTH_PASSWORD);
    await expect(page.getByTestId('logout')).toBeVisible();
    onlyHttp(consoleErrors, 429);
  });

  test('пароль на сервере не задан: сказано прямо, без петли', async ({
    page,
    auth,
    consoleErrors,
  }) => {
    auth.state.off = true;
    await page.goto('/');
    await signIn(page, 'что-то');
    await expect(page.getByTestId('login-error')).toContainText(
      'Пароль на сервере не задан, поэтому вход из домашней сети выключен',
    );
    await page.waitForTimeout(500);
    expect(auth.state.calls).toEqual(['GET /api/auth/state', 'POST /api/auth/login']);
    onlyHttp(consoleErrors, 409);
  });

  test('выход: «Выйти» в шапке → экран входа; снова вход', async ({
    page,
    auth,
    consoleErrors,
  }) => {
    auth.state.loggedIn = true;
    await page.goto('/');
    await expect(page.getByTestId('attention')).toBeVisible();
    await page.getByTestId('logout').click();
    await expect(page.getByTestId('login-note')).toHaveText(
      'Вы вышли из центра на этом устройстве',
    );
    expect(auth.state.loggedIn).toBe(false);
    expect(auth.state.calls).toContain('POST /api/auth/logout');
    await signIn(page, AUTH_PASSWORD);
    await expect(page.getByTestId('attention')).toBeVisible();
    onlyHttp(consoleErrors, 401);
  });

  test('вход истёк посреди работы → вход → та же страница', async ({
    page,
    auth,
    consoleErrors,
  }) => {
    auth.state.loggedIn = true;
    // Главная опрашивает ленту часто — начинаем со спокойной страницы.
    await page.goto('/versions');
    await expect(page.getByTestId('versions-release')).toHaveText('2.3.4');
    // Кука истекла на сервере: следующий запрос — 401 auth_required.
    auth.state.loggedIn = false;
    await tabs(page).getByRole('link', { name: 'Каналы', exact: true }).click();
    await expect(page.getByTestId('login-screen')).toBeVisible();
    await expect(page.getByTestId('login-note')).toContainText('Вход истёк');
    await expect(page).toHaveURL(/\/channels$/);

    await signIn(page, AUTH_PASSWORD);
    await expect(page).toHaveURL(/\/channels$/);
    await expect(page.getByTestId('channels-count')).toHaveText('3 канала');
    onlyHttp(consoleErrors, 401);
  });
});

test.describe('телефон', () => {
  test.use({ authMode: 'lan', viewport: { width: 390, height: 844 } });

  test('экран входа без прокрутки вбок, «Выйти» помещается в шапку', async ({ page, auth }) => {
    await page.goto('/');
    await expect(page.getByTestId('login-screen')).toBeVisible();
    await noSideScroll(page);
    auth.state.loggedIn = true;
    await page.reload();
    await expect(page.getByTestId('logout')).toBeInViewport({ ratio: 1 });
    await noSideScroll(page);
  });
});
