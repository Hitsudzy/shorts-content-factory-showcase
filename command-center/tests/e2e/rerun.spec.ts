// «Повторить с…» (CC-0123, фабрика CF-0739) на подставном API (src/mocks/batchActions.ts):
// стадии с недоступными и причиной, план «сбросится / останется», «сразу продолжить» и заметка,
// итог — сброшен, продолжен, или сброшен без продолжения (`resume_failed`); упавшие батчи;
// «оборвалась» в прошлых прогонах; телефон.
import type { Locator, Page } from '@playwright/test';

import { PAST, RUNNING, STOPPED, STRANDED_FAILED, STRANDED_STOPPED } from '../../src/mocks/batches';
import { expect, noSideScroll, test } from './fixtures';

const card = (page: Page, batch: string) =>
  page.locator(`[data-testid="open-batch"][data-batch="${batch}"]`);
const stranded = (page: Page, batch: string) =>
  page.locator(`[data-testid="stranded-batch"][data-batch="${batch}"]`);
const stage = (dialog: Locator, id: string) =>
  dialog.locator(`[data-testid="rerun-stage"][data-stage="${id}"]`);

async function openRerun(page: Page, where: Locator) {
  await where.getByTestId('rerun-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('rerun-stage').first()).toBeVisible();
  return dialog;
}

test('идущий батч — без «Повторить с…»; остановленный — стадии с причинами недоступных', async ({
  page,
}) => {
  await page.goto('/batches');
  await expect(card(page, RUNNING).getByTestId('batch-status')).toHaveText('идёт');
  await expect(card(page, RUNNING).getByTestId('rerun-open')).toHaveCount(0);
  const dialog = await openRerun(page, card(page, STOPPED));
  await expect(stage(dialog, 'batch-start').getByRole('radio')).toBeDisabled();
  await expect(stage(dialog, 'batch-start').getByTestId('rerun-stage-why')).toContainText(
    'стадия «Старт батча» или раньше',
  );
  await expect(stage(dialog, 'frame-judge')).toContainText('ещё не шла');
  await expect(stage(dialog, 'frame-judge').getByRole('radio')).toBeDisabled();
  await expect(stage(dialog, 'video-editor').getByRole('radio')).toBeEnabled();
  await expect(dialog.getByTestId('rerun-confirm')).toBeDisabled();
});

test('план и «да» без продолжения: сброшен до стадии, заметка ушла, бэкап под «подробнее»', async ({
  page,
  batches,
}) => {
  await page.goto('/batches');
  const dialog = await openRerun(page, card(page, STOPPED));
  await stage(dialog, 'content-researcher').getByRole('radio').check();
  const plan = dialog.getByTestId('rerun-plan');
  await expect(plan.getByTestId('rerun-reset-stage')).toHaveText([
    /Исследование и сценарии/,
    /Проверка сценариев/,
    /Монтаж/,
  ]);
  await expect(plan.getByTestId('rerun-kept')).toContainText('Поиск трендов');
  await expect(plan.getByTestId('rerun-message')).toContainText('Можно повторить батч');
  await plan.getByTestId('rerun-resume').uncheck();
  await plan.getByTestId('rerun-note').fill('сценарии заново');
  await expect(dialog.getByTestId('rerun-confirm')).toHaveText(/^Повторить · \d:\d\d$/);
  await dialog.getByTestId('rerun-confirm').click();
  await expect(dialog).toBeHidden();
  const done = card(page, STOPPED).getByTestId('rerun-done');
  await expect(done).toContainText('Батч сброшен до стадии «Исследование и сценарии»');
  // Путь бэкапа — только под свёрнутым «Подробнее»: textContent его видит, innerText — нет.
  await expect(done).not.toContainText('run-state.before-rerun', { useInnerText: true });
  await done.locator('summary', { hasText: 'Подробнее' }).click();
  await expect(done.locator('[data-slot="more"]')).toContainText('run-state.before-rerun', {
    useInnerText: true,
  });
  expect(batches.actions.writes.at(-1)).toMatchObject({
    path: `${STOPPED}/rerun-from`,
    body: { resume: false, note: 'сценарии заново' },
  });
});

test('«сразу продолжить»: продолжен; не вышло — «сброшен, но не продолжен» с причиной', async ({
  page,
  batches,
}) => {
  batches.actions.setRerunResume('failed');
  await page.goto('/batches');
  let dialog = await openRerun(page, card(page, STOPPED));
  await stage(dialog, 'video-editor').getByRole('radio').check();
  await expect(dialog.getByTestId('rerun-resume')).toBeChecked();
  await dialog.getByTestId('rerun-confirm').click();
  const failed = card(page, STOPPED).getByTestId('rerun-resume-failed');
  await expect(failed).toContainText('Батч сброшен до стадии «Монтаж», но не продолжен');
  await expect(failed).toContainText('замок батча держит другой процесс');

  batches.actions.setRerunResume('ok');
  await failed.getByTestId('outcome-close').click();
  dialog = await openRerun(page, card(page, STOPPED));
  await stage(dialog, 'content-researcher').getByRole('radio').check();
  await expect(dialog.getByTestId('rerun-plan')).toBeVisible();
  await dialog.getByTestId('rerun-confirm').click();
  await expect(card(page, STOPPED).getByTestId('rerun-done')).toContainText(
    'Батч повторяется со стадии «Исследование и сценарии»',
  );
  await expect(card(page, STOPPED).getByTestId('batch-status')).toHaveText('идёт');
});

test('упавшие батчи: «Повторить с…» и когда продолжить нельзя; упал на старте — ни с одной', async ({
  page,
  batches,
}) => {
  batches.strand();
  await page.goto('/batches');
  let dialog = await openRerun(page, stranded(page, STRANDED_FAILED));
  await expect(dialog.getByTestId('rerun-can-count')).toHaveText('ни с одной нельзя');
  await expect(stage(dialog, 'monitors').getByTestId('rerun-stage-why')).toContainText(
    'раньше упала стадия «Старт батча»',
  );
  await page.keyboard.press('Escape');
  await expect(dialog).toBeHidden();
  const stopped = stranded(page, STRANDED_STOPPED);
  await expect(stopped.getByTestId('stranded-refusal')).toBeVisible();
  dialog = await openRerun(page, stopped);
  await stage(dialog, 'trend-hunter').getByRole('radio').check();
  await expect(dialog.getByTestId('rerun-plan')).toBeVisible();
  await dialog.getByTestId('rerun-confirm').click();
  await expect(dialog).toBeHidden();
  // Продолжен — из «упавших» в «идёт сейчас».
  await expect(card(page, STRANDED_STOPPED).getByTestId('batch-status')).toHaveText('идёт');
});

test('прошлый прогон: стадия без конца — «оборвалась»', async ({ page, batches }) => {
  batches.cutStage(PAST, 4);
  await page.goto('/batches');
  const run = page.getByTestId('batch-history').locator(`[data-batch="${PAST}"]`);
  await run.getByRole('button', { expanded: false }).click();
  await expect(run.getByTestId('run-open')).toHaveText(
    'Батч не закрыт — оборвались: Поиск трендов',
  );
  await expect(run.getByTestId('run-stage-cut')).toHaveText('оборвалась');
  await expect(run.getByTestId('run-stages')).not.toContainText('идёт');
});

test.describe('телефон', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('окно «Повторить с…» без прокрутки вбок', async ({ page }) => {
    await page.goto('/batches');
    const dialog = await openRerun(page, card(page, STOPPED));
    await stage(dialog, 'content-researcher').getByRole('radio').check();
    await expect(dialog.getByTestId('rerun-plan')).toBeVisible();
    await noSideScroll(page);
  });
});
