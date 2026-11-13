// CC-0121: скелетоны вместо прыжков. Ответы подставного API задерживаются до `release()`; пока
// блок читается, на его месте скелетон, и высота тела блока (от шапки до низа) до и после
// прихода данных расходится не больше чем на 8 px — страница не прыгает. Ширина — Desktop
// Chrome (1280), по ней подобраны высоты скелетонов.
//
// Сколько строк у скелетона: где число задаёт сама фабрика — как на рабочей фабрике (пять
// закреплённых агентов agents.lock.json, полная страница истории HISTORY_LIMIT = 20 прогонов),
// и тест отдаёт ответ такой формы; где число — данные канала (список правообладателей, футаж),
// — как у демо-мира src/mocks/rightsData.ts, его и отдаёт подставной API.
import type { Locator, Page } from '@playwright/test';

import { fixtures } from '../../src/mocks/fixtures';
import { expect, test } from './fixtures';

const SLACK = 8;

/** Страница истории прогонов (`HISTORY_LIMIT` в src/api/batches.ts). */
const HISTORY_PAGE = 20;

/** Агенты, закреплённые на рабочей фабрике (agents.lock.json). */
const PINNED = [
  'compliance-checker',
  'content-researcher',
  'footage-indexer',
  'trend-hunter',
  'video-editor',
];

/**
 * Задержать GET по шаблону, пока тест не скажет `release()`; дальше — обычный подставной API
 * или, если дан `body`, этот ответ.
 */
async function hold(
  page: Page,
  pattern: string | RegExp,
  body?: () => unknown,
): Promise<() => void> {
  let release!: () => void;
  const gate = new Promise<void>((r) => (release = r));
  await page.route(pattern, async (route) => {
    await gate;
    if (body) await route.fulfill({ json: body() });
    else await route.fallback();
  });
  return release;
}

/** Тело блока-карточки: от низа шапки (первый ребёнок) до низа последнего ребёнка. */
function bodyHeight(block: Locator): Promise<number> {
  return block.evaluate((e) => {
    const kids = [...e.children];
    const top = kids[0]!.getBoundingClientRect().bottom;
    const bottom = Math.max(...kids.slice(1).map((c) => c.getBoundingClientRect().bottom));
    return bottom - top;
  });
}

const pending = (block: Locator) => block.locator('[data-slot="pending"]');

/**
 * Снять высоты блоков под скелетоном, отпустить ответы и дождаться, что каждый блок без
 * скелетона и его высота — в пределах `SLACK` от прежней (опросом: следом могут дочитываться
 * мелкие запросы вроде «в копилке N»). Расхождение — сразу по всем блокам: было и стало.
 */
async function expectNoJump(blocks: Locator[], release: () => void) {
  for (const b of blocks) await expect(pending(b).first()).toBeVisible();
  const before = await Promise.all(blocks.map(bodyHeight));
  release();
  for (const b of blocks) await expect(pending(b)).toHaveCount(0);
  await expect
    .poll(async () => {
      const after = await Promise.all(blocks.map(bodyHeight));
      return after.map((h, i) =>
        Math.abs(h - before[i]!) <= SLACK
          ? 'ровно'
          : `блок ${i + 1}: скелетон ${before[i]} px, данные ${Math.round(h)} px`,
      );
    })
    .toEqual(blocks.map(() => 'ровно'));
}

test.describe('скелетоны вместо прыжков @cc-0121', () => {
  test('главная: «Фабрика», «Агенты», «Каналы» не прыгают при приходе данных', async ({ page }) => {
    const version = await hold(page, '**/api/version', () => ({
      ...fixtures.version,
      agents: PINNED.map((agent) => ({
        ...fixtures.version.agents[0]!,
        agent,
        path: `agents/${agent}`,
      })),
    }));
    const list = await hold(page, '**/api/channels');
    await page.goto('/');
    const factory = page.getByTestId('factory-card');
    const agents = page.getByTestId('agents-card');
    const channels = page.getByTestId('channels-card');
    // Скелетон для читалки — статус с прежним текстом.
    await expect(factory.getByRole('status')).toContainText('Спрашиваю фабрику о версии…');
    const below = page.getByTestId('batch-card');
    const topBefore = (await below.boundingBox())!.y;
    await expectNoJump([factory, agents, channels], () => {
      version();
      list();
    });
    await expect(factory.getByRole('heading', { name: /^Версия/ })).toBeVisible();
    // Блок под карточками тоже не сдвинулся.
    expect(Math.abs((await below.boundingBox())!.y - topBefore)).toBeLessThanOrEqual(SLACK);
  });

  test('батчи: «Прошлые прогоны» — страница строк скелетона той же высоты', async ({
    page,
    batches,
  }) => {
    // Полная страница истории, как на рабочей фабрике: прогоны демо-мира и их копии днями раньше.
    const release = await hold(page, /\/api\/batches\/history/, () => {
      const body = batches.history().body as { runs: { batch: string | null }[] };
      const runs = Array.from({ length: HISTORY_PAGE }, (_, i) => {
        const r = body.runs[i % body.runs.length]!;
        if (i < body.runs.length) return r;
        const day = String(30 - i).padStart(2, '0');
        return { ...r, batch: `${r.batch?.split('/')[0]}/2026-09-${day}T0200Z` };
      });
      return { ...body, runs };
    });
    await page.goto('/batches');
    const history = page.getByTestId('batch-history');
    await expect(history.getByRole('status')).toContainText('Читаю историю…');
    await expectNoJump([history], release);
    await expect(history.getByTestId('run').first()).toBeVisible();
  });

  test('без анимации при prefers-reduced-motion; полоски скрыты от читалки', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    const release = await hold(page, '**/api/version');
    await page.goto('/');
    const bar = page.getByTestId('factory-card').locator('[data-slot="skeleton"]').first();
    await expect(bar).toBeVisible();
    expect(await bar.evaluate((e) => getComputedStyle(e).animationName)).toBe('none');
    await expect(bar).toHaveAttribute('aria-hidden', 'true');
    await page.emulateMedia({ reducedMotion: 'no-preference' });
    expect(await bar.evaluate((e) => getComputedStyle(e).animationName)).not.toBe('none');
    release();
    await expect(page.getByTestId('factory-card').locator('[data-slot="pending"]')).toHaveCount(0);
  });
});
