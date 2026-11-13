// CC-0133: «Добавить мем» на столе — картинка по ссылке (подсказка про http(s) до плана, план
// словами, ход по шагам, новая запись `pending` в сетке), отказ фабрики словами
// (`duplicate_id`), лист кадров (метки смен сцен, два щелчка по кадрам → форма GIF с отрезком),
// пересчёт признаков, перезагруженная страница находит идущую задачу добавления.
import { fireEvent, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { memes } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

import { resetMemeDrafts } from './draft';

afterEach(() => resetMemeDrafts());
beforeEach(() => {
  memes.jobs.state.pollS = 0.05;
});

async function openAdd(path = '/memes?channel=example-tech') {
  const user = userEvent.setup();
  renderApp(path);
  const desk = await screen.findByTestId('meme-desk');
  await within(desk).findAllByTestId('meme');
  await user.click(within(desk).getByTestId('meme-add-toggle'));
  return { user, desk };
}

const fill = (root: HTMLElement, values: Record<string, string>) => {
  for (const [id, v] of Object.entries(values))
    fireEvent.change(within(root).getByTestId(id), { target: { value: v } });
};

const IMAGE = {
  'add-image-url': 'https://i.imgflip.com/success-kid.jpg',
  'add-image-source': 'https://imgflip.com/memetemplate/success-kid',
  'add-image-id': 'success-kid',
  'add-image-description': 'Малыш сжимает кулак с песком',
  'add-image-tags': 'успех, победа',
};

describe('CC-0133: добавить мем', () => {
  it('картинка: file:// — подсказка до плана; план → «да» → шаги → новая запись ждёт разбора', async () => {
    const { user, desk } = await openAdd();
    const form = within(desk).getByTestId('meme-add-image');
    fill(form, { ...IMAGE, 'add-image-url': 'file:///home/me/kid.jpg' });
    expect(within(form).getByTestId('field-hint')).toHaveTextContent('Только ссылка http(s)://');
    expect(within(form).getByTestId('meme-add-image-open')).toHaveAttribute(
      'aria-disabled',
      'true',
    );
    expect(memes.jobs.state.plans).toEqual([]);

    fill(form, IMAGE);
    expect(within(form).queryByTestId('field-hint')).toBeNull();
    await user.click(within(form).getByTestId('meme-add-image-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('add-plan-fetch')).toHaveTextContent(
      'картинка https://i.imgflip.com/success-kid.jpg',
    );
    expect(within(dialog).getByTestId('add-plan-where')).toHaveTextContent(
      'в банк новым мемом «Success kid», ждёт разбора',
    );
    expect(within(dialog).getByTestId('add-plan-time')).toHaveTextContent('до 4 мин');
    expect(within(dialog).getByTestId('plan-notes')).toHaveTextContent('непроверенным');
    expect(memes.jobs.state.plans.at(-1)).toEqual({
      kind: 'add_image',
      body: {
        id: 'success-kid',
        url: IMAGE['add-image-url'],
        source_url: IMAGE['add-image-source'],
        description: 'Малыш сжимает кулак с песком',
        tags: ['успех', 'победа'],
      },
    });
    const confirm = within(dialog).getByTestId('meme-add-image-confirm');
    await waitFor(() => expect(confirm).toBeEnabled());
    memes.jobs.state.pollS = 0.4;
    await user.click(confirm);
    const job = await within(desk).findByTestId('meme-job');
    expect(within(job).getByTestId('job-title')).toHaveTextContent('Добавление картинки');
    await waitFor(() =>
      expect(within(job).getByTestId('job-count')).toHaveTextContent(/шаг \d из 4/),
    );
    await waitFor(() => expect(job).toHaveAttribute('data-state', 'done'), { timeout: 5000 });
    const entry = within(job).getByTestId('add-done-entry');
    expect(entry).toHaveTextContent('Картинка «Success kid» в банке');
    expect(entry).toHaveTextContent('ждёт разбора');
    expect(within(job).getByTestId('add-done-embedding')).toHaveTextContent('пересчитаны');
    await waitFor(() => expect(within(desk).getAllByTestId('meme')).toHaveLength(36));
    await user.click(within(job).getByTestId('add-done-open'));
    await waitFor(() =>
      expect(within(desk).getByTestId('meme-viewer')).toHaveAttribute('data-id', 'success-kid'),
    );
  });

  it('отказ фабрики словами: id уже есть в банке (duplicate_id), код — под «подробнее»', async () => {
    const { user, desk } = await openAdd();
    const form = within(desk).getByTestId('meme-add-image');
    fill(form, { ...IMAGE, 'add-image-id': 'roll-safe' });
    await user.click(within(form).getByTestId('meme-add-image-open'));
    const dialog = await screen.findByRole('alertdialog');
    const refusal = await within(dialog).findByTestId('write-refusal');
    expect(refusal).toHaveAttribute('data-code', 'duplicate_id');
    expect(within(refusal).getByTestId('write-refusal-title')).toHaveTextContent('Мем не добавлен');
    expect(within(refusal).getByTestId('write-refusal-message')).toHaveTextContent(
      'мем «Roll safe» уже есть в банке',
    );
  });

  it('лист кадров: смены сцен на кадрах, два щелчка → «GIF из видео» с отрезком', async () => {
    const { user, desk } = await openAdd();
    await user.click(within(desk).getByTestId('add-tab-sheet'));
    const form = within(desk).getByTestId('meme-add-sheet');
    fill(form, {
      'sheet-video': 'https://www.youtube.com/watch?v=abc',
      'sheet-end': '700',
    });
    expect(within(form).getByTestId('sheet-frames')).toHaveTextContent('В листе будет 350 кадров');
    expect(within(form).getByTestId('meme-sheet-open')).toHaveAttribute('aria-disabled', 'true');
    fill(form, { 'sheet-end': '40' });
    await user.click(within(form).getByTestId('meme-sheet-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('add-plan-span')).toHaveTextContent(
      '0–40 с, кадр каждые 2 с — 20 кадров',
    );
    const confirm = within(dialog).getByTestId('meme-sheet-confirm');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    const job = await within(desk).findByTestId('meme-job');
    await waitFor(() => expect(job).toHaveAttribute('data-state', 'done'), { timeout: 5000 });
    expect(within(job).getByTestId('sheet-image')).toHaveAttribute(
      'src',
      '/api/memes/example-tech/sheets/sheet.jpg',
    );
    expect(within(job).getAllByTestId('sheet-frame')).toHaveLength(20);
    expect(within(job).getAllByTestId('sheet-cut')).toHaveLength(2);
    expect(within(job).getByTestId('sheet-cuts')).toHaveTextContent('Смены сцен: 12,4 с · 27 с');
    await user.click(within(job).getByRole('button', { name: 'Кадр 10 с' }));
    await user.click(
      within(job).getByRole('button', { name: 'Кадр 14 с, после смены сцены на 12,4 с' }),
    );
    expect(within(job).getByTestId('sheet-pick-start')).toHaveValue('10');
    expect(within(job).getByTestId('sheet-pick-end')).toHaveValue('16');
    expect(within(job).getByTestId('sheet-pick-cuts')).toHaveTextContent('смена сцены на 12,4 с');
    await user.click(within(job).getByTestId('sheet-to-gif'));
    const gif = within(desk).getByTestId('meme-add-gif');
    expect(gif).toBeVisible();
    expect(within(gif).getByTestId('add-gif-video')).toHaveValue(
      'https://www.youtube.com/watch?v=abc',
    );
    expect(within(gif).getByTestId('add-gif-start')).toHaveValue('10');
    expect(within(gif).getByTestId('add-gif-end')).toHaveValue('16');
    expect(within(gif).getByTestId('add-gif-seeded')).toHaveTextContent('10–16 с');
  });

  it('пересчёт признаков: план центра → «да» → задача → итог', async () => {
    const user = userEvent.setup();
    renderApp('/memes?channel=example-tech');
    const desk = await screen.findByTestId('meme-desk');
    await within(desk).findAllByTestId('meme');
    await user.click(within(desk).getByTestId('meme-tools-toggle'));
    await user.click(within(desk).getByTestId('meme-embed-open'));
    const dialog = await screen.findByRole('alertdialog');
    expect(await within(dialog).findByTestId('embed-plan-time')).toHaveTextContent('до 11 мин');
    expect(within(dialog).getByTestId('plan-notes')).toHaveTextContent(
      'файлы и отметки мемов не меняются',
    );
    const confirm = within(dialog).getByTestId('meme-embed-confirm');
    await waitFor(() => expect(confirm).toBeEnabled());
    await user.click(confirm);
    const job = await within(desk).findByTestId('meme-job');
    await waitFor(() => expect(job).toHaveAttribute('data-state', 'done'), { timeout: 5000 });
    expect(within(job).getByTestId('job-title')).toHaveTextContent(
      'Пересчёт признаков для поиска похожих мемов',
    );
    expect(within(job).getByTestId('embed-done')).toHaveTextContent('пересчитаны');
  });

  it('перезагруженная страница находит идущую задачу добавления; кэш видео — «Беру видео»', async () => {
    memes.jobs.state.holdAt = 0;
    memes.jobs.state.cached = ['https://www.youtube.com/watch?v=abc'];
    memes.jobs.seed('example-tech', 'add_gif', {
      meme_id: 'dog-turns',
      video: 'https://www.youtube.com/watch?v=abc',
      start: 10,
      end: 14,
      description: 'Собака оборачивается',
      tags: ['собака'],
      local: false,
    });
    renderApp('/memes?channel=example-tech');
    const job = await screen.findByTestId('meme-job');
    expect(within(job).getByTestId('job-title')).toHaveTextContent('Нарезка GIF');
    expect(within(job).getByTestId('job-state')).toHaveTextContent('идёт');
    expect(within(job).getByTestId('job-progress')).toHaveTextContent('Беру видео');
    expect(within(job).getByTestId('job-count')).toHaveTextContent('шаг 1 из 6');
    expect(within(job).getByTestId('job-step-text')).toHaveTextContent('из кэша банка');
  });
});
