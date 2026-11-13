// CC-0025: экран «Мемы» на подставном столе (src/mocks/memes.ts): таб → банк Tech (35 на разборе)
// → мем в просмотре → отметки кнопками и клавишами → «Сохранить отметки» (единственная запись
// до «Применить», с `base`) → «Применить разбор»: план словами → «да». Чужое изменение черновика —
// «изменились в другом месте» без перезаписи; только смотреть — листать можно, писать нельзя;
// телефон 390 без прокрутки вбок; тренировка показывает экран на демо-данных.
import type { Page } from '@playwright/test';

import { fixtures, writesModes } from '../../src/mocks/fixtures';
import { TECH_BANK } from '../../src/mocks/memesData';
import { expect, noSideScroll, onlyHttp, openTip, test } from './fixtures';

const writes = (hits: string[]) => hits.filter((h) => !h.startsWith('GET '));
const viewer = (page: Page) => page.getByTestId('meme-viewer');
const card = (page: Page, id: string) => page.locator(`[data-testid="meme"][data-id="${id}"]`);

test('таб → банк Tech: отметки кнопками и клавишами, сохранить с base, применить разбор', async ({
  page,
  apiHits,
  memes,
}) => {
  await page.goto('/');
  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Мемы', exact: true })
    .click();
  await expect(page).toHaveURL(/\/memes$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Мемы');
  const tech = page.locator('[data-testid="bank-option"][data-bank="memes-example-tech"]');
  await expect(tech).toHaveAttribute('aria-pressed', 'true');
  await expect(tech).toContainText('ждут разбора: 35');
  await expect(tech).toContainText('Мемы в роликах выключены — включает фабрика после разбора');
  await expect(page.getByTestId('meme')).toHaveCount(35);
  await expect(page.getByTestId('notice-stale')).toContainText('уже нет: 1');
  await expect(page.getByTestId('notice-bands')).toContainText('сверху белая полоса, 22% высоты');

  // Картинки карточек — с подставного API, GIF стоит на первом кадре и играет при наведении.
  const gif = card(page, 'this-is-fine');
  await expect(gif.locator('canvas')).toBeVisible();
  await gif.hover();
  await expect(gif.locator('img')).toBeVisible();
  await expect(gif.locator('canvas')).toBeHidden();

  await card(page, 'bell-curve').click();
  await expect(viewer(page)).toHaveAttribute('data-id', 'bell-curve');
  await expect(page).toHaveURL(/m=bell-curve/);
  await expect(viewer(page).getByTestId('meme-source')).toHaveAttribute('target', '_blank');
  await openTip(page, page.getByTestId('keys-legend'), 'K — оставить');

  await viewer(page).getByTestId('mark-keep').click();
  await expect(card(page, 'bell-curve')).toHaveAttribute('data-state', 'keep');
  await page.locator('body').click({ position: { x: 5, y: 300 } });
  await page.keyboard.press('ArrowRight');
  await expect(viewer(page)).toHaveAttribute('data-id', 'bernie-once-again-asking');
  await page.keyboard.press('c');
  await expect(viewer(page).getByTestId('mark-cut')).toHaveAttribute('aria-checked', 'true');
  await page.keyboard.press('d');
  await expect(viewer(page)).toHaveAttribute('data-id', 'buff-doge-vs-cheems');
  await page.keyboard.press('k');
  await expect(viewer(page)).toHaveAttribute('data-id', 'change-my-mind');
  await expect(page.getByTestId('desk-unsaved')).toContainText('Не сохранено: 3 отметки');
  await viewer(page).getByTestId('mark-note').fill('к месту про «опять»');
  await expect(page.getByTestId('desk-unsaved')).toContainText('Не сохранено: 4 отметки');
  expect(writes(apiHits), 'до «Сохранить» ничего не пишется').toEqual([]);

  const base0 = memes.desk('example-tech').fingerprint;
  const put = page.waitForRequest((r) => r.method() === 'PUT');
  await page.getByTestId('desk-save').click();
  const body = (await put).postDataJSON() as { base: string; decisions: Record<string, unknown> };
  expect(body.base).toBe(base0);
  expect(Object.keys(body.decisions).sort()).toEqual([
    'always-has-been',
    'bell-curve',
    'bernie-once-again-asking',
    'buff-doge-vs-cheems',
    'change-my-mind',
  ]);
  await expect(page.getByTestId('desk-unsaved')).toHaveText('Все отметки сохранены');
  await expect(page.getByTestId('notice-stale')).toHaveCount(0);
  expect(writes(apiHits)).toEqual(['PUT /api/memes/example-tech/marks']);

  await page.getByTestId('apply-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('plan-accept')).toContainText('Войдут в библиотеку: 3 мема');
  await expect(dialog.getByTestId('plan-remove')).toContainText('Уберу из банка: 1 мем');
  await expect(dialog.getByTestId('plan-files')).toContainText('Удалю из банка 1 файл');
  await expect(dialog.getByTestId('apply-confirm')).toContainText(/Применить · \d/);
  expect(writes(apiHits)).toEqual([
    'PUT /api/memes/example-tech/marks',
    'POST /api/memes/example-tech/apply/plan',
  ]);
  await dialog.getByTestId('apply-confirm').click();
  await expect(page.getByTestId('apply-done')).toContainText('Вошли в библиотеку: 3 мема');
  await expect(page.getByTestId('meme')).toHaveCount(34);
  // Принятые остаются со своей отметкой в черновике; новых без решения — 31.
  await expect(page.locator('[data-testid="meme"][data-state="new"]')).toHaveCount(31);
  await expect(tech).toContainText('ждут разбора: 31');
});

test.describe('отказы фабрики', () => {
  test.use({ expectCleanConsole: false });

  test('черновик поменяли в другом месте: словами, без перезаписи; «загрузить заново»', async ({
    page,
    apiHits,
    memes,
    consoleErrors,
  }) => {
    await page.goto('/memes?channel=example-tech&m=roll-safe');
    await viewer(page).getByTestId('mark-drop').click();
    memes.editElsewhere(TECH_BANK, 'trade-offer', { v: 'keep' });
    await page.getByTestId('desk-save').click();
    const conflict = page.getByTestId('desk-conflict');
    await expect(conflict).toContainText('Отметки изменились в другом месте');
    await expect(conflict).toContainText('не сохранены, чтобы не затереть чужие');
    expect(memes.desk('example-tech').decisions['roll-safe']).toBeUndefined();
    await expect(page.getByTestId('desk-save')).toHaveAttribute('aria-disabled', 'true');
    await expect(page.getByTestId('apply-open')).toHaveAttribute('aria-disabled', 'true');
    await conflict.getByTestId('desk-reload').click();
    await expect(conflict).toHaveCount(0);
    await expect(card(page, 'trade-offer')).toHaveAttribute('data-state', 'keep');
    await expect(card(page, 'roll-safe')).toHaveAttribute('data-state', 'new');
    expect(writes(apiHits)).toEqual(['PUT /api/memes/example-tech/marks']);
    onlyHttp(consoleErrors, 409);
  });

  test('«да» после чужой правки: фабрика проверила заново, подтвердить ещё раз', async ({
    page,
    memes,
    consoleErrors,
  }) => {
    await page.goto('/memes?channel=example-film');
    await page.getByTestId('apply-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('plan-accept')).toContainText('Войдут в библиотеку: 1 мем');
    await expect(dialog.getByTestId('plan-remove')).toHaveCount(0);
    await expect(dialog.getByTestId('plan-held')).toContainText(
      'Останутся, хоть и отмечены «убрать»',
    );
    await dialog.getByTestId('apply-drop').getByRole('checkbox').check();
    await expect(dialog.getByTestId('plan-remove')).toContainText('Уберу из банка: 1 мем');
    memes.editElsewhere('memes', 'epic-handshake', { v: 'drop' });
    await dialog.getByTestId('apply-confirm').click();
    await expect(dialog.getByTestId('replanned')).toContainText(
      'С момента проверки что-то изменилось',
    );
    await expect(dialog.getByTestId('plan-remove')).toContainText('Уберу из банка: 2 мема');
    await dialog.getByTestId('apply-confirm').click();
    await expect(page.getByTestId('apply-done')).toContainText('убраны: 2 мема');
    onlyHttp(consoleErrors, 409);
  });
});

test('только смотреть: листать и искать можно, отметки и запись погашены', async ({
  page,
  apiHits,
}) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  await page.goto('/memes?channel=example-tech&m=bell-curve');
  await expect(page.getByTestId('desk-readonly')).toBeVisible();
  await expect(viewer(page).getByTestId('mark-keep')).toHaveAttribute('aria-disabled', 'true');
  await viewer(page).getByTestId('mark-keep').click({ force: true });
  await page.keyboard.press('k');
  await expect(card(page, 'bell-curve')).toHaveAttribute('data-state', 'new');
  await expect(page.getByTestId('desk-save')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByTestId('apply-open')).toHaveAttribute('aria-disabled', 'true');
  await page.getByTestId('meme-search').fill('pikachu');
  await expect(page.getByTestId('meme')).toHaveCount(1);
  await page.getByRole('heading', { level: 1 }).click();
  await page.keyboard.press('Escape');
  await expect(viewer(page)).toHaveCount(0);
  expect(writes(apiHits)).toEqual([]);
});

// CC-0143: «Целиком» (было «только целиком» на доске 8765) — обратное «С вырезкой»: GIF и мемы
// без «можно вырезать»; включён один из двух; без записей.
test('фильтр «Целиком»: мемы без вырезки, вместе с «С вырезкой» — весь банк', async ({
  page,
  apiHits,
}) => {
  await page.goto('/memes?channel=example-tech');
  await expect(page.getByTestId('meme')).toHaveCount(35);
  const cut = page.getByTestId('filter-cut');
  const whole = page.getByTestId('filter-whole');
  await expect(cut).toHaveText('С вырезкой · 3');
  await expect(whole).toHaveText('Целиком · 32');
  await openTip(page, whole, 'GIF — всегда целиком');
  await whole.click();
  await expect(whole).toHaveAttribute('aria-pressed', 'true');
  await expect(cut).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('meme')).toHaveCount(32);
  await expect(card(page, 'this-is-fine')).toBeVisible();
  await expect(card(page, 'drake-hotline-bling')).toHaveCount(0);
  await cut.click();
  await expect(whole).toHaveAttribute('aria-pressed', 'false');
  await expect(page.getByTestId('meme')).toHaveCount(3);
  await expect(card(page, 'drake-hotline-bling')).toBeVisible();
  expect(writes(apiHits)).toEqual([]);
});

// CC-0083: подсказка, которая уже закрылась, не держит Escape. Раньше она уходила из DOM лишь
// после анимации выхода, и всё это время её слой съедал Escape (`preventDefault`) — просмотр
// оставался открытым. Escape здесь посылается сразу после закрытия, ещё до любого кадра.
test('Escape сразу после закрытия подсказки закрывает просмотр', async ({ page }) => {
  await page.goto('/memes?channel=example-tech&m=bell-curve');
  await openTip(page, viewer(page).getByTestId('mark-keep'), 'Оставить мем в библиотеке (K)');
  const prevented = await page.evaluate(async () => {
    (document.activeElement as HTMLElement).blur();
    await new Promise((r) => setTimeout(r, 0));
    const e = new KeyboardEvent('keydown', { key: 'Escape', bubbles: true, cancelable: true });
    document.body.dispatchEvent(e);
    return e.defaultPrevented;
  });
  expect(prevented).toBe(false);
  await expect(page.getByRole('tooltip')).toHaveCount(0);
  await expect(viewer(page)).toHaveCount(0);
});

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('банки, сетка, просмотр и отметки без прокрутки вбок', async ({ page, apiHits }) => {
    await page.goto('/memes');
    await expect(page.getByTestId('meme')).toHaveCount(35);
    await noSideScroll(page);
    await card(page, 'drake-hotline-bling').click();
    await expect(viewer(page)).toBeInViewport();
    await viewer(page).getByTestId('meme-show-cut').click();
    await expect(viewer(page).getByTestId('meme-media')).toHaveAttribute('src', /kind=cut/);
    await viewer(page).getByTestId('mark-keep').click();
    await viewer(page).getByTestId('meme-next').click();
    await expect(viewer(page)).toHaveAttribute('data-id', 'evil-kermit');
    await noSideScroll(page);
    expect(writes(apiHits)).toEqual([]);

    // Панель внизу: статус одной строкой, кнопки строкой под ним, не выше ~110px, ничто не
    // наезжает; в конце страницы последняя строка сетки — над панелью, а не под ней.
    await viewer(page).getByTestId('mark-drop').click();
    await expect(page.getByTestId('desk-unsaved')).toHaveText('Не сохранено: 2 отметки');
    const bar = await page.evaluate(() => {
      const box = (e: Element) => e.getBoundingClientRect();
      const b = box(document.querySelector('[data-testid="desk-bar"]')!);
      const status = document.querySelector('[data-testid="desk-unsaved"]')!;
      const s = box(status);
      const lineHeight = parseFloat(getComputedStyle(status).lineHeight) || 18;
      const buttons = [...document.querySelectorAll('[data-testid="desk-bar"] button')].map(box);
      const hit = buttons.filter(
        (r) => r.left < s.right && r.right > s.left && r.top < s.bottom && r.bottom > s.top,
      ).length;
      const rows = new Set(buttons.map((r) => Math.round(r.top))).size;
      return {
        height: b.height,
        statusLines: Math.round(s.height / lineHeight),
        hit,
        rows,
        text: (status as HTMLElement).innerText,
        bottom: b.bottom,
        viewport: window.innerHeight,
      };
    });
    expect(bar.height).toBeLessThanOrEqual(110);
    expect(bar.statusLines).toBe(1);
    expect(bar.hit).toBe(0);
    expect(bar.rows).toBe(1);
    expect(bar.text).toBe('Не сохранено: 2');
    expect(Math.round(bar.bottom)).toBe(bar.viewport);
    await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
    const end = await page.evaluate(() => {
      const cards = [...document.querySelectorAll('[data-testid="meme"]')];
      const last = cards[cards.length - 1]!.getBoundingClientRect();
      const b = document.querySelector('[data-testid="desk-bar"]')!.getBoundingClientRect();
      return { last: last.bottom, bar: b.top };
    });
    expect(end.last).toBeLessThanOrEqual(end.bar);
    await noSideScroll(page);
    await page.getByTestId('desk-save').click();
    await expect(page.getByTestId('desk-unsaved')).toHaveText('Все отметки сохранены');
    expect(writes(apiHits)).toEqual(['PUT /api/memes/example-tech/marks']);
  });
});
