// Разнообразие ленты (CC-0115 → CC-0108) на «Статистике», подставной API (src/mocks/diversity.ts):
// оси словами с долями и подсказкой «N из M», переключатели «Вся фабрика»/«Вся лента», битый
// журнал приёмки, телефон без прокрутки вбок.
import { expect, noSideScroll, openTip, test } from './fixtures';

test('разнообразие ленты канала, переключатели, подсказка доли', async ({ page, analytics }) => {
  await page.goto('/stats?channel=example-film');
  const b = page.getByTestId('stats-diversity');
  await expect(b.getByTestId('diversity-axis')).toHaveCount(4);
  const first = b.locator('[data-axis="pattern"]').getByTestId('diversity-value').first();
  await expect(first).toContainText('список');
  await openTip(page, first.locator('[tabindex="0"]'), /из 9 роликов/);
  await b.getByTestId('diversity-all').click();
  await expect(b).toContainText('вся фабрика · последние 10 · посчитано 10 роликов');
  await b.getByTestId('diversity-whole').click();
  await expect(b).toContainText('посчитано 12 роликов');
  expect(analytics.state.calls).toContain('/api/analytics/diversity?last=0');
});

test('битый журнал приёмки — «журнал приёмки не читается»; телефон', async ({
  page,
  analytics,
}) => {
  analytics.state.diversityLog = 'broken';
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/stats?channel=example-film');
  const b = page.getByTestId('stats-diversity');
  await expect(b.getByTestId('diversity-log-error')).toContainText('Журнал приёмки не читается');
  await b.getByText('Подробнее', { exact: true }).click();
  await expect(b).toContainText('not JSON');
  await noSideScroll(page);
});
