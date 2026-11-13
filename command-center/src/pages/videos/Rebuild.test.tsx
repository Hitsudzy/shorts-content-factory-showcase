// CC-0063: «Пересобрать…» и сравнение версий — режимы, секунды → моменты, оставить/убрать
// исключения, rewrite без исключений, план → «да» только с токеном, итог; два плеера рядом.
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { PAST } from '@/mocks/batches';
import { videos } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

const at = (slug: string, extra = '') =>
  `/videos?batch=${encodeURIComponent(PAST)}&v=${slug}${extra}`;

async function prepare(seconds: string) {
  const user = userEvent.setup();
  renderApp(at('delver'));
  await user.click(await screen.findByTestId('rebuild-toggle'));
  const panel = await screen.findByTestId('rebuild');
  await within(panel).findAllByTestId('rebuild-mode-option');
  await user.type(within(panel).getByTestId('rebuild-seconds'), seconds);
  await user.click(within(panel).getByTestId('rebuild-find'));
  await within(panel).findByTestId('moments');
  return { user, panel };
}

describe('CC-0063: пересборка ролика', () => {
  it('секунды → моменты; снять исключение, взять соседний блок; план и «да» с токеном', async () => {
    const { user, panel } = await prepare('12 18 24');
    const moments = within(panel).getAllByTestId('moment');
    expect(moments.map((m) => m.dataset.block)).toEqual(['4', '7', '9']);
    await user.click(within(moments[1]!).getByTestId('moment-exclude'));
    await user.click(within(moments[0]!).getByTestId('moment-near'));
    expect(within(panel).getByTestId('rebuild-summary')).toHaveTextContent(
      'Уберём кадры: 4=wIM1PDRvKSE:32, 9=ZLXL1L0TfsI:19, 5=wIM1PDRvKSE:40',
    );
    await user.click(within(panel).getByTestId('rebuild-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('rebuild-reason')).toHaveTextContent(
      'Можно пересобрать',
    );
    expect(videos.rebuild.state.plans.at(-1)!.body).toMatchObject({
      videos: ['delver'],
      mode: 'reedit',
      notes: {
        videos: {
          delver: { exclude: ['4=wIM1PDRvKSE:32', '9=ZLXL1L0TfsI:19', '5=wIM1PDRvKSE:40'] },
        },
      },
    });
    const yes = within(dialog).getByTestId('rebuild-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    expect(yes).toHaveTextContent(/Пересобрать · \d:\d\d/);
    await user.click(yes);
    expect(await screen.findByTestId('rebuild-done')).toHaveTextContent('Пересборка запущена');
    expect(videos.rebuild.state.confirms.map((c) => c.body)).toEqual([{ confirm: 'rb-1' }]);
  });

  it('«Новый сценарий» исключений не берёт: объяснение, флажки погашены', async () => {
    const { user, panel } = await prepare('12');
    await user.click(within(panel).getAllByTestId('rebuild-mode-option')[1]!);
    expect(within(panel).getByTestId('no-exclude')).toHaveTextContent('Новый сценарий');
    expect(within(panel).getByTestId('moment-exclude')).toBeDisabled();
    expect(within(panel).getByTestId('rebuild-summary')).toHaveTextContent(
      'Без исключений кадров.',
    );
  });

  it('план упал — «Проверить заново» спрашивает план с тем же телом (CC-0069)', async () => {
    const { user, panel } = await prepare('18');
    // первый план — отказ фабрики без ответа как положено, дальше подставной API как есть
    server.use(
      http.post(
        '*/api/batches/:channel/:batch/rebuild/plan',
        () => HttpResponse.json({ detail: 'упало' }, { status: 500 }),
        { once: true },
      ),
    );
    await user.click(within(panel).getByTestId('rebuild-open'));
    const dialog = await screen.findByRole('alertdialog');
    const again = await within(dialog).findByTestId('replan');
    expect(videos.rebuild.state.plans).toHaveLength(0);
    await user.click(again);
    expect(await within(dialog).findByTestId('rebuild-reason')).toHaveTextContent(
      'Можно пересобрать',
    );
    expect(videos.rebuild.state.plans).toHaveLength(1);
    expect(videos.rebuild.state.plans[0]!.body).toMatchObject({ videos: ['delver'] });
    const yes = within(dialog).getByTestId('rebuild-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
  });

  it('старт не удался — «Продолжить в «Батчах»»', async () => {
    videos.rebuild.state.next = 'start_failed';
    const { user, panel } = await prepare('18');
    await user.click(within(panel).getByTestId('rebuild-open'));
    const dialog = await screen.findByRole('alertdialog');
    const yes = within(dialog).getByTestId('rebuild-confirm');
    await waitFor(() => expect(yes).toBeEnabled());
    await user.click(yes);
    const failed = await screen.findByTestId('rebuild-failed');
    expect(within(failed).getByTestId('rebuild-resume-link')).toHaveAttribute('href', '/batches');
  });
});

describe('CC-0063: сравнение версий', () => {
  it('две версии рядом; шаг кадра ставит обе на одно время', async () => {
    const user = userEvent.setup();
    renderApp(at('delver', '&cmp=1'));
    const panes = await screen.findAllByTestId('compare-pane');
    expect(panes.map((p) => p.dataset.batch)).toEqual([PAST, 'rebuilds/2026-10-09T1500Z']);
    const vids = screen.getAllByTestId('compare-video') as HTMLVideoElement[];
    for (const v of vids) {
      Object.defineProperty(v, 'duration', { configurable: true, value: 3 });
      v.pause = () => {};
      fireEvent.loadedMetadata(v);
    }
    expect(screen.getAllByTestId('compare-frame')[0]).toHaveTextContent('кадр 1 из 90');
    await user.click(screen.getByTestId('compare-next'));
    expect(vids.map((v) => v.currentTime.toFixed(4))).toEqual([
      (1.5 / 30).toFixed(4),
      (1.5 / 30).toFixed(4),
    ]);
    expect(screen.queryByTestId('player')).toBeNull();
  });
});
