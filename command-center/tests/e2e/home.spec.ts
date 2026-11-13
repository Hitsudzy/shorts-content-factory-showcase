// Главная: карточка «Каналы» на подставном API каналов (src/mocks/channels.ts) — список,
// состояние, переход в экран канала, «подробнее», ошибка загрузки, телефон.
import { expect, openTip, test } from './fixtures';

test('«Каналы» на главной: состояние каждого канала, переход в канал и в список', async ({
  page,
  channels,
}) => {
  channels.lock('example-tech', 'Идёт батч канала example-tech.');
  await page.goto('/');
  const card = page.getByTestId('channels-card');
  await expect(card.getByRole('heading', { level: 2 })).toHaveText('3 канала');
  await expect(card.getByText(/Скоро/)).toHaveCount(0);

  const row = (id: string) => card.getByTestId(`home-channel-${id}`);
  await expect(row('example-film').getByText('в работе', { exact: true })).toBeVisible();
  await expect(row('example-science').getByText('готовится', { exact: true })).toBeVisible();
  await expect(row('example-science').getByText('оформлен, конвейера пока нет')).toBeVisible();
  await expect(row('example-tech').getByText('идёт батч', { exact: true })).toBeVisible();

  // Пояснение метки — в тултипе, номера и прежние имена — только под «подробнее».
  await openTip(page, row('example-tech').getByText('идёт батч', { exact: true }), 'правка закрыта');
  const former = card.getByText(/прежние имена: legacy-film/);
  await expect(former).toBeHidden();
  await card.getByText('Подробнее').click();
  await expect(former).toBeVisible();
  await expect(card.getByText(/канал example-tech · ревизия [0-9a-f]{12}/)).toBeVisible();

  await row('example-film').getByRole('link', { name: 'ExampleFilm' }).click();
  await expect(page).toHaveURL(/\/channels\/example-film$/);
  await expect(page.getByRole('heading', { level: 1, name: 'ExampleFilm' })).toBeVisible();

  await page.goBack();
  await card.getByRole('link', { name: 'Все', exact: true }).click();
  await expect(page).toHaveURL(/\/channels$/);
  await expect(page.getByTestId('channels-count')).toHaveText('3 канала');
});

test('на главной к каналам — только чтение: ни одного запроса, кроме GET', async ({ page }) => {
  const calls: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/api/')) calls.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  await page.goto('/');
  await expect(page.getByTestId('channels-card').getByRole('heading', { level: 2 })).toHaveText(
    '3 канала',
  );
  expect(calls.filter((c) => !c.startsWith('GET '))).toEqual([]);
  expect(calls).toContain('GET /api/channels');
  // Тяжёлые карточки каналов главная не грузит — ей хватает списка.
  expect(calls.filter((c) => c.startsWith('GET /api/channels/'))).toEqual([]);
});

test.describe('список каналов не загрузился', () => {
  test.use({ expectCleanConsole: false });

  test('ошибка с «Повторить», остальная главная работает', async ({ page }) => {
    let down = true;
    await page.route('**/api/channels', (route) =>
      down ? route.fulfill({ status: 503, body: 'down' }) : route.fallback(),
    );
    await page.goto('/');
    const card = page.getByTestId('channels-card');
    const alert = card.getByRole('alert');
    await expect(alert).toContainText('Каналы не загрузились', { timeout: 15_000 });
    await expect(page.getByTestId('factory-card').getByRole('alert')).toHaveCount(0);

    down = false;
    await alert.getByRole('button', { name: 'Повторить' }).click();
    await expect(card.getByRole('heading', { level: 2 })).toHaveText('3 канала');
    await expect(card.getByRole('alert')).toHaveCount(0);
  });
});

test.describe('телефон', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  test('строки каналов помещаются в карточку, без прокрутки вбок', async ({ page }) => {
    await page.goto('/');
    const card = page.getByTestId('channels-card');
    await expect(card.getByRole('heading', { level: 2 })).toHaveText('3 канала');
    const box = (await card.boundingBox())!;
    for (const id of ['example-film', 'example-science', 'example-tech']) {
      const badge = (await card
        .getByTestId(`home-channel-${id}`)
        .locator('[data-slot="status"]')
        .boundingBox())!;
      expect(badge.x + badge.width).toBeLessThanOrEqual(box.x + box.width);
    }
    const doc = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      width: document.documentElement.clientWidth,
    }));
    expect(doc.scroll).toBeLessThanOrEqual(doc.width);
  });
});
