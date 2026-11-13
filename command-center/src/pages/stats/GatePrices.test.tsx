import { screen, within } from '@testing-library/react';

import { gates } from '@/mocks/handlers';
import { renderApp } from '@/test/renderApp';

import { basisText, decisionText, priceText, ruleText, signatureText } from './gateWords';

describe('цена воротец словами (CC-0115 → CC-0100)', () => {
  it('цена, окно, подпись, решение', () => {
    expect(priceText({ price: 3, ready: 15 })).toBe('убил бы 3 из 15 готовых роликов');
    expect(priceText({ price: 1, ready: 1 })).toBe('убил бы 1 из 1 готового ролика');
    expect(priceText({ price: 0, ready: 15 })).toBe('не убил бы ни одного из 15 готовых роликов');
    expect(priceText({ price: null, ready: 0 })).toBe('не измерена');
    expect(basisText({ measured_on: 4, of: 5 })).toBe('по 4 из 5 батчей окна');
    expect(basisText({ measured_on: 0, of: 5 })).toBe(
      'ни один из 5 батчей окна не мог её показать',
    );
    expect(signatureText({ date: '2026-10-05', price: 1 })).toBe(
      'Подписано 05.10: можно терять 1 готовый ролик',
    );
    expect(decisionText({ date: '2026-09-28', mode: 'warn' })).toBe(
      'Решение 28.09: предупреждение',
    );
    expect(ruleText('x.unknown')).toBe('Правило воротец без имени в центре');
  });
});

describe('«Статистика»: цена воротец', () => {
  it('правила словами, вердикт, цена, подпись; имена правил — под «подробнее»', async () => {
    renderApp('/stats?channel=example-film');
    const card = await screen.findByTestId('gate-prices');
    const rows = await within(card).findAllByTestId('gate-rule');
    expect(rows).toHaveLength(5);
    expect(card).toHaveTextContent('Воротца · окно — последние 5 батчей · ждут подписи: 1');
    const tail = rows[0]!;
    expect(tail).toHaveTextContent('Речь после последнего кадра-якоря');
    expect(tail).toHaveTextContent('ждёт подписи');
    expect(tail).toHaveTextContent('предупреждение');
    expect(within(tail).getByTestId('gate-price')).toHaveTextContent(
      'Отказ убил бы 3 из 15 готовых роликов',
    );
    expect(within(rows[1]!).getByTestId('gate-signed')).toHaveTextContent(
      'Подписано 05.10: можно терять 1 готовый ролик',
    );
    expect(within(rows[2]!).getByTestId('gate-price')).toHaveTextContent('Цена не измерена');
    expect(within(rows[4]!).getByTestId('gate-signed')).toHaveTextContent(
      'сейчас фабрика: только замеряет',
    );
    expect(within(tail).getByText(/^правило: content_researcher/)).not.toBeVisible();
    expect(within(card).getByTestId('gate-unregistered')).toHaveTextContent(
      'Ваши решения, которые сейчас не пересчитать',
    );
    expect(within(card).queryByTestId('gate-no-proposals')).not.toBeInTheDocument();
    expect(within(card).getByTestId('gate-unregistered')).toHaveTextContent(
      'Субтитры поверх текста в кадреРешение 21.09: предупреждение',
    );
  });

  it('предложений на подпись нет (CF-0743) — спокойная строка, без «ждёт подписи»', async () => {
    gates.state.noProposals = true;
    renderApp('/stats?channel=example-film');
    const card = await screen.findByTestId('gate-prices');
    expect(await within(card).findByTestId('gate-no-proposals')).toHaveTextContent(
      'Цен, ждущих вашей подписи, нет.',
    );
    expect(card).not.toHaveTextContent('ждёт подписи');
    expect(card).not.toHaveTextContent('ждут подписи');
    expect(within(card).getAllByTestId('gate-rule')).toHaveLength(5);
  });

  it('фабрика не посчитала — ошибка с её словами', async () => {
    gates.state.broken = true;
    renderApp('/stats?channel=example-film');
    const card = await screen.findByTestId('gate-prices');
    expect(await within(card).findByText('Цену воротец не посчитать')).toBeInTheDocument();
    expect(card).toHaveTextContent('Фабрика не посчитала цену воротец.');
  });
});
