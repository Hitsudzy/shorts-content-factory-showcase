import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Video } from '@/api/videos';
import { DEFAULT_FPS, fpsOf, groupsOf, posterOf } from '@/api/videos';
import { PAST } from '@/mocks/batches';
import { videos } from '@/mocks/handlers';
import { createVideosBackend, OLDER, PAST_REDO, routeVideos } from '@/mocks/videos';
import { renderApp } from '@/test/renderApp';

import { acceptanceView, frameAt, frameLabel, stepTime, timecode, timecodeFine } from './format';

const listOf = (batch: string) => {
  const r = createVideosBackend().list(batch);
  if (r.status !== 200) throw new Error('нет батча');
  return r.body;
};

describe('ролики: разбор ответа', () => {
  it('обложка: кадр как есть, лист — с сеткой (по умолчанию 3×2), нет — с причиной', () => {
    const [delver, rivalry, vanguards] = listOf(PAST).videos as [Video, Video, Video];
    expect(posterOf(rivalry.preview)).toEqual({ kind: 'frame', url: rivalry.preview.url });
    expect(posterOf(delver.preview)).toMatchObject({ kind: 'sheet', columns: 3, rows: 2 });
    expect(posterOf({ ...delver.preview, grid: null })).toMatchObject({ columns: 3, rows: 2 });
    expect(posterOf({ ...delver.preview, grid: { columns: 4, rows: 1 } })).toMatchObject({
      columns: 4,
      rows: 1,
    });
    expect(posterOf(vanguards.preview)).toEqual({
      kind: 'none',
      reason: vanguards.preview.reason,
    });
  });

  it('версии: пересборка — рядом со своим роликом (rebuilt_in → rebuilds[])', () => {
    const groups = groupsOf(listOf(PAST));
    expect(groups.map((g) => [g.video.slug, g.versions.map((v) => v.batch)])).toEqual([
      ['delver', [PAST_REDO]],
      ['rink-rivals', []],
      ['vanguards-doomsday', []],
    ]);
    expect(groupsOf(listOf(OLDER)).every((g) => g.versions.length === 1)).toBe(true);
  });

  it('кадров в секунду: из карточки, иначе 30', () => {
    expect(fpsOf(null, null)).toBe(DEFAULT_FPS);
    expect(fpsOf({ mark: { fps: 25 } } as never)).toBe(25);
    expect(fpsOf({ mark: { fps: 'x' } } as never)).toBe(30);
  });

  it('шаг кадра: середина соседнего кадра, в пределах ролика', () => {
    expect(stepTime(1, 1, 30, 3)).toBeCloseTo(31.5 / 30);
    expect(stepTime(31.5 / 30, -1, 30, 3)).toBeCloseTo(30.5 / 30);
    expect(stepTime(0, -1, 30, 3)).toBeCloseTo(0.5 / 30);
    expect(stepTime(2.99, 5, 30, 3)).toBeCloseTo(89.5 / 30);
    expect(stepTime(1, 1, 25, 0)).toBeCloseTo(26.5 / 25);
    expect(frameAt(31.5 / 30, 30)).toBe(32);
    expect(frameAt(0, 30)).toBe(1);
    expect(frameLabel(31.5 / 30, 30, 3, null)).toBe('кадр 32 из 90');
    expect(frameLabel(31.5 / 30, 30, null, 41.2)).toBe('кадр 32 из ≈1236');
    expect(frameLabel(0, 30, null, null)).toBe('кадр 1');
    expect(timecode(44.9)).toBe('0:44');
    expect(timecode(null)).toBe('—');
    expect(timecodeFine(72.054)).toBe('1:12.05');
  });

  it('приёмка словами: нет вердикта, принят, холд, переделка в очереди, журнал не читается', () => {
    const [delver, rivalry, vanguards] = listOf(PAST).videos as [Video, Video, Video];
    expect(acceptanceView(delver.acceptance)).toMatchObject({
      label: 'ждёт решения',
      decided: false,
    });
    expect(acceptanceView(rivalry.acceptance)).toMatchObject({ label: 'принят', tone: 'ok' });
    expect(acceptanceView({ ...rivalry.acceptance!, held: true }).label).toBe('принят · холд');
    expect(acceptanceView(vanguards.acceptance)).toMatchObject({
      label: 'на переделку · ждёт конца батча',
      pending: true,
    });
    expect(acceptanceView({ ...vanguards.acceptance!, note: null, pending: false }).label).toBe(
      'отклонён',
    );
    expect(acceptanceView(null).label).toBe('журнал не читается');
  });

  it('мок: список, карточка, mp4 с Range, превью кадр/лист, отказы; запись — не его', () => {
    const b = createVideosBackend();
    const get = (path: string, range?: string) =>
      routeVideos(b, 'GET', new URL(`http://x${path}`), { range });
    expect(get(`/api/batches/${PAST}/videos`)).toMatchObject({ status: 200 });
    expect(get(`/api/batches/${PAST}/videos/delver/card`)).toMatchObject({ status: 200 });
    expect(get(`/api/batches/${OLDER}/videos/usb-c-myths/card`)).toMatchObject({
      status: 404,
      body: { code: 'no_card' },
    });
    expect(get(`/api/batches/${PAST}/videos/delver/mp4`, 'bytes=0-')).toMatchObject({
      file: 'clip.mp4',
    });
    expect(b.mp4Calls).toEqual(['bytes=0-']);
    expect(get(`/api/batches/${PAST}/videos/delver/preview`)).toMatchObject({ file: 'sheet.png' });
    expect(get(`/api/batches/${PAST}/videos/rink-rivals/preview`)).toMatchObject({
      file: 'frame.jpg',
    });
    expect(get(`/api/batches/${PAST}/videos/vanguards-doomsday/preview`)).toMatchObject({
      status: 404,
      body: { code: 'no_preview' },
    });
    expect(get('/api/batches/x/y/videos')).toMatchObject({
      status: 404,
      body: { code: 'unknown_batch' },
    });
    expect(get(`/api/batches/${PAST}/videos/nope/mp4`)).toMatchObject({ status: 404 });
    expect(
      routeVideos(b, 'GET', new URL(`http://x/api/batches/${PAST}/videos/delver/acceptance`)),
    ).toBeNull();
    expect(routeVideos(b, 'GET', new URL(`http://x/api/batches/${PAST}`))).toBeNull();
    b.setAcceptance(PAST, 'delver', { verdict: 'accepted', pending: true });
    const after = get(`/api/batches/${PAST}/videos`) as { body: { videos: Video[] } };
    expect(after.body.videos[0]!.acceptance).toMatchObject({ verdict: 'accepted', pending: true });
  });
});

describe('«Ролики»: экран', () => {
  it('таб открывает экран (не «скоро»), по умолчанию — последний батч, пересборка рядом', async () => {
    renderApp('/videos');
    expect(await screen.findByRole('heading', { name: 'Ролики', level: 1 })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Ролики' })).toHaveAttribute('aria-current', 'page');
    const reels = await screen.findByTestId('reels');
    expect(screen.getByTestId('batch-picker')).toHaveValue(PAST);
    const items = within(reels).getAllByRole('listitem');
    expect(items.map((li) => `${li.dataset.testid}:${li.dataset.slug}`)).toEqual([
      'reel:delver',
      'reel-version:delver',
      'reel:rink-rivals',
      'reel:vanguards-doomsday',
    ]);
    expect(items[3]).toHaveTextContent('ждёт конца батча');
    expect(screen.queryByText(/Скоро · версия/)).toBeNull();
  });

  it('ролик: плеер, шаг кадра и клавиши, карточка с «подробнее», приёмка без кнопок', async () => {
    const user = userEvent.setup();
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}&v=delver`);
    const player = await screen.findByTestId('player');
    const video = screen.getByTestId('player-video') as HTMLVideoElement;
    // jsdom видео не играет: длительность и время задаём сами.
    Object.defineProperty(video, 'duration', { configurable: true, value: 3 });
    Object.defineProperty(video, 'paused', { configurable: true, get: () => true });
    video.pause = () => {};
    // До метаданных файла — длительность списка «примерно»; после — счёт по файлу.
    expect(screen.getByTestId('player-frame')).toHaveTextContent('кадр 1 из ≈1347 · 30 к/с');
    expect(screen.getByTestId('player-frame')).toHaveAttribute('data-meta', '0');
    fireEvent.loadedMetadata(video);
    expect(screen.getByTestId('player-frame')).toHaveTextContent('кадр 1 из 90 · 30 к/с');
    expect(screen.getByTestId('player-frame')).toHaveAttribute('data-meta', '1');

    await user.click(screen.getByTestId('player-next'));
    expect(video.currentTime).toBeCloseTo(1.5 / 30);
    player.focus();
    await user.keyboard('..');
    expect(video.currentTime).toBeCloseTo(3.5 / 30);
    await user.keyboard(',');
    expect(video.currentTime).toBeCloseTo(2.5 / 30);
    await user.keyboard('{ArrowRight}');
    expect(video.currentTime).toBeCloseTo(2.5 / 30 + 1);
    expect(screen.getByTestId('player-frame')).toHaveTextContent('кадр 33 из 90');
    // Лист судьи — плиткой поверх видео, пока ролик не трогали; после шага — нет.
    expect(within(player).queryByTestId('poster-sheet')).toBeNull();

    const card = screen.getByTestId('publish-card');
    expect(await within(card).findByTestId('card-title')).toHaveTextContent('one-take mine scene');
    const raw = within(card).getByTestId('card-raw');
    expect(raw.closest('details')!.open).toBe(false);
    expect(raw).toHaveTextContent('## Название');

    const acc = screen.getByTestId('acceptance');
    expect(within(acc).getByTestId('acceptance-verdict')).toHaveTextContent('ждёт решения');
    expect(
      within(within(acc).getByRole('group', { name: 'Ваше решение по ролику' })).getAllByRole(
        'button',
      ),
    ).toHaveLength(3);
  });

  it('вердикт в очереди под батчем: «записано, ждёт конца батча»; выбор батча меняет адрес', async () => {
    videos.setAcceptance(PAST, 'rink-rivals', {
      verdict: 'accepted',
      answer: 'rink-rivals — да',
      pending: true,
      queued_at: '2026-10-10T06:00:00Z',
    });
    const user = userEvent.setup();
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}&v=rink-rivals`);
    expect(await screen.findByTestId('acceptance-pending')).toHaveTextContent(
      'Записано, ждёт конца батча — в очереди с 10.10',
    );
    expect(screen.getByTestId('acceptance-words')).toHaveTextContent(
      '«Rink Rivals: the casting call that broke the fandom — да»',
    );
    await user.selectOptions(screen.getByTestId('batch-picker'), OLDER);
    await waitFor(() =>
      expect(screen.getByTestId('batch-videos')).toHaveAttribute('data-batch', OLDER),
    );
    expect(screen.queryByTestId('video-detail')).toBeNull();
  });
});
