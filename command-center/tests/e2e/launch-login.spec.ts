// CC-0177 (по CC-0176, договор 0.77.0) на подставном API: вход Claude в окне «Запустить батч» —
// план без входа придерживает «Запустить» до «Проверить снова», неизвестный вход — мягкое
// предупреждение и рядом с «Батч запущен», отказ «да» `not_logged_in` — текст фабрики и
// «Проверить снова»; история — строка «продолжен тиком сам» с подсказкой. Компьютер и телефон
// без прокрутки вбок.
import type { Page } from '@playwright/test';

import { LOGIN_NO, LOGIN_OK, LOGIN_UNKNOWN } from '../../src/mocks/batchActions';
import { AUTO_RESUME } from '../../src/mocks/batches';
import { expect, noSideScroll, openTip, test } from './fixtures';

const openLaunch = async (page: Page) => {
  await page.goto('/batches');
  await page.getByTestId('launch-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('launch-why')).toBeVisible();
  return dialog;
};

for (const device of ['desktop', 'phone'] as const) {
  test.describe(`вход Claude при запуске @cc-0177: ${device}`, () => {
    test.beforeEach(async ({ page }) => {
      if (device === 'phone') await page.setViewportSize({ width: 390, height: 844 });
    });

    test('план без входа: строка сразу, «Запустить» придержана; вошёл — «Проверить снова»', async ({
      page,
      batches,
    }) => {
      batches.closeAll();
      batches.actions.setLogin(LOGIN_NO);
      const dialog = await openLaunch(page);
      const line = dialog.getByTestId('launch-login');
      await expect(line).toHaveAttribute('data-login', 'missing');
      await expect(line).toHaveText(
        'Claude не залогинен. Войдите — в терминале claude, затем /login — и нажмите «Проверить снова».',
      );
      await expect(line.locator('code')).toHaveText(['claude', '/login']);
      await expect(dialog.getByText('запуск придержан: нет входа в Claude')).toBeVisible();
      await expect(dialog.getByTestId('launch-confirm')).toBeDisabled();
      await expect(dialog.getByTestId('launch-confirm')).toHaveText('Запустить');
      await noSideScroll(page);
      batches.actions.setLogin(LOGIN_OK);
      await dialog.getByTestId('login-recheck').click();
      await expect(dialog.getByTestId('launch-confirm')).toBeEnabled();
      await expect(dialog.getByTestId('launch-login')).toHaveCount(0);
      await expect(dialog.getByTestId('login-recheck')).toHaveCount(0);
    });

    test('вход не проверить: предупреждение в плане и у «Батч запущен»', async ({
      page,
      batches,
    }) => {
      batches.closeAll();
      batches.actions.setLogin(LOGIN_UNKNOWN);
      const dialog = await openLaunch(page);
      await expect(dialog.getByTestId('launch-login')).toHaveText(
        'Вход в Claude не проверен: claude не найден',
      );
      await dialog.getByTestId('launch-confirm').click();
      await expect(dialog).toBeHidden();
      const done = page.getByTestId('launch-done');
      await expect(done).toContainText('Батч запущен');
      await expect(done.getByTestId('launch-login-warn')).toHaveText(
        'Вход в Claude не проверен: claude не найден',
      );
      await noSideScroll(page);
    });

    test.describe('отказ «да»', () => {
      test.use({ expectCleanConsole: false });

      test('not_logged_in: текст фабрики, код под «подробнее», «Проверить снова» — новый план', async ({
        page,
        batches,
      }) => {
        batches.closeAll();
        const dialog = await openLaunch(page);
        batches.actions.setLogin(LOGIN_NO);
        await dialog.getByTestId('launch-confirm').click();
        const err = dialog.getByTestId('act-error');
        await expect(err).toHaveAttribute('data-code', 'not_logged_in');
        await expect(err.getByTestId('refusal-message')).toHaveText(
          'Claude не залогинен. Войдите — в терминале claude, затем /login — батч не открыт.',
        );
        await expect(err.getByTestId('refusal-message').locator('code')).toHaveCount(2);
        await expect(dialog.getByTestId('launch-confirm')).toHaveText('Запустить');
        await expect(dialog.getByText('запуск придержан: нет входа в Claude')).toBeVisible();
        await expect(err.getByText('код: not_logged_in')).toBeHidden();
        await expect(err.getByTestId('login-note')).toContainText('Подтверждение потрачено');
        await expect(dialog.getByTestId('launch-confirm')).toBeDisabled();
        await expect(dialog.getByTestId('replan')).toHaveCount(0);
        await noSideScroll(page);
        batches.actions.setLogin(LOGIN_OK);
        await dialog.getByTestId('login-recheck').click();
        await expect(dialog.getByTestId('launch-confirm')).toBeEnabled();
        await expect(dialog.getByTestId('act-error')).toHaveCount(0);
        expect(batches.actions.writes.map((w) => w.path)).toEqual([
          'launch/plan',
          'launch',
          'launch/plan',
        ]);
      });
    });

    test('история: «продолжен тиком сам» — подсказка и строка фабрики под «подробнее»', async ({
      page,
      batches,
    }) => {
      batches.setAutoResume();
      await page.goto('/batches');
      const row = page.getByTestId('batch-history').getByTestId('run-auto');
      await expect(row).toHaveCount(1);
      await expect(row).toContainText('ExampleFilm');
      const badge = row.locator('[data-slot="status"]');
      await expect(badge).toHaveText('продолжен тиком сам');
      await openTip(page, badge, 'Тик продолжил его сам');
      await expect(row.getByTestId('run-auto-text')).toBeHidden();
      await row.getByRole('button').first().click();
      await expect(row.getByTestId('run-auto-text')).toContainText(
        'Батч стоял на «Исследование и сценарии»: Claude был не залогинен.',
      );
      await row.getByText('Подробнее').click();
      await expect(row).toContainText(`фабрика: ${AUTO_RESUME.auto}`);
      await noSideScroll(page);
    });
  });
}
