import { CONTRACT } from '@/api/contract.gen';

import { mockGet } from './handlers';

describe('подставной API типизирован контрактом', () => {
  it('мок не той формы — ошибка типов (держит tsc в npm run typecheck)', () => {
    // Каждая строка обязана НЕ компилироваться: если ошибка пропадёт, @ts-expect-error
    // сам станет ошибкой и typecheck упадёт.
    const wrong = [
      // @ts-expect-error — нет обязательного `api`
      mockGet('/api/health', { status: 'ok' }),
      // @ts-expect-error — `status` в контракте — константа "ok"
      mockGet('/api/health', { status: 'fine', api: CONTRACT.version }),
      // @ts-expect-error — лишнее поле
      mockGet('/api/health', { status: 'ok', api: CONTRACT.version, extra: 1 }),
      // @ts-expect-error — тело 403 — Refusal, guard из перечня
      mockGet('/api/session', { detail: 'нет', guard: 'csrf' }, 403),
      // @ts-expect-error — такой ручки нет в контракте
      mockGet('/api/nope', {}),
    ];
    expect(wrong).toHaveLength(5);
  });

  it('мок по контракту компилируется', () => {
    expect(mockGet('/api/session', { detail: 'нет сессии', guard: 'session' }, 403)).toBeDefined();
  });
});
