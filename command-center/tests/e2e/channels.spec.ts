// Экран «Каналы» на подставном API (src/mocks/channels.ts): правка, проверка, сохранение,
// история и «вернуть», блокировка батчем, конфликт, телефон.
import type { Page } from '@playwright/test';

import type { components } from '../../src/api/schema.gen';
import { REEL_CONFIG_TEXT, REEL_STANCE_TEXT, revisionOf } from '../../src/mocks/channels';
import { expect, onlyHttp, openTip, test } from './fixtures';

type S = components['schemas'];

const noHorizontalScroll = async (page: Page) => {
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(doc.scroll, 'горизонтальная прокрутка страницы').toBeLessThanOrEqual(doc.width);
};

const SCORE_RU =
  'Настройки сценариста, поле scope.min_popularity_score (сейчас 450): значение не подходит сценаристу - он его не прочтёт.';
const SCORE_EN =
  'example-film.json.scope.min_popularity_score: must be a number from 0 to 100, got 450 (код причины: content_researcher_invalid)';

const openScope = async (page: Page) => {
  await page.getByRole('button', { name: /^scope,/ }).click();
  return page.getByLabel('min popularity score', { exact: true });
};

test('список → канал → правка → ошибка на поле → исправление → сохранение → история → «вернуть»', async ({
  page,
  channels,
}) => {
  await page.goto('/channels');
  await expect(page.getByTestId('channels-count')).toHaveText('3 канала');
  const reel = page.getByTestId('channel-example-film');
  await expect(reel.getByTestId('schedule')).toHaveText('окно с 02:00 на 3 ч · Europe/Moscow');
  await reel.getByRole('link', { name: 'Открыть настройки' }).click();
  await expect(page).toHaveURL(/\/channels\/example-film$/);
  await expect(page.getByRole('heading', { level: 1, name: 'ExampleFilm' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'Каналы', exact: true })).toHaveAttribute(
    'aria-current',
    'page',
  );

  const score = await openScope(page);
  // Тултип поля — пояснение из конфига, без номера задачи.
  const fieldTip = await openTip(
    page,
    page.getByRole('button', { name: 'Что это: scope → min popularity score' }),
    'A candidate below this popularity score',
    'hover',
  );
  await expect(fieldTip).not.toContainText('CF-0060');

  await score.fill('450');
  await expect(page.getByTestId('draft-state')).toHaveText('Не сохранено, изменено полей: 1');
  await page.getByRole('button', { name: 'Проверить' }).click();
  const result = page.getByTestId('check-result');
  await expect(result).toContainText('Проверка не пройдена');
  // CC-0055: русская строка фабрики (`text_ru`) — поле и значение названы в ней самой.
  await expect(result).toContainText(SCORE_RU);
  await expect(result).not.toContainText('Поле «scope → min popularity score»');
  await expect(result).not.toContainText('Must be a number');
  const scoreField = page.locator('[data-field="config:scope.min_popularity_score"]');
  await expect(scoreField).toHaveAttribute('data-invalid', 'true');
  await expect(scoreField).toContainText(SCORE_RU);
  // Английский текст проверки и код причины — только под «подробнее».
  const english = result.getByText(SCORE_EN, { exact: true });
  await expect(english).toBeHidden();
  await result.getByText('Подробнее', { exact: true }).click();
  await expect(english).toBeVisible();
  await expect(
    result.getByRole('button', { name: 'К полю в форме «scope → min popularity score»' }),
  ).toBeVisible();

  await score.fill('50');
  await page.getByRole('button', { name: 'Сохранить' }).click();
  await expect(page.getByRole('button', { name: 'Сохраняю…' })).toBeVisible();
  await expect(page.getByTestId('saved')).toContainText('изменено scope.min_popularity_score');
  await expect(page.getByTestId('draft-state')).toHaveText('Правок нет');

  const put = channels.writes.find((w) => w.kind === 'save')!.body as Record<string, unknown>;
  expect(put.base).toBe(revisionOf(REEL_CONFIG_TEXT, REEL_STANCE_TEXT));
  expect(put.config_text).toBe(
    REEL_CONFIG_TEXT.replace('"min_popularity_score": 45', '"min_popularity_score": 50'),
  );
  expect(put).not.toHaveProperty('config');

  await page.getByRole('tab', { name: 'История' }).click();
  await expect(page).toHaveURL(/tab=history/);
  const first = page.getByRole('list', { name: 'История правок' }).getByRole('listitem').first();
  await expect(first).toContainText('из центра');
  await expect(first).toContainText('изменено scope.min_popularity_score');
  // Чужой коммит не возвращается — с объяснением в тултипе.
  const foreign = page.getByTestId('commit-f40c69a');
  await expect(foreign).toContainText('Правка в репозитории фабрики');
  await expect(foreign.getByText(/CF-0645/)).toBeHidden();
  await expect(foreign.getByRole('button', { name: 'Вернуть' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );

  await first.getByRole('button', { name: 'Вернуть' }).click();
  const dialog = page.getByRole('alertdialog', { name: 'Вернуть как было до этой правки?' });
  await dialog.getByRole('button', { name: 'Отмена' }).click();
  expect(channels.writes.filter((w) => w.kind === 'revert')).toHaveLength(0);
  await first.getByRole('button', { name: 'Вернуть' }).click();
  await dialog.getByRole('button', { name: 'Вернуть' }).click();
  await expect(page.getByTestId('revert-done')).toContainText('Возвращено');
  const revert = channels.writes.find((w) => w.kind === 'revert')!.body as { base: string };
  expect(revert.base).toBe(
    revisionOf(
      REEL_CONFIG_TEXT.replace('"min_popularity_score": 45', '"min_popularity_score": 50'),
      REEL_STANCE_TEXT,
    ),
  );
  await expect(
    page.getByRole('list', { name: 'История правок' }).getByRole('listitem').first(),
  ).toContainText('возврат');

  await page.getByRole('tab', { name: 'Настройки' }).click();
  await expect(await openScope(page)).toHaveValue('45');
});

test('сырой JSON: подсветка, ошибка записи по-русски, проверка до сохранения', async ({
  page,
  channels,
}) => {
  await page.goto('/channels/example-film?tab=raw');
  const editor = page.getByTestId('raw-editor');
  await expect(editor.locator('.cm-content')).toContainText('"min_popularity_score": 45');
  // Подсветка: ключи и числа — своими цветами (разбор идёт фоном — ждём его).
  await expect
    .poll(() =>
      editor.evaluate((el) => {
        const color = (t: string) => {
          const span = [...el.querySelectorAll('.cm-line span')].find((x) => x.textContent === t);
          return span ? getComputedStyle(span).color : null;
        };
        const key = color('"display_name"');
        const num = color('45');
        return !!key && !!num && key !== num;
      }),
    )
    .toBe(true);

  const content = editor.locator('.cm-content');
  await content.click();
  await page.keyboard.press('ControlOrMeta+End');
  await page.keyboard.type(',');
  await expect(page.getByTestId('syntax')).toContainText('Запись JSON с ошибкой');
  await expect(page.getByRole('button', { name: 'Сохранить' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  await page.keyboard.press('Backspace');
  await expect(page.getByTestId('syntax')).toHaveCount(0);

  // Правка текстом → «Проверить» (ничего не пишется) → ошибка ведёт к полю формы.
  await page.getByText('"max_video_seconds": 58').click();
  await page.keyboard.press('End');
  await page.keyboard.press('ArrowLeft'); // перед запятой
  await page.keyboard.press('Backspace');
  await page.keyboard.press('Backspace');
  await page.keyboard.type('90');
  await page.getByRole('button', { name: 'Проверить' }).click();
  const result = page.getByTestId('check-result');
  await expect(result).toContainText(
    'Настройки монтажёра, поле video_editor.max_video_seconds (сейчас 90): значение не подходит монтажёру - с ним он не соберёт ролик.',
  );
  expect(channels.writes).toHaveLength(0);
  await result
    .getByRole('button', { name: 'К полю в форме «video editor → max video seconds»' })
    .click();
  await expect(page.getByLabel('max video seconds', { exact: true })).toBeFocused();
  await expect(page.getByLabel('max video seconds', { exact: true })).toHaveValue('90');
});

test('строка без русского у фабрики (`text_ru` null) — поле по-русски и причина проверки', async ({
  page,
  channels,
}) => {
  const text = 'example-film.json.scope.min_popularity_score: below the floor of the feed, got 1';
  await page.route('**/api/channels/example-film/check', (route) =>
    route.fulfill({
      json: {
        ok: false,
        errors: [{ field: 'scope.min_popularity_score', text, code: null, text_ru: null }],
      } satisfies S['CheckResult'],
    }),
  );
  await page.goto('/channels/example-film');
  const score = await openScope(page);
  await score.fill('1');
  await page.getByRole('button', { name: 'Проверить' }).click();
  const result = page.getByTestId('check-result');
  await expect(result).toContainText('Поле «scope → min popularity score»');
  await expect(result).toContainText('Below the floor of the feed, got 1');
  const scoreField = page.locator('[data-field="config:scope.min_popularity_score"]');
  await expect(scoreField).toHaveAttribute('data-invalid', 'true');
  await expect(scoreField).toContainText('Не прошло проверку: Below the floor of the feed, got 1');
  // Строка целиком — под «подробнее», без кода причины (его нет).
  await result.getByText('Подробнее', { exact: true }).click();
  await expect(result.getByText(text, { exact: true })).toBeVisible();
  await expect(result).not.toContainText('код причины');
  await result.getByRole('button', { name: 'Поле «scope → min popularity score»' }).click();
  await expect(score).toBeFocused();
  expect(channels.writes).toHaveLength(0);
});

test('идёт батч канала: объяснение, поля и «сохранить» закрыты', async ({ page, channels }) => {
  channels.lock(
    'example-film',
    'Идёт батч канала example-film (2026-10-10T0200Z): пока он не закончится, конфиг и позицию менять нельзя - батч читает их по ходу работы.',
  );
  await page.goto('/channels');
  await expect(
    page.getByTestId('channel-example-film').getByText('идёт батч', { exact: true }),
  ).toBeVisible();
  await page.goto('/channels/example-film');
  const banner = page.getByTestId('lock-banner');
  await expect(banner).toContainText('Правка закрыта, пока идёт батч');
  await expect(banner).toContainText('батч читает их по ходу работы');
  await expect(banner.getByText(/pipeline\/runs/)).toBeHidden();
  await expect(await openScope(page)).toBeDisabled();
  const save = page.getByRole('button', { name: 'Сохранить' });
  await expect(save).toHaveAttribute('aria-disabled', 'true');
  await openTip(page, save, 'Идёт батч канала example-film', 'hover');
  await page.getByRole('tab', { name: 'История' }).click();
  await expect(
    page
      .getByRole('list', { name: 'История правок' })
      .getByRole('button', { name: 'Вернуть' })
      .first(),
  ).toHaveAttribute('aria-disabled', 'true');
  expect(channels.writes).toHaveLength(0);
});

test.describe('ожидаемые отказы API', () => {
  test.use({ expectCleanConsole: false });

  test('конфликт 409: понятное сообщение и «загрузить свежую версию»', async ({
    page,
    channels,
    consoleErrors,
  }) => {
    await page.goto('/channels/example-film');
    const score = await openScope(page);
    await score.fill('60');
    channels.touch('example-film'); // кто-то поменял файл мимо центра
    await page.getByRole('button', { name: 'Сохранить' }).click();
    const result = page.getByTestId('check-result');
    await expect(result).toContainText('Конфиг изменился, пока вы его правили');
    await result.getByRole('button', { name: 'Загрузить свежую версию' }).click();
    await page
      .getByRole('alertdialog', { name: 'Загрузить свежую версию канала?' })
      .getByRole('button', { name: 'Загрузить' })
      .click();
    await expect(page.getByTestId('draft-state')).toHaveText('Правок нет');
    await expect(page.getByTestId('check-result')).toHaveCount(0);
    await score.fill('60');
    await page.getByRole('button', { name: 'Сохранить' }).click();
    await expect(page.getByTestId('saved')).toBeVisible();
    onlyHttp(consoleErrors, 409);
  });

  test('устаревшее «открыто»: сохранение — 409 batch_running по-человечески, батч на экране', async ({
    page,
    channels,
    consoleErrors,
  }) => {
    const msg =
      'Идёт батч канала example-film (2026-10-10T0200Z): пока он не закончится, конфиг и позицию менять нельзя - батч читает их по ходу работы.';
    channels.lock('example-film', msg, false); // прошлый скан фабрики батча ещё не видел
    await page.goto('/channels/example-film');
    await openTip(page, page.getByText('Правка настроек', { exact: true }), 'проверено 4 с назад');
    const score = await openScope(page);
    await score.fill('60');
    await page.getByRole('button', { name: 'Сохранить' }).click();
    const result = page.getByTestId('check-result');
    await expect(result).toContainText('Не сохранено: идёт батч');
    await expect(result).toContainText('при записи фабрика проверила заново и нашла идущий батч');
    await expect(page.getByTestId('lock-banner')).toContainText('Правка закрыта, пока идёт батч');
    await expect(page.getByTestId('draft-state')).toHaveText('Не сохранено, изменено полей: 1');
    onlyHttp(consoleErrors, 409);
  });

  test('отказ сохранения (422 invalid): русская строка, английская с кодом — раз, в «подробнее»', async ({
    page,
    channels,
    consoleErrors,
  }) => {
    await page.goto('/channels/example-film');
    const score = await openScope(page);
    await score.fill('450');
    await page.getByRole('button', { name: 'Сохранить' }).click();
    const result = page.getByTestId('check-result');
    await expect(result).toContainText('Ничего не сохранено');
    await expect(result).toContainText(SCORE_RU);
    await expect(page.locator('[data-field="config:scope.min_popularity_score"]')).toHaveAttribute(
      'data-invalid',
      'true',
    );
    await result.getByText('Подробнее', { exact: true }).click();
    await expect(result.getByText(SCORE_EN, { exact: true })).toHaveCount(1);
    await expect(result.getByText(SCORE_EN.replace(/ \(код.*$/, ''), { exact: true })).toHaveCount(
      0,
    );
    await expect(page.getByTestId('draft-state')).toHaveText('Не сохранено, изменено полей: 1');
    expect(channels.detail('example-film').body).toMatchObject({ config_text: REEL_CONFIG_TEXT });
    onlyHttp(consoleErrors, 422);
  });

  test('несуществующий канал — понятное «нет такого»', async ({ page, consoleErrors }) => {
    await page.goto('/channels/nope');
    await expect(page.getByText('Такого канала нет')).toBeVisible();
    await expect(page.getByText('Канала «nope» нет в фабрике.')).toBeVisible();
    onlyHttp(consoleErrors, 404);
  });
});

test('телефон: без горизонтальной прокрутки на списке, форме и сыром JSON', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels');
  await expect(page.getByTestId('channel-example-film').getByTestId('schedule')).toBeVisible();
  await noHorizontalScroll(page);
  await page.goto('/channels/example-film');
  await page.getByRole('button', { name: 'Развернуть все' }).first().click();
  await expect(page.getByLabel('min popularity score', { exact: true })).toBeVisible();
  await noHorizontalScroll(page);
  await page.getByRole('tab', { name: 'Сырой JSON' }).click();
  await expect(page.getByTestId('raw-editor').locator('.cm-content')).toBeVisible();
  await noHorizontalScroll(page);
  await page.getByRole('tab', { name: 'История' }).click();
  await expect(page.getByRole('list', { name: 'История правок' })).toBeVisible();
  await noHorizontalScroll(page);
});
