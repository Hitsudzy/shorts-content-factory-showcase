// История переключателя API-загрузки (CC-0141): новые сверху, не больше пяти, кто словами,
// «переключений не было», число предупреждений — только если оно есть; на экране — свёрнуто.
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { REEL, SCIENCE } from '@/mocks/publish';
import { renderApp } from '@/test/renderApp';

import { SwitchHistory } from './SwitchHistory';
import { latestSwitches, switchAction, switchWho } from './switchHistoryWords';

const row = (at: string | null, action: string | null, extra: Record<string, unknown> = {}) => ({
  at,
  by: 'user',
  channel: 'example-film',
  action,
  note: null,
  warnings: [] as string[],
  ...extra,
});

describe('история переключателя: слова', () => {
  it('кто: user — вы, user (центр) — вы из центра, system — фабрика, иное как есть', () => {
    expect(switchWho('user')).toBe('вы');
    expect(switchWho('user (центр)')).toBe('вы, из центра');
    expect(switchWho('system')).toBe('фабрика');
    expect(switchWho('operator')).toBe('operator');
    expect(switchWho(null)).toBe('кто — не записано');
  });

  it('что: on/off словами, незнакомое как есть', () => {
    expect(switchAction('on')).toBe('включена');
    expect(switchAction('off')).toBe('выключена');
    expect(switchAction('reset')).toBe('reset');
    expect(switchAction(null)).toBe('действие не записано');
  });

  it('новые сверху по времени, не больше пяти, без даты — в конце', () => {
    const rows = [
      row('2026-10-01T10:00:00Z', 'off'),
      row(null, 'on', { note: 'без даты' }),
      ...['02', '03', '04', '05', '06'].map((d) => row(`2026-10-${d}T10:00:00Z`, 'on')),
    ];
    const at = latestSwitches(rows).map((r) => r.at);
    expect(at).toEqual([
      '2026-10-06T10:00:00Z',
      '2026-10-05T10:00:00Z',
      '2026-10-04T10:00:00Z',
      '2026-10-03T10:00:00Z',
      '2026-10-02T10:00:00Z',
    ]);
    expect(latestSwitches(rows, 10).at(-1)?.note).toBe('без даты');
  });
});

describe('история переключателя: блок', () => {
  it('строки по МСК, кто, что, заметка; предупреждения — только если есть', () => {
    render(
      <SwitchHistory
        rows={[
          row('2026-10-02T09:12:00Z', 'on', { note: 'пробная загрузка', warnings: ['a', 'b'] }),
          row('2026-10-03T16:45:00Z', 'off', { by: 'user (центр)', note: '  вернул Studio  ' }),
        ]}
      />,
    );
    const items = screen.getAllByTestId('switch-history-row');
    expect(items).toHaveLength(2);
    expect(items[0]).toHaveTextContent('03.10, 19:45 · вы, из центра · выключена');
    expect(items[0]).toHaveTextContent('«вернул Studio»');
    expect(items[0]).not.toHaveTextContent('предупреждений');
    expect(items[1]).toHaveTextContent('02.10, 12:12 · вы · включена · предупреждений: 2');
    expect(items[1]).toHaveTextContent('«пробная загрузка»');
    expect(screen.queryByTestId('switch-history-empty')).toBeNull();
  });

  it('пусто — «переключений не было»; больше пяти — сколько всего', () => {
    const { unmount } = render(<SwitchHistory rows={[]} />);
    expect(screen.getByTestId('switch-history-empty')).toHaveTextContent('переключений не было');
    unmount();
    render(
      <SwitchHistory
        rows={['01', '02', '03', '04', '05', '06', '07'].map((d) =>
          row(`2026-10-${d}T10:00:00Z`, 'on'),
        )}
      />,
    );
    expect(screen.getAllByTestId('switch-history-row')).toHaveLength(5);
    expect(screen.getByTestId('switch-history')).toHaveTextContent('показаны последние 5 из 7');
  });

  it('на экране «Публикация»: у ExampleFilm три строки свёрнуто, у ExampleScience — пусто', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const block = await screen.findByTestId('state-api-upload');
    const history = await within(block).findByTestId('switch-history');
    expect(history).not.toHaveAttribute('open');
    await user.click(within(history).getByText('История переключений'));
    expect(history).toHaveAttribute('open');
    const items = within(history).getAllByTestId('switch-history-row');
    expect(items).toHaveLength(3);
    expect(items[0]).toHaveTextContent('вы, из центра · выключена');
    expect(items[1]).toHaveTextContent('включена · предупреждений: 2');
    expect(items[2]).toHaveTextContent('28.09, 10:30 · фабрика · выключена');
  });

  it('ExampleScience: «переключений не было»', async () => {
    renderApp(`/publishing?channel=${SCIENCE}`);
    const block = await screen.findByTestId('state-api-upload');
    expect(await within(block).findByTestId('switch-history-empty')).toHaveTextContent(
      'переключений не было',
    );
  });
});
