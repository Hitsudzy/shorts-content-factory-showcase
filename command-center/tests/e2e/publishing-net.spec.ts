// «Публикация» (в), CC-0069: записи за пределы машины на подставном API
// (src/mocks/publishWrites.ts) — переключатель API-загрузки (заметка, предупреждения, фраза
// аудита руками), загрузка на YouTube (сводка, условия, «да» руками, долгое ожидание, «внести
// руками»), «загружено через Studio» (расхождения, would-add), «только смотреть», телефон.
import type { Page } from '@playwright/test';

import { fixtures, writesModes } from '../../src/mocks/fixtures';
import { READY, REEL, type PublishBackend } from '../../src/mocks/publish';
import { AUDIT_PHRASE } from '../../src/mocks/publishWrites';
import { expect, noSideScroll, openTip, test } from './fixtures';

const READY_DAY = '2026-10-13';
const NOTE = 'аудит пройден 11.10 — письмо Google, решили на созвоне';
const AT_READY = `/publishing?channel=${REEL}&slot=${READY_DAY}/${READY}`;

function posts(page: Page): string[] {
  const seen: string[] = [];
  page.on('request', (r) => {
    const path = new URL(r.url()).pathname;
    if (r.method() === 'POST' && path.includes('/api/publish')) seen.push(path);
  });
  return seen;
}

function switchOn(publish: PublishBackend) {
  publish.writes.state.switches[REEL] = {
    on: true,
    at: '2026-10-09T10:00:00Z',
    by: 'user',
    note: 'включено (из центра)',
    history: [],
  };
}

test.describe('публикация: переключатель, загрузка, Studio', () => {
  test('переключатель: заметка → предупреждения → фраза руками → включено', async ({
    page,
    publish,
  }) => {
    const sent = posts(page);
    await page.goto(`/publishing?channel=${REEL}`);
    const block = page.getByTestId('state-api-upload');
    await openTip(page, block.getByTestId('switch-on-toggle'), 'Только после аудита');
    await block.getByTestId('switch-on-toggle').click();
    await expect(block.getByTestId('switch-on-open')).toHaveAttribute('aria-disabled', 'true');
    await block.getByTestId('switch-note').fill(NOTE);
    await block.getByTestId('switch-on-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('switch-plan-warnings')).toContainText('ещё не прошло аудит');
    const phrase = dialog.getByTestId('switch-audit');
    await expect(phrase).toHaveValue('');
    const yes = dialog.getByTestId('switch-on-confirm');
    await expect(yes).toBeDisabled();
    await phrase.fill(AUDIT_PHRASE);
    await expect(yes).toBeEnabled();
    await expect(yes).toHaveText(/Включить · [12]:\d\d/);
    await yes.click();
    await expect(dialog).toBeHidden();
    await expect(block.getByTestId('switch-done')).toContainText('API-загрузка включена');
    await expect(block.getByTestId('switch-off-toggle')).toBeVisible();
    expect(publish.writes.state.calls.at(-1)!.body).toMatchObject({ audit: AUDIT_PHRASE });
    expect(sent).toEqual([
      `/api/publish/${REEL}/api-upload/switch/plan`,
      `/api/publish/${REEL}/api-upload/switch`,
    ]);
  });

  test.describe('долгая загрузка', () => {
    test.use({ writeDelay: 2500 });

    test('сводка и условия; «да» руками; окно ждёт с отсчётом, второй раз не шлёт', async ({
      page,
      publish,
    }) => {
      switchOn(publish);
      const sent = posts(page);
      await page.goto(AT_READY);
      const card = page.getByTestId('upload-writes');
      await expect(card).toContainText('API-загрузка включена');
      await card.getByTestId('upload-open').click();
      const dialog = page.getByRole('alertdialog');
      await expect(dialog.getByTestId('upload-summary')).toContainText('Название:');
      await expect(dialog.getByTestId('upload-tos')).toContainText('Условия использования');
      const answer = dialog.getByTestId('upload-answer');
      await expect(answer).toHaveValue('');
      await expect(dialog.getByRole('button', { name: /вставить/i })).toHaveCount(0);
      const yes = dialog.getByTestId('upload-confirm');
      await expect(yes).toBeDisabled();
      await answer.fill('да');
      await expect(yes).toBeEnabled();
      await yes.click();
      await expect(dialog.getByTestId('act-waiting')).toContainText('несколько минут');
      await expect(dialog.getByTestId('elapsed')).toHaveText(/0:0[1-9]/);
      await expect(yes).toBeDisabled();
      await expect(yes).toHaveText('Загружаю…');
      await expect(dialog.getByRole('button', { name: 'Отмена' })).toBeDisabled();
      await page.keyboard.press('Escape');
      await expect(dialog).toBeVisible();
      await expect(card.getByTestId('upload-done')).toContainText('Загружено на YouTube', {
        timeout: 10_000,
      });
      expect(sent.filter((p) => p.endsWith('/upload'))).toHaveLength(1);
    });
  });

  test.describe('ответ 500', () => {
    // Браузер пишет в консоль сам ответ 500 — это и есть проверяемый отказ, других ошибок нет.
    test.use({ expectCleanConsole: false });

    test('загружено, но не записано — строки «внести руками» с «скопировать»', async ({
      page,
      publish,
      consoleErrors,
    }) => {
      switchOn(publish);
      publish.writes.state.uploadNext = 'uploaded_unrecorded';
      await page.goto(AT_READY);
      await page.getByTestId('upload-open').click();
      const dialog = page.getByRole('alertdialog');
      await dialog.getByTestId('upload-answer').fill('да');
      await dialog.getByTestId('upload-confirm').click();
      const manual = dialog.getByTestId('upload-manual');
      await expect(manual).toContainText('не загружайте его ещё раз');
      await expect(manual.getByTestId('upload-manual-line').first()).toBeVisible();
      await expect(manual.getByTestId('upload-manual-copy')).toHaveCount(
        await manual.getByTestId('upload-manual-line').count(),
      );
      await expect(dialog.getByTestId('write-refusal-title')).toContainText('внесите её руками');
      expect(consoleErrors.filter((e) => !/status of 500/.test(e))).toEqual([]);
    });
  });

  test('Studio: поля не те — расхождения; JSON совпал — «добавит запись» → записано', async ({
    page,
    publish,
  }) => {
    await page.goto(AT_READY);
    const card = page.getByTestId('upload-writes');
    await card.getByTestId('studio-record-toggle').click();
    await card.getByTestId('record-video').fill('https://youtube.com/shorts/Ab3dE5gH7jK');
    await card.getByTestId('record-title').fill('Vanguards: Doomsday Moved Again');
    await card.getByTestId('record-visibility').fill('Запланировано');
    await card.getByTestId('record-publish-at').fill('2026-10-13T01:00+03:00');
    await card.getByTestId('studio-record-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('record-mismatch').first()).toContainText('Название');
    await expect(dialog.getByTestId('studio-record-confirm')).toBeDisabled();
    await dialog.getByRole('button', { name: 'Отмена' }).click();

    const note = [...publish.state.notes.values()].find((n) => n.slug === READY)!;
    const f = note.studio!;
    const read = {
      title: f.title,
      description: f.description,
      tags: f.tags,
      visibility: 'Запланировано',
      publish_at: (f.schedule as { publish_at: string }).publish_at,
    };
    await card.getByTestId('record-json').fill(JSON.stringify(read));
    await card.getByTestId('studio-record-open').click();
    await expect(dialog.getByTestId('record-status')).toContainText('добавит запись');
    await dialog.getByTestId('studio-record-confirm').click();
    await expect(card.getByTestId('record-done')).toContainText('Подряд без правок: 3 из 5');
    await expect(page.getByTestId('state-studio')).toContainText('3 из 5');
  });

  test('только смотреть: переключатель и загрузка погашены, ни одного POST', async ({ page }) => {
    await page.route('**/api/health', (route) =>
      route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
    );
    const sent = posts(page);
    await page.goto(AT_READY);
    const go = page.getByTestId('upload-open');
    await expect(go).toHaveAttribute('data-writes', 'off');
    await openTip(page, go, 'Только смотреть');
    await go.click({ force: true });
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    const block = page.getByTestId('state-api-upload');
    await block.getByTestId('switch-on-toggle').click();
    await block.getByTestId('switch-note').fill(NOTE);
    await expect(block.getByTestId('switch-on-open')).toHaveAttribute('data-writes', 'off');
    expect(sent).toEqual([]);
  });

  test('телефон: окно загрузки и форма Studio — без прокрутки вбок', async ({ page, publish }) => {
    switchOn(publish);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(AT_READY);
    await page.getByTestId('studio-record-toggle').click();
    await page.getByTestId('switch-off-toggle').click();
    await expect(page.getByTestId('studio-record-form')).toBeVisible();
    await noSideScroll(page);
    await page.getByTestId('upload-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('upload-summary')).toBeVisible();
    await noSideScroll(page);
  });
});
