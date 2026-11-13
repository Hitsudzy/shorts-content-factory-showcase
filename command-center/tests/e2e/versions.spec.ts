// CC-0031: экран «Версии и агенты» на подставном API (src/mocks/versions.ts): таб → экран (только
// GET); выпуск фабрики, центр, что в работе; расхождение агентов с пинами — полоса сверху, строки
// словами, подсказка у «расходится», строка фабрики под «Подробнее»; «Проверить заново» —
// `?fresh=true`; всё на пинах и ничего не в работе; отказ API и повтор; телефон 390 без прокрутки
// вбок.
import type { Locator, Page } from '@playwright/test';

import { versionAnswer } from '../../src/mocks/fixtures';
import { API_STALE_PATHS } from '../../src/mocks/versions';
import { expect, noSideScroll, onlyHttp, openTip, test } from './fixtures';

const tabs = (page: Page) => page.getByRole('navigation', { name: 'Разделы' });
const agent = (page: Page, name: string) =>
  page.locator(`[data-testid="versions-agent"][data-agent="${name}"]`);

/** Видимый текст `main` без «подробнее». */
const plain = (page: Page) =>
  page.locator('main').evaluate((m) => {
    const c = m.cloneNode(true) as HTMLElement;
    c.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
    return c.textContent ?? '';
  });

test('таб → выпуск, центр, в работе, расхождение словами — только GET', async ({
  page,
  apiHits,
}) => {
  await page.goto('/');
  await tabs(page).getByRole('link', { name: 'Версии', exact: true }).click();
  await expect(page).toHaveURL(/\/versions$/);
  await expect(page.getByRole('heading', { level: 1 })).toHaveText('Версии и агенты');
  await expect(page.getByText(/Скоро · версия/)).toHaveCount(0);

  await expect(page.getByTestId('versions-release')).toHaveText('2.3.4');
  await expect(page.getByTestId('versions-center-version')).toHaveText('0.3.1');
  await expect(page.getByTestId('versions-work-item')).toHaveText(/2\.4\s*готовится/);

  const sum = page.getByTestId('versions-summary');
  await expect(sum).toHaveAttribute('data-drift', '1');
  await expect(sum).toContainText('Агенты расходятся с пинами');
  await expect(sum).toContainText('Что сделать — в строке каждого агента');
  await expect(sum.getByTestId('versions-sync')).toContainText(
    'вернёт на пин: Content Researcher.',
  );
  await expect(page.getByRole('heading', { name: '2 из 5 расходятся с пином' })).toBeVisible();
  await expect(page.getByTestId('versions-agent')).toHaveCount(5);
  await expect(page.getByTestId('versions-agent').first()).toHaveAttribute('data-ok', '0');
  await expect(agent(page, 'content-researcher').getByTestId('versions-agent-why')).toHaveText(
    'стоит на ветке выпуска 2.4, а не на v2.3',
  );
  await expect(agent(page, 'video-editor').getByTestId('versions-agent-why')).toHaveText(
    'в 2 файлах правки не зафиксированы',
  );

  // Коммиты, пути, строка фабрики и англоязычные термины — только под «Подробнее».
  expect(await plain(page)).not.toMatch(
    /release\/|agents\/|[0-9a-f]{12}|uncommitted|HEAD|\bgit\b|коммит|не на пине/i,
  );
  const row = agent(page, 'content-researcher');
  await row.getByText('Подробнее').click();
  await expect(row.locator('[data-slot="more"]')).toContainText('(release/2.4) is not v2.3');

  await openTip(
    page,
    row.locator('[data-slot="status"]'),
    'пока он не вернётся на пин, батч на этой копии не запустится',
  );
  // Пояснения к словам «пин», «ветка выпуска», «Договор API» и к версии по описанию.
  await openTip(page, row.getByTestId('versions-pin-tip'), 'Пин — версия, закреплённая');
  await page.goto('/versions');
  await expect(page.getByTestId('versions-agent')).toHaveCount(5);
  await openTip(page, page.getByText('Договор API', { exact: true }), 'Договор API — общее');
  await openTip(
    page,
    page.getByText('Версия по описанию фабрики', { exact: true }),
    'пишет в своём описании',
  );
  await openTip(page, page.getByTestId('versions-branch'), 'Основная ветка — то, на чём');
  await openTip(page, page.getByTestId('versions-work-version'), 'Ветка выпуска — отдельная');

  expect(apiHits.filter((h) => !h.startsWith('GET '))).toEqual([]);
  expect(apiHits).toContain('GET /api/versions');
});

test('«Проверить заново» — свежая проверка, время сменилось', async ({ page, versions }) => {
  await page.goto('/versions');
  const checked = page.getByTestId('versions-checked');
  await expect(checked).toContainText('14 октября, 09:40');
  await page.getByTestId('versions-recheck').click();
  await expect(checked).toContainText('14 октября, 09:41');
  await expect(checked).not.toContainText('сохранённый ответ');
  expect(versions.state.calls).toContain('/api/versions?fresh=true');
});

test('всё на пинах и ничего не в работе', async ({ page, versions }) => {
  versions.clean();
  versions.state.inWork = [];
  await page.goto('/versions');
  await expect(page.getByTestId('versions-summary')).toHaveAttribute('data-drift', '0');
  await expect(page.getByRole('heading', { name: 'Все 5 на своих пинах' })).toBeVisible();
  await expect(page.getByTestId('versions-agent-drift')).toHaveCount(0);
  await expect(page.getByTestId('versions-work-empty')).toContainText('фабрика работает на 2.3.4');
});

test('телефон: ничего не вылезает вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/versions');
  await expect(page.getByTestId('versions-agent')).toHaveCount(5);
  await noSideScroll(page);
});

test.describe('отказ API пишет 500 в консоль', () => {
  test.use({ expectCleanConsole: false });

  test('API не ответил — ошибка и «Повторить»', async ({ page, versions, consoleErrors }) => {
    versions.state.refuse = true;
    await page.goto('/versions');
    await expect(page.getByText('Версии не прочитать')).toBeVisible({ timeout: 15_000 });
    versions.state.refuse = false;
    await page.getByRole('button', { name: 'Повторить' }).click();
    await expect(page.getByTestId('versions-agent')).toHaveCount(5);
    onlyHttp(consoleErrors, 500);
  });
});

// CC-0155 (договор 0.70.0): процесс cc-api из `GET /api/version` — когда запущен и не отстал ли от
// кода фабрики. Подставной ответ — `fixtures.version` (на текущем коде), «на старом коде» —
// подменой маршрута.
const STALE_TITLE = 'API работает на старом коде — с запуска изменился код фабрики.';
const STALE_ACTION = 'Нужен перезапуск API (это делает фабрика).';
const apiProcess = (page: Page) => page.getByTestId('versions-api-process');

test('процесс API на текущем коде — тихая строка, коммит под «Подробнее»', async ({ page }) => {
  await page.goto('/versions');
  const strip = apiProcess(page);
  await expect(strip).toHaveAttribute('data-state', 'fresh');
  await expect(strip).toContainText('API запущен 22.10, 01:15 МСК · на текущем коде фабрики');
  await expect(page.getByText(STALE_TITLE)).toHaveCount(0);
  await expect(page.getByTestId('api-status')).toHaveText('Фабрика на связи');
  await strip.getByText('Подробнее').click();
  await expect(strip.locator('[data-slot="more"]')).toContainText('на коммите 0000000');
});

test('процесс API на старом коде — предупреждение, шапка, что изменилось', async ({ page }) => {
  await page.route('**/api/version', (route) => route.fulfill({ json: versionAnswer('stale') }));
  await page.goto('/versions');
  const strip = apiProcess(page);
  await expect(strip).toHaveAttribute('data-state', 'stale');
  await expect(strip).toHaveAttribute('role', 'status');
  await expect(strip).toContainText(STALE_TITLE);
  await expect(strip).toContainText(STALE_ACTION);
  await expect(page.getByTestId('api-status')).toHaveText('API на старом коде');
  expect(await plain(page)).not.toMatch(/коммит|abc1234|\.py\b/);
  await strip.getByText('Подробнее: что изменилось').click();
  const more = strip.locator('[data-slot="more"]');
  await expect(more).toContainText('на коммите abc1234');
  await expect(more).toContainText('сейчас у фабрики: 5c9cb3a');
  await expect(more).not.toContainText('API запущен');
  await expect(strip.getByTestId('versions-api-stale-path')).toHaveText([...API_STALE_PATHS]);

  // Телефон: точка — в первой строке заголовка, как у полосы «Агенты расходятся с пинами».
  await page.setViewportSize({ width: 390, height: 844 });
  await noSideScroll(page);
  const offset = (box: Locator) =>
    box.evaluate((el) => {
      const dot = el.querySelector('[aria-hidden]')!.getBoundingClientRect();
      const line = el.querySelector('b')!.getClientRects()[0]!;
      return {
        dy: dot.top + dot.height / 2 - (line.top + line.height / 2),
        dx: dot.left - el.getBoundingClientRect().left,
      };
    });
  const mine = await offset(strip);
  const theirs = await offset(page.getByTestId('versions-summary'));
  expect(Math.abs(mine.dy - theirs.dy)).toBeLessThan(1);
  expect(Math.abs(mine.dx - theirs.dx)).toBeLessThan(1);
});
