// «Снять окончательно…» (CC-0115 шаг 3, CC-0107): план без записи, ответ пользователя — по-русски
// и с именем ролика (центр его не подставляет), он уходит фабрике как есть; отказы словами;
// уже снят — снимать нечего; токен устарел — «План устарел».
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PAST } from '@/mocks/batches';
import { videos } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

async function openPlan(slug = 'rink-rivals') {
  const user = userEvent.setup();
  renderApp(`/videos?batch=${encodeURIComponent(PAST)}&v=${slug}`);
  const box = await screen.findByTestId('withdraw');
  await user.click(within(box).getByTestId('withdraw-open'));
  const dialog = await screen.findByRole('alertdialog');
  await within(dialog).findByTestId('plan-head');
  return { user, box, dialog };
}

describe('ролики: «снять окончательно» (CC-0115 шаг 3)', () => {
  it('план → ответ по-русски с именем ролика → снято, ответ ушёл как есть', async () => {
    const { user, box, dialog } = await openPlan();
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('можно снять');
    expect(within(dialog).getByTestId('withdraw-plan-video')).toHaveTextContent('Rink Rivals');
    expect(within(dialog).getByTestId('withdraw-plan-status')).toHaveTextContent(
      'принят, но не опубликован → после снятия: снят окончательно',
    );
    expect(within(dialog).getByTestId('withdraw-plan-frees')).toHaveTextContent(
      'После снятия освободится 1 исходник',
    );
    const field = within(dialog).getByTestId('withdraw-yes');
    const confirm = within(dialog).getByTestId('withdraw-confirm');
    expect(field).toHaveValue('');
    expect(confirm).toBeDisabled();
    await user.type(field, 'да');
    expect(within(dialog).getByTestId('withdraw-yes-hint')).toHaveTextContent(
      'Впишите имя из подписи выше',
    );
    expect(confirm).toBeDisabled();
    await user.clear(field);
    await user.type(field, 'rink-rivals');
    expect(within(dialog).getByTestId('withdraw-yes-hint')).toHaveTextContent('по-русски');
    await user.clear(field);
    await user.type(field, 'снимаю rink-rivals насовсем');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    expect(await within(box).findByTestId('withdraw-done')).toHaveTextContent(
      'Ролик снят окончательно',
    );
    expect(videos.withdrawal.state.answers).toEqual(['снимаю rink-rivals насовсем']);
    expect(videos.withdrawal.state.calls.at(-1)!.body).toEqual({
      confirm: 'withdraw-1',
      answer: 'снимаю rink-rivals насовсем',
    });
  });

  it('уже снят — «снять нельзя», поля ответа нет', async () => {
    videos.withdrawal.state.journal.push({
      event: 'withdrawn',
      entry_id: `${PAST}/rink-rivals`,
      at: '2026-10-09T10:00:00Z',
    });
    const { dialog } = await openPlan();
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('снять нельзя');
    expect(within(dialog).getByTestId('plan-why')).toHaveTextContent('уже снят окончательно');
    expect(within(dialog).queryByTestId('withdraw-yes')).toBeNull();
  });

  it('отказ «да» словами; токен устарел — «План устарел»', async () => {
    videos.withdrawal.state.next = 'factory_broken';
    const { user, dialog } = await openPlan();
    await user.type(within(dialog).getByTestId('withdraw-yes'), 'снимаю rink-rivals');
    await user.click(within(dialog).getByTestId('withdraw-confirm'));
    expect(await within(dialog).findByTestId('act-error')).toHaveTextContent(
      'Фабрика ответила ошибкой',
    );
    expect(videos.withdrawal.state.journal).toEqual([]);
    await user.click(within(dialog).getByTestId('replan'));
    await within(dialog).findByTestId('withdraw-yes');
    expect(within(dialog).getByTestId('withdraw-yes')).toHaveValue('');
    videos.withdrawal.expireTokens();
    await user.type(within(dialog).getByTestId('withdraw-yes'), 'снимаю rink-rivals');
    await user.click(within(dialog).getByTestId('withdraw-confirm'));
    await waitFor(() =>
      expect(within(dialog).getByTestId('withdraw-plan')).toHaveTextContent(/устарел/),
    );
    expect(videos.withdrawal.state.journal).toEqual([]);
  });

  it('идут батчи — исходники держат, план это говорит', async () => {
    videos.withdrawal.state.openBatches = ['example-film/2026-10-10T0200Z'];
    const { dialog } = await openPlan('delver');
    expect(within(dialog).getByTestId('withdraw-plan-frees')).toHaveTextContent(
      'Ни один исходник темы не освободится',
    );
    expect(within(dialog).getByTestId('withdraw-plan-open')).toHaveTextContent('Идут батчи (1)');
  });
});
