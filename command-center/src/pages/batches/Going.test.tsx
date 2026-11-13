import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { JUDGE_ROUND_GOING_STAGES, PAST, PAST_REBUILD, RUNNING, STOPPED } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const card = async (batch: string) => {
  const all = await screen.findAllByTestId('open-batch');
  const c = all.find((x) => x.dataset.batch === batch);
  if (!c) throw new Error(`нет карточки ${batch}`);
  return c;
};

/** Текст блока без «подробнее» — то, что человек видит сразу. */
const mainText = (el: HTMLElement) => {
  const copy = el.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('[data-slot="more"]').forEach((m) => m.remove());
  return copy.textContent ?? '';
};
const moreText = (el: HTMLElement) =>
  [...el.querySelectorAll('[data-slot="more"]')].map((m) => m.textContent).join(' ');

describe('«Батчи» (б): идущий батч', () => {
  it('карточка батча словами: коды и id — только под «подробнее» (CC-0118)', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    const raw =
      /skipped_no_permission|studio-read|content-researcher|video-editor|код 0|edit-\d|vanguards-doomsday/;

    const needs = within(c).getByTestId('needs-human');
    expect(needs).toHaveTextContent('исполнитель пошёл дальше: пропустил шаг — нет разрешения');
    expect(mainText(needs)).not.toMatch(raw);
    expect(moreText(needs)).toContain(
      'studio-read · studio-read@studio-read-due.s0.a0 · skipped_no_permission',
    );

    const qs = await within(c).findByTestId('batch-questions');
    expect(qs).toHaveTextContent('спросил: Чтение Studio');
    expect(mainText(qs)).not.toMatch(raw);
    expect(moreText(qs)).toContain('источник studio-read');

    const procs = within(c).getByTestId('batch-processes');
    expect(mainText(procs)).toContain('Монтажработает');
    expect(mainText(procs)).not.toMatch(raw);
    expect(procs.querySelector('.font-mono:not([data-slot="more"] *)')).toBeNull();
    expect(moreText(procs)).toContain('стадия content-researcher, pid 4101, код выхода 0');

    const lines = await within(c).findAllByTestId('event-line');
    expect(lines[0]).toHaveTextContent(/Монтаж · (Vanguards: Doomsday|Delver)готово/);
    const feed = within(c).getByTestId('events-feed');
    for (const l of lines) expect(l.textContent).not.toMatch(raw);
    expect(moreText(feed)).toMatch(/video-editor · vanguards-doomsday · edit-\d+ — ok/);
  });

  it('идущий батч: кинолента, стадия с потолком, оценка конца, процессы, вопросы, события', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    expect(await within(c).findByRole('heading', { name: 'ExampleFilm' })).toBeInTheDocument();
    expect(within(c).getByTestId('batch-status')).toHaveTextContent('идёт');
    expect(within(c).getByTestId('batch-eta')).toHaveTextContent('осталось ≈ 1 ч');
    expect(within(c).getByTestId('stage-clock')).toHaveTextContent('20 мин из 1 ч 30 мин');
    const frames = within(within(c).getByTestId('film-strip')).getAllByRole('listitem');
    expect(frames.map((f) => f.dataset.state)).toEqual([
      'done',
      'done',
      'done',
      'unneeded',
      'done',
      'now',
      'wait',
      'wait',
    ]);
    expect(frames[5]).toHaveAttribute('aria-current', 'step');
    expect(frames[3]).toHaveTextContent('Добор');
    expect(frames[3]).toHaveTextContent('не понадобился');
    expect(within(c).getByTestId('needs-human')).toHaveTextContent('Студия канала давно');
    expect(await within(c).findByTestId('batch-questions')).toHaveTextContent('ждёт ответа');
    const procs = within(c).getAllByTestId('process');
    expect(procs.find((p) => p.dataset.alive === 'true')).toHaveTextContent('работает');
    expect(procs.find((p) => p.dataset.alive === 'false')).toHaveTextContent(
      /^Исследование и сценариизавершён$/,
    );
    // Лента событий идущего батча открыта сразу: хвост без курсора.
    expect(await within(c).findAllByTestId('event-line')).toHaveLength(30);
    // Жирные строки ленты — отметки стадий: легенда под лентой (CC-0126).
    expect(within(c).getByTestId('events-legend')).toHaveTextContent('отметки стадий');
    expect(c.querySelector('[data-testid="event-line"][data-marker]')).toHaveAttribute(
      'title',
      expect.stringContaining('отметка стадии'),
    );
    expect(batches.eventCalls[0]).toBeNull();
  });

  it('остановленная пересборка: пометка, статус, причина, остановка, блок пересборки; лента закрыта', async () => {
    renderApp('/batches');
    const c = await card(STOPPED);
    expect(within(c).getByText('пересборка')).toBeInTheDocument();
    expect(within(c).getByTestId('batch-status')).toHaveTextContent('остановлен');
    expect(within(c).getByTestId('halt-reason')).toHaveTextContent('ждёт «продолжить»');
    expect(within(c).queryByTestId('batch-eta')).not.toBeInTheDocument();
    expect(within(within(c).getByTestId('film-strip')).getAllByRole('listitem')[5]).toHaveAttribute(
      'data-state',
      'stopped',
    );
    expect(await within(c).findByTestId('batch-stops')).toHaveTextContent(
      'Остановлен 10.10, 07:30 — вы, на стадии «Монтаж», вместе с шагом',
    );
    // Ролики — названиями из карточек исходного батча; без карточки — имя словами.
    await waitFor(() =>
      expect(within(c).getByTestId('batch-rebuild')).toHaveTextContent(
        'Перемонтаж батча от 08.10, 05:00 · ролики: Why quiet keyboards cost twice as much, Usb c myths',
      ),
    );
    expect(within(c).getByTestId('events-feed')).not.toHaveAttribute('open');
    // Опрашивается лента только идущего батча.
    await waitFor(() => expect(batches.eventCalls.length).toBeGreaterThan(0));
    expect(batches.eventCalls).toHaveLength(1);
  });

  it('«Сейчас: …» — заголовок текущего кадра: «Добор после судьи», а не «Добор» (CC-0150)', async () => {
    batches.patch(RUNNING, { stages: JUDGE_ROUND_GOING_STAGES, stage: 'video-editor-judge' });
    renderApp('/batches');
    const c = await card(RUNNING);
    const now = within(within(c).getByTestId('film-strip')).getAllByRole('listitem')[7]!;
    expect(now.dataset.state).toBe('now');
    expect(now).toHaveTextContent('Добор после судьи');
    expect(within(c).getByTestId('batch-stage')).toHaveTextContent(
      'Сейчас: Добор после судьи · 20 мин из 1 ч 30 мин',
    );
    // Число и единица — через неразрывный пробел.
    expect(within(c).getByTestId('stage-clock').textContent).toBe(
      '20\u00a0мин из 1\u00a0ч 30\u00a0мин',
    );
  });

  it('кадры — в порядке `stages` из ответа API, номера подряд (CC-0090)', async () => {
    // План, где исследование идёт раньше футажа: центр рисует как пришло, не по своему списку.
    const order = [
      'batch-start',
      'trend-hunter',
      'content-researcher',
      'thin-pool-supplement',
      'footage-indexer',
      'video-editor',
      'frame-judge',
      'batch-done',
    ];
    batches.patch(RUNNING, {
      stages: order.map((id) => ({ id, status: id === 'trend-hunter' ? 'running' : 'pending' })),
      stage: 'trend-hunter',
    });
    renderApp('/batches');
    const c = await card(RUNNING);
    const frames = within(within(c).getByTestId('film-strip')).getAllByRole('listitem');
    expect(frames.map((f) => f.textContent?.slice(0, 2))).toEqual([
      '01',
      '02',
      '03',
      '04',
      '05',
      '06',
      '07',
      '08',
    ]);
    expect(frames.map((f) => f.dataset.kind)).toEqual([
      'trends',
      'research',
      'extra',
      'footage',
      'scripts',
      'edit',
      'judge',
      'accept',
    ]);
    expect(frames[1]).toHaveTextContent('Исследование');
    expect(frames[2]).toHaveTextContent('только если нужно');
    expect(frames[4]).toHaveAttribute('data-state', 'wait'); // в плане нет — на обычном месте
  });

  it('дольше обычного: left_s < 0', async () => {
    batches.patch(RUNNING, { estimate: { mean_wall_s: 3600, runs: 3, left_s: -1500 } });
    renderApp('/batches');
    const eta = within(await card(RUNNING)).getByTestId('batch-eta');
    expect(eta).toHaveTextContent('дольше обычного на 25 мин');
    expect(eta).toHaveAttribute('data-over', 'true');
  });

  it('нет батчей — «сейчас батча нет»', async () => {
    batches.closeAll();
    renderApp('/batches');
    expect(await screen.findByTestId('no-batch')).toHaveTextContent('Сейчас батча нет');
  });
});

describe('«Батчи» (б): история прогонов', () => {
  it('прогоны: длительность, итог, кто запустил, пересборка', async () => {
    renderApp('/batches');
    const hist = await screen.findByTestId('batch-history');
    const runs = await within(hist).findAllByTestId('run');
    expect(runs.map((r) => r.dataset.batch)).toEqual([
      PAST,
      PAST_REBUILD,
      'example-tech/2026-10-07T0200Z',
      'example-film/2026-10-06T0210Z',
    ]);
    expect(runs.map((r) => within(r).getByTestId('run-by').textContent)).toEqual([
      'таймер',
      'центр',
      'пульт',
      'вручную в чате',
    ]);
    expect(within(runs[0]!).getByTestId('run-duration')).toHaveTextContent('2 ч 24 мин');
    expect(within(runs[0]!).getByTestId('run-outcome')).toHaveTextContent('готово: 3 ролика');
    expect(within(runs[2]!).getByTestId('run-outcome')).toHaveTextContent('не хватило материала');
    expect(within(runs[1]!).getByText('пересборка')).toBeInTheDocument();
    expect(within(runs[0]!).queryByText('пересборка')).not.toBeInTheDocument();
  });

  it('раскрытие: стадии с длительностями, журналы, хвост с «показан конец»', async () => {
    renderApp('/batches');
    const run = (await screen.findAllByTestId('run')).find((r) => r.dataset.batch === PAST)!;
    await userEvent.click(within(run).getByRole('button', { expanded: false }));
    const stages = await within(run).findByTestId('run-stages');
    expect(within(stages).getAllByTestId('run-stage')).toHaveLength(17);
    expect(within(stages).getAllByTestId('run-stage')[9]).toHaveTextContent('Монтаж');
    expect(within(stages).getAllByTestId('run-stage')[9]).toHaveTextContent('10 мин');
    // Стадии и журналы — словами; имена стадий и файлов — только под «подробнее».
    expect(within(stages).getAllByTestId('run-stage')[9]).not.toHaveTextContent('video-editor');
    expect(within(stages).queryByTestId('run-open')).not.toBeInTheDocument();
    const logs = within(stages).getAllByTestId('log-button');
    await userEvent.click(logs.find((b) => b.dataset.log?.startsWith('video-editor.'))!);
    expect(await within(stages).findByTestId('log-tail-note')).toHaveTextContent(
      /Показан конец: последние \d+ КБ из \d+ КБ/,
    );
    await userEvent.click(logs.find((b) => b.dataset.log?.startsWith('batch-start.'))!);
    expect(await within(stages).findByText('Журнал целиком, 15 Б')).toBeInTheDocument();
  });

  it('стадия без конца в законченном батче — «оборвалась», а не «идёт» (CC-0123)', async () => {
    // Как футаж Reel 13.10: батч кончился, у стадии есть начало и нет конца.
    batches.cutStage(PAST, 4);
    renderApp('/batches');
    const run = (await screen.findAllByTestId('run')).find((r) => r.dataset.batch === PAST)!;
    await userEvent.click(within(run).getByRole('button', { expanded: false }));
    const stages = await within(run).findByTestId('run-stages');
    expect(within(stages).getByTestId('run-open')).toHaveTextContent(
      'Батч не закрыт — оборвались: Поиск трендов',
    );
    const cut = within(stages).getByTestId('run-stage-cut');
    expect(cut).toHaveTextContent('оборвалась');
    expect(stages).not.toHaveTextContent('идёт');
    expect(stages.querySelector(':scope > [data-slot="more"]')).toHaveTextContent(
      'почему не закрыт: нет batch-done',
    );
  });
});

describe('главная: блок «Батч»', () => {
  it('идущий батч — кинолента и оценка конца, ссылка на экран батчей', async () => {
    renderApp('/');
    const c = await screen.findByTestId('batch-card');
    await waitFor(() => expect(c).toHaveAttribute('data-state', 'going'));
    expect(await within(c).findByRole('heading', { name: 'ExampleFilm' })).toBeInTheDocument();
    expect(within(c).getByTestId('home-batch-eta')).toHaveTextContent('осталось ≈ 1 ч');
    expect(within(c).getAllByRole('listitem')[5]).toHaveAttribute('data-state', 'now');
    expect(within(c).getByRole('link', { name: 'К батчам' })).toHaveAttribute('href', '/batches');
    expect(within(c).getByText(/Ещё открыто батчей: 1/)).toBeInTheDocument();
    expect(within(c).queryByText(/Скоро/)).not.toBeInTheDocument();
  });

  it('нет батча — «сейчас батча нет», кадры пустые', async () => {
    batches.closeAll();
    renderApp('/');
    const c = await screen.findByTestId('batch-card');
    expect(await within(c).findByText('Сейчас батча нет')).toBeInTheDocument();
    expect(within(c).getAllByRole('listitem')).toHaveLength(8);
  });
});
