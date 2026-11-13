// CC-0132: «Вырезать фон» и «Обрезать пустые поля» на столе мемов — план фабрики словами, «да»,
// ход фоновой задачи опросом («i из N»), итог, отказы словами фабрики, оборвавшаяся задача;
// пока задача идёт — отметки и «Применить разбор» закрыты; перезагруженная страница находит
// свою идущую задачу; Vision недоступен; задача на другом банке машины.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { memes } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

import { resetMemeDrafts } from './draft';

afterEach(() => resetMemeDrafts());
beforeEach(() => {
  memes.jobs.state.pollS = 0.05;
});

async function openTools(path = '/memes?channel=example-tech') {
  const user = userEvent.setup();
  renderApp(path);
  const desk = await screen.findByTestId('meme-desk');
  await within(desk).findAllByTestId('meme');
  await user.click(within(desk).getByTestId('meme-tools-toggle'));
  return { user, desk };
}

describe('CC-0132: вырезка фона и обрезка полей', () => {
  it('вырезка: план → «да» → ход «i из N» → итог; пока идёт — запись закрыта', async () => {
    const { user, desk } = await openTools();
    expect(within(desk).getByTestId('meme-cutout-panel')).toHaveTextContent(
      'Можно вырезать: 3 мема — вырезка есть у 2, нет у 1.',
    );
    await user.click(within(desk).getByTestId('meme-cutout-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('cutout-plan-made')).toHaveTextContent(
      'Вырежет фон: 1 мем«Distracted boyfriend»',
    );
    expect(within(dialog).getByTestId('cutout-plan-unchanged')).toHaveTextContent(
      '«Drake hotline bling», «Roll safe»',
    );
    expect(within(dialog).getByTestId('plan-notes')).toHaveTextContent(
      'станут известны только после прогона',
    );
    expect(within(dialog).getByTestId('cutout-available')).toHaveTextContent('Vision');
    expect(memes.jobs.state.plans.at(-1)).toEqual({
      kind: 'cutout',
      body: { ids: null, force: false },
    });
    const confirm = within(dialog).getByTestId('meme-cutout-confirm');
    await waitFor(() => expect(confirm).toBeEnabled());
    // Задача пойдёт медленнее, чтобы застать её идущей.
    memes.jobs.state.pollS = 0.4;
    await user.click(confirm);
    const job = await within(desk).findByTestId('meme-job');
    expect(within(job).getByTestId('job-title')).toHaveTextContent('Вырезка фона');
    await waitFor(() => expect(within(job).getByTestId('job-state')).toHaveTextContent('идёт'));
    expect(within(desk).getByTestId('desk-save')).toHaveAttribute('aria-disabled', 'true');
    expect(within(desk).getByTestId('apply-open')).toHaveAttribute('aria-disabled', 'true');
    expect(within(desk).getByTestId('meme-trim-open')).toHaveAttribute('aria-disabled', 'true');
    await waitFor(() => expect(within(job).getByTestId('job-count')).toHaveTextContent('1 из 1'));
    await waitFor(() => expect(job).toHaveAttribute('data-state', 'done'), { timeout: 4000 });
    expect(within(job).getByTestId('cutout-done-made')).toHaveTextContent('Вырезан фон: 1 мем');
    expect(within(job).getByRole('img', { name: 'Вырезка: Distracted boyfriend' })).toBeTruthy();
    await waitFor(() =>
      expect(within(desk).getByTestId('meme-cutout-panel')).toHaveTextContent(
        'вырезка есть у 3, нет у 0',
      ),
    );
    expect(within(desk).getByTestId('apply-open')).not.toHaveAttribute('aria-disabled');
    await user.click(within(job).getByTestId('job-close'));
    expect(within(desk).queryByTestId('meme-job')).toBeNull();
  });

  it('Vision недоступен — словами cutout_available(), «да» погашено', async () => {
    memes.jobs.state.vision = { available: false, reason: 'нужна macOS 14 или новее' };
    const { user, desk } = await openTools();
    await user.click(within(desk).getByTestId('meme-cutout-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('plan-why')).toHaveTextContent(
      'Вырезка на этой машине недоступна: нужна macOS 14 или новее',
    );
    expect(within(dialog).queryByTestId('cutout-unavailable')).toBeNull();
    expect(within(dialog).getByTestId('meme-cutout-confirm')).toBeDisabled();
  });

  it('обрезка: что обрежет, что растянулось бы выше потолка; задача оборвалась', async () => {
    memes.jobs.state.outcome = 'interrupted';
    const { user, desk } = await openTools();
    await user.click(within(desk).getByTestId('meme-trim-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('trim-plan-trim')).toHaveTextContent(
      '«Two buttons» — снизу чёрная полоса, 17% высоты; 600×359 → 600×298, растянется в 1,2 раза (допустимо до 1,25)',
    );
    expect(within(dialog).getByTestId('trim-plan-under')).toHaveTextContent(
      'Не обрежет, решать вам: 1 мем (растянулся бы сильнее допустимого)«Grus plan» — сверху белая полоса, 22% высоты; 600×359 → 600×280, растянулся бы в 1,28 раза — допустимо до 1,25',
    );
    expect(within(dialog).getByTestId('trim-plan-left')).toHaveTextContent('GIF');
    // Путь папки оригиналов из заметки фабрики — словами на виду, сам путь — под «подробнее».
    const notes = within(dialog).getByTestId('plan-notes');
    expect(notes).toHaveTextContent('Оригиналы картинок останутся в папке оригиналов банка.');
    expect(notes).not.toHaveTextContent('_desk');
    const confirm = within(dialog).getByTestId('meme-trim-confirm');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    const job = await within(desk).findByTestId('meme-job');
    await waitFor(() => expect(job).toHaveAttribute('data-state', 'interrupted'), {
      timeout: 4000,
    });
    expect(within(job).getByTestId('job-state')).toHaveTextContent('оборвалась');
    expect(within(job).getByTestId('job-error')).toHaveTextContent('Задача оборвалась');
  });

  it('упавшая задача: строка фабрики на виду, код и хвост журнала — под «подробнее»', async () => {
    memes.jobs.state.outcome = 'failed';
    const { user, desk } = await openTools();
    await user.click(within(desk).getByTestId('meme-cutout-open'));
    const dialog = await screen.findByRole('alertdialog');
    const confirm = within(dialog).getByTestId('meme-cutout-confirm');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    const job = await within(desk).findByTestId('meme-job');
    await waitFor(() => expect(job).toHaveAttribute('data-state', 'failed'), { timeout: 4000 });
    expect(within(job).getByTestId('job-state')).toHaveTextContent('не удалась');
    expect(within(job).getByTestId('job-error')).toHaveTextContent(
      'Задача упала на «Distracted boyfriend»: распознавание вернуло ошибку.',
    );
    const more = job.querySelector('details[data-slot="more"]')!;
    expect(more).toHaveTextContent('код: job_crashed');
    expect(within(job).getByTestId('job-log-tail')).toHaveTextContent('Traceback');
  });

  it.each([
    ['refused', true],
    ['committed', false],
    ['nothing', false],
  ] as const)('CC-0161: коммит итога %s', async (status, warned) => {
    memes.jobs.state.commit = status;
    const { user, desk } = await openTools();
    await user.click(within(desk).getByTestId('meme-cutout-open'));
    const dialog = await screen.findByRole('alertdialog');
    const confirm = within(dialog).getByTestId('meme-cutout-confirm');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    const job = await within(desk).findByTestId('meme-job');
    await waitFor(() => expect(job).toHaveAttribute('data-state', 'done'), { timeout: 4000 });
    // «Подробнее» самой задачи — последнее (у итога вырезки своё).
    const more = [...job.querySelectorAll('details[data-slot="more"]')].at(-1)!;
    if (warned) {
      expect(within(job).getByTestId('job-commit-refused')).toHaveTextContent(
        'Результат сохранён, но фабрика не смогла записать его в историю изменений — в её папке остались незаписанные правки. Скажите фабрике.',
      );
      // Жирный — только что случилось; «Скажите фабрике.» — обычным начертанием.
      expect(within(job).getByTestId('warn-title')).not.toHaveTextContent('Скажите фабрике');
      expect(within(job).getByTestId('job-commit-detail')).not.toBeVisible();
      expect(more).toHaveTextContent(
        "git отказал в коммите: fatal: Unable to create '.git/index.lock'",
      );
    } else expect(within(job).queryByTestId('job-commit-refused')).toBeNull();
    if (status === 'committed') {
      expect(within(job).getByTestId('job-commit')).toHaveTextContent('записано в историю');
      expect(more).toHaveTextContent('коммит: 3f9c2a1');
    } else expect(within(job).queryByTestId('job-commit')).toBeNull();
  });

  it('страницу открыли посреди задачи: она находится, отметки и разбор закрыты', async () => {
    memes.jobs.state.pollS = 5;
    memes.jobs.seed('example-tech', 'trim_blank');
    renderApp('/memes?channel=example-tech');
    const desk = await screen.findByTestId('meme-desk');
    const job = await within(desk).findByTestId('meme-job');
    expect(job).toHaveAttribute('data-state', 'running');
    expect(within(job).getByTestId('job-title')).toHaveTextContent('Обрезка пустых полей');
    expect(within(job).getByTestId('job-wait')).toHaveTextContent('Отмены нет');
    expect(within(desk).getByTestId('apply-open')).toHaveAttribute('aria-disabled', 'true');
    expect(within(desk).getByTestId('desk-save')).toHaveAttribute('aria-disabled', 'true');
  });

  it('задача на другом банке машины — план говорит словами фабрики', async () => {
    memes.jobs.state.elsewhere = {
      job_id: 'job-cutout-9',
      kind: 'cutout',
      kind_word: 'вырезка фона',
      bank: 'memes',
      channel: null,
    };
    const { user, desk } = await openTools();
    await user.click(within(desk).getByTestId('meme-trim-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('plan-why')).toHaveTextContent(
      'одна задача на машину, дождитесь её конца',
    );
    expect(within(dialog).getByTestId('meme-trim-confirm')).toBeDisabled();
  });
});
