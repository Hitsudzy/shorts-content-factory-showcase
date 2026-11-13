// CC-0127: карточка публикации без оператора — путь «принял → разложил → загрузил» в центре.
// Подставной API (src/mocks/cards.ts): у Reel карточка готова, принята вашим решением, собирается
// (готова через два опроса), не готова — не прошли слова ролика; у vanguards-doomsday не прошло
// утверждение названия. Приёмка сама запускает сборку (`queued.card_build`).
import type { Page } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import {
  CARD_BUILDING,
  CARD_OWN_FAIL,
  CARD_READY,
  CARD_RULED,
  CARD_TITLE_FAIL,
  RULED_WORDS,
} from '../../src/mocks/cards';
import { REEL } from '../../src/mocks/publish';
import { SCIENCE, STASH_OLD_BATCH } from '../../src/mocks/videos';
import { expect, noSideScroll, test } from './fixtures';

const row = (page: Page, slug: string) =>
  page.getByTestId('stash').locator(`[data-testid="stash-row"][data-slug="${slug}"]`);

test.describe('карточка без оператора', () => {
  test('копилка: готова, вашим решением, собирается → готова сама, не готова — почему', async ({
    page,
  }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    await expect(row(page, CARD_READY).getByTestId('stash-card')).toHaveText('карточка готова');
    await expect(row(page, CARD_RULED).getByTestId('stash-card')).toHaveText(
      'карточка готова вашим решением',
    );
    await expect(row(page, CARD_OWN_FAIL).getByTestId('stash-card')).toHaveText(
      'карточка не готова',
    );
    const building = row(page, CARD_BUILDING).getByTestId('stash-card');
    await expect(building).toHaveAttribute('data-state', 'building');
    await expect(building).toHaveAttribute('data-state', 'ready', { timeout: 15_000 });
  });

  test('«Принять своим решением…»: слова → план (что не прошло) → «да» → принята', async ({
    page,
    publish,
  }) => {
    await page.goto(`/publishing?channel=${REEL}`);
    const r = row(page, CARD_OWN_FAIL);
    await r.getByTestId('card-ruling-toggle').click();
    await r.getByTestId('card-ruling-words-input').fill('Цифру проверил по Variety — публикуем');
    await r.getByTestId('card-ruling-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('card-ruling-fail')).toHaveCount(2);
    // CC-0128: окно открыто — встроенная форма свёрнута, «Ваше решение» на экране одно.
    await expect(r.getByTestId('card-ruling-form')).toBeHidden();
    await expect(dialog.getByTestId('card-ruling-scope')).toContainText(
      'только слова самого ролика',
    );
    await dialog.getByTestId('card-ruling-confirm').click();
    await expect(page.getByTestId('card-ruling-done')).toContainText('принята вашим решением');
    await expect(r.getByTestId('stash-card')).toHaveAttribute('data-state', 'ruled');
    expect(publish.cards.state.calls.filter((c) => c.kind === 'confirm')).toHaveLength(1);
  });

  test('страница ролика: «Собрать заново…» — решение пропадёт → «да» → собирается → готова', async ({
    page,
  }) => {
    await page.goto(`/videos?batch=${encodeURIComponent(STASH_OLD_BATCH)}&v=${CARD_RULED}`);
    const card = page.getByTestId('publish-card');
    await expect(card.getByTestId('card-ruling-said')).toContainText(RULED_WORDS);
    await card.getByTestId('card-rebuild-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('card-build-replaces')).toContainText('решение пропадёт');
    await dialog.getByTestId('card-rebuild-confirm').click();
    await expect(card.getByTestId('card-build')).toContainText('собирается');
    await expect(card.getByTestId('card-build')).toContainText('готова к публикации', {
      timeout: 15_000,
    });
    await expect(card.getByTestId('card-state')).toHaveAttribute('data-state', 'ready');
  });

  test('утверждение названия — решением не принять: отказ словами, «да» погашено', async ({
    page,
  }) => {
    await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=${CARD_TITLE_FAIL}`);
    const card = page.getByTestId('publish-card');
    await card.getByTestId('card-ruling-toggle').click();
    await card.getByTestId('card-ruling-words-input').fill('беру');
    await card.getByTestId('card-ruling-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('card-plan-refusal')).toContainText('утверждение названия');
    await expect(dialog.getByTestId('card-ruling-confirm')).toBeDisabled();
    await expect(dialog.getByText('note_claim_failed').filter({ visible: true })).toHaveCount(0);
  });

  test('приёмка: «карточка собирается…» рядом с копилкой, потом готова', async ({ page }) => {
    await page.goto(`/videos?batch=${encodeURIComponent(SCIENCE)}&v=mars-sample-return`);
    await page.getByTestId('verdict-yes').click();
    await page.getByRole('alertdialog').getByTestId('verdict-confirm').click();
    const build = page.getByTestId('acceptance-answer-queued').getByTestId('accept-card-build');
    await expect(build).toContainText('собирается');
    await expect(build).toContainText('готова к публикации', { timeout: 15_000 });
  });

  test('телефон: копилка с действиями карточки без бокового скролла', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/publishing?channel=${REEL}`);
    await expect(row(page, CARD_OWN_FAIL).getByTestId('card-ruling-toggle')).toBeVisible();
    await noSideScroll(page);
  });
});
