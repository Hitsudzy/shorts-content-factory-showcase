import type { Page } from '@playwright/test';

import { AREAS } from '../../src/app/areas';
import { fixtures } from '../../src/mocks/fixtures';
import { KINDS } from '../../src/pages/batches/stages';
import { expect, openTip, test } from './fixtures';

const tabsNav = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });
const tab = (page: Page, name: string) => tabsNav(page).getByRole('link', { name, exact: true });
const bodyBg = (page: Page) => page.evaluate(() => getComputedStyle(document.body).backgroundColor);

test.describe('оболочка', () => {
  test('табы: каждый открывает свой раздел, неготовые — заглушка «скоро» с версией', async ({
    page,
  }) => {
    await page.goto('/');
    for (const area of AREAS.slice(1)) {
      await tab(page, area.short).click();
      await expect(page).toHaveURL(new RegExp(`/${area.path}$`));
      await expect(tab(page, area.short)).toHaveAttribute('aria-current', 'page');
      await expect(page.getByRole('heading', { level: 1, name: area.title })).toBeVisible();
      if (area.soon) await expect(page.getByText(`Скоро · версия ${area.soon}`)).toBeVisible();
    }
    await tab(page, 'Главная').click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId('factory-card')).toBeVisible();
  });

  test('тема: по умолчанию тёмная, переключается и переживает перезагрузку', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    expect(await bodyBg(page)).toBe('rgb(11, 11, 18)');

    await page.getByRole('button', { name: 'Светлая тема' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    expect(await bodyBg(page)).toBe('rgb(242, 242, 245)');

    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');
    await page.getByRole('button', { name: 'Тёмная тема' }).click();
    await page.reload();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
  });

  test('«подробнее»: коммит и пути спрятаны, пока не раскрыть', async ({ page }) => {
    await page.goto('/');
    const card = page.getByTestId('factory-card');
    await expect(
      card.getByRole('heading', { name: `Версия ${fixtures.version.factory.version}` }),
    ).toBeVisible();
    const commit = card.getByText(`коммит фабрики: ${fixtures.version.factory.commit}`);
    await expect(commit).toBeHidden();

    await card.getByText('Подробнее').click();
    await expect(commit).toBeVisible();
    await expect(card.getByText('раздача центра: frontend/dist')).toBeVisible();
    await card.getByText('Подробнее').click();
    await expect(commit).toBeHidden();

    // На видном месте — ни путей, ни хэшей.
    const visible = await page.locator('main').evaluate((m) => (m as HTMLElement).innerText);
    expect(visible).not.toContain('agents/footage-indexer');
    expect(visible).not.toMatch(/[0-9a-f]{12}/);
  });

  test('тултип: у таба — полное имя раздела, у статуса — пояснение', async ({ page }) => {
    await page.goto('/');
    await openTip(page, tab(page, 'Мемы'), 'Банки мемов каналов', 'hover');
    await page.mouse.move(600, 400, { steps: 5 });
    await page.mouse.move(640, 420, { steps: 3 });
    await expect(page.getByRole('tooltip')).toBeHidden();

    await openTip(
      page,
      page.getByTestId('agents-card').getByText('на пине', { exact: true }),
      'закреплён',
    );
  });

  test('подтверждение: «Сбросить вид» спрашивает, «Отмена» ничего не меняет', async ({ page }) => {
    await page.goto('/');
    await page.getByRole('button', { name: 'Светлая тема' }).click();

    await page.getByRole('button', { name: 'Сбросить вид' }).click();
    const dialog = page.getByRole('alertdialog', { name: 'Сбросить вид центра?' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Отмена' }).click();
    await expect(dialog).toBeHidden();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

    await page.getByRole('button', { name: 'Сбросить вид' }).click();
    await dialog.getByRole('button', { name: 'Сбросить' }).click();
    await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
    expect(await page.evaluate(() => localStorage.getItem('cc-theme'))).toBeNull();
  });
});

test.describe('телефон', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  for (const path of ['/', '/channels']) {
    test(`${path}: нет прокрутки вбок, табы листаются внутри своей строки`, async ({ page }) => {
      await page.goto(path);
      await expect(tabsNav(page)).toBeVisible();
      const page_ = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        width: document.documentElement.clientWidth,
      }));
      expect(page_.scroll).toBeLessThanOrEqual(page_.width);

      const row = tabsNav(page).locator('div').first();
      const r = await row.evaluate((el) => ({ scroll: el.scrollWidth, width: el.clientWidth }));
      expect(r.scroll).toBeGreaterThan(r.width);

      await tab(page, 'Разработка').scrollIntoViewIfNeeded();
      await expect(tab(page, 'Разработка')).toBeInViewport();
    });
  }

  test('кинолента батча — вертикальная', async ({ page }) => {
    await page.goto('/');
    const frames = page.getByTestId('batch-card').locator('ol > li');
    // В плане идущего батча мока — все виды кадров (CC-0090).
    await expect(frames).toHaveCount(Object.keys(KINDS).length);
    const [a, b] = await Promise.all([frames.nth(0).boundingBox(), frames.nth(1).boundingBox()]);
    expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1);
    expect(Math.abs(b!.x - a!.x)).toBeLessThan(1);
  });
});

test.describe('API недоступен', () => {
  test.use({ expectCleanConsole: false });

  test('шапка и карточки говорят «нет связи», «Повторить» поднимает данные', async ({ page }) => {
    let down = true;
    for (const path of ['/api/health', '/api/version']) {
      await page.route(`**${path}`, (route) =>
        down
          ? route.fulfill({ status: 503, body: 'down' })
          : route.fulfill({ json: path.endsWith('health') ? fixtures.health : fixtures.version }),
      );
    }
    await page.goto('/');

    await expect(page.getByTestId('api-status')).toHaveText('Нет связи с фабрикой');
    const card = page.getByTestId('factory-card');
    await expect(card.getByRole('alert')).toContainText('Нет связи с фабрикой', {
      timeout: 15_000,
    });
    await expect(page.getByTestId('agents-card').getByRole('alert')).toBeVisible();

    down = false;
    await card.getByRole('button', { name: 'Повторить' }).click();
    await expect(
      card.getByRole('heading', { name: `Версия ${fixtures.version.factory.version}` }),
    ).toBeVisible();
    await expect(page.getByTestId('api-status')).toHaveText('Фабрика на связи');
  });
});
