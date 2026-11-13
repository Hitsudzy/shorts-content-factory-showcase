import { screen, within } from '@testing-library/react';

import { PAST } from '@/mocks/batches';
import { FUNNEL_REPAIRS } from '@/mocks/batchTopics';
import { videos } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const reelOf = async (slug: string) =>
  (await screen.findAllByTestId('reel')).find((r) => r.dataset.slug === slug)!;

describe('ролики батча: ремонт после судьи кадров (CC-0172)', () => {
  it('отремонтирован и не удался — под обложкой и в открытом ролике', async () => {
    videos.setRepair(PAST, 'vanguards-doomsday', FUNNEL_REPAIRS['vanguards-doomsday']!);
    videos.setRepair(PAST, 'delver', FUNNEL_REPAIRS.delver!);
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}&v=vanguards-doomsday`);
    const ok = within(await reelOf('vanguards-doomsday')).getByTestId('reel-repair');
    expect(ok).toHaveTextContent('Отремонтирован: блоки 5, 14 (полоса)');
    expect(ok).toHaveAttribute('data-outcome', 'repaired');
    expect(within(await reelOf('delver')).getByTestId('reel-repair')).toHaveTextContent(
      'Ремонт не удался — отказ (замены для блока 9 в пуле не нашлось)',
    );
    const detail = await screen.findByTestId('video-detail');
    expect(within(detail).getByTestId('video-repair')).toHaveTextContent(
      'Отремонтирован: блоки 5, 14 (полоса)',
    );
    // Коды ремонта — только под «подробнее».
    expect(within(detail).getByText('ремонт: repaired, монтаж: rendered')).not.toBeVisible();
  });

  it('ролик без ремонта (старый батч) — без строки', async () => {
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}&v=delver`);
    const reel = await reelOf('delver');
    expect(within(reel).queryByTestId('reel-repair')).not.toBeInTheDocument();
    expect(await screen.findByTestId('video-detail')).toBeInTheDocument();
    expect(screen.queryByTestId('video-repair')).not.toBeInTheDocument();
  });
});
