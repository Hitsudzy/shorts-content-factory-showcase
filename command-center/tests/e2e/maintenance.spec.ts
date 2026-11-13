// CC-0033: экран «Обслуживание и расход» на подставном API (src/mocks/maintenance.ts): таб →
// экран (только чтения); расход батча словами, денег нет — сказано подсказкой; сравнение прогонов;
// запись plan → «да» (поле пустое, «да» набираете вы) → итог; отказ «идёт батч» словами;
// устаревший план — переплан сам, «да» снова пустое; телефон 390 без прокрутки вбок.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, onlyHttp, openTip, test } from './fixtures';

const tabs = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });

/** Видимый текст `main` без «подробнее». */
const plain = (page: Page) =>
  page.locator('main').evaluate((m) => {
    const c = m.cloneNode(true) as HTMLElement;
    c.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
    return c.textContent ?? '';
  });

const RAW =
  /\d{4}-\d\d-\d\dT\d{4}Z|scripts\/|pipeline\/|shared\/|yt-[A-Za-z0-9]{6}|example(reel|tech|science)\b/;

const ready = async (page: Page) => {
  await expect(page.getByTestId('usage-view')).toBeVisible();
  await expect(page.getByTestId('pool-view')).toBeVisible();
  await expect(page.getByTestId('archive-view')).toBeVisible();
};

test('таб → расход и уборки словами, только чтения; денег нет — сказано подсказкой', async ({
  page,
  apiHits,
}) => {
  await page.goto('/');
  await tabs(page).getByRole('link', { name: 'Обслуживание', exact: true }).click();
  await expect(page).toHaveURL(/\/maintenance$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Обслуживание и расход');
  await expect(page.getByText(/Скоро · версия/)).toHaveCount(0);
  await ready(page);
  await expect(page.getByTestId('usage-batch')).toHaveValue('example-film/2026-10-09T0215Z');
  await expect(page.getByTestId('usage-total')).toContainText('млн');
  await openTip(page, page.getByTestId('usage-money'), 'только токены');
  await page.getByTestId('compare-run').click();
  await expect(page.getByTestId('compare-view')).toHaveAttribute('data-same', '1');
  expect(await plain(page)).not.toMatch(RAW);
  expect(apiHits.filter((h) => h.includes('/api/maintenance') && !h.startsWith('GET '))).toEqual(
    [],
  );
});

test('пул: план → «да» набрано вами → освобождён, записано из центра', async ({
  page,
  maintenance,
  apiHits,
}) => {
  await page.goto('/maintenance');
  await ready(page);
  await expect(page.getByTestId('pool-release')).toContainText('3 источника');
  await page.getByTestId('pool-release-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('pool-plan-total')).toContainText('Уйдёт 3 источника');
  const yes = dialog.getByTestId('pool-yes');
  await expect(yes).toHaveValue('');
  const confirm = dialog.getByTestId('pool-release-confirm');
  await expect(confirm).toBeDisabled();
  await yes.fill('да');
  await expect(confirm).toBeEnabled();
  await confirm.click();
  await expect(page.getByTestId('pool-done')).toContainText('Удалено 3 источника');
  await expect(page.getByTestId('pool-release')).toContainText('0 источников');
  expect(maintenance.state.written.released).toHaveLength(3);
  expect(apiHits.filter((h) => h.startsWith('POST /api/maintenance'))).toEqual([
    'POST /api/maintenance/pool/release/plan',
    'POST /api/maintenance/pool/release',
  ]);
});

test.describe('отказы фабрики: в консоли — только ответ 409', () => {
  test.use({ expectCleanConsole: false });

  test('журналы: батч начался после плана — отказ «идёт батч» словами, ничего не тронуто', async ({
    page,
    maintenance,
    consoleErrors,
  }) => {
    await page.goto('/maintenance');
    await ready(page);
    await page.getByTestId('journals-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('journals-plan-rows')).toContainText(
      'ExampleScience · батч 08.10, 06:00',
    );
    maintenance.state.openBatches = ['example-science/2026-10-14T0300Z'];
    await dialog.getByTestId('journals-yes').fill('да');
    await dialog.getByTestId('journals-confirm').click();
    const err = dialog.getByTestId('act-error');
    await expect(err).toHaveAttribute('data-code', 'batch_open');
    await expect(err).toContainText('Идёт батч — уборки и архив ждут, пока он закончится');
    expect(maintenance.state.written.journals).toBe(0);
    onlyHttp(consoleErrors, 409);
  });

  test('архив: план устарел — переплан сам, «да» снова пустое; потом месяц в архиве', async ({
    page,
    maintenance,
    consoleErrors,
  }) => {
    await page.goto('/maintenance');
    await ready(page);
    await page.getByTestId('archive-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('archive-plan-jobs')).toContainText(
      'ExampleFilm · сентябрь 2026',
    );
    maintenance.expireTokens();
    await dialog.getByTestId('archive-yes').fill('да');
    await dialog.getByTestId('archive-confirm').click();
    await expect(dialog.getByTestId('replanned')).toHaveAttribute('data-code', 'confirm_expired');
    await expect(dialog.getByTestId('archive-yes')).toHaveValue('');
    await expect(dialog.getByTestId('archive-confirm')).toBeDisabled();
    await dialog.getByTestId('archive-yes').fill('да');
    await dialog.getByTestId('archive-confirm').click();
    await expect(page.getByTestId('archive-done')).toContainText('Месяц в архиве');
    await expect(page.getByTestId('archive-done-commit')).toContainText('Коммит сделан');
    expect(maintenance.state.written.archived).toHaveLength(3);
    onlyHttp(consoleErrors, 409);
  });
});

test('телефон 390: экран и окно плана без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/maintenance');
  await ready(page);
  await noSideScroll(page);
  await page.getByTestId('pool-release-open').click();
  await expect(page.getByRole('alertdialog').getByTestId('pool-yes')).toBeVisible();
  await noSideScroll(page);
});
