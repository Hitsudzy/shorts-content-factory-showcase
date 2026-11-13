// «Данные канала» (CC-0115 → CC-0101/0102) на подставном API (src/mocks/channelData.ts): вкладка
// открывается из табов страницы канала, концовка, источники с подсказкой, партнёрские ссылки,
// «подробнее», телефон без прокрутки вбок.
import { expect, noSideScroll, openTip, test } from './fixtures';

test('вкладка «Данные канала»: концовка, источники, партнёрские ссылки', async ({ page }) => {
  await page.goto('/channels/example-film');
  await page.getByRole('tab', { name: 'Данные канала' }).click();
  await expect(page).toHaveURL(/tab=data/);
  const d = page.getByTestId('channel-data');
  await expect(d.getByTestId('ending-probe')).toHaveText('3 с · 1080×1920 · 30 к/с · со звуком');
  await expect(page.getByTestId('save-bar')).toHaveCount(0);
  await openTip(page, d.getByText('collider.com'), /только ссылка/);
  const src = d.getByTestId('fact-sources');
  await src.getByText('Подробнее', { exact: true }).click();
  await expect(src).toContainText('1: hollywood_reporter');
});

test('«Данные канала» Tech на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels/example-tech?tab=data');
  const d = page.getByTestId('channel-data');
  await expect(d.getByTestId('affiliate-products')).toContainText('Meta Quest 4');
  await noSideScroll(page);
});
