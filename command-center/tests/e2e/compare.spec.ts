// Сравнение версий (CC-0063): исходная и пересборка рядом, одни кнопки на оба видео — пуск и
// пауза вместе, перемотка и шаг по кадру ставят обе на одно время; у каждой — подпись и
// приёмка. Телефон — переключатель, вторая версия прячется, но идёт в ногу; без прокрутки вбок.
import type { Page } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import { PAST_REDO } from '../../src/mocks/videos';
import { expect, noSideScroll, test } from './fixtures';

const states = (page: Page) =>
  page
    .getByTestId('compare-video')
    .evaluateAll((els) =>
      (els as HTMLVideoElement[]).map((v) => ({ t: v.currentTime, paused: v.paused })),
    );

/** Обе версии взяли метаданные файла: счёт кадров по файлу. */
async function ready(page: Page) {
  await expect(page.getByTestId('compare-frame')).toHaveCount(2);
  for (const f of await page.getByTestId('compare-frame').all())
    await expect(f).toHaveAttribute('data-meta', '1');
}

test.describe('сравнение версий', () => {
  test('две версии рядом: подписи, приёмка, синхронные пуск, пауза, перемотка и шаг', async ({
    page,
  }) => {
    await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=delver`);
    await page.getByTestId('compare-open').click();
    await expect(page).toHaveURL(/cmp=1/);
    const panes = page.getByTestId('compare-pane');
    await expect(panes).toHaveCount(2);
    await expect(panes.nth(0)).toHaveAttribute('data-batch', PAST);
    await expect(panes.nth(1)).toHaveAttribute('data-batch', PAST_REDO);
    await expect(page.getByTestId('compare-label')).toHaveText(['исходная', 'пересборка 1']);
    await expect(panes.nth(0).getByTestId('compare-state')).toContainText('ждёт решения');
    await expect(panes.nth(1).getByTestId('compare-state')).toContainText('ждёт решения');
    // Одиночный плеер не дублирует видео.
    await expect(page.getByTestId('player')).toHaveCount(0);
    await expect(page.getByTestId('player-in-compare')).toBeVisible();
    await ready(page);

    await page.getByTestId('compare-play').click();
    await expect.poll(async () => (await states(page)).every((s) => !s.paused)).toBe(true);
    await expect
      .poll(async () => Math.min(...(await states(page)).map((s) => s.t)))
      .toBeGreaterThan(0.2);
    await page.getByTestId('compare-play').click();
    await expect.poll(async () => (await states(page)).every((s) => s.paused)).toBe(true);

    await page.getByTestId('compare-seek').fill('2');
    await expect
      .poll(async () => (await states(page)).map((s) => s.t.toFixed(1)))
      .toEqual(['2.0', '2.0']);

    await page.getByTestId('compare-next').click();
    await expect
      .poll(async () => (await states(page)).map((s) => s.t.toFixed(3)))
      .toEqual([(61.5 / 30).toFixed(3), (61.5 / 30).toFixed(3)]);
    await expect(page.getByTestId('compare-frame').first()).toContainText('кадр 62 из 90');

    const player = page.getByTestId('compare-player');
    await player.focus();
    await page.keyboard.press(',');
    await page.keyboard.press(',');
    await expect
      .poll(async () => (await states(page)).map((s) => s.t.toFixed(3)))
      .toEqual([(59.5 / 30).toFixed(3), (59.5 / 30).toFixed(3)]);
    await page.keyboard.press(' ');
    await expect.poll(async () => (await states(page)).every((s) => !s.paused)).toBe(true);
    await page.keyboard.press(' ');
    await expect.poll(async () => (await states(page)).every((s) => s.paused)).toBe(true);

    // Другая пара: справа та же исходная — предупреждение; закрыть — снова один плеер.
    await page.getByTestId('compare-right').selectOption({ index: 0 });
    await expect(page.getByTestId('compare-same')).toBeVisible();
    await page.getByTestId('compare-close').click();
    await expect(page).not.toHaveURL(/cmp=1/);
    await expect(page.getByTestId('player')).toBeVisible();
  });

  test('ролик без пересборок — сравнивать нечего', async ({ page }) => {
    await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=rink-rivals&cmp=1`);
    await expect(page.getByTestId('player')).toBeVisible();
    await expect(page.getByTestId('compare')).toHaveCount(0);
    await expect(page.getByTestId('compare-open')).toHaveCount(0);
  });

  test('телефон: переключатель версий, вторая идёт в ногу, без прокрутки вбок', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=delver&cmp=1`);
    const panes = page.getByTestId('compare-pane');
    await expect(panes.nth(0)).toBeVisible();
    await expect(panes.nth(1)).toBeHidden();
    await ready(page);
    await noSideScroll(page);
    await page.getByTestId('compare-seek').fill('1');
    await page.locator('[data-testid="compare-show"][data-side="b"]').click();
    await expect(panes.nth(0)).toBeHidden();
    await expect(panes.nth(1)).toBeVisible();
    await expect(page.locator('[data-testid="compare-show"][data-side="b"]')).toHaveAttribute(
      'aria-pressed',
      'true',
    );
    await expect
      .poll(async () => (await states(page)).map((s) => s.t.toFixed(1)))
      .toEqual(['1.0', '1.0']);
    const box = await panes.nth(1).getByTestId('compare-video').boundingBox();
    expect(box!.width).toBeGreaterThan(390 - 2 * 16 - 2 * 14);
    await noSideScroll(page);
  });
});
