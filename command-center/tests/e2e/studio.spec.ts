// «Прочитать Studio» по хукам действий (CC-0120, фабрика CF-0735) на подставном API
// (src/mocks/studio.ts): хук первого открытия за день — кнопка в шапке с окошком (CC-0151); окно
// запуска батча и карточка загрузки — подсвеченная кнопка; запуск выключен (как на проде) —
// кнопка погашена с причиной, план виден; включён — «да», опрос, итог одной строкой. Тихие
// решения плана — строки журнала на карточке батча; `?channel=` выбирает канал; телефон.
import type { Page } from '@playwright/test';

import { RUNNING } from '../../src/mocks/batches';
import { REEL } from '../../src/mocks/publish';
import { LAUNCH_OFF_WHY } from '../../src/mocks/studio';
import { expect, noSideScroll, test } from './fixtures';

const FIRST = 'center-first-open-of-day';
const pop = (page: Page) => page.getByTestId('studio-pop');

/** CC-0151: блок хука первого открытия — в окошке кнопки «Пора прочитать Studio» в шапке. */
async function banner(page: Page) {
  if (!(await pop(page).isVisible())) await page.getByTestId('studio-pop-open').click();
  return pop(page).getByTestId('studio-due');
}

async function confirmRead(page: Page) {
  await (await banner(page)).getByTestId('studio-read-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('studio-plan')).toBeVisible();
  await expect(dialog.getByTestId('studio-read-confirm')).toHaveText(/^Прочитать · \d:\d\d$/);
  await dialog.getByTestId('studio-read-confirm').click();
  await expect(dialog).toBeHidden();
}

test('не пора — полосы нет; хук первого открытия спрошен один раз на загрузку', async ({
  page,
  studio,
}) => {
  await page.goto('/');
  await expect.poll(() => studio.calls).toContain(`GET due?hook=${FIRST}`);
  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Батчи' })
    .click();
  await expect(page.getByTestId('launch-open')).toBeVisible();
  expect(studio.calls.filter((c) => c === `GET due?hook=${FIRST}`)).toHaveLength(1);
  await expect(page.getByTestId('studio-due')).toHaveCount(0);
});

test('пора, запуск выключен: кнопка погашена с причиной, план виден, «да» недоступно', async ({
  page,
  studio,
  apiHits,
}) => {
  studio.setDue(true, [FIRST]);
  await page.goto('/');
  const box = await banner(page);
  await expect(box.getByTestId('studio-why')).toContainText('Studio не читали 30 ч');
  await expect(box.getByTestId('studio-read-open')).toBeDisabled();
  await expect(box.getByTestId('studio-launch-off')).toHaveText(LAUNCH_OFF_WHY);
  await box.getByTestId('studio-read-plan').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('studio-plan-channel')).toHaveCount(3);
  await expect(dialog.getByTestId('studio-plan-chrome')).toContainText(
    'Только чтение в вашем Chrome',
  );
  await expect(dialog.getByTestId('studio-plan-off')).toContainText(
    'первый запуск делается вместе с вами',
  );
  await expect(dialog.getByTestId('studio-read-confirm')).toBeDisabled();
  await dialog.getByRole('button', { name: 'Отмена' }).click();
  expect(apiHits).not.toContain('POST /api/studio/read');
});

test('запуск включён: «да» → «читается» → «прочитано», полоса гаснет после «Скрыть»', async ({
  page,
  studio,
}) => {
  studio.setDue(true, [FIRST]);
  studio.setLaunch(true);
  studio.state.pollsToDone = 2;
  await page.goto('/');
  await confirmRead(page);
  await expect(page.getByTestId('studio-reading')).toBeVisible();
  const result = page.getByTestId('studio-result');
  await expect(result).toHaveAttribute('data-code', 'read');
  await expect(result).toContainText('Studio: прочитано');
  await result.getByTestId('studio-result-close').click();
  await expect(page.getByTestId('studio-due')).toHaveCount(0);
  await expect(page.getByTestId('studio-pop-open')).toHaveCount(0);
});

for (const [code, word, next] of [
  ['no_extension', 'расширение не подключено', 'включите расширение'],
  ['login_needed', 'нужен вход', 'войдите в Chrome и нажмите ещё раз'],
] as const) {
  test(`исход «${word}» — одной строкой и что сделать`, async ({ page, studio }) => {
    studio.setDue(true, [FIRST]);
    studio.setLaunch(true);
    studio.setOutcome(code);
    await page.goto('/');
    await confirmRead(page);
    const result = page.getByTestId('studio-result');
    await expect(result).toHaveAttribute('data-code', code);
    await expect(result).toContainText(`Studio: ${word}`);
    await expect(result.getByTestId('studio-result-line')).toContainText(next);
    // Что сделать — один раз, «Подробнее» у полосы — одно (ревью экранов).
    await expect(result.getByTestId('studio-result-next')).toHaveCount(0);
    await expect(page.getByTestId('studio-due').locator('summary')).toHaveCount(1);
  });
}

test('окно запуска батча: хук «запуск батча» подсвечивает кнопку, запуск не ждёт чтения', async ({
  page,
  studio,
}) => {
  studio.setDue(true, ['batch-start']);
  await page.goto('/batches');
  await page.getByTestId('launch-open').click();
  const dialog = page.getByRole('alertdialog');
  const due = dialog.getByTestId('studio-due');
  await expect(due).toHaveAttribute('data-hook', 'batch-start');
  await expect(due.getByTestId('studio-hook')).toContainText('запуск батча');
  await expect(dialog.getByTestId('launch-plan')).toBeVisible();
  expect(studio.calls).not.toContain('POST plan');
});

test('карточка загрузки: хук «загрузка» подсвечивает кнопку', async ({ page, studio }) => {
  studio.setDue(true, ['upload']);
  await page.goto(`/publishing?channel=${REEL}`);
  const due = page.getByTestId('upload-writes').getByTestId('studio-due');
  await expect(due).toHaveAttribute('data-hook', 'upload');
  await expect(due.getByTestId('studio-why')).toContainText('пора проверить досмотры');
});

test('«пропущено тихо» на карточке батча — строкой журнала, не тревогой', async ({
  page,
  batches,
}) => {
  batches.setQuiet(RUNNING, [
    {
      stage: 'studio-read-due',
      key: 'studio-read@example-film',
      line: 'Studio не прочитан — нет разрешения; взято по умолчанию',
      took: 'skipped_no_permission',
      at: '2026-10-10T05:31:00Z',
    },
  ]);
  await page.goto('/batches');
  const block = page
    .locator(`[data-testid="open-batch"][data-batch="${RUNNING}"]`)
    .getByTestId('batch-quiet');
  await expect(block.getByTestId('batch-quiet-line')).toContainText(
    'пропущено тихо: Чтение Studio — Studio не прочитан',
  );
  await expect(block.getByRole('alert')).toHaveCount(0);
});

test('?channel= в ссылке уведомления выбирает канал на «Батчах» и «Роликах»', async ({
  page,
}) => {
  await page.goto('/batches?channel=example-tech');
  await expect(page.getByTestId('launch-channel')).toHaveValue('example-tech');
  await page.goto('/videos?channel=example-tech');
  await expect(page.getByTestId('batch-picker')).toHaveValue(/^example-tech\//);
});

test('телефон: окошко Studio и окно плана без прокрутки вбок', async ({ page, studio }) => {
  studio.setDue(true, [FIRST]);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  const box = await banner(page);
  await expect(box.getByTestId('studio-read-open')).toBeVisible();
  await noSideScroll(page);
  await box.getByTestId('studio-read-plan').click();
  await expect(page.getByRole('alertdialog').getByTestId('studio-plan')).toBeVisible();
  await noSideScroll(page);
});

// CC-0151: вместо полосы под шапкой — кнопка в шапке и окошко как панель аккаунта Google.
test.describe('кнопка «Пора прочитать Studio» в шапке', () => {
  const opener = (page: Page) =>
    page.getByRole('banner').getByRole('button', { name: 'Пора прочитать Studio' });

  test('не пора — кнопки нет', async ({ page, studio }) => {
    await page.goto('/');
    await expect.poll(() => studio.calls).toContain(`GET due?hook=${FIRST}`);
    await expect(page.getByTestId('studio-pop-open')).toHaveCount(0);
  });

  test('окошко под кнопкой у правого края, страница не сдвигается', async ({ page, studio }) => {
    studio.setDue(true, [FIRST]);
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/');
    const btn = opener(page);
    await expect(btn.getByTestId('studio-pop-mark')).toBeVisible();
    await expect(page.getByTestId('studio-banner')).toHaveCount(0);
    const main = await page.locator('main').boundingBox();
    await btn.click();
    const dialog = page.getByRole('dialog', { name: 'Пора прочитать Studio' });
    await expect(dialog).toBeVisible();
    await expect(dialog).toBeFocused();
    await expect(btn).toHaveAttribute('aria-expanded', 'true');
    expect(await btn.getAttribute('aria-controls')).toBe(await dialog.getAttribute('id'));
    await expect(dialog.getByTestId('studio-why')).toContainText('Studio не читали 30 ч');
    await expect(dialog.getByTestId('studio-age')).toHaveCount(0);
    await expect(dialog.getByTestId('studio-hook')).toHaveText(
      'Повод: первое открытие центра за день',
    );
    await expect(dialog.getByTestId('studio-read-open')).toBeVisible();
    const b = (await btn.boundingBox())!;
    const d = (await dialog.boundingBox())!;
    expect(Math.abs(d.x + d.width - (b.x + b.width))).toBeLessThanOrEqual(1);
    expect(d.y).toBeGreaterThan(b.y + b.height);
    expect(
      await page.evaluate(
        () =>
          getComputedStyle(document.querySelector('[data-testid="studio-pop"]')!)
            .borderTopLeftRadius,
      ),
    ).toBe('24px');
    expect(await page.locator('main').boundingBox()).toEqual(main);
  });

  for (const how of ['Esc', 'клик вне', 'крестик'] as const) {
    test(`закрывается: ${how} — фокус возвращается на кнопку`, async ({ page, studio }) => {
      studio.setDue(true, [FIRST]);
      await page.goto('/');
      const btn = opener(page);
      await btn.click();
      const dialog = page.getByRole('dialog', { name: 'Пора прочитать Studio' });
      await expect(dialog).toBeFocused();
      if (how === 'Esc') await page.keyboard.press('Escape');
      else if (how === 'клик вне') await page.mouse.click(5, 400);
      else await dialog.getByRole('button', { name: 'Закрыть' }).click();
      await expect(dialog).toHaveCount(0);
      await expect(btn).toHaveAttribute('aria-expanded', 'false');
      await expect(btn).toBeFocused();
    });
  }

  test('окно подтверждения поверх окошка: Esc закрывает только его', async ({ page, studio }) => {
    studio.setDue(true, [FIRST]);
    studio.setLaunch(true);
    await page.goto('/');
    await opener(page).click();
    const dialog = page.getByRole('dialog', { name: 'Пора прочитать Studio' });
    await dialog.getByTestId('studio-read-open').click();
    const confirm = page.getByRole('alertdialog');
    await expect(confirm.getByTestId('studio-plan')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(confirm).toBeHidden();
    await expect(dialog).toBeVisible();
    await expect(dialog.getByTestId('studio-read-open')).toBeFocused();
  });

  test('телефон: окошко на всю ширину с полями 16px, без прокрутки вбок', async ({
    page,
    studio,
  }) => {
    studio.setDue(true, [FIRST]);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/');
    await opener(page).click();
    const dialog = page.getByRole('dialog', { name: 'Пора прочитать Studio' });
    await expect(dialog.getByTestId('studio-read-open')).toBeVisible();
    const d = (await dialog.boundingBox())!;
    expect(d.x).toBeCloseTo(16, 0);
    expect(d.width).toBeCloseTo(390 - 32, 0);
    await noSideScroll(page);
  });

  test('низкий экран: окошко прокручивается внутри себя', async ({ page, studio }) => {
    studio.setDue(true, [FIRST]);
    await page.setViewportSize({ width: 390, height: 300 });
    await page.goto('/');
    await opener(page).click();
    const dialog = page.getByRole('dialog', { name: 'Пора прочитать Studio' });
    await expect(dialog).toBeVisible();
    const fit = await dialog.evaluate((el) => ({
      bottom: el.getBoundingClientRect().bottom,
      scrolls: el.scrollHeight > el.clientHeight,
      overflow: getComputedStyle(el).overflowY,
    }));
    expect(fit.bottom).toBeLessThanOrEqual(300);
    expect(fit.overflow).toBe('auto');
    expect(fit.scrolls).toBe(true);
  });
});
