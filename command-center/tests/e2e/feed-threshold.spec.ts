// Горизонт ленты и порог батча в окне канала на подставном расписании (CC-0185, договор 0.79.0,
// фабрика CC-0184, CF-0922): поле «Порог ленты» стало «Горизонт ленты», рядом «Порог батча» с тем,
// откуда он (файл канала, центр, по умолчанию фабрики); порог ниже горизонта — предупреждение до
// сохранения, отказ фабрики 409 — как есть. Компьютер и телефон, без бокового скролла.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, onlyHttp, test } from './fixtures';

const SIZES = {
  компьютер: { width: 1280, height: 800 },
  телефон: { width: 390, height: 844 },
} as const;

async function open(page: Page, size: { width: number; height: number }) {
  await page.setViewportSize(size);
  await page.goto('/batches');
  await expect(page.getByTestId('channel-windows')).toBeVisible();
}

for (const [name, size] of Object.entries(SIZES)) {
  test.describe(`горизонт ленты и порог батча: ${name} @cc-0185`, () => {
    test('поля: «Горизонт ленты», «Порог батча», откуда порог', async ({ page }) => {
      await open(page, size);
      const reel = page.getByTestId('window-example-film');
      await expect(reel.getByText('Горизонт ленты, дн.')).toBeVisible();
      await expect(reel.getByText('Порог батча, дн.')).toBeVisible();
      await expect(reel.getByText(/Порог ленты/)).toHaveCount(0);
      await expect(reel.getByTestId('win-feed')).toHaveValue('3');
      await expect(reel.getByTestId('win-batch-feed')).toHaveValue('3');
      await expect(reel.getByTestId('win-batch-origin')).toHaveText('Задан в настройках канала');

      const sci = page.getByTestId('window-example-science');
      await expect(sci.getByTestId('win-batch-feed')).toHaveValue('14');
      await expect(sci.getByTestId('win-batch-origin')).toHaveText('По умолчанию фабрики');

      await reel.getByText('Подробнее').click();
      await expect(reel.getByTestId('win-plan-feed')).toHaveText(
        'в плане: горизонт ленты 3 дн., порог батча 3 дн.',
      );
      await noSideScroll(page);
    });

    test('новый порог сохраняется: в теле PUT только он, «что поменялось» — порог батча', async ({
      page,
      schedule,
    }) => {
      await open(page, size);
      const card = page.getByTestId('window-example-film');
      await card.getByTestId('win-batch-feed').fill('7');
      await expect(card.getByTestId('win-threshold-below')).toHaveCount(0);
      const put = page.waitForRequest(
        (r) => r.method() === 'PUT' && r.url().endsWith('/api/schedule/channels/example-film'),
      );
      await card.getByTestId('win-save').click();
      expect((await put).postDataJSON()).toMatchObject({ min_feed_days: 3, batch_feed_days: 7 });
      await expect(card.getByTestId('win-saved')).toContainText('порог батча: 3 дн. → 7 дн.');
      await expect(card.getByTestId('win-batch-origin')).toHaveText('Задан в центре');
      expect(schedule.writes.filter((w) => w.kind === 'settings')).toHaveLength(1);
      await noSideScroll(page);
    });

    test('порог по умолчанию: горизонт выше 14 — без предупреждения, порог поднят', async ({
      page,
    }) => {
      await open(page, size);
      const card = page.getByTestId('window-example-science');
      await card.getByTestId('win-feed').fill('20');
      await expect(card.getByTestId('win-threshold-below')).toHaveCount(0);
      const put = page.waitForRequest(
        (r) => r.method() === 'PUT' && r.url().endsWith('/api/schedule/channels/example-science'),
      );
      await card.getByTestId('win-save').click();
      expect((await put).postDataJSON()).not.toHaveProperty('batch_feed_days');
      await expect(card.getByTestId('win-saved')).toContainText('горизонт ленты: 3 дн. → 20 дн.');
      await expect(card.getByTestId('win-batch-feed')).toHaveValue('20');
      await expect(card.getByTestId('win-batch-origin')).toHaveText(
        'По умолчанию фабрики — поднят до горизонта ленты',
      );
      await noSideScroll(page);
    });

    test.describe('отказ фабрики (409 в консоли браузера)', () => {
      test.use({ expectCleanConsole: false });

      test('порог ниже горизонта: предупреждение до сохранения, 409 как есть', async ({
        page,
        schedule,
        consoleErrors,
      }) => {
        await open(page, size);
        const card = page.getByTestId('window-example-film');
        await card.getByTestId('win-batch-feed').fill('2');
        const warn = card.getByTestId('win-threshold-below');
        await expect(warn).toHaveText(
          'Порог батча 2 дн. меньше горизонта ленты 3 дн. — фабрика такое не примет. Порог батча — не меньше горизонта.',
        );
        await expect(card.getByTestId('win-batch-feed')).toHaveAttribute('aria-invalid', 'true');
        await noSideScroll(page);

        await card.getByTestId('win-save').click();
        await expect(card.getByTestId('refusal-message')).toContainText(
          'Фабрика не приняла настройки расписания канала example-film: порог батча не меньше горизонта ленты',
        );
        expect(schedule.writes.filter((w) => w.kind === 'settings')).toHaveLength(0);
        await expect(card.getByTestId('win-batch-feed')).toHaveValue('2');
        await noSideScroll(page);

        // Поднять горизонт выше заданного порога — тоже предупреждение.
        await card.getByRole('button', { name: 'Вернуть как было' }).click();
        await card.getByTestId('win-feed').fill('5');
        await expect(warn).toContainText('Порог батча 3 дн. меньше горизонта ленты 5 дн.');
        onlyHttp(consoleErrors, 409);
      });
    });
  });
}
