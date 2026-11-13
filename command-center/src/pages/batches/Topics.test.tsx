import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import type { ReactNode } from 'react';

import { useBatchTopics, useTopicsRefresh } from '@/api/batchTopics';
import { PAST, RUNNING, STOPPED } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

const card = async (batch: string) => {
  const all = await screen.findAllByTestId('open-batch');
  const c = all.find((x) => x.dataset.batch === batch);
  if (!c) throw new Error(`нет карточки ${batch}`);
  return c;
};

describe('«Батчи»: темы батча (CC-0092)', () => {
  it('блок «Темы»: тема, сигнал, состояние, источники, отсеянные, расход поиска', async () => {
    renderApp('/batches');
    const c = await card(RUNNING);
    const block = await within(c).findByTestId('topics');
    expect(block).toHaveTextContent('в работе 2 · в резерве 1');
    expect(within(block).getByTestId('topics-quota')).toHaveTextContent(
      'Поиск YouTube: батч потратил 9 поисков · квота дня 100, осталось 60',
    );
    const rows = within(block).getAllByTestId('topic');
    expect(rows).toHaveLength(3);
    expect(rows[0]).toHaveTextContent('Vanguards: Doomsday');
    expect(rows[0]).toHaveTextContent('фильм · 2026');
    expect(within(rows[0]!).getByTestId('topic-signal')).toHaveTextContent('сигнал 82');
    expect(within(rows[0]!).getByTestId('topic-state')).toHaveTextContent('в работе: монтаж');
    expect(within(rows[2]!).getByTestId('topic-state')).toHaveTextContent('в резерве');
    const links = within(within(rows[0]!).getByTestId('topic-sources')).getAllByRole('link');
    expect(links.map((a) => a.textContent)).toEqual(['Variety', 'Deadline']);
    expect(links[0]).toHaveAttribute('target', '_blank');
    // Отсеянные — свёрнуты, с причиной по-русски; сырой код — под «подробнее».
    const skipped = within(block).getByTestId('topics-skipped');
    expect(skipped).not.toHaveAttribute('open');
    expect(skipped).toHaveTextContent('Отсеяны при подборе тем: 3');
    expect(within(skipped).getAllByTestId('skipped-topic')[0]).toHaveTextContent(
      'The Running Manсигнал 61отсеяна: нет факта',
    );
    // Пересборка без тем — блока нет.
    const stopped = await card(STOPPED);
    await waitFor(() => expect(batches.topicCalls).toContain(STOPPED));
    expect(within(stopped).queryByTestId('topics')).not.toBeInTheDocument();
  });

  it('итоги этапов в киноленте; клик по итогу ведёт к темам', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(RUNNING);
    await within(c).findByTestId('topics');
    const frames = within(within(c).getByTestId('film-strip')).getAllByRole('listitem');
    expect(within(frames[0]!).getByTestId('frame-summary')).toHaveTextContent(
      'нашёл 6 тем, взял 3, отсеял 3проверку прошли 2 из 3в резерве 1',
    );
    // Готовый кадр с итогом этапа — и «готово» с длительностью (CC-0126: готово видно сразу).
    expect(within(frames[0]!).getByTestId('frame-small')).toHaveTextContent('готово · 1 ч');
    expect(within(frames[1]!).getByTestId('frame-summary')).toHaveTextContent(
      'футажа хватает: 1 из 2',
    );
    expect(within(frames[4]!).getByTestId('frame-summary')).toHaveTextContent(
      'проверку прошли 2 из 2',
    );
    expect(within(frames[5]!).queryByTestId('frame-summary')).not.toBeInTheDocument();
    await user.click(within(frames[0]!).getByTestId('frame-summary'));
    expect(within(c).getByTestId('topics')).toHaveFocus();
  });

  it('клик по теме — подробности: сцены, факт и источник, проверки, футаж', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(RUNNING);
    const row = (await within(c).findAllByTestId('topic'))[0]!;
    const open = within(row).getByTestId('topic-open');
    expect(open).toHaveAttribute('aria-expanded', 'false');
    await user.click(open);
    expect(open).toHaveAttribute('aria-expanded', 'true');
    const d = await within(row).findByTestId('topic-details');
    expect(within(d).getAllByRole('listitem').length).toBeGreaterThan(4);
    expect(within(d).getByTestId('topic-scenes')).toHaveTextContent('Доктор Дум впервые без маски');
    expect(within(d).getByTestId('topic-fact')).toHaveTextContent('202 млн просмотров');
    expect(within(d).getByTestId('topic-fact')).toHaveTextContent('источник: Variety');
    // CC-0119: не прошедшие проверку кандидаты — причины словами фабрики, код — в подсказке.
    const block = within(d).getByTestId('fact-failed');
    expect(block).toHaveTextContent('Отклонённые кандидаты — не прошли проверку факта:');
    const failed = within(d).getAllByTestId('fact-failed-candidate');
    expect(failed.map((x) => x.textContent)).toEqual([
      '✕«Фильм самый дорогой в истории студии» — нет конкретики (числа, даты или имени) — похоже на мнение и ещё одна причина без описания',
      '✕«Сборы первого уик-энда превысили» — предложение обрезано',
    ]);
    expect(
      within(d)
        .getAllByTestId('fact-failure')
        .map((x) => x.dataset.code),
    ).toEqual(['no_specifics', 'cut_short']);
    expect(within(d).getByTestId('fact-failure-undescribed')).toHaveAttribute('data-codes', 'tier');
    expect(within(d).getByTestId('fact-failed')).not.toHaveTextContent(
      /cut_short|tier|no_specifics/,
    );
    expect(within(d).getByTestId('topic-checks')).toHaveTextContent(
      'Проверка темы: пропущена в батч',
    );
    expect(within(d).getByTestId('topic-checks')).toHaveTextContent('Сценарий: прошёл проверку');
    expect(within(d).getByTestId('topic-footage')).toHaveTextContent(
      'годных 45 кадров из 70, нужно 24 — хватает',
    );
    expect(within(d).getByTestId('topic-footage')).toHaveTextContent('поисков YouTube на тему: 4');
    expect(batches.topicCalls).toContain(`${RUNNING}#vanguards-doomsday`);
    await user.click(open);
    expect(within(row).queryByTestId('topic-details')).not.toBeInTheDocument();
  });

  it('CC-0170: флаг чувствительности — со сценами темы или «вся тема»', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const c = await card(RUNNING);
    const rows = await within(c).findAllByTestId('topic');
    const of = (id: string) => rows.find((r) => r.dataset.topic === id)!;
    await user.click(within(of('delver')).getByTestId('topic-open'));
    const d = await within(of('delver')).findByTestId('topic-checks');
    expect(d).toHaveTextContent(
      'Чувствительная тема: кадры обвала с пострадавшими; сцены sc2, sc3',
    );
    await user.click(within(of('partition-s3')).getByTestId('topic-open'));
    const w = await within(of('partition-s3')).findByTestId('topic-checks');
    expect(w).toHaveTextContent('Чувствительная тема: сцены насилия в офисе; вся тема');
    await user.click(within(of('vanguards-doomsday')).getByTestId('topic-open'));
    const a = await within(of('vanguards-doomsday')).findByTestId('topic-checks');
    expect(a).not.toHaveTextContent('Чувствительная тема');
  });

  it('битый файл этапа: понятная строка, код и путь — под «подробнее»', async () => {
    batches.setTopics(RUNNING, 'broken');
    renderApp('/batches');
    const c = await card(RUNNING);
    const block = await within(c).findByTestId('topics');
    const alert = within(block).getByRole('alert');
    expect(alert).toHaveAttribute('data-code', 'stage_broken');
    expect(alert).toHaveTextContent('Темы батча не читаются');
    expect(within(alert).getByTestId('refusal-message')).toHaveTextContent(
      'Данные этапа «Проверка тем» не читаются',
    );
    expect(within(alert).getByTestId('refusal-message')).not.toHaveTextContent('json');
    expect(within(block).getByTestId('topics-broken-hint')).toHaveTextContent(
      'Темы появятся сами, когда этап перезапишет свои данные',
    );
    expect(within(c).queryByTestId('frame-summary')).not.toBeInTheDocument();
  });

  it('история: темы закрытого прогона — до проверки кадров', async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const runs = await screen.findAllByTestId('run');
    const run = runs.find((r) => r.dataset.batch === PAST)!;
    await user.click(within(run).getAllByRole('button')[0]!);
    const block = await within(run).findByTestId('topics');
    expect(block).toHaveTextContent('готово 1 · в резерве 1 · отсеяно позже 1');
    const states = within(block).getAllByTestId('topic-state');
    expect(states.map((s) => s.textContent)).toEqual([
      'ролик готов',
      'отсеяна: не прошла проверку кадров',
      'в резерве',
    ]);
  });
});

describe('ремонт роликов и добор тем (CC-0172, договор 0.75.0)', () => {
  const openPast = async () => {
    const user = userEvent.setup();
    renderApp('/batches');
    const runs = await screen.findAllByTestId('run');
    const run = runs.find((r) => r.dataset.batch === PAST)!;
    await user.click(within(run).getAllByRole('button')[0]!);
    return { user, block: await within(run).findByTestId('topics') };
  };

  it('сводка батча: ремонт и добор, раунды раскрываются', async () => {
    batches.setFunnel(PAST);
    const { user, block } = await openPast();
    const funnel = within(block).getByTestId('topics-funnel');
    expect(within(funnel).getByTestId('topics-repairs')).toHaveTextContent(
      'Ремонт роликов после проверки кадров: удался 1, не удался 1',
    );
    const refill = within(funnel).getByTestId('topics-refill');
    expect(refill).toHaveTextContent('Добор ниже шорт-листа: подано 1, поисков 4 · раундов 2');
    expect(refill).not.toHaveAttribute('open');
    await user.click(within(refill).getByTestId('topics-refill-text'));
    expect(refill).toHaveAttribute('open');
    const rounds = within(refill).getAllByTestId('refill-round');
    expect(rounds[0]).toHaveTextContent(
      'первый раунд: темы поданы — Partition; нужно 1 — шорт-лист дал 2 темы из 3; 3 поиска',
    );
    expect(rounds[1]).toHaveTextContent(
      'после судьи кадров: квота поиска на сегодня кончилась (квоты поиска на тему не хватило)',
    );
    // Коды раундов — только под «подробнее».
    expect(within(refill).getByText(/after_compliance/)).not.toBeVisible();
  });

  it('темы: пометка «добор», ремонт в проверках, отказ добора с причиной', async () => {
    batches.setFunnel(PAST);
    const { user, block } = await openPast();
    const rows = within(block).getAllByTestId('topic');
    expect(within(rows[0]!).getByTestId('topic-state')).toHaveTextContent(
      'ролик готов после ремонта',
    );
    expect(within(rows[1]!).getByTestId('topic-state')).toHaveTextContent(
      'отсеяна: не прошла проверку кадров; ремонт не удался',
    );
    expect(within(rows[0]!).queryByTestId('topic-refill')).not.toBeInTheDocument();
    expect(within(rows[2]!).getByTestId('topic-refill')).toHaveTextContent('добор');

    await user.click(within(rows[0]!).getByTestId('topic-open'));
    const checks = await within(rows[0]!).findByTestId('topic-checks');
    expect(within(checks).getByTestId('topic-repair')).toHaveTextContent(
      'Отремонтирован: блоки 5, 14 (полоса)',
    );
    expect(checks).toHaveTextContent('Проверка кадров: кадры прошли');
    await user.click(within(rows[1]!).getByTestId('topic-open'));
    const failed = await within(rows[1]!).findByTestId('topic-checks');
    expect(within(failed).getByTestId('topic-repair')).toHaveTextContent(
      'Ремонт не удался — отказ (замены для блока 9 в пуле не нашлось)',
    );
    await user.click(within(rows[2]!).getByTestId('topic-open'));
    expect(await within(rows[2]!).findByTestId('topic-refill-detail')).toHaveTextContent(
      'Тема была ниже шорт-листа — батч добрал её (первый раунд).',
    );

    const skipped = within(block).getByTestId('topics-skipped');
    expect(skipped).toHaveTextContent('Отсеяны при подборе тем: 5');
    const list = within(skipped).getAllByTestId('skipped-topic');
    const tron = list.find((x) => x.textContent?.includes('Grid: Ares'))!;
    // Строка фабрики уже говорит об отказе добора — своей строки нет.
    expect(within(tron).getByTestId('skipped-state')).toHaveTextContent(
      'не вошла в шорт-лист; добор: отказ (права на трейлер не подтверждены)',
    );
    expect(within(tron).queryByTestId('topic-refill-note')).not.toBeInTheDocument();
    const battle = list.find((x) => x.textContent?.includes('One Battle After Another'))!;
    expect(within(battle).getByTestId('topic-refill-note')).toHaveTextContent(
      'добор: не хватило квоты поиска',
    );
  });

  it('CC-0175: записи раундов нет — сводки добора нет, ремонт и пометки тем — на месте', async () => {
    batches.setFunnel(PAST);
    batches.setRefillNoRounds(PAST);
    const { block } = await openPast();
    const funnel = within(block).getByTestId('topics-funnel');
    expect(within(funnel).getByTestId('topics-repairs')).toBeInTheDocument();
    expect(within(funnel).queryByTestId('topics-refill')).not.toBeInTheDocument();
    expect(funnel).not.toHaveTextContent('Добор ниже шорт-листа');
    expect(
      within(within(block).getAllByTestId('topic')[2]!).getByTestId('topic-refill'),
    ).toHaveTextContent('добор');
  });

  it('старый батч без этих полей — ни сводки, ни пометок, ни строк ремонта', async () => {
    const { user, block } = await openPast();
    expect(within(block).queryByTestId('topics-funnel')).not.toBeInTheDocument();
    expect(within(block).queryByTestId('topic-refill')).not.toBeInTheDocument();
    expect(within(block).queryByTestId('topic-refill-note')).not.toBeInTheDocument();
    const rows = within(block).getAllByTestId('topic');
    await user.click(within(rows[0]!).getByTestId('topic-open'));
    await within(rows[0]!).findByTestId('topic-checks');
    expect(within(rows[0]!).queryByTestId('topic-repair')).not.toBeInTheDocument();
    expect(within(rows[0]!).queryByText('Добор')).not.toBeInTheDocument();
  });
});

describe('темы обновляются вместе с экраном батча', () => {
  const wrap = () => {
    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={qc}>{children}</QueryClientProvider>
    );
  };

  it('новый ответ опроса идущего батча перечитывает темы; без него — нет; закрытый — нет', async () => {
    const wrapper = wrap();
    const { rerender } = renderHook(
      ({ tick, going }: { tick: number; going: boolean }) => {
        useTopicsRefresh(RUNNING, going, tick);
        return useBatchTopics(RUNNING);
      },
      { wrapper, initialProps: { tick: 1, going: true } },
    );
    const calls = () => batches.topicCalls.filter((x) => x === RUNNING).length;
    await waitFor(() => expect(calls()).toBe(1));
    rerender({ tick: 1, going: true });
    await new Promise((r) => setTimeout(r, 50));
    expect(calls()).toBe(1);
    rerender({ tick: 2, going: true });
    await waitFor(() => expect(calls()).toBe(2));
    rerender({ tick: 3, going: false });
    await new Promise((r) => setTimeout(r, 50));
    expect(calls()).toBe(2);
  });
});
