// CC-0116: ролик, отказанный после монтажа. Настоящий случай 13.10: sophie-adenot (Science
// 2001Z) отрендерен и отказан проверкой качества 24 < 40 — пересборка его не видела, а экран
// показывал бы ему вердикт. Подставной API: батч SCIENCE, sophie-adenot с mp4 и ролик без файла.
import { SCIENCE } from '../../src/mocks/videos';
import { expect, noSideScroll, test } from './fixtures';

const at = (slug?: string) =>
  `/videos?batch=${encodeURIComponent(SCIENCE)}${slug ? `&v=${encodeURIComponent(slug)}` : ''}`;

test.describe('отказан после монтажа', () => {
  test('в списке — причина словами; открыт — плеер, без вердикта, «Пересобрать…» → план → «да»', async ({
    page,
    videos,
  }) => {
    await page.goto(at());
    const reel = page.locator('[data-testid="reel"][data-slug="sophie-adenot"]');
    await expect(reel.getByTestId('reel-state')).toHaveText('отказан после монтажа');
    await expect(reel.getByTestId('reel-refused')).toHaveText(
      'Оценка ниже порога после штрафов: 24 из 40 — зависший кадр (1 блок, хук)',
    );
    await reel.getByRole('link').click();
    const detail = page.getByTestId('video-detail');
    await expect(detail).toHaveAttribute('data-slug', 'sophie-adenot');
    await expect(detail.locator('video')).toHaveCount(1);
    await expect(detail.getByTestId('refused-reason')).toContainText('24 из 40');
    await expect(detail.getByTestId('acceptance')).toHaveCount(0);
    await expect(detail.getByTestId('verdict-yes')).toHaveCount(0);
    await expect(detail.getByRole('button', { name: 'Пересобрать…' })).toHaveCount(1);
    await expect(detail.getByText(/\/Users\//)).toHaveCount(0);
    await expect(page.getByText(/score_below_threshold/).filter({ visible: true })).toHaveCount(0);

    await detail.getByTestId('refused-rebuild').click();
    const panel = page.getByTestId('rebuild');
    await expect(panel.getByTestId('rebuild-refused-reason')).toHaveText(
      'оценка ниже порога после штрафов: 24 из 40 — зависший кадр (1 блок, хук)',
    );
    await expect(panel.getByTestId('rebuild-mode-option').first()).toBeVisible();
    await panel.getByTestId('rebuild-open').click();
    const dialog = page.getByRole('alertdialog');
    await expect(dialog.getByTestId('plan-refused')).toContainText('отказан после монтажа');
    await dialog.getByTestId('rebuild-confirm').click();
    await expect(page.getByTestId('rebuild-done-reason')).toContainText('запущена');
    expect(videos.accepted).toEqual([]);
  });

  test('без файла: «Файла ролика нет», перемонтажу не с чего начать; телефон без сдвига вбок', async ({
    page,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(at('jwst-little-red-dots'));
    const detail = page.getByTestId('video-detail');
    await expect(detail.getByText('Файла ролика нет')).toBeVisible();
    await expect(detail.locator('video')).toHaveCount(0);
    await expect(detail.getByTestId('refused-reason')).toContainText('Всё из одного источника');
    await detail.getByTestId('refused-rebuild').click();
    await expect(page.getByTestId('rebuild-no-plan')).toBeVisible();
    await noSideScroll(page);
  });
});
