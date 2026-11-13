// Экран «Батчи» (б) на подставных батчах (src/mocks/batches.ts): идущий батч с ходом,
// курсор событий (`more`/`reset`), опрос стоит на скрытой вкладке и после ухода со страницы,
// остановленная пересборка в списке, история с раскрытием и хвостом журнала, главная, телефон.
import type { Page } from '@playwright/test';

import {
  type BatchesBackend,
  FAILED_AT_START_STAGES,
  ORDER,
  PAST,
  PAST_REBUILD,
  RUNNING,
  STOPPED,
} from '../../src/mocks/batches';
import { isConditional, KINDS } from '../../src/pages/batches/stages';
import { expect, openTip, test } from './fixtures';

const noHorizontalScroll = async (page: Page) => {
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(doc.scroll, 'горизонтальная прокрутка страницы').toBeLessThanOrEqual(doc.width);
};

/** Кадров у ленты идущего батча: в плане мока — все виды кадров (CC-0090). */
const FRAMES_N = Object.keys(KINDS).length;
/** Стадии, которые прошлый прогон мока запускал: без резерва и добора. */
const RAN = ORDER.filter((id) => !isConditional(id));

const card = (page: Page, batch: string) =>
  page.locator(`[data-testid="open-batch"][data-batch="${batch}"]`);

/**
 * Закрыть идущие батчи, пока ни одна страница их не опрашивает (CC-0159). Если закрыть при
 * открытых «Батчах» или главной, очередной опрос идущего (`…/footage`) успевает получить 404
 * до перехода — браузер пишет его в консоль, и тест падает на «ошибке в консоли».
 */
async function closeAway(page: Page, batches: BatchesBackend) {
  await page.goto('about:blank');
  batches.closeAll();
}

/** Вкладка «скрыта» / «видна» — как её видит TanStack Query (visibilitychange). */
const setHidden = (page: Page, hidden: boolean) =>
  page.evaluate((h) => {
    Object.defineProperty(document, 'visibilityState', {
      configurable: true,
      get: () => (h ? 'hidden' : 'visible'),
    });
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => h });
    document.dispatchEvent(new Event('visibilitychange'));
  }, hidden);

test('идущий батч: кинолента, стадия с потолком, оценка конца с тултипом, процессы', async ({
  page,
}) => {
  await page.goto('/batches');
  const c = card(page, RUNNING);
  await expect(c.getByRole('heading', { name: 'ExampleFilm' })).toBeVisible();
  await expect(c.getByTestId('batch-status')).toHaveText('идёт');
  const frames = c.getByTestId('film-strip').locator('li');
  await expect(frames).toHaveCount(FRAMES_N);
  await expect(frames.nth(5)).toHaveAttribute('data-state', 'now');
  await expect(frames.nth(5)).toContainText('Монтаж');
  await expect(frames.nth(5)).toContainText('идёт 20 мин из 1 ч 30 мин');
  await expect(frames.nth(5).locator('i')).toHaveAttribute('style', /width: 22%/);
  await expect(frames.nth(6)).toHaveAttribute('data-state', 'wait');
  await expect(frames.nth(3)).toHaveAttribute('data-state', 'unneeded');
  await expect(frames.nth(3)).toContainText('не понадобился');
  await openTip(page, c.getByTestId('batch-eta'), 'Оценка по 5 прогонам');
  await openTip(page, c.getByTestId('stage-clock'), 'Потолок стадии');
  await expect(c.getByTestId('batch-eta')).toHaveText('осталось ≈ 1 ч');
  await expect(c.getByTestId('needs-human')).toContainText('Студия канала давно не читалась');
  await expect(c.getByTestId('batch-questions')).toContainText('ждёт ответа');
  await expect(c.locator('[data-testid="process"][data-alive="true"]')).toContainText('работает');
  // pid и пути — только под «подробнее».
  await expect(c.getByText(/pid 4188/)).toBeHidden();
  await expect(page.getByTestId('going-fresh')).toContainText('проверено');
});

test('события по курсору: хвост, more — дочитывает сразу, reset — заново; в памяти ≤ 500', async ({
  page,
  batches,
}) => {
  await page.goto('/batches');
  const feed = card(page, RUNNING).getByTestId('events-feed');
  await expect(feed.getByTestId('event-line')).toHaveCount(30);
  expect(batches.eventCalls[0]).toBeNull();

  // 450 новых строк — больше лимита страницы (200): фабрика говорит more, центр спрашивает
  // сразу, не дожидаясь трёх секунд.
  batches.append(RUNNING, 450);
  await expect(feed.getByTestId('events-count')).toHaveText(
    'Показаны последние 100 из 480 строк в памяти',
    { timeout: 15_000 },
  );
  const afters = batches.eventCalls.filter((a): a is number => a != null);
  expect(new Set(afters).size, 'каждый опрос — с нового курсора').toBe(afters.length);

  batches.append(RUNNING, 100);
  await expect(feed.getByTestId('events-count')).toContainText('из 500 строк в памяти', {
    timeout: 15_000,
  });
  await expect(feed.getByTestId('events-count')).toContainText('старше выброшены');

  // Файл заменён коротким: курсор за концом → reset → лента — хвост нового файла.
  batches.replace(RUNNING, 3);
  await expect(feed.getByTestId('events-reset')).toBeVisible({ timeout: 15_000 });
  await expect(feed.getByTestId('event-line')).toHaveCount(3);
  await expect(feed.getByTestId('event-line').first()).toContainText('(новый файл)перезапуск');
  // Код итога и слаги — под «подробнее» (CC-0118).
  await expect(feed.getByTestId('event-line').first()).not.toContainText('restart');
});

test('опрос стоит на скрытой вкладке и после ухода со страницы', async ({ page, batches }) => {
  await page.goto('/batches');
  await expect(card(page, RUNNING).getByTestId('event-line')).toHaveCount(30);
  await expect.poll(() => batches.eventCalls.length, { timeout: 10_000 }).toBeGreaterThan(1);

  await setHidden(page, true);
  await page.waitForTimeout(500);
  const hidden = batches.eventCalls.length;
  await page.waitForTimeout(7_000);
  expect(batches.eventCalls.length, 'опрос на скрытой вкладке').toBe(hidden);

  await setHidden(page, false);
  await expect.poll(() => batches.eventCalls.length, { timeout: 10_000 }).toBeGreaterThan(hidden);

  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Каналы' })
    .click();
  await expect(page.getByRole('heading', { level: 1, name: 'Каналы' })).toBeVisible();
  await page.waitForTimeout(500);
  const left = batches.eventCalls.length;
  await page.waitForTimeout(7_000);
  expect(batches.eventCalls.length, 'опрос после ухода со страницы').toBe(left);
});

test('остановленная пересборка в списке: пометка, статус, причина, остановка, без оценки', async ({
  page,
}) => {
  await page.goto('/batches');
  const c = card(page, STOPPED);
  await expect(c).toBeVisible();
  await expect(c.locator('.eyebrow').first()).toHaveText('Пересборка');
  await expect(c.getByText('пересборка', { exact: true })).toBeVisible(); // метка
  await expect(c.getByRole('heading', { name: 'ExampleTech' })).toBeVisible();
  await expect(c.getByTestId('batch-status')).toHaveText('остановлен');
  await expect(c.getByTestId('film-strip').locator('li').nth(5)).toHaveAttribute(
    'data-state',
    'stopped',
  );
  // У остановленного кадра — «остановлено», а не «идёт 2 ч 40 мин из …» (CC-0095).
  await expect(c.getByTestId('film-strip').locator('li').nth(5).locator('small')).toHaveText(
    'остановлено',
  );
  await expect(c.getByTestId('batch-elapsed')).toHaveCount(0);
  await expect(c.getByTestId('halt-reason')).toContainText('ждёт «продолжить»');
  await expect(c.getByTestId('batch-eta')).toHaveCount(0);
  await expect(c.getByTestId('batch-stops')).toContainText('Остановлен 10.10, 07:30 — вы');
  await expect(c.getByTestId('batch-rebuild')).toContainText('Перемонтаж батча от 08.10, 05:00');
  // Лента остановленного батча закрыта и не опрашивается; открыть — спросит хвост.
  const feed = c.getByTestId('events-feed');
  await expect(feed).not.toHaveAttribute('open');
  await feed.locator('summary').click();
  await expect(feed.getByTestId('event-line')).toHaveCount(8);
  // Адрес — поле batch (rebuilds/<ts>), не channel.
  await c.getByText('Подробнее', { exact: true }).last().click();
  await expect(c.getByText(`батч ${STOPPED}`)).toBeVisible();
});

test('дольше обычного и «сейчас батча нет»', async ({ page, batches }) => {
  batches.patch(RUNNING, { estimate: { mean_wall_s: 3600, runs: 3, left_s: -1500 } });
  await page.goto('/batches');
  await expect(card(page, RUNNING).getByTestId('batch-eta')).toHaveText(
    'дольше обычного на 25 мин',
  );
  await closeAway(page, batches);
  await page.goto('/batches');
  await expect(page.getByTestId('no-batch')).toContainText('Сейчас батча нет');
});

test('история: длительность, итог, кто запустил; раскрытие — стадии и хвост журнала', async ({
  page,
}) => {
  await page.goto('/batches');
  const hist = page.getByTestId('batch-history');
  const runs = hist.getByTestId('run');
  await expect(runs).toHaveCount(4);
  await expect(runs.getByTestId('run-by')).toHaveText([
    'таймер',
    'центр',
    'пульт',
    'вручную в чате',
  ]);
  await openTip(page, runs.nth(3).getByTestId('run-by'), 'запустили в чате');
  await expect(
    hist.locator(`[data-batch="${PAST_REBUILD}"]`).getByText('пересборка'),
  ).toBeVisible();

  const past = hist.locator(`[data-batch="${PAST}"]`);
  await expect(past.getByTestId('run-duration')).toHaveText('2 ч 24 мин');
  await expect(past.getByTestId('run-outcome')).toHaveText('готово: 3 ролика');
  await past.getByRole('button', { expanded: false }).click();
  await expect(past.getByTestId('run-stage')).toHaveCount(RAN.length);
  await expect(past.getByTestId('run-stage').nth(RAN.indexOf('video-editor'))).toContainText(
    'Монтаж',
  );
  await past.locator('[data-testid="log-button"][data-log^="video-editor."]').click();
  await expect(past.getByTestId('log-tail-note')).toHaveText(
    /^Показан конец: последние 32\sКБ из \d+\sКБ$/,
  );
  await expect(past.getByTestId('log-tail').locator('pre')).toContainText('шаг 2000: WARN');
  // Журналы — словами, имя файла — под «подробнее» (ревью экранов).
  await expect(past.locator('[data-log="batch-start.s0.a0.log"]')).toHaveText(/^Старт батча/);
  for (const b of await past.getByTestId('log-button').all())
    await expect(b).not.toContainText('.log');
  await expect(past.getByTestId('run-stage').first()).not.toContainText('-');
  await past.locator('[data-testid="log-button"][data-log^="batch-start."]').click();
  await expect(past.getByTestId('log-tail-note')).toHaveText('Журнал целиком, 15 Б');
  await past.getByRole('button', { expanded: true }).click();
  await expect(past.getByTestId('run-stages')).toBeHidden();
});

test('футаж раньше исследования (как run_plan фабрики): номера кадров подряд, без перескока', async ({
  page,
  batches,
}) => {
  // Живой батч example-science/2026-10-12T2001Z: идёт footage-indexer, content-researcher ждёт.
  const order = [
    'studio-read-due',
    'rights-check',
    'batch-start',
    'pool-maintenance',
    'trend-hunter',
    'compliance-shortlist',
    'footage-indexer',
    'content-researcher',
    'footage-indexer-reserve',
    'content-researcher-reserve',
    'thin-pool-supplement',
    'plan-check-after-supplement',
    'compliance-scripts',
    'video-editor',
    'frame-judge',
    'batch-done',
    'monitors',
  ];
  const cur = order.indexOf('footage-indexer');
  batches.patch(RUNNING, {
    stages: order.map((id, i) => ({
      id,
      status: i < cur ? 'done' : i === cur ? 'running' : 'pending',
    })),
    stage: 'footage-indexer',
  });
  await page.goto('/batches');
  const frames = card(page, RUNNING).getByTestId('film-strip').locator('li');
  await expect(frames).toHaveCount(FRAMES_N);
  await expect(frames.nth(0)).toContainText('Тренды');
  await expect(frames.nth(1)).toContainText('Футаж');
  await expect(frames.nth(1)).toHaveAttribute('data-state', 'now');
  await expect(frames.nth(2)).toContainText('Исследование');
  await expect(frames.nth(2)).toHaveAttribute('data-state', 'wait');
  await expect(frames.nth(3)).toContainText('только если нужно');
  // Номера — подряд: 01 02 03 …, а не «01 тренды → 03 футаж».
  const nums = await frames.evaluateAll((li) =>
    li.map((x) => x.querySelector('span')?.textContent?.trim() ?? ''),
  );
  expect(nums).toEqual(Array.from({ length: FRAMES_N }, (_, i) => String(i + 1).padStart(2, '0')));
  await expect(card(page, RUNNING).getByTestId('batch-stage')).toContainText('Сейчас: Футаж');
});

test('упавший батч: пропущенное после падения — «не дошёл», серым и без ✓ (CC-0095)', async ({
  page,
  batches,
}) => {
  // Стадии — как у живого example-science/2026-10-12T1908Z: упал batch-start, остальное skipped.
  batches.patch(RUNNING, {
    status: 'failed',
    stages: FAILED_AT_START_STAGES,
    stage: null,
    next: null,
    halt_reason: null,
  });
  await page.goto('/batches');
  const c = card(page, RUNNING);
  await expect(c.getByTestId('batch-status')).toContainText('упал');
  const frames = c.getByTestId('film-strip').locator('li');
  await expect(frames).toHaveCount(FRAMES_N);
  const states = await frames.evaluateAll((li) => li.map((x) => x.getAttribute('data-state')));
  expect(states).toEqual([
    'bad',
    'unreached',
    'unreached',
    'unreached',
    'unreached',
    'unreached',
    'unreached',
    'bad',
  ]);
  await expect(frames.nth(1)).toContainText('не дошёл');
  await expect(frames.nth(3)).toContainText('не дошёл');
  // Упавший кадр — «ошибка», а не «идёт N из …» (у батча осталась оценка стадии из мока).
  await expect(frames.nth(0).locator('small')).toHaveText('ошибка');
  await expect(frames.nth(7).locator('small')).toHaveText('ошибка');
  await expect(c.getByTestId('film-strip')).not.toContainText('идёт');
  // Ни одного ✓: у «не дошёл» номер без галочки.
  await expect(frames.locator('[data-state="done"]')).toHaveCount(0);
  const mark = await frames
    .nth(1)
    .locator('span')
    .first()
    .evaluate((el) => getComputedStyle(el, '::after').content);
  expect(mark).not.toContain('✓');
  // На главной — та же лента.
  await page.goto('/');
  const home = page.getByTestId('batch-card').locator('ol > li');
  await expect(home.nth(1)).toHaveAttribute('data-state', 'unreached');
});

test('главная: блок «Батч» живой — кинолента идущего, ссылка в «Батчи»', async ({
  page,
  batches,
}) => {
  await page.goto('/');
  const c = page.getByTestId('batch-card');
  await expect(c).toHaveAttribute('data-state', 'going');
  await expect(c.getByRole('heading', { name: 'ExampleFilm' })).toBeVisible();
  await expect(c.locator('ol > li').nth(5)).toHaveAttribute('data-state', 'now');
  await expect(c.getByTestId('home-batch-eta')).toHaveText('осталось ≈ 1 ч');
  await expect(c.getByText(/Скоро/)).toHaveCount(0);
  await c.getByRole('link', { name: 'К батчам' }).click();
  await expect(page.getByRole('heading', { level: 1, name: 'Батчи' })).toBeVisible();

  await closeAway(page, batches);
  await page.goto('/');
  await expect(c.getByRole('heading', { name: 'Сейчас батча нет' })).toBeVisible();
  await expect(c.locator('ol > li')).toHaveCount(FRAMES_N);
});

test.describe('телефон', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('кинолента вертикальная, история с журналом — без горизонтальной прокрутки', async ({
    page,
  }) => {
    await page.goto('/batches');
    const frames = card(page, RUNNING).getByTestId('film-strip').locator('li');
    await expect(frames).toHaveCount(FRAMES_N);
    const [a, b] = await Promise.all([frames.nth(0).boundingBox(), frames.nth(1).boundingBox()]);
    expect(b!.y).toBeGreaterThan(a!.y + a!.height - 1);
    await expect(card(page, RUNNING).getByTestId('event-line').first()).toBeVisible();
    const past = page.getByTestId('batch-history').locator(`[data-batch="${PAST}"]`);
    await past.getByRole('button', { expanded: false }).click();
    await past.locator('[data-testid="log-button"][data-log^="video-editor."]').click();
    await expect(past.getByTestId('log-tail')).toBeVisible();
    await noHorizontalScroll(page);
    await page.goto('/');
    await expect(page.getByTestId('batch-card')).toHaveAttribute('data-state', 'going');
    await noHorizontalScroll(page);
  });
});
