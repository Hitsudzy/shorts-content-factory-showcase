// CC-0059: API не на рабочей фабрике — плашка «Только смотреть» в шапке, все кнопки записи
// погашены с причиной, планы действий не спрашиваются; значок «режим разработки» при флаге;
// отказ 409 `not_working_factory` посреди сессии — сообщение как есть, health перечитан.
import type { Page } from '@playwright/test';

import { RUNNING } from '../../src/mocks/batches';
import { fixtures, READ_ONLY_REASON, writesModes } from '../../src/mocks/fixtures';
import { expect, onlyHttp, openTip, test } from './fixtures';

const health = (page: Page, m: keyof typeof writesModes) =>
  page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes[m] } }),
  );

/** Не-GET запросы страницы к API (всё, что могло бы писать). */
const writesOf = (page: Page) => {
  const sent: string[] = [];
  page.on('request', (r) => {
    if (r.method() !== 'GET' && r.url().includes('/api/'))
      sent.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return sent;
};

const expectOff = async (el: ReturnType<Page['getByTestId']>) => {
  await expect(el).toHaveAttribute('aria-disabled', 'true');
  await expect(el).toHaveAttribute('data-writes', 'off');
  // Погашена и на вид: `aria-disabled:opacity-60` кнопки (как у прочих недоступных).
  await expect(el).toHaveCSS('opacity', '0.6');
};

test('только смотреть: плашка в шапке, «Батчи» — запись погашена, планов не просим', async ({
  page,
}) => {
  await health(page, 'off');
  const sent = writesOf(page);
  await page.goto('/batches');
  const banner = page.getByTestId('read-only-banner');
  await expect(banner).toContainText(
    'Только смотреть: это рабочая копия разработки, а не рабочая фабрика',
  );
  await expect(banner.getByTestId('read-only-reason')).not.toContainText('/');
  await expect(banner.getByTestId('read-only-reason-raw')).toBeHidden();
  await banner.getByText('Что это значит').click();
  await expect(banner.getByTestId('read-only-reason-raw')).toContainText(READ_ONLY_REASON);
  await expect(banner.getByTestId('read-only-more')).toContainText('не на рабочей фабрике');

  const toggle = page.getByTestId('switch-toggle');
  await expectOff(toggle);
  await toggle.click({ force: true });
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await openTip(page, toggle, `Только смотреть: ${READ_ONLY_REASON}`);

  const launch = page.getByTestId('launch-open');
  await expectOff(launch);
  await launch.click({ force: true });
  await expect(page.getByRole('alertdialog')).toHaveCount(0);

  const stop = page
    .locator(`[data-testid="open-batch"][data-batch="${RUNNING}"]`)
    .getByTestId('stop-open');
  await expectOff(stop);
  await stop.click({ force: true });
  await expect(page.getByRole('alertdialog')).toHaveCount(0);

  const save = page.getByTestId('win-save').first();
  await expectOff(save);
  await save.click({ force: true });
  expect(sent).toEqual([]);
});

test('только смотреть: канал — «Проверить» работает, «Сохранить» и «Вернуть» погашены', async ({
  page,
}) => {
  await health(page, 'off');
  const sent = writesOf(page);
  await page.goto('/channels/example-film');
  await page.getByRole('button', { name: /^scope,/ }).click();
  await page.getByLabel('min popularity score', { exact: true }).fill('450');
  const save = page.getByTestId('channel-save');
  await expectOff(save);
  await save.click({ force: true });
  await page.getByRole('button', { name: 'Проверить' }).click();
  await expect(page.getByTestId('check-result')).toBeVisible();
  await page.getByRole('tab', { name: 'История' }).click();
  const reverts = page
    .getByRole('list', { name: 'История правок' })
    .getByRole('button', { name: 'Вернуть' });
  await expect(reverts.first()).toBeVisible();
  for (const r of await reverts.all()) {
    await expect(r).toHaveAttribute('data-writes', 'off');
  }
  expect(sent).toEqual(['POST /api/channels/example-film/check']);
});

test('флаг разработки: значок «режим разработки», запись живая', async ({ page }) => {
  await health(page, 'dev');
  await page.goto('/batches');
  await expect(page.getByTestId('writes-dev')).toHaveText('режим разработки');
  await openTip(page, page.getByTestId('writes-dev'), 'CC_API_WRITES=dev');
  await expect(page.getByTestId('read-only-banner')).toHaveCount(0);
  await expect(page.getByTestId('switch-toggle')).not.toHaveAttribute('data-writes', 'off');
});

test.describe('отказ посреди сессии', () => {
  test.use({ expectCleanConsole: false });

  test('409 not_working_factory: message как есть, health перечитан, кнопки гаснут', async ({
    page,
    consoleErrors,
  }) => {
    const reason = 'основной чекаут не на main (cc/api)';
    let off = false;
    let asked = 0;
    await page.route('**/api/health', (route) => {
      asked++;
      return route.fulfill({
        json: off
          ? { ...fixtures.health, writes: false, writes_reason: reason, writes_dev: false }
          : fixtures.health,
      });
    });
    await page.route('**/api/schedule/switch', (route) => {
      off = true;
      return route.fulfill({
        status: 409,
        json: {
          message: `Только смотреть: ${reason}`,
          code: 'not_working_factory',
          details: [reason],
        },
      });
    });
    await page.goto('/batches');
    const toggle = page.getByTestId('switch-toggle');
    await expect(toggle).toBeVisible();
    await expect(toggle).not.toHaveAttribute('data-writes', 'off');
    await expect(page.getByTestId('read-only-banner')).toHaveCount(0);
    const before = asked;
    await toggle.click({ force: true });
    const dialog = page.getByRole('alertdialog');
    await dialog.getByTestId('switch-note-input').fill('в чате сказал включай');
    await dialog.getByRole('button', { name: 'Включить' }).click();
    await expect(dialog.getByTestId('refusal-message')).toHaveText(`Только смотреть: ${reason}`);
    await expect(page.getByTestId('read-only-banner')).toContainText(reason);
    expect(asked).toBeGreaterThan(before);
    await expectOff(dialog.getByRole('button', { name: 'Включить' }));
    await dialog.getByRole('button', { name: 'Отмена' }).click();
    await expectOff(toggle);
    onlyHttp(consoleErrors, 409);
  });
});
