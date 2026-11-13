// Приёмка ролика (CC-0062): «Да» со словами (как набраны), «Нет» без причины — отказ фабрики
// как есть, «Нет» с новым кодом причины, повторный вердикт через «почему меняем», вердикт под
// идущим батчем — «ждёт конца батча», «Переделать» — просьба ещё не в очереди, только смотреть
// гасит, 409 `not_working_factory` посреди сессии, телефон без прокрутки вбок; главная —
// «Ролики ждут решения» по последнему батчу; CC-0175 — почему автосборка карточки не
// запустилась (`card_build.why`). Подставной API — с состоянием.
import type { Page } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import { ACCEPT_BUILD_REFUSED } from '../../src/mocks/cards';
import { fixtures, READ_ONLY_REASON, writesModes } from '../../src/mocks/fixtures';
import { queuedBuildRefused } from '../../src/mocks/videos';
import { expect, noSideScroll, onlyHttp, openTip, test } from './fixtures';

const at = (slug: string) => `/videos?batch=${encodeURIComponent(PAST)}&v=${slug}`;

async function verdict(page: Page, v: 'yes' | 'no' | 'redo') {
  await page.getByTestId(`verdict-${v}`).click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('verdict-form')).toHaveAttribute('data-verdict', v);
  return dialog;
}

/** Не-GET запросы страницы к API. */
const writesOf = (page: Page) => {
  const sent: string[] = [];
  page.on('request', (r) => {
    if (r.method() !== 'GET' && r.url().includes('/api/'))
      sent.push(`${r.method()} ${new URL(r.url()).pathname}`);
  });
  return sent;
};

test('«Да»: слова с именем ролика заготовлены и уходят как набраны; «записано», вердикт в списке', async ({
  page,
  videos,
}) => {
  await page.goto(at('delver'));
  const dialog = await verdict(page, 'yes');
  const words = dialog.getByTestId('verdict-words');
  await expect(words).toHaveValue('delver — ');
  await words.press('End');
  await words.pressSequentially('берём  ');
  await dialog.getByTestId('verdict-confirm').click();
  await expect(dialog.getByTestId('verdict-confirm')).toHaveText('Записываю…');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  const answer = page.getByTestId('acceptance-answer');
  await expect(answer.getByTestId('acceptance-answer-text')).toHaveText('Записано.');
  await answer.locator('[data-slot="more"] > summary').click();
  await expect(answer).toContainText('коммит: Приёмка: delver принят (user (центр))');
  await expect(page.getByTestId('acceptance-verdict')).toHaveText('принят');
  // На экране — название ролика вместо имени-латиницы; фабрике слова уходят как набраны.
  await expect(page.getByTestId('acceptance-words')).toContainText(
    '«Delver: the one-take mine scene nobody believed was real — берём',
  );
  expect(videos.accepted.map((a) => a.body.words)).toEqual(['delver — берём  ']);
  // Обложка в списке — тоже перечитана.
  await expect(
    page.locator('[data-testid="reel"][data-slug="delver"] [data-testid="reel-state"]'),
  ).toContainText('принят');
});

test.describe('отказы фабрики', () => {
  test.use({ expectCleanConsole: false });

  test('«Нет» без причины — сообщение фабрики как есть, код под «подробнее», окно открыто', async ({
    page,
    videos,
    consoleErrors,
  }) => {
    await page.goto(at('delver'));
    const dialog = await verdict(page, 'no');
    await dialog.getByTestId('verdict-confirm').click();
    await expect(dialog.getByTestId('refusal-message')).toHaveText(
      'Отказ без причины не записывается - нужна причина одной фразой.',
    );
    const more = dialog.locator('[data-slot="refusal"] [data-slot="more"]');
    await expect(more.getByText('код: rejection_without_reason')).toBeHidden();
    await more.locator('> summary').click();
    await expect(more.getByText('код: rejection_without_reason')).toBeVisible();
    await expect(dialog.getByTestId('verdict-words')).toHaveValue('delver — ');
    expect(videos.accepted).toEqual([]);
    onlyHttp(consoleErrors, 422);
  });

  test('повторный вердикт: verdict_already_given открывает «почему меняем», с ним — записано', async ({
    page,
    videos,
    consoleErrors,
  }) => {
    await page.goto(at('delver'));
    await expect(page.getByTestId('acceptance-verdict')).toHaveText('ждёт решения');
    // Вердикт дали из терминала: экран ещё не знает.
    videos.setAcceptance(PAST, 'delver', { verdict: 'accepted', answer: 'delver да' });
    const dialog = await verdict(page, 'no');
    await expect(dialog.getByTestId('verdict-amend')).toHaveCount(0);
    await dialog.getByTestId('verdict-reason').fill('хук скучный');
    await dialog.getByTestId('verdict-code').selectOption('weak_hook');
    await dialog.getByTestId('verdict-confirm').click();
    await expect(dialog.getByTestId('refusal-message')).toContainText(
      'У ролика «delver» уже есть вердикт',
    );
    await dialog.getByTestId('verdict-amend').fill('пересмотрел — хук всё-таки скучный');
    await dialog.getByTestId('verdict-confirm').click();
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
    await expect(page.getByTestId('acceptance-answer-text')).toHaveText('Записано.');
    await expect(page.getByTestId('acceptance-verdict')).toHaveText('отклонён');
    expect(videos.accepted[0]!.body).toMatchObject({
      verdict: 'no',
      reason_code: 'weak_hook',
      amend: 'пересмотрел — хук всё-таки скучный',
    });
    // Теперь вердикт известен: поле открыто сразу.
    const again = await verdict(page, 'yes');
    await expect(again.getByTestId('verdict-amend')).toBeVisible();
    onlyHttp(consoleErrors, 422);
  });

  test('телефон: окно вердикта и карточка приёмки без прокрутки вбок', async ({
    page,
    consoleErrors,
  }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto(at('delver'));
    await expect(page.getByTestId('verdict-yes')).toBeVisible();
    const noHScroll = () =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
      );
    expect(await noHScroll()).toBe(true);
    const dialog = await verdict(page, 'no');
    await dialog.getByTestId('verdict-code').selectOption({ label: 'новый код…' });
    await dialog.getByTestId('verdict-confirm').click();
    await expect(dialog.getByTestId('refusal-message')).toBeVisible();
    const box = await dialog.boundingBox();
    expect(box!.x).toBeGreaterThanOrEqual(0);
    expect(box!.x + box!.width).toBeLessThanOrEqual(375);
    expect(await noHScroll()).toBe(true);
    onlyHttp(consoleErrors, 422);
  });

  test('409 not_working_factory посреди сессии: сообщение как есть, кнопки гаснут', async ({
    page,
    consoleErrors,
  }) => {
    const reason = 'основной чекаут не на main (cc/api)';
    let off = false;
    await page.route('**/api/health', (route) =>
      route.fulfill({
        json: off
          ? { ...fixtures.health, writes: false, writes_reason: reason, writes_dev: false }
          : fixtures.health,
      }),
    );
    await page.route('**/videos/delver/acceptance', (route) => {
      off = true;
      return route.fulfill({
        status: 409,
        json: {
          message: `Только смотреть: ${reason}`,
          code: 'not_working_factory',
          details: [reason],
        },
      });
    });
    await page.goto(at('delver'));
    const dialog = await verdict(page, 'yes');
    await dialog.getByTestId('verdict-confirm').click();
    await expect(dialog.getByTestId('refusal-message')).toHaveText(`Только смотреть: ${reason}`);
    await expect(page.getByTestId('read-only-banner')).toContainText(reason);
    await expect(dialog.getByTestId('verdict-confirm')).toHaveAttribute('data-writes', 'off');
    await dialog.getByRole('button', { name: 'Отмена' }).click();
    for (const v of ['yes', 'no', 'redo'])
      await expect(page.getByTestId(`verdict-${v}`)).toHaveAttribute('data-writes', 'off');
    onlyHttp(consoleErrors, 409);
  });
});

test('«Нет» с новым кодом причины: код уходит как введён', async ({ page, videos }) => {
  await page.goto(at('delver'));
  const dialog = await verdict(page, 'no');
  await dialog.getByTestId('verdict-reason').fill('звук плывёт на второй минуте');
  await dialog.getByTestId('verdict-code').selectOption({ label: 'новый код…' });
  const code = dialog.getByTestId('verdict-new-code');
  await code.fill('Audio');
  await expect(code).toHaveAttribute('aria-invalid', 'true');
  await code.fill('audio_drift');
  await expect(code).not.toHaveAttribute('aria-invalid');
  await dialog.getByTestId('verdict-confirm').click();
  await expect(page.getByTestId('acceptance-answer-text')).toHaveText('Записано.');
  await expect(page.getByTestId('acceptance-reason')).toContainText('звук плывёт на второй минуте');
  expect(videos.accepted[0]!.body).toMatchObject({ verdict: 'no', reason_code: 'audio_drift' });
});

test('под идущим батчем: «записано, ждёт конца батча» и почему; список — в очереди', async ({
  page,
  videos,
}) => {
  videos.setGoing([
    { dir: 'pipeline/example-film/2026-10-10T0200Z', why: 'батч дня example-film ещё идёт' },
  ]);
  await page.goto(at('delver'));
  const dialog = await verdict(page, 'yes');
  await dialog.getByTestId('verdict-confirm').click();
  const answer = page.getByTestId('acceptance-answer');
  await expect(answer.getByTestId('acceptance-answer-text')).toHaveText(
    'Записано, ждёт конца батча.',
  );
  await expect(answer.getByTestId('acceptance-answer-batches')).toHaveText(
    'батч дня example-film ещё идёт',
  );
  await expect(page.getByTestId('acceptance-pending')).toContainText('Записано, ждёт конца батча');
  await expect(page.getByTestId('acceptance-verdict')).toHaveText('принят · ждёт конца батча');
});

test('«Переделать»: записано, просьба в очередь оператору ещё не поставлена', async ({
  page,
  videos,
}) => {
  await page.goto(at('delver'));
  const dialog = await verdict(page, 'redo');
  await dialog.getByTestId('verdict-words').fill('delver — переделать хук');
  await dialog.getByTestId('verdict-reason').fill('хук не цепляет');
  await dialog.getByTestId('verdict-code').selectOption('weak_hook');
  await dialog.getByTestId('verdict-confirm').click();
  const answer = page.getByTestId('acceptance-answer');
  await expect(answer.getByTestId('acceptance-answer-redo')).toHaveText(
    'Просьба записана, в очередь оператору ещё не поставлена.',
  );
  await expect(page.getByTestId('acceptance-verdict')).toHaveText('на переделку');
  expect(videos.accepted[0]!.body).toMatchObject({
    verdict: 'redo',
    words: 'delver — переделать хук',
  });
});

test('только смотреть: кнопки вердикта погашены с причиной, окно не открывается', async ({
  page,
}) => {
  await page.route('**/api/health', (route) =>
    route.fulfill({ json: { ...fixtures.health, ...writesModes.off } }),
  );
  const sent = writesOf(page);
  await page.goto(at('delver'));
  for (const v of ['yes', 'no', 'redo']) {
    const b = page.getByTestId(`verdict-${v}`);
    await expect(b).toHaveAttribute('aria-disabled', 'true');
    await expect(b).toHaveAttribute('data-writes', 'off');
    await b.click({ force: true });
    await expect(page.getByRole('alertdialog')).toHaveCount(0);
  }
  await openTip(page, page.getByTestId('verdict-yes'), `Только смотреть: ${READ_ONLY_REASON}`);
  expect(sent).toEqual([]);
});

test('главная: «Ролики ждут решения» — последний батч; после вердикта счёт обнуляется', async ({
  page,
}) => {
  await page.goto('/');
  const card = page.getByTestId('reels-card');
  await expect(card.getByTestId('reels-count')).toHaveText(
    /1 из 3 — без вердикта в последнем батче/,
  );
  await expect(page.getByTestId('attention-text')).toContainText(
    'Роликов без вердикта в последнем батче: 1.',
  );
  await card.locator('[data-testid="reels-item"][data-slug="delver"] a').click();
  await expect(page.getByTestId('video-detail')).toHaveAttribute('data-slug', 'delver');
  const dialog = await verdict(page, 'yes');
  await dialog.getByTestId('verdict-confirm').click();
  await expect(page.getByTestId('acceptance-answer-text')).toHaveText('Записано.');
  await page.goto('/');
  await expect(page.getByTestId('reels-count')).toHaveText(
    /В последнем батче у всех роликов уже есть вердикт/,
  );
});

test.describe('автосборка карточки не запустилась @cc-0175', () => {
  test('«Да»: причина по-русски рядом со строкой копилки, коды — под «подробнее о сборке»', async ({
    page,
    videos,
  }) => {
    videos.setQueued(queuedBuildRefused(PAST.split('/')[0]!, 'delver'));
    await page.goto(at('delver'));
    const dialog = await verdict(page, 'yes');
    await dialog.getByTestId('verdict-confirm').click();
    const queued = page.getByTestId('acceptance-answer-queued');
    const build = queued.getByTestId('accept-card-build');
    await expect(build).toHaveAttribute('data-why', '1');
    await expect(build.getByTestId('accept-card-build-why')).toHaveText(
      'Карточку не собрать: модель не написала черновик карточки — ответ пустой; не прошла проверка утверждений.',
    );
    const code = build.getByTestId('accept-card-build-why-code');
    await expect(code.first()).toBeHidden();
    await build.locator('[data-slot="more"] > summary').click();
    await expect(code).toHaveCount(2);
    await expect(code.first()).toHaveText(/^model_refused: /);
    await expect(code.nth(1)).toHaveText(
      'claims_failed: claim check failed: title says 2027, source says 2026',
    );
    await noSideScroll(page);
  });

  test('why нет — прежняя строка, без «подробнее о сборке»', async ({ page, videos }) => {
    videos.setQueued({
      ...queuedBuildRefused(PAST.split('/')[0]!, 'delver'),
      card_build: { ...ACCEPT_BUILD_REFUSED, why: null },
    });
    await page.goto(at('delver'));
    const dialog = await verdict(page, 'yes');
    await dialog.getByTestId('verdict-confirm').click();
    const build = page.getByTestId('acceptance-answer-queued').getByTestId('accept-card-build');
    await expect(build).toHaveText(
      'Карточку не собрать: модель не написала черновик; не прошла проверка утверждений.',
    );
    await expect(build).not.toHaveAttribute('data-why');
    await expect(page.getByTestId('accept-card-build-why-code')).toHaveCount(0);
  });
});
