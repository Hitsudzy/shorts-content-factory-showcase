// «Правил в Studio» и отмена (CC-0115 шаг 3) на «Публикации», подставной API (src/mocks/publish.ts):
// последний ролик серии, план с серией после, «да» набирается, серия заново; телефон без
// прокрутки вбок.
import { expect, noSideScroll, test } from './fixtures';

test('правка в Studio: план, «да» набирается, серия заново', async ({ page, publish }) => {
  await page.goto('/publishing');
  const block = page.getByTestId('state-studio');
  await expect(block).toContainText('2 из 5');
  await block.getByTestId('studio-edited-toggle').click();
  await block.getByTestId('studio-edited-note').fill('поправил описание');
  await block.getByTestId('studio-edited-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('edited-plan-streak')).toContainText('0 из 5');
  await expect(dialog.getByTestId('studio-edited-confirm')).toBeDisabled();
  await dialog.getByTestId('studio-edited-yes').pressSequentially('да');
  await dialog.getByTestId('studio-edited-confirm').click();
  await expect(block.getByTestId('studio-edited-done')).toContainText('Правка в Studio отмечена');
  await expect(block).toContainText('0 из 5');
  expect(publish.writes.state.written.map((w) => w.action)).toEqual(['studio_edited']);
});

test('снять отметку: план → «да» → снято', async ({ page }) => {
  await page.goto('/publishing');
  const block = page.getByTestId('state-studio');
  await block.getByTestId('studio-unedit-open').click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByTestId('studio-unedit-yes').pressSequentially('да');
  await dialog.getByTestId('studio-unedit-confirm').click();
  await expect(block.getByTestId('studio-edited-done')).toContainText('Отметка о правке снята');
});

test('правка в Studio на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/publishing');
  const block = page.getByTestId('state-studio');
  await block.getByTestId('studio-edited-toggle').click();
  await block.getByTestId('studio-edited-other').click();
  await expect(block.getByTestId('studio-edited-link')).toBeVisible();
  await noSideScroll(page);
});
