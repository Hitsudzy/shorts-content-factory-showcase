// CC-0119: «Футаж по темам» на карточке батча — состояние словами, собрано из нужного, кадры
// против порога, последнее видео, причина; сводка; «по журналу» в подсказке; опрос и скелетон.
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { delay, http, HttpResponse } from 'msw';

import { RUNNING, STOPPED } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { server } from '@/mocks/server';
import { renderApp } from '@/test/renderApp';

import { countsLine, factsOf, stateWord } from './footageText';

const card = async (batch: string) => {
  await waitFor(() =>
    expect(screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)).toBeTruthy(),
  );
  return screen.getAllByTestId('open-batch').find((x) => x.dataset.batch === batch)!;
};
const row = (block: HTMLElement, id: string) =>
  within(block)
    .getAllByTestId('footage-topic')
    .find((x) => x.dataset.topic === id)!;

describe('CC-0119: футаж по темам', () => {
  it('слова: состояние, сводка, факты темы', () => {
    expect(stateWord({ state: 'short', state_ru: null })).toBe('не хватило');
    expect(stateWord({ state: 'odd', state_ru: null })).toBe('состояние неизвестно');
    expect(
      countsLine({
        counts: { short: 1, collected: 2 },
        topics: [{ topic_id: 'a', state: 'collected', state_ru: 'собрано' }],
      }),
    ).toBe('собрано 2 · не хватило 1');
    expect(
      factsOf({
        topic_id: 'a',
        state: 'short',
        collected: 3,
        needed: 4,
        usable_shots: 7,
        floor: 12,
        last_video: 'V',
      }),
    ).toEqual([
      { text: 'источников 3 из 4' },
      { text: '7 пригодных кадров (порог 12)', low: true },
      { text: 'последнее видео: V' },
    ]);
  });

  it('идущий батч: темы названиями, состояние, кадры против порога, причина, сводка', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    const block = await within(c).findByTestId('footage');
    expect(within(block).getByTestId('footage-counts')).toHaveTextContent(
      'собрано 1 · собирается 1 · в очереди 1 · не хватило 1 · отказано 1',
    );
    const done = row(block, 'vanguards-doomsday');
    expect(done).toHaveTextContent('Vanguards: Doomsday');
    expect(within(done).getByTestId('footage-state')).toHaveTextContent('собрано');
    expect(done).toHaveTextContent('источников 4 из 4');
    expect(done).toHaveTextContent('31 пригодный кадр (порог 12)');
    expect(done).toHaveTextContent('последнее видео: Vanguards: Doomsday — Teaser');
    const short = row(block, 'partition-s3');
    expect(within(short).getByTestId('footage-reason')).toHaveTextContent(
      'Почему не хватило: пул тоньше сценария — пригодных кадров меньше порога: 7 из 12',
    );
    expect(short).not.toHaveTextContent('pool_too_thin');
    expect(within(row(block, 'the-running-man')).getByTestId('footage-reason')).toHaveTextContent(
      'Почему отказано: у всех найденных роликов лицензия не подходит каналу',
    );
    // CC-0113: код без строки фабрики, но с русским уточнением — уточнение, кода не видно.
    expect(row(block, 'the-running-man')).not.toHaveTextContent('licence_refused');
    // Темы нет среди тем батча — id словами.
    expect(row(block, 'one-battle-after-another')).toHaveTextContent('One battle after another');
    expect(within(block).queryByTestId('footage-source')).toBeNull();
  });

  it('по журналу (source: events) — «восстановлено по журналу» с подсказкой', async () => {
    batches.setFootage(RUNNING, { source: 'events' });
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(RUNNING);
    const src = await within(c).findByTestId('footage-source');
    expect(src).toHaveTextContent('восстановлено по журналу');
    await user.hover(src);
    expect(await screen.findByRole('tooltip')).toHaveTextContent('Восстановлено по журналу');
  });

  it('пока батч идёт — опрос; у стоящего без футажа блока нет и опроса нет', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    await within(c).findByTestId('footage');
    await waitFor(
      () => expect(batches.footageCalls.filter((b) => b === RUNNING).length).toBeGreaterThan(1),
      { timeout: 5000 },
    );
    const stopped = await card(STOPPED);
    expect(within(stopped).queryByTestId('footage')).toBeNull();
    expect(batches.footageCalls.filter((b) => b === STOPPED)).toHaveLength(1);
  });

  it('скелетон, пока ответ не пришёл', async () => {
    server.use(
      http.get('*/api/batches/:c/:b/footage', async () => {
        await delay('infinite');
        return HttpResponse.json({});
      }),
    );
    renderApp('/batches');
    const c = await card(RUNNING);
    const block = await within(c).findByTestId('footage');
    expect(within(block).getByRole('status')).toHaveTextContent('Читаю сбор футажа…');
  });
});
