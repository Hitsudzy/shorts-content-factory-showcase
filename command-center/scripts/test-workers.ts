import { availableParallelism } from 'node:os';

// CC-0042: сколько параллельных воркеров дают тестам Vitest (`maxWorkers`) и Playwright
// (`workers`). Штатно оба берут почти все ядра — рядом с полным прогоном фабрики (load до 110)
// это лишняя конкуренция, и тесты падают по таймауту. По умолчанию — половина ядер;
// `CC_TEST_WORKERS=<n>` задаёт число явно (CI, слабая машина, отладка — `1`).

export const WORKERS_ENV = 'CC_TEST_WORKERS';

export function testWorkers(
  env: Record<string, string | undefined> = process.env,
  cpus: number = availableParallelism(),
): number {
  const raw = env[WORKERS_ENV]?.trim();
  if (raw) {
    if (!/^\d+$/.test(raw) || Number(raw) < 1) {
      throw new Error(`${WORKERS_ENV}=${raw}: нужно целое число воркеров ≥ 1`);
    }
    return Number(raw);
  }
  return Math.max(1, Math.floor(cpus / 2));
}
