import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RUNNING, STOPPED } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const card = async (batch: string) => {
  await waitFor(() =>
    expect(screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)).toBeTruthy(),
  );
  return screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)!;
};

describe('«Батчи» (в): действия', () => {
  it('запуск: проверки списком, отсчёт на кнопке, «да» — строка фабрики, pid под «подробнее»', async () => {
    batches.closeAll();
    const user = userEvent.setup();
    renderApp('/batches');
    const launchCard = await screen.findByTestId('batches-actions');
    await user.click(within(launchCard).getByTestId('launch-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('launch-why')).toHaveTextContent(
      'все защиты пройдены',
    );
    expect(within(dialog).getAllByTestId('launch-guard')).toHaveLength(5);
    expect(within(dialog).getByTestId('launch-skipped')).toHaveTextContent('рубильник расписания');
    const go = within(dialog).getByTestId('launch-confirm');
    expect(go).toHaveTextContent(/^Запустить · [12]:\d\d$/);
    // CC-0131: та же строка о жизни плана, что во всех окнах записи.
    expect(within(dialog).getByTestId('plan-life')).toHaveTextContent(
      /^План действует ещё [12]:\d\d/,
    );
    expect(
      within(dialog)
        .getAllByTestId('launch-guard-text')
        .map((g) => g.textContent)
        .join(''),
    ).not.toMatch(/ - /);
    expect(go).toBeEnabled();
    await user.click(go);
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    const done = within(launchCard).getByTestId('launch-done');
    expect(within(done).getByTestId('launch-line')).toHaveTextContent('запущен вручную');
    // pid и журнал — только под «подробнее».
    const details = within(done).getByText('Подробнее').closest('details')!;
    expect(details).not.toHaveAttribute('open');
    expect(within(details).getByText(/^pid 51/)).toBeInTheDocument();
    // Список перечитан: новый батч канала — в «Идёт сейчас».
    expect(await screen.findAllByTestId('open-batch')).toHaveLength(1);
    expect(batches.actions.writes.map((w) => w.path)).toEqual(['launch/plan', 'launch']);
  });

  it('запуск: канал с открытым батчем — «Запустить» недоступна, причина фабрики как есть', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    await user.click(await screen.findByTestId('launch-open'));
    const dialog = await screen.findByRole('alertdialog');
    // Своими словами центра; строка фабрики с путём батча — под «подробнее».
    expect(await within(dialog).findByTestId('launch-why')).toHaveTextContent(
      /^У канала уже открыт батч \(начат 10\.10, \d\d:\d\d\) — второй не запустить/,
    );
    expect(within(dialog).getByTestId('launch-why')).not.toHaveTextContent(RUNNING);
    expect(
      within(dialog).getByText(`фабрика: открыт батч ${RUNNING} (running) - второй не запускаю`),
    ).toBeInTheDocument();
    expect(within(dialog).getByTestId('launch-confirm')).toBeDisabled();
    expect(within(dialog).getByTestId('launch-confirm')).toHaveTextContent(/^Запустить$/);
    expect(within(dialog).getByTestId('replan')).toBeInTheDocument();
  });

  it('запуск: check_changed — проверка заново сама; refused «1 батч в сутки» — как есть', async () => {
    batches.closeAll();
    const user = userEvent.setup();
    renderApp('/batches');
    await user.click(await screen.findByTestId('launch-open'));
    const dialog = await screen.findByRole('alertdialog');
    await within(dialog).findByTestId('launch-why');
    batches.actions.failNext('launch', 'check_changed');
    await user.click(within(dialog).getByTestId('launch-confirm'));
    expect(await within(dialog).findByTestId('replanned')).toHaveTextContent(
      'С момента проверки что-то изменилось',
    );
    await waitFor(() => expect(within(dialog).getByTestId('launch-confirm')).toBeEnabled());
    expect(batches.actions.writes.map((w) => w.path)).toEqual([
      'launch/plan',
      'launch',
      'launch/plan',
    ]);
    batches.actions.startedToday('example-film');
    await user.click(within(dialog).getByTestId('launch-confirm'));
    const err = await within(dialog).findByTestId('act-error');
    expect(err).toHaveAttribute('data-code', 'refused');
    expect(within(err).getByTestId('refusal-message')).toHaveTextContent(
      'сегодня (2026-10-10) батч канала уже был - 1 батч в сутки (квота YouTube Search)',
    );
    // Токен потрачен: «Запустить» больше недоступна, есть «Проверить заново».
    expect(within(dialog).getByTestId('launch-confirm')).toBeDisabled();
    expect(within(dialog).getByTestId('replan')).toBeInTheDocument();
  });

  it('остановка: ok:false — строка kill -9 только текстом, никакой кнопки её выполнить', async () => {
    batches.actions.setStopOutcome('survived');
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(RUNNING);
    await user.click(within(c).getByTestId('stop-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('stop-reason')).toHaveTextContent('можно остановить');
    expect(within(dialog).getByTestId('stop-step')).toHaveTextContent('«Монтаж»');
    await user.click(within(dialog).getByTestId('stop-confirm'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    const failed = within(await card(RUNNING)).getByTestId('stop-failed');
    expect(within(failed).getByTestId('kill-line').tagName).toBe('CODE');
    // CC-0131: своими словами; строка фабрики с pid и SIGTERM — только под «Подробнее».
    expect(within(failed).getByTestId('stop-result-reason')).toHaveTextContent(
      /^Исполнитель не остановился за 30 с после просьбы завершиться/,
    );
    expect(within(failed).getByTestId('stop-result-reason')).not.toHaveTextContent('SIGTERM');
    expect(within(failed).getByTestId('kill-line')).toHaveTextContent(/^kill -9 -\d+$/);
    expect(within(failed).queryByRole('button', { name: /kill|выполн/i })).toBeNull();
  });

  it('остановка с шагом: флажок берёт проверку заново и уходит в «да»', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(RUNNING);
    await user.click(within(c).getByTestId('stop-open'));
    const dialog = await screen.findByRole('alertdialog');
    await within(dialog).findByTestId('stop-reason');
    await user.click(within(dialog).getByTestId('stop-also-step'));
    await waitFor(() => expect(within(dialog).getByTestId('stop-confirm')).toBeEnabled());
    await user.click(within(dialog).getByTestId('stop-confirm'));
    const done = await within(await card(RUNNING)).findByTestId('stop-done');
    expect(done).toHaveTextContent('шаг остановлен');
    expect(batches.actions.writes.at(-1)!.body).toMatchObject({ also_step: true });
    // Перечитан: батч остановлен — теперь «Продолжить…».
    expect(await within(await card(RUNNING)).findByTestId('resume-open')).toBeInTheDocument();
  });

  it('продолжить пересборку: busy — токен годен, второе «да» проходит', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(STOPPED);
    expect(within(c).queryByTestId('stop-open')).toBeNull();
    await user.click(within(c).getByTestId('resume-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('resume-reason')).toHaveTextContent(
      'можно продолжить',
    );
    batches.actions.failNext('resume', 'busy');
    await user.click(within(dialog).getByTestId('resume-confirm'));
    expect(await within(dialog).findByTestId('busy-note')).toHaveTextContent(
      'Подтверждение ещё годно',
    );
    expect(within(dialog).getByTestId('resume-confirm')).toBeEnabled();
    await user.click(within(dialog).getByTestId('resume-confirm'));
    expect(await within(await card(STOPPED)).findByTestId('resume-done')).toHaveTextContent(
      'Исполнитель снова работает',
    );
  });

  it('исполнитель умер (running, alive []): «батч стоит», причина фабрики, «Продолжить с этапа…», без «Остановить» (CC-0094)', async () => {
    batches.killExecutor(RUNNING);
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(RUNNING);
    expect(await within(c).findByTestId('executor-gone-reason')).toHaveTextContent(
      'Исполнитель остановился, не записав конца (перезагрузка или сбой)',
    );
    expect(within(c).getByTestId('batch-status')).toHaveTextContent('исполнитель не отвечает');
    expect(within(c).queryByTestId('stop-open')).toBeNull();
    expect(within(c).queryByTestId('batch-eta')).toBeNull();
    expect(within(c).getByTestId('batch-event-age')).toHaveTextContent(
      'последнее событие 7 мин назад',
    );
    // Живость — из строки списка (CC-0110): фоновой проверки resume/plan нет.
    expect(screen.queryByTestId('write-lock')).toBeNull();
    expect(batches.actions.writes.filter((w) => w.path.endsWith('/resume/plan'))).toEqual([]);
    const open = within(c).getByTestId('resume-open');
    expect(open).toHaveTextContent('Продолжить с этапа «Монтаж»…');
    await user.click(open);
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('resume-reason')).toHaveTextContent(
      'исполнитель умер, не записав конца',
    );
    await user.click(within(dialog).getByTestId('resume-confirm'));
    expect(await within(await card(RUNNING)).findByTestId('resume-done')).toHaveTextContent(
      'Исполнитель снова работает',
    );
    expect(batches.actions.writes.map((w) => w.path).filter((p) => p.endsWith('/resume'))).toEqual([
      `${RUNNING}/resume`,
    ]);
    // Продолживший исполнитель запустил шаг — фабрику о нём больше не спрашивают.
    const again = await card(RUNNING);
    await waitFor(() =>
      expect(
        within(again)
          .getAllByTestId('process')
          .filter((x) => x.dataset.alive === 'true'),
      ).toHaveLength(1),
    );
    expect(batches.actions.writes.at(-1)?.path).toBe(`${RUNNING}/resume`);
  });

  it('исполнитель жив: фабрику о нём не спрашивают, «Остановить» есть (CC-0094)', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    expect(await within(c).findByTestId('batch-processes')).toBeInTheDocument();
    expect(within(c).getByTestId('stop-open')).toBeInTheDocument();
    expect(within(c).queryByTestId('executor-gone')).toBeNull();
    expect(batches.actions.writes.map((w) => w.path)).toEqual([]);
  });
});
