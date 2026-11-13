// Правка списков канала и сборка концовки на «Данных канала» (CC-0115 шаг 3): партнёрские
// ссылки и ваша часть блок-листа — по строкам (поля, добавить/убрать, проверка словами; JSON —
// только «как файл»), источники фактов (CC-0129) и происхождение футажа (CC-0130) — по строкам;
// план с sha чтения, «да» набирает пользователь, сменившийся файл — «Список изменился, откройте
// заново», ошибка в строке — без плана, отказы фабрики словами, концовка — план и запуск.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { channels, rights } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

async function open(id = 'example-tech') {
  const user = userEvent.setup();
  renderApp(`/channels/${id}?tab=data`);
  const d = await screen.findByTestId('channel-data');
  return { user, d };
}

async function editAffiliate() {
  const r = await open();
  const card = await within(r.d).findByTestId('affiliate');
  await r.user.click(within(card).getByTestId('list-affiliate-toggle'));
  return { ...r, card };
}

async function editFacts(id = 'example-film') {
  const r = await open(id);
  const card = await within(r.d).findByTestId('fact-sources');
  await r.user.click(within(card).getByTestId('list-fact-sources-toggle'));
  return { ...r, card };
}

async function editOrigin(id = 'example-film') {
  const r = await open(id);
  const card = await within(r.d).findByTestId('footage-origin');
  await r.user.click(within(card).getByTestId('list-footage-origin-toggle'));
  return { ...r, card };
}

const lastOrigin = <T,>() => (rights.lists.state.plans.at(-1)!.body as { doc: T }).doc;
type OriginDoc = {
  _what?: string;
  official_channels: Record<string, unknown>[];
  footage_origins: Record<string, unknown>[];
};

type FactDoc = {
  tiers: Record<string, Record<string, unknown>[]>;
  any_host: Record<string, unknown>[];
  kinds: string[];
  do_not_take: unknown[];
};

const lastDoc = <T,>() => (channels.data.lists.state.plans.at(-1)!.body as { doc: T }).doc;

describe('данные канала: правка списков и концовка (CC-0115 шаг 3)', () => {
  it('партнёрские ссылки по строкам: убрать товар → план с sha чтения → «да» → записано', async () => {
    const { user, card } = await editAffiliate();
    const products = within(card).getByTestId('rows-products');
    expect(within(products).getAllByTestId('rows-products-row')).toHaveLength(2);
    expect(within(card).queryByTestId('list-affiliate-text')).toBeNull();
    await user.click(within(products).getAllByTestId('rows-products-remove')[1]!);
    await user.click(within(card).getByTestId('list-affiliate-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('list-plan-changes')).toHaveTextContent('изменится');
    const sent = channels.data.lists.state.plans.at(-1)!;
    expect(sent.list).toBe('affiliate');
    expect(sent.body).toMatchObject({ base_sha256: 'ef'.repeat(32) });
    expect(lastDoc<{ products: { id: string }[] }>().products.map((p) => p.id)).toEqual([
      'pixel-10',
    ]);
    const confirm = within(dialog).getByTestId('list-affiliate-confirm');
    expect(within(dialog).getByTestId('list-affiliate-yes')).toHaveValue('');
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByTestId('list-affiliate-yes'), 'да');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    expect(await within(card).findByTestId('list-done')).toHaveTextContent('Список записан');
    expect(channels.data.lists.state.written).toEqual(['example-tech affiliate']);
    await waitFor(() =>
      expect(within(card).getByTestId('affiliate-counts')).toHaveTextContent('товаров: 1'),
    );
  });

  it('новый товар: проверки словами, пока не заполнен; поля уходят в документ', async () => {
    const { user, card } = await editAffiliate();
    const products = within(card).getByTestId('rows-products');
    await user.click(within(products).getByTestId('rows-products-add'));
    const row = within(products).getAllByTestId('rows-products-row')[2]!;
    expect(within(row).getByTestId('rows-products-problems')).toHaveTextContent(
      'Впишите хотя бы одно название товара',
    );
    expect(within(card).getByTestId('list-affiliate-why')).toHaveTextContent('Поправьте записи');
    expect(within(card).getByTestId('list-affiliate-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    await user.type(within(row).getByTestId('rows-products-names'), 'Galaxy S26, Galaxy');
    await user.type(within(row).getByTestId('rows-products-id'), 'galaxy-s26');
    await user.selectOptions(within(row).getByTestId('rows-products-programme'), 'amazon-us');
    await user.type(within(row).getByTestId('rows-products-url'), 'https://amzn.to/z');
    expect(within(row).getByTestId('rows-products-problems')).toHaveTextContent('нет вашей метки');
    await user.clear(within(row).getByTestId('rows-products-url'));
    await user.type(
      within(row).getByTestId('rows-products-url'),
      'https://amzn.to/z?tag=example-20',
    );
    expect(within(row).queryByTestId('rows-products-problems')).toBeNull();
    await user.click(within(card).getByTestId('list-affiliate-open'));
    await screen.findByRole('alertdialog');
    expect(lastDoc<{ products: unknown[] }>().products[2]).toMatchObject({
      id: 'galaxy-s26',
      names: ['Galaxy S26', 'Galaxy'],
      programme: 'amazon-us',
      added_by: 'user',
    });
  });

  it('происхождение футажа Reel по строкам: правка канала → план → «да»; чужие поля целы', async () => {
    const { user, card } = await editOrigin();
    // JSON — только под «Подробнее → как файл».
    expect(within(card).queryByTestId('list-footage-origin-text')).toBeNull();
    expect(within(card).getByTestId('list-footage-origin-file')).not.toBeVisible();
    expect(within(card).queryByTestId('rows-origins')).toBeNull();
    const rows = within(card).getAllByTestId('rows-official-row');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Example Studios');
    const title = within(rows[0]!).getAllByTestId('rows-yt-title')[1]!;
    await user.clear(title);
    await user.type(title, 'Example Studios Великобритания');
    await user.click(within(card).getByTestId('list-footage-origin-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('list-plan-changes')).toHaveTextContent('изменится');
    const doc = lastOrigin<OriginDoc>();
    expect(doc._what).toContain('Официальные каналы');
    expect(Object.keys(doc)).not.toContain('footage_origins');
    expect(doc.official_channels[0]).toMatchObject({
      owners: ['example_studios'],
      channels: [
        { id: 'UCexample000000000000050', resolved_by: 'videos.list по ролику батча' },
        { title: 'Example Studios Великобритания', resolved_by: 'по @имени' },
      ],
    });
    await user.type(within(dialog).getByTestId('list-footage-origin-yes'), 'да');
    await user.click(within(dialog).getByTestId('list-footage-origin-confirm'));
    expect(await within(card).findByTestId('list-done')).toHaveTextContent('Список записан');
    expect(rights.lists.state.written).toEqual(['example-film footage-origin']);
  });

  it('новый канал правообладателя: пусто — «впишите», не тот вид — словами; план не спрашиваем', async () => {
    const { user, card } = await editOrigin();
    const row = within(card).getAllByTestId('rows-official-row')[2]!;
    await user.click(within(row).getByTestId('rows-yt-add'));
    const problems = () => within(row).getByTestId('rows-yt-problems');
    expect(problems()).toHaveTextContent('Впишите код канала');
    expect(problems()).not.toHaveTextContent('24 знака');
    await user.type(within(row).getAllByTestId('rows-yt-id')[1]!, 'UC123');
    expect(problems()).toHaveTextContent('Код канала — 24 знака, начинается с UC');
    expect(within(card).getByTestId('list-footage-origin-why')).toHaveTextContent(
      'Поправьте записи',
    );
    await user.click(within(card).getByTestId('list-footage-origin-open'));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(rights.lists.state.plans).toEqual([]);
  });

  it('Science: источники и лицензии словами; правка подписи — attribution и found_by целы', async () => {
    const { user, card } = await editOrigin('example-science');
    const origins = within(card).getAllByTestId('rows-origins-row');
    expect(origins).toHaveLength(3);
    const nasa = origins[0]!;
    const licence = within(nasa).getByTestId('rows-origins-licence') as HTMLSelectElement;
    expect(licence.value).toBe('public_domain');
    expect(licence.selectedOptions[0]).toHaveTextContent('общественное достояние');
    expect(within(nasa).getByTestId('footage-found-by')).toHaveTextContent(
      'API архива (пока не работает)',
    );
    expect(within(card).getAllByTestId('rows-accepted-id')[1]).toHaveValue(
      'CC BY (с указанием автора)',
    );
    expect(within(card).getAllByTestId('rows-refused-row')).toHaveLength(2);
    const credit = within(nasa).getByTestId('rows-origins-attribution.credit');
    await user.clear(credit);
    await user.type(credit, 'NASA/JPL');
    await user.selectOptions(
      within(nasa).getByTestId('rows-origins-attribution.where'),
      'description+on_screen',
    );
    await user.click(within(card).getByTestId('list-footage-origin-open'));
    await screen.findByRole('alertdialog');
    const doc = lastOrigin<OriginDoc>();
    expect(doc.footage_origins[0]).toMatchObject({
      licence: 'public_domain',
      quote: 'обычно не охраняются авторским правом в США',
      attribution: {
        required: false,
        requested: true,
        credit: 'NASA/JPL',
        where: 'description+on_screen',
        on_screen: true,
      },
    });
    expect(doc.footage_origins[0]!.found_by).toHaveLength(2);
    expect(doc.footage_origins[0]!.caveats).toHaveLength(2);
  });

  it('Science: отказ проверки фабрики — словами, строка фабрики под «подробнее»', async () => {
    rights.state.footageRefuse['example-science'] = [
      'footage_origins[0] (nasa): found_by[1] does not say `works_now`',
    ];
    const { user, card } = await editOrigin('example-science');
    await user.click(within(card).getByTestId('list-footage-origin-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('list-plan-invalid-lines')).toHaveTextContent(
      'Источник «NASA»: у способа 2 не отмечено, работает ли он',
    );
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('записать нельзя');
    expect(within(dialog).getAllByText(/works_now/)[0]).not.toBeVisible();
    expect(within(dialog).queryByTestId('list-footage-origin-yes')).toBeNull();
  });

  it('происхождение футажа: файл сменился — «Список изменился, откройте заново»', async () => {
    const { user, card } = await editOrigin();
    rights.state.footage['example-film'] = { official_channels: [] };
    await user.click(within(card).getByTestId('list-footage-origin-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('list-changed')).toHaveTextContent(
      'Список изменился, откройте заново',
    );
    expect(within(dialog).queryByTestId('list-footage-origin-yes')).toBeNull();
  });

  it('источники фактов по строкам: правка → план → «да»; ai_policy и чужие поля целы', async () => {
    const { user, card } = await editFacts();
    expect(within(card).queryByTestId('list-fact-sources-text')).toBeNull();
    const t1 = within(card).getByTestId('rows-tier1');
    expect(within(t1).getAllByTestId('rows-tier1-row')).toHaveLength(6);
    expect(
      within(within(card).getByTestId('rows-tier2')).getAllByTestId('rows-tier2-row'),
    ).toHaveLength(2);
    expect(
      within(within(card).getByTestId('rows-any-host')).getAllByTestId('rows-any-host-row'),
    ).toHaveLength(2);
    // Коды — словами: род источника, как брать, виды фактов.
    const kinds = within(t1).getAllByTestId('rows-tier1-kind') as HTMLInputElement[];
    expect(kinds[0]!.value).toBe('энциклопедия');
    expect(within(card).getByTestId('facts-kinds')).toHaveTextContent('кассовые сборы');
    expect(within(t1).getAllByTestId('facts-ai-policy')[0]).toHaveTextContent(
      'Сайт открыт для ИИ-ботов, проверено 08.10.2026',
    );
    const notes = within(t1).getAllByTestId('rows-tier1-note') as HTMLInputElement[];
    await user.clear(notes[0]!);
    await user.type(notes[0]!, 'Фон, не новость');
    await user.click(within(t1).getAllByTestId('rows-tier1-major_outlet')[0]!);
    await user.click(within(card).getAllByTestId('facts-kind-remove')[1]!);
    await user.click(within(card).getByTestId('list-fact-sources-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('list-plan-changes')).toHaveTextContent('изменится');
    expect(channels.data.lists.state.plans.at(-1)!.body).toMatchObject({
      base_sha256: 'cd'.repeat(32),
    });
    const doc = lastDoc<FactDoc>();
    expect(doc.tiers['1']![0]).toMatchObject({
      id: 'wikipedia',
      note: 'Фон, не новость',
      major_outlet: true,
      sections: ['Production', 'Filming', 'Release'],
      ai_policy: { verdict: 'allowed', checked_on: '2026-10-08' },
    });
    expect(doc.tiers['2']![0]!.ai_policy).toMatchObject({ verdict: 'forbidden' });
    expect(doc.any_host[1]).toMatchObject({ source_type: 'studio_press', requires: null });
    expect(doc.kinds).not.toContain('box_office');
    expect(doc.do_not_take).toHaveLength(3);
    await user.type(within(dialog).getByTestId('list-fact-sources-yes'), 'да');
    await user.click(within(dialog).getByTestId('list-fact-sources-confirm'));
    expect(await within(card).findByTestId('list-done')).toHaveTextContent('Список записан');
    expect(channels.data.lists.state.written).toEqual(['example-film fact-sources']);
  });

  it('новое издание без проверки robots.txt — словами, план не спрашиваем', async () => {
    const { user, card } = await editFacts();
    const t2 = within(card).getByTestId('rows-tier2');
    await user.click(within(t2).getByTestId('rows-tier2-add'));
    const row = within(t2).getAllByTestId('rows-tier2-row')[2]!;
    expect(within(row).getByTestId('facts-ai-policy')).toHaveTextContent(
      'Сайт ещё не проверен на правила для ИИ-ботов',
    );
    await user.type(within(row).getByTestId('rows-tier2-id'), 'ign');
    await user.type(within(row).getByTestId('rows-tier2-hosts'), 'collider.com');
    const problems = within(row).getByTestId('rows-tier2-problems');
    expect(problems).toHaveTextContent(
      'Сайт «collider.com» уже есть — в источниках только для ссылки, запись 1',
    );
    expect(problems).toHaveTextContent('Сайт ещё не проверен на правила для ИИ-ботов');
    expect(within(card).getByTestId('list-fact-sources-why')).toHaveTextContent('Поправьте записи');
    expect(within(card).getByTestId('list-fact-sources-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(within(card).getByTestId('list-fact-sources-file')).toHaveTextContent('"id": "ign"');
  });

  it('виды фактов: добавить из знакомых; убрать все — словами', async () => {
    const { user, card } = await editFacts();
    await user.selectOptions(within(card).getByTestId('facts-kind-add'), 'measurement');
    expect(within(card).getByTestId('facts-kinds')).toHaveTextContent('измерение');
    for (const b of within(card).getAllByTestId('facts-kind-remove').reverse()) await user.click(b);
    expect(within(card).getByTestId('facts-doc-problems')).toHaveTextContent(
      'Нужен хотя бы один вид фактов',
    );
    expect(within(card).getByTestId('list-fact-sources-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('файл сменился, пока правили, — «Список изменился, откройте заново»', async () => {
    const { user, card } = await editAffiliate();
    channels.data.over['affiliate example-tech'] = { programmes: [], products: [] };
    await user.click(within(card).getByTestId('list-affiliate-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('list-changed')).toHaveTextContent(
      'Список изменился, откройте заново',
    );
    expect(within(dialog).queryByTestId('list-affiliate-yes')).toBeNull();
  });

  it('проверка фабрики не прошла — «записать нельзя», строки фабрики словами', async () => {
    const { user, card } = await editFacts('example-science');
    await user.click(within(card).getAllByTestId('facts-kind-remove').at(-1)!);
    await user.click(within(card).getByTestId('list-fact-sources-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('list-plan-invalid-lines')).toHaveTextContent(
      'Сайт ленты новостей example.org закрыт для всех роботов, а канал её читает',
    );
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('записать нельзя');
    expect(within(dialog).getAllByText(/sources\.rss\.feeds/)[0]).not.toBeVisible();
    expect(within(dialog).queryByTestId('list-fact-sources-yes')).toBeNull();
  });

  it('отказ «да» словами; ничего не записано', async () => {
    channels.data.lists.state.actRefuse = 'batch_open';
    const { user, card } = await editAffiliate();
    await user.click(within(card).getByTestId('list-affiliate-open'));
    const dialog = await screen.findByRole('alertdialog');
    await user.type(await within(dialog).findByTestId('list-affiliate-yes'), 'да');
    await user.click(within(dialog).getByTestId('list-affiliate-confirm'));
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveTextContent('Идёт батч канала');
    expect(channels.data.lists.state.written).toEqual([]);
  });

  it('партнёрские ссылки: сеть, метка, код ссылки — по-русски и с подсказкой (CC-0131)', async () => {
    const { card } = await editAffiliate();
    for (const label of [
      'Партнёрская сеть, латиницей',
      'Ваша метка в программе',
      'или код ссылки (если метки нет)',
    ])
      expect(within(card).getAllByText(label)[0]).toHaveAttribute('tabindex', '0');
  });

  it('концовка Tech: «Собрать концовку…» → план → «да» → рендер запущен', async () => {
    const { user, d } = await open('example-tech');
    const ending = await within(d).findByTestId('ending');
    await user.click(within(ending).getByTestId('ending-render-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('plan-head')).toHaveTextContent('можно собрать');
    expect(within(dialog).getByTestId('ending-plan-needs')).toHaveTextContent('шрифт надписи');
    await user.type(within(dialog).getByTestId('ending-render-yes'), 'да');
    await user.click(within(dialog).getByTestId('ending-render-confirm'));
    expect(await within(ending).findByTestId('ending-started')).toHaveTextContent(
      'Рендер концовки запущен',
    );
    expect(channels.data.ending.started).toEqual(['example-tech']);
  });

  it('концовка: идёт батч — собрать нельзя; Reel (вручную) — кнопки нет', async () => {
    channels.data.ending.refuse = 'batch_open';
    const { user, d } = await open('example-tech');
    const ending = await within(d).findByTestId('ending');
    await user.click(within(ending).getByTestId('ending-render-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('plan-head')).toHaveTextContent('собрать нельзя');
    expect(within(dialog).getByTestId('ending-plan-batches')).toBeInTheDocument();
    expect(within(dialog).queryByTestId('ending-render-yes')).toBeNull();
  });

  it('Reel: концовка собрана вручную — собирать нечем', async () => {
    const { d } = await open('example-film');
    const ending = await within(d).findByTestId('ending');
    expect(within(ending).queryByTestId('ending-render-open')).toBeNull();
  });
});
