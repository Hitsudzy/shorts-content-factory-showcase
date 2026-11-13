// @vitest-environment node
import { describe, expect, it } from 'vitest';

import { testWorkers } from './test-workers.ts';

describe('testWorkers (CC_TEST_WORKERS)', () => {
  it('по умолчанию — половина ядер, но не меньше одного', () => {
    expect(testWorkers({}, 12)).toBe(6);
    expect(testWorkers({}, 7)).toBe(3);
    expect(testWorkers({}, 1)).toBe(1);
    expect(testWorkers({ CC_TEST_WORKERS: '  ' }, 8)).toBe(4);
  });

  it('переменная задаёт число явно', () => {
    expect(testWorkers({ CC_TEST_WORKERS: '1' }, 12)).toBe(1);
    expect(testWorkers({ CC_TEST_WORKERS: '16' }, 12)).toBe(16);
  });

  it('мусор в переменной — ошибка, а не тихое значение по умолчанию', () => {
    for (const bad of ['0', '-2', '50%', 'two', '1.5']) {
      expect(() => testWorkers({ CC_TEST_WORKERS: bad }, 12)).toThrow(/CC_TEST_WORKERS/);
    }
  });
});
