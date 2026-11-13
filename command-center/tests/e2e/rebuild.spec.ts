// «Пересобрать…» (CC-0063): режимы из плана канала, секунды → моменты (`near` — вариант,
// `note` — почему нельзя), оставить/убрать исключения, `rewrite` исключений не берёт; план →
// подтверждение с отсчётом, истёк — проверить заново, `check_changed` — план заново сам,
// `busy`, успех со ссылкой в «Батчи», старт не удался — «Продолжить»; «только смотреть» гасит
// план и запуск; телефон без прокрутки вбок. Подставной API — со состоянием (src/mocks/rebuild.ts).
import type { Page } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import { fixtures, READ_ONLY_REASON, writesModes } from '../../src/mocks/fixtures';
import { expect, noSideScroll, onlyHttp, openTip, test } from './fixtures';

const DELVER = `/videos?batch=${encodeURIComponent(PAST)}&v=delver`;

async function prepare(page: Page, seconds = '12 18 24') {
  await page.goto(DELVER);
  await page.getByTestId('rebuild-toggle').click();
  const panel = page.getByTestId('rebuild');
  await expect(panel.getByTestId('rebuild-mode-option')).toHaveCount(2);
  await panel.getByTestId('rebuild-seconds').fill(seconds);
  await panel.getByTestId('rebuild-find').click();
  await expect(panel.getByTestId('moment').first()).toBeVisible();
  return panel;
}

test.describe('пересборка', () => {
  test('секунды → моменты: блок, окно, кадры, соседний блок у склейки, «нельзя» с причиной', async ({
    page,
    videos,
  }) => {
    const panel = await prepare(page, '12 18 24 28 42 50');
    expect(videos.rebuild.state.blockCalls).toEqual(['12,18,24,28,42,50']);
    const moments = panel.getByTestId('moment');
    await expect(moments).toHaveCount(6);
    await expect(panel.getByTestId('moment-block')).toHaveText([
      'блок 4 · 8,9–12,3 с · видео',
      'блок 7 · 17,2–20,6 с · видео',
      'блок 9 · 23,1–26,4 с · видео',
      'блок 10 · 26,4–29,8 с · сплит-экран',
      'концовка канала · 40,9–44,9 с · концовка',
      'вне ролика',
    ]);
    // Исключения из ответа фабрики — сразу отмечены; соседний блок — вариант, не отмечен.
    await expect(moments.nth(0).getByTestId('moment-exclude')).toBeChecked();
    await expect(moments.nth(0).getByTestId('moment-near')).toHaveAttribute(
      'data-exclude',
      '5=wIM1PDRvKSE:40',
    );
    await expect(moments.nth(0).getByTestId('moment-near')).not.toBeChecked();
    await expect(moments.nth(3).getByTestId('moment-note')).toContainText(
      'Сплит-экран: монтаж не исключает кадр',
    );
    await expect(moments.nth(4).getByTestId('moment-note')).toContainText('Концовка канала');
    await expect(moments.nth(5).getByTestId('moment-note')).toContainText('за концом ролика');
    await expect(moments.nth(3).getByTestId('moment-exclude')).toHaveCount(0);
    await expect(panel.getByTestId('rebuild-summary')).toHaveText(
      'Уберём кадры: 4=wIM1PDRvKSE:32, 7=wIM1PDRvKSE:55, 9=ZLXL1L0TfsI:19',
    );
    await openTip(page, moments.nth(0).getByText('И соседний блок 5'), 'у самой склейки');

    // Ошибка ввода — подсказка, в API не ходим.
    await panel.getByTestId('rebuild-seconds').fill('12 потом');
    await panel.getByTestId('rebuild-find').click();
    await expect(panel.getByTestId('seconds-error')).toContainText('«потом» — не секунды');
    expect(videos.rebuild.state.blockCalls).toHaveLength(1);
  });

  test('оставить/убрать исключения, соседний блок; план показывает их, «да» — только {confirm}', async ({
    page,
    videos,
  }) => {
    const panel = await prepare(page);
    const moments = panel.getByTestId('moment');
    await moments.nth(1).getByTestId('moment-exclude').uncheck();
    await moments.nth(0).getByTestId('moment-near').check();
    await panel.getByTestId('rebuild-text').fill('хук скучный, середина проседает');
    await expect(panel.getByTestId('rebuild-summary')).toHaveText(
      'Уберём кадры: 4=wIM1PDRvKSE:32, 9=ZLXL1L0TfsI:19, 5=wIM1PDRvKSE:40',
    );

    await panel.getByTestId('rebuild-open').click();
    const dialog = page.getByRole('alertdialog');
    const plan = dialog.getByTestId('rebuild-plan');
    await expect(plan.getByTestId('rebuild-reason')).toContainText('Можно пересобрать: delver');
    await expect(plan.getByTestId('rebuild-mode')).toContainText(
      'Перемонтаж — тот же сценарий, другие кадры — с шага «Монтаж»',
    );
    await expect(plan.getByTestId('layout-run')).toHaveText(
      'Тренды → Монтаж → Проверка кадров → На приёмку',
    );
    await expect(plan.getByTestId('layout-copied')).toHaveText(
      'Тренды → Футаж → Исследование → Проверка сценариев',
    );
    await expect(plan.getByTestId('layout-skipped')).toHaveText('на приёмку');
    await expect(plan.getByTestId('rebuild-video-exclude')).toContainText(
      '4=wIM1PDRvKSE:32, 9=ZLXL1L0TfsI:19, 5=wIM1PDRvKSE:40',
    );
    await expect(plan.getByTestId('rebuild-video-note')).toHaveText(
      'замечания на секундах 12, 18, 24',
    );
    await expect(plan.getByTestId('rebuild-notes')).toHaveText(
      'Замечание: хук скучный, середина проседает',
    );
    expect(videos.rebuild.state.plans.at(-1)!.body).toEqual({
      videos: ['delver'],
      mode: 'reedit',
      notes: {
        text: 'хук скучный, середина проседает',
        videos: {
          delver: {
            exclude: ['4=wIM1PDRvKSE:32', '9=ZLXL1L0TfsI:19', '5=wIM1PDRvKSE:40'],
            note: 'замечания на секундах 12, 18, 24',
          },
        },
      },
    });
    // Отсчёт на кнопке: «Пересобрать · 1:59».
    await expect(dialog.getByTestId('rebuild-confirm')).toHaveText(/^Пересобрать · [12]:\d\d$/);
    await dialog.getByTestId('rebuild-confirm').click();
    await expect(dialog).toBeHidden();
    expect(videos.rebuild.state.confirms.at(-1)!.body).toEqual({ confirm: 'rb-1' });

    const done = page.getByTestId('rebuild-done');
    await expect(done).toContainText('Пересборка запущена');
    await expect(done.getByTestId('rebuild-done-reason')).toHaveText(
      'Пересборка 2026-10-10T1930Z запущена.',
    );
    const link = done.getByTestId('rebuild-batch-link');
    await expect(link).toHaveAttribute('data-batch', 'rebuilds/2026-10-10T1930Z');
    await link.click();
    await expect(page).toHaveURL(/\/batches$/);
  });

  test('«Новый сценарий»: исключения не берёт — объяснение, флажки погашены, план без них', async ({
    page,
    videos,
  }) => {
    const panel = await prepare(page);
    await panel.getByTestId('rebuild-mode-option').nth(1).check();
    await expect(panel.getByTestId('no-exclude')).toContainText(
      'Убирать кадры можно только в режиме «Перемонтаж — тот же сценарий, другие кадры»',
    );
    for (const box of await panel.getByTestId('moment-exclude').all()) {
      await expect(box).toBeDisabled();
      await expect(box).not.toBeChecked();
    }
    await expect(panel.getByTestId('rebuild-summary')).toHaveText('Без исключений кадров.');
    await panel.getByTestId('rebuild-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('rebuild-mode')).toContainText('Новый сценарий');
    await expect(dialog.getByTestId('rebuild-video-exclude')).toHaveText('Без исключений кадров');
    expect(videos.rebuild.state.plans.at(-1)!.body).toMatchObject({
      mode: 'rewrite',
      notes: { videos: { delver: { exclude: [] } } },
    });
  });

  test.describe('отказы «да» (браузер пишет 409 в консоль)', () => {
    test.use({ expectCleanConsole: false });

    test('подтверждение истекло — «Проверить заново»; проверка изменилась — план заново сам', async ({
      page,
      videos,
      consoleErrors,
    }) => {
      videos.rebuild.state.life = 2;
      const panel = await prepare(page);
      await panel.getByTestId('rebuild-open').click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByTestId('rebuild-confirm')).toHaveText(/Пересобрать · 0:0[12]/);
      await expect(dialog.getByTestId('token-expired')).toBeVisible({ timeout: 6000 });
      await expect(dialog.getByTestId('rebuild-confirm')).toBeDisabled();
      videos.rebuild.state.life = 120;
      await dialog.getByTestId('replan').click();
      await expect(dialog.getByTestId('rebuild-confirm')).toBeEnabled();
      expect(videos.rebuild.state.plans).toHaveLength(2);

      videos.rebuild.state.next = 'check_changed';
      await dialog.getByTestId('rebuild-confirm').click();
      await expect(dialog.getByTestId('replanned')).toContainText(
        'С момента проверки что-то изменилось',
      );
      await expect.poll(() => videos.rebuild.state.plans.length).toBe(3);
      await expect(dialog.getByTestId('rebuild-confirm')).toBeEnabled();
      await dialog.getByTestId('rebuild-confirm').click();
      await expect(page.getByTestId('rebuild-done')).toBeVisible();
      onlyHttp(consoleErrors, 409);
    });

    test('busy: идёт запуск или другая пересборка, подтверждение цело — нажать ещё раз', async ({
      page,
      videos,
      consoleErrors,
    }) => {
      const panel = await prepare(page);
      await panel.getByTestId('rebuild-open').click();
      const dialog = page.getByRole('alertdialog');
      videos.rebuild.state.next = 'busy';
      await dialog.getByTestId('rebuild-confirm').click();
      const err = dialog.getByTestId('act-error');
      await expect(err).toHaveAttribute('data-code', 'busy');
      await expect(err).toContainText('Идёт запуск или другая пересборка');
      await expect(dialog.getByTestId('busy-note')).toBeVisible();
      videos.rebuild.state.next = 'ok';
      await dialog.getByTestId('rebuild-confirm').click();
      await expect(page.getByTestId('rebuild-done')).toBeVisible();
      expect(videos.rebuild.state.confirms.map((c) => c.body)).toEqual([
        { confirm: 'rb-1' },
        { confirm: 'rb-1' },
      ]);
      onlyHttp(consoleErrors, 409);
    });
  });

  test('старт не удался (ok:false, каталог есть) — «Продолжить в «Батчах»»', async ({
    page,
    videos,
  }) => {
    videos.rebuild.state.next = 'start_failed';
    const panel = await prepare(page);
    await panel.getByTestId('rebuild-open').click();
    await page.getByRole('alertdialog').getByTestId('rebuild-confirm').click();
    const failed = page.getByTestId('rebuild-failed');
    await expect(failed).toContainText('Пересборка не стартовала');
    await expect(failed.getByTestId('rebuild-failed-reason')).toHaveText(
      'Каталог пересборки создан, но исполнитель не стартовал (код 1) — продолжите её.',
    );
    const link = failed.getByTestId('rebuild-resume-link');
    await expect(link).toHaveAttribute('data-batch', 'rebuilds/2026-10-10T1930Z');
    await link.click();
    await expect(page).toHaveURL(/\/batches$/);
  });

  test('только смотреть: подготовка читается, план и запуск погашены, POST не уходит', async ({
    page,
    videos,
  }) => {
    await page.route('**/api/health', (route) =>
      route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
    );
    const panel = await prepare(page);
    await expect(panel.getByTestId('rebuild-readonly')).toBeVisible();
    const open = panel.getByTestId('rebuild-open');
    await expect(open).toHaveAttribute('aria-disabled', 'true');
    await open.click({ force: true });
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await openTip(page, open, `Только смотреть: ${READ_ONLY_REASON}`);
    expect(videos.rebuild.state.plans).toEqual([]);
    expect(videos.rebuild.state.confirms).toEqual([]);
  });

  test('телефон: панель пересборки и окно плана без прокрутки вбок', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const panel = await prepare(page);
    await panel.getByTestId('moment').first().getByTestId('moment-near').check();
    await noSideScroll(page);
    await panel.getByTestId('rebuild-open').click();
    await expect(page.getByRole('alertdialog').getByTestId('rebuild-plan')).toBeVisible();
    await noSideScroll(page);
  });
});
