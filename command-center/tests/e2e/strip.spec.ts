// Кинолента батча (CC-0126): законченное видно с первого взгляда — готово ✓ с длительностью,
// идёт ▶, ждёт ○, упала ✕, пропущена – (пунктир); запасные шаги добора «не понадобились»;
// батч вернулся за добором — «добор · идёт …»; плёнка между кадрами по прогрессу; свет и тьма,
// телефон, «меньше движения». Подставные батчи — src/mocks/batches.ts.
import type { Locator, Page } from '@playwright/test';

import {
  FAILED_AT_START_STAGES,
  JUDGE_ROUND_DONE_STAGES,
  JUDGE_ROUND_GOING_STAGES,
  JUDGE_ROUND_SKIPPED_STAGES,
  ORDER,
  RUNNING,
} from '../../src/mocks/batches';
import { isConditional } from '../../src/pages/batches/stages';
import { expect, noSideScroll, openTip, test } from './fixtures';

const strip = (page: Page) =>
  page
    .locator(`[data-testid="open-batch"][data-batch="${RUNNING}"]`)
    .getByTestId('film-strip')
    .locator('li');

/** Значок кадра — `::after` номера (CSS по `data-state`). */
const glyph = (li: Locator) =>
  li.locator('.film-num').evaluate((el) => getComputedStyle(el, '::after').content);

/** До `cur` — готово (условные из `ran` — тоже, остальные условные — `extra`), дальше — ждёт. */
const upTo = (cur: string, ran: string[] = [], extra = 'skipped') =>
  ORDER.map((id, i) => {
    const c = ORDER.indexOf(cur as (typeof ORDER)[number]);
    const before = isConditional(id) && !ran.includes(id) ? extra : 'done';
    return { id, status: i < c ? before : i === c ? 'running' : 'pending' };
  });

const SUPPLEMENT = ['thin-pool-supplement', 'plan-check-after-supplement'];

test('пять состояний: значок, подпись и рамка у каждого; готово — с длительностью', async ({
  page,
}) => {
  await page.goto('/batches');
  const li = strip(page);
  await expect(li.nth(0)).toHaveAttribute('data-state', 'done');
  // Тренды — шесть стадий по 10 мин (пролёты `…/stages` мока).
  await expect(li.nth(0).getByTestId('frame-small')).toHaveText('готово · 1 ч');
  await expect(li.nth(1).getByTestId('frame-small')).toHaveText('готово · 10 мин');
  expect(await glyph(li.nth(0))).toContain('✓');
  expect(await glyph(li.nth(5))).toContain('▶');
  expect(await glyph(li.nth(6))).toContain('○');
  expect(await glyph(li.nth(3))).toContain('–');
  await expect(li.nth(3)).toContainText('не понадобился');
  // Готовое — сплошная рамка «ок», пропущенное — пунктир: различимы и без цвета.
  const style = (n: number) =>
    li.nth(n).evaluate((el) => {
      const s = getComputedStyle(el);
      return { border: s.borderTopStyle, color: s.borderTopColor, bg: s.backgroundColor };
    });
  expect(await style(0)).toEqual({
    border: 'solid',
    color: 'rgb(46, 154, 102)',
    bg: 'rgb(11, 26, 18)',
  });
  expect((await style(3)).border).toBe('dashed');
  expect((await style(5)).color).toBe('rgb(255, 226, 61)');
  // Плёнка: до идущего — пройдена (толще), дальше — впереди.
  const links = await li.evaluateAll((els) => els.map((el) => el.getAttribute('data-link')));
  expect(links).toEqual(['passed', 'passed', 'passed', 'passed', 'passed', 'ahead', 'ahead', null]);
  const thick = (n: number) =>
    li.nth(n).evaluate((el) => parseFloat(getComputedStyle(el, '::after').height));
  expect(await thick(0)).toBe(3);
  expect(await thick(5)).toBe(1);
});

test('упала — ✕ и «ошибка», не дошла — «не дошёл» без ✓', async ({ page, batches }) => {
  batches.patch(RUNNING, {
    status: 'failed',
    stages: FAILED_AT_START_STAGES,
    stage: null,
    next: null,
  });
  await page.goto('/batches');
  const li = strip(page);
  await expect(li.nth(0)).toHaveAttribute('data-state', 'bad');
  await expect(li.nth(0).getByTestId('frame-small')).toHaveText('ошибка');
  expect(await glyph(li.nth(0))).toContain('✕');
  await expect(li.nth(1)).toHaveAttribute('data-state', 'unreached');
  expect(await glyph(li.nth(1))).not.toContain('✓');
  await expect(li.locator('[data-state="done"]')).toHaveCount(0);
  // Плёнка не пройдена нигде: из упавшего, в недошедшие и в упавший последний (ревью экранов).
  await expect(li.locator('[data-link="passed"]')).toHaveCount(0);
  // Недошедший этап не запускался — итогов у него нет.
  await expect(li.locator('[data-state="unreached"] [data-testid="frame-summary"]')).toHaveCount(0);
});

test('пропущенный этап — «не в этом прогоне», пунктиром', async ({ page, batches }) => {
  batches.patch(RUNNING, {
    stages: ['batch-start', 'video-editor', 'frame-judge', 'batch-done'].map((id) => ({
      id,
      status: id === 'batch-start' ? 'done' : id === 'video-editor' ? 'running' : 'pending',
    })),
  });
  await page.goto('/batches');
  const li = strip(page);
  await expect(li.nth(1)).toHaveAttribute('data-state', 'skip');
  await expect(li.nth(1).getByTestId('frame-small')).toHaveText('не в этом прогоне');
  expect(await glyph(li.nth(1))).toContain('–');
});

test('добор прошёл, запасные не понадобились — «готово», а не «2 из 8 шагов»', async ({
  page,
  batches,
}) => {
  // Как Reel 2026-10-13T1411Z: добор тонкого пула прошёл, резерв так и остался pending.
  batches.patch(RUNNING, { stages: upTo('video-editor', SUPPLEMENT, 'pending') });
  await page.goto('/batches');
  const li = strip(page);
  await expect(li.nth(3)).toHaveAttribute('data-state', 'done');
  await expect(li.nth(3).getByTestId('frame-small')).toHaveText('готово');
  await expect(li.nth(3).getByTestId('frame-spare')).toHaveText('6 запасных шагов не понадобились');
  await expect(li.nth(3)).not.toContainText('шагов ·');
  await expect(li.nth(3)).not.toContainText('из 8');
});

test('идёт добор — «добор · идёт …», подсказка про добор', async ({ page, batches }) => {
  batches.patch(RUNNING, {
    stages: upTo('thin-pool-supplement'),
    stage: 'thin-pool-supplement',
    next: 'plan-check-after-supplement',
  });
  await page.goto('/batches');
  const li = strip(page);
  await expect(li.nth(3)).toHaveAttribute('data-state', 'now');
  await expect(li.nth(3)).toHaveAttribute('data-returned', 'true');
  const small = li.nth(3).getByTestId('frame-small');
  await expect(small).toHaveText('добор · идёт 20 мин из 1 ч 30 мин');
  await openTip(page, small, 'только когда основного не хватило');
  await expect(li.nth(2)).toHaveAttribute('data-state', 'done');
});

test.describe('добор после отказа судьи кадра (CC-0150, фабрика 2.16)', () => {
  const titles = (page: Page) => strip(page).locator('.film-title');
  const NINE = [
    'Тренды',
    'Футаж',
    'Исследование',
    'Добор',
    'Проверка сценариев',
    'Монтаж',
    'Проверка кадров',
    'Добор после судьи',
    'На приёмку',
  ];

  test('раунд пропущен — свой кадр «не понадобился» между проверкой кадров и приёмкой', async ({
    page,
    batches,
  }) => {
    batches.patch(RUNNING, {
      stages: JUDGE_ROUND_SKIPPED_STAGES,
      stage: 'batch-done',
      next: 'monitors',
    });
    await page.goto('/batches');
    const li = strip(page);
    await expect(li).toHaveCount(9);
    await expect(titles(page)).toHaveText(NINE);
    await expect(li.nth(7)).toHaveAttribute('data-state', 'unneeded');
    await expect(li.nth(7)).toHaveAttribute('data-kind', 'extra');
    await expect(li.nth(7).getByTestId('frame-small')).toHaveText('не понадобился');
    await expect(li.nth(6)).toHaveAttribute('data-state', 'done');
    await expect(li.nth(8)).toHaveAttribute('data-state', 'now');
  });

  test('раунд идёт — «добор · идёт …», подсказка про отказ судьи кадра', async ({
    page,
    batches,
  }) => {
    batches.patch(RUNNING, {
      stages: JUDGE_ROUND_GOING_STAGES,
      stage: 'video-editor-judge',
      next: 'frame-judge-judge',
    });
    await page.goto('/batches');
    const li = strip(page);
    await expect(li).toHaveCount(9);
    await expect(li.nth(7)).toHaveAttribute('data-state', 'now');
    await expect(li.nth(7)).toHaveAttribute('data-returned', 'true');
    const small = li.nth(7).getByTestId('frame-small');
    await expect(small).toHaveText('добор · идёт 20 мин из 1 ч 30 мин');
    await expect(li.nth(7).getByTestId('frame-first')).toHaveCount(0);
    await openTip(page, small, 'только когда судья кадра отказал роликам');
    // Строка под лентой — заголовок текущего кадра, а не вид кадра «Добор».
    await expect(
      page
        .locator(`[data-testid="open-batch"][data-batch="${RUNNING}"]`)
        .getByTestId('batch-stage'),
    ).toContainText('Сейчас: Добор после судьи · 20 мин из 1 ч 30 мин');
    await expect(li.nth(6)).toHaveAttribute('data-state', 'done');
  });

  test('раунд прошёл — «готово», два запасных шага не понадобились', async ({ page, batches }) => {
    batches.patch(RUNNING, {
      stages: JUDGE_ROUND_DONE_STAGES,
      stage: 'batch-done',
      next: 'monitors',
    });
    await page.goto('/batches');
    const li = strip(page);
    await expect(titles(page)).toHaveText(NINE);
    await expect(li.nth(7)).toHaveAttribute('data-state', 'done');
    await expect(li.nth(7).getByTestId('frame-small')).toHaveText('готово');
    await expect(li.nth(7).getByTestId('frame-spare')).toHaveText(
      '2 запасных шага не понадобились',
    );
  });
});

test('светлая тема: лента тёмная, готовый кадр — того же вида', async ({ page }) => {
  await page.addInitScript(() => localStorage.setItem('cc-theme', 'light'));
  await page.goto('/batches');
  const li = strip(page);
  await expect(li.nth(0)).toHaveAttribute('data-state', 'done');
  expect(await li.nth(0).evaluate((el) => getComputedStyle(el).backgroundColor)).toBe(
    'rgb(11, 26, 18)',
  );
  expect(
    await li
      .nth(0)
      .locator('.film-title')
      .evaluate((el) => getComputedStyle(el).color),
  ).toBe('rgb(230, 230, 238)');
});

test.describe('телефон и «меньше движения»', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('кадры столбиком, «готово» видно, плёнка вниз, значок «идёт» не мигает', async ({
    page,
  }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto('/batches');
    const li = strip(page);
    const [a, b] = await Promise.all([li.nth(0).boundingBox(), li.nth(1).boundingBox()]);
    expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1);
    await expect(li.nth(0).getByTestId('frame-small')).toBeVisible();
    await expect(li.nth(6).getByTestId('frame-small')).toBeHidden();
    const link = await li.nth(0).evaluate((el) => ({
      w: parseFloat(getComputedStyle(el, '::after').width),
      h: parseFloat(getComputedStyle(el, '::after').height),
    }));
    expect(link.w).toBe(3);
    expect(link.h).toBeGreaterThan(link.w);
    expect(
      await li
        .nth(5)
        .locator('.film-num')
        .evaluate((el) => getComputedStyle(el, '::after').animationName),
    ).toBe('none');
    await noSideScroll(page);
  });
});
