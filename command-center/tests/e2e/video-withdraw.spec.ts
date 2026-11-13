// «Снять окончательно…» у ролика (CC-0115 шаг 3) на «Роликах», подставной API (src/mocks/withdraw.ts):
// план, ответ по-русски с именем ролика набирается сам, ушёл как есть; телефон без прокрутки вбок.
import { PAST } from '../../src/mocks/batches';
import { expect, noSideScroll, test } from './fixtures';

const URL = `/videos?batch=${encodeURIComponent(PAST)}&v=rink-rivals`;

test('снять окончательно: план, ответ с именем, снято', async ({ page, videos }) => {
  await page.goto(URL);
  const box = page.getByTestId('withdraw');
  await box.getByTestId('withdraw-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('withdraw-plan-status')).toContainText('после снятия');
  await expect(dialog.getByTestId('withdraw-confirm')).toBeDisabled();
  await dialog.getByTestId('withdraw-yes').pressSequentially('да');
  await expect(dialog.getByTestId('withdraw-yes-hint')).toContainText(
    'Впишите имя из подписи выше',
  );
  await dialog.getByTestId('withdraw-yes').fill('');
  await dialog.getByTestId('withdraw-yes').pressSequentially('снимаю rink-rivals');
  await dialog.getByTestId('withdraw-confirm').click();
  await expect(box.getByTestId('withdraw-done')).toContainText('Ролик снят окончательно');
  expect(videos.withdrawal.state.answers).toEqual(['снимаю rink-rivals']);
});

test('снять окончательно на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(URL);
  await page.getByTestId('withdraw-open').click();
  await expect(page.getByRole('alertdialog').getByTestId('withdraw-yes')).toBeVisible();
  await noSideScroll(page);
});
