// «Не положены: похоже на другую версию» на подставном API (`publish.otherVersion`, CC-0187, фабрика
// CC-0186, CF-0921): только чтение — название, батч, причина словами, ссылка на уже размещённую версию
// (или её имя и батч), «решает драйвер»; команды на виду нет, кнопок нет; без сцены блока нет.
// Компьютер и телефон, без бокового скролла.
import type { Page } from '@playwright/test';

import {
  OTHER_TITLE,
  OTHER_UNLINKED,
  OTHER_UNLINKED_TITLE,
  PLACED,
  REEL,
} from '../../src/mocks/publish';
import { expect, noSideScroll, test } from './fixtures';

const SIZES = {
  компьютер: { width: 1280, height: 800 },
  телефон: { width: 390, height: 844 },
} as const;

const row = (page: Page, slug: string) =>
  page
    .getByTestId('stash-other-version')
    .locator(`[data-testid="stash-other-row"][data-slug="${slug}"]`);

/** У подставных роликов нет превью: пустая картинка вместо 404 в консоли. */
async function open(page: Page, size: { width: number; height: number }) {
  await page.setViewportSize(size);
  await page.route('**/api/batches/**/videos/*/preview', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg"/>',
    }),
  );
  await page.goto(`/publishing?channel=${REEL}`);
  await expect(page.getByTestId('stash-list')).toBeVisible();
}

for (const [name, size] of Object.entries(SIZES)) {
  test.describe(`другая версия: ${name} @cc-0187`, () => {
    test('без сцены блока нет', async ({ page }) => {
      await open(page, size);
      await expect(page.getByTestId('stash-other-version')).toHaveCount(0);
      await noSideScroll(page);
    });

    test('строки: название, батч, причина, размещённая версия; драйвер решает; без кнопок', async ({
      page,
      publish,
    }) => {
      publish.otherVersion();
      await open(page, size);
      const block = page.getByTestId('stash-other-version');
      await expect(block.getByRole('heading')).toHaveText('Не положены: похоже на другую версию');
      await expect(block.getByTestId('stash-other-note')).toHaveText(
        'Решает драйвер фабрики, вам ничего делать не нужно.',
      );
      await expect(block.getByTestId('stash-other-row')).toHaveCount(2);

      const linked = row(page, PLACED);
      await expect(linked.getByTestId('stash-other-title')).toHaveText(
        OTHER_TITLE.replace(' #shorts', ''),
      );
      await expect(linked).toContainText('батч от 9.10');
      await expect(linked.getByTestId('stash-other-why')).toHaveText(
        'Темы нет в записи — новый ролик от версии не отличить.',
      );
      await expect(linked.getByTestId('stash-other-link')).toContainText('Delver, в ленте на');

      const unlinked = row(page, OTHER_UNLINKED);
      await expect(unlinked.getByTestId('stash-other-title')).toHaveText(
        OTHER_UNLINKED_TITLE.replace(' #shorts', ''),
      );
      await expect(unlinked.getByTestId('stash-other-why')).toHaveText(
        'Другая версия этого ролика уже размещена — эта в копилку не идёт.',
      );
      await expect(unlinked.getByTestId('stash-other-link')).toHaveCount(0);
      await expect(unlinked.getByTestId('stash-other-placed')).toHaveText(
        'Уже размещена: Night shift, батч от 30.09',
      );

      // Только чтение: кнопок нет, команда — лишь под свёрнутым «Подробнее».
      await expect(block.getByTestId('stash-other-row').getByRole('button')).toHaveCount(0);
      await expect(block.getByText(/--other-version-ok/).first()).toBeHidden();
      await noSideScroll(page);
      await block.getByText('Подробнее: для драйвера фабрики').click();
      await expect(block.getByText(/--other-version-ok/).first()).toBeVisible();
      await noSideScroll(page);
    });

    test('ссылка открывает слот уже размещённой версии', async ({ page, publish }) => {
      publish.otherVersion();
      await open(page, size);
      await row(page, PLACED).getByTestId('stash-other-link').click();
      await expect(page).toHaveURL(new RegExp(`slot=\\d{4}-\\d{2}-\\d{2}%2F${PLACED}`));
      await expect(page.getByTestId('studio-card')).toBeVisible();
      await noSideScroll(page);
    });
  });
}
