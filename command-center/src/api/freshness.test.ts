import {
  agoText,
  freshnessText,
  recheckDelay,
  recheckWhileChecking,
  RECHECK_MAX,
} from './freshness';

type L = { checking: boolean; age_s: number };
const q = (data: L | undefined, at: number, error: unknown = null) => ({
  state: { data, dataUpdatedAt: at, error },
});

describe('свежесть блокировки (договор 0.5.0)', () => {
  it('паузы переспроса растут и кончаются', () => {
    expect([1, 2, 3, 4, 5, 6, 7].map(recheckDelay)).toEqual([
      3000, 5000, 8000, 13000, 20000, 30000, 30000,
    ]);
    expect(recheckDelay(RECHECK_MAX + 1)).toBe(false);
    expect(recheckDelay(0)).toBe(false);
  });

  it('переспрос — только пока `checking`; счёт по новым ответам, не по вызовам', () => {
    const every = recheckWhileChecking<L>((d) => d);
    const query = q({ checking: true, age_s: 40 }, 1);
    expect(every(query)).toBe(3000);
    expect(every(query)).toBe(3000); // тот же ответ — та же пауза
    query.state = q({ checking: true, age_s: 43 }, 2).state;
    expect(every(query)).toBe(5000);
    query.state = q({ checking: false, age_s: 0 }, 3).state;
    expect(every(query)).toBe(false);
    query.state = q({ checking: true, age_s: 31 }, 4).state;
    expect(every(query)).toBe(3000); // новая серия — сначала
    expect(every(q(undefined, 0))).toBe(false);
    expect(every(q({ checking: true, age_s: 1 }, 5, new Error('x')))).toBe(false);
  });

  it('текст: «проверено N назад», «уже проверяет заново»', () => {
    expect(agoText(4.2)).toBe('4 с');
    expect(agoText(125)).toBe('2 мин');
    expect(agoText(7300)).toBe('2 ч');
    expect(freshnessText({ checked_at: 'x', age_s: 4.2, checking: false })).toBe(
      'проверено 4 с назад',
    );
    expect(freshnessText({ checked_at: 'x', age_s: 40, checking: true }, 30)).toBe(
      'проверено 1 мин назад, фабрика уже проверяет заново',
    );
    expect(freshnessText({ checking: false })).toBeNull();
    expect(freshnessText(undefined)).toBeNull();
  });
});
