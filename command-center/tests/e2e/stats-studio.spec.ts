// CC-0077: ввод прочитанного в Studio на подставном API (src/mocks/analyticsStudio.ts). Два ролика
// → план фабрики → «да» с отсчётом → итог словами и перечитанный блок; отказ
// `read_refused`; «да» после перемены — план заново сам; истёкший план; телефон 390 без прокрутки
// вбок; тренировка. Пока человек не попросил план, с экрана уходят только GET.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, openTip, test } from './fixtures';

const writes = (hits: string[]) => hits.filter((h) => !h.startsWith('GET '));

async function openEntry(page: Page) {
  await page.goto('/stats');
  const block = page.getByTestId('stats-studio');
  await expect(block.getByTestId('studio-due')).toContainText('пора читать');
  await block.getByTestId('studio-entry-toggle').click();
  const cards = block.getByTestId('studio-entry-video');
  await expect(cards).toHaveCount(5);
  return { block, cards };
}

async function fillTwo(page: Page) {
  const { block, cards } = await openEntry(page);
  await cards.nth(0).getByTestId('studio-lines').fill('Досмотрели\n72,4 %\nПролистали\n27,6 %');
  await cards.nth(3).getByTestId('studio-lines').fill('Продолжили смотреть\n58 %');
  return { block, cards };
}

async function plan(page: Page, block: ReturnType<Page['getByTestId']>) {
  await block.getByTestId('studio-entry-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  return { dialog, yes: dialog.getByTestId('studio-entry-confirm') };
}

test('два ролика → план → «да» → итог; до плана — только GET', async ({
  page,
  apiHits,
  analytics,
}) => {
  const { block, cards } = await fillTwo(page);
  await expect(cards.nth(0).getByRole('link', { name: 'Открыть в Studio' })).toHaveAttribute(
    'href',
    /studio\.youtube\.com\/video\/dN3vEr5mTh8\//,
  );
  await openTip(page, cards.nth(0).getByText('Строки из Studio'), 'Скопируйте со страницы');
  expect(writes(apiHits), 'до плана ничего, кроме GET').toEqual([]);

  const { dialog, yes } = await plan(page, block);
  const vids = dialog.getByTestId('studio-plan-video');
  await expect(vids).toHaveCount(2);
  await expect(vids.nth(0)).toContainText('Sandfall messiah');
  await expect(vids.nth(0).getByTestId('studio-plan-viewed')).toHaveText(
    'Досмотрели: 72,4 % · раньше не читали',
  );
  await expect(vids.nth(0).getByTestId('studio-plan-swiped')).toHaveText(
    'Пролистали: 27,6 % · раньше не читали',
  );
  await expect(vids.nth(1).getByTestId('studio-plan-viewed')).toHaveText(
    'Досмотрели: было 55,2 % → станет 58 %',
  );
  await expect(yes).toHaveText(/Внести · [12]:\d\d/);
  expect(writes(apiHits)).toEqual(['POST /api/analytics/example-film/studio/record/plan']);
  expect(analytics.entry.state.written).toEqual([]);

  await yes.click();
  await expect(dialog).toBeHidden();
  const done = block.getByTestId('studio-done');
  await expect(done).toContainText('Цифры Studio внесены');
  await expect(done.getByTestId('studio-done-videos')).toHaveText(
    'Чтения роликов: новых — 2, заменено — 0, без изменений — 0.',
  );
  expect(analytics.entry.state.written).toHaveLength(1);
  // Блок перечитан: страховка закрыта, у Sandfall — новая доля; форма пуста.
  await expect(block.getByTestId('studio-due')).toContainText('рано');
  await expect(block.getByTestId('studio-video').filter({ hasText: 'Sandfall messiah' })).toContainText(
    'досмотрели 72,4 %',
  );
  await expect(cards.nth(0).getByTestId('studio-lines')).toHaveValue('');
});

test.describe('отказы (браузер пишет 4xx в консоль)', () => {
  test.use({ expectCleanConsole: false });

  test('read_refused — русский заголовок и строка фабрики, ничего не записано', async ({
    page,
    analytics,
  }) => {
    // Ролик Sandfall в журнале у другого канала: Studio показывала не тот канал.
    const tech = analytics.state.videos['example-tech']!;
    tech.push({ ...tech[0]!, video_id: 'dN3vEr5mTh8' });
    const { block } = await fillTwo(page);
    const { dialog, yes } = await plan(page, block);
    const refusal = dialog.getByTestId('write-refusal');
    await expect(refusal).toHaveAttribute('data-code', 'read_refused');
    await expect(refusal.getByTestId('write-refusal-title')).toHaveText(
      'Фабрика не приняла прочитанное — ничего не записано',
    );
    await expect(refusal.getByTestId('write-refusal-message')).toContainText(
      'is of channel example-tech',
    );
    await expect(yes).toBeDisabled();
    expect(analytics.entry.state.written).toEqual([]);
  });

  test('«да» после перемены — план заново сам, второе «да» пишет', async ({ page, analytics }) => {
    const { block } = await fillTwo(page);
    const { dialog, yes } = await plan(page, block);
    await expect(yes).toBeEnabled();
    analytics.entry.state.next = 'check_changed';
    await yes.click();
    await expect(dialog.getByTestId('replanned')).toHaveAttribute('data-code', 'check_changed');
    await expect(dialog.getByTestId('replanned')).toContainText('посмотрите план заново');
    await expect(yes).toBeEnabled();
    expect(analytics.entry.state.calls.filter((c) => c.kind === 'plan')).toHaveLength(2);
    await yes.click();
    await expect(block.getByTestId('studio-done')).toBeVisible();
    expect(analytics.entry.state.written).toHaveLength(1);
  });

  test('план устарел — «Проверить заново» даёт новый', async ({ page, analytics }) => {
    analytics.entry.state.life = 2;
    const { block } = await fillTwo(page);
    const { dialog, yes } = await plan(page, block);
    await expect(yes).toHaveText(/Внести · 0:0[12]/);
    await expect(dialog.getByTestId('token-expired')).toBeVisible({ timeout: 6000 });
    await expect(yes).toBeDisabled();
    analytics.entry.state.life = 120;
    await dialog.getByTestId('replan').click();
    await expect(yes).toBeEnabled();
    await expect(dialog.getByTestId('token-expired')).toHaveCount(0);
    await yes.click();
    await expect(block.getByTestId('studio-done')).toBeVisible();
  });
});

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('форма, план и итог без прокрутки вбок', async ({ page, apiHits }) => {
    const { block } = await fillTwo(page);
    await noSideScroll(page);
    expect(writes(apiHits)).toEqual([]);
    const { dialog, yes } = await plan(page, block);
    await noSideScroll(page);
    await yes.click();
    await expect(block.getByTestId('studio-done')).toBeVisible();
    await noSideScroll(page);
  });
});

test('тренировка: ввод цифр Studio на демо-данных, живой API не тронут', async ({
  page,
  apiHits,
}) => {
  test.setTimeout(90_000);
  await page.goto('/');
  await expect(page.getByTestId('attention')).toBeVisible();
  await page.getByTestId('tour-open').click();
  await page.getByTestId('tour-contents').getByTestId('tour-practice').click();
  await expect(page.getByTestId('training-banner-text')).toBeVisible();
  const live = apiHits.length;
  if (await page.getByTestId('training-panel').isVisible())
    await page.getByTestId('training-collapse').click();
  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Статистика', exact: true })
    .click();
  const block = page.getByTestId('stats-studio');
  await block.getByTestId('studio-entry-toggle').click();
  await block
    .getByTestId('studio-entry-video')
    .nth(0)
    .getByTestId('studio-lines')
    .fill('Досмотрели\n61 %');
  const { yes } = await plan(page, block);
  await yes.click();
  await expect(block.getByTestId('studio-done')).toContainText('Цифры Studio внесены');
  expect(apiHits.slice(live)).toEqual([]);
});
