// CC-0111 и CC-0113 на подставном API (src/mocks): стадия изменила код фабрики — предупреждение
// на странице батча и пометка в списке и на главной; «Проверка кадров — нечего проверять» одним
// кадром киноленты; причины словами фабрики, а без её строки — код. Телефон — без прокрутки вбок.
import type { Page } from '@playwright/test';

import {
  EMPTY_JUDGE_STAGES,
  FOOTAGE_CODE_EDIT,
  RUNNING,
  SCRIPTS_CODE_EDIT,
} from '../../src/mocks/batches';
import { expect, noSideScroll, openTip, test } from './fixtures';

const card = (page: Page, batch = RUNNING) =>
  page.locator(`[data-testid="open-batch"][data-batch="${batch}"]`);

test('стадия изменила код: предупреждение на странице батча, пометка в списке и на главной', async ({
  page,
  batches,
}) => {
  batches.setCodeEdits(RUNNING, [FOOTAGE_CODE_EDIT, SCRIPTS_CODE_EDIT]);
  await page.goto('/batches');
  const c = card(page);
  const warn = c.getByTestId('code-edits');
  await expect(warn).toBeVisible();
  await expect(warn.getByTestId('code-edit').first()).toContainText(
    'Стадия «Разметка футажа» (кадр «Футаж») изменила код фабрики:',
  );
  await expect(warn.getByTestId('code-edit-file').first()).toHaveText(
    'agents/footage-indexer/scripts/source_rights.py',
  );
  await expect(warn.getByTestId('code-edits-consequence')).toContainText(
    'Следующий батч не запустится',
  );
  // Технические подробности — свёрнуты.
  await expect(warn.getByText('строка фабрики:', { exact: false }).first()).toBeHidden();
  await warn.getByText('Подробнее', { exact: true }).click();
  await expect(warn.getByText('строка фабрики:', { exact: false }).first()).toBeVisible();
  const mark = c.getByTestId('code-edits-mark');
  await expect(mark).toHaveText('правки кода: 2');
  await openTip(page, mark.locator('[data-slot="status"]'), /следующий батч не запустится/);

  await page.goto('/');
  const home = page.getByTestId('batch-card');
  await expect(home.getByTestId('code-edits-mark')).toHaveText('правки кода: 2');
  await expect(home.getByTestId('home-code-edits')).toContainText('следующий батч не запустится');
});

test('правка кода на телефоне — файлы переносятся, без прокрутки вбок', async ({
  page,
  batches,
}) => {
  batches.setCodeEdits(RUNNING, [FOOTAGE_CODE_EDIT, SCRIPTS_CODE_EDIT]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  await expect(card(page).getByTestId('code-edits')).toBeVisible();
  await noSideScroll(page);
});

test('проверке кадров нечего проверять — один готовый кадр, не пропуск', async ({
  page,
  batches,
}) => {
  batches.patch(RUNNING, { stages: EMPTY_JUDGE_STAGES, stage: 'batch-done', next: 'monitors' });
  await page.goto('/batches');
  const li = card(page).getByTestId('film-strip').locator('li');
  await expect(li).toHaveCount(8);
  const judge = li.filter({ hasText: 'Проверка кадров' });
  await expect(judge).toHaveCount(1);
  await expect(judge).toHaveAttribute('data-state', 'done');
  await expect(judge.getByTestId('frame-small')).toContainText('нечего проверять');
  // Номера подряд.
  await expect(li.locator('.film-num')).toHaveText([
    '01',
    '02',
    '03',
    '04',
    '05',
    '06',
    '07',
    '08',
  ]);
});

test('причины нехватки футажа — словами фабрики, без её строки — код', async ({ page }) => {
  await page.goto('/stats');
  const reasons = page.getByTestId('stats-footage').getByTestId('footage-reasons');
  await expect(reasons).toContainText('монтажу не хватило кадра для главного героя');
  await expect(reasons).toContainText('пул тоньше сценария');
  // У `event_footage_short` строки фабрики нет — центр своей не придумывает: «причина без
  // описания», код — в подсказке и под «Подробнее».
  await expect(reasons).toContainText('причина без описания: 1');
  await expect(reasons).not.toContainText('event_footage_short');
  await openTip(page, reasons.getByText('причина без описания: 1'), 'event_footage_short');
  const saturn = page.locator('[data-testid="footage-row"][data-name="Orbit Awards 2026"]');
  await expect(saturn.getByRole('list', { name: 'Почему' })).toHaveText('причина без описания');
  // «Где добыть»: канал один раз, его ролик — после двоеточия.
  await expect(
    page
      .locator('[data-testid="footage-row"][data-name="Rink Rivals"]')
      .getByTestId('footage-where'),
  ).toHaveText('Где добыть: канал «Examplevue»: «Rink Rivals | Official Trailer | Examplevue»');
});
