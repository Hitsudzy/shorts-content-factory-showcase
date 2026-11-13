/// <reference types="vitest/config" />
import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig, loadEnv, type Plugin } from 'vite';

import { checkContract, contractStamp } from './scripts/api-contract.ts';
import { lazyProblems, type BundleInfo } from './scripts/lazy-chunks.ts';
import { testWorkers } from './scripts/test-workers.ts';
import { TEST_TIMEOUT_MS } from './src/test/timeouts.ts';

// Адрес API фабрики для dev-сервера и `vite preview`: запросы на `/api` проксируются туда.
// В собранном приложении API живёт на том же origin (FastAPI фабрики раздаёт `dist/`),
// поэтому клиент всегда ходит на относительный `<base>api/…`, а адрес нужен только прокси.
const DEFAULT_API_URL = 'http://127.0.0.1:8790';

// CC-0004: сборка сверяет типы API с контрактом фабрики (scripts/api-contract.ts) и
// падает при расхождении, а в `dist/contract.json` пишет, под какой контракт собрана.
// Только для `vite build` — dev-сервер и Vitest контракт не трогают.
function apiContract(): Plugin {
  let stamp = '';
  return {
    name: 'cc-api-contract',
    apply: 'build',
    async buildStart() {
      const r = await checkContract();
      for (const w of r.warnings) this.warn(w);
      if (!r.ok) this.error(r.errors.join('\n'));
      stamp = contractStamp(r);
    },
    generateBundle() {
      this.emitFile({ type: 'asset', fileName: 'contract.json', source: stamp });
    },
  };
}

// CC-0073: демо-код тренировки — только в ленивых кусках; иначе сборка падает.
function trainingLazy(): Plugin {
  return {
    name: 'cc-training-lazy',
    apply: 'build',
    generateBundle(_options, bundle) {
      const info: BundleInfo = {};
      for (const [name, c] of Object.entries(bundle)) {
        info[name] =
          c.type === 'chunk'
            ? {
                type: 'chunk',
                fileName: c.fileName,
                isEntry: c.isEntry,
                imports: c.imports,
                dynamicImports: c.dynamicImports,
                moduleIds: c.moduleIds ?? Object.keys(c.modules ?? {}),
              }
            : { type: 'asset', fileName: c.fileName };
      }
      const problems = lazyProblems(info);
      if (problems.length) this.error(problems.join('\n'));
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), ''), ...process.env };
  const apiUrl = env.CC_API_URL || DEFAULT_API_URL;
  // Базовый путь, под которым раздаётся приложение (например `/cc/`). По умолчанию — корень.
  const base = env.CC_BASE_PATH || '/';
  const apiPrefix = `${base.replace(/\/$/, '')}/api`;

  const proxy = { [apiPrefix]: { target: apiUrl, changeOrigin: true } };

  return {
    base,
    plugins: [react(), tailwindcss(), apiContract(), trainingLazy()],
    resolve: {
      alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
    },
    server: { host: '127.0.0.1', port: 5173, strictPort: true, proxy },
    preview: { host: '127.0.0.1', port: 4173, strictPort: true, proxy },
    build: {
      outDir: 'dist',
      emptyOutDir: true,
      // Самый большой кусок — демо-сервер тренировки (MSW и подставной API, ~560 КБ): он ленивый
      // и грузится только во вкладке в тренировке (проверка — trainingLazy выше).
      chunkSizeWarningLimit: 600,
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: ['./src/test/setup.ts'],
      include: ['src/**/*.test.{ts,tsx}', 'scripts/**/*.test.ts'],
      css: false,
      // CC-0042: под нагрузкой машины — длиннее штатных 5 с, но конечно (потолок findBy — setup.ts),
      // и не на всех ядрах сразу: половина, или CC_TEST_WORKERS (scripts/test-workers.ts).
      testTimeout: TEST_TIMEOUT_MS,
      hookTimeout: TEST_TIMEOUT_MS,
      maxWorkers: testWorkers(),
    },
  };
});
