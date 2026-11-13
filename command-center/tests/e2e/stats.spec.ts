// CC-0021: экран «Статистика и аналитик» на подставной статистике (src/mocks/analytics.ts):
// таб → каналы → ролики с окном 7 дней → график ролика, сводка аналитика словами, нужный футаж
// (упакованные — только по кнопке), чтение Studio (ввод — stats-studio.spec.ts); пустые состояния;
// телефон 390 без прокрутки вбок; тренировка показывает экран на демо-данных. Пока ничего не
// вносят, с экрана уходят только GET.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, openTip, test } from './fixtures';

const tabs = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });
const onlyGets = (hits: string[]) =>
  expect(
    hits.filter((h) => !h.startsWith('GET ')),
    'записи с экрана статистики',
  ).toEqual([]);

test('таб → Reel: ролики, график ролика, сводка, футаж, Studio — только GET', async ({
  page,
  apiHits,
  analytics,
}) => {
  await page.goto('/');
  await tabs(page).getByRole('link', { name: 'Статистика', exact: true }).click();
  await expect(page).toHaveURL(/\/stats$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Статистика и аналитик');
  await expect(page.getByText('Скоро · версия 0.4', { exact: true })).toHaveCount(0);

  const reel = page.locator('[data-testid="stats-channel"][data-channel="example-film"]');
  await expect(reel.getByRole('link')).toHaveAttribute('aria-current', 'true');
  await openTip(page, reel.locator('[data-slot="status"]'), 'Последний сбор прошёл без ошибок');

  const videos = page.getByTestId('stats-videos');
  await expect(videos.getByTestId('stats-video')).toHaveCount(8);
  const heated = videos.locator('[data-video="hR4c9xQe1aA"]');
  await expect(heated).toContainText('48 210');
  await expect(heated).toContainText('окончательные');
  await openTip(
    page,
    videos.getByText('Вовлечённые', { exact: true }),
    'По ним фабрика сравнивает ролики',
  );

  // Клик по строке — график ролика, ролик в адресе.
  await heated.click();
  await expect(page).toHaveURL(/video=hR4c9xQe1aA/);
  const detail = page.getByTestId('stats-video-detail');
  await expect(detail.getByTestId('chart-bar')).toHaveCount(12);
  await expect(detail.getByTestId('window-tiles')).toContainText('31 400');
  await expect(detail.getByRole('heading', { name: 'Rink rivals' })).toBeVisible();

  // Сводка: измерения словами и пробелы.
  const summary = page.getByTestId('stats-summary');
  await expect(summary.getByTestId('small-sample')).toContainText('Роликов пока мало.');
  await expect(summary.locator('[data-dimension="pattern"]')).toContainText(
    'Больше всего вовлечённых просмотров (медиана) — у «контраст»',
  );
  await expect(summary.getByTestId('gap-no_profile')).toContainText('Sandfall messiah');
  await summary.getByTestId('summary-day').selectOption('2026-10-08');
  await expect(summary).toContainText('Сводка аналитика · за 08.10');
  await expect(page).toHaveURL(/day=2026-10-08/);

  // Нужный футаж: упакованные — только по кнопке.
  const footage = page.getByTestId('stats-footage');
  await expect(footage.getByTestId('footage-row')).toHaveCount(5);
  expect(analytics.state.calls.some((c) => c.includes('packed=true'))).toBe(false);
  await openTip(page, footage.getByTestId('footage-packed'), 'это может занять минуту');
  await footage.getByTestId('footage-packed').click();
  await expect(footage.getByTestId('footage-row')).toHaveCount(6);
  await expect(footage.locator('[data-name="The Last Ember S2"]')).toContainText('из архива');
  expect(analytics.state.calls).toContain('/api/analytics/example-film/footage-wanted?packed=true');

  // Studio: что прочитать; ввод свёрнут, пока его не раскроют.
  const studio = page.getByTestId('stats-studio');
  await expect(studio.getByTestId('studio-due')).toContainText('пора читать');
  await expect(studio.getByTestId('studio-video')).toHaveCount(5);
  await expect(studio.getByTestId('studio-entry-toggle')).toBeVisible();
  await expect(studio.getByTestId('studio-entry-form')).toHaveCount(0);

  onlyGets(apiHits);
});

test('Tech: окно не собирается, Studio не настроено; Science: сбора не было', async ({
  page,
  apiHits,
}) => {
  await page.goto('/stats?channel=example-tech');
  await expect(page.getByTestId('not-collected')).toBeVisible();
  await expect(page.getByTestId('stats-video').first()).toContainText('окно не собирается');
  await expect(page.getByText('Чтение Studio для канала не настроено')).toBeVisible();

  await page.locator('[data-testid="stats-channel"][data-channel="example-science"] a').click();
  await expect(page).toHaveURL(/channel=example-science/);
  await expect(page.getByTestId('never-collected')).toBeVisible();
  await expect(page.getByText('Роликов со статистикой пока нет')).toBeVisible();
  await expect(page.getByText('Нужного футажа нет')).toBeVisible();
  await expect(page.getByText('У канала нет конвейера')).toBeVisible();
  onlyGets(apiHits);
});

test.describe('отказ', () => {
  test.use({ expectCleanConsole: false });
  test('хранилище не читается — строка фабрики словами', async ({
    page,
    analytics,
    consoleErrors,
  }) => {
    analytics.state.broken = 'example-film';
    await page.goto('/stats');
    await expect(page.getByText('Числа роликов не прочитать')).toBeVisible();
    await expect(page.getByText('Хранилище статистики канала не читается.').first()).toBeVisible();
    expect(consoleErrors.filter((e) => !e.includes('status of 409'))).toEqual([]);
  });
});

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('экран целиком без прокрутки вбок, график ролика открывается', async ({ page, apiHits }) => {
    await page.goto('/stats');
    await expect(page.getByTestId('stats-video')).toHaveCount(8);
    await expect(page.getByTestId('footage-row')).toHaveCount(5);
    await expect(page.getByTestId('summary-dimension')).toHaveCount(5);
    await noSideScroll(page);
    await page.getByRole('link', { name: 'Vanguards doomsday' }).click();
    await expect(page.getByTestId('views-chart')).toBeVisible();
    // Подписи оси — целиком внутри графика: верхняя (самая длинная) не срезана слева.
    const chart = (await page.getByTestId('views-chart').boundingBox())!;
    for (const label of await page.getByTestId('chart-axis-label').all()) {
      const box = (await label.boundingBox())!;
      expect(box.x, (await label.textContent()) ?? '').toBeGreaterThanOrEqual(chart.x);
    }
    await noSideScroll(page);
    onlyGets(apiHits);
  });
});

test('тренировка: экран статистики на демо-данных, живой API не тронут', async ({
  page,
  apiHits,
}) => {
  test.setTimeout(90_000);
  await page.goto('/');
  await expect(page.getByTestId('attention')).toBeVisible();
  await page.getByTestId('tour-open').click();
  await page.getByTestId('tour-contents').getByTestId('tour-practice').click();
  await expect(page.getByTestId('training-banner-text')).toBeVisible();
  const live = apiHits.length;
  if (await page.getByTestId('training-panel').isVisible())
    await page.getByTestId('training-collapse').click();
  await tabs(page).getByRole('link', { name: 'Статистика', exact: true }).click();
  await expect(page.getByTestId('stats-video')).toHaveCount(8);
  await expect(page.getByTestId('stats-studio').getByTestId('studio-due')).toBeVisible();
  expect(apiHits.slice(live)).toEqual([]);
});
