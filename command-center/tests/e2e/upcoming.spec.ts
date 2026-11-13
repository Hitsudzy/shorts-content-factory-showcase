// CC-0138: «Ближайшие публикации» главной и строки «Пауза» / «Ближайшая публикация» в обзоре
// канала — живые, по очередям «Публикации» (src/mocks/publish.ts: Reel и Tech — 01:00 МСК,
// у Science слота нет и стоит пауза), без «скоро · версия».
import { TECH, TECH_QUEUE } from '../../src/mocks/publish';
import { expect, noSideScroll, onlyHttp, test } from './fixtures';

test('главная: слоты всех каналов на 3 дня, канал без слота — строкой, переход в ленту', async ({
  page,
}) => {
  await page.goto('/');
  const card = page.getByTestId('publications-card');
  await expect(card.getByRole('heading', { name: 'Очередь на 3 дня' })).toBeVisible();
  await expect(card.getByText(/Скоро|версия 0\./)).toHaveCount(0);
  const rows = card.getByTestId('publications-slot');
  await expect(rows).toHaveCount(6);
  const tech = card.locator(`[data-testid="publications-slot"][data-channel="${TECH}"]`);
  await expect(tech.getByTestId('publications-title')).toHaveText([...TECH_QUEUE].map(cap));
  await expect(tech.first()).toContainText('завтра01:00 МСК');
  await expect(tech.first().getByTestId('publications-time')).toHaveText('01:00 МСК');
  await expect(tech.first().getByTestId('publications-channel')).toHaveText('ExampleTech');
  await expect(rows.nth(2).getByTestId('publications-title')).toContainText(
    'Delver Was a $160 Million Bet',
  );
  await expect(card.getByTestId('publications-note')).toHaveText('ExampleScience — слот не задан');

  await expect(tech.first().getByRole('link')).toHaveAttribute(
    'href',
    '/publishing?channel=example-tech&slot=2026-10-11%2Fhomepod',
  );
  // Строка ведёт в ленту канала с открытой карточкой этого ролика.
  await rows.nth(2).getByRole('link').click();
  await expect(page).toHaveURL(/\/publishing\?channel=example-film&slot=2026-10-12%2Fdigger$/);
  await expect(page.getByTestId('slot-feed')).toHaveAttribute('data-channel', 'example-film');
  await expect(page.getByTestId('studio-card')).toHaveAttribute('data-slug', 'delver');
});

test.describe('свободный слот Tech: в консоли — только 409 ротации', () => {
  test.use({ expectCleanConsole: false });

  test('главная: свободный слот — «свободно», ведёт в ленту канала', async ({
    page,
    publish,
    consoleErrors,
  }) => {
    delete publish.channels[TECH]!.taken[1];
    await page.goto('/');
    const free = page.locator(
      `[data-testid="publications-slot"][data-channel="${TECH}"][data-slug=""]`,
    );
    await expect(free).toContainText('свободно');
    await free.getByRole('link').click();
    await expect(page).toHaveURL(/\/publishing\?channel=example-tech$/);
    // CC-0159: у ExampleTech ротация не настроена, и «Публикация» канала получает на неё 409
    // `rotation_broken` (src/mocks/publish.ts — как у живой фабрики); браузер пишет отказ в
    // консоль. Раньше тест кончался до ответа, а под нагрузкой ответ успевал — и падал на
    // «ошибке в консоли». Теперь ждём отказ на экране и пропускаем ровно его.
    await expect(page.getByTestId('state-rotation').getByTestId('state-failed')).toBeVisible();
    onlyHttp(consoleErrors, 409);
  });
});

test('канал со слотом: ближайшая публикация ссылкой на слот, паузы нет', async ({ page }) => {
  await page.goto(`/channels/${TECH}`);
  const nearest = page.getByTestId('nearest-row');
  await expect(nearest).toHaveText('завтра, 01:00 МСК · Homepod');
  await expect(page.getByTestId('pause-row')).toHaveText('нет · поставить');
  await expect(page.getByText(/\(0\.\d\)/)).toHaveCount(0);
  await expect(nearest).toHaveAttribute(
    'href',
    '/publishing?channel=example-tech&slot=2026-10-11%2Fhomepod',
  );
});

test('канал без слота и на паузе: «слот не задан», пауза — ссылкой в «Публикацию»', async ({
  page,
}) => {
  await page.goto('/channels/example-science');
  await expect(page.getByTestId('nearest-row')).toHaveText('слот не задан');
  const pause = page.getByTestId('pause-row');
  await expect(pause).toHaveAttribute('data-state', 'paused');
  await expect(pause).toHaveText('на паузе, без срока · снять');
  await pause.getByRole('link', { name: 'снять паузу в разделе «Публикация»' }).click();
  await expect(page).toHaveURL(/\/publishing\?channel=example-science$/);
  await expect(page.getByTestId('state-pause')).toContainText('на паузе');
});

test('телефон: карточка публикаций и строки канала без прокрутки вбок и без наездов', async ({
  page,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto('/');
  await expect(page.getByTestId('publications-slot')).toHaveCount(6);
  await noSideScroll(page);
  // Названия всех строк начинаются на одной линии; день и время не наезжают на название.
  const titles = await page
    .getByTestId('publications-title')
    .evaluateAll((els) => els.map((e) => Math.round(e.getBoundingClientRect().left)));
  expect(new Set(titles).size).toBe(1);
  const whenRight = await page
    .getByTestId('publications-time')
    .evaluateAll((els) => Math.max(...els.map((e) => e.getBoundingClientRect().right)));
  expect(whenRight).toBeLessThanOrEqual(titles[0]!);

  for (const id of [TECH, 'example-science']) {
    await page.goto(`/channels/${id}`);
    await expect(page.getByTestId('nearest-row')).toBeVisible();
    await expect(page.getByTestId('pause-row')).toBeVisible();
    await noSideScroll(page);
    for (const [label, value] of [
      ['Ближайшая публикация', 'nearest-row'],
      ['Пауза', 'pause-row'],
    ] as const) {
      const a = await page.getByText(label, { exact: true }).boundingBox();
      const b = await page.getByTestId(value).boundingBox();
      expect(apart(a!, b!), `${id}: «${label}» и значение не наезжают`).toBe(true);
    }
    const title = await page.locator('#channel-title').boundingBox();
    const ask = await page.getByTestId('ask-channel').boundingBox();
    expect(apart(title!, ask!), `${id}: имя канала и «Попросить»`).toBe(true);
  }
});

type Box = { x: number; y: number; width: number; height: number };
const apart = (a: Box, b: Box) =>
  a.x + a.width <= b.x + 0.5 ||
  b.x + b.width <= a.x + 0.5 ||
  a.y + a.height <= b.y + 0.5 ||
  b.y + b.height <= a.y + 0.5;

function cap(slug: string) {
  return slug[0]!.toUpperCase() + slug.slice(1);
}
