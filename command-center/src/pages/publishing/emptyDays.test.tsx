// Пустые дни ленты и «журнала загрузок нет» (CC-0142): счёт по `slots` очереди (московские дни,
// прошедший сегодняшний слот не в счёт, окно ленты), слова с неразрывным пробелом перед тире,
// без графика — ничего; на экране — строка под правилом слота; предупреждение по `journal_exists` —
// одно над каналами, не в ленте (CC-0148: журнал один на фабрику).
import { screen, within } from '@testing-library/react';

import type { ChannelQueue, QueueSlot } from '@/api/publish';
import { publish } from '@/mocks/handlers';
import { REEL, SCIENCE } from '@/mocks/publish';
import { renderApp } from '@/test/renderApp';

import {
  emptyDays,
  emptyDaysText,
  JOURNAL_MISSING,
  JOURNAL_NO_ROWS,
  periodText,
} from './emptyDays';

const NBSP = ' ';
const RULE = { channel: REEL, times: ['01:00'], tz: 'Europe/Moscow', per_day: 1, lead_hours: 12 };

/** Слот 01:00 МСК московского дня `day` (в UTC — 22:00 накануне). */
function slot(day: string, taken_by: string | null = null): QueueSlot {
  const [y, m, d] = day.split('-').map(Number) as [number, number, number];
  const at = new Date(Date.UTC(y, m - 1, d - 1, 22)).toISOString().replace('.000', '');
  return {
    at,
    local: `${day}T01:00:00+03:00`,
    label: `${day} 01:00 МСК`,
    day,
    taken_by,
    next_free: false,
  };
}

type Q = Pick<ChannelQueue, 'slot' | 'slots' | 'as_of' | 'days'>;
const queue = (as_of: string, slots: QueueSlot[], days = 14): Q => ({
  slot: RULE,
  slots,
  as_of,
  days,
});

describe('пустые дни: счёт', () => {
  it('свободные дни впереди; занятый и прошедший сегодняшний — не в счёт', () => {
    const q = queue('2026-10-17T07:00:00Z', [
      slot('2026-10-17'), // 01:00 сегодня уже прошёл
      slot('2026-10-18', 'a'),
      slot('2026-10-19'),
      slot('2026-10-20', 'b'),
      slot('2026-10-22'),
    ]);
    expect(emptyDays(q)).toEqual(['2026-10-19', '2026-10-22']);
  });

  it('границы московского дня: 00:30 МСК — уже новый день, его 01:00 впереди', () => {
    // 2026-10-16T21:30Z = 17.10 00:30 МСК: сегодня — 17.10, слот 16.10 — вчерашний.
    const q = queue('2026-10-16T21:30:00Z', [slot('2026-10-16'), slot('2026-10-17')]);
    expect(emptyDays(q)).toEqual(['2026-10-17']);
    // 21:59Z = 00:59 МСК — слот 17.10 ещё впереди; 22:00Z — ровно его время, тоже ещё в счёт.
    expect(emptyDays({ ...q, as_of: '2026-10-16T22:00:00Z' })).toEqual(['2026-10-17']);
    expect(emptyDays({ ...q, as_of: '2026-10-16T22:00:01Z' })).toEqual([]);
  });

  it('окно ленты: 14 дней с сегодняшнего, дальше — не считается', () => {
    const q = queue('2026-10-17T07:00:00Z', [slot('2026-10-30'), slot('2026-10-31')]);
    expect(emptyDays(q)).toEqual(['2026-10-30']);
    expect(emptyDays({ ...q, days: 15 })).toEqual(['2026-10-30', '2026-10-31']);
  });

  it('два слота в день: занят хотя бы один — день не пустой', () => {
    const late = { ...slot('2026-10-19'), at: '2026-10-19T15:00:00Z' };
    const q = queue('2026-10-17T07:00:00Z', [slot('2026-10-19'), { ...late, taken_by: 'x' }]);
    expect(emptyDays(q)).toEqual([]);
  });

  it('графика нет — null; всё занято — пустой список', () => {
    expect(
      emptyDays({ ...queue('2026-10-17T07:00:00Z', [slot('2026-10-19')]), slot: null }),
    ).toBeNull();
    expect(emptyDays(queue('2026-10-17T07:00:00Z', []))).toBeNull();
    expect(emptyDays(queue('2026-10-17T07:00:00Z', [slot('2026-10-19', 'a')]))).toEqual([]);
  });
});

describe('пустые дни: горизонт ленты (CC-0180)', () => {
  it('дальше последнего дня горизонта пустой день не считается', () => {
    const q = queue('2026-10-10T07:00:00Z', [
      slot('2026-10-11'),
      slot('2026-10-13'),
      slot('2026-10-14'),
      slot('2026-10-20'),
    ]);
    expect(emptyDays(q)).toEqual(['2026-10-11', '2026-10-13', '2026-10-14', '2026-10-20']);
    expect(emptyDays(q, '2026-10-13')).toEqual(['2026-10-11', '2026-10-13']);
    expect(emptyDays(q, null)).toHaveLength(4);
    expect(emptyDaysText([], 3)).toBe(`Пустых дней за 3${NBSP}дня нет`);
  });
});

describe('пустые дни: слова', () => {
  it('число и даты, тире не начинает строку; ноль — «нет»', () => {
    expect(emptyDaysText(['2026-10-19', '2026-10-22', '2026-10-25'])).toBe(
      `Пустых дней за 2${NBSP}недели: 3${NBSP}— 19.10, 22.10, 25.10`,
    );
    expect(emptyDaysText([])).toBe(`Пустых дней за 2${NBSP}недели нет`);
    expect(JOURNAL_MISSING).toBe(`Журнала загрузок нет${NBSP}— фабрика не видит, что уже выложено`);
  });

  it('окно словами по правилам числа', () => {
    expect(periodText(7)).toBe('неделю');
    expect(periodText(14)).toBe(`2${NBSP}недели`);
    expect(periodText(35)).toBe(`5${NBSP}недель`);
    expect(periodText(1)).toBe(`1${NBSP}день`);
    expect(periodText(3)).toBe(`3${NBSP}дня`);
    expect(periodText(10)).toBe(`10${NBSP}дней`);
  });
});

describe('пустые дни и журнал на экране', () => {
  it('у ленты — пустые дни словами; журнал есть — предупреждения нет', async () => {
    renderApp(`/publishing?channel=${REEL}`);
    const line = await screen.findByTestId('empty-days');
    // Подставная ExampleFilm: занято 11, 12, 13 и 15.10, сегодняшний 10.10 прошёл.
    expect(line).toHaveAttribute('data-count', '9');
    expect(line.textContent).toBe(
      `Пустых дней за 2${NBSP}недели: 9${NBSP}— 14.10, 16.10, 17.10, 18.10, 19.10, 20.10, 21.10, 22.10, 23.10`,
    );
    expect(screen.queryByTestId('journal-missing')).toBeNull();
  });

  it('всё занято — «нет» приглушённо; журнала нет — одно предупреждение над каналами', async () => {
    publish.fillReelDays();
    publish.state.journalMissing = true;
    renderApp(`/publishing?channel=${REEL}`);
    const feed = await screen.findByTestId('slot-feed');
    const line = await within(feed).findByTestId('empty-days');
    expect(line).toHaveAttribute('data-count', '0');
    expect(line).toHaveClass('text-muted-foreground');
    const warn = await screen.findByTestId('journal-missing');
    expect(warn).toHaveTextContent('Журнала загрузок нет — фабрика не видит, что уже выложено');
    expect(screen.getAllByTestId('journal-missing')).toHaveLength(1);
    expect(within(feed).queryByTestId('journal-missing')).toBeNull();
    expect(screen.getByTestId('publish-channels').contains(warn)).toBe(false);
  });

  it('журнала нет — предупреждение и у канала без слота (оно про фабрику)', async () => {
    publish.state.journalMissing = true;
    renderApp(`/publishing?channel=${SCIENCE}`);
    expect(await screen.findByText('У канала нет слота публикации')).toBeInTheDocument();
    expect(await screen.findByTestId('journal-missing')).toBeInTheDocument();
    expect(screen.getAllByTestId('journal-missing')).toHaveLength(1);
  });

  it('канал без слота — ни строки пустых дней', async () => {
    renderApp(`/publishing?channel=${SCIENCE}`);
    expect(await screen.findByText('У канала нет слота публикации')).toBeInTheDocument();
    expect(screen.queryByTestId('empty-days')).toBeNull();
  });

  it('CC-0149: у канала без строк в журнале — приглушённая строка в ленте', async () => {
    renderApp(`/publishing?channel=${SCIENCE}`);
    const feed = await screen.findByTestId('slot-feed');
    const line = await within(feed).findByTestId('journal-no-rows');
    expect(line.textContent).toBe(JOURNAL_NO_ROWS);
    expect(line.textContent).toBe('У канала ещё нет записей в журнале загрузок');
    expect(line).toHaveClass('text-muted-foreground');
    expect(screen.queryByTestId('journal-missing')).toBeNull();
  });

  it('CC-0149: строки в журнале есть — строки нет', async () => {
    renderApp(`/publishing?channel=${REEL}`);
    const feed = await screen.findByTestId('slot-feed');
    await within(feed).findByTestId('empty-days');
    expect(within(feed).queryByTestId('journal-no-rows')).toBeNull();
  });

  it('CC-0149: журнала нет — строки у канала нет, говорит одна плашка над каналами', async () => {
    publish.state.journalMissing = true;
    renderApp(`/publishing?channel=${SCIENCE}`);
    expect(await screen.findByTestId('journal-missing')).toBeInTheDocument();
    expect(screen.queryByTestId('journal-no-rows')).toBeNull();
  });
});
