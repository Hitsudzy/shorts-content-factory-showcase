// CC-0125: оценка ролика — значок «A · 86» цвета тира и окно «Оценка ролика» с разбором.
// Подставной API (src/mocks/score.ts): у delver — полный журнал (пять стадий, потолок, находка
// со временем, прогноз), у sophie-adenot (отказан после монтажа) — разбор из 05 с жёсткой
// находкой; по ролику на тир S/A/B/C/D/F. «к моменту ▶» на странице ролика ставит плеер на время.
import { PAST } from '../../src/mocks/batches';
import { REEL } from '../../src/mocks/publish';
import { SCORE_FULL, SCORE_HARD, SCORE_MOMENT_T } from '../../src/mocks/score';
import { STASH_HELD } from '../../src/mocks/stash';
import { OLDER, SCIENCE } from '../../src/mocks/videos';
import { expect, noSideScroll, openTip, test } from './fixtures';

const at = (batch: string, slug?: string, extra = '') =>
  `/videos?batch=${encodeURIComponent(batch)}${slug ? `&v=${encodeURIComponent(slug)}` : ''}${extra}`;

test.describe('оценка ролика', () => {
  test('список: значок у каждого ролика, буква и баллы, подсказка; тиры S…F разного цвета', async ({
    page,
  }) => {
    await page.goto(at(PAST));
    const badges = page.getByTestId('reel').getByTestId('score-badge');
    await expect(badges).toHaveText(['B · 74', 'A · 82', 'C · 58']);
    await openTip(page, badges.first(), 'Оценка ролика — подробнее');
    // Цвета тиров — разные (токены темы), буква — всегда.
    const colors = new Set<string>();
    for (const [batch, n] of [
      [PAST, 4],
      [OLDER, 4],
      [SCIENCE, 2],
    ] as const) {
      await page.goto(at(batch));
      const list = page.getByTestId('reels').getByTestId('score-badge');
      await expect(list).toHaveCount(n);
      for (const c of await list.evaluateAll((els) => els.map((e) => getComputedStyle(e).color)))
        colors.add(c);
    }
    expect(colors.size).toBe(6);
  });

  test('окно разбора: стадии, штрафы по цене, потолок, прогноз; «Ниже ещё ↓»; Esc закрывает', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 1280, height: 640 });
    await page.goto(at(PAST));
    const reel = page.locator(`[data-testid="reel"][data-slug="${SCORE_FULL}"]`);
    await reel.getByTestId('score-badge').click();
    const dialog = page.getByRole('alertdialog', { name: 'Оценка ролика' });
    await expect(dialog.getByTestId('score-big')).toContainText('B');
    await expect(dialog.getByTestId('score-stage')).toHaveCount(5);
    await expect(dialog.getByTestId('score-penalties').getByTestId('score-price')).toHaveText([
      '−10',
      '−7',
      '−6',
      '−3',
    ]);
    await expect(dialog.getByTestId('score-capped')).toContainText('потолок правила');
    await expect(dialog.getByTestId('score-forecast')).toContainText('в счёт не идёт');
    await expect(dialog.getByTestId('dialog-more-below')).toBeVisible();
    await expect(dialog.getByText(/\/Users\//)).toHaveCount(0);
    await page.keyboard.press('Escape');
    await expect(dialog).toHaveCount(0);
    await expect(reel.getByTestId('score-badge')).toBeFocused();
  });

  test('страница ролика: «к моменту ▶» ставит плеер на время находки; из списка — ссылкой с ?t=', async ({
    page,
  }) => {
    await page.goto(at(PAST, SCORE_FULL));
    const video = page.getByTestId('player-video');
    await expect(page.getByTestId('video-score').getByTestId('score-badge')).toHaveText('B · 74');
    await page.getByTestId('video-score').getByTestId('score-badge').click();
    await page.getByRole('alertdialog').getByTestId('score-moment').first().click();
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    // Файл-заглушка короче ролика (≈3 с): плеер встаёт на время находки или на конец файла.
    await expect
      .poll(() =>
        video.evaluate(
          (v: HTMLVideoElement, t) => Math.abs(v.currentTime - Math.min(t, v.duration)) < 0.05,
          SCORE_MOMENT_T,
        ),
      )
      .toBe(true);

    await page.goto(at(PAST, SCORE_FULL, '&t=1.5'));
    await expect
      .poll(() => page.getByTestId('player-video').evaluate((v: HTMLVideoElement) => v.currentTime))
      .toBeCloseTo(1.5, 1);
  });

  test('отказанный после монтажа: F, жёсткие сверху красным, остановлен досрочно', async ({
    page,
  }) => {
    await page.goto(at(SCIENCE, SCORE_HARD));
    const badge = page.getByTestId('refused').getByTestId('score-badge');
    await expect(badge).toHaveText('F · 24');
    await badge.click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('score-hard')).toContainText('ролик F при любых баллах');
    await expect(dialog.getByTestId('score-stopped')).toContainText('Остановлен досрочно');
    await expect(dialog.getByTestId('score-passed')).toHaveText('Не прошёл порог канала');
  });

  test('копилка и главная: значок с разбором', async ({ page }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    const row = page.locator(`[data-testid="stash-row"][data-slug="${STASH_HELD}"]`);
    await expect(row.getByTestId('score-badge')).toHaveText('A · 84');
    // Значок на главной — в конце цепочки: кусок экрана → история батчей → ролики последнего
    // батча. Под нагрузкой (CC-0131) одно окно ожидания на всю цепочку не успевало: ждём каждое
    // звено по его признаку — карточка прочла ролики (`data-waiting`), ждущий ролик на месте.
    await page.goto('/');
    const card = page.getByTestId('reels-card');
    await expect(card).toHaveAttribute('data-waiting', '1');
    const item = card.locator('[data-testid="reels-item"][data-slug="delver"]');
    await expect(item.getByTestId('score-badge')).toHaveText('B · 74');
  });

  test('телефон: окно разбора без бокового скролла', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 740 });
    await page.goto(at(PAST, SCORE_FULL));
    await page.getByTestId('video-score').getByTestId('score-badge').click();
    await expect(page.getByRole('alertdialog').getByTestId('score-body')).toBeVisible();
    await noSideScroll(page);
  });
});
