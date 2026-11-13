// CC-0128: «Публикация <дата>» в карточке ролика — только у загруженного или стоящего в слоте;
// ролик копилки — «в копилке — слота пока нет»; не разложенный — без строки (дата карточки
// батча старая и путает).
import { screen, within } from '@testing-library/react';

import { PAST } from '@/mocks/batches';
import { PLACED } from '@/mocks/publish';
import { NOT_QUEUED, STASH_HELD } from '@/mocks/stash';
import { NOT_QUEUED_BATCH, STASH_BATCH } from '@/mocks/videos';
import { renderApp } from '@/test/renderApp';

const videoUrl = (batch: string, slug: string) =>
  `/videos?batch=${encodeURIComponent(batch)}&v=${slug}`;

async function cardOf(batch: string, slug: string) {
  renderApp(videoUrl(batch, slug));
  const card = await screen.findByTestId('publish-card');
  await within(card).findByTestId('card-title');
  return card;
}

describe('CC-0128: «Публикация» в карточке ролика', () => {
  it('стоит в слоте ленты — дата публикации', async () => {
    const card = await cardOf(PAST, PLACED);
    const when = await within(card).findByTestId('card-publish');
    expect(when).toHaveTextContent('11.10');
    expect(when.querySelector('[data-where]')).toHaveAttribute('data-where', 'placed');
  });

  it('в копилке — «слота пока нет», не старая дата карточки', async () => {
    const card = await cardOf(STASH_BATCH, STASH_HELD);
    const when = await within(card).findByTestId('card-publish');
    expect(when).toHaveTextContent('в копилке — слота пока нет');
    expect(when).not.toHaveTextContent('11.10');
  });

  it('не в слоте и не в копилке — строки «Публикация» нет', async () => {
    const card = await cardOf(NOT_QUEUED_BATCH, NOT_QUEUED);
    // Очередь и копилка успели прочитаться (ролика в них нет) — строки так и не появилось.
    await screen.findByTestId('card-actions');
    await new Promise((r) => setTimeout(r, 200));
    expect(within(card).queryByTestId('card-publish')).toBeNull();
  });
});
