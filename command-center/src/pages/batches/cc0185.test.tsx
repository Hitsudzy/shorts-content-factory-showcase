// CC-0185 (договор 0.79.0, фабрика CF-0922): горизонт ленты и порог батча в окне канала —
// переименование, новое поле, откуда порог, предупреждение «порог ниже горизонта» до сохранения,
// отказ фабрики 409 как есть; слова «что поменялось» и причина дня плана — по порогу батча.
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { PlanChannel, PlanDay, SchedulePlan, ScheduleSettings } from '@/api/schedule';
import { schedule } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

import { dayWhy } from './dayWhy';
import { changesText } from './format';
import { draftOf, editOf, thresholdBelow, thresholdOrigin } from './windowDraft';

const settings = (s: Partial<ScheduleSettings>): ScheduleSettings => ({
  enabled: true,
  window: '02:00',
  window_hours: 3,
  min_feed_days: 3,
  batch_feed_days: 14,
  overlay: {},
  ...s,
});

describe('CC-0185: слова и черновик', () => {
  it('откуда порог: пульт, файл канала, по умолчанию (14, поднятый до горизонта), нет порога', () => {
    expect(thresholdOrigin(settings({}))).toBe('default');
    expect(thresholdOrigin(settings({ min_feed_days: 20, batch_feed_days: 20 }))).toBe('default');
    expect(thresholdOrigin(settings({ batch_feed_days: 3 }))).toBe('channel');
    expect(
      thresholdOrigin(settings({ batch_feed_days: 14, overlay: { batch_feed_days: 14 } })),
    ).toBe('center');
    expect(thresholdOrigin(settings({ batch_feed_days: null }))).toBeNull();
  });

  it('порог ниже горизонта: заданный — в счёт, нетронутый по умолчанию — нет', () => {
    const was = draftOf(settings({ batch_feed_days: 5 }));
    expect(thresholdBelow({ ...was, min_feed_days: '6' }, was, 'channel')).toEqual({
      threshold: 5,
      horizon: 6,
    });
    expect(thresholdBelow({ ...was, batch_feed_days: '2' }, was, 'center')).toEqual({
      threshold: 2,
      horizon: 3,
    });
    expect(thresholdBelow({ ...was, batch_feed_days: '3' }, was, 'channel')).toBeNull();
    const def = draftOf(settings({}));
    // Горизонт 20 при пороге по умолчанию: фабрика сама поднимет порог — не предупреждаем.
    expect(thresholdBelow({ ...def, min_feed_days: '20' }, def, 'default')).toBeNull();
    // А если порог тронули — в счёт.
    expect(
      thresholdBelow({ ...def, min_feed_days: '20', batch_feed_days: '15' }, def, 'default'),
    ).toEqual({ threshold: 15, horizon: 20 });
    expect(thresholdBelow({ ...def, batch_feed_days: '' }, def, 'center')).toBeNull();
  });

  it('тело PUT: порог — только когда поменяли', () => {
    const was = draftOf(settings({}));
    expect(editOf(was, false, was)).not.toHaveProperty('batch_feed_days');
    expect(editOf({ ...was, min_feed_days: '20' }, false, was)).not.toHaveProperty(
      'batch_feed_days',
    );
    expect(editOf({ ...was, batch_feed_days: '7' }, false, was)).toMatchObject({
      batch_feed_days: 7,
      min_feed_days: 3,
    });
    // Пустое поле — без изменений (снять порог нельзя).
    expect(editOf({ ...was, batch_feed_days: '' }, false, was)).not.toHaveProperty(
      'batch_feed_days',
    );
  });

  it('«что поменялось»: горизонт ленты и порог батча в днях', () => {
    expect(changesText({ min_feed_days: [3, 4], batch_feed_days: [14, 7] })).toEqual([
      'горизонт ленты: 3 дн. → 4 дн.',
      'порог батча: 14 дн. → 7 дн.',
    ]);
  });

  it('причина дня плана — по порогу батча, не по горизонту', () => {
    const ch = (p: Partial<PlanChannel>): PlanChannel => ({
      plannable: true,
      min_feed_days: 3,
      batch_feed_days: 14,
      settings: { enabled: true, min_feed_days: 3, batch_feed_days: 14 },
      ...p,
    });
    const plan = (channels: Record<string, PlanChannel>) =>
      ({
        now: '',
        today: '2026-10-10',
        quota_day: '2026-10-10',
        quota_tz: 'America/Los_Angeles',
        per_day: 1,
        stale_open: [],
        channels,
        days: [],
        timer: '',
      }) as unknown as SchedulePlan;
    const need = {
      day: '2026-10-11',
      channel: 'reel',
      status: 'planned',
      kind: 'needs_batch',
      why: 'лента короче 14 дн. (на 2 дн.)',
      covers_days: [],
      first_empty_slot: null,
    } as unknown as PlanDay;
    expect(dayWhy(need, plan({ reel: ch({}) })).text).toBe(
      'Публикаций на 14 дней вперёд не хватает\u00a0— нужен батч',
    );
    // Старая фабрика без порога — порогом был `min_feed_days`.
    expect(
      dayWhy(
        need,
        plan({
          reel: ch({
            batch_feed_days: null,
            settings: { enabled: true, min_feed_days: 3, batch_feed_days: null },
          }),
        }),
      ).text,
    ).toBe('Публикаций на 3 дня вперёд не хватает\u00a0— нужен батч');
    const fed = { ...need, channel: null, status: 'idle', kind: 'fed' } as unknown as PlanDay;
    expect(dayWhy(fed, plan({ reel: ch({}), tech: ch({}) })).text).toBe(
      'Публикаций хватает на 14 дней вперёд\u00a0— батч не нужен',
    );
  });
});

describe('CC-0185: окно канала на экране', () => {
  it('горизонт ленты и порог батча: подписи, откуда порог', async () => {
    renderApp('/batches');
    const reel = await screen.findByTestId('window-example-film');
    await within(reel).findByTestId('win-feed');
    expect(within(reel).getByText('Горизонт ленты, дн.')).toBeInTheDocument();
    expect(within(reel).getByText('Порог батча, дн.')).toBeInTheDocument();
    expect(within(reel).queryByText(/Порог ленты/)).not.toBeInTheDocument();
    expect(within(reel).getByTestId('win-feed')).toHaveValue(3);
    expect(within(reel).getByTestId('win-batch-feed')).toHaveValue(3);
    expect(within(reel).getByTestId('win-batch-origin')).toHaveTextContent(
      'Задан в настройках канала',
    );
    expect(within(reel).getByTestId('win-plan-feed')).toHaveTextContent(
      'в плане: горизонт ленты 3 дн., порог батча 3 дн.',
    );

    const sci = await screen.findByTestId('window-example-science');
    expect(await within(sci).findByTestId('win-batch-feed')).toHaveValue(14);
    expect(within(sci).getByTestId('win-batch-origin')).toHaveTextContent('По умолчанию фабрики');
  });

  it('порог ниже горизонта: предупреждение до сохранения, отказ фабрики 409 как есть', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const card = await screen.findByTestId('window-example-film');
    const bfd = await within(card).findByTestId('win-batch-feed');
    expect(within(card).queryByTestId('win-threshold-below')).not.toBeInTheDocument();

    await user.clear(bfd);
    await user.type(bfd, '2');
    expect(within(card).getByTestId('win-threshold-below')).toHaveTextContent(
      'Порог батча 2 дн. меньше горизонта ленты 3 дн. — фабрика такое не примет',
    );
    expect(bfd).toHaveAttribute('aria-invalid', 'true');

    await user.click(within(card).getByTestId('win-save'));
    expect(await within(card).findByTestId('refusal-message')).toHaveTextContent(
      'Фабрика не приняла настройки расписания канала example-film: порог батча не меньше горизонта ленты',
    );
    expect(schedule.writes.filter((w) => w.kind === 'settings')).toHaveLength(0);
    expect(bfd).toHaveValue(2);

    // Порог не ниже горизонта — сохраняется, «что поменялось» — порог батча.
    await user.clear(bfd);
    await user.type(bfd, '7');
    expect(within(card).queryByTestId('win-threshold-below')).not.toBeInTheDocument();
    await user.click(within(card).getByTestId('win-save'));
    expect(await within(card).findByTestId('win-saved')).toHaveTextContent(
      'порог батча: 3 дн. → 7 дн.',
    );
    expect(within(card).getByTestId('win-batch-origin')).toHaveTextContent('Задан в центре');
  });

  it('порог по умолчанию: горизонт выше 14 не предупреждает — фабрика поднимет порог сама', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const card = await screen.findByTestId('window-example-science');
    const feed = await within(card).findByTestId('win-feed');
    await user.clear(feed);
    await user.type(feed, '20');
    expect(within(card).queryByTestId('win-threshold-below')).not.toBeInTheDocument();
    await user.click(within(card).getByTestId('win-save'));
    expect(await within(card).findByTestId('win-saved')).toHaveTextContent(
      'горизонт ленты: 3 дн. → 20 дн.',
    );
    expect(await within(card).findByTestId('win-batch-feed')).toHaveValue(20);
    expect(within(card).getByTestId('win-batch-origin')).toHaveTextContent(
      'По умолчанию фабрики — поднят до горизонта ленты',
    );
  });
});
