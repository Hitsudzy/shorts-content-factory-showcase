// Перенос размещённых роликов (CC-0166) на подставном API (src/mocks/publishMove.ts): «Сдвинуть
// очередь…» — все с дня на день раньше, ролик дня перед ним — в копилку → план фабрики целиком →
// одно «да» → лента переставлена, ролик в копилке; телефон — без бокового скролла.
import type { Page } from '@playwright/test';

import { NOT_READY, READY, REEL } from '../../src/mocks/publish';
import { expect, noSideScroll, test } from './fixtures';

const slot = (page: Page, slug: string) =>
  page.getByTestId('slot-feed').locator(`[data-testid="slot"][data-slug="${slug}"]`);

/** POST-запросы страницы к переносу. */
function posts(page: Page): string[] {
  const seen: string[] = [];
  page.on('request', (r) => {
    const path = new URL(r.url()).pathname;
    if (r.method() === 'POST' && path.includes('/move/')) seen.push(path);
  });
  return seen;
}

test.describe('перенос в ленте слотов', () => {
  test('сдвиг с 14.10 на день раньше, 13.10 — в копилку: план → «да» → лента обновилась', async ({
    page,
    publish,
  }) => {
    publish.fillReelDays();
    const sent = posts(page);
    // Ролик, вернувшийся в копилку, показывает превью из батча — у подставных роликов его нет.
    await page.route(`**/api/batches/**/videos/${READY}/preview`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg"/>',
      }),
    );
    await page.goto(`/publishing?channel=${REEL}`);
    const feed = page.getByTestId('slot-feed');
    await expect(slot(page, READY)).toHaveAttribute('data-day', '2026-10-13');
    await feed.getByTestId('move-shift-toggle').click();
    const form = feed.getByTestId('move-shift-form');
    await form.getByTestId('move-shift-from').selectOption('2026-10-14');
    await expect(form.getByTestId('move-shift-unplace')).toBeChecked();
    await form.getByTestId('move-shift-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('move-plan-item')).toHaveCount(11);
    await expect(dialog.getByTestId('move-plan-item').first()).toContainText(
      'вт 13.10 → в копилку',
    );
    await expect(dialog.getByTestId('plan-head')).toContainText('можно перенести');
    const yes = dialog.getByTestId('move-shift-confirm');
    await expect(yes).toBeEnabled();
    expect(publish.move.state.written).toEqual([]);
    await yes.click();
    await expect(dialog).toBeHidden();
    await expect(feed.getByTestId('move-done')).toContainText(
      'Перенесено: 10 роликов, в копилку: 1 ролик',
    );
    await expect(slot(page, 'filler-1')).toHaveAttribute('data-day', '2026-10-13');
    await expect(slot(page, NOT_READY)).toHaveAttribute('data-day', '2026-10-14');
    await expect(slot(page, READY)).toHaveCount(0);
    await expect(
      page.getByTestId('stash').locator(`[data-testid="stash-row"][data-slug="${READY}"]`),
    ).toHaveCount(1);
    expect(sent).toEqual([`/api/publish/${REEL}/move/plan`, `/api/publish/${REEL}/move/confirm`]);
  });

  test('итог сборки карточки сразу после «да», лента ещё старая: прежние «день/ролик» не перечитываются', async ({
    page,
    publish,
  }) => {
    // CC-0178: подставная сборка карточки копилки (zootopia-2) кончается на третьем опросе и
    // перечитывает карточки дней. Пришла бы она между «да» и новой лентой — строки ленты ещё на
    // прежних днях, и чужие карточки по ним дали бы 404 (их уже перенесли). Здесь окно задано
    // нарочно: опросы сборки после первого ждут «да», лента после «да» отвечает через 3 с.
    // Ошибок в консоли быть не должно — их ловит фикстура `consoleErrors`.
    publish.fillReelDays();
    let confirmed = false;
    page.on('response', (r) => {
      if (r.url().includes('/move/confirm')) confirmed = true;
    });
    let polls = 0;
    await page.route(`**/api/publish/${REEL}/cards/build/run-*`, async (route) => {
      polls += 1;
      while (polls >= 2 && !confirmed) await new Promise((r) => setTimeout(r, 50));
      return route.fallback();
    });
    await page.route(`**/api/publish/${REEL}/queue*`, async (route) => {
      if (confirmed) await new Promise((r) => setTimeout(r, 3000));
      return route.fallback();
    });
    await page.route(`**/api/batches/**/videos/${READY}/preview`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'image/svg+xml',
        body: '<svg xmlns="http://www.w3.org/2000/svg"/>',
      }),
    );
    await page.goto(`/publishing?channel=${REEL}`);
    const feed = page.getByTestId('slot-feed');
    await expect(slot(page, READY)).toHaveAttribute('data-day', '2026-10-13');
    await feed.getByTestId('move-shift-toggle').click();
    const form = feed.getByTestId('move-shift-form');
    await form.getByTestId('move-shift-from').selectOption('2026-10-14');
    await form.getByTestId('move-shift-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('move-shift-confirm')).toBeEnabled();
    await dialog.getByTestId('move-shift-confirm').click();
    await expect(dialog).toBeHidden();
    await expect.poll(() => polls).toBeGreaterThanOrEqual(3);
    await expect(slot(page, 'filler-1')).toHaveAttribute('data-day', '2026-10-13');
    await expect(slot(page, READY)).toHaveCount(0);
  });

  test('телефон: строки с «Перенести…» и форма сдвига — без бокового скролла', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/publishing?channel=${REEL}`);
    const feed = page.getByTestId('slot-feed');
    await expect(slot(page, READY).getByTestId('move-open')).toBeVisible();
    await feed.getByTestId('move-shift-toggle').click();
    await expect(feed.getByTestId('move-shift-form')).toBeVisible();
    await slot(page, READY).getByTestId('move-open').click();
    await expect(slot(page, READY).getByTestId('move-form')).toBeVisible();
    await noSideScroll(page);
    await slot(page, READY).getByTestId('move-one-open').click();
    await expect(page.getByRole('alertdialog').getByTestId('move-plan-item')).toHaveCount(1);
    await noSideScroll(page);
  });
});
