// Политика ленты 04.11 на подставном API (`publish.feedPolicy`, CC-0180): копилка — новостные и
// бессрочные, запас, горизонт, `news_why` как есть; «Разложить автоматически» — план с порядком и
// пропущенными, `force` под «подробнее»; «Снять из ленты в запас…» — до «да» окно говорит про Studio,
// ролик — в «Снято из ленты»; возврат на день — новой загрузки нет. Компьютер и телефон, без бокового
// скролла. Нигде не предлагается опубликовать сразу.
import type { Page } from '@playwright/test';

import { PLACED, REEL } from '../../src/mocks/publish';
import {
  STASH_EVERGREEN,
  STASH_FRESH_NEWS,
  STASH_NO_CARD,
  STASH_RESERVE,
  STASH_STALE,
} from '../../src/mocks/stash';
import { expect, noSideScroll, test } from './fixtures';

const SIZES = {
  компьютер: { width: 1280, height: 800 },
  телефон: { width: 390, height: 844 },
} as const;

const FORBIDDEN = /Опубликовать сейчас|Открытый доступ/;

const row = (page: Page, slug: string) =>
  page.getByTestId('stash').locator(`[data-testid="stash-row"][data-slug="${slug}"]`);
const slot = (page: Page, slug: string) =>
  page.getByTestId('slot-feed').locator(`[data-testid="slot"][data-slug="${slug}"]`);
const gone = (page: Page, slug: string) =>
  page.getByTestId('slot-feed').locator(`[data-testid="feed-withdrawn-row"][data-slug="${slug}"]`);

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
  test.describe(`политика ленты: ${name} @cc-0180`, () => {
    test('копилка: новостные и бессрочные, запас, горизонт, почему новость', async ({
      page,
      publish,
    }) => {
      publish.feedPolicy();
      await open(page, size);
      const stash = page.getByTestId('stash');
      await expect(stash.getByTestId('stash-summary')).toHaveText(
        'Новостных: 2 · бессрочных: 2 · в запасе: 1',
      );
      await expect(stash.getByTestId('stash-horizon')).toContainText('Лента вперёд на 3 дня');
      await expect(stash.getByTestId('stash-group')).toHaveCount(2);
      await expect(stash.getByTestId('stash-group').first()).toHaveAttribute('data-kind', 'news');
      await expect(row(page, STASH_FRESH_NEWS).getByTestId('stash-news-why')).toContainText(
        '«трейлер выйдет в ноябре»',
      );
      await expect(row(page, STASH_FRESH_NEWS).getByTestId('stash-stale-at')).toContainText(
        'Устареет',
      );
      await expect(row(page, STASH_STALE).getByTestId('stash-stale-at')).toContainText(
        'Срок вышел',
      );
      await expect(row(page, STASH_RESERVE).getByTestId('stash-reserve')).toBeVisible();
      await expect(row(page, STASH_EVERGREEN).getByTestId('stash-news')).toHaveCount(0);
      await noSideScroll(page);
    });

    test('авто-раскладка: порядок, пропущенные с причинами, одно «да», итог', async ({
      page,
      publish,
    }) => {
      publish.feedPolicy({ noCard: true });
      await open(page, size);
      const stash = page.getByTestId('stash');
      await stash.getByTestId('stash-auto-open').click();
      const dialog = page.getByRole('alertdialog');
      // Про порядок — одна фраза; отсчёт на кнопке назван словами.
      await expect(dialog.getByText('Порядок выбирает фабрика', { exact: false })).toHaveCount(1);
      await expect(dialog.getByText('Порядок выбрала фабрика', { exact: false })).toHaveCount(0);
      await expect(dialog.getByTestId('stash-auto-confirm')).toHaveText(
        /^Разложить · план ещё \d:\d\d$/,
      );
      await expect(dialog.getByTestId('stash-plan-item')).toHaveCount(1);
      await expect(dialog.getByTestId('stash-plan-item')).toHaveAttribute(
        'data-slug',
        STASH_FRESH_NEWS,
      );
      const skip = (slug: string) =>
        dialog.locator(`[data-testid="stash-plan-skip"][data-slug="${slug}"]`);
      await expect(skip(STASH_STALE)).toHaveAttribute('data-reason', 'stale_news');
      await expect(skip(STASH_STALE)).toContainText('Новость устарела, можно поставить вручную');
      await expect(skip(STASH_STALE)).not.toContainText('force');
      await expect(skip(STASH_NO_CARD)).toHaveAttribute('data-reason', 'no_card');
      await expect(skip(STASH_EVERGREEN)).toHaveAttribute('data-reason', 'beyond_horizon');
      await expect(dialog).not.toContainText(FORBIDDEN);
      await noSideScroll(page);
      const yes = dialog.getByTestId('stash-auto-confirm');
      await expect(yes).toBeEnabled();
      await yes.click();
      await expect(dialog).toBeHidden();
      await expect(stash.getByTestId('stash-done')).toContainText('Разложено автоматически');
      await expect(stash.getByTestId('stash-done-skipped')).toContainText('Ждёт в копилке');
      await expect(slot(page, STASH_FRESH_NEWS)).toHaveAttribute('data-day', '2026-10-13');
    });

    test('`force` спрятан под «подробнее»; с отметкой устаревшая новость в плане', async ({
      page,
      publish,
    }) => {
      publish.feedPolicy({ days: 5 });
      await open(page, size);
      const stash = page.getByTestId('stash');
      const more = stash.getByTestId('stash-auto-more');
      const force = more.getByTestId('stash-auto-force');
      await expect(force).toBeHidden();
      await more.getByText('Подробнее: устаревшие новости').click();
      await expect(more).toContainText('Брать и устаревшие новости');
      await force.check();
      await stash.getByTestId('stash-auto-open').click();
      const dialog = page.getByRole('alertdialog');
      const stale = dialog.locator(`[data-testid="stash-plan-item"][data-slug="${STASH_STALE}"]`);
      await expect(stale.getByTestId('stash-plan-warning')).toHaveAttribute('data-kind', 'stale');
      await expect(stale.getByTestId('stash-plan-warning')).toContainText('Новость устарела');
      await noSideScroll(page);
    });

    test('снять из ленты в запас: окно говорит про Studio до «да», ролик в «Снято из ленты»', async ({
      page,
      publish,
    }) => {
      publish.feedPolicy();
      await open(page, size);
      const feed = page.getByTestId('slot-feed');
      await slot(page, PLACED).getByTestId('move-withdraw-open').click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByTestId('withdraw-studio-first')).toHaveText(
        'Сначала поставьте в Studio «Ограниченный доступ»',
      );
      const note = dialog.getByTestId('move-studio-withdraw');
      await expect(note).toContainText('Центр Studio не проверяет');
      await expect(note).toContainText('уберите дату вручную');
      // Сама строка фабрики — под «подробнее».
      await expect(note.getByTestId('move-studio-line')).toBeHidden();
      await expect(dialog).not.toContainText(FORBIDDEN);
      await noSideScroll(page);
      const yes = dialog.getByTestId('move-withdraw-confirm');
      await expect(yes).toBeEnabled();
      expect(publish.move.state.written).toEqual([]);
      await yes.click();
      await expect(dialog).toBeHidden();
      await expect(feed.getByTestId('move-done')).toContainText('Снято из ленты');
      await expect(gone(page, PLACED)).toBeVisible();
      await expect(slot(page, PLACED)).toHaveCount(0);
      await expect(row(page, PLACED).getByTestId('stash-reserve')).toBeVisible();
      await noSideScroll(page);
    });

    test('возврат из запаса: новой загрузки нет, дату в Studio вручную, ролик снова в ленте', async ({
      page,
      publish,
    }) => {
      publish.feedPolicy();
      await open(page, size);
      const feed = page.getByTestId('slot-feed');
      const back = gone(page, STASH_RESERVE);
      await expect(back.getByTestId('feed-withdrawn-sub')).toContainText('Ограниченный доступ');
      await expect(back.getByTestId('feed-withdrawn-note')).toBeVisible();
      await expect(back.getByTestId('feed-withdrawn-link')).toBeVisible();
      await back.getByTestId('reserve-return-toggle').click();
      await expect(back.getByTestId('reserve-no-upload')).toContainText('Новой загрузки нет');
      await expect(back.getByTestId('reserve-return-day')).toHaveValue('2026-10-13');
      await back.getByTestId('reserve-return-open').click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByTestId('move-studio-title')).toHaveText(
        'Дату в Studio поставить вручную',
      );
      await expect(dialog.getByTestId('move-studio-no-upload')).toContainText('новой загрузки нет');
      await expect(dialog.getByTestId('move-plan-where')).toContainText('из запаса →');
      await expect(dialog).not.toContainText(FORBIDDEN);
      await noSideScroll(page);
      const yes = dialog.getByTestId('reserve-return-confirm');
      await expect(yes).toBeEnabled();
      await yes.click();
      await expect(dialog).toBeHidden();
      await expect(feed.getByTestId('move-done').getByTestId('move-studio-title')).toHaveText(
        'Теперь поставьте дату в Studio вручную',
      );
      await expect(slot(page, STASH_RESERVE)).toHaveAttribute('data-day', '2026-10-13');
      await expect(feed.getByTestId('feed-withdrawn')).toHaveCount(0);
    });

    test('горизонт в ленте: свободный день дальше него — не пропуск', async ({ page, publish }) => {
      publish.feedPolicy();
      await open(page, size);
      const beyond = page
        .getByTestId('slot-feed')
        .locator('[data-testid="slot"][data-day="2026-10-20"]');
      await expect(beyond).toHaveAttribute('data-state', 'за горизонтом');
      await expect(beyond.getByTestId('slot-sub')).toContainText('дальше горизонта');
      await expect(page.getByTestId('empty-days')).toHaveAttribute('data-count', '1');
      await noSideScroll(page);
    });
  });
}
