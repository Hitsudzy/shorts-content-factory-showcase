// «Правил в Studio» и отмена (CC-0115 шаг 3, CC-0106): план — строка журнала и серия после,
// «да» набирает пользователь, серия перечитывается; отказы словами; токен устарел — новый план.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { publish } from '@/mocks/handlers';
import { EDITED_VIDEO, PLACED } from '@/mocks/publish';
import { renderApp } from '@/test/renderApp';

async function open() {
  const user = userEvent.setup();
  renderApp('/publishing');
  const block = await screen.findByTestId('state-studio');
  await within(block).findByText(/Подряд без правок/);
  return { user, block };
}

async function planOf(user: ReturnType<typeof userEvent.setup>, id: string) {
  await user.click(screen.getByTestId(`${id}-open`));
  const dialog = await screen.findByRole('alertdialog');
  await within(dialog).findByTestId('plan-head');
  return dialog;
}

describe('публикация: «правил в Studio» и отмена (CC-0115 шаг 3)', () => {
  it('последний из серии → план «серия станет 0» → «да» набрано → отмечено, серия заново', async () => {
    const { user, block } = await open();
    expect(block).toHaveTextContent('2 из 5');
    await user.click(within(block).getByTestId('studio-edited-toggle'));
    await user.type(within(block).getByTestId('studio-edited-note'), 'поправил описание');
    const dialog = await planOf(user, 'studio-edited');
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('можно отметить');
    expect(within(dialog).getByTestId('edited-plan-streak')).toHaveTextContent('станет: 0 из 5');
    // CC-0131: название ролика (журнал его не хранит — имя словами), не «загружен через Studio».
    expect(within(dialog).getByTestId('edited-plan-video')).toHaveTextContent(/^Ролик: «[^»]+»/);
    expect(within(dialog).getByTestId('edited-plan-video')).not.toHaveTextContent('загружен через');
    expect(within(dialog).getByTestId('edited-plan-note')).toHaveTextContent('поправил описание');
    expect(publish.writes.state.calls.at(-1)!.body).toEqual({
      slug: PLACED,
      note: 'поправил описание',
    });
    const confirm = within(dialog).getByTestId('studio-edited-confirm');
    expect(within(dialog).getByTestId('studio-edited-yes')).toHaveValue('');
    expect(confirm).toBeDisabled();
    await user.type(within(dialog).getByTestId('studio-edited-yes'), 'да');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    expect(await within(block).findByTestId('studio-edited-done')).toHaveTextContent(
      'Правка в Studio отмечена',
    );
    expect(publish.writes.state.written.map((w) => w.action)).toEqual(['studio_edited']);
    expect(publish.writes.state.calls.at(-1)!.body).toEqual({ confirm: 'pub-studio_edited-1' });
    await waitFor(() => expect(block).toHaveTextContent('0 из 5'));
  });

  it('по ссылке из Studio: ссылка не ролик — кнопка погашена; ролик загружен через API — нельзя', async () => {
    publish.writes.state.uploads.push({
      channel: 'example-film',
      slug: 'api-video',
      video_id: 'Zz9yX8wV7uT',
      source: 'api',
      publish_at: null,
      entry_id: null,
      recorded_at: '2026-10-09T10:00:00Z',
    });
    const { user, block } = await open();
    await user.click(within(block).getByTestId('studio-edited-toggle'));
    await user.click(within(block).getByTestId('studio-edited-other'));
    await user.type(within(block).getByTestId('studio-edited-link'), 'не ссылка');
    expect(within(block).getByTestId('studio-edited-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    await user.clear(within(block).getByTestId('studio-edited-link'));
    await user.type(
      within(block).getByTestId('studio-edited-link'),
      'https://youtube.com/shorts/Zz9yX8wV7uT',
    );
    const dialog = await planOf(user, 'studio-edited');
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('отметить нельзя');
    expect(within(dialog).getByTestId('plan-why')).toHaveTextContent('загружен не через Studio');
    expect(within(dialog).queryByTestId('studio-edited-yes')).toBeNull();
  });

  it('отмена отметки последней правки → план → «да» → снято, серия пересчитана', async () => {
    const { user, block } = await open();
    const dialog = await planOf(user, 'studio-unedit');
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('можно снять');
    expect(publish.writes.state.calls.at(-1)!.body).toEqual({ video_id: EDITED_VIDEO });
    await user.type(within(dialog).getByTestId('studio-unedit-yes'), 'да');
    await user.click(within(dialog).getByTestId('studio-unedit-confirm'));
    expect(await within(block).findByTestId('studio-edited-done')).toHaveTextContent(
      'Отметка о правке снята',
    );
    await waitFor(() => expect(block).toHaveTextContent('цель взята'));
  });

  it('отказ «да» словами; токен устарел — «План устарел»', async () => {
    publish.writes.state.next = 'factory_broken';
    const { user } = await open();
    let dialog = await planOf(user, 'studio-unedit');
    await user.type(within(dialog).getByTestId('studio-unedit-yes'), 'да');
    await user.click(within(dialog).getByTestId('studio-unedit-confirm'));
    expect(await within(dialog).findByTestId('act-error')).toHaveTextContent(
      'Фабрика сломалась посреди записи',
    );
    expect(publish.writes.state.written).toEqual([]);
    await user.keyboard('{Escape}');
    dialog = await planOf(user, 'studio-unedit');
    publish.writes.expireTokens();
    await user.type(within(dialog).getByTestId('studio-unedit-yes'), 'да');
    await user.click(within(dialog).getByTestId('studio-unedit-confirm'));
    await waitFor(() =>
      expect(within(dialog).getByTestId('studio-unedit-plan')).toHaveTextContent(/устарел/),
    );
    expect(publish.writes.state.written).toEqual([]);
  });
});
