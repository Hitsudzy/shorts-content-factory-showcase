// «Публикация» (г), CC-0071: подпись холда content-sensitivity из центра на подставном API
// (src/mocks/publishWrites.ts). Ролик смотрят рядом, в плеере; «Посмотрел, снимаю холд» →
// обязательная заметка → план фабрики (что отметил compliance-checker, что значит подпись,
// «вы, из центра») → «да» с отсчётом → холд уходит из открытых. Ни одного не-GET запроса, пока
// пользователь не попросил план, и подписи — пока не подтвердил. Компьютер и телефон 390 px.
import type { Page } from '@playwright/test';

import { fixtures, writesModes } from '../../src/mocks/fixtures';
import { HOLD_SENSITIVE, REEL } from '../../src/mocks/publish';
import { expect, noSideScroll, openTip, test } from './fixtures';

const NOTE = 'посмотрел: пострадавших крупно нет, кадры из новостей';
const BASE = `/api/publish/${REEL}/holds/${HOLD_SENSITIVE.batch_id}/${HOLD_SENSITIVE.topic_id}/sign`;

/** Все запросы страницы, кроме чтения (GET/HEAD): метод и путь. */
function writes(page: Page): string[] {
  const seen: string[] = [];
  page.on('request', (r) => {
    if (r.method() !== 'GET' && r.method() !== 'HEAD')
      seen.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return seen;
}

async function openHolds(page: Page) {
  await page.goto(`/publishing?channel=${REEL}`);
  const holds = page.getByTestId('holds');
  await expect(holds.getByTestId('hold')).toHaveCount(2);
  return { holds, row: holds.locator('[data-testid="hold"][data-signable="1"]') };
}

for (const phone of [false, true]) {
  test.describe(phone ? 'подпись холда: телефон 390' : 'подпись холда: компьютер', () => {
    test.beforeEach(async ({ page }) => {
      if (phone) await page.setViewportSize({ width: 390, height: 844 });
    });

    test('плеер → заметка → план → «да» → холд уходит из открытых', async ({ page, publish }) => {
      const sent = writes(page);
      const { holds, row } = await openHolds(page);
      await expect(holds.getByText('только просмотр')).toHaveCount(0);
      // Сначала ролик — плеер рядом с кнопкой.
      await expect(row.getByTestId('hold-video')).toHaveAttribute('data-slug', 'delver');
      await expect(row.getByTestId('player-video')).toBeVisible();
      const toggle = row.getByTestId('hold-sign-toggle');
      await expect(toggle).toHaveText(/Посмотрел, снимаю холд/);
      if (!phone) await openTip(page, toggle, 'Сначала посмотрите ролик');
      // У холда прав — строка фабрики вместо кнопки.
      const other = holds.locator('[data-testid="hold"][data-signable="0"]');
      await expect(other.getByTestId('hold-sign-refusal')).toContainText(
        'центр его не подписывает',
      );
      await expect(other.getByTestId('hold-sign-toggle')).toHaveCount(0);

      await toggle.click();
      const go = row.getByTestId('hold-sign-open');
      await expect(go).toHaveAttribute('aria-disabled', 'true');
      await go.click({ force: true });
      await expect(page.getByRole('alertdialog')).toHaveCount(0);
      await row.getByTestId('hold-sign-note').fill(NOTE);
      if (phone) await noSideScroll(page);
      expect(sent).toEqual([]);

      await go.click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByTestId('sign-plan-flagged').getByRole('listitem')).toHaveCount(4);
      await expect(dialog.getByTestId('sign-plan-flagged')).toContainText(
        'чувствительность контента',
      );
      await expect(dialog.getByTestId('sign-plan-meaning')).toContainText('вы посмотрели ролик');
      await expect(dialog.getByTestId('sign-plan-note')).toHaveText(NOTE);
      await expect(dialog.getByTestId('sign-plan-signature')).toHaveText('вы, из центра');
      const yes = dialog.getByTestId('hold-sign-confirm');
      await expect(yes).toBeEnabled();
      await expect(yes).toHaveText(/Подписать · [12]:\d\d/);
      if (phone) await noSideScroll(page);
      expect(sent).toEqual([`POST ${BASE}/plan`]);
      expect(publish.writes.state.written).toEqual([]);

      await yes.click();
      await expect(dialog).toBeHidden();
      await expect(page.getByTestId('toast')).toContainText('Холд снят');
      await expect(holds.getByTestId('hold')).toHaveCount(1);
      await expect(holds.getByTestId('hold').first()).toHaveAttribute('data-signable', '0');
      await expect(holds.getByText('Открытых: 1')).toBeVisible();
      await holds.getByText(/Снятые раньше: 2/).click();
      await expect(holds.getByTestId('hold-signed').first()).toContainText(
        'подпись: вы, из центра',
      );
      expect(sent).toEqual([`POST ${BASE}/plan`, `POST ${BASE}`]);
      expect(publish.writes.state.written.map((w) => w.action)).toEqual(['hold_sign']);
    });

    test.describe('отказы', () => {
      // 4xx фабрики браузер пишет в консоль — это ожидаемо.
      test.use({ expectCleanConsole: false });

      test('отказ фабрики — её строкой; подписи нет', async ({ page, publish }) => {
        const sent = writes(page);
        const { row } = await openHolds(page);
        // Холд подписали в терминале, пока страница была открыта.
        publish.state.holds.find((h) => h.topic_id === HOLD_SENSITIVE.topic_id)!.signature = {
          user: 'user',
          via: 'terminal',
        };
        await row.getByTestId('hold-sign-toggle').click();
        await row.getByTestId('hold-sign-note').fill(NOTE);
        await row.getByTestId('hold-sign-open').click();
        const dialog = page.getByRole('alertdialog');
        const refusal = dialog.getByTestId('write-refusal');
        await expect(refusal).toHaveAttribute('data-code', 'already_signed');
        await expect(refusal.getByTestId('write-refusal-title')).toHaveText('Холд уже подписан');
        await expect(refusal.getByTestId('write-refusal-message')).toHaveText(
          'Холд уже подписан — второй раз подписывать нечего.',
        );
        await expect(dialog.getByTestId('hold-sign-confirm')).toBeDisabled();
        if (phone) await noSideScroll(page);
        expect(sent).toEqual([`POST ${BASE}/plan`]);
        expect(publish.writes.state.written).toEqual([]);
      });

      test('план устарел — «запросите заново», заново — и подпись проходит', async ({
        page,
        publish,
      }) => {
        const sent = writes(page);
        const { row } = await openHolds(page);
        await row.getByTestId('hold-sign-toggle').click();
        await row.getByTestId('hold-sign-note').fill(NOTE);
        await row.getByTestId('hold-sign-open').click();
        const dialog = page.getByRole('alertdialog');
        const yes = dialog.getByTestId('hold-sign-confirm');
        await expect(yes).toBeEnabled();
        // Токен устарел у фабрики (окно простояло): «да» — отказ, центр сам берёт план заново.
        publish.writes.expireTokens();
        await yes.click();
        const again = dialog.getByTestId('replanned');
        await expect(again).toHaveAttribute('data-code', 'confirm_expired');
        await expect(again).toContainText('План устарел — запросите заново');
        await expect(yes).toBeEnabled();
        expect(publish.writes.state.written).toEqual([]);
        if (phone) await noSideScroll(page);
        await yes.click();
        await expect(dialog).toBeHidden();
        expect(sent).toEqual([
          `POST ${BASE}/plan`,
          `POST ${BASE}`,
          `POST ${BASE}/plan`,
          `POST ${BASE}`,
        ]);
        expect(publish.writes.state.written.map((w) => w.action)).toEqual(['hold_sign']);
      });
    });
  });
}

test('подпись холда: «только смотреть» — кнопка погашена, ни одного POST', async ({ page }) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  const sent = writes(page);
  const { row } = await openHolds(page);
  const toggle = row.getByTestId('hold-sign-toggle');
  await expect(toggle).toHaveAttribute('data-writes', 'off');
  await openTip(page, toggle, 'Только смотреть');
  await toggle.click({ force: true });
  await expect(row.getByTestId('hold-sign-form')).toHaveCount(0);
  expect(sent).toEqual([]);
});
