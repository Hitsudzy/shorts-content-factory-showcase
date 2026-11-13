// «Публикация» (г), CC-0071: подпись холда content-sensitivity из центра. Кнопка — только у
// строки с `signable: true` и рядом с плеером ролика; у прочих — строка фабрики, почему нет.
// Заметка обязательна; план — что отметил compliance-checker, что значит подпись, заметка и
// «вы, из центра»; «да» с отсчётом; после — тост, холд уходит из открытых. Отказы — словами.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, publish } from '@/mocks/handlers';
import { HOLD_SENSITIVE, REEL } from '@/mocks/publish';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const NOTE = 'посмотрел: пострадавших крупно нет, кадры из новостей';

async function open() {
  const user = userEvent.setup();
  renderApp(`/publishing?channel=${REEL}`);
  const holds = await screen.findByTestId('holds');
  await within(holds).findByText('Открытых: 2');
  const [sensitive, rights] = within(holds).getAllByTestId('hold') as [HTMLElement, HTMLElement];
  return { user, holds, sensitive, rights };
}

/** Раскрыть форму, вписать заметку, открыть окно плана. */
async function planned(user: ReturnType<typeof userEvent.setup>, row: HTMLElement, note = NOTE) {
  await user.click(within(row).getByTestId('hold-sign-toggle'));
  await user.type(within(row).getByTestId('hold-sign-note'), note);
  await user.click(within(row).getByTestId('hold-sign-open'));
  const dialog = await screen.findByRole('alertdialog');
  return { dialog, yes: within(dialog).getByTestId('hold-sign-confirm') };
}

const posts = () => publish.writes.state.calls;

describe('CC-0071: подпись холда', () => {
  it('кнопка — только у холда, который центр подписывает, и рядом с плеером', async () => {
    const { holds, sensitive, rights } = await open();
    expect(sensitive).toHaveAttribute('data-signable', '1');
    expect(within(sensitive).getByTestId('hold-sign-toggle')).toHaveTextContent(
      'Посмотрел, снимаю холд',
    );
    expect(await within(sensitive).findByTestId('hold-video')).toHaveAttribute(
      'data-slug',
      'delver',
    );
    expect(within(sensitive).getByTestId('player-video')).toHaveAttribute(
      'src',
      expect.stringContaining('/videos/delver/mp4'),
    );
    // Холд прав — строка фабрики словами, без кнопки и плеера.
    expect(within(rights).queryByTestId('hold-sign-toggle')).not.toBeInTheDocument();
    expect(within(rights).queryByTestId('player')).not.toBeInTheDocument();
    expect(within(rights).getByTestId('hold-sign-refusal')).toHaveTextContent(
      'центр его не подписывает',
    );
    // Плашки «только просмотр» больше нет.
    expect(within(holds).queryByText('только просмотр')).not.toBeInTheDocument();
    expect(posts()).toEqual([]);
  });

  it('заметка обязательна: без неё план не спрашиваем', async () => {
    const { user, sensitive } = await open();
    await user.click(within(sensitive).getByTestId('hold-sign-toggle'));
    const go = within(sensitive).getByTestId('hold-sign-open');
    expect(go).toHaveAttribute('aria-disabled', 'true');
    await user.type(within(sensitive).getByTestId('hold-sign-note'), '   ');
    expect(go).toHaveAttribute('aria-disabled', 'true');
    await user.click(go);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(posts()).toEqual([]);
  });

  it('план → «да» с отсчётом → тост, холд уходит из открытых', async () => {
    const { user, holds, sensitive, rights } = await open();
    // CC-0170: у строки холда — сцены флага; у холда без поля — ничего.
    expect(within(sensitive).getByTestId('hold-scenes')).toHaveTextContent(
      'флаг чувствительности: сцены s2, s3',
    );
    expect(within(rights).queryByTestId('hold-scenes')).not.toBeInTheDocument();
    const { dialog, yes } = await planned(user, sensitive);
    const flagged = await within(dialog).findByTestId('sign-plan-flagged');
    expect(within(flagged).getAllByRole('listitem').length).toBe(4);
    expect(flagged).toHaveTextContent('чувствительность контента: отмечено');
    // CC-0170: сцены флага — отдельной строкой плана, без строки фабрики в списке.
    expect(flagged).not.toHaveTextContent('Сцены флага');
    expect(within(dialog).getByTestId('sign-plan-scenes')).toHaveTextContent('сцены s2, s3');
    // CC-0131: вердикт словами — без имени агента и английского кода.
    expect(flagged).toHaveTextContent('вердикт проверки на риски: холд');
    expect(
      within(flagged)
        .getAllByRole('listitem')
        .map((li) => li.textContent)
        .join(' '),
    ).not.toMatch(/compliance-checker|: hold/);
    expect(within(dialog).getByTestId('sign-plan-meaning')).toHaveTextContent(
      'вы посмотрели ролик',
    );
    expect(within(dialog).getByTestId('sign-plan-note')).toHaveTextContent(NOTE);
    expect(within(dialog).getByTestId('sign-plan-signature')).toHaveTextContent('вы, из центра');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(yes).toHaveTextContent(/Подписать · [12]:\d\d/);
    expect(posts().map((c) => c.kind)).toEqual(['plan']);
    expect(posts()[0]!.body).toMatchObject({ note: NOTE, ...HOLD_SENSITIVE });
    expect(publish.writes.state.written).toEqual([]);
    await user.click(yes);
    expect(await screen.findByTestId('toast')).toHaveTextContent('Холд снят');
    expect(publish.writes.state.written.map((w) => w.action)).toEqual(['hold_sign']);
    expect(posts().at(-1)!.body).toEqual({ confirm: 'pub-hold_sign-1' });
    await within(holds).findByText('Открытых: 1');
    expect(within(holds).getAllByTestId('hold')).toHaveLength(1);
    expect(within(holds).getByTestId('holds-resolved')).toHaveTextContent('Снятые раньше: 2');
    expect(within(holds).getAllByTestId('hold-signed')[0]).toHaveTextContent(
      `подпись: вы, из центра`,
    );
  });

  it('отказ плана — строкой фабрики как есть', async () => {
    const { user, sensitive } = await open();
    // Холд подписали в терминале, пока страница была открыта.
    publish.state.holds.find((h) => h.topic_id === HOLD_SENSITIVE.topic_id)!.signature = {
      user: 'user',
      via: 'terminal',
    };
    const { dialog, yes } = await planned(user, sensitive);
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'already_signed');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent(
      'Холд уже подписан',
    );
    expect(within(refusal).getByTestId('write-refusal-message')).toHaveTextContent(
      'Холд уже подписан — второй раз подписывать нечего.',
    );
    expect(yes).toBeDisabled();
  });

  it.each([
    ['ledger_unreadable', 'Реестр холдов не читается — пока его не починят'],
    ['no_such_hold', 'Такого холда в реестре нет'],
  ] as const)('отказ %s — словами', async (code, line) => {
    const { user, sensitive } = await open();
    if (code === 'ledger_unreadable') publish.state.holdsProblem = 'not JSON';
    else
      publish.state.holds = publish.state.holds.filter(
        (h) => h.topic_id !== HOLD_SENSITIVE.topic_id,
      );
    const { dialog } = await planned(user, sensitive);
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', code);
    expect(refusal).toHaveTextContent(line);
  });

  it('«да» после перемены — план заново; занято — токен цел', async () => {
    const { user, sensitive } = await open();
    const { dialog, yes } = await planned(user, sensitive);
    await waitFor(() => expect(yes).toBeEnabled());
    publish.writes.state.next = 'check_changed';
    await user.click(yes);
    const again = await within(dialog).findByTestId('replanned');
    expect(again).toHaveAttribute('data-code', 'check_changed');
    expect(again).toHaveTextContent('С момента плана что-то изменилось');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(posts().filter((c) => c.kind === 'plan')).toHaveLength(2);
    publish.writes.state.next = 'busy';
    await user.click(yes);
    expect(await within(dialog).findByTestId('busy-note')).toHaveTextContent('ещё годно');
    expect(publish.writes.state.written).toEqual([]);
  });

  it('план устарел — «запросите заново»', async () => {
    publish.writes.state.life = 0;
    const { user, sensitive } = await open();
    const { dialog } = await planned(user, sensitive);
    expect(await within(dialog).findByTestId('token-expired')).toHaveTextContent(
      'План устарел — запросите заново',
    );
    expect(within(dialog).getByTestId('hold-sign-confirm')).toBeDisabled();
    expect(publish.writes.state.written).toEqual([]);
  });

  it('«только смотреть»: кнопка погашена, плана не спрашиваем', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const { user, sensitive } = await open();
    const go = within(sensitive).getByTestId('hold-sign-toggle');
    await waitFor(() => expect(go).toHaveAttribute('data-writes', 'off'));
    await user.click(go);
    expect(within(sensitive).queryByTestId('hold-sign-form')).not.toBeInTheDocument();
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(posts()).toEqual([]);
  });
});
