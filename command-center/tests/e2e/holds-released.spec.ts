// «Публикация» → «Холды публикации», CC-0170: свёрнутый список «Снятые за 14 дней (N)» на
// подставном `GET /api/publish/holds/released` (src/mocks/publish.ts). Раскрыть — строка фабрики
// «Удержание снято: флаг на s2, в ролике s1, подпись не нужна», снова поставленное — с отметкой,
// сцены флага у открытого холда. Компьютер и телефон 390 px — без бокового скролла.
import { TECH } from '../../src/mocks/publish';
import { expect, noSideScroll, test } from './fixtures';

// У подставного Tech ротация нарочно не настроена: GET /rotation — 409 rotation_broken, и
// браузер пишет это в консоль. Остальное — как обычно.
test.use({ expectCleanConsole: false });

for (const phone of [false, true]) {
  test.describe(phone ? 'снятые холды: телефон 390' : 'снятые холды: компьютер', () => {
    test.beforeEach(async ({ page }) => {
      if (phone) await page.setViewportSize({ width: 390, height: 844 });
    });

    test('раскрыть «Снятые за 14 дней» — строки фабрики и отметка', async ({ page }) => {
      await page.goto(`/publishing?channel=${TECH}`);
      const holds = page.getByTestId('holds');
      const list = holds.getByTestId('holds-released');
      const summary = list.getByTestId('holds-released-summary');
      await expect(summary).toHaveText('Снятые за 14 дней (3)');
      await expect(list.getByTestId('hold-released-line').first()).toBeHidden();
      await expect(holds.getByTestId('hold').getByTestId('hold-scenes')).toHaveText(
        'флаг чувствительности: сцена s2',
      );
      await summary.click();
      const lines = list.getByTestId('hold-released-line');
      await expect(lines).toHaveText([
        'Удержание снова стоит: флаг на s2, в ролике s2, нужна подпись',
        'Удержание снято: флаг на s2, в ролике s1, подпись не нужна',
        'Удержание снято: посмотрел: без подробностей, источники — новости',
      ]);
      await expect(list.getByTestId('hold-reopened')).toHaveCount(1);
      await expect(list.getByTestId('hold-reopened')).toHaveText('снова стоит, нужна подпись');
      await expect(list.getByTestId('hold-scenes').last()).toHaveText(
        'флаг чувствительности: вся тема',
      );
      await noSideScroll(page);
    });
  });
}
