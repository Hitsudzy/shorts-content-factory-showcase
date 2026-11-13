// «Статистика и аналитик» (CC-0021): каналы со сбором, ролики с окном 7 дней, график ролика,
// сводка аналитика словами, нужный футаж с упакованными по кнопке, чтение Studio (ввод — StudioEntry.test);
// пустые состояния и отказы — словами. Номера и пути — только под «подробнее».
import { act, fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';

import { analytics } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { dueText, leadLine, videoName } from './format';

/** Видимый текст без «подробнее». */
function plainText(el: HTMLElement): string {
  const clone = el.cloneNode(true) as HTMLElement;
  clone.querySelectorAll('[data-slot="more"]').forEach((d) => d.remove());
  return clone.textContent ?? '';
}

async function open(path = '/stats') {
  const user = userEvent.setup();
  renderApp(path);
  await screen.findByTestId('stats-videos');
  return user;
}

describe('CC-0021: экран «Статистика и аналитик»', () => {
  it('каналы: Reel выбран, у Science сбор ещё не запускался', async () => {
    await open();
    const ch = screen.getAllByTestId('stats-channel');
    expect(ch.map((c) => c.dataset.channel)).toEqual([
      'example-film',
      'example-tech',
      'example-science',
    ]);
    expect(within(ch[0]!).getByRole('link')).toHaveAttribute('aria-current', 'true');
    expect(ch[0]).toHaveTextContent('собрана');
    expect(ch[2]).toHaveTextContent('Сбор статистики ещё не запускался');
  });

  it('ролики: числа окна, окончательные и нет, «досмотрели» из Studio, новые сверху', async () => {
    await open();
    const rows = screen.getAllByTestId('stats-video');
    expect(rows).toHaveLength(8);
    expect(rows[0]).toHaveTextContent('Sandfall messiah');
    expect(rows[0]).toHaveTextContent('чисел ещё нет');
    const heated = rows.find((r) => r.dataset.video === 'hR4c9xQe1aA')!;
    expect(heated).toHaveTextContent('48 210');
    expect(heated).toHaveTextContent('64,1 %');
    expect(heated).toHaveTextContent('окончательные');
    const young = rows.find((r) => r.dataset.video === 'sN7gWz4oPc2')!;
    expect(young).toHaveTextContent('идёт 4 из 7 дн.');
    expect(plainText(screen.getByTestId('stats-videos'))).not.toMatch(/hR4c9xQe1aA|analytics\//);
  });

  it('клик по ролику — его график по дням и окно плитками', async () => {
    const user = await open();
    expect(screen.getByTestId('stats-video-hint')).toBeInTheDocument();
    await user.click(screen.getByRole('link', { name: 'Rink rivals' }));
    const detail = await screen.findByTestId('stats-video-detail');
    await within(detail).findByTestId('views-chart');
    expect(within(detail).getAllByTestId('chart-bar')).toHaveLength(12);
    expect(within(detail).getByTestId('window-tiles')).toHaveTextContent('31 400');
    expect(within(detail).getByTestId('video-studio')).toHaveTextContent('досмотрели 64,1 %');
    expect(within(detail).getByRole('img')).toHaveAccessibleName(/Просмотры по дням: 12 дн\./);
  });

  it('Tech: окно 7 дней не собирается — так и сказано, в ролике только дневные строки', async () => {
    const user = await open('/stats?channel=example-tech');
    expect(screen.getByTestId('not-collected')).toHaveTextContent(
      'Окно первых 7 дней фабрика у YouTube для этого канала не спрашивает',
    );
    expect(screen.getAllByTestId('stats-video')[0]).toHaveTextContent('окно не собирается');
    await user.click(screen.getByRole('link', { name: 'Rtx 5090 melts' }));
    expect(await screen.findByTestId('no-window')).toBeInTheDocument();
    expect(screen.getByTestId('views-chart')).toBeInTheDocument();
  });

  it('Science: сбора не было — пустые состояния словами', async () => {
    await open('/stats?channel=example-science');
    expect(screen.getByTestId('never-collected')).toBeInTheDocument();
    expect(screen.getByText('Роликов со статистикой пока нет')).toBeInTheDocument();
    expect(await screen.findByText('Нужного футажа нет')).toBeInTheDocument();
    expect(await screen.findByTestId('summary-counts')).toHaveTextContent(
      'Роликов в сводке пока нет',
    );
    expect(await screen.findByText('У канала нет конвейера')).toBeInTheDocument();
  });

  it('сводка: измерения словами, «мало роликов», пробелы по видам', async () => {
    await open();
    const s = screen.getByTestId('stats-summary');
    await within(s).findByTestId('summary-counts');
    expect(within(s).getByTestId('summary-counts')).toHaveTextContent(
      'В сводке 8 роликов: вышли 8, со стилем 7, с числами YouTube 7, с чтением Studio 6',
    );
    expect(within(s).getByTestId('small-sample')).toHaveTextContent('Роликов пока мало.');
    const pattern = within(s)
      .getAllByTestId('summary-dimension')
      .find((d) => d.dataset.dimension === 'pattern')!;
    expect(pattern).toHaveTextContent('Схема сценария');
    expect(pattern).toHaveTextContent(
      'Больше всего вовлечённых просмотров (медиана) — у «контраст»',
    );
    expect(pattern).toHaveTextContent('мало роликов');
    expect(within(s).getByTestId('gap-no_profile')).toHaveTextContent(
      'Sandfall messiah — нет строки приёмки',
    );
    expect(within(s).getByTestId('gap-no_studio')).toHaveTextContent('Odd quarter finale');
    expect(plainText(s)).not.toMatch(/III\.E|windows\.jsonl/);
  });

  it('сводка: сохранённая за день — по выбору дня', async () => {
    const user = await open();
    const s = screen.getByTestId('stats-summary');
    await within(s).findByTestId('summary-counts');
    await user.selectOptions(within(s).getByTestId('summary-day'), '2026-10-07');
    await waitFor(() => expect(s).toHaveTextContent('Сводка аналитика · за 07.10'));
    expect(analytics.state.calls).toContain('/api/analytics/example-film/summary/2026-10-07');
  });

  it('CC-0163: ролик, затем день — до перерисовки; оба выбора остаются', async () => {
    await open();
    const s = screen.getByTestId('stats-summary');
    await within(s).findByTestId('summary-counts');
    const row = () =>
      screen.getAllByTestId('stats-video').find((r) => r.dataset.video === 'hR4c9xQe1aA')!;
    // Оба — в одном act: день выбран, пока экран ещё не перерисован после ролика.
    act(() => {
      fireEvent.click(screen.getByRole('link', { name: 'Rink rivals' }));
      fireEvent.change(within(s).getByTestId('summary-day'), { target: { value: '2026-10-07' } });
    });
    await waitFor(() => expect(s).toHaveTextContent('Сводка аналитика · за 07.10'));
    expect(within(s).getByTestId('summary-day')).toHaveValue('2026-10-07');
    expect(row()).toHaveAttribute('aria-current', 'true');
    await screen.findByTestId('stats-video-detail');
  });

  it('CC-0163: день, затем строка ролика — до перерисовки; оба выбора остаются', async () => {
    await open();
    const s = screen.getByTestId('stats-summary');
    await within(s).findByTestId('summary-counts');
    const row = () =>
      screen.getAllByTestId('stats-video').find((r) => r.dataset.video === 'hR4c9xQe1aA')!;
    act(() => {
      fireEvent.change(within(s).getByTestId('summary-day'), { target: { value: '2026-10-07' } });
      fireEvent.click(row());
    });
    await screen.findByTestId('stats-video-detail');
    expect(row()).toHaveAttribute('aria-current', 'true');
    expect(within(s).getByTestId('summary-day')).toHaveValue('2026-10-07');
    await waitFor(() => expect(s).toHaveTextContent('Сводка аналитика · за 07.10'));
  });

  it('нужный футаж: причины словами, где добыть; упакованные — только по кнопке', async () => {
    const user = await open();
    const f = screen.getByTestId('stats-footage');
    await within(f).findAllByTestId('footage-row');
    const heated = within(f)
      .getAllByTestId('footage-row')
      .find((r) => r.dataset.name === 'Rink Rivals')!;
    expect(heated).toHaveTextContent('монтажу не хватило кадра для главного героя');
    // Канал — один раз, его ролик — после двоеточия (CC-0113, ревью экранов).
    expect(within(heated).getByTestId('footage-where')).toHaveTextContent(
      /^Где добыть: канал «Examplevue»: «Rink Rivals \| Official Trailer \| Examplevue»$/,
    );
    // Код без строки фабрики — «причина без описания»; сам код — в подсказке и под «Подробнее».
    const saturn = within(f)
      .getAllByTestId('footage-row')
      .find((r) => r.dataset.name === 'Orbit Awards 2026')!;
    expect(within(saturn).getByRole('list', { name: 'Почему' })).toHaveTextContent(
      /^причина без описания$/,
    );
    expect(within(f).getByTestId('footage-reasons')).toHaveTextContent('причина без описания: 1');
    expect(within(f).getByTestId('footage-reasons')).not.toHaveTextContent('event_footage_short');
    expect(saturn.querySelector('details')).toHaveTextContent('event_footage_short ×1');
    expect(heated).toHaveTextContent('не хватило 5 раз');
    expect(within(f).getAllByTestId('footage-row')).toHaveLength(5);
    expect(analytics.state.calls.some((c) => c.includes('packed=true'))).toBe(false);
    await user.click(within(f).getByTestId('footage-packed'));
    await waitFor(() => expect(within(f).getAllByTestId('footage-row')).toHaveLength(6));
    expect(within(f).getByTestId('footage-packed')).toHaveTextContent('Только свежие');
    expect(analytics.state.calls).toContain(
      '/api/analytics/example-film/footage-wanted?packed=true',
    );
  });

  it('Studio: пора читать, ссылки в Studio, ввод цифр — свёрнут, без записей', async () => {
    await open();
    const st = screen.getByTestId('stats-studio');
    await within(st).findByTestId('studio-due');
    expect(within(st).getByTestId('studio-due')).toHaveTextContent('пора читать');
    expect(within(st).getByTestId('studio-due')).not.toHaveTextContent('due example-film');
    expect(within(st).getAllByTestId('studio-video')).toHaveLength(5);
    expect(within(st).getAllByRole('link', { name: 'Открыть в Studio' })[0]).toHaveAttribute(
      'href',
      expect.stringMatching(/^https:\/\/studio\.youtube\.com\/video\//),
    );
    expect(within(st).getByTestId('studio-entry-toggle')).toHaveTextContent(
      'Внести прочитанное в Studio',
    );
    expect(within(st).queryByTestId('studio-entry-form')).toBeNull();
    expect(analytics.entry.state.calls).toEqual([]);
  });

  it('Studio не настроено (Tech) — словами, строка фабрики под «подробнее»', async () => {
    await open('/stats?channel=example-tech');
    const st = screen.getByTestId('stats-studio');
    expect(
      await within(st).findByText('Чтение Studio для канала не настроено'),
    ).toBeInTheDocument();
    expect(plainText(st)).not.toMatch(/studio_read/);
  });

  it('отказ фабрики — её словами', async () => {
    analytics.state.broken = 'example-film';
    renderApp('/stats');
    expect(await screen.findByText('Числа роликов не прочитать')).toBeInTheDocument();
    expect(screen.getAllByText('Хранилище статистики канала не читается.').length).toBeGreaterThan(
      0,
    );
  });

  it('пустой журнал загрузок — «статистики пока нет»', async () => {
    server.use(
      http.get('*/api/analytics', () => HttpResponse.json({ channels: [], window_days: [7] })),
    );
    renderApp('/stats');
    expect(await screen.findByText('Статистики пока нет')).toBeInTheDocument();
  });
});

describe('слова статистики', () => {
  it('строка «пора читать» — без служебного префикса', () => {
    expect(dueText('due example-film: пора читать (страховка)')).toBe('Пора читать (страховка)');
    expect(dueText('ok example-film: последнее чтение 08.10')).toBe('Последнее чтение 08.10');
  });

  it('имя ролика — из слага или entry_id', () => {
    expect(videoName({ entry_id: 'example-film/2026-10-01T0200Z/rapid-reckless-11' })).toBe(
      'Rapid reckless 11',
    );
    expect(videoName({ video_id: 'abc' })).toBe('abc');
  });

  it('главная фраза: одной группы мало', () => {
    expect(leadLine([], 20)).toMatch(/Сравнивать пока не с чем/);
  });
});
