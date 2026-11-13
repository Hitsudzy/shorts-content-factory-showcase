import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { strandedBatch, strandedLogName, type StrandedBatch } from '@/api/batches';
import { RUNNING, STRANDED_FAILED, STRANDED_STOPPED } from '@/mocks/batches';
import { fixtures, writesModes } from '@/mocks/fixtures';
import { batches, mockGet } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { guardLinks, strandedHeadline, strandedReasonText } from './stranded';

const row = (over: Partial<StrandedBatch> = {}): StrandedBatch => ({
  batch: 'example-science/2026-10-12T1908Z',
  dir: 'pipeline/example-science/2026-10-12T1908Z',
  channel: 'example-science',
  batch_id: '2026-10-12T1908Z',
  status: 'failed',
  stage: 'batch-start',
  reason: 'step 0 (runlog batch-start) exited 2; log logs/batch-start.s0.a0.log',
  log: 'pipeline/example-science/2026-10-12T1908Z/logs/batch-start.s0.a0.log',
  log_name: 'batch-start.s0.a0.log',
  log_url: '/api/batches/example-science/2026-10-12T1908Z/logs/batch-start.s0.a0.log',
  holds_day: true,
  ...over,
});

const cardOf = async (batch: string) => {
  await waitFor(() =>
    expect(
      screen.getAllByTestId('stranded-batch').find((x) => x.dataset.batch === batch),
    ).toBeTruthy(),
  );
  return screen.getAllByTestId('stranded-batch').find((x) => x.dataset.batch === batch)!;
};

describe('упавшие батчи: слова и пути (CC-0089)', () => {
  it('путь API и журнал — поля фабрики `batch`, `log_name` (CC-0115), не вывод из каталога', () => {
    expect(strandedBatch(row())).toBe('example-science/2026-10-12T1908Z');
    expect(strandedBatch(row({ batch: 'rebuilds/2026-10-10T0410Z' }))).toBe(
      'rebuilds/2026-10-10T0410Z',
    );
    // Без `batch` центр каталог не разбирает.
    expect(strandedBatch(row({ batch: null }))).toBeNull();
    expect(strandedBatch(row({ batch: 'x/y/z' }))).toBeNull();
    expect(strandedLogName(row())).toBe('batch-start.s0.a0.log');
    expect(strandedLogName(row({ log_name: null }))).toBeNull();
  });

  it('причина словами: шаг упал, пропуск, русская без путей, неизвестная — общими словами', () => {
    expect(strandedHeadline(row())).toBe(
      'Упал на стадии «Старт батча» — команда стадии завершилась с ошибкой — что именно, видно в журнале стадии',
    );
    expect(strandedReasonText('after failed stage batch-start')).toBe(
      'стадия пропущена: до неё упала стадия «Старт батча»',
    );
    expect(strandedReasonText('остановлен пользователем (центр): ждёт «продолжить»')).toBe(
      'остановлен вами из центра: ждёт «продолжить»',
    );
    expect(strandedReasonText('грязное дерево (/home/x/repo) - стоп')).toBe(
      'грязное дерево — стоп',
    );
    expect(strandedReasonText('weird thing')).toMatch(/под «подробнее»/);
    expect(strandedReasonText(null)).toBe('причину фабрика не записала');
    expect(strandedHeadline(row({ status: 'stopped', stage: null, reason: null }))).toBe(
      'Остановлен до первой стадии — причину фабрика не записала',
    );
  });

  it('ссылки отказа — только batches защиты (CF-0724), без запасного пути по holds_day', () => {
    const r = row();
    const other = row({ batch: 'example-film/2026-10-09T1410Z', channel: 'example-film' });
    const all = [r, other];
    expect(guardLinks({ name: 'today', ok: true, batches: null }, all, [])).toEqual([]);
    // Фабрика батчей не назвала — ссылок нет, хоть упавший батч и держит день.
    expect(guardLinks({ name: 'today', ok: false, batches: null }, all, [])).toEqual([]);
    expect(
      guardLinks(
        { name: 'today', ok: false, batches: ['example-science/2026-10-12T1908Z'] },
        all,
        [],
      ),
    ).toEqual([{ batch: 'example-science/2026-10-12T1908Z', kind: 'stranded', row: r }]);
    expect(guardLinks({ name: 'today', ok: false, batches: ['x/y'] }, all, [])).toEqual([
      { batch: 'x/y', kind: 'unknown' },
    ]);
    expect(guardLinks({ name: 'pause', ok: false, batches: null }, all, [])).toEqual([]);
  });
});

describe('«Батчи»: блок «Упавшие батчи» (CC-0089)', () => {
  it('пусто — блока нет', async () => {
    renderApp('/batches');
    await screen.findAllByTestId('open-batch');
    await screen.findByTestId('batch-history');
    expect(screen.queryByTestId('stranded')).toBeNull();
  });

  it('упал на batch-start: стадия и причина словами, держит день, журнал под «подробнее», «Продолжить…»', async () => {
    batches.strand();
    const user = userEvent.setup();
    renderApp('/batches');
    const block = await screen.findByTestId('stranded');
    expect(within(block).getByRole('heading', { name: 'Упавшие батчи' })).toBeInTheDocument();
    const card = await cardOf(STRANDED_FAILED);
    expect(within(card).getByTestId('stranded-headline')).toHaveTextContent(
      'Упал на стадии «Старт батча» — команда стадии завершилась с ошибкой',
    );
    expect(within(card).getByTestId('stranded-holds')).toHaveTextContent('держит запуск сегодня');
    expect(within(card).getByTestId('stranded-holds-note')).toBeInTheDocument();
    // Сырое — только под «подробнее».
    const details = card.querySelector('details[data-slot="more"]')!;
    expect(details).not.toHaveAttribute('open');
    expect(within(details as HTMLElement).getByText(/^причина: step 0/)).toBeInTheDocument();
    expect(within(card).getByTestId('stranded-headline')).not.toHaveTextContent('step 0');
    // Журнал стадии читается, только когда «подробнее» раскрыто.
    expect(within(card).queryByTestId('log-tail')).toBeNull();
    await user.click(within(card).getAllByText('Подробнее')[0]!);
    expect(await within(card).findByTestId('log-tail')).toHaveTextContent(
      'working tree is not clean',
    );

    await user.click(await within(card).findByTestId('resume-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('resume-reason')).toHaveTextContent(
      'можно продолжить',
    );
    await user.click(within(dialog).getByTestId('resume-confirm'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    // Продолжен — из «упавших» в «Идёт сейчас».
    await waitFor(() =>
      expect(
        screen.getAllByTestId('open-batch').some((x) => x.dataset.batch === STRANDED_FAILED),
      ).toBe(true),
    );
    await waitFor(() =>
      expect(screen.getAllByTestId('stranded-batch').map((x) => x.dataset.batch)).toEqual([
        STRANDED_STOPPED,
      ]),
    );
  });

  it('остановлен вчера: день не держит, «Продолжить» нет — отказ фабрики словами', async () => {
    batches.strand();
    renderApp('/batches');
    const card = await cardOf(STRANDED_STOPPED);
    expect(within(card).getByTestId('stranded-headline')).toHaveTextContent(
      'Остановлен на стадии «Поиск трендов» — остановлен вами из центра',
    );
    expect(within(card).getByTestId('stranded-holds')).toHaveTextContent('запуск не держит');
    expect(await within(card).findByTestId('stranded-refusal')).toHaveTextContent(
      'Продолжить нельзя: батч вчерашний (9 октября): день батча прошёл, темы и квота поиска — уже не его',
    );
    expect(within(card).queryByTestId('resume-open')).toBeNull();
    expect(within(card).queryByTestId('stranded-holds-note')).toBeNull();
    // Проверка — тихая: план без слоя записи.
    expect(screen.queryByTestId('write-lock')).toBeNull();
  });

  it('окно запуска: отказ «сегодня» ведёт к батчу, что держит день; «открытые» — к идущему', async () => {
    batches.strand();
    const user = userEvent.setup();
    renderApp('/batches');
    await cardOf(STRANDED_FAILED);
    await user.selectOptions(await screen.findByTestId('launch-channel'), 'example-science');
    await user.click(screen.getByTestId('launch-open'));
    let dialog = await screen.findByRole('alertdialog');
    const today = (await within(dialog).findAllByTestId('launch-guard')).find(
      (g) => g.dataset.ok === 'false',
    )!;
    expect(today).toHaveTextContent('Батч сегодня');
    expect(within(dialog).getByTestId('launch-why')).toHaveTextContent(
      /^Сегодня батч канала уже был \(10\.10, 07:04\) — в сутки разрешён один$/,
    );
    expect(within(today).getByTestId('launch-guard-text')).not.toHaveTextContent('0405Z');
    expect(within(today).getByTestId('launch-guard-text')).not.toHaveTextContent('pipeline');
    expect(within(dialog).getByTestId('launch-skipped')).not.toHaveTextContent('batch_feed_days');
    // Строка фабрики — под «подробнее».
    expect(
      within(dialog).getByText(/^today: сегодня батч уже был: example-science 2026-10-10T0405Z/),
    ).toBeInTheDocument();
    const link = within(today).getByTestId('launch-guard-batch');
    expect(link).toHaveAttribute('data-batch', STRANDED_FAILED);
    expect(link).toHaveTextContent('Батч, что держит день');
    await user.click(link);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(document.activeElement).toBe(await cardOf(STRANDED_FAILED));

    await user.selectOptions(screen.getByTestId('launch-channel'), 'example-film');
    await user.click(screen.getByTestId('launch-open'));
    dialog = await screen.findByRole('alertdialog');
    await within(dialog).findByTestId('launch-why');
    const open = within(dialog).getByTestId('launch-guard-batch');
    expect(open).toHaveAttribute('data-batch', RUNNING);
    expect(open).toHaveTextContent('Открытый батч');
    await user.click(open);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(document.activeElement).toHaveAttribute('data-batch', RUNNING);
  });

  it('вне рабочей фабрики: проверку не спрашиваем, «Продолжить…» погашена', async () => {
    server.use(mockGet('/api/health', { ...fixtures.health, ...writesModes.off }));
    batches.strand();
    renderApp('/batches');
    const card = await cardOf(STRANDED_FAILED);
    await waitFor(() =>
      expect(within(card).getByTestId('resume-open')).toHaveAttribute('data-writes', 'off'),
    );
    expect(batches.actions.writes.filter((w) => w.path.endsWith('/resume/plan'))).toEqual([]);
  });
});
