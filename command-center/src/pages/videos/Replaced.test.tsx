// CC-0088: ролик, заменённый принятой пересборкой, решения не ждёт. Настоящий случай 12.10:
// первые версии rink-rivals и delver (example-film/2026-10-08T1824Z) без строки журнала,
// их пересборка rebuilds/2026-10-09T1208Z принята и залита.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { groupsOf, replacementOf, replacementsOf, waitingOf } from '@/api/videos';
import { PAST } from '@/mocks/batches';
import { publish, videos } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import {
  createVideosBackend,
  PAST_REDO,
  REPLACED_REDO,
  REPLACED_RUN,
  REPLACED_SRC,
  REPLACED_UPLOADS,
} from '@/mocks/videos';
import { renderApp } from '@/test/renderApp';

const listOf = (batch: string) => {
  const r = createVideosBackend().list(batch);
  if (r.status !== 200) throw new Error('нет батча');
  return r.body;
};

/** Батч REPLACED_SRC — последний в истории (как было у пользователя 12.10). */
const latestIsReplaced = () =>
  server.use(
    http.get('*/api/batches/history', () =>
      HttpResponse.json({ channel: null, runs: [REPLACED_RUN], launches: [] }),
    ),
  );

const uploadAll = () => {
  for (const u of REPLACED_UPLOADS) publish.addUpload('example-film', u);
};

describe('заменён пересборкой: разбор ответа', () => {
  it('первые версии без вердикта, чья пересборка принята, не ждут решения', () => {
    const list = listOf(REPLACED_SRC);
    const replaced = replacementsOf(list);
    expect([...replaced.keys()].sort()).toEqual(['delver', 'rink-rivals']);
    expect(replaced.get('delver')).toMatchObject({
      batch: REPLACED_REDO,
      batch_id: '2026-10-09T1208Z',
    });
    expect(replaced.get('delver')!.video.acceptance?.verdict).toBe('accepted');
    // vanguards-doomsday принят сам — он и так не ждёт; новых в батче, кроме двух, нет.
    expect(waitingOf(list)).toEqual([]);
  });

  it('пересборка без вердикта ролик не заменяет — он ждёт, как раньше', () => {
    const list = listOf(PAST);
    expect(replacementsOf(list).size).toBe(0);
    expect(waitingOf(list).map((v) => v.slug)).toEqual(['delver']);
  });

  it('отклонённая пересборка не заменяет; свой вердикт у первой версии — тоже нет', () => {
    const list = listOf(REPLACED_SRC);
    const g = groupsOf(list).find((x) => x.video.slug === 'delver')!;
    const rejected = {
      ...g,
      versions: g.versions.map((v) => ({
        ...v,
        video: { ...v.video, acceptance: { ...v.video.acceptance!, verdict: 'rejected' as const } },
      })),
    };
    expect(replacementOf(rejected)).toBeNull();
    const own = {
      ...g,
      video: { ...g.video, acceptance: { ...g.video.acceptance!, verdict: 'rejected' as const } },
    };
    expect(replacementOf(own)).toBeNull();
  });

  it('журнал не читается — про замену не говорим (и ожидание не считаем)', () => {
    const list = listOf(REPLACED_SRC);
    const g = groupsOf(list).find((x) => x.video.slug === 'delver')!;
    expect(replacementOf({ ...g, video: { ...g.video, acceptance: null } })).toBeNull();
  });
});

describe('заменён пересборкой: главная', () => {
  it('первая версия не в «Ждут вас» и не в «Ролики ждут решения»', async () => {
    latestIsReplaced();
    renderApp();
    await waitFor(() =>
      expect(screen.getByTestId('attention-text')).toHaveTextContent(
        'В последнем батче решения не ждёт ни один ролик.',
      ),
    );
    const card = screen.getByTestId('reels-card');
    expect(await within(card).findByTestId('reels-count')).toHaveTextContent(
      'В последнем батче решения не ждёт ни один ролик.',
    );
    expect(card).toHaveAttribute('data-waiting', '0');
    expect(within(card).queryAllByTestId('reels-item')).toHaveLength(0);
    expect(within(card).getByTestId('reels-replaced')).toHaveTextContent(
      'Заменены принятой пересборкой: 2',
    );
  });

  it('третий ролик без вердикта и без пересборки — в счёте один он', async () => {
    latestIsReplaced();
    videos.setAcceptance(REPLACED_SRC, 'vanguards-doomsday', {});
    renderApp();
    await waitFor(() =>
      expect(screen.getByTestId('attention-text')).toHaveTextContent(
        'Роликов без вердикта в последнем батче: 1.',
      ),
    );
    const items = within(screen.getByTestId('reels-card')).getAllByTestId('reels-item');
    expect(items.map((i) => i.dataset.slug)).toEqual(['vanguards-doomsday']);
  });
});

describe('заменён пересборкой: экран «Ролики»', () => {
  const at = (slug: string) =>
    `/videos?batch=${encodeURIComponent(REPLACED_SRC)}&v=${encodeURIComponent(slug)}`;

  it('плашка «заменён пересборкой», в заголовке не «ждут решения»', async () => {
    renderApp(`/videos?batch=${encodeURIComponent(REPLACED_SRC)}`);
    const reels = await screen.findByTestId('batch-videos');
    expect(await within(reels).findByRole('heading', { level: 2 })).toHaveTextContent(
      '3 ролика · заменены пересборкой: 2 · пересборок: 2',
    );
    const first = within(reels)
      .getAllByTestId('reel')
      .filter((r) => r.dataset.replaced === 'true');
    expect(first.map((r) => r.dataset.slug).sort()).toEqual(['delver', 'rink-rivals']);
    for (const r of first)
      expect(within(r).getByTestId('reel-state')).toHaveTextContent('заменён пересборкой');
  });

  it('«Заменён пересборкой … — принят, залит X66dFJ80XgA», ссылка на пересборку', async () => {
    uploadAll();
    renderApp(at('rink-rivals'));
    const notice = await screen.findByTestId('replaced');
    expect(notice).toHaveAttribute('data-rebuild', REPLACED_REDO);
    const line = within(notice).getByTestId('replaced-line');
    expect(line).toHaveTextContent(/^Заменён пересборкой 09\.10, 15:08 — принят/);
    // Залит — номер из ленты, а не другая загрузка rink-rivals (Qx7rT2mVb0c — не тот батч).
    expect(await within(notice).findByTestId('replaced-upload')).toHaveTextContent('X66dFJ80XgA');
    expect(line).toHaveTextContent('— принят, залит X66dFJ80XgA (публикация 13.10).');
    expect(within(notice).getByTestId('replaced-upload')).toHaveAttribute(
      'href',
      'https://youtube.com/shorts/X66dFJ80XgA',
    );
    expect(within(notice).getByTestId('replaced-link')).toHaveAttribute(
      'href',
      `${at('rink-rivals')}&at=${encodeURIComponent(REPLACED_REDO)}`,
    );
  });

  it('delver: загрузка своей пересборки, а не delver другой пересборки (rJSXkLVswSs)', async () => {
    uploadAll();
    renderApp(at('delver'));
    const notice = await screen.findByTestId('replaced');
    expect(await within(notice).findByTestId('replaced-upload')).toHaveTextContent('jHGkh2Zo0zw');
    expect(notice).not.toHaveTextContent('rJSXkLVswSs');
  });

  it('загрузки в ленте нет — «принят», без номера, и так и сказано', async () => {
    renderApp(at('delver'));
    const notice = await screen.findByTestId('replaced');
    expect(
      await within(notice).findByText(/в ленте публикации её загрузки пока не видно/),
    ).toBeInTheDocument();
    expect(within(notice).queryByTestId('replaced-upload')).toBeNull();
    // Другая загрузка delver (rebuilds/2026-10-05T1427Z) — не её: номер не подставлен.
    expect(notice).not.toHaveTextContent('rJSXkLVswSs');
  });

  it('вердикт не предлагается: кнопки — под «Всё равно дать вердикт» с предупреждением', async () => {
    renderApp(at('rink-rivals'));
    const acc = await screen.findByTestId('acceptance');
    expect(within(acc).getByTestId('acceptance-verdict')).toHaveTextContent('заменён пересборкой');
    expect(within(acc).getByTestId('acceptance-replaced')).toBeVisible();
    const anyway = within(acc).getByTestId('verdict-anyway');
    expect(anyway).not.toHaveAttribute('open');
    expect(within(acc).queryByRole('button', { name: /^Да/ })).not.toBeVisible();
    await userEvent.click(within(anyway).getByText('Всё равно дать вердикт этой версии'));
    expect(anyway).toHaveAttribute('open');
    expect(within(anyway).getByTestId('verdict-anyway-warning')).toHaveTextContent(
      'пересборку, её загрузку, слот и ротацию он не тронет',
    );
    expect(within(anyway).getByRole('button', { name: /^Да/ })).toBeVisible();
  });

  it('версия-пересборка — обычная приёмка, без плашки замены', async () => {
    renderApp(`${at('rink-rivals')}&at=${encodeURIComponent(REPLACED_REDO)}`);
    const acc = await screen.findByTestId('acceptance');
    expect(within(acc).getByTestId('acceptance-verdict')).toHaveTextContent('принят');
    expect(screen.queryByTestId('replaced')).toBeNull();
    expect(within(acc).queryByTestId('verdict-anyway')).toBeNull();
  });

  it('пересборка без вердикта (PAST) — ролик ждёт решения, как раньше', async () => {
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}&v=delver`);
    const acc = await screen.findByTestId('acceptance');
    expect(within(acc).getByTestId('acceptance-verdict')).toHaveTextContent('ждёт решения');
    expect(screen.queryByTestId('replaced')).toBeNull();
    expect(PAST_REDO).toBeTruthy();
  });
});
