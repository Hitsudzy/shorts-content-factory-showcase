// Приём кандидатов в банк мемов (CC-0115 шаг 3) на «Мемах», подставной API (src/mocks/memes.ts):
// выбор, текст записи, план, «да», набранное пользователем, итог; телефон без прокрутки вбок.
import { expect, noSideScroll, test } from './fixtures';

test('приём кандидатов: план, «да» набирается, итог', async ({ page, memes }) => {
  await page.goto('/memes?channel=example-tech');
  const card = page.getByTestId('meme-candidates');
  await card.getByTestId('meme-accept-toggle').click();
  await expect(card.getByTestId('meme-accept-item')).toHaveCount(2);
  const fine = card.locator('[data-testid="meme-accept-item"][data-id="this-is-fine"]');
  await fine.getByTestId('meme-accept-description').fill('всё горит, а мы спокойны');
  await card.getByTestId('meme-accept-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('accept-plan-take')).toContainText('This Is Fine');
  await expect(dialog.getByTestId('meme-accept-confirm')).toBeDisabled();
  await dialog.getByTestId('meme-accept-yes').pressSequentially('да');
  await dialog.getByTestId('meme-accept-confirm').click();
  await expect(card.getByTestId('meme-accept-done')).toContainText('Принято в банк: 2 шаблона');
  expect(memes.accept.answers).toEqual(['да']);
});

test('приём кандидатов на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/memes?channel=example-tech');
  const card = page.getByTestId('meme-candidates');
  await card.getByTestId('meme-accept-toggle').click();
  await expect(card.getByTestId('meme-accept-item')).toHaveCount(2);
  await noSideScroll(page);
});
