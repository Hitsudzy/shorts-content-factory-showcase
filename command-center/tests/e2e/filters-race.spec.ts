// CC-0162: фильтры в адресе под нагрузкой. react-router перерисовывает экран в startTransition,
// и второй щелчок приходит раньше, чем отрисован первый; раньше он собирал адрес из прежних
// параметров и стирал только что выбранное. Здесь процессор замедлен в 4 раза (CDP, только
// Chromium), а щелчки идут подряд — без ожидания экрана между ними. «Статистика» — CC-0163.
import type { Page } from '@playwright/test';

import { expect, test } from './fixtures';

test.use({ cpuThrottle: 4 });

/** Параметры адреса страницы — без учёта порядка и кодировки запятой. */
const search = (page: Page) => Object.fromEntries(new URL(page.url()).searchParams);
const ids = (page: Page) =>
  page.getByTestId('task-row').evaluateAll((els) => els.map((e) => e.getAttribute('data-id')));

test('«Разработка»: проект, статусы, веха и вид — щелчками подряд; всё в адресе и на экране', async ({
  page,
}) => {
  test.slow();
  await page.goto('/dev');
  await expect(page.getByTestId('task-row').first()).toBeVisible();

  const center = page.getByTestId('dev-project-center');
  const going = page.locator('[data-testid="dev-status"][data-status="in-progress"]');
  const blocked = page.locator('[data-testid="dev-status"][data-status="blocked"]');
  // Подряд, без ожиданий: каждый следующий — пока экран может ещё не показать предыдущий.
  await center.click();
  await going.click();
  await page.getByTestId('dev-milestone').selectOption('1.1');
  await expect
    .poll(() => search(page))
    .toEqual({ project: 'center', milestone: '1.1', status: 'in-progress' });
  await expect(center).toHaveAttribute('aria-pressed', 'true');
  await expect(going).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('dev-milestone')).toHaveValue('1.1');
  await expect.poll(() => ids(page)).toEqual(['CC-0037', 'CC-0124']);

  // Фильтр и сразу вид: переключатель вида тоже пишет от текущего адреса.
  await blocked.click();
  await page.getByTestId('dev-view-roadmap').click();
  await expect
    .poll(() => search(page))
    .toEqual({
      view: 'roadmap',
      project: 'center',
      milestone: '1.1',
      status: 'in-progress,blocked',
    });
  await expect(page.getByTestId('dev-view-roadmap')).toHaveAttribute('aria-pressed', 'true');
  await expect(center).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('roadmap')).toHaveCount(1);
  await expect(page.getByTestId('roadmap')).toHaveAttribute('data-project', 'center');
});

test('«Вопросы»: источник и канал — выбором подряд; оба в адресе и на экране', async ({ page }) => {
  test.slow();
  await page.goto('/questions');
  const cards = page.getByTestId('question');
  await expect(cards).toHaveCount(4);
  const source = page.getByTestId('filter-source');
  const channel = page.getByTestId('filter-channel');

  await source.selectOption('trend-hunter');
  await channel.selectOption('example-film');
  await expect.poll(() => search(page)).toEqual({ source: 'trend-hunter', channel: 'example-film' });
  await expect(source).toHaveValue('trend-hunter');
  await expect(channel).toHaveValue('example-film');
  await expect(cards).toHaveCount(1);
  await expect(cards).toHaveAttribute('data-qid', 'Q9');

  // В обратном порядке: сначала канал, потом источник.
  await channel.selectOption('example-tech');
  await source.selectOption('footage-indexer');
  await expect
    .poll(() => search(page))
    .toEqual({ source: 'footage-indexer', channel: 'example-tech' });
  await expect(source).toHaveValue('footage-indexer');
  await expect(channel).toHaveValue('example-tech');
  await expect(cards).toHaveCount(1);
  await expect(cards).toHaveAttribute('data-qid', 'Q8');

  // И снять оба подряд — адрес пустой, на экране снова все открытые.
  await source.selectOption('');
  await channel.selectOption('');
  await expect(page).toHaveURL(/\/questions$/);
  await expect(source).toHaveValue('');
  await expect(channel).toHaveValue('');
  await expect(cards).toHaveCount(4);
});

test('«Статистика»: ролик, затем день — щелчками подряд; оба в адресе и на экране', async ({
  page,
}) => {
  test.slow();
  await page.goto('/stats');
  const videos = page.getByTestId('stats-videos');
  await expect(videos.getByTestId('stats-video')).toHaveCount(8);
  const summary = page.getByTestId('stats-summary');
  const day = summary.getByTestId('summary-day');
  await expect(summary.getByTestId('summary-counts')).toBeVisible();
  const heated = videos.locator('[data-video="hR4c9xQe1aA"]');
  const detail = page.getByTestId('stats-video-detail');

  // Ссылка ролика и сразу день — без ожидания экрана между ними.
  await heated.getByRole('link', { name: 'Rink rivals' }).click();
  await day.selectOption('2026-10-08');
  await expect.poll(() => search(page)).toEqual({ video: 'hR4c9xQe1aA', day: '2026-10-08' });
  await expect(heated).toHaveAttribute('aria-current', 'true');
  await expect(detail.getByRole('heading', { name: 'Rink rivals' })).toBeVisible();
  await expect(day).toHaveValue('2026-10-08');
  await expect(summary).toContainText('Сводка аналитика · за 08.10');

  // В обратном порядке, строкой: сначала день, потом другой ролик.
  const young = videos.locator('[data-video="sN7gWz4oPc2"]');
  await day.selectOption('2026-10-07');
  await young.click();
  await expect.poll(() => search(page)).toEqual({ video: 'sN7gWz4oPc2', day: '2026-10-07' });
  await expect(young).toHaveAttribute('aria-current', 'true');
  await expect(heated).not.toHaveAttribute('aria-current', 'true');
  await expect(day).toHaveValue('2026-10-07');
  await expect(summary).toContainText('Сводка аналитика · за 07.10');

  // История — как раньше: каждый выбор — свой шаг «назад».
  await page.goBack();
  await expect.poll(() => search(page)).toEqual({ video: 'hR4c9xQe1aA', day: '2026-10-07' });
  await page.goBack();
  await expect.poll(() => search(page)).toEqual({ video: 'hR4c9xQe1aA', day: '2026-10-08' });
});
