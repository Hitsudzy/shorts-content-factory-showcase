// Кандидаты в банк мемов (CC-0115 → CC-0103) на подставном API (src/mocks/memeCandidates.ts):
// сводка, группы по растяжке с подсказкой, свёрнутые «малы», телефон без прокрутки вбок.
import { expect, noSideScroll, openTip, test } from './fixtures';

test('кандидаты в банк Tech: сводка, группы, подсказка растяжки', async ({ page }) => {
  await page.goto('/memes?channel=example-tech');
  const card = page.getByTestId('meme-candidates');
  await expect(card.getByTestId('candidates-summary')).toContainText('Ждут вашего «да»: 2');
  const pass = card.locator('[data-group="pass"]');
  await expect(pass.getByTestId('candidate')).toHaveCount(6);
  await openTip(page, pass.getByText('проходит').first(), /растягивать/);
  const fail = card.locator('[data-group="fail"]');
  await expect(fail.getByTestId('candidate').first()).toBeHidden();
  await fail.locator('summary').click();
  await expect(fail.getByTestId('candidate')).toHaveCount(2);
});

test('кандидаты на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/memes?channel=example-tech');
  await expect(page.getByTestId('meme-candidates').getByTestId('candidate').first()).toBeVisible();
  await noSideScroll(page);
});
