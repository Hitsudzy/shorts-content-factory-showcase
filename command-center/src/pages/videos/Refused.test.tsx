// CC-0116: ролик, отказанный после монтажа (Science 2001Z, sophie-adenot — 24 из 40), виден в
// списке батча с причиной словами, открывается с плеером (если файл есть), без вердикта и с
// «Пересобрать…» (план → «да»); в окне пересборки — что исходный ролик отказан и почему;
// 409 `video_refused` на вердикт — простыми словами.
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import type { BatchVideos, Video, VideoRefusal } from '@/api/videos';
import { awaitsVerdict, readableSlug, replacementsOf, videoTitle, waitingOf } from '@/api/videos';
import { videos } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { ADENOT_SCORE_LINE, createVideosBackend, SCIENCE } from '@/mocks/videos';
import { renderApp } from '@/test/renderApp';

import {
  noPaths,
  penaltiesOf,
  reasonLeftOut,
  refusalKind,
  refusalLine,
  refusalSentence,
  scoreLogLines,
  VIDEO_REFUSED_TEXT,
} from './refusal';

const at = (slug?: string) =>
  `/videos?batch=${encodeURIComponent(SCIENCE)}${slug ? `&v=${slug}` : ''}`;

const listOf = () => {
  const r = createVideosBackend().list(SCIENCE);
  if (r.status !== 200) throw new Error('нет батча');
  return r.body;
};

const REDO = 'rebuilds/2026-10-13T1000Z';
/** Science 2001Z, где пересборку sophie-adenot вы приняли. */
function withAcceptedRedo(): BatchVideos {
  const list = structuredClone(listOf());
  const adenot = list.videos.find((v) => v.slug === 'sophie-adenot')!;
  adenot.rebuilt_in = [REDO];
  const again: Video = { ...adenot, refused: null };
  list.rebuilds = [
    {
      batch: REDO,
      batch_id: '2026-10-13T1000Z',
      dir: `pipeline/${REDO}`,
      editor_error: null,
      videos: [
        {
          ...again,
          rebuilt_in: [],
          qc_passed: true,
          score_line: 'B · 71 — хук держит',
          acceptance: {
            ...adenot.acceptance!,
            recorded: true,
            verdict: 'accepted',
            accepted: true,
            answer: 'sophie-adenot — да',
            answered_at: '2026-10-13',
            recorded_at: '2026-10-13T12:00:00Z',
          },
        },
      ],
    },
  ];
  return list;
}

const LINE = 'оценка ниже порога после штрафов: 24 из 40 — зависший кадр (1 блок, хук)';

describe('CC-0116: слова отказа', () => {
  it('настоящая строка sophie-adenot: порог из `score`, пояснение — самый большой штраф', () => {
    const [, adenot, dots] = listOf().videos as [Video, Video, Video];
    expect(adenot.refused!.score_line).toBe(ADENOT_SCORE_LINE);
    expect(refusalLine(adenot.refused!)).toBe(LINE);
    expect(refusalSentence(adenot.refused!)).toMatch(/^Оценка ниже порога после штрафов: 24 из 40/);
    // Запятая в скобках («(1 блок, хук)») штраф не делит.
    expect(penaltiesOf(adenot.refused!).map((p) => p.price)).toEqual([6, 3, 4, 1, 62]);
    // Английская строка монтажа не попадает в слова — она под «подробнее».
    expect(reasonLeftOut(adenot.refused!)).toBe('SCORE UNDER THE THRESHOLD after qc: 24 < 40');
    expect(refusalLine(dots.refused!)).toBe('всё из одного источника');
    expect(reasonLeftOut(dots.refused!)).toMatch(/^fact 2 has a single source/);
  });

  it('слова отказа — строка фабрики `reason_ru`; без неё — общая строка, без догадок по коду', () => {
    const r = (x: Partial<VideoRefusal>): VideoRefusal => ({
      reason_code: null,
      gate: null,
      score_line: null,
      score: null,
      reason: null,
      ...x,
    });
    expect(
      refusalKind(r({ reason_code: 'score_below_threshold', reason_ru: 'оценка ниже порога' })),
    ).toBe('оценка ниже порога');
    // CC-0113: своей карты кодов нет — код без строки фабрики даёт общую строку.
    expect(refusalKind(r({ gate: 'score_below_threshold' }))).toBe(
      'не прошёл проверку после монтажа',
    );
    expect(refusalKind('no_second_source')).toBe('не прошёл проверку после монтажа');
    expect(refusalKind(r({ reason_code: 'frame_judge_reject', gate: 'frame-judge' }))).toBe(
      'не прошёл проверку после монтажа',
    );
    expect(refusalLine(r({ score_line: 'F · 31' }))).toBe(
      'не прошёл проверку после монтажа: оценка 31',
    );
    // Строка оценки без штрафов — её хвост целиком, слова фабрики.
    expect(
      refusalLine(
        r({
          reason_code: 'score_below_threshold',
          reason_ru: 'оценка ниже порога после штрафов',
          score_line: 'F · 31 — хук слабый',
        }),
      ),
    ).toBe('оценка ниже порога после штрафов: оценка 31 — хук слабый');
  });

  it('журнал оценки без абсолютных путей: `where.shot` — имя файла, путь в `note` убран', () => {
    const [, adenot] = listOf().videos as [Video, Video];
    const lines = scoreLogLines(adenot.refused!);
    expect(lines).toHaveLength(5);
    expect(lines.join('\n')).not.toMatch(/\/Users|\/pool\//);
    expect(lines[2]).toBe(
      '-4 · score.resolution · shot a06_esa-adenot-training.mp4: source 640x360 under 1080p',
    );
    expect(lines[1]).toBe('-3 · score.framing · shot a03_iss-cupola.mp4: subject off-center:');
    expect(lines[4]).toBe(
      '-62 · score.frozen_block · хук: clip block rendered as a still (qc_render frozen_blocks)',
    );
    expect(noPaths('/home/x/clips/a.mp4')).toBe('');
  });

  it('отказанный решения не ждёт: не считается в «ждут решения»', () => {
    const list = listOf();
    expect(list.videos.filter(awaitsVerdict).map((v) => v.slug)).toEqual(['mars-sample-return']);
    expect(waitingOf(list).map((v) => v.slug)).toEqual(['mars-sample-return']);
  });

  it('отказанный, чью пересборку приняли, — заменён пересборкой (CC-0088)', () => {
    expect([...replacementsOf(withAcceptedRedo()).keys()]).toEqual(['sophie-adenot']);
    expect(replacementsOf(listOf()).size).toBe(0);
  });
});

describe('CC-0116: экран «Ролики»', () => {
  it('в списке — плашка и причина словами, счётчик отказанных; коды не видны', async () => {
    renderApp(at());
    const reels = await screen.findAllByTestId('reel');
    const adenot = reels.find((r) => r.dataset.slug === 'sophie-adenot')!;
    expect(adenot.dataset.refused).toBe('true');
    expect(within(adenot).getByTestId('reel-state')).toHaveTextContent('отказан после монтажа');
    expect(within(adenot).getByTestId('reel-state')).not.toHaveTextContent('не прошёл проверку');
    expect(within(adenot).getByTestId('reel-refused')).toHaveTextContent(
      'Оценка ниже порога после штрафов: 24 из 40 — зависший кадр (1 блок, хук)',
    );
    expect(screen.getByTestId('batch-videos')).toHaveTextContent(
      '3 ролика · ждут решения: 1 · отказаны после монтажа: 2',
    );
    expect(screen.queryByText(/score_below_threshold/)).not.toBeInTheDocument();
  });

  it('открытый: плеер, причина, «Пересобрать…», без вердикта; коды — под «подробнее»', async () => {
    const user = userEvent.setup();
    renderApp(at('sophie-adenot'));
    const detail = await screen.findByTestId('video-detail');
    expect(detail.querySelector('video')).not.toBeNull();
    const card = within(detail).getByTestId('refused');
    expect(within(card).getByTestId('refused-reason')).toHaveTextContent(
      'Оценка ниже порога после штрафов: 24 из 40 — зависший кадр (1 блок, хук).',
    );
    expect(within(card).getByTestId('refused-penalties')).toHaveTextContent(
      '−62 зависший кадр (1 блок, хук)',
    );
    // «Пересобрать…» — одна, в карточке отказа.
    expect(within(detail).getAllByRole('button', { name: 'Пересобрать…' })).toHaveLength(1);
    expect(within(detail).queryByTestId('rebuild-toggle')).not.toBeInTheDocument();
    expect(within(detail).queryByTestId('acceptance')).not.toBeInTheDocument();
    expect(within(detail).queryByTestId('verdict-yes')).not.toBeInTheDocument();
    expect(within(detail).queryByTestId('verdict-no')).not.toBeInTheDocument();
    const more = within(card).getByText('Подробнее').closest('details')!;
    expect(more).toHaveTextContent('код причины: score_below_threshold');
    expect(more).toHaveTextContent('проверка: score_below_threshold');
    expect(more).toHaveTextContent('shot a06_esa-adenot-training.mp4');
    expect(detail.textContent).not.toMatch(/\/Users\//);

    await user.click(within(card).getByTestId('refused-rebuild'));
    const panel = await screen.findByTestId('rebuild');
    expect(within(panel).getByTestId('rebuild-refused-reason')).toHaveTextContent(LINE);
    expect(within(panel).queryByTestId('rebuild-no-plan')).not.toBeInTheDocument();
    await within(panel).findAllByTestId('rebuild-mode-option');
    await user.click(within(panel).getByTestId('rebuild-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('rebuild-reason')).toHaveTextContent(
      'Можно пересобрать',
    );
    expect(within(dialog).getByTestId('plan-refused')).toHaveTextContent(
      'отказан после монтажа' + LINE,
    );
    // Строка фабрики («Можно пересобрать: sophie-adenot — …, с шага «video-editor»») — только
    // под «подробнее»; в основном виде — название ролика и стадия по-русски.
    const plan = within(dialog).getByTestId('rebuild-plan');
    expect(within(dialog).getByTestId('rebuild-reason').closest('details')).not.toBeNull();
    expect(within(plan).getByTestId('rebuild-mode')).toHaveTextContent('с шага «Монтаж»');
    expect(within(plan).getByTestId('rebuild-video')).toHaveTextContent(
      /^Sophie Adenot: the second French woman heading to space/,
    );
    const shown = [...plan.children].filter((el) => el.tagName !== 'DETAILS');
    expect(shown.map((el) => el.textContent).join(' ')).not.toMatch(/sophie-adenot|video-editor/);
    expect(within(plan).getByTestId('layout-skipped')).toHaveTextContent(/^на приёмку$/);
    expect(videos.rebuild.state.plans.at(-1)!.body).toMatchObject({
      videos: ['sophie-adenot'],
      mode: 'reedit',
    });
    await user.click(within(dialog).getByTestId('rebuild-confirm'));
    expect(await screen.findByTestId('rebuild-done-reason')).toHaveTextContent('запущена');
    expect(videos.accepted).toEqual([]);
  });

  it('без файла: «Файла ролика нет», превью нет; в пересборке — плана монтажа нет', async () => {
    const user = userEvent.setup();
    renderApp(at('jwst-little-red-dots'));
    const detail = await screen.findByTestId('video-detail');
    expect(detail.querySelector('video')).toBeNull();
    expect(within(detail).getByText('Файла ролика нет')).toBeInTheDocument();
    expect(within(detail).getByTestId('refused-reason')).toHaveTextContent(
      'Всё из одного источника.',
    );
    await user.click(within(detail).getByTestId('refused-rebuild'));
    const panel = await screen.findByTestId('rebuild');
    expect(await within(panel).findByTestId('rebuild-no-plan')).toHaveTextContent(
      'Плана монтажа у ролика нет',
    );
    // Отказ плана — строкой фабрики, но с названием ролика; сама строка — под «подробнее».
    await user.click(within(panel).getByTestId('rebuild-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('rebuild-reason')).toHaveTextContent(
      'У ролика «The little red dots: what JWST found at the edge of time» нет плана монтажа',
    );
    expect(within(dialog).getByTestId('rebuild-reason-raw')).toHaveTextContent(
      '«jwst-little-red-dots»',
    );
  });

  it('без названия карточки — имя ролика словами, а не через дефисы', () => {
    expect(readableSlug('jwst-little-red-dots')).toBe('Jwst little red dots');
    expect(videoTitle({ slug: 'mars_sample-return', card: { title: null } as never })).toBe(
      'Mars sample return',
    );
    expect(videoTitle({ slug: 'x', card: { title: 'Своё название' } as never })).toBe(
      'Своё название',
    );
    // CC-0128: для показа — без хвоста хэштегов карточки.
    expect(
      videoTitle({ slug: 'x', card: { title: 'Skyman Sequel #shorts #кино' } as never }),
    ).toBe('Skyman Sequel');
    expect(videoTitle({ slug: 'only-tags', card: { title: '#shorts' } as never })).toBe('#shorts');
  });

  it('409 `video_refused` на вердикт (список отстал) — простыми словами, код — под «подробнее»', async () => {
    const user = userEvent.setup();
    server.use(
      http.post('*/api/batches/:ch/:id/videos/mars-sample-return/acceptance', () =>
        HttpResponse.json(
          {
            message: 'Ролик «mars-sample-return» отказан после монтажа - вердикт ему не дают.',
            code: 'video_refused',
            details: ['mars-sample-return: in 05 refusals[]'],
          },
          { status: 409 },
        ),
      ),
    );
    renderApp(at('mars-sample-return'));
    await user.click(await screen.findByTestId('verdict-yes'));
    const dialog = await screen.findByRole('alertdialog');
    await user.click(within(dialog).getByTestId('verdict-confirm'));
    const refusal = await within(dialog).findByRole('alert');
    expect(within(refusal).getByTestId('refusal-message')).toHaveTextContent(VIDEO_REFUSED_TEXT);
    expect(refusal).toHaveAttribute('data-code', 'video_refused');
    expect(within(refusal).getByText('Подробнее').closest('details')).toHaveTextContent(
      'код: video_refused',
    );
  });

  it('отказанный, чью пересборку приняли: «заменён пересборкой», без вердикта и без «отказан»', async () => {
    server.use(
      http.get(`*/api/batches/example-science/2026-10-12T2001Z/videos`, () =>
        HttpResponse.json(withAcceptedRedo()),
      ),
    );
    renderApp(at('sophie-adenot'));
    const detail = await screen.findByTestId('video-detail');
    expect(await within(detail).findByTestId('acceptance-replaced')).toBeInTheDocument();
    expect(within(detail).getByTestId('acceptance-verdict')).toHaveTextContent(
      'заменён пересборкой',
    );
    expect(within(detail).queryByTestId('refused')).not.toBeInTheDocument();
    expect(within(detail).queryByTestId('verdict-anyway')).not.toBeInTheDocument();
    expect(within(detail).queryByTestId('verdict-yes')).not.toBeInTheDocument();
    expect(within(detail).getByTestId('acceptance-was-refused')).toHaveTextContent(LINE);
    const reel = screen.getAllByTestId('reel').find((r) => r.dataset.slug === 'sophie-adenot')!;
    expect(reel.dataset.replaced).toBe('true');
    expect(reel.dataset.refused).toBeUndefined();
    expect(within(reel).getByTestId('reel-state')).toHaveTextContent('заменён пересборкой');
    expect(within(reel).queryByTestId('reel-refused')).not.toBeInTheDocument();
    expect(screen.getByTestId('batch-videos')).toHaveTextContent(
      'заменены пересборкой: 1 · отказаны после монтажа: 1',
    );
  });
});
