// CC-0187 (договор 0.79.0, фабрика CC-0186, CF-0921): «Не положены: похоже на другую версию» —
// только чтение: название, батч, причина словами, ссылка на уже размещённую версию или её имя и
// батч, пояснение «решает драйвер»; команды `repair` на экране нет (только под «Подробнее»), кнопок
// нет; пустой список — блока нет.
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { publish } from '@/mocks/handlers';
import {
  OTHER_BATCH,
  OTHER_TITLE,
  OTHER_UNLINKED,
  OTHER_UNLINKED_TITLE,
  PLACED,
  REEL,
} from '@/mocks/publish';
import { UNSURE_NO_FACT, UNSURE_NO_TOPIC, otherVersionText } from '@/mocks/stash';
import { renderApp } from '@/test/renderApp';

import { entryParts, otherVersionSlot, otherVersionWhy } from './stashWords';

describe('CC-0187: слова другой версии', () => {
  it('причина: `other_why` предложением, иначе `queue_text_ru` без записи, кода и команды', () => {
    expect(otherVersionWhy({ other_why: UNSURE_NO_TOPIC })).toBe(
      'Темы нет в записи — новый ролик от версии не отличить.',
    );
    expect(otherVersionWhy({ other_why: UNSURE_NO_FACT, queue_text_ru: 'x' })).toBe(
      'Факта нет в записи — новый ролик от версии не отличить.',
    );
    const entry = 'example-film/2026-10-09T0200Z/night-shift';
    const raw = otherVersionText(
      {
        slug: 'night-shift',
        batch: '2026-10-09T0200Z',
        title: '',
        accepted_at: '',
        other_entry: 'example-film/2026-09-30T0200Z/night-shift',
        other_path: null,
        other_why: null,
      },
      entry,
    );
    const words = otherVersionWhy({ other_why: null, queue_text_ru: raw });
    expect(words).toBe('Другая версия этого ролика уже размещена — эта в копилку не идёт.');
    expect(words).not.toMatch(/runlog|--|CF-|example-film/);
    expect(otherVersionWhy({})).toBe('Правило не отличило новый ролик от версии уже размещённого.');
  });

  it('куда вести: день ленты, копилка, запас, тёзка с батчем; чужой канал и другой путь — нет', () => {
    expect(otherVersionSlot('publish/example-film/2026-10-12/delver.mp4', 'example-film')).toEqual({
      slot: '2026-10-12/delver',
      batch: null,
      where: 'в ленте на 12.10',
    });
    expect(otherVersionSlot('publish/example-film/_queue/delver.mp4', 'example-film')).toMatchObject({
      slot: '_queue/delver',
      where: 'в копилке',
    });
    expect(
      otherVersionSlot('publish/example-film/_reserve/delver~2026-10-01T0200Z.mp4', 'example-film'),
    ).toEqual({ slot: '_reserve/delver', batch: '2026-10-01T0200Z', where: 'в запасе' });
    expect(otherVersionSlot('publish/example-tech/2026-10-12/delver.mp4', 'example-film')).toBeNull();
    expect(otherVersionSlot('publish/example-film/out/delver.mp4', 'example-film')).toBeNull();
    expect(otherVersionSlot(null, 'example-film')).toBeNull();
    expect(entryParts('example-film/2026-09-30T0200Z/night-shift')).toEqual({
      channel: 'example-film',
      batch: '2026-09-30T0200Z',
      slug: 'night-shift',
    });
    expect(entryParts('broken')).toBeNull();
  });
});

describe('CC-0187: блок в копилке', () => {
  it('пустой список — блока нет', async () => {
    renderApp(`/publishing?channel=${REEL}`);
    const stash = await screen.findByTestId('stash');
    await within(stash).findByTestId('stash-list');
    expect(within(stash).queryByTestId('stash-other-version')).not.toBeInTheDocument();
  });

  it('строки: название, батч, причина, ссылка или имя и батч; драйвер решает; без кнопок и команды', async () => {
    publish.otherVersion();
    const user = userEvent.setup();
    renderApp(`/publishing?channel=${REEL}`);
    const block = await screen.findByTestId('stash-other-version');
    expect(within(block).getByText('Не положены: похоже на другую версию')).toBeInTheDocument();
    expect(within(block).getByTestId('stash-other-note')).toHaveTextContent(
      'Решает драйвер фабрики, вам ничего делать не нужно.',
    );
    const rows = within(block).getAllByTestId('stash-other-row');
    expect(rows).toHaveLength(2);

    const [linked, unlinked] = rows as [HTMLElement, HTMLElement];
    expect(linked.dataset.slug).toBe(PLACED);
    expect(within(linked).getByTestId('stash-other-title')).toHaveTextContent(
      OTHER_TITLE.replace(' #shorts', ''),
    );
    expect(within(linked).getByTestId('stash-other-title')).toHaveAttribute(
      'href',
      `/videos?batch=${encodeURIComponent(`${REEL}/${OTHER_BATCH}`)}&v=${PLACED}`,
    );
    expect(linked).toHaveTextContent('батч от 9.10');
    expect(within(linked).getByTestId('stash-other-why')).toHaveTextContent(
      'Темы нет в записи — новый ролик от версии не отличить.',
    );
    const link = within(linked).getByTestId('stash-other-link');
    expect(link).toHaveTextContent('Delver, в ленте на');
    expect(link.getAttribute('href')).toMatch(
      new RegExp(`channel=${REEL}&slot=\\d{4}-\\d{2}-\\d{2}%2F${PLACED}$`),
    );

    expect(unlinked.dataset.slug).toBe(OTHER_UNLINKED);
    expect(within(unlinked).getByTestId('stash-other-title')).toHaveTextContent(
      OTHER_UNLINKED_TITLE.replace(' #shorts', ''),
    );
    expect(within(unlinked).getByTestId('stash-other-why')).toHaveTextContent(
      'Другая версия этого ролика уже размещена — эта в копилку не идёт.',
    );
    expect(within(unlinked).queryByTestId('stash-other-link')).not.toBeInTheDocument();
    expect(within(unlinked).getByTestId('stash-other-placed')).toHaveTextContent(
      'Уже размещена: Night shift, батч от 30.09',
    );

    // Только чтение: ни одной кнопки записи; команды на виду нет.
    for (const r of rows) expect(within(r).queryByRole('button')).not.toBeInTheDocument();
    for (const r of rows) expect(r).not.toHaveTextContent(/runlog|--other-version-ok/);
    const details = block.querySelector('details')!;
    expect(details).not.toHaveAttribute('open');
    // Под «Подробнее» (свёрнуто) — для драйвера, с командой.
    expect(details).toHaveTextContent('--other-version-ok');
    await user.click(within(block).getByText('Подробнее: для драйвера фабрики'));
    expect(details).toHaveAttribute('open');

    // Ссылка ведёт на слот размещённой версии: карточка Studio открывается.
    await user.click(link);
    expect(await screen.findByTestId('studio-card')).toBeInTheDocument();
  });
});
