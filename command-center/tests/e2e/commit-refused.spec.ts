// CC-0161 (договор 0.71.0): фабрика записала итог, но git отказал в коммите — дерево фабрики
// осталось грязным. На подставном API (src/mocks/memeJobs.ts `state.commit`, src/mocks/channelData.ts
// `ending.lastRun`): задача банка мемов кончилась с `commit.status = refused` и концовка Tech
// собрана с `last_run.commit_refused` — заметная строка, слово git — под «подробнее».
import { ENDING_COMMIT_REFUSED } from '../../src/mocks/channelData';
import { expect, noSideScroll, test } from './fixtures';

test('задача мемов: итог записан, коммит отказан — строка на виду, git под «подробнее»', async ({
  page,
  memes,
}) => {
  memes.jobs.state.pollS = 0.2;
  memes.jobs.state.commit = 'refused';
  await page.goto('/memes?channel=example-tech');
  await expect(page.getByTestId('meme')).toHaveCount(35);
  await page.getByTestId('meme-tools-toggle').click();
  await page.getByTestId('meme-cutout-open').click();
  const dialog = page.getByRole('alertdialog');
  await dialog.getByTestId('meme-cutout-confirm').click();
  const job = page.getByTestId('meme-job');
  await expect(job).toHaveAttribute('data-state', 'done', { timeout: 15_000 });
  await expect(job.getByTestId('job-commit-refused')).toHaveText(
    /^Результат сохранён, но фабрика не смогла записать его в историю изменений\s— в её папке остались незаписанные правки\. Скажите фабрике\.$/,
  );
  await expect(job.getByTestId('job-commit')).toHaveCount(0);
  const detail = job.getByTestId('job-commit-detail');
  await expect(detail).toBeHidden();
  await job.getByText('Подробнее', { exact: true }).last().click();
  await expect(detail).toContainText(
    "git отказал в коммите: fatal: Unable to create '.git/index.lock'",
  );
});

test('концовка Tech собрана, коммит отказан — строка на виду; телефон без прокрутки вбок', async ({
  page,
  channels,
}) => {
  channels.data.ending.lastRun['example-tech'] = ENDING_COMMIT_REFUSED('example-tech');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/channels/example-tech?tab=data');
  const ending = page.getByTestId('ending');
  await expect(ending.getByTestId('ending-commit-refused')).toHaveText(
    /^Концовка собрана, но не записана в историю изменений\s— в папке фабрики остались незаписанные правки\. Скажите фабрике\.$/,
  );
  const detail = ending.getByTestId('ending-commit-detail');
  await expect(detail).toBeHidden();
  await ending.getByText('Подробнее', { exact: true }).click();
  await expect(detail).toContainText('git отказал в коммите: fatal:');
  await noSideScroll(page);
  // Строка git переносится, а не уходит за правый край карточки — и на телефоне, и на компьютере.
  for (const width of [390, 1280]) {
    await page.setViewportSize({ width, height: 844 });
    const fits = await detail.evaluate((el) => {
      const card = el.closest('section')!.getBoundingClientRect();
      const rects = [...el.getClientRects()];
      return (
        el.scrollWidth <= el.clientWidth + 1 &&
        rects.every((r) => r.right <= card.right + 0.5 && r.left >= card.left - 0.5)
      );
    });
    expect(fits, `ширина ${width}`).toBe(true);
  }
});
