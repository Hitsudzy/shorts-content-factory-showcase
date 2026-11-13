// CC-0017: экран «Вопросы» на подставном журнале (src/mocks/questions.ts): счётчик на табе и на
// главной, ответ прямо в карточке, «решено» с одним подтверждением, история, фильтры в адресе,
// тултипы, отказ словами, «только смотреть» (кнопки погашены, записей нет), телефон.
import type { Page } from '@playwright/test';

import { fixtures, READ_ONLY_REASON, writesModes } from '../../src/mocks/fixtures';
import { expect, noSideScroll, onlyHttp, openTip, test } from './fixtures';

const card = (page: Page, qid: string) =>
  page.locator(`[data-testid="question"][data-qid="${qid}"]`);
const tabCount = (page: Page) =>
  page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Вопросы', exact: true })
    .locator('[data-slot="count"]');

test('главная → «К вопросам» → ответ в карточке: счётчики на табе и на главной падают', async ({
  page,
  questions,
}) => {
  await page.goto('/');
  await expect(page.getByTestId('attention-questions')).toHaveText(
    'Вопросов ждут вашего ответа: 3.',
  );
  await expect(tabCount(page)).toHaveText('3');
  await openTip(
    page,
    page.getByRole('navigation', { name: 'Разделы' }).getByRole('link', { name: 'Вопросы' }),
    'Ждут ответа: 3',
  );
  const box = page.getByTestId('questions-card');
  await expect(box.getByTestId('questions-item')).toHaveCount(2);
  await page.getByRole('link', { name: /К вопросам/ }).click();
  await expect(page).toHaveURL(/\/questions$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Вопросы');

  const q = card(page, 'Q9');
  const send = q.getByTestId('answer-send');
  await expect(send).toHaveAttribute('aria-disabled', 'true');
  await openTip(page, send, 'Сначала напишите ответ');
  await q.getByTestId('answer-text').fill('Да, взять Entourage пятой');
  await send.click();
  await expect(send).toHaveText('Отправляю…');
  await expect(page.getByText('Ответ отправлен фабрике')).toBeVisible();
  await expect(q).toHaveAttribute('data-status', 'answered');
  await expect(q.getByTestId('question-answer')).toHaveText('Да, взять Entourage пятой');
  await expect(tabCount(page)).toHaveText('2');
  expect(questions.writes).toEqual([
    {
      path: '/api/questions/Q9/answer',
      body: { text: 'Да, взять Entourage пятой', by: 'user', accept: false },
    },
  ]);

  await page.getByRole('link', { name: 'Главная' }).click();
  await expect(page.getByTestId('attention-questions')).toHaveText(
    'Вопросов ждут вашего ответа: 2.',
  );
});

test('«Решено…» — одно подтверждение; вопрос уходит в историю с заметкой', async ({
  page,
  questions,
}) => {
  await page.goto('/questions');
  const q = card(page, 'Q6');
  await openTip(page, q.getByTestId('resolve-open'), 'Закрыть вопрос: он уйдёт в историю');
  await q.getByTestId('resolve-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toContainText('Отметить вопрос решённым?');
  await dialog.getByTestId('resolve-note').fill('переразрешил доступ 10.10');
  await dialog.getByTestId('resolve-confirm').click();
  await expect(dialog.getByTestId('resolve-confirm')).toHaveText('Записываю…');
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText('Вопрос отмечен решённым')).toBeVisible();
  await expect(q).toHaveCount(0);
  const first = page.getByTestId('history').getByTestId('history-item').first();
  await expect(first).toHaveAttribute('data-qid', 'Q6');
  await expect(first.getByTestId('history-resolved')).toContainText(
    'вами · переразрешил доступ 10.10',
  );
  await expect(tabCount(page)).toHaveText('2');
  expect(questions.writes.map((w) => w.path)).toEqual(['/api/questions/Q6/resolve']);
});

test('тултипы: состояние вопроса, источник; номера — только в «подробнее»', async ({ page }) => {
  await page.goto('/questions');
  const q = card(page, 'Q7');
  await openTip(page, q.locator('[data-slot="status"]'), 'Ответ записан в журнал фабрики');
  await openTip(page, q.getByTestId('question-source'), 'Аналитик: просмотры, удержание');
  const more = card(page, 'Q6').locator('[data-slot="more"]');
  await expect(more.getByText('вопрос: Q6')).toBeHidden();
  await more.getByText('Подробнее').click();
  await expect(more.getByText('вопрос: Q6')).toBeVisible();
  await expect(more.getByText('ссылка: agents/publisher/publisher_auth.py')).toBeVisible();
  await expect(page.getByRole('main').getByText('Q9', { exact: true })).toHaveCount(0);
});

test('фильтры по источнику и каналу живут в адресе', async ({ page }) => {
  await page.goto('/questions?source=publisher-auth');
  await expect(page.getByTestId('question')).toHaveCount(1);
  await expect(page.getByTestId('filter-source')).toHaveValue('publisher-auth');
  await page.getByTestId('filter-source').selectOption('');
  // Дождаться адреса: два выбора подряд до перерисовки — второй собрал бы адрес из прежнего
  // (react-router отдаёт в функцию параметры последней отрисовки), и source остался бы.
  await expect(page).not.toHaveURL(/source=/);
  // Адрес меняется раньше отрисовки (переход react-router — в startTransition): ждём и сам
  // экран без фильтра, иначе под нагрузкой второй выбор вернул бы source=publisher-auth.
  await expect(page.getByTestId('question')).toHaveCount(4);
  await page.getByTestId('filter-channel').selectOption({ label: 'ExampleScience' });
  await expect(page).toHaveURL(/channel=example-science/);
  await expect(page.getByTestId('question')).toHaveCount(0);
  // Открытых под фильтр нет (первая пустышка — у открытых; история ниже, пока читается
  // под новым фильтром, на миг тоже бывает пустой — отсюда `.first()`, а не строгий поиск).
  await expect(page.getByText('Под фильтр ничего не попало').first()).toBeVisible();
  await expect(page.getByTestId('history').getByTestId('history-item')).toHaveCount(1);
  await page.getByTestId('filters-reset').click();
  await expect(page.getByTestId('question')).toHaveCount(4);
  await expect(page).toHaveURL(/\/questions$/);
});

test.describe('отказ фабрики', () => {
  test.use({ expectCleanConsole: false });

  test('вопрос уже решён — словами, строка фабрики под «подробнее», список перечитан', async ({
    page,
    questions,
    consoleErrors,
  }) => {
    await page.goto('/questions');
    await expect(card(page, 'Q8')).toBeVisible();
    // Пока человек писал, вопрос закрыли с другой стороны (скрипт фабрики сам).
    questions.questions = questions.questions.map((x) =>
      x.id === 'Q8'
        ? { ...x, status: 'resolved', resolved_by: 'footage-indexer', resolved_at: x.created }
        : x,
    );
    const q = card(page, 'Q8');
    await q.getByTestId('answer-text').fill('взять');
    await q.getByTestId('answer-send').click();
    // Карточка уйдёт из открытых вместе с отказом, поэтому он ещё и тостом.
    await expect(page.getByTestId('toast').getByText('Вопрос уже решён')).toBeVisible();
    await expect(q).toHaveCount(0);
    await expect(
      page.locator('[data-testid="history-item"][data-qid="Q8"]').getByTestId('history-resolved'),
    ).toContainText('Футаж');
    onlyHttp(consoleErrors, 409);
  });
});

test('«только смотреть»: «Отправить» и «Решено…» погашены причиной, записей нет', async ({
  page,
  questions,
}) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  await page.goto('/questions');
  const q = card(page, 'Q9');
  await q.getByTestId('answer-text').fill('да');
  const send = q.getByTestId('answer-send');
  await expect(send).toHaveAttribute('data-writes', 'off');
  await send.click({ force: true });
  await q.getByTestId('answer-text').press('Control+Enter');
  await openTip(page, send, `Только смотреть: ${READ_ONLY_REASON}`);
  const resolve = q.getByTestId('resolve-open');
  await expect(resolve).toHaveAttribute('data-writes', 'off');
  await resolve.click({ force: true });
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  expect(questions.writes).toEqual([]);
});

test('телефон: одна колонка, без прокрутки вбок; ответ работает', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/questions');
  await expect(page.getByTestId('question')).toHaveCount(4);
  await noSideScroll(page);
  const q = card(page, 'Q8');
  await q.getByTestId('answer-text').fill('Снять тему');
  await q.getByTestId('answer-send').click();
  await expect(q).toHaveAttribute('data-status', 'answered');
  await noSideScroll(page);
});

// CC-0086: предложенное решение — плейсхолдером, «Принять предложение» одним нажатием,
// «Вставить и поправить», «почему» тултипом, пометка у ответа, строка на главной.
test.describe('CC-0086: предложенное решение @cc-0086', () => {
  test('главная — предложение строкой; экран — плейсхолдер, «почему», «принять» одной записью', async ({
    page,
    questions,
  }) => {
    await page.goto('/');
    const home = page
      .getByTestId('questions-card')
      .locator('[data-testid="questions-item"][data-qid="Q9"]');
    await expect(home.getByTestId('questions-suggestion')).toHaveText(
      'Предложение: Да, взять Entourage пятой.',
    );
    await page.goto('/questions');
    const q = card(page, 'Q9');
    await expect(q.getByTestId('answer-text')).toHaveAttribute(
      'placeholder',
      'Да, взять Entourage пятой.',
    );
    await expect(q.getByTestId('answer-text')).toHaveValue('');
    await openTip(page, q.getByTestId('suggestion-why'), /меньше двух пунктов до порога/);
    await openTip(page, q.getByTestId('suggestion-accept'), /одним нажатием/);
    await expect(card(page, 'Q6').getByTestId('suggestion-accept')).toHaveCount(0);
    await expect(card(page, 'Q6').getByTestId('answer-text')).toHaveAttribute(
      'placeholder',
      'Ваш ответ — словами',
    );
    await q.getByTestId('suggestion-accept').click();
    await expect(page.getByText('Предложение принято — ответ отправлен фабрике')).toBeVisible();
    await expect(q).toHaveAttribute('data-status', 'answered');
    await expect(q.getByTestId('question-answer')).toHaveText('Да, взять Entourage пятой.');
    await expect(q.getByTestId('answer-kind')).toHaveText('принято предложение');
    await expect(card(page, 'Q7').getByTestId('answer-kind')).toHaveText('свой ответ');
    expect(questions.writes).toEqual([
      {
        path: '/api/questions/Q9/answer',
        body: { by: 'user', accept: true, suggested_at: '2026-10-10T06:40:00Z' },
      },
    ]);
  });

  test('«Вставить и поправить» — текст в поле, правка уходит своим ответом', async ({
    page,
    questions,
  }) => {
    await page.goto('/questions');
    const q = card(page, 'Q9');
    await q.getByTestId('suggestion-paste').click();
    const field = q.getByTestId('answer-text');
    await expect(field).toHaveValue('Да, взять Entourage пятой.');
    await expect(field).toBeFocused();
    await expect(q.getByTestId('suggestion-accept')).toHaveAttribute('aria-disabled', 'true');
    await field.press('End');
    await field.pressSequentially(' Шестой — Partition.');
    await q.getByTestId('answer-send').click();
    await expect(q.getByTestId('answer-kind')).toHaveText('свой ответ');
    expect(questions.writes[0]?.body).toEqual({
      text: 'Да, взять Entourage пятой. Шестой — Partition.',
      by: 'user',
      accept: false,
    });
  });

  test.describe('отказ: предложение сменилось', () => {
    test.use({ expectCleanConsole: false });

    test('словами, ничего не записано, новое предложение в поле; второе «принять» проходит', async ({
      page,
      questions,
      consoleErrors,
    }) => {
      await page.setViewportSize({ width: 390, height: 844 });
      await page.goto('/questions');
      const q = card(page, 'Q8');
      await q.getByTestId('suggestion-accept').click();
      const err = q.getByTestId('answer-error');
      await expect(err).toContainText('Предложение изменилось');
      await expect(err).toContainText('ничего не записано');
      await expect(q).toHaveAttribute('data-status', 'open');
      await expect(q.getByTestId('answer-text')).toHaveAttribute(
        'placeholder',
        'Снять тему и взять запасную «Pixel 10 battery» из вчерашних трендов.',
      );
      await noSideScroll(page);
      await q.getByTestId('suggestion-accept').click();
      await expect(q).toHaveAttribute('data-status', 'answered');
      await expect(q.getByTestId('answer-kind')).toHaveText('принято предложение');
      expect(questions.writes.map((w) => w.body)).toEqual([
        { by: 'user', accept: true, suggested_at: '2026-10-10T05:20:00Z' },
        { by: 'user', accept: true, suggested_at: '2026-10-10T06:55:00Z' },
      ]);
      onlyHttp(consoleErrors, 409);
    });
  });
});
