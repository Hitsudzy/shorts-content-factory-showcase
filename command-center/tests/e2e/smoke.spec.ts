import { expect, test } from './fixtures';

test('приложение открывается, показывает 14 табов и статус подставного API', async ({ page }) => {
  await page.goto('/');

  const tabs = page.getByRole('navigation', { name: 'Разделы' }).getByRole('link');
  await expect(tabs).toHaveCount(14);
  await expect(page.getByTestId('api-status')).toHaveText('Фабрика на связи');

  await page.getByRole('link', { name: 'Вопросы', exact: true }).click();
  await expect(page).toHaveURL(/\/questions$/);
  await expect(page.getByRole('heading', { name: 'Вопросы' })).toBeVisible();
});

test('прямой заход на раздел по URL работает', async ({ page }) => {
  await page.goto('/maintenance');
  await expect(page.getByRole('heading', { name: 'Обслуживание и расход' })).toBeVisible();
});
