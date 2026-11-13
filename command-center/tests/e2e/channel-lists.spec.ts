// Правка списков канала и сборка концовки (CC-0115 шаг 3) на вкладке «Данные канала»,
// подставной API (src/mocks/channelLists.ts, channelData.ts, rights.ts): план → «да», набранное
// пользователем; сменившийся файл — «Список изменился, откройте заново»; телефон без прокрутки.
import { expect, noSideScroll, test } from './fixtures';

test('партнёрские ссылки по строкам: убрать товар → план → «да» → записано', async ({
  page,
  channels,
}) => {
  await page.goto('/channels/example-tech?tab=data');
  const card = page.getByTestId('affiliate');
  await card.getByTestId('list-affiliate-toggle').click();
  const products = card.getByTestId('rows-products');
  await expect(products.getByTestId('rows-products-row')).toHaveCount(2);
  await products.getByTestId('rows-products-remove').nth(1).click();
  await card.getByTestId('list-affiliate-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('list-plan-changes')).toContainText('изменится');
  await expect(dialog.getByTestId('list-affiliate-confirm')).toBeDisabled();
  await dialog.getByTestId('list-affiliate-yes').pressSequentially('да');
  await dialog.getByTestId('list-affiliate-confirm').click();
  await expect(card.getByTestId('list-done')).toContainText('Список записан');
  await expect(card.getByTestId('affiliate-counts')).toContainText('товаров: 1');
  expect(channels.data.lists.state.written).toEqual(['example-tech affiliate']);
});

test('источники фактов: файл сменился — «Список изменился, откройте заново»', async ({
  page,
  channels,
}) => {
  await page.goto('/channels/example-film?tab=data');
  const card = page.getByTestId('fact-sources');
  await card.getByTestId('list-fact-sources-toggle').click();
  channels.data.over['fact-sources example-film'] = { tiers: { '1': [] } };
  await card.getByTestId('list-fact-sources-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('list-changed')).toContainText(
    'Список изменился, откройте заново',
  );
  await expect(dialog.getByTestId('list-fact-sources-yes')).toHaveCount(0);
});

test('партнёрские ссылки по строкам на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels/example-tech?tab=data');
  const card = page.getByTestId('affiliate');
  await card.getByTestId('list-affiliate-toggle').click();
  await expect(card.getByTestId('rows-products-row')).toHaveCount(2);
  await noSideScroll(page);
});

test('концовка Tech на телефоне: план, «да», рендер запущен', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels/example-tech?tab=data');
  const ending = page.getByTestId('ending');
  await ending.getByTestId('ending-render-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('plan-head')).toContainText('можно собрать');
  await noSideScroll(page);
  await dialog.getByTestId('ending-render-yes').pressSequentially('да');
  await dialog.getByTestId('ending-render-confirm').click();
  await expect(ending.getByTestId('ending-started')).toContainText('Рендер концовки запущен');
});
