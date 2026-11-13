// CC-0084: глобальный прелоадер записи. Пока запись в полёте, центр под слоем: клик по другому
// табу не проходит, клавиши и Esc — тоже; слой снимается по ответу фабрики (успех или отказ —
// отказ экран показывает как раньше). Окно подтверждения во время плана и «да» не закрывается.
// Ответ записи держим своим `page.route` и отпускаем, когда проверили слой.
import type { Page } from '@playwright/test';

import { TECH_BANK } from '../../src/mocks/memesData';
import { expect, onlyHttp, test } from './fixtures';

const lock = (page: Page) => page.getByTestId('write-lock');
const tab = (page: Page, name: string) =>
  page.getByRole('navigation', { name: 'Разделы' }).getByRole('link', { name, exact: true });

/** Держать ответ на запись `method glob`, пока тест не отпустит (`release`). */
async function hold(page: Page, method: string, glob: string) {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  let seen!: () => void;
  const sent = new Promise<void>((r) => (seen = r));
  await page.route(glob, async (route) => {
    if (route.request().method() !== method) return route.fallback();
    seen();
    await gate;
    await route.fallback();
  });
  return { release, sent };
}

/** Подписи слоя, которые показывались на странице (короткую запись иначе не поймать). */
async function recordLocks(page: Page) {
  await page.addInitScript(() => {
    const seen: string[] = [];
    (window as unknown as { __locks: string[] }).__locks = seen;
    new MutationObserver(() => {
      const t = document.querySelector('[data-testid="write-lock-title"]')?.textContent;
      if (t && seen.at(-1) !== t) seen.push(t);
    }).observe(document, { subtree: true, childList: true, characterData: true });
  });
  return () => page.evaluate(() => (window as unknown as { __locks: string[] }).__locks);
}

test('«Сохранить отметки»: центр замер — таб не нажимается, клавиши не идут; ответ снимает слой', async ({
  page,
  memes,
}) => {
  await page.goto('/memes?channel=example-tech&m=roll-safe');
  const viewer = page.getByTestId('meme-viewer');
  await viewer.getByTestId('mark-drop').click();
  await expect(page.getByTestId('desk-unsaved')).toContainText('Не сохранено: 1 отметка');
  const put = await hold(page, 'PUT', '**/api/memes/*/marks');

  await page.getByTestId('desk-save').click();
  await put.sent;
  await expect(lock(page)).toBeVisible();
  await expect(page.getByTestId('write-lock-title')).toHaveText('Сохраняю отметки…');
  await expect(lock(page)).toHaveAttribute('aria-busy', 'true');
  await expect(page.locator('[aria-busy="true"]').first()).toBeAttached();
  await expect(lock(page)).toBeFocused();
  await expect(lock(page).locator('.write-lock-in').last()).toHaveCSS('opacity', '1');

  // Клик по другому табу — мышью в его точку (force: без ожидания, что он кликабелен).
  await tab(page, 'Вопросы').click({ force: true });
  await page.keyboard.press('Escape');
  await page.keyboard.press('k');
  await page.keyboard.press('Tab');
  await expect(page).toHaveURL(/\/memes\?/);
  await expect(lock(page)).toBeVisible();
  await expect(lock(page)).toBeFocused();
  await expect(viewer).toHaveAttribute('data-id', 'roll-safe');
  await expect(page.getByTestId('desk-unsaved')).toContainText('Не сохранено: 1 отметка');

  put.release();
  await expect(lock(page)).toHaveCount(0);
  await expect(page.getByTestId('desk-unsaved')).toHaveText('Все отметки сохранены');
  expect(memes.desk('example-tech').decisions['roll-safe']).toMatchObject({ v: 'drop' });

  // После ответа — интерфейс снова живой.
  await tab(page, 'Вопросы').click();
  await expect(page).toHaveURL(/\/questions$/);
});

test.describe('отказ', () => {
  test.use({ expectCleanConsole: false });

  test('отказ фабрики снимает слой, отказ на экране как раньше', async ({
    page,
    memes,
    consoleErrors,
  }) => {
    await page.goto('/memes?channel=example-tech&m=roll-safe');
    await page.getByTestId('meme-viewer').getByTestId('mark-drop').click();
    memes.editElsewhere(TECH_BANK, 'trade-offer', { v: 'keep' });
    const put = await hold(page, 'PUT', '**/api/memes/*/marks');
    await page.getByTestId('desk-save').click();
    await put.sent;
    await expect(lock(page)).toBeVisible();
    await tab(page, 'Каналы').click({ force: true });
    await expect(page).toHaveURL(/\/memes\?/);

    put.release();
    await expect(lock(page)).toHaveCount(0);
    await expect(page.getByTestId('desk-conflict')).toContainText(
      'Отметки изменились в другом месте',
    );
    await tab(page, 'Каналы').click();
    await expect(page).toHaveURL(/\/channels$/);
    onlyHttp(consoleErrors, 409);
  });
});

test('«Применить разбор»: план под слоем коротко, окно ждёт «да»; «да» — слой «Применяю разбор…», Esc окно не закрывает', async ({
  page,
}) => {
  const locks = await recordLocks(page);
  await page.goto('/memes?channel=example-tech');
  await expect(page.getByTestId('meme').first()).toBeVisible();
  await page.getByTestId('apply-open').click();
  const dialog = page.getByRole('alertdialog');
  const confirm = dialog.getByTestId('apply-confirm');
  await expect(confirm).toContainText(/Применить · \d/);
  // План прошёл под слоем; окно с отсчётом — без слоя, им можно пользоваться.
  await expect(lock(page)).toHaveCount(0);
  expect(await locks()).toEqual(['Готовлю план…']);

  const apply = await hold(page, 'POST', '**/api/memes/*/apply');
  await confirm.click();
  await apply.sent;
  await expect(page.getByTestId('write-lock-title')).toHaveText('Применяю разбор…');
  await page.keyboard.press('Escape');
  await expect(dialog).toBeVisible();
  await expect(lock(page)).toBeVisible();

  apply.release();
  await expect(lock(page)).toHaveCount(0);
  await expect(page.getByTestId('apply-done')).toContainText('Вошли в библиотеку');
});

test('чтения слой не включают: открытие экранов и перечитывания идут без слоя', async ({
  page,
}) => {
  const locks = await recordLocks(page);
  await page.goto('/');
  await tab(page, 'Мемы').click();
  await expect(page.getByTestId('meme').first()).toBeVisible();
  await tab(page, 'Публикация').click();
  await expect(page).toHaveURL(/\/publishing$/);
  await page.waitForLoadState('networkidle');
  await tab(page, 'Каналы').click();
  await expect(page).toHaveURL(/\/channels$/);
  await page.waitForLoadState('networkidle');
  expect(await locks()).toEqual([]);
});

test('тренировка — тот же слой', async ({ page, apiHits }) => {
  test.slow();
  const locks = await recordLocks(page);
  await page.goto('/');
  await page.getByTestId('tour-open').click();
  await page.getByTestId('tour-contents').getByTestId('tour-practice').click();
  await expect(page.getByTestId('training-banner-text')).toHaveText(
    'Тренировка — это демо, фабрика не трогается',
    { timeout: 30_000 },
  );
  const live = apiHits.length;
  const collapse = page.getByTestId('training-collapse');
  if (await collapse.isVisible()) await collapse.click();
  await tab(page, 'Вопросы').click();
  const q = page.getByTestId('question').first();
  await q.getByTestId('answer-text').fill('Берём второй вариант');
  await q.getByTestId('answer-send').click();
  await expect(page.getByText('Ответ отправлен фабрике')).toBeVisible();
  await expect(lock(page)).toHaveCount(0);
  expect(await locks()).toContain('Записываю ответ на вопрос…');
  expect(apiHits.length, 'в живой API тренировка не ходит').toBe(live);
});
