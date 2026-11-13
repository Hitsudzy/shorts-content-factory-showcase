// Происхождение футажа по строкам (CC-0130) на вкладке «Данные канала», подставной API
// (src/mocks/rights.ts, rightsData.ts, channelLists.ts): у Reel — официальные каналы с их каналами
// на YouTube, у Science — ещё источники и лицензии словами; правка → план с sha чтения → «да»;
// неизвестные поля и вложенная подпись уходят как были; проверка фабрики словами; сменившийся
// файл — «Список изменился, откройте заново»; телефон без прокрутки вбок.
import { expect, noSideScroll, test } from './fixtures';

type Doc = {
  _what?: string;
  official_channels: Record<string, unknown>[];
  footage_origins?: Record<string, unknown>[];
};

test('Reel: правка по строкам → план → «да»; owners и чужие поля целы', async ({
  page,
  rights,
}) => {
  await page.goto('/channels/example-film?tab=data');
  const card = page.getByTestId('footage-origin');
  await card.getByTestId('list-footage-origin-toggle').click();
  await expect(card.getByTestId('list-footage-origin-text')).toHaveCount(0);
  await expect(card.getByTestId('rows-origins')).toHaveCount(0);
  const rows = card.getByTestId('rows-official-row');
  await expect(rows).toHaveCount(3);
  await expect(card.getByTestId('list-footage-origin-file')).not.toBeVisible();

  const first = rows.first();
  await first.getByTestId('rows-official-what').fill('киностудия и стример');
  await first.getByTestId('rows-yt-add').click();
  const added = first.getByTestId('rows-yt-row').nth(2);
  await added.getByTestId('rows-yt-title').fill('Example Studios Германия');
  await expect(added.getByTestId('rows-yt-problems')).toHaveText('Впишите код канала');
  await added.getByTestId('rows-yt-id').fill('UCexample000000000000020');
  await expect(added.getByTestId('rows-yt-problems')).toHaveCount(0);

  await card.getByTestId('list-footage-origin-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('list-plan-changes')).toContainText('изменится');
  const body = rights.lists.state.plans.at(-1)!.body as { base_sha256: string; doc: Doc };
  expect(body.base_sha256).toMatch(/^[0-9a-f]{64}$/);
  expect(body.doc._what).toContain('Официальные каналы');
  expect(body.doc.footage_origins).toBeUndefined();
  expect(body.doc.official_channels[0]).toMatchObject({
    pattern: 'example studios',
    what: 'киностудия и стример',
    owners: ['example_studios'],
  });
  expect((body.doc.official_channels[0]!.channels as unknown[]).at(-1)).toEqual({
    id: 'UCexample000000000000020',
    title: 'Example Studios Германия',
    resolved_by: 'вписан вручную в центре управления',
  });
  await dialog.getByTestId('list-footage-origin-yes').pressSequentially('да');
  await dialog.getByTestId('list-footage-origin-confirm').click();
  await expect(card.getByTestId('list-done')).toContainText('Список записан');
  expect(rights.lists.state.written).toEqual(['example-film footage-origin']);
});

test('Science: источники, лицензии словами; подпись и оговорки — во вложенных полях', async ({
  page,
  rights,
}) => {
  await page.goto('/channels/example-science?tab=data');
  const card = page.getByTestId('footage-origin');
  await card.getByTestId('list-footage-origin-toggle').click();
  const origins = card.getByTestId('rows-origins-row');
  await expect(origins).toHaveCount(3);
  const nasa = origins.first();
  await expect(nasa.getByTestId('rows-origins-licence')).toHaveValue('public_domain');
  await expect(nasa.getByTestId('rows-origins-licence').locator('option:checked')).toHaveText(
    'общественное достояние',
  );
  await expect(nasa.getByTestId('footage-found-by')).toContainText('API архива');
  await expect(card.getByTestId('rows-accepted-id').nth(1)).toHaveValue(
    'CC BY (с указанием автора)',
  );
  await expect(card.getByTestId('rows-refused-id').first()).toHaveValue(
    'без коммерческого использования (NC)',
  );

  await nasa
    .getByTestId('rows-origins-caveats')
    .fill('Эмблему NASA на обложку не ставим.\nАстронавты — без намёка на одобрение.');
  await card.getByTestId('list-footage-origin-open').click();
  await expect(page.getByRole('alertdialog').getByTestId('list-plan-changes')).toContainText(
    'изменится',
  );
  const doc = (rights.lists.state.plans.at(-1)!.body as { doc: Doc }).doc;
  expect(doc.footage_origins![0]).toMatchObject({
    name: 'NASA Image and Video Library',
    attribution: { required: false, requested: true, credit: 'NASA', on_screen: false },
    caveats: ['Эмблему NASA на обложку не ставим.', 'Астронавты — без намёка на одобрение.'],
  });
  expect(doc.footage_origins![0]!.found_by).toHaveLength(2);
});

test('новый источник: одна ошибка за раз, план не спрашиваем', async ({ page, rights }) => {
  await page.goto('/channels/example-science?tab=data');
  const card = page.getByTestId('footage-origin');
  await card.getByTestId('list-footage-origin-toggle').click();
  await card.getByTestId('rows-origins-add').click();
  const row = card.getByTestId('rows-origins-row').nth(3);
  const problems = row.getByTestId('rows-origins-problems');
  await expect(problems.locator('li')).toHaveCount(1);
  await expect(problems).toHaveText('Впишите короткое имя');
  await row.getByTestId('rows-origins-id').fill('eso_hubble');
  await expect(problems).toHaveText('Выберите лицензию');
  await row.getByTestId('rows-origins-licence').selectOption('cc_by');
  await expect(problems).toHaveText('Впишите страницу с условиями источника');
  await expect(card.getByTestId('list-footage-origin-open')).toHaveAttribute(
    'aria-disabled',
    'true',
  );
  expect(rights.lists.state.plans).toEqual([]);
});

test('проверка фабрики не прошла — строки словами, «да» нет', async ({ page, rights }) => {
  rights.state.footageRefuse['example-science'] = [
    'footage_origins[0] (nasa): found_by[1] does not say `works_now`',
    'official_channels[1] (european southern observatory|eso) channels[0]: no @handle it was resolved from',
  ];
  await page.goto('/channels/example-science?tab=data');
  const card = page.getByTestId('footage-origin');
  await card.getByTestId('list-footage-origin-toggle').click();
  await card.getByTestId('list-footage-origin-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('plan-head')).toContainText('записать нельзя');
  const lines = dialog.getByTestId('list-plan-invalid-lines');
  await expect(lines).toContainText('Источник «NASA»: у способа 2 не отмечено, работает ли он');
  await expect(lines).toContainText('Правообладатель «ESO», канал 1: не вписано @имя канала');
  await expect(dialog.getByText(/works_now/).first()).toBeHidden();
  await expect(dialog.getByTestId('list-footage-origin-yes')).toHaveCount(0);
});

test('файл сменился, пока правили, — «Список изменился, откройте заново»', async ({
  page,
  rights,
}) => {
  await page.goto('/channels/example-film?tab=data');
  const card = page.getByTestId('footage-origin');
  await card.getByTestId('list-footage-origin-toggle').click();
  await card.getByTestId('rows-official-remove').last().click();
  rights.state.footage['example-film'] = { official_channels: [] };
  await card.getByTestId('list-footage-origin-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('list-changed')).toContainText(
    'Список изменился, откройте заново',
  );
  await expect(dialog.getByTestId('list-footage-origin-yes')).toHaveCount(0);
});

test('на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels/example-science?tab=data');
  const card = page.getByTestId('footage-origin');
  await card.getByTestId('list-footage-origin-toggle').click();
  await expect(card.getByTestId('rows-origins-row')).toHaveCount(3);
  await noSideScroll(page);
});
