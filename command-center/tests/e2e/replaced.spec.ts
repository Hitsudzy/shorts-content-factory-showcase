// CC-0088: ролик, заменённый принятой пересборкой, решения не ждёт. Настоящий случай 12.10:
// первые версии rink-rivals и delver (example-film/2026-10-08T1824Z) без строки журнала —
// отказ оформили пересборкой, — их пересборка rebuilds/2026-10-09T1208Z принята и залита.
// Пользователь видел их в «Ждут вас» и отклонил как повтор. Подставной API; последний батч
// истории — этот (маршрут страницы главнее фикстуры).
import type { Page } from '@playwright/test';

import {
  REPLACED_REDO,
  REPLACED_RUN,
  REPLACED_SRC,
  REPLACED_UPLOADS,
} from '../../src/mocks/videos';
import { expect, noSideScroll, test } from './fixtures';

/** Батч REPLACED_SRC — последний в истории прогонов. */
async function latestIsReplaced(page: Page) {
  await page.route(
    (url) => url.pathname === '/api/batches/history',
    (route) => route.fulfill({ json: { channel: null, runs: [REPLACED_RUN], launches: [] } }),
  );
}

const at = (slug: string) =>
  `/videos?batch=${encodeURIComponent(REPLACED_SRC)}&v=${encodeURIComponent(slug)}`;

test.describe('заменён пересборкой', () => {
  test.beforeEach(async ({ publish }) => {
    for (const u of REPLACED_UPLOADS) publish.addUpload('example-film', u);
  });

  test('первая версия не в счётчике «Ждут вас» и не в «Ролики ждут решения»', async ({ page }) => {
    await latestIsReplaced(page);
    await page.goto('/');
    const text = page.getByTestId('attention-text');
    await expect(text).toContainText('В последнем батче решения не ждёт ни один ролик.');
    await expect(text).not.toContainText('Роликов без вердикта');
    const card = page.getByTestId('reels-card');
    await expect(card).toHaveAttribute('data-waiting', '0');
    await expect(card.getByTestId('reels-item')).toHaveCount(0);
    await expect(card.getByTestId('reels-replaced')).toContainText(
      'Заменены принятой пересборкой: 2',
    );
  });

  test('контроль: пересборка без вердикта — ролик в «Ждут вас», как раньше', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByTestId('attention-text')).toContainText(
      'Роликов без вердикта в последнем батче: 1.',
    );
    await expect(page.getByTestId('reels-card').getByTestId('reels-replaced')).toHaveCount(0);
  });

  test('«Ролики»: плашка, «заменён пересборкой — принят, залит», ссылка ведёт в пересборку', async ({
    page,
  }) => {
    await page.goto(`/videos?batch=${encodeURIComponent(REPLACED_SRC)}`);
    const reels = page.getByTestId('batch-videos');
    await expect(reels.getByRole('heading', { level: 2 })).toHaveText(
      '3 ролика · заменены пересборкой: 2 · пересборок: 2',
    );
    const rivalry = reels.locator('[data-testid="reel"][data-slug="rink-rivals"]');
    await expect(rivalry).toHaveAttribute('data-replaced', 'true');
    await expect(rivalry.getByTestId('reel-state')).toHaveText('заменён пересборкой');

    await rivalry.getByRole('link').click();
    const notice = page.getByTestId('replaced');
    await expect(notice.getByTestId('replaced-line')).toHaveText(
      'Заменён пересборкой 09.10, 15:08 — принят, залит X66dFJ80XgA (публикация 13.10).',
    );
    await expect(notice.getByTestId('replaced-upload')).toHaveAttribute(
      'href',
      'https://youtube.com/shorts/X66dFJ80XgA',
    );
    // Пути и записи — только под «подробнее».
    await expect(notice.getByText(`пересборка: ${REPLACED_REDO}`)).toBeHidden();
    await notice.getByText('Подробнее').click();
    await expect(notice.getByText(`пересборка: ${REPLACED_REDO}`)).toBeVisible();

    await notice.getByTestId('replaced-link').click();
    await expect(page).toHaveURL(new RegExp(`at=${encodeURIComponent(REPLACED_REDO)}`));
    await expect(page.getByTestId('video-detail')).toHaveAttribute('data-batch', REPLACED_REDO);
    await expect(page.getByTestId('acceptance-verdict')).toHaveText('принят');
    await expect(page.getByTestId('replaced')).toHaveCount(0);
  });

  test('delver: номер своей пересборки, а не delver другой (rJSXkLVswSs)', async ({ page }) => {
    await page.goto(at('delver'));
    const notice = page.getByTestId('replaced');
    await expect(notice.getByTestId('replaced-upload')).toHaveText('jHGkh2Zo0zw');
    await expect(notice).not.toContainText('rJSXkLVswSs');
  });

  test('вердикт не предлагается: кнопки — под «Всё равно дать вердикт» с предупреждением', async ({
    page,
    apiHits,
  }) => {
    await page.goto(at('rink-rivals'));
    const acc = page.getByTestId('acceptance');
    await expect(acc.getByTestId('acceptance-verdict')).toHaveText('заменён пересборкой');
    await expect(acc.getByTestId('acceptance-replaced')).toBeVisible();
    await expect(acc.getByRole('button', { name: 'Да', exact: true })).toBeHidden();
    await acc.getByText('Всё равно дать вердикт этой версии').click();
    await expect(acc.getByTestId('verdict-anyway-warning')).toContainText(
      'пересборку, её загрузку, слот и ротацию он не тронет',
    );
    await expect(acc.getByRole('button', { name: 'Да', exact: true })).toBeVisible();
    // Только чтение: открыть ролик и раскрыть кнопки — ни одной записи.
    expect(apiHits.filter((h) => !h.startsWith('GET '))).toEqual([]);
  });

  test('телефон 390: плашка в кадре, страница вбок не едет', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(at('rink-rivals'));
    await expect(page.getByTestId('replaced-upload')).toHaveText('X66dFJ80XgA');
    const box = (await page.getByTestId('replaced').boundingBox())!;
    expect(box.x).toBeGreaterThanOrEqual(16);
    expect(box.x + box.width).toBeLessThanOrEqual(390 - 16 + 1);
    await noSideScroll(page);
  });

  for (const vp of [
    { width: 1280, height: 800 },
    { width: 390, height: 844 },
  ]) {
    test(`переход к первой версии: плашка ниже липкой шапки · ${vp.width}`, async ({ page }) => {
      await page.setViewportSize(vp);
      await page.goto(`${at('rink-rivals')}&at=${encodeURIComponent(REPLACED_REDO)}`);
      await expect(page.getByTestId('video-detail')).toHaveAttribute('data-batch', REPLACED_REDO);
      await page.getByTestId('version-link').filter({ hasText: 'исходная' }).click();
      await expect(page.getByTestId('replaced')).toBeVisible();
      // Прокрутка к ролику закончилась: верх ролика стоит на месте.
      const top = () =>
        page.getByTestId('video-detail').evaluate((e) => e.getBoundingClientRect().top);
      await expect.poll(async () => Math.round(await top())).toBeGreaterThan(0);
      let prev = NaN;
      await expect
        .poll(async () => {
          const t = Math.round(await top());
          const still = t === prev;
          prev = t;
          return still;
        })
        .toBe(true);
      const m = await page.evaluate(() => ({
        header: document.querySelector('header')!.getBoundingClientRect().bottom,
        title: document.querySelector('[data-testid="video-detail"] h2')!.getBoundingClientRect()
          .top,
        notice: document.querySelector('[data-testid="replaced"]')!.getBoundingClientRect().top,
      }));
      expect(m.title).toBeGreaterThanOrEqual(m.header);
      expect(m.notice).toBeGreaterThanOrEqual(m.header);
    });
  }

  for (const theme of ['light', 'dark'] as const) {
    test(`контраст текста плашки и приёмки ≥ 4.5:1 · ${theme}`, async ({ page }) => {
      await page.addInitScript((t) => localStorage.setItem('cc-theme', t), theme);
      await page.goto(at('rink-rivals'));
      await expect(page.getByTestId('replaced-upload')).toHaveText('X66dFJ80XgA');
      await page.getByText('Всё равно дать вердикт этой версии').click();
      const ratios = await page.evaluate(() => {
        type C = [number, number, number, number];
        const parse = (c: string): C => {
          const n = (c.match(/[\d.]+/g) ?? []).map(Number);
          if (c.startsWith('color(srgb')) return [n[0]! * 255, n[1]! * 255, n[2]! * 255, n[3] ?? 1];
          return [n[0]!, n[1]!, n[2]!, n[3] ?? 1];
        };
        const over = (top: C, under: C): C => {
          const a = top[3];
          return [0, 1, 2].map((i) => top[i]! * a + under[i]! * (1 - a)).concat(1) as C;
        };
        /** Фон под элементом: слои фонов до первого непрозрачного, сложенные. */
        const bgOf = (el: Element | null): C => {
          const layers: C[] = [];
          for (; el; el = el.parentElement) {
            const c = parse(getComputedStyle(el).backgroundColor);
            if (c[3] > 0) layers.push(c);
            if (c[3] >= 1) break;
          }
          let acc: C = [255, 255, 255, 1];
          for (const l of layers.reverse()) acc = over(l, acc);
          return acc;
        };
        const lum = (c: C) => {
          const f = (v: number) => {
            const s = v / 255;
            return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
          };
          return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2]);
        };
        const sel = [
          '[data-testid="replaced-link"]',
          '[data-testid="replaced-upload"]',
          '[data-testid="replaced"] p',
          '[data-testid="replaced"] summary',
          '[data-testid="verdict-anyway"] summary',
          '[data-testid="verdict-anyway-warning"]',
          '[data-testid="acceptance-replaced"]',
          '[data-testid="acceptance-verdict"] [data-slot="status"]',
          '[data-replaced] [data-slot="status"]',
        ];
        return sel.flatMap((s) =>
          [...document.querySelectorAll(s)].map((e) => {
            const fg = parse(getComputedStyle(e).color);
            const bg = bgOf(e);
            const [a, b] = [lum(over(fg, bg)), lum(bg)].sort((x, y) => y - x);
            return { s, ratio: Math.round(((a! + 0.05) / (b! + 0.05)) * 100) / 100 };
          }),
        );
      });
      expect(ratios.length).toBeGreaterThanOrEqual(9);
      expect(ratios.filter((r) => r.ratio < 4.5)).toEqual([]);
    });
  }
});
