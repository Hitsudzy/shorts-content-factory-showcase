// Цена воротец (CC-0115 → CC-0100) на «Статистике», подставной API (src/mocks/gates.ts): правила
// словами, вердикт с подсказкой, «не измерена» с подсказкой, подробности правила, телефон.
import { expect, noSideScroll, openTip, test } from './fixtures';

test('цена воротец: правила, вердикт, «не измерена», подробности', async ({ page }) => {
  await page.goto('/stats?channel=example-film');
  const card = page.getByTestId('gate-prices');
  await expect(card.getByTestId('gate-rule')).toHaveCount(5);
  const tail = card.locator('[data-rule="content_researcher.tail_after_last_anchor"]');
  await expect(tail.getByTestId('gate-price')).toHaveText('Отказ убил бы 3 из 15 готовых роликов');
  await openTip(page, tail.getByText('предупреждение'), /только предупреждает/);
  const none = card.locator('[data-rule="footage_indexer.no_second_source"]');
  await openTip(page, none.getByTestId('gate-price'), /не цена ноль/);
  await tail.getByText('Подробнее', { exact: true }).click();
  await expect(tail).toContainText('убил бы: example-film/2026-10-04T1825Z: delver');
});

test('цена воротец на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/stats?channel=example-film');
  await expect(page.getByTestId('gate-rule')).toHaveCount(5);
  await noSideScroll(page);
});
