// «Ролики» (CC-0061): список батча обложками, последний батч по умолчанию, выбор батча,
// пересборка рядом с исходником, ссылка из «Батчей», плеер (пуск, перемотка по Range, шаг
// по кадру, клавиши), обложки кадр/лист, карточка с «подробнее», приёмка только чтением
// (в том числе «ждёт конца батча»), телефон без прокрутки вбок. Подставной API — с состоянием.
import type { Page } from '@playwright/test';

import { PAST, PAST_REBUILD } from '../../src/mocks/batches';
import { OLDER } from '../../src/mocks/videos';
import { expect, openTip, test } from './fixtures';

const slugs = (page: Page) =>
  page
    .getByTestId('reels')
    .locator(':scope > li')
    .evaluateAll((els) =>
      els.map((e) => `${e.getAttribute('data-testid')}:${e.getAttribute('data-slug')}`),
    );

const videoState = (page: Page) =>
  page.getByTestId('player-video').evaluate((v: HTMLVideoElement) => ({
    t: v.currentTime,
    paused: v.paused,
    ready: v.readyState,
  }));

async function openVideo(page: Page, slug: string) {
  await page.locator(`[data-testid="reel"][data-slug="${slug}"] a`).click();
  await expect(page.getByTestId('video-detail')).toHaveAttribute('data-slug', slug);
  // Метаданные пришли и плеер их взял: счёт кадров — по файлу, а не по списку («≈»).
  await expect.poll(async () => (await videoState(page)).ready).toBeGreaterThanOrEqual(1);
  await expect(page.getByTestId('player-frame')).toHaveAttribute('data-meta', '1');
}

test.describe('ролики', () => {
  test('по умолчанию — последний батч истории, пересборка рядом с исходником', async ({ page }) => {
    await page.goto('/videos');
    await expect(page.getByRole('heading', { level: 1, name: 'Ролики' })).toBeVisible();
    await expect(page.getByTestId('batch-picker')).toHaveValue(PAST);
    await expect(page.getByTestId('batch-videos')).toHaveAttribute('data-batch', PAST);
    await expect
      .poll(() => slugs(page))
      .toEqual([
        'reel:delver',
        'reel-version:delver',
        'reel:rink-rivals',
        'reel:vanguards-doomsday',
      ]);
    const version = page.getByTestId('reel-version');
    await expect(version).toContainText('Пересборка 1');
    await expect(version).toContainText('версия ролика');
    await expect(page.locator('#reels-title')).toContainText('3 ролика');
    await expect(page.locator('#reels-title')).toContainText('ждут решения: 1');
    // Только смотреть: кнопок вердикта на экране нет (это CC-0062).
    await expect(page.getByRole('button', { name: /Принять|Переделать/ })).toHaveCount(0);
  });

  test('выбор батча: другой батч и пересборка со ссылкой на исходник', async ({ page }) => {
    await page.goto('/videos');
    await page.getByTestId('batch-picker').selectOption(OLDER);
    await expect(page).toHaveURL(/batch=example-film%2F2026-10-06T0210Z/);
    await expect
      .poll(() => slugs(page))
      .toEqual([
        'reel:quiet-keyboards',
        'reel-version:quiet-keyboards',
        'reel:usb-c-myths',
        'reel-version:usb-c-myths',
      ]);
    await page.getByTestId('batch-picker').selectOption(PAST_REBUILD);
    await expect(page.getByTestId('rebuild-of')).toContainText('пересборка роликов батча');
    await page.getByTestId('rebuild-of').getByRole('link').click();
    await expect(page.getByTestId('batch-picker')).toHaveValue(OLDER);
  });

  test('из «Батчей»: раскрытый прогон ведёт к своим роликам', async ({ page }) => {
    await page.goto('/batches');
    const run = page.locator(`[data-testid="run"][data-batch="${PAST}"]`);
    await run.getByRole('button', { expanded: false }).click();
    await run.getByTestId('run-videos').click();
    await expect(page).toHaveURL(/\/videos\?batch=example-film%2F2026-10-09T0215Z$/);
    await expect(page.getByTestId('batch-videos')).toHaveAttribute('data-batch', PAST);
  });

  test('плеер: пуск, перемотка по Range, шаг по кадру кнопками и клавишами', async ({
    page,
    videos,
  }) => {
    await page.goto('/videos');
    await openVideo(page, 'rink-rivals');
    await expect(page.getByTestId('player-frame')).toHaveAttribute('data-fps', '30');

    await page.getByTestId('player-play').click();
    await expect.poll(async () => (await videoState(page)).t).toBeGreaterThan(0.2);
    await page.getByTestId('player-play').click();
    await expect.poll(async () => (await videoState(page)).paused).toBe(true);

    // Перемотка полосой: браузер спрашивает файл диапазонами, мок отвечает 206.
    await page.getByTestId('player-seek').fill('2');
    await expect.poll(async () => (await videoState(page)).t).toBeCloseTo(2, 1);
    expect(videos.mp4Calls.some((r) => r?.startsWith('bytes='))).toBe(true);

    // Шаг кадра: ровно 1/30 с, на середину кадра.
    await page.getByTestId('player-seek').fill('1');
    await page.getByTestId('player-next').click();
    await expect.poll(async () => (await videoState(page)).t).toBeCloseTo(31.5 / 30, 3);
    await expect(page.getByTestId('player-frame')).toContainText('кадр 32 из 90');
    await page.getByTestId('player-prev').click();
    await page.getByTestId('player-prev').click();
    await expect.poll(async () => (await videoState(page)).t).toBeCloseTo(29.5 / 30, 3);

    // Клавиши: , . — кадр; ← → — секунда; пробел — пуск и пауза.
    const player = page.getByTestId('player');
    await player.focus();
    await page.keyboard.press('.');
    await expect.poll(async () => (await videoState(page)).t).toBeCloseTo(30.5 / 30, 3);
    await page.keyboard.press(',');
    await page.keyboard.press(',');
    await expect.poll(async () => (await videoState(page)).t).toBeCloseTo(28.5 / 30, 3);
    await page.keyboard.press('ArrowRight');
    await expect.poll(async () => (await videoState(page)).t).toBeCloseTo(28.5 / 30 + 1, 2);
    await page.keyboard.press('ArrowLeft');
    await page.keyboard.press('ArrowLeft');
    await expect.poll(async () => (await videoState(page)).t).toBeCloseTo(0, 2);
    await page.keyboard.press(' ');
    await expect.poll(async () => (await videoState(page)).paused).toBe(false);
    await page.keyboard.press(' ');
    await expect.poll(async () => (await videoState(page)).paused).toBe(true);
    await openTip(page, page.getByTestId('player-keys'), 'на кадр назад и вперёд');
  });

  test('обложки: кадр монтажа как есть, лист судьи — первая плитка, без превью — название', async ({
    page,
  }) => {
    await page.goto('/videos');
    const frame = page.locator('[data-testid="reel"][data-slug="rink-rivals"]');
    await expect(frame.getByTestId('poster-frame')).toHaveAttribute(
      'src',
      /rink-rivals\/preview$/,
    );
    const sheet = page
      .locator('[data-testid="reel"][data-slug="delver"]')
      .getByTestId('poster-sheet');
    await expect(sheet).toHaveCSS('background-size', '300% 200%');
    await expect(sheet).toHaveCSS('background-position', '0px 0px');
    const none = page.locator('[data-testid="reel"][data-slug="vanguards-doomsday"]');
    await expect(none.locator('[data-slot="cover"]')).toHaveAttribute('data-poster', 'none');
    await expect(none.locator('[data-slot="cover"]')).toContainText('Vanguards');

    // В плеере: кадр — атрибут poster; лист — плитка поверх видео, пока ролик не тронут.
    await openVideo(page, 'rink-rivals');
    await expect(page.getByTestId('player-video')).toHaveAttribute(
      'poster',
      /rink-rivals\/preview$/,
    );
    await openVideo(page, 'delver');
    await expect(page.getByTestId('player-video')).not.toHaveAttribute('poster', /.*/);
    const overlay = page.getByTestId('player').getByTestId('poster-sheet');
    await expect(overlay).toBeVisible();
    await page.getByTestId('player-next').click();
    await expect(overlay).toBeHidden();
  });

  test('карточка публикации разобрана, текст целиком — в «подробнее»', async ({ page }) => {
    await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=delver`);
    const card = page.getByTestId('publish-card');
    await expect(card.getByTestId('card-title')).toHaveText(/one-take mine scene/);
    await expect(card.getByTestId('card-description').locator('p')).toHaveCount(3);
    await expect(card.getByTestId('card-tags').locator('li')).toHaveCount(4);
    await expect(card.getByTestId('card-publish')).toContainText('11.10');
    await expect(card.getByTestId('card-raw')).toBeHidden();
    await card.locator('[data-slot="more"] > summary').click();
    await expect(card.getByTestId('card-raw')).toContainText('## Название');
    // Карточка не готова: почему и замечания — на виду.
    await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=vanguards-doomsday`);
    await expect(page.getByTestId('card-why')).toContainText('Публикация');
    await expect(page.getByTestId('card-problems')).toContainText('слот не назначен');
  });

  test('приёмка только чтением: принят со словами, «ждёт конца батча», ещё нет вердикта', async ({
    page,
  }) => {
    await page.goto('/videos');
    const vanguards = page.locator('[data-testid="reel"][data-slug="vanguards-doomsday"]');
    await expect(vanguards.getByTestId('reel-state')).toContainText('ждёт конца батча');
    await openVideo(page, 'vanguards-doomsday');
    const acc = page.getByTestId('acceptance');
    await expect(acc.getByTestId('acceptance-pending')).toContainText('Записано, ждёт конца батча');
    await expect(acc.getByTestId('acceptance-reason')).toContainText('хук про дату скучный');
    await openVideo(page, 'rink-rivals');
    await expect(acc.getByTestId('acceptance-verdict')).toHaveText('принят');
    await expect(acc.getByTestId('acceptance-words')).toContainText(
      'Rink Rivals: the casting call that broke the fandom — да, берём',
    );
    await expect(acc.getByTestId('acceptance-pending')).toHaveCount(0);
    await openVideo(page, 'delver');
    await expect(acc.getByTestId('acceptance-verdict')).toHaveText('ждёт решения');
    await expect(acc.locator('[data-slot="acceptance-actions"]')).toBeVisible();
    await expect(
      acc.getByRole('group', { name: 'Ваше решение по ролику' }).getByRole('button'),
    ).toHaveText(['Да', 'Переделать', 'Нет']);
  });

  test('версии ролика: пересборка открывается рядом с исходником', async ({ page }) => {
    await page.goto('/videos');
    await page.locator('[data-testid="reel-version"][data-slug="delver"] a').click();
    const detail = page.getByTestId('video-detail');
    await expect(detail).toHaveAttribute('data-batch', 'rebuilds/2026-10-09T1500Z');
    await expect(detail.getByTestId('version-link')).toHaveText(['исходная', 'пересборка 1']);
    await expect(page.getByTestId('player-video')).toHaveAttribute(
      'src',
      /rebuilds\/2026-10-09T1500Z\/videos\/delver\/mp4$/,
    );
    await detail.getByTestId('version-link').first().click();
    await expect(detail).toHaveAttribute('data-batch', PAST);
  });

  test('телефон: без прокрутки вбок, плеер во всю ширину', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=delver`);
    await expect(page.getByTestId('player')).toBeVisible();
    await page.getByTestId('publish-card').locator('[data-slot="more"] > summary').click();
    const { scroll, client } = await page.evaluate(() => ({
      scroll: document.documentElement.scrollWidth,
      client: document.documentElement.clientWidth,
    }));
    // Что вылезло за край (кроме того, что внутри своей прокрутки, — строка табов).
    const wide = await page.evaluate(() => {
      const w = document.documentElement.clientWidth;
      const clipped = (e: Element | null): boolean =>
        !!e && (getComputedStyle(e).overflowX !== 'visible' || clipped(e.parentElement));
      return [...document.querySelectorAll('body *')]
        .filter((e) => e.getBoundingClientRect().right > w + 1 && !clipped(e.parentElement))
        .slice(0, 5)
        .map(
          (e) =>
            `${e.tagName} ${e.getAttribute('data-testid') ?? ''} ${e.textContent?.slice(0, 40)}`,
        );
    });
    expect(wide).toEqual([]);
    expect(scroll).toBeLessThanOrEqual(client);
    const box = await page.getByTestId('player-video').boundingBox();
    expect(box!.width).toBeGreaterThan(390 - 2 * 16 - 2 * 14);
  });
});
