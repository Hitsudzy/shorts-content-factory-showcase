// CC-0029: экран «Токены, OAuth и данные API» на подставном API (src/mocks/oauth.ts): таб → экран;
// токен без значения (срок словами, разрешения, файлы, команда входа с «Скопировать»; истёк / нет
// токена / не хватает разрешения — словами, точка у таба); сухой прогон отзыва (кнопка погашена с
// подсказкой, ничего не уходит); данные API по каналам, авто-прогон без кнопки, ссылка на
// переключатель загрузки; удаление — план по каналам → «да» с отсчётом → итог, данные перечитаны;
// отказы (изменилось — план заново сам, занято — токен цел, сломалось), устаревший план; пусто;
// телефон 390 без прокрутки вбок; тренировка на демо-данных. Пока человек не попросил план, с
// экрана уходят только GET; значения токена нет ни в одном ответе.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, openTip, test } from './fixtures';

const tabs = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });
const writes = (hits: string[]) => hits.filter((h) => !h.startsWith('GET '));

async function openPurge(page: Page, channels?: string[]) {
  const box = page.getByTestId('oauth-purge');
  if (channels) {
    await box.getByTestId('oauth-purge-all').uncheck();
    for (const c of channels) await box.getByTestId(`oauth-purge-ch-${c}`).check();
  }
  await box.getByTestId('oauth-purge-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog).toBeVisible();
  return { box, dialog, yes: dialog.getByTestId('oauth-purge-confirm') };
}

test('таб → токен, отзыв, данные API — только GET; значения токена нет', async ({
  page,
  apiHits,
}) => {
  const bodies: string[] = [];
  page.on('response', async (r) => {
    if (r.url().includes('/api/oauth/')) bodies.push(await r.text().catch(() => ''));
  });
  await page.goto('/');
  await tabs(page).getByRole('link', { name: 'Токены', exact: true }).click();
  await expect(page).toHaveURL(/\/tokens$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Токены, OAuth и данные API');
  await expect(page.getByText(/Скоро · версия/)).toHaveCount(0);

  const token = page.getByTestId('oauth-token');
  await expect(token.getByTestId('oauth-token-term')).toHaveText(
    'Действует ещё 4 дня — до 16 октября, 18:40 МСК',
  );
  await openTip(page, token.locator('[data-slot="status"]').first(), 'загружает ролики');
  await openTip(
    page,
    token.locator('[data-slot="status"]:has([data-scope="yt-analytics.readonly"])'),
    'YouTube Analytics',
  );
  await expect(token.getByTestId('oauth-command')).toHaveText(
    'agents/publisher/.venv/bin/python agents/publisher/upload.py --authorize',
  );
  await expect(token.getByTestId('oauth-token-line')).toBeHidden();

  const revoke = page.getByTestId('oauth-revoke');
  await expect(revoke.getByTestId('oauth-revoke-steps')).toContainText(
    'Данные API удалятся: 11 объектов — 2 канала:',
  );
  const btn = revoke.getByTestId('oauth-revoke-open');
  await expect(btn).not.toHaveAttribute('aria-disabled');
  await openTip(page, btn, 'Фабрика покажет, что сделает отзыв');
  await expect(revoke).not.toContainText('следующей версии');

  const data = page.getByTestId('oauth-api-data');
  await expect(data.getByTestId('oauth-held').getByTestId('oauth-share')).toHaveCount(2);
  await expect(data.getByTestId('oauth-due')).toContainText('delver');
  await expect(data.getByTestId('oauth-due').getByTestId('oauth-auto-open')).toBeVisible();
  await data.getByTestId('oauth-api-data-again').click();
  await expect(data.getByTestId('oauth-api-data-again')).toHaveText('Перечитать');
  expect(writes(apiHits), 'с экрана токенов — только GET').toEqual([]);
  expect(bodies.length).toBeGreaterThanOrEqual(3);
  for (const b of bodies) expect(b).not.toMatch(/refresh_token|client_secret"|ya29\./);

  await data.getByRole('link', { name: '«Публикация»' }).click();
  await expect(page).toHaveURL(/\/publishing$/);
});

test('удаление: план по каналам → «да» с отсчётом → итог, данные перечитаны', async ({
  page,
  apiHits,
  oauth,
}) => {
  await page.goto('/tokens');
  await expect(page.getByTestId('oauth-held').getByTestId('oauth-share')).toHaveCount(2);
  const { box, dialog, yes } = await openPurge(page, ['example-film']);
  await expect(dialog.getByTestId('oauth-purge-size')).toHaveText('Удалится 8 объектов — 1 канал:');
  const share = dialog.getByTestId('oauth-share');
  await expect(share).toHaveCount(1);
  await expect(share).toContainText(
    'Статистика просмотров из YouTube Analytics: по дням, по окнам после публикации, журнал загрузок',
  );
  await expect(share).toContainText('Сводка аналитика по этой статистике (6 файлов)');
  await expect(share).toContainText('«Rink rivals», «Delver»');
  await expect(share).toContainText('Ссылки на ролики в 2 текстах заменятся пометкой');
  await expect(dialog.getByTestId('oauth-purge-kept')).toContainText('Токен YouTube');
  await expect(dialog.getByTestId('oauth-purge-kept')).toContainText('Цифры из Studio');
  await expect(yes).toHaveText(/Удалить · [12]:\d\d/);
  expect(writes(apiHits)).toEqual(['POST /api/oauth/api-data/purge/plan']);
  expect(oauth.state.written).toEqual([]);
  await yes.click();
  await expect(dialog).toBeHidden();
  await expect(box.getByTestId('oauth-purge-done')).toContainText('Данные API удалены');
  await expect(box.getByTestId('oauth-purge-done')).toContainText('Токен YouTube на месте');
  await expect(page.getByTestId('oauth-held').getByTestId('oauth-share')).toHaveCount(1);
  await expect(page.getByTestId('oauth-due')).toContainText('Авто-прогону сейчас удалять нечего');
  await expect(page.getByTestId('oauth-revoke-steps')).toContainText('3 объекта — 1 канал');
  expect(oauth.state.written).toHaveLength(1);
  expect(oauth.state.written[0]).toMatchObject({ by: 'user', via: 'center' });
  await expect(page.getByTestId('oauth-token-kind')).toHaveText('действует');
});

test.describe('отказы (браузер пишет 4xx/5xx в консоль)', () => {
  test.use({ expectCleanConsole: false });

  test('«да» после изменения — план заново сам, второе «да» удаляет', async ({ page, oauth }) => {
    await page.goto('/tokens');
    const { box, dialog, yes } = await openPurge(page);
    await expect(yes).toBeEnabled();
    oauth.state.next = 'check_changed';
    await yes.click();
    await expect(dialog.getByTestId('replanned')).toHaveAttribute('data-code', 'check_changed');
    await expect(dialog.getByTestId('replanned')).toContainText('Данные API изменились');
    await expect(yes).toBeEnabled();
    await yes.click();
    await expect(box.getByTestId('oauth-purge-done')).toBeVisible();
    expect(oauth.state.written).toHaveLength(1);
  });

  test('занято — токен цел, «да» ещё раз удаляет; сломалось — словами фабрики', async ({
    page,
    oauth,
  }) => {
    await page.goto('/tokens');
    const { dialog, yes } = await openPurge(page, ['example-tech']);
    await expect(yes).toBeEnabled();
    oauth.state.next = 'busy';
    await yes.click();
    await expect(dialog.getByTestId('act-error')).toHaveAttribute('data-code', 'busy');
    await expect(dialog.getByTestId('busy-note')).toBeVisible();
    oauth.state.next = 'factory_broken';
    await yes.click();
    const refusal = dialog.getByTestId('act-error').getByTestId('write-refusal');
    await expect(refusal).toHaveAttribute('data-code', 'factory_broken');
    await expect(refusal.getByTestId('write-refusal-title')).toHaveText(
      'Фабрика ответила ошибкой — посмотрите состояние данных API, прежде чем повторять',
    );
    await expect(yes).toBeDisabled();
    expect(oauth.state.written).toEqual([]);
  });

  test('опустело, пока смотрели план — «удалять уже нечего»', async ({ page, oauth }) => {
    await page.goto('/tokens');
    const { dialog, yes } = await openPurge(page);
    await expect(yes).toBeEnabled();
    oauth.state.next = 'refused';
    await yes.click();
    await expect(dialog.getByTestId('act-error')).toHaveAttribute('data-code', 'refused');
    await expect(dialog.getByTestId('write-refusal-title')).toHaveText(
      'Удалять уже нечего — данные API этих каналов кто-то удалил',
    );
  });

  test('план устарел — «Проверить заново» даёт новый', async ({ page, oauth }) => {
    oauth.state.life = 2;
    await page.goto('/tokens');
    const { box, dialog, yes } = await openPurge(page);
    await expect(dialog.getByTestId('token-expired')).toBeVisible({ timeout: 6000 });
    await expect(yes).toBeDisabled();
    oauth.state.life = 120;
    await dialog.getByTestId('replan').click();
    await expect(yes).toBeEnabled();
    await yes.click();
    await expect(box.getByTestId('oauth-purge-done')).toBeVisible();
  });

  test('настройки публикатора не читаются — токен и отзыв словами, данные API на месте', async ({
    page,
    oauth,
  }) => {
    oauth.state.configBroken = true;
    await page.goto('/tokens');
    await expect(page.getByTestId('oauth-token')).toContainText('Состояние токена не прочитать');
    await expect(page.getByTestId('oauth-token')).toContainText(
      'Конфигурация публикатора не читается',
    );
    await expect(page.getByTestId('oauth-revoke')).toContainText('План отзыва не составлен');
    await expect(page.getByTestId('oauth-config-error')).toBeVisible();
    await expect(page.getByTestId('oauth-held').getByTestId('oauth-share')).toHaveCount(2);
  });
});

test('токен истёк, нет токена, не хватает разрешения — словами; точка у таба', async ({
  page,
  oauth,
}) => {
  oauth.state.token = 'expired';
  await page.goto('/tokens');
  await expect(page.getByTestId('oauth-token-kind')).toHaveText('истёк');
  await expect(page.getByTestId('oauth-signin')).toHaveAttribute('data-urgent', '1');
  const mark = tabs(page).getByTestId('tab-token-mark');
  await expect(mark).toHaveAttribute('data-tone', 'danger');
  await openTip(
    page,
    tabs(page).getByRole('link', { name: 'Токены', exact: true }),
    'Токен YouTube не действует',
  );

  oauth.state.token = 'no-scope';
  await page.reload();
  await expect(page.getByTestId('oauth-token-term')).toHaveText(
    'У токена нет разрешения: Аналитика',
  );
  await expect(page.locator('[data-scope="yt-analytics.readonly"]')).toHaveText('нет: Аналитика');

  oauth.state.token = 'expires-soon';
  await page.reload();
  await expect(page.getByTestId('oauth-token-term')).toHaveText(
    'Истекает через 20 ч — 13 октября, 14:40 МСК',
  );
  await expect(tabs(page).getByTestId('tab-token-mark')).toHaveAttribute('data-tone', 'warn');

  oauth.state.token = 'no-auth';
  await page.reload();
  await expect(page.getByTestId('oauth-signin')).toContainText('Разрешить доступ');
  await expect(page.getByTestId('oauth-revoke-steps')).toContainText('Отзывать у Google нечего');
});

test('пусто: «Данных API нет», удалять нечего; отметка отзыва — когда удалится', async ({
  page,
  oauth,
}) => {
  oauth.empty();
  await page.goto('/tokens');
  await expect(page.getByTestId('oauth-held')).toContainText('Данных API нет');
  await expect(page.getByTestId('oauth-revoke-steps')).toContainText('Данных API нет');
  const open = page.getByTestId('oauth-purge-open');
  await expect(open).toHaveAttribute('aria-disabled', 'true');
  await openTip(page, open, 'Удалять нечего');

  oauth.markRevoked();
  await page.reload();
  await expect(page.getByTestId('oauth-api-data-head')).toContainText(
    'Google отказал токену 10 октября — данные API удалятся 4 ноября',
  );
});

test.describe('телефон 390', () => {
  test.use({ viewport: { width: 390, height: 844 } });

  test('экран, план и итог без прокрутки вбок', async ({ page }) => {
    await page.goto('/tokens');
    await expect(page.getByTestId('oauth-held').getByTestId('oauth-share')).toHaveCount(2);
    await page.getByTestId('oauth-signin').getByText('Подробнее: команда входа').click();
    await expect(page.getByTestId('oauth-command')).toBeVisible();
    // Команда переносится только по пробелу или после «/» — не посреди слова.
    const breaks = await page.getByTestId('oauth-command').evaluate((code) => {
      const out: string[] = [];
      const walker = document.createTreeWalker(code, NodeFilter.SHOW_TEXT);
      let prevTop: number | null = null;
      let prevChar = '';
      for (let n = walker.nextNode(); n; n = walker.nextNode()) {
        const text = n.textContent ?? '';
        for (let i = 0; i < text.length; i++) {
          if (text[i] === ' ') {
            prevChar = ' ';
            continue;
          }
          const r = document.createRange();
          r.setStart(n, i);
          r.setEnd(n, i + 1);
          const top = Math.round(r.getBoundingClientRect().top);
          if (prevTop !== null && top > prevTop) out.push(`${prevChar}|${text[i]}`);
          prevTop = top;
          prevChar = text[i]!;
        }
      }
      return out;
    });
    expect(breaks.length, 'на 390 команда в несколько строк').toBeGreaterThan(0);
    for (const b of breaks) expect(b, 'перенос по пробелу или после «/»').toMatch(/^[ /]\|/);
    await noSideScroll(page);
    const { box, dialog, yes } = await openPurge(page);
    await expect(dialog.getByTestId('oauth-share')).toHaveCount(2);
    // Окно длиннее экрана — прокручивается внутри, подвал с «Отмена» и «да» виден всегда.
    for (const b of [dialog.getByRole('button', { name: 'Отмена' }), yes]) {
      const r = (await b.boundingBox())!;
      expect(r.y + r.height).toBeLessThanOrEqual(844);
    }
    await noSideScroll(page);
    await yes.click();
    await expect(box.getByTestId('oauth-purge-done')).toContainText('11 объектов');
    // Итог подведён в поле зрения и не под липкой шапкой.
    const done = (await box.getByTestId('oauth-purge-done').boundingBox())!;
    const head = (await page.locator('header').boundingBox())!;
    expect(done.y).toBeGreaterThanOrEqual(head.y + head.height);
    expect(done.y).toBeLessThan(844);
    await noSideScroll(page);
  });
});

test('тренировка: удалить данные API на демо-данных, живой API не тронут', async ({
  page,
  apiHits,
}) => {
  test.setTimeout(90_000);
  await page.goto('/');
  await expect(page.getByTestId('attention')).toBeVisible();
  await page.getByTestId('tour-open').click();
  await page.getByTestId('tour-contents').getByTestId('tour-practice').click();
  await expect(page.getByTestId('training-banner-text')).toBeVisible();
  const live = apiHits.length;
  if (await page.getByTestId('training-panel').isVisible())
    await page.getByTestId('training-collapse').click();
  await tabs(page).getByRole('link', { name: 'Токены', exact: true }).click();
  await expect(page.getByTestId('oauth-held').getByTestId('oauth-share')).toHaveCount(2);
  const { box, yes } = await openPurge(page, ['example-tech']);
  await yes.click();
  await expect(box.getByTestId('oauth-purge-done')).toContainText('Данные API удалены');
  expect(apiHits.slice(live)).toEqual([]);
});

test('отозвать доступ: план → «да» → итог словами; значения токена нет (CC-0087)', async ({
  page,
  oauth,
}) => {
  await page.goto('/tokens');
  const revoke = page.getByTestId('oauth-revoke');
  await revoke.getByTestId('oauth-revoke-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('oauth-revoke-plan-steps')).toContainText(
    'Google отзовёт разрешение фабрики',
  );
  await expect(dialog.getByTestId('oauth-revoke-confirm')).toBeEnabled();
  await dialog.getByTestId('oauth-revoke-confirm').click();
  const res = page.getByTestId('oauth-revoke-result');
  await expect(res.getByTestId('oauth-revoke-google')).toContainText('Google отозвал разрешение');
  await expect(res.getByTestId('oauth-revoke-token')).toContainText(
    'Файл токена на этой машине удалён',
  );
  expect(oauth.state.written).toHaveLength(1);
  await expect(page.locator('body')).not.toContainText(/refresh_token|ya29\./);
});

test('удалить по сроку: план → «да» → итог (CC-0087)', async ({ page, oauth }) => {
  await page.goto('/tokens');
  const due = page.getByTestId('oauth-due');
  await due.getByTestId('oauth-auto-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('oauth-auto-plan-part')).toHaveCount(1);
  await expect(dialog.getByTestId('oauth-auto-confirm')).toBeEnabled();
  await dialog.getByTestId('oauth-auto-confirm').click();
  await expect(page.getByTestId('oauth-auto-done')).toContainText('Удалено по сроку');
  expect(oauth.state.written).toHaveLength(1);
});
