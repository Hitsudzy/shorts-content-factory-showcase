// CC-0133: «Добавить мем» на столе мемов, подставной API (src/mocks/memeJobs.ts): картинка по
// ссылке (только http(s) — подсказка до плана), план словами → «да» → задача по шагам → новая
// запись «ждёт разбора» в сетке; отказ фабрики словами; лист кадров картинкой со сменами сцен,
// два щелчка по кадрам → «GIF из видео» с отрезком → гифка; пересчёт признаков; перезагруженная
// страница находит идущую задачу; телефон без прокрутки вбок.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, test } from './fixtures';

const writes = (hits: string[]) => hits.filter((h) => !h.startsWith('GET '));
const desk = (page: Page) => page.getByTestId('meme-desk');
const VIDEO = 'https://www.youtube.com/watch?v=dQw4w9WgXcQ';

async function openAdd(page: Page) {
  await page.goto('/memes?channel=example-tech');
  await expect(page.getByTestId('meme')).toHaveCount(35);
  await page.getByTestId('meme-add-toggle').click();
}

async function fillImage(page: Page, id = 'success-kid') {
  await page.getByTestId('add-image-url').fill('https://i.imgflip.com/success-kid.jpg');
  await page.getByTestId('add-image-source').fill('https://imgflip.com/memetemplate/success-kid');
  await page.getByTestId('add-image-id').fill(id);
  await page.getByTestId('add-image-tags').fill('успех, победа');
  await page.getByTestId('add-image-description').fill('Малыш сжимает кулак с песком');
}

test('картинка: file:// — подсказка до плана; план → «да» → шаги → новая запись в сетке', async ({
  page,
  apiHits,
  memes,
}) => {
  memes.jobs.state.pollS = 0.3;
  await openAdd(page);
  await fillImage(page);
  await page.getByTestId('add-image-url').fill('file:///home/me/kid.jpg');
  await expect(page.getByTestId('field-hint')).toContainText('Только ссылка http(s)://');
  await expect(page.getByTestId('meme-add-image-open')).toHaveAttribute('aria-disabled', 'true');
  expect(writes(apiHits)).toEqual([]);

  await page.getByTestId('add-image-url').fill('https://i.imgflip.com/success-kid.jpg');
  await page.getByTestId('meme-add-image-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('add-plan-fetch')).toContainText(
    'https://i.imgflip.com/success-kid.jpg',
  );
  await expect(dialog.getByTestId('add-plan-time')).toContainText('до 4 мин');
  await dialog.getByTestId('meme-add-image-confirm').click();
  await expect(dialog).toBeHidden();

  const job = page.getByTestId('meme-job');
  await expect(job.getByTestId('job-title')).toHaveText('Добавление картинки');
  await expect(job).toHaveAttribute('data-state', 'done', { timeout: 15_000 });
  await expect(job.getByTestId('add-done-entry')).toContainText('ждёт разбора');
  await expect(job.getByRole('img', { name: 'Новый мем: Success kid' })).toBeVisible();
  await expect(page.getByTestId('meme')).toHaveCount(36);
  await job.getByTestId('add-done-open').click();
  await expect(page).toHaveURL(/m=success-kid/);
  expect(writes(apiHits)).toEqual([
    'POST /api/memes/example-tech/add-image/plan',
    'POST /api/memes/example-tech/add-image',
  ]);
});

test.describe('отказы', () => {
  // Отказ фабрики — ответ 409, браузер пишет его в консоль.
  test.use({ expectCleanConsole: false });

  test('отказы словами фабрики: duplicate_id и too_many_frames, коды — под «подробнее»', async ({
    page,
  }) => {
    await openAdd(page);
    await fillImage(page, 'roll-safe');
    await page.getByTestId('meme-add-image-open').click();
    const dialog = page.getByRole('alertdialog');
    const refusal = dialog.getByTestId('write-refusal');
    await expect(refusal).toHaveAttribute('data-code', 'duplicate_id');
    await expect(refusal.getByTestId('write-refusal-message')).toHaveText(
      'мем «Roll safe» уже есть в банке',
    );
    // Код — только под свёрнутым «подробнее».
    await expect(refusal.getByText('код: duplicate_id')).toBeHidden();
    await page.keyboard.press('Escape');

    // Шаг в 0,1 с на 40 с — 400 кадров: центр подсказывает до плана.
    await page.getByTestId('add-tab-sheet').click();
    await page.getByTestId('sheet-video').fill(VIDEO);
    await page.getByTestId('sheet-end').fill('40');
    await page.getByTestId('sheet-every').fill('0,1');
    await expect(page.getByTestId('sheet-frames')).toContainText('В листе будет 400 кадров');
    await expect(page.getByTestId('meme-sheet-open')).toHaveAttribute('aria-disabled', 'true');
  });
});

test('лист кадров → два кадра → GIF из отрезка → новая гифка', async ({ page, memes, apiHits }) => {
  memes.jobs.state.pollS = 0.2;
  await openAdd(page);
  await page.getByTestId('add-tab-sheet').click();
  await page.getByTestId('sheet-video').fill(VIDEO);
  await page.getByTestId('sheet-end').fill('40');
  await page.getByTestId('meme-sheet-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('add-plan-span')).toContainText('20 кадров');
  await dialog.getByTestId('meme-sheet-confirm').click();
  const job = page.getByTestId('meme-job');
  await expect(job).toHaveAttribute('data-state', 'done', { timeout: 15_000 });
  const img = job.getByTestId('sheet-image');
  await expect(img).toBeVisible();
  expect(await img.evaluate((el) => (el as HTMLImageElement).naturalWidth)).toBe(1600);
  await expect(job.getByTestId('sheet-cut')).toHaveCount(2);
  await job.getByRole('button', { name: 'Кадр 22 с', exact: true }).click();
  await job.getByRole('button', { name: 'Кадр 26 с', exact: true }).click();
  await expect(job.getByTestId('sheet-pick-end')).toHaveValue('28');
  await job.getByTestId('sheet-to-gif').click();
  const gif = page.getByTestId('meme-add-gif');
  await expect(gif).toBeVisible();
  await expect(gif.getByTestId('add-gif-start')).toHaveValue('22');
  await gif.getByTestId('add-gif-id').fill('dog-turns-around');
  await gif.getByTestId('add-gif-description').fill('Собака резко оборачивается');
  await job.getByTestId('job-close').click();
  await gif.getByTestId('meme-add-gif-open').click();
  await expect(dialog.getByTestId('add-plan-fetch')).toContainText('видео уже скачано');
  await expect(dialog.getByTestId('add-plan-span')).toContainText('22–28 с (6 с)');
  await dialog.getByTestId('meme-add-gif-confirm').click();
  await expect(job).toHaveAttribute('data-state', 'done', { timeout: 15_000 });
  await expect(job.getByTestId('add-done-cuts')).toContainText('смена сцены на 27 с');
  await expect(page.getByTestId('meme')).toHaveCount(36);
  expect(writes(apiHits)).toEqual([
    'POST /api/memes/example-tech/sheet/plan',
    'POST /api/memes/example-tech/sheet',
    'POST /api/memes/example-tech/add-gif/plan',
    'POST /api/memes/example-tech/add-gif',
  ]);
});

test('перезагрузка посреди добавления: задача находится, запись закрыта', async ({
  page,
  memes,
}) => {
  memes.jobs.state.holdAt = 0;
  memes.jobs.seed('example-tech', 'add_image', {
    meme_id: 'success-kid',
    url: 'https://i.imgflip.com/success-kid.jpg',
    source_url: 'https://imgflip.com/memetemplate/success-kid',
    description: 'Малыш',
    tags: [],
  });
  await page.goto('/memes?channel=example-tech');
  const job = page.getByTestId('meme-job');
  await expect(job.getByTestId('job-count')).toHaveText('шаг 1 из 4');
  await page.reload();
  await expect(job.getByTestId('job-state')).toHaveText('идёт');
  await expect(job.getByTestId('job-step-text')).toHaveText(
    'https://i.imgflip.com/success-kid.jpg',
  );
  await page.getByTestId('meme-add-toggle').click();
  await expect(page.getByTestId('meme-add-image-open')).toHaveAttribute('aria-disabled', 'true');
});

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('поиск и формы без прокрутки вбок; лист кадров щёлкается', async ({ page, memes }) => {
    memes.jobs.state.pollS = 0.2;
    await openAdd(page);
    await expect(page.getByTestId('meme-search')).toHaveAttribute('placeholder', 'Поиск по мемам');
    await noSideScroll(page);
    await page.getByTestId('add-tab-sheet').click();
    await page.getByTestId('sheet-video').fill(VIDEO);
    await page.getByTestId('sheet-end').fill('40');
    await noSideScroll(page);
    await page.getByTestId('meme-sheet-open').click();
    await expect(page.getByRole('alertdialog').getByTestId('add-plan-facts')).toBeVisible();
    await noSideScroll(page);
    await page.getByRole('alertdialog').getByTestId('meme-sheet-confirm').click();
    const job = desk(page).getByTestId('meme-job');
    await expect(job).toHaveAttribute('data-state', 'done', { timeout: 15_000 });
    await noSideScroll(page);
    await job.getByRole('button', { name: 'Кадр 2 с', exact: true }).click();
    await job.getByRole('button', { name: 'Кадр 6 с', exact: true }).click();
    await expect(job.getByTestId('sheet-to-gif')).toBeEnabled();
  });
});
