// CC-0019: «попросить оператора» и просьбы в табе «Вопросы» на подставной очереди
// (src/mocks/requests.ts): общая кнопка в шапке и кнопки на ролике, батче, канале с
// подставленным контекстом, окно с видимым «Откуда» и тултипом «кто это сделает», список со
// статусами словами, ответом и доставкой в Telegram, «закрыть» и «отменить» с одним
// подтверждением, отказ строкой фабрики, «только смотреть», телефон.
import type { Page } from '@playwright/test';

import { PAST, RUNNING } from '../../src/mocks/batches';
import { fixtures, READ_ONLY_REASON, writesModes } from '../../src/mocks/fixtures';
import { expect, noSideScroll, openTip, test } from './fixtures';

const card = (page: Page, rid: string) =>
  page.locator(`[data-testid="request"][data-rid="${rid}"]`);
const dialog = (page: Page) => page.getByTestId('ask-dialog');

test('шапка → окно: контекст — экран, тултип «кто это сделает», просьба уходит и видна в «Просьбах»', async ({
  page,
  requests,
}) => {
  await page.goto('/publishing');
  const header = page.getByTestId('ask-open-header');
  await openTip(page, header, 'Центр сам ничего не исполняет');
  await header.click();
  const d = dialog(page);
  await expect(d.getByRole('heading')).toHaveText('Попросить оператора');
  await expect(d.getByTestId('ask-context')).toContainText('Публикация');
  await openTip(page, d.getByTestId('ask-how'), 'сессия-оператор');
  await openTip(
    page,
    d.getByTestId('ask-how'),
    'придёт сюда, в «Вопросы» → «Просьбы», и в Telegram',
  );
  const send = d.getByTestId('ask-send');
  await expect(send).toHaveAttribute('aria-disabled', 'true');
  await openTip(page, send, 'Сначала напишите просьбу');
  await d.getByTestId('ask-text').fill('Сколько роликов ждут загрузки на этой неделе?');
  await send.click();
  await expect(send).toHaveText('Отправляю…');
  await expect(page.getByText('Просьба отправлена оператору')).toBeVisible();
  await expect(d).toHaveCount(0);
  expect(requests.writes).toEqual([
    {
      path: '/api/requests',
      body: {
        text: 'Сколько роликов ждут загрузки на этой неделе?',
        channel: null,
        context: { screen: '/publishing', area: 'Публикация' },
      },
    },
  ]);

  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Вопросы' })
    .click();
  await page.getByTestId('view-requests').click();
  await expect(page).toHaveURL(/\/questions\?view=requests$/);
  const fresh = card(page, 'R7');
  await expect(fresh).toHaveAttribute('data-status', 'open');
  await expect(fresh.locator('[data-slot="status"]')).toHaveText('открыта');
  await expect(fresh.getByTestId('request-context')).toHaveText('Откуда: Публикация');
});

test('контекст подставлен сам: ролик, батч, канал', async ({ page, requests }) => {
  await page.goto(`/videos?batch=${encodeURIComponent(PAST)}&v=delver`);
  await openTip(page, page.getByTestId('ask-video'), 'об этом ролике');
  await page.getByTestId('ask-video').click();
  const ctx = dialog(page).getByTestId('ask-context');
  await expect(ctx).toContainText('Ролики');
  await expect(ctx).toContainText('ExampleFilm');
  await expect(ctx.locator('[data-row="batch"]')).toBeVisible();
  await expect(ctx.locator('[data-row="video"]')).toBeVisible();
  // Ключи и JSON — только под «подробнее».
  const json = dialog(page).getByTestId('ask-context-json');
  await expect(json).toBeHidden();
  await dialog(page).getByText('Подробнее').click();
  await expect(json).toContainText('"video": "delver"');
  await dialog(page).getByTestId('ask-text').fill('Музыка обрывается на 0:42');
  await dialog(page).getByTestId('ask-text').press('Control+Enter');
  await expect(page.getByText('Просьба отправлена оператору')).toBeVisible();
  expect(requests.writes[0]?.body).toMatchObject({
    channel: 'example-film',
    context: { area: 'Ролики', channel: 'example-film', batch: PAST, video: 'delver' },
  });

  await page.goto('/batches');
  const batch = page.locator(`[data-testid="open-batch"][data-batch="${RUNNING}"]`);
  await batch.getByTestId('ask-batch').click();
  await expect(dialog(page).getByTestId('ask-context')).toContainText('Батчи');
  await expect(dialog(page).locator('[data-row="batch"]')).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(dialog(page)).toHaveCount(0);

  await page.goto('/channels/example-science');
  await page.getByTestId('ask-channel').click();
  await expect(dialog(page).getByTestId('ask-context')).toContainText('ExampleScience');
  await dialog(page).getByRole('button', { name: 'Отмена' }).click();
  await expect(dialog(page)).toHaveCount(0);
  expect(requests.writes).toHaveLength(1);
});

test('список просьб: статусы словами, ответ, Telegram; тултипы; номера — в «подробнее»', async ({
  page,
}) => {
  await page.goto('/questions');
  await openTip(
    page,
    page.getByRole('navigation', { name: 'Разделы' }).getByRole('link', { name: 'Вопросы' }),
    'Ответ на просьбы: 2',
  );
  await expect(page.getByTestId('view-requests').locator('[data-slot="count"]')).toHaveText('2');
  await page.getByTestId('view-requests').click();
  await expect(page.getByTestId('answered-requests').getByTestId('request')).toHaveCount(2);
  await expect(page.getByTestId('pending-requests').getByTestId('request')).toHaveCount(2);
  await expect(card(page, 'R5').locator('[data-slot="status"]')).toHaveText('взята оператором');
  await openTip(page, card(page, 'R5').locator('[data-slot="status"]'), 'взяла просьбу в работу');
  const r3 = card(page, 'R3');
  await expect(r3.getByTestId('request-answer')).toContainText('Трек короче ролика');
  await expect(r3.getByTestId('request-notify')).toHaveText('дошёл в Telegram');
  await openTip(
    page,
    r3.getByTestId('request-notify').locator('[data-slot="status"]'),
    'пришёл вам в Telegram',
  );
  const r4 = card(page, 'R4');
  await expect(r4.getByTestId('request-notify')).toHaveAttribute('data-notify', 'failed');
  await openTip(
    page,
    r4.getByTestId('request-notify').locator('[data-slot="status"]'),
    'отправить его ещё раз может оператор',
  );
  const more = r4.locator('[data-slot="more"]');
  await expect(more.getByText('просьба: R4')).toBeHidden();
  await more.getByText('Подробнее').click();
  await expect(more.getByText('просьба: R4')).toBeVisible();
  await expect(more).toContainText('telegram: 502 Bad Gateway');
  await expect(page.getByRole('main').getByText('R3', { exact: true })).toHaveCount(0);
  await expect(
    page.getByTestId('requests-history').getByTestId('request-history-item'),
  ).toHaveCount(2);
});

test('«Закрыть» у отвеченной; «Отменить…» — одно подтверждение', async ({ page, requests }) => {
  await page.goto('/questions?view=requests');
  const r3 = card(page, 'R3');
  await openTip(page, r3.getByTestId('request-close'), 'Ответ прочитан');
  await expect(r3.getByTestId('request-cancel')).toHaveCount(0);
  await r3.getByTestId('request-close').click();
  await expect(page.getByText('Просьба закрыта')).toBeVisible();
  await expect(r3).toHaveCount(0);
  const first = page.getByTestId('requests-history').getByTestId('request-history-item').first();
  await expect(first).toHaveAttribute('data-rid', 'R3');
  await expect(first.getByTestId('request-history-state')).toContainText('Закрыта');
  await expect(first.getByTestId('request-history-state')).toContainText('вами');
  await expect(page.getByTestId('view-requests').locator('[data-slot="count"]')).toHaveText('1');

  const r5 = card(page, 'R5');
  await expect(r5.getByTestId('request-close')).toHaveCount(0);
  await openTip(page, r5.getByTestId('request-cancel'), 'одно подтверждение');
  await r5.getByTestId('request-cancel').click();
  const d = page.getByRole('alertdialog');
  await expect(d).toContainText('Отменить просьбу?');
  await expect(d).toContainText('Сдвинь батч ExampleFilm');
  await d.getByTestId('request-cancel-confirm').click();
  await expect(d.getByTestId('request-cancel-confirm')).toHaveText('Отменяю…');
  await expect(d).toHaveCount(0);
  await expect(page.getByText('Просьба отменена')).toBeVisible();
  await expect(r5).toHaveCount(0);
  await expect(
    page
      .locator('[data-testid="request-history-item"][data-rid="R5"]')
      .getByTestId('request-history-state'),
  ).toContainText('Отменена');
  expect(requests.writes.map((w) => w.path)).toEqual([
    '/api/requests/R3/close',
    '/api/requests/R5/cancel',
  ]);
});

test.describe('отказ фабрики', () => {
  test.use({ expectCleanConsole: false });

  test('просьба длиннее потолка — строкой фабрики в окне; закрытая с другой стороны — тостом', async ({
    page,
    requests,
    consoleErrors,
  }) => {
    await page.goto('/');
    requests.next = { status: 422, code: 'text_too_long' };
    await page.getByTestId('ask-open-header').click();
    await dialog(page).getByTestId('ask-text').fill('Проверь всё');
    await dialog(page).getByTestId('ask-send').click();
    const err = dialog(page).getByTestId('create-error');
    await expect(err).toContainText('Просьба не отправлена');
    await expect(err).toContainText('Просьба длиннее 4000 знаков - сократите её.');
    await expect(dialog(page).getByTestId('ask-text')).toHaveValue('Проверь всё');
    await dialog(page).getByRole('button', { name: 'Отмена' }).click();

    await page.goto('/questions?view=requests');
    await expect(card(page, 'R4')).toBeVisible();
    // Пока человек читал, просьбу закрыли с другой стороны.
    requests.requests = requests.requests.map((r) =>
      r.id === 'R4' ? { ...r, status: 'closed', closed_by: 'user', closed_at: r.answered_at } : r,
    );
    await card(page, 'R4').getByTestId('request-close').click();
    await expect(page.getByTestId('toast').getByText('Просьба R4 уже закрыта.')).toBeVisible();
    await expect(card(page, 'R4')).toHaveCount(0);
    expect(consoleErrors.filter((e) => !/status of (409|422)/.test(e))).toEqual([]);
  });
});

test('«только смотреть»: «попросить», «Закрыть», «Отменить…» погашены причиной, записей нет', async ({
  page,
  requests,
}) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  await page.goto('/questions?view=requests');
  const header = page.getByTestId('ask-open-header');
  await expect(header).toHaveAttribute('data-writes', 'off');
  await openTip(page, header, READ_ONLY_REASON);
  await header.click({ force: true });
  await expect(dialog(page)).toHaveCount(0);
  const close = card(page, 'R3').getByTestId('request-close');
  await expect(close).toHaveAttribute('aria-disabled', 'true');
  await openTip(page, close, 'Только смотреть');
  await close.click({ force: true });
  const cancel = card(page, 'R6').getByTestId('request-cancel');
  await expect(cancel).toHaveAttribute('aria-disabled', 'true');
  await cancel.click({ force: true });
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  await expect(page.getByTestId('ask-new')).toHaveAttribute('data-writes', 'off');
  expect(requests.writes).toEqual([]);
});

test.describe('телефон', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('просьбы и окно «попросить» без прокрутки вбок; в шапке — одна иконка', async ({ page }) => {
    await page.goto('/questions?view=requests');
    await expect(page.getByTestId('answered-requests').getByTestId('request')).toHaveCount(2);
    await noSideScroll(page);
    const header = page.getByTestId('ask-open-header');
    await expect(header).toHaveAccessibleName('Попросить оператора');
    await expect(header.getByText('Попросить оператора')).toBeHidden();
    await header.click();
    await expect(dialog(page).getByTestId('ask-context')).toContainText('Вопросы');
    await noSideScroll(page);
  });
});
