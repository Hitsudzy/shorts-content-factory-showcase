// Копилка канала (CC-0122) на подставном API (src/mocks/stash.ts): над лентой — принятые без
// слота с давностью, «устарел», карточкой, холдом и ссылкой; порядок ↑/↓; пачкой по слотам —
// план с отказом по ролику без «да», без него — «да», ролик в ленте, «в копилке» уменьшилась;
// dirty — строкой; «Доложить в копилку…»; «только смотреть» — ни одного POST; телефон.
import type { Page } from '@playwright/test';

import { fixtures, writesModes } from '../../src/mocks/fixtures';
import { REEL, SCIENCE } from '../../src/mocks/publish';
import {
  NOT_QUEUED,
  STASH_BUILDING,
  STASH_HELD,
  STASH_NOT_READY,
  STASH_STALE,
  STASH_TITLES,
} from '../../src/mocks/stash';
import { expect, noSideScroll, test } from './fixtures';

/** CC-0128: название для показа — `title_clean`, без « #shorts». */
const clean = (slug: string) => STASH_TITLES[slug]!.replace(/ #shorts$/, '');

const row = (page: Page, slug: string) =>
  page.getByTestId('stash').locator(`[data-testid="stash-row"][data-slug="${slug}"]`);

/** POST-запросы страницы к копилке. */
function posts(page: Page): string[] {
  const seen: string[] = [];
  page.on('request', (r) => {
    const path = new URL(r.url()).pathname;
    if (r.method() === 'POST' && path.includes('/stash')) seen.push(path);
  });
  return seen;
}

test.describe('копилка канала', () => {
  test('ролики по дате принятия, «устарел», карточка, холд; имя канала в ленте и «Для Studio»', async ({
    page,
  }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    const stash = page.getByTestId('stash');
    await expect(stash.getByTestId('stash-row')).toHaveCount(4);
    expect(
      await stash
        .getByTestId('stash-row')
        .evaluateAll((els) => els.map((el) => (el as HTMLElement).dataset.slug)),
    ).toEqual([STASH_STALE, STASH_HELD, STASH_NOT_READY, STASH_BUILDING]);
    await expect(row(page, STASH_STALE).getByTestId('stash-age')).toContainText('устарел');
    // CC-0128: настоящие названия карточек, без « #shorts» и без слага.
    await expect(row(page, STASH_STALE).getByTestId('stash-title')).toHaveText(clean(STASH_STALE));
    await expect(stash.getByTestId('stash-not-queued-row').getByTestId('stash-title')).toHaveText(
      clean(NOT_QUEUED),
    );
    await expect(stash).not.toContainText('#shorts');
    await expect(row(page, STASH_NOT_READY).getByTestId('stash-card-why')).toHaveText(
      'описание без источника факта',
    );
    await expect(row(page, STASH_HELD).getByTestId('stash-held')).toBeVisible();
    await expect(stash.getByTestId('stash-not-queued-row')).toHaveAttribute(
      'data-slug',
      NOT_QUEUED,
    );
    await expect(page.getByTestId('feed-channel')).toHaveText('ExampleFilm');
    await expect(page.getByTestId('studio-channel')).toHaveText('ExampleFilm');
    await expect(page.locator(`[data-testid="stash-count"][data-channel="${REEL}"]`)).toHaveText(
      'в копилке 4 · устарели: 1',
    );
    // Ссылка ведёт на ролик на экране «Ролики».
    await row(page, STASH_STALE).getByTestId('stash-title').click();
    await expect(page).toHaveURL(
      /\/videos\?batch=example-film%2F2026-09-24T0200Z&v=skyman-sequel/,
    );
  });

  test('пустая копилка — одной строкой', async ({ page }) => {
    await page.goto(`/publishing?channel=${SCIENCE}`);
    await expect(page.getByTestId('stash-empty')).toContainText('Копилка пуста');
  });

  test('порядок с клавиатуры → план с отказом без «да» → убрать → «да» → ролик в ленте', async ({
    page,
    publish,
  }) => {
    const sent = posts(page);
    await page.goto(`/publishing?channel=${REEL}`);
    const stash = page.getByTestId('stash');
    await row(page, STASH_STALE).getByTestId('stash-down').focus();
    await page.keyboard.press('Enter');
    await expect(stash.getByTestId('stash-row').first()).toHaveAttribute('data-slug', STASH_HELD);
    await row(page, STASH_STALE).getByTestId('stash-up').focus();
    await page.keyboard.press('Enter');
    await expect(stash.getByTestId('stash-row').first()).toHaveAttribute('data-slug', STASH_STALE);

    await row(page, STASH_STALE).getByTestId('stash-pick').check();
    await row(page, STASH_NOT_READY).getByTestId('stash-pick').check();
    await stash.getByTestId('stash-place-open').click();
    let dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('stash-plan-item')).toHaveCount(2);
    await expect(dialog.getByTestId('stash-plan-refusal')).toHaveText(
      'Карточка ролика не готова: описание без источника факта.',
    );
    await expect(dialog.getByTestId('stash-plan-stale')).toContainText('устарел');
    await expect(dialog.getByTestId('stash-place-confirm')).toBeDisabled();
    await dialog.getByRole('button', { name: 'Отмена' }).click();
    await expect(dialog).toBeHidden();

    await row(page, STASH_NOT_READY).getByTestId('stash-pick').uncheck();
    await stash.getByTestId('stash-place-open').click();
    dialog = page.getByRole('alertdialog');
    const slot = await dialog.getByTestId('stash-plan-slot').innerText();
    const yes = dialog.getByTestId('stash-place-confirm');
    await expect(yes).toBeEnabled();
    expect(publish.stash.state.written).toEqual([]);
    await yes.click();
    await expect(dialog).toBeHidden();
    await expect(stash.getByTestId('stash-done')).toContainText('Разложено: 1 ролик');
    await expect(stash.getByTestId('stash-done-item')).toContainText(slot.replace(/^→\s*/, ''));
    await expect(stash.getByTestId('stash-done-item')).toContainText(clean(STASH_STALE));
    await expect(stash.getByTestId('stash-row')).toHaveCount(3);
    await expect(
      page.getByTestId('slot-feed').locator(`[data-testid="slot"][data-slug="${STASH_STALE}"]`),
    ).toHaveCount(1);
    await expect(page.locator(`[data-testid="stash-count"][data-channel="${REEL}"]`)).toHaveText(
      'в копилке 3',
    );
    expect(sent).toEqual([
      `/api/publish/${REEL}/stash/place/plan`,
      `/api/publish/${REEL}/stash/place/plan`,
      `/api/publish/${REEL}/stash/place`,
    ]);
  });

  test('незакоммиченные правки — отказ строкой, код только под «Подробнее»', async ({
    page,
    publish,
  }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    const stash = page.getByTestId('stash');
    await stash.getByTestId('stash-pick-ready').click();
    publish.stash.state.next = 'dirty';
    await stash.getByTestId('stash-place-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('stash-plan-refusals')).toContainText('незакоммиченные правки');
    await expect(dialog.getByText('код dirty', { exact: false })).toBeHidden();
    await expect(dialog.getByTestId('stash-place-confirm')).toBeDisabled();
  });

  test('«Доложить в копилку…»: план → «да» → ролик в копилке', async ({ page }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    const stash = page.getByTestId('stash');
    await stash.getByTestId('stash-not-queued-row').getByTestId('stash-repair-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('stash-repair-items')).toContainText(
      `${clean(NOT_QUEUED)}: Будет положен в копилку`,
    );
    await expect(dialog.getByTestId('stash-repair-items')).not.toContainText('publish/');
    const yes = dialog.getByTestId('stash-repair-confirm');
    await expect(yes).toBeEnabled();
    await yes.click();
    await expect(stash.getByTestId('stash-repaired-item')).toHaveText(
      `${clean(NOT_QUEUED)}: Положен в копилку`,
    );
    await expect(stash.getByTestId('stash-row')).toHaveCount(5);
  });

  test('только смотреть: «Разложить» и «Доложить» погашены, ни одного POST', async ({ page }) => {
    await page.route('**/api/health', (route) =>
      route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
    );
    const sent = posts(page);
    await page.goto(`/publishing?channel=${REEL}`);
    const stash = page.getByTestId('stash');
    await stash.getByTestId('stash-pick-ready').click();
    const go = stash.getByTestId('stash-place-open');
    await expect(go).toHaveAttribute('data-writes', 'off');
    await go.click({ force: true });
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    expect(sent).toEqual([]);
  });

  test('телефон: копилка без бокового скролла, кнопки порядка на месте', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/publishing?channel=${REEL}`);
    await expect(page.getByTestId('stash-row')).toHaveCount(4);
    await expect(row(page, STASH_HELD).getByTestId('stash-up')).toBeVisible();
    await noSideScroll(page);
  });
});
