// CC-0124: «Разработка» на подставном API (src/mocks/dev.ts): таб → список по вехам (текущие
// сверху, сделанные свёрнуты), поиск и фильтры — в адресе и переживают перезагрузку, карточка
// задачи с markdown и связями, номер в тексте ведёт на другую карточку, «задачи нет», дорожная
// карта; только чтения; телефон 375 без прокрутки вбок.
import type { Page } from '@playwright/test';

import { expect, noSideScroll, onlyHttp, test } from './fixtures';

const rows = (page: Page) => page.getByTestId('task-row');
const ids = (page: Page) =>
  rows(page).evaluateAll((els) => els.map((e) => e.getAttribute('data-id')));

test('таб → задачи по вехам: текущие сверху, сделанные свёрнуты; только чтения', async ({
  page,
  apiHits,
}) => {
  await page.goto('/');
  await page
    .getByRole('navigation', { name: 'Разделы' })
    .getByRole('link', { name: 'Разработка' })
    .click();
  await expect(page).toHaveURL(/\/dev$/);
  await expect(page.getByRole('heading', { level: 1, name: 'Разработка' })).toBeVisible();
  const groups = page.getByTestId('dev-group');
  await expect(groups.first()).toHaveAttribute('data-key', 'factory|2.9');
  await expect(groups.nth(1)).toHaveAttribute('data-key', 'center|1.1');
  await expect(groups.first()).toContainText('текущая');
  const done = page.locator('[data-testid="dev-group"][data-key="factory|2.8"]');
  await expect(done).toContainText('сделана 14.10');
  await expect(done.getByTestId('task-row')).toHaveCount(0);
  await done.getByRole('button', { expanded: false }).click();
  await expect(done.getByTestId('task-row')).toHaveCount(5);
  await expect(done).toContainText('архив v2.8');
  await expect(page.getByTestId('dev-count')).toHaveText('Всего 35 задач');
  expect(apiHits.filter((h) => !h.startsWith('GET '))).toEqual([]);
});

test('поиск и фильтры — в адресе; перезагрузка их восстанавливает', async ({ page, dev }) => {
  await page.goto('/dev');
  await expect(rows(page).first()).toBeVisible();
  await page.getByTestId('dev-search').fill('tech 01:00');
  await expect(page).toHaveURL(/[?&]q=tech/);
  await expect.poll(() => ids(page)).toEqual(['CF-0618']);
  expect(dev.state.calls.some((c) => c.includes('q='))).toBe(true);

  await page.getByTestId('dev-search').fill('');
  await expect(page).toHaveURL(/\/dev$/);
  // CC-0159: каждый щелчок — после того, как экран показал предыдущий. Роутер перерисовывает
  // в transition, и под нагрузкой чипы ещё сдвигаются (счёт в подписи меняется), когда
  // приходит следующий щелчок.
  await page.getByTestId('dev-project-center').click();
  await expect(page.getByTestId('dev-project-center')).toHaveAttribute('aria-pressed', 'true');
  const chip = page.locator('[data-testid="dev-status"][data-status="in-progress"]');
  await chip.click();
  // Выбранный чип — с галочкой и в цвете своего статуса («в работе» — акцентный текст).
  await expect(chip).toHaveAttribute('aria-pressed', 'true');
  await expect(chip.getByTestId('dev-status-on')).toBeVisible();
  const blocked = page.locator('[data-testid="dev-status"][data-status="blocked"]');
  await blocked.click();
  await expect(blocked).toHaveAttribute('aria-pressed', 'true');
  const colors = await Promise.all(
    [chip, blocked].map((c) => c.evaluate((e) => getComputedStyle(e).color)),
  );
  expect(colors[0]).not.toBe(colors[1]);
  await blocked.click();
  await expect(blocked).toHaveAttribute('aria-pressed', 'false');
  await page.getByTestId('dev-milestone').selectOption('1.1');
  await expect(page).toHaveURL(/\/dev\?project=center&milestone=1\.1&status=in-progress$/);
  await expect.poll(() => ids(page)).toEqual(['CC-0037', 'CC-0124']);

  await page.reload();
  await expect.poll(() => ids(page)).toEqual(['CC-0037', 'CC-0124']);
  await expect(page.getByTestId('dev-project-center')).toHaveAttribute('aria-pressed', 'true');
  await expect(page.getByTestId('dev-milestone')).toHaveValue('1.1');
  await expect(page.getByTestId('dev-count')).toHaveText(/Нашлось 2 задачи из 35/);

  // Ссылку с поиском можно переслать: открывается сразу найденным.
  await page.goto('/dev?q=%D1%81%D0%B2%D1%8F%D0%B7%D0%BA%D0%B0&sort=id');
  await expect(page.getByTestId('dev-search')).toHaveValue('связка');
  await expect(page.getByTestId('dev-sort')).toHaveValue('id');
  await expect.poll(() => ids(page)).toEqual(['CC-0150']);
});

test('карточка: тело как markdown, чеклист, связи, история; номер в тексте — ссылка', async ({
  page,
}) => {
  await page.goto('/dev?project=center&status=in-progress');
  await page
    .locator('[data-testid="task-row"][data-id="CC-0124"]')
    .getByTestId('task-link')
    .click();
  await expect(page).toHaveURL(/\/dev\/CC-0124$/);
  await expect(page.getByTestId('task-title')).toContainText('Вкладка «Разработка»');
  const body = page.getByTestId('task-body');
  await expect(body.getByRole('heading', { name: 'Экран' })).toBeVisible();
  await expect(body.locator('strong', { hasText: 'версией' })).toBeVisible();
  await expect(body.locator('li[data-check="done"]')).toHaveCount(2);
  await expect(body.locator('li[data-check="open"]')).toHaveCount(2);
  await expect(page.getByTestId('task-checklist')).toContainText('сделано 2 из 4');
  await expect(page.getByTestId('task-related').getByTestId('task-link')).toHaveText([
    'CC-0037',
    'CF-0626',
  ]);
  await expect(page.getByTestId('task-history').getByRole('listitem')).toHaveCount(2);

  await body.getByRole('link', { name: 'CF-0626' }).first().click();
  await expect(page).toHaveURL(/\/dev\/CF-0626$/);
  await expect(page.getByTestId('task-title')).toHaveText(/Командный центр/);
  await expect(page.getByTestId('task-facts')).toContainText('Фабрика');

  // «← К задачам» — к тем же фильтрам, откуда открыли.
  await page.getByTestId('dev-back').click();
  await expect(page).toHaveURL(/\/dev\?project=center&status=in-progress$/);
  await expect.poll(() => ids(page)).toEqual(['CC-0037', 'CC-0124']);
});

test('сырой HTML в теле задачи — текстом, без элементов', async ({ page }) => {
  await page.goto('/dev/CF-0635');
  const body = page.getByTestId('task-body');
  await expect(body).toContainText('<script>alert(1)</script>');
  await expect(body).toContainText('<img src=x onerror=alert(2)>');
  await expect(body.locator('script, img, a[href^="javascript"]')).toHaveCount(0);
});

test.describe('задачи нет', () => {
  test.use({ expectCleanConsole: false });
  test('неизвестный номер — спокойное «задачи нет»', async ({ page, consoleErrors }) => {
    await page.goto('/dev/CF-9999');
    await expect(page.getByRole('heading', { level: 1, name: 'Задачи CF-9999 нет' })).toBeVisible();
    await expect(page.getByRole('alert')).toHaveCount(0);
    onlyHttp(consoleErrors, 404);
  });
});

test('дорожная карта: вехи, спринты и задачи по порядку таблицы', async ({ page }) => {
  await page.goto('/dev');
  await page.getByTestId('dev-view-roadmap').click();
  await expect(page).toHaveURL(/\?view=roadmap$/);
  const factory = page.locator('[data-testid="roadmap"][data-project="factory"]');
  const ms = factory.getByTestId('roadmap-milestone');
  await expect(ms).toHaveCount(3);
  await expect(ms.nth(0)).toContainText('сделана 14.10');
  await expect(ms.nth(1)).toHaveAttribute('data-current', 'true');
  await expect(ms.nth(1)).toContainText('текущая');
  const sprint = ms.nth(1).getByTestId('roadmap-sprint').nth(1);
  await expect(sprint.getByTestId('roadmap-task').first()).toHaveAttribute('data-id', 'CF-0618');
  await expect(sprint.getByTestId('roadmap-task').first()).toContainText('в работе');

  await page.getByTestId('dev-project-center').click();
  await expect(page).toHaveURL(/view=roadmap&project=center$/);
  await expect(page.getByTestId('roadmap')).toHaveCount(1);
  await page.reload();
  await expect(page.getByTestId('roadmap')).toHaveAttribute('data-project', 'center');
  await page
    .locator('[data-testid="roadmap-task"][data-id="CC-0124"]')
    .getByTestId('task-link')
    .click();
  await expect(page).toHaveURL(/\/dev\/CC-0124$/);
});

test('ошибка чтения центра — сказано над списком, задачи фабрики видны', async ({ page, dev }) => {
  dev.state.sourceError = true;
  await page.goto('/dev');
  await expect(page.getByTestId('dev-source-error')).toContainText(
    'Задачи центра сейчас не прочитать',
  );
  await expect(page.getByTestId('dev-group').first()).toHaveAttribute('data-key', 'factory|2.9');
  await expect(page.locator('[data-testid="dev-group"][data-key^="center"]')).toHaveCount(0);
});

test.describe('телефон', () => {
  test.use({ viewport: { width: 375, height: 812 }, isMobile: true, hasTouch: true });
  for (const path of ['/dev', '/dev?status=open&q=%D1%82', '/dev/CC-0124', '/dev?view=roadmap']) {
    test(`${path}: без прокрутки вбок`, async ({ page }) => {
      await page.goto(path);
      await expect(
        page
          .getByTestId(
            path.includes('CC-0124')
              ? 'task-body'
              : path.includes('roadmap')
                ? 'roadmap'
                : 'dev-groups',
          )
          .first(),
      ).toBeVisible();
      await noSideScroll(page);
      // Номера и диапазоны в одну строку — не рвутся на дефисе.
      for (const el of await page.getByTestId('task-id-text').all())
        expect(
          await el.evaluate(
            (e) => new Set([...e.getClientRects()].map((r) => Math.round(r.top))).size,
          ),
        ).toBe(1);
    });
  }

  test('длинная строка в блоке кода переносится: не вылезает и не обрезается', async ({ page }) => {
    await page.goto('/dev/CC-0124');
    const pre = page.getByTestId('task-body').locator('pre');
    await expect(pre).toContainText('jq');
    const m = await pre.evaluate((e) => ({
      scroll: e.scrollWidth,
      client: e.clientWidth,
      right: e.getBoundingClientRect().right,
      vw: document.documentElement.clientWidth,
    }));
    expect(m.scroll).toBeLessThanOrEqual(m.client);
    expect(m.right).toBeLessThanOrEqual(m.vw);
  });

  test('метки статуса в списке выровнены с заголовком задачи', async ({ page }) => {
    await page.goto('/dev?status=wontfix,open&sort=id');
    await expect(rows(page).first()).toBeVisible();
    const shifts = await rows(page).evaluateAll((els) =>
      els.map((r) => {
        const title = r.querySelector('[data-testid="task-link"]')!.getBoundingClientRect().left;
        const pill = r.querySelector('[data-slot="status"]')!.getBoundingClientRect().left;
        return Math.round(pill - title);
      }),
    );
    expect(shifts.every((s) => s === 0)).toBe(true);
  });
});
