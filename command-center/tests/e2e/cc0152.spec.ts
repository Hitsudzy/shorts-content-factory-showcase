// CC-0152 (фабрика 2.20, договор 0.69.0) на подставном API: размыкатель повторов (день плана,
// плашка канала, проверка ручного запуска, строка `repeat_held` в истории), бюджет поиска YouTube
// и второй батч дня с причиной допуска, несколько окон канала (запись, 422, снятие), принятый
// ролик «не в копилке» с тёзкой.
import { REPEAT_HELD } from '../../src/mocks/batches';
import { LEFT_OUT_ALERT, LEFT_OUT_SLUG, OLDER } from '../../src/mocks/videos';
import { expect, noSideScroll, onlyHttp, openTip, test } from './fixtures';

const NBSP = '\u00a0';

test.describe('размыкатель повторов (CF-0822)', () => {
  test('день плана словами, метка с правилом, плашка у канала', async ({ page, schedule }) => {
    schedule.setScene({ breaker: true });
    await page.goto('/batches');
    const day = page.getByTestId('day-2026-10-11');
    await expect(day).toHaveAttribute('data-kind', 'nobody_available');
    await expect(day.getByTestId('day-why')).toContainText(
      `Повтор ExampleFilm придержан: батч 10.10,${NBSP}02:05${NBSP}МСК упал на «Поиск трендов», не потратив квоту.`,
    );
    await expect(day.getByTestId('day-why')).not.toContainText('Некого');
    await expect(day.getByTestId('day-next')).toContainText('ExampleFilm 12.10');
    const pill = day.locator('[data-slot="status"]').first();
    await expect(pill).toHaveText('повтор придержан');
    await openTip(page, pill, 'фабрика не запускает его снова в те же сутки квоты');
    await day.getByText('Подробнее').click();
    await expect(day.getByTestId('day-breaker-line')).toContainText('защита от повтора:');

    const card = page.getByTestId('window-example-film');
    const badge = card.getByTestId('win-breaker');
    await expect(badge).toHaveAttribute('data-held', 'true');
    await expect(badge).toContainText('повтор придержан');
    await expect(card.getByTestId('win-breaker-text')).toContainText(
      'Повтор ExampleFilm придержан',
    );
    await expect(page.getByTestId('window-example-tech').getByTestId('win-breaker')).toHaveCount(0);
  });

  test('ручной запуск: размыкатель не держит; строку тика список проверок не повторяет', async ({
    page,
    batches,
  }) => {
    batches.actions.setBreaker();
    await page.goto('/batches');
    await page.getByTestId('launch-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('launch-why')).toBeVisible();
    await expect(dialog.getByTestId('launch-breaker')).toContainText(
      'Ручной запуск защита от повтора не останавливает',
    );
    await expect(dialog.getByTestId('launch-breaker')).toContainText(
      'Фабрика сама не повторит ExampleFilm в эти сутки квоты',
    );
    await expect(dialog.getByTestId('launch-skipped')).not.toContainText('повтор того же отказа');
  });

  test('история запусков: «фабрика не повторила» — приглушённая строка, не батч', async ({
    page,
  }) => {
    await page.goto('/batches');
    const held = page.getByTestId('batch-history').getByTestId('run-held');
    await expect(held).toHaveCount(1);
    await expect(held).toContainText('ExampleTech');
    await expect(held).toContainText('повтор придержан');
    // Свёрнута той же высоты, что строка прогона (CC-0121): предложение — по раскрытию.
    await expect(held.getByTestId('run-held-text')).toBeHidden();
    await held.getByRole('button').click();
    await expect(held.getByTestId('run-held-text')).toHaveText(
      `Фабрика не повторила батч 07.10,${NBSP}05:00${NBSP}МСК: он упал на «Поиск трендов», не потратив квоту, код тот же. Батча не было`,
    );
    await held.getByText('Подробнее').click();
    await expect(held).toContainText(`упавший батч: ${REPEAT_HELD.failed_batch}`);
  });
});

test.describe('бюджет поиска и второй батч (CF-0830)', () => {
  test('блок бюджета: лимит, потрачено, осталось, батчи; подсказка — квота общая', async ({
    page,
  }) => {
    await page.goto('/batches');
    const b = page.getByTestId('search-budget');
    await expect(b).toContainText('Бюджет поиска YouTube');
    await expect(b.getByTestId('budget-limit')).toContainText('100 поисков, из них 5 в запасе');
    await expect(b.getByTestId('budget-spent')).toContainText('82');
    await expect(b.getByTestId('budget-left')).toContainText('13 до запаса (всего 18)');
    await expect(b.getByTestId('budget-held')).toHaveText(
      'Батч этих суток: ExampleFilm · 10.10, 02:05 — запустило расписание',
    );
    await expect(b.getByTestId('budget-batches')).toContainText('1 из 2');
    await expect(b.getByTestId('budget-multi')).toContainText(
      'Ни у одного канала нет нескольких окон',
    );
    await openTip(page, b.getByTestId('budget-tip'), 'общая на все каналы');
  });

  test('второй батч дня — с причиной допуска; отказ по бюджету — «ещё батча не будет»', async ({
    page,
    schedule,
  }) => {
    schedule.setScene({ budget: true });
    await page.goto('/batches');
    await expect(page.getByTestId('search-budget').getByTestId('budget-multi')).toContainText(
      'Второй батч в сутки квоты может взять: ExampleFilm, ExampleTech',
    );
    const more = page.getByTestId('day-2026-10-12').getByTestId('day-more-batch');
    await expect(more).toHaveCount(1);
    await expect(more).toContainText('Ещё батч: ExampleTech');
    await expect(more).toContainText('окно 05:30–08:30 МСК');
    const ok = more.getByTestId('day-more-admission');
    await expect(ok).toHaveAttribute('data-reason', 'ok');
    await expect(ok).toContainText('допущен по бюджету: потрачено 64 + ожидается 18 = 82 из 95');
    // `why` фабрики — только под «Подробнее».
    await expect(more.getByText(/^фабрика:/)).toBeHidden();

    // Тот же канал в день, где батч уже был: строка дня это говорит — «ещё батча не будет»
    // только под «Подробнее».
    const today = page.getByTestId('day-2026-10-10');
    await expect(today.getByTestId('day-more-held')).toHaveCount(0);
    const quiet = today.getByTestId('day-held-quiet');
    await expect(quiet).toBeHidden();
    await today.getByText('Подробнее').click();
    await expect(quiet).toContainText('ещё батча не будет: ExampleFilm');
    await expect(quiet).toContainText(
      'не хватит бюджета поиска: потрачено 82 + ожидается 64 = 146, а можно не больше 95',
    );
  });
});

test.describe('несколько окон канала (CF-0830)', () => {
  test.use({ expectCleanConsole: false });
  test('записать окна, 422 — больше четырёх и не время, снять окна', async ({
    page,
    schedule,
    consoleErrors,
  }) => {
    await page.goto('/batches');
    const card = page.getByTestId('window-example-tech');
    const field = card.getByTestId('win-windows');
    await expect(field).toHaveValue('');
    await expect(card.getByTestId('win-windows-note')).toHaveText(
      `Пусто${NBSP}— одно окно с «Начала окна»`,
    );

    await field.fill('05:30, 17:00');
    await expect(card.getByTestId('win-window-overridden')).toHaveText('Не действует: заданы окна');
    const put = page.waitForRequest(
      (r) => r.method() === 'PUT' && r.url().endsWith('/api/schedule/channels/example-tech'),
    );
    await card.getByTestId('win-save').click();
    expect((await put).postDataJSON().windows).toEqual(['05:30', '17:00']);
    await expect(card.getByTestId('win-saved')).toContainText('окна: — → 05:30, 17:00');
    await expect(field).toHaveValue('05:30, 17:00');

    await field.fill('01:00, 02:00, 03:00, 04:00, 05:00');
    await card.getByTestId('win-save').click();
    await expect(card.getByTestId('refusal-message')).toHaveText(
      'Настройка не принята: окна запуска - не больше 4.',
    );
    await field.fill('05:30, 25:00');
    await card.getByTestId('win-save').click();
    await expect(card.getByTestId('refusal-message')).toHaveText(
      "Настройка не принята: окна запуска: '25:00' - время ЧЧ:ММ, 00:00-23:59.",
    );

    await field.fill('');
    await expect(card.getByTestId('win-windows-note')).toHaveText(
      `Окна снимутся${NBSP}— снова одно окно с «Начала окна»`,
    );
    const off = page.waitForRequest(
      (r) => r.method() === 'PUT' && r.url().endsWith('/api/schedule/channels/example-tech'),
    );
    await card.getByTestId('win-save').click();
    expect((await off).postDataJSON().windows).toEqual([]);
    await expect(card.getByTestId('win-saved')).toContainText('окна: 05:30, 17:00 → —');
    expect(schedule.writes.filter((w) => w.kind === 'settings')).toHaveLength(2);
    onlyHttp(consoleErrors, 422);
  });
});

test('приёмка: принятый ролик «не в копилке» — громко, с тёзкой, без двойной приставки', async ({
  page,
}) => {
  await page.goto(`/videos?batch=${encodeURIComponent(OLDER)}&v=${LEFT_OUT_SLUG}`);
  await page.getByTestId('verdict-yes').click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByTestId('verdict-words').press('End');
  await dialog.getByTestId('verdict-words').pressSequentially('да');
  await dialog.getByTestId('verdict-confirm').click();
  const answer = page.getByTestId('acceptance-answer');
  const mark = answer.getByTestId('left-out');
  await expect(mark).toContainText('Не в копилке');
  // Название — как центр показывает ролик (у него нет карточки — имя словами).
  await expect(mark.getByTestId('left-out-alert')).toHaveText(
    `Ролик «Usb c myths» принят, но в копилку не попал: такое имя уже занято роликом другого батча`,
  );
  await expect(mark.getByTestId('left-out-namesake')).toHaveText('У того ролика другая тема');
  // Служебное — строка фабрики, батч, пути — только под «Подробнее».
  for (const raw of [LEFT_OUT_ALERT, '2026-10-06T0210Z', 'publish/example-film/usb-c-myths.mp4'])
    await expect(mark.getByText(raw, { exact: false }).first()).toBeHidden();
  await mark.getByText('Подробнее').click();
  await expect(mark).toContainText(`фабрика: ${LEFT_OUT_ALERT}`);
  await expect(mark).toContainText('тёзка: publish/example-film/usb-c-myths.mp4');
  await expect(answer.getByTestId('acceptance-answer-queued')).toHaveAttribute(
    'data-left-out',
    'true',
  );
  await expect(answer).not.toContainText('НЕ В КОПИЛКЕ: НЕ В КОПИЛКЕ');
  await expect(mark).not.toContainText('НЕ В КОПИЛКЕ');
});

test('телефон: бюджет, второй батч и окна — без прокрутки вбок', async ({ page, schedule }) => {
  schedule.setScene({ budget: true, breaker: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/batches');
  await expect(page.getByTestId('search-budget')).toBeVisible();
  await expect(page.getByTestId('window-example-tech').getByTestId('win-windows')).toBeVisible();
  await noSideScroll(page);
});
