// Мастер «Новый канал» (CC-0009, CC-0043) на подставном API (src/mocks/channels.ts): dry-run по
// ходу ввода, шаги с тултипами, проверка, создание с позицией одним коммитом, приём в редакторе;
// блокировка батчем и устаревшее «открыто»; отказ фабрики по позиции; `new`; телефон.
import type { Page } from '@playwright/test';

import type { components } from '../../src/api/schema.gen';
import { expect, openTip, test } from './fixtures';

type S = components['schemas'];

const noHorizontalScroll = async (page: Page) => {
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(doc.scroll, 'горизонтальная прокрутка страницы').toBeLessThanOrEqual(doc.width);
};

const fillInputs = async (page: Page, id: string, name: string) => {
  await page.getByLabel('Идентификатор', { exact: true }).fill(id);
  await page.getByLabel('Название', { exact: true }).fill(name);
};

const THESIS = 'Позиция в одну фразу (можно оставить пустой)';

test('счастливый путь: ошибка фабрики под полем → исправление → шаги → проверка → создание + позиция → редактор', async ({
  page,
  channels,
}) => {
  await page.goto('/channels');
  const newButton = page.getByRole('link', { name: '+ Новый канал' });
  await openTip(page, newButton, 'по своему шаблону');
  await newButton.click();
  await expect(page).toHaveURL(/\/channels\/new$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Новый канал' })).toBeVisible();

  // Тултип поля — пояснение шаблона фабрики, без номера задачи.
  const idTip = await openTip(
    page,
    page.getByRole('button', { name: 'Что это: Идентификатор' }),
    'латиница в нижнем регистре',
  );
  await expect(idTip).not.toContainText('CF-0197');

  // Своя проверка — сразу, фабрики (занято) — dry-run по ходу ввода.
  await page.getByLabel('Идентификатор', { exact: true }).fill('Food');
  await expect(page.locator('[data-input="channel_id"]')).toContainText('Латиница в нижнем');
  await fillInputs(page, 'example-film', 'ExampleFilm');
  await expect(page.locator('[data-input="channel_id"]')).toContainText(
    "Канал 'example-film' уже есть",
  );
  await expect(page.locator('[data-input="display_name"]')).toContainText(
    "'ExampleFilm' - уже название канала 'example-film'",
  );
  const next = page.getByRole('button', { name: /Далее: Тематика и позиция/ });
  await expect(next).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByRole('button', { name: 'Шаг 7: Создать' })).toHaveAttribute(
    'aria-disabled',
    'true',
  );

  await fillInputs(page, 'example-food', 'ExampleFood');
  await expect(page.getByTestId('dry-run-ok')).toBeVisible();
  await expect(page.locator('[data-input="channel_id"] .text-danger')).toHaveCount(0);
  expect(channels.writes, 'dry-run ничего не пишет').toEqual([]);

  await next.click();
  await openTip(page, page.getByRole('button', { name: `Что это: ${THESIS}` }), 'one sentence');
  await page.getByLabel(THESIS, { exact: true }).fill('Food facts, checked at the source.');
  await expect(page.locator('[data-guide="Тематика"]')).toContainText(
    'В шаблоне фабрики этого нет',
  );

  await page.getByRole('button', { name: /Далее: Голос и паттерны/ }).click();
  await expect(page.locator('[data-guide="Голос озвучки"]')).toBeVisible();
  await page.getByRole('button', { name: /Далее: Ленты и источники/ }).click();
  await expect(page.locator('[data-guide="Источники"]')).toContainText('robots.txt');
  await page.getByRole('button', { name: /Далее: Публикация и окно/ }).click();
  await expect(page.getByTestId('schedule-off')).toHaveText('выключено');
  await openTip(page, page.getByText('Расписание батчей', { exact: true }), 'off the schedule');

  await page.getByRole('button', { name: /Далее: Проверка/ }).click();
  await expect(page.getByTestId('review-ok')).toContainText('Фабрика примет канал');
  await expect(page.getByTestId('review-thesis')).toHaveText(
    '«Food facts, checked at the source.»',
  );
  // Пути файлов и разница — только под «подробнее».
  await expect(page.getByText('channels/example-food/stance.json', { exact: true })).toBeHidden();
  const diff = page.getByTestId('review-diff');
  await diff.getByText('Разница с шаблоном').click();
  await expect(diff).toContainText('+     "thesis": "Food facts, checked at the source.",');

  await page.getByRole('button', { name: /Далее: Создать/ }).click();
  await expect(page.getByTestId('plan')).toContainText('позиция — уже с вашей фразой');
  // Свежесть блокировки: когда фабрика последний раз смотрела батчи.
  await expect(page.getByTestId('lock-fresh')).toContainText('фабрика проверила 4 с назад');
  await expect(page.getByTestId('todo')).toContainText('Что ещё нужно до первого батча');
  await page.getByTestId('create').click();
  await expect(page.getByRole('status').filter({ hasText: 'Создаю канал' })).toBeVisible();

  await expect(page).toHaveURL(/\/channels\/example-food$/);
  await expect(page.getByTestId('wizard-landing')).toContainText('с вашей позицией, одной правкой');
  await expect(page.getByRole('heading', { level: 1, name: 'ExampleFood' })).toBeVisible();
  await expect(page.getByTestId('todo')).toContainText('Расписание батчей');
  // Один коммит: позиция — в самом создании (`stance_text`), PUT следом нет.
  expect(channels.writes.map((w) => w.kind)).toEqual(['create']);
  const create = channels.writes[0]!.body as S['NewChannel'];
  expect(create).toEqual({
    channel_id: 'example-food',
    display_name: 'ExampleFood',
    language: 'en',
    stance_text: expect.stringContaining('"thesis": "Food facts, checked at the source."'),
    dry_run: false,
  });
  expect(create.stance_text).toContain('"channel_id": "example-food"');
  const made = channels.detail('example-food');
  expect(made.status === 200 && made.body.stance_text).toBe(create.stance_text);

  // Канал в списке.
  await page.getByRole('link', { name: '← Все каналы' }).click();
  await expect(page.getByTestId('channels-count')).toHaveText('4 канала');
});

test('идёт любой батч: создать нельзя, объяснение и тултип на кнопке', async ({
  page,
  channels,
}) => {
  channels.lock(
    'example-tech',
    'Идёт батч канала example-tech: пока он не закончится, конфиг менять нельзя.',
  );
  await page.goto('/channels/new');
  await expect(page.getByTestId('create-lock')).toContainText('канал не создать');
  await fillInputs(page, 'example-food', 'ExampleFood');
  await expect(page.getByTestId('dry-run-ok')).toBeVisible();
  await page.getByRole('button', { name: 'Шаг 7: Создать' }).click();
  const create = page.getByTestId('create');
  await expect(create).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByTestId('create-why')).toContainText('канал не создать');
  await openTip(page, create, 'code_drift');
  await create.click({ force: true });
  expect(channels.writes).toEqual([]);
});

test('id «new» отклоняет сама фабрика — её текст под полем', async ({ page, channels }) => {
  await page.goto('/channels/new');
  await fillInputs(page, 'new', 'ExampleNew');
  await expect(page.locator('[data-input="channel_id"]')).toContainText(
    "'new' - служебное имя, не канал",
  );
  await expect(page.getByTestId('dry-run-ok')).toHaveCount(0);
  await expect(page.getByRole('button', { name: /Далее: Тематика и позиция/ })).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  expect(channels.writes).toEqual([]);
});

test.describe('ожидаемый отказ API', () => {
  test.use({ expectCleanConsole: false });

  test('позиция не принята: ничего не создано, замечания фабрики на шаге с фразой', async ({
    page,
    channels,
    consoleErrors,
  }) => {
    await page.route('**/api/channels', async (route) => {
      const sent = route.request().postDataJSON() as S['NewChannel'] | null;
      if (route.request().method() !== 'POST' || sent?.dry_run) return route.fallback();
      channels.writes.push({ kind: 'create', id: 'example-food', body: sent });
      const body: S['ChannelProblem'] = {
        code: 'invalid',
        message: 'Фабрика не приняла новый канал: 1 ошибка проверки. Ничего не создано.',
        details: ['stance.json.position.thesis: one sentence, no line breaks'],
        errors: [
          {
            field: 'stance.position.thesis',
            text: 'stance.json.position.thesis: one sentence, no line breaks',
            code: null,
            text_ru: null,
          },
        ],
        batches: [],
      };
      return route.fulfill({ status: 422, json: body });
    });
    await page.goto('/channels/new');
    await fillInputs(page, 'example-food', 'ExampleFood');
    await expect(page.getByTestId('dry-run-ok')).toBeVisible();
    await page.getByRole('button', { name: 'Шаг 2: Тематика и позиция' }).click();
    await page.getByLabel(THESIS, { exact: true }).fill('Line one.\nLine two.');
    await page.getByRole('button', { name: 'Шаг 7: Создать' }).click();
    await page.getByTestId('create').click();

    // Мастер вернул на шаг с фразой: замечание фабрики там, фраза на месте, канала нет.
    await expect(page).toHaveURL(/\/channels\/new$/);
    const failed = page.getByTestId('stance-failed');
    await expect(failed).toContainText('Канал не создан');
    await expect(failed).toContainText('Ничего не создано');
    await expect(failed).toContainText('One sentence, no line breaks');
    // Проверка позиции русской строки не даёт (`text_ru` null): поле по-русски + причина проверки,
    // сама строка — под «подробнее».
    await expect(failed).toContainText('Поле «Позиция: position → thesis»');
    const line = failed.getByText('stance.json.position.thesis: one sentence, no line breaks', {
      exact: true,
    });
    await expect(line).toBeHidden();
    await failed.getByText('Подробнее', { exact: true }).click();
    await expect(line).toBeVisible();
    await expect(page.getByRole('heading', { level: 2, name: 'Тематика и позиция' })).toBeVisible();
    await expect(page.getByLabel(THESIS, { exact: true })).toHaveValue('Line one.\nLine two.');
    expect(channels.writes.map((w) => w.kind)).toEqual(['create']);
    expect((channels.writes[0]!.body as S['NewChannel']).stance_text).toContain('Line one.');
    expect(channels.detail('example-food').status).toBe(404);
    // Отказ API браузер сам пишет в консоль; других ошибок быть не должно.
    expect(consoleErrors.filter((e) => !e.includes('status of 422'))).toEqual([]);
  });

  test('шаблон фабрики не проходит её проверку: русская строка, английская с кодом — в «подробнее»', async ({
    page,
    channels,
  }) => {
    const text = "example-food.json.theme.text: contrast 2.1 against the background, got '#777'";
    const ru =
      "Оформление канала, поле theme.text (сейчас '#777'): цвета и шрифты заданы не по правилам - монтажёр рисует ролик этой палитрой.";
    await page.route('**/api/channels', async (route) => {
      const sent = route.request().postDataJSON() as S['NewChannel'] | null;
      if (route.request().method() !== 'POST' || !sent?.dry_run) return route.fallback();
      const real = channels.create(sent).body as S['CreateResult'];
      const line: S['CheckLine'] = {
        field: 'theme.text',
        text,
        code: 'theme_invalid',
        text_ru: ru,
      };
      return route.fulfill({ json: { ...real, ok: false, errors: [...real.errors, line] } });
    });
    await page.goto('/channels/new');
    await fillInputs(page, 'example-food', 'ExampleFood');
    await page.getByRole('button', { name: 'Шаг 2: Тематика и позиция' }).click();
    const problems = page.getByTestId('dry-run-problems');
    await expect(problems).toContainText(ru);
    await expect(problems).not.toContainText('Поле «');
    const english = problems.getByText(`${text} (код причины: theme_invalid)`, { exact: true });
    await expect(english).toBeHidden();
    await problems.getByText('Подробнее', { exact: true }).click();
    await expect(english).toBeVisible();
    expect(channels.writes).toEqual([]);
  });

  test('устаревшее «открыто»: создание кончается 409 batch_running — объяснение, баннер', async ({
    page,
    channels,
    consoleErrors,
  }) => {
    // Прошлый скан фабрики батча не видел; запись сканирует заново и находит его.
    channels.openBatch(
      'Идёт батч канала example-film (2026-10-10T0200Z): пока не закончится, канал не создать.',
      false,
    );
    await page.goto('/channels/new');
    await fillInputs(page, 'example-food', 'ExampleFood');
    await expect(page.getByTestId('dry-run-ok')).toBeVisible();
    await expect(page.getByTestId('create-lock')).toHaveCount(0);
    await page.getByRole('button', { name: 'Шаг 7: Создать' }).click();
    await page.getByTestId('create').click();
    const failed = page.getByTestId('create-failed');
    await expect(failed).toContainText('Канал не создан: идёт батч');
    await expect(failed).toContainText('при записи фабрика проверила заново и нашла идущий батч');
    await expect(page.getByTestId('create-lock')).toContainText('канал не создать');
    await expect(page.getByTestId('create')).toHaveAttribute('aria-disabled', 'true');
    expect(channels.detail('example-food').status).toBe(404);
    expect(consoleErrors.filter((e) => !e.includes('status of 409'))).toEqual([]);
  });
});

test('телефон: шаги мастера без горизонтальной прокрутки', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels/new');
  await expect(page.getByRole('navigation', { name: 'Шаги мастера' })).toBeVisible();
  await noHorizontalScroll(page);
  await fillInputs(page, 'example-food', 'ExampleFood');
  await expect(page.getByTestId('dry-run-ok')).toBeVisible();
  await page.getByRole('button', { name: 'Шаг 2: Тематика и позиция' }).click();
  await page.getByLabel(THESIS, { exact: true }).fill('Food facts, checked at the source.');
  for (const n of [3, 4, 5, 6, 7]) {
    await page
      .locator('nav[aria-label="Шаги мастера"] button')
      .nth(n - 1)
      .click();
    await expect(page.locator('[data-step]')).toBeVisible();
    await noHorizontalScroll(page);
  }
  await page.getByRole('button', { name: 'Шаг 6: Проверка' }).click();
  await page.getByText('Файл целиком').first().click();
  await noHorizontalScroll(page);
});
