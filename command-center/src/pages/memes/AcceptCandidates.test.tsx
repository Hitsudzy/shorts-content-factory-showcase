// Приём кандидатов в банк мемов (CC-0115 шаг 3): выбор, текст записи по кандидату, план, «да»
// набирает пользователь и уходит фабрике как ответ; список сдвинулся — словами; отказы.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { memes } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

async function open() {
  const user = userEvent.setup();
  renderApp('/memes?channel=example-tech');
  const card = await screen.findByTestId('meme-candidates');
  await within(card).findByTestId('candidates-summary');
  await user.click(within(card).getByTestId('meme-accept-toggle'));
  const item = (id: string) =>
    card.querySelector<HTMLElement>(`[data-testid="meme-accept-item"][data-id="${id}"]`)!;
  return { user, card, item };
}

describe('мемы: приём кандидатов в банк (CC-0115 шаг 3)', () => {
  it('выбор и текст по кандидату → план → набранное «да» уходит ответом', async () => {
    const { user, card, item } = await open();
    expect(within(card).getAllByTestId('meme-accept-item')).toHaveLength(2);
    await user.click(within(item('drake')).getByTestId('meme-accept-pick'));
    const fine = item('this-is-fine');
    await user.type(
      within(fine).getByTestId('meme-accept-description'),
      'всё горит, а мы спокойны',
    );
    await user.type(within(fine).getByTestId('meme-accept-tags'), 'calm, disaster');
    await user.click(within(card).getByTestId('meme-accept-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('accept-plan-take')).toHaveTextContent('This Is Fine');
    // CC-0131: «Возьмёт в банк (N шаблонов)» — одна строка; вопрос фабрики — только под «подробнее».
    expect(within(dialog).queryByTestId('accept-plan-prompt')).toBeNull();
    expect(within(dialog).getByTestId('accept-plan-take')).toHaveTextContent(
      /Возьмёт в банк \(\d+ шаблон(а|ов)?\)/,
    );
    expect(memes.accept.plans.at(-1)).toEqual({
      ids: ['this-is-fine'],
      details: {
        'this-is-fine': {
          description: 'всё горит, а мы спокойны',
          tags: ['calm', 'disaster'],
          notes: null,
        },
      },
    });
    const yes = within(dialog).getByTestId('meme-accept-yes');
    expect(yes).toHaveValue('');
    const confirm = within(dialog).getByTestId('meme-accept-confirm');
    expect(confirm).toBeDisabled();
    await user.type(yes, 'Да');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    expect(await within(card).findByTestId('meme-accept-done')).toHaveTextContent(
      'Принято в банк: 1 шаблон',
    );
    expect(memes.accept.answers).toEqual(['Да']);
    expect(memes.accept.accepted).toEqual(['this-is-fine']);
  });

  it('ни одного не отмечено — план не спрашиваем', async () => {
    const { user, card, item } = await open();
    await user.click(within(item('drake')).getByTestId('meme-accept-pick'));
    await user.click(within(item('this-is-fine')).getByTestId('meme-accept-pick'));
    await user.click(within(card).getByTestId('meme-accept-open'));
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(memes.accept.plans).toEqual([]);
  });

  it('список сдвинулся с плана — «Список кандидатов изменился, откройте заново»', async () => {
    memes.accept.listChanged = true;
    const { user, card } = await open();
    await user.click(within(card).getByTestId('meme-accept-open'));
    const dialog = await screen.findByRole('alertdialog');
    await user.type(await within(dialog).findByTestId('meme-accept-yes'), 'да');
    await user.click(within(dialog).getByTestId('meme-accept-confirm'));
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveAttribute('data-code', 'list_changed');
    expect(err).toHaveTextContent('Список кандидатов изменился, откройте заново');
    expect(memes.accept.accepted).toEqual([]);
  });

  it('токен устарел — план заново, «да» снова пустое', async () => {
    const { user, card } = await open();
    await user.click(within(card).getByTestId('meme-accept-open'));
    const dialog = await screen.findByRole('alertdialog');
    await user.type(await within(dialog).findByTestId('meme-accept-yes'), 'да');
    for (const t of memes.accept.tokens.values()) t.expires = 0;
    await user.click(within(dialog).getByTestId('meme-accept-confirm'));
    expect(await within(dialog).findByTestId('replanned')).toHaveAttribute(
      'data-code',
      'confirm_expired',
    );
    await waitFor(() => expect(memes.accept.plans).toHaveLength(2));
    expect(await within(dialog).findByTestId('meme-accept-yes')).toHaveValue('');
  });
});
