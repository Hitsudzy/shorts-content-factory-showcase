// «Публикация» (б), CC-0068: записи без сети — пауза (поставить, заменить, снять), карточка
// (разместить в слот, собрать из черновика), ротация (назначить, отклонить, отказаться). Каждая —
// план фабрики → «да» с отсчётом токена; отказы — словами; «только смотреть» — кнопки погашены.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, publish } from '@/mocks/handlers';
import {
  DEFICIT,
  NOT_READY,
  READY,
  REEL,
  REEL_BATCH,
  SCIENCE,
  SCRIPT_HELD,
  SCRIPT_REJECTED,
  SCRIPT_STANDING,
  WAITING,
} from '@/mocks/publish';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const REASON = 'проверка — смотрим вкладку «Авторские права»';

async function open(channel = REEL) {
  const user = userEvent.setup();
  renderApp(`/publishing?channel=${channel}`);
  const status = await screen.findByTestId('channel-status');
  return { user, status };
}

/** Окно подтверждения: дождаться плана, вернуть окно и кнопку «да». */
async function dialogOf(id: string) {
  const dialog = await screen.findByRole('alertdialog');
  const yes = within(dialog).getByTestId(`${id}-confirm`);
  return { dialog, yes };
}

describe('CC-0068: пауза канала', () => {
  it('поставить: причина и срок → план → «да» с отсчётом → пауза стоит', async () => {
    const { user, status } = await open();
    const pause = within(status).getByTestId('state-pause');
    await within(pause).findByTestId('pause-writes');
    await user.click(within(pause).getByTestId('pause-set-toggle'));
    const go = within(pause).getByTestId('pause-set-open');
    expect(go).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(pause).getByTestId('pause-reason'), REASON);
    await user.type(within(pause).getByTestId('pause-until'), '2026-10-20');
    await user.click(within(pause).getByTestId('pause-set-open'));
    const { dialog, yes } = await dialogOf('pause-set');
    expect(await within(dialog).findByTestId('pause-plan-reason')).toHaveTextContent(
      `${REASON} (из центра)`,
    );
    expect(within(dialog).getByTestId('pause-plan-until')).toHaveTextContent('до 20.10');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(yes).toHaveTextContent(/Поставить · [12]:\d\d/);
    expect(publish.writes.state.written).toEqual([]);
    await user.click(yes);
    expect(await within(pause).findByTestId('pause-done')).toHaveTextContent('Пауза поставлена');
    expect(publish.writes.state.written.map((w) => w.action)).toEqual(['pause_set']);
    expect(publish.writes.state.calls.at(-1)!.body).toEqual({ confirm: 'pub-pause_set-1' });
    await waitFor(() => expect(within(pause).getByText('на паузе')).toBeInTheDocument());
    // теперь пауза стоит: снять можно, а «поставить» стало «заменить»
    expect(within(pause).getByTestId('pause-clear-toggle')).toBeInTheDocument();
    expect(within(pause).getByTestId('pause-set-toggle')).toHaveTextContent('Заменить паузу');
  });

  it('снять с заметкой; занято — токен цел, «да» ещё раз', async () => {
    const { user, status } = await open(SCIENCE);
    const pause = within(status).getByTestId('state-pause');
    await user.click(await within(pause).findByTestId('pause-clear-toggle'));
    await user.type(within(pause).getByTestId('pause-note'), 'канал запущен');
    await user.click(within(pause).getByTestId('pause-clear-open'));
    const { dialog, yes } = await dialogOf('pause-clear');
    expect(await within(dialog).findByTestId('pause-plan-note')).toHaveTextContent(
      'канал запущен (из центра)',
    );
    await waitFor(() => expect(yes).toBeEnabled());
    publish.writes.state.next = 'busy';
    await user.click(yes);
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveAttribute('data-code', 'busy');
    expect(within(err).getByTestId('write-refusal-title')).toHaveTextContent(
      'Идёт другая запись публикации',
    );
    expect(within(dialog).getByTestId('busy-note')).toBeInTheDocument();
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(pause).findByTestId('pause-done')).toHaveTextContent('Пауза снята');
  });

  it('мир сменился между планом и «да» — план заново сам, причина словами', async () => {
    const { user, status } = await open();
    const pause = within(status).getByTestId('state-pause');
    await user.click(await within(pause).findByTestId('pause-set-toggle'));
    await user.type(within(pause).getByTestId('pause-reason'), REASON);
    await user.click(within(pause).getByTestId('pause-set-open'));
    const { dialog, yes } = await dialogOf('pause-set');
    await waitFor(() => expect(yes).toBeEnabled());
    // мир сменился между планом и «да»: фабрика скажет check_changed — план берётся заново
    publish.writes.state.next = 'check_changed';
    await user.click(yes);
    const again = await within(dialog).findByTestId('replanned');
    expect(again).toHaveAttribute('data-code', 'check_changed');
    expect(again).toHaveTextContent('С момента плана что-то изменилось');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(publish.writes.state.calls.filter((c) => c.kind === 'plan')).toHaveLength(2);
  });

  it('«только смотреть»: кнопка погашена, плана не спрашиваем', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const { user, status } = await open();
    const pause = within(status).getByTestId('state-pause');
    await user.click(await within(pause).findByTestId('pause-set-toggle'));
    await user.type(within(pause).getByTestId('pause-reason'), REASON);
    const go = within(pause).getByTestId('pause-set-open');
    await waitFor(() => expect(go).toHaveAttribute('data-writes', 'off'));
    await user.click(go);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(publish.writes.state.calls).toEqual([]);
  });
});

describe('CC-0068: карточка ролика', () => {
  it('из очереди в слот: слот, сдвиги и предупреждения в плане; после «да» ролик в ленте', async () => {
    publish.writes.state.placeMoves = true;
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const card = await screen.findByTestId('card-writes');
    await user.click(await within(card).findByTestId('card-pick-waiting'));
    expect(within(card).getByTestId('card-slug')).toHaveValue(WAITING);
    await user.click(within(card).getByTestId('card-place-toggle'));
    expect(within(card).getByTestId('card-place-open')).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(card).getByTestId('card-batch'), REEL_BATCH);
    await user.click(within(card).getByTestId('card-place-open'));
    const { dialog, yes } = await dialogOf('card-place');
    expect(await within(dialog).findByTestId('place-where')).toHaveTextContent(
      /Ролик встанет в слот \d\d\.10/,
    );
    expect(within(dialog).getAllByTestId('place-move')).toHaveLength(1);
    expect(within(dialog).getByTestId('place-warnings')).toHaveTextContent('WINDOW');
    expect(publish.writes.state.calls[0]!.body).toEqual({
      batch_id: '2026-10-09T0200Z',
      dir: 'example-film',
      slug: WAITING,
      day: null,
      replace: false,
    });
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(card).findByTestId('place-done')).toHaveTextContent('Карточка размещена');
    const feed = screen.getByTestId('slot-feed');
    await waitFor(() =>
      expect(
        within(feed)
          .getAllByTestId('slot')
          .some((x) => x.dataset.slug === WAITING),
      ).toBe(true),
    );
  });

  it('неготовая карточка: план «разместить нельзя» с причиной фабрики, «да» погашено', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const card = await screen.findByTestId('card-writes');
    await user.type(within(card).getByTestId('card-batch'), REEL_BATCH);
    await user.type(within(card).getByTestId('card-slug'), NOT_READY);
    await user.click(within(card).getByTestId('card-place-toggle'));
    await user.click(within(card).getByTestId('card-place-open'));
    const { dialog, yes } = await dialogOf('card-place');
    expect(await within(dialog).findByTestId('plan-head')).toHaveTextContent('разместить нельзя');
    expect(within(dialog).getByTestId('plan-why')).toHaveTextContent('Карточка не готова');
    expect(yes).toBeDisabled();
  });

  it('собрать из черновика: «утверждения не проверены»; модель — понятный отказ без запроса', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const card = await screen.findByTestId('card-writes');
    await screen.findByText(/Vanguards: Doomsday Moved Again/, { selector: 'h2' });
    await user.click(await within(card).findByTestId('card-pick-selected'));
    expect(within(card).getByTestId('card-slug')).toHaveValue(READY);
    await user.click(within(card).getByTestId('card-build-toggle'));
    await user.click(within(card).getByTestId('card-build-model'));
    expect(within(card).getByTestId('model-refused')).toHaveTextContent(
      'Черновик моделью из центра не пишется',
    );
    const go = within(card).getByTestId('card-build-open');
    expect(go).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(card).getByTestId('draft-title'), 'Doomsday moved again');
    await user.type(within(card).getByTestId('draft-about'), 'Zenith moved it to December.');
    await user.type(within(card).getByTestId('draft-hashtags'), '#Vanguards #Zenith');
    await user.type(within(card).getByTestId('draft-tags'), 'Zenith, MCU');
    await user.click(within(card).getByTestId('card-build-open'));
    const { dialog, yes } = await dialogOf('card-build');
    expect(await within(dialog).findByTestId('build-claims')).toHaveTextContent(
      'утверждения не проверены',
    );
    expect(publish.writes.state.calls[0]!.body).toMatchObject({
      model: false,
      draft: { hashtags: ['Vanguards', 'Zenith'], tags: ['Zenith', 'MCU'] },
    });
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(card).findByTestId('build-done')).toHaveTextContent(
      'утверждения не проверены',
    );
    expect(publish.writes.state.calls.some((c) => (c.body as { model?: boolean }).model)).toBe(
      false,
    );
  });
});

describe('CC-0068: ротация', () => {
  async function rotation() {
    const { user, status } = await open();
    const rot = within(status).getByTestId('state-rotation');
    await within(rot).findByTestId('rotation-writes');
    return { user, rot };
  }

  it('отклонить: вердикт стража в плане — «примут» с заменой; после «да» — итог', async () => {
    const { user, rot } = await rotation();
    await user.click(within(rot).getByTestId('rot-reject-toggle'));
    await user.type(within(rot).getByTestId('reject-script'), SCRIPT_STANDING);
    await user.type(within(rot).getByTestId('reject-reason'), 'коротко');
    expect(within(rot).getByTestId('rot-reject-open')).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(rot).getByTestId('reject-reason'), ': у факта нет второй стороны');
    await user.click(within(rot).getByTestId('rot-reject-open'));
    const { dialog, yes } = await dialogOf('rot-reject');
    const ruling = await within(dialog).findByTestId('ruling');
    expect(ruling).toHaveAttribute('data-verdict', 'upheld');
    expect(ruling).toHaveTextContent('отказ примут');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(rot).findByTestId('rotation-done')).toHaveTextContent(
      'Отказ принят — пара заменена',
    );
  });

  it('второй отказ того же сценария — «отклонят» по правилу словами', async () => {
    const { user, rot } = await rotation();
    await user.click(within(rot).getByTestId('rot-reject-toggle'));
    await user.type(within(rot).getByTestId('reject-script'), SCRIPT_REJECTED);
    await user.type(within(rot).getByTestId('reject-reason'), 'пара не подходит этому факту никак');
    await user.click(within(rot).getByTestId('rot-reject-open'));
    const { dialog } = await dialogOf('rot-reject');
    const ruling = await within(dialog).findByTestId('ruling');
    expect(ruling).toHaveAttribute('data-verdict', 'denied');
    expect(within(ruling).getByTestId('ruling-text')).toHaveTextContent('один отказ на сценарий');
  });

  it('назначить: тема ждёт материала — «назначить нельзя»; с флажком — можно', async () => {
    const { user, rot } = await rotation();
    await user.click(within(rot).getByTestId('rot-assign-toggle'));
    await user.type(within(rot).getByTestId('assign-batch'), '2026-10-10T0200Z');
    await user.type(within(rot).getByTestId('assign-ids'), SCRIPT_HELD);
    await user.click(within(rot).getByTestId('rot-assign-open'));
    let d = await dialogOf('rot-assign');
    expect(await within(d.dialog).findByTestId('plan-head')).toHaveTextContent('назначить нельзя');
    expect(within(d.dialog).getByTestId('assign-script')).toHaveAttribute('data-state', 'held');
    await user.click(within(d.dialog).getByRole('button', { name: 'Отмена' }));
    await user.click(within(rot).getByTestId('assign-despite'));
    await user.type(within(rot).getByTestId('assign-ids'), ' lf-new-script1');
    await user.click(within(rot).getByTestId('rot-assign-open'));
    d = await dialogOf('rot-assign');
    await waitFor(() => expect(d.yes).toBeEnabled());
    expect(
      within(d.dialog)
        .getAllByTestId('assign-script')
        .map((x) => x.dataset.state),
    ).toEqual(['fresh', 'fresh']);
    await user.click(d.yes);
    expect(await within(rot).findByTestId('rotation-done')).toHaveTextContent(
      'Новых назначений: 2',
    );
  });

  it('отказаться: дефицит только под pipeline/; журнал сломан — rotation_broken словами', async () => {
    const { user, rot } = await rotation();
    await user.click(within(rot).getByTestId('rot-refuse-toggle'));
    await user.type(within(rot).getByTestId('refuse-script'), SCRIPT_STANDING);
    await user.type(within(rot).getByTestId('refuse-reason'), 'в пуле нет шотов второго трейлера');
    await user.type(within(rot).getByTestId('refuse-deficit'), 'rotation/x.json');
    expect(within(rot).getByTestId('refuse-deficit')).toHaveAttribute('aria-invalid', 'true');
    expect(within(rot).getByTestId('rot-refuse-open')).toHaveAttribute('aria-disabled', 'true');
    await user.clear(within(rot).getByTestId('refuse-deficit'));
    await user.type(within(rot).getByTestId('refuse-deficit'), DEFICIT);
    publish.writes.state.rotationBroken = true;
    await user.click(within(rot).getByTestId('rot-refuse-open'));
    const { dialog, yes } = await dialogOf('rot-refuse');
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'rotation_broken');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent(
      'Ротация канала не читается',
    );
    expect(yes).toBeDisabled();
    publish.writes.state.rotationBroken = false;
    await user.click(within(dialog).getByTestId('replan'));
    expect(await within(dialog).findByTestId('refuse-what')).toHaveTextContent(
      'закроется без замены',
    );
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(rot).findByTestId('rotation-done')).toHaveTextContent(
      'тема ждёт материала',
    );
    expect(publish.writes.state.calls.find((c) => c.action === 'rotation_refuse')!.body).toEqual({
      script_id: SCRIPT_STANDING,
      reason: 'в пуле нет шотов второго трейлера',
      deficit: DEFICIT,
      batch_id: null,
    });
  });
});
