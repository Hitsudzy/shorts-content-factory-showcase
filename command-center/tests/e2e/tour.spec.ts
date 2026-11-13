// CC-0072: тур «Обучение» на подставном API — проходит все шаги на компьютере и на телефоне,
// сам ходит по экранам, подсказка не вылезает за экран и не закрывает подсветку, Esc и
// «Пропустить» закрывают, прогресс помнится. Тур только показывает: за весь тур — ни одного
// запроса, кроме GET.
import type { Page } from '@playwright/test';

import { fixtures, writesModes } from '../../src/mocks/fixtures';
import { STEPS, sectionStart, stepLabel } from '../../src/tour/steps';
import { expect, test } from './fixtures';

const SIZES = {
  desktop: { width: 1280, height: 800 },
  phone: { width: 390, height: 844 },
} as const;

/** Шаги, цели которых на подставных данных нет — они объясняют словами. */
const MISSING_ON_MOCKS = new Set(['read-only']);

/** Не-GET запросы страницы (к API и куда угодно). */
function watchWrites(page: Page): string[] {
  const writes: string[] = [];
  page.on('request', (r) => {
    if (r.method() !== 'GET') writes.push(`${r.method()} ${r.url()}`);
  });
  return writes;
}

type Rect = { top: number; left: number; bottom: number; right: number };
type Geometry = {
  view: { width: number; height: number };
  card: Rect;
  spot: Rect | null;
  target: Rect | null;
  /** Низ липкой шапки (0 — цель в самой шапке). */
  safeTop: number;
};

const geometry = (page: Page, target?: string) =>
  page.evaluate((name): Geometry => {
    const r = (el: Element | null | undefined) => {
      if (!el) return null;
      const b = el.getBoundingClientRect();
      return { top: b.top, left: b.left, bottom: b.bottom, right: b.right };
    };
    const el = name
      ? [...document.querySelectorAll(`[data-tour="${name}"]`)].find(
          (e) => e.getBoundingClientRect().height > 0,
        )
      : undefined;
    const header = document.querySelector('header')!.getBoundingClientRect().bottom;
    return {
      view: { width: document.documentElement.clientWidth, height: window.innerHeight },
      card: r(document.querySelector('[data-testid="tour-card"]'))!,
      spot: r(document.querySelector('[data-testid="tour-spot"]')),
      target: r(el),
      safeTop: el?.closest('header') ? 0 : Math.max(0, header),
    };
  }, target);

const cross = (a: Rect, b: Rect) =>
  Math.min(a.right, b.right) - Math.max(a.left, b.left) > 1 &&
  Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top) > 1;

/**
 * Подсказка целиком в окне и не закрывает ни подсветку, ни верх цели. Сравнивать только с
 * подсветкой мало: она обрезается по подсказке, и узкая полоска над подсказкой «не
 * пересекается», даже когда подсказка легла на заголовок цели (так было с карточкой Studio на
 * телефоне). Поэтому ещё — верхняя полоса самой цели (до 100px её видимой части).
 */
async function expectClear(page: Page, id: string, target: string | undefined, found: boolean) {
  const g = await geometry(page, found ? target : undefined);
  expect(g.card.top, id).toBeGreaterThanOrEqual(0);
  expect(g.card.left, id).toBeGreaterThanOrEqual(0);
  expect(g.card.bottom, id).toBeLessThanOrEqual(g.view.height + 0.5);
  expect(g.card.right, id).toBeLessThanOrEqual(g.view.width + 0.5);
  if (!found) return;
  expect(g.spot, `${id}: подсветка`).not.toBeNull();
  expect(cross(g.spot!, g.card), `${id}: подсказка закрывает подсветку`).toBe(false);
  expect(g.spot!.bottom - g.spot!.top, id).toBeGreaterThan(8);
  const t = g.target!;
  const top = Math.max(t.top, g.safeTop);
  const bottom = Math.min(t.bottom, g.view.height);
  expect(bottom - top, `${id}: цель на экране`).toBeGreaterThan(4);
  const head = { ...t, top, bottom: Math.min(bottom, top + 100) };
  expect(cross(head, g.card), `${id}: подсказка закрывает верх цели`).toBe(false);
  expect(g.spot!.top, `${id}: подсветка начинается с верха цели`).toBeLessThanOrEqual(top + 1);
}

for (const [device, viewport] of Object.entries(SIZES)) {
  test(`тур проходит все шаги: ${device}`, async ({ page }) => {
    test.setTimeout(240_000);
    const writes = watchWrites(page);
    await page.setViewportSize(viewport);
    await page.goto('/');
    await page.getByTestId('tour-invite-start').click();
    const card = page.getByTestId('tour-card');
    const seen: string[] = [];

    for (const [i, step] of STEPS.entries()) {
      await expect(card).toHaveAttribute('data-step', step.id);
      await expect(page.getByTestId('tour-count')).toHaveText(stepLabel(i));
      await expect(card).toBeFocused();
      await expect(card).not.toHaveAttribute('data-target', 'pending', { timeout: 15_000 });
      const status = await card.getAttribute('data-target');
      seen.push(`${step.id}:${status}`);
      if (!step.target) expect(status, step.id).toBe('none');
      else if (MISSING_ON_MOCKS.has(step.id)) expect(status, step.id).toBe('missing');
      else expect(status, step.id).toBe('found');
      if (status === 'missing') await expect(page.getByTestId('tour-missing')).toBeVisible();

      // Экран шага: тур сам перешёл куда нужно.
      const path = new URL(page.url()).pathname;
      if (step.deeper) expect(path.startsWith(step.route), step.id).toBe(true);
      else expect(path, step.id).toBe(step.route);

      // Подсказка целиком на экране и не закрывает подсветку и верх цели — когда раскладка
      // встала (подсветка едет за целью 150 мс, тур ещё докручивает, пока догружаются данные).
      await expect(() => expectClear(page, step.id, step.target, status === 'found')).toPass({
        timeout: 5000,
      });
      await page.getByTestId('tour-next').click();
    }

    await expect(page.getByTestId('tour')).toHaveCount(0);
    const saved = await page.evaluate(() => JSON.parse(localStorage.getItem('cc-tour') ?? '{}'));
    expect(saved.finished).toBe(true);
    expect(saved.seen).toHaveLength(STEPS.length);
    console.log(`${device}: ${seen.join(' ')}`);
    expect(writes, 'тур не пишет').toEqual([]);
  });
}

test('телефон: подсказка не ложится на карточку Studio', async ({ page }) => {
  await page.setViewportSize(SIZES.phone);
  await page.goto('/');
  await page.getByTestId('tour-open').click();
  await page.locator('[data-testid="tour-section"][data-section="publishing"]').click();
  await page.getByTestId('tour-next').click();
  const card = page.getByTestId('tour-card');
  await expect(card).toHaveAttribute('data-step', 'studio');
  await expect(card).toHaveAttribute('data-target', 'found');
  // Данные выше карточки догружаются и сдвигают её — проверяем и сразу, и когда всё встало.
  for (const wait of [200, 1500]) {
    await page.waitForTimeout(wait);
    await expectClear(page, 'studio', 'studio', true);
    const g = await geometry(page, 'studio');
    expect(cross(g.spot!, g.card)).toBe(false);
    // Подпись «Для Studio» — над подсказкой, в подсветке.
    const eyebrow = await page
      .getByTestId('studio-card')
      .getByText('Для Studio', { exact: true })
      .boundingBox();
    expect(eyebrow!.y + eyebrow!.height).toBeLessThanOrEqual(g.card.top);
    expect(eyebrow!.y).toBeGreaterThanOrEqual(g.spot!.top);
  }
  // Рамка подсветки заметная: толстая, акцентом, с тёмной обводкой для контраста.
  const ring = await page.getByTestId('tour-spot').evaluate((el) => {
    const st = getComputedStyle(el);
    return { width: st.borderTopWidth, shadow: st.boxShadow };
  });
  expect(ring.width).toBe('3px');
  expect(ring.shadow).toContain('inset');
});

test('Esc закрывает тур, оглавление продолжает с того же шага', async ({ page }) => {
  const writes = watchWrites(page);
  await page.goto('/');
  await page.getByTestId('tour-invite-start').click();
  await page.keyboard.press('ArrowRight');
  await page.keyboard.press('ArrowRight');
  await expect(page.getByTestId('tour-card')).toHaveAttribute('data-step', STEPS[2]!.id);
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('tour')).toHaveCount(0);
  await expect(page.getByTestId('tour-invite')).toHaveCount(0);

  await page.getByTestId('tour-open').click();
  const menu = page.getByTestId('tour-contents');
  await expect(menu).toBeFocused();
  // Оглавление не налезает на шапку (плашки «Фабрика на связи» и т. п.).
  const header = (await page.locator('header').boundingBox())!;
  const box = (await menu.boundingBox())!;
  expect(box.y).toBeGreaterThanOrEqual(header.y + header.height + 8);
  expect(box.y + box.height).toBeLessThanOrEqual(800);
  await expect(menu.getByTestId('tour-resume')).toContainText(`шаг ${stepLabel(2)}`);
  await expect(menu.getByTestId('tour-practice')).toContainText('Начать тренировку');
  await page.keyboard.press('Escape');
  await expect(page.getByTestId('tour')).toHaveCount(0);
  await expect(page.getByTestId('tour-open')).toBeFocused();
  expect(writes).toEqual([]);
});

test('«Пропустить» закрывает; раздел из оглавления; прогресс переживает перезагрузку', async ({
  page,
}) => {
  const writes = watchWrites(page);
  await page.goto('/');
  await page.getByTestId('tour-open').click();
  await page.locator('[data-testid="tour-section"][data-section="publishing"]').click();
  const card = page.getByTestId('tour-card');
  await expect(card).toHaveAttribute('data-step', STEPS[sectionStart('publishing')]!.id);
  await expect(page).toHaveURL(/\/publishing$/);
  await expect(card).toHaveAttribute('data-target', 'found');
  // Под туром ничего не нажать: клик по странице ловит слой тура.
  await page.mouse.click(5, 400);
  await expect(card).toBeVisible();
  await page.getByTestId('tour-next').click();
  await page.getByTestId('tour-skip').click();
  await expect(page.getByTestId('tour')).toHaveCount(0);

  await page.reload();
  await page.getByTestId('tour-open').click();
  const section = page.locator('[data-testid="tour-section"][data-section="publishing"]');
  await expect(section.getByTestId('tour-section-state')).toHaveText(
    `2 из ${STEPS.filter((s) => s.section === 'publishing').length}`,
  );
  await page.getByTestId('tour-restart').click();
  await expect(card).toHaveAttribute('data-step', STEPS[0]!.id);
  await expect(page).toHaveURL(/\/$/);
  expect(writes).toEqual([]);
});

test('«только смотреть»: шаг подсвечивает плашку', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  await page.goto('/');
  await page.getByTestId('read-only-banner').waitFor();
  await page.getByTestId('tour-open').click();
  await page.locator('[data-testid="tour-section"][data-section="basics"]').click();
  const card = page.getByTestId('tour-card');
  await expect(card).toHaveAttribute('data-step', 'read-only');
  await expect(card).toHaveAttribute('data-target', 'found');
  await expect(page.getByTestId('tour-spot')).toBeVisible();
  // Плашка — внизу липкой шапки: рамка подсветки не выходит за нижний край шапки.
  await expect(async () => {
    const header = (await page.locator('header').boundingBox())!;
    const spot = (await page.getByTestId('tour-spot').boundingBox())!;
    expect(spot.y).toBeGreaterThanOrEqual(-0.5);
    expect(spot.y + spot.height).toBeLessThanOrEqual(header.y + header.height + 0.5);
  }).toPass({ timeout: 5000 });
});

test('телефон: плашка «только смотреть» не обрезает причину многоточием', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  await page.setViewportSize(SIZES.phone);
  await page.goto('/');
  const line = page.getByTestId('read-only-banner').locator('p').first();
  await expect(line).toContainText('это рабочая копия разработки, а не рабочая фабрика');
  const fit = await line.evaluate((el) => ({
    clipped: el.scrollWidth > el.clientWidth + 1,
    ellipsis: getComputedStyle(el).textOverflow === 'ellipsis',
    height: el.getBoundingClientRect().height,
    font: parseFloat(getComputedStyle(el).fontSize),
  }));
  expect(fit.clipped).toBe(false);
  expect(fit.ellipsis).toBe(false);
  // Не влезла в строку — перенеслась на вторую.
  expect(fit.height).toBeGreaterThanOrEqual(2 * fit.font);
});

for (const [device, viewport] of Object.entries(SIZES)) {
  test(`оглавление: «Закрыть» всегда на экране, листается только список: ${device}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport);
    await page.goto('/');
    await page.getByTestId('tour-open').click();
    const menu = page.getByTestId('tour-contents');
    const close = menu.getByTestId('tour-contents-close');
    await expect(close).toBeVisible();
    await expect(async () => {
      const m = (await menu.boundingBox())!;
      const c = (await close.boundingBox())!;
      // Кнопка целиком в окне …
      expect(c.y).toBeGreaterThanOrEqual(0);
      expect(c.x).toBeGreaterThanOrEqual(0);
      expect(c.y + c.height).toBeLessThanOrEqual(viewport.height + 0.5);
      expect(c.x + c.width).toBeLessThanOrEqual(viewport.width + 0.5);
      // … и целиком внутри окна оглавления (не срезана его краем).
      expect(c.y).toBeGreaterThanOrEqual(m.y);
      expect(c.y + c.height).toBeLessThanOrEqual(m.y + m.height + 0.5);
      expect(c.x).toBeGreaterThanOrEqual(m.x);
      expect(c.x + c.width).toBeLessThanOrEqual(m.x + m.width + 0.5);
      // Само окно — в экране.
      expect(m.y + m.height).toBeLessThanOrEqual(viewport.height + 0.5);
    }).toPass({ timeout: 5000 });
    // Листается список, а не всё окно: кнопка остаётся на месте после прокрутки списка.
    const before = (await close.boundingBox())!.y;
    await menu.getByTestId('tour-contents-list').evaluate((el) => el.scrollTo(0, el.scrollHeight));
    expect((await close.boundingBox())!.y).toBeCloseTo(before, 0);
    await expect(menu.getByTestId('tour-practice')).toBeInViewport();
    await close.click();
    await expect(page.getByTestId('tour')).toHaveCount(0);
  });
}

test('без хранилища тур работает', async ({ page }) => {
  await page.addInitScript(() => {
    const deny = () => {
      throw new Error('denied');
    };
    Storage.prototype.getItem = deny;
    Storage.prototype.setItem = deny;
  });
  await page.goto('/');
  await page.getByTestId('tour-invite-start').click();
  await page.getByTestId('tour-next').click();
  await expect(page.getByTestId('tour-card')).toHaveAttribute('data-step', STEPS[1]!.id);
});
