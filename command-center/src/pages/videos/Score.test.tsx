// CC-0125: значок оценки «A · 86» цвета тира — в списке роликов, на странице ролика, на главной
// («Ролики ждут решения»), в копилке и у отказанного после монтажа; окно «Оценка ролика» с
// разбором (стадии, жёсткие, штрафы по цене, потолок, прогноз отдельно, статус цен), «к моменту ▶»
// — плеер на это время на странице ролика, ссылка с `?t=` в других местах; клавиатура.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PAST } from '@/mocks/batches';
import { REEL } from '@/mocks/publish';
import { SCORE_FULL, SCORE_HARD, SCORE_MOMENT_T } from '@/mocks/score';
import { STASH_HELD } from '@/mocks/stash';
import { SCIENCE } from '@/mocks/videos';
import { renderApp } from '@/test/renderApp';
import type { VideoScoreFinding } from '@/api/score';

import { noteRu, whereText } from './scoreWords';

const videoUrl = (batch: string, slug: string) =>
  `/videos?batch=${encodeURIComponent(batch)}&v=${slug}`;

describe('CC-0125: значок оценки и разбор', () => {
  it('список батча: у каждого ролика значок с буквой тира и баллами, цвет — по тиру', async () => {
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}`);
    const reels = await screen.findAllByTestId('reel');
    const badges = reels.map((r) => within(r).getByTestId('score-badge'));
    expect(badges.map((b) => b.textContent)).toEqual(['B · 74', 'A · 82', 'C · 58']);
    expect(badges.map((b) => b.dataset.level)).toEqual(['3', '2', '4']);
    // Буква видна всегда; для читалки — словами.
    expect(badges[1]).toHaveAccessibleName(/Оценка ролика: тир A, 82 баллов — подробнее/);
  });

  it('окно разбора: стадии, штрафы по цене с потолком, прогноз отдельно, статус цен, строка под «Подробнее»', async () => {
    const user = userEvent.setup();
    renderApp(`/videos?batch=${encodeURIComponent(PAST)}`);
    const reel = (await screen.findAllByTestId('reel')).find((r) => r.dataset.slug === SCORE_FULL)!;
    await user.click(within(reel).getByTestId('score-badge'));
    const dialog = await screen.findByTestId('score-dialog');
    expect(within(dialog).getByRole('heading', { name: 'Оценка ролика' })).toBeInTheDocument();
    const body = await within(dialog).findByTestId('score-body');
    expect(within(body).getByTestId('score-big')).toHaveTextContent('B74');
    expect(within(body).getByTestId('score-passed')).toHaveTextContent('Прошёл порог канала');
    expect(within(body).getByTestId('score-frame')).toHaveTextContent(
      'старт 100 · порог канала 40 · итог 74',
    );
    const stages = within(body).getAllByTestId('score-stage');
    expect(stages.map((s) => s.dataset.stage)).toEqual(['6b', 'plan', 'render', 'qc', 'judge']);
    expect(stages[2]).toHaveTextContent('без снятий');
    expect(stages[4]).toHaveTextContent('−10');
    const pen = within(within(body).getByTestId('score-penalties')).getAllByTestId('score-finding');
    expect(pen.map((f) => within(f).getByTestId('score-price').textContent)).toEqual([
      '−10',
      '−7',
      '−6',
      '−3',
    ]);
    expect(pen[0]).toHaveTextContent('полоса удержания');
    expect(within(pen[0]!).getByTestId('score-where')).toHaveTextContent('блоки 3, 4 · на 0:12');
    expect(within(pen[0]!).getByTestId('score-capped')).toHaveTextContent(
      'потолок правила: больше 10 не снимается',
    );
    // Путь пула в заметке — только имя файла.
    expect(pen[3]).toHaveTextContent('subject off-center: a04_mine-cart.mp4');
    expect(pen[3]).not.toHaveTextContent('/home/');
    // CC-0128: заметка по-русски (`note_ru`) — на виду; сырая `note` — только под «подробнее».
    expect(within(pen[0]!).getByTestId('score-note-ru')).toHaveTextContent(
      'зритель уходит на середине: два блока подряд без смены кадра',
    );
    expect(within(pen[0]!).getByTestId('score-note').closest('[data-slot="more"]')).not.toBeNull();
    expect(within(pen[0]!).getByTestId('score-note-ru').closest('[data-slot="more"]')).toBeNull();
    // Кадр — `shot_ru` фабрики.
    expect(within(pen[3]!).getByTestId('score-where')).toHaveTextContent('кадр «mine cart»');
    expect(within(pen[3]!).getByTestId('score-note-ru')).toHaveTextContent(
      'главное в кадре смещено от центра',
    );
    // У находки без шаблона (`note_ru` null) на виду заметки нет — она под «подробнее».
    const fc = within(within(body).getByTestId('score-forecast')).getByTestId('score-finding');
    expect(within(fc).queryByTestId('score-note-ru')).toBeNull();
    expect(within(fc).getByTestId('score-note').closest('[data-slot="more"]')).not.toBeNull();
    const forecast = within(body).getByTestId('score-forecast');
    expect(forecast).toHaveTextContent('Прогноз — в счёт не идёт');
    expect(within(forecast).getAllByTestId('score-finding')).toHaveLength(1);
    expect(within(body).queryByTestId('score-hard')).toBeNull();
    expect(within(body).getByTestId('score-prices')).toHaveTextContent('подписаны');
    // Вне страницы ролика «к моменту ▶» — ссылка на ролик с `?t=`.
    const moment = within(pen[0]!).getByTestId('score-moment');
    expect(moment).toHaveAttribute(
      'href',
      `/videos?batch=${encodeURIComponent(PAST)}&v=${SCORE_FULL}&t=${SCORE_MOMENT_T}`,
    );
    expect(within(body).getByTestId('score-line')).toHaveTextContent('B · 74');
    await user.click(within(dialog).getByTestId('dialog-close'));
    await waitFor(() => expect(screen.queryByTestId('score-dialog')).toBeNull());
  });

  it('страница ролика: значок вместо строки «Оценка: …», «к моменту ▶» — плеер на это время', async () => {
    const user = userEvent.setup();
    renderApp(videoUrl(PAST, SCORE_FULL));
    await screen.findByTestId('player');
    const video = screen.getByTestId('player-video') as HTMLVideoElement;
    Object.defineProperty(video, 'duration', { configurable: true, value: 44.9 });
    video.pause = () => {};
    const row = screen.getByTestId('video-score');
    const badge = within(row).getByTestId('score-badge');
    expect(badge).toHaveTextContent('B · 74');
    // С клавиатуры: фокус на значке, Enter открывает окно.
    badge.focus();
    await user.keyboard('{Enter}');
    const dialog = await screen.findByTestId('score-dialog');
    const moments = await within(dialog).findAllByTestId('score-moment');
    expect(moments[0]!.tagName).toBe('BUTTON');
    await user.click(moments[0]!);
    await waitFor(() => expect(screen.queryByTestId('score-dialog')).toBeNull());
    expect(video.currentTime).toBeCloseTo(SCORE_MOMENT_T);
  });

  it('адрес с `?t=` — плеер встаёт на это время сразу', async () => {
    renderApp(`${videoUrl(PAST, SCORE_FULL)}&t=21.8`);
    const video = (await screen.findByTestId('player-video')) as HTMLVideoElement;
    await waitFor(() => expect(video.currentTime).toBeCloseTo(21.8));
  });

  it('отказанный после монтажа: F, жёсткая находка сверху красным, остановлен досрочно, разбор из 05', async () => {
    const user = userEvent.setup();
    renderApp(videoUrl(SCIENCE, SCORE_HARD));
    const refused = await screen.findByTestId('refused');
    const badge = within(refused).getByTestId('score-badge');
    expect(badge).toHaveTextContent('F · 24');
    expect(badge.dataset.level).toBe('f');
    expect(badge.dataset.passed).toBe('false');
    await user.click(badge);
    const body = await within(await screen.findByTestId('score-dialog')).findByTestId('score-body');
    const hard = within(body).getByTestId('score-hard');
    expect(hard).toHaveTextContent('Жёсткие находки — ролик F при любых баллах');
    expect(hard).toHaveTextContent('зависший кадр в хуке');
    // Жёсткие — раньше штрафов.
    expect(
      hard.compareDocumentPosition(within(body).getByTestId('score-penalties')) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(within(body).getByTestId('score-passed')).toHaveTextContent('Не прошёл порог канала');
    expect(within(body).getByTestId('score-stopped')).toHaveTextContent(
      'Остановлен досрочно: после проверки качества',
    );
    expect(within(body).getByTestId('score-no-stages')).toBeInTheDocument();
    expect(within(body).getByTestId('score-prices')).toHaveTextContent('черновик');
  });

  it('главная, «Ролики ждут решения»: значок у ролика, «к моменту» ведёт на его страницу', async () => {
    const user = userEvent.setup();
    renderApp('/');
    const card = await screen.findByTestId('reels-card');
    const items = await within(card).findAllByTestId('reels-item');
    const badge = await within(items[0]!).findByTestId('score-badge');
    expect(badge).toHaveTextContent(/^[SABCDF] · \d+$/);
    await user.click(badge);
    const dialog = await screen.findByTestId('score-dialog');
    expect(await within(dialog).findByTestId('score-body')).toBeInTheDocument();
  });

  it('у ролика без оценки значка нет', async () => {
    renderApp(`/videos?batch=${encodeURIComponent(SCIENCE)}`);
    const reels = await screen.findAllByTestId('reel');
    const dots = reels.find((r) => r.dataset.slug === 'jwst-little-red-dots')!;
    expect(within(dots).queryByTestId('score-badge')).toBeNull();
  });

  it('копилка: значок у ролика из списка его батча, «к моменту» ведёт на ролик', async () => {
    renderApp(`/publishing?channel=${REEL}`);
    const stash = await screen.findByTestId('stash');
    const row = (await within(stash).findAllByTestId('stash-row')).find(
      (r) => r.dataset.slug === STASH_HELD,
    )!;
    expect(await within(row).findByTestId('score-badge')).toHaveTextContent('A · 84');
  });
});

describe('CC-0128: кадр и заметка находки словами', () => {
  const f = (x: Partial<VideoScoreFinding>) =>
    ({
      where: {},
      hook: false,
      capped: false,
      hard: false,
      forecast: false,
      ...x,
    }) as VideoScoreFinding;
  it('кадр — `shot_ru` фабрики; без него — своя обрезка имени файла', () => {
    expect(whereText(f({ shot: 'a07_ocean-floor.mp4', shot_ru: 'дно океана' }))).toBe(
      'кадр «дно океана»',
    );
    expect(whereText(f({ shot: '/pool/clips/a07_ocean-floor.mp4', shot_ru: null }))).toBe(
      'кадр «ocean floor»',
    );
  });
  it('заметка по-русски — только из `note_ru`, пустая — нет', () => {
    expect(noteRu(f({ note: 'raw', note_ru: 'по-русски' }))).toBe('по-русски');
    expect(noteRu(f({ note: 'raw', note_ru: '  ' }))).toBeNull();
    expect(noteRu(f({ note: 'raw' }))).toBeNull();
  });
});
