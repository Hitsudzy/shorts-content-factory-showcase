// «Публикация» (б), CC-0068: записи без сети на подставном API (src/mocks/publishWrites.ts) —
// пауза (план → «да» с отсчётом → канал на паузе), карточка (из очереди в слот со сдвигами и
// предупреждениями; сборка из черновика — «утверждения не проверены», модель — отказ словами),
// ротация (вердикт стража в плане), «только смотреть» — всё погашено и ни одного POST, телефон.
import type { Page } from '@playwright/test';

import { fixtures, writesModes } from '../../src/mocks/fixtures';
import {
  REEL,
  REEL_BATCH,
  SCRIPT_REJECTED,
  SCRIPT_STANDING,
  WAITING,
} from '../../src/mocks/publish';
import { expect, noSideScroll, openTip, test } from './fixtures';

const REASON = 'проверка — смотрим вкладку «Авторские права»';

/** POST-запросы страницы к API публикации. */
function posts(page: Page): string[] {
  const seen: string[] = [];
  page.on('request', (r) => {
    const path = new URL(r.url()).pathname;
    if (r.method() === 'POST' && path.includes('/api/publish')) seen.push(path);
  });
  return seen;
}

test.describe('публикация: записи без сети', () => {
  test('пауза: причина и срок → план → «да» с отсчётом → канал на паузе', async ({
    page,
    publish,
  }) => {
    const sent = posts(page);
    await page.goto(`/publishing?channel=${REEL}`);
    const pause = page.getByTestId('state-pause');
    await openTip(page, pause.getByTestId('pause-set-toggle'), 'Остановить выкладку');
    await pause.getByTestId('pause-set-toggle').click();
    await pause.getByTestId('pause-reason').fill(REASON);
    await pause.getByTestId('pause-until').fill('2026-10-20');
    await pause.getByTestId('pause-set-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('pause-plan-reason')).toHaveText(`${REASON} (из центра)`);
    const yes = dialog.getByTestId('pause-set-confirm');
    await expect(yes).toBeEnabled();
    await expect(yes).toHaveText(/Поставить · [12]:\d\d/);
    expect(publish.writes.state.written).toEqual([]);
    await yes.click();
    await expect(dialog).toBeHidden();
    await expect(pause.getByTestId('pause-done')).toContainText('Пауза поставлена');
    await expect(pause.locator('[data-slot="status"]').first()).toHaveText('на паузе');
    await expect(
      page.getByTestId('publish-channel').filter({ hasText: 'ExampleFilm' }),
    ).toContainText('на паузе');
    expect(sent).toEqual([`/api/publish/${REEL}/pause/set/plan`, `/api/publish/${REEL}/pause/set`]);
  });

  test('карточка из очереди в слот: слот, сдвиги, предупреждения; ролик встаёт в ленту', async ({
    page,
    publish,
  }) => {
    publish.writes.state.placeMoves = true;
    await page.goto(`/publishing?channel=${REEL}`);
    const card = page.getByTestId('card-writes');
    await card.getByTestId('card-pick-waiting').click();
    await card.getByTestId('card-batch').fill(REEL_BATCH);
    await card.getByTestId('card-place-toggle').click();
    await card.getByTestId('card-place-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('place-where')).toContainText('Ролик встанет в слот');
    await expect(dialog.getByTestId('place-move')).toHaveCount(1);
    await expect(dialog.getByTestId('place-warnings')).toContainText('WINDOW');
    await dialog.getByTestId('place-move').scrollIntoViewIfNeeded();
    await dialog.getByTestId('card-place-confirm').click();
    await expect(card.getByTestId('place-done')).toContainText('Карточка размещена');
    await expect(
      page.getByTestId('slot-feed').locator(`[data-testid="slot"][data-slug="${WAITING}"]`),
    ).toHaveCount(1);
  });

  test('CC-0168: ролик из копилки — поля «День» нет, введённый слот стёрт, план без дня', async ({
    page,
    publish,
  }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    const card = page.getByTestId('card-writes');
    await card.getByTestId('card-place-toggle').click();
    await expect(card.getByText('День: папка, где ролик лежит сейчас (не слот)')).toBeVisible();
    await card.getByTestId('card-day').fill('2026-10-26');
    await card.getByTestId('card-pick-waiting').click();
    await expect(card.getByTestId('card-day')).toHaveCount(0);
    await expect(card.getByTestId('card-day-queued')).toContainText('Разложить по слотам');
    await card.getByTestId('card-batch').fill(REEL_BATCH);
    await card.getByTestId('card-place-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('place-where')).toContainText('Ролик встанет в слот');
    const plans = publish.writes.state.calls.filter((c) => c.kind === 'plan');
    expect(plans.map((c) => c.body)).toEqual([
      {
        batch_id: '2026-10-09T0200Z',
        dir: 'example-film',
        slug: WAITING,
        day: null,
        replace: false,
      },
    ]);
  });

  test('сборка из черновика: «утверждения не проверены»; модель — понятный отказ', async ({
    page,
    publish,
  }) => {
    const sent = posts(page);
    await page.goto(`/publishing?channel=${REEL}`);
    const card = page.getByTestId('card-writes');
    await card.getByTestId('card-pick-selected').click();
    await card.getByTestId('card-build-toggle').click();
    await card.getByTestId('card-build-model').click();
    await expect(card.getByTestId('model-refused')).toContainText(
      'Черновик моделью из центра не пишется',
    );
    expect(sent).toEqual([]);
    await openTip(page, card.getByTestId('card-build-open'), 'Напишите название и описание');
    await card.getByTestId('draft-title').fill('Doomsday moved again');
    await card.getByTestId('draft-about').fill('Zenith moved it to December.');
    await card.getByTestId('draft-tags').fill('Zenith, MCU');
    await card.getByTestId('card-build-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('build-claims')).toContainText('утверждения не проверены');
    await dialog.getByTestId('card-build-confirm').click();
    await expect(card.getByTestId('build-done')).toContainText('утверждения не проверены');
    expect(publish.writes.state.written.map((w) => w.action)).toEqual(['card_build']);
  });

  test('ротация: вердикт стража в плане — «примут» и «отклонят» словами', async ({ page }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    const rot = page.getByTestId('state-rotation');
    await rot.getByTestId('rot-reject-toggle').click();
    await rot.getByTestId('reject-script').fill(SCRIPT_STANDING);
    await rot.getByTestId('reject-reason').fill('у этого факта нет второй стороны для контраста');
    await rot.getByTestId('rot-reject-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('ruling')).toHaveAttribute('data-verdict', 'upheld');
    await dialog.getByTestId('rot-reject-confirm').click();
    await expect(rot.getByTestId('rotation-done')).toContainText('Отказ принят');

    await rot.getByTestId('reject-script').fill(SCRIPT_REJECTED);
    await rot.getByTestId('rot-reject-open').click();
    await expect(dialog.getByTestId('ruling')).toHaveAttribute('data-verdict', 'denied');
    await expect(dialog.getByTestId('ruling-text')).toContainText('один отказ на сценарий');
  });

  test('только смотреть: записи погашены с причиной, ни одного POST', async ({ page }) => {
    await page.route('**/api/health', (route) =>
      route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
    );
    const sent = posts(page);
    await page.goto(`/publishing?channel=${REEL}`);
    const pause = page.getByTestId('state-pause');
    await pause.getByTestId('pause-set-toggle').click();
    await pause.getByTestId('pause-reason').fill(REASON);
    const go = pause.getByTestId('pause-set-open');
    await expect(go).toHaveAttribute('data-writes', 'off');
    await openTip(page, go, 'Только смотреть');
    await go.click({ force: true });
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    expect(sent).toEqual([]);
  });

  test('телефон: формы записей раскрыты — без прокрутки вбок', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(`/publishing?channel=${REEL}`);
    await page.getByTestId('pause-set-toggle').click();
    await page.getByTestId('card-place-toggle').click();
    await page.getByTestId('card-build-toggle').click();
    await page.getByTestId('rot-reject-toggle').click();
    await page.getByTestId('rot-refuse-toggle').click();
    await expect(page.getByTestId('rot-refuse-form')).toBeVisible();
    await noSideScroll(page);
  });
});
