// CC-0019: окно «Попросить оператора» — общая кнопка в шапке (контекст — экран), видимое
// «Откуда», «Отправить» погашено, пока пусто, отказ — строкой фабрики, «только смотреть» —
// кнопка погашена и ничего не уходит.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { fixtures, writesModes } from '@/mocks/fixtures';
import { mockGet, requests } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { areaOf, contextOf, contextRows } from './target';

describe('CC-0019: контекст просьбы', () => {
  it('экран по адресу, пустое не пишется', () => {
    expect(areaOf('/channels/example-film')).toBe('Каналы');
    expect(areaOf('/')).toBe('Главная');
    expect(areaOf('/nope')).toBe('Командный центр');
    expect(
      contextOf({ pathname: '/videos', search: '?batch=b&v=s' }, { channel: 'c', video: 's' }),
    ).toEqual({
      screen: '/videos?batch=b&v=s',
      area: 'Ролики',
      channel: 'c',
      video: 's',
    });
  });

  it('«Откуда» словами из любого JSON; незнакомое не показывается', () => {
    const name = (id: string) => (id === 'example-film' ? 'ExampleFilm' : id);
    expect(
      contextRows(
        { screen: '/batches', channel: 'example-film', batch: 'b/1', video_title: 'Ролик', x: 1 },
        name,
      ).map((r) => `${r.label}: ${r.value}`),
    ).toEqual(['Экран: Батчи', 'Канал: ExampleFilm', 'Батч: b/1', 'Ролик: «Ролик»']);
    expect(contextRows('строка', name, 'example-film')).toEqual([
      { key: 'channel', label: 'Канал', value: 'ExampleFilm' },
    ]);
    expect(contextRows(null, name)).toEqual([]);
  });
});

describe('CC-0019: окно «Попросить оператора»', () => {
  it('из шапки: контекст — экран, «Отправить» ждёт текста, просьба уходит без `by`', async () => {
    const user = userEvent.setup();
    renderApp('/publishing');
    await user.click(await screen.findByTestId('ask-open-header'));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByRole('heading')).toHaveTextContent('Попросить оператора');
    expect(within(dialog).getByTestId('ask-context')).toHaveTextContent('ЭкранПубликация');
    const text = within(dialog).getByTestId('ask-text');
    expect(text).toHaveFocus();
    const send = within(dialog).getByTestId('ask-send');
    expect(send).toHaveAttribute('aria-disabled', 'true');
    await user.click(send);
    expect(requests.writes).toEqual([]);
    await user.type(text, 'Сколько роликов ждут загрузки?');
    expect(send).not.toHaveAttribute('aria-disabled');
    await user.click(send);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(await screen.findByText('Просьба отправлена оператору')).toBeInTheDocument();
    expect(requests.writes).toEqual([
      {
        path: '/api/requests',
        body: {
          text: 'Сколько роликов ждут загрузки?',
          channel: null,
          context: { screen: '/publishing', area: 'Публикация' },
        },
      },
    ]);
    expect(requests.requests.at(-1)).toMatchObject({ id: 'R7', status: 'open' });
  });

  it('отказ фабрики — её строкой в окне, текст остаётся; JSON контекста — под «подробнее»', async () => {
    requests.next = { status: 422, code: 'context_invalid' };
    const user = userEvent.setup();
    renderApp('/');
    await user.click(await screen.findByTestId('ask-open-header'));
    const dialog = await screen.findByRole('alertdialog');
    const more = within(dialog).getByTestId('ask-context-json');
    expect(more.closest('details')).not.toHaveAttribute('open');
    expect(more).toHaveTextContent('"screen": "/"');
    await user.type(within(dialog).getByTestId('ask-text'), 'да{Control>}{Enter}{/Control}');
    const err = await within(dialog).findByTestId('create-error');
    expect(err).toHaveTextContent('Просьба не отправлена');
    expect(err).toHaveTextContent('Контекст просьбы не записать');
    expect(within(dialog).getByTestId('ask-text')).toHaveValue('да');
  });

  it('«только смотреть»: кнопка в шапке погашена причиной, окно не открывается', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    const user = userEvent.setup();
    renderApp('/');
    const btn = await screen.findByTestId('ask-open-header');
    await waitFor(() => expect(btn).toHaveAttribute('data-writes', 'off'));
    await user.click(btn);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(requests.writes).toEqual([]);
  });

  it('на канале: канал подставлен сам и уходит полем `channel`', async () => {
    const user = userEvent.setup();
    renderApp('/channels/example-film');
    await user.click(await screen.findByTestId('ask-channel'));
    const dialog = await screen.findByRole('alertdialog');
    const ctx = within(dialog).getByTestId('ask-context');
    expect(ctx).toHaveTextContent('ЭкранКаналы');
    expect(ctx).toHaveTextContent('КаналExampleFilm');
    await user.type(within(dialog).getByTestId('ask-text'), 'Проверь позицию');
    await user.click(within(dialog).getByTestId('ask-send'));
    await waitFor(() => expect(requests.writes).toHaveLength(1));
    expect(requests.writes[0]!.body).toEqual({
      text: 'Проверь позицию',
      channel: 'example-film',
      context: { screen: '/channels/example-film', area: 'Каналы', channel: 'example-film' },
    });
  });
});
