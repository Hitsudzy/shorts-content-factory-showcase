// CC-0085: шапка и полоса табов — активный таб (вид, aria-current, в видимой области на
// телефоне), отступ счётчика от подписи, знак Example ведёт на главную.
import type { Page } from '@playwright/test';

import { expect, test } from './fixtures';

const tabsNav = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });
const tab = (page: Page, name: string) => tabsNav(page).getByRole('link', { name, exact: true });
const current = (page: Page) => tabsNav(page).locator('[aria-current="page"]');
const logo = (page: Page) => page.getByRole('link', { name: 'На главную' });

/** Цвет и толщина подчёркивания, насыщенность подписи — и значение `--primary-text` темы. */
const look = (page: Page, name: string) =>
  tab(page, name).evaluate((el) => {
    const s = getComputedStyle(el);
    const probe = document.createElement('i');
    probe.style.color = 'var(--primary-text)';
    document.body.append(probe);
    const accent = getComputedStyle(probe).color;
    probe.remove();
    return {
      line: s.borderBottomColor,
      width: s.borderBottomWidth,
      weight: s.fontWeight,
      color: s.color,
      accent,
    };
  });

const PATHS: [string, string][] = [
  ['/', 'Главная'],
  ['/channels/example-film', 'Каналы'],
  ['/channels/new', 'Каналы'],
  ['/questions?view=requests', 'Вопросы'],
  ['/videos?batch=example-film%2F2026-10-09T0215Z', 'Ролики'],
  ['/tokens', 'Токены'],
];

test.describe('шапка: активный таб и знак', () => {
  for (const [path, name] of PATHS) {
    test(`${path} → активен «${name}»`, async ({ page }) => {
      await page.goto(path);
      await expect(current(page)).toHaveCount(1);
      await expect(tab(page, name)).toHaveAttribute('aria-current', 'page');
      await expect(tab(page, name)).toBeInViewport();
    });
  }

  for (const theme of ['dark', 'light'] as const) {
    test(`вид активного таба — подчёркивание акцентом и жирная подпись (${theme})`, async ({
      page,
    }) => {
      await page.goto('/batches');
      if (theme === 'light') await page.getByRole('button', { name: 'Светлая тема' }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      const on = await look(page, 'Батчи');
      const off = await look(page, 'Каналы');
      expect(on.line).toBe(on.accent);
      expect(on.width).toBe('2px');
      expect(Number(on.weight)).toBeGreaterThanOrEqual(600);
      expect(off.line).toBe('rgba(0, 0, 0, 0)');
      expect(Number(off.weight)).toBeLessThan(600);
      expect(on.color).not.toBe(off.color);
    });
  }

  for (const theme of ['dark', 'light'] as const) {
    test(`ховер неактивного таба: подпись и намёк на линию, не как активный (${theme})`, async ({
      page,
    }) => {
      await page.goto('/batches');
      if (theme === 'light') await page.getByRole('button', { name: 'Светлая тема' }).click();
      await expect(page.locator('html')).toHaveAttribute('data-theme', theme);
      await page.mouse.move(0, 0);
      const before = await look(page, 'Каналы');
      const active = await look(page, 'Батчи');
      await tab(page, 'Каналы').hover();
      // Цвет меняется плавно (transition-colors) — ждём конечного.
      await expect.poll(async () => (await look(page, 'Каналы')).color).not.toBe(before.color);
      await expect
        .poll(async () => (await look(page, 'Каналы')).color)
        .toBe(active.color /* --foreground, как у активного */);
      const hovered = await look(page, 'Каналы');
      expect(hovered.line).not.toBe('rgba(0, 0, 0, 0)');
      expect(hovered.line).not.toBe(active.line);
      expect(Number(hovered.weight)).toBeLessThan(600);
      await expect(tab(page, 'Каналы')).not.toHaveAttribute('aria-current');
      await expect(current(page)).toHaveCount(1);
    });
  }

  test('ховер табов и знака — только там, где есть мышь (на касании не залипает)', async ({
    page,
  }) => {
    await page.goto('/');
    await expect(tabsNav(page)).toBeVisible();
    // Правила `:hover` для таба и знака лежат внутри `@media (hover: hover)`.
    const media = await page.evaluate(
      (CLASSES) => {
        const found: string[] = [];
        const walk = (rules: CSSRuleList, cond: string) => {
          for (const r of rules) {
            if (r instanceof CSSMediaRule) walk(r.cssRules, `${cond} ${r.conditionText}`);
            else if ('cssRules' in r && (r as CSSGroupingRule).cssRules)
              walk((r as CSSGroupingRule).cssRules, cond);
            if (!(r instanceof CSSStyleRule)) continue;
            const sel = r.selectorText.replaceAll('\\', '');
            if (CLASSES.some((c) => sel.includes(`.hover:${c}:hover`)))
              found.push(cond.trim() || 'none');
          }
        };
        for (const sheet of document.styleSheets) walk(sheet.cssRules, '');
        return found;
      },
      ['text-foreground', 'border-muted-foreground/50', 'opacity-80'],
    );
    expect(media.length).toBeGreaterThanOrEqual(3);
    for (const c of media) expect(c).toContain('hover: hover');
  });

  test('счётчик «Вопросы» отстоит от подписи на gap', async ({ page }) => {
    await page.goto('/');
    const badge = tab(page, 'Вопросы').locator('[data-slot="count"]');
    await expect(badge).toBeVisible();
    const gap = await tab(page, 'Вопросы').evaluate((el) => {
      const text = el.firstChild!;
      const range = document.createRange();
      range.selectNodeContents(text);
      const label = range.getBoundingClientRect();
      const count = el.querySelector('[data-slot="count"]')!.getBoundingClientRect();
      return count.left - label.right;
    });
    expect(gap).toBeGreaterThanOrEqual(5.5);
    expect(gap).toBeLessThanOrEqual(6.5);
  });

  test('знак Example ведёт на главную из любого раздела', async ({ page }) => {
    await page.goto('/channels/example-film');
    await expect(logo(page)).toHaveAttribute('href', '/');
    await logo(page).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(page.getByTestId('factory-card')).toBeVisible();
    await expect(tab(page, 'Главная')).toHaveAttribute('aria-current', 'page');
    await expect(current(page)).toHaveCount(1);
  });

  test('знак с клавиатуры — кольцо фокуса', async ({ page }) => {
    await page.goto('/batches');
    await expect(tab(page, 'Батчи')).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(logo(page)).toBeFocused();
    const outline = await logo(page).evaluate((el) => getComputedStyle(el).outlineStyle);
    expect(outline).toBe('solid');
  });
});

test.describe('шапка на телефоне', () => {
  test.use({ viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true });

  for (const [path, name] of [
    ['/tokens', 'Токены'],
    ['/maintenance', 'Обслуживание'],
    ['/dev/CC-0124', 'Разработка'],
    ['/questions?view=requests', 'Вопросы'],
  ] as const) {
    test(`${path}: активный «${name}» прокручен в видимую часть полосы`, async ({ page }) => {
      await page.goto(path);
      await expect(tab(page, name)).toHaveAttribute('aria-current', 'page');
      await expect(tab(page, name)).toBeInViewport({ ratio: 1 });
      // Страница вбок не уехала — прокручена только полоса табов.
      expect(await page.evaluate(() => window.scrollX)).toBe(0);
    });
  }

  test('переход по ссылке внутри центра докручивает полосу до нового таба', async ({ page }) => {
    await page.goto('/maintenance');
    await expect(tab(page, 'Обслуживание')).toBeInViewport({ ratio: 1 });
    await expect(tab(page, 'Главная')).not.toBeInViewport();
    await logo(page).click();
    await expect(page).toHaveURL(/\/$/);
    await expect(tab(page, 'Главная')).toHaveAttribute('aria-current', 'page');
    await expect(tab(page, 'Главная')).toBeInViewport({ ratio: 1 });

    await page.getByRole('link', { name: 'Уведомления и напоминания' }).first().click();
    await expect(page).toHaveURL(/\/notifications$/);
    await expect(tab(page, 'Уведомления')).toBeInViewport({ ratio: 1 });
  });
});
