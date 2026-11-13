// Подставные «Версии и агенты» (`GET /api/versions`, CC-0030 / CC-0119 фабрики; экран — CC-0031).
// Общий для Vitest (MSW, src/mocks/handlers.ts), Playwright (tests/e2e/fixtures.ts) и тренировки
// (src/training/demo.ts). Импорты — относительные.
//
// Как у живой фабрики 14.10: на `main` выпуск v2.3.4 (README — «2.3»), в работе `release/2.4`;
// пять агентов из `agents.lock.json`, центр 0.3.1 модулем `frontend`. По умолчанию — расхождение:
// content-researcher стоит на ветке release/2.4 вместо пина v2.3, у video-editor два изменённых
// файла. Ручки теста (`state`): `drift` (false — все на пинах), `inWork` (ветки выпусков с рабочей
// копией; [] — ничего не в работе), `rootLines` (замечания проверки вне агентов: битая ссылка),
// `lockError` (лок не прочитан — строк нет), `centerOff` (центр собран не из пина), `refuse` (500 —
// API не ответил), `calls` (пути запросов). Каждый `?fresh=true` — новая проверка (время +1 мин,
// `cached: false`); без него — сохранённый ответ (`cached: true` после первого).
import type { components } from '../api/schema.gen';

type S = components['schemas'];

export type VersionsReply =
  { status: 200; body: S['Versions'] } | { status: 500; body: { detail: string } };

/** Когда прошла первая проверка подставной фабрики. */
export const VERSIONS_CHECKED_AT = '2026-10-14T06:40:12Z';

const sha = (c: string) => c.repeat(40).slice(0, 40);
const MAIN = '4e2b7d19a03c55f8e6d1b2a9c07f3e8d5a61b4c2';

/**
 * Процесс cc-api в ответе `GET /api/version` (CC-0155, договор 0.70.0): когда запущен, на каком
 * коммите и не отстал ли от кода фабрики. `fresh` — в `fixtures.version` (коммит при запуске тот же,
 * что `factory.commit` подставной фабрики, `'0' × 40`); `stale` и `unknown` — подменой ответа:
 * `mockGet('/api/version', versionAnswer('stale'))` в Vitest, `page.route('**\/api/version', …)` с
 * тем же `versionAnswer` (src/mocks/fixtures.ts) в Playwright.
 */
export const API_STARTED_AT = '2026-10-21T22:15:07Z';
export const API_STALE_COMMIT = 'abc1234f5e6d7c8b9a0f1e2d3c4b5a6978695a4b';
/** Коммит фабрики «сейчас» в сценарии `stale`: корень ушёл вперёд от `API_STALE_COMMIT`. */
export const API_FACTORY_COMMIT_NOW = '5c9cb3a7e41d8f02b6a9d3c5e7f1048a2b6d9e3f';
export const API_STALE_PATHS = [
  'api/cc_api/versions.py',
  'shared/agents_lock.py',
  'agents.lock.json',
] as const;

export const API_PROCESS = {
  fresh: {
    started_at: API_STARTED_AT,
    commit_at_start: '0'.repeat(40),
    stale: false,
    stale_paths: [],
  },
  stale: {
    started_at: API_STARTED_AT,
    commit_at_start: API_STALE_COMMIT,
    stale: true,
    stale_paths: [...API_STALE_PATHS],
  },
  unknown: {
    started_at: API_STARTED_AT,
    commit_at_start: null,
    stale: null,
    stale_paths: null,
  },
} satisfies Record<
  string,
  Pick<S['Version'], 'started_at' | 'commit_at_start' | 'stale' | 'stale_paths'>
>;

/** Пины `agents.lock.json` живой фабрики. */
export const PINS = [
  ['compliance-checker', 'v2.3', sha('c1')],
  ['content-researcher', 'v2.3', sha('d2')],
  ['footage-indexer', 'v2.3.2', sha('f3')],
  ['trend-hunter', 'v2.3', sha('a4')],
  ['video-editor', 'v2.3.2', sha('e5')],
] as const;

/** Строка `scripts/agents status` как её печатает фабрика (`agents_lock.py`). */
function cliLine(
  mark: 'ok' | 'DIFF' | 'WARN',
  path: string,
  rev: string,
  head: string | null,
  at: string,
  why: string | null,
) {
  const m = mark === 'ok' ? 'ok  ' : mark;
  return `${m} ${path.padEnd(28)} ${rev.padEnd(12)} ${(head ?? '-').slice(0, 12).padEnd(12)} ${at.padEnd(10)} ${why ?? ''}`.trimEnd();
}

type Row = Omit<S['AgentState'], 'line' | 'mark'>;

function agentRows(drift: boolean): Row[] {
  return PINS.map(([agent, rev, pin]) => {
    const row: Row = {
      agent,
      path: `agents/${agent}`,
      rev,
      sha: pin,
      head: pin,
      branch: null,
      dirty: [],
      ok: true,
      why: null,
    };
    if (!drift) return row;
    if (agent === 'content-researcher') {
      const head = sha('7b');
      return {
        ...row,
        head,
        branch: 'release/2.4',
        ok: false,
        why: `HEAD ${head.slice(0, 12)} (release/2.4) is not ${rev} ${pin.slice(0, 12)}`,
      };
    }
    if (agent === 'video-editor') {
      const dirty = ['render/src/Quote.tsx', 'render/package.json'];
      return {
        ...row,
        dirty,
        ok: false,
        why: `${dirty.length} uncommitted tracked file(s) (${dirty.join(', ')})`,
      };
    }
    return row;
  });
}

export type VersionsState = {
  drift: boolean;
  inWork: string[];
  rootLines: boolean;
  lockError: string | null;
  centerOff: boolean;
  refuse: boolean;
  checks: number;
  calls: string[];
};

export function createVersionsBackend() {
  const state: VersionsState = {
    drift: true,
    inWork: ['release/2.4'],
    rootLines: false,
    lockError: null,
    centerOff: false,
    refuse: false,
    checks: 0,
    calls: [],
  };

  function answer(fresh: boolean): S['Versions'] {
    const cached = !fresh && state.checks > 0;
    if (!cached) state.checks += 1;
    const at = new Date(Date.parse(VERSIONS_CHECKED_AT) + (state.checks - 1) * 60_000)
      .toISOString()
      .replace('.000Z', 'Z');
    const rows = state.lockError ? [] : agentRows(state.drift);
    const lines: S['StatusLine'][] = [];
    const agents: S['AgentState'][] = rows.map((r) => {
      const mark = r.ok ? 'ok' : 'DIFF';
      const text = cliLine(mark, r.path, r.rev, r.head, r.branch ?? 'detached', r.why);
      lines.push({ text, mark, of: 'agent', subject: r.agent });
      return { ...r, line: text, mark };
    });
    const centerSha = sha('0f');
    const centerHead = state.centerOff ? sha('9a') : centerSha;
    const modules: S['ModuleState'][] = state.lockError
      ? []
      : [
          (() => {
            const why = state.centerOff
              ? `HEAD ${centerHead.slice(0, 12)} (detached) is not v0.3.1 ${centerSha.slice(0, 12)}`
              : null;
            const mark = state.centerOff ? 'WARN' : 'ok';
            const text = cliLine(mark, 'frontend', 'v0.3.1', centerHead, 'detached', why);
            lines.push({ text, mark, of: 'module', subject: 'frontend' });
            return {
              module: 'frontend',
              path: 'frontend',
              rev: 'v0.3.1',
              sha: centerSha,
              head: centerHead,
              branch: null,
              dirty: [],
              built: !state.centerOff,
              api: true,
              ok: !state.centerOff,
              why,
              build: {
                rev: 'v0.3.1',
                sha: centerSha,
                contract: 'api/openapi.json',
                contract_sha256: '1060d98913481f9b82312bb8e29f74625f8e038ec4c8e48f4a9c3de987db3c27',
                built_by: 'scripts/agents sync',
              },
              line: text,
              mark,
            };
          })(),
        ];
    if (state.rootLines && !state.lockError)
      lines.push({
        text: 'DIFF shared/inserts/example-tech/hook-07.mp4 -> ../../../shared/inserts/example-tech/hook-07.mp4: its target is missing (CF-0584)',
        mark: 'DIFF',
        of: 'root',
        subject: null,
      });
    const diff = !state.lockError && (rows.some((r) => !r.ok) || state.rootLines);
    return {
      checked_at: at,
      cached,
      ttl_s: 30,
      api: '0.58.0',
      factory: {
        version: '2.3',
        git: true,
        commit: MAIN,
        branch: 'main',
        main: MAIN,
        dirty: [],
        branch_ok: true,
        release_tag: 'v2.3.4',
        versions_in_work: [...state.inWork],
      },
      lock: { path: 'agents.lock.json', error: state.lockError },
      agents,
      modules,
      status: {
        command: 'scripts/agents status',
        exit_code: state.lockError ? 2 : diff ? 1 : 0,
        ok: !state.lockError && !diff,
        lines: state.lockError ? [] : lines,
        stderr: state.lockError ? `agents status: ${state.lockError}` : null,
        error: null,
      },
      center: {
        version: '0.3.1',
        built: true,
        built_at: '2026-10-13T18:05:41Z',
        dist: 'frontend/dist',
      },
    };
  }

  return {
    state,
    answer,
    /** Всё на пинах, без замечаний. */
    clean() {
      state.drift = false;
      state.rootLines = false;
    },
  };
}

export type VersionsBackend = ReturnType<typeof createVersionsBackend>;

/** Ответ на `GET /api/versions[?fresh=true]`; другой путь — null (не наш). */
export function routeVersions(b: VersionsBackend, method: string, url: URL): VersionsReply | null {
  if (method !== 'GET' || !url.pathname.endsWith('/api/versions')) return null;
  b.state.calls.push(`${url.pathname}${url.search}`);
  if (b.state.refuse) return { status: 500, body: { detail: 'Internal Server Error' } };
  return { status: 200, body: b.answer(url.searchParams.get('fresh') === 'true') };
}
