// Пробное сообщение (CC-0115 шаг 3) на «Уведомлениях», подставной API (src/mocks/notify.ts):
// план без отправки, «да» набирается, ответ по каналам; телефон без прокрутки вбок.
import { expect, noSideScroll, test } from './fixtures';

test('пробное сообщение: план, «да», отправлено', async ({ page, notify }) => {
  await page.goto('/notifications');
  const box = page.getByTestId('test-send');
  await box.getByTestId('test-send-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('test-plan-channel')).toHaveCount(3);
  await expect(dialog.getByTestId('test-send-confirm')).toBeDisabled();
  expect(notify.state.testSent).toEqual([]);
  await dialog.getByTestId('test-send-yes').pressSequentially('да');
  await dialog.getByTestId('test-send-confirm').click();
  await expect(box.getByTestId('test-send-done')).toContainText('Пробное сообщение отправлено');
  expect(notify.state.testSent).toHaveLength(1);
});

test('пробное сообщение на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/notifications');
  await page.getByTestId('test-send-open').click();
  await expect(page.getByRole('alertdialog').getByTestId('test-send-yes')).toBeVisible();
  await noSideScroll(page);
});
