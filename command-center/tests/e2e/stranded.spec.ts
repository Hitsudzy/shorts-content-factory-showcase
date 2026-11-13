// «Упавшие батчи» на экране «Батчи» (CC-0089) на подставном API (src/mocks/batches.ts →
// `strand()`): батч, упавший на batch-start и держащий день, и вчерашний остановленный;
// журнал стадии под «подробнее», «Продолжить…» и отказ фабрики, ссылка из отказа «сегодня».
import type { Page } from '@playwright/test';

import {
  RUNNING,
  STRANDED_FAILED,
  STRANDED_REFUSAL,
  STRANDED_STOPPED,
} from '../../src/mocks/batches';
import { expect, openTip, test } from './fixtures';

const card = (page: Page, batch: string) =>
  page.locator(`[data-testid="stranded-batch"][data-batch="${batch}"]`);

const noHorizontalScroll = async (page: Page) => {
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(doc.scroll, 'горизонтальная прокрутка страницы').toBeLessThanOrEqual(doc.width);
};

test('нет упавших — блока нет', async ({ page }) => {
  await page.goto('/batches');
  await expect(page.getByTestId('batch-history')).toBeVisible();
  await expect(page.getByTestId('open-batch').first()).toBeVisible();
  await expect(page.getByTestId('stranded')).toHaveCount(0);
});

test('упал на batch-start: словами, держит день, журнал под «подробнее», продолжить', async ({
  page,
  batches,
}) => {
  batches.strand();
  await page.goto('/batches');
  const block = page.getByTestId('stranded');
  await expect(block.getByRole('heading', { name: 'Упавшие батчи' })).toBeVisible();
  const failed = card(page, STRANDED_FAILED);
  await expect(failed.getByTestId('stranded-headline')).toHaveText(
    /^Упал на стадии «Старт батча» — команда стадии завершилась с ошибкой/,
  );
  await expect(failed.getByTestId('stranded-headline')).not.toContainText('step 0');
  await openTip(
    page,
    failed.getByTestId('stranded-holds').locator('[tabindex="0"]'),
    '1 батч в сутки',
  );

  await failed.locator('summary', { hasText: 'Подробнее' }).first().click();
  await expect(failed.getByTestId('log-tail')).toContainText('working tree is not clean');
  await expect(failed.getByText(/^причина: step 0/)).toBeVisible();

  const stopped = card(page, STRANDED_STOPPED);
  // Слова фабрики, но дата — словами и тире вместо « - » (сырое — в `STRANDED_REFUSAL`).
  await expect(stopped.getByTestId('stranded-refusal')).toContainText(
    'Продолжить нельзя: батч вчерашний (9 октября): день батча прошёл',
  );
  await expect(stopped.getByTestId('stranded-refusal')).toContainText('поиска — уже не его');
  expect(STRANDED_REFUSAL).toContain('2026-10-09');
  await expect(stopped.getByTestId('resume-open')).toHaveCount(0);
  await expect(stopped.getByTestId('stranded-holds')).toHaveText('запуск не держит');

  await failed.getByTestId('resume-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('resume-reason')).toContainText('можно продолжить');
  await dialog.getByTestId('resume-confirm').click();
  await expect(dialog).toBeHidden();
  await expect(
    page.locator(`[data-testid="open-batch"][data-batch="${STRANDED_FAILED}"]`),
  ).toBeVisible();
  await expect(failed).toHaveCount(0);
  await expect(page.getByTestId('stranded-batch')).toHaveCount(1);
});

test('окно запуска: отказ «сегодня» ведёт к упавшему батчу, «открытые» — к идущему', async ({
  page,
  batches,
}) => {
  batches.strand();
  await page.goto('/batches');
  await expect(card(page, STRANDED_FAILED)).toBeVisible();
  await page.getByTestId('launch-channel').selectOption('example-science');
  await page.getByTestId('launch-open').click();
  const dialog = page.getByRole('alertdialog');
  const today = dialog.locator('[data-testid="launch-guard"][data-ok="false"]');
  await expect(today).toHaveCount(1);
  await expect(today).toContainText('Батч сегодня');
  await expect(dialog.getByTestId('launch-why')).toHaveText(
    'Сегодня батч канала уже был (10.10, 07:04) — в сутки разрешён один',
  );
  await expect(today.getByTestId('launch-guard-text')).not.toContainText('2026-10-10T0405Z');
  await expect(dialog.getByTestId('launch-skipped')).not.toContainText('batch_feed_days');
  const link = today.getByTestId('launch-guard-batch');
  await expect(link).toHaveAttribute('data-batch', STRANDED_FAILED);
  await link.click();
  await expect(dialog).toBeHidden();
  await expect(card(page, STRANDED_FAILED)).toBeFocused();
  await expect(card(page, STRANDED_FAILED)).toBeInViewport();

  await page.getByTestId('launch-channel').selectOption('example-film');
  await page.getByTestId('launch-open').click();
  const open = dialog.getByTestId('launch-guard-batch');
  await expect(open).toHaveAttribute('data-batch', RUNNING);
  await open.click();
  await expect(dialog).toBeHidden();
  await expect(page.locator(`[data-testid="open-batch"][data-batch="${RUNNING}"]`)).toBeFocused();
});

test('телефон: блок без горизонтальной прокрутки', async ({ page, batches }) => {
  batches.strand();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  const failed = card(page, STRANDED_FAILED);
  await failed.locator('summary', { hasText: 'Подробнее' }).first().click();
  await expect(failed.getByTestId('log-tail')).toBeVisible();
  await noHorizontalScroll(page);
});
