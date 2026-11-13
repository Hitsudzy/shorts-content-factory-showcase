// CC-0175: `card_build.why` («code: line; code: line») — части, русская строка или код словами.
import { ACCEPT_BUILD_WHY } from '@/mocks/cards';

import { buildRefusalsText, buildWhyPartText, buildWhyText, parseBuildWhy } from './buildWhy';

describe('CC-0175: почему автосборка карточки не запустилась', () => {
  it('«code: line; code: line» → части; «;» внутри строки часть не рвёт', () => {
    expect(parseBuildWhy('no_card: нет карточки; draft_problems: a; b; c')).toEqual([
      { code: 'no_card', line: 'нет карточки' },
      { code: 'draft_problems', line: 'a; b; c' },
    ]);
    expect(parseBuildWhy('просто строка')).toEqual([{ code: null, line: 'просто строка' }]);
    expect(parseBuildWhy(null)).toEqual([]);
    expect(parseBuildWhy(undefined)).toEqual([]);
    expect(parseBuildWhy('  ')).toEqual([]);
  });

  it('русская строка — как есть; английская — код словами центра; неизвестный код — строка', () => {
    expect(buildWhyPartText({ code: 'model_refused', line: 'Модель молчит.' })).toBe(
      'Модель молчит',
    );
    expect(buildWhyPartText({ code: 'claims_failed', line: 'claim check failed' })).toBe(
      'не прошла проверка утверждений',
    );
    expect(buildWhyPartText({ code: 'spawn_failed', line: 'fork: EAGAIN' })).toBe(
      'Фабрика не смогла запустить сборку',
    );
    expect(buildWhyPartText({ code: 'weird_new', line: 'something odd' })).toBe('something odd');
    expect(buildWhyPartText({ code: 'weird_new', line: '' })).toBe('фабрика отказала');
  });

  it('строкой: причины через «; » с маленькой буквы, повторы — один раз; нет why — null', () => {
    expect(buildWhyText(ACCEPT_BUILD_WHY)).toBe(
      'модель не написала черновик карточки — ответ пустой; не прошла проверка утверждений',
    );
    expect(buildWhyText('spawn_failed: x; spawn_failed: y')).toBe(
      'фабрика не смогла запустить сборку',
    );
    expect(buildWhyText(null)).toBeNull();
  });

  it('ответ без why: коды refusals словами центра, неизвестный — «фабрика отказала»', () => {
    expect(buildRefusalsText(['model_refused', 'claims_failed', 'odd', 'odd2'])).toBe(
      'модель не написала черновик; не прошла проверка утверждений; фабрика отказала',
    );
    expect(buildRefusalsText(['spawn_failed'])).toBe('фабрика не смогла запустить сборку');
    expect(buildWhyText('')).toBeNull();
  });
});
