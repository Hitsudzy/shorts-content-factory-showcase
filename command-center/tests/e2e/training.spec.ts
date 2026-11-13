// Тренировка на демо-данных (CC-0073): вход из оглавления тура, все десять заданий руками,
// перезагрузка посреди тренировки, выход. Главное — живой API (здесь его играет подставной
// API e2e, `tests/e2e/fixtures.ts`) за всю тренировку не получает ни одного запроса: каждый
// `/api/…` страницы отвечает service worker демо-сервера (`response.fromServiceWorker()`), до
// сети он не доходит (`apiHits`). Записей в живой API нет за весь тест. Обычная загрузка центра
// кусок тренировки не тянет и service worker не регистрирует.
import type { Page, Request } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import { REEL_BATCH } from '../../src/mocks/publish';
import { expect, noSideScroll, test } from './fixtures';

const BANNER = 'Тренировка — это демо, фабрика не трогается';
const TRAINING_CHUNK = /\/assets\/(demo|TrainingLayer)-[^/]+\.js$/;

/** Отказы демо-фабрики (409/500) браузер сам пишет в консоль — это ожидаемо, прочее — нет. */
test.use({ expectCleanConsole: false });
const unexpected = (errors: string[]) => errors.filter((e) => !/status of (409|422|500)/.test(e));

/** Все запросы страницы к API — чтобы потом спросить, кто на них ответил. */
function apiRequests(page: Page): Request[] {
  const seen: Request[] = [];
  page.on('request', (r) => {
    if (new URL(r.url()).pathname.includes('/api/')) seen.push(r);
  });
  return seen;
}

async function panelOpen(page: Page) {
  const panel = page.getByTestId('training-panel');
  if (!(await panel.isVisible())) await page.getByTestId('training-tasks-toggle').click();
  await expect(panel).toBeVisible();
  return panel;
}

/** «Открыть» у задания в панели — и свернуть панель, чтобы не закрывала экран. */
async function goTask(page: Page, id: string) {
  const panel = await panelOpen(page);
  await panel.locator(`[data-task="${id}"]`).getByTestId('training-task-go').click();
  await page.getByTestId('training-collapse').click();
}

async function lever(page: Page, id: 'training-expire' | 'training-refuse') {
  const panel = await panelOpen(page);
  await panel.getByTestId(id).click();
  await expect(panel.getByTestId(id)).toBeDisabled();
  await page.getByTestId('training-collapse').click();
}

async function expectDone(page: Page, ids: string[]) {
  const panel = await panelOpen(page);
  for (const id of ids)
    await expect(panel.locator(`[data-task="${id}"]`)).toHaveAttribute('data-done', 'yes');
  await page.getByTestId('training-collapse').click();
}

/**
 * Подъём демо-сервера после перезагрузки (CC-0159): страница ждёт свой service worker, а его
 * запросы мимо демо (куски сайта) идут через перехват Playwright. Под нагрузкой машины это
 * звено одно стоит 10–30 с (в трассе — ни одного запроса, потом сразу все), поэтому плашку
 * ждём дольше обычных 10 с — ровно здесь, не во всём тесте.
 */
const BOOT = { timeout: 30_000 };

async function enterFromTour(page: Page) {
  await page.getByTestId('tour-open').click();
  const entry = page.getByTestId('tour-contents').getByTestId('tour-practice');
  await expect(entry).toContainText('Начать тренировку');
  await entry.click();
  await expect(page.getByTestId('training-banner-text')).toHaveText(BANNER, BOOT);
}

async function pauseFlow(page: Page) {
  const pause = page.getByTestId('state-pause');
  if (!(await pause.getByTestId('pause-reason').isVisible()))
    await pause.getByTestId('pause-set-toggle').click();
  await pause.getByTestId('pause-reason').fill('тренировка: пробую паузу');
  await pause.getByTestId('pause-set-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('pause-set-confirm')).toBeEnabled();
  await dialog.getByTestId('pause-set-confirm').click();
  return { pause, dialog };
}

test('обычная загрузка: куска тренировки и её service worker нет', async ({ page }) => {
  const chunks: string[] = [];
  page.on('request', (r) => {
    const path = new URL(r.url()).pathname;
    if (TRAINING_CHUNK.test(path) || path.endsWith('/mockServiceWorker.js')) chunks.push(path);
  });
  await page.goto('/');
  await expect(page.getByTestId('attention')).toBeVisible();
  for (const tab of ['Публикация', 'Вопросы', 'Ролики']) {
    await page
      .getByRole('navigation', { name: 'Разделы' })
      .getByRole('link', { name: tab })
      .click();
    await expect(page.getByRole('heading', { level: 1 })).toHaveText(tab);
  }
  await expect(page.getByTestId('training-banner')).toHaveCount(0);
  expect(chunks).toEqual([]);
  expect(await page.evaluate(() => navigator.serviceWorker.getRegistrations())).toHaveLength(0);
});

test('тренировка от начала до конца: все задания, перезагрузка, выход — живой API не тронут', async ({
  page,
  apiHits,
  consoleErrors,
}) => {
  // CC-0159: двенадцать заданий руками и два подъёма демо-сервера — около 125 действий; под
  // нагрузкой (load 70–200) тест упирался в потолок 60 с посреди заданий без единой ошибки.
  // Это один длинный сценарий, его потолок — свой (×3), общий не трогаем.
  test.slow();
  await page.goto('/');
  await expect(page.getByTestId('attention')).toBeVisible();
  await enterFromTour(page);
  // Демо-данные на месте: шапка говорит, что фабрика — демо, записи разрешены.
  await expect(page.getByTestId('read-only-banner')).toHaveCount(0);
  const panel = page.getByTestId('training-panel');
  await expect(panel.getByTestId('training-task')).toHaveCount(12);
  await expect(panel.getByTestId('training-count')).toHaveText('0 из 12');
  const live = apiHits.length;
  const sent = apiRequests(page);
  await page.getByTestId('training-collapse').click();

  // Попросить оператора — из шапки.
  await page.getByTestId('ask-open-header').click();
  const ask = page.getByTestId('ask-dialog');
  await ask.getByTestId('ask-text').fill('Тренировка: сколько роликов ждут загрузки?');
  await ask.getByTestId('ask-send').click();
  await expect(page.getByText('Просьба отправлена оператору')).toBeVisible();
  await expect(page.getByTestId('training-last')).toHaveText(
    'Задание выполнено: Попросить оператора',
  );

  // Ответить на вопрос.
  await goTask(page, 'answer');
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Вопросы');
  const q = page.getByTestId('question').first();
  await q.getByTestId('answer-text').fill('Берём второй вариант');
  await q.getByTestId('answer-send').click();
  await expect(page.getByTestId('training-last')).toHaveText(
    'Задание выполнено: Ответить на вопрос',
  );

  // Принять ролик.
  await goTask(page, 'accept');
  await expect(page).toHaveURL(new RegExp(`batch=${encodeURIComponent(PAST)}`));
  await page.getByTestId('verdict-yes').click();
  const verdict = page.getByRole('alertdialog');
  await verdict.getByTestId('verdict-words').press('End');
  await verdict.getByTestId('verdict-words').pressSequentially('берём');
  await verdict.getByTestId('verdict-confirm').click();
  await expect(page.getByTestId('acceptance-answer-text')).toHaveText('Записано.');

  // Отказ фабрики: рычаг — и «да» в паузе получает отказ, записи нет.
  await lever(page, 'training-refuse');
  await goTask(page, 'pause');
  const first = await pauseFlow(page);
  await expect(first.dialog.getByTestId('act-error')).toHaveAttribute('data-code', 'refused');
  await first.dialog.getByRole('button', { name: 'Отмена' }).click();
  await expect(first.dialog).toBeHidden();

  // Пауза — теперь проходит: план → «да».
  const again = await pauseFlow(page);
  await expect(again.dialog).toBeHidden();
  await expect(again.pause.getByTestId('pause-done')).toContainText('Пауза поставлена');
  await expectDone(page, ['ask', 'answer', 'accept', 'refused', 'pause', 'confirm']);

  // Перезагрузка посреди тренировки: демо-сервер встаёт до первого запроса, отметки на месте.
  await page.reload();
  await expect(page.getByTestId('training-banner-text')).toHaveText(BANNER, BOOT);
  await expectDone(page, ['ask', 'answer', 'accept', 'refused', 'pause', 'confirm']);
  await expect(page.getByTestId('training-tasks-toggle')).toHaveText('Задания · 6 из 12');

  // «План устарел» и подпись холда: рычаг «промотать время», «да» — устарел, ещё раз — подписан.
  await lever(page, 'training-expire');
  await goTask(page, 'hold');
  const holds = page.getByTestId('holds');
  const row = holds.locator('[data-testid="hold"][data-signable="1"]');
  await row.getByTestId('hold-sign-toggle').click();
  await row.getByTestId('hold-sign-note').fill('посмотрел ролик на тренировке');
  await row.getByTestId('hold-sign-open').click();
  const sign = page.getByRole('alertdialog');
  await sign.getByTestId('hold-sign-confirm').click();
  await expect(sign.getByTestId('replanned')).toHaveAttribute('data-code', 'confirm_expired');
  await expect(sign.getByTestId('hold-sign-confirm')).toBeEnabled();
  await sign.getByTestId('hold-sign-confirm').click();
  await expect(sign).toBeHidden();
  await expect(page.getByTestId('toast')).toContainText('Холд снят');

  // Карточка в слот.
  await goTask(page, 'card');
  const card = page.getByTestId('card-writes');
  await card.getByTestId('card-pick-waiting').click();
  await card.getByTestId('card-batch').fill(REEL_BATCH);
  await card.getByTestId('card-place-toggle').click();
  await card.getByTestId('card-place-open').click();
  const place = page.getByRole('alertdialog');
  await place.getByTestId('card-place-confirm').click();
  await expect(card.getByTestId('place-done')).toContainText('Карточка размещена');

  // Загрузка на YouTube — только в демо.
  await goTask(page, 'upload');
  const upload = page.getByTestId('upload-writes');
  await upload.getByTestId('upload-open').click();
  const up = page.getByRole('alertdialog');
  await up.getByTestId('upload-answer').fill('да');
  await up.getByTestId('upload-confirm').click();
  await expect(upload.getByTestId('upload-done')).toContainText('Загружено на YouTube');

  // Разбор мемов: мем → «Оставить» → «Сохранить отметки».
  await goTask(page, 'meme');
  await page.locator('[data-testid="meme"][data-id="bell-curve"]').click();
  await page.getByTestId('meme-viewer').getByTestId('mark-keep').click();
  await page.getByTestId('desk-save').click();
  await expect(page.getByTestId('desk-unsaved')).toHaveText('Все отметки сохранены');

  // Цифры Studio: строки по ролику → план → «да».
  await goTask(page, 'studio');
  const studio = page.getByTestId('stats-studio');
  await studio.getByTestId('studio-entry-toggle').click();
  await studio
    .getByTestId('studio-entry-video')
    .first()
    .getByTestId('studio-lines')
    .fill('Досмотрели\n61 %');
  await studio.getByTestId('studio-entry-open').click();
  await page.getByRole('alertdialog').getByTestId('studio-entry-confirm').click();
  await expect(studio.getByTestId('studio-done')).toContainText('Цифры Studio внесены');

  const done = await panelOpen(page);
  await expect(done.getByTestId('training-count')).toHaveText('12 из 12');
  await expect(done.getByTestId('training-all-done')).toContainText('Все задания выполнены');
  await expect(done.locator('[data-done="no"]')).toHaveCount(0);

  // Ни одного запроса к живому API за всю тренировку; каждый ответил service worker.
  expect(apiHits.slice(live)).toEqual([]);
  expect(sent.length).toBeGreaterThan(20);
  // Ответ без service worker — только у запроса, оборванного самой страницей (переход, перезагрузка,
  // отменённый запрос экрана): ответа у него нет вовсе, а до живого API он не дошёл (`apiHits`
  // выше). Под нагрузкой таких больше (CC-0131), потому они не провал — провал любой другой ответ.
  const answered = await Promise.all(
    sent.map(async (r) => {
      const res = await r.response();
      if (res) return res.fromServiceWorker() ? 'sw' : `${r.method()} ${r.url()}`;
      return /ERR_ABORTED|cancel/i.test(r.failure()?.errorText ?? '')
        ? 'aborted'
        : `${r.method()} ${r.url()}: ${r.failure()?.errorText ?? 'без ответа'}`;
    }),
  );
  expect(answered.filter((a) => a !== 'sw' && a !== 'aborted')).toEqual([]);
  expect(answered.filter((a) => a === 'sw').length).toBeGreaterThan(20);

  // Выход: живые данные, демо-сервер снят, флага нет.
  await page.getByTestId('training-exit').click();
  await expect(page.getByTestId('training-banner')).toHaveCount(0);
  await expect(page.getByTestId('training-panel')).toHaveCount(0);
  await page.goto('/');
  await expect(page.getByTestId('attention')).toBeVisible();
  expect(apiHits.length).toBeGreaterThan(live);
  expect(await page.evaluate(() => sessionStorage.getItem('cc-training'))).toBeNull();
  await expect
    .poll(() =>
      page.evaluate(async () => (await navigator.serviceWorker.getRegistrations()).length),
    )
    .toBe(0);
  // Живой API за весь тест не получил ни одной записи.
  expect(apiHits.filter((h) => !h.startsWith('GET '))).toEqual([]);
  expect(unexpected(consoleErrors)).toEqual([]);
});

/**
 * Плашка на телефоне: текст — своей строкой во всю ширину (слова не рвутся), кнопки — второй,
 * вся плашка — не выше 110 px (не треть экрана).
 */
async function compactBanner(page: Page) {
  const banner = (await page.getByTestId('training-banner').boundingBox())!;
  expect(banner.height).toBeLessThanOrEqual(110);
  const text = (await page.getByTestId('training-banner-text').boundingBox())!;
  expect(text.width).toBeGreaterThanOrEqual(250);
  // Не больше двух строк: высота строки 13px-текста — около 19 px.
  expect(text.height).toBeLessThanOrEqual(40);
  const last = page.getByTestId('training-last');
  if ((await last.textContent())?.trim()) {
    const l = (await last.boundingBox())!;
    expect(l.height).toBeLessThanOrEqual(22);
  }
}

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('плашка и панель без прокрутки вбок; задание отмечается; выход — живые данные', async ({
    page,
    apiHits,
    consoleErrors,
  }) => {
    await page.goto('/');
    await expect(page.getByTestId('attention')).toBeVisible();
    await enterFromTour(page);
    // На телефоне панель сначала свёрнута: экран не закрыт, внизу — полоса «Задания».
    await expect(page.getByTestId('training-panel')).toHaveCount(0);
    await expect(page.getByTestId('training-exit')).toBeVisible();
    const handle = page.getByTestId('training-handle');
    await expect(handle).toBeInViewport({ ratio: 1 });
    await expect(handle).toContainText('Задания · 0 из 12');
    const hb = (await handle.boundingBox())!;
    expect(hb.y + hb.height).toBeLessThanOrEqual(844);
    expect(hb.y).toBeGreaterThan(844 - 80);
    await compactBanner(page);
    await noSideScroll(page);
    const live = apiHits.length;
    const panel = await panelOpen(page);
    await expect(panel.getByTestId('training-task')).toHaveCount(12);
    await noSideScroll(page);
    const box = (await panel.boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(0);
    expect(box.x + box.width).toBeLessThanOrEqual(390);

    await goTask(page, 'answer');
    const q = page.getByTestId('question').first();
    await q.getByTestId('answer-text').fill('С телефона: берём');
    await q.getByTestId('answer-send').click();
    await expectDone(page, ['answer']);
    await expect(page.getByTestId('training-last')).toHaveText(
      'Задание выполнено: Ответить на вопрос',
    );
    await compactBanner(page);
    await noSideScroll(page);
    expect(apiHits.slice(live)).toEqual([]);

    // Тост — над открытой панелью, а не поверх её низа; низ панели с полем от края.
    const sheet = await panelOpen(page);
    await sheet.getByTestId('training-reset').click();
    const toast = page.getByTestId('toast');
    await expect(toast).toContainText('Тренировка начата заново');
    const tb = (await toast.boundingBox())!;
    const sb = (await sheet.boundingBox())!;
    expect(tb.y + tb.height).toBeLessThanOrEqual(sb.y + 1);
    const exit = (await sheet.getByTestId('training-exit-panel').boundingBox())!;
    expect(exit.y + exit.height).toBeLessThanOrEqual(844 - 10);
    await page.getByTestId('training-collapse').click();
    await expect(handle).toBeInViewport({ ratio: 1 });

    await page.getByTestId('training-exit').click();
    await expect(page.getByTestId('training-banner')).toHaveCount(0);
    expect(apiHits.filter((h) => !h.startsWith('GET '))).toEqual([]);
    expect(unexpected(consoleErrors)).toEqual([]);
  });
});
