// Темы батча (CC-0092) на подставных батчах (src/mocks/batches.ts + batchTopics.ts): блок
// «Темы» идущего батча, итоги этапов в киноленте и переход к темам, подробности темы, отсеянные,
// расход поиска, битый файл этапа, обновление вместе с опросом экрана, телефон без прокрутки вбок.
import type { Page } from '@playwright/test';

import { RUNNING } from '../../src/mocks/batches';
import { expect, noSideScroll, openTip, test } from './fixtures';

const card = (page: Page, batch: string) =>
  page.locator(`[data-testid="open-batch"][data-batch="${batch}"]`);

test('темы идущего батча: строки, итоги этапов, подробности, отсеянные', async ({ page }) => {
  await page.goto('/batches');
  const c = card(page, RUNNING);
  const block = c.getByTestId('topics');
  await expect(block.getByTestId('topic')).toHaveCount(3);
  await expect(block.getByTestId('topics-quota')).toContainText(
    'батч потратил 9 поисков · квота дня 100, осталось 60',
  );
  const first = block.getByTestId('topic').first();
  await expect(first.getByTestId('topic-state')).toHaveText('в работе: монтаж');
  await openTip(page, first.getByTestId('topic-signal'), /популярность темы/);

  // Итог этапа в кадре киноленты; клик — к темам.
  const summary = c.getByTestId('frame-summary').first();
  await expect(summary).toContainText('нашёл 6 тем, взял 3, отсеял 3');
  await summary.click();
  await expect(block).toBeFocused();

  // Подробности темы по клику.
  await first.getByTestId('topic-open').click();
  const d = first.getByTestId('topic-details');
  await expect(d.getByTestId('topic-scenes')).toContainText('Доктор Дум');
  await expect(d.getByTestId('topic-fact')).toContainText('источник: Variety');
  // CC-0119: отказы кандидатов факта — словами фабрики, код — только в подсказке.
  const failed = d.getByTestId('fact-failed');
  await expect(failed.getByTestId('fact-failed-candidate')).toHaveCount(2);
  await expect(failed).toContainText('предложение обрезано');
  await expect(failed).toContainText('Отклонённые кандидаты — не прошли проверку факта:');
  await expect(failed).toContainText('похоже на мнение и ещё одна причина без описания');
  await expect(failed).not.toContainText('cut_short');
  await openTip(
    page,
    failed.locator('[data-testid="fact-failure"][data-code="cut_short"]'),
    /код проверки факта: cut_short/,
  );
  await expect(d.getByTestId('topic-checks')).toContainText('Сценарий: прошёл проверку');
  await expect(d.getByTestId('topic-footage')).toContainText('— хватает');

  // Отсеянные — свёрнуты.
  const skipped = block.getByTestId('topics-skipped');
  await expect(skipped.getByTestId('skipped-topic').first()).toBeHidden();
  await skipped.locator('summary').first().click();
  await expect(skipped.getByTestId('skipped-topic')).toHaveCount(3);
  await expect(skipped.getByTestId('skipped-topic').first()).toContainText('отсеяна: нет факта');
});

test('этапы по ходу батча: темы обновляются с опросом экрана, без своего опроса', async ({
  page,
  batches,
}) => {
  batches.setTopics(RUNNING, '01');
  await page.clock.install();
  await page.goto('/batches');
  const c = card(page, RUNNING);
  await expect(c.getByTestId('topic').first().getByTestId('topic-state')).toHaveText(
    'в работе: проверка темы',
  );
  await expect(c.getByTestId('frame-summary')).toHaveCount(1);
  const before = batches.topicCalls.filter((x) => x === RUNNING).length;
  batches.setTopics(RUNNING, '02');
  // Опрос списка идущих батчей — раз в 15 с; темы приходят вместе с ним.
  await page.clock.runFor(16_000);
  await expect(c.getByTestId('topic').first().getByTestId('topic-state')).toHaveText(
    'в работе: футаж',
  );
  await expect(c.getByTestId('frame-summary').first()).toContainText('проверку прошли 2 из 3');
  const after = batches.topicCalls.filter((x) => x === RUNNING).length;
  expect(after - before).toBe(1);
});

test.describe('битый файл этапа', () => {
  // Отказ 409 браузер сам пишет в консоль — это ожидаемо.
  test.use({ expectCleanConsole: false });

  test('понятная строка, код под «подробнее»', async ({ page, batches }) => {
    batches.setTopics(RUNNING, 'broken');
    await page.goto('/batches');
    const alert = card(page, RUNNING).getByTestId('topics').getByRole('alert');
    await expect(alert).toHaveAttribute('data-code', 'stage_broken');
    await expect(alert.getByTestId('refusal-message')).toHaveText(
      'Данные этапа «Проверка тем» не читаются — темы батча показать нельзя.',
    );
    await expect(alert.getByText('stage_broken', { exact: false })).toBeHidden();
  });
});

test('телефон: темы и подробности без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  const c = card(page, RUNNING);
  const first = c.getByTestId('topic').first();
  await first.getByTestId('topic-open').click();
  await expect(first.getByTestId('topic-details')).toBeVisible();
  await expect(first.getByTestId('fact-failed')).toBeVisible();
  // Причины отказа кандидатов факта переносятся, не обрезаются.
  const clipped = await first
    .getByTestId('fact-failed-candidate')
    .evaluateAll((els) => els.filter((e) => e.scrollWidth > e.clientWidth + 1).length);
  expect(clipped).toBe(0);
  await expect(c.getByTestId('frame-summary').first()).toBeVisible();
  await noSideScroll(page);
});
