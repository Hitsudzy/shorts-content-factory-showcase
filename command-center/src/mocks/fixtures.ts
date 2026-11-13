// Подставные ответы API, типизированные сгенерированными типами контракта (CC-0004):
// поменялся контракт и перегенерировали типы — расхождение здесь станет ошибкой типов.
// Общие для Vitest (src/mocks/handlers.ts) и Playwright (tests/e2e/fixtures.ts), поэтому
// импорты относительные, без алиаса `@`.
import type { components } from '../api/schema.gen';
import { CONTRACT } from '../api/contract.gen';
import { API_FACTORY_COMMIT_NOW, API_PROCESS } from './versions';

type Schemas = components['schemas'];

export const SESSION_TOKEN = 'test-session-token';

/** Рабочая фабрика: API пишет (CC-0058). */
const WRITES = { writes: true, writes_reason: null, writes_dev: false } as const;

/** Причина «только смотреть», как её даёт `is_working_factory` из рабочей копии (CC-0059). */
export const READ_ONLY_REASON = 'это рабочая копия разработки (.../cc-api), а не рабочая фабрика';

/** Режимы записи для `/api/health` (CC-0059): рабочая фабрика, «только смотреть», флаг разработки. */
export const writesModes = {
  on: WRITES,
  off: { writes: false, writes_reason: READ_ONLY_REASON, writes_dev: false },
  dev: { writes: true, writes_reason: READ_ONLY_REASON, writes_dev: true },
} satisfies Record<string, Pick<Schemas['Health'], 'writes' | 'writes_reason' | 'writes_dev'>>;

export const fixtures = {
  health: { status: 'ok', api: CONTRACT.version, ...WRITES },
  version: {
    api: CONTRACT.version,
    ...WRITES,
    factory: { version: 'Example (подставная фабрика)', commit: '0'.repeat(40), dirty: false },
    agents: [
      {
        agent: 'footage-indexer',
        path: 'agents/footage-indexer',
        rev: 'main',
        sha: '1'.repeat(40),
        head: '1'.repeat(40),
        branch: 'main',
        ok: true,
        why: null,
      },
    ],
    agents_error: null,
    ...API_PROCESS.fresh,
    center: {
      version: '0.0.0',
      built: true,
      built_at: '2026-10-10T00:00:00Z',
      dist: 'frontend/dist',
    },
  },
  session: { token: SESSION_TOKEN, header: 'X-CC-Session' },
} satisfies {
  health: Schemas['Health'];
  version: Schemas['Version'];
  session: Schemas['Session'];
};

/**
 * CC-0155: ответ `GET /api/version` в сценарии процесса API (`API_PROCESS`). На старом коде у
 * фабрики уже другой коммит, чем тот, на котором запущен API.
 */
export function versionAnswer(scenario: keyof typeof API_PROCESS): Schemas['Version'] {
  const v = { ...fixtures.version, ...API_PROCESS[scenario] };
  return scenario === 'stale'
    ? { ...v, factory: { ...v.factory, commit: API_FACTORY_COMMIT_NOW } }
    : v;
}
