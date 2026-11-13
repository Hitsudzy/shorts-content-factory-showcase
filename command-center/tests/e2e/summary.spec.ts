// Сводка прогона (CC-0115 → CC-0099) в раскрытом прошлом прогоне на подставных батчах
// (src/mocks/batches.ts + runSummary.ts): время, воронка, тиры, замечания с подсказками,
// RUN_SUMMARY.md под «подробнее», телефон без прокрутки вбок.
import type { Page } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import { expect, noSideScroll, openTip, test } from './fixtures';

const run = (page: Page, batch: string) =>
  page.locator(`[data-testid="run"][data-batch="${batch}"]`);

test('сводка прогона: время, воронка, тиры, замечания, файл под «подробнее»', async ({ page }) => {
  await page.goto('/batches');
  const r = run(page, PAST);
  await r.getByRole('button').first().click();
  const s = r.getByTestId('run-summary');
  await expect(s.getByTestId('summary-fact')).toHaveCount(5);
  await expect(s.getByTestId('summary-funnel-line')).toContainText('1 из 5 тем потеряна по пути');
  await expect(s.getByTestId('summary-tier')).toHaveCount(5);
  await openTip(page, s.getByText('Проверки после батча: 5 из 28 не зелёные'), /Живые проверки/);
  await expect(s.getByTestId('summary-file')).toBeHidden();
  await s.getByText('Подробнее', { exact: true }).click();
  await expect(s.getByTestId('summary-file')).toContainText('RUN_SUMMARY');
});

test('сводка прогона на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  const r = run(page, PAST);
  await r.getByRole('button').first().click();
  await expect(r.getByTestId('summary-step')).toHaveCount(7);
  await r.getByTestId('run-summary').getByText('Подробнее', { exact: true }).click();
  await noSideScroll(page);
});
