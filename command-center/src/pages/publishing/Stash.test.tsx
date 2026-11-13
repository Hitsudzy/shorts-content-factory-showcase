// Копилка канала (CC-0122): принятые без слота над лентой — давность, «устарел», карточка, холд,
// превью и ссылка; порядок ↑/↓ с клавиатуры; пачкой по слотам — план с отказами по ролику, одно
// «да», итог с коммитом; dirty / commit_refused словами; «Доложить в копилку…»; «в копилке N».
import { act, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { stashKey } from '@/api/stash';

import { publish } from '@/mocks/handlers';
import { REEL, SCIENCE } from '@/mocks/publish';
import {
  NOT_QUEUED,
  STASH_BUILDING,
  STASH_HELD,
  STASH_NOT_READY,
  STASH_STALE,
  STASH_TITLES,
} from '@/mocks/stash';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import {
  acceptedAgo,
  ageOf,
  mergeOrder,
  move,
  slotWhen,
  stashTitle,
  stashTitles,
  videoHref,
  withoutPath,
} from './stashWords';

/** CC-0128: название для показа — без « #shorts». */
const clean = (slug: string) => STASH_TITLES[slug]!.replace(/ #shorts$/, '');

async function open(channel = REEL) {
  const user = userEvent.setup();
  const { queryClient } = renderApp(`/publishing?channel=${channel}`);
  const stash = await screen.findByTestId('stash');
  /** Перечитать копилку — как опрос раз в минуту (CC-0164). */
  const reread = () =>
    act(() => queryClient.refetchQueries({ queryKey: stashKey(channel) }).catch(() => {}));
  return { user, stash, reread };
}

const rowsOf = (stash: HTMLElement) => within(stash).getAllByTestId('stash-row');
const rowOf = (stash: HTMLElement, slug: string) =>
  rowsOf(stash).find((r) => r.dataset.slug === slug)!;
const slugs = (stash: HTMLElement) => rowsOf(stash).map((r) => r.dataset.slug);

describe('копилка словами', () => {
  it('давность, возраст, порядок', () => {
    expect(acceptedAgo(0)).toBe('принят сегодня');
    expect(acceptedAgo(1)).toBe('принят вчера');
    expect(acceptedAgo(5)).toBe('принят 5 дней назад');
    expect(acceptedAgo(22)).toBe('принят 22 дня назад');
    const news = ageOf({ basis: 'news', days: 20, news_at: '2026-09-20T12:00:00Z', stale: true });
    expect(news.stale).toBe(true);
    expect(news.tip).toMatch(/от даты новости темы \(20\.09\)/);
    expect(news.tip).toMatch(/только пометка/);
    const evergreen = ageOf({ basis: 'accepted', days: 3, stale: false });
    expect(evergreen.tip).toMatch(/вечнозелёная/);
    expect(move(['a', 'b', 'c'], 0, -1)).toEqual(['a', 'b', 'c']);
    expect(move(['a', 'b', 'c'], 1, 1)).toEqual(['a', 'c', 'b']);
    expect(slotWhen('2026-10-14', '2026-10-14 01:00 МСК', () => 'вт 14.10')).toBe(
      'вт 14.10, 01:00',
    );
  });

  it('CC-0128: название — title_clean, иначе из карточки, иначе без хэштегов, иначе слаг словами', () => {
    expect(stashTitle({ slug: 's', title: 'Big News #shorts', title_clean: 'Big News' })).toBe(
      'Big News',
    );
    expect(
      stashTitle({ slug: 's', title: null, card: { title: 'Card #shorts', title_clean: 'Card' } }),
    ).toBe('Card');
    expect(stashTitle({ slug: 's', title: 'Raw Title #shorts #кино' })).toBe('Raw Title');
    expect(stashTitle({ slug: 'rink-rivals', title: null, title_clean: '  ' })).toBe(
      'Rink rivals',
    );
    const nameOf = stashTitles([
      { slug: 'a', title_clean: 'Alpha' } as Parameters<typeof stashTitles>[0][number],
    ]);
    expect(nameOf('a')).toBe('Alpha');
    expect(nameOf('the-nightwatch')).toBe('The nightwatch');
    expect(nameOf(null)).toBe('—');
  });

  it('CC-0128: строка фабрики без путей — в конце, посреди, в скобках', () => {
    expect(withoutPath('Будет положен в копилку: publish/r/_queue/x.mp4')).toBe(
      'Будет положен в копилку',
    );
    expect(withoutPath('ролик положен в копилку publish/r/_queue/x.mp4, карточка собирается')).toBe(
      'ролик положен в копилку, карточка собирается',
    );
    expect(withoutPath('не положен (pipeline/r/b/videos/x.mp4) — нет файла')).toBe(
      'не положен — нет файла',
    );
    expect(withoutPath('в копилку не положен: нет файла ролика в батче')).toBe(
      'в копилку не положен: нет файла ролика в батче',
    );
  });

  it('новый ролик — в конец, ушедший — из порядка', () => {
    const v = (slug: string, at: string) =>
      ({ slug, batch_id: 'b', accepted_at: at }) as Parameters<typeof mergeOrder>[1][number];
    expect(
      mergeOrder(
        ['b/x', 'b/gone'],
        [v('y', '2026-10-01T00:00:00Z'), v('x', '2026-10-05T00:00:00Z')],
      ),
    ).toEqual(['b/x', 'b/y']);
    expect(
      videoHref({
        slug: 's',
        channel: 'c',
        batch_dir: 'pipeline/c/2026-10-09T0200Z',
      } as Parameters<typeof videoHref>[0]),
    ).toBe('/videos?batch=c%2F2026-10-09T0200Z&v=s');
  });
});

describe('CC-0122: копилка на «Публикации»', () => {
  it('ролики по дате принятия: устарел, карточка не готова, холд, превью и ссылка; не в копилке', async () => {
    const { stash } = await open();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    expect(within(stash).getByTestId('stash-channel')).toHaveTextContent('ExampleFilm');
    expect(
      screen.getByRole('heading', { name: /В копилке: 4 ролика · устарели: 1/ }),
    ).toBeInTheDocument();
    expect(slugs(stash)).toEqual([STASH_STALE, STASH_HELD, STASH_NOT_READY, STASH_BUILDING]);
    // CC-0128: настоящие названия карточек, без « #shorts» и без слага.
    expect(
      within(stash)
        .getAllByTestId('stash-title')
        .map((t) => t.textContent),
    ).toEqual([
      clean(STASH_STALE),
      clean(STASH_HELD),
      clean(STASH_NOT_READY),
      clean(STASH_BUILDING),
      clean(NOT_QUEUED),
    ]);
    expect(stash).not.toHaveTextContent('#shorts');
    const stale = rowOf(stash, STASH_STALE);
    expect(within(stale).getByTestId('stash-age')).toHaveAttribute('data-stale', '1');
    expect(within(stale).getByTestId('stash-age')).toHaveTextContent('устарел · новости 20 дн.');
    expect(within(stale).getByTestId('stash-accepted')).toHaveTextContent('принят 14 дней назад');
    expect(within(stale).getByTestId('stash-title')).toHaveAttribute(
      'href',
      `/videos?batch=${encodeURIComponent(`${REEL}/2026-09-24T0200Z`)}&v=${STASH_STALE}`,
    );
    expect(within(stale).getByTestId('stash-thumb')).toHaveAttribute(
      'src',
      `/api/batches/${REEL}/2026-09-24T0200Z/videos/${STASH_STALE}/preview`,
    );
    const notReady = rowOf(stash, STASH_NOT_READY);
    expect(within(notReady).getByTestId('stash-card')).toHaveTextContent('карточка не готова');
    expect(within(notReady).getByTestId('stash-card-why')).toHaveTextContent(
      'описание без источника факта',
    );
    expect(within(rowOf(stash, STASH_HELD)).getByTestId('stash-held')).toHaveTextContent('холд');
    const nq = within(stash).getByTestId('stash-not-queued-row');
    expect(nq).toHaveAttribute('data-slug', NOT_QUEUED);
    // Путь — только под «Подробнее».
    expect(within(nq).getByTestId('stash-not-queued-text')).not.toHaveTextContent('publish/');
    expect(within(nq).getByTestId('stash-not-queued-text')).toHaveTextContent(
      'Будет положен в копилку',
    );
    // «в копилке N» — у карточек каналов, из того же кэша.
    const reel = (await screen.findAllByTestId('stash-count')).find(
      (x) => x.dataset.channel === REEL,
    );
    expect(reel).toHaveTextContent('в копилке 4 · устарели: 1');
  });

  it('пустая копилка — одной строкой', async () => {
    const { stash } = await open(SCIENCE);
    expect(await within(stash).findByTestId('stash-empty')).toHaveTextContent('Копилка пуста');
    expect(within(stash).queryByTestId('stash-place-open')).toBeNull();
  });

  it('порядок ↑/↓ с клавиатуры, крайние кнопки погашены', async () => {
    const { user, stash } = await open();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    expect(within(rowsOf(stash)[0]!).getByTestId('stash-up')).toBeDisabled();
    expect(within(rowsOf(stash)[3]!).getByTestId('stash-down')).toBeDisabled();
    within(rowOf(stash, STASH_STALE)).getByTestId('stash-down').focus();
    await user.keyboard('{Enter}');
    expect(slugs(stash)).toEqual([STASH_HELD, STASH_STALE, STASH_NOT_READY, STASH_BUILDING]);
    // Фокус остался на кнопке сдвинутого ролика — можно жать дальше.
    expect(document.activeElement).toBe(
      within(rowOf(stash, STASH_STALE)).getByTestId('stash-down'),
    );
    await user.keyboard('{Enter}');
    expect(slugs(stash)).toEqual([STASH_HELD, STASH_NOT_READY, STASH_STALE, STASH_BUILDING]);
    expect(within(stash).getByTestId('stash-said')).toHaveTextContent('теперь 3-й из 4');
    await user.click(within(rowOf(stash, STASH_STALE)).getByRole('button', { name: /Выше/ }));
    expect(slugs(stash)).toEqual([STASH_HELD, STASH_STALE, STASH_NOT_READY, STASH_BUILDING]);
  });

  it('пачкой: отказ по ролику без «да» → убрать его → план по дням → «да» → разложено и закоммичено', async () => {
    const { user, stash } = await open();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    expect(within(stash).getByTestId('stash-place-open')).toHaveAttribute('aria-disabled', 'true');
    await user.click(within(rowOf(stash, STASH_STALE)).getByTestId('stash-pick'));
    await user.click(within(rowOf(stash, STASH_NOT_READY)).getByTestId('stash-pick'));
    expect(within(stash).getByTestId('stash-picked')).toHaveTextContent('Отмечено: 2 ролика');
    await user.click(within(stash).getByTestId('stash-place-open'));
    let dialog = await screen.findByRole('alertdialog');
    const items = await within(dialog).findAllByTestId('stash-plan-item');
    expect(items.map((i) => i.dataset.ok)).toEqual(['1', '0']);
    expect(items[0]).toHaveTextContent(`1. ${clean(STASH_STALE)}`);
    expect(items[1]).toHaveTextContent(`2. ${clean(STASH_NOT_READY)}`);
    expect(within(items[0]!).getByTestId('stash-plan-slot')).toHaveTextContent(/→ .+, 01:00/);
    expect(within(items[0]!).getByTestId('stash-plan-stale')).toHaveTextContent('устарел: 20 дн.');
    expect(within(items[1]!).getByTestId('stash-plan-refusal')).toHaveTextContent(
      'Карточка ролика не готова: описание без источника факта.',
    );
    // Код отказа — не на виду (только под «Подробнее»).
    expect(within(items[1]!).queryByText(/card_not_ready/)).toBeNull();
    expect(within(dialog).getByTestId('plan-why')).toHaveTextContent('Разложить можно 1 из 2');
    expect(within(dialog).getByTestId('stash-place-confirm')).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: /Отмена|Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());

    await user.click(within(rowOf(stash, STASH_NOT_READY)).getByTestId('stash-pick'));
    await user.click(within(stash).getByTestId('stash-place-open'));
    dialog = await screen.findByRole('alertdialog');
    const yes = within(dialog).getByTestId('stash-place-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(publish.stash.state.written).toEqual([]);
    await user.click(yes);
    const done = await within(stash).findByTestId('stash-done');
    expect(done).toHaveTextContent('Разложено: 1 ролик');
    // Название держится и после перечитывания: разложенного в копилке уже нет.
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(3));
    expect(within(done).getByTestId('stash-done-item')).toHaveTextContent(clean(STASH_STALE));
    expect(within(done).getByTestId('stash-done-item')).not.toHaveTextContent(STASH_STALE);
    expect(within(done).getByTestId('stash-done-commit')).toHaveTextContent(
      'Сохранено: 4 файла публикации',
    );
    expect(publish.stash.state.written).toEqual([
      { action: 'place', channel: REEL, order: [`2026-09-24T0200Z/${STASH_STALE}`] },
    ]);
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(3));
  });

  it('dirty — отказ строкой в плане; commit_refused — словами после «да»', async () => {
    const { user, stash } = await open();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    await user.click(within(stash).getByTestId('stash-pick-ready'));
    expect(within(stash).getByTestId('stash-picked')).toHaveTextContent('Отмечено: 1 ролик');
    publish.stash.state.next = 'dirty';
    await user.click(within(stash).getByTestId('stash-place-open'));
    let dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('stash-plan-refusals')).toHaveTextContent(
      'незакоммиченные правки',
    );
    expect(within(dialog).getByTestId('stash-place-confirm')).toBeDisabled();
    await user.click(within(dialog).getByRole('button', { name: /Отмена|Закрыть/ }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());

    await user.click(within(stash).getByTestId('stash-place-open'));
    dialog = await screen.findByRole('alertdialog');
    const yes = within(dialog).getByTestId('stash-place-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    publish.stash.state.next = 'commit_refused';
    await user.click(yes);
    const err = await within(dialog).findByTestId('act-error');
    expect(within(err).getByTestId('write-refusal-title')).toHaveTextContent(
      'Ролики разложены, но коммит не прошёл',
    );
    expect(within(err).queryByText(/^commit_refused$/)).toBeNull();
  });

  it('«Доложить в копилку…»: план → «да» → ролик в копилке', async () => {
    const { user, stash } = await open();
    const row = await within(stash).findByTestId('stash-not-queued-row');
    await user.click(within(row).getByTestId('stash-repair-open'));
    const dialog = await screen.findByRole('alertdialog');
    const items = await within(dialog).findByTestId('stash-repair-items');
    expect(items).toHaveTextContent(`${clean(NOT_QUEUED)}: Будет положен в копилку`);
    // CC-0128: путь строки фабрики — только под «Подробнее».
    expect(items).not.toHaveTextContent('publish/');
    const yes = within(dialog).getByTestId('stash-repair-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    expect(await within(stash).findByTestId('stash-repaired')).toHaveTextContent(
      'Положен в копилку',
    );
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(5));
    const said = within(stash).getByTestId('stash-repaired-item');
    expect(said).toHaveTextContent(`${clean(NOT_QUEUED)}: Положен в копилку`);
    expect(said).not.toHaveTextContent('publish/');
    expect(within(stash).queryByTestId('stash-not-queued')).toBeNull();
  });
});

describe('CC-0164: отметка переживает перечитанную копилку', () => {
  const picked = (stash: HTMLElement) =>
    rowsOf(stash)
      .filter((r) => within(r).getByTestId<HTMLInputElement>('stash-pick').checked)
      .map((r) => r.dataset.slug);

  it('тот же состав — отметка на месте; перечитать не вышло — ролики и отметка на месте', async () => {
    const { user, stash, reread } = await open();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    await user.click(within(rowOf(stash, STASH_NOT_READY)).getByTestId('stash-pick'));
    expect(within(stash).getByTestId('stash-picked')).toHaveTextContent('Отмечено: 1 ролик');

    const asked = publish.stash.state.calls.filter((c) => c.kind === 'get').length;
    await reread();
    await waitFor(() =>
      expect(publish.stash.state.calls.filter((c) => c.kind === 'get').length).toBeGreaterThan(
        asked,
      ),
    );
    expect(picked(stash)).toEqual([STASH_NOT_READY]);
    expect(within(stash).getByTestId('stash-picked')).toHaveTextContent('Отмечено: 1 ролик');

    // Опрос упал: прежний список остаётся на экране вместе с отметкой, рядом — что не перечитано.
    server.use(
      http.get(
        '*/api/publish/:channel/stash',
        () =>
          HttpResponse.json(
            { message: 'Копилка недоступна.', code: 'unknown_channel', details: [] },
            { status: 404 },
          ),
        { once: true },
      ),
    );
    await reread();
    expect(await within(stash).findByTestId('stash-stale-read')).toHaveTextContent(
      'Копилку не перечитать',
    );
    expect(rowsOf(stash)).toHaveLength(4);
    expect(picked(stash)).toEqual([STASH_NOT_READY]);

    await reread();
    await waitFor(() => expect(within(stash).queryByTestId('stash-stale-read')).toBeNull());
    expect(picked(stash)).toEqual([STASH_NOT_READY]);
    await user.click(within(stash).getByTestId('stash-place-open'));
    const dialog = await screen.findByRole('alertdialog');
    const items = await within(dialog).findAllByTestId('stash-plan-item');
    expect(items).toHaveLength(1);
    expect(items[0]).toHaveTextContent(clean(STASH_NOT_READY));
  });

  it('ролик ушёл из копилки — его отметка снята и не возвращается вместе с ним', async () => {
    const { user, stash, reread } = await open();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    await user.click(within(rowOf(stash, STASH_STALE)).getByTestId('stash-pick'));
    await user.click(within(rowOf(stash, STASH_NOT_READY)).getByTestId('stash-pick'));
    expect(within(stash).getByTestId('stash-picked')).toHaveTextContent('Отмечено: 2 ролика');

    const pile = publish.stash.state.piles.get(REEL)!;
    const gone = pile.videos.find((v) => v.slug === STASH_STALE)!;
    pile.videos = pile.videos.filter((v) => v !== gone);
    await reread();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(3));
    expect(picked(stash)).toEqual([STASH_NOT_READY]);
    expect(within(stash).getByTestId('stash-picked')).toHaveTextContent('Отмечено: 1 ролик');

    // Вернулся (например, снова положили в копилку) — уже без отметки.
    pile.videos = [...pile.videos, gone];
    await reread();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    expect(picked(stash)).toEqual([STASH_NOT_READY]);
    expect(within(stash).getByTestId('stash-picked')).toHaveTextContent('Отмечено: 1 ролик');
  });

  it('«Снять отметки» на месте и без отметок: «Разложить по слотам…» не сдвигается под щелчком', async () => {
    const { user, stash } = await open();
    await waitFor(() => expect(rowsOf(stash)).toHaveLength(4));
    const bar = within(stash).getByTestId('stash-bar');
    const order = () =>
      [...bar.querySelectorAll('[data-testid]')]
        .map((e) => (e as HTMLElement).dataset.testid)
        .filter((t) => t === 'stash-pick-none' || t === 'stash-place-open');
    expect(order()).toEqual(['stash-pick-none', 'stash-place-open']);
    expect(within(bar).getByTestId('stash-pick-none')).toBeDisabled();
    await user.click(within(rowOf(stash, STASH_STALE)).getByTestId('stash-pick'));
    expect(order()).toEqual(['stash-pick-none', 'stash-place-open']);
    expect(within(bar).getByTestId('stash-pick-none')).toBeEnabled();
  });
});
