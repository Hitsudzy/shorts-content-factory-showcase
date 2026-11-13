// CC-0132: «Вырезать фон» и «Обрезать пустые поля» на столе мемов, подставной API
// (src/mocks/memeJobs.ts): план словами → «да» с отсчётом → фоновая задача опросом («i из N»),
// итог, стол перечитан; пока задача идёт — отметки и «Применить разбор» закрыты с причиной;
// перезагруженная страница находит идущую задачу; только смотреть — запуск погашен; телефон
// без прокрутки вбок.
import type { Page } from '@playwright/test';

import { fixtures, writesModes } from '../../src/mocks/fixtures';
import { expect, noSideScroll, openTip, test } from './fixtures';

const writes = (hits: string[]) => hits.filter((h) => !h.startsWith('GET '));
const desk = (page: Page) => page.getByTestId('meme-desk');

async function openTools(page: Page) {
  await page.goto('/memes?channel=example-tech');
  await expect(page.getByTestId('meme')).toHaveCount(35);
  await page.getByTestId('meme-tools-toggle').click();
}

test('вырезка фона: план → «да» → ход задачи → итог, запись закрыта, пока идёт', async ({
  page,
  apiHits,
  memes,
}) => {
  memes.jobs.state.pollS = 0.3;
  // Задача стоит на «1 из 3», пока тест не проверит закрытую запись, — иначе она успевает
  // кончиться до подсказки.
  memes.jobs.state.holdAt = 1;
  await openTools(page);
  await expect(page.getByTestId('meme-cutout-panel')).toContainText('вырезка есть у 2, нет у 1');
  await page.getByTestId('meme-cutout-force').check();
  await page.getByTestId('meme-cutout-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('cutout-plan-made')).toContainText('Вырежет фон: 3 мема');
  await expect(dialog.getByTestId('plan-notes')).toContainText('только после прогона');
  await expect(dialog.getByTestId('meme-cutout-confirm')).toContainText(/Вырезать · \d/);
  expect(writes(apiHits)).toEqual(['POST /api/memes/example-tech/cutout/plan']);
  await dialog.getByTestId('meme-cutout-confirm').click();
  await expect(dialog).toBeHidden();

  const job = page.getByTestId('meme-job');
  await expect(job.getByTestId('job-state')).toHaveText('идёт');
  await expect(job.getByTestId('job-count')).toHaveText('1 из 3');
  await expect(page.getByTestId('desk-save')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByTestId('apply-open')).toHaveAttribute('aria-disabled', 'true');
  // Перед тире — неразрывный пробел (nbDashes): `\s` его берёт.
  await openTip(page, page.getByTestId('apply-open'), /Идёт вырезка фона\s— дождитесь её конца/);
  memes.jobs.state.holdAt = null;

  await expect(job).toHaveAttribute('data-state', 'done', { timeout: 15_000 });
  await expect(job.getByTestId('cutout-done-made')).toContainText('Вырезан фон: 3 мема');
  await expect(job.getByRole('img', { name: 'Вырезка: Roll safe' })).toBeVisible();
  await expect(page.getByTestId('apply-open')).not.toHaveAttribute('aria-disabled');
  expect(writes(apiHits)).toEqual([
    'POST /api/memes/example-tech/cutout/plan',
    'POST /api/memes/example-tech/cutout',
  ]);
  expect(apiHits.filter((h) => /\/jobs\/job-cutout-\d+$/.test(h)).length).toBeGreaterThan(2);
  await job.getByTestId('job-close').click();
  await expect(job).toHaveCount(0);
});

test('обрезка полей: «решать вам» у растянутых сильнее допустимого, итог с признаками для поиска', async ({
  page,
  memes,
}) => {
  memes.jobs.state.pollS = 0.2;
  memes.jobs.state.embedFail = true;
  await openTools(page);
  await page.getByTestId('meme-trim-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('trim-plan-trim')).toContainText('«Two buttons»');
  await expect(dialog.getByTestId('trim-plan-under')).toContainText('решать вам');
  await dialog.getByTestId('meme-trim-confirm').click();
  const job = page.getByTestId('meme-job');
  await expect(job).toHaveAttribute('data-state', 'done', { timeout: 15_000 });
  await expect(job.getByTestId('trim-done-trim')).toContainText('Обрезаны поля: 1 мем');
  await expect(job.getByTestId('trim-done-embedding')).toContainText(
    'Признаки для поиска похожих мемов не пересчитались',
  );
  // Стол перечитан: у обрезанного мема полосы больше нет.
  await expect(page.getByTestId('notice-bands')).toContainText('У 1 мем пустая полоса');
});

test('Vision недоступен и задача упала — словами фабрики', async ({ page, memes }) => {
  memes.jobs.state.vision = { available: false, reason: 'нужна macOS 14 или новее' };
  await openTools(page);
  await page.getByTestId('meme-cutout-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('plan-why')).toHaveText(
    'Вырезка на этой машине недоступна: нужна macOS 14 или новее',
  );
  await expect(dialog.getByTestId('meme-cutout-confirm')).toBeDisabled();
  await page.keyboard.press('Escape');

  memes.jobs.state.vision = { available: true, reason: 'Vision' };
  memes.jobs.state.outcome = 'failed';
  memes.jobs.state.pollS = 0.2;
  await page.getByTestId('meme-cutout-open').click();
  await dialog.getByTestId('meme-cutout-confirm').click();
  const job = page.getByTestId('meme-job');
  await expect(job).toHaveAttribute('data-state', 'failed', { timeout: 15_000 });
  await expect(job.getByTestId('job-error')).toContainText(
    'Задача упала на «Distracted boyfriend»: распознавание вернуло ошибку',
  );
  await expect(job.getByTestId('job-log-tail')).toBeHidden();
});

test('страницу открыли посреди задачи: задача находится и после перезагрузки', async ({
  page,
  memes,
}) => {
  memes.jobs.state.pollS = 30;
  memes.jobs.seed('example-tech', 'cutout', { force: true });
  await page.goto('/memes?channel=example-tech');
  const job = page.getByTestId('meme-job');
  await expect(job.getByTestId('job-state')).toHaveText('идёт');
  await expect(job.getByTestId('job-title')).toHaveText('Вырезка фона');
  await page.reload();
  await expect(job.getByTestId('job-state')).toHaveText('идёт');
  await expect(page.getByTestId('desk-save')).toHaveAttribute('aria-disabled', 'true');
  await page.getByTestId('meme-tools-toggle').click();
  await expect(page.getByTestId('meme-trim-open')).toHaveAttribute('aria-disabled', 'true');
});

test('только смотреть: план и запуск погашены, ничего не пишется', async ({ page, apiHits }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  await openTools(page);
  await expect(page.getByTestId('meme-cutout-open')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByTestId('meme-trim-open')).toHaveAttribute('aria-disabled', 'true');
  expect(writes(apiHits)).toEqual([]);
});

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('план и ход задачи без прокрутки вбок', async ({ page, memes }) => {
    memes.jobs.state.pollS = 30;
    await openTools(page);
    await noSideScroll(page);
    await page.getByTestId('meme-trim-open').click();
    await expect(page.getByRole('alertdialog').getByTestId('trim-plan-under')).toBeVisible();
    await noSideScroll(page);
    await page.getByRole('alertdialog').getByTestId('meme-trim-confirm').click();
    await expect(desk(page).getByTestId('meme-job')).toBeVisible();
    await noSideScroll(page);
  });
});
