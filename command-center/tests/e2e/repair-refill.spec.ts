// CC-0172 (договор 0.75.0): ремонт ролика после судьи кадров и добор тем ниже шорт-листа на
// подставном прошлом батче (src/mocks/batchTopics.ts `setFunnel`, src/mocks/videos.ts
// `setRepair`): сводка у тем батча с раундами по раскрытию, пометка «добор», отказ добора с
// причиной, строка ремонта в проверках темы и под обложкой ролика; старый батч — без плашек;
// компьютер и телефон без прокрутки вбок. CC-0175 (договор 0.76.0): исход раунда — строкой
// фабрики `outcome_ru`; записи раундов нет (`rounds: []`) — сводки добора нет.
import type { Page } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import { FUNNEL_REPAIRS } from '../../src/mocks/batchTopics';
import { expect, noSideScroll, test } from './fixtures';

const openPast = async (page: Page) => {
  await page.goto('/batches');
  const run = page.locator(`[data-testid="run"][data-batch="${PAST}"]`);
  await run.getByRole('button').first().click();
  const block = run.getByTestId('topics');
  await expect(block.getByTestId('topic')).toHaveCount(3);
  return block;
};

for (const device of ['desktop', 'phone'] as const) {
  test.describe(`ремонт и добор @cc-0172: ${device}`, () => {
    test.beforeEach(async ({ page }) => {
      if (device === 'phone') await page.setViewportSize({ width: 390, height: 844 });
    });

    test('темы батча: сводка, «добор», отказ добора, ремонт в проверках', async ({
      page,
      batches,
    }) => {
      batches.setFunnel(PAST);
      const block = await openPast(page);
      await expect(block.getByTestId('topics-repairs')).toHaveText(
        'Ремонт роликов после проверки кадров: удался 1, не удался 1',
      );
      const refill = block.getByTestId('topics-refill');
      await expect(refill).toContainText('Добор ниже шорт-листа: подано 1, поисков 4 · раундов 2');
      await expect(refill.getByTestId('refill-round').first()).toBeHidden();
      await refill.getByTestId('topics-refill-text').click();
      await expect(refill.getByTestId('refill-round')).toHaveCount(2);
      await expect(refill.getByTestId('refill-round').first()).toContainText(
        'первый раунд: темы поданы — Partition',
      );

      const rows = block.getByTestId('topic');
      await expect(rows.nth(0).getByTestId('topic-state')).toHaveText('ролик готов после ремонта');
      await expect(rows.nth(2).getByTestId('topic-refill')).toHaveText('добор');
      await rows.nth(0).getByTestId('topic-open').click();
      await expect(rows.nth(0).getByTestId('topic-repair')).toHaveText(
        'Отремонтирован: блоки 5, 14 (полоса)',
      );
      await rows.nth(1).getByTestId('topic-open').click();
      await expect(rows.nth(1).getByTestId('topic-repair')).toHaveText(
        'Ремонт не удался — отказ (замены для блока 9 в пуле не нашлось)',
      );

      const skipped = block.getByTestId('topics-skipped');
      await skipped.locator('summary').first().click();
      await expect(skipped.getByTestId('skipped-topic')).toHaveCount(5);
      await expect(
        skipped.getByTestId('skipped-topic').filter({ hasText: 'Grid: Ares' }),
      ).toContainText('добор: отказ (права на трейлер не подтверждены)');
      await expect(
        skipped
          .getByTestId('skipped-topic')
          .filter({ hasText: 'One Battle After Another' })
          .getByTestId('topic-refill-note'),
      ).toHaveText('добор: не хватило квоты поиска');
      await noSideScroll(page);
    });

    test('ролики батча: строка ремонта под обложкой и в открытом ролике', async ({
      page,
      videos,
    }) => {
      videos.setRepair(PAST, 'vanguards-doomsday', FUNNEL_REPAIRS['vanguards-doomsday']!);
      videos.setRepair(PAST, 'delver', FUNNEL_REPAIRS.delver!);
      await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=vanguards-doomsday`);
      const reel = (slug: string) => page.locator(`[data-testid="reel"][data-slug="${slug}"]`);
      await expect(reel('vanguards-doomsday').getByTestId('reel-repair')).toHaveText(
        'Отремонтирован: блоки 5, 14 (полоса)',
      );
      await expect(reel('delver').getByTestId('reel-repair')).toHaveText(
        'Ремонт не удался — отказ (замены для блока 9 в пуле не нашлось)',
      );
      await expect(reel('rink-rivals').getByTestId('reel-repair')).toHaveCount(0);
      await expect(page.getByTestId('video-repair')).toHaveText(
        'Отремонтирован: блоки 5, 14 (полоса)',
      );
      await noSideScroll(page);
    });

    test('исход раунда строкой фабрики; записи раундов нет — без сводки добора @cc-0175', async ({
      page,
      batches,
    }) => {
      batches.setFunnel(PAST);
      let block = await openPast(page);
      const refill = block.getByTestId('topics-refill');
      await refill.getByTestId('topics-refill-text').click();
      await expect(refill.getByTestId('refill-round').nth(1)).toContainText(
        'после судьи кадров: квота поиска на сегодня кончилась',
      );
      await expect(refill.getByTestId('refill-round').first()).toContainText(
        'первый раунд: темы поданы',
      );

      batches.setRefillNoRounds(PAST);
      block = await openPast(page);
      await expect(block.getByTestId('topics-repairs')).toBeVisible();
      await expect(block.getByTestId('topics-refill')).toHaveCount(0);
      await expect(block.getByTestId('topics-funnel')).not.toContainText('Добор ниже шорт-листа');
      await expect(block.getByTestId('topic').nth(2).getByTestId('topic-refill')).toHaveText(
        'добор',
      );
      await noSideScroll(page);
    });

    test('старый батч без ремонта и добора — без плашек', async ({ page }) => {
      const block = await openPast(page);
      await expect(block.getByTestId('topics-funnel')).toHaveCount(0);
      await expect(block.getByTestId('topic-refill')).toHaveCount(0);
      await block.getByTestId('topic').first().getByTestId('topic-open').click();
      await expect(block.getByTestId('topic-checks')).toBeVisible();
      await expect(block.getByTestId('topic-repair')).toHaveCount(0);
      await page.goto(`/videos?batch=${encodeURIComponent(PAST)}`);
      await expect(page.getByTestId('reel').first()).toBeVisible();
      await expect(page.getByTestId('reel-repair')).toHaveCount(0);
    });
  });
}
