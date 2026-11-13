// Подпись цены и решение по правилу воротец (CC-0115 шаг 3) на «Статистике», подставной API
// (src/mocks/gates.ts): план → «да», набранное пользователем (вставка не принимается), итог;
// сменившийся леджер — «Цены изменились, откройте заново»; телефон без прокрутки вбок.
import { expect, noSideScroll, test } from './fixtures';

const TAIL = '[data-rule="content_researcher.tail_after_last_anchor"]';

test('подпись цены: план, «да» набирается, итог на карточке', async ({ page, gates }) => {
  await page.goto('/stats?channel=example-film');
  const row = page.getByTestId('gate-prices').locator(TAIL);
  await row.getByTestId('gate-sign-toggle').click();
  await expect(row.getByTestId('gate-sign-price')).toHaveValue('3');
  await row.getByTestId('gate-sign-note').fill('решили в чате — пусть отказывает');
  await row.getByTestId('gate-sign-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('plan-head')).toContainText('можно подписать');
  const yes = dialog.getByTestId('gate-sign-yes');
  await expect(yes).toHaveValue('');
  await expect(dialog.getByTestId('gate-sign-confirm')).toBeDisabled();
  // Вставка «да» не принимается — только набор.
  await yes.focus();
  await page.evaluate(() => {
    const el = document.activeElement as HTMLInputElement;
    const dt = new DataTransfer();
    dt.setData('text/plain', 'да');
    el.dispatchEvent(
      new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true }),
    );
  });
  await expect(yes).toHaveValue('');
  await yes.pressSequentially('да');
  await expect(dialog.getByTestId('gate-sign-confirm')).toBeEnabled();
  await dialog.getByTestId('gate-sign-confirm').click();
  await expect(row.getByTestId('gate-write-done')).toContainText('Цена подписана');
  await expect(row).toContainText('Подписано');
  expect(gates.state.written.signed['content_researcher.tail_after_last_anchor']).toBeTruthy();
});

test('леджер сменился — «Цены изменились, откройте заново»', async ({ page, gates }) => {
  await page.goto('/stats?channel=example-film');
  const row = page.getByTestId('gate-prices').locator(TAIL);
  await expect(row).toBeVisible();
  gates.changeLedger();
  await row.getByTestId('gate-sign-toggle').click();
  await row.getByTestId('gate-sign-note').fill('подписываю');
  await row.getByTestId('gate-sign-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('gate-changed')).toContainText(
    'Цены изменились, откройте заново',
  );
  await expect(dialog.getByTestId('gate-sign-yes')).toHaveCount(0);
});

test('решение по правилу на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/stats?channel=example-film');
  const row = page.getByTestId('gate-prices').locator('[data-rule="orchestrator.stopcock"]');
  await row.getByTestId('gate-decide-toggle').click();
  await row.getByTestId('gate-decide-warn').check();
  await row.getByTestId('gate-decide-task').fill('CF-0330');
  await row.getByTestId('gate-decide-note').fill('пусть предупреждает');
  await row.getByTestId('gate-decide-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('gate-write-what')).toContainText('Решение: предупреждение');
  await noSideScroll(page);
  await dialog.getByTestId('gate-decide-yes').pressSequentially('да');
  await dialog.getByTestId('gate-decide-confirm').click();
  await expect(row.getByTestId('gate-write-done')).toContainText('Решение записано');
});
