// Политика ленты 04.11 на экране (CC-0180): копилка делит новостные и бессрочные, показывает запас
// и горизонт, `news_why` как есть; авто-раскладка — план, порядок, пропущенные с причинами, `force`
// под «подробнее»; снятие в запас до «да» говорит про Studio; «Снято из ленты»; возврат на день —
// новой загрузки нет. Нигде не предлагается опубликовать сразу.
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { videoKeys } from '@/api/videos';
import { publish } from '@/mocks/handlers';
import { PLACED, REEL, REEL_BATCH } from '@/mocks/publish';
import {
  STASH_EVERGREEN,
  STASH_FRESH_NEWS,
  STASH_NO_CARD,
  STASH_RESERVE,
  STASH_STALE,
} from '@/mocks/stash';
import { renderApp } from '@/test/renderApp';

import { PlacePlan } from './CardWrites';
import { kindMarkLabel, RESERVE_WHY } from './stashWords';
import type { CardPlacePlan } from '@/api/publishWrites';

async function open() {
  const user = userEvent.setup();
  renderApp(`/publishing?channel=${REEL}`);
  const stash = await screen.findByTestId('stash');
  await within(stash).findByTestId('stash-list');
  const feed = await screen.findByTestId('slot-feed');
  await waitFor(() => expect(within(feed).getAllByTestId('slot-moves').length).toBeGreaterThan(0));
  return { user, stash, feed };
}

const rowOf = (root: HTMLElement, id: string, slug: string) =>
  within(root)
    .getAllByTestId(id)
    .find((r) => r.dataset.slug === slug)!;

const FORBIDDEN = /Опубликовать сейчас|Открытый доступ/;

describe('CC-0180: копилка', () => {
  it('без политики — как раньше: одна группа без заголовка и без строки политики', async () => {
    const { stash } = await open();
    expect(within(stash).queryByTestId('stash-policy')).toBeNull();
    expect(within(stash).queryByTestId('stash-group-head')).toBeNull();
    expect(within(stash).queryByTestId('stash-auto-more')).toBeNull();
  });

  it('новостные и бессрочные отдельно, запас и горизонт; `news_why` как есть, устаревшая помечена', async () => {
    publish.feedPolicy();
    const { stash } = await open();
    expect(await within(stash).findByTestId('stash-summary')).toHaveTextContent(
      'Новостных: 2 · бессрочных: 2 · в запасе: 1',
    );
    expect(within(stash).getByTestId('stash-horizon')).toHaveTextContent('Лента вперёд на 3 дня');
    expect(within(stash).getByTestId('stash-horizon')).toHaveTextContent('13.10');
    const groups = within(stash).getAllByTestId('stash-group');
    expect(groups.map((g) => g.dataset.kind)).toEqual(['news', 'evergreen']);
    const news = within(groups[0]!)
      .getAllByTestId('stash-row')
      .map((r) => r.dataset.slug);
    expect(news.sort()).toEqual([STASH_FRESH_NEWS, STASH_STALE].sort());

    const fresh = rowOf(stash, 'stash-row', STASH_FRESH_NEWS);
    expect(within(fresh).getByTestId('stash-news-why')).toHaveTextContent(
      '«трейлер выйдет в ноябре»',
    );
    expect(within(fresh).getByTestId('stash-stale-at')).toHaveTextContent('Устареет');
    expect(within(fresh).getByTestId('stash-news').dataset.stale).toBeUndefined();
    const old = rowOf(stash, 'stash-row', STASH_STALE);
    expect(within(old).getByTestId('stash-news').dataset.stale).toBe('1');
    // Один значок (возраст в строке выше) и дата, без повторов.
    expect(within(old).getByTestId('stash-age')).toHaveTextContent('устарел');
    expect(within(old).getByTestId('stash-stale-at')).toHaveTextContent('Срок вышел');
    expect(old).not.toHaveTextContent('устарела');
    expect(old).not.toHaveTextContent('Устарела');
    // Старые слова про датированный источник не возвращаются.
    expect(stash).not.toHaveTextContent('дата источника');

    const reserve = rowOf(stash, 'stash-row', STASH_RESERVE);
    expect(within(reserve).getByTestId('stash-reserve')).toHaveTextContent('в запасе');
    // Бессрочный ролик новостной строки не имеет.
    expect(
      within(rowOf(stash, 'stash-row', STASH_EVERGREEN)).queryByTestId('stash-news'),
    ).toBeNull();
  });

  it('батча ролика нет в списке (404 на оценку): строка на месте, только без значка оценки', async () => {
    const gone = `${REEL}/2020-01-01T0000Z`;
    publish.stash.receive(REEL, {
      slug: 'batch-gone',
      batch: gone.split('/')[1]!,
      title: 'Batch Gone #shorts',
      ready: true,
    });
    const { queryClient } = renderApp(`/publishing?channel=${REEL}`);
    const stash = await screen.findByTestId('stash');
    await within(stash).findByTestId('stash-list');
    await waitFor(() =>
      expect(queryClient.getQueryState(videoKeys.list(gone))?.status).toBe('error'),
    );
    const row = rowOf(stash, 'stash-row', 'batch-gone');
    expect(within(row).getByTestId('stash-title')).toHaveTextContent('Batch Gone');
    expect(within(stash).queryByTestId('stash-stale-read')).toBeNull();
    expect(screen.queryByText('Копилку не прочитать')).toBeNull();
  });

  it('↑/↓ — только внутри своей группы', async () => {
    publish.feedPolicy();
    const { stash } = await open();
    const groups = await within(stash).findAllByTestId('stash-group');
    const downs = within(groups[0]!).getAllByTestId('stash-down');
    expect(downs.at(-1)).toBeDisabled();
    expect(within(groups[1]!).getAllByTestId('stash-up')[0]).toBeDisabled();
  });

  it('авто-раскладка: порядок, пропущенные с причинами, одно «да» и итог', async () => {
    publish.feedPolicy({ noCard: true });
    const { user, stash } = await open();
    await user.click(within(stash).getByTestId('stash-auto-open'));
    const dialog = await screen.findByRole('alertdialog');
    await within(dialog).findByTestId('stash-plan-items');
    // Про порядок — одна фраза, в описании окна.
    expect(dialog.textContent!.match(/Порядок выб/g)).toHaveLength(1);
    expect(dialog).toHaveTextContent('сначала свежие новости');
    // Отсчёт на кнопке назван словами: это жизнь плана, а не время публикации.
    expect(within(dialog).getByTestId('stash-auto-confirm').textContent).toMatch(
      /^Разложить · план ещё \d:\d\d$/,
    );
    expect(
      within(dialog)
        .getAllByTestId('stash-plan-item')
        .map((i) => i.dataset.slug),
    ).toEqual([STASH_FRESH_NEWS]);
    const skipped = within(dialog).getAllByTestId('stash-plan-skip');
    const reason = (slug: string) => skipped.find((s) => s.dataset.slug === slug)!;
    expect(reason(STASH_STALE).dataset.reason).toBe('stale_news');
    expect(reason(STASH_STALE)).toHaveTextContent('Новость устарела, можно поставить вручную');
    expect(reason(STASH_STALE).textContent).not.toMatch(/force/);
    // Исходный текст фабрики и объяснение — под «Подробнее: устаревшие новости», свёрнуто.
    const staleMore = within(dialog).getByTestId('stash-plan-stale-more');
    expect(within(staleMore).getByText('Подробнее: устаревшие новости')).toBeInTheDocument();
    expect(staleMore.querySelector('details')!.open).toBe(false);
    expect(staleMore).toHaveTextContent('Обычно автоматика пропускает устаревшие новости');
    expect(staleMore).toHaveTextContent('force');
    expect(reason(STASH_NO_CARD).dataset.reason).toBe('no_card');
    expect(reason(STASH_NO_CARD)).toHaveTextContent('нет карточки');
    expect(reason(STASH_EVERGREEN).dataset.reason).toBe('beyond_horizon');
    expect(dialog).not.toHaveTextContent(FORBIDDEN);

    const before = publish.stash.state.calls.filter((c) => c.kind === 'plan').at(-1)!;
    expect(before.body).toEqual({ auto: true, force: false });
    await user.click(within(dialog).getByTestId('stash-auto-confirm'));
    const done = await within(stash).findByTestId('stash-done');
    expect(done).toHaveTextContent('Разложено автоматически');
    expect(within(done).getByTestId('stash-done-skipped')).toHaveTextContent('Ждёт в копилке');
  });

  it('`force` спрятан под «подробнее» и объяснён; с отметкой устаревшая новость в плане со словами', async () => {
    publish.feedPolicy({ days: 5 });
    const { user, stash } = await open();
    const more = within(stash).getByTestId('stash-auto-more');
    expect(more.querySelector('details')!.open).toBe(false);
    expect(more).toHaveTextContent('Брать и устаревшие новости');
    await user.click(within(more).getByText('Подробнее: устаревшие новости'));
    await user.click(within(more).getByTestId('stash-auto-force'));
    await user.click(within(stash).getByTestId('stash-auto-open'));
    const dialog = await screen.findByRole('alertdialog');
    const stale = rowOf(
      await within(dialog).findByTestId('stash-plan-items'),
      'stash-plan-item',
      STASH_STALE,
    );
    const line = within(stale).getByTestId('stash-plan-warning');
    expect(line.dataset.kind).toBe('stale');
    expect(line).toHaveTextContent('Новость устарела');
    expect(line.textContent).not.toMatch(/^STALE/);
    expect(publish.stash.state.calls.filter((c) => c.kind === 'plan').at(-1)!.body).toEqual({
      auto: true,
      force: true,
    });
  });

  it('нечего ставить: окно говорит это, «да» нет, можно разложить вручную', async () => {
    publish.feedPolicy({ days: 0 });
    const { user, stash } = await open();
    await user.click(within(stash).getByTestId('stash-auto-open'));
    const dialog = await screen.findByRole('alertdialog');
    const head = await within(dialog).findByTestId('plan-head');
    expect(head).toHaveTextContent('ставить нечего');
    expect(within(dialog).getByTestId('stash-plan-refusals')).toHaveTextContent('Ставить нечего');
    expect(within(dialog).getByTestId('stash-plan-refusals')).not.toHaveTextContent('skipped');
    expect(within(dialog).getByTestId('stash-auto-manual')).toHaveTextContent('вручную');
    expect(within(dialog).getByTestId('stash-auto-confirm')).toBeDisabled();
  });
});

describe('CC-0180: снять из ленты в запас', () => {
  it('до «да» окно говорит про Studio; строка фабрики — под «подробнее»; итог и «Снято из ленты»', async () => {
    publish.feedPolicy();
    const { user, feed } = await open();
    const row = rowOf(feed, 'slot', PLACED);
    await user.click(within(row).getByTestId('move-withdraw-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('withdraw-studio-first')).toHaveTextContent(
      'Сначала поставьте в Studio «Ограниченный доступ»',
    );
    const note = within(dialog).getByTestId('move-studio-withdraw');
    expect(note).toHaveTextContent('Центр Studio не проверяет');
    expect(note).toHaveTextContent('уберите дату вручную');
    const raw = within(note).getByTestId('move-studio-line');
    expect(raw).toHaveTextContent(/^STUDIO /);
    expect(raw.closest('details')!.open).toBe(false);
    expect(within(dialog).getByTestId('move-plan-where')).toHaveTextContent('→ в запас');
    expect(dialog).not.toHaveTextContent(FORBIDDEN);
    expect(publish.move.state.written).toHaveLength(0);

    await user.click(within(dialog).getByTestId('move-withdraw-confirm'));
    const done = await within(feed).findByTestId('move-done');
    expect(done).toHaveTextContent('Снято из ленты');
    expect(within(done).getByTestId('withdraw-studio-first')).toHaveTextContent('Проверьте Studio');
    expect(publish.move.state.written[0]).toMatchObject({ withdraw: [PLACED] });

    const list = await within(feed).findByTestId('feed-withdrawn');
    await waitFor(() =>
      expect(
        within(list)
          .getAllByTestId('feed-withdrawn-row')
          .map((r) => r.dataset.slug),
      ).toContain(PLACED),
    );
  });

  it('ролик не в Studio: снять нельзя, кнопка погашена', async () => {
    publish.feedPolicy({ days: 5 });
    publish.fillReelDays();
    const { feed } = await open();
    const notInStudio = within(feed)
      .getAllByTestId('slot')
      .find((r) => r.dataset.slug === 'filler-1')!;
    expect(within(notInStudio).getByTestId('move-withdraw-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });

  it('снятый ролик: день, что в Studio; ссылка на заметку с `_reserve`; день свободен сверх горизонта — не пропуск', async () => {
    publish.feedPolicy();
    const { feed } = await open();
    const row = rowOf(feed, 'feed-withdrawn-row', STASH_RESERVE);
    expect(within(row).getByTestId('feed-withdrawn-sub')).toHaveTextContent(
      'в Studio должно стоять: Ограниченный доступ',
    );
    expect(within(row).getByTestId('feed-withdrawn-title').getAttribute('href')).toContain(
      `slot=_reserve%2F${STASH_RESERVE}`,
    );
    // Ссылка на заметку — на виду у строки, рядом с YouTube, не под «Подробнее».
    const noteLink = within(row).getByTestId('feed-withdrawn-note');
    expect(noteLink).toHaveTextContent('Заметка ролика');
    expect(noteLink.getAttribute('href')).toContain(`slot=_reserve%2F${STASH_RESERVE}`);
    expect(noteLink.closest('details')).toBeNull();
    expect(within(row).getByTestId('feed-withdrawn-link').getAttribute('href')).toContain(
      'youtube.com',
    );
    const beyond = within(feed)
      .getAllByTestId('slot')
      .find((s) => s.dataset.day === '2026-10-20')!;
    expect(beyond.dataset.state).toBe('за горизонтом');
    expect(within(beyond).getByTestId('slot-sub')).toHaveTextContent('дальше горизонта');
    expect(within(feed).getByTestId('empty-days').dataset.count).toBe('1');
  });
});

describe('CC-0180: заметка запаса', () => {
  it('ссылка `slot=_reserve/<имя>` читает заметку с `day=_reserve`, опубликовать не предлагает', async () => {
    publish.feedPolicy();
    renderApp(`/publishing?channel=${REEL}&slot=_reserve/${STASH_RESERVE}`);
    await waitFor(() =>
      expect(
        publish.state.calls.some((c) => c.endsWith(`/notes/${STASH_RESERVE}?day=_reserve`)),
      ).toBe(true),
    );
    const fields = await screen.findAllByTestId('studio-value');
    expect(fields.some((f) => f.textContent?.includes('Sandfall Three'))).toBe(true);
    expect(document.body).not.toHaveTextContent(FORBIDDEN);
  });

  it('кнопок, что шлют `day=_reserve` в запись, нет: вместо них — куда идти', async () => {
    publish.feedPolicy();
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}&slot=_reserve/${STASH_RESERVE}`);
    expect(await screen.findByTestId('upload-reserve')).toHaveTextContent(RESERVE_WHY);
    const upload = screen.getByTestId('upload-writes');
    expect(within(upload).queryByTestId('upload-open')).toBeNull();
    expect(within(upload).queryByTestId('studio-record-toggle')).toBeNull();

    const card = screen.getByTestId('card-writes');
    expect(within(card).getByTestId('card-pick-reserve')).toHaveTextContent(RESERVE_WHY);
    expect(within(card).queryByTestId('card-pick-selected')).toBeNull();
    // `waiting` называет и ролик запаса — но разместить его отсюда нельзя.
    await within(await screen.findByTestId('stash')).findByTestId('stash-list');
    await waitFor(() =>
      expect(
        within(card)
          .queryAllByTestId('card-pick-waiting')
          .map((b) => b.dataset.slug),
      ).not.toContain(STASH_RESERVE),
    );

    // И вписанное руками имя: «Проверить и разместить» погашено с той же причиной.
    await user.click(within(card).getByTestId('card-place-toggle'));
    await user.type(within(card).getByTestId('card-batch'), REEL_BATCH);
    await user.type(within(card).getByTestId('card-slug'), STASH_RESERVE);
    const place = within(card).getByTestId('card-place-open');
    expect(place).toHaveAttribute('aria-disabled', 'true');
    await user.hover(place);
    expect((await screen.findAllByText(RESERVE_WHY)).length).toBeGreaterThan(1);
    await user.click(place);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(publish.writes.state.calls).toEqual([]);
  });

  it('ролик не из запаса: те же кнопки на месте', async () => {
    publish.feedPolicy();
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const upload = await screen.findByTestId('upload-writes');
    expect(await within(upload).findByTestId('upload-open')).toBeInTheDocument();
    expect(within(upload).getByTestId('studio-record-toggle')).toBeInTheDocument();
    expect(within(upload).queryByTestId('upload-reserve')).toBeNull();
    const card = screen.getByTestId('card-writes');
    expect(within(card).queryByTestId('card-pick-reserve')).toBeNull();
    await user.click(within(card).getByTestId('card-place-toggle'));
    await user.type(within(card).getByTestId('card-batch'), REEL_BATCH);
    await user.type(within(card).getByTestId('card-slug'), STASH_EVERGREEN);
    expect(within(card).getByTestId('card-place-open')).not.toHaveAttribute(
      'aria-disabled',
      'true',
    );
  });
});

describe('CC-0180: вид, поставленный вручную', () => {
  it('подпись у размеченного бессрочного; у ролика без пометки её нет', async () => {
    publish.feedPolicy();
    const { stash } = await open();
    await within(stash).findAllByTestId('stash-group');
    expect(
      within(rowOf(stash, 'stash-row', STASH_EVERGREEN)).getByTestId('stash-kind-mark'),
    ).toHaveTextContent('вид определён вручную');
    expect(
      within(rowOf(stash, 'stash-row', STASH_RESERVE)).queryByTestId('stash-kind-mark'),
    ).toBeNull();
  });

  it('у новости об этом уже говорит `news_why`: второй подписи нет', () => {
    const kind_mark = { kind: 'news' as const };
    expect(
      kindMarkLabel({ feed_kind: 'news', news_why: 'вид поставлен руками', kind_mark }),
    ).toBeNull();
    expect(kindMarkLabel({ feed_kind: 'news', news_why: null, kind_mark })?.tip).toContain(
      'новостной',
    );
    expect(kindMarkLabel({ feed_kind: 'evergreen', news_why: null, kind_mark: null })).toBeNull();
  });
});

describe('CC-0180: карточка и горизонт', () => {
  it('ближайший свободный слот за горизонтом: ролик остаётся в копилке, строка фабрики — под «подробнее»', () => {
    const plan = {
      ok: true,
      slot: {
        slot: null,
        day: null,
        line: null,
        note: 'beyond_horizon: the slot is past the horizon',
        beyond_horizon: true,
        warnings: [],
        moves: [],
      },
    } as unknown as CardPlacePlan;
    render(<PlacePlan plan={plan} />);
    expect(screen.getByTestId('place-where')).toHaveTextContent(
      'Ролик останется в копилке: ближайший свободный слот дальше горизонта ленты.',
    );
    expect(screen.getByText(/^beyond_horizon/).closest('details')).not.toBeNull();
  });
});

describe('CC-0180: возврат из запаса', () => {
  it('из «Снято из ленты»: новой загрузки нет, блок «Дату в Studio», запись переносом на день', async () => {
    publish.feedPolicy();
    const { user, feed } = await open();
    const row = rowOf(feed, 'feed-withdrawn-row', STASH_RESERVE);
    await user.click(within(row).getByTestId('reserve-return-toggle'));
    const form = within(row).getByTestId('reserve-return-form');
    expect(within(form).getByTestId('reserve-no-upload')).toHaveTextContent('Новой загрузки нет');
    // По умолчанию — свободный день в горизонте.
    expect(within(form).getByTestId('reserve-return-day')).toHaveValue('2026-10-13');
    await user.click(within(form).getByTestId('reserve-return-open'));
    const dialog = await screen.findByRole('alertdialog');
    const studio = await within(dialog).findByTestId('move-studio');
    expect(within(studio).getByTestId('move-studio-title')).toHaveTextContent(
      'Дату в Studio поставить вручную',
    );
    expect(within(studio).getByTestId('move-studio-item')).toHaveTextContent(
      'поставить «Отложенная публикация» на',
    );
    expect(within(studio).getByTestId('move-studio-no-upload')).toHaveTextContent(
      'новой загрузки нет',
    );
    expect(within(dialog).getByTestId('move-plan-where')).toHaveTextContent('из запаса →');
    expect(dialog).not.toHaveTextContent(FORBIDDEN);
    await user.click(within(dialog).getByTestId('reserve-return-confirm'));
    const done = await within(feed).findByTestId('move-done');
    expect(within(done).getByTestId('move-studio-title')).toHaveTextContent(
      'Теперь поставьте дату в Studio вручную',
    );
    await waitFor(() => expect(within(feed).queryByTestId('feed-withdrawn')).toBeNull());
  });

  it('день за горизонтом: подпись в выборе и слова HORIZON в плане, но не отказ', async () => {
    publish.feedPolicy();
    const { user, feed } = await open();
    const row = rowOf(feed, 'slot', PLACED);
    await user.click(within(row).getByTestId('move-open'));
    const select = within(row).getByTestId<HTMLSelectElement>('move-day');
    expect([...select.options].find((o) => o.value === '2026-10-20')!.textContent).toContain(
      'за горизонтом',
    );
    await user.selectOptions(select, '2026-10-20');
    expect(within(row).getByTestId('move-day-beyond')).toHaveTextContent('дальше горизонта');
    await user.click(within(row).getByTestId('move-one-open'));
    const dialog = await screen.findByRole('alertdialog');
    const line = await within(dialog).findByTestId('move-plan-warning');
    expect(line.dataset.kind).toBe('horizon');
    expect(line).toHaveTextContent('дальше горизонта ленты');
    expect(within(dialog).getByTestId('plan-head')).toHaveTextContent('можно перенести');
  });
});
