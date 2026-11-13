// Подпись цены и решение по правилу воротец (CC-0115 шаг 3): план с base_sha256 чтения, «да»
// набирает пользователь (пусто, без вставки, чистится на новом плане), сменившийся леджер —
// «Цены изменились, откройте заново», отказы фабрики словами, устаревший токен — новый план.
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { gates } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const TAIL = 'content_researcher.tail_after_last_anchor';
const STOPCOCK = 'orchestrator.stopcock';

function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

async function rule(name: string) {
  const user = userEvent.setup();
  renderApp('/stats?channel=example-film');
  const card = await screen.findByTestId('gate-prices');
  await within(card).findAllByTestId('gate-rule');
  const row = card.querySelector<HTMLElement>(`[data-rule="${name}"]`)!;
  return { user, row, card };
}

async function signPlan(name = TAIL, note = 'решили в чате — пусть отказывает') {
  const r = await rule(name);
  await r.user.click(within(r.row).getByTestId('gate-sign-toggle'));
  await r.user.type(within(r.row).getByTestId('gate-sign-note'), note);
  await r.user.click(within(r.row).getByTestId('gate-sign-open'));
  const dialog = await screen.findByRole('alertdialog');
  await within(dialog).findByTestId('plan-head');
  return { ...r, dialog };
}

describe('воротца: подпись цены и решение (CC-0115 шаг 3)', () => {
  it('кнопки — только где `actions` разрешает', async () => {
    const { card } = await rule(TAIL);
    const row = (n: string) => card.querySelector<HTMLElement>(`[data-rule="${n}"]`)!;
    expect(within(row(TAIL)).getByTestId('gate-sign-toggle')).toBeInTheDocument();
    expect(within(row(TAIL)).getByTestId('gate-decide-toggle')).toBeInTheDocument();
    // Подписано — подписи нет, решение есть.
    expect(within(row('frame_judge.foreign_core')).queryByTestId('gate-sign-toggle')).toBeNull();
    expect(
      within(row('frame_judge.foreign_core')).getByTestId('gate-decide-toggle'),
    ).toBeInTheDocument();
    // Не измерена — подписывать нечего.
    expect(
      within(row('footage_indexer.no_second_source')).queryByTestId('gate-sign-toggle'),
    ).toBeNull();
  });

  it('подпись: цена не ниже измеренной, без заметки план не спрашиваем', async () => {
    const { user, row } = await rule(TAIL);
    await user.click(within(row).getByTestId('gate-sign-toggle'));
    const price = within(row).getByTestId('gate-sign-price');
    expect(price).toHaveValue('3');
    expect(row).toHaveTextContent('Измерено: 3 готовых ролика — меньше подписать нельзя');
    // CC-0131: пояснение к заметке — строкой под полем, как у цены, не тултипом с пунктиром.
    expect(row).toHaveTextContent('заметка останется в журнале цен');
    expect(within(row).getByTestId('gate-sign-open')).toHaveAttribute('aria-disabled', 'true');
    await user.clear(price);
    await user.type(price, '2');
    await user.type(within(row).getByTestId('gate-sign-note'), 'заметка');
    await user.click(within(row).getByTestId('gate-sign-open'));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(gates.state.plans).toEqual([]);
  });

  it('подпись: план с base_sha256 чтения, «да» набирает пользователь, итог, карточка перечитана', async () => {
    const { user, dialog, row } = await signPlan();
    expect(gates.state.plans.at(-1)).toEqual({
      kind: 'sign',
      rule: TAIL,
      body: { price: 3, note: 'решили в чате — пусть отказывает', base_sha256: expect.any(String) },
    });
    const sent = gates.state.plans.at(-1)!.body as { base_sha256: string };
    expect(sent.base_sha256).toBe(gates.state.written.sha);
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('можно подписать');
    expect(within(dialog).getByTestId('gate-write-what')).toHaveTextContent(
      'ради этого правила можно терять 3 готовых ролика окна',
    );
    expect(plainText(dialog)).not.toContain(TAIL);
    const yesInput = within(dialog).getByTestId('gate-sign-yes');
    expect(yesInput).toHaveValue('');
    const confirm = within(dialog).getByTestId('gate-sign-confirm');
    expect(confirm).toBeDisabled();
    // Вставка не принимается.
    fireEvent.paste(yesInput, { clipboardData: { getData: () => 'да' } });
    expect(yesInput).toHaveValue('');
    await user.type(yesInput, 'нет');
    expect(confirm).toBeDisabled();
    await user.clear(yesInput);
    await user.type(yesInput, 'да');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    const done = await within(row).findByTestId('gate-write-done');
    expect(done).toHaveTextContent('Цена подписана');
    expect(gates.state.written.signed[TAIL]).toMatchObject({ price: 3, via: 'center' });
    await waitFor(() => expect(row).toHaveTextContent('Подписано'));
    await waitFor(() => expect(within(row).queryByTestId('gate-sign-toggle')).toBeNull());
  });

  it('«да» пустеет на каждом новом плане: окно открыто заново', async () => {
    const { user, dialog, row } = await signPlan();
    await user.type(within(dialog).getByTestId('gate-sign-yes'), 'да');
    await user.click(within(dialog).getByRole('button', { name: 'Отмена' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    await user.click(within(row).getByTestId('gate-sign-open'));
    const again = await screen.findByRole('alertdialog');
    await waitFor(() => expect(gates.state.plans).toHaveLength(2));
    expect(await within(again).findByTestId('gate-sign-yes')).toHaveValue('');
    expect(within(again).getByTestId('gate-sign-confirm')).toBeDisabled();
  });

  it('леджер сменился после чтения — «Цены изменились, откройте заново», токена нет', async () => {
    const { user, row } = await rule(TAIL);
    gates.changeLedger();
    await user.click(within(row).getByTestId('gate-sign-toggle'));
    await user.type(within(row).getByTestId('gate-sign-note'), 'подписываю');
    await user.click(within(row).getByTestId('gate-sign-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('gate-changed')).toHaveTextContent(
      'Цены изменились, откройте заново',
    );
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('подписать нельзя');
    expect(within(dialog).queryByTestId('gate-sign-yes')).toBeNull();
    expect(within(dialog).getByTestId('gate-sign-confirm')).toBeDisabled();
  });

  it('леджер сменился между планом и «да» — план заново с причиной словами', async () => {
    const { user, dialog } = await signPlan();
    await user.type(within(dialog).getByTestId('gate-sign-yes'), 'да');
    gates.changeLedger();
    await user.click(within(dialog).getByTestId('gate-sign-confirm'));
    const re = await within(dialog).findByTestId('replanned');
    expect(re).toHaveAttribute('data-code', 'check_changed');
    expect(re).toHaveTextContent('Цены изменились, откройте заново');
    expect(await within(dialog).findByTestId('gate-changed')).toBeInTheDocument();
    expect(gates.state.written.signed[TAIL]).toBeUndefined();
  });

  it('отказ плана фабрики — строка фабрики, без «да»', async () => {
    gates.state.refuse = 'batch_open';
    const { dialog } = await signPlan();
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('подписать нельзя');
    expect(within(dialog).getByTestId('plan-why')).toHaveTextContent('Пока идёт батч');
    expect(within(dialog).queryByTestId('gate-sign-yes')).toBeNull();
  });

  it('отказ «да» — словами, ничего не записано', async () => {
    gates.state.actRefuse = 'commit_refused';
    const { user, dialog } = await signPlan();
    await user.type(within(dialog).getByTestId('gate-sign-yes'), 'да');
    await user.click(within(dialog).getByTestId('gate-sign-confirm'));
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveAttribute('data-code', 'commit_refused');
    expect(within(err).getByTestId('write-refusal-title')).toHaveTextContent(
      'История фабрики не приняла запись журнала цен',
    );
    expect(gates.state.written.signed[TAIL]).toBeUndefined();
  });

  it('токен устарел — план заново сам', async () => {
    const { user, dialog } = await signPlan();
    await user.type(within(dialog).getByTestId('gate-sign-yes'), 'да');
    gates.expireTokens();
    await user.click(within(dialog).getByTestId('gate-sign-confirm'));
    expect(await within(dialog).findByTestId('replanned')).toHaveAttribute(
      'data-code',
      'confirm_expired',
    );
    await waitFor(() => expect(gates.state.plans).toHaveLength(2));
    expect(within(dialog).getByTestId('gate-sign-yes')).toHaveValue('');
  });

  it('решение: режим, задача, заметка → план → «да»', async () => {
    const { user, row } = await rule(STOPCOCK);
    await user.click(within(row).getByTestId('gate-decide-toggle'));
    const open = within(row).getByTestId('gate-decide-open');
    expect(open).toHaveAttribute('aria-disabled', 'true');
    await user.click(within(row).getByTestId('gate-decide-warn'));
    await user.type(within(row).getByTestId('gate-decide-task'), 'cf-0330');
    await user.type(within(row).getByTestId('gate-decide-note'), 'пусть предупреждает');
    await user.click(within(row).getByTestId('gate-decide-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('gate-write-what')).toHaveTextContent(
      'Решение: предупреждение',
    );
    expect(gates.state.plans.at(-1)?.body).toMatchObject({
      mode: 'warn',
      task: 'CF-0330',
      note: 'пусть предупреждает',
    });
    await user.type(within(dialog).getByTestId('gate-decide-yes'), 'да');
    await user.click(within(dialog).getByTestId('gate-decide-confirm'));
    expect(await within(row).findByTestId('gate-write-done')).toHaveTextContent('Решение записано');
    expect(gates.state.written.decided[STOPCOCK]).toMatchObject({ mode: 'warn', task: 'CF-0330' });
  });
});
