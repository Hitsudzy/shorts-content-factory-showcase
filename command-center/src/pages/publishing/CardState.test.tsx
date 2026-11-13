// CC-0127: карточка без оператора на экране — состояние в копилке, на странице ролика, «Для
// Studio» и в ленте; «Собрать заново…» (план с «решение пропадёт» → «да» → опрос → итог);
// «Принять своим решением…» (ваши слова обязательны, план — что не прошло и что покрывает
// решение → «да» → итог; утверждение названия — отказ словами); приёмка — «карточка
// собирается…» рядом со строкой копилки; размещение — по `placeable`.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PAST } from '@/mocks/batches';
import {
  CARD_BUILDING,
  CARD_OWN_FAIL,
  CARD_READY,
  CARD_RULED,
  CARD_TITLE_FAIL,
  RULED_WORDS,
} from '@/mocks/cards';
import { publish } from '@/mocks/handlers';
import { REEL } from '@/mocks/publish';
import { SCIENCE, STASH_OLD_BATCH } from '@/mocks/videos';
import { renderApp } from '@/test/renderApp';

import { cardStateView, reasonsText, whereText } from './cardWords';

const rowOf = async (slug: string) => {
  const stash = await screen.findByTestId('stash');
  await waitFor(() => expect(within(stash).getAllByTestId('stash-row')).toHaveLength(4));
  return within(stash)
    .getAllByTestId('stash-row')
    .find((r) => r.dataset.slug === slug)!;
};

describe('состояние карточки словами', () => {
  it('нет / собирается / готова / вашим решением / не готова: почему', () => {
    expect(cardStateView({ state: 'none' }).label).toBe('нет карточки');
    expect(cardStateView({ state: 'building' }).label).toBe('собирается…');
    expect(cardStateView({ state: 'ready' }).tone).toBe('ok');
    const ruled = cardStateView({
      state: 'ruled',
      ruling: { words: 'беру', at: '2026-10-10T07:00:00Z' },
    });
    expect(ruled.label).toBe('готова вашим решением');
    expect(ruled.tip).toMatch(/«беру»/);
    expect(cardStateView({ state: 'not_ready', reasons: ['claims_failed'] }).label).toBe(
      'не готова: не прошла проверка утверждений',
    );
    // Неизвестный код — строка фабрики.
    expect(reasonsText({ state: 'not_ready', reasons: ['zzz'], why: 'строка фабрики' })).toBe(
      'строка фабрики',
    );
    expect(whereText('claims/on_screen')).toBe('текст на экране');
    expect(whereText('claims/title')).toBe('название карточки');
  });
});

describe('CC-0127: карточка в копилке', () => {
  it('готова, вашим решением (её можно отметить), собирается → готова через два опроса, не готова — почему и действия', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const ready = await rowOf(CARD_READY);
    expect(within(ready).getByTestId('stash-card')).toHaveTextContent('карточка готова');
    const ruled = await rowOf(CARD_RULED);
    const ruledBadge = within(ruled).getByTestId('stash-card');
    expect(ruledBadge).toHaveTextContent('карточка готова вашим решением');
    expect(ruledBadge).toHaveAttribute('data-placeable', '1');
    // «Отметить готовые» берёт и принятую решением (held — нет).
    await user.click(within(await screen.findByTestId('stash')).getByTestId('stash-pick-ready'));
    expect(ruled).toHaveAttribute('data-picked', '1');
    const notReady = await rowOf(CARD_OWN_FAIL);
    expect(within(notReady).getByTestId('stash-card')).toHaveTextContent('карточка не готова');
    expect(within(notReady).getByTestId('card-rebuild-open')).toBeInTheDocument();
    expect(within(notReady).getByTestId('card-ruling-toggle')).toBeInTheDocument();
    expect(within(ready).queryByTestId('card-actions')).toBeNull();

    const building = await rowOf(CARD_BUILDING);
    const badge = within(building).getByTestId('stash-card');
    expect(badge).toHaveAttribute('data-state', 'building');
    expect(badge).toHaveTextContent('карточка собирается…');
    expect(within(badge).getByTestId('spinner')).toBeInTheDocument();
    // Опрос раз в poll_s (1 с у подставной фабрики): на третий — готова, копилка перечитана.
    await waitFor(
      async () =>
        expect(within(await rowOf(CARD_BUILDING)).getByTestId('stash-card')).toHaveAttribute(
          'data-state',
          'ready',
        ),
      { timeout: 9000 },
    );
    expect(publish.cards.state.calls.filter((c) => c.kind === 'run').length).toBeGreaterThanOrEqual(
      3,
    );
  }, 15_000);

  it('«Принять своим решением…»: без слов — нельзя; план — что не прошло и что покрывает; «да» — принята', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const row = await rowOf(CARD_OWN_FAIL);
    await user.click(within(row).getByTestId('card-ruling-toggle'));
    const open = within(row).getByTestId('card-ruling-open');
    expect(open).toHaveAttribute('aria-disabled', 'true');
    await user.type(
      within(row).getByTestId('card-ruling-words-input'),
      'Цифру проверил по Variety — публикуем',
    );
    await user.click(within(row).getByTestId('card-ruling-open'));
    const dialog = await screen.findByRole('alertdialog');
    // CC-0128: окно решения открыто — встроенная форма свёрнута (не два «Ваше решение» разом).
    expect(within(row).getByTestId('card-ruling-form')).not.toBeVisible();
    expect(within(row).getByTestId('card-ruling-toggle')).toHaveAttribute('aria-expanded', 'false');
    const fails = await within(dialog).findAllByTestId('card-ruling-fail');
    expect(fails.map((f) => f.dataset.own)).toEqual(['1', '1']);
    expect(fails[0]).toHaveTextContent('комментарий ролика');
    expect(fails[1]).toHaveTextContent('текст на экране');
    expect(within(dialog).getByTestId('card-ruling-scope')).toHaveTextContent(
      'только слова самого ролика',
    );
    // Коды — только под «Подробнее».
    expect(
      within(dialog)
        .getAllByText(/no_source/)
        .every((el) => el.closest('[data-slot="more"]')),
    ).toBe(true);
    const yes = within(dialog).getByTestId('card-ruling-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const done = await screen.findByTestId('card-ruling-done');
    expect(done).toHaveTextContent('Карточка принята вашим решением');
    expect(done).toHaveTextContent('Сохранено: 2 файла публикации');
    await waitFor(async () =>
      expect(within(await rowOf(CARD_OWN_FAIL)).getByTestId('stash-card')).toHaveAttribute(
        'data-state',
        'ruled',
      ),
    );
  });

  it('CC-0128: «Отмена» в окне решения — форма снова раскрыта, набранные слова целы', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const row = await rowOf(CARD_OWN_FAIL);
    await user.click(within(row).getByTestId('card-ruling-toggle'));
    await user.type(within(row).getByTestId('card-ruling-words-input'), 'беру под себя');
    await user.click(within(row).getByTestId('card-ruling-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(row).getByTestId('card-ruling-form')).not.toBeVisible();
    await user.click(within(dialog).getByRole('button', { name: /Отмена|Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(within(row).getByTestId('card-ruling-form')).toBeVisible();
    expect(within(row).getByTestId('card-ruling-words-input')).toHaveValue('беру под себя');
    // Свернуть руками — по-прежнему кнопкой.
    await user.click(within(row).getByTestId('card-ruling-toggle'));
    expect(within(row).getByTestId('card-ruling-form')).not.toBeVisible();
  });

  it('commit_refused — словами в окне, код — под «подробнее»', async () => {
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const row = await rowOf(CARD_OWN_FAIL);
    await user.click(within(row).getByTestId('card-ruling-toggle'));
    await user.type(within(row).getByTestId('card-ruling-words-input'), 'беру');
    await user.click(within(row).getByTestId('card-ruling-open'));
    const dialog = await screen.findByRole('alertdialog');
    const yes = within(dialog).getByTestId('card-ruling-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    publish.cards.state.next = 'commit_refused';
    await user.click(yes);
    expect(await within(dialog).findByTestId('write-refusal-title')).toHaveTextContent(
      'Записано, но коммит не прошёл',
    );
  });
});

describe('CC-0127: карточка на странице ролика', () => {
  it('вашим решением — слова видны; «Собрать заново…»: решение пропадёт → «да» → собирается → готова', async () => {
    const user = userEvent.setup();
    renderApp(`/videos?batch=${encodeURIComponent(STASH_OLD_BATCH)}&v=${CARD_RULED}`);
    const card = await screen.findByTestId('publish-card');
    await waitFor(() =>
      expect(within(card).getByTestId('card-state')).toHaveTextContent('готова вашим решением'),
    );
    expect(within(card).getByTestId('card-ruling-said')).toHaveTextContent(RULED_WORDS);
    await user.click(await within(card).findByTestId('card-rebuild-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('card-build-replaces')).toHaveTextContent(
      'решение пропадёт',
    );
    const yes = within(dialog).getByTestId('card-rebuild-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const progress = await within(card).findByTestId('card-build');
    expect(progress).toHaveAttribute('data-done', '0');
    expect(progress).toHaveTextContent('Карточка собирается…');
    await waitFor(
      () =>
        expect(within(card).getByTestId('card-build')).toHaveTextContent(
          'Карточка собрана и готова к публикации.',
        ),
      { timeout: 9000 },
    );
    await waitFor(() =>
      expect(within(card).getByTestId('card-state')).toHaveAttribute('data-state', 'ready'),
    );
  }, 15_000);

  it('не прошло утверждение названия — решением не принять: отказ словами, «да» погашено', async () => {
    const user = userEvent.setup();
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}&v=${CARD_TITLE_FAIL}`);
    const card = await screen.findByTestId('publish-card');
    await user.click(await within(card).findByTestId('card-ruling-toggle'));
    await user.type(within(card).getByTestId('card-ruling-words-input'), 'беру');
    await user.click(within(card).getByTestId('card-ruling-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('card-plan-refusal')).toHaveTextContent(
      'утверждение названия карточки',
    );
    expect(within(dialog).getByTestId('card-ruling-fail')).toHaveAttribute('data-own', '0');
    expect(within(dialog).getByTestId('card-ruling-confirm')).toBeDisabled();
  });
});

describe('CC-0127: приёмка запускает сборку карточки', () => {
  it('«Да» — рядом со строкой копилки «карточка собирается…», потом итог', async () => {
    const user = userEvent.setup();
    renderApp(`/videos?batch=${encodeURIComponent(SCIENCE)}&v=mars-sample-return`);
    await user.click(await screen.findByTestId('verdict-yes'));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    const queued = await screen.findByTestId('acceptance-answer-queued');
    const build = await within(queued).findByTestId('accept-card-build');
    expect(build).toHaveTextContent('Карточка собирается…');
    await waitFor(
      () =>
        expect(within(queued).getByTestId('accept-card-build')).toHaveTextContent(
          'Карточка собрана и готова к публикации.',
        ),
      { timeout: 9000 },
    );
  }, 15_000);
});
