// CC-0137: полоса «Ждут вас» горит, только когда что-то ждёт. Подставной API: по умолчанию в
// последнем батче (PAST) ролик delver без вердикта и три вопроса без ответа — «Ждут вас»;
// вердикт delver и пустой журнал вопросов — «Ничего не ждёт»; последний батч без роликов
// (EMPTY, как второй батч Tech на фабрике 2.5) — «роликов нет», а не «все с вердиктом».
import type { Page } from '@playwright/test';

import { PAST } from '../../src/mocks/batches';
import { latestIsEmpty } from './attentionMocks';
import { expect, noSideScroll, test } from './fixtures';

const strip = (page: Page) => page.getByTestId('attention');
const link = (page: Page, name: RegExp) => strip(page).getByRole('link', { name });
const PRIMARY = /\bbg-primary\b/;

test('что-то ждёт — «Ждут вас», главная кнопка «Смотреть ролики»', async ({ page }) => {
  await page.goto('/');
  await expect(strip(page)).toHaveAttribute('data-state', 'waiting');
  await expect(strip(page).locator('#attention-title')).toHaveText('Ждут вас');
  await expect(page.getByTestId('attention-text')).toContainText(
    'Роликов без вердикта в последнем батче: 1.',
  );
  await expect(link(page, /Смотреть ролики/)).toHaveClass(PRIMARY);
  await expect(link(page, /К вопросам/)).not.toHaveClass(PRIMARY);
});

test('ждут только вопросы — главная кнопка «К вопросам»', async ({ page, videos }) => {
  videos.setAcceptance(PAST, 'delver', { verdict: 'rejected', reason: 'x', reason_code: 'x' });
  await page.goto('/');
  await expect(strip(page)).toHaveAttribute('data-state', 'waiting');
  await expect(link(page, /К вопросам/)).toHaveClass(PRIMARY);
  await expect(link(page, /Смотреть ролики/)).not.toHaveClass(PRIMARY);
});

test('ничего не ждёт — «Ничего не ждёт», без жёлтого; ссылки ведут туда же', async ({
  page,
  videos,
  questions,
}) => {
  videos.setAcceptance(PAST, 'delver', { verdict: 'rejected', reason: 'x', reason_code: 'x' });
  questions.questions = [];
  await page.goto('/');
  await expect(strip(page)).toHaveAttribute('data-state', 'calm');
  await expect(strip(page)).toHaveAttribute('data-tour', 'attention');
  await expect(strip(page).locator('#attention-title')).toHaveText('Ничего не ждёт');
  await expect(page.getByTestId('attention-text')).toHaveText(
    'В последнем батче все ролики с вердиктом. Вопросов к вам нет.',
  );
  await expect(strip(page).locator('.bg-primary')).toHaveCount(0);
  await expect(link(page, /Смотреть ролики/)).toHaveAttribute('href', '/videos');
  await link(page, /К вопросам/).click();
  await expect(page).toHaveURL(/\/questions$/);
});

test('последний батч без роликов — «роликов нет», а не «все с вердиктом»', async ({
  page,
  questions,
}) => {
  questions.questions = [];
  await latestIsEmpty(page);
  await page.goto('/');
  await expect(strip(page)).toHaveAttribute('data-state', 'calm');
  await expect(page.getByTestId('attention-text')).toHaveText(
    'В последнем батче роликов нет. Вопросов к вам нет.',
  );
});

test('телефон: полоса в обоих состояниях без прокрутки вбок', async ({
  page,
  videos,
  questions,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(strip(page)).toHaveAttribute('data-state', 'waiting');
  await noSideScroll(page);
  videos.setAcceptance(PAST, 'delver', { verdict: 'rejected', reason: 'x', reason_code: 'x' });
  questions.questions = [];
  await page.reload();
  await expect(strip(page)).toHaveAttribute('data-state', 'calm');
  await noSideScroll(page);
});
