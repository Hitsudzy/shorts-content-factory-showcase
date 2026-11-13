// Источники фактов по строкам (CC-0129) на вкладке «Данные канала», подставной API
// (src/mocks/channelData.ts, channelLists.ts): ярусы, «с любого сайта», виды фактов словами;
// правка → план с sha чтения → «да»; `ai_policy` и неизвестные поля строки уходят как были;
// проверка фабрики словами; сменившийся файл — «Список изменился, откройте заново»; телефон.
import { expect, noSideScroll, test } from './fixtures';

test('правка по строкам → план → «да»: ai_policy и чужие поля целы', async ({ page, channels }) => {
  await page.goto('/channels/example-film?tab=data');
  const card = page.getByTestId('fact-sources');
  await card.getByTestId('list-fact-sources-toggle').click();
  await expect(card.getByTestId('list-fact-sources-text')).toHaveCount(0);
  const t1 = card.getByTestId('rows-tier1');
  await expect(t1.getByTestId('rows-tier1-row')).toHaveCount(6);
  await expect(card.getByTestId('rows-tier2-row')).toHaveCount(2);
  await expect(card.getByTestId('rows-any-host-row')).toHaveCount(2);
  await expect(t1.getByTestId('rows-tier1-kind').first()).toHaveValue('энциклопедия');
  await expect(t1.getByTestId('rows-tier1-use').first()).toHaveValue('read_text');
  await expect(card.getByTestId('facts-kinds')).toContainText('кассовые сборы');
  // JSON — только под «Подробнее → как файл».
  await expect(card.getByTestId('list-fact-sources-file')).not.toBeVisible();

  const note = t1.getByTestId('rows-tier1-note').first();
  await note.fill('Фон, не новость');
  await card.getByTestId('rows-any-host-tier').nth(1).selectOption('2');
  await card.getByTestId('list-fact-sources-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('list-plan-changes')).toContainText('изменится');
  const body = channels.data.lists.state.plans.at(-1)!.body as {
    base_sha256: string;
    doc: {
      tiers: Record<string, Record<string, unknown>[]>;
      any_host: Record<string, unknown>[];
    };
  };
  expect(body.base_sha256).toBe('cd'.repeat(32));
  expect(body.doc.tiers['1']![0]).toMatchObject({
    note: 'Фон, не новость',
    sections: ['Production', 'Filming', 'Release'],
    ai_policy: { verdict: 'allowed', checked_on: '2026-10-08' },
  });
  expect(body.doc.any_host[1]).toMatchObject({ tier: 2, requires: null });
  await dialog.getByTestId('list-fact-sources-yes').pressSequentially('да');
  await dialog.getByTestId('list-fact-sources-confirm').click();
  await expect(card.getByTestId('list-done')).toContainText('Список записан');
  expect(channels.data.lists.state.written).toEqual(['example-film fact-sources']);
});

test('новое издание: проверки словами, пока не заполнено и не проверено фабрикой', async ({
  page,
  channels,
}) => {
  await page.goto('/channels/example-film?tab=data');
  const card = page.getByTestId('fact-sources');
  await card.getByTestId('list-fact-sources-toggle').click();
  await card.getByTestId('rows-tier1-add').click();
  const row = card.getByTestId('rows-tier1-row').nth(6);
  await row.getByTestId('rows-tier1-hosts').fill('Variety.com');
  const problems = row.getByTestId('rows-tier1-problems');
  await expect(problems).toContainText('строчными, без https:// и пути');
  await expect(problems).toContainText('Сайт ещё не проверен на правила для ИИ-ботов');
  await expect(card.getByTestId('list-fact-sources-why')).toContainText('Поправьте записи');
  await expect(card.getByTestId('list-fact-sources-open')).toHaveAttribute('aria-disabled', 'true');
  await expect(page.getByRole('alertdialog')).toHaveCount(0);
  expect(channels.data.lists.state.plans).toEqual([]);
});

test('проверка фабрики не прошла — строки словами, «да» нет', async ({ page }) => {
  await page.goto('/channels/example-science?tab=data');
  const card = page.getByTestId('fact-sources');
  await card.getByTestId('list-fact-sources-toggle').click();
  await expect(card.getByTestId('rows-tier1-row')).toHaveCount(1);
  await card.getByTestId('list-fact-sources-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('plan-head')).toContainText('записать нельзя');
  await expect(dialog.getByTestId('list-plan-invalid-lines')).toContainText(
    'Сайт ленты новостей example.org закрыт для всех роботов, а канал её читает',
  );
  await expect(dialog.getByTestId('list-fact-sources-yes')).toHaveCount(0);
});

test('файл сменился, пока правили, — «Список изменился, откройте заново»', async ({
  page,
  channels,
}) => {
  await page.goto('/channels/example-film?tab=data');
  const card = page.getByTestId('fact-sources');
  await card.getByTestId('list-fact-sources-toggle').click();
  await card.getByTestId('facts-kind-remove').first().click();
  channels.data.over['fact-sources example-film'] = { tiers: { '1': [] } };
  await card.getByTestId('list-fact-sources-open').click();
  const dialog = page.getByRole('alertdialog');
  await expect(dialog.getByTestId('list-changed')).toContainText(
    'Список изменился, откройте заново',
  );
  await expect(dialog.getByTestId('list-fact-sources-yes')).toHaveCount(0);
});

test('на телефоне — без прокрутки вбок', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels/example-tech?tab=data');
  const card = page.getByTestId('fact-sources');
  await card.getByTestId('list-fact-sources-toggle').click();
  await expect(card.getByTestId('rows-tier1-row')).toHaveCount(6);
  await noSideScroll(page);
});
