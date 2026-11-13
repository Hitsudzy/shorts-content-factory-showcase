// CC-0027: экран «Уведомления и напоминания» на подставном API (src/mocks/notify.ts): таб и
// колокольчик → экран; журнал (сверху новые, фильтр, «показать все», ответы каналов в тултипе);
// напоминания (очередь, отмена погашена с подсказкой, «показать все»); «поставить напоминание» —
// план → «да» с отсчётом → итог, очередь перечитана; отказ «время не подходит»; «да» после сдвига
// времени — план заново сам; истёкший план; проверка каналов (строки фабрики как есть); пустые
// состояния; телефон 390 без прокрутки вбок; тренировка на демо-данных. Пока человек не попросил
// план, с экрана уходят только GET.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, openTip, test } from './fixtures';

const tabs = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });
const writes = (hits: string[]) => hits.filter((h) => !h.startsWith('GET '));

async function fill(page: Page, at: string, text: string) {
  const box = page.getByTestId('notify-new');
  await box.getByTestId('notify-new-at').fill(at);
  await box.getByTestId('notify-new-text').fill(text);
  await box.getByTestId('notify-new-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  return { box, dialog, yes: dialog.getByTestId('notify-new-confirm') };
}

test('таб → журнал, напоминания, проверка каналов — только GET; колокольчик ведёт сюда же', async ({
  page,
  apiHits,
}) => {
  await page.goto('/');
  await tabs(page).getByRole('link', { name: 'Уведомления', exact: true }).click();
  await expect(page).toHaveURL(/\/notifications$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Уведомления и напоминания');
  await expect(page.getByText(/Скоро · версия/)).toHaveCount(0);

  const journal = page.getByTestId('notify-journal');
  const rows = journal.getByTestId('notify-event');
  await expect(rows).toHaveCount(20);
  await expect(rows.first()).toContainText('пробное сообщение фабрики');
  await expect(journal.getByTestId('notify-journal-count')).toHaveText(
    'Показаны последние 20 из 23.',
  );
  const halted = journal.locator('[data-testid="notify-event"][data-kind="run_halted"]');
  await openTip(
    page,
    halted.locator('[data-backend="telegram"] [data-slot="status"]'),
    'error: HTTP 502 Bad Gateway',
  );
  await journal.getByTestId('notify-journal-kind').selectOption('token');
  await expect(rows).toHaveCount(1);
  await expect(rows).toContainText('Токен YouTube');
  await journal.getByTestId('notify-journal-kind').selectOption('');
  await journal.getByTestId('notify-journal-all').click();
  await expect(rows).toHaveCount(23);

  const rem = page.getByTestId('notify-reminders');
  await expect(rem.getByTestId('notify-reminder')).toHaveCount(4);
  await expect(rem.locator('[data-status="exhausted"]')).toContainText(
    'не дошло — попытки кончились',
  );
  await openTip(
    page,
    rem.getByTestId('notify-reminder-cancel-open').first(),
    'Фабрика покажет, что значит отмена',
  );
  await rem.getByTestId('notify-reminders-all').click();
  await expect(rem.getByTestId('notify-reminder')).toHaveCount(6);
  await expect(rem.locator('[data-status="cancelled"]')).toContainText('отменено');

  const check = page.getByTestId('notify-check');
  await expect(check.getByTestId('notify-check-external')).toContainText(
    'С этой машины уходит: Telegram',
  );
  await expect(
    check.locator('[data-testid="notify-check-backend"][data-name="telegram"]'),
  ).toContainText('уходит с машины');
  await check.getByTestId('notify-check-again').click();
  await expect(check.getByTestId('notify-check-again')).toHaveText('Проверить ещё раз');
  expect(writes(apiHits), 'с экрана уведомлений — только GET').toEqual([]);

  await page.goto('/');
  await page.getByRole('link', { name: 'Уведомления и напоминания' }).click();
  await expect(page).toHaveURL(/\/notifications$/);
});

test('поставить: план → «да» с отсчётом → итог, очередь перечитана', async ({
  page,
  apiHits,
  notify,
}) => {
  await page.goto('/notifications');
  await expect(page.getByTestId('notify-reminder')).toHaveCount(4);
  const { box, dialog, yes } = await fill(page, '21:30', 'Позвонить монтажёру');
  await expect(dialog.getByTestId('notify-plan-when')).toHaveText(
    'Напомнит 12 октября, 21:30 МСК · через 2 ч 50 мин',
  );
  await expect(dialog.getByTestId('notify-plan-text')).toHaveText('Позвонить монтажёру');
  await expect(yes).toHaveText(/Поставить · [12]:\d\d/);
  expect(writes(apiHits)).toEqual(['POST /api/notify/reminders/plan']);
  expect(notify.state.written).toEqual([]);
  await yes.click();
  await expect(dialog).toBeHidden();
  await expect(box.getByTestId('notify-reminder-done')).toContainText('Напоминание поставлено');
  await expect(page.getByTestId('notify-reminder')).toHaveCount(5);
  await expect(page.locator('[data-testid="notify-reminder"][data-id="R7"]')).toContainText(
    'Позвонить монтажёру',
  );
  expect(notify.state.written).toEqual(['R7']);

  // То же самое ещё раз — фабрика не ставит второе.
  const again = await fill(page, '21:30', 'Позвонить монтажёру');
  await again.yes.click();
  await expect(box.getByTestId('notify-reminder-done')).toContainText(
    'Такое напоминание уже стоит',
  );
  expect(notify.state.written).toEqual(['R7']);
});

test.describe('отказы (браузер пишет 4xx/5xx в консоль)', () => {
  test.use({ expectCleanConsole: false });

  test('«вечером» — время не подходит, строка фабрики, «да» погашено', async ({ page, notify }) => {
    await page.goto('/notifications');
    const { dialog, yes } = await fill(page, 'вечером', 'что-то');
    const refusal = dialog.getByTestId('write-refusal');
    await expect(refusal).toHaveAttribute('data-code', 'bad_time');
    await expect(refusal.getByTestId('write-refusal-title')).toHaveText(
      'Время не подходит — напоминание не поставлено',
    );
    await expect(refusal.getByTestId('write-refusal-message')).toContainText('по Москве');
    await expect(yes).toBeDisabled();
    expect(notify.state.written).toEqual([]);
  });

  test('«да» после сдвига времени — план заново сам, второе «да» ставит', async ({
    page,
    notify,
  }) => {
    await page.goto('/notifications');
    const { box, dialog, yes } = await fill(page, '21:30', 'Позвонить монтажёру');
    await expect(yes).toBeEnabled();
    notify.state.next = 'check_changed';
    await yes.click();
    await expect(dialog.getByTestId('replanned')).toHaveAttribute('data-code', 'check_changed');
    await expect(dialog.getByTestId('replanned')).toContainText(
      'Напоминание изменилось с момента плана',
    );
    await expect(yes).toBeEnabled();
    await yes.click();
    await expect(box.getByTestId('notify-reminder-done')).toBeVisible();
    expect(notify.state.written).toHaveLength(1);
  });

  test('план устарел — «Проверить заново» даёт новый', async ({ page, notify }) => {
    notify.state.life = 2;
    await page.goto('/notifications');
    const { box, dialog, yes } = await fill(page, '21:30', 'x');
    await expect(dialog.getByTestId('token-expired')).toBeVisible({ timeout: 6000 });
    await expect(yes).toBeDisabled();
    notify.state.life = 120;
    await dialog.getByTestId('replan').click();
    await expect(yes).toBeEnabled();
    await yes.click();
    await expect(box.getByTestId('notify-reminder-done')).toBeVisible();
  });

  test('сломанная проверка — словами фабрики, журнал на месте', async ({ page, notify }) => {
    notify.state.refuse.check = true;
    await page.goto('/notifications');
    await expect(page.getByTestId('notify-check')).toContainText('Проверка каналов не прошла');
    await expect(page.getByTestId('notify-check')).toContainText(
      'Проверка уведомлений фабрики не прошла.',
    );
    await expect(page.getByTestId('notify-event')).toHaveCount(20);
  });
});

test('пусто: журнал и очередь словами', async ({ page, notify }) => {
  notify.state.journal = [];
  notify.state.reminders = [];
  await page.goto('/notifications');
  await expect(page.getByTestId('notify-journal')).toContainText(
    'Фабрика ещё ничего не отправляла',
  );
  await expect(page.getByTestId('notify-reminders')).toContainText('Ничего не ждёт');
  await page.getByTestId('notify-reminders-all').click();
  await expect(page.getByTestId('notify-reminders')).toContainText('Напоминаний ещё не ставили');
});

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('экран, план и итог без прокрутки вбок', async ({ page }) => {
    await page.goto('/notifications');
    await expect(page.getByTestId('notify-event')).toHaveCount(20);
    await expect(page.getByTestId('notify-check-preview')).toBeVisible();
    await noSideScroll(page);
    const { box, yes } = await fill(page, '2026-10-20 10:00', 'Внести цифры Studio за неделю');
    await noSideScroll(page);
    await yes.click();
    await expect(box.getByTestId('notify-reminder-done')).toContainText('20 октября, 10:00 МСК');
    await noSideScroll(page);
  });
});

// CC-0188 (CF-0925): приёмка и «залито в Studio» в журнале; `upload` — только на этой машине;
// многострочный `body` — под свёрнутым «Подробнее», простым текстом, переносы как есть.
for (const [name, viewport] of [
  ['компьютер', { width: 1280, height: 800 }],
  ['телефон 390', { width: 390, height: 844 }],
] as const) {
  test.describe(`приёмка и «залито в Studio»: ${name} @cc-0188`, () => {
    test.use({ viewport });

    test('новые виды словами, upload — локальный, body под «Подробнее»', async ({
      page,
      apiHits,
    }) => {
      await page.goto('/notifications');
      const journal = page.getByTestId('notify-journal');
      const row = (kind: string) =>
        journal.locator(`[data-testid="notify-event"][data-kind="${kind}"]`);
      await expect(journal.getByTestId('notify-event')).toHaveCount(20);

      const uploaded = row('uploaded');
      await expect(uploaded).toContainText('Залито в Studio');
      await expect(uploaded).toContainText('выйдет 13 октября');
      await expect(uploaded.getByTestId('notify-event-body')).toHaveCount(0);

      const upload = row('upload');
      await expect(upload.getByTestId('notify-backend')).toHaveCount(1);
      await openTip(
        page,
        upload.locator('[data-slot="status"]').first(),
        /только на этой машине: в Telegram не уходит/,
      );
      await page.keyboard.press('Escape');

      const accepted = row('accepted');
      await expect(accepted).toContainText('Приёмка');
      const body = accepted.getByTestId('notify-event-body');
      await expect(body).toBeHidden();
      await noSideScroll(page);
      await accepted.getByText('Подробнее: текст для Telegram').click();
      await expect(body).toBeVisible();
      expect(await body.textContent()).toContain('Принято: 2 из 3\n  • «Чип за 60 секунд»');
      expect(await body.evaluate((e) => getComputedStyle(e).whiteSpace)).toBe('pre-wrap');
      const box = await body.boundingBox();
      expect(box!.height, 'строки body — каждая на своей строке').toBeGreaterThan(60);
      await noSideScroll(page);
      expect(writes(apiHits)).toEqual([]);
    });
  });
}

test('тренировка: поставить напоминание на демо-данных, живой API не тронут', async ({
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
  await tabs(page).getByRole('link', { name: 'Уведомления', exact: true }).click();
  await expect(page.getByTestId('notify-event')).toHaveCount(20);
  const { box, yes } = await fill(page, '21:30', 'Учебное напоминание');
  await yes.click();
  await expect(box.getByTestId('notify-reminder-done')).toContainText('Напоминание поставлено');
  expect(apiHits.slice(live)).toEqual([]);
});
