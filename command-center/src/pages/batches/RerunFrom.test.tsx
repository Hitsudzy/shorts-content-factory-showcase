import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { RUNNING, STOPPED, STRANDED_FAILED, STRANDED_STOPPED } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

import { resumeText } from './actions';
import { rerunStatus, rerunWhy } from './rerunText';

const card = async (batch: string) => {
  await waitFor(() =>
    expect(screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)).toBeTruthy(),
  );
  return screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)!;
};

const stranded = async (batch: string) => {
  await waitFor(() =>
    expect(
      screen.queryAllByTestId('stranded-batch').find((x) => x.dataset.batch === batch),
    ).toBeTruthy(),
  );
  return screen.getAllByTestId('stranded-batch').find((x) => x.dataset.batch === batch)!;
};

/** Текст без «подробнее» — то, что человек видит сразу. */
const mainText = (el: HTMLElement) => {
  const copy = el.cloneNode(true) as HTMLElement;
  copy.querySelectorAll('[data-slot="more"]').forEach((m) => m.remove());
  return copy.textContent ?? '';
};

const stageRow = (dialog: HTMLElement, id: string) =>
  within(dialog)
    .getAllByTestId('rerun-stage')
    .find((x) => x.dataset.stage === id)!;

async function openRerun(user: ReturnType<typeof userEvent.setup>, where: HTMLElement) {
  await user.click(within(where).getByTestId('rerun-open'));
  const dialog = await screen.findByRole('alertdialog');
  await within(dialog).findAllByTestId('rerun-stage');
  return dialog;
}

describe('«Повторить с…» (CC-0123)', () => {
  it('слова: статусы стадий, строка фабрики со стадиями по-русски', () => {
    expect(rerunStatus('done')).toBe('готово');
    expect(rerunStatus('pending')).toBe('ещё не шла');
    expect(rerunWhy('раньше упала стадия batch-start — повторите с неё')).toBe(
      'раньше упала стадия «Старт батча» — повторите с неё',
    );
    expect(rerunWhy(null)).toBe('');
    // Ответ продолжения: message, а у `refused` (фабрика без кода) — её строка.
    expect(resumeText({ code: 'executor_alive', message: 'Батч идёт', reason: 'alive' })).toBe(
      'Батч идёт',
    );
    expect(resumeText({ code: 'refused', message: 'Фабрика отказала', reason: 'вчерашний' })).toBe(
      'вчерашний',
    );
  });

  it('идущий батч — кнопки нет; остановленный — стадии, недоступные погашены с причиной', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    expect(within(await card(RUNNING)).queryByTestId('rerun-open')).toBeNull();
    const dialog = await openRerun(user, await card(STOPPED));
    const start = stageRow(dialog, 'batch-start');
    expect(start).toHaveAttribute('data-can', 'false');
    expect(within(start).getByRole('radio')).toBeDisabled();
    expect(within(start).getByTestId('rerun-stage-why')).toHaveTextContent(
      'стадия «Старт батча» или раньше',
    );
    const judge = stageRow(dialog, 'frame-judge');
    expect(within(judge).getByRole('radio')).toBeDisabled();
    expect(judge).toHaveTextContent('Проверка кадровещё не шла');
    expect(within(stageRow(dialog, 'video-editor')).getByRole('radio')).toBeEnabled();
    expect(within(dialog).getByTestId('rerun-can-count')).toHaveTextContent('можно с');
    // «Да» — только после выбора стадии и плана.
    expect(within(dialog).getByTestId('rerun-confirm')).toBeDisabled();
    expect(mainText(within(dialog).getByTestId('rerun-stages'))).not.toMatch(
      /frame-judge|stage_not_run|batch-start/,
    );
  });

  it('план: что сбросится и что останется; заметка и без «сразу продолжить» — батч сброшен', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(STOPPED);
    const dialog = await openRerun(user, c);
    await user.click(within(stageRow(dialog, 'content-researcher')).getByRole('radio'));
    const plan = await within(dialog).findByTestId('rerun-plan');
    expect(
      within(plan)
        .getAllByTestId('rerun-reset-stage')
        .map((x) => x.textContent),
    ).toEqual([
      'Исследование и сценариисейчас: готово',
      'Проверка сценариевсейчас: готово',
      'Монтажсейчас: остановлена',
    ]);
    expect(within(plan).getByTestId('rerun-kept')).toHaveTextContent('Поиск трендовеё файл');
    expect(mainText(plan)).not.toMatch(/pipeline\/|trends\.json|CF-0739|rerun-from/);
    const resume = within(plan).getByTestId('rerun-resume');
    expect(resume).toBeChecked();
    await user.click(resume);
    await user.type(within(plan).getByTestId('rerun-note'), 'сценарии заново');
    await user.click(within(dialog).getByTestId('rerun-confirm'));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(batches.actions.writes.at(-1)).toMatchObject({
      path: `${STOPPED}/rerun-from`,
      body: { resume: false, note: 'сценарии заново' },
    });
    const done = await within(await card(STOPPED)).findByTestId('rerun-done');
    expect(done).toHaveTextContent('Батч сброшен до стадии «Исследование и сценарии»');
    expect(done).toHaveTextContent('продолжите его кнопкой «Продолжить»');
    expect(mainText(done)).not.toContain('run-state.before-rerun');
    expect(done.querySelector('[data-slot="more"]')).toHaveTextContent('run-state.before-rerun');
  });

  it('«сразу продолжить»: продолжен; не вышло — «сброшен, но не продолжен» с причиной', async () => {
    const user = userEvent.setup();
    batches.actions.setRerunResume('failed');
    renderApp('/batches');
    let dialog = await openRerun(user, await card(STOPPED));
    await user.click(within(stageRow(dialog, 'video-editor')).getByRole('radio'));
    await within(dialog).findByTestId('rerun-plan');
    await user.click(within(dialog).getByTestId('rerun-confirm'));
    const failed = await within(await card(STOPPED)).findByTestId('rerun-resume-failed');
    expect(failed).toHaveTextContent('Батч сброшен до стадии «Монтаж», но не продолжен');
    expect(failed).toHaveTextContent('замок батча держит другой процесс');
    expect(mainText(failed)).not.toMatch(/resume_failed|locked/);

    batches.actions.setRerunResume('ok');
    dialog = await openRerun(user, await card(STOPPED));
    await user.click(within(stageRow(dialog, 'content-researcher')).getByRole('radio'));
    await within(dialog).findByTestId('rerun-plan');
    await user.click(within(dialog).getByTestId('rerun-confirm'));
    const ok = await within(await card(STOPPED)).findByTestId('rerun-done');
    expect(ok).toHaveTextContent('Батч повторяется со стадии «Исследование и сценарии»');
    expect(ok.querySelector('[data-slot="more"]')).toHaveTextContent(/исполнитель pid \d+/);
  });

  it('упавшие батчи: «Повторить с…» рядом с «Продолжить»; упал на старте — ни с одной нельзя', async () => {
    const user = userEvent.setup();
    batches.strand();
    renderApp('/batches');
    const failed = await stranded(STRANDED_FAILED);
    const dialog = await openRerun(user, failed);
    expect(within(dialog).getByTestId('rerun-can-count')).toHaveTextContent('ни с одной нельзя');
    expect(within(stageRow(dialog, 'monitors')).getByTestId('rerun-stage-why')).toHaveTextContent(
      'раньше упала стадия «Старт батча»',
    );
    await user.keyboard('{Escape}');
    // Вчерашний остановленный: продолжить нельзя, а повторить со стадии — можно.
    const stopped = await stranded(STRANDED_STOPPED);
    expect(await within(stopped).findByTestId('stranded-refusal')).toBeInTheDocument();
    const d2 = await openRerun(user, stopped);
    expect(within(stageRow(d2, 'trend-hunter')).getByRole('radio')).toBeEnabled();
  });
});
