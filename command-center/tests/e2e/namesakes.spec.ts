// Тёзки на подставном API (`publish.namesakes`, CC-0183, фабрика CC-0182, CF-0920): два ролика одного
// имени в копилке; строка — батч плюс имя, метка батча рядом с именем только у них. Перенос, снятие и
// размещение второго не трогают первого; ссылка заметки открывает своего; голое имя — понятный отказ
// `namesakes`; файл `<имя>~<батч>` нигде не виден. Компьютер и телефон, без бокового скролла.
import type { Page } from '@playwright/test';

import { PLACED, REEL } from '../../src/mocks/publish';
import {
  TWIN,
  TWIN_NEW,
  TWIN_OF_PLACED,
  TWIN_OLD,
  TWIN_RESERVE,
  TWIN_TITLES,
} from '../../src/mocks/stash';
import { expect, noSideScroll, test } from './fixtures';

const SIZES = {
  компьютер: { width: 1280, height: 800 },
  телефон: { width: 390, height: 844 },
} as const;

const row = (page: Page, slug: string, batch?: string) =>
  page
    .getByTestId('stash')
    .locator(
      `[data-testid="stash-row"][data-slug="${slug}"]${batch ? `[data-batch="${batch}"]` : ''}`,
    );
const slot = (page: Page, slug: string) =>
  page.getByTestId('slot-feed').locator(`[data-testid="slot"][data-slug="${slug}"]`);
const gone = (page: Page, slug: string, batch?: string) =>
  page
    .getByTestId('slot-feed')
    .locator(
      `[data-testid="feed-withdrawn-row"][data-slug="${slug}"]${batch ? `[data-batch="${batch}"]` : ''}`,
    );

/** У подставных роликов нет превью: пустая картинка вместо 404 в консоли. */
async function open(page: Page, size: { width: number; height: number }, extra = '') {
  await page.setViewportSize(size);
  await page.route('**/api/batches/**/videos/*/preview', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'image/svg+xml',
      body: '<svg xmlns="http://www.w3.org/2000/svg"/>',
    }),
  );
  await page.goto(`/publishing?channel=${REEL}${extra}`);
  await expect(page.getByTestId('stash-list')).toBeVisible();
}

for (const [name, size] of Object.entries(SIZES)) {
  test.describe(`тёзки: ${name} @cc-0183`, () => {
    test('две строки с батчем рядом с именем; `~` нигде нет', async ({ page, publish }) => {
      publish.namesakes();
      await open(page, size);
      await expect(row(page, TWIN)).toHaveCount(2);
      await expect(row(page, TWIN, TWIN_OLD).getByTestId('stash-namesake')).toHaveText(
        'батч от 24.09',
      );
      await expect(row(page, TWIN, TWIN_NEW).getByTestId('stash-namesake')).toHaveText(
        'батч от 9.10',
      );
      await expect(row(page, TWIN, TWIN_NEW).getByTestId('stash-batch')).toHaveCount(0);
      await expect(row(page, TWIN, TWIN_NEW).getByText(/батч от/)).toHaveCount(1);
      await expect(page.getByTestId('stash')).not.toContainText('~');
      await expect(page.getByTestId('slot-feed')).not.toContainText('~');
      await noSideScroll(page);
    });

    test('размещение второго тёзки не трогает первого', async ({ page, publish }) => {
      publish.namesakes();
      await open(page, size);
      await row(page, TWIN, TWIN_NEW).getByTestId('stash-pick').click();
      await expect(row(page, TWIN, TWIN_OLD).getByTestId('stash-pick')).not.toBeChecked();
      await page.getByTestId('stash-place-open').click();
      const dialog = page.getByRole('alertdialog');
      const item = dialog.getByTestId('stash-plan-item');
      await expect(item).toHaveAttribute('data-batch', TWIN_NEW);
      await expect(item).toContainText('батч от 9.10');
      await noSideScroll(page);
      await dialog.getByTestId('stash-place-confirm').click();
      await expect(dialog).toBeHidden();
      await expect(row(page, TWIN)).toHaveCount(1);
      await expect(row(page, TWIN)).toHaveAttribute('data-batch', TWIN_OLD);
      await expect(slot(page, TWIN)).toHaveCount(1);
    });

    test('возврат второго тёзки из запаса не трогает первого', async ({ page, publish }) => {
      publish.namesakes();
      await open(page, size);
      await expect(gone(page, TWIN_RESERVE)).toHaveCount(2);
      const back = gone(page, TWIN_RESERVE, TWIN_NEW);
      await back.getByTestId('reserve-return-toggle').click();
      await back.getByTestId('reserve-return-open').click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByTestId('move-plan-item')).toHaveAttribute('data-batch', TWIN_NEW);
      await noSideScroll(page);
      await dialog.getByTestId('reserve-return-confirm').click();
      await expect(dialog).toBeHidden();
      await expect(gone(page, TWIN_RESERVE)).toHaveCount(1);
      await expect(gone(page, TWIN_RESERVE)).toHaveAttribute('data-batch', TWIN_OLD);
      await expect(row(page, TWIN_RESERVE)).toHaveCount(1);
      await expect(row(page, TWIN_RESERVE)).toHaveAttribute('data-batch', TWIN_OLD);
      await expect(slot(page, TWIN_RESERVE)).toHaveCount(1);
    });

    test('снятие ролика ленты с тёзкой в копилке: тёзка остаётся в копилке', async ({
      page,
      publish,
    }) => {
      publish.namesakes();
      await open(page, size);
      await slot(page, PLACED).getByTestId('move-withdraw-open').click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByTestId('withdraw-studio-first')).toBeVisible();
      const yes = dialog.getByTestId('move-withdraw-confirm');
      await expect(yes).toBeEnabled();
      await yes.click();
      await expect(dialog).toBeHidden();
      await expect(slot(page, PLACED)).toHaveCount(0);
      await expect(gone(page, PLACED)).toHaveCount(1);
      await expect(row(page, PLACED)).toHaveCount(2);
      await expect(row(page, PLACED, TWIN_OF_PLACED).getByTestId('stash-reserve')).toHaveCount(0);
      await noSideScroll(page);
    });

    test('ссылка заметки открывает своего тёзку', async ({ page, publish }) => {
      publish.namesakes();
      await open(page, size);
      await gone(page, TWIN_RESERVE, TWIN_NEW).getByTestId('feed-withdrawn-note').click();
      const card = page.getByTestId('studio-card');
      await expect(card).toHaveAttribute('data-batch', TWIN_NEW);
      await expect(card).toContainText(TWIN_TITLES[`${TWIN_NEW}/${TWIN_RESERVE}`]!.split(' #')[0]!);
      await expect(card).not.toContainText('~');
      await expect(page).toHaveURL(new RegExp(`batch=${encodeURIComponent(TWIN_NEW)}`));
      await noSideScroll(page);
    });

    test.describe('отказ', () => {
      test.use({ expectCleanConsole: false });

      test('ссылка без батча: слова центра со ссылкой на копилку, повтора нет', async ({
        page,
        publish,
      }) => {
        publish.namesakes();
        await open(page, size, `&slot=_queue/${TWIN}`);
        const card = page.getByTestId('studio-card');
        const words = card.getByTestId('studio-namesakes');
        await expect(words).toHaveText(
          'Роликов с этим именем несколько. Откройте нужный в копилке: у каждого своя метка батча.',
        );
        await expect(words).not.toContainText(TWIN_OLD);
        await expect(card.getByRole('button', { name: 'Повторить' })).toHaveCount(0);
        // Строка API — под «Подробнее», свёрнута.
        await expect(card.getByText(/Назовите батч/)).toBeHidden();
        await noSideScroll(page);
        await words.getByTestId('studio-namesakes-stash').click();
        await expect(page).toHaveURL(/#stash$/);
        await expect(page.getByTestId('stash')).toBeInViewport();
      });
    });

    test('ссылка с батчем открывает своего, не второго', async ({ page, publish }) => {
      publish.namesakes();
      await open(page, size, `&slot=_queue/${TWIN}&batch=${TWIN_OLD}`);
      const card = page.getByTestId('studio-card');
      await expect(card).toContainText('The First Cut');
      await expect(card).not.toContainText('The Studio Recut');
      await noSideScroll(page);
    });
  });
}
