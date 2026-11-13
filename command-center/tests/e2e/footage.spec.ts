// «Футаж по темам» (CC-0119, фабрика CF-0715 `footage_progress`) на подставном API
// (src/mocks/batches.ts): темы названиями, состояние словами, собрано из нужного, кадры против
// порога, последнее видео, причина; сводка; «восстановлено по журналу» в подсказке; опрос, пока
// батч идёт; скелетон; телефон.
import type { Page } from '@playwright/test';

import { footageTopics, RUNNING, STOPPED } from '../../src/mocks/batches';
import { expect, noSideScroll, openTip, test } from './fixtures';

const card = (page: Page, batch: string) =>
  page.locator(`[data-testid="open-batch"][data-batch="${batch}"]`);
const topic = (page: Page, id: string) =>
  card(page, RUNNING).locator(`[data-testid="footage-topic"][data-topic="${id}"]`);

test('идущий батч: темы, состояния, кадры против порога, причины, сводка', async ({ page }) => {
  await page.goto('/batches');
  const block = card(page, RUNNING).getByTestId('footage');
  await expect(block.getByTestId('footage-counts')).toHaveText(
    'собрано 1 · собирается 1 · в очереди 1 · не хватило 1 · отказано 1',
  );
  await expect(topic(page, 'vanguards-doomsday')).toContainText('Vanguards: Doomsday');
  await expect(topic(page, 'vanguards-doomsday').getByTestId('footage-state')).toHaveText('собрано');
  await expect(topic(page, 'vanguards-doomsday')).toContainText('31 пригодный кадр (порог 12)');
  await expect(topic(page, 'delver')).toContainText('источников 2 из 4');
  await expect(topic(page, 'delver')).toContainText('последнее видео: Delver — First Look');
  await expect(topic(page, 'partition-s3').getByTestId('footage-reason')).toContainText(
    'пригодных кадров меньше порога: 7 из 12',
  );
  await expect(topic(page, 'the-running-man').getByTestId('footage-reason')).toContainText(
    'лицензия не подходит каналу',
  );
  await expect(topic(page, 'one-battle-after-another')).toContainText('One battle after another');
  // Код причины — только под свёрнутым «Подробнее»: textContent его видит, innerText — нет.
  await expect(block).not.toContainText('pool_too_thin', { useInnerText: true });
  await expect(block.locator('[data-slot="more"]')).toContainText('pool_too_thin');
  await expect(card(page, STOPPED).getByTestId('footage')).toHaveCount(0);
});

test('по журналу: «восстановлено по журналу» с подсказкой', async ({ page, batches }) => {
  batches.setFootage(RUNNING, { source: 'events' });
  await page.goto('/batches');
  const src = card(page, RUNNING).getByTestId('footage-source');
  await expect(src).toHaveText('восстановлено по журналу');
  await openTip(page, src, 'Восстановлено по журналу');
});

test('пока батч идёт — опрос по poll_s: новое состояние темы видно без перезагрузки', async ({
  page,
  batches,
}) => {
  await page.goto('/batches');
  await expect(topic(page, 'delver').getByTestId('footage-state')).toHaveText('собирается');
  batches.setFootage(RUNNING, {
    topics: footageTopics().map((t) =>
      t.topic_id === 'delver'
        ? { ...t, state: 'collected', state_ru: 'собрано', collected: 4, usable_shots: 18 }
        : t,
    ),
  });
  await expect(topic(page, 'delver').getByTestId('footage-state')).toHaveText('собрано');
  await expect(card(page, RUNNING).getByTestId('footage-counts')).toContainText('собрано 2');
});

test('скелетон, пока ответ не пришёл', async ({ page }) => {
  let release: () => void = () => {};
  const held = new Promise<void>((r) => (release = r));
  await page.route('**/api/batches/*/*/footage', async (route) => {
    await held;
    await route.fallback();
  });
  await page.goto('/batches');
  const block = card(page, RUNNING).getByTestId('footage');
  await expect(block.getByRole('status')).toContainText('Читаю сбор футажа');
  release();
  await expect(block.getByTestId('footage-topic')).toHaveCount(5);
});

test('телефон: блок футажа без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  await expect(card(page, RUNNING).getByTestId('footage-topic')).toHaveCount(5);
  await noSideScroll(page);
});
