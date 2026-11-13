// CC-0168 (API CC-0167): «День» в «Разместить или собрать» — папка, где ролик лежит сейчас, а не
// слот; у ролика из копилки («ждёт слота») поля нет и день в план не идёт; запросы строки ленты
// (заметка, план загрузки, план записи Studio) несут её день; 404 `unknown_note` с просьбой
// назвать день — строкой фабрики, без падения.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { publish } from '@/mocks/handlers';
import { READY, REEL, REEL_BATCH, WAITING } from '@/mocks/publish';
import { renderApp } from '@/test/renderApp';

const READY_DAY = '2026-10-13';

async function openCard(url = `/publishing?channel=${REEL}`) {
  const user = userEvent.setup();
  renderApp(url);
  const card = await screen.findByTestId('card-writes');
  await user.click(within(card).getByTestId('card-place-toggle'));
  return { user, card };
}

const planBodies = () =>
  publish.writes.state.calls.filter((c) => c.kind === 'plan').map((c) => c.body);

describe('CC-0168: поле «День» карточки', () => {
  it('подпись — папка, где ролик лежит сейчас (не слот); подсказка — про «Разложить по слотам»', async () => {
    const { card } = await openCard();
    expect(
      within(card).getByText('День: папка, где ролик лежит сейчас (не слот)'),
    ).toBeInTheDocument();
    const hint = within(card).getByTestId('card-day-hint');
    expect(hint).toHaveTextContent('Слот выбирается в «Разложить по слотам»');
    expect(hint).toHaveTextContent('Пусто — фабрика сама найдёт ролик этого батча');
  });

  it('ролик из копилки: поле скрыто, введённый день стёрт, в плане day: null', async () => {
    const { user, card } = await openCard();
    await user.type(within(card).getByTestId('card-day'), '2026-10-26');
    await user.click(await within(card).findByTestId('card-pick-waiting'));
    expect(within(card).queryByTestId('card-day')).not.toBeInTheDocument();
    expect(within(card).getByTestId('card-day-queued')).toHaveTextContent('день не нужен');
    await user.type(within(card).getByTestId('card-batch'), REEL_BATCH);
    await user.click(within(card).getByTestId('card-place-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('place-where')).toHaveTextContent(
      'Ролик встанет в слот',
    );
    expect(planBodies()).toEqual([
      {
        batch_id: '2026-10-09T0200Z',
        dir: 'example-film',
        slug: WAITING,
        day: null,
        replace: false,
      },
    ]);
  });

  it('имя ролика правят руками — поле «День» снова на месте и пустое', async () => {
    const { user, card } = await openCard();
    await user.click(await within(card).findByTestId('card-pick-waiting'));
    expect(within(card).queryByTestId('card-day')).not.toBeInTheDocument();
    await user.type(within(card).getByTestId('card-slug'), 'x');
    expect(within(card).getByTestId('card-day')).toHaveValue('');
  });

  it('ролик строки ленты: в поле — день строки, он же уходит в план', async () => {
    const { user, card } = await openCard(`/publishing?channel=${REEL}&slot=${READY_DAY}/${READY}`);
    await screen.findByText(/Vanguards: Doomsday Moved Again/, { selector: 'h2' });
    await user.click(await within(card).findByTestId('card-pick-selected'));
    expect(within(card).getByTestId('card-day')).toHaveValue(READY_DAY);
    await user.click(within(card).getByTestId('card-replace'));
    await user.click(within(card).getByTestId('card-place-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('plan-head')).toHaveTextContent('можно разместить');
    expect(planBodies()[0]).toMatchObject({ slug: READY, day: READY_DAY });
  });

  it('день не той папки — отказ фабрики объясняет: день — где ролик лежит, не слот', async () => {
    const { user, card } = await openCard();
    await user.type(within(card).getByTestId('card-batch'), REEL_BATCH);
    await user.type(within(card).getByTestId('card-slug'), READY);
    await user.type(within(card).getByTestId('card-day'), '2026-10-26');
    await user.click(within(card).getByTestId('card-place-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('plan-why')).toHaveTextContent(
      'папка, где ролик лежит сейчас, не слот',
    );
  });
});

describe('CC-0168: запросы строки ленты несут её день', () => {
  it('заметка — ?day=, план загрузки — day строки', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}&slot=${READY_DAY}/${READY}`);
    const card = await screen.findByTestId('upload-writes');
    await user.click(await within(card).findByTestId('upload-open'));
    await screen.findByRole('alertdialog');
    await waitFor(() => expect(planBodies()).toHaveLength(1));
    expect(publish.state.calls).toContain(`/api/publish/${REEL}/notes/${READY}?day=${READY_DAY}`);
    expect(planBodies()[0]).toEqual({ slug: READY, day: READY_DAY });
  });

  it('у имени два места, день не назван — строка фабрики с просьбой о дне, без падения', async () => {
    const twin = publish.state.notes.get(`${READY_DAY}/${READY}`)!;
    publish.state.notes.set(`_queue/${READY}`, { ...twin, day: '_queue' });
    renderApp(`/publishing?channel=${REEL}&slot=/${READY}`);
    const studio = await screen.findByTestId('studio-card');
    const alert = await within(studio).findByRole('alert');
    expect(alert).toHaveTextContent('Карточку ролика не прочитать');
    expect(alert).toHaveTextContent('укажите день: папку, где лежит заметка');
    expect(alert).toHaveTextContent(`(${READY_DAY}, _queue)`);
    expect(screen.getByTestId('upload-no-note')).toBeInTheDocument();
  });
});
