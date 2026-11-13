// CC-0164: отметка ролика в копилке переживает опрос копилки (раз в минуту), а «Разложить по
// слотам…» не уезжает из-под щелчка, когда появляется первая отметка. Раньше на место кнопки
// вставала «Снять отметки»: щелчок по только что увиденной кнопке снимал отметку, окна не было.
// Галочка — по всей полосе у края строки. Второй прогон — на замедленном в 4 раза процессоре.
import type { Page } from '@playwright/test';

import { REEL, type PublishBackend } from '../../src/mocks/publish';
import { STASH_NOT_READY, STASH_TITLES } from '../../src/mocks/stash';
import { expect, test } from './fixtures';

/** CC-0128: название для показа — без « #shorts». */
const title = STASH_TITLES[STASH_NOT_READY]!.replace(/ #shorts$/, '');

const row = (page: Page, slug: string) =>
  page.getByTestId('stash').locator(`[data-testid="stash-row"][data-slug="${slug}"]`);

const reads = (publish: PublishBackend) =>
  publish.stash.state.calls.filter((c) => c.kind === 'get' && c.channel === REEL).length;

async function pickRefreshPlace(page: Page, publish: PublishBackend) {
  await page.clock.install();
  await page.goto(`/publishing?channel=${REEL}`);
  const stash = page.getByTestId('stash');
  await expect(stash.getByTestId('stash-row')).toHaveCount(4);
  await expect(stash.getByTestId('stash-picked')).toHaveText('Ничего не отмечено');
  // Где кнопка была до отметки — туда человек и щёлкнет (строка и кнопка — на одном экране).
  await stash.getByTestId('stash-bar').scrollIntoViewIfNeeded();
  const before = (await stash.getByTestId('stash-place-open').boundingBox())!;

  // Щелчок у края строки, мимо самого квадрата, — тоже отметка.
  const target = row(page, STASH_NOT_READY);
  await target.getByTestId('stash-pick-area').click({ position: { x: 4, y: 6 } });
  await expect(target.getByTestId('stash-pick')).toBeChecked();
  await expect(stash.getByTestId('stash-picked')).toHaveText('Отмечено: 1 ролик');

  // Опрос копилки: та же копилка пришла заново — отметка на месте.
  const asked = reads(publish);
  await page.clock.runFor(61_000);
  await expect.poll(() => reads(publish)).toBeGreaterThan(asked);
  await expect(target.getByTestId('stash-pick')).toBeChecked();
  await expect(stash.getByTestId('stash-picked')).toHaveText('Отмечено: 1 ролик');

  const after = (await stash.getByTestId('stash-place-open').boundingBox())!;
  expect(after.x).toBeCloseTo(before.x, 0);
  expect(after.y).toBeCloseTo(before.y, 0);
  await page.mouse.click(before.x + before.width / 2, before.y + before.height / 2);
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('stash-plan-item')).toHaveCount(1);
  await expect(dialog.getByTestId('stash-plan-item')).toContainText(title);
  await expect(stash.getByTestId('stash-picked')).toHaveText('Отмечено: 1 ролик');
}

test('отметить → опрос копилки → «Разложить по слотам…» там же, где была: в окне отмеченный', async ({
  page,
  publish,
}) => {
  await pickRefreshPlace(page, publish);
});

test.describe('процессор замедлен в 4 раза', () => {
  test.use({ cpuThrottle: 4 });
  test('то же под нагрузкой', async ({ page, publish }) => {
    test.slow();
    await pickRefreshPlace(page, publish);
  });
});
