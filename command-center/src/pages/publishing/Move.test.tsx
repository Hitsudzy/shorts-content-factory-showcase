// Перенос размещённых роликов в ленте слотов (CC-0166): сдвиг очереди как 23.10 («с 14-го на день
// раньше, 13-й — в копилку») одним планом; без возврата — `day_taken`; «Вернуть в копилку» у
// ролика в Studio — отказ фабрики `in_studio` (лента устарела) или погашено (лента знает);
// перенос ролика из Studio — строка STUDIO на виду; «да» шлёт токен и `base_sha256` и перечитывает
// ленту, копилку и обзор; «только смотреть» — кнопки погашены, ни одного POST.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { publishKeys } from '@/api/publish';
import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, publish } from '@/mocks/handlers';
import { NOT_READY, PLACED, READY, REEL } from '@/mocks/publish';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { addDay, shiftBody, type Placed } from './moveWords';

async function open() {
  const user = userEvent.setup();
  const { queryClient } = renderApp(`/publishing?channel=${REEL}`);
  const feed = await screen.findByTestId('slot-feed');
  await waitFor(() => expect(within(feed).getAllByTestId('slot-moves').length).toBeGreaterThan(0));
  return { user, feed, queryClient };
}

const rowOf = (feed: HTMLElement, slug: string) =>
  within(feed)
    .getAllByTestId('slot')
    .find((r) => r.dataset.slug === slug)!;

const plans = () => publish.move.state.calls.filter((c) => c.kind === 'plan');
/** Сколько раз читали ленту канала (`/queue`) или обзор (`overview` — `GET /api/publish`). */
const reads = (what: '/queue' | 'overview') =>
  publish.state.calls.filter((c) =>
    what === 'overview' ? c === '/api/publish' : c.startsWith(`/api/publish/${REEL}/queue`),
  ).length;
const stashReads = () => publish.stash.state.calls.filter((c) => c.kind === 'get').length;

describe('сдвиг очереди словами', () => {
  const p = (slug: string, day: string): Placed => ({ slug, day, title: slug, inStudio: false });
  it('все с дня N на день раньше, ролик дня N−1 — в копилку; позже — без возврата', () => {
    const placed = [p('a', '2026-10-24'), p('b', '2026-10-25'), p('c', '2026-10-26')];
    expect(shiftBody(placed, '2026-10-25', -1, true)).toEqual({
      moves: [
        { slug: 'b', day: '2026-10-24' },
        { slug: 'c', day: '2026-10-25' },
      ],
      unplace: ['a'],
    });
    expect(shiftBody(placed, '2026-10-25', 1, true)).toEqual({
      moves: [
        { slug: 'b', day: '2026-10-26' },
        { slug: 'c', day: '2026-10-27' },
      ],
      unplace: [],
    });
    expect(addDay('2026-10-31', 1)).toBe('2026-11-01');
  });
});

describe('CC-0166: перенос в ленте слотов', () => {
  it('сдвиг как 23.10: с 14.10 на день раньше и 13.10 в копилку — план целиком; без возврата — day_taken', async () => {
    publish.fillReelDays();
    const { user, feed } = await open();
    await user.click(within(feed).getByTestId('move-shift-toggle'));
    const form = within(feed).getByTestId('move-shift-form');
    await user.selectOptions(within(form).getByTestId('move-shift-from'), '2026-10-14');
    expect(within(form).getByTestId('move-shift-earlier')).toBeChecked();
    expect(within(form).getByTestId('move-shift-unplace')).toBeChecked();
    expect(within(form).getByTestId('move-shift-preview')).toHaveTextContent(
      'Сдвинутся на день раньше: 10 роликов, в копилку — 1 ролик',
    );

    // Без возврата 13-го: день занят — фабрика отказывает всем переносам, «да» нет.
    await user.click(within(form).getByTestId('move-shift-unplace'));
    await user.click(within(form).getByTestId('move-shift-open'));
    let dialog = await screen.findByRole('alertdialog');
    let items = await within(dialog).findAllByTestId('move-plan-item');
    expect(items.every((i) => i.dataset.ok === '0')).toBe(true);
    expect(within(items[0]!).getByTestId('move-plan-refusal')).toHaveAttribute(
      'data-code',
      'day_taken',
    );
    expect(within(items[0]!).getByTestId('move-plan-refusal')).toHaveTextContent(
      'В этот день уже стоит другой ролик',
    );
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('перенести нельзя');
    expect(within(dialog).getByTestId('move-shift-confirm')).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: /Отмена|Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());

    await user.click(within(form).getByTestId('move-shift-unplace'));
    await user.click(within(form).getByTestId('move-shift-open'));
    dialog = await screen.findByRole('alertdialog');
    items = await within(dialog).findAllByTestId('move-plan-item');
    expect(items).toHaveLength(11);
    expect(items[0]).toHaveAttribute('data-op', 'unplace');
    expect(items[0]).toHaveAttribute('data-slug', READY);
    expect(within(items[0]!).getByTestId('move-plan-where')).toHaveTextContent(
      'вт 13.10 → в копилку',
    );
    expect(items[1]).toHaveAttribute('data-slug', 'filler-1');
    expect(within(items[1]!).getByTestId('move-plan-where')).toHaveTextContent(
      'ср 14.10 → вт 13.10, 01:00',
    );
    expect(items.every((i) => i.dataset.ok === '1')).toBe(true);
    expect(within(dialog).queryByTestId('move-studio')).toBeNull();
    expect(within(dialog).getByTestId('move-shift-plan-life')).toBeInTheDocument();
    const yes = within(dialog).getByTestId('move-shift-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(plans().at(-1)!.body).toEqual({
      moves: [
        { slug: 'filler-1', day: '2026-10-13' },
        { slug: NOT_READY, day: '2026-10-14' },
        ...Array.from({ length: 8 }, (_, i) => ({
          slug: `filler-${i + 2}`,
          day: addDay('2026-10-15', i),
        })),
      ],
      unplace: [READY],
    });
    await user.click(yes);
    const done = await within(feed).findByTestId('move-done');
    expect(done).toHaveTextContent('Перенесено: 10 роликов, в копилку: 1 ролик');
    await waitFor(() => expect(rowOf(feed, 'filler-1')).toHaveAttribute('data-day', '2026-10-13'));
    expect(rowOf(feed, NOT_READY)).toHaveAttribute('data-day', '2026-10-14');
    expect(rowOf(feed, READY)).toBeUndefined();
  });

  it('«Вернуть в копилку» у ролика в Studio: лента знает — погашено; лента устарела — отказ in_studio', async () => {
    const { user, feed } = await open();
    expect(within(rowOf(feed, PLACED)).getByTestId('move-unplace-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    // Ролик успели загрузить, а лента ещё не перечитана: решает отказ фабрики.
    publish.channels[REEL]!.occupants.find((o) => o.slug === READY)!.sources.push(
      'uploads.json:Rd7yT3stX9q',
    );
    await user.click(within(rowOf(feed, READY)).getByTestId('move-unplace-open'));
    const dialog = await screen.findByRole('alertdialog');
    const item = await within(dialog).findByTestId('move-plan-item');
    expect(item).toHaveAttribute('data-ok', '0');
    const refusal = within(item).getByTestId('move-plan-refusal');
    expect(refusal).toHaveAttribute('data-code', 'in_studio');
    expect(refusal).toHaveTextContent('Ролик уже в Studio — вернуть его в копилку нельзя');
    // Код — только под «Подробнее».
    expect(within(item).queryByText(/in_studio/)).toBeNull();
    expect(within(dialog).getByTestId('move-unplace-confirm')).toBeDisabled();
  });

  it('перенос ролика из Studio: строка STUDIO на виду; «да» шлёт токен и base_sha256, перечитывает ленту, копилку и обзор', async () => {
    const { user, feed, queryClient } = await open();
    const invalidate = vi.spyOn(queryClient, 'invalidateQueries');
    const row = rowOf(feed, PLACED);
    await user.click(within(row).getByTestId('move-open'));
    const day = within(row).getByTestId('move-day');
    // По умолчанию — ближайший свободный день.
    expect(day).toHaveValue('2026-10-14');
    expect(within(row).getByTestId('move-row-studio')).toHaveTextContent(
      'дату там поставить вручную',
    );
    await user.click(within(row).getByTestId('move-one-open'));
    const dialog = await screen.findByRole('alertdialog');
    const studio = await within(dialog).findByTestId('move-studio');
    expect(within(studio).getByTestId('move-studio-title')).toHaveTextContent(
      'Дату в Studio поставить вручную',
    );
    expect(within(studio).getByTestId('move-studio-item')).toHaveTextContent(
      'поставить ср 14.10, 01:00',
    );
    expect(within(studio).getByTestId('move-studio-line')).toHaveTextContent(/^STUDIO delver/);
    const yes = within(dialog).getByTestId('move-one-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    const before = { queue: reads('/queue'), overview: reads('overview'), stash: stashReads() };
    const planned = plans().at(-1)!;
    expect(planned.body).toEqual({ moves: [{ slug: PLACED, day: '2026-10-14' }], unplace: [] });
    await user.click(yes);
    const done = await within(feed).findByTestId('move-done');
    expect(done).toHaveTextContent('Перенесено: 1 ролик');
    expect(within(done).getByTestId('move-studio-title')).toHaveTextContent(
      'Теперь поставьте дату в Studio вручную',
    );
    const sent = publish.move.state.calls.find((c) => c.kind === 'confirm')!.body as {
      confirm: string;
      base_sha256: string;
    };
    expect(sent.confirm).toMatch(/^publish-move-\d+$/);
    expect(sent.base_sha256).toMatch(/^sha256:example-film-/);
    expect(Object.keys(sent).sort()).toEqual(['base_sha256', 'confirm']);
    // Вся публикация, кроме карточек дней, — перечитать; карточки — только пометить устаревшими.
    expect(invalidate).toHaveBeenCalledWith(
      expect.objectContaining({ queryKey: publishKeys.all, predicate: expect.any(Function) }),
    );
    expect(invalidate).toHaveBeenCalledWith({
      queryKey: [...publishKeys.all, 'note'],
      refetchType: 'none',
    });
    // Перечитаны лента, копилка и обзор публикации.
    await waitFor(() => {
      expect(reads('/queue')).toBeGreaterThan(before.queue);
      expect(reads('overview')).toBeGreaterThan(before.overview);
      expect(stashReads()).toBeGreaterThan(before.stash);
    });
    await waitFor(() => expect(rowOf(feed, PLACED)).toHaveAttribute('data-day', '2026-10-14'));
  });

  it('«только смотреть»: «Сдвинуть», «Перенести» и «Вернуть» погашены, ни одного POST', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const { user, feed } = await open();
    const shift = within(feed).getByTestId('move-shift-toggle');
    await waitFor(() => expect(shift).toHaveAttribute('data-writes', 'off'));
    await user.click(shift);
    expect(within(feed).queryByTestId('move-shift-form')).toBeNull();
    const row = rowOf(feed, READY);
    expect(within(row).getByTestId('move-open')).toHaveAttribute('data-writes', 'off');
    await user.click(within(row).getByTestId('move-open'));
    expect(within(row).queryByTestId('move-form')).toBeNull();
    const back = within(row).getByTestId('move-unplace-open');
    expect(back).toHaveAttribute('data-writes', 'off');
    await user.click(back);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(publish.move.state.calls).toEqual([]);
  });
});
