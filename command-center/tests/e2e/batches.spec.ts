// Экран «Батчи» (а) на подставном расписании (src/mocks/schedule.ts): план недели, рубильник
// с заметкой и отказ без неё, окна каналов — сохранение, 422, «ничего не поменялось», телефон.
import type { Page } from '@playwright/test';

import { NOTE_REQUIRED } from '../../src/mocks/schedule';
import { expect, onlyHttp, openTip, test } from './fixtures';

const noHorizontalScroll = async (page: Page) => {
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(doc.scroll, 'горизонтальная прокрутка страницы').toBeLessThanOrEqual(doc.width);
};

test('таб «Батчи» → план недели: дни, окна, оценки с пометкой, каналы вне плана', async ({
  page,
}) => {
  await page.goto('/');
  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Батчи' })
    .click();
  await expect(page.getByRole('heading', { level: 1, name: 'Батчи' })).toBeVisible();
  // Экран собран целиком (CC-0050…0052): мест «скоро» на нём больше нет.
  await expect(page.getByTestId('batches-actions')).toBeVisible();
  await expect(page.getByRole('main').getByText(/Скоро · версия/)).toHaveCount(0);
  await expect(page.getByTestId('batches-live')).toContainText('Идёт сейчас');
  await expect(page.getByTestId('batches-actions')).toContainText('Запуск вручную');

  const plan = page.getByTestId('week-plan');
  await expect(plan.locator('[data-status]')).toHaveCount(7);
  await expect(page.getByTestId('day-2026-10-10')).toHaveAttribute('data-status', 'done');
  await expect(page.getByTestId('day-2026-10-10')).toContainText('сегодня');
  const planned = page.getByTestId('day-2026-10-12');
  await expect(planned).toHaveAttribute('data-status', 'planned');
  await expect(planned.getByTestId('day-window')).toHaveText('окно 02:00–05:00 МСК');
  // Причина дня — словами (CC-0146): строки фабрики и заметки — только под «Подробнее».
  await expect(plan).toContainText(
    'План на 7 дней · не больше одного батча в сутки на всю фабрику',
  );
  // «Сутки» фабрики — сутки квоты поиска YouTube (CF-0787): когда обновится — по МСК.
  await expect(page.getByTestId('day-2026-10-10').getByTestId('day-why')).toHaveText(
    'Батч в эти сутки квоты уже был — следующие начнутся 11.10, 10:00 МСК',
  );
  // CC-0147: окна 11.10 (02:00 и 05:30 МСК) ещё в сутках квоты 10.10, их уже взял батч —
  // «квота занята» (не «батч был»: батча в этот день не было), причина словами и следующее окно канала по МСК; что такое квота — в подсказке.
  const taken = page.getByTestId('day-2026-10-11');
  await expect(taken).toHaveAttribute('data-kind', 'quota_day_taken');
  await expect(taken).toHaveAttribute('data-status', 'done');
  await expect(taken.getByTestId('day-why')).toHaveText(
    'Эти сутки квоты поиска YouTube уже занял прошлый батч — второй не запускается. Следующее окно: ExampleFilm 12.10, 02:00 МСК',
  );
  expect(await taken.getByTestId('day-next').textContent()).toBe(
    '. Следующее окно: ExampleFilm 12.10,\u00a002:00\u00a0МСК',
  );
  await openTip(page, taken.getByText('квота занята', { exact: true }), '100 поисков в сутки');
  await expect(taken.getByText('батч был', { exact: true })).toHaveCount(0);
  // 13.10 и 14.10 — батчи разных каналов (слоты у каждого свои): имя канала у метки дня.
  await expect(page.getByTestId('day-2026-10-13')).toContainText('ExampleFilm');
  await expect(page.getByTestId('day-2026-10-14')).toContainText('ExampleTech');
  // CC-0147: день с батчем — первый пустой слот ленты (`first_empty_slot`) и дни роликов.
  await expect(planned.getByTestId('day-why')).toHaveText(
    'Публикаций на 3 дня вперёд не хватает — нужен батч. Первый пустой слот: 12.10, 18:00 МСК. Ролики встанут в слоты 12.10–14.10',
  );
  await expect(planned).toHaveAttribute('data-kind', 'needs_batch');
  // Оба канала на паузе 16.10 — «некого», заметки словами в причине, одна причина — один раз.
  const paused = page.getByTestId('day-2026-10-16');
  await expect(paused).toHaveAttribute('data-kind', 'nobody_available');
  await expect(paused.getByTestId('day-why')).toHaveText(
    'Некого планировать: ExampleFilm и ExampleTech на паузе до 17.10 (заметка: «меняю ключи YouTube»)',
  );
  await expect(paused.getByTestId('day-notes')).toHaveCount(0);
  await expect(paused.getByText('некого', { exact: true })).toBeVisible();
  await expect(page.getByTestId('day-2026-10-15').getByText('без батча')).toBeVisible();
  await expect(page.getByTestId('day-2026-10-15').getByTestId('day-why')).toHaveText(
    'Публикаций хватает на 3 дня вперёд — батч не нужен',
  );
  // Тире не начинает строку, дата со временем не рвётся: неразрывные пробелы в самом тексте.
  expect(await planned.getByTestId('day-why').textContent()).toContain(
    'не хватает\u00a0— нужен батч. Первый пустой слот: 12.10,\u00a018:00\u00a0МСК. Ролики встанут в\u00a0слоты 12.10–14.10',
  );
  await expect(planned.getByTestId('day-factory')).toBeHidden();
  await expect(plan.getByText(/дн\.|≥/).filter({ visible: true })).toHaveCount(0);
  const notes = page.getByTestId('day-2026-10-12').getByTestId('day-notes');
  await expect(notes).toBeHidden();
  await page.getByTestId('day-2026-10-12').getByText('Подробнее').click();
  await expect(notes).toContainText('батч не нужен');
  await openTip(page, planned.getByTestId('day-est-end'), 'Оценка по 5 прогонам');
  await openTip(page, planned.getByTestId('day-est-videos'), 'По умолчанию');
  // Сплошное подчёркивание — только у ссылок; у подсказок-оценок — серый пунктир.
  const lines = await plan.locator('*').evaluateAll((els) =>
    els
      .map((el) => ({ el, s: getComputedStyle(el) }))
      .filter(({ s }) => s.textDecorationLine.includes('underline'))
      .map(({ el, s }) => ({
        tag: el.tagName,
        style: s.textDecorationStyle,
        same: s.textDecorationColor === s.color,
      })),
  );
  expect(lines.filter((l) => l.style === 'solid').every((l) => l.tag === 'A')).toBe(true);
  const dotted = lines.filter((l) => l.style === 'dotted');
  expect(dotted.length).toBeGreaterThan(0);
  expect(dotted.every((l) => l.tag !== 'A' && !l.same)).toBe(true);
  // Вне расписания (CC-0140): ExampleTech в плане — берёт свои дни; ExampleScience план не
  // называет — строка с причиной словами, ссылка ведёт к окну канала на этой же странице.
  await expect(page.getByTestId('day-2026-10-12')).toContainText('ExampleTech');
  await expect(page.getByTestId('why-not-example-tech')).toHaveCount(0);
  const science = page.getByTestId('why-not-example-science');
  await expect(science).toContainText('ExampleScience — вне расписания: нет слота публикации');
  await expect(science.getByText(/publisher\.slot/)).toBeHidden();
  await science.getByTestId('why-not-window').click();
  await expect(page.getByTestId('window-example-science')).toBeFocused();
  await expect(page.getByTestId('window-example-science')).toBeInViewport();
  await expect(page.getByTestId('switch-timer')).toContainText('не установлен');
  // Строка таймера с путём — только под «подробнее».
  await expect(page.getByText(/LaunchAgents/)).toBeHidden();
});

test.describe('ожидаемые отказы фабрики (422 в консоли браузера)', () => {
  test.use({ expectCleanConsole: false });

  test('рубильник: без заметки — отказ фабрики как есть, с заметкой — включено, потом выключено', async ({
    page,
    schedule,
    consoleErrors,
  }) => {
    await page.goto('/batches');
    await expect(page.getByTestId('header-switch')).toHaveText('Рубильник: выключено');

    await page.getByTestId('switch-toggle').click();
    const dialog = page.getByRole('alertdialog', { name: 'Включить расписание?' });
    await expect(dialog).toBeVisible();
    await dialog.getByRole('button', { name: 'Включить' }).click();
    await expect(dialog.getByTestId('refusal-message')).toHaveText(NOTE_REQUIRED);
    await expect(dialog).toBeVisible();
    expect(schedule.writes).toEqual([]);

    await dialog.getByTestId('switch-note-input').fill('в чате 10.10 вечером сказал «включай»');
    await dialog.getByRole('button', { name: 'Включить' }).click();
    await expect(dialog.getByRole('button', { name: 'Включаю…' })).toBeVisible();
    await expect(dialog).toBeHidden();
    expect(schedule.writes).toEqual([
      { kind: 'switch', body: { on: true, note: 'в чате 10.10 вечером сказал «включай»' } },
    ]);
    await expect(page.getByTestId('header-switch')).toHaveText('Рубильник: включено');
    await expect(page.getByTestId('switch-note')).toContainText('сказал «включай»');
    await expect(page.getByTestId('switch-since')).toContainText('вы');

    // «Отмена» ничего не пишет; выключение — без заметки.
    await page.getByTestId('switch-toggle').click();
    const off = page.getByRole('alertdialog', { name: 'Выключить расписание?' });
    await off.getByRole('button', { name: 'Отмена' }).click();
    await expect(off).toBeHidden();
    expect(schedule.writes).toHaveLength(1);
    await page.getByTestId('switch-toggle').click();
    await off.getByRole('button', { name: 'Выключить' }).click();
    await expect(off).toBeHidden();
    expect(schedule.writes.at(-1)).toEqual({ kind: 'switch', body: { on: false, note: null } });
    await expect(page.getByTestId('header-switch')).toHaveText('Рубильник: выключено');
    onlyHttp(consoleErrors, 422);
  });

  test('окно канала: сохранение, «ничего не поменялось», 422 фабрики как есть', async ({
    page,
    schedule,
    consoleErrors,
  }) => {
    await page.goto('/batches');
    const card = page.getByTestId('window-example-film');
    await expect(card.getByTestId('win-window')).toHaveValue('02:00');

    await card.getByTestId('win-window').fill('03:30');
    await card.getByTestId('win-note').fill('позже ночью');
    const put = page.waitForRequest(
      (r) => r.method() === 'PUT' && r.url().endsWith('/api/schedule/channels/example-film'),
    );
    await card.getByTestId('win-save').click();
    const req = await put;
    expect(req.postDataJSON()).toEqual({
      enabled: true,
      window: '03:30',
      window_hours: 3,
      min_feed_days: 3,
      note: 'позже ночью',
    });
    expect(req.headers()['x-cc-session']).toBe('test-session-token');
    await expect(card.getByTestId('win-saved')).toContainText('начало окна: 02:00 → 03:30');
    // План пересчитан: окно дня — с новым началом.
    await expect(page.getByTestId('day-2026-10-12').getByTestId('day-window')).toHaveText(
      'окно 03:30–06:30 МСК',
    );
    await card.getByText('Подробнее').click();
    await expect(card.getByTestId('win-source')).toContainText('пульт');
    await expect(card.getByTestId('win-overlay')).toContainText('{"window":"03:30"}');

    await card.getByTestId('win-save').click();
    await expect(card.getByTestId('win-unchanged')).toHaveText(
      'Ничего не поменялось: значения те же, запись не сделана.',
    );
    expect(schedule.writes.filter((w) => w.kind === 'settings')).toHaveLength(1);

    await card.getByTestId('win-feed').fill('2.5');
    await card.getByTestId('win-save').click();
    await expect(card.getByTestId('refusal-message')).toHaveText(
      'Настройка не принята: порог ленты 2.5: целое число дней от 1 до 30',
    );
    await expect(card.getByTestId('win-feed')).toHaveValue('2.5');
    await card.getByRole('button', { name: 'Вернуть как было' }).click();
    await expect(card.getByTestId('win-feed')).toHaveValue('3');
    await expect(card.getByTestId('refusal-message')).toBeHidden();
    onlyHttp(consoleErrors, 422);
  });
});

test('ветки дня из `kind` (CC-0147): идёт батч, окна сегодня прошли, планировать некого', async ({
  page,
  schedule,
}) => {
  schedule.setRunning({ channel: 'example-tech', id: '2026-10-10T0230Z' });
  await page.goto('/batches');
  const today = page.getByTestId('day-2026-10-10');
  await expect(today).toHaveAttribute('data-kind', 'running');
  await expect(today.getByTestId('day-why')).toHaveText(
    'Идёт батч — второй в этот день не запускается',
  );

  schedule.setRunning(null);
  schedule.setDoneToday(false);
  await page.reload();
  await expect(today).toHaveAttribute('data-kind', 'nobody_available');
  await expect(today.getByTestId('day-why')).toHaveText(
    'Некого планировать: у ExampleFilm и ExampleTech окна на сегодня уже прошли',
  );

  schedule.save('example-film', { enabled: false });
  schedule.save('example-tech', { enabled: false });
  await page.reload();
  const plan = page.getByTestId('week-plan');
  await expect(plan.locator('[data-kind="nobody_plannable"]')).toHaveCount(7);
  await expect(today.getByTestId('day-why')).toHaveText(
    'Некого планировать: ни у одного канала нет слота и плана запуска',
  );
});

test('снять канал с расписания: план говорит почему', async ({ page }) => {
  await page.goto('/batches');
  const card = page.getByTestId('window-example-film');
  await card.getByTestId('win-enabled').uncheck();
  await card.getByTestId('win-save').click();
  await expect(card.getByTestId('win-saved')).toContainText('участие в расписании: да → нет');
  await expect(page.getByTestId('why-not-example-film')).toContainText(
    'ExampleFilm — вне расписания: расписание батчей канала выключено',
  );
  await page.getByTestId('why-not-example-film').getByText('Подробнее').click();
  await expect(page.getByTestId('why-not-example-film')).toContainText('не участвует в расписании');
  await expect(page.getByTestId('day-2026-10-11')).toHaveAttribute('data-status', 'idle');
});

test('телефон: без горизонтальной прокрутки на плане, окнах и в окне подтверждения', async ({
  page,
  schedule,
}) => {
  schedule.setStaleOpen(['example-film 2026-10-08T0205Z']);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  await expect(page.getByTestId('stale-open')).toBeVisible();
  await expect(page.getByTestId('window-example-tech').getByTestId('win-window')).toBeVisible();
  await noHorizontalScroll(page);
  for (const c of await page.locator('[data-testid^="window-"]').all()) {
    const box = (await c.boundingBox())!;
    expect(box.x + box.width).toBeLessThanOrEqual(390);
  }
  await page.getByTestId('switch-toggle').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  const box = (await dialog.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  await noHorizontalScroll(page);
});
