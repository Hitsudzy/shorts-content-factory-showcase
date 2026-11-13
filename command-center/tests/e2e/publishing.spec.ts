// «Публикация» (CC-0067): таб ведёт на экран, лента слотов на 14 дней, карточка для Studio —
// «скопировать» мышью и с клавиатуры (буфер обмена и тост), выбор слота в адресе, холды и
// переключатель только чтением (ни одного не-GET запроса, пока ничего не записано), подсказки
// тултипами, телефон без прокрутки вбок. Записи — tests/e2e/publishing-writes.spec.ts.
// Подставной API — src/mocks/publish.ts.
import type { Page } from '@playwright/test';

import { NOT_READY, READY, SCIENCE } from '../../src/mocks/publish';
import { expect, noSideScroll, openTip, test } from './fixtures';

test.use({ permissions: ['clipboard-read', 'clipboard-write'] });

const clipboard = (page: Page) => page.evaluate(() => navigator.clipboard.readText());

/** Методы запросов к API публикации за тест: экран только читает. */
function publishMethods(page: Page): string[] {
  const seen: string[] = [];
  page.on('request', (r) => {
    if (new URL(r.url()).pathname.includes('/api/publish')) seen.push(r.method());
  });
  return seen;
}

test.describe('публикация', () => {
  test('таб, лента на 14 дней, карточка ближайшего ролика, копирование', async ({ page }) => {
    const methods = publishMethods(page);
    await page.goto('/');
    await page
      .getByRole('navigation', { name: 'Разделы' })
      .getByRole('link', { name: 'Публикация' })
      .click();
    await expect(page.getByRole('heading', { level: 1, name: 'Публикация' })).toBeVisible();
    await expect(page.getByText(/Скоро · версия/)).toHaveCount(0);

    const feed = page.getByTestId('slot-feed');
    await expect(feed.getByTestId('slot')).toHaveCount(14);
    await expect(feed.locator(`[data-testid="slot"][data-slug="${READY}"]`)).toHaveAttribute(
      'data-state',
      'готов',
    );
    await expect(feed.locator('[data-state="ближайший свободный"]')).toHaveCount(1);

    const card = page.getByTestId('studio-card');
    await expect(card).toHaveAttribute('data-slug', READY);
    await expect(card.getByRole('heading', { level: 2 })).toContainText('Vanguards: Doomsday');

    await card.getByRole('button', { name: 'Скопировать: Название' }).click();
    await expect(page.getByTestId('toast')).toHaveText('Скопировано: Название');
    expect(await clipboard(page)).toBe(
      'Vanguards: Doomsday Moved Again — The Date Zenith Picked Says a Lot #shorts',
    );

    // С клавиатуры: фокус на «Дата», Tab к «Время», Enter.
    await card.getByRole('button', { name: 'Скопировать: Дата' }).focus();
    await page.keyboard.press('Tab');
    await expect(card.getByRole('button', { name: 'Скопировать: Время' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('toast')).toHaveText('Скопировано: Время');
    expect(await clipboard(page)).toBe('01:00');
    await expect(card.getByRole('button', { name: 'Скопировать: Время' })).toHaveAttribute(
      'data-copied',
      '1',
    );

    await openTip(
      page,
      card.getByRole('button', { name: 'Скопировать: Часовой пояс' }),
      'пояс компьютера',
    );
    expect(methods.length).toBeGreaterThan(0);
    expect(methods.every((m) => m === 'GET')).toBe(true);
  });

  test('CC-0142: пустые дни у ленты и «журнала загрузок нет»', async ({ page, publish }) => {
    await page.goto('/publishing');
    const feed = page.getByTestId('slot-feed');
    const warn = page.getByTestId('journal-missing');
    // Подставная ExampleFilm: свободны 14.10 и 16–23.10 (сегодняшний 10.10 уже прошёл).
    const line = feed.getByTestId('empty-days');
    await expect(line).toHaveAttribute('data-count', '9');
    await expect(line).toHaveText(/^Пустых дней за 2\sнедели: 9\s— 14\.10, 16\.10, .*23\.10$/);
    await expect(warn).toHaveCount(0);

    // Свободные дни заняты роликами с карточками, журнала загрузок нет: предупреждение одно,
    // про фабрику — над каналами, не в ленте (CC-0148).
    publish.fillReelDays();
    publish.state.journalMissing = true;
    await page.reload();
    await expect(line).toHaveText(/^Пустых дней за 2\sнедели нет$/);
    await expect(warn).toHaveText(/^Журнала загрузок нет\s— фабрика не видит, что уже выложено$/);
    await expect(warn).toHaveCount(1);
    await expect(feed.getByTestId('journal-missing')).toHaveCount(0);
    await expect(page.getByTestId('publish-channels').getByTestId('journal-missing')).toHaveCount(
      0,
    );

    // Канал без слота — строки пустых дней нет; предупреждение про фабрику — то же, одно.
    await page.goto(`/publishing?channel=${SCIENCE}`);
    await expect(feed.getByText('У канала нет слота публикации')).toBeVisible();
    await expect(feed.getByTestId('empty-days')).toHaveCount(0);
    await expect(warn).toHaveCount(1);
  });

  test('CC-0149: у канала нет записей в журнале загрузок — приглушённая строка в ленте', async ({
    page,
    publish,
  }) => {
    const feed = page.getByTestId('slot-feed');
    const line = feed.getByTestId('journal-no-rows');
    // У Reel строки в журнале есть — строки нет.
    await page.goto('/publishing');
    await expect(feed.getByTestId('empty-days')).toBeVisible();
    await expect(line).toHaveCount(0);

    // У Science (журнал есть, строк канала нет) — одна приглушённая строка.
    await page.goto(`/publishing?channel=${SCIENCE}`);
    await expect(feed.getByText('У канала нет слота публикации')).toBeVisible();
    await expect(line).toHaveText('У канала ещё нет записей в журнале загрузок');
    await expect(line).toHaveClass(/text-muted-foreground/);
    await expect(page.getByTestId('journal-missing')).toHaveCount(0);

    // Журнала нет вовсе — говорит плашка над каналами, у канала строки нет.
    publish.state.journalMissing = true;
    await page.reload();
    await expect(page.getByTestId('journal-missing')).toHaveCount(1);
    await expect(feed.getByText('У канала нет слота публикации')).toBeVisible();
    await expect(line).toHaveCount(0);
  });

  test('выбор слота — в адресе; неготовая карточка — отказом словами', async ({ page }) => {
    await page.goto('/publishing');
    const row = page.locator(`[data-testid="slot"][data-slug="${NOT_READY}"]`);
    await expect(row).toHaveAttribute('data-state', 'не готов');
    await openTip(page, row.locator('[data-slot="status"]'), 'Карточка не готова');
    await row.getByRole('link').click();
    await expect(page).toHaveURL(new RegExp(`slot=2026-10-15%2F${NOT_READY}`));
    const card = page.getByTestId('studio-card');
    await expect(card.getByTestId('studio-refusal')).toContainText('Поля для Studio не готовы');
    // Пути — только под «подробнее».
    await expect(card.getByText(/publish\/example-film/).first()).toBeHidden();
    await card.getByText('Подробнее', { exact: true }).last().click();
    await expect(card.getByText(/карточка: publish\/example-film\/2026-10-15/)).toBeVisible();
    // Переход по адресу открывает тот же слот.
    await page.reload();
    await expect(page.getByTestId('studio-card')).toHaveAttribute('data-slug', NOT_READY);
  });

  test('холды и состояние канала — подсказки тултипами, записи свёрнуты', async ({ page }) => {
    await page.goto('/publishing');
    const holds = page.getByTestId('holds');
    await expect(holds.getByTestId('hold')).toHaveCount(2);
    await openTip(page, holds.getByText('холд', { exact: true }).first(), 'пока его не снимут');
    const status = page.getByTestId('channel-status');
    await expect(status.getByTestId('state-pause')).toContainText('идут');
    await expect(status.getByTestId('state-api-upload')).toContainText('выключена');
    await expect(status.getByTestId('api-warnings')).toBeVisible();
    // Подпись холда (CC-0071), записи паузы, ротации (CC-0068) и переключателя API-загрузки
    // (CC-0069) — свёрнуты, пока их не раскрыть.
    await expect(holds.getByTestId('hold-sign-form')).toHaveCount(0);
    await expect(status.getByTestId('switch-on-form')).toHaveCount(0);
    await expect(status.getByTestId('pause-set-form')).toHaveCount(0);
    // История переключателя (CC-0141): свёрнута; раскрыта — новые сверху, кто словами.
    const history = status.getByTestId('switch-history');
    await expect(history.getByTestId('switch-history-row').first()).toBeHidden();
    await history.getByText('История переключений').click();
    const rows = history.getByTestId('switch-history-row');
    await expect(rows).toHaveCount(3);
    await expect(rows.first()).toContainText('03.10, 19:45 · вы, из центра · выключена');
    await expect(rows.nth(1)).toContainText('включена · предупреждений: 2');

    await page
      .getByTestId('publish-channels')
      .getByRole('link', { name: /ExampleScience/ })
      .click();
    await expect(page).toHaveURL(new RegExp(`channel=${SCIENCE}`));
    await expect(status.getByTestId('state-pause')).toContainText('на паузе');
    await expect(status.getByTestId('switch-history-empty')).toHaveText('переключений не было');
    await expect(page.getByTestId('studio-card')).toContainText('Ролик не выбран');
  });

  // CC-0139: одна сетка у занятых и свободных строк — названия с одной линии, день над временем,
  // значок по правому краю (на телефоне — под названием, без наезда).
  for (const [device, size] of [
    ['компьютер', { width: 1280, height: 800 }],
    ['телефон', { width: 375, height: 812 }],
  ] as const) {
    test(`лента: строки на одной сетке, день над временем — ${device}`, async ({ page }) => {
      await page.setViewportSize(size);
      await page.goto('/publishing');
      const rows = page.getByTestId('slot-feed').getByTestId('slot');
      await expect(rows).toHaveCount(14);
      const box = async (row: number, id: string) => {
        const b = await rows.nth(row).getByTestId(id).boundingBox();
        expect(b, `${id} в строке ${row}`).not.toBeNull();
        return b!;
      };
      const states = await rows.evaluateAll((els) =>
        els.map((e) => (e as HTMLElement).dataset.slug ?? ''),
      );
      expect(
        states.some((s) => s),
        'есть занятые строки',
      ).toBe(true);
      expect(
        states.some((s) => !s),
        'есть свободные строки',
      ).toBe(true);
      const titleX = new Set<number>();
      const subX = new Set<number>();
      const stateRight = new Set<number>();
      for (let i = 0; i < 14; i++) {
        const day = await box(i, 'slot-day');
        const time = await box(i, 'slot-time');
        const title = await box(i, 'slot-title');
        const sub = await box(i, 'slot-sub');
        const state = await box(i, 'slot-state');
        expect(time.y, 'время под днём').toBeGreaterThanOrEqual(day.y + day.height - 1);
        expect(Math.abs(title.y - day.y), 'строки выровнены по верху').toBeLessThan(4);
        titleX.add(Math.round(title.x));
        subX.add(Math.round(sub.x));
        stateRight.add(Math.round(state.x + state.width));
        // Значок не наезжает на название и подпись.
        const overlap =
          state.x < title.x + title.width &&
          state.y < sub.y + sub.height &&
          state.x + state.width > title.x &&
          state.y + state.height > title.y;
        expect(overlap, `значок поверх текста в строке ${i}`).toBe(false);
        if (size.width < 640) expect(Math.round(state.x)).toBe(Math.round(title.x));
      }
      expect([...titleX], 'названия с одной линии').toHaveLength(1);
      expect([...subX], 'подписи с одной линии').toHaveLength(1);
      if (size.width >= 640) expect([...stateRight], 'значки по одному краю').toHaveLength(1);
      await expect(rows.first().getByTestId('slot-time')).toHaveText(/^\d{2}:\d{2} МСК$/);
      await noSideScroll(page);
    });
  }

  test('телефон: экран без прокрутки вбок', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/publishing');
    await expect(page.getByTestId('slot-feed').getByTestId('slot')).toHaveCount(14);
    await expect(page.getByTestId('studio-card')).toHaveAttribute('data-slug', READY);
    await expect(page.getByTestId('studio-field').first()).toBeVisible();
    await noSideScroll(page);
  });
});
