// Тёзки на экране (CC-0183): строки различает батч плюс имя; метка батча — только у тёзок; запись
// уходит с адресом своего ролика и не трогает второго; ссылка заметки несёт батч; отказ `namesakes`
// читается; файл `<имя>~<батч>` оператор не видит. Без тёзки — запросы как раньше.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { NAMESAKES_TEXT } from '@/api/batchProblem';
import { publish } from '@/mocks/handlers';
import { PLACED, REEL } from '@/mocks/publish';
import {
  STASH_RESERVE,
  TWIN,
  TWIN_NEW,
  TWIN_OF_PLACED,
  TWIN_OLD,
  TWIN_RESERVE,
  TWIN_TITLES,
} from '@/mocks/stash';
import { renderApp } from '@/test/renderApp';

async function open(extra = '') {
  const user = userEvent.setup();
  renderApp(`/publishing?channel=${REEL}${extra}`);
  const stash = await screen.findByTestId('stash');
  await within(stash).findByTestId('stash-list');
  const feed = await screen.findByTestId('slot-feed');
  await waitFor(() => expect(within(feed).getAllByTestId('slot-moves').length).toBeGreaterThan(0));
  return { user, stash, feed };
}

const rowsOf = (root: HTMLElement, id: string, slug: string) =>
  within(root)
    .getAllByTestId(id)
    .filter((r) => r.dataset.slug === slug);
const rowOf = (root: HTMLElement, id: string, slug: string, batch?: string) =>
  rowsOf(root, id, slug).find((r) => !batch || r.dataset.batch === batch)!;

describe('CC-0183: тёзки в копилке', () => {
  it('экран с тёзками не получает ни одного отказа: забытого батча в запросах нет', async () => {
    publish.namesakes();
    const refused: string[] = [];
    const real = globalThis.fetch;
    const spy = vi.spyOn(globalThis, 'fetch').mockImplementation(async (...args) => {
      const r = await real(...args);
      if (r.status >= 400) refused.push(`${r.status} ${r.url}`);
      return r;
    });
    const { user, stash, feed } = await open();
    await user.click(
      within(rowOf(feed, 'feed-withdrawn-row', TWIN_RESERVE, TWIN_OLD)).getByTestId(
        'feed-withdrawn-note',
      ),
    );
    await screen.findByTestId('studio-card');
    await waitFor(() => expect(rowsOf(stash, 'stash-row', TWIN)).toHaveLength(2));
    await new Promise((done) => setTimeout(done, 200));
    spy.mockRestore();
    expect(refused).toEqual([]);
  });

  it('две строки, у каждой свой батч и своё название; у остальных метки нет; `~` не виден', async () => {
    publish.namesakes();
    const { stash } = await open();
    const twins = rowsOf(stash, 'stash-row', TWIN);
    expect(twins.map((r) => r.dataset.batch).sort()).toEqual([TWIN_OLD, TWIN_NEW]);
    const old = rowOf(stash, 'stash-row', TWIN, TWIN_OLD);
    const young = rowOf(stash, 'stash-row', TWIN, TWIN_NEW);
    expect(within(old).getByTestId('stash-namesake')).toHaveTextContent('батч от 24.09');
    expect(within(young).getByTestId('stash-namesake')).toHaveTextContent('батч от 9.10');
    expect(young).toHaveTextContent('The Studio Recut');
    expect(old).toHaveTextContent('The First Cut');
    const single = rowOf(stash, 'stash-row', STASH_RESERVE);
    expect(within(single).queryByTestId('stash-namesake')).toBeNull();
    expect(stash.textContent).not.toMatch(/~/);
  });

  it('батч у тёзки — только метка в заголовке; у остальных — общая подпись; точек-разделителей нет', async () => {
    publish.namesakes();
    const { stash } = await open();
    const twin = rowOf(stash, 'stash-row', TWIN, TWIN_NEW);
    expect(within(twin).queryByTestId('stash-batch')).toBeNull();
    expect(within(twin).getAllByText(/батч от/)).toHaveLength(1);
    const single = rowOf(stash, 'stash-row', STASH_RESERVE);
    expect(within(single).getByTestId('stash-batch')).toHaveTextContent(/батч от/);
    for (const row of [twin, single])
      expect(
        [...row.querySelectorAll('[aria-hidden]')].filter((x) => x.textContent === '·'),
      ).toEqual([]);
  });

  it('отметка одного тёзки не отмечает второго; размещение называет батч', async () => {
    publish.namesakes();
    const { user, stash, feed } = await open();
    const young = rowOf(stash, 'stash-row', TWIN, TWIN_NEW);
    await user.click(within(young).getByTestId('stash-pick'));
    const old = rowOf(stash, 'stash-row', TWIN, TWIN_OLD);
    expect(within(old).getByTestId('stash-pick')).not.toBeChecked();
    await user.click(within(stash).getByTestId('stash-place-open'));
    const dialog = await screen.findByRole('alertdialog');
    const item = await within(dialog).findByTestId('stash-plan-item');
    expect(item.dataset.batch).toBe(TWIN_NEW);
    expect(item).toHaveTextContent('батч от 9.10');
    expect(publish.stash.state.calls.filter((c) => c.kind === 'plan').at(-1)!.body).toMatchObject({
      order: [`${TWIN_NEW}/${TWIN}`],
    });
    await user.click(within(dialog).getByTestId('stash-place-confirm'));
    await waitFor(() => expect(rowsOf(stash, 'stash-row', TWIN)).toHaveLength(1));
    expect(rowOf(stash, 'stash-row', TWIN).dataset.batch).toBe(TWIN_OLD);
    await waitFor(() => expect(rowsOf(feed, 'slot', TWIN)).toHaveLength(1));
  });
});

describe('CC-0183: тёзки в ленте', () => {
  it('«Снято из ленты»: возврат второго не трогает первого', async () => {
    publish.namesakes();
    const { user, feed } = await open();
    const row = rowOf(feed, 'feed-withdrawn-row', TWIN_RESERVE, TWIN_NEW);
    await user.click(within(row).getByTestId('reserve-return-toggle'));
    const form = within(row).getByTestId('reserve-return-form');
    await user.click(within(form).getByTestId('reserve-return-open'));
    const dialog = await screen.findByRole('alertdialog');
    const item = await within(dialog).findByTestId('move-plan-item');
    expect(item.dataset.batch).toBe(TWIN_NEW);
    const planned = publish.move.state.calls.filter((c) => c.kind === 'plan').at(-1)!.body as {
      moves: { slug: string; batch_id?: string }[];
    };
    expect(planned.moves[0]).toMatchObject({ slug: TWIN_RESERVE, batch_id: TWIN_NEW });
    await user.click(within(dialog).getByTestId('reserve-return-confirm'));
    await waitFor(() => expect(rowsOf(feed, 'slot', TWIN_RESERVE)).toHaveLength(1));
    const left = rowsOf(feed, 'feed-withdrawn-row', TWIN_RESERVE);
    expect(left.map((r) => r.dataset.batch)).toEqual([TWIN_OLD]);
  });

  it('снятие ролика ленты с тёзкой в копилке называет батч; тёзка на месте', async () => {
    publish.namesakes();
    const { user, stash, feed } = await open();
    const before = rowOf(stash, 'stash-row', PLACED, TWIN_OF_PLACED);
    expect(within(before).queryByTestId('stash-reserve')).toBeNull();
    await user.click(within(rowOf(feed, 'slot', PLACED)).getByTestId('move-withdraw-open'));
    const dialog = await screen.findByRole('alertdialog');
    await within(dialog).findByTestId('withdraw-studio-first');
    const body = publish.move.state.calls.filter((c) => c.kind === 'plan').at(-1)!.body as {
      withdraw: string[];
    };
    expect(body.withdraw).toHaveLength(1);
    expect(body.withdraw[0]).toMatch(new RegExp(`^[^/]+/${PLACED}$`));
    await user.click(within(dialog).getByTestId('move-withdraw-confirm'));
    await waitFor(() => expect(rowsOf(feed, 'slot', PLACED)).toHaveLength(0));
    await waitFor(() => expect(rowsOf(stash, 'stash-row', PLACED)).toHaveLength(2));
    const twin = rowOf(stash, 'stash-row', PLACED, TWIN_OF_PLACED);
    expect(within(twin).queryByTestId('stash-reserve')).toBeNull();
  });

  it('ссылка заметки несёт батч и открывает своего тёзку', async () => {
    publish.namesakes();
    const { user, feed } = await open();
    const row = rowOf(feed, 'feed-withdrawn-row', TWIN_RESERVE, TWIN_NEW);
    const link = within(row).getByTestId('feed-withdrawn-note');
    expect(link.getAttribute('href')).toContain(`batch=${encodeURIComponent(TWIN_NEW)}`);
    await user.click(link);
    const card = await screen.findByTestId('studio-card');
    await waitFor(() =>
      expect(card).toHaveTextContent(TWIN_TITLES[`${TWIN_NEW}/${TWIN_RESERVE}`]!.split(' #')[0]!),
    );
    expect(card.dataset.batch).toBe(TWIN_NEW);
    expect(card.textContent).not.toMatch(/~/);
    expect(
      publish.state.calls.some(
        (c) =>
          c.includes(`/notes/${TWIN_RESERVE}?`) &&
          c.includes('day=_reserve') &&
          c.includes(`batch_id=${encodeURIComponent(TWIN_NEW)}`),
      ),
    ).toBe(true);
  });

  it('ссылка без батча: слова центра со ссылкой на копилку, строка API под «Подробнее», повтора нет', async () => {
    publish.namesakes();
    await open(`&slot=_queue/${TWIN}`);
    const card = await screen.findByTestId('studio-card');
    const words = await within(card).findByTestId('studio-namesakes');
    expect(words.textContent).toBe(NAMESAKES_TEXT);
    expect(words).not.toHaveTextContent(TWIN_OLD);
    expect(within(words).getByTestId('studio-namesakes-stash')).toHaveAttribute('href', '#stash');
    expect(document.getElementById('stash')).toBe(screen.getByTestId('stash'));
    expect(within(card).queryByRole('button', { name: 'Повторить' })).toBeNull();
    const raw = within(card).getByText(/Назовите батч/);
    expect(raw).toHaveTextContent(TWIN_OLD);
    expect(raw.closest('details')!.open).toBe(false);
  });

  it('другой отказ заметки — как раньше: с «Повторить» и без слов о тёзках', async () => {
    publish.namesakes();
    await open('&slot=_queue/no-such-video');
    const card = await screen.findByTestId('studio-card');
    expect(await within(card).findByRole('button', { name: 'Повторить' })).toBeInTheDocument();
    expect(within(card).queryByTestId('studio-namesakes')).toBeNull();
  });

  it('ссылка с батчем открывает своего, не второго', async () => {
    publish.namesakes();
    await open(`&slot=_queue/${TWIN}&batch=${TWIN_OLD}`);
    const card = await screen.findByTestId('studio-card');
    await waitFor(() => expect(card).toHaveTextContent('The First Cut'));
    expect(card).not.toHaveTextContent('The Studio Recut');
  });
});

describe('CC-0183: без тёзки запросы — как раньше', () => {
  it('снятие идёт по имени, ссылка заметки без батча', async () => {
    publish.feedPolicy();
    const { user, feed } = await open();
    const row = rowOf(feed, 'feed-withdrawn-row', STASH_RESERVE);
    expect(within(row).getByTestId('feed-withdrawn-note').getAttribute('href')).not.toContain(
      'batch=',
    );
    await user.click(within(rowOf(feed, 'slot', PLACED)).getByTestId('move-withdraw-open'));
    const dialog = await screen.findByRole('alertdialog');
    await within(dialog).findByTestId('withdraw-studio-first');
    expect(publish.move.state.calls.filter((c) => c.kind === 'plan').at(-1)!.body).toMatchObject({
      withdraw: [PLACED],
    });
  });
});
