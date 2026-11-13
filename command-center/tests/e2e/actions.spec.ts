// Экран «Батчи» (в) на подставных действиях (src/mocks/batchActions.ts): запуск с проверками
// и отсчётом, истёкший токен (у кнопки и у фабрики) → проверка заново, `check_changed`,
// `refused` «1 батч в сутки», остановка без шага и с шагом, `ok:false` со строкой `kill -9`
// только текстом, `busy`, продолжение пересборки, телефон без горизонтальной прокрутки.
import type { Page } from '@playwright/test';

import { RUNNING, STOPPED } from '../../src/mocks/batches';
import { expect, onlyHttp, openTip, test } from './fixtures';

const card = (page: Page, batch: string) =>
  page.locator(`[data-testid="open-batch"][data-batch="${batch}"]`);

const noHorizontalScroll = async (page: Page) => {
  const doc = await page.evaluate(() => ({
    scroll: document.documentElement.scrollWidth,
    width: document.documentElement.clientWidth,
  }));
  expect(doc.scroll, 'горизонтальная прокрутка страницы').toBeLessThanOrEqual(doc.width);
};

const openLaunch = async (page: Page) => {
  await page.getByTestId('launch-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('launch-why')).toBeVisible();
  return dialog;
};

test('запуск: проверки, отсчёт на кнопке, «да» — строка фабрики, батч в «Идёт сейчас»', async ({
  page,
  batches,
}) => {
  batches.closeAll();
  await page.goto('/batches');
  await expect(page.getByTestId('no-batch')).toBeVisible();
  const dialog = await openLaunch(page);
  await expect(dialog.getByTestId('launch-why')).toHaveText('все защиты пройдены');
  await expect(dialog.getByTestId('launch-guard')).toHaveCount(5);
  await expect(dialog.locator('[data-testid="launch-guard"][data-ok="false"]')).toHaveCount(0);
  await openTip(page, dialog.getByTestId('launch-skipped-tip'), 'проверки таймера расписания');
  const go = dialog.getByTestId('launch-confirm');
  await expect(go).toHaveText(/^Запустить · [12]:\d\d$/);
  const first = await go.textContent();
  await expect(go).not.toHaveText(first!, { timeout: 5_000 });
  await go.click();
  await expect(dialog).toBeHidden();
  const done = page.getByTestId('launch-done');
  await expect(done.getByTestId('launch-line')).toContainText('запущен вручную');
  await expect(done.getByText(/^pid \d+/)).toBeHidden();
  await done.getByText('Подробнее').click();
  await expect(done.getByText(/^pid \d+/)).toBeVisible();
  // договор 0.35.0+ (CC-0098 фабрики): путь журнала — от корня фабрики, не абсолютный
  await expect(done.getByText(/журнал schedule\/logs\/\S+\.log/)).toBeVisible();
  await expect(page.getByTestId('open-batch')).toHaveCount(1);
  await expect(card(page, 'example-film/2026-10-10T0701Z').getByTestId('batch-status')).toHaveText(
    'идёт',
  );
  expect(batches.actions.writes.map((w) => w.path)).toEqual(['launch/plan', 'launch']);
});

test('запуск: канал с открытым батчем — «Запустить» недоступна, причина как есть', async ({
  page,
}) => {
  await page.goto('/batches');
  const dialog = await openLaunch(page);
  await expect(dialog.getByTestId('launch-why')).toHaveText(
    /^У канала уже открыт батч \(начат 10\.10, \d\d:\d\d\) — второй не запустить/,
  );
  await expect(dialog.getByTestId('launch-why')).not.toContainText(RUNNING);
  await expect(dialog.locator('[data-testid="launch-guard"][data-ok="false"]')).toHaveCount(1);
  await expect(dialog.getByTestId('launch-confirm')).toBeDisabled();
  await dialog.getByRole('button', { name: 'Отмена' }).click();
  await expect(dialog).toBeHidden();
});

test.describe('отказы «да»', () => {
  test.use({ expectCleanConsole: false });

  test('истёкший токен: у кнопки — «Проверить заново»; у фабрики — проверка заново сама', async ({
    page,
    batches,
    consoleErrors,
  }) => {
    batches.closeAll();
    batches.actions.setTtl(2);
    await page.goto('/batches');
    const dialog = await openLaunch(page);
    const go = dialog.getByTestId('launch-confirm');
    await expect(dialog.getByTestId('token-expired')).toBeVisible({ timeout: 6_000 });
    await expect(go).toBeDisabled();
    await expect(go).toHaveText('Запустить · 0:00');
    batches.actions.setTtl(120);
    await dialog.getByTestId('replan').click();
    await expect(go).toBeEnabled();
    await expect(dialog.getByTestId('token-expired')).toBeHidden();
    // Фабрика считает токен устаревшим (часы разошлись): план заново сам, с причиной.
    batches.actions.expireTokens();
    await go.click();
    await expect(dialog.getByTestId('replanned')).toContainText('Подтверждение устарело');
    await expect(go).toBeEnabled();
    await go.click();
    await expect(page.getByTestId('launch-done')).toBeVisible();
    onlyHttp(consoleErrors, 409);
  });

  test('check_changed — проверка заново; refused «1 батч в сутки» — как есть', async ({
    page,
    batches,
    consoleErrors,
  }) => {
    batches.closeAll();
    await page.goto('/batches');
    const dialog = await openLaunch(page);
    const go = dialog.getByTestId('launch-confirm');
    batches.actions.failNext('launch', 'check_changed');
    await go.click();
    await expect(dialog.getByTestId('replanned')).toContainText(
      'С момента проверки что-то изменилось',
    );
    await expect(go).toBeEnabled();
    batches.actions.startedToday('example-film');
    await go.click();
    const err = dialog.getByTestId('act-error');
    await expect(err).toHaveAttribute('data-code', 'refused');
    await expect(err.getByTestId('refusal-message')).toHaveText(
      'сегодня (2026-10-10) батч канала уже был - 1 батч в сутки (квота YouTube Search)',
    );
    await expect(go).toBeDisabled();
    // Окно не закрылось: фабрика не согласилась. Проверка заново — та же причина в плане.
    await dialog.getByTestId('replan').click();
    await expect(dialog.getByTestId('launch-why')).toHaveText(
      'Сегодня батч канала уже был — в сутки разрешён один',
    );
    await expect(go).toBeDisabled();
    onlyHttp(consoleErrors, 409);
  });

  test('остановка: busy — подтверждение годно; второе «да» останавливает, шаг живёт', async ({
    page,
    batches,
    consoleErrors,
  }) => {
    await page.goto('/batches');
    const c = card(page, RUNNING);
    await c.getByTestId('stop-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('stop-reason')).toContainText('можно остановить');
    await expect(dialog.getByTestId('stop-step')).toContainText('«Монтаж»');
    const go = dialog.getByTestId('stop-confirm');
    await expect(go).toHaveText(/^Остановить · [12]:\d\d$/);
    batches.actions.failNext('stop', 'busy');
    await go.click();
    await expect(dialog.getByTestId('act-error')).toHaveAttribute('data-code', 'busy');
    await expect(dialog.getByTestId('busy-note')).toContainText('Подтверждение ещё годно');
    await expect(go).toBeEnabled();
    await go.click();
    await expect(dialog).toBeHidden();
    const done = c.getByTestId('stop-done');
    await expect(done.getByTestId('stop-result-reason')).toContainText('работает дальше');
    await expect(done.getByTestId('step-left-running')).toContainText('продолжение его дождётся');
    await expect(c.getByTestId('batch-status')).toHaveText('остановлен');
    await expect(c.getByTestId('resume-open')).toBeVisible();
    await expect(c.getByTestId('stop-open')).toBeHidden();
    expect(batches.actions.writes.at(-1)!.body).toMatchObject({ also_step: false });
    onlyHttp(consoleErrors, 409);
  });
});

test('остановка с шагом: флажок — проверка заново, шаг остановлен', async ({ page, batches }) => {
  await page.goto('/batches');
  const c = card(page, RUNNING);
  await c.getByTestId('stop-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('stop-reason')).toBeVisible();
  await openTip(page, dialog.getByTestId('stop-also-step-tip'), 'начнётся заново');
  await dialog.getByTestId('stop-also-step').check();
  await expect(dialog.getByTestId('stop-confirm')).toBeEnabled();
  expect(batches.actions.writes.filter((w) => w.path.endsWith('stop/plan')).at(-1)!.body).toEqual({
    also_step: true,
  });
  await dialog.getByTestId('stop-confirm').click();
  await expect(c.getByTestId('stop-done')).toContainText('шаг остановлен');
  await expect(c.getByTestId('step-left-running')).toBeHidden();
  expect(batches.actions.writes.at(-1)!.body).toMatchObject({ also_step: true });
});

test('остановка: ok:false — строка kill -9 только текстом, кнопки «выполнить» нет', async ({
  page,
  batches,
}) => {
  batches.actions.setStopOutcome('survived');
  await page.goto('/batches');
  const c = card(page, RUNNING);
  await c.getByTestId('stop-open').click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByTestId('stop-confirm').click();
  await expect(dialog).toBeHidden();
  const failed = c.getByTestId('stop-failed');
  await expect(failed).toHaveAttribute('role', 'alert');
  await expect(failed.getByTestId('stop-result-reason')).toContainText(
    'Исполнитель не остановился за 30 с после просьбы завершиться',
  );
  const kill = failed.getByTestId('kill-line');
  await expect(kill).toHaveText(/^kill -9 -\d+$/);
  expect(await kill.evaluate((el) => el.tagName)).toBe('CODE');
  expect(await kill.evaluate((el) => getComputedStyle(el).userSelect)).toBe('all');
  await expect(failed.getByRole('button')).toHaveText(['Скрыть']);
  // Батч не остановлен — так и показан.
  await expect(c.getByTestId('batch-status')).toHaveText('идёт');
});

test('остановка с шагом, шаг пережил SIGTERM: reason_step и его kill -9 — текстом', async ({
  page,
  batches,
}) => {
  batches.actions.setStopOutcome('step_survived');
  await page.goto('/batches');
  const c = card(page, RUNNING);
  await c.getByTestId('stop-open').click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByTestId('stop-also-step').check();
  await expect(dialog.getByTestId('stop-confirm')).toBeEnabled();
  await dialog.getByTestId('stop-confirm').click();
  const done = c.getByTestId('stop-done');
  await expect(done.getByTestId('step-left-running')).toContainText('Шаг не остановился за 30 с');
  await expect(done.getByTestId('kill-line')).toHaveText('kill -9 -4188');
});

test('продолжить пересборку rebuilds/<ts>: проверка, отсчёт, «да» — снова идёт', async ({
  page,
  batches,
}) => {
  await page.goto('/batches');
  const c = card(page, STOPPED);
  await expect(c.getByTestId('stop-open')).toHaveCount(0);
  await c.getByTestId('resume-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('resume-reason')).toContainText(
    'можно продолжить с video-editor',
  );
  await expect(dialog.getByTestId('resume-confirm')).toHaveText(/^Продолжить · [12]:\d\d$/);
  await dialog.getByTestId('resume-confirm').click();
  await expect(dialog).toBeHidden();
  await expect(c.getByTestId('resume-done')).toContainText('Исполнитель снова работает');
  await expect(c.getByTestId('batch-status')).toHaveText('идёт');
  await expect(c.getByTestId('stop-open')).toBeVisible();
  expect(batches.actions.writes.map((w) => w.path)).toEqual([
    `${STOPPED}/resume/plan`,
    `${STOPPED}/resume`,
  ]);
});

test('исполнитель умер (running, alive []): «батч стоит», «Продолжить с этапа…», без «Остановить» (CC-0094)', async ({
  page,
  batches,
}) => {
  // Как example-science/2026-10-12T2001Z после перезагрузки 12.10: status running, fresh true,
  // живых процессов нет, последнее событие 7 мин назад.
  batches.killExecutor(RUNNING);
  // Главная — тот же статус.
  await page.goto('/');
  const home = page.getByTestId('batch-card');
  await expect(home).toHaveAttribute('data-state', 'gone');
  await expect(home.getByTestId('home-batch-status')).toHaveText('исполнитель не отвечает');
  await expect(home.getByTestId('home-executor-gone')).toContainText('Исполнитель остановился');
  await expect(home.getByTestId('film-strip')).not.toContainText('идёт');

  await page.goto('/batches');
  const c = card(page, RUNNING);
  await expect(c.getByTestId('executor-gone')).toContainText(
    'Исполнитель не отвечает — батч стоит',
  );
  await expect(c.getByTestId('executor-gone-reason')).toContainText(
    'Исполнитель остановился, не записав конца (перезагрузка или сбой)',
  );
  await expect(c.getByTestId('batch-status')).toHaveText('исполнитель не отвечает');
  await expect(c.getByTestId('stop-open')).toHaveCount(0);
  await expect(c.getByTestId('batch-eta')).toHaveCount(0);
  await expect(c.getByTestId('batch-event-age')).toHaveText('последнее событие 7 мин назад');
  // Кадр стадии — «остановлено», под ним — почему; «идёт N из …» нет нигде.
  const stoppedFrame = c.getByTestId('film-strip').locator('li[data-state="stopped"]');
  await expect(stoppedFrame.locator('small').first()).toHaveText('остановлено');
  await expect(stoppedFrame.getByTestId('frame-note')).toHaveText('исполнитель не отвечает');
  await expect(c.getByTestId('film-strip')).not.toContainText('идёт');
  // Строка времени: не «идёт 1 ч 30 мин», а возраст события; статус — в шапке и на компьютере.
  await expect(c.getByTestId('batch-elapsed')).toHaveCount(0);
  await expect(c.getByTestId('batch-status')).toBeVisible();
  await expect(c.getByTestId('batch-stage')).toContainText('Встал на стадии: Монтаж');
  // Живость — из строки списка (CC-0110): фоновой проверки resume/plan нет, слоя записи нет.
  await expect(page.getByTestId('write-lock')).toHaveCount(0);
  expect(batches.actions.writes.filter((w) => w.path.endsWith('/resume/plan'))).toHaveLength(0);
  const open = c.getByTestId('resume-open');
  await expect(open).toHaveText('Продолжить с этапа «Монтаж»…');
  await open.click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('resume-reason')).toContainText(
    'можно продолжить с video-editor',
  );
  await dialog.getByTestId('resume-confirm').click();
  await expect(dialog).toBeHidden();
  await expect(c.getByTestId('resume-done')).toContainText('Исполнитель снова работает');
  await expect(c.getByTestId('executor-gone')).toHaveCount(0);
  await expect(c.getByTestId('stop-open')).toBeVisible();
  expect(batches.actions.writes.filter((w) => w.path.endsWith('/resume'))).toHaveLength(1);
  // Продолживший исполнитель запустил шаг — живой процесс есть, фабрику больше не спрашивают.
  await expect(c.locator('[data-testid="process"][data-alive="true"]')).toHaveCount(1);
  expect(batches.actions.writes.at(-1)?.path).toBe(`${RUNNING}/resume`);
});

test('телефон: окно запуска и итог остановки без горизонтальной прокрутки', async ({
  page,
  batches,
}) => {
  batches.actions.setStopOutcome('survived');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  const c = card(page, RUNNING);
  await c.getByTestId('stop-open').click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByTestId('stop-confirm').click();
  await expect(c.getByTestId('kill-line')).toBeVisible();
  await noHorizontalScroll(page);
  const launch = await openLaunch(page);
  const box = (await launch.boundingBox())!;
  expect(box.x).toBeGreaterThanOrEqual(0);
  expect(box.x + box.width).toBeLessThanOrEqual(390);
  await noHorizontalScroll(page);
});
