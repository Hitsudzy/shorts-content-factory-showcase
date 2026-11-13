// «Статистика» (б), CC-0077: ввод прочитанного в Studio. Форма → JSON для `studio_read.py parse`;
// план фабрики (что распознала, «было → станет», замечания словами); «да» с отсчётом → итог
// словами и перечитанный блок Studio; отказы словами; «только смотреть» — плана не спрашиваем.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { emptyVideo, readOf, shareOf, warningText, type StudioForm } from '@/api/studioEntry';
import { fixtures, writesModes } from '@/mocks/fixtures';
import { analytics, mockGet } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const NOW = new Date('2026-10-10T07:00:00Z');
const posts = () => analytics.entry.state.calls;

/** Видимый текст без «подробнее». */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

describe('CC-0077: форма → прочитанное', () => {
  const form = (over: Partial<StudioForm> = {}): StudioForm => ({
    videos: [
      {
        ...emptyVideo('dN3vEr5mTh8'),
        lines: ' Досмотрели \n\n72,4 %\n',
        viewed: '72,4',
        swiped: '',
      },
      emptyVideo('sN7gWz4oPc2'),
    ],
    ...over,
  });

  it('только заполненные ролики, строки построчно, доли числом; хук — вручную', () => {
    expect(readOf('example-film', form(), NOW)).toEqual({
      channel: 'example-film',
      read_at: '2026-10-10T07:00:00.000Z',
      hook: 'manual',
      ui_language: 'ru',
      videos: [
        {
          video_id: 'dN3vEr5mTh8',
          lines: ['Досмотрели', '72,4 %'],
          period_text: 'С момента публикации',
          viewed: 72.4,
        },
      ],
    });
  });

  it('доли и замечания словами', () => {
    expect(shareOf('72,4 %')).toBe(72.4);
    expect(shareOf('72.4')).toBe(72.4);
    expect(shareOf('много')).toBe('много');
    expect(shareOf(' ')).toBeNull();
    expect(warningText('viewed: not recognised in the lines')).toBe(
      '«Досмотрели»: не нашлось в строках — доля не записана',
    );
    expect(warningText('period_text: the period the shares cover was not copied')).toBe(
      'Не указано, за какой период цифры',
    );
    expect(warningText('something new')).toBe('something new');
  });
});

async function open() {
  const user = userEvent.setup();
  renderApp('/stats');
  const block = await screen.findByTestId('stats-studio');
  await within(block).findByTestId('studio-due');
  await user.click(within(block).getByTestId('studio-entry-toggle'));
  const cards = within(block).getAllByTestId('studio-entry-video');
  return { user, block, cards };
}

async function fillTwo(user: ReturnType<typeof userEvent.setup>, cards: HTMLElement[]) {
  await user.type(within(cards[0]!).getByTestId('studio-lines'), 'Досмотрели{enter}72,4 %');
  await user.type(within(cards[3]!).getByTestId('studio-lines'), 'Продолжили смотреть');
}

async function planned(user: ReturnType<typeof userEvent.setup>, block: HTMLElement) {
  await user.click(within(block).getByTestId('studio-entry-open'));
  const dialog = await screen.findByRole('alertdialog');
  return { dialog, yes: within(dialog).getByTestId('studio-entry-confirm') };
}

describe('CC-0077: ввод цифр Studio на экране', () => {
  it('карточки последних роликов со ссылкой в Studio; пустая форма — план не спрашиваем', async () => {
    const { user, block, cards } = await open();
    expect(cards).toHaveLength(5);
    expect(cards[0]).toHaveTextContent('Sandfall messiah');
    expect(within(cards[0]!).getByRole('link', { name: 'Открыть в Studio' })).toHaveAttribute(
      'href',
      expect.stringContaining('studio.youtube.com/video/dN3vEr5mTh8'),
    );
    expect(within(cards[0]!).getByTestId('studio-period')).toHaveValue('С момента публикации');
    expect(within(block).queryByText(/Скоро/)).not.toBeInTheDocument();
    const go = within(block).getByTestId('studio-entry-open');
    expect(go).toHaveAttribute('aria-disabled', 'true');
    await user.click(go);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(posts()).toEqual([]);
  });

  it('план: «было → станет», замечания словами, «да» → итог, блок перечитан', async () => {
    const { user, block, cards } = await open();
    await fillTwo(user, cards);
    const { dialog, yes } = await planned(user, block);
    const vids = await within(dialog).findAllByTestId('studio-plan-video');
    expect(vids).toHaveLength(2);
    expect(vids[0]).toHaveTextContent('Sandfall messiah');
    expect(within(vids[0]!).getByTestId('studio-plan-viewed')).toHaveTextContent(
      'Досмотрели: 72,4 % · раньше не читали',
    );
    expect(vids[1]).toHaveTextContent('Rapid reckless 11');
    expect(within(vids[1]!).getByTestId('studio-plan-viewed')).toHaveTextContent(
      'было 55,2 % → станет не распознано',
    );
    expect(within(vids[1]!).getByTestId('studio-plan-warnings')).toHaveTextContent(
      '«Досмотрели»: не нашлось в строках',
    );
    expect(plainText(dialog)).not.toMatch(/dN3vEr5mTh8|not recognised/);
    // Новое ли чтение или замена — до записи не известно, план этого не утверждает.
    expect(within(dialog).getByTestId('studio-plan-videos')).not.toHaveTextContent(/нов|замен/i);
    await waitFor(() => expect(yes).toBeEnabled());
    expect(yes).toHaveTextContent(/Внести · [12]:\d\d/);
    expect(posts().map((c) => c.kind)).toEqual(['plan']);
    expect(posts()[0]!.body).toMatchObject({
      read: {
        channel: 'example-film',
        hook: 'manual',
        ui_language: 'ru',
        videos: [
          { video_id: 'dN3vEr5mTh8', lines: ['Досмотрели', '72,4 %'] },
          { video_id: 'fF11rElDt5x', lines: ['Продолжили смотреть'] },
        ],
      },
    });
    expect(analytics.entry.state.written).toEqual([]);
    await user.click(yes);
    const done = await within(block).findByTestId('studio-done');
    expect(done).toHaveTextContent('Цифры Studio внесены');
    expect(within(done).getByTestId('studio-done-videos')).toHaveTextContent(
      'новых — 2, заменено — 0, без изменений — 0',
    );
    expect(posts().at(-1)).toMatchObject({ kind: 'confirm', body: { confirm: 'studio-1' } });
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    // Перечитано: страховка закрыта, у Sandfall — новое чтение; форма пуста.
    await waitFor(() => expect(within(block).getByTestId('studio-due')).toHaveTextContent('рано'));
    const sandfall = within(block)
      .getAllByTestId('studio-video')
      .find((li) => li.textContent?.includes('Sandfall messiah'))!;
    expect(sandfall).toHaveTextContent('досмотрели 72,4 %');
    expect(within(cards[0]!).getByTestId('studio-lines')).toHaveValue('');
  });

  it('read_refused — заголовок по-русски и строка фабрики; check_changed — план заново сам', async () => {
    const { user, block, cards } = await open();
    await fillTwo(user, cards);
    await user.clear(within(cards[0]!).getByTestId('studio-period'));
    analytics.entry.state.planNext = 'journal_unreadable';
    const { dialog, yes } = await planned(user, block);
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'journal_unreadable');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent(
      'Журнал загрузок не читается — ничего не записано',
    );
    expect(yes).toBeDisabled();
    // «Проверить заново» — план есть, замечание про период словами.
    await user.click(within(dialog).getByRole('button', { name: /Проверить заново/ }));
    const v = await within(dialog).findAllByTestId('studio-plan-video');
    expect(within(v[0]!).getByTestId('studio-plan-warnings')).toHaveTextContent(
      'Не указано, за какой период цифры',
    );
    await waitFor(() => expect(yes).toBeEnabled());
    analytics.entry.state.next = 'check_changed';
    await user.click(yes);
    const again = await within(dialog).findByTestId('replanned');
    expect(again).toHaveAttribute('data-code', 'check_changed');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(posts().filter((c) => c.kind === 'plan')).toHaveLength(3);
    analytics.entry.state.next = 'busy';
    await user.click(yes);
    expect(await within(dialog).findByTestId('act-error')).toHaveTextContent(
      'Идёт другая запись чтения Studio',
    );
    expect(analytics.entry.state.written).toEqual([]);
  });

  it('read_refused: строка фабрики как есть под русским заголовком', async () => {
    const { user, block, cards } = await open();
    await fillTwo(user, cards);
    // Ролик другого канала в журнале — Studio показывала не тот канал.
    analytics.state.videos['example-tech']!.push({
      ...analytics.state.videos['example-tech']![0]!,
      video_id: 'dN3vEr5mTh8',
    });
    const { dialog } = await planned(user, block);
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'read_refused');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent(
      'Фабрика не приняла прочитанное — ничего не записано',
    );
    expect(within(refusal).getByTestId('write-refusal-message')).toHaveTextContent(
      'is of channel example-tech',
    );
  });

  it('план устарел — «запросите заново», «да» погашено', async () => {
    analytics.entry.state.life = 0;
    const { user, block, cards } = await open();
    await fillTwo(user, cards);
    const { dialog, yes } = await planned(user, block);
    expect(await within(dialog).findByTestId('token-expired')).toHaveTextContent(
      'План устарел — запросите заново',
    );
    expect(yes).toBeDisabled();
    expect(analytics.entry.state.written).toEqual([]);
  });

  it('«только смотреть»: кнопка погашена, плана не спрашиваем', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const { user, block, cards } = await open();
    await fillTwo(user, cards);
    const go = within(block).getByTestId('studio-entry-open');
    await waitFor(() => expect(go).toHaveAttribute('data-writes', 'off'));
    await user.click(go);
    expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument();
    expect(posts()).toEqual([]);
  });
});
