import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { PAST, PAST_REBUILD } from '@/mocks/batches';
import { batches } from '@/mocks/handlers';
import { summaryReply } from '@/mocks/runSummary';
import { renderApp } from '@/test/renderApp';

import { summaryView } from './runSummaryText';

const openRun = async (batch: string) => {
  const run = (await screen.findAllByTestId('run')).find((r) => r.dataset.batch === batch)!;
  await userEvent.click(within(run).getAllByRole('button')[0]!);
  return within(run).findByTestId('run-summary');
};

describe('сводка прогона словами (CC-0115 → CC-0099)', () => {
  it('время, воронка, тиры и замечания из разделов runlog summary', () => {
    const v = summaryView(summaryReply(PAST, 'full').data)!;
    expect(v.time).toMatchObject({
      wall: '5\u00a0ч 26\u00a0мин',
      live: '4\u00a0ч 12\u00a0мин',
      gaps: { count: 1, span: '1\u00a0ч 14\u00a0мин', share: 22.6 },
      waits: { count: 1, span: '21\u00a0мин' },
      operator: { span: '25\u00a0мин', share: 7.7 },
    });
    expect(v.funnel.map((s) => `${s.count} ${s.label}`)).toEqual([
      '7 найдено',
      '5 отобрано',
      '5 прошли проверку тем',
      '5 с двумя источниками',
      '5 сценарии',
      '5 смонтировано',
      '4 прошли проверку кадров',
    ]);
    expect(v.funnelLine).toBe('1 из 5 тем потеряна по пути');
    // CC-0113: без карты ответа — строки фабрики из `lost[].reason_ru`, больше — выше.
    expect(v.losses.map((l) => `${l.text} ×${l.count}`)).toEqual([
      'за темой не нашлось факта, проходящего правило фактов ×2',
      'судья кадров нашёл брак футажа из жёсткого списка ×1',
      'о событии темы нет опорного текста (статьи или описания эпизода) ×1',
    ]);
    expect(v.tiers.map((t) => `${t.tier}${t.count}`)).toEqual(['S1', 'C1', 'D1', 'E1', 'F1']);
    expect(v.attention.map((a) => a.text)).toEqual([
      'Батч стоял без причины: 1\u00a0ч 14\u00a0мин',
      'Проверки после батча: 5 из 28 не зелёные',
      'Код фабрики менялся во время прогона: 1 раз',
    ]);
  });

  it('CC-0113: потери — словами `funnel_reasons_ru`; null и незнакомый код — «причина без описания»', () => {
    const data = {
      funnel: { steps: [], losses: { no_fact: 1, legacy_drop: 2, judge_footage_defect: 1 } },
    };
    const v = summaryView(data, { no_fact: 'нет факта', judge_footage_defect: null })!;
    expect(v.losses).toEqual([
      { code: 'legacy_drop', text: 'причина без описания', count: 2 },
      { code: 'judge_footage_defect', text: 'причина без описания', count: 1 },
      { code: 'no_fact', text: 'нет факта', count: 1 },
    ]);
  });

  it('чистый прогон — без замечаний; чужой вид разделов — не ошибка', () => {
    const v = summaryView(summaryReply(PAST, 'clean').data)!;
    expect(v.funnelLine).toBe('все 3 темы дошли до конца');
    expect(v.attention).toEqual([]);
    expect(summaryView({ times: 'x', funnel: { steps: [{ step: 1 }] }, scores: {} })).toEqual({
      time: null,
      funnel: [],
      funnelLine: null,
      losses: [],
      tiers: [],
      attention: [],
      lines: [],
    });
    expect(summaryView(null)).toBeNull();
  });

  it('раскрытый прошлый прогон: сводка словами, коды и файл — под «подробнее»', async () => {
    renderApp('/batches');
    const block = await openRun(PAST);
    const facts = within(block).getAllByTestId('summary-fact');
    expect(facts.map((f) => f.textContent)).toEqual([
      'Шёл5\u00a0ч 26\u00a0мин',
      'Работал4\u00a0ч 12\u00a0мин',
      'Простои1\u00a0ч 14\u00a0мин · 22,6 %',
      'Ждал вас21\u00a0мин',
      'Оператор думал25\u00a0мин · 7,7 %',
    ]);
    expect(within(block).getByTestId('summary-funnel-line')).toHaveTextContent(
      '1 из 5 тем потеряна по пути',
    );
    expect(within(block).getAllByTestId('summary-step')).toHaveLength(7);
    // CC-0113: почему потеряны — строками фабрики, кодов на виду нет.
    expect(
      within(block)
        .getAllByTestId('summary-loss')
        .map((l) => l.textContent),
    ).toEqual([
      'за темой не нашлось факта, проходящего правило фактов\u00a0×\u00a02',
      'судья кадров нашёл брак футажа из жёсткого списка',
      'о событии темы нет опорного текста (статьи или описания эпизода)',
    ]);
    expect(within(block).getByTestId('summary-losses')).not.toHaveTextContent('no_fact');
    expect(
      within(block)
        .getAllByTestId('summary-tier')
        .map((t) => t.textContent),
    ).toEqual(['S × 1', 'C × 1', 'D × 1', 'E × 1', 'F × 1']);
    // CC-0131: что значат «S × 1» — тултипом у подписи.
    expect(within(block).getByTestId('summary-tiers-legend')).toHaveAttribute('tabindex', '0');
    expect(within(block).getByTestId('summary-tiers-key')).toHaveTextContent(
      'S — лучшая оценка, F — худшая',
    );
    expect(within(block).getByTestId('summary-attention')).toHaveTextContent(
      'Проверки после батча: 5 из 28 не зелёные',
    );
    // Имена файлов, строки фабрики, слаги — не на виду.
    const more = block.querySelector('details[data-slot="more"]')!;
    expect(more).not.toHaveAttribute('open');
    expect(within(block).getByTestId('summary-file')).not.toBeVisible();
    expect(block.textContent).toContain('RUN_SUMMARY.md');
    expect(within(block).getAllByText(/^GAPS: 1/)[0]).not.toBeVisible();
    expect(batches.summaryCalls).toEqual([PAST]);
  });

  it('событий ещё нет — так и сказано; посчитать не вышло — отказ, файл под «подробнее»', async () => {
    renderApp('/batches');
    const none = await openRun(PAST_REBUILD);
    expect(within(none).getByTestId('summary-note')).toHaveTextContent(
      'Сводки ещё нет: у батча пока нет событий прогона.',
    );
    expect(none).toHaveTextContent('RUN_SUMMARY.md ещё нет');
    const broken = await openRun('example-film/2026-10-06T0210Z');
    expect(within(broken).getByRole('alert')).toHaveTextContent('Сводку не посчитать');
    expect(within(broken).getByRole('alert')).toHaveTextContent("KeyError: 'stage'");
    expect(within(broken).getByTestId('summary-file')).toBeInTheDocument();
  });
});
